# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The math library's golden generator (step 6, M1's build, parcel E1):
exp, as a fragment of a tile program.

transcend.py DEFINES exp, expm1, exp2, log, log1p and log2: bits and flags,
correctly rounded, for every argument. A tile has none of them as an
instruction. M1 builds each as a ROUTINE - a fragment of existing
instructions, in C4's shape (routines.Fragment), that the compiler inlines
where a node stands, as it inlines division and square root. This module
builds the fragments. They are built, not read from a program as C4's are:
the construction below IS the design of docs/studies/M1-exp-log.md, whose
model (docs/studies/m1/) this file ports into the tree; nothing here
imports it. So far it builds exp. The other five come in M1's later
parcels, each as this one was.

The interface, and only this, is what a battery may rely on:

  fragment(name, fmt, rnd)  the specialised routines.Fragment of `name`
                            ("exp") at fmt (FP32, FP64, FP128 or FP256)
                            under the program's attribute rnd, held to
                            invariants() - the widened form of C4's - as
                            routines.fragment() holds a division
  evaluate(f, x)            one lane: the argument's bits x run through
                            f's body, instruction by instruction, with
                            softfloat.compute as seq.py's ALU computes -
                            the pair (result bits, flag word)

What the fragment is (the study's sections 2.1, 2.2, 3.1 and 4):

  classify   NaN, signalling, infinity, zero, sign, the two screens, the
             tiny gate: conditions the specials select on
  reduce     n = round(x 8/ln2) by the magic-number FMA, one rounding;
             r = x - n ln2/8 by Cody-Waite, |r| <= rho: at fp64, fp128 and
             fp256 ln2/8 in three words (the study's 2.2) and r a double
             word; at fp32 ln2/8 in five words and r in three (2.5)
  lookup     T_j = 2^(j/8), j = n mod 8, two words (three at fp32), a
             SELECT tree over j's three bits - bank words only, no scratch
             slot
  scale      2^k1 and 2^k2, k = floor(n/8) and k1 = floor(k/2), by integer
             arithmetic on the encoding of the magic-number sum
  tail,head  Y(r) = (e^r - 1)/r by Taylor: a single-word Horner tail
             (FMA) down to degree K, then K double-word steps (TwoProd by
             FMA, Fast2Sum where the exponents are ordered)
  Z, recon   Z = e^r - 1 as a double word; V = T (1 + Z) = V_h + V_l
  final      R = rnd(V_h + V_l); the IN-LANE TEST: both ends of V's error
             interval, V_l - Bv rounded down and V_l + Bv rounded up with
             Bv = 2^-(p+G) |V_h|, are added to V_h under rnd; a lane where
             the two roundings differ is not decided and is MARKED
  fixed grid a result that may be subnormal is rounded once on its own
             grid (k <= emin), its own test beside the main one
  specials   NaN, +-inf, +-0, the screens, in the order of the study's
             section 4, selected over the main path, lowest priority first

The routine runs QUIET, its body, ENDQUIET, then RAISE of its flag word,
as C4's do (cftc/inline.py): the flag word's bits [4:0] are exactly the
operation's IEEE flags, in FLAGS's order, and bit 7 marks a lane the test
could not decide (R24; seq.RAISE_MARK). A marked lane's value is the
routine's best guess, rnd(V_h + V_l), and the caller replays the lane with
the definition. Its error bound is relative, 2^-(p+G) with G the guard:
44 at fp64, 46 at fp128 and fp256, 40 at fp32 (Logan, 2026-10-12, the
study's questions 1 and 2).

Two builders. fp64, fp128 and fp256 hold V as a DOUBLE word. fp32's double
word floors near 2^-44.7, short of 2^-(24+40), so fp32's reduction, table,
head and reconstruction carry THREE words (the study's 2.5); that fragment
keeps 33 to 34 values live at once and does not fit seq.py's 32 registers,
so it is built, held to the invariants and run by evaluate(), not by
routines.program (the live cap, LIVE_CAP, is not applied to it; its count
is reported).

No augmented addition: the quad is built without R21 (revision 8's question
9), so every error-free sum is a Fast2Sum (3 instructions) where the
exponents of its two terms are provably ordered and a TwoSum (6) where they
are not, as the study's design has it: the double-word exp holds nine
Fast2Sums and one TwoSum, counted in Build.meta["fast_two_sum"] and
["two_sum"]. That is the sense of "TwoSum, not augadd".

Every constant is DERIVED - from mpmath at 3,000 bits or from an exact
rational - and rounded once. `python -m cft_golden.mathlib --check`
re-derives each constant that the built fragments hold, in integer
arithmetic that shares nothing with the generator or with mpmath, and
exits non-zero on a difference.

The instrumented form. build_exp() returns a Build, which keeps what the
specialised fragment drops: the unpruned body, each instruction's phase,
and the probes (V_h, V_l, Bv, the biased exponent Ek, and the values
between). Build.fragment() is the fragment; the error budget of
python/tests/mathlib_budget.py reads the rest. build_exp(...,
plant=name) builds the fragment with one named fault, for the tests: each
plant is a defect the study's model found in itself or one a check of this
file's tests must see (PLANTS).

Marks, as the study's: every figure in a comment is READ, COMPUTED or
stated as a design; what was MEASURED is in docs/VALIDATION.md's entry for
parcel E1, with its commands.
"""

import argparse
import functools
import math
import sys
from fractions import Fraction

import mpmath

from . import asm, routines, seq
from . import softfloat as sf
from .formats import FP32, FP64, FP128, FP256, FpFormat

__all__ = ["fragment", "evaluate", "invariants", "flag_words", "build_exp",
           "Build", "plan_exp", "GUARD", "LIVE_CAP", "PLANTS", "FORMATS",
           "NAMES", "check_constants", "main"]

NAMES = ("exp",)                       # the routines built so far
FORMATS = (FP32, FP64, FP128, FP256)
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
ROUNDED = routines.ROUNDED

# The guard G: the error bound is 2^-(p+G) relative (Logan's decisions of
# 2026-10-12, the study's questions 1 and 2, "as recommended").
GUARD = {"fp32": 40, "fp64": 44, "fp128": 46, "fp256": 46}

# The table: N = 8 entries, read by a SELECT tree over bank words (the
# study's question 3).
N = 8
T_BITS = 3

# The bit of the flag word that marks a lane the in-lane test could not
# decide: bit 7, which RAISE reads as the mark (R24).
MARK = seq.RAISE_MARK
# the working precision of every derivation
LN2_BITS = 3000


# ---- exact arithmetic on encodings ----------------------------------------

def _frac(v):
    """An mpmath value as the exact Fraction it is (an mpf is a dyadic
    rational, so no rounding happens here). The sign is read from the mpf
    itself, the first field of its raw tuple: mpmath.libmp.to_man_exp
    returns the mantissa UNSIGNED by default (mpmath 1.3; 1.4 deprecates
    that default), which turns every negative value positive (through
    profile 3 the pool generators of vectors.py and
    host/tests/transcend_check.py took it so on the negative thresholds
    n ln2 and lost their signs: parcel E1's entry; since profile 3.1 they
    read the raw tuple as this does and call to_man_exp nowhere: parcel
    PS's)."""
    sign, man, ex, _bc = v._mpf_
    if not man and ex:
        raise ValueError(f"{v} is not a finite number")
    q = Fraction(int(man)) * (Fraction(2) ** int(ex))
    return -q if sign else q


def _enc(fmt: FpFormat, value, rnd=RNE):
    """The bits of the exact rational `value` rounded ONCE into fmt under
    rnd (zero is +0). The quotient is taken with eight guard bits and the
    remainder folded into a sticky bit below them, so round_pack sees the
    value's rounding position with the exact tie and sticky information."""
    v = Fraction(value)
    if v == 0:
        return 0
    sign = 1 if v < 0 else 0
    n, d = abs(v).numerator, abs(v).denominator
    e = n.bit_length() - d.bit_length() - fmt.prec - 8
    q, r = divmod(n, d << e) if e >= 0 else divmod(n << -e, d)
    return sf.round_pack(fmt, sign, (q << 1) | (1 if r else 0), e - 1, rnd)[0]


def _dec(fmt: FpFormat, bits):
    """The exact value of a finite encoding."""
    u = sf.unpack(fmt, bits)
    if u.kind == sf.ZERO:
        return Fraction(0)
    if u.kind in (sf.INF, sf.NAN):
        raise ValueError(f"{bits:#x} is not finite at {fmt.name}")
    v = Fraction(u.m) * (Fraction(2) ** u.e)
    return -v if u.sign else v


def _enc_exact(fmt: FpFormat, value):
    """_enc, refusing a value the format does not hold exactly."""
    bits = _enc(fmt, value)
    if _dec(fmt, bits) != Fraction(value):
        raise ValueError(f"{value} is not exact at {fmt.name}")
    return bits


def _pow2(fmt: FpFormat, k):
    """2^k as an encoding (exact: the format holds it)."""
    return _enc_exact(fmt, Fraction(2) ** k)


def _words(fmt: FpFormat, value, n):
    """`value` as n words, each the nearest to what is left: w0 = RN(v),
    w1 = RN(v - w0), ... as encodings."""
    v = Fraction(value)
    out = []
    for _ in range(n):
        b = _enc(fmt, v)
        out.append(b)
        v -= _dec(fmt, b)
    return out


def _truncated(fmt: FpFormat, value, nbits):
    """`value` truncated toward zero to `nbits` significant bits, exactly
    representable: so n * it is exact for any n of up to p - nbits bits."""
    v = Fraction(value)
    sign = -1 if v < 0 else 1
    v = abs(v)
    e = v.numerator.bit_length() - v.denominator.bit_length()
    while Fraction(2) ** e > v:
        e -= 1
    while Fraction(2) ** (e + 1) <= v:
        e += 1
    sc = Fraction(2) ** (nbits - 1 - e)
    t = Fraction(math.floor(v * sc)) / sc
    return _enc_exact(fmt, sign * t)


# ---- the constants, derived -------------------------------------------------

@functools.lru_cache(maxsize=None)
def _ln2():
    """ln 2 to 3,000 bits, as the exact rational it is."""
    with mpmath.workprec(LN2_BITS):
        return _frac(mpmath.log(2))


@functools.lru_cache(maxsize=None)
def _two_to_eighth(j):
    """2^(j/8) to 3,000 bits, as the exact rational it is."""
    with mpmath.workprec(LN2_BITS):
        return _frac(mpmath.mpf(2) ** (mpmath.mpf(j) / N))


def _coefficient(i):
    """The Taylor coefficient of r^i in Y(r) = (e^r - 1)/r, 1/(i+1)!:
    exact."""
    return Fraction(1, math.factorial(i + 1))


def _n_width(fmt: FpFormat):
    """nb: the bit width of the largest |n| the screens let through. The
    first Cody-Waite word holds p - nb bits, so n times it is exact. The
    overflow screen is (emax + 1) ln2 and the underflow screen (emin - p)
    ln2, so |n| is under N (max(emax + 1, p - emin) + 4): four more than
    the screens reach, for the rounding of n at their ends."""
    nmax = N * (max(fmt.emax + 1, -(fmt.emin - fmt.prec)) + 4)
    return nmax.bit_length()


def _screens(fmt: FpFormat):
    """(XOVF, XUNF) as encodings: the overflow screen RU((emax+1) ln 2)
    and the underflow screen RD((emin-p) ln 2). x >= XOVF gives e^x above
    2^(emax+1), an overflow under every attribute; x <= XUNF gives e^x
    below 2^(emin-p), under half the smallest subnormal. ln 2 is
    irrational, so neither screen is ever an equality."""
    l2 = _ln2()
    return (_enc(fmt, (fmt.emax + 1) * l2, RUP),
            _enc(fmt, (fmt.emin - fmt.prec) * l2, RDN))


# ---- the plan: K and D ------------------------------------------------------

def _rho(fmt: FpFormat, cushion_bits):
    """The reduction's bound on |r_h|: (1/2 + 2^-cushion) ln2/N. The
    cushion covers the magic-number FMA picking the neighbour of the
    nearest n, which happens only where x 8/ln2 is within the rounding of
    8/ln2 times |n| of a half-integer: that is 2^(nb-p) of a unit, and the
    cushion exceeds it."""
    return (Fraction(1, 2) + Fraction(1, 2 ** cushion_bits)) * _ln2() / N


def _cushion(fmt: FpFormat):
    """30 bits at fp64 and wider, where 2^(nb-p) is 2^-39 or less; 12 at
    fp32, where it is 2^-13."""
    return 12 if fmt.prec <= 24 else 30


def plan_exp(fmt: FpFormat, G):
    """(K, D) for the double-word exp: K double-word head steps and a
    single-word tail to degree D of Y, the smallest whose estimated bound
    is two bits under 2^-(p+G): the tail through r^(K+1),
    2u rho^(K+1)/(K+1)! (u = 2^-p), within half the target, and with the
    truncation rho^(D+2)/(D+2)! (1 + rho) and the double word's own floor
    10 u^2 under the target (the study's 3.2). Exact rational arithmetic,
    so the plan is the same on every platform."""
    p = fmt.prec
    u = Fraction(1, 2 ** p)
    rho = _rho(fmt, _cushion(fmt))
    target = Fraction(1, 2 ** (p + G + 2))
    floor = 10 * u * u
    if floor >= target:
        raise ValueError(f"G = {G} is past the double word's floor at "
                         f"{fmt.name}: 10 u^2 = 2^{math.log2(floor):.1f}")

    def tail(K):
        return 2 * u * rho ** (K + 1) / math.factorial(K + 1)

    def trunc(D):
        return rho ** (D + 2) / math.factorial(D + 2) * (1 + rho)
    K = 1
    while tail(K) > target / 2 and K < 60:
        K += 1
    D = K
    while tail(K) + trunc(D) + floor > target and D < 150:
        D += 1
    return K, D


# ---- the builder ------------------------------------------------------------

# Faults, for the tests: build_exp(..., plant=name) builds the fragment with
# one of them. Each is a defect the study's model found in itself (section
# 3.6) or the study's table of plants (section 8), or one a check of
# python/tests/test_mathlib.py needs to see fail; the value says which.
PLANTS = {
    "table_entry": ("dw tw", "T_3's high word one ulp off (the study's "
                    "first plant)"),
    "c1_ulp": ("dw tw", "the reduction's first word C1 one ulp off (the "
               "second)"),
    "bound_loose": ("dw tw", "the in-lane bound 2^-40 smaller: Bv = "
                    "2^-(p+G+40) |V_h| (the third)"),
    "bound_wide": ("dw tw", "the in-lane bound 2^16 times wider: marks far "
                   "more lanes than the law allows"),
    "bound_half": ("dw tw", "the in-lane bound half as wide: Bv = "
                   "2^-(p+G+1) |V_h|"),
    "bound_double": ("dw tw", "the in-lane bound twice as wide: Bv = "
                     "2^-(p+G-1) |V_h|"),
    "mark_silenced": ("dw tw", "the mark never ORed into the flag word (the "
                      "fifth)"),
    "rl_through_y": ("dw", "defect 1: r_l carried through Y(r_h), not "
                     "e^(r_h)"),
    "c3_dropped": ("dw", "Cody-Waite in two words: n C3 dropped from r's low "
                   "word (defect 2's kind, in exp's reduction)"),
    "tiny_gate_off": ("dw tw", "the tiny-argument gate removed (the study's "
                      "tenth)"),
    "screen_ulp": ("dw tw", "the overflow screen one ulp low"),
    "head_short": ("dw", "two fewer double-word head steps (K - 2)"),
    "tininess_klt_only": ("dw tw", "tininess decided on k alone, not after "
                          "rounding"),
    "c0_wrong": ("dw tw", "the fixed grid's offset at k = emin 2^-3, not "
                 "2^-4: C + V reaches 2 and the grid doubles"),
    "square_term_dropped": ("tw", "fp32: the square term of e^(r1+r2) - 1 "
                            "dropped (the study's defect 7)"),
    "two_sum_all": ("dw tw", "every Fast2Sum built as a TwoSum: the same "
                    "values, 3 more instructions each, counted otherwise"),
    "abs_by_copysign": ("dw tw", "|x| built as copysign(x, +0): the same "
                        "values, an opcode outside the design's set"),
    "odd_dropped": ("dw tw", "the fixed grid's round-to-odd of V_l's share "
                    "built as round-to-nearest: V_l is lost where V_h is "
                    "exactly on a half-grid point and |V_l| is under half an "
                    "ulp of the remainder, and no argument is known to reach "
                    "such a state (check_fixed_grid hands it one)"),
}


class Build:
    """A routine under construction and, finished, its instrumented form.

    The body is straight-line SSA in C4's shape: instruction i defines value
    i, each (opcode, attribute, srcs), a src ("in", name), ("v", i) or
    ("w", name). An instruction is hash-consed on (opcode, attribute,
    operands) as cftc's inliner shares them, and routines.simplify's rules
    apply as it is made, so a SELECT on a word, a SELECT of one value twice
    and an IOR of a value with itself are never emitted.

    Beside the body it keeps, and Build.fragment() drops:
      phase_of  the phase each instruction was made in (the study's section
                5.1 counts by these: classify, reduce, lookup, scale, tail,
                head, Z, recon, final, fixed-grid, special)
      probes    {name: ref}: the values the error budget reads, V_h, V_l,
                Bv, Ek, and the ones between
      roles     {role: ref}: every DERIVED constant (a table word, a
                Cody-Waite word, a coefficient, a screen, 2^-(p+G), ...) by
                what it is, so that `--check` can re-derive each
      words     every word made, used or not, {name: bits}
      meta      the parameters (G, K, D, the scale offset OFF, ...)
    """

    def __init__(self, fmt: FpFormat, rnd: int, name: str):
        self.fmt = fmt
        self.rnd = rnd
        self.name = name
        self.inputs = ("a",)
        self.body = []
        self.phase_of = []
        self.words = {}
        self.word_of = {}
        self.roles = {}
        self.probes = {}
        self.meta = {}
        self.phase = "setup"
        self.result = None
        self.flags = None
        self._keyed = {}
        self._eft = {"two_sum": 0, "fast_two_sum": 0}

    # ---- words ----
    def word(self, bits, name=None):
        """The ref of the bank word holding `bits`: one word for each
        distinct bit pattern, named for the first request."""
        bits &= (1 << self.fmt.width) - 1
        if bits in self.word_of:
            return ("w", self.word_of[bits])
        nm = name or f"K{len(self.words)}"
        while nm in self.words:
            nm += "'"
        self.words[nm] = bits
        self.word_of[bits] = nm
        return ("w", nm)

    def const(self, role, bits, name=None):
        """word(), recording `role` for the check of the constants."""
        ref = self.word(bits, name or role)
        self.roles[role] = ref
        return ref

    def bits_of(self, s):
        return self.words[s[1]] if s[0] == "w" else None

    # ---- instructions ----
    def ins(self, op, srcs, rnd=None):
        if op in ROUNDED and rnd is None:
            rnd = RNE
        if op not in ROUNDED:
            rnd = None
        srcs = tuple(srcs)
        same = routines.simplify(op, srcs, self.bits_of, self.fmt.sign_mask)
        if same is not None:
            return same
        key = (op, rnd, srcs)
        if key in self._keyed:
            return self._keyed[key]
        self.body.append(key)
        self.phase_of.append(self.phase)
        ref = ("v", len(self.body) - 1)
        self._keyed[key] = ref
        return ref

    # The opcodes, operands in asm.OP_FIELDS' order (ADD and SUB read a and
    # c, MUL a and b, SELECT is c ? a : b).
    def fma(self, a, b, c, rnd=RNE):
        return self.ins(sf.OP_FMA, (a, b, c), rnd)

    def add(self, a, c, rnd=RNE):
        return self.ins(sf.OP_ADD, (a, c), rnd)

    def sub(self, a, c, rnd=RNE):
        return self.ins(sf.OP_SUB, (a, c), rnd)

    def mul(self, a, b, rnd=RNE):
        return self.ins(sf.OP_MUL, (a, b), rnd)

    def neg(self, a):
        return self.ins(sf.OP_NEG, (a,))

    def fabs(self, a):
        if self.meta.get("plant") == "abs_by_copysign":
            return self.ins(sf.OP_COPYSIGN, (a, self.word(0, "ZERO")))
        return self.ins(sf.OP_ABS, (a,))

    def sel(self, a, b, c):
        return self.ins(sf.OP_SELECT, (a, b, c))

    def cmplt(self, a, b):
        return self.ins(sf.OP_CMPLT, (a, b))

    def cmple(self, a, b):
        return self.ins(sf.OP_CMPLE, (a, b))

    def cmpeq(self, a, b):
        return self.ins(sf.OP_CMPEQ, (a, b))

    def iand(self, a, b):
        return self.ins(sf.OP_IAND, (a, b))

    def ior(self, a, b):
        return self.ins(sf.OP_IOR, (a, b))

    def ixor(self, a, b):
        return self.ins(sf.OP_IXOR, (a, b))

    def iadd(self, a, b):
        return self.ins(sf.OP_IADD, (a, b))

    def isub(self, a, b):
        return self.ins(sf.OP_ISUB, (a, b))

    def ishl(self, a, b):
        return self.ins(sf.OP_ISHL, (a, b))

    def ishr(self, a, b):
        return self.ins(sf.OP_ISHR, (a, b))

    def icmplt(self, a, b):
        return self.ins(sf.OP_ICMPLT, (a, b))

    # ---- the error-free transformations (no augadd: question 9) ----
    def two_sum(self, a, c):
        """(s, e): s = RN(a + c) and e the exact error, any exponents
        (Knuth's six)."""
        self._eft["two_sum"] += 1
        s = self.add(a, c)
        a1 = self.sub(s, c)
        b1 = self.sub(s, a1)
        return s, self.add(self.sub(a, a1), self.sub(c, b1))

    def fast_two_sum(self, a, c):
        """(s, e) for |a| >= |c| or a = 0 (Dekker's three)."""
        if self.meta.get("plant") == "two_sum_all":
            return self.two_sum(a, c)
        self._eft["fast_two_sum"] += 1
        s = self.add(a, c)
        return s, self.sub(c, self.sub(s, a))

    # ---- finishing ----
    def finish(self, result, flags):
        self.result, self.flags = result, flags
        self.meta.update(self._eft)
        return self

    def fragment(self):
        """The specialised routines.Fragment: C4's own specialise() over
        the body - which drops the values neither the result nor the flag
        word reaches and the words they alone read - named "exp"."""
        return routines.specialise(routines.Fragment(
            self.meta.get("fn", "exp"), self.fmt, self.rnd, self.inputs,
            self.body, self.result, self.flags, self.words, "read"))

    def run(self, x, want=(), over=None):
        """One lane through the UNPRUNED body: (result bits, flag word,
        {probe: bits}) for the probes named in `want`. The result and the
        flag word are the specialised fragment's, value for value.

        `over`, {probe name: bits}, replaces those probes' values as the
        body reaches them, so that what follows them runs on a state no
        argument is known to reach: python/tests/mathlib_harness's
        check_fixed_grid hands the fixed grid a V_h exactly on a half-grid
        point. A probe must be a value of the body, not a word, and what the
        body computes from a replaced probe is computed again: V_l is built
        from V_h, so replace both."""
        pos = {}
        for name, bits in (over or {}).items():
            ref = self.probes[name]
            if ref[0] != "v":
                raise ValueError(f"probe {name!r} is not a value of the body")
            pos[ref[1]] = bits & ((1 << self.fmt.width) - 1)
        vals = _values(self.fmt, self.body, self.words, x, pos)
        get = _getter(vals, self.words, x)
        return (get(self.result), get(self.flags),
                {k: get(self.probes[k]) for k in want if k in self.probes})


def _getter(vals, words, x):
    def get(s):
        if s[0] == "v":
            return vals[s[1]]
        if s[0] == "in":
            return x
        return words[s[1]]
    return get


def _values(fmt, body, words, x, over=None):
    """Every instruction's value on one lane, through softfloat.compute as
    seq.py's ALU calls it: a, b and c are the operand fields the opcode
    reads, the attribute is the instruction's (RNE where it has none).
    `over` {instruction index: bits} takes the place of those values."""
    vals = []
    get = _getter(vals, words, x)
    for i, (op, r, srcs) in enumerate(body):
        if over and i in over:
            vals.append(over[i])
            continue
        ops = {"ra": 0, "rb": 0, "rc": 0}
        for s, field in zip(srcs, asm.OP_FIELDS[op]):
            ops[field] = get(s)
        vals.append(sf.compute(fmt, op, ops["ra"], ops["rb"], ops["rc"],
                               RNE if r is None else r)[0])
    return vals


# ---- exp's constants, derived -----------------------------------------------

def _exp_constants(fmt: FpFormat, G, K, D, shift, plant):
    """{role: bits}: every derived constant of the double-word exp, each
    rounded once from an exact value:

      MAGIC            1.5 2^(p-1): n lands in t's low bits
      INVLN2N          RN(8/ln2)
      NC1, NC2, C2, C3 the Cody-Waite words of ln2/8: C1 TRUNCATED to
                       p - nb bits, so n C1 is exact (nb: _n_width), C2 the
                       nearest to what is left and C3 to what is left
                       after that; NC1 and NC2 are the negations
      TH_j, TL_j       2^(j/8) as two words, RN and then RN of the rest
      Y_i              the tail's coefficient 1/(i+1)!, RN, i = K..D
      CH_i, CL_i       the head's, as two words, i = 0..K-1
      XOVF, XUNF       the screens (_screens)
      TINYX            2^-(p+3): below it exp is decided by the side of 1
      C0               2^-4: the fixed grid's offset at k = emin
      BREL             2^-(p+G): the bound; `shift` inflates it for the
                       mark-rate law (2^shift times as wide)
      UNFB, OVFB       the answers of the two screens under rnd, which the
                       caller's attribute decides - added by the builder
    """
    p = fmt.prec
    l2 = _ln2()
    L = l2 / N
    c = {}
    c["MAGIC"] = _enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    c["INVLN2N"] = _enc(fmt, N / l2)
    C1 = _truncated(fmt, L, p - _n_width(fmt))
    rest = L - _dec(fmt, C1)
    C2 = _enc(fmt, rest)
    C3 = _enc(fmt, rest - _dec(fmt, C2))
    if plant == "c1_ulp":
        C1 += 1
    c["NC1"] = sf.negate(fmt, C1)
    c["NC2"] = sf.negate(fmt, C2)
    c["C2"], c["C3"] = C2, C3
    for j in range(N):
        hi, lo = _words(fmt, _two_to_eighth(j), 2)
        if plant == "table_entry" and j == 3:
            hi += 1
        c[f"TH{j}"], c[f"TL{j}"] = hi, lo
    for i in range(K, D + 1):
        c[f"Y{i}"] = _enc(fmt, _coefficient(i))
    for i in range(K):
        c[f"CH{i}"], c[f"CL{i}"] = _words(fmt, _coefficient(i), 2)
    c["XOVF"], c["XUNF"] = _screens(fmt)
    if plant == "screen_ulp":
        c["XOVF"] -= 1
    c["TINYX"] = _pow2(fmt, -(p + 3))
    c["C0"] = _pow2(fmt, -3 if plant == "c0_wrong" else -4)
    c["BREL"] = _pow2(fmt, -(p + G) + shift - _bound_plant(plant))
    return c


def _bound_plant(plant):
    """The bits a planted bound is off by: 2^-40 smaller (too loose: lanes
    that are not decided are not marked), 2^16 wider (marks far too many),
    half as wide and twice as wide (the bound's calibration, which the
    family's deepest windows pin)."""
    return {"bound_loose": 40, "bound_wide": -16, "bound_half": 1,
            "bound_double": -1}.get(plant, 0)


def _words_common(b: Build):
    """The words every builder uses, and their refs: the integers are raw
    encodings (two's complement), the flag words the values the flag word
    selects among."""
    fmt = b.fmt
    full = (1 << fmt.width) - 1
    mw = fmt.man_w

    def ib(v, name=None):
        v &= full
        return b.word(v, name or (f"I{v}" if v < 1 << 16 else None))
    r = {"ib": ib}
    r["ZERO"], r["ONE"] = b.word(0, "ZERO"), b.word(sf.one_bits(fmt), "ONE")
    r["INT1"] = ib(1)
    r["ABSM"] = ib(full ^ fmt.sign_mask, "ABSMASK")
    r["INF"] = b.word(sf.inf_bits(fmt), "INF")
    r["QBIT"] = ib(1 << (mw - 1), "QUIETBIT")
    r["QNAN"] = b.word(sf.qnan_bits(fmt), "QNAN")
    r["INX"] = ib(sf.FLAG_INEXACT, "FL_INEXACT")
    r["INXUNF"] = ib(sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW, "FL_INEXACT_UNDER")
    r["OVFINX"] = ib(sf.FLAG_OVERFLOW | sf.FLAG_INEXACT, "FL_OVER_INEXACT")
    r["INVALID"] = ib(sf.FLAG_INVALID, "FL_INVALID")
    r["MARKW"] = ib(MARK, "FL_MARK")
    return r


def _scale_offset(fmt: FpFormat):
    """OFF: the biased exponent of the scaled domain's 2^0 sits OFF above
    the true one, so Ek = k + bias + OFF is positive for every k the main
    path sees, and bias + OFF is even so that k1 = floor(k/2) and
    k2 = k - k1 come from one shift (the study's 2.2). OFF = p + 8, or one
    more."""
    off = fmt.prec + 8
    if (fmt.bias + off) % 2:
        off += 1
    return off


def _build_exp_dw(fmt: FpFormat, rnd: int, G, shift, plant):
    """exp at fp64, fp128 and fp256: V as a double word (the module
    docstring; the study's 2.2 and 3.1)."""
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    K, D = plan_exp(fmt, G)
    if plant == "head_short":
        K -= 2
    c = _exp_constants(fmt, G, K, D, shift, plant)
    b = Build(fmt, rnd, f"exp-{fmt.name}-{sf.RND_NAMES[rnd]}")
    b.meta.update(fn="exp", G=G, K=K, D=D, N=N, shift=shift, plant=plant,
                  family="double word")
    x = ("in", "a")
    w = b.word
    k_ = _words_common(b)
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    INF, QNAN, ABSM, QBIT = k_["INF"], k_["QNAN"], k_["ABSM"], k_["QBIT"]
    INX, INXUNF, OVFINX = k_["INX"], k_["INXUNF"], k_["OVFINX"]
    INVALID, MARKW = k_["INVALID"], k_["MARKW"]
    MAGIC = b.const("MAGIC", c["MAGIC"])
    MANW = ib(mw, "MANTISSA_WIDTH")

    # ---- classify: the conditions the specials select on -------------------
    b.phase = "classify"
    ax = b.iand(x, ABSM)                              # |x|, as an integer
    isnan = b.icmplt(INF, ax)
    issnan = b.sel(ZERO, isnan, b.iand(x, QBIT))      # NaN, quiet bit clear
    isinf = b.cmpeq(ax, INF)
    iszero = b.icmplt(ax, INT1)
    neg = b.ishr(x, ib(W - 1, "SIGN_SHIFT"))
    uns = b.cmple(x, b.const("XUNF", c["XUNF"]))      # x <= XUNF
    ovs = b.cmple(b.const("XOVF", c["XOVF"]), x)      # x >= XOVF
    # transcend.py decides |x| < 2^-(p+3) by the side of 1 alone: the
    # routine's R is that side (V = 1 + Z, Z with x's sign), so the in-lane
    # test, whose bound is relative to V, must not be consulted there
    tinyx = b.icmplt(ax, b.const("TINYX", c["TINYX"]))

    # ---- reduce: n = round(x 8/ln2), r = x - n ln2/8 in two words ----------
    b.phase = "reduce"
    t = b.fma(x, b.const("INVLN2N", c["INVLN2N"]), MAGIC)
    nf = b.sub(t, MAGIC)                              # n, as a float
    r1 = b.fma(nf, b.const("NC1", c["NC1"]), x)       # x - n C1: exact
    Q = b.mul(nf, b.const("NC2", c["NC2"]))           # -n C2, rounded
    Qe = b.fma(nf, b.const("C2", c["C2"]), Q)         # -(its error): exact
    s, e = b.two_sum(r1, Q)                           # r1 + Q = s + e, exact
    rh = s
    # r = rh + rl with rl = e - Qe - n C3; nrl = -rl, as the products below
    # want it
    low = b.sub(Qe, e)
    nrl = low if plant == "c3_dropped" else b.fma(
        nf, b.const("C3", c["C3"]), low)
    nr = b.neg(rh)
    b.probes.update(t=t, nf=nf, rh=rh, nrl=nrl)

    # ---- lookup: T_j = 2^(j/8), j = n mod 8, a SELECT tree -----------------
    b.phase = "lookup"
    bitsel = [b.iand(t, ib(1 << i)) for i in range(T_BITS)]

    def tree(vals):
        level = list(vals)
        for bit in bitsel:
            level = [b.sel(level[2 * m + 1], level[2 * m], bit)
                     for m in range(len(level) // 2)]
        return level[0]
    Th = tree([b.const(f"TH{j}", c[f"TH{j}"]) for j in range(N)])
    Tl = tree([b.const(f"TL{j}", c[f"TL{j}"]) for j in range(N)])
    b.probes.update(Th=Th, Tl=Tl)

    # ---- scale: 2^k1 and 2^k2 from n, integers on t's encoding -------------
    b.phase = "scale"
    OFF = _scale_offset(fmt)
    half = (fmt.bias + OFF) // 2
    b.meta["OFF"] = OFF
    Ek = b.ishr(b.isub(t, ib(c["MAGIC"] - N * (fmt.bias + OFF), "KOFFSET")),
                ib(T_BITS))                           # k + bias + OFF
    E1 = b.ishr(Ek, INT1)
    KB1 = ib(fmt.bias - half, "KBIAS1")
    S1 = b.ishl(b.iadd(E1, KB1), MANW)                # 2^k1
    S2 = b.ishl(b.iadd(b.isub(Ek, E1), KB1), MANW)    # 2^k2
    b.probes.update(Ek=Ek, S1=S1, S2=S2)
    # the fixed grid: u = 2^(emin - p + 1 - k) in the scaled domain; Cu is
    # the offset C = 2^(emin - k) (2^-4 at k = emin), hu the half-grid u/2
    KD = fmt.emin + 2 * fmt.bias + OFF
    # sub_p: k <= emin; klt: k < emin
    sub_p = b.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF + 1, "K_EMIN_P1"))
    klt = b.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF, "K_EMIN"))
    Cu = b.sel(b.ishl(b.isub(ib(KD, "K_KD"), Ek), MANW),
               b.const("C0", c["C0"]), klt)
    hu = None
    if rnd in (RNE, RMM):
        hu = b.ishl(b.isub(ib(KD - p, "K_KD_P"), Ek), MANW)
        b.probes["hu"] = hu
    b.probes.update(Cu=Cu, sub_p=sub_p, klt=klt)

    # ---- the polynomial Y(r) = sum r^i/(i+1)!: tail by FMA, head by pairs
    b.phase = "tail"
    y = b.const(f"Y{D}", c[f"Y{D}"])
    for i in range(D - 1, K - 1, -1):
        y = b.fma(y, rh, b.const(f"Y{i}", c[f"Y{i}"]))
    b.phase = "head"
    yh, yl = y, None
    for i in range(K - 1, -1, -1):
        CH = b.const(f"CH{i}", c[f"CH{i}"])
        CL = b.const(f"CL{i}", c[f"CL{i}"])
        pp = b.mul(yh, rh)
        ne = b.fma(yh, nr, pp)                        # pp - yh r = -(error)
        nl = b.fma(yl, nr, ne) if yl is not None else ne
        s, e = b.fast_two_sum(CH, pp)                 # |c| >= |pp|: ordered
        tt = b.sub(e, nl)
        yl = b.add(tt, CL) if c[f"CL{i}"] else tt
        yh = s

    # ---- Z = e^r - 1 as a double word ---------------------------------------
    b.phase = "Z"
    zp = b.mul(yh, rh)
    nze = b.fma(yh, nr, zp)
    nzl = b.fma(yl, nr, nze)
    # r_l enters through e^(r_h) ~ 1 + Z_h, rounded once (its error times
    # |r_l| is far below the bound), not through Y(r_h): that was the first
    # model's defect 1, an error of r_l r_h/2
    eh = yh if plant == "rl_through_y" else b.add(ONE, zp)
    nZl = b.fma(eh, nrl, nzl)
    b.probes.update(Yh=yh, Yl=yl, Zh=zp, nZl=nZl)

    # ---- reconstruct V = T (1 + Z) as V_h + V_l -----------------------------
    b.phase = "recon"
    P = b.mul(Th, zp)
    nPe = b.fma(Th, b.neg(zp), P)                     # P - Th Zh = -(error)
    S, e2 = b.fast_two_sum(Th, P)                     # |Th| >= |P|: ordered
    a1 = b.fma(Th, nZl, nPe)                          # -(Th Zl + Pe)
    a2 = b.fma(Tl, zp, Tl)                            # Tl (1 + Zh)
    lo = b.add(b.sub(e2, a1), a2)
    Vh, Vl = b.fast_two_sum(S, lo)                    # |S| >= |lo|: ordered
    b.probes.update(Vh=Vh, Vl=Vl)

    # ---- the final rounding and the in-lane test ----------------------------
    b.phase = "final"
    R = b.add(Vh, Vl, rnd)                            # the guess: rnd(Vh + Vl)
    Bv = b.mul(Vh, b.const("BREL", c["BREL"]))        # 2^-(p+G) |V|: exact
    lo_dn = b.sub(Vl, Bv, RDN)
    lo_up = b.add(Vl, Bv, RUP)
    R1 = b.add(Vh, lo_dn, rnd)
    R2 = b.add(Vh, lo_up, rnd)
    mk = b.ixor(R1, R2)                               # nonzero: not decided
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)

    # a result that may be subnormal (k <= emin) is rounded once on its own
    # grid: V_h split at C, V_l's share added after rounding to odd (its ulp
    # is finer than u/4), rounded under rnd, C taken off again
    b.phase = "fixed-grid"
    Z0 = b.add(Cu, Vh)
    W0 = b.sub(Z0, Cu)
    zr = b.sub(Vh, W0)
    if plant == "odd_dropped":
        ro = b.add(zr, Vl)                  # round-to-nearest: V_l can be lost
    else:
        s_ = b.add(zr, Vl, RTZ)
        eq = b.cmpeq(b.sub(s_, zr), Vl)
        ro = b.sel(s_, b.ior(s_, INT1), eq)           # round-to-odd of zr + Vl
    Ws = b.sub(b.add(Z0, ro, rnd), Cu)
    # the fixed grid's own test: V can straddle a boundary only where zr IS
    # one (+-u/2 for rne and rmm, 0 for the directed three) and |Vl| <= Bv
    c1 = b.cmpeq(b.fabs(zr), hu) if hu is not None else b.cmpeq(zr, ZERO)
    smallo = b.cmple(b.fabs(Vl), Bv)
    msub = b.sel(smallo, ZERO, c1)
    Wsel = b.sel(Ws, R, sub_p)
    mk = b.sel(ONE, mk, b.sel(msub, ZERO, sub_p))
    # tininess after rounding: k < emin, or k = emin and the precision-p
    # rounding R of the scaled value is below 1
    tn = klt if plant == "tininess_klt_only" else \
        b.sel(ONE, b.cmplt(R, ONE), klt)
    tinyu = b.sel(tn, ZERO, sub_p)
    b.probes.update(Ws=Ws)

    b.phase = "final"
    Y1 = b.mul(Wsel, S1)                              # exact
    FIN = b.mul(Y1, S2, rnd)                          # the one rounding
    if rnd in (RNE, RMM, RUP):
        ovf = b.cmpeq(FIN, INF)
    else:       # the directed-down attributes answer max_normal, not +inf
        ovf = b.cmpeq(b.mul(Y1, S2, RUP), INF)
    fl = b.sel(INXUNF, INX, tinyu)
    fl = b.sel(OVFINX, fl, ovf)
    if plant != "tiny_gate_off":
        mk = b.sel(ZERO, mk, tinyx)
    if plant != "mark_silenced":
        fl = b.ior(fl, b.sel(MARKW, ZERO, mk))
    b.probes.update(FIN=FIN, mk=mk)

    # ---- the specials, lowest priority first (the study's section 4) --------
    b.phase = "special"
    bits = FIN
    unfb = sf.round_pack(fmt, 0, 1, fmt.emin - mw - 2, rnd)[0]
    bits = b.sel(b.const("UNFB", unfb), bits, uns)
    fl = b.sel(INXUNF, fl, uns)
    ovfb = sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0]
    bits = b.sel(b.const("OVFB", ovfb), bits, ovs)
    fl = b.sel(OVFINX, fl, ovs)
    bits = b.sel(ONE, bits, iszero)
    infb = b.sel(ZERO, INF, neg)                      # exp(-inf) = +0
    fl = b.sel(ZERO, fl, iszero)
    bits = b.sel(infb, bits, isinf)
    fl = b.sel(ZERO, fl, isinf)
    bits = b.sel(QNAN, bits, isnan)
    fl = b.sel(b.sel(INVALID, ZERO, issnan), fl, isnan)
    return b.finish(bits, fl)


# ---- exp at fp32: three words where the bound needs them --------------------

def plan_exp32(fmt: FpFormat, G):
    """(K3, K2, D) for the triple-word exp (the study's 2.5): K3
    triple-word head steps, then K2 double-word steps, then a single-word
    tail to degree D of Y. Y's partial sum y_i enters V scaled by
    rho^(i+1), and a w-word step keeps about 24 w - 2 bits of relative
    accuracy, so y_i needs  need(i) = (p + G + 2) + log2(rho^(i+1) 2/(i+1)!)
    bits: K3 is the first i whose need fits two words less two bits, K3 + K2
    the first that fits one word less two; D the first degree whose
    truncation rho^(D+1)/(D+2)! is under 2^-(p+G+3). Exact rational
    arithmetic."""
    p = fmt.prec
    rho = _rho(fmt, _cushion(fmt))

    def need_within(i, bits):
        return rho ** (i + 1) * 2 / math.factorial(i + 1) <= \
            Fraction(2) ** (bits - (p + G + 2))
    D = 1
    while rho ** (D + 1) / math.factorial(D + 2) > \
            Fraction(1, 2 ** (p + G + 3)):
        D += 1
    K3 = 0
    while not need_within(K3, 2 * p - 2):
        K3 += 1
    K23 = K3
    while not need_within(K23, p - 2):
        K23 += 1
    return K3, K23 - K3, D


def _exp32_constants(fmt: FpFormat, G, K3, K2, D, shift, plant):
    """{role: bits} for the triple-word exp: the double word's, with ln2/8
    in five words (three of p - nb bits, so n times each is exact, then the
    nearest two to what is left), the table and the three-word head in
    three words, and the double-word steps' in two."""
    p = fmt.prec
    l2 = _ln2()
    L = l2 / N
    nb = _n_width(fmt)
    c = {}
    c["MAGIC"] = _enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    c["INVLN2N"] = _enc(fmt, N / l2)
    rest = L
    cw = []
    for _ in range(3):
        wd = _truncated(fmt, rest, p - nb)
        cw.append(wd)
        rest -= _dec(fmt, wd)
    l4 = _enc(fmt, rest)
    l5 = _enc(fmt, rest - _dec(fmt, l4))
    if plant == "c1_ulp":
        cw[0] += 1
    for i, wd in enumerate(cw):
        c[f"NL{i + 1}"] = sf.negate(fmt, wd)
    c["NL4"], c["L4"], c["NL5"] = sf.negate(fmt, l4), l4, sf.negate(fmt, l5)
    for j in range(N):
        for i, wd in enumerate(_words(fmt, _two_to_eighth(j), 3)):
            if plant == "table_entry" and (j, i) == (3, 0):
                wd += 1
            c[f"T{j}_{i}"] = wd
    lo_i = K3 + K2
    for i in range(lo_i, D + 1):
        c[f"Y{i}"] = _enc(fmt, _coefficient(i))
    for i in range(K3, lo_i):
        for k, wd in enumerate(_words(fmt, _coefficient(i), 2)):
            c[f"A{i}_{k}"] = wd
    for i in range(K3):
        for k, wd in enumerate(_words(fmt, _coefficient(i), 3)):
            c[f"B{i}_{k}"] = wd
    c["XOVF"], c["XUNF"] = _screens(fmt)
    if plant == "screen_ulp":
        c["XOVF"] -= 1
    c["TINYX"] = _pow2(fmt, -(p + 3))
    c["C0"] = _pow2(fmt, -3 if plant == "c0_wrong" else -4)
    c["BREL"] = _pow2(fmt, -(p + G) + shift - _bound_plant(plant))
    c["HALF"] = _pow2(fmt, -1)
    return c


def _round_to_odd_add(b: Build, a, c, one):
    """The sum a + c truncated, its last bit set where it was inexact:
    round-to-odd, for |a| >= |c| or either zero. Exact iff the Fast2Sum
    error c - ((a + c) - a) is zero."""
    s = b.add(a, c, RTZ)
    exact = b.cmpeq(b.sub(c, b.sub(s, a)), b.word(0, "ZERO"))
    return b.sel(s, b.ior(s, one), exact)


def _build_exp_tw(fmt: FpFormat, rnd: int, G, shift, plant):
    """exp at fp32, V as three words (the study's 2.5): the reduction's
    r = r0 + r1 + r2, the table's T = T0 + T1 + T2, the first Taylor terms
    and V itself in three words, the final rounding through round-to-odd of
    the low words."""
    p, W, mw = fmt.prec, fmt.width, fmt.man_w
    K3, K2, D = plan_exp32(fmt, G)
    c = _exp32_constants(fmt, G, K3, K2, D, shift, plant)
    b = Build(fmt, rnd, f"exp-{fmt.name}-{sf.RND_NAMES[rnd]}-tw")
    b.meta.update(fn="exp", G=G, K3=K3, K2=K2, D=D, N=N, shift=shift,
                  plant=plant, family="triple word")
    x = ("in", "a")
    w = b.word
    k_ = _words_common(b)
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    INF, QNAN, ABSM, QBIT = k_["INF"], k_["QNAN"], k_["ABSM"], k_["QBIT"]
    INX, INXUNF, OVFINX = k_["INX"], k_["INXUNF"], k_["OVFINX"]
    INVALID, MARKW = k_["INVALID"], k_["MARKW"]
    MAGIC = b.const("MAGIC", c["MAGIC"])
    MANW = ib(mw, "MANTISSA_WIDTH")
    two_sum, fast_two_sum = b.two_sum, b.fast_two_sum

    b.phase = "classify"
    ax = b.iand(x, ABSM)
    isnan = b.icmplt(INF, ax)
    issnan = b.sel(ZERO, isnan, b.iand(x, QBIT))
    isinf = b.cmpeq(ax, INF)
    iszero = b.icmplt(ax, INT1)
    neg = b.ishr(x, ib(W - 1, "SIGN_SHIFT"))
    uns = b.cmple(x, b.const("XUNF", c["XUNF"]))
    ovs = b.cmple(b.const("XOVF", c["XOVF"]), x)
    tinyx = b.icmplt(ax, b.const("TINYX", c["TINYX"]))

    # ---- reduce: r = x - n ln2/8 as three words, from five of ln2/8 --------
    b.phase = "reduce"
    t = b.fma(x, b.const("INVLN2N", c["INVLN2N"]), MAGIC)
    nf = b.sub(t, MAGIC)
    a = b.fma(nf, b.const("NL1", c["NL1"]), x)        # exact
    q2 = b.mul(nf, b.const("NL2", c["NL2"]))          # exact
    q3 = b.mul(nf, b.const("NL3", c["NL3"]))          # exact
    q4 = b.mul(nf, b.const("NL4", c["NL4"]))
    e4n = b.fma(nf, b.const("L4", c["L4"]), q4)       # -(the error of q4)
    q5 = b.mul(nf, b.const("NL5", c["NL5"]))
    s0, s1 = two_sum(a, q2)
    u0, u1 = two_sum(s1, q3)
    v0, v1 = two_sum(u0, q4)
    rest_ = b.add(b.sub(b.add(u1, v1), e4n), q5)
    r0, t1 = two_sum(s0, v0)
    r1, r2 = two_sum(t1, rest_)
    nr0 = b.neg(r0)
    b.probes.update(t=t, nf=nf, r0=r0, r1=r1, r2=r2)

    # ---- the table, three words ---------------------------------------------
    b.phase = "lookup"
    bitsel = [b.iand(t, ib(1 << i)) for i in range(T_BITS)]

    def tree(vals):
        level = list(vals)
        for bit in bitsel:
            level = [b.sel(level[2 * m + 1], level[2 * m], bit)
                     for m in range(len(level) // 2)]
        return level[0]
    T0, T1, T2 = (
        tree([b.const(f"T{j}_{i}", c[f"T{j}_{i}"]) for j in range(N)])
        for i in range(3))

    # ---- scale factors and the fixed grid (as the double word's) ------------
    b.phase = "scale"
    OFF = _scale_offset(fmt)
    half = (fmt.bias + OFF) // 2
    b.meta["OFF"] = OFF
    Ek = b.ishr(b.isub(t, ib(c["MAGIC"] - N * (fmt.bias + OFF), "KOFFSET")),
                ib(T_BITS))
    E1 = b.ishr(Ek, INT1)
    KB1 = ib(fmt.bias - half, "KBIAS1")
    S1 = b.ishl(b.iadd(E1, KB1), MANW)
    S2 = b.ishl(b.iadd(b.isub(Ek, E1), KB1), MANW)
    b.probes.update(Ek=Ek, S1=S1, S2=S2)
    KD = fmt.emin + 2 * fmt.bias + OFF
    sub_p = b.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF + 1, "K_EMIN_P1"))
    klt = b.icmplt(Ek, ib(fmt.emin + fmt.bias + OFF, "K_EMIN"))
    Cu = b.sel(b.ishl(b.isub(ib(KD, "K_KD"), Ek), MANW),
               b.const("C0", c["C0"]), klt)
    hu = None
    if rnd in (RNE, RMM):
        hu = b.ishl(b.isub(ib(KD - p, "K_KD_P"), Ek), MANW)
        b.probes["hu"] = hu
    b.probes.update(Cu=Cu, sub_p=sub_p, klt=klt)

    # ---- Y(r0): a single tail, double-word steps, triple-word steps ---------
    b.phase = "tail"
    y = b.const(f"Y{D}", c[f"Y{D}"])
    lo_i = K3 + K2
    for i in range(D - 1, lo_i - 1, -1):
        y = b.fma(y, r0, b.const(f"Y{i}", c[f"Y{i}"]))
    b.phase = "head2"
    yh, yl = y, None
    for i in range(lo_i - 1, K3 - 1, -1):
        CH = b.const(f"A{i}_0", c[f"A{i}_0"])
        CL = b.const(f"A{i}_1", c[f"A{i}_1"])
        pp = b.mul(yh, r0)
        ne = b.fma(yh, nr0, pp)
        nl = b.fma(yl, nr0, ne) if yl is not None else ne
        s, e = fast_two_sum(CH, pp)
        tt = b.sub(e, nl)
        yl = b.add(tt, CL) if c[f"A{i}_1"] else tt
        yh = s
    b.phase = "head3"
    y0, y1, y2 = yh, yl, None
    for i in range(K3 - 1, -1, -1):
        C0w = b.const(f"B{i}_0", c[f"B{i}_0"])
        C1w = b.const(f"B{i}_1", c[f"B{i}_1"])
        C2w = b.const(f"B{i}_2", c[f"B{i}_2"])
        c1, c2 = c[f"B{i}_1"], c[f"B{i}_2"]
        p0 = b.mul(y0, r0)
        ne0 = b.fma(y0, nr0, p0)                      # = -e0
        p1 = b.mul(y1, r0) if y1 is not None else None
        ne1 = b.fma(y1, nr0, p1) if y1 is not None else None
        p2 = b.mul(y2, r0) if y2 is not None else None
        s0_, t0 = fast_two_sum(C0w, p0)               # level 0
        lv1 = [t0] + ([C1w] if c1 else []) + ([p1] if p1 is not None else [])
        acc, errs = lv1[0], []
        for term in lv1[1:]:
            acc, er = two_sum(acc, term)
            errs.append(er)
        acc, er = two_sum(acc, b.neg(ne0))
        errs.append(er)
        lv2 = errs + ([C2w] if c2 else [])
        s2_ = lv2[0]
        for term in lv2[1:]:
            s2_ = b.add(s2_, term)
        if ne1 is not None:
            s2_ = b.sub(s2_, ne1)
        if p2 is not None:
            s2_ = b.add(s2_, p2)
        a0, a1 = fast_two_sum(s0_, acc)
        a1, a2 = fast_two_sum(a1, s2_)
        y0, y1, y2 = a0, a1, a2

    # ---- Z = r Y with r = r0 + r1 + r2; e^(r0) for the low terms ------------
    b.probes.update(y0=y0, y1=y1, y2=y2, T0=T0, T1=T1, T2=T2)
    b.phase = "Z"
    z0 = b.mul(y0, r0)
    nze0 = b.fma(y0, nr0, z0)                         # -e
    z1a = b.mul(y1, r0)
    nze1 = b.fma(y1, nr0, z1a)
    # e^(r0) = 1 + Z(r0) as two words: r1 (~2^-28) needs it to 2^-44
    ep0, ep1 = fast_two_sum(ONE, z0)
    z1b = b.mul(ep0, r1)
    nze2 = b.fma(ep0, b.neg(r1), z1b)
    zz, e_a = two_sum(z1a, z1b)
    zz, e_b = two_sum(zz, b.neg(nze0))
    lvl2 = b.sub(b.sub(b.add(b.add(e_a, e_b), b.mul(y2, r0)), nze1), nze2)
    # e^(r0) to 2^-48: 1 + z0 is short by Z(r0)'s second word (z1a + e0,
    # about 2^-28.5), which times r1 (~2^-28) is 2^-57
    ep1 = b.add(ep1, b.sub(z1a, nze0))
    lvl2 = b.fma(ep1, r1, lvl2)
    lvl2 = b.fma(ep0, r2, lvl2)
    # e^(r1 + r2) - 1 = r1 + r2 + r1^2/2 + ...: at p = 24, r1 ~ 2^-28 and
    # r1^2/2 ~ 2^-57 is inside the bound's range (at fp64 it is 2^-116),
    # and it is e^(r0) r1^2/2
    if plant != "square_term_dropped":
        half_r1 = b.mul(b.mul(r1, b.const("HALF", c["HALF"])), ep0)
        lvl2 = b.fma(half_r1, r1, lvl2)
    Z0, Z1 = fast_two_sum(z0, zz)
    Z1, Z2 = fast_two_sum(Z1, lvl2)
    b.probes.update(Z0=Z0, Z1=Z1, Z2=Z2, ep0=ep0, ep1=ep1, lvl2=lvl2,
                    zz=zz, z0=z0)

    # ---- V = T (1 + Z), three words -----------------------------------------
    b.phase = "recon"
    P0 = b.mul(T0, Z0)
    nP0 = b.fma(T0, b.neg(Z0), P0)                    # -(err)
    P1 = b.mul(T0, Z1)
    nP1 = b.fma(T0, b.neg(Z1), P1)
    Q1 = b.mul(T1, Z0)
    nQ1 = b.fma(T1, b.neg(Z0), Q1)
    S0, s1 = fast_two_sum(T0, P0)
    m, m1 = two_sum(s1, T1)
    m, m2 = two_sum(m, b.neg(nP0))
    m, m3 = two_sum(m, P1)
    m, m4 = two_sum(m, Q1)
    l2_ = b.add(b.add(b.add(m1, m2), b.add(m3, m4)), T2)
    l2_ = b.sub(b.sub(l2_, nP1), nQ1)
    l2_ = b.fma(T0, Z2, l2_)
    l2_ = b.fma(T1, Z1, l2_)
    l2_ = b.fma(T2, Z0, l2_)
    V0, V1 = fast_two_sum(S0, m)
    V1, V2 = fast_two_sum(V1, l2_)
    V0, V1 = fast_two_sum(V0, V1)
    b.probes.update(V0=V0, V1=V1, V2=V2)

    # ---- final: R = rnd(V0 + RO(V1 + V2)); the test on V1 + V2 -+ Bv --------
    b.phase = "final"
    lo = _round_to_odd_add(b, V1, V2, INT1)
    R = b.add(V0, lo, rnd)
    Bv = b.mul(V0, b.const("BREL", c["BREL"]))
    lo_dn = _round_to_odd_add(b, V1, b.sub(V2, Bv, RDN), INT1)
    lo_up = _round_to_odd_add(b, V1, b.add(V2, Bv, RUP), INT1)
    R1 = b.add(V0, lo_dn, rnd)
    R2 = b.add(V0, lo_up, rnd)
    mk = b.ixor(R1, R2)
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv, Vh=V0)
    # the fixed grid: Z0' = RN(Cu + V0); the rest V0 - (Z0' - Cu) + V1 + V2
    b.phase = "fixed-grid"
    Zc = b.add(Cu, V0)
    W0 = b.sub(Zc, Cu)
    zr = b.sub(V0, W0)
    t_ = b.add(zr, lo) if plant == "odd_dropped" else \
        _round_to_odd_add(b, zr, lo, INT1)
    Ws = b.sub(b.add(Zc, t_, rnd), Cu)
    c1_ = b.cmpeq(b.fabs(zr), hu) if hu is not None else b.cmpeq(zr, ZERO)
    smallo = b.cmple(b.fabs(lo), Bv)
    msub = b.sel(smallo, ZERO, c1_)
    Wsel = b.sel(Ws, R, sub_p)
    mk = b.sel(ONE, mk, b.sel(msub, ZERO, sub_p))
    tn = klt if plant == "tininess_klt_only" else \
        b.sel(ONE, b.cmplt(R, ONE), klt)
    tinyu = b.sel(tn, ZERO, sub_p)
    b.phase = "final"
    Y1 = b.mul(Wsel, S1)
    FIN = b.mul(Y1, S2, rnd)
    if rnd in (RNE, RMM, RUP):
        ovf = b.cmpeq(FIN, INF)
    else:
        ovf = b.cmpeq(b.mul(Y1, S2, RUP), INF)
    fl = b.sel(INXUNF, INX, tinyu)
    fl = b.sel(OVFINX, fl, ovf)
    if plant != "tiny_gate_off":
        mk = b.sel(ZERO, mk, tinyx)
    if plant != "mark_silenced":
        fl = b.ior(fl, b.sel(MARKW, ZERO, mk))
    b.probes.update(FIN=FIN, mk=mk)

    b.phase = "special"
    bits = FIN
    unfb = sf.round_pack(fmt, 0, 1, fmt.emin - mw - 2, rnd)[0]
    bits = b.sel(b.const("UNFB", unfb), bits, uns)
    fl = b.sel(INXUNF, fl, uns)
    ovfb = sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0]
    bits = b.sel(b.const("OVFB", ovfb), bits, ovs)
    fl = b.sel(OVFINX, fl, ovs)
    bits = b.sel(ONE, bits, iszero)
    fl = b.sel(ZERO, fl, iszero)
    bits = b.sel(b.sel(ZERO, INF, neg), bits, isinf)
    fl = b.sel(ZERO, fl, isinf)
    bits = b.sel(QNAN, bits, isnan)
    fl = b.sel(b.sel(INVALID, ZERO, issnan), fl, isnan)
    return b.finish(bits, fl)


