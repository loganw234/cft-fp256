# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The trigonometric reduction of python/cft_golden/mathlib.py (parcel M2G1,
M2's build, wave 1), held to the study's section 8, items 2, 6 and 7, and its
plants (docs/studies/M2-trig.md): quick enough for the golden stage; the larger
runs are `python python/tests/mathlib_runs.py reduction`.

A CHECK returns FINDINGS: a list of strings, each beginning with the check's
name and a colon, empty when it holds (mathlib_harness's convention). Eight:

  reference   (r, n mod 4) of every lane against |x| 2/pi in exact rationals,
              with 2/pi read from host/src/mp_2opi.h, not from the generator:
              r's relative error at most 2^-(p+G+3), |r| <= pi/4 (1 + 2^-30)
              (2^-11 at fp32), rh = RN(rh + rl), and `small` exactly where
              |x| < RD(pi/4)
  cushion     that cushion past pi/4 proven from the build's static bounds
              (the third quadrant count does not see the mid sum's low word),
              pinned, and held to the lanes: none overshoots the bound
  audit       every instruction the build claims exact, on every lane, by
              reduction_audit(); the number of claims pinned per format, so
              that a build that records none cannot pass
  setup       every biased exponent from 2^Egate to 2^Emax: g - 1, sigma,
              2^sigma, 2^-sigma, m, 1/m and M, exactly
  proofs      the plan's fields, the static bounds of every position, and each
              refusal by name: fp32 at G = 40, a b whose coarse sum is not
              exact, fp32 at G = 16, 20, 22 and 30
  range       fp128 and fp256: 2^R's predecessor reduced right and in range,
              2^R and the largest finite out of range; fp64: no range, its
              largest finite reduced right
  constants   mathlib.check_reduction_constants() (every word by role against
              Machin's formula in integers and the header), in process and as
              `python -m cft_golden.mathlib --check --only reduction`
  shape       the instructions by phase pinned to the study's table

The arguments are redcheck.py's at its final N (docs/studies/m2/, whose
runs are the study's): random over the range, each bucket's edge exponents,
every power of two (every 7th at fp128 and fp256), the pools' deepest
cancellations; the products' binade edges (m2edges.py); and the arguments the
study did not have: fp128's deepest, at value exponent 909, fp256's, and the
neighbours of RD(pi/4). Nothing here imports the study's model.

And for every check a planted fault shown red in it, by name, and the control
green in all (mathlib.REDUCTION_PLANTS, and one fault of the independent
derivation): the last section.
"""

import functools
import math
import pathlib
import random
import subprocess
import sys
import types
from collections import Counter
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, vectors  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_harness as H  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
RNE, RDN = sf.RND_RNE, sf.RND_RDN
DOUBLE = (FP64, FP128, FP256)
BY_NAME = {f.name: f for f in (FP32, FP64, FP128, FP256)}
G_OF = dict(ml.GUARD, fp32=18)           # fp32 at the double word's fallback


# ---- what the study states, and the model measured (READ) --------------------
#
# The plan's fields (the study's 2.2 and 2.3; redcheck.fp64, fp128 and
# fp256.out.txt's first lines): 28 chunks of 44 bits (1,232 bits, 30 words
# with the two zero ones, a shifter of 5 levels) at fp64, 13 of 108 (15 words, 4
# levels) at fp128, 8 of 233 (10 words, 3 levels) at fp256.
PLAN = {
    "fp64": dict(b=44, L=6, Z=2, K=30, nchunks=28, bits=1232, bottom=-63,
                 budget=-162, delta=3, gm1_min=-2, gm1_max=22, shifts=25,
                 Emax=1023, Egate=-28),
    "fp128": dict(b=108, L=5, Z=2, K=15, nchunks=13, bits=1404, bottom=-67,
                  budget=-286, delta=3, gm1_min=-2, gm1_max=8, shifts=11,
                  Emax=1023, Egate=-58),
    "fp256": dict(b=233, L=5, Z=2, K=10, nchunks=8, bits=1864, bottom=-65,
                  budget=-532, delta=3, gm1_min=-2, gm1_max=3, shifts=6,
                  Emax=1023, Egate=-120),
}
# fp32 at G = 18, the double word's fallback (fp32_guard.out.txt, line 2):
# b 15, L 8, bottom -34, budget -75, 17 words.
PLAN32 = dict(b=15, L=8, Z=3, K=17, nchunks=14, bits=210, bottom=-34,
              budget=-75, delta=3, gm1_min=-3, gm1_max=6, shifts=10,
              Emax=127, Egate=-14)
# The instructions by part (the study's 2.2 table, MEASURED by its costs.py and
# again by redcheck.py: 206, 168 and 155), and the one more that is the range
# compare, in the phase "classify", where there is a range.
PHASES = {
    "fp64": {"red-setup": 18, "red-window": 61, "red-products": 21,
             "red-coarse": 18, "red-mid": 36, "red-lower": 33,
             "red-scale": 14, "red-small": 5},
    "fp128": {"red-setup": 18, "red-window": 35, "red-products": 17,
              "red-coarse": 18, "red-mid": 28, "red-lower": 33,
              "red-scale": 14, "red-small": 5, "classify": 1},
    "fp256": {"red-setup": 18, "red-window": 22, "red-products": 17,
              "red-coarse": 18, "red-mid": 28, "red-lower": 33,
              "red-scale": 14, "red-small": 5, "classify": 1},
}
TOTALS = {"fp64": 206, "fp128": 168, "fp256": 155}
# The claims a build records (Build.meta["exact"], ["data"]): the model's,
# counted (redcheck.fp64, fp128 and fp256.out.txt print the sets).
CLAIMS = {"fp64": (42, 10), "fp128": (38, 10), "fp256": (38, 10),
          "fp32": (48, 10)}
# The cushion past pi/4 (the contract, trig_reduction's docstring):
# |r| <= pi/4 (1 + 2^-30) at fp64, fp128 and fp256 and pi/4 (1 + 2^-11) at fp32
# (G = 18). The quadrant count is taken from the high word of the exact sum
# alone, and what it does not see - the mid sum's low word, the pieces below
# the bottom, the rounding of the sum - is bounded by the generator's own
# static bounds: quadrant_slack().
CUSHION = {"fp32": 11}
# The arguments of redcheck.py at its final N (queue7.log:83 to 88) and the
# products' binade edges: the study's 2.2 table.
N_RANDOM = {"fp64": 400, "fp128": 400, "fp256": 200, "fp32": 100}
HALVES_STEP = {"fp32": 1, "fp64": 16, "fp128": 64, "fp256": 64}
N_ARGS = {"fp64": (3853, 1844), "fp128": (676, 632), "fp256": (434, 302)}
# What a stated range costs (the study's 2.3 tables, READ): R -> (words stored,
# chunks, b, the shifter's levels) at fp128 and fp256.
RANGES = {
    "fp128": {128: (7, 5, 109, 2), 256: (8, 6, 109, 2), 512: (10, 8, 108, 3),
              1024: (15, 13, 108, 4)},
    "fp256": {128: (6, 4, 233, 1), 256: (7, 5, 233, 2), 512: (8, 6, 233, 2),
              1024: (10, 8, 233, 3)},
}
# The static bounds of every position (the model's analyse(), rounded to 1e-6):
# (j, log2 Tmin, log2 Tmax, P's grid, rho's bound, rho's grid).
ROWS = {
    "fp64": [(0, 91.28037, 96.958459, 39, 44, 0),
             (1, 47.28037, 52.958459, -5, 0, -44),
             (2, 3.28037, 8.958459, -49, -44, -88),
             (3, -40.71963, -35.041541, -93, -88, -132),
             (4, -84.940647, -79.041541, -137, -132, -176),
             (5, -128.940647, -123.041541, -181, -176, -220)],
    "fp128": [(0, 217.314447, 220.425174, 105, 108, 0),
              (1, 109.314447, 112.425174, -3, 0, -108),
              (2, 1.314447, 4.872963, -111, -108, -216),
              (3, -106.685553, -103.127037, -219, -216, -324),
              (4, -214.685553, -211.127037, -327, -324, -432)],
    "fp256": [(0, 467.901374, 469.761545, 231, 233, 0),
              (1, 234.901374, 236.845457, -2, 0, -233),
              (2, 1.672916, 3.845457, -235, -233, -466),
              (3, -233.98755, -229.154543, -470, -466, -699),
              (4, -466.98755, -462.102438, -703, -699, -932)],
    "fp32": [(0, 35.876325, 38.597762, 12, 15, 0),
             (1, 20.876325, 23.597762, -3, 0, -15),
             (2, 5.876325, 8.597762, -18, -15, -30),
             (3, -9.123675, -6.402238, -33, -30, -45),
             (4, -24.123675, -21.402238, -48, -45, -60),
             (5, -39.123675, -36.408653, -63, -60, -75),
             (6, -57.958341, -51.408653, -81, -75, -90),
             (7, -72.958341, -66.077927, -96, -90, -105)],
}
PHASES["fp32"] = {"red-setup": 18, "red-window": 47, "red-products": 29,
                  "red-coarse": 18, "red-mid": 44, "red-lower": 41,
                  "red-scale": 14, "red-small": 5}


# ---- the exact reference, from the header ------------------------------------

@functools.lru_cache(maxsize=None)
def header():
    """(2/pi 2^bits truncated toward zero as an integer, bits) from
    host/src/mp_2opi.h: a BIT STREAM of 32-bit words, most significant first
    (a copy of test_mp_consts._parse_2opi, without its checksum)."""
    text = (ROOT / "host" / "src" / "mp_2opi.h").read_text()
    bits = int(text.split("#define CFT_TWO_OVER_PI_BITS")[1].split()[0])
    body = text.split("cft_two_over_pi[CFT_TWO_OVER_PI_WORDS] = {")[1]
    vals = [int(tok[2:10], 16) for tok in
            body.split("};")[0].replace(",", " ").split()
            if tok.startswith("0x")]
    assert len(vals) * 32 == bits
    v = 0
    for w in vals:
        v = (v << 32) | w
    return v, bits


@functools.lru_cache(maxsize=None)
def _two_opi(nbits):
    """2/pi to nbits bits as a Fraction, truncated toward zero, from the
    header."""
    v, bits = header()
    return Fraction(v >> (bits - nbits), 1 << nbits)


def reference(fmt, x, nmod4):
    """(t, r, T): for the argument x (its sign ignored) and the claimed
    quadrant n mod 4, t = |x| 2/pi - m with m the integer of n's class mod 4
    that leaves t in (-2, 2], r = t / T = |x| - m/T: |x| - m pi/2 with pi/2
    taken as 1/T, T the header's 2/pi to e + 2p + 400 bits (an error of
    2^-(2p + 399) of |x| at most, far below the bound). Exact rationals."""
    X = abs(ml._dec(fmt, x))
    e = max(0, X.numerator.bit_length() - X.denominator.bit_length())
    T = _two_opi(e + 2 * fmt.prec + 400)
    Pv = X * T
    k = Pv.numerator // Pv.denominator
    t = Pv - k + ((k - nmod4) % 4)
    if t > 2:
        t -= 4
    return t, t / T, T


def _log2(fr):
    return math.log2(fr.numerator) - math.log2(fr.denominator) if fr else -math.inf


# ---- the arguments -----------------------------------------------------------

def _enc(fmt, sign, m, e):
    return sf.round_pack(fmt, sign, m, e, RNE)[0]


def redcheck_args(fmt, P, n, seed=7):
    """redcheck.py's arguments (docs/studies/m2/): ([random], [bucket edges],
    [powers of two], [the pools]) in its order, so that their concatenation is
    its list. Random over the range (exponent uniform, significand random,
    both signs); each bucket's two edge exponents with the least, the greatest
    and a random significand; every power of two the range holds (every 7th at
    fp128 and fp256); the pools of host/tests/transcend_check.py's
    radian_pool and vectors.radian_unary_pool inside the range."""
    rng = random.Random(seed)
    p = fmt.prec
    rand, buckets, pow2, pool = [], [], [], []
    for _ in range(n):
        E = rng.randint(P.Egate, P.Emax)
        m = rng.getrandbits(p - 1) | (1 << (p - 1))
        rand.append(_enc(fmt, rng.getrandbits(1), m, E - p + 1))
    for gm1 in range(P.gm1_min, P.gm1_max + 1):
        for G0 in (gm1 * P.b, gm1 * P.b + P.b - 1):
            E = G0 + p + 1
            if P.Egate <= E <= P.Emax:
                for m in ((1 << (p - 1)), (1 << p) - 1,
                          rng.getrandbits(p - 1) | (1 << (p - 1))):
                    buckets.append(_enc(fmt, 0, m, E - p + 1))
    step = 1 if fmt.width <= 64 else 7
    for E in range(P.Egate, P.Emax + 1, step):
        pow2.append(_enc(fmt, 0, 1 << (p - 1), E - p + 1))
    tc = H._transcend_check()
    t = 64 if fmt.width <= 64 else 16
    found = set(tc.radian_pool(fmt, t, 5)) | set(vectors.radian_unary_pool(fmt, 24, 14))
    lim = ml._enc(fmt, Fraction(2) ** (P.Emax + 1))
    lo = ml._enc(fmt, Fraction(2) ** P.Egate)
    for bits in found:
        ax = bits & ~fmt.sign_mask
        u = sf.unpack(fmt, bits)
        if u.kind not in (sf.ZERO, sf.INF, sf.NAN) and lo <= ax < lim:
            pool.append(bits)
    return rand, buckets, pow2, pool


def edge_args(fmt, P, ms_around=(-2, -1, 0, 1)):
    """The products' binade edges (docs/studies/m2/m2edges.py, the study's
    2.2): the generator's static proofs bound each piece by the extremes of
    its product T_j = M c 2^-(jb), and a sum they call exact is nearest to
    failing where a product sits next to a power of two. For every bucket and
    every position whose chunk c is nonzero, the significands M around
    M0 = ceil(2^K / c), 2^K the power of two inside [2^(p-1) c, 2^p c), and the
    two ends, at three exponents of the bucket; positive."""
    p = fmt.prec
    lo, hi = 1 << (p - 1), (1 << p) - 1
    out = set()
    for gm1 in range(P.gm1_min, P.gm1_max + 1):
        Ms = {lo, hi}
        for j in range(P.L):
            k = gm1 + j
            if k < 0 or k >= len(P.chunks) or P.chunks[k] == 0:
                continue
            c = P.chunks[k]
            K = (p - 1) + c.bit_length()
            if c & (c - 1) == 0:          # a power of two: the edge is the low end
                K -= 1
            M0 = -((-(1 << K)) // c)       # ceil(2^K / c)
            for d in ms_around:
                if lo <= M0 + d <= hi:
                    Ms.add(M0 + d)
        for i in (0, P.b // 2, P.b - 1):
            E = gm1 * P.b + i + p + 1      # G0 = E - p - 1 = gm1 b + i
            if not (P.Egate <= E <= P.Emax):
                continue
            for M in Ms:
                out.add(_enc(fmt, 0, M, E - p + 1))
    return sorted(out)


# The deepest cancellations over the stated range (the study's 1.4, worst_range
# .fp128.out.txt and .fp256.out.txt, MEASURED by pi_worstcase's own search over
# every binade of [1, 2^1024)): value exponent and significand.
DEEP = {"fp128": (909, 0x12f1e98468cc75b82b4a8dea8d346),
        "fp256": (239, 0x1dd71d552efac6c6246fb9a1e5680e751b9e3f84e2a77bbc0298a0f4b498)}


def deep_args(fmt, neighbours=(-2, -1, 0, 1, 2)):
    """fp128's argument of 123 bits lost (value exponent 909) and fp256's of
    244 (239), with their neighbours: the pools hold neither (a sampled search
    misses 909). Empty at fp32 and fp64, whose deepest the pools hold."""
    if fmt.name not in DEEP:
        return []
    v, m = DEEP[fmt.name]
    base = _enc(fmt, 0, m, v - fmt.prec + 1)
    return [base + d for d in neighbours]


def near_pio4(fmt):
    """RD(pi/4) and its neighbours either side: where `small` ends."""
    c = ml._enc(fmt, ml._pi() / 4, RDN)
    return [c + d for d in (-2, -1, 0, 1, 2)]


def half_args(fmt, P, step=16):
    """The floats next to an odd multiple of pi/4 in every `step`-th binade
    (and two ulps either side): where x 2/pi is a half-integer and the
    quadrant count n is decided by a tie or by the last bit. The multiple is
    placed with the generator's pi, which the check does not use."""
    out = []
    quarter = ml._pi() / 4
    for E in range(max(P.Egate, -1), P.Emax + 1, step):
        k = max(0, math.floor((Fraction(2) ** E * Fraction(13, 10) / quarter
                               - 1) / 2))
        c = ml._enc(fmt, (2 * k + 1) * quarter)
        out += [c + d for d in (-2, -1, 0, 1, 2)]
    return out


