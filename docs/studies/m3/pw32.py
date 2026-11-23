# M3 model: pow and powr at fp32 as a TRIPLE word (parcel M3X; scratch, not the
# tree's code, and nothing in the tree imports it). The study's 2.8 sketch
# built and measured: result = sign 2^t, t = y log2|x|, G = 40.
#
#   logarithm  M1's fp32 log2 (the reduction, the three-word table, the
#              triple/double/single Horner steps of plan_log32, the sum with
#              1/ln 2 in three words), planned at GL = G + 8 (L to p + G + 8
#              = 72 bits), L = L0 + L1 + L2
#   product    t = y L in three words: TwoProd of y against L0 and L1, a
#              rounded product with L2, the level sums by a cascade
#   exponential  M1's fp32 exp2: n = round(8 t0) by the magic-number FMA,
#              r' = (t0 - n/8) + t1 + t2 (three words), r = r' ln 2 in three
#              words (a 3 x 3 product by levels), the three-word table, the
#              triple/double/single polynomial, V = V0 + V1 + V2
#   test       round-to-odd of the low words, the in-lane test on
#              V1 + V2 -+ Bv with Bv = |V0| (2^-(p+G) + |t0| B1 + |y k| B2),
#              the "may be exact" test under rne and rmm, the fixed grid, the
#              exact power of two, the rule beside 1, the screens, the signs
#              and the specials: the model's (m3pow.py), imported or copied
#
# Built on the tree's mathlib.Build and M1's helpers, imported and never
# edited. Every name, constant and order here is PROPOSED. The static proofs
# are asserted (static_proofs) with a message that names each, before a lane
# runs.

import math
import types
from fractions import Fraction

from m3core import ml, sf, routines, RNE, RTZ, RDN, RUP, RMM, AN, FP32
import m3pow as M

fmt = FP32
N = ml.N
GUARD = 40

# the plants (each a `plant=` of build; the brief's three, named)
PLANTS = {
    "l3_dropped": "the third word of L dropped: the product's rounded term "
                  "y L2 and L2's share of the sum are left out",
    "b1_dropped": "the bound's |t0| B1 term dropped (B1 = 0): Bv = |V0| "
                  "(2^-(p+G) + |y k| B2)",
    "mark_silenced": "the mark never set",
}

# B1 and B2 (the bound's coefficients of |t0| and |y k|): each try of the
# ladder is a pair of exponents, recorded by the driver. The first value is
# the study's ESTIMATE (2.8: B1 about 2^-(3p-6), B2 about 2^-(3p-5)).
B1_FIRST = Fraction(1, 2 ** (3 * 24 - 6))
B2_FIRST = Fraction(1, 2 ** (3 * 24 - 5))

# the phase each label is scheduled by (mathlib.PHASE_ORDER's names); the map
# the `live` mode prints
PHASE_MAP = {
    "classify": "classify", "front": "front",
    "log-reduce": "reduce", "log-table": "table", "log-tail": "tail",
    "log-head2": "head2", "log-head3": "head3", "log-Z": "Z",
    "log-sum": "recon",
    "product": "reduce",
    "exp-reduce": "reduce", "exp-table": "lookup", "exp-scale": "scale",
    "exp-tail": "tail", "exp-head2": "head2", "exp-head3": "head3",
    "exp-Z": "Z", "exp-recon": "recon",
    "exact": "final", "test": "final", "fixed-grid": "fixed-grid",
    "final": "final", "beside-1": "final", "special": "special",
}
# the parts of the study's 5.1 (logarithm, product, exponential, test,
# specials), by label
PARTS = {
    "classify": "specials", "front": "specials", "special": "specials",
    "log-reduce": "logarithm", "log-table": "logarithm",
    "log-tail": "logarithm", "log-head2": "logarithm",
    "log-head3": "logarithm", "log-Z": "logarithm", "log-sum": "logarithm",
    "product": "product",
    "exp-reduce": "exponential", "exp-table": "exponential",
    "exp-scale": "exponential", "exp-tail": "exponential",
    "exp-head2": "exponential", "exp-head3": "exponential",
    "exp-Z": "exponential", "exp-recon": "exponential",
    "exact": "test", "test": "test", "fixed-grid": "test", "final": "test",
    "beside-1": "test",
}


