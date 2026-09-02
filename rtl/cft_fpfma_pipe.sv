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
// Stage map (LATENCY = 15 edges, S0..S14):
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
//   S11   LZC (per-64 chunk tree) + coarse normalize shift
//   S12   fine normalize shift
//   S13   round-window extraction (clamped and as-if-unbounded),
//         attribute-directed increment, tininess-after-rounding
//   S14   pack + specials mux -> output registers
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
    parameter int LATENCY = 15,
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
    parameter int ALN_W = 3 * MAN_W + 8
) (
    input  logic                 clk,
    input  logic                 rst_n,
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
  localparam int NCH  = (NW + 63) / 64;

  // multiplier decomposition
  localparam int MCH  = 24;                    // chunk width
  localparam int NMC  = (P + MCH - 1) / MCH;   // chunks (fp256: 10)
  localparam int PPW  = 2 * P + 2 * MCH;       // uniform tree width

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

  localparam int DEPTH = 15;

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
      $error("cft_fpfma_pipe: LATENCY must equal the structural depth (15)");
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
  end

  logic [DEPTH-1:0] v;
  always_ff @(posedge clk) begin
    if (!rst_n) v <= '0;
    else        v <= {v[DEPTH-2:0], in_valid};
  end
  assign out_valid = v[DEPTH-1];

  // ------------------------------------------------------------------
  // S0: input registers
  // ------------------------------------------------------------------
  logic [W-1:0] s0_a, s0_b, s0_c;
  logic         s0_byp;
  logic [W-1:0] s0_byp_d;
  logic [4:0]   s0_byp_f;
  always_ff @(posedge clk) begin
    s0_a <= a; s0_b <= b; s0_c <= c;
    s0_byp <= byp; s0_byp_d <= byp_d; s0_byp_f <= byp_f;
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
    rd_dly[0] <= rnd;
    for (int i = 1; i <= DEPTH-2; i = i + 1) rd_dly[i] <= rd_dly[i-1];
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
    end else begin : g_mul_local
      logic [PPW-1:0] s2_pp [0:15];
      logic [PPW-1:0] s3_q  [0:7];
      logic [PPW-1:0] s4_t  [0:3];
      logic [PPW-1:0] s5_u  [0:1];
      logic [2*P-1:0] s6_mp_r;

      logic [NMC*MCH-1:0] mb_pad;
      assign mb_pad = {{(NMC*MCH-P){1'b0}}, s1_mb};

      always_ff @(posedge clk) begin : mult_stages
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
    s7_big    <= n7_bigv;
    s7_marker <= n7_marker;
    s7_sbig <= s6_sbig; s7_ssml <= s6_ssml;
    s7_g <= s6_g;
    s7_spc <= s6_spc; s7_spd <= s6_spd; s7_spf <= s6_spf;
  end

  logic [GW-1:0] s8_bigf, s8_smlf;
  logic          s8_sbig, s8_ssml, s8_spc;
  logic [W-1:0]  s8_spd;
  logic [4:0]    s8_spf;
  int            s8_g;

  always_ff @(posedge clk) begin : stage8
    s8_bigf <= {s7_big, 1'b0};
    s8_sbig <= s7_sbig; s8_ssml <= s7_ssml;
    s8_g <= s7_g;
    s8_spc <= s7_spc; s8_spd <= s7_spd; s8_spf <= s7_spf;
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
      always_ff @(posedge clk) s8_marker <= s7_marker;
      assign s8_smlf = {aln_d[GW-2:0], s8_marker};
    end else begin : g_align_priv
      logic [GW-2:0] s7_sml;
      logic [5:0]    s7_fsh;
      logic          s7_right;
      always_ff @(posedge clk) begin
        s7_sml   <= s6_right ? (n7_smlv >> (s6_csh * 64))
                             : (n7_smlv << (s6_csh * 64));
        s7_fsh   <= aln_fshw[5:0];
        s7_right <= s6_right;
      end
      always_ff @(posedge clk) begin
        s8_smlf <= {s7_right ? (s7_sml >> s7_fsh) : (s7_sml << s7_fsh),
                    s7_marker};
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

  logic [GW:0]  s10_mag;
  logic         s10_rsign, s10_spc;
  logic [W-1:0] s10_spd;
  logic [4:0]   s10_spf;
  int           s10_g;

  always_ff @(posedge clk) begin : stage10
    logic [HHW-1:0] sumH, dAH, dBH;
    logic negA;
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

  // ------------------------------------------------------------------
  // S11: LZC + coarse normalize; S12: fine normalize
  // ------------------------------------------------------------------
  function automatic int lzc64(input logic [63:0] x);
    int r;
    begin
      r = 64;
      for (int i = 0; i < 64; i = i + 1) if (x[i]) r = 63 - i;
      lzc64 = r;
    end
  endfunction

  // s11_valw and s11_fine are the private shifter's own intermediate
  // and live inside the generate below, so a shared lane does not carry
  // an undriven register it never reads.
  logic          s11_stk, s11_zero, s11_rsign, s11_spc;
  logic [W-1:0]  s11_spd;
  logic [4:0]    s11_spf;
  int            s11_enorm;

  // ---- S11 combinational: the leading-zero scan and the distance ----
  //
  // Split out of the register process below so that a shared normaliser
  // can be handed exactly the values the private one uses. Nothing here
  // changed when it was split: the scan, the msb and the two halves of
  // the distance are what stage11 always computed, they are just named
  // now instead of being locals inside an always_ff.
  //
  // n11_lsh is the total left shift, NW-1-msb, and the pipe's own split
  // of it into whole 64-bit granules plus a 0..63 remainder is what the
  // nrm_csh/nrm_fsh ports carry. Taking the halves as bit-selects of
  // n11_lsh rather than by arithmetic keeps csh*64 + fsh == lsh true by
  // construction.
  logic [NW-1:0] n11_valw;
  logic          n11_empty;
  logic [9:0]    n11_lsh;
  logic [3:0]    n11_csh;
  logic [5:0]    n11_fsh;
  int            n11_msb;

  always_comb begin
    logic [NCH*64-1:0] padded;
    logic [31:0] lsh_full;
    int chunk, cl;
    // Default-assigned before the branch. `cl` is only meaningful in
    // the non-empty case, but a block-local written on one path of an
    // always_comb is a latch, and Yosys refuses it - which is the whole
    // reason the portability gate exists. This was a clocked process
    // before the split, where the same code is unremarkable.
    cl = 0;
    lsh_full = '0;
    n11_valw = s10_mag[GW:1];
    padded = {{(NCH*64-NW){1'b0}}, n11_valw};
    chunk = -1;
    for (int ci = NCH - 1; ci >= 0; ci = ci - 1) begin
      if (chunk == -1 && (padded[ci*64 +: 64] != 0)) chunk = ci;
    end
    if (chunk == -1) begin
      // An empty window: n11_valw is zero by definition here, so any
      // shift of it is zero and the distance is a don't-care. Driving
      // zero rather than leaving it undefined matters for the shared
      // path, where this lane's amount reaches a ladder other lanes
      // are also using.
      n11_empty = 1'b1;
      n11_msb   = 0;
      n11_lsh   = '0;
    end else begin
      cl        = lzc64(padded[chunk*64 +: 64]);
      n11_msb   = chunk * 64 + (63 - cl);
      n11_empty = 1'b0;
      // NW-1-msb is at most 716 (fp256), so ten bits hold it. Taken as
      // an explicit slice of a named 32-bit intermediate rather than by
      // implicit truncation: the truncation is intended, and saying so
      // in the source is what keeps it distinguishable from the ones
      // that are not. (A width cast would read better still, but Icarus
      // is uneven about casts - cft_mulfrac's own comment records it.)
      lsh_full  = NW - 1 - n11_msb;
      n11_lsh   = lsh_full[9:0];
    end
    n11_csh = n11_lsh[9:6];
    n11_fsh = n11_lsh[5:0];
  end

  assign nrm_v   = n11_valw;
  assign nrm_csh = n11_csh;
  assign nrm_fsh = n11_fsh;

  // S11 registers, less the shift itself. The empty-window case:
  //
  // Exact zero only without sticky residue; else a bare epsilon,
  // and s10_g already places it below the subnormal grid so S13
  // rounds it per the attribute, carrying the true sign.
  //
  // Why that holds - it is NOT because the anchor is zero (a
  // nonzero subnormal addend reaches here too: fp32
  // a=0x1ef3ab49 b=0x1ef536f9 c=0x80074b3a cancels to an empty
  // window with the marker set). It is because an empty window
  // with a surviving residue requires the anchor's significand
  // below 2^(P-4), which forces it subnormal or zero - and any
  // subnormal pins its exponent at EMIN-MAN_W, so g = EMIN-MAN_W-SH
  // and S13's K is negative. Change SH or the far-alignment
  // threshold and this is the argument to re-derive.
  always_ff @(posedge clk) begin : stage11
    s11_zero  <= n11_empty && !s10_mag[0];
    s11_enorm <= n11_empty ? s10_g : (s10_g + n11_msb);
    s11_stk   <= s10_mag[0];
    s11_rsign <= s10_rsign;
    s11_spc <= s10_spc; s11_spd <= s10_spd; s11_spf <= s10_spf;
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

  // ---- the two normalise shifters, here or elsewhere ----------------
  //
  // Private: exactly what stage11 and stage12 did before the split -
  // coarse by whole granules into s11_valw, then the remainder into
  // s12_norm. The empty-window case needs no special handling because
  // n11_valw IS zero then and n11_csh/n11_fsh are driven zero, so
  // `n11_valw << 0` reproduces the old `s11_valw <= '0` exactly.
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
        s11_valw <= n11_valw << (n11_csh * 64);
        s11_fine <= n11_fsh;
      end
      always_ff @(posedge clk) begin
        s12_norm <= s11_valw << s11_fine;
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

endmodule
