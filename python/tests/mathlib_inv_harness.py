# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The lanes, the measurements and the checks parcel M4G1 holds atan to
(cft_golden/mathlib.py; docs/studies/M4-invtrig.md, section 8), gathered in one
place so that python/tests/test_mathlib_inv.py (quick, for the golden stage)
and python/tests/mathlib_runs.py (the larger runs, for the lead's box:
inv-pools and inv-bound) run the same lanes and the same checks. Parcels M4G2
(asin, acos) and M4G3 (atan2) add their functions at the anchors below: every
table here is a dict BY FUNCTION that they assign into, and every check takes
the table it reads as an argument.

A CHECK takes a fragment or its instrumented build and returns FINDINGS: a
list of strings, each beginning with the check's name and a colon, empty when
it holds (mathlib_harness's convention); one that measures also returns what
it measured. A planted fault is "caught by name" when the check it is meant for
returns a finding that begins with that name. mathlib_harness.py and
mathlib_trig_harness.py are imported, never edited.

  pools        the unary pool (the stage's trig_pool, vectors.trig_unary_pool
               and test_transcend's brute pool) through one fragment: every
               unmarked lane equal to transcend.py in bits AND flag word; every
               marked lane's guess counted; every mark on the committed list
               (INV_POOL_MARKS, empty for atan) and no other
  seq          the fragment as a stand-alone program on seq.py equal to
               evaluate() lane by lane and to transcend.py where unmarked; the
               compiled shape (mathlib_harness.r24_program): each lane's byte
               is the IEEE flags with the mark in bit 7, FLAGS the OR of the
               bytes, STATUS[6] set exactly when a lane is marked; the
               configuration's committed structured lanes marked in the byte
  bound        |V - f| / Bv under 1, mpmath at 4p + 200 bits, over the edge,
               big, small and random regions (48 points a region), each lane
               also against transcend.py. The largest is a sampled lower bound
  structured   the committed lanes that must mark, each marked, its guess equal
               to transcend.py's (and the listed exceptions' not)
  specials     the study's section 4 rows, both signs, every attribute
  shape        instructions, words and live pinned; instructions by phase the
               model's; the flag word's values the study's; no MIN but the
               index's, no MAX; the scheduled fragment the design's reordered;
               INV_LIVE_CAP the measured maximum, a cap one under failing by
               name
  audit        the index's exactness, lane by lane (the study's section 8,
               item 2), through build_inv_core on general (n, d): the only
               check that can see sterbenz_bias
  core         build_inv_core(double=True) against mpmath on placed double
               words, low words of both signs; the contract of Kk on lanes
  constants    mathlib.check_inv_constants() in process, and as
               `python -m cft_golden.mathlib --check --only inv`
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

FORMATS = ml.INV_FORMATS                 # fp64, fp128, fp256
BY_NAME = {f.name: f for f in FORMATS}
FUNCS = tuple(ml._INV_BUILDERS)          # atan, and what M4G2 and M4G3 build
RND_MODES = sf.RND_MODES                 # rne, rtz, rdn, rup, rmm
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
MARK = ml.MARK
RND_BY_NAME = {v: k for k, v in sf.RND_NAMES.items()}
CHECKS = ("pools", "seq", "bound", "structured", "specials", "shape", "audit",
          "core", "constants")


# ---- the definition, memoised -----------------------------------------------

@functools.lru_cache(maxsize=None)
def golden(fmt, rnd, x, fn):
    """transcend.py's function: the definition, (bits, flag word). `x` is an
    encoding, or for atan2 a tuple (y, x). Cached, since a plant re-runs the
    lanes of the clean fragment."""
    if isinstance(x, tuple):
        return transcend.compute(fmt, fn, x[0], x[1], rnd)
    return transcend.compute(fmt, fn, x, 0, rnd)


def value(fmt, bits):
    return ml._dec(fmt, bits)


def _mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


# the true values, by function: M4G2 and M4G3 assign theirs (a function of the
# format and the lane, at the caller's working precision)
TRUE_FNS = {"atan": lambda fmt, x: mpmath.atan(_mp(value(fmt, x)))}


def true_value(fn, fmt, x):
    return TRUE_FNS[fn](fmt, x)


# ---- the pools --------------------------------------------------------------

def _unary_pool(fmt):
    """The unary pool, deduplicated and sorted: the stage's (host/tests/
    transcend_check.py's trig_pool at its default trials, 64 random encodings
    at fp64 and 16 above, and seed 5), the vector sets' (vectors.
    trig_unary_pool as transcend_cases calls it: 24 extra, seed 12) and
    test_transcend's brute pool."""
    from test_transcend import _brute_pool
    t = 64 if fmt.width <= 64 else 16
    a = H._transcend_check().trig_pool(fmt, t, 5)
    b = vectors.trig_unary_pool(fmt, 24, 12)
    return tuple(sorted(set(a) | set(b) | set(_brute_pool(fmt))))


# the pool of each function, by function and format (M4G2 assigns asin's and
# acos's, M4G3 atan2's pairs)
POOL_FNS = {"atan": _unary_pool}


@functools.lru_cache(maxsize=None)
def pool(fn, fmt):
    return POOL_FNS[fn](fmt)


def _hexes(xs, k=3):
    return ", ".join(hex(x) if isinstance(x, int) else
                     "(" + ", ".join(hex(v) for v in x) + ")"
                     for x in list(xs)[:k])


# The marks of the pools that are not a fault: every (function, format,
# attribute, argument, reason) of the whole pools through every fragment that
# is marked. EMPTY for atan (MEASURED by the parcel: the pools through all 15
# configurations mark no lane); a lane marked off the list fails the pools, a
# listed lane not marked fails them. M4G2 and M4G3 append their rows at their
# anchors (the tuple is rebuilt by assigning a longer one).
INV_POOL_MARKS = ()


@functools.lru_cache(maxsize=None)
def _marks_of(marks, fn, fmt_name, rnd_name):
    return {lane: reason for f_, n_, r_, lane, reason in marks
            if (f_, n_, r_) == (fn, fmt_name, rnd_name)}


def pool_marks(fn, fmt_name, rnd_name, marks=None):
    return _marks_of(INV_POOL_MARKS if marks is None else tuple(marks), fn,
                     fmt_name, rnd_name)


class Tally:
    """The lanes of one run: n; the marked lanes and how many guesses were
    right; the unmarked lanes that were wrong; the marks off the list; the
    listed lanes not marked; and the flag words with stray bits."""

    def __init__(self):
        self.n = 0
        self.marked = []
        self.guess_wrong = []
        self.wrong = []
        self.off = []
        self.missing = []
        self.stray = []

    @property
    def marked_right(self):
        return len(self.marked) - len(self.guess_wrong)


def check_pools(f, xs=None, results=None, marks=None):
    """[finding], Tally: pools. `xs` the lanes (the pool of the function by
    default), `results` their (bits, flag word) if the caller has them,
    `marks` the committed list {lane: reason} (INV_POOL_MARKS' part for this
    fragment by default)."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    xs = pool(fn, fmt) if xs is None else xs
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
        if fw & MARK:
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
                   f"transcend.{fn}, first {_hexes([x])}: got ({got[0]:#x}, "
                   f"{got[1]:#x}), want ({want[0]:#x}, {want[1]:#x})")
    if t.stray:
        out.append(f"{where}: {len(t.stray)} flag words carry bits other "
                   f"than [4:0] and the mark, first {_hexes([t.stray[0][0]])}")
    if t.off:
        out.append(f"{where}: {len(t.off)} lanes are marked off the committed "
                   f"list (INV_POOL_MARKS), first {_hexes(t.off)}")
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


@functools.lru_cache(maxsize=None)
def core_of(fmt, plant=None, double=False):
    return ml.build_inv_core(fmt, plant=plant, double=double)


# ---- the placed points: the study's regions (m4measure.py's) -----------------

REGIONS = ("edge", "big", "small", "random")


def _rand_sig(rng, fmt, E, sign):
    p = fmt.prec
    m = rng.getrandbits(p - 1) | (1 << (p - 1))
    return sf.round_pack(fmt, sign, m, E - p + 1, RNE)[0]


def _sample_atan(fmt, mode, n, seed):
    """n arguments of atan placed where the bound binds (m4measure.sample):
    random, every bit random with the exponent uniform from the tiny gate to
    emax; edge, n/d at the table's cells' edges (t = (k +- 1/2)/(N 63/64)
    (1 +- eps), each k), where |s| is largest, and x = t or 1/t; big, |x| from
    2^(p/2) to emax (C = pi/2, s tiny); small, |x| from the gate to 1/16 (k =
    0)."""
    rng = random.Random(seed * 1000003 + fmt.width * 7 + len("atan"))
    p = fmt.prec
    ga = ml.trig_gates(fmt)[1]
    edges = [e for lo_hi in ml.inv_cells(ml.INV_N) for e in lo_hi
             if 0 < e <= 1]
    out = []
    for _ in range(n):
        s = rng.getrandbits(1)
        if mode == "random":
            out.append(_rand_sig(rng, fmt, rng.randint(ga, fmt.emax), s))
        elif mode == "edge":
            t = rng.choice(edges) * (1 + Fraction(rng.randint(-64, 64),
                                                  2 ** 16))
            t = min(t, Fraction(1))
            X = t if rng.getrandbits(1) else 1 / t
            b = ml._enc(fmt, X) + rng.randint(-2, 2)
            out.append(b | (fmt.sign_mask if s else 0))
        elif mode == "big":
            out.append(_rand_sig(rng, fmt, rng.randint(p // 2, fmt.emax), s))
        elif mode == "small":
            out.append(_rand_sig(rng, fmt, rng.randint(ga, -5), s))
        else:
            raise ValueError(f"region {mode!r}: one of {', '.join(REGIONS)}")
    return out


# the samplers by function (M4G2 and M4G3 assign theirs: sampler(fmt, mode, n,
# seed) -> lanes)
SAMPLE_FNS = {"atan": _sample_atan}


def sample(fn, fmt, mode, n, seed):
    return SAMPLE_FNS[fn](fmt, mode, n, seed)


def _finite(fmt, b):
    return sf.unpack(fmt, b).kind not in (sf.NAN, sf.INF, sf.ZERO)


def _in_main_atan(fmt, x):
    """Whether the main path answers x: finite, nonzero, not under the tiny
    gate 2^gc."""
    if not _finite(fmt, x):
        return False
    return (x & ~fmt.sign_mask) >= ml._pow2(fmt, ml.trig_gates(fmt)[1])


IN_MAIN = {"atan": _in_main_atan}


def in_main(fn, fmt, x):
    return IN_MAIN[fn](fmt, x)


# ---- the structured lanes -----------------------------------------------------

# The committed list of the lanes that must mark (the study's 3.5, plants.py's
# candidates, census.py's): by format, [(the attributes, the lanes)], each lane
# also with its sign flipped. A lane here is a float whose true value sits
# within the in-lane bound of a rounding boundary of the attribute. Atan's:
# fp64 3 2^-26, where atan(x) = x - x^3/3 + ... sits within the bound of the
# midpoint under rne and rmm; the windows' centres, a grid point (rtz, rdn,
# rup) and a midpoint (rne, rmm), each with the neighbour on either side; and
# the first tiny lanes at fp128 and fp256 under the directed three (the tiny
# gate's edge, where the result is a hair below the argument; census.*.out.txt,
# MEASURED by the study's drafter). The whole families are parcel M4G4's.
_DIRECTED = (RTZ, RDN, RUP)
_NEAREST = (RNE, RMM)
STRUCT = {
    "atan": {
        "fp64": [(_NEAREST, [0x3e68000000000000]),
                 (_DIRECTED, [0x434d02967c31cdb4, 0x434d02967c31cdb5,
                              0x434d02967c31cdb6]),
                 (_NEAREST, [0x43349ff16b9c1e3d, 0x43349ff16b9c1e3e,
                             0x43349ff16b9c1e3f])],
        "fp128": [(_DIRECTED, [0x40711c46bd57277993a2ee60193c957a,
                               0x40711c46bd57277993a2ee60193c957b,
                               0x40711c46bd57277993a2ee60193c957c]),
                  (_NEAREST, [0x406f6109e5326af7afff76b6dfd05004,
                              0x406f6109e5326af7afff76b6dfd05005,
                              0x406f6109e5326af7afff76b6dfd05006]),
                  (_DIRECTED, [0x3fd78000000000000000000000000000])],
        "fp256": [(_DIRECTED, [
            0x400ec1bf8c524542c943c6d4e82ad1428d9158f77f54d3ffe8301f68d3bd219a,
            0x400ec1bf8c524542c943c6d4e82ad1428d9158f77f54d3ffe8301f68d3bd219b,
            0x400ec1bf8c524542c943c6d4e82ad1428d9158f77f54d3ffe8301f68d3bd219c]),
                  (_NEAREST, [
            0x400eb0d42e9ba6f1bb5d01e5b39c73df565dc6a99d47236fad2557593d6bf5f4,
            0x400eb0d42e9ba6f1bb5d01e5b39c73df565dc6a99d47236fad2557593d6bf5f5,
            0x400eb0d42e9ba6f1bb5d01e5b39c73df565dc6a99d47236fad2557593d6bf5f6]),
                  (_DIRECTED, [
            0x3ffb880000000000000000000000000000000000000000000000000000000000])],
    },
}
# A PIN on the fragment's current guesses, not a claim of correctness: the
# marked lanes whose guess differs from transcend.py's. A marked lane's guess
# is not promised right (the replay with the definition decides it), and where
# the true value is within the bound of a midpoint it may fall either side. The
# brief asked every structured lane's guess to equal transcend.py's; for these
# it does not. The check fails on an unlisted wrong guess and on a listed lane
# whose guess has become right, so a change of the guess is seen, not judged.
# (function, format, attribute) -> lanes (MEASURED: the midpoint centre at fp64
# under rne and rmm, both signs).
STRUCT_GUESS_WRONG = {
    ("atan", "fp64", RNE): {0x43349ff16b9c1e3e, 0x43349ff16b9c1e3e | 1 << 63},
    ("atan", "fp64", RMM): {0x43349ff16b9c1e3e, 0x43349ff16b9c1e3e | 1 << 63},
}


# the functions whose committed lanes are taken as listed, no sign flipped:
# acos is not odd (acos(-x) = pi - acos(x)), so each lane carries its sign
ONE_SIGN = {"acos"}


def structured_lanes(fn, fmt, rnd, table=None):
    """The committed lanes of (fn, fmt, rnd), each also with its sign
    flipped (y's for a pair: atan2(-y, x) = -atan2(y, x)), but for the
    functions of ONE_SIGN, whose lanes are taken as listed."""
    out = []
    for rnds, lanes in (STRUCT if table is None else table)[fn].get(
            fmt.name, []):
        if rnd in rnds:
            for x in lanes:
                if fn in ONE_SIGN:
                    out.append(x)
                elif isinstance(x, tuple):
                    out += [x, (x[0] | fmt.sign_mask,) + x[1:]]
                else:
                    out += [x, x | fmt.sign_mask]
    return out


def check_structured(f, evaluator=None, table=None, wrong=None):
    """[finding], lanes: structured. Each committed lane of the fragment's
    (function, format, attribute) marked, its guess equal to transcend.py's
    except where the exceptions (STRUCT_GUESS_WRONG, or `wrong`) list it, and
    those listed differing. The configurations the list has no lanes for pass
    with none run. `evaluator` stands for ml.evaluate, for the test that
    plants a fault in it."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    exc = (STRUCT_GUESS_WRONG if wrong is None else wrong).get(
        (fn, fmt.name, rnd), set())
    lanes = structured_lanes(fn, fmt, rnd, table)
    unmarked, bad_guess, listed_right = [], [], []
    for x in lanes:
        bits, fw = (evaluator or ml.evaluate)(f, x)
        if not fw & MARK:
            unmarked.append(x)
            continue
        same = (bits, fw & 0x1F) == golden(fmt, rnd, x, fn)
        if not same and x not in exc:
            bad_guess.append(x)
        if same and x in exc:
            listed_right.append(x)
    where = f"structured: {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if unmarked:
        out.append(f"{where}: {len(unmarked)} of the {len(lanes)} committed "
                   f"lanes are not marked, first {_hexes(unmarked)}")
    if bad_guess:
        out.append(f"{where}: {len(bad_guess)} marked lanes have a guess that "
                   f"differs from transcend.{fn}, first {_hexes(bad_guess)}")
    if listed_right:
        out.append(f"{where}: {len(listed_right)} lanes listed as having a "
                   f"wrong guess have the right one, first "
                   f"{_hexes(listed_right)}")
    return out, lanes