def plan(G=GUARD, GL=None):
    """(G, GL, (K3, K2, D) of the logarithm, (K3, K2, D) of the exponential):
    GL = G + 8 (M.extra_bits: log2 of T_f = 152 rounded up), the logarithm's
    planned guard where L must reach p + G + 8 bits."""
    GL = G + M.extra_bits(fmt) if GL is None else GL
    return G, GL, ml.plan_log32(fmt, GL), ml.plan_exp32(fmt, G)


def static_proofs(G, GL, plog, pexp):
    """Every static proof of the build, asserted, each message naming it.
    Exact rationals; run before any lane. Returns the names that held."""
    p = fmt.prec
    held = []

    def proof(name, ok, why):
        if not ok:
            raise AssertionError(f"static proof {name!r} FAILED: {why}")
        held.append(name)
    K3, K2, D = plog
    rho_l = ml.RHO_LOG
    proof("log-truncation",
          rho_l ** (D + 1) / ((D + 2) * (1 - rho_l))
          <= Fraction(1, 2 ** (p + GL + 3)),
          f"the log polynomial's truncation at degree {D} is over "
          f"2^-(p+GL+3) = 2^-{p + GL + 3}")
    for i, bits in ((K3, 2 * p - 2), (K3 + K2, p - 2)):
        proof(f"log-step-{i}-fits",
              rho_l ** i * 2 / (i + 1) <= Fraction(2) ** (bits - (p + GL + 2)),
              f"the log's partial sum y_{i} needs more than {bits} bits")
    proof("log-three-word-steps-first",
          K3 >= 1 and K3 + K2 <= D,
          f"K3 {K3}, K2 {K2}, D {D}: the tail starts after the steps")
    k3, k2, d = pexp
    rho_e = ml._rho(fmt, ml._cushion(fmt))
    proof("exp-truncation",
          rho_e ** (d + 1) / math.factorial(d + 2)
          <= Fraction(1, 2 ** (p + G + 3)),
          f"the exp polynomial's truncation at degree {d} is over "
          f"2^-(p+G+3)")
    # r' = (t0 - n/8) + t1 + t2: |t0 - n/8| <= 1/16 exactly (n by one
    # rounding of 8 t0), |t1| <= ulp(t0)/2 <= 2^-17 for |t0| < 2^8, t2 below
    # that: so |r| <= (1/16 + 2^-16) ln 2, inside the polynomial's rho
    ln2_hi = Fraction(6931472, 10 ** 7)
    proof("exp-rho",
          (Fraction(1, 16) + Fraction(1, 2 ** 16)) * ln2_hi <= rho_e,
          "r' ln 2 past the exponential polynomial's rho")
    tf = M.t_reach(fmt)
    proof("exp-magic-range",
          8 * tf < 2 ** (p - 2),
          f"8 T_f = {8 * tf} is not under 2^(p-2): MAGIC's units digit is "
          f"not n")
    off = ml._scale_offset(fmt)
    half = (fmt.bias + off) // 2
    ok = True
    for k in range(fmt.emin - p - 2, fmt.emax + 3):
        ek = k + fmt.bias + off
        e1 = ek >> 1
        ok = ok and ek > 0 and 1 <= e1 + fmt.bias - half <= 2 ** fmt.exp_w - 2             and 1 <= ek - e1 + fmt.bias - half <= 2 ** fmt.exp_w - 2
    proof("exp-scale-words-in-range", ok,
          "2^k1 or 2^k2 leaves the exponent field for some k the main path "
          "sees")
    # the dropped terms: ln 2 in three words is short by under 2^-74 of
    # itself, and the 3 x 3 product by levels drops level 3, about 2^-72 of
    # r 's scale (r <= 0.0434 = 2^-4.5): 2^-77, under 2^-(p+G+2) = 2^-66
    # with 11 bits to spare
    w = [ml._dec(fmt, v) for v in ml._words(fmt, ml._ln2(), 3)]
    miss = abs(ml._ln2() - sum(w))
    proof("ln2-three-words", miss < Fraction(1, 2 ** (3 * p + 1)),
          f"ln 2 less its three words is {float(miss):.3e}")
    proof("exp-r-level-3",
          Fraction(1, 2 ** (3 * p + 1)) * Fraction(1, 16)
          <= Fraction(1, 2 ** (p + G + 8)),
          "r's level-3 terms exceed 2^-(p+G+8)")
    iw = [ml._dec(fmt, v) for v in ml._words(fmt, ml._inv_ln2(), 3)]
    proof("inv-ln2-three-words",
          abs(ml._inv_ln2() - sum(iw)) < Fraction(1, 2 ** (3 * p + 1)),
          "1/ln 2 less its three words")
    proof("log-product-floor", p + GL + 2 <= 3 * p + 2,
          f"GL = {GL} asks for more than the three words can hold")
    return held


