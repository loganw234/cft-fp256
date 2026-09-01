// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_seq_lanes: the sequencer's beat-wide ALU array.
//
// One beat of lanes - 8x fp32 / 4x fp64 / 2x fp128 / 1x fp256 - each
// lane the SAME verified recipe cft_engine_stream instantiates:
// cft_opmux steering into cft_fpfma_pipe, with cft_simpleops and
// cft_seedop merged through the pipe's bypass sideband so every
// opcode has the same fixed latency and per-lane flags. That is P1 of
// docs/SEQUENCER.md made concrete: the sequencer introduces no
// arithmetic, only a schedule.
//
// A deliberate v1 deviation from SEQUENCER.md's sketch, recorded
// there too: the design document wants the sequencer to SHARE the
// engine's array instances, making P1 a fact about the netlist. This
// module instead instantiates the same source modules a second time.
// The engine's array is woven through 1,700 lines of streaming
// datapath with the optional fused ladders, and the tree it lives in
// is timing-closed and staged for card day - extracting a shared
// array is the right chiplet-era area work and the wrong week to do
// it. Same sources, same parameters, same bits; the area cost is one
// extra array on a part with room for it, and the extraction becomes
// mechanical once this module has a proven bench.
//
// Differences from the engine's banks, all subtractions:
//   * no reduction steering (the accumulator is the engine's);
//   * no fused-ladder externals (EXT_MUL/EXT_NORM/EXT_ALIGN all 0 -
//     the pipe's internal paths, the configuration every quarter-tile
//     build already uses and the equivalence campaign proved);
//   * op and rnd are PER-ISSUE inputs rather than per-run registers.
//     The pipe already carries the attribute alongside each operation
//     - that is what lets adjacent sequencer instructions round
//     differently, which interval arithmetic needs.
//
// Flags come out PER LANE, not OR-reduced: the sequencer masks each
// lane's contribution by its active bit (P3), so the reduction has to
// happen after masking, in cft_seq.

