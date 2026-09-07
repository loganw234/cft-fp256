// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_fpfma_pipe v1: the staged IEEE-754 fusedMultiplyAdd pipeline.
// Same ports and same bit-exact contract as the v0 behavioural wrapper
// it replaces (fixed latency, in_valid -> out_valid after LATENCY
// cycles, no stalls); the difference is real stage boundaries so the
// datapath closes timing at speed instead of ~65 MHz (fp32) / ~14 MHz
// (fp256) measured for the v0 single cloud.
//
// The significand multiplier is STRUCTURALLY staged - the single
// biggest lesson of the first v1 QoR pass: registering a raw
// 237x237 product leaves a ~50ns 196-DSP cascade in one cycle that
// no retiming rescues. Here mb is decomposed into 24-bit chunks
// (fp256: 10 partial products of 237x24, each a short DSP column),
// then reduced through four registered tree levels with compounding
// 24/48/96/192-bit shifts. Narrow formats degenerate gracefully
// (fp32: one chunk, the tree levels are pass-through registers).
//
// Stage map (LATENCY = 16 edges, S0..S15):
//   S0    input registers
//   S1    unpack, classify, specials sideband
//   S2    partial products  pp[k] = ma * mb[24k +: 24]
//   S3    tree L1: q[j] = pp[2j] + (pp[2j+1] << 24)
//   S4    tree L2: t[i] = q[2i] + (q[2i+1] << 48)   + alignment prep
//   S5    tree L3: u[i] = t[2i] + (t[2i+1] << 96)
//   S6    tree L4: mp   = u[0]  + (u[1]  << 192)    (product complete)
//   S7    coarse align shift (64-bit granules) + coarse sticky
//   S8    fine align shift + marker -> appended-bit operands
//   S9    split add low halves: sum, big-small, small-big in parallel
//   S10   split add high halves + magnitude/sign select; strip the
//         appended marker into the explicit sticky rail
//   S11   LEADING-ZERO COUNT (cft_lzcone): the per-64-bit chunk
//         zero-detect, two balanced (valid, count) trees and the chunk
//         mux between them - the normalise distance, registered
//   S12   coarse normalize shift (whole 64-bit granules) + the
//         exponent/zero/sticky rails
//   S13   fine normalize shift + the round stage's exponent arithmetic
//   S14   round-window extraction (clamped and as-if-unbounded),
//         attribute-directed increment, tininess-after-rounding
//   S15   pack + specials mux -> output registers
//
// S11 became a register boundary of its own on 2026-09-07
// (docs/studies/OPT-C-timing.md idea 1). Before that the whole
// leading-zero cone and the coarse shift shared one cycle, and the
// routed reports had that cone as the worst path on every part: 8.77 ns
// of an 11.55 ns fp256 path was "work out how far to shift". The
// register-name prefixes s11_*, s12_*, s13_*, s14_* were fixed when
// the LZC and the coarse shift shared a stage, and they were NOT
// renamed when the stage split, so from S12 on a prefix lags its
// pipeline level by one: s11_* is level 12, s14_* is level 15. Names
// are names, levels are levels - which is exactly why the
// rounding-attribute delay line's taps are written relative to DEPTH
// and did not have to move. The registers at level 11 are r11_*.
//
// The pipe advances on `en`, a pipeline enable that is tied high in the
// shipping configuration and folds away. MUL_PASSES > 1 replaces the
// side-by-side multiplier (S2..S6) with cft_mulpass, which iterates a
// subset of the chunk columns on the wall clock while `en` holds every
// other stage; the product lands at the same level in enabled cycles,
// so the stage map above is unchanged and so are the bits. The rung's
// throughput drops to one beat per NP cycles, which is the trade the
// multi-cycle tile makes deliberately (docs/ARCHITECTURE.md).
//
// Marker/sticky safety carries over from v0 strengthened: the
// appended LSB participates in the S9/S10 subtract exactly (floor +
// remainder), then becomes an explicit sticky bit for rounding, so
// no shift can move its weight. An all-zero value window is an exact
// zero ONLY when that residue is also clear; otherwise the value is a
// bare epsilon, below the smallest subnormal, and each rounding
// attribute disposes of it its own way (toward zero under RTZ and on
// the far side under a directed attribute; away from it under RUP for
// a positive value, giving the minimum subnormal).