# ---- seq.py -------------------------------------------------------------------

# the functions with seq lanes of their own, SEQ_LANES[fn](fmt) -> lanes (atan2's
# are pairs, parcel M4G3's); atan, asin and acos keep the unary lanes below
SEQ_LANES = {}


def _seq_lanes(fn, fmt):
    """The lanes of the seq check: the brute pool, every 16th power of two of
    the stage's pool, and 64 random main-path arguments (seed 11); or the
    function's own (SEQ_LANES)."""
    if fn in SEQ_LANES:
        return SEQ_LANES[fn](fmt)
    from test_transcend import _brute_pool
    tc = H._transcend_check()
    stage = tc.trig_pool(fmt, 64 if fmt.width <= 64 else 16, 5)
    out = set(_brute_pool(fmt))
    out |= set(sorted(b for b in stage if (b & fmt.man_mask) == 0)[::16])
    out |= set(sample(fn, fmt, "random", 64, 11))
    return tuple(sorted(out))


@functools.lru_cache(maxsize=None)
def seq_slice(fn, fmt):
    return _seq_lanes(fn, fmt)


# the marked lane of the seq check: atan(3 2^-26) under rne at fp64 (the card's
# case); the structured lanes of the configuration are added to the lanes
SEQ_MARKED = {("atan", "fp64", RNE): 0x3e68000000000000}
# further lanes that must be marked in the byte, by (function, format): atan2's
# range lanes (parcel M4G3's)
SEQ_RANGE = {}


LOUD_MUL = 3


def _loud(prog, bank, fmt, nth=LOUD_MUL):
    """The compiled program with its QUIET moved to just after the body's
    nth MUL (the third, P = c d_h, by default): that instruction is outside
    the quiet region and raises its flags on the lane, the fault the byte must
    see. The first two MULs are exact at d = 1 (the seed of 1 is 1 - 2^-11) and
    the lane's flag word says inexact for every lane that is not exact, so the
    fault shows on a lane where this MUL raises what the result's flag word
    does not: +inf, where P = 0 x inf raises invalid early and the byte is
    inexact alone at the end (the fifth MUL shows on x = 0, the seventh on the
    minimum normal: underflow raised early)."""
    insns = list(prog.insns)
    q = next(i for i, w in enumerate(insns) if seq.decode(w)["op"] == seq.QUIET
             and seq.decode(w)["ctrl"])
    muls = [i for i in range(q + 1, len(insns))
            if not seq.decode(insns[i])["ctrl"]
            and seq.decode(insns[i])["op"] == sf.OP_MUL]
    k = muls[nth - 1]
    insns = insns[:q] + insns[q + 1:k + 1] + [insns[q]] + insns[k + 1:]
    return seq.Program(fmt, insns, consts=(), max_deposits=1,
                       flags=seq.FLAG_BANK_EXT, n_consts=len(bank))


def _split(xs):
    """(a, b): the lanes' first and second operands, for seq.run: a pair
    (y, x) gives y in r0 and x in r1, an encoding gives itself and zero."""
    if any(isinstance(x, tuple) for x in xs):
        return [x[0] for x in xs], [x[1] for x in xs]
    return list(xs), [0] * len(xs)


def check_seq(f, xs=None, evaluator=None, loud=False, post=None, table=None):
    """[finding], lanes: seq. The fragment as a program on seq.py
    (routines.program and routines.run) equal to evaluate() lane for lane
    (`evaluator` stands for it, for the test that plants a fault in it) and,
    where unmarked, to transcend.py; the compiled shape (QUIET, the body,
    ENDQUIET, RAISE of the flag word: mathlib_harness.r24_program, `loud`
    moving the QUIET past the third MUL, which raises invalid outside it on
    +inf; an int moves it past that MUL instead) with
    each lane's byte the IEEE flags of the operation and the mark in bit 7,
    FLAGS the OR of the bytes and STATUS[6] set exactly when a lane is marked
    (`post`, a function of seq.py's result, doctors it for the test); and the
    committed lanes of the configuration among the lanes, marked in the
    byte."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    xs = list(seq_slice(fn, fmt) if xs is None else xs)
    struct = structured_lanes(fn, fmt, rnd, table)
    if (fn, fmt.name, rnd) in SEQ_MARKED:
        struct = struct + [SEQ_MARKED[(fn, fmt.name, rnd)]]
    struct = struct + list(SEQ_RANGE.get((fn, fmt.name), ()))
    have = set(xs)
    xs += [x for x in dict.fromkeys(struct) if x not in have]
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
    prog, bank = H.r24_program(f)
    if loud:
        prog = _loud(prog, bank, fmt) if loud is True \
            else _loud(prog, bank, fmt, loud)
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
    off = [x for x in struct
           if not res.lane_flags[index[x]] & seq.LANE_MARKED]
    if off:
        out.append(f"{where}: {len(off)} of the committed lanes are not "
                   f"marked in the lane's byte, first {_hexes(off)}")
    return out[:8], xs


# ---- the bound ----------------------------------------------------------------

def bound_log2(b, x):
    """log2(|V - f(x)| / Bv) for one main-path lane of the build b: V the sum
    of its probes Vh and Vl, the true value from mpmath at 4p + 200 bits.
    None where V is exact; 999.0 where V is not finite."""
    fmt = b.fmt
    _res, _fl, pr = b.run(x, ("Vh", "Vl", "Bv"))
    try:
        V = value(fmt, pr["Vh"]) + value(fmt, pr["Vl"])
        Bv = abs(value(fmt, pr["Bv"]))
    except ValueError:
        return 999.0
    with mpmath.workprec(4 * fmt.prec + 200):
        err = abs(_mp(V) - true_value(b.meta["fn"], fmt, x))
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
        if not in_main(fn, fmt, x):
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
                   f"bound, the worst {_hexes([x])} at 2^{r:+.2f} of Bv")
    if differ:
        out.append(f"{where}: {len(differ)} unmarked lanes differ from "
                   f"transcend.{fn}, first {_hexes([differ[0]])}")
    return out, (worst, n, len(xs))


# the regions of each function's bound check (the study's 3.2): atan's are
# REGIONS; M4G2 and M4G3 assign theirs, with the diagonal (diag)
REGIONS_BY_FN = {"atan": REGIONS}


def placed_points(fn, fmt, n=48, seed=11):
    """The bound check's lanes: n points of each of the function's regions
    (REGIONS_BY_FN; atan's edge, big, small and random), seed `seed`."""
    return {r: sample(fn, fmt, r, n, seed) for r in REGIONS_BY_FN[fn]}


# ---- the specials ----------------------------------------------------------------

def _V(fmt, s, m, e):
    b, fl = sf.round_pack(fmt, s, m, e, RNE)
    assert fl == 0, (m, e)
    return b


def _rows_atan(fmt):
    """[(label, lanes)]: the rows of the study's section 4 for atan
    (specials.py's), each in both signs where the row has them."""
    p = fmt.prec
    ga = ml.trig_gates(fmt)[1]
    one, mxn = sf.one_bits(fmt), sf.max_normal_bits(fmt)
    S = fmt.sign_mask
    rows = [("+0, -0", [0, S]),
            ("+inf, -inf", [sf.inf_bits(fmt), sf.inf_bits(fmt) | S]),
            ("qNaN, both signs", [sf.qnan_bits(fmt), sf.qnan_bits(fmt) | S]),
            ("sNaN, both signs", [sf.snan_bits(fmt), sf.snan_bits(fmt) | S]),
            ("minSub, both signs", [sf.min_subnormal_bits(fmt),
                                    sf.min_subnormal_bits(fmt) | S]),
            ("maxSub, both signs", [sf.max_subnormal_bits(fmt),
                                    sf.max_subnormal_bits(fmt) | S]),
            ("minNormal, both signs", [sf.min_normal_bits(fmt),
                                       sf.min_normal_bits(fmt) | S]),
            (f"gate - ulp (2^{ga} - ulp), both signs",
             [_V(fmt, 0, 1, ga) - 1, (_V(fmt, 0, 1, ga) - 1) | S]),
            (f"gate 2^{ga}, both signs", [_V(fmt, 0, 1, ga),
                                          _V(fmt, 0, 1, ga) | S]),
            ("+1, -1", [one, sf.one_bits(fmt, 1)]),
            ("+maxN, -maxN", [mxn, mxn | S]),
            (f"2^{p}, both signs", [_V(fmt, 0, 1, p), _V(fmt, 0, 1, p) | S]),
            (f"2^{p + 2}, both signs", [_V(fmt, 0, 1, p + 2),
                                        _V(fmt, 0, 1, p + 2) | S])]
    return rows


# the rows of each function, by function (M4G2 and M4G3 assign theirs)
SPECIAL_ROWS = {"atan": _rows_atan}


def special_rows(fn, fmt):
    return SPECIAL_ROWS[fn](fmt)


def check_specials(f, evaluator=None, rows=None):
    """[finding], lanes: specials. Every row of the function's special_rows()
    through the fragment: equal to transcend.py in bits AND flag word and not
    marked. `evaluator` stands for ml.evaluate, for the test that plants a
    fault in it; `rows` for the table."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    out, n = [], 0
    for label, lanes in (special_rows(fn, fmt) if rows is None else rows):
        bad = []
        for x in lanes:
            n += 1
            bits, fw = (evaluator or ml.evaluate)(f, x)
            if fw & MARK or (bits, fw) != golden(fmt, rnd, x, fn):
                bad.append((x, (bits, fw), golden(fmt, rnd, x, fn)))
        if bad:
            x, got, want = bad[0]
            out.append(f"specials: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: row "
                       f"{label!r}: {len(bad)} of {len(lanes)} lanes differ "
                       f"or are marked, first {_hexes([x])}: ({got[0]:#x}, "
                       f"{got[1]:#x}) against ({want[0]:#x}, {want[1]:#x})")
    return out, n


# ---- the shape --------------------------------------------------------------

# (instructions, bank words, values live) of every fragment, in RND_MODES'
# order (rne, rtz, rdn, rup, rmm): MEASURED by parcel M4G1. The instructions
# are the study's (costs.fp64, fp128, fp256.out.txt: atan 176, 186, 203 under
# every attribute), the words its (54, 62, 77), the live counts the design's
# order's 15 (the order the fragments are emitted in: schedule_order's other
# two candidates keep more).
SHAPE = {
    ("atan", "fp64"): [(176, 54, 15)] * 5,
    ("atan", "fp128"): [(186, 62, 15)] * 5,
    ("atan", "fp256"): [(203, 77, 15)] * 5,
}

# the study's instructions by phase (costs.*.out.txt): the quotient (17, 19,
# 21: the Newton steps) and the tail (6, 14, 29: D - K FMAs) are the
# formats'; the rest is the same at every format
_PHASES_ATAN = {"front": 5, "index": 7, "num": 6, "den": 6, "z": 6,
                "head": 52, "atan_s": 6, "table": 17, "recon": 23,
                "final": 9, "classify": 4, "special": 12}
_QUOTIENT = {"fp64": 17, "fp128": 19, "fp256": 21}
_TAIL = {"fp64": 6, "fp128": 14, "fp256": 29}


# the model's instructions by phase, by function: (those equal at every
# format, {phase: {format: count}} for the rest); M4G2 and M4G3 assign theirs
MODEL_PHASES = {"atan": (_PHASES_ATAN, {"quotient": _QUOTIENT, "tail": _TAIL})}


def model_phases(fn, fmt_name):
    """The model's instructions by phase for fn at the format."""
    if fn not in MODEL_PHASES:
        raise ValueError(f"no phases of {fn} pinned")
    same, by_fmt = MODEL_PHASES[fn]
    return dict(same, **{k: v[fmt_name] for k, v in by_fmt.items()})


# The values the flag word takes (the study's section 4; MEASURED by its
# costs.py): the pools saw exactly these.
FLAG_WORDS = {"atan": frozenset({0x0, 0x1, 0x10, 0x18, 0x90})}
# (MIN, MAX) instructions: the index's one MIN (k at most 7), no MAX
MIN_MAX = {"atan": (1, 0)}


class Tables:
    """The pinned data the shape check reads, one attribute a table, so that a
    test can doctor one and show its leg fail alone."""

    def __init__(self, **kw):
        self.shape = SHAPE
        self.phases = model_phases
        self.flag_words = FLAG_WORDS
        self.min_max = MIN_MAX
        self.caps = ml.INV_LIVE_CAP
        for k, v in kw.items():
            if not hasattr(self, k):
                raise ValueError(f"no table {k!r}")
            setattr(self, k, v)


def check_shape(fmt, builds, tables=None, fragments=None):
    """[finding]: shape. `builds`: {(fn, rnd): Build} for the functions built
    under all five attributes at `fmt`. Per fragment: (instructions, words,
    live) the pinned ones; the instructions by phase the model's; the flag
    word's values exactly the study's; MIN and MAX as pinned (the index's one
    MIN, no MAX); the scheduled fragment the design's reordered
    (mathlib_harness.check_reorder); its own invariants under INV_LIVE_CAP.
    Per function: its INV_LIVE_CAP entry the measured maximum under the five
    attributes, the fragment of that maximum holding to it and failing, by
    name, a cap one under. `tables` (Tables) holds the pinned data, one
    attribute a table; `fragments` {(fn, rnd): Fragment} stands for the
    builds' own scheduled fragments: both are for the tests that doctor one
    leg."""
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
                       f"design's {t.min_max[fn][0]} and {t.min_max[fn][1]} "
                       f"(the index's MIN alone)")
        out += [f"shape: {s}" for s in H.check_reorder(b, f)]
        out += [f"{where}: invariants: {s}"
                for s in ml.invariants(f, live_cap=t.caps[fn][name])]
    for fn in fns:
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
    return out


