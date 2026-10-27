# M2X: fp32's sin, cos and tan as a TRIPLE word at G = 40, built in the
# study's model (scratch; not the tree's code, and nothing in the tree
# imports it). The study's 2.7 sketched this and called it an ESTIMATE;
# this builds it. NEW FILE: no existing file of docs/studies/m2/ changed.
#
# The shape (m2trig.py's, with the double word's two places widened):
#   reduce   m2red.reduce_ph's setup, window, products and coarse sum
#            (copied, b = 16, L = 9), then a mid sum cut at TWO fixed
#            boundaries into an UPPER group (bits from 2^BMID up, reduced
#            modulo U as the double word's mid sum was), a LOWER group (the
#            bits from 2^BOTTOM to 2^BMID, a pure fraction) and the LOWS
#            (below the bottom, a double word that may round); each of the
#            first two an exact double word by the greedy of design A
#            (static proofs, TwoSum where a plain add is not provable); the
#            lower group's high word then gives up its multiple of 2^BMID to
#            the upper group (the carry, exact), so that no cancellation is
#            left between the two; and the six words are turned into a
#            triple word t by two VecSum passes. r = t pi/2 in three words
#   z        r_0^2 exactly, as a double word
#   S, C     Taylor in z: a single-word tail, double-word steps, then
#            triple-word steps where a double word's rounding would reach
#            2^-(p+G+3) (plan_tw_poly, in exact rationals, plan_exp32's rule)
#   sin, cos r_0 S and C in three words, then r's lower words by the
#            derivative to second order (cos(r_0) d - sin(r_0) d^2/2 for sin,
#            -sin(r_0) d - cos(r_0) d^2/2 for cos; d = r_1 + r_2)
#   select   by the quadrant and the sign, three words; tan's quotient in
#            three words by a long division with exact remainders
#   final    R = rnd(V0 + RO(V1 + V2)) and the in-lane test through
#            round-to-odd (mathlib.py:1892 to 1902), Bv = 2^-(p+G) |V0|; the
#            clamp (m2trig.py:234 to 245); the classification late and the
#            specials (m2trig.py:250 to 289)
# Every instruction the reduction calls exact is recorded for m2red.audit;
# every static proof is asserted with a message that names it, at build
# time, before any lane runs.

import math
from fractions import Fraction

from m2core import (Frag, FORMATS, sf, enc, enc_exact, dec, pow2_bits,
                    words_of, RNE, RTZ, RDN, RUP, RMM)
from m2const import sin_coef, cos_coef, pi_frac, pio2_words
from m2plan import plan_b, LOST
from m2red import SV, exact, data, add_exact, build_window, _lg
from m2trig import gates

FMT = FORMATS["fp32"]
G_TW = 40                     # the guard: Logan's for M1's fp32 library
B_TW = 16                     # chunk width: the widest whose coarse sum is exact
BMID_TW = -20                 # the boundary between the upper and the lower group
PLANTS = ("r2-dropped", "carry-dropped", "mark-silenced")
# rho, the polynomials' domain |r| <= rho = pi/4 (1 + over), is NOT the study's
# 2^-30 (which fails at fp32: the float 0x3f490fdb, just above pi/4, takes n = 0
# by the tie, 2^-25.10 over; and the double word's quadrant count, which leaves
# out the mid sum's low word, overshoots by 2^-17.09 at 0x44264edd: M2G1's
# findings, the lead's messages of 2026-10-27). `over` is COMPUTED in
# reduce_tw from the static magnitudes of what the last quadrant step does not
# see, in M2G1's form 2^(1-p) + 4 |lower terms| (derivation there), and the
# plan of the polynomials is made at that rho.


def proof(f, cond, name, detail=""):
    """A static proof: asserted at build time, with its name; the ones that
    held are listed in f.meta["proofs"]."""
    if not cond:
        raise AssertionError(f"static proof '{name}' fails: {detail}")
    f.meta.setdefault("proofs", []).append(name)


