# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The lanes, the measurements and the checks parcel E1 holds exp's
fragments to (cft_golden/mathlib.py; docs/studies/M1-exp-log.md, section 8,
items 1 to 5), gathered in one place so that python/tests/test_mathlib.py
(quick, for the golden stage) and python/tests/mathlib_runs.py (the larger
runs, for the lead's box) run the same lanes and the same checks.

A CHECK takes a fragment or its instrumented build and returns FINDINGS: a
list of strings, each beginning with the check's name and a colon, empty
when it holds. So a planted fault is "caught by name" when the check it is
meant for returns a finding that begins with that name, and the test that
plants it says which.

  pools:        every lane of the transcend pools, at one format and
                attribute, through one fragment: every unmarked lane equals
                transcend.exp in bits AND flag word; every marked lane is
                replayed and its guess counted; the marked set is the
                committed one
  seq:          the fragment as a stand-alone program on seq.py (C4's
                routines.program and routines.run) equal to evaluate() and
                to transcend.exp
  r24:          the compiled shape - QUIET, the body, ENDQUIET, RAISE of the
                flag word - on seq.py: each lane's byte is exactly the
                operation's IEEE flags, the mark is bit 7
  bound:        |V - mpmath| / Bv under 1, mpmath at 4p + 200 bits, over
                random arguments with every bit random and over the places
                each path's reduced argument is largest
  budget:       the first-order budget's bound under 1 (mathlib_budget)
  rate:         the mark-rate law with the bound inflated by a fixed factor
  family:       the structured family (mathlib_family): the committed list
                against the theory's generation; the centres and their
                neighbours, inside and outside the windows
  census:       at fp32 the study's census finds no window
  edges:        pools: the thresholds with their signs and the cells' ends
  invariants:   mathlib.invariants()
  constants:    mathlib.check_constants()
"""

import functools
import importlib.util
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

FORMATS = (FP32, FP64, FP128, FP256)
RND_MODES = sf.RND_MODES
N = ml.N


# ---- the definition, memoised -----------------------------------------------

@functools.lru_cache(maxsize=None)
def golden(fmt, rnd, x):
    """transcend.exp: the definition. Cached, since a plant re-runs the
    lanes of the clean fragment."""
    return transcend.exp(fmt, x, rnd)


def value(fmt, bits):
    return ml._dec(fmt, bits)


# ---- the pools --------------------------------------------------------------

_TC = []


def _transcend_check():
    """host/tests/transcend_check.py as a module (it is a script of the
    libcft stage; its pools are what that stage replays)."""
    if not _TC:
        spec = importlib.util.spec_from_file_location(
            "mathlib_transcend_check", ROOT / "host" / "tests" /
            "transcend_check.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _TC.append(mod)
    return _TC[0]


@functools.lru_cache(maxsize=None)
def pools(fmt):
    """The transcend pools, deduplicated and sorted: transcend_check's
    unary_pool at its default trials (64 random encodings at fp32 and fp64,
    16 at fp128 and fp256) and seed 5, the vector sets' transcend_unary_pool
    at the same counts and its seed 9, and test_transcend's brute pool."""
    from test_transcend import _brute_pool
    t = 64 if fmt.width <= 64 else 16
    a = _transcend_check().unary_pool(fmt, t, 5)
    b = vectors.transcend_unary_pool(fmt, t, 9)
    return tuple(sorted(set(a) | set(b) | set(_brute_pool(fmt))))


def tiny_two(fmt, sign):
    """+-2^-p as an encoding: the argument whose exp sits 2^-(2p+1) from a
    rounding boundary, the one lane of the pools the in-lane test cannot
    decide."""
    return sf.round_pack(fmt, sign, 1, -fmt.prec, sf.RND_RNE)[0]


def expected_pool_marks(fmt, rnd):
    """The marked lanes of `pools`, committed: none at fp32 (at G = 40 the
    structured windows are empty, mathlib_family); at fp64, fp128 and fp256
    exactly exp(2^-p) under rne and rmm, whose true value 1 + 2^-p + 2^-(2p+1)
    is 2^-(2p+1) above a midpoint, and exp(-2^-p) under the directed three,
    2^-(2p+1) from the grid point 1 - 2^-p (the study's 3.4, MEASURED again
    in parcel E1's entry)."""
    if fmt.name == "fp32":
        return set()
    return {tiny_two(fmt, 0 if rnd in (sf.RND_RNE, sf.RND_RMM) else 1)}


# ---- tallying lanes against the definition ----------------------------------

class Tally:
    """The lanes of one run: n, how many marked, how many marked guesses
    were right, the unmarked lanes that were wrong, and the marked lanes."""

    def __init__(self):
        self.n = 0
        self.marked = []
        self.guess_wrong = []
        self.wrong = []
        self.stray = []

    @property
    def marked_right(self):
        return len(self.marked) - len(self.guess_wrong)


def tally(fmt, rnd, xs, results):
    t = Tally()
    for x, (bits, fw) in zip(xs, results):
        gb, gf = golden(fmt, rnd, x)
        t.n += 1
        if fw & ~(ml.MARK | 0x1F):
            t.stray.append((x, fw))
        if fw & ml.MARK:
            t.marked.append(x)
            if (bits, fw & 0x1F) != (gb, gf):
                t.guess_wrong.append((x, bits, gb))
        elif (bits, fw) != (gb, gf):
            t.wrong.append((x, (bits, fw), (gb, gf)))
    return t


def _hexes(xs, k=3):
    return ", ".join(hex(x) for x in list(xs)[:k])


def structured_arguments(fmt, rnd):
    """The arguments of the committed structured list (mathlib_family.FAMILY)
    for this format and attribute: the only arguments of the pools that may
    be marked."""
    import mathlib_family as F
    return {F.argument(fmt, c) for c in F.FAMILY[fmt.name][sf.RND_NAMES[rnd]]}


def check_lanes(name, fmt, rnd, xs, results, allowed_marks=None):
    """[finding], Tally: results[i] = (bits, flag word) of xs[i], against
    transcend.exp: every unmarked lane equal in bits and flags; no flag bit
    but [4:0] and the mark; and, where `allowed_marks` is given, a marked
    lane only at one of those arguments."""
    t = tally(fmt, rnd, xs, results)
    where = f"{name}: {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if t.wrong:
        x, got, want = t.wrong[0]
        out.append(f"{where}: {len(t.wrong)} unmarked lanes differ from "
                   f"transcend.exp, first {hex(x)}: got "
                   f"({got[0]:#x}, {got[1]:#x}), want ({want[0]:#x}, "
                   f"{want[1]:#x})")
    if t.stray:
        out.append(f"{where}: {len(t.stray)} flag words carry bits other "
                   f"than [4:0] and the mark, first {hex(t.stray[0][0])}")
    if allowed_marks is not None:
        off = [x for x in t.marked if x not in allowed_marks]
        if off:
            out.append(f"{where}: {len(off)} lanes are marked off the "
                       f"structured list, first {_hexes(off)}")
    return out, t


# ---- the lanes through a fragment -------------------------------------------

def evaluate_all(f, xs):
    return [ml.evaluate(f, x) for x in xs]


def check_pools(f, rnd=None, xs=None):
    """pools: one fragment over the pools of its format. A lane may be
    marked only where the committed structured list has its argument (the
    study found the pools' only marks to be those, exp(+-2^-p): a mark
    anywhere else is a fault)."""
    fmt = f.fmt
    rnd = f.rnd if rnd is None else rnd
    xs = pools(fmt) if xs is None else xs
    return check_lanes("pools", fmt, rnd, xs, evaluate_all(f, xs),
                       structured_arguments(fmt, rnd))


def check_random_lanes(f, n, seed):
    """lanes: n random main-path arguments with every bit random
    (random_main) and n of the weighted sampler (weighted_exp) through the
    fragment, as the pools are: every unmarked lane equal to transcend.exp
    in bits and flags, a mark only on the structured list. A random lane is
    marked with probability about 2^(0.53 - G), 2^-43.5 at fp64 (the study's
    3.4): none of these is."""
    fmt, rnd = f.fmt, f.rnd
    xs = sorted(set(random_main(fmt, n, seed)
                    + weighted_exp(fmt, n, seed + 1)))
    return check_lanes("lanes", fmt, rnd, xs, evaluate_all(f, xs),
                       structured_arguments(fmt, rnd))


def edge_pool(fmt):
    """The arguments the transcend pools mean to hold and, for the negative
    ones, do not: x = n ln2 rounded, with neighbours at +-1 and +-2 ulps,
    for the n of transcend_check.unary_pool's exp edges (emax, emax + 1,
    emin, emin - man_w, emin - man_w - 1, -(p+2), -(p+3), p+1), BOTH signs;
    and placed_exp(), the ends of every cell of n at the ends of the range
    and across k = emin, where the fixed grid takes over.

    The pools' generators (vectors.transcend_unary_pool and
    host/tests/transcend_check.unary_pool) take x = n ln2 from
    mpmath.libmp.to_man_exp, which returns the mantissa unsigned, so every
    negative n comes out positive: the pools hold exp(+708.39...), exp's
    overflow, where the underflow thresholds - the argument of emin ln2 and
    the screen of (emin - p) ln2 - should be. This pool holds both, so that
    the tininess decision at k = emin and the fixed grid are met."""
    l2 = ml._ln2()
    ns = (fmt.emax, fmt.emax + 1, fmt.emin, fmt.emin - fmt.man_w,
          fmt.emin - fmt.man_w - 1, -(fmt.prec + 2), -(fmt.prec + 3),
          fmt.prec + 1)
    out = set(placed_exp(fmt))
    for n in ns:
        for sgn in (1, -1):
            b = ml._enc(fmt, sgn * n * l2)
            out.update((b, b + 1, b - 1, b + 2, b - 2))
    return tuple(sorted(out))


def check_edges(f, xs=None):
    """edges: the signed thresholds and the cell ends (edge_pool) through the
    fragment, as the pools are: every unmarked lane equal to transcend.exp, a
    mark only on the structured list."""
    fmt, rnd = f.fmt, f.rnd
    xs = edge_pool(fmt) if xs is None else xs
    return check_lanes("edges", fmt, rnd, xs, evaluate_all(f, xs),
                       structured_arguments(fmt, rnd))


def check_seq(f, xs=None, evaluator=None):
    """seq: the fragment as a program on seq.py equal to evaluate() lane
    for lane, and to transcend.exp unless marked. `evaluator` is the
    function standing for evaluate(), for the test that plants a fault in
    it."""
    fmt, rnd = f.fmt, f.rnd
    xs = pools(fmt) if xs is None else xs
    outs, words = routines.run(f, xs)
    got = list(zip(outs, words))
    out, t = check_lanes("seq", fmt, rnd, xs, got)
    ev = [(evaluator or ml.evaluate)(f, x) for x in xs]
    bad = [x for x, a, b in zip(xs, got, ev) if a != b]
    if bad:
        out.append(f"seq: {fmt.name} {sf.RND_NAMES[rnd]}: seq.py and "
                   f"evaluate() differ on {len(bad)} lanes, first "
                   f"{hex(bad[0])}")
    return out, t


def r24_program(f, loud=False):
    """The fragment as the compiler inlines it (cftc/inline.py): QUIET, the
    body, ENDQUIET, RAISE of the flag word, the result deposited. `loud`
    leaves the first instruction that can raise a flag outside the region,
    the fault the check must see."""
    prog, bank = routines.program(f)
    insns = list(prog.insns)
    res, flg = seq.decode(insns[-3]), seq.decode(insns[-2])
    assert res["op"] == seq.DEPOSIT and flg["op"] == seq.DEPOSIT
    body = insns[:-3]
    head = []
    if loud:
        for k, word in enumerate(body):
            if seq.decode(word)["op"] in routines.ROUNDED:
                head, body = body[:k + 1], body[k + 1:]
                break
    insns = head + [seq.quiet()] + body + [seq.endquiet(),
                                           seq.raise_(flg["ra"]),
                                           seq.deposit(res["ra"]),
                                           seq.halt()]
    return seq.Program(f.fmt, insns, consts=(), max_deposits=1,
                       flags=seq.FLAG_BANK_EXT, n_consts=len(bank)), bank


def check_r24(f, xs=None, loud=False):
    """r24: on seq.py, each lane's byte is the operation's IEEE flags and
    nothing else, with bit 7 where the lane is marked, and FLAGS and STATUS
    are what the bytes make them (docs/SEQUENCER.md, R23 and R24)."""
    fmt, rnd = f.fmt, f.rnd
    xs = pools(fmt) if xs is None else xs
    prog, bank = r24_program(f, loud)
    res = seq.run(prog, list(xs), [0] * len(xs), bank=bank)
    out, flags_or, marked = [], 0, False
    tag = f"r24: {fmt.name} {sf.RND_NAMES[rnd]}"
    for i, x in enumerate(xs):
        bits, fw = ml.evaluate(f, x)
        gb, gf = golden(fmt, rnd, x)
        byte = res.lane_flags[i]
        flags_or |= byte & seq.LANE_FLAGS_IEEE
        if fw & ml.MARK:
            marked = True
            want = (fw & 0x1F) | seq.LANE_MARKED
        else:
            want = gf
            if res.deposits[i] != gb:
                out.append(f"{tag}: lane {hex(x)} deposited "
                           f"{res.deposits[i]:#x}, want {gb:#x}")
        if byte != want:
            out.append(f"{tag}: lane {hex(x)} raised {byte:#x}, want "
                       f"{want:#x}")
    if res.flags != flags_or:
        out.append(f"{tag}: FLAGS {res.flags:#x} is not the OR of the "
                   f"lanes' bytes {flags_or:#x}")
    if bool(res.status & seq.STATUS_MARKED) != marked:
        status6 = bool(res.status & seq.STATUS_MARKED)
        out.append(f"{tag}: STATUS[6] is {status6}"
                   f", a marked lane was {'' if marked else 'not '}run")
    return out[:6]


# ---- the main path ----------------------------------------------------------

def screens(fmt):
    """(XOVF, XUNF) as values."""
    hi, lo = ml._screens(fmt)
    return value(fmt, hi), value(fmt, lo)


def in_main(fmt, x):
    """Whether the main path answers x: no NaN, infinity, zero, screen or
    tiny-argument gate does."""
    u = sf.unpack(fmt, x)
    if u.kind in (sf.NAN, sf.INF, sf.ZERO):
        return False
    xv = value(fmt, x)
    hi, lo = screens(fmt)
    return lo < xv < hi and abs(xv) >= Fraction(1, 2 ** (fmt.prec + 3))


def random_main(fmt, n, seed):
    """n arguments of the main path with every bit random: 60% a real
    drawn uniformly over the whole range between the screens (p + 20 random
    bits, rounded), 40% a random mantissa at a random exponent from
    -(p + 2) to 4 and a random sign (the study's domain_sample, with the
    low bits random, not 53 of them)."""
    rng = random.Random(seed * 1000003 + fmt.width)
    p = fmt.prec
    hi, lo = screens(fmt)
    out = []
    while len(out) < n:
        if rng.random() < 0.6:
            x = ml._enc(fmt, lo + (hi - lo) *
                        Fraction(rng.getrandbits(p + 20), 2 ** (p + 20)))
        else:
            e = rng.randint(-(p + 2), 4)
            x = sf.round_pack(fmt, rng.getrandbits(1),
                              rng.getrandbits(p) | (1 << (p - 1)),
                              e - p + 1, sf.RND_RNE)[0]
        if in_main(fmt, x):
            out.append(x)
    return out


def uniform_m1rate(fmt, n, seed=7):
    """The arguments the study's m1rate.py draws for exp, its
    uniform_sample: n reals uniform on ((emin - p) 0.693 + 1,
    (emax + 1) 0.693 - 1), from random.Random(seed + width), each a Python
    float taken exactly. They lie between the two screens, so all are on the
    main path; the few under emin ln2 have subnormal results, which the
    fixed grid rounds and rarely marks."""
    rng = random.Random(seed + fmt.width)
    p = fmt.prec
    lo, hi = (fmt.emin - p) * 0.693 + 1, (fmt.emax + 1) * 0.693 - 1
    return [ml._enc(fmt, Fraction(rng.uniform(lo, hi))) for _ in range(n)]


# the n whose cells' ends are measured: small ones, every residue j at a few
# k, and the ends of the main path, at both of each cell's ends
_PLACED_N = (-41, -17, -9, -1, 0, 1, 3, 9, 33, 77, 401)


def placed_exp(fmt):
    """The arguments where this path's reduced r is largest: x next to
    (n +- 1/2) ln2/8, the ends of each cell of n, for the study's n and for
    every residue j = n mod 8 at k = emin - 1, emin, emin + 1, -1, 0, 1 and
    at the ends of the main path (the study's worstcase.py, extended to the
    ends of n's range and to every j); each with its two neighbours in the
    encoding."""
    p = fmt.prec
    l2 = ml._ln2()
    hi, lo = screens(fmt)
    k_top, k_bot = math.floor(hi * N / l2) // N, math.ceil(lo * N / l2) // N
    ns = set(_PLACED_N)
    for k in (fmt.emin - 1, fmt.emin, fmt.emin + 1, -1, 0, 1, k_top,
              k_top - 1, k_bot, k_bot + 1):
        ns.update(N * k + j for j in range(N))
    out = set()
    for n in sorted(ns):
        for s in (-1, 1):
            mid = (Fraction(n) + Fraction(s, 2)) * l2 / N
            b = ml._enc(fmt, Fraction(math.floor(mid * 2 ** (p + 60)),
                                      2 ** (p + 60)))
            out.update((b, b + 1, b - 1))
    return sorted(x for x in out if in_main(fmt, x))


def uniform_unit(fmt, n, seed):
    """n arguments uniform on [-1, 1] with every bit random (p + 20 random
    bits, rounded): the region of VM1b's budget for exp, 0.164 Bv at fp64
    and G = 44 (the study's 3.3)."""
    rng = random.Random(seed * 15485863 + fmt.width)
    p = fmt.prec
    return [ml._enc(fmt, 2 * Fraction(rng.getrandbits(p + 20), 2 ** (p + 20))
                    - 1) for _ in range(n)]


def weighted_exp(fmt, n, seed):
    """n arguments of VM1's sampler for the exp family, weighted to where
    the terms are largest: x = (m + d) ln2/8, m half the time near 0 and
    half over the whole range, d 40% uniform in (-1/2, 1/2), 40% within
    0.0003 of an end and 20% small (verifier-VM1's p8_bound.py, vm1b)."""
    rng = random.Random(seed * 104729 + fmt.width)
    p = fmt.prec
    l2 = ml._ln2()
    hi, lo = screens(fmt)
    nlo, nhi = math.ceil(lo * N / l2), math.floor(hi * N / l2)
    out = []
    while len(out) < n:
        m = rng.randint(-24, 24) if rng.random() < 0.5 else \
            rng.randint(nlo + 16, nhi - 16)
        r = rng.random()
        if r < 0.4:
            d = Fraction(rng.randint(-499999, 499999), 10 ** 6)
        elif r < 0.8:
            d = (1 if rng.random() < 0.5 else -1) * (
                Fraction(1, 2) - Fraction(rng.randint(0, 3000), 10 ** 7))
        else:
            d = Fraction(rng.randint(-5, 5), 100)
        x = ml._enc(fmt, (Fraction(m) + d) * l2 / N)
        if in_main(fmt, x):
            out.append(x)
    return out


# ---- the bound against mpmath -----------------------------------------------

def _v_names(b):
    return ("V0", "V1", "V2") if b.meta["family"] == "triple word" \
        else ("Vh", "Vl")


def bound_log2(b, x):
    """log2(|V - exp(x) 2^-k| / Bv) for one main-path lane of the build b:
    V from its probes (V_h + V_l, or the three words at fp32), k from Ek,
    the true value from mpmath at 4p + 200 bits. None where V is exact."""
    fmt = b.fmt
    names = _v_names(b)
    _res, _fl, pr = b.run(x, names + ("Bv", "Ek"))
    k = pr["Ek"] - fmt.bias - b.meta["OFF"]
    with mpmath.workprec(4 * fmt.prec + 200):
        T = mpmath.exp(_mp(value(fmt, x))) * mpmath.mpf(2) ** (-k)
        V = sum(_mp(value(fmt, pr[nm])) for nm in names)
        err = abs(V - T)
        if err == 0:
            return None
        return float(mpmath.log(err / _mp(value(fmt, pr["Bv"])), 2))


def _mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


def check_bound(b, xs, label="random"):
    """[finding], (worst log2(err/Bv), lanes measured): bound: every
    measured lane under 1 Bv."""
    worst, n, bad = -1e9, 0, []
    for x in xs:
        if not in_main(b.fmt, x):
            continue
        r = bound_log2(b, x)
        n += 1
        if r is None:
            continue
        if r > worst:
            worst = r
        if r >= 0:
            bad.append((r, x))
    out = []
    if bad:
        r, x = max(bad)
        out.append(f"bound: {b.fmt.name} {sf.RND_NAMES[b.rnd]} {label}: "
                   f"{len(bad)} of {n} lanes are past the bound, the worst "
                   f"{hex(x)} at 2^{r:+.2f} of Bv")
    return out, (worst, n)


def check_budget(b, xs, label="budget"):
    """[finding], summary: budget: the first-order budget's bound
    (mathlib_budget: the method's largest error plus the rounding
    instructions' largest capacities, in Bv) under 1, and no sampled lane's
    error past it."""
    import mathlib_budget as MB
    s = MB.Budget(b).add(xs).summary()
    out = []
    where = f"budget: {b.fmt.name} {sf.RND_NAMES[b.rnd]} {label}"
    if s["bound"] >= 1:
        out.append(f"{where}: the budget's bound is {s['bound']:.3g} Bv "
                   f"(M {s['Mmax']:.3g} + capacities {s['S_cap']:.3g}), "
                   f"not under 1")
    if s["Emax"] > s["bound"] * 1.001:
        out.append(f"{where}: a lane's error {s['Emax']:.3g} Bv is past the "
                   f"budget's bound {s['bound']:.3g}")
    return out, s


# ---- the mark-rate law ------------------------------------------------------

def check_rate(fmt, rnd, n=2000, seed=7, sigmas=3.0, g_inflated=6,
               plant=None):
    """[finding], stats: rate: the mark-rate law (the study's 3.4). The bound
    is inflated to 2^-(p+6), so that G' = g_inflated = 6 is the guard left,
    and a random lane's true value, uniform within a rounding cell, is within
    the bound of a boundary - and so marked - with probability
    2^(0.53 - G') (2^-G' / ln 2, the average of 2 Bv / ulp over the binade).
    On n uniform main-path arguments (uniform_m1rate: the study used 2,000 a
    cell) the marked fraction must be within `sigmas` sigma of that, every
    unmarked lane right, and every marked guess counted (the study found
    them all right; a wrong one is a finding here)."""
    G = ml.GUARD[fmt.name]
    build = ml.build_exp(fmt, rnd, bound_shift=G - g_inflated, plant=plant)
    f = build.fragment()
    xs = uniform_m1rate(fmt, n, seed)
    t = tally(fmt, rnd, xs, evaluate_all(f, xs))
    p_mark = 2.0 ** (0.53 - g_inflated)
    mean, sd = n * p_mark, math.sqrt(n * p_mark * (1 - p_mark))
    st = {"n": n, "marked": len(t.marked), "expected": mean, "sigma": sd,
          "wrong": len(t.wrong), "guess_wrong": len(t.guess_wrong)}
    where = f"rate: {fmt.name} {sf.RND_NAMES[rnd]} (G' = {g_inflated})"
    out = []
    if abs(len(t.marked) - mean) > sigmas * sd:
        out.append(f"{where}: {len(t.marked)} of {n} lanes marked, "
                   f"{mean:.1f} expected (sigma {sd:.1f}): "
                   f"{(len(t.marked) - mean) / sd:+.1f} sigma")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} unmarked lanes are wrong")
    if t.guess_wrong:
        out.append(f"{where}: {len(t.guess_wrong)} marked guesses are wrong")
    return out, st


