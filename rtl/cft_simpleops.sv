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
//
// ------------------------------------------------------------------
// Why the shape below, and not the obvious one
// ------------------------------------------------------------------
//
// This module was written as one flat case(op) assigning a W-bit value
// per opcode, which is the readable spelling and reads exactly like the
// standard. It was also, measured, the second-largest block in the
// tile: 22,418 LUT across the fifteen lanes, behind only the FMA pipes
// and ahead of everything else combined. Nothing here multiplies, so
// that number was a surprise, and it is worth recording where it went.
//
// Every lane bank is exactly 256 bits wide - eight fp32, four fp64, two
// fp128 and one fp256 all consume one HBM beat - so the array is 1,024
// bits of datapath, and 22,418 LUT is 21.9 LUT per bit. A 2:1 mux is
// half a LUT per bit. The flat form spent that budget four ways:
//
//   ~4 LUT/bit   twenty-odd W-bit sources feeding one mux. On this
//                fabric a 4:1 mux is one LUT6 and MUXF7/MUXF8 are free,
//                so mux cost is 2 LUT/bit per octave: 8:1 costs 2,
//                16:1 costs 4. Sources, not opcodes, set the price.
//   ~6.5 LUT/bit two independent barrel shifters, one per direction.
//   ~2 LUT/bit   two independent adders, one per sign.
//   ~2 LUT/bit   three magnitude comparators over the same operands.
//
// The rewrite changes no function. It groups the opcodes by the SHAPE
// of the answer rather than by name, which collapses the mux to eight
// sources, and it builds one instance of each expensive primitive:
//
//   pick      a, b, qnan, or a predicate constant - every opcode whose
//             answer is an operand or a fixed pattern lands here, which
//             is all of min/max, select, the comparisons and the
//             reserved-opcode trap. abs/negate/copySign join it too:
//             their answer is `a` with a different sign bit, so they
//             cost one LUT on the MSB rather than three W-bit sources.
//   integer   bitwise, add/sub, shift - three sources, each built once.
//
// The three savings that are not just mux depth:
//
//   * One barrel shifter. Reversing the bits, shifting left, and
//     reversing back is a logical right shift, and bit reversal is
//     wiring. Two W-bit muxes replace a whole second SHB-deep ladder.
//   * One adder. a - b is a + ~b + 1, and the inversion folds into the
//     carry chain's own LUT, so the subtract is free rather than a
//     second chain.
//   * One magnitude comparator. mag_a > mag_b is neither less nor
//     equal; the unsigned integer compare ICMPLT needs only the sign
//     bits on top of the same magnitude result; and within one sign the
//     full-word equality already computed for CMPEQ *is* magnitude
//     equality. Three comparators become one, plus an equality test
//     that was there anyway.
//
// The one thing to be careful of when editing: `pick` must carry the
// operand's own sign, and only abs/negate/copySign override it. That
// override is applied to bit W-1 alone, deliberately - routing the sign
// ops through the wide mux is what made them cost three sources.

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

  // Which of the four fixed shapes the answer takes. PK_PRED's value is
  // `one` or `pzero`, both constants, so that source is wiring: the
  // whole word is either zero or a pattern of EXP_W-1 ones.
  localparam logic [1:0] PK_A    = 2'd0;
  localparam logic [1:0] PK_B    = 2'd1;
  localparam logic [1:0] PK_NAN  = 2'd2;
  localparam logic [1:0] PK_PRED = 2'd3;

  localparam logic [1:0] CL_BIT = 2'd0;   // and / or / xor
  localparam logic [1:0] CL_SUM = 2'd1;   // add / sub
  localparam logic [1:0] CL_SHF = 2'd2;   // shl / shr

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

  // The one magnitude comparator, and the one equality test. Everything
  // that compares in this module is a function of these two bits and
  // the two sign bits.
  logic mag_lt, word_eq;
  assign mag_lt  = (mag_a < mag_b);
  assign word_eq = (a == b);

  // IEEE comparison for non-NaN operands. The encoding is monotone in
  // magnitude, so within one sign the payload-free patterns compare
  // directly; across signs the negative one is smaller. Zeros are
  // handled separately because they compare equal.
  //
  // The negative branch wants mag_a > mag_b, which is "neither less nor
  // equal". Equal magnitudes with equal signs are equal words, so
  // word_eq stands in for the magnitude equality here and no second
  // comparator is needed. (Across signs the substitution would be
  // wrong - +0 and -0 have equal magnitudes and unequal words - but
  // that branch is unreachable: sa == sb holds by construction.)
  always_comb begin
    if (both_zero)          a_lt_b = 1'b0;
    else if (sa != sb)      a_lt_b = sa;
    else if (sa)            a_lt_b = !mag_lt && !word_eq;
    else                    a_lt_b = mag_lt;
  end

  // ICMPLT is an unsigned W-bit integer compare, so the sign bit is
  // just the top bit of the number: differing tops decide it outright,
  // equal tops defer to the magnitude compare already built above.
  logic icmp_lt;
  assign icmp_lt = (sa != sb) ? sb : mag_lt;

  logic want_max, is_number_form, is_minmax;
  assign want_max       = (op == OP_MAX) || (op == OP_MAXNUM);
  assign is_number_form = (op == OP_MINNUM) || (op == OP_MAXNUM);
  assign is_minmax      = (op == OP_MIN) || (op == OP_MAX) ||
                          (op == OP_MINNUM) || (op == OP_MAXNUM);

  // Numeric equality for non-NaN operands. Two different patterns can
  // only be numerically equal when both are zero, so outside that case
  // the patterns compare directly.
  logic eq, unord, is_cmp;
  assign eq     = both_zero || word_eq;
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
  // 26 and 27 left the reserved set on 2026-08-31: they are the
  // divide/sqrt seed opcodes, answered by cft_seedop through the same
  // bypass sideband this module uses. 24 is the reduction (the engine
  // routes it around the banks entirely), 25 is CFT_DOT (host-composed,
  // never issued raw), and both still trap here if an element-wise run
  // somehow presents them - deterministically, as before.
  assign is_reserved = (op == 8'd15) || (op == 8'd24) || (op == 8'd25) ||
                       (op > 8'd27);

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

  // ------------------------------------------------------------------
  // Control: eight bits of opcode in, seven bits of select out. This
  // block is the whole decode, and it is narrow - nothing W-bit wide
  // is chosen here, only which of the eight sources below wins.
  // ------------------------------------------------------------------
  logic [1:0] pk;
  logic [1:0] int_cls;
  logic       pred, sgn_ovr_en, sgn_ovr, use_int;

  always_comb begin
    // Opcodes 0-3 are the arithmetic group: cft_fpfma_pipe answers
    // those and `valid` is low, so the default of `a` is never read.
    pk         = PK_A;
    pred       = 1'b0;
    sgn_ovr_en = 1'b0;
    sgn_ovr    = 1'b0;
    use_int    = 1'b0;
    int_cls    = CL_BIT;
    flags      = 5'b0;
    case (op)
      OP_ABS:      begin sgn_ovr_en = 1'b1; sgn_ovr = 1'b0; end
      OP_NEG:      begin sgn_ovr_en = 1'b1; sgn_ovr = ~sa;  end
      OP_COPYSIGN: begin sgn_ovr_en = 1'b1; sgn_ovr = sb;   end

      // Data movement: inspects c's magnitude and nothing else, so it
      // carries NaNs and infinities through intact and signals nothing.
      OP_SELECT:   pk = (c[W-2:0] != 0) ? PK_A : PK_B;

      OP_IAND, OP_IOR, OP_IXOR: begin use_int = 1'b1; int_cls = CL_BIT; end
      OP_IADD, OP_ISUB:         begin use_int = 1'b1; int_cls = CL_SUM; end
      OP_ISHL, OP_ISHR:         begin use_int = 1'b1; int_cls = CL_SHF; end

      OP_ICMPLT: begin pk = PK_PRED; pred = icmp_lt; end

      // 754 5.11 quiet comparison: signals only on a signaling NaN,
      // and an unordered pair makes every predicate false. The result
      // is a float so a later select can consume it.
      OP_CMPLT, OP_CMPLE, OP_CMPEQ: begin
        flags[FL_INVALID] = a_snan || b_snan;
        pk   = PK_PRED;
        pred = !unord && ((op == OP_CMPEQ) ? eq                :
                          (op == OP_CMPLE) ? (a_lt_b || eq)    :
                                             a_lt_b);
      end

      OP_MIN, OP_MAX, OP_MINNUM, OP_MAXNUM: begin
        flags[FL_INVALID] = a_snan || b_snan;
        if (a_nan || b_nan) begin
          if (!is_number_form || (a_nan && b_nan)) pk = PK_NAN;
          else                                     pk = a_nan ? PK_B : PK_A;
        end else if (both_zero) begin
          if (sa == sb)      pk = PK_A;
          else if (want_max) pk = sa ? PK_B : PK_A;   // the positive one
          else               pk = sa ? PK_A : PK_B;   // the negative one
        end else begin
          if (want_max) pk = a_lt_b ? PK_B : PK_A;
          else          pk = a_lt_b ? PK_A : PK_B;
        end
      end

      default: begin
        if (is_reserved) begin
          pk                = PK_NAN;
          flags[FL_INVALID] = 1'b1;
        end
      end
    endcase
  end

  // ------------------------------------------------------------------
  // Datapath: eight sources, each built once.
  // ------------------------------------------------------------------

  // Both arms are constants, so this is a fan-out of `pred` onto the
  // EXP_W-1 bits that 1.0 sets and a tie-off everywhere else.
  logic [W-1:0] pred_val;
  assign pred_val = pred ? one : pzero;

  logic [W-1:0] pick;
  always_comb begin
    case (pk)
      PK_A:    pick = a;
      PK_B:    pick = b;
      PK_NAN:  pick = qnan;
      default: pick = pred_val;
    endcase
  end

  // op[1:0] is 00/01/10 for IAND/IOR/IXOR, and this source is only
  // selected for those three, so no fourth encoding exists to handle.
  logic [W-1:0] bit_val;
  always_comb begin
    case (op[1:0])
      2'b00:   bit_val = a & b;
      2'b01:   bit_val = a | b;
      default: bit_val = a ^ b;
    endcase
  end

  // One carry chain for both signs: a - b is a + ~b + 1, and the
  // conditional inversion folds into the same LUT that generates the
  // chain's propagate term.
  logic         sub;
  logic [W-1:0] sum_val;
  assign sub     = (op == OP_ISUB);
  assign sum_val = a + (b ^ {W{sub}}) + {{(W-1){1'b0}}, sub};

  // One barrel shifter for both directions. rev(rev(x) << n) is x >> n
  // logically: reversing maps bit i to W-1-i, so a left shift between
  // two reversals moves bit i+n to bit i and fills the top with the
  // zeros the left shift put at the bottom. Reversal is wiring, so the
  // second direction costs two W-bit muxes instead of an SHB-deep
  // ladder. Logical, never arithmetic - matching the model.
  logic         sh_right;
  logic [W-1:0] a_rev, sh_in, sh_out, sh_out_rev, shift_val;
  assign sh_right = (op == OP_ISHR);
  always_comb begin
    for (int i = 0; i < W; i++) a_rev[i] = a[W-1-i];
  end
  assign sh_in  = sh_right ? a_rev : a;
  assign sh_out = sh_in << shamt;
  always_comb begin
    for (int i = 0; i < W; i++) sh_out_rev[i] = sh_out[W-1-i];
  end
  assign shift_val = sh_right ? sh_out_rev : sh_out;

  logic [W-1:0] int_val;
  always_comb begin
    case (int_cls)
      CL_BIT:  int_val = bit_val;
      CL_SUM:  int_val = sum_val;
      default: int_val = shift_val;
    endcase
  end

  // The sign override reaches bit W-1 only. abs, negate and copySign
  // are `a` with a different sign, and spending three wide mux sources
  // on that was most of what made those three opcodes expensive.
  logic [W-1:0] body;
  assign body = use_int ? int_val : pick;
  assign d    = {sgn_ovr_en ? sgn_ovr : body[W-1], body[W-2:0]};

endmodule
