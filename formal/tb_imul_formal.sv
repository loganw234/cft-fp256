// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_imul_formal: what cft_simpleops' IMUL must be true of at every
// input at once - its decode, its width discipline, and the 32-bit
// rule that is the whole of its definition.
//
// Opcode 30 is the one member of the integer group NOT defined on the
// format width. `d` is the low 32 bits of the product of the operands'
// low 32 bits, zero-extended to W, at every format - because its
// caller is a 32-bit hash whose value has to agree with a GPU
// computing it on a `uint`. Three things follow from that sentence,
// and none of them is checkable by sampling:
//
//   * NO BIT OF EITHER OPERAND ABOVE 31 REACHES THE ANSWER. Proven as
//     a self-miter: two instances of the module see the same low 32
//     bits of `a` and of `b` and arbitrary, unequal, high halves, and
//     must produce the same `d` and the same flags. This is the half
//     of the contract a W-bit implementation would break silently at
//     fp64 and above, and the half tb/test_simpleops.py can only
//     sample.
//   * THE RESULT IS ZERO-EXTENDED, NOT MERGED. `d[W-1:32]` is zero
//     whatever the operands were, so the answer is a function of the
//     sources alone and never of the destination.
//   * IT IS QUIET AND IT IS ANSWERED HERE. `flags` is clear and
//     `valid` is high on opcode 30, which is what puts the result on
//     the pipe's bypass sideband at all; and the codes either side,
//     29 and 31, must still trap with the canonical quiet NaN and
//     invalid, so the decode is one opcode wide rather than a range.
//
// Both modules are combinational, so each BMC step quantifies over the
// whole input space at this rung and no state connects one step to the
// next: bounded in time, not in coverage.
//
// The rung is EXP_W=11/MAN_W=52, W=64, and the width is the point:
// at fp32's W=32 the zero extension is empty and the self-miter has no
// high bits to vary, so neither of the first two properties would say
// anything.
//
// WHAT IS NOT PROVEN HERE, and where it is checked instead. The VALUE
// - that `d` equals a truncated 32x32 multiply - is the `value` task
// below, guarded by IMUL_VALUE, and it is NOT in formal/run.sh's gate:
// bitwuzla ran twenty-six minutes on it without returning and was
// stopped, which is what a miter of two differently-associated
// multipliers costs a bit-blasting engine and is the same wall
// formal/mulpass.sby ran into. The value rests on
// tb/test_simpleops.py's `test_imul`, which
// drives 6,225 operand pairs at all four rungs against
// python/cft_golden/softfloat.py - the directed corpus
// docs/studies/OPT-D-contract.md names, every power of two, every
// 2^k-1, the two `lowbias32` constants and the wraparound boundary -
// and on the C-versus-model differential. Two gates, two jobs, stated
// so nobody reads this file as more than it is.
//
// The opcode number comes from the golden model's map
// (python/cft_golden/softfloat.py: OP_IMUL = 30; mirrored in
// host/include/cft.h as CFT_IMUL). It is an assignment, not an
// encoding, so it appears here as the same literal the RTL uses.
// Every expected VALUE below is computed from the format fields.

`timescale 1ns/1ps

module tb_imul_formal #(
    parameter int EXP_W = 11,
    parameter int MAN_W = 52
) (
    input logic [7:0]           op,
    input logic [EXP_W+MAN_W:0] lo_a,   // the low halves both instances
    input logic [EXP_W+MAN_W:0] lo_b,   //   share - independent of each other
    input logic [EXP_W+MAN_W:0] hi1,    // and two arbitrary high halves
    input logic [EXP_W+MAN_W:0] hi2,
    input logic [EXP_W+MAN_W:0] c
);

  localparam int W = 1 + EXP_W + MAN_W;

  // The ISA assignment (see header): the opcode this proof is about,
  // and its two reserved neighbours.
  localparam logic [7:0] OP_IMUL  = 8'd30;
  localparam logic [7:0] OP_BELOW = 8'd29;   // sumAbs: a reduction, trapped
  localparam logic [7:0] OP_ABOVE = 8'd31;   // unassigned

  // Shared low 32 bits, two different everything-above-32, and the
  // two operands' low halves independent of each other so the miter
  // covers every (a, b) pair and not just the diagonal. The two
  // instances differ in every bit the operation is defined to ignore
  // and in none that it reads.
  logic [W-1:0] a1, b1, a2, b2;
  assign a1 = {hi1[W-1:32], lo_a[31:0]};
  assign b1 = {hi2[W-1:32], lo_b[31:0]};
  assign a2 = {hi2[W-1:32], lo_a[31:0]};
  assign b2 = {hi1[W-1:32], lo_b[31:0]};

  logic         v1, v2;
  logic [W-1:0] d1, d2;
  logic [4:0]   f1, f2;

  cft_simpleops #(.EXP_W(EXP_W), .MAN_W(MAN_W)) u1 (
      .op(op), .a(a1), .b(b1), .c(c), .valid(v1), .d(d1), .flags(f1));
  cft_simpleops #(.EXP_W(EXP_W), .MAN_W(MAN_W)) u2 (
      .op(op), .a(a2), .b(b2), .c(c), .valid(v2), .d(d2), .flags(f2));

  wire [W-1:0] enc_qnan = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};

  always_comb begin
    if (op == OP_IMUL) begin
      // the 32-bit rule, as a self-miter over the ignored bits
      a_imul_ignores_high:  assert (d1 == d2);
      a_imul_same_flags:    assert (f1 == f2);
      // the zero extension, on both instances
      a_imul_zero_extended: assert (d1[W-1:32] == '0 && d2[W-1:32] == '0);
      // quiet, and answered by this module
      a_imul_quiet:         assert (f1 == 5'b0);
      a_imul_valid:         assert (v1);
    end
    // one opcode wide, not a range: the codes either side still trap
    if (op == OP_BELOW || op == OP_ABOVE) begin
      a_neighbour_traps: assert (v1 && d1 == enc_qnan && f1 == 5'b00001);
    end
  end

`ifdef IMUL_VALUE
  // The value miter. NOT in the gate - see the header. Kept so the
  // property can be retried on a quiet machine or a better engine.
  wire [63:0]  ref_p  = {32'b0, a1[31:0]} * {32'b0, b1[31:0]};
  wire [W-1:0] ref_lo = W'(ref_p[31:0]);
  always_comb begin
    if (op == OP_IMUL) a_imul_value: assert (d1 == ref_lo);
  end
`endif

  // Non-vacuity: every antecedent is satisfiable and the interesting
  // corners of the product are reachable, so an edit that narrowed the
  // decode turns the proof loud rather than hollow.
  always_comb begin
    c_imul:           cover (op == OP_IMUL);
    c_imul_high_diff: cover (op == OP_IMUL && a1 != a2);
    c_imul_zero:      cover (op == OP_IMUL && d1 == '0 &&
                             a1[31:0] != 0 && b1[31:0] != 0);
    c_imul_top_bit:   cover (op == OP_IMUL && d1[31]);
    c_imul_nonzero:   cover (op == OP_IMUL && d1 != '0);
    c_neighbour_lo:   cover (op == OP_BELOW);
    c_neighbour_hi:   cover (op == OP_ABOVE);
    c_not_ours:       cover (!v1);
  end

endmodule
