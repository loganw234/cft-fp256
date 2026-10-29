# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""fp32's triple-word reduction (parcel M2F1): build_reduction(FP32) at G = 40,
mathlib.trig_reduction_tw on plan_reduction_tw, parcel M2X's tw32.reduce_tw
(docs/studies/m2/) ported, and the two switches of the shared front it needs
(reduction_front's rho_half and late_from). The model is NOT imported here
(nothing in the tree imports it): what it computed is recorded below, READ
from its outputs (tw32_costs.out.txt, tw32_reduce.out.txt) or MEASURED by
running it on the arguments listed, and the port is held to those; the run
that put the port beside the model lane for lane is in docs/VALIDATION.md.

The legs, each able to fail alone (the plant table says which plant turns
which red):
  shape      the instructions by phase, the bank words, the claims, the 13
             static proofs by name and in order, the error-free transformations,
             the dag digest: the model's, under all five attributes
  model      the model's outputs at 22 arguments, lane for lane
  switches   off, the front is M2G1's; each switch changes what it names
  bound      with the looser rho bound the lower group's proof fails, by name
  reference  r = r0 + r1 + r2 against |x| 2/pi in exact rationals, from the
             header: its relative error, the quadrant, `small`, q
  audit      every claimed-exact instruction holds on every lane, the binade
             edges of the products included
  cushion    the measured overshoot past pi/4 under the computed bound, the
             bound proved (_check_trig_cushion_tw), rho an exact rational
  constants  check_reduction_tw_constants: every word against an independent
             derivation and the header
"""

import functools
import math
import pathlib
import random
import subprocess
import sys
import types
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import routines  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import test_mathlib_reduction as RT  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
FMT = FP32
G = ml.GUARD["fp32"]                                  # 40
P_BITS = FMT.prec
MAGIC = ml._enc_exact(FMT, Fraction(3, 2) * 2 ** (P_BITS - 1))


# ---- what the model states and measured (READ, MEASURED on the model) --------

PHASES = {"red-setup": 18, "red-window": 51, "red-products": 15,
          "red-coarse": 18, "red-mid": 56, "red-products-low": 18,
          "red-lower": 30, "red-triple": 66, "red-scale": 41, "red-small": 6}
# the 13 static proofs the reduction holds (tw32_costs.out.txt:5-17), in order
PROOFS = ["coarse sum exact (P0, rho0, P1 mod m)"] * 2 + [
    "f_I = V_I - k U exact", "split at 2^-20: magic in range",
    "split at 2^-20: magic in range", "upper group not empty",
    "e + low word of the upper group exact",
    "split at 2^-56: magic in range", "split at 2^-56: magic in range",
    "lower group not empty", "carry: magic in range", "e + carry exact",
    "overshoot of |r| past pi/4 is small"]
# TwoSum, Fast2Sum, TwoProd of the reduction; the claims (exact, data); words
EFT, CLAIMS, WORDS = (21, 2, 11), (64, 13), 50
PIECES = {"upper": 4, "lower": 6, "lows": 8}
# the dataflow graph's digest (dag_digest of the unpruned body): MEASURED equal
# to the model's reduce_tw (docs/VALIDATION.md, parcel M2F1)
DAG = "98d7a660ced867bd8574c5a704be1232a895f397d4b5148a669ec491323e0ac7"
# the model's COMPUTED bound on |r| past pi/4, 2.029e-06 = 2^-18.91, and the
# largest overshoot it measured, 1.878e-06 = 2^-19.02 at 0x4bb9109b
OVER, OVER_MEASURED = 2.0293518901991266e-06, "1.878e-06"
# r's largest relative error, in units of 2^-(p+G): 2^-5.51 (tw32_reduce.out.txt)
WORST_LOG2 = -5.51
# the plan's static bounds (tw32.tw_plan().rows, rounded to 1e-6): (j, log2
# Tmin, log2 Tmax, P's grid, rho's bound, rho's grid)
ROWS = [(0, 35.403278, 39.978152, 12, 16, 0), (1, 19.403278, 23.978152, -4, 0, -16),
        (2, 3.403278, 7.978152, -20, -16, -32), (3, -12.596722, -8.021848, -36, -32, -48),
        (4, -28.596722, -24.021848, -52, -48, -64), (5, -44.596722, -40.021848, -68, -64, -80),
        (6, -60.596722, -56.009519, -84, -80, -96), (7, -75.08683, -72.009519, -99, -96, -112),
        (8, -91.08683, -88.009519, -115, -112, -128)]
# the model's (x, r0, r1, r2, q, small) at 22 arguments (MEASURED by running
# tw32.reduce_tw): the float just above pi/4 and its neighbours, 0x44264edd,
# the arguments of the largest overshoot and of r's largest error in each of
# the study's families, 1.0, pi, the largest float, the smallest normal
MODEL_LANES = [
    (0x3f490fdb, 0x3f490fdb, 0x00000000, 0x00000000, 0x4b400000, 0),
    (0x3f490fd8, 0x3f490fd8, 0x00000000, 0x00000000, 0x4b400000, 1),
    (0x3f490fdc, 0xbf490fd9, 0xb28885a3, 0xa48d3130, 0x4b400001, 0),
    (0x44264edd, 0x3f490f7c, 0x32565f39, 0xa5262474, 0x4b3fffff, 0),
    (0x4bb9109b, 0x3f490ff3, 0x32c50cde, 0xa490f87c, 0x4b3ffffc, 0),
    (0xd3098cea, 0x3f0a5430, 0xafe1f56a, 0x234ac000, 0x4b3ffffe, 0),
    (0x6001f405, 0xbf13b457, 0x2f7e0dea, 0x22d00c00, 0x4b3fffff, 0),
    (0x5a0df42c, 0x3f490fac, 0xb03ed44a, 0xa3d7f300, 0x4b3fffff, 0),
    (0x3f800000, 0xbf121fb5, 0xb28885a3, 0xa48d3135, 0x4b400001, 0),
    (0x40490fdb, 0x33bbbd2e, 0x27772ced, 0x99cc5178, 0x4b400002, 0),
    (0x7f7fffff, 0xbf0c8e7f, 0xb2503b5f, 0x2524ff70, 0x4b400000, 0),
    (0x00800000, 0x00800000, 0x00000000, 0x00000000, 0x4b400000, 1),
    (0x3e800000, 0x3e800000, 0x00000000, 0x00000000, 0x4b400000, 1),
    (0x47c35000, 0xbd127552, 0xaec55c7a, 0x20846c00, 0x4b400002, 0),
    (0xbf800000, 0xbf121fb5, 0xb28885a3, 0xa48d3135, 0x4b400001, 0),
    (0x7bdd447c, 0x3f490ff3, 0x31fbdc82, 0x2377c280, 0x4b400000, 0),
    (0x63d8c0f2, 0xbf490ff3, 0xb1e35756, 0xa4d79380, 0x4b400001, 0),
    (0x73fa22b3, 0x3f490ff3, 0xb00593ad, 0xa3f8b100, 0x4b400003, 0),
    (0x5b90c020, 0xbf490ff2, 0xb25bbdd3, 0x25b7d2c4, 0x4b400002, 0),
    (0x4d000000, 0x3f33c564, 0x321424df, 0x259e1948, 0x4b3fffff, 0),
    (0xfef7caae, 0xbc2c5589, 0x2f29a015, 0x229a5030, 0x4b400003, 0),
    (0x42395aa0, 0xbf490f3e, 0x2e2dc9ef, 0xa1f0e000, 0x4b400002, 0),
]
# the arguments the model's reduce mode found worst: r's largest error in its
# five families, and its five largest overshoots (tw32_reduce.out.txt)
WORST = (0xd3098cea, 0x6001f405, 0xfef7caae, 0x42395aa0, 0x5a0df42c, 0x4bb9109b,
         0x7bdd447c, 0x63d8c0f2, 0x73fa22b3, 0x5b90c020, 0x44264edd, 0x3f490fdb)


# ---- the builds, the arguments ------------------------------------------------

@functools.lru_cache(maxsize=None)
def plan_tw():
    return ml.plan_reduction_tw()


@functools.lru_cache(maxsize=None)
def build_tw(plant=None, rnd=sf.RND_RNE):
    return ml.build_reduction(FMT, rnd, plant=plant)


def quad_args(P=None, K=64, J=3, extra=128, seed=41):
    """The floats within J ulps of (k + 1/2) pi/2, the odd multiples of pi/4
    and the quadrant boundaries, for every k from 0 (0x3f490fdb is k = 0, j =
    0) and `extra` random k of random size, both signs (the model's
    quad_family, with M2G1's pi)."""
    rng = random.Random(seed)
    pio2 = ml._pi() / 2
    ks = list(range(K)) + [rng.getrandbits(rng.randint(1, FMT.emax))
                           for _ in range(extra)]
    out = set()
    for k in ks:
        c = ml._enc(FMT, (Fraction(k) + Fraction(1, 2)) * pio2)
        for j in range(-J, J + 1):
            out.update((c + j, (c + j) | FMT.sign_mask))
    return sorted(x for x in out if sf.unpack(FMT, x).kind
                  not in (sf.INF, sf.NAN) and ml._main_lane(FMT, plan_tw(), x))


def edge_sample(n=2000, seed=31):
    """n floats within 3 ulps of odd multiples of pi/4 of random size, both
    signs, in the main range (the model's m2measure.sample "edge")."""
    rng = random.Random(seed * 1000003 + FMT.width)
    pio2 = ml._pi() / 2
    out = []
    for _ in range(n):
        E = rng.randint(1, FMT.emax)
        k = rng.getrandbits(max(1, E)) | 1
        x = ml._enc(FMT, (Fraction(k) + Fraction(1, 2)) * pio2) + rng.randint(-3, 3)
        out.append(x | FMT.sign_mask if rng.getrandbits(1) else x)
    return [x for x in out if sf.unpack(FMT, x).kind not in (sf.INF, sf.NAN, sf.ZERO)
            and ml._main_lane(FMT, plan_tw(), x)]


def half_family(thr_bits=18, cap=96, small_v=6, neighbours=2):
    """The floats next to the odd multiples of pi/4 in every binade, positive
    (the model's half_family, 8,138 with the negative ones left out): value
    exponents -1 to 6 every odd multiple in the binade and `neighbours` either
    side; 7 and up the floats whose x 2/pi lies within 2^-thr_bits of a
    half-integer (the `cap` nearest, about 128 a binade), found with numpy's
    wrapping uint64 product M x (2^e 2/pi mod 1 to 64 bits). The only use of
    numpy here, and for the box run only: ImportError where it is absent."""
    import importlib.util
    import numpy as np
    spec = importlib.util.spec_from_file_location(
        "pi_worstcase", ROOT / "host" / "tools" / "pi_worstcase.py")
    pw = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pw)
    pio2, lo, out = ml._pi() / 2, 1 << (P_BITS - 1), set()
    Ms = np.arange(lo, 1 << P_BITS, dtype=np.uint64)
    for v in range(-1, FMT.emax + 1):
        if v <= small_v:
            k = 0
            while (Fraction(k) + Fraction(1, 2)) * pio2 < Fraction(2) ** (v + 1):
                m = (Fraction(k) + Fraction(1, 2)) * pio2
                if m >= Fraction(2) ** v:
                    out.update(ml._enc(FMT, m) + j
                               for j in range(-neighbours, neighbours + 1))
                k += 1
            continue
        a64 = np.uint64(pw.alpha_of(v - P_BITS + 1, 128) >> 64)
        d = (Ms * a64 - np.uint64(1 << 63)).view(np.int64)
        ad = np.abs(d.astype(np.float64))
        idx = np.nonzero(ad < float(1 << (64 - thr_bits)))[0]
        if len(idx) > cap:
            idx = idx[np.argsort(ad[idx])[:cap]]
        out.update(((v + FMT.bias) << FMT.man_w) | int(Ms[int(i)] - lo)
                   for i in idx)
    return sorted(x for x in out if ml._main_lane(FMT, plan_tw(), x))


@functools.lru_cache(maxsize=None)
def fams():
    """The test-sized families: the study's own arguments at a small N
    (random, bucket edges, powers of two, the pools), the products' binade
    edges, the quadrant boundaries (K = 24), the odd multiples of pi/4 in
    every binade, RD(pi/4)'s neighbours and the model's worst arguments."""
    P = plan_tw()
    rand, buckets, pow2, pool = RT.redcheck_args(FMT, P, 100)
    return {"main": tuple(rand + buckets + pow2 + pool),
            "edges": tuple(RT.edge_args(FMT, P)),
            "quad": tuple(quad_args(K=24, extra=24)),
            "halves": tuple(RT.half_args(FMT, P, 1)),
            "pio4": tuple(RT.near_pio4(FMT)), "worst": WORST}


def run_lanes_tw(b, xs):
    """Each lane through the build's unpruned body once: its rows (x, r0, r1,
    r2, q, small) and the claims that fail (reduction_audit's, from the same
    values), with the audit's tally."""
    rows, bad, tally = [], [], {}
    for x in xs:
        vals = ml._values(FMT, b.body, b.words, x)
        get = ml._getter(vals, b.words, x)
        rows.append((x,) + tuple(get(b.probes[k]) for k in
                                 ("r0", "r1", "r2", "q", "small")))
        fails = ml._audit_values(b, x, vals, tally)
        if fails:
            bad.append((x, fails))
    return types.SimpleNamespace(b=b, rows=rows, bad=bad, tally=tally)


@functools.lru_cache(maxsize=None)
def clean_run(fam):
    return run_lanes_tw(build_tw(), fams()[fam])


# ---- the checks: each returns its findings, "check: ..." ---------------------

def check_shape(b):
    """The model's figures: instructions by phase, words, claims, proofs in
    order, error-free transformations, pieces."""
    out = []
    by = {}
    for ph in b.phase_of:
        by[ph] = by.get(ph, 0) + 1
    if by != PHASES:
        out.append(f"shape: instructions by phase {by}, not {PHASES}")
    if len(b.words) != WORDS:
        out.append(f"shape: {len(b.words)} bank words, not {WORDS}")
    got = (len(b.meta.get("exact", ())), len(b.meta.get("data", ())))
    if got != CLAIMS:
        out.append(f"shape: claims (exact, data) {got}, not {CLAIMS}")
    if b.meta.get("proofs") != PROOFS:
        out.append(f"shape: the static proofs {b.meta.get('proofs')}, not the "
                   f"model's 13")
    eft = (b.meta["two_sum"], b.meta["fast_two_sum"], b.meta["two_prod"])
    if eft != EFT:
        out.append(f"shape: TwoSum, Fast2Sum, TwoProd {eft}, not {EFT}")
    if b.meta["reduction_tw"]["pieces"] != PIECES:
        out.append(f"shape: pieces {b.meta['reduction_tw']['pieces']}")
    return out


def check_digest(b):
    """The dataflow graph is the model's (dag_digest of the unpruned body)."""
    if ml.dag_digest(routines.Fragment(
            "x", b.fmt, b.rnd, b.inputs, b.body, b.result, b.flags, b.words,
            "read")) != DAG:
        return ["digest: the dag digest is not the model's"]
    return []


def check_reference(run, stats=None):
    """r = r0 + r1 + r2 and n mod 4 of every lane against |x| 2/pi in exact
    rationals, 2/pi from the header: |r - (|x| - n pi/2)| <= 2^-(p+G+3) |r|,
    |r| <= pi/4 (1 + OVER), the model's computed bound (pinned: the build's
    own is the cushion check's), `small` nonzero
    exactly where |x| < RD(pi/4) (there r0 = |x|, r1 = r2 = +0, q = MAGIC) and q
    on MAGIC's integer grid. `stats` gains "worst" (log2 of the largest
    relative error in units of 2^-(p+G)), "over" (the largest 2|t| - 1) and
    "lanes"."""
    tol = Fraction(1, 2 ** (P_BITS + G + 3))
    size = (1 + Fraction(OVER)) / 2          # |t|: the model's bound, pinned
    why = {}
    worst, worst_x, over = -math.inf, None, Fraction(0)

    def note(kind, x):
        c, first = why.get(kind, (0, None))
        why[kind] = (c + 1, first if first is not None else x)
    for x, r0, r1, r2, q, small in run.rows:
        try:
            rm = sum(ml._dec(FMT, w) for w in (r0, r1, r2))
        except ValueError:
            note("a non-finite r word", x)
            continue
        if q >> FMT.man_w != MAGIC >> FMT.man_w:
            note("q not on MAGIC's integer grid", x)
        t, r, T = RT.reference(FMT, x, q & 3)
        over = max(over, 2 * abs(t) - 1)
        if abs(t) > size:
            note("a quadrant off (|r| past pi/4 (1 + OVER))", x)
            continue
        if r == 0 or abs(rm - r) > tol * abs(r):
            note("r off by more than 2^-(p+G+3) of itself", x)
        else:
            e = RT._log2(abs(rm - r) / abs(r)) + P_BITS + G
            if e > worst:
                worst, worst_x = e, x
        X = abs(ml._dec(FMT, x))
        if 2 * X * T < 1:
            up = ml._dec(FMT, sf.next_up(FMT, x & ~FMT.sign_mask)[0])
            want = 2 * up * T < 1
        else:
            want = False
        if bool(small & 0x7fffffff) != want:
            note("`small` not where |x| < RD(pi/4)", x)
        elif small & 0x7fffffff and (r0 != x & ~FMT.sign_mask or r1 or r2
                                     or q != MAGIC):
            note("a small lane not r = |x|, r1 = r2 = +0, q = MAGIC", x)
    if stats is not None:
        if worst > stats.get("worst", -math.inf):
            stats["worst"], stats["worst_x"] = worst, worst_x
        stats["over"] = max(stats.get("over", Fraction(0)), over)
        stats["lanes"] = stats.get("lanes", 0) + len(run.rows)
        stats["quadrant off"] = stats.get("quadrant off", 0) + why.get(
            "a quadrant off (|r| past pi/4 (1 + OVER))", (0, 0))[0]
    run.over = over
    return [f"reference: {c} lanes with {kind}, the first {x:#x}"
            for kind, (c, x) in why.items()]


def check_audit(run):
    """Every claim of the build on every lane (reduction_audit's); the claims
    recorded pinned, so that a build that records none cannot pass."""
    b = run.b
    out = []
    got = (len(b.meta.get("exact", ())), len(b.meta.get("data", ())))
    if got != CLAIMS:
        out.append(f"audit: {got} claims recorded, not {CLAIMS}")
    if run.bad:
        x, fails = run.bad[0]
        out.append(f"audit: {len(run.bad)} of {len(run.rows)} lanes have a "
                   f"claim that fails, first {x:#x}: instruction {fails[0][0]} "
                   f"({fails[0][1]}, {fails[0][2]})")
    if run.tally.get("nonfinite") or run.tally.get("skipped"):
        out.append(f"audit: {run.tally}")
    return out


def check_cushion(run):
    """The overshoot of |r| past pi/4 measured on the lanes (2|t| - 1 at the
    most, check_reference's `over`) is within the build's computed bound, as
    the cushion proof recomputes it from the static magnitudes kept."""
    if not hasattr(run, "over"):
        check_reference(run)
    bound = ml._trig_slack_tw(run.b)
    if run.over > bound:
        return [f"cushion: the measured overshoot 2^{RT._log2(run.over):.2f} "
                f"is past the computed bound 2^{RT._log2(bound):.2f}"]
    return []


def check_constants(builder=None):
    return [f"constants: {s}" for s in
            ml.check_reduction_tw_constants(builder=builder)[1]]


# ---- the plan, the shape, the model ------------------------------------------

def test_the_plan_is_the_models_and_refuses_what_it_cannot_build():
    P = plan_tw()
    for k, v in dict(b=16, L=9, Z=3, K=18, nchunks=15, bits=240, bottom=-56,
                     budget=-97, delta=3, gm1_min=-3, gm1_max=6, shifts=10,
                     Emax=127, Egate=-14, bmid=-20, span_upper=33,
                     span_lower=36).items():
        assert getattr(P, k) == v, k
    assert [(j, round(a, 6), round(c, 6), g, rb, rg)
            for j, a, c, g, rb, rg in P.rows] == [
        (j, round(a, 6), round(c, 6), g, rb, rg) for j, a, c, g, rb, rg in ROWS]
    # plan_reduction_tw is plan_reduction(FP32, 40, b=16) and the groups
    Q = ml.plan_reduction(FMT, G, b=16)
    assert (Q.rows, Q.words, Q.chunks) == (P.rows, P.words, P.chunks)
    with pytest.raises(ValueError, match="no plan: the exact combination"):
        ml.plan_reduction(FMT, G)                 # M2G1's: refused by name
    with pytest.raises(ValueError, match="b = 17: the coarse sum is not exact"):
        ml.plan_reduction(FMT, G, b=17)
    for args, why in (((FP64,), "fp32's"), ((FMT, 18), "41 to 44 fail"),
                      ((FMT, 41), "lower group's proof")):
        with pytest.raises(ValueError, match=why):
            ml.plan_reduction_tw(*args)
    with pytest.raises(ValueError, match="whole range"):
        ml.plan_reduction_tw(R=8)


@pytest.mark.parametrize("rnd", sf.RND_MODES, ids=sf.RND_NAMES.get)
def test_the_build_is_the_models_under_every_attribute(rnd):
    b = build_tw(None, rnd)
    assert check_shape(b) == [] and check_digest(b) == []
    assert b.body == build_tw().body and b.words == build_tw().words
    assert b.result == b.probes["r0"] or b.result[0] == "v"
    assert b.meta["G"] == G and b.meta["R"] is None


def test_the_ports_lanes_are_the_models():
    b = build_tw()
    for x, *want in MODEL_LANES:
        got = [b.run(x, ("r0", "r1", "r2", "q", "small"))[2][k]
               for k in ("r0", "r1", "r2", "q", "small")]
        got[4] = int(bool(got[4] & 0x7fffffff))
        assert got == want, hex(x)


# ---- the switches --------------------------------------------------------------

def _front(P, fmt=FMT, **kw):
    b = ml.Build(fmt, sf.RND_RNE, "front")
    fr = ml.reduction_front(b, ("in", "a"), P, **kw)
    return b, fr


def test_with_the_switches_off_the_front_is_m2g1s():
    P = ml.plan_reduction(FP64, ml.GUARD["fp64"])
    b0, f0 = _front(P, FP64)
    b1, _ = _front(P, FP64, rho_half=False, late_from=None)
    assert (b0.body, b0.phase_of, b0.words) == (b1.body, b1.phase_of, b1.words)
    assert len(f0.prods) == P.L
    # a rho piece's bound is one binade tighter with rho_half, nothing else moves
    b2, f2 = _front(P, FP64, rho_half=True)
    assert (b2.body, b2.phase_of) == (b0.body, b0.phase_of)
    pairs = [(a[1], c[1]) for a, c in zip(f0.prods, f2.prods) if a and a[1]]
    assert pairs and all(c.mag == a.mag - 1 and c.ref == a.ref
                         for a, c in pairs)


def test_late_from_leaves_the_late_products_to_the_tail():
    P = plan_tw()
    b, fr = _front(P, late_from=4)
    assert len(fr.prods) == 4
    assert not any(ph == "red-products-low" for ph in b.phase_of)
    n = len(b.body)
    pr = fr.product(5, "red-products-low")
    assert len(b.body) > n and b.phase_of[-1] == "red-products-low"
    assert set(b.phase_of[n:]) == {"red-products-low"} and b.phase == "red-coarse"
    n = len(b.body)
    assert fr.product(5, "red-products-low") is pr and len(b.body) == n
    # the same positions early or late are the same instructions, in another order
    ball, _ = _front(P)
    assert len(ball.body) >= n
    for bad in (1, 0, True, "4", 2.5):
        with pytest.raises(ValueError, match="late_from"):
            _front(P, late_from=bad)


def test_the_looser_rho_bound_fails_the_lower_groups_proof_by_name():
    """rho_half off, the tail as the model has it: the lower group's low word
    plus a TwoSum error is not provably one word (the drafter's E5)."""
    P = plan_tw()
    b = ml.Build(FMT, sf.RND_RNE, "loose")
    R = ml._Red(b, P, None, rho_half=False, late_from=4)
    fr = ml._front(R, ("in", "a"))
    with pytest.raises(ValueError, match=r"static proof 'lower group: low word "
                       r"\+ TwoSum error exact' fails: lw \(mag -32.00, grid "
                       r"-52\) \+ e \(mag -43.91, grid -56\) is not provably "
                       r"one word"):
        ml._tail_tw(R, ("in", "a"), fr)
    # and with it the same tail builds
    b2 = ml.Build(FMT, sf.RND_RNE, "tight")
    R2 = ml._Red(b2, P, None, rho_half=True, late_from=4)
    ml._tail_tw(R2, ("in", "a"), ml._front(R2, ("in", "a")))
    assert len(b2.body) == sum(PHASES.values())


def _tail_at(G_):
    """The triple word's tail on the plan of guard G_ (b = 16, bmid = -20),
    which plan_reduction_tw() refuses: what the proofs make of it."""
    P = ml.plan_reduction(FMT, G_, b=16)
    P.bmid = -20
    b = ml.Build(FMT, sf.RND_RNE, "g")
    R = ml._Red(b, P, None, rho_half=True, late_from=4)
    ml._tail_tw(R, ("in", "a"), ml._front(R, ("in", "a")))
    return b


def test_g_36_to_40_build_and_41_to_44_fail_at_the_lower_groups_proof():
    """The model's tw32_guard.out.txt, again on the port: G = 40 is the last G
    the proofs hold at (parcel M2X: 36 to 40 build, 41 to 44 fail by name)."""
    for G_ in range(36, 41):
        assert _tail_at(G_).meta["overshoot"] < Fraction(1, 2 ** 10)
    for G_ in range(41, 45):
        with pytest.raises(ValueError, match=r"static proof 'lower group: low "
                           r"word \+ TwoSum error exact' fails: lw \(mag -33.00, "
                           r"grid -52\) \+ e \(mag -43.91, grid -%d\)" % (G_ + 16)):
            _tail_at(G_)


def test_m2g1s_tail_still_refuses_the_triple_plan_by_name():
    b = ml.Build(FMT, sf.RND_RNE, "dw")
    with pytest.raises(ValueError, match="the mid sum's low word is not exact"):
        ml.trig_reduction(b, ("in", "a"), ml.plan_reduction(FMT, G, b=16))


# ---- reference, audit, cushion -------------------------------------------------

def test_reference_audit_and_cushion_on_every_family():
    """r's error under the plan's bound with the model's worst figure as the
    ceiling, no quadrant off, `small` right, every claim holding, the
    overshoot under its bound: on a test-sized sample of each of the study's
    families, the products' binade edges, every binade's odd multiples of pi/4
    and the model's worst arguments."""
    stats = {}
    for fam in fams():
        run = clean_run(fam)
        assert check_reference(run, stats) == [], fam
        assert check_audit(run) == [], fam
        assert check_cushion(run) == [], fam
    assert stats["lanes"] > 2000
    assert stats["worst"] <= WORST_LOG2 + 0.005, stats["worst"]
    assert stats["worst"] >= WORST_LOG2 - 0.5        # the ceiling is near, not far
    assert f"{float(stats['over']):.3e}" == OVER_MEASURED   # the model's maximum
    # the bound itself: the model's, proved at the build and recomputed
    b = build_tw()
    assert float(b.meta["overshoot"]) == OVER
    assert ml._trig_slack_tw(b) == b.meta["overshoot"]
    assert float(stats["over"]) < OVER


def test_the_three_words_of_r_do_not_overlap_on_the_families():
    """MEASURED, not proved (the interface says so): |r1| <= ulp(r0)/2, |r2| <=
    ulp(r1)/2 and r0 = RN(r0 + r1 + r2) on every lane that is not `small`."""
    n = 0
    for fam in fams():
        for x, r0, r1, r2, q, small in clean_run(fam).rows:
            if small & 0x7fffffff:
                continue
            d0, d1, d2 = (ml._dec(FMT, w) for w in (r0, r1, r2))
            assert ml._enc(FMT, d0 + d1 + d2) == r0, hex(x)
            assert abs(d1) <= Fraction(2) ** ml._ulp_exp(abs(d0), P_BITS) / 2, hex(x)
            if d2:
                assert abs(d2) <= Fraction(2) ** ml._ulp_exp(abs(d1), P_BITS) / 2, hex(x)
            n += 1
    assert n > 2000


def test_the_reference_agrees_with_mpmath_on_the_models_lanes():
    """r against mpmath at 700 bits (the independent value of |x| - n pi/2 with
    n the integer of q's class nearest |x| 2/pi), and the header-based
    reference of the other checks against both."""
    import mpmath
    mpmath.mp.prec = 700
    frac = lambda q: mpmath.mpf(q.numerator) / q.denominator
    for x, r0, r1, r2, q, small in MODEL_LANES:
        if small:
            continue
        X = frac(abs(ml._dec(FMT, x)))
        n = q & 3
        m = n + 4 * int(mpmath.nint((X * 2 / mpmath.pi - n) / 4))
        r = X - m * mpmath.pi / 2
        rm = frac(sum(ml._dec(FMT, w) for w in (r0, r1, r2)))
        assert abs(rm - r) <= abs(r) * mpmath.mpf(2) ** -(P_BITS + G + 3), hex(x)
        _t, r_hdr, _T = RT.reference(FMT, x, n)
        assert abs(frac(r_hdr) - r) <= abs(r) * mpmath.mpf(2) ** -200, hex(x)


def test_the_cushion_is_proved_by_name_and_rho_is_an_exact_rational():
    b = build_tw()
    rho = b.meta["rho"]
    assert isinstance(rho, Fraction) and rho > ml._pi() / 4 * (1 + b.meta["overshoot"]) - Fraction(1, 2 ** 90)
    assert rho == ml._tw_upper(ml._pi() / 4 * (1 + b.meta["overshoot"]))
    assert Fraction(rho).denominator & (Fraction(rho).denominator - 1) == 0   # dyadic
    ml._check_trig_cushion_tw(b, rho)                          # no room to spare, still passes
    with pytest.raises(ValueError, match="the triple word's computed cushion past pi/4"):
        ml._check_trig_cushion_tw(b, ml.trig_rho())            # the study's 2^-30
    with pytest.raises(ValueError, match="2\\^-18.91"):
        ml._check_trig_cushion_tw(b, ml.trig_rho(19))
    # M2G1's formula is not this one: it accepts neither the build's meta
    with pytest.raises(KeyError):
        ml._trig_slack(b)
    # plan_trig takes the exact rational: M2F2's (K, D) of S and of C
    assert ml.plan_trig(FMT, G, rho) == ((7, 9), (8, 9))
    assert ml.plan_trig(FMT, G, ml.trig_rho()) == ((7, 9), (8, 9))


def test_the_proof_of_the_cushion_names_what_it_reads():
    """The computed bound is the formula of the tail's comment: 2^(1-p) (1 +
    2^(e+1)) + 4 (2^(bmid-1) + 2^lwl + the lows) + 2^-60, from the magnitudes
    kept in meta, so a build that keeps smaller ones has a smaller bound."""
    m = build_tw().meta["reduction_tw"]
    assert (m["bmid"], m["bottom"], m["lower"]) == (-20, -56, -21)
    over = ml._tw_overshoot(24, m["lower"], m["e"], m["lwl"], m["lows"])
    assert over == build_tw().meta["overshoot"]
    assert ml._tw_overshoot(24, m["lower"] - 8, m["e"], m["lwl"], m["lows"]) < over / 10


# ---- the plants -----------------------------------------------------------------

# MEASURED (the plant by check matrix of the parcel's ledger): every check a
# plant turns red, and the ones it leaves green. The cushion check reads the
# reference's lanes, so it follows a plant that breaks r; `digest` is the dag
# digest, red for every plant that changes the dataflow.
CHECKS = ("shape", "digest", "reference", "audit", "cushion", "constants")
PLANTED = [
    ("carry_dropped", ("audit", "reference", "digest"),
     ("shape", "cushion", "constants")),
    ("r2_dropped", ("reference", "shape", "digest"),
     ("audit", "cushion", "constants")),
    ("chunk", ("reference", "constants", "digest"), ("audit", "shape")),
    ("window", ("reference", "shape", "digest"), ("audit", "constants")),
    ("exact_add", ("audit", "reference", "digest"),
     ("shape", "cushion", "constants")),
    ("quadrant_dropped", ("reference", "audit", "shape", "digest"),
     ("constants",)),
    ("bucket_nearest", ("reference", "digest"), ("audit", "shape", "constants")),
    ("pio2_low", ("reference", "constants", "shape", "digest"),
     ("audit", "cushion")),
    ("claims_lost", ("audit", "shape"),
     ("reference", "digest", "cushion", "constants")),
    ("fast_as_two_sum", ("audit", "shape", "digest"),
     ("reference", "cushion", "constants")),
    ("lw_understated", ("cushion",),
     ("reference", "audit", "constants", "shape", "digest")),
]
# the lanes a plant needs: the least that shows it
LANES = {"carry_dropped": ("edges",), "exact_add": ("edges", "main"),
         "lw_understated": ("worst",), "chunk": ("main", "pio4"),
         "window": ("main", "pio4")}
# where a plant cannot act and is refused by name: it is neither red nor green
CANNOT_ACT = ("mid_inexact", "range_short", "split_unproved")


@functools.lru_cache(maxsize=None)
def planted_run(plant, fam):
    return run_lanes_tw(build_tw(plant), [x for k in fam for x in fams()[k]])


def _found(plant, checks):
    fam = LANES.get(plant, ("worst", "pio4", "quad"))
    b = build_tw(plant)
    out = {}
    if {"reference", "audit", "cushion"} & set(checks):
        run = planted_run(plant, tuple(fam))
        out["reference"] = check_reference(run)
        out["audit"] = check_audit(run)
        out["cushion"] = check_cushion(run)
    if "shape" in checks:
        out["shape"] = check_shape(b)
    if "digest" in checks:
        out["digest"] = check_digest(b)
    if "constants" in checks:
        out["constants"] = check_constants(
            builder=lambda fmt, **kw: build_tw(plant))
    return out


@pytest.mark.parametrize("row", PLANTED, ids=lambda r: r[0])
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(row):
    plant, red, green = row
    found = _found(plant, set(red) | set(green))
    for c in red:
        assert found[c], f"{plant}: {c} stays green"
        assert all(s.startswith(c + ": ") for s in found[c]), found[c][:2]
    for c in green:
        assert found[c] == [], f"{plant}: {c} is red: {found[c][:2]}"


def test_carry_dropped_is_red_in_the_audit_on_the_binade_edges_only():
    """The study's finding (10 failures in 1,867 lanes): the dropped carry
    shows only where a product sits next to a power of two. Both the audit and
    the reference of the random, bucket, power-of-two, pool and quadrant
    arguments stay green; on the products' binade edges the same lanes turn
    both red."""
    b = build_tw("carry_dropped")
    edges = planted_run("carry_dropped", ("edges",))
    assert 0 < len(edges.bad) < len(edges.rows) // 10
    main = run_lanes_tw(b, fams()["main"] + fams()["quad"])
    assert main.bad == [] and check_audit(main) == []
    assert check_reference(main) == []
    assert any("r off by more than" in s for s in check_reference(edges))


def test_the_plants_that_cannot_act_are_refused_by_name():
    for plant in CANNOT_ACT:
        with pytest.raises(ValueError, match=f"plant '{plant}' does not apply at "
                           "fp32 .G = 40, R = None.: the fault is not reached"):
            ml.build_reduction(FMT, plant=plant)
    for plant in ml.TRIG_TW_PLANTS:
        with pytest.raises(ValueError, match=f"plant '{plant}' does not apply "
                           "at fp64"):
            ml.build_reduction(FP64, plant=plant)
        with pytest.raises(ValueError, match="does not apply at fp32 .G = 18"):
            ml.build_reduction(FMT, G=18, plant=plant)
    with pytest.raises(ValueError, match="unknown plant"):
        ml.build_reduction(FMT, plant="nope")


def test_every_plant_is_in_the_table_or_refused_and_changes_the_build():
    names = [r[0] for r in PLANTED]
    assert sorted(names + list(CANNOT_ACT)) == sorted(
        list(ml.REDUCTION_PLANTS) + list(ml.TRIG_TW_PLANTS))
    clean = build_tw()
    for plant in names:
        b = build_tw(plant)
        assert (b.body, b.words, b.meta.get("exact"), b.meta["overshoot"]) \
            != (clean.body, clean.words, clean.meta.get("exact"),
                clean.meta["overshoot"]), plant


# ---- the constants ----------------------------------------------------------------

def test_the_constants_hold_and_each_leg_can_fail_alone():
    lines, findings = ml.check_reduction_tw_constants()
    assert findings == [] and len(lines) == 1
    b = build_tw()
    P = b.meta["reduction"]
    assert set(b.roles) == ({"MAGIC", "MQ", "MQ_MID", "INVB", "FLOOROFF", "PIO2_0",
                             "PIO2_1", "PIO2_2", "PIO4D"}
                            | {f"CHUNK{k}" for k in range(P.nchunks)})
    assert (P.nchunks, P.K, P.Z) == (15, 18, 3)       # 18 words: 3 zero, 15 chunks

    def with_word(role, delta=1):
        c = ml.build_reduction(FMT)
        c.words[c.roles[role][1]] = (c.words[c.roles[role][1]] + delta) & 0xffffffff
        return c
    for role in ("MQ", "MQ_MID", "PIO2_0", "PIO2_1", "PIO2_2", "PIO4D", "MAGIC",
                 "INVB", "FLOOROFF", "CHUNK0", "CHUNK7", "CHUNK14"):
        found = check_constants(builder=lambda fmt, r=role: with_word(r))
        assert found and any(role in s for s in found), (role, found)
    # the carry's magic must be the word MQ_MID
    c = ml.build_reduction(FMT)
    c.meta["reduction_tw"]["carry_magic"] = c.roles["MQ"]
    assert any("carry's magic" in s for s in check_constants(builder=lambda fmt: c))
    # a different constant derived through a shifted pi is a difference too
    orig = ml._check_pi

    def shifted(bits):
        lo, hi = orig(bits)
        eps = Fraction(1, 2 ** 100)
        return lo + eps, hi + eps
    ml._check_pi = shifted
    try:
        assert check_constants()
    finally:
        ml._check_pi = orig


def test_the_check_runs_as_a_program_and_prints_its_line_only_when_asked():
    run = lambda *a: subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib", *a],
                                    cwd=PYTHON_DIR, capture_output=True, text=True)
    done = run("--check", "--only", "reduction-tw")
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == \
        "mathlib --check (reduction, triple word): 1 formats, 0 differences"
    assert "reduction fp32 (triple word): G = 40, b = 16, L = 9, 15 chunks" in done.stdout
    assert "routines" not in done.stdout
    listing = run("--only", "reduction-tw")
    assert listing.returncode == 0 and "319 instructions by phase" in listing.stdout
    assert run("--check", "--only", "sqrt2").returncode == 2


