# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The lanes, the measurements and the checks parcel M2G2a holds the fragments
of sin, cos and tan to (cft_golden/mathlib.py; docs/studies/M2-trig.md, section
8), gathered in one place so that python/tests/test_mathlib_trig.py (quick, for
the golden stage) and python/tests/mathlib_runs.py (the larger runs, for the
lead's box: trig-pools and trig-bound) run the same lanes and the same checks.

A CHECK takes a fragment or its instrumented build and returns FINDINGS: a
list of strings, each beginning with the check's name and a colon, empty when
it holds (mathlib_harness's convention); one that measures also returns what
it measured. A planted fault is "caught by name" when the check it is meant for
returns a finding that begins with that name. mathlib_harness.py is imported,
never edited: its checks name the six (its TRANSCEND table has no sin, cos or
tan) and its pools are the exp pools, so these are beside them, not in them.

  pools        the radian pools through one fragment, at one format and
               attribute: every unmarked lane equal to transcend.py in bits AND
               flag word; every marked lane replayed and its guess counted; a
               lane at or past the stated range (fp128, fp256) MARKED, its guess
               not counted; every other mark on the committed list
               (TRIG_POOL_MARKS), and every listed lane marked
  seq          the fragment as a stand-alone program on seq.py
               (routines.program and routines.run) equal to evaluate() lane by
               lane and to transcend.py where unmarked; and the compiled shape
               (mathlib_harness.r24_program, imported): each lane's byte is the
               operation's IEEE flags with the mark in bit 7, FLAGS the OR of
               the bytes, STATUS[6] set exactly when a lane is marked, and the
               structured lanes of the configuration (fp64: cos at 2^-26 under
               rtz, the study's card case) marked
  bound        |V - f(x)| / Bv under 1, mpmath at 4p + 200 bits, at placed
               points of the study's five regions (edge, near, zero, small,
               random: 3.2) and the deepest cancellations, each lane also
               against transcend.py. The largest is a sampled lower bound
  structured   the committed centres that must mark (plants.py's STRUCT: at
               fp64 cos at 2^-26, 2^-25, 3 2^-26 and 2^-24 under rtz, rdn and
               rup, tan at 3 2^-26 under rne and rmm, both signs): each marked,
               its guess equal to transcend.py's. The full families are parcel
               M2G2b's
  specials     the study's section 4, row by row, both signs: NaNs, infinities,
               zeros, subnormals, the minimum normal, the largest tiny and the
               smallest non-tiny float at each gate, the maximum normal; and
               past the range at fp128 and fp256 2^R and the largest finite
               marked, 2^R's predecessor decided
  shape        the fragment's instructions, words and live values pinned; its
               instructions by phase the model's; its flag word's values the
               study's; MIN and MAX in sin and cos only; the scheduled
               fragment the design's reordered (mathlib_harness.check_reorder);
               TRIG_LIVE_CAP the measured maximum, a cap one under failing by
               name; and the three of one format and attribute alike
               instruction for instruction before `select`, so that cftc's
               sharing holds (2.1), their sum the model's
  audit        reduction_audit() on the routines' own builds over the slice and
               the products' binade edges: every claim of exactness holds
  constants    mathlib.check_trig_constants(), in process

Parcel M2G2b adds, at the end of this file, the mark-rate law and the checks of
the structured families (the budget is mathlib_trig_budget.py's, the theory of
the families mathlib_trig_family.py's):

  rate         the mark-rate law (the study's 3.4) with the bound inflated to
               G' = 6 through bound_shift: the count of marks against the
               sample's own expectation, each lane's 2^-G' times the
               significand of its true value, judged by its exact two-sided
               tail under the six's calibration (parcel RC: mathlib_harness's
               RateSample), every unmarked lane right and every marked guess
               right
  family       the structured lanes (the committed centres and their
               neighbours, the census arguments that are not centres, the deep
               arguments): every lane the theory puts inside a window (d under
               0.7 of the bound) marked, none outside (d over 1.3), none wrong
               unmarked, every marked guess right (MB1's rule)
  windows      each centre's window against the half-width the study's 3.5
               computes: the neighbours inside it marked and outside it not, at
               every format and attribute, and the marked run of the study's
               measured windows
  census_counts  the tiny family's and the minimisers' neighbours' marked
               counts at the decided G equal the study's tables
  family_list  the committed centres against a fresh generation by the theory
  pool_marks   every structured mark of TRIG_POOL_MARKS is a centre, or inside
               a window, of the generated families
"""

import collections
import functools
import math
import random
import sys
from fractions import Fraction
from pathlib import Path

import mpmath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import FP32, FP64, FP128, FP256, routines, seq  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import transcend, vectors  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_trig_family as TF  # noqa: E402

# FORMATS are the double word's, the three the parametrized tests of
# test_mathlib_trig.py iterate and their pinned lists name; ALL_FORMATS adds
# fp32, the triple word (parcel M2F2), which has tests of its own
# (test_mathlib_trig_tw.py) and which the box commands of mathlib_runs.py take
# beside them
FORMATS = (FP64, FP128, FP256)
ALL_FORMATS = FORMATS + (FP32,)
FUNCS = ml.TRIG_NAMES                   # sin, cos, tan
RND_MODES = sf.RND_MODES                # rne, rtz, rdn, rup, rmm
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
MARK = ml.MARK
BY_NAME = {f.name: f for f in ALL_FORMATS}
RND_BY_NAME = {v: k for k, v in sf.RND_NAMES.items()}


# ---- the definition, memoised -----------------------------------------------

@functools.lru_cache(maxsize=None)
def golden(fmt, rnd, x, fn):
    """transcend.py's sin, cos or tan: the definition, (bits, flag word).
    Cached, since a plant re-runs the lanes of the clean fragment."""
    return transcend.compute(fmt, fn, x, 0, rnd)


def value(fmt, bits):
    return ml._dec(fmt, bits)


def _mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


def true_value(fn, xv):
    """sin, cos or tan of the exact rational xv, by mpmath at the caller's
    working precision."""
    x = _mp(xv)
    return {"sin": mpmath.sin, "cos": mpmath.cos, "tan": mpmath.tan}[fn](x)


# ---- the pools --------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def radian_pools(fmt):
    """The radian pools, deduplicated and sorted: the stage's
    (host/tests/transcend_check.py's radian_pool at its default trials, 64
    random encodings at fp64 and 16 at fp128 and fp256, and seed 5), the
    vector sets' (vectors.radian_unary_pool as transcend_cases calls it: 24
    extra and seed 14) and test_transcend's brute pool. 4,408, 620 and 614
    arguments at fp64, fp128 and fp256 (MEASURED by the parcel's entry)."""
    from test_transcend import _brute_pool
    t = 64 if fmt.width <= 64 else 16
    a = H._transcend_check().radian_pool(fmt, t, 5)
    b = vectors.radian_unary_pool(fmt, 24, 14)
    return tuple(sorted(set(a) | set(b) | set(_brute_pool(fmt))))


def past_range(fmt, x):
    """Whether the finite argument x is at or past the stated range, |x| >=
    2^R (fp128, fp256), where the lane is marked whatever the test says."""
    R = ml.TRIG_RANGE[fmt.name]
    if R is None or sf.unpack(fmt, x).kind in (sf.NAN, sf.INF):
        return False
    return (x & ~fmt.sign_mask) >= ml._pow2(fmt, R)


def in_main(fmt, fn, x):
    """Whether the main path answers x: finite, nonzero, not under the tiny
    gate (2^gs for sin, 2^gc for cos and tan) and inside the range."""
    if sf.unpack(fmt, x).kind in (sf.NAN, sf.INF, sf.ZERO):
        return False
    gs, gc = ml.trig_gates(fmt)
    if (x & ~fmt.sign_mask) < ml._pow2(fmt, gs if fn == "sin" else gc):
        return False
    return not past_range(fmt, x)


# The marks of the pools that are neither past the range nor a fault: every
# (function, format, attribute, argument, reason) of the whole radian pools
# (the three pools above, 4,408, 620 and 614 arguments) through all 45
# fragments, MEASURED by the parcel's entry (84,630 lanes: 0 wrong unmarked, and
# these the only marks that are not past the range, each with a right guess).
# They are the structured centres of the study's 3.5: cos(x) with x^2/2 a
# multiple of 2^-p, whose true value sits x^4/24 above the float 1 - x^2/2,
# within the in-lane bound of it, under the directed three; tan(x) with x^3/3 an
# odd multiple of half an ulp of x, within the bound of a midpoint, under rne and
# rmm. A lane marked off this list fails the pools; a listed lane not marked
# fails them.
_COS_MARK = ("cos(x) = 1 - x^2/2 + x^4/24 with x^2/2 a multiple of 2^-p: the "
             "true value is x^4/24 above the float 1 - x^2/2, within the "
             "in-lane bound of it")
_TAN_MARK = ("tan(x) = x + x^3/3 + ... with x^3/3 = 4.5 ulp(x): the true value "
             "is within the in-lane bound of a midpoint")


def _marks(fn, fmt, rnds, lanes, reason):
    return tuple((fn, fmt, r, x, reason) for r in rnds for x in lanes)


TRIG_POOL_MARKS = (
    _marks("cos", "fp64", ("rtz", "rdn", "rup"),
     (0x3e50000000000000, 0x3e60000000000000, 0x3e68000000000000,
      0x3e70000000000000, 0xbe50000000000000, 0xbe60000000000000,
      0xbe68000000000000, 0xbe70000000000000),
     _COS_MARK) +
    _marks("tan", "fp64", ("rne", "rmm"),
     (0x3e68000000000000, 0xbe68000000000000),
     _TAN_MARK) +
    _marks("cos", "fp128", ("rtz", "rdn", "rup"),
     (0x3fc70000000000000000000000000000,
      0x3fc80000000000000000000000000000,
      0x3fc88000000000000000000000000000,
      0xbfc70000000000000000000000000000,
      0xbfc80000000000000000000000000000,
      0xbfc88000000000000000000000000000),
     _COS_MARK) +
    _marks("tan", "fp128", ("rne", "rmm"),
     (0x3fc88000000000000000000000000000,
      0xbfc88000000000000000000000000000),
     _TAN_MARK) +
    _marks("cos", "fp256", ("rtz", "rdn", "rup"),
     (0x3ff8900000000000000000000000000000000000000000000000000000000000,
      0x3ff8a00000000000000000000000000000000000000000000000000000000000,
      0x3ff8a80000000000000000000000000000000000000000000000000000000000,
      0xbff8900000000000000000000000000000000000000000000000000000000000,
      0xbff8a00000000000000000000000000000000000000000000000000000000000,
      0xbff8a80000000000000000000000000000000000000000000000000000000000),
     _COS_MARK) +
    _marks("tan", "fp256", ("rne", "rmm"),
     (0x3ff8a80000000000000000000000000000000000000000000000000000000000,
      0xbff8a80000000000000000000000000000000000000000000000000000000000),
     _TAN_MARK))


@functools.lru_cache(maxsize=None)
def pool_marks(fn, fmt_name, rnd_name):
    return {lane: reason for f_, n_, r_, lane, reason in TRIG_POOL_MARKS
            if (f_, n_, r_) == (fn, fmt_name, rnd_name)}


class Tally:
    """The lanes of one run: n; the marked lanes (not past the range) and how
    many guesses were right; the past-range lanes marked and unmarked; the
    unmarked lanes that were wrong; the marks off the list; the listed lanes
    not marked; and the flag words with stray bits."""

    def __init__(self):
        self.n = 0
        self.marked = []
        self.guess_wrong = []
        self.range_marked = []
        self.range_unmarked = []
        self.wrong = []
        self.off = []
        self.missing = []
        self.stray = []

    @property
    def marked_right(self):
        return len(self.marked) - len(self.guess_wrong)


def _hexes(xs, k=3):
    return ", ".join(hex(x) for x in list(xs)[:k])


def check_pools(f, xs=None, results=None, marks=None):
    """[finding], Tally: pools. `xs` the lanes (the radian pools by default),
    `results` their (bits, flag word) if the caller has them, `marks` the
    committed list {lane: reason} (TRIG_POOL_MARKS' part for this fragment
    by default)."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    xs = radian_pools(fmt) if xs is None else xs
    if results is None:
        results = [ml.evaluate(f, x) for x in xs]
    allowed = pool_marks(fn, fmt.name, sf.RND_NAMES[rnd]) if marks is None \
        else marks
    t = Tally()
    for x, (bits, fw) in zip(xs, results):
        gb, gf = golden(fmt, rnd, x, fn)
        t.n += 1
        if fw & ~(MARK | 0x1F):
            t.stray.append((x, fw))
        marked = bool(fw & MARK)
        if past_range(fmt, x):
            (t.range_marked if marked else t.range_unmarked).append(x)
        elif marked:
            t.marked.append(x)
            if x not in allowed:
                t.off.append(x)
            if (bits, fw & 0x1F) != (gb, gf):
                t.guess_wrong.append((x, bits, gb))
        else:
            if (bits, fw) != (gb, gf):
                t.wrong.append((x, (bits, fw), (gb, gf)))
            if x in allowed:
                t.missing.append(x)
    where = f"pools: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if t.wrong:
        x, got, want = t.wrong[0]
        out.append(f"{where}: {len(t.wrong)} unmarked lanes differ from "
                   f"transcend.{fn}, first {hex(x)}: got ({got[0]:#x}, "
                   f"{got[1]:#x}), want ({want[0]:#x}, {want[1]:#x})")
    if t.stray:
        out.append(f"{where}: {len(t.stray)} flag words carry bits other "
                   f"than [4:0] and the mark, first {hex(t.stray[0][0])}")
    if t.range_unmarked:
        out.append(f"{where}: {len(t.range_unmarked)} lanes at or past "
                   f"2^{ml.TRIG_RANGE[fmt.name]} are not marked, first "
                   f"{_hexes(t.range_unmarked)}")
    if t.off:
        out.append(f"{where}: {len(t.off)} lanes are marked off the committed "
                   f"list (TRIG_POOL_MARKS), first {_hexes(t.off)}")
    if t.missing:
        out.append(f"{where}: {len(t.missing)} lanes on the committed list "
                   f"are not marked, first {_hexes(t.missing)}")
    return out, t


# ---- builds, memoised --------------------------------------------------------

@functools.lru_cache(maxsize=None)
def build_of(fn, fmt, rnd, plant=None):
    """ml.build(fn, fmt, rnd, plant=plant), once. A Build is never mutated by
    a check, so the tests share them."""
    return ml.build(fn, fmt, rnd, plant=plant)


@functools.lru_cache(maxsize=None)
def fragment_of(fn, fmt, rnd, plant=None):
    """The build's fragment, scheduled (the library's own for no plant)."""
    return build_of(fn, fmt, rnd, plant).fragment()


# ---- the placed points: the study's five regions ------------------------------

REGIONS = ("edge", "near", "zero", "small", "random")
# fp32's triple word has a sixth, parcel M2X's `quad` (tw32_box.sh): the floats
# next to the odd multiples of pi/4 from k = 0, in every binade, where |r| is
# next to pi/4 and the polynomials' rho acts. The box runs it, and it needs
# numpy (quad_sample)
REGIONS_TW = REGIONS + ("quad",)
_QUAD = {}


def quad_sample(fmt, n, seed):
    """n of the quadrant-boundary arguments of fp32 (parcel M2X's
    tw32.quad_sample): quad_family (the floats within 3 ulps of (k + 1/2) pi/2,
    k = 0 to 63 and 128 random k, both signs) and half_family (the odd
    multiples of pi/4 in every binade, both signs; numpy), 18,266 in all, drawn
    by `seed` (all of them if fewer). parcel M2F1's test_mathlib_reduction_tw
    builds both families (its positive half family and both signs of its quad
    family are the model's)."""
    if fmt.name != "fp32":
        raise ValueError(f"the region 'quad' is fp32's, not {fmt.name}'s")
    if "quad" not in _QUAD:                    # about 9 s, once a process
        import test_mathlib_reduction_tw as W
        half = W.half_family()
        _QUAD["quad"] = sorted(set(W.quad_args()) | set(half)
                               | {x | fmt.sign_mask for x in half})
    fam = _QUAD["quad"]
    return sorted(random.Random(seed).sample(fam, n)) if n < len(fam) else fam


def sample(fmt, mode, n, seed):
    """n arguments of a region of the study's 3.2 (docs/studies/m2/
    m2measure.py's sample, ported): random (every bit of x random, its
    exponent uniform from the tiny gate to the range's top), edge (x within 3
    ulps of (k + 1/2) pi/2, k odd and random in the range's bits, so |r| is
    near pi/4), near (within 3 ulps of k pi/2, k odd: r small, the
    cancellation deep, where cos is small and tan large), zero (the same at
    even k, where sin and tan are small) and small (|x| from the tiny gate to
    4). Both signs. A function of (format, mode, seed). fp32 also has `quad`
    (REGIONS_TW)."""
    if mode == "quad":
        return quad_sample(fmt, n, seed)
    rng = random.Random(seed * 1000003 + fmt.width)
    p = fmt.prec
    gs, gc = ml.trig_gates(fmt)
    R = ml.TRIG_RANGE[fmt.name]
    Emax = (R - 1) if R else fmt.emax
    pio2 = ml._pi() / 2
    out = []
    for _ in range(n):
        if mode == "random":
            E = rng.randint(min(gs, gc), Emax)
            m = rng.getrandbits(p - 1) | (1 << (p - 1))
            out.append(sf.round_pack(fmt, rng.getrandbits(1), m, E - p + 1,
                                     RNE)[0])
        elif mode in ("edge", "near", "zero"):
            E = rng.randint(1, Emax)
            k = rng.getrandbits(max(1, E)) | 1
            if mode == "zero":
                k = max(2, k - 1)
            v = (Fraction(k) + (Fraction(1, 2) if mode == "edge" else 0)) \
                * pio2
            b = ml._enc(fmt, v) + rng.randint(-3, 3)
            if rng.getrandbits(1):
                b |= fmt.sign_mask
            out.append(b)
        elif mode == "small":
            E = rng.randint(min(gs, gc), 2)
            m = rng.getrandbits(p - 1) | (1 << (p - 1))
            out.append(sf.round_pack(fmt, rng.getrandbits(1), m, E - p + 1,
                                     RNE)[0])
        else:
            raise ValueError(f"{mode!r} is not one of {REGIONS}")
    return out


@functools.lru_cache(maxsize=None)
def deepest(fmt):
    """The deepest cancellations the pools carry (host/tools/pi_worstcase.py's
    minimisers and their neighbours, both signs: transcend_check.WORST_SWEEP's
    stride and top)."""
    tc = H._transcend_check()
    stride, top = tc.WORST_SWEEP[fmt.name]
    return tuple(sorted(set(tc.pi_worstcase.worst_encodings(fmt, stride,
                                                            top))))


@functools.lru_cache(maxsize=None)
def deepest_in_range(fmt):
    """The deepest cancellations INSIDE the stated range, both signs. fp64's
    are the pools' (pi_worstcase's minimisers: fp64 has no range). The pools'
    at fp128 and fp256 are past 2^1024, where the lane is marked and the bound
    is not consulted, so the range's own deepest are used with them: the
    study's 1.4, worst_range.py's MEASURED figures (value exponent 909 at
    fp128, 239 at fp256; test_mathlib_reduction.DEEP) and two neighbours
    either side. fp32 (parcel M2F2) has no range, as fp64: the pools' own."""
    inside = {x for x in deepest(fmt) if not past_range(fmt, x)}
    if fmt.name not in ("fp32", "fp64"):
        import test_mathlib_reduction as R
        for x in R.deep_args(fmt):
            inside |= {x, x | fmt.sign_mask}
    return tuple(sorted(inside))


@functools.lru_cache(maxsize=None)
def pool_slice(fmt, n=64):
    """plants.py's slice of the pools (docs/studies/m2/plants.py, the study's
    8): test_transcend's brute pool, the deepest cancellations, every 16th
    power of two of the stage's pool and n random main-path arguments (seed
    11): 387 arguments at fp64."""
    from test_transcend import _brute_pool
    tc = H._transcend_check()
    stage = tc.radian_pool(fmt, 64 if fmt.width <= 64 else 16, 5)
    out = set(_brute_pool(fmt)) | set(deepest(fmt))
    powers = sorted(b for b in stage if (b & fmt.man_mask) == 0)
    out |= set(powers[::16])
    out |= set(sample(fmt, "random", n, 11))
    return tuple(sorted(out))


# ---- the structured centres ----------------------------------------------------

# The committed list of the structured arguments that must mark (the study's
# 3.5, plants.py's STRUCT, census.py's): by format, (function, the attributes,
# the centres as exact values). A centre is a float whose true value sits
# within the in-lane bound of a rounding boundary of its attribute.
STRUCT = {"fp64": [("cos", (RTZ, RDN, RUP),
                    [Fraction(1, 2 ** 26), Fraction(1, 2 ** 25),
                     Fraction(3, 2 ** 26), Fraction(1, 2 ** 24)]),
                   ("tan", (RNE, RMM), [Fraction(3, 2 ** 26)])]}


def structured_lanes(fn, fmt, rnd):
    """The committed centres of (fn, fmt, rnd), both signs: encodings."""
    out = []
    for f_, rnds, vals in STRUCT.get(fmt.name, []):
        if f_ == fn and rnd in rnds:
            for v in vals:
                out += [ml._enc(fmt, v), ml._enc(fmt, v) | fmt.sign_mask]
    return out


def check_structured(f, evaluator=None):
    """[finding], lanes: structured. Each committed centre of the fragment's
    (function, format, attribute) marked, its guess equal to transcend.py's.
    The configurations the list has no centres for pass with none run.
    `evaluator` stands for ml.evaluate, for the test that plants a fault in
    it."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    lanes = structured_lanes(fn, fmt, rnd)
    unmarked, wrong = [], []
    for x in lanes:
        bits, fw = (evaluator or ml.evaluate)(f, x)
        if not fw & MARK:
            unmarked.append(x)
            continue
        if (bits, fw & 0x1F) != golden(fmt, rnd, x, fn):
            wrong.append(x)
    where = f"structured: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if unmarked:
        out.append(f"{where}: {len(unmarked)} of the {len(lanes)} committed "
                   f"centres are not marked, first {_hexes(unmarked)}")
    if wrong:
        out.append(f"{where}: {len(wrong)} marked centres have a guess that "
                   f"differs from transcend.{fn}, first {_hexes(wrong)}")
    return out, lanes


# ---- seq.py -------------------------------------------------------------------

def check_seq(f, xs=None, evaluator=None, loud=False, post=None):
    """[finding], lanes: seq. The fragment as a program on seq.py
    (routines.program and routines.run) equal to evaluate() lane for lane
    (`evaluator` stands for it, for the test that plants a fault in it) and,
    where unmarked, to transcend.py; the compiled shape (QUIET, the body,
    ENDQUIET, RAISE of the flag word: mathlib_harness.r24_program, `loud`
    moving the QUIET past the first FMA, which raises inexact outside it) with each
    lane's byte the IEEE flags of the operation and the mark in bit 7, FLAGS
    the OR of the bytes and STATUS[6] set exactly when a lane is marked
    (`post`, a function of seq.py's result, doctors it for the test); and the
    committed centres of the configuration among the lanes, marked in the
    byte. The lanes are plants.py's slice (pool_slice) by default."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    xs = list(pool_slice(fmt) if xs is None else xs)
    struct = structured_lanes(fn, fmt, rnd)
    have = set(xs)
    xs += [x for x in struct if x not in have]
    where = f"seq: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    outs, words = routines.run(f, xs)
    got = list(zip(outs, words))
    true = [ml.evaluate(f, x) for x in xs]
    ev = true if evaluator is None else [evaluator(f, x) for x in xs]
    bad = [x for x, a, b in zip(xs, got, ev) if a != b]
    if bad:
        out.append(f"{where}: seq.py and evaluate() differ on {len(bad)} "
                   f"lanes, first {hex(bad[0])}")
    wrong = [x for x, (bits, fw) in zip(xs, got)
             if not fw & MARK and (bits, fw) != golden(fmt, rnd, x, fn)]
    if wrong:
        out.append(f"{where}: {len(wrong)} unmarked lanes on seq.py differ "
                   f"from transcend.{fn}, first {hex(wrong[0])}")
    prog, bank = H.r24_program(f)
    if loud:
        prog = _loud(prog, bank, fmt)
    res = seq.run(prog, xs, [0] * len(xs), bank=bank)
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
                out.append(f"{where}: lane {hex(x)} deposited "
                           f"{res.deposits[i]:#x}, want {gb:#x}")
        if byte != want:
            out.append(f"{where}: lane {hex(x)} raised {byte:#x}, want "
                       f"{want:#x}")
    if res.flags != flags_or:
        out.append(f"{where}: FLAGS {res.flags:#x} is not the OR of the "
                   f"lanes' bytes {flags_or:#x}")
    status6 = bool(res.status & seq.STATUS_MARKED)
    if status6 != marked:
        out.append(f"{where}: STATUS[6] is {status6}, a marked lane was "
                   f"{'' if marked else 'not '}run")
    index = {x: i for i, x in enumerate(xs)}
    off = [x for x in struct
           if not res.lane_flags[index[x]] & seq.LANE_MARKED]
    if off:
        out.append(f"{where}: {len(off)} of the committed centres are not "
                   f"marked in the lane's byte, first {_hexes(off)}")
    return out[:8], xs


def _loud(prog, bank, fmt):
    """The compiled program with its QUIET moved to just after the body's
    first FMA: that instruction (the bucket's, y = G0p / b + the floor's
    offset, inexact on every lane) is outside the quiet region and raises its
    flag on the lane, the fault the byte must see. mathlib_harness's own
    `loud` leaves the first rounded instruction, which is here an exact SUB
    that raises nothing."""
    insns = list(prog.insns)
    q = next(i for i, w in enumerate(insns) if seq.decode(w)["op"] == seq.QUIET
             and seq.decode(w)["ctrl"])
    k = next(i for i in range(q + 1, len(insns))
             if not seq.decode(insns[i])["ctrl"]
             and seq.decode(insns[i])["op"] == sf.OP_FMA)
    insns = insns[:q] + insns[q + 1:k + 1] + [insns[q]] + insns[k + 1:]
    return seq.Program(fmt, insns, consts=(), max_deposits=1,
                       flags=seq.FLAG_BANK_EXT, n_consts=len(bank))


# ---- the bound ----------------------------------------------------------------

def v_names(b):
    """The probes holding V's words: V0, V1, V2 for a triple word (fp32,
    parcel M2F2), Vh and Vl for a double word."""
    return ("V0", "V1", "V2") if "V0" in b.probes else ("Vh", "Vl")


def bound_log2(b, x):
    """log2(|V - f(x)| / Bv) for one main-path lane of the build b: V the sum
    of its probes' words (V0, V1 and V2 of a triple word, Vh and Vl of a double
    word: a triple word has no Vl, and a sum of Vh and Vl alone would drop V2,
    2^-48 of V at fp32, 2^16 Bv), the true value from mpmath at 4p + 200 bits.
    None where V is exact; 999.0 where V is not finite."""
    fmt = b.fmt
    names = v_names(b)
    _res, _fl, pr = b.run(x, names + ("Bv",))
    try:
        V = sum(value(fmt, pr[n]) for n in names)
        Bv = abs(value(fmt, pr["Bv"]))
    except ValueError:
        return 999.0
    with mpmath.workprec(4 * fmt.prec + 200):
        err = abs(_mp(V) - true_value(b.meta["fn"], value(fmt, x)))
        if err == 0:
            return None
        return float(mpmath.log(err / _mp(Bv), 2))


def check_bound(b, xs, label="random"):
    """[finding], (worst log2(err/Bv), main-path lanes, lanes): bound. Every
    main-path lane of xs under 1 Bv, and every lane (main or not) equal to
    transcend.py in bits and flag word or marked. The worst is the largest
    found, a lower bound on the true worst."""
    fmt, fn = b.fmt, b.meta["fn"]
    worst, n, over, differ = -1e9, 0, [], []
    for x in xs:
        res, fw, _pr = b.run(x)
        if not fw & MARK and (res, fw) != golden(fmt, b.rnd, x, fn):
            differ.append(x)
        if not in_main(fmt, fn, x):
            continue
        r = bound_log2(b, x)
        n += 1
        if r is None:
            continue
        worst = max(worst, r)
        if r >= 0:
            over.append((r, x))
    where = f"bound: {fn} {fmt.name} {sf.RND_NAMES[b.rnd]} {label}"
    out = []
    if over:
        r, x = max(over)
        out.append(f"{where}: {len(over)} of {n} main-path lanes are past the "
                   f"bound, the worst {hex(x)} at 2^{r:+.2f} of Bv")
    if differ:
        out.append(f"{where}: {len(differ)} unmarked lanes differ from "
                   f"transcend.{fn}, first {hex(differ[0])}")
    return out, (worst, n, len(xs))


# ---- the specials ----------------------------------------------------------------

def special_rows(fmt):
    """[(label, kind, lanes)]: the rows of the study's section 4, both signs,
    in the routine's order of priority. kind "equal": the answer is
    transcend.py's in bits and flag word and the lane is not marked;
    "marked": past the stated range the lane is marked and its flag word is
    exactly inexact with the mark (the guess is not compared); "decided": the
    predecessor of 2^R, which the main path answers, equal to transcend.py's
    and not marked."""
    gs, gc = ml.trig_gates(fmt)
    S = fmt.sign_mask
    qn, sn = sf.qnan_bits(fmt), sf.snan_bits(fmt)
    rows = [
        ("NaN (quiet, both signs)", "equal", [qn, qn | S]),
        ("NaN (signalling, both signs)", "equal", [sn, sn | S]),
        ("+inf, -inf", "equal", [sf.inf_bits(fmt), sf.inf_bits(fmt, 1)]),
        ("+0, -0", "equal", [0, S]),
        ("subnormals: min, max, both signs", "equal",
         [sf.min_subnormal_bits(fmt), sf.max_subnormal_bits(fmt),
          sf.min_subnormal_bits(fmt) | S, sf.max_subnormal_bits(fmt) | S]),
        ("min normal, both signs", "equal",
         [sf.min_normal_bits(fmt), sf.min_normal_bits(fmt) | S]),
    ]
    for label, g in (("sin's gate", gs), ("cos's and tan's gate", gc)):
        b = ml._pow2(fmt, g)
        rows.append((f"{label} 2^{g}: the largest tiny and the smallest not, "
                     f"both signs", "equal", [b - 1, b, (b - 1) | S, b | S]))
    R = ml.TRIG_RANGE[fmt.name]
    if R is None:
        rows.append(("max normal, both signs", "equal",
                     [sf.max_normal_bits(fmt), sf.max_normal_bits(fmt) | S]))
    else:
        top = ml._pow2(fmt, R)
        rows.append((f"2^{R} and the largest finite, both signs", "marked",
                     [top, top | S, sf.max_normal_bits(fmt),
                      sf.max_normal_bits(fmt) | S]))
        rows.append((f"the predecessor of 2^{R}, both signs", "decided",
                     [top - 1, (top - 1) | S]))
    return rows


def check_specials(f, evaluator=None):
    """[finding], lanes: specials. Every row of special_rows() through the
    fragment: "equal" and "decided" rows equal to transcend.py in bits AND flag
    word and not marked, "marked" rows (past the range) marked with the flag
    word inexact | mark. `evaluator` stands for ml.evaluate, for the test that
    plants a fault in it."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    out, n = [], 0
    for label, kind, lanes in special_rows(fmt):
        bad = []
        for x in lanes:
            n += 1
            bits, fw = (evaluator or ml.evaluate)(f, x)
            if kind == "marked":
                if fw != sf.FLAG_INEXACT | MARK:
                    bad.append((x, "flag word", fw, sf.FLAG_INEXACT | MARK))
            elif (bits, fw) != golden(fmt, rnd, x, fn):
                bad.append((x, "bits and flag word", (bits, fw),
                            golden(fmt, rnd, x, fn)))
        if bad:
            x, what, got, want = bad[0]
            out.append(f"specials: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: row "
                       f"{label!r}: {len(bad)} of {len(lanes)} lanes differ, "
                       f"first {hex(x)}: {what} {got} against {want}")
    return out, n


# ---- the audit -----------------------------------------------------------------

def check_audit(b, xs):
    """[finding], tally: audit. reduction_audit() on the build's lanes: every
    instruction the build claims exact (Build.meta["exact"]) is the exact
    operation, on every lane of xs; and the build records claims at all."""
    claims = len(b.meta.get("exact", ()))
    where = f"audit: {b.meta['fn']} {b.fmt.name} {sf.RND_NAMES[b.rnd]}"
    out, tally, bad = [], {}, []
    if not claims:
        out.append(f"{where}: the build records no claim of exactness")
    for x in xs:
        fails = ml.reduction_audit(b, x, tally=tally)
        if fails:
            bad.append((x, fails))
    if bad:
        x, fails = bad[0]
        out.append(f"{where}: {len(bad)} of {len(xs)} lanes have a claim that "
                   f"fails, first {hex(x)}: instruction {fails[0][0]} "
                   f"({fails[0][1]}, {fails[0][2]})")
    return out, tally


# ---- the constants ----------------------------------------------------------------

def check_constants(**kw):
    """[finding], lines: constants. mathlib.check_trig_constants() in process,
    at FORMATS (the double word's three) unless `formats` is given: fp32's,
    the triple word's, are asked for by name (test_mathlib_trig_tw.py)."""
    kw.setdefault("formats", FORMATS)
    lines, findings = ml.check_trig_constants(**kw)
    return [f"constants: {s}" for s in findings], lines


# ---- the shape --------------------------------------------------------------

# (instructions, bank words, values live) of every fragment, in RND_MODES'
# order (rne, rtz, rdn, rup, rmm): MEASURED by parcel M2G2a. The instructions
# are the study's (costs.fp64, fp128, fp256.out.txt: sin 406, 382, 389, cos
# 402, 378, 385, tan 419, 397, 406 under every attribute); the live counts are
# the design's order's 26, 17 and 16, the order the fragments are emitted in
# (schedule_order: neither of the scheduler's own orders is lower).
SHAPE = {
    ("sin", "fp64"): [(406, 107, 26), (406, 108, 26), (406, 108, 26),
                      (406, 107, 26), (406, 107, 26)],
    ("cos", "fp64"): [(402, 104, 26), (402, 105, 26), (402, 105, 26),
                      (402, 104, 26), (402, 104, 26)],
    ("tan", "fp64"): [(419, 106, 26)] * 5,
    ("sin", "fp128"): [(382, 104, 17), (382, 105, 17), (382, 105, 17),
                       (382, 104, 17), (382, 104, 17)],
    ("cos", "fp128"): [(378, 101, 17), (378, 102, 17), (378, 102, 17),
                       (378, 101, 17), (378, 101, 17)],
    ("tan", "fp128"): [(397, 103, 17)] * 5,
    ("sin", "fp256"): [(389, 118, 16), (389, 119, 16), (389, 119, 16),
                       (389, 118, 16), (389, 118, 16)],
    ("cos", "fp256"): [(385, 115, 16), (385, 116, 16), (385, 116, 16),
                       (385, 115, 16), (385, 115, 16)],
    ("tan", "fp256"): [(406, 117, 16)] * 5,
    # fp32, the triple word (parcel M2F2): the model's 939, 936 and 993
    # (tw32_costs.out.txt) and its bank words, 97 under rne, rup and rmm and
    # 98 under rtz and rdn for sin, 94 and 95 for cos, 96 for tan; 23 values
    # live, in the design's order and scheduled, in all 15
    ("sin", "fp32"): [(939, 97, 23), (939, 98, 23), (939, 98, 23),
                      (939, 97, 23), (939, 97, 23)],
    ("cos", "fp32"): [(936, 94, 23), (936, 95, 23), (936, 95, 23),
                      (936, 94, 23), (936, 94, 23)],
    ("tan", "fp32"): [(993, 96, 23)] * 5,
}

# The instructions by phase, the study's (docs/studies/m2/costs.*.out.txt, the
# "by phase" line of each function under rne; the same under every attribute):
# the reduction's 206, 168 and 155 in red-*, then the rest. At fp128 and fp256
# the model's two "range" instructions are the compare and the SELECT; M2G1's
# `inrange` compare is the reduction's and is in the phase "classify", so the
# port has one more there and one less in "range" (RANGE_MOVE).
_RED = {"fp64": {"red-setup": 18, "red-window": 61, "red-products": 21,
                 "red-coarse": 18, "red-mid": 36, "red-lower": 33,
                 "red-scale": 14, "red-small": 5},
        "fp128": {"red-setup": 18, "red-window": 35, "red-products": 17,
                  "red-coarse": 18, "red-mid": 28, "red-lower": 33,
                  "red-scale": 14, "red-small": 5},
        "fp256": {"red-setup": 18, "red-window": 22, "red-products": 17,
                  "red-coarse": 18, "red-mid": 28, "red-lower": 33,
                  "red-scale": 14, "red-small": 5},
        # fp32's triple word: the model's 319 (tw32_costs.out.txt)
        "fp32": {"red-setup": 18, "red-window": 51, "red-products": 15,
                 "red-coarse": 18, "red-mid": 56, "red-products-low": 18,
                 "red-lower": 30, "red-triple": 66, "red-scale": 41,
                 "red-small": 6}}
_TAILS = {"fp64": (4, 5), "fp128": (10, 11), "fp256": (20, 21), "fp32": (2, 1)}
_QUOTIENT = {"fp64": 19, "fp128": 21, "fp256": 23, "fp32": 60}
_REST = {"sin": {"S-head": 70, "C-head": 69, "sincos": 7, "select": 9,
                 "final": 13, "classify": 6, "special": 13},
         "cos": {"S-head": 70, "C-head": 69, "sincos": 7, "select": 9,
                 "final": 13, "classify": 6, "special": 9},
         "tan": {"S-head": 70, "C-head": 69, "sincos": 7, "select": 8,
                 "final": 9, "classify": 6, "special": 12}}


# fp32's heads are the triple word's: S-head2 and C-head2 (the double-word
# steps, 26 each), S-head3 (191) and C-head3 (233), z is 5 and sin(r) cos(r)
# 74 (tw32_costs.out.txt, the "by phase" line of each function under rne)
_REST32 = {"sin": {"S-head2": 26, "S-head3": 191, "C-head2": 26,
                   "C-head3": 233, "sincos": 74, "select": 11, "final": 31,
                   "classify": 7, "special": 13},
           "cos": {"S-head2": 26, "S-head3": 191, "C-head2": 26,
                   "C-head3": 233, "sincos": 74, "select": 12, "final": 31,
                   "classify": 7, "special": 9},
           "tan": {"S-head2": 26, "S-head3": 191, "C-head2": 26,
                   "C-head3": 233, "sincos": 74, "select": 10, "final": 27,
                   "classify": 7, "special": 12}}


def model_phases(fn, fmt_name):
    """The study's instructions by phase for fn at the format."""
    if fmt_name == "fp32":
        out = dict(_RED[fmt_name], z=5, **_REST32[fn])
        out["S-tail"], out["C-tail"] = _TAILS[fmt_name]
        if fn == "tan":
            out["quotient"] = _QUOTIENT[fmt_name]
        return out
    out = dict(_RED[fmt_name], z=4, **_REST[fn])
    out["S-tail"], out["C-tail"] = _TAILS[fmt_name]
    if fn == "tan":
        out["quotient"] = _QUOTIENT[fmt_name]
    if fmt_name != "fp64":
        out["range"] = 2
    return out


def port_phases(fn, fmt_name):
    """model_phases() with the one move: where there is a range, the compare
    is in "classify" (M2G1's inrange) and the SELECT alone in "range"."""
    out = model_phases(fn, fmt_name)
    if "range" in out:
        out["range"] -= 1
        out["classify"] += 1
    return out


# The values the flag word takes (the study's section 4; MEASURED by its
# costs.py on all 60 fragments): the pools saw exactly these.
FLAG_WORDS = {"sin": frozenset({0x0, 0x1, 0x10, 0x18, 0x90}),
              "tan": frozenset({0x0, 0x1, 0x10, 0x18, 0x90}),
              "cos": frozenset({0x0, 0x1, 0x10, 0x90})}
# (MIN, MAX) instructions: the clamp's two of each in sin and cos only
MIN_MAX = {"sin": (2, 2), "cos": (2, 2), "tan": (0, 0)}
# bank words, all three functions under five attributes (the study's
# costs.*.out.txt last lines)
UNION_WORDS = {"fp64": 111, "fp128": 108, "fp256": 122, "fp32": 102}
# the instructions of sin, cos and tan of one argument in one compiled step,
# once each shared one is counted once (docs/studies/m2/share.py, the study's
# 2.1 table: 475, 455 and 464, at every attribute)
SHARED = {"fp64": 475, "fp128": 455, "fp256": 464, "fp32": 1088}


class Tables:
    """The pinned data the shape check reads, one attribute a table, so that a
    test can doctor one and show its leg fail alone."""

    def __init__(self, **kw):
        self.shape = SHAPE
        self.phases = port_phases
        self.flag_words = FLAG_WORDS
        self.min_max = MIN_MAX
        self.union = UNION_WORDS
        self.shared = SHARED
        self.caps = ml.TRIG_LIVE_CAP
        for k, v in kw.items():
            if not hasattr(self, k):
                raise ValueError(f"no table {k!r}")
            setattr(self, k, v)


def _signature(f, upto=None):
    """f's instructions as (opcode, attribute, operands) with a word as its
    bits and a value as its index: comparable across fragments."""
    out = []
    for op, r, srcs in f.body[:upto]:
        out.append((op, r, tuple(("w", f.words[s[1]]) if s[0] == "w" else s
                                 for s in srcs)))
    return out


def shared_count(frags):
    """The instructions that remain when the fragments of one argument share in
    a compiled step: cftc's inliner (python/cftc/inline.py, expand) keys each
    routine instruction by (opcode, attribute, resolved operands) across the
    instances, after routines.simplify (docs/studies/m2/share.py, ported)."""
    keyed = {}
    for f in frags:
        vals = {}
        for i, (op, r, srcs) in enumerate(f.body):
            ss = tuple(("x",) if s[0] == "in" else vals[s] if s[0] == "v"
                       else ("w", f.words[s[1]]) for s in srcs)
            same = routines.simplify(op, ss,
                                     lambda t: t[1] if t[0] == "w" else None,
                                     f.fmt.sign_mask)
            if same is not None:
                vals[("v", i)] = same
                continue
            key = (sf.OP_NAMES[op], r, ss)
            if key not in keyed:
                keyed[key] = ("n", len(keyed))
            vals[("v", i)] = keyed[key]
    return len(keyed)


def check_shape(fmt, builds, tables=None, fragments=None):
    """[finding]: shape. `builds`: {(fn, rnd): Build} for sin, cos and tan
    under all five attributes at `fmt`. Per fragment: (instructions, words,
    live) the pinned ones; the instructions by phase the model's, with the one
    move (port_phases); the flag word's values exactly the study's; MIN and MAX
    in sin and cos only; the scheduled fragment the design's reordered
    (mathlib_harness.check_reorder); its own invariants. Per function: its
    TRIG_LIVE_CAP entry the measured maximum under the five attributes, the
    fragment of that maximum holding to it and failing, by name, a cap one
    under. Per format: the three functions alike instruction for instruction
    before `select` under each attribute (so that cftc's sharing holds, 2.1),
    their sum in a step the model's, and the words of all fifteen the model's
    count. `tables` (Tables) holds the pinned data, one attribute a table;
    `fragments` {(fn, rnd): Fragment} stands for the builds' own scheduled
    fragments: both are for the tests that doctor one leg."""
    t = tables or Tables()
    name = fmt.name
    out = []
    frags = fragments or {k: b.fragment() for k, b in builds.items()}
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
        if by != t.phases(fn, name):
            diff = {k: (by.get(k, 0), t.phases(fn, name).get(k, 0))
                    for k in set(by) | set(t.phases(fn, name))
                    if by.get(k, 0) != t.phases(fn, name).get(k, 0)}
            out.append(f"{where}: instructions by phase differ from the "
                       f"model's (phase: got, model's): {diff}")
        fw = routines.flag_words(f)
        if fw != t.flag_words[fn]:
            out.append(f"{where}: the flag word takes "
                       f"{sorted(hex(w) for w in fw or ())}, the study's "
                       f"{sorted(hex(w) for w in t.flag_words[fn])}")
        counts = f.counts()
        if (counts.get("min", 0), counts.get("max", 0)) != t.min_max[fn]:
            out.append(f"{where}: {counts.get('min', 0)} MIN and "
                       f"{counts.get('max', 0)} MAX instructions, the "
                       f"clamp's {t.min_max[fn][0]} and {t.min_max[fn][1]} "
                       f"(sin and cos only)")
        out += [f"shape: {s}" for s in H.check_reorder(b, f)]
        out += [f"{where}: invariants: {s}"
                for s in ml.invariants(f, live_cap=t.caps[fn][name])]
    for fn in FUNCS:
        lives = {rnd: frags[(fn, rnd)].live_max() for rnd in RND_MODES}
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
            out.append(f"shape: {fn} {name}: a cap one under ({top - 1}) "
                       f"does not fail by name: {under}")
    words = set()
    for rnd in RND_MODES:
        designs = {fn: builds[(fn, rnd)].fragment(schedule=False)
                   for fn in FUNCS}
        phased = {fn: [builds[(fn, rnd)].phase_of[i]
                       for i in builds[(fn, rnd)].live_indices()]
                  for fn in FUNCS}
        firsts = {fn: phased[fn].index("select") for fn in FUNCS}
        if len(set(firsts.values())) != 1:
            out.append(f"shape: {name} {sf.RND_NAMES[rnd]}: `select` begins "
                       f"at instruction {firsts}, not the same for the three")
        else:
            k = firsts["sin"]
            sigs = {fn: _signature(designs[fn], k) for fn in FUNCS}
            if not sigs["sin"] == sigs["cos"] == sigs["tan"]:
                odd = [fn for fn in ("cos", "tan") if sigs[fn] != sigs["sin"]]
                first = next(i for i in range(k)
                             if len({sigs[fn][i] for fn in FUNCS}) > 1)
                out.append(f"shape: {name} {sf.RND_NAMES[rnd]}: sin, cos and "
                           f"tan are not alike before `select` (instruction "
                           f"{first} of {k} differs; {', '.join(odd)} not "
                           f"sin's)")
        try:
            n = shared_count([frags[(fn, rnd)] for fn in FUNCS])
        except KeyError:
            out.append(f"shape: {name} {sf.RND_NAMES[rnd]}: a fragment reads "
                       f"a value before it is defined, so cftc's keying "
                       f"cannot count what the three share")
        else:
            if n != t.shared[name]:
                out.append(f"shape: {name} {sf.RND_NAMES[rnd]}: sin, cos and "
                           f"tan of one argument are {n} instructions in a "
                           f"compiled step, the model's {t.shared[name]}")
        for fn in FUNCS:
            words |= set(frags[(fn, rnd)].words.values())
    if len(words) != t.union[name]:
        out.append(f"shape: {name}: {len(words)} bank words over the three "
                   f"functions and five attributes, the model's "
                   f"{t.union[name]}")
    return out


# ---- the mark-rate law (parcel M2G2b; the study's 3.4) -----------------------------
#
# The law, as the six's (mathlib_harness, the comment above RATE_ALPHA; parcel
# RC): with the bound inflated to 2^-(p + G') |V_h|, a lane is marked when its
# true value lies within the bound of a boundary of the attribute (a float under
# the directed three, a midpoint under rne and rmm), which with its place in the
# rounding cell uniform has probability 2 Bv / ulp = 2^-G' m_V, m_V in [1, 2)
# the significand of the true value. The count of marks is a sum of independent
# Bernoulli(2^-G' m_V) lanes: the SAMPLE'S OWN mean and variance, the cell judged
# by the exact two-sided tail of that count (H.RateSample.pmf and p_value), a
# run of cells as the independent statistics it holds (rtz, rdn and rup mark
# the same lanes, rne and rmm the same). The study's rate.py (3.4) drew the
# lanes of the "random" region (every bit random, the exponent uniform from the
# tiny gate to the range's top): sin and cos values crowd toward +-1, where
# m_V is near 2, so their rate is 2.5% against tan's 2.25% at G' = 6 (the
# study: sig(V) averages 1.59 and 1.44), not M1's n 2^(0.53 - G') for all.
# These cells are a family of their own, judged by their own count
# (rate_statistics of THEIR cells); they are never added to test_mathlib.py's
# 90 (RATE_STATISTICS there is 36 statistics and is pinned).

RATE_G = 6                              # G', the inflated bound's guard


def rate_arguments(fmt, fn, n, seed):
    """rate.py's sample: `n` arguments of the "random" region of sample() for
    `seed`, those the main path answers for fn (all of them at fp64, fp128 and
    fp256, whose gates are one exponent for sin, cos and tan)."""
    return [x for x in sample(fmt, "random", n, seed) if in_main(fmt, fn, x)]


def lane_cell(fmt, fn, x):
    """(E, m, u) of the true value |f(x)| = m 2^E, m in [1, 2), and u in [0, 1)
    its place in its p-bit rounding cell: mathlib_harness.lane_cell for sin, cos
    and tan. mpmath at p + 96 bits (more internally for a large argument), x
    exact, read from the `_mpf_` tuple."""
    p = fmt.prec
    u_ = sf.unpack(fmt, x)
    with mpmath.workprec(p + 96):
        xv = mpmath.ldexp(mpmath.mpf(u_.m), u_.e)
        if u_.sign:
            xv = -xv
        _sign, man, ex, bc = {"sin": mpmath.sin, "cos": mpmath.cos,
                              "tan": mpmath.tan}[fn](xv)._mpf_
    if not man:
        raise ValueError(f"{fn}({hex(x)}) is zero: not a main-path lane")
    man = int(man)
    m = man / (1 << (bc - 1))
    u = (man & ((1 << (bc - p)) - 1)) / (1 << (bc - p)) if bc > p else 0.0
    return ex + bc - 1, m, u


class TrigRateSample(H.RateSample):
    """H.RateSample over rate_arguments(): lane i is marked with probability
    p_i = 2^-G' m_i (m_i the significand of its true value), independently of
    the others; `mean`, `sigma`, `tails`, `p_value`, `rejection` and
    `geometric_marks` are the six's, on this sample."""

    def __init__(self, fmt, fn, n, seed, g_inflated=RATE_G):
        self.fmt, self.fn, self.n, self.seed = fmt, fn, n, seed
        self.g = g_inflated
        self.xs = rate_arguments(fmt, fn, n, seed)
        self.n = len(self.xs)
        self.cells = [lane_cell(fmt, fn, x) for x in self.xs]
        self.p = [m * 2.0 ** -g_inflated for _e, m, _u in self.cells]
        self.mean = math.fsum(self.p)
        self.var = math.fsum(q * (1.0 - q) for q in self.p)
        self.sigma = math.sqrt(self.var)
        self._pmf = None


@functools.lru_cache(maxsize=None)
def rate_sample(fmt, fn, n, seed, g_inflated=RATE_G):
    """The TrigRateSample of these arguments, cached: it holds the clean
    sample, which a planted fault does not touch, and the attributes of a cell
    share it."""
    return TrigRateSample(fmt, fn, n, seed, g_inflated)


def tally(fmt, rnd, xs, results, fn):
    """mathlib_harness.tally for sin, cos and tan: the lanes against
    transcend.py (golden), a marked lane's guess counted, an unmarked lane
    that differs in bits or flag word listed."""
    t = H.Tally()
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
    return t


# Faults of the TOOL, for the tests: check_rate(tool_plant=...).
RATE_TOOL_PLANTS = {
    "expectation_follows_build": "the law's expectation computed from the "
                                 "build under test (its own bound word), so "
                                 "that a faulted bound moves the centre with "
                                 "the count and the check cannot see it",
}


def check_rate(fmt, rnd, fn, n=720, seed=7, g_inflated=RATE_G, plant=None,
               statistics=1, alpha=H.RATE_ALPHA, sigmas=None,
               tool_plant=None, evaluator=None, guard=None):
    """[finding], stats: rate. The mark-rate law (the study's 3.4) held to the
    sample's own count: the build of fn at fmt under rnd with the bound
    inflated to 2^-(p + G') (bound_shift = G - G'), `plant` a fault of the
    builder (TRIG_PLANTS), n arguments of the random region (rate_arguments),
    each lane's probability 2^-G' m_V with m_V the significand of its true
    value, the cell flagged when the exact two-sided tail of its count under
    that law is under alpha / statistics (a run of cells judged together, as
    mathlib_harness.check_rate: H.rate_statistics of the run's cells), or with
    `sigmas` beyond that many sigma; and every unmarked lane right and every
    marked guess counted, all right as the study found them.

    The expectation is of the UNPLANTED bound: a planted bound or a silenced
    mark changes the count and not the centre. `tool_plant` is a fault of this
    tool (RATE_TOOL_PLANTS): the expectation taken from the build under test;
    `evaluator` stands for ml.evaluate, for the test that doctors a lane;
    `guard` the build's G (the decided one by default; fp32's triple word,
    parcel M2F2, is built at GUARD's 40 alone)."""
    if tool_plant is not None and tool_plant not in RATE_TOOL_PLANTS:
        raise ValueError(f"unknown tool plant {tool_plant!r}: "
                         f"{', '.join(RATE_TOOL_PLANTS)}")
    G = ml.GUARD[fmt.name] if guard is None else guard
    b = ml.build(fn, fmt, rnd, guard=guard, bound_shift=G - g_inflated,
                 plant=plant)
    f = b.fragment()
    smp = rate_sample(fmt, fn, n, seed, g_inflated)
    if tool_plant == "expectation_follows_build":
        # the build's own bound word, 2^-(p + G'') with G'' = G' (clean) or
        # 40 more (bound_loose): the law of what the build is, not of what it
        # was meant to be
        brel = ml._dec(fmt, b.words[b.roles["BREL"][1]])
        g_built = round(-math.log2(brel)) - fmt.prec
        smp = rate_sample(fmt, fn, n, seed, g_built)
    ev = evaluator or ml.evaluate
    t = tally(fmt, rnd, smp.xs, [ev(f, x) for x in smp.xs], fn)
    c, mean, sd = len(t.marked), smp.mean, smp.sigma
    lo, hi = smp.tails(c)
    p = min(1.0, 2.0 * min(lo, hi))
    level = H.rate_level(statistics, alpha)
    z = (c - mean) / sd if sd > 0 else 0.0
    st = {"n": smp.n, "marked": c, "expected": mean, "sigma": sd, "z": z,
          "p": p, "level": level, "statistics": statistics,
          "class": H.rate_class(rnd), "wrong": len(t.wrong),
          "guess_wrong": len(t.guess_wrong)}
    where = f"rate: {fn} {fmt.name} {sf.RND_NAMES[rnd]} (G' = {g_inflated})"
    out = []
    if sigmas is not None:
        if abs(z) > sigmas:
            out.append(f"{where}: {c} of {smp.n} lanes marked, {mean:.1f} "
                       f"expected (sigma {sd:.1f}): {z:+.1f} sigma")
    elif p < level:
        out.append(f"{where}: {c} of {smp.n} lanes marked, {mean:.1f} "
                   f"expected (sigma {sd:.1f}): {z:+.1f} sigma, an exact "
                   f"two-sided tail of {p:.2g}, under the {level:.2g} of this "
                   f"run (alpha {alpha:g} over {statistics} statistics)")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} unmarked lanes are wrong, first "
                   f"{hex(t.wrong[0][0])}")
    if t.guess_wrong:
        out.append(f"{where}: {len(t.guess_wrong)} marked guesses are wrong, "
                   f"first {hex(t.guess_wrong[0][0])}")
    return out, st


# ---- the structured families (parcel M2G2b; the study's 3.5) ----------------------
#
# The theory is mathlib_trig_family's; these are the checks that hold a
# fragment, and the committed list, to it.

# The study's counts (3.5, MEASURED by census.py at the decided G, every lane
# against transcend.py: 0 wrong, every guess right): the lanes of the tiny
# family (TF.census: 144, 384 and 880 arguments) a fragment marks, as
# (under rne and rmm, under each of the directed three).
TINY_COUNTS = {
    "fp64": {"sin": (0, 2), "cos": (0, 14), "tan": (2, 0)},
    "fp128": {"sin": (0, 84), "cos": (0, 244), "tan": (6, 78)},
    "fp256": {"sin": (0, 270), "cos": (0, 740), "tan": (6, 264)},
    # fp32 at G = 40 (parcel M2F2): ZERO is a claim. The tiny family is 48
    # arguments there (e = 12 and 13), the theory demands none marked (no
    # centre at G = 40), and the model marked none of them (parcel M2X: 0 in
    # 720 lanes for E0 = 12, tw32_pools-census.out.txt)
    "fp32": {"sin": (0, 0), "cos": (0, 0), "tan": (0, 0)},
}
# and of the minimisers' neighbours (TF.minnbr_arguments: binades 0 to 80, 40 to
# 90 and 100 to 210, j = -4 .. 4: 729, 459 and 999 arguments): none under rne and
# rmm, none for tan, none at fp64; the directed three mark sin 48 and cos 36 at
# fp128, sin 156 and cos 254 at fp256
MINNBR_COUNTS = {
    "fp64": {"sin": (0, 0), "cos": (0, 0), "tan": (0, 0)},
    "fp128": {"sin": (0, 48), "cos": (0, 36), "tan": (0, 0)},
    "fp256": {"sin": (0, 156), "cos": (0, 254), "tan": (0, 0)},
}
CENSUS_SIZES = {("tiny", "fp64"): 144, ("tiny", "fp128"): 384,
                ("tiny", "fp256"): 880, ("minnbr", "fp64"): 729,
                ("minnbr", "fp128"): 459, ("minnbr", "fp256"): 999,
                # fp32 at G = 40: 48 (the theory takes p and G); no
                # minimisers' neighbours (MINNBR_RANGE has no fp32)
                ("tiny", "fp32"): 48}
# The study's measured windows (window.py, 3.5; fp64): (function, attribute,
# centre c 2^-e, J) -> (marked, first j, last j) of the neighbours x0 + j,
# j = -J .. J, the encoding stepped by j: the finer ulp below a power of two
WINDOW_SCANS = {
    ("sin", "rtz", 3, 25, 40): (21, -9, 11),
    ("tan", "rne", 3, 26, 40): (43, -23, 19),
    ("cos", "rtz", 1, 26, 400): (384, -255, 128),
}


def _centre_name(cen):
    if cen[0] == "m":
        return f"minimiser of 2^{cen[1]}{cen[2]:+d} ulp"
    return f"{cen[0]} 2^-{cen[1]}"


def family_lanes(fmt, rnd, fn, centres, G=None):
    """[(x, label, what the theory demands)] for the centres, their negatives
    and their neighbours (TF.neighbours: the first four inside the window, the
    rest outside), each lane once."""
    seen, out = set(), []
    for cen in centres:
        x0 = TF.argument(fmt, cen)
        for x, lab in ([(x0, "centre"), (x0 | fmt.sign_mask, "centre (-)")]
                       + TF.neighbours(fmt, fn, cen, G)):
            if x not in seen:
                seen.add(x)
                out.append((x, f"{_centre_name(cen)} {lab}",
                            TF.classify(fmt, rnd, x, G, fn)))
    return out


def check_family(f, centres, G=None, extra=(), deep=False, evaluator=None):
    """[finding], stats: family. On the centres (TF.expand of the committed
    entries, or a sample of them), their neighbours, `extra` (arguments, such as
    the census's, that are not centres) and, with `deep`, TF.deep_arguments (the
    family beyond the committed sample): the routine marks every lane the theory
    says is inside a window (d under 0.7 of the bound), marks none that is
    outside (d over 1.3) or gated, is right on every lane it does not mark, and
    every marked guess is right. MB1's rule (VALIDATION.md). `evaluator` stands
    for ml.evaluate, for the test that doctors a lane."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    lanes = family_lanes(fmt, rnd, fn, centres, G)
    seen = {x for x, _l, _c in lanes}
    more = [(x, f"argument {hex(x)}") for x in extra]
    if deep:
        more += [(x, f"deep {lab}") for x, lab in TF.deep_arguments(fmt, fn, G)]
    for x, lab in more:
        if x not in seen:
            seen.add(x)
            lanes.append((x, lab, TF.classify(fmt, rnd, x, G, fn)))
    ev = evaluator or ml.evaluate
    res = [ev(f, x) for x, _l, _c in lanes]
    out = []
    st = {"lanes": len(lanes), "guess_wrong": 0, "wrong": 0}
    for w in ("mark", "clear", "either", "gated"):
        st[w] = st["marked_" + w] = 0
    tag = f"family: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    for (x, lab, want), (bits, fw) in zip(lanes, res):
        marked = bool(fw & MARK)
        gb, gf = golden(fmt, rnd, x, fn)
        st[want] += 1
        if marked:
            st["marked_" + want] += 1
            if (bits, fw & 0x1F) != (gb, gf):
                st["guess_wrong"] += 1
        elif (bits, fw) != (gb, gf):
            st["wrong"] += 1
            out.append(f"{tag}: {lab} ({hex(x)}) is unmarked and wrong: got "
                       f"({bits:#x}, {fw:#x}), want ({gb:#x}, {gf:#x})")
        if want == "mark" and not marked:
            out.append(f"{tag}: {lab} ({hex(x)}) is inside a window, d = "
                       f"{TF.distance(fmt, rnd, x, G, fn):.3f}, and not marked")
        if want in ("clear", "gated") and marked:
            where = "gated" if want == "gated" else "outside every window"
            out.append(f"{tag}: {lab} ({hex(x)}) is {where} and marked")
    if st["guess_wrong"]:
        out.append(f"{tag}: {st['guess_wrong']} marked guesses are wrong")
    return out[:8], st


def scan_window(f, x0, J, evaluator=None):
    """window.py (the study's): x0 and its neighbours x0 + j, j = -J .. J (the
    encoding stepped by j, so below a power of two the steps are the finer ulp):
    ({j: marked}, wrong unmarked, wrong guesses), every lane against
    transcend.py."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    marked, wrong, guess_wrong = [], 0, 0
    for j in range(-J, J + 1):
        x = x0 + j
        bits, fw = (evaluator or ml.evaluate)(f, x)
        gb, gf = golden(fmt, rnd, x, fn)
        if fw & MARK:
            marked.append(j)
            guess_wrong += (bits, fw & 0x1F) != (gb, gf)
        elif (bits, fw) != (gb, gf):
            wrong += 1
    return marked, wrong, guess_wrong


def check_scan(f, c, e, J, expect=None, G=None, evaluator=None):
    """[finding], (marked, first, last): windows (the scan). The window of the centre
    c 2^-e scanned lane by lane (scan_window), j = -J .. J: every unmarked lane
    right and every marked guess right; the marked lanes ONE run around the
    centre (a window is an interval); the run no wider than the half-width the
    study's 3.5 computes allows, between (1 - d0) W and (1 + d0) W on a side
    with the centre's d0 under 0.7, so at most 1.7 W + 1 either side; the run
    reaching at least 0.3 W - 1 either side where the scan does (the theory's
    window); and with `expect` (the study's measured window) the run (marked,
    first j, last j) equal to it. `evaluator` as in check_family."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    x0 = TF.argument(fmt, (c, e))
    js, wrong, gw = scan_window(f, x0, J, evaluator)
    W = float(TF.half_width(fmt, fn, x0, G))
    where = f"windows: {fn} {fmt.name} {sf.RND_NAMES[rnd]} {c} 2^-{e} scan"
    out = []
    if wrong:
        out.append(f"{where}: {wrong} unmarked lanes are wrong")
    if gw:
        out.append(f"{where}: {gw} marked guesses are wrong")
    first, last = (min(js), max(js)) if js else (0, 0)
    if js and len(js) != last - first + 1:
        out.append(f"{where}: the marked lanes are not one run: {len(js)} "
                   f"marked between j = {first} and {last}")
    if js and (-first > 2 * W + 2 or last > 2 * W + 2):
        out.append(f"{where}: the marked run j = {first} .. {last} is wider "
                   f"than the computed half-width W = {W:.1f} allows (1.7 W)")
    if J > 2 * W + 2 and js and not (-first >= 0.3 * W - 1
                                     and last >= 0.3 * W - 1):
        out.append(f"{where}: the marked run j = {first} .. {last} stops "
                   f"short of 0.3 W = {0.3 * W:.1f} on one side")
    if J > 2 * W + 2 and not js:
        out.append(f"{where}: no lane of the window is marked, W = {W:.1f}")
    if expect is not None and (len(js), first, last) != tuple(expect):
        out.append(f"{where}: the marked run is {len(js)} lanes, j = {first} "
                   f".. {last}; the study's {expect[0]}, j = {expect[1]} .. "
                   f"{expect[2]}")
    return out, (len(js), first, last)


def check_windows(f, centres, G=None, evaluator=None, edges=None):
    """[finding], n: windows. For each tiny centre (the minimisers' neighbours
    are isolated lanes: no window) the window's EDGES on each side, exact by the
    theory (TF.window_edges: the largest j whose lane the theory demands marked,
    d under 0.7, and the smallest it calls clear, d over 1.3, by search and
    bisection, whatever the width: 2^189 arguments at fp256): the lanes at the
    inner edge and half way to it must be marked and the lanes at the outer
    edge and twice as far unmarked, every unmarked lane right and every marked
    guess right; and the half-width the study's 3.5 computes (TF.half_width)
    must agree with the exact edges: the outer edge between 0.6 W and 2 W, the
    inner at most 1.4 W (a centre with d0 under 0.7 puts them at (1 -+ d0) W
    and (0.7 +- d0) W; a power of two has the finer ulp on one side, twice as
    many steps). `edges` the window_edges to use, `evaluator` stands for
    ml.evaluate, for the test that doctors a lane."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    ev = evaluator or ml.evaluate
    out, n = [], 0
    for cen in centres:
        if cen[0] == "m":
            continue
        x0 = TF.argument(fmt, cen)
        W = float(TF.half_width(fmt, fn, x0, G))
        fine = 2.0 if x0 & fmt.man_mask == 0 else 1.0
        es = TF.window_edges(fmt, rnd, fn, x0, G) if edges is None else edges
        for side, (j_in, j_out) in sorted(es.items()):
            where = (f"windows: {fn} {fmt.name} {sf.RND_NAMES[rnd]} "
                     f"{cen[0]} 2^-{cen[1]} {'above' if side > 0 else 'below'}")
            if j_out is None:
                out.append(f"{where}: no lane of a binade's worth of steps is "
                           f"clear: the window has no outer edge")
                continue
            if not (0.6 * W / fine - 2 <= j_out <= 2.0 * W * fine + 2) or \
                    j_in > 1.4 * W * fine + 2:
                out.append(f"{where}: the computed half-width W = {W:.4g} "
                           f"does not agree with the exact window, inner edge "
                           f"j = {j_in}, outer edge j = {j_out}")
            for j, must, label in ((j_in, True, "inner edge"),
                                   (j_in // 2, True, "half way to it"),
                                   (j_out, False, "outer edge"),
                                   (min(2 * j_out, 1 << fmt.man_w), False,
                                    "twice as far")):
                x = x0 + side * j
                bits, fw = ev(f, x)
                gb, gf = golden(fmt, rnd, x, fn)
                n += 1
                marked = bool(fw & MARK)
                if must and not marked:
                    out.append(f"{where}: the lane at the {label} (j = {j}, "
                               f"d = {TF.distance(fmt, rnd, x, G, fn):.3f}) is "
                               f"inside the window and not marked")
                if not must and marked:
                    out.append(f"{where}: the lane at the {label} (j = {j}, "
                               f"d = {TF.distance(fmt, rnd, x, G, fn):.3f}) is "
                               f"outside the window and marked")
                if marked and (bits, fw & 0x1F) != (gb, gf):
                    out.append(f"{where}: the marked guess at the {label} "
                               f"(j = {j}) is wrong")
                if not marked and (bits, fw) != (gb, gf):
                    out.append(f"{where}: the unmarked lane at the {label} "
                               f"(j = {j}) is wrong")
    return out[:8], n


def census_arguments(fmt, kind):
    """The study's census as arguments: "tiny" (TF.census) or "minnbr"
    (TF.minnbr_arguments)."""
    return TF.census(fmt) if kind == "tiny" else TF.minnbr_arguments(fmt)


def check_census_counts(f, kind, want=None, xs=None, evaluator=None):
    """[finding], Tally: census_counts. The study's census of the family
    `kind` ("tiny": c 2^-e, c <= 16; "minnbr": the minimisers' neighbours)
    through the fragment marks the counted lanes at the decided G (`want` =
    (under rne and rmm, under the directed three); TINY_COUNTS and
    MINNBR_COUNTS), every lane the theory demands marked is among them, none
    the theory calls clear, and no unmarked lane is wrong. `evaluator` as in
    check_family."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    xs = census_arguments(fmt, kind) if xs is None else xs
    if want is None:
        want = (TINY_COUNTS if kind == "tiny" else MINNBR_COUNTS)[fmt.name][fn]
    expect = want[0] if rnd in NEAREST_ATTRS else want[1]
    ev = evaluator or ml.evaluate
    t = tally(fmt, rnd, xs, [ev(f, x) for x in xs], fn)
    where = f"census_counts: {kind} {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if len(t.marked) != expect:
        out.append(f"{where}: {len(t.marked)} of the census's {t.n} arguments "
                   f"are marked, the study's count is {expect}")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} census lanes are wrong unmarked, "
                   f"first {hex(t.wrong[0][0])}")
    if t.guess_wrong:
        out.append(f"{where}: {len(t.guess_wrong)} marked guesses are wrong")
    marked = set(t.marked)
    must = [x for x in xs if TF.classify(fmt, rnd, x, None, fn) == "mark"]
    missing = [x for x in must if x not in marked]
    if missing:
        out.append(f"{where}: {len(missing)} lanes the theory demands marked "
                   f"(d under 0.7) are not, first {_hexes(missing)}")
    clear = [x for x in marked
             if TF.classify(fmt, rnd, x, None, fn) in ("clear", "gated")]
    if clear:
        out.append(f"{where}: {len(clear)} marked lanes the theory calls "
                   f"clear (d over 1.3), first {_hexes(clear)}")
    return out, t


NEAREST_ATTRS = (RNE, RMM)


def check_family_list(committed, generated=None):
    """[finding]: family_list. The committed entries (mathlib_trig_family.
    TRIG_FAMILY, or a copy a test has tampered with) are exactly what the
    theory generates, for every function, format and attribute."""
    generated = TF.generate() if generated is None else generated
    out = []
    for fn in sorted(set(committed) | set(generated)):
        cfn, gfn = committed.get(fn, {}), generated.get(fn, {})
        for fmt_name in sorted(set(cfn) | set(gfn)):
            for rnd_name in sorted(set(cfn.get(fmt_name, {}))
                                   | set(gfn.get(fmt_name, {}))):
                have = cfn.get(fmt_name, {}).get(rnd_name)
                want = gfn.get(fmt_name, {}).get(rnd_name)
                if have != want:
                    hc = set(TF.expand(have or ()))
                    wc = set(TF.expand(want or ()))
                    miss = sorted(wc - hc, key=str)
                    extra = sorted(hc - wc, key=str)
                    out.append(f"family_list: the committed centres of {fn} "
                               f"{fmt_name} {rnd_name} are not the theory's: "
                               f"missing {miss[:3]}, extra {extra[:3]}")
    return out


def check_pool_marks(marks=None, committed=None, generated=None):
    """[finding], explained: pool_marks. Every structured mark of the radian
    pools (TRIG_POOL_MARKS, parcel M2G2a's committed list of the lanes the
    pools mark that are not past the range) is a centre of the generated
    family of its function, format and attribute, or inside a centre's window
    (within the computed half-width W of a listed centre, in the encoding), or a
    lane the theory demands marked (d under 0.7). A mark the theory does not
    explain is a finding. `committed` the entries to look in (the generated
    ones by default: the list under test is family_list's)."""
    marks = TRIG_POOL_MARKS if marks is None else marks
    fam = TF.generate() if committed is None and generated is None else \
        (committed if generated is None else generated)
    out, explained = [], 0
    for fn, fmt_name, rnd_name, lane, _reason in marks:
        fmt, rnd = BY_NAME[fmt_name], RND_BY_NAME[rnd_name]
        ax = lane & ~fmt.sign_mask
        cen = [c for c in TF.expand(fam[fn][fmt_name][rnd_name])
               if c[0] != "m"]
        args = {TF.argument(fmt, c): c for c in cen}
        why = None
        if ax in args:
            why = "centre"
        else:
            for x0, c in args.items():
                W = float(TF.half_width(fmt, fn, x0))
                if abs(ax - x0) <= W:
                    why = f"inside the window of {c[0]} 2^-{c[1]}"
                    break
        if why is None and TF.classify(fmt, rnd, ax, None, fn) == "mark":
            why = "the theory demands the mark"
        if why is None:
            out.append(f"pool_marks: {fn} {fmt_name} {rnd_name} {hex(lane)} "
                       f"is marked in the pools and is not a centre, or inside "
                       f"a window, of the generated family (d = "
                       f"{TF.distance(fmt, rnd, ax, None, fn):.3g})")
        else:
            explained += 1
    return out, explained