@functools.lru_cache(maxsize=None)
def plan_of(name):
    return ml.plan_reduction(BY_NAME[name], G_OF[name])


@functools.lru_cache(maxsize=None)
def families(name):
    """{"random", "buckets", "pow2", "pool", "edges", "deep", "pio4"}: the
    arguments of each format, as tuples."""
    fmt = BY_NAME[name]
    P = plan_of(name)
    rand, buckets, pow2, pool = redcheck_args(fmt, P, N_RANDOM[name])
    return {"random": tuple(rand), "buckets": tuple(buckets),
            "pow2": tuple(pow2), "pool": tuple(pool),
            "edges": tuple(edge_args(fmt, P)), "deep": tuple(deep_args(fmt)),
            "pio4": tuple(near_pio4(fmt)),
            "halves": tuple(half_args(fmt, P, HALVES_STEP[name]))}


def main_args(name):
    f = families(name)
    return f["random"] + f["buckets"] + f["pow2"] + f["pool"]


# ---- the lanes ---------------------------------------------------------------

def run_lanes(b, xs, audit=True):
    """Each lane of `xs` through the build's unpruned body once: its rows
    (x, rh, rl, q, small, inrange) and, when `audit`, the claims that fail
    (reduction_audit's, from the same values) and the audit's tally."""
    fmt, pr = b.fmt, b.probes
    rows, bad, tally = [], [], {}
    for x in xs:
        vals = ml._values(fmt, b.body, b.words, x)
        get = ml._getter(vals, b.words, x)
        rows.append((x, get(b.result), get(pr["rl"]), get(b.flags),
                     get(pr["small"]),
                     get(pr["inrange"]) if "inrange" in pr else None))
        if audit:
            fails = ml._audit_values(b, x, vals, tally)
            if fails:
                bad.append((x, fails))
    return types.SimpleNamespace(b=b, rows=rows, bad=bad, tally=tally,
                                 audited=audit)


