// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// tb_mulpass_formal: the iterated chunk-column multiplier is exact, for
// every operand pair and every reachable internal state.
//
// cft_mulpass computes a P x P product over NP passes of COLS chunk
// columns and hands it back at pipeline level 5 in ENABLED cycles.
// tb/test_mulpass.py drives the same claim with random operands; this
// harness hands the operands to the solver. The DUT sits behind the
// same pacing the lane array gives it - a phase counter of period NP,
// `en` on the period's last cycle - and behind a model of the pipe's
// S1 register (an `en`-clocked capture of the free inputs). An
// `en`-clocked history of the captured operands is kept six deep, so
// the pair at level 6 is the pair whose product is due at the output,
// and the assertion is simply that they multiply to it.
//
// Nothing about the DUT's initial state is assumed. Its counters,
// delay line, accumulator and output chain start ARBITRARY in the
// solver's world, which is stronger than the simulator's X: the claim
// is that the first operation captured after reset is already exact,
// because the load discards whatever the accumulator held and the
// shift-out replaces every low bit before the product is read.
//
// The geometry is small on purpose - a multiplier is the hardest
// object a SAT solver meets, and 24-bit chunks are fixed by the
// include the DUT shares with the pipe - so the tasks cover the
// mechanism's shapes at the smallest P that reaches each: two passes
// of one column (P=25, the load, one fold, the shift-out, a three-deep
// output chain), three passes (P=49, two folds), and two columns (P=49
// at COLS=2, the one-level in-pass tree). Wider P adds no structure the
// module does not already have at these; the tile's rungs are the same
// generate at P = 53, 113 and 237, and tb_mulpass.sv runs those.

`timescale 1ns/1ps

module tb_mulpass_formal #(
    parameter int P    = 6,
    parameter int COLS = 1,
    // 1: also assert against the plain product a * b. That is a second
    // multiplier for the solver to reason about, and equality between
    // two multiplier circuits is the hard case for SAT - a 10 x 10 was
    // still on its first assertion step after eight minutes - so it is
    // asked only where it is cheap. The column-sum reference below is
    // always asserted and is the equivalence the gate exists for.
    parameter bit FULL = 1'b0,
    // the pass count the .sby expects of this geometry; 0 is not a pass
    // count, so a task that forgot to set it cannot elaborate, and a
    // task whose (P, COLS) do not give the pass count its own table
    // claims cannot elaborate either
    parameter int EXP_NP = 0
) (
    input logic         clk,
    input logic         rst_n,
    input logic [P-1:0] a,
    input logic [P-1:0] b
);

  `include "cft_mulgeom.svh"
  localparam int NP    = (cft_mul_chunks(P) + COLS - 1) / COLS;
  localparam int PHW   = (NP > 1) ? $clog2(NP) : 1;
  localparam int LEVEL = 5;

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

  // ---- the pacer, exactly cft_lanes' ------------------------------------
  logic [PHW-1:0] ph;
  logic           en;
  always_ff @(posedge clk) begin
    if (!rst_n)                  ph <= '0;
    else if (ph >= PHW'(NP - 1)) ph <= '0;
    else                         ph <= ph + 1'b1;
  end
  assign en = rst_n && (ph >= PHW'(NP - 1));

  // ---- the S1 model and the operand history ---------------------------
  // h[k] holds, during the interval after the k-th enabled edge since
  // an operand was captured, that operand: h[1] is the S1 register
  // itself, h[6] the pair whose product the DUT presents at level 5.
  logic [P-1:0] ha [1:LEVEL+1], hb [1:LEVEL+1];
  always_ff @(posedge clk) begin
    if (en) begin
      ha[1] <= a;
      hb[1] <= b;
      for (int k = 2; k <= LEVEL + 1; k = k + 1) begin
        ha[k] <= ha[k-1];
        hb[k] <= hb[k-1];
      end
    end
  end

  logic [2*P-1:0] p;
  cft_mulpass #(.P(P), .COLS(COLS), .LEVEL(LEVEL)) dut (
      .clk(clk), .en(en), .a(ha[1]), .b(hb[1]), .p(p));

  // ---- enabled edges since reset, saturating ---------------------------
  logic [3:0] edges;
  always_ff @(posedge clk) begin
    if (!rst_n)                 edges <= '0;
    else if (en && edges < 4'd8) edges <= edges + 1'b1;
  end

  // ---- the reference: the pipe's own side-by-side column sum ----------
  // cft_fpfma_pipe's private multiplier is pp[k] = ma * mb[k*MCH +: MCH]
  // summed with k*MCH shifts - the structure the suite has held to the
  // golden model at every rung. Written here as one combinational sum
  // over the captured pair, it is the thing cft_mulpass must equal:
  // the same P x MCH partial products, folded in a different order.
  // Equal partial products are what lets the solver match the two
  // circuits term by term instead of proving two multipliers equal.
  localparam int MCH = CFT_MUL_MCH;
  localparam int NMC = cft_mul_chunks(P);
  logic [NMC*MCH-1:0] bref_pad;
  logic [2*P-1:0]     colsum;
  assign bref_pad = {{(NMC*MCH - P){1'b0}}, hb[LEVEL+1]};
  always_comb begin
    logic [2*P+MCH-1:0] acc;
    acc = '0;
    for (int k = 0; k < NMC; k = k + 1)
      acc = acc + ((ha[LEVEL+1] * bref_pad[k*MCH +: MCH]) << (k * MCH));
    colsum = acc[2*P-1:0];
  end

  // ---- the claim --------------------------------------------------------
  // Once six enabled edges have passed since reset, h[6] holds a real
  // captured pair and p must be its column sum - in every cycle of the
  // interval, not only the last. past_valid keeps the solver off the
  // initial step, where `edges` itself is arbitrary and the reset has
  // not yet happened.
  always_comb begin
    if (past_valid && edges >= 4'd6)
      a_colsum: assert (p == colsum);
  end

  generate
    if (FULL) begin : g_full
      always_comb begin
        if (past_valid && edges >= 4'd6)
          a_exact: assert (p == ha[LEVEL+1] * hb[LEVEL+1]);
      end
    end
  endgenerate

  // Non-vacuity: the claim is reached with a product that is not
  // trivially zero, and with one that carries into the top bits.
  always_comb begin
    c_reached: cover (past_valid && edges >= 4'd6 && p != '0);
    c_topbit:  cover (past_valid && edges >= 4'd6 && p[2*P-1]);
  end

endmodule
