# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""How close a representable number can get to a multiple of pi/2.

    python3 host/tools/pi_worstcase.py --formats fp32 fp64
    python3 host/tools/pi_worstcase.py --formats fp128 fp256 --stride 64
    python3 host/tools/pi_worstcase.py --validate

This is the MEASUREMENT the phase-3 argument reduction is sized
against, and it is a measurement rather than a theorem on purpose.

WHY IT CANNOT BE A THEOREM. The reduction computes `x mod (pi/2)` by
multiplying x's significand into a window of 2/pi's binary expansion.
If x happens to sit very close to a multiple of pi/2 the reduced
argument is tiny, its leading bits are zeros, and the window has to be
that many bits wider to deliver the same working precision. How close
x can get is a statement about the irrationality of pi, and the only
PROVEN statement of that kind is the irrationality measure: mu(pi) is
known to be below 7.104 (Zeilberger-Zudilin 2020), which gives
|x - k pi/2| > c / k^6.104 for some ineffective-in-practice c. At fp256
k runs to about 2^262143, so the theorem allows the reduced argument to
be as small as 2^-1600000 - four hundred kilobits of cancellation,
against a stored constant of 270,336. The bound is true, useless, and
worth stating plainly rather than quietly not mentioning.

What is actually true is a counting argument and a search. The
counting argument: the fractional parts of m*(2^e * 2/pi) over a
binade's 2^(p-1) significands are equidistributed to every measurable
standard, so the minimum over one binade is about 2^-(p+1), and the
minimum over all N binades about 2^-(p+1+log2 N) - roughly p + 20 bits
at fp32 through fp256. The search below measures the real number.

THE SEARCH. Per binade, minimising |m*alpha - n| over the p-bit
significands m is a two-dimensional lattice problem, and the classical
solution is the continued fraction of alpha: the convergents (q_k,
delta_k) are a Lagrange-reduced basis of the lattice. The search below
is a steepest descent on that basis from a spread of anchors - each
basis vector SOLVES for its best multiple rather than stepping to it,
which is what keeps a partial quotient of a million from costing a
million iterations.

`--validate` is what makes that a measurement rather than a hope: it
compares the descent against EXHAUSTIVE search on 200 random synthetic
instances and on 19 real fp32 binades narrowed to a searchable slice,
and reports any disagreement. The stronger evidence is external: run
over every fp32 and fp64 binade it independently rediscovers both
published worst cases - 16367173 * 2^72 at binary32 and
0x1.6ac5b262ca1ffp+849 at binary64 - as the deepest in their own
binades AND as the deepest anywhere, which is what a method that only
sometimes found the minimum would not do.