# ---- the audit: the index's exactness, lane by lane --------------------------

def audit_lanes(fmt):
    """(n, d) lanes for the audit, ported from the study's plants.py: (1) d = 1
    + frac/2048, the upper half of the seed's cell 0, where d RECIP_SEED(d) >
    1, with n just under d/16: an unbiased index takes k = 1 at t/c < 1/2, but
    n and P - n share a binade and the difference stays exact; (2) d = 2 -
    2^-e (e = 12, 14, 20), the top seed cell's upper part, with n just under 1/8
    - (2 - d)/8 and its last bit set: there 1/8 lies between n and P - n, and
    the unbiased index's n_h - P is inexact (the study's 3.6, item 7); (3) the
    cells' ends, d = 1. 214 lanes at each format (MEASURED). A few of the
    cells' lanes have n one or two ulps past d: check_audit sorts each lane to
    n <= d first."""
    p = fmt.prec
    out = []
    for frac_ in (3, 5, 7):                  # d = 1 + frac/2048: cell 0's top
        d = sf.round_pack(fmt, 0, (1 << (p - 1)) + (frac_ << (p - 12)),
                          -(p - 1), RNE)[0]
        D = value(fmt, d)
        for j in range(0, 40):
            n = ml._enc(fmt, D / 16 * (1 - Fraction(j, 2 ** 16)), RTZ)
            out.append((n, d))
    ulp_n = Fraction(1, 2 ** (p + 3))        # n in [1/16, 1/8)
    for e in (12, 14, 20):                   # d = 2 - 2^-e: the top cell
        eps = Fraction(1, 2 ** e)
        d = ml._enc(fmt, 2 - eps)
        for j in range(0, 8):
            out.append((ml._enc(fmt, Fraction(1, 8) - eps / 8
                                - (2 * j + 1) * ulp_n), d))
    for k, (lo, hi) in enumerate(ml.inv_cells(ml.INV_N)):
        for t in (lo, hi):
            for j in (-2, -1, 0, 1, 2):
                if 0 < t <= 1:
                    out.append((ml._enc(fmt, t) + j, sf.one_bits(fmt)))
    return out


def _bound_log2(theta, true, p, G):
    """log2 of |theta - true| / (2^-(p+G) theta), None where they are equal;
    at the caller's working precision."""
    err = abs(_mp(theta) - true)
    if not err:
        return None
    if not theta:
        return math.inf
    return float(mpmath.log(err / (abs(_mp(theta)) * mpmath.mpf(2) ** -(p + G)),
                            2))


def check_audit(fmt, plant=None, lanes=None, b=None):
    """[finding], tally: audit. audit_lanes(fmt) through build_inv_core (n, d
    single words), each lane sorted to n <= d first. Per lane with k >= 1: n_h
    / P in [1/2, 2] (Sterbenz's premise) and n_h - P equal to its exact value
    (Nh0); per lane: |theta0 - atan(n/d)| under 2^-(p+G) theta0, mpmath at 4p
    + 200 bits. tally: lanes, premise (lanes with the premise broken),
    inexact, past (past the bound), largest (log2 of the largest |theta0 -
    atan| / (2^-(p+G) theta0)). This is the only check that sees
    sterbenz_bias: on atan's own lanes d = 1 or n = 1 never meets the
    overestimating seed's k = 1 below t = 1/16."""
    b = core_of(fmt, plant) if b is None else b
    p, G = fmt.prec, b.meta["G"]
    lanes = audit_lanes(fmt) if lanes is None else lanes
    magic = ml._enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    tally = {"lanes": 0, "premise": 0, "inexact": 0, "past": 0,
             "largest": -1e9}
    first = {}
    with mpmath.workprec(4 * p + 200):
        for n, d in lanes:
            if value(fmt, n) > value(fmt, d):
                n, d = d, n
            th, tl, pr = b.run((n, d), ("nh", "P", "Nh0", "Kk"))
            tally["lanes"] += 1
            if pr["Kk"] != magic:
                nh, P_, N0 = (value(fmt, pr[k]) for k in ("nh", "P", "Nh0"))
                if P_ and not (Fraction(1, 2) <= nh / P_ <= 2):
                    tally["premise"] += 1
                    first.setdefault("premise", (n, d))
                if nh - P_ != N0:
                    tally["inexact"] += 1
                    first.setdefault("inexact", (n, d))
            theta = value(fmt, th) + value(fmt, tl)
            true = mpmath.atan(_mp(value(fmt, n)) / _mp(value(fmt, d)))
            r = _bound_log2(theta, true, p, G)
            if r is not None:
                tally["largest"] = max(tally["largest"], r)
                if r > 0:
                    tally["past"] += 1
                    first.setdefault("past", (n, d))
    where = f"audit: {fmt.name}" + (f" plant {plant}" if plant else "")
    out = []
    if tally["premise"]:
        out.append(f"{where}: {tally['premise']} of {tally['lanes']} lanes "
                   f"have n_h / P outside [1/2, 2], first "
                   f"{_hexes([first['premise']], 1)}")
    if tally["inexact"]:
        out.append(f"{where}: {tally['inexact']} of {tally['lanes']} lanes "
                   f"have n_h - P inexact, first "
                   f"{_hexes([first['inexact']], 1)}")
    if tally["past"]:
        out.append(f"{where}: {tally['past']} of {tally['lanes']} lanes have "
                   f"|theta0 - atan(n/d)| past 2^-(p+G) theta0, first "
                   f"{_hexes([first['past']], 1)}, the largest "
                   f"2^{tally['largest']:+.1f} of the bound")
    return out, tally


# ---- the core: double-word operands, and the contract of Kk -------------------

def core_lanes(fmt, n=60, seed=31):
    """(n_h, n_l, d_h, d_l) lanes for build_inv_core(double=True), n of them
    (three of them t = 1), n <= d and n_h <= d_h: t = n/d from the cells' edges and at random, d_h
    with a random exponent from -40 to 40, n_h its product with t, the low
    words |lo| <= ulp/2 of either sign (zero, the extremes and random)."""
    rng = random.Random(seed * 1000003 + fmt.width)
    p = fmt.prec
    edges = [e for lo_hi in ml.inv_cells(ml.INV_N) for e in lo_hi
             if 0 < e <= 1]
    # t = 1 exactly (theta0 = pi/4, the most th can be) at three scales, so
    # that over_pi4 is measured where it can be positive
    out = [(h, 0, h, 0) for h in (sf.one_bits(fmt),
                                  ml._enc(fmt, Fraction(17, 10)),
                                  ml._enc(fmt, Fraction(3, 10)))]

    def low(h):
        r = rng.choice((0, 1 << (p - 2), -(1 << (p - 2)), 1, -1,
                        rng.randint(-(1 << (p - 2)), 1 << (p - 2))))
        return ml._enc(fmt, value(fmt, h) * Fraction(r, 2 ** (2 * p - 1)))
    while len(out) < n:
        dh = _rand_sig(rng, fmt, rng.randint(-40, 40), 0)
        if len(out) % 2:
            t = rng.choice(edges) * (1 + Fraction(rng.randint(-64, 64),
                                                  2 ** 16))
        else:
            t = Fraction(rng.getrandbits(40) + 1, 1 << 40)
        t = min(t, Fraction(1))
        nh = ml._enc(fmt, value(fmt, dh) * t)
        nl, dl = low(nh), low(dh)
        N = value(fmt, nh) + value(fmt, nl)
        D = value(fmt, dh) + value(fmt, dl)
        if N > D:
            nh, nl, dh, dl = dh, dl, nh, nl
        if nh > dh or value(fmt, nh) + value(fmt, nl) <= 0:
            continue
        out.append((nh, nl, dh, dl))
    return out


def check_core(fmt, plant=None, lanes=None, b=None):
    """[finding], tally: core. build_inv_core(double=True) on placed (n_h, n_l,
    d_h, d_l): th + tl within 2^-(p+G) theta0 of atan(n/d), mpmath at 4p + 200
    bits; 0 <= th; and the contract of Kk on every lane, k recomputed from t~
    in exact rationals (k = min(7, round-half-even(8 (63/64) t~))): Kk's low
    three bits are k, and Kk is the word MAGIC exactly where k = 0. tally:
    lanes, past, kk (lanes whose Kk breaks the contract), negative (th < 0),
    largest (log2 of the largest error over the bound), over_pi4 (the
    largest (th - pi/4) / ulp(pi/4), as a float)."""
    b = core_of(fmt, plant, True) if b is None else b
    p, G = fmt.prec, b.meta["G"]
    lanes = core_lanes(fmt) if lanes is None else lanes
    magic = ml._enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    tally = {"lanes": 0, "past": 0, "kk": 0, "negative": 0,
             "largest": -1e9, "over_pi4": -math.inf}
    first = {}
    with mpmath.workprec(4 * p + 200):
        pi4 = mpmath.pi / 4
        ulp = mpmath.mpf(2) ** (int(mpmath.floor(mpmath.log(pi4, 2))) - p + 1)
        for lane in lanes:
            th, tl, pr = b.run(lane, ("Kk", "tt"))
            tally["lanes"] += 1
            nh, nl, dh, dl = (value(fmt, v) for v in lane)
            k = min(7, round(Fraction(8 * 63, 64) * value(fmt, pr["tt"])))
            if (pr["Kk"] & 7) != k or (pr["Kk"] == magic) != (k == 0):
                tally["kk"] += 1
                first.setdefault("kk", lane)
            theta = value(fmt, th) + value(fmt, tl)
            if value(fmt, th) < 0:
                tally["negative"] += 1
                first.setdefault("negative", lane)
            true = mpmath.atan(_mp((nh + nl) / (dh + dl)))
            r = _bound_log2(theta, true, p, G)
            if r is not None:
                tally["largest"] = max(tally["largest"], r)
                if r > 0:
                    tally["past"] += 1
                    first.setdefault("past", lane)
            tally["over_pi4"] = max(tally["over_pi4"],
                                    float((_mp(value(fmt, th)) - pi4) / ulp))
    where = f"core: {fmt.name}" + (f" plant {plant}" if plant else "")
    out = []
    if tally["past"]:
        out.append(f"{where}: {tally['past']} of {tally['lanes']} lanes have "
                   f"|theta0 - atan(n/d)| past 2^-(p+G) theta0, first "
                   f"{_hexes([first['past']], 1)}, the largest "
                   f"2^{tally['largest']:+.1f} of the bound")
    if tally["kk"]:
        out.append(f"{where}: {tally['kk']} of {tally['lanes']} lanes break "
                   f"Kk's contract (low bits k, MAGIC exactly where k = 0), "
                   f"first {_hexes([first['kk']], 1)}")
    if tally["negative"]:
        out.append(f"{where}: {tally['negative']} lanes have th < 0, first "
                   f"{_hexes([first['negative']], 1)}")
    return out, tally


# ---- the constants ----------------------------------------------------------------

def check_constants(**kw):
    """[finding], lines: constants. mathlib.check_inv_constants() in process,
    at INV_FORMATS unless `formats` is given."""
    kw.setdefault("formats", FORMATS)
    lines, findings = ml.check_inv_constants(**kw)
    return [f"constants: {s}" for s in findings], lines


