# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""symmetry_check.py - the reductions of a sweep's space, tested on the golden model.

python/cft_golden is the authority (CLAUDE.md), so every reduction is first a claim about
the GOLDEN function and is held to it here, by EXHAUSTION on tiny formats of the same
family (e4m3: width 8, p = 4; e5m6: width 12, p = 7; the model takes any (exp_w, man_w),
and python/tests/test_tiny_formats.py already sweeps 8-bit formats). A tiny-format
exhaustion proves the statement for that format only; for p = 24 and p = 53 the statement
rests on the argument written beside each claim, which this script does not replace. That
difference is the PROVED / PLAUSIBLE split of the study: what is shown here is PROVED for
the model at the tiny format and checked on samples at fp32, fp64 and fp128; whether the
TILE honours the same structure is a claim about its RTL that nothing here tests.

  G1  sign mirror: negating an operand mirrors the rounding attribute (rdn <-> rup)
  G2  mode folding: for a positive result rdn equals rtz, for a negative one rup does
  G3  RMM against RNE: for division they differ ONLY where the exact quotient is below the
      smallest normal (Dutton et al., arXiv:2404.00387, prove no exact midpoint for
      division; subnormal results, where the rounding grid is coarser, are the exception
      tested here); for square root they never differ; for roundToIntegral they do
  G4  scale invariance: dividing, square root and remainder commute with scaling by a
      power of two (2^k, 4^k, 2^k on both) whenever the results stay in the normal core;
      the violations OUTSIDE the core are counted: they are the edge strips
  G5  the structure of rounding: convertFormat and roundToIntegral equal a decision rule
      written here from the definitions (kept bits, the class of the dropped bits - zero,
      below half, half, above half - and the kept lsb), on every finite source encoding
  G6  the sizes that remain, and what they cost at the stress run's measured rates

