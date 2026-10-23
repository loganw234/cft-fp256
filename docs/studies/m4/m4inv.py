# M4 model: atan, atan2, asin and acos as tile routines, in double words
# (fp64, fp128, fp256 at Logan's G; fp32's double word at G = 18, the
# fallback M2 measured) (scratch; the study's sections 2 to 4).
#
# ONE CORE, four front ends. Every function is atan2 in transcend.py's
# definition, so every function here is
#
#     result = sign * (C + sigma * theta0),  theta0 = atan(n/d), 0 <= n <= d,
#
# with C one of 0, pi/2, pi and sigma = +-1 chosen by the quadrant:
#
#   front     atan: n, d = min, max of |x| and 1
#             asin, acos: w = sqrt((1 - |x|)(1 + |x|)), the product form,
#             1 - |x| exact (Sterbenz) and 1 + |x| an exact double word;
#             n, d = min, max of |x| and w (double words)
#             atan2: n, d = min, max of |y| and |x|, both scaled by 2^3p
#             where d < 2^(emin + 3p) and by 2^-2 where d >= 2^(emax-1)
#             (so that RECIP_SEED never sees a subnormal and d + c n never
#             overflows); the quotient is unchanged
#   index     t~ = n_h RECIP_SEED(d_h), 8.5 bits; k = round(N (63/64) t~),
#             at most N - 1, by the magic-number FMA and one MIN; c = k/N,
#             exact. The bias 63/64 keeps n_h / (c d_h) in [1/2, 2] for
#             every k >= 1, so that n_h - c d_h is exact (Sterbenz)
#   num, den  ONE double-word quotient s = (n - c d)/(d + c n), which is
#             tan(theta0 - atan c): c d and c n by TwoProd, n_h - P exact
#   quotient  M2's tan quotient (its 2.5): RECIP_SEED, Newton to p + 8
#             bits, the exact remainder by FMA with the low words
#   z, poly   z = s^2 as a double word (s_l's share included); atan(s)/s =
#             sum (-1)^i z^i/(2i+1), Taylor: a single-word tail from D down
#             to K, then K double-word steps (M2's step)
#   table     atan(k/N) in two words, a SELECT tree over k's bits (bank
#             words only); atan(0) = 0
#   recon     theta0 = atan(c) + s P(z); V = C + sigma theta0, then the
#             sign, applied to the double word before its one rounding
#   final     R = rnd(V_h + V_l) and M1's in-lane test, Bv = 2^-(p+G)|V_h|
#   specials  the tiny gates (atan's toward zero, asin's away), the zeros,
#             |x| > 1, NaN; atan2's 9.2.1 table rides the core: theta0 is
#             forced to 0 (an infinite or zero operand) or pi/4 (both
#             infinite) and C, sigma do the rest; atan2's exact-quotient
#             rule in-lane (x > 0, k = 0, the remainder zero, below the
#             gate: one FMA under the attribute, toward zero), and its
#             tiny-quotient range marked (x > 0, |y/x| < 2^(emin+p+2))
#
# asin and acos of one argument share everything up to C and sigma; so do
# the four functions' core instructions, instruction for instruction.

import math
from fractions import Fraction

from m4core import (Frag2, sf, enc, pow2_bits, words_of, RNE, RTZ, RDN,
                    RUP, RMM, pi_frac, atan_frac, atan_coef)

GUARD = {"fp32": 18, "fp64": 44, "fp128": 46, "fp256": 46}
NTAB = 8
SEL_BIAS = Fraction(63, 64)
# t~ = n_h RECIP_SEED(d_h): the seed's relative error is below 2^-8.5 =
# 0.00276 (softfloat.recip_seed), and the product's rounding adds 2^-p
EPS_T = Fraction(28, 10000)
FNS = ("atan", "asin", "acos", "atan2")


def gates(fmt):
    """The definition's tiny gates as |x| < 2^g: atan (and atan2's exact
    quotient) 2e + p + 3 <= 0, asin 2e + p + 2 <= 0, e = floor(log2|x|)."""
    p = fmt.prec
    return math.floor(-(p + 3) / 2) + 1, math.floor(-(p + 2) / 2) + 1


