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
//   way round. Verified two ways by
//   test_add_is_commutative_so_operand_order_is_free: EXHAUSTIVELY over
//   the interesting-operand pool crossed with itself - every signalling
//   and quiet NaN, both infinities, both zeros, subnormals and the
//   extreme normals against each other - plus 80,000 random pairs
//   across four formats and five attributes. That test asserts its own
//   pair count so this number cannot drift away from it again; it read
//   80,000 here while the test was doing 10,000.
//
// The adder is external. This module issues (a, b) and expects the sum
// ADD_LATENCY cycles later; it carries the destination level alongside
// in its own delay line. That keeps it independent of which adder is
// used, and lets the engine share the one it already has.
//
// THE WIDE INPUT: ENTERING THE COUNTER ABOVE LEVEL 0
//
// A caller that can reduce a whole ALIGNED GROUP of 2^k consecutive
// elements on its own - the engine's beat-wide tree does, in the ALU
// lanes this accumulator leaves idle - holds a value that is exactly
// what level k would have held had those elements been streamed in one
// at a time. The counter says so and it is a statement about the tree
// rather than about timing: inserting 2^k elements into a counter whose
// levels 0..k-1 are empty leaves those levels empty again and one value
// at level k, and that value IS the balanced tree over the group, with
// the pairs the counter would have made. So a group may be handed over
// through `win_*` at level k and NOTHING about the pairing moves.
//
// Two rules the caller keeps, and the engine keeps both:
//
//   * groups arrive in index order, and an element that does NOT
//     arrive in a group arrives at level 0 with an index above every
//     group's - in practice whole aligned groups first and a short
//     tail afterwards, never interleaved. A tail of fewer than 2^k
//     elements cannot carry out of level k-1, so it never reaches the
//     group level and the two never collide.
//   * `win_lvl` does not change while an accumulation runs.
//
// Level `win_lvl` gets its own REGISTER, `slotw`, rather than a second
// write port on the levels RAM. A returning result and a group partial
// can land in the same cycle - a carry above the group level beside
// the next group's placement - and a distributed RAM has one write
// port; that is the same argument the slot0/slotm split is made of,
// one level further up. The invariant that keeps the two apart - a
// RESULT never targets win_lvl while groups are arriving - is checked
// in simulation below rather than assumed.