# ---- the plants: every check on every plant ---------------------------------------

def red_checks(plant, fmt=FP64, pool_rnds=(RNE, RTZ), seq_rnds=(RNE, RTZ),
               bound_n=48):
    """{check: [findings]} for the checks that are RED on `plant` (None: the
    control) at `fmt`: pools and seq under pool_rnds and seq_rnds, bound over
    the four regions (bound_n points each) under rne, structured, specials and
    shape under all five attributes, audit, core and constants (rne). A check
    a plant cannot reach (a fault outside the core, for audit and core) is
    green there: build_inv_core refuses the plant by name and the check does
    not run."""
    fn = "atan"
    red = {}

    def add(name, found):
        if found:
            red.setdefault(name, []).extend(found)
    for rnd in pool_rnds:
        add("pools", check_pools(fragment_of(fn, fmt, rnd, plant))[0])
    for rnd in seq_rnds:
        add("seq", check_seq(fragment_of(fn, fmt, rnd, plant))[0])
    b = build_of(fn, fmt, RNE, plant)
    for region, xs in placed_points(fn, fmt, bound_n).items():
        add("bound", check_bound(b, xs, region)[0])
    for rnd in RND_MODES:
        f = fragment_of(fn, fmt, rnd, plant)
        add("structured", check_structured(f)[0])
        add("specials", check_specials(f)[0])
    add("shape", check_shape(fmt, {(fn, rnd): build_of(fn, fmt, rnd, plant)
                                   for rnd in RND_MODES}))
    try:
        core_of(fmt, plant)
    except ValueError as e:
        if "does not apply" not in str(e):
            raise
    else:
        add("audit", check_audit(fmt, plant)[0])
        add("core", check_core(fmt, plant)[0])
    add("constants", check_constants(
        builder=lambda name, f_, r_: build_of(name, f_, r_, plant),
        formats=(fmt,), attrs=(RNE,), names=(fn,))[0])
    return red


# ---- asin and acos: parcel M4G2 builds here ----
#
# (assign into POOL_FNS, TRUE_FNS, SAMPLE_FNS, IN_MAIN, SPECIAL_ROWS, STRUCT,
# SHAPE, FLAG_WORDS, MIN_MAX and extend INV_POOL_MARKS, model_phases and the
# plants table of test_mathlib_inv.py; do not edit the checks above)


# ---- atan2: parcel M4G3 builds here ----
#
# (the same tables, by function; atan2 lanes are tuples (y, x))
#
# atan2 is the first built routine with two inputs: a lane is a tuple (y, x),
# y first as C and transcend.py have it. The tables below are the study's
# (docs/studies/m4/: m4harness.pair_pool, m4measure.sample and in_main,
# specials.rows, plants.py's audit and corner), ported; nothing here imports
# the model. Lists that are literals were taken from the FRAGMENT (marked
# "taken from the fragment"): they hold what it does, not what the definition
# says, and each has an independent leg beside it where one exists.

def _atan2_pool(fmt):
    """The pairs, deduplicated in a fixed order: the stage's
    (transcend_check.atan2_pairs at 64 trials at fp64 and 16 above, seed 5),
    the vector sets' new ones (vectors.trig_atan2_pairs, extra 24, seed 13),
    test_transcend's brute pool as it draws a binary function's pairs
    (pool[:9] x pool[:9]) new ones: 527, 479 and 479 at fp64, fp128, fp256."""
    from test_transcend import _brute_pool
    t = 64 if fmt.width <= 64 else 16
    stage = list(H._transcend_check().atan2_pairs(fmt, t, 5))
    vec = list(vectors.trig_atan2_pairs(fmt, 24, 13))
    bp = _brute_pool(fmt)[:9]
    brute = [(a, b) for a in bp for b in bp]
    return tuple(dict.fromkeys(stage + vec + brute))


POOL_FNS["atan2"] = _atan2_pool


def _true_atan2(fmt, lane):
    return mpmath.atan2(_mp(value(fmt, lane[0])), _mp(value(fmt, lane[1])))


TRUE_FNS["atan2"] = _true_atan2

# the regions of atan2's bound check: atan's four and the diagonal
REGIONS_BY_FN["atan2"] = REGIONS + ("diag",)


