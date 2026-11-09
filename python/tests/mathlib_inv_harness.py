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


def structured_lanes(fn, fmt, rnd, table=None):
    """The committed lanes of (fn, fmt, rnd), both signs: encodings."""
    out = []
    for rnds, lanes in (STRUCT if table is None else table)[fn].get(
            fmt.name, []):
        if rnd in rnds:
            for x in lanes:
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

def _seq_lanes(fn, fmt):
    """The lanes of the seq check: the brute pool, every 16th power of two of
    the stage's pool, and 64 random main-path arguments (seed 11)."""
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


def check_seq(f, xs=None, evaluator=None, loud=False, post=None, table=None):
    """[finding], lanes: seq. The fragment as a program on seq.py
    (routines.program and routines.run) equal to evaluate() lane for lane
    (`evaluator` stands for it, for the test that plants a fault in it) and,
    where unmarked, to transcend.py; the compiled shape (QUIET, the body,
    ENDQUIET, RAISE of the flag word: mathlib_harness.r24_program, `loud`
    moving the QUIET past the third MUL, which raises invalid outside it on
    +inf) with
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
    have = set(xs)
    xs += [x for x in dict.fromkeys(struct) if x not in have]
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
                   f"bound, the worst {hex(x)} at 2^{r:+.2f} of Bv")
    if differ:
        out.append(f"{where}: {len(differ)} unmarked lanes differ from "
                   f"transcend.{fn}, first {hex(differ[0])}")
    return out, (worst, n, len(xs))


def placed_points(fn, fmt, n=48, seed=11):
    """The bound check's lanes: n points of each region (edge, big, small,
    random), seed `seed`."""
    return {r: sample(fn, fmt, r, n, seed) for r in REGIONS}


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
# 21: the Newton steps) and the tail (6, 14, 29: D - K + 1 FMAs) are the
# formats'; the rest is the same at every format
_PHASES_ATAN = {"front": 5, "index": 7, "num": 6, "den": 6, "z": 6,
                "head": 52, "atan_s": 6, "table": 17, "recon": 23,
                "final": 9, "classify": 4, "special": 12}
_QUOTIENT = {"fp64": 17, "fp128": 19, "fp256": 21}
_TAIL = {"fp64": 6, "fp128": 14, "fp256": 29}


def model_phases(fn, fmt_name):
    """The study's instructions by phase for fn at the format; atan's, the
    function this parcel builds (M4G2 and M4G3 extend it by function)."""
    if fn != "atan":
        raise ValueError(f"no phases of {fn} pinned")
    return dict(_PHASES_ATAN, quotient=_QUOTIENT[fmt_name],
                tail=_TAIL[fmt_name])


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
        formats=(fmt,), attrs=(RNE,))[0])
    return red


# ---- asin and acos: parcel M4G2 builds here ----
#
# (assign into POOL_FNS, TRUE_FNS, SAMPLE_FNS, IN_MAIN, SPECIAL_ROWS, STRUCT,
# SHAPE, FLAG_WORDS, MIN_MAX and extend INV_POOL_MARKS, model_phases and the
# plants table of test_mathlib_inv.py; do not edit the checks above)


# ---- atan2: parcel M4G3 builds here ----
#
# (the same tables, by function; atan2 lanes are tuples (y, x))
