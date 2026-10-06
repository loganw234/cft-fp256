# M1 model: exp at fp32 with triple-word arithmetic where the bound needs
# it (scratch, phase 1). The double-word design's floor at p = 24 is about
# 2^-47, short of 2^-(p+G) = 2^-70 at G = 46; so the reduction, the table,
# the first Taylor terms and the reconstruction carry three words.
#
# Structure as m1exp.py's exp: x = n ln2/8 + r, exp(x) = 2^k T_j (1 + Z),
# Z = r Y(r), the fixed-grid path for results that may be subnormal, the
# in-lane test on the final (V0, V1, V2) through round-to-odd.

import math
from fractions import Fraction

import mpmath

from m1core import (Frag, enc, enc_exact, dec, pow2_bits, RNE, RTZ, RDN,
                    RUP, RMM, sf)
from m1const import words_of, truncated, mpf_to_frac

LN2 = mpmath.log(2)


def two_sum(f, a, b):
    s = f.add(a, b)
    a1 = f.sub(s, b)
    b1 = f.sub(s, a1)
    return s, f.add(f.sub(a, a1), f.sub(b, b1))


def fast_two_sum(f, a, b):
    s = f.add(a, b)
    return s, f.sub(b, f.sub(s, a))


def ro_add(f, a, b, one):
    """round-to-odd of a + b (a's exponent >= b's, or either zero): the
    sum truncated, its last bit set where it was inexact."""
    s = f.add(a, b, RTZ)
    exact = f.cmpeq(f.sub(b, f.sub(s, a)), f.w(0, "ZERO"))
    return f.sel(s, f.ior(s, one), exact)