def cells(N, eps=EPS_T):
    """The interval of t = n/d each k can be chosen for, exact rationals:
    k = round(N (63/64) t~) with |t~/t - 1| <= eps, k <= N - 1."""
    M = N * SEL_BIAS
    out = []
    for k in range(N):
        lo = Fraction(0) if k == 0 else (k - Fraction(1, 2)) / (M * (1 + eps))
        hi = (Fraction(1) + Fraction(1, 2 ** 20) if k == N - 1
              else (k + Fraction(1, 2)) / (M * (1 - eps)))
        out.append((lo, hi))
    return out


def rho_of(N):
    """The largest |s| = |t - c|/(1 + t c) over every cell (s is monotone
    in t, so at a cell's ends); and the Sterbenz margins: the least
    t/c and the largest over k >= 1, which must lie inside [1/2, 2]."""
    r = Fraction(0)
    lo_ratio, hi_ratio = Fraction(10), Fraction(0)
    for k, (lo, hi) in enumerate(cells(N)):
        c = Fraction(k, N)
        for t in (lo, hi):
            r = max(r, abs(t - c) / (1 + t * c))
        if k:
            # the top cell's t is n/d, a hair past 1 only through the low
            # words; n_h <= d_h by the selection, so n_h/P <= 1/c there
            top = Fraction(1) if k == N - 1 else hi
            lo_ratio = min(lo_ratio, lo / c)
            hi_ratio = max(hi_ratio, top / c)
    assert lo_ratio > Fraction(1, 2) and hi_ratio <= 2, (lo_ratio, hi_ratio)
    return r, lo_ratio, hi_ratio


def plan_poly(fmt, G, rho):
    """(K, D): the double-word head covers every i whose term
    |c_i| rho^(2i) exceeds 2^-(G+3); the truncation |c_(D+1)| rho^(2D+2)
    (an alternating series) is under 2^-(p+G+3)."""
    p = fmt.prec
    z = rho * rho
    K = 0
    while abs(atan_coef(K)) * z ** K > Fraction(1, 2 ** (G + 3)):
        K += 1
    D = K
    while abs(atan_coef(D + 1)) * z ** (D + 1) > Fraction(1, 2 ** (p + G + 3)):
        D += 1
    return K, D


PLANTS = ("table-entry", "coef", "newton-short", "sterbenz-bias",
          "zl-dropped", "sl-dropped", "pio2-low", "bound-loose",
          "mark-silenced", "tiny-gate-off", "tiny-side", "domain-edge",
          "signed-zero", "side-rule-off", "side-rule-sign", "range-off",
          "u-low-dropped", "sqrt-product", "quadrant", "prescale-d")


