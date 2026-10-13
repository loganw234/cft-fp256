# M2 model: sin, cos and tan as tile routines, double-word formats (fp64,
# fp128, fp256) (scratch; the study's sections 2 to 4).
#
#   classify   NaN, signalling, infinity, zero, the tiny gate, the range
#   reduce     m2red.reduce_ph: |x| = n pi/2 + r, r = r_h + r_l,
#              |r| <= pi/4 (1 + tiny), n mod 4 in q's encoding
#   z          r_h^2 as an exact double word (TwoProd)
#   S, C       S(z) = sin(r)/r and C(z) = cos(r), Taylor: a single-word
#              Horner tail in z_h from degree D down to K, then K
#              double-word steps in the double word z (the coefficients'
#              low words where they have one)
#   sin, cos   sin(r_h) = r_h S, cos(r_h) = C, as double words; r_l's
#              share by the derivative: + cos(r_h) r_l, - sin(r_h) r_l
#   select     by n: sin(|x|) = S, C, -S, -C; cos = C, -S, -C, S;
#              tan = S/C or -C/S (a double-word quotient: RECIP_SEED,
#              Newton, the exact remainder); x's sign for sin and tan.
#              The sign is applied to the double word V before its one
#              rounding
#   final      R = rnd(V_h + V_l); the in-lane test of M1's 3.1 with
#              Bv = 2^-(p+G) |V_h|; for sin and cos the clamp |T| < 1
#              (Hermite-Lindemann, transcend.py's beside-one rule): the
#              roundings of both ends and of the guess are taken within
#              [rnd(-1+), rnd(1-)]
#   specials   the tiny paths (the definition's neighbour rules, by one
#              FMA under the attribute), +-0, +-inf, NaN; past a stated
#              range (fp128, fp256) the lane is marked
#
# Every lane's work is the same up to `select`, whatever the function:
# sin, cos and tan of one argument share their prefix instruction for
# instruction, so cftc's inliner, which hash-conses a routine's
# instructions across instances, computes it once.

import math
from fractions import Fraction

from m2core import (Frag, FORMATS, sf, enc, enc_exact, dec, pow2_bits,
                    words_of, RNE, RTZ, RDN, RUP, RMM)
from m2const import sin_coef, cos_coef, pi_frac
from m2plan import plan, LOST
from m2red import reduce_ph, PLANTS_RED

# G: M1's, as Logan decided them (2026-10-12), at fp64, fp128 and fp256.
# fp32: M1's 40 is a TRIPLE-word guard; this model builds fp32 in DOUBLE
# words only, which reach G = 18 at most there (plan()'s exactness
# constraints fail from G = 20), so its fp32 is the double word at 18 (the
# study's 2.7 and question 4).
GUARD = {"fp32": 18, "fp64": 44, "fp128": 46, "fp256": 46}
RANGE = {"fp32": None, "fp64": None, "fp128": 1024, "fp256": 1024}   # |x| < 2^R; None: all


def gates(fmt):
    """The definition's tiny gates as |x| < 2^g: sin 2e + p + 2 <= 0, tan
    and cos 2e + p + 3 <= 0, e = floor(log2 |x|)."""
    p = fmt.prec
    es = math.floor(-(p + 2) / 2)
    ec = math.floor(-(p + 3) / 2)
    return es + 1, ec + 1


def plan_poly(fmt, G, rho):
    """(K, D) for S and for C: the head covers every k whose term
    |c_k| rho^(2k) exceeds 2^-(G+3) (a single word's rounding there would
    reach the bound), and the truncation |c_(D+1)| rho^(2D+2) is under
    2^-(p+G+3). Exact rational arithmetic."""
    p = fmt.prec
    z = rho * rho
    out = []
    for coef in (sin_coef, cos_coef):
        K = 0
        while abs(coef(K)) * z ** K > Fraction(1, 2 ** (G + 3)):
            K += 1
        D = K
        while abs(coef(D + 1)) * z ** (D + 1) > Fraction(1, 2 ** (p + G + 3)):
            D += 1
        out.append((K, D))
    return out