def build_exp(fmt: FpFormat, rnd: int, *, guard=None, bound_shift=0,
              plant=None) -> Build:
    """exp at `fmt` under the program's attribute `rnd`, instrumented
    (Build.fragment() is the routine). `guard` overrides the guard G
    (GUARD's, by default); `bound_shift` makes the in-lane bound 2^shift
    times as wide, so that marks are common enough to count (the mark-rate
    law, the study's 3.4); `plant` builds one fault of PLANTS."""
    if fmt not in FORMATS:
        raise ValueError(f"{fmt!r} is not one of the four formats")
    if rnd not in sf.RND_NAMES:
        raise ValueError(f"rounding attribute {rnd!r} is not one of the five")
    if plant is not None and plant not in PLANTS:
        raise ValueError(f"unknown plant {plant!r}: {', '.join(PLANTS)}")
    family = "tw" if fmt.name == "fp32" else "dw"
    if plant is not None and family not in PLANTS[plant][0].split():
        raise ValueError(f"plant {plant!r} does not apply to the "
                         f"{'triple' if family == 'tw' else 'double'}-word "
                         f"fragments ({fmt.name})")
    G = GUARD[fmt.name] if guard is None else guard
    if family == "tw":
        return _build_exp_tw(fmt, rnd, G, bound_shift, plant)
    return _build_exp_dw(fmt, rnd, G, bound_shift, plant)


