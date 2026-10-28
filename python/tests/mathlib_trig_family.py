# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The structured families of sin, cos and tan (parcel M2G2b): the windows of
arguments next to an exact case, which the in-lane test marks and a replay
decides (docs/studies/M2-trig.md, section 3.5; Logan's answer 7: "keep the
structured families' marks, with their centres listed in the tests").

WHY THERE IS A FAMILY, and where. For x tiny, sin x = x - x^3/6 + x^5/120 ...,
tan x = x + x^3/3 + 2 x^5/15 ... and cos x = 1 - x^2/2 + x^4/24 .... Where x^3/6
(sin), x^3/3 (tan) or x^2/2 (cos) lands on the result's grid, a float, or on a
midpoint of two floats, the true value sits x^5/120 (2 x^5/15, x^4/24) from a
rounding boundary of the attribute: a grid point under the directed three, a
midpoint under rne and rmm. The in-lane test cannot decide such a lane while
that is under the bound Bv = 2^-(p+G) |V_h|; it marks it, and the replay
decides it. For x = c 2^-e, c an odd integer of b bits (the study's 3.5,
COMPUTED there, redone here from the fragment's ulp):

  sin     x^3/6 = (c^3/3) 2^(p - b - 2e - 1) ulps of x: a whole number of them
          when 3 | c and 2e <= p - b - 1 (the directed three), an odd number of
          halves when 3 | c and 2e = p - b (rne and rmm: b of the parity of p,
          3 2^-11 at fp32, 21 and 27 2^-54 at fp128 and 2^-116 at fp256 for
          b = 5, none at fp64 inside the bound). x^4 < 120 2^-(p+G) bounds it
          below: e above about b + (p + G - 7)/4, so b below about (p - G + 7)/6:
          c up to 2^12 at fp128 and 2^33 at fp256, 3 2^-25 at fp64
  tan     the same with x^3/3 and 2 x^5/15 (3 2^-26 under rne and rmm at fp64)
  cos     x^2/2 = c^2 2^(-2e-1) a whole number of the grid's steps 2^-p below 1
          when 2e + 1 <= p: c = 1 to 7 2^-26 at fp64 (the study's 14 arguments
          are seven centres), x^4 < 24 2^-(p+G) bounding log2(c) below by about
          (p - G + 3)/4: c up to 2^17 at fp128 and 2^48 at fp256. A midpoint
          needs c^2 2^(p-2e-1) to be an odd number of halves, which an odd c
          and p odd never give exactly (none for c < 64, nor in the study's
          census), but c = 2^k +- 1 gives it to within 2^-(2e+1) when 2e = p + k
          + 1: the four lanes of deep_arguments() at fp256 (c = 2^46 - 1,
          2^46 + 1 and 3 2^46 - 1 at 2^-142, 3 2^48 - 1 at 2^-143)

and the NEIGHBOURS OF THE ARGUMENTS NEAREST MULTIPLES OF pi/2 (verifier-VM2S's
family, the study's 3.5): with x = m0 2^E + j ulp, m0 the minimiser of the
binade, r = x - k pi/2 = j ulp + delta with delta tiny, and sin next to odd
multiples (cos next to even ones) about +-cos r = 1 - r^2/2: (j ulp)^2/2 lands on
the result's grid below 1 once E is about p/2 or more, and the true value then
sits (j ulp)^4/24 + j ulp delta from a grid point: the tiny family with (j
ulp)^2/2 in the place of x^2/2. The minimisers themselves (j = 0) mark none.

EACH CENTRE IS A WINDOW. A neighbour x + j ulp(x) moves the true value's
distance from the boundary by about j ulp(x) x^2/2 for sin, j ulp(x) x^2 for tan
and j x ulp(x) for cos, which is much less than the value's ulp (the study's
3.5), so it marks too while that stays inside Bv: half_width() computes it, in
ulps of x, from the closed forms the study gives. The minimisers' neighbours are
isolated lanes (the window beyond |j| = 4 is not measured by the study).

THE THEORY, independent of the fragment. For an argument x and an attribute,
d(x) is the distance from |f(x)|, mpmath at 4p + 200 bits, to the nearest
rounding boundary of the result under the attribute's class, in units of the
nominal bound 2^-(p+G) |f(x)|. Under sin and cos the grid point +-1 is not a
boundary (|sin x| < 1 and |cos x| < 1 for every nonzero dyadic x, and the
routine clamps its roundings to the float below 1 under rtz and rdn, and
to 1 under the others, so that a true value just under 1 is decided; the top
cell of [1/2, 1) has only its lower grid point and its midpoint). The routine
marks a lane when V +- Bv straddles a boundary, and V is within 0.17 Bv of f(x)
(the budget, mathlib_trig_budget), so:

  d < 0.7        the lane MUST be marked;
  d > 1.3        the lane must NOT be marked, and is right unmarked;
  between        either: if marked, its guess is counted, not judged;
  gated          never marked: the tiny gate (|x| < 2^gs for sin, 2^gc for
                 cos and tan: decided by the neighbour rules), the zeros, the
                 infinities and NaNs, and past the stated range, where the lane
                 is marked whatever the test says.

THE COMMITTED LIST (TRIG_FAMILY, at the end of this file) is
TRIG_FAMILY[fn][fmt][rnd] = [entry, ...], an entry
  (c, e0, e1)          the centres c 2^-e, e = e0 .. e1, c an odd integer below
                       2^CBITS, both signs, whose d is under 0.7
  ("m", (v, ...), (j, ...))  the minimisers of the binades of value exponents
                       v (those with the same neighbours) and their neighbours
                       m0 + j at those j, positive (sin is odd and cos even,
                       the directed three cover the mirror)
GENERATED by generate() from the theory alone, and held to a fresh generation
by test_mathlib_trig.py, so it can neither go stale nor be edited by hand to
agree with a fault.

THE BOUND ON c. At fp128 and fp256 the family runs to the c above: more
centres than can be listed or replayed at fp256. The committed list is a SAMPLE:
c below 2^CBITS = 64, which holds the study's census (c <= 16, its 144, 384 and
880 arguments) and the next two bit lengths, every centre the theory finds
there. The family beyond is held by deep_arguments(): for each bit length from
CBITS + 1 to two past where the theory's window closes, the smallest, the middle
and the largest odd c (the odd multiples of 3 for sin and tan), at the window's
exponents and one either side, each lane classified by the theory and run
through the fragment, not listed. The census counts of the study (c <= 16) and
the minimisers' (MINNBR_RANGE) are tables of test_mathlib_trig.py.

    python python/tests/mathlib_runs.py trig-family --write    regenerate
"""

import functools
import math
import sys
import textwrap
from fractions import Fraction
from pathlib import Path

import mpmath

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / "host" / "tools"))        # pi_worstcase

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

MUST_MARK = 0.7
MUST_NOT = 1.3
RND_NAMES = sf.RND_NAMES
FUNCTIONS = ml.TRIG_NAMES
NEAREST = (sf.RND_RNE, sf.RND_RMM)
CBITS = 6                       # the listed c: odd, below 2^CBITS
# (label, multiple of W in ulps; None for exactly one ulp): the first N_INSIDE
# inside a window, the rest outside it (mathlib_family's offsets: 0.65 W and
# 1.35 W sit just inside the theory's two thresholds)
OFFSETS = (("1", None), ("W/8", Fraction(1, 8)), ("W/4", Fraction(1, 4)),
           ("0.65W", Fraction(13, 20)), ("1.35W", Fraction(27, 20)),
           ("2W", Fraction(2)), ("8W", Fraction(8)), ("1024W", Fraction(1024)))
N_INSIDE = 4
# the minimisers' binades (value exponents) and neighbours of the study's census
# (3.5: census.py minnbr 40 90 at fp128 and 100 210 at fp256, 0 80 at fp64) and
# j = -J..J
MINNBR_RANGE = {"fp64": (0, 80), "fp128": (40, 90), "fp256": (100, 210)}
MINNBR_J = 4


def cls_of(rnd):
    """"nearest" for rne and rmm (a midpoint), "directed" for rtz, rdn, rup (a
    grid point): the two sets of lanes an attribute can mark."""
    return "nearest" if rnd in NEAREST else "directed"


def _mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


def _true(fn, xv):
    return {"sin": mpmath.sin, "cos": mpmath.cos, "tan": mpmath.tan}[fn](xv)


@functools.lru_cache(maxsize=None)
def _fraction_in_cell(fn, fmt, x):
    """(midpoint, grid point): where |f(x)| lies in its rounding cell, by
    mpmath at 4p + 200 bits, as the distance to the nearest midpoint and to the
    nearest grid point, each relative to |f(x)|; cached, since the attributes
    share it. For sin and cos the grid point 1 is not a boundary (the module
    docstring): the top cell below 1 has only its lower end."""
    p = fmt.prec
    with mpmath.workprec(4 * p + 200):
        T = abs(_true(fn, _mp(ml._dec(fmt, x))))
        e = mpmath.mag(T) - 1                       # floor(log2 T)
        ulp = mpmath.mpf(2) ** (e - p + 1)
        q = T / ulp
        fl = mpmath.floor(q)
        frac = q - fl
        grid = min(frac, 1 - frac)
        if fn != "tan" and fl == 2 ** p - 1 and e == -1:
            grid = frac                             # the top cell below 1
        return (float(abs(frac - mpmath.mpf(1) / 2) * ulp / T),
                float(grid * ulp / T))


def distance(fmt, rnd, x, G=None, fn="sin"):
    """d(x): the distance from |f(x)| to the nearest rounding boundary of the
    result under rnd, in units of 2^-(p+G) |f(x)|. By mpmath."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    mid, grid = _fraction_in_cell(fn, fmt, x)
    return (mid if rnd in NEAREST else grid) / 2.0 ** (-(p + G))


def is_gated(fmt, x, fn):
    """Never marked by the test (or marked whatever it says): a zero, an
    infinity or a NaN; under the tiny gate; at or past the stated range."""
    if sf.unpack(fmt, x).kind in (sf.NAN, sf.INF, sf.ZERO):
        return True
    gs, gc = ml.trig_gates(fmt)
    ax = x & ~fmt.sign_mask
    if ax < ml._pow2(fmt, gs if fn == "sin" else gc):
        return True
    R = ml.TRIG_RANGE[fmt.name]
    return R is not None and ax >= ml._pow2(fmt, R)


def classify(fmt, rnd, x, G=None, fn="sin"):
    """"mark", "clear", "either" or "gated": what the theory demands of the
    routine on x."""
    if is_gated(fmt, x, fn):
        return "gated"
    d = distance(fmt, rnd, x, G, fn)
    return "mark" if d < MUST_MARK else "clear" if d > MUST_NOT else "either"


def half_width(fmt, fn, x, G=None):
    """W: the window's half-width in ulps of x, the study's closed forms (3.5):
    sin Bv / (ulp(x) x^2/2), tan Bv / (ulp(x) x^2) and cos Bv / (x ulp(x)), with
    Bv = 2^-(p+G) |f(x)| (f about x for sin and tan, about 1 for cos). Exact
    (a Fraction). 10.7, 21.3 and 128 at fp64 for 3 2^-25 (sin), 3 2^-26 (tan) and
    2^-26 (cos): the study's 10.8, 21.6 and 128."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    u = sf.unpack(fmt, x)
    lead = u.m.bit_length() - 1 + u.e              # floor(log2 |x|)
    ulp = Fraction(2) ** (lead - p + 1)
    xv = abs(ml._dec(fmt, x))
    Bv = Fraction(1, 2 ** (p + G)) * (1 if fn == "cos" else xv)
    drift = {"sin": xv * xv / 2, "tan": xv * xv, "cos": xv}[fn] * ulp
    return Bv / drift


# ---- the arguments --------------------------------------------------------------

def _gate_exponent(fmt):
    gs, gc = ml.trig_gates(fmt)
    return -min(gs, gc)


def census(fmt, G=None):
    """The study's tiny family (census.py tiny_family): +-c 2^-e for c = 1 to
    16 and e from (p + G)/4 - 4 up to the tiny gate, each distinct value once,
    both signs, sorted: 144, 384 and 880 arguments at fp64, fp128 and fp256 (and
    144 at fp32, G = 18 or 40: the theory takes p and G)."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    out = set()
    for e in range((p + G) // 4 - 4, _gate_exponent(fmt) + 1):
        for c in range(1, 17):
            b = ml._enc(fmt, Fraction(c, 2 ** e))
            out |= {b, b | fmt.sign_mask}
    return sorted(out)


@functools.lru_cache(maxsize=None)
def minimiser(fmt, v):
    """(m, e): the p-bit significand m whose value m 2^e, e = v - p + 1, comes
    closest to a multiple of pi/2 among the floats of the binade of value
    exponent v (host/tools/pi_worstcase.py's worst_in_binade)."""
    import pi_worstcase
    m, e, _lost, _mag, _N = pi_worstcase.worst_in_binade(fmt, v)
    return m, e


def minnbr_arguments(fmt, v0=None, v1=None, J=MINNBR_J):
    """The study's minimisers' neighbours (census.py minnbr_family): the
    minimiser of every binade v0 .. v1 and m0 + j, j = -J .. J, positive, those
    inside the binade; sorted encodings (459, 999 and 729 at fp128 [40, 90],
    fp256 [100, 210] and fp64 [0, 80] for J = 4)."""
    r0, r1 = MINNBR_RANGE[fmt.name]
    v0, v1 = r0 if v0 is None else v0, r1 if v1 is None else v1
    return sorted({argument(fmt, ("m", v, j)) for v in range(v0, v1 + 1)
                   for j in range(-J, J + 1) if _in_binade(fmt, v, j)})


def _in_binade(fmt, v, j):
    m, _e = minimiser(fmt, v)
    return (1 << (fmt.prec - 1)) <= m + j <= (1 << fmt.prec) - 1


def argument(fmt, centre):
    """The encoding of a centre: c 2^-e for (c, e), positive; m0 + j for
    ("m", v, j)."""
    if centre[0] == "m":
        import pi_worstcase
        _m, v, j = centre
        m, e = minimiser(fmt, v)
        return pi_worstcase._enc(fmt, 0, m + j, e)
    c, e = centre
    return ml._enc(fmt, Fraction(c, 2 ** e))


def _exponents(fmt, b, G=None):
    """The exponents e at which a centre c 2^-e with c of b bits is a
    candidate: from two under the study's first, shifted by the bit length,
    up to the tiny gate."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    return range(max(1, (p + G) // 4 - 6 + b - 1),
                 _gate_exponent(fmt) + b)


@functools.lru_cache(maxsize=None)
def _tiny_centres(fmt, fn, cls, G=None):
    """[(c, e)] the odd c below 2^CBITS and exponents whose x = c 2^-e the
    theory demands marked under the class, sorted by c then e."""
    rnd = sf.RND_RNE if cls == "nearest" else sf.RND_RTZ
    out = []
    for c in range(1, 1 << CBITS, 2):
        for e in _exponents(fmt, c.bit_length(), G):
            x = ml._enc(fmt, Fraction(c, 2 ** e))
            if classify(fmt, rnd, x, G, fn) == "mark":
                out.append((c, e))
    return out


@functools.lru_cache(maxsize=None)
def _minnbr_centres(fmt, fn, cls):
    """[("m", v, j)]: the minimisers' neighbours the theory demands marked."""
    rnd = sf.RND_RNE if cls == "nearest" else sf.RND_RTZ
    v0, v1 = MINNBR_RANGE[fmt.name]
    out = []
    for v in range(v0, v1 + 1):
        for j in range(-MINNBR_J, MINNBR_J + 1):
            if not _in_binade(fmt, v, j):
                continue
            x = argument(fmt, ("m", v, j))
            if classify(fmt, rnd, x, None, fn) == "mark":
                out.append(("m", v, j))
    return out


def entries(fmt, rnd, fn, G=None):
    """The compact entries of (fn, fmt, rnd) the theory generates: runs
    (c, e0, e1) of the tiny family, then ("m", (v, ...), (j, ...)). The
    minimisers' neighbours are the decided G's (the formats the study ran them
    at); G is the tiny family's."""
    cls = cls_of(rnd)
    out, run = [], None
    for c, e in _tiny_centres(fmt, fn, cls, G):
        if run and run[0] == c and run[2] == e - 1:
            run[2] = e
        else:
            run = [c, e, e]
            out.append(run)
    out = [tuple(r) for r in out]
    by_v = {}
    for _m, v, j in (_minnbr_centres(fmt, fn, cls) if fmt.name in MINNBR_RANGE
                     else ()):
        by_v.setdefault(v, []).append(j)
    by_js = {}                      # the binades with the same neighbours
    for v, js in sorted(by_v.items()):
        by_js.setdefault(tuple(js), []).append(v)
    return out + [("m", tuple(vs), js) for js, vs in by_js.items()]


def expand(es):
    """The centres of compact entries: (c, e) and ("m", v, j), in order."""
    out = []
    for en in es:
        if en[0] == "m":
            out += [("m", v, j) for v in en[1] for j in en[2]]
        else:
            c, e0, e1 = en
            out += [(c, e) for e in range(e0, e1 + 1)]
    return out


def centres(fmt, rnd, fn, G=None):
    """The generated centres of (fn, fmt, rnd), expanded."""
    return expand(entries(fmt, rnd, fn, G))


def deep_arguments(fmt, fn, G=None):
    """[(bits, label)]: x = c 2^-e for the odd c of each bit length from
    CBITS + 1 up to two past where the theory's window closes (the smallest,
    the middle and the largest odd c; the odd multiples of 3 for sin and tan,
    the only centres they have), at the exponents of the window the theory finds
    for that c and one either side, positive. The family beyond the committed
    sample, each lane classified by the theory and not listed."""
    p = fmt.prec
    G = ml.GUARD[fmt.name] if G is None else G
    top = (p - G + 7) // 6 + 2 if fn != "cos" else (p - G + 3) // 4 + 2
    mod, rem = (6, 3) if fn != "cos" else (2, 1)       # odd multiples of 3 / odd
    out = []
    for b in range(CBITS + 1, top + 1):
        lo, hi = 1 << (b - 1), (1 << b) - 1
        first = lo + (rem - lo) % mod
        last = hi - (hi - rem) % mod
        mid = first + ((last - first) // 2) // mod * mod
        for c in sorted({first, mid, last}):
            es = [e for e in _exponents(fmt, b)
                  if any(classify(fmt, r, ml._enc(fmt, Fraction(c, 2 ** e)),
                                  G, fn) == "mark"
                         for r in (sf.RND_RNE, sf.RND_RTZ))]
            if not es:
                continue
            for e in sorted({min(es) - 1, min(es), (min(es) + max(es)) // 2,
                             max(es), max(es) + 1}):
                if e >= 1:
                    out.append((ml._enc(fmt, Fraction(c, 2 ** e)),
                                f"{c} 2^-{e}"))
    return out


def neighbours(fmt, fn, centre, G=None):
    """[(bits, label)]: the tiny centre's neighbours in the encoding, either
    side, at OFFSETS: the first N_INSIDE inside its window, the rest outside.
    A minimiser's neighbour is isolated: none."""
    if centre[0] == "m":
        return []
    x0 = argument(fmt, centre)
    W = half_width(fmt, fn, x0, G)
    out = []
    for lab, mult in OFFSETS:
        j = 1 if mult is None else max(1, math.ceil(W * mult))
        for sgn in (1, -1):
            mag = x0 + sgn * j
            if 0 < mag < fmt.exp_mask << fmt.man_w:
                out.append((mag, f"{'+' if sgn > 0 else '-'}{lab}"))
    return out


def window_edges(fmt, rnd, fn, x0, G=None):
    """{side: (j_in, j_out)} for the centre x0, side +1 (the encoding stepped up)
    and -1: along x0 + side j, the largest j whose lane the theory demands
    marked (d under 0.7) and the smallest it calls clear (d over 1.3) or gated;
    the two are exact, by an exponential search and a bisection (the marked set
    is an interval holding x0, so each predicate is monotone in j on a side).
    j_out is None where the search reaches a binade's worth of steps without
    one. The window's edges, whatever its width: 2^189 arguments at fp256."""
    jmax = 1 << fmt.man_w
    out = {}
    for side in (1, -1):
        def cls(j, side=side):
            c = classify(fmt, rnd, x0 + side * j, G, fn)
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


def generate(formats=None):
    """TRIG_FAMILY, all of it, from the theory: {fn: {fmt: {attribute:
    [entry]}}} (the committed list below is held to this)."""
    out = {}
    for fn in FUNCTIONS:
        out[fn] = {}
        for fmt in formats or ml.TRIG_FORMATS:
            out[fn][fmt.name] = {RND_NAMES[r]: entries(fmt, r, fn)
                                 for r in sf.RND_MODES}
    return out


# The line that starts the generated tail of this file. Built from two pieces
# so that this line does not itself contain it.
_MARKER = ("# ---- GENERATED by "
           + "python/tests/mathlib_runs.py trig-family --write")
NL = chr(10)


def _token(en):
    if en[0] == "m":
        return f"('m', {tuple(en[1])!r}, {tuple(en[2])!r}),"
    return f"({en[0]}, {en[1]}, {en[2]}),"


def render(data):
    """The generated tail of this file: TRIG_FAMILY as text, each distinct
    list of entries written once and named by every function, format and
    attribute that has it."""
    out = [_MARKER + ": centres",
           "#",
           "# {fn: {format: {attribute: [entry]}}}: an entry is (c, e0, e1),",
           "# the centres c 2^-e for e = e0 .. e1 (c odd, below 2^CBITS), or",
           "# ('m', (v, ...), (j, ...)), the minimisers of the binades of value",
           "# exponents v and their neighbours at those j. Each centre's f",
           "# lies within 0.7 of the nominal bound of a rounding boundary under",
           "# that attribute. The directed three share their boundaries, and",
           "# so do rne and rmm.",
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
                    if len(tok) > 70:               # a long entry: wrapped
                        if line.strip():
                            lines.append(line.rstrip())
                        wrapped = textwrap.wrap(tok, 70, break_long_words=False)
                        lines += [("    " if i == 0 else "        ") + w
                                  for i, w in enumerate(wrapped)]
                        line = "    "
                        continue
                    if len(line) + len(tok) + 1 > 78:
                        lines.append(line.rstrip())
                        line = "    "
                    line += tok + " "
                if line.strip():
                    lines.append(line.rstrip())
                out.append(f"{names[key]} = [" + NL + NL.join(lines) + NL
                           + "]")
    out += ["", "TRIG_FAMILY = {"]
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


def write(path=None):
    """Regenerate TRIG_FAMILY into this file (everything from the marker)."""
    path = Path(path or __file__)
    text = path.read_text(encoding="utf-8")
    head = text[:text.index(_MARKER)]
    path.write_text(head + render(generate()), encoding="utf-8", newline=NL)


# ---- GENERATED by python/tests/mathlib_runs.py trig-family --write: centres
#
# {fn: {format: {attribute: [entry]}}}: an entry is (c, e0, e1),
# the centres c 2^-e for e = e0 .. e1 (c odd, below 2^CBITS), or
# ('m', (v, ...), (j, ...)), the minimisers of the binades of value
# exponents v and their neighbours at those j. Each centre's f
# lies within 0.7 of the nominal bound of a rounding boundary under
# that attribute. The directed three share their boundaries, and
# so do rne and rmm.

_SIN_FP64_1 = []
_SIN_FP64_2 = [
    (3, 25, 25),
]
_SIN_FP128_3 = [
    (21, 54, 54), (27, 54, 54),
]
_SIN_FP128_4 = [
    (3, 40, 55), (9, 42, 54), (15, 43, 54), (21, 43, 53), (27, 43, 53),
    (33, 44, 53), (39, 44, 53), (45, 44, 53), (51, 44, 53), (57, 44, 53),
    (63, 45, 53),
    ('m', (56, 57, 59, 60, 61, 64), (-4, -3, -2, -1, 1, 2, 3, 4)),
]
_SIN_FP256_5 = [
    (21, 116, 116), (27, 116, 116),
]
_SIN_FP256_6 = [
    (3, 71, 117), (9, 73, 116), (15, 74, 116), (21, 74, 115), (27, 74, 115),
    (33, 75, 115), (39, 75, 115), (45, 75, 115), (51, 75, 115),
    (57, 75, 115), (63, 76, 115), ('m', (116,), (-4, 4)),
    ('m', (118, 120, 122, 123, 129, 130, 133, 138, 145, 146, 151, 153,
        154, 157, 158, 161, 163), (-4, -3, -2, -1, 1, 2, 3, 4)),
    ('m', (165,), (-2, -1, 1, 2)), ('m', (166,), (-1, 1)),
    ('m', (179, 182, 184, 185, 187, 188), (-3, 3)),
]
_COS_FP64_7 = []
_COS_FP64_8 = [
    (1, 24, 26), (3, 25, 26), (5, 26, 26),
]
_COS_FP128_9 = []
_COS_FP128_10 = [
    (1, 39, 56), (3, 41, 56), (5, 42, 56), (7, 42, 56), (9, 42, 56),
    (11, 43, 56), (13, 43, 56), (15, 43, 56), (17, 43, 56), (19, 43, 56),
    (21, 44, 56), (23, 44, 56), (25, 44, 56), (27, 44, 56), (29, 44, 56),
    (31, 44, 56), (33, 44, 56), (35, 44, 56), (37, 44, 56), (39, 45, 56),
    (41, 45, 56), (43, 45, 56), (45, 45, 56), (47, 45, 56), (49, 45, 56),
    (51, 45, 56), (53, 45, 56), (55, 45, 56), (57, 45, 56), (59, 45, 56),
    (61, 45, 56), (63, 45, 56), ('m', (54,), (-4, 4)),
    ('m', (55,), (-4, -2, 2, 4)),
    ('m', (58, 62), (-4, -3, -2, -1, 1, 2, 3, 4)),
    ('m', (63,), (-3, -2, -1, 1, 2, 3)), ('m', (65,), (-2, -1, 1, 2)),
]
_COS_FP256_11 = []
_COS_FP256_12 = [
    (1, 70, 118), (3, 72, 118), (5, 73, 118), (7, 73, 118), (9, 73, 118),
    (11, 74, 118), (13, 74, 118), (15, 74, 118), (17, 74, 118),
    (19, 74, 118), (21, 75, 118), (23, 75, 118), (25, 75, 118),
    (27, 75, 118), (29, 75, 118), (31, 75, 118), (33, 75, 118),
    (35, 75, 118), (37, 75, 118), (39, 76, 118), (41, 76, 118),
    (43, 76, 118), (45, 76, 118), (47, 76, 118), (49, 76, 118),
    (51, 76, 118), (53, 76, 118), (55, 76, 118), (57, 76, 118),
    (59, 76, 118), (61, 76, 118), (63, 76, 118),
    ('m', (117,), (-4, -2, 2, 4)),
    ('m', (119, 121, 124, 125, 126, 127, 128, 131, 132, 134, 135, 136,
        137, 139, 140, 141, 142, 143, 144, 147, 148, 149, 150, 152, 155, 156,
        159, 160, 162, 164), (-4, -3, -2, -1, 1, 2, 3, 4)),
    ('m', (178, 180, 181, 183, 186), (-3, 3)),
]
_TAN_FP64_13 = [
    (3, 26, 26),
]
_TAN_FP64_14 = []
_TAN_FP128_15 = [
    (3, 56, 56), (9, 55, 55), (15, 55, 55), (33, 54, 54), (39, 54, 54),
    (45, 54, 54), (51, 54, 54), (57, 54, 54), (63, 54, 54),
]
_TAN_FP128_16 = [
    (3, 41, 55), (9, 43, 54), (15, 44, 54), (21, 44, 54), (27, 44, 54),
    (33, 45, 53), (39, 45, 53), (45, 45, 53), (51, 45, 53), (57, 45, 53),
    (63, 46, 53),
]
_TAN_FP256_17 = [
    (3, 118, 118), (9, 117, 117), (15, 117, 117), (33, 116, 116),
    (39, 116, 116), (45, 116, 116), (51, 116, 116), (57, 116, 116),
    (63, 116, 116),
]
_TAN_FP256_18 = [
    (3, 72, 117), (9, 74, 116), (15, 75, 116), (21, 75, 116), (27, 75, 116),
    (33, 76, 115), (39, 76, 115), (45, 76, 115), (51, 76, 115),
    (57, 76, 115), (63, 77, 115),
]

TRIG_FAMILY = {
    "sin": {
        "fp64": {
            "rne": _SIN_FP64_1,
            "rtz": _SIN_FP64_2,
            "rdn": _SIN_FP64_2,
            "rup": _SIN_FP64_2,
            "rmm": _SIN_FP64_1,
        },
        "fp128": {
            "rne": _SIN_FP128_3,
            "rtz": _SIN_FP128_4,
            "rdn": _SIN_FP128_4,
            "rup": _SIN_FP128_4,
            "rmm": _SIN_FP128_3,
        },
        "fp256": {
            "rne": _SIN_FP256_5,
            "rtz": _SIN_FP256_6,
            "rdn": _SIN_FP256_6,
            "rup": _SIN_FP256_6,
            "rmm": _SIN_FP256_5,
        },
    },
    "cos": {
        "fp64": {
            "rne": _COS_FP64_7,
            "rtz": _COS_FP64_8,
            "rdn": _COS_FP64_8,
            "rup": _COS_FP64_8,
            "rmm": _COS_FP64_7,
        },
        "fp128": {
            "rne": _COS_FP128_9,
            "rtz": _COS_FP128_10,
            "rdn": _COS_FP128_10,
            "rup": _COS_FP128_10,
            "rmm": _COS_FP128_9,
        },
        "fp256": {
            "rne": _COS_FP256_11,
            "rtz": _COS_FP256_12,
            "rdn": _COS_FP256_12,
            "rup": _COS_FP256_12,
            "rmm": _COS_FP256_11,
        },
    },
    "tan": {
        "fp64": {
            "rne": _TAN_FP64_13,
            "rtz": _TAN_FP64_14,
            "rdn": _TAN_FP64_14,
            "rup": _TAN_FP64_14,
            "rmm": _TAN_FP64_13,
        },
        "fp128": {
            "rne": _TAN_FP128_15,
            "rtz": _TAN_FP128_16,
            "rdn": _TAN_FP128_16,
            "rup": _TAN_FP128_16,
            "rmm": _TAN_FP128_15,
        },
        "fp256": {
            "rne": _TAN_FP256_17,
            "rtz": _TAN_FP256_18,
            "rdn": _TAN_FP256_18,
            "rup": _TAN_FP256_18,
            "rmm": _TAN_FP256_17,
        },
    },
}
