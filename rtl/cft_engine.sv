// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_engine: v0 vector engine. Streams three operand arrays A, B, C
// from HBM through the compute banks and writes D = op(A, B, C) back,
// one 256-bit beat at a time.
//
// Datapath geometry: the beat IS the tile's compute width - 256 bits,
// carrying 8 fp32 / 4 fp64 / 2 fp128 lanes or 1 fp256 operand,
// selected per run by cfg_prec (0..3 = the PREC_CODE ladder). All
// four rungs share the one beat, the one delay line, and the one
// flags rail; only the lane slicing differs. N must be a whole
// number of beats (host contract; see docs/ARCHITECTURE.md). The
// EN_FP64/EN_FP128/EN_FP256 parameters let a trimmed tile (open-core
// conformance nodes, docs/ROADMAP.md) drop banks it cannot fit; what
// remains is advertised in the CAPS CSR and behaves identically.
// 256 bits is also the native width of an HBM pseudo-channel, so no
// width converter sits between the kernel and memory - in hardware or
// in emulation, where a 512-bit master demonstrably lost write
// payloads through the 2022-era platform's converter models (see
// docs/BRINGUP.md).
//
// Determinism: element i of D depends only on element i of A, B, C and
// the op - there is no cross-element arithmetic in v0, so ordering
// questions cannot arise. The flags CSR is the OR of all per-element
// flag sets, which is order-independent by construction. When the v2
// reduction ops land, their tree order is fixed by element index, per
// the contract, never by arrival time.
//
// AXI: single-ID, single-outstanding, one beat per burst (ARLEN=0).
// Deliberately naive - correctness and auditability first; the v1
// engine adds bursts and outstanding transactions behind the same
// CSR contract without touching numerics.

