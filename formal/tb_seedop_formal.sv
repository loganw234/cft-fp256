// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_seedop_formal: exhaustive special-case proof for cft_seedop.
//
// The module is combinational, so a bounded check IS a complete one:
// each BMC step quantifies over every value of {op, a} at once, and
// no state connects one step to the next. What the sby run proves,
// for every one of the 2^40 input combinations at EXP_W=8/MAN_W=23:
//
//   * valid is high for opcodes 26 and 27 and for nothing else - the
//     engine merges this module's result over the bypass sideband
//     with an OR, which is only sound if that decode is exact;
//   * RECIP_SEED (26): NaN in -> the canonical quiet NaN out; +/-inf
//     -> +/-0 (sign carried); biased-exponent-zero in - zero OR
//     subnormal, because flush-at-input is the spec - -> +/-inf
//     (sign carried);
//   * RSQRT_SEED (27): NaN -> canonical qNaN; zero-class -> +/-inf
//     (sign carried: 1/sqrt(-0) is -inf, 754-2019 9.2.1); negative
//     non-zero-class (which includes -inf) -> canonical qNaN; +inf
//     -> +0;
//   * and two claims the module's header makes that cost nothing to
//     pin down: a normal operand never produces an infinity or NaN
//     from either seed (the exponent algebra cannot overflow), and
//     an RSQRT seed of a positive normal is itself strictly normal.
//
// The opcode numbers come from the golden model's opcode map
// (python/cft_golden/softfloat.py: OP_RECIP_SEED, OP_RSQRT_SEED =
// 26, 27; mirrored in host/include/cft.h). They are assignments, not
// encodings, so they appear here as the same literals the RTL uses.
// Every EXPECTED ENCODING, by contrast, is derived from the format
// fields below - no hand-typed hex anywhere, per the house rule that
// transcribed constants have been wrong three times too often.
//
// SCOPE, honestly: this proves the special-case routing and the
// never-a-special envelope, at one rung (fp32's 8/23). It does NOT
// prove the seed VALUES approximate anything - the table contents
// are the golden model's, generated into cft_seed_rom.svh, and their
// 2^-8.5 relative-error bound is proven exhaustively against the
// model in python/tests/test_seeds.py. Two gates, two jobs: Python
// owns the numerics, this owns the routing.

