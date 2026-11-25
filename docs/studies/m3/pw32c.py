# M3 model: compound at fp32 as a triple word, the follow-up to pw32n.py
# (parcel M3XN2; scratch, not the tree's code, and nothing in the tree imports
# it). pw32n.py is imported and never edited. This file holds a COMPOUND-ONLY
# copy of pw32n.build's body, so that compound's logarithm (the "log-lowword"
# block and the "log-sum" cascade, the two places the budget's logarithm terms
# come from) can change without touching the function pown, rootn and compound
# share in pw32n.py.
#
# HOW THIS FILE RELATES TO pw32n.py (read it as a diff):
#   [pw32n]  the line is pw32n.build's, character for character (its pown and
#            rootn branches are cut out, which is the only other difference)
#   [NEW]    the line is this file's: the `variant` hooks
#   [CUT]    a comment where pw32n.build's pown / rootn lines were
# With variant None the fragment is pw32n.build's compound fragment, the same
# instructions in the same order (pw32c_run.py `same` shows the dag_digest and
# the instruction list equal at every n and attribute).
#
# VARIANTS (names are the change; "+" joins them):
#   None        the control: pw32n.build's compound
# (more are listed in VARIANTS below as they are added)

from fractions import Fraction

from m3core import ml, sf, RNE, RTZ, RDN, RUP, RMM, AN, FP32
import m3pow as M
import pw32
import pw32n
from pw32n import (fmt, N, GUARD, PHASE_MAP, PARTS, B1_FIRST, B2_FIRST,
                   y_words, n_words_needed, plan, static_proofs, _consts)

PLANTS = {k: v for k, v in pw32n.PLANTS.items()
          if k not in ("rootn_m0_neg",)}
FNS = ("compound",)
LW_PHASE = "lowword"        # the phase the low-word block is scheduled in
VARIANTS = {
    "sum2": "[NEW] the two plain sums of the logarithm's level 2 (log-sum's "
            "S2 and the 1/ln 2 product's Sk2) become compensated sums: a "
            "TwoSum chain whose errors, with the level-3 terms, are summed "
            "by plain adds and added once",
    "cross": "[NEW] the correction's low word gains the cross term "
             "rh * rho_l of rho^2 = (rh + rho_l)^2 (rho^2 / 2 was rh^2 / 2)",
    "yexact": "[NEW] rho_l = -nrho_l from exact products and a two-word "
              "residual e of the reciprocal (needs cexact): the rounding of "
              "yl and of rlh * yl, at 2^-24 of the correction's low word, "
              "gone",
    "early": "[NEW] the low word's block is built BEFORE the table's lookups "
             "(the same DAG, the instructions in another order: the three "
             "table words are not yet live while the block runs)",
    "rho3": "[NEW] the third-order term rho^3 / 3 enters the correction "
            "(dropped in pw32n; needs sum2: it is a level-3 term)",
    "cexact": "[NEW] the correction's low word is formed exactly: the "
              "product hrh * rh by TwoProd and its sum with rho_l by "
              "TwoSum, the errors level-3 terms (needs sum2 and cross)",
}


def comp_sum(b, terms, extra=()):
    """[NEW] a compensated sum of `terms` ([(ref, negated)], the first not
    negated): the TwoSum chain's sum, plus the plain sum of the chain's
    errors and of `extra` (level-3 terms, [(ref, negated)]), added ONCE. Its
    rounding is that of the one add and of the tail (2^-24 below)."""
    acc, es = ml._cascade(b, terms)
    tail = [(e, False) for e in es] + list(extra)
    if not tail:
        return acc
    return b.add(acc, ml._plain_sum(b, tail))


# short names for the two combinations the report recommends between
ALIASES = {
    "fixA": "sum2+cross+cexact+rho3",
    "fixB": "sum2+cross+cexact+yexact+rho3",
}


def variant_flags(variant):
    """the set of change names in `variant` (None: empty; an alias of ALIASES
    stands for its combination), each refused by name if unknown"""
    variant = ALIASES.get(variant, variant)
    fl = set() if variant is None else set(variant.split("+"))
    bad = fl - set(VARIANTS)
    if bad:
        raise ValueError(f"unknown variant {sorted(bad)}: "
                         f"{', '.join(VARIANTS) or 'none defined'}")
    return fl


