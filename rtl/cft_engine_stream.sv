// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_engine_stream: the v1 streaming vector engine. Same CSR
// contract, same compute banks, same delay-line collection and the
// same determinism argument as cft_engine (the naive reference
// engine, which stays in rtl/ as readable spec) - the difference is
// pure microarchitecture:
//
//   - reads are AXI INCR bursts (up to 2^BURST_LOG2 beats, 4KB-
//     boundary safe) into three per-stream FIFOs, streams arbitrated
//     a > b > c with one AR outstanding at a time;
//   - compute issues one beat per cycle whenever all three operand
//     FIFOs are non-empty and the result FIFO has room for
//     everything already in flight;
//   - results collect through the latency-matched delay line into
//     the D FIFO and drain as write bursts.
//
// Read, compute and write all overlap across beats. Element order is
// still total: beats are popped in index order by the single issue
// point and written in index order by the single writer, so the
// determinism contract is untouched - flags remain an order-free OR.
//
// Steady-state cost on the shared 256-bit port is 4 transfers per
// beat (3 reads + 1 write), so the engine is port-bound rather than
// handshake-bound: ~5 cycles/beat with burst-amortized latency,
// versus ~40 for the naive engine. The next knobs (multiple
// outstanding ARs, per-stream HBM pseudo-channels, multiple CUs) are
// roadmap items; none of them change numerics.