# ---- what is proved of every fragment ---------------------------------------
#
# C4's routines.invariants() holds a division's and a root's fragments; the
# study (section 6, question 12) found four ways it fails these, and Logan's
# answer widens them. routines.py is not edited: its invariants stay as they
# are for division and root, and this module holds ITS fragments to the
# widened form. The later cftc parcel moves the widened form into routines.py
# and into cftc's internal check.

# The values a flag word can take: C4's six, and inexact, overflow with
# inexact and underflow with inexact each with the mark. Never bits [6:5].
FLAG_WORDS = routines.FLAG_WORDS | frozenset(
    w | MARK for w in (sf.FLAG_INEXACT,
                       sf.FLAG_OVERFLOW | sf.FLAG_INEXACT,
                       sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT))

# The most values a fragment may keep live at once, by format. The double
# word's exp keeps 22 (rtz, rdn, rup) or 23 (rne, rmm) live, at every one
# of fp64, fp128 and fp256: its classification, its scale words and its
# reduction's words are all computed early and read late, and 23 is the
# cap because that is what the design measures, so a growth is a change to
# look at. It leaves NREG - 23 = 9 of seq.py's 32 registers for the
# program's own values across a call, which the compiler's allocator spills
# when it must (C4's allocator does so around any routine). fp32's
# triple-word exp keeps 33 or 34 live (MEASURED), which no allocation of 32
# registers holds in this order: it is built, held to everything else and
# REPORTED, not capped (None), and run by evaluate(), not by seq.py.
LIVE_CAP = {"fp32": None, "fp64": 23, "fp128": 23, "fp256": 23}
_BY_FORMAT = object()            # invariants()'s default cap: LIVE_CAP's


