# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""hardcase_div.py - the hardest-to-round divisions (and square roots), constructed instead of searched for.

Division x / y of p-bit significands mx, my (integers in [2^(p-1), 2^p)): take mx >= my, so
the quotient Q = mx / my is in [1, 2) and the representable results are j 2^(1-p). Midpoints
between them are odd multiples of 2^-p. The distance of Q to the nearest midpoint is
    |N| / (my 2^p),   N = mx 2^p  -  c my,  c the odd integer nearest mx 2^p / my,
and N is a nonzero integer unless Q is exactly a midpoint, which for division of normal
operands never happens (Dutton et al., arXiv:2404.00387; symmetry_check.py G3 sees ties only
in the subnormal-result strip). So |N| >= 1: the closest approach to a midpoint is N = +-1,
at distance 1/(my 2^p). For my ODD, mx 2^p = +-1 (mod my) has the solution mx = +-2^-p mod my:
a dividend at the closest possible approach, found with one modular inverse, no sweep. The
same for the directed roundings, where the boundary is a representable number: N' = mx 2^(p-1)
- j my = +-1.

This script
  H1  constructs those dividends for random odd divisors at p = 24, 53, 113 and verifies,
      in exact integer arithmetic, that |N| = 1 (the construction succeeds for about 39% of
      divisors per sign, a count MEASURED here);
  H2  runs the golden model's division on them under all five attributes against an
      INDEPENDENT exact arbiter (Fractions, the decision rule of symmetry_check.py), bits and
      the inexact flag;
  H3  measures how close the campaign's own sampler (host/tools/divsqrt_soak.c's banded
      generator, ported in seed_audit.py and held there to the real tool) comes: the least
      |N| / my over its draws, against the expected least for a campaign of 1.45 x 10^10 draws;
  H4  shows the repository's own failure family (a = 1, b = 1 - ulp, python/tests/
      test_sequences.py) is a closest-approach case: its |N| is computed;
  H5  PLANTS a defective division - the quotient computed to g extra bits and rounded
      ties-to-even on those bits alone, ignoring the remainder - and counts what the random
      sampler finds against what the constructed set finds;
  H6  scans every midpoint of fp32 square root for the input nearest its square: the least
      distance is d = 1 (in units of 2^-2p, the least an odd square allows), reached by two
      midpoints, one of them sqrt(1 + ulp), the repository's own failing family; the golden
      model agrees with an exact integer arbiter on them.

usage: python hardcase_div.py
"""
import os
import random
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, HERE)

from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.formats import FP32, FP64, FP128  # noqa: E402
import seed_audit as sa  # noqa: E402  (the port of the tools' sampler, held to the real tool there)

RND = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP, sf.RND_RMM)
fails = 0
CAMPAIGN_DRAWS = 14_498_660_352        # the stress run's div32-rne count (sweep_cost.py, final record)


def check(label, ok, detail=""):
    global fails
    print("CHECK %-96s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


def construct(p, my, target, sign):
    """A dividend significand mx in [my, 2^p) with |N| = 1 for the given target, or None.
    target 'mid': the boundary is a midpoint, N = mx 2^p - c my with c odd.
    target 'rep': the boundary is a representable number, N' = mx 2^(p-1) - j my."""
    if my % 2 == 0:
        return None
    k = p if target == "mid" else p - 1
    inv = pow(2 ** k, -1, my)
    mx0 = (sign * inv) % my
    mx = mx0 + my
    return mx if mx < 2 ** p else None


def N_mid(p, mx, my):
    """The integer N of the midpoint distance for Q = mx / my in [1, 2): |N| = |t - my|, t = mx 2^p mod 2 my."""
    t = (mx << p) % (2 * my)
    return t - my


def N_rep(p, mx, my):
    r = (mx << (p - 1)) % my
    return r if r <= my // 2 else r - my


