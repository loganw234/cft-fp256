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
import importlib.util
import math
import random
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
    (x, y). Cached, since a plant re-runs the lanes of the clean fragment."""
    return transcend.compute(fmt, fn, lane[0], lane[1], rnd)


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
        results = [ml.evaluate(f, x) for x in xs]
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
    outs, words = routines.run(f, *_split(xs))
    got = list(zip(outs, words))
    true = [ml.evaluate(f, x) for x in xs]
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
    res = seq.run(prog, *_split(xs), bank=bank)
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
    _res, _fl, pr = b.run(lane, ("Vh", "Vl", "Bv", "th0", "nf"))
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
        res, fw, pr = b.run(lane, ("th0",))
        if not fw & MARK and (res, fw) != golden(fmt, b.rnd, lane, fn):
            differ.append(lane)
        if not in_main(fn, fmt, lane) or _screened(fmt, pr):
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
#
# (assign into POOL_FNS, TRUE_FNS, POOL_SIZES, POOL_MARKS, REGION_NAMES,
# REGION_LANES, FIRST_LANES, SPECIAL_ROWS, SPECIAL_MARKS, STRUCT_ROWS, SHAPE,
# EFT, FLAG_WORDS, MIN_MAX, PHASES_RNE and PHASE_DELTA, and extend plant_cases'
# rows through a table of its own and POWR_ONLY's analogue; do not edit the
# checks above)

# ---- fp32: the triple word, pow and powr (parcel M3F1) builds here ----
#
# (the same tables, for FP32, in a section of its own; FORMATS is the double
# word's three and stays)
