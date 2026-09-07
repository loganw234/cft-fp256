// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_mulfold_formal: LEMMA A of cft_mulpass' exactness - the pass fold
// is exact integer arithmetic, at the real chunk width, for every pass
// geometry the tile builds.
//
// WHAT IS ABSTRACTED, AND BY WHOM
//
// The whole claim "cft_mulpass' product equals the side-by-side array's"
// is a bounded model check over two multipliers, which is the shape a
// SAT solver does worst at: at the real 24-bit chunk the smallest
// multi-pass geometry did not return in four hours (docs/VALIDATION.md,
// 2026-09-06). It splits into lemmas that each avoid the hard part.
//
//   A (this file)  With the column registers taken as FREE VALUES, the
//                  tree, the shift-accumulate and the level chain
//                  deliver, at LEVEL, the sum of one operation's own
//                  free values at their column weights.
//   B (tb_mulsel)  The operands handed to the columns on pass p are the
//                  captured `a` and chunk group p of the captured `b`.
//   C (tb_mulsel)  The column register holds those operands' product,
//                  and a column the geometry does not build holds zero.
//
// A carries no multiplier at all: the property is linear in the free
// values, so it closes at P = 237 with 24-bit chunks. B and C carry no
// multiplier reasoning either. Multiplication is a function, so equal
// operands give equal products, and substituting B and C into A's sum
// yields
//
//     p = sum over k of (a * b[24k +: 24]) << 24k, truncated to 2P
//
// which is the side-by-side array's own expression in
// cft_fpfma_pipe.sv (g_mul_local). formal/README.md writes the
// composition out in full, including the side-conditions below.
//
// HOW THE ABSTRACTION IS MADE
//
// Not by editing or copying the RTL: formal/mulexact.sby flattens the
// real rtl/cft_mulpass.sv into this harness, makes every `dut.pcol[c]`
// a yosys `cutpoint` - an unconstrained $anyseq in place of the
// register and of the multiplier that fed it - and then aliases this
// harness's own `qw<c>` onto the cut nets with `connect -set`, so the
// reference below is built from exactly the values the DUT's tree sees.
// The .sby then CHECKS the cut, with `select -assert-count 0 t:$mul` on
// the prepared model: a cut that silently failed to apply would leave
// the multiplier in the netlist and fail that assertion, and would also
// fail this proof outright, because pcol would then be a product of the
// tied-off operands while the reference is free.
//
// THE COLUMNS THE CUT COVERS
//
// The module's in-pass tree is a fixed sixteen-entry, four-level shape
// of which the first L levels are read, L = ceil(log2 COLS); psum is
// that level's root, so exactly NC = 2^L column registers reach it and
// the rest are dead. NC, not COLS: at COLS = 3 the tree is two levels
// and reads four columns, of which the module drives the fourth to
// zero. This harness sums all NC of them at the tree's own weights.
//
// THE SIDE-CONDITIONS
//
// Two assumptions on the abstracted values, both of them properties the
// real column registers have and tb_mulsel_formal proves they have:
//
//   * a built column is below 2^(P+24) - `a` is below 2^P and a chunk
//     is below 2^24 - so the pass sum fits the tree's own P + COLS*24
//     bits and the lemma is not about a truncation the design never
//     performs;
//   * a column the geometry does not build (COLS <= c < NC) is zero.
//
// WHAT IS NOT ASSUMED
//
// Nothing about the DUT's initial state. cft_mulpass has no reset at
// all - pass counter, enable delay line, accumulator, shift-out
// register, the completed-product latch and the level chain all start
// arbitrary - and the bound covers reset, the pipeline's fill and
// enough further complete operations that the operation under test had
// real operations before it.