def exact_round(p, mx, my, mode):
    """The correctly rounded significand of mx / my (positive, Q in [1, 2)), in units of 2^(1-p),
    by exact rational arithmetic and the decision rule from the definitions; returns (J, inexact)
    with J possibly 2^p (a carry into the next binade)."""
    Q = Fraction(mx, my) * (1 << (p - 1))        # Q in units of the grid
    j = Q.numerator // Q.denominator
    frac = Q - j
    if frac == 0:
        return j, False
    cls = 1 if frac < Fraction(1, 2) else (2 if frac == Fraction(1, 2) else 3)
    lsb = j & 1
    if mode == sf.RND_RTZ or mode == sf.RND_RDN:
        up = 0
    elif mode == sf.RND_RUP:
        up = 1
    elif mode == sf.RND_RNE:
        up = 1 if (cls == 3 or (cls == 2 and lsb)) else 0
    else:                                        # RMM
        up = 1 if cls >= 2 else 0
    return j + up, True


def bits_of(fmt, mx, J_or_none=None):
    """Encoding of the value mx 2^(1-p) in [1, 2) (biased exponent = bias)."""
    return (fmt.bias << fmt.man_w) | (mx - (1 << (fmt.prec - 1)))


def result_bits(fmt, J):
    """The encoding of J 2^(1-p), J in [2^(p-1), 2^p]: the carry case J = 2^p is the next binade."""
    p = fmt.prec
    if J == 1 << p:
        return (fmt.bias + 1) << fmt.man_w
    return (fmt.bias << fmt.man_w) | (J - (1 << (p - 1)))


