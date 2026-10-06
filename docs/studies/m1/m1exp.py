# M1 model: exp, exp2 and expm1 as tile routines (scratch, phase 1).
#
#   x = n ln2/N + r (exp, expm1; Cody-Waite in three words)  or
#   x = n/N + r'    (exp2, exact; r = r' ln2 as a double word)
#   n = N k + j;  exp(x) = 2^k T_j (1 + Z),  Z = r Y(r) = e^r - 1
#   T_j = 2^(j/N) by a SELECT tree over j's bits (bank words, no scratch)
#   Y(r) = sum r^i/(i+1)!: a single-word tail (Horner by FMA) for
#   i >= K, then K double-word steps; every error-free step is TwoProd by
#   FMA, Fast2Sum where the exponents are ordered, TwoSum elsewhere - no
#   augadd (Logan's question 9: the quad is built without R21).
#   The result is rounded once, under the program's attribute, from the
#   double word V = V_h + V_l in the scaled domain, and scaled by
#   2^k1 2^k2 (k1 = floor(k/2)); a result that may be subnormal is
#   rounded on the fixed grid instead (the fixed-grid path).
#   The in-lane test: R1 = rnd(V_h + RD(V_l - Bv)) and
#   R2 = rnd(V_h + RU(V_l + Bv)); a lane with R1 != R2 is MARKED.

import math
from fractions import Fraction

import mpmath

from m1core import (Frag, enc, enc_exact, dec, pow2_bits, RNE, RTZ, RDN,
                    RUP, RMM, sf)
from m1const import words_of, truncated, mpf_to_frac

LN2 = mpmath.log(2)


def _lg(v):
    return math.log2(v) if v > 0 else -1e9


def exp_plan(fmt, N=8, G=46, rel_z=False):
    """K (double-word head steps) and D (degree of Y), minimal, with the
    bound's estimated total (section 3.2 of the study: the tail
    2u rho^(K+1)/(K+1)! - one factor rho fewer relative to Z, for expm1's
    n = 0 - the truncation rho^(D+2)/(D+2)! (1+rho) and the double-word
    roundings, 10u^2) two bits under 2^-(p+G)."""
    p = fmt.prec
    u = 2.0 ** -p
    rho = math.log(2) / (2 * N) * (1 + 2.0 ** -30)
    extra = 0 if rel_z else 1
    target = 2.0 ** -(p + G + 2)
    floor = 10 * u * u

    def tail(K):
        return 2 * u * math.exp((K + extra) * math.log(rho)
                                - math.lgamma(K + 2))

    def trunc(D):
        return math.exp((D + 1 + extra) * math.log(rho)
                        - math.lgamma(D + 3)) * (1 + rho)
    if floor >= target:
        raise ValueError(f"G = {G} is past the double word's floor at "
                         f"{fmt.name}: 10u^2 = 2^{math.log2(floor):.1f}")
    K = 1
    while tail(K) > target / 2 and K < 60:
        K += 1
    D = K
    while tail(K) + trunc(D) + floor > target and D < 150:
        D += 1
    return K, D, rho


