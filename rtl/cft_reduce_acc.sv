// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_reduce_acc: the streaming reduction accumulator.
//
// Consumes one value per cycle and produces the canonical reduction
// tree over them - the tree python/cft_golden/reduce.py defines, and
// specifically the `stream_reduce` form of it, which is this machine
// written in Python.
//
// THE TREE, AND WHY IT IS THIS TREE
//
// A binary-counter stack. Level j holds a partial result covering 2^j
// inputs; an arriving value goes to level 0, and whenever a level is
// already occupied its contents - always the LOWER indices, because
// values reach each level in index order - are added to the arriving
// value and the sum carries up one level. At the end the occupied
// levels are folded lowest first, right-associating outward.
//
// The model's split() was originally the midpoint of the range, which
// is the tidier-looking balanced tree. It is not this one: a midpoint
// tree equals a streaming accumulation only when the count is a power
// of two, and differs at 3, 5, 6, 7, 9, 11 and so on. The model was
// changed to the power-of-two split BEFORE this module existed,
// precisely so the hardware would not have to walk an index range it
// has no reason to know about. Depth is ceil(log2 n) either way.
//
// WHY THE CARRIES ARE DEFERRED
//
// The adder is a 15-stage pipeline. A carry at level j+1 needs level
// j's result, so resolving a burst eagerly costs ADD_LATENCY cycles per
// LEVEL of the burst. Measured against the tree's own statistics that
// is ~15.5 cycles per input - the accumulator would cost ten times what
// the engine spends fetching the operands.
//
// So a carry is not resolved before the next input is accepted. An add
// is issued, the arriving value's slot is freed immediately, and the
// result is placed when it returns - carrying again if it collides.
// Adds at different levels are independent, so several are in flight at
// once and the pipe stays busy. Total adds is exactly n-1 either way;
// deferring is what turns that into ~1 cycle per input instead of 15.
//
// WHAT IS FIXED AND WHAT IS FREE
//
// The contract fixes the PAIRING - which values are added together, and
// at which level - and nothing else. Two things it leaves free, and the
// design uses both:
//
//   Issue schedule. Adds may be issued in any order and be in flight
//   together; a pair's operands are both determined before it issues,
//   so when it issues cannot reach the answer. This is the same
//   argument that lets tiles run at different speeds.
//
//   Operand side. add is commutative bit for bit here - magnitude is
//   symmetric, the sign of an exact cancellation comes from the
//   rounding attribute rather than operand order (754-2019 6.3), and
//   NaN results are always the canonical quiet NaN rather than a
//   propagated payload. So a pair may be presented to the adder either
//   way round. Verified over 80,000 pairs across four formats and five
//   attributes; test_add_is_commutative_so_operand_order_is_free keeps
//   it true, and it is the reason this module never has to reason about
//   which side a value came from.
//
// The adder is external. This module issues (a, b) and expects the sum
// ADD_LATENCY cycles later; it carries the destination level alongside
// in its own delay line. That keeps it independent of which adder is
// used, and lets the engine share the one it already has.

