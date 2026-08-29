// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// cft_fpfma: parameterized IEEE 754-2019 fusedMultiplyAdd, d = a*b + c.
//
// One module, any binary interchange format: (EXP_W, MAN_W) =
// (8,23) fp32, (11,52) fp64, (15,112) fp128, (19,236) fp256.
//
// Semantics (the determinism contract, docs/DETERMINISM.md):
//   * roundTiesToEven only (mode input reserved for v1)
//   * subnormals in and out, never flushed
//   * one rounding: the product is exact inside the datapath
//   * canonical qNaN out (sign 0, quiet bit, payload 0); sNaN in
//     raises invalid
//   * signed zeros per IEEE 754-2019 6.3; exact cancellation is +0
//   * flags: {inexact, underflow, overflow, divzero, invalid},
//     underflow = tininess AFTER rounding AND inexact (as RISC-V)
//
// This is the v0 BEHAVIOURAL datapath: a single combinational cloud,
// written to be read against python/cft_golden/softfloat.py line by
// line. It simulates exactly and synthesizes correctly but slowly; the
// v1 pipelined/fractured implementation replaces it behind the same
// ports and the same testbench.
//
// Datapath sketch (all widths in units of P = MAN_W+1):
//
//   product m_a*m_b (2P bits) and addend m_c (P bits) meet on a fixed
//   grid anchored SH = P+4 bits above the grid LSB, with the
//   smaller-exponent operand shifted right; bits that fall off the
//   grid OR into one appended "marker" LSB. The marker participates
//   in the magnitude subtract, which makes floor-plus-sticky exact:
//   subtracting a tail t in (0, 2^g) as one marker bit yields
//   kept-1 with a nonzero remainder, exactly floor semantics.
//   Safety argument for the marker (mirrored from the golden model):
//   the marker can only be set when the operands' LSB weights differ
//   by more than SH, and then no cancellation is possible, so the
//   rounding position sits at least 3 bits above the marker and the
//   marker can never be the guard or tie bit.

