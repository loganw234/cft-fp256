# M1 model: log, log2 and log1p as tile routines (scratch, phase 1).
#
#   x = 2^E m, m in [1, 2) (a subnormal x scaled by 2^p first)
#   C = round(16 RECIP_SEED(m)) in [8, 16]; C = 8 wraps to m/2, C = 16
#   c = C/16 (five bits at most), r = m' c - 1 EXACT (one FMA), |r| < 2^-3.9
#   log x = k ln2 + log(16/C) + log1p(r),  k = E (+1 where wrapped)
#   log(16/C) by a SELECT tree over C mod 8 (two bank words an entry)
#   log1p(r) = r Y(r), Y = sum (-1)^i r^i/(i+1): a single-word tail, K
#   double-word head steps, as the exp family's
#   log2 x = k + (log(16/C) + log1p(r)) / ln2 (a double-word product)
#   log1p x: u = 1 + x by TwoSum; the core on u_h, the low word folded in
#   as r_l = u_l 2^-k c, corrected by r_l / (1 + r) (three Newton steps);
#   |x| < 15/256 skips the reduction (r = x, k = 0, C = 16). 15/256 =
#   2^-4.093 is under RHO, so one (rho, K, D) serves every path of the
#   family. (The first threshold, 2^-4, was past RHO: at fp256 the
#   truncation reached 2^0.93 of the bound there - verifier-VM1's (b)-1.)

import math
from fractions import Fraction

import mpmath

from m1core import (Frag, enc, enc_exact, dec, pow2_bits, RNE, RTZ, RDN,
                    RUP, RMM, sf)
from m1const import words_of, truncated, mpf_to_frac

LN2 = mpmath.log(2)
RHO = 0.0592    # |r| < 0.0590820 = 2^-4.081 over all 512 seed cells (rmax.py, computed exactly)
SMALL = Fraction(15, 256)   # log1p's r = x path: |x| < SMALL <= RHO (one rho for every path)


def log_plan(fmt, G=46, rho=RHO):
    """K and D, minimal, with the bound's estimated total (section 3.2:
    the tail 2u rho^K/(K+1), the truncation rho^(D+1)/((D+2)(1-rho)) and
    the double-word roundings, 12u^2) two bits under 2^-(p+G)."""
    p = fmt.prec
    u = 2.0 ** -p
    target = 2.0 ** -(p + G + 2)
    floor = 12 * u * u
    if floor >= target:
        raise ValueError(f"G = {G} is past the double word's floor at "
                         f"{fmt.name}: 12u^2 = 2^{math.log2(floor):.1f}")
    K = 1
    while 2 * u * rho ** K / (K + 1) + floor > target / 2 + floor and K < 60:
        K += 1
    D = K
    while (2 * u * rho ** K / (K + 1) + rho ** (D + 1) / ((D + 2) * (1 - rho))
           + floor) > target and D < 200:
        D += 1
    return K, D


