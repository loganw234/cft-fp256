# M2 model: the argument reduction, design A (scratch; the study's 2.2).
#
# Payne-Hanek against 2/pi's bits, in S-hat units (m2plan.py's header):
#   setup     E, M, G0 = E - p - 1, g-1 = floor(G0/b), sigma, and the
#             powers U = 2^-sigma, V = 2^sigma, m = 4U, 1/m = V/4 built on
#             the encoding from sigma
#   window    the L chunks c_(g-1) .. c_(g-2+L), integer-valued floats, out
#             of the table by a SELECT log-shifter over the shift
#             g-1+Z (bank words only); or by LDX from a scratch copy, the
#             alternative, counted (m2alts.py)
#   products  T_j = M c 2^-(jb): TwoProd where the low word matters, MUL
#             where it is below the needed accuracy
#   coarse    P_0 mod m (guarded), rho_0 mod m, P_1 mod m: one exact sum
#             V_I; k1 = round(V_I/U) and f_I = V_I - k1 U, exact
#   mid       the pieces above a fixed S-hat bottom 2^bottom, split there
#             where they straddle it, summed exactly; reduced modulo U;
#             added to f_I exactly; the quadrant taken out again, exactly.
#             The cancellation against the nearest multiple of pi/2
#             happens here, with no rounding
#   lower     the pieces below the bottom, a double-word sum, then the
#             exact part plus it (TwoSum, the low words added)
#   scale     t = (that) V, exact; r = t pi/2 as a double word
#   small     |x| < pi/4 takes r = x, quadrant 0
#
# Every instruction this module calls exact is listed in f.meta["exact"]
# and audited lane by lane (audit()): its operands' exact values, the
# exact operation, and the rounded result compared.

import math
from fractions import Fraction

from m2core import (sf, enc, enc_exact, dec, pow2_bits, run_body, RNE,
                    RTZ, RDN, RUP, RMM)
from m2const import pio2_words


class SV:
    """A value of the reduction with static bounds: |v| <= 2^mag (mag a
    float), v a multiple of 2^grid (grid an int, or None if unknown)."""
    __slots__ = ("ref", "mag", "grid")

    def __init__(self, ref, mag, grid):
        self.ref, self.mag, self.grid = ref, mag, grid


def _lg(x):
    return math.log2(x) if x > 0 else -1e9


def exact(f, ref):
    f.meta.setdefault("exact", set()).add(ref)
    return ref


def data(f, ref):
    """A rounding that SELECTS an integer (a magic-number rounding: the
    quotient of a modular reduction, a quadrant count, a split's high
    part, the bucket): its rounding is the operation's purpose, not an
    error, so the first-order budget freezes it as data (m2budget.py)."""
    f.meta.setdefault("data", set()).add(ref)
    return ref


def add_exact(f, a: SV, b: SV, p):
    """a + b claimed exact: both on known grids, the sum fits p bits."""
    g = min(a.grid, b.grid)
    mag = _lg(2 ** a.mag + 2 ** b.mag)
    if mag - g >= p:                     # the static proof fails
        return None
    return SV(exact(f, f.add(a.ref, b.ref)), mag, g)


def build_window(f, P, shift_int):
    """The L words P.words[s + j], j < L, s = the shift (an integer in the
    low bits of `shift_int`'s encoding), by a SELECT log-shifter: at the
    level of bit i, an array of L + 2^i - 1 values, each the SELECT of
    two of the level above. -> [refs]."""
    nbits = max(1, (P.shifts - 1).bit_length())
    arr = [f.wx(c) if c else f.w(0, "ZERO") for c in P.words]
    for i in range(nbits - 1, -1, -1):
        bit = f.iand(shift_int, f.wi(1 << i))
        need = P.L + (1 << i) - 1
        nxt = []
        for k in range(need):
            lo = arr[k] if k < len(arr) else arr[-1]
            hi = arr[k + (1 << i)] if k + (1 << i) < len(arr) else arr[-1]
            nxt.append(f.sel(hi, lo, bit))
        arr = nxt
    return arr[:P.L]


PLANTS_RED = ("chunk", "window", "mid-inexact", "exact-add")