def main():
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    rng = random.Random(2026)
    print("hardcase_div.py: closest-approach divisions, constructed, verified, and measured against the campaign's sampler")
    print()

    # ---- H1 -------------------------------------------------------------------
    print("== H1. construction: one modular inverse a divisor, |N| = 1 verified in exact integers")
    built = {}
    for fmt in (FP32, FP64, FP128):
        p = fmt.prec
        stats = {}
        cases = []
        for target in ("mid", "rep"):
            for sign in (+1, -1):
                ok = tot = bad = 0
                for _ in range(3000):
                    my = rng.randrange(1 << (p - 1), 1 << p) | 1
                    mx = construct(p, my, target, sign)
                    tot += 1
                    if mx is None:
                        continue
                    ok += 1
                    n = N_mid(p, mx, my) if target == "mid" else N_rep(p, mx, my)
                    if abs(n) != 1 or not (my <= mx < (1 << p)):
                        bad += 1
                    else:
                        cases.append((mx, my, target, n))
                stats[(target, sign)] = (ok, tot, bad)
        built[fmt.name] = cases
        for (target, sign), (ok, tot, bad) in stats.items():
            print("   %-6s %-3s %+d: built for %4d of %d odd divisors (%.1f%%), |N| = 1 verified on all of them (%d wrong)" % (
                fmt.name, target, sign, ok, tot, 100.0 * ok / tot, bad))
        check("%s: every constructed dividend has |N| = 1 exactly and lies in [my, 2^p)" % fmt.name,
              all(s[2] == 0 for s in stats.values()) and len(cases) > 3000)
        rate = sum(s[0] for k, s in stats.items() if k[0] == "mid") / sum(s[1] for k, s in stats.items() if k[0] == "mid")
        check("%s: the construction succeeds for 30 to 45%% of odd divisors per sign (about 2 ln 2 - 1 = 38.6%%)" % fmt.name,
              0.30 < rate < 0.47, "(%.1f%%)" % (100 * rate))
    print()

    # ---- H2 -------------------------------------------------------------------
    print("== H2. the golden model's division on the closest-approach cases against an independent exact arbiter")
    for fmt in (FP32, FP64, FP128):
        p = fmt.prec
        cases = built[fmt.name]
        rng2 = random.Random(5)
        sample = rng2.sample(cases, 300 if fmt.name != "fp128" else 120)
        bad = n = 0
        for mx, my, target, nn in sample:
            a = bits_of(fmt, mx)
            b = bits_of(fmt, my)
            for m in RND:
                got = sf.div(fmt, a, b, m)
                J, inexact = exact_round(p, mx, my, m)
                want = (result_bits(fmt, J), sf.FLAG_INEXACT if inexact else 0)
                n += 1
                if got != want:
                    bad += 1
        check("%s: golden div = exact arbiter on %d constructed pairs x 5 attributes (bits and flags)" % (fmt.name, len(sample)), bad == 0,
              "(%d cases, %d differ)" % (n, bad))
    # the arbiter can disagree: a wrong decision rule (ties always up) must differ from the model on a tie
    bad = 0
    for mx, my, target, nn in built["fp32"][:200]:
        J, inexact = exact_round(24, mx, my, sf.RND_RNE)
        a, b = bits_of(FP32, mx), bits_of(FP32, my)
        got = sf.div(FP32, a, b, sf.RND_RTZ)[0]
        if got != result_bits(FP32, J) and result_bits(FP32, J) != result_bits(FP32, exact_round(24, mx, my, sf.RND_RTZ)[0]):
            bad += 1
    check("CONTROL: the arbiter's RNE answer differs from the model's RTZ answer on the near-midpoint cases (the comparison can see)",
          bad > 0, "(%d of 200)" % bad)
    print()

    # ---- H3 -------------------------------------------------------------------
    print("== H3. how close does the campaign's sampler come? (the least |N| / my over its draws)")
    print("   rho = |N| / my in [0, 1] is the distance to the nearest midpoint in units of half an ulp; its least possible value is 1 / my.")
    print("   %-6s %12s %16s %20s %20s %22s" % ("format", "draws here", "least rho here", "least possible rho", "expected hits of rho = 1/my", "in a 1.45e10-draw item"))
    for fmt, dr in ((FP32, 400000), (FP64, 400000)):
        p = fmt.prec
        r = sa.Rng(0x50AC0001)
        least = 1.0
        used = 0
        for _ in range(dr):
            a = sa.banded32(r) if fmt is FP32 else sa.banded64(r)
            b = sa.banded32(r) if fmt is FP32 else sa.banded64(r)
            mw = fmt.man_w
            ea, eb = (a >> mw) & fmt.exp_mask, (b >> mw) & fmt.exp_mask
            if ea in (0, fmt.exp_mask) or eb in (0, fmt.exp_mask):
                continue                                  # the generator's band operands are subnormal or special: not a significand pair
            mx = (a & fmt.man_mask) | (1 << mw)
            my = (b & fmt.man_mask) | (1 << mw)
            if mx < my:
                mx *= 2                                   # Q in [1, 2): double the dividend significand (my unchanged)
            nn = abs(N_mid(p, mx, my) if mx < (1 << (p + 1)) else 0)
            rho = nn / my
            used += 1
            if rho < least:
                least = rho
        my_typ = 1.5 * (1 << (p - 1))
        exp_hits = CAMPAIGN_DRAWS * 2 / my_typ
        print("   %-6s %12d %16.3e %20.3e %20.3g %22s" % (fmt.name, used, least, 1.0 / my_typ, exp_hits,
                                                      "reached" if exp_hits > 1 else "NOT reached (expected %.1e)" % exp_hits))
        # the least rho of `used` independent uniform draws on [0, 1] is about 1 / used: a guard on this computation
        check("%s: the least rho over %d draws is within a factor 10 of 1 / draws, as uniform draws predict" % (fmt.name, used),
              0.1 / used < least < 10.0 / used, "(%.2e against %.2e)" % (least, 1.0 / used))
    f32_hits = CAMPAIGN_DRAWS * 2 / (1.5 * (1 << 23))
    f64_hits = CAMPAIGN_DRAWS * 2 / (1.5 * (1 << 52))
    check("fp32: the stress run's draws (1.45e10 a division item) expect over 1,000 closest-approach (|N| = 1) hits", f32_hits > 1000, "(%.0f)" % f32_hits)
    check("fp64: the same draws expect fewer than 10^-5 closest-approach hits (the class is invisible to sampling)", f64_hits < 1e-5, "(%.2e)" % f64_hits)
    print()

    # ---- H4 -------------------------------------------------------------------
    print("== H4. the repository's own failure family: a = 1, b = 1 - ulp (python/tests/test_sequences.py)")
    for fmt in (FP32, FP64):
        p = fmt.prec
        mx, my = 1 << p, (1 << p) - 1                     # a = 1 (as 2 * 2^(p-1)), b = 1 - 2^-p, Q in [1, 2): mx doubled
        n = N_mid(p, mx, my)
        print("   %-6s |N| = %d, rho = |N| / my = %.3e = 1 / my: a closest-approach case (the quotient is 1/(my 2^p), about 2^-%d, from a midpoint: 2^-%d of an ulp)" % (
            fmt.name, abs(n), abs(n) / my, 2 * p, p + 1))
        check("%s: (1, 1 - ulp) has |N| <= 2, i.e. is within a factor 2 of the closest possible approach to a midpoint" % fmt.name, abs(n) <= 2, "(|N| = %d)" % abs(n))
    print()

    # ---- H5 -------------------------------------------------------------------
    print("== H5. a PLANTED defect only the constructed set finds: the quotient computed to g extra bits, rounded ties-to-even on those bits alone")

    def flawed_rne(p, mx, my, g):
        S = (mx << (p - 1 + g)) // my                     # the quotient truncated to g extra bits
        kept, low = S >> g, S & ((1 << g) - 1)
        half = 1 << (g - 1)
        up = 1 if (low > half or (low == half and (kept & 1))) else 0
        return kept + up

    def flaw_fails(p, mx, my, g):
        J, _ = exact_round(p, mx, my, sf.RND_RNE)
        return flawed_rne(p, mx, my, g) != J

    g = 40
    fmt = FP64
    p = fmt.prec
    # random sampler draws
    r = sa.Rng(0x50AC0003)
    nrand = fail_rand = 0
    for _ in range(300000):
        a, b = sa.banded64(r), sa.banded64(r)
        ea, eb = (a >> 52) & 2047, (b >> 52) & 2047
        if ea in (0, 2047) or eb in (0, 2047):
            continue
        mx, my = (a & fmt.man_mask) | (1 << 52), (b & fmt.man_mask) | (1 << 52)
        if mx < my:
            mx *= 2
        nrand += 1
        fail_rand += flaw_fails(p, mx, my, g)
    cons = [(mx, my) for mx, my, t, nn in built["fp64"] if t == "mid"]
    fail_cons = sum(flaw_fails(p, mx, my, g) for mx, my in cons)
    exp_week = CAMPAIGN_DRAWS * 2.0 ** -(g + 1)
    print("   the flawed division (g = %d extra bits) at fp64: %d failures in %d sampler draws; %d failures in %d constructed closest-approach pairs" % (
        g, fail_rand, nrand, fail_cons, len(cons)))
    print("   expected failures in a stress-run-sized item (1.45e10 draws): about %.2e" % exp_week)
    check("the sampler finds NO failure of the flawed division in 300,000 draws", fail_rand == 0, "(%d)" % fail_rand)
    check("the constructed closest-approach set finds the flawed division FAILING on about a quarter of its midpoint pairs at least",
          fail_cons >= 0.2 * len(cons), "(%d of %d)" % (fail_cons, len(cons)))
    check("a stress-run-sized item would expect under 0.01 failures: the defect would pass the weekend", exp_week < 0.01, "(%.2e)" % exp_week)
    # a control: with a generous margin (g = 80) the flawed algorithm is correct on every constructed pair
    fail80 = sum(flaw_fails(p, mx, my, 80) for mx, my in cons)
    check("CONTROL: with g = 80 extra bits the same method is correct on every constructed pair (the set does not just fail everything)",
          fail80 == 0, "(%d failures)" % fail80)
    print()

    # ---- H6 -------------------------------------------------------------------
    print("== H6. square root: where is the closest approach to a midpoint? (fp32, every midpoint of the binade pair [1, 4))")
    # For a result in [1, 2) with grid 2^(1-p), the midpoints are M = (2j + 1) 2^-p. The inputs are x = k 2^(1-p)
    # (k in [2^(p-1), 2^p), exponent even) or x = k 2^(2-p) (exponent odd, x in [2, 4)). M^2 = (2j+1)^2 2^(-2p).
    # The input nearest M^2 is at distance d 2^(-2p) with d an integer, d = min(r, 2^(s) - r) where r = (2j+1)^2 mod 2^s,
    # s = p + 1 for x in [1, 2) and s = p + 2 for x in [2, 4). An odd square is 1 mod 8, so d >= 1.
    p = 24
    best = {}
    counts = {}
    for j in range(1 << (p - 1), 1 << p):
        T = (2 * j + 1) ** 2
        s = p + 1 if T < (1 << (2 * p + 1)) else p + 2    # x = T 2^(-2p) in [1, 2) or [2, 4)
        r = T % (1 << s)
        d = min(r, (1 << s) - r)
        counts[d] = counts.get(d, 0) + 1
        if d not in best:
            best[d] = j
    dmin = min(counts)
    jmins = sorted(j for j in range(1 << (p - 1), 1 << p) if False)  # filled below
    print("   least d over the %d midpoints: %d, reached by %d midpoint(s); the next values of d: %s" % (
        1 << (p - 1), dmin, counts[dmin], sorted(counts)[:6]))
    # which inputs are they? j = 2^(p-1) gives M = 1 + 2^-p and the input x = 1 + ulp, the repository's family
    j0 = 1 << (p - 1)
    x_bits = (FP32.bias << FP32.man_w) | 1                  # 1 + ulp
    T0 = (2 * j0 + 1) ** 2
    d0 = min(T0 % (1 << (p + 1)), (1 << (p + 1)) - T0 % (1 << (p + 1)))
    check("fp32: the least d is 1 (a closest approach of 2^-%d to the midpoint M^2: the minimum an odd square allows)" % (2 * p), dmin == 1, "(d = %d)" % dmin)
    check("fp32: sqrt(1 + ulp), the repository's failure family under RMM (python/tests/test_sequences.py), has d = 1", d0 == 1, "(d = %d)" % d0)
    nd1 = counts[1]
    print("   the %d midpoint(s) with d = 1 of the %d; sampling reaches such an input with probability about %d / 2^%d a draw" % (nd1, 1 << (p - 1), nd1, p))
    # the golden model's sqrt against an exact integer arbiter on every d <= 2 input
    def exact_sqrt_round(fmt, k, odd_exp, mode):
        """sqrt of x = k 2^(1-p) (even exponent) or k 2^(2-p) (odd) by exact integers; returns (J, inexact)
        with the root in [1, 2) in units of 2^(1-p)."""
        pp = fmt.prec
        # x = k 2^(e); root = sqrt(k 2^e); in units of 2^(1-pp): J_exact = sqrt(k 2^e) 2^(pp-1)
        e = (1 - pp) if not odd_exp else (2 - pp)
        # J^2 <= k 2^e 2^(2pp-2) < (J+1)^2 : integer arithmetic
        num = k << (e + 2 * pp - 2) if e + 2 * pp - 2 >= 0 else None
        from math import isqrt
        J = isqrt(num)
        rem = num - J * J
        if rem == 0:
            return J, False
        # compare the root with J + 1/2: (2J + 1)^2 / 4 against num  ->  (2J+1)^2 vs 4 num
        c = (2 * J + 1) ** 2
        cls = 1 if c > 4 * num else (2 if c == 4 * num else 3)
        lsb = J & 1
        if mode in (sf.RND_RTZ, sf.RND_RDN):
            up = 0
        elif mode == sf.RND_RUP:
            up = 1
        elif mode == sf.RND_RNE:
            up = 1 if (cls == 3 or (cls == 2 and lsb)) else 0
        else:
            up = 1 if cls >= 2 else 0
        return J + up, True
    bad = n = 0
    picked = [jj for jj in range(1 << (p - 1), 1 << p) if False]
    for j in range(1 << (p - 1), 1 << p):
        T = (2 * j + 1) ** 2
        s = p + 1 if T < (1 << (2 * p + 1)) else p + 2
        r = T % (1 << s)
        d = min(r, (1 << s) - r)
        if d > 1:
            continue
        # the nearest input: k = round(T / 2^s)
        k = (T + (1 << (s - 1))) >> s
        odd_exp = s == p + 2
        if not ((1 << (p - 1)) <= k < (1 << p)):
            continue
        bits = (FP32.bias + (1 if odd_exp else 0)) << FP32.man_w | (k - (1 << (p - 1)))
        for m in RND:
            got = sf.sqrt(FP32, bits, m)
            J, inexact = exact_sqrt_round(FP32, k, odd_exp, m)
            want = (((FP32.bias << FP32.man_w) | (J - (1 << (p - 1)))) if J < (1 << p) else ((FP32.bias + 1) << FP32.man_w),
                    sf.FLAG_INEXACT if inexact else 0)
            n += 1
            bad += got != want
    check("fp32: golden sqrt = an exact integer arbiter on every closest-approach input (d = 1), all 5 attributes", bad == 0 and n > 0,
          "(%d cases, %d differ)" % (n, bad))
    print()
    print("hardcase_div: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