def flag_words(f):
    """The values the flag word can take, by a walk of its definition: a
    word is its bits, a SELECT the union of its arms, an IAND with the word
    0 is 0, an IOR the set of the pairwise ORs of its operands'; anything
    else is unknown (None). C4's walk (routines.flag_words) has no IOR
    rule, so it cannot see through the instruction that ORs the mark in."""
    sets = {}

    def val(s):
        if s[0] == "w":
            return {f.words[s[1]]}
        if s[0] == "v":
            return sets.get(s[1])
        return None
    for i, (op, _r, srcs) in enumerate(f.body):
        if op == sf.OP_SELECT:
            a, b = val(srcs[0]), val(srcs[1])
            sets[i] = a | b if a is not None and b is not None else None
        elif op == sf.OP_IAND and any(val(s) == {0} for s in srcs):
            sets[i] = {0}
        elif op == sf.OP_IOR:
            a, b = val(srcs[0]), val(srcs[1])
            sets[i] = ({u | v for u in a for v in b}
                       if a is not None and b is not None else None)
        else:
            sets[i] = None
    return sets.get(f.flags[1]) if f.flags[0] == "v" else val(f.flags)


def invariants(f, live_cap=_BY_FORMAT):
    """[str]: what does not hold of the fragment, empty when all does:

      * the flag word's values, by flag_words(), within FLAG_WORDS: never
        bits [6:5], the mark only with inexact (an IOR rule in the walk);
      * at most `live_cap` values live at once (LIVE_CAP's, by default;
        None for no cap: fp32's count is reported, not capped);
      * every instruction reading a word or an internal value, so none can
        be a language node's (cftc/inline.py's argument);
      * nothing left to simplify (routines.simplify), once specialised;
      * the attributes the routine's own: RNE, RTZ, RDN, RUP and the
        PROGRAM's (f.rnd), and none where an opcode does not round;
      * well formed: values read only after they are defined, the words
        named exist and are encodings at the format, each opcode takes its
        operands, the result and the flag word are values.
    C4's invariants admit RNE and RTZ only, cap the live count at 16, and
    cannot see an IOR, which is how the study measured them failing."""
    out = []
    fmt = f.fmt
    if live_cap is _BY_FORMAT:
        live_cap = LIVE_CAP.get(fmt.name)
    for name, bits in f.words.items():
        if not 0 <= bits < 1 << fmt.width:
            out.append(f"word {name} is not an encoding at {fmt.name}")
    n = len(f.body)
    for i, (op, r, srcs) in enumerate(f.body):
        fields = asm.OP_FIELDS.get(op)
        if fields is None or len(srcs) != len(fields):
            out.append(f"instruction {i}: opcode {op} with {len(srcs)} "
                       f"operands is not an ALU instruction")
        for s in srcs:
            if s[0] == "v" and not 0 <= s[1] < i:
                out.append(f"instruction {i} reads value {s[1]} before it "
                           f"is defined")
            elif s[0] == "w" and s[1] not in f.words:
                out.append(f"instruction {i} reads the word {s[1]!r}, "
                           f"which the fragment does not hold")
            elif s[0] == "in" and s[1] not in f.inputs:
                out.append(f"instruction {i} reads the input {s[1]!r}")
    for what, ref in (("result", f.result), ("flag word", f.flags)):
        if ref[0] != "v" or not 0 <= ref[1] < n:
            out.append(f"the {what} {ref} is not a value of the body")
    if out:
        return out              # the checks below walk a well-formed body
    fw = flag_words(f)
    if fw is None or not fw <= FLAG_WORDS:
        out.append(f"the flag word's values {fw} are not within "
                   f"{sorted(FLAG_WORDS)}")
    live = f.live_max()
    if live_cap is not None and live > live_cap:
        out.append(f"{live} values live at once, past {live_cap}")
    own = (RNE, RTZ, RDN, RUP, f.rnd)
    for i, (op, r, srcs) in enumerate(f.body):
        if not any(s[0] in ("w", "v") for s in srcs):
            out.append(f"instruction {i} reads only the routine's inputs")
        if f.stage == "specialised" and routines.simplify(
                op, srcs, lambda s: f.words[s[1]] if s[0] == "w" else None,
                fmt.sign_mask) is not None:
            out.append(f"instruction {i} simplifies further")
        if (op in ROUNDED) != (r is not None) or \
                (r is not None and r not in own):
            out.append(f"instruction {i}'s attribute {r} is not the "
                       f"routine's own")
    return out