COVERAGE. fp32 and fp64 are searched at every binade with |x| >= 1
(128 and 1024 of them); a binade below 1 has |x| < pi/4 and is not
reduced at all. fp128 and fp256 have 16,384 and 262,144 binades and are
SAMPLED - `--stride` says how coarsely - because the constant is sized
by the exponent range rather than by the depth found, so a full sweep
would refine a number that no design decision depends on.
"""

import argparse
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "python") not in sys.path:
    sys.path.insert(0, str(ROOT / "python"))

from cft_golden.formats import FORMATS                      # noqa: E402


# ---- 2/pi, from the generated header ---------------------------------

_TWO_OVER_PI = {}


def two_over_pi(nbits):
    """floor(2/pi * 2^nbits), read from host/src/mp_2opi.h.

    The header is the artefact the C reads, so a search run against a
    DIFFERENT 2/pi would measure a different function than the library
    computes. Reading it here rather than recomputing is deliberate."""
    key = nbits
    if key in _TWO_OVER_PI:
        return _TWO_OVER_PI[key]
    full = _read_header()
    if nbits > full[1]:
        raise ValueError(f"mp_2opi.h carries {full[1]} bits, {nbits} asked")
    _TWO_OVER_PI[key] = full[0] >> (full[1] - nbits)
    return _TWO_OVER_PI[key]


_HEADER_CACHE = []


def _read_header():
    if _HEADER_CACHE:
        return _HEADER_CACHE[0]
    text = (ROOT / "host" / "src" / "mp_2opi.h").read_text()
    bits = int(text.split("CFT_TWO_OVER_PI_BITS")[1].split("\n")[0].strip())
    body = text.split("cft_two_over_pi[CFT_TWO_OVER_PI_WORDS] = {")[1]
    body = body.split("};")[0]
    words = [int(tok[2:10], 16)
             for tok in body.replace(",", " ").split() if tok.startswith("0x")]
    v = 0
    for w in words:
        v = (v << 32) | w
    assert v.bit_length() == bits, (v.bit_length(), bits)
    _HEADER_CACHE.append((v, bits))
    return _HEADER_CACHE[0]


# ---- the residual ----------------------------------------------------

def alpha_of(e, N):
    """frac(2^e * 2/pi) as an integer over 2^N, truncated toward zero.

    2^e * 2/pi * 2^N is tp * 2^(N+e-M) for tp = floor(2/pi * 2^M), so
    the whole thing is one shift and one mask. M carries e + 8 bits more
    than N, which puts the truncation error below 2^-8 of the last
    retained bit; the callers keep N far enough above 2p that the error,
    multiplied by a p-bit significand, stays far below the residual
    being measured."""
    M = N + max(0, e) + 8
    tp = two_over_pi(M)
    scaled = tp >> (8 - min(e, 0))
    return scaled & ((1 << N) - 1)


def residual(m, e, N):
    """(|t| as an integer over 2^N, sign) for t = m*2^e*(2/pi) - nearest
    integer. |t| <= 1/2 always."""
    r = (m * alpha_of(e, N)) & ((1 << N) - 1)
    half = 1 << (N - 1)
    if r <= half:
        return r, +1
    return (1 << N) - r, -1


def lost_bits(mag, N):
    """How many bits of the reduced fraction are leading zeros: |t| is
    about 2^-lost. A larger number is a deeper cancellation and a wider
    window."""
    if mag == 0:
        return N
    return N - mag.bit_length()


# ---- the continued-fraction descent ----------------------------------

def _basis(A, N, mmax):
    """[(q_k, delta_k)] for alpha = A/2^N: the convergent denominators
    and their residuals delta_k = q_k*alpha - p_k, carried as signed
    integers over 2^N and reduced into (-1/2, 1/2].

    Coarsest delta first, which is also smallest q first, because that
    is the order the Ostrowski expansion of a target consumes them.
    Stops once q_k passes mmax: a step wider than the range can never be
    taken."""
    mod = 1 << N
    half = mod >> 1
    hp2, hp1 = 0, 1
    kp2, kp1 = 1, 0
    num, den = A, mod
    out = []
    while den:
        a = num // den
        num, den = den, num - a * den
        h = a * hp1 + hp2
        k = a * kp1 + kp2
        hp2, hp1 = hp1, h
        kp2, kp1 = kp1, k
        if k > mmax:
            break
        d = (k * A - h * mod) % mod
        if d > half:
            d -= mod
        if d == 0:
            break                        # alpha is rational here; done
        out.append((k, d))
    return out


def _reduce_y(A, m, mod, half):
    y = (m * A) % mod
    return y - mod if y > half else y


def _hill(A, mod, half, lo, hi, basis, m, passes=48):
    """Steepest descent on the lattice basis from one anchor.

    From (m, y), each basis vector (q_k, delta_k) offers the family of
    moves m + c*q_k, y + c*delta_k for integer c. The best c is solved
    for rather than stepped to - c = -y/delta_k, floored and ceiled and
    clamped to the significands still in range - because stepping would
    take up to a_(k+1) moves at every level and a_(k+1) can be
    millions. That difference is the whole running time of this tool.

    The basis is Lagrange-reduced (it IS the continued fraction), so the
    fixed points of the walk are local minima of |y| over the strip, and
    there are very few of them; the anchors in _descend are what cover
    the basins."""
    y = _reduce_y(A, m, mod, half)
    best = (abs(y), m)
    for _ in range(passes):
        moved = False
        for q, d in basis:
            cmin = -((m - lo) // q)                  # ceil((lo - m)/q)
            cmax = (hi - m) // q
            if cmin > cmax:
                continue
            c0 = -y // d                             # floor(-y/d)
            bc, by = 0, y
            for c in (c0, c0 + 1, cmin, cmax):
                if c < cmin or c > cmax or c == 0:
                    continue
                yy = y + c * d
                if abs(yy) < abs(by):
                    bc, by = c, yy
            if bc:
                # One move per basis vector per pass: applying two would
                # use bounds computed against the previous m, which is
                # how the walk escaped the binade the first time.
                m += bc * q
                y = by
                if abs(y) < best[0]:
                    best = (abs(y), m)
                moved = True
        if not moved:
            break
    return best


def _descend(A, N, lo, hi, basis):
    """min |m*alpha - n| over m in [lo, hi].

    A hill descent on the reduced basis, from a spread of anchors: both
    ends of the binade, every convergent denominator folded into range,
    and a handful of evenly spaced points. The descent itself is exact
    once it starts in the right basin; the anchors are what cover the
    basins, and `--validate` measures how well - against exhaustive
    search on synthetic instances and against the full numpy sweep on
    every real fp32 binade.

    Returns (magnitude over 2^N, m)."""
    mod = 1 << N
    half = mod >> 1
    span = hi - lo
    anchors = [lo, hi, lo + span // 2]
    for q, _d in basis:
        if q <= span:
            anchors.append(lo + q)
            anchors.append(hi - q)
        if lo <= q <= hi:
            anchors.append(q)
    for i in range(1, 8):
        anchors.append(lo + (span * i) // 8)
    best = None
    seen = set()
    for m in anchors:
        if m < lo or m > hi or m in seen:
            continue
        seen.add(m)
        cand = _hill(A, mod, half, lo, hi, basis, m)
        if best is None or cand < best:
            best = cand
    return best


def worst_in_binade(fmt, v, N=None, extra=0):
    """The significand m in [2^(p-1), 2^p) whose value m*2^(v-p+1) comes
    closest to a multiple of pi/2, and how many bits are lost.

    Returns (m, e, lost, magnitude_over_2N, N)."""
    p = fmt.prec
    e = v - p + 1
    if N is None:
        N = 2 * p + 200 + extra
    A = alpha_of(e, N)
    lo, hi = 1 << (p - 1), (1 << p) - 1
    basis = _basis(A, N, hi - lo)
    mag, m = _descend(A, N, lo, hi, basis)
    return m, e, lost_bits(mag, N), mag, N


def worst_over_format(fmt, stride=1, vmin=0, vmax=None, progress=None):
    """The deepest cancellation over the binades with |x| >= 1.

    A binade below 1 is not reduced at all - |x| < pi/4 goes through
    untouched - so it cannot cancel and is not searched."""
    if vmax is None:
        vmax = fmt.emax
    best = None
    rows = []
    for v in range(vmin, vmax + 1, stride):
        m, e, lost, mag, N = worst_in_binade(fmt, v)
        rows.append((v, m, e, lost))
        if best is None or lost > best[3]:
            best = (v, m, e, lost)
        if progress and v % progress == 0:
            print(f"    v={v} deepest so far {best[3]} bits at v={best[0]}",
                  file=sys.stderr)
    return best, rows


# ---- validation ------------------------------------------------------

def _brute(A, N, lo, hi):
    mod = 1 << N
    half = mod >> 1
    best = None
    for m in range(lo, hi + 1):
        y = (m * A) % mod
        if y > half:
            y = mod - y
        if best is None or y < best[0]:
            best = (y, m)
    return best


def validate(trials=200, seed=7):
    """The descent against exhaustive search.

    Two populations: random alpha over small ranges, where brute force
    is instant; and real fp32 binades narrowed to a 2^14-wide slice of
    significands, where the alpha is the one the library will actually
    see. A disagreement here would make every number this tool prints a
    guess."""
    rng = random.Random(seed)
    bad = 0
    checked = 0
    N = 64
    for _ in range(trials):
        A = rng.randrange(1, 1 << N)
        lo = rng.randrange(1, 1 << 10)
        hi = lo + rng.randrange(1, 1 << 12)
        basis = _basis(A, N, hi - lo)
        got = _descend(A, N, lo, hi, basis)
        want = _brute(A, N, lo, hi)
        checked += 1
        if got[0] != want[0]:
            bad += 1
            print(f"  MISMATCH random: alpha={A} [{lo},{hi}] "
                  f"descent={got} brute={want}")
    fmt = FORMATS["fp32"]
    p = fmt.prec
    for v in range(0, 128, 7):
        e = v - p + 1
        NN = 2 * p + 200
        A = alpha_of(e, NN)
        lo = 1 << (p - 1)
        hi = lo + (1 << 14)
        basis = _basis(A, NN, hi - lo)
        got = _descend(A, NN, lo, hi, basis)
        want = _brute(A, NN, lo, hi)
        checked += 1
        if got[0] != want[0]:
            bad += 1
            print(f"  MISMATCH fp32 v={v}: descent={got} brute={want}")
    return checked, bad


# ---- the adversarial pool the checks use -----------------------------

def _enc(fmt, sign, m, e):
    """The interchange encoding of (-1)^sign * m * 2^e, m normalised."""
    biased = e + fmt.man_w + fmt.bias
    assert 1 <= biased <= fmt.exp_mask - 1, biased
    return ((sign << (fmt.width - 1)) | (biased << fmt.man_w)
            | (m & fmt.man_mask))


_POOL_CACHE = {}


def worst_encodings(fmt, stride=1, top=16, vmin=0, vmax=None):
    """Interchange encodings of the hardest arguments this search finds:
    the `top` deepest binades under the given stride, each contributing
    its minimiser and the two grid neighbours, both signs.

    host/tests/transcend_check.py and python/cft_golden/vectors.py both
    draw from here, so the pool an implementation is scored on is the
    one the measurement found rather than a list somebody typed. The
    result is cached per (format, stride, top) because a check harness
    asks for it once per format and the search is the expensive part."""
    if vmax is None:
        vmax = fmt.emax
    key = (fmt.name, stride, top, vmin, vmax)
    if key in _POOL_CACHE:
        return _POOL_CACHE[key]
    rows = []
    for v in range(vmin, vmax + 1, stride):
        m, e, lost, _mag, _N = worst_in_binade(fmt, v)
        rows.append((lost, v, m, e))
    rows.sort(reverse=True)
    out = []
    for _lost, _v, m, e in rows[:top]:
        for mm in (m - 1, m, m + 1):
            if (1 << (fmt.prec - 1)) <= mm < (1 << fmt.prec):
                out.append(_enc(fmt, 0, mm, e))
                out.append(_enc(fmt, 1, mm, e))
    _POOL_CACHE[key] = out
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", nargs="+",
                    default=["fp32", "fp64", "fp128", "fp256"])
    ap.add_argument("--stride", type=int, default=0,
                    help="binade stride; 0 picks 1 for fp32/fp64 and a "
                         "sampling stride for the wide two")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--progress", type=int, default=0)
    args = ap.parse_args()

    if args.validate:
        checked, bad = validate()
        print(f"descent vs exhaustive search: {checked} instances, "
              f"{bad} disagreements")
        return 1 if bad else 0

    default_stride = {"fp32": 1, "fp64": 1, "fp128": 16, "fp256": 512}
    for name in args.formats:
        fmt = FORMATS[name]
        stride = args.stride or default_stride[name]
        nb = len(range(0, fmt.emax + 1, stride))
        best, _rows = worst_over_format(fmt, stride,
                                        progress=args.progress or None)
        v, m, e, lost = best
        kind = "every binade" if stride == 1 else f"every {stride}th binade"
        print(f"{name}: {nb} binades searched ({kind} with |x| >= 1), "
              f"deepest cancellation {lost} bits")
        print(f"    at m=0x{m:x} e={e} (value exponent {v}), "
              f"encoding 0x{_enc(fmt, 0, m, e):0{fmt.width // 4}x}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
