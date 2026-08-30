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
    input  logic [7:0]           op,
    input  logic [EXP_W+MAN_W:0] a,
    input  logic [EXP_W+MAN_W:0] b,
    input  logic [EXP_W+MAN_W:0] c,
    output logic                 valid,   // this opcode is handled here
    output logic [EXP_W+MAN_W:0] d,
    output logic [4:0]           flags
);

  localparam int W = 1 + EXP_W + MAN_W;
  localparam int FL_INVALID = 0;

  localparam logic [7:0] OP_ABS = 8'd4;
  localparam logic [7:0] OP_NEG = 8'd5;
  localparam logic [7:0] OP_COPYSIGN = 8'd6;
  localparam logic [7:0] OP_MIN = 8'd7;
  localparam logic [7:0] OP_MAX = 8'd8;
  localparam logic [7:0] OP_MINNUM = 8'd9;
  localparam logic [7:0] OP_MAXNUM = 8'd10;
  localparam logic [7:0] OP_SELECT = 8'd11;
  localparam logic [7:0] OP_CMPLT = 8'd12;
  localparam logic [7:0] OP_CMPLE = 8'd13;
  localparam logic [7:0] OP_CMPEQ = 8'd14;
  localparam logic [7:0] OP_IAND   = 8'd16;
  localparam logic [7:0] OP_IOR    = 8'd17;
  localparam logic [7:0] OP_IXOR   = 8'd18;
  localparam logic [7:0] OP_IADD   = 8'd19;
  localparam logic [7:0] OP_ISUB   = 8'd20;
  localparam logic [7:0] OP_ISHL   = 8'd21;
  localparam logic [7:0] OP_ISHR   = 8'd22;
  localparam logic [7:0] OP_ICMPLT = 8'd23;

  localparam int BIAS = (1 << (EXP_W - 1)) - 1;
  localparam int SHB  = $clog2(W);   // every W here is a power of two

  logic [W-1:0]     qnan, one, pzero;
  logic [EXP_W-1:0] bias_f;
  assign qnan   = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};
  // 1.0: build the exponent from BIAS rather than a bit pattern. The
  // hand-written {(EXP_W-1){1'b1}, 1'b0} spelling is off by one binade
  // - it is 2^BIAS, not 1.0 - which is exactly the mistake this
  // replaced, caught by the kernel bench.
  assign bias_f = BIAS;
  assign one    = {1'b0, bias_f, {MAN_W{1'b0}}};
  assign pzero  = '0;

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

  // Numeric equality for non-NaN operands. Two different patterns can
  // only be numerically equal when both are zero, so outside that case
  // the patterns compare directly.
  logic eq, unord, is_cmp;
  assign eq     = both_zero || (a == b);
  assign unord  = a_nan || b_nan;
  assign is_cmp = (op == OP_CMPLT) || (op == OP_CMPLE) || (op == OP_CMPEQ);

  // Integer group: the encoding as a W-bit unsigned word. Shift counts
  // come from b's low SHB bits, so no count can be out of range.
  logic is_int;
  logic [SHB-1:0] shamt;
  assign shamt  = b[SHB-1:0];
  assign is_int = (op == OP_IAND) || (op == OP_IOR) || (op == OP_IXOR) ||
                  (op == OP_IADD) || (op == OP_ISUB) || (op == OP_ISHL) ||
                  (op == OP_ISHR) || (op == OP_ICMPLT);

  // Unassigned opcodes answer with the canonical quiet NaN and raise
  // invalid, rather than falling through to the FMA datapath and
  // returning a plausible number. Both behaviours are deterministic,
  // so neither breaks the contract - but a host that issues an opcode
  // this bitstream predates should learn that from the flags, not
  // discover it when the arithmetic changes under a later build. It
  // also gives the host library's UNSUPPORTED error something real to
  // report. 15 and everything above 23 are the current holes; divide,
  // square root, conversions and the reductions will fill them.
  logic is_reserved;
  assign is_reserved = (op == 8'd15) || (op > 8'd23);

  assign valid = (op == OP_ABS) || (op == OP_NEG) ||
                 (op == OP_COPYSIGN) || is_minmax ||
                 (op == OP_SELECT) || is_cmp || is_int || is_reserved;

  // The shift-count rule (b modulo W) is only equivalent to taking the
  // low $clog2(W) bits when W is a power of two. Every format on the
  // interchange ladder is, but nothing in the parameterization forces
  // it, and a non-power-of-two rung would diverge from the golden
  // model silently rather than loudly.
  generate
    if (W != (1 << SHB)) begin : g_bad_width
      $error("cft_simpleops: format width must be a power of two");
    end
  endgenerate

  always_comb begin
    d     = a;
    flags = 5'b0;
    case (op)
      OP_ABS:      d = {1'b0,  a[W-2:0]};
      OP_NEG:      d = {~sa,   a[W-2:0]};
      OP_COPYSIGN: d = {sb,    a[W-2:0]};
      // Data movement: inspects c's magnitude and nothing else, so it
      // carries NaNs and infinities through intact and signals nothing.
      OP_SELECT:   d = (c[W-2:0] != 0) ? a : b;
      OP_IAND:     d = a & b;
      OP_IOR:      d = a | b;
      OP_IXOR:     d = a ^ b;
      OP_IADD:     d = a + b;
      OP_ISUB:     d = a - b;
      OP_ISHL:     d = a << shamt;
      OP_ISHR:     d = a >> shamt;            // logical, never arithmetic
      OP_ICMPLT:   d = (a < b) ? one : pzero; // unsigned, yields a float
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
        end else if (is_cmp) begin
          // 754 5.11 quiet comparison: signals only on a signaling
          // NaN, and an unordered pair makes every predicate false.
          // The result is a float so a later select can consume it.
          flags[FL_INVALID] = a_snan || b_snan;
          if (unord) d = pzero;
          else begin
            case (op)
              OP_CMPLT: d = a_lt_b        ? one : pzero;
              OP_CMPLE: d = (a_lt_b || eq) ? one : pzero;
              default:  d = eq            ? one : pzero;  // OP_CMPEQ
            endcase
          end
        end else if (is_reserved) begin
          d = qnan;
          flags[FL_INVALID] = 1'b1;
        end
      end
    endcase
  end

endmodule