def _sample_atan2(fmt, mode, n, seed):
    """n pairs (y, x) placed where the bound binds (m4measure.sample, atan2's
    branch): random, both operands' exponents within p + 40 of each other;
    edge, y/x at the table's cells' edges (and swapped) with the last bits
    moved; diag, y/x = 1 and one to four ulps off; big, |y| far above |x|;
    small, |y| far below |x|; tinyn, send-back 1's corner: a subnormal or tiny
    |y| (exponent from the subnormal grid to emin + 3p + 4) against a larger
    |x|, 70% x > 0 with t from the tiny-quotient range's edge to 1/4 or in the
    band above it, 10% x over the whole range, 10% x < 0, 10% swapped."""
    rng = random.Random(seed * 1000003 + fmt.width * 7 + len("atan2"))
    p = fmt.prec
    emin, emax = fmt.emin, fmt.emax
    edges = [e for lo_hi in ml.inv_cells(ml.INV_N) for e in lo_hi
             if 0 < e <= 1]
    S = fmt.sign_mask
    out = []
    for _ in range(n):
        rng.getrandbits(1)                   # the model draws it for every fn
        sy, sx = rng.getrandbits(1), rng.getrandbits(1)
        Ex = rng.randint(emin + 2 * p, emax - 2 * p)
        if mode == "random":
            Ey = Ex + rng.randint(-(p + 40), p + 40)
            out.append((_rand_sig(rng, fmt, Ey, sy),
                        _rand_sig(rng, fmt, Ex, sx)))
        elif mode in ("edge", "diag"):
            xb = _rand_sig(rng, fmt, Ex, 0)
            X = value(fmt, xb)
            if mode == "edge":
                t = rng.choice(edges) * (1 + Fraction(rng.randint(-64, 64),
                                                      2 ** 16))
                t = min(t, Fraction(1))
            else:
                t = Fraction(1)
            yb = ml._enc(fmt, X * t) + rng.randint(-4, 4)
            yb, xb = (yb, xb) if rng.getrandbits(1) else (xb, yb)
            out.append((yb | (S if sy else 0), xb | (S if sx else 0)))
        elif mode == "big":
            Ey = Ex + rng.randint(p // 2, 2 * p + 20)
            a, b = _rand_sig(rng, fmt, Ey, sy), _rand_sig(rng, fmt, Ex, sx)
            out.append((a, b) if rng.getrandbits(1)
                       else (b ^ (S if sx != sy else 0), a))
        elif mode == "small":
            Ey = Ex - rng.randint(4, min(p + 40, Ex - emin - p - 6))
            out.append((_rand_sig(rng, fmt, Ey, sy),
                        _rand_sig(rng, fmt, Ex, 0)))
        elif mode == "tinyn":
            Ey = rng.randint(emin - p + 1, emin + 3 * p + 4)
            if Ey < emin:
                k = Ey - emin + p - 1
                nb = (1 << k) | rng.getrandbits(k)
            else:
                nb = _rand_sig(rng, fmt, Ey, 0)
            u = rng.random()
            if 0.70 <= u < 0.80:
                Ex = rng.randint(Ey + 1, emax)
            elif 0.50 <= u < 0.70:
                Ex = Ey - rng.randint(emin + p + 2, emin + 2 * p + 4)
            else:
                Ex = Ey - rng.randint(emin + p + 2, -2)
            db = _rand_sig(rng, fmt, Ex, 0)
            ys = S if sy else 0
            if u < 0.80:
                out.append((nb | ys, db))
            elif u < 0.90:
                out.append((nb | ys, db | S))
            else:
                out.append((db | ys, nb | (S if sx else 0)))
        else:
            raise ValueError(f"region {mode!r}: one of {', '.join(REGIONS)}, "
                             f"diag, tinyn")
    return out


SAMPLE_FNS["atan2"] = _sample_atan2


def _in_main_atan2(fmt, lane):
    """Whether the main path answers the lane: both operands finite and
    nonzero, and not (x > 0, |y| < |x| and the quotient t = |y/x| below
    2^(emin+p+4), the tiny-quotient range with its margin, or below atan's
    gate 2^ga, where the exact-quotient rule acts: V is still the main
    path's there, but the budget's sample leaves it out). m4measure.in_main."""
    y, x = lane
    if not (_finite(fmt, y) and _finite(fmt, x)):
        return False
    Y, X = value(fmt, y), value(fmt, x)
    if X > 0 and abs(Y) < X:
        t = abs(Y) / X
        if t < Fraction(2) ** (fmt.emin + fmt.prec + 4):
            return False
        if t < Fraction(2) ** ml.trig_gates(fmt)[1]:
            return False
    return True


IN_MAIN["atan2"] = _in_main_atan2


# ---- the specials (specials.py's 76 rows), the range, the pins --------------------

def _all_rows_atan2(fmt):
    """specials.py's atan2 rows, [(label, (y, x))], in its order: 9.2.1's
    table (seven y against seven x), the NaNs, the diagonals, the exact
    quotients (decided in-lane by the rule, or marked in the tiny-quotient
    range) and the cases the first designs got wrong."""
    p = fmt.prec
    ga = ml.trig_gates(fmt)[1]
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    msub, mnn = sf.min_subnormal_bits(fmt), sf.min_normal_bits(fmt)
    mxn = sf.max_normal_bits(fmt)
    inf, qn, sn = sf.inf_bits(fmt), sf.qnan_bits(fmt), sf.snan_bits(fmt)
    S = fmt.sign_mask
    two = _V(fmt, 0, 1, 1)
    ys = {"+0": 0, "-0": S, "+1": one, "-1": mone, "+inf": inf,
          "-inf": inf | S, "+minSub": msub}
    xs = {"+0": 0, "-0": S, "+1": one, "-1": mone, "+inf": inf,
          "-inf": inf | S, "+maxN": mxn}
    r = [(f"9.2.1 y {yn}, x {xn}", (y, x))
         for yn, y in ys.items() for xn, x in xs.items()]
    r += [("NaN y", (qn, one)), ("NaN x", (one, qn)), ("sNaN y", (sn, one)),
          ("sNaN x", (one, sn)), ("NaN, sNaN", (qn, sn)),
          ("diagonal +1, +1", (one, one)), ("diagonal +1, -1", (one, mone)),
          ("diagonal -1, -1", (mone, mone)),
          ("diagonal minSub, -minSub", (msub, msub | S)),
          ("diagonal maxN, maxN", (mxn, mxn)),
          ("diagonal one off: 1+ulp, 1", (one + 1, one)),
          ("exact quotient minSub/2 (a subnormal midpoint)", (msub, two)),
          ("exact quotient -minSub/2", (msub | S, two)),
          ("exact quotient minSub/1", (msub, one)),
          ("exact quotient 2^(emin)/2^p", (mnn, _V(fmt, 0, 1, p))),
          ("exact quotient 2^-60 / 1", (_V(fmt, 0, 1, -60), one)),
          ("exact quotient 3 2^-60 / 3",
           (_V(fmt, 0, 9, -60), _V(fmt, 0, 3, 0))),
          ("exact quotient -2^-40 / 2", (_V(fmt, 1, 1, -40), two)),
          (f"exact quotient at the gate 2^{ga - 1}",
           (_V(fmt, 0, 1, ga - 1), one)),
          (f"exact quotient past the gate 2^{ga}", (_V(fmt, 0, 1, ga), one)),
          ("exact quotient 2^-60 against x < 0",
           (_V(fmt, 0, 1, -60), mone)),
          ("one ulp off exact 2^-60 / 1", (_V(fmt, 0, 1, -60) + 1, one)),
          ("one ulp off, divisor 1 + ulp", (_V(fmt, 0, 1, -60), one + 1)),
          ("|y| dominant, 1 / 2^-60", (one, _V(fmt, 0, 1, -60))),
          ("subnormal both, 3 minSub / minSub", (3 * msub, msub)),
          ("subnormal both, minSub / 3 minSub", (msub, 3 * msub)),
          ("maxN / (0.9 maxN), d + c n past maxN unscaled",
           (mxn, ml._enc(fmt, Fraction(9, 10) * value(fmt, mxn))))]
    return r


# The rows that MARK, by format (MEASURED on the fragment under the five
# attributes; the specials check fails on a row that marks): the eight of the tiny-quotient range
# at every format, and at fp64 under rtz, rdn and rup the ninth, the quotient
# within the bound of a grid point (the study's 3.5). The fragment's, not the
# definition's: a marking row is a row where the answer is not promised, so the
# range rows go in RANGE_ROWS, checked as marked, and the ninth in STRUCT.
_RANGE_LABELS = ("9.2.1 y +1, x +maxN", "9.2.1 y -1, x +maxN",
                 "9.2.1 y +minSub, x +1", "9.2.1 y +minSub, x +maxN",
                 "exact quotient minSub/2 (a subnormal midpoint)",
                 "exact quotient -minSub/2", "exact quotient minSub/1",
                 "exact quotient 2^(emin)/2^p")
_GRID_LABEL = "one ulp off, divisor 1 + ulp"
MARKING_ROWS = {"fp64": _RANGE_LABELS + (_GRID_LABEL,),
                "fp128": _RANGE_LABELS, "fp256": _RANGE_LABELS}

# The last y that marks in atan2(y, 1), under every attribute (found by
# bisection on the fragment: RECIP_SEED(1) = 1 - 2^-10, so t~ = y (1 - 2^-10)
# and the mark is t~ < 2^(emin+p+2): the edge is 1.000977 of that power of two,
# not the power itself) and y + 1, the first that does not.
RANGE_EDGE = {
    "fp64": 0x380040100401003,
    "fp128": 0x740040100401004010040100401003,
    "fp256": 0xf00040100401004010040100401004010040100401004010040100401003f,
}


def _rows_atan2(fmt):
    """[(label, [lane])] of the specials for atan2: specials.py's rows less the
    ones that mark at this format (MARKING_ROWS), plus the rows of the
    range's edge (the first y that does not mark, against x = 1) and, at
    fp64, the first j past the grid-point family's threshold (j = 12 does not
    mark; j = 1 to 11 do, STRUCT's)."""
    p = fmt.prec
    one = sf.one_bits(fmt)
    rows = [(label, [lane]) for label, lane in _all_rows_atan2(fmt)
            if label not in MARKING_ROWS[fmt.name]]
    rows.append(("the range's edge: first y that does not mark, y / 1",
                 [(RANGE_EDGE[fmt.name] + 1, one)]))
    if fmt.name == "fp64":
        rows.append(("grid-point family: 2^-(p+10) / (1 + 12 ulp), past the "
                     "last j that marks", [(_V(fmt, 0, 1, -(p + 10)),
                                            one + 12)]))
    return rows


SPECIAL_ROWS["atan2"] = _rows_atan2


def _range_rows(fmt):
    """[(label, lane)]: the tiny-quotient range's lanes that must mark, in a
    table of their own: the eight rows of 9.2.1 and the exact quotients that
    fall in it, and the last y that marks against x = 1."""
    rows = [(label, lane) for label, lane in _all_rows_atan2(fmt)
            if label in _RANGE_LABELS]
    rows.append(("the range's edge: last y that marks, y / 1",
                 (RANGE_EDGE[fmt.name], sf.one_bits(fmt))))
    return rows


RANGE_ROWS = {f.name: _range_rows(f) for f in FORMATS}
SEQ_RANGE.update({("atan2", n): [lane for _l, lane in rows]
                  for n, rows in RANGE_ROWS.items()})

SHAPE.update({
    ("atan2", "fp64"): [(218, 62, 19)] * 5,
    ("atan2", "fp128"): [(228, 70, 19)] * 5,
    ("atan2", "fp256"): [(245, 85, 19)] * 5,
})

# the model's instructions by phase for atan2 (costs.*.out.txt, box-out2/): no
# "classify" phase, the model classifies y and x inside recon and special
MODEL_PHASES["atan2"] = (
    {"front": 19, "index": 7, "num": 6, "den": 6, "z": 6, "head": 52,
     "atan_s": 6, "table": 17, "recon": 35, "final": 9, "special": 32},
    {"quotient": {"fp64": 17, "fp128": 19, "fp256": 21},
     "tail": {"fp64": 6, "fp128": 14, "fp256": 29}})
FLAG_WORDS["atan2"] = frozenset({0x0, 0x1, 0x10, 0x90})
MIN_MAX["atan2"] = (1, 0)

# atan2(3 2^-26, 1) under rne at fp64: marked (the same lane as atan's, the
# quotient exact and the answer a hair below the midpoint)
SEQ_MARKED[("atan2", "fp64", RNE)] = (0x3e68000000000000, 0x3ff0000000000000)


def _atan2_seq_lanes(fmt):
    """The seq check's pairs: the brute pool's 9 x 9, every 16th of the
    stage's pairs, and 64 random pairs (seed 11)."""
    from test_transcend import _brute_pool
    bp = _brute_pool(fmt)[:9]
    stage = H._transcend_check().atan2_pairs(
        fmt, 64 if fmt.width <= 64 else 16, 5)
    out = {(a, b) for a in bp for b in bp}
    out |= set(list(stage)[::16])
    out |= set(sample("atan2", fmt, "random", 64, 11))
    return tuple(sorted(out))


SEQ_LANES["atan2"] = _atan2_seq_lanes


# The marked lanes of the pools, taken from the FRAGMENT (the pool of each
# format through it: the same set under all five attributes), all of them in the
# tiny-quotient range (x > 0, |y| < |x|, t~ under 2^(emin+p+2)): 19, 15 and 19
# lanes. A committed list that holds what the fragment does, not what the
# definition says; check_pool_marks holds it to an independent predicate in
# exact rationals. A marked guess is not promised: the replay decides it.
_TQR_MARKED = {
    "fp64": [
        (0x3ff0000000000000, 0x7fefffffffffffff),
        (0xbff0000000000000, 0x7fefffffffffffff),
        (0x4000000000000000, 0x7fefffffffffffff),
        (0xc000000000000000, 0x7fefffffffffffff),
        (0x4008000000000000, 0x7fefffffffffffff),
        (0xc008000000000000, 0x7fefffffffffffff),
        (0x0000000000000001, 0x3ff0000000000000),
        (0x0000000000000001, 0x4000000000000000),
        (0x0000000000000001, 0x4008000000000000),
        (0x0000000000000001, 0x7fefffffffffffff),
        (0x8000000000000001, 0x3ff0000000000000),
        (0x8000000000000001, 0x4000000000000000),
        (0x8000000000000001, 0x4008000000000000),
        (0x8000000000000001, 0x7fefffffffffffff),
        (0x0000000000000001, 0x4010000000000000),
        (0xbe28666ff072ef3f, 0x7f69e175224dd1c6),
        (0xa2c193533bcb08a7, 0x68891a61646fc960),
        (0x02bab000e57fb3b2, 0x64161a9b0c22c03b),
        (0x02afd0615577c063, 0x6f7e9140b170de30),
    ],
    "fp128": [
        (0x3fff0000000000000000000000000000, 0x7ffeffffffffffffffffffffffffffff),
        (0xbfff0000000000000000000000000000, 0x7ffeffffffffffffffffffffffffffff),
        (0x40000000000000000000000000000000, 0x7ffeffffffffffffffffffffffffffff),
        (0xc0000000000000000000000000000000, 0x7ffeffffffffffffffffffffffffffff),
        (0x40008000000000000000000000000000, 0x7ffeffffffffffffffffffffffffffff),
        (0xc0008000000000000000000000000000, 0x7ffeffffffffffffffffffffffffffff),
        (0x00000000000000000000000000000001, 0x3fff0000000000000000000000000000),
        (0x00000000000000000000000000000001, 0x40000000000000000000000000000000),
        (0x00000000000000000000000000000001, 0x40008000000000000000000000000000),
        (0x00000000000000000000000000000001, 0x7ffeffffffffffffffffffffffffffff),
        (0x80000000000000000000000000000001, 0x3fff0000000000000000000000000000),
        (0x80000000000000000000000000000001, 0x40000000000000000000000000000000),
        (0x80000000000000000000000000000001, 0x40008000000000000000000000000000),
        (0x80000000000000000000000000000001, 0x7ffeffffffffffffffffffffffffffff),
        (0x00000000000000000000000000000001, 0x40010000000000000000000000000000),
    ],
    "fp256": [
        (0x3ffff00000000000000000000000000000000000000000000000000000000000, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0xbffff00000000000000000000000000000000000000000000000000000000000, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0x4000000000000000000000000000000000000000000000000000000000000000, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0xc000000000000000000000000000000000000000000000000000000000000000, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0x4000080000000000000000000000000000000000000000000000000000000000, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0xc000080000000000000000000000000000000000000000000000000000000000, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0x0000000000000000000000000000000000000000000000000000000000000001, 0x3ffff00000000000000000000000000000000000000000000000000000000000),
        (0x0000000000000000000000000000000000000000000000000000000000000001, 0x4000000000000000000000000000000000000000000000000000000000000000),
        (0x0000000000000000000000000000000000000000000000000000000000000001, 0x4000080000000000000000000000000000000000000000000000000000000000),
        (0x0000000000000000000000000000000000000000000000000000000000000001, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0x8000000000000000000000000000000000000000000000000000000000000001, 0x3ffff00000000000000000000000000000000000000000000000000000000000),
        (0x8000000000000000000000000000000000000000000000000000000000000001, 0x4000000000000000000000000000000000000000000000000000000000000000),
        (0x8000000000000000000000000000000000000000000000000000000000000001, 0x4000080000000000000000000000000000000000000000000000000000000000),
        (0x8000000000000000000000000000000000000000000000000000000000000001, 0x7fffefffffffffffffffffffffffffffffffffffffffffffffffffffffffffff),
        (0x0000000000000000000000000000000000000000000000000000000000000001, 0x4000100000000000000000000000000000000000000000000000000000000000),
        (0x918fbda43c5a4b270a285a9556e17dc0bf3a81c6ea50feab2655f3694a08c0c6, 0x6b534a7de4c672455e548a58e33511ba7c8fd8604b21620b3b893d99e27e1d5e),
        (0x19c18c5a2b244beb010e322159f0b179f1767ef6b758b116f9150ad40909841e, 0x696ed8c7ee308ad1fbca6a8f36018c0616dd7a6b35c08b7cd42ed5e67d9094ea),
        (0x0731ff8d53fa6a78c64949e4a4cf68c5076f5dcae8e58143108fad0dd30b504d, 0x4c279859a196e3fa060f3ee314d0ba32decdabddb4c740477348b2bf5b881dab),
        (0x01b3d6d7a15ed7aa39e674654e40bc4900e096338377ceec2fd964815bafe946, 0x425f988d4b52c850646a6fdae869f15150e1170ffd4f0541ddb27f86004f23c3),
    ],
}


INV_POOL_MARKS = INV_POOL_MARKS + tuple(
    ("atan2", name, sf.RND_NAMES[rnd], lane, "the tiny-quotient range")
    for name, lanes in _TQR_MARKED.items() for rnd in RND_MODES
    for lane in lanes)


# ---- the structured lanes: pairs that must mark (the study's 3.5) -------------------------
#
# Each lane a pair (y, x), each also with y's sign flipped (structured_lanes):
# the windows next to pi, atan2(y, -1), at a grid point (rtz, rdn, rup) and a
# midpoint (rne, rmm) with the neighbour on either side (the centres are
# census.py's, fp64 0x3ca1a62633145c07 and 0x3cb8d313198a2e03, and the
# fp128/fp256 pairs in census.*-near.out.txt); at fp64 atan2(3 2^-26, 1), where
# atan(t) sits within the bound of the midpoint under rne and rmm; (2^-60,
# 1 + ulp), the quotient beside a grid point (a hair below the grid point,
# directed); and atan2(2^-(p+10), 1 + j ulp) at the last j that marks at fp64
# (11: the threshold j < 2^((p - G - 2)/2) = 11.3) and at j = 40 at fp128 and
# fp256, where every j of the census's 40 marks.

STRUCT["atan2"] = {
    "fp64": [
        # atan2(3 2^-26, 1): atan's tiny family through an exact quotient, the midpoint under rne and rmm
        (_NEAREST, [
            (0x3e68000000000000, 0x3ff0000000000000),
        ]),
        # the window next to pi, a grid point, with its neighbours
        (_DIRECTED, [
            (0x3ca1a62633145c06, 0xbff0000000000000),
            (0x3ca1a62633145c07, 0xbff0000000000000),
            (0x3ca1a62633145c08, 0xbff0000000000000),
        ]),
        # the window next to pi, a midpoint, with its neighbours
        (_NEAREST, [
            (0x3cb8d313198a2e02, 0xbff0000000000000),
            (0x3cb8d313198a2e03, 0xbff0000000000000),
            (0x3cb8d313198a2e04, 0xbff0000000000000),
        ]),
        # (2^-60, 1 + ulp): the quotient within the bound of a grid point
        (_DIRECTED, [
            (0x3c30000000000000, 0x3ff0000000000001),
        ]),
        # (2^-(p+10), 1 + 11 ulp): the last j that marks
        (_DIRECTED, [
            (0x3c00000000000000, 0x3ff000000000000b),
        ]),
    ],
    "fp128": [
        # the window next to pi, a grid point, with its neighbours
        (_DIRECTED, [
            (0x3f8dcd129024e088a67cc74020bbea63, 0xbfff0000000000000000000000000000),
            (0x3f8dcd129024e088a67cc74020bbea64, 0xbfff0000000000000000000000000000),
            (0x3f8dcd129024e088a67cc74020bbea65, 0xbfff0000000000000000000000000000),
        ]),
        # the window next to pi, a midpoint, with its neighbours
        (_NEAREST, [
            (0x3f8f7344a4093822299f31d0082efa98, 0xbfff0000000000000000000000000000),
            (0x3f8f7344a4093822299f31d0082efa99, 0xbfff0000000000000000000000000000),
            (0x3f8f7344a4093822299f31d0082efa9a, 0xbfff0000000000000000000000000000),
        ]),
        # (2^-(p+10), 1 + 40 ulp)
        (_DIRECTED, [
            (0x3f840000000000000000000000000000, 0x3fff0000000000000000000000000028),
        ]),
    ],
    "fp256": [
        # the window next to pi, a grid point, with its neighbours
        (_DIRECTED, [
            (0x3ff12cd9128a5043cc71a026ef7ca8cd9e69d218d98158536f92f8a1ba7f09aa, 0xbffff00000000000000000000000000000000000000000000000000000000000),
            (0x3ff12cd9128a5043cc71a026ef7ca8cd9e69d218d98158536f92f8a1ba7f09ab, 0xbffff00000000000000000000000000000000000000000000000000000000000),
            (0x3ff12cd9128a5043cc71a026ef7ca8cd9e69d218d98158536f92f8a1ba7f09ac, 0xbffff00000000000000000000000000000000000000000000000000000000000),
        ]),
        # the window next to pi, a midpoint, with its neighbours
        (_NEAREST, [
            (0x3ff13e6c89452821e638d01377be5466cf34e90c6cc0ac29b7c97c50dd3f84d5, 0xbffff00000000000000000000000000000000000000000000000000000000000),
            (0x3ff13e6c89452821e638d01377be5466cf34e90c6cc0ac29b7c97c50dd3f84d6, 0xbffff00000000000000000000000000000000000000000000000000000000000),
            (0x3ff13e6c89452821e638d01377be5466cf34e90c6cc0ac29b7c97c50dd3f84d7, 0xbffff00000000000000000000000000000000000000000000000000000000000),
        ]),
        # (2^-(p+10), 1 + 40 ulp)
        (_DIRECTED, [
            (0x3ff0800000000000000000000000000000000000000000000000000000000000, 0x3ffff00000000000000000000000000000000000000000000000000000000028),
        ]),
    ],
}


# The marked lanes whose guess differs from transcend.py's (STRUCT_GUESS_WRONG's
# meaning, atan2's rows): MEASURED on the fragment, a pin of what it does and
# not a claim that it is right. A marked lane's guess is not promised right (the
# replay decides it), and where the true value is within the bound of a grid
# point or a midpoint it may fall either side. The grid centre at fp64, fp128
# under the directed three; the midpoint centre at fp128 under rne and rmm.
STRUCT_GUESS_WRONG.update({
    ("atan2", "fp64", RTZ): {
        (0x3ca1a62633145c07, 0xbff0000000000000),
        (0xbca1a62633145c07, 0xbff0000000000000),
    },
    ("atan2", "fp64", RDN): {
        (0x3ca1a62633145c07, 0xbff0000000000000),
        (0xbca1a62633145c07, 0xbff0000000000000),
    },
    ("atan2", "fp64", RUP): {
        (0x3ca1a62633145c07, 0xbff0000000000000),
        (0xbca1a62633145c07, 0xbff0000000000000),
    },
    ("atan2", "fp128", RNE): {
        (0x3f8f7344a4093822299f31d0082efa99, 0xbfff0000000000000000000000000000),
        (0xbf8f7344a4093822299f31d0082efa99, 0xbfff0000000000000000000000000000),
    },
    ("atan2", "fp128", RTZ): {
        (0x3f8dcd129024e088a67cc74020bbea64, 0xbfff0000000000000000000000000000),
        (0xbf8dcd129024e088a67cc74020bbea64, 0xbfff0000000000000000000000000000),
    },
    ("atan2", "fp128", RDN): {
        (0x3f8dcd129024e088a67cc74020bbea64, 0xbfff0000000000000000000000000000),
        (0xbf8dcd129024e088a67cc74020bbea64, 0xbfff0000000000000000000000000000),
    },
    ("atan2", "fp128", RUP): {
        (0x3f8dcd129024e088a67cc74020bbea64, 0xbfff0000000000000000000000000000),
        (0xbf8dcd129024e088a67cc74020bbea64, 0xbfff0000000000000000000000000000),
    },
    ("atan2", "fp128", RMM): {
        (0x3f8f7344a4093822299f31d0082efa99, 0xbfff0000000000000000000000000000),
        (0xbf8f7344a4093822299f31d0082efa99, 0xbfff0000000000000000000000000000),
    },
})



# ---- the exact-rational predicate of the tiny-quotient range ------------------------

def _tqr(fmt):
    """2^(emin+p+2): the range's edge in t~ = n_h RECIP_SEED(d_h)."""
    return Fraction(2) ** (fmt.emin + fmt.prec + 2)


def _tq_shape(fmt, lane):
    """t = |y / x|, an exact Fraction, for a lane of the range's shape (y and x
    finite, y not zero, x > 0, |y| < x); None for any other."""
    y, x = lane
    if not (_finite(fmt, y) and _finite(fmt, x)) or x & fmt.sign_mask:
        return None
    t = abs(value(fmt, y)) / value(fmt, x)
    return t if t < 1 else None


def _tq_band(fmt):
    """(lo, hi): the range's edge in t = |y/x| is not exact, the test being on
    t~ = t (1 +- e) with the seed's error e at most INV_EPS_T (mathlib), so a
    lane with t under lo is inside whatever the seed does, one at or past hi is
    outside, and one between may sit either side."""
    edge = _tqr(fmt)
    return edge * (1 - ml.INV_EPS_T), edge / (1 - ml.INV_EPS_T)


def check_pool_marks(fmt, lanes=None, listed=None):
    """[finding], band: pools. The committed tiny-quotient marks
    (_TQR_MARKED, the same set under all five attributes) against an
    independent predicate in exact rationals: each listed lane has the range's
    shape and t under the band's top; each pool lane of that shape with t under
    the band's bottom is listed. band: the lanes of the pool of that shape in
    the band between (a seed's error either side of the edge)."""
    lanes = pool("atan2", fmt) if lanes is None else lanes
    listed = _TQR_MARKED[fmt.name] if listed is None else listed
    lo, hi = _tq_band(fmt)
    out, band = [], []
    where = f"pools: atan2 {fmt.name}"
    bad = [x for x in listed
           if (t := _tq_shape(fmt, x)) is None or t >= hi]
    if bad:
        out.append(f"{where}: {len(bad)} of the {len(listed)} committed range "
                   f"marks are not of the range's shape or are past the band "
                   f"in exact rationals, first {_hexes(bad)}")
    have = set(listed)
    missing = []
    for x in lanes:
        t = _tq_shape(fmt, x)
        if t is None:
            continue
        if t < lo and x not in have:
            missing.append(x)
        elif lo <= t < hi:
            band.append(x)
    if missing:
        out.append(f"{where}: {len(missing)} pool lanes are inside the range "
                   f"in exact rationals and not on the committed list, first "
                   f"{_hexes(missing)}")
    return out, band


# ---- the range lanes: marked, their guesses counted -----------------------------------

def check_range(f, rows=None, edge=None, evaluator=None):
    """[finding], tally: range. Each committed range lane (RANGE_ROWS, or
    `rows`, [(label, lane)]) marked by the fragment, its guess COUNTED and not
    compared (a marked lane's guess is not promised: the replay decides it),
    and in the range in exact rationals (_tq_shape, under the band's top). The
    edge (RANGE_EDGE, or `edge`, the last y that marks against x = 1) is held
    to RECIP_SEED(1) = softfloat's seed of 1 in exact rationals: y_last times
    the seed rounds below 2^(emin+p+2) and (y_last + 1) times it does not, and
    atan2(y_last + 1, 1) is not marked. tally: lanes, marked, guess_right."""
    fmt, rnd = f.fmt, f.rnd
    ev = evaluator or ml.evaluate
    rows = RANGE_ROWS[fmt.name] if rows is None else rows
    where = f"range: atan2 {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    tally = {"lanes": 0, "marked": 0, "guess_right": 0}
    unmarked, outside = [], []
    lo, hi = _tq_band(fmt)
    for label, lane in rows:
        tally["lanes"] += 1
        bits, fw = ev(f, lane)
        if fw & MARK:
            tally["marked"] += 1
            if (bits, fw & 0x1F) == golden(fmt, rnd, lane, "atan2"):
                tally["guess_right"] += 1
        else:
            unmarked.append(lane)
        t = _tq_shape(fmt, lane)
        if t is None or t >= hi:
            outside.append(lane)
    if unmarked:
        out.append(f"{where}: {len(unmarked)} of the {len(rows)} committed "
                   f"range lanes are not marked, first {_hexes(unmarked)}")
    if outside:
        out.append(f"{where}: {len(outside)} committed range lanes are not in "
                   f"the range in exact rationals, first {_hexes(outside)}")
    # the edge, in exact rationals (the seed of 1 from softfloat, the product
    # rounded to nearest: marked iff it rounds below 2^(emin+p+2))
    one = sf.one_bits(fmt)
    last = RANGE_EDGE[fmt.name] if edge is None else edge
    seed = value(fmt, sf.recip_seed(fmt, one)[0])
    limit = _tqr(fmt) * (1 - Fraction(1, 2 ** (fmt.prec + 1)))
    if not value(fmt, last) * seed < limit:
        out.append(f"{where}: the edge lane {_hexes([last])} times the seed of "
                   f"1 is not under 2^(emin+p+2) in exact rationals")
    if value(fmt, last + 1) * seed < limit:
        out.append(f"{where}: the lane past the edge {_hexes([last + 1])} "
                   f"times the seed of 1 is still under 2^(emin+p+2)")
    if ev(f, (last + 1, one))[1] & MARK:
        out.append(f"{where}: the lane past the edge ({_hexes([last + 1])}, 1)"
                   f" is marked")
    return out, tally


# ---- the corner: a committed set, and the check no pool reaches --------------------------

# The corner lanes (the study's 3.6, item 9: send-back 1): a tiny |y| against a
# larger |x|, where the first prescale (keyed on d) left an inexact remainder
# and the answer wrong and unmarked by up to 2^44.76 of the bound. Drawn once
# from the sampler's region `tinyn` (100 lanes at fp64, seed 17, plants.py's;
# 40 at fp128 and fp256, seed 17) with verifier-VM4S's lane appended at fp64
# (the other named lane, 0x812d63ff0271ce60 against 0x3c3053b19c7200ec, is
# drawn). No pool reaches them; the plant prescale_d is red here alone.

CORNER = {
    "fp64": [
        (0x812d63ff0271ce60, 0x3c3053b19c7200ec),
        (0x024fd0b90fa10a95, 0x3bc23924341ae014),
        (0x8214cb9c53e30b21, 0x07cc39f8e72deac6),
        (0x05399837e4ae41ad, 0x40e9b8664db08590),
        (0x85b49184acbe432b, 0x17545e7a2c7e2db6),
        (0x03e18fdb8cfe510f, 0x3fa17047072f5266),
        (0x000000000000104b, 0x371dd1b5a9cbe108),
        (0x95cbc140ec907fe7, 0x8000000000000046),
        (0x82b261faf9d2ce6d, 0x2a96e542e8a8ae01),
        (0x8000000000000f37, 0x9c4fdaaca4e98c88),
        (0x897ed3980a4c24b2, 0x439fdc407452c157),
        (0x0162865c5e10d2fd, 0x11ad3ec45e94dce2),
        (0x80b07bbbf9a38ae6, 0x1e1a30ca4aca9364),
        (0x80000e6d70419f29, 0x2f08ca2b4f1a9f08),
        (0x87fb73d0b7de92b5, 0x1b131db19dad9e0f),
        (0x800000000000002e, 0x06b26dafae963070),
        (0x8000001d1124de2e, 0x20c6dc5d08de9882),
        (0x8831a78989f2f6f5, 0x41cb9ad7b4b171d6),
        (0x01d1a2412ad9b6cd, 0x3bf60110d1e2f300),
        (0x800000ed9a2b0e34, 0x3b14369a5b8323f1),
        (0x00980b043af443d3, 0x90a6c32a812185ae),
        (0x899f5f97dccdaef6, 0x3c0c603617704835),
        (0x89822eb9f3c245da, 0x97366da5d34b5b08),
        (0x09dae7e06c975e26, 0x34b118b48a55e658),
        (0x82b6fdffc2ce3747, 0x1ce9557bc17465b6),
        (0x04ab9b9b5c7cefe6, 0x6e9b6ee8b67fc5a5),
        (0x85fde40b10f10c5f, 0x4217fe0f050ccd42),
        (0x800000135a276346, 0x2c1ae9b94d17db9c),
        (0x0000042c5870b1c2, 0x1520981941aaee65),
        (0x80000000804da188, 0x1241ecc63db1545b),
        (0x0a4db5cb44bd817b, 0x3337ef18b1f6e860),
        (0x80000000000003de, 0x3524ab1fff67ff11),
        (0x07a4a85cfe178dee, 0x41503c62982046c0),
        (0x800056bbcaa7dbb2, 0x197b95dd222e19d0),
        (0x0339893cb9f32e7c, 0x282744dfe0cd6c5c),
        (0x04e31a5ffd3200ad, 0x2ac5b8cd3498bf9a),
        (0x8471bcf6a4233bae, 0x0a3e8e9a885c5a15),
        (0x0a54a422272033dd, 0x84deec078ac4f00d),
        (0x00e8038915296729, 0x2cf4a8cb260af81a),
        (0x800000000000024c, 0xb3688d0f8c45dbd1),
        (0x876c7f5cd8d7c764, 0x3abda3ed2bed59c4),
        (0x04ab695908b20b84, 0x3dcdf626f21c1aaf),
        (0x0300e4269bd40613, 0xa5e9dd5d8d12647e),
        (0x1d23a1603e431700, 0x83c45d1fcab3aa57),
        (0x00037c5c5b913959, 0x38eb498cc84ad81d),
        (0x074a4a3ebb2c4cd3, 0x41bfb39e638fc373),
        (0x83b595bc20632552, 0x2bb4b2e9e2a5bfda),
        (0x89b8d12265982326, 0x0596f67339b73d12),
        (0x88f86671f68e86ed, 0xaf53c080a85373f0),
        (0x82d7a121b8b0d632, 0x0bc8bd992259cce9),
        (0x0718e08c1cd886dc, 0x4171da545b1ddf19),
        (0x899896d9007fb69e, 0x0d81891b28c6d9c3),
        (0x0711a6c2ab895095, 0x37f3d6c0881b327f),
        (0x03e1391d08b7825d, 0x25c20fee46e6544f),
        (0x84fba7fb8dc4140f, 0x2e3689130ff49aac),
        (0x01ccdd4c9ef38d6e, 0x3d4ee82700bd8d34),
        (0x80000001a2ac8ca8, 0x3b36a9a54cd6ad7f),
        (0x812248f23a5455b7, 0x3cd82cf02441f637),
        (0x0000000000000026, 0x3629121bdbac4ce6),
        (0x05eb7905d5961b9d, 0x0626304835c9b5e1),
        (0x86889655bf4de908, 0x41f9bba5d830ef88),
        (0xabc9305b16c32ac2, 0x07d7f1a09948eede),
        (0x826591c77c950713, 0x08bdc2ffe7b17378),
        (0x0226fa39e5a47137, 0x998cbbd0b230e348),
        (0x02b7544df8650c4d, 0x191cf6e17e0b40c4),
        (0x07d62f2970d0d6ab, 0x33323f8230ca8bf6),
        (0x03d62976e44baa13, 0x84631c993eda251f),
        (0x829d50cece082dc7, 0x67de6dd01a1102aa),
        (0x029f811742883d49, 0x2413276e4304fe93),
        (0x0000000000000001, 0x3ca7f86a331dd1dd),
        (0x0000000000000006, 0x0b25dbdd32cd52f4),
        (0x09188769f5334efd, 0xa773e1c161edb228),
        (0x0177d4d029d1dd54, 0x105f0bc7aa855985),
        (0x800000009415c95d, 0x3210a002e69eebd8),
        (0x0000000000007d95, 0x04e1b2235f5d6aea),
        (0x01a8be91b8445948, 0x367611fbc0fbb3f7),
        (0x0127e24fdc5649ca, 0x0a560d0bb1a11a7e),
        (0x3d84f0029c07130a, 0x8a4a8046b94cc212),
        (0x309308eb29d4b17f, 0x000000270f6e1247),
        (0x8291633d657d7278, 0x0e99bb55af98b326),
        (0x00000000000095f6, 0xab2740bc09c59de9),
        (0x0000000000000017, 0x3620ce0875d81fdd),
        (0x01bb5a2dd95e4dc2, 0x25bae6166ec327a2),
        (0x09edc936c9f11c68, 0x282f5db1299957ee),
        (0x00a0896f32be8b4c, 0xaeb76b78f7534178),
        (0x06abe4f4be2d6b29, 0x2efd4b405fda8b11),
        (0x8205b514a3ae7506, 0xb01230029cac65a1),
        (0x0919401c9102b27b, 0x4448f4c6e8b44132),
        (0x077a5e75bc576da2, 0x41242e2085f89702),
        (0x02af6ee01d782d86, 0xb8b81e4a2916a7ab),
        (0x078a2d9d9a16a118, 0x1ff96420e68b042f),
        (0x26ed9678a576329e, 0x008a3f7c49f80f97),
        (0x84b1b390aeff3b45, 0x1d2c350029bab6fa),
        (0x0000000092e8bf6d, 0x211ef795fb3f4088),
        (0x0081cd8ba309dedc, 0x3c8a2b26ca3fb24e),
        (0x0000000176a87d5c, 0x18d39d845d4d6e52),
        (0x0a0b5189cfef0f2a, 0x0cd926bf3ef9325d),
        (0x8072a8be87ba6da4, 0x3a2f150db5e478e3),
        (0x0912aa6fcd685a51, 0x0bc630680a97d3b3),
        (0x8082e3e710be0dba, 0x3a1679ef8c683a93),
        (0x003871ec348e50c8, 0x2b8d56babd2a3847),
    ],
    "fp128": [
        (0x00835f204475d5077974d3833536618e, 0x3fdd779dfeebd76c3d8694645d90f91b),
        (0x80ac11542bd08f6438377529e42791dc, 0x08e24bb6555462e872370d016b6ccdbd),
        (0x80ed4e97c5e2dbc9816fadb7edae5e22, 0x402c6865415560e896fecdda2f2e391f),
        (0x80e8d835e765c40af35f052b4c5615ff, 0x387bc686f996b032eeed9e49a3637e48),
        (0x8156fb1988727699e7787f78c3dbe746, 0x4087ab566be5000689cb28f82a2afef7),
        (0x014430a5081d1ce8913735606cdd03ff, 0x985260962193a8091d134f09d34ad3b9),
        (0x80437f2afacdc920a284075e3e11b1ca, 0x10b4121dea2685e00c824decb7dc2dea),
        (0x80236c9b759c781f88b36ecb04b58bcf, 0x3fadb677e3e60cff3802e43ac24420df),
        (0x8000000000000000000000405371d9f4, 0xa660ff68799782af0768ee0f2c25be4d),
        (0x002be95044696e3a5ab3bf13ae566e93, 0x3f7833015dbf609264034f47a69fde12),
        (0x8099bc1696921239f8ed731929d40dfe, 0x3fe90c1c0063402b1c5ac58e4bfde004),
        (0x00a06305cb52fefe0d348bd818e74c68, 0x3ff8f45f21288e365054f5dced662bb1),
        (0x800000000000000000004bc334c3272b, 0x2511db10573e0cac78965c580ef49698),
        (0x00dc28ef5ed7ebb33639f2a337b98a06, 0x19eccce9936604341a3ad3be01b72b83),
        (0x00c23bca631b24c8c6d367a8c335f3ae, 0x3b8b51416f6b213a905d14030ef7da53),
        (0x807e9766008cb3efe0132706aa2ccfb8, 0x3f9f5e4c54b2eec18ef55ee3e88664d3),
        (0x00000000000000000000000002a54dff, 0xbf261c98dc13ede5bc5cdd8cc02b8fe0),
        (0x0096c70773527709e1ab9a68dee968e2, 0x639bb3f007752b01c7e3fe9b87d5a9d2),
        (0x0093c80bacb13409ff33df8a0eec2b4a, 0x1f7164f7940a43c68248e5de3d089f71),
        (0x00f008134ae256a60f16fdf62f3be7e3, 0x2b2bac168db14433d3470e755cfa7e6a),
        (0x8000000000000000000000d20d4b5f4a, 0x2f3deee6ecc8668f1fe054136c0ae631),
        (0x8000000000000000000067f17feae28b, 0x240dde2383e312997bcff436b3e512fe),
        (0x80698cd6f00472c775d8f00cba3cc120, 0x3fed00dc78932e3b3798fe13e5ffcdd3),
        (0x8076d671b785bd28d66ab976abc72ac1, 0x13d0cb83a277d1e6acbd4fdfe43aeb27),
        (0x80460d9aa9f7a7f26d97378deb04c8bd, 0x3fd0dbcd502c406fec26af006c5623d7),
        (0x80629cb7ea54f8da0a78751f635e3802, 0x3f92e9e2530a9e5199c598a333fc88c8),
        (0x0038a3b0a9b3858e4b928d85635a496e, 0xa914fd59fcc685771f8a3660ff3bdd57),
        (0x8087d06a4df3e7d13b2d33f1bfdae548, 0x3feca6bed64776402a81642e1fe787de),
        (0x0138ffed8d2cdc5f5d9ad9088994ca8b, 0x2869bb3be91352691cd1476cb1341da7),
        (0x0000000000000000000000000001e71a, 0x3eccb2303c3fbcf06c7f03c394796cdd),
        (0x00000000000000000000000000000005, 0x3329d5509ffa3e6e5616e096ac3d449b),
        (0x0000000000000000000000000000000a, 0x3eacb510b4d7fad61d81f2ffd97dbd6a),
        (0x04ee457200d5180d2c9fbed2433b32a5, 0x00000000000018098e77a3a5b34f6cfc),
        (0x001847b63d420c6d4d78cb66fcdb4d8c, 0x3cc59f8803a1b81cfbc23b542d742563),
        (0x812edb52f5a8a3535d3636897e052e04, 0x1cbd802e1efcd85cb8a1ec2977976651),
        (0x801ee147354574db7a3ca419859d091e, 0x0b0925f658ee3c97af452eb49b465f71),
        (0x0000000000000e2455583be4a08c1b0b, 0x35e13d8006317f9ca757adea4a7f5f09),
        (0x00ff1a85793db723ad73ea2f1ba83dd6, 0x4060c134ef7ef64edde4459d646b38a9),
        (0x00a27769a87f86b0ca3e15d0469bf5d3, 0x095346e44643d045bd237fbced7b411d),
        (0x0067332c7644a14f71671043bcc897ff, 0x2ba54501e7bc8e84aff8072c36002cff),
    ],
    "fp256": [
        (0x0004fdbc7d4a4e30b7b6e32c26d94929040de0f760d07e5f38ded4283e5fdc09, 0x5ac3baa80a6ebefc6e48eba730d7a0024630ac86fd4162e1b8a06011486ada66),
        (0x80209efd2eff40b73bce053a1b17856c4e5669d9b1e9855d70e285bdbc7e6fb1, 0x0402acc33b3630d2571627eaefd79df37f03b481eaa7a18a172dc24c8c501892),
        (0x800536f94fc7672cc28799b982f3afcfc95b74c444fa382e0d2746d579b52072, 0x1caaab9e12153f1090d2822c76f07818d8a39c5956bc75a00585f99decb1a512),
        (0x2855b9d06540e80e9604e64f436ce83fdfc8af0cb693b05611584d735bcd4400, 0x800c0352e2078f095cbbcb4b973ed929da208fe1bb86bb5373f107a714fcc356),
        (0x80076717da17c0975c0b165ddb63e82a9b36aaa783c469f4c28f1e8aaeeab8fa, 0x3ff034c043109015b11a45a8876f70d6597a691348baefd37b92005913b2220f),
        (0x80000000000000000000000000000000000000000000000000000000000001f9, 0x19fb3d3edc9911adff2ad13b99e6eb0ab2f51cd8bfbbe46d68220be4bff9acb1),
        (0x8000000000000061be58974e535e69a1704d1d8081b6e2fc9764824f2d9ad6f5, 0xa9eca3712f907b271e70b6a2672a0a8bb7ebdfcd619bec358b4adc215e65338c),
        (0x800058270616b60f6ee4f5234121606512823e65d61cb6d19c9a6334fe278e43, 0xb2406f691077e7f3eae68423b9e216adc80e5c66d3aaf7e4a91d53f1ad191368),
        (0x80000000075defbb92b86ba198bb29e39a652411821f1dc9849f07fa5de7bf1b, 0x067f65f2ca4b652d154ca146d73ba3fcddd5f0c5790dd1253403ffd23fd05b3f),
        (0x8011d48a6750afdaa9bcc44d284df3137252c3cae66a7159a7ae3a9af443dbff, 0x028fd7c4abefca70c2f4b533e55f7f7e3c5a0fba05846526abfdb587d495118f),
        (0x000c63591bc60c7fea1b87c2cc07c6fa4686b6d8903b12727067352373e475d6, 0x3ffbe488e5be226a1ec24c41a55dba349fd0384d2fc258172e1a8c5c5156d6f4),
        (0x800000000d38fc7a93d8a98a31df4b3d72db6c5baa969d2e6d567d47e117a6f6, 0x3fee34b1409277bd0625c8c7eeb902985462a25e9cea497838dc667bd7bf0642),
        (0x00081b98dc26f8ef69a8ba534f6447e0457c720c3255a682c86ab65f495ffac6, 0x3feee25f4282cf7f46685713a5f0c6e2c09a5cbde5e0c799232bd7ae2d12010f),
        (0x801b2fd58fa8d8d735eef762dc220003de524d59fa26477985357f981c310b45, 0x08f023b5fd70d2b1808f2481109a8462819f56ef81e6c1598c6faa0826ad1e1c),
        (0x8024c87963df9b64e144c64e169baf0325244a271a27f9a827bcbffcf7c5b410, 0x31d144bd8e3c1c7462d5e5c18ac5288a051520947b016ca77e2d58a4b71e82b1),
        (0x001537607490a0fdc6df8a2c454b0afe0057e11f2fa5d182edf31c400b5cfba3, 0x3ff7839d2ce04a6bc9fba0a9280047eefa51d557caa734bc8669846a2f4bf9b6),
        (0x00187b35db36619f5513fb8b736bfd94a6883e14bb0e34b5ad86f901ae153397, 0x7d61eac8c956b62b36fd530c6ebb8da2de2cbc424b64668f1fe8520a05a71691),
        (0x80248873ab3a896d3031597b5415ddaed5ba17a409d20ea13935b35509b68b9d, 0x314f64243828ef469713a26e66bbd9b6ecf5abf2c04df167dc3b161b602785f0),
        (0x210230c5b776865c77896d11076c6d6ff2c3822a478658fe5854e18a8e37303b, 0x801f7ef55cffa90b7530bcc587bb5b18b09a498f9e01eefb994d84cbf87bcf03),
        (0x802c622f766930181ac7cec4ec1ce9b1972c0e4062ad94947caf2d9b326d189d, 0x400f48063a81f26aeaf14aedd10aa0e99e85c5ba2de5fbf362ce43d21596c166),
        (0x899de047020e29d9da37cfda2028378d380321da81458a566042af3f39b5c0cf, 0x0000000000000000000000000000000000000000000000000000000000000003),
        (0x0000000000013ed71d21392a6e5c28ace439d212940e668d0defc78660aa877b, 0x1499e7e2993fe17ea11ca1ff39ab313042651f92808c872fcec2f54cd5470abd),
        (0x80000000000000000000000000000000000000000000000000138b53303a1d3e, 0x149ba01969f31f2acbbd320dd9bf97dbd7b7150c7d25c728dac2caea6c47a166),
        (0x802875cfb19773242994962307382e5436180d864c7344a28274321b342bd732, 0x3126ed0bd1ed50fc1bf7e7d08c08faf9f93772e8fc176c86c72ce03691d78c58),
        (0x8000000000000000000000006f54f9fbbbdccdedf1f43f1f0bc34574673b5a14, 0x2101261af82f2cb7b95a21a5d895ca2e04ba032d512f507f279060bf5c3fa39e),
        (0x801b9f5a4cc2635832e0f9fa32cdd0a2b4d742223ae7bcb7832d0f067197531e, 0x2c82be19b63242c472f3ac3e1fd417288e6a3c2e0543a326754af3abd8a110f6),
        (0x802bf0272ce2ea3354a1e55c40406c56819d48d6aa9f28f83d91f644379c6597, 0x26b943daa00293bfbbb3216217bfc8776de3e8e9374bafc5a2bf8d275cf6adbe),
        (0x000e4c1878fc921217634655dcb7a42057d70d9564683283704d10366df4a8a7, 0x64191624ced2d3c7f598639b8a5a122975688ef51b2ece68051364a5d8f324c5),
        (0x802bc8d2f8c3a896071fdc22b7551c2fcc9627bc8af8bb77c20a5628a9e5d8af, 0x105f835224bbd769bbd298cda7250a919a730fe525fd328d53c60ce7aed076a1),
        (0x800000000000000000000000000000000000000000000000000000000000577e, 0x3fdf72182f842a90ad708797b7acc117946ffab82f03d0760405caa278b8e74f),
        (0x90cdb571bd0cb472d894ab86967517012e47dc4ebbe51087aaa3657a198cfdc8, 0x0016e45ec7fcdaf5d2f9c89e1f0d35a6463aceb498a1f72f8ec9cf2f72f3bba9),
        (0x000000000000000000027e8e3cdbf3ec9cad2f3f1762c79bd8165e5f28204d37, 0x0e09547fd394ecb95fbdbb522e1dc72eea86760209dc8e67c9d1adda9a33723b),
        (0x002125620f8d6e45908b3acbf31d739e366179fa916c2736dff11ba7e4f45b73, 0x40067d5c3725dc7af0ba21576b67a1fe553fda9dd5dc35b1512744e0ce1a4f58),
        (0x8003cb36fe6d39f898f6769d9232c6e864e4e644a4e517e3b557485dec9c5ad2, 0xaa1ed0669a255155b8f552be045d4d31953504366d926e366a2782f764a95109),
        (0x0005acfe3f3f22ed72c07ada53eada91c66f8526fe5db3329fa11d99f7972aac, 0x37d99b4cb7159fb5fb3e184fbad03b89f8d095be7cf1c0ae0cab1fe427762629),
        (0x869ab18cde8e465000808d6f2c5e9bd7f79c6b2bb6066a4b5d43bf81a91d151d, 0x001954bb5bfcf0d54e4cbf39ed7def54fefabf67bdc2037385c8f05ee8bbd502),
        (0x000b73d45de423a8bd4489c77efa0a453c489dc83445e02010fe59b44177da06, 0x0153a888273a712930a61697031445005157ea47f88479abd2250462a02f0ed3),
        (0x00000000000000000000000000000000000000000012fbbd3c2b251a2a03b3b8, 0x51473509e70468c3d85e2b76dfdda232612e69c01a82725a7c1cfbc797402218),
        (0x8000000000000000000000000000000000000000000002a4ca795d0e37fadff0, 0x2a0fbbe8c2b8f82eb104385ec74017f7d406d501557c3bd13ee4ef433063bcd2),
        (0x80010a2b70b00e92df03111128bbee11f8dd2d2d921dac8a4074030ddaa350a8, 0x28b049ceffd71d161fbe644e104d4787c08aa8bd648a5e03ebdbff33817a42e8),
    ],
}



def _exp2_floor(q):
    """floor(log2 q) of a positive Fraction, exactly."""
    e = q.numerator.bit_length() - q.denominator.bit_length()
    return e - 1 if Fraction(2) ** e > q else e


def corner_region(fmt, lane):
    """Whether the lane is in the region `tinyn` samples (m4measure.py:139):
    the smaller operand's exponent from emin - p + 1 (the least subnormal) to
    emin + 3p + 4, both operands finite and nonzero."""
    y, x = lane
    if not (_finite(fmt, y) and _finite(fmt, x)):
        return False
    e = _exp2_floor(min(abs(value(fmt, y)), abs(value(fmt, x))))
    return fmt.emin - fmt.prec + 1 <= e <= fmt.emin + 3 * fmt.prec + 4


def check_corner(f, lanes=None, b=None, evaluator=None, seq_evaluator=None,
                 region=True, seq=True):
    """[finding], tally: corner. The committed corner lanes (CORNER, or
    `lanes`) of the fragment's format through atan2, under the fragment's
    attribute: every lane in the region (corner_region); every unmarked lane
    equal to transcend.py in bits and flag word; under rne, every unmarked
    lane with y not zero and flag word exactly inexact within its bound
    (|V - f| / Bv under 1, mpmath at 4p + 200 bits) and with Bv not zero (a Bv
    that underflowed certified the lane with no margin: the study's 3.6, item
    10); and the same lanes on seq.py (routines.run(f, ys, xs)) equal to
    evaluate(). `b` is the Build of the same fragment, for V and Bv (the
    library's own by default: a planted fragment's caller hands its Build),
    `evaluator` and `seq_evaluator` stand for ml.evaluate and the seq run, for
    the tests that plant a fault in them. tally: lanes, marked, wrong, bv0,
    past, largest (log2 of the largest |V - f| / Bv over the lanes tested),
    differ (seq.py against evaluate)."""
    fmt, rnd = f.fmt, f.rnd
    lanes = CORNER[fmt.name] if lanes is None else lanes
    b = build_of("atan2", fmt, rnd) if b is None else b
    ev = evaluator or ml.evaluate
    where = f"corner: atan2 {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    tally = {"lanes": len(lanes), "marked": 0, "wrong": 0, "bv0": 0,
             "past": 0, "largest": -math.inf, "differ": 0}
    if region:
        off = [x for x in lanes if not corner_region(fmt, x)]
        if off:
            out.append(f"{where}: {len(off)} of the {len(lanes)} committed "
                       f"lanes are not in the region tinyn samples, first "
                       f"{_hexes(off)}")
    first = {}
    with mpmath.workprec(4 * fmt.prec + 200):
        for x in lanes:
            bits, fw = ev(f, x)
            if fw & MARK:
                tally["marked"] += 1
                continue
            if (bits, fw) != golden(fmt, rnd, x, "atan2"):
                tally["wrong"] += 1
                first.setdefault("wrong", (x, (bits, fw)))
                continue
            if rnd != RNE or fw != sf.FLAG_INEXACT \
                    or not x[0] & ~fmt.sign_mask:
                continue
            _r, _fl, pr = b.run(x, ("Vh", "Vl", "Bv"))
            Bv = abs(value(fmt, pr["Bv"]))
            if Bv == 0:
                tally["bv0"] += 1
                first.setdefault("bv0", x)
                continue
            V = value(fmt, pr["Vh"]) + value(fmt, pr["Vl"])
            err = abs(_mp(V) - true_value("atan2", fmt, x))
            r = -math.inf if err == 0 else float(
                mpmath.log(err / _mp(Bv), 2))
            tally["largest"] = max(tally["largest"], r)
            if r >= 0:
                tally["past"] += 1
                first.setdefault("past", (x, r))
    if tally["wrong"]:
        x, got = first["wrong"]
        want = golden(fmt, rnd, x, "atan2")
        out.append(f"{where}: {tally['wrong']} unmarked lanes differ from "
                   f"transcend.atan2, first {_hexes([x])}: got ({got[0]:#x}, "
                   f"{got[1]:#x}), want ({want[0]:#x}, {want[1]:#x})")
    if tally["bv0"]:
        out.append(f"{where}: {tally['bv0']} unmarked lanes have a Bv that "
                   f"underflowed to 0 (the test certified them with no "
                   f"margin), first {_hexes([first['bv0']])}")
    if tally["past"]:
        x, r = first["past"]
        out.append(f"{where}: {tally['past']} unmarked lanes are past the "
                   f"bound, first {_hexes([x])} at 2^{r:+.2f} of Bv")
    # the same lanes on seq.py: equal to evaluate() (seq=False leaves it out)
    differ = []
    if seq:
        outs, words = routines.run(f, *_split(lanes))
        got = list(zip(outs, words)) if seq_evaluator is None \
            else [seq_evaluator(f, x) for x in lanes]
        differ = [x for x, g in zip(lanes, got) if g != ml.evaluate(f, x)]
    tally["differ"] = len(differ)
    if differ:
        out.append(f"{where}: seq.py and evaluate() differ on {len(differ)} "
                   f"lanes, first {_hexes(differ)}")
    return out, tally