def build(fn, rnd, n, G=GUARD, bound_shift=0, plant=None, B1=None, B2=None,
          GL=None, words=None, variant=None):
    """compound at fp32 under rnd at the integer operand n (a constant of the
    build), as a triple word, instrumented: pw32n.build's compound with
    `variant` (see VARIANTS). Other functions are refused by name."""
    if fn != "compound":                                           # [NEW]
        raise ValueError(f"pw32c builds compound only, not {fn!r}: pown "
                         f"and rootn are pw32n.build's")
    flags = variant_flags(variant)                                 # [NEW]
    if ("rho3" in flags or "cexact" in flags) and "sum2" not in flags:
        raise ValueError("variants rho3 and cexact need sum2: their terms "
                         "are level-3 terms of the compensated sum")
    if "yexact" in flags and "cexact" not in flags:
        raise ValueError("variant yexact needs cexact")
    if "cexact" in flags and "cross" not in flags:
        raise ValueError("variant cexact needs cross")
    if plant is not None and plant not in PLANTS:
        raise ValueError(f"unknown plant {plant!r}: {', '.join(PLANTS)}")
    if not -2 ** 63 <= n <= 2 ** 63 - 1:
        raise ValueError(f"{fn}: n = {n} is outside int64")
    if n in (0, 1):
        if plant is not None:
            raise ValueError(f"plant {plant!r} does not apply at n = {n}")
        return M.build_small(fn, fmt, rnd, n)          # Refused for rootn 0
    p, mw = fmt.prec, fmt.man_w
    G, GL, plog, pexp = plan(G, GL)
    ws = y_words(fn, n, words)
    # the plants that act on the words
    if plant == "n_word_ulp":
        ws[0] += 1
    if plant == "n_low_dropped":
        if len(ws) < 2:
            raise ValueError(f"n_low_dropped does not apply at n = {n}: "
                             f"n has one word")
        ws = ws[:1]
    if plant == "n_word3_dropped":
        if len(ws) < 3:
            raise ValueError(f"n_word3_dropped does not apply at n = {n}: "
                             f"Y has {len(ws)} words")
        ws = ws[:2]
    truncated = plant in ("n_word_ulp", "n_low_dropped", "n_word3_dropped") \
        or (words is not None and words < n_words_needed(fn, n))
    proofs = static_proofs(fn, n, G, GL, plog, pexp, ws, truncated)
    B1 = B1_FIRST if B1 is None else Fraction(B1)
    B2 = B2_FIRST if B2 is None else Fraction(B2)
    if plant == "b1_dropped":
        B1 = Fraction(0)
    cl_, ce = _consts(fn, G, GL, plog, pexp)
    b = M.PBuild(fmt, rnd, f"{fn}-fp32-{AN[rnd]}-tw-n{n}")
    b.inputs = ("a",)                                              # [NEW]
    b.meta.update(fn=fn, G=G, GL=GL, GE=G, KL=plog, KE=pexp, B1=B1, B2=B2,
                  plant=plant, family="triple word", N=N, shift=bound_shift,
                  proofs=proofs, n=n, ywords=len(ws))
    k_ = ml._words_common(b)
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    INF, QNAN = k_["INF"], k_["QNAN"]
    INX, INXUNF, OVFINX = k_["INX"], k_["INXUNF"], k_["OVFINX"]
    MARKW = k_["MARKW"]
    INVALID = k_["INVALID"]                                        # [NEW]
    DIVZ = ib(sf.FLAG_DIVZERO, "FL_DIVZERO")                       # [NEW]
    SIGN = ib(fmt.sign_mask, "SIGN_BIT")
    MANW = ib(mw, "MANTISSA_WIDTH")                                # [NEW]
    two_sum, fast_two_sum = b.two_sum, b.fast_two_sum
    at = M._at

    def W(name, bits):
        return b.word(bits, name)

    # ---- classify ----------------------------------------------------------
    at(b, "classify", "classify")
    cl = ml._classify_common(b, k_)
    x = cl.x

    # ---- the sign, and Y in words [NEW; pw32 has pow's integrality here] -----
    at(b, "front", "front")
    negres = None            # [CUT] pown's and rootn's odd-n sign; none here
    sgnw = None
    Yw = [W(f"N{i}", w) for i, w in enumerate(ws)]                # [NEW]

    # ---- the logarithm: L = log2 X in three words -----------------------------
    at(b, "log-reduce", "reduce")
    red = ml._log_reduce(b, "log1p", cl_, k_, cl, None)            # [NEW]
    if plant == "compound_onep_rounded":
        red.ul = ZERO
    r, kf = red.r, red.kf                                          # [pw32]
    def do_table():
        at(b, "log-table", "table")
        return ml._table(b, cl_, red.tc, k_,
                         tuple(lambda j, i=i: f"L{j}_{i}"
                               for i in range(3)))                 # [pw32]
    if "early" not in flags:
        t0_, t1_, t2_ = do_table()                                 # [pw32n]
    corr_h = corr_l = None
    corr_ll = []                                                   # [NEW]
    if True:                       # [pw32n] was `if fn == "compound":`
        # [NEW] M1's triple-word log1p low word (mathlib._build_log_tw,
        # "lowword" phase, copied; GL is its G): rho = r_l / (1 + r) with
        # r_l = u_l 2^-k c, as a double word, and log1p of it, rho - rho^2/2
        at(b, "log-lowword", LW_PHASE)
        p2mk = b.ishl(b.isub(ib(fmt.bias + cl_["MAGIC"], "K_BIAS_MAGIC"),
                             red.kb), MANW)
        p2mk = b.sel(ZERO, p2mk, b.icmplt(
            ib(cl_["MAGIC"] + p + GL + 2, "K_CLAMP"), red.kb))
        ul2 = b.mul(red.ul, p2mk)
        rlh = b.mul(ul2, red.cc)
        nrle = b.fma(ul2, b.neg(red.cc), rlh)
        nr0 = b.neg(r)
        y = b.sub(ONE, r)
        for _ in range(2):
            e = b.fma(nr0, y, b.sub(ONE, y))
            y = b.fma(y, e, y)
        n3 = []              # [NEW] level-3 terms of nrho_l (yexact): (ref,
        if "yexact" not in flags:       # negated in the sum nrho_l = ...)
            e = b.fma(nr0, y, b.sub(ONE, y))                      # [pw32n]
            yl = b.mul(y, e)
            rh = b.mul(rlh, y)
            nre = b.fma(rlh, b.neg(y), rh)
            w1 = b.fma(nrle, y, nre)
            nrho_l = b.fma(b.neg(rlh), yl, w1)
        else:
            # [NEW] nrho_l = nre + nrle y - rlh yl with every product exact
            # (TwoProd) and the residual e = 1 - (1 + r) y kept as two
            # words, so that no rounding of the 2^-24 word's size is left
            omy = b.sub(ONE, y)                          # exact (Sterbenz)
            ph_ = b.mul(nr0, y)
            pe_ = b.fma(nr0, y, b.neg(ph_))
            e_h, se_ = two_sum(omy, ph_)
            e_l = b.add(se_, pe_)
            yh = b.mul(y, e_h)
            ye = b.fma(y, e_h, b.neg(yh))
            yel = b.mul(y, e_l)
            rh = b.mul(rlh, y)
            nre = b.fma(rlh, b.neg(y), rh)
            pb = b.mul(nrle, y)
            pbe = b.fma(nrle, y, b.neg(pb))
            qh = b.mul(rlh, yh)
            qe = b.fma(rlh, yh, b.neg(qh))
            nrho_l, e3 = ml._cascade(b, [(nre, False), (pb, False),
                                         (qh, True)])
            n3 = ([(e, False) for e in e3] + [(pbe, False), (qe, True),
                  (b.mul(rlh, ye), True), (b.mul(rlh, yel), True)])
        hrh = b.mul(rh, b.const("HALF", cl_["HALF"]))
        corr_h = rh
        corr_ll = []                                  # [NEW] level-3 terms
        if "cexact" in flags:
            # [NEW] corr_l exactly: hrh * rh = ph + pe (TwoProd), ph + nrho_l
            # = corr_l + se (TwoSum); pe and se are level 3
            ph = b.mul(hrh, rh)
            pe = b.fma(hrh, rh, b.neg(ph))
            corr_l, se = two_sum(ph, nrho_l)
            corr_ll += [(pe, True), (se, True)]   # held negated
        else:
            corr_l = b.fma(hrh, rh, nrho_l)               # [pw32n]
        if "cross" in flags:
            # rho = rh + rho_l with rho_l = -nrho_l: rho^2 / 2 gains rh *
            # rho_l, held negated like corr_l: corr_l - rh * nrho_l
            if "cexact" in flags:
                ce_ = b.mul(rh, nrho_l)                   # a level-3 product
                corr_ll.append((ce_, False))
            else:
                corr_l = b.fma(b.neg(rh), nrho_l, corr_l)
        # nrho_l's level-3 terms (held negated like nrho_l itself)
        corr_ll += [(v, not ng) for v, ng in n3]                   # [NEW]
        if "rho3" in flags:
            # + rho^3 / 3 (rh = rho to 2^-24), a contribution as it stands
            cube = b.mul(b.mul(rh, rh), b.mul(rh, b.const(
                "THIRD", ml._enc(fmt, Fraction(1, 3)))))
            corr_ll.append((cube, False))
        if "early" in flags:                                       # [NEW]
            t0_, t1_, t2_ = do_table()
        sm = b.icmplt(cl.ax, b.const("SMALL", cl_["SMALL"]))
        r = b.sel(x, r, sm)
        kf = b.sel(ZERO, kf, sm)
        t0_, t1_, t2_ = (b.sel(ZERO, w, sm) for w in (t0_, t1_, t2_))
        corr_h, corr_l = b.sel(ZERO, corr_h, sm), b.sel(ZERO, corr_l, sm)
        corr_ll = [(b.sel(ZERO, v, sm), ng) for v, ng in corr_ll]  # [NEW]
    nr = b.neg(r)                                                  # [pw32]
    y0, y1, y2 = pw32._poly3(b, cl_, *plog, r, nr, "L", "log")     # [pw32]
    at(b, "log-Z", "Z")
    P0 = b.mul(y0, r)                                              # [pw32]
    nE0 = b.fma(y0, nr, P0)                                        # [pw32]
    P1 = b.mul(y1, r)
    nE1 = b.fma(y1, nr, P1)
    P2 = b.mul(y2, r)
    at(b, "log-sum", "recon")
    F0s, Ea = fast_two_sum(t0_, P0)                                # [pw32]
    lv1 = [(Ea, False), (t1_, False), (nE0, True), (P1, False)]    # [pw32]
    lv2 = [(P2, False), (nE1, True), (t2_, False)]                 # [pw32]
    if corr_h is not None:                                         # [NEW]
        lv1.append((corr_h, False))
        lv2.append((corr_l, True))                  # held negated
    S1, errs = ml._cascade(b, lv1)
    if "sum2" in flags:                                            # [NEW]
        S2 = comp_sum(b, lv2 + [(e, False) for e in errs], corr_ll)
    else:
        S2 = ml._plain_sum(b, lv2 + [(e, False) for e in errs])    # [pw32n]
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
    Sk0, Ek_ = fast_two_sum(kf, g0)
    Sk1, errs = ml._cascade(b, [(Ek_, False), (ng0, True), (g1, False),
                                (g2, False)])
    sk2t = [(q2, False), (q1, False), (q0, False), (ng2, True),
            (ng1, True)] + [(e, False) for e in errs]
    if "sum2" in flags:                                            # [NEW]
        Sk2 = comp_sum(b, sk2t)
    else:
        Sk2 = ml._plain_sum(b, sk2t)                               # [pw32n]
    L0, L1 = fast_two_sum(Sk0, Sk1)
    L1, L2 = fast_two_sum(L1, Sk2)
    L0, L1 = fast_two_sum(L0, L1)
    if plant == "l3_dropped":
        L2 = ZERO
    b.probes.update(L0=L0, L1=L1, L2=L2, r=r)

    # ---- t = Y L in three words [NEW: Y in up to three words] ------------------
    # level 0 (Y0 L0) and 1 (Y0 L1, Y1 L0) by TwoProd, level 2 (Y0 L2, Y1 L1,
    # Y2 L0) rounded, level 3 and below dropped (2^-72 of t, the logarithm's
    # own floor). With ONE word of Y the body is pw32's, instruction for
    # instruction.
    at(b, "product", "reduce")
    nL0, nL1 = b.neg(L0), b.neg(L1)
    Y0 = Yw[0]
    Q0 = b.mul(Y0, L0)
    pnE0 = b.fma(Y0, nL0, Q0)                         # -(the error of Q0)
    Q1 = b.mul(Y0, L1)
    pnE1 = b.fma(Y0, nL1, Q1)
    Q2 = b.mul(Y0, L2)
    th0 = Q0
    if len(Yw) == 1:
        u0, u1 = b.two_diff(Q1, pnE0)                 # e0 + Q1 = u0 + u1
        lv2_ = b.sub(b.add(Q2, u1), pnE1)             # Q2 + u1 + e1
        t0, tc1 = fast_two_sum(Q0, u0)                # |Q0| >= |u0|
        t1, t2 = two_sum(tc1, lv2_)
    else:
        Y1 = Yw[1]
        R10 = b.mul(Y1, L0)
        pnE10 = b.fma(Y1, nL0, R10)
        R11 = b.mul(Y1, L1)
        lv2t = [(R11, False), (Q2, False)]
        if len(Yw) > 2:
            lv2t.insert(0, (b.mul(Yw[2], L0), False))
        # level 1: Q1 + Y1 L0 + e0 by a TwoSum chain (exact), the errors fall
        # to level 2 with the TwoProd errors of the level-1 products
        S1p, errsp = ml._cascade(b, [(Q1, False), (R10, False),
                                     (pnE0, True)])
        S2p = ml._plain_sum(b, lv2t + [(pnE1, True), (pnE10, True)]
                            + [(e, False) for e in errsp])
        t0, t1 = fast_two_sum(Q0, S1p)
        t1, t2 = fast_two_sum(t1, S2p)
        t0, t1 = fast_two_sum(t0, t1)
    b.probes.update(th0=th0, t0=t0, t1=t1, t2=t2)
    # the screens, on the rounded product (an overflowed product is +-inf)
    hi_t = fmt.emax + 2
    ovs = b.cmple(W("TOVF", ml._enc_exact(fmt, hi_t)), th0)
    uns = b.cmple(th0, W("TUNF", ml._enc_exact(fmt, fmt.emin - p - 2)))

    # ---- the bound's coefficient w: Bv = |V0| w ------------------------------
    at(b, "test", "head2")
    sh = bound_shift
    wB = W("BREL", ml._pow2(fmt, -(p + G) + sh))                   # [pw32]
    if B1:
        wB = b.fma(b.fabs(t0), W("B1", ml._enc(fmt, B1 * 2 ** sh)), wB, RUP)
    if B2:
        # [NEW] |Y k| is |k| times |n|, a constant: the double word's YB2
        ay = Fraction(abs(n))
        wB = b.fma(b.fabs(kf), W("YB2", M._enc_up(fmt, ay * B2 * 2 ** sh)),
                   wB, RUP)

    # ---- 2^t: M1's fp32 exp2 with a three-word argument [pw32, unchanged] ------
    at(b, "exp-reduce", "reduce")
    MAGIC = W("MAGIC", ce["MAGIC"])
    tq = b.fma(t0, W("EIGHT", ce["EIGHT"]), MAGIC)
    nf = b.sub(tq, MAGIC)
    rp = b.fma(nf, W("NINV8", ce["NINV8"]), t0)       # t0 - n/8: exact
    a0, a1 = fast_two_sum(rp, t1)
    R1_, R2_ = two_sum(a1, t2)
    R0_ = a0
    LN0, LN1, LN2 = (b.const(f"LN2_{i}", ce[f"LN2_{i}"]) for i in range(3))
    NLN0, NLN1 = (b.const(f"NLN2_{i}", ce[f"NLN2_{i}"]) for i in range(2))
    c00 = b.mul(R0_, LN0)
    n00 = b.fma(R0_, NLN0, c00)
    c01 = b.mul(R0_, LN1)
    n01 = b.fma(R0_, NLN1, c01)
    c10 = b.mul(R1_, LN0)
    n10 = b.fma(R1_, NLN0, c10)
    d02, d11, d20 = b.mul(R0_, LN2), b.mul(R1_, LN1), b.mul(R2_, LN0)
    s0, E1 = fast_two_sum(c00, c01)
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
    y0, y1, y2 = pw32._poly3(b, ce, *pexp, r0, nr0, "E", "exp")
    at(b, "exp-Z", "Z")
    z0 = b.mul(y0, r0)
    nze0 = b.fma(y0, nr0, z0)
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

    # ---- the exact power of two, in-lane ---------------------------------------
    at(b, "exact", "final")
    jz = b.icmplt(b.iand(tq, ib(N - 1)), INT1)
    ex = b.sel(b.cmpeq(rp, ZERO), ZERO, jz)
    # [NEW] the t_l = 0 test: pw32's; compound adds u_l = 0 (m3pow.py)
    if plant != "exact_rule_no_tl":
        ex = b.sel(b.cmpeq(t1, ZERO), ZERO, ex)
    ex = b.sel(b.cmpeq(r, ZERO), ZERO, ex)                         # [pw32]
    ex = b.sel(b.cmpeq(red.ul, ZERO), ZERO, ex)
    b.probes.update(V0=V0, V1=V1, V2=V2, Vh=V0, ex=ex)

    # ---- the final rounding and the in-lane test [pw32, unchanged] ---------------
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

    # ---- the fixed grid [pw32, unchanged] ---------------------------------------
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

    # ---- the scaling, the flag word, the mark [pw32, unchanged] -----------------
    at(b, "final", "final")
    Y1_ = b.mul(Wsel, sc.S1)
    FIN = b.mul(Y1_, sc.S2, rnd)
    ovf = b.cmpeq(b.mul(b.fabs(Y1_), sc.S2, RUP), INF)
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

    # ---- the rule beside 1: m3pow.py's, for the three [NEW: `up` by function] ----
    at(b, "beside-1", "final")
    gt1 = b.icmplt(ONE, cl.ax)
    up = cl.neg if n < 0 else b.sel(ZERO, ONE, cl.neg)  # 1 + x > 1 iff x > 0
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

    # ---- the screens and the specials ---------------------------------------------
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
    # [NEW] the n-keyed rows: m3pow.build's, copied (its lines 601 to 641),
    # with n_row_loud (the x = +-inf row's inexact flag left raised)
    loud = INX if plant == "n_row_loud" else ZERO

    # [CUT] pown's and rootn's rows
    if True:
        NEGONE = W("NEGONE", sf.one_bits(fmt, 1))
        bits = b.sel(INF if n > 0 else ZERO, bits, cl.isinf)
        fl = b.sel(loud, fl, cl.isinf)
        bits = b.sel(ONE, bits, cl.iszero)
        fl = b.sel(ZERO, fl, cl.iszero)
        m1 = b.cmpeq(x, NEGONE)
        bits = b.sel(ZERO if n > 0 else INF, bits, m1)
        fl = b.sel(DIVZ if n < 0 else ZERO, fl, m1)
        below = b.cmplt(x, NEGONE)
        bits = b.sel(QNAN, bits, below)
        fl = b.sel(INVALID, fl, below)
        bits = b.sel(QNAN, bits, cl.isnan)
        fl = b.sel(b.sel(INVALID, ZERO, cl.issnan), fl, cl.isnan)
    b.label_of = b.label_of[:len(b.body)]
    return b.finish(bits, fl)


def run(bld, fn, lane, want=()):
    """A lane is (x, n); the build is keyed by n, so x alone is run."""
    x = lane[0] if isinstance(lane, tuple) else lane
    return bld.run(x, want)