# ---- the checks --------------------------------------------------------------

def check_reference(run, stats=None):
    """(r, n mod 4) of every lane against |x| 2/pi in exact rationals, 2/pi
    from the header: |r - (|x| - n pi/2)| <= 2^-(p+G+3) |r|, |r| <= pi/4
    (1 + 2^-30) - at fp32, G = 18, (1 + 2^-22): CUSHION - rh = RN(rh + rl),
    and `small` nonzero exactly where |x| < RD(pi/4). `stats`, a dict, gains
    "worst" (log2 of the largest error in units of 2^-(p+G)), "over" (the
    largest 2|t| - 1, as a rational: how far past pi/4 |r| went) and
    "lanes"."""
    b = run.b
    fmt, p = b.fmt, b.fmt.prec
    G = b.meta["reduction"].G
    tol = Fraction(1, 2 ** (p + G + 3))
    size = (1 + Fraction(1, 2 ** CUSHION.get(fmt.name, 30))) / 2   # |t|
    magic = ml._enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    why = {}                                         # kind -> (count, first)

    def note(kind, x):
        c, first = why.get(kind, (0, None))
        why[kind] = (c + 1, first if first is not None else x)
    worst, over = -math.inf, Fraction(0)
    for x, rh, rl, q, small, _inr in run.rows:
        try:
            rm = ml._dec(fmt, rh) + ml._dec(fmt, rl)
        except ValueError:
            note("a non-finite r_h or r_l", x)
            continue
        t, r, T = reference(fmt, x, q & 3)
        over = max(over, 2 * abs(t) - 1)
        if abs(t) > size:
            note(f"a quadrant off (|r| past pi/4 (1 + 2^-"
                 f"{CUSHION.get(fmt.name, 30)}))", x)
            continue
        if r == 0 or abs(rm - r) > tol * abs(r):
            note("r off by more than 2^-(p+G+3) of itself", x)
        else:
            worst = max(worst, _log2(abs(rm - r) / abs(r)) + p + G)
        if ml._enc(fmt, rm) != rh:
            note("r_h not RN(r_h + r_l)", x)
        try:
            n = ml._dec(fmt, q) - Fraction(3, 2) * 2 ** (p - 1)
        except ValueError:
            n = None
        if n is None or n.denominator != 1 or n % 4 != q & 3:
            note("q not MAGIC + n, n an integer, with n mod 4 as q's low bits",
                 x)
        X = abs(ml._dec(fmt, x))
        if 2 * X * T < 1:
            up = ml._dec(fmt, sf.next_up(fmt, x & ~fmt.sign_mask)[0])
            want = 2 * up * T < 1
        else:
            want = False
        if bool(small) != want:
            note("`small` not where |x| < RD(pi/4)", x)
        elif small and (rh != x & ~fmt.sign_mask or rl != 0 or q != magic):
            note("a small lane not r = |x|, r_l = +0, q = MAGIC", x)
    if stats is not None:
        stats["worst"] = max(stats.get("worst", -math.inf), worst)
        stats["over"] = max(stats.get("over", Fraction(0)), over)
        stats["lanes"] = stats.get("lanes", 0) + len(run.rows)
    run.over = over
    return [f"reference: {c} lanes with {kind}, the first {x:#x}"
            for kind, (c, x) in why.items()]


def check_audit(run, pin=None):
    """Every claim of the build on every lane, by reduction_audit(); the
    claims recorded pinned (CLAIMS), so that a build that records none, and
    an audit of none, cannot pass."""
    b = run.b
    name = b.fmt.name
    pin = CLAIMS[name] if pin is None else pin
    got = (len(b.meta.get("exact", ())), len(b.meta.get("data", ())))
    out = []
    if got != pin:
        out.append(f"audit: {got[0]} exact and {got[1]} data claims recorded "
                   f"at {name}, {pin[0]} and {pin[1]} pinned")
    if not run.audited:
        out.append("audit: the lanes were not audited")
    elif run.rows and run.tally.get("claims", 0) != got[0] * len(run.rows):
        out.append(f"audit: {run.tally.get('claims', 0)} claims examined on "
                   f"{len(run.rows)} lanes, {got[0]} a lane recorded")
    if run.bad:
        x, fails = run.bad[0]
        out.append(f"audit: {len(run.bad)} lanes with a claim that fails, the "
                   f"first {x:#x}: {fails[:3]}")
    if run.tally.get("nonfinite"):
        out.append(f"audit: {run.tally['nonfinite']} claims on a non-finite "
                   f"value of a main lane")
    return out


def lane_probes(b, x, names):
    """The probes `names` on the lane x, through the instructions they need
    alone (their ancestors), not the whole body."""
    key = (id(b), tuple(names))
    cache = lane_probes.cache
    if key not in cache:
        need, stack = set(), [b.probes[n] for n in names
                              if b.probes[n][0] == "v"]
        while stack:
            v = stack.pop()
            if v not in need:
                need.add(v)
                stack.extend(s for s in b.body[v[1]][2] if s[0] == "v")
        cache[key] = (b, sorted(i for _v, i in need))
    keep = cache[key][1]
    vals = {}
    words = b.words

    def get(s):
        return vals[s[1]] if s[0] == "v" else x if s[0] == "in" else words[s[1]]
    for i in keep:
        op, r, srcs = b.body[i]
        ops = {"ra": 0, "rb": 0, "rc": 0}
        for s, fld in zip(srcs, ml.asm.OP_FIELDS[op]):
            ops[fld] = get(s)
        vals[i] = sf.compute(b.fmt, op, ops["ra"], ops["rb"], ops["rc"],
                             RNE if r is None else r)[0]
    return {n: get(b.probes[n]) for n in names}


lane_probes.cache = {}


def check_setup(b):
    """Every biased exponent from 2^Egate to 2^Emax, at the least and the
    greatest significand: g - 1 = floor((E - p - 1) / b), sigma = E - p - 1 + 2
    - b - (g - 1) b (in [2 - b, 1]), 2^sigma, 2^-sigma, m = 2^(2-sigma),
    1/m = 2^(sigma-2) and M, each exactly."""
    fmt, p = b.fmt, b.fmt.prec
    P = b.meta["reduction"]
    names = ("gm1", "sig", "V", "U", "m", "inv_m", "M")
    bad = Counter()
    first = {}
    for E in range(P.Egate, P.Emax + 1):
        for frac in (0, fmt.man_mask):
            x = ((E + fmt.bias) << fmt.man_w) | frac
            pr = lane_probes(b, x, names)
            g0 = E - p - 1
            gm1 = g0 // P.b
            sigma = g0 + 2 - P.b - gm1 * P.b
            want = {"gm1": Fraction(gm1), "sig": Fraction(sigma),
                    "V": Fraction(2) ** sigma, "U": Fraction(2) ** -sigma,
                    "m": Fraction(2) ** (2 - sigma),
                    "inv_m": Fraction(2) ** (sigma - 2),
                    "M": Fraction((1 << (p - 1)) | frac)}
            for n in names:
                try:
                    got = ml._dec(fmt, pr[n])
                except ValueError:
                    got = None
                if got != want[n]:
                    bad[n] += 1
                    first.setdefault(n, (E, got, want[n]))
            if not (2 - P.b <= sigma <= 1 and P.gm1_min <= gm1 <= P.gm1_max):
                bad["the plan's range"] += 1
                first.setdefault("the plan's range", (E, gm1, sigma))
    return [f"setup: {c} lanes with {n} wrong at {b.fmt.name}, the first "
            f"E = {first[n][0]}: {first[n][1]} for {first[n][2]}"
            for n, c in bad.items()]


def range_args(fmt, P):
    """[(what, bits, in range)] at the range's end: 2^R's predecessor, 2^R,
    its successor, the largest finite number, +inf and a quiet NaN. fp64 has
    no range: its largest finite number is the one lane (in range: None)."""
    if P.R is None:
        return [("the largest finite", sf.max_normal_bits(fmt), None)]
    top = ml._pow2(fmt, P.R)
    return [("2^R's predecessor", sf.next_down(fmt, top)[0], True),
            ("2^R", top, False),
            ("2^R's successor", sf.next_up(fmt, top)[0], False),
            ("the largest finite", sf.max_normal_bits(fmt), False),
            ("+inf", sf.inf_bits(fmt), False),
            ("a quiet NaN", sf.qnan_bits(fmt), False)]


