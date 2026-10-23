# M4 model: fp32 at G = 40, in TRIPLE words (scratch; the study's 2.7).
# Logan's guard for fp32's library (M1's question 2) is 40, and a double
# word at p = 24 floors near 2^-44.7 (M1's 2.5), short of 2^-(24+40); so
# every value that carries the bound here has three words: the quotient s,
# z = s^2, the polynomial's head, atan(s), the table's atan(c), pi/2 and
# pi, and V. The shape is m4inv.py's, part for part:
#
#   front     as m4inv.py; asin, acos: u = (1 - |x|)(1 + |x|) as an exact
#             expansion of the four products of the two exact double words,
#             renormalised to three words; w = sqrt(u) in three words:
#             RSQRT_SEED, Newton, then two corrections from the exact
#             residuals (u0 - w0^2 by FMA; r - 2 w0 w1 with w0 w1 by
#             TwoProd, exact by Sterbenz)
#   index     as m4inv.py (N = 8, the 63/64 bias)
#   num, den  n - c d and d + c n as exact expansions (TwoProd of c with
#             each word), renormalised
#   quotient  s = N/D in three words: q0 = N0 y, the remainder N - q0 D to
#             two words (N0 - q0 D0 exact by FMA, q0 D1 by TwoProd), q1
#             from it, the remainder again, q2; renormalised
#   z, poly   z = s^2 in three words; atan(s)/s by a single-word tail, K2
#             double-word steps (M2's step) and K3 triple-word steps (M1's
#             exp32 step, with z in three words): plan_tw
#   recon     theta0 = T + A and V = C + sigma theta0, three words each
#   final     R = rnd(V0 + RO(V1 + V2)), the test on RO(V1 + V2 -+ Bv)
#             (M1's _round_to_odd_add), Bv = 2^-(p+G)|V0|
#   specials  as m4inv.py
#
# The model is GENERIC: expansions summed by TwoSum chains, negations by
# IXOR, as M1's exp32 model was. A hand-scheduled routine is cheaper; by
# how much is not measured (the study's 2.7).

from fractions import Fraction

from m4core import (Frag2, sf, pow2_bits, words_of, RNE, RTZ, RDN, RUP,
                    pi_frac, atan_frac, atan_coef)
from m4inv import gates, rho_of, SEL_BIAS, NTAB, FNS

GUARD_TW = 40


def plan_tw(fmt, G, rho):
    """(K3, K2, D): y_i, the Horner value from degree i, enters V scaled by
    |c_i| z^i (V >= |atan s|), and a w-word step keeps about 24 w - 2 bits,
    so y_i needs (p + G + 2) + log2(2 |c_i| z^i) bits: K3 is the first i
    whose need fits two words less two bits, K3 + K2 the first that fits one
    word less two; D the first degree whose truncation |c_(D+1)| z^(D+1) is
    under 2^-(p+G+3). M1's plan_exp32, for atan's series."""
    p = fmt.prec
    z = rho * rho

    def within(i, bits):
        return 2 * abs(atan_coef(i)) * z ** i <= Fraction(2) ** (bits - (p + G + 2))
    D = 1
    while abs(atan_coef(D + 1)) * z ** (D + 1) > Fraction(1, 2 ** (p + G + 3)):
        D += 1
    K3 = 0
    while not within(K3, 2 * p - 2):
        K3 += 1
    K23 = K3
    while not within(K23, p - 2):
        K23 += 1
    return K3, K23 - K3, D


PLANTS_TW = ("q2-dropped", "head3-two", "w2-dropped", "z2-dropped",
             "prescale-d", "range-low")
# a variant is measured beside the plants and is not one: head3-short, one
# triple-word head step in two words, the cheaper variant the study
# measured and did not propose (its error stays inside the bound, so it
# cannot turn a check red; send-back 1)
VARIANTS_TW = ("head3-short",)