# ---- the interface ----------------------------------------------------------

_CACHE = {}


def fragment(name, fmt: FpFormat, rnd: int):
    """The specialised routines.Fragment of `name` at `fmt` under the
    program's attribute `rnd`, held to invariants(): as routines.fragment()
    returns a division's. `name` is one of NAMES; any other is refused by
    name. The fragment is built once and shared."""
    if name not in NAMES:
        raise ValueError(f"{name!r} is not a math-library routine built "
                         f"so far: {', '.join(NAMES)}")
    key = (name, fmt, rnd)
    if key not in _CACHE:
        f = build_exp(fmt, rnd).fragment()
        bad = invariants(f)
        if bad:
            raise AssertionError(f"{name} at {fmt.name}, rnd {rnd}: "
                                 f"{'; '.join(bad)}")
        _CACHE[key] = f
    return _CACHE[key]


def evaluate(f, x):
    """(result bits, flag word) of the fragment `f` on one lane whose
    argument is the encoding `x`: f's body run instruction by instruction
    through softfloat.compute, as seq.py's ALU computes (the operand fields
    the opcode reads, the instruction's own attribute). The flag word is
    the value the compiled routine RAISEs: bits [4:0] the operation's IEEE
    flags, bit 7 the mark."""
    if not 0 <= x < 1 << f.fmt.width:
        raise ValueError(f"{x:#x} is not an encoding at {f.fmt.name}")
    vals = _values(f.fmt, f.body, f.words, x)
    get = _getter(vals, f.words, x)
    return get(f.result), get(f.flags)