def check_range(b):
    """The stated range. fp128 and fp256, to 2^1024: `inrange` nonzero
    exactly below 2^R, 2^R's predecessor reduced right (r, n mod 4 against
    the header; its claims hold), and 2^R, its successor, the largest finite
    number, +inf and a NaN out of range. fp64, the whole range: `inrange` is
    None, and the largest finite number is reduced right."""
    fmt = b.fmt
    P = b.meta["reduction"]
    out = []
    for what, x, inside in range_args(fmt, P):
        run = run_lanes(b, [x])
        inr = run.rows[0][5]
        if P.R is None:
            if inr is not None:
                out.append(f"range: {what} has an inrange word, where the "
                           f"range is the whole")
        elif bool(inr) != inside:
            out.append(f"range: {what} ({x:#x}) is "
                       f"{'in' if inr else 'out of'} range, want "
                       f"{'in' if inside else 'out of'} 2^{P.R}")
        if inside or inside is None:
            out += [f"range: {what} ({x:#x}): {f.split(': ', 1)[1]}"
                    for f in check_reference(run)]
            if run.bad:
                out.append(f"range: {what} ({x:#x}): a claim fails, "
                           f"{run.bad[0][1][:2]}")
    return out


# fp32 at the double word's guards (fp32_guard.out.txt: the plan, and the
# static proof that fails, or none): (G, the plan's fields, the refusal).
FP32_GUARD = [
    (16, dict(b=16, L=8, K=17, bottom=-32, budget=-73),
     "the split's magic is out of range"),
    (18, dict(b=15, L=8, K=17, bottom=-34, budget=-75), None),
    (20, dict(b=13, L=9, K=19, bottom=-36, budget=-77),
     "the mid sum's low word is not exact"),
    (22, dict(b=11, L=11, K=24, bottom=-38, budget=-79),
     "the mid sum's low word is not exact"),
    (30, dict(b=3, L=39, K=86, bottom=-46, budget=-87),
     "the split's magic is out of range"),
]


def check_proofs(planner=None, builder=None):
    """The plan's fields, the static bounds of every position, and the
    generator's refusals, each by name: fp32 at G = 40 (no plan), fp128 at a
    b of 109 (the coarse sum), fp32 at G = 20 and 22 (the mid sum's low word)
    and at G = 16 and 30 (the split's magic). `planner` is plan_reduction,
    `builder(fmt, **kw)` build_reduction, or faulted ones for a test."""
    planner = planner or ml.plan_reduction
    builder = builder or ml.build_reduction
    out = []

    def fields(P, want, tag):
        for k, v in want.items():
            if getattr(P, k) != v:
                out.append(f"proofs: {tag}: {k} is {getattr(P, k)!r}, "
                           f"pinned {v!r}")
        if P.words != [0] * P.Z + P.chunks or len(P.words) != P.K:
            out.append(f"proofs: {tag}: the table is not Z zero words and "
                       f"the chunks")
        if any(not 0 <= c < 1 << P.b for c in P.chunks):
            out.append(f"proofs: {tag}: a chunk is not a b-bit integer")

    def rows_of(P):
        return [tuple(None if v is None else round(v, 6) for v in r)
                for r in P.rows]

    def refuses(call, text, tag):
        try:
            call()
        except ValueError as e:
            if text not in str(e):
                out.append(f"proofs: {tag}: refused as {str(e)[:90]!r}, "
                           f"not as {text!r}")
        except Exception as e:                   # noqa: BLE001
            out.append(f"proofs: {tag}: {type(e).__name__}, not a "
                       f"ValueError naming {text!r}")
        else:
            out.append(f"proofs: {tag}: built, not refused as {text!r}")
    for name, want in PLAN.items():
        fmt = BY_NAME[name]
        P = planner(fmt, ml.GUARD[name])
        fields(P, want, name)
        if rows_of(P) != ROWS[name]:
            out.append(f"proofs: {name}: the static bounds of the positions "
                       f"are {rows_of(P)}, pinned {ROWS[name]}")
        if (P.R, P.fmt, P.G) != (ml.TRIG_RANGE[name], fmt, ml.GUARD[name]):
            out.append(f"proofs: {name}: R, fmt or G of the plan are off")
    P = planner(FP32, 18, R=None)
    fields(P, PLAN32, "fp32 at G = 18")
    if rows_of(P) != ROWS["fp32"]:
        out.append("proofs: fp32 at G = 18: the static bounds differ")
    # a range below the default is planned, and its table is the study's 2.3
    # (words, chunks, b, shifter levels); past it, refused
    for name, table in RANGES.items():
        for Rv, want in table.items():
            P = planner(BY_NAME[name], ml.GUARD[name], R=Rv)
            got = (P.K, P.nchunks, P.b, max(1, (P.shifts - 1).bit_length()))
            if got != want or P.Emax != Rv - 1:
                out.append(f"proofs: {name} to 2^{Rv}: (words, chunks, b, "
                           f"levels) {got}, the study's {want}")
    refuses(lambda: planner(FP128, 46, R=2048), "past 2^1024, the range",
            "fp128, R = 2048")
    refuses(lambda: planner(FP256, 46, R=None), "past 2^1024, the range",
            "fp256, the whole range")
    refuses(lambda: planner(FP64, 44, R=1024), "not a finite fp64 number",
            "fp64, R = 1024")
    refuses(lambda: planner(FP128, 46, R=0), "R = 0", "fp128, R = 0")
    # the refusals of the study's 2.7 and 3.6, item 2, and fp32_guard.py's
    refuses(lambda: planner(FP32, 40, R=None),
            "no plan: the exact combination needs b <= 2p + 1 + bottom = -7",
            "fp32 at G = 40")
    refuses(lambda: builder(FP32),
            "no plan: the exact combination needs b <= 2p + 1 + bottom = -7",
            "build_reduction(FP32), whose G is GUARD's 40")
    refuses(lambda: planner(FP128, 46, b=109),
            "b = 109: the coarse sum is not exact", "fp128 at b = 109")
    if planner(FP128, 46, b=108).b != 108:
        out.append("proofs: fp128 at b = 108 is not planned as given")
    for G, want, text in FP32_GUARD:
        fields(planner(FP32, G, R=None), want, f"fp32 at G = {G}")
        if text is None:
            if len(builder(FP32, G=G).body) != TOTALS32:
                out.append(f"proofs: fp32 at G = {G} is not {TOTALS32} "
                           f"instructions")
        else:
            refuses(lambda G=G: builder(FP32, G=G), text, f"fp32 at G = {G}")
    return out


def quadrant_slack(b):
    """log2 of the greatest 2|t| - 1 the build can leave: the third quadrant
    count rounds the high word s of the exact sum f_I + h2 and does not see
    its rounding error (at most 2^-p of U), the mid sum's low word lw and the
    pieces below the bottom, so |t| <= 1/2 + (|e| + |lw| + |lower|)/U and,
    with U >= 1/2 (sigma <= 1), 2|t| - 1 <= 2^(1-p) + 4 (|lw| + |lower|).
    From the static bounds the generator keeps (Build.meta["reduction_mid"])."""
    mid = b.meta["reduction_mid"]
    lw = 2.0 ** mid["lw"][0] if mid.get("lw") else 0.0
    return math.log2(2.0 ** (1 - b.fmt.prec) + 4 * (lw + 2.0 ** mid["lows"]))


def overshoot(run):
    """The greatest 2|t| - 1 over the lanes, exact: how far past pi/4 |r|
    went (0 where it never did). Kept on the run by check_reference()."""
    if not hasattr(run, "over"):
        fmt = run.b.fmt
        run.over = max([Fraction(0)] + [
            2 * abs(reference(fmt, x, q & 3)[0]) - 1
            for x, _rh, _rl, q, _s, _i in run.rows])
    return run.over


def check_cushion(run):
    """The cushion past pi/4, proven from the build's static bounds and held
    to the lanes: the computed bound on 2|t| - 1 (quadrant_slack) is within
    the stated cushion (CUSHION: 2^-30, 2^-11 at fp32) and is the pinned
    figure (SLACK), and no lane of the run overshoots by more than it."""
    b = run.b
    name = b.fmt.name
    slack = quadrant_slack(b)
    out = []
    if not slack <= -CUSHION.get(name, 30):
        out.append(f"cushion: {name}: the computed bound 2^{slack:.2f} is "
                   f"past the stated cushion 2^-{CUSHION.get(name, 30)}")
    if round(slack, 2) != SLACK[name]:
        out.append(f"cushion: {name}: the computed bound is 2^{slack:.2f}, "
                   f"pinned 2^{SLACK[name]}")
    over = overshoot(run)
    if over > 0 and _log2(over) > slack + 1e-9:
        out.append(f"cushion: {name}: a lane of the {len(run.rows)} "
                   f"overshoots pi/4 by 2^{_log2(over):.2f}, past the "
                   f"computed bound 2^{slack:.2f}")
    return out