def build(fmt, rnd, fn, G=None, N=NTAB, bound_shift=0, plant=None):
    assert fn in FNS, fn
    assert plant is None or plant in PLANTS_TW + VARIANTS_TW, plant
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    G = GUARD_TW if G is None else G
    inputs = ("a", "b") if fn == "atan2" else ("a",)
    f = Frag2(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}-tw", inputs)
    rho, _lr, _hr = rho_of(N)
    K3, K2, D = plan_tw(fmt, G, rho)
    if plant in ("head3-short", "head3-two"):
        # one (two) of the planned triple-word head steps in two words; the
        # planner keeps two bits a word, so one step is margin (the study's
        # 8: head3-short is a variant, a measurement of that margin)
        mv = 1 if plant == "head3-short" else 2
        K3, K2 = K3 - mv, K2 + mv
    f.meta.update(G=G, N=N, K3=K3, K2=K2, D=D, rho=float(rho), data=set(),
                  family="triple word")
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
    ga, gs = gates(fmt)

    def neg(a):
        return f.ixor(a, SIGN)

    def tp(a, b):
        """(p, e) with p + e = a b exactly: MUL, and the error by FMA."""
        pr = f.mul(a, b)
        return pr, neg(f.fma(neg(a), b, pr))

    def chain(terms):
        terms = [t for t in terms if t is not None]
        acc, errs = terms[0], []
        for t in terms[1:]:
            acc, e = f.two_sum(acc, t)
            errs.append(e)
        return acc, errs

    def plain(terms):
        terms = [t for t in terms if t is not None]
        if not terms:
            return None
        acc = terms[0]
        for t in terms[1:]:
            acc = f.add(acc, t)
        return acc

    def renorm(a, b, c):
        s0, t = f.fast_two_sum(a, b)
        if c is None:
            return [s0, t, None]
        s1, s2 = f.fast_two_sum(t, c)
        s0, s1 = f.fast_two_sum(s0, s1)
        return [s0, s1, s2]

    def words3(v):
        return [w(b) for b in words_of(fmt, v, 3)]

    # ---- front ends ------------------------------------------------------
    f.phase = "front"
    nv = dv = None
    if fn == "atan2":
        y, x = ("in", "a"), ("in", "b")
        ay, ax = f.iand(y, ABSM), f.iand(x, ABSM)
        swap = f.icmplt(ax, ay)
        n0, d0 = f.sel(ax, ay, swap), f.sel(ay, ax, swap)
        # keyed on n, as m4inv.py (send-back 1): the remainders are about
        # 2^-p n and 2^-2p n, exact only while n >= 2^(emin+2p+1)
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
        nv = [f.sel(f.mul(n1, QTR), n1, dbig), None, None]
        dv = [f.sel(f.mul(d1, QTR), d1, dbig), None, None]
        xneg = f.icmplt(ABSM, x)
        sx = f.iand(y, SIGN)
    elif fn == "atan":
        x = ("in", "a")
        ax = f.iand(x, ABSM)
        swap = f.icmplt(ONE, ax)
        nv, dv = [f.sel(ONE, ax, swap), None, None], [f.sel(ax, ONE, swap), None, None]
        sx = f.iand(x, SIGN)
        xneg = None
    else:
        x = ("in", "a")
        ax = f.iand(x, ABSM)
        nax = neg(ax)
        f.phase = "sqrt"
        a1, a1l = f.fast_two_sum(ONE, nax)
        b1, b1l = f.fast_two_sum(ONE, ax)
        p0, e0 = tp(a1, b1)
        p1, e1 = tp(a1, b1l)
        p2, e2 = tp(a1l, b1)
        q3 = f.mul(a1l, b1l)
        l1, errs = chain([e0, p1, p2])
        l2 = plain(errs + [e1, e2, q3])
        u = renorm(p0, l1, l2)
        uc = f.fmax(u[0], w(pow2_bits(fmt, fmt.emin + 2 * p), "TINYU"))
        yq = f.ins(sf.OP_RSQRT_SEED, (uc,))
        nuc = neg(uc)
        HALF = w(pow2_bits(fmt, -1), "HALF")
        bits = 8
        while bits < p + 8:
            h = f.mul(nuc, yq)
            e = f.fma(h, yq, ONE)
            yq = f.fma(f.mul(yq, HALF), e, yq)
            bits *= 2
        hy = f.mul(yq, HALF)                             # 1/(2 sqrt u)
        w0 = f.mul(u[0], yq)
        # u0 - w0^2 EXACTLY: w0^2 by TwoProd, u0 - its head exact by
        # Sterbenz (one FMA is exact only for a faithful w0, as the
        # quotient's remainder: the study's 3.6)
        W2, W2e = tp(w0, w0)
        r = f.sub(u[0], W2)
        rh, errs = chain([r, neg(W2e), u[1]])
        rl = plain(errs + [u[2]])
        w1 = f.mul(rh, hy)
        # r - 2 w0 w1 - w1^2: w0 w1 by TwoProd, rh - 2 P exact (Sterbenz)
        P, Pe = tp(w0, w1)
        r2 = f.sub(rh, f.add(P, P))
        r2 = f.sub(r2, f.add(Pe, Pe))
        if rl is not None:
            r2 = f.add(r2, rl)
        r2 = f.fma(neg(w1), w1, r2)
        w2 = None if plant == "w2-dropped" else f.mul(r2, hy)
        wv_ = renorm(w0, w1, w2)
        f.probes.update({k: v for k, v in (("w0", wv_[0]), ("w1", wv_[1]),
                                            ("w2", wv_[2])) if v is not None})
        f.phase = "front"
        swap = f.icmplt(wv_[0], ax)
        nv = [f.sel(wv_[0], ax, swap), f.sel(wv_[1], ZERO, swap),
              f.sel(wv_[2], ZERO, swap) if wv_[2] is not None else None]
        dv = [f.sel(ax, wv_[0], swap), f.sel(ZERO, wv_[1], swap),
              f.sel(ZERO, wv_[2], swap) if wv_[2] is not None else None]
        sx = f.iand(x, SIGN)
        xneg = f.icmplt(ABSM, x) if fn == "acos" else None

    # ---- index -----------------------------------------------------------
    f.phase = "index"
    yd = f.recip_seed(dv[0])
    tt = f.mul(nv[0], yd)
    Kk = f.fma(tt, f.wx(N * SEL_BIAS, "MSEL"), MAGIC)
    f.meta["data"].add(("index", Kk[1]))
    Kk = f.fmin(Kk, f.wx(Fraction(3, 2) * 2 ** (p - 1) + N - 1, "MAGICN1"))
    kf = f.sub(Kk, MAGIC)
    c = f.mul(kf, f.wx(Fraction(1, N), "INVN"))
    nc = neg(c)

    # ---- N = n - c d and D = d + c n, exact expansions ----------------------
    f.phase = "num"
    P = f.mul(c, dv[0])
    nE = f.fma(nc, dv[0], P)                             # P - c d0
    N0 = f.sub(nv[0], P)                                 # exact
    if nv[1] is None:
        Nv = list(f.fast_two_sum(N0, nE)) + [None]
    else:
        # N = N0 + (nE + n1 - c d1) + (the errors, - E1, n2, - c d2): N0
        # exact and leading but for cancellation, the level-1 terms near
        # 2^-24 of n, the level-2 near 2^-48; three words, since N is not
        # small beside n where k = 0. (The first version cut N to two words
        # and lost 2^-48 of it: the study's 3.6.)
        P1, E1 = tp(c, dv[1])
        lv1, errs = chain([nE, nv[1], neg(P1)])
        lv2 = plain(errs + [neg(E1), nv[2],
                            f.mul(nc, dv[2]) if dv[2] is not None else None])
        a_, e_ = f.two_sum(N0, lv1)
        b_, c_ = f.two_sum(e_, lv2)
        a_, b_ = f.fast_two_sum(a_, b_)
        Nv = [a_, b_, c_]
    f.phase = "den"
    Q = f.mul(c, nv[0])
    nF = f.fma(nc, nv[0], Q)                             # Q - c n0
    Dh, De = f.fast_two_sum(dv[0], Q)
    if nv[1] is None:
        D1, D2 = f.two_sum(De, neg(nF))
        Dv = [Dh, D1, D2]
    else:
        Q1, F1 = tp(c, nv[1])
        lv1, errs = chain([De, neg(nF), dv[1], Q1])
        lv2 = plain(errs + [F1, dv[2], f.mul(c, nv[2]) if nv[2] is not None else None])
        Dv = renorm(Dh, lv1, lv2)

    # ---- s = N/D in three words ---------------------------------------------
    f.phase = "quotient"
    yr = f.recip_seed(Dv[0])
    nD0 = neg(Dv[0])
    bits = 8
    while bits < p + 8:
        e = f.fma(nD0, yr, ONE)
        yr = f.fma(yr, e, yr)
        bits *= 2
    q0 = f.mul(Nv[0], yr)
    nq0 = neg(q0)
    # N0 - q0 D0 EXACTLY, as two words: q0 D0 by TwoProd, N0 - its head
    # exact by Sterbenz. A single FMA is exact only when q0 is faithful,
    # and q0 from a single-word reciprocal can be two ulps off: an error of
    # 2^-2p of N, harmless at the double word's formats (2^-106 at fp64)
    # and 2^-48 here (the study's 3.6)
    QD = f.mul(q0, Dv[0])
    nQe = f.fma(nq0, Dv[0], QD)                          # QD - q0 D0
    rem0 = f.sub(Nv[0], QD)                              # exact
    t1 = [rem0, nQe, Nv[1]]
    t2 = [Nv[2]] if Nv[2] is not None else []
    if Dv[1] is not None:
        PP = f.mul(q0, Dv[1])
        nPE = f.fma(nq0, Dv[1], PP)                      # PP - q0 D1
        t1.append(neg(PP))
        t2.append(nPE)
    if Dv[2] is not None:
        t2.append(f.mul(nq0, Dv[2]))
    r1h, errs = chain(t1)
    r1l = plain(errs + t2)
    q1 = f.mul(r1h, yr)
    nq1 = neg(q1)
    r2 = f.fma(nq1, Dv[0], r1h)                          # exact
    if r1l is not None:
        r2 = f.add(r2, r1l)
    if Dv[1] is not None:
        r2 = f.fma(nq1, Dv[1], r2)
    q2 = None if plant == "q2-dropped" else f.mul(r2, yr)
    sv = renorm(q0, q1, q2)
    f.probes.update({k: v for k, v in (("s0", sv[0]), ("s1", sv[1]),
                                        ("s2", sv[2]), ("rem0", rem0),
                                        ("tt", tt), ("Kk", Kk))
                     if v is not None})

    # ---- z = s^2 in three words ---------------------------------------------
    f.phase = "z"
    z0, ze = tp(sv[0], sv[0])
    p01, e01 = tp(sv[0], f.add(sv[1], sv[1]))
    l1, ea = f.two_sum(p01, ze)
    l2 = f.add(ea, e01)
    l2 = f.fma(sv[1], sv[1], l2)
    if sv[2] is not None and plant != "z2-dropped":
        l2 = f.fma(f.add(sv[0], sv[0]), sv[2], l2)
    zv = renorm(z0, l1, l2)
    nzh = neg(zv[0])
    nzl = neg(zv[1])

    # ---- atan(s)/s: tail, K2 double-word steps, K3 triple-word steps ---------
    f.phase = "tail"
    yv = wv(atan_coef(D))
    for k in range(D - 1, K3 + K2 - 1, -1):
        yv = f.fma(yv, zv[0], wv(atan_coef(k)))
    f.phase = "head2"
    yh, yl = yv, None
    for k in range(K3 + K2 - 1, K3 - 1, -1):
        ch, cl = words_of(fmt, atan_coef(k), 2)
        CH = w(ch)
        pp = f.mul(yh, zv[0])
        ne = f.fma(yh, nzh, pp)
        nl = f.fma(yl, nzh, ne) if yl is not None else ne
        nl = f.fma(yh, nzl, nl)
        s_, e2 = f.fast_two_sum(CH, pp)
        tt2 = f.sub(e2, nl)
        yl = f.add(tt2, w(cl)) if cl else tt2
        yh = s_
    f.phase = "head3"
    y0, y1, y2 = yh, yl, None
    for k in range(K3 - 1, -1, -1):
        cw = words_of(fmt, atan_coef(k), 3)
        C0w = w(cw[0])
        p0, e0 = tp(y0, zv[0])
        s0_, t0 = f.fast_two_sum(C0w, p0)
        lv1 = [t0, w(cw[1]) if cw[1] else None, e0]
        lv2 = [w(cw[2]) if cw[2] else None]
        if y1 is not None:
            p10, e10 = tp(y1, zv[0])
            lv1.append(p10)
            lv2.append(e10)
        p01_, e01_ = tp(y0, zv[1])
        lv1.append(p01_)
        lv2.append(e01_)
        acc, errs = chain(lv1)
        lv2 = errs + lv2
        if zv[2] is not None:
            lv2.append(f.mul(y0, zv[2]))
        if y1 is not None:
            lv2.append(f.mul(y1, zv[1]))
        if y2 is not None:
            lv2.append(f.mul(y2, zv[0]))
        s2_ = plain(lv2)
        a0, a1 = f.fast_two_sum(s0_, acc)
        a1, a2 = f.fast_two_sum(a1, s2_)
        y0, y1, y2 = a0, a1, a2
    Pv = [y0, y1, y2]

    # ---- atan(s) = s P, three words -------------------------------------------
    f.phase = "atan_s"
    A0, Ae = tp(sv[0], Pv[0])
    b1_, be1 = tp(sv[0], Pv[1])
    c1_, ce1 = tp(sv[1], Pv[0])
    l1, errs = chain([Ae, b1_, c1_])
    l2 = plain(errs + [be1, ce1,
                       f.mul(sv[0], Pv[2]) if Pv[2] is not None else None,
                       f.mul(sv[1], Pv[1]),
                       f.mul(sv[2], Pv[0]) if sv[2] is not None else None])
    Av = renorm(A0, l1, l2)

    # ---- the table, three words ---------------------------------------------
    f.phase = "table"
    nb = N.bit_length() - 1
    bitsel = [f.iand(Kk, wi(1 << i)) for i in range(nb)]

    def tree(vals):
        level = list(vals)
        for bit in bitsel:
            level = [f.sel(level[2 * m + 1], level[2 * m], bit)
                     for m in range(len(level) // 2)]
        return level[0]
    tw = [words_of(fmt, atan_frac(Fraction(k, N)), 3) for k in range(N)]
    Tv = [tree([w(t[i]) for t in tw]) for i in range(3)]

    # ---- theta0 = T + A; V = C + sigma theta0 ---------------------------------
    f.phase = "recon"
    th, te = f.fast_two_sum(Tv[0], Av[0])
    l1, errs = chain([te, Tv[1], Av[1]])
    l2 = plain(errs + [Tv[2], Av[2]])
    thv = renorm(th, l1, l2)
    PIO2, PI, PIO4 = words3(pi_frac() / 2), words3(pi_frac()), words3(pi_frac() / 4)

    def sel3(a, b, cnd):
        return [f.sel(a[i], b[i], cnd) for i in range(3)]
    Z3 = [ZERO, ZERO, ZERO]
    if fn == "atan":
        isinf = f.cmpeq(ax, INF)
        thv = sel3(Z3, thv, isinf)
        Cv = sel3(PIO2, Z3, swap)
        sigc = swap
    elif fn == "asin":
        Cv = sel3(PIO2, Z3, swap)
        sigc = swap
    elif fn == "acos":
        Cv = sel3(sel3(PI, Z3, xneg), PIO2, swap)
        sigc = f.ixor(f.sel(ZERO, ONE, swap), xneg)
    else:
        yinf, xinf = f.cmpeq(ay, INF), f.cmpeq(ax, INF)
        yzero, xzero = f.icmplt(ay, INT1), f.icmplt(ax, INT1)
        s0z = f.sel(ONE, f.sel(ONE, f.sel(ONE, xzero, yzero), xinf), yinf)
        both = f.sel(xinf, ZERO, yinf)
        thv = sel3(Z3, thv, s0z)
        thv = sel3(PIO4, thv, both)
        Cv = sel3(PIO2, sel3(PI, Z3, xneg), swap)
        sigc = f.ixor(swap, xneg)
    sg = f.sel(SIGN, ZERO, sigc)
    st = [f.ixor(v, sg) for v in thv]
    V0, Ve = f.fast_two_sum(Cv[0], st[0])
    l1, errs = chain([Ve, Cv[1], st[1]])
    l2 = plain(errs + [Cv[2], st[2]])
    Vv = renorm(V0, l1, l2)
    if fn != "acos":
        Vv = [f.ixor(v, sx) for v in Vv]
    f.probes.update(Vh=Vv[0], Vl=Vv[1], V2=Vv[2])

    # ---- final: R = rnd(V0 + RO(V1 + V2)); the test --------------------------
    f.phase = "final"

    def ro_add(a, cc):
        s_ = f.add(a, cc, RTZ)
        exact = f.cmpeq(f.sub(cc, f.sub(s_, a)), ZERO)
        return f.sel(s_, f.ior(s_, INT1), exact)
    lo = ro_add(Vv[1], Vv[2])
    Rg = f.add(Vv[0], lo, rnd)
    Bv = f.mul(f.fabs(Vv[0]), w(pow2_bits(fmt, -(p + G) + bound_shift), "BREL"))
    lo_dn = ro_add(Vv[1], f.sub(Vv[2], Bv, RDN))
    lo_up = ro_add(Vv[1], f.add(Vv[2], Bv, RUP))
    R1 = f.add(Vv[0], lo_dn, rnd)
    R2 = f.add(Vv[0], lo_up, rnd)
    mk = f.ixor(R1, R2)
    fl = f.sel(INXM, INX, mk)
    bits_ = Rg
    f.probes.update(R=Rg, R1=R1, R2=R2, Bv=Bv, mk=mk)

    # ---- specials (m4inv.py's) -----------------------------------------------
    f.phase = "special"
    if fn == "atan2":
        c0 = f.sel(ZERO, f.sel(ZERO, ONE, xneg), swap)
        kz = f.cmpeq(Kk, MAGIC)
        ex = f.sel(f.cmpeq(nQe, ZERO), ZERO, f.cmpeq(rem0, ZERO))
        small = f.icmplt(q0, w(pow2_bits(fmt, ga), "GATEA"))
        side = f.sel(f.sel(f.sel(small, ZERO, ex), ZERO, kz), ZERO, c0)
        ss = f.ixor(q0, sx)
        tb = f.fma(ss, f.wv(-Fraction(1, 2 ** (p + 2))), ss, rnd)
        bits_ = f.sel(tb, bits_, side)
        fl = f.sel(INX, fl, side)
        # the tiny-quotient range, marked: below 2^(emin+2p+2) the third
        # words of s and V fall under the subnormal grid and Bv under
        # minSub's neighbourhood, so three words keep only two (send-back
        # 1; the double word's 2^(emin+p+2) is the plant range-low)
        tqr = fmt.emin + (p if plant == "range-low" else 2 * p) + 2
        rmk = f.sel(f.icmplt(tt, w(pow2_bits(fmt, tqr), "TQR")), ZERO, c0)
        fl = f.sel(INXM, fl, rmk)
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
            tiny = f.icmplt(ax, w(pow2_bits(fmt, g)))
            eps = Fraction(1, 2 ** (p + 2))
            away = fn == "asin"
            tb = f.fma(x, f.wv(eps if away else -eps), x, rnd)
            un = f.icmplt(ax, MINN) if away else f.icmplt(f.iand(tb, ABSM), MINN)
            tfl = f.sel(UNFINX, INX, un)
            bits_ = f.sel(tb, bits_, tiny)
            fl = f.sel(tfl, fl, tiny)
            bits_ = f.sel(x, bits_, iszero)
            fl = f.sel(ZERO, fl, iszero)
        if fn == "acos":
            isone = f.cmpeq(x, ONE)
            bits_ = f.sel(ZERO, bits_, isone)
            fl = f.sel(ZERO, fl, isone)
        if fn in ("asin", "acos"):
            edge = f.icmplt(ONE, ax)
            bits_ = f.sel(QNAN, bits_, edge)
            fl = f.sel(INVALID, fl, edge)
        bits_ = f.sel(QNAN, bits_, isnan)
        fl = f.sel(f.sel(INVALID, ZERO, issnan), fl, isnan)
    f.result, f.flags = bits_, fl
    return f.prune()
