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
    parameter int LATENCY = 15
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
    output logic [4:0]           flags
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
  // rd_dly[k] is aligned with the s{k}_* stage registers: it holds the
  // attribute of the operation whose data those registers hold. The
  // last consumer is stage 14, which reads s13_*, so the line stops at
  // DEPTH-2 rather than carrying a register nothing reads.
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
    efa_i = efa; efb_i = efb; efc_i = efc;
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
  logic [PPW-1:0] s2_pp [0:15];
  logic [PPW-1:0] s3_q  [0:7];
  logic [PPW-1:0] s4_t  [0:3];
  logic [PPW-1:0] s5_u  [0:1];
  logic [2*P-1:0] s6_mp;

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
    // S6: L4 final, shift 192
    s6_mp <= s5_u[0] + (s5_u[1] << (8*MCH));
  end

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
  logic [GW-2:0] s7_big, s7_sml;
  logic          s7_sbig, s7_ssml, s7_marker, s7_right, s7_spc;
  logic [W-1:0]  s7_spd;
  logic [4:0]    s7_spf;
  int            s7_g, s7_fsh;

  always_ff @(posedge clk) begin : stage7
    logic [GW-2:0] bigv, smlv, onesv, lost_mask;
    onesv = {(GW-1){1'b1}};
    if (s6_big_is_p) begin
      bigv = {{(GW-1-2*P){1'b0}}, s6_mp} << SH;
      smlv = {{(GW-1-P){1'b0}}, s6_mc};
    end else begin
      bigv = {{(GW-1-P){1'b0}}, s6_mc} << SH;
      smlv = {{(GW-1-2*P){1'b0}}, s6_mp};
    end
    s7_big <= bigv;
    if (s6_far) begin
      s7_sml <= '0;
      s7_marker <= s6_mkpre;
    end else if (s6_right) begin
      s7_sml <= smlv >> (s6_csh * 64);
      lost_mask = ~(onesv << (s6_csh * 64));
      s7_marker <= (s6_csh != 0) && (|(smlv & lost_mask));
    end else begin
      s7_sml <= smlv << (s6_csh * 64);
      s7_marker <= 1'b0;
    end
    s7_right <= s6_right;
    s7_fsh <= s6_fsh;
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
    logic [GW-2:0] onesv, fmask;
    logic fmarker;
    onesv = {(GW-1){1'b1}};
    s8_bigf <= {s7_big, 1'b0};
    if (s7_right) begin
      fmask = ~(onesv << s7_fsh);
      fmarker = s7_marker | ((s7_fsh != 0) && (|(s7_sml & fmask)));
      s8_smlf <= {s7_sml >> s7_fsh, fmarker};
    end else begin
      s8_smlf <= {s7_sml << s7_fsh, s7_marker};
    end
    s8_sbig <= s7_sbig; s8_ssml <= s7_ssml;
    s8_g <= s7_g;
    s8_spc <= s7_spc; s8_spd <= s7_spd; s8_spf <= s7_spf;
  end

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

  logic [NW-1:0] s11_valw;
  logic          s11_stk, s11_zero, s11_rsign, s11_spc;
  logic [W-1:0]  s11_spd;
  logic [4:0]    s11_spf;
  int            s11_enorm, s11_fine;

  always_ff @(posedge clk) begin : stage11
    logic [NCH*64-1:0] padded;
    logic [NW-1:0] valw;
    int chunk, cl, msb, lsh_coarse;
    valw = s10_mag[GW:1];
    padded = {{(NCH*64-NW){1'b0}}, valw};
    chunk = -1;
    for (int ci = NCH - 1; ci >= 0; ci = ci - 1) begin
      if (chunk == -1 && (padded[ci*64 +: 64] != 0)) chunk = ci;
    end
    if (chunk == -1) begin
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
      s11_zero <= !s10_mag[0];
      s11_valw <= '0;
      s11_enorm <= s10_g;
      s11_fine <= 0;
    end else begin
      cl  = lzc64(padded[chunk*64 +: 64]);
      msb = chunk * 64 + (63 - cl);
      s11_zero  <= 1'b0;
      s11_enorm <= s10_g + msb;
      lsh_coarse = (NW - 1 - msb) >> 6;
      s11_valw <= valw << (lsh_coarse * 64);
      s11_fine <= (NW - 1 - msb) & 63;
    end
    s11_stk   <= s10_mag[0];
    s11_rsign <= s10_rsign;
    s11_spc <= s10_spc; s11_spd <= s10_spd; s11_spf <= s10_spf;
  end

  logic [NW-1:0] s12_norm;
  logic          s12_stk, s12_zero, s12_rsign, s12_spc;
  logic [W-1:0]  s12_spd;
  logic [4:0]    s12_spf;
  int            s12_enorm;

  always_ff @(posedge clk) begin : stage12
    s12_norm  <= s11_valw << s11_fine;
    s12_stk   <= s11_stk;
    s12_zero  <= s11_zero;
    s12_enorm <= s11_enorm;
    s12_rsign <= s11_rsign;
    s12_spc <= s11_spc; s12_spd <= s11_spd; s12_spf <= s11_spf;
  end

  // ------------------------------------------------------------------
  // S13: rounding (clamped and as-if-unbounded windows)
  // ------------------------------------------------------------------
  logic [P:0]   s13_kept_r;
  logic         s13_inexact, s13_tiny, s13_zero, s13_rsign, s13_spc;
  logic [W-1:0] s13_spd;
  logic [4:0]   s13_spf;
  int           s13_q;

  always_ff @(posedge clk) begin : stage13
    int K, sh_amt;
    logic [NW-1:0] shifted, low_mask, ones;
    logic [P:0] kept;
    logic guard, sticky, up;
    logic [P-1:0] kept_u;
    logic guard_u, sticky_u, up_u, carry_u;

    ones = {NW{1'b1}};
    K = (s12_enorm >= EMIN) ? P : (P - (EMIN - s12_enorm));
    s13_q     <= ((s12_enorm >= EMIN) ? s12_enorm : EMIN) - (P - 1);
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
      s13_tiny <= (s12_enorm + (carry_u ? 1 : 0)) < EMIN;

      if (K <= 0) begin
        // Entirely below the subnormal grid. K == 0 puts the value's
        // MSB in the guard position; K < 0 puts everything into the
        // sticky. Either way the result is inexact, and only the
        // attribute decides whether it becomes zero or one ulp.
        guard  = (K == 0);
        sticky = (K == 0) ? ((|s12_norm[NW-2:0]) | s12_stk) : 1'b1;
        kept   = '0;
      end else begin
        sh_amt  = NW - K;
        shifted = s12_norm >> sh_amt;
        kept    = shifted[P:0];
        guard   = s12_norm[sh_amt-1];
        if (sh_amt >= 2) begin
          low_mask = ~(ones << (sh_amt - 1));
          sticky = (|(s12_norm & low_mask)) | s12_stk;
        end else begin
          sticky = s12_stk;
        end
      end
      up = round_up(rd_dly[DEPTH-3], s12_rsign, guard, sticky, kept[0]);
      s13_kept_r  <= kept + {{P{1'b0}}, up};
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
            biased_f = e_res + BIAS;
            res = {s13_rsign, biased_f, kr[MAN_W-1:0]};
          end
        end
      end
    end
    d     <= res;
    flags <= fl;
  end

endmodule
