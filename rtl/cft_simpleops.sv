// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_simpleops: the operations that are not arithmetic.
//
// abs, negate, copySign (754-2019 5.5.1) and the four min/max forms
// (9.6) need no adder, no multiplier and no rounding - they are a sign
// bit and a magnitude comparison. Computing them here, combinationally,
// and handing the answer to cft_fpfma_pipe as a precomputed result
// costs nothing: the pipe already carries results that skip the
// datapath (infinities, NaNs, zero products) down a sideband to the
// output stage, so this reuses that path instead of adding a
// latency-matching delay line beside it.
//
// Two semantics worth stating because they are easy to get wrong:
//
//   * abs/negate/copySign are "quiet-computational" - they touch the
//     sign bit and nothing else, signal NO exception even for a
//     signaling NaN, and preserve the rest of the pattern including a
//     NaN payload. This is the one place the canonical-NaN rule does
//     not apply, and it does not weaken determinism: there is a single
//     source for the payload, so the result is still a function of the
//     input bits. Canonicalising would make copySign lossy.
//
//   * min(+0, -0) is -0 and max(+0, -0) is +0, even though the two
//     compare equal. Signed zeros are equal but not interchangeable.
//
// The ...Number forms return the non-NaN operand where the plain forms
// propagate the NaN; both signal invalid on a signaling NaN.

`timescale 1ns/1ps

module cft_simpleops #(
    parameter int EXP_W = 8,
    parameter int MAN_W = 23
) (
    input  logic [3:0]           op,
    input  logic [EXP_W+MAN_W:0] a,
    input  logic [EXP_W+MAN_W:0] b,
    output logic                 valid,   // this opcode is handled here
    output logic [EXP_W+MAN_W:0] d,
    output logic [4:0]           flags
);

  localparam int W = 1 + EXP_W + MAN_W;
  localparam int FL_INVALID = 0;

  localparam logic [3:0] OP_ABS      = 4'd4;
  localparam logic [3:0] OP_NEG      = 4'd5;
  localparam logic [3:0] OP_COPYSIGN = 4'd6;
  localparam logic [3:0] OP_MIN      = 4'd7;
  localparam logic [3:0] OP_MAX      = 4'd8;
  localparam logic [3:0] OP_MINNUM   = 4'd9;
  localparam logic [3:0] OP_MAXNUM   = 4'd10;

  logic [W-1:0] qnan;
  assign qnan = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};

  logic             sa, sb;
  logic [EXP_W-1:0] ea, eb;
  logic [MAN_W-1:0] fra, frb;
  logic             a_nan, b_nan, a_snan, b_snan, a_zero, b_zero;
  logic [W-2:0]     mag_a, mag_b;
  logic             a_lt_b, both_zero;

  assign sa  = a[W-1];
  assign sb  = b[W-1];
  assign ea  = a[W-2 -: EXP_W];
  assign eb  = b[W-2 -: EXP_W];
  assign fra = a[MAN_W-1:0];
  assign frb = b[MAN_W-1:0];

  assign a_nan  = (&ea) && (fra != 0);
  assign b_nan  = (&eb) && (frb != 0);
  assign a_snan = a_nan && !fra[MAN_W-1];
  assign b_snan = b_nan && !frb[MAN_W-1];
  assign a_zero = (ea == 0) && (fra == 0);
  assign b_zero = (eb == 0) && (frb == 0);

  assign mag_a = a[W-2:0];
  assign mag_b = b[W-2:0];
  assign both_zero = a_zero && b_zero;

  // IEEE comparison for non-NaN operands. The encoding is monotone in
  // magnitude, so within one sign the payload-free patterns compare
  // directly; across signs the negative one is smaller. Zeros are
  // handled separately because they compare equal.
  always_comb begin
    if (both_zero)          a_lt_b = 1'b0;
    else if (sa != sb)      a_lt_b = sa;
    else if (sa)            a_lt_b = (mag_a > mag_b);
    else                    a_lt_b = (mag_a < mag_b);
  end

  logic want_max, is_number_form, is_minmax;
  assign want_max       = (op == OP_MAX) || (op == OP_MAXNUM);
  assign is_number_form = (op == OP_MINNUM) || (op == OP_MAXNUM);
  assign is_minmax      = (op == OP_MIN) || (op == OP_MAX) ||
                          (op == OP_MINNUM) || (op == OP_MAXNUM);

  assign valid = (op == OP_ABS) || (op == OP_NEG) ||
                 (op == OP_COPYSIGN) || is_minmax;

  always_comb begin
    d     = a;
    flags = 5'b0;
    case (op)
      OP_ABS:      d = {1'b0,  a[W-2:0]};
      OP_NEG:      d = {~sa,   a[W-2:0]};
      OP_COPYSIGN: d = {sb,    a[W-2:0]};
      default: begin
        if (is_minmax) begin
          flags[FL_INVALID] = a_snan || b_snan;
          if (a_nan || b_nan) begin
            if (!is_number_form || (a_nan && b_nan)) d = qnan;
            else                                     d = a_nan ? b : a;
          end else if (both_zero) begin
            if (sa == sb)      d = a;
            else if (want_max) d = sa ? b : a;   // the positive one
            else               d = sa ? a : b;   // the negative one
          end else begin
            if (want_max) d = a_lt_b ? b : a;
            else          d = a_lt_b ? a : b;
          end
        end
      end
    endcase
  end

endmodule