def test_the_default_check_shows_the_triple_words_differences_and_no_line(
        monkeypatch, capsys):
    monkeypatch.setattr(ml, "check_constants", lambda **kw: (["six"], []))
    monkeypatch.setattr(ml, "check_reduction_constants", lambda **kw: (["red"], []))
    monkeypatch.setattr(ml, "check_trig_constants", lambda **kw: (["trig"], []))
    monkeypatch.setattr(ml, "check_reduction_tw_constants", lambda **kw: (["tw line"], []))
    assert ml.main(["--check"]) == 0
    assert "tw line" not in capsys.readouterr().out
    monkeypatch.setattr(ml, "check_reduction_tw_constants",
                        lambda **kw: (["tw line"], ["PIO2_2: wrong"]))
    assert ml.main(["--check"]) == 1
    assert "DIFFERENCE: PIO2_2: wrong" in capsys.readouterr().out


# ---- the interface -----------------------------------------------------------------

def test_the_interface_is_public_and_documented():
    for n in ("plan_reduction_tw", "trig_reduction_tw", "TRIG_TW_PLANTS",
              "check_reduction_tw_constants"):
        assert n in ml.__all__, n
    for fn in (ml.plan_reduction_tw, ml.trig_reduction_tw, ml.reduction_front,
               ml.check_reduction_tw_constants, ml.build_reduction):
        assert fn.__doc__ and len(fn.__doc__) > 400, fn.__name__
    doc = ml.trig_reduction_tw.__doc__.lower()
    for word in ("r0", "r1", "r2", "inrange", "ax", "small", "hash-conse",
                 "rho", "overshoot", "reduction_tw", "red-products-low",
                 "red-triple", "trig_tw_plants", "plan_trig", "2^-18.91",
                 "24, not 23"):
        assert word in doc, word
    doc = ml.reduction_front.__doc__.lower()
    for word in ("rho_half", "late_from", "product(j"):
        assert word in doc, word
    assert set(ml.TRIG_TW_PLANTS) == {"carry_dropped", "r2_dropped"}
    # the result's names, and the value red-small leaves
    b = build_tw()
    out = types.SimpleNamespace(**{k: b.probes[k] for k in
                                   ("r0", "r1", "r2", "q", "small", "ax")})
    assert b.body[out.ax[1]][0] == sf.OP_IAND and b.phase_of[out.ax[1]] == "red-small"
    assert b.words[b.body[out.ax[1]][2][1][1]] == FMT.sign_mask ^ ((1 << 32) - 1)
    assert b.result == b.probes["r0"] and b.flags == b.probes["q"]


def test_build_reduction_at_g_18_is_still_the_double_words():
    assert ml.GUARD["fp32"] == 40
    b = ml.build_reduction(FMT, G=18)
    assert b.meta["reduction"].b == 15 and "reduction_tw" not in b.meta
    assert b.result == b.probes["rh"]
    t = ml.build_reduction(FMT)
    assert t.meta["reduction"].b == 16 and t.result == t.probes["r0"]


def test_the_runs_command_runs_at_small_sizes():
    import mathlib_runs as runs
    done = subprocess.run([sys.executable, "-B", str(pathlib.Path(runs.__file__)),
                           "reduction-tw", "--quick"], cwd=PYTHON_DIR,
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "reduction fp32 (triple word): G = 40" in done.stdout
    assert "quadrant off 0" in done.stdout and "audit failures 0" in done.stdout