# ---- the audit through atan2's own fragment ------------------------------------------------

def check_audit_atan2(fmt, plant=None, lanes=None, b=None):
    """[finding], tally: audit. audit_lanes(fmt) (the study's own audit,
    plants.py :132 to :160) run as (y, x) = (n, d) through atan2's fragment,
    each lane sorted to n <= d first (as check_audit does): per lane with k >=
    1, n_h / P in [1/2, 2] and n_h - P equal to its exact value (probes nh, P,
    Nh0, Kk); per lane |th + tl - atan(n/d)| under 2^-(p+G) theta0 (probes th,
    tl, the builder's, after the forcing, which these lanes never meet), and
    the lane equal to transcend.py or marked. tally: lanes, premise, inexact,
    past, largest, wrong. check_audit cannot read this fragment (it takes
    build_inv_core's result and flags as th and tl)."""
    b = build_of("atan2", fmt, RNE, plant) if b is None else b
    p, G = fmt.prec, b.meta["G"]
    lanes = audit_lanes(fmt) if lanes is None else lanes
    magic = ml._enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    tally = {"lanes": 0, "premise": 0, "inexact": 0, "past": 0, "wrong": 0,
             "largest": -1e9}
    first = {}
    with mpmath.workprec(4 * p + 200):
        for n, d in lanes:
            if value(fmt, n) > value(fmt, d):
                n, d = d, n
            res, fw, pr = b.run((n, d), ("nh", "P", "Nh0", "Kk", "th", "tl"))
            tally["lanes"] += 1
            if not fw & MARK and (res, fw) != golden(fmt, b.rnd, (n, d),
                                                     "atan2"):
                tally["wrong"] += 1
                first.setdefault("wrong", (n, d))
            if pr["Kk"] != magic:
                nh, P_, N0 = (value(fmt, pr[k]) for k in ("nh", "P", "Nh0"))
                if P_ and not (Fraction(1, 2) <= nh / P_ <= 2):
                    tally["premise"] += 1
                    first.setdefault("premise", (n, d))
                if nh - P_ != N0:
                    tally["inexact"] += 1
                    first.setdefault("inexact", (n, d))
            theta = value(fmt, pr["th"]) + value(fmt, pr["tl"])
            true = mpmath.atan(_mp(value(fmt, n)) / _mp(value(fmt, d)))
            r = _bound_log2(theta, true, p, G)
            if r is not None:
                tally["largest"] = max(tally["largest"], r)
                if r > 0:
                    tally["past"] += 1
                    first.setdefault("past", (n, d))
    where = f"audit: atan2 {fmt.name}" + (f" plant {plant}" if plant else "")
    out = []
    if tally["premise"]:
        out.append(f"{where}: {tally['premise']} of {tally['lanes']} lanes "
                   f"have n_h / P outside [1/2, 2], first "
                   f"{_hexes([first['premise']], 1)}")
    if tally["inexact"]:
        out.append(f"{where}: {tally['inexact']} of {tally['lanes']} lanes "
                   f"have n_h - P inexact, first "
                   f"{_hexes([first['inexact']], 1)}")
    if tally["past"]:
        out.append(f"{where}: {tally['past']} of {tally['lanes']} lanes have "
                   f"|theta0 - atan(n/d)| past 2^-(p+G) theta0, first "
                   f"{_hexes([first['past']], 1)}, the largest "
                   f"2^{tally['largest']:+.1f} of the bound")
    if tally["wrong"]:
        out.append(f"{where}: {tally['wrong']} of {tally['lanes']} lanes are "
                   f"unmarked and differ from transcend.atan2, first "
                   f"{_hexes([first['wrong']], 1)}")
    return out, tally


