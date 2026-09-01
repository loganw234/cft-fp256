// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_normshare: the same four banks, twice, differing only in where the
// normalised significand comes from.
//
//   *_int   lanes with EXT_NORM=0 - each builds its own two normalise
//           shifters, the arrangement every existing build uses
//   *_shr   lanes with EXT_NORM=1 - all of them fed by ONE cft_normseg
//
// Both halves see identical inputs on the same cycle, and the bench
// asserts their outputs are equal bit for bit, flags included. This is
// the claim the segmented ladder has to earn AT THE PIPE, not just in
// isolation: tb_normseg already proves the shifter shifts correctly,
// and what is new here is that a lane driven through the nrm_* ports
// produces the same FMA result as a lane that shifts for itself.
//
// The distinction matters because the two are different failure modes.
// A shifter bug shows up in tb_normseg. A PLUMBING bug - the value
// handed out a cycle early or late, the wrong half of the distance, a
// lane reading its neighbour's slice - does not, because tb_normseg
// drives the ladder directly and never goes through a pipe.
//
// Exactly as tb_mulshare does it: one shared resource serves whichever
// bank `mode` selects, the other three banks' shared halves receive
// nothing meaningful, and only the selected bank is compared. That is
// not a weakness of the bench - it is what the engine does, where
// prec_r is snapshot at start and one bank is live for the whole run.
//
// PACKING. Lane l of mode m occupies bits [l*(SLOTW<<m) +: NW_m] with
// SLOTW = 90, the uniform slot cft_normseg tiles. Getting this wrong is
// the plumbing bug most likely to survive review, so it is written once
// here and once in cft_engine_stream, and this bench is what says the
// two agree.