PLANTS = PLANTS_RED + ("quadrant-sign", "clamp-tight", "bound-loose",
                       "mark-silenced", "coef", "newton-short",
                       "tiny-gate-off", "rl-dropped", "zl-dropped",
                       "clamp-off")


def build(fmt, rnd, fn, G=None, bound_shift=0, variant="A", Pr=None,
          range_exp="default", clamp=True, plant=None):
    """One routine, instrumented (pruned; the unpruned body kept as
    all_body). `plant`, one of PLANTS, builds one named fault (plants.py):
    the reduction's (m2red.PLANTS_RED), and
      quadrant-sign  cos's sign taken from n's low bit alone
      clamp-tight    the clamp's ends one ulp inside rnd(+-1 -+ tiny)
      bound-loose    the in-lane bound 2^40 times too small
      mark-silenced  the flag word never carries the mark
      coef           S's z^1 coefficient without its low word
      newton-short   tan's reciprocal one Newton step short
      tiny-gate-off  no tiny path: every lane the main path's
      rl-dropped     r_l's share (the derivative terms) left out
      zl-dropped     z_l's share in the head left out
      clamp-off      no clamp: not a fault, the |T| < 1 rule switched off"""
    assert fn in ("sin", "cos", "tan")
    assert plant is None or plant in PLANTS, plant
    if plant == "clamp-off":
        clamp = False
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    G = GUARD[fmt.name] if G is None else G
    R = RANGE[fmt.name] if range_exp == "default" else range_exp
    gs, gc = gates(fmt)
    gate = gs if fn == "sin" else gc
    if Pr is None:
        Pr = plan(fmt, G, LOST[fmt.name], (R - 1) if R else fmt.emax,
                  min(gs, gc) - 1)
    f = Frag(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}")
    f.meta.update(G=G, R=R, b=Pr.b, L=Pr.L, K_words=Pr.K, variant=variant)
    x = ("in", "a")
    w, wi = f.w, f.wi
    full = (1 << W) - 1
    ZERO, ONE = w(0, "ZERO"), w(sf.one_bits(fmt), "ONE")
    SIGN = wi(fmt.sign_mask, "SIGN")
    INF, QNAN = w(sf.inf_bits(fmt), "INF"), w(sf.qnan_bits(fmt), "QNAN")
    INX = wi(sf.FLAG_INEXACT, "INX")
    INXM = wi(sf.FLAG_INEXACT | 0x80, "INXM")
    UNFINX = wi(sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT, "UNFINX")
    INVALID = wi(sf.FLAG_INVALID, "INVALID")
    MAGIC = f.wx(Fraction(3, 2) * 2 ** (p - 1), "MAGIC")

    # The classification of x is emitted LATE, after the final rounding
    # (x itself is live to the end for the tiny path and the specials, so
    # deriving the conditions there keeps them out of the reduction's and
    # the polynomials' live ranges); the order of a straight-line body is
    # free, and the inliner's sharing keys on operands, not on places.

    # ---- reduce --------------------------------------------------------
    red = reduce_ph(f, x, Pr, MAGIC, variant,
                    plant if plant in PLANTS_RED else None)
    rh, rl, q = red["rh"], red["rl"], red["q"]

    # ---- the polynomials -------------------------------------------------
    rho = pi_frac() / 4 * (1 + Fraction(1, 2 ** 30))
    (KS, DS), (KC, DC) = plan_poly(fmt, G, rho)
    f.meta.update(KS=KS, DS=DS, KC=KC, DC=DC)
    f.phase = "z"
    zh = f.mul(rh, rh)
    nrh = f.ixor(rh, SIGN)
    nzl = f.fma(nrh, rh, zh)                            # zh - rh^2 = -zl
    nzh = f.ixor(zh, SIGN)

    def poly(coef, K, D, name):
        f.phase = name + "-tail"
        y = f.wv(coef(D))
        for k in range(D - 1, K - 1, -1):
            y = f.fma(y, zh, f.wv(coef(k)))
        f.phase = name + "-head"
        yh, yl = y, None
        for k in range(K - 1, -1, -1):
            ch, cl = words_of(fmt, coef(k), 2)
            if plant == "coef" and coef is sin_coef and k == 1:
                cl = 0
            CH = w(ch)
            pp = f.mul(yh, zh)
            ne = f.fma(yh, nzh, pp)                     # pp - yh zh = -err
            nl = f.fma(yl, nzh, ne) if yl is not None else ne
            if plant != "zl-dropped":
                nl = f.fma(yh, nzl, nl)                 # - yh zl
            s = f.add(CH, pp)                           # Fast2Sum(c, pp)
            f.meta["fast_two_sum"] += 1
            zz = f.sub(s, CH)
            e2 = f.sub(pp, zz)
            tt = f.sub(e2, nl)
            yl = f.add(tt, w(cl)) if cl else tt
            yh = s
        return yh, yl

    Sh, Sl = poly(sin_coef, KS, DS, "S")
    Ch, Cl = poly(cos_coef, KC, DC, "C")
    f.phase = "sincos"
    # sin(r_h) = r_h S: TwoProd, the low word r_h S_l and the error
    sh = f.mul(rh, Sh)
    ne = f.fma(nrh, Sh, sh)                             # sh - rh Sh = -err
    nsl = f.fma(nrh, Sl, ne)                            # -(err + rh Sl)
    nrl = f.ixor(rl, SIGN)
    if plant != "rl-dropped":
        nsl = f.fma(Ch, nrl, nsl)                       # - cos(r_h) r_l
    sl = f.ixor(nsl, SIGN)
    cl = Cl if plant == "rl-dropped" else f.fma(sh, nrl, Cl)  # - sin(r_h) r_l
    f.probes.update(sh=sh, sl=sl, ch=Ch, cl=cl)

    # ---- select by the quadrant, and the sign --------------------------
    f.phase = "select"
    sx = f.iand(x, SIGN)                                 # x's sign bit
    b0 = f.iand(q, wi(1, "INT1"))
    b1 = f.iand(q, wi(2, "INT2"))
    if fn == "sin":
        Vh, Vl = f.sel(Ch, sh, b0), f.sel(cl, sl, b0)
        sg = f.ixor(f.ishl(b1, wi(W - 2)), sx)
    elif fn == "cos":
        Vh, Vl = f.sel(sh, Ch, b0), f.sel(sl, cl, b0)
        sg = f.ishl(f.ixor(f.ishl(b0, wi(1)), b1), wi(W - 2))
        if plant == "quadrant-sign":
            sg = f.ishl(b0, wi(W - 1))
    else:
        Nh, Nl = f.sel(Ch, sh, b0), f.sel(cl, sl, b0)
        Dh, Dl = f.sel(sh, Ch, b0), f.sel(sl, cl, b0)
        sg = f.ixor(f.ishl(b0, wi(W - 1)), sx)
        f.phase = "quotient"
        y = f.recip_seed(Dh)
        nDh = f.ixor(Dh, SIGN)
        bits = 16 if plant == "newton-short" else 8
        while bits < p + 8:
            e = f.fma(nDh, y, ONE)                       # 1 - D y
            y = f.fma(y, e, y)
            bits *= 2
        qh = f.mul(Nh, y)
        nqh = f.ixor(qh, SIGN)
        rem = f.fma(nqh, Dh, Nh)                         # N_h - q_h D_h
        rem = f.add(rem, Nl)
        rem = f.fma(nqh, Dl, rem)
        ql = f.mul(rem, y)
        Vh, Vl = f.fast_two_sum(qh, ql)
    Vh = f.ixor(Vh, sg)
    Vl = f.ixor(Vl, sg)
    f.probes.update(Vh=Vh, Vl=Vl)

    # ---- the final rounding and the in-lane test ------------------------
    f.phase = "final"
    Rg = f.add(Vh, Vl, rnd)
    brel = pow2_bits(fmt, -(p + G) + bound_shift
                     - (40 if plant == "bound-loose" else 0))
    Bv = f.mul(f.fabs(Vh), w(brel, "BREL"))
    lo_dn = f.sub(Vl, Bv, RDN)
    lo_up = f.add(Vl, Bv, RUP)
    R1 = f.add(Vh, lo_dn, rnd)
    R2 = f.add(Vh, lo_up, rnd)
    f.probes.update(R=Rg, R1=R1, R2=R2, Bv=Bv)
    if fn in ("sin", "cos") and clamp:
        # |sin x|, |cos x| < 1 for every nonzero dyadic x: the rounding of
        # the true value lies within [rnd(-1+), rnd(1-)]
        tinyv = Fraction(1, 2 ** (3 * p))
        u1, l1 = enc(fmt, 1 - tinyv, rnd), enc(fmt, -1 + tinyv, rnd)
        if plant == "clamp-tight":
            u1, l1 = u1 - 1, l1 - 1          # one ulp toward zero each
        U1 = w(u1, "U1")
        L1 = w(l1, "L1")
        R1 = f.fmax(R1, L1)
        R2 = f.fmin(R2, U1)
        Rg = f.fmin(f.fmax(Rg, L1), U1)
    mk = f.ixor(R1, R2)
    fl = INX if plant == "mark-silenced" else f.sel(INXM, INX, mk)
    bits_ = Rg

    # ---- classify x (late: see above) ------------------------------------
    f.phase = "classify"
    ax = f.iand(x, wi(full ^ fmt.sign_mask, "ABSM"))
    isnan = f.icmplt(INF, ax)
    issnan = f.sel(ZERO, isnan, f.iand(x, wi(1 << (mw - 1), "QBIT")))
    isinf = f.cmpeq(ax, INF)
    iszero = f.icmplt(ax, wi(1, "INT1"))
    tiny = ZERO if plant == "tiny-gate-off" else         f.icmplt(ax, w(pow2_bits(fmt, gate)))
    if R is not None:
        f.phase = "range"
        out = f.icmplt(ax, w(pow2_bits(fmt, R), "RANGE")) # |x| < 2^R
        fl = f.sel(fl, INXM, out)
    f.probes.update(mk=mk)

    # ---- the tiny paths and the specials, lowest priority first ----------
    f.phase = "special"
    if fn == "cos":
        tb = w(enc(fmt, 1 - Fraction(1, 2 ** (p + 3)), rnd), "COSTINY")
        tfl = INX
    else:
        eps = Fraction(1, 2 ** (p + 2))
        tb = f.fma(x, f.wv(-eps if fn == "sin" else eps), x, rnd)
        if fn == "sin":
            atb = f.iand(tb, wi(full ^ fmt.sign_mask, "ABSM"))
            un = f.icmplt(atb, w(sf.min_normal_bits(fmt), "MINN"))
        else:
            un = f.icmplt(ax, w(sf.min_normal_bits(fmt), "MINN"))
        tfl = f.sel(UNFINX, INX, un)
    bits_ = f.sel(tb, bits_, tiny)
    fl = f.sel(tfl, fl, tiny)
    if fn == "cos":
        bits_ = f.sel(ONE, bits_, iszero)
    else:
        bits_ = f.sel(x, bits_, iszero)
    fl = f.sel(ZERO, fl, iszero)
    bits_ = f.sel(QNAN, bits_, isinf)
    fl = f.sel(INVALID, fl, isinf)
    bits_ = f.sel(QNAN, bits_, isnan)
    fl = f.sel(f.sel(INVALID, ZERO, issnan), fl, isnan)
    f.result, f.flags = bits_, fl
    return f.prune()
