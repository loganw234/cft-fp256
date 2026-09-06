// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_mulpass: the chunk-column significand multiplier, iterated.
//
// cft_fpfma_pipe's own multiplier lays every column of a P x P product
// side by side - pp[k] = ma * mb[24k +: 24], fp256: ten columns of
// 237 x 24 - and sums them through four registered tree levels, so the
// product occupies pipeline levels 2 through 6 and costs quadratically
// in P. This module computes the SAME integer with COLS columns
// instead of all of them: it walks the multiplier's chunks COLS at a
// time over NP = ceil(chunks / COLS) passes, one pass per clock,
// summing each pass's columns through a small tree and folding the
// pass sums into an accumulator whose low bits are shifted out as they
// become final. The exact product is integer arithmetic, and no
// summation order of the same partial products changes an integer -
// so the product handed back is bit-identical to the side-by-side
// array's by construction, and the pipe's alignment, normalisation
// and rounding downstream never learn which one built it.
//
// THE CLOCK IT RUNS ON, AND THE CLOCK IT ANSWERS IN
//
// The pipe around it advances on `en`, the tile's pipeline enable: in
// the multi-cycle configuration every stage register in the lane
// array is held for NP - 1 of every NP cycles (cft_lanes generates
// `en` from the live rung's pass count), so in ENABLED-edge terms the
// pipe is exactly the single-pass pipe. This block is the one thing
// that runs on the wall clock in between: its pass counter, chunk
// select, columns, tree and accumulator tick every cycle, and its
// result re-enters the enabled domain through a chain of `en`-clocked
// registers sized so the product lands at exactly the level the
// side-by-side tree delivered it. Nothing else in the pipe moves.
//
// Timing, with E_n the enabled edge at which the pipe's S1 registers
// capture operation n's significands (a, b here; stable until
// E_{n+1} = E_n + NP because S1 only advances on `en`), and L the
// number of tree levels COLS needs (ceil(log2 COLS), 0 for one
// column):
//
//   E_n         pidx <= 0                  (`en` was high in the cycle ending here)
//   E_n + 1     a_r <= a; bsel_r <= chunk group 0
//   E_n + 2     pcol <= a_r * bsel_r        pass 0 columns
//   ...         tree levels 1..L, one per edge
//   E_n + 3+L   acc/low <= pass 0's sum     LOAD (en delayed 3+L marks it)
//   E_n + 3+L+p pass p folded in            p = 1 .. NP-1
//   E_n + NP+2+L  the last pass folded: acc/low = the whole product
//   E_n + NP+3+L  mp_done <= {acc, low}     (the same edge loads op n+1's pass 0)
//
// so mp_done holds op n's product from E_n + D until E_n + NP + D,
// D = NP + 3 + L. The first `en`-clocked register of the chain
// captures at E_{n+KD+1} with KD = floor(D / NP): that edge is inside
// the window because KD*NP <= D < (KD+1)*NP, and at the window's far
// edge the register still samples the old value. LEVEL - KD registers
// then carry it to level LEVEL, which for the pipe is 5: `p` holds
// op n's product during [E_{n+5}, E_{n+6}), which is precisely when
// the pipe's private s6_mp_r held it. The guards refuse a geometry
// where KD would exceed LEVEL - 1.
//
// WHY THE LOW BITS ARE SHIFTED OUT
//
// Pass p's sum is ma times a K-bit slice of mb, K = COLS * 24,
// weighted 2^(K*p). Bits below K*(p+1) of the running total are never
// touched by a later pass, so after each fold the low K bits are
// final and move into a shift register, and the accumulator keeps
// only the P+1 bits above them: R < 2^(P+1) always, because
// R_next = floor((R + psum) / 2^K) < 2^(P+1-K) + 2^P. The fold is a
// fixed (P+K+1)-bit add with no variable shift, and the product is
// {R, low} at the end. Truncating that to 2P bits is exact - the
// product is below 2^(2P) - which is the same argument the pipe's own
// S6 makes.
//
// The pass counter saturates rather than wraps, so a lane that is NOT
// the live rung - and therefore sees a longer `en` period than its own
// NP - folds zeros for the extra passes and produces the right
// product anyway; a lane seeing a SHORTER period than its NP produces
// garbage, which is fine because such a lane is not the live one and
// nothing reads it. Only the live rung's product matters, and for the
// live rung the period IS NP by construction (cft_lanes).

