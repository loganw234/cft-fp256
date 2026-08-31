// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_seedop: the divide/sqrt seed opcodes (RECIP_SEED, RSQRT_SEED).
//
// The one thing the composed divide and square root need that FMA
// cannot supply is a starting point. This module supplies it: an
// approximation of 1/x or 1/sqrt(x) with relative error < 2^-8.5
// (proven exhaustively against the table definition in
// python/tests/test_seeds.py), from which the library sequences
// Newton-refine to full precision and finish with measured rounding.
//
// The tables in cft_seed_rom.svh are GENERATED from the golden model
// (python/gen_seed_rom.py), never transcribed, and a sync test fails
// if they drift. Three properties of the spec make this module almost
// embarrassingly small, and each was chosen deliberately:
//
//   * both tables are normalised by construction - msb always set,
//     never a power of two - so there is no normalisation case-split;
//   * subnormal INPUTS flush to their zero-class result (the
//     sequences prenormalise before seeding, so nothing ever uses a
//     subnormal seed, and honouring one would cost a leading-zero
//     count and a normalising shift per lane - most of a normaliser);
//   * the exponent algebra never rounds: rsqrt results are always
//     normal (a root's exponent is half its operand's), and recip
//     results that land subnormal do so with the 18 table bits
//     shifting LEFT into a >= 23-bit fraction field - exact placement,
//     no guard, no sticky, no rounding logic at all.
//
// So the datapath is: classify, index, look up, add exponents, shift.
// Like cft_simpleops it is combinational and quiet - no flags, ever -
// and its result reaches the pipe output through the same
// precomputed-result bypass.

`timescale 1ns/1ps

module cft_seedop #(
    parameter int EXP_W = 8,
    parameter int MAN_W = 23
) (
    input  logic [7:0]           op,
    input  logic [EXP_W+MAN_W:0] a,
    output logic                 valid,   // this opcode is handled here
    output logic [EXP_W+MAN_W:0] d
);

  localparam int W = 1 + EXP_W + MAN_W;

  localparam logic [7:0] OP_RECIP_SEED = 8'd26;
  localparam logic [7:0] OP_RSQRT_SEED = 8'd27;

  `include "cft_seed_rom.svh"

  // The seed index is the top 9 fraction bits; the tables need
  // MAN_W >= 18 to place their entries exactly (true for every rung,
  // and refused loudly for anything narrower).
  generate
    if (MAN_W < 18) begin : g_too_narrow
      $error("cft_seedop: MAN_W must be at least 18");
    end
  endgenerate

  localparam int BIAS = (1 << (EXP_W - 1)) - 1;

  logic             sa;
  logic [EXP_W-1:0] ef;
  logic [MAN_W-1:0] fr;
  logic             is_nan, is_inf, is_zc;      // zc: zero or subnormal
  logic [8:0]       idx;

  assign sa  = a[W-1];
  assign ef  = a[W-2 -: EXP_W];
  assign fr  = a[MAN_W-1:0];
  assign is_nan = (&ef) && (fr != 0);
  assign is_inf = (&ef) && (fr == 0);
  assign is_zc  = (ef == 0);
  assign idx = fr[MAN_W-1 -: 9];

  logic [W-1:0] qnan, pinf_mag;
  assign qnan     = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};
  assign pinf_mag = {1'b0, {EXP_W{1'b1}}, {MAN_W{1'b0}}};

  assign valid = (op == OP_RECIP_SEED) || (op == OP_RSQRT_SEED);

  // Signed exponent arithmetic, two bits of headroom.
  logic signed [EXP_W+1:0] E, be_r, be_s;
  assign E = $signed({2'b00, ef}) - BIAS;

  // ---- reciprocal ----------------------------------------------------
  // value = r * 2^(-18 - E) = 1.f17 * 2^(-1 - E); be = BIAS - 1 - E.
  // be >= 1: normal, fraction = r[16:0] left-aligned.
  // be <= 0: subnormal, exact left placement of all 18 bits with the
  //          hidden msb kept - see the shift derivation at the site.
  logic [17:0]      r_rec;
  logic [MAN_W-1:0] frac_rec;
  logic [W-1:0]     d_rec;
  assign r_rec = seed_recip(idx);
  assign be_r  = BIAS - 1 - E;
  always_comb begin
    if (be_r >= 1) begin
      frac_rec = {r_rec[16:0], {(MAN_W-17){1'b0}}};
      d_rec = {sa, be_r[EXP_W-1:0], frac_rec};
    end else begin
      // Exact subnormal placement, msb included. The left shift is
      // (MAN_W-18)+be: the table's LSB sits at 2^(-18-E) and the
      // subnormal grid at 2^(emin-MAN_W), and the algebra collapses to
      // that - checked against the model's own anchors (E = emax gives
      // MAN_W-19, E = emax-1 gives MAN_W-18). be here is 0 or -1, so
      // the shift is always non-negative for MAN_W >= 19.
      frac_rec = {{(MAN_W-18){1'b0}}, r_rec}
                 << ((be_r == 0) ? (MAN_W - 18) : (MAN_W - 19));
      d_rec = {sa, {EXP_W{1'b0}}, frac_rec};
    end
  end

  // ---- reciprocal square root ----------------------------------------
  // value = r * 2^(-17 - (E - odd)/2) = 1.f16 * 2^(-1 - (E - odd)/2);
  // be = BIAS - 1 - (E - odd)/2, always strictly inside the normal
  // range for a normal operand.
  logic             oddE;
  logic [16:0]      r_rs;
  logic [W-1:0]     d_rs;
  assign oddE = E[0];
  assign r_rs = seed_rsqrt({oddE, idx});
  assign be_s = BIAS - 1 - ((E - $signed({{EXP_W+1{1'b0}}, oddE})) >>> 1);
  assign d_rs = {1'b0, be_s[EXP_W-1:0],
                 r_rs[15:0], {(MAN_W-16){1'b0}}};

  // ---- result select -------------------------------------------------
  always_comb begin
    d = qnan;
    if (op == OP_RECIP_SEED) begin
      if (is_nan)      d = qnan;
      else if (is_inf) d = {sa, {(W-1){1'b0}}};          // +/-0
      else if (is_zc)  d = {sa, pinf_mag[W-2:0]};        // +/-inf
      else             d = d_rec;
    end else if (op == OP_RSQRT_SEED) begin
      if (is_nan)      d = qnan;
      else if (is_zc)  d = {sa, pinf_mag[W-2:0]};        // zero-class
      else if (sa)     d = qnan;                          // negative
      else if (is_inf) d = {1'b0, {(W-1){1'b0}}};        // +0
      else             d = d_rs;
    end
  end

endmodule
