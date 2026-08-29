// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_engine: v0 vector engine. Streams three operand arrays A, B, C
// from HBM through the compute banks and writes D = op(A, B, C) back,
// one 256-bit beat at a time.
//
// Datapath geometry: the beat IS the tile's compute width - 256 bits,
// which is 8 fp32 lanes or 1 fp256 operand, selected per run by
// cfg_prec (0 = fp32x8, 3 = fp256; 1 and 2 are reserved for the
// fp64/fp128 rungs of the fractured array, v1). Elements per beat:
// fp32 -> 8, fp256 -> 1. v0 requires N to be a whole number of beats
// (host contract; see docs/ARCHITECTURE.md). 256 bits is also the
// native width of an HBM pseudo-channel, so no width converter sits
// between the kernel and memory - in hardware or in emulation, where
// a 512-bit master demonstrably lost write payloads through the
// 2022-era platform's converter models (see docs/BRINGUP.md).
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
    parameter int LATENCY = 15
) (
    input  logic         ap_clk,
    input  logic         ap_rst_n,

    // control (cft_csr)
    input  logic         start,
    output logic         busy,
    output logic         done,
    output logic [4:0]   flags_acc,
    input  logic [3:0]   cfg_op,
    input  logic [3:0]   cfg_prec,
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
    output logic [255:0] m00_axi_wdata,
    output logic [31:0]  m00_axi_wstrb,
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
    input  logic [255:0] m00_axi_rdata,
    input  logic [1:0]   m00_axi_rresp,
    input  logic         m00_axi_rlast,
    input  logic         m00_axi_rvalid,
    output logic         m00_axi_rready
);

  localparam logic [3:0] PREC_FP32  = 4'd0;
  localparam logic [3:0] PREC_FP256 = 4'd3;

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
  logic [255:0] abuf, bbuf, cbuf, dbuf;
  logic         is_wide;
  logic         captured;

  // constant AXI attributes
  assign m00_axi_awid    = 1'b0;
  assign m00_axi_awlen   = 8'd0;      // one beat per burst
  assign m00_axi_awsize  = 3'd5;      // 32 bytes
  assign m00_axi_awburst = 2'd1;      // INCR
  assign m00_axi_awlock  = 1'b0;
  assign m00_axi_awcache = 4'b0011;
  assign m00_axi_awprot  = 3'b000;
  assign m00_axi_awqos   = 4'd0;
  assign m00_axi_arid    = 1'b0;
  assign m00_axi_arlen   = 8'd0;
  assign m00_axi_arsize  = 3'd5;
  assign m00_axi_arburst = 2'd1;
  assign m00_axi_arlock  = 1'b0;
  assign m00_axi_arcache = 4'b0011;
  assign m00_axi_arprot  = 3'b000;
  assign m00_axi_arqos   = 4'd0;
  assign m00_axi_wstrb   = {32{1'b1}};
  assign m00_axi_wlast   = 1'b1;

  assign m00_axi_arvalid = (state == S_AR_A) || (state == S_AR_B) || (state == S_AR_C);
  assign m00_axi_araddr  = (state == S_AR_A) ? (cfg_a + (beat_idx << 5)) :
                           (state == S_AR_B) ? (cfg_b + (beat_idx << 5)) :
                                               (cfg_c + (beat_idx << 5));
  assign m00_axi_rready  = (state == S_R_A) || (state == S_R_B) || (state == S_R_C);
  assign m00_axi_awvalid = (state == S_AW);
  assign m00_axi_awaddr  = cfg_d + (beat_idx << 5);
  assign m00_axi_wvalid  = (state == S_W);
  assign m00_axi_wdata   = dbuf;
  assign m00_axi_bready  = (state == S_B);

  assign busy = (state != S_IDLE);

  // ---- compute banks ------------------------------------------------
  logic ex_valid;
  assign ex_valid = (state == S_EX);

  // 8 x fp32 lanes
  logic [255:0] d32;
  logic [4:0]   f32_l [0:7];
  logic [4:0]   f32_or;
  genvar gi;
  generate
    for (gi = 0; gi < 8; gi = gi + 1) begin : g_lane32
      logic [31:0] sa, sb, sc, fa, fb, fc, dd;
      assign sa = abuf[gi*32 +: 32];
      assign sb = bbuf[gi*32 +: 32];
      assign sc = cbuf[gi*32 +: 32];
      cft_opmux #(.EXP_W(8), .MAN_W(23)) u_mux (
          .op(cfg_op[1:0]), .a(sa), .b(sb), .c(sc),
          .fa(fa), .fb(fb), .fc(fc));
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY)) u_fma (
          .clk(ap_clk), .rst_n(ap_rst_n),
          .in_valid(ex_valid && !is_wide),
          .a(fa), .b(fb), .c(fc),
          .out_valid(), .d(dd), .flags(f32_l[gi]));
      assign d32[gi*32 +: 32] = dd;
    end
  endgenerate
  always_comb begin
    f32_or = 5'b0;
    for (int i = 0; i < 8; i = i + 1) f32_or = f32_or | f32_l[i];
  end

  // 1 x fp256 unit
  logic [255:0] w_fa, w_fb, w_fc, d256;
  logic [4:0]   f256;
  cft_opmux #(.EXP_W(19), .MAN_W(236)) u_wmux (
      .op(cfg_op[1:0]), .a(abuf), .b(bbuf), .c(cbuf),
      .fa(w_fa), .fb(w_fb), .fc(w_fc));
  cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY)) u_wfma (
      .clk(ap_clk), .rst_n(ap_rst_n),
      .in_valid(ex_valid && is_wide),
      .a(w_fa), .b(w_fb), .c(w_fc),
      .out_valid(), .d(d256), .flags(f256));

  logic [255:0] beat_d;
  logic [4:0]   beat_f;
  assign beat_d = is_wide ? d256 : d32;
  assign beat_f = is_wide ? f256 : f32_or;

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
      is_wide <= 1'b0;
    end else begin
      done <= 1'b0;

      // delay line runs unconditionally; capture on emergence
      vdl <= {vdl[LATENCY-2:0], ex_valid};
      if (vdl[LATENCY-1]) begin
        dbuf <= beat_d;
        flags_acc <= flags_acc | beat_f;
        captured <= 1'b1;
        // synthesis translate_off
        $display("[CFT-ENG] beat%0d EXQ wide=%b d[127:0]=0x%h flags=%b", beat_idx, is_wide, beat_d[127:0], beat_f);
        // synthesis translate_on
      end

      case (state)
        S_IDLE: begin
          if (start) begin
            // synthesis translate_off
            $display("[CFT-ENG] START op=%0d prec=%0d n=%0d a=0x%h b=0x%h c=0x%h d=0x%h",
                     cfg_op, cfg_prec, cfg_n, cfg_a, cfg_b, cfg_c, cfg_d);
            // synthesis translate_on
            is_wide <= (cfg_prec == PREC_FP256);
            beats_total <= (cfg_prec == PREC_FP256) ? cfg_n : (cfg_n >> 3);
            beat_idx <= '0;
            flags_acc <= 5'b0;
            if (((cfg_prec == PREC_FP256) ? cfg_n : (cfg_n >> 3)) == 0) begin
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
