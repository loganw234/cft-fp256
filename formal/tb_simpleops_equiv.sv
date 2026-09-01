// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_simpleops_equiv: the area rewrite of cft_simpleops, proven equal
// to the flat form it replaced - not tested equal, proven.
//
// tb/wrappers/cft_simpleops_ref.sv is the frozen byte copy of the
// module as it stood before the mux-collapse rewrite (7ab02b3), kept
// precisely so the rewrite could be checked against the thing it
// replaced. tb_simpleops.sv drives both with the same random and
// directed traffic and compares bit for bit; this harness closes the
// remaining gap between "every vector we drew agreed" and "every
// input agrees": both instances see the same symbolic {op, a, b, c},
// and the solver owns the quantifier. Combinational modules, so each
// BMC step is the whole 2^104 input space at EXP_W=8/MAN_W=23 - a
// complete equivalence proof at this rung, bounded in time, not in
// coverage.
//
// The one carve-out, and its provenance: opcodes 26 and 27 left the
// reserved set on 2026-08-31 for cft_seedop (tb/test_simpleops.py
// REASSIGNED_OPS tells the story). The frozen ref predates that and
// still traps them; the live module deliberately stays quiet so the
// engine can OR the seed result over the shared sideband. They are
// the ONE place ref and new are allowed to differ, so the assumption
// below excludes exactly those two codes and nothing else - the
// sweep's carve-out, restated to the solver. What the live module
// does on 26/27 instead (valid low, flags clear) is cft_seedop's
// gate's business, and the reserved codes bracketing them (25, 28)
// stay INSIDE this proof, trapping in both instances.
//
// All three outputs are compared: d, valid, AND flags - the frozen
// ref is the arbiter of flag behaviour too, including invalid on
// signaling NaNs reaching min/max/compare and on the reserved trap.

`timescale 1ns/1ps

module tb_simpleops_equiv #(
    parameter int EXP_W = 8,
    parameter int MAN_W = 23
) (
    input logic [7:0]           op,
    input logic [EXP_W+MAN_W:0] a,
    input logic [EXP_W+MAN_W:0] b,
    input logic [EXP_W+MAN_W:0] c
);

  localparam int W = 1 + EXP_W + MAN_W;

  // The reassigned opcodes (golden model's map: OP_RECIP_SEED,
  // OP_RSQRT_SEED = 26, 27) - the one sanctioned divergence.
  localparam logic [7:0] OP_RECIP_SEED = 8'd26;
  localparam logic [7:0] OP_RSQRT_SEED = 8'd27;

  logic         v_new, v_ref;
  logic [W-1:0] d_new, d_ref;
  logic [4:0]   fl_new, fl_ref;

  cft_simpleops #(
      .EXP_W(EXP_W),
      .MAN_W(MAN_W)
  ) u_new (
      .op(op), .a(a), .b(b), .c(c),
      .valid(v_new), .d(d_new), .flags(fl_new)
  );

  cft_simpleops_ref #(
      .EXP_W(EXP_W),
      .MAN_W(MAN_W)
  ) u_ref (
      .op(op), .a(a), .b(b), .c(c),
      .valid(v_ref), .d(d_ref), .flags(fl_ref)
  );

  always_comb begin
    assume (op != OP_RECIP_SEED && op != OP_RSQRT_SEED);

    a_same_valid: assert (v_new == v_ref);
    a_same_d:     assert (d_new == d_ref);
    a_same_flags: assert (fl_new == fl_ref);
  end

  // Non-vacuity: the carve-out leaves both trap codes that bracket it
  // reachable, plus the groups whose rewrite did the real collapsing.
  always_comb begin
    c_op25_trap:  cover (op == 8'd25);
    c_op28_trap:  cover (op == 8'd28);
    c_minmax:     cover (op == 8'd7 && v_new);
    c_cmp:        cover (op == 8'd12 && v_new);
    c_shift:      cover (op == 8'd22 && v_new);
    c_arith_gap:  cover (op == 8'd0 && !v_new);
  end

endmodule