# ---- the check of the constants ---------------------------------------------
#
# A constant here has been derived by the generator from mpmath at 3,000 bits
# and rounded once. This section derives each again, in integer arithmetic
# that shares nothing with the generator or with mpmath, and compares - not
# by regenerating and comparing the generator with itself, which a defect in
# the generator would survive, but by asking, of the bits the BUILT fragment
# holds, whether they are what the rounding rule gives for every value of an
# interval that encloses the true number:
#
#   ln 2          2 atanh(1/3) = 2 sum 1/((2k+1) 3^(2k+1)), floors of 2^3200
#                 over each term, the loss counted: width 2^-3190
#   2^(j/8)       the integer 8th root of 2^j 2^(8 1700), floor: width 2^-1700,
#                 exact (a degenerate interval) at j = 0
#   1/(i+1)!      exact
#
# and the rules - nearest, up, down, truncated to n bits - are asked of the
# fragment's words through softfloat's neighbours (next_up, next_down) and
# exact fractions, not through the generator's _enc. An enclosure that
# straddles a rounding boundary is REFUSED as undecidable, never passed.
#
# The words that are not rounded reals - the scale offsets, the fixed grid's
# C and u/2 - are checked where they act: lanes at the ends and the middle of
# the range, through the fragment's own instructions, against 2^k exactly.