# ---- the plants: every check of atan2 on every plant -----------------------------------------

CHECKS_ATAN2 = ("pools", "seq", "bound", "structured", "range", "specials",
                "shape", "audit", "constants", "corner")


def red_checks_atan2(plant, fmt=FP64, pool_rnds=(RNE, RTZ),
                     seq_rnds=(RNE, RTZ), bound_n=48, corner_rnds=(RNE, RTZ)):
    """{check: [findings]} for the checks that are RED on `plant` (None: the
    control) at `fmt`, atan2's ten (CHECKS_ATAN2): pools (and the marks' own
    leg, check_pool_marks) and seq under pool_rnds and seq_rnds, bound over
    the five regions (bound_n points each) under rne, structured, range,
    specials and shape under all five attributes, audit, constants (rne) and
    corner under corner_rnds. A plant atan2 never reaches (tiny_gate_off and
    tiny_side) is refused by the build, by name: the caller catches it."""
    fn = "atan2"
    red = {}

    def add(name, found):
        if found:
            red.setdefault(name, []).extend(found)
    for rnd in pool_rnds:
        add("pools", check_pools(fragment_of(fn, fmt, rnd, plant))[0])
    add("pools", check_pool_marks(fmt)[0])
    for rnd in seq_rnds:
        add("seq", check_seq(fragment_of(fn, fmt, rnd, plant))[0])
    b = build_of(fn, fmt, RNE, plant)
    for region, xs in placed_points(fn, fmt, bound_n).items():
        add("bound", check_bound(b, xs, region)[0])
    for rnd in RND_MODES:
        f = fragment_of(fn, fmt, rnd, plant)
        add("structured", check_structured(f)[0])
        add("range", check_range(f)[0])
        add("specials", check_specials(f)[0])
    add("shape", check_shape(fmt, {(fn, rnd): build_of(fn, fmt, rnd, plant)
                                   for rnd in RND_MODES}))
    add("audit", check_audit_atan2(fmt, plant)[0])
    add("constants", check_constants(
        builder=lambda name, f_, r_: build_of(name, f_, r_, plant),
        formats=(fmt,), attrs=(RNE,), names=(fn,))[0])
    for rnd in corner_rnds:
        add("corner", check_corner(fragment_of(fn, fmt, rnd, plant),
                                   b=build_of(fn, fmt, rnd, plant))[0])
    return red