def build(fmt, rnd, fn, G=None, N=NTAB, bound_shift=0, plant=None,
          u_form="product"):
    """One routine, instrumented (pruned; the unpruned body kept as
    all_body). `u_form`, asin's and acos's 1 - x^2: "product", (1 - |x|)
    (1 + |x|) as transcend.py forms it, or "direct", 1 - RN(x^2) by
    Fast2Sum plus x^2's exact TwoProd error, exact as a sum but left
    unnormalised near |x| = 1, which breaks the bound (the study's 2.4 and
    3.6: it was judged no fault by argument, and uform.py measured it a
    fault; it is the plant sqrt-product), or "renorm", the direct form
    normalised by one more Fast2Sum (measured beside them, not proposed).
    `plant`, one of PLANTS, builds one named fault (plants.py):
      table-entry     atan(c_3)'s high word one ulp off
      coef            the z^1 coefficient without its low word
      newton-short    the quotient's reciprocal one Newton step short
      sterbenz-bias   k chosen without the 63/64 bias (n_h - c d_h then
                      not always exact)
      zl-dropped      z's low word (s_l's share) left out of the head
      sl-dropped      s's low word left out of atan(s) = s P
      pio2-low        pi/2's low word dropped
      bound-loose     the in-lane bound 2^40 too small
      mark-silenced   the flag word never carries the mark
      tiny-gate-off   no tiny path (atan, asin)
      tiny-side       the tiny path on the wrong side (atan away, asin
                      toward zero)
      domain-edge     asin, acos: |x| > 1 tested as |x| >= 1 (+-1 refused)
      signed-zero     atan2(+-0, -0) answered +-0, not +-pi
      side-rule-off   atan2's exact-quotient rule not applied in-lane
      side-rule-sign  the rule's FMA rounded away from zero
      range-off       atan2's tiny-quotient range not marked
      u-low-dropped   asin, acos: u = 1 - x^2's low word left out of the
                      root's residual
      sqrt-product    asin, acos: 1 - x^2 formed directly (u_form
                      "direct"): passes the pools, breaks the bound
      quadrant        atan2: sigma from the swap alone (x's sign ignored)
      prescale-d      atan2: the 2^3p prescale keyed on d, as first
                      designed (send-back 1: a tiny n under a large d keeps
                      an inexact remainder; the corner region sees it)"""
    assert fn in FNS, fn
    assert plant is None or plant in PLANTS, plant
    if plant == "sqrt-product":
        # 1 - x^2 in the direct form: exact, but its double word
        # unnormalised near |x| = 1, which the root's one residual step
        # cannot absorb (uform.py: past the bound by 2^24 to 2^38 at fp64)
        u_form = "direct"
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    G = GUARD[fmt.name] if G is None else G
    inputs = ("a", "b") if fn == "atan2" else ("a",)
    f = Frag2(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}", inputs)
    rho, _lr, _hr = rho_of(N)
    K, D = plan_poly(fmt, G, rho)
    f.meta.update(G=G, N=N, K=K, D=D, rho=float(rho), data=set())
    w, wi, wv = f.w, f.wi, f.wv
    full = (1 << W) - 1
    ZERO, ONE = w(0, "ZERO"), w(sf.one_bits(fmt), "ONE")
    SIGN = wi(fmt.sign_mask, "SIGN")
    ABSM = wi(full ^ fmt.sign_mask, "ABSM")
    INT1 = wi(1, "INT1")
    INF, QNAN = w(sf.inf_bits(fmt), "INF"), w(sf.qnan_bits(fmt), "QNAN")
    QBIT = wi(1 << (mw - 1), "QBIT")
    INX = wi(sf.FLAG_INEXACT, "INX")
    INXM = wi(sf.FLAG_INEXACT | 0x80, "INXM")
    UNFINX = wi(sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT, "UNFINX")
    INVALID = wi(sf.FLAG_INVALID, "INVALID")
    MINN = w(sf.min_normal_bits(fmt), "MINN")
    MAGIC = f.wx(Fraction(3, 2) * 2 ** (p - 1), "MAGIC")
    pio2 = pi_frac() / 2
    PIO2h, PIO2l = (w(b) for b in words_of(fmt, pio2, 2))
    if plant == "pio2-low":
        PIO2l = ZERO
    PIh, PIl = (w(b) for b in words_of(fmt, pi_frac(), 2))
    PIO4h, PIO4l = (w(b) for b in words_of(fmt, pi_frac() / 4, 2))
    ga, gs = gates(fmt)
    nl_ = dl_ = None

    # ---- the front ends: n <= d, the quadrant's conditions ---------------
    f.phase = "front"
    if fn == "atan2":
        y, x = ("in", "a"), ("in", "b")
        ay, ax = f.iand(y, ABSM), f.iand(x, ABSM)
        swap = f.icmplt(ax, ay)                          # |y| > |x|
        n0, d0 = f.sel(ax, ay, swap), f.sel(ay, ax, swap)
        # the prescale by 2^3p, keyed on n (send-back 1): the quotient's
        # FMA remainder N_h - s_h D_h is about 2^-p n, so it is exact only
        # while n >= 2^(emin+p+1); n < 2^(emin+3p) scales both, unless d
        # would pass 2^(emax-2), where t is far inside the marked range
        if plant == "prescale-d":
            dsub = f.icmplt(d0, w(pow2_bits(fmt, fmt.emin + 3 * p), "DSUB"))
        else:
            nsub = f.icmplt(n0, w(pow2_bits(fmt, fmt.emin + 3 * p), "DSUB"))
            dok = f.icmplt(d0, wi(pow2_bits(fmt, fmt.emax - 3 * p - 2), "DOK"))
            dsub = f.sel(dok, ZERO, nsub)
        S3P = w(pow2_bits(fmt, 3 * p), "S3P")
        n1, d1 = f.sel(f.mul(n0, S3P), n0, dsub), f.sel(f.mul(d0, S3P), d0, dsub)
        dbig = f.icmplt(wi(pow2_bits(fmt, fmt.emax - 1) - 1, "DBIG"), d0)
        QTR = w(pow2_bits(fmt, -2), "QTR")
        nh_, dh_ = f.sel(f.mul(n1, QTR), n1, dbig), f.sel(f.mul(d1, QTR), d1, dbig)
        xneg = f.icmplt(ABSM, x)                         # x's sign bit set
        sx = f.iand(y, SIGN)                             # the result's sign
    elif fn == "atan":
        x = ("in", "a")
        ax = f.iand(x, ABSM)
        swap = f.icmplt(ONE, ax)                         # |x| > 1
        nh_, dh_ = f.sel(ONE, ax, swap), f.sel(ax, ONE, swap)
        sx = f.iand(x, SIGN)
        xneg = None
    else:
        x = ("in", "a")
        ax = f.iand(x, ABSM)
        nax = f.ixor(ax, SIGN)
        f.phase = "sqrt"
        if u_form in ("direct", "renorm"):
            # 1 - x^2 formed directly: x^2 by TwoProd, then 1 - it
            xx = f.mul(ax, ax)
            nxe = f.fma(nax, ax, xx)                     # xx - x^2
            uh, ue = f.fast_two_sum(ONE, f.ixor(xx, SIGN))
            ul = f.add(ue, nxe)
            if u_form == "renorm":
                # normalised: |ul| <= ulp(uh)/2 (uh >= 2^-p > |ul| for
                # |x| < 1, both zero at |x| = 1)
                uh, ul = f.fast_two_sum(uh, ul)
        else:
            # u = (1 - |x|)(1 + |x|): both factors exact double words
            a1, a1l = f.fast_two_sum(ONE, nax)           # 1 >= |x|
            b1, b1l = f.fast_two_sum(ONE, ax)
            uh = f.mul(a1, b1)
            na1 = f.ixor(a1, SIGN)
            nul = f.fma(na1, b1, uh)                     # uh - a1 b1
            nul = f.fma(na1, b1l, nul)                   # - a1 b1l
            ul = f.fma(a1l, b1, f.ixor(nul, SIGN))       # + a1l b1
        # w = sqrt(u): RSQRT_SEED, Newton, the exact residual by FMA
        uc = f.fmax(uh, w(pow2_bits(fmt, fmt.emin + 2 * p), "TINYU"))
        yq = f.ins(sf.OP_RSQRT_SEED, (uc,))
        nuc = f.ixor(uc, SIGN)
        HALF = w(pow2_bits(fmt, -1), "HALF")
        bits = 8
        while bits < p + 8:
            h = f.mul(nuc, yq)                           # -u y
            e = f.fma(h, yq, ONE)                        # 1 - u y^2
            yq = f.fma(f.mul(yq, HALF), e, yq)
            bits *= 2
        wh = f.mul(uh, yq)
        res = f.fma(f.ixor(wh, SIGN), wh, uh)            # uh - wh^2, exact
        if plant != "u-low-dropped":
            res = f.add(res, ul)
        wl = f.mul(res, f.mul(yq, HALF))
        wh, wl = f.fast_two_sum(wh, wl)
        f.probes.update(uh=uh, ul=ul, wh=wh, wl=wl)
        f.phase = "front"
        swap = f.icmplt(wh, ax)                          # |x| > w
        nh_, nl_ = f.sel(wh, ax, swap), f.sel(wl, ZERO, swap)
        dh_, dl_ = f.sel(ax, wh, swap), f.sel(ZERO, wl, swap)
        sx = f.iand(x, SIGN)
        xneg = f.icmplt(ABSM, x) if fn == "acos" else None

    # ---- the index: k = round(N (63/64) t~), c = k/N ----------------------
    f.phase = "index"
    yd = f.recip_seed(dh_)
    tt = f.mul(nh_, yd)
    msel = Fraction(N) if plant == "sterbenz-bias" else N * SEL_BIAS
    Kk = f.fma(tt, f.wx(msel, "MSEL"), MAGIC)
    f.meta["data"].add(("index", Kk[1]))
    Kk = f.fmin(Kk, f.wx(Fraction(3, 2) * 2 ** (p - 1) + N - 1, "MAGICN1"))
    kf = f.sub(Kk, MAGIC)
    c = f.mul(kf, f.wx(Fraction(1, N), "INVN"))
    nc = f.ixor(c, SIGN)

    # ---- s = (n - c d)/(d + c n) as a double word --------------------------
    f.phase = "num"
    P = f.mul(c, dh_)
    nE = f.fma(nc, dh_, P)                               # P - c d_h
    Nh0 = f.sub(nh_, P)                                  # exact (Sterbenz)
    lo = nE
    if nl_ is not None:
        lo = f.add(lo, nl_)
        lo = f.fma(nc, dl_, lo)
        Nh, Nl = f.two_sum(Nh0, lo)
    else:
        Nh, Nl = f.fast_two_sum(Nh0, lo)                 # |Nh0| >= |nE|
    f.phase = "den"
    Q = f.mul(c, nh_)
    nF = f.fma(nc, nh_, Q)                               # Q - c n_h
    Dh, De = f.fast_two_sum(dh_, Q)                      # d_h >= Q
    Dl = f.sub(De, nF)
    if dl_ is not None:
        Dl = f.add(Dl, dl_)
        Dl = f.fma(c, nl_, Dl)
    f.phase = "quotient"
    yr = f.recip_seed(Dh)
    nDh = f.ixor(Dh, SIGN)
    bits = 16 if plant == "newton-short" else 8
    while bits < p + 8:
        e = f.fma(nDh, yr, ONE)                          # 1 - D y
        yr = f.fma(yr, e, yr)
        bits *= 2
    sh0 = f.mul(Nh, yr)
    nsh0 = f.ixor(sh0, SIGN)
    rem0 = f.fma(nsh0, Dh, Nh)                           # exact
    rem = f.add(rem0, Nl)
    rem = f.fma(nsh0, Dl, rem)
    sl = f.mul(rem, yr)
    sh, sl = f.fast_two_sum(sh0, sl)
    f.probes.update(tt=tt, Kk=Kk, c=c, Nh=Nh, Nl=Nl, Dh=Dh, Dl=Dl, sh=sh,
                    sl=sl, rem0=rem0, nh=nh_, P=P, Nh0=Nh0)

    # ---- z = s^2 and atan(s)/s ------------------------------------------
    f.phase = "z"
    nsh = f.ixor(sh, SIGN)
    zh = f.mul(sh, sh)
    nzl = f.fma(nsh, sh, zh)                             # zh - sh^2
    if plant != "zl-dropped":
        nzl = f.fma(f.add(nsh, nsh), sl, nzl)            # - 2 sh sl
    nzh = f.ixor(zh, SIGN)
    f.phase = "tail"
    yv = wv(atan_coef(D))
    for k in range(D - 1, K - 1, -1):
        yv = f.fma(yv, zh, wv(atan_coef(k)))
    f.phase = "head"
    yh, yl = yv, None
    for k in range(K - 1, -1, -1):
        ch, cl = words_of(fmt, atan_coef(k), 2)
        if plant == "coef" and k == 1:
            cl = 0
        CH = w(ch)
        pp = f.mul(yh, zh)
        ne = f.fma(yh, nzh, pp)                          # pp - yh zh
        nl = f.fma(yl, nzh, ne) if yl is not None else ne
        nl = f.fma(yh, nzl, nl)                          # - yh zl
        s_ = f.add(CH, pp)                               # Fast2Sum(c, pp)
        f.meta["fast_two_sum"] += 1
        zz = f.sub(s_, CH)
        e2 = f.sub(pp, zz)
        tt2 = f.sub(e2, nl)
        yl = f.add(tt2, w(cl)) if cl else tt2
        yh = s_
    Ph, Pl = yh, yl
    f.phase = "atan_s"
    Ah = f.mul(sh, Ph)
    nAl = f.fma(nsh, Ph, Ah)                             # Ah - sh Ph
    nAl = f.fma(nsh, Pl, nAl)                            # - sh Pl
    if plant != "sl-dropped":
        nAl = f.fma(f.ixor(sl, SIGN), Ph, nAl)           # - sl Ph
    Al = f.ixor(nAl, SIGN)

    # ---- the table: atan(k/N) in two words ----------------------------------
    f.phase = "table"
    nb = N.bit_length() - 1
    bitsel = [f.iand(Kk, wi(1 << i)) for i in range(nb)]

    def tree(vals):
        level = list(vals)
        for bit in bitsel:
            level = [f.sel(level[2 * m + 1], level[2 * m], bit)
                     for m in range(len(level) // 2)]
        return level[0]
    tw = [words_of(fmt, atan_frac(Fraction(k, N)), 2) for k in range(N)]
    if plant == "table-entry":
        tw[3] = (tw[3][0] + 1, tw[3][1])
    Th = tree([w(t[0]) for t in tw])
    Tl = tree([w(t[1]) for t in tw])

    # ---- theta0 = atan(c) + atan(s); V = C + sigma theta0 -------------------
    f.phase = "recon"
    th, te = f.fast_two_sum(Th, Ah)                      # |T| >= |A|, or T = 0
    tl = f.add(f.add(te, Tl), Al)
    if fn == "atan":
        isinf = f.cmpeq(ax, INF)
        th, tl = f.sel(ZERO, th, isinf), f.sel(ZERO, tl, isinf)
        Ch, Cl = f.sel(PIO2h, ZERO, swap), f.sel(PIO2l, ZERO, swap)
        sigc = swap
    elif fn == "asin":
        Ch, Cl = f.sel(PIO2h, ZERO, swap), f.sel(PIO2l, ZERO, swap)
        sigc = swap
    elif fn == "acos":
        cpi_h, cpi_l = f.sel(PIh, ZERO, xneg), f.sel(PIl, ZERO, xneg)
        Ch, Cl = f.sel(cpi_h, PIO2h, swap), f.sel(cpi_l, PIO2l, swap)
        sigc = f.ixor(f.sel(ZERO, ONE, swap), xneg)      # (not swap) xor xneg
    else:
        yinf, xinf = f.cmpeq(ay, INF), f.cmpeq(ax, INF)
        yzero, xzero = f.icmplt(ay, INT1), f.icmplt(ax, INT1)
        s0 = f.sel(ONE, f.sel(ONE, f.sel(ONE, xzero, yzero), xinf), yinf)
        both = f.sel(xinf, ZERO, yinf)
        th, tl = f.sel(ZERO, th, s0), f.sel(ZERO, tl, s0)
        th, tl = f.sel(PIO4h, th, both), f.sel(PIO4l, tl, both)
        cpi_h, cpi_l = f.sel(PIh, ZERO, xneg), f.sel(PIl, ZERO, xneg)
        if plant == "signed-zero":
            # +-0 against -0 taken as +0: C from x's sign only when x != 0
            xneg_c = f.sel(ZERO, xneg, xzero)
            cpi_h, cpi_l = f.sel(PIh, ZERO, xneg_c), f.sel(PIl, ZERO, xneg_c)
        Ch, Cl = f.sel(PIO2h, cpi_h, swap), f.sel(PIO2l, cpi_l, swap)
        sigc = swap if plant == "quadrant" else f.ixor(swap, xneg)
    sg = f.sel(SIGN, ZERO, sigc)
    sth, stl = f.ixor(th, sg), f.ixor(tl, sg)
    Vh, Ve = f.fast_two_sum(Ch, sth)                     # |C| >= |theta0| or C = 0
    Vl = f.add(f.add(Ve, Cl), stl)
    Vh, Vl = f.fast_two_sum(Vh, Vl)
    if fn != "acos":
        Vh, Vl = f.ixor(Vh, sx), f.ixor(Vl, sx)
    f.probes.update(Vh=Vh, Vl=Vl, th=th, tl=tl)

    # ---- the final rounding and the in-lane test ----------------------------
    f.phase = "final"
    Rg = f.add(Vh, Vl, rnd)
    brel = pow2_bits(fmt, -(p + G) + bound_shift
                     - (40 if plant == "bound-loose" else 0))
    Bv = f.mul(f.fabs(Vh), w(brel, "BREL"))
    lo_dn = f.sub(Vl, Bv, RDN)
    lo_up = f.add(Vl, Bv, RUP)
    R1 = f.add(Vh, lo_dn, rnd)
    R2 = f.add(Vh, lo_up, rnd)
    mk = f.ixor(R1, R2)
    fl = INX if plant == "mark-silenced" else f.sel(INXM, INX, mk)
    bits_ = Rg
    f.probes.update(R=Rg, R1=R1, R2=R2, Bv=Bv, mk=mk)

    # ---- the specials, lowest priority first --------------------------------
    f.phase = "special"
    if fn == "atan2":
        # the exact-quotient rule: x > 0, |y| < |x|, k = 0, the remainder
        # zero (y/x = s_h exactly), and s_h below atan's gate: atan(y/x) is
        # a hair below y/x, decided by side (one FMA, toward zero)
        c0 = f.sel(ZERO, f.sel(ZERO, ONE, xneg), swap)
        kz = f.cmpeq(Kk, MAGIC)
        ex = f.cmpeq(rem0, ZERO)
        small = f.icmplt(sh0, w(pow2_bits(fmt, ga), "GATEA"))
        side = f.sel(f.sel(f.sel(small, ZERO, ex), ZERO, kz), ZERO, c0)
        ss = f.ixor(sh0, sx)
        eps = Fraction(1, 2 ** (p + 2))
        tb = f.fma(ss, f.wv(eps if plant == "side-rule-sign" else -eps), ss,
                   rnd)
        if plant != "side-rule-off":
            bits_ = f.sel(tb, bits_, side)
            fl = f.sel(INX, fl, side)
        # the tiny-quotient range: x > 0, |y| < |x| and t~ below
        # 2^(emin + p + 2), where s's double word would lose its low word
        if plant != "range-off":
            rmk = f.sel(f.icmplt(tt, w(pow2_bits(fmt, fmt.emin + p + 2),
                                       "TQR")), ZERO, c0)
            fl = f.sel(INXM, fl, rmk)
        # 9.2.1's zeros: y = +-0 against x >= +0, and a finite y against
        # x = +inf, are +-0 with no flag
        zres = f.sel(ZERO, f.sel(ONE, f.sel(f.sel(ZERO, ONE, yinf), ZERO,
                                            xinf), yzero), xneg)
        bits_ = f.sel(sx, bits_, zres)
        fl = f.sel(ZERO, fl, zres)
        ynan, xnan = f.icmplt(INF, ay), f.icmplt(INF, ax)
        ysn = f.sel(ZERO, ynan, f.iand(y, QBIT))
        xsn = f.sel(ZERO, xnan, f.iand(x, QBIT))
        anynan = f.sel(ONE, xnan, ynan)
        anysn = f.sel(ONE, xsn, ysn)
        bits_ = f.sel(QNAN, bits_, anynan)
        fl = f.sel(f.sel(INVALID, ZERO, anysn), fl, anynan)
    else:
        f.phase = "classify"
        isnan = f.icmplt(INF, ax)
        issnan = f.sel(ZERO, isnan, f.iand(x, QBIT))
        iszero = f.icmplt(ax, INT1)
        f.phase = "special"
        if fn in ("atan", "asin"):
            g = ga if fn == "atan" else gs
            tiny = ZERO if plant == "tiny-gate-off" else \
                f.icmplt(ax, w(pow2_bits(fmt, g)))
            eps = Fraction(1, 2 ** (p + 2))
            away = (fn == "asin") != (plant == "tiny-side")
            tb = f.fma(x, f.wv(eps if away else -eps), x, rnd)
            if away:
                un = f.icmplt(ax, MINN)                  # |x| below 2^emin
            else:
                un = f.icmplt(f.iand(tb, ABSM), MINN)    # the result below
            tfl = f.sel(UNFINX, INX, un)
            bits_ = f.sel(tb, bits_, tiny)
            fl = f.sel(tfl, fl, tiny)
            bits_ = f.sel(x, bits_, iszero)              # +-0, exact
            fl = f.sel(ZERO, fl, iszero)
        if fn == "acos":
            isone = f.cmpeq(x, ONE)                      # acos(1) = +0, exact
            bits_ = f.sel(ZERO, bits_, isone)
            fl = f.sel(ZERO, fl, isone)
        if fn in ("asin", "acos"):
            edge = (f.icmplt(f.w(sf.one_bits(fmt) - 1, "ONEM"), ax)
                    if plant == "domain-edge" else f.icmplt(ONE, ax))
            bits_ = f.sel(QNAN, bits_, edge)             # |x| > 1: invalid
            fl = f.sel(INVALID, fl, edge)
        bits_ = f.sel(QNAN, bits_, isnan)
        fl = f.sel(f.sel(INVALID, ZERO, issnan), fl, isnan)
    f.result, f.flags = bits_, fl
    return f.prune()
