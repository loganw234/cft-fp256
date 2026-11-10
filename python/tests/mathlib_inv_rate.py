# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The mark-rate law of atan, asin, acos and atan2 (parcel M4G4): the study's
3.4 (docs/studies/M4-invtrig.md), the model's rate.py (docs/studies/m4/,
which nothing in the tree imports) in the form of mathlib_trig_harness's
TrigRateSample and check_rate, with the CROWDING SPLIT.

The law (the six's, mathlib_harness's comment above RATE_ALPHA; M1's 3.4):
with the bound inflated to 2^-(p + G') |V_h| (G' = 6, bound_shift = G - G'),
a lane is marked when its true value lies within the bound of a boundary of
the attribute, which with its place in the rounding cell uniform has
probability 2 Bv / ulp = 2^-G' m, m in [1, 2) the significand of the true
value. The count of marks is a sum of independent Bernoulli(2^-G' m_i) lanes:
the SAMPLE'S OWN mean and variance, the cell judged by the exact two-sided
tail of that count (RateSample.pmf and p_value), a run of cells as the
independent statistics it holds (rtz, rdn and rup mark the same lanes, rne and
rmm the same). The model's rate.py takes m from V_h; this takes it from the
true value (they differ only where V and f straddle a power of two).

THE CROWDING SPLIT (send-back 1 of the study's 3.4). The law assumes the true
value spread over its rounding cell. Where lanes crowd beside pi/4, pi/2,
3pi/4 or pi (atan of a huge argument, acos of a tiny one, atan2 with one
operand dominant: their true value is within an ulp of the constant) it does
not: such a lane marks only if the constant lies within the inflated bound of
a boundary, and the constants lie 4.0 to 37 inflated bounds from the nearest boundary
(CROWD_DISTANCES, exact rationals, below). So the lanes whose true value is
within an ulp of one of the four are JUDGED APART:

  the rest   follow the law: the exact two-sided tail of their count, with
             their own mean and variance (the study's 11 of 12 cells)
  crowded    may mark FEWER than the law says, never judged from below; a
             crowded cell that marks more than the law's upper tail allows
             is a finding. The law is conservative there (the study: 0 to 57
             marks against 40 to 1,137)

The edge region repeats its arguments (26,900 distinct of 50,000 at fp64):
the cell is judged on the DISTINCT arguments, each once (independent
Bernoulli lanes), and the all-lanes count and sigma are stated beside, with
the multiplicity's inflation sqrt(sum k^2 / n) (the study's 1.55 at fp64).

THE OPEN CELLS (3.4): fp256 acos under rne, whose rest is -2.9 sigma at the
box's 20,000 (389 marks against 450.7) while its crowded lanes obey the law,
and fp64 atan under rtz on the edge region (+4.6 sigma, +3.0 with repeats
counted). This tool measures them (`inv-rate`); they are open until the
record says what it measured.
"""

import functools
import math
import sys
from fractions import Fraction
from pathlib import Path

import mpmath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_inv_family as F  # noqa: E402
import mathlib_inv_harness as I  # noqa: E402

RATE_G = 6                              # G', the inflated bound's guard
REGIONS = ("random", "edge")
CROWD_NAMES = ("pi/4", "pi/2", "3pi/4", "pi")


# ---- the constants' distances from the boundaries (the study's 1.4) -------------

def crowd_constants():
    """pi/4, pi/2, 3pi/4 and pi, exact rationals (pi to 2400 bits)."""
    pi = F.pi_frac()
    return [pi * k / 4 for k in (1, 2, 3, 4)]


def crowd_ulp(fmt, c):
    """The ulp of the format at the constant, an exact rational."""
    return F._ulp(fmt, ml._enc(fmt, c, sf.RND_RTZ))


def crowd_distance(fmt, c):
    """(grid, midpoint): the distance from the constant to the nearest float
    and to the nearest midpoint of two, relative to the constant, in units of
    the nominal bound 2^-(p+G) (exact rationals, then rounded to a float)."""
    p, G = fmt.prec, ml.GUARD[fmt.name]
    lo = ml._dec(fmt, ml._enc(fmt, c, sf.RND_RTZ))
    u = crowd_ulp(fmt, c)
    grid = min(c - lo, lo + u - c)
    mid = abs(c - (lo + u / 2))
    unit = c / 2 ** (p + G)
    return float(grid / unit), float(mid / unit)


def crowd_distances():
    """{format: {constant name: (grid, mid)}}, every figure in units of
    2^-(p+G), COMPUTED in exact rationals. Divided by 2^(G - G') it is the
    distance in inflated bounds, which is what the crowded lanes need to
    mark."""
    cs = crowd_constants()
    return {fmt.name: {n: crowd_distance(fmt, c)
                       for n, c in zip(CROWD_NAMES, cs)}
            for fmt in I.FORMATS}


def inflated_bounds(fmt, dist, g_inflated=RATE_G):
    """A distance in units of 2^-(p+G) as inflated bounds 2^-(p+G')."""
    return dist / 2.0 ** (ml.GUARD[fmt.name] - g_inflated)


# The study's table (1.4, COMPUTED there by consts.py, to two figures), for
# comparison: {format: {constant: (grid, mid)}} in units of 2^-(p+G).
STUDY_DISTANCES = {
    "fp64": {"pi/4": (6.2e12, 5.0e12), "pi/2": (6.2e12, 5.0e12),
             "3pi/4": (6.2e12, 8.8e12), "pi": (6.2e12, 5.0e12)},
    "fp128": {"pi/4": (2.0e13, 2.5e13), "pi/2": (2.0e13, 2.5e13),
              "3pi/4": (2.0e13, 4.0e13), "pi": (2.0e13, 2.5e13)},
    "fp256": {"pi/4": (4.0e13, 4.4e12), "pi/2": (4.0e13, 4.4e12),
              "3pi/4": (1.9e13, 4.0e13), "pi": (4.0e13, 4.4e12)},
}


# crowd_distances(), COMPUTED in exact rationals (pi to 2400 bits) and written
# here to four figures: {format: {constant: (to a grid point, to a midpoint)}}
# in units of 2^-(p+G), which divided by 2^(G - G') = 2^38, 2^40, 2^40 are the
# distances in inflated bounds: 4.01 at the least (fp256, a midpoint beside pi/4,
# pi/2 and pi: the open cell's constants), 17.6 to 37 for the others. A
# crowded lane marks only where its true value is within the inflated bound of
# a boundary, which for the lanes beside a constant is where the lane's own
# offset from the constant matches one of these. test_mathlib_inv_family.py
# holds this to a fresh computation and to the study's table to two figures.
CROWD_DISTANCES = {
    "fp64": {"pi/4": (6.177e+12, 5.023e+12), "pi/2": (6.177e+12, 5.023e+12),
             "3pi/4": (6.177e+12, 8.756e+12), "pi": (6.177e+12, 5.023e+12)},
    "fp128": {"pi/4": (2.017e+13, 2.463e+13), "pi/2": (2.017e+13, 2.463e+13),
              "3pi/4": (2.017e+13, 3.956e+13), "pi": (2.017e+13, 2.463e+13)},
    "fp256": {"pi/4": (4.039e+13, 4.413e+12), "pi/2": (4.039e+13, 4.413e+12),
              "3pi/4": (1.935e+13, 4.039e+13), "pi": (4.039e+13, 4.413e+12)},
}


# ---- the sample ------------------------------------------------------------------------

def rate_arguments(fmt, fn, region, n, seed):
    """rate.py's sample: `n` arguments of the region of sample() for `seed`,
    those the main path answers for fn."""
    return [x for x in I.sample(fn, fmt, region, n, seed)
            if I.in_main(fn, fmt, x)]


def lane_cell(fmt, fn, x):
    """(E, m) of the true value |f| = m 2^E, m in [1, 2): mpmath at p + 96
    bits (the lane exact), read from the `_mpf_` tuple."""
    p = fmt.prec
    with mpmath.workprec(p + 96):
        _s, man, ex, bc = I.true_value(fn, fmt, x)._mpf_
    if not man:
        raise ValueError(f"{fn}({x!r}) is zero: not a main-path lane")
    man = int(man)
    return ex + bc - 1, man / (1 << (bc - 1))


@functools.lru_cache(maxsize=None)
def _crowd_mp(fmt_name):
    """[(constant, ulp)] as mpf at 4p + 200 bits."""
    fmt = I.BY_NAME[fmt_name]
    with mpmath.workprec(4 * fmt.prec + 200):
        return [(F._mp(c), F._mp(crowd_ulp(fmt, c))) for c in crowd_constants()]


def crowded(fmt, fn, x):
    """Whether |f(x)| lies within an ulp of pi/4, pi/2, 3pi/4 or pi (the
    ulp of the constant's binade, as rate.py)."""
    with mpmath.workprec(4 * fmt.prec + 200):
        T = abs(I.true_value(fn, fmt, x))
        return any(abs(T - c) < u for c, u in _crowd_mp(fmt.name))


class Law(H.RateSample):
    """H.RateSample's law (mean, sigma, pmf, tails, p_value) for lanes given
    by their probabilities."""

    def __init__(self, ps):
        self.p = list(ps)
        self.n = len(self.p)
        self.mean = math.fsum(self.p)
        self.var = math.fsum(q * (1.0 - q) for q in self.p)
        self.sigma = math.sqrt(self.var)
        self._pmf = None


class InvRateSample:
    """The lanes of rate_arguments() with the law of the count of marks under
    the bound inflated to G': lane i is marked with probability p_i = 2^-G'
    m_i. `xs` all lanes (with repeats), `distinct` each argument once, `rest`
    and `crowd` the distinct lanes split by crowded(), each with its Law."""

    def __init__(self, fmt, fn, region, n, seed, g_inflated=RATE_G):
        self.fmt, self.fn, self.region = fmt, fn, region
        self.seed, self.g = seed, g_inflated
        self.xs = rate_arguments(fmt, fn, region, n, seed)
        self.n = len(self.xs)
        self.mult = {}
        for x in self.xs:
            self.mult[x] = self.mult.get(x, 0) + 1
        self.distinct = list(self.mult)
        self.p = {x: min(1.0, lane_cell(fmt, fn, x)[1] * 2.0 ** -g_inflated)
                  for x in self.distinct}
        self.is_crowded = {x: crowded(fmt, fn, x) for x in self.distinct}
        self.rest = [x for x in self.distinct if not self.is_crowded[x]]
        self.crowd = [x for x in self.distinct if self.is_crowded[x]]
        self.law_all = Law([self.p[x] for x in self.distinct])
        self.law_rest = Law([self.p[x] for x in self.rest])
        self.law_crowd = Law([self.p[x] for x in self.crowd])
        # the multiplicity's inflation, the study's: repeats mark alike
        self.inflation = math.sqrt(sum(k * k for k in self.mult.values())
                                   / self.n) if self.n else 1.0


@functools.lru_cache(maxsize=None)
def rate_sample(fmt, fn, region, n, seed, g_inflated=RATE_G):
    """The InvRateSample of these arguments, cached: it holds the clean
    sample, which a planted fault does not touch, and the attributes of a
    cell share it."""
    return InvRateSample(fmt, fn, region, n, seed, g_inflated)


# Faults of the TOOL, for the tests: check_rate(tool_plant=...).
RATE_TOOL_PLANTS = {
    "expectation_follows_build": "the law's expectation computed from the "
                                 "build under test (its own bound word), so "
                                 "that a faulted bound moves the centre with "
                                 "the count and the check cannot see it",
}


def check_rate(fmt, rnd, fn, region="random", n=2000, seed=3,
               g_inflated=RATE_G, plant=None, statistics=1,
               alpha=H.RATE_ALPHA, sigmas=None, tool_plant=None,
               evaluator=None):
    """[finding], stats: rate. The mark-rate law (the study's 3.4) held to
    the sample's own count on the lanes that are not crowded: the build of fn
    at fmt under rnd with the bound inflated to 2^-(p + G') (bound_shift = G -
    G'), `plant` a fault of the builder (INV_PLANTS), n arguments of the
    region (rate_arguments), each lane's probability 2^-G' m with m the
    significand of its true value, the rest of the distinct arguments flagged
    when the exact two-sided tail of its count under that law is under alpha /
    statistics (a run of cells judged together), or with `sigmas` beyond that
    many sigma; the crowded lanes judged apart (the module docstring: a
    finding only for more marks than the law's upper tail allows); and every
    unmarked lane right (a marked guess is counted, not judged).

    The expectation is of the UNPLANTED bound: a planted bound or a silenced
    mark changes the count and not the centre. `tool_plant` is a fault of
    this tool (RATE_TOOL_PLANTS): the expectation taken from the build under
    test; `evaluator` stands for ml.evaluate, for the test that doctors a
    lane."""
    if tool_plant is not None and tool_plant not in RATE_TOOL_PLANTS:
        raise ValueError(f"unknown tool plant {tool_plant!r}: "
                         f"{', '.join(RATE_TOOL_PLANTS)}")
    G = ml.GUARD[fmt.name]
    b = ml.build(fn, fmt, rnd, bound_shift=G - g_inflated, plant=plant)
    f = b.fragment()
    smp = rate_sample(fmt, fn, region, n, seed, g_inflated)
    if tool_plant == "expectation_follows_build":
        # the build's own bound word, 2^-(p + G'') with G'' = G' (clean) or
        # 40 more (bound_loose): the law of what the build is, not of what
        # it was meant to be
        brel = ml._dec(fmt, b.words[b.roles["BREL"][1]])
        g_built = round(-math.log2(brel)) - fmt.prec
        smp = rate_sample(fmt, fn, region, n, seed, g_built)
    ev = evaluator or ml.evaluate
    res = {x: ev(f, x) for x in smp.distinct}
    mk = {x: bool(res[x][1] & ml.MARK) for x in smp.distinct}
    wrong = [x for x in smp.distinct if not mk[x]
             and res[x] != I.golden(fmt, rnd, x, fn)]
    gwrong = [x for x in smp.distinct if mk[x]
              and (res[x][0], res[x][1] & 0x1F) != I.golden(fmt, rnd, x, fn)]
    c_rest = sum(mk[x] for x in smp.rest)
    c_crowd = sum(mk[x] for x in smp.crowd)
    c_all = sum(mk[x] for x in smp.distinct)
    c_lanes = sum(smp.mult[x] for x in smp.distinct if mk[x])

    def z(c, law):
        return (c - law.mean) / law.sigma if law.sigma > 0 else 0.0
    law = smp.law_rest
    lo, hi = law.tails(c_rest) if law.n else (1.0, 1.0)
    pval = min(1.0, 2.0 * min(lo, hi))
    level = H.rate_level(statistics, alpha)
    clo, chi = smp.law_crowd.tails(c_crowd) if smp.law_crowd.n else (1.0, 1.0)
    st = {"n": smp.n, "distinct": len(smp.distinct), "lanes_marked": c_lanes,
          "marked": c_all, "rest_n": len(smp.rest), "rest_marked": c_rest,
          "rest_expected": law.mean, "rest_sigma": law.sigma,
          "rest_z": z(c_rest, law), "p": pval, "level": level,
          "crowd_n": len(smp.crowd), "crowd_marked": c_crowd,
          "crowd_expected": smp.law_crowd.mean,
          "crowd_z": z(c_crowd, smp.law_crowd), "crowd_upper_tail": chi,
          "all_expected": smp.law_all.mean, "all_z": z(c_all, smp.law_all),
          "inflation": smp.inflation, "statistics": statistics,
          "class": H.rate_class(rnd), "wrong": len(wrong),
          "guess_wrong": len(gwrong)}
    where = (f"rate: {fn} {fmt.name} {sf.RND_NAMES[rnd]} {region} "
             f"(G' = {g_inflated})")
    out = []
    if sigmas is not None:
        if abs(st["rest_z"]) > sigmas:
            out.append(f"{where}: {c_rest} of {len(smp.rest)} uncrowded "
                       f"distinct lanes marked, {law.mean:.1f} expected "
                       f"(sigma {law.sigma:.1f}): {st['rest_z']:+.1f} sigma")
    elif law.n and pval < level:
        out.append(f"{where}: {c_rest} of {len(smp.rest)} uncrowded distinct "
                   f"lanes marked, {law.mean:.1f} expected (sigma "
                   f"{law.sigma:.1f}): {st['rest_z']:+.1f} sigma, an exact "
                   f"two-sided tail of {pval:.2g}, under the {level:.2g} of "
                   f"this run (alpha {alpha:g} over {statistics} statistics)")
    if smp.law_crowd.n and chi < level:
        out.append(f"{where}: the {len(smp.crowd)} crowded lanes mark "
                   f"{c_crowd}, more than the law's {smp.law_crowd.mean:.1f} "
                   f"allows (upper tail {chi:.2g}, under {level:.2g}): the "
                   f"constants lie too close to a boundary")
    if wrong:
        out.append(f"{where}: {len(wrong)} unmarked lanes are wrong, first "
                   f"{I._hexes([wrong[0]])}")
    return out, st