`timescale 1ns/1ps

module tb_seedop_formal #(
    parameter int EXP_W = 8,
    parameter int MAN_W = 23
) (
    input logic [7:0]           op,
    input logic [EXP_W+MAN_W:0] a
);

  localparam int W = 1 + EXP_W + MAN_W;

  // The ISA assignment (see header): the two opcodes this module
  // answers, and the only hand-written numbers in the file.
  localparam logic [7:0] OP_RECIP_SEED = 8'd26;
  localparam logic [7:0] OP_RSQRT_SEED = 8'd27;

  logic         valid;
  logic [W-1:0] d;

  cft_seedop #(
      .EXP_W(EXP_W),
      .MAN_W(MAN_W)
  ) dut (
      .op   (op),
      .a    (a),
      .valid(valid),
      .d    (d)
  );

  // ------------------------------------------------------------------
  // Operand classes, from the 754 field definitions.
  // ------------------------------------------------------------------
  wire             sa = a[W-1];
  wire [EXP_W-1:0] ef = a[W-2 -: EXP_W];
  wire [MAN_W-1:0] fr = a[MAN_W-1:0];

  wire cls_nan = (&ef) && (fr != '0);
  wire cls_inf = (&ef) && (fr == '0);
  wire cls_zc  = (ef == '0);            // zero-class: zero OR subnormal,
                                        // because flush-at-input is the
                                        // spec for the seeds
  wire cls_neg_nonzc = sa && !cls_zc && !cls_nan;   // includes -inf

  // ------------------------------------------------------------------
  // Expected encodings, derived from the format fields. The canonical
  // quiet NaN is sign 0, exponent all ones, quiet bit set, payload
  // clear - the tile's one NaN, per docs/DETERMINISM.md.
  // ------------------------------------------------------------------
  wire [W-1:0] enc_qnan   = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};
  wire [W-1:0] enc_inf_sa = {sa,   {EXP_W{1'b1}}, {MAN_W{1'b0}}};
  wire [W-1:0] enc_zero_sa = {sa,  {(W-1){1'b0}}};
  wire [W-1:0] enc_pzero   = {(W){1'b0}};

  wire [EXP_W-1:0] d_ef = d[W-2 -: EXP_W];

  // ------------------------------------------------------------------
  // The properties. Combinational, so immediate assertions in comb
  // context are checked in every step over all inputs.
  // ------------------------------------------------------------------
  always_comb begin
    // The decode is exact: 26 and 27, nothing else.
    a_valid_exact: assert (valid == (op == OP_RECIP_SEED ||
                                     op == OP_RSQRT_SEED));

    if (op == OP_RECIP_SEED) begin
      if (cls_nan) a_recip_nan:  assert (d == enc_qnan);
      if (cls_inf) a_recip_inf:  assert (d == enc_zero_sa);
      if (cls_zc)  a_recip_zc:   assert (d == enc_inf_sa);
      // A normal operand's reciprocal seed is never a special: the
      // exponent algebra tops out at 2*BIAS-2 < all-ones (it CAN go
      // subnormal, which is the exact-left-placement path, so an
      // exponent field of zero is legitimate here).
      if (!cls_nan && !cls_inf && !cls_zc) begin
        a_recip_normal_no_special: assert (!(&d_ef));
        a_recip_keeps_sign:        assert (d[W-1] == sa);
      end
    end

    if (op == OP_RSQRT_SEED) begin
      if (cls_nan)        a_rsqrt_nan: assert (d == enc_qnan);
      if (cls_zc)         a_rsqrt_zc:  assert (d == enc_inf_sa);
      if (cls_neg_nonzc)  a_rsqrt_neg: assert (d == enc_qnan);
      if (cls_inf && !sa) a_rsqrt_pinf: assert (d == enc_pzero);
      // An RSQRT seed of a positive normal is strictly normal: a
      // root's exponent is half its operand's, so the result can
      // reach neither the subnormal floor nor the special ceiling.
      if (!cls_nan && !cls_inf && !cls_zc && !sa) begin
        a_rsqrt_normal_stays_normal:
            assert (d_ef != '0 && !(&d_ef) && d[W-1] == 1'b0);
      end
    end
  end

  // ------------------------------------------------------------------
  // Non-vacuity: every antecedent above is satisfiable at this rung.
  // There are no assumptions in this harness, so these cannot fail
  // from over-constraint - they are here so that a future edit that
  // accidentally narrows a class (a typo in cls_zc, say) turns the
  // proof loud instead of hollow.
  // ------------------------------------------------------------------
  always_comb begin
    c_recip_nan:    cover (op == OP_RECIP_SEED && cls_nan);
    c_recip_inf:    cover (op == OP_RECIP_SEED && cls_inf);
    c_recip_zc:     cover (op == OP_RECIP_SEED && cls_zc);
    c_recip_sub:    cover (op == OP_RECIP_SEED && cls_zc && fr != '0);
    c_recip_norm:   cover (op == OP_RECIP_SEED &&
                           !cls_nan && !cls_inf && !cls_zc);
    c_rsqrt_nan:    cover (op == OP_RSQRT_SEED && cls_nan);
    c_rsqrt_zc:     cover (op == OP_RSQRT_SEED && cls_zc);
    c_rsqrt_neg:    cover (op == OP_RSQRT_SEED && cls_neg_nonzc);
    c_rsqrt_ninf:   cover (op == OP_RSQRT_SEED && cls_inf && sa);
    c_rsqrt_pinf:   cover (op == OP_RSQRT_SEED && cls_inf && !sa);
    c_rsqrt_norm:   cover (op == OP_RSQRT_SEED &&
                           !cls_nan && !cls_inf && !cls_zc && !sa);
    c_not_ours:     cover (!valid);
  end

endmodule