`timescale 1ns/1ps

module cft_fpfma_pipe #(
    parameter int EXP_W   = 8,
    parameter int MAN_W   = 23,
    parameter int LATENCY = 16,
    // Take the significand product from mul_p instead of building a
    // multiplier here. See the mul_* ports for the contract. Default 0
    // keeps every existing instantiation bit-identical.
    parameter bit EXT_MUL = 1'b0,
    // Take the normalised significand from nrm_d instead of building
    // the two normalise shifters here. See the nrm_* ports. Default 0
    // keeps every existing instantiation bit-identical, and the two
    // parameters are independent - a lane may share either, both or
    // neither.
    parameter bit EXT_NORM = 1'b0,
    // Width of the normalise window, for the nrm_* ports only - the
    // localparam NW below is the one the datapath uses, and it is
    // declared after the port list so it cannot be named here. DERIVED:
    // do not override. NW = GW = VW+1 = 2P + SH + 2 with P = MAN_W+1
    // and SH = P+4, which reduces to 3*MAN_W + 9. An elaboration guard
    // below asserts the two agree, because a silent disagreement would
    // truncate a significand window and return a wrong result with
    // clean flags.
    parameter int NRM_W = 3 * MAN_W + 9,
    // Take the ALIGNED small operand from aln_d instead of building the
    // two alignment shifters here. Same shape as EXT_NORM; independent
    // of it and of EXT_MUL. Default 0 keeps every existing
    // instantiation bit-identical.
    parameter bit EXT_ALIGN = 1'b0,
    // Width of the alignment window, for the aln_* ports only. DERIVED,
    // do not override: GW-1 = 3*MAN_W + 8, guarded below.
    parameter int ALN_W = 3 * MAN_W + 8,
    // The multi-cycle multiplier's pass BUDGET (rtl/cft_mulgeom.svh).
    // 1, the default, builds every chunk column side by side - the
    // shipping pipe, unchanged. Above 1 the lane builds
    // ceil(chunks / MUL_PASSES) columns and iterates them
    // (cft_mulpass), which needs the whole pipe held on `en` for
    // NP - 1 of every NP cycles, NP = ceil(chunks / columns). A lane
    // whose chunk count fits the budget - fp32's one column always,
    // fp64's three under a budget of 3 or more - stays single-pass.
    parameter int MUL_PASSES = 1,
    // The `en` period whoever paces this pipe believes this lane
    // needs, cross-checked against the count derived here; 0 skips
    // the check (a bench that ties en high). cft_lanes passes the
    // period it will actually generate, so a geometry disagreement
    // between the two files is an elaboration error and not a wrong
    // product with clean flags.
    parameter int MUL_PERIOD = 0
) (
    input  logic                 clk,
    input  logic                 rst_n,
    // Pipeline enable. Every stage register - S0 through S15, the
    // rounding-attribute and valid delay lines, the sideband - advances
    // only on a cycle with en high, so in enabled-edge terms the pipe
    // is the same pipe at every MUL_PASSES. Tie high for the
    // single-pass configuration; the multi-cycle one takes it from
    // cft_lanes' phase counter. out_valid is gated by it too: one
    // pulse per result, in the last cycle d holds it.
    input  logic                 en,
    input  logic                 in_valid,
    input  logic [2:0]           rnd,      // rounding attribute, per op
    // Precomputed result. When byp is high the datapath's answer is
    // discarded and byp_d/byp_f are delivered at the output instead,
    // carried down the same sideband the specials already use. This is
    // how the non-arithmetic operations (cft_simpleops) reach the
    // output without a latency-matching delay line of their own.
    input  logic                 byp,
    input  logic [EXP_W+MAN_W:0] byp_d,
    input  logic [4:0]           byp_f,
    input  logic [EXP_W+MAN_W:0] a,
    input  logic [EXP_W+MAN_W:0] b,
    input  logic [EXP_W+MAN_W:0] c,
    output logic                 out_valid,
    output logic [EXP_W+MAN_W:0] d,
    output logic [4:0]           flags,

    // ---- shared-multiplier port (EXT_MUL) ---------------------------
    //
    // With EXT_MUL = 0 (the default, and what every existing
    // instantiation gets) these are inert: mul_a/mul_b still carry the
    // stage-1 significands out for whoever wants them, mul_p is
    // ignored, and the internal multiplier runs exactly as before. The
    // point of the default is that adding this port changed nothing.
    //
    // With EXT_MUL = 1 the internal multiplier is not built. The lane
    // hands its stage-1 significands out and expects their product back
    // FIVE cycles later, which is precisely the depth the internal
    // multiplier had (S2 partial products, then four tree levels). That
    // equality is why sharing the multiplier moves no other stage: the
    // alignment, normalisation and rounding downstream are untouched
    // and still see their operand arrive at exactly stage 6.
    //
    // cft_mulfrac is the intended supplier - one array serving a whole
    // bank of lanes - but nothing here depends on that. Anything that
    // returns a*b with five cycles of latency will do.
    output logic [MAN_W:0]       mul_a,
    output logic [MAN_W:0]       mul_b,
    input  logic [2*MAN_W+1:0]   mul_p,

    // ---- shared-normaliser port (EXT_NORM) --------------------------
    //
    // With EXT_NORM = 0 (the default) the lane builds both normalise
    // shifters and these are inert, exactly as for EXT_MUL.
    //
    // With EXT_NORM = 1 the lane hands out the value to normalise and
    // the two halves of its shift distance, and expects the normalised
    // value back TWO cycles later - precisely the depth the internal
    // shifters had (S11 coarse, S12 fine). That equality is what makes
    // sharing move no other stage: the leading-zero count, the exponent
    // and the zero/sticky rails all stay here and are unaffected.
    //
    // The distance is split the way the pipe already splits it: nrm_csh
    // counts whole 64-bit granules and nrm_fsh is the 0..63 remainder,
    // so the total is nrm_csh*64 + nrm_fsh and a supplier can simply
    // concatenate them.
    //
    // cft_normseg is the intended supplier - one segmented ladder
    // serving every bank - but nothing here depends on that. Anything
    // that returns the value left-shifted by the given distance, two
    // cycles later, will do.
    output logic [NRM_W-1:0]     nrm_v,
    output logic [3:0]           nrm_csh,
    output logic [5:0]           nrm_fsh,
    input  logic [NRM_W-1:0]     nrm_d,

    // ---- shared-aligner port (EXT_ALIGN) ----------------------------
    //
    // With EXT_ALIGN = 0 (the default) the lane builds both alignment
    // shifters and these are inert, exactly as for EXT_MUL/EXT_NORM.
    //
    // With EXT_ALIGN = 1 the lane hands out the small operand BEFORE
    // any shifting, the two halves of the distance, and the direction,
    // and expects the shifted value back TWO cycles later - the depth
    // the internal shifters had (S7 coarse, S8 fine). Unlike the
    // normalise port this one is bidirectional: alignment shifts left
    // when the addend anchors and right when the product does.
    //
    // What deliberately does NOT travel: the sticky. The marker is a
    // function of the pre-shift value and the total distance - the two
    // incremental lost-bit masks are equivalent to one mask on the
    // original operand - so it is computed in the lane and delayed two
    // cycles beside the shift. A supplier moves values only. The far
    // case is also the lane's: the value handed out is gated to zero,
    // and zero shifted is zero.
    //
    // cft_normseg with BIDIR=1 is the intended supplier; anything that
    // returns the value shifted the given way, two cycles later, will
    // do.
    output logic [ALN_W-1:0]     aln_v,
    output logic [3:0]           aln_csh,
    output logic [5:0]           aln_fsh,
    output logic                 aln_dir,   // 0 left, 1 right
    input  logic [ALN_W-1:0]     aln_d
);

  localparam int W    = 1 + EXP_W + MAN_W;
  localparam int P    = MAN_W + 1;
  localparam int BIAS = (1 << (EXP_W - 1)) - 1;
  localparam int EMIN = 1 - BIAS;
  localparam int EMAX = BIAS;
  localparam int SH   = P + 4;
  localparam int VW   = 2 * P + SH + 1;
  localparam int GW   = VW + 1;         // + appended marker LSB
  localparam int AW   = GW + 1;
  localparam int CHW  = AW / 2;
  localparam int HHW  = AW - CHW;
  localparam int NW   = GW;

  // multiplier decomposition - the geometry is rtl/cft_mulgeom.svh's,
  // included rather than restated so the pipe, cft_mulpass and the
  // array's pacing cannot disagree about a chunk count.
  `include "cft_mulgeom.svh"
  localparam int MCH  = CFT_MUL_MCH;           // chunk width, 24
  localparam int NMC  = cft_mul_chunks(P);     // chunks (fp256: 10)
  localparam int PPW  = 2 * P + 2 * MCH;       // uniform tree width
  localparam int MUL_C  = cft_mul_cols(P, MUL_PASSES);    // columns this lane builds
  localparam int MUL_NP = cft_mul_passes(P, MUL_PASSES);  // passes it takes (1 = side by side)

  localparam int FL_INVALID   = 0;
  localparam int FL_OVERFLOW  = 2;
  localparam int FL_UNDERFLOW = 3;
  localparam int FL_INEXACT   = 4;

  // Rounding attributes (IEEE 754-2019 4.3), encoded as RISC-V frm -
  // the same table as cft_golden.softfloat. Encodings 5-7 are reserved
  // and fall back to RNE here; no conforming host issues them (the
  // golden model rejects them outright).
  localparam logic [2:0] RND_RNE = 3'd0;
  localparam logic [2:0] RND_RTZ = 3'd1;
  localparam logic [2:0] RND_RDN = 3'd2;
  localparam logic [2:0] RND_RUP = 3'd3;
  localparam logic [2:0] RND_RMM = 3'd4;

  // Should the retained magnitude be incremented? Everything in this
  // datapath is sign-and-magnitude, so the directed attributes are
  // just "away from zero on one side of it".
  function automatic logic round_up(input logic [2:0] mode, input logic sgn,
                                    input logic g, input logic s,
                                    input logic lsb);
    case (mode)
      RND_RTZ: round_up = 1'b0;
      RND_RDN: round_up =  sgn && (g || s);
      RND_RUP: round_up = !sgn && (g || s);
      RND_RMM: round_up = g;
      default: round_up = g && (s || lsb);   // RNE, and reserved
    endcase
  endfunction

  // 754 7.4: which overflows deliver an infinity, and which deliver
  // the largest finite magnitude instead.
  function automatic logic overflow_to_inf(input logic [2:0] mode,
                                           input logic sgn);
    case (mode)
      RND_RTZ: overflow_to_inf = 1'b0;
      RND_RDN: overflow_to_inf =  sgn;
      RND_RUP: overflow_to_inf = !sgn;
      default: overflow_to_inf = 1'b1;       // RNE, RMM, and reserved
    endcase
  endfunction

  localparam int DEPTH = 16;

  // Elaboration-time guards. These have to be in generate scope, not in
  // an `initial` block: synthesis ignores `initial` entirely, so a
  // simulation-only check is no guard at all for the thing it is
  // guarding against. Both matter -
  //   LATENCY is structural. It does not shorten or lengthen anything;
  //   the engines size their result-capture delay lines from the same
  //   parameter, so an override would desynchronise the capture window
  //   from the real depth and silently latch every beat at the wrong
  //   cycle, with no error anywhere.
  //   NMC is the multiplier's chunk count. The partial-product array
  //   and its reduction tree are fixed at 16 entries, so a mantissa
  //   wide enough to need a 17th chunk would silently drop the top of
  //   the product. MAN_W <= 383 is the real ceiling.
  // Measured tool behaviour, which is why both forms are here: Yosys
  // and Vivado honour the generate-scope $error and ignore `initial`;
  // Icarus is the reverse. Neither form alone refuses a bad build
  // everywhere we build. (Yosys prints the message without expanding
  // format arguments, so these strings carry no %0d - the numbers are
  // in the simulation message below.)
  generate
    if (LATENCY != DEPTH) begin : g_bad_latency
      $error("cft_fpfma_pipe: LATENCY must equal the structural depth (16)");
    end
    if (NMC > 16) begin : g_too_many_chunks
      $error("cft_fpfma_pipe: MAN_W too wide - the multiplier tree holds 16 chunks (max MAN_W 383)");
    end
    if (NRM_W != NW) begin : g_bad_nrm_w
      $error("cft_fpfma_pipe: NRM_W must equal NW - do not override it");
    end
    if (ALN_W != GW - 1) begin : g_bad_aln_w
      $error("cft_fpfma_pipe: ALN_W must equal GW-1 - do not override it");
    end
    // The pacer and the pipe derive the pass count from the same
    // include; if they still disagree, something overrode a parameter
    // it should not have, and a lane held for the wrong number of
    // cycles returns a partial product with clean flags.
    if (MUL_PERIOD != 0 && MUL_PERIOD != MUL_NP) begin : g_bad_mul_period
      $error("cft_fpfma_pipe: MUL_PERIOD disagrees with the pass count derived from MUL_PASSES");
    end
    // A shared array (EXT_MUL) is single-pass by construction; the two
    // ways of not building a private multiplier do not compose.
    if (EXT_MUL && MUL_NP > 1) begin : g_ext_and_multi
      $error("cft_fpfma_pipe: EXT_MUL and a multi-pass MUL_PASSES cannot both be set");
    end
  endgenerate

  initial begin
    if (LATENCY != DEPTH) begin
      $display("FATAL: cft_fpfma_pipe LATENCY (%0d) != structural depth (%0d)",
               LATENCY, DEPTH);
      $fatal(1);
    end
    if (NMC > 16) begin
      $display("FATAL: cft_fpfma_pipe MAN_W (%0d) needs %0d multiplier chunks; the tree holds 16",
               MAN_W, NMC);
      $fatal(1);
    end
    // NRM_W exists only because the nrm_* ports are declared before NW
    // can be. If the two ever disagree the shared normaliser silently
    // truncates a significand window, which is a wrong answer with
    // clean flags - the worst failure this design has.
    if (NRM_W != NW) begin
      $display("FATAL: cft_fpfma_pipe NRM_W (%0d) != NW (%0d)", NRM_W, NW);
      $fatal(1);
    end
    if (ALN_W != GW - 1) begin
      $display("FATAL: cft_fpfma_pipe ALN_W (%0d) != GW-1 (%0d)", ALN_W, GW - 1);
      $fatal(1);
    end
    if (MUL_PERIOD != 0 && MUL_PERIOD != MUL_NP) begin
      $display("FATAL: cft_fpfma_pipe MUL_PERIOD (%0d) != derived pass count (%0d) at P=%0d, MUL_PASSES=%0d",
               MUL_PERIOD, MUL_NP, P, MUL_PASSES);
      $fatal(1);
    end
    if (EXT_MUL && MUL_NP > 1) begin
      $display("FATAL: cft_fpfma_pipe EXT_MUL=1 with MUL_PASSES=%0d (%0d passes)", MUL_PASSES, MUL_NP);
      $fatal(1);
    end
  end

  // The valid line advances on `en` like every other stage, and
  // out_valid is high for exactly the last cycle of the interval in
  // which d holds a result - one pulse per operation, whatever the
  // period. With en tied high that is the shipping contract verbatim.
  logic [DEPTH-1:0] v;
  always_ff @(posedge clk) begin
    if (!rst_n)  v <= '0;
    else if (en) v <= {v[DEPTH-2:0], in_valid};
  end
  assign out_valid = v[DEPTH-1] && en;

  // ------------------------------------------------------------------
  // S0: input registers
  // ------------------------------------------------------------------
  logic [W-1:0] s0_a, s0_b, s0_c;
  logic         s0_byp;
  logic [W-1:0] s0_byp_d;
  logic [4:0]   s0_byp_f;
  always_ff @(posedge clk) begin
    if (en) begin
      s0_a <= a; s0_b <= b; s0_c <= c;
      s0_byp <= byp; s0_byp_d <= byp_d; s0_byp_f <= byp_f;
    end
  end

  // The rounding attribute travels with its operation rather than
  // being sampled once per run, so back-to-back operations may use
  // different attributes - which is what an interval-arithmetic
  // consumer wants (a lower and an upper bound from one stream). Only
  // stages 1, 13 and 14 consult it, so a delay line is cheaper and far
  // less error-prone than threading a field through every stage.
  // The invariant is by pipeline level, not by register name:
  // rd_dly[k] holds the attribute of whatever operation currently sits
  // at level k, because both advance on the same edge.
  //
  // In THIS arrangement the register names happen to agree - rd_dly[12]
  // is read beside s12_*, and DEPTH-3 is 12. Do not rely on that. It
  // holds only because no stage before the round stage is split, and it
  // stopped holding once one was: while S11 was briefly two stages,
  // s12_* sat at level 13 and took rd_dly[13], and every tap written
  // as a literal would have handed each operation its neighbour's
  // rounding attribute. So the taps stay written relative to DEPTH -
  // the round stage is always second-to-last (DEPTH-3), pack always
  // last (DEPTH-2) - and they survive the next split without being
  // touched. The shuffled unit bench catches this class of error, but
  // only because it was made aperiodic for exactly this reason.
  //
  // The line stops at DEPTH-2 because that is the last level any
  // consumer reads; a further entry would be a register nothing uses.
  logic [2:0] rd_dly [0:DEPTH-2];
  always_ff @(posedge clk) begin
    if (en) begin
      rd_dly[0] <= rnd;
      for (int i = 1; i <= DEPTH-2; i = i + 1) rd_dly[i] <= rd_dly[i-1];
    end
  end

  // ------------------------------------------------------------------
  // S1: unpack, classify, specials sideband
  // ------------------------------------------------------------------
  logic         s1_sp, s1_sc;
  logic [P-1:0] s1_ma, s1_mb, s1_mc;
  int           s1_ep, s1_ec;
  logic         s1_special;
  logic [W-1:0] s1_spec_d;
  logic [4:0]   s1_spec_fl;
  logic         s1_c_zero;

  logic [W-1:0] qnan;
  assign qnan = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};

  always_ff @(posedge clk) begin : stage1
    logic sa, sb, sc;
    logic [EXP_W-1:0] efa, efb, efc;
    logic [MAN_W-1:0] fra, frb, frc;
    logic a_nan, b_nan, c_nan, a_snan, b_snan, c_snan;
    logic a_inf, b_inf, c_inf, a_zero, b_zero, c_zero;
    int   efa_i, efb_i, efc_i;
    logic spx;

    if (en) begin
      sa = s0_a[W-1]; sb = s0_b[W-1]; sc = s0_c[W-1];
      efa = s0_a[W-2 -: EXP_W]; efb = s0_b[W-2 -: EXP_W]; efc = s0_c[W-2 -: EXP_W];
      fra = s0_a[MAN_W-1:0];    frb = s0_b[MAN_W-1:0];    frc = s0_c[MAN_W-1:0];
      a_nan  = (&efa) && (fra != 0);  b_nan  = (&efb) && (frb != 0);
      c_nan  = (&efc) && (frc != 0);
      a_snan = a_nan && !fra[MAN_W-1]; b_snan = b_nan && !frb[MAN_W-1];
      c_snan = c_nan && !frc[MAN_W-1];
      a_inf  = (&efa) && (fra == 0);  b_inf  = (&efb) && (frb == 0);
      c_inf  = (&efc) && (frc == 0);
      a_zero = (efa == 0) && (fra == 0); b_zero = (efb == 0) && (frb == 0);
      c_zero = (efc == 0) && (frc == 0);
      // The biased fields into int, explicitly: the sideband exponent
      // algebra runs signed at 32 bits, with EXP_W <= 19 there is no
      // value a field can hold that the cast moves.
      efa_i = 32'(efa); efb_i = 32'(efb); efc_i = 32'(efc);
      spx = sa ^ sb;

      s1_sp <= spx;
      s1_sc <= sc;
      s1_ma <= (efa == 0) ? {1'b0, fra} : {1'b1, fra};
      s1_mb <= (efb == 0) ? {1'b0, frb} : {1'b1, frb};
      s1_mc <= c_zero ? '0 : ((efc == 0) ? {1'b0, frc} : {1'b1, frc});
      s1_ep <= (((efa == 0) ? 1 : efa_i) - BIAS - MAN_W)
             + (((efb == 0) ? 1 : efb_i) - BIAS - MAN_W);
      s1_ec <= ((efc == 0) ? 1 : efc_i) - BIAS - MAN_W;
      s1_c_zero <= c_zero;

      s1_special <= 1'b0;
      s1_spec_d  <= '0;
      s1_spec_fl <= '0;
      // A precomputed result wins over every classification below: the
      // operation was not arithmetic, so nothing the operands look like
      // can change its answer or raise a flag it did not raise.
      if (s0_byp) begin
        s1_special <= 1'b1;
        s1_spec_d  <= s0_byp_d;
        s1_spec_fl <= s0_byp_f;
      end else if (a_nan || b_nan || c_nan) begin
        s1_special <= 1'b1;
        s1_spec_d  <= qnan;
        s1_spec_fl <= (a_snan || b_snan || c_snan) ? (5'b1 << FL_INVALID) : 5'b0;
      end else if ((a_inf && b_zero) || (b_inf && a_zero)) begin
        s1_special <= 1'b1;
        s1_spec_d  <= qnan;
        s1_spec_fl <= 5'b1 << FL_INVALID;
      end else if (a_inf || b_inf) begin
        s1_special <= 1'b1;
        if (c_inf && (sc != spx)) begin
          s1_spec_d  <= qnan;
          s1_spec_fl <= 5'b1 << FL_INVALID;
        end else begin
          s1_spec_d <= {spx, {EXP_W{1'b1}}, {MAN_W{1'b0}}};
        end
      end else if (c_inf) begin
        s1_special <= 1'b1;
        s1_spec_d  <= {sc, {EXP_W{1'b1}}, {MAN_W{1'b0}}};
      end else if (a_zero || b_zero) begin
        s1_special <= 1'b1;
        // 754 6.3: a zero product plus a zero addend keeps a shared
        // sign; when they disagree the sum is an exact zero, which is
        // +0 in every attribute except roundTowardNegative.
        if (c_zero) s1_spec_d <= {(sc == spx) ? sc : (rd_dly[0] == RND_RDN),
                                  {(W-1){1'b0}}};
        else        s1_spec_d <= s0_c;
      end
    end
  end

  // ------------------------------------------------------------------
  // Sideband pipe for everything the multiplier stages don't touch:
  // stages 2..6 carry {sp, sc, mc, ep, ec, c_zero, special bundle}.
  // ------------------------------------------------------------------
  typedef int unsigned uint_t;  // (unused; keeps some linters quiet)

  logic         pb_sp   [2:6];
  logic         pb_sc   [2:6];
  logic [P-1:0] pb_mc   [2:6];
  int           pb_ep   [2:6];
  int           pb_ec   [2:6];
  logic         pb_cz   [2:6];
  logic         pb_spc  [2:6];
  logic [W-1:0] pb_spd  [2:6];
  logic [4:0]   pb_spf  [2:6];

  always_ff @(posedge clk) begin : sideband
    if (en) begin
      pb_sp[2] <= s1_sp;  pb_sc[2] <= s1_sc;  pb_mc[2] <= s1_mc;
      pb_ep[2] <= s1_ep;  pb_ec[2] <= s1_ec;  pb_cz[2] <= s1_c_zero;
      pb_spc[2] <= s1_special; pb_spd[2] <= s1_spec_d; pb_spf[2] <= s1_spec_fl;
      for (int k = 3; k <= 6; k = k + 1) begin
        pb_sp[k] <= pb_sp[k-1];   pb_sc[k] <= pb_sc[k-1];
        pb_mc[k] <= pb_mc[k-1];   pb_ep[k] <= pb_ep[k-1];
        pb_ec[k] <= pb_ec[k-1];   pb_cz[k] <= pb_cz[k-1];
        pb_spc[k] <= pb_spc[k-1]; pb_spd[k] <= pb_spd[k-1];
        pb_spf[k] <= pb_spf[k-1];
      end
    end
  end

  // ------------------------------------------------------------------
  // S2..S6: staged significand multiplier
  // ------------------------------------------------------------------
  localparam int NPP = (NMC < 1) ? 1 : NMC;
  logic [2*P-1:0] s6_mp;

  // The lane's significands, out to whoever is multiplying them. Driven
  // in both modes so a shared array and an internal one see the same
  // operands - which is what makes the two configurations comparable.
  assign mul_a = s1_ma;
  assign mul_b = s1_mb;

  generate
    if (EXT_MUL) begin : g_mul_shared
      // Someone else owns the array. The contract is five cycles, the
      // same depth this used to build, so s6_mp lands where it always
      // did and nothing downstream moves.
      assign s6_mp = mul_p;
    end else if (MUL_NP > 1) begin : g_mul_multi
      // The multi-cycle multiplier: MUL_C columns iterated over MUL_NP
      // passes on the wall clock, its product handed back at level 5
      // in ENABLED cycles - the same level the tree below delivers it,
      // so alignment onward sees s6_mp arrive exactly when it always
      // has. The pipe around it is being held on `en` for MUL_NP - 1
      // of every MUL_NP cycles; that is the whole cost of the trade,
      // and it is paid in throughput, never in bits (cft_mulpass'
      // header carries the argument and the timeline).
      cft_mulpass #(.P(P), .COLS(MUL_C), .LEVEL(5)) u_mulpass (
          .clk(clk), .en(en), .a(s1_ma), .b(s1_mb), .p(s6_mp));
    end else begin : g_mul_local
      logic [PPW-1:0] s2_pp [0:15];
      logic [PPW-1:0] s3_q  [0:7];
      logic [PPW-1:0] s4_t  [0:3];
      logic [PPW-1:0] s5_u  [0:1];
      logic [2*P-1:0] s6_mp_r;

      logic [NMC*MCH-1:0] mb_pad;
      assign mb_pad = {{(NMC*MCH-P){1'b0}}, s1_mb};

      always_ff @(posedge clk) begin : mult_stages
        if (en) begin
          // S2: partial products (each a short DSP column)
          for (int k = 0; k < 16; k = k + 1) begin
            if (k < NMC) s2_pp[k] <= s1_ma * mb_pad[k*MCH +: MCH];
            else         s2_pp[k] <= '0;
          end
          // S3: L1 pairs, shift 24
          for (int j = 0; j < 8; j = j + 1)
            s3_q[j] <= s2_pp[2*j] + (s2_pp[2*j+1] << MCH);
          // S4: L2 pairs, shift 48
          for (int i = 0; i < 4; i = i + 1)
            s4_t[i] <= s3_q[2*i] + (s3_q[2*i+1] << (2*MCH));
          // S5: L3 pairs, shift 96
          for (int i = 0; i < 2; i = i + 1)
            s5_u[i] <= s4_t[2*i] + (s4_t[2*i+1] << (4*MCH));
          // S6: L4 final, shift 192. The add runs at the tree's uniform
          // PPW = 2P+48 bits and lands in 2P: the sum IS the exact
          // product ma*mb < 2^2P, so the 48 bits dropped are zero by
          // arithmetic, not by luck. Left as written - restaging the
          // final add to please a width lint is exactly the edit this
          // file's history warns against.
          /* verilator lint_off WIDTHTRUNC */
          s6_mp_r <= s5_u[0] + (s5_u[1] << (8*MCH));
          /* verilator lint_on WIDTHTRUNC */
        end
      end

      assign s6_mp = s6_mp_r;
    end
  endgenerate

  // ------------------------------------------------------------------
  // S6 (parallel): alignment prep from the sideband exponents
  // ------------------------------------------------------------------
  logic       s6_sbig, s6_ssml, s6_big_is_p, s6_right, s6_far, s6_mkpre;
  int         s6_g, s6_csh, s6_fsh;
  logic       s6_sp, s6_cz;
  logic [P-1:0] s6_mc;
  logic       s6_spc;
  logic [W-1:0] s6_spd;
  logic [4:0] s6_spf;

  always_ff @(posedge clk) begin : stage6_prep
    int dd, lshift;
    logic bp;
    if (en) begin
      bp = (pb_ep[5] >= pb_ec[5]);
      s6_big_is_p <= bp;
      s6_sbig <= bp ? pb_sp[5] : pb_sc[5];
      s6_ssml <= bp ? pb_sc[5] : pb_sp[5];
      if (bp) begin dd = pb_ep[5] - pb_ec[5]; s6_g <= pb_ep[5] - SH; end
      else     begin dd = pb_ec[5] - pb_ep[5]; s6_g <= pb_ec[5] - SH; end
      lshift = SH - dd;
      if (lshift >= 0) begin
        s6_far <= 1'b0; s6_right <= 1'b0;
        s6_csh <= (lshift >> 6); s6_fsh <= (lshift & 63);
        s6_mkpre <= 1'b0;
      end else if (-lshift < 2 * P + 2) begin
        s6_far <= 1'b0; s6_right <= 1'b1;
        s6_csh <= ((-lshift) >> 6); s6_fsh <= ((-lshift) & 63);
        s6_mkpre <= 1'b0;
      end else begin
        s6_far <= 1'b1; s6_right <= 1'b0;
        s6_csh <= 0; s6_fsh <= 0;
        // sml is entirely below the grid: it is (a) the addend when the
        // product anchors, or (b) the product when the addend anchors.
        // For (b) the product is nonzero by construction here (a_zero/
        // b_zero went down the specials path), so |sml| = 1.
        s6_mkpre <= bp ? (pb_cz[5] ? 1'b0 : |pb_mc[5]) : 1'b1;
      end
      s6_sp  <= pb_sp[5];
      s6_cz  <= pb_cz[5];
      s6_mc  <= pb_mc[5];
      s6_spc <= pb_spc[5]; s6_spd <= pb_spd[5]; s6_spf <= pb_spf[5];
    end
  end

  // ------------------------------------------------------------------
  // S7: coarse align; S8: fine align + appended-marker operands
  // ------------------------------------------------------------------
  // ---- S7 combinational: operand steering, and the whole sticky -----
  //
  // Split out of the register process so a shared aligner can be handed
  // exactly what the private one consumes. Two changes of FORM and none
  // of function:
  //
  //   * the marker is computed from the PRE-shift value and the total
  //     distance, replacing the two incremental masks (coarse in S7,
  //     fine in S8). They are the same set: the coarse shift discards
  //     the low csh*64 bits of smlv and the fine shift then discards
  //     the next fsh, so together they discard the low csh*64+fsh -
  //     one mask on the original operand. At amt=0 the mask is empty,
  //     which is why the old (csh != 0)/(fsh != 0) guards have no
  //     replacement: they were already implied.
  //   * the far case gates the VALUE to zero instead of assigning zero
  //     after the shift. Zero shifted is zero, and it means the far
  //     rail does not need to exist inside a shared supplier.
  logic [GW-2:0] n7_smlv, n7_bigv;
  logic          n7_marker;

  always_comb begin
    logic [GW-2:0] smlv0, onesv;
    logic [9:0]    amt;
    logic [31:0]   cshw, fshw;
    onesv = {(GW-1){1'b1}};
    if (s6_big_is_p) begin
      n7_bigv = {{(GW-1-2*P){1'b0}}, s6_mp} << SH;
      smlv0   = {{(GW-1-P){1'b0}}, s6_mc};
    end else begin
      n7_bigv = {{(GW-1-P){1'b0}}, s6_mc} << SH;
      smlv0   = {{(GW-1-2*P){1'b0}}, s6_mp};
    end
    n7_smlv = s6_far ? '0 : smlv0;
    // s6_csh/s6_fsh are ints. The slices are safe by range - csh is at
    // most 7 (right bound 2P+1 < 512) and fsh at most 63 - and taken
    // through named intermediates so the narrowing is visible.
    cshw = s6_csh;
    fshw = s6_fsh;
    amt = {cshw[3:0], fshw[5:0]};
    if (s6_far)
      n7_marker = s6_mkpre;
    else if (s6_right)
      n7_marker = |(smlv0 & ~(onesv << amt));
    else
      n7_marker = 1'b0;
  end

  logic [31:0] aln_cshw, aln_fshw;
  always_comb begin
    aln_cshw = s6_csh;
    aln_fshw = s6_fsh;
  end
  assign aln_v   = n7_smlv;
  assign aln_csh = aln_cshw[3:0];
  assign aln_fsh = aln_fshw[5:0];
  assign aln_dir = s6_right;

  logic [GW-2:0] s7_big;
  logic          s7_sbig, s7_ssml, s7_marker, s7_spc;
  logic [W-1:0]  s7_spd;
  logic [4:0]    s7_spf;
  int            s7_g;

  always_ff @(posedge clk) begin : stage7
    if (en) begin
      s7_big    <= n7_bigv;
      s7_marker <= n7_marker;
      s7_sbig <= s6_sbig; s7_ssml <= s6_ssml;
      s7_g <= s6_g;
      s7_spc <= s6_spc; s7_spd <= s6_spd; s7_spf <= s6_spf;
    end
  end

  logic [GW-1:0] s8_bigf, s8_smlf;
  logic          s8_sbig, s8_ssml, s8_spc;
  logic [W-1:0]  s8_spd;
  logic [4:0]    s8_spf;
  int            s8_g;

  always_ff @(posedge clk) begin : stage8
    if (en) begin
      s8_bigf <= {s7_big, 1'b0};
      s8_sbig <= s7_sbig; s8_ssml <= s7_ssml;
      s8_g <= s7_g;
      s8_spc <= s7_spc; s8_spd <= s7_spd; s8_spf <= s7_spf;
    end
  end

  // ---- the two alignment shifters, here or elsewhere ----------------
  //
  // Private: the same data movement the merged stages performed -
  // coarse by whole granules into s7_sml, then the remainder - with the
  // amounts and direction registered beside the value so each stage
  // uses ITS operand's amount. Shared: the value comes back from the
  // supplier as the supplier's own register, so S9 sees the same
  // timing either way; the marker was computed in-lane at S7 and rides
  // the s7/s8 registers to be appended below the value.
  generate
    if (EXT_ALIGN) begin : g_align_shared
      // The marker needs its own second register: aln_d is two
      // registers deep (the supplier's stages) while s7_marker is one,
      // and s8_smlf is a wire here rather than the register it is in
      // the private arm. Without this the marker rides one cycle ahead
      // of its operand - correct on isolated operations, wrong on the
      // streams the engine actually issues.
      logic s8_marker;
      always_ff @(posedge clk) if (en) s8_marker <= s7_marker;
      assign s8_smlf = {aln_d[GW-2:0], s8_marker};
    end else begin : g_align_priv
      logic [GW-2:0] s7_sml;
      logic [5:0]    s7_fsh;
      logic          s7_right;
      always_ff @(posedge clk) begin
        if (en) begin
          s7_sml   <= s6_right ? (n7_smlv >> (s6_csh * 64))
                               : (n7_smlv << (s6_csh * 64));
          s7_fsh   <= aln_fshw[5:0];
          s7_right <= s6_right;
        end
      end
      always_ff @(posedge clk) begin
        if (en) begin
          s8_smlf <= {s7_right ? (s7_sml >> s7_fsh) : (s7_sml << s7_fsh),
                      s7_marker};
        end
      end
    end
  endgenerate

  // ------------------------------------------------------------------
  // S9, S10: split-carry arithmetic; sum and both differences race
  // ------------------------------------------------------------------
  logic [CHW-1:0] s9_sumL, s9_dAL, s9_dBL;
  logic           s9_sumC, s9_dAB, s9_dBB;
  logic [HHW-1:0] s9_bigH, s9_smlH;
  logic           s9_same, s9_sbig, s9_ssml, s9_spc;
  logic [W-1:0]   s9_spd;
  logic [4:0]     s9_spf;
  int             s9_g;

  always_ff @(posedge clk) begin : stage9
    logic [CHW:0] sl, al, bl;
    logic [CHW-1:0] bigL, smlL;
    if (en) begin
      bigL = s8_bigf[CHW-1:0];
      smlL = s8_smlf[CHW-1:0];
      sl = {1'b0, bigL} + {1'b0, smlL};
      al = {1'b0, bigL} - {1'b0, smlL};
      bl = {1'b0, smlL} - {1'b0, bigL};
      s9_sumL <= sl[CHW-1:0];  s9_sumC <= sl[CHW];
      s9_dAL  <= al[CHW-1:0];  s9_dAB  <= al[CHW];
      s9_dBL  <= bl[CHW-1:0];  s9_dBB  <= bl[CHW];
      s9_bigH <= {1'b0, s8_bigf[GW-1:CHW]};
      s9_smlH <= {1'b0, s8_smlf[GW-1:CHW]};
      s9_same <= (s8_sbig == s8_ssml);
      s9_sbig <= s8_sbig; s9_ssml <= s8_ssml;
      s9_g <= s8_g;
      s9_spc <= s8_spc; s9_spd <= s8_spd; s9_spf <= s8_spf;
    end
  end

  logic [GW:0]  s10_mag;
  logic         s10_rsign, s10_spc;
  logic [W-1:0] s10_spd;
  logic [4:0]   s10_spf;
  int           s10_g;

  always_ff @(posedge clk) begin : stage10
    logic [HHW-1:0] sumH, dAH, dBH;
    logic negA;
    if (en) begin
      sumH = s9_bigH + s9_smlH + {{(HHW-1){1'b0}}, s9_sumC};
      dAH  = s9_bigH - s9_smlH - {{(HHW-1){1'b0}}, s9_dAB};
      dBH  = s9_smlH - s9_bigH - {{(HHW-1){1'b0}}, s9_dBB};
      if (s9_same) begin
        s10_mag   <= {sumH, s9_sumL};
        s10_rsign <= s9_sbig;
      end else begin
        negA = dAH[HHW-1];
        if (!negA) begin
          s10_mag   <= {dAH, s9_dAL};
          s10_rsign <= s9_sbig;
        end else begin
          s10_mag   <= {dBH, s9_dBL};
          s10_rsign <= s9_ssml;
        end
      end
      s10_g <= s9_g;
      s10_spc <= s9_spc; s10_spd <= s9_spd; s10_spf <= s9_spf;
    end
  end

  // ------------------------------------------------------------------
  // S11: leading-zero count (registered); S12: coarse normalize shift
  // and the rails; S13: fine normalize shift
  // ------------------------------------------------------------------
  //
  // The scan, the priority encode, the chunk mux, lzc64 and the
  // NW-1-msb subtract were inline here until 2026-09-07. They are
  // cft_lzcone, at the bottom of this file, for two reasons: the
  // register below has to sit between the cone and its consumers, which
  // is the whole point of the change, and a module is the thing a
  // combinational equivalence miter can hold - formal/lzcone.sby proves
  // the shipping cone equal over the whole NW-bit input space to the
  // priority-loop form that was here.
  //
  // n11_valw is what gets normalised: the magnitude window less its
  // appended marker LSB, which becomes the explicit sticky rail below.
  logic [NW-1:0] n11_valw;
  logic          n11_empty;
  logic [9:0]    n11_lsh;
  logic [9:0]    n11_msb;

  assign n11_valw = s10_mag[GW:1];

  cft_lzcone #(.NW(NW)) u_lzcone (
      .v     (n11_valw),
      .empty (n11_empty),
      .msb   (n11_msb),
      .lsh   (n11_lsh)
  );

  // ---- S11 registers: the distance, the window, and everything
  // ---- travelling beside them ---------------------------------------
  //
  // The parallel paths are the point. This is a SYNCHRONISED multi-path
  // pipeline, not a linear one, so the sign, the exponent anchor, the
  // residue rail and the whole specials sideband cross the new boundary
  // on the same edge the distance does. Delay one and not the others and
  // every FMA pairs a shift amount with another operation's control
  // word - docs/ROADMAP.md records what that looked like the last time
  // a stage was added here: garbage, not drift.
  //
  // n11_lsh is the total left shift, NW-1-msb; the pipe's split of it
  // into whole 64-bit granules plus a 0..63 remainder is what the
  // nrm_csh/nrm_fsh ports carry. The halves are bit-selects of the
  // REGISTERED total rather than arithmetic on it, so csh*64 + fsh ==
  // lsh stays true by construction, exactly as when the split was
  // combinational, and the two ports leave from flip-flops.
  logic [NW-1:0] r11_valw;
  logic          r11_empty;
  logic [9:0]    r11_lsh;
  int            r11_msb;
  logic          r11_stk;      // the appended marker, s10_mag[0]
  logic          r11_rsign, r11_spc;
  logic [W-1:0]  r11_spd;
  logic [4:0]    r11_spf;
  int            r11_g;
  logic [3:0]    r11_csh;
  logic [5:0]    r11_fsh;

  always_ff @(posedge clk) begin : reg11
    if (en) begin
      r11_valw  <= n11_valw;
      r11_empty <= n11_empty;
      r11_lsh   <= n11_lsh;
      // 0 <= msb <= NW-1 <= 716, so this is a value-preserving widening
      // of an unsigned count into the signed int the exponent add below
      // wants - and it keeps that add signed, which it must be: g is
      // negative for a subnormal anchor.
      r11_msb   <= {22'b0, n11_msb};
      r11_stk   <= s10_mag[0];
      r11_rsign <= s10_rsign;
      r11_g     <= s10_g;
      r11_spc <= s10_spc; r11_spd <= s10_spd; r11_spf <= s10_spf;
    end
  end

  assign r11_csh = r11_lsh[9:6];
  assign r11_fsh = r11_lsh[5:0];

  assign nrm_v   = r11_valw;
  assign nrm_csh = r11_csh;
  assign nrm_fsh = r11_fsh;

  // s11_valw and s11_fine are the private shifter's own intermediate
  // and live inside the generate below, so a shared lane does not carry
  // an undriven register it never reads.
  logic          s11_stk, s11_zero, s11_rsign, s11_spc;
  logic [W-1:0]  s11_spd;
  logic [4:0]    s11_spf;
  int            s11_enorm;

  // S12's rails - the exponent, the zero and sticky flags, the
  // sideband. They keep their s11_* names from when this process and
  // the leading-zero count were one stage. The empty-window case:
  //
  // Exact zero only without sticky residue; else a bare epsilon,
  // and s10_g already places it below the subnormal grid so the
  // round stage disposes of it per the attribute, carrying the true
  // sign.
  //
  // Why that holds - it is NOT because the anchor is zero (a
  // nonzero subnormal addend reaches here too: fp32
  // a=0x1ef3ab49 b=0x1ef536f9 c=0x80074b3a cancels to an empty
  // window with the marker set). It is because an empty window
  // with a surviving residue requires the anchor's significand
  // below 2^(P-4), which forces it subnormal or zero - and any
  // subnormal pins its exponent at EMIN-MAN_W, so g = EMIN-MAN_W-SH
  // and the round stage's K is negative. Change SH or the
  // far-alignment threshold and this is the argument to re-derive.
  always_ff @(posedge clk) begin : stage11
    if (en) begin
      s11_zero  <= r11_empty && !r11_stk;
      s11_enorm <= r11_empty ? r11_g : (r11_g + r11_msb);
      s11_stk   <= r11_stk;
      s11_rsign <= r11_rsign;
      s11_spc <= r11_spc; s11_spd <= r11_spd; s11_spf <= r11_spf;
    end
  end

  logic [NW-1:0] s12_norm;
  logic          s12_stk, s12_zero, s12_rsign, s12_spc;
  logic [W-1:0]  s12_spd;
  logic [4:0]    s12_spf;
  int            s12_enorm;
  // S13's exponent arithmetic, done here. K (how many significand bits
  // the format keeps at this exponent), the round window's shift, q,
  // and the two tininess compares are all functions of s11_enorm
  // alone, and S13 was deriving them from s12_enorm - the same value
  // one register later - at the head of the design's measured critical
  // path: four CARRY8 and two LUTs of subtraction before a shift amount
  // that fans out to 625 loads (routed quad @135, 2026-09-02, -0.133 ns
  // on s12_enorm_reg[0] -> s13_kept_r_reg). Computed here they arrive
  // as registers, the fanout leaves from flip-flops the placer can
  // replicate, and the value of every one of them is unchanged.
  int            s12_k;        // = K as S13 computed it
  int            s12_delta;    // = P - K, the round window's own shift (K > 0)
  int            s12_q;        // = s13_q as S13 computed it
  logic          s12_tiny0;    // s11_enorm     < EMIN
  logic          s12_tiny1;    // s11_enorm + 1 < EMIN
  logic [P+1:0]  s12_ymask;    // the delta low bits of the window: sticky's share

  always_ff @(posedge clk) begin : stage12
    int k12, d12;
    logic [P+1:0] ones_y;
    if (en) begin
      ones_y = {(P+2){1'b1}};
      k12 = (s11_enorm >= EMIN) ? P : (P - (EMIN - s11_enorm));
      d12 = P - k12;
      s12_stk   <= s11_stk;
      s12_zero  <= s11_zero;
      s12_enorm <= s11_enorm;
      s12_rsign <= s11_rsign;
      s12_spc <= s11_spc; s12_spd <= s11_spd; s12_spf <= s11_spf;
      s12_k     <= k12;
      s12_delta <= d12;
      s12_q     <= ((s11_enorm >= EMIN) ? s11_enorm : EMIN) - (P - 1);
      s12_tiny0 <= (s11_enorm < EMIN);
      s12_tiny1 <= ((s11_enorm + 1) < EMIN);
      // Only meaningful for K in 1..P (delta in 0..P-1); the K <= 0 branch
      // never reads it, and a delta past the window just masks everything.
      s12_ymask <= ~(ones_y << ((d12 < 0) ? 0 : ((d12 > P + 1) ? (P + 1) : d12)));
    end
  end

  // ---- the two normalise shifters, here or elsewhere ----------------
  //
  // Private: the same two shifts as ever, one level later - coarse by
  // whole granules into s11_valw, then the remainder into s12_norm.
  // The empty-window case needs no special handling because r11_valw IS
  // zero then and r11_csh/r11_fsh are zero with it, so `r11_valw << 0`
  // reproduces the old `s11_valw <= '0` exactly.
  //
  // Shared: s12_norm is a wire from the supplier, which must return the
  // value two cycles later. It still arrives as a register - the
  // supplier's - so S13 sees the same timing either way.
  generate
    if (EXT_NORM) begin : g_norm_shared
      assign s12_norm = nrm_d;
    end else begin : g_norm_priv
      logic [NW-1:0] s11_valw;
      logic [5:0]    s11_fine;
      always_ff @(posedge clk) begin
        if (en) begin
          s11_valw <= r11_valw << (r11_csh * 64);
          s11_fine <= r11_fsh;
        end
      end
      always_ff @(posedge clk) begin
        if (en) begin
          s12_norm <= s11_valw << s11_fine;
        end
      end
    end
  endgenerate

  // ------------------------------------------------------------------
  // S13: rounding (clamped and as-if-unbounded windows)
  // ------------------------------------------------------------------
  logic [P:0]   s13_kept_r;
  logic         s13_inexact, s13_tiny, s13_zero, s13_rsign, s13_spc;
  logic [W-1:0] s13_spd;
  logic [4:0]   s13_spf;
  int           s13_q;

  always_ff @(posedge clk) begin : stage13
    int K;
    logic [P+1:0] ywin, zwin;
    logic [P:0] kept, kept_p1;
    logic guard, sticky, up;
    logic [P-1:0] kept_u;
    logic guard_u, sticky_u, up_u, carry_u;

    if (en) begin
      K = s12_k;
      s13_q     <= s12_q;
      s13_zero  <= s12_zero;
      s13_rsign <= s12_rsign;
      s13_spc <= s12_spc; s13_spd <= s12_spd; s13_spf <= s12_spf;

      if (s12_zero) begin
        s13_kept_r <= '0; s13_inexact <= 1'b0; s13_tiny <= 1'b0;
      end else begin
        kept_u   = s12_norm[NW-1 -: P];
        guard_u  = s12_norm[NW-1-P];
        sticky_u = (|s12_norm[NW-2-P:0]) | s12_stk;
        up_u     = round_up(rd_dly[DEPTH-3], s12_rsign, guard_u, sticky_u,
                            kept_u[0]);
        carry_u  = (&kept_u) && up_u;
        s13_tiny <= carry_u ? s12_tiny1 : s12_tiny0;

        if (K <= 0) begin
          // Entirely below the subnormal grid. K == 0 puts the value's
          // MSB in the guard position; K < 0 puts everything into the
          // sticky. Either way the result is inexact, and only the
          // attribute decides whether it becomes zero or one ulp.
          guard  = (K == 0);
          sticky = (K == 0) ? ((|s12_norm[NW-2:0]) | s12_stk) : 1'b1;
          kept   = '0;
        end else begin
          // The clamped window, extracted from the P+1 bits that can
          // reach it rather than by shifting all NW. With sh = NW - K
          // the old form was kept = (s12_norm >> sh)[P:0] and
          // guard = s12_norm[sh-1]; the bits those can name are
          // s12_norm[NW-1 : NW-P-1] - the top P plus the guard position -
          // and a zero above them. Shifting that window right by
          // delta = P - K lands the same bits in the same places (bit i
          // of kept is s12_norm[NW-K+i] either way, zero above K), so the
          // shifter is 8 levels over P+2 bits instead of 10 over NW, and
          // its amount is a register instead of a subtraction. Sticky is
          // everything below the guard: the part that is below the
          // window at every K, plus the delta window bits the shift
          // dropped, which s12_ymask names.
          ywin   = {1'b0, s12_norm[NW-1 : NW-P-1]};
          zwin   = ywin >> s12_delta;
          kept   = zwin[P+1:1];
          guard  = zwin[0];
          sticky = (|s12_norm[NW-P-2:0]) | (|(ywin & s12_ymask)) | s12_stk;
        end
        // Round by SELECTING between kept and kept+1, not by adding up.
        //
        // These are the same value. They are not the same circuit, and
        // this stage is the measured critical path of the whole design
        // (S12 -> S13, 39 logic levels, 21 of them CARRY8, ~61% route
        // when this was written; 25 levels, 15 CARRY8 and 73% route on
        // the routed quad of 2026-09-02, before the amount moved to S12).
        //
        // `up` depends on guard, sticky and kept[0], all of which come
        // out of the variable shift above - so `kept + up` cannot begin
        // until the guard/sticky reduction and round_up have finished,
        // and a 238-bit ripple carry then sits at the END of an already
        // long path. Computing kept+1 as soon as `kept` exists runs that
        // carry in PARALLEL with the reduction that produces `up`, and
        // leaves one multiplexer where the adder used to be.
        //
        // Nothing about the arithmetic changes, which is the point: this
        // is the most safety-critical logic here, and the 441,000-case
        // suite is what has to agree afterwards.
        kept_p1 = kept + {{P{1'b0}}, 1'b1};
        up = round_up(rd_dly[DEPTH-3], s12_rsign, guard, sticky, kept[0]);
        s13_kept_r  <= up ? kept_p1 : kept;
        s13_inexact <= guard || sticky;
      end
    end
  end

  // ------------------------------------------------------------------
  // S14: pack + specials mux -> outputs
  // ------------------------------------------------------------------
  function automatic int bitlen_p1(input logic [P:0] x);
    int r;
    begin
      r = 0;
      for (int i = 0; i <= P; i = i + 1) if (x[i]) r = i + 1;
      bitlen_p1 = r;
    end
  endfunction

  always_ff @(posedge clk) begin : stage14
    logic [W-1:0] res;
    logic [4:0] fl;
    logic [P:0] kr;
    logic [EXP_W-1:0] biased_f;
    logic [31:0] e_biased;
    int bl, e_res;

    if (en) begin
      res = '0; fl = '0;
      if (s13_spc) begin
        res = s13_spd;
        fl  = s13_spf;
      end else if (s13_zero) begin
        // exact cancellation (754 6.3): +0, except toward -infinity
        res = {(rd_dly[DEPTH-2] == RND_RDN), {(W-1){1'b0}}};
      end else begin
        kr = s13_kept_r;
        fl[FL_INEXACT] = s13_inexact;
        if (kr == 0) begin
          res = {s13_rsign, {(W-1){1'b0}}};
          fl[FL_UNDERFLOW] = 1'b1;
        end else begin
          bl = bitlen_p1(kr);
          e_res = s13_q + bl - 1;
          if (e_res > EMAX) begin
            // 754 7.4: overflow is signalled in every attribute, but
            // only some of them deliver an infinity; the rest deliver
            // the largest finite magnitude.
            if (overflow_to_inf(rd_dly[DEPTH-2], s13_rsign))
              res = {s13_rsign, {EXP_W{1'b1}}, {MAN_W{1'b0}}};
            else
              res = {s13_rsign, {(EXP_W-1){1'b1}}, 1'b0, {MAN_W{1'b1}}};
            fl[FL_OVERFLOW] = 1'b1;
            fl[FL_INEXACT]  = 1'b1;
          end else begin
            if (s13_tiny && s13_inexact) fl[FL_UNDERFLOW] = 1'b1;
            if (e_res < EMIN) begin
              res = {s13_rsign, {EXP_W{1'b0}}, kr[MAN_W-1:0]};
            end else begin
              if (bl == P + 1) kr = kr >> 1;
              // In this branch EMIN <= e_res <= EMAX, so the biased sum
              // sits in [1, 2^EXP_W - 2] and the field select is exact.
              e_biased = e_res + BIAS;
              biased_f = e_biased[EXP_W-1:0];
              res = {s13_rsign, biased_f, kr[MAN_W-1:0]};
            end
          end
        end
      end
      d     <= res;
      flags <= fl;
    end
  end

endmodule

// ---------------------------------------------------------------------
// cft_lz4: leading zeros of a 4**L-bit vector, as a balanced tree.
//
// `cnt` is the number of zeros above the top set bit, and is meaningful
// only when `vld`. The merge is the textbook log-depth (valid, count)
// one, folded four wide:
//
//     valid = |{v3,v2,v1,v0}
//     count = v3 ? {2'b00, c3} : v2 ? {2'b01, c2}
//           : v1 ? {2'b10, c1} :      {2'b11, c0}
//
// with quarter 3 the most significant, so each level contributes one
// base-4 digit and the root's count is the leading-zero count itself.
//
// Written as ONE always_comb over ONE loop, and that is measured rather
// than preferred. The obvious form - a generate pyramid with a
// continuous assignment per node - needs two multiply driven nets, and
// Icarus schedules every one of those drivers as its own event: it took
// `make fp32` from 21.6 s to 528.1 s on an otherwise identical tree
// (2026-09-07). The whole cocotb matrix runs on Icarus.
//
// Two identities make the single flat loop possible. The first child of
// node n is 4n - W at EVERY level - it falls out of B[k-1] = 4*B[k] - W
// with B[k] = (W - W/4^k)/3, where level k starts - so no node needs to
// know its own level to find its children; and c < n always, so a
// node's children are resolved before it is reached. The second is that
// the digits accumulate REVERSED, rc_parent = (rc_child << 2) | q,
// which is also level-independent; one fixed permutation at the root
// puts them back in order. (Yosys refuses a procedural for-loop whose
// bound is not constant, so a level-by-level reduction in one process
// is not available. This is.)
// ---------------------------------------------------------------------
module cft_lz4 #(
    // Must be a power of four, and at least 4. Guarded below.
    parameter int W = 64
) (
    input  logic [W-1:0] x,
    output logic         vld,
    output logic [9:0]   cnt
);

  localparam int LV  = ($clog2(W) + 1) / 2;   // levels
  localparam int NU0 = W / 4;                 // leaves
  localparam int NN  = (W - 1) / 3;           // nodes; the root is the last
  localparam int CW  = 10;                    // count bits; 2*LV at most

  generate
    if (W < 4 || (1 << (2 * LV)) != W) begin : g_bad_w
      $error("cft_lz4: W must be a power of four, at least 4");
    end
  endgenerate

  initial begin
    if (W < 4 || (1 << (2 * LV)) != W) begin
      $display("FATAL: cft_lz4 W=%0d is not a power of four", W);
      $fatal(1);
    end
  end

  always_comb begin
    logic [NN-1:0]    nv;     // per-node validity
    logic [NN*CW-1:0] nc;     // per-node count, digits reversed
    logic [CW-1:0]    rc, cv;
    logic [1:0]       q;
    logic             v3, v2, v1, v0;
    int               c;

    // Yosys refuses a block-local written on only one path of an
    // always_comb, and it is right to: that is a latch.
    nv = '0; nc = '0; rc = '0; cv = '0; q = 2'd0;
    v3 = 1'b0; v2 = 1'b0; v1 = 1'b0; v0 = 1'b0; c = 0;

    for (int n = 0; n < NN; n = n + 1) begin
      if (n < NU0) begin
        v3 = x[4*n+3]; v2 = x[4*n+2]; v1 = x[4*n+1]; v0 = x[4*n+0];
        rc = '0;
      end else begin
        c  = 4*n - W;
        v3 = nv[c+3]; v2 = nv[c+2]; v1 = nv[c+1]; v0 = nv[c+0];
        rc = v3 ? nc[(c+3)*CW +: CW]
           : v2 ? nc[(c+2)*CW +: CW]
           : v1 ? nc[(c+1)*CW +: CW]
           :      nc[(c+0)*CW +: CW];
        rc = rc << 2;
      end
      q = v3 ? 2'd0 : v2 ? 2'd1 : v1 ? 2'd2 : 2'd3;
      nv[n] = v3 | v2 | v1 | v0;
      nc[n*CW +: CW] = rc | {{(CW-2){1'b0}}, q};
    end

    // Un-reverse the base-4 digits: the root's digit is the most
    // significant of the true count, and it is the one sitting lowest.
    rc = nc[(NN-1)*CW +: CW];
    for (int i = 0; i < LV; i = i + 1)
      cv[2*(LV-1-i) +: 2] = rc[2*i +: 2];

    vld = nv[NN-1];
    cnt = cv;
  end

endmodule

// ---------------------------------------------------------------------
// cft_lzcone: the leading-zero cone, for one normalise window.
//
// Given the NW-bit window `v`, report whether it is empty, the index of
// its most significant 1, and the left shift NW-1-msb that puts that 1
// at the top. On an empty window both counts are driven ZERO rather
// than left undefined: this lane's amount reaches a ladder other lanes
// are also using (rtl/cft_normseg.sv), and an X there is everyone's
// problem.
//
// This was inline in cft_fpfma_pipe's S11 until 2026-09-07, as two
// PRIORITY LOOPS: a per-64-bit chunk zero-detect, a top-down scan for
// the highest nonzero chunk, a chunk mux and a 64-way priority count.
// The 2026-09-06 routed fp256 trace put 8.77 ns of an 11.55 ns path in
// here, over about thirteen levels
// (docs/studies/OPT-C-timing.md 0.2). Two things changed. The pipe now
// registers this module's answer, which is what wanted it to be one
// nameable object; and both SCANS became balanced trees (cft_lz4).
//
// What did NOT change is the 64-bit chunk zero-detect, and that is
// deliberate. It is the one part of the old cone Vivado already mapped
// well - five CARRY4 for 0.484 ns and no routing, per the same trace -
// and it is also what keeps this module cheap to SIMULATE: a 64-bit
// reduction is one vector operation, where a tree over the same bits is
// sixteen nodes. Measured on 2026-09-07: a pure radix-4 tree over the
// whole 717-bit window is bit-identical and about four times slower
// through Icarus on tb_fpfma_fp256, which the cocotb matrix pays on
// every run. So the trees go where the PRIORITY LOOPS were - twelve
// chunk flags, and sixty-four bits of the one chunk that matters - and
// the wide cheap reduction stays.
//
// formal/lzcone.sby proves the whole module equal to the priority form
// over the whole NW-bit input space at all four rungs. That proof is
// the gate: this is a restructuring of a combinational function, so
// "the vectors agreed" is the weaker claim and was never the one to
// settle for here.
// ---------------------------------------------------------------------
module cft_lzcone #(
    // Window width; the pipe builds 78, 165, 345 and 717.
    parameter int NW = 717
) (
    input  logic [NW-1:0] v,
    output logic          empty,   // v == 0
    output logic [9:0]    msb,     // index of the top 1; 0 when empty
    output logic [9:0]    lsh      // NW-1-msb; 0 when empty
);

  localparam int NCH = (NW + 63) / 64;              // 64-bit chunks needed
  localparam int LVC = ($clog2(NCH) + 1) / 2;       // levels over chunks
  localparam int NCP = 1 << (2 * LVC);              // chunks, padded to 4**LVC
  localparam int CIW = 2 * LVC;                     // bits of chunk index
  // Truncations here are intended and are written as slices of a named
  // 32-bit intermediate rather than left implicit, which is what keeps
  // them distinguishable from the ones that are not - and what lets the
  // width warnings stay fatal, as tb/cocotb.mk's header insists. (Do
  // not open a comment line with the simulator's name: it reads one as
  // a metacomment and refuses the file.)
  localparam logic [31:0] NWM1_FULL = NW - 1;
  localparam logic [9:0]  NWM1      = NWM1_FULL[9:0];

  // NW <= 1024 is the real ceiling: lsh is ten bits, and the chunk
  // index and the 0..63 offset are concatenated into it below.
  generate
    if (NW < 4 || NW > 1024) begin : g_bad_nw
      $error("cft_lzcone: NW must be between 4 and 1024");
    end
  endgenerate

  initial begin
    if (NW < 4 || NW > 1024) begin
      $display("FATAL: cft_lzcone NW=%0d outside 4..1024", NW);
      $fatal(1);
    end
  end

  // The window sits at the TOP of the padded field, so its leading-zero
  // count is unchanged by the padding and every chunk that is all
  // padding folds to a constant zero flag.
  logic [NCP*64-1:0] padded;
  logic [NCP-1:0]    cvalid;

  always_comb begin
    padded = '0;
    padded[NCP*64-1 -: NW] = v;
    for (int i = 0; i < NCP; i = i + 1) cvalid[i] = |padded[64*i +: 64];
  end

  // Which chunk, counted in chunks from the top.
  logic       any;
  logic [9:0] ctop;
  cft_lz4 #(.W(NCP)) u_chunk (.x(cvalid), .vld(any), .cnt(ctop));

  // That chunk's 64 bits, and where its top 1 sits inside them. The
  // chunk NUMBER is (NCP-1) - ctop, and since NCP-1 is all ones in CIW
  // bits that subtraction is exactly a bit-complement - no borrow, no
  // width to get wrong. Multiplying it by 64 is a concatenation for the
  // same reason: `64 * x` would be evaluated at x's own width.
  logic [CIW-1:0]   ctop_i, chunk_i;
  logic [63:0]      sel;
  logic [9:0]       wz;
  logic             selv;
  assign ctop_i  = ctop[CIW-1:0];
  assign chunk_i = ~ctop_i;
  always_comb sel = padded[{chunk_i, 6'b0} +: 64];
  cft_lz4 #(.W(64)) u_bits (.x(sel), .vld(selv), .cnt(wz));

  // ctop whole chunks of 64 plus wz inside the chunk. A concatenation
  // rather than a multiply-add, because wz is 0..63 by construction and
  // saying so in the source is what keeps the two halves from drifting.
  logic [9:0] lsh_all;
  assign lsh_all = {ctop[3:0], wz[5:0]};

  assign empty = ~any;
  assign lsh   = any ? lsh_all : 10'd0;
  assign msb   = any ? (NWM1 - lsh_all) : 10'd0;

endmodule