def check_constants(builder=None, header=None, formats=DOUBLE):
    """mathlib.check_reduction_constants() in process: every word by role
    against Machin's formula in integers and the header, a difference by
    name."""
    _lines, findings = ml.check_reduction_constants(
        builder=builder, header=header, formats=formats)
    return [f"constants: {f}" for f in findings]


def check_shape(b):
    """The instructions by phase, pinned to the study's table."""
    name = b.fmt.name
    by = dict(Counter(b.phase_of))
    out = []
    if by != PHASES[name]:
        out.append(f"shape: instructions by phase {by}, pinned {PHASES[name]}")
    return out


# =====================================================================
# the control: every check on the clean builds
# =====================================================================

TOTALS32 = 216
INTERFACE = ("TRIG_RANGE", "TRIG_LOST", "trig_gates", "plan_reduction",
             "ReductionValue", "reduction_front", "trig_reduction",
             "reduction_audit", "build_reduction", "REDUCTION_PLANTS",
             "check_reduction_constants")
PLANT_NAMES = {"chunk", "window", "mid_inexact", "exact_add", "lw_understated",
               "quadrant_dropped", "bucket_nearest", "pio2_low", "claims_lost",
               "range_short", "split_unproved", "fast_as_two_sum"}
# r's largest error in units of 2^-(p+G), over redcheck's arguments and over
# the binade edges (the study's 2.2 table: 2^-7.90 and 2^-7.90, 2^-50.90 and
# 2^-56.43, 2^-189.59 and 2^-181.91).
# quadrant_slack(), COMPUTED: log2 of the greatest 2|t| - 1 each build can leave
SLACK = {"fp32": -11.66, "fp64": -33.04, "fp128": -64.0, "fp256": -62.0}
WORST = {"fp64": (-7.90, -7.90), "fp128": (-50.90, -56.43),
         "fp256": (-189.59, -181.91)}


@functools.lru_cache(maxsize=None)
def build_of(name, plant=None):
    return ml.build_reduction(BY_NAME[name], G=G_OF[name], plant=plant)


def test_the_interface_is_public_and_documented():
    for n in INTERFACE:
        assert n in ml.__all__, n
        obj = getattr(ml, n)
        if callable(obj):
            assert obj.__doc__ and len(obj.__doc__.split()) > 25, n
    assert ml.TRIG_RANGE == {"fp32": None, "fp64": None, "fp128": 1024,
                             "fp256": 1024}
    assert ml.TRIG_LOST == {"fp32": 29, "fp64": 61, "fp128": 123,
                            "fp256": 245}
    assert set(ml.REDUCTION_PLANTS) == PLANT_NAMES
    assert all(isinstance(t, str) and t for t in ml.REDUCTION_PLANTS.values())


def test_the_gates_are_the_definitions_tiny_gates():
    """transcend.py's rule: sin is tiny while 2 e + p + 2 <= 0, cos and tan
    while 2 e + p + 3 <= 0, e = floor(log2 |x|): the gate is one more than
    the greatest such e (the contract: -27, -57, -119; fp32 -12 and -13)."""
    want = {"fp64": (-27, -27), "fp128": (-57, -57), "fp256": (-119, -119),
            "fp32": (-12, -13)}
    for fmt in (FP32, FP64, FP128, FP256):
        p = fmt.prec
        gs = 1 + max(e for e in range(-400, 1) if 2 * e + p + 2 <= 0)
        gc = 1 + max(e for e in range(-400, 1) if 2 * e + p + 3 <= 0)
        assert ml.trig_gates(fmt) == (gs, gc) == want[fmt.name]


def test_plan_reduction_returns_the_fields_the_contract_names():
    fields = ("b", "L", "Z", "K", "nchunks", "bits", "bottom", "budget",
              "delta", "gm1_min", "gm1_max", "shifts", "chunks", "words",
              "rows", "Emax", "Egate")
    P = ml.plan_reduction(FP64, 44)
    assert isinstance(P, types.SimpleNamespace)
    assert all(hasattr(P, f) for f in fields)
    assert P.words[:P.Z] == [0] * P.Z and P.words[P.Z:] == P.chunks
    assert (P.R, P.G, P.fmt) == (None, 44, FP64)
    # R = "default" is TRIG_RANGE's; None is the whole range at fp32 and fp64
    assert ml.plan_reduction(FP64, 44, R=None).Emax == FP64.emax
    assert ml.plan_reduction(FP128, 46).Emax == 1023
    assert ml.plan_reduction(FP128, 46, R=1024).Emax == 1023


def test_proofs():
    assert check_proofs() == []


@pytest.mark.parametrize("name", ["fp64", "fp128", "fp256", "fp32"])
def test_shape(name):
    assert check_shape(build_of(name)) == []
    b = build_of(name)
    assert len(b.body) == sum(PHASES[name].values())
    if name != "fp32":
        assert len(b.body) - PHASES[name].get("classify", 0) == TOTALS[name]
    else:
        assert len(b.body) == TOTALS32


def test_the_phases_are_in_the_phase_order_after_reduce():
    order = ml.PHASE_ORDER
    reds = [p for p in order if p.startswith("red-")]
    assert reds == ["red-setup", "red-window", "red-products", "red-coarse",
                    "red-mid", "red-lower", "red-scale", "red-small"]
    i = order.index("reduce")
    assert order[i + 1:i + 1 + len(reds)] == tuple(reds)
    # the six's phases keep their order
    six = ("setup", "reduce", "lowword", "tail", "head", "head2", "head3",
           "Z", "lookup", "recon", "scale", "fixed-grid", "final",
           "classify", "special")
    assert tuple(p for p in order if not p.startswith("red-")) == six
    for name in ("fp64", "fp128", "fp256", "fp32"):
        assert set(build_of(name).phase_of) <= set(order)


@pytest.mark.parametrize("name", ["fp64", "fp128", "fp256", "fp32"])
def test_setup_on_every_exponent(name):
    assert check_setup(build_of(name)) == []


def _run(name, fams):
    f = families(name)
    return run_lanes(build_of(name), [x for k in fams for x in f[k]])


@pytest.mark.parametrize("name", ["fp64", "fp128", "fp256"])
def test_reference_and_audit_on_the_studys_arguments(name):
    """redcheck.py's arguments and the products' binade edges, at their final
    N: the study's counts, r's largest error as the study measured it, no
    quadrant off, no claim failing; and the arguments the study did not have,
    the deepest cancellations and RD(pi/4)'s neighbours."""
    f = families(name)
    assert (len(main_args(name)), len(f["edges"])) == N_ARGS[name]
    for lanes, worst in ((main_args(name), WORST[name][0]),
                         (f["edges"], WORST[name][1])):
        stats = {}
        run = run_lanes(build_of(name), lanes)
        assert check_reference(run, stats) == []
        assert check_audit(run) == []
        assert run.tally["nonfinite"] == run.tally["skipped"] == 0
        assert round(stats["worst"], 2) == worst, (stats, worst)
    run = _run(name, ("deep", "pio4", "halves"))
    assert check_reference(run) == [] and check_audit(run) == []
    assert check_cushion(run) == []
    if name in DEEP:
        # the deep argument is deep: the reduced fraction has TRIG_LOST bits
        # of leading zeros (the study's 1.4)
        x = f["deep"][2]
        q = run.rows[2][3]
        t, _r, _T = reference(BY_NAME[name], x, q & 3)
        lost = ml.TRIG_LOST[name]
        assert lost - 2 <= -_log2(abs(t)) <= lost + 1, _log2(abs(t))


def test_fp32_at_the_fallback_guard_is_reduced_right():
    """fp32 at G = 18 once, so that M2F can call the reduction unchanged if
    the double word is taken."""
    b = build_of("fp32")
    f = families("fp32")
    run = run_lanes(b, list(main_args("fp32")) + list(f["edges"])
                    + list(f["pio4"]) + list(f["halves"]))
    assert check_reference(run) == []
    assert check_audit(run) == []
    assert check_cushion(run) == []
    # the cushion at fp32 is 2^-11, not the wide formats' 2^-30: the floats
    # next to the odd multiples of pi/4 pass pi/4 by 2^-17.09 (0x44264edd:
    # n = 424 where 423 is the nearest integer) and 2^-25.10 (0x3f490fdb)
    assert round(_log2(run.over), 2) == -17.09
    row = next(r for r in run.rows if r[0] == 0x44264edd)
    assert row[3] & 3 == 0 and 423 % 4 == 3
    assert (b.meta["reduction"].b, b.meta["reduction"].L) == (15, 8)


@pytest.mark.parametrize("name", ["fp64", "fp128", "fp256"])
def test_range(name):
    assert check_range(build_of(name)) == []