`timescale 1ns/1ps

module cft_fpfma #(
    parameter int EXP_W = 8,
    parameter int MAN_W = 23
) (
    input  logic [EXP_W+MAN_W:0] a,
    input  logic [EXP_W+MAN_W:0] b,
    input  logic [EXP_W+MAN_W:0] c,
    output logic [EXP_W+MAN_W:0] d,
    output logic [4:0]           flags
);

  localparam int W    = 1 + EXP_W + MAN_W;
  localparam int P    = MAN_W + 1;
  localparam int BIAS = (1 << (EXP_W - 1)) - 1;
  localparam int EMIN = 1 - BIAS;
  localparam int EMAX = BIAS;
  localparam int SH   = P + 4;         // grid offset of the anchor operand
  localparam int VW   = 2 * P + SH + 1; // value-bit grid width (incl carry)
  // full grid words carry one marker LSB below the value bits
  localparam int GW   = VW + 1;

  // flag bit positions (match cft_golden.softfloat FLAG_*)
  localparam int FL_INVALID   = 0;
  localparam int FL_DIVZERO   = 1;
  localparam int FL_OVERFLOW  = 2;
  localparam int FL_UNDERFLOW = 3;
  localparam int FL_INEXACT   = 4;

  // ---- field extraction ---------------------------------------------
  logic                sa, sb, sc;
  logic [EXP_W-1:0]    efa, efb, efc;
  logic [MAN_W-1:0]    fra, frb, frc;
  logic a_nan, b_nan, c_nan, a_snan, b_snan, c_snan;
  logic a_inf, b_inf, c_inf, a_zero, b_zero, c_zero, a_sub, b_sub, c_sub;
  logic [P-1:0] ma, mb, mc;
  int ea, eb, ec, efa_i, efb_i, efc_i;

  // canonical quiet NaN: sign 0, exponent all ones, quiet bit only
  logic [W-1:0] qnan;
  assign qnan = {1'b0, {EXP_W{1'b1}}, 1'b1, {(MAN_W-1){1'b0}}};

  always_comb begin
    sa  = a[W-1];  sb  = b[W-1];  sc  = c[W-1];
    efa = a[W-2 -: EXP_W]; efb = b[W-2 -: EXP_W]; efc = c[W-2 -: EXP_W];
    fra = a[MAN_W-1:0];    frb = b[MAN_W-1:0];    frc = c[MAN_W-1:0];

    a_nan  = (&efa) && (fra != 0);
    b_nan  = (&efb) && (frb != 0);
    c_nan  = (&efc) && (frc != 0);
    a_snan = a_nan && !fra[MAN_W-1];
    b_snan = b_nan && !frb[MAN_W-1];
    c_snan = c_nan && !frc[MAN_W-1];
    a_inf  = (&efa) && (fra == 0);
    b_inf  = (&efb) && (frb == 0);
    c_inf  = (&efc) && (frc == 0);
    a_zero = (efa == 0) && (fra == 0);
    b_zero = (efb == 0) && (frb == 0);
    c_zero = (efc == 0) && (frc == 0);
    a_sub  = (efa == 0) && (fra != 0);
    b_sub  = (efb == 0) && (frb != 0);
    c_sub  = (efc == 0) && (frc != 0);

    ma = a_sub ? {1'b0, fra} : {1'b1, fra};
    mb = b_sub ? {1'b0, frb} : {1'b1, frb};
    mc = c_sub ? {1'b0, frc} : {1'b1, frc};
    // significand-LSB-weight exponents: value = m * 2^e
    efa_i = efa;  efb_i = efb;  efc_i = efc;
    ea = ((efa == 0) ? 1 : efa_i) - BIAS - MAN_W;
    eb = ((efb == 0) ? 1 : efb_i) - BIAS - MAN_W;
    ec = ((efc == 0) ? 1 : efc_i) - BIAS - MAN_W;
  end

  // ---- helper: index of the most significant set bit ----------------
  function automatic int fls_grid(input logic [GW-1:0] v);
    int r;
    begin
      r = -1;
      for (int i = 0; i < GW; i = i + 1) begin
        if (v[i]) r = i;
      end
      fls_grid = r;
    end
  endfunction

  function automatic int bitlen_p1(input logic [P:0] v);
    int r;
    begin
      r = 0;
      for (int i = 0; i <= P; i = i + 1) begin
        if (v[i]) r = i + 1;
      end
      bitlen_p1 = r;
    end
  endfunction

  // ---- main datapath ------------------------------------------------
  logic        sp;              // product sign
  logic [2*P-1:0] mp;           // exact product significand
  int          ep;              // product LSB-weight exponent

  always_comb begin : datapath
    // grid operands
    logic [VW-1:0] mp_w, mc_w, gbig, gsml_v;
    logic [GW-1:0] bigf, smlf, sumh, magg;
    logic          marker, sbig, ssml, rsign;
    logic [P-1:0]  sml_mask_lo;
    logic [2*P-1:0] sml2_mask_lo;
    logic [P:0]    kept_r, kept_ur;
    logic [EXP_W-1:0] biased_f;
    logic [GW-1:0] kept_w, kept_uw, low_mask, ones;
    int dd, t, g, msb, e_norm, e_use, q, j, ju, e_res, bl, e_after_u;
    logic guard, sticky, up, inexact, kept_zero;
    logic guard_u, sticky_u, up_u, carry_u, tiny;
    logic [W-1:0] res;
    logic [4:0] fl;

    // defaults - every block-local gets one so no tool can infer a
    // latch from a branch that leaves a temporary unassigned (Yosys
    // enforces combinational completeness strictly; Vivado and Icarus
    // are permissive - the open flow keeps us honest)
    res = '0;
    fl = '0;
    mp_w = '0;  mc_w = '0;  gbig = '0;  gsml_v = '0;
    bigf = '0;  smlf = '0;  sumh = '0;  magg = '0;
    marker = 1'b0;  sbig = 1'b0;  ssml = 1'b0;  rsign = 1'b0;
    sml_mask_lo = '0;  sml2_mask_lo = '0;
    kept_r = '0;  kept_ur = '0;  biased_f = '0;
    kept_w = '0;  kept_uw = '0;  low_mask = '0;  ones = '0;
    dd = 0;  t = 0;  g = 0;  msb = 0;  e_norm = 0;  e_use = 0;
    q = 0;  j = 0;  ju = 0;  e_res = 0;  bl = 0;  e_after_u = 0;
    guard = 1'b0;  sticky = 1'b0;  up = 1'b0;  inexact = 1'b0;
    kept_zero = 1'b0;  guard_u = 1'b0;  sticky_u = 1'b0;
    up_u = 1'b0;  carry_u = 1'b0;  tiny = 1'b0;
    sp = sa ^ sb;
    mp = ma * mb;                 // context-widened: full 2P-bit product
    ep = ea + eb;

    if (a_nan || b_nan || c_nan) begin
      res = qnan;
      fl[FL_INVALID] = a_snan || b_snan || c_snan;
    end else if ((a_inf && b_zero) || (b_inf && a_zero)) begin
      res = qnan;                 // inf * 0
      fl[FL_INVALID] = 1'b1;
    end else if (a_inf || b_inf) begin
      if (c_inf && (sc != sp)) begin
        res = qnan;               // inf - inf
        fl[FL_INVALID] = 1'b1;
      end else begin
        res = {sp, {EXP_W{1'b1}}, {MAN_W{1'b0}}};
      end
    end else if (c_inf) begin
      res = {sc, {EXP_W{1'b1}}, {MAN_W{1'b0}}};
    end else if (a_zero || b_zero) begin
      if (c_zero) begin
        // exact zero + exact zero: keep the sign only when they agree
        res = {(sc == sp) ? sc : 1'b0, {(W-1){1'b0}}};
      end else begin
        res = c;                  // 0*b + c == c exactly
      end
    end else begin
      // ---- finite fused path (c may be zero: mc contributes nothing)
      ones = {GW{1'b1}};
      mp_w = mp;                  // zero-extended into the grid
      mc_w = c_zero ? '0 : {{(VW-P){1'b0}}, mc};
      marker = 1'b0;

      if (ep >= ec) begin
        dd   = ep - ec;
        g    = ep - SH;
        sbig = sp;  ssml = sc;
        gbig = mp_w << SH;
        if (dd <= SH) begin
          gsml_v = mc_w << (SH - dd);
        end else begin
          t = dd - SH;
          if (t > P + 2) t = P + 2;      // beyond this mc is pure sticky
          gsml_v = mc_w >> t;
          sml_mask_lo = ~({P{1'b1}} << t);
          marker = c_zero ? 1'b0 : |(mc & sml_mask_lo);
        end
      end else begin
        dd   = ec - ep;
        g    = ec - SH;
        sbig = sc;  ssml = sp;
        gbig = mc_w << SH;
        if (dd <= SH) begin
          gsml_v = mp_w << (SH - dd);
        end else begin
          t = dd - SH;
          if (t > 2 * P + 2) t = 2 * P + 2;
          gsml_v = mp_w >> t;
          sml2_mask_lo = ~({(2*P){1'b1}} << t);
          marker = |(mp & sml2_mask_lo);
        end
      end

      bigf = {gbig, 1'b0};
      smlf = {gsml_v, marker};

      // sign-magnitude add: unsigned compares keep the wide math simple
      if (sbig == ssml) begin
        magg  = bigf + smlf;
        rsign = sbig;
      end else if (bigf >= smlf) begin
        magg  = bigf - smlf;
        rsign = sbig;
      end else begin
        magg  = smlf - bigf;
        rsign = ssml;
      end

      if (magg == 0) begin
        // exact cancellation of non-zero operands: +0 under RNE
        res = '0;
      end else begin
        msb    = fls_grid(magg);      // >= 1 whenever the marker is 0 or set
        e_norm = g + msb - 1;         // bit i>=1 of magg has weight g+i-1
        e_use  = (e_norm >= EMIN) ? e_norm : EMIN;
        q      = e_use - (P - 1);
        j      = q - g + 1;           // grid index of the result ulp

        if (j <= 0) begin
          // every value bit is at or above the ulp: exact
          kept_w  = (magg >> 1) << (1 - j);
          inexact = 1'b0;
          up      = 1'b0;
        end else begin
          kept_w   = magg >> j;
          guard    = magg[j-1];
          if (j >= 2) begin
            low_mask = ~(ones << (j - 1));
            sticky   = |(magg & low_mask);
          end else begin
            sticky = 1'b0;
          end
          inexact = guard || sticky;
          up      = guard && (sticky || kept_w[0]);
        end
        kept_r = kept_w[P:0] + {{P{1'b0}}, up};

        // tininess after rounding: round again as if unbounded
        ju = msb - P + 1;
        if (ju <= 0) begin
          carry_u = 1'b0;
        end else begin
          kept_uw = magg >> ju;
          guard_u = magg[ju-1];
          if (ju >= 2) begin
            low_mask = ~(ones << (ju - 1));
            sticky_u = |(magg & low_mask);
          end else begin
            sticky_u = 1'b0;
          end
          kept_ur = kept_uw[P:0];
          up_u    = guard_u && (sticky_u || kept_ur[0]);
          kept_ur = kept_ur + {{P{1'b0}}, up_u};
          carry_u = kept_ur[P];
        end
        e_after_u = e_norm + (carry_u ? 1 : 0);
        tiny = e_after_u < EMIN;

        fl[FL_INEXACT] = inexact;
        if (kept_r == 0) begin
          // rounded away below the smallest subnormal
          res = {rsign, {(W-1){1'b0}}};
          fl[FL_UNDERFLOW] = 1'b1;
        end else begin
          bl    = bitlen_p1(kept_r);
          e_res = q + bl - 1;
          if (e_res > EMAX) begin
            res = {rsign, {EXP_W{1'b1}}, {MAN_W{1'b0}}};
            fl[FL_OVERFLOW] = 1'b1;
            fl[FL_INEXACT]  = 1'b1;
          end else begin
            if (tiny && inexact) fl[FL_UNDERFLOW] = 1'b1;
            if (e_res < EMIN) begin
              // subnormal: kept_r has < P bits, LSB weight EMIN-(P-1)
              res = {rsign, {EXP_W{1'b0}}, kept_r[MAN_W-1:0]};
            end else begin
              if (bl == P + 1) kept_r = kept_r >> 1; // carry-out: 2^P
              biased_f = e_res + BIAS;
              res = {rsign, biased_f, kept_r[MAN_W-1:0]};
            end
          end
        end
      end
    end

    d     = res;
    flags = fl;
  end

endmodule