`timescale 1ns/1ps

module cft_reduce_acc #(
    parameter int W           = 32,   // element width
    // Inputs this can reduce is 2^LEVELS. 40 covers any count a beat
    // engine can stream in a human lifetime and costs 40 registers of
    // W bits; the flush fold walks them once per run.
    parameter int LEVELS      = 40,
    parameter int ADD_LATENCY = 15,
    // Width of a level index ON THE PORTS, which must be
    // $clog2(LEVELS+1) - the guard at the end of the file holds it
    // there. It is a parameter rather than that expression written
    // into the port list because no other module in this tree puts a
    // system function in a port range and the lint gate spans three
    // front ends.
    parameter int LVL_W       = 6
) (
    input  logic         clk,
    input  logic         rst_n,
    // Advance enable, tied high by every caller but the multi-cycle
    // tile's engine, which hands it the lane array's pipeline enable:
    // the external adder then accepts a beat and returns a sum only on
    // enabled edges, so this machine - which counts ADD_LATENCY in
    // adder cycles - has to count the same edges. Reset and `clear`
    // are not gated; they are not part of the schedule.
    input  logic         clk_en,
    input  logic         clear,        // begin a new reduction

    input  logic         in_valid,
    input  logic [W-1:0] in_data,
    output logic         in_ready,

    // ---- the wide input -------------------------------------------
    // A partial covering an aligned group of 2^win_lvl consecutive
    // elements, entering the counter at that level - see the header.
    // Tie win_valid low and this module is exactly what it was.
    input  logic             win_valid,
    input  logic [W-1:0]     win_data,
    input  logic [LVL_W-1:0] win_lvl,
    output logic             win_ready,

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

  // ---- the levels, as one register and one distributed RAM ----------
  //
  // Measured, this module is 5,955 LUT and 10,853 FF of a 120,303-LUT
  // kernel. The flip-flops are the giveaway: 40 x 256 is 10,240 bits,
  // so the whole array had been inferred as registers with a 40:1
  // multiplexer in front of it, and that multiplexer is most of the
  // LUTs. Nothing here wants registers - the array is written once per
  // add and read once per issue, which is a memory.
  //
  // Two things stopped Vivado inferring one, and both are fixable
  // without changing what the module does:
  //
  //   * TWO write statements. `slot[res_lvl]` for a returning result
  //     and `slot[0]` for an arriving input, in the same process. A
  //     distributed RAM has one write port, so two writes force
  //     registers no matter what else is true.
  //   * the writes sat inside the reset process. Nothing resets the
  //     array, but inference is more reliable from a process that
  //     contains the write and nothing else.
  //
  // The first is not a real conflict, and the reason is already load
  // bearing elsewhere in this file: a result NEVER targets level 0.
  // An issue from level t targets t+1, the input path targets 1, and
  // the fold targets ptr, which is at least 1 because the seed
  // consumed the lower index before fold_started went high. The
  // arbitration comment above relies on exactly this to argue that a
  // result and an input cannot contend for a slot. So level 0 has one
  // writer and levels 1..LEVELS-1 have one writer, and splitting them
  // gives each a single port.
  //
  // The invariant is checked in simulation rather than assumed - if it
  // ever stops holding, a result would silently land in the wrong
  // level instead of colliding visibly.
  logic [W-1:0]  slot0;                  // level 0: the input path only
  (* ram_style = "distributed" *)
  logic [W-1:0]  slotm [0:LEVELS-2];     // levels 1..LEVELS-1
  logic [LEVELS-1:0] occ;

  // Level `win_lvl`, once a group has arrived at one: its own register
  // for the reason the header gives - a result and a group partial can
  // want to be placed in the same cycle, and slotm has one write port.
  // wlvl_r is which level that is and wlvl_v whether any group has
  // arrived since the last clear; until one has, every level lives
  // where it always did.
  logic [W-1:0]  slotw;
  logic [LVL_W-1:0] wlvl_r;
  logic          wlvl_v;

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
  //
  // A group partial (win_*) sits between the two: it is not yet in the
  // machine, so a result still beats it, but it stands for 2^win_lvl
  // elements where a single input stands for one, so it goes ahead of
  // the input path. The engine never offers both at once - whole
  // groups first, the tail after - but the order is written down
  // rather than assumed, so the module alone behaves as its bench and
  // the engine both expect.
  logic res_needs_issue, in_needs_issue, win_needs_issue;
  logic win_issue, in_issue;
  assign res_needs_issue = res_v && occ[res_lvl];
  assign win_needs_issue = win_valid && occ[win_lvl];
  assign in_needs_issue  = in_valid && occ[0];
  assign win_issue = (st == S_ACC) && win_needs_issue && !res_needs_issue;
  assign in_issue  = (st == S_ACC) && in_needs_issue && !res_needs_issue &&
                     !win_issue;

  logic fold_issue;
  assign fold_issue = (st == S_SCAN) && fold_started &&
                      (ptr < LEVELS[LW-1:0]) && occ[ptr];

  // The scan's first hit, which seeds the fold rather than issuing an
  // add. Named because the read port below has to know about it.
  logic seed_read;
  assign seed_read = (st == S_SCAN) && !fold_started &&
                     (ptr < LEVELS[LW-1:0]) && occ[ptr];

  assign win_ready = (st == S_ACC) && !(res_needs_issue && win_needs_issue);
  assign in_ready  = (st == S_ACC) &&
                     !(in_needs_issue && (res_needs_issue || win_issue));

  // ---- one read port, not four ---------------------------------------
  //
  // `slot` is LEVELS x W - 40 x 256 bits as instantiated - and it was
  // being read at four places, three of them at a variable index. Each
  // one is a 40:1 multiplexer 256 bits wide, and Vivado has no reason
  // to merge them because nothing in the source says they are
  // exclusive. Measured, this module is 8,171 LUT of a 134,697-LUT
  // kernel: 6% of the tile for an accumulator whose datapath is one
  // add wide.
  //
  // All four reads ARE exclusive, so one port serves them:
  //
  //   - the three adder sources are branches of a single if/else chain
  //     (fold, returning result, new input), so at most one is live;
  //   - the fold SEED reads slot[ptr] when !fold_started, and the fold
  //     ISSUE reads slot[ptr] when fold_started. `fold_started` gates
  //     them apart, so they cannot want the port in the same cycle.
  //   - a result cannot land during the seed cycle: S_DRAIN does not
  //     hand over to S_SCAN until `inflight == 0 && !add_valid`, and
  //     no add is issued before fold_started.
  //
  // So the multiplexer becomes 6 bits wide instead of 256, and the
  // array keeps one read port instead of four.
  logic [LW-1:0] slot_idx;
  logic [W-1:0]  slot_rd;
  always_comb begin
    if      (fold_issue)      slot_idx = ptr;
    else if (res_needs_issue) slot_idx = res_lvl;
    else if (seed_read)       slot_idx = ptr;
    else if (win_issue)       slot_idx = win_lvl;   // the group's level
    else                      slot_idx = '0;   // the input path reads level 0
  end

  // Level 0 is a register and the rest is a RAM, so the one read port
  // is one 2:1 mux wide rather than 40:1. The address is forced to
  // zero for the level-0 case rather than left to wrap to all-ones:
  // the mux discards it either way, but an out-of-range read is an X
  // in simulation and a needless decode in hardware.
  // The wide level is a third case, and a 3:1 mux rather than a 2:1.
  // It is only ever selected once a group HAS arrived, because until
  // then wlvl_v is low and nothing can be occupied at that level.
  logic [LW-1:0] rd_addr, wr_addr;
  assign rd_addr = (slot_idx == '0) ? '0 : (slot_idx - 1'b1);
  assign wr_addr = res_lvl - 1'b1;
  assign slot_rd = (slot_idx == '0)                  ? slot0
                 : (wlvl_v && (slot_idx == wlvl_r))  ? slotw
                 :                                     slotm[rd_addr];

  // The two write ports, each in its own process with no reset, which
  // is the shape distributed-RAM inference wants. The enables are the
  // same conditions the placement block below uses, with the reset
  // term made explicit because that block's `else` no longer covers
  // them.
  logic res_place, in_place, win_place, res_to_w;
  // A result that targets the wide level. It cannot happen while the
  // caller keeps the header's rules, and the assertion below says so -
  // but it is ROUTED correctly rather than left to corrupt slotm, so
  // the storage stays consistent even under a caller that breaks them.
  assign res_to_w  = wlvl_v && (res_lvl == wlvl_r);   // LW == LVL_W, guarded
  assign res_place = rst_n && !clear && clk_en && res_v && (st != S_WAIT) &&
                     !occ[res_lvl];
  assign in_place  = rst_n && !clear && clk_en && (st == S_ACC) &&
                     in_valid && in_ready && !occ[0];
  assign win_place = rst_n && !clear && clk_en && (st == S_ACC) &&
                     win_valid && win_ready && !occ[win_lvl];

  always_ff @(posedge clk) begin
    if (in_place) slot0 <= in_data;
  end

  always_ff @(posedge clk) begin
    if (res_place && !res_to_w) slotm[wr_addr] <= add_res;
  end

  always_ff @(posedge clk) begin
    if      (win_place)             slotw <= win_data;
    else if (res_place && res_to_w) slotw <= add_res;
  end

  // synthesis translate_off
  always_ff @(posedge clk) begin
    if (res_place && (res_lvl == '0))
      $fatal(1, "cft_reduce_acc: a result targeted level 0 - the split of slot0 from slotm is invalid");
    if (clk_en && (st == S_ACC) && win_valid && win_ready && (win_lvl == '0))
      $fatal(1, "cft_reduce_acc: a group arrived at level 0 - that level belongs to the single-element input");
    if (res_place && res_to_w)
      $fatal(1, "cft_reduce_acc: a result targeted the wide level %0d - groups and single elements overlapped, and the pairing is no longer the counter's", wlvl_r);
  end
  // synthesis translate_on

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
      add_a     = slot_rd;
      add_b     = fold_r;
    end else if (res_needs_issue) begin
      add_valid = 1'b1;
      add_a     = slot_rd;
      add_b     = add_res;
    end else if (win_issue) begin
      // The group already at win_lvl covers the LOWER indices, as a
      // level's contents always do; the arriving group is the upper
      // half and the sum carries to win_lvl + 1.
      add_valid = 1'b1;
      add_a     = slot_rd;
      add_b     = win_data;
    end else if (in_valid && in_ready && in_needs_issue) begin
      add_valid = 1'b1;
      add_a     = slot_rd;
      add_b     = in_data;
    end
  end

  // Destination level for whatever is being issued this cycle.
  logic [LW-1:0] issue_lvl;
  always_comb begin
    if (fold_issue)                                 issue_lvl = ptr;
    else if (res_needs_issue)                       issue_lvl = res_lvl + 1'b1;
    else if (win_issue)                             issue_lvl = win_lvl + 1'b1;
    else                                            issue_lvl = {{(LW-1){1'b0}}, 1'b1};
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
      wlvl_r    <= '0;
      wlvl_v    <= 1'b0;
      out_valid <= 1'b0;
      out_data  <= '0;
      out_flags <= 5'b0;
      for (i = 0; i < ADD_LATENCY; i = i + 1) begin
        dly_v[i]   <= 1'b0;
        dly_lvl[i] <= '0;
      end
    end else if (clk_en) begin
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
      // The value itself is written by the two single-port processes
      // above; what stays here is the occupancy bit, which does need
      // the reset. res_place and in_place are the same conditions as
      // the `else` arms below.
      if (res_v && (st != S_WAIT)) begin
        if (occ[res_lvl]) occ[res_lvl] <= 1'b0;      // consumed by the re-issue
        else              occ[res_lvl] <= 1'b1;
      end

      // A group partial, at its own level. Its level and the input's
      // are different by the header's rules and by the assertion
      // above, so these two arms never write the same bit of occ.
      if (st == S_ACC && win_valid && win_ready) begin
        if (occ[win_lvl]) occ[win_lvl] <= 1'b0;      // consumed by the issue
        else              occ[win_lvl] <= 1'b1;
        wlvl_r <= win_lvl;
        wlvl_v <= 1'b1;
      end

      if (st == S_ACC && in_valid && in_ready) begin
        if (occ[0]) occ[0] <= 1'b0;                  // consumed by the issue
        else        occ[0] <= 1'b1;
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
              fold_r <= slot_rd;          // seed_read selected slot[ptr]
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
    if (LVL_W != $clog2(LEVELS + 1)) begin : g_lvlw
      $error("cft_reduce_acc: LVL_W must be $clog2(LEVELS+1)");
    end
  endgenerate

  initial begin
    if (LEVELS < 2 || ADD_LATENCY < 1 || LVL_W != $clog2(LEVELS + 1)) begin
      $display("FATAL: cft_reduce_acc LEVELS=%0d ADD_LATENCY=%0d LVL_W=%0d",
               LEVELS, ADD_LATENCY, LVL_W);
      $finish;
    end
  end

endmodule