CONTROLS: each group has a deliberately wrong version that must be caught.
usage: python symmetry_check.py      (reads stress-final-item-rates.txt beside it)
"""
import math
import os
import random
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))

from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.formats import FpFormat, FP32, FP64, FP128  # noqa: E402

RND = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP, sf.RND_RMM)
NAME = sf.RND_NAMES
MIRROR = {sf.RND_RNE: sf.RND_RNE, sf.RND_RTZ: sf.RND_RTZ, sf.RND_RDN: sf.RND_RUP, sf.RND_RUP: sf.RND_RDN, sf.RND_RMM: sf.RND_RMM}
E4M3 = FpFormat("e4m3", 4, 3)
E5M6 = FpFormat("e5m6", 5, 6)
YEAR = 365.25 * 86400.0
fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-92s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


# ---- helpers ---------------------------------------------------------------------------
def neg(fmt, x):
    return x ^ fmt.sign_mask


def is_nan(fmt, x):
    return sf.is_nan(fmt, x)


def same(fmt, r1, r2):
    """(bits, flags) equality, NaN results as a class (the model canonicalises payloads)."""
    (b1, f1), (b2, f2) = r1, r2
    if f1 != f2:
        return False
    if is_nan(fmt, b1) and is_nan(fmt, b2):
        return True
    return b1 == b2


def value(fmt, x):
    """The exact value of a finite encoding as a Fraction."""
    u = sf.unpack(fmt, x)
    if u.kind in (sf.ZERO,):
        return Fraction(0)
    v = Fraction(u.m) * (Fraction(2) ** u.e)
    return -v if u.sign else v


def finite(fmt, nonzero=True):
    out = []
    for x in range(1 << fmt.width):
        u = sf.unpack(fmt, x)
        if u.kind in (sf.NAN, sf.INF):
            continue
        if nonzero and u.kind == sf.ZERO:
            continue
        out.append(x)
    return out


def scale_exact(fmt, x, k):
    """x * 2^k as an encoding if that is exactly representable and nonzero, else None."""
    bits, fl = sf.scaleb(fmt, x, k, sf.RND_RNE)
    u = sf.unpack(fmt, bits)
    if fl != 0 or u.kind in (sf.ZERO, sf.INF, sf.NAN):
        return None
    return bits


def exp_field(fmt, x):
    return (x >> fmt.man_w) & fmt.exp_mask


def is_normal(fmt, x):
    e = exp_field(fmt, x)
    return 0 < e < fmt.exp_mask


def in_core(fmt, x):
    """A finite nonzero NORMAL result at least one binade below the overflow edge."""
    e = exp_field(fmt, x)
    return 0 < e < fmt.exp_mask - 1


# ---- G1, G2 ------------------------------------------------------------------------------
def g1_g2():
    print("== G1, G2. sign mirror and mode folding (e4m3, every encoding and every pair)")
    fmt = E4M3
    allx = list(range(1 << fmt.width))
    # division, every pair
    v1 = v1c = v2 = v2c = 0
    n_pairs = 0
    for a in allx:
        for b in allx:
            n_pairs += 1
            for m in RND:
                r = sf.div(fmt, a, b, m)
                rm = sf.div(fmt, neg(fmt, a), b, MIRROR[m])
                want = (r[0] if is_nan(fmt, r[0]) else neg(fmt, r[0]), r[1])
                if not same(fmt, rm, want):
                    v1 += 1
                # the control: the wrong mirror (swap rne and rmm, leave rdn and rup)
                wrong = {sf.RND_RNE: sf.RND_RMM, sf.RND_RMM: sf.RND_RNE, sf.RND_RTZ: sf.RND_RTZ, sf.RND_RDN: sf.RND_RDN, sf.RND_RUP: sf.RND_RUP}[m]
                rw = sf.div(fmt, neg(fmt, a), b, wrong)
                if not same(fmt, rw, want):
                    v1c += 1
            # folding: the sign of the result decides which directed mode is truncation
            r_rtz = sf.div(fmt, a, b, sf.RND_RTZ)
            if not is_nan(fmt, r_rtz[0]):
                s = (r_rtz[0] >> (fmt.width - 1)) & 1
                fold = sf.RND_RDN if s == 0 else sf.RND_RUP
                if not same(fmt, sf.div(fmt, a, b, fold), r_rtz):
                    v2 += 1
                wrongfold = sf.RND_RUP if s == 0 else sf.RND_RDN
                if not same(fmt, sf.div(fmt, a, b, wrongfold), r_rtz):
                    v2c += 1
    print("   div   : %d pairs x 5 attributes; sign-mirror violations %d; (rdn for s=0, rup for s=1) vs rtz violations %d" % (n_pairs, v1, v2))
    check("div: div(-a, b, mirror(m)) = -div(a, b, m), bits and flags, for every pair and attribute", v1 == 0)
    check("div: for a positive result rdn = rtz and for a negative one rup = rtz, every pair", v2 == 0)
    check("CONTROL: the mirror with rne and rmm swapped is NOT a symmetry", v1c > 0, "(%d violations)" % v1c)
    check("CONTROL: folding the OTHER directed mode onto rtz is NOT valid", v2c > 0, "(%d violations)" % v2c)
    # sqrt, scaleb, rint, convert: mirror on every encoding
    for label, fn in (
        ("sqrt (positive operands only: a negative operand is an invalid class)", None),
    ):
        pass
    bad = 0
    for a in allx:
        for m in RND:
            r = sf.round_int(fmt, a, m, True)
            rm = sf.round_int(fmt, neg(fmt, a), MIRROR[m], True)
            want = (r[0] if is_nan(fmt, r[0]) else neg(fmt, r[0]), r[1])
            if not same(fmt, rm, want):
                bad += 1
    check("rint (exact variant): rint(-x, mirror(m)) = -rint(x, m) for every encoding and attribute", bad == 0, "(%d violations)" % bad)
    bad = 0
    for a in allx:
        for n in range(-18, 19):
            for m in RND:
                r = sf.scaleb(fmt, a, n, m)
                rm = sf.scaleb(fmt, neg(fmt, a), n, MIRROR[m])
                want = (r[0] if is_nan(fmt, r[0]) else neg(fmt, r[0]), r[1])
                if not same(fmt, rm, want):
                    bad += 1
    check("scaleb: scaleb(-x, n, mirror(m)) = -scaleb(x, n, m) for every encoding, n in [-18, 18], attribute", bad == 0, "(%d violations)" % bad)
    src = E5M6
    bad = 0
    for a in range(1 << src.width):
        for m in RND:
            r = sf.convert(src, fmt, a, m)
            rm = sf.convert(src, fmt, neg(src, a), MIRROR[m])
            want = (r[0] if is_nan(fmt, r[0]) else neg(fmt, r[0]), r[1])
            if not same(fmt, rm, want):
                bad += 1
    check("convertFormat e5m6 -> e4m3: mirror holds for every source encoding and attribute", bad == 0, "(%d violations)" % bad)
    bad = 0
    for a in range(1 << fmt.width):
        r = sf.sqrt(fmt, a, sf.RND_RTZ)
        if is_nan(fmt, r[0]):
            continue
        s = (r[0] >> (fmt.width - 1)) & 1
        fold = sf.RND_RDN if s == 0 else sf.RND_RUP
        if not same(fmt, sf.sqrt(fmt, a, fold), r):
            bad += 1
    check("sqrt: for a positive result rdn = rtz (and -0's result keeps its sign), every encoding", bad == 0, "(%d violations)" % bad)
    # the same at the real formats, on samples
    rng = random.Random(7)
    bad = tot = 0
    for fm in (FP32, FP64, FP128):
        for _ in range(400):
            a, b = rng.getrandbits(fm.width), rng.getrandbits(fm.width)
            for m in RND:
                r = sf.div(fm, a, b, m)
                rm = sf.div(fm, neg(fm, a), b, MIRROR[m])
                want = (r[0] if is_nan(fm, r[0]) else neg(fm, r[0]), r[1])
                tot += 1
                bad += not same(fm, rm, want)
    check("div: the mirror on 400 random pairs x 5 attributes at each of fp32, fp64, fp128 (samples)", bad == 0, "(%d of %d)" % (bad, tot))
    print()


# ---- G3 ----------------------------------------------------------------------------------
def g3():
    print("== G3. roundTiesToAway against roundTiesToEven")
    fmt = E4M3
    allx = list(range(1 << fmt.width))
    diff = []
    for a in allx:
        for b in allx:
            r1, r2 = sf.div(fmt, a, b, sf.RND_RNE), sf.div(fmt, a, b, sf.RND_RMM)
            if not same(fmt, r1, r2):
                diff.append((a, b))
    minnorm = Fraction(2) ** fmt.emin
    outside = []
    for a, b in diff:
        ua, ub = sf.unpack(fmt, a), sf.unpack(fmt, b)
        q = abs(value(fmt, a) / value(fmt, b))
        if not q < minnorm:
            outside.append((a, b))
    print("   div  e4m3: %d of 65,536 pairs give different results under rne and rmm; %d of them have an exact quotient >= 2^emin" % (len(diff), len(outside)))
    check("div: RMM = RNE on EVERY pair whose exact quotient is >= the smallest normal (no midpoint there)", not outside, "(%d outside)" % len(outside))
    check("div: the pairs where RMM and RNE differ exist, all with a quotient below the smallest normal", len(diff) > 0 and not outside, "(%d pairs)" % len(diff))
    bad = sum(1 for a in allx if not same(fmt, sf.sqrt(fmt, a, sf.RND_RNE), sf.sqrt(fmt, a, sf.RND_RMM)))
    check("sqrt: RMM = RNE on every encoding of e4m3 (an inexact root is never a midpoint)", bad == 0, "(%d differ)" % bad)
    bad_big = 0
    rng = random.Random(11)
    for fm in (FP32, FP64):
        for _ in range(3000):
            a = rng.getrandbits(fm.width)
            if not same(fm, sf.sqrt(fm, a, sf.RND_RNE), sf.sqrt(fm, a, sf.RND_RMM)):
                bad_big += 1
    check("sqrt: RMM = RNE on 3,000 random operands at each of fp32 and fp64 (samples)", bad_big == 0, "(%d differ)" % bad_big)
    n_rint = sum(1 for a in allx if not same(fmt, sf.round_int(fmt, a, sf.RND_RNE, True), sf.round_int(fmt, a, sf.RND_RMM, True)))
    check("CONTROL: for roundToIntegral RMM and RNE DO differ (ties exist), so the comparison can see a difference", n_rint > 0,
          "(%d of 256 encodings)" % n_rint)
    print()


# ---- G4 ----------------------------------------------------------------------------------
def g4():
    print("== G4. scale invariance with its preconditions, and the edge strips (e4m3, every finite nonzero pair)")
    fmt = E4M3
    fin = finite(fmt)
    KS = range(-8, 9)

    lo, hi = Fraction(2) ** fmt.emin, Fraction(2) ** fmt.emax

    def run_div(m):
        # The CORE is defined by the EXACT quotient: 2^emin <= |a/b| < 2^emax, for the pair and for
        # the scaled pair. (Defining it by the rounded result is wrong at the lower edge: a quotient
        # just below 2^emin can round UP into the normal range, having been rounded on the coarser
        # subnormal grid, and scale invariance then fails although the result is normal.)
        core_checked = core_bad = edge_checked = edge_bad = 0
        for a in fin:
            va = abs(value(fmt, a))
            for b in fin:
                vb = abs(value(fmt, b))
                q = va / vb
                r = sf.div(fmt, a, b, m)
                for k in KS:
                    a2 = scale_exact(fmt, a, k)
                    if a2 is None:
                        continue
                    q2 = q * (Fraction(2) ** k)
                    r2 = sf.div(fmt, a2, b, m)
                    rk = scale_exact(fmt, r[0], k)
                    in1, in2 = (lo <= q < hi), (lo <= q2 < hi)
                    if in1 and in2:
                        core_checked += 1
                        if rk is None or r2[0] != rk or r2[1] != r[1]:
                            core_bad += 1
                    elif in1:
                        # the pair is in the core and the scaled pair has left it
                        edge_checked += 1
                        if rk is None or r2[0] != rk or r2[1] != r[1]:
                            edge_bad += 1
        return core_checked, core_bad, edge_checked, edge_bad
    tot = [0, 0, 0, 0]
    for m in (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP):
        r = run_div(m)
        tot = [x + y for x, y in zip(tot, r)]
        print("   div %s: scaled pairs with both results in the core: %7d, violations %d; base in the core and scaled result OUTSIDE it: %7d, differing %d"
              % (NAME[m], r[0], r[1], r[2], r[3]))
    check("div: a pair and its scaled pair whose EXACT quotients are both in [2^emin, 2^emax) give scaled results, bits and flags",
          tot[1] == 0 and tot[0] > 100000, "(%d checked, %d violations)" % (tot[0], tot[1]))
    check("div: when the scaled pair's quotient leaves that core, scale invariance FAILS (the edge strips are real)", tot[3] > 0,
          "(%d of %d scaled pairs differ)" % (tot[3], tot[2]))
    # sqrt: every positive finite nonzero input, subnormals included; shifts of 2k
    core = bad = 0
    pos = [a for a in fin if not (a >> (fmt.width - 1)) & 1]
    for a in pos:
        for m in (sf.RND_RNE, sf.RND_RTZ, sf.RND_RUP):
            r = sf.sqrt(fmt, a, m)
            for k in range(-6, 7):
                a2 = scale_exact(fmt, a, 2 * k)
                if a2 is None:
                    continue
                r2 = sf.sqrt(fmt, a2, m)
                rk = scale_exact(fmt, r[0], k)
                core += 1
                if rk is None or r2[0] != rk or r2[1] != r[1]:
                    bad += 1
    check("sqrt: sqrt(a 4^k) = sqrt(a) 2^k for EVERY positive input incl. subnormals, 3 attributes, k in [-6, 6]", bad == 0 and core > 2000,
          "(%d checked, %d violations)" % (core, bad))
    # rem: both operands scaled by the same 2^k
    core = bad = 0
    for a in fin:
        for b in fin:
            r = sf.remainder(fmt, a, b)
            for k in range(-8, 9):
                a2, b2 = scale_exact(fmt, a, k), scale_exact(fmt, b, k)
                if a2 is None or b2 is None:
                    continue
                r2 = sf.remainder(fmt, a2, b2)
                rk = (scale_exact(fmt, r[0], k) if (r[0] & ~fmt.sign_mask) != 0 else r[0] ^ 0)
                core += 1
                if (r[0] & ~fmt.sign_mask) == 0:
                    ok = (r2[0] & ~fmt.sign_mask) == 0 and r2[0] == r[0] and r2[1] == r[1]
                else:
                    ok = rk is not None and r2[0] == rk and r2[1] == r[1]
                if not ok:
                    bad += 1
    check("rem: remainder(a 2^k, b 2^k) = remainder(a, b) 2^k for every pair and k in [-8, 8] (exact, no result edge)", bad == 0 and core > 100000,
          "(%d checked, %d violations)" % (core, bad))
    print()


# ---- G5 ----------------------------------------------------------------------------------
def decide(sign, mode, cls, lsb):
    """Round the MAGNITUDE up? cls: 0 exact, 1 below half, 2 exactly half, 3 above half."""
    if mode == sf.RND_RTZ or cls == 0:
        return 0
    if mode == sf.RND_RNE:
        return 1 if (cls == 3 or (cls == 2 and lsb == 1)) else 0
    if mode == sf.RND_RMM:
        return 1 if cls >= 2 else 0
    if mode == sf.RND_RUP:
        return 1 if sign == 0 else 0
    if mode == sf.RND_RDN:
        return 1 if sign == 1 else 0
    raise ValueError(mode)


def decide_wrong(sign, mode, cls, lsb):
    """The control: ties-to-even forgotten (a tie always rounds up in magnitude)."""
    if mode == sf.RND_RNE:
        return 1 if cls >= 2 else 0
    return decide(sign, mode, cls, lsb)


def encode(fmt, sign, R, u):
    """The encoding of (-1)^sign * R * 2^u for an integer R >= 0, or None when it overflows."""
    if R == 0:
        return sign << (fmt.width - 1)
    top = R.bit_length() - 1 + u
    if top < fmt.emin:
        # subnormal: u is fixed at emin - man_w, R < 2^man_w
        if u != fmt.emin - fmt.man_w or R >= (1 << fmt.man_w):
            return None
        return (sign << (fmt.width - 1)) | R
    if top > fmt.emax:
        return None
    frac = (R << (fmt.man_w - (R.bit_length() - 1))) & fmt.man_mask if R.bit_length() - 1 <= fmt.man_w else None
    if frac is None:
        return None
    return (sign << (fmt.width - 1)) | ((top + fmt.bias) << fmt.man_w) | frac


def predict_convert(src, dst, x, mode, dec):
    """The destination encoding by the decision rule alone, or None for a special or an overflow."""
    u = sf.unpack(src, x)
    if u.kind not in (sf.NORM, sf.SUB):
        return None
    m, e = u.m, u.e                      # value = m * 2^e, m a positive integer
    top = m.bit_length() - 1 + e
    ulp = max(top - dst.man_w, dst.emin - dst.man_w)
    dropped = ulp - e
    if dropped <= 0:
        R, cls, lsb = m << (-dropped), 0, 0
    else:
        kept, rem = m >> dropped, m & ((1 << dropped) - 1)
        half = 1 << (dropped - 1)
        cls = 0 if rem == 0 else (1 if rem < half else (2 if rem == half else 3))
        lsb = kept & 1
        R = kept
        lsb = kept & 1
        R = kept + dec(u.sign, mode, cls, lsb)
    return encode(dst, u.sign, R, ulp)


def predict_rint(fmt, x, mode, dec):
    u = sf.unpack(fmt, x)
    if u.kind not in (sf.NORM, sf.SUB):
        return None
    m, e = u.m, u.e
    if e >= 0:
        return x
    dropped = -e
    kept, rem = m >> dropped, m & ((1 << dropped) - 1)
    half = 1 << (dropped - 1)
    cls = 0 if rem == 0 else (1 if rem < half else (2 if rem == half else 3))
    R = kept + dec(u.sign, mode, cls, kept & 1)
    return encode(fmt, u.sign, R, 0)


def g5():
    print("== G5. the structure of rounding: the golden model equals a decision rule (kept bits, class of the dropped bits, lsb)")
    src, dst = E5M6, E4M3
    n = tested = bad = badw = 0
    classes = set()
    for x in range(1 << src.width):
        for m in RND:
            p = predict_convert(src, dst, x, m, decide)
            if p is None:
                continue
            tested += 1
            got = sf.convert(src, dst, x, m)
            if got[0] != p:
                bad += 1
            pw = predict_convert(src, dst, x, m, decide_wrong)
            if pw is not None and got[0] != pw:
                badw += 1
    # count what the decision depends on
    for x in range(1 << src.width):
        u = sf.unpack(src, x)
        if u.kind not in (sf.NORM, sf.SUB):
            continue
        top = u.m.bit_length() - 1 + u.e
        ulp = max(top - dst.man_w, dst.emin - dst.man_w)
        dropped = ulp - u.e
        if dropped > 0:
            rem = u.m & ((1 << dropped) - 1)
            half = 1 << (dropped - 1)
            cls = 0 if rem == 0 else (1 if rem < half else (2 if rem == half else 3))
            classes.add((u.sign, top, dropped, cls))
    print("   convertFormat e5m6 -> e4m3: %d (encoding, attribute) cases predicted (finite, no overflow); the decision needs only"
          " (sign, exponent, class) = %d classes plus the kept lsb, against 4,096 source encodings" % (tested, len(classes)))
    check("convertFormat: result bits = the decision rule on (kept, class, lsb), every finite source encoding and attribute", bad == 0 and tested > 14000,
          "(%d tested, %d differ)" % (tested, bad))
    check("CONTROL: a rule that forgets ties-to-even (a tie always rounds up) is NOT the model's convertFormat", badw > 0, "(%d differ)" % badw)
    fmt = E5M6
    tested = bad = badw = 0
    for x in range(1 << fmt.width):
        for m in RND:
            p = predict_rint(fmt, x, m, decide)
            if p is None:
                continue
            tested += 1
            got = sf.round_int(fmt, x, m, False)
            if got[0] != p:
                bad += 1
            pw = predict_rint(fmt, x, m, decide_wrong)
            if pw is not None and got[0] != pw:
                badw += 1
    check("roundToIntegral: result bits = the decision rule on (kept, class, lsb), every finite encoding of e5m6 and attribute", bad == 0 and tested > 15000,
          "(%d tested, %d differ)" % (tested, bad))
    check("CONTROL: the rule that forgets ties-to-even is NOT the model's roundToIntegral", badw > 0, "(%d differ)" % badw)
    print()


# ---- G6 ----------------------------------------------------------------------------------
def read_rates():
    rates = {}
    with open(os.path.join(HERE, "stress-final-item-rates.txt"), encoding="utf-8") as fh:
        next(fh)
        for ln in fh:
            f = ln.split()
            if f[1] == "quad":
                rates[f[0]] = (int(f[6]), int(f[7]))
    return rates


def div_keys(fmt):
    """The number of distinct (significand pair, rounding strip) keys the pairs of a format
    reach, against the bound (1 + strips) * 4^(p-1). Strip 0 is the core (normal result);
    s = 1 .. p + 1 the subnormal result strips (the rounding position moved up s places);
    'O' the overflow strip. A key is what a scaling-reduced sweep must visit."""
    p = fmt.prec
    keys = set()
    fin = finite(fmt)
    for a in fin:
        ua = sf.unpack(fmt, a)
        for b in fin:
            ub = sf.unpack(fmt, b)
            ma, mb = ua.m << (p - ua.m.bit_length()), ub.m << (p - ub.m.bit_length())
            # exact quotient exponent: floor(log2(|a| / |b|))
            q = abs(value(fmt, a) / value(fmt, b))
            eq = q.numerator.bit_length() - q.denominator.bit_length()
            if Fraction(2) ** eq > q:
                eq -= 1
            if eq > fmt.emax:
                strip = "O"
            elif eq >= fmt.emin:
                strip = 0
            else:
                strip = min(fmt.emin - eq, p + 1)
            keys.add((ma, mb, strip))
    return len(keys), (1 + (p + 1) + 1) * (1 << (2 * (p - 1)))


def g6():
    print("== G6. the sizes that remain, and what they cost at the stress run's measured rates (COMPUTED)")
    n, bound = div_keys(E4M3)
    print("   division at e4m3: %d distinct (significand pair, strip) keys are reached by the pairs; the bound (1 + (p+1) + 1) 4^(p-1) = %d" % (n, bound))
    check("div: the number of (significand pair, strip) keys reached is at most (p + 3) 4^(p-1) at e4m3", n <= bound, "(%d <= %d)" % (n, bound))
    rates = read_rates()
    # a sweep's reduced space, level L1 (PROVED for the model, G1-G4), in the unit of the soak's count
    p32, p64 = 24, 53
    magn = 3                                                     # nearest, truncate, away (G1, G2, G3)

    def L1_div(p):
        return magn * (1 + (p + 1) + 1) * (1 << (2 * (p - 1)))   # core + subnormal strips + overflow strip, per magnitude function

    def L1_sqrt(p):
        return magn * (1 << p)                                   # mantissa x exponent parity; subnormals normalise into it

    def L1_rint(p):
        return magn * p * (1 << (p - 1))                         # |x| in [1/2, 2^(p-1)): p binades of 2^(p-1) significands

    def L1_conv(ps, pd):
        return magn * (1 + (pd + 1) + 1) * (1 << (ps - 1))       # normal core + subnormal strips + overflow strip

    def L1_cvtto(p):
        return 2 * (p + 12) * (1 << (p - 1)) * magn               # e in [-1, 63]: 65 binades; negative targets unsigned: x2

    def L1_rem(p, ew):
        gap = (1 << ew) + p - 5          # emax - emin + p - 2, clause5.c's bound on the host's walk: 275 at fp32, 2,096 at fp64
        return (1 << (2 * (p - 1))) * gap                        # significand pairs x exponent gaps

    rows = []

    def add(name, space0, space1, item, workers_per_quad, note):
        rate = rates[item][0]
        sec = space1 / (workers_per_quad * rate)
        rows.append((name, space0, space1, sec / YEAR, note))

    add("div32", 4 * (1 << 64), L1_div(p32), "div32-rne", 4, "tile")
    add("div64", 4 * (1 << 128), L1_div(p64), "div64-rne", 4, "tile")
    add("sqrt64", 4 * (1 << 64), L1_sqrt(p64), "sqrt64-rne", 4, "tile")
    add("rint64", 5 * (1 << 64), L1_rint(p64), "rint64-rne", 4, "tile")
    add("conv64to32", 4 * (1 << 64), L1_conv(p64, 24), "conv64to32-rne", 4, "host")
    add("cvtto64", 5 * (1 << 64), L1_cvtto(p64), "cvtto64-rne", 4, "host")
    add("rem32", 1 * (1 << 64), L1_rem(p32, 8), "rem32", 4, "host")
    add("rem64", 1 * (1 << 128), L1_rem(p64, 11), "rem64", 4, "host")
    add("scaleb64 (wide)", 4 * (1 << 64) * 4198, magn * (1 + (p64 + 1) + 1) * (1 << (p64 - 1)), "scaleb64-rne", 4, "tile")
    print("   level L1 = the sign, attribute and scale reductions of G1-G4 (PROVED for the golden model at e4m3; the arguments for p = 24 and 53 are in the study)")
    print("   %-16s %-5s %12s %12s %10s %16s" % ("space", "runs", "L0 (log2)", "L1 (log2)", "L0 / L1", "L1, one quad"))
    for name, s0, s1, yrs, note in rows:
        print("   %-16s %-5s %12.1f %12.1f %10.2e %16s" % (name, note, math.log2(s0), math.log2(s1), s0 / s1,
                                                          ("%.3g y" % yrs) if yrs >= 1 else ("%.1f d" % (yrs * 365.25))))
    print()
    print("   how many quads (four workers: tiles for 'tile' items, cores for 'host' items) finish the reduced sweep in a decade, a year, a month (COMPUTED):")
    print("   %-16s %-5s %14s %14s %14s %16s" % ("space", "runs", "quads, 10 y", "quads, 1 y", "quads, 1 month", "weekends of one card"))
    weekend_y = 219550.0 / YEAR
    for name, s0, s1, yrs, note in rows:
        if yrs > 1e6:
            print("   %-16s %-5s %14s %14s %14s %16s" % (name, note, "-", "-", "-", "-"))
            continue
        print("   %-16s %-5s %14d %14d %14d %16s" % (name, note, math.ceil(yrs / 10.0), math.ceil(yrs), math.ceil(yrs * 12.0),
                                                    "{:,}".format(int(yrs / weekend_y))))
    d32 = [r for r in rows if r[0] == "div32"][0]
    print()
    print("   div32's reduced space: %d = 3 magnitude functions x 27 strips-and-core x 2^46; one quad needs %.3g years (L0: 3.0e5 years)" % (d32[2], d32[3]))
    check("div32's reduced sweep is under 100 quad-years (the raw one is over 300,000)", d32[3] < 100 and d32[1] / d32[2] > 1e4, "(%.1f y)" % d32[3])
    check("every reduced space is smaller than its raw space", all(r[2] < r[1] for r in rows))
    # the L2 level: class representatives
    print()
    print("   level L2 (PLAUSIBLE, a structural assumption about the implementation; G5 shows the model's structure): the result depends on")
    print("   (sign, exponent, class of the dropped bits, kept lsb, kept all-ones), so a representative per class plus a walking-ones set over")
    print("   the dropped and kept bits covers it. conv64to32: %d exponents x 4 classes x (lsb 2 x all-ones 2 + %d walking bits) x 2 signs x 3 magnitude"
          % (254 + 25 + 2, 52))
    l2 = (254 + 25 + 2) * 4 * (4 + 52) * 2 * 3
    print("   functions = %d cases; at the measured conv64to32 rate of %.1f M/s (a host item: one core) that is %.2f seconds" %
          (l2, rates["conv64to32-rne"][0] / 1e6, l2 / rates["conv64to32-rne"][0]))
    check("conv64to32's class-level sweep (a few hundred thousand cases) takes seconds, not years", l2 / rates["conv64to32-rne"][0] < 120, "(%d cases)" % l2)
    print()


def main():
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    print("symmetry_check.py: the reductions of a sweep's space, tested on the golden model")
    print()
    g1_g2()
    g3()
    g4()
    g5()
    g6()
    print("symmetry_check: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