def _iroot(n, k):
    """floor(n^(1/k)), integer Newton iteration."""
    if n < 2:
        return n
    x = 1 << ((n.bit_length() + k - 1) // k)
    while True:
        y = ((k - 1) * x + n // x ** (k - 1)) // k
        if y >= x:
            return x
        x = y


@functools.lru_cache(maxsize=None)
def _check_ln2():
    """(lo, hi): ln 2 enclosed, from the atanh series in integers."""
    bits = 3200
    one = 1 << bits
    total, k, pw = 0, 0, 3
    while True:
        t = one // ((2 * k + 1) * pw)
        if t == 0:
            break
        total += t
        k += 1
        pw *= 9
    return Fraction(2 * total, one), Fraction(2 * (total + k + 1), one)


@functools.lru_cache(maxsize=None)
def _check_two_to_eighth(j):
    """(lo, hi): 2^(j/8) enclosed, from the integer 8th root; degenerate at
    j = 0."""
    bits = 1700
    target = 1 << (j + 8 * bits)
    r = _iroot(target, N)
    if r ** N == target:
        return Fraction(r, 1 << bits), Fraction(r, 1 << bits)
    return Fraction(r, 1 << bits), Fraction(r + 1, 1 << bits)


def _why_not(fmt, rule, bits, lo, hi, nbits=None):
    """None where `bits` is what `rule` gives for EVERY value of [lo, hi],
    else why not. rules: "rn" nearest, "ru" up, "rd" down, "trunc" toward
    zero to `nbits` significant bits (positive values), "exact"."""
    try:
        w = _dec(fmt, bits)
        up = _dec(fmt, sf.next_up(fmt, bits)[0])
        dn = _dec(fmt, sf.next_down(fmt, bits)[0])
    except ValueError:
        return f"{bits:#x} is not a finite encoding"
    if rule == "exact":
        ok = lo == hi == w
    elif rule == "rn":
        ok = (w + dn) / 2 < lo and hi < (w + up) / 2
    elif rule == "ru":
        ok = dn < lo and hi <= w
    elif rule == "rd":
        ok = w <= lo and hi < up
    elif rule == "trunc":
        u = sf.unpack(fmt, bits)
        sig = u.m.bit_length() - ((u.m & -u.m).bit_length() - 1)
        e = u.m.bit_length() - 1 + u.e
        ok = (sig <= nbits and w <= lo
              and hi < w + Fraction(2) ** (e - nbits + 1))
    else:
        raise ValueError(rule)
    if ok:
        return None
    return (f"{bits:#x} = {float(w):.17g} is not the {rule} rounding of "
            f"[{float(lo):.17g}, {float(hi):.17g}]")


def _check_scale(b: Build, findings):
    """The scale offsets, the fixed grid's words and the table's wiring,
    where they act: lanes x = n ln2/8 over the range of k, each run through
    the unpruned body, its probes against exact values. -> lanes run."""
    fmt, p, mw = b.fmt, b.fmt.prec, b.fmt.man_w
    OFF = b.meta["OFF"]
    ks = [fmt.emin - p - 2, fmt.emin - 2, fmt.emin - 1, fmt.emin,
          fmt.emin + 1, fmt.emin + p, -2, -1, 0, 1, 2, fmt.emax - 1,
          fmt.emax, fmt.emax + 1]
    ns = [8 * k + j for k in ks for j in (0, 3, 5, 7)]
    ns += [8 * k + 1 for k in range(-9, 10, 3)]
    l2 = _check_ln2()[0]
    tw = fmt.name == "fp32"
    ran = 0
    for n in ns:
        x = _enc(fmt, Fraction(n) * l2 / N)
        want = ("nf", "Ek", "S1", "S2", "sub_p", "klt", "Cu", "hu",
                "T0", "T1", "T2", "Th", "Tl")
        _res, _fl, pr = b.run(x, want)
        got_n = _dec(fmt, pr["nf"])
        if got_n.denominator != 1 or abs(got_n - n) > 1:
            findings.append(f"{fmt.name} {sf.RND_NAMES[b.rnd]}: n = {n} was "
                            f"reduced to {got_n}")
            continue
        n_ = int(got_n)
        k, j = n_ // N, n_ % N
        ran += 1
        where = f"{fmt.name} {sf.RND_NAMES[b.rnd]} n = {n_} (k = {k})"
        if pr["Ek"] != k + fmt.bias + OFF:
            findings.append(f"{where}: Ek = {pr['Ek']}, want "
                            f"{k + fmt.bias + OFF}")
        for nm, kk in (("S1", k // 2), ("S2", k - k // 2)):
            u = sf.unpack(fmt, pr[nm])
            if (u.kind != sf.NORM or u.sign or u.m != 1 << mw
                    or u.e + mw != kk):
                findings.append(f"{where}: {nm} = {pr[nm]:#x} is not 2^{kk}")
        for nm, truth in (("sub_p", k <= fmt.emin), ("klt", k < fmt.emin)):
            if (pr[nm] == sf.one_bits(fmt)) != truth or pr[nm] not in (
                    0, sf.one_bits(fmt)):
                findings.append(f"{where}: {nm} = {pr[nm]:#x}, want {truth}")
        if k <= fmt.emin:
            cu = Fraction(2) ** (fmt.emin - k) if k < fmt.emin \
                else Fraction(1, 16)
            if _dec(fmt, pr["Cu"]) != cu:
                findings.append(f"{where}: Cu is not {cu}")
            if "hu" in pr and _dec(fmt, pr["hu"]) != \
                    Fraction(2) ** (fmt.emin - p - k):
                findings.append(f"{where}: u/2 is not 2^{fmt.emin - p - k}")
        if tw:
            for i in range(3):
                if pr[f"T{i}"] != b.words[b.roles[f"T{j}_{i}"][1]]:
                    findings.append(f"{where}: the table's word {i} is not "
                                    f"T_{j}'s")
        else:
            for nm, role in (("Th", f"TH{j}"), ("Tl", f"TL{j}")):
                if pr[nm] != b.words[b.roles[role][1]]:
                    findings.append(f"{where}: the table read for j = {j} "
                                    f"is not {role}")
    return ran


def _check_plan(fmt, family, G, l2hi):
    """The plan again, from the independent ln 2: (K, D) or (K3, K2, D),
    the smallest satisfying the study's conditions (plan_exp, plan_exp32)."""
    p = fmt.prec
    rho = (Fraction(1, 2) + Fraction(1, 2 ** _cushion(fmt))) * l2hi / N
    fact = math.factorial
    if family == "triple word":
        def fits(i, bits):
            return rho ** (i + 1) * 2 / fact(i + 1) <= \
                Fraction(2) ** (bits - (p + G + 2))
        D = next(d for d in range(1, 150)
                 if rho ** (d + 1) / fact(d + 2) <=
                 Fraction(1, 2 ** (p + G + 3)))
        K3 = next(i for i in range(60) if fits(i, 2 * p - 2))
        K23 = next(i for i in range(K3, 80) if fits(i, p - 2))
        return (K3, K23 - K3, D)
    u = Fraction(1, 2 ** p)
    target = Fraction(1, 2 ** (p + G + 2))

    def tail(K):
        return 2 * u * rho ** (K + 1) / fact(K + 1)

    def trunc(D):
        return rho ** (D + 2) / fact(D + 2) * (1 + rho)
    K = next(k for k in range(1, 60) if tail(k) <= target / 2)
    D = next(d for d in range(K, 150)
             if tail(K) + trunc(d) + 10 * u * u <= target)
    return (K, D)


def _check_build(b: Build, findings):
    """Every derived constant of one built exp, against its independent
    derivation, and the scale words where they act. -> (constants checked,
    lanes run)."""
    fmt, p = b.fmt, b.fmt.prec
    tag = f"{fmt.name} {sf.RND_NAMES[b.rnd]}"
    tw = b.meta["family"] == "triple word"
    G = b.meta["G"]
    seen = set()
    count = [0]

    def verify(role, rule, lo, hi, nbits=None, negated=False):
        """Check the constant `role`, as held (negated: the held word is
        the constant's negation). -> its value, for the next word."""
        seen.add(role)
        if role not in b.roles:
            findings.append(f"{tag}: the fragment has no constant {role}")
            return Fraction(0)
        count[0] += 1
        bits = b.words[b.roles[role][1]]
        if negated:
            bits = sf.negate(fmt, bits)
        msg = _why_not(fmt, rule, bits, lo, hi, nbits)
        if msg:
            findings.append(f"{tag} {role}: {msg}")
            return Fraction(0)
        return _dec(fmt, bits)

    def point(role, value, negated=False):
        return verify(role, "exact", Fraction(value), Fraction(value),
                      negated=negated)

    l2lo, l2hi = _check_ln2()
    nb = _n_width(fmt)
    plan = _check_plan(fmt, b.meta["family"], G, l2hi)
    held_plan = ((b.meta["K3"], b.meta["K2"], b.meta["D"]) if tw
                 else (b.meta["K"], b.meta["D"]))
    if plan != held_plan:
        findings.append(f"{tag}: the plan {held_plan} is not the re-derived "
                        f"{plan}")
    point("MAGIC", Fraction(3, 2) * 2 ** (p - 1))
    verify("INVLN2N", "rn", Fraction(N) / l2hi, Fraction(N) / l2lo)
    # Cody-Waite: each word against what the ones before leave of ln2/8
    lo, hi = l2lo / N, l2hi / N
    if tw:
        for role in ("NL1", "NL2", "NL3"):
            w = verify(role, "trunc", lo, hi, nbits=p - nb, negated=True)
            lo, hi = lo - w, hi - w
        l4 = verify("L4", "rn", lo, hi)
        point("NL4", l4, negated=True)
        verify("NL5", "rn", lo - l4, hi - l4, negated=True)
    else:
        c1 = verify("NC1", "trunc", lo, hi, nbits=p - nb, negated=True)
        lo, hi = lo - c1, hi - c1
        c2 = verify("C2", "rn", lo, hi)
        point("NC2", c2, negated=True)
        verify("C3", "rn", lo - c2, hi - c2)
    # the table: 2^(j/8), each word the nearest to what the ones before leave
    nwords = 3 if tw else 2
    for j in range(N):
        vlo, vhi = _check_two_to_eighth(j)
        for i in range(nwords):
            role = f"T{j}_{i}" if tw else ("TH" if i == 0 else "TL") + str(j)
            w = verify(role, "rn", vlo, vhi)
            vlo, vhi = vlo - w, vhi - w
    # the Taylor coefficients 1/(i+1)!: exact, then rounded word by word
    if tw:
        K3, K2, D = held_plan
        names = {i: [f"Y{i}"] for i in range(K3 + K2, D + 1)}
        names.update({i: [f"A{i}_{k}" for k in range(2)]
                      for i in range(K3, K3 + K2)})
        names.update({i: [f"B{i}_{k}" for k in range(3)] for i in range(K3)})
    else:
        K, D = held_plan
        names = {i: [f"Y{i}"] for i in range(K, D + 1)}
        names.update({i: [f"CH{i}", f"CL{i}"] for i in range(K)})
    for i, roles in names.items():
        left = Fraction(1, math.factorial(i + 1))
        for role in roles:
            left -= verify(role, "rn", left, left)
    # the screens, by the rounding direction that makes each one safe
    verify("XOVF", "ru", (fmt.emax + 1) * l2lo, (fmt.emax + 1) * l2hi)
    verify("XUNF", "rd", (fmt.emin - p) * l2hi, (fmt.emin - p) * l2lo)
    point("TINYX", Fraction(2) ** -(p + 3))
    point("C0", Fraction(1, 16))
    point("BREL", Fraction(2) ** -(p + G) * 2 ** b.meta["shift"])
    if tw:
        point("HALF", Fraction(1, 2))
    # the answers of the two screens under the program's attribute (754 7.4):
    # a quarter of the smallest subnormal, rounded; a number past the largest
    point("UNFB", _dec(fmt, sf.min_subnormal_bits(fmt)) if b.rnd == RUP
          else 0)
    seen.add("OVFB")
    want_ovf = (sf.inf_bits(fmt) if b.rnd in (RNE, RMM, RUP)
                else sf.max_normal_bits(fmt))
    count[0] += 1
    if b.words[b.roles["OVFB"][1]] != want_ovf:
        findings.append(f"{tag} OVFB: {b.words[b.roles['OVFB'][1]]:#x} is not "
                        f"the overflow result {want_ovf:#x} under "
                        f"{sf.RND_NAMES[b.rnd]}")
    unchecked = sorted(set(b.roles) - seen)
    if unchecked:
        findings.append(f"{tag}: derived but not checked: {unchecked}")
    return count[0], _check_scale(b, findings)


def check_constants(builder=None, formats=FORMATS, attrs=sf.RND_MODES):
    """(lines, findings): re-derive every derived constant of every built
    fragment (the section's comment above) and run the scale words. `lines`
    say what was checked; `findings` are the differences, empty when none.
    `builder(fmt, rnd)` is build_exp, or a faulted one for a test."""
    builder = builder or build_exp
    lines, findings = [], []
    for fmt in formats:
        n_const = n_lanes = 0
        for rnd in attrs:
            b = builder(fmt, rnd)
            c, ln = _check_build(b, findings)
            n_const += c
            n_lanes += ln
        meta = b.meta
        plan = ((meta["K3"], meta["K2"], meta["D"]) if "K3" in meta
                else (meta["K"], meta["D"]))
        lines.append(
            f"{fmt.name}: G = {meta['G']}, plan {plan}: {n_const} derived "
            f"constants in {len(attrs)} fragments, each the rounding its "
            f"rule gives for every value of an enclosure of the true "
            f"number; {n_lanes} lanes of the scale, fixed-grid and table "
            f"words")
    return lines, findings


# ---- the module as a program ------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m cft_golden.mathlib",
        description="The math library's golden generator: exp's fragments.")
    ap.add_argument("--check", action="store_true",
                    help="re-derive every constant the built fragments "
                         "hold, in integer arithmetic of its own, and exit "
                         "1 on a difference")
    args = ap.parse_args(argv)
    if args.check:
        lines, findings = check_constants(formats=FORMATS)
        for ln in lines:
            print(ln)
        for fd in findings:
            print("DIFFERENCE:", fd)
        print(f"mathlib --check: {len(lines)} formats, "
              f"{len(findings)} differences")
        return 1 if findings else 0
    print(f"{'routine':8s} {'format':6s} {'rnd':4s} {'insns':>6s} "
          f"{'words':>6s} {'live':>5s}  cap")
    for fmt in FORMATS:
        for rnd in sf.RND_MODES:
            f = fragment("exp", fmt, rnd)
            print(f"{'exp':8s} {fmt.name:6s} {sf.RND_NAMES[rnd]:4s} "
                  f"{len(f):6d} {len(f.words):6d} {f.live_max():5d}  "
                  f"{LIVE_CAP[fmt.name]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