`timescale 1ns/1ps

module tb_mulfold_formal #(
    parameter int P      = 53,
    parameter int COLS   = 1,
    // the pass count mulexact.sby expects of this geometry; 0 is not a
    // pass count, so a task that forgot to set it cannot elaborate
    parameter int EXP_NP = 0
) (
    input logic clk,
    input logic rst_n
);

  `include "cft_mulgeom.svh"

  localparam int MCH   = CFT_MUL_MCH;
  localparam int NMC   = cft_mul_chunks(P);
  localparam int C     = COLS;
  localparam int NP    = (NMC + C - 1) / C;   // passes
  localparam int K     = C * MCH;             // multiplier bits per pass
  localparam int PSW   = P + K;               // one pass's column sum, exact
  localparam int BW    = NP * K;              // the shift-out register
  localparam int FW    = P + BW + 2;          // the reference accumulator
  localparam int PHW   = (NP > 1) ? $clog2(NP) : 1;
  localparam int RPW   = $clog2(NP + 2);
  localparam int LEVEL = 5;
  // the module's own in-pass tree depth, and the columns it reaches
  localparam int L     = (C <= 1) ? 0 : (C <= 2) ? 1 : (C <= 4) ? 2 : (C <= 8) ? 3 : 4;
  localparam int NC    = 1 << L;

  // The reference's own delay to the enabled domain, derived the same
  // way cft_mulpass derives its own (see that file's timeline). The
  // reference reaches its completed product DR = NP + 3 edges after the
  // operation was captured - three, not 3+L, because this harness
  // applies no tree delay: it sums the free values in the cycle they
  // are presented, where the DUT's tree takes L edges to do it.
  localparam int DR  = NP + 3;
  localparam int RKD = DR / NP;
  localparam int RCH = LEVEL - RKD;

  // The geometry, cross-checked. mulexact.sby states the pass count it
  // believes each (P, COLS) pair has; cft_mulgeom.svh's own functions
  // derive it here, and a disagreement - including a `chparam` that
  // silently matched nothing and left the defaults in place - refuses to
  // elaborate rather than proving something about the wrong rung.
  generate
    if (EXP_NP != NP) begin : g_bad_geom
      $error("EXP_NP disagrees with the pass count derived from P and COLS");
    end
  endgenerate

  // ---- the reset shape: low at the first step, high after ------------
  logic past_valid = 1'b0;
  always_ff @(posedge clk) past_valid <= 1'b1;
  always_comb begin
    if (!past_valid) assume (!rst_n);
    else             assume (rst_n);
  end

  // ---- the pacer, exactly cft_lanes' ---------------------------------
  logic [PHW-1:0] ph;
  logic           en;
  always_ff @(posedge clk) begin
    if (!rst_n)                  ph <= '0;
    else if (ph >= PHW'(NP - 1)) ph <= '0;
    else                         ph <= ph + 1'b1;
  end
  assign en = rst_n && (ph >= PHW'(NP - 1));

  // ---- the free column values ----------------------------------------
  // One per column the module's tree reads; mulexact.sby aliases qw<c>
  // onto the cut dut.pcol[c]. Eight is the widest tree any rung of the
  // tile asks for (fp256 at MUL_PASSES=2 builds five columns behind a
  // three-level tree, which reads eight).
  (* keep *) logic [PSW-1:0] qw0;
  (* keep *) logic [PSW-1:0] qw1;
  (* keep *) logic [PSW-1:0] qw2;
  (* keep *) logic [PSW-1:0] qw3;
  (* keep *) logic [PSW-1:0] qw4;
  (* keep *) logic [PSW-1:0] qw5;
  (* keep *) logic [PSW-1:0] qw6;
  (* keep *) logic [PSW-1:0] qw7;

  logic [8*PSW-1:0] qv;
  assign qv = {qw7, qw6, qw5, qw4, qw3, qw2, qw1, qw0};

  // the range a real column product satisfies, and the zero the module
  // drives into a column its geometry does not build
  generate
    if (PSW > P + MCH) begin : g_qrange
      always_comb
        for (int c = 0; c < C; c = c + 1)
          assume (qv[c*PSW + P + MCH +: PSW - P - MCH] == '0);
    end
    if (NC > C) begin : g_qzero
      always_comb
        for (int c = C; c < NC; c = c + 1)
          assume (qv[c*PSW +: PSW] == '0);
    end
  endgenerate

  // ---- the DUT --------------------------------------------------------
  // Operands tied off: after the cut nothing in the module reads them.
  // If the cut did NOT apply, pcol would be zero and this proof would
  // fail loudly rather than pass on an abstraction that never happened.
  logic [2*P-1:0] p;
  cft_mulpass #(.P(P), .COLS(COLS), .LEVEL(LEVEL)) dut (
      .clk(clk), .en(en), .a('0), .b('0), .p(p));

  // ---- enabled edges since reset, saturating --------------------------
  logic [3:0] edges;
  always_ff @(posedge clk) begin
    if (!rst_n)                  edges <= '0;
    else if (en && edges < 4'd8) edges <= edges + 1'b1;
  end

  // ---- the reference: exact accumulation of one operation's columns ---
  // cft_mulpass presents operation n's pass-p columns on pcol during
  // the cycle that starts at E_n + 2 + p (its own timeline: pidx = p in
  // [E_n+p, E_n+1+p), the operand registers take it one edge later, the
  // columns one edge after that). `en` delayed three cycles is high in
  // exactly the cycle that starts at E_n + 2, so `newop` marks the
  // arrival of a fresh operation's pass 0 and the NP - 1 cycles after
  // it are its remaining passes.
  logic [3:1] ed;
  always_ff @(posedge clk) ed <= {ed[2:1], en};
  logic newop;
  assign newop = ed[3];

  // the pass's column sum, at the tree's own width and weights
  logic [PSW-1:0] qsum;
  always_comb begin
    logic [PSW-1:0] t;
    t = '0;
    for (int c = 0; c < NC; c = c + 1)
      t = t + PSW'(qv[c*PSW +: PSW] << (c * MCH));
    qsum = t;
  end

  // the accumulation: a plain weighted sum, no shift-out, no truncation
  // - the arithmetic the module's shift-accumulate has to equal.
  logic [RPW-1:0] rp;
  logic [FW-1:0]  racc, rterm;
  always_comb begin
    rterm = '0;
    for (int j = 0; j < NP; j = j + 1)
      if (rp == RPW'(j)) rterm = FW'(qsum) << (K * j);
  end
  always_ff @(posedge clk) begin
    if (newop) begin
      racc <= FW'(qsum);
      rp   <= RPW'(1);
    end else begin
      racc <= racc + rterm;
      if (rp < RPW'(NP)) rp <= rp + 1'b1;
    end
  end

  // Operation n's sum is complete at edge E_n + NP + 2 and is latched
  // one edge later, at the `newop` edge of operation n + 1 - the same
  // edge at which cft_mulpass latches mp_done. RKD/RCH then carry it to
  // LEVEL on `en`, by the module header's own KD argument.
  logic [FW-1:0] rdone;
  always_ff @(posedge clk) if (newop) rdone <= racc;

  logic [2*P-1:0] rchain [0:RCH-1];
  always_ff @(posedge clk) begin
    if (en) begin
      rchain[0] <= rdone[2*P-1:0];
      for (int i = 1; i < RCH; i = i + 1)
        rchain[i] <= rchain[i-1];
    end
  end

  // ---- the claim -------------------------------------------------------
  // Once LEVEL + 1 enabled edges have passed since reset, the operation
  // whose product the DUT presents at LEVEL is one whose whole pass
  // window happened after reset, and the product must be its columns'
  // weighted sum - in every cycle of the interval, not only the last.
  always_comb begin
    if (past_valid && edges >= 4'd6)
      a_fold: assert (p == rchain[RCH-1]);
  end

  // Non-vacuity: the claim is reached with a product that is not
  // trivially zero, and with one that carries into the top bit.
  always_comb begin
    c_reached: cover (past_valid && edges >= 4'd6 && p != '0);
    c_topbit:  cover (past_valid && edges >= 4'd6 && p[2*P-1]);
  end

endmodule