def build_exp(fmt, rnd, fn, N=8, G=46, K=None, D=None, brel=None,
              brel_z=None):
    assert fn in ("exp", "exp2", "expm1")
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    full = (1 << W) - 1
    t_bits = int(math.log2(N))
    assert 1 << t_bits == N
    Kp, Dp, rho = exp_plan(fmt, N, G, rel_z=(fn == "expm1"))
    K = Kp if K is None else K
    D = Dp if D is None else D
    f = Frag(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}")
    f.meta = {"N": N, "G": G, "K": K, "D": D}
    x = ("in", "a")
    w = f.w

    def ib(v):                       # an integer word, two's complement
        return w(v & full)
    ZERO, ONE, INT1 = w(0, "ZERO"), w(sf.one_bits(fmt), "ONE"), ib(1)
    ABSM, INF = ib(full ^ fmt.sign_mask), w(sf.inf_bits(fmt), "INF")
    QBIT, QNAN = ib(1 << (mw - 1)), w(sf.qnan_bits(fmt), "QNAN")
    INX = ib(sf.FLAG_INEXACT)
    INXUNF = ib(sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW)
    OVFINX = ib(sf.FLAG_OVERFLOW | sf.FLAG_INEXACT)
    INVALID = ib(sf.FLAG_INVALID)
    MARK = ib(0x80)
    MAGIC = w(enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1)), "MAGIC")
    MAGIC_B = enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))

    # ---- classify ---------------------------------------------------
    f.phase = "classify"
    ax = f.iand(x, ABSM)
    isnan = f.icmplt(INF, ax)
    qb = f.iand(x, QBIT)
    issnan = f.sel(ZERO, isnan, qb)
    isinf = f.cmpeq(ax, INF)
    iszero = f.icmplt(ax, INT1)
    neg = f.ishr(x, ib(W - 1))
    if fn == "exp2":
        XOVF = enc_exact(fmt, fmt.emax + 1)
        XUNF = enc_exact(fmt, fmt.emin - p)
        uns = f.cmple(x, w(XUNF, "XUNF"))       # x <= emin - p
    else:
        XOVF = enc(fmt, (fmt.emax + 1) * mpf_to_frac(LN2) + Fraction(1, 2 ** 3000), RUP)
        if fn == "exp":
            XUNF = enc(fmt, (fmt.emin - p) * mpf_to_frac(LN2), RDN)
            uns = f.cmple(x, w(XUNF, "XUNF"))
        else:
            XM1 = enc(fmt, -(p + 2) * mpf_to_frac(LN2), RDN)
            m1s = f.cmple(x, w(XM1, "XM1"))
            tiny = f.icmplt(ax, w(pow2_bits(fmt, -(p + 2)), "TINYM1"))
    ovs = f.cmple(w(XOVF, "XOVF"), x)
    if fn != "expm1":
        # transcend.py decides |x| < 2^-(p+3) by the side of 1 alone: the
        # routine's R is that side (V = 1 + Z, Z with x's sign), so the
        # in-lane test, whose bound is relative to V, is not consulted
        tinyx = f.icmplt(ax, w(pow2_bits(fmt, -(p + 3)), "TINYX"))
    f.meta.update(XOVF=XOVF)

    # ---- reduce -----------------------------------------------------
    f.phase = "reduce"
    if fn == "exp2":
        t = f.fma(x, w(enc_exact(fmt, N), "NF"), MAGIC)
        nf = f.sub(t, MAGIC)
        rp = f.fma(nf, w(enc_exact(fmt, Fraction(-1, N)), "NINVN"), x)
        l2 = words_of(fmt, LN2, 2)
        rh = f.mul(rp, w(l2[0], "LN2H"))
        nre = f.fma(rp, w(sf.negate(fmt, l2[0]), "NLN2H"), rh)
        nrl = f.fma(rp, w(sf.negate(fmt, l2[1]), "NLN2L"), nre)
        f.probes.update(rp=rp)
    else:
        L = LN2 / N
        nmax = N * (max(fmt.emax + 1, -(fmt.emin - p)) + 4)
        nb = nmax.bit_length()
        c1 = truncated(fmt, L, p - nb)
        rest = mpf_to_frac(L) - dec(fmt, c1)
        c2 = enc(fmt, rest)
        rest -= dec(fmt, c2)
        c3 = enc(fmt, rest)
        f.meta.update(nb=nb, C1=c1, C2=c2, C3=c3)
        t = f.fma(x, w(enc(fmt, mpf_to_frac(N / LN2)), "INVLN2N"), MAGIC)
        nf = f.sub(t, MAGIC)
        r1 = f.fma(nf, w(sf.negate(fmt, c1), "NC1"), x)
        Q = f.mul(nf, w(sf.negate(fmt, c2), "NC2"))
        Qe = f.fma(nf, w(c2, "C2"), Q)              # = -(error of Q)
        s = f.add(r1, Q)                            # TwoSum(r1, Q)
        a1 = f.sub(s, Q)
        b1 = f.sub(s, a1)
        da = f.sub(r1, a1)
        db = f.sub(Q, b1)
        e = f.add(da, db)
        rh = s
        nrl = f.fma(nf, w(c3, "C3"), f.sub(Qe, e))  # = -(e - Qe - n C3)
    nr = f.neg(rh)
    f.probes.update(t=t, nf=nf, rh=rh, nrl=nrl)

    # ---- index and table ----------------------------------------------
    f.phase = "lookup"
    bitsel = [f.iand(t, ib(1 << i)) for i in range(t_bits)]
    if fn == "exp2":
        # exact iff x is an integer: r' = 0 and j = 0
        jz = f.icmplt(f.iand(t, ib(N - 1)), INT1)
        exact = f.sel(f.cmpeq(rp, ZERO), ZERO, jz)
    TH, TL = [], []
    for j in range(N):
        hw = words_of(fmt, mpmath.mpf(2) ** (mpmath.mpf(j) / N), 2)
        TH.append(w(hw[0]))
        TL.append(w(hw[1]))

    def tree(vals):
        level = list(vals)
        for b in bitsel:
            level = [f.sel(level[2 * m + 1], level[2 * m], b)
                     for m in range(len(level) // 2)]
        return level[0]
    Th, Tl = tree(TH), tree(TL)
    f.probes.update(Th=Th, Tl=Tl)

    # ---- scale factors from n (integers on the encoding) ---------------
    f.phase = "scale"
    OFF = p + 8
    if (fmt.bias + OFF) % 2:
        OFF += 1
    half = (fmt.bias + OFF) // 2
    f.meta["OFF"] = OFF
    KOFFK = (MAGIC_B - N * (fmt.bias + OFF))
    Ek = f.ishr(f.isub(t, ib(KOFFK)), ib(t_bits))     # k + bias + OFF
    E1 = f.ishr(Ek, INT1)
    KB1 = ib(fmt.bias - half)
    MANW = ib(mw)
    S1 = f.ishl(f.iadd(E1, KB1), MANW)                # 2^k1
    S2 = f.ishl(f.iadd(f.isub(Ek, E1), KB1), MANW)    # 2^k2
    f.probes.update(Ek=Ek, S1=S1, S2=S2)
    if fn in ("exp", "exp2"):
        KD = fmt.emin + 2 * fmt.bias + OFF
        sub_p = f.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF + 1))  # k <= emin
        klt = f.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF))        # k < emin
        Cu = f.sel(f.ishl(f.isub(ib(KD), Ek), MANW),
                   w(pow2_bits(fmt, -4), "C0"), klt)
        if rnd in (RNE, RMM):
            hu = f.ishl(f.isub(ib(KD - p), Ek), MANW)   # u/2 = 2^(D-p)
    if fn == "expm1":
        # 2^-k, clamped to 0 where it is below 2^-(p+G+2)
        npk = f.ishl(f.isub(ib(2 * fmt.bias + OFF), Ek), MANW)
        kbig = f.icmplt(ib(p + G + 2 + fmt.bias + OFF), Ek)
        npk = f.sel(ZERO, npk, kbig)

    # ---- the polynomial Y(r) = sum r^i/(i+1)! -------------------------
    f.phase = "tail"
    coef = [Fraction(1, math.factorial(i + 1)) for i in range(D + 1)]
    y = w(enc(fmt, coef[D]))
    for i in range(D - 1, K - 1, -1):
        y = f.fma(y, rh, w(enc(fmt, coef[i])))
    f.phase = "head"
    yh, yl = y, None
    for i in range(K - 1, -1, -1):
        ch, cl = words_of(fmt, coef[i], 2)
        CH = w(ch)
        pp = f.mul(yh, rh)
        ne = f.fma(yh, nr, pp)                       # pp - yh r = -err
        nl = f.fma(yl, nr, ne) if yl is not None else ne
        s = f.add(CH, pp)                            # Fast2Sum(c, pp)
        z = f.sub(s, CH)
        e = f.sub(pp, z)
        tt = f.sub(e, nl)
        yl = f.add(tt, w(cl)) if cl else tt
        yh = s
    f.phase = "Z"
    zp = f.mul(yh, rh)
    nze = f.fma(yh, nr, zp)
    nzl = f.fma(yl, nr, nze)
    # r_l enters through e^(r_h), not Y(r_h): e^(r_h) ~ 1 + Z_h, rounded
    # once (its error times |r_l| ~ 2^-(2p+5) is far below the bound)
    nZl = f.fma(f.add(ONE, zp), nrl, nzl)            # Z = zp - nZl
    f.probes.update(Yh=yh, Yl=yl, Zh=zp, nZl=nZl)

    # ---- reconstruct V = T (1 + Z) [ - 2^-k for expm1 ] ---------------
    f.phase = "recon"
    P = f.mul(Th, zp)
    nPe = f.fma(Th, f.neg(zp), P)                    # P - Th Zh = -Pe
    if fn == "expm1":
        sA = f.sub(Th, npk)                          # TwoSum(Th, -2^-k)
        a1 = f.add(sA, npk)
        b1 = f.sub(sA, a1)
        da = f.sub(Th, a1)
        dbn = f.add(npk, b1)
        ea = f.sub(da, dbn)
        base = sA
    else:
        base = Th
    S = f.add(base, P)                               # Fast2Sum(base, P)
    zz = f.sub(S, base)
    e2 = f.sub(P, zz)
    a1 = f.fma(Th, nZl, nPe)                         # -(Th Zl + Pe)
    a2 = f.fma(Tl, zp, Tl)                           # Tl (1 + Zh)
    lo = f.add(f.sub(e2, a1), a2)
    if fn == "expm1":
        lo = f.add(lo, ea)
    Vh = f.add(S, lo)                                # Fast2Sum(S, lo)
    Vl = f.sub(lo, f.sub(Vh, S))
    f.probes.update(Vh=Vh, Vl=Vl)

    # ---- the final rounding and the in-lane test ------------------------
    f.phase = "final"
    R = f.add(Vh, Vl, rnd)
    n0 = f.cmpeq(nf, ZERO)
    BV = w(pow2_bits(fmt, -(p + G)) if brel is None else brel, "BREL")
    BZ = w(pow2_bits(fmt, -(p + G)) if brel_z is None else brel_z, "BRELZ")
    if fn == "expm1":
        # n = 0: V' is Z itself, and the bound is relative to it
        Bv = f.mul(f.fabs(Vh), f.sel(BZ, BV, n0))
    else:
        # relative to V for every lane: for n = 0, V = 1 + Z as a double
        # word cannot resolve Z's bits below 2^-2p (the study, 2.3)
        Bv = f.mul(Vh, BV)
    lo_dn = f.sub(Vl, Bv, RDN)
    lo_up = f.add(Vl, Bv, RUP)
    R1 = f.add(Vh, lo_dn, rnd)
    R2 = f.add(Vh, lo_up, rnd)
    mk = f.ixor(R1, R2)
    f.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)
    if fn in ("exp", "exp2"):
        f.phase = "fixed-grid"
        Z0 = f.add(Cu, Vh)
        W0 = f.sub(Z0, Cu)
        zr = f.sub(Vh, W0)
        s_ = f.add(zr, Vl, RTZ)                      # round to odd
        eq = f.cmpeq(f.sub(s_, zr), Vl)
        ro = f.sel(s_, f.ior(s_, INT1), eq)
        Ws = f.sub(f.add(Z0, ro, rnd), Cu)
        if rnd in (RNE, RMM):
            c1 = f.cmpeq(f.fabs(zr), hu)
        else:
            c1 = f.cmpeq(zr, ZERO)
        smallo = f.cmple(f.fabs(Vl), Bv)
        msub = f.sel(smallo, ZERO, c1)
        Wsel = f.sel(Ws, R, sub_p)
        mk = f.sel(ONE, mk, f.sel(msub, ZERO, sub_p))
        tn = f.sel(ONE, f.cmplt(R, ONE), klt)
        tinyu = f.sel(tn, ZERO, sub_p)
        f.probes.update(Ws=Ws, sub_p=sub_p)
        f.phase = "final"
    else:
        Wsel = R
    Y1 = f.mul(Wsel, S1)
    FIN = f.mul(Y1, S2, rnd)
    if rnd in (RNE, RMM, RUP):
        ovf = f.cmpeq(FIN, INF)
    else:
        ovf = f.cmpeq(f.mul(Y1, S2, RUP), INF)
    fl = f.sel(INXUNF, INX, tinyu) if fn != "expm1" else INX
    fl = f.sel(OVFINX, fl, ovf)
    if fn != "expm1":
        mk = f.sel(ZERO, mk, tinyx)
    fl = f.ior(fl, f.sel(MARK, ZERO, mk))
    if fn == "exp2":
        fl = f.sel(ZERO, fl, exact)
    f.probes.update(FIN=FIN, mk=mk)

    # ---- specials, lowest priority first -------------------------------
    f.phase = "special"
    bits = FIN
    if fn == "expm1":
        tb = f.fma(x, x, x, rnd)
        ut = f.icmplt(ax, w(sf.min_normal_bits(fmt), "MINN"))
        if rnd in (RTZ, RUP):
            ut = f.sel(ONE, ut, f.cmpeq(x, w(sf.min_normal_bits(fmt, 1),
                                            "NMINN")))
        tfl = f.sel(INXUNF, INX, ut)
        bits = f.sel(tb, bits, tiny)
        fl = f.sel(tfl, fl, tiny)
        m1b = sf.round_pack(fmt, 1, (1 << (p + 3)) - 1, -(p + 3), rnd)[0]
        bits = f.sel(w(m1b, "M1B"), bits, m1s)
        fl = f.sel(INX, fl, m1s)
    else:
        unfb = sf.round_pack(fmt, 0, 1, fmt.emin - mw - 2, rnd)[0]
        bits = f.sel(w(unfb, "UNFB"), bits, uns)
        fl = f.sel(INXUNF, fl, uns)
    ovfb = sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0]
    bits = f.sel(w(ovfb, "OVFB"), bits, ovs)
    fl = f.sel(OVFINX, fl, ovs)
    if fn == "expm1":
        bits = f.sel(x, bits, iszero)
        infb = f.sel(w(sf.one_bits(fmt, 1), "NEGONE"), INF, neg)
    else:
        bits = f.sel(ONE, bits, iszero)
        infb = f.sel(ZERO, INF, neg)
    fl = f.sel(ZERO, fl, iszero)
    bits = f.sel(infb, bits, isinf)
    fl = f.sel(ZERO, fl, isinf)
    bits = f.sel(QNAN, bits, isnan)
    fl = f.sel(f.sel(INVALID, ZERO, issnan), fl, isnan)
    f.result, f.flags = bits, fl
    return f.prune()