def build_exp32(fmt, rnd, G=46, N=8, K3=None, K2=None, D=None, brel=None):
    """exp at fp32: K3 triple-word head steps, then K2 double-word steps,
    then the single tail to degree D (of Y)."""
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    assert p == 24
    full = (1 << W) - 1
    rho = math.log(2) / (2 * N) * (1 + 2.0 ** -12)
    lr = math.log2(rho)
    coef = [Fraction(1, math.factorial(i + 1)) for i in range(40)]
    # Y's partial sum y_i enters Z scaled by rho^(i+1) and V by rho^(i+1)
    # too; a w-word step's error is about 2^-(24w - 2) relative to y_i
    def need(i):           # bits of relative accuracy y_i needs
        return (p + G + 2) + (i + 1) * lr + math.log2(coef[i] / coef[0] * 2)
    if D is None:
        D = 1
        while (D + 1) * lr - math.lgamma(D + 3) / math.log(2) > -(p + G + 3):
            D += 1
    if K3 is None:
        K3 = 0
        while need(K3) > 2 * p - 2:
            K3 += 1
    if K2 is None:
        K2 = K3
        while need(K2) > p - 2:
            K2 += 1
        K2 -= K3
    f = Frag(fmt, rnd, f"exp-{fmt.name}-{sf.RND_NAMES[rnd]}-tw")
    f.meta = {"N": N, "G": G, "K3": K3, "K2": K2, "D": D}
    x = ("in", "a")
    w = f.w

    def ib(v):
        return w(v & full)
    ZERO, ONE, INT1 = w(0, "ZERO"), w(sf.one_bits(fmt), "ONE"), ib(1)
    ABSM, INF = ib(full ^ fmt.sign_mask), w(sf.inf_bits(fmt), "INF")
    QBIT, QNAN = ib(1 << (mw - 1)), w(sf.qnan_bits(fmt), "QNAN")
    INX = ib(sf.FLAG_INEXACT)
    INXUNF = ib(sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW)
    OVFINX = ib(sf.FLAG_OVERFLOW | sf.FLAG_INEXACT)
    INVALID = ib(sf.FLAG_INVALID)
    MARK = ib(0x80)
    MAGIC_B = enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    MAGIC = w(MAGIC_B, "MAGIC")
    MANW = ib(mw)

    f.phase = "classify"
    ax = f.iand(x, ABSM)
    isnan = f.icmplt(INF, ax)
    issnan = f.sel(ZERO, isnan, f.iand(x, QBIT))
    isinf = f.cmpeq(ax, INF)
    iszero = f.icmplt(ax, INT1)
    neg = f.ishr(x, ib(W - 1))
    XOVF = enc(fmt, (fmt.emax + 1) * mpf_to_frac(LN2), RUP)
    XUNF = enc(fmt, (fmt.emin - p) * mpf_to_frac(LN2), RDN)
    uns = f.cmple(x, w(XUNF, "XUNF"))
    ovs = f.cmple(w(XOVF, "XOVF"), x)
    tinyx = f.icmplt(ax, w(pow2_bits(fmt, -(p + 3)), "TINYX"))

    # ---- reduce: r = x - n ln2/8 as three words -----------------------
    f.phase = "reduce"
    L = mpf_to_frac(LN2 / N)
    nmax = N * (max(fmt.emax + 1, -(fmt.emin - p)) + 4)
    nb = nmax.bit_length()
    l1 = truncated(fmt, L, p - nb)
    l2 = truncated(fmt, L - dec(fmt, l1), p - nb)
    l3 = truncated(fmt, L - dec(fmt, l1) - dec(fmt, l2), p - nb)
    rest = L - dec(fmt, l1) - dec(fmt, l2) - dec(fmt, l3)
    l4 = enc(fmt, rest)
    l5 = enc(fmt, rest - dec(fmt, l4))
    t = f.fma(x, w(enc(fmt, mpf_to_frac(N / LN2)), "INVLN2N"), MAGIC)
    nf = f.sub(t, MAGIC)
    a = f.fma(nf, w(sf.negate(fmt, l1)), x)          # exact
    q2 = f.mul(nf, w(sf.negate(fmt, l2)))            # exact
    q3 = f.mul(nf, w(sf.negate(fmt, l3)))            # exact
    q4 = f.mul(nf, w(sf.negate(fmt, l4)))
    e4n = f.fma(nf, w(l4), q4)                       # = -(error of q4)
    q5 = f.mul(nf, w(sf.negate(fmt, l5)))
    s0, s1 = two_sum(f, a, q2)
    u0, u1 = two_sum(f, s1, q3)
    v0, v1 = two_sum(f, u0, q4)
    rest_ = f.add(f.sub(f.add(u1, v1), e4n), q5)
    r0, t1 = two_sum(f, s0, v0)
    r1, r2 = two_sum(f, t1, rest_)
    nr0 = f.neg(r0)
    f.probes.update(t=t, nf=nf, r0=r0, r1=r1, r2=r2)

    # ---- the table, three words -----------------------------------------
    f.phase = "lookup"
    bitsel = [f.iand(t, ib(1 << i)) for i in range(3)]

    def tree(vals):
        level = list(vals)
        for b in bitsel:
            level = [f.sel(level[2 * m + 1], level[2 * m], b)
                     for m in range(len(level) // 2)]
        return level[0]
    TW = [words_of(fmt, mpmath.mpf(2) ** (mpmath.mpf(j) / N), 3)
          for j in range(N)]
    T0 = tree([w(tw[0]) for tw in TW])
    T1 = tree([w(tw[1]) for tw in TW])
    T2 = tree([w(tw[2]) for tw in TW])

    # ---- scale factors and the fixed grid (as m1exp.py) ----------------
    f.phase = "scale"
    OFF = p + 8
    if (fmt.bias + OFF) % 2:
        OFF += 1
    half = (fmt.bias + OFF) // 2
    f.meta["OFF"] = OFF
    Ek = f.ishr(f.isub(t, ib(MAGIC_B - N * (fmt.bias + OFF))), ib(3))
    E1 = f.ishr(Ek, INT1)
    KB1 = ib(fmt.bias - half)
    S1 = f.ishl(f.iadd(E1, KB1), MANW)
    S2 = f.ishl(f.iadd(f.isub(Ek, E1), KB1), MANW)
    KD = fmt.emin + 2 * fmt.bias + OFF
    sub_p = f.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF + 1))
    klt = f.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF))
    Cu = f.sel(f.ishl(f.isub(ib(KD), Ek), MANW), w(pow2_bits(fmt, -4), "C0"),
               klt)
    if rnd in (RNE, RMM):
        hu = f.ishl(f.isub(ib(KD - p), Ek), MANW)

    # ---- Y(r0): single tail, double steps, triple steps -----------------
    f.phase = "tail"
    y = w(enc(fmt, coef[D]))
    lo_i = K3 + K2
    for i in range(D - 1, lo_i - 1, -1):
        y = f.fma(y, r0, w(enc(fmt, coef[i])))
    f.phase = "head2"
    yh, yl = y, None
    for i in range(lo_i - 1, K3 - 1, -1):
        ch, cl = words_of(fmt, coef[i], 2)
        CH = w(ch)
        pp = f.mul(yh, r0)
        ne = f.fma(yh, nr0, pp)
        nl = f.fma(yl, nr0, ne) if yl is not None else ne
        s, e = fast_two_sum(f, CH, pp)
        tt = f.sub(e, nl)
        yl = f.add(tt, w(cl)) if cl else tt
        yh = s
    f.phase = "head3"
    y0, y1, y2 = yh, yl, None
    for i in range(K3 - 1, -1, -1):
        c0, c1, c2 = words_of(fmt, coef[i], 3)
        C0w = w(c0)
        p0 = f.mul(y0, r0)
        ne0 = f.fma(y0, nr0, p0)                     # = -e0
        p1 = f.mul(y1, r0) if y1 is not None else None
        ne1 = f.fma(y1, nr0, p1) if y1 is not None else None
        p2 = f.mul(y2, r0) if y2 is not None else None
        s0_, t0 = fast_two_sum(f, C0w, p0)           # level 0
        lv1 = [t0] + ([w(c1)] if c1 else []) + ([p1] if p1 is not None else [])
        acc, errs = lv1[0], []
        for term in lv1[1:]:
            acc, er = two_sum(f, acc, term)
            errs.append(er)
        acc, er = two_sum(f, acc, f.neg(ne0))
        errs.append(er)
        lv2 = errs + ([w(c2)] if c2 else [])
        s2_ = lv2[0]
        for term in lv2[1:]:
            s2_ = f.add(s2_, term)
        if ne1 is not None:
            s2_ = f.sub(s2_, ne1)
        if p2 is not None:
            s2_ = f.add(s2_, p2)
        a0, a1 = fast_two_sum(f, s0_, acc)
        a1, a2 = fast_two_sum(f, a1, s2_)
        y0, y1, y2 = a0, a1, a2
    # ---- Z = r Y with r = r0 + r1 + r2; e^(r0) for the low terms --------
    f.probes.update(y0=y0, y1=y1, y2=y2, T0=T0, T1=T1, T2=T2)
    f.phase = "Z"
    z0 = f.mul(y0, r0)
    nze0 = f.fma(y0, nr0, z0)                        # -e
    z1a = f.mul(y1, r0)
    nze1 = f.fma(y1, nr0, z1a)
    # e^(r0) = 1 + Z(r0) as two words: r1 (~2^-28) needs it to 2^-44
    ep0, ep1 = fast_two_sum(f, ONE, z0)
    z1b = f.mul(ep0, r1)
    nze2 = f.fma(ep0, f.neg(r1), z1b)
    zz, e_a = two_sum(f, z1a, z1b)
    zz, e_b = two_sum(f, zz, f.neg(nze0))
    lvl2 = f.sub(f.sub(f.add(f.add(e_a, e_b), f.mul(y2, r0)), nze1), nze2)
    # e^(r0) to 2^-48: 1 + z0 is short by Z(r0)'s second word
    # (z1a + e0, about 2^-28.5), which times r1 (~2^-28) is 2^-57
    ep1 = f.add(ep1, f.sub(z1a, nze0))
    lvl2 = f.fma(ep1, r1, lvl2)
    lvl2 = f.fma(ep0, r2, lvl2)
    # e^(r1 + r2) - 1 = r1 + r2 + r1^2/2 + ...: at p = 24, r1 ~ 2^-28 and
    # r1^2/2 ~ 2^-57 is in the bound's range (at fp64 it is 2^-116)
    # (and it is e^(r0) r1^2/2: (e^(r0) - 1) r1^2/2 is 2^-63.5 itself)
    lvl2 = f.fma(f.mul(f.mul(r1, w(enc_exact(fmt, Fraction(1, 2)), "HALF")),
                       ep0), r1, lvl2)
    Z0, Z1 = fast_two_sum(f, z0, zz)
    Z1, Z2 = fast_two_sum(f, Z1, lvl2)
    f.probes.update(Z0=Z0, Z1=Z1, Z2=Z2, ep0=ep0, ep1=ep1, lvl2=lvl2, zz=zz, z0=z0)
    # ---- V = T (1 + Z), three words -----------------------------------
    f.phase = "recon"
    P0 = f.mul(T0, Z0)
    nP0 = f.fma(T0, f.neg(Z0), P0)                   # -(err)
    P1 = f.mul(T0, Z1)
    nP1 = f.fma(T0, f.neg(Z1), P1)
    Q1 = f.mul(T1, Z0)
    nQ1 = f.fma(T1, f.neg(Z0), Q1)
    S0, s1 = fast_two_sum(f, T0, P0)
    m, m1 = two_sum(f, s1, T1)
    m, m2 = two_sum(f, m, f.neg(nP0))
    m, m3 = two_sum(f, m, P1)
    m, m4 = two_sum(f, m, Q1)
    l2 = f.add(f.add(f.add(m1, m2), f.add(m3, m4)), T2)
    l2 = f.sub(f.sub(l2, nP1), nQ1)
    l2 = f.fma(T0, Z2, l2)
    l2 = f.fma(T1, Z1, l2)
    l2 = f.fma(T2, Z0, l2)
    V0, V1 = fast_two_sum(f, S0, m)
    V1, V2 = fast_two_sum(f, V1, l2)
    V0, V1 = fast_two_sum(f, V0, V1)
    f.probes.update(V0=V0, V1=V1, V2=V2)

    # ---- final: R = rnd(V0 + RO(V1 + V2)); the test on V1 + V2 +- Bv ---
    f.phase = "final"
    lo = ro_add(f, V1, V2, INT1)
    R = f.add(V0, lo, rnd)
    BV = w(pow2_bits(fmt, -(p + G)) if brel is None else brel, "BREL")
    Bv = f.mul(V0, BV)
    lo_dn = ro_add(f, V1, f.sub(V2, Bv, RDN), INT1)
    lo_up = ro_add(f, V1, f.add(V2, Bv, RUP), INT1)
    R1 = f.add(V0, lo_dn, rnd)
    R2 = f.add(V0, lo_up, rnd)
    mk = f.ixor(R1, R2)
    f.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)
    # fixed grid: Z0' = RN(Cu + V0); the remainder V0 - (Z0' - Cu) + V1 + V2
    f.phase = "fixed-grid"
    Zc = f.add(Cu, V0)
    W0 = f.sub(Zc, Cu)
    zr = f.sub(V0, W0)
    t_ = ro_add(f, zr, lo, INT1) if True else None
    Ws = f.sub(f.add(Zc, t_, rnd), Cu)
    if rnd in (RNE, RMM):
        c1 = f.cmpeq(f.fabs(zr), hu)
    else:
        c1 = f.cmpeq(zr, ZERO)
    smallo = f.cmple(f.fabs(lo), Bv)
    msub = f.sel(smallo, ZERO, c1)
    Wsel = f.sel(Ws, R, sub_p)
    mk = f.sel(ONE, mk, f.sel(msub, ZERO, sub_p))
    tn = f.sel(ONE, f.cmplt(R, ONE), klt)
    tinyu = f.sel(tn, ZERO, sub_p)
    f.phase = "final"
    Y1 = f.mul(Wsel, S1)
    FIN = f.mul(Y1, S2, rnd)
    if rnd in (RNE, RMM, RUP):
        ovf = f.cmpeq(FIN, INF)
    else:
        ovf = f.cmpeq(f.mul(Y1, S2, RUP), INF)
    fl = f.sel(INXUNF, INX, tinyu)
    fl = f.sel(OVFINX, fl, ovf)
    mk = f.sel(ZERO, mk, tinyx)
    fl = f.ior(fl, f.sel(MARK, ZERO, mk))

    f.phase = "special"
    bits = FIN
    unfb = sf.round_pack(fmt, 0, 1, fmt.emin - mw - 2, rnd)[0]
    bits = f.sel(w(unfb, "UNFB"), bits, uns)
    fl = f.sel(INXUNF, fl, uns)
    ovfb = sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0]
    bits = f.sel(w(ovfb, "OVFB"), bits, ovs)
    fl = f.sel(OVFINX, fl, ovs)
    bits = f.sel(ONE, bits, iszero)
    fl = f.sel(ZERO, fl, iszero)
    bits = f.sel(f.sel(ZERO, INF, neg), bits, isinf)
    fl = f.sel(ZERO, fl, isinf)
    bits = f.sel(QNAN, bits, isnan)
    fl = f.sel(f.sel(INVALID, ZERO, issnan), fl, isnan)
    f.result, f.flags = bits, fl
    return f.prune()