def reduce_ph(f, x, P, magic_ref, variant="A", plant=None):
    """Append the reduction to f. -> dict with r_h, r_l (the reduced
    argument as a double word), q (MAGIC + n as a float: its encoding's
    low two bits are n mod 4), small (|x| < pi/4, a condition), and the
    probes. variant "A" carries the cancellation exactly; "B" sums the
    mid pieces in double-word arithmetic (the alternative). `plant`, one
    of PLANTS_RED, builds one named fault (plants.py):
      chunk        one bit flipped in a stored chunk of 2/pi (the middle
                   of the table's chunks)
      window       the window read one word late (the shift off by one)
      mid-inexact  the mid pieces summed with rounding (design B's sum)
                   while the in-lane bound stays design A's
      exact-add    the mid sum's first TwoSum replaced by a plain add, the
                   add still listed as exact"""
    fmt = f.fmt
    p, mw, bias = fmt.prec, fmt.man_w, fmt.bias
    b, L = P.b, P.L
    MAGIC = Fraction(3, 2) * 2 ** (p - 1)
    MAGIC_B = enc_exact(fmt, MAGIC)
    if plant == "chunk":
        import copy
        P = copy.copy(P)
        P.words = list(P.words)
        k = P.Z + P.nchunks // 2
        P.words[k] ^= 1 << (P.b // 2)
    if plant == "mid-inexact":
        variant = "B"
    f.phase = "red-setup"
    # E from the encoding; the bucket first, since the window needs it
    Eb = f.ishr(f.iand(x, f.wi(fmt.exp_mask << mw)), f.wi(mw))
    Ebm = f.ior(Eb, magic_ref)                          # MAGIC + Eb
    # G0p = G0 + 2 - b, G0 = Eb - bias - p - 1
    G0p = exact(f, f.sub(Ebm, f.wx(MAGIC + bias + p + 1 - 2 + b)))
    # g-1 = floor((G0 + 1/2)/b) = floor((G0p + b - 3/2)/b)
    y = f.fma(G0p, f.wv(Fraction(1, b)), f.wv(Fraction(2 * b - 3, 2 * b)))
    gm1m = data(f, f.add(y, magic_ref, RDN))            # MAGIC + (g-1)
    shift = f.iadd(gm1m, f.wi(P.Z + (1 if plant == "window" else 0)))

    f.phase = "red-window"
    win = build_window(f, P, shift)

    f.phase = "red-setup"
    # sigma, its powers of two (built on the encoding), and M: after the
    # window, so that they are not live across it
    gm1 = exact(f, f.sub(gm1m, magic_ref))
    sig = exact(f, f.fma(gm1, f.wx(-b), G0p))           # sigma
    sigm = exact(f, f.add(sig, magic_ref))              # MAGIC + sigma
    V = f.ishl(f.isub(sigm, f.wi(MAGIC_B - bias)), f.wi(mw))   # 2^sigma
    U = f.isub(f.wi((2 * bias) << mw), V)                      # 2^-sigma
    m = f.iadd(U, f.wi(2 << mw))                               # 4U
    inv_m = f.isub(V, f.wi(2 << mw))                           # V/4
    f.probes.update(sig=sig, V=V, U=U, gm1=gm1)
    M = f.ior(f.iand(x, f.wi(fmt.man_mask)), f.wi((bias + p - 1) << mw))
    nM = f.ixor(M, f.wi(fmt.sign_mask))                 # -M, for TwoProd

    f.phase = "red-products"
    rows = {r[0]: r for r in P.rows}
    need = P.budget - 3                                 # S-hat accuracy
    prods = []
    for j in range(L):
        # the chunk scaled by 2^-(jb), exactly: one MUL, shared by the
        # product and its error
        Wj = win[j] if j == 0 else exact(f, f.mul(win[j], f.wx(Fraction(1, 2 ** (j * b)))))
        _j, lmin, lmax, pgrid, rhomag, rhogrid = rows[j]
        if lmax is None:
            prods.append(None)
            continue
        Pj = f.mul(M, Wj)
        if rhomag > need:                               # the low word counts
            f.meta["two_prod"] += 1
            nrho = exact(f, f.fma(nM, Wj, Pj))          # = P - T = -rho
            rho = f.neg(nrho)
            prods.append((SV(Pj, lmax + 1e-9, pgrid), SV(rho, rhomag, rhogrid)))
        else:
            prods.append((SV(Pj, lmax + 1e-9, pgrid), None))
    if prods[0] is not None:
        f.probes.update(P0=prods[0][0].ref)

    f.phase = "red-coarse"
    nqs = []                    # -k for every quadrant count taken out

    def mod_m(v: SV, guard=False):
        q = data(f, f.fma(v.ref, inv_m, magic_ref))     # MAGIC + round(v/m)
        nq = exact(f, f.sub(magic_ref, q))              # -round(v/m)
        r = exact(f, f.fma(nq, m, v.ref))
        if guard:
            # |v| >= 2^(p-1) m: v's ulp is at least m, so v = 0 mod m
            thr = f.iadd(m, f.wi((p - 1) << mw))
            small = f.cmplt(f.fabs(v.ref), thr)
            r = f.sel(r, f.w(0, "ZERO"), small)
        # |r| <= m <= 2^b, and r = v - q m is a multiple of min(grid, 2)
        return SV(r, min(v.mag, b + 0.0), min(v.grid, 1))

    # A position whose chunk is zero in every bucket the range has (a range
    # below 2^p leaves position 0, and below 2^(p-b) position 1, without
    # one) contributes nothing: its pieces are left out.
    P0, rho0 = prods[0] if prods[0] is not None else (None, None)
    P1, rho1 = prods[1] if prods[1] is not None else (None, None)
    coarse = []
    if P0 is not None:
        coarse.append(mod_m(P0, guard=True))
    if rho0 is not None:
        coarse.append(mod_m(rho0))
    if P1 is not None:
        coarse.append(mod_m(P1))
    if coarse:
        VI = coarse[0]
        for c in coarse[1:]:
            VI = add_exact(f, VI, c, p)
            assert VI is not None, "the coarse sum is not exact"
        q1 = data(f, f.fma(VI.ref, V, magic_ref))       # MAGIC + round(VI/U)
        nk1 = exact(f, f.sub(magic_ref, q1))
        fI = exact(f, f.fma(nk1, U, VI.ref))            # |fI| <= U/2
        nqs.append(nk1)
    else:
        fI = f.w(0, "ZERO")
    f.probes.update(fI=fI)

    f.phase = "red-mid"
    bottom = P.bottom
    MQ = f.wx(Fraction(3, 2) * 2 ** (p - 1 + bottom))  # the split's magic
    mids, lows = [], []

    def place(v: SV):
        """Classify a piece against the bottom: mid, split, or lower."""
        if v is None:
            return
        if v.grid >= bottom:
            mids.append(v)
        elif v.mag < bottom:
            lows.append(v)
        else:
            assert v.mag < p - 2 + bottom, "the split's magic is out of range"
            hi = exact(f, f.sub(data(f, f.add(v.ref, MQ)), MQ))
            lo = exact(f, f.sub(v.ref, hi))
            mids.append(SV(hi, v.mag + 1e-9, bottom))
            lows.append(SV(lo, bottom, v.grid))

    place(rho1)
    for j in range(2, L):
        if prods[j] is None:
            continue
        Pj, rhoj = prods[j]
        if Pj.mag >= -1:                                # may carry quadrant bits
            Pj = mod_m(Pj)
            Pj.mag = min(Pj.mag, prods[j][0].mag)
        place(Pj)
        place(rhoj)
    # the mid pieces, summed exactly: largest first, TwoSum where a plain
    # add is not provably exact, the low words added exactly
    mids.sort(key=lambda v: -v.mag)
    if variant == "A":
        # largest first into (h, lw), the double word h + lw exact
        # throughout: a piece goes into the low word where that sum is
        # provably exact, else into h where that is, else by TwoSum
        h = mids[0]
        lw = None
        planted = plant != "exact-add"
        for v in mids[1:]:
            if lw is not None:
                s = add_exact(f, lw, v, p)
                if s is not None:
                    lw = s
                    continue
            s = add_exact(f, h, v, p)
            if s is not None:
                h = s
                continue
            if not planted:
                # the plant: a plain add where a TwoSum is needed, claimed
                planted = True
                h = SV(exact(f, f.add(h.ref, v.ref)), _lg(2 ** h.mag + 2 ** v.mag),
                       min(h.grid, v.grid))
                continue
            ss, ee = f.two_sum(h.ref, v.ref)
            g = min(h.grid, v.grid)
            nh = SV(ss, _lg(2 ** h.mag + 2 ** v.mag), g)
            ev = SV(ee, nh.mag - p, g)
            h = nh
            if lw is None:
                lw = ev
            else:
                lw = add_exact(f, lw, ev, p)
                assert lw is not None
        f.probes.update(mid_h=h.ref)
        # the mid sum modulo U, exactly
        q2 = data(f, f.fma(h.ref, V, magic_ref))
        nk2 = exact(f, f.sub(magic_ref, q2))
        h2 = SV(exact(f, f.fma(nk2, U, h.ref)), h.mag, h.grid)
        nqs.append(nk2)
        # fI + mid, exactly, as a double word: TwoSum, then the low words
        s, e = f.two_sum(fI, h2.ref)
        if lw is not None:
            e = exact(f, f.add(e, lw.ref))
        # the quadrant once more: |s| <= U
        q3 = data(f, f.fma(s, V, magic_ref))
        nk3 = exact(f, f.sub(magic_ref, q3))
        s3 = exact(f, f.fma(nk3, U, s))
        nqs.append(nk3)
        xh, xl = f.two_sum(s3, e)                       # exact, renormalised
    else:
        # design B: the mid pieces join the lower ones, summed with the
        # double-word accuracy only; fI is exact
        lows = mids + lows
        xh, xl = fI, None
    f.probes.update(xh=xh)

    f.phase = "red-lower"
    lows.sort(key=lambda v: -v.mag)
    lh = ll = None
    acc_need = need + p                     # below this a plain add is fine
    for v in lows:
        if lh is None:
            lh = v.ref
            lhmag = v.mag
            continue
        if v.mag > acc_need:
            lh, e = f.two_sum(lh, v.ref)
            ll = e if ll is None else f.add(ll, e)
        else:
            ll = v.ref if ll is None else f.add(ll, v.ref)
    if variant == "B":
        # B: the coarse fraction and everything else; the lower sum is a
        # double word, its quadrant bits taken out once
        s, e = f.two_sum(xh, lh)
        if ll is not None:
            e = f.add(e, ll)
        q3 = data(f, f.fma(s, V, magic_ref))
        nk3 = exact(f, f.sub(magic_ref, q3))
        s3 = exact(f, f.fma(nk3, U, s))
        nqs.append(nk3)
        th, tl = f.two_sum(s3, e)
    else:
        # A: the exact part plus the lower double word (TwoSum of the
        # highs, the lows added, Fast2Sum); the lower part is below the
        # bottom, so no cancellation it causes reaches past u^2 |t|
        s, e = f.two_sum(xh, lh)
        lo = xl if ll is None else f.add(xl, ll)
        e = f.add(e, lo)
        th, tl = f.fast_two_sum(s, e)
    f.probes.update(th=th, tl=tl)

    f.phase = "red-scale"
    th = exact(f, f.mul(th, V))
    tl = exact(f, f.mul(tl, V))
    ph, pl = pio2_words(fmt, 2)
    PH, PL = f.w(ph, "PIO2H"), f.w(pl, "PIO2L")
    rh = f.mul(th, PH)
    nre = f.fma(f.neg(th), PH, rh)                      # rh - th PH
    rl = f.fma(th, PL, f.fma(tl, PH, f.neg(nre)))
    rh, rl = f.fast_two_sum(rh, rl)
    # the quadrant: n = -(sum of the -k), as MAGIC + n
    nsum = nqs[0]
    for v in nqs[1:]:
        nsum = exact(f, f.add(nsum, v))
    q = exact(f, f.sub(magic_ref, nsum))                # MAGIC + n
    f.phase = "red-small"
    # the reduction is of |x|: M carries no sign. sin and tan are odd and
    # cos even, so the routine applies x's sign with the quadrant's, to
    # the double word before its one rounding (rounding is not symmetric
    # under rdn and rup)
    ax = f.iand(x, f.wi(fmt.sign_mask ^ ((1 << fmt.width) - 1)))
    small = f.cmplt(ax, f.w(enc(fmt, _pio4(), RDN), "PIO4D"))
    rh = f.sel(ax, rh, small)
    rl = f.sel(f.w(0, "ZERO"), rl, small)
    q = f.sel(magic_ref, q, small)
    f.probes.update(rh=rh, rl=rl, q=q, small=small)
    return {"rh": rh, "rl": rl, "q": q, "small": small}


def _pio4():
    from m2const import pi_frac
    return pi_frac() / 4


def audit(f, xa):
    """Every instruction f.meta["exact"] claims exact, checked on lane xa
    against the exact operation on its operands' exact values.
    -> [(index, op name, phase)] of the failures (an empty list holds)."""
    # the claims hold refs of the body as built, which prune() keeps as
    # f.all_body
    body, phases, _probes = f.all_body if hasattr(f, "all_body") else (
        f.body, f.phase_of, f.probes)
    fmt = f.fmt
    vals, get = run_body(fmt, body, f.allwords, xa)
    claims = f.meta.get("exact", set())
    bad = []
    for ref in claims:
        i = ref[1]
        op, r, srcs = body[i]
        try:
            a = [dec(fmt, get(s)) for s in srcs]
            got = dec(fmt, vals[i])
        except ValueError:
            continue                     # a NaN or infinity: not a main lane
        if op == sf.OP_ADD:
            want = a[0] + a[1]
        elif op == sf.OP_SUB:
            want = a[0] - a[1]
        elif op == sf.OP_MUL:
            want = a[0] * a[1]
        elif op == sf.OP_FMA:
            want = a[0] * a[1] + a[2]
        else:
            continue
        if got != want:
            bad.append((i, sf.OP_NAMES[op], phases[i]))
    return bad