`timescale 1ns/1ps

module cft_engine_stream #(
    parameter int LATENCY    = 15,
    parameter bit EN_FP64    = 1'b1,
    parameter bit EN_FP128   = 1'b1,
    parameter bit EN_FP256   = 1'b1,
    parameter int BEAT_BITS  = 256,
    parameter int BURST_LOG2 = 4,   // max beats per AXI burst
    parameter int FIFO_LOG2  = 5    // per-stream buffer depth (beats)
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


  localparam int BURST_MAX = 1 << BURST_LOG2;
  localparam int FDEPTH    = 1 << FIFO_LOG2;

  // The writer starts a burst only once the result FIFO holds the
  // whole burst, so a burst longer than the FIFO can never start and
  // the engine would deadlock with beats still outstanding. Equality
  // is legal but degenerate (writes could only begin with the FIFO
  // completely full, stalling read and compute for the whole burst),
  // so demand real headroom.
  // Generate scope AND initial, for the reason cft_fpfma_pipe's guards
  // spell out: Yosys and Vivado honour the elaboration-time $error and
  // ignore `initial`, Icarus is the reverse, so one form alone leaves
  // some toolchain able to build a deadlocking design.
  generate
    if (BURST_MAX >= FDEPTH) begin : g_burst_exceeds_fifo
      $error("cft_engine_stream: BURST_LOG2 must be less than FIFO_LOG2");
    end
  endgenerate

  initial begin
    if (BURST_MAX >= FDEPTH) begin
      $display("FATAL: cft_engine_stream needs BURST_LOG2 (%0d) < FIFO_LOG2 (%0d)",
               BURST_LOG2, FIFO_LOG2);
      $fatal(1);
    end
  end

  // sticky bus faults, reported through the STATUS CSR
  localparam int ERR_RRESP = 0;
  localparam int ERR_BRESP = 1;
  localparam int ERR_RLEN  = 2;

  // constant AXI attributes
  assign m00_axi_awid    = 1'b0;
  assign m00_axi_awsize  = ADDR_SH[2:0];   // log2(BEAT_BYTES)
  assign m00_axi_awburst = 2'd1;      // INCR
  assign m00_axi_awlock  = 1'b0;
  assign m00_axi_awcache = 4'b0011;
  assign m00_axi_awprot  = 3'b000;
  assign m00_axi_awqos   = 4'd0;
  assign m00_axi_arid    = 1'b0;
  assign m00_axi_arsize  = ADDR_SH[2:0];
  assign m00_axi_arburst = 2'd1;
  assign m00_axi_arlock  = 1'b0;
  assign m00_axi_arcache = 4'b0011;
  assign m00_axi_arprot  = 3'b000;
  assign m00_axi_arqos   = 4'd0;
  assign m00_axi_wstrb   = {BEAT_BYTES{1'b1}};

  // ---- run control ---------------------------------------------------
  logic         running;
  logic [1:0]   prec_r;
  logic [7:0]   op_r;
  logic [2:0]   rnd_r;
  logic [63:0]  beats_total;
  logic [63:0]  base_a, base_b, base_c, base_d;

  logic [63:0] beats_new;
  assign beats_new = cfg_n >> (LANE_SH - cfg_prec[1:0]);

  logic start_accept, fifo_clear, wfinish;
  assign start_accept = start && !running;
  assign fifo_clear   = start_accept;
  assign busy = running;

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      running <= 1'b0;
      done <= 1'b0;
      prec_r <= 2'd0;
      op_r <= 8'd0;
      rnd_r <= 3'd0;
      beats_total <= '0;
      base_a <= '0; base_b <= '0; base_c <= '0; base_d <= '0;
    end else begin
      done <= 1'b0;
      if (start_accept) begin
        // synthesis translate_off
        $display("[CFT-ENGS] START op=%0d prec=%0d n=%0d beats=%0d a=0x%h b=0x%h c=0x%h d=0x%h",
                 cfg_op, cfg_prec, cfg_n, beats_new, cfg_a, cfg_b, cfg_c, cfg_d);
        // synthesis translate_on
        // Everything the run depends on is snapshot here. op and rnd
        // used to be read combinationally, which meant a MODE write
        // landing mid-run changed the arithmetic partway through the
        // array - and the split point depended on memory timing, so
        // the same host program could produce different bits on
        // different runs. That is the exact failure this design
        // exists to rule out.
        prec_r <= cfg_prec[1:0];
        op_r   <= cfg_op;
        rnd_r  <= cfg_rnd;
        beats_total <= beats_new;
        base_a <= cfg_a; base_b <= cfg_b; base_c <= cfg_c; base_d <= cfg_d;
        if (beats_new == 0) done <= 1'b1;
        else running <= 1'b1;
      end
      if (wfinish) begin
        running <= 1'b0;
        done <= 1'b1;
      end
    end
  end
  // flags_acc lives in its own block at the end of the module, after
  // beat_f exists

  // ---- stream FIFOs --------------------------------------------------
  logic         a_wr, b_wr, c_wr, abc_rd, d_wr, d_rd;
  logic [BEAT_BITS-1:0] a_q, b_q, c_q, d_qout;
  logic [FIFO_LOG2:0] a_cnt, b_cnt, c_cnt, d_cnt;

  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_a (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(a_wr), .wr_data(m00_axi_rdata),
      .rd_en(abc_rd), .rd_data(a_q), .count(a_cnt));
  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_b (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(b_wr), .wr_data(m00_axi_rdata),
      .rd_en(abc_rd), .rd_data(b_q), .count(b_cnt));
  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_c (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(c_wr), .wr_data(m00_axi_rdata),
      .rd_en(abc_rd), .rd_data(c_q), .count(c_cnt));

  // ---- reader: one AR outstanding, streams arbitrated a > b > c ------
  localparam logic [1:0] R_IDLE = 2'd0, R_AR = 2'd1, R_DATA = 2'd2;

  logic [1:0]  rd_state, cur_s;
  logic [63:0] rd_issued0, rd_issued1, rd_issued2;
  logic [7:0]  ar_len, r_beats;

  logic [63:0] rem0, rem1, rem2, addr0, addr1, addr2;
  assign rem0 = beats_total - rd_issued0;
  assign rem1 = beats_total - rd_issued1;
  assign rem2 = beats_total - rd_issued2;
  assign addr0 = base_a + (rd_issued0 << ADDR_SH);
  assign addr1 = base_b + (rd_issued1 << ADDR_SH);
  assign addr2 = base_c + (rd_issued2 << ADDR_SH);

  // beats this burst may cover: min(BURST_MAX, remaining, beats to the
  // 4KB AXI boundary, FIFO free space). Addresses are 32B-aligned by
  // the host contract, so the boundary term is never zero.
  function automatic logic [7:0] burst_len(
      input logic [63:0] rem,
      input logic [63:0] addr,
      input logic [FIFO_LOG2:0] cnt);
    logic [63:0] bound, free, l;
    begin
      bound = (64'd4096 - {52'd0, addr[11:0]}) >> 5;
      free  = FDEPTH - {{(63-FIFO_LOG2){1'b0}}, cnt};
      l = BURST_MAX;
      if (rem   < l) l = rem;
      if (bound < l) l = bound;
      if (free  < l) l = free;
      burst_len = l[7:0];
    end
  endfunction

  logic [7:0] len0, len1, len2;
  always_comb begin
    len0 = burst_len(rem0, addr0, a_cnt);
    len1 = burst_len(rem1, addr1, b_cnt);
    len2 = burst_len(rem2, addr2, c_cnt);
  end

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      rd_state <= R_IDLE;
      cur_s <= 2'd0;
      rd_issued0 <= '0; rd_issued1 <= '0; rd_issued2 <= '0;
      ar_len <= 8'd0;
      r_beats <= 8'd0;
    end else if (!running) begin
      rd_state <= R_IDLE;
      rd_issued0 <= '0; rd_issued1 <= '0; rd_issued2 <= '0;
      r_beats <= 8'd0;
    end else begin
      case (rd_state)
        R_IDLE: begin
          if (len0 != 0) begin
            cur_s <= 2'd0; ar_len <= len0; rd_state <= R_AR;
          end else if (len1 != 0) begin
            cur_s <= 2'd1; ar_len <= len1; rd_state <= R_AR;
          end else if (len2 != 0) begin
            cur_s <= 2'd2; ar_len <= len2; rd_state <= R_AR;
          end
        end
        R_AR: if (m00_axi_arready) begin
          rd_state <= R_DATA;
          r_beats <= 8'd0;
          // synthesis translate_off
          $display("[CFT-ENGS] AR s=%0d addr=0x%h len=%0d", cur_s, m00_axi_araddr, ar_len);
          // synthesis translate_on
        end
        R_DATA: if (m00_axi_rvalid) begin
          r_beats <= r_beats + 8'd1;
          if (m00_axi_rlast) begin
            case (cur_s)
              2'd0: rd_issued0 <= rd_issued0 + {56'd0, ar_len};
              2'd1: rd_issued1 <= rd_issued1 + {56'd0, ar_len};
              default: rd_issued2 <= rd_issued2 + {56'd0, ar_len};
            endcase
            rd_state <= R_IDLE;
          end
        end
        default: rd_state <= R_IDLE;
      endcase
    end
  end

  assign m00_axi_arvalid = (rd_state == R_AR);
  assign m00_axi_araddr  = (cur_s == 2'd0) ? addr0 :
                           (cur_s == 2'd1) ? addr1 : addr2;
  assign m00_axi_arlen   = ar_len - 8'd1;
  assign m00_axi_rready  = (rd_state == R_DATA);

  assign a_wr = (rd_state == R_DATA) && m00_axi_rvalid && (cur_s == 2'd0);
  assign b_wr = (rd_state == R_DATA) && m00_axi_rvalid && (cur_s == 2'd1);
  assign c_wr = (rd_state == R_DATA) && m00_axi_rvalid && (cur_s == 2'd2);

  // ---- compute issue and collection ----------------------------------
  logic [63:0] issued_beats;
  logic [7:0]  inflight;
  logic        ex_valid, collect;

  assign ex_valid = running && (issued_beats < beats_total) &&
                    (a_cnt != 0) && (b_cnt != 0) && (c_cnt != 0) &&
                    ((d_cnt + inflight) < FDEPTH);
  assign abc_rd = ex_valid;

  logic [LATENCY-1:0] vdl;
  assign collect = vdl[LATENCY-1];

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      issued_beats <= '0;
      inflight <= 8'd0;
      vdl <= '0;
    end else if (!running) begin
      issued_beats <= '0;
      inflight <= 8'd0;
      vdl <= {vdl[LATENCY-2:0], 1'b0};
    end else begin
      vdl <= {vdl[LATENCY-2:0], ex_valid};
      if (ex_valid) issued_beats <= issued_beats + 64'd1;
      inflight <= inflight + (ex_valid ? 8'd1 : 8'd0) - (collect ? 8'd1 : 8'd0);
    end
  end

  assign d_wr = collect;

  // ---- compute banks (identical structure to cft_engine) -------------
  // 8 x fp32 lanes
  logic [BEAT_BITS-1:0] d32;
  logic [4:0]   f32_l [0:LANES32-1];
  logic [4:0]   f32_or;
  genvar gi;
  generate
    for (gi = 0; gi < LANES32; gi = gi + 1) begin : g_lane32
      logic [31:0] sa, sb, sc, fa, fb, fc, dd;
      assign sa = a_q[gi*32 +: 32];
      assign sb = b_q[gi*32 +: 32];
      assign sc = c_q[gi*32 +: 32];
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
          .out_valid(), .d(dd), .flags(f32_l[gi]));
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
        assign sa = a_q[gi*64 +: 64];
        assign sb = b_q[gi*64 +: 64];
        assign sc = c_q[gi*64 +: 64];
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
            .out_valid(), .d(dd), .flags(f64_l[gi]));
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
        assign sa = a_q[gi*128 +: 128];
        assign sb = b_q[gi*128 +: 128];
        assign sc = c_q[gi*128 +: 128];
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
            .out_valid(), .d(dd), .flags(f128_l[gi]));
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
          .op(op_r), .a(a_q), .b(b_q), .c(c_q),
          .fa(w_fa), .fb(w_fb), .fc(w_fc));
      logic bv; logic [255:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(19), .MAN_W(236)) u_simple (
          .op(op_r), .a(a_q), .b(b_q), .c(c_q),
          .valid(bv), .d(bd), .flags(bf));
      cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY)) u_wfma (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(ex_valid && (prec_r == PREC_FP256)),
          .rnd(rnd_r), .byp(bv), .byp_d(bd), .byp_f(bf),
          .a(w_fa), .b(w_fb), .c(w_fc),
          .out_valid(), .d(d256), .flags(f256));
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

  cft_fifo #(.WIDTH(256), .DEPTH_LOG2(FIFO_LOG2)) u_fifo_d (
      .clk(ap_clk), .rst_n(ap_rst_n), .clear(fifo_clear),
      .wr_en(d_wr), .wr_data(beat_d),
      .rd_en(d_rd), .rd_data(d_qout), .count(d_cnt));

  // ---- writer: index-order bursts from the D FIFO --------------------
  localparam logic [1:0] W_IDLE = 2'd0, W_AW = 2'd1, W_DATA = 2'd2, W_B = 2'd3;

  logic [1:0]  wr_state;
  logic [63:0] wr_done;
  logic [7:0]  w_len, w_cnt;

  logic [63:0] rem_w, addr_w;
  assign rem_w  = beats_total - wr_done;
  assign addr_w = base_d + (wr_done << ADDR_SH);

  // target burst: full-size when possible; the tail is always fully
  // buffered by the time rem_w is what is left, so d_cnt >= target
  // holds without a special drain case.
  logic [7:0] w_target;
  always_comb begin
    logic [63:0] bound, l;
    bound = (64'd4096 - {52'd0, addr_w[11:0]}) >> 5;
    l = BURST_MAX;
    if (rem_w < l) l = rem_w;
    if (bound < l) l = bound;
    w_target = l[7:0];
  end

  logic w_go;
  assign w_go = running && (w_target != 8'd0) && (d_cnt >= w_target);

  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      wr_state <= W_IDLE;
      wr_done <= '0;
      w_len <= 8'd0;
      w_cnt <= 8'd0;
    end else if (!running) begin
      wr_state <= W_IDLE;
      wr_done <= '0;
    end else begin
      case (wr_state)
        W_IDLE: if (w_go) begin
          w_len <= w_target;
          w_cnt <= 8'd0;
          wr_state <= W_AW;
        end
        W_AW: if (m00_axi_awready) begin
          wr_state <= W_DATA;
          // synthesis translate_off
          $display("[CFT-ENGS] AW addr=0x%h len=%0d", m00_axi_awaddr, w_len);
          // synthesis translate_on
        end
        W_DATA: if (m00_axi_wvalid && m00_axi_wready) begin
          w_cnt <= w_cnt + 8'd1;
          if (w_cnt + 8'd1 == w_len) wr_state <= W_B;
        end
        W_B: if (m00_axi_bvalid) begin
          wr_done <= wr_done + {56'd0, w_len};
          wr_state <= W_IDLE;
        end
        default: wr_state <= W_IDLE;
      endcase
    end
  end

  assign m00_axi_awvalid = (wr_state == W_AW);
  assign m00_axi_awaddr  = addr_w;
  assign m00_axi_awlen   = w_len - 8'd1;
  assign m00_axi_wvalid  = (wr_state == W_DATA) && (d_cnt != 0);
  assign m00_axi_wdata   = d_qout;
  assign m00_axi_wlast   = (w_cnt == w_len - 8'd1);
  assign d_rd            = m00_axi_wvalid && m00_axi_wready;
  assign m00_axi_bready  = (wr_state == W_B);

  assign wfinish = (wr_state == W_B) && m00_axi_bvalid &&
                   ((wr_done + {56'd0, w_len}) == beats_total);

  // ---- sticky bus faults ---------------------------------------------
  //
  // The memory system's own verdict on the data this run consumed and
  // produced. Without it a DECERR on an out-of-range pointer is
  // indistinguishable from success: the engine would compute on
  // whatever the interconnect drove, write it out, and report done
  // with clean IEEE flags. A determinism claim that cannot tell
  // "these are the bits" from "the memory never answered" is not
  // worth much, so a run ending with STATUS non-zero is a run whose
  // output must be discarded.
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n) begin
      err_acc <= 3'b0;
    end else if (start_accept) begin
      err_acc <= 3'b0;
    end else begin
      if ((rd_state == R_DATA) && m00_axi_rvalid && (m00_axi_rresp != 2'b00))
        err_acc[ERR_RRESP] <= 1'b1;
      if ((wr_state == W_B) && m00_axi_bvalid && (m00_axi_bresp != 2'b00))
        err_acc[ERR_BRESP] <= 1'b1;
      // RLAST must land on exactly the beat ARLEN asked for. A short
      // burst would otherwise starve compute forever and a long one
      // would overrun an unguarded FIFO - both silent hangs today.
      if ((rd_state == R_DATA) && m00_axi_rvalid &&
          (m00_axi_rlast != (r_beats == ar_len - 8'd1)))
        err_acc[ERR_RLEN] <= 1'b1;
    end
  end

  // ---- sticky flags --------------------------------------------------
  always_ff @(posedge ap_clk) begin
    if (!ap_rst_n)          flags_acc <= 5'b0;
    else if (start_accept)  flags_acc <= 5'b0;
    else if (collect) begin
      flags_acc <= flags_acc | beat_f;
      // synthesis translate_off
      $display("[CFT-ENGS] EXQ prec=%0d d[127:0]=0x%h flags=%b", prec_r, beat_d[127:0], beat_f);
      // synthesis translate_on
    end
  end

endmodule