`timescale 1ns/1ps

module tb_normshare #(
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

  localparam logic [1:0] M32 = 2'd0, M64 = 2'd1, M128 = 2'd2, M256 = 2'd3;

  localparam int SLOTS = 8;
  localparam int SLOTW = 90;
  localparam int WT    = SLOTS * SLOTW;      // 720

  // NW = 3*MAN_W + 9, the pipe's own normalise window.
  localparam int NW32 = 78, NW64 = 165, NW128 = 345, NW256 = 717;
  // AW = 3*MAN_W + 8, the align window - one bit narrower.
  localparam int AW32 = 77, AW64 = 164, AW128 = 344, AW256 = 716;

  // ---- the shared ladder ---------------------------------------------
  // The amounts are packed at cft_normseg's per-lane pitch: lane l at
  // l*4 / l*6, direction at bit l.
  logic [WT-1:0]      nrm_din, nrm_dout;
  logic [SLOTS*4-1:0] nrm_csh;
  logic [SLOTS*6-1:0] nrm_fsh;

  cft_normseg #(.PMAX(237), .SLOTS(SLOTS)) u_normseg (
      .clk(clk), .mode(mode), .din(nrm_din),
      .csh(nrm_csh), .fsh(nrm_fsh), .dir('0), .dout(nrm_dout));

  // ---- the shared ALIGNER: the same ladder, bidirectional -----------
  logic [WT-1:0]      aln_din, aln_dout;
  logic [SLOTS*4-1:0] aln_csh;
  logic [SLOTS*6-1:0] aln_fsh;
  logic [SLOTS-1:0]   aln_dir;

  cft_normseg #(.PMAX(237), .SLOTS(SLOTS), .BIDIR(1'b1)) u_alnseg (
      .clk(clk), .mode(mode), .din(aln_din),
      .csh(aln_csh), .fsh(aln_fsh), .dir(aln_dir), .dout(aln_dout));

  logic [AW32-1:0]  av32  [0:7];
  logic [AW64-1:0]  av64  [0:3];
  logic [AW128-1:0] av128 [0:1];
  logic [AW256-1:0] av256;
  logic [3:0] ac32 [0:7], ac64 [0:3], ac128 [0:1], ac256;
  logic [5:0] af32 [0:7], af64 [0:3], af128 [0:1], af256;
  logic       ad32 [0:7], ad64 [0:3], ad128 [0:1], ad256;

  always_comb begin
    aln_din = '0;
    aln_csh = '0;
    aln_fsh = '0;
    aln_dir = '0;
    case (mode)
      M32: for (int i = 0; i < 8; i = i + 1) begin
             aln_din[i*SLOTW +: AW32] = av32[i];
             aln_csh[i*4 +: 4] = ac32[i];
             aln_fsh[i*6 +: 6] = af32[i];
             aln_dir[i] = ad32[i];
           end
      M64: for (int i = 0; i < 4; i = i + 1) begin
             aln_din[i*2*SLOTW +: AW64] = av64[i];
             aln_csh[i*4 +: 4] = ac64[i];
             aln_fsh[i*6 +: 6] = af64[i];
             aln_dir[i] = ad64[i];
           end
      M128: for (int i = 0; i < 2; i = i + 1) begin
             aln_din[i*4*SLOTW +: AW128] = av128[i];
             aln_csh[i*4 +: 4] = ac128[i];
             aln_fsh[i*6 +: 6] = af128[i];
             aln_dir[i] = ad128[i];
           end
      default: begin
             aln_din[0 +: AW256] = av256;
             aln_csh[0 +: 4] = ac256;
             aln_fsh[0 +: 6] = af256;
             aln_dir[0] = ad256;
           end
    endcase
  end

  // Per-lane exports from the shared halves, waiting to be packed.
  logic [NW32-1:0]  v32  [0:7];
  logic [NW64-1:0]  v64  [0:3];
  logic [NW128-1:0] v128 [0:1];
  logic [NW256-1:0] v256;
  logic [3:0] c32 [0:7], c64 [0:3], c128 [0:1], c256;
  logic [5:0] g32 [0:7], g64 [0:3], g128 [0:1], g256;

  always_comb begin
    nrm_din = '0;
    nrm_csh = '0;
    nrm_fsh = '0;
    case (mode)
      M32: for (int i = 0; i < 8; i = i + 1) begin
             nrm_din[i*SLOTW +: NW32] = v32[i];
             nrm_csh[i*4 +: 4] = c32[i];
             nrm_fsh[i*6 +: 6] = g32[i];
           end
      M64: for (int i = 0; i < 4; i = i + 1) begin
             nrm_din[i*2*SLOTW +: NW64] = v64[i];
             nrm_csh[i*4 +: 4] = c64[i];
             nrm_fsh[i*6 +: 6] = g64[i];
           end
      M128: for (int i = 0; i < 2; i = i + 1) begin
             nrm_din[i*4*SLOTW +: NW128] = v128[i];
             nrm_csh[i*4 +: 4] = c128[i];
             nrm_fsh[i*6 +: 6] = g128[i];
           end
      default: begin
             nrm_din[0 +: NW256] = v256;
             nrm_csh[0 +: 4] = c256;
             nrm_fsh[0 +: 6] = g256;
           end
    endcase
  end

  logic [255:0] d32_i, d32_s, d64_i, d64_s, d128_i, d128_s, d256_i, d256_s;
  logic [4:0]   f32_i, f32_s, f64_i, f64_s, f128_i, f128_s, f256_i, f256_s;
  logic [4:0]   f32_il [0:7], f32_sl [0:7];
  logic [4:0]   f64_il [0:3], f64_sl [0:3];
  logic [4:0]   f128_il [0:1], f128_sl [0:1];
  logic         v32_l [0:7];

  genvar gi;

  // ---- fp32: 8 lanes -------------------------------------------------
  generate
    for (gi = 0; gi < 8; gi = gi + 1) begin : g32b
      logic [31:0] di, ds;
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY)) u_int (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*32 +: 32]), .b(b_beat[gi*32 +: 32]),
          .c(c_beat[gi*32 +: 32]),
          .out_valid(v32_l[gi]), .d(di), .flags(f32_il[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY),
                       .EXT_NORM(1'b1), .EXT_ALIGN(1'b1)) u_shr (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*32 +: 32]), .b(b_beat[gi*32 +: 32]),
          .c(c_beat[gi*32 +: 32]),
          .out_valid(), .d(ds), .flags(f32_sl[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(v32[gi]), .nrm_csh(c32[gi]), .nrm_fsh(g32[gi]),
          .nrm_d(nrm_dout[gi*SLOTW +: NW32]),
          .aln_v(av32[gi]), .aln_csh(ac32[gi]), .aln_fsh(af32[gi]),
          .aln_dir(ad32[gi]), .aln_d(aln_dout[gi*SLOTW +: AW32]));
      assign d32_i[gi*32 +: 32] = di;
      assign d32_s[gi*32 +: 32] = ds;
    end
  endgenerate

  // ---- fp64: 4 lanes -------------------------------------------------
  generate
    for (gi = 0; gi < 4; gi = gi + 1) begin : g64b
      logic [63:0] di, ds;
      cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY)) u_int (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*64 +: 64]), .b(b_beat[gi*64 +: 64]),
          .c(c_beat[gi*64 +: 64]),
          .out_valid(), .d(di), .flags(f64_il[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY),
                       .EXT_NORM(1'b1), .EXT_ALIGN(1'b1)) u_shr (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*64 +: 64]), .b(b_beat[gi*64 +: 64]),
          .c(c_beat[gi*64 +: 64]),
          .out_valid(), .d(ds), .flags(f64_sl[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(v64[gi]), .nrm_csh(c64[gi]), .nrm_fsh(g64[gi]),
          .nrm_d(nrm_dout[gi*2*SLOTW +: NW64]),
          .aln_v(av64[gi]), .aln_csh(ac64[gi]), .aln_fsh(af64[gi]),
          .aln_dir(ad64[gi]), .aln_d(aln_dout[gi*2*SLOTW +: AW64]));
      assign d64_i[gi*64 +: 64] = di;
      assign d64_s[gi*64 +: 64] = ds;
    end
  endgenerate

  // ---- fp128: 2 lanes ------------------------------------------------
  generate
    for (gi = 0; gi < 2; gi = gi + 1) begin : g128b
      logic [127:0] di, ds;
      cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY)) u_int (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*128 +: 128]), .b(b_beat[gi*128 +: 128]),
          .c(c_beat[gi*128 +: 128]),
          .out_valid(), .d(di), .flags(f128_il[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY),
                       .EXT_NORM(1'b1), .EXT_ALIGN(1'b1)) u_shr (
          .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
          .byp(1'b0), .byp_d('0), .byp_f('0),
          .a(a_beat[gi*128 +: 128]), .b(b_beat[gi*128 +: 128]),
          .c(c_beat[gi*128 +: 128]),
          .out_valid(), .d(ds), .flags(f128_sl[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(v128[gi]), .nrm_csh(c128[gi]), .nrm_fsh(g128[gi]),
          .nrm_d(nrm_dout[gi*4*SLOTW +: NW128]),
          .aln_v(av128[gi]), .aln_csh(ac128[gi]), .aln_fsh(af128[gi]),
          .aln_dir(ad128[gi]), .aln_d(aln_dout[gi*4*SLOTW +: AW128]));
      assign d128_i[gi*128 +: 128] = di;
      assign d128_s[gi*128 +: 128] = ds;
    end
  endgenerate

  // ---- fp256: 1 lane -------------------------------------------------
  cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY)) u_int256 (
      .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
      .byp(1'b0), .byp_d('0), .byp_f('0),
      .a(a_beat), .b(b_beat), .c(c_beat),
      .out_valid(), .d(d256_i), .flags(f256_i),
      .mul_a(), .mul_b(), .mul_p('0),
      .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
  cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY),
                   .EXT_NORM(1'b1), .EXT_ALIGN(1'b1)) u_shr256 (
      .clk(clk), .rst_n(rst_n), .in_valid(in_valid), .rnd(rnd),
      .byp(1'b0), .byp_d('0), .byp_f('0),
      .a(a_beat), .b(b_beat), .c(c_beat),
      .out_valid(), .d(d256_s), .flags(f256_s),
      .mul_a(), .mul_b(), .mul_p('0),
      .nrm_v(v256), .nrm_csh(c256), .nrm_fsh(g256),
      .nrm_d(nrm_dout[0 +: NW256]),
      .aln_v(av256), .aln_csh(ac256), .aln_fsh(af256),
      .aln_dir(ad256), .aln_d(aln_dout[0 +: AW256]));

  // ---- flag reduction and output selection ---------------------------
  always_comb begin
    f32_i = '0; f32_s = '0;
    for (int i = 0; i < 8; i = i + 1) begin
      f32_i = f32_i | f32_il[i];
      f32_s = f32_s | f32_sl[i];
    end
    f64_i = '0; f64_s = '0;
    for (int i = 0; i < 4; i = i + 1) begin
      f64_i = f64_i | f64_il[i];
      f64_s = f64_s | f64_sl[i];
    end
    f128_i = '0; f128_s = '0;
    for (int i = 0; i < 2; i = i + 1) begin
      f128_i = f128_i | f128_il[i];
      f128_s = f128_s | f128_sl[i];
    end
  end

  assign out_valid = v32_l[0];

  always_comb begin
    case (mode)
      M32:     begin d_int = d32_i;  d_shr = d32_s;  f_int = f32_i;  f_shr = f32_s;  end
      M64:     begin d_int = d64_i;  d_shr = d64_s;  f_int = f64_i;  f_shr = f64_s;  end
      M128:    begin d_int = d128_i; d_shr = d128_s; f_int = f128_i; f_shr = f128_s; end
      default: begin d_int = d256_i; d_shr = d256_s; f_int = f256_i; f_shr = f256_s; end
    endcase
  end

endmodule