def build_log(fmt, rnd, fn, G=46, K=None, D=None, brel=None, small=SMALL):
    assert fn in ("log", "log2", "log1p")
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    full = (1 << W) - 1
    Kp, Dp = log_plan(fmt, G)
    K = Kp if K is None else K
    D = Dp if D is None else D
    f = Frag(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}")
    f.meta = {"G": G, "K": K, "D": D}
    x = ("in", "a")
    w = f.w

    def ib(v):
        return w(v & full)
    ZERO, ONE, INT1 = w(0, "ZERO"), w(sf.one_bits(fmt), "ONE"), ib(1)
    NEGONE = w(sf.one_bits(fmt, 1), "NEGONE")
    ABSM, INF = ib(full ^ fmt.sign_mask), w(sf.inf_bits(fmt), "INF")
    NINF = w(sf.inf_bits(fmt, 1), "NINF")
    QBIT, QNAN = ib(1 << (mw - 1)), w(sf.qnan_bits(fmt), "QNAN")
    INX = ib(sf.FLAG_INEXACT)
    INXUNF = ib(sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW)
    INVALID = ib(sf.FLAG_INVALID)
    DIVZ = ib(sf.FLAG_DIVZERO)
    MARK = ib(0x80)
    MAGIC_B = enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    MAGIC = w(MAGIC_B, "MAGIC")
    MANW = ib(mw)

    # ---- classify ---------------------------------------------------
    f.phase = "classify"
    ax = f.iand(x, ABSM)
    isnan = f.icmplt(INF, ax)
    qb = f.iand(x, QBIT)
    issnan = f.sel(ZERO, isnan, qb)
    isinf = f.cmpeq(ax, INF)
    iszero = f.icmplt(ax, INT1)
    neg = f.ishr(x, ib(W - 1))

    # ---- the argument the core reduces ----------------------------------
    f.phase = "reduce"
    KOFF = MAGIC_B - fmt.bias
    if fn == "log1p":
        uh = f.add(ONE, x)                           # TwoSum(1, x)
        a1 = f.sub(uh, x)
        b1 = f.sub(uh, a1)
        ul = f.add(f.sub(ONE, a1), f.sub(x, b1))
        xn, eoff = uh, ib(KOFF)
    else:
        issub = f.icmplt(ax, w(sf.min_normal_bits(fmt), "MINN"))
        xn = f.sel(f.mul(x, w(pow2_bits(fmt, p), "P2P")), x, issub)
        eoff = f.sel(ib(KOFF - p), ib(KOFF), issub)
    m = f.ior(f.iand(xn, ib(fmt.man_mask)), ONE)
    Eb = f.ishr(xn, MANW)
    seed = f.recip_seed(m)
    tc = f.fma(seed, w(enc_exact(fmt, 16), "K16"), MAGIC)
    wrap = f.icmplt(tc, ib(MAGIC_B + 9))             # C <= 8
    mp = f.sel(f.mul(m, w(enc_exact(fmt, Fraction(1, 2)), "HALF")), m, wrap)
    c = f.sel(ONE, f.fma(tc, w(enc_exact(fmt, Fraction(1, 16)), "K1_16"),
                          w(enc_exact(fmt, -Fraction(3 * 2 ** (p - 2), 16)), "NM16")),
              wrap)
    r = f.fma(mp, c, NEGONE)                          # exact
    kb = f.iadd(f.iadd(Eb, eoff), f.sel(INT1, ZERO, wrap))
    kf = f.sub(kb, MAGIC)                             # k, exact
    f.probes.update(m=m, tc=tc, c=c, r=r, kf=kf)

    # ---- the table log(16/C) ---------------------------------------------
    f.phase = "lookup"
    bitsel = [f.iand(tc, ib(1 << i)) for i in range(3)]
    LH, LL = [], []
    for j in range(8):
        Cj = 16 if j == 0 else 8 + j
        hw = words_of(fmt, mpmath.log(mpmath.mpf(16) / Cj), 2)
        LH.append(w(hw[0]))
        LL.append(w(hw[1]))

    def tree(vals):
        level = list(vals)
        for b in bitsel:
            level = [f.sel(level[2 * mm + 1], level[2 * mm], b)
                     for mm in range(len(level) // 2)]
        return level[0]
    Lh, Ll = tree(LH), tree(LL)

    if fn == "log1p":
        f.phase = "log1p-low"
        # r_l = u_l 2^-k c, and r_l/(1 + r) by y ~ 1/(1+r)
        p2mk = f.ishl(f.isub(ib(fmt.bias + MAGIC_B), kb), MANW)
        # for k > p + G + 2 the low word moves log1p by less than the
        # bound (u_l <= ulp(u_h)/2): 2^-k is taken as 0, as expm1 does
        p2mk = f.sel(ZERO, p2mk, f.icmplt(ib(MAGIC_B + p + G + 2), kb))
        rl = f.mul(f.mul(ul, p2mk), c)
        nr0 = f.neg(r)
        y = f.sub(ONE, r)
        for _ in range(3):
            e = f.fma(nr0, y, f.sub(ONE, y))          # 1 - (1 + r) y
            y = f.fma(y, e, y)
        corr = f.mul(rl, y)
        f.probes.update(uh=uh, ul=ul, rl=rl, yinv=y, corr=corr)
        sm = f.icmplt(ax, w(enc_exact(fmt, small), "SMALL"))
        r = f.sel(x, r, sm)
        kf = f.sel(ZERO, kf, sm)
        Lh = f.sel(ZERO, Lh, sm)
        Ll = f.sel(ZERO, Ll, sm)
        corr = f.sel(ZERO, corr, sm)

    # ---- Y(r) = log1p(r)/r ----------------------------------------------
    nr = f.neg(r)
    coef = [Fraction((-1) ** i, i + 1) for i in range(D + 1)]
    f.phase = "tail"
    y = w(enc(fmt, coef[D]))
    for i in range(D - 1, K - 1, -1):
        y = f.fma(y, r, w(enc(fmt, coef[i])))
    f.phase = "head"
    yh, yl = y, None
    for i in range(K - 1, -1, -1):
        ch, cl = words_of(fmt, coef[i], 2)
        CH = w(ch)
        pp = f.mul(yh, r)
        ne = f.fma(yh, nr, pp)
        nl = f.fma(yl, nr, ne) if yl is not None else ne
        s = f.add(CH, pp)
        z = f.sub(s, CH)
        e = f.sub(pp, z)
        tt = f.sub(e, nl)
        yl = f.add(tt, w(cl)) if cl else tt
        yh = s
    f.phase = "lp"
    lph = f.mul(yh, r)
    nlpe = f.fma(yh, nr, lph)
    nlpl = f.fma(yl, nr, nlpe)                         # lp = lph - nlpl
    if fn == "log1p":
        nlpl = f.sub(nlpl, corr)
    f.probes.update(lph=lph, nlpl=nlpl)

    # ---- the sum -----------------------------------------------------------
    f.phase = "sum"
    if fn == "log2":
        F = f.add(Lh, lph)                             # Fast2Sum(Lh, lph)
        fe = f.sub(lph, f.sub(F, Lh))
        Fl = f.sub(f.add(fe, Ll), nlpl)
        i2 = words_of(fmt, 1 / LN2, 2)
        gh = f.mul(F, w(i2[0], "IL2H"))
        nge = f.fma(F, w(sf.negate(fmt, i2[0]), "NIL2H"), gh)
        ngl = f.fma(F, w(sf.negate(fmt, i2[1]), "NIL2L"), nge)
        ngl = f.fma(Fl, w(sf.negate(fmt, i2[0]), "NIL2H"), ngl)   # G = gh - ngl
        S = f.add(kf, gh)                              # Fast2Sum(k, gh)
        e = f.sub(gh, f.sub(S, kf))
        lo = f.sub(e, ngl)
    else:
        # ln2 in three words, the first two of p - nk bits so that k ln2h
        # and k ln2m are exact: k ln2 to about 3p - 2nk bits, which the
        # bound needs at every k (two words gave 2p - nk: measured)
        kmax = max(fmt.emax + 1, -(fmt.emin - p)) + 2
        nk = kmax.bit_length()
        l2 = truncated(fmt, LN2, p - nk)
        l2m = truncated(fmt, mpf_to_frac(LN2) - dec(fmt, l2), p - nk)
        l2l = enc(fmt, mpf_to_frac(LN2) - dec(fmt, l2) - dec(fmt, l2m))
        f.meta.update(nk=nk)
        kl = f.mul(kf, w(l2, "LN2H"))                  # exact
        km = f.mul(kf, w(l2m, "LN2M"))                 # exact
        A = f.add(kl, Lh)                              # Fast2Sum(kl, Lh)
        a = f.sub(Lh, f.sub(A, kl))
        S0 = f.add(A, lph)                             # TwoSum(A, lph)
        a1 = f.sub(S0, lph)
        b1 = f.sub(S0, a1)
        s = f.add(f.sub(A, a1), f.sub(lph, b1))
        S = f.add(S0, km)                              # Fast2Sum(S0, km)
        sm = f.sub(km, f.sub(S, S0))
        t1 = f.add(f.add(s, a), sm)
        t2 = f.fma(kf, w(l2l, "LN2L"), t1)
        t3 = f.add(t2, Ll)
        lo = f.sub(t3, nlpl)
    Vh = f.add(S, lo)                                  # Fast2Sum(S, lo)
    Vl = f.sub(lo, f.sub(Vh, S))
    f.probes.update(Vh=Vh, Vl=Vl)

    # ---- the final rounding and the in-lane test -------------------------
    f.phase = "final"
    R = f.add(Vh, Vl, rnd)
    BV = w(pow2_bits(fmt, -(p + G)) if brel is None else brel, "BREL")
    Bv = f.mul(f.fabs(Vh), BV)
    R1 = f.add(Vh, f.sub(Vl, Bv, RDN), rnd)
    R2 = f.add(Vh, f.add(Vl, Bv, RUP), rnd)
    mk = f.ixor(R1, R2)
    fl = f.ior(INX, f.sel(MARK, ZERO, mk))
    f.probes.update(R=R, R1=R1, R2=R2, Bv=Bv, mk=mk)

    # ---- exact cases and specials, lowest priority first ----------------
    f.phase = "special"
    bits = R
    if fn == "log":
        fl = f.sel(ZERO, fl, f.cmpeq(x, ONE))          # log(1) = +0
    elif fn == "log2":
        fl = f.sel(ZERO, fl, f.cmpeq(r, ZERO))         # x a power of two
    if fn == "log1p":
        tb = f.fma(f.neg(x), x, x, rnd)                # x - x^2
        ut = f.icmplt(ax, w(sf.min_normal_bits(fmt), "MINN"))
        if rnd in (RTZ, RDN):
            ut = f.sel(ONE, ut, f.cmpeq(x, w(sf.min_normal_bits(fmt), "MINN")))
        tinyl = f.icmplt(ax, w(pow2_bits(fmt, -(p + 2)), "TINYL"))
        bits = f.sel(tb, bits, tinyl)
        fl = f.sel(f.sel(INXUNF, INX, ut), fl, tinyl)
        bits = f.sel(INF, bits, isinf)
        fl = f.sel(ZERO, fl, isinf)
        lt = f.cmplt(x, NEGONE)
        bits = f.sel(QNAN, bits, lt)
        fl = f.sel(INVALID, fl, lt)
        m1 = f.cmpeq(x, NEGONE)
        bits = f.sel(NINF, bits, m1)
        fl = f.sel(DIVZ, fl, m1)
        bits = f.sel(x, bits, iszero)
        fl = f.sel(ZERO, fl, iszero)
    else:
        bits = f.sel(INF, bits, isinf)
        fl = f.sel(ZERO, fl, isinf)
        negnz = f.sel(ZERO, neg, iszero)
        bits = f.sel(QNAN, bits, negnz)
        fl = f.sel(INVALID, fl, negnz)
        bits = f.sel(NINF, bits, iszero)
        fl = f.sel(DIVZ, fl, iszero)
    bits = f.sel(QNAN, bits, isnan)
    fl = f.sel(f.sel(INVALID, ZERO, issnan), fl, isnan)
    f.result, f.flags = bits, fl
    return f.prune()