`timescale 1ns/1ps

module cft_reduce_acc #(
    parameter int W           = 32,   // element width
    // Inputs this can reduce is 2^LEVELS. 40 covers any count a beat
    // engine can stream in a human lifetime and costs 40 registers of
    // W bits; the flush fold walks them once per run.
    parameter int LEVELS      = 40,
    parameter int ADD_LATENCY = 15
) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         clear,        // begin a new reduction

    input  logic         in_valid,
    input  logic [W-1:0] in_data,
    output logic         in_ready,

    input  logic         flush,        // stream ended; produce the result

    // external adder: a + b, result ADD_LATENCY cycles later
    output logic         add_valid,
    output logic [W-1:0] add_a,
    output logic [W-1:0] add_b,
    input  logic [W-1:0] add_res,
    input  logic [4:0]   add_flags,

    output logic         out_valid,
    output logic [W-1:0] out_data,
    output logic [4:0]   out_flags
);

  localparam int LW = $clog2(LEVELS + 1);

  logic [W-1:0]  slot [0:LEVELS-1];
  logic [LEVELS-1:0] occ;

  // Destination level travelling with an in-flight add. The adder does
  // not know or care about levels, so the bookkeeping lives here.
  logic          dly_v   [0:ADD_LATENCY-1];
  logic [LW-1:0] dly_lvl [0:ADD_LATENCY-1];

  logic          res_v;
  logic [LW-1:0] res_lvl;
  assign res_v   = dly_v[ADD_LATENCY-1];
  assign res_lvl = dly_lvl[ADD_LATENCY-1];

  // in-flight add count, so flush knows when the pipe is empty
  logic [LW+4:0] inflight;

  // ---- flush state machine -------------------------------------------
  localparam logic [2:0] S_ACC   = 3'd0,   // accumulating
                         S_DRAIN = 3'd1,   // flush asked; wait for the pipe
                         S_SCAN  = 3'd2,   // walk to the next occupied level
                         S_WAIT  = 3'd3,   // fold add in flight
                         S_DONE  = 3'd4;
  logic [2:0]    st;
  logic [LW-1:0] ptr;
  logic [W-1:0]  fold_r;
  logic          fold_started;

  // ---- issue arbitration ---------------------------------------------
  //
  // A returning result and an arriving input can both need the adder in
  // the same cycle, and there is one adder. The result wins - it is
  // already in the machine and holding it up stalls everything behind
  // it - and the input is refused with in_ready.
  //
  // A result never targets level 0 (an issue from level t targets t+1,
  // and t >= 0), so a result and an input can never contend for the
  // same slot. Only the adder port is contended.
  logic res_needs_issue, in_needs_issue;
  assign res_needs_issue = res_v && occ[res_lvl];
  assign in_needs_issue  = in_valid && occ[0];

  logic fold_issue;
  assign fold_issue = (st == S_SCAN) && fold_started &&
                      (ptr < LEVELS[LW-1:0]) && occ[ptr];

  assign in_ready = (st == S_ACC) && !(res_needs_issue && in_needs_issue);

  always_comb begin
    add_valid = 1'b0;
    add_a     = '0;
    add_b     = '0;
    if (fold_issue) begin
      // Fold. The higher level holds the lower indices, so it goes in
      // the left operand for readability - but only the PAIRING matters,
      // not which side a value lands on: add is commutative bit for bit
      // in this design and test_add_is_commutative_so_operand_order_is_free
      // holds it so. Swapping these two is a verified no-op.
      add_valid = 1'b1;
      add_a     = slot[ptr];
      add_b     = fold_r;
    end else if (res_needs_issue) begin
      add_valid = 1'b1;
      add_a     = slot[res_lvl];
      add_b     = add_res;
    end else if (in_valid && in_ready && in_needs_issue) begin
      add_valid = 1'b1;
      add_a     = slot[0];
      add_b     = in_data;
    end
  end

  // Destination level for whatever is being issued this cycle.
  logic [LW-1:0] issue_lvl;
  always_comb begin
    if (fold_issue)                                 issue_lvl = ptr;
    else if (res_needs_issue)                       issue_lvl = res_lvl + 1'b1;
    else                                            issue_lvl = 1'b1;
  end

  integer i;
  always_ff @(posedge clk) begin
    if (!rst_n || clear) begin
      occ       <= '0;
      inflight  <= '0;
      st        <= S_ACC;
      ptr       <= '0;
      fold_r    <= '0;
      fold_started <= 1'b0;
      out_valid <= 1'b0;
      out_data  <= '0;
      out_flags <= 5'b0;
      for (i = 0; i < ADD_LATENCY; i = i + 1) begin
        dly_v[i]   <= 1'b0;
        dly_lvl[i] <= '0;
      end
    end else begin
      // ---- adder delay line ------------------------------------------
      dly_v[0]   <= add_valid;
      dly_lvl[0] <= issue_lvl;
      for (i = 1; i < ADD_LATENCY; i = i + 1) begin
        dly_v[i]   <= dly_v[i-1];
        dly_lvl[i] <= dly_lvl[i-1];
      end

      inflight <= inflight + (add_valid ? 1 : 0) - (res_v ? 1 : 0);

      if (res_v)
        out_flags <= out_flags | add_flags;

      // ---- placement --------------------------------------------------
      //
      // A returning result either lands in its level or collides and is
      // re-issued (the issue itself is handled above); either way the
      // level it came from is now free.
      if (res_v && (st != S_WAIT)) begin
        if (occ[res_lvl]) occ[res_lvl] <= 1'b0;      // consumed by the re-issue
        else begin
          slot[res_lvl] <= add_res;
          occ[res_lvl]  <= 1'b1;
        end
      end

      if (st == S_ACC && in_valid && in_ready) begin
        if (occ[0]) occ[0] <= 1'b0;                  // consumed by the issue
        else begin
          slot[0] <= in_data;
          occ[0]  <= 1'b1;
        end
      end

      // ---- flush ------------------------------------------------------
      case (st)
        S_ACC: if (flush) st <= S_DRAIN;

        S_DRAIN: if (inflight == 0 && !add_valid) begin
          // Everything that was in flight has landed. Start the fold at
          // the lowest occupied level; that value is the seed and the
          // higher levels wrap around it.
          ptr <= '0;
          fold_started <= 1'b0;
          st <= S_SCAN;
        end

        S_SCAN: begin
          if (!fold_started) begin
            if (ptr >= LEVELS[LW-1:0]) begin
              // nothing was ever accumulated
              fold_r <= '0;
              st <= S_DONE;
            end else if (occ[ptr]) begin
              fold_r <= slot[ptr];
              occ[ptr] <= 1'b0;
              fold_started <= 1'b1;
              ptr <= ptr + 1'b1;
            end else begin
              ptr <= ptr + 1'b1;
            end
          end else begin
            if (ptr >= LEVELS[LW-1:0]) st <= S_DONE;
            else if (occ[ptr]) begin
              occ[ptr] <= 1'b0;
              st <= S_WAIT;                      // add issued this cycle
            end else ptr <= ptr + 1'b1;
          end
        end

        S_WAIT: if (res_v) begin
          fold_r <= add_res;
          ptr    <= ptr + 1'b1;
          st     <= S_SCAN;
        end

        S_DONE: begin
          out_data  <= fold_r;
          out_valid <= 1'b1;
        end

        default: st <= S_ACC;
      endcase
    end
  end

  // ---- elaboration guards ---------------------------------------------
  //
  // Generate scope AND initial, for the reason the other modules spell
  // out: Vivado and Yosys honour the elaboration-time $error and ignore
  // `initial`; Icarus is the reverse.
  generate
    if (LEVELS < 2) begin : g_levels
      $error("cft_reduce_acc: LEVELS must be at least 2");
    end
    if (ADD_LATENCY < 1) begin : g_lat
      $error("cft_reduce_acc: ADD_LATENCY must be at least 1");
    end
  endgenerate

  initial begin
    if (LEVELS < 2 || ADD_LATENCY < 1) begin
      $display("FATAL: cft_reduce_acc LEVELS=%0d ADD_LATENCY=%0d", LEVELS, ADD_LATENCY);
      $finish;
    end
  end

endmodule