def test_the_range_is_the_stated_one():
    """fp128 and fp256 to 2^1024, fp64 the whole range (the contract)."""
    for name, R in (("fp128", 1024), ("fp256", 1024), ("fp64", None)):
        b = build_of(name)
        assert b.meta["reduction"].R == R
        assert ("inrange" in b.probes) == (R is not None)
        assert ("RANGE" in b.roles) == (R is not None)


@pytest.mark.parametrize("name,R,empty", [("fp256", 128, True),
                                          ("fp128", 128, False),
                                          ("fp128", 512, False)])
def test_a_smaller_range_is_reduced_right_and_position_0_may_have_no_chunk(
        name, R, empty):
    """The study's 3.6, item 4: a range below 2^(p+1+b) leaves the window's
    first position without a chunk in every bucket (fp256 to 2^128), and the
    position contributes nothing. Built at smaller stated ranges and held to
    the checks on lanes inside them (the claims' pin is the default plan's,
    so the build's own counts stand in for it)."""
    fmt = BY_NAME[name]
    b = ml.build_reduction(fmt, R=R)
    P = b.meta["reduction"]
    assert (P.R, P.Emax) == (R, R - 1)
    fr = ml.reduction_front(ml.Build(fmt, RNE, "front"), ("in", "a"), P)
    assert (fr.prods[0] is None) == empty
    rng = random.Random(5)
    p = fmt.prec
    xs = []
    for _ in range(150):
        E = rng.randint(P.Egate, P.Emax)
        xs.append(_enc(fmt, rng.getrandbits(1),
                       rng.getrandbits(p - 1) | (1 << (p - 1)), E - p + 1))
    xs += edge_args(fmt, P)[:150] + half_args(fmt, P, 8)
    run = run_lanes(b, xs)
    pin = (len(b.meta["exact"]), len(b.meta["data"]))
    assert check_reference(run) == [] and check_audit(run, pin=pin) == []
    assert check_range(b) == []


def test_the_front_is_what_trig_reduction_calls():
    fmt = FP64
    P = ml.plan_reduction(fmt, 44)
    x = ("in", "a")
    f = ml.Build(fmt, RNE, "front")
    fr = ml.reduction_front(f, x, P)
    for k in ("M", "nM", "U", "V", "m", "inv_m", "prods", "fI", "nqs",
              "coarse", "sig", "gm1"):
        assert hasattr(fr, k), k
    assert len(fr.prods) == P.L
    pairs = [p for p in fr.prods if p is not None]
    assert pairs and all(isinstance(v, ml.ReductionValue) for pr in pairs
                         for v in pr if v is not None)
    assert set(f.phase_of) == {"red-setup", "red-window", "red-products",
                               "red-coarse"}
    assert len(fr.nqs) == 1                      # k_1 only: the tail adds two
    g = ml.Build(fmt, RNE, "whole")
    out = ml.trig_reduction(g, x, P)
    assert g.body[:len(f.body)] == f.body        # the front, then the rest
    assert g.phase == "setup"                    # restored
    assert out.inrange is None
    for k in ("rh", "rl", "q", "small", "inrange"):
        assert hasattr(out, k)
    for k in ("rh", "rl", "q", "small", "sig", "U", "V", "fI", "xh", "th",
              "tl"):
        assert k in g.probes, k
    # the claims were added to Build.meta
    assert len(g.meta["exact"]) == CLAIMS["fp64"][0]
    assert len(g.meta["data"]) == CLAIMS["fp64"][1]


def test_the_reduction_is_straight_line_alu_in_bank_words():
    """No scratch slot, no branch, no instruction but the ALU's; every
    operand a value or a word (the contract: straight-line ALU instructions,
    bank words only)."""
    alu = {sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL, sf.OP_NEG, sf.OP_ABS,
           sf.OP_SELECT, sf.OP_CMPLT, sf.OP_IAND, sf.OP_IOR, sf.OP_IXOR,
           sf.OP_IADD, sf.OP_ISUB, sf.OP_ISHL, sf.OP_ISHR, sf.OP_ICMPLT}
    for name in ("fp64", "fp128", "fp256", "fp32"):
        b = build_of(name)
        assert {op for op, _r, _s in b.body} <= alu
        assert all(s[0] in ("v", "w", "in") for _o, _r, srcs in b.body
                   for s in srcs)
        # RNE throughout, and RDN for the bucket's floor alone
        rounds = Counter(r for _o, r, _s in b.body if r is not None)
        assert set(rounds) == {RNE, RDN} and rounds[RDN] == 1


# ---- the audit, stricter than the model's ----------------------------------

def test_the_audit_reports_a_claim_on_an_opcode_it_cannot_check():
    b = ml.build_reduction(FP64)
    iand = next(i for i, (op, _r, _s) in enumerate(b.body)
                if op == sf.OP_IAND)
    assert ml.reduction_audit(b, 0x4000000000000000) == []
    b.meta["exact"].add(("v", iand))
    bad = ml.reduction_audit(b, 0x4000000000000000)
    assert bad == [(iand, "iand", b.phase_of[iand])]
    assert check_audit(run_lanes(b, [0x4000000000000000]))[0].startswith(
        "audit: 43 exact")


def test_the_audit_counts_and_reports_a_non_finite_operand_of_a_main_lane():
    b = ml.build_reduction(FP64)
    b.words[b.roles["INVB"][1]] = sf.qnan_bits(FP64)       # 1/b a NaN
    main, off = 0x4000000000000000, 0x7ff0000000000000     # 2, +inf
    t = {}
    bad = ml.reduction_audit(b, main, tally=t)
    assert bad and t["nonfinite"] == len(bad) > 0
    assert all(name in ("fma", "sub", "add", "mul") for _i, name, _p in bad)
    t = {}
    assert ml.reduction_audit(b, off, tally=t) == []        # +inf is not main
    assert t["nonfinite"] == 0 and t["skipped"] == t["claims"] == 42
    # and in a run: check_audit says so
    assert any("non-finite" in s for s in check_audit(run_lanes(b, [main])))


def test_the_audit_asserts_nothing_on_lanes_that_are_not_main():
    b = build_of("fp128")
    t = {}
    for x in (0, sf.inf_bits(FP128), sf.qnan_bits(FP128),
              ml._pow2(FP128, 1024), sf.max_normal_bits(FP128),
              ml._pow2(FP128, -300), 1):
        assert ml.reduction_audit(b, x, tally=t) == []
    assert t["skipped"] == t["claims"] == 7 * CLAIMS["fp128"][0]
    # and a main lane is audited
    t = {}
    assert ml.reduction_audit(b, ml._pow2(FP128, 5), tally=t) == []
    assert t["skipped"] == 0 and t["claims"] == CLAIMS["fp128"][0]
    with pytest.raises(ValueError, match="no trig_reduction"):
        ml.reduction_audit(ml.Build(FP64, RNE, "none"), 1)


def test_plants_that_cannot_act_are_refused_by_name():
    with pytest.raises(ValueError, match="does not apply at fp64"):
        ml.build_reduction(FP64, plant="range_short")          # no range
    with pytest.raises(ValueError, match="does not apply at fp128"):
        ml.build_reduction(FP128, plant="exact_add")           # no TwoSum there
    with pytest.raises(ValueError, match="does not apply at fp64"):
        ml.build_reduction(FP64, plant="split_unproved")
    with pytest.raises(ValueError, match="unknown plant"):
        ml.build_reduction(FP64, plant="nothing")
    with pytest.raises(ValueError, match="unknown plant"):
        ml.trig_reduction(ml.Build(FP64, RNE, "x"), ("in", "a"),
                          ml.plan_reduction(FP64, 44), plant="nothing")
    with pytest.raises(ValueError, match="the plan is for fp64"):
        ml.trig_reduction(ml.Build(FP128, RNE, "x"), ("in", "a"),
                          ml.plan_reduction(FP64, 44))


# ---- the constants ---------------------------------------------------------

def test_constants_in_process():
    assert check_constants() == []
    lines, findings = ml.check_reduction_constants()
    assert findings == [] and len(lines) == 3
    # the roles the reduction holds, and every one was asked
    for name in ("fp64", "fp128", "fp256"):
        roles = set(build_of(name).roles)
        P = build_of(name).meta["reduction"]
        assert roles >= {"MAGIC", "MQ", "INVB", "FLOOROFF", "PIO2H", "PIO2L",
                         "PIO4D"} | {f"CHUNK{k}" for k in range(P.nchunks)}


def _program(*args):
    return subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                           *args], cwd=PYTHON_DIR, capture_output=True,
                          text=True)


def test_constants_as_a_program():
    done = _program("--check", "--only", "reduction")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "mathlib --check (reduction): 3 formats, 0 differences" in done.stdout
    for name in ("fp64", "fp128", "fp256"):
        assert f"reduction {name}: G = {ml.GUARD[name]}" in done.stdout
    assert "routines" not in done.stdout            # the six are not run
    done = _program("--only", "reduction")
    assert done.returncode == 0 and "instructions by phase" in done.stdout
    assert _program("--check", "--only", "sqrt").returncode == 2