# ---- the structured family --------------------------------------------------

def family_lanes(fmt, rnd, centres, G=None):
    """[(x, label, what the theory demands)] for the centres and their
    neighbours, each lane once (mathlib_family.classify)."""
    import mathlib_family as F
    seen, out = set(), []
    for cen in centres:
        x0 = F.argument(fmt, cen)
        for x, lab in [(x0, "centre")] + F.neighbours(fmt, cen, G):
            if x not in seen:
                seen.add(x)
                out.append((x, f"{cen[0]} 2^-{cen[1]} {lab}",
                            F.classify(fmt, rnd, x, G)))
    return out


def check_family_list(committed, generated=None):
    """family: the committed centres (mathlib_family.FAMILY, or a copy a test
    has tampered with) are exactly what the theory generates."""
    import mathlib_family as F
    generated = F.generate() if generated is None else generated
    out = []
    for fmt_name in sorted(set(committed) | set(generated)):
        for rnd_name in sorted(set(committed.get(fmt_name, {})) |
                               set(generated.get(fmt_name, {}))):
            have = committed.get(fmt_name, {}).get(rnd_name)
            want = generated.get(fmt_name, {}).get(rnd_name)
            if have != want:
                miss = sorted(set(want or ()) - set(have or ()))
                extra = sorted(set(have or ()) - set(want or ()))
                out.append(f"family: the committed centres of {fmt_name} "
                           f"{rnd_name} are not the theory's: missing "
                           f"{miss[:3]}, extra {extra[:3]}")
    return out