`timescale 1ns/1ps

module cft_seq_lanes #(
    parameter int BEAT_BITS = 256,
    parameter int LATENCY   = 15,
    parameter bit EN_FP64   = 1'b1,
    parameter bit EN_FP128  = 1'b1,
    parameter bit EN_FP256  = 1'b1
)(
    input  logic                 clk,
    input  logic                 rst_n,

    input  logic                 in_valid,
    input  logic [7:0]           op,     // opcode, sampled per issue
    input  logic [2:0]           rnd,    // 754 attribute, per issue
    input  logic [1:0]           prec,   // PREC_CODE; stable per run
    input  logic [BEAT_BITS-1:0] a,
    input  logic [BEAT_BITS-1:0] b,
    input  logic [BEAT_BITS-1:0] c,

    output logic                 out_valid,   // in_valid, LATENCY later
    output logic [BEAT_BITS-1:0] d,
    // Per-lane flags at the CURRENT precision, packed 5 bits per
    // lane position (bits [i*5 +: 5] are lane i's set); positions at
    // or beyond lanes_per_beat read zero. Packed because yosys's
    // frontend refuses unpacked-array ports, and the portability
    // lint gate is CI law here.
    output logic [BEAT_BITS/32*5-1:0] lane_flags
);

  localparam logic [1:0] PREC_FP32  = 2'd0;
  localparam logic [1:0] PREC_FP64  = 2'd1;
  localparam logic [1:0] PREC_FP128 = 2'd2;
  localparam logic [1:0] PREC_FP256 = 2'd3;

  localparam int LANES32  = BEAT_BITS / 32;
  localparam int LANES64  = BEAT_BITS / 64;
  localparam int LANES128 = BEAT_BITS / 128;
  localparam int LANES256 = BEAT_BITS / 256;

  // ---- validity delay line -------------------------------------------
  logic [LATENCY-1:0] v_sh;
  always_ff @(posedge clk) begin
    if (!rst_n)
      v_sh <= '0;
    else
      v_sh <= {v_sh[LATENCY-2:0], in_valid};
  end
  assign out_valid = v_sh[LATENCY-1];

  // ---- fp32 bank -----------------------------------------------------
  logic [BEAT_BITS-1:0] d32;
  logic [4:0] f32_l [0:LANES32-1];
  genvar gi;
  generate
    for (gi = 0; gi < LANES32; gi = gi + 1) begin : g_lane32
      logic [31:0] sa, sb, sc, fa, fb, fc, dd;
      assign sa = a[gi*32 +: 32];
      assign sb = b[gi*32 +: 32];
      assign sc = c[gi*32 +: 32];
      cft_opmux #(.EXP_W(8), .MAN_W(23)) u_mux (
          .op(op), .a(sa), .b(sb), .c(sc),
          .fa(fa), .fb(fb), .fc(fc));
      logic bv; logic [31:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(8), .MAN_W(23)) u_simple (
          .op(op), .a(sa), .b(sb), .c(sc),
          .valid(bv), .d(bd), .flags(bf));
      logic sev; logic [31:0] sed;
      cft_seedop #(.EXP_W(8), .MAN_W(23)) u_seed (
          .op(op), .a(sa), .valid(sev), .d(sed));
      logic bv_m; logic [31:0] bd_m; logic [4:0] bf_m;
      assign bv_m = bv | sev;
      assign bd_m = sev ? sed : bd;
      assign bf_m = sev ? 5'b0 : bf;
      cft_fpfma_pipe #(.EXP_W(8), .MAN_W(23), .LATENCY(LATENCY),
                       .EXT_MUL(1'b0), .EXT_NORM(1'b0), .EXT_ALIGN(1'b0))
        u_fma (
          .clk(clk), .rst_n(rst_n),
          .in_valid(in_valid && (prec == PREC_FP32)),
          .rnd(rnd),
          .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
          .a(fa), .b(fb), .c(fc),
          .out_valid(), .d(dd), .flags(f32_l[gi]),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      assign d32[gi*32 +: 32] = dd;
    end
  endgenerate

  // ---- fp64 bank -----------------------------------------------------
  logic [BEAT_BITS-1:0] d64;
  logic [4:0] f64_l [0:(LANES64 > 0 ? LANES64 : 1)-1];
  generate
    if (EN_FP64 && LANES64 > 0) begin : g_bank64
      for (gi = 0; gi < LANES64; gi = gi + 1) begin : g_lane64
        logic [63:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = a[gi*64 +: 64];
        assign sb = b[gi*64 +: 64];
        assign sc = c[gi*64 +: 64];
        cft_opmux #(.EXP_W(11), .MAN_W(52)) u_mux (
            .op(op), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [63:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(11), .MAN_W(52)) u_simple (
            .op(op), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        logic sev; logic [63:0] sed;
        cft_seedop #(.EXP_W(11), .MAN_W(52)) u_seed (
            .op(op), .a(sa), .valid(sev), .d(sed));
        logic bv_m; logic [63:0] bd_m; logic [4:0] bf_m;
        assign bv_m = bv | sev;
        assign bd_m = sev ? sed : bd;
        assign bf_m = sev ? 5'b0 : bf;
        cft_fpfma_pipe #(.EXP_W(11), .MAN_W(52), .LATENCY(LATENCY),
                         .EXT_MUL(1'b0), .EXT_NORM(1'b0), .EXT_ALIGN(1'b0))
          u_fma (
            .clk(clk), .rst_n(rst_n),
            .in_valid(in_valid && (prec == PREC_FP64)),
            .rnd(rnd),
            .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
            .a(fa), .b(fb), .c(fc),
            .out_valid(), .d(dd), .flags(f64_l[gi]),
            .mul_a(), .mul_b(), .mul_p('0),
            .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
            .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
        assign d64[gi*64 +: 64] = dd;
      end
    end else begin : g_no_bank64
      assign d64 = '0;
      always_comb
        for (int i = 0; i < (LANES64 > 0 ? LANES64 : 1); i = i + 1)
          f64_l[i] = '0;
    end
  endgenerate

  // ---- fp128 bank ----------------------------------------------------
  logic [BEAT_BITS-1:0] d128;
  logic [4:0] f128_l [0:(LANES128 > 0 ? LANES128 : 1)-1];
  generate
    if (EN_FP128 && LANES128 > 0) begin : g_bank128
      for (gi = 0; gi < LANES128; gi = gi + 1) begin : g_lane128
        logic [127:0] sa, sb, sc, fa, fb, fc, dd;
        assign sa = a[gi*128 +: 128];
        assign sb = b[gi*128 +: 128];
        assign sc = c[gi*128 +: 128];
        cft_opmux #(.EXP_W(15), .MAN_W(112)) u_mux (
            .op(op), .a(sa), .b(sb), .c(sc),
            .fa(fa), .fb(fb), .fc(fc));
        logic bv; logic [127:0] bd; logic [4:0] bf;
        cft_simpleops #(.EXP_W(15), .MAN_W(112)) u_simple (
            .op(op), .a(sa), .b(sb), .c(sc),
            .valid(bv), .d(bd), .flags(bf));
        logic sev; logic [127:0] sed;
        cft_seedop #(.EXP_W(15), .MAN_W(112)) u_seed (
            .op(op), .a(sa), .valid(sev), .d(sed));
        logic bv_m; logic [127:0] bd_m; logic [4:0] bf_m;
        assign bv_m = bv | sev;
        assign bd_m = sev ? sed : bd;
        assign bf_m = sev ? 5'b0 : bf;
        cft_fpfma_pipe #(.EXP_W(15), .MAN_W(112), .LATENCY(LATENCY),
                         .EXT_MUL(1'b0), .EXT_NORM(1'b0), .EXT_ALIGN(1'b0))
          u_fma (
            .clk(clk), .rst_n(rst_n),
            .in_valid(in_valid && (prec == PREC_FP128)),
            .rnd(rnd),
            .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
            .a(fa), .b(fb), .c(fc),
            .out_valid(), .d(dd), .flags(f128_l[gi]),
            .mul_a(), .mul_b(), .mul_p('0),
            .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
            .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
        assign d128[gi*128 +: 128] = dd;
      end
    end else begin : g_no_bank128
      assign d128 = '0;
      always_comb
        for (int i = 0; i < (LANES128 > 0 ? LANES128 : 1); i = i + 1)
          f128_l[i] = '0;
    end
  endgenerate

  // ---- fp256 bank ----------------------------------------------------
  logic [BEAT_BITS-1:0] d256;
  logic [4:0] f256_l;
  generate
    if (EN_FP256 && LANES256 > 0) begin : g_bank256
      logic [255:0] fa, fb, fc, dd;
      cft_opmux #(.EXP_W(19), .MAN_W(236)) u_mux (
          .op(op), .a(a[255:0]), .b(b[255:0]), .c(c[255:0]),
          .fa(fa), .fb(fb), .fc(fc));
      logic bv; logic [255:0] bd; logic [4:0] bf;
      cft_simpleops #(.EXP_W(19), .MAN_W(236)) u_simple (
          .op(op), .a(a[255:0]), .b(b[255:0]), .c(c[255:0]),
          .valid(bv), .d(bd), .flags(bf));
      logic sev; logic [255:0] sed;
      cft_seedop #(.EXP_W(19), .MAN_W(236)) u_seed (
          .op(op), .a(a[255:0]), .valid(sev), .d(sed));
      logic bv_m; logic [255:0] bd_m; logic [4:0] bf_m;
      assign bv_m = bv | sev;
      assign bd_m = sev ? sed : bd;
      assign bf_m = sev ? 5'b0 : bf;
      cft_fpfma_pipe #(.EXP_W(19), .MAN_W(236), .LATENCY(LATENCY),
                       .EXT_MUL(1'b0), .EXT_NORM(1'b0), .EXT_ALIGN(1'b0))
        u_fma (
          .clk(clk), .rst_n(rst_n),
          .in_valid(in_valid && (prec == PREC_FP256)),
          .rnd(rnd),
          .byp(bv_m), .byp_d(bd_m), .byp_f(bf_m),
          .a(fa), .b(fb), .c(fc),
          .out_valid(), .d(dd), .flags(f256_l),
          .mul_a(), .mul_b(), .mul_p('0),
          .nrm_v(), .nrm_csh(), .nrm_fsh(), .nrm_d('0),
          .aln_v(), .aln_csh(), .aln_fsh(), .aln_dir(), .aln_d('0));
      assign d256 = dd;
    end else begin : g_no_bank256
      assign d256 = '0;
      assign f256_l = '0;
    end
  endgenerate

  // ---- result and per-lane flag selection ----------------------------
  always_comb begin
    case (prec)
      PREC_FP32:  d = d32;
      PREC_FP64:  d = d64;
      PREC_FP128: d = d128;
      default:    d = d256;
    endcase
  end

  always_comb begin
    lane_flags = '0;
    case (prec)
      PREC_FP32:
        for (int i = 0; i < LANES32; i = i + 1)
          lane_flags[i*5 +: 5] = f32_l[i];
      PREC_FP64:
        for (int i = 0; i < LANES64; i = i + 1)
          lane_flags[i*5 +: 5] = f64_l[i];
      PREC_FP128:
        for (int i = 0; i < LANES128; i = i + 1)
          lane_flags[i*5 +: 5] = f128_l[i];
      default:
        if (LANES256 > 0)
          lane_flags[4:0] = f256_l;
    endcase
  end

endmodule