def test_check_runs_the_routines_line_as_it_is_and_the_reductions_own(
        monkeypatch, capsys):
    """With no --only: the six routines' line, unchanged, then a line of the
    reduction's own; exit 1 on a difference in either."""
    monkeypatch.setattr(ml, "check_constants",
                        lambda **kw: (["six lines"], []))
    assert ml.main(["--check"]) == 0
    shown = capsys.readouterr().out.splitlines()
    i = shown.index("mathlib --check: 6 routines, 4 formats, 0 differences")
    assert shown[0] == "six lines" and shown[i + 1].startswith("reduction fp64")
    assert shown[-1] == "mathlib --check (reduction): 3 formats, 0 differences"
    monkeypatch.setattr(ml, "check_constants",
                        lambda **kw: (["six lines"], ["a difference"]))
    assert ml.main(["--check"]) == 1                 # the six differ
    assert "DIFFERENCE: a difference" in capsys.readouterr().out
    monkeypatch.undo()
    real = ml.build_reduction
    monkeypatch.setattr(ml, "check_constants", lambda **kw: (["six"], []))
    monkeypatch.setattr(ml, "build_reduction", lambda fmt, **kw: real(
        fmt, plant="pio2_low", **kw))
    assert ml.main(["--check"]) == 1                 # the reduction's differ
    shown = capsys.readouterr().out
    assert "DIFFERENCE" in shown and "PIO2L" in shown
    assert "mathlib --check: 6 routines, 4 formats, 0 differences" in shown
    assert ml.main(["--check", "--only", "reduction"]) == 1
    assert "routines" not in capsys.readouterr().out


def test_a_missing_header_is_a_difference_by_name(tmp_path):
    lines, findings = ml.check_reduction_constants(
        formats=(FP64,), header=tmp_path / "mp_2opi.h")
    assert any("header" in f and "mp_2opi.h" in f for f in findings), findings
    junk = tmp_path / "junk.h"
    junk.write_text("not a header\n")
    assert any("not the 2/pi header" in f for f in
               ml.check_reduction_constants(formats=(FP64,), header=junk)[1])
    short = tmp_path / "short.h"
    text = (ROOT / "host" / "src" / "mp_2opi.h").read_text()
    head, _, rest = text.partition("cft_two_over_pi[CFT_TWO_OVER_PI_WORDS] = {")
    short.write_text(head + "cft_two_over_pi[CFT_TWO_OVER_PI_WORDS] = {"
                     + rest[:200] + "};\n")
    assert any("words read" in f for f in
               ml.check_reduction_constants(formats=(FP64,), header=short)[1])


def test_a_header_with_a_flipped_bit_is_a_difference_by_name(tmp_path):
    """The header leg alone: one bit of the stream flipped, in a word the
    fp64 table reads, and the chunk that holds it is named."""
    text = (ROOT / "host" / "src" / "mp_2opi.h").read_text()
    head, sep, rest = text.partition("cft_two_over_pi[CFT_TWO_OVER_PI_WORDS] = {")
    i = rest.index("0x") + 2 + 5                      # a digit of the 1st word
    flipped = rest[:i] + "%x" % (int(rest[i], 16) ^ 1) + rest[i + 1:]
    bad = tmp_path / "mp_2opi.h"
    bad.write_text(head + sep + flipped)
    found = ml.check_reduction_constants(formats=(FP64,), header=bad)[1]
    assert any("CHUNK0" in f and "header's bits" in f for f in found), found
    assert not any("Machin" in f for f in found)       # the derivation agrees


def test_an_enclosure_that_straddles_a_chunks_last_bit_is_refused(monkeypatch):
    """The undecidable case: pi known only to 60 bits cannot decide chunks
    of 1,232 bits, and the check says so rather than pass."""
    lo, hi = ml._check_pi(ml._PI_CHECK_BITS)
    wide = Fraction(1, 2 ** 60)
    monkeypatch.setattr(ml, "_check_pi",
                        lambda bits: (lo - wide, hi + wide))
    _lines, findings = ml.check_reduction_constants(formats=(FP64,))
    assert any("undecidable" in f and "CHUNK" in f for f in findings), findings


# =====================================================================
# the plants: for every check, a fault shown red in it, by name
# =====================================================================
#
# Each row: (plant, the format it is built at, the checks it must turn red,
# the checks that must stay green). A check named in neither is not asserted:
# a fault may well turn more than the checks it exists for red (a wrong
# bucket does), and the table says what it was built to be seen by. Fresh
# builds of the clean module's functions, nothing cached is mutated, so every
# row passes alone, in any order and under pytest-xdist.

CHECKS = ("reference", "audit", "setup", "proofs", "range", "constants",
          "shape", "cushion")
# a plant of the independent derivation: Machin's enclosure of pi shifted by
# 2^-200 (a series that lost a term, a constant mistyped)
DERIVATION = "pi_shifted"
PLANTED = [
    ("chunk", "fp64", ("reference", "constants"),
     ("audit", "setup", "shape")),
    ("window", "fp64", ("reference",), ("setup", "constants", "shape")),
    ("mid_inexact", "fp128", ("reference", "audit", "shape"),
     ("setup", "constants")),
    ("exact_add", "fp64", ("audit", "reference"),
     ("setup", "constants", "shape")),
    ("quadrant_dropped", "fp64", ("reference", "audit", "shape"),
     ("setup", "constants")),
    ("bucket_nearest", "fp64", ("setup", "reference"),
     ("constants", "shape")),
    ("pio2_low", "fp64", ("reference", "constants"),
     ("audit", "setup", "shape")),
    ("claims_lost", "fp64", ("audit",),
     ("reference", "setup", "constants", "shape")),
    ("range_short", "fp128", ("range", "constants"),
     ("reference", "audit", "setup", "shape")),
    ("split_unproved", "fp32", ("proofs",), ()),
    ("fast_as_two_sum", "fp64", ("shape",),
     ("reference", "audit", "setup", "constants")),
    ("lw_understated", "fp32", ("cushion",),
     ("reference", "audit", "setup", "constants", "shape")),
    (DERIVATION, "fp64", ("constants",), ("shape",)),
]
# the lanes a plant's reference and audit run on: the least that shows it
LANES = {"mid_inexact": ("pool",), "exact_add": ("edges",),
         "lw_understated": ("halves",)}
# where a plant cannot act, and is refused by name ("does not apply"), at the
# guards the module builds at (G_OF). It counts as neither red nor green
# there. (split_unproved is not here: it acts where the split's range proof
# fails, fp32 at G = 16, which check_proofs builds, and nowhere at G_OF.)
NOT_APPLICABLE = {("exact_add", "fp128"), ("exact_add", "fp256"),
                  ("range_short", "fp64"), ("range_short", "fp32"),
                  ("lw_understated", "fp128"), ("lw_understated", "fp256")}


@functools.lru_cache(maxsize=None)
def planted_run(plant, name, fam):
    """The planted build's lanes of the families `fam`, run once for the
    tests that read them."""
    return run_lanes(build_of(name, plant),
                     [x for k in fam for x in families(name)[k]])


def _planted_findings(plant, name, checks, monkeypatch=None):
    """{check: findings} of the planted build at `name`."""
    fam = LANES.get(plant, ("buckets", "pio4", "deep"))
    if plant == DERIVATION:
        lo, hi = ml._check_pi(ml._PI_CHECK_BITS)
        eps = Fraction(1, 2 ** 200)
        monkeypatch.setattr(ml, "_check_pi", lambda bits: (lo + eps, hi + eps))
        b = build_of(name)
        builder = None
    elif plant == "split_unproved":
        b = None

        def builder(fmt, **kw):
            # the generator without the split's proof: where that proof never
            # fails (fp32 at G = 18) it is the clean generator
            try:
                return ml.build_reduction(fmt, plant="split_unproved", **kw)
            except ValueError as e:
                if "does not apply" not in str(e):
                    raise
                return ml.build_reduction(fmt, **kw)
    else:
        b = build_of(name, plant)

        def builder(fmt, **kw):
            return build_of(fmt.name, plant)
    out = {}
    if {"reference", "audit", "cushion"} & set(checks):
        run = planted_run(plant, name, tuple(fam)) if plant != DERIVATION \
            else run_lanes(b, [x for k in fam for x in families(name)[k]])
        out["reference"] = check_reference(run)
        out["audit"] = check_audit(run)
        out["cushion"] = check_cushion(run)
    if "setup" in checks:
        out["setup"] = check_setup(b)
    if "range" in checks:
        out["range"] = check_range(b)
    if "shape" in checks:
        out["shape"] = check_shape(b)
    if "constants" in checks:
        out["constants"] = check_constants(builder=builder,
                                           formats=(BY_NAME[name],))
    if "proofs" in checks:
        out["proofs"] = check_proofs(builder=builder)
    return out


def _row_id(r):
    return f"{r[0]}-{r[1]}"


