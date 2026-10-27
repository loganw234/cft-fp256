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
"""

import collections
import functools
import random
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

FORMATS = (FP64, FP128, FP256)
FUNCS = ml.TRIG_NAMES                   # sin, cos, tan
RND_MODES = sf.RND_MODES                # rne, rtz, rdn, rup, rmm
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
MARK = ml.MARK
BY_NAME = {f.name: f for f in FORMATS}
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


def sample(fmt, mode, n, seed):
    """n arguments of a region of the study's 3.2 (docs/studies/m2/
    m2measure.py's sample, ported): random (every bit of x random, its
    exponent uniform from the tiny gate to the range's top), edge (x within 3
    ulps of (k + 1/2) pi/2, k odd and random in the range's bits, so |r| is
    near pi/4), near (within 3 ulps of k pi/2, k odd: r small, the
    cancellation deep, where cos is small and tan large), zero (the same at
    even k, where sin and tan are small) and small (|x| from the tiny gate to
    4). Both signs. A function of (format, mode, seed)."""
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
    either side."""
    inside = {x for x in deepest(fmt) if not past_range(fmt, x)}
    if fmt.name != "fp64":
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

def bound_log2(b, x):
    """log2(|V - f(x)| / Bv) for one main-path lane of the build b: V from
    its probes Vh and Vl, the true value from mpmath at 4p + 200 bits. None
    where V is exact; 999.0 where V is not finite."""
    fmt = b.fmt
    _res, _fl, pr = b.run(x, ("Vh", "Vl", "Bv"))
    try:
        V = value(fmt, pr["Vh"]) + value(fmt, pr["Vl"])
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
                  "red-scale": 14, "red-small": 5}}
_TAILS = {"fp64": (4, 5), "fp128": (10, 11), "fp256": (20, 21)}
_QUOTIENT = {"fp64": 19, "fp128": 21, "fp256": 23}
_REST = {"sin": {"S-head": 70, "C-head": 69, "sincos": 7, "select": 9,
                 "final": 13, "classify": 6, "special": 13},
         "cos": {"S-head": 70, "C-head": 69, "sincos": 7, "select": 9,
                 "final": 13, "classify": 6, "special": 9},
         "tan": {"S-head": 70, "C-head": 69, "sincos": 7, "select": 8,
                 "final": 9, "classify": 6, "special": 12}}


def model_phases(fn, fmt_name):
    """The study's instructions by phase for fn at the format."""
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
UNION_WORDS = {"fp64": 111, "fp128": 108, "fp256": 122}
# the instructions of sin, cos and tan of one argument in one compiled step,
# once each shared one is counted once (docs/studies/m2/share.py, the study's
# 2.1 table: 475, 455 and 464, at every attribute)
SHARED = {"fp64": 475, "fp128": 455, "fp256": 464}


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