def _upper(q, bits=96):
    """q rounded UP to a dyadic rational of `bits` fractional bits: an upper
    bound that keeps the plan's exact rational arithmetic small."""
    return Fraction(-((-q.numerator * 2 ** bits) // q.denominator), 2 ** bits)


def stated(cond, name, detail=""):
    """A static proof outside a fragment (the plan's)."""
    if not cond:
        raise AssertionError(f"static proof '{name}' fails: {detail}")


# ---- the plan --------------------------------------------------------------

def tw_plan(fmt=FMT, G=G_TW, b=B_TW, bmid=BMID_TW):
    """The reduction's parameters at fp32 for the triple word: m2plan.plan_b
    at an explicit b, with the coarse sum's exactness asserted by name (the
    double word's plan() searches b downward for it; here the widest b that
    holds is b = 16: b = 17 puts P_1's grid at 2^-6 and the proof below fails,
    shown by name in the driver's guard mode), and the boundary between the
    two exact groups."""
    p = fmt.prec
    gs, gc = gates(fmt)
    P = plan_b(fmt, G, LOST[fmt.name], fmt.emax, min(gs, gc) - 1, b=b)
    pg1 = P.rows[1][3]
    stated(math.log2(3) + P.b - min(0, pg1) < p, "coarse-sum exact",
           f"3 terms of at most 2^{P.b} on P_1's grid 2^{pg1} need "
           f"{math.log2(3) + P.b - min(0, pg1):.2f} bits, past p = {p}")
    P.bmid = bmid
    # the upper group's span and the lower group's, in bits: each must fit
    # a double word with room (the greedy proves its own sums piece by piece)
    P.span_upper = (b - 3) - bmid
    P.span_lower = bmid - P.bottom
    stated(P.span_upper <= 2 * p - 4 and P.span_lower <= 2 * p - 4,
           "groups fit a double word",
           f"upper {P.span_upper} bits, lower {P.span_lower} bits, "
           f"double word {2 * p}")
    return P


# ---- counted error-free transformations (this file's) ----------------------

def two_diff(f, a, c):
    """(s, e), s + e = a - c exactly (Knuth's TwoSum of a and -c), 6."""
    f.meta["two_sum"] += 1
    s = f.sub(a, c)
    a1 = f.add(s, c)
    b1 = f.sub(s, a1)
    da = f.sub(a, a1)
    dc = f.add(c, b1)
    return s, f.sub(da, dc)


def f2s(f, a, b, claim=True):
    """Fast2Sum, 3, with its ordering claim audited: the two subtractions are
    exact when |a| >= |b| (or a = 0), so they are listed as exact claims and
    m2red.audit checks them lane by lane."""
    f.meta["fast_two_sum"] += 1
    s = f.add(a, b)
    z = f.sub(s, a)
    e = f.sub(b, z)
    if claim:
        exact(f, z)
        exact(f, e)
    return s, e


def tprod(f, a, na, b):
    """(p, ne): p = a b rounded, ne = p - a b = -(the exact error), by one
    MUL and one FMA; `na` is -a."""
    f.meta["two_prod"] += 1
    p = f.mul(a, b)
    return p, f.fma(na, b, p)


# ---- the reduction ----------------------------------------------------------

def sum_exact(f, pieces, label, plant_carry=False):
    """The exact sum of SV pieces as a double word (h, lw|None), by design A's
    greedy: largest first; a piece goes into the low word where that sum is
    provably exact (SV bounds), else into the high word where that is, else
    by TwoSum, the error word then added to the low word. Every plain add
    is built only when its static proof holds (m2red.add_exact), every
    failure of a proof is asserted by name. `plant_carry` builds the
    carry-dropped plant: the first TwoSum a plain add, still claimed exact."""
    p = f.fmt.prec
    pieces = sorted([v for v in pieces if v is not None], key=lambda v: -v.mag)
    if not pieces:
        return None, None
    h, lw = pieces[0], None
    planted = not plant_carry
    for v in pieces[1:]:
        if lw is not None:
            s = add_exact(f, lw, v, p)
            if s is not None:
                lw = s
                continue
        s = add_exact(f, h, v, p)
        if s is not None:
            h = s
            continue
        g = min(h.grid, v.grid)
        mag = _lg(2 ** h.mag + 2 ** v.mag)
        if not planted:
            planted = True               # the plant: a plain add, the error dropped
            h = SV(exact(f, f.add(h.ref, v.ref)), mag, g)
            continue
        ss, ee = f.two_sum(h.ref, v.ref)
        h = SV(ss, mag, g)
        ev = SV(ee, mag - p, g)
        if lw is None:
            lw = ev
        else:
            lw2 = add_exact(f, lw, ev, p)
            proof(f, lw2 is not None, f"{label}: low word + TwoSum error exact",
                  f"lw (mag {lw.mag:.2f}, grid {lw.grid}) + e (mag {ev.mag:.2f}, "
                  f"grid {ev.grid}) is not provably one word")
            lw = lw2
    return h, lw


def to_triple(f, terms):
    """The exact sum of the float `terms` (smallest first, by their static
    magnitudes) as a triple word (t0, t1, t2): VecSum from the bottom (every
    TwoSum exact), VecSum again over the errors, the second pass's errors
    added (plain; their rounding is below 2^-72 of t), then renormalised:
    Fast2Sum(s, u) with its claim audited, TwoSum for the rest."""
    s = terms[0]
    errs = []
    for a in terms[1:]:
        s, e = f.two_sum(a, s)
        errs.append(e)
    u = errs[0]
    qs = []
    for e in errs[1:]:
        u, q = f.two_sum(e, u)
        qs.append(q)
    lv2 = qs[0]
    for q in qs[1:]:
        lv2 = f.add(lv2, q)
    t0, w = f2s(f, s, u)
    t1, t2 = f.two_sum(w, lv2)
    return t0, t1, t2


def reduce_tw(f, x, P, magic_ref, plant=None):
    """Append the triple-word reduction to f. -> dict(r0, r1, r2, q, small)."""
    fmt = f.fmt
    p, mw, bias = fmt.prec, fmt.man_w, fmt.bias
    b, L = P.b, P.L
    BM, BT = P.bmid, P.bottom
    ZERO = f.w(0, "ZERO")
    MAGIC = Fraction(3, 2) * 2 ** (p - 1)
    MAGIC_B = enc_exact(fmt, MAGIC)
    f.meta.update(b=b, L=L, bmid=BM, bottom=BT, budget=P.budget,
                  K_words=P.K, Z=P.Z)

    # ---- setup, window: m2red.reduce_ph's, as it is ----------------------
    f.phase = "red-setup"
    Eb = f.ishr(f.iand(x, f.wi(fmt.exp_mask << mw)), f.wi(mw))
    Ebm = f.ior(Eb, magic_ref)
    G0p = exact(f, f.sub(Ebm, f.wx(MAGIC + bias + p + 1 - 2 + b)))
    y = f.fma(G0p, f.wv(Fraction(1, b)), f.wv(Fraction(2 * b - 3, 2 * b)))
    gm1m = data(f, f.add(y, magic_ref, RDN))
    shift = f.iadd(gm1m, f.wi(P.Z))
    f.phase = "red-window"
    win = build_window(f, P, shift)
    f.phase = "red-setup"
    gm1 = exact(f, f.sub(gm1m, magic_ref))
    sig = exact(f, f.fma(gm1, f.wx(-b), G0p))
    sigm = exact(f, f.add(sig, magic_ref))
    V = f.ishl(f.isub(sigm, f.wi(MAGIC_B - bias)), f.wi(mw))        # 2^sigma
    U = f.isub(f.wi((2 * bias) << mw), V)                           # 2^-sigma
    m = f.iadd(U, f.wi(2 << mw))                                    # 4U
    inv_m = f.isub(V, f.wi(2 << mw))                                # V/4
    f.probes.update(sig=sig, V=V, U=U, gm1=gm1)
    M = f.ior(f.iand(x, f.wi(fmt.man_mask)), f.wi((bias + p - 1) << mw))
    nM = f.ixor(M, f.wi(fmt.sign_mask))

    # ---- products (lazily: position j when its first piece is wanted) ----
    rows = {r[0]: r for r in P.rows}
    need = P.budget - 3
    cache = {}

    def product(j, phase):
        """(P_j, rho_j) as SVs (rho_j None where its bound is under the
        need), or None where position j holds no chunk in any bucket."""
        if j in cache:
            return cache[j]
        keep, f.phase = f.phase, phase
        Wj = win[j] if j == 0 else exact(
            f, f.mul(win[j], f.wx(Fraction(1, 2 ** (j * b)))))
        _j, lmin, lmax, pgrid, rhomag, rhogrid = rows[j]
        if lmax is None:
            res = None
        else:
            Pj = f.mul(M, Wj)
            if rhomag > need:                       # the low word counts
                f.meta["two_prod"] += 1
                nrho = exact(f, f.fma(nM, Wj, Pj))
                rho = f.neg(nrho)
                # |rho| <= ulp(P)/2: one bit tighter than m2red's ulp bound
                res = (SV(Pj, lmax + 1e-9, pgrid), SV(rho, rhomag - 1.0, rhogrid))
            else:
                res = (SV(Pj, lmax + 1e-9, pgrid), None)
        f.phase = keep
        cache[j] = res
        return res

    f.phase = "red-products"
    prods = {0: product(0, "red-products"), 1: product(1, "red-products")}

    # ---- coarse: m2red's, as it is ----------------------------------------
    f.phase = "red-coarse"
    nqs = []

    def mod_m(v, guard=False):
        q = data(f, f.fma(v.ref, inv_m, magic_ref))
        nq = exact(f, f.sub(magic_ref, q))
        r = exact(f, f.fma(nq, m, v.ref))
        if guard:
            thr = f.iadd(m, f.wi((p - 1) << mw))
            small = f.cmplt(f.fabs(v.ref), thr)
            r = f.sel(r, ZERO, small)
        return SV(r, min(v.mag, b + 0.0), min(v.grid, 1))

    P0, rho0 = prods[0]
    P1, rho1 = prods[1]
    f.phase = "red-coarse"
    coarse = [mod_m(P0, guard=True)]
    if rho0 is not None:
        coarse.append(mod_m(rho0))
    coarse.append(mod_m(P1))
    VI = coarse[0]
    for c in coarse[1:]:
        VI2 = add_exact(f, VI, c, p)
        proof(f, VI2 is not None, "coarse sum exact (P0, rho0, P1 mod m)",
              f"mag {_lg(2 ** VI.mag + 2 ** c.mag):.2f}, grid {min(VI.grid, c.grid)}")
        VI = VI2
    q1 = data(f, f.fma(VI.ref, V, magic_ref))
    nk1 = exact(f, f.sub(magic_ref, q1))
    fI = exact(f, f.fma(nk1, U, VI.ref))                # |fI| <= U/2
    nqs.append(nk1)
    fI_sv = SV(fI, b - 3.0, VI.grid)
    proof(f, fI_sv.mag - fI_sv.grid < p, "f_I = V_I - k U exact",
          f"|f_I| <= 2^{fI_sv.mag} on grid 2^{fI_sv.grid}")
    f.probes.update(fI=fI)

    # ---- the mid pieces, routed to the groups ----------------------------
    f.phase = "red-mid"

    def split(v, B):
        """v cut at 2^B by a magic number: hi (a multiple of 2^B), lo
        (|lo| <= 2^(B-1)); both exact."""
        proof(f, v.mag < p - 2 + B, f"split at 2^{B}: magic in range",
              f"|v| < 2^{v.mag:.2f} against 2^{p - 2 + B}")
        MQ = f.wx(Fraction(3, 2) * 2 ** (p - 1 + B))
        hi = exact(f, f.sub(data(f, f.add(v.ref, MQ)), MQ))
        lo = exact(f, f.sub(v.ref, hi))
        return (SV(hi, _lg(2 ** v.mag + 2 ** (B - 1)), B),
                SV(lo, B - 1.0, v.grid))

    upper, lower, lows = [], [], []

    def route(v):
        if v is None:
            return
        if v.grid >= BM:
            upper.append(v)
            return
        if v.mag <= BM - 1:
            rest = v
        else:
            hi, rest = split(v, BM)
            upper.append(hi)
        if rest.grid >= BT:
            lower.append(rest)
        elif rest.mag < BT:
            lows.append(rest)
        else:
            hi, lo = split(rest, BT)
            lower.append(hi)
            lows.append(lo)

    def route_position(j, phase):
        pr = product(j, phase)
        if pr is None:
            return
        Pj, rhoj = pr
        if Pj.mag >= -1:                                # may carry quadrant bits
            Pj = mod_m(Pj)
            Pj.mag = min(Pj.mag, pr[0].mag)
        route(Pj)
        route(rhoj)

    route(rho1)
    for j in (2, 3):
        route_position(j, "red-products")

    # ---- the upper group: an exact double word, modulo U, with f_I -------
    hu, lwu = sum_exact(f, upper, "upper group", plant_carry=(plant == "carry-dropped"))
    proof(f, hu is not None, "upper group not empty")
    q2 = data(f, f.fma(hu.ref, V, magic_ref))
    nk2 = exact(f, f.sub(magic_ref, q2))
    h2 = SV(exact(f, f.fma(nk2, U, hu.ref)), min(hu.mag, b - 3.0 + 1e-9), hu.grid)
    nqs.append(nk2)
    s, e = f.two_sum(fI, h2.ref)
    s_sv = SV(s, _lg(2 ** fI_sv.mag + 2 ** h2.mag), min(fI_sv.grid, h2.grid))
    e_sv = SV(e, s_sv.mag - p, s_sv.grid)
    if lwu is not None:
        e_sv = add_exact(f, e_sv, lwu, p)
        proof(f, e_sv is not None, "e + low word of the upper group exact")

    # ---- the low positions' products, then the lower group ----------------
    for j in range(4, L):
        route_position(j, "red-products-low")
    f.meta["pieces"] = {"upper": len(upper), "lower": len(lower), "lows": len(lows)}
    f.phase = "red-mid"
    hl, lwl = sum_exact(f, lower, "lower group")
    proof(f, hl is not None, "lower group not empty")
    proof(f, hl.mag < p - 2 + BM, "carry: magic in range",
          f"|h_l| < 2^{hl.mag:.2f} against 2^{p - 2 + BM}")
    MQb = f.wx(Fraction(3, 2) * 2 ** (p - 1 + BM))
    c = exact(f, f.sub(data(f, f.add(hl.ref, MQb)), MQb))
    hl2 = exact(f, f.sub(hl.ref, c))
    c_sv = SV(c, _lg(2 ** hl.mag + 2 ** (BM - 1)), BM)
    e_sv = add_exact(f, e_sv, c_sv, p)
    proof(f, e_sv is not None, "e + carry exact")
    f.probes.update(carry=c)

    # ---- the exact upper part (f_I + h2 + low word + carry) as a double word,
    # ---- then the quadrant once more, on its high word ---------------------
    xh0, xl = f.two_sum(s, e_sv.ref)
    q3 = data(f, f.fma(xh0, V, magic_ref))
    nk3 = exact(f, f.sub(magic_ref, q3))
    xh = exact(f, f.fma(nk3, U, xh0))                   # |xh| <= U/2
    nqs.append(nk3)
    f.probes.update(xh=xh, xl=xl, hl=hl2, hu=hu.ref, h2=h2.ref, s=s, e=e_sv.ref)

    # ---- the lows: a double word that may round (below the bottom) --------
    f.phase = "red-lower"
    lows.sort(key=lambda v: -v.mag)
    acc_need = need + p                     # below this a plain add is fine
    lh = ll = None
    for v in lows:
        if lh is None:
            lh = v.ref
            continue
        if v.mag > acc_need:
            lh, er = f.two_sum(lh, v.ref)
            ll = er if ll is None else f.add(ll, er)
        else:
            ll = v.ref if ll is None else f.add(ll, v.ref)

    # ---- the overshoot of |r| past pi/4, from the pieces' static magnitudes ----
    # The last quadrant step centres xh0, the exact upper part's high word
    # (f_I + h2 + the upper group's low word + the carry, rounded), so |xh| <= U/2
    # whatever the lower words are. What it does not see: xl, the rounding of
    # that sum (|xl| <= ulp(xh0)/2 <= 2^-24 |xh0|, |xh0| <= U + |e|), and the
    # lower terms L = h_l - carry (<= 2^(bmid-1): the carry took the multiples
    # of 2^bmid up into the decision), the lower group's low word and the lows.
    # In t = f V, V = 2^sigma <= 2 (sigma <= 1) and U V = 1:
    #   2|t| - 1 = 2 V (|f| - U/2) <= 2 V |xl| + 2 V |L|
    #            <= 2^(1-p) (1 + |e|/U) + 4 |L|
    # (|e| <= 2^e.mag, U >= 1/2), and 2^-60 for the rounding of r = t pi/2 and
    # of t's triple word (2^-69.5 relative, MEASURED by the reduce mode). The
    # double word's reduction at fp32 G = 18 (M2G1) misses the mid sum's low
    # word here, which is why its bound is 2^-11.66 and this one is not.
    lowsum = Fraction(2) ** (BM - 1)
    if lwl is not None:
        lowsum += Fraction(2) ** math.ceil(lwl.mag)
    for v in lows:
        lowsum += Fraction(2) ** math.ceil(v.mag)
    over = _upper(Fraction(2) ** (1 - p) * (1 + Fraction(2) ** math.ceil(e_sv.mag + 1))
                  + 4 * lowsum + Fraction(1, 2 ** 60))
    proof(f, over < Fraction(1, 2 ** 10), "overshoot of |r| past pi/4 is small",
           f"over = {float(over):.3e}")
    P.overshoot = over
    P.rho = _upper(pi_frac() / 4 * (1 + over))
    f.meta["overshoot"] = over

    # ---- the triple word t -------------------------------------------------
    f.phase = "red-triple"
    terms = [t for t in (ll, lh, lwl.ref if lwl is not None else None, hl2, xl, xh)
             if t is not None]
    t0, t1, t2 = to_triple(f, terms)
    f.probes.update(t0=t0, t1=t1, t2=t2)

    # ---- scale by V, then r = t pi/2 in three words -----------------------
    f.phase = "red-scale"
    T0 = exact(f, f.mul(t0, V))
    T1 = exact(f, f.mul(t1, V))
    T2 = exact(f, f.mul(t2, V))
    pw = pio2_words(fmt, 3)
    PI0, PI1, PI2 = (f.w(pw[0], "PIO2_0"), f.w(pw[1], "PIO2_1"), f.w(pw[2], "PIO2_2"))
    nT0 = f.neg(T0)
    nT1 = f.neg(T1)
    a, nea = tprod(f, T0, nT0, PI0)            # T0 pi0
    bb, neb = tprod(f, T0, nT0, PI1)           # T0 pi1
    cc, nec = tprod(f, T1, nT1, PI0)           # T1 pi0
    u1, e1 = f.two_sum(bb, cc)
    u2, e2 = two_diff(f, u1, nea)              # + the error of T0 pi0
    lv = f.add(e1, e2)
    lv = f.sub(lv, neb)
    lv = f.sub(lv, nec)
    lv = f.fma(T0, PI2, lv)
    lv = f.fma(T1, PI1, lv)
    lv = f.fma(T2, PI0, lv)
    if plant == "r2-dropped":
        lv = ZERO                               # r's third word left out
    r0, w = f2s(f, a, u2)
    r1, r2 = f.two_sum(w, lv)
    if plant == "r2-dropped":
        r1, r2 = w, ZERO
    # the quadrant: n = -(sum of the -k), as MAGIC + n
    nsum = nqs[0]
    for v in nqs[1:]:
        nsum = exact(f, f.add(nsum, v))
    q = exact(f, f.sub(magic_ref, nsum))

    # ---- |x| < pi/4: r = |x|, quadrant 0 -----------------------------------
    f.phase = "red-small"
    # the same IAND as m2red's; the classification forms |x| otherwise (below),
    # so that this value is not the one kept live across the polynomials
    ax = f.iand(x, f.wi(fmt.sign_mask ^ ((1 << fmt.width) - 1)))
    from m2red import _pio4
    small = f.cmplt(ax, f.w(enc(fmt, _pio4(), RDN), "PIO4D"))
    r0 = f.sel(ax, r0, small)
    r1 = f.sel(ZERO, r1, small)
    r2 = f.sel(ZERO, r2, small)
    q = f.sel(magic_ref, q, small)
    f.probes.update(r0=r0, r1=r1, r2=r2, q=q, small=small)
    return {"r0": r0, "r1": r1, "r2": r2, "q": q, "small": small}


# ---- an argument family for the cushion and the budget ------------------------

def quad_family(fmt=FMT, K=64, J=3, extra=128, seed=41):
    """The floats within J ulps of (k + 1/2) pi/2 - the odd multiples of pi/4,
    the quadrant boundaries, where |r| is next to pi/4 and the rho of the
    polynomials' domain acts - for every k from 0 to K - 1 (so 0x3f490fdb,
    the float just above pi/4, is k = 0, j = 0), and for `extra` more k of
    random size (random_bits: 1 to 127, both parities), both signs. The
    study's `edge` region takes odd k only and never k = 0. -> sorted list."""
    import random
    rng = random.Random(seed)
    pio2 = pi_frac() / 2
    ks = list(range(K)) + [rng.getrandbits(rng.randint(1, fmt.emax)) for _ in range(extra)]
    out = set()
    for k in ks:
        b = enc(fmt, (Fraction(k) + Fraction(1, 2)) * pio2)
        for j in range(-J, J + 1):
            out.add(b + j)
            out.add((b + j) | fmt.sign_mask)
    return sorted(x for x in out if sf.unpack(fmt, x).kind not in (sf.INF, sf.NAN))


_HALF = {}


def half_family(fmt=FMT, thr_bits=18, cap=96, small_v=6, neighbours=2):
    """The floats next to the odd multiples of pi/4 in every binade, both
    signs (the lead's second message of 2026-10-27: 0x44264edd, 665.2322,
    x 2/pi = 423.4999964, is one). Value exponents -1 to 6: every odd
    multiple (k + 1/2) pi/2 in the binade, its nearest float and `neighbours`
    on each side. Value exponents 7 and up: the floats whose x 2/pi lies
    within 2^-thr_bits of a half-integer (about 2^(24 - thr_bits + 1) = 128
    a binade; the `cap` nearest if more), found with numpy's wrapping uint64
    product M x (2^e 2/pi mod 1 to 64 bits), whose product's error is under
    2^-40. The only use of numpy in this model; the Miniconda of the desktop
    has it. -> sorted list of encodings."""
    key = (fmt.name, thr_bits, cap, small_v, neighbours)
    if key in _HALF:
        return _HALF[key]
    import numpy as np
    import pi_worstcase
    p = fmt.prec
    pio2 = pi_frac() / 2
    lo = 1 << (p - 1)
    Ms = np.arange(lo, 1 << p, dtype=np.uint64)
    out = set()
    for v in range(-1, fmt.emax + 1):
        if v <= small_v:
            k = 0
            while True:
                m = (Fraction(k) + Fraction(1, 2)) * pio2
                if m >= Fraction(2) ** (v + 1):
                    break
                if m >= Fraction(2) ** v:
                    b = enc(fmt, m)
                    for j in range(-neighbours, neighbours + 1):
                        out.add(b + j)
                k += 1
            continue
        a64 = np.uint64(pi_worstcase.alpha_of(v - p + 1, 128) >> 64)
        d = (Ms * a64 - np.uint64(1 << 63)).view(np.int64)       # frac(M alpha) - 1/2, units 2^-64
        ad = np.abs(d.astype(np.float64))                        # (-2^63 would overflow an int64 abs)
        idx = np.nonzero(ad < float(1 << (64 - thr_bits)))[0]
        if len(idx) > cap:
            idx = idx[np.argsort(ad[idx])[:cap]]
        for i in idx:
            out.add(((v + fmt.bias) << fmt.man_w) | int(Ms[int(i)] - lo))
    both = set(out) | {x | fmt.sign_mask for x in out}
    _HALF[key] = sorted(both)
    return _HALF[key]


def quad_sample(fmt, n, seed):
    """n of the quadrant-boundary arguments (quad_family and half_family),
    drawn by `seed` (all of them if fewer)."""
    import random
    fam = sorted(set(quad_family(fmt)) | set(half_family(fmt)))
    return sorted(random.Random(seed).sample(fam, n)) if n < len(fam) else fam


# ---- the polynomials' plan ---------------------------------------------------

def plan_tw_poly(fmt, G, rho, slack=2):
    """(K3, K2, D) for S and for C, plan_exp32's rule on S and C in exact
    rationals: term k enters V at weight w_k = |c_k| rho^(2k), so its partial
    sum needs  need(k) = (p + G + slack) + log2 w_k  bits; a triple-word step
    keeps 3p - 2, a double-word step 2p - 2 and a single-word step p - 2.
    K3 steps are triple-word (need above 2p - 2), K2 more are double-word
    (need above p - 2), then a single-word tail to degree D, the first
    degree whose next term is under 2^-(p+G+3)."""
    p = fmt.prec
    z = rho * rho
    out = {}
    for name, coef in (("S", sin_coef), ("C", cos_coef)):
        w = lambda k: abs(coef(k)) * z ** k
        D = 1
        while w(D + 1) > Fraction(1, 2 ** (p + G + 3)):
            D += 1
        def above(bits):
            return lambda k: w(k) > Fraction(2) ** (bits - (p + G + slack))
        k3 = 0
        while above(2 * p - 2)(k3):
            k3 += 1
        k23 = k3
        while above(p - 2)(k23):
            k23 += 1
        out[name] = (k3, k23 - k3, D)
    return out


_RATIO = {}


def order_ratio(coef, k, rho, upto=60):
    """sup over z <= rho^2 of |z y_(k+1)(z)| / |c_k|, y_(k+1) the Horner
    partial sum, bounded by the series' absolute values: the head step's
    Fast2Sum(c_k, z y) is ordered while this is under 1."""
    key = (coef.__name__, k, rho)
    if key not in _RATIO:
        z = rho * rho
        s = sum(abs(coef(j)) * z ** (j - k) for j in range(k + 1, upto))
        _RATIO[key] = s / abs(coef(k))
    return _RATIO[key]


# ---- the build ---------------------------------------------------------------

def build(fmt, rnd, fn, G=G_TW, bound_shift=0, plant=None):
    """One routine at fp32, a triple word at G = 40 (pruned; the unpruned
    body kept as all_body). `plant`, one of PLANTS:
      r2-dropped     r's third word left out of the reduction's product
      carry-dropped  the upper group's first TwoSum a plain add, its error
                     (a carry into the low word) dropped, still claimed exact
      mark-silenced  the flag word never carries the mark"""
    assert fn in ("sin", "cos", "tan"), fn
    assert plant is None or plant in PLANTS, plant
    assert fmt.name == "fp32", fmt.name
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    gs, gc = gates(fmt)
    gate = gs if fn == "sin" else gc
    P = tw_plan(fmt, G)
    f = Frag(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}-tw")
    f.meta.update(G=G, R=None, variant="tw", fn=fn)
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
    INT1 = wi(1, "INT1")
    MAGIC = f.wx(Fraction(3, 2) * 2 ** (p - 1), "MAGIC")

    # ---- reduce ------------------------------------------------------------
    red = reduce_tw(f, x, P, MAGIC, plant if plant in ("r2-dropped", "carry-dropped") else None)
    r0, r1, r2, q = red["r0"], red["r1"], red["r2"], red["q"]

    # ---- z = r0^2 exactly, as a double word --------------------------------
    f.phase = "z"
    pl = plan_tw_poly(fmt, G, P.rho)
    f.meta["poly"] = pl
    nr0 = f.ixor(r0, SIGN)
    z0 = f.mul(r0, r0)
    nz1 = f.fma(nr0, r0, z0)                           # z0 - r0^2 = -z1
    z1 = f.ixor(nz1, SIGN)
    nz0 = f.ixor(z0, SIGN)

    def coefw(coef, k, n):
        return words_of(fmt, coef(k), n)

    def poly(coef, name):
        K3, K2, D = pl[name]
        f.phase = name + "-tail"
        y = f.wv(coef(D))
        for k in range(D - 1, K3 + K2 - 1, -1):
            y = f.fma(y, z0, f.wv(coef(k)))
        yh, yl = y, None
        f.phase = name + "-head2"
        for k in range(K3 + K2 - 1, K3 - 1, -1):      # double-word steps
            ch, cl = coefw(coef, k, 2)
            CH = w(ch)
            pp = f.mul(yh, z0)
            ne = f.fma(yh, nz0, pp)                   # pp - yh z0 = -err
            nl = f.fma(yl, nz0, ne) if yl is not None else ne
            nl = f.fma(yh, nz1, nl)                   # - yh z1
            s_, e2 = f2s(f, CH, pp)                   # Fast2Sum(c, pp): ordered
            tt = f.sub(e2, nl)
            yl = f.add(tt, w(cl)) if cl else tt
            yh = s_
            proof(f, order_ratio(coef, k, P.rho) < 1,
                  f"{name} k={k}: |c_k| > |z y| (Fast2Sum ordered)",
                  f"ratio {float(order_ratio(coef, k, P.rho)):.3f}")
        y0, y1, y2 = yh, yl, None
        f.phase = name + "-head3"
        for k in range(K3 - 1, -1, -1):               # triple-word steps
            c0, c1, c2 = coefw(coef, k, 3)
            proof(f, order_ratio(coef, k, P.rho) < 1,
                  f"{name} k={k}: |c_k| > |z y| (Fast2Sum ordered)",
                  f"ratio {float(order_ratio(coef, k, P.rho)):.3f}")
            # the terms of y' = c + y z by level, each product's error taken as
            # soon as the product is, each TwoSum's error added to the level-2
            # word as soon as it is made (few values live at once)
            a = f.mul(y0, z0)
            nea = f.fma(y0, nz0, a)                   # a - y0 z0 = -ea
            f.meta["two_prod"] += 1
            s0, t0 = f2s(f, w(c0), a)
            lv, acc = None, t0

            def lvadd(lv, er):
                return er if lv is None else f.add(lv, er)
            if c1:
                acc, er = f.two_sum(acc, w(c1))
                lv = lvadd(lv, er)
            acc, er = two_diff(f, acc, nea)           # + ea
            lv = lvadd(lv, er)
            bq = f.mul(y0, z1)
            neb = f.fma(y0, nz1, bq)                  # -eb
            f.meta["two_prod"] += 1
            acc, er = f.two_sum(acc, bq)
            lv = lvadd(lv, er)
            lv = f.sub(lv, neb)                       # + eb
            if y1 is not None:
                cc = f.mul(y1, z0)
                nec = f.fma(y1, nz0, cc)              # -ec
                f.meta["two_prod"] += 1
                acc, er = f.two_sum(acc, cc)
                lv = lvadd(lv, er)
                lv = f.sub(lv, nec)                   # + ec
                lv = f.fma(y1, z1, lv)                # + y1 z1
            if c2:
                lv = f.add(lv, w(c2))
            if y2 is not None:
                lv = f.fma(y2, z0, lv)                # + y2 z0
            u_, v_ = f2s(f, s0, acc)
            v2, w2 = f.two_sum(v_, lv)
            y0, y1, y2 = u_, v2, w2
        return y0, y1, y2

    S0, S1, S2 = poly(sin_coef, "S")
    C0, C1, C2 = poly(cos_coef, "C")

    # ---- sin(r0) = r0 S, three words; r's lower words to second order -------
    f.phase = "sincos"
    p0, ne0 = tprod(f, r0, nr0, S0)
    p1, ne1 = tprod(f, r0, nr0, S1)
    p2 = f.mul(r0, S2)
    u1, v1 = two_diff(f, p1, ne0)                      # p1 + e0
    lvl = f.sub(f.add(v1, p2), ne1)                    # + p2 + e1
    a_, b_ = f2s(f, p0, u1)
    s0, rest = a_, b_
    s1, s2 = f.two_sum(rest, lvl)                      # sin(r0) = (s0, s1, s2)
    f.probes.update(s0=s0, s1=s1, s2=s2, C0=C0, C1=C1, C2=C2)

    nr1 = f.ixor(r1, SIGN)
    nhr1 = f.mul(r1, w(pow2_bits(fmt, -1) | fmt.sign_mask, "NHALF"))   # -r1/2

    # sin(r) = sin r0 + cos r0 d - sin r0 d^2/2, d = r1 + r2
    mc0 = f.mul(C0, r1)
    nmce = f.fma(C0, nr1, mc0)                         # mc0 - C0 r1 = -(the error)
    lc = f.neg(nmce)                                   # + the error of C0 r1
    lc = f.fma(C0, r2, lc)
    lc = f.fma(C1, r1, lc)
    hs = f.mul(s0, nhr1)                               # -s0 r1 / 2
    lc = f.fma(hs, r1, lc)                             # - s0 r1^2 / 2
    SIN = _add_level1(f, (s0, s1, s2), mc0, lc)
    # cos(r) = cos r0 - sin r0 d - cos r0 d^2/2: level 1 is -(s0 r1), level 2
    # is its error's negation, -s0 r2, -s1 r1 and -C0 r1^2/2
    ms0 = f.mul(s0, r1)
    nmse = f.fma(s0, nr1, ms0)                         # ms0 - s0 r1 = -(the error)
    ns0, ns1 = f.ixor(s0, SIGN), f.ixor(s1, SIGN)
    hc = f.mul(C0, nhr1)                               # -C0 r1 / 2
    lc2 = f.fma(ns0, r2, nmse)
    lc2 = f.fma(ns1, r1, lc2)
    lc2 = f.fma(hc, r1, lc2)
    COS = _add_level1(f, (C0, C1, C2), f.ixor(ms0, SIGN), lc2)
    f.probes.update(sinr=SIN[0], cosr=COS[0])

    # ---- select by the quadrant, and the sign ------------------------------
    f.phase = "select"
    sx = f.iand(x, SIGN)
    b0 = f.iand(q, INT1)
    b1 = f.iand(q, wi(2, "INT2"))
    if fn == "sin":
        Vw = [f.sel(c_, s_, b0) for c_, s_ in zip(COS, SIN)]
        sg = f.ixor(f.ishl(b1, wi(W - 2)), sx)
    elif fn == "cos":
        Vw = [f.sel(s_, c_, b0) for c_, s_ in zip(COS, SIN)]
        sg = f.ishl(f.ixor(f.ishl(b0, wi(1)), b1), wi(W - 2))
    else:
        Nw = [f.sel(c_, s_, b0) for c_, s_ in zip(COS, SIN)]
        Dw = [f.sel(s_, c_, b0) for c_, s_ in zip(COS, SIN)]
        sg = f.ixor(f.ishl(b0, wi(W - 1)), sx)
        f.phase = "quotient"
        Vw = _quotient(f, Nw, Dw, ONE, SIGN, p)
    V0, V1, V2 = [f.ixor(v, sg) for v in Vw]
    f.probes.update(V0=V0, V1=V1, V2=V2, Vh=V0)

    # ---- the final rounding and the in-lane test (mathlib.py:1892-1902) -----
    f.phase = "final"

    def rto(a, c):
        """round-to-odd of a + c (|a| >= |c| or either zero): the sum
        truncated, its last bit set where it was inexact."""
        s_ = f.add(a, c, RTZ)
        ex = f.cmpeq(f.sub(c, f.sub(s_, a)), ZERO)
        return f.sel(s_, f.ior(s_, INT1), ex)
    lo = rto(V1, V2)
    Rg = f.add(V0, lo, rnd)
    brel = pow2_bits(fmt, -(p + G) + bound_shift)
    Bv = f.mul(f.fabs(V0), w(brel, "BREL"))
    lo_dn = rto(V1, f.sub(V2, Bv, RDN))
    lo_up = rto(V1, f.add(V2, Bv, RUP))
    R1 = f.add(V0, lo_dn, rnd)
    R2 = f.add(V0, lo_up, rnd)
    f.probes.update(R=Rg, R1=R1, R2=R2, Bv=Bv)
    if fn in ("sin", "cos"):
        tinyv = Fraction(1, 2 ** (3 * p))
        U1 = w(enc(fmt, 1 - tinyv, rnd), "U1")
        L1 = w(enc(fmt, -1 + tinyv, rnd), "L1")
        R1 = f.fmax(R1, L1)
        R2 = f.fmin(R2, U1)
        Rg = f.fmin(f.fmax(Rg, L1), U1)
    mk = f.ixor(R1, R2)
    fl = INX if plant == "mark-silenced" else f.sel(INXM, INX, mk)
    bits_ = Rg

    # ---- classify x (late), the tiny paths and the specials (m2trig's) -------
    f.phase = "classify"
    ax = f.ixor(x, f.iand(x, SIGN))                     # |x|: x with its sign bit cleared
    isnan = f.icmplt(INF, ax)
    issnan = f.sel(ZERO, isnan, f.iand(x, wi(1 << (mw - 1), "QBIT")))
    isinf = f.cmpeq(ax, INF)
    iszero = f.icmplt(ax, INT1)
    tiny = f.icmplt(ax, w(pow2_bits(fmt, gate)))
    f.probes.update(mk=mk)
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


def _add_level1(f, base, m1, lvl2):
    """(b0, b1, b2) + m1 (a level-1 word) + lvl2 (a level-2 word), the sum
    renormalised: TwoSum(b1, m1), plain adds into the level-2 word,
    Fast2Sum(b0, .) with its claim audited, TwoSum for the last."""
    b0, b1, b2 = base
    a1, a2 = f.two_sum(b1, m1)
    lv = f.add(f.add(b2, a2), lvl2)
    c0, c1 = f2s(f, b0, a1)
    d1, d2 = f.two_sum(c1, lv)
    return c0, d1, d2


def _quotient(f, Nw, Dw, ONE, SIGN, p):
    """N / D as a triple word, N and D triple words with D0 not zero: a
    reciprocal y of D0 (RECIP_SEED and two Newton steps: one word, good to
    about 2^-24), then a long division with exact remainders. q0 = N0 y is
    one ulp off at most, so N0 - q0 D0 can need 25 bits and is NOT one FMA's
    exact result (the first version lost 2^-48 there: tan at 0x3a410113,
    2^+16 Bv): it is kept as the two exact floats (N0 - m) and (m - q0 D0),
    m = rnd(q0 D0). Then R1 = N - q0 D as a (high, low) pair, q1 = R1 y,
    R2 = R1 - q1 D, q2 = R2 y, R3 = R2 - q2 D, q3 = R3 y; each remainder
    is computed so that the rounding of q_i is inside the next."""
    N0, N1, N2 = Nw
    D0, D1, D2 = Dw
    y = f.recip_seed(D0)
    nD0 = f.ixor(D0, SIGN)
    for _ in range(2):
        e = f.fma(nD0, y, ONE)                          # 1 - D0 y
        y = f.fma(y, e, y)
    q0 = f.mul(N0, y)
    nq0 = f.ixor(q0, SIGN)
    m_, nem = tprod(f, q0, nq0, D0)                     # q0 D0 = m_ - nem
    w0 = f.sub(N0, m_)                                  # exact: m_ is within 2x of N0
    b_, neb = tprod(f, q0, nq0, D1)                     # q0 D1 = b_ - neb
    c2 = f.fma(nq0, D2, N2)                             # N2 - q0 D2
    # R1 = (w0 + nem) + (N1 - b_) + neb + c2: the level-1 floats by TwoSums
    acc, e1 = f.two_sum(w0, nem)
    acc, e2 = f.two_sum(acc, N1)
    R1a, e3 = two_diff(f, acc, b_)
    lv = f.add(f.add(e1, e2), e3)
    lv = f.add(lv, neb)
    lv = f.add(lv, c2)
    q1 = f.mul(R1a, y)
    nq1 = f.ixor(q1, SIGN)
    a1 = f.fma(nq1, D0, R1a)                            # R1a - q1 D0
    a1b = f.fma(nq1, D1, lv)                            # lv - q1 D1
    R2 = f.add(a1, a1b)
    R2 = f.fma(nq1, D2, R2)
    q2 = f.mul(R2, y)
    nq2 = f.ixor(q2, SIGN)
    R3 = f.fma(nq2, D0, R2)
    R3 = f.fma(nq2, D1, R3)
    q3 = f.mul(R3, y)
    # q0 + q1 + q2 + q3 -> a triple word
    s0, w1 = f2s(f, q0, q1)
    s1, w2 = f.two_sum(w1, q2)
    return s0, s1, f.add(w2, q3)