_CACHE = {}


def _consts(G, GL, plog, pexp):
    key = (G, GL, plog, pexp)
    if key not in _CACHE:
        cl = ml._log32_constants("log2", fmt, GL, *plog, 0, None)
        ce = ml._tw_constants("exp2", fmt, G, *pexp, 0, None)
        _CACHE[key] = (cl, ce)
    return _CACHE[key]


def _poly3(b, c, K3, K2, D, r, nr, pre, lab):
    """Y(r): a single-word tail to degree D, K2 double-word steps, K3
    triple-word steps (M1's fp32 steps, mathlib _build_log_tw's, copied; the
    constants A{i}_k, B{i}_k and Y{i} are `c`'s). Returns y0, y1, y2."""
    two_sum, fast_two_sum = b.two_sum, b.fast_two_sum
    M._at(b, f"{lab}-tail", "tail")
    y = b.const(f"{pre}Y{D}", c[f"Y{D}"])
    lo_i = K3 + K2
    for i in range(D - 1, lo_i - 1, -1):
        y = b.fma(y, r, b.const(f"{pre}Y{i}", c[f"Y{i}"]))
    M._at(b, f"{lab}-head2", "head2")
    yh, yl = y, None
    for i in range(lo_i - 1, K3 - 1, -1):
        CH = b.const(f"{pre}A{i}_0", c[f"A{i}_0"])
        CL = b.const(f"{pre}A{i}_1", c[f"A{i}_1"])
        pp = b.mul(yh, r)
        ne = b.fma(yh, nr, pp)
        nl = b.fma(yl, nr, ne) if yl is not None else ne
        s, e = fast_two_sum(CH, pp)
        tt = b.sub(e, nl)
        yl = b.add(tt, CL) if c[f"A{i}_1"] else tt
        yh = s
    M._at(b, f"{lab}-head3", "head3")
    y0, y1, y2 = yh, yl, None
    for i in range(K3 - 1, -1, -1):
        C0w = b.const(f"{pre}B{i}_0", c[f"B{i}_0"])
        C1w = b.const(f"{pre}B{i}_1", c[f"B{i}_1"])
        C2w = b.const(f"{pre}B{i}_2", c[f"B{i}_2"])
        c1, c2 = c[f"B{i}_1"], c[f"B{i}_2"]
        p0 = b.mul(y0, r)
        ne0 = b.fma(y0, nr, p0)                       # = -e0
        p1 = b.mul(y1, r) if y1 is not None else None
        ne1 = b.fma(y1, nr, p1) if y1 is not None else None
        p2 = b.mul(y2, r) if y2 is not None else None
        s0_, t0 = fast_two_sum(C0w, p0)               # level 0
        lv1 = [t0] + ([C1w] if c1 else []) + ([p1] if p1 is not None else [])
        acc, errs = lv1[0], []
        for term in lv1[1:]:
            acc, er = two_sum(acc, term)
            errs.append(er)
        acc, er = two_sum(acc, b.neg(ne0))
        errs.append(er)
        lv2 = errs + ([C2w] if c2 else [])
        s2_ = lv2[0]
        for term in lv2[1:]:
            s2_ = b.add(s2_, term)
        if ne1 is not None:
            s2_ = b.sub(s2_, ne1)
        if p2 is not None:
            s2_ = b.add(s2_, p2)
        a0, a1 = fast_two_sum(s0_, acc)
        a1, a2 = fast_two_sum(a1, s2_)
        y0, y1, y2 = a0, a1, a2
    return y0, y1, y2