`timescale 1ns/1ps

module cft_mulpass #(
    parameter int P     = 237,   // significand width, 1 + MAN_W
    parameter int COLS  = 1,     // columns built; must be fewer than the chunks
    parameter int LEVEL = 5      // enabled intervals from S1 capture to product
) (
    input  logic           clk,
    input  logic           en,   // the pipe's enable: high in the LAST cycle of each interval
    input  logic [P-1:0]   a,    // the S1 significands, stable per interval
    input  logic [P-1:0]   b,
    output logic [2*P-1:0] p     // a * b, at level LEVEL
);

  `include "cft_mulgeom.svh"

  localparam int MCH = CFT_MUL_MCH;
  localparam int NMC = cft_mul_chunks(P);            // columns a full product needs
  localparam int C   = COLS;
  localparam int NP  = (NMC + C - 1) / C;            // passes
  localparam int K   = C * MCH;                      // multiplier bits per pass
  localparam int BW  = NP * K;                       // the multiplier, padded to whole passes
  localparam int PSW = P + K;                        // one pass's column sum, exact
  localparam int L   = (C <= 1) ? 0 : (C <= 2) ? 1 : (C <= 4) ? 2 : (C <= 8) ? 3 : 4;
  localparam int D   = NP + 3 + L;                   // edges from E_n to mp_done
  localparam int KD  = D / NP;                       // whole intervals in D
  localparam int CH  = LEVEL - KD;                   // en-clocked registers to LEVEL

  // ---- elaboration guards -------------------------------------------
  // Generate scope AND initial, for the reason every module here
  // spells out: Vivado and Yosys honour the generate-scope $error and
  // ignore `initial`; Icarus is the reverse.
  generate
    if (C < 1 || C > 16) begin : g_bad_cols
      $error("cft_mulpass: COLS must be 1..16");
    end
    if (NMC < 2 || C >= NMC) begin : g_single_pass
      $error("cft_mulpass: a lane with COLS >= its chunk count is single-pass - use the pipe's own tree");
    end
    if (CH < 1) begin : g_too_slow
      $error("cft_mulpass: NP + 3 + L exceeds the level budget - the product cannot reach LEVEL");
    end
  endgenerate

  initial begin
    if (C < 1 || C > 16 || NMC < 2 || C >= NMC || CH < 1) begin
      $display("FATAL: cft_mulpass P=%0d COLS=%0d chunks=%0d passes=%0d tree=%0d KD=%0d LEVEL=%0d",
               P, C, NMC, NP, L, KD, LEVEL);
      $finish;
    end
  end

  // ---- the pass counter and the enable's delayed copies -------------
  // pidx names the pass whose chunk group is being selected this
  // cycle: 0 in the cycle after an enabled edge, then up, saturating
  // at NP (a group of zeros) for a period longer than this lane's own.
  localparam int PXW = $clog2(NP + 1);
  logic [PXW-1:0] pidx;
  always_ff @(posedge clk) begin
    if (en)              pidx <= '0;
    else if (pidx < NP)  pidx <= pidx + 1'b1;
  end

  // en_d[j] is `en` delayed by j cycles. The accumulator's load and the
  // product capture both key off en_d[3+L] - see the header's timeline.
  logic [3+L:1] en_d;
  always_ff @(posedge clk) en_d <= {en_d[2+L:1], en};

  // ---- chunk-group select, then the columns -------------------------
  // b padded to (NP+1) whole groups, so the saturated pass index reads
  // zeros and no select is ever out of range. The group is picked a
  // bit at a time from a variable base - a K-wide mux over NP+1
  // positions - and registered beside a copy of `a`, so the DSP
  // columns see flip-flops on both inputs.
  logic [(NP+1)*K-1:0] bpad;
  assign bpad = {{((NP+1)*K - P){1'b0}}, b};

  logic [K-1:0] bsel_w, bsel_r;
  logic [P-1:0] a_r;
  always_comb begin
    for (int i = 0; i < K; i = i + 1)
      bsel_w[i] = bpad[pidx * K + i];
  end
  always_ff @(posedge clk) begin
    a_r    <= a;
    bsel_r <= bsel_w;
  end

  // The columns and the in-pass tree, in the pipe's own fixed shape
  // (sixteen entries, four levels, pairwise shifts of 24/48/96/192)
  // at the pass-sum width PSW. Entries past COLS are constant zero and
  // levels past L are never read, so synthesis keeps exactly the COLS
  // columns and the L levels; `if (c < C)` is what keeps a simulator
  // from multiplying by the zeros.
  logic [PSW-1:0] pcol [0:15];
  logic [PSW-1:0] t1   [0:7];
  logic [PSW-1:0] t2   [0:3];
  logic [PSW-1:0] t3   [0:1];
  logic [PSW-1:0] t4;

  always_ff @(posedge clk) begin : columns_and_tree
    for (int c = 0; c < 16; c = c + 1) begin
      if (c < C) pcol[c] <= a_r * bsel_r[c*MCH +: MCH];
      else       pcol[c] <= '0;
    end
    for (int j = 0; j < 8; j = j + 1)
      t1[j] <= pcol[2*j] + (pcol[2*j+1] << MCH);
    for (int i = 0; i < 4; i = i + 1)
      t2[i] <= t1[2*i] + (t1[2*i+1] << (2*MCH));
    for (int i = 0; i < 2; i = i + 1)
      t3[i] <= t2[2*i] + (t2[2*i+1] << (4*MCH));
    t4 <= t3[0] + (t3[1] << (8*MCH));
  end

  logic [PSW-1:0] psum;
  generate
    if (L == 0)      begin : g_l0 assign psum = pcol[0]; end
    else if (L == 1) begin : g_l1 assign psum = t1[0];   end
    else if (L == 2) begin : g_l2 assign psum = t2[0];   end
    else if (L == 3) begin : g_l3 assign psum = t3[0];   end
    else             begin : g_l4 assign psum = t4;      end
  endgenerate

  // ---- the fold: accumulate high, shift the final low bits out ------
  logic           ld;
  logic [P:0]     acc;
  logic [BW-1:0]  low;
  logic [P+K:0]   s;

  assign ld = en_d[3+L];
  always_comb
    s = {{K{1'b0}}, (ld ? {(P+1){1'b0}} : acc)} + {1'b0, psum};

  always_ff @(posedge clk) begin
    acc <= s[P+K:K];
    low <= {s[K-1:0], low[BW-1:K]};
  end

  // ---- the completed product, back into the enabled domain ----------
  // Captured at the edge that loads the next operation's first pass,
  // when acc/low hold the finished product for exactly one cycle.
  logic [P+BW:0] mp_done;
  always_ff @(posedge clk) begin
    if (ld) mp_done <= {acc, low};
  end

  // The chain: CH registers on `en`, the first sampling mp_done inside
  // its validity window (the header's KD argument), the last at LEVEL.
  // {acc, low} is P+1+BW bits; the product is below 2^(2P), so the
  // slice keeps every bit that can be set.
  logic [2*P-1:0] chain [0:CH-1];
  always_ff @(posedge clk) begin
    if (en) begin
      chain[0] <= mp_done[2*P-1:0];
      for (int i = 1; i < CH; i = i + 1)
        chain[i] <= chain[i-1];
    end
  end

  assign p = chain[CH-1];

endmodule
