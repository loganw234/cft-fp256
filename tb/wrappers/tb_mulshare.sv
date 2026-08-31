// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_mulshare: the same four banks, twice, differing only in where the
// significand product comes from.
//
//   *_int   lanes with EXT_MUL=0 - each builds its own multiplier, the
//           arrangement that has passed 111,278 vectors
//   *_shr   lanes with EXT_MUL=1 - all of them fed by ONE cft_mulfrac
//
// Both halves see identical inputs on the same cycle, and the bench
// asserts their outputs are equal bit for bit, flags included. That is
// the whole claim the fused array has to earn, checked directly rather
// than inferred from two separate comparisons against the model.
//
// This wrapper is also the prototype of the engine change: the
// packing, the mode mux and the product distribution here are what
// cft_engine_stream will do once the equivalence holds.

`timescale 1ns/1ps

module tb_mulshare #(
    parameter int LATENCY = 15
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic [1:0]   mode,        // 0 fp32, 1 fp64, 2 fp128, 3 fp256
    input  logic         in_valid,
    input  logic [2:0]   rnd,
    input  logic [255:0] a_beat,
    input  logic [255:0] b_beat,
    input  logic [255:0] c_beat,
    output logic         out_valid,
    output logic [255:0] d_int,
    output logic [255:0] d_shr,
    output logic [4:0]   f_int,
    output logic [4:0]   f_shr
);

  localparam int PMAX = 237;
  localparam int MCH  = 27;
  localparam int ACCW = 2 * PMAX + 2 * MCH;

  localparam logic [1:0] M32 = 2'd0, M64 = 2'd1, M128 = 2'd2, M256 = 2'd3;

  // ---- the shared array ---------------------------------------------
  logic [PMAX-1:0] mf_a, mf_b;
  logic [ACCW-1:0] mf_p;

  cft_mulfrac #(.PMAX(PMAX), .MCH(MCH), .SLOTS(16)) u_mulfrac (
      .clk(clk), .mode(mode), .in_valid(in_valid),
      .a(mf_a), .b(mf_b), .out_valid(), .p(mf_p));

  // ---- per-format lane arrays ---------------------------------------
  // Significands out of the shared lanes, packed for the array.
  logic [23:0]  a32_s  [0:7], b32_s  [0:7];
  logic [52:0]  a64_s  [0:3], b64_s  [0:3];
  logic [112:0] a128_s [0:1], b128_s [0:1];
  logic [236:0] a256_s, b256_s;

  logic [255:0] d32_i, d32_s, d64_i, d64_s, d128_i, d128_s, d256_i, d256_s;
  logic [4:0]   f32_i, f32_s, f64_i, f64_s, f128_i, f128_s, f256_i, f256_s;
  logic [4:0]   f32_il [0:7], f32_sl [0:7];
  logic [4:0]   f64_il [0:3], f64_sl [0:3];
  logic [4:0]   f128_il [0:1], f128_sl [0:1];
  logic         v32_l [0:7];

  genvar gi;

  // ---- fp32: 8 lanes -------------------------------------------------
  generate
    for (gi = 0; gi < 8; gi = gi + 1) begin : g32
      logic [31:0] di, ds;
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY),
                       .EXT_MUL(1'b0)) u_int (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*32 +: 32]), .b(b_beat[gi*32 +: 32]),
          .c(c_beat[gi*32 +: 32]),
          .out_valid(v32_l[gi]), .d(di), .flags(f32_il[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY),
                       .EXT_MUL(1'b1)) u_shr (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*32 +: 32]), .b(b_beat[gi*32 +: 32]),
          .c(c_beat[gi*32 +: 32]),
          .out_valid(), .d(ds), .flags(f32_sl[gi]),
          .mul_a(a32_s[gi]), .mul_b(b32_s[gi]),
          .mul_p(mf_p[gi*48 +: 48]),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      assign d32_i[gi*32 +: 32] = di;
      assign d32_s[gi*32 +: 32] = ds;
    end
  endgenerate

  // ---- fp64: 4 lanes -------------------------------------------------
  generate
    for (gi = 0; gi < 4; gi = gi + 1) begin : g64
      logic [63:0] di, ds;
      cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY),
                       .EXT_MUL(1'b0)) u_int (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*64 +: 64]), .b(b_beat[gi*64 +: 64]),
          .c(c_beat[gi*64 +: 64]),
          .out_valid(), .d(di), .flags(f64_il[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY),
                       .EXT_MUL(1'b1)) u_shr (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*64 +: 64]), .b(b_beat[gi*64 +: 64]),
          .c(c_beat[gi*64 +: 64]),
          .out_valid(), .d(ds), .flags(f64_sl[gi]),
          .mul_a(a64_s[gi]), .mul_b(b64_s[gi]),
          .mul_p(mf_p[gi*106 +: 106]),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      assign d64_i[gi*64 +: 64] = di;
      assign d64_s[gi*64 +: 64] = ds;
    end
  endgenerate

  // ---- fp128: 2 lanes ------------------------------------------------
  generate
    for (gi = 0; gi < 2; gi = gi + 1) begin : g128
      logic [127:0] di, ds;
      cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY),
                       .EXT_MUL(1'b0)) u_int (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*128 +: 128]), .b(b_beat[gi*128 +: 128]),
          .c(c_beat[gi*128 +: 128]),
          .out_valid(), .d(di), .flags(f128_il[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY),
                       .EXT_MUL(1'b1)) u_shr (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*128 +: 128]), .b(b_beat[gi*128 +: 128]),
          .c(c_beat[gi*128 +: 128]),
          .out_valid(), .d(ds), .flags(f128_sl[gi]),
          .mul_a(a128_s[gi]), .mul_b(b128_s[gi]),
          .mul_p(mf_p[gi*226 +: 226]),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      assign d128_i[gi*128 +: 128] = di;
      assign d128_s[gi*128 +: 128] = ds;
    end
  endgenerate

  // ---- fp256: 1 lane -------------------------------------------------
  cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY),
                   .EXT_MUL(1'b0)) u_int256 (
      .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
      .byp(1'b0), .byp_d('0), .byp_f('0),
      .a(a_beat), .b(b_beat), .c(c_beat),
      .out_valid(), .d(d256_i), .flags(f256_i),
      .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
  cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY),
                   .EXT_MUL(1'b1)) u_shr256 (
      .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
      .byp(1'b0), .byp_d('0), .byp_f('0),
      .a(a_beat), .b(b_beat), .c(c_beat),
      .out_valid(), .d(d256_s), .flags(f256_s),
      .mul_a(a256_s), .mul_b(b256_s), .mul_p(mf_p[0 +: 474]),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));

  // ---- pack the active format's significands for the array ----------
  //
  // Only one precision is live at a time, so one array serves whichever
  // bank is selected; the others get whatever falls out and their
  // results are discarded. This mux is exactly what the engine will do.
  always_comb begin
    mf_a = '0;
    mf_b = '0;
    case (mode)
      M32: for (int i = 0; i < 8; i = i + 1) begin
             mf_a[i*24 +: 24] = a32_s[i];
             mf_b[i*24 +: 24] = b32_s[i];
           end
      M64: for (int i = 0; i < 4; i = i + 1) begin
             mf_a[i*53 +: 53] = a64_s[i];
             mf_b[i*53 +: 53] = b64_s[i];
           end
      M128: for (int i = 0; i < 2; i = i + 1) begin
             mf_a[i*113 +: 113] = a128_s[i];
             mf_b[i*113 +: 113] = b128_s[i];
           end
      default: begin
             mf_a = a256_s;
             mf_b = b256_s;
           end
    endcase
  end

  // ---- flag reduction and result selection --------------------------
  always_comb begin
    f32_i = 5'b0; f32_s = 5'b0;
    for (int i = 0; i < 8; i = i + 1) begin
      f32_i = f32_i | f32_il[i];
      f32_s = f32_s | f32_sl[i];
    end
    f64_i = 5'b0; f64_s = 5'b0;
    for (int i = 0; i < 4; i = i + 1) begin
      f64_i = f64_i | f64_il[i];
      f64_s = f64_s | f64_sl[i];
    end
    f128_i = 5'b0; f128_s = 5'b0;
    for (int i = 0; i < 2; i = i + 1) begin
      f128_i = f128_i | f128_il[i];
      f128_s = f128_s | f128_sl[i];
    end
  end

  always_comb begin
    case (mode)
      M32:     begin d_int = d32_i;  d_shr = d32_s;  f_int = f32_i;  f_shr = f32_s;  end
      M64:     begin d_int = d64_i;  d_shr = d64_s;  f_int = f64_i;  f_shr = f64_s;  end
      M128:    begin d_int = d128_i; d_shr = d128_s; f_int = f128_i; f_shr = f128_s; end
      default: begin d_int = d256_i; d_shr = d256_s; f_int = f256_i; f_shr = f256_s; end
    endcase
  end

  // Every lane has the same fixed latency, so any one of them dates the
  // whole beat.
  assign out_valid = v32_l[0];

endmodule