def build(fn, rnd, G=GUARD, bound_shift=0, plant=None, B1=None, B2=None,
          GL=None):
    """pow or powr at fp32 under rnd, as a triple word, instrumented. `B1`
    and `B2` are the bound's coefficients (Fractions; the study's estimate by
    default); `bound_shift` inflates the bound 2^shift times (the mark-rate
    law); `GL` overrides the logarithm's planned guard."""
    if fn not in ("pow", "powr"):
        raise ValueError(f"pw32 builds pow and powr, not {fn!r}")
    if plant is not None and plant not in PLANTS:
        raise ValueError(f"unknown plant {plant!r}: {', '.join(PLANTS)}")
    p, mw = fmt.prec, fmt.man_w
    G, GL, plog, pexp = plan(G, GL)
    proofs = static_proofs(G, GL, plog, pexp)
    B1 = B1_FIRST if B1 is None else Fraction(B1)
    B2 = B2_FIRST if B2 is None else Fraction(B2)
    if plant == "b1_dropped":
        B1 = Fraction(0)
    cl_, ce = _consts(G, GL, plog, pexp)
    b = M.PBuild(fmt, rnd, f"{fn}-fp32-{AN[rnd]}-tw")
    b.inputs = ("a", "b")
    b.meta.update(fn=fn, G=G, GL=GL, GE=G, KL=plog, KE=pexp, B1=B1, B2=B2,
                  plant=plant, family="triple word", N=N, shift=bound_shift,
                  proofs=proofs)
    k_ = ml._words_common(b)
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    INF, QNAN = k_["INF"], k_["QNAN"]
    INX, INXUNF, OVFINX = k_["INX"], k_["INXUNF"], k_["OVFINX"]
    MARKW = k_["MARKW"]
    SIGN = ib(fmt.sign_mask, "SIGN_BIT")
    two_sum, fast_two_sum = b.two_sum, b.fast_two_sum
    at = M._at

    def W(name, bits):
        return b.word(bits, name)

    # ---- classify ----------------------------------------------------------
    at(b, "classify", "classify")
    cl = ml._classify_common(b, k_)
    x = cl.x
    yc = M._classify(b, k_, "b")

    # ---- the sign -----------------------------------------------------------
    at(b, "front", "front")
    isint = odd = negres = None
    if fn == "pow":
        isint, odd = M._integrality(b, k_, yc, None)
        negres = b.sel(odd, ZERO, cl.neg)
    sgnw = None
    if negres is not None:
        sgnw = b.iand(x, SIGN) if negres is cl.neg else \
            b.sel(SIGN, ZERO, negres)
    Y = ("in", "b")

    # ---- the logarithm: L = log2|x| in three words ---------------------------
    at(b, "log-reduce", "reduce")
    clx = types.SimpleNamespace(x=cl.ax, ax=cl.ax)
    red = ml._log_reduce(b, "log2", cl_, k_, clx, None)
    r, kf = red.r, red.kf
    at(b, "log-table", "table")
    t0_, t1_, t2_ = ml._table(b, cl_, red.tc, k_,
                              tuple(lambda j, i=i: f"L{j}_{i}"
                                    for i in range(3)))
    nr = b.neg(r)
    y0, y1, y2 = _poly3(b, cl_, *plog, r, nr, "L", "log")
    at(b, "log-Z", "Z")
    P0 = b.mul(y0, r)
    nE0 = b.fma(y0, nr, P0)                           # = -e0
    P1 = b.mul(y1, r)
    nE1 = b.fma(y1, nr, P1)
    P2 = b.mul(y2, r)
    at(b, "log-sum", "recon")
    F0s, Ea = fast_two_sum(t0_, P0)                   # |L0| >= |P0| or L0 = 0
    S1, errs = ml._cascade(b, [(Ea, False), (t1_, False), (nE0, True),
                               (P1, False)])
    S2 = ml._plain_sum(b, [(P2, False), (nE1, True), (t2_, False)]
                       + [(e, False) for e in errs])
    F0, F1 = fast_two_sum(F0s, S1)
    F1, F2 = fast_two_sum(F1, S2)
    F0, F1 = fast_two_sum(F0, F1)
    I0, I1, I2 = (b.const(f"IL2_{i}", cl_[f"IL2_{i}"]) for i in range(3))
    NI0, NI1 = (b.const(f"NIL2_{i}", cl_[f"NIL2_{i}"]) for i in range(2))
    g0 = b.mul(F0, I0)
    ng0 = b.fma(F0, NI0, g0)
    g1 = b.mul(F0, I1)
    ng1 = b.fma(F0, NI1, g1)
    g2 = b.mul(F1, I0)
    ng2 = b.fma(F1, NI0, g2)
    q0, q1, q2 = b.mul(F0, I2), b.mul(F1, I1), b.mul(F2, I0)
    Sk0, Ek_ = fast_two_sum(kf, g0)                   # |k| >= |g0| or k = 0
    Sk1, errs = ml._cascade(b, [(Ek_, False), (ng0, True), (g1, False),
                                (g2, False)])
    Sk2 = ml._plain_sum(b, [(q2, False), (q1, False), (q0, False),
                            (ng2, True), (ng1, True)]
                        + [(e, False) for e in errs])
    L0, L1 = fast_two_sum(Sk0, Sk1)
    L1, L2 = fast_two_sum(L1, Sk2)
    L0, L1 = fast_two_sum(L0, L1)
    if plant == "l3_dropped":
        L2 = ZERO
    b.probes.update(L0=L0, L1=L1, L2=L2, r=r)

    # ---- t = y L in three words ----------------------------------------------
    at(b, "product", "reduce")
    nL0, nL1 = b.neg(L0), b.neg(L1)
    Q0 = b.mul(Y, L0)
    pnE0 = b.fma(Y, nL0, Q0)                          # -(the error of Q0)
    Q1 = b.mul(Y, L1)
    pnE1 = b.fma(Y, nL1, Q1)
    Q2 = b.mul(Y, L2)
    u0, u1 = b.two_diff(Q1, pnE0)                     # e0 + Q1 = u0 + u1
    lv2 = b.sub(b.add(Q2, u1), pnE1)                  # Q2 + u1 + e1
    th0 = Q0
    t0, tc1 = fast_two_sum(Q0, u0)                    # |Q0| >= |u0|
    t1, t2 = two_sum(tc1, lv2)
    b.probes.update(th0=th0, t0=t0, t1=t1, t2=t2)
    # the screens, on the rounded product (an overflowed product is +-inf)
    hi_t = fmt.emax + 2
    ovs = b.cmple(W("TOVF", ml._enc_exact(fmt, hi_t)), th0)
    uns = b.cmple(th0, W("TUNF", ml._enc_exact(fmt, fmt.emin - p - 2)))

    # ---- the bound's coefficient w: Bv = |V0| w ------------------------------
    at(b, "test", "head2")
    sh = bound_shift
    wB = W("BREL", ml._pow2(fmt, -(p + G) + sh))
    if B1:
        wB = b.fma(b.fabs(t0), W("B1", ml._enc(fmt, B1 * 2 ** sh)), wB, RUP)
    if B2:
        yk = b.mul(b.fabs(kf), yc.ax, RUP)
        wB = b.fma(yk, W("B2", M._enc_up(fmt, B2 * 2 ** sh)), wB, RUP)

    # ---- 2^t: M1's fp32 exp2 with a three-word argument ----------------------
    at(b, "exp-reduce", "reduce")
    MAGIC = W("MAGIC", ce["MAGIC"])
    tq = b.fma(t0, W("EIGHT", ce["EIGHT"]), MAGIC)
    nf = b.sub(tq, MAGIC)
    rp = b.fma(nf, W("NINV8", ce["NINV8"]), t0)       # t0 - n/8: exact
    a0, a1 = fast_two_sum(rp, t1)                     # rp = 0 or |rp| >= |t1|
    R1_, R2_ = two_sum(a1, t2)
    R0_ = a0
    # r = r' ln 2: R x LN by levels (TwoProd of the first levels, rounded
    # products below), as M1's log2's k + F/ln 2 and exp2's r' ln 2
    LN0, LN1, LN2 = (b.const(f"LN2_{i}", ce[f"LN2_{i}"]) for i in range(3))
    NLN0, NLN1 = (b.const(f"NLN2_{i}", ce[f"NLN2_{i}"]) for i in range(2))
    c00 = b.mul(R0_, LN0)
    n00 = b.fma(R0_, NLN0, c00)
    c01 = b.mul(R0_, LN1)
    n01 = b.fma(R0_, NLN1, c01)
    c10 = b.mul(R1_, LN0)
    n10 = b.fma(R1_, NLN0, c10)
    d02, d11, d20 = b.mul(R0_, LN2), b.mul(R1_, LN1), b.mul(R2_, LN0)
    s0, E1 = fast_two_sum(c00, c01)                   # |c00| >= |c01|
    acc, errs = ml._cascade(b, [(E1, False), (c10, False), (n00, True)])
    s2 = ml._plain_sum(b, [(d20, False), (d11, False), (d02, False),
                           (n10, True), (n01, True)]
                       + [(e, False) for e in errs])
    r0, r1 = fast_two_sum(s0, acc)
    r1, r2 = fast_two_sum(r1, s2)
    r0, r1 = fast_two_sum(r0, r1)
    nr0 = b.neg(r0)
    b.probes.update(tq=tq, rp=rp, r0=r0, r1=r1, r2=r2)
    at(b, "exp-table", "lookup")
    T0, T1, T2 = ml._table(b, ce, tq, k_,
                           tuple(lambda j, i=i: f"T{j}_{i}"
                                 for i in range(3)))
    at(b, "exp-scale", "scale")
    sc = ml._scale(b, "exp2", rnd, tq, ce, G, None, k_)
    y0, y1, y2 = _poly3(b, ce, *pexp, r0, nr0, "E", "exp")
    at(b, "exp-Z", "Z")
    z0 = b.mul(y0, r0)
    nze0 = b.fma(y0, nr0, z0)                         # -e
    z1a = b.mul(y1, r0)
    nze1 = b.fma(y1, nr0, z1a)
    ep0, ep1 = fast_two_sum(ONE, z0)
    z1b = b.mul(ep0, r1)
    nze2 = b.fma(ep0, b.neg(r1), z1b)
    zz, e_a = two_sum(z1a, z1b)
    zz, e_b = two_sum(zz, b.neg(nze0))
    lvl2 = b.sub(b.sub(b.add(b.add(e_a, e_b), b.mul(y2, r0)), nze1), nze2)
    ep1 = b.add(ep1, b.sub(z1a, nze0))
    lvl2 = b.fma(ep1, r1, lvl2)
    lvl2 = b.fma(ep0, r2, lvl2)
    half_r1 = b.mul(b.mul(r1, W("HALF", ce["HALF"])), ep0)
    lvl2 = b.fma(half_r1, r1, lvl2)
    Z0, Z1 = fast_two_sum(z0, zz)
    Z1, Z2 = fast_two_sum(Z1, lvl2)
    at(b, "exp-recon", "recon")
    Pa = b.mul(T0, Z0)
    nPa = b.fma(T0, b.neg(Z0), Pa)
    Pb = b.mul(T0, Z1)
    nPb = b.fma(T0, b.neg(Z1), Pb)
    Qa = b.mul(T1, Z0)
    nQa = b.fma(T1, b.neg(Z0), Qa)
    S0, s1 = fast_two_sum(T0, Pa)
    m, m1 = two_sum(s1, T1)
    m, m2 = two_sum(m, b.neg(nPa))
    m, m3 = two_sum(m, Pb)
    m, m4 = two_sum(m, Qa)
    l2_ = b.add(b.add(b.add(m1, m2), b.add(m3, m4)), T2)
    l2_ = b.sub(b.sub(l2_, nPb), nQa)
    l2_ = b.fma(T0, Z2, l2_)
    l2_ = b.fma(T1, Z1, l2_)
    l2_ = b.fma(T2, Z0, l2_)
    V0, V1 = fast_two_sum(S0, m)
    V1, V2 = fast_two_sum(V1, l2_)
    V0, V1 = fast_two_sum(V0, V1)

    # ---- the exact power of two, in-lane --------------------------------------
    at(b, "exact", "final")
    jz = b.icmplt(b.iand(tq, ib(N - 1)), INT1)
    ex = b.sel(b.cmpeq(rp, ZERO), ZERO, jz)
    ex = b.sel(b.cmpeq(t1, ZERO), ZERO, ex)
    ex = b.sel(b.cmpeq(r, ZERO), ZERO, ex)
    if sgnw is not None:
        V0, V1, V2 = (b.ixor(v, sgnw) for v in (V0, V1, V2))
    b.probes.update(V0=V0, V1=V1, V2=V2, Vh=V0, ex=ex)

    # ---- the final rounding and the in-lane test ------------------------------
    at(b, "test", "final")
    lo = ml._round_to_odd_add(b, V1, V2, INT1)
    R = b.add(V0, lo, rnd)
    aV0 = b.fabs(V0)
    ath = b.fabs(t0)
    Bv = b.mul(aV0, wB, RUP)
    lo_dn = ml._round_to_odd_add(b, V1, b.sub(V2, Bv, RDN), INT1)
    lo_up = ml._round_to_odd_add(b, V1, b.add(V2, Bv, RUP), INT1)
    R1 = b.add(V0, lo_dn, rnd)
    R2 = b.add(V0, lo_up, rnd)
    mk = b.ixor(R1, R2)
    if rnd in (RNE, RMM):
        g1 = b.add(V0, lo_dn, RUP)
        g2 = b.add(V0, lo_up, RDN)
        mk = b.sel(ONE, mk, b.cmple(g1, g2))
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)

    # ---- the fixed grid: a result that may be subnormal -----------------------
    at(b, "fixed-grid", "fixed-grid")
    Cu = sc.Cu if sgnw is None else b.ixor(sc.Cu, sgnw)
    Zg = b.add(Cu, V0)
    Wg = b.sub(Zg, Cu)
    zr = b.sub(V0, Wg)
    ro = ml._round_to_odd_add(b, zr, lo, INT1)
    Ws = b.sub(b.add(Zg, ro, rnd), Cu)
    if sgnw is not None:
        Ws = b.ior(Ws, sgnw)
    if sc.hu is not None:
        c1 = b.cmpeq(b.fabs(zr), sc.hu)
        c1 = b.sel(ONE, c1, b.cmpeq(zr, ZERO))
    else:
        c1 = b.cmpeq(zr, ZERO)
    smallo = b.cmple(b.fabs(lo), Bv)
    msub = b.sel(smallo, ZERO, c1)
    Wsel = b.sel(Ws, R, sc.sub_p)
    mk = b.sel(ONE, mk, b.sel(msub, ZERO, sc.sub_p))
    tn = b.sel(ONE, b.cmplt(b.fabs(R), ONE), sc.klt)
    tinyu = b.sel(tn, ZERO, sc.sub_p)

    # ---- the scaling, the flag word, the mark ---------------------------------
    at(b, "final", "final")
    Y1 = b.mul(Wsel, sc.S1)
    FIN = b.mul(Y1, sc.S2, rnd)
    ovf = b.cmpeq(b.mul(b.fabs(Y1), sc.S2, RUP), INF)
    fl = b.sel(OVFINX, b.sel(INXUNF, INX, tinyu), ovf)
    tinyt = b.icmplt(ath, W("TINYT", ml._pow2(fmt, -(p + 3))))
    mk = b.sel(ZERO, mk, tinyt)
    mk = b.sel(ZERO, mk, ex)
    if plant != "mark_silenced":
        fl = b.ior(fl, b.sel(MARKW, ZERO, mk))
    OFF = b.meta["OFF"]
    lowk = b.icmplt(sc.Ek, ib(fmt.emin - p + 1 + fmt.bias + OFF, "K_SUBMIN"))
    exrep = b.sel(b.sel(ZERO, b.sel(ZERO, ONE, lowk), ovf), ZERO, ex)
    fl = b.sel(ZERO, fl, exrep)
    bits = FIN

    # ---- the rule beside 1, transcend.py's own (m3pow.py's, copied) ----------
    at(b, "beside-1", "final")
    gt1 = b.icmplt(ONE, cl.ax)
    up = b.sel(b.sel(ZERO, ONE, yc.neg), yc.neg, gt1)
    one_m = 1 << (p - 1)

    def nbr(sign, away):
        return W(f"NB{sign}{int(away)}", sf.round_pack(
            fmt, sign, 8 * one_m + (1 if away else -1), -(p - 1) - 3,
            rnd)[0])
    nb = b.sel(nbr(0, True), nbr(0, False), up)
    if negres is not None:
        nb = b.sel(b.sel(nbr(1, True), nbr(1, False), up), nb, negres)
    side = b.sel(ZERO, tinyt, ex)
    bits = b.sel(nb, bits, side)
    fl = b.sel(INX, fl, side)
    b.probes.update(FIN=FIN, mk=mk, tinyt=tinyt)

    # ---- the screens and the specials ------------------------------------------
    at(b, "special", "special")

    def signed_pair(pos, neg):
        if negres is None:
            return W(f"W{pos:x}", pos)
        return b.sel(W(f"W{neg:x}", neg), W(f"W{pos:x}", pos), negres)
    ovfb = signed_pair(sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0],
                       sf.round_pack(fmt, 1, 3, fmt.emax, rnd)[0])
    unfb = signed_pair(sf.round_pack(fmt, 0, 1, fmt.emin - mw - 2, rnd)[0],
                       sf.round_pack(fmt, 1, 1, fmt.emin - mw - 2, rnd)[0])
    bits = b.sel(ovfb, bits, ovs)
    fl = b.sel(OVFINX, fl, ovs)
    bits = b.sel(unfb, bits, uns)
    fl = b.sel(INXUNF, fl, uns)
    if fn == "pow":
        bits, fl = M._pow_specials(b, k_, cl, yc, isint, sgnw, bits, fl, None)
    else:
        bits, fl = M._powr_specials(b, k_, cl, yc, bits, fl, None)
    b.label_of = b.label_of[:len(b.body)]
    return b.finish(bits, fl)


def run(bld, fn, lane, want=()):
    return M.run(bld, fn, lane, want)
