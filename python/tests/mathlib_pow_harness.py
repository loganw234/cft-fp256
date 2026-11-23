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
               failure; the rule "a mark off a list fails" is parcel M3G3's, from
               the study's 3.5)
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
               parcel M3G3's, this is the direct error
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
    fails" is parcel M3G3's: the count here is the model's, not a list."""
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
    worst; the study's budget is parcel M3G3's."""
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
    are a sample (the budget at 10,000 lanes is parcel M3G3's)."""
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

def check_core_n(fn, fmt, rnd=RNE, plant=None, lanes=None):
    """[finding], (worst, lanes, n_l signs): core, at fp64 for pown and
    compound. (1) The double-word Y path on real lanes: the nlow region's
    lanes (n_l of both signs) through the build of their n, |V - f| / Bv under
    1 by mpmath (bound_log2), a finding where one sign of n_l is missing among
    the main-path lanes. (2) The Fraction ybound, on lanes of each function at
    n = 3 and at fp64's n_l lanes: the build's own Bv equal to the exact bound
    |V| (2^-(p+G) + |t_h| B1 + |Y_h k| B2) rounded upward (_check_ybound's
    rule), where B2 is not 0 (fp64) and the term is absent where it is 0."""
    out = []
    p, G = fmt.prec, ml.GUARD[fmt.name]
    P = ml.plan_pow(fmt, G)
    worst, n_main, signs = -1e9, 0, set()
    if fn in ("pown", "compound") and fmt.name == "fp64":
        lanes = region_n_cached(fmt, fn, "nlow", 40, 5) if lanes is None \
            else lanes
        for n, ls in _by_n(lanes).items():
            b = build_n(fn, fmt, rnd, n, plant)
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
            b = build_n(fn, fmt, rnd, n, plant)
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
# reached by any of the three, and the plants of the budget are parcel M3G3's.

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
