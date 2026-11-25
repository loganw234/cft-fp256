# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The lanes, the measurements and the checks parcel M3G1 holds pow and powr
to (cft_golden/mathlib.py, the section "pow and powr"; docs/studies/M3-pow.md,
sections 3, 4 and 8), gathered in one place so that python/tests/
test_mathlib_pow.py (quick, for the golden stage) and python/tests/
mathlib_runs.py (the larger runs, for the lead's box: pow-pools and pow-bound)
run the same lanes and the same checks. Parcels M3G2 (pown, rootn, compound)
and M3F1 (fp32) add their functions at the anchors at the end: every table here
is a dict BY FUNCTION that they assign into, and every check takes the table it
reads as an argument.

A CHECK takes a fragment or its instrumented build and returns FINDINGS: a list
of strings, each beginning with the check's name and a colon, empty when it
holds (mathlib_harness's convention); one that measures also returns what it
measured. A planted fault is "caught by name" when the check it is meant for
returns a finding that begins with that name. mathlib_harness.py,
mathlib_inv_harness.py and the others are imported, never edited. A lane is a
tuple (x, y) of encodings, in the build's inputs' order.

  pools        the vector sets' and the stage's pools (the study's 1.3 and 3.3)
               through one fragment: every unmarked lane equal to transcend.py in
               bits AND flag word; the lanes marked COUNTED and pinned to the
               model's (POOL_MARKS: a count that differs is a finding, since the
               port is the model; a marked lane's guess is counted, not a
               failure; the rule "a mark off a list fails" is parcel M3G3's,
               from the study's 3.5: mathlib_pow_family.py's committed list)
  regions      the study's placed regions (3.3) as committed sets, every lane
               against transcend.py, 0 wrong unmarked; and the first design's
               lanes by name (the study's 3.6, items 1, 2 and 7)
  specials     the study's section 4 rows, both signs of every zero and infinity
               where the row has them, 0 wrong unmarked, the marks counted
               against the model's (SPECIAL_MARKS)
  structured   the committed lanes: the exact powers of two that must NOT mark,
               y = 1, the lanes beside 1 on both sides of the gate, the tie at
               half the least subnormal, a few exact cases that must mark by
               family with their neighbours that must not, and the plants'
               named lanes
  seq          the fragment as a stand-alone program on seq.py (routines.program
               and routines.run, x in r0 and y in r1) equal to evaluate() lane by
               lane and to transcend.py where unmarked; the compiled shape
               (mathlib_harness.r24_program): each lane's byte, FLAGS and
               STATUS[6]
  bound        |V - f| / Bv under 1, mpmath at 4p + 200 bits, over the regions'
               lanes (48 points a region), each lane also against transcend.py.
               The largest is a sampled lower bound; the study's budget is
               parcel M3G3's (mathlib_pow_budget.py), this is the direct error
  shape        instructions, words and live pinned per fragment; instructions by
               phase and the Fast2Sum and TwoSum counts the model's; the flag
               word's values; the scheduled fragment the design's reordered;
               POW_LIVE_CAP the measured maximum, a cap one under failing by name
  core         build_pow_core(double=True) against mpmath on placed (x, y_h,
               y_l), the low word of both signs; the plain build's V_h + V_l
               against |x|^y within Bv; a Fraction's ybound
  constants    mathlib.check_pow_constants() in process, and as
               `python -m cft_golden.mathlib --check --only pow`
"""

import collections
import functools
import hashlib
import importlib.util
import math
import random
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import mpmath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import FP64, FP128, FP256, routines, seq  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import transcend, vectors  # noqa: E402

import mathlib_harness as H  # noqa: E402

FORMATS = (FP64, FP128, FP256)           # POW_FORMATS: fp32 is parcel M3F1's
BY_NAME = {f.name: f for f in FORMATS}
FUNCS = tuple(ml._POW_BUILDERS)          # pow, powr, and what M3G2 builds
RND_MODES = sf.RND_MODES                 # rne, rtz, rdn, rup, rmm
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
MARK = ml.MARK
CHECKS = ("pools", "regions", "specials", "structured", "seq", "bound",
          "shape", "core", "constants")


# ---- the definition, memoised -----------------------------------------------

@functools.lru_cache(maxsize=None)
def golden(fmt, rnd, lane, fn):
    """transcend.py's function: the definition, (bits, flag word), for the lane
    (x, y). Cached, since a plant re-runs the lanes of the clean fragment.
    For pown, rootn and compound (parcel M3G2) the lane is (x, n) with n the
    integer operand, which transcend.compute takes by keyword."""
    if fn in ml.POW_INT_NAMES:
        return transcend.compute(fmt, fn, lane[0], 0, rnd, n=lane[1])
    return transcend.compute(fmt, fn, lane[0], lane[1], rnd)


def lane_args(fn, lane):
    """The argument of a fragment's or build's evaluate() and run() for a lane:
    the lane itself for pow and powr, whose two operands are inputs, and (x,)
    for pown, rootn and compound (parcel M3G2), whose n is a constant of the
    fragment and whose one input is x."""
    return (lane[0],) if fn in ml.POW_INT_NAMES else lane


def value(fmt, bits):
    return ml._dec(fmt, bits)


def _mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


def _V(fmt, s, m, e):
    """(-1)^s m 2^e as an encoding, exactly (an assertion where it is not)."""
    b, fl = sf.round_pack(fmt, s, m, e, RNE)
    assert fl == 0, (m, e)
    return b


def _enc(fmt, q):
    return ml._enc(fmt, Fraction(q))


def _hexes(lanes, k=3):
    return ", ".join("(" + ", ".join(hex(v) for v in x) + ")"
                     for x in list(lanes)[:k])


def true_value(fn, fmt, lane):
    """The function's value on a main-path lane as an mpf at the working
    precision of the caller: |x|^y, negative where x < 0 and y is an odd
    integer (pow; powr's x is positive). Parcel M3G2 assigns TRUE_FNS' other
    keys."""
    return TRUE_FNS[fn](fmt, lane)


def _true_pow(fmt, lane):
    X, Y = value(fmt, lane[0]), value(fmt, lane[1])
    mag = mpmath.power(abs(_mp(X)), _mp(Y))
    odd = Y.denominator == 1 and Y.numerator % 2 != 0
    return -mag if (X < 0 and odd) else +mag


TRUE_FNS = {"pow": _true_pow, "powr": _true_pow}


# ---- the pools --------------------------------------------------------------

def _dedup(seq_):
    seen, out = set(), []
    for v in seq_:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return tuple(out)


def _trials(fmt):
    return 64 if fmt.width <= 64 else 16


def _pow_pool(fmt):
    """The vector sets' pairs (vectors.transcend_pow_pairs as transcend_cases
    calls it: 24 extra, seed 10) and the stage's (host/tests/transcend_check.py's
    pow_pairs at its default trials, 64 at fp64 and 16 above, seed 5),
    deduplicated in order."""
    tc = H._transcend_check()
    return _dedup(list(vectors.transcend_pow_pairs(fmt, 24, 10))
                  + list(tc.pow_pairs(fmt, _trials(fmt), 5)))


def _powr_pool(fmt):
    tc = H._transcend_check()
    return _dedup(list(vectors.transcend_powr_pairs(fmt, 24, 18))
                  + list(tc.powr_pairs(fmt, _trials(fmt), 5)))


# the pool of each function, by function (M3G2 assigns its own)
POOL_FNS = {"pow": _pow_pool, "powr": _powr_pool}


@functools.lru_cache(maxsize=None)
def pool(fn, fmt):
    return POOL_FNS[fn](fmt)


# The lanes of the pools and the lanes of them that are marked, by function and
# format: the study's 3.3 (docs/studies/M3-pow.md, "The pools against
# transcend.py", MEASURED by the model; this parcel's port gives the same
# numbers, which the test pins). Marks are in RND_MODES' order: rne, rtz, rdn,
# rup, rmm. M3G2 assigns its rows at its anchor.
POOL_SIZES = {("pow", "fp64"): 794, ("pow", "fp128"): 746,
              ("pow", "fp256"): 746, ("powr", "fp64"): 823,
              ("powr", "fp128"): 775, ("powr", "fp256"): 775}
POOL_MARKS = {("pow", "fp64"): (129, 108, 108, 108, 129),
              ("pow", "fp128"): (146, 125, 125, 125, 146),
              ("pow", "fp256"): (152, 131, 131, 131, 152),
              ("powr", "fp64"): (100, 79, 79, 79, 100),
              ("powr", "fp128"): (115, 94, 94, 94, 115),
              ("powr", "fp256"): (120, 99, 99, 99, 120)}


class Tally:
    """The lanes of one run: n; the marked lanes and how many guesses were
    wrong; the unmarked lanes that were wrong; and the flag words with stray
    bits."""

    def __init__(self):
        self.n = 0
        self.marked = []
        self.guess_wrong = []
        self.wrong = []
        self.stray = []

    @property
    def marked_right(self):
        return len(self.marked) - len(self.guess_wrong)


def check_pools(f, xs=None, results=None, marks=None, size=None):
    """[finding], Tally: pools. `xs` the lanes (the pool of the function by
    default), `results` their (bits, flag word) if the caller has them; `marks`
    the pinned count of marked lanes and `size` the pinned count of lanes (the
    function's POOL_MARKS and POOL_SIZES entries by default, when the whole pool
    is run; None where `xs` is a part of it). The rule "a mark off a list
    fails" is parcel M3G3's (mathlib_pow_family.py): the count here is the
    model's, not a list."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    whole = xs is None
    xs = pool(fn, fmt) if whole else xs
    if whole:
        if marks is None:
            marks = POOL_MARKS[(fn, fmt.name)][RND_MODES.index(rnd)]
        if size is None:
            size = POOL_SIZES[(fn, fmt.name)]
    if results is None:
        results = [ml.evaluate(f, lane_args(fn, x)) for x in xs]
    t = Tally()
    for x, (bits, fw) in zip(xs, results):
        gb, gf = golden(fmt, rnd, x, fn)
        t.n += 1
        if fw & ~(MARK | 0x1F):
            t.stray.append((x, fw))
        if fw & MARK:
            t.marked.append(x)
            if (bits, fw & 0x1F) != (gb, gf):
                t.guess_wrong.append((x, bits, gb))
        elif (bits, fw) != (gb, gf):
            t.wrong.append((x, (bits, fw), (gb, gf)))
    where = f"pools: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if t.wrong:
        x, got, want = t.wrong[0]
        out.append(f"{where}: {len(t.wrong)} unmarked lanes differ from "
                   f"transcend.{fn}, first {_hexes([x])}: got ({got[0]:#x}, "
                   f"{got[1]:#x}), want ({want[0]:#x}, {want[1]:#x})")
    if t.stray:
        out.append(f"{where}: {len(t.stray)} flag words carry bits other "
                   f"than [4:0] and the mark, first {_hexes([t.stray[0][0]])}")
    if size is not None and t.n != size:
        out.append(f"{where}: {t.n} lanes, the model's pool has {size}")
    if marks is not None and len(t.marked) != marks:
        out.append(f"{where}: {len(t.marked)} lanes marked, the model's "
                   f"count is {marks}")
    return out, t


# ---- builds, memoised --------------------------------------------------------

@functools.lru_cache(maxsize=None)
def build_of(fn, fmt, rnd, plant=None):
    """ml.build(fn, fmt, rnd, plant=plant), once. A Build is never mutated by a
    check, so the tests share them."""
    return ml.build(fn, fmt, rnd, plant=plant)


@functools.lru_cache(maxsize=None)
def fragment_of(fn, fmt, rnd, plant=None):
    """The build's fragment, scheduled (the library's own for no plant)."""
    return build_of(fn, fmt, rnd, plant).fragment()


@functools.lru_cache(maxsize=None)
def core_of(fmt, rnd=RNE, plant=None, double=False):
    return ml.build_pow_core(fmt, rnd, plant=plant, double=double)


# ---- the placed regions: the study's regions.py, ported -----------------------
#
# Regions of placed arguments that reach every corner of the two operands,
# placed by the quantity the error depends on, t = y log2|x|, and by the
# operands' own ranges (the study's 3.3; M4's study passed its own regions and
# failed its verifier's in a corner none of them reached):
#
#   wide     x log-uniform from the least subnormal to the largest finite, either
#            sign for pow (y then an integer), t uniform on the main path's whole
#            range, y = t / log2|x| rounded: y from about 2^-18 to past 2^p
#   near1    x = 1 +- k ulp (k < 2^8, or 2^(p/2)), y large: t uniform
#   edge     t within 2 of emax + 1 and of emin - p: the overflow and underflow
#            edges, subnormal results among them
#   redb     t within 2^-30 of a sixteenth (the reduction's n/8 boundary)
#   small    |t| log-uniform from 2^-(p+12) to 2^-4: next to 1
#   negint   x < 0 with an integer y, odd and even, |y| up to 2^(p+4) (pow only)
#   sub      x subnormal, t in range
#   tinyy    y log-uniform from the least subnormal to 2^-(p+2), either sign, x
#            over its whole range: t beside 1, t_h underflowing at the bottom
#   hugey    |y| log-uniform from 2^p to the largest finite (every one an even
#            integer), x within 2^-p of 1 and of -1 or anywhere
#   negedge  x < 0 with an odd integer y and t within 2 of the edges: the signed
#            result at the overflow threshold and on the fixed grid (pow only)
#   rhoedge  x in [0.941, 0.965], where M1's reduction takes the cell C = 16 and
#            |r| is next to its rho: the logarithm's polynomial at its weakest
#   zone     |x| in the cancelling zone of M1's reduction, [1/2, 241/256), where
#            k = -1 and log2 m' up to 0.913 make L as small as -0.0871: six tenths
#            uniform in [0.92, 241/256), two tenths over the whole zone, a tenth
#            within 2^-6 of the top, a tenth just above it; y from t uniform in
#            range
REGION_NAMES = {
    "pow": ("wide", "near1", "edge", "redb", "small", "negint", "sub",
            "tinyy", "hugey", "negedge", "rhoedge", "zone"),
    "powr": ("wide", "near1", "edge", "redb", "small", "sub", "tinyy",
             "hugey", "rhoedge", "zone")}
# the study's lanes a region at each format (regions_run.py's N: pow 400 at
# fp64 and 80 at fp128 and fp256; powr half): the box command's size; the test
# takes a tenth. The region's seed is the study's, 1.
REGION_LANES = {("pow", "fp64"): 400, ("pow", "fp128"): 80,
                ("pow", "fp256"): 80, ("powr", "fp64"): 200,
                ("powr", "fp128"): 40, ("powr", "fp256"): 40}
ZONE_TOP = Fraction(241, 256)     # m = 2X = 241/128: the seed's cells 9, 8


def _zone_x(rng, lo=0.5):
    u = rng.random()
    if u < 0.6:
        return Fraction(rng.uniform(max(0.92, lo), float(ZONE_TOP)))
    if u < 0.8:
        return Fraction(rng.uniform(lo, float(ZONE_TOP)))
    if u < 0.9:
        return ZONE_TOP - Fraction(2.0 ** -rng.uniform(6, 50))
    return ZONE_TOP + Fraction(rng.uniform(0, 0.01))


def _log2(fmt, x):
    with mpmath.workprec(fmt.prec + 64):
        q = value(fmt, x)
        return mpmath.log(abs(mpmath.mpf(q.numerator) / q.denominator), 2)


def _rand_mag(fmt, rng, lo_e, hi_e):
    """A random positive finite encoding with exponent in [lo_e, hi_e]."""
    e = rng.randint(lo_e, hi_e)
    m = rng.getrandbits(fmt.prec - 1) | (1 << (fmt.prec - 1))
    b = sf.round_pack(fmt, 0, m, e - fmt.prec + 1, RNE)[0]
    return b


def _y_for(fmt, x, t):
    """y = t / log2|x|, rounded to the format, or None."""
    L = _log2(fmt, x)
    if L == 0:
        return None
    with mpmath.workprec(fmt.prec + 64):
        bits = _enc(fmt, ml._frac(mpmath.mpf(t) / L))
    if (bits & ~fmt.sign_mask) >= sf.inf_bits(fmt) or not \
            (bits & ~fmt.sign_mask):
        return None
    return bits


def in_main(fn, fmt, lane):
    """The lane is one the main path answers: no special row (a NaN, an
    infinity, a zero, x or y = 1, a negative x with a non-integer y, or any
    negative x for powr). The screens may still take it."""
    x, y = lane
    ux, uy = sf.unpack(fmt, x), sf.unpack(fmt, y)
    if ux.kind in (sf.NAN, sf.INF, sf.ZERO) or \
            uy.kind in (sf.NAN, sf.INF, sf.ZERO):
        return False
    qx, qy = value(fmt, x), value(fmt, y)
    if qx == 1 or qy == 1:
        return False
    if qx < 0 and (fn == "powr" or qy.denominator != 1):
        return False
    return True


def region(fmt, fn, name, count, seed=1):
    """`count` lanes of the region `name` for `fn` at `fmt`: the study's
    regions.py, seeded (seed * 1000003 + width). [] for a region the function
    has none of (negint and negedge are pow's)."""
    rng = random.Random(seed * 1000003 + fmt.width)
    p = fmt.prec
    lo_e, hi_e = fmt.emin - p + 1, fmt.emax
    Tf = ml._pow_t_reach(fmt) - 3
    out, tries = [], 0
    while len(out) < count and tries < 50 * count + 100:
        tries += 1
        lane = None
        if name == "zone":
            X = _zone_x(rng)
            x = _enc(fmt, X)
            t = rng.uniform(-Tf, Tf)
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            if fn == "pow" and rng.random() < 0.3:
                # a negative base with an integer y
                yi = round(value(fmt, y))
                if yi in (0, 1, -1):
                    continue
                y = _enc(fmt, yi)
                x |= fmt.sign_mask
            lane = (x, y)
        elif name == "wide":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            y = _y_for(fmt, x, rng.uniform(-Tf, Tf))
            if y is None:
                continue
            lane = (x, y)
        elif name == "near1":
            k = rng.randint(1, 255) if rng.random() < 0.7 else \
                rng.randint(1, 1 << (p // 2))
            one = sf.one_bits(fmt)
            x = one + k if rng.random() < 0.5 else one - k
            y = _y_for(fmt, x, rng.uniform(-Tf, Tf))
            if y is None:
                continue
            lane = (x, y)
        elif name == "edge":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            if rng.random() < 0.5:
                t = fmt.emax + 1 + rng.uniform(-2, 0.99)
            else:
                t = fmt.emin - p + rng.uniform(-1.99, 2)
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "redb":
            x = _rand_mag(fmt, rng, -8, 8)
            k = rng.randint(-16 * 40, 16 * 40)
            t = k / 16 + rng.uniform(-1, 1) * 2.0 ** -30
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "small":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            t = 2.0 ** rng.uniform(-(p + 12), -4) * rng.choice((-1, 1))
            y = _y_for(fmt, x, t)
            if y is None:
                continue
            lane = (x, y)
        elif name == "negint":
            if fn == "powr":
                return []
            m = rng.getrandbits(fmt.prec - 1) | (1 << (fmt.prec - 1))
            ey = rng.randint(0, p + 4)
            yv = m >> max(0, p - 1 - ey) if ey < p else m << (ey - p + 1)
            yv = max(2, yv)
            if rng.random() < 0.5:
                yv = yv | 1 if ey < p else yv
            # x near enough to 1 that t stays in range
            L = rng.uniform(-Tf, Tf) / yv
            with mpmath.workprec(p + 64):
                x = _enc(fmt, ml._frac(mpmath.power(2, mpmath.mpf(L))))
            if x == sf.one_bits(fmt):
                continue
            yb = _enc(fmt, Fraction(yv) * rng.choice((1, -1)))
            lane = (x | fmt.sign_mask, yb)
        elif name == "tinyy":
            x = _rand_mag(fmt, rng, lo_e, hi_e)
            if fn == "pow" and rng.random() < 0.2:
                x |= fmt.sign_mask
                y = None
            else:
                y = _rand_mag(fmt, rng, lo_e, -(p + 2))
                if rng.random() < 0.5:
                    y |= fmt.sign_mask
            if y is None:
                continue
            lane = (x, y)
        elif name == "hugey":
            y = _rand_mag(fmt, rng, p, hi_e)
            if rng.random() < 0.5:
                y |= fmt.sign_mask
            one = sf.one_bits(fmt)
            k = rng.randint(1, 4)
            x = rng.choice((one + k, one - k, _rand_mag(fmt, rng, lo_e, hi_e)))
            if fn == "pow" and rng.random() < 0.5:
                x |= fmt.sign_mask
            lane = (x, y)
        elif name == "rhoedge":
            u = rng.uniform(0.6, 1.0)
            x = _enc(fmt, 1 - Fraction(592, 10000) * Fraction(u))
            y = _y_for(fmt, x, rng.uniform(-Tf, Tf))
            if y is None:
                continue
            lane = (x, y)
        elif name == "negedge":
            if fn != "pow":
                return []
            yv = rng.randrange(3, 2001, 2)
            if rng.random() < 0.5:
                t = fmt.emax + 1 + rng.uniform(-2, 0.99)
            else:
                t = fmt.emin - p + rng.uniform(-1.99, 2)
            if rng.random() < 0.3:
                yv = -yv
            with mpmath.workprec(p + 64):
                x = _enc(fmt, ml._frac(mpmath.power(2, mpmath.mpf(t) / yv)))
            if not (x & ~fmt.sign_mask) or x == sf.one_bits(fmt):
                continue
            lane = (x | fmt.sign_mask, _enc(fmt, Fraction(yv)))
        elif name == "sub":
            x = _rand_mag(fmt, rng, lo_e, fmt.emin - 1)
            y = _y_for(fmt, x, rng.uniform(-Tf, Tf))
            if y is None:
                continue
            lane = (x, y)
        else:
            raise ValueError(name)
        if lane is not None and in_main(fn, fmt, lane):
            out.append(lane)
    return out


@functools.lru_cache(maxsize=None)
def placed_points(fn, fmt, n=48, seed=11):
    """The bound check's lanes: n points of each of the function's regions,
    seed `seed` (the study's regions, a seed of their own)."""
    return {r: tuple(region(fmt, fn, r, n, seed))
            for r in REGION_NAMES[fn] if region(fmt, fn, r, 1, seed)}


def _first_design_lanes(fmt):
    """[(label, fn, lane)]: the lanes the first design got wrong, by name, as
    literal lanes (the study's 3.6): item 1, pow(1.2, minSub) and pow(5/6,
    minSub), both signs of minSub (the attributes are the check's); item 2,
    pow(-(1 + 0x389 ulp), 0x43285fac64090d34) (fp64: the lane is an even y near
    2^51.6, written in fp64's bits); item 7, pow(-67.6, -177)."""
    one = sf.one_bits(fmt)
    ms = sf.min_subnormal_bits(fmt)
    out = []
    for q in (Fraction(6, 5), Fraction(5, 6)):
        for s in (0, 1):
            out.append((f"pow({q}, {'-' if s else ''}minSub)", "pow",
                        (_enc(fmt, q), ms | (fmt.sign_mask if s else 0))))
    if fmt.name == "fp64":
        out.append(("pow(-(1 + 0x389 ulp), 0x43285fac64090d34)", "pow",
                    ((one + 0x389) | fmt.sign_mask, 0x43285fac64090d34)))
    out.append(("pow(-67.6, -177)", "pow",
                (_enc(fmt, Fraction(676, 10)) | fmt.sign_mask,
                 _enc(fmt, -177))))
    return out


# the first design's lanes by function and format (M3G2 assigns theirs)
FIRST_LANES = {"pow": _first_design_lanes}


def first_lanes(fn, fmt):
    return [(lab, lane) for lab, f_, lane in FIRST_LANES[fn](fmt)
            if f_ == fn] if fn in FIRST_LANES else []


def check_regions(f, regions=None, first=None, evaluator=None):
    """[finding], (lanes, marked): regions. Every lane of every region (the
    function's, at a tenth of the study's size by default) and the first
    design's lanes by name, through the fragment: unmarked lanes equal to
    transcend.py in bits and flag word. `regions` {name: lanes} stands for the
    placed ones, `first` [(label, lane)] for the literal ones, `evaluator` for
    ml.evaluate (for the test that plants a fault in it)."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    if regions is None:
        n = REGION_LANES[(fn, fmt.name)] // 10
        regions = {r: region(fmt, fn, r, n, 1) for r in REGION_NAMES[fn]}
    out, n_lanes, marked = [], 0, 0
    where = f"regions: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    for name, lanes in regions.items():
        bad = []
        for lane in lanes:
            bits, fw = (evaluator or ml.evaluate)(f, lane)
            n_lanes += 1
            if fw & MARK:
                marked += 1
            elif (bits, fw) != golden(fmt, rnd, lane, fn):
                bad.append(lane)
        if bad:
            out.append(f"{where} {name}: {len(bad)} of {len(lanes)} unmarked "
                       f"lanes differ from transcend.{fn}, first "
                       f"{_hexes(bad, 2)}")
    for label, lane in (first_lanes(fn, fmt) if first is None else first):
        bits, fw = (evaluator or ml.evaluate)(f, lane)
        n_lanes += 1
        if not fw & MARK and (bits, fw) != golden(fmt, rnd, lane, fn):
            out.append(f"{where}: the first design's lane {label}: got "
                       f"({bits:#x}, {fw:#x}), want "
                       f"{tuple(hex(v) for v in golden(fmt, rnd, lane, fn))}")
    return out, (n_lanes, marked)


# ---- the specials: the study's section 4 --------------------------------------

def _rows(fmt, fn):
    """[(label, lanes)]: the rows of the study's section 4 for pow and powr
    (specials.py's), both signs of every zero and infinity where the row has
    them, and y's integrality and parity across MAGIC's band, the band of
    halves, the band of integers and past 2^p."""
    p, mw = fmt.prec, fmt.man_w
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    z, mz = sf.zero_bits(fmt), sf.zero_bits(fmt, 1)
    inf, minf = sf.inf_bits(fmt), sf.inf_bits(fmt, 1)
    qn, sn = sf.qnan_bits(fmt), sf.snan_bits(fmt)
    mx, mn = sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)
    S = fmt.sign_mask

    def v(s, m, e):
        # None where (-1)^s m 2^e is not a number of the format (a lane that
        # has one is dropped, as the model's specials.py drops it)
        b, fl = sf.round_pack(fmt, s, m, e, RNE)
        return None if fl else b
    fin = [v(0, 3, 0), v(1, 3, 0), v(0, 3, -2), v(1, 5, -3), mx, mx | S, mn,
           mn | S, v(0, 1, fmt.emin)]
    ally = [z, mz, inf, minf, qn, one, mone, v(0, 3, -1), v(1, 3, -1),
            v(0, 3, 0), v(1, 3, 0), mx, mx | S, mn, mn | S]
    oddy = [v(0, 3, 0), v(1, 3, 0), one, mone, v(0, (1 << p) - 1, 0),
            v(1, (1 << p) - 1, 0), v(0, (1 << (p - 2)) - 1, 0),
            v(0, (1 << (p - 2)) + 1, 0), v(1, (1 << (p - 2)) + 3, 0),
            v(0, (1 << (p - 1)) - 1, 0), v(1, (1 << (p - 1)) + 1, 0)]
    eveny = [v(0, 2, 0), v(1, 2, 0), v(0, 1, p), v(1, 1, p + 5), mx, mx | S,
             v(0, 1, p - 2), v(0, (1 << (p - 2)) + 2, 0),
             v(1, (1 << (p - 1)) - 2, 0), v(0, (1 << (p - 1)) + 2, 0)]
    noninty = [v(0, 1, -1), v(1, 3, -1), mn, v(0, (1 << p) - 1, -1),
               v(1, 1, -p), v(0, (1 << (p - 1)) + 1, -1),
               v(1, (1 << p) - 1, -1)]
    R = [("y = +-0 (pow: 1, even x = NaN; powr: finite x > 0)",
          [(a, b) for a in fin + [z, mz, inf, minf, qn, one, mone]
           for b in (z, mz)]),
         ("x = +1 (pow: 1, even y = NaN; powr: finite y)",
          [(one, b) for b in ally]),
         ("x = -1 and y = +-inf", [(mone, inf), (mone, minf)]),
         ("a sNaN in either operand",
          [(sn, b) for b in (z, one, qn)]
          + [(a, sn) for a in (one, z, qn, mone)]),
         ("a qNaN in either, no row above",
          [(qn, b) for b in (one, mone, inf, v(0, 3, 0))]
          + [(a, qn) for a in (mone, z, inf, v(0, 3, 0), v(1, 3, 0))]),
         ("x = +-0, y < 0 (odd, even, non-integer, -inf)",
          [(a, b) for a in (z, mz) for b in
           (mone, v(1, 3, 0), v(1, 2, 0), v(1, 3, -1), mx | S, minf)]),
         ("x = +-0, y > 0",
          [(a, b) for a in (z, mz) for b in
           (one, v(0, 3, 0), v(0, 2, 0), v(0, 3, -1), mx, inf, mn)]),
         ("x = +-inf",
          [(a, b) for a in (inf, minf) for b in
           (one, mone, v(0, 3, 0), v(1, 3, 0), v(0, 2, 0), v(1, 2, 0),
            v(0, 3, -1), v(1, 3, -1), inf, minf, mn, mx)]),
         ("y = +-inf, |x| < 1 and > 1",
          [(a, b) for a in (v(0, 1, -1), v(1, 1, -1), v(0, 3, 0), v(1, 3, 0),
                            mn, mx, one - 1, one + 1) for b in (inf, minf)]),
         ("x < 0 finite, y not an integer",
          [(a, b) for a in (mone, v(1, 3, 0), mx | S, mn | S)
           for b in noninty]),
         ("x < 0, y odd integer (sign kept), across y's bands",
          [(a, b) for a in (v(1, 3, 0), v(1, 5, -3), v(1, 1, -3), mone + 1,
                            mone - 1) for b in oddy]),
         ("x < 0, y even integer, y past 2^p",
          [(a, b) for a in (v(1, 3, 0), v(1, 5, -3), mone + 1)
           for b in eveny]),
         ("y = 1: x itself (exact)", [(a, one) for a in fin]),
         ("subnormal operands",
          [(mn, v(0, 1, -1)), (mn, one + 1),
           (v(0, 3, fmt.emin - p), v(0, 1, -1)), (v(0, 1, -2), v(0, 1, 1)),
           (mn, mone), (v(0, 3, -p), v(0, 3, 0))]),
         ("overflowing and underflowing results",
          [(v(0, 1, 1), v(0, fmt.emax, 0)), (v(0, 1, 1), v(0, fmt.emax + 1, 0)),
           (v(0, 1, 1), v(1, -(fmt.emin - mw - 1), 0)),
           (v(0, 1, 1), v(1, -(fmt.emin - mw), 0)),
           (v(0, 1, 1), v(1, -(fmt.emin - mw - 2), 0)),
           (v(0, 10, 0), v(0, 400, 0)), (v(0, 10, 0), v(1, 400, 0)),
           (v(0, 3, 0), mx), (v(0, 3, -2), mx), (mx, v(0, 3, -1)),
           (mx, v(0, 2, 0)), (mn, v(0, 2, 0)), (mn, v(1, 1, -1))])]
    R = [(label, [ln for ln in lanes
                  if ln[0] is not None and ln[1] is not None])
         for label, lanes in R]
    if fn == "powr":
        R += [("powr: x < 0 (every y, qNaN included)",
               [(a, b) for a in (mone, v(1, 3, 0), minf, mn | S)
                for b in (z, one, qn, inf, v(0, 3, -1))]),
              ("powr: +-0 to +-0, +inf to +-0, +1 to +-inf",
               [(a, b) for a in (z, mz) for b in (z, mz)]
               + [(inf, z), (inf, mz), (one, inf), (one, minf)])]
    return R


# the rows by function (M3G2 assigns its own)
SPECIAL_ROWS = {"pow": lambda fmt: _rows(fmt, "pow"),
                "powr": lambda fmt: _rows(fmt, "powr")}


def special_rows(fn, fmt):
    return SPECIAL_ROWS[fn](fmt)


# The marks of the rows: the lanes of a row that go through the core and may be
# marked, summed over the five attributes (the model's specials.fp64, fp128 and
# fp256 .out.txt, the same at the three formats: MEASURED by the model, which a
# special row should never mark but for the lanes the core answers). A row not
# listed marks nothing.
SPECIAL_MARKS = {
    "pow": {"x < 0, y odd integer (sign kept), across y's bands": 34,
            "x < 0, y even integer, y past 2^p": 20,
            "subnormal operands": 5},
    "powr": {"subnormal operands": 5}}


def check_specials(fmt, fn, frags, evaluator=None, rows=None, marks=None):
    """[finding], lanes: specials. Every row of the function's special_rows()
    through the five fragments `frags` {rnd: Fragment}: unmarked lanes equal to
    transcend.py in bits AND flag word, and the marks of a row, summed over the
    attributes, the model's (SPECIAL_MARKS). `evaluator` stands for ml.evaluate,
    for the test that plants a fault in it; `rows` for the table."""
    out, n = [], 0
    marks = SPECIAL_MARKS.get(fn, {}) if marks is None else marks
    for label, lanes in (special_rows(fn, fmt) if rows is None else rows):
        bad, got_marks = [], 0
        for rnd, f in frags.items():
            for lane in lanes:
                n += 1
                bits, fw = (evaluator or ml.evaluate)(f, lane)
                if fw & MARK:
                    got_marks += 1
                elif (bits, fw) != golden(fmt, rnd, lane, fn):
                    bad.append((rnd, lane, (bits, fw),
                                golden(fmt, rnd, lane, fn)))
        where = f"specials: {fn} {fmt.name}: row {label!r}"
        if bad:
            rnd, lane, got, want = bad[0]
            out.append(f"{where}: {len(bad)} unmarked lanes differ, first "
                       f"{sf.RND_NAMES[rnd]} {_hexes([lane])}: ({got[0]:#x}, "
                       f"{got[1]:#x}) against ({want[0]:#x}, {want[1]:#x})")
        if len(frags) == len(RND_MODES) and got_marks != marks.get(label, 0):
            out.append(f"{where}: {got_marks} marks over the five attributes, "
                       f"the model's {marks.get(label, 0)}")
    return out, n


# ---- the structured lanes ------------------------------------------------------
#
# A row is (label, lanes, expectation), the expectation one of
#   decided  unmarked and equal to transcend.py in bits and flag word under the
#            attribute: the lane the design decides in-lane (an exact power of
#            two, y = 1, beside 1)
#   marked   marked: an exact result the in-lane test cannot decide (the guess is
#            not compared: under a directed attribute it may be an ulp off, which
#            is why the lane is marked)
#   nearest  decided under rne and rmm, free under the directed attributes
#   midpoint marked under rne and rmm (the value is within the bound of a
#            midpoint), free under the directed attributes
#   free     unmarked and equal, or marked
# The plants' named lanes are the study's plants.py table (section 8), here
# plant_cases(): they enter as `free` lanes (a plant that gives a wrong
# unmarked answer makes one finding), and as `decided` where the plant's case is
# a lane the control decides and the plant marks (the kind "mark").

def _pow2_bits(fmt, k):
    return _V(fmt, 0, 1, k)


def _beside_one(fmt):
    """The lanes either side of the gate: x = 1 + ulp, y chosen so that t is
    nine tenths and eleven tenths of 2^-(p+3) (|t| below 2^-(p+3) is the rule
    beside 1, transcend.py's and the routine's gate). Returns (below, above)."""
    p = fmt.prec
    one = sf.one_bits(fmt)
    below, above = [], []
    for x in (one + 1, one + 5, one - 1):
        L = _log2(fmt, x)
        for scale, lst in ((Fraction(9, 10), below),
                           (Fraction(11, 10), above)):
            with mpmath.workprec(p + 64):
                y = _enc(fmt, ml._frac(mpmath.mpf(2) ** -(p + 3) / L)
                         * scale)
            for s in (0, 1):
                lst.append((x, y | (fmt.sign_mask if s else 0)))
    return below, above


def _exact_pow2(fmt):
    p = fmt.prec
    two, half = _pow2_bits(fmt, 1), _pow2_bits(fmt, -1)
    out = []
    for base in (two, half, _pow2_bits(fmt, 2), _pow2_bits(fmt, -3)):
        for k in (1, 2, 3, 5, 10, -1, -3, -10, 100):
            out.append((base, _enc(fmt, k)))
    out += [(two, _enc(fmt, fmt.emax)), (two, _enc(fmt, fmt.emin)),
            (two, _enc(fmt, fmt.emin - 1)), (half, _enc(fmt, fmt.emax)),
            (two, _enc(fmt, -(fmt.emax - 1))),
            (two, _enc(fmt, fmt.emin - p + 1)),      # the least subnormal
            (_pow2_bits(fmt, 3), _enc(fmt, Fraction(1, 3))),
            (_pow2_bits(fmt, 12), _enc(fmt, Fraction(1, 4)))]
    return out


def _exact_pow2_neg(fmt):
    """pow(-2^E, y) for integer y: the sign by y's parity, exact."""
    two = _pow2_bits(fmt, 1) | fmt.sign_mask
    half = _pow2_bits(fmt, -1) | fmt.sign_mask
    return [(b, _enc(fmt, k)) for b in (two, half)
            for k in (1, 2, 3, 4, 5, -2, -3, 11)]


def _exact_families(fmt):
    """(exact, neighbours): [(label, lane)] the exact cases that must mark
    (3^2, 10^3, 1.5^3, 9^0.5) and, one ulp of x or y away, their neighbours."""
    cases = [("3^2", Fraction(3), Fraction(2)),
             ("10^3", Fraction(10), Fraction(3)),
             ("1.5^3", Fraction(3, 2), Fraction(3)),
             ("9^0.5", Fraction(9), Fraction(1, 2))]
    exact, neigh = [], []
    for label, x, y in cases:
        xb, yb = _enc(fmt, x), _enc(fmt, y)
        exact.append((label, (xb, yb)))
        for d in (1, -1):
            neigh.append((f"{label} x{d:+d}ulp", (xb + d, yb)))
            neigh.append((f"{label} y{d:+d}ulp", (xb, yb + d)))
    return exact, neigh


def _notl_lane(fmt):
    """x = 2^E, y = RN(k/E): t = k + f with t_h = k and t_l = f != 0."""
    for E in (1000, 999, 997, 991, 701, 333, 120, 100, 77):
        if E > fmt.emax:
            continue
        for k in (3, 5, 7, 2, 1):
            y = _enc(fmt, Fraction(k, E))
            q = value(fmt, y) * E
            if q != k and abs(q - k) < Fraction(1, 2 ** (fmt.prec - 1)):
                return (_V(fmt, 0, 1, E), y)
    return None


def _screen_lane(fmt):
    """A lane whose ROUTINE's t_h0 is exactly emax + 1 and whose result is
    finite under rne (transcend.py's answer not an infinity): the low screen's
    overflow is wrong there. Searched on the control's probe th0."""
    p = fmt.prec
    top = fmt.emax + 1
    b = build_of("pow", fmt, RNE)
    for M_ in range(3, 400, 2):
        x = _V(fmt, 0, M_, 0)
        with mpmath.workprec(4 * p):
            y0 = ml._frac(mpmath.mpf(top) / mpmath.log(M_, 2))
        yb = _enc(fmt, y0)
        for d in range(-3, 4):
            y = yb + d
            _bits, _fl, pr = b.run((x, y), ("th0",))
            if value(fmt, pr["th0"]) != top:
                continue
            want = golden(fmt, RNE, (x, y), "pow")
            if (want[0] & ~fmt.sign_mask) != sf.inf_bits(fmt):
                return (x, y)
    return None


def _zero_lane(fmt):
    """pow(-2^E, d), d odd, d E = emin - p - 1: an exact -2^(emin-p-1), below
    half the least subnormal, which rounds to -0 with underflow under rne (the
    fixed grid's signed zero)."""
    t0 = fmt.emin - fmt.prec - 1
    for d in range(3, 1 << 20, 2):
        if t0 % d == 0:
            return (_V(fmt, 1, 1, t0 // d), _V(fmt, 0, d, 0))
    return None


@functools.lru_cache(maxsize=None)
def _midpoint_lane(fmt):
    """pow(x, 2) exactly a midpoint, x = (3 2^(h-2) + k) 2^-(h-1) near 1.5
    (h = (p + 2)/2, k odd: the square's odd part p + 1 bits), where the loose
    bound's answer is wrong under rne. Not near 1: there V's own error is below
    the ulp of V_l, which is the test's resolution, so no bound below it can
    leave a midpoint unmarked."""
    p = fmt.prec
    h = (p + 2) // 2
    two = _V(fmt, 0, 2, 0)
    b = build_of("pow", fmt, RNE, "bound_loose")
    for k in range(1, 4000, 2):
        Mx = 3 * (1 << (h - 2)) + k
        if (Mx * Mx).bit_length() != p + 1:
            continue
        x = _V(fmt, 0, Mx, -(h - 1))
        bits, fl, _ = b.run((x, two))
        if fl & MARK:
            continue
        if (bits, fl) != golden(fmt, RNE, (x, two), "pow"):
            return (x, two)
    return None


def plant_cases(fmt):
    """[(plant, fn, rnd, kind, lane)]: the study's plants.py table (section 8,
    cases()) at `fmt`, the lanes where each plant is red, kind `lane` (the lane
    is wrong and unmarked with the plant, right or marked without it), `mark`
    (the design decides the lane in-lane and the plant marks it) or `redundant`
    (midpoint_unmarked: equal to the control, shown equal, not counted). A lane
    is None where the format has none. The rootn and compound rows are parcel
    M3G2's."""
    p = fmt.prec
    one = sf.one_bits(fmt)

    def v(s, m, e):
        return _V(fmt, s, m, e)
    q = sf.qnan_bits(fmt)
    return [
        ("exact_unmarked", "pow", RNE, "lane", (v(0, 3, 0), v(0, 2, 0))),
        ("exact_unmarked", "pow", RNE, "lane", (v(0, 10, 0), v(0, 3, 0))),
        ("exact_rule_off", "pow", RTZ, "mark", (v(0, 1, 1), v(0, 10, 0))),
        ("exact_rule_off", "pow", RNE, "mark", (v(0, 1, -1), v(0, 3, 0))),
        ("exact_rule_no_tl", "pow", RNE, "lane", _notl_lane(fmt)),
        ("midpoint_unmarked", "pow", RNE, "redundant",
         (v(0, 3, -((fmt.man_w - fmt.emin + 1) // 5)), v(0, 5, 0))
         if (fmt.man_w - fmt.emin + 1) % 5 == 0 else None),
        ("bound_loose", "pow", RNE, "lane", _midpoint_lane(fmt)),
        ("pow_zero_nan", "pow", RNE, "lane", (q, 0)),
        ("pow_one_nan", "pow", RNE, "lane", (one, q)),
        ("sign_even", "pow", RNE, "lane",
         (_enc(fmt, Fraction(-11, 10)), v(0, 2, 0))),
        ("sign_odd_lost", "pow", RNE, "lane",
         (_enc(fmt, Fraction(-11, 10)), v(0, 3, 0))),
        ("zero_sign_lost", "pow", RNE, "lane", _zero_lane(fmt)),
        ("integrality_wide", "pow", RNE, "lane",
         ((one + 1) | fmt.sign_mask, v(0, (1 << (p - 2)) + 1, 0))),
        ("powr_neg_ok", "powr", RNE, "lane", (v(1, 1, 1), v(0, 1, -1))),
        ("powr_zero_zero", "powr", RNE, "lane", (0, 0)),
        ("near_one_gate_off", "pow", RTZ, "mark", (one + 1, v(0, 1, -60))),
        ("side_rule_off", "pow", RUP, "lane",
         (_enc(fmt, Fraction(6, 5)), sf.min_subnormal_bits(fmt))),
        ("side_rule_off", "pow", RTZ, "lane",
         (_enc(fmt, Fraction(5, 6)), sf.min_subnormal_bits(fmt))),
        ("screen_low", "pow", RNE, "lane", _screen_lane(fmt)),
        ("mark_silenced", "pow", RTZ, "lane", (v(0, 3, 0), v(0, 2, 0))),
    ]


def structured_rows(fn, fmt):
    """[(label, lanes, expectation)] for fn at fmt: the exact powers of two,
    y = 1, beside 1 on both sides of the gate, the tie, the exact families and
    their neighbours, the negative powers of two (pow), and the plants' named
    lanes of the function."""
    p = fmt.prec
    rows = [("exact powers of two (2^n, 0.5^n, integer t, both signs of n)",
             _exact_pow2(fmt), "decided"),
            ("y = 1: x itself", [(x, sf.one_bits(fmt)) for x in
                                 (_V(fmt, 0, 3, 0), _V(fmt, 0, 5, -7),
                                  sf.min_subnormal_bits(fmt),
                                  sf.max_normal_bits(fmt))], "decided"),
            ("the tie at half the least subnormal (pow(2, emin - p))",
             [(_pow2_bits(fmt, 1), _enc(fmt, fmt.emin - p))], "decided")]
    below, above = _beside_one(fmt)
    rows += [("beside 1, t below 2^-(p+3) (the gate, both signs of y)", below,
              "decided"),
             ("beside 1, t above the gate", above, "free")]
    exact, neigh = _exact_families(fmt)
    # (3 +- ulp)^2 is 9 +- 1.5 ulp(9) + u^2: a midpoint to within the bound, so
    # marked under rne and rmm; the other neighbours are decided
    mid = [l for n_, l in neigh if n_.startswith("3^2 x")]
    rows += [("exact cases that must mark by family", [l for _, l in exact],
              "marked"),
             ("their neighbours one ulp of x or y away",
              [l for n_, l in neigh if not n_.startswith("3^2 x")],
              "nearest"),
             ("3^2's neighbours in x: within the bound of a midpoint", mid,
              "midpoint")]
    if fn == "pow":
        rows.append(("negative powers of two, the sign by y's parity",
                     _exact_pow2_neg(fmt), "decided"))
    for plant, f_, rnd, kind, lane in plant_cases(fmt):
        if f_ == fn and lane is not None and kind != "redundant":
            rows.append((f"plant {plant} ({kind})", [lane],
                         "decided" if kind == "mark" else "free"))
    return rows


# the rows by function (M3G2 assigns its own)
STRUCT_ROWS = {"pow": lambda fmt: structured_rows("pow", fmt),
               "powr": lambda fmt: structured_rows("powr", fmt)}


def check_structured(f, evaluator=None, rows=None):
    """[finding], lanes: structured. Each row's lanes through the fragment under
    ITS attribute, against its expectation (the head of the section): decided,
    marked, nearest, midpoint, free."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    out, n = [], 0
    for label, lanes, expect in (STRUCT_ROWS[fn](fmt) if rows is None
                                 else rows):
        bad = []
        for lane in lanes:
            n += 1
            bits, fw = (evaluator or ml.evaluate)(f, lane)
            gb, gf = golden(fmt, rnd, lane, fn)
            mk = bool(fw & MARK)
            must_decide = expect == "decided" or \
                (expect == "nearest" and rnd in (RNE, RMM))
            if mk and must_decide:
                bad.append((lane, "is marked, the design decides it"))
            elif not mk and (expect == "marked" or (
                    expect == "midpoint" and rnd in (RNE, RMM))):
                bad.append((lane, "is not marked, the in-lane test cannot "
                                  "decide it"))
            elif not mk and (bits, fw) != (gb, gf):
                bad.append((lane, f"unmarked ({bits:#x}, {fw:#x}), want "
                                  f"({gb:#x}, {gf:#x})"))
        if bad:
            lane, why = bad[0]
            out.append(f"structured: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: row "
                       f"{label!r}: {len(bad)} of {len(lanes)} lanes wrong, "
                       f"first {_hexes([lane])} {why}")
    return out, n


# ---- seq: the fragment as a program ---------------------------------------------

def seq_lanes(fn, fmt):
    """The lanes of the seq check: every 8th lane of the function's pool, and
    every structured lane (the exact powers of two, y = 1, beside 1, the exact
    families, the plants' named lanes) and the special lanes of the loud leg
    (SEQ_LOUD)."""
    out = list(pool(fn, fmt)[::8])
    for _label, lanes, _e in STRUCT_ROWS[fn](fmt):
        out += lanes
    out += SEQ_LOUD(fmt)
    return tuple(dict.fromkeys(out))


def SEQ_LOUD(fmt):
    """Lanes on which an instruction that raises a flag outside the quiet
    region shows in the lane's byte: the largest finite x with y = 0 (the
    flag word of 1 is quiet, an early MUL of x overflows), a signalling NaN
    and the least subnormal against a large y."""
    mx = sf.max_normal_bits(fmt)
    return [(mx, 0), (sf.snan_bits(fmt), sf.one_bits(fmt)),
            (sf.min_subnormal_bits(fmt), _enc(fmt, 3)),
            (mx, _enc(fmt, 2)), (mx, _enc(fmt, Fraction(1, 2)))]


@functools.lru_cache(maxsize=None)
def seq_slice(fn, fmt):
    return seq_lanes(fn, fmt)


def _split(xs):
    """(a, b): the lanes' first and second operands, for seq.run: x in r0 and
    y in r1."""
    return [x[0] for x in xs], [x[1] for x in xs]


def check_seq(f, xs=None, evaluator=None, loud=False, post=None, rows=None):
    """[finding], lanes: seq. The fragment as a program on seq.py
    (routines.program and routines.run) equal to evaluate() lane for lane
    (`evaluator` stands for it, for the test that plants a fault in it) and,
    where unmarked, to transcend.py; the compiled shape (QUIET, the body,
    ENDQUIET, RAISE of the flag word: mathlib_harness.r24_program, `loud`
    leaving the first instruction that can raise a flag outside the region) with
    each lane's byte the IEEE flags of the operation and the mark in bit 7,
    FLAGS the OR of the bytes and STATUS[6] set exactly when a lane is marked
    (`post`, a function of seq.py's result, doctors it for the test); and the
    structured lanes that must be marked, marked in the byte."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    xs = list(seq_slice(fn, fmt) if xs is None else xs)
    rows = STRUCT_ROWS[fn](fmt) if rows is None else rows
    must = [lane for _l, lanes, e in rows if e == "marked" for lane in lanes]
    have = set(xs)
    xs += [x for x in dict.fromkeys(must) if x not in have]
    where = f"seq: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    ins = _split(xs)[:1] if fn in ml.POW_INT_NAMES else _split(xs)
    outs, words = routines.run(f, *ins)
    got = list(zip(outs, words))
    true = [ml.evaluate(f, lane_args(fn, x)) for x in xs]
    ev = true if evaluator is None else [evaluator(f, x) for x in xs]
    bad = [x for x, a, b in zip(xs, got, ev) if a != b]
    if bad:
        out.append(f"{where}: seq.py and evaluate() differ on {len(bad)} "
                   f"lanes, first {_hexes([bad[0]])}")
    wrong = [x for x, (bits, fw) in zip(xs, got)
             if not fw & MARK and (bits, fw) != golden(fmt, rnd, x, fn)]
    if wrong:
        out.append(f"{where}: {len(wrong)} unmarked lanes on seq.py differ "
                   f"from transcend.{fn}, first {_hexes([wrong[0]])}")
    prog, bank = H.r24_program(f, loud)
    res = seq.run(prog, *(ins if len(ins) > 1 else (ins[0], [0] * len(xs))),
                  bank=bank)
    if post is not None:
        res = post(res)
    flags_or, marked = 0, False
    for i, x in enumerate(xs):
        bits, fw = true[i]
        gb, gf = golden(fmt, rnd, x, fn)
        byte = res.lane_flags[i]
        flags_or |= byte & seq.LANE_FLAGS_IEEE
        if fw & MARK:
            marked = True
            want = (fw & 0x1F) | seq.LANE_MARKED
        else:
            want = gf
            if res.deposits[i] != gb:
                out.append(f"{where}: lane {_hexes([x])} deposited "
                           f"{res.deposits[i]:#x}, want {gb:#x}")
        if byte != want:
            out.append(f"{where}: lane {_hexes([x])} raised {byte:#x}, want "
                       f"{want:#x}")
    if res.flags != flags_or:
        out.append(f"{where}: FLAGS {res.flags:#x} is not the OR of the "
                   f"lanes' bytes {flags_or:#x}")
    status6 = bool(res.status & seq.STATUS_MARKED)
    if status6 != marked:
        out.append(f"{where}: STATUS[6] is {status6}, a marked lane was "
                   f"{'' if marked else 'not '}run")
    index = {x: i for i, x in enumerate(xs)}
    off = [x for x in must if not res.lane_flags[index[x]] & seq.LANE_MARKED]
    if off:
        out.append(f"{where}: {len(off)} of the committed lanes are not "
                   f"marked in the lane's byte, first {_hexes(off)}")
    return out[:8], xs


# ---- the bound -----------------------------------------------------------------

def _screened(fmt, pr):
    """The lane is taken by the screens: t_h0 at or past emax + 2 or at or below
    emin - p - 2."""
    try:
        th0 = value(fmt, pr["th0"])
    except ValueError:          # the product overflowed to an infinity
        return True
    return th0 >= fmt.emax + 2 or th0 <= fmt.emin - fmt.prec - 2


def bound_log2(b, lane, signed=True):
    """log2(|V - f 2^-k| / Bv) for one main-path lane of the build b: V the sum
    of its probes Vh and Vl, which is the result in the scaled domain (the final
    multiplications by 2^k1 and 2^k2 are after it: k = floor(n/8), n the probe
    nf), the true value from mpmath at 4p + 200 bits (the function's, signed).
    None where V is exact or the screens take the lane; 999.0 where V is not
    finite."""
    fmt = b.fmt
    _res, _fl, pr = b.run(lane_args(b.meta["fn"], lane),
                          ("Vh", "Vl", "Bv", "th0", "nf"))
    if _screened(fmt, pr):
        return None
    try:
        V = value(fmt, pr["Vh"]) + value(fmt, pr["Vl"])
        Bv = abs(value(fmt, pr["Bv"]))
    except ValueError:
        return 999.0
    with mpmath.workprec(4 * fmt.prec + 200):
        k = int(value(fmt, pr["nf"])) // 8
        err = abs(_mp(V) - true_value(b.meta["fn"], fmt, lane)
                  * mpmath.mpf(2) ** -k)
        if err == 0:
            return None
        return float(mpmath.log(err / _mp(Bv), 2))


# the regions in which no lane reaches the main path (every lane is a special
# row or a screened one: |y| from 2^p up makes |t| huge, so the screens answer
# it): check_bound is not asked to find a main-path lane there, and returns 0
# main-path lanes for it (at 48 points; a larger sample may reach a few). It
# does not say NOT MEASURED itself: a CALLER does (mathlib_runs.py's pow-bound
# prints a line naming the region NOT MEASURED, 0 main-path lanes, and keeps it
# out of its tally), and a caller keeps such a region out of any pass count
BOUND_NO_MAIN = {"hugey"}


def check_bound(b, lanes, label="random", need=1):
    """[finding], (worst log2(err/Bv), main-path lanes, lanes): bound. Every
    main-path lane of `lanes` under 1 Bv, and every lane equal to transcend.py
    in bits and flag word or marked; fewer than `need` main-path lanes is a
    finding (the region measures nothing: BOUND_NO_MAIN's are exempt, and the
    caller says so). The worst is the largest found, a lower bound on the true
    worst; the study's budget is parcel M3G3's (mathlib_pow_budget.py)."""
    fmt, fn = b.fmt, b.meta["fn"]
    worst, n, over, differ = -1e9, 0, [], []
    for lane in lanes:
        res, fw, pr = b.run(lane_args(fn, lane), ("th0",))
        if not fw & MARK and (res, fw) != golden(fmt, b.rnd, lane, fn):
            differ.append(lane)
        if not (in_main_n if fn in ml.POW_INT_NAMES else in_main)(
                fn, fmt, lane) or _screened(fmt, pr):
            continue
        r = bound_log2(b, lane)
        n += 1
        if r is None:
            continue
        worst = max(worst, r)
        if r >= 0:
            over.append((r, lane))
    where = f"bound: {fn} {fmt.name} {sf.RND_NAMES[b.rnd]} {label}"
    out = []
    if n < need and label.split()[0] not in BOUND_NO_MAIN:
        out.append(f"{where}: only {n} of {len(lanes)} lanes reach the main "
                   f"path, {need} wanted: the region measures nothing")
    if over:
        r, lane = max(over)
        out.append(f"{where}: {len(over)} of {n} main-path lanes are past the "
                   f"bound, the worst {_hexes([lane])} at 2^{r:+.2f} of Bv")
    if differ:
        out.append(f"{where}: {len(differ)} unmarked lanes differ from "
                   f"transcend.{fn}, first {_hexes([differ[0]])}")
    return out, (worst, n, len(lanes))


# ---- the shape -------------------------------------------------------------------

# (instructions, bank words, values live) of every fragment, in RND_MODES'
# order (rne, rtz, rdn, rup, rmm): MEASURED by parcel M3G1, and the model's: the
# port was shown equal to it, instruction for instruction and in its order, at
# all 30 configurations (the study's costs.fp64, fp128 and fp256 .out.txt: pow
# 434, 489 and 540 instructions and 30 live, powr 413, 468 and 519 and 23, 22
# and 22 live, under rne). POW_LIVE_CAP is the maximum of each row's live.
SHAPE = {
    ("pow", "fp64"): [(434, 129, 30), (429, 131, 28), (430, 132, 28),
                      (430, 130, 28), (434, 129, 30)],
    ("pow", "fp128"): [(489, 157, 30), (484, 159, 28), (485, 160, 28),
                       (485, 158, 28), (489, 157, 30)],
    ("pow", "fp256"): [(540, 202, 30), (535, 204, 28), (536, 205, 28),
                       (536, 203, 28), (540, 202, 30)],
    ("powr", "fp64"): [(413, 125, 23), (407, 126, 21), (407, 126, 21),
                       (407, 125, 21), (413, 125, 23)],
    ("powr", "fp128"): [(468, 153, 22), (462, 154, 21), (462, 154, 21),
                        (462, 153, 21), (468, 153, 22)],
    ("powr", "fp256"): [(519, 198, 22), (513, 199, 21), (513, 199, 21),
                        (513, 198, 21), (519, 198, 22)],
}
# the Fast2Sum and TwoSum counts (Build.meta), the same under every attribute:
# the model's (m3pow.py builds Fast2Sums only, no TwoSum)
EFT = {("pow", "fp64"): (26, 0), ("pow", "fp128"): (31, 0),
       ("pow", "fp256"): (32, 0), ("powr", "fp64"): (26, 0),
       ("powr", "fp128"): (31, 0), ("powr", "fp256"): (32, 0)}
# The values the flag word takes (the study's section 4, MEASURED by the
# model's costs.py): the inexact, invalid, divide-by-zero, overflow and underflow
# bits and the mark with the inexact
FLAG_WORDS = {fn: frozenset({0x0, 0x1, 0x2, 0x10, 0x14, 0x18, 0x90, 0x94,
                             0x98}) for fn in FUNCS}
# (MIN, MAX) instructions: none
MIN_MAX = {fn: (0, 0) for fn in FUNCS}

# instructions by phase under rne (Build.phase_of over the live instructions),
# the model's (MEASURED by the port against the model at all 30 configurations,
# the study's costs.fp64, fp128 and fp256 .out.txt): the other attributes' differ
# by PHASE_DELTA, the same at the three formats; rmm's are rne's
PHASES_RNE = {
    ("pow", "fp64"): {"Z": 8, "classify": 14, "final": 44, "fixed-grid": 26, "front": 19, "head": 144, "head2": 16, "lookup": 17, "recon": 29, "reduce": 30, "scale": 15, "special": 36, "table": 17, "tail": 19},
    ("pow", "fp128"): {"Z": 8, "classify": 14, "final": 45, "fixed-grid": 26, "front": 19, "head": 183, "head2": 11, "lookup": 17, "recon": 29, "reduce": 30, "scale": 15, "special": 36, "table": 17, "tail": 39},
    ("pow", "fp256"): {"Z": 8, "classify": 14, "final": 45, "fixed-grid": 26, "front": 19, "head": 191, "head2": 11, "lookup": 17, "recon": 29, "reduce": 30, "scale": 15, "special": 36, "table": 17, "tail": 82},
    ("powr", "fp64"): {"Z": 8, "classify": 14, "final": 41, "fixed-grid": 24, "head": 144, "head2": 16, "lookup": 17, "recon": 29, "reduce": 30, "scale": 15, "special": 39, "table": 17, "tail": 19},
    ("powr", "fp128"): {"Z": 8, "classify": 14, "final": 42, "fixed-grid": 24, "head": 183, "head2": 11, "lookup": 17, "recon": 29, "reduce": 30, "scale": 15, "special": 39, "table": 17, "tail": 39},
    ("powr", "fp256"): {"Z": 8, "classify": 14, "final": 42, "fixed-grid": 24, "head": 191, "head2": 11, "lookup": 17, "recon": 29, "reduce": 30, "scale": 15, "special": 39, "table": 17, "tail": 82},
}
PHASE_DELTA = {
    "pow": {"rtz": {"fixed-grid": -3, "scale": -2},
            "rdn": {"fixed-grid": -3, "scale": -2, "special": 1},
            "rup": {"fixed-grid": -3, "scale": -2, "special": 1}, "rmm": {}},
    "powr": {"rtz": {"final": -1, "fixed-grid": -3, "scale": -2},
             "rdn": {"final": -1, "fixed-grid": -3, "scale": -2},
             "rup": {"final": -1, "fixed-grid": -3, "scale": -2}, "rmm": {}}}


def model_phases(fn, fmt_name, rnd):
    """The model's instructions by phase for fn at the format under rnd."""
    if (fn, fmt_name) not in PHASES_RNE:
        raise ValueError(f"no phases of {fn} at {fmt_name} pinned")
    out = dict(PHASES_RNE[(fn, fmt_name)])
    for k, d in PHASE_DELTA[fn].get(sf.RND_NAMES[rnd], {}).items():
        out[k] = out.get(k, 0) + d
    return out


class Tables:
    """The pinned data the shape check reads, one attribute a table, so that a
    test can doctor one and show its leg fail alone."""

    def __init__(self, **kw):
        self.shape = SHAPE
        self.phases = model_phases
        self.eft = EFT
        self.flag_words = FLAG_WORDS
        self.min_max = MIN_MAX
        self.caps = ml.POW_LIVE_CAP
        for k, v in kw.items():
            if not hasattr(self, k):
                raise ValueError(f"no table {k!r}")
            setattr(self, k, v)


def check_shape(fmt, builds, tables=None, fragments=None):
    """[finding]: shape. `builds`: {(fn, rnd): Build} for the functions built
    under all five attributes at `fmt`. Per fragment: (instructions, words,
    live) the pinned ones; the instructions by phase and the Fast2Sum and
    TwoSum counts the model's; the flag word's values exactly the study's; MIN
    and MAX as pinned; the scheduled fragment the design's reordered
    (mathlib_harness.check_reorder); its own invariants under POW_LIVE_CAP.
    Per function: its POW_LIVE_CAP entry the measured maximum under the five
    attributes, the fragment of that maximum holding to it and failing, by
    name, a cap one under. `tables` (Tables) holds the pinned data, one
    attribute a table; `fragments` {(fn, rnd): Fragment} stands for the builds'
    own scheduled fragments: both are for the tests that doctor one leg."""
    t = tables or Tables()
    name = fmt.name
    out = []
    frags = fragments or {k: b.fragment() for k, b in builds.items()}
    fns = sorted({fn for fn, _ in builds})
    for (fn, rnd), b in sorted(builds.items()):
        f = frags[(fn, rnd)]
        where = f"shape: {fn} {name} {sf.RND_NAMES[rnd]}"
        want = t.shape[(fn, name)][RND_MODES.index(rnd)]
        got = (len(f), len(f.words), f.live_max())
        if got != tuple(want):
            out.append(f"{where}: {got[0]} instructions, {got[1]} words, "
                       f"{got[2]} values live; pinned {want[0]}, {want[1]}, "
                       f"{want[2]}")
        by = dict(collections.Counter(b.phase_of[i]
                                      for i in b.live_indices()))
        mp = t.phases(fn, name, rnd)
        if by != mp:
            diff = {k: (by.get(k, 0), mp.get(k, 0))
                    for k in set(by) | set(mp) if by.get(k, 0) != mp.get(k, 0)}
            out.append(f"{where}: instructions by phase differ from the "
                       f"model's (phase: got, model's): {diff}")
        eft = (b.meta["fast_two_sum"], b.meta["two_sum"])
        if eft != tuple(t.eft[(fn, name)]):
            out.append(f"{where}: {eft[0]} Fast2Sums and {eft[1]} TwoSums, "
                       f"the model's {t.eft[(fn, name)][0]} and "
                       f"{t.eft[(fn, name)][1]}")
        fw = routines.flag_words(f)
        if fw != t.flag_words[fn]:
            out.append(f"{where}: the flag word takes "
                       f"{sorted(hex(w) for w in fw or ())}, the study's "
                       f"{sorted(hex(w) for w in t.flag_words[fn])}")
        counts = f.counts()
        if (counts.get("min", 0), counts.get("max", 0)) != t.min_max[fn]:
            out.append(f"{where}: {counts.get('min', 0)} MIN and "
                       f"{counts.get('max', 0)} MAX instructions, the "
                       f"design's {t.min_max[fn][0]} and {t.min_max[fn][1]}")
        out += [f"shape: {s}" for s in H.check_reorder(b, f)]
        out += [f"{where}: invariants: {s}"
                for s in ml.invariants(f, live_cap=t.caps[fn][name])]
    for fn in fns:
        lives = {rnd: frags[(fn_, rnd)].live_max()
                 for fn_, rnd in builds if fn_ == fn}
        top = max(lives.values())
        cap = t.caps[fn][name]
        if cap != top:
            out.append(f"shape: {fn} {name}: the cap is {cap}, the most "
                       f"values live under any attribute is {top}")
        worst = frags[(fn, max(lives, key=lives.get))]
        if ml.invariants(worst, live_cap=top) != []:
            out.append(f"shape: {fn} {name}: the maximal fragment fails its "
                       f"own cap {top}")
        under = ml.invariants(worst, live_cap=top - 1)
        if under != [f"{top} values live at once, past {top - 1}"]:
            out.append(f"shape: {fn} {name}: a cap one under ({top - 1}) does "
                       f"not fail by name: {under}")
    return out


# ---- core: build_pow_core ----------------------------------------------------------

def core_lanes(fmt, n=40, seed=31):
    """(x, y_h, y_l) placed so that t = Y log2|x| is on the main path, the low
    word of both signs: x log-uniform over the format's range, y_h from t
    uniform, y_l = +-u 2^-(p+1) y_h with u in (0.01, 1)."""
    rng = random.Random(seed * 1009 + fmt.width)
    p = fmt.prec
    Tf = ml._pow_t_reach(fmt) - 3
    out = []
    while len(out) < n:
        x = _rand_mag(fmt, rng, fmt.emin - p + 1, fmt.emax)
        yh = _y_for(fmt, x, rng.uniform(-Tf, Tf))
        if yh is None:
            continue
        yv = value(fmt, yh)
        sign = 1 if len(out) % 2 else -1
        yl = _enc(fmt, sign * yv * Fraction(rng.randint(1, 100), 100)
                  / 2 ** (p + 1))
        out.append((x, yh, yl))
    return out


def check_core(fmt, rnd=RNE, plant=None, lanes=None, b=None, plain=None):
    """[finding], (worst, lanes): core. build_pow_core(double=True) against
    mpmath at 4p + 200 bits on placed (x, y_h, y_l): |V_h + V_l - |x|^(y_h + y_l)|
    under 1 Bv, the low word of both signs among the lanes (a finding where one
    sign is missing); the plain build's V_h + V_l against |x|^y within Bv on the
    same x and y_h (`plain` stands for that build, for the test that doctors
    it); the Fraction path of the bound is _check_ybound's."""
    b = core_of(fmt, rnd, plant, True) if b is None else b
    lanes = core_lanes(fmt) if lanes is None else lanes
    where = f"core: {fmt.name} {sf.RND_NAMES[rnd]}"
    out, worst, n, signs = [], -1e9, 0, set()
    over = []
    for x, yh, yl in lanes:
        _r, _f, pr = b.run((x, yh, yl), ("Vh", "Vl", "Bv", "th0", "nf"))
        if _screened(fmt, pr):
            continue
        signs.add(bool(yl & fmt.sign_mask))
        n += 1
        Y = value(fmt, yh) + value(fmt, yl)
        k = int(value(fmt, pr["nf"])) // 8
        with mpmath.workprec(4 * fmt.prec + 200):
            true = mpmath.power(_mp(value(fmt, x)), _mp(Y))                 * mpmath.mpf(2) ** -k
            V = _mp(value(fmt, pr["Vh"]) + value(fmt, pr["Vl"]))
            err = abs(V - true)
            if err == 0:
                continue
            r = float(mpmath.log(err / _mp(abs(value(fmt, pr["Bv"]))), 2))
        worst = max(worst, r)
        if r >= 0:
            over.append((r, (x, yh, yl)))
    if over:
        r, lane = max(over)
        out.append(f"{where}: {len(over)} of {n} lanes are past the bound, "
                   f"the worst {_hexes([lane])} at 2^{r:+.2f} of Bv")
    if signs != {True, False}:
        out.append(f"{where}: the low word y_l has "
                   f"{'only one sign' if signs else 'no lane'} among the "
                   f"{n} main-path lanes")
    # the plain build, on the same x and y_h (x positive: pow's sign is pow's)
    try:
        pb = plain or build_of("pow", fmt, rnd, plant)
    except ValueError:
        pb = None
    if pb is not None:
        for x, yh, _yl in lanes[:8]:
            r = bound_log2(pb, (x, yh))
            if r is not None and r >= 0:
                out.append(f"{where}: the plain build is past the bound on "
                           f"{_hexes([(x, yh)])}: 2^{r:+.2f} of Bv")
                break
    return out, (worst, n)


def _check_ybound(fmt, n_int=1000, b=None, ybound=None):
    """[finding]: core. The Fraction path of pow_core's `ybound` (parcel M3G2's
    |n| or 1/|n|): a core whose Y is the constant word n, built by hand, whose
    Bv must be at least the exact bound |V| (2^-(p+G) + |t_h| B1 + |n k| B2)
    and no more than it with the last roundings (2^-(p-2) relative), on lanes
    x. `ybound` stands for the Fraction handed (a doctored one fails). Where B2
    is 0 (fp128, fp256) the term is not built and the leg says so."""
    out = []
    G = ml.GUARD[fmt.name]
    P = ml.plan_pow(fmt, G)
    if not P.B2:
        return [], 0
    b0 = ml._pow_setup("pow_core", fmt, RNE, G, 0, None)
    b0.inputs = ("a",)
    k_ = ml._pow_words(b0)
    b0.phase = "classify"
    cl = ml._classify_common(b0, k_)
    Yh = b0.word(_enc(fmt, n_int), "NH")
    yb = Fraction(abs(n_int)) if ybound is None else ybound
    core = ml.pow_core(b0, k_, cl, Yh, None, yb, negres=None, sgnw=None,
                       up=lambda: b0.icmplt(k_["ONE"], cl.ax))
    b0.finish(core.Vh, core.Vl)
    rng = random.Random(7)
    p = fmt.prec
    bad, n = 0, 0
    for _ in range(24):
        x = _enc(fmt, Fraction(rng.uniform(0.5, 0.95)))
        _r, _f, pr = b0.run(x, ("Vh", "th", "Bv", "kf", "th0"))
        if _screened(fmt, pr):
            continue
        n += 1
        kf = abs(value(fmt, pr["kf"]))
        need = abs(value(fmt, pr["Vh"])) * (
            Fraction(1, 2 ** (p + G)) + abs(value(fmt, pr["th"])) * P.B1
            + abs(Fraction(n_int)) * kf * P.B2)
        got = value(fmt, pr["Bv"])
        if not need <= got <= need * (1 + Fraction(1, 2 ** (p - 3))):
            bad += 1
    if bad:
        out.append(f"core: {fmt.name}: the Fraction ybound's Bv is not the "
                   f"exact bound, upward rounded, on {bad} of {n} lanes")
    return out, n


# ---- the constants ----------------------------------------------------------------

def check_constants(**kw):
    """[finding], lines: constants. mathlib.check_pow_constants() in process,
    at POW_FORMATS unless `formats` is given."""
    kw.setdefault("formats", FORMATS)
    lines, findings = ml.check_pow_constants(**kw)
    return [f"constants: {s}" for s in findings], lines


def check_constants_cli():
    """[finding], output: constants. `python -m cft_golden.mathlib --check
    --only pow` in a process of its own, exit 0 and its last line ending
    `0 differences`, listing every routine and format."""
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--check", "--only", "pow"], capture_output=True,
                       text=True, cwd=ROOT / "python")
    out = r.stdout.strip().splitlines()
    findings = []
    if r.returncode != 0:
        findings.append(f"constants: --check --only pow exited {r.returncode}")
    want = (f"mathlib --check (pow): {len(ml._POW_BUILDERS)} routines, "
            f"{len(ml.POW_FORMATS)} formats, 0 differences")
    if not out or out[-1] != want:
        findings.append(f"constants: the last line is "
                        f"{out[-1] if out else r.stderr[-200:]!r}, not "
                        f"{want!r}")
    n = sum(1 for ln in out if ln.split(" ")[0] in ml._POW_BUILDERS)
    if n != len(ml._POW_BUILDERS) * len(ml.POW_FORMATS):
        findings.append(f"constants: {n} routine lines, "
                        f"{len(ml._POW_BUILDERS) * len(ml.POW_FORMATS)} "
                        f"wanted")
    return findings, out


# ---- the plants: every check on every plant ---------------------------------------

POWR_ONLY = {"powr_neg_ok", "powr_zero_zero"}


def _reaches(fn, fmt, rnd, plant):
    """The plant's fault is reached by the build of fn at fmt under rnd (a build
    refuses it by name where it is not: "does not apply")."""
    try:
        build_of(fn, fmt, rnd, plant)
    except ValueError as e:
        if "does not apply" not in str(e):
            raise
        return False
    return True


def plant_fn(plant):
    """The function a plant is red on: powr for powr's own, else pow."""
    return "powr" if plant in POWR_ONLY else "pow"


def red_checks(plant, fmt=FP64, fn=None, rnds=(RNE,), bound_n=8,
               region_n=6):
    """{check: [findings]} for the checks that are RED on `plant` (None: the
    control) at `fmt`, on the function the plant acts on (plant_fn): pools,
    regions, specials and seq under `rnds` (seq under the first alone), the
    structured lanes under all five attributes, shape under all five, bound over
    the placed regions (bound_n points each) under rne, core (rne) and
    constants (rne). A check a plant cannot reach (a fault outside the core, for
    core) is green there: build_pow_core refuses the plant by name and the check
    does not run. GREEN means green at this scope, which is smaller than the
    tests' own on the control."""
    fn = fn or plant_fn(plant)
    red = {}

    def add(name, found):
        if found:
            red.setdefault(name, []).extend(found)
    # the attributes a plant acts under (exact_unmarked and midpoint_unmarked
    # are faults of the nearest attributes' test: under rtz, rdn and rup they
    # are refused by name, and the checks skip those attributes)
    reach = [rnd for rnd in RND_MODES if _reaches(fn, fmt, rnd, plant)]
    if not reach:
        raise ValueError(f"plant {plant!r} does not apply to {fn} at "
                         f"{fmt.name} under any attribute")
    rnds = tuple(r for r in rnds if r in reach) or (reach[0],)
    for rnd in rnds:
        add("pools", check_pools(fragment_of(fn, fmt, rnd, plant))[0])
    add("seq", check_seq(fragment_of(fn, fmt, rnds[0], plant))[0])
    regs = {r: region(fmt, fn, r, region_n, 1) for r in REGION_NAMES[fn]}
    # the regions under rne, rtz and rup: the first design's lanes by name
    # (side_rule_off's) are directed ones
    for rnd in (RNE, RTZ, RUP):
        if rnd in reach:
            add("regions", check_regions(fragment_of(fn, fmt, rnd, plant),
                                         regs)[0])
    for rnd in reach:
        add("structured", check_structured(fragment_of(fn, fmt, rnd,
                                                       plant))[0])
    add("specials", check_specials(
        fmt, fn, {rnd: fragment_of(fn, fmt, rnd, plant) for rnd in rnds})[0])
    b = build_of(fn, fmt, RNE, plant)
    for r, lanes in placed_points(fn, fmt, bound_n).items():
        add("bound", check_bound(b, lanes, r)[0])
    add("shape", check_shape(fmt, {(fn, rnd): build_of(fn, fmt, rnd, plant)
                                   for rnd in reach}))
    try:
        core_of(fmt, RNE, plant, True)
    except ValueError as e:
        if "does not apply" not in str(e):
            raise
    else:
        add("core", check_core(fmt, RNE, plant)[0])
    add("constants", check_constants(
        builder=lambda name, f_, r_: build_of(name, f_, r_, plant),
        formats=(fmt,), attrs=(RNE,), names=(fn,))[0])
    return red


# ---- pown, rootn and compound: parcel M3G2 builds here ----

# The lane of pown, rootn and compound is the pair (x, n): x an encoding and n
# the build's integer operand (a Python int). Their fragments are keyed by n
# (mathlib._POW_N_BUILDERS), so every check below takes the n it runs at, and
# its findings name it. FUNCS and the pow-only tables above stay pow and powr.
INT_FUNCS = ml.POW_INT_NAMES
EV_N = lambda f, lane: ml.evaluate(f, (lane[0],))        # noqa: E731


@functools.lru_cache(maxsize=None)
def build_n(fn, fmt, rnd, n, plant=None):
    """ml.build(fn, fmt, rnd, n=n, plant=plant), once (a Build is never
    mutated by a check)."""
    return ml.build(fn, fmt, rnd, n=n, plant=plant)


@functools.lru_cache(maxsize=None)
def fragment_n(fn, fmt, rnd, n, plant=None):
    """The scheduled fragment (the library's own, held to its invariants, for
    no plant)."""
    if plant is None:
        return ml.fragment(fn, fmt, rnd, n)
    return build_n(fn, fmt, rnd, n, plant).fragment()


def check_ns(fn, fmt):
    """The n list of fn at fmt (mathlib.pow_check_ns)."""
    return ml.pow_check_ns(fn, fmt)


def check_attrs(fmt, n):
    return ml.pow_check_attrs(fmt, n)


def in_main_n(fn, fmt, lane):
    """The lane (x, n) is one the main path answers (the model's regions.py
    main_lane): x finite and nonzero, n not 0 or 1, rootn's x < 0 only for an
    odd n, compound's x > -1. The screens may still take it."""
    x, n = lane
    if sf.unpack(fmt, x).kind in (sf.NAN, sf.INF, sf.ZERO) or n in (0, 1):
        return False
    q = value(fmt, x)
    if fn in ("pown", "rootn") and abs(q) == 1:
        return False              # L = 0: t = 0, nothing of the core to measure
    if fn == "rootn":
        return not (q < 0 and n % 2 == 0)
    if fn == "compound":
        return q > -1
    return True


def _true_pown(fmt, lane):
    X, n = value(fmt, lane[0]), lane[1]
    mag = mpmath.power(abs(_mp(X)), n)
    return -mag if (X < 0 and n % 2) else +mag


def _true_rootn(fmt, lane):
    X, n = value(fmt, lane[0]), lane[1]
    mag = mpmath.power(abs(_mp(X)), mpmath.mpf(1) / n)
    return -mag if (X < 0 and n % 2) else +mag


def _true_compound(fmt, lane):
    X, n = value(fmt, lane[0]), lane[1]
    return mpmath.power(_mp(X + 1), n)


TRUE_FNS.update({"pown": _true_pown, "rootn": _true_rootn,
                 "compound": _true_compound})


# ---- the pools: (x, n) pairs, one pool for the three, grouped by n -----------

def _int_pool(fmt):
    """The vector sets' (operand, n) pairs (vectors.transcend_int_pow_cases as
    transcend_cases calls it: 24 extra, seed 17) and the stage's (host/tests/
    transcend_check.py's int_pow_cases at its default trials, seed 5),
    deduplicated in order: 4,260, 4,131 and 3,204 pairs over 31 distinct n."""
    tc = H._transcend_check()
    return _dedup(list(vectors.transcend_int_pow_cases(fmt, 24, 17))
                  + list(tc.int_pow_cases(fmt, _trials(fmt), 5)))


POOL_FNS.update({fn: _int_pool for fn in INT_FUNCS})
# the pool's lanes the golden stage runs of each n: every POOL_STEP-th (the
# whole pools are pow-pools', on the box)
POOL_STEP = 3


@functools.lru_cache(maxsize=None)
def pool_n(fn, fmt, n, step=POOL_STEP):
    """The lanes of the pool of fn at fmt whose integer operand is n, every
    `step`-th."""
    return tuple([ln for ln in pool(fn, fmt) if ln[1] == n][::step])


def check_pools_n(fn, fmt, rnd, n, plant=None, step=POOL_STEP, marks=None):
    """[finding], Tally: pools, at n. The lanes of pool_n against transcend.py,
    unmarked equal in bits and flag word, the marks counted and pinned to the
    model's (POOL_MARKS_N: over the lanes this step takes; None where the pool
    has none of n). `marks` stands for the pinned count."""
    f = fragment_n(fn, fmt, rnd, n, plant)
    xs = pool_n(fn, fmt, n, step)
    if marks is None and step == POOL_STEP and xs:
        marks = POOL_MARKS_N.get((fn, fmt.name, n), {}).get(
            sf.RND_NAMES[rnd])
    out, t = check_pools(f, list(xs), marks=marks, size=None)
    return [s.replace("pools:", f"pools: n = {n}:", 1) for s in out], t


# ---- the placed regions of the integer operand (the study's regions.py) -------
#
#   int<N>   x placed so that t = n log2|x| (pown: t uniform in range; rootn:
#            x log-uniform over the format's range, t = log2|x|/n; compound:
#            1 + x across (0, max] and x in [-1/2, -2^-(p+4)], |n log2(1 + x)|
#            in range), either sign of x where the function allows, at n = N:
#            int (3), int-neg (-3), int17, int1000, int31 (2^31 - 1), int63
#            (-2^63: the study's 3.3 finds no main-path lane in it)
#   zone     |x| (1 + x for compound) in the cancelling zone of M1's reduction,
#            [1/2, 241/256), as pow's zone, at n = 3; zone<N> at n = N (where
#            |n L| is still in range at the zone's top: 12,000 at fp64,
#            188,000 at fp128, 2,990,000 at fp256; 1,000 at fp64 too)
#   m1edge   compound: x just above -1: x = -(1 - k ulp) with k log-uniform to
#            2^(p-1), so 1 + x = k ulp exactly (Sterbenz), n small enough
#   nlow     pown and compound at fp64: n over NLOW_NS (n_l nonzero of both
#            signs) and x = 1 + k ulp or 1 - k ulp (compound: x = +-k ulp), k up
#            to the largest for which |n log2 x| is below T_f, and their mirrors
#            (x negated where n is odd, for pown)
REGION_N = {"int": 3, "int-neg": -3, "int17": 17, "int1000": 1000,
            "int31": 2 ** 31 - 1, "int63": -2 ** 63}
NLOW_NS = (2 ** 53 + 1, 2 ** 54 + 3, 2 ** 60 + 5, -(2 ** 54 + 3))
ZONE_BIG = {"fp64": 12000, "fp128": 188000, "fp256": 2990000}


def region_names_n(fn, fmt):
    """The regions of fn at fmt, in the order they are reported."""
    names = list(REGION_N) + ["zone"]
    if fmt.name == "fp64":
        names.append("zone1000")
    names.append(f"zone{ZONE_BIG[fmt.name]}")
    if fmt.name == "fp64" and fn in ("pown", "compound"):
        names.append("nlow")
    if fn == "compound":
        names.append("m1edge")
    return tuple(names)


REGION_NAMES.update({fn: ("int", "int-neg", "int17", "int1000", "int31",
                          "int63", "zone") for fn in INT_FUNCS})
# the lanes a region at each format: the box command's size, set as pow's (400
# at fp64 and 80 above; the study's own run took 150 at fp64, its
# regions_run.fp64-pown.out.txt); a check takes a tenth by default
# (check_regions_n) and the golden stage's test fewer
REGION_LANES.update({(fn, f.name): (400 if f.name == "fp64" else 80)
                     for fn in INT_FUNCS for f in FORMATS})


def region_n_of(name, fmt=None):
    """The n of region `name`: REGION_N's, zone's 3, zone<N>'s and int<N>'s N;
    None for nlow (its own set) and m1edge (n small)."""
    if name in REGION_N:
        return REGION_N[name]
    if name == "zone":
        return 3
    m = re.fullmatch(r"(?:int|zone)(-?\d+)", name)
    if m:
        return int(m.group(1))
    return None


def _nlow_kmax(fmt, n, below):
    """The largest k with |n log2(1 +- k ulp)| below T_f (1 - k ulp is k half
    ulps below 1): by mpmath, then checked at k + 1."""
    Tf = ml._pow_t_reach(fmt) - 3
    p = fmt.prec
    ulp = Fraction(1, 2 ** ((p - 1) + (1 if below else 0)))

    def ok(k):
        q = 1 - k * ulp if below else 1 + k * ulp
        with mpmath.workprec(p + 64):
            return abs(n * mpmath.log(_mp(q), 2)) < Tf
    lo, hi = 1, 1 << (p - 2)
    if not ok(1):
        return 0
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid - 1
    return lo


def nlow_lanes(fmt, fn, n, per, rng):
    """Lanes (x, n) beside 1 at one n (|n| above 2^53 at fp64, so n_l is not
    zero): x = 1 + k ulp and 1 - k ulp (compound: x = +-k ulp), k up to the
    largest for which |n log2 x| is below T_f (none where that is 0: n =
    2^63 - 1 has no such lane at fp64), and their mirrors (x negated where n is
    odd, for pown)."""
    p = fmt.prec
    one = sf.one_bits(fmt)
    out = []
    for below in (False, True):
        kmax = _nlow_kmax(fmt, n, below)
        ks = sorted({1, 2, kmax, max(1, kmax // 2)}
                    | {rng.randint(1, max(1, kmax)) for _ in range(per)})
        for k in ks:
            if not 1 <= k <= kmax:
                continue
            if fn == "compound":
                x = _enc(fmt, Fraction(k, 2 ** (p - 1 + below))
                         * (-1 if below else 1))
            else:
                x = one - k if below else one + k
            out.append((x, n))
            if fn == "pown" and n % 2:
                out.append((x | fmt.sign_mask, n))         # the mirror
    return out


def region_n(fmt, fn, name, count, seed=1):
    """`count` lanes (x, n) of the region `name` for fn at fmt (the study's
    regions.py, ported; seed * 1000003 + width). nlow takes `count` over its
    four n; [] where the function has none of the region."""
    rng = random.Random(seed * 1000003 + fmt.width)
    p = fmt.prec
    lo_e, hi_e = fmt.emin - p + 1, fmt.emax
    Tf = ml._pow_t_reach(fmt) - 3
    one = sf.one_bits(fmt)
    out, tries = [], 0
    if name == "nlow":
        if fmt.name != "fp64" or fn == "rootn":
            return []
        out = []
        for n in NLOW_NS:
            out += nlow_lanes(fmt, fn, n, max(1, count // len(NLOW_NS)), rng)
        return out
    n_fixed = region_n_of(name, fmt)
    if name == "m1edge" and fn != "compound":
        return []
    while len(out) < count and tries < 50 * count + 100:
        tries += 1
        lane = None
        if name == "m1edge":
            n = rng.choice((-17, -3, -2, 2, 3, 17))
            kk = int(2 ** rng.uniform(0, p - 1))
            q = -(1 - Fraction(kk, 2 ** p))                  # 1 + q = kk 2^-p
            lane = (_enc(fmt, q), n)
        elif name.startswith("zone"):
            n = n_fixed
            lo = 0.5
            if fn != "rootn":
                lo = max(0.5, 2.0 ** (-Tf / abs(n)))
            X = _zone_x(rng, lo)
            if fn == "compound":
                lane = (_enc(fmt, X - 1), n)
            else:
                x = _enc(fmt, X)
                if rng.random() < 0.5 and (fn != "rootn" or n % 2):
                    x |= fmt.sign_mask
                lane = (x, n)
        else:
            n = n_fixed
            if fn == "compound":
                if rng.random() < 0.3:
                    x = _rand_mag(fmt, rng, -p - 4, -1) | fmt.sign_mask
                else:
                    x = _rand_mag(fmt, rng, lo_e, hi_e)
                q = value(fmt, x) + 1
                with mpmath.workprec(p + 64):
                    L = mpmath.log(_mp(q), 2)
                if abs(n * L) >= Tf:
                    continue
                lane = (x, n)
            else:
                if fn == "rootn":
                    x = _rand_mag(fmt, rng, lo_e, hi_e)
                else:
                    with mpmath.workprec(p + 64):
                        xv = mpmath.power(2, mpmath.mpf(rng.uniform(-Tf, Tf))
                                          / n)
                        x = _enc(fmt, ml._frac(xv))
                    if not (x & ~fmt.sign_mask) or \
                            (x & ~fmt.sign_mask) >= sf.inf_bits(fmt):
                        continue
                if rng.random() < 0.5 and (fn != "rootn" or n % 2):
                    x |= fmt.sign_mask
                lane = (x, n)
        if lane is not None and in_main_n(fn, fmt, lane):
            out.append(lane)
    return out


@functools.lru_cache(maxsize=None)
def region_n_cached(fmt, fn, name, count, seed=1):
    return tuple(region_n(fmt, fn, name, count, seed))


def _by_n(lanes):
    """{n: [lane]} in order."""
    out = {}
    for ln in lanes:
        out.setdefault(ln[1], []).append(ln)
    return out


def reach_n(fn, fmt, lanes, n=None):
    """(main-path lanes, lanes): a lane reaches the main path where in_main_n
    holds and the screens do not take it (t_h0 inside them): the build's probe.
    Lanes of one n only (`n`, else each lane's)."""
    c = 0
    for ln in lanes:
        k = ln[1] if n is None else n
        if not in_main_n(fn, fmt, ln):
            continue
        _r, _f, pr = build_n(fn, fmt, RNE, k).run((ln[0],), ("th0",))
        if not _screened(fmt, pr):
            c += 1
    return c, len(lanes)


def check_regions_n(fn, fmt, rnd, name, count=None, plant=None):
    """[finding], (lanes, marked, main-path lanes): regions, one region at its
    n (or its n's: nlow), every lane through the fragment of its n against
    transcend.py (0 wrong unmarked), the main-path lanes counted (the region
    that reaches none is NOT MEASURED, the caller says so)."""
    count = REGION_LANES[(fn, fmt.name)] // 10 if count is None else count
    lanes = region_n_cached(fmt, fn, name, count, 1)
    out, n_lanes, marked, main = [], 0, 0, 0
    for n, ls in _by_n(lanes).items():
        f = fragment_n(fn, fmt, rnd, n, plant)
        o, (nl, mk) = check_regions(f, {name: ls}, first=[], evaluator=EV_N)
        out += [s.replace("regions:", f"regions: n = {n}:", 1) for s in o]
        n_lanes += nl
        marked += mk
        main += reach_n(fn, fmt, ls, n)[0]
    return out, (n_lanes, marked, main)


# ---- the specials: the study's section 4, per n --------------------------------

def _special_xs(fmt):
    p = fmt.prec
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    z, mz = sf.zero_bits(fmt), sf.zero_bits(fmt, 1)
    inf, minf = sf.inf_bits(fmt), sf.inf_bits(fmt, 1)
    qn, sn = sf.qnan_bits(fmt), sf.snan_bits(fmt)
    mx, mn = sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)
    S = fmt.sign_mask

    def v(s, m, e):
        return _V(fmt, s, m, e)
    return [z, mz, inf, minf, qn, sn, one, mone, one + 1, one - 1, mone + 1,
            mone - 1, mn, mn | S, mx, mx | S, v(0, 3, 0), v(1, 3, 0),
            v(0, 1, -1), v(1, 1, -1), v(0, 1, -p - 3), v(1, 1, -p - 3)]


def special_rows_n(fn, fmt, n):
    """[(label, lanes)] of fn at n: the model's row (specials.py): x specials
    and neighbours of +-1, 0 and the range, at this n."""
    return [(f"{fn} n = {n}: x specials and neighbours of +-1, 0 and the "
             f"range", [(x, n) for x in _special_xs(fmt)])]


def _named_special_lanes(fn, fmt, n):
    """[(label, lane, (bits, flags))]: the study's named rows, answered by the
    rule itself (not by transcend.py): rootn(+-0, n) by n's parity and sign
    (2.6, MEASURED in 4), pown(-1, 2^63 - 1) = -1 and pown(-1, -2^63) = +1,
    compound(-1, n)'s +0 or +inf, compound(x < -1) invalid, compound(+inf)."""
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    z, mz = sf.zero_bits(fmt), sf.zero_bits(fmt, 1)
    inf, minf = sf.inf_bits(fmt), sf.inf_bits(fmt, 1)
    qn = sf.qnan_bits(fmt)
    DZ, INV = sf.FLAG_DIVZERO, sf.FLAG_INVALID
    out = []
    if fn == "rootn" and n not in (0, 1):
        for zero, neg in ((z, 0), (mz, 1)):
            odd = n % 2 != 0
            if n > 0:
                want = (mz if (odd and neg) else z, 0)
            else:
                want = (minf if (odd and neg) else inf, DZ)
            out.append((f"rootn({'-' if neg else '+'}0, {n})", (zero, n),
                        want))
    if fn == "pown" and n in (2 ** 63 - 1, -2 ** 63):
        out.append((f"pown(-1, {n})", (mone, n),
                    (mone if n % 2 else one, 0)))
    if fn == "compound" and n not in (0, 1):
        out.append((f"compound(-1, {n})", (mone, n),
                    (z, 0) if n > 0 else (inf, DZ)))
        out.append((f"compound(-2, {n})", (_enc(fmt, -2), n), (qn, INV)))
        out.append((f"compound(+inf, {n})", (inf, n),
                    (inf, 0) if n > 0 else (z, 0)))
        out.append((f"compound(-inf, {n})", (minf, n), (qn, INV)))
        out.append((f"compound(-0, {n})", (mz, n), (one, 0)))
    return out


def check_specials_n(fn, fmt, n, rnds=None, plant=None, marks=None):
    """[finding], lanes: specials, at n: every row of special_rows_n through
    the fragments at n under `rnds` (all five by default), unmarked equal to
    transcend.py in bits AND flag word, the marks of the row the model's
    (SPECIAL_MARKS_N: summed over the five attributes, compared where all five
    run), and the named rows (_named_special_lanes) answered as the rule says
    under every attribute run."""
    rnds = RND_MODES if rnds is None else rnds
    frags = {r: fragment_n(fn, fmt, r, n, plant) for r in rnds}
    rows = special_rows_n(fn, fmt, n)
    if marks is None:
        pinned = SPECIAL_MARKS_N.get((fn, fmt.name, n))
        marks = {rows[0][0]: None if pinned is None else sum(pinned)}
    out, cnt = check_specials(fmt, fn, frags, evaluator=EV_N, rows=rows,
                              marks={k: v for k, v in marks.items()
                                     if v is not None})
    for label, lane, want in _named_special_lanes(fn, fmt, n):
        for r, f in frags.items():
            cnt += 1
            got = ml.evaluate(f, (lane[0],))
            if got[1] & MARK or got != want:
                out.append(f"specials: {fn} {fmt.name} "
                           f"{sf.RND_NAMES[r]}: named row {label}: got "
                           f"({got[0]:#x}, {got[1]:#x}), want "
                           f"({want[0]:#x}, {want[1]:#x}) and unmarked")
    return [s.replace("specials:", f"specials: n = {n}:", 1) for s in out], cnt


def region_line_n(name, main, lanes):
    """One region's line: a region none of whose lanes reaches the main path
    is NOT MEASURED (its lane count printed), never a pass."""
    if main == 0:
        return f"{name}: NOT MEASURED ({lanes} lanes, none reaches the main path)"
    return f"{name}: measured ({main} of {lanes} lanes reach the main path)"


def region_summary_n(results):
    """(passed, not_measured, lines, RESULT line) over {name: (main, lanes,
    findings)}: the pass count is of the measured regions only, and the RESULT
    line says how many were not measured."""
    lines = [region_line_n(k, m, n) for k, (m, n, _f) in results.items()]
    nm = [k for k, (m, _n, _f) in results.items() if m == 0]
    bad = [k for k, (_m, _n, f) in results.items() if f]
    passed = len(results) - len(nm) - len(bad)
    res = (f"RESULT: {'ok' if not bad else 'FAIL'}: {passed} regions "
           f"measured and passing, {len(nm)} NOT MEASURED ({', '.join(nm) or 'none'}), "
           f"{len(bad)} failing")
    return passed, nm, lines, res


# ---- the structured lanes, per n -------------------------------------------------
#
# The expectations are check_structured's (decided, marked, nearest, midpoint,
# free). The exact cases are chosen by transcend.py's OWN rules, not by this
# file's idea of them: pown's and compound's by _pown_dyadic (M = 1 at any n,
# an odd M only while M^n fits p + 1 bits and n > 0), rootn's by _rootn_dyadic
# (M a perfect |n|-th power and |n| divides E; a negative n only where the root
# is 1), compound's operand 1 + x by _exact_one_plus, its dominant operand by
# transcend.compound's threshold vexp(x) >= p + 2 + bits(|n|).

def _odd_candidates(fmt, n):
    """Odd M >= 3 near the edges of _pown_dyadic's fit (M^n of p bits and of
    p + 1 bits), and a few small ones."""
    p = fmt.prec
    out = [3, 5, 7, 9, 15]
    if 2 <= n <= p + 1:        # past it _pown_dyadic answers None for every odd M > 1
        for bits in (p, p + 1):
            r = ml._iroot(1 << bits, n)
            for d in (-4, -3, -2, -1, 0, 1, 2, 3):
                m = r + d
                if m >= 3 and m % 2 == 1:
                    out.append(m)
    return sorted({m for m in out if m.bit_length() <= p})


def _pown_classes(fmt, n):
    """(exact, mid): odd M >= 3 for which transcend._pown_dyadic(M, 0, n) is
    an exact dyadic of at most p bits (exact: a representable result) and of
    p + 1 bits (a midpoint of the format)."""
    p = fmt.prec
    exact, mid = [], []
    for m in _odd_candidates(fmt, n):
        res = transcend._pown_dyadic(fmt, m, 0, n)
        if res is None:
            continue
        bl = res[0].bit_length()
        (exact if bl <= p else mid if bl == p + 1 else []).append(m)
    return exact, mid


def _signs(fmt, x, n, both):
    """x, and -x where n is odd (the sign of pown's and rootn's result) or
    `both`."""
    return [x, x | fmt.sign_mask] if (both or n % 2) else [x]


def _structured_core_n(fn, fmt, n):
    p = fmt.prec
    rows = []
    emin, emax = fmt.emin, fmt.emax

    def x2(E):
        return _V(fmt, 0, 1, E)
    if fn == "pown":
        decided = []
        Es = [1, 2, -1, -3, 5, -7, 100]
        for t in (emin - p, emin - p + 1, emin, emax, emax + 1, emax - 1):
            if t % n == 0:
                Es.append(t // n)
        for E in Es:
            if emin - p + 1 <= E <= emax:
                decided += [(x, n) for x in _signs(fmt, x2(E), n, False)]
        rows.append(("exact powers of two (x = 2^E, both signs where n is "
                     "odd, integer t, overflow and the tie included where "
                     "they exist)", decided, "decided"))
        exact, mid = _pown_classes(fmt, n)
        for e in (0, -3):
            ex = [(_V(fmt, 0, m, e), n) for m in exact]
            ex += [(_V(fmt, 1, m, e), n) for m in exact if n % 2]
            rows.append((f"pown exact cases that must mark (odd M^n of at "
                         f"most p bits, transcend._pown_dyadic), 2^{e}", ex,
                         "marked"))
        rows.append(("pown midpoint cases (M^n of p + 1 bits)",
                     [(_V(fmt, 0, m, 0), n) for m in mid], "midpoint"))
        neigh = [(x + d, n) for x, _n in
                 [(_V(fmt, 0, m, 0), n) for m in exact[:3]] for d in (1, -1)]
        # (3 +- ulp)^2 and the like are a midpoint to within the bound: free
        rows.append(("their neighbours one ulp of x away", neigh, "free"))
    elif fn == "rootn":
        decided = []
        k = abs(n)
        for F in (1, -1, 2, 7, -9, 40):
            E = F * n
            if emin - p + 1 <= E <= emax:
                decided += [(x, n) for x in _signs(fmt, x2(E), n, False)]
        rows.append(("exact powers of two (x = 2^E, |n| divides E, both signs "
                     "where n is odd)", decided, "decided"))
        marked, neigh = [], []
        for r in (3, 5, 7, 9, 11, 13, 15, 17):
            if n < 0 or n > p:           # r^n of at most p bits needs n <= p
                break
            m = r ** n
            if m.bit_length() > p:
                break
            for F in (0, 1, -2):
                x = _V(fmt, 0, m, F * n)
                u = sf.unpack(fmt, x)
                if transcend._rootn_dyadic(fmt, u, n) is None:
                    continue
                marked += [(y, n) for y in _signs(fmt, x, n, False)]
                neigh += [(x + 1, n), (x - 1, n)]
        rows.append(("rootn exact cases that must mark (M a perfect |n|-th "
                     "power, transcend._rootn_dyadic)", marked, "marked"))
        rows.append(("their neighbours one ulp of x away", neigh, "nearest"))
    else:                                              # compound
        decided = []
        for E in (1, 2, 3, 5, -1, -2, -3, -5):
            decided.append((_enc(fmt, Fraction(2) ** E - 1), n))
        rows.append(("1 + x a power of two (x = 2^E - 1, E of either sign)",
                     decided, "decided"))
        exact, mid = _pown_classes(fmt, n)
        rows.append(("compound exact cases that must mark (1 + x = M odd, M^n "
                     "of at most p bits: _exact_one_plus, _pown_dyadic)",
                     [(_enc(fmt, m - 1), n) for m in exact], "marked"))
        rows.append(("compound midpoint cases (M^n of p + 1 bits)",
                     [(_enc(fmt, m - 1), n) for m in mid], "midpoint"))
        thr = p + 2 + abs(n).bit_length()
        dom = []
        for V in (thr, thr - 1):
            for m in (3, 5):
                if V + 2 <= emax:
                    dom.append((_V(fmt, 0, m, V - 1), n))
        rows.append((f"compound's dominant operand at vexp(x) = p + 2 + "
                     f"bits(|n|) = {thr} and one below (transcend.compound)",
                     dom, "free"))
    if fn == "pown" and n > 0 and n % 2:
        # a negative result rounding to zero on the subnormal grid (the plant
        # zero_sign_lost): x = -RN(2^((emin - p - 0.1) / n)), t = emin - p - 0.1
        with mpmath.workprec(p + 64):
            xv = mpmath.power(2, (mpmath.mpf(emin - p) - mpmath.mpf(1) / 10)
                              / n)
        rows.append(("a negative result rounding to zero on the subnormal "
                     "grid (plant zero_sign_lost)",
                     [(_enc(fmt, ml._frac(xv)) | fmt.sign_mask, n)], "free"))
    # the plants' named lanes (the study's plants.py): compound(RN(0.1), 3) is
    # two ulps off where 1 + x is rounded before the logarithm; rootn(-0, n
    # even) is +0 (squareRoot(-0) is -0: the standard's note)
    if fn == "compound":
        rows.append(("plant compound_onep_rounded: x = RN(0.1), 1 + x not "
                     "representable", [(_enc(fmt, Fraction(1, 10)), n)],
                     "free"))
    if fn == "rootn" and n % 2 == 0:
        rows.append(("plant rootn_m0_neg: rootn(-0, n even) is +0",
                     [(sf.zero_bits(fmt, 1), n)], "decided"))
    return rows


def _beside_one_n(fn, fmt, n):
    """(below, above): lanes (x, n) whose t = Y log2|X| is under and over the
    gate 2^-(p+3) (0.3 to 0.97 and 1.03 to 4 times it), found by scan: pown
    has none (|t| >= |n| ulp / ln 2), rootn takes x = 1 +- k ulp at a large |n|,
    compound x = +-m 2^-j."""
    p = fmt.prec
    gate = Fraction(1, 2 ** (p + 3))
    cands = []
    one = sf.one_bits(fmt)
    if fn == "compound":
        for j in range(p - 2, 2 * p + 10, 3):
            for m in (1, 3, 5):
                for sg in (1, -1):
                    cands.append(_enc(fmt, sg * Fraction(m, 2 ** j)))
    else:
        for k in (1, 2, 3, 5, 9, 17, 33):
            cands += [one + k, one - k]
    below, above = [], []
    for x in cands:
        X = value(fmt, x) + (1 if fn == "compound" else 0)
        if X <= 0:
            continue
        with mpmath.workprec(p + 64):
            L = mpmath.log(_mp(X), 2)
            t = abs(L * n) if fn != "rootn" else abs(L / n)
            r = float(t / _mp(gate))
        if 0.3 <= r <= 0.97 and len(below) < 3:
            below.append((x, n))
        elif 1.03 <= r <= 4 and len(above) < 3:
            above.append((x, n))
    return below, above


def structured_rows_n(fn, fmt, n):
    """[(label, lanes, expectation)] of fn at n: _structured_core_n's, the
    lanes beside 1 under and over the gate (where they exist), and the small
    fragments' (n = 0, 1)."""
    p = fmt.prec
    mx, mn = sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)
    one = sf.one_bits(fmt)
    if n in (0, 1):
        xs = _special_xs(fmt) + [mx, mn, one + 1, one - 1,
                                 _V(fmt, 0, 1, -p - 1), _V(fmt, 1, 1, -p - 1),
                                 _enc(fmt, -2), _enc(fmt, Fraction(-3, 2)),
                                 _enc(fmt, Fraction(-1, 2))]
        return [(f"the small fragment (n = {n}): specials, +-max, +-min, "
                 f"neighbours of 1 and -1, x just inside +-2^-p, x < -1",
                 [(x, n) for x in xs], "decided")]
    rows = list(_structured_core_n(fn, fmt, n))
    below, above = _beside_one_n(fn, fmt, n)
    if below:
        rows.append(("beside 1, t below 2^-(p+3) (the gate, both signs of x "
                     "where they exist)", below, "decided"))
    if above:
        rows.append(("beside 1, t above the gate", above, "free"))
    return [r for r in rows if r[1]]


def check_structured_n(fn, fmt, rnd, n, plant=None):
    """[finding], lanes: structured, at n."""
    f = fragment_n(fn, fmt, rnd, n, plant)
    out, cnt = check_structured(f, evaluator=EV_N,
                                rows=structured_rows_n(fn, fmt, n))
    return [s.replace("structured:", f"structured: n = {n}:", 1)
            for s in out], cnt


# ---- seq, per n --------------------------------------------------------------------

def seq_lanes_n(fn, fmt, n):
    """The seq check's lanes at n: the pool's lanes of n (every POOL_STEP-th),
    every structured lane, and the loud ones (the largest finite x, a signalling
    NaN, the least subnormal, an infinity)."""
    out = list(pool_n(fn, fmt, n))
    for _l, lanes, _e in structured_rows_n(fn, fmt, n):
        out += lanes
    out += [(sf.max_normal_bits(fmt), n), (sf.snan_bits(fmt), n),
            (sf.min_subnormal_bits(fmt), n), (sf.inf_bits(fmt), n)]
    return tuple(dict.fromkeys(out))


def check_seq_n(fn, fmt, rnd, n, plant=None, **kw):
    """[finding], lanes: seq, at n (check_seq on seq_lanes_n and the n's
    structured rows)."""
    f = fragment_n(fn, fmt, rnd, n, plant)
    out, xs = check_seq(f, xs=seq_lanes_n(fn, fmt, n),
                        rows=structured_rows_n(fn, fmt, n), **kw)
    return [s.replace("seq:", f"seq: n = {n}:", 1) for s in out], xs


# ---- the bound, per n ----------------------------------------------------------------

# a region in which no lane reaches the main path is NOT MEASURED, not passed:
# int63 at fp64 (the study's 3.3), and any other a run finds to have none
BOUND_NO_MAIN.add("int63")


def bound_regions_n(fn, fmt, count=8, seed=11):
    """{region: lanes}: `count` points of each of the function's regions (the
    bound's seed 11, the study's regions' own is 1)."""
    return {r: region_n_cached(fmt, fn, r, count, seed)
            for r in region_names_n(fn, fmt)}


def check_bound_n(fn, fmt, rnd, name, count=8, plant=None, lanes=None):
    """[finding], (worst, main-path lanes, lanes): bound, over one region's
    lanes at each of its n (check_bound on the build of that n). The worst is
    the largest found over THESE lanes; the zone's and int1000's direct errors
    are a sample (the budget at 10,000 lanes is parcel M3G3's: `pow-budget
    --set box`)."""
    lanes = region_n_cached(fmt, fn, name, count, 11) if lanes is None \
        else lanes
    out, worst, main, total = [], -1e9, 0, 0
    for n, ls in _by_n(lanes).items():
        b = build_n(fn, fmt, rnd, n, plant)
        o, (w, m, t) = check_bound(b, ls, f"{name} n = {n}")
        out += o
        worst, main, total = max(worst, w), main + m, total + t
    return out, (worst, main, total)


# ---- the shape, per n ----------------------------------------------------------------

def _phases_digest(b):
    c = collections.Counter(b.phase_of[i] for i in b.live_indices())
    return hashlib.sha256(repr(sorted(c.items())).encode()).hexdigest()[:16]


def check_shape_n(fn, fmt, n, rnds=None, plant=None, pins=None, eft=None,
                  fragments=None, builds=None):
    """[finding]: shape, at n. Per attribute the instructions, bank words and
    live values, the dag digest of the scheduled fragment and the digest of
    the instructions by phase pinned to the model's (PINS_N); the Fast2Sum and
    TwoSum counts (EFT_N); the flag word's values (FLAG_WORDS_N); no MIN or MAX;
    the scheduled fragment the design's reordered; its own invariants under
    POW_LIVE_CAP. `pins`, `eft`, `fragments` and `builds` stand for the pinned
    tables and the objects, for the tests that doctor one leg."""
    pins = PINS_N if pins is None else pins
    eft_t = EFT_N if eft is None else eft
    rnds = check_attrs(fmt, n) if rnds is None else rnds
    out = []
    for rnd in rnds:
        b = (builds or {}).get(rnd) or build_n(fn, fmt, rnd, n, plant)
        f = (fragments or {}).get(rnd) or b.fragment()
        key = (fn, fmt.name, sf.RND_NAMES[rnd], n)
        where = f"shape: n = {n}: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
        want = pins[key]
        got = (len(f), len(f.words), f.live_max(), ml.dag_digest(f)[:32],
               _phases_digest(b))
        names = ("instructions", "bank words", "values live",
                 "dag digest", "instructions-by-phase digest")
        for nm, g, w in zip(names, got, want):
            if g != w:
                out.append(f"{where}: {nm} {g}, pinned {w}")
        e = (b.meta["fast_two_sum"], b.meta["two_sum"])
        if e != tuple(eft_t[(fn, fmt.name, n)]):
            out.append(f"{where}: {e[0]} Fast2Sums and {e[1]} TwoSums, the "
                       f"model's {eft_t[(fn, fmt.name, n)]}")
        fw = routines.flag_words(f)
        wantfw = FLAG_WORDS_N[(fn, f"n{n}" if n in (0, 1) else
                               ("neg" if n < 0 else "pos"))]
        if fw != wantfw:
            out.append(f"{where}: the flag word takes "
                       f"{sorted(hex(w) for w in fw or ())}, pinned "
                       f"{sorted(hex(w) for w in wantfw)}")
        counts = f.counts()
        if counts.get("min", 0) or counts.get("max", 0):
            out.append(f"{where}: MIN or MAX instructions: {counts}")
        out += [f"shape: n = {n}: {s}" for s in H.check_reorder(b, f)]
        out += [f"{where}: invariants: {s}"
                for s in ml.invariants(f, live_cap=ml.POW_LIVE_CAP[fn][
                    fmt.name])]
    return out


def check_caps_n(fn, fmt, ns=None, plant=None, caps=None, fragments=None):
    """[finding]: shape. POW_LIVE_CAP's row of fn at fmt is the measured
    maximum over the n list and its attributes, the fragment of that maximum
    holds it and fails, by name, a cap one under. `caps` stands for the table,
    `fragments` {(n, rnd): Fragment} for the objects."""
    caps = ml.POW_LIVE_CAP if caps is None else caps
    frags = fragments or {(n, rnd): fragment_n(fn, fmt, rnd, n, plant)
                          for n in (check_ns(fn, fmt) if ns is None else ns)
                          for rnd in check_attrs(fmt, n)}
    lives = {k: f.live_max() for k, f in frags.items()}
    top = max(lives.values())
    cap = caps[fn][fmt.name]
    out = []
    if cap != top:
        out.append(f"shape: {fn} {fmt.name}: the cap is {cap}, the most "
                   f"values live over {len(frags)} fragments is {top}")
    worst = frags[max(lives, key=lives.get)]
    if ml.invariants(worst, live_cap=top) != []:
        out.append(f"shape: {fn} {fmt.name}: the maximal fragment fails its "
                   f"own cap {top}")
    under = ml.invariants(worst, live_cap=top - 1)
    if under != [f"{top} values live at once, past {top - 1}"]:
        out.append(f"shape: {fn} {fmt.name}: a cap one under ({top - 1}) does "
                   f"not fail by name: {under}")
    return out


# ---- core: the double-word Y and the Fraction ybound ---------------------------------

def check_core_n(fn, fmt, rnd=RNE, plant=None, lanes=None, builder=None):
    """[finding], (worst, lanes, n_l signs): core, at fp64 for pown and
    compound. (1) The double-word Y path on real lanes: the nlow region's
    lanes (n_l of both signs) through the build of their n, |V - f| / Bv under
    1 by mpmath (bound_log2), a finding where one sign of n_l is missing among
    the main-path lanes. (2) The Fraction ybound, on lanes of each function at
    n = 3 and at fp64's n_l lanes: the build's own Bv equal to the exact bound
    |V| (2^-(p+G) + |t_h| B1 + |Y_h k| B2) rounded upward (_check_ybound's
    rule), where B2 is not 0 (fp64) and the term is absent where it is 0. That
    leg is a WINDOW, need <= Bv <= need (1 + 2^-(p-3)): a YB2 word one ulp off
    stays inside it and is not seen (the constants' check holds YB2 to one
    ulp); a doubled one is. `builder(fn, fmt, rnd, n, plant)` stands for
    build_n, for the test that doctors a word."""
    out = []
    p, G = fmt.prec, ml.GUARD[fmt.name]
    P = ml.plan_pow(fmt, G)
    worst, n_main, signs = -1e9, 0, set()
    if fn in ("pown", "compound") and fmt.name == "fp64":
        lanes = region_n_cached(fmt, fn, "nlow", 40, 5) if lanes is None \
            else lanes
        for n, ls in _by_n(lanes).items():
            b = (builder or build_n)(fn, fmt, rnd, n, plant)
            hi, lo = ml._pow_int_words(fmt, n)
            for ln in ls:
                _r, _f, pr = b.run((ln[0],), ("th0",))
                if not in_main_n(fn, fmt, ln) or _screened(fmt, pr):
                    continue
                r = bound_log2(b, ln)
                n_main += 1
                signs.add(value(fmt, lo) < 0 if lo is not None else None)
                if r is not None:
                    worst = max(worst, r)
                    if r >= 0:
                        out.append(f"core: {fn} {fmt.name} n = {n}: past the "
                                   f"bound at {_hexes([ln])}: 2^{r:+.2f} Bv")
        if signs != {True, False}:
            out.append(f"core: {fn} {fmt.name}: n_l has "
                       f"{'one sign' if len(signs) == 1 else 'no lane'} "
                       f"among the {n_main} main-path lanes")
    # the Fraction ybound, by the fragments' own words
    if P.B2:
        bad = tot = 0
        for n in (3, -3, 2 ** 53 + 1):
            if fn == "rootn" and n == 0:
                continue
            b = (builder or build_n)(fn, fmt, rnd, n, plant)
            yb = Fraction(1, abs(n)) if fn == "rootn" else Fraction(abs(n))
            for ln in region_n_cached(fmt, fn, "int", 12, 7):
                ln = (ln[0], n)
                if not in_main_n(fn, fmt, ln):
                    continue
                _r, _f, pr = b.run((ln[0],), ("Vh", "th", "Bv", "kf", "th0"))
                if _screened(fmt, pr):
                    continue
                tot += 1
                need = abs(value(fmt, pr["Vh"])) * (
                    Fraction(1, 2 ** (p + G))
                    + abs(value(fmt, pr["th"])) * P.B1
                    + yb * abs(value(fmt, pr["kf"])) * P.B2)
                got = value(fmt, pr["Bv"])
                if not need <= got <= need * (1 + Fraction(1, 2 ** (p - 3))):
                    bad += 1
        if bad:
            out.append(f"core: {fn} {fmt.name}: the build's Bv is not the "
                       f"exact bound |V| (2^-(p+G) + |t_h| B1 + |Y k| B2), "
                       f"upward rounded, on {bad} of {tot} lanes")
    return out, (worst, n_main, sorted(s for s in signs if s is not None))


# ---- the constants ----------------------------------------------------------------------

def check_constants_n(**kw):
    """[finding], lines: constants. mathlib.check_pow_n_constants() in
    process, at POW_FORMATS unless `formats` is given."""
    kw.setdefault("formats", FORMATS)
    lines, findings = ml.check_pow_n_constants(**kw)
    return [f"constants: {s}" for s in findings], lines


def check_constants_n_cli():
    """[finding], output: constants. `python -m cft_golden.mathlib --check
    --only pow-n` in a process of its own, exit 0 and its last line ending
    `0 differences`, listing every routine and format."""
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--check", "--only", "pow-n"], capture_output=True,
                       text=True, cwd=ROOT / "python")
    out = r.stdout.strip().splitlines()
    findings = []
    if r.returncode != 0:
        findings.append(f"constants: --check --only pow-n exited "
                        f"{r.returncode}")
    want = (f"mathlib --check (pow, integer operand): "
            f"{len(ml._POW_N_BUILDERS)} routines, {len(ml.POW_FORMATS)} "
            f"formats, 0 differences")
    if not out or out[-1] != want:
        findings.append(f"constants: the last line is "
                        f"{out[-1] if out else r.stderr[-200:]!r}, not "
                        f"{want!r}")
    n = sum(1 for ln in out if ln.split(" ")[0] in ml._POW_N_BUILDERS)
    if n != len(ml._POW_N_BUILDERS) * len(ml.POW_FORMATS):
        findings.append(f"constants: {n} routine lines, "
                        f"{len(ml._POW_N_BUILDERS) * len(ml.POW_FORMATS)} "
                        f"wanted")
    return findings, out


# ---- the plants, per n ------------------------------------------------------------------
#
# Every plant of POW_PLANTS acts on the build it reaches and is refused by name
# ("does not apply") where it does not: PLANT_N says, for each, which (function,
# n) it is shown at; the plants of pow's front (pow_zero_nan, pow_one_nan,
# sign_even, integrality_wide, sign_odd_lost, y_one_loud) and powr's are not
# reached by any of the three, and the plants of the budget are parcel M3G3's
# (_POW_BUDGET_PLANTS).

POW_FRONT_ONLY = {"pow_zero_nan", "pow_one_nan", "sign_even",
                  "integrality_wide", "sign_odd_lost", "y_one_loud",
                  "powr_neg_ok", "powr_zero_zero"}
# plant: [(fn, n)] the cases it is shown red at (fp64)
PLANT_N = {
    "rootn_m0_neg": [("rootn", 2)],
    "compound_onep_rounded": [("compound", 3)],
    "n_low_dropped": [("pown", 2 ** 53 + 1), ("compound", 2 ** 53 + 1)],
    "n_word_ulp": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "n_row_loud": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "exact_unmarked": [("pown", 2), ("compound", 2), ("rootn", 2)],
    "exact_rule_off": [("pown", 2), ("rootn", 2), ("compound", 2)],
    "exact_rule_no_tl": [("pown", 3), ("compound", 3)],
    "midpoint_unmarked": [("pown", 2)],
    "near_one_gate_off": [("compound", 3), ("rootn", 1000)],
    "side_rule_off": [("compound", 3), ("rootn", 1000)],
    "screen_low": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "mark_silenced": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "bound_loose": [("pown", 2), ("rootn", 3), ("compound", 3)],
    "zero_sign_lost": [("pown", 3)],
    "log_table_entry": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "il2h_ulp": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "screen_ulp": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "two_sum_all": [("pown", 3), ("rootn", 3), ("compound", 3)],
    "log_short": [("pown", 3), ("rootn", 3), ("compound", 3)],
}


def _reaches_n(fn, fmt, rnd, n, plant):
    try:
        build_n(fn, fmt, rnd, n, plant)
    except ValueError as e:
        if "does not apply" not in str(e):
            raise
        return False
    return True


def red_checks_n(plant, fn, n, fmt=FP64, rnds=(RNE,), bound_n=8,
                 region_n_=6):
    """{check: [findings]} for the checks RED on `plant` (None: the control) at
    (fn, n) at `fmt`: pools (the pool's lanes of n, every POOL_STEP-th), seq,
    regions (the n's own region lanes), structured and specials at n under all
    five attributes where they reach, bound over the n's int region (bound_n
    points), shape under all five and core (fp64) and constants (rne). A check
    a plant cannot reach is green there; ValueError where the plant does not
    apply at (fn, n) under any attribute."""
    reach = [r for r in RND_MODES if _reaches_n(fn, fmt, r, n, plant)]
    if not reach:
        raise ValueError(f"plant {plant!r} does not apply to {fn} at "
                         f"{fmt.name}, n = {n} under any attribute")
    rnds = tuple(r for r in rnds if r in reach) or (reach[0],)
    red = {}

    def add(name, found):
        if found:
            red.setdefault(name, []).extend(found)
    for rnd in rnds:
        add("pools", check_pools_n(fn, fmt, rnd, n, plant)[0])
    add("seq", check_seq_n(fn, fmt, rnds[0], n, plant)[0])
    huge = fmt.name == "fp64" and abs(n) > 2 ** 53 and fn != "rootn"
    if huge:           # x beside 1: the only lanes |n log2 x| keeps in range
        lanes = tuple(nlow_lanes(fmt, fn, n, region_n_,
                                 random.Random(1))) or ()
    else:
        lanes = tuple((x, n) for x, _n in region_n(fmt, fn, "int", region_n_,
                                                    1))
    for rnd in (RNE, RTZ, RUP):
        if rnd in reach:
            f = fragment_n(fn, fmt, rnd, n, plant)
            add("regions", check_regions(f, {"int": list(lanes)}, first=[],
                                         evaluator=EV_N)[0])
    if huge:           # the nlow region too: n_l of both signs (its four n)
        add("regions", check_regions_n(fn, fmt, RNE, "nlow", 40, plant)[0])
    for rnd in reach:
        add("structured", check_structured_n(fn, fmt, rnd, n, plant)[0])
    add("specials", check_specials_n(fn, fmt, n, rnds, plant)[0])
    b = build_n(fn, fmt, RNE, n, plant)
    if huge:
        pts = tuple(nlow_lanes(fmt, fn, n, bound_n, random.Random(11)))
    else:
        pts = tuple((x, n) for x, _n in region_n(fmt, fn, "int", bound_n,
                                                  11))
    if pts:
        add("bound", check_bound(b, list(pts), f"int n = {n}")[0])
    pinned = tuple(r for r in reach if r in check_attrs(fmt, n))
    add("shape", check_shape_n(fn, fmt, n, pinned, plant))
    if fmt.name == "fp64" and fn in ("pown", "compound") \
            and abs(n) > 2 ** 53 and plant is not None:
        add("core", check_core_n(fn, fmt, RNE, plant)[0])
    elif fmt.name == "fp64" and plant is None:
        add("core", check_core_n(fn, fmt, RNE, plant)[0])
    add("constants", check_constants_n(
        builder=lambda name, f_, r_, n_: build_n(name, f_, r_, n_, plant),
        formats=(fmt,), attrs=(RNE,), names=(fn,), ns=(n,))[0])
    return red

# ---- the pinned data: the MODEL's, for the n list ----------------------------
#
# generated by the parcel's scratch script from the MODEL (docs/studies/m3/m3pow.py build_any at
# the base), once: shape (instructions, bank words, live, dag digest, instructions-by-phase digest)
PINS_N = {('compound', 'fp128', 'rdn', -9223372036854775808): (462, 155, 20, 'dfed1224adf3386e0f6bd34632793689',
                                                      '6e7f72726998556a'),
 ('compound', 'fp128', 'rdn', -3): (462, 155, 20, '44358e97507b10a207b862dd9b90e50a', '6e7f72726998556a'),
 ('compound', 'fp128', 'rdn', 0): (9, 8, 3, '425d2afda22e322f80785dc953cf9f09', '87852c9d56d2b291'),
 ('compound', 'fp128', 'rdn', 1): (26, 10, 7, 'f8a5c3013a71d0affb26f97e42f823e2', '8b1e2965175a1b97'),
 ('compound', 'fp128', 'rdn', 3): (463, 155, 20, '29d9b9e51a90f8329b787ea83b9b8b94', '1a918aaa97faa307'),
 ('compound', 'fp128', 'rmm', -9223372036854775808): (469, 153, 22, 'cad39db86321afaf40eac637bea54e14',
                                                      '8b6edc94bc5eda3d'),
 ('compound', 'fp128', 'rmm', -3): (469, 153, 22, '6eb373cf2a2de2687489b1082e9746c0', '8b6edc94bc5eda3d'),
 ('compound', 'fp128', 'rmm', 0): (9, 8, 3, '425d2afda22e322f80785dc953cf9f09', '87852c9d56d2b291'),
 ('compound', 'fp128', 'rmm', 1): (26, 10, 7, 'd948cc6cd6d146bf0b09a7ec07bf9079', '8b1e2965175a1b97'),
 ('compound', 'fp128', 'rmm', 3): (469, 153, 22, 'a2a7f08dba9dc328d4cdd21d18003011', '8b6edc94bc5eda3d'),
 ('compound', 'fp128', 'rne', -9223372036854775808): (469, 153, 22, 'eb5503d1a82424d2b81024a66f6b2299',
                                                      '8b6edc94bc5eda3d'),
 ('compound', 'fp128', 'rne', -3): (469, 153, 22, 'd4b59991369daed2ff176ff66b892379', '8b6edc94bc5eda3d'),
 ('compound', 'fp128', 'rne', 0): (9, 8, 3, '425d2afda22e322f80785dc953cf9f09', '87852c9d56d2b291'),
 ('compound', 'fp128', 'rne', 1): (25, 10, 7, '999dd016065188f81579731dd1ac8b94', '6bb06f4f804cd716'),
 ('compound', 'fp128', 'rne', 3): (469, 153, 22, '0aa987ee20aaab40e7d6fa74aa6d666a', '8b6edc94bc5eda3d'),
 ('compound', 'fp128', 'rne', 17): (469, 153, 22, '57268d1a1d4366609750bcd7c48943d9', '8b6edc94bc5eda3d'),
 ('compound', 'fp128', 'rtz', -9223372036854775808): (462, 155, 20, '21340a0e96dd7022c4f4ea39aeb6ce7a',
                                                      '6e7f72726998556a'),
 ('compound', 'fp128', 'rtz', -3): (462, 155, 20, '6044d4fb53e29b472056fb5a5eede6ae', '6e7f72726998556a'),
 ('compound', 'fp128', 'rtz', 0): (9, 8, 3, '425d2afda22e322f80785dc953cf9f09', '87852c9d56d2b291'),
 ('compound', 'fp128', 'rtz', 1): (26, 10, 7, 'ff14e2dcf435f40c6c97a354b030b299', '8b1e2965175a1b97'),
 ('compound', 'fp128', 'rtz', 3): (463, 155, 20, '3de961adca1ff2380e455a8dd5c29493', '1a918aaa97faa307'),
 ('compound', 'fp128', 'rtz', 17): (463, 155, 20, '527eb8814bf42b201cb28d7587587b2b', '1a918aaa97faa307'),
 ('compound', 'fp128', 'rup', -9223372036854775808): (462, 154, 20, '94dc5647d2835717cc7c5e55db94c262',
                                                      '6e7f72726998556a'),
 ('compound', 'fp128', 'rup', -3): (462, 154, 20, '957c430c64e810d9be73d526db62e38b', '6e7f72726998556a'),
 ('compound', 'fp128', 'rup', 0): (9, 8, 3, '425d2afda22e322f80785dc953cf9f09', '87852c9d56d2b291'),
 ('compound', 'fp128', 'rup', 1): (26, 10, 7, '805920292627e9e6a10782d5c6bd43bb', '8b1e2965175a1b97'),
 ('compound', 'fp128', 'rup', 3): (463, 154, 20, 'da42e797fbac6d2c4772df1594eb53d4', '1a918aaa97faa307'),
 ('compound', 'fp256', 'rdn', -9223372036854775808): (513, 200, 20, 'f721096e631596e7b6e692c8ed21b323',
                                                      'e46a3ec1d92bddb1'),
 ('compound', 'fp256', 'rdn', -3): (513, 200, 20, '2a94c9912a69e489c2aa99b9f1043ce7', 'e46a3ec1d92bddb1'),
 ('compound', 'fp256', 'rdn', 0): (9, 8, 3, 'e9660be42f4f7f1785a5ad7a65e05819', '87852c9d56d2b291'),
 ('compound', 'fp256', 'rdn', 1): (26, 10, 7, '2bb18c0a52d96a26799cc1506f82b16c', '8b1e2965175a1b97'),
 ('compound', 'fp256', 'rdn', 3): (514, 200, 20, '535a7ff56c1acec4b98d28f29ee5f3cc', 'c22cc9a03504c48f'),
 ('compound', 'fp256', 'rmm', -9223372036854775808): (520, 198, 22, '0dd5abe266775784706b4df1ca1a4179',
                                                      'ad5f92e987862d1b'),
 ('compound', 'fp256', 'rmm', -3): (520, 198, 22, '4653eebcb4f4562a9ac091202297ab2e', 'ad5f92e987862d1b'),
 ('compound', 'fp256', 'rmm', 0): (9, 8, 3, 'e9660be42f4f7f1785a5ad7a65e05819', '87852c9d56d2b291'),
 ('compound', 'fp256', 'rmm', 1): (26, 10, 7, '8564949636426691b343a8b9dae14e45', '8b1e2965175a1b97'),
 ('compound', 'fp256', 'rmm', 3): (520, 198, 22, '410a7dfd21f06cf30ddbd181d620f9e3', 'ad5f92e987862d1b'),
 ('compound', 'fp256', 'rne', -9223372036854775808): (520, 198, 22, '725084c0ce0d0a439d2e70571f524622',
                                                      'ad5f92e987862d1b'),
 ('compound', 'fp256', 'rne', -3): (520, 198, 22, '2632852ef3bb320efaa4864a7849dfc0', 'ad5f92e987862d1b'),
 ('compound', 'fp256', 'rne', 0): (9, 8, 3, 'e9660be42f4f7f1785a5ad7a65e05819', '87852c9d56d2b291'),
 ('compound', 'fp256', 'rne', 1): (25, 10, 7, '7d250d1bde78ef5656294c8768e5c08b', '6bb06f4f804cd716'),
 ('compound', 'fp256', 'rne', 3): (520, 198, 22, 'a6edfc4423fb2eab99bddf3e2450648c', 'ad5f92e987862d1b'),
 ('compound', 'fp256', 'rne', 17): (520, 198, 22, 'fb5d37bfda3de5da674c7d757c78ce03', 'ad5f92e987862d1b'),
 ('compound', 'fp256', 'rtz', -9223372036854775808): (513, 200, 20, '364a375de5861ba34ed5a1d228c6b3fc',
                                                      'e46a3ec1d92bddb1'),
 ('compound', 'fp256', 'rtz', -3): (513, 200, 20, 'ed1b51d43908243747c74c35463f87f0', 'e46a3ec1d92bddb1'),
 ('compound', 'fp256', 'rtz', 0): (9, 8, 3, 'e9660be42f4f7f1785a5ad7a65e05819', '87852c9d56d2b291'),
 ('compound', 'fp256', 'rtz', 1): (26, 10, 7, '270a06880955b4102a0105347d18a223', '8b1e2965175a1b97'),
 ('compound', 'fp256', 'rtz', 3): (514, 200, 20, 'cbcff15870fd6d85892be89f88c924ad', 'c22cc9a03504c48f'),
 ('compound', 'fp256', 'rtz', 17): (514, 200, 20, '9ac4e4ac62476ef15bc5878725343c97', 'c22cc9a03504c48f'),
 ('compound', 'fp256', 'rup', -9223372036854775808): (513, 199, 20, 'f9c47d2a0964b2270ad172bfa6c9897b',
                                                      'e46a3ec1d92bddb1'),
 ('compound', 'fp256', 'rup', -3): (513, 199, 20, 'cde7b5e816077d9955f6887531e7ff54', 'e46a3ec1d92bddb1'),
 ('compound', 'fp256', 'rup', 0): (9, 8, 3, 'e9660be42f4f7f1785a5ad7a65e05819', '87852c9d56d2b291'),
 ('compound', 'fp256', 'rup', 1): (26, 10, 7, '5f76ed1e6e05ab6571b12b01ad2f305f', '8b1e2965175a1b97'),
 ('compound', 'fp256', 'rup', 3): (514, 199, 20, 'ef7141df32e998e703139f896f37dbfe', 'c22cc9a03504c48f'),
 ('compound', 'fp64', 'rdn', -3): (403, 127, 21, '7466d2b41ab44cffcf0e6d2245957818', '16ceb96e4ddbe889'),
 ('compound', 'fp64', 'rdn', 0): (9, 8, 3, 'ab315843037c0487427e8ba4046dab66', '87852c9d56d2b291'),
 ('compound', 'fp64', 'rdn', 1): (26, 10, 7, 'fc5e373c0211b193195fd09a2c0c56c8', '8b1e2965175a1b97'),
 ('compound', 'fp64', 'rdn', 3): (404, 127, 21, '12b1771a67cbd61ca09f19273fa2e598', '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rdn', 9007199254740993): (405, 127, 21, '3e346094d790df28095f62c89ff9af31',
                                                 '6676f859f6d982a4'),
 ('compound', 'fp64', 'rmm', -3): (410, 126, 22, '5a177234f3cc993ba15e3ac066ab53ad', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rmm', 0): (9, 8, 3, 'ab315843037c0487427e8ba4046dab66', '87852c9d56d2b291'),
 ('compound', 'fp64', 'rmm', 1): (26, 10, 7, '56b1190ccb29e7f1dfbcb804f90d60f3', '8b1e2965175a1b97'),
 ('compound', 'fp64', 'rmm', 3): (410, 126, 22, 'e9ea22cc56fe718afb0d66ea48f76b83', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rmm', 9007199254740993): (411, 126, 22, 'e454bd7e36b4188d5491892d11d06375',
                                                 '2e52f03de8a21a02'),
 ('compound', 'fp64', 'rne', -9223372036854775808): (410, 126, 22, '07deb52d5ec7c2421b344b4eb739e470',
                                                     '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', -3): (410, 126, 22, '978e38176873f3c288cb4ce4f70f13f0', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', -2): (410, 125, 22, '7047c168f081b80fd8aa13474e264386', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', 0): (9, 8, 3, 'ab315843037c0487427e8ba4046dab66', '87852c9d56d2b291'),
 ('compound', 'fp64', 'rne', 1): (25, 10, 7, '643c43b7d7e325456fd368126a6e8e14', '6bb06f4f804cd716'),
 ('compound', 'fp64', 'rne', 2): (410, 125, 22, 'c8f446c50b79ae1fec67de59df4f8f47', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', 3): (410, 126, 22, '557a39f6bd68b545ad2d01924e926801', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', 8): (410, 125, 22, '5cfcd301b8b2909cc314c71922c4cd62', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', 17): (410, 126, 22, '3fb7b898a80bcaf76cc8a1f56d37618a', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', 1000): (410, 126, 22, 'a693da8dd1826d8e97c7c3ce1602936b', '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', 2147483647): (410, 126, 22, '41ff0fc8536aa926ee4c94448371cd6f',
                                           '0b8b7b9ade43140e'),
 ('compound', 'fp64', 'rne', 9007199254740993): (411, 126, 22, '8d865c1a09915293e00d9c38bfd2c3d5',
                                                 '2e52f03de8a21a02'),
 ('compound', 'fp64', 'rne', 9223372036854775807): (411, 126, 22, '46ee2a1eae34aafb7d522b783de4dcf4',
                                                    '2e52f03de8a21a02'),
 ('compound', 'fp64', 'rtz', -9223372036854775808): (403, 127, 21, '1005171f70a1e5caf0759c76e00d1f9c',
                                                     '16ceb96e4ddbe889'),
 ('compound', 'fp64', 'rtz', -3): (403, 127, 21, '2d6c8c4120b14c0d9a7213266c867086', '16ceb96e4ddbe889'),
 ('compound', 'fp64', 'rtz', -2): (403, 126, 21, '82cfc876e2e7ffd672b50e92484b777f', '16ceb96e4ddbe889'),
 ('compound', 'fp64', 'rtz', 0): (9, 8, 3, 'ab315843037c0487427e8ba4046dab66', '87852c9d56d2b291'),
 ('compound', 'fp64', 'rtz', 1): (26, 10, 7, 'c5d34ba551849e95ee354a36533ed942', '8b1e2965175a1b97'),
 ('compound', 'fp64', 'rtz', 2): (404, 126, 21, '2a0f7a91e4f963adc8daf58274266177', '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rtz', 3): (404, 127, 21, '7f1c4d3ba8481887915608fa2fe054dd', '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rtz', 8): (404, 126, 21, '8f3275cb6cc2c0a97837d56d2e59c566', '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rtz', 17): (404, 127, 21, '1e7d4dd190ab3aca8cd300e929fea50b', '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rtz', 1000): (404, 127, 21, 'df04d6ce53c99ec9f99800df41127517', '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rtz', 2147483647): (404, 127, 21, '1887a3f25193c7017c2eebfffe547715',
                                           '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rtz', 9007199254740993): (405, 127, 21, '8169ac7846d681ecd872defc1c72ac63',
                                                 '6676f859f6d982a4'),
 ('compound', 'fp64', 'rtz', 9223372036854775807): (405, 127, 21, '9b54a326fa6e2d0588f52d8873ae894c',
                                                    '6676f859f6d982a4'),
 ('compound', 'fp64', 'rup', -3): (403, 126, 21, '1a194a06abdb12edbaa20970f1654232', '16ceb96e4ddbe889'),
 ('compound', 'fp64', 'rup', 0): (9, 8, 3, 'ab315843037c0487427e8ba4046dab66', '87852c9d56d2b291'),
 ('compound', 'fp64', 'rup', 1): (26, 10, 7, '7dc6c453bfd48a635e18b36269e12f71', '8b1e2965175a1b97'),
 ('compound', 'fp64', 'rup', 3): (404, 126, 21, 'd08f2bc97b690c416373ede35849a89e', '9604a57af3ad2f03'),
 ('compound', 'fp64', 'rup', 9007199254740993): (405, 126, 21, 'd02ae20cfc500d80eb0e49535517f256',
                                                 '6676f859f6d982a4'),
 ('pown', 'fp128', 'rdn', -9223372036854775808): (425, 154, 19, '20787a3e1d0d0ce3862642225404cc4d',
                                                  'f3b8c7483398aa46'),
 ('pown', 'fp128', 'rdn', -3): (437, 159, 20, 'd8b75911d19e5a6e5c779db5fabfb534', '181c04cc6751f892'),
 ('pown', 'fp128', 'rdn', 0): (6, 7, 2, '708cafe9b4c4211f25472cf4bdf302fc', '9286480e7da5e680'),
 ('pown', 'fp128', 'rdn', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('pown', 'fp128', 'rdn', 3): (436, 159, 20, 'ee10a4f0d4a1fed4ae932a4aff1129b7', '9b6f0b059c5d25a9'),
 ('pown', 'fp128', 'rmm', -9223372036854775808): (431, 153, 21, '3a911407722bfe6cf1cf65be9bae8701',
                                                  'c917ba0f0544a3e5'),
 ('pown', 'fp128', 'rmm', -3): (442, 156, 20, '3d306fcc977a74486918d7d3497442cc', '55c20d2a3ef2a324'),
 ('pown', 'fp128', 'rmm', 0): (6, 7, 2, '708cafe9b4c4211f25472cf4bdf302fc', '9286480e7da5e680'),
 ('pown', 'fp128', 'rmm', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('pown', 'fp128', 'rmm', 3): (442, 156, 20, 'bf43ad742f5236d16655327f3ebb2c5a', '55c20d2a3ef2a324'),
 ('pown', 'fp128', 'rne', -9223372036854775808): (431, 153, 21, '20b314d42b588be1779329ce2d8fe5a7',
                                                  'c917ba0f0544a3e5'),
 ('pown', 'fp128', 'rne', -3): (442, 156, 20, '86a15dc6c833f467e831fc7b8511209f', '55c20d2a3ef2a324'),
 ('pown', 'fp128', 'rne', 0): (6, 7, 2, '708cafe9b4c4211f25472cf4bdf302fc', '9286480e7da5e680'),
 ('pown', 'fp128', 'rne', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('pown', 'fp128', 'rne', 3): (442, 156, 20, '0d60fdbc7dbc0a3d25657f704c1e3760', '55c20d2a3ef2a324'),
 ('pown', 'fp128', 'rne', 17): (442, 156, 20, 'b1929c1fa3734968c3967a59dc9bd108', '55c20d2a3ef2a324'),
 ('pown', 'fp128', 'rtz', -9223372036854775808): (425, 154, 19, 'fe5f470f3552fc1d2c7a5e6ba871a3f2',
                                                  'f3b8c7483398aa46'),
 ('pown', 'fp128', 'rtz', -3): (437, 158, 20, '3e8f3dcc1f1363f1c1aee9cc63253a01', '181c04cc6751f892'),
 ('pown', 'fp128', 'rtz', 0): (6, 7, 2, '708cafe9b4c4211f25472cf4bdf302fc', '9286480e7da5e680'),
 ('pown', 'fp128', 'rtz', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('pown', 'fp128', 'rtz', 3): (436, 158, 20, 'd47d248dd50420611fe49dd2df7ec1e2', '9b6f0b059c5d25a9'),
 ('pown', 'fp128', 'rtz', 17): (436, 158, 20, 'fca88f7c444c484a4a8660646769979a', '9b6f0b059c5d25a9'),
 ('pown', 'fp128', 'rup', -9223372036854775808): (425, 153, 19, '1bbc16146a69f8ca02064cd5383f3bd8',
                                                  'f3b8c7483398aa46'),
 ('pown', 'fp128', 'rup', -3): (437, 157, 20, '42fa92c8af86e636b648a6f268af41d3', '181c04cc6751f892'),
 ('pown', 'fp128', 'rup', 0): (6, 7, 2, '708cafe9b4c4211f25472cf4bdf302fc', '9286480e7da5e680'),
 ('pown', 'fp128', 'rup', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('pown', 'fp128', 'rup', 3): (436, 157, 20, '9a9e2714f0d8979fafe38ab384d0f527', '9b6f0b059c5d25a9'),
 ('pown', 'fp256', 'rdn', -9223372036854775808): (476, 199, 19, 'd24f463f7c544feed668ea1f35a5f80d',
                                                  '1896d5a718a4c264'),
 ('pown', 'fp256', 'rdn', -3): (488, 204, 20, '4d9714de8983e0965bb39fa03dbdde9d', '8da761c333beb2be'),
 ('pown', 'fp256', 'rdn', 0): (6, 7, 2, 'f30e43afef1d37c888c3a562e2fccabd', '9286480e7da5e680'),
 ('pown', 'fp256', 'rdn', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('pown', 'fp256', 'rdn', 3): (487, 204, 20, '96225b306e0c2ed4ccd2f170aa2742f8', '59ce5a8b6683de7d'),
 ('pown', 'fp256', 'rmm', -9223372036854775808): (482, 198, 21, 'f6b391554c1db55132d95f66ebb3b20a',
                                                  '1d4f98ddcd2eb5da'),
 ('pown', 'fp256', 'rmm', -3): (493, 201, 20, 'bd41fff40f5c0b06a7b7ac1533a21058', 'c90bad1fd54a0eb7'),
 ('pown', 'fp256', 'rmm', 0): (6, 7, 2, 'f30e43afef1d37c888c3a562e2fccabd', '9286480e7da5e680'),
 ('pown', 'fp256', 'rmm', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('pown', 'fp256', 'rmm', 3): (493, 201, 20, '75e0a061fbed3db5c7cfa6346ff20aab', 'c90bad1fd54a0eb7'),
 ('pown', 'fp256', 'rne', -9223372036854775808): (482, 198, 21, '123db7b65c44bb3382eade2184c575da',
                                                  '1d4f98ddcd2eb5da'),
 ('pown', 'fp256', 'rne', -3): (493, 201, 20, '2117f58abd409321aaaf59e5ac80b3be', 'c90bad1fd54a0eb7'),
 ('pown', 'fp256', 'rne', 0): (6, 7, 2, 'f30e43afef1d37c888c3a562e2fccabd', '9286480e7da5e680'),
 ('pown', 'fp256', 'rne', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('pown', 'fp256', 'rne', 3): (493, 201, 20, '55b95d870e068c4512c6ac2aa2615199', 'c90bad1fd54a0eb7'),
 ('pown', 'fp256', 'rne', 17): (493, 201, 20, '3f7260df1c20c0805e48ec69fd485868', 'c90bad1fd54a0eb7'),
 ('pown', 'fp256', 'rtz', -9223372036854775808): (476, 199, 19, 'ae9d86e40817ceab3bdbd762b46efcff',
                                                  '1896d5a718a4c264'),
 ('pown', 'fp256', 'rtz', -3): (488, 203, 20, '69212d6d72235df3b63c0289d3c9c8aa', '8da761c333beb2be'),
 ('pown', 'fp256', 'rtz', 0): (6, 7, 2, 'f30e43afef1d37c888c3a562e2fccabd', '9286480e7da5e680'),
 ('pown', 'fp256', 'rtz', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('pown', 'fp256', 'rtz', 3): (487, 203, 20, 'c156c849b514e8fc35aeb84c2d6bd91e', '59ce5a8b6683de7d'),
 ('pown', 'fp256', 'rtz', 17): (487, 203, 20, 'ae137dc66b8398c8dea2212e0a583015', '59ce5a8b6683de7d'),
 ('pown', 'fp256', 'rup', -9223372036854775808): (476, 198, 19, '298d0be4db08d44fc1780ec50f4f2e59',
                                                  '1896d5a718a4c264'),
 ('pown', 'fp256', 'rup', -3): (488, 202, 20, '725bd48237e3d7d000373ff9dfb71271', '8da761c333beb2be'),
 ('pown', 'fp256', 'rup', 0): (6, 7, 2, 'f30e43afef1d37c888c3a562e2fccabd', '9286480e7da5e680'),
 ('pown', 'fp256', 'rup', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('pown', 'fp256', 'rup', 3): (487, 202, 20, '25053065145922e74beeb2799e3c14d5', '59ce5a8b6683de7d'),
 ('pown', 'fp64', 'rdn', -3): (381, 131, 21, 'ff314862485560258b549022cd4d2a5f', '81feee007c9a3170'),
 ('pown', 'fp64', 'rdn', 0): (6, 7, 2, '33f4ed572c379364ded125886df8f9ac', '9286480e7da5e680'),
 ('pown', 'fp64', 'rdn', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('pown', 'fp64', 'rdn', 3): (380, 131, 21, 'bccc34f1cd1ca0c8bc2cdb5803ff8e02', 'b95b9cccd7cdc064'),
 ('pown', 'fp64', 'rdn', 9007199254740993): (381, 130, 21, '1f3c2cba03c9d2a296acbff17b31bcfb',
                                             'f5dc6a98676985a9'),
 ('pown', 'fp64', 'rmm', -3): (386, 128, 21, '69c0a44c709a029c60e06aab8a2c74e4', 'd1ff3af4107efad5'),
 ('pown', 'fp64', 'rmm', 0): (6, 7, 2, '33f4ed572c379364ded125886df8f9ac', '9286480e7da5e680'),
 ('pown', 'fp64', 'rmm', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('pown', 'fp64', 'rmm', 3): (386, 128, 21, '9950b2efabd05680caf38a4e54e2dc55', 'd1ff3af4107efad5'),
 ('pown', 'fp64', 'rmm', 9007199254740993): (387, 127, 21, '5b3791864557137966c6a7dfcc6d0791',
                                             '85d6114b18958e7b'),
 ('pown', 'fp64', 'rne', -9223372036854775808): (375, 126, 21, 'fdd4989cc4c5b3f79cc384de1eef1cc1',
                                                 '0a17e5f932417a60'),
 ('pown', 'fp64', 'rne', -3): (386, 128, 21, '518125692ef09e71ffc454e94d3edf8c', 'd1ff3af4107efad5'),
 ('pown', 'fp64', 'rne', -2): (375, 125, 21, 'f8c8d4d0e8742d32b4fa1038d7afbf33', '0a17e5f932417a60'),
 ('pown', 'fp64', 'rne', 0): (6, 7, 2, '33f4ed572c379364ded125886df8f9ac', '9286480e7da5e680'),
 ('pown', 'fp64', 'rne', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('pown', 'fp64', 'rne', 2): (375, 125, 21, 'd81cf02f1c1a96fb3647d55b74306e27', '0a17e5f932417a60'),
 ('pown', 'fp64', 'rne', 3): (386, 128, 21, '054058564c30bf082beb6b4f944b237f', 'd1ff3af4107efad5'),
 ('pown', 'fp64', 'rne', 8): (375, 125, 21, 'bf08f35484ec8965b11bdfee13cdc5de', '0a17e5f932417a60'),
 ('pown', 'fp64', 'rne', 17): (386, 128, 21, '10b384815bd9a0cd9fd9abf11917e288', 'd1ff3af4107efad5'),
 ('pown', 'fp64', 'rne', 1000): (375, 126, 21, 'ddbf167e9e878eacbafce1fe7e2e5b7e', '0a17e5f932417a60'),
 ('pown', 'fp64', 'rne', 2147483647): (386, 128, 21, 'bdf5af2ccbaedd3976dcea3004125b90', 'd1ff3af4107efad5'),
 ('pown', 'fp64', 'rne', 9007199254740993): (387, 127, 21, '8424cddfc7a6cb73b56ba473a0a9d4f4',
                                             '85d6114b18958e7b'),
 ('pown', 'fp64', 'rne', 9223372036854775807): (387, 128, 21, '1bb7f61400dc4355e9842e9b86676038',
                                                '85d6114b18958e7b'),
 ('pown', 'fp64', 'rtz', -9223372036854775808): (369, 127, 20, 'ab71372fe2e2e75ec1d0cf0aa8b5846c',
                                                 '53cd5c6a6cadeb5f'),
 ('pown', 'fp64', 'rtz', -3): (381, 130, 21, '7f97de607d28cbeadaca7ff7ac21593f', '81feee007c9a3170'),
 ('pown', 'fp64', 'rtz', -2): (369, 126, 20, 'b4a3fbd0fcd27075270a19d95219ba0a', '53cd5c6a6cadeb5f'),
 ('pown', 'fp64', 'rtz', 0): (6, 7, 2, '33f4ed572c379364ded125886df8f9ac', '9286480e7da5e680'),
 ('pown', 'fp64', 'rtz', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('pown', 'fp64', 'rtz', 2): (368, 126, 20, '29857f787a2bc25d1ff9564e3d155fb0', '185e15abb8c4c351'),
 ('pown', 'fp64', 'rtz', 3): (380, 130, 21, 'eb725ecf66614535318201502ad0dd71', 'b95b9cccd7cdc064'),
 ('pown', 'fp64', 'rtz', 8): (368, 126, 20, 'b58129d0563fb4cb809c924ac442d246', '185e15abb8c4c351'),
 ('pown', 'fp64', 'rtz', 17): (380, 130, 21, '0b9e23beb0e9d021ea4b773eb7f139fd', 'b95b9cccd7cdc064'),
 ('pown', 'fp64', 'rtz', 1000): (368, 127, 20, '453ef31100726bb620382d5b109fa3cf', '185e15abb8c4c351'),
 ('pown', 'fp64', 'rtz', 2147483647): (380, 130, 21, '7ac3525aba20d5affdfcaad34390b601', 'b95b9cccd7cdc064'),
 ('pown', 'fp64', 'rtz', 9007199254740993): (381, 129, 21, 'bef0d99f8f22a1f419fd464ce2098158',
                                             'f5dc6a98676985a9'),
 ('pown', 'fp64', 'rtz', 9223372036854775807): (381, 130, 21, '8d6042b7b001122093190b584bd994c2',
                                                'f5dc6a98676985a9'),
 ('pown', 'fp64', 'rup', -3): (381, 129, 21, 'abf0aca764410744001677fdbb59ddf7', '81feee007c9a3170'),
 ('pown', 'fp64', 'rup', 0): (6, 7, 2, '33f4ed572c379364ded125886df8f9ac', '9286480e7da5e680'),
 ('pown', 'fp64', 'rup', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('pown', 'fp64', 'rup', 3): (380, 129, 21, '98201463952b516a9de9b3923f71b4d6', 'b95b9cccd7cdc064'),
 ('pown', 'fp64', 'rup', 9007199254740993): (381, 128, 21, '099caef7b6be535ca442d81c2ca8cb69',
                                             'f5dc6a98676985a9'),
 ('rootn', 'fp128', 'rdn', -9223372036854775808): (430, 155, 16, '07605af66371e17d915f1ce818a5624a',
                                                   '2829f55569ab0c0c'),
 ('rootn', 'fp128', 'rdn', -3): (438, 160, 17, 'd539ce412f4315c6ddd3d5cef09be4fc', '51ea6f64d4b8c016'),
 ('rootn', 'fp128', 'rdn', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('rootn', 'fp128', 'rdn', 3): (437, 158, 17, 'ff1413fc75fb2965e6d55c862a2d6a03', '647213b31354da83'),
 ('rootn', 'fp128', 'rmm', -9223372036854775808): (436, 154, 18, '8789c7b76ec53a3698ce4b995ca2b2da',
                                                   'a6ed7bf24eb7e0ab'),
 ('rootn', 'fp128', 'rmm', -3): (443, 157, 19, '69f642ff9a2e16a7f7e191b445f3950d', '0350d09a931a7632'),
 ('rootn', 'fp128', 'rmm', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('rootn', 'fp128', 'rmm', 3): (443, 155, 19, 'cb7ca5116ff458ec7e7846de6ed04d32', '0350d09a931a7632'),
 ('rootn', 'fp128', 'rne', -9223372036854775808): (436, 154, 18, '08e6e21dcd00d13ed1431aa4d4b356e5',
                                                   'a6ed7bf24eb7e0ab'),
 ('rootn', 'fp128', 'rne', -3): (443, 157, 19, 'bf5939f173c4cef9cb5b1ae3405e9543', '0350d09a931a7632'),
 ('rootn', 'fp128', 'rne', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('rootn', 'fp128', 'rne', 3): (443, 155, 19, '20f3d7edd71a3de7c48552139bc9a60f', '0350d09a931a7632'),
 ('rootn', 'fp128', 'rne', 17): (443, 156, 19, '86698a12724020753cd9969dfaae6f62', '0350d09a931a7632'),
 ('rootn', 'fp128', 'rtz', -9223372036854775808): (430, 155, 16, 'b1ec37943b68d109a2d08e40ccdda6e2',
                                                   '2829f55569ab0c0c'),
 ('rootn', 'fp128', 'rtz', -3): (438, 159, 17, 'a1c54865a9de3089b2d669a714df49da', '51ea6f64d4b8c016'),
 ('rootn', 'fp128', 'rtz', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('rootn', 'fp128', 'rtz', 3): (437, 157, 17, 'b70f74f2e31c3e3eb8d9b5b81602e34f', '647213b31354da83'),
 ('rootn', 'fp128', 'rtz', 17): (437, 158, 17, '65bd51cccbe4e182b2753c2082d47c36', '647213b31354da83'),
 ('rootn', 'fp128', 'rup', -9223372036854775808): (430, 154, 16, 'bb1dbaac5afcccdcde50e75dbfbbaca4',
                                                   '2829f55569ab0c0c'),
 ('rootn', 'fp128', 'rup', -3): (438, 158, 17, 'b8319eba67854565444b29b6aacf854f', '51ea6f64d4b8c016'),
 ('rootn', 'fp128', 'rup', 1): (6, 6, 3, 'a0a4d950af06a09cd10a3cee11f0c09f', '9286480e7da5e680'),
 ('rootn', 'fp128', 'rup', 3): (437, 156, 17, 'f0c3291f9e88ff27d46a412e6a6fcbac', '647213b31354da83'),
 ('rootn', 'fp256', 'rdn', -9223372036854775808): (481, 200, 16, '4f67aff1aae03faea9f2020db338750a',
                                                   'bb950b238df9ff6f'),
 ('rootn', 'fp256', 'rdn', -3): (489, 205, 17, 'daaa9c56bfc9d6ee07805206aea0d64d', 'f73ee15c31de8ab0'),
 ('rootn', 'fp256', 'rdn', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('rootn', 'fp256', 'rdn', 3): (488, 203, 17, '5937ae3bcfd3d4c5d3b5aa026779a883', '4fc9b545c133872f'),
 ('rootn', 'fp256', 'rmm', -9223372036854775808): (487, 199, 18, '4a56c15119324456addb97064c90fbc2',
                                                   'f673fd0c795d4068'),
 ('rootn', 'fp256', 'rmm', -3): (494, 202, 19, '08d2bb8df15d7e6fd32c9ef21f570fb6', '9ab4da2dce0af23a'),
 ('rootn', 'fp256', 'rmm', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('rootn', 'fp256', 'rmm', 3): (494, 200, 19, '65845bd9c757a1665419ef197cfba2ef', '9ab4da2dce0af23a'),
 ('rootn', 'fp256', 'rne', -9223372036854775808): (487, 199, 18, '437297d4c9d1a397468e2a0d7965e398',
                                                   'f673fd0c795d4068'),
 ('rootn', 'fp256', 'rne', -3): (494, 202, 19, '6f76553b7c64e06f712892f510a6243b', '9ab4da2dce0af23a'),
 ('rootn', 'fp256', 'rne', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('rootn', 'fp256', 'rne', 3): (494, 200, 19, '53358d6e8ca59a0ad5f0ed4d6712b4b4', '9ab4da2dce0af23a'),
 ('rootn', 'fp256', 'rne', 17): (494, 200, 19, '52f53f5219d35bbd33bce4175dd400dd', '9ab4da2dce0af23a'),
 ('rootn', 'fp256', 'rtz', -9223372036854775808): (481, 200, 16, '42102c82fc5fe2503f26c2f14a6e7087',
                                                   'bb950b238df9ff6f'),
 ('rootn', 'fp256', 'rtz', -3): (489, 204, 17, '145cdb635400046fec54564351ea47ae', 'f73ee15c31de8ab0'),
 ('rootn', 'fp256', 'rtz', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('rootn', 'fp256', 'rtz', 3): (488, 202, 17, '5356f4335843e916bd5d5c02c2dfa69f', '4fc9b545c133872f'),
 ('rootn', 'fp256', 'rtz', 17): (488, 202, 17, '6985c1c72350c82ffc18f5b627efb973', '4fc9b545c133872f'),
 ('rootn', 'fp256', 'rup', -9223372036854775808): (481, 199, 16, 'c80a93db7281e0133219c98379a51ba6',
                                                   'bb950b238df9ff6f'),
 ('rootn', 'fp256', 'rup', -3): (489, 203, 17, '5d013db01dc59eae14ef53bcaa755774', 'f73ee15c31de8ab0'),
 ('rootn', 'fp256', 'rup', 1): (6, 6, 3, '43ae19dcbfb158c655833addeebb3963', '9286480e7da5e680'),
 ('rootn', 'fp256', 'rup', 3): (488, 201, 17, '52f4100cd0b6d4a5081230573611b47f', '4fc9b545c133872f'),
 ('rootn', 'fp64', 'rdn', -3): (382, 132, 18, '3ef91166a93e529ea960fd5ff7804ce3', '825969e1c2a89fe5'),
 ('rootn', 'fp64', 'rdn', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('rootn', 'fp64', 'rdn', 3): (381, 130, 18, '626abb42d42e8b5c0a80e6552c13c8fd', 'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rdn', 9007199254740993): (381, 132, 18, '9625a7a0d3458852a6ce1903eb3caeaf',
                                              'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rmm', -3): (387, 129, 19, '5143362330eca4c821b738a1c95d0320', '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rmm', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('rootn', 'fp64', 'rmm', 3): (387, 127, 19, 'fcd1c3489904d57b5e93fe09801a66fc', '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rmm', 9007199254740993): (387, 129, 19, '8db2231e29d9a2fbb3be3fa810a7b0a6',
                                              '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rne', -9223372036854775808): (380, 126, 18, '067d7532f740361680c36f1df3401637',
                                                  '65341c5631abe958'),
 ('rootn', 'fp64', 'rne', -3): (387, 129, 19, 'f02ef13698718582486b2bcb307fc260', '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rne', -2): (380, 125, 18, '3f4cc785d7fd64418c563875348cfb7f', '65341c5631abe958'),
 ('rootn', 'fp64', 'rne', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('rootn', 'fp64', 'rne', 2): (380, 125, 18, '126481fd1f8162258c26c4057353f988', '65341c5631abe958'),
 ('rootn', 'fp64', 'rne', 3): (387, 127, 19, 'fe7f1c10a8b68ea7b1d1e29c4b45b50f', '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rne', 8): (380, 126, 18, '2ec64a90ded0988b39760d20ea4e83e9', '65341c5631abe958'),
 ('rootn', 'fp64', 'rne', 17): (387, 128, 19, 'e4eda5b344aa814b1d303e840ad86eb3', '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rne', 1000): (381, 127, 18, 'e61eca76cde81d2b679cef93a3249577', '22c4c18ea9b0d075'),
 ('rootn', 'fp64', 'rne', 2147483647): (387, 129, 19, '57e8d019b036b49c3bf92acfe5943034', '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rne', 9007199254740993): (387, 129, 19, 'a65ec91dc54541cd7ed8a0b5dfc2f8d2',
                                              '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rne', 9223372036854775807): (387, 129, 19, 'c56e88c55d2ddaa1549ae783a9e02248',
                                                 '85d6114b18958e7b'),
 ('rootn', 'fp64', 'rtz', -9223372036854775808): (374, 127, 17, '846e52909dd23130f8bb004864b8ad3c',
                                                  '7fd81f627423c6c3'),
 ('rootn', 'fp64', 'rtz', -3): (382, 131, 18, 'b05c21962b11e4547618aaec97313c2f', '825969e1c2a89fe5'),
 ('rootn', 'fp64', 'rtz', -2): (374, 126, 17, 'ac3dce0db1ba6060f07c38ca2ec9b41c', '7fd81f627423c6c3'),
 ('rootn', 'fp64', 'rtz', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('rootn', 'fp64', 'rtz', 2): (373, 126, 17, 'c7f1b802abbc97eee62878864146a839', '2505cbc174d96c13'),
 ('rootn', 'fp64', 'rtz', 3): (381, 129, 18, '6604f7acb7d3555ef83727f44daac88e', 'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rtz', 8): (373, 127, 17, '46afedc2a33e45877a0b294d8e152bd5', '2505cbc174d96c13'),
 ('rootn', 'fp64', 'rtz', 17): (381, 130, 18, 'b88b52c1c65abb36faa10142d8517b48', 'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rtz', 1000): (374, 128, 17, 'fb25b898662b37f3f18a16410ab516f3', 'b755e5ef02deba60'),
 ('rootn', 'fp64', 'rtz', 2147483647): (381, 131, 18, '4fd8633627f97c25e0af909b0611415a', 'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rtz', 9007199254740993): (381, 131, 18, '260baa325fe1e6bbc5772389b0c576fd',
                                              'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rtz', 9223372036854775807): (381, 131, 18, 'cb620a144fb3b04189662e92257b3a1d',
                                                 'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rup', -3): (382, 130, 18, 'a98f78bee8f1360300ee785aec86f8b0', '825969e1c2a89fe5'),
 ('rootn', 'fp64', 'rup', 1): (6, 6, 3, 'cd40c863b2241b86a977f5ba5be2b81f', '9286480e7da5e680'),
 ('rootn', 'fp64', 'rup', 3): (381, 128, 18, '9a304bae38eac8ee80b54527f9f8b6f9', 'f5dc6a98676985a9'),
 ('rootn', 'fp64', 'rup', 9007199254740993): (381, 130, 18, 'e28d326f2cf7ec723e5edd2c948c28bc',
                                              'f5dc6a98676985a9')}

EFT_N = {('compound', 'fp128', -9223372036854775808): (31, 1),
 ('compound', 'fp128', -3): (31, 1),
 ('compound', 'fp128', 0): (0, 0),
 ('compound', 'fp128', 1): (0, 1),
 ('compound', 'fp128', 3): (31, 1),
 ('compound', 'fp128', 17): (31, 1),
 ('compound', 'fp256', -9223372036854775808): (32, 1),
 ('compound', 'fp256', -3): (32, 1),
 ('compound', 'fp256', 0): (0, 0),
 ('compound', 'fp256', 1): (0, 1),
 ('compound', 'fp256', 3): (32, 1),
 ('compound', 'fp256', 17): (32, 1),
 ('compound', 'fp64', -9223372036854775808): (26, 1),
 ('compound', 'fp64', -3): (26, 1),
 ('compound', 'fp64', -2): (26, 1),
 ('compound', 'fp64', 0): (0, 0),
 ('compound', 'fp64', 1): (0, 1),
 ('compound', 'fp64', 2): (26, 1),
 ('compound', 'fp64', 3): (26, 1),
 ('compound', 'fp64', 8): (26, 1),
 ('compound', 'fp64', 17): (26, 1),
 ('compound', 'fp64', 1000): (26, 1),
 ('compound', 'fp64', 2147483647): (26, 1),
 ('compound', 'fp64', 9007199254740993): (26, 1),
 ('compound', 'fp64', 9223372036854775807): (26, 1),
 ('pown', 'fp128', -9223372036854775808): (31, 0),
 ('pown', 'fp128', -3): (31, 0),
 ('pown', 'fp128', 0): (0, 0),
 ('pown', 'fp128', 1): (0, 0),
 ('pown', 'fp128', 3): (31, 0),
 ('pown', 'fp128', 17): (31, 0),
 ('pown', 'fp256', -9223372036854775808): (32, 0),
 ('pown', 'fp256', -3): (32, 0),
 ('pown', 'fp256', 0): (0, 0),
 ('pown', 'fp256', 1): (0, 0),
 ('pown', 'fp256', 3): (32, 0),
 ('pown', 'fp256', 17): (32, 0),
 ('pown', 'fp64', -9223372036854775808): (26, 0),
 ('pown', 'fp64', -3): (26, 0),
 ('pown', 'fp64', -2): (26, 0),
 ('pown', 'fp64', 0): (0, 0),
 ('pown', 'fp64', 1): (0, 0),
 ('pown', 'fp64', 2): (26, 0),
 ('pown', 'fp64', 3): (26, 0),
 ('pown', 'fp64', 8): (26, 0),
 ('pown', 'fp64', 17): (26, 0),
 ('pown', 'fp64', 1000): (26, 0),
 ('pown', 'fp64', 2147483647): (26, 0),
 ('pown', 'fp64', 9007199254740993): (26, 0),
 ('pown', 'fp64', 9223372036854775807): (26, 0),
 ('rootn', 'fp128', -9223372036854775808): (31, 0),
 ('rootn', 'fp128', -3): (31, 0),
 ('rootn', 'fp128', 1): (0, 0),
 ('rootn', 'fp128', 3): (31, 0),
 ('rootn', 'fp128', 17): (31, 0),
 ('rootn', 'fp256', -9223372036854775808): (32, 0),
 ('rootn', 'fp256', -3): (32, 0),
 ('rootn', 'fp256', 1): (0, 0),
 ('rootn', 'fp256', 3): (32, 0),
 ('rootn', 'fp256', 17): (32, 0),
 ('rootn', 'fp64', -9223372036854775808): (26, 0),
 ('rootn', 'fp64', -3): (26, 0),
 ('rootn', 'fp64', -2): (26, 0),
 ('rootn', 'fp64', 1): (0, 0),
 ('rootn', 'fp64', 2): (26, 0),
 ('rootn', 'fp64', 3): (26, 0),
 ('rootn', 'fp64', 8): (26, 0),
 ('rootn', 'fp64', 17): (26, 0),
 ('rootn', 'fp64', 1000): (26, 0),
 ('rootn', 'fp64', 2147483647): (26, 0),
 ('rootn', 'fp64', 9007199254740993): (26, 0),
 ('rootn', 'fp64', 9223372036854775807): (26, 0)}

FLAG_WORDS_N = {('compound', 'n0'): frozenset({0, 1}),
 ('compound', 'n1'): frozenset({0, 1, 20, 16}),
 ('compound', 'neg'): frozenset({0, 1, 2, 16, 144, 20, 148, 24, 152}),
 ('compound', 'pos'): frozenset({0, 1, 16, 144, 20, 148, 24, 152}),
 ('pown', 'n0'): frozenset({0, 1}),
 ('pown', 'n1'): frozenset({0, 1}),
 ('pown', 'neg'): frozenset({0, 1, 2, 16, 144, 20, 148, 24, 152}),
 ('pown', 'pos'): frozenset({0, 1, 16, 144, 20, 148, 24, 152}),
 ('rootn', 'n1'): frozenset({0, 1}),
 ('rootn', 'neg'): frozenset({0, 1, 2, 16, 144, 20, 148, 24, 152}),
 ('rootn', 'pos'): frozenset({0, 1, 16, 144, 20, 148, 24, 152})}

POOL_MARKS_N = {('compound', 'fp128', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp128', -3): {'rdn': 1, 'rmm': 2, 'rne': 2, 'rtz': 1, 'rup': 1},
 ('compound', 'fp128', 0): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp128', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp128', 3): {'rdn': 15, 'rmm': 16, 'rne': 16, 'rtz': 15, 'rup': 15},
 ('compound', 'fp128', 17): {'rdn': 9, 'rmm': 10, 'rne': 10, 'rtz': 9, 'rup': 9},
 ('compound', 'fp256', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp256', -3): {'rdn': 0, 'rmm': 1, 'rne': 1, 'rtz': 0, 'rup': 0},
 ('compound', 'fp256', 0): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp256', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp256', 3): {'rdn': 11, 'rmm': 11, 'rne': 11, 'rtz': 11, 'rup': 11},
 ('compound', 'fp256', 17): {'rdn': 10, 'rmm': 10, 'rne': 10, 'rtz': 10, 'rup': 10},
 ('compound', 'fp64', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp64', -3): {'rdn': 0, 'rmm': 1, 'rne': 1, 'rtz': 0, 'rup': 0},
 ('compound', 'fp64', -2): {'rdn': 2, 'rmm': 2, 'rne': 2, 'rtz': 2, 'rup': 2},
 ('compound', 'fp64', 0): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp64', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp64', 2): {'rdn': 24, 'rmm': 25, 'rne': 25, 'rtz': 24, 'rup': 24},
 ('compound', 'fp64', 3): {'rdn': 16, 'rmm': 17, 'rne': 17, 'rtz': 16, 'rup': 16},
 ('compound', 'fp64', 8): {'rdn': 11, 'rmm': 11, 'rne': 11, 'rtz': 11, 'rup': 11},
 ('compound', 'fp64', 17): {'rdn': 2, 'rmm': 3, 'rne': 3, 'rtz': 2, 'rup': 2},
 ('compound', 'fp64', 1000): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp64', 2147483647): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('compound', 'fp64', 9223372036854775807): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp128', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp128', -3): {'rdn': 2, 'rmm': 6, 'rne': 6, 'rtz': 2, 'rup': 2},
 ('pown', 'fp128', 0): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp128', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp128', 3): {'rdn': 23, 'rmm': 23, 'rne': 23, 'rtz': 23, 'rup': 23},
 ('pown', 'fp128', 17): {'rdn': 19, 'rmm': 19, 'rne': 19, 'rtz': 19, 'rup': 19},
 ('pown', 'fp256', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp256', -3): {'rdn': 0, 'rmm': 2, 'rne': 2, 'rtz': 0, 'rup': 0},
 ('pown', 'fp256', 0): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp256', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp256', 3): {'rdn': 16, 'rmm': 16, 'rne': 16, 'rtz': 16, 'rup': 16},
 ('pown', 'fp256', 17): {'rdn': 16, 'rmm': 16, 'rne': 16, 'rtz': 16, 'rup': 16},
 ('pown', 'fp64', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp64', -3): {'rdn': 3, 'rmm': 5, 'rne': 5, 'rtz': 3, 'rup': 3},
 ('pown', 'fp64', -2): {'rdn': 3, 'rmm': 3, 'rne': 3, 'rtz': 3, 'rup': 3},
 ('pown', 'fp64', 0): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp64', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp64', 2): {'rdn': 34, 'rmm': 35, 'rne': 35, 'rtz': 34, 'rup': 34},
 ('pown', 'fp64', 3): {'rdn': 20, 'rmm': 20, 'rne': 20, 'rtz': 20, 'rup': 20},
 ('pown', 'fp64', 8): {'rdn': 15, 'rmm': 15, 'rne': 15, 'rtz': 15, 'rup': 15},
 ('pown', 'fp64', 17): {'rdn': 5, 'rmm': 7, 'rne': 7, 'rtz': 5, 'rup': 5},
 ('pown', 'fp64', 1000): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp64', 2147483647): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('pown', 'fp64', 9223372036854775807): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp128', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp128', -3): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp128', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp128', 3): {'rdn': 5, 'rmm': 5, 'rne': 5, 'rtz': 5, 'rup': 5},
 ('rootn', 'fp128', 17): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp256', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp256', -3): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp256', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp256', 3): {'rdn': 1, 'rmm': 1, 'rne': 1, 'rtz': 1, 'rup': 1},
 ('rootn', 'fp256', 17): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', -9223372036854775808): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', -3): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', -2): {'rdn': 1, 'rmm': 1, 'rne': 1, 'rtz': 1, 'rup': 1},
 ('rootn', 'fp64', 1): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', 2): {'rdn': 7, 'rmm': 13, 'rne': 13, 'rtz': 7, 'rup': 7},
 ('rootn', 'fp64', 3): {'rdn': 3, 'rmm': 3, 'rne': 3, 'rtz': 3, 'rup': 3},
 ('rootn', 'fp64', 8): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', 17): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', 1000): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', 2147483647): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0},
 ('rootn', 'fp64', 9223372036854775807): {'rdn': 0, 'rmm': 0, 'rne': 0, 'rtz': 0, 'rup': 0}}

SPECIAL_MARKS_N = {('compound', 'fp128', -9223372036854775808): (2, 2, 2, 2, 2),
 ('compound', 'fp128', -3): (1, 1, 1, 1, 1),
 ('compound', 'fp128', 0): (0, 0, 0, 0, 0),
 ('compound', 'fp128', 1): (0, 0, 0, 0, 0),
 ('compound', 'fp128', 3): (3, 1, 1, 1, 3),
 ('compound', 'fp128', 17): (3, 1, 1, 1, 3),
 ('compound', 'fp256', -9223372036854775808): (2, 2, 2, 2, 2),
 ('compound', 'fp256', -3): (1, 1, 1, 1, 1),
 ('compound', 'fp256', 0): (0, 0, 0, 0, 0),
 ('compound', 'fp256', 1): (0, 0, 0, 0, 0),
 ('compound', 'fp256', 3): (3, 1, 1, 1, 3),
 ('compound', 'fp256', 17): (3, 1, 1, 1, 3),
 ('compound', 'fp64', -9223372036854775808): (0, 0, 0, 0, 0),
 ('compound', 'fp64', -3): (1, 1, 1, 1, 1),
 ('compound', 'fp64', -2): (2, 1, 1, 1, 2),
 ('compound', 'fp64', 0): (0, 0, 0, 0, 0),
 ('compound', 'fp64', 1): (0, 0, 0, 0, 0),
 ('compound', 'fp64', 2): (3, 3, 3, 3, 3),
 ('compound', 'fp64', 3): (3, 1, 1, 1, 3),
 ('compound', 'fp64', 8): (5, 4, 4, 4, 5),
 ('compound', 'fp64', 17): (3, 1, 1, 1, 3),
 ('compound', 'fp64', 1000): (0, 0, 0, 0, 0),
 ('compound', 'fp64', 2147483647): (0, 0, 0, 0, 0),
 ('compound', 'fp64', 9007199254740993): (0, 0, 0, 0, 0),
 ('compound', 'fp64', 9223372036854775807): (0, 0, 0, 0, 0),
 ('pown', 'fp128', -9223372036854775808): (0, 0, 0, 0, 0),
 ('pown', 'fp128', -3): (4, 2, 2, 2, 4),
 ('pown', 'fp128', 0): (0, 0, 0, 0, 0),
 ('pown', 'fp128', 1): (0, 0, 0, 0, 0),
 ('pown', 'fp128', 3): (6, 6, 6, 6, 6),
 ('pown', 'fp128', 17): (6, 6, 6, 6, 6),
 ('pown', 'fp256', -9223372036854775808): (4, 4, 4, 4, 4),
 ('pown', 'fp256', -3): (4, 2, 2, 2, 4),
 ('pown', 'fp256', 0): (0, 0, 0, 0, 0),
 ('pown', 'fp256', 1): (0, 0, 0, 0, 0),
 ('pown', 'fp256', 3): (6, 6, 6, 6, 6),
 ('pown', 'fp256', 17): (6, 6, 6, 6, 6),
 ('pown', 'fp64', -9223372036854775808): (0, 0, 0, 0, 0),
 ('pown', 'fp64', -3): (4, 2, 2, 2, 4),
 ('pown', 'fp64', -2): (4, 4, 4, 4, 4),
 ('pown', 'fp64', 0): (0, 0, 0, 0, 0),
 ('pown', 'fp64', 1): (0, 0, 0, 0, 0),
 ('pown', 'fp64', 2): (6, 6, 6, 6, 6),
 ('pown', 'fp64', 3): (6, 6, 6, 6, 6),
 ('pown', 'fp64', 8): (6, 6, 6, 6, 6),
 ('pown', 'fp64', 17): (4, 4, 4, 4, 4),
 ('pown', 'fp64', 1000): (0, 0, 0, 0, 0),
 ('pown', 'fp64', 2147483647): (0, 0, 0, 0, 0),
 ('pown', 'fp64', 9007199254740993): (0, 0, 0, 0, 0),
 ('pown', 'fp64', 9223372036854775807): (0, 0, 0, 0, 0),
 ('rootn', 'fp128', -9223372036854775808): (0, 0, 0, 0, 0),
 ('rootn', 'fp128', -3): (0, 0, 0, 0, 0),
 ('rootn', 'fp128', 1): (0, 0, 0, 0, 0),
 ('rootn', 'fp128', 3): (0, 0, 0, 0, 0),
 ('rootn', 'fp128', 17): (0, 0, 0, 0, 0),
 ('rootn', 'fp256', -9223372036854775808): (0, 0, 0, 0, 0),
 ('rootn', 'fp256', -3): (0, 0, 0, 0, 0),
 ('rootn', 'fp256', 1): (0, 0, 0, 0, 0),
 ('rootn', 'fp256', 3): (0, 0, 0, 0, 0),
 ('rootn', 'fp256', 17): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', -9223372036854775808): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', -3): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', -2): (1, 1, 1, 1, 1),
 ('rootn', 'fp64', 1): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', 2): (3, 0, 0, 0, 3),
 ('rootn', 'fp64', 3): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', 8): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', 17): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', 1000): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', 2147483647): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', 9007199254740993): (0, 0, 0, 0, 0),
 ('rootn', 'fp64', 9223372036854775807): (0, 0, 0, 0, 0)}

# ---- fp32: the triple word, pow and powr (parcel M3F1) builds here ----
#
# (the same tables, for FP32, in a section of its own; FORMATS is the double
# word's three and stays)

import hashlib  # noqa: E402

from cft_golden import FP32  # noqa: E402

# The functions, the five attributes and the tables of fp32's triple word are
# here and below; FORMATS is the double word's three and stays. Every table is
# keyed by (fn, rnd) or by fn, and every pin is the MODEL's (docs/studies/m3/
# pw32.py, parcel M3X: MEASURED on its builds and on seq.py, and equal on this
# build's lanes: the port was shown equal to it on every lane of both pools at
# all five attributes, result, flag word, V0, V1, V2, R, R1, R2 and Bv), not
# computed from the code under test.
#
# Which of the double word's functions are format-generic, CONFIRMED by running
# each on FP32 (parcel M3F1's tests): golden, pool, region, in_main,
# check_pools (given its pinned counts), check_regions, check_specials (given
# its marks), check_structured, check_seq (given its lanes and rows), _screened
# and H.check_reorder. NOT generic, and written here: bound_log2 and
# check_bound (they read the double word's probes Vh and Vl), plant_cases and
# so structured_rows (plant_cases builds the double word's plants, which fp32
# refuses by name), check_shape's tables, check_constants and red_checks.

TW_FUNS = ("pow", "powr")
CHECKS_TW = ("pools", "regions", "specials", "structured", "seq", "bound",
             "shape", "constants")

# the lanes of the pools and the lanes of them that are marked (the model's:
# pw32_pools-model.out.txt, pw32_pools-seq-pow.out.txt, MEASURED by M3X; equal
# here): rne, rtz, rdn, rup, rmm. The pool is pool(fn, FP32), M3G1's, whose
# trials are 64 at width 64 or less
POOL_SIZES_TW = {"pow": 794, "powr": 823}
POOL_MARKS_TW = {("pow", RNE): 57, ("pow", RTZ): 55, ("pow", RDN): 55,
                 ("pow", RUP): 55, ("pow", RMM): 57,
                 ("powr", RNE): 34, ("powr", RTZ): 33, ("powr", RDN): 33,
                 ("powr", RUP): 33, ("powr", RMM): 34}
# the marks of the special rows summed over the five attributes: MEASURED on the
# model's builds (a scratch run of the rows through pw32.build: pow 10, 10 and
# 5, powr 5; the double word's are 34 and 20 for the first two)
SPECIAL_MARKS_TW = {
    "pow": {"x < 0, y odd integer (sign kept), across y's bands": 10,
            "x < 0, y even integer, y past 2^p": 10,
            "subnormal operands": 5},
    "powr": {"subnormal operands": 5}}
# the highest register routines.program uses, the model's `live` mode (r31 and
# r28) and M4C's first-spill rule over the 29 registers r3 to r31: 30 less
# the cap, -2 for pow and +1 for powr
REG_TOP_TW = {"pow": 31, "powr": 28}

SHAPE_TW = {
    ("pow", RNE): (925, 143, 32),
    ("pow", RTZ): (920, 145, 32),
    ("pow", RDN): (921, 146, 32),
    ("pow", RUP): (921, 144, 32),
    ("pow", RMM): (925, 143, 32),
    ("powr", RNE): (903, 139, 29),
    ("powr", RTZ): (897, 140, 29),
    ("powr", RDN): (897, 140, 29),
    ("powr", RUP): (897, 139, 29),
    ("powr", RMM): (903, 139, 29),
}
# (Fast2Sums, TwoSums) built, before pruning: the model's 61 and 42, the same under every attribute
EFT_TW = {(fn, rnd): (61, 42) for fn in ("pow", "powr") for rnd in RND_MODES}
# instructions by phase (Build.phase_of over the live instructions): MEASURED on the model's builds
PHASES_TW = {
    ("pow", RNE): {"Z": 46, "classify": 14, "final": 63, "fixed-grid": 27, "front": 19, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 15, "special": 36, "table": 25, "tail": 6},
    ("pow", RTZ): {"Z": 46, "classify": 14, "final": 63, "fixed-grid": 24, "front": 19, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 13, "special": 36, "table": 25, "tail": 6},
    ("pow", RDN): {"Z": 46, "classify": 14, "final": 63, "fixed-grid": 24, "front": 19, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 13, "special": 37, "table": 25, "tail": 6},
    ("pow", RUP): {"Z": 46, "classify": 14, "final": 63, "fixed-grid": 24, "front": 19, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 13, "special": 37, "table": 25, "tail": 6},
    ("pow", RMM): {"Z": 46, "classify": 14, "final": 63, "fixed-grid": 27, "front": 19, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 15, "special": 36, "table": 25, "tail": 6},
    ("powr", RNE): {"Z": 46, "classify": 14, "final": 59, "fixed-grid": 25, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 15, "special": 39, "table": 25, "tail": 6},
    ("powr", RTZ): {"Z": 46, "classify": 14, "final": 58, "fixed-grid": 22, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 13, "special": 39, "table": 25, "tail": 6},
    ("powr", RDN): {"Z": 46, "classify": 14, "final": 58, "fixed-grid": 22, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 13, "special": 39, "table": 25, "tail": 6},
    ("powr", RUP): {"Z": 46, "classify": 14, "final": 58, "fixed-grid": 22, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 13, "special": 39, "table": 25, "tail": 6},
    ("powr", RMM): {"Z": 46, "classify": 14, "final": 59, "fixed-grid": 25, "head2": 82, "head3": 336, "lookup": 24, "recon": 135, "reduce": 97, "scale": 15, "special": 39, "table": 25, "tail": 6},
}
# instructions by the study's part (label_of over the live instructions)
PARTS_TW = {
    ("pow", RNE): {"exponential": 315, "logarithm": 420, "product": 26, "specials": 69, "test": 95},
    ("pow", RTZ): {"exponential": 313, "logarithm": 420, "product": 26, "specials": 69, "test": 92},
    ("pow", RDN): {"exponential": 313, "logarithm": 420, "product": 26, "specials": 70, "test": 92},
    ("pow", RUP): {"exponential": 313, "logarithm": 420, "product": 26, "specials": 70, "test": 92},
    ("pow", RMM): {"exponential": 315, "logarithm": 420, "product": 26, "specials": 69, "test": 95},
    ("powr", RNE): {"exponential": 315, "logarithm": 420, "product": 26, "specials": 53, "test": 89},
    ("powr", RTZ): {"exponential": 313, "logarithm": 420, "product": 26, "specials": 53, "test": 85},
    ("powr", RDN): {"exponential": 313, "logarithm": 420, "product": 26, "specials": 53, "test": 85},
    ("powr", RUP): {"exponential": 313, "logarithm": 420, "product": 26, "specials": 53, "test": 85},
    ("powr", RMM): {"exponential": 315, "logarithm": 420, "product": 26, "specials": 53, "test": 89},
}
# dag_digest of the model's Build (the design's order), of its scheduled fragment, and the sha256 of the scheduled fragment's emitted order (words by bits)
DIGESTS_TW = {
    ("pow", RNE): (
        "7fea1644e003f4c07c2714dbb401a606761ac38bfab597e04a71ab6c5d36faee",
        "7fea1644e003f4c07c2714dbb401a606761ac38bfab597e04a71ab6c5d36faee",
        "557980e3c4c266692250209c42dbf08ceece04dbac39c49b98cddeb74abcb084"),
    ("pow", RTZ): (
        "92e0e13fc9df847061274efe722b2673f6c7895f53b8d8aca1d2e364e8a79d94",
        "92e0e13fc9df847061274efe722b2673f6c7895f53b8d8aca1d2e364e8a79d94",
        "1797867705784270b8ef1e463918e20266cb3c4e98498e5bfaac6f828b18df6c"),
    ("pow", RDN): (
        "d98b54ac32903ddeb6f8da4fe6c71a25c3b8784212c323caccadff071361b750",
        "d98b54ac32903ddeb6f8da4fe6c71a25c3b8784212c323caccadff071361b750",
        "ad55895b74eafd52ee715ac3db8f52cb11fe0360487711b0a18663fb38b47d77"),
    ("pow", RUP): (
        "a753edc11ea7d48801736f9b05e5353006d445ce933f68f62410a605c00500fb",
        "a753edc11ea7d48801736f9b05e5353006d445ce933f68f62410a605c00500fb",
        "7337e1c9d4b2c738886d0eb4bd5e9603b61354e8c24f2753aeea8c6e0f6b0496"),
    ("pow", RMM): (
        "8a0f496aeace4023163f6a5f5452674662e7563bd323b48df220857a9f3579e5",
        "8a0f496aeace4023163f6a5f5452674662e7563bd323b48df220857a9f3579e5",
        "52d483a9b6bc5855cf30fbda0dd99d5ee0ee03534bb921ebb43a3585adeb520c"),
    ("powr", RNE): (
        "f0c7f76ddc76522ee4720e3b62bff9e60f798b029f77c0d4fb2c037d0eab8d97",
        "f0c7f76ddc76522ee4720e3b62bff9e60f798b029f77c0d4fb2c037d0eab8d97",
        "476f873bb3d4a98c2a01ea622df147a1ca6488d414f55fa51f00f79e0b5b49d9"),
    ("powr", RTZ): (
        "c0b21b4c41f1366e79bc621efac1f7c258ad50f8238cde82807a66fb15c6b92d",
        "c0b21b4c41f1366e79bc621efac1f7c258ad50f8238cde82807a66fb15c6b92d",
        "bea63561dc9f1f502dfeda66e8f8f6d2c552f1b0693d12568a7a289dab0ba6f2"),
    ("powr", RDN): (
        "6c34c1a24aa73919797aba7df069ed1bb6f0216510b09a055a93175306e09096",
        "6c34c1a24aa73919797aba7df069ed1bb6f0216510b09a055a93175306e09096",
        "eb673be84f6c5e6ae5b86c0f94164ed9dc0470246904bf9f3db3474b890738cc"),
    ("powr", RUP): (
        "900cf609b97b822eaf443af521f2d81556b0d67f413ab76a2a4ec4c814d8ab18",
        "900cf609b97b822eaf443af521f2d81556b0d67f413ab76a2a4ec4c814d8ab18",
        "2771e84f4e7f5434eca510bc063cf3105f906196c569520150e321805bcad7ad"),
    ("powr", RMM): (
        "dfcce79e6b79c1029b3ea897031725a8781bc6b0d65b7f5a38414b6197b40c73",
        "dfcce79e6b79c1029b3ea897031725a8781bc6b0d65b7f5a38414b6197b40c73",
        "df5d03de5df570f359536b71c609d2a6aca408836c8399cbb2bcb948023ff767"),
}


def order_digest(f):
    """The sha256 of the fragment's EMITTED ORDER: each instruction's opcode,
    attribute and operands, a word by its bits and a value by its position."""
    def ref(s):
        return ("w%x" % f.words[s[1]]) if s[0] == "w" else s[0] + str(s[1])
    return hashlib.sha256(repr([(op, r, tuple(ref(s) for s in srcs))
                                for op, r, srcs in f.body]).encode()
                          ).hexdigest()


@functools.lru_cache(maxsize=None)
def tw_build_of(fn, rnd, plant=None, shift=0):
    """ml.build(fn, FP32, rnd, plant=plant, bound_shift=shift), once."""
    return ml.build(fn, FP32, rnd, plant=plant, bound_shift=shift)


@functools.lru_cache(maxsize=None)
def tw_fragment_of(fn, rnd, plant=None, shift=0):
    """The build's scheduled fragment."""
    return tw_build_of(fn, rnd, plant, shift).fragment()


# ---- the pools, the regions, the specials, the structured lanes, seq ----------

def check_pools_tw(f, xs=None, results=None):
    """[finding], Tally: pools. check_pools on the whole pool of f's function
    at fp32 with the model's pinned counts (POOL_SIZES_TW, POOL_MARKS_TW), or
    on `xs` (a part of it) with none."""
    if xs is None:
        return check_pools(f, None, results, POOL_MARKS_TW[(f.op, f.rnd)],
                           POOL_SIZES_TW[f.op])
    return check_pools(f, xs, results)


@functools.lru_cache(maxsize=None)
def regions_tw(fn, n=12, seed=1):
    """{name: lanes}: the function's placed regions at fp32, n lanes each
    (the study's seed): `region` is generic, and returns [] for a region the
    function has none of (powr's negint and negedge)."""
    return {r: tuple(region(FP32, fn, r, n, seed)) for r in REGION_NAMES[fn]}


def check_regions_tw(f, n=12, regions=None, first=None, evaluator=None):
    """[finding], (lanes, marked): regions. check_regions on the fp32 regions
    of `n` lanes (REGION_NAMES' for the function; a region with no lane adds
    none) and the first design's lanes by name."""
    regions = regions_tw(f.op, n) if regions is None else regions
    return check_regions(f, {k: v for k, v in regions.items() if v}, first,
                         evaluator)


def check_specials_tw(fn, frags, evaluator=None, rows=None, marks=None):
    """[finding], lanes: specials. check_specials at fp32 with the model's
    marks (SPECIAL_MARKS_TW)."""
    return check_specials(FP32, fn, frags, evaluator, rows,
                          SPECIAL_MARKS_TW.get(fn, {}) if marks is None
                          else marks)


def structured_rows_tw(fn):
    """[(label, lanes, expectation)] for fn at fp32: structured_rows'
    families (the exact powers of two, y = 1, the tie, beside 1 either side of
    the gate, the exact cases and their neighbours, the negative powers of two)
    and the lanes of the double word's plants that need no plant to build
    (plant_cases builds the lane of bound_loose with that plant, which fp32
    refuses by name): each a `free` lane, or `decided` where plant_cases says
    the design decides it."""
    fmt = FP32
    one = sf.one_bits(fmt)
    q = sf.qnan_bits(fmt)

    def v(s, m, e):
        return _V(fmt, s, m, e)
    rows = [("exact powers of two (2^n, 0.5^n, integer t, both signs of n)",
             _exact_pow2(fmt), "decided"),
            ("y = 1: x itself", [(x, one) for x in (
                v(0, 3, 0), v(0, 5, -7), sf.min_subnormal_bits(fmt),
                sf.max_normal_bits(fmt))], "decided"),
            ("the tie at half the least subnormal (pow(2, emin - p))",
             [(_pow2_bits(fmt, 1), _enc(fmt, fmt.emin - fmt.prec))],
             "decided")]
    below, above = _beside_one(fmt)
    rows += [("beside 1, t below 2^-(p+3) (the gate, both signs of y)", below,
              "decided"),
             ("beside 1, t above the gate", above, "free")]
    exact, neigh = _exact_families(fmt)
    # (3 +- ulp)^2 is a midpoint to within u^2 = 2^-44, which the double word's
    # bound 2^-(p+G) |V| (2^-97 at fp64) covers and the triple word's 2^-64 |V|
    # does not: at fp32 the neighbours in x are decided too, so there is no
    # "midpoint" row (MEASURED: row 3^2's neighbours, 2 of 2 lanes unmarked)
    rows += [("exact cases that must mark by family", [ln for _, ln in exact],
              "marked"),
             ("their neighbours one ulp of x or y away",
              [ln for _n, ln in neigh], "nearest")]
    free = [("plant exact_unmarked (lane)", (v(0, 3, 0), v(0, 2, 0))),
            ("plant exact_unmarked (lane)", (v(0, 10, 0), v(0, 3, 0))),
            ("plant exact_rule_no_tl (lane)", _notl_lane(fmt)),
            ("plant pow_zero_nan (lane)", (q, 0)),
            ("plant pow_one_nan (lane)", (one, q)),
            ("plant sign_even (lane)", (_enc(fmt, Fraction(-11, 10)),
                                        v(0, 2, 0))),
            ("plant sign_odd_lost (lane)", (_enc(fmt, Fraction(-11, 10)),
                                            v(0, 3, 0))),
            ("plant zero_sign_lost (lane)", _zero_lane(fmt)),
            ("plant integrality_wide (lane)",
             ((one + 1) | fmt.sign_mask, v(0, (1 << (fmt.prec - 2)) + 1, 0))),
            ("plant side_rule_off (lane)", (_enc(fmt, Fraction(6, 5)),
                                            sf.min_subnormal_bits(fmt))),
            ("plant side_rule_off (lane)", (_enc(fmt, Fraction(5, 6)),
                                            sf.min_subnormal_bits(fmt))),
            ("plant screen_low (lane)", _screen_lane(fmt))]
    if fn == "powr":
        free += [("plant powr_neg_ok (lane)", (v(1, 1, 1), v(0, 1, -1))),
                 ("plant powr_zero_zero (lane)", (0, 0))]
    decided = [("plant exact_rule_off (mark)", (v(0, 1, 1), v(0, 10, 0))),
               ("plant exact_rule_off (mark)", (v(0, 1, -1), v(0, 3, 0))),
               ("plant near_one_gate_off (mark)", (one + 1, v(0, 1, -60)))]
    rows += [(lab, [ln], "free") for lab, ln in free if ln is not None]
    rows += [(lab, [ln], "decided") for lab, ln in decided]
    if fn == "pow":
        rows.append(("negative powers of two, the sign by y's parity",
                     _exact_pow2_neg(fmt), "decided"))
    return rows


def seq_lanes_tw(fn, stride=16):
    """The lanes of the seq check: every `stride`th lane of the function's pool
    at fp32, every structured lane and SEQ_LOUD's."""
    out = list(pool(fn, FP32)[::stride])
    for _label, lanes, _e in structured_rows_tw(fn):
        out += lanes
    out += SEQ_LOUD(FP32)
    return tuple(dict.fromkeys(out))


def check_structured_tw(f, evaluator=None, rows=None):
    """[finding], lanes: structured, at fp32 (check_structured on
    structured_rows_tw)."""
    return check_structured(f, evaluator, structured_rows_tw(f.op)
                            if rows is None else rows)


def check_seq_tw(f, xs=None, stride=16, **kw):
    """[finding], lanes: seq. check_seq on f at fp32 over seq_lanes_tw (every
    `stride`th pool lane, the structured lanes and the loud ones) with the
    structured rows' marked lanes. The bound is not inflated: the byte's mark
    is exercised by the exact cases that must mark (a row of "marked"), and a
    run that marks no lane is a finding of check_seq's (STATUS[6])."""
    rows = structured_rows_tw(f.op)
    xs = seq_lanes_tw(f.op, stride) if xs is None else xs
    return check_seq(f, xs=list(xs), rows=rows, **kw)


# ---- the bound: V0 + V1 + V2 against mpmath ------------------------------------

def bound_log2_tw(b, lane):
    """log2(|V - f 2^-k| / Bv) for one main-path lane of the fp32 build b: V
    the sum of its probes V0, V1 and V2 (the result in the scaled domain, the
    sign applied; the final multiplications by 2^k1 and 2^k2 are after it,
    k = floor(n/8), n the probe nf), the true value from mpmath at 4p + 200
    bits. None where V is exact or the screens take the lane; 999.0 where V is
    not finite. fp32 has no budget in this build (as M4F1's did not): this is
    the direct error, and the model's measured margin carries over because
    the port equals the model."""
    fmt = b.fmt
    _res, _fl, pr = b.run(lane, ("V0", "V1", "V2", "Bv", "th0", "nf"))
    if _screened(fmt, pr):
        return None
    try:
        V = (value(fmt, pr["V0"]) + value(fmt, pr["V1"])
             + value(fmt, pr["V2"]))
        Bv = abs(value(fmt, pr["Bv"]))
    except ValueError:
        return 999.0
    with mpmath.workprec(4 * fmt.prec + 200):
        k = int(value(fmt, pr["nf"])) // 8
        err = abs(_mp(V) - true_value(b.meta["fn"], fmt, lane)
                  * mpmath.mpf(2) ** -k)
        if err == 0:
            return None
        return float(mpmath.log(err / _mp(Bv), 2))


def check_bound_tw(b, lanes, label="random", need=1):
    """[finding], (worst log2(err/Bv), main-path lanes, lanes): bound. Every
    main-path lane of `lanes` under 1 Bv (bound_log2_tw), and every lane equal
    to transcend.py in bits and flag word or marked; fewer than `need`
    main-path lanes is a finding (the region measures nothing: BOUND_NO_MAIN's
    are exempt, and the caller says NOT MEASURED, with the lane count, and
    keeps the region out of its pass count). The worst is the largest found, a
    sampled lower bound."""
    fmt, fn = b.fmt, b.meta["fn"]
    worst, n, over, differ = -1e9, 0, [], []
    for lane in lanes:
        res, fw, pr = b.run(lane, ("th0",))
        if not fw & MARK and (res, fw) != golden(fmt, b.rnd, lane, fn):
            differ.append(lane)
        if not in_main(fn, fmt, lane) or _screened(fmt, pr):
            continue
        r = bound_log2_tw(b, lane)
        n += 1
        if r is None:
            continue
        worst = max(worst, r)
        if r >= 0:
            over.append((r, lane))
    where = f"bound: {fn} {fmt.name} {sf.RND_NAMES[b.rnd]} {label}"
    out = []
    if n < need and label.split()[0] not in BOUND_NO_MAIN:
        out.append(f"{where}: only {n} of {len(lanes)} lanes reach the main "
                   f"path, {need} wanted: the region measures nothing")
    if over:
        r, lane = max(over)
        out.append(f"{where}: {len(over)} of {n} main-path lanes are past the "
                   f"bound, the worst {_hexes([lane])} at 2^{r:+.2f} of Bv")
    if differ:
        out.append(f"{where}: {len(differ)} unmarked lanes differ from "
                   f"transcend.{fn}, first {_hexes([differ[0]])}")
    return out, (worst, n, len(lanes))


def bound_regions_tw(b, n=48, seed=11, regions=None):
    """[finding], {region: (worst, main-path lanes, lanes)}: bound over the
    function's placed regions at fp32 (placed_points: n points each; a region
    with no lane at all is not in it, and not_measured_tw names it). A region
    whose lanes reach the main path in none is NOT MEASURED: it is in the dict
    with 0 main-path lanes, and the caller prints it so, outside the pass
    count."""
    fn = b.meta["fn"]
    regions = (regions if regions is not None
               else dict(placed_points(fn, FP32, n, seed)))
    out, worst = [], {}
    for label, xs in regions.items():
        found, w = check_bound_tw(b, xs, label)
        out += found
        worst[label] = w
    return out, worst


def not_measured_tw(fn, worst):
    """[(region, main-path lanes)] of the regions of `fn` that measured
    NOTHING: those with 0 main-path lanes in `worst`, and those the function
    has no lane of at all (powr's negint and negedge, at 0). They are outside
    any pass count."""
    out = [(name, w[1]) for name, w in worst.items() if w[1] == 0]
    out += [(name, 0) for name in ("negint", "negedge")
            if name not in REGION_NAMES.get(fn, ()) or name not in worst]
    return sorted(set(out))


# ---- the shape, the registers, the port ------------------------------------------

def model_phases_tw(fn, fmt_name, rnd):
    return dict(PHASES_TW[(fn, rnd)])


def tables_tw(**kw):
    """The shape check's pinned data at fp32 (Tables), one attribute a table."""
    shape = {(fn, "fp32"): [SHAPE_TW[(fn, rnd)] for rnd in RND_MODES]
             for fn in TW_FUNS}
    eft = {(fn, "fp32"): EFT_TW[(fn, RNE)] for fn in TW_FUNS}
    return Tables(**dict({"shape": shape, "eft": eft,
                          "phases": model_phases_tw}, **kw))


def highest_register(prog):
    """The highest register an instruction of the program names: the
    destination of an ALU instruction, a register operand of one, and the
    register a DEPOSIT or RAISE reads."""
    top = 0
    for w in prog.insns:
        d = seq.decode(w)
        if not d["ctrl"]:
            top = max(top, d["rd"])
            for r, k in (("ra", "ka"), ("rb", "kb"), ("rc", "kc")):
                if not d[k]:
                    top = max(top, d[r])
        elif d["op"] in (seq.DEPOSIT, seq.RAISE):
            top = max(top, d["ra"])
    return top


def check_registers_tw(fn, frags, top=None):
    """[finding]: shape. routines.program accepts the fragment of `fn` under
    each attribute of `frags` {rnd: Fragment}, its highest register is
    REG_TOP_TW's (31 for pow, 28 for powr), and POW_LIVE_CAP's fp32 row is the
    most values live under any attribute (32 and 29; 30 less the cap is -2 and
    +1)."""
    top = REG_TOP_TW[fn] if top is None else top
    out = []
    for rnd, f in frags.items():
        where = f"shape: {fn} fp32 {sf.RND_NAMES[rnd]}"
        try:
            prog, _bank = routines.program(f)
        except AssertionError as e:
            out.append(f"{where}: routines.program refuses it: {e}")
            continue
        got = highest_register(prog)
        if got != top:
            out.append(f"{where}: the highest register is r{got}, pinned "
                       f"r{top}")
    cap = max(f.live_max() for f in frags.values())
    if ml.POW_LIVE_CAP[fn]["fp32"] != cap:
        out.append(f"shape: {fn} fp32: POW_LIVE_CAP is "
                   f"{ml.POW_LIVE_CAP[fn]['fp32']}, the most values live "
                   f"under any attribute is {cap}")
    return out


def check_port_tw(fn, builds, digests=None, fragments=None):
    """[finding]: port. The Build's dag_digest (the design's order), the
    scheduled fragment's dag_digest and its emitted order, each against the
    model's literal (DIGESTS_TW); every instruction's label a name of
    _POW_TW_PHASE_MAP whose phase is the one it was built in, a PHASE_ORDER
    name; the instructions by study part (PARTS_TW). `builds` {rnd: Build},
    `digests` stands for the table, `fragments` {rnd: Fragment} for the
    builds' own scheduled fragments (both for the tests that doctor one
    leg)."""
    digests = DIGESTS_TW if digests is None else digests
    out = []
    for rnd, b in builds.items():
        where = f"port: {fn} fp32 {sf.RND_NAMES[rnd]}"
        f = fragments[rnd] if fragments else b.fragment()
        got = (ml.dag_digest(b.fragment(schedule=False)), ml.dag_digest(f),
               order_digest(f))
        for what, g, w in zip(("the Build's dag digest",
                               "the scheduled fragment's dag digest",
                               "the emitted order"), got, digests[(fn, rnd)]):
            if g != w:
                out.append(f"{where}: {what} is {g[:16]}, the model's is "
                           f"{w[:16]}")
        keep = b.live_indices()
        if len(b.label_of) != len(b.body):
            out.append(f"{where}: {len(b.label_of)} labels for "
                       f"{len(b.body)} instructions")
            continue
        # the map is the study's (label -> scheduled phase), by name; the
        # instruction's own phase is what it was built in (the five of the
        # bound's coefficient carry the label "test" and the phase head2)
        bad = [i for i in keep
               if ml._POW_TW_PHASE_MAP.get(b.label_of[i]) not in ml.PHASE_ORDER
               or b.phase_of[i] not in ml.PHASE_ORDER]
        if bad:
            out.append(f"{where}: {len(bad)} instructions whose label maps "
                       f"to no PHASE_ORDER name or whose phase is not in "
                       f"PHASE_ORDER, first {b.label_of[bad[0]]!r}")
        parts = dict(collections.Counter(ml._POW_TW_PARTS[b.label_of[i]]
                                         for i in keep))
        if parts != PARTS_TW[(fn, rnd)]:
            out.append(f"{where}: instructions by part {parts}, the model's "
                       f"{PARTS_TW[(fn, rnd)]}")
    return out


def check_shape_tw(fn, builds=None, tables=None, fragments=None):
    """[finding]: shape. check_shape on fn at fp32 under all five attributes
    with tables_tw() (instructions, bank words and live per fragment; the
    instructions by phase and the Fast2Sum and TwoSum counts the model's; the
    flag word's nine values; MIN and MAX none; the scheduled fragment the
    design's reordered; POW_LIVE_CAP's fp32 row the measured maximum, and a cap
    one under failing by name), then the registers (check_registers_tw) and the
    port (check_port_tw). `fragments` {rnd: Fragment} stands for the builds'
    own, for the test that doctors one."""
    builds = builds or {rnd: tw_build_of(fn, rnd) for rnd in RND_MODES}
    out = check_shape(FP32, {(fn, rnd): b for rnd, b in builds.items()},
                      tables or tables_tw(),
                      {(fn, rnd): f for rnd, f in (fragments or {}).items()}
                      or None)
    frags = fragments or {rnd: b.fragment() for rnd, b in builds.items()}
    out += check_registers_tw(fn, frags)
    out += [f"shape: {s}" for s in check_port_tw(fn, builds,
                                                   fragments=fragments)]
    return out


# ---- the constants ---------------------------------------------------------------

def check_constants_tw(**kw):
    """[finding], lines: constants. mathlib.check_pow_tw_constants() in
    process."""
    lines, findings = ml.check_pow_tw_constants(**kw)
    return [f"constants: {s}" for s in findings], lines


def check_constants_cli_tw():
    """[finding], output: constants. `python -m cft_golden.mathlib --check
    --only pow-tw` in a process of its own, exit 0 and its last line ending
    `0 differences`, listing pow and powr."""
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--check", "--only", "pow-tw"], capture_output=True,
                       text=True, cwd=ROOT / "python")
    out = r.stdout.strip().splitlines()
    findings = []
    if r.returncode != 0:
        findings.append(f"constants: --check --only pow-tw exited "
                        f"{r.returncode}")
    want = (f"mathlib --check (pow, triple word): {len(ml._POW_TW_BUILDERS)} "
            f"routines, 1 format, 0 differences")
    if not out or out[-1] != want:
        findings.append(f"constants: the last line is "
                        f"{out[-1] if out else r.stderr[-200:]!r}, not "
                        f"{want!r}")
    n = sum(1 for ln in out if ln.split(" ")[0] in ml._POW_TW_BUILDERS
            and "(triple word)" in ln)
    if n != len(ml._POW_TW_BUILDERS):
        findings.append(f"constants: {n} routine lines, "
                        f"{len(ml._POW_TW_BUILDERS)} wanted")
    return findings, out


# ---- the plants: every check on every plant ----------------------------------------

def red_checks_tw(plant, fn="pow", rnds=(RNE,), region_n=6, bound_n=6,
                  seq_stride=192, pool_step=4, struct_rnds=(RNE,),
                  shift=0):
    """{check: [findings]} for CHECKS_TW, EVERY key present (a check that is
    green has an empty list), on `plant` (None: the control) at fp32 on `fn`:
    pools over every `pool_step`th lane of the pool (1: the whole pool and its
    pinned counts; a step above 1 drops the count pins, which the whole-pool
    check holds) and regions and specials under `rnds`, structured under
    `struct_rnds`, seq under the first of `rnds` (every `seq_stride`th lane of
    the pool, the structured lanes and the loud ones), bound over the placed
    regions (bound_n points each) under rne, shape under all five (where the
    plant reaches all five) and constants under rne. A plant the build cannot
    reach is refused by name. GREEN means green at this scope, which is smaller
    than the tests' own on the control."""
    red = {name: [] for name in CHECKS_TW}
    reach = []
    for rnd in RND_MODES:
        try:
            tw_build_of(fn, rnd, plant, shift)
        except ValueError as e:
            if "does not apply" not in str(e):
                raise
            continue
        reach.append(rnd)
    if not reach:
        raise ValueError(f"plant {plant!r} does not apply to {fn} at fp32 "
                         f"under any attribute")
    rnds = tuple(r for r in rnds if r in reach) or (reach[0],)
    for rnd in rnds:
        f = tw_fragment_of(fn, rnd, plant, shift)
        red["pools"] += check_pools_tw(
            f, None if pool_step == 1 else list(pool(fn, FP32)[::pool_step])
        )[0]
        red["regions"] += check_regions_tw(f, region_n)[0]
    red["specials"] += check_specials_tw(
        fn, {rnd: tw_fragment_of(fn, rnd, plant, shift) for rnd in rnds})[0]
    for rnd in struct_rnds:
        if rnd in reach:
            red["structured"] += check_structured_tw(
                tw_fragment_of(fn, rnd, plant, shift))[0]
    red["seq"] += check_seq_tw(tw_fragment_of(fn, rnds[0], plant, shift),
                               stride=seq_stride)[0]
    b = tw_build_of(fn, RNE, plant, shift)
    for r, lanes in placed_points(fn, FP32, bound_n).items():
        red["bound"] += check_bound_tw(b, lanes, r)[0]
    if len(reach) == len(RND_MODES):
        red["shape"] += check_shape_tw(
            fn, {rnd: tw_build_of(fn, rnd, plant, shift)
                 for rnd in RND_MODES})
    red["constants"] += check_constants_tw(
        builder=lambda name, f_, r_: tw_build_of(name, r_, plant, shift),
        attrs=(RNE,), names=(fn,))[0]
    return red


# the sizes of mathlib_runs.py's pow commands at fp32: the model's regions of
# 300 lanes (pow-pools) and, for pow-bound, 1,000 points a region
REGION_LANES_TW = {"pow": 300, "powr": 300}
BOUND_POINTS_TW = 1000


# ---- fp32: pown and rootn (parcel M3F2) ----
#
# pown and rootn at fp32 are the triple word of pow and powr with n a constant of
# the fragment; the harness of the double word's n-keyed checks (INT_FUNCS, from
# line 1620: pool_n, region_n, special_rows_n, structured_rows_n, check_seq_n,
# check_shape_n, check_caps_n) is format-generic where it reads no table with
# no fp32 key (ZONE_BIG, REGION_LANES, POOL_MARKS_N and SPECIAL_MARKS_N are not
# read at fp32: the wrappers below pass their own, or refuse by name), and is
# called here at FP32. Every pin is the MODEL's (docs/studies/m3/pw32n.py,
# parcel M3XN: MEASURED on its builds, scheduled, over the n list at the five
# attributes, and equal on this build's: the port was shown equal to it by dag
# digest, emitted order and on lanes), not computed from the code under test.

TW_N_FUNS = ("pown", "rootn")
_TW_N_COMMON = (2, -2, 3, -3, 17, 2 ** 31 - 1, -2 ** 63, 1000, 2 ** 24 + 1,
                2 ** 40, 2 ** 48 + 1)
# the n of each function's checks: the sweeps' seven, 1000, 2^24 + 1 (two words),
# 2^40 (a power of two: one word), 2^48 + 1 (two words), 2^62 + 2^37 + 1 (three
# words, pown only: rootn's 1/n has three words at every n that is not a power
# of two), and n = 0 and 1 (the small fragments; rootn's 0 is refused by name)
TW_N_NS = {"pown": _TW_N_COMMON + (2 ** 62 + 2 ** 37 + 1, 0, 1),
           "rootn": _TW_N_COMMON + (1,)}
# the n beside the list at which the registers and caps are shown too
# (VM3XN's: 28 and 27 live at an odd n, one fewer at an even)
TW_N_CAP_EXTRA_NS = (5, 2 ** 35 + 7)
CHECKS_TW_N = ("pools", "regions", "specials", "structured", "seq", "bound",
               "shape", "constants")
# the box's regions (the model's regions.py at fp32): int<N> at n = N, zone at
# n = 3, zone<N> at n = N; n = 2 and -2 have no region at all
REGION_NAMES_TW_N = ("int", "int-neg", "int17", "int31", "int63", "int1000",
                     "int16777217", "int1099511627776",
                     "int281474976710657", "zone", "zone1000", "zone-3",
                     "zone17")
# the lanes a region at the box's size (pw32n_box.sh: 12,000)
REGION_LANES_TW_N = {"pown": 12000, "rootn": 12000}
# a region whose lanes the screens may all take (the model's: pown's n = 2^31 - 1
# and up, rootn's 2^40 and up; int63 is the double word's too): none of them is
# a finding, each is NOT MEASURED when it measures nothing
BOUND_NO_MAIN_TW_N = {"int31", "int63", "int1099511627776",
                      "int281474976710657"}

PINS_TW_N = {
    ('pown', 'fp32', 'rne', 2): (865, 138, 27, 'fda9d17725e1493de1f2047fee6dfc32', '476680b4a258bd75'),
    ('pown', 'fp32', 'rtz', 2): (858, 139, 27, '4cc2f971929cdcdadb6a7d0281c4421e', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rdn', 2): (858, 139, 27, '063e75db2cf7f6e4493e2a709a1454d9', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rup', 2): (858, 138, 27, 'fd89017949542788d55d33cb885b6055', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rmm', 2): (865, 138, 27, '2698bce4fa2adc7da07e7bb7db305b75', '476680b4a258bd75'),
    ('pown', 'fp32', 'rne', -2): (865, 138, 27, '9606f30bfe46d5bd442ae85f2c56cbfe', '476680b4a258bd75'),
    ('pown', 'fp32', 'rtz', -2): (859, 139, 27, '4aecdfd3c498090c5df3974bce5ba8cf', '2db81b7aa85e531c'),
    ('pown', 'fp32', 'rdn', -2): (859, 139, 27, 'ca8fd268f65b46051bd3a728e326af80', '2db81b7aa85e531c'),
    ('pown', 'fp32', 'rup', -2): (859, 138, 27, '1f6d76c1352a1b2a6979ed0e6a433382', '2db81b7aa85e531c'),
    ('pown', 'fp32', 'rmm', -2): (865, 138, 27, '12ed4ffe3479846bf65a3f0e7edc8040', '476680b4a258bd75'),
    ('pown', 'fp32', 'rne', 3): (877, 142, 28, 'e556cd310d28002e669250f940507370', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rtz', 3): (871, 144, 28, '6b802ac033b519092bda458560c9698b', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rdn', 3): (871, 145, 28, 'e4eee54928baad9e75e18dc7de631809', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rup', 3): (871, 143, 28, 'b9b99f5a8e6f08806e752e1aec31f992', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rmm', 3): (877, 142, 28, '3d40c34e05e364bb45ef5ad6376756ae', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rne', -3): (877, 142, 28, 'ecfee621e6606fbae95414eff7a0e3bc', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rtz', -3): (872, 144, 28, 'c375bc4b3d35ee7a30efaae01d143d46', 'd08566ed24c8e3f3'),
    ('pown', 'fp32', 'rdn', -3): (872, 145, 28, '87e4cda0c4d92ea75190f5cd75f8ad6f', 'd08566ed24c8e3f3'),
    ('pown', 'fp32', 'rup', -3): (872, 143, 28, 'ab379b4f24ad3968a805e7ac59a2db8f', 'd08566ed24c8e3f3'),
    ('pown', 'fp32', 'rmm', -3): (877, 142, 28, '505ba9f1a43b0adc8ec53a4a80e88dd5', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rne', 17): (877, 142, 28, 'a380b25e01daf76c48398640db89a17b', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rtz', 17): (871, 144, 28, 'd44ddc26510d4f148eb87b6512f7e674', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rdn', 17): (871, 145, 28, 'af027de776ca0cd6187e4422a11d687d', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rup', 17): (871, 143, 28, '624b4acf30690c46434a352e4e56949c', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rmm', 17): (877, 142, 28, 'de7fcfc3dae70cb1430e36b4d3de5c64', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rne', 2147483647): (889, 142, 28, 'ce89c8e36764ca7a6a77987257f9aef6', '1f61c7fbe610b845'),
    ('pown', 'fp32', 'rtz', 2147483647): (883, 144, 28, '0b7662292653de326eda3c160fd7bc59', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rdn', 2147483647): (883, 145, 28, '029ad9851cf7f4ffe6bc4cb634ddc50f', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rup', 2147483647): (883, 143, 28, 'c6220f6b448a055ef195eec2e58da3b1', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rmm', 2147483647): (889, 142, 28, 'adc9867d5d65370bbc364dba565925f9', '1f61c7fbe610b845'),
    ('pown', 'fp32', 'rne', -9223372036854775808): (865, 138, 27, '21c3e47b208952c7087edffa1a35baf1', '476680b4a258bd75'),
    ('pown', 'fp32', 'rtz', -9223372036854775808): (859, 139, 27, '8d7339120d7bf823dd2540a5ab7e7402', '2db81b7aa85e531c'),
    ('pown', 'fp32', 'rdn', -9223372036854775808): (859, 139, 27, '090acbe5cc4074578f48507c06b772d4', '2db81b7aa85e531c'),
    ('pown', 'fp32', 'rup', -9223372036854775808): (859, 138, 27, '1b4f8e9a6b06ed3c676daaf39ee63abc', '2db81b7aa85e531c'),
    ('pown', 'fp32', 'rmm', -9223372036854775808): (865, 138, 27, 'decb3a453140bb078c344639dec75eca', '476680b4a258bd75'),
    ('pown', 'fp32', 'rne', 1000): (865, 139, 27, 'a1fb24e3e0dbfcac2c6b7e24fb8e03c9', '476680b4a258bd75'),
    ('pown', 'fp32', 'rtz', 1000): (858, 140, 27, '430bcfe7decb31b8bb1311fc5a3bb8a9', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rdn', 1000): (858, 140, 27, '7015a94fde809317ee6fce2bcfa4aecd', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rup', 1000): (858, 139, 27, '1d79ec5a94aff7997e8b03c613ce2adc', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rmm', 1000): (865, 139, 27, 'b91d0116e034522f9133ea556098d17c', '476680b4a258bd75'),
    ('pown', 'fp32', 'rne', 16777217): (889, 141, 28, '5fe58be5d54c4fe196cee25dd01519ad', '1f61c7fbe610b845'),
    ('pown', 'fp32', 'rtz', 16777217): (883, 143, 28, '3b4f572b765fa8e2ede5579828f60a90', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rdn', 16777217): (883, 144, 28, '222b3badbd4693f78e6404efb1433017', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rup', 16777217): (883, 142, 28, '100c185b2c8bef09858c5b87c7ab931f', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rmm', 16777217): (889, 141, 28, '90c9c1827404535f21c85ddc17ec15be', '1f61c7fbe610b845'),
    ('pown', 'fp32', 'rne', 1099511627776): (865, 138, 27, '2e81f136433dbcd514decb0b2057d77a', '476680b4a258bd75'),
    ('pown', 'fp32', 'rtz', 1099511627776): (858, 139, 27, '88f3f1ab585b3a0021f316b07621d341', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rdn', 1099511627776): (858, 139, 27, 'b58a659d48735f758b58e74ad5b58d2d', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rup', 1099511627776): (858, 138, 27, '2b140d72b974bdc0380b3739b7ef3966', '6be8d199c1d83a4c'),
    ('pown', 'fp32', 'rmm', 1099511627776): (865, 138, 27, '265f10f4b987778506e53a0fb4aa1501', '476680b4a258bd75'),
    ('pown', 'fp32', 'rne', 281474976710657): (889, 142, 28, 'b80ffeaa6bcb0ba8b548a64279e5f9af', '1f61c7fbe610b845'),
    ('pown', 'fp32', 'rtz', 281474976710657): (883, 144, 28, 'a5bb3809c2a1f5cbe14a3ce5e7c25351', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rdn', 281474976710657): (883, 145, 28, '5774b7b26c6a03fecd6bc2c3143523bf', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rup', 281474976710657): (883, 143, 28, 'cddd2b8fba8d10c91d37536770d576d8', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rmm', 281474976710657): (889, 142, 28, '05167dc349c7cf2f632b17c93b804b83', '1f61c7fbe610b845'),
    ('pown', 'fp32', 'rne', 4611686155866341377): (891, 143, 28, '662d0f8339eb6dddef00e4b6c84c7c39', '8016f383a4da5b63'),
    ('pown', 'fp32', 'rtz', 4611686155866341377): (885, 145, 28, '651f1a4ab5a293673c34b5cf8abdc9c1', '7d66182f39d0b3a8'),
    ('pown', 'fp32', 'rdn', 4611686155866341377): (885, 146, 28, '9a112173fe7ca5335867747d0fd9853b', '7d66182f39d0b3a8'),
    ('pown', 'fp32', 'rup', 4611686155866341377): (885, 144, 28, '944b40f6bd8ab2847f632817954401b6', '7d66182f39d0b3a8'),
    ('pown', 'fp32', 'rmm', 4611686155866341377): (891, 143, 28, '1b742ebd5c247a0b2fe83aa255a6c402', '8016f383a4da5b63'),
    ('pown', 'fp32', 'rne', 0): (6, 7, 2, '1480c8b2218e2222317bea6b8b42cfff', '9286480e7da5e680'),
    ('pown', 'fp32', 'rtz', 0): (6, 7, 2, '1480c8b2218e2222317bea6b8b42cfff', '9286480e7da5e680'),
    ('pown', 'fp32', 'rdn', 0): (6, 7, 2, '1480c8b2218e2222317bea6b8b42cfff', '9286480e7da5e680'),
    ('pown', 'fp32', 'rup', 0): (6, 7, 2, '1480c8b2218e2222317bea6b8b42cfff', '9286480e7da5e680'),
    ('pown', 'fp32', 'rmm', 0): (6, 7, 2, '1480c8b2218e2222317bea6b8b42cfff', '9286480e7da5e680'),
    ('pown', 'fp32', 'rne', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('pown', 'fp32', 'rtz', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('pown', 'fp32', 'rdn', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('pown', 'fp32', 'rup', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('pown', 'fp32', 'rmm', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('pown', 'fp32', 'rne', 5): (877, 142, 28, 'fb8ed0e6a125ceb33012f9d56e5f9823', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rtz', 5): (871, 144, 28, '954dadea55b8c29f72c21500f6ac8f75', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rdn', 5): (871, 145, 28, '705a222c67b623de17b9334e7c72af36', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rup', 5): (871, 143, 28, 'f25f90af9d2bdb4920012869dc38339b', 'bccb3d99fe0a8ff0'),
    ('pown', 'fp32', 'rmm', 5): (877, 142, 28, '64f863b482deb1720050ea1d0d341c15', 'faa1a644b6b3dc39'),
    ('pown', 'fp32', 'rne', 34359738375): (889, 143, 28, '35d340689eeddfddee8e1134497d7bae', '1f61c7fbe610b845'),
    ('pown', 'fp32', 'rtz', 34359738375): (883, 145, 28, 'e9e12105382b0ee5d61eb88f1138f4b1', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rdn', 34359738375): (883, 146, 28, '5351b32d726373d600d488d4b12c2a3a', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rup', 34359738375): (883, 144, 28, '654c0c51afd83f70b60e5be72df19636', '36c0fe7898d54036'),
    ('pown', 'fp32', 'rmm', 34359738375): (889, 143, 28, 'd910ddfd49b58863784503d83237d15a', '1f61c7fbe610b845'),
    ('rootn', 'fp32', 'rne', 2): (871, 139, 26, 'd856f1ce5ae59a4a162f015eb9015e07', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rtz', 2): (864, 140, 26, '1e7d14cf1ec7dae21a467a6b9221b133', 'f7ffaf9abe436f64'),
    ('rootn', 'fp32', 'rdn', 2): (864, 140, 26, 'b5af3d4c2548dce2c4fb35f71f8a4aac', 'f7ffaf9abe436f64'),
    ('rootn', 'fp32', 'rup', 2): (864, 139, 26, '661abae5c73114e88da1a2fdd47f1bf5', 'f7ffaf9abe436f64'),
    ('rootn', 'fp32', 'rmm', 2): (871, 139, 26, '9a4160873488154d53bf1fa5da66252e', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rne', -2): (871, 139, 26, 'b74898cb6fe9311a1034febbefca5742', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rtz', -2): (865, 140, 26, '618bdc92143aa53e4afe0431c33b7429', '2c87253033971e57'),
    ('rootn', 'fp32', 'rdn', -2): (865, 140, 26, '990691c0af2ec2c5cd53df1ce2509b56', '2c87253033971e57'),
    ('rootn', 'fp32', 'rup', -2): (865, 139, 26, '5a180183472c717255b1c05a20e34846', '2c87253033971e57'),
    ('rootn', 'fp32', 'rmm', -2): (871, 139, 26, 'cf7ea225c2ff7235d0c052b411c4424d', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rne', 3): (892, 141, 27, 'ecf7fd41cb6cc73686988f27bd2b517a', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', 3): (886, 143, 27, '15036d4c7e745db09a823aefc5ad55e3', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rdn', 3): (886, 144, 27, 'e35209057f0f2303915eb9b76d601c2b', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rup', 3): (886, 142, 27, '9b918fa968ce446c8a0a8b9c0ecb2755', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rmm', 3): (892, 141, 27, 'b6b95e22d2324a7849a30f66b7e57963', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rne', -3): (892, 144, 27, '7f9742e720258faffffd24c125a11942', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', -3): (887, 146, 27, '7c5026790f185604834f120d0bfa222b', 'deaca6652505a500'),
    ('rootn', 'fp32', 'rdn', -3): (887, 147, 27, 'aba0d4f421e527fc1d903d855bccb7f4', 'deaca6652505a500'),
    ('rootn', 'fp32', 'rup', -3): (887, 145, 27, 'fee09a06a2307f341aea2bce9282ec0d', 'deaca6652505a500'),
    ('rootn', 'fp32', 'rmm', -3): (892, 144, 27, '27b8c88ae49db16a2d4d435052017763', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rne', 17): (892, 143, 27, '3144a3d7f2f8673025f4d34c3f22e355', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', 17): (886, 145, 27, '19dd886e21cae54a3c2e15b2913e2f0c', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rdn', 17): (886, 146, 27, 'ca641208cb705ac1e39e8cf893f02503', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rup', 17): (886, 144, 27, '254f663e33296cc9b2cf7942510f2549', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rmm', 17): (892, 143, 27, '8210dfabaa05a71b95d445bfd91f48c1', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rne', 2147483647): (892, 144, 27, 'd41396711fbc36505342d3e52732ee42', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', 2147483647): (886, 146, 27, 'ed29dd82b6d714392b327a59ca59ffc7', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rdn', 2147483647): (886, 147, 27, '4db5c2a7eff6d57649161ff1c0dc69a8', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rup', 2147483647): (886, 145, 27, 'd6ecb3ee538884784fdced943be7453e', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rmm', 2147483647): (892, 144, 27, '684d85c5ebd82d8552f442ca03cfc88e', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rne', -9223372036854775808): (871, 140, 26, 'de17fb7b47a96dccad034b17336ca165', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rtz', -9223372036854775808): (865, 141, 26, '7cd5c8be636886645b258111a14615e5', '2c87253033971e57'),
    ('rootn', 'fp32', 'rdn', -9223372036854775808): (865, 141, 26, '51dd8b793b9311c5c82161a40143b766', '2c87253033971e57'),
    ('rootn', 'fp32', 'rup', -9223372036854775808): (865, 140, 26, '7cd6fb8272aeb65d5a2957d6939ca96b', '2c87253033971e57'),
    ('rootn', 'fp32', 'rmm', -9223372036854775808): (871, 140, 26, '76472311d7e8418f411a9eca941cc52c', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rne', 1000): (885, 142, 26, 'e0ecd3cb612920b3cc28f049ab71cc11', 'e481e0e874799fc8'),
    ('rootn', 'fp32', 'rtz', 1000): (878, 143, 26, '041af3def3a47db65ed8b69a0f045c0a', 'dfe21b195d5f29c9'),
    ('rootn', 'fp32', 'rdn', 1000): (878, 143, 26, '431219af33696886a94eeb1988f81708', 'dfe21b195d5f29c9'),
    ('rootn', 'fp32', 'rup', 1000): (878, 142, 26, '917602cc7b8ab93773629a181a4fceed', 'dfe21b195d5f29c9'),
    ('rootn', 'fp32', 'rmm', 1000): (885, 142, 26, '603027fe6ebf57eb0dfe185db7a4b0b9', 'e481e0e874799fc8'),
    ('rootn', 'fp32', 'rne', 16777217): (892, 144, 27, '6b9f003b28867340a104557f9b6c6979', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', 16777217): (886, 146, 27, 'f191c4b87d2ca0e496342bdcf578dfd4', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rdn', 16777217): (886, 147, 27, 'f03100b68c54e2ce6b9111accfd85e2a', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rup', 16777217): (886, 145, 27, 'a5f79f7b374b7997bb0587835143e829', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rmm', 16777217): (892, 144, 27, 'a062690dfefd784b0533eee32ddc850e', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rne', 1099511627776): (871, 140, 26, 'fc2f226be0b489f89f97fceea4012309', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rtz', 1099511627776): (864, 141, 26, '1037c07996fd7ed49441f3ed7588c31e', 'f7ffaf9abe436f64'),
    ('rootn', 'fp32', 'rdn', 1099511627776): (864, 141, 26, '66d862a0b294f385d06f4c949e5dd709', 'f7ffaf9abe436f64'),
    ('rootn', 'fp32', 'rup', 1099511627776): (864, 140, 26, '755e475bf68ee1638f6b00e26cc11b03', 'f7ffaf9abe436f64'),
    ('rootn', 'fp32', 'rmm', 1099511627776): (871, 140, 26, '992fdd7e08480aa6866be02725b732c2', 'baffe940ed5bd31e'),
    ('rootn', 'fp32', 'rne', 281474976710657): (892, 144, 27, 'f72cd2f9441a00d212c7a2b99335edf8', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', 281474976710657): (886, 146, 27, '54e9fb4433ef25ab972a6092ff0f6197', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rdn', 281474976710657): (886, 147, 27, '8e967fddff948b9ebcb03f32a1d1a61e', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rup', 281474976710657): (886, 145, 27, '83739d78098aa9bb0c38c80fb42e2334', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rmm', 281474976710657): (892, 144, 27, 'f0a6f88744158e9e3b9d87b18d55d35e', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rne', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('rootn', 'fp32', 'rtz', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('rootn', 'fp32', 'rdn', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('rootn', 'fp32', 'rup', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('rootn', 'fp32', 'rmm', 1): (6, 6, 3, 'bde8082e862905cd882ad1ab8a8b3e99', '9286480e7da5e680'),
    ('rootn', 'fp32', 'rne', 5): (892, 141, 27, '0d936f0918b3ca8661807c03157ac694', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', 5): (886, 143, 27, 'e38fba233c3f3240e80e840d369eb3d4', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rdn', 5): (886, 144, 27, '506a4d0d6a3822e24bdefbd34ff005ea', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rup', 5): (886, 142, 27, 'd87c9d9958e06c4853793811bba8f73c', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rmm', 5): (892, 141, 27, '10840b3b1533e24d1c3bb16736d41e05', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rne', 34359738375): (892, 144, 27, 'fe4a25ef1d4819b754ebae7d2dc49318', 'b8f78802e61d5e6b'),
    ('rootn', 'fp32', 'rtz', 34359738375): (886, 146, 27, '4e0f4895c6bc6d948bc6b40f568f2092', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rdn', 34359738375): (886, 147, 27, '936b939039fe9652038f15b6022a619d', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rup', 34359738375): (886, 145, 27, '13c51537c0adce8628367ad3197ccbd1', '23fd8459e977db87'),
    ('rootn', 'fp32', 'rmm', 34359738375): (892, 144, 27, '10ae64a28540d839ce36907a2e38448d', 'b8f78802e61d5e6b'),
}
EFT_TW_N = {
    ('pown', 'fp32', 2): (61, 42),
    ('pown', 'fp32', -2): (61, 42),
    ('pown', 'fp32', 3): (61, 42),
    ('pown', 'fp32', -3): (61, 42),
    ('pown', 'fp32', 17): (61, 42),
    ('pown', 'fp32', 2147483647): (63, 42),
    ('pown', 'fp32', -9223372036854775808): (61, 42),
    ('pown', 'fp32', 1000): (61, 42),
    ('pown', 'fp32', 16777217): (63, 42),
    ('pown', 'fp32', 1099511627776): (61, 42),
    ('pown', 'fp32', 281474976710657): (63, 42),
    ('pown', 'fp32', 4611686155866341377): (63, 42),
    ('pown', 'fp32', 0): (0, 0),
    ('pown', 'fp32', 1): (0, 0),
    ('pown', 'fp32', 5): (61, 42),
    ('pown', 'fp32', 34359738375): (63, 42),
    ('rootn', 'fp32', 2): (61, 42),
    ('rootn', 'fp32', -2): (61, 42),
    ('rootn', 'fp32', 3): (63, 42),
    ('rootn', 'fp32', -3): (63, 42),
    ('rootn', 'fp32', 17): (63, 42),
    ('rootn', 'fp32', 2147483647): (63, 42),
    ('rootn', 'fp32', -9223372036854775808): (61, 42),
    ('rootn', 'fp32', 1000): (63, 42),
    ('rootn', 'fp32', 16777217): (63, 42),
    ('rootn', 'fp32', 1099511627776): (61, 42),
    ('rootn', 'fp32', 281474976710657): (63, 42),
    ('rootn', 'fp32', 1): (0, 0),
    ('rootn', 'fp32', 5): (63, 42),
    ('rootn', 'fp32', 34359738375): (63, 42),
}
DIGESTS_TW_N = {
    ('pown', 2, 'rne'): ('fda9d17725e1493de1f2047fee6dfc3236d15ec74d6266d2b18c56e76b5652bd', 'fda9d17725e1493de1f2047fee6dfc3236d15ec74d6266d2b18c56e76b5652bd', '229032a4c42e2df1c4bb9d5c3be7e154cafbd23e1321c0e17be9d43c207e3381'),
    ('pown', 2, 'rtz'): ('4cc2f971929cdcdadb6a7d0281c4421ef52ec8b943736c8426dfb622f4c17bad', '4cc2f971929cdcdadb6a7d0281c4421ef52ec8b943736c8426dfb622f4c17bad', '70a0a3b283c3023dfa13de8f665848a3b4862f4f1adeb197f5f51569ada5d913'),
    ('pown', 2, 'rdn'): ('063e75db2cf7f6e4493e2a709a1454d90fa51ae7f404c58fa8b8ba5b694b5a05', '063e75db2cf7f6e4493e2a709a1454d90fa51ae7f404c58fa8b8ba5b694b5a05', 'e05fbcc99d5642c489f22a88e9ffca71da9de5fba85033201451112f745ba32e'),
    ('pown', 2, 'rup'): ('fd89017949542788d55d33cb885b60554ba427ef3f1fcb3c6dc8f4e38fb3427d', 'fd89017949542788d55d33cb885b60554ba427ef3f1fcb3c6dc8f4e38fb3427d', 'a9738fcf3eb4d7c6f94e9544a23d05082ddb48f6e44ede201ad8b203391b0260'),
    ('pown', 2, 'rmm'): ('2698bce4fa2adc7da07e7bb7db305b757e6f67067ed034df7e1741505f9c7ea5', '2698bce4fa2adc7da07e7bb7db305b757e6f67067ed034df7e1741505f9c7ea5', '7ec92f0d61733b12c59d0fe72666d38886f9c2f43d060b7938d061d5f95afaf3'),
    ('pown', -2, 'rne'): ('9606f30bfe46d5bd442ae85f2c56cbfed12d9a3a72ea67ef387ee32c45ee3a9a', '9606f30bfe46d5bd442ae85f2c56cbfed12d9a3a72ea67ef387ee32c45ee3a9a', '7a3f4658574275b9872be130f8361fde0fe8c56f87ec1eea061082e222430681'),
    ('pown', -2, 'rtz'): ('4aecdfd3c498090c5df3974bce5ba8cf6129f4604483102ab74491e09ec759c1', '4aecdfd3c498090c5df3974bce5ba8cf6129f4604483102ab74491e09ec759c1', 'ea3f2b08a9ca7a423e18f091bd690c58f6d76889d99e5b61df3077b2307f395f'),
    ('pown', -2, 'rdn'): ('ca8fd268f65b46051bd3a728e326af80de13f47cb59aa56ea3e3bce2a2e8f225', 'ca8fd268f65b46051bd3a728e326af80de13f47cb59aa56ea3e3bce2a2e8f225', '1a1c6dc344a194dc561d755228bc285d2cc8e77ba8239318a9daf129ec9ae37d'),
    ('pown', -2, 'rup'): ('1f6d76c1352a1b2a6979ed0e6a43338225379a9bfe53784d060683dba9d2952f', '1f6d76c1352a1b2a6979ed0e6a43338225379a9bfe53784d060683dba9d2952f', '41cafa0eb40aedd1ba4b55683f2a83132b7fc3b41f91d937dff5121adc430109'),
    ('pown', -2, 'rmm'): ('12ed4ffe3479846bf65a3f0e7edc8040c6197bdeb2ffe4c818c4953fb43b37a4', '12ed4ffe3479846bf65a3f0e7edc8040c6197bdeb2ffe4c818c4953fb43b37a4', 'd2943686f943b5f9b74353291a748d31651401753048cb4491210e5f34c16b0d'),
    ('pown', 3, 'rne'): ('e556cd310d28002e669250f940507370038bc36c4d0abc11ede3df58626f3a81', 'e556cd310d28002e669250f940507370038bc36c4d0abc11ede3df58626f3a81', 'c374b01d73cee8dd5d04ac1ead21f5cf926005cc68cd40a35b557e5c3bcbabdf'),
    ('pown', 3, 'rtz'): ('6b802ac033b519092bda458560c9698bf516fd7025eed31af1ef1554144db870', '6b802ac033b519092bda458560c9698bf516fd7025eed31af1ef1554144db870', '917a97f2f0f4e5755499c7bc1808557ddbe997266c756dcbbb37d26b444deb04'),
    ('pown', 3, 'rdn'): ('e4eee54928baad9e75e18dc7de63180943bc46ea0815044ed2ccc730737ec980', 'e4eee54928baad9e75e18dc7de63180943bc46ea0815044ed2ccc730737ec980', '454c1ee4223a39e1ca097d60c82ebced7ead18f8e11a657e1e950a16d3be63dc'),
    ('pown', 3, 'rup'): ('b9b99f5a8e6f08806e752e1aec31f9925c3aa08765552c0cab038fcd55eeb0b4', 'b9b99f5a8e6f08806e752e1aec31f9925c3aa08765552c0cab038fcd55eeb0b4', 'eb79f3de176e76b047fc1649fa806480091fcc5c330e8ad025576af50158699d'),
    ('pown', 3, 'rmm'): ('3d40c34e05e364bb45ef5ad6376756ae0d3f0fc7d5a1b47dd03b1b95f2278095', '3d40c34e05e364bb45ef5ad6376756ae0d3f0fc7d5a1b47dd03b1b95f2278095', '5a1602b2c5e2510496491d1710aae893524bc47b1c0f782e4dbc1797bc3dc056'),
    ('pown', -3, 'rne'): ('ecfee621e6606fbae95414eff7a0e3bcfe8c87311d95f9cde36d9fcc40c25307', 'ecfee621e6606fbae95414eff7a0e3bcfe8c87311d95f9cde36d9fcc40c25307', 'e51e4c97100af0d000cf95dd8e57930ecc892284eeb7a6141ddd5856a0d43015'),
    ('pown', -3, 'rtz'): ('c375bc4b3d35ee7a30efaae01d143d46cd1e8fc50c88fa240c807b4fefe98a52', 'c375bc4b3d35ee7a30efaae01d143d46cd1e8fc50c88fa240c807b4fefe98a52', 'cfcfd9d4b396f73dbe1a40f5dca258f80146ffb58631853127147564958976db'),
    ('pown', -3, 'rdn'): ('87e4cda0c4d92ea75190f5cd75f8ad6fb748f29311522c7ae246eeef06811d96', '87e4cda0c4d92ea75190f5cd75f8ad6fb748f29311522c7ae246eeef06811d96', 'c39adc6a56b39bc9f8de04ffb5d454db30a01565b726714d53cdda8eed4ce9d8'),
    ('pown', -3, 'rup'): ('ab379b4f24ad3968a805e7ac59a2db8f8f3382f2d0061a0326df4732f2c252b3', 'ab379b4f24ad3968a805e7ac59a2db8f8f3382f2d0061a0326df4732f2c252b3', '8cf851ae9620fddb5bdfdc316bffd31d3d507ee5602587b81357b9984d904683'),
    ('pown', -3, 'rmm'): ('505ba9f1a43b0adc8ec53a4a80e88dd5285e22ed8dfb181b4cd315dd54a5c40c', '505ba9f1a43b0adc8ec53a4a80e88dd5285e22ed8dfb181b4cd315dd54a5c40c', 'f578dc8f9ec446ca2d43588a94d304d2e8453701ea26984cf7d63b29b4165276'),
    ('pown', 17, 'rne'): ('a380b25e01daf76c48398640db89a17b0f14e94da7d8da324a99667ed7af8702', 'a380b25e01daf76c48398640db89a17b0f14e94da7d8da324a99667ed7af8702', '295f31b7c152c33865b671025dc3ef45e018c9f60540222b99a85598543d6db3'),
    ('pown', 17, 'rtz'): ('d44ddc26510d4f148eb87b6512f7e6744e4c8b8cb0d4234cec726a2952d94f54', 'd44ddc26510d4f148eb87b6512f7e6744e4c8b8cb0d4234cec726a2952d94f54', 'ea60295372b520b9c7c25feac6faaf4cf6987257528f481ab010062f2459ab8d'),
    ('pown', 17, 'rdn'): ('af027de776ca0cd6187e4422a11d687dfa013d20248d43cc16c4d039627d0120', 'af027de776ca0cd6187e4422a11d687dfa013d20248d43cc16c4d039627d0120', 'c497f8a8a1a826a19da0465bca2c5fd99a30e2b7ee5a96e0dc7adf1565381e2d'),
    ('pown', 17, 'rup'): ('624b4acf30690c46434a352e4e56949ce32223b45cb72a30340eb5669db90aa0', '624b4acf30690c46434a352e4e56949ce32223b45cb72a30340eb5669db90aa0', '527b1c657f344f9d4fffa61fecc4a77f52e3275a2271fae912bd958e4f8d8dae'),
    ('pown', 17, 'rmm'): ('de7fcfc3dae70cb1430e36b4d3de5c6415e6f174ef838e85e82ff628cbb0b487', 'de7fcfc3dae70cb1430e36b4d3de5c6415e6f174ef838e85e82ff628cbb0b487', 'e587d1922ed0b4c933281cd0a1132ef727b1d3e67356361bf0c53cdc45ce241b'),
    ('pown', 2147483647, 'rne'): ('ce89c8e36764ca7a6a77987257f9aef6f1d110ca84b86ad3016b34a8f3c97c6d', 'ce89c8e36764ca7a6a77987257f9aef6f1d110ca84b86ad3016b34a8f3c97c6d', 'b9a7a39e359c0ce07d2a164e7884c1f61281201156be2a876d1da237c6cfc332'),
    ('pown', 2147483647, 'rtz'): ('0b7662292653de326eda3c160fd7bc595a909d5bef2617eae24b5581be73d988', '0b7662292653de326eda3c160fd7bc595a909d5bef2617eae24b5581be73d988', 'd2629ce1b5ebd061e2db4ad8a86201f21b289802226fcb3536893571d6db90b4'),
    ('pown', 2147483647, 'rdn'): ('029ad9851cf7f4ffe6bc4cb634ddc50fe945ced3f5c9ac6f3d0b7e7692a9222b', '029ad9851cf7f4ffe6bc4cb634ddc50fe945ced3f5c9ac6f3d0b7e7692a9222b', '088e723547cc358c686fcad0ba494336a49b42411b1b16fbe8e2d47a0be33f26'),
    ('pown', 2147483647, 'rup'): ('c6220f6b448a055ef195eec2e58da3b15b30ebe1e273ee01713f7b9df6a9ab1b', 'c6220f6b448a055ef195eec2e58da3b15b30ebe1e273ee01713f7b9df6a9ab1b', 'e86510273c4deed7b6690496bfd6a7e8e8d1912886452c961c3c78688f7dc633'),
    ('pown', 2147483647, 'rmm'): ('adc9867d5d65370bbc364dba565925f92dc9aee507a211fa1e5ab16edb29e5b5', 'adc9867d5d65370bbc364dba565925f92dc9aee507a211fa1e5ab16edb29e5b5', '3745262880c2a65f8a1c50b36001c2a4e12d80cf6434cf958cf7c0131757affd'),
    ('pown', -9223372036854775808, 'rne'): ('21c3e47b208952c7087edffa1a35baf17d0ef04083182a42e789a56b230bca36', '21c3e47b208952c7087edffa1a35baf17d0ef04083182a42e789a56b230bca36', '63492654f1608466387cda466e451ba36bb569bc4feb301ce9fc5040e67d7ffa'),
    ('pown', -9223372036854775808, 'rtz'): ('8d7339120d7bf823dd2540a5ab7e7402c9596a2cb6d275e8652cd8c53c540d44', '8d7339120d7bf823dd2540a5ab7e7402c9596a2cb6d275e8652cd8c53c540d44', 'c0fe9cc40d6e8ed85532dd5e275a9d99ebd29b16560396aec965f0b05ea70992'),
    ('pown', -9223372036854775808, 'rdn'): ('090acbe5cc4074578f48507c06b772d4bcaba24086340445b1d02cf5d54dc98c', '090acbe5cc4074578f48507c06b772d4bcaba24086340445b1d02cf5d54dc98c', '53f6f06c4c3f1092ab7a8c30cd4f7405ff6a8c81b1c24c286cdae77b82cbad05'),
    ('pown', -9223372036854775808, 'rup'): ('1b4f8e9a6b06ed3c676daaf39ee63abcc278f66ce4e4900db940100eb0c46014', '1b4f8e9a6b06ed3c676daaf39ee63abcc278f66ce4e4900db940100eb0c46014', '0190c8ebaad8ecc414ba6b6cdcf1e55ec3645cb631f9bff0ee4834ec020ec2e9'),
    ('pown', -9223372036854775808, 'rmm'): ('decb3a453140bb078c344639dec75ecaadd7a25d3d9f180e1f80b43e02fbbf66', 'decb3a453140bb078c344639dec75ecaadd7a25d3d9f180e1f80b43e02fbbf66', '3dc533645784e2e801971a530e54483559dbff967486214b24480141b127d49e'),
    ('pown', 1000, 'rne'): ('a1fb24e3e0dbfcac2c6b7e24fb8e03c90d2897848a360b777e06b3a41741f9e9', 'a1fb24e3e0dbfcac2c6b7e24fb8e03c90d2897848a360b777e06b3a41741f9e9', '6649fbee1558337d9d63665780e24f36f3bc891a81424bbc817f7b068fbee85f'),
    ('pown', 1000, 'rtz'): ('430bcfe7decb31b8bb1311fc5a3bb8a96db19d0f993105287836688de446c9e4', '430bcfe7decb31b8bb1311fc5a3bb8a96db19d0f993105287836688de446c9e4', '0d861cfea16c41858e24d252ede26f06fb252da77b81529b9a68b42f4882582f'),
    ('pown', 1000, 'rdn'): ('7015a94fde809317ee6fce2bcfa4aecd02325a7b37ac9d2e20eb3f9bcdd09bdc', '7015a94fde809317ee6fce2bcfa4aecd02325a7b37ac9d2e20eb3f9bcdd09bdc', 'cfdcf1d36098be2a90111fd6c6ef5252b26913440abd22fea718f7b861d4c05b'),
    ('pown', 1000, 'rup'): ('1d79ec5a94aff7997e8b03c613ce2adca0e7c5803815fb5edffb776f416d788a', '1d79ec5a94aff7997e8b03c613ce2adca0e7c5803815fb5edffb776f416d788a', '4cf1e4a5f81cca0bb62ed919fac9a13cac65817e9084d70c4d17af05528b8e0c'),
    ('pown', 1000, 'rmm'): ('b91d0116e034522f9133ea556098d17cc22afe969b46419de97f6ec06d11b730', 'b91d0116e034522f9133ea556098d17cc22afe969b46419de97f6ec06d11b730', '39ed988d042906e5460dec90235e75dc59b662c378ed5680d8ba2d3c0f267627'),
    ('pown', 16777217, 'rne'): ('5fe58be5d54c4fe196cee25dd01519ad225823b29c8603c4e6359502f2126236', '5fe58be5d54c4fe196cee25dd01519ad225823b29c8603c4e6359502f2126236', '1e57db9c8b43857d4b590d77649eda1237ca29fd8450c33c98efaef73ac6494f'),
    ('pown', 16777217, 'rtz'): ('3b4f572b765fa8e2ede5579828f60a902e21f44c218d4b4e4edec2269f871639', '3b4f572b765fa8e2ede5579828f60a902e21f44c218d4b4e4edec2269f871639', 'a14546e61b417054efadbf12e0afd8764ff6a3d002e62995fb3a327df3f05e0e'),
    ('pown', 16777217, 'rdn'): ('222b3badbd4693f78e6404efb1433017b48f86a75a5d8918a4d2d33e4ed8c35a', '222b3badbd4693f78e6404efb1433017b48f86a75a5d8918a4d2d33e4ed8c35a', 'fe0cb558da65eca6a02be6090218e1543c3a209fc20f0287dd341d48878e132a'),
    ('pown', 16777217, 'rup'): ('100c185b2c8bef09858c5b87c7ab931fd676e5370a41f22d7c3418bfda26dc5b', '100c185b2c8bef09858c5b87c7ab931fd676e5370a41f22d7c3418bfda26dc5b', 'dda19c07033fa79c25b038aa7f101abfafc5c29535461ef95c002f9f029cf4e0'),
    ('pown', 16777217, 'rmm'): ('90c9c1827404535f21c85ddc17ec15be232ab20fa6bb155f3e57d2c11c1e0ba9', '90c9c1827404535f21c85ddc17ec15be232ab20fa6bb155f3e57d2c11c1e0ba9', 'de0525d657aec85ba640bae9dd1e6a6266b5be9618706577365e393834a73c08'),
    ('pown', 1099511627776, 'rne'): ('2e81f136433dbcd514decb0b2057d77a2bbcd6ced6a9a0d874ef2ef3bf60f206', '2e81f136433dbcd514decb0b2057d77a2bbcd6ced6a9a0d874ef2ef3bf60f206', '0c5752a1369135eef02ca8d48f1e297f9b75c22e4c7ba1e1ebd71d9d1922b781'),
    ('pown', 1099511627776, 'rtz'): ('88f3f1ab585b3a0021f316b07621d34149500eaf6fb90759f4a4764ce3b1165f', '88f3f1ab585b3a0021f316b07621d34149500eaf6fb90759f4a4764ce3b1165f', 'b4cdc1e7921d67fb3a45d6dda92f767812a429204f2c8daebe7a29625486023f'),
    ('pown', 1099511627776, 'rdn'): ('b58a659d48735f758b58e74ad5b58d2d5f8a11e832b8e309752742b31b373faf', 'b58a659d48735f758b58e74ad5b58d2d5f8a11e832b8e309752742b31b373faf', 'cb9e8c8a5713721b32588b93434e2fe718613af15804429ae140c6606ded6571'),
    ('pown', 1099511627776, 'rup'): ('2b140d72b974bdc0380b3739b7ef39666d97f2f6654cfbb31b39d818feffbd39', '2b140d72b974bdc0380b3739b7ef39666d97f2f6654cfbb31b39d818feffbd39', 'd09d8218ff31959289e3c60ad8d2042bb54a984a1cdcb0f49c32991570bff5eb'),
    ('pown', 1099511627776, 'rmm'): ('265f10f4b987778506e53a0fb4aa15015e4f922d417638f821a27a556072c70d', '265f10f4b987778506e53a0fb4aa15015e4f922d417638f821a27a556072c70d', '42006b76605ebece78934b5c3ee6484d448ea3e5e71f7df7bf2dc8bd06044749'),
    ('pown', 281474976710657, 'rne'): ('b80ffeaa6bcb0ba8b548a64279e5f9afa4fb4dd3c7721a8b98db1a26d255d7b3', 'b80ffeaa6bcb0ba8b548a64279e5f9afa4fb4dd3c7721a8b98db1a26d255d7b3', '758eb6db3c97cd4f03b9192e14f9fa0a3e18e43d276ce5160a28b9f716eeb224'),
    ('pown', 281474976710657, 'rtz'): ('a5bb3809c2a1f5cbe14a3ce5e7c25351637bd709439671267397abf808b8de2b', 'a5bb3809c2a1f5cbe14a3ce5e7c25351637bd709439671267397abf808b8de2b', '29986f6869f7d5d4ee217bf2b03bb93106690b387bc0a12b45d74f8d61aab592'),
    ('pown', 281474976710657, 'rdn'): ('5774b7b26c6a03fecd6bc2c3143523bf54d0e9666a15bb72ff86069e924f9bdb', '5774b7b26c6a03fecd6bc2c3143523bf54d0e9666a15bb72ff86069e924f9bdb', '60b15d34e9a5fd65a08b3bbf77b6ec01958a4bc32d8fecd568a36558b1d83994'),
    ('pown', 281474976710657, 'rup'): ('cddd2b8fba8d10c91d37536770d576d8491c713d159d914b21fbf7945f69fdfe', 'cddd2b8fba8d10c91d37536770d576d8491c713d159d914b21fbf7945f69fdfe', '1397bb06606c45fd2afd9fffa8fc08a0cc30baf5aa1eaabad6362433dd98c380'),
    ('pown', 281474976710657, 'rmm'): ('05167dc349c7cf2f632b17c93b804b83cedc302d2fa31394a9832df98ae794a1', '05167dc349c7cf2f632b17c93b804b83cedc302d2fa31394a9832df98ae794a1', 'd2009ebbc3f246d487a612a683d2d8ed6f0ed642ef10bc7897740e82b70b1a20'),
    ('pown', 4611686155866341377, 'rne'): ('662d0f8339eb6dddef00e4b6c84c7c39bb4dedb02747caae72646742ab2d7b48', '662d0f8339eb6dddef00e4b6c84c7c39bb4dedb02747caae72646742ab2d7b48', '60ec33ffcf7de0bc54723d573a15b898a65d7c3f95d2f1a35b0e8f6edde46d36'),
    ('pown', 4611686155866341377, 'rtz'): ('651f1a4ab5a293673c34b5cf8abdc9c1c404cdf30fce994b105eba1ed5a94006', '651f1a4ab5a293673c34b5cf8abdc9c1c404cdf30fce994b105eba1ed5a94006', '277e6d2ebf2e87aee98eaecaecebdc75e963a0368a6b32bb8ffd5fb96dadf817'),
    ('pown', 4611686155866341377, 'rdn'): ('9a112173fe7ca5335867747d0fd9853beb2a4ac1e7a08666d918d6777beef085', '9a112173fe7ca5335867747d0fd9853beb2a4ac1e7a08666d918d6777beef085', '4477df5744de1cd5198daab9d7ea47b44daf91d901f8d53d08436ea838bb2b16'),
    ('pown', 4611686155866341377, 'rup'): ('944b40f6bd8ab2847f632817954401b667497635beb3d807d2a0a8104846a9ea', '944b40f6bd8ab2847f632817954401b667497635beb3d807d2a0a8104846a9ea', '75c0e79f12976c285d9e853fb3bf95409ca7432d58b7fcd234d37b9232edde02'),
    ('pown', 4611686155866341377, 'rmm'): ('1b742ebd5c247a0b2fe83aa255a6c402523811b2eb0b146faa8b8e16660bb9ec', '1b742ebd5c247a0b2fe83aa255a6c402523811b2eb0b146faa8b8e16660bb9ec', 'b0c3fc41cbcc16241497b2966d4a11745147797d4e540557c7dbd305889c5d8e'),
    ('pown', 0, 'rne'): ('1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '56d6f056f010074493ecfee042fb16e0b753a1d1582b6cb1859f37aec2ace574'),
    ('pown', 0, 'rtz'): ('1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '56d6f056f010074493ecfee042fb16e0b753a1d1582b6cb1859f37aec2ace574'),
    ('pown', 0, 'rdn'): ('1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '56d6f056f010074493ecfee042fb16e0b753a1d1582b6cb1859f37aec2ace574'),
    ('pown', 0, 'rup'): ('1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '56d6f056f010074493ecfee042fb16e0b753a1d1582b6cb1859f37aec2ace574'),
    ('pown', 0, 'rmm'): ('1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '1480c8b2218e2222317bea6b8b42cfffc178b70dbd69fb18589fd46552c1eb4b', '56d6f056f010074493ecfee042fb16e0b753a1d1582b6cb1859f37aec2ace574'),
    ('pown', 1, 'rne'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('pown', 1, 'rtz'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('pown', 1, 'rdn'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('pown', 1, 'rup'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('pown', 1, 'rmm'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('pown', 5, 'rne'): ('fb8ed0e6a125ceb33012f9d56e5f9823e6017c22d0d109e00bc783e82a3c6096', 'fb8ed0e6a125ceb33012f9d56e5f9823e6017c22d0d109e00bc783e82a3c6096', '7b0d05b926ccb1d5a93ce8e9368d925c0bb0b1b466288b11c995613c41420205'),
    ('pown', 5, 'rtz'): ('954dadea55b8c29f72c21500f6ac8f757ca7503667671d8e05cc102f540ffb17', '954dadea55b8c29f72c21500f6ac8f757ca7503667671d8e05cc102f540ffb17', 'ef51fc390f81ebf5720fb6904e44e34b62748f93299c67d31dac9681b90741f6'),
    ('pown', 5, 'rdn'): ('705a222c67b623de17b9334e7c72af36d4fcc3f593a18606bfdda52aa2399e03', '705a222c67b623de17b9334e7c72af36d4fcc3f593a18606bfdda52aa2399e03', '6f383965a7f27a7f490e37476e7a4076d3c4772cf7be12e17f7ff157dc5bd6d5'),
    ('pown', 5, 'rup'): ('f25f90af9d2bdb4920012869dc38339bed9e54052eceb362f38bb5ea1f115b7d', 'f25f90af9d2bdb4920012869dc38339bed9e54052eceb362f38bb5ea1f115b7d', 'e3ef7862801236fbde00b10f971110e22b1b456955ed8098001b1bf35122d2fe'),
    ('pown', 5, 'rmm'): ('64f863b482deb1720050ea1d0d341c15a2a41fba230f4d1a4245de7ed89cdccd', '64f863b482deb1720050ea1d0d341c15a2a41fba230f4d1a4245de7ed89cdccd', 'cd980aa13e6f06dc878200d915970d037ff9f4e329c56f63d3163d0cbfe2f210'),
    ('pown', 34359738375, 'rne'): ('35d340689eeddfddee8e1134497d7bae6d28c117a0e4edc3c6dc2de80f8a38e2', '35d340689eeddfddee8e1134497d7bae6d28c117a0e4edc3c6dc2de80f8a38e2', 'cc1ed7ce68a79c4777a8388ee5836ebea6394eb6ed55a95c4107ec94c1cb4ca9'),
    ('pown', 34359738375, 'rtz'): ('e9e12105382b0ee5d61eb88f1138f4b166f0e7c864ac993e9c3003df99f53652', 'e9e12105382b0ee5d61eb88f1138f4b166f0e7c864ac993e9c3003df99f53652', '72b759e13b7bc3e28babf90fb80e2b292a6c789ad6c3142f572ac17fa7900121'),
    ('pown', 34359738375, 'rdn'): ('5351b32d726373d600d488d4b12c2a3a7fc4c982d72d68564553f7bcdf2f287a', '5351b32d726373d600d488d4b12c2a3a7fc4c982d72d68564553f7bcdf2f287a', '3d40a5b70137a5bfdd858e751b9eea14cc06ba4d33c6a8c2bc315cb484c14673'),
    ('pown', 34359738375, 'rup'): ('654c0c51afd83f70b60e5be72df19636aa251c7535fba4cc1448a367646a3821', '654c0c51afd83f70b60e5be72df19636aa251c7535fba4cc1448a367646a3821', 'ae23941ffe48d97d0cac9bd007c60e4c2d8e058cd7b17e77345cf4f795a92b50'),
    ('pown', 34359738375, 'rmm'): ('d910ddfd49b58863784503d83237d15a806c1347b13e931db6503400317abc9c', 'd910ddfd49b58863784503d83237d15a806c1347b13e931db6503400317abc9c', 'ec749ed2dfde5f76cdf05377d8d15185dda986dc4db9ab6ba18c492a37631853'),
    ('rootn', 2, 'rne'): ('d856f1ce5ae59a4a162f015eb9015e07a7d6e9f3e7ab8f910c7cc83bbe77a898', 'd856f1ce5ae59a4a162f015eb9015e07a7d6e9f3e7ab8f910c7cc83bbe77a898', '19701151bc1c28152291e0b18a8e8b485f41bbce781eb2788762ee870f019129'),
    ('rootn', 2, 'rtz'): ('1e7d14cf1ec7dae21a467a6b9221b1336895cb6e987a4b0710c379534f93d7b0', '1e7d14cf1ec7dae21a467a6b9221b1336895cb6e987a4b0710c379534f93d7b0', '8fe669ed8a4c5c2ad20db2a68b95dc81ad737d80c74036dab788d8a842350e51'),
    ('rootn', 2, 'rdn'): ('b5af3d4c2548dce2c4fb35f71f8a4aac55452d7a86a41e5825a77427426deee4', 'b5af3d4c2548dce2c4fb35f71f8a4aac55452d7a86a41e5825a77427426deee4', '7c05231826256343bcbc89730428819251c15b4ed2ee624f49712cae29442816'),
    ('rootn', 2, 'rup'): ('661abae5c73114e88da1a2fdd47f1bf5bc7352acbafc85acaf41a4cb491ed9e7', '661abae5c73114e88da1a2fdd47f1bf5bc7352acbafc85acaf41a4cb491ed9e7', '1f415d4d811d081aa6eced3749c9fa3c300c9f83a640241a842bba856bcf6c96'),
    ('rootn', 2, 'rmm'): ('9a4160873488154d53bf1fa5da66252e7380ff006ec63974c59f27ad6a8de95b', '9a4160873488154d53bf1fa5da66252e7380ff006ec63974c59f27ad6a8de95b', '0f1cb7a15badf7325c9b957627079eae77b5fd10a60ae4a8ee51b146b8ff126d'),
    ('rootn', -2, 'rne'): ('b74898cb6fe9311a1034febbefca57423e105b84b9ed64f0525c6583c6e1ff96', 'b74898cb6fe9311a1034febbefca57423e105b84b9ed64f0525c6583c6e1ff96', 'eb5ee02d64722e8ea42d96d577a159c9862281c80922149c101d144f43fe1c6c'),
    ('rootn', -2, 'rtz'): ('618bdc92143aa53e4afe0431c33b7429cb6283bfdef6fe79f9a278489d913658', '618bdc92143aa53e4afe0431c33b7429cb6283bfdef6fe79f9a278489d913658', '63fccb3b8b32cfe6fcd594bbcaed73f6507af6f8687f31ca72a338e2baaba05b'),
    ('rootn', -2, 'rdn'): ('990691c0af2ec2c5cd53df1ce2509b56e7dbfe613f0a12973adfe875987483e6', '990691c0af2ec2c5cd53df1ce2509b56e7dbfe613f0a12973adfe875987483e6', '5a964edfed86f41d0e20f017ac7dcf901529419bd0338c270c41f05bf4ebab6c'),
    ('rootn', -2, 'rup'): ('5a180183472c717255b1c05a20e34846fa85b76eed377e0ee4ade71a2009b91b', '5a180183472c717255b1c05a20e34846fa85b76eed377e0ee4ade71a2009b91b', '29f0df8a211cd509d4e44b4b1baff7544893788b16a348bcbb2ce0372315a184'),
    ('rootn', -2, 'rmm'): ('cf7ea225c2ff7235d0c052b411c4424d2cc59382c077d544e40fba72fd30afed', 'cf7ea225c2ff7235d0c052b411c4424d2cc59382c077d544e40fba72fd30afed', 'fad33ee34958b575cda7dedf7d9d5eb25d7a9723e94f1fef9eccdec7c0e33c0c'),
    ('rootn', 3, 'rne'): ('ecf7fd41cb6cc73686988f27bd2b517a937922f19b6825ceeb4e5d427c568e56', 'ecf7fd41cb6cc73686988f27bd2b517a937922f19b6825ceeb4e5d427c568e56', '442475acc511bd229071ea9ac70223e16e82fe899d7b61372d87dac36e64cb18'),
    ('rootn', 3, 'rtz'): ('15036d4c7e745db09a823aefc5ad55e38b70214e0bcf1202afbc919d2eb2a6e0', '15036d4c7e745db09a823aefc5ad55e38b70214e0bcf1202afbc919d2eb2a6e0', '46f0d6bbecd2974d2c94ee128cb593735ed2419b4a5ad55ffcaec129a520ee51'),
    ('rootn', 3, 'rdn'): ('e35209057f0f2303915eb9b76d601c2b787f7c96e57f34707e785deb2f7ac7a4', 'e35209057f0f2303915eb9b76d601c2b787f7c96e57f34707e785deb2f7ac7a4', '623e3ff49e8a741dfa773051b981d9cb8aa6b3a5477d7cf959c51fad6859d0ba'),
    ('rootn', 3, 'rup'): ('9b918fa968ce446c8a0a8b9c0ecb2755dcfbb279987e480db4a36f8dbe9a81cb', '9b918fa968ce446c8a0a8b9c0ecb2755dcfbb279987e480db4a36f8dbe9a81cb', 'e6099a5617b7fe7f9bfddeed846a3c7e64aecf30131908a223f915d13de4d5c5'),
    ('rootn', 3, 'rmm'): ('b6b95e22d2324a7849a30f66b7e5796312c67a2b8b00edb3ac5824228835bc50', 'b6b95e22d2324a7849a30f66b7e5796312c67a2b8b00edb3ac5824228835bc50', '59e158d80f114c4a6b2d1a1bfe0f7e9c80df9f566a8ceac72657e7aad94a1e24'),
    ('rootn', -3, 'rne'): ('7f9742e720258faffffd24c125a11942578429925f8424ffe3fe7d41ca9f2b06', '7f9742e720258faffffd24c125a11942578429925f8424ffe3fe7d41ca9f2b06', '226683ae76ae35e81d252e56b8e156b69476da35ff943fe34294b01913c41d78'),
    ('rootn', -3, 'rtz'): ('7c5026790f185604834f120d0bfa222bda1b8f9a080e3893ad9ed8800d6cfa17', '7c5026790f185604834f120d0bfa222bda1b8f9a080e3893ad9ed8800d6cfa17', 'adbd58633f76e37fc287ea3345e4a8db746959f6e12d434f99b0c96a996a0038'),
    ('rootn', -3, 'rdn'): ('aba0d4f421e527fc1d903d855bccb7f4fa6426cefdc92c16559fbee16a793978', 'aba0d4f421e527fc1d903d855bccb7f4fa6426cefdc92c16559fbee16a793978', '584ccca9a44c1c8493e3dd64dbe51dd77a3ad1e868dfa6880df4817a45c344e5'),
    ('rootn', -3, 'rup'): ('fee09a06a2307f341aea2bce9282ec0d002349581ce7259a8598d44b427b1d98', 'fee09a06a2307f341aea2bce9282ec0d002349581ce7259a8598d44b427b1d98', '72ff3f7694d903d903b69c51cf5da1e53662f8ef11b3a13ef83576d0cc80eff8'),
    ('rootn', -3, 'rmm'): ('27b8c88ae49db16a2d4d4350520177635724c046f01a3e46e39690b347a1df3f', '27b8c88ae49db16a2d4d4350520177635724c046f01a3e46e39690b347a1df3f', '1eb9b6bb9a0a97b22c0cea2e9c35ed3b446b23f39f342dc68f6a0afb5773a4f7'),
    ('rootn', 17, 'rne'): ('3144a3d7f2f8673025f4d34c3f22e35553ed8858dfb43bf05009327701eaa16b', '3144a3d7f2f8673025f4d34c3f22e35553ed8858dfb43bf05009327701eaa16b', 'b8e28a90b4380641d6f1dc9719057982a54954856444809ca81db7c0c41ef7ec'),
    ('rootn', 17, 'rtz'): ('19dd886e21cae54a3c2e15b2913e2f0cb2c059d266415494ff666562ac63d057', '19dd886e21cae54a3c2e15b2913e2f0cb2c059d266415494ff666562ac63d057', 'a829bf4a3cae9ed16c0b44c84180c3d9de4403052d1458188f570f1de1da72f8'),
    ('rootn', 17, 'rdn'): ('ca641208cb705ac1e39e8cf893f0250391fa834c1d8439cfe7afd980eb1266b9', 'ca641208cb705ac1e39e8cf893f0250391fa834c1d8439cfe7afd980eb1266b9', '4156764e8250b2a7da261678efbc4b4fd42e9af7fdd6cedcc5ebf3042636faaf'),
    ('rootn', 17, 'rup'): ('254f663e33296cc9b2cf7942510f254987745d4d681ca3d4f77bcdc09ee059c2', '254f663e33296cc9b2cf7942510f254987745d4d681ca3d4f77bcdc09ee059c2', 'e06f147f909e1e20bf650d53f85c35fd977530cecbcef8cdbe568fc8ef1598e5'),
    ('rootn', 17, 'rmm'): ('8210dfabaa05a71b95d445bfd91f48c1623269f8160e1c756b54f62c5b959663', '8210dfabaa05a71b95d445bfd91f48c1623269f8160e1c756b54f62c5b959663', 'f152b2274ab415521a67a89d2eb3bcc278dffe05f5c3c779bf9f774a0fe022ec'),
    ('rootn', 2147483647, 'rne'): ('d41396711fbc36505342d3e52732ee42db7e2c020b4675e053be5530b8ca6a27', 'd41396711fbc36505342d3e52732ee42db7e2c020b4675e053be5530b8ca6a27', 'd5579f06b4be0de388efa30da1875bacde92e76fa64aafb584107153d3bad372'),
    ('rootn', 2147483647, 'rtz'): ('ed29dd82b6d714392b327a59ca59ffc76683d7769010cc9766cb03dd33f1b94e', 'ed29dd82b6d714392b327a59ca59ffc76683d7769010cc9766cb03dd33f1b94e', '474611bb0d982ed189ff1f1ebc14bc031d6b3f4af12d62e8cc64e0cef0d9286a'),
    ('rootn', 2147483647, 'rdn'): ('4db5c2a7eff6d57649161ff1c0dc69a8b62e2e344b916a27cef0aa98ea4518df', '4db5c2a7eff6d57649161ff1c0dc69a8b62e2e344b916a27cef0aa98ea4518df', '37fade7b5d689f8916ba50de1fa80dc1f4ad1b7d9de3171464d99c05727a1a6d'),
    ('rootn', 2147483647, 'rup'): ('d6ecb3ee538884784fdced943be7453e313b23cb2e6f2fb38be198ba93abe54a', 'd6ecb3ee538884784fdced943be7453e313b23cb2e6f2fb38be198ba93abe54a', 'ec22c542fafe0cac07235175c089a87d76b24b0668353c1511987c0aac42ce76'),
    ('rootn', 2147483647, 'rmm'): ('684d85c5ebd82d8552f442ca03cfc88e75eb7e70d63c8841682ecde4035e251e', '684d85c5ebd82d8552f442ca03cfc88e75eb7e70d63c8841682ecde4035e251e', '6adad7d0111acfeb928e5d05c4ba9c8ce77ddbe8f3250bc163862e1e7664c635'),
    ('rootn', -9223372036854775808, 'rne'): ('de17fb7b47a96dccad034b17336ca165bee421fbdbde3cd2634b43b3e87dec18', 'de17fb7b47a96dccad034b17336ca165bee421fbdbde3cd2634b43b3e87dec18', 'ad8eae7f83dd751be2455d61a04d12f861d8459f491d2e43da45f9b9c74b1582'),
    ('rootn', -9223372036854775808, 'rtz'): ('7cd5c8be636886645b258111a14615e54543cb3c30ef57ddd9451cb12a037660', '7cd5c8be636886645b258111a14615e54543cb3c30ef57ddd9451cb12a037660', '1f596d5815a5ce287319d9edee88b1e4b528c001ee3421f711b78c5df5ec32ce'),
    ('rootn', -9223372036854775808, 'rdn'): ('51dd8b793b9311c5c82161a40143b7665eb5969657876d866a3e194682576be1', '51dd8b793b9311c5c82161a40143b7665eb5969657876d866a3e194682576be1', '0db43360f3aac862e50756a13cd25a85851bf606b5d06d0d13f83e71d75c052b'),
    ('rootn', -9223372036854775808, 'rup'): ('7cd6fb8272aeb65d5a2957d6939ca96b08bd7121a647381f2146d8dcc26ca72d', '7cd6fb8272aeb65d5a2957d6939ca96b08bd7121a647381f2146d8dcc26ca72d', '047c8f24446370c963c1c46fe37f83996d2e244426ea5a82b9e9a38af017a548'),
    ('rootn', -9223372036854775808, 'rmm'): ('76472311d7e8418f411a9eca941cc52c261014fc5bef8769aac61bdd087aaf9b', '76472311d7e8418f411a9eca941cc52c261014fc5bef8769aac61bdd087aaf9b', 'df6e70011a5f758e2b9fdf40bc239381406f98affed3f2c415f28a3581b2a64c'),
    ('rootn', 1000, 'rne'): ('e0ecd3cb612920b3cc28f049ab71cc11e9f467bd308076dc7dcb29c1f1f3268b', 'e0ecd3cb612920b3cc28f049ab71cc11e9f467bd308076dc7dcb29c1f1f3268b', '3bbde3f338958d27e4eb6a9285a1eedff6e49916fa6c94f87da0dd19bbe75450'),
    ('rootn', 1000, 'rtz'): ('041af3def3a47db65ed8b69a0f045c0ab6bae68f8dc65a61cdd515e3c05e5531', '041af3def3a47db65ed8b69a0f045c0ab6bae68f8dc65a61cdd515e3c05e5531', '9e0d76b55c6b1a8e8120b60f8ed03e87117f1fb110233f57d92fbbae4c59e27d'),
    ('rootn', 1000, 'rdn'): ('431219af33696886a94eeb1988f8170827fcda000072683a950780146ad84d2e', '431219af33696886a94eeb1988f8170827fcda000072683a950780146ad84d2e', 'b16fd4a7a5002340a9b065b82cd0c808b7cebcdc4109c186f9bc4f6a8a20f09d'),
    ('rootn', 1000, 'rup'): ('917602cc7b8ab93773629a181a4fceedec0da7bcc7ea935b5d7997d6b4a664c9', '917602cc7b8ab93773629a181a4fceedec0da7bcc7ea935b5d7997d6b4a664c9', '7428efd90bf5bfef469703fd7a0977bc699d75169e967ee6dafa328e5ef95f75'),
    ('rootn', 1000, 'rmm'): ('603027fe6ebf57eb0dfe185db7a4b0b9253d3513a5fc0b51077f4341364aa559', '603027fe6ebf57eb0dfe185db7a4b0b9253d3513a5fc0b51077f4341364aa559', '62e5d5010a35bc63ecc03d28ef8faa96f3d6577f5655c6a08195429e1bbe59f8'),
    ('rootn', 16777217, 'rne'): ('6b9f003b28867340a104557f9b6c6979a562dd3f97bedb1da94498a77f1c110d', '6b9f003b28867340a104557f9b6c6979a562dd3f97bedb1da94498a77f1c110d', 'baa4a0446d39e0ff0bc950ccc02dc61e7165b23a12bbe09651bf1f79c2be5543'),
    ('rootn', 16777217, 'rtz'): ('f191c4b87d2ca0e496342bdcf578dfd4a2a1df934d1d81d471fdcd72930c6993', 'f191c4b87d2ca0e496342bdcf578dfd4a2a1df934d1d81d471fdcd72930c6993', 'a43ad6ea013fc5561e044710fdbda1804f3b3fa22cd8c60eb023759a3d0705bb'),
    ('rootn', 16777217, 'rdn'): ('f03100b68c54e2ce6b9111accfd85e2a4f2adf7e991bb9be23c552730408b472', 'f03100b68c54e2ce6b9111accfd85e2a4f2adf7e991bb9be23c552730408b472', '472540da875dc5f7a463c5a0fc0d6380124e0e0c95bf7169f967b10a7fe9fcbe'),
    ('rootn', 16777217, 'rup'): ('a5f79f7b374b7997bb0587835143e829d9de5f1b8424ed73d85b30c8a54c15f6', 'a5f79f7b374b7997bb0587835143e829d9de5f1b8424ed73d85b30c8a54c15f6', '9db1d3cb9744373d84077593dd2e58e4a7df84f7387926d6cbd6b2b1e87725c6'),
    ('rootn', 16777217, 'rmm'): ('a062690dfefd784b0533eee32ddc850ea190c5c7f79f7968e8bf769ee87579c3', 'a062690dfefd784b0533eee32ddc850ea190c5c7f79f7968e8bf769ee87579c3', '99593975eeef1448e3ca78621990cbb8df17796b736b4322375f64db6388e4e7'),
    ('rootn', 1099511627776, 'rne'): ('fc2f226be0b489f89f97fceea4012309443a6905b3be7bf81213f0a80ede4af8', 'fc2f226be0b489f89f97fceea4012309443a6905b3be7bf81213f0a80ede4af8', '7c2fcb400384878a3db01b2584e8708263b9c168e6c31245db57f7769bce68d6'),
    ('rootn', 1099511627776, 'rtz'): ('1037c07996fd7ed49441f3ed7588c31e1ae3909f96552cc88d08af1c3584f61d', '1037c07996fd7ed49441f3ed7588c31e1ae3909f96552cc88d08af1c3584f61d', 'e8d2c928a9a8847d07ce395a36ce92ca00a4ef1c60e5f0f3783f0e48ffae177c'),
    ('rootn', 1099511627776, 'rdn'): ('66d862a0b294f385d06f4c949e5dd7093db980ae50e56e59bf303bbe763a8e1a', '66d862a0b294f385d06f4c949e5dd7093db980ae50e56e59bf303bbe763a8e1a', '46199b2911b2d3928616f34ed0ecbc45b06cf21ce2145a79c139a518aa919e1a'),
    ('rootn', 1099511627776, 'rup'): ('755e475bf68ee1638f6b00e26cc11b039425b7106e4aaf383c1314d2890ee581', '755e475bf68ee1638f6b00e26cc11b039425b7106e4aaf383c1314d2890ee581', 'edcf25ec926ca13d283c1c4abd8413310ea17f2101ffdb64108614c55ee3ee8f'),
    ('rootn', 1099511627776, 'rmm'): ('992fdd7e08480aa6866be02725b732c2a6b4148e67b79942967a8b5987ae424d', '992fdd7e08480aa6866be02725b732c2a6b4148e67b79942967a8b5987ae424d', 'fd1b6fa3127070c6728ec42ba8b1b400dbbac8b4708b3f41b131fd70e900aa92'),
    ('rootn', 281474976710657, 'rne'): ('f72cd2f9441a00d212c7a2b99335edf8df29f3555a8d75774f58d7e68ddd8097', 'f72cd2f9441a00d212c7a2b99335edf8df29f3555a8d75774f58d7e68ddd8097', '4c8ddaaac6acc6803fa9e71ddc93e5f03057917796bd2ddcedd63b0997239c33'),
    ('rootn', 281474976710657, 'rtz'): ('54e9fb4433ef25ab972a6092ff0f619771d6ae5a9e6bb8ae2c32546c841be998', '54e9fb4433ef25ab972a6092ff0f619771d6ae5a9e6bb8ae2c32546c841be998', '6b7014b601e491d412d9b5e8925150f17c95ee925547b277cff41f23d396dbe9'),
    ('rootn', 281474976710657, 'rdn'): ('8e967fddff948b9ebcb03f32a1d1a61e1088080a0e7b60b740f01280e6f601ac', '8e967fddff948b9ebcb03f32a1d1a61e1088080a0e7b60b740f01280e6f601ac', 'f1c8c4cbe1d2a247a068c371d30ab3f47b570471eb9322e8b2e7d577037e9b75'),
    ('rootn', 281474976710657, 'rup'): ('83739d78098aa9bb0c38c80fb42e233411db1891d8010517c4b03db7c7c6327b', '83739d78098aa9bb0c38c80fb42e233411db1891d8010517c4b03db7c7c6327b', '63ac23a1b13317f80bd720167c45d010f1dfc0e8fad678b6cbb11f3cb3c90694'),
    ('rootn', 281474976710657, 'rmm'): ('f0a6f88744158e9e3b9d87b18d55d35ea60cc9dba292d3df4a5e82c760bb7d3d', 'f0a6f88744158e9e3b9d87b18d55d35ea60cc9dba292d3df4a5e82c760bb7d3d', '3a87ce7ced419de1d6f020e06dc36e8f2c76dc038704136295965e72b364d80e'),
    ('rootn', 1, 'rne'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('rootn', 1, 'rtz'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('rootn', 1, 'rdn'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('rootn', 1, 'rup'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('rootn', 1, 'rmm'): ('bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'bde8082e862905cd882ad1ab8a8b3e993ec7870e6d8f225a37d11dcc874cb6c6', 'b118336f52ae67984a343462db4f6f965628d2ce374aad8feb99974a58e93c83'),
    ('rootn', 5, 'rne'): ('0d936f0918b3ca8661807c03157ac694f4ca862647cec112292c7e8741cdf1bc', '0d936f0918b3ca8661807c03157ac694f4ca862647cec112292c7e8741cdf1bc', 'b5103cf6054bad0d5f09b5878fa76cfebd97f74b0668b7f90855913dd7c5f5f7'),
    ('rootn', 5, 'rtz'): ('e38fba233c3f3240e80e840d369eb3d468569bfe76bf2345ee1f3edf74079323', 'e38fba233c3f3240e80e840d369eb3d468569bfe76bf2345ee1f3edf74079323', 'e5459f1c6435722ee244bd94cf007114047c8b920843b30c75867fd9df7cb88a'),
    ('rootn', 5, 'rdn'): ('506a4d0d6a3822e24bdefbd34ff005ea0552c6f2e4ac5ed403e98e5f05117c0b', '506a4d0d6a3822e24bdefbd34ff005ea0552c6f2e4ac5ed403e98e5f05117c0b', '7d9e051fe5c411568ef86252fc7a523abe0bd2f0e77acc49673effbe98d8978c'),
    ('rootn', 5, 'rup'): ('d87c9d9958e06c4853793811bba8f73c51078151f0161378d482b8f2e27f9fd5', 'd87c9d9958e06c4853793811bba8f73c51078151f0161378d482b8f2e27f9fd5', 'c6966e6696c843cda81905136594d28f072936e3c1cf9f28392ff49a570365a9'),
    ('rootn', 5, 'rmm'): ('10840b3b1533e24d1c3bb16736d41e0562883b67df207865200f72104878a9a8', '10840b3b1533e24d1c3bb16736d41e0562883b67df207865200f72104878a9a8', '0091cbdd14c1650adf8ef506398bbe5dd9d9a4fb64b7e2249f892e955bae0614'),
    ('rootn', 34359738375, 'rne'): ('fe4a25ef1d4819b754ebae7d2dc493180662658253f1aef5d1e0b4a7ea5c6472', 'fe4a25ef1d4819b754ebae7d2dc493180662658253f1aef5d1e0b4a7ea5c6472', 'c37432e645a069df4181019c92e8e385cc441415732a9368b3fdf6f67cba9e88'),
    ('rootn', 34359738375, 'rtz'): ('4e0f4895c6bc6d948bc6b40f568f2092401159e8e9006d085bed4261f9dece99', '4e0f4895c6bc6d948bc6b40f568f2092401159e8e9006d085bed4261f9dece99', '76fc46c15780aa7d659d624f7729d0b9db7a83c121b0206f0be2bc2bee9730eb'),
    ('rootn', 34359738375, 'rdn'): ('936b939039fe9652038f15b6022a619dd41cfc7892a5d9c3fbb234d6cc55621e', '936b939039fe9652038f15b6022a619dd41cfc7892a5d9c3fbb234d6cc55621e', '565f9b8fdf7f8783546079cb0b32f28b4f85b80ac1483a705536fcaeed1c241b'),
    ('rootn', 34359738375, 'rup'): ('13c51537c0adce8628367ad3197ccbd1b4876a5879c40a9e2dd2d61a5193a721', '13c51537c0adce8628367ad3197ccbd1b4876a5879c40a9e2dd2d61a5193a721', 'afaa794fc859b8a1c9e94c93bef37a46434e386d8a45080d2c3c6066c20f56c3'),
    ('rootn', 34359738375, 'rmm'): ('10ae64a28540d839ce36907a2e38448d3c36cb8be297d0607baa9b3b6e6754a0', '10ae64a28540d839ce36907a2e38448d3c36cb8be297d0607baa9b3b6e6754a0', 'cd2e76332f3781d3356ffdfe1a6310d842dd6f547880a1e4ad269d1afec369a4'),
}
REG_TOP_TW_N = {
    ('pown', 2, 'rne'): 26,
    ('pown', 2, 'rtz'): 26,
    ('pown', 2, 'rdn'): 26,
    ('pown', 2, 'rup'): 26,
    ('pown', 2, 'rmm'): 26,
    ('pown', -2, 'rne'): 26,
    ('pown', -2, 'rtz'): 26,
    ('pown', -2, 'rdn'): 26,
    ('pown', -2, 'rup'): 26,
    ('pown', -2, 'rmm'): 26,
    ('pown', 3, 'rne'): 27,
    ('pown', 3, 'rtz'): 27,
    ('pown', 3, 'rdn'): 27,
    ('pown', 3, 'rup'): 27,
    ('pown', 3, 'rmm'): 27,
    ('pown', -3, 'rne'): 27,
    ('pown', -3, 'rtz'): 27,
    ('pown', -3, 'rdn'): 27,
    ('pown', -3, 'rup'): 27,
    ('pown', -3, 'rmm'): 27,
    ('pown', 17, 'rne'): 27,
    ('pown', 17, 'rtz'): 27,
    ('pown', 17, 'rdn'): 27,
    ('pown', 17, 'rup'): 27,
    ('pown', 17, 'rmm'): 27,
    ('pown', 2147483647, 'rne'): 27,
    ('pown', 2147483647, 'rtz'): 27,
    ('pown', 2147483647, 'rdn'): 27,
    ('pown', 2147483647, 'rup'): 27,
    ('pown', 2147483647, 'rmm'): 27,
    ('pown', -9223372036854775808, 'rne'): 26,
    ('pown', -9223372036854775808, 'rtz'): 26,
    ('pown', -9223372036854775808, 'rdn'): 26,
    ('pown', -9223372036854775808, 'rup'): 26,
    ('pown', -9223372036854775808, 'rmm'): 26,
    ('pown', 1000, 'rne'): 26,
    ('pown', 1000, 'rtz'): 26,
    ('pown', 1000, 'rdn'): 26,
    ('pown', 1000, 'rup'): 26,
    ('pown', 1000, 'rmm'): 26,
    ('pown', 16777217, 'rne'): 27,
    ('pown', 16777217, 'rtz'): 27,
    ('pown', 16777217, 'rdn'): 27,
    ('pown', 16777217, 'rup'): 27,
    ('pown', 16777217, 'rmm'): 27,
    ('pown', 1099511627776, 'rne'): 26,
    ('pown', 1099511627776, 'rtz'): 26,
    ('pown', 1099511627776, 'rdn'): 26,
    ('pown', 1099511627776, 'rup'): 26,
    ('pown', 1099511627776, 'rmm'): 26,
    ('pown', 281474976710657, 'rne'): 27,
    ('pown', 281474976710657, 'rtz'): 27,
    ('pown', 281474976710657, 'rdn'): 27,
    ('pown', 281474976710657, 'rup'): 27,
    ('pown', 281474976710657, 'rmm'): 27,
    ('pown', 4611686155866341377, 'rne'): 27,
    ('pown', 4611686155866341377, 'rtz'): 27,
    ('pown', 4611686155866341377, 'rdn'): 27,
    ('pown', 4611686155866341377, 'rup'): 27,
    ('pown', 4611686155866341377, 'rmm'): 27,
    ('pown', 0, 'rne'): 1,
    ('pown', 0, 'rtz'): 1,
    ('pown', 0, 'rdn'): 1,
    ('pown', 0, 'rup'): 1,
    ('pown', 0, 'rmm'): 1,
    ('pown', 1, 'rne'): 2,
    ('pown', 1, 'rtz'): 2,
    ('pown', 1, 'rdn'): 2,
    ('pown', 1, 'rup'): 2,
    ('pown', 1, 'rmm'): 2,
    ('pown', 5, 'rne'): 27,
    ('pown', 5, 'rtz'): 27,
    ('pown', 5, 'rdn'): 27,
    ('pown', 5, 'rup'): 27,
    ('pown', 5, 'rmm'): 27,
    ('pown', 34359738375, 'rne'): 27,
    ('pown', 34359738375, 'rtz'): 27,
    ('pown', 34359738375, 'rdn'): 27,
    ('pown', 34359738375, 'rup'): 27,
    ('pown', 34359738375, 'rmm'): 27,
    ('rootn', 2, 'rne'): 25,
    ('rootn', 2, 'rtz'): 25,
    ('rootn', 2, 'rdn'): 25,
    ('rootn', 2, 'rup'): 25,
    ('rootn', 2, 'rmm'): 25,
    ('rootn', -2, 'rne'): 25,
    ('rootn', -2, 'rtz'): 25,
    ('rootn', -2, 'rdn'): 25,
    ('rootn', -2, 'rup'): 25,
    ('rootn', -2, 'rmm'): 25,
    ('rootn', 3, 'rne'): 26,
    ('rootn', 3, 'rtz'): 26,
    ('rootn', 3, 'rdn'): 26,
    ('rootn', 3, 'rup'): 26,
    ('rootn', 3, 'rmm'): 26,
    ('rootn', -3, 'rne'): 26,
    ('rootn', -3, 'rtz'): 26,
    ('rootn', -3, 'rdn'): 26,
    ('rootn', -3, 'rup'): 26,
    ('rootn', -3, 'rmm'): 26,
    ('rootn', 17, 'rne'): 26,
    ('rootn', 17, 'rtz'): 26,
    ('rootn', 17, 'rdn'): 26,
    ('rootn', 17, 'rup'): 26,
    ('rootn', 17, 'rmm'): 26,
    ('rootn', 2147483647, 'rne'): 26,
    ('rootn', 2147483647, 'rtz'): 26,
    ('rootn', 2147483647, 'rdn'): 26,
    ('rootn', 2147483647, 'rup'): 26,
    ('rootn', 2147483647, 'rmm'): 26,
    ('rootn', -9223372036854775808, 'rne'): 25,
    ('rootn', -9223372036854775808, 'rtz'): 25,
    ('rootn', -9223372036854775808, 'rdn'): 25,
    ('rootn', -9223372036854775808, 'rup'): 25,
    ('rootn', -9223372036854775808, 'rmm'): 25,
    ('rootn', 1000, 'rne'): 25,
    ('rootn', 1000, 'rtz'): 25,
    ('rootn', 1000, 'rdn'): 25,
    ('rootn', 1000, 'rup'): 25,
    ('rootn', 1000, 'rmm'): 25,
    ('rootn', 16777217, 'rne'): 26,
    ('rootn', 16777217, 'rtz'): 26,
    ('rootn', 16777217, 'rdn'): 26,
    ('rootn', 16777217, 'rup'): 26,
    ('rootn', 16777217, 'rmm'): 26,
    ('rootn', 1099511627776, 'rne'): 25,
    ('rootn', 1099511627776, 'rtz'): 25,
    ('rootn', 1099511627776, 'rdn'): 25,
    ('rootn', 1099511627776, 'rup'): 25,
    ('rootn', 1099511627776, 'rmm'): 25,
    ('rootn', 281474976710657, 'rne'): 26,
    ('rootn', 281474976710657, 'rtz'): 26,
    ('rootn', 281474976710657, 'rdn'): 26,
    ('rootn', 281474976710657, 'rup'): 26,
    ('rootn', 281474976710657, 'rmm'): 26,
    ('rootn', 1, 'rne'): 2,
    ('rootn', 1, 'rtz'): 2,
    ('rootn', 1, 'rdn'): 2,
    ('rootn', 1, 'rup'): 2,
    ('rootn', 1, 'rmm'): 2,
    ('rootn', 5, 'rne'): 26,
    ('rootn', 5, 'rtz'): 26,
    ('rootn', 5, 'rdn'): 26,
    ('rootn', 5, 'rup'): 26,
    ('rootn', 5, 'rmm'): 26,
    ('rootn', 34359738375, 'rne'): 26,
    ('rootn', 34359738375, 'rtz'): 26,
    ('rootn', 34359738375, 'rdn'): 26,
    ('rootn', 34359738375, 'rup'): 26,
    ('rootn', 34359738375, 'rmm'): 26,
}
POOL_MARKS_TW_N = {
    ('pown', 'fp32', 2): {'rne': 21, 'rtz': 21, 'rdn': 21, 'rup': 21, 'rmm': 21},
    ('pown', 'fp32', -2): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 3): {'rne': 15, 'rtz': 15, 'rdn': 15, 'rup': 15, 'rmm': 15},
    ('pown', 'fp32', -3): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 17): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 2147483647): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', -9223372036854775808): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 1000): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 16777217): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 1099511627776): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 281474976710657): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 4611686155866341377): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 0): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 1): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('pown', 'fp32', 5): {'rne': 8, 'rtz': 8, 'rdn': 8, 'rup': 8, 'rmm': 8},
    ('pown', 'fp32', 34359738375): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 2): {'rne': 6, 'rtz': 6, 'rdn': 6, 'rup': 6, 'rmm': 6},
    ('rootn', 'fp32', -2): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 3): {'rne': 4, 'rtz': 4, 'rdn': 4, 'rup': 4, 'rmm': 4},
    ('rootn', 'fp32', -3): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 17): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 2147483647): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', -9223372036854775808): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 1000): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 16777217): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 1099511627776): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 281474976710657): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 1): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 5): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
    ('rootn', 'fp32', 34359738375): {'rne': 0, 'rtz': 0, 'rdn': 0, 'rup': 0, 'rmm': 0},
}
SPECIAL_MARKS_TW_N = {
    ('pown', 'fp32', 2): (2, 2, 2, 2, 2),
    ('pown', 'fp32', -2): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 3): (2, 2, 2, 2, 2),
    ('pown', 'fp32', -3): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 17): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 2147483647): (0, 0, 0, 0, 0),
    ('pown', 'fp32', -9223372036854775808): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 1000): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 16777217): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 1099511627776): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 281474976710657): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 4611686155866341377): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 0): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 1): (0, 0, 0, 0, 0),
    ('pown', 'fp32', 5): (2, 2, 2, 2, 2),
    ('pown', 'fp32', 34359738375): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 2): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', -2): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 3): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', -3): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 17): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 2147483647): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', -9223372036854775808): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 1000): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 16777217): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 1099511627776): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 281474976710657): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 1): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 5): (0, 0, 0, 0, 0),
    ('rootn', 'fp32', 34359738375): (0, 0, 0, 0, 0),
}


def tw_n_ns(fn):
    """The n of fn's fp32 checks, in order (TW_N_NS)."""
    return TW_N_NS[fn]


@functools.lru_cache(maxsize=None)
def tw_n_build_of(fn, rnd, n, plant=None, shift=0):
    """ml.build(fn, FP32, rnd, n=n, plant=plant, bound_shift=shift), once."""
    return ml.build(fn, FP32, rnd, n=n, plant=plant, bound_shift=shift)


@functools.lru_cache(maxsize=None)
def tw_n_fragment_of(fn, rnd, n, plant=None, shift=0):
    """The build's scheduled fragment (the library's own where there is no
    plant and no shift)."""
    if plant is None and shift == 0:
        return ml.fragment(fn, FP32, rnd, n)
    return tw_n_build_of(fn, rnd, n, plant, shift).fragment()


def _tag(s, n):
    return s.replace(":", f": n = {n}:", 1)


# ---- the pools, the regions, the specials, the structured lanes, seq ----------

def check_pools_tw_n(fn, rnd, n, plant=None, step=POOL_STEP):
    """[finding], Tally: pools, at n. check_pools_n at fp32 with the model's
    pinned marks (POOL_MARKS_TW_N: the lanes pool_n takes at POOL_STEP; a
    pool with no lane of n pins 0 marks and measures nothing: the n
    2^31 - 1 and up, 2^24 + 1 and up have few or none, said by
    tw_n_pool_lanes)."""
    marks = None
    if step == POOL_STEP:
        marks = POOL_MARKS_TW_N.get((fn, "fp32", n), {}).get(
            sf.RND_NAMES[rnd])
    return check_pools_n(fn, FP32, rnd, n, plant, step, marks=marks)


def tw_n_pool_lanes(fn, n):
    """The lanes of the pool of fn at n that check_pools_tw_n runs."""
    return len(pool_n(fn, FP32, n))


def check_regions_tw_n(fn, rnd, name, count, plant=None, seed=1):
    """[finding], (lanes, marked, main-path lanes): regions, one region of
    REGION_NAMES_TW_N at its n (check_regions_n's body at fp32, with the seed
    a parameter: check_regions_n reads REGION_LANES, which has no fp32 key). A
    region with no lane returns (0, 0, 0)."""
    lanes = region_n_cached(FP32, fn, name, count, seed)
    out, n_lanes, marked, main = [], 0, 0, 0
    for n, ls in _by_n(lanes).items():
        f = fragment_n(fn, FP32, rnd, n, plant)
        o, (nl, mk) = check_regions(f, {name: ls}, first=[], evaluator=EV_N)
        out += [_tag(s, n) for s in o]
        n_lanes += nl
        marked += mk
        main += reach_n(fn, FP32, ls, n)[0]
    return out, (n_lanes, marked, main)


def check_specials_tw_n(fn, n, rnds=None, plant=None):
    """[finding], lanes: specials, at n: check_specials_n at fp32 with the
    model's marks of the row (SPECIAL_MARKS_TW_N, summed over the five
    attributes, compared where all five run)."""
    rnds = RND_MODES if rnds is None else rnds
    marks = None
    if tuple(rnds) == tuple(RND_MODES):
        rows = special_rows_n(fn, FP32, n)
        marks = {rows[0][0]: sum(SPECIAL_MARKS_TW_N[(fn, "fp32", n)])}
    return check_specials_n(fn, FP32, n, rnds, plant, marks or {})


def check_structured_tw_n(fn, rnd, n, plant=None):
    """[finding], lanes: structured, at n (check_structured_n at fp32)."""
    return check_structured_n(fn, FP32, rnd, n, plant)


def check_seq_tw_n(fn, rnd, n, plant=None, **kw):
    """[finding], lanes: seq, at n (check_seq_n at fp32): the compiled shape
    on seq.py over the pool's lanes of n, the structured lanes and the loud
    ones."""
    return check_seq_n(fn, FP32, rnd, n, plant, **kw)


# ---- the bound: V0 + V1 + V2 against mpmath, per n ------------------------------

def bound_log2_tw_n(b, lane):
    """log2(|V - f 2^-k| / Bv) for one main-path lane (x, n) of the fp32 build
    b of that n: bound_log2_tw's, the build's lane being x alone. None where V
    is exact or the screens take the lane; 999.0 where V is not finite."""
    fmt = b.fmt
    _res, _fl, pr = b.run((lane[0],), ("V0", "V1", "V2", "Bv", "th0", "nf"))
    if _screened(fmt, pr):
        return None
    try:
        V = (value(fmt, pr["V0"]) + value(fmt, pr["V1"])
             + value(fmt, pr["V2"]))
        Bv = abs(value(fmt, pr["Bv"]))
    except ValueError:
        return 999.0
    with mpmath.workprec(4 * fmt.prec + 200):
        k = int(value(fmt, pr["nf"])) // 8
        err = abs(_mp(V) - true_value(b.meta["fn"], fmt, lane)
                  * mpmath.mpf(2) ** -k)
        if err == 0:
            return None
        return float(mpmath.log(err / _mp(Bv), 2))


def check_bound_tw_n(b, lanes, label="random", need=1):
    """[finding], (worst log2(err/Bv), main-path lanes, lanes): bound, at the
    n of b. Every main-path lane (x, n) of `lanes` under 1 Bv, every lane equal
    to transcend.py in bits and flag word or marked; fewer than `need` main-path
    lanes is a finding (the region measures nothing: BOUND_NO_MAIN's are
    exempt, and the caller says NOT MEASURED, with the lane count, outside
    its pass count). The worst is the largest found, a sampled lower bound."""
    fmt, fn = b.fmt, b.meta["fn"]
    worst, n, over, differ = -1e9, 0, [], []
    for lane in lanes:
        res, fw, pr = b.run((lane[0],), ("th0",))
        if not fw & MARK and (res, fw) != golden(fmt, b.rnd, lane, fn):
            differ.append(lane)
        if not in_main_n(fn, fmt, lane) or _screened(fmt, pr):
            continue
        r = bound_log2_tw_n(b, lane)
        n += 1
        if r is None:
            continue
        worst = max(worst, r)
        if r >= 0:
            over.append((r, lane))
    where = f"bound: {fn} {fmt.name} {sf.RND_NAMES[b.rnd]} {label}"
    out = []
    if n < need and label.split()[0] not in BOUND_NO_MAIN_TW_N:
        out.append(f"{where}: only {n} of {len(lanes)} lanes reach the main "
                   f"path, {need} wanted: the region measures nothing")
    if over:
        r, lane = max(over)
        out.append(f"{where}: {len(over)} of {n} main-path lanes are past the "
                   f"bound, the worst {_hexes([lane])} at 2^{r:+.2f} of Bv")
    if differ:
        out.append(f"{where}: {len(differ)} unmarked lanes differ from "
                   f"transcend.{fn}, first {_hexes([differ[0]])}")
    return out, (worst, n, len(lanes))


def check_bound_tw_n_region(fn, rnd, name, lanes):
    """[finding], (worst, main-path lanes, lanes): the bound over one region's
    lanes at each of its n (check_bound_tw_n on the build of that n)."""
    out, worst, main, total = [], -1e9, 0, 0
    for n, ls in _by_n(lanes).items():
        o, (w, m, t) = check_bound_tw_n(tw_n_build_of(fn, rnd, n), ls,
                                        f"{name} n = {n}")
        out += o
        worst, main, total = max(worst, w), main + m, total + t
    return out, (worst, main, total)


def bound_regions_tw_n(fn, rnd=RNE, count=8, seed=11, names=None):
    """[finding], {region: (worst, main-path lanes, lanes)}: the bound over the
    function's regions at fp32 (REGION_NAMES_TW_N), `count` lanes each at that
    region's n (region_n at fp32). A region with no lane at all is in the dict
    at (-1e9, 0, 0) and a region none of whose lanes reaches the main path at
    0 main-path lanes: both are NOT MEASURED (not_measured_tw_n), outside any
    pass count. n = 2 and -2 have no region."""
    out, worst = [], {}
    for name in (names or REGION_NAMES_TW_N):
        lanes = region_n_cached(FP32, fn, name, count, seed)
        if not lanes:
            worst[name] = (-1e9, 0, 0)
            continue
        w = [-1e9, 0, 0]
        for n, ls in _by_n(lanes).items():
            found, (wn, mn, tn) = check_bound_tw_n(
                tw_n_build_of(fn, rnd, n), ls, f"{name} n = {n}")
            out += found
            w = [max(w[0], wn), w[1] + mn, w[2] + tn]
        worst[name] = tuple(w)
    return out, worst


def not_measured_tw_n(worst):
    """[(region, main-path lanes, lanes)] of the regions that measured
    NOTHING: those of `worst` with 0 main-path lanes. They are outside the
    pass count."""
    return sorted((name, w[1], w[2]) for name, w in worst.items()
                  if w[1] == 0)


# ---- the shape, the registers, the port, per n -------------------------------------

def check_registers_tw_n(fn, n, frags, tops=None):
    """[finding]: shape. routines.program accepts the fragment of fn at n
    under each attribute of `frags` {rnd: Fragment}, its highest register is
    REG_TOP_TW_N's, and POW_LIVE_CAP's fp32 row (pown 28, rootn 27) is at
    least the most values live here (the cap is the maximum over every n of
    the list, so equal at the odd n and one more at the even)."""
    tops = REG_TOP_TW_N if tops is None else tops
    out = []
    for rnd, f in frags.items():
        where = f"shape: n = {n}: {fn} fp32 {sf.RND_NAMES[rnd]}"
        try:
            prog, _bank = routines.program(f)
        except AssertionError as e:
            out.append(f"{where}: routines.program refuses it: {e}")
            continue
        got = highest_register(prog)
        want = tops[(fn, n, sf.RND_NAMES[rnd])]
        if got != want:
            out.append(f"{where}: the highest register is r{got}, pinned "
                       f"r{want}")
        if f.live_max() > ml.POW_LIVE_CAP[fn]["fp32"]:
            out.append(f"{where}: {f.live_max()} values live, past "
                       f"POW_LIVE_CAP's {ml.POW_LIVE_CAP[fn]['fp32']}")
    return out


def check_caps_tw_n(fn, ns=None, caps=None, fragments=None):
    """[finding]: shape. check_caps_n at fp32 over the n of `ns` (default
    TW_N_NS[fn] and TW_N_CAP_EXTRA_NS) under all five attributes: the cap is
    the most values live over them, and a cap one under fails by name."""
    ns = tuple(TW_N_NS[fn]) + TW_N_CAP_EXTRA_NS if ns is None else ns
    frags = fragments or {(n, rnd): tw_n_fragment_of(fn, rnd, n)
                          for n in ns for rnd in RND_MODES}
    return check_caps_n(fn, FP32, ns, caps=caps, fragments=frags)


def check_port_tw_n(fn, n, builds, digests=None, fragments=None):
    """[finding]: port. The Build's dag_digest (the design's order), the
    scheduled fragment's dag_digest and its emitted order, each against the
    model's literal (DIGESTS_TW_N), and every instruction's label a name of
    _POW_TW_PHASE_MAP whose phase is a PHASE_ORDER name. `builds` {rnd:
    Build}."""
    digests = DIGESTS_TW_N if digests is None else digests
    out = []
    for rnd, b in builds.items():
        where = f"port: n = {n}: {fn} fp32 {sf.RND_NAMES[rnd]}"
        f = fragments[rnd] if fragments else b.fragment()
        got = (ml.dag_digest(b.fragment(schedule=False)), ml.dag_digest(f),
               order_digest(f))
        for what, g, w in zip(("the Build's dag digest",
                               "the scheduled fragment's dag digest",
                               "the emitted order"),
                              got, digests[(fn, n, sf.RND_NAMES[rnd])]):
            if g != w:
                out.append(f"{where}: {what} is {g[:16]}, the model's is "
                           f"{w[:16]}")
        if n in (0, 1):
            continue
        keep = b.live_indices()
        if len(b.label_of) != len(b.body):
            out.append(f"{where}: {len(b.label_of)} labels for "
                       f"{len(b.body)} instructions")
            continue
        bad = [i for i in keep
               if ml._POW_TW_PHASE_MAP.get(b.label_of[i]) not in ml.PHASE_ORDER
               or b.phase_of[i] not in ml.PHASE_ORDER]
        if bad:
            out.append(f"{where}: {len(bad)} instructions whose label maps "
                       f"to no PHASE_ORDER name or whose phase is not in "
                       f"PHASE_ORDER, first {b.label_of[bad[0]]!r}")
    return out


def check_shape_tw_n(fn, n, builds=None, fragments=None, plant=None):
    """[finding]: shape, at n and fp32: check_shape_n with the model's pins
    (PINS_TW_N: instructions, bank words, live, dag digest, the instructions by
    phase) and Fast2Sum and TwoSum counts (EFT_TW_N), the flag words, no MIN
    or MAX, the reordered design and the invariants under POW_LIVE_CAP; then
    the registers (check_registers_tw_n) and the port (check_port_tw_n).
    n = 0 and 1 are the small fragments (no phases, no digests of a core):
    their pins are the model's build_small's."""
    builds = builds or {rnd: tw_n_build_of(fn, rnd, n, plant)
                        for rnd in RND_MODES}
    frags = fragments or {rnd: b.fragment() for rnd, b in builds.items()}
    out = check_shape_n(fn, FP32, n, RND_MODES, plant, pins=PINS_TW_N,
                        eft=EFT_TW_N, fragments=frags, builds=builds)
    out += check_registers_tw_n(fn, n, frags)
    out += check_port_tw_n(fn, n, builds, fragments=frags)
    return out


# ---- the constants ---------------------------------------------------------------

def check_constants_tw_n(**kw):
    """[finding], lines: constants. mathlib.check_pow_tw_n_constants() in
    process."""
    lines, findings = ml.check_pow_tw_n_constants(**kw)
    return [f"constants: {s}" for s in findings], lines


def check_constants_cli_tw_n():
    """[finding], output: constants. `python -m cft_golden.mathlib --check
    --only pow-tw` in a process of its own, exit 0, listing pown and rootn
    after pow and powr and ending with the integer operand's count line,
    `0 differences`, the pow-tw line before it unchanged."""
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--check", "--only", "pow-tw"], capture_output=True,
                       text=True, cwd=ROOT / "python")
    out = r.stdout.strip().splitlines()
    findings = []
    if r.returncode != 0:
        findings.append(f"constants: --check --only pow-tw exited "
                        f"{r.returncode}")
    want = (f"mathlib --check (pow, triple word, integer operand): "
            f"{len(ml._POW_TW_N_BUILDERS)} routines, 1 format, 0 differences")
    if want not in out:
        findings.append(f"constants: the integer operand's count line is "
                        f"not there: {want!r}; the last line is "
                        f"{out[-1] if out else r.stderr[-200:]!r}")
    # the integer operand's lines come BEFORE pow-tw's, whose last line a test
    # of parcel M3F1's pins: pow-tw's count line stays the last
    if not out or out[-1] != ("mathlib --check (pow, triple word): 2 "
                              "routines, 1 format, 0 differences"):
        findings.append("constants: pow-tw's own count line is not the "
                        "last, unchanged")
    n = sum(1 for ln in out if ln.split(" ")[0] in ml._POW_TW_N_BUILDERS
            and "(triple word, integer operand)" in ln)
    if n != len(ml._POW_TW_N_BUILDERS):
        findings.append(f"constants: {n} routine lines, "
                        f"{len(ml._POW_TW_N_BUILDERS)} wanted")
    return findings, out


# ---- the plants: every check on every plant ----------------------------------------

def red_checks_tw_n(plant, fn="pown", n=3, rnds=(RNE,), region_count=6,
                    bound_count=6, pool_step=3, shift=0):
    """{check: [findings]} for CHECKS_TW_N, EVERY key present (a check that
    is green has an empty list; one in `not_run` is absent from the run and
    on `plant` (None: the control) at fp32 on `fn` at
    n: pools at pool_step, regions (the regions whose n is this n; the
    check's own lanes), specials under `rnds` and structured under rne, seq
    under rne, bound over the regions of that n, shape under all five (where
    the plant reaches all five) and constants under rne. A plant the build
    cannot reach is refused by name. GREEN means green at this scope."""
    red = {name: [] for name in CHECKS_TW_N}
    reach = []
    for rnd in RND_MODES:
        try:
            tw_n_build_of(fn, rnd, n, plant, shift)
        except ValueError as e:
            if "does not apply" not in str(e):
                raise
            continue
        reach.append(rnd)
    if not reach:
        raise ValueError(f"plant {plant!r} does not apply to {fn} at fp32, "
                         f"n = {n}, under any attribute")
    rnds = tuple(r for r in rnds if r in reach) or (reach[0],)
    names = [r for r in REGION_NAMES_TW_N if region_n_of(r) == n]
    for rnd in rnds:
        red["pools"] += check_pools_tw_n(fn, rnd, n, plant, pool_step)[0]
        for name in names:
            red["regions"] += check_regions_tw_n(fn, rnd, name, region_count,
                                                 plant)[0]
    red["specials"] += check_specials_tw_n(fn, n, rnds, plant)[0]
    red["structured"] += check_structured_tw_n(fn, rnds[0], n, plant)[0]
    red["seq"] += check_seq_tw_n(fn, rnds[0], n, plant)[0]
    b = tw_n_build_of(fn, RNE, n, plant, shift)
    for name in names:
        lanes = region_n_cached(FP32, fn, name, bound_count, 11)
        red["bound"] += check_bound_tw_n(b, lanes, name)[0]
    if len(reach) == len(RND_MODES):
        red["shape"] += check_shape_tw_n(fn, n, plant=plant)
    red["constants"] += check_constants_tw_n(
        builder=lambda name, f_, r_, n_: tw_n_build_of(name, r_, n_, plant,
                                                       shift),
        attrs=(RNE,), names=(fn,), ns=(n,))[0]
    return red