`timescale 1ns/1ps

module cft_engine #(
    parameter int LATENCY  = 15,
    parameter bit EN_FP64  = 1'b1,
    parameter bit EN_FP128 = 1'b1,
    parameter bit EN_FP256 = 1'b1,
    parameter int BEAT_BITS = 256
) (
    input  logic         ap_clk,
    input  logic         ap_rst_n,

    // control (cft_csr)
    input  logic         start,
    output logic         busy,
    output logic         done,
    output logic [4:0]   flags_acc,
    output logic [2:0]   err_acc,
    input  logic [7:0]   cfg_op,
    input  logic [3:0]   cfg_prec,
    input  logic [2:0]   cfg_rnd,
    input  logic [63:0]  cfg_n,
    input  logic [63:0]  cfg_a,
    input  logic [63:0]  cfg_b,
    input  logic [63:0]  cfg_c,
    input  logic [63:0]  cfg_d,

    // AXI4 master (m00_axi)
    output logic [0:0]   m00_axi_awid,
    output logic [63:0]  m00_axi_awaddr,
    output logic [7:0]   m00_axi_awlen,
    output logic [2:0]   m00_axi_awsize,
    output logic [1:0]   m00_axi_awburst,
    output logic         m00_axi_awlock,
    output logic [3:0]   m00_axi_awcache,
    output logic [2:0]   m00_axi_awprot,
    output logic [3:0]   m00_axi_awqos,
    output logic         m00_axi_awvalid,
    input  logic         m00_axi_awready,
    output logic [BEAT_BITS-1:0] m00_axi_wdata,
    output logic [BEAT_BITS/8-1:0] m00_axi_wstrb,
    output logic         m00_axi_wlast,
    output logic         m00_axi_wvalid,
    input  logic         m00_axi_wready,
    input  logic [0:0]   m00_axi_bid,
    input  logic [1:0]   m00_axi_bresp,
    input  logic         m00_axi_bvalid,
    output logic         m00_axi_bready,
    output logic [0:0]   m00_axi_arid,
    output logic [63:0]  m00_axi_araddr,
    output logic [7:0]   m00_axi_arlen,
    output logic [2:0]   m00_axi_arsize,
    output logic [1:0]   m00_axi_arburst,
    output logic         m00_axi_arlock,
    output logic [3:0]   m00_axi_arcache,
    output logic [2:0]   m00_axi_arprot,
    output logic [3:0]   m00_axi_arqos,
    output logic         m00_axi_arvalid,
    input  logic         m00_axi_arready,
    input  logic [0:0]   m00_axi_rid,
    input  logic [BEAT_BITS-1:0] m00_axi_rdata,
    input  logic [1:0]   m00_axi_rresp,
    input  logic         m00_axi_rlast,
    input  logic         m00_axi_rvalid,
    output logic         m00_axi_rready
);

  localparam logic [1:0] PREC_FP32  = 2'd0;
  localparam logic [1:0] PREC_FP64  = 2'd1;
  localparam logic [1:0] PREC_FP128 = 2'd2;
  localparam logic [1:0] PREC_FP256 = 2'd3;

  // ---- beat geometry -------------------------------------------------
  //
  // BEAT_BITS is the ONE parameter here. Lane counts are not
  // independent knobs: a beat holds BEAT_BITS/width elements of each
  // format, so 256 bits gives 8/4/2/1 and narrowing the beat narrows
  // every bank together. That is the honest shape of the thing - the
  // beat is the tile's compute width AND its memory width, and the two
  // cannot disagree without a width converter, which is exactly what
  // this design refuses to have.
  //
  // A format wider than the beat would need multi-beat elements and an
  // assembly buffer; rather than pretend, the guards below refuse the
  // configuration. So narrowing the beat means dropping the wide rungs
  // with it: BEAT_BITS=64 with fp32+fp64 only is a quarter-tile that
  // fits an Alchitry Au (docs/ROADMAP.md's conformance node), and a
  // 130nm chiplet that wants area back for deposition buffering makes
  // the same trade.
  //
  // 256 is correct for the Alveo path and should stay there: it is the
  // native width of an HBM pseudo-channel, which is why no width
  // converter sits between kernel and memory.
  localparam int BEAT_BYTES = BEAT_BITS / 8;
  localparam int ADDR_SH    = $clog2(BEAT_BYTES);   // byte address step
  localparam int LANE_SH    = $clog2(BEAT_BITS / 32);
  localparam int LANES32    = BEAT_BITS / 32;
  localparam int LANES64    = (BEAT_BITS >= 64)  ? BEAT_BITS / 64  : 0;
  localparam int LANES128   = (BEAT_BITS >= 128) ? BEAT_BITS / 128 : 0;
  localparam int LANES256   = (BEAT_BITS >= 256) ? BEAT_BITS / 256 : 0;

  generate
    if (BEAT_BITS != (1 << ADDR_SH) * 8)
      $error("BEAT_BITS must be a power of two");
    if (BEAT_BITS < 32)
      $error("BEAT_BITS must hold at least one fp32 element");
    if (EN_FP64 && BEAT_BITS < 64)
      $error("EN_FP64 needs BEAT_BITS >= 64");
    if (EN_FP128 && BEAT_BITS < 128)
      $error("EN_FP128 needs BEAT_BITS >= 128");
    if (EN_FP256 && BEAT_BITS < 256)
      $error("EN_FP256 needs BEAT_BITS >= 256");
    // Upper bound, deliberately. This parameterization exists to make
    // the tile SMALLER - a quarter-tile for an open-core conformance
    // node, or a chiplet trading lanes for deposition buffer. Going
    // wider than 256 would put two fp256 elements in a beat, and the
    // fp256 bank is a single instance rather than a generate loop, so
    // it would silently compute only the low one. Refuse instead.
    // (256 is also the native HBM pseudo-channel width, and a 512-bit
    // master demonstrably lost write payloads through this platform's
    // emulation models - see docs/BRINGUP.md.)
    if (BEAT_BITS > 256)
      $error("BEAT_BITS > 256 needs the fp256 bank to become a loop");
  endgenerate


  // ---- FSM ----------------------------------------------------------
  localparam int S_IDLE  = 0;
  localparam int S_AR_A  = 1;
  localparam int S_R_A   = 2;
  localparam int S_AR_B  = 3;
  localparam int S_R_B   = 4;
  localparam int S_AR_C  = 5;
  localparam int S_R_C   = 6;
  localparam int S_EX    = 7;
  localparam int S_DRAIN = 8;
  localparam int S_AW    = 9;
  localparam int S_W     = 10;
  localparam int S_B     = 11;
  localparam int S_NEXT  = 12;
  localparam int S_DONE  = 13;

  logic [3:0]   state;
  logic [63:0]  beats_total, beat_idx;
  logic [BEAT_BITS-1:0] abuf, bbuf, cbuf, dbuf;
  logic [1:0]   prec_r;
  logic [7:0]   op_r;
  logic [2:0]   rnd_r;
  logic [63:0]  base_a, base_b, base_c, base_d;
  logic         captured;

  // elements per beat = 8 >> prec, so beats = n >> (3 - prec)
  logic [63:0] beats_new;
  assign beats_new = cfg_n >> (LANE_SH - cfg_prec[1:0]);

  // constant AXI attributes
  assign m00_axi_awid    = 1'b0;
  assign m00_axi_awlen   = 8'd0;      // one beat per burst
  assign m00_axi_awsize  = ADDR_SH[2:0];   // log2(BEAT_BYTES)
  assign m00_axi_awburst = 2'd1;      // INCR
  assign m00_axi_awlock  = 1'b0;
  assign m00_axi_awcache = 4'b0011;
  assign m00_axi_awprot  = 3'b000;
  assign m00_axi_awqos   = 4'd0;
  assign m00_axi_arid    = 1'b0;
  assign m00_axi_arlen   = 8'd0;
  assign m00_axi_arsize  = ADDR_SH[2:0];
  assign m00_axi_arburst = 2'd1;
  assign m00_axi_arlock  = 1'b0;
  assign m00_axi_arcache = 4'b0011;
  assign m00_axi_arprot  = 3'b000;
  assign m00_axi_arqos   = 4'd0;
  assign m00_axi_wstrb   = {BEAT_BYTES{1'b1}};
  assign m00_axi_wlast   = 1'b1;

  assign m00_axi_arvalid = (state == S_AR_A) || (state == S_AR_B) || (state == S_AR_C);
  // Addresses come from the per-run snapshot, never from the live CSR
  // outputs: AXI requires ARADDR/AWADDR to be stable from VALID until
  // READY, and a pointer written mid-run would otherwise change an
  // address while VALID is asserted.
  assign m00_axi_araddr  = (state == S_AR_A) ? (base_a + (beat_idx << ADDR_SH)) :
                           (state == S_AR_B) ? (base_b + (beat_idx << ADDR_SH)) :
                                               (base_c + (beat_idx << ADDR_SH));
  assign m00_axi_rready  = (state == S_R_A) || (state == S_R_B) || (state == S_R_C);
  assign m00_axi_awvalid = (state == S_AW);
  assign m00_axi_awaddr  = base_d + (beat_idx << ADDR_SH);
  assign m00_axi_wvalid  = (state == S_W);
  assign m00_axi_wdata   = dbuf;
  assign m00_axi_bready  = (state == S_B);

  assign busy = (state != S_IDLE);

  // ---- compute banks ------------------------------------------------
  logic ex_valid;
  assign ex_valid = (state == S_EX);

  // 8 x fp32 lanes
  logic [BEAT_BITS-1:0] d32;
  logic [4:0]   f32_l [0:LANES32-1];
  logic [4:0]   f32_or;
  genvar gi;
  generate
    for (gi = 0; gi < LANES32; gi = gi + 1) begin : g_lane32
      logic [31:0] sa, sb, sc, fa, fb, fc, dd;
      assign sa = abuf[gi*32 +: 32];
      assign sb = bbuf[gi*32 +: 32];
      assign sc = cbuf[gi*32 +: 32];
      cft_opmux #(.EXP_W(8), .MAN_W(23)) u_mux (
          .op(op_r), .a(sa), .b(sb), .c(sc),
          .fa(fa), .fb(fb), .fc(fc));
      logic bv; logic [31:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(8), .MAN_W(23)) u_simple (
          .op(op_r), .a(sa), .b(sb), .c(sc),
          .valid(bv), .d(bd), .flags(bf));
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY)) u_fma (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(ex_valid && (prec_r == PREC_FP32)),
          .rnd(rnd_r), .byp(bv), .byp_d(bd), .byp_f(bf),
          .a(fa), .b(fb), .c(fc),
          .out_valid(), .d(dd), .flags(f32_l[gi]),
          // EXT_MUL is left at its default here, so the lane builds its
          // own multiplier and these three are inert. They still have to
          // be NAMED. This engine is the uninstantiated readable
          // reference, so when cft_fpfma_pipe grew the shared-multiplier
          // port it was never updated - Icarus tolerates a missing pin
          // and nothing else read this file. Verilator makes it fatal,
          // which is why `make SIM=verilator sim` has never run despite
          // being advertised at the top of tb/Makefile.
          .mul_a(), .mul_b(), .mul_p('0));
      assign d32[gi*32 +: 32] = dd;
    end
  endgenerate
  always_comb begin
    f32_or = 5'b0;
    for (int i = 0; i < LANES32; i = i + 1) f32_or = f32_or | f32_l[i];
  end

  // 4 x fp64 lanes
  logic [BEAT_BITS-1:0] d64;
  logic [4:0]   f64_or;
  generate
    if (EN_FP64 && LANES64 > 0) begin : g_bank64
      logic [4:0] f64_l [0:LANES64-1];
      for (gi = 0; gi < LANES64; gi = gi + 1) begin : g_lane64
        logic [63:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = abuf[gi*64 +: 64];
        assign sb = bbuf[gi*64 +: 64];
        assign sc = cbuf[gi*64 +: 64];
        cft_opmux #(.EXP_W(11), .MAN_W(52)) u_mux (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [63:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(11), .MAN_W(52)) u_simple (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY)) u_fma (
            .clk(ap_clk), .rst_n(ap_rst_n),
            .in_valid(ex_valid && (prec_r == PREC_FP64)),
          .rnd(rnd_r), .byp(bv), .byp_d(bd), .byp_f(bf),
            .a(fa), .b(fb), .c(fc),
            .out_valid(), .d(dd), .flags(f64_l[gi]),
            .mul_a(), .mul_b(), .mul_p('0));
        assign d64[gi*64 +: 64] = dd;
      end
      always_comb begin
        f64_or = 5'b0;
        for (int i = 0; i < LANES64; i = i + 1) f64_or = f64_or | f64_l[i];
      end
    end else begin : g_bank64_off
      assign d64 = '0;
      assign f64_or = 5'b0;
    end
  endgenerate

  // 2 x fp128 lanes
  logic [BEAT_BITS-1:0] d128;
  logic [4:0]   f128_or;
  generate
    if (EN_FP128 && LANES128 > 0) begin : g_bank128
      logic [4:0] f128_l [0:LANES128-1];
      for (gi = 0; gi < LANES128; gi = gi + 1) begin : g_lane128
        logic [127:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = abuf[gi*128 +: 128];
        assign sb = bbuf[gi*128 +: 128];
        assign sc = cbuf[gi*128 +: 128];
        cft_opmux #(.EXP_W(15), .MAN_W(112)) u_mux (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [127:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(15), .MAN_W(112)) u_simple (
            .op(op_r), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY)) u_fma (
            .clk(ap_clk), .rst_n(ap_rst_n),
            .in_valid(ex_valid && (prec_r == PREC_FP128)),
          .rnd(rnd_r), .byp(bv), .byp_d(bd), .byp_f(bf),
            .a(fa), .b(fb), .c(fc),
            .out_valid(), .d(dd), .flags(f128_l[gi]),
            .mul_a(), .mul_b(), .mul_p('0));
        assign d128[gi*128 +: 128] = dd;
      end
      always_comb begin
        f128_or = 5'b0;
        for (int i = 0; i < LANES128; i = i + 1) f128_or = f128_or | f128_l[i];
      end
    end else begin : g_bank128_off
      assign d128 = '0;
      assign f128_or = 5'b0;
    end
  endgenerate

  // 1 x fp256 unit
  logic [BEAT_BITS-1:0] d256;
  logic [4:0]   f256;
  generate
    if (EN_FP256 && LANES256 > 0) begin : g_bank256
      logic [BEAT_BITS-1:0] w_fa, w_fb, w_fc;
      cft_opmux #(.EXP_W(19), .MAN_W(236)) u_wmux (
          .op(op_r), .a(abuf), .b(bbuf), .c(cbuf),
          .fa(w_fa), .fb(w_fb), .fc(w_fc));
      logic bv; logic [255:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(19), .MAN_W(236)) u_simple (
          .op(op_r), .a(abuf), .b(bbuf), .c(cbuf),
          .valid(bv), .d(bd), .flags(bf));
      cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY)) u_wfma (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(ex_valid && (prec_r == PREC_FP256)),
          .rnd(rnd_r), .byp(bv), .byp_d(bd), .byp_f(bf),
          .a(w_fa), .b(w_fb), .c(w_fc),
          .out_valid(), .d(d256), .flags(f256),
          .mul_a(), .mul_b(), .mul_p('0));
    end else begin : g_bank256_off
      assign d256 = '0;
      assign f256 = 5'b0;
    end
  endgenerate

  logic [BEAT_BITS-1:0] beat_d;
  logic [4:0]   beat_f;
  always_comb begin
    beat_d = d32;
    beat_f = f32_or;
    case (prec_r)
      PREC_FP64:  begin beat_d = d64;  beat_f = f64_or;  end
      PREC_FP128: begin beat_d = d128; beat_f = f128_or; end
      PREC_FP256: begin beat_d = d256; beat_f = f256;    end
      default: ;  // PREC_FP32 falls through to the defaults
    endcase
  end

  // issue delay line, matched to the banks' fixed latency
  logic [LATENCY-1:0] vdl;

  // ---- sequencing ----------------------------------------------------
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      state <= S_IDLE;
      done <= 1'b0;
      flags_acc <= 5'b0;
      vdl <= '0;
      captured <= 1'b0;
      beat_idx <= '0;
      beats_total <= '0;
      prec_r <= 2'd0;
      op_r <= 8'd0;
      rnd_r <= 3'd0;
      err_acc <= 3'b0;
      base_a <= '0; base_b <= '0; base_c <= '0; base_d <= '0;
    end else begin
      done <= 1'b0;

      // The memory system's verdict on this run's data (see the STATUS
      // CSR). ARLEN is always 0 here, so there is no burst-length
      // check to make - only the responses.
      if (m00_axi_rready && m00_axi_rvalid && (m00_axi_rresp != 2'b00))
        err_acc[0] <= 1'b1;
      if ((state == S_B) && m00_axi_bvalid && (m00_axi_bresp != 2'b00))
        err_acc[1] <= 1'b1;

      // delay line runs unconditionally; capture on emergence
      vdl <= {vdl[LATENCY-2:0], ex_valid};
      if (vdl[LATENCY-1]) begin
        dbuf <= beat_d;
        flags_acc <= flags_acc | beat_f;
        captured <= 1'b1;
        // synthesis translate_off
        $display("[CFT-ENG] beat%0d EXQ prec=%0d d[127:0]=0x%h flags=%b", beat_idx, prec_r, beat_d[127:0], beat_f);
        // synthesis translate_on
      end

      case (state)
        S_IDLE: begin
          if (start) begin
            // synthesis translate_off
            $display("[CFT-ENG] START op=%0d prec=%0d n=%0d a=0x%h b=0x%h c=0x%h d=0x%h",
                     cfg_op, cfg_prec, cfg_n, cfg_a, cfg_b, cfg_c, cfg_d);
            // synthesis translate_on
            prec_r <= cfg_prec[1:0];
            op_r   <= cfg_op;
            rnd_r  <= cfg_rnd;
            base_a <= cfg_a; base_b <= cfg_b;
            base_c <= cfg_c; base_d <= cfg_d;
            beats_total <= beats_new;
            beat_idx <= '0;
            flags_acc <= 5'b0;
            err_acc <= 3'b0;
            if (beats_new == 0) begin
              state <= S_DONE;
            end else begin
              state <= S_AR_A;
            end
          end
        end
        S_AR_A: if (m00_axi_arready) state <= S_R_A;
        S_R_A:  if (m00_axi_rvalid) begin
          abuf <= m00_axi_rdata; state <= S_AR_B;
          // synthesis translate_off
          $display("[CFT-ENG] beat%0d RA data[127:0]=0x%h", beat_idx, m00_axi_rdata[127:0]);
          // synthesis translate_on
        end
        S_AR_B: if (m00_axi_arready) state <= S_R_B;
        S_R_B:  if (m00_axi_rvalid) begin
          bbuf <= m00_axi_rdata; state <= S_AR_C;
          // synthesis translate_off
          $display("[CFT-ENG] beat%0d RB data[127:0]=0x%h", beat_idx, m00_axi_rdata[127:0]);
          // synthesis translate_on
        end
        S_AR_C: if (m00_axi_arready) state <= S_R_C;
        S_R_C:  if (m00_axi_rvalid) begin
          cbuf <= m00_axi_rdata; captured <= 1'b0; state <= S_EX;
          // synthesis translate_off
          $display("[CFT-ENG] beat%0d RC data[127:0]=0x%h", beat_idx, m00_axi_rdata[127:0]);
          // synthesis translate_on
        end
        S_EX:    state <= S_DRAIN;
        S_DRAIN: if (captured) state <= S_AW;
        S_AW:   if (m00_axi_awready) begin
          state <= S_W;
          // synthesis translate_off
          $display("[CFT-ENG] beat%0d AW addr=0x%h", beat_idx, m00_axi_awaddr);
          // synthesis translate_on
        end
        S_W:    if (m00_axi_wready) begin
          state <= S_B;
          // synthesis translate_off
          $display("[CFT-ENG] beat%0d W  data[127:0]=0x%h strb[15:0]=0x%h wlast=%b",
                   beat_idx, m00_axi_wdata[127:0], m00_axi_wstrb[15:0], m00_axi_wlast);
          // synthesis translate_on
        end
        S_B:    if (m00_axi_bvalid) begin
          state <= S_NEXT;
          // synthesis translate_off
          $display("[CFT-ENG] beat%0d B  resp=%b", beat_idx, m00_axi_bresp);
          // synthesis translate_on
        end
        S_NEXT: begin
          beat_idx <= beat_idx + 64'd1;
          if (beat_idx + 64'd1 >= beats_total) state <= S_DONE;
          else state <= S_AR_A;
        end
        S_DONE: begin
          done <= 1'b1;
          state <= S_IDLE;
        end
        default: state <= S_IDLE;
      endcase
    end
  end

endmodule