@pytest.mark.parametrize("row", PLANTED, ids=_row_id)
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(
        row, monkeypatch):
    plant, name, red, green = row
    found = _planted_findings(plant, name, set(red) | set(green), monkeypatch)
    for c in red:
        assert found[c], f"{plant} at {name}: {c} stays green"
        assert all(s.startswith(c + ": ") for s in found[c]), found[c][:2]
    for c in green:
        assert found[c] == [], f"{plant} at {name}: {c} is red: {found[c][:2]}"


def test_each_leg_of_the_reference_can_fail():
    """The reference's legs, each on a lane doctored to break it alone: the
    normal form (r_h moved an ulp, r_l by the same, the sum kept), `small`
    either way, a small lane's shape, q's meaning, a non-finite word."""
    b = build_of("fp64")
    fmt = FP64
    two, half = 0x4000000000000000, 0x3fe0000000000000     # 2.0; 0.5 is small
    run = run_lanes(b, [two, half], audit=False)
    assert check_reference(run) == []
    (x, rh, rl, q, sm, inr), (x2, rh2, rl2, q2, sm2, inr2) = run.rows
    assert not sm and sm2
    ulp = ml._dec(fmt, rh + 1) - ml._dec(fmt, rh)
    one = sf.one_bits(fmt)
    cases = {
        "r_h not RN(r_h + r_l)": [(x, rh + 1, ml._enc(fmt, ml._dec(fmt, rl)
                                                      - ulp), q, sm, inr)],
        "`small` not where": [(x, rh, rl, q, one, inr),
                              (x2, rh2, rl2, q2, 0, inr2)],
        "a small lane not r = |x|": [(x2, rh2, ml._enc(fmt, Fraction(1, 2 ** 60)),
                                      q2, sm2, inr2)],
        "q not MAGIC + n": [(x, rh, rl, q + (1 << fmt.man_w), sm, inr)],
        "a non-finite": [(x, sf.qnan_bits(fmt), rl, q, sm, inr)],
    }
    for kind, rows in cases.items():
        found = check_reference(types.SimpleNamespace(b=b, rows=rows))
        assert any(kind in f and f.startswith("reference: ") for f in found),             (kind, found)


def test_the_proofs_check_fails_on_a_wrong_plan_alone(monkeypatch):
    """Its plan legs without its refusals: fp128 planned with the docs'
    sampled 121 bits of cancellation, not the range's 123 (the study's 3.6,
    item 3), moves the budget, the bottom and L, and the check says so."""
    monkeypatch.setitem(ml.TRIG_LOST, "fp128", 121)
    found = check_proofs()
    assert any("proofs: fp128: budget is -284, pinned -286" in f for f in found)
    assert not any(f.startswith("proofs: fp64") or f.startswith("proofs: fp256")
                   for f in found)


def test_the_cushion_check_fails_on_the_lanes_alone_and_on_the_pin_alone(
        monkeypatch):
    """Both legs of the check can fail without the other: the measured
    overshoot past the computed bound (the pin set to the understated
    figure, so that it is quiet), and the pin (the bound understated by a
    plant, the lanes quiet, there being none that reach it)."""
    b = build_of("fp32", "lw_understated")
    run = run_lanes(b, list(families("fp32")["halves"]), audit=False)
    slack = round(quadrant_slack(b), 2)
    assert slack == -19.52                                # 8 bits under -11.66
    monkeypatch.setitem(SLACK, "fp32", slack)
    found = check_cushion(run)
    assert len(found) == 1 and "overshoots pi/4 by 2^-17.09" in found[0]
    monkeypatch.undo()
    quiet = run_lanes(b, [0x3f800000], audit=False)       # 1.0: no overshoot
    found = check_cushion(quiet)
    assert len(found) == 1 and "pinned 2^-11.66" in found[0]


def test_the_runs_command_runs_at_small_sizes():
    """python/tests/mathlib_runs.py reduction, the lead's box command, at the
    least it accepts."""
    done = subprocess.run(
        [sys.executable, "-B", str(pathlib.Path(__file__).parent
                                   / "mathlib_runs.py"), "reduction",
         "--formats", "fp128", "--n", "30", "--edge-width", "0",
         "--halves-step", "256", "--quick"], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RESULT: ok" in done.stdout
    assert "reduction fp128: G = 46, b = 108" in done.stdout
    assert "computed bound 2^-64.00" in done.stdout


def test_exact_add_is_red_in_the_audit_on_the_binade_edges_only():
    """The study's 3.6, item 8: the plant is invisible to random arguments,
    the bucket edges and the deepest cancellations, and the products' binade
    edges find it, at fp64 27 lanes, the first 0x46167c4c45c1b200."""
    b = build_of("fp64", "exact_add")
    f = families("fp64")
    run = planted_run("exact_add", "fp64", ("edges",))
    assert check_audit(run)[0].startswith("audit: 27 lanes with a claim")
    assert min(x for x, _bad in run.bad) == 0x46167c4c45c1b200
    quiet = run_lanes(b, f["random"] + f["buckets"] + f["pio4"])
    assert check_audit(quiet) == [] and check_reference(quiet) == []


def test_the_chunk_plant_flips_one_bit_of_the_middle_chunk():
    for name in ("fp64", "fp128", "fp256"):
        clean, bad = build_of(name), build_of(name, "chunk")
        P = clean.meta["reduction"]
        k = P.nchunks // 2
        diff = [r for r in clean.roles if r.startswith("CHUNK")
                and clean.words[clean.roles[r][1]] != bad.words[bad.roles[r][1]]]
        assert diff == [f"CHUNK{k}"]
        a = ml._dec(clean.fmt, clean.words[clean.roles[diff[0]][1]])
        c = ml._dec(clean.fmt, bad.words[bad.roles[diff[0]][1]])
        assert abs(a - c) == 1 << (P.b // 2)


def _applies(plant, name):
    """Whether the plant acts at `name` (at its guard), or is refused there
    by name."""
    try:
        ml.build_reduction(BY_NAME[name], G=G_OF[name], plant=plant)
    except ValueError as e:
        assert "does not apply" in str(e), (plant, name, e)
        return False
    return True


def test_every_plant_is_in_the_table_and_every_row_names_a_plant():
    named = {row[0] for row in PLANTED}
    assert named == PLANT_NAMES | {DERIVATION}
    assert len(PLANTED) == len({_row_id(r) for r in PLANTED})
    for plant, name, red, green in PLANTED:
        assert set(red) | set(green) <= set(CHECKS), (plant, red, green)
        assert not set(red) & set(green), (plant, red, green)
        assert red, plant
        # a row is where the plant acts: where it does not, it is neither
        # red nor green, and has no row
        assert (plant, name) not in NOT_APPLICABLE, (plant, name)


def test_the_plants_that_do_not_apply_are_the_pinned_ones():
    """A plant refused by name where it cannot act (the fault is not reached
    there) is counted as neither red nor green: the pairs are pinned, so that
    a plant that stops acting where it did is seen, not read as green."""
    got = {(p, n) for p in ml.REDUCTION_PLANTS if p != "split_unproved"
           for n in ("fp64", "fp128", "fp256", "fp32")
           if not _applies(p, n)}
    assert got == NOT_APPLICABLE
    # split_unproved acts where its proof fails and nowhere else: fp32 at
    # G = 16 (at G = 30 the next proof, the mid sum's low word, refuses)
    assert len(ml.build_reduction(FP32, G=16, plant="split_unproved").body) > 0
    with pytest.raises(ValueError, match="does not apply at fp32"):
        ml.build_reduction(FP32, G=18, plant="split_unproved")
    with pytest.raises(ValueError, match="low word is not exact"):
        ml.build_reduction(FP32, G=30, plant="split_unproved")


def test_every_check_has_a_plant_red_in_it_and_a_clean_test():
    red = {c for plant, name, r, _g in PLANTED
           if (plant, name) not in NOT_APPLICABLE for c in r}
    assert red == set(CHECKS), set(CHECKS) - red
    # and the control: a test of the clean build for each
    tests = {"reference": "test_reference_and_audit_on_the_studys_arguments",
             "audit": "test_reference_and_audit_on_the_studys_arguments",
             "cushion": "test_reference_and_audit_on_the_studys_arguments",
             "setup": "test_setup_on_every_exponent",
             "proofs": "test_proofs", "range": "test_range",
             "constants": "test_constants_in_process", "shape": "test_shape"}
    assert set(tests) == set(CHECKS)
    for fn in tests.values():
        assert callable(globals()[fn]), fn


def test_every_plant_of_the_module_changes_the_build_or_is_refused():
    """A plant that did nothing would pass every row green: each is a
    different build from the clean one - in its body, its words, its claims
    or the static bounds it keeps - or is refused where it cannot act."""
    for name in ("fp64", "fp128"):
        clean = build_of(name)
        for plant in ml.REDUCTION_PLANTS:
            if not _applies(plant, name):
                continue
            b = ml.build_reduction(BY_NAME[name], plant=plant)
            same = (b.body == clean.body and b.words == clean.words
                    and len(b.meta.get("exact", ()))
                    == len(clean.meta["exact"])
                    and b.meta["reduction_mid"] == clean.meta["reduction_mid"])
            assert not same, (plant, name)