def census_run(f):
    """Tally: the study's census (mathlib_family.census, 240 arguments
    x = c 2^-e at the fragment's format) through the fragment, against
    transcend.exp. The study's census.py counted the marks of these."""
    import mathlib_family as F
    xs = sorted(F.census(f.fmt))
    return tally(f.fmt, f.rnd, xs, evaluate_all(f, xs))


def check_census_empty(f):
    """census: the study's census finds no window - no lane marked, every
    lane right - which is what fp32 must show at G = 40: marks need an
    exponent from (p + G)/2 = 32 down to p = 24, an empty range."""
    t = census_run(f)
    out = []
    where = f"census: {f.fmt.name} {sf.RND_NAMES[f.rnd]}"
    if t.marked:
        out.append(f"{where}: {len(t.marked)} of the census's {t.n} "
                   f"arguments are marked, first {_hexes(t.marked)}; the "
                   f"windows are meant to be empty")
    if t.wrong:
        out.append(f"{where}: {len(t.wrong)} census lanes are wrong "
                   f"unmarked, first {hex(t.wrong[0][0])}")
    return out, t


def check_family(f, centres, G=None, extra=(), deep=False):
    """[finding], stats: family: on the centres and their neighbours, on
    `extra` (the census arguments that are not centres) and, with `deep`, on
    the arguments between the first exponent a window can start at and the
    census (mathlib_family.deep_arguments), the routine marks every lane the
    theory says is inside a window, marks none that is outside or gated, and
    is right on every lane it does not mark."""
    fmt, rnd = f.fmt, f.rnd
    import mathlib_family as F
    lanes = family_lanes(fmt, rnd, centres, G)
    seen = {x for x, _l, _c in lanes}
    more = [(x, f"census {hex(x)}") for x in extra]
    if deep:
        more += [(x, f"deep {lab}") for x, lab in F.deep_arguments(fmt, G)]
    for x, lab in more:
        if x not in seen:
            seen.add(x)
            lanes.append((x, lab, F.classify(fmt, rnd, x, G)))
    xs = [x for x, _l, _c in lanes]
    res = evaluate_all(f, xs)
    out = []
    st = {"lanes": len(lanes), "guess_wrong": 0, "wrong": 0}
    for w in ("mark", "clear", "either", "gated"):
        st[w] = st["marked_" + w] = 0
    tag = f"family: {fmt.name} {sf.RND_NAMES[rnd]}"
    for (x, lab, want), (bits, fw) in zip(lanes, res):
        marked = bool(fw & ml.MARK)
        gb, gf = golden(fmt, rnd, x)
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
            out.append(f"{tag}: {lab} ({hex(x)}) is inside a window, "
                       f"d = {F.distance(fmt, rnd, x, G):.3f}, and not marked")
        if want in ("clear", "gated") and marked:
            where = "gated" if want == "gated" else "outside every window"
            out.append(f"{tag}: {lab} ({hex(x)}) is {where} and marked")
    return out[:8], st


# ---- invariants and constants, as findings ----------------------------------

def check_invariants(f, **kw):
    return [f"invariants: {s}" for s in ml.invariants(f, **kw)]


def check_constants(**kw):
    lines, findings = ml.check_constants(**kw)
    return [f"constants: {s}" for s in findings], lines
