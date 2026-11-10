# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The structured families of atan, asin, acos and atan2 (parcel M4G4): the
arguments whose true value sits within the in-lane bound of a rounding
boundary, which the test marks and a replay decides (docs/studies/
M4-invtrig.md, section 3.5; Logan's answer 7: "their marks kept, with the
windows' centres and the hard-case family's threshold listed in the build's
tests"). mathlib_trig_family.py's design, for two more inputs and different
series.

WHY THERE IS A FAMILY, and where (the study's 3.5; every figure COMPUTED
there, redone here from the fragment's ulp):

  tiny    atan x = x - x^3/3 + x^5/5 ..., asin x = x + x^3/6 + 3 x^5/40 ...
          and atan2(c 2^-e x, x), whose quotient is the exact c 2^-e and
          whose answer is atan's at it. For x = c 2^-e, c odd of b bits,
          x^3/3 (x^3/6) lands on the result's grid or on a midpoint of two
          floats at some exponents; the true value then sits x^5/5 from a
          rounding boundary, inside the bound 2^-(p+G) x while x^4 < 5
          2^-(p+G). At fp64 one centre each (atan 3 2^-26 under rne and rmm;
          asin 3 2^-25 under the directed three), at fp128 and fp256 a family
          to c of about 2^12 and 2^33. THE LISTED c are the odd c below
          2^CBITS (6), every centre the theory finds there; the deeper c are
          held by deep_arguments(), classified and run, not listed.
  windows atan(x) = pi/2 - 1/x + 1/(3 x^3) ... lands on the boundary b of
          the result's grid (or a midpoint) nearest below pi/2 where 1/x =
          pi/2 - b: x0 = 1/(pi/2 - b); acos(x) = pi/2 - x - ... where x =
          pi/2 - b (POSITIVE x only: acos is not odd, and -x0 gives pi - ...,
          nowhere near a boundary); atan2(y, -1) = pi - y ... about y0 = pi
          - b. The K_BOUNDARIES nearest boundaries of each kind below each
          constant (the census's two at least), each a WINDOW of arguments:
          a neighbour x0 + j moves the true value by about j ulp(x0) / x0^2
          (atan), j ulp(x0) (acos, atan2), against a bound of 2^-(p+G) times
          the constant: half_width() computes it (about 2^(p-G+2) arguments
          at fp64 and past 2^69 at fp128, 2^192 at fp256).
  ratio   atan2(2^k, 1 + j ulp): the quotient 2^k/(1 + j u) = 2^k (1 - j u +
          j^2 u^2 ...) sits j^2 u^2 relative above the grid point 2^k (1 - j
          u). Where t^3/3 is under the bound too (k = -(p + 10)) the lane
          marks under the directed three while j^2 u^2 < 2^-(p+G), j <
          2^((p - G - 2)/2): 11.3 at fp64, 2^32.5 and 2^94.5 at fp128 and
          fp256. Division's hard cases; the family is two-parameter, the
          listed centres are the threshold and the census's j = 1 to 40.
  zero    no mark, claims of ZERO with their lanes: acos(1 - j 2^-p) and
          asin(1 - j 2^-p), acos(-1 + j 2^-p), j = 1 to 64 (acos(1 - eps) =
          sqrt(2 eps)(1 + eps/12 ...) keeps the answer far outside the
          bound; asin's slope there leaves less than one argument a
          window), and the diagonals atan2(x + j, x), 40 random x, j = -4
          to 4, four quadrants (1,440 lanes).

THE THEORY, independent of the fragment. For a lane and an attribute, d is
the distance from |f| (mpmath at 4p + 200 bits) to the nearest rounding
boundary of the attribute's class (a float under the directed three, a
midpoint under rne and rmm), in units of the nominal bound 2^-(p+G) |f|. The
routine marks a lane when V +- Bv straddles a boundary, and V is within the
budget's bound of f (mathlib_inv_budget: the cells of the study's 3.2, each
under its function's and format's B below, 0.073 Bv at the largest), so:

  d < 1 - B             the lane MUST be marked;
  d > 1 + B             the lane must NOT be marked, and is right unmarked;
  between               either: if marked, its guess is counted, not judged;
  gated                 never marked: the zeros, infinities, NaNs, |x| >= 1
                        for asin and acos, under the tiny gate, and atan2's
                        exact quotients under the gate (decided by the rule);
  range                 atan2's tiny-quotient range: marked whatever the test
                        says (M4G3's exact-rational predicate decides which
                        lanes: mathlib_inv_harness._tq_band).

B is thresholds()'s: the budget's largest cell for the function and
format (THRESHOLD_B, below). M2's fixed 0.7 and 1.3 were set for a budget of
0.17 Bv and would fail three lanes the merged waves committed (the lead's
ruling of 2026-11-10: asin's fp64 centre 3 2^-25 at d 0.759 and its
neighbour at 0.853, atan2's (2^-(p+10), 1 + 11 ulp) at 0.945). A lane
between 1 - B and 1 + B is "either": never asserted, its guess counted.

THE COMMITTED LIST (INV_FAMILY, at the end of this file) is INV_FAMILY[fn][fmt]
[rnd] = [entry, ...], an entry
  ("tiny", c, e0, e1)             the centres c 2^-e, e = e0 .. e1, c odd below
                                  2^CBITS, both signs, whose d is under 1 - B
                                  (atan2: against x = 1)
  ("win", const, kind, i)         the window about the i-th boundary of the
                                  kind ("grid" or "mid") below the constant
                                  ("pio2" or "pi"), the centre's d under 1 - B
  ("ratio", k, j)                 atan2(2^k, 1 + j' ulp) for j' = 1 .. j
  ("zero", family, ...)           a claim: the family marks nothing, with its
                                  parameters ("near1", 64) / ("diag", 40, 4)
GENERATED by generate() from the theory alone, and held to a fresh generation
by test_mathlib_inv_family.py and by `inv-family --check`, so it can neither
go stale nor be edited by hand to agree with a fault.

    python python/tests/mathlib_runs.py inv-family --write    regenerate
"""

import functools
import math
import random
import sys
from fractions import Fraction
from pathlib import Path

import mpmath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_inv_harness as I  # noqa: E402

# THE THRESHOLDS (the lead's ruling of 2026-11-10 on the committed lanes that
# a fixed 0.7 and 1.3, M2's rule for a budget of 0.17 Bv, would fail). B is
# the budget's largest cell for the function and format over its regions,
# the larger of the study's figure for the cell (bound_table.py: the desktop
# and box budgets with their residuals and the sampled worsts, READ) and this
# tool's (mathlib_inv_budget at the study's desktop sizes), rounded UP to two
# significant figures. A lane MUST be marked when d < 1 - B, MUST NOT when d >
# 1 + B, between either. THEY ARE ONLY AS GOOD AS THE BUDGET'S AGREEMENT WITH
# THE MODEL, which mathlib_inv_budget's `reference` leg holds (57 cells, digit
# for digit); a cell whose figure passes its B is a finding of
# `inv-budget`, not a number to loosen.
THRESHOLD_B = {
    ("atan", "fp64"): 0.034, ("asin", "fp64"): 0.073,
    ("acos", "fp64"): 0.066, ("atan2", "fp64"): 0.038,
    ("atan", "fp128"): 0.031, ("asin", "fp128"): 0.031,
    ("acos", "fp128"): 0.031, ("atan2", "fp128"): 0.031,
    ("atan", "fp256"): 0.023, ("asin", "fp256"): 0.023,
    ("acos", "fp256"): 0.023, ("atan2", "fp256"): 0.023,
}


def thresholds(fmt, fn):
    """(must, clear) for the function and format: 1 - B and 1 + B."""
    B = THRESHOLD_B[(fn, fmt.name)]
    return round(1 - B, 6), round(1 + B, 6)
RND_NAMES = sf.RND_NAMES
FUNCTIONS = ml.INV_NAMES
FORMATS = ml.INV_FORMATS
NEAREST = (sf.RND_RNE, sf.RND_RMM)
CBITS = 6                       # the listed c: odd, below 2^CBITS
K_BOUNDARIES = 3                # boundaries of each kind below each constant
RATIO_KS = (-10, -40, "deep")   # k = -10, -40, -(p + 10)
RATIO_JCAP = 40                 # the census's j; the threshold lanes besides
NEAR1_J = 64
DIAG = (40, 4)                  # x's and |j| (the census's 40 and -4 .. 4)
# (label, multiple of W in ulps; None for exactly one ulp): the first N_INSIDE
# inside a window, the rest outside it (mathlib_trig_family's offsets)
OFFSETS = (("1", None), ("W/8", Fraction(1, 8)), ("W/4", Fraction(1, 4)),
           ("0.65W", Fraction(13, 20)), ("1.35W", Fraction(27, 20)),
           ("2W", Fraction(2)), ("8W", Fraction(8)), ("1024W", Fraction(1024)))
N_INSIDE = 4
CONSTS = ("pio2", "pi")
KINDS = ("grid", "mid")
# the window family of each function: (constant, the function's role)
WINDOW_CONST = {"atan": "pio2", "acos": "pio2", "atan2": "pi"}
TINY_FNS = ("atan", "asin", "atan2")
TINY_X = (1, 3, 5 << 7)         # atan2(c 2^-e x, x): the census's x


def cls_of(rnd):
    """"nearest" for rne and rmm (a midpoint), "directed" for rtz, rdn, rup (a
    grid point): the two sets of lanes an attribute can mark."""
    return "nearest" if rnd in NEAREST else "directed"


def rep_of(cls):
    """The attribute that stands for a class in the theory."""
    return sf.RND_RNE if cls == "nearest" else sf.RND_RTZ


def _mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


@functools.lru_cache(maxsize=None)
def pi_frac():
    """pi as an exact Fraction to 2400 bits (mpmath)."""
    with mpmath.workprec(2400):
        return ml._frac(+mpmath.pi)


def const_value(const):
    return pi_frac() / 2 if const == "pio2" else pi_frac()


# ---- the lanes ----------------------------------------------------------------

def one(fmt, sign=0):
    return sf.one_bits(fmt, sign)


def make(fn, fmt, v, x=None):
    """The lane of fn whose varied operand is the encoding v: v itself, or
    for atan2 (v, x) with x the fixed divisor (+1 by default)."""
    if fn == "atan2":
        return (v, one(fmt) if x is None else x)
    return v


def negated(fn, fmt, lane):
    """The lane with the sign of its varied operand flipped (y's for a pair:
    atan2(-y, x) = -atan2(y, x))."""
    if isinstance(lane, tuple):
        return (lane[0] ^ fmt.sign_mask,) + lane[1:]
    return lane ^ fmt.sign_mask


def varied(lane):
    return lane[0] if isinstance(lane, tuple) else lane


def with_varied(lane, v):
    return (v,) + lane[1:] if isinstance(lane, tuple) else v


# ---- the distance, the classes ------------------------------------------------

@functools.lru_cache(maxsize=None)
def _fraction_in_cell(fn, fmt, lane):
    """(midpoint, grid point): where |f| lies in its rounding cell, by
    mpmath at 4p + 200 bits, as the distance to the nearest midpoint and to
    the nearest grid point, each relative to |f|; cached, since the
    attributes share it. The cell is that of |f| (a lane just under a power
    of two sees the finer ulp), the grid point 2^k its top."""
    p = fmt.prec
    with mpmath.workprec(4 * p + 200):
        T = abs(I.true_value(fn, fmt, lane))
        e = mpmath.mag(T) - 1                       # floor(log2 T)
        ulp = mpmath.mpf(2) ** (e - p + 1)
        q = T / ulp
        fl = mpmath.floor(q)
        frac = q - fl
        grid = min(frac, 1 - frac)
        return (float(abs(frac - mpmath.mpf(1) / 2) * ulp / T),
                float(grid * ulp / T))


def distance(fmt, rnd, fn, lane, G=None):
    """d: the distance from |f| to the nearest rounding boundary of the
    result under rnd, in units of 2^-(p+G) |f|. By mpmath."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    mid, grid = _fraction_in_cell(fn, fmt, lane)
    return (mid if rnd in NEAREST else grid) / 2.0 ** (-(p + G))


def _exact_quotient(fmt, t):
    """Whether the positive rational t is a float of the format (so that
    atan2's exact-quotient rule, not the test, decides the lane)."""
    n, d = t.numerator, t.denominator
    if d & (d - 1):
        return False
    return n.bit_length() <= fmt.prec


def atan2_status(fmt, lane):
    """"gated", "mark" (the tiny-quotient range: marked whatever the test
    says), "either" (the band where the seed's error decides) or None (the
    main path's d decides): the shape of atan2's lane. The range is
    mathlib_inv_harness._tq_band's, an exact rational; the exact quotient
    below the gate is decided by the rule and never marked."""
    y, x = lane
    if not (I._finite(fmt, y) and I._finite(fmt, x)):
        return "gated"
    t = I._tq_shape(fmt, lane)
    if t is None:
        return None
    lo, hi = I._tq_band(fmt)
    if t < lo:
        return "mark"
    if t < hi:
        return "either"
    if t < Fraction(2) ** ml.trig_gates(fmt)[1] and _exact_quotient(fmt, t):
        return "gated"
    return None


def is_gated(fmt, fn, lane):
    """Never marked by the test (or marked whatever it says): a zero, an
    infinity or a NaN; asin and acos at |x| >= 1 (acos(-1) apart); asin and
    atan under their tiny gates."""
    if fn == "atan2":
        return atan2_status(fmt, lane) == "gated"
    return not I.in_main(fn, fmt, lane)


def classify(fmt, rnd, fn, lane, G=None, must=None, clear=None):
    """"mark", "clear", "either" or "gated": what the theory demands of the
    routine on the lane (the thresholds of thresholds(), or the caller's)."""
    if must is None:
        must, clear = thresholds(fmt, fn)
    if fn == "atan2":
        st = atan2_status(fmt, lane)
        if st is not None:
            return st
    elif is_gated(fmt, fn, lane):
        return "gated"
    d = distance(fmt, rnd, fn, lane, G)
    return "mark" if d < must else "clear" if d > clear else "either"


def predicted(fmt, rnd, fn, lane, G=None):
    """Whether the theory allows the lane to be marked: d under 1 + B, or
    in atan2's tiny-quotient range or its band."""
    return classify(fmt, rnd, fn, lane, G) in ("mark", "either")


# ---- the half-width of a window -------------------------------------------------

def _ulp(fmt, v):
    u = sf.unpack(fmt, v)
    return Fraction(2) ** (u.m.bit_length() - 1 + u.e - fmt.prec + 1)


def half_width(fmt, fn, centre, v0, G=None):
    """W: the window's half-width in ulps of the varied operand v0 (an
    encoding), the study's closed forms (3.5), exact (a Fraction): the bound
    2^-(p+G) |f| over how far one ulp of the operand moves the true value
    from the boundary. tiny atan and atan2: x^2 ulp(x) (x^3/3's slope), tiny
    asin: x^2 ulp(x) / 2 (x^3/6's); windows: atan about x0: ulp(x0)/x0^2
    (|f| about pi/2), acos and atan2(y, -1): ulp(x0) (|f| about pi/2, pi)."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    xv = abs(ml._dec(fmt, v0))
    ulp = _ulp(fmt, v0)
    if centre[0] == "tiny":
        drift = xv * xv * ulp / (2 if fn == "asin" else 1)
        Bv = xv / 2 ** (p + G)
    else:
        const = const_value(centre[1])
        Bv = const / 2 ** (p + G)
        drift = ulp / (xv * xv) if fn == "atan" else ulp
    return Bv / drift


# ---- the centres ------------------------------------------------------------------

def _gate_exponent(fmt, fn):
    gs, ga = ml.trig_gates(fmt)[0], ml.trig_gates(fmt)[1]
    return -(gs if fn == "asin" else ga)


def _exponents(fmt, fn, b, G=None):
    """The exponents e at which a centre c 2^-e with c of b bits is a
    candidate: from two under the study's first, shifted by the bit length,
    up to the tiny gate."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    return range(max(1, (p + G) // 4 - 6 + b - 1),
                 _gate_exponent(fmt, fn) + b)


def tiny_argument(fmt, c, e):
    return ml._enc(fmt, Fraction(c, 2 ** e))


def tiny_lane(fn, fmt, c, e, x=1):
    """atan(c 2^-e), asin(c 2^-e), or atan2(c 2^-e x, x) (x a small integer
    float, the census's 1, 3 and 5 2^7)."""
    if fn == "atan2":
        xb = ml._enc(fmt, Fraction(x))
        return (ml._enc(fmt, Fraction(c * x, 2 ** e)), xb)
    return tiny_argument(fmt, c, e)


@functools.lru_cache(maxsize=None)
def _tiny_centres(fmt, fn, cls, G=None):
    """[(c, e)] the odd c below 2^CBITS and exponents whose x = c 2^-e the
    theory demands marked under the class, sorted by c then e."""
    rnd = rep_of(cls)
    out = []
    for c in range(1, 1 << CBITS, 2):
        for e in _exponents(fmt, fn, c.bit_length(), G):
            if classify(fmt, rnd, fn, tiny_lane(fn, fmt, c, e), G) == "mark":
                out.append((c, e))
    return out


def boundaries_below(fmt, const, kind, count=K_BOUNDARIES):
    """The `count` nearest rounding boundaries of the kind below the
    constant, exact rationals: grid points (the floats at and below the
    constant) or midpoints (those of the cells below it)."""
    K = const_value(const)
    lo = ml._dec(fmt, ml._enc(fmt, K, sf.RND_RTZ))
    u = _ulp(fmt, ml._enc(fmt, K, sf.RND_RTZ))
    if kind == "grid":
        return [lo - j * u for j in range(count)]
    out = [lo + u / 2 - j * u for j in range(count + 1)]
    return [b for b in out if b < K][:count]


def window_centre(fmt, fn, const, kind, i):
    """The encoding at the centre of the window about the i-th boundary b:
    atan 1/(pi/2 - b), acos pi/2 - b, atan2's y of (y, -1) pi - b."""
    K = const_value(const)
    gap = K - boundaries_below(fmt, const, kind)[i]
    return ml._enc(fmt, 1 / gap if fn == "atan" else gap)


def window_lane(fn, fmt, v):
    """The lane of a window about the varied operand v: atan(v), acos(v) or
    atan2(v, -1)."""
    return (v, one(fmt, 1)) if fn == "atan2" else v


def centre_lane(fn, fmt, centre):
    """The lane at a centre (positive)."""
    if centre[0] == "tiny":
        return tiny_lane(fn, fmt, centre[1], centre[2])
    if centre[0] == "win":
        return window_lane(fn, fmt, window_centre(fmt, fn, *centre[1:]))
    raise ValueError(f"centre {centre!r}")


def _win_centres(fmt, fn, cls):
    rnd = rep_of(cls)
    const = WINDOW_CONST[fn]
    out = []
    for kind in KINDS:
        for i in range(len(boundaries_below(fmt, const, kind))):
            cen = ("win", const, kind, i)
            if classify(fmt, rnd, fn, centre_lane(fn, fmt, cen)) == "mark":
                out.append(cen)
    return out


def ratio_lane(fmt, k, j):
    """atan2(2^k, 1 + j ulp)."""
    return (ml._pow2(fmt, k), one(fmt) + j)


def ratio_k(fmt, k):
    return -(fmt.prec + 10) if k == "deep" else k


@functools.lru_cache(maxsize=None)
def _ratio_threshold(fmt, cls, k):
    """The largest j whose lane the theory demands marked (d under 1 - B), by
    exponential search and bisection (d grows with j: j^2 u^2 over the bound
    at the lane's cell), 0 where j = 1 is not; and the smallest the theory
    calls clear (d over 1 + B)."""
    rnd = rep_of(cls)

    def cl(j):
        return classify(fmt, rnd, "atan2", ratio_lane(fmt, ratio_k(fmt, k), j))
    if cl(1) != "mark":
        return 0
    hi = 2
    while cl(hi) == "mark":
        hi *= 2
    lo = hi // 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if cl(mid) == "mark" else (lo, mid)
    return lo


def entries(fmt, rnd, fn, G=None):
    """The compact entries of (fn, fmt, rnd) the theory generates: runs
    ("tiny", c, e0, e1), the windows, the ratio's thresholds, the claims of
    zero."""
    cls = cls_of(rnd)
    out = []
    if fn in TINY_FNS:
        run = None
        for c, e in _tiny_centres(fmt, fn, cls, G):
            if run and run[1] == c and run[3] == e - 1:
                run[3] = e
            else:
                run = ["tiny", c, e, e]
                out.append(run)
        out = [tuple(r) for r in out]
    if fn in WINDOW_CONST:
        out += _win_centres(fmt, fn, cls)
    if fn == "atan2":
        for k in RATIO_KS:
            j = _ratio_threshold(fmt, cls, k)
            if j:
                out.append(("ratio", k, j))
        out.append(("zero", "diag") + DIAG)
    if fn in ("asin", "acos"):
        out.append(("zero", "near1", NEAR1_J))
    return out


def generate(formats=None):
    """INV_FAMILY, all of it, from the theory: {fn: {fmt: {attribute:
    [entry]}}} (the committed list below is held to this)."""
    out = {}
    for fn in FUNCTIONS:
        out[fn] = {}
        for fmt in formats or FORMATS:
            out[fn][fmt.name] = {RND_NAMES[r]: entries(fmt, r, fn)
                                 for r in sf.RND_MODES}
    return out


# ---- expanding the entries into lanes ---------------------------------------------

def expand(es):
    """The centres of compact entries: ("tiny", c, e) and ("win", const, kind,
    i), in order; the ratio's and the claims of zero stay as entries."""
    out = []
    for en in es:
        if en[0] == "tiny":
            out += [("tiny", en[1], e) for e in range(en[2], en[3] + 1)]
        else:
            out.append(tuple(en))
    return out


def centres(fmt, rnd, fn, G=None):
    """The generated centres of (fn, fmt, rnd), expanded."""
    return expand(entries(fmt, rnd, fn, G))


def neighbours(fmt, fn, centre, G=None):
    """[(lane, label)]: the centre's neighbours in the encoding of its varied
    operand, either side, at OFFSETS: the first N_INSIDE inside its window,
    the rest outside."""
    x0 = centre_lane(fn, fmt, centre)
    v0 = varied(x0)
    W = half_width(fmt, fn, centre, v0, G)
    out = []
    for lab, mult in OFFSETS:
        j = 1 if mult is None else max(1, math.ceil(W * mult))
        for sgn in (1, -1):
            mag = v0 + sgn * j
            if 0 < mag < fmt.exp_mask << fmt.man_w:
                out.append((with_varied(x0, mag),
                            f"{'+' if sgn > 0 else '-'}{lab}"))
    return out


def window_edges(fmt, rnd, fn, centre, G=None):
    """{side: (j_in, j_out)} for the centre, side +1 (the varied operand's
    encoding stepped up) and -1: along v0 + side j, the largest j whose lane
    the theory demands marked (d under 1 - B) and the smallest it calls clear
    (d over 1 + B) or gated; the two are exact, by an exponential search and
    a bisection (the marked set is an interval holding the centre, so each
    predicate is monotone in j on a side). j_out is None where the search
    reaches a binade's worth of steps without one. The window's edges,
    whatever its width: 2^192 arguments at fp256."""
    x0 = centre_lane(fn, fmt, centre)
    v0 = varied(x0)
    jmax = 1 << fmt.man_w
    out = {}
    for side in (1, -1):
        def cls(j, side=side):
            c = classify(fmt, rnd, fn, with_varied(x0, v0 + side * j), G)
            return "clear" if c == "gated" else c
        lo, j = 0, 1
        while j <= jmax and cls(j) != "clear":
            lo, j = j, j * 2
        if j > jmax:
            out[side] = (None, None)
            continue
        hi = j
        while hi - lo > 1:
            mid = (lo + hi) // 2
            lo, hi = (lo, mid) if cls(mid) == "clear" else (mid, hi)
        a, b = 0, hi
        while b - a > 1:
            mid = (a + b) // 2
            a, b = (mid, b) if cls(mid) == "mark" else (a, mid)
        out[side] = (a, hi)
    return out


def tiny_top(fmt, G=None):
    """The bit length of c past which the theory's window closes (about),
    from x^4 < 5 2^-(p+G) against the grid's alignment (the trig family's
    shape): (p - G + 7) // 6, which test_mathlib_inv_family.py holds to the
    sampled c: some have a window up to this bit length and none two past it."""
    G = ml.GUARD[fmt.name] if G is None else G
    return (fmt.prec - G + 7) // 6


def deep_arguments(fmt, fn, G=None):
    """[(lane, label)]: x = c 2^-e for the odd multiples of 3 of each bit
    length from CBITS + 1 up to two past where the theory's window closes
    (the smallest, the middle and the largest), at the exponents of the
    window the theory finds for that c and one either side, positive. The
    family beyond the committed sample, each lane classified by the theory
    and not listed (atan, asin and atan2 against x = 1)."""
    top = tiny_top(fmt, G) + 2
    out = []
    for b in range(CBITS + 1, top + 1):
        lo, hi = 1 << (b - 1), (1 << b) - 1
        first = lo + (3 - lo) % 6
        last = hi - (hi - 3) % 6
        mid = first + ((last - first) // 2) // 6 * 6
        for c in sorted({first, mid, last}):
            es = [e for e in _exponents(fmt, fn, b)
                  if any(classify(fmt, r, fn, tiny_lane(fn, fmt, c, e), G)
                         == "mark" for r in (sf.RND_RNE, sf.RND_RTZ))]
            if not es:
                continue
            for e in sorted({min(es) - 1, min(es), (min(es) + max(es)) // 2,
                             max(es), max(es) + 1}):
                if e >= 1:
                    out.append((tiny_lane(fn, fmt, c, e), f"{c} 2^-{e}"))
    return out


# ---- the census (census.py's families) --------------------------------------------

def census_tiny(fmt, fn):
    """The study's tiny family (census.py fam_tiny): +-c 2^-e for c = 1 to 16
    and e from (p + G)/4 - 4 up past the tiny gate (to 6 below it), both
    signs; atan2's against x = 1, 3 and 5 2^7 (exact quotients c 2^-e). A
    value that several (c, e) give (3 2^-26, 6 2^-27, 12 2^-28) is IN THE
    LIST AS MANY TIMES, as the study counts them: its 6 marks at fp64 are the
    three arguments in both signs."""
    p, G = fmt.prec, ml.GUARD[fmt.name]
    lo = max(1, (p + G) // 4 - 4)
    hi = _gate_exponent(fmt, fn) + 6
    out = []
    for x in (TINY_X if fn == "atan2" else (1,)):
        for e in range(lo, hi + 1):
            for c in range(1, 17):
                lane = tiny_lane(fn, fmt, c, e, x)
                out += [lane, negated(fn, fmt, lane)]
    return out


def census_near1(fmt, fn):
    """acos(1 - j 2^-p), acos(-1 + j 2^-p) and asin(1 - j 2^-p), j = 1 to 64
    (acos's both, asin's one)."""
    o, m = one(fmt), one(fmt, 1)
    out = [o - j for j in range(1, NEAR1_J + 1)]
    if fn == "acos":
        out += [m - j for j in range(1, NEAR1_J + 1)]
    return out


def census_diag(fmt, x=DIAG[0], jmax=DIAG[1]):
    """atan2(x + j, x), x random (40 of them, the census's generator seeded
    77 + the width), j = -4 to 4, all four quadrants: 1,440 lanes."""
    rng = random.Random(77 + fmt.width)
    p = fmt.prec
    S = fmt.sign_mask
    out = []
    for _ in range(x):
        E = rng.randint(-p, p)
        m = rng.getrandbits(p - 1) | (1 << (p - 1))
        xb = sf.round_pack(fmt, 0, m, E - p + 1, sf.RND_RNE)[0]
        for j in range(-jmax, jmax + 1):
            for sy in (0, 1):
                for sx in (0, 1):
                    out.append(((xb + j) | (S if sy else 0),
                                xb | (S if sx else 0)))
    return out


def census_ratio(fmt):
    """atan2(2^k, 1 + j ulp), j = 1 to 40, k = -10, -40, -(p + 10): the
    census's 120 lanes."""
    return [ratio_lane(fmt, ratio_k(fmt, k), j) for k in RATIO_KS
            for j in range(1, RATIO_JCAP + 1)]


def census_near(fmt, fn, J=64):
    """The windows next to pi/2 and pi: 2 J + 1 arguments about the centre
    of each of the census's two nearest boundaries of each kind."""
    out = []
    const = WINDOW_CONST[fn]
    for kind in KINDS:
        for i in range(2):
            v0 = window_centre(fmt, fn, const, kind, i)
            for j in range(-J, J + 1):
                out.append(window_lane(fn, fmt, v0 + j))
    return out


def census_lanes(fmt, fn):
    """{family: [lane]} the study's census of the function at the format."""
    out = {}
    if fn in TINY_FNS:
        out["tiny"] = census_tiny(fmt, fn)
    if fn in WINDOW_CONST:
        out["near"] = census_near(fmt, fn)
    if fn in ("asin", "acos"):
        out["near1"] = census_near1(fmt, fn)
    if fn == "atan2":
        out["ratio"] = census_ratio(fmt)
        out["diag"] = census_diag(fmt)
    return out


# ---- the lanes of the committed entries -------------------------------------------

def _label(centre):
    if centre[0] == "tiny":
        return f"{centre[1]} 2^-{centre[2]}"
    return f"{centre[1]} {centre[2]} {centre[3]}"


def ratio_edge_lanes(fmt, rnd, k, G=None):
    """[(j, label)]: the ratio family's edge at k for the attribute's class:
    the largest j the theory demands marked, one past it, and the smallest it
    calls clear."""
    cls = cls_of(rnd)
    j = _ratio_threshold(fmt, cls, k)
    if not j:
        return []
    rep = rep_of(cls)
    kk = ratio_k(fmt, k)
    lo, hi = j, j * 2
    while classify(fmt, rep, "atan2", ratio_lane(fmt, kk, hi), G) != "clear":
        hi *= 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if classify(fmt, rep, "atan2", ratio_lane(fmt, kk, mid), G) == "clear":
            hi = mid
        else:
            lo = mid
    return [(j, "last j demanded marked"), (j + 1, "first j past it"),
            (hi, "first j the theory calls clear")]


def family_lanes(fmt, rnd, fn, ents, G=None):
    """[(lane, label, family, what the theory demands)] for the entries'
    centres, their negatives and their neighbours (the first four inside the
    window, the rest outside), for atan2 the ratio family's lanes (j = 1 to 40
    at each k and the threshold's edge), and the claims of zero's lanes; each
    lane once."""
    seen, out = set(), []

    def add(lane, label, fam):
        if lane not in seen:
            seen.add(lane)
            out.append((lane, label, fam, classify(fmt, rnd, fn, lane, G)))
    for cen in expand(ents):
        if cen[0] in ("tiny", "win"):
            x0 = centre_lane(fn, fmt, cen)
            add(x0, f"{_label(cen)} centre", cen[0] + "-centre")
            add(negated(fn, fmt, x0), f"{_label(cen)} centre (-)", cen[0])
            for lane, lab in neighbours(fmt, fn, cen, G):
                add(lane, f"{_label(cen)} {lab}", cen[0])
    if fn == "atan2":
        for en in ents:
            if en[0] == "ratio":
                # the listed threshold: its last j is a lane the theory must
                # demand marked (a threshold one too high lists a lane it does
                # not)
                kk = ratio_k(fmt, en[1])
                add(ratio_lane(fmt, kk, en[2]),
                    f"2^{kk} / (1 + {en[2]} ulp): the listed threshold",
                    "ratio-listed")
        for k in RATIO_KS:
            kk = ratio_k(fmt, k)
            for j in range(1, RATIO_JCAP + 1):
                add(ratio_lane(fmt, kk, j), f"2^{kk} / (1 + {j} ulp)", "ratio")
            for j, lab in ratio_edge_lanes(fmt, rnd, k, G):
                add(ratio_lane(fmt, kk, j), f"2^{kk} / (1 + {j} ulp): {lab}",
                    "ratio")
    for en in ents:
        if en[0] == "zero" and en[1] == "near1":
            for lane in census_near1(fmt, fn):
                add(lane, f"near 1: {hex(lane)}", "near1")
        if en[0] == "zero" and en[1] == "diag":
            for lane in census_diag(fmt, en[2], en[3]):
                add(lane, "diagonal " + str(tuple(hex(v) for v in lane)),
                    "diag")
    return out


# ---- the checks ---------------------------------------------------------------------
#
# Each finding begins with its check's name and a colon. The checks hold a
# fragment (and the committed list) to the theory above; the theory shares
# nothing with the fragment: it reads mpmath at 4p + 200 bits and exact
# rationals.

MARK = ml.MARK
CHECKS = ("family_list", "family", "off_list", "windows", "census_counts",
          "struct", "pool_marks")


def _lane_name(lane):
    return ("(" + ", ".join(hex(v) for v in lane) + ")"
            if isinstance(lane, tuple) else hex(lane))


def _tally(fmt, rnd, fn, lanes, results):
    """([marked lanes], [(lane, bits, golden) of marked guesses that differ],
    [(lane, got, want) of unmarked lanes that differ], [stray flag words])."""
    marked, gw, wrong, stray = [], [], [], []
    for x, (bits, fw) in zip(lanes, results):
        gb, gf = I.golden(fmt, rnd, x, fn)
        if fw & ~(MARK | 0x1F):
            stray.append((x, fw))
        if fw & MARK:
            marked.append(x)
            if (bits, fw & 0x1F) != (gb, gf):
                gw.append((x, bits, gb))
        elif (bits, fw) != (gb, gf):
            wrong.append((x, (bits, fw), (gb, gf)))
    return marked, gw, wrong, stray


def check_family_list(committed, generated=None):
    """[finding]: family_list. The committed entries (INV_FAMILY, or a copy a
    test has tampered with) are exactly what the theory generates, for every
    function, format and attribute."""
    generated = generate() if generated is None else generated
    out = []
    for fn in sorted(set(committed) | set(generated)):
        cfn, gfn = committed.get(fn, {}), generated.get(fn, {})
        for fmt_name in sorted(set(cfn) | set(gfn)):
            for rnd_name in sorted(set(cfn.get(fmt_name, {}))
                                   | set(gfn.get(fmt_name, {}))):
                have = cfn.get(fmt_name, {}).get(rnd_name)
                want = gfn.get(fmt_name, {}).get(rnd_name)
                if have != want:
                    hc = set(expand(have or ()))
                    wc = set(expand(want or ()))
                    miss = sorted(wc - hc, key=str)
                    extra = sorted(hc - wc, key=str)
                    out.append(f"family_list: the committed entries of {fn} "
                               f"{fmt_name} {rnd_name} are not the theory's: "
                               f"missing {miss[:3]}, extra {extra[:3]}")
    return out


def check_family(f, ents, G=None, extra=(), deep=False, evaluator=None):
    """[finding], stats: family and off_list. On the entries' centres,
    their negatives and neighbours, the ratio family, the claims of zero's
    lanes, `extra` (arguments, such as the census's, that are not centres)
    and, with `deep`, deep_arguments: the routine marks every lane the theory
    says is inside a window (d under 1 - B), is right on every lane it does
    not mark (family:); every marked guess is COUNTED (st["guess_wrong"]), not
    judged: a replay decides a marked lane; and marks no lane
    the theory calls clear (d over 1 + B) or gated (off_list: a mark off the
    list). `evaluator` stands for ml.evaluate, for the test that doctors a
    lane."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    lanes = family_lanes(fmt, rnd, fn, ents, G)
    seen = {x for x, _l, _f, _c in lanes}
    more = [(x, f"argument {_lane_name(x)}", "extra") for x in extra]
    if deep:
        more += [(x, f"deep {lab}", "deep")
                 for x, lab in deep_arguments(fmt, fn, G)]
    for x, lab, fam in more:
        if x not in seen:
            seen.add(x)
            lanes.append((x, lab, fam, classify(fmt, rnd, fn, x, G)))
    ev = evaluator or ml.evaluate
    res = [ev(f, x) for x, _l, _f, _c in lanes]
    out = []
    st = {"lanes": len(lanes), "guess_wrong": 0, "wrong": 0}
    for w in ("mark", "clear", "either", "gated"):
        st[w] = st["marked_" + w] = 0
    tag = f"{fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    for (x, lab, fam, want), (bits, fw) in zip(lanes, res):
        marked = bool(fw & MARK)
        gb, gf = I.golden(fmt, rnd, x, fn)
        st[want] += 1
        if marked:
            st["marked_" + want] += 1
            if (bits, fw & 0x1F) != (gb, gf):
                st["guess_wrong"] += 1
        elif (bits, fw) != (gb, gf):
            st["wrong"] += 1
            out.append(f"family: {tag}: {lab} ({_lane_name(x)}) is unmarked "
                       f"and wrong: got ({bits:#x}, {fw:#x}), want "
                       f"({gb:#x}, {gf:#x})")
        if fam in ("near1", "diag") and want not in ("clear", "gated"):
            out.append(f"family: {tag}: {lab} ({_lane_name(x)}) is in a "
                       f"family claimed to mark nothing and the theory says "
                       f"{want} (d = {_d(fmt, rnd, fn, x, G):.3f})")
        if fam.endswith(("-centre", "-listed")) and want != "mark":
            out.append(f"family: {tag}: {lab} ({_lane_name(x)}) is LISTED "
                       f"and the theory does not demand it marked (d = "
                       f"{_d(fmt, rnd, fn, x, G):.3f}, {want})")
        if want == "mark" and not marked:
            out.append(f"family: {tag}: {lab} ({_lane_name(x)}) is inside a "
                       f"window, d = "
                       f"{_d(fmt, rnd, fn, x, G):.3f}, and not marked")
        if want in ("clear", "gated") and marked:
            why = "gated" if want == "gated" else "past 1 + B"
            out.append(f"off_list: {tag}: {lab} ({_lane_name(x)}) is marked "
                       f"and the theory calls it {why}: a mark off the list")
    return out[:8], st


def _d(fmt, rnd, fn, lane, G=None):
    try:
        return distance(fmt, rnd, fn, lane, G)
    except (ValueError, ZeroDivisionError):
        return float("nan")


def check_off_list(f, lanes, results=None, G=None, evaluator=None):
    """[finding], marks: off_list. Every lane of `lanes` that the fragment
    marks is predicted by the theory (d under 1 + B, or in atan2's
    tiny-quotient range or its band): any other mark is a finding. The
    census, the pools and the families' runs go through it."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    ev = evaluator or ml.evaluate
    if results is None:
        results = [ev(f, x) for x in lanes]
    marks, out = [], []
    for x, (_b, fw) in zip(lanes, results):
        if fw & MARK:
            marks.append(x)
            if not predicted(fmt, rnd, fn, x, G):
                out.append(f"off_list: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: "
                           f"{_lane_name(x)} is marked and is not predicted "
                           f"(d = {_d(fmt, rnd, fn, x, G):.3g}, over "
                           f"{thresholds(fmt, fn)[1]:.3f}): a mark off the "
                           f"list")
    return out[:8], marks


def check_windows(f, centres_, G=None, evaluator=None, edges=None):
    """[finding], n: windows. For each tiny or window centre the window's
    EDGES on each side, exact by the theory (window_edges: the largest j whose
    lane the theory demands marked and the smallest it calls clear, by search
    and bisection, whatever the width): the lanes at the inner edge and half
    way to it must be marked and the lanes at the outer edge and twice as far
    unmarked, every unmarked lane right (a marked guess is not judged); and the
    half-width the study's 3.5 computes (half_width) must agree with the exact
    edges: the outer edge within (clear -+ d0) W and the inner within (must -+
    d0) W, d0 the centre's own d (a power of two has the finer ulp on one side,
    twice as many steps).
    `edges` the window_edges to use, `evaluator` stands for ml.evaluate."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    ev = evaluator or ml.evaluate
    out, n = [], 0
    for cen in centres_:
        if cen[0] not in ("tiny", "win"):
            continue
        x0 = centre_lane(fn, fmt, cen)
        v0 = varied(x0)
        W = float(half_width(fmt, fn, cen, v0, G))
        fine = 2.0 if v0 & fmt.man_mask == 0 else 1.0
        t_must, t_clear = thresholds(fmt, fn)
        d0 = distance(fmt, rnd, fn, x0, G)
        es = window_edges(fmt, rnd, fn, cen, G) if edges is None else edges
        for side, (j_in, j_out) in sorted(es.items()):
            where = (f"windows: {fn} {fmt.name} {sf.RND_NAMES[rnd]} "
                     f"{_label(cen)} {'above' if side > 0 else 'below'}")
            if j_out is None:
                out.append(f"{where}: no lane of a binade's worth of steps "
                           f"is clear: the window has no outer edge")
                continue
            # the marked lanes are |s + j| < must W (s the centre's signed
            # offset from the boundary in ulps, |s| = d0 W): the inner edge
            # j_in lies in ((t_must - d0) W, (t_must + d0) W) and the outer in
            # ((t_clear - d0) W, (t_clear + d0) W), a power of two's finer ulp
            # making one side up to twice as many steps
            tol = 1 + 1e-9                  # W is a float of a Fraction
            if not ((t_clear - d0) * W / fine / tol - 2 <= j_out
                    <= (t_clear + d0) * W * fine * tol + 2) or \
                    not ((t_must - d0) * W / fine / tol - 2 <= j_in
                         <= (t_must + d0) * W * fine * tol + 2):
                out.append(f"{where}: the computed half-width W = {W:.4g} "
                           f"does not agree with the exact window, inner "
                           f"edge j = {j_in}, outer edge j = {j_out}")
            for j, must, label in ((j_in, True, "inner edge"),
                                   (j_in // 2, True, "half way to it"),
                                   (j_out, False, "outer edge"),
                                   (min(2 * j_out, 1 << fmt.man_w), False,
                                    "twice as far")):
                lane = with_varied(x0, v0 + side * j)
                bits, fw = ev(f, lane)
                gb, gf = I.golden(fmt, rnd, lane, fn)
                n += 1
                marked = bool(fw & MARK)
                if must and not marked:
                    out.append(f"{where}: the lane at the {label} (j = {j}, "
                               f"d = {_d(fmt, rnd, fn, lane, G):.3f}) is "
                               f"inside the window and not marked")
                if not must and marked:
                    out.append(f"{where}: the lane at the {label} (j = {j}, "
                               f"d = {_d(fmt, rnd, fn, lane, G):.3f}) is "
                               f"outside the window and marked")
                if not marked and (bits, fw) != (gb, gf):
                    out.append(f"{where}: the unmarked lane at the {label} "
                               f"(j = {j}) is wrong")
    return out[:8], n


# The study's census counts (3.5, MEASURED by census.py, every lane against
# transcend.py: 0 wrong, every guess counted): the marks of ONE attribute, as
# (under rne or rmm, under each of the directed three).
#   tiny    c = 1 to 16 over the exponents (census_tiny), both signs (atan2:
#           against x = 1, 3 and 5 2^7)
TINY_COUNTS = {
    "fp64": {"atan": (6, 0), "asin": (0, 6), "atan2": (18, 0)},
    "fp128": {"atan": (10, 136), "asin": (0, 140), "atan2": (30, 408)},
    "fp256": {"atan": (10, 446), "asin": (0, 450), "atan2": (30, 1338)},
}
#   near    the windows: 129 arguments about each of the census's two
#           boundaries of each kind: every lane of a kind's windows marks
#           under that kind's attributes (258 a kind) and none under the
#           other's
NEAR_COUNT = 2 * 129
#   ratio   atan2(2^k, 1 + j ulp), j = 1 to 40, k = -(p + 10): the directed
#           three mark 11, 40 and 40 (the threshold j < 2^((p - G - 2)/2)),
#           the others and the other k none
RATIO_COUNTS = {"fp64": 11, "fp128": 40, "fp256": 40}
#   near1, diag: none (the claims of zero)


def census_expect(fmt, fn, rnd, family):
    """The study's count of marks for one attribute on the census family, or
    None where the study states none."""
    nearest = rnd in NEAREST
    if family == "tiny":
        return TINY_COUNTS[fmt.name][fn][0 if nearest else 1]
    if family == "near":
        # the first two boundaries of the kind the attribute marks under:
        # 2 x 129 lanes of that kind, none of the other
        return NEAR_COUNT
    if family == "ratio":
        return 0 if nearest else RATIO_COUNTS[fmt.name]
    return 0                                    # near1, diag


def check_census_counts(f, family, lanes=None, want=None, evaluator=None,
                        G=None):
    """[finding], marks: census_counts. The study's census of `family`
    ("tiny", "near", "near1", "ratio", "diag") through the fragment marks the
    counted lanes (`want`, or census_expect), every lane the theory demands
    marked (d under 1 - B) is among them, none the theory calls clear, and no
    unmarked lane is wrong (a marked guess is counted by the caller, not
    judged)."""
    fmt, rnd, fn = f.fmt, f.rnd, f.op
    if lanes is None:
        lanes = census_lanes(fmt, fn)[family]
    ev = evaluator or ml.evaluate
    res = [ev(f, x) for x in lanes]
    marked, _gw, wrong, _stray = _tally(fmt, rnd, fn, lanes, res)
    if want is None:
        want = census_expect(fmt, fn, rnd, family)
    if family == "near":
        # the windows of the kind this attribute marks under: the lanes of
        # the other kind are unmarked, so the count is the kind's alone
        want = NEAR_COUNT
    where = f"census_counts: {family} {fn} {fmt.name} {sf.RND_NAMES[rnd]}"
    out = []
    if len(marked) != want:
        out.append(f"{where}: {len(marked)} of the census's {len(lanes)} "
                   f"arguments are marked, the study's count is {want}")
    if wrong:
        out.append(f"{where}: {len(wrong)} census lanes are wrong unmarked, "
                   f"first {_lane_name(wrong[0][0])}")
    ms = set(marked)
    missing = [x for x in lanes
               if classify(fmt, rnd, fn, x, G) == "mark" and x not in ms]
    if missing:
        out.append(f"{where}: {len(missing)} lanes the theory demands marked "
                   f"(d under 1 - B) are not, first "
                   f"{_lane_name(missing[0])}")
    clear = [x for x in marked
             if classify(fmt, rnd, fn, x, G) in ("clear", "gated")]
    if clear:
        out.append(f"off_list: {where}: {len(clear)} marked lanes the theory "
                   f"calls clear (d over 1 + B), first "
                   f"{_lane_name(clear[0])}")
    return out, marked


def struct_report(fmt, rnd, fn, table=None):
    """[(lane, d)]: every lane of the harness's STRUCT for (fn, fmt, rnd)
    (structured_lanes: each also with its sign flipped), its d under rnd."""
    return [(x, distance(fmt, rnd, fn, x))
            for x in I.structured_lanes(fn, fmt, rnd, table)]


def check_struct(fmt, rnd, fn, table=None):
    """[finding], report: struct. Every committed lane of the harness's STRUCT
    (waves 1 and 2's) held to the predicate: d under 1 - B under each of its
    listed attributes. The predicate shares nothing with the fragment."""
    must, _clear = thresholds(fmt, fn)
    rep = struct_report(fmt, rnd, fn, table)
    out = [f"struct: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: the committed lane "
           f"{_lane_name(x)} has d = {d:.4f}, not under {must:.3f}"
           for x, d in rep if not d < must]
    return out, rep


def check_pool_marks(marks=None):
    """[finding], n: pool_marks. Every mark of the pools committed in
    mathlib_inv_harness.INV_POOL_MARKS (function, format, attribute, lane,
    reason) is predicted by the theory (d under 1 + B, or atan2's
    tiny-quotient range): the pools keep M4G1's check (check_pools), and
    this reads the same list and holds each lane to the theory."""
    marks = I.INV_POOL_MARKS if marks is None else marks
    out = []
    for fn, fmt_name, rnd_name, lane, _reason in marks:
        fmt, rnd = I.BY_NAME[fmt_name], I.RND_BY_NAME[rnd_name]
        if not predicted(fmt, rnd, fn, lane):
            out.append(f"pool_marks: {fn} {fmt_name} {rnd_name} "
                       f"{_lane_name(lane)} is marked in the pools and the "
                       f"theory does not predict it (d = "
                       f"{_d(fmt, rnd, fn, lane):.3g})")
    return out, len(marks)


def listed_between(fmt, rnd, fn, ents=None):
    """(listed, between): the number of listed centres (tiny and window, as
    expand gives them) of the function at the format under the attribute,
    and how many of them have d from 0.7 up to (but not including) 1 - B: the
    lanes that the fixed 0.7 of M2's rule would not have listed."""
    must, _clear = thresholds(fmt, fn)
    cs = [c for c in expand(entries(fmt, rnd, fn) if ents is None else ents)
          if c[0] in ("tiny", "win")]
    n = sum(0.7 <= distance(fmt, rnd, fn, centre_lane(fn, fmt, c)) < must
            for c in cs)
    return len(cs), n


# The tool's faults, for the tests (never INV_PLANTS): each acts on the list or
# on the theory's width, never on the fragment.
TOOL_PLANTS = {
    "list_edited": "the committed list edited by hand: a centre added that "
                   "the theory does not generate",
    "centre_dropped": "a generated centre left out of the committed list",
    "halfwidth_halved": "a window's half-width computed at half its value",
    "ratio_off_by_one": "the ratio family's threshold one too high",
}


# ---- the committed list, written ---------------------------------------------------

# The line that starts the generated tail of this file. Built from two pieces
# so that this line does not itself contain it.
_MARKER = ("# ---- GENERATED by "
           + "python/tests/mathlib_runs.py inv-family --write")
NL = chr(10)


def _token(en):
    return repr(tuple(en)) + ","


def render(data):
    """The generated tail of this file: INV_FAMILY as text, each distinct list
    of entries written once and named by every function, format and attribute
    that has it."""
    out = [_MARKER + ": entries",
           "#",
           "# {fn: {format: {attribute: [entry]}}}: an entry is ('tiny', c, e0,",
           "# e1), the centres c 2^-e for e = e0 .. e1 (c odd, below 2^CBITS);",
           "# ('win', const, kind, i), the window about the i-th boundary of",
           "# the kind below the constant; ('ratio', k, j), atan2(2^k, 1 + j'",
           "# ulp) for j' = 1 .. j ('deep' is k = -(p + 10)); ('zero', family,",
           "# ...), a claim that the family marks nothing. Each centre's f",
           "# lies within 1 - B of the nominal bound of a rounding boundary",
           "# under that attribute. The directed three share their",
           "# boundaries, and so do rne and rmm.",
           ""]
    names = {}
    for fn, per_fmt in data.items():
        for fmt_name, per in per_fmt.items():
            for lst in per.values():
                key = (fn, fmt_name, tuple(lst))
                if key in names:
                    continue
                names[key] = f"_{fn.upper()}_{fmt_name.upper()}_{len(names) + 1}"
                if not lst:
                    out.append(f"{names[key]} = []")
                    continue
                lines, line = [], "    "
                for en in lst:
                    tok = _token(en)
                    if len(line) + len(tok) + 1 > 78:
                        lines.append(line.rstrip())
                        line = "    "
                    line += tok + " "
                if line.strip():
                    lines.append(line.rstrip())
                out.append(f"{names[key]} = [" + NL + NL.join(lines) + NL
                           + "]")
    out += ["", "INV_FAMILY = {"]
    for fn, per_fmt in data.items():
        out.append(f'    "{fn}": {{')
        for fmt_name, per in per_fmt.items():
            out.append(f'        "{fmt_name}": {{')
            for rnd_name, lst in per.items():
                out.append(f'            "{rnd_name}": '
                           f'{names[(fn, fmt_name, tuple(lst))]},')
            out.append("        },")
        out.append("    },")
    out.append("}")
    return NL.join(out) + NL


def write(path=None, data=None):
    """Regenerate INV_FAMILY into this file (everything from the marker)."""
    path = Path(path or __file__)
    text = path.read_text(encoding="utf-8")
    head = text[:text.index(_MARKER)] if _MARKER in text else text
    path.write_text(head + render(generate() if data is None else data),
                    encoding="utf-8", newline=NL)
# ---- GENERATED by python/tests/mathlib_runs.py inv-family --write: entries
#
# {fn: {format: {attribute: [entry]}}}: an entry is ('tiny', c, e0,
# e1), the centres c 2^-e for e = e0 .. e1 (c odd, below 2^CBITS);
# ('win', const, kind, i), the window about the i-th boundary of
# the kind below the constant; ('ratio', k, j), atan2(2^k, 1 + j'
# ulp) for j' = 1 .. j ('deep' is k = -(p + 10)); ('zero', family,
# ...), a claim that the family marks nothing. Each centre's f
# lies within 1 - B of the nominal bound of a rounding boundary
# under that attribute. The directed three share their
# boundaries, and so do rne and rmm.

_ATAN_FP64_1 = [
    ('tiny', 3, 26, 26), ('win', 'pio2', 'mid', 0),
    ('win', 'pio2', 'mid', 1), ('win', 'pio2', 'mid', 2),
]
_ATAN_FP64_2 = [
    ('win', 'pio2', 'grid', 0), ('win', 'pio2', 'grid', 1),
    ('win', 'pio2', 'grid', 2),
]
_ATAN_FP128_3 = [
    ('tiny', 3, 56, 56), ('tiny', 9, 55, 55), ('tiny', 15, 55, 55),
    ('tiny', 33, 54, 54), ('tiny', 39, 54, 54), ('tiny', 45, 54, 54),
    ('tiny', 51, 54, 54), ('tiny', 57, 54, 54), ('tiny', 63, 54, 54),
    ('win', 'pio2', 'mid', 0), ('win', 'pio2', 'mid', 1),
    ('win', 'pio2', 'mid', 2),
]
_ATAN_FP128_4 = [
    ('tiny', 3, 41, 55), ('tiny', 9, 43, 54), ('tiny', 15, 44, 54),
    ('tiny', 21, 44, 54), ('tiny', 27, 44, 54), ('tiny', 33, 45, 53),
    ('tiny', 39, 45, 53), ('tiny', 45, 45, 53), ('tiny', 51, 45, 53),
    ('tiny', 57, 46, 53), ('tiny', 63, 46, 53), ('win', 'pio2', 'grid', 0),
    ('win', 'pio2', 'grid', 1), ('win', 'pio2', 'grid', 2),
]
_ATAN_FP256_5 = [
    ('tiny', 3, 118, 118), ('tiny', 9, 117, 117), ('tiny', 15, 117, 117),
    ('tiny', 33, 116, 116), ('tiny', 39, 116, 116), ('tiny', 45, 116, 116),
    ('tiny', 51, 116, 116), ('tiny', 57, 116, 116), ('tiny', 63, 116, 116),
    ('win', 'pio2', 'mid', 0), ('win', 'pio2', 'mid', 1),
    ('win', 'pio2', 'mid', 2),
]
_ATAN_FP256_6 = [
    ('tiny', 3, 72, 117), ('tiny', 9, 74, 116), ('tiny', 15, 75, 116),
    ('tiny', 21, 75, 116), ('tiny', 27, 75, 116), ('tiny', 33, 76, 115),
    ('tiny', 39, 76, 115), ('tiny', 45, 76, 115), ('tiny', 51, 76, 115),
    ('tiny', 57, 77, 115), ('tiny', 63, 77, 115), ('win', 'pio2', 'grid', 0),
    ('win', 'pio2', 'grid', 1), ('win', 'pio2', 'grid', 2),
]
_ASIN_FP64_7 = [
    ('zero', 'near1', 64),
]
_ASIN_FP64_8 = [
    ('tiny', 3, 25, 25), ('zero', 'near1', 64),
]
_ASIN_FP128_9 = [
    ('tiny', 21, 54, 54), ('tiny', 27, 54, 54), ('zero', 'near1', 64),
]
_ASIN_FP128_10 = [
    ('tiny', 3, 41, 55), ('tiny', 9, 42, 54), ('tiny', 15, 43, 54),
    ('tiny', 21, 44, 53), ('tiny', 27, 44, 53), ('tiny', 33, 44, 53),
    ('tiny', 39, 45, 53), ('tiny', 45, 45, 53), ('tiny', 51, 45, 53),
    ('tiny', 57, 45, 53), ('tiny', 63, 45, 53), ('zero', 'near1', 64),
]
_ASIN_FP256_11 = [
    ('tiny', 21, 116, 116), ('tiny', 27, 116, 116), ('zero', 'near1', 64),
]
_ASIN_FP256_12 = [
    ('tiny', 3, 72, 117), ('tiny', 9, 73, 116), ('tiny', 15, 74, 116),
    ('tiny', 21, 75, 115), ('tiny', 27, 75, 115), ('tiny', 33, 75, 115),
    ('tiny', 39, 76, 115), ('tiny', 45, 76, 115), ('tiny', 51, 76, 115),
    ('tiny', 57, 76, 115), ('tiny', 63, 76, 115), ('zero', 'near1', 64),
]
_ACOS_FP64_13 = [
    ('win', 'pio2', 'mid', 0), ('win', 'pio2', 'mid', 1),
    ('win', 'pio2', 'mid', 2), ('zero', 'near1', 64),
]
_ACOS_FP64_14 = [
    ('win', 'pio2', 'grid', 0), ('win', 'pio2', 'grid', 1),
    ('win', 'pio2', 'grid', 2), ('zero', 'near1', 64),
]
_ACOS_FP128_15 = [
    ('win', 'pio2', 'mid', 0), ('win', 'pio2', 'mid', 1),
    ('win', 'pio2', 'mid', 2), ('zero', 'near1', 64),
]
_ACOS_FP128_16 = [
    ('win', 'pio2', 'grid', 0), ('win', 'pio2', 'grid', 1),
    ('win', 'pio2', 'grid', 2), ('zero', 'near1', 64),
]
_ACOS_FP256_17 = [
    ('win', 'pio2', 'mid', 0), ('win', 'pio2', 'mid', 1),
    ('win', 'pio2', 'mid', 2), ('zero', 'near1', 64),
]
_ACOS_FP256_18 = [
    ('win', 'pio2', 'grid', 0), ('win', 'pio2', 'grid', 1),
    ('win', 'pio2', 'grid', 2), ('zero', 'near1', 64),
]
_ATAN2_FP64_19 = [
    ('tiny', 3, 26, 26), ('win', 'pi', 'mid', 0), ('win', 'pi', 'mid', 1),
    ('win', 'pi', 'mid', 2), ('zero', 'diag', 40, 4),
]
_ATAN2_FP64_20 = [
    ('win', 'pi', 'grid', 0), ('win', 'pi', 'grid', 1),
    ('win', 'pi', 'grid', 2), ('ratio', 'deep', 11), ('zero', 'diag', 40, 4),
]
_ATAN2_FP128_21 = [
    ('tiny', 3, 56, 56), ('tiny', 9, 55, 55), ('tiny', 15, 55, 55),
    ('tiny', 33, 54, 54), ('tiny', 39, 54, 54), ('tiny', 45, 54, 54),
    ('tiny', 51, 54, 54), ('tiny', 57, 54, 54), ('tiny', 63, 54, 54),
    ('win', 'pi', 'mid', 0), ('win', 'pi', 'mid', 1),
    ('win', 'pi', 'mid', 2), ('zero', 'diag', 40, 4),
]
_ATAN2_FP128_22 = [
    ('tiny', 3, 41, 55), ('tiny', 9, 43, 54), ('tiny', 15, 44, 54),
    ('tiny', 21, 44, 54), ('tiny', 27, 44, 54), ('tiny', 33, 45, 53),
    ('tiny', 39, 45, 53), ('tiny', 45, 45, 53), ('tiny', 51, 45, 53),
    ('tiny', 57, 46, 53), ('tiny', 63, 46, 53), ('win', 'pi', 'grid', 0),
    ('win', 'pi', 'grid', 1), ('win', 'pi', 'grid', 2),
    ('ratio', 'deep', 5979112811), ('zero', 'diag', 40, 4),
]
_ATAN2_FP256_23 = [
    ('tiny', 3, 118, 118), ('tiny', 9, 117, 117), ('tiny', 15, 117, 117),
    ('tiny', 33, 116, 116), ('tiny', 39, 116, 116), ('tiny', 45, 116, 116),
    ('tiny', 51, 116, 116), ('tiny', 57, 116, 116), ('tiny', 63, 116, 116),
    ('win', 'pi', 'mid', 0), ('win', 'pi', 'mid', 1),
    ('win', 'pi', 'mid', 2), ('zero', 'diag', 40, 4),
]
_ATAN2_FP256_24 = [
    ('tiny', 3, 72, 117), ('tiny', 9, 74, 116), ('tiny', 15, 75, 116),
    ('tiny', 21, 75, 116), ('tiny', 27, 75, 116), ('tiny', 33, 76, 115),
    ('tiny', 39, 76, 115), ('tiny', 45, 76, 115), ('tiny', 51, 76, 115),
    ('tiny', 57, 77, 115), ('tiny', 63, 77, 115), ('win', 'pi', 'grid', 0),
    ('win', 'pi', 'grid', 1), ('win', 'pi', 'grid', 2),
    ('ratio', 'deep', 27687380689297756840250768057),
    ('zero', 'diag', 40, 4),
]

INV_FAMILY = {
    "atan": {
        "fp64": {
            "rne": _ATAN_FP64_1,
            "rtz": _ATAN_FP64_2,
            "rdn": _ATAN_FP64_2,
            "rup": _ATAN_FP64_2,
            "rmm": _ATAN_FP64_1,
        },
        "fp128": {
            "rne": _ATAN_FP128_3,
            "rtz": _ATAN_FP128_4,
            "rdn": _ATAN_FP128_4,
            "rup": _ATAN_FP128_4,
            "rmm": _ATAN_FP128_3,
        },
        "fp256": {
            "rne": _ATAN_FP256_5,
            "rtz": _ATAN_FP256_6,
            "rdn": _ATAN_FP256_6,
            "rup": _ATAN_FP256_6,
            "rmm": _ATAN_FP256_5,
        },
    },
    "asin": {
        "fp64": {
            "rne": _ASIN_FP64_7,
            "rtz": _ASIN_FP64_8,
            "rdn": _ASIN_FP64_8,
            "rup": _ASIN_FP64_8,
            "rmm": _ASIN_FP64_7,
        },
        "fp128": {
            "rne": _ASIN_FP128_9,
            "rtz": _ASIN_FP128_10,
            "rdn": _ASIN_FP128_10,
            "rup": _ASIN_FP128_10,
            "rmm": _ASIN_FP128_9,
        },
        "fp256": {
            "rne": _ASIN_FP256_11,
            "rtz": _ASIN_FP256_12,
            "rdn": _ASIN_FP256_12,
            "rup": _ASIN_FP256_12,
            "rmm": _ASIN_FP256_11,
        },
    },
    "acos": {
        "fp64": {
            "rne": _ACOS_FP64_13,
            "rtz": _ACOS_FP64_14,
            "rdn": _ACOS_FP64_14,
            "rup": _ACOS_FP64_14,
            "rmm": _ACOS_FP64_13,
        },
        "fp128": {
            "rne": _ACOS_FP128_15,
            "rtz": _ACOS_FP128_16,
            "rdn": _ACOS_FP128_16,
            "rup": _ACOS_FP128_16,
            "rmm": _ACOS_FP128_15,
        },
        "fp256": {
            "rne": _ACOS_FP256_17,
            "rtz": _ACOS_FP256_18,
            "rdn": _ACOS_FP256_18,
            "rup": _ACOS_FP256_18,
            "rmm": _ACOS_FP256_17,
        },
    },
    "atan2": {
        "fp64": {
            "rne": _ATAN2_FP64_19,
            "rtz": _ATAN2_FP64_20,
            "rdn": _ATAN2_FP64_20,
            "rup": _ATAN2_FP64_20,
            "rmm": _ATAN2_FP64_19,
        },
        "fp128": {
            "rne": _ATAN2_FP128_21,
            "rtz": _ATAN2_FP128_22,
            "rdn": _ATAN2_FP128_22,
            "rup": _ATAN2_FP128_22,
            "rmm": _ATAN2_FP128_21,
        },
        "fp256": {
            "rne": _ATAN2_FP256_23,
            "rtz": _ATAN2_FP256_24,
            "rdn": _ATAN2_FP256_24,
            "rup": _ATAN2_FP256_24,
            "rmm": _ATAN2_FP256_23,
        },
    },
}
