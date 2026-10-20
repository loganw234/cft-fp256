# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Class-level (L2) enumerators for the clause-5 soak's 64-bit rounding operations.

The reference for host/tools/clause5_soak.c's `-class` modes: conv64to32-class, rint64-class, cvtto64-class,
cvtfrom64-class and scaleb64-class. Each maps an INDEX to the operand (and, for scaleB, the exponent) the soak
runs, over the structure docs/studies/SWP-A-coverage.md section 4.3 calls the second level:

    the rounding unit depends on the dropped bits only through guard and a sticky tree, on the kept bits only
    through the lsb and the carry, and on the exponent only through a rebias and range checks; so a
    representative of every class plus a walking-ones set over the dropped and kept bits covers it.

THE CLAIM IS AT THE CLASS LEVEL (L2) AND IT IS PLAUSIBLE, NOT PROVED: it rests on that structural assumption
about the tile (and about libcft's host code), which nothing here tests. What this file shows is that the
ENUMERATION reaches every class (python/tests/test_c5_class_enum.py), not that the unit has the structure.

THE INDEX SPACE. One index is one operand (one operand-exponent pair for scaleB). Slowest to fastest:

    position  x  sign (2)  x  class (4)  x  pattern (4 + W)

 * position   an exponent (a rounding position), or a witness. Each operation's structural exponents are the
              ones at which the rounding position or the range class changes, plus one saturated exponent on
              each side; after them come the WITNESSES: the walking ones and zeros of the biased exponent field
              (the biased exponents 2^j and (2^E - 1) xor 2^j, j < E: 2E values) and the subnormal field (biased
              exponent 0). Witnesses that fall inside the structural range repeat a cell: harmless, counted.
 * sign       0 then 1.
 * class      0 the dropped bits are zero, 1 below half (only the lowest dropped bit set), 2 exactly half (only
              the guard bit), 3 above half (guard and the lowest bit). Where a class does not exist at a position
              (one dropped bit has no below-half; no kept bits leave the implicit bit in the dropped part) the
              construction yields the nearest class that does: a repeated operand, counted by `distinct`.
 * pattern    t < 4: the kept bits (lsb 0 or 1) x (the bits above the lsb all zeros or all ones), the four
              patterns of "the lsb and the carry"; t >= 4: the kept bits zero, plus ONE walking one at fraction
              bit t - 4, OR-ed onto the class's representative. So each class has a walking-ones set over the kept
              and the dropped bits (the study's "4 + 52 walking bits"), and the walking one on the class-0
              and class-2 representatives is the single sticky bit at every position under and over the guard.

HOW THE SOAK RUNS AN INDEX (host/tools/clause5_soak.c, "How a class case is run"). Alone: the library's batch call
returns one flags word and the kernels compare the OR over the call, so a flag a defect drops on one operand among others
that raise it is unseen in a batch; a call of one operand makes every flag the operand's own. And, for the two modes that
reach a tile (rint64-class, scaleb64-class), in each of the tile's LANES = 4 fp64 lanes: an element goes to the lane its
place in a pass gives it, so each operand is run behind 0 to 3 benign operands (1.0 for rint, +0 for scaleB), which are not
cases. That is why k is 4 for those two modes (a case a lane), as it is 4 for cvtto64-class (a case a target).

Per-attribute: the operands do not depend on the attribute, so each attribute's job runs the same N indices;
the study's 377,664 for conv64to32 counts THREE magnitude functions (nearest, truncate, away) and so leaves out
the duplicated (attribute, sign) pairs; running each attribute covers every mode code and sign path separately
(the study's own edge note, 4.3 (d)).

    python python/c5_class_enum.py --sizes        the five spaces, their formulas and distinct operands
    python python/c5_class_enum.py --dump JOB LO HI    the lines the C tool's `dump` prints, for a diff
    python python/c5_class_enum.py --check        the coverage check at e4m3 and e5m6, and its plants
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.formats import FP32, FP64, FpFormat  # noqa: E402

E4M3 = FpFormat("e4m3", 4, 3)
E5M6 = FpFormat("e5m6", 5, 6)

NCLS = 4
LANES = 4                  # fp64 lanes of a tile (docs/ARCHITECTURE.md): the tile modes run each operand in each lane
CLS_NAMES = ("zero", "below-half", "half", "above-half")
INT64_MAX = (1 << 63) - 1
INT64_MIN = -(1 << 63)


def mask(n: int) -> int:
    return (1 << n) - 1 if n > 0 else 0


# ---------------------------------------------------------------------------------------------------
# the significand builder: one class representative, one pattern
# ---------------------------------------------------------------------------------------------------

def sig(P: int, d: int, c: int, t: int) -> int:
    """The P-bit significand (bit P-1 set) whose low d bits are dropped by the rounding, of class c and pattern t.

    The kept bits are the top k = P - d bits (the implicit bit is the top one); the dropped bits are class c's
    representative; pattern t < 4 sets the kept lsb (t & 1) and whether the kept bits above the lsb are all ones
    (t >> 1); t >= 4 keeps only the implicit bit and ORs in the walking one at bit t - 4 of the significand.
    d is clamped to P + 1, where the whole significand lies below half and nothing more can change."""
    d = min(d, P + 1)
    k = P - d
    walk = 0
    if t >= 4:
        walk = 1 << (t - 4)
        K = 1 << (k - 1) if k >= 1 else 0
    elif k <= 0:
        K = 0
    elif k == 1:
        K = 1
    else:
        lsb, ones = t & 1, t >> 1
        K = ((mask(k) - 1) if ones else (1 << (k - 1))) | lsb
    D = 0 if d == 0 else (0, 1, 1 << (d - 1), (1 << (d - 1)) | 1)[c]
    return ((K << d) | D | walk | (1 << (P - 1))) & mask(P)


def exp_witnesses(E: int) -> list:
    """Biased exponent fields: the walking ones, the walking zeros of an all-ones field (never the all-ones
    field itself, which is infinity or NaN), and zero (the subnormals). 2E + 1 values."""
    full = (1 << E) - 1
    return [1 << j for j in range(E)] + [full ^ (1 << j) for j in range(E)] + [0]


def fp_encode(fmt: FpFormat, sign: int, b: int, frac: int) -> int:
    return (sign << (fmt.exp_w + fmt.man_w)) | (b << fmt.man_w) | (frac & fmt.man_mask)


class _Base:
    """Common index arithmetic: position x sign x class x pattern."""
    name = ""
    k = 1                      # checks one index makes: cases + skipped = k x indices
    attrs = ("rne", "rtz", "rdn", "rup")

    def split(self, i: int):
        t = i % self.npat
        i //= self.npat
        c = i % NCLS
        i //= NCLS
        return i // 2, i % 2, c, t

    def size_formula(self) -> str:
        return f"{self.npos} positions x 2 signs x {NCLS} classes x {self.npat} patterns = {self.N}"


class RoundEnum(_Base):
    """conv (a source format to a narrower one), rint and cvtto: a floating-point operand whose rounding position
    is a function of its exponent."""

    def __init__(self, kind: str, src: FpFormat, dst: FpFormat | None = None, B: int | None = None):
        self.kind, self.src, self.dst = kind, src, dst
        self.P, self.W, self.E = src.prec, src.man_w, src.exp_w
        if kind == "conv":
            self.lo_e = dst.emin - dst.prec - 2
            self.hi_e = dst.emax + 1
            self.name = "conv64to32-class" if (src, dst) == (FP64, FP32) else f"conv-{src.name}-{dst.name}-class"
        elif kind == "rint":
            self.lo_e, self.hi_e = -3, self.P
            self.name = "rint64-class" if src == FP64 else f"rint-{src.name}-class"
            self.attrs = ("rne", "rtz", "rdn", "rup", "rmm")
            self.k = LANES                               # a tile mode: each operand is run once in each lane
        elif kind == "cvtto":
            self.lo_e, self.hi_e = -3, B
            self.B = B
            self.name = "cvtto64-class" if (src == FP64 and B == 64) else f"cvtto-{src.name}-{B}-class"
            self.attrs = ("rne", "rtz", "rdn", "rup", "rmm")
            self.k = 4                                   # the four integer targets, each in-range lane
        else:
            raise ValueError(kind)
        assert self.hi_e + src.bias <= (1 << self.E) - 2, "the structural range must stay inside the finite exponents"
        self.nstruct = self.hi_e - self.lo_e + 1
        self.wit = exp_witnesses(self.E)
        self.npos = self.nstruct + len(self.wit)
        self.npat = 4 + self.W
        self.N = self.npos * 2 * NCLS * self.npat

    def d_of(self, e: int) -> int:
        if self.kind == "conv":
            return (self.P - self.dst.prec) + max(0, self.dst.emin - e)
        return max(0, self.P - 1 - e)

    def position(self, pi: int):
        """(biased exponent field, dropped count) of position pi."""
        if pi < self.nstruct:
            e = self.lo_e + pi
            return e + self.src.bias, self.d_of(e)
        b = self.wit[pi - self.nstruct]
        if b == 0:
            return 0, self.P + 1
        return b, self.d_of(b - self.src.bias)

    def operand(self, i: int) -> int:
        pi, sign, c, t = self.split(i)
        b, d = self.position(pi)
        return fp_encode(self.src, sign, b, sig(self.P, d, c, t))

    def dump_line(self, i: int) -> str:
        return "%d 0x%016x" % (i, self.operand(i))

    def operands(self, i: int):
        return (self.operand(i), None)


class CvtfromEnum(_Base):
    """cvtfrom: a 64-bit integer source (i64 positive, i64 negative, u64) whose rounding position is its bit length
    L. Three more indices close the space: -2^63 (the one signed value whose magnitude has 64 bits), and zero as an
    i64 and as a u64 (integer zero converts to +0 by its own path, with no rounding)."""
    attrs = ("rne", "rtz", "rdn", "rup")

    def __init__(self, dst: FpFormat, Wi: int = 64):
        self.dst, self.Wi = dst, Wi
        self.name = "cvtfrom64-class" if (dst == FP64 and Wi == 64) else f"cvtfrom-{dst.name}-i{Wi}-class"
        self.npat = 4 + (Wi - 1)
        self.cells = [(0, L) for L in range(1, Wi)] + [(1, L) for L in range(1, Wi)] + [(2, L) for L in range(1, Wi + 1)]
        self.npos = len(self.cells)
        self.nspecial = 3
        self.N = self.npos * NCLS * self.npat + self.nspecial

    def split(self, i):
        t = i % self.npat
        i //= self.npat
        c = i % NCLS
        return i // NCLS, 0, c, t

    def operands(self, i: int):
        """(the 64-bit pattern of the source, 0 for i64 and 1 for u64)."""
        if i >= self.N - self.nspecial:
            return ((1 << (self.Wi - 1), 0), (0, 0), (0, 1))[i - (self.N - self.nspecial)]
        ci, _s, c, t = self.split(i)
        sv, L = self.cells[ci]
        m = sig(L, max(0, L - self.dst.prec), c, t)
        return ((-m) & mask(self.Wi) if sv == 1 else m), (1 if sv == 2 else 0)

    def dump_line(self, i: int) -> str:
        v, u = self.operands(i)
        return "%d 0x%016x %s" % (i, v, "u64" if u else "i64")

    def size_formula(self) -> str:
        return (f"{self.npos} cells (i64+ L=1..{self.Wi - 1}, i64- L=1..{self.Wi - 1}, u64 L=1..{self.Wi}) x {NCLS} classes x "
                f"{self.npat} patterns + 3 (-2^{self.Wi - 1}, 0 as i64, 0 as u64) = {self.N}")


class ScalebEnum(_Base):
    """scaleb strips: results in the subnormal strips s = 1 .. P + 1 (the result's exponent below emin by s), reached
    three ways (route 0: a normal operand of exponent 0, whose exponents n = emin - s the tile takes while n >= emin - W,
    s = 1 .. 52 at fp64; route 1: a normal operand of the largest exponent, which needs exponents far below emin - W to
    reach the strips and so takes libcft's host path; route 2: a subnormal operand whose leading bit is the field's top
    bit, with a small n), then a block of overflow results and a block of results deeper than the last strip. Results in
    range are exact and are not enumerated."""
    attrs = ("rne", "rtz", "rdn", "rup")

    def __init__(self, fmt: FpFormat):
        self.fmt = fmt
        self.P, self.W, self.E = fmt.prec, fmt.man_w, fmt.exp_w
        self.name = "scaleb64-class" if fmt == FP64 else f"scaleb-{fmt.name}-class"
        self.k = LANES                                   # a tile mode: each operand is run once in each lane
        self.nstrip = self.P + 1
        self.npat = 4 + self.W
        self.npos = 3 * self.nstrip                      # (route, strip) cells
        self.nstripidx = self.npos * 2 * NCLS * self.npat
        self.OPS = self._block_operands()
        self.nlist = 6
        self.nblock = 2 * len(self.OPS) * self.nlist     # signs x operands x exponents
        self.N = self.nstripidx + 2 * self.nblock

    def _block_operands(self):
        """(biased exponent field, fraction, the operand's leading exponent) of 1.0, the largest finite and the
        smallest subnormal."""
        f = self.fmt
        return [(f.bias, 0, 0), ((1 << self.E) - 2, f.man_mask, f.emax), (0, 1, f.emin - f.man_w)]

    def operands(self, i: int):
        f = self.fmt
        if i < self.nstripidx:
            pi, sign, c, t = self.split(i)
            route, s = divmod(pi, self.nstrip)
            s += 1
            if route == 0:
                a = fp_encode(f, sign, f.bias, sig(self.P, s, c, t))
                n = f.emin - s
            elif route == 1:
                a = fp_encode(f, sign, (1 << self.E) - 2, sig(self.P, s, c, t))
                n = f.emin - s - f.emax
            else:
                a = fp_encode(f, sign, 0, sig(self.W, s - 1, c, t))
                n = 1 - s
            return a, n
        j = i - self.nstripidx
        deep = j >= self.nblock
        j %= self.nblock
        sign, j = divmod(j, len(self.OPS) * self.nlist)
        oi, li = divmod(j, self.nlist)
        b, frac, ex = self.OPS[oi]
        a = fp_encode(f, sign, b, frac)
        if not deep:
            nf = f.emax + 1 - ex
            n = (nf, nf + 1, 3 * f.emax, 3 * f.emax + 1, 100000, INT64_MAX)[li]
        else:
            nl = f.emin - self.P - 2 - ex
            n = (nl, nl - 1, -(4 * f.emax + 2 * self.P), -(4 * f.emax + 2 * self.P) - 1, -100000, INT64_MIN)[li]
        return a, n

    def dump_line(self, i: int) -> str:
        a, n = self.operands(i)
        return "%d 0x%016x %d" % (i, a, n)

    def size_formula(self) -> str:
        return (f"3 routes x {self.nstrip} strips x 2 signs x {NCLS} classes x {self.npat} patterns = {self.nstripidx}, "
                f"+ {self.nblock} overflow + {self.nblock} deep = {self.N}")


def enums64() -> dict:
    """The five spaces of the 64-bit operations, by the job word the soak uses."""
    es = [RoundEnum("conv", FP64, FP32), RoundEnum("rint", FP64), RoundEnum("cvtto", FP64, B=64),
          CvtfromEnum(FP64), ScalebEnum(FP64)]
    return {e.name: e for e in es}


def distinct(e) -> int:
    return len({e.operands(i) for i in range(e.N)})


# ---------------------------------------------------------------------------------------------------
# the decision rule (the study's, symmetry_check.py G5) and the exact classification of an operand by it
# ---------------------------------------------------------------------------------------------------

def decide(sign, mode, cls, lsb):
    """Round the MAGNITUDE up? cls: 0 exact, 1 below half, 2 exactly half, 3 above half. The study's `decide`, verbatim
    (the test loads the study's own and holds this copy to it)."""
    if mode == sf.RND_RTZ or cls == 0:
        return 0
    if mode == sf.RND_RNE:
        return 1 if (cls == 3 or (cls == 2 and lsb == 1)) else 0
    if mode == sf.RND_RMM:
        return 1 if cls >= 2 else 0
    if mode == sf.RND_RUP:
        return 1 if sign == 0 else 0
    if mode == sf.RND_RDN:
        return 1 if sign == 1 else 0
    raise ValueError(mode)


def ones_of(kept: int) -> bool:
    return kept > 0 and (kept & (kept + 1)) == 0


def cls_lsb_ones(m: int, ex: int, ulp: int):
    """(class, kept lsb, kept all ones) of the magnitude m * 2^ex rounded at the grid of weight 2^ulp, from the
    definitions: kept = m >> dropped, the dropped bits against half."""
    dropped = ulp - ex
    if dropped <= 0:
        kept = m << -dropped
        return 0, kept & 1, ones_of(kept)
    if dropped > m.bit_length():                 # the whole magnitude is under half the grid: nothing kept, below half
        return 1, 0, False
    kept, rem = m >> dropped, m & mask(dropped)
    half = 1 << (dropped - 1)
    cls = 0 if rem == 0 else (1 if rem < half else (2 if rem == half else 3))
    return cls, kept & 1, ones_of(kept)


def clip(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else (hi if v > hi else v)


def key_round(e, x: int):
    """The key (sign, position, class, lsb, ones) of a floating-point operand of a RoundEnum: the position is the
    leading exponent clipped to the structural range, the class and the kept bits are the rounding's at that
    position. None for a zero, an infinity or a NaN."""
    u = sf.unpack(e.src, x)
    if u.kind not in (sf.NORM, sf.SUB):
        return None
    top = u.m.bit_length() - 1 + u.e
    if e.kind == "conv":
        ulp = max(top - e.dst.man_w, e.dst.emin - e.dst.man_w)
    else:
        ulp = 0
    cls, lsb, ones = cls_lsb_ones(u.m, u.e, ulp)
    return (u.sign, clip(top, e.lo_e, e.hi_e), cls, int(lsb), int(ones))


def key_cvtfrom(e, v: int, unsigned: int):
    """(source kind, bit length, class, lsb, ones) of a 64-bit integer source (v is the source's bit pattern)."""
    sgn = 0
    if not unsigned and v >> (e.Wi - 1):
        sgn, v = 1, (-v) & mask(e.Wi)
        if v == 0:
            v = 1 << (e.Wi - 1)
    L = v.bit_length()
    cls, lsb, ones = cls_lsb_ones(v, 0, max(0, L - e.dst.prec))
    return (2 if unsigned else sgn, L, cls, int(lsb), int(ones))


def key_scaleb(e, x: int, n: int):
    """(sign, strip or 'ovf' or 'deep', class, lsb, ones) of x * 2^n, or None where the result is in range (exact)."""
    f = e.fmt
    u = sf.unpack(f, x)
    if u.kind not in (sf.NORM, sf.SUB):
        return None
    r = u.m.bit_length() - 1 + u.e + n
    if r > f.emax:
        return (u.sign, "ovf", 0, 0, 0)
    if r >= f.emin:
        return None
    s = f.emin - r
    if s > e.P + 1:                              # under a quarter of the smallest subnormal: below half, nothing kept
        return (u.sign, "deep", 1, 0, 0)
    cls, lsb, ones = cls_lsb_ones(u.m, u.e + n, f.emin - f.man_w)
    return (u.sign, s, cls, int(lsb), int(ones))


# ---------------------------------------------------------------------------------------------------
# the coverage check: every key some encoding exhibits is reached by some enumerated case
# ---------------------------------------------------------------------------------------------------

def universe_and_reached(e, drop_class: int | None = None, drop_by: str = "key"):
    """(universe, reached): the keys over EVERY encoding of the format (or every source integer, or every
    encoding x exponent pair), and the keys of the enumerated cases.

    drop_class plants an enumerator that is missing one class, and the check must then fail by name. drop_by="key"
    removes every case whose operand has that dropped class (an enumerator that never produces one); drop_by="slot"
    leaves the construction and gives the cases of one class SLOT the next class's operand instead (a wrong class
    selector), which a class reached a second way (a walking one onto the class-0 representative lands on the guard
    bit, which is class 2) can hide."""
    uni, reached = set(), set()
    slot = drop_class if drop_by == "slot" else None

    def add(k):
        if k and not (drop_class is not None and drop_by == "key" and k[1] != "ovf" and k[2] == drop_class):
            reached.add(k)

    if isinstance(e, RoundEnum):
        for x in range(1 << e.src.width):
            k = key_round(e, x)
            if k:
                uni.add(k)
        for i in range(e.N):
            pi, sign, c, t = e.split(i)
            if c == slot:
                c = (c + 1) % NCLS
            b, d = e.position(pi)
            add(key_round(e, fp_encode(e.src, sign, b, sig(e.P, d, c, t))))
    elif isinstance(e, CvtfromEnum):
        for v in range(1 << e.Wi):
            uni.add(key_cvtfrom(e, v, 0))
            uni.add(key_cvtfrom(e, v, 1))
        for i in range(e.N):
            if i >= e.N - e.nspecial:
                v, u = e.operands(i)
            else:
                ci, _s, c, t = e.split(i)
                if c == slot:
                    c = (c + 1) % NCLS
                sv, L = e.cells[ci]
                m = sig(L, max(0, L - e.dst.prec), c, t)
                v, u = ((-m) & mask(e.Wi) if sv == 1 else m), (1 if sv == 2 else 0)
            add(key_cvtfrom(e, v, u))
    else:
        f = e.fmt
        span = 2 * (f.emax - f.emin + f.man_w + e.P) + 8
        for x in range(1 << f.width):
            for n in range(-span, span + 1):
                k = key_scaleb(e, x, n)
                if k:
                    uni.add(k)
        for i in range(e.N):
            a, n = e.operands(i)
            if slot is not None and i < e.nstripidx:
                pi, sign, c, t = e.split(i)
                if c == slot:
                    a, n = e.operands(i + ((((c + 1) % NCLS) - c) * e.npat))
            add(key_scaleb(e, a, n))
    return uni, reached


def carry_pairs(keys, attrs) -> set:
    """The (key, attribute) pairs that are a CARRY out of the kept bits: the kept bits are all ones and the attribute rounds
    the magnitude up (by the decision rule), so the increment runs the whole carry chain and moves the exponent."""
    out = set()
    for k in keys:
        if k[1] == "ovf" or not k[4]:
            continue
        for a in attrs:
            if decide(1 if k[0] == 1 else 0, MODE_OF[a], k[2], k[3]):
                out.add((k, a))
    return out


def carry_coverage(e):
    """(carry pairs over every encoding, carry pairs the enumerated cases reach)."""
    uni, reached = universe_and_reached(e)
    return carry_pairs(uni, e.attrs), carry_pairs(reached, e.attrs)


def coverage(e, drop_class: int | None = None, drop_by: str = "key"):
    """(keys over every encoding, of them reached, the keys missed, keys reached that no encoding has)."""
    uni, reached = universe_and_reached(e, drop_class, drop_by)
    return len(uni), len(reached & uni), sorted(uni - reached, key=str), len(reached - uni)


def constructive(e) -> tuple:
    """The check at widths where exhaustion is out of reach (p = 24 and 53): for every index whose cell is non-
    degenerate (at least 2 dropped bits and 3 kept bits: with 2 kept bits the patterns "lsb 1, bits above not all
    ones" and "lsb 1, all ones" are the same two bits) and whose pattern is one of the four kept-bit patterns,
    the key of the operand the enumerator BUILDS equals the key the index NAMES: (sign, position, class, lsb,
    kept all ones). Every such tuple is then reached, by construction, at this width as at the small ones. The
    rest of a key's validity (which classes and patterns exist at a position) is a function of whether the dropped
    width is 0, 1 or at least 2 and the kept width at most 0, 1, 2 or at least 3, and the small formats hold every such regime. Returns (indices
    checked, indices whose actual key differs from the named one, the first few of those)."""
    checked, bad, firsts = 0, 0, []

    def note(i, got, want):
        nonlocal bad
        bad += 1
        if len(firsts) < 5:
            firsts.append((i, got, want))

    if isinstance(e, RoundEnum):
        for i in range(e.N):
            pi, sign, c, t = e.split(i)
            b, d = e.position(pi)
            k = e.P - d
            if b == 0 or d < 2 or k < 3 or t >= 4:
                continue
            checked += 1
            got = key_round(e, e.operand(i))
            want = (sign, clip(b - e.src.bias, e.lo_e, e.hi_e), c, t & 1, int(t == 3))
            if got != want:
                note(i, got, want)
    elif isinstance(e, CvtfromEnum):
        for i in range(e.N - e.nspecial):
            ci, _s, c, t = e.split(i)
            sv, L = e.cells[ci]
            d = max(0, L - e.dst.prec)
            if d < 2 or e.dst.prec < 2 or t >= 4:
                continue
            checked += 1
            v, u = e.operands(i)
            got = key_cvtfrom(e, v, u)
            want = (sv, L, c, t & 1, int(t == 3))
            if got != want:
                note(i, got, want)
    else:
        for i in range(e.nstripidx):
            pi, sign, c, t = e.split(i)
            route, s = divmod(pi, e.nstrip)
            s += 1
            d = s - 1 if route == 2 else s
            P = e.W if route == 2 else e.P
            if d < 2 or P - d < 3 or t >= 4:
                continue
            checked += 1
            a, n = e.operands(i)
            got = key_scaleb(e, a, n)
            want = (sign, s, c, t & 1, int(t == 3))
            if got != want:
                note(i, got, want)
    return checked, bad, firsts


def wide_enums() -> dict:
    """The enumerators at p = 24 and p = 53, where `constructive` stands in for exhaustion."""
    return {
        "conv fp64->fp32 (p 53 -> 24)": RoundEnum("conv", FP64, FP32),
        "rint fp32 (p 24)": RoundEnum("rint", FP32),
        "rint fp64 (p 53)": RoundEnum("rint", FP64),
        "cvtto fp32 (p 24, B 32)": RoundEnum("cvtto", FP32, B=32),
        "cvtto fp64 (p 53, B 64)": RoundEnum("cvtto", FP64, B=64),
        "cvtfrom i64 -> fp32 (p 24)": CvtfromEnum(FP32, 64),
        "cvtfrom i64 -> fp64 (p 53)": CvtfromEnum(FP64, 64),
        "scaleb fp32 (p 24)": ScalebEnum(FP32),
        "scaleb fp64 (p 53)": ScalebEnum(FP64),
    }


def small_enums() -> dict:
    """The five enumerators built at e4m3 and e5m6 (widths where the study's exhaustion works). cvtto's widest
    target B stays below the format's emax, so its structural exponents are all finite."""
    return {
        "conv e5m6->e4m3": RoundEnum("conv", E5M6, E4M3),
        "rint e5m6": RoundEnum("rint", E5M6),
        "rint e4m3": RoundEnum("rint", E4M3),
        "cvtto e5m6 (B=8)": RoundEnum("cvtto", E5M6, B=8),
        "cvtto e4m3 (B=6)": RoundEnum("cvtto", E4M3, B=6),
        "cvtfrom i8 -> e4m3": CvtfromEnum(E4M3, 8),
        "cvtfrom i10 -> e5m6": CvtfromEnum(E5M6, 10),
        "scaleb e4m3": ScalebEnum(E4M3),
    }


# ---------------------------------------------------------------------------------------------------
# what a cvtto64 index compares: the pairs of (operand, integer target) the soak skips
# ---------------------------------------------------------------------------------------------------

TARGET_RANGES = ((-(1 << 31), (1 << 31) - 1), (0, (1 << 32) - 1), (-(1 << 63), (1 << 63) - 1), (0, (1 << 64) - 1))
MODE_OF = {"rne": sf.RND_RNE, "rtz": sf.RND_RTZ, "rdn": sf.RND_RDN, "rup": sf.RND_RUP, "rmm": sf.RND_RMM}


def rounded_integer(fmt: FpFormat, x: int, attr: str):
    """The integer attribute `attr` rounds the finite operand x to, by the decision rule; None for a NaN or an
    infinity (no target holds them)."""
    u = sf.unpack(fmt, x)
    if u.kind in (sf.NAN, sf.INF):
        return None
    if u.kind == sf.ZERO:
        return 0
    if u.e >= 0:
        mag = u.m << u.e
    else:
        cls, lsb, _ = cls_lsb_ones(u.m, u.e, 0)
        mag = (u.m >> -u.e) + decide(u.sign, MODE_OF[attr], cls, lsb)
    return -mag if u.sign else mag


def expected_skipped_cvtto(e: RoundEnum, lo: int, hi: int, attr: str) -> int:
    """The (operand, target) pairs of the indices [lo, hi) that cvtto64-class must SKIP, counted here from the rule
    alone: a pair is compared exactly when the rounded integer lies in the target's range."""
    skipped = 0
    for i in range(lo, hi):
        r = rounded_integer(e.src, e.operand(i), attr)
        skipped += len(TARGET_RANGES) if r is None else sum(1 for tmin, tmax in TARGET_RANGES if not tmin <= r <= tmax)
    return skipped


# ---------------------------------------------------------------------------------------------------
# the rounding stand-in and the planted defect (the soak's own random draws, ported)
# ---------------------------------------------------------------------------------------------------

M64 = (1 << 64) - 1


class SoakRng:
    """clause5_soak.c's xorshift64 and banded64(), ported: state = seed | 1; the band draw is evaluated before the
    jitter draw (the order gcc 11 and 12 give `bands[rng() % 7] + (rng() % 3)`, MEASURED by parcel SC)."""

    def __init__(self, seed: int):
        self.s = (seed | 1) & M64

    def rng(self) -> int:
        x = self.s
        x ^= (x << 13) & M64
        x ^= x >> 7
        x ^= (x << 17) & M64
        self.s = x
        return x

    def banded64(self) -> int:
        x = self.rng()
        if (self.rng() & 3) == 0:
            bands = (0, 1, 2, 1023, 2044, 2045, 2046)
            e = bands[self.rng() % 7] + (self.rng() % 3)
            if e > 2047:
                e = 2047
            x = (x & 0x800FFFFFFFFFFFFF) | (e << 52)
        return x


def standin_convert(x: int, mode: int, defect: str | None = None):
    """A stand-in for libcft's fp64 -> fp32 rounding unit, written as the structure the second level assumes: kept
    bits, guard, a sticky tree, the kept lsb, the carry. defect='sticky-no-lsb' plants a sticky tree that leaves
    out the lowest dropped bit. Returns the fp32 encoding, or None for a special or an overflow (not compared)."""
    u = sf.unpack(FP64, x)
    if u.kind not in (sf.NORM, sf.SUB):
        return None
    top = u.m.bit_length() - 1 + u.e
    ulp = max(top - 23, -126 - 23)
    dropped = ulp - u.e
    if dropped <= 0:
        kept, guard, sticky = u.m << -dropped, 0, 0
    else:
        kept = u.m >> dropped
        guard = (u.m >> (dropped - 1)) & 1
        low = u.m & mask(dropped - 1)
        if defect == "sticky-no-lsb":
            low &= ~1
        sticky = int(low != 0)
    lsb = kept & 1
    if mode == sf.RND_RNE:
        up = guard and (sticky or lsb)
    elif mode == sf.RND_RTZ:
        up = 0
    elif mode == sf.RND_RDN:
        up = u.sign and (guard or sticky)
    else:
        up = (not u.sign) and (guard or sticky)
    R = kept + int(bool(up))
    return _encode(FP32, u.sign, R, ulp)


def predict_round(dst: FpFormat, sign: int, m: int, ex: int, ulp: int, mode: int):
    """The encoding in dst of the magnitude m * 2^ex rounded at the grid of weight 2^ulp, by the decision rule on the
    class and lsb the key reads off the definitions (kept bits, the dropped bits against half): kept + decide(...).
    None where the result overflows dst. The test holds this to the golden model on every enumerated case, which is
    what ties the keys' classification to the authority."""
    cls, lsb, _ = cls_lsb_ones(m, ex, ulp)
    dropped = ulp - ex
    kept = (m << -dropped) if dropped <= 0 else (0 if dropped > m.bit_length() else m >> dropped)
    return _encode(dst, sign, kept + decide(sign, mode, cls, lsb), ulp)


def standin_pair(x: int, mode: int):
    """(the stand-in's result, the planted stand-in's result) for one operand, sharing the work; None where the
    operand is a special or the result overflows."""
    u = sf.unpack(FP64, x)
    if u.kind not in (sf.NORM, sf.SUB):
        return None, None
    top = u.m.bit_length() - 1 + u.e
    ulp = max(top - 23, -126 - 23)
    dropped = ulp - u.e
    if dropped <= 0:
        r = _encode(FP32, u.sign, u.m << -dropped, ulp)
        return r, r
    kept = u.m >> dropped
    guard = (u.m >> (dropped - 1)) & 1
    low = u.m & mask(dropped - 1)
    st_ok, st_bad = int(low != 0), int((low & ~1) != 0)
    lsb = kept & 1

    def up(sticky):
        if mode == sf.RND_RNE:
            return int(bool(guard and (sticky or lsb)))
        if mode == sf.RND_RTZ:
            return 0
        if mode == sf.RND_RDN:
            return int(bool(u.sign and (guard or sticky)))
        return int(bool((not u.sign) and (guard or sticky)))

    ok, bad = up(st_ok), up(st_bad)
    a = _encode(FP32, u.sign, kept + ok, ulp)
    return a, (a if ok == bad else _encode(FP32, u.sign, kept + bad, ulp))


def defect_experiment(attrs=("rne", "rup"), seeds=(1, 77)) -> dict:
    """The planted rounding defect (a sticky tree that leaves out the lowest dropped bit) against the class set and
    against an EQUAL number of the soak's own random draws (clause5-soak conv64to32's banded64(), per seed, per
    attribute). Counts the operands where the planted stand-in's result differs from the golden model's; the correct
    stand-in is held to the golden model on the candidates and on every 61st index."""
    e = enums64()["conv64to32-class"]
    res = {"N": e.N, "attrs": {}}
    for name in attrs:
        mode = MODE_OF[name]
        cls_hits, cls_first, wrong_good = 0, None, 0
        for i in range(e.N):
            x = e.operand(i)
            good, bad = standin_pair(x, mode)
            if good is None:
                continue
            cand = good != bad
            if cand or i % 61 == 0:
                ref = sf.convert(FP64, FP32, x, mode)[0]
                wrong_good += good != ref
                if cand and bad != ref:
                    cls_hits += 1
                    cls_first = cls_first or (i, x)
        rnd = {}
        for seed in seeds:
            rg = SoakRng(seed)
            hits = 0
            for _ in range(e.N):
                x = rg.banded64()
                good, bad = standin_pair(x, mode)
                if good is not None and good != bad:
                    hits += bad != sf.convert(FP64, FP32, x, mode)[0]
            rnd[seed] = hits
        res["attrs"][name] = {"class_set_hits": cls_hits, "first": cls_first, "stand_in_vs_golden": wrong_good,
                              "random_hits": rnd}
    return res


def _encode(fmt: FpFormat, sign: int, R: int, u: int):
    """The encoding of (-1)^sign * R * 2^u, or None when it overflows."""
    if R == 0:
        return sign << (fmt.width - 1)
    if R == 1 << (fmt.man_w + 1):
        R, u = R >> 1, u + 1
    top = R.bit_length() - 1 + u
    if top < fmt.emin:
        if u != fmt.emin - fmt.man_w or R >= (1 << fmt.man_w):
            return None
        return (sign << (fmt.width - 1)) | R
    if top > fmt.emax:
        return None
    if R.bit_length() - 1 > fmt.man_w:
        return None
    frac = (R << (fmt.man_w - (R.bit_length() - 1))) & fmt.man_mask
    return (sign << (fmt.width - 1)) | ((top + fmt.bias) << fmt.man_w) | frac


# ---------------------------------------------------------------------------------------------------
# command line
# ---------------------------------------------------------------------------------------------------

def _sizes() -> None:
    for name, e in enums64().items():
        print(f"{name}: N = {e.size_formula()}; k = {e.k}; distinct operands {distinct(e)}; attributes {','.join(e.attrs)}")


def _check() -> int:
    bad = 0
    for label, e in small_enums().items():
        nu, nr, missing, extra = coverage(e)
        cu, cr = carry_coverage(e)
        print(f"coverage {label}: {nu} keys over every encoding, {nr} reached by {e.N} cases, {len(missing)} missing, "
              f"{extra} reached beyond; carries out of the kept bits (key, attribute): {len(cu)} exist, {len(cu & cr)} reached")
        bad += len(cu) == 0 or not cu <= cr
        bad += bool(missing)
        for c in range(NCLS):
            _, _, miss_c, _ = coverage(e, drop_class=c)
            print(f"   plant, no case of class {CLS_NAMES[c]}: {len(miss_c)} keys missing" + (f", e.g. {miss_c[0]}" if miss_c else ""))
            bad += not miss_c
            _, _, miss_s, _ = coverage(e, drop_class=c, drop_by="slot")
            print(f"   plant, class slot {CLS_NAMES[c]} mis-selected: {len(miss_s)} keys missing")
    for label, e in wide_enums().items():
        n, nbad, firsts = constructive(e)
        print(f"constructive {label}: {e.N} indices, {n} non-degenerate indices whose built key is checked against the key "
              f"the index names, {nbad} differ" + (f", e.g. {firsts[0]}" if firsts else ""))
        bad += bool(nbad) or n == 0
    return 1 if bad else 0


def main(argv) -> int:
    if len(argv) >= 2 and argv[1] == "--sizes":
        _sizes()
        return 0
    if len(argv) == 5 and argv[1] == "--dump":
        e = enums64()[argv[2]]
        lo, hi = int(argv[3], 0), int(argv[4], 0)
        out = sys.stdout
        for i in range(lo, hi):
            out.write(e.dump_line(i) + "\n")
        return 0
    if len(argv) >= 2 and argv[1] == "--check":
        return _check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
