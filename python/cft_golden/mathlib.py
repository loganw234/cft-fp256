# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The math library's golden generator (step 6, M1's build, parcels E1, MB1
and MB2): exp, exp2, expm1, log, log2 and log1p, as fragments of a tile
program.

transcend.py DEFINES exp, expm1, exp2, log, log1p and log2: bits and flags,
correctly rounded, for every argument. A tile has none of them as an
instruction. M1 builds each as a ROUTINE - a fragment of existing
instructions, in C4's shape (routines.Fragment), that the compiler inlines
where a node stands, as it inlines division and square root. This module
builds the fragments. They are built, not read from a program as C4's are:
the construction below IS the design of docs/studies/M1-exp-log.md, whose
model (docs/studies/m1/) this file ports into the tree; nothing here
imports it. It builds exp (parcel E1), exp2 and expm1 (parcel MB1), and log,
log2 and log1p (parcel MB2): all six.

The interface, and only this, is what a battery may rely on:

  fragment(name, fmt, rnd)  the specialised routines.Fragment of `name`
                            (one of NAMES) at fmt (FP32, FP64, FP128 or
                            FP256) under the program's attribute rnd, held to
                            invariants() - the widened form of C4's - as
                            routines.fragment() holds a division
  evaluate(f, x)            one lane: the argument's bits x run through
                            f's body, instruction by instruction, with
                            softfloat.compute as seq.py's ALU computes -
                            the pair (result bits, flag word)

What a fragment is (the study's sections 2.1, 2.2, 3.1 and 4). The exp
family's three share one shape and differ in the reduction, the
reconstruction and the specials:

  classify   NaN, signalling, infinity, zero, sign, the screens, the tiny
             gate: conditions the specials select on
  reduce     exp, expm1: n = round(x 8/ln2) by the magic-number FMA;
             r = x - n ln2/8 by Cody-Waite, |r| <= rho: at fp64, fp128 and
             fp256 ln2/8 in three words and r a double word; at fp32 ln2/8
             in five words and r in three (2.5)
             exp2: n = round(8x), exact by the same FMA; r' = x - n/8,
             exact; r = r' ln2 by TwoProd of r' against ln2's words - two,
             and r a double word, at fp64 to fp256; three, and r in three,
             at fp32 (this parcel's design: the study models only exp there)
  lookup     T_j = 2^(j/8), j = n mod 8, two words (three at fp32), a
             SELECT tree over j's three bits - bank words only, no scratch
             slot
  scale      2^k1 and 2^k2, k = floor(n/8) and k1 = floor(k/2), by integer
             arithmetic on the encoding of the magic-number sum
  tail,head  Y(r) = (e^r - 1)/r by Taylor: a single-word Horner tail
             (FMA) down to degree K, then K double-word steps (TwoProd by
             FMA, Fast2Sum where the exponents are ordered); expm1 plans one
             factor rho fewer, its n = 0 lanes being bounded relative to Z
  Z, recon   Z = e^r - 1 as a double word; V = T (1 + Z) = V_h + V_l; expm1's
             V' = T (1 + Z) - 2^-k, T_h - 2^-k by TwoSum and 2^-k taken as 0
             beyond k = p + G + 2
  final      R = rnd(V_h + V_l); the IN-LANE TEST: both ends of V's error
             interval, V_l - Bv rounded down and V_l + Bv rounded up with
             Bv = 2^-(p+G) |V_h|, are added to V_h under rnd; a lane where
             the two roundings differ is not decided and is MARKED
  fixed grid exp, exp2: a result that may be subnormal is rounded once on its
             own grid (k <= emin), its own test beside the main one; expm1's
             result is never subnormal off its tiny path
  specials   NaN, +-inf, +-0, the screens, in the order of the study's
             section 4, selected over the main path, lowest priority first:
             exp2's integer x exact with no flag, down to 2^(emin - man_w),
             and its tie at emin - p (half the smallest subnormal) answered
             by roundTiesToAway under rmm as transcend.exp2 has since profile
             3 (the study's model gave +0); expm1's tiny path fma(x, x, x)
             for |x| < 2^-(p+2) with its underflow cases, and -1, or
             -(1 - 2^-p) under rtz and rup, for x <= -(p+2) ln2

The log family (the study's 2.3 and 4; parcel MB2) has the same parts and is
not scaled, a result being always normal and never an overflow:

  reduce     x = 2^E m, m in [1, 2), a subnormal x scaled by 2^p, exactly
             (log1p: m is that of u = 1 + x = u_h + u_l by TwoSum);
             C = round(16 RECIP_SEED(m)) by the magic-number FMA, 8 to 16;
             C = 8 wraps (m' = m/2, C = 16, k = E + 1); c = C/16, exact;
             r = m' c - 1 is ONE FMA and EXACT, |r| < 0.0591 = 2^-4.081
  lookup     L_j = log(16/C), j = C mod 8, two words (three at fp32), the
             same SELECT tree over t's low bits; L_0 = 0
  lowword    log1p, reduction path: r_l = u_l 2^-k c, corrected by
             r_l/(1 + r), 1/(1 + r) by Newton steps from 1 - r, 2^-k taken
             as 0 past k = p + G + 2; at fp32 as a double word with
             rho - rho^2/2. |x| < 15/256 skips the reduction (r = x, k = 0,
             L = 0), the end of the path the study's defect 8 had at 2^-4
  tail,head  Y(r) = log1p(r)/r = sum (-1)^i r^i/(i+1): a single-word tail
             down to K, K double-word steps; at fp32 single, double (K2) and
             triple (K3) word steps
  Z, recon   r Y as a double word; the sum k ln2 + L_j + r Y, with ln 2 in
             three words, the first two TRUNCATED to p - nk bits so that
             k times either is exact (log, log1p); log2: F = L + r Y times
             1/ln2 in two words, then k + it; fp32 sums the terms of three
             words by levels - exactly (a TwoSum chain) down to 2^-48 of the
             scale, by rounded adds below
  final      as the exp family's: R = rnd(V_h + V_l) and the in-lane test
  specials   NaN, +-0 (log, log2: -inf with divideByZero; log1p: the operand),
             the negatives (NaN, invalid), +inf, log1p's -1 (-inf, divideByZero),
             log(1) = +0 and log2(2^k) = k exact with no flag and no mark, and
             log1p's tiny path fma(-x, x, x) for |x| < 2^-(p+2) with its
             underflow cases

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
head and reconstruction carry THREE words (the study's 2.5).

The order of a fragment's instructions. The builders emit in the design's
order, in which the exp family's triple-word routines keep 33 to 36 values
live at once and its double word's 22 to 25: past seq.py's 32 registers at
fp32, so that routines.program refused them ("no register for the harness");
the log family's keep 21 to 24 and 14 to 18. A fragment is therefore
SCHEDULED (Build.fragment, schedule_order): the same instructions in another
topological order, which keeps 17 to 21 live at fp32 and 11 to 13 at the
double word's formats (LIVE_CAP). The order changes no value; the order-free
digest of the dataflow graph, dag_digest(), shows it. The instrumented form
(Build) keeps the design's order.

No augmented addition: the quad is built without R21 (revision 8's question
9), so every error-free sum is a Fast2Sum (3 instructions) where the
exponents of its two terms are provably ordered and a TwoSum (6) where they
are not, as the study's design has it: the double-word exp holds nine
Fast2Sums and one TwoSum, exp2 nine and none, expm1 ten and two, log, log2 and
log1p K + 3 Fast2Sums and one, none and two TwoSums, counted in
Build.meta["fast_two_sum"] and ["two_sum"]. That is the sense of "TwoSum, not
augadd".

Every constant is DERIVED - from mpmath at 3,000 bits or from an exact
rational - and rounded once. `python -m cft_golden.mathlib --check`
re-derives each constant that the built fragments hold, in integer
arithmetic that shares nothing with the generator or with mpmath, and
exits non-zero on a difference.

The instrumented form. build() returns a Build, which keeps what the
specialised fragment drops: the unpruned body, each instruction's phase,
and the probes (V_h, V_l, Bv, for the scaled exp family the biased exponent
Ek, and the values between). Build.fragment() is the fragment; the error
budget of
python/tests/mathlib_budget.py reads the rest. build(..., plant=name)
builds the fragment with one named fault, for the tests: each plant is a
defect the study's model found in itself or one a check of this file's
tests must see (PLANTS).

Marks, as the study's: every figure in a comment is READ, COMPUTED or
stated as a design; what was MEASURED is in docs/VALIDATION.md's entries for
parcels E1, MB1 and MB2, with their commands.

The trigonometric reduction (parcel M2G1, M2's build, wave 1) is beside the
six and is not one of them: the argument reduction that sin, cos and tan will
share, Payne-Hanek against 2/pi's bits in bank words, ported from the study's
model (docs/studies/M2-trig.md, 2.2 and 2.3; its section below). Its names
are public, and the later waves are briefed against them: TRIG_RANGE,
TRIG_LOST, trig_gates, plan_reduction, ReductionValue, reduction_front,
trig_reduction, reduction_audit, build_reduction, REDUCTION_PLANTS and
check_reduction_constants (`--check`, and `--only reduction`). It adds no
routine to NAMES and moves none of the six: their fragments are the ones they
were.
"""

import argparse
import functools
import hashlib
import heapq
import math
import pathlib
import sys
import types
from fractions import Fraction

import mpmath

from . import asm, routines, seq
from . import softfloat as sf
from .formats import FP32, FP64, FP128, FP256, FpFormat

__all__ = ["fragment", "evaluate", "invariants", "flag_words", "build",
           "build_exp", "build_exp2", "build_expm1", "build_log",
           "build_log2", "build_log1p", "Build", "plan_exp", "plan_exp32",
           "plan_log", "plan_log32", "GUARD", "LIVE_CAP", "PLANTS", "FORMATS",
           "NAMES", "EXP_NAMES", "LOG_NAMES", "PHASE_ORDER", "dag_digest",
           "schedule_order", "check_constants", "main",
           "TRIG_RANGE", "TRIG_LOST", "trig_gates", "plan_reduction",
           "ReductionValue", "reduction_front", "trig_reduction",
           "reduction_audit", "build_reduction", "REDUCTION_PLANTS",
           "check_reduction_constants"]

EXP_NAMES = ("exp", "exp2", "expm1")   # the exp family (parcels E1 and MB1)
LOG_NAMES = ("log", "log2", "log1p")   # the log family (parcel MB2)
NAMES = EXP_NAMES + LOG_NAMES          # the routines built: all six
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


def _screens_exp2(fmt: FpFormat):
    """(XOVF, XUNF) of exp2 as encodings: emax + 1 and emin - p, both exact
    (an integer of under 20 bits). x >= XOVF gives 2^x >= 2^(emax+1), an
    overflow under every attribute; x <= XUNF gives 2^x <= 2^(emin-p), at
    most half the smallest subnormal. At x = XUNF itself 2^x IS half of it,
    the tie between +0 and the smallest subnormal, which rmm (roundTiesToAway)
    rounds to the subnormal: the builder answers that one lane apart (the
    screen's quarter rounds to +0), as transcend.exp2 has since profile 3."""
    return (_enc_exact(fmt, fmt.emax + 1), _enc_exact(fmt, fmt.emin - fmt.prec))


def _screen_expm1(fmt: FpFormat):
    """XM1 as an encoding: RD(-(p+2) ln 2). x <= XM1 gives e^x under
    2^-(p+2), so expm1(x) lies within 2^-(p+2) of -1, nearer than half of the
    spacing 2^-p below 1: the answer is -1, or -(1 - 2^-p) under rtz and rup,
    never anything else. ln 2 is irrational, so the screen is never an
    equality."""
    return _enc(fmt, -(fmt.prec + 2) * _ln2(), RDN)


# ---- the log family's constants (parcel MB2) ---------------------------------

# The log family's reduction (the study's 2.3) leaves |r| < 0.0590820 = 2^-4.081
# over all 512 cells of RECIP_SEED, at C = 9 (the study's rmax.py; COMPUTED
# again, exactly, by --check from the seed table). RHO_LOG is that bound
# rounded up, the model's RHO = 0.0592, and the one rho of the family's plan.
# log1p's r = x path ends at SMALL_LOG = 15/256 = 0.0586, under it, so one
# (K, D) serves every path of the family; the first model's end at 2^-4 was
# past it (defect 8, the study's 3.6).
RHO_LOG = Fraction(592, 10000)
SMALL_LOG = Fraction(15, 256)


@functools.lru_cache(maxsize=None)
def _log16(C):
    """log(16/C) to 3,000 bits, as the exact rational it is, for C = 9 to 16
    (0 at C = 16): the table's values."""
    if C == 16:
        return Fraction(0)
    with mpmath.workprec(LN2_BITS):
        return _frac(mpmath.log(mpmath.mpf(16) / C))


@functools.lru_cache(maxsize=None)
def _inv_ln2():
    """1/ln 2 to 3,000 bits, as the exact rational it is."""
    with mpmath.workprec(LN2_BITS):
        return _frac(1 / mpmath.log(2))


def _log_coefficient(i):
    """The Taylor coefficient of r^i in Y(r) = log1p(r)/r, (-1)^i/(i+1):
    exact."""
    return Fraction((-1) ** i, i + 1)


def _k_width(fmt: FpFormat):
    """nk: the bit width of the largest |k| the log family's sum sees, with
    two to spare: the first two words of ln 2 hold p - nk bits each, so that
    k times either is exact (the study's 2.3). k is the exponent of x (of
    1 + x for log1p), at most emax + 1 and, for a subnormal x scaled by 2^p,
    at least emin - man_w; the bound used is the larger of emax + 1 and p - emin,
    plus 2."""
    kmax = max(fmt.emax + 1, -(fmt.emin - fmt.prec)) + 2
    return kmax.bit_length()


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


def plan_exp(fmt: FpFormat, G, rel_z=False):
    """(K, D) for the double-word exp family: K double-word head steps and a
    single-word tail to degree D of Y, the smallest whose estimated bound
    is two bits under 2^-(p+G): the tail through r^(K+1),
    2u rho^(K+1)/(K+1)! (u = 2^-p), within half the target, and with the
    truncation rho^(D+2)/(D+2)! (1 + rho) and the double word's own floor
    10 u^2 under the target (the study's 3.2). Exact rational arithmetic,
    so the plan is the same on every platform. `rel_z` plans expm1, whose
    n = 0 lanes are bounded relative to Z = r Y, not to V = 1 + Z: one factor
    rho fewer in the tail and in the truncation (the study's 3.2, K = 8)."""
    p = fmt.prec
    u = Fraction(1, 2 ** p)
    rho = _rho(fmt, _cushion(fmt))
    target = Fraction(1, 2 ** (p + G + 2))
    floor = 10 * u * u
    if floor >= target:
        raise ValueError(f"G = {G} is past the double word's floor at "
                         f"{fmt.name}: 10 u^2 = 2^{math.log2(floor):.1f}")
    extra = 0 if rel_z else 1

    def tail(K):
        return 2 * u * rho ** (K + extra) / math.factorial(K + 1)

    def trunc(D):
        return rho ** (D + 1 + extra) / math.factorial(D + 2) * (1 + rho)
    K = 1
    while tail(K) > target / 2 and K < 60:
        K += 1
    D = K
    while tail(K) + trunc(D) + floor > target and D < 150:
        D += 1
    return K, D


def plan_log(fmt: FpFormat, G):
    """(K, D) for the double-word log family: K double-word head steps and a
    single-word tail to degree D of Y(r) = log1p(r)/r, the smallest whose
    estimated bound is two bits under 2^-(p+G): the tail, 2u rho^K/(K+1)
    (u = 2^-p; the log family's V is about r Y, so a partial sum enters
    scaled by rho^K, not exp's rho^(K+1)), within half the target, and with
    the truncation rho^(D+1)/((D+2)(1 - rho)) and the double word's own
    floor 12 u^2 under the target (the study's 3.2). Exact rational
    arithmetic, so the plan is the same on every platform: (11, 23) at fp64
    and G = 44, (12, 38) and (12, 68) at fp128 and fp256 and G = 46, the
    study's figures."""
    p = fmt.prec
    u = Fraction(1, 2 ** p)
    rho = RHO_LOG
    target = Fraction(1, 2 ** (p + G + 2))
    floor = 12 * u * u
    if floor >= target:
        raise ValueError(f"G = {G} is past the double word's floor at "
                         f"{fmt.name}: 12 u^2 = 2^{math.log2(floor):.1f}")

    def tail(K):
        return 2 * u * rho ** K / (K + 1)

    def trunc(D):
        return rho ** (D + 1) / ((D + 2) * (1 - rho))
    K = 1
    while tail(K) > target / 2 and K < 60:
        K += 1
    D = K
    while tail(K) + trunc(D) + floor > target and D < 200:
        D += 1
    return K, D


def plan_log32(fmt: FpFormat, G):
    """(K3, K2, D) for the triple-word log family at fp32 (new design: the
    study models only exp there): K3 triple-word head steps, then K2
    double-word steps, then a single-word tail to degree D of Y(r) =
    log1p(r)/r, as plan_exp32 plans exp's, with the log family's weights. A
    partial sum y_i enters V = r Y scaled by r^i relative to V (not exp's
    rho^(i+1)), its coefficient is 1/(i+1) and a w-word step keeps about
    24 w - 2 bits of relative accuracy, so y_i needs
    need(i) = (p + G + 2) + log2(rho^i 2/(i+1)) bits: K3 is the first i
    whose need fits two words less two bits, K3 + K2 the first that fits one
    word less two; D the first degree whose truncation
    rho^(D+1)/((D+2)(1 - rho)) is under 2^-(p+G+3). Exact rational
    arithmetic."""
    p = fmt.prec
    rho = RHO_LOG

    def fits(i, bits):
        return rho ** i * 2 / (i + 1) <= Fraction(2) ** (bits - (p + G + 2))
    D = 1
    while rho ** (D + 1) / ((D + 2) * (1 - rho)) > Fraction(1, 2 ** (p + G + 3)):
        D += 1
    K3 = 0
    while not fits(K3, 2 * p - 2):
        K3 += 1
    K23 = K3
    while not fits(K23, p - 2):
        K23 += 1
    return K3, K23 - K3, D


# ---- the builder ------------------------------------------------------------

# Faults, for the tests: build(name, ..., plant=name) builds the fragment with
# one of them. Each is a defect the study's model found in itself (section
# 3.6) or the study's table of plants (section 8), or one a check of
# python/tests/test_mathlib.py needs to see fail. The value is (the families
# it applies to: "dw" the double word's, "tw" fp32's triple word; the
# routines it applies to; what it is).
_EXPS = "exp exp2 expm1"
_LOGS = "log log2 log1p"
_ALL = _EXPS + " " + _LOGS
PLANTS = {
    "table_entry": ("dw tw", _ALL, "the table's entry j = 3, high word one "
                    "ulp off (T_3 = 2^(3/8); log's L_3 = log(16/11)): the "
                    "study's first plant"),
    "c1_ulp": ("dw tw", "exp expm1", "the reduction's first word C1 one ulp "
               "off (the second)"),
    "bound_loose": ("dw tw", _ALL, "the in-lane bound 2^-40 smaller: Bv = "
                    "2^-(p+G+40) |V_h| (the third)"),
    "bound_wide": ("dw tw", _ALL, "the in-lane bound 2^16 times wider: marks "
                   "far more lanes than the law allows"),
    "bound_half": ("dw tw", _ALL, "the in-lane bound half as wide: Bv = "
                   "2^-(p+G+1) |V_h|"),
    "bound_double": ("dw tw", _ALL, "the in-lane bound twice as wide: Bv = "
                     "2^-(p+G-1) |V_h|"),
    "mark_silenced": ("dw tw", _ALL, "the mark never ORed into the flag word "
                      "(the fifth)"),
    "mark_forced": ("dw tw", _ALL, "the in-lane test's verdict forced to "
                    "'not decided': every lane of the main path marked"),
    "rl_through_y": ("dw", _EXPS, "defect 1: r_l carried through Y(r_h), not "
                     "e^(r_h)"),
    "c3_dropped": ("dw", "exp expm1", "Cody-Waite in two words: n C3 dropped "
                   "from r's low word (defect 2's kind, in exp's reduction)"),
    "tiny_gate_off": ("dw tw", "exp exp2", "the tiny-argument gate removed "
                      "(the study's tenth)"),
    "screen_ulp": ("dw tw", _EXPS, "the overflow screen one ulp low"),
    "head_short": ("dw", _ALL, "two fewer double-word head steps (K - 2)"),
    "tininess_klt_only": ("dw tw", "exp exp2", "tininess decided on k alone, "
                          "not after rounding"),
    "c0_wrong": ("dw tw", "exp exp2", "the fixed grid's offset at k = emin "
                 "2^-3, not 2^-4: C + V reaches 2 and the grid doubles"),
    "square_term_dropped": ("tw", _EXPS, "fp32: the square term of "
                            "e^(r1+r2) - 1 dropped (the study's defect 7)"),
    "two_sum_all": ("dw tw", _ALL, "every Fast2Sum built as a TwoSum: the "
                    "same values, 3 more instructions each, counted "
                    "otherwise"),
    "abs_by_copysign": ("dw tw", _ALL, "|x| built as copysign(x, +0): the "
                        "same values, an opcode outside the design's set"),
    "odd_dropped": ("dw tw", "exp exp2", "the fixed grid's round-to-odd of "
                    "V_l's share built as round-to-nearest: V_l is lost "
                    "where V_h is exactly on a half-grid point and |V_l| is "
                    "under half an ulp of the remainder, and no argument is "
                    "known to reach such a state (check_fixed_grid hands it "
                    "one)"),
    # exp2's own (parcel MB1)
    "exact_no_j": ("dw tw", "exp2", "exp2's exact test without j = 0: "
                   "r' = 0 alone takes x = j/8 for an integer (the study's "
                   "defect 6)"),
    "tie_screen": ("dw tw", "exp2", "the study's screen at x = emin - p "
                   "under rmm: the tie between +0 and the smallest "
                   "subnormal answered +0, as transcend.exp2 did before "
                   "profile 3"),
    "ln2_ulp": ("dw tw", "exp2", "exp2's reduction off by one ulp: the "
                "first word of ln 2 one ulp off"),
    "ln2_short": ("dw tw", "exp2", "ln 2 one word short in r = r' ln 2 "
                  "(the double word's low word, the triple word's third)"),
    # expm1's own (parcel MB1)
    "tiny_path_off": ("dw tw", "expm1 log1p", "the tiny path removed (expm1's "
                      "fma(x, x, x), log1p's fma(-x, x, x)): the main path "
                      "answers |x| < 2^-(p+2)"),
    "m1_screen_off": ("dw tw", "expm1", "the clamp to -1 removed: the main "
                      "path answers x <= -(p+2) ln 2"),
    "m1_answer_rne": ("dw tw", "expm1", "the clamp's answer -1 under every "
                      "attribute, not -(1 - 2^-p) under rtz and rup"),
    "clamp_low": ("dw tw", "expm1", "2^-k taken as 0 four k early, beyond "
                  "p + G - 2, where it is over the bound"),
    "ea_dropped": ("dw tw", "expm1", "the TwoSum error of T_h - 2^-k left "
                   "out of V"),
    "nminn_dropped": ("dw tw", "expm1", "the tiny path's underflow at "
                      "x = -2^emin under rtz and rup left out"),
    # the log family's own (parcel MB2)
    "ln2_two_words": ("dw tw", "log log1p", "defect 2: ln 2 one word short in "
                      "the sum - at the double word the first of p - nk bits "
                      "and the second of p, as the first model had it (k ln 2 "
                      "short by up to 2^3 times the bound), at fp32 the third "
                      "word dropped"),
    "ln2h_ulp": ("dw tw", "log log1p", "the sum's k ln 2 off by one ulp: the "
                 "first word of ln 2 one ulp off, so that k times it is not "
                 "exact"),
    "il2_short": ("dw tw", "log2", "log2's 1/ln 2 one word short: the low "
                  "word left out (fp32: the third)"),
    "il2h_ulp": ("dw tw", "log2", "log2's 1/ln 2 off by one ulp: the first "
                 "word one ulp off"),
    "r_ulp": ("dw tw", _LOGS, "the reduction off by one ulp: r = m' c - 1 "
              "times (1 + 2^-(p-1)), no longer exact"),
    "wrap_off": ("dw tw", _LOGS, "the wrap of C = 8 removed: m' = m, c = 1/2 "
                 "and k not incremented"),
    "small_2m4": ("dw tw", "log1p", "defect 8: log1p's r = x path out to "
                  "|x| < 2^-4, past rho"),
    "ul_dropped": ("dw tw", "log1p", "the low word u_l of 1 + x left out of "
                   "the reduction path"),
    "newton_short": ("dw", "log1p", "one Newton step fewer in 1/(1 + r): the "
                     "low word's correction accurate to 2^-33 only"),
    "rho2_dropped": ("tw", "log1p", "fp32: the square term of log1p(rho) = "
                     "rho - rho^2/2 dropped from the low word's correction "
                     "(2^-49 at fp32, far over the bound)"),
    "p2mk_unclamped": ("dw tw", "log1p", "2^-k built for every k, not taken "
                       "as 0 beyond p + G + 2 (defect 5: a NaN at "
                       "max_normal)"),
    "pminn_dropped": ("dw tw", "log1p", "the tiny path's underflow at "
                      "x = +2^emin under rtz and rdn left out"),
    "exact_x_one": ("dw tw", "log2", "log2's exact test as log's: x = 1 "
                    "alone, not every power of two"),
    # the scheduler's (parcel MB1): the reorder of the specialised body
    "reorder_misnumbered": ("dw tw", _ALL, "a reorder that renumbers one "
                            "operand wrong: still a topological order, but "
                            "one value changes"),
    "reorder_forward": ("dw tw", _ALL, "a reorder that puts one instruction "
                        "before an operand it reads"),
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

    def recip_seed(self, a):
        """About 1/a to 2^-8.5 from the 512-entry table (the log family's
        reduction reads it, as divfull does)."""
        return self.ins(sf.OP_RECIP_SEED, (a,))

    # ---- the error-free transformations (no augadd: question 9) ----
    def two_sum(self, a, c):
        """(s, e): s = RN(a + c) and e the exact error, any exponents
        (Knuth's six)."""
        self._eft["two_sum"] += 1
        s = self.add(a, c)
        a1 = self.sub(s, c)
        b1 = self.sub(s, a1)
        return s, self.add(self.sub(a, a1), self.sub(c, b1))

    def two_diff(self, a, nc):
        """(s, e): s = RN(a - nc) and e the exact error, a - nc = s + e,
        for any exponents: Knuth's six with the second operand given
        negated, as the products and errors of the double word are (nc = -c,
        so TwoSum(a, c) without a NEG)."""
        self._eft["two_sum"] += 1
        s = self.sub(a, nc)
        a1 = self.add(s, nc)
        b1 = self.sub(s, a1)
        da = self.sub(a, a1)
        dcn = self.add(nc, b1)
        return s, self.sub(da, dcn)

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

    def live_indices(self):
        """The indices of the body the specialised fragment keeps, in
        order: the values the result or the flag word reaches."""
        need, stack = set(), [s for s in (self.result, self.flags)
                              if s[0] == "v"]
        while stack:
            v = stack.pop()
            if v not in need:
                need.add(v)
                stack.extend(s for s in self.body[v[1]][2] if s[0] == "v")
        return [i for i in range(len(self.body)) if ("v", i) in need]

    def fragment(self, schedule=True):
        """The specialised routines.Fragment: C4's own specialise() over
        the body - which drops the values neither the result nor the flag
        word reaches and the words they alone read - named for the routine,
        and then SCHEDULED: the same instructions in the order
        schedule_order() gives, so that the fragment keeps few values live at
        once (a pure permutation, shown by dag_digest()). `schedule=False`
        is the design's own order, the one the instrumented form keeps and
        the study's model emitted."""
        f = routines.specialise(routines.Fragment(
            self.meta.get("fn", "exp"), self.fmt, self.rnd, self.inputs,
            self.body, self.result, self.flags, self.words, "read"))
        if not schedule:
            return f
        keep = self.live_indices()
        if len(keep) != len(f.body):
            raise AssertionError(
                f"{self.name}: specialise() changed the body, {len(keep)} "
                f"live values of the build, {len(f.body)} instructions")
        order = schedule_order(f, [self.phase_of[i] for i in keep])
        g = permuted(f, order)
        plant = self.meta.get("plant")
        if plant == "reorder_misnumbered":
            g = _misnumbered(g)
        elif plant == "reorder_forward":
            g = _forward(g)
        return g

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


# ---- the order of the body: the scheduler -----------------------------------
#
# The builders emit in the design's order, the study's: the classification
# first, the scale words and the table before the polynomial, the specials'
# conditions all computed at the start and read at the end. That order keeps
# many values live at once - 22 or 23 at the double word's formats and 33 or
# 34 at fp32 for exp (MEASURED, parcel E1) - and seq.py has 32 registers: the
# triple word's exp did not fit routines.program's allocation, "no register
# for the harness". The values a fragment computes do not depend on the order
# of its instructions, only on the dataflow, so the fragment is emitted in
# another: a topological order that keeps fewer values live. Nothing else
# changes - not an operand, an attribute or a word - and dag_digest() shows
# it: the order-free digest of the dataflow graph is the design's.
#
# Two orders are tried and the one that keeps fewer values live is taken (the
# first on a tie):
#   by phase   Kahn's algorithm taking, of the instructions ready, the one of
#              the earliest phase in PHASE_ORDER (then the earliest in the
#              design's order). The reduction runs first, whole, since it
#              collapses many partial sums into a few words; the polynomial
#              next; the table, the reconstruction and the scale words just
#              before they are read; the classification last, since the
#              specials that read it come last and it reads only x.
#   by depth   a depth-first walk from the flag word and then the result,
#              each instruction emitted just before its first reader, the
#              operand with the larger set of ancestors first (parcel E1's
#              finding: it keeps 11 live at the double word's formats and 25
#              at fp32, where the reduction's partial sums wait for r_1 and
#              r_2 across the polynomial).
# Neither is optimal and none is claimed to be: the live count is measured and
# pinned per fragment (test_mathlib.py's SHAPE), and LIVE_CAP is its maximum.

PHASE_ORDER = ("setup", "reduce", "red-setup", "red-window", "red-products",
               "red-coarse", "red-mid", "red-lower", "red-scale", "red-small",
               "lowword", "tail", "head", "head2", "head3", "Z", "lookup",
               "recon", "scale", "fixed-grid", "final", "classify", "special")


def permuted(f, order):
    """The fragment f with its body in `order`, a permutation of the body's
    indices: value references renumbered, nothing else changed. It does not
    check that the order is topological; invariants() does."""
    n = len(f.body)
    if sorted(order) != list(range(n)):
        raise ValueError("the order is not a permutation of the body")
    new = {old: k for k, old in enumerate(order)}
    body = []
    for old in order:
        op, r, srcs = f.body[old]
        body.append((op, r, tuple(("v", new[s[1]]) if s[0] == "v" else s
                                  for s in srcs)))
    return routines.Fragment(f.op, f.fmt, f.rnd, f.inputs, body,
                             ("v", new[f.result[1]]), ("v", new[f.flags[1]]),
                             f.words, f.stage)


def _ranked_order(f, phases):
    rank = {p: k for k, p in enumerate(PHASE_ORDER)}
    n = len(f.body)
    indeg, users = [0] * n, [[] for _ in range(n)]
    for i, (_op, _r, srcs) in enumerate(f.body):
        for j in {s[1] for s in srcs if s[0] == "v"}:
            indeg[i] += 1
            users[j].append(i)
    ready = [(rank[phases[i]], i) for i in range(n) if indeg[i] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        _rk, i = heapq.heappop(ready)
        order.append(i)
        for u in users[i]:
            indeg[u] -= 1
            if indeg[u] == 0:
                heapq.heappush(ready, (rank[phases[u]], u))
    if len(order) != n:
        raise AssertionError("the body has a cycle")
    return order


def _dfs_order(f):
    n = len(f.body)
    anc = [0] * n
    for i, (_op, _r, srcs) in enumerate(f.body):
        m = 1 << i
        for s in srcs:
            if s[0] == "v":
                m |= anc[s[1]]
        anc[i] = m
    size = [bin(m).count("1") for m in anc]

    def deps(i):
        return sorted({s[1] for s in f.body[i][2] if s[0] == "v"},
                      key=lambda j: (-size[j], j))
    order, seen = [], set()
    for root in (f.flags[1], f.result[1]):
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(deps(root)))]
        while stack:
            node, it = stack[-1]
            for j in it:
                if j not in seen:
                    seen.add(j)
                    stack.append((j, iter(deps(j))))
                    break
            else:
                stack.pop()
                order.append(node)
    if len(order) != n:
        raise AssertionError("an instruction reaches neither the result nor "
                             "the flag word")
    return order


def schedule_order(f, phases):
    """The order of f's body that the fragment is emitted in: of the two
    candidates above the one keeping fewer values live (by phase on a tie).
    `phases[i]` is the phase instruction i was built in."""
    best = None
    for order in (_ranked_order(f, phases), _dfs_order(f)):
        live = permuted(f, order).live_max()
        if best is None or live < best[0]:
            best = (live, order)
    return best[1]


def dag_digest(f):
    """The sha256 of the fragment's dataflow graph, independent of the order
    of its instructions and of its words' names: each instruction is hashed
    from its opcode, its attribute and what its operands hash to (a word by
    its bits, the input by its name); the digest is that of the sorted
    instruction hashes and the hashes of the result and of the flag word.
    Two fragments with one digest compute one function on every argument."""
    h = [None] * len(f.body)

    def ref(s):
        if s[0] == "v":
            return "v:" + h[s[1]]
        if s[0] == "w":
            return "w:%x" % f.words[s[1]]
        return "in:" + s[1]
    for i, (op, r, srcs) in enumerate(f.body):
        text = "%s|%s|%s" % (sf.OP_NAMES[op], r,
                             ",".join(ref(s) for s in srcs))
        h[i] = hashlib.sha256(text.encode()).hexdigest()
    text = "\n".join(sorted(h)) + "\nresult:%s\nflags:%s" % (ref(f.result),
                                                             ref(f.flags))
    return hashlib.sha256(text.encode()).hexdigest()


def _misnumbered(g):
    """The plant reorder_misnumbered: the first SUB after the middle of the
    body whose first operand is a value has it renumbered to the value before
    it. The order is still topological; one value is wrong."""
    body = list(g.body)
    for i in range(len(body) // 2, len(body)):
        op, r, srcs = body[i]
        if op == sf.OP_SUB and srcs[0][0] == "v" and srcs[0][1] > 0:
            body[i] = (op, r, (("v", srcs[0][1] - 1),) + srcs[1:])
            break
    else:
        raise AssertionError("no SUB to misnumber")
    return routines.Fragment(g.op, g.fmt, g.rnd, g.inputs, body, g.result,
                             g.flags, g.words, g.stage)


def _forward(g):
    """The plant reorder_forward: the first instruction after the middle of
    the body that reads the one before it is exchanged with it, so that it
    reads a value not yet defined."""
    n = len(g.body)
    for i in range(n // 2, n):
        if ("v", i - 1) in g.body[i][2]:
            order = list(range(n))
            order[i - 1], order[i] = order[i], order[i - 1]
            return permuted(g, order)
    raise AssertionError("no adjacent pair to exchange")


# ---- the double word's constants, derived ------------------------------------

def _dw_constants(fn, fmt: FpFormat, G, K, D, shift, plant):
    """{role: bits}: every derived constant of the double-word exp, exp2 or
    expm1, each rounded once from an exact value:

      MAGIC            1.5 2^(p-1): n lands in t's low bits
      exp, expm1:
      INVLN2N          RN(8/ln2)
      NC1, NC2, C2, C3 the Cody-Waite words of ln2/8: C1 TRUNCATED to
                       p - nb bits, so n C1 is exact (nb: _n_width), C2 the
                       nearest to what is left and C3 to what is left
                       after that; NC1 and NC2 are the negations
      exp2:
      EIGHT, NINV8     8 and -1/8, exact: n = round(8 x), r' = x - n/8
      LN2H, NLN2H,     ln 2 as two words, RN and then RN of the rest: LN2H
      NLN2L            and the negations of both, which r = r' ln 2 by
                       TwoProd reads
      TH_j, TL_j       2^(j/8) as two words, RN and then RN of the rest
      Y_i              the tail's coefficient 1/(i+1)!, RN, i = K..D
      CH_i, CL_i       the head's, as two words, i = 0..K-1
      XOVF, XUNF       the screens: exp's (_screens), exp2's emax + 1 and
                       emin - p (_screens_exp2); expm1's XOVF is exp's
      XM1              expm1: RD(-(p+2) ln 2), the clamp to -1 (_screen_expm1)
      TINYM1, MINN,    expm1: 2^-(p+2), below which the tiny path answers,
      NMINN            and the smallest normal and its negative, where the
                       tiny path's underflow is decided
      TINYX            exp, exp2: 2^-(p+3): below it the result is decided by
                       the side of 1
      C0               exp, exp2: 2^-4, the fixed grid's offset at k = emin
      BREL             2^-(p+G): the bound; `shift` inflates it for the
                       mark-rate law (2^shift times as wide)
      UNFB, OVFB       the answers of the screens under rnd, which the
                       caller's attribute decides - added by the builder
    """
    p = fmt.prec
    l2 = _ln2()
    c = {}
    c["MAGIC"] = _enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    if fn == "exp2":
        c["EIGHT"] = _enc_exact(fmt, N)
        c["NINV8"] = _enc_exact(fmt, Fraction(-1, N))
        hi, lo = _words(fmt, l2, 2)
        if plant == "ln2_ulp":
            hi += 1
        if plant == "ln2_short":
            lo = 0
        c["LN2H"] = hi
        c["NLN2H"], c["NLN2L"] = sf.negate(fmt, hi), sf.negate(fmt, lo)
    else:
        L = l2 / N
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
    if fn == "exp2":
        c["XOVF"], c["XUNF"] = _screens_exp2(fmt)
    else:
        c["XOVF"], c["XUNF"] = _screens(fmt)
    if plant == "screen_ulp":
        c["XOVF"] -= 1
    if fn == "expm1":
        del c["XUNF"]
        c["XM1"] = _screen_expm1(fmt)
        c["TINYM1"] = _pow2(fmt, -(p + 2))
        c["MINN"] = sf.min_normal_bits(fmt)
        c["NMINN"] = sf.min_normal_bits(fmt, 1)
    else:
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


def _classify_common(b: Build, k_):
    """The conditions every routine's specials select on, from x and words
    alone: |x| as an integer, NaN, signalling NaN, infinity, zero and the
    sign. Returns a namespace."""
    fmt = b.fmt
    x = ("in", "a")
    ib, ZERO, INF = k_["ib"], k_["ZERO"], k_["INF"]
    b.phase = "classify"
    cl = types.SimpleNamespace(x=x, XUNF=None, uns=None, m1s=None, tiny=None,
                               tinyx=None)
    cl.ax = b.iand(x, k_["ABSM"])                     # |x|, as an integer
    cl.isnan = b.icmplt(INF, cl.ax)
    cl.issnan = b.sel(ZERO, cl.isnan, b.iand(x, k_["QBIT"]))  # quiet bit clear
    cl.isinf = b.cmpeq(cl.ax, INF)
    cl.iszero = b.icmplt(cl.ax, k_["INT1"])
    cl.neg = b.ishr(x, ib(fmt.width - 1, "SIGN_SHIFT"))
    return cl


def _classify(b: Build, fn, c, k_):
    """The conditions the specials select on, from x and words alone: NaN,
    signalling NaN, infinity, zero, the sign, and the screens. Returns a
    namespace; `uns` and `tinyx` are exp's and exp2's, `m1s` and `tiny`
    expm1's."""
    x = ("in", "a")
    cl = _classify_common(b, k_)
    if fn == "expm1":
        cl.m1s = b.cmple(x, b.const("XM1", c["XM1"]))     # x <= XM1: -1
        cl.tiny = b.icmplt(cl.ax, b.const("TINYM1", c["TINYM1"]))  # < 2^-(p+2)
    else:
        cl.XUNF = b.const("XUNF", c["XUNF"])
        cl.uns = b.cmple(x, cl.XUNF)                  # x <= XUNF
    cl.ovs = b.cmple(b.const("XOVF", c["XOVF"]), x)   # x >= XOVF
    if fn != "expm1":
        # transcend.py decides |x| < 2^-(p+3) by the side of 1 alone: the
        # routine's R is that side (V = 1 + Z, Z with x's sign), so the
        # in-lane test, whose bound is relative to V, must not be consulted
        # there
        cl.tinyx = b.icmplt(cl.ax, b.const("TINYX", c["TINYX"]))
    return cl


def _scale(b: Build, fn, rnd, t, c, G, plant, k_):
    """2^k1 and 2^k2 from n, integers on the encoding of t (k = floor(n/8),
    k1 = floor(k/2), k2 = k - k1); and, for exp and exp2, the fixed grid's
    words (u = 2^(emin - p + 1 - k) in the scaled domain; Cu the offset
    C = 2^(emin - k), 2^-4 at k = emin; hu the half-grid u/2), for expm1
    2^-k, taken as 0 where k is past p + G + 2 (under the bound: the study's
    2.2 and 3.2)."""
    fmt = b.fmt
    p, mw = fmt.prec, fmt.man_w
    ib, ZERO = k_["ib"], k_["ZERO"]
    MANW = ib(mw, "MANTISSA_WIDTH")
    b.phase = "scale"
    sc = types.SimpleNamespace(sub_p=None, klt=None, Cu=None, hu=None,
                               npk=None)
    OFF = _scale_offset(fmt)
    half = (fmt.bias + OFF) // 2
    b.meta["OFF"] = OFF
    sc.Ek = b.ishr(b.isub(t, ib(c["MAGIC"] - N * (fmt.bias + OFF), "KOFFSET")),
                   ib(T_BITS))                        # k + bias + OFF
    E1 = b.ishr(sc.Ek, k_["INT1"])
    KB1 = ib(fmt.bias - half, "KBIAS1")
    sc.S1 = b.ishl(b.iadd(E1, KB1), MANW)             # 2^k1
    sc.S2 = b.ishl(b.iadd(b.isub(sc.Ek, E1), KB1), MANW)      # 2^k2
    b.probes.update(Ek=sc.Ek, S1=sc.S1, S2=sc.S2)
    if fn == "expm1":
        clamp = p + G + 2 - (4 if plant == "clamp_low" else 0)
        npk = b.ishl(b.isub(ib(2 * fmt.bias + OFF, "K_2BIAS_OFF"), sc.Ek),
                     MANW)
        kbig = b.icmplt(ib(clamp + fmt.bias + OFF, "K_CLAMP"), sc.Ek)
        sc.npk = b.sel(ZERO, npk, kbig)
        b.probes["NPK"] = sc.npk
    else:
        KD = fmt.emin + 2 * fmt.bias + OFF
        # sub_p: k <= emin; klt: k < emin
        sc.sub_p = b.icmplt(sc.Ek, ib(fmt.emin + fmt.bias + OFF + 1,
                                      "K_EMIN_P1"))
        sc.klt = b.icmplt(sc.Ek, ib(fmt.emin + fmt.bias + OFF, "K_EMIN"))
        sc.Cu = b.sel(b.ishl(b.isub(ib(KD, "K_KD"), sc.Ek), MANW),
                      b.const("C0", c["C0"]), sc.klt)
        if rnd in (RNE, RMM):
            sc.hu = b.ishl(b.isub(ib(KD - p, "K_KD_P"), sc.Ek), MANW)
            b.probes["hu"] = sc.hu
        b.probes.update(Cu=sc.Cu, sub_p=sc.sub_p, klt=sc.klt)
    return sc


def _fixed_grid(b: Build, plant, rnd, cl, sc, k_, R, Bv, mk, Vh, rest, tw):
    """A result that may be subnormal (k <= emin) is rounded once on its own
    grid: V_h split at C, the rest (V_l; at fp32 V_1 + V_2 rounded to odd)
    added after rounding to odd (its ulp is finer than u/4), rounded under
    rnd, C taken off again. `rest` is that rest as one word. Returns (Wsel,
    mk, tinyu). The double word's round-to-odd tests the sum's exactness
    against `rest` itself, the triple word's by the Fast2Sum error
    (_round_to_odd_add): the forms parcel E1 built, kept so that exp's
    instructions are the same."""
    ZERO, ONE, INT1 = k_["ZERO"], k_["ONE"], k_["INT1"]
    b.phase = "fixed-grid"
    Z0 = b.add(sc.Cu, Vh)
    W0 = b.sub(Z0, sc.Cu)
    zr = b.sub(Vh, W0)
    if plant == "odd_dropped":
        ro = b.add(zr, rest)                # round-to-nearest: rest can be lost
    elif tw:
        ro = _round_to_odd_add(b, zr, rest, INT1)
    else:
        s_ = b.add(zr, rest, RTZ)
        eq = b.cmpeq(b.sub(s_, zr), rest)
        ro = b.sel(s_, b.ior(s_, INT1), eq)       # round-to-odd of zr + rest
    Ws = b.sub(b.add(Z0, ro, rnd), sc.Cu)
    # the fixed grid's own test: V can straddle a boundary only where zr IS
    # one (+-u/2 for rne and rmm, 0 for the directed three) and |rest| <= Bv
    c1 = b.cmpeq(b.fabs(zr), sc.hu) if sc.hu is not None \
        else b.cmpeq(zr, ZERO)
    smallo = b.cmple(b.fabs(rest), Bv)
    msub = b.sel(smallo, ZERO, c1)
    Wsel = b.sel(Ws, R, sc.sub_p)
    mk = b.sel(ONE, mk, b.sel(msub, ZERO, sc.sub_p))
    # tininess after rounding: k < emin, or k = emin and the precision-p
    # rounding R of the scaled value is below 1
    tn = sc.klt if plant == "tininess_klt_only" else \
        b.sel(ONE, b.cmplt(R, ONE), sc.klt)
    tinyu = b.sel(tn, ZERO, sc.sub_p)
    b.probes.update(Ws=Ws)
    return Wsel, mk, tinyu


def _finalize(b: Build, fn, rnd, plant, c, cl, sc, k_, Wsel, mk, tinyu,
              exact):
    """The scaling by 2^k1 and 2^k2 (the one rounding), the flag word, and
    the specials in the study's order of priority, lowest first."""
    fmt = b.fmt
    p, mw = fmt.prec, fmt.man_w
    ZERO, ONE, INT1 = k_["ZERO"], k_["ONE"], k_["INT1"]
    INF, QNAN = k_["INF"], k_["QNAN"]
    INX, INXUNF, OVFINX = k_["INX"], k_["INXUNF"], k_["OVFINX"]
    x = cl.x
    b.phase = "final"
    Y1 = b.mul(Wsel, sc.S1)                           # exact
    FIN = b.mul(Y1, sc.S2, rnd)                       # the one rounding
    if rnd in (RNE, RMM, RUP):
        ovf = b.cmpeq(FIN, INF)
    else:       # the directed-down attributes answer max_normal, not +inf
        ovf = b.cmpeq(b.mul(Y1, sc.S2, RUP), INF)
    fl = INX if fn == "expm1" else b.sel(INXUNF, INX, tinyu)
    fl = b.sel(OVFINX, fl, ovf)
    if fn != "expm1" and plant != "tiny_gate_off":
        mk = b.sel(ZERO, mk, cl.tinyx)
    if plant == "mark_forced":
        mk = ONE
    if plant != "mark_silenced":
        fl = b.ior(fl, b.sel(k_["MARKW"], ZERO, mk))
    if fn == "exp2":
        fl = b.sel(ZERO, fl, exact)                   # an integer x is exact
    b.probes.update(FIN=FIN, mk=mk)

    b.phase = "special"
    bits = FIN
    if fn == "expm1":
        # |x| < 2^-(p+2): fma(x, x, x) under the attribute, x + x^2, on the
        # side of x that expm1 is on, and the underflow where it is tiny. The
        # IOR is question 12's one instruction, so that none reads only x
        tb = b.fma(b.ior(x, ZERO), x, x, rnd)
        ut = b.icmplt(cl.ax, b.const("MINN", c["MINN"]))  # |x| < 2^emin
        if rnd in (RTZ, RUP) and plant != "nminn_dropped":
            # x = -2^emin: expm1(x) is above it, toward zero, and rtz and rup
            # round that to the largest subnormal: tiny after rounding
            ut = b.sel(ONE, ut, b.cmpeq(x, b.const("NMINN", c["NMINN"])))
        if plant != "tiny_path_off":
            bits = b.sel(tb, bits, cl.tiny)
            fl = b.sel(b.sel(INXUNF, INX, ut), fl, cl.tiny)
        # x <= -(p+2) ln 2: -1, or -(1 - 2^-p) under rtz and rup
        m1b = sf.round_pack(fmt, 1, (1 << (p + 3)) - 1, -(p + 3),
                            RNE if plant == "m1_answer_rne" else rnd)[0]
        if plant != "m1_screen_off":
            bits = b.sel(b.const("M1B", m1b), bits, cl.m1s)
            fl = b.sel(INX, fl, cl.m1s)
    else:
        unfb = sf.round_pack(fmt, 0, 1, fmt.emin - mw - 2, rnd)[0]
        bits = b.sel(b.const("UNFB", unfb), bits, cl.uns)
        fl = b.sel(INXUNF, fl, cl.uns)
        if fn == "exp2" and rnd == RMM and plant != "tie_screen":
            # x = emin - p: 2^x is half the smallest subnormal, the tie
            # between +0 and it, and roundTiesToAway gives the subnormal; the
            # screen's quarter rounds to +0 (the smallest subnormal's
            # encoding is the integer 1)
            bits = b.sel(INT1, bits, b.cmpeq(x, cl.XUNF))
    ovfb = sf.round_pack(fmt, 0, 3, fmt.emax, rnd)[0]
    bits = b.sel(b.const("OVFB", ovfb), bits, cl.ovs)
    fl = b.sel(OVFINX, fl, cl.ovs)
    if fn == "expm1":
        bits = b.sel(x, bits, cl.iszero)              # expm1(+-0) = +-0
        infb = b.sel(b.word(sf.one_bits(fmt, 1), "NEGONE"), INF, cl.neg)
    else:
        bits = b.sel(ONE, bits, cl.iszero)
        infb = b.sel(ZERO, INF, cl.neg)               # exp(-inf) = +0
    fl = b.sel(ZERO, fl, cl.iszero)
    bits = b.sel(infb, bits, cl.isinf)
    fl = b.sel(ZERO, fl, cl.isinf)
    bits = b.sel(QNAN, bits, cl.isnan)
    fl = b.sel(b.sel(k_["INVALID"], ZERO, cl.issnan), fl, cl.isnan)
    return b.finish(bits, fl)


def _table(b: Build, c, t, k_, words):
    """The table's words T_j = 2^(j/8) by a SELECT tree over the three low
    bits of t - the integer j = n mod 8 - read from bank words only: for each
    function in `words` (j -> the role of that word of T_j) the tree over
    the eight entries."""
    ib = k_["ib"]
    bitsel = [b.iand(t, ib(1 << i)) for i in range(T_BITS)]

    def tree(vals):
        level = list(vals)
        for bit in bitsel:
            level = [b.sel(level[2 * m + 1], level[2 * m], bit)
                     for m in range(len(level) // 2)]
        return level[0]
    return [tree([b.const(nm(j), c[nm(j)]) for j in range(N)])
            for nm in words]


def _exact_flag(b: Build, plant, t, rp, k_):
    """exp2: 2^x is exact exactly when x is an integer: r' = 0 together with
    j = 0 (r' = 0 alone is every x = j/8)."""
    if plant == "exact_no_j":
        return b.cmpeq(rp, k_["ZERO"])
    jz = b.icmplt(b.iand(t, k_["ib"](N - 1)), k_["INT1"])
    return b.sel(b.cmpeq(rp, k_["ZERO"]), k_["ZERO"], jz)


def _build_dw(fn, fmt: FpFormat, rnd: int, G, shift, plant):
    """exp, exp2 or expm1 at fp64, fp128 and fp256: V as a double word (the
    module docstring; the study's 2.2 and 3.1). exp2 reduces by n = round(8x)
    exactly and multiplies the exact remainder by a two-word ln 2; expm1
    reduces as exp does, subtracts 2^-k from the table's high word by TwoSum
    and rounds without the fixed grid, since its result is never subnormal
    off its tiny path."""
    p = fmt.prec
    K, D = plan_exp(fmt, G, rel_z=(fn == "expm1"))
    if plant == "head_short":
        K -= 2
    c = _dw_constants(fn, fmt, G, K, D, shift, plant)
    b = Build(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}")
    b.meta.update(fn=fn, G=G, K=K, D=D, N=N, shift=shift, plant=plant,
                  family="double word")
    k_ = _words_common(b)
    ZERO, ONE = k_["ZERO"], k_["ONE"]
    MAGIC = b.const("MAGIC", c["MAGIC"])
    cl = _classify(b, fn, c, k_)
    x = cl.x

    # ---- reduce: n = round(x 8/ln2), r = x - n ln2/8 in two words ----------
    b.phase = "reduce"
    rp = None
    if fn == "exp2":
        # n = round(8x) is exact (8x is a power of two times x), r' = x - n/8
        # is exact (|r'| <= 1/16 and a multiple of x's ulp), and r = r' ln2 is
        # TwoProd of r' against ln 2's high word, its low word added by one
        # FMA: r = rh + rl with nrl = -rl
        t = b.fma(x, b.const("EIGHT", c["EIGHT"]), MAGIC)
        nf = b.sub(t, MAGIC)                          # n, as a float
        rp = b.fma(nf, b.const("NINV8", c["NINV8"]), x)   # r' = x - n/8
        rh = b.mul(rp, b.const("LN2H", c["LN2H"]))
        nre = b.fma(rp, b.const("NLN2H", c["NLN2H"]), rh)     # -(its error)
        nrl = b.fma(rp, b.const("NLN2L", c["NLN2L"]), nre)
        b.probes["rp"] = rp
    else:
        t = b.fma(x, b.const("INVLN2N", c["INVLN2N"]), MAGIC)
        nf = b.sub(t, MAGIC)                          # n, as a float
        r1 = b.fma(nf, b.const("NC1", c["NC1"]), x)   # x - n C1: exact
        Q = b.mul(nf, b.const("NC2", c["NC2"]))       # -n C2, rounded
        Qe = b.fma(nf, b.const("C2", c["C2"]), Q)     # -(its error): exact
        s, e = b.two_sum(r1, Q)                       # r1 + Q = s + e, exact
        rh = s
        # r = rh + rl with rl = e - Qe - n C3; nrl = -rl, as the products
        # below want it
        low = b.sub(Qe, e)
        nrl = low if plant == "c3_dropped" else b.fma(
            nf, b.const("C3", c["C3"]), low)
    nr = b.neg(rh)
    b.probes.update(t=t, nf=nf, rh=rh, nrl=nrl)

    # ---- lookup: T_j = 2^(j/8), j = n mod 8, a SELECT tree -----------------
    b.phase = "lookup"
    Th, Tl = _table(b, c, t, k_, (lambda j: f"TH{j}", lambda j: f"TL{j}"))
    b.probes.update(Th=Th, Tl=Tl)
    exact = _exact_flag(b, plant, t, rp, k_) if fn == "exp2" else None

    sc = _scale(b, fn, rnd, t, c, G, plant, k_)

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

    # ---- reconstruct V = T (1 + Z) [ - 2^-k for expm1 ] as V_h + V_l --------
    b.phase = "recon"
    P = b.mul(Th, zp)
    nPe = b.fma(Th, b.neg(zp), P)                     # P - Th Zh = -(error)
    if fn == "expm1":
        # (T_h - 2^-k) = base + ea exactly. |base| >= |P| for every n but 0
        # (the study's 2.2, COMPUTED from the table: base is 0.0905 at n = 1
        # and -0.166 at n = -1 against |P| under 0.049 and 0.082, and larger
        # beyond); at n = 0, base is 0 and the Fast2Sum below is exact in any
        # order (S = P, e2 = 0)
        base, ea = b.two_diff(Th, sc.npk)
    else:
        base = Th
    S, e2 = b.fast_two_sum(base, P)                   # |base| >= |P|: ordered
    a1 = b.fma(Th, nZl, nPe)                          # -(Th Zl + Pe)
    a2 = b.fma(Tl, zp, Tl)                            # Tl (1 + Zh)
    lo = b.add(b.sub(e2, a1), a2)
    if fn == "expm1" and plant != "ea_dropped":
        lo = b.add(lo, ea)
    Vh, Vl = b.fast_two_sum(S, lo)                    # |S| >= |lo|: ordered
    b.probes.update(Vh=Vh, Vl=Vl)

    # ---- the final rounding and the in-lane test ----------------------------
    b.phase = "final"
    R = b.add(Vh, Vl, rnd)                            # the guess: rnd(Vh + Vl)
    # Bv = 2^-(p+G) |V_h|: exact; expm1's V_h is negative for x < 0
    Bv = b.mul(b.fabs(Vh) if fn == "expm1" else Vh, b.const("BREL", c["BREL"]))
    lo_dn = b.sub(Vl, Bv, RDN)
    lo_up = b.add(Vl, Bv, RUP)
    R1 = b.add(Vh, lo_dn, rnd)
    R2 = b.add(Vh, lo_up, rnd)
    mk = b.ixor(R1, R2)                               # nonzero: not decided
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)
    Wsel, tinyu = R, None
    if fn != "expm1":
        Wsel, mk, tinyu = _fixed_grid(b, plant, rnd, cl, sc, k_, R, Bv, mk,
                                      Vh, Vl, False)
    return _finalize(b, fn, rnd, plant, c, cl, sc, k_, Wsel, mk, tinyu, exact)


# ---- exp, exp2 and expm1 at fp32: three words where the bound needs them -----

def plan_exp32(fmt: FpFormat, G, rel_z=False):
    """(K3, K2, D) for the triple-word routines (the study's 2.5): K3
    triple-word head steps, then K2 double-word steps, then a single-word
    tail to degree D of Y. Y's partial sum y_i enters V scaled by
    rho^(i+1), and a w-word step keeps about 24 w - 2 bits of relative
    accuracy, so y_i needs  need(i) = (p + G + 2) + log2(rho^(i+1) 2/(i+1)!)
    bits: K3 is the first i whose need fits two words less two bits, K3 + K2
    the first that fits one word less two; D the first degree whose
    truncation rho^(D+1)/(D+2)! is under 2^-(p+G+3). Exact rational
    arithmetic. `rel_z` plans expm1, whose n = 0 lanes are bounded relative
    to Z = r Y, not to V = 1 + Z: y_i enters scaled by rho^i, one factor rho
    fewer."""
    p = fmt.prec
    rho = _rho(fmt, _cushion(fmt))
    extra = 0 if rel_z else 1

    def need_within(i, bits):
        return rho ** (i + extra) * 2 / math.factorial(i + 1) <= \
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


def _tw_constants(fn, fmt: FpFormat, G, K3, K2, D, shift, plant):
    """{role: bits} for the triple-word routines: the double word's, with
    ln2/8 in five words at exp and expm1 (three of p - nb bits, so n times
    each is exact, then the nearest two to what is left) and ln 2 in three
    words at exp2 (RN, then RN of what is left, twice); the table and the
    three-word head in three words, and the double-word steps' in two."""
    p = fmt.prec
    l2 = _ln2()
    c = {}
    c["MAGIC"] = _enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))
    if fn == "exp2":
        c["EIGHT"] = _enc_exact(fmt, N)
        c["NINV8"] = _enc_exact(fmt, Fraction(-1, N))
        w0, w1, w2 = _words(fmt, l2, 3)
        if plant == "ln2_ulp":
            w0 += 1
        if plant == "ln2_short":
            w2 = 0
        c["LN2_0"], c["LN2_1"], c["LN2_2"] = w0, w1, w2
        c["NLN2_0"], c["NLN2_1"] = sf.negate(fmt, w0), sf.negate(fmt, w1)
    else:
        L = l2 / N
        nb = _n_width(fmt)
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
    if fn == "exp2":
        c["XOVF"], c["XUNF"] = _screens_exp2(fmt)
    else:
        c["XOVF"], c["XUNF"] = _screens(fmt)
    if plant == "screen_ulp":
        c["XOVF"] -= 1
    if fn == "expm1":
        del c["XUNF"]
        c["XM1"] = _screen_expm1(fmt)
        c["TINYM1"] = _pow2(fmt, -(p + 2))
        c["MINN"] = sf.min_normal_bits(fmt)
        c["NMINN"] = sf.min_normal_bits(fmt, 1)
    else:
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


def _build_tw(fn, fmt: FpFormat, rnd: int, G, shift, plant):
    """exp, exp2 or expm1 at fp32, V as three words (the study's 2.5): the
    reduction's r = r0 + r1 + r2, the table's T = T0 + T1 + T2, the first
    Taylor terms and V itself in three words, the final rounding through
    round-to-odd of the low words. exp2 and expm1 are this parcel's design,
    by the structure of exp's: exp2's r = r' ln 2 is TwoProd of the exact
    remainder against ln 2's first two words and a rounded product with its
    third; expm1's V' subtracts 2^-k from the table's first word by TwoSum
    and puts the error in the level of the table's second word."""
    p = fmt.prec
    K3, K2, D = plan_exp32(fmt, G, rel_z=(fn == "expm1"))
    c = _tw_constants(fn, fmt, G, K3, K2, D, shift, plant)
    b = Build(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}-tw")
    b.meta.update(fn=fn, G=G, K3=K3, K2=K2, D=D, N=N, shift=shift,
                  plant=plant, family="triple word")
    k_ = _words_common(b)
    ZERO, ONE, INT1 = k_["ZERO"], k_["ONE"], k_["INT1"]
    MAGIC = b.const("MAGIC", c["MAGIC"])
    two_sum, fast_two_sum = b.two_sum, b.fast_two_sum
    cl = _classify(b, fn, c, k_)
    x = cl.x

    # ---- reduce: r as three words -------------------------------------------
    b.phase = "reduce"
    rp = None
    if fn == "exp2":
        # n = round(8x) and r' = x - n/8 exact as at the double word; r' ln 2
        # = r' (L0 + L1 + L2 + ...) by TwoProd against L0 and L1 (P0 + e0,
        # P1 + e1) and a rounded product with L2 (P2): the level-1 terms e0
        # and P1 summed by TwoSum, the level-2 terms (its error, e1, P2) by
        # two rounded adds - about 2^-77 - and the three words by a Fast2Sum
        # and a TwoSum. The terms dropped, r' (ln 2 - L0 - L1 - L2) and the
        # error of P2, are under 2^-77
        t = b.fma(x, b.const("EIGHT", c["EIGHT"]), MAGIC)
        nf = b.sub(t, MAGIC)
        rp = b.fma(nf, b.const("NINV8", c["NINV8"]), x)
        P0 = b.mul(rp, b.const("LN2_0", c["LN2_0"]))
        nE0 = b.fma(rp, b.const("NLN2_0", c["NLN2_0"]), P0)   # -e0
        P1 = b.mul(rp, b.const("LN2_1", c["LN2_1"]))
        nE1 = b.fma(rp, b.const("NLN2_1", c["NLN2_1"]), P1)   # -e1
        P2 = b.mul(rp, b.const("LN2_2", c["LN2_2"]))
        u0, u1 = b.two_diff(P1, nE0)                  # e0 + P1 = u0 + u1
        lvl2 = b.sub(b.add(P2, u1), nE1)              # P2 + u1 + e1
        r0, t1 = fast_two_sum(P0, u0)                 # |P0| >= |u0|: ordered
        r1, r2 = two_sum(t1, lvl2)
        b.probes["rp"] = rp
    else:
        # r = x - n ln2/8 from five words of ln2/8
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
    T0, T1, T2 = _table(b, c, t, k_,
                        tuple(lambda j, i=i: f"T{j}_{i}" for i in range(3)))
    exact = _exact_flag(b, plant, t, rp, k_) if fn == "exp2" else None

    # ---- scale factors and the fixed grid (as the double word's) ------------
    sc = _scale(b, fn, rnd, t, c, G, plant, k_)

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

    # ---- V = T (1 + Z) [ - 2^-k for expm1 ], three words --------------------
    b.phase = "recon"
    P0 = b.mul(T0, Z0)
    nP0 = b.fma(T0, b.neg(Z0), P0)                    # -(err)
    P1 = b.mul(T0, Z1)
    nP1 = b.fma(T0, b.neg(Z1), P1)
    Q1 = b.mul(T1, Z0)
    nQ1 = b.fma(T1, b.neg(Z0), Q1)
    if fn == "expm1":
        # (T0 - 2^-k) = base + ea exactly; |base| >= |P0| for every n but 0
        # and exact at n = 0, as at the double word, so the Fast2Sum holds.
        # ea is of the table's second word's size or less, and joins its level
        base, ea = b.two_diff(T0, sc.npk)
    else:
        base = T0
    S0, s1 = fast_two_sum(base, P0)
    m, m1 = two_sum(s1, T1)
    if fn == "expm1" and plant != "ea_dropped":
        m, m_ea = two_sum(m, ea)
    m, m2 = two_sum(m, b.neg(nP0))
    m, m3 = two_sum(m, P1)
    m, m4 = two_sum(m, Q1)
    l2_ = b.add(b.add(b.add(m1, m2), b.add(m3, m4)), T2)
    if fn == "expm1" and plant != "ea_dropped":
        l2_ = b.add(l2_, m_ea)
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
    Bv = b.mul(b.fabs(V0) if fn == "expm1" else V0, b.const("BREL", c["BREL"]))
    lo_dn = _round_to_odd_add(b, V1, b.sub(V2, Bv, RDN), INT1)
    lo_up = _round_to_odd_add(b, V1, b.add(V2, Bv, RUP), INT1)
    R1 = b.add(V0, lo_dn, rnd)
    R2 = b.add(V0, lo_up, rnd)
    mk = b.ixor(R1, R2)
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv, Vh=V0)
    Wsel, tinyu = R, None
    if fn != "expm1":
        Wsel, mk, tinyu = _fixed_grid(b, plant, rnd, cl, sc, k_, R, Bv, mk,
                                      V0, lo, True)
    return _finalize(b, fn, rnd, plant, c, cl, sc, k_, Wsel, mk, tinyu, exact)


# ---- log, log2 and log1p (parcel MB2) -----------------------------------------
#
# The study's 2.3 and 4. x = 2^E m with m in [1, 2) (a subnormal x scaled by
# 2^p, exactly; log1p's m is that of u = 1 + x). C = round(16 RECIP_SEED(m)) by
# the magic-number FMA, which takes the values 8 to 16 over the 512 seed cells;
# C = 8 wraps (m' = m/2, C = 16, k = E + 1); c = C/16; r = m' c - 1 is ONE FMA
# and EXACT, |r| < 0.0591. Then
#
#   log x    = k ln 2 + L_j + log1p(r),     L_j = log(16/C), j = C mod 8
#   log2 x   = k + (L_j + log1p(r))/ln 2
#   log1p(x) = log(u_h + u_l), u = 1 + x by TwoSum: the same core on u_h, the
#              low word folded in as r_l = u_l 2^-k c, corrected by r_l/(1 + r),
#              except that |x| < 15/256 skips the reduction (r = x, k = 0,
#              C = 16).
#
# log1p(r) = r Y(r), Y = sum (-1)^i r^i/(i+1): a single-word Horner tail from
# degree D down to K, then K double-word steps, as the exp family's.

def _log_constants(fn, fmt: FpFormat, G, K, D, shift, plant):
    """{role: bits}: every derived constant of the double-word log, log2 or
    log1p, each rounded once from an exact value:

      MAGIC, SIXTEEN,  1.5 2^(p-1), 16, 1/16 and -MAGIC/16, exact: the
      SIXTEENTH,       reduction's t = fma(seed, 16, MAGIC) is MAGIC + C, and
      NMAGIC16         c = C/16 is fma(t, 1/16, -MAGIC/16)
      HALF, NEGONE     1/2 (m' = m/2 where C = 8 wraps) and -1 (r = m' c - 1)
      MINN, P2P        the smallest normal and 2^p: a subnormal x is scaled
                       by 2^p, exactly (log1p: MINN decides its tiny path's
                       underflow, and 2^p is not used)
      LH_j, LL_j       L_j = log(16/C) as two words, RN and then RN of the
                       rest, C = 8 + j for j = 1..7; entry 0 is 0
      Y_i              the tail's coefficient (-1)^i/(i+1), RN, i = K..D
      CH_i, CL_i       the head's, as two words, i = 0..K-1
      log, log1p:
      LN2H, LN2M,      ln 2 in three words: the first two TRUNCATED to p - nk
      LN2L             bits (nk, _k_width), so that k times either is exact,
                       the third the nearest to what is left (the study's
                       2.3; two words, the first model's choice, were short
                       by up to 2^3 times the bound: its defect 2)
      log2:
      IL2H, NIL2H,     1/ln 2 as two words, RN and then RN of the rest, and
      NIL2L            the negations of both, which the product by FMA reads
      log1p:
      SMALL, TINY      15/256, below which the reduction is skipped (r = x),
                       and 2^-(p+2), below which the tiny path answers
      BREL             2^-(p+G): the bound; `shift` inflates it for the
                       mark-rate law (2^shift times as wide)
    """
    p = fmt.prec
    magic = Fraction(3, 2) * 2 ** (p - 1)
    c = {}
    c["MAGIC"] = _enc_exact(fmt, magic)
    c["SIXTEEN"] = _enc_exact(fmt, 16)
    c["SIXTEENTH"] = _enc_exact(fmt, Fraction(1, 16))
    c["NMAGIC16"] = _enc_exact(fmt, -magic / 16)
    c["HALF"] = _pow2(fmt, -1)
    c["NEGONE"] = _enc_exact(fmt, -1)
    c["MINN"] = sf.min_normal_bits(fmt)
    if fn != "log1p":
        c["P2P"] = _pow2(fmt, p)
    for j in range(N):
        hi, lo = _words(fmt, _log16(16 if j == 0 else 8 + j), 2)
        if plant == "table_entry" and j == 3:
            hi += 1
        c[f"LH{j}"], c[f"LL{j}"] = hi, lo
    for i in range(K, D + 1):
        c[f"Y{i}"] = _enc(fmt, _log_coefficient(i))
    for i in range(K):
        c[f"CH{i}"], c[f"CL{i}"] = _words(fmt, _log_coefficient(i), 2)
    if fn == "log2":
        hi, lo = _words(fmt, _inv_ln2(), 2)
        if plant == "il2_short":
            lo = 0
        if plant == "il2h_ulp":
            hi += 1
        c["IL2H"] = hi
        c["NIL2H"], c["NIL2L"] = sf.negate(fmt, hi), sf.negate(fmt, lo)
    else:
        l2, nk = _ln2(), _k_width(fmt)
        h = _truncated(fmt, l2, p - nk)
        rest = l2 - _dec(fmt, h)
        mid = _truncated(fmt, rest, p - nk)
        low = _enc(fmt, rest - _dec(fmt, mid))
        if plant == "ln2_two_words":
            mid, low = 0, _enc(fmt, rest)
        if plant == "ln2h_ulp":
            h += 1
        c["LN2H"], c["LN2M"], c["LN2L"] = h, mid, low
    if fn == "log1p":
        c["SMALL"] = _enc_exact(fmt, Fraction(1, 16) if plant == "small_2m4"
                                else SMALL_LOG)
        c["TINY"] = _pow2(fmt, -(p + 2))
    c["BREL"] = _pow2(fmt, -(p + G) + shift - _bound_plant(plant))
    return c


def _log_reduce(b: Build, fn, c, k_, cl, plant):
    """The reduction, the same at every format (the study's 2.3): the
    namespace of m' (mp), c (cc), t (tc), r (r), k as a float (kf), and,
    for log1p, u_l (ul). Returns it with the instructions of the "reduce"
    phase made."""
    fmt = b.fmt
    p, mw = fmt.prec, fmt.man_w
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    x = cl.x
    MAGIC = b.const("MAGIC", c["MAGIC"])
    MANW = ib(mw, "MANTISSA_WIDTH")
    red = types.SimpleNamespace(ul=None)
    b.phase = "reduce"
    koff = c["MAGIC"] - fmt.bias         # MAGIC's encoding less the bias
    if fn == "log1p":
        uh, red.ul = b.two_sum(ONE, x)               # u = 1 + x = uh + ul
        xn, eoff = uh, ib(koff, "K_OFFSET")
        b.probes.update(uh=uh, ul=red.ul)
    else:
        issub = b.icmplt(cl.ax, b.const("MINN", c["MINN"]))
        xn = b.sel(b.mul(x, b.const("P2P", c["P2P"])), x, issub)
        eoff = b.sel(ib(koff - p, "K_OFFSET_SUB"), ib(koff, "K_OFFSET"), issub)
    m = b.ior(b.iand(xn, ib(fmt.man_mask, "MANTISSA_MASK")), ONE)
    eb = b.ishr(xn, MANW)                            # the biased exponent
    seed = b.recip_seed(m)
    red.tc = b.fma(seed, b.const("SIXTEEN", c["SIXTEEN"]), MAGIC)
    wrap = b.icmplt(red.tc, ib(c["MAGIC"] + 9, "C_WRAP"))     # C <= 8
    red.mp = b.sel(b.mul(m, b.const("HALF", c["HALF"])), m, wrap)
    red.cc = b.sel(ONE, b.fma(red.tc, b.const("SIXTEENTH", c["SIXTEENTH"]),
                              b.const("NMAGIC16", c["NMAGIC16"])), wrap)
    if plant == "wrap_off":
        wrap = ZERO
        red.mp, red.cc = m, b.fma(red.tc, b.const("SIXTEENTH", c["SIXTEENTH"]),
                                  b.const("NMAGIC16", c["NMAGIC16"]))
    red.r = b.fma(red.mp, red.cc, b.const("NEGONE", c["NEGONE"]))   # exact
    if plant == "r_ulp":
        red.r = b.fma(red.r, b.word(_pow2(fmt, -(p - 1)), "ULP"), red.r)
    kb = b.iadd(b.iadd(eb, eoff), b.sel(INT1, ZERO, wrap))
    red.kb = kb
    red.kf = b.sub(kb, MAGIC)                        # k, as a float: exact
    b.probes.update(m=m, tc=red.tc, cc=red.cc, r=red.r, kf=red.kf)
    return red


def _log_finalize(b: Build, fn, rnd, plant, c, cl, k_, R, mk, r):
    """The flag word and the specials of log, log2 and log1p, in the study's
    order of priority (section 4), lowest first: the main path's inexact (+ the
    mark), the exact cases, log1p's tiny path, the infinity, the negatives,
    zero and -1, NaN."""
    fmt = b.fmt
    x = cl.x
    ib, ZERO, ONE = k_["ib"], k_["ZERO"], k_["ONE"]
    INF, QNAN = k_["INF"], k_["QNAN"]
    INX, INXUNF = k_["INX"], k_["INXUNF"]
    INVALID = k_["INVALID"]
    DIVZ = ib(sf.FLAG_DIVZERO, "FL_DIVZERO")
    NINF = b.word(sf.inf_bits(fmt, 1), "NINF")
    NEGONE = b.const("NEGONE", c["NEGONE"])
    b.phase = "final"
    fl = INX
    if plant == "mark_forced":
        mk = ONE
    if plant != "mark_silenced":
        fl = b.ior(fl, b.sel(k_["MARKW"], ZERO, mk))
    # the exact cases carry no flag, and no mark: log(1) = +0, log2(2^k) = k
    if fn == "log":
        fl = b.sel(ZERO, fl, b.cmpeq(x, ONE))
    elif fn == "log2":
        if plant == "exact_x_one":
            fl = b.sel(ZERO, fl, b.cmpeq(x, ONE))
        else:
            fl = b.sel(ZERO, fl, b.cmpeq(r, ZERO))
    b.probes.update(mk=mk)

    b.phase = "special"
    bits = R
    if fn == "log1p":
        # |x| < 2^-(p+2): fma(-x, x, x) = x - x^2 under the attribute, and
        # the underflow where it is tiny after rounding, |x| < 2^emin or x =
        # +2^emin under rtz and rdn. -x is x IXOR the sign bit: one
        # instruction, so that none reads only the input (question 12)
        nx = b.ixor(x, ib(fmt.sign_mask, "SIGN_BIT"))
        tb = b.fma(nx, x, x, rnd)
        ut = b.icmplt(cl.ax, b.const("MINN", c["MINN"]))
        if rnd in (RTZ, RDN) and plant != "pminn_dropped":
            ut = b.sel(ONE, ut, b.cmpeq(x, b.const("MINN", c["MINN"])))
        tiny = b.icmplt(cl.ax, b.const("TINY", c["TINY"]))
        if plant != "tiny_path_off":
            bits = b.sel(tb, bits, tiny)
            fl = b.sel(b.sel(INXUNF, INX, ut), fl, tiny)
        bits = b.sel(INF, bits, cl.isinf)
        fl = b.sel(ZERO, fl, cl.isinf)
        lt = b.cmplt(x, NEGONE)                    # x < -1, -inf included
        bits = b.sel(QNAN, bits, lt)
        fl = b.sel(INVALID, fl, lt)
        m1 = b.cmpeq(x, NEGONE)
        bits = b.sel(NINF, bits, m1)
        fl = b.sel(DIVZ, fl, m1)
        bits = b.sel(x, bits, cl.iszero)           # log1p(+-0) = +-0
        fl = b.sel(ZERO, fl, cl.iszero)
    else:
        bits = b.sel(INF, bits, cl.isinf)
        fl = b.sel(ZERO, fl, cl.isinf)
        negnz = b.sel(ZERO, cl.neg, cl.iszero)     # negative and not zero
        bits = b.sel(QNAN, bits, negnz)
        fl = b.sel(INVALID, fl, negnz)
        bits = b.sel(NINF, bits, cl.iszero)        # log(+-0) = -inf
        fl = b.sel(DIVZ, fl, cl.iszero)
    bits = b.sel(QNAN, bits, cl.isnan)
    fl = b.sel(b.sel(INVALID, ZERO, cl.issnan), fl, cl.isnan)
    return b.finish(bits, fl)


def _build_log_dw(fn, fmt: FpFormat, rnd: int, G, shift, plant):
    """log, log2 or log1p at fp64, fp128 and fp256: V as a double word (the
    study's 2.3). The sum's ordering claims, each COMPUTED from the table's
    values and the seed cells' runs (docs/VALIDATION.md, parcel MB2's entry
    gives the figures): |k ln 2_h| >= |L_j|
    wherever k != 0 (0.693 against at most 0.575) and the sum is exact at
    k = 0 (k ln 2_h = 0), so Fast2Sum adds them; |L_j| >= |r Y| at every C
    but 16 (0.0645 against at most 0.0340 at C = 15, the least ratio, 1.9),
    where L is 0 and the Fast2Sum is exact, so Fast2Sum adds r Y's high word
    to L in log2; log2's |k| >= |log2 m'| (m' from 0.941 to 1.883: log2 m'
    from -0.087 to 0.913) for k + G; |S| >= |lo| for the last. The study
    adds r Y to A = k ln 2_h + L_j by TwoSum, "the exponents can tie", and so
    does this; |A| >= |r Y| holds in every case but those where A is 0 (k = 0
    with C = 16, or the wrap), by a factor of 1.9 or more (k = 0 and C = 15:
    0.0645 against 0.0340; k = -1 and C = 9: 0.118 against 0.057, a factor
    of 2.1), so a Fast2Sum would do, 3 instructions fewer a call: not taken,
    to keep the study's counts."""
    p = fmt.prec
    K, D = plan_log(fmt, G)
    if plant == "head_short":
        K -= 2
    c = _log_constants(fn, fmt, G, K, D, shift, plant)
    b = Build(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}")
    b.meta.update(fn=fn, G=G, K=K, D=D, N=N, shift=shift, plant=plant,
                  family="double word", scaled=False)
    k_ = _words_common(b)
    ib, ZERO, ONE = k_["ib"], k_["ZERO"], k_["ONE"]
    MANW = ib(fmt.man_w, "MANTISSA_WIDTH")
    cl = _classify_common(b, k_)
    x = cl.x

    # ---- reduce: C, c, r = m' c - 1 exact, k -------------------------------
    red = _log_reduce(b, fn, c, k_, cl, plant)
    r = red.r

    # ---- lookup: L_j = log(16/C), j = C mod 8, a SELECT tree ----------------
    b.phase = "lookup"
    Lh, Ll = _table(b, c, red.tc, k_, (lambda j: f"LH{j}", lambda j: f"LL{j}"))
    b.probes.update(Lh=Lh, Ll=Ll)

    # ---- log1p: the low word of 1 + x, and the r = x path -------------------
    corr = None
    kf = red.kf
    if fn == "log1p":
        b.phase = "lowword"
        # r_l = u_l 2^-k c, and r_l/(1 + r) by y ~ 1/(1 + r) from 1 - r by
        # Newton steps: error r^2, then 2^-16, 2^-32, 2^-64 and the last step's
        # rounding. 2^-k is taken as 0 past k = p + G + 2, where u_l moves
        # log1p by less than the bound: the first model built it for every k
        # and answered a NaN at max_normal (the study's defect 5)
        p2mk = b.ishl(b.isub(ib(fmt.bias + c["MAGIC"], "K_BIAS_MAGIC"),
                             red.kb), MANW)
        if plant != "p2mk_unclamped":
            p2mk = b.sel(ZERO, p2mk, b.icmplt(
                ib(c["MAGIC"] + p + G + 2, "K_CLAMP"), red.kb))
        rl = b.mul(b.mul(red.ul, p2mk), red.cc)
        if plant == "ul_dropped":
            rl = b.mul(b.mul(ZERO, p2mk), red.cc)
        nr0 = b.neg(r)
        y = b.sub(ONE, r)
        for _ in range(2 if plant == "newton_short" else 3):
            e = b.fma(nr0, y, b.sub(ONE, y))             # 1 - (1 + r) y
            y = b.fma(y, e, y)
        corr = b.mul(rl, y)
        b.probes.update(rl=rl, yinv=y, corr=corr, p2mk=p2mk)
        # |x| < 15/256: r = x, k = 0, C = 16 (L = 0), no low word
        sm = b.icmplt(cl.ax, b.const("SMALL", c["SMALL"]))
        r = b.sel(x, r, sm)
        kf = b.sel(ZERO, kf, sm)
        Lh, Ll = b.sel(ZERO, Lh, sm), b.sel(ZERO, Ll, sm)
        corr = b.sel(ZERO, corr, sm)
        b.probes.update(r_used=r, kf_used=kf, small=sm)

    # ---- Y(r) = log1p(r)/r: a single-word tail, K double-word steps ---------
    b.phase = "tail"
    nr = b.neg(r)
    y = b.const(f"Y{D}", c[f"Y{D}"])
    for i in range(D - 1, K - 1, -1):
        y = b.fma(y, r, b.const(f"Y{i}", c[f"Y{i}"]))
    b.phase = "head"
    yh, yl = y, None
    for i in range(K - 1, -1, -1):
        CH = b.const(f"CH{i}", c[f"CH{i}"])
        CL = b.const(f"CL{i}", c[f"CL{i}"])
        pp = b.mul(yh, r)
        ne = b.fma(yh, nr, pp)                        # pp - yh r = -(error)
        nl = b.fma(yl, nr, ne) if yl is not None else ne
        s, e = b.fast_two_sum(CH, pp)                 # |c| >= |pp|: ordered
        tt = b.sub(e, nl)
        yl = b.add(tt, CL) if c[f"CL{i}"] else tt
        yh = s

    # ---- r Y as a double word: lp = lph - nlpl ------------------------------
    b.phase = "Z"
    lph = b.mul(yh, r)
    nlpe = b.fma(yh, nr, lph)
    nlpl = b.fma(yl, nr, nlpe)
    if corr is not None:
        nlpl = b.sub(nlpl, corr)
    b.probes.update(lph=lph, nlpl=nlpl)

    # ---- the sum ------------------------------------------------------------
    b.phase = "recon"
    if fn == "log2":
        # F = L + r Y as a double word, times 1/ln 2 (two words), then k + it
        F, fe = b.fast_two_sum(Lh, lph)               # |L| >= |r Y| or L = 0
        Fl = b.sub(b.add(fe, Ll), nlpl)
        gh = b.mul(F, b.const("IL2H", c["IL2H"]))
        nge = b.fma(F, b.const("NIL2H", c["NIL2H"]), gh)
        ngl = b.fma(F, b.const("NIL2L", c["NIL2L"]), nge)
        ngl = b.fma(Fl, b.const("NIL2H", c["NIL2H"]), ngl)    # G = gh - ngl
        S, e = b.fast_two_sum(kf, gh)                 # |k| >= |gh| or k = 0
        lo = b.sub(e, ngl)
    else:
        kl = b.mul(kf, b.const("LN2H", c["LN2H"]))    # exact
        km = b.mul(kf, b.const("LN2M", c["LN2M"]))    # exact
        A, a = b.fast_two_sum(kl, Lh)                 # |k ln2h| >= |L| or k = 0
        S0, s = b.two_sum(A, lph)                     # the exponents can tie
        S, sm_ = b.fast_two_sum(S0, km)
        t1 = b.add(b.add(s, a), sm_)
        t2 = b.fma(kf, b.const("LN2L", c["LN2L"]), t1)
        t3 = b.add(t2, Ll)
        lo = b.sub(t3, nlpl)
    Vh, Vl = b.fast_two_sum(S, lo)                    # |S| >= |lo|: ordered
    b.probes.update(Vh=Vh, Vl=Vl)

    # ---- the final rounding and the in-lane test ----------------------------
    b.phase = "final"
    R = b.add(Vh, Vl, rnd)                            # the guess: rnd(Vh + Vl)
    # Bv = 2^-(p+G) |V_h|: exact; V_h is negative for x < 1
    Bv = b.mul(b.fabs(Vh), b.const("BREL", c["BREL"]))
    lo_dn = b.sub(Vl, Bv, RDN)
    lo_up = b.add(Vl, Bv, RUP)
    R1 = b.add(Vh, lo_dn, rnd)
    R2 = b.add(Vh, lo_up, rnd)
    mk = b.ixor(R1, R2)                               # nonzero: not decided
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)
    return _log_finalize(b, fn, rnd, plant, c, cl, k_, R, mk, r)


def _log32_constants(fn, fmt: FpFormat, G, K3, K2, D, shift, plant):
    """{role: bits} for the triple-word log, log2 and log1p (fp32): the
    double word's small constants (MAGIC, SIXTEEN, SIXTEENTH, NMAGIC16, HALF,
    NEGONE, MINN, P2P, SMALL, TINY, BREL), the table in three words (L_j_i),
    the coefficients (-1)^i/(i+1) as single words for the tail (Y_i), double
    words for the K2 middle steps (A_i_k) and triple words for the K3 first
    (B_i_k), and, for log and log1p, ln 2 in three words (LN2_0 to LN2_2, each
    the nearest to what the ones before leave, and the negations of the first
    two, which the product's error by FMA reads), for log2 1/ln 2 the same
    way (IL2_k, NIL2_0, NIL2_1)."""
    p = fmt.prec
    magic = Fraction(3, 2) * 2 ** (p - 1)
    c = {}
    c["MAGIC"] = _enc_exact(fmt, magic)
    c["SIXTEEN"] = _enc_exact(fmt, 16)
    c["SIXTEENTH"] = _enc_exact(fmt, Fraction(1, 16))
    c["NMAGIC16"] = _enc_exact(fmt, -magic / 16)
    c["HALF"] = _pow2(fmt, -1)
    c["NEGONE"] = _enc_exact(fmt, -1)
    c["MINN"] = sf.min_normal_bits(fmt)
    if fn != "log1p":
        c["P2P"] = _pow2(fmt, p)
    for j in range(N):
        for i, wd in enumerate(_words(fmt, _log16(16 if j == 0 else 8 + j), 3)):
            if plant == "table_entry" and (j, i) == (3, 0):
                wd += 1
            c[f"L{j}_{i}"] = wd
    lo_i = K3 + K2
    for i in range(lo_i, D + 1):
        c[f"Y{i}"] = _enc(fmt, _log_coefficient(i))
    for i in range(K3, lo_i):
        for k, wd in enumerate(_words(fmt, _log_coefficient(i), 2)):
            c[f"A{i}_{k}"] = wd
    for i in range(K3):
        for k, wd in enumerate(_words(fmt, _log_coefficient(i), 3)):
            c[f"B{i}_{k}"] = wd
    if fn == "log2":
        w0, w1, w2 = _words(fmt, _inv_ln2(), 3)
        if plant == "il2_short":
            w2 = 0
        if plant == "il2h_ulp":
            w0 += 1
        c["IL2_0"], c["IL2_1"], c["IL2_2"] = w0, w1, w2
        c["NIL2_0"], c["NIL2_1"] = sf.negate(fmt, w0), sf.negate(fmt, w1)
    else:
        w0, w1, w2 = _words(fmt, _ln2(), 3)
        if plant == "ln2_two_words":
            w2 = 0
        if plant == "ln2h_ulp":
            w0 += 1
        c["LN2_0"], c["LN2_1"], c["LN2_2"] = w0, w1, w2
        c["NLN2_0"], c["NLN2_1"] = sf.negate(fmt, w0), sf.negate(fmt, w1)
    if fn == "log1p":
        c["SMALL"] = _enc_exact(fmt, Fraction(1, 16) if plant == "small_2m4"
                                else SMALL_LOG)
        c["TINY"] = _pow2(fmt, -(p + 2))
    c["BREL"] = _pow2(fmt, -(p + G) + shift - _bound_plant(plant))
    return c


def _cascade(b: Build, terms):
    """The exact sum of `terms`, [(ref, negated)], a term's ref holding its
    NEGATION where `negated` (the error of a product by FMA is held so): a
    TwoSum chain from the first term, which must not be negated. Returns
    (the chain's sum, the list of its errors, which are exact: sum + errors
    is the terms' sum)."""
    (acc, neg0), rest = terms[0], terms[1:]
    assert not neg0
    errs = []
    for ref, neg in rest:
        acc, e = b.two_diff(acc, ref) if neg else b.two_sum(acc, ref)
        errs.append(e)
    return acc, errs


def _plain_sum(b: Build, terms):
    """The sum of `terms`, [(ref, negated)], by rounded adds in the given
    order (the smallest first): the lowest level of a sum, whose terms are
    under 2^-47 of the result's scale, so that each add's error is under
    2^-72 of it."""
    (acc, neg0), rest = terms[0], terms[1:]
    if neg0:
        acc = b.neg(acc)
    for ref, neg in rest:
        acc = b.sub(acc, ref) if neg else b.add(acc, ref)
    return acc


def _build_log_tw(fn, fmt: FpFormat, rnd: int, G, shift, plant):
    """log, log2 or log1p at fp32: V as three words (new design: the study
    models only exp there; this is exp's and exp2's structure, MB1's, applied
    to the log family). r = m' c - 1 is exact in ONE word, so there is no
    reduction to carry; Y(r) is evaluated in triple-word, double-word and
    single-word Horner steps (plan_log32); the table and ln 2 (or 1/ln 2) are
    three words each, k ln 2 by TwoProd against ln 2's words; and V is the sum
    of the three words' terms by levels - exactly (a TwoSum chain) down to
    2^-48 of the scale, by rounded adds below - normalised by Fast2Sums, then
    the final rounding through round-to-odd of the low words as exp's."""
    p = fmt.prec
    K3, K2, D = plan_log32(fmt, G)
    c = _log32_constants(fn, fmt, G, K3, K2, D, shift, plant)
    b = Build(fmt, rnd, f"{fn}-{fmt.name}-{sf.RND_NAMES[rnd]}-tw")
    b.meta.update(fn=fn, G=G, K3=K3, K2=K2, D=D, N=N, shift=shift,
                  plant=plant, family="triple word", scaled=False)
    k_ = _words_common(b)
    ib, ZERO, ONE, INT1 = k_["ib"], k_["ZERO"], k_["ONE"], k_["INT1"]
    MANW = ib(fmt.man_w, "MANTISSA_WIDTH")
    two_sum, fast_two_sum = b.two_sum, b.fast_two_sum
    cl = _classify_common(b, k_)
    x = cl.x

    # ---- reduce: C, c, r = m' c - 1 exact, k --------------------------------
    red = _log_reduce(b, fn, c, k_, cl, plant)
    r = red.r

    # ---- lookup: L_j = log(16/C) in three words ------------------------------
    b.phase = "lookup"
    L0, L1, L2 = _table(b, c, red.tc, k_,
                        tuple(lambda j, i=i: f"L{j}_{i}" for i in range(3)))
    b.probes.update(L0=L0, L1=L1, L2=L2)

    # ---- log1p: the low word of 1 + x, and the r = x path --------------------
    kf, corr_h, corr_l = red.kf, None, None
    if fn == "log1p":
        b.phase = "lowword"
        # rho = r_l/(1 + r) with r_l = u_l 2^-k c, as a double word, and log1p
        # of it, rho - rho^2/2: at fp32 r_l is up to 2^-24, so rho^2/2 (2^-49)
        # is far over the bound and rho^3/3 (2^-73) is not. 2^-k is taken as 0
        # past k = p + G + 2, where u_l moves log1p by less than the bound
        # (defect 5). u_l 2^-k is exact; r_l = rlh + rll by TwoProd with c;
        # y = 1/(1 + r) from 1 - r by two single-word Newton steps and a
        # double-word one (y_h, y_l = y_h e: 2^-48); rho = rl y by TwoProd of
        # the high words and the two cross products
        p2mk = b.ishl(b.isub(ib(fmt.bias + c["MAGIC"], "K_BIAS_MAGIC"),
                             red.kb), MANW)
        if plant != "p2mk_unclamped":
            p2mk = b.sel(ZERO, p2mk, b.icmplt(
                ib(c["MAGIC"] + p + G + 2, "K_CLAMP"), red.kb))
        ul2 = b.mul(red.ul, p2mk)
        if plant == "ul_dropped":
            ul2 = b.mul(ZERO, p2mk)
        rlh = b.mul(ul2, red.cc)
        nrle = b.fma(ul2, b.neg(red.cc), rlh)             # rlh - ul2 c = -rll
        nr0 = b.neg(r)
        y = b.sub(ONE, r)
        for _ in range(2):
            e = b.fma(nr0, y, b.sub(ONE, y))              # 1 - (1 + r) y
            y = b.fma(y, e, y)
        e = b.fma(nr0, y, b.sub(ONE, y))
        yl = b.mul(y, e)
        rh = b.mul(rlh, y)
        nre = b.fma(rlh, b.neg(y), rh)                    # rh - rlh y = -erh
        # rho_l = erh + rlh y_l + rll y = rlh y_l - w1 with w1 = nre + nrle y;
        # held negated, with rho_h^2/2 taken off: nrho_l = -rho_l, ncorr_l =
        # -(rho_l - rho_h^2/2)
        w1 = b.fma(nrle, y, nre)
        nrho_l = b.fma(b.neg(rlh), yl, w1)
        hrh = b.mul(rh, b.const("HALF", c["HALF"]))
        corr_h = rh
        corr_l = nrho_l if plant == "rho2_dropped" else \
            b.fma(hrh, rh, nrho_l)
        b.probes.update(rl=rlh, yinv=y, corr=corr_h, p2mk=p2mk)
        # |x| < 15/256: r = x, k = 0, C = 16 (L = 0), no low word
        sm = b.icmplt(cl.ax, b.const("SMALL", c["SMALL"]))
        r = b.sel(x, r, sm)
        kf = b.sel(ZERO, kf, sm)
        L0, L1, L2 = (b.sel(ZERO, w, sm) for w in (L0, L1, L2))
        corr_h, corr_l = b.sel(ZERO, corr_h, sm), b.sel(ZERO, corr_l, sm)
        b.probes.update(r_used=r, kf_used=kf, small=sm)

    # ---- Y(r): a single tail, double-word steps, triple-word steps ----------
    b.phase = "tail"
    nr = b.neg(r)
    y = b.const(f"Y{D}", c[f"Y{D}"])
    lo_i = K3 + K2
    for i in range(D - 1, lo_i - 1, -1):
        y = b.fma(y, r, b.const(f"Y{i}", c[f"Y{i}"]))
    b.phase = "head2"
    yh, yl = y, None
    for i in range(lo_i - 1, K3 - 1, -1):
        CH = b.const(f"A{i}_0", c[f"A{i}_0"])
        CL = b.const(f"A{i}_1", c[f"A{i}_1"])
        pp = b.mul(yh, r)
        ne = b.fma(yh, nr, pp)
        nl = b.fma(yl, nr, ne) if yl is not None else ne
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
        p0 = b.mul(y0, r)
        ne0 = b.fma(y0, nr, p0)                       # = -e0
        p1 = b.mul(y1, r) if y1 is not None else None
        ne1 = b.fma(y1, nr, p1) if y1 is not None else None
        p2 = b.mul(y2, r) if y2 is not None else None
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
    b.probes.update(y0=y0, y1=y1, y2=y2)

    # ---- r Y as terms: P0 + e0 + P1 + e1 + P2 --------------------------------
    b.phase = "Z"
    P0 = b.mul(y0, r)
    nE0 = b.fma(y0, nr, P0)                           # P0 - y0 r = -e0
    P1 = b.mul(y1, r)
    nE1 = b.fma(y1, nr, P1)
    P2 = b.mul(y2, r)

    # ---- the sum -------------------------------------------------------------
    b.phase = "recon"
    if fn == "log2":
        # F = L + r Y as three words
        F0s, Ea = fast_two_sum(L0, P0)                # |L0| >= |P0| or L0 = 0
        S1, errs = _cascade(b, [(Ea, False), (L1, False), (nE0, True),
                                (P1, False)])
        S2 = _plain_sum(b, [(P2, False), (nE1, True), (L2, False)]
                        + [(e, False) for e in errs])
        F0, F1 = fast_two_sum(F0s, S1)
        F1, F2 = fast_two_sum(F1, S2)
        F0, F1 = fast_two_sum(F0, F1)
        # G = F / ln 2: F times 1/ln 2 in three words, TwoProd for the
        # products of the first levels and rounded products below
        I0, I1, I2 = (b.const(f"IL2_{i}", c[f"IL2_{i}"]) for i in range(3))
        NI0, NI1 = (b.const(f"NIL2_{i}", c[f"NIL2_{i}"]) for i in range(2))
        g0 = b.mul(F0, I0)
        ng0 = b.fma(F0, NI0, g0)
        g1 = b.mul(F0, I1)
        ng1 = b.fma(F0, NI1, g1)
        g2 = b.mul(F1, I0)
        ng2 = b.fma(F1, NI0, g2)
        q0, q1, q2 = b.mul(F0, I2), b.mul(F1, I1), b.mul(F2, I0)
        # V = k + G
        S0, Ea = fast_two_sum(kf, g0)                 # |k| >= |g0| or k = 0
        S1, errs = _cascade(b, [(Ea, False), (ng0, True), (g1, False),
                                (g2, False)])
        S2 = _plain_sum(b, [(q2, False), (q1, False), (q0, False),
                            (ng2, True), (ng1, True)]
                        + [(e, False) for e in errs])
    else:
        # k ln 2: TwoProd against ln 2's first two words, a rounded product
        # with the third
        LN0, LN1, LN2 = (b.const(f"LN2_{i}", c[f"LN2_{i}"]) for i in range(3))
        NLN0, NLN1 = (b.const(f"NLN2_{i}", c[f"NLN2_{i}"]) for i in range(2))
        kP0 = b.mul(kf, LN0)
        knE0 = b.fma(kf, NLN0, kP0)                   # kP0 - k L0 = -e
        kP1 = b.mul(kf, LN1)
        knE1 = b.fma(kf, NLN1, kP1)
        kP2 = b.mul(kf, LN2)
        s1, Ea = fast_two_sum(kP0, L0)                # |kP0| >= |L0| or k = 0
        S0, Eb = two_sum(s1, P0)                      # the exponents can tie
        lv1 = [(Ea, False), (Eb, False), (knE0, True), (kP1, False),
               (L1, False), (nE0, True), (P1, False)]
        if corr_h is not None:
            lv1.append((corr_h, False))
        S1, errs = _cascade(b, lv1)
        lv2 = [(P2, False), (nE1, True), (L2, False), (kP2, False),
               (knE1, True)]
        if corr_l is not None:
            lv2.append((corr_l, True))                # held negated
        S2 = _plain_sum(b, lv2 + [(e, False) for e in errs])
    V0, V1 = fast_two_sum(S0, S1)
    V1, V2 = fast_two_sum(V1, S2)
    V0, V1 = fast_two_sum(V0, V1)
    b.probes.update(V0=V0, V1=V1, V2=V2, Vh=V0)

    # ---- final: R = rnd(V0 + RO(V1 + V2)); the test on V1 + V2 -+ Bv ---------
    b.phase = "final"
    lo = _round_to_odd_add(b, V1, V2, INT1)
    R = b.add(V0, lo, rnd)
    Bv = b.mul(b.fabs(V0), b.const("BREL", c["BREL"]))
    lo_dn = _round_to_odd_add(b, V1, b.sub(V2, Bv, RDN), INT1)
    lo_up = _round_to_odd_add(b, V1, b.add(V2, Bv, RUP), INT1)
    R1 = b.add(V0, lo_dn, rnd)
    R2 = b.add(V0, lo_up, rnd)
    mk = b.ixor(R1, R2)
    b.probes.update(R=R, R1=R1, R2=R2, Bv=Bv)
    return _log_finalize(b, fn, rnd, plant, c, cl, k_, R, mk, red.r)


def build(name, fmt: FpFormat, rnd: int, *, guard=None, bound_shift=0,
          plant=None) -> Build:
    """`name` (one of NAMES) at `fmt` under the program's attribute `rnd`,
    instrumented (Build.fragment() is the routine). `guard` overrides the
    guard G (GUARD's, by default); `bound_shift` makes the in-lane bound
    2^shift times as wide, so that marks are common enough to count (the
    mark-rate law, the study's 3.4); `plant` builds one fault of PLANTS."""
    if name not in NAMES:
        raise ValueError(f"{name!r} is not a math-library routine built so "
                         f"far: {', '.join(NAMES)}")
    if fmt not in FORMATS:
        raise ValueError(f"{fmt!r} is not one of the four formats")
    if rnd not in sf.RND_NAMES:
        raise ValueError(f"rounding attribute {rnd!r} is not one of the five")
    if plant is not None and plant not in PLANTS:
        raise ValueError(f"unknown plant {plant!r}: {', '.join(PLANTS)}")
    family = "tw" if fmt.name == "fp32" else "dw"
    if plant is not None:
        families, names, _text = PLANTS[plant]
        if family not in families.split():
            raise ValueError(f"plant {plant!r} does not apply to the "
                             f"{'triple' if family == 'tw' else 'double'}-"
                             f"word fragments ({fmt.name})")
        if name not in names.split():
            raise ValueError(f"plant {plant!r} does not apply to {name}: "
                             f"{names}")
    G = GUARD[fmt.name] if guard is None else guard
    if name in LOG_NAMES:
        if family == "tw":
            return _build_log_tw(name, fmt, rnd, G, bound_shift, plant)
        return _build_log_dw(name, fmt, rnd, G, bound_shift, plant)
    if family == "tw":
        return _build_tw(name, fmt, rnd, G, bound_shift, plant)
    return _build_dw(name, fmt, rnd, G, bound_shift, plant)


def build_log(fmt: FpFormat, rnd: int, **kw) -> Build:
    """build("log", fmt, rnd, ...)."""
    return build("log", fmt, rnd, **kw)


def build_log2(fmt: FpFormat, rnd: int, **kw) -> Build:
    """build("log2", fmt, rnd, ...)."""
    return build("log2", fmt, rnd, **kw)


def build_log1p(fmt: FpFormat, rnd: int, **kw) -> Build:
    """build("log1p", fmt, rnd, ...)."""
    return build("log1p", fmt, rnd, **kw)


def build_exp(fmt: FpFormat, rnd: int, **kw) -> Build:
    """build("exp", fmt, rnd, ...)."""
    return build("exp", fmt, rnd, **kw)


def build_exp2(fmt: FpFormat, rnd: int, **kw) -> Build:
    """build("exp2", fmt, rnd, ...)."""
    return build("exp2", fmt, rnd, **kw)


def build_expm1(fmt: FpFormat, rnd: int, **kw) -> Build:
    """build("expm1", fmt, rnd, ...)."""
    return build("expm1", fmt, rnd, **kw)


# ---- the trigonometric reduction (parcel M2G1) --------------------------------
#
# The argument reduction that sin, cos and tan share: |x| = n pi/2 + r, with
# r = r_h + r_l, |r| <= pi/4 (1 + 2^-30) (2^-11 at fp32, G = 18: see
# trig_reduction) and n mod 4 in the low bits of q's encoding.
# Payne-Hanek against 2/pi's bits, design A of the study's 2.2 and 2.3
# (docs/studies/M2-trig.md; Logan's answers of 2026-10-14: 2/pi in bank words
# read by a SELECT shifter, 2^1024 at fp128 and fp256, fp64's whole range,
# G = 44, 46, 46). The construction below IS the study's model
# (docs/studies/m2/, m2plan.py and m2red.py), ported; nothing here imports
# it, and the port is held to it in the parcel's entry. M2G2's routines build
# on this interface; a change to a public name below is the lead's to approve.
#
# x = M 2^e, M the p-bit integer significand, e = E - (p-1). 2/pi =
# sum_k c_k 2^-((k+1) b), each chunk c_k a b-bit integer held exactly as a
# float. The bucket g - 1 = floor((E - p - 1) / b) picks the window c_(g-1) ..
# c_(g-2+L); sigma = e - g b is in [2 - b, 1]; x 2/pi = 2^sigma S (mod 4),
# S = sum_(j<L) M c_(g-1+j) 2^-(jb), and S is reduced modulo m = 2^(2-sigma)
# in S-hat units, where every product has a fixed grid and fixed bounds
# whatever sigma is. So every piece is bounded once, at generation, over the
# chunks that can stand at its position (_analyse), and the generator emits
# only the operations the bounds need.
#
# The phases: red-setup (E, the bucket, sigma's powers of two, M), red-window
# (the SELECT shifter), red-products, red-coarse, red-mid (the exact sum, where
# the cancellation happens), red-lower, red-scale (t V, r = t pi/2 as a double
# word, n) and red-small (|x| < RD(pi/4) takes r = |x|).
#
# The claims. An instruction the generator calls EXACT (its rounding loses
# nothing, by the static bounds) is recorded in Build.meta["exact"], and a
# rounding that SELECTS an integer (a quotient, a split's high part, a
# bucket) in Build.meta["data"]. reduction_audit() checks every exact claim on
# a lane against the exact operation. Each static proof of the generator that
# fails is a ValueError that names it.
#
# Marks. Figures here are READ from the study, COMPUTED from the generator's
# own static bounds (the cushion past pi/4) or stated as design; what was
# MEASURED is in docs/VALIDATION.md's entry for parcel M2G1.

# |x| < 2^R, None the whole range (the study's 2.3; Logan's answer 2 of
# 2026-10-14).
TRIG_RANGE = {"fp32": None, "fp64": None, "fp128": 1024, "fp256": 1024}

# The deepest cancellation the reduction must carry, |t| >= 2^-(lost+1)
# (the study's 1.4). fp32, fp64: READ from docs/TRANSCENDENTALS.md, every
# binade searched by host/tools/pi_worstcase.py. fp128, fp256: the study's
# MEASURED figures over the stated range [1, 2^1024): 123 at value exponent
# 909, which is past the docs' sampled 121, and 244, for which 245 is kept.
TRIG_LOST = {"fp32": 29, "fp64": 61, "fp128": 123, "fp256": 245}

_TRIG_DELTA = 3                  # the reduction's share of the bound: 2^-delta
_TRIG_LOW_CAP = 4                # the lower pieces' bound, in units of 2^bottom
_TRIG_PLAN_B_MIN = 2             # no plan for a chunk narrower than this
# the header the library reduces with, which --check holds the chunks to
_TWO_OPI_HEADER = (pathlib.Path(__file__).resolve().parents[2] / "host" / "src"
                   / "mp_2opi.h")

# Faults of the reduction, for the tests: build_reduction(..., plant=name),
# trig_reduction(..., plant=name). Each is the defect named; the value is its
# description. A plant that could not act (the fault is not reached at that
# format) is refused by name, so that none passes by doing nothing.
REDUCTION_PLANTS = {
    "chunk": "one bit flipped in a stored chunk of 2/pi, the middle one",
    "window": "the window read one word late: the shift one too large",
    "mid_inexact": "the mid pieces rounded, design B's sum, while design A's "
                   "claims stand",
    "exact_add": "the mid sum's first TwoSum a plain add, still claimed exact",
    "quadrant_dropped": "the last quadrant count left out of n",
    "bucket_nearest": "the bucket's floor rounded to nearest, not down",
    "pio2_low": "pi/2's low word dropped",
    "claims_lost": "no claim recorded: Build.meta has no exact or data",
    "range_short": "the range word 2^(R-1), not 2^R",
    "split_unproved": "the split's range proof not enforced: a configuration "
                      "refused by it is built",
    "fast_as_two_sum": "every Fast2Sum of the reduction built as a TwoSum: "
                       "the same values, 3 more instructions each",
    "lw_understated": "the static bound of the mid sum's low word, kept in "
                      "Build.meta['reduction_mid'], 8 bits too small: no "
                      "value changes, the computed cushion bound falls below "
                      "a measured overshoot",
}

_AUDITED = (sf.OP_ADD, sf.OP_SUB, sf.OP_MUL, sf.OP_FMA)


def trig_gates(fmt):
    """(gs, gc): the definition's tiny gates at `fmt` as exponents. sin's
    tiny path takes |x| < 2^gs and cos's and tan's |x| < 2^gc; below them
    transcend.py answers by the neighbour rules (2 e + p + 2 <= 0 for sin,
    2 e + p + 3 <= 0 for cos and tan, e = floor(log2 |x|)), so a reduction
    is wanted from 2^(min(gs, gc) - 1) up (plan_reduction's Egate): -27,
    -57, -119 for both at fp64, fp128 and fp256; -12 and -13 at fp32."""
    p = fmt.prec
    return -((p + 3) // 2) + 1, -((p + 4) // 2) + 1


@functools.lru_cache(maxsize=None)
def _two_over_pi_int(nbits):
    """floor(2/pi 2^nbits), from mpmath at nbits + 64 bits (--check holds it
    to host/src/mp_2opi.h and to an integer derivation of pi)."""
    with mpmath.workprec(nbits + 64):
        v = _frac(mpmath.mpf(2) / mpmath.pi * (mpmath.mpf(2) ** nbits))
    return v.numerator // v.denominator


def _reduction_chunks(b, count):
    """c_0 .. c_(count-1): 2/pi = sum c_k 2^-((k+1) b), each a b-bit integer
    (the bits [k b, (k+1) b) after the binary point)."""
    nb = b * count
    t = _two_over_pi_int(nb)
    return [(t >> (nb - (k + 1) * b)) & ((1 << b) - 1) for k in range(count)]


@functools.lru_cache(maxsize=None)
def _pi():
    """pi to 3,000 bits, as the exact rational it is."""
    with mpmath.workprec(LN2_BITS):
        return _frac(+mpmath.pi)


def _ulp_exp(v, p):
    """floor(log2 v) - p + 1 for a rational v > 0: the exponent of v's ulp."""
    e0 = v.numerator.bit_length() - v.denominator.bit_length()
    return e0 - (1 if Fraction(2) ** e0 > v else 0) - p + 1


def _plan_b(fmt, G, lost, Emax, Egate, delta, b, L=None, bottom=None):
    """The reduction's parameters at fmt for guard G, a cancellation `lost`
    (|t| >= 2^-(lost+1)), arguments |x| < 2^(Emax+1) down to 2^Egate, and the
    chunk width b (m2plan.plan_b):
      budget   t's absolute error allowed: 2^-(p+G+delta+lost+1)
      L        chunks a lane: the tail 2^(1+p-(L-1)b) within budget/4
      bottom   the S-hat exponent below which a piece may round: the lower
               pieces' double-word sum within budget/4."""
    p = fmt.prec
    P = types.SimpleNamespace(fmt=fmt, G=G, lost=lost, delta=delta)
    P.budget = -(p + G + delta + lost + 1)
    if bottom is None:
        babs = math.floor(P.budget - 2 + 2 * p - math.log2(3 * _TRIG_LOW_CAP))
        bottom = babs - 1
    P.bottom = bottom
    P.b = b
    P.L = L if L is not None else 1 + math.ceil((1 + p - (P.budget - 2)) / b)
    P.Emax, P.Egate = Emax, Egate
    G0min, G0max = Egate - p - 1, Emax - p - 1
    P.gm1_min, P.gm1_max = G0min // b, G0max // b
    P.Z = max(0, -P.gm1_min)
    P.nchunks = P.gm1_max + P.L          # c_0 .. c_(nchunks-1)
    P.K = P.Z + P.nchunks                # the stored words
    P.bits = P.nchunks * b
    P.chunks = _reduction_chunks(b, P.nchunks)
    P.words = [0] * P.Z + P.chunks       # the table the window reads
    P.shifts = P.gm1_max - P.gm1_min + 1
    P.rows = _analyse(P)
    return P


def _positions(P):
    """[(j, smallest nonzero chunk, largest chunk, any chunk zero)] over the
    chunks that can stand at position j, for every bucket the range has."""
    out = []
    for j in range(P.L):
        cs = [P.chunks[gm1 + j] if gm1 + j >= 0 else 0
              for gm1 in range(P.gm1_min, P.gm1_max + 1)]
        nz = [c for c in cs if c]
        out.append((j, min(nz) if nz else 0, max(cs), 0 in cs))
    return out


def _analyse(P):
    """Static bounds of every piece in S-hat units: for position j, T_j in
    [2^(p-1) cmin, (2^p - 1) cmax] 2^-(jb) on grid 2^-(jb); the TwoProd pieces
    P_j = RN(T_j) (grid >= max(2^-(jb), ulp(Tmin))) and rho_j = T_j - P_j
    (|rho_j| <= ulp(Tmax), grid 2^-(jb)). Rows (j, log2 Tmin, log2 Tmax, P's
    grid exponent, rho's bound exponent, rho's grid exponent), None for a
    position no bucket gives a chunk."""
    p = P.fmt.prec
    rows = []
    for j, cmin, cmax, _zero in _positions(P):
        if cmax == 0:
            rows.append((j, None, None, None, None, None))
            continue
        tmin = Fraction((1 << (p - 1)) * cmin, 1 << (j * P.b))
        tmax = Fraction(((1 << p) - 1) * cmax, 1 << (j * P.b))
        pgrid = max(-j * P.b, _ulp_exp(tmin, p))
        rows.append((j, math.log2(tmin), math.log2(tmax), pgrid,
                     _ulp_exp(tmax, p), -j * P.b))
    return rows


def plan_reduction(fmt, G, *, R="default", b=None):
    """The trigonometric reduction's plan at `fmt` for guard G, a
    types.SimpleNamespace, for every argument 2^Egate <= |x| < 2^R (the whole
    range where R is None). `R` is TRIG_RANGE's by default; a smaller R is
    planned with the same TRIG_LOST, which covers it. A larger one, and R =
    None where TRIG_RANGE is 1024 (fp128, fp256), is refused naming 2^1024,
    the range the cancellation was measured over; so is an R of 0 or less
    and a 2^R the format does not hold (fp64 at 1024).

    Fields: b (the chunk width, the widest for which the coarse sum is
    provably exact: searched downward from the exact combination's, unless
    `b` is given), L (chunks a lane), Z (leading zero words), K (words
    stored), nchunks, bits (of 2/pi), bottom, budget (log2 of t's error
    allowed), delta, gm1_min, gm1_max (the buckets g - 1), shifts, chunks
    (c_0 ..), words (Z zeros, then the chunks: the table), rows (the static
    bounds, _analyse), Emax and Egate (the exponents of the range's ends),
    and fmt, G, lost, R.

    Where no plan exists the answer is a ValueError that names the proof:
    "no plan: the exact combination needs b <= 2p + 1 + bottom = -7 ..." (fp32
    at G = 40), or "b = 109: the coarse sum is not exact" (fp128, a b given)."""
    if fmt.name not in TRIG_LOST:
        raise ValueError(f"{fmt.name}: no cancellation figure (TRIG_LOST)")
    if R == "default":
        R = TRIG_RANGE[fmt.name]
    if R is not None and (not isinstance(R, int) or isinstance(R, bool)
                          or R < 1):
        raise ValueError(f"R = {R!r}: the range is None or an exponent of "
                         f"at least 1")
    if R is not None and R > fmt.emax:
        raise ValueError(f"R = {R}: 2^R is not a finite {fmt.name} number "
                         f"(the largest power of two is 2^{fmt.emax}); the "
                         f"whole range is R = None")
    top = TRIG_RANGE[fmt.name]
    if top is not None and (R is None or R > top):
        raise ValueError(
            f"R = {R}: past 2^{top}, the range TRIG_LOST[{fmt.name!r}] = "
            f"{TRIG_LOST[fmt.name]} was measured over (pi_worstcase's search "
            f"of every binade of [1, 2^{top}), the study's 1.4)")
    p = fmt.prec
    lost = TRIG_LOST[fmt.name]
    gs, gc = trig_gates(fmt)
    Emax = (R - 1) if R is not None else fmt.emax
    Egate = min(gs, gc) - 1
    if b is not None and b < _TRIG_PLAN_B_MIN:
        raise ValueError(f"b = {b}: no plan for a chunk under "
                         f"{_TRIG_PLAN_B_MIN} bits")
    if b is None:
        budget = -(p + G + _TRIG_DELTA + lost + 1)
        bottom = math.floor(budget - 2 + 2 * p
                            - math.log2(3 * _TRIG_LOW_CAP)) - 1
        if 2 * p + 1 + bottom < _TRIG_PLAN_B_MIN:
            raise ValueError(
                f"no plan: the exact combination needs b <= 2p + 1 + bottom "
                f"= {2 * p + 1 + bottom} (budget {budget}, bottom {bottom})")
        if p - 4 < _TRIG_PLAN_B_MIN:
            raise ValueError(f"no plan: the coarse sum needs b <= p - 4 = "
                             f"{p - 4}")
    cand = b
    while True:
        P = _plan_b(fmt, G, lost, Emax, Egate, _TRIG_DELTA,
                    cand if cand is not None
                    else min(p - 4, 2 * p + 1 + bottom))
        # the coarse sum: three terms of at most m <= 2^b on the grid of P_1's
        # ulp, which a chunk with leading zeros makes finer
        pgrid1 = P.rows[1][3] if len(P.rows) > 1 else None
        if math.log2(3) + P.b - min(0, pgrid1 or 0) < p:
            P.R = R
            return P
        if b is not None:
            raise ValueError(
                f"b = {b}: the coarse sum is not exact (three terms of at "
                f"most 2^{b} on the grid 2^{pgrid1} of P_1's ulp need "
                f"log2(3) + b - min(0, {pgrid1}) < p = {p})")
        cand = P.b - 1
        if cand < _TRIG_PLAN_B_MIN:
            raise ValueError("no plan: the coarse sum is exact for no chunk "
                             f"of {_TRIG_PLAN_B_MIN} bits or more")


class ReductionValue:
    """A value of the reduction with static bounds: |v| <= 2^mag (mag a
    float, log2) and v a multiple of 2^grid (grid an int, the exponent). The
    generator's proofs of exactness read these two numbers and no lane's
    value: `ref` is the instruction (or word) holding it."""
    __slots__ = ("ref", "mag", "grid")

    def __init__(self, ref, mag, grid):
        self.ref, self.mag, self.grid = ref, mag, grid

    def __repr__(self):
        return (f"ReductionValue({self.ref}, mag {self.mag:.2f}, "
                f"grid {self.grid})")


def _lg(x):
    return math.log2(x) if x > 0 else -1e9


class _Red:
    """The reduction under construction: the Build, the plan, the plant and
    the claims. Not public: reduction_front() and trig_reduction() make one."""

    def __init__(self, b, P, plant):
        self.b, self.P, self.plant = b, P, plant
        self.fmt = fmt = b.fmt
        if P.fmt != fmt:
            raise ValueError(f"the plan is for {P.fmt.name}, the build for "
                             f"{fmt.name}")
        self.p, self.mw, self.bias = fmt.prec, fmt.man_w, fmt.bias
        self.bb = P.b
        self.full = (1 << fmt.width) - 1
        self.fired = set()
        if plant == "claims_lost":
            self.fired.add(plant)
        else:
            b.meta.setdefault("exact", set())
            b.meta.setdefault("data", set())
        b.meta["reduction"] = P
        b.meta.setdefault("two_prod", 0)
        self.ZERO = b.word(0, "ZERO")
        self.magic_val = Fraction(3, 2) * 2 ** (self.p - 1)
        self.magic_bits = _enc_exact(fmt, self.magic_val)
        self.magic = b.const("MAGIC", self.magic_bits)

    # words
    def wi(self, v):
        return self.b.word(v & self.full)

    def wx(self, v):
        return self.b.word(_enc_exact(self.fmt, v))

    def wv(self, v):
        return self.b.word(_enc(self.fmt, v))

    # claims
    def exact(self, ref):
        if self.plant != "claims_lost":
            self.b.meta["exact"].add(ref)
        return ref

    def data(self, ref):
        if self.plant != "claims_lost":
            self.b.meta["data"].add(ref)
        return ref

    def two_prod(self):
        self.b.meta["two_prod"] += 1

    def fast(self, a, c):
        if self.plant == "fast_as_two_sum":
            self.fired.add(self.plant)
            return self.b.two_sum(a, c)
        return self.b.fast_two_sum(a, c)

    def add_exact(self, a, c):
        """a + c claimed exact: both on known grids and the sum fits p bits
        by their bounds, else None (the static proof fails)."""
        g = min(a.grid, c.grid)
        mag = _lg(2 ** a.mag + 2 ** c.mag)
        if mag - g >= self.p:
            return None
        return ReductionValue(self.exact(self.b.add(a.ref, c.ref)), mag, g)

    def mod_m(self, fr, v, guard=False):
        """v reduced modulo m: q = MAGIC + round(v/m), r = v - q m, exact;
        with `guard`, 0 where |v| >= 2^(p-1) m (v's ulp is then a multiple of
        m)."""
        b = self.b
        q = self.data(b.fma(v.ref, fr.inv_m, self.magic))
        nq = self.exact(b.sub(self.magic, q))
        r = self.exact(b.fma(nq, fr.m, v.ref))
        if guard:
            thr = b.iadd(fr.m, self.wi((self.p - 1) << self.mw))
            small = b.cmplt(b.fabs(v.ref), thr)
            r = b.sel(r, self.ZERO, small)
        # |r| <= m <= 2^b, and r = v - q m is a multiple of min(grid, 2)
        return ReductionValue(r, min(v.mag, self.bb + 0.0), min(v.grid, 1))

    def check_fired(self):
        if self.plant is not None and self.plant not in self.fired:
            raise ValueError(f"plant {self.plant!r} does not apply at "
                             f"{self.fmt.name} (G = {self.P.G}, R = "
                             f"{self.P.R}): the fault is not reached")


def _window(R, shift):
    """The L words words[s + j], j < L, s the shift (an integer in the low
    bits of `shift`'s encoding), by a SELECT log-shifter: at the level of bit
    i an array of L + 2^i - 1 values, each the SELECT of two of the level
    above. Bank words only. -> [refs]."""
    b, P = R.b, R.P
    words = list(P.words)
    if R.plant == "chunk":
        words[P.Z + P.nchunks // 2] ^= 1 << (P.b // 2)
        R.fired.add("chunk")
    arr = [R.ZERO if k < P.Z else
           b.const(f"CHUNK{k - P.Z}", _enc_exact(R.fmt, c))
           for k, c in enumerate(words)]
    nbits = max(1, (P.shifts - 1).bit_length())
    for i in range(nbits - 1, -1, -1):
        bit = b.iand(shift, R.wi(1 << i))
        need = P.L + (1 << i) - 1
        nxt = []
        for k in range(need):
            lo = arr[k] if k < len(arr) else arr[-1]
            hi = arr[k + (1 << i)] if k + (1 << i) < len(arr) else arr[-1]
            nxt.append(b.sel(hi, lo, bit))
        arr = nxt
    return arr[:P.L]


def _front(R, x):
    b, P, fmt = R.b, R.P, R.fmt
    p, mw, bias, bb, L = R.p, R.mw, R.bias, R.bb, P.L
    wi, wx, wv, ZERO, MAGIC = R.wi, R.wx, R.wv, R.ZERO, R.magic
    fr = types.SimpleNamespace(plan=P, magic=MAGIC)
    b.phase = "red-setup"
    # E from the encoding; the bucket first, since the window needs it
    Eb = b.ishr(b.iand(x, wi(fmt.exp_mask << mw)), wi(mw))
    Ebm = b.ior(Eb, MAGIC)                              # MAGIC + Eb
    # G0p = G0 + 2 - b, G0 = Eb - bias - p - 1
    G0p = R.exact(b.sub(Ebm, wx(R.magic_val + bias + p + 1 - 2 + bb)))
    # g - 1 = floor((G0 + 1/2)/b) = floor((G0p + b - 3/2)/b)
    INVB = b.const("INVB", _enc(fmt, Fraction(1, bb)))
    FLOOROFF = b.const("FLOOROFF", _enc(fmt, Fraction(2 * bb - 3, 2 * bb)))
    y = b.fma(G0p, INVB, FLOOROFF)
    # the floor: RDN (the plant rounds to nearest)
    nearest = R.plant == "bucket_nearest"
    if nearest:
        R.fired.add("bucket_nearest")
    gm1m = R.data(b.add(y, MAGIC, RNE if nearest else RDN))   # MAGIC + (g-1)
    late = R.plant == "window"
    if late:
        R.fired.add("window")
    shift = b.iadd(gm1m, wi(P.Z + (1 if late else 0)))

    b.phase = "red-window"
    win = _window(R, shift)

    b.phase = "red-setup"
    # sigma, its powers of two (built on the encoding), and M: after the
    # window, so that they are not live across it
    gm1 = R.exact(b.sub(gm1m, MAGIC))
    sig = R.exact(b.fma(gm1, wx(-bb), G0p))             # sigma
    sigm = R.exact(b.add(sig, MAGIC))                   # MAGIC + sigma
    V = b.ishl(b.isub(sigm, wi(R.magic_bits - bias)), wi(mw))   # 2^sigma
    U = b.isub(wi((2 * bias) << mw), V)                         # 2^-sigma
    m = b.iadd(U, wi(2 << mw))                                  # 4U
    inv_m = b.isub(V, wi(2 << mw))                              # V/4
    b.probes.update(sig=sig, V=V, U=U, gm1=gm1, m=m, inv_m=inv_m)
    M = b.ior(b.iand(x, wi(fmt.man_mask)), wi((bias + p - 1) << mw))
    nM = b.ixor(M, wi(fmt.sign_mask))                   # -M, for TwoProd
    b.probes.update(M=M)
    fr.M, fr.nM, fr.U, fr.V, fr.m, fr.inv_m = M, nM, U, V, m, inv_m
    fr.sig, fr.gm1, fr.win = sig, gm1, win

    b.phase = "red-products"
    rows = {r[0]: r for r in P.rows}
    need = P.budget - 3                                 # S-hat accuracy
    prods = []
    for j in range(L):
        # the chunk scaled by 2^-(jb), exactly: one MUL, shared by the
        # product and its error
        Wj = win[j] if j == 0 else R.exact(
            b.mul(win[j], wx(Fraction(1, 2 ** (j * bb)))))
        _j, _lmin, lmax, pgrid, rhomag, rhogrid = rows[j]
        if lmax is None:
            prods.append(None)
            continue
        Pj = b.mul(M, Wj)
        if rhomag > need:                               # the low word counts
            R.two_prod()
            nrho = R.exact(b.fma(nM, Wj, Pj))           # = P - T = -rho
            rho = b.neg(nrho)
            prods.append((ReductionValue(Pj, lmax + 1e-9, pgrid),
                          ReductionValue(rho, rhomag, rhogrid)))
        else:
            prods.append((ReductionValue(Pj, lmax + 1e-9, pgrid), None))
    if prods[0] is not None:
        b.probes.update(P0=prods[0][0].ref)
    fr.prods = prods

    b.phase = "red-coarse"
    nqs = []                    # -k for every quadrant count taken out
    # A position whose chunk is zero in every bucket the range has (a range
    # below 2^p leaves position 0, and below 2^(p-b) position 1, without
    # one) contributes nothing: its pieces are left out.
    P0, rho0 = prods[0] if prods[0] is not None else (None, None)
    P1, _rho1 = prods[1] if len(prods) > 1 and prods[1] is not None \
        else (None, None)
    coarse = []
    if P0 is not None:
        coarse.append(R.mod_m(fr, P0, guard=True))
    if rho0 is not None:
        coarse.append(R.mod_m(fr, rho0))
    if P1 is not None:
        coarse.append(R.mod_m(fr, P1))
    if not coarse:
        raise ValueError("no coarse piece: the range leaves positions 0 and "
                         "1 without a chunk, and nothing fixes the quadrant")
    VI = coarse[0]
    for c in coarse[1:]:
        nxt = R.add_exact(VI, c)
        if nxt is None:
            raise ValueError(
                f"the coarse sum is not exact: 2^{VI.mag:.2f} on grid "
                f"2^{VI.grid} and 2^{c.mag:.2f} on grid 2^{c.grid} do not "
                f"fit {p} bits (b = {bb})")
        VI = nxt
    q1 = R.data(b.fma(VI.ref, V, MAGIC))                # MAGIC + round(VI/U)
    nk1 = R.exact(b.sub(MAGIC, q1))
    fI = R.exact(b.fma(nk1, U, VI.ref))                 # |fI| <= U/2
    nqs.append(nk1)
    b.probes.update(fI=fI)
    fr.coarse, fr.fI, fr.nqs = coarse, fI, nqs
    return fr


def reduction_front(b, x, P, *, plant=None):
    """The reduction's front, appended to the Build `b` for the argument ref
    `x`: the setup (red-setup), the window (red-window), the products
    (red-products) and the coarse sum (red-coarse). The reduction is of |x|.
    A types.SimpleNamespace of refs and bounds:
      M, nM        the integer significand of |x| as a float, and -M
      U, V, m, inv_m   2^-sigma, 2^sigma, 4 U and V/4 (powers of two built on
                   the encoding), the quadrant unit and the modulus
      sig, gm1     sigma and g - 1, exact floats; magic, the word MAGIC
      prods        for j < L: None where no bucket gives position j a chunk,
                   else (P_j, rho_j), ReductionValues, T_j = M c 2^-(jb) =
                   P_j - rho_j exactly; rho_j None where it is below the
                   accuracy needed
      coarse, fI   the pieces mod m and f_I, |f_I| <= U/2, exact, which is
                   (P_0 + rho_0 + P_1) mod U
      nqs          the negated quadrant counts taken out so far, [-k_1]
    What follows (trig_reduction's mid, lower, scale and small parts) is what
    a triple word would replace. A static proof that fails is a ValueError
    naming it. `plant`: one of REDUCTION_PLANTS (the front's act)."""
    if plant is not None and plant not in REDUCTION_PLANTS:
        raise ValueError(f"unknown plant {plant!r}: "
                         f"{', '.join(REDUCTION_PLANTS)}")
    return _front(_Red(b, P, plant), x)


def _tail(R, x, fr):
    b, P, fmt = R.b, R.P, R.fmt
    p, mw, bias, bb, L = R.p, R.mw, R.bias, R.bb, P.L
    wi, wx, ZERO, MAGIC = R.wi, R.wx, R.ZERO, R.magic
    U, V = fr.U, fr.V
    prods, fI, nqs = fr.prods, fr.fI, fr.nqs
    variant = "B" if R.plant == "mid_inexact" else "A"
    if variant == "B":
        R.fired.add("mid_inexact")

    b.phase = "red-mid"
    bottom = P.bottom
    MQ = b.const("MQ", _enc_exact(
        fmt, Fraction(3, 2) * Fraction(2) ** (p - 1 + bottom)))
    mids, lows = [], []

    def place(v):
        """Classify a piece against the bottom: mid, split, or lower."""
        if v is None:
            return
        if v.grid >= bottom:
            mids.append(v)
        elif v.mag < bottom:
            lows.append(v)
        else:
            if v.mag >= p - 2 + bottom:
                if R.plant != "split_unproved":
                    raise ValueError(
                        f"the split's magic is out of range: a piece of "
                        f"2^{v.mag:.2f} on grid 2^{v.grid} reaches the "
                        f"magic's 2^{p - 2 + bottom} (p - 2 + bottom) at "
                        f"the bottom 2^{bottom}")
                R.fired.add("split_unproved")
            hi = R.exact(b.sub(R.data(b.add(v.ref, MQ)), MQ))
            lo = R.exact(b.sub(v.ref, hi))
            mids.append(ReductionValue(hi, v.mag + 1e-9, bottom))
            lows.append(ReductionValue(lo, bottom, v.grid))

    rho1 = prods[1][1] if len(prods) > 1 and prods[1] is not None else None
    place(rho1)
    for j in range(2, L):
        if prods[j] is None:
            continue
        Pj, rhoj = prods[j]
        if Pj.mag >= -1:                            # may carry quadrant bits
            Pj = R.mod_m(fr, Pj)
            Pj.mag = min(Pj.mag, prods[j][0].mag)
        place(Pj)
        place(rhoj)
    # the mid pieces, summed exactly: largest first, TwoSum where a plain
    # add is not provably exact, the low words added exactly
    mids.sort(key=lambda v: -v.mag)
    if not mids:
        raise ValueError("the mid sum has no piece: nothing lies above the "
                         "bottom")
    if variant == "A":
        # largest first into (h, lw), the double word h + lw exact
        # throughout: a piece goes into the low word where that sum is
        # provably exact, else into h where that is, else by TwoSum
        h = mids[0]
        lw = None
        planted = R.plant != "exact_add"
        for v in mids[1:]:
            if lw is not None:
                s = R.add_exact(lw, v)
                if s is not None:
                    lw = s
                    continue
            s = R.add_exact(h, v)
            if s is not None:
                h = s
                continue
            if not planted:
                # the plant: a plain add where a TwoSum is needed, claimed
                planted = True
                R.fired.add("exact_add")
                h = ReductionValue(R.exact(b.add(h.ref, v.ref)),
                                   _lg(2 ** h.mag + 2 ** v.mag),
                                   min(h.grid, v.grid))
                continue
            ss, ee = b.two_sum(h.ref, v.ref)
            g = min(h.grid, v.grid)
            nh = ReductionValue(ss, _lg(2 ** h.mag + 2 ** v.mag), g)
            ev = ReductionValue(ee, nh.mag - p, g)
            h = nh
            if lw is None:
                lw = ev
            else:
                nlw = R.add_exact(lw, ev)
                if nlw is None:
                    raise ValueError(
                        f"the mid sum's low word is not exact: 2^{lw.mag:.2f}"
                        f" on grid 2^{lw.grid} and 2^{ev.mag:.2f} on grid "
                        f"2^{ev.grid} do not fit {p} bits")
                lw = nlw
        b.probes.update(mid_h=h.ref)
        mid = {"h": (h.mag, h.grid), "lw": None}
        if lw is not None:
            under = R.plant == "lw_understated"
            if under:
                R.fired.add(R.plant)
            mid["lw"] = (lw.mag - (8 if under else 0), lw.grid)
        b.meta["reduction_mid"] = mid
        # the mid sum modulo U, exactly
        q2 = R.data(b.fma(h.ref, V, MAGIC))
        nk2 = R.exact(b.sub(MAGIC, q2))
        h2 = ReductionValue(R.exact(b.fma(nk2, U, h.ref)), h.mag, h.grid)
        nqs.append(nk2)
        # fI + mid, exactly, as a double word: TwoSum, then the low words
        s, e = b.two_sum(fI, h2.ref)
        if lw is not None:
            e = R.exact(b.add(e, lw.ref))
        # the quadrant once more: |s| <= U
        q3 = R.data(b.fma(s, V, MAGIC))
        nk3 = R.exact(b.sub(MAGIC, q3))
        s3 = R.exact(b.fma(nk3, U, s))
        nqs.append(nk3)
        xh, xl = b.two_sum(s3, e)                       # exact, renormalised
    else:
        # design B (the plant mid_inexact, and only that): the mid pieces
        # join the lower ones, summed with the double-word accuracy only;
        # fI is exact
        lows = mids + lows
        xh, xl = fI, None
    b.probes.update(xh=xh)

    b.phase = "red-lower"
    lows.sort(key=lambda v: -v.mag)
    b.meta.setdefault("reduction_mid", {})["lows"] = _lg(
        sum(2 ** v.mag for v in lows))
    lh = ll = None
    need = P.budget - 3
    acc_need = need + p                     # below this a plain add is fine
    for v in lows:
        if lh is None:
            lh = v.ref
            continue
        if v.mag > acc_need:
            lh, e = b.two_sum(lh, v.ref)
            ll = e if ll is None else b.add(ll, e)
        else:
            ll = v.ref if ll is None else b.add(ll, v.ref)
    if lh is None:
        lh = ZERO
    if variant == "B":
        # B: the coarse fraction and everything else; the lower sum is a
        # double word, its quadrant bits taken out once
        s, e = b.two_sum(xh, lh)
        if ll is not None:
            e = b.add(e, ll)
        q3 = R.data(b.fma(s, V, MAGIC))
        nk3 = R.exact(b.sub(MAGIC, q3))
        s3 = R.exact(b.fma(nk3, U, s))
        nqs.append(nk3)
        th, tl = b.two_sum(s3, e)
    else:
        # A: the exact part plus the lower double word (TwoSum of the
        # highs, the lows added, Fast2Sum); the lower part is below the
        # bottom, so no cancellation it causes reaches past u^2 |t|
        s, e = b.two_sum(xh, lh)
        lo = xl if ll is None else b.add(xl, ll)
        e = b.add(e, lo)
        th, tl = R.fast(s, e)
    b.probes.update(th=th, tl=tl)

    b.phase = "red-scale"
    th = R.exact(b.mul(th, V))
    tl = R.exact(b.mul(tl, V))
    ph, pl = _words(fmt, _pi() / 2, 2)
    if R.plant == "pio2_low":
        pl = 0
        R.fired.add("pio2_low")
    PH = b.const("PIO2H", ph)
    PL = b.const("PIO2L", pl)
    rh = b.mul(th, PH)
    nre = b.fma(b.neg(th), PH, rh)                      # rh - th PH
    rl = b.fma(th, PL, b.fma(tl, PH, b.neg(nre)))
    rh, rl = R.fast(rh, rl)
    # the quadrant: n = -(sum of the -k), as MAGIC + n
    counts = nqs[:-1] if R.plant == "quadrant_dropped" else nqs
    if R.plant == "quadrant_dropped":
        R.fired.add("quadrant_dropped")
    nsum = counts[0]
    for v in counts[1:]:
        nsum = R.exact(b.add(nsum, v))
    q = R.exact(b.sub(MAGIC, nsum))                     # MAGIC + n

    b.phase = "red-small"
    # the reduction is of |x|: M carries no sign. sin and tan are odd and
    # cos even, so the routine applies x's sign with the quadrant's, to
    # the double word before its one rounding (rounding is not symmetric
    # under rdn and rup)
    ax = b.iand(x, wi(fmt.sign_mask ^ R.full))
    small = b.cmplt(ax, b.const("PIO4D", _enc(fmt, _pi() / 4, RDN)))
    rh = b.sel(ax, rh, small)
    rl = b.sel(ZERO, rl, small)
    q = b.sel(MAGIC, q, small)
    b.probes.update(rh=rh, rl=rl, q=q, small=small)
    inrange = None
    if P.R is not None:
        b.phase = "classify"
        Rbits = _pow2(fmt, P.R - 1 if R.plant == "range_short" else P.R)
        if R.plant == "range_short":
            R.fired.add("range_short")
        inrange = b.icmplt(ax, b.const("RANGE", Rbits))
        b.probes.update(inrange=inrange)
    return types.SimpleNamespace(rh=rh, rl=rl, q=q, small=small,
                                 inrange=inrange)


def trig_reduction(b, x, P, *, plant=None):
    """The trigonometric reduction appended to the Build `b` for the
    argument ref `x` (straight-line ALU instructions, bank words only, no
    scratch slot; RNE, and RDN for the bucket's floor), under the plan P of
    plan_reduction(). -> types.SimpleNamespace(rh, rl, q, small, inrange).
    For every x with 2^Egate <= |x| < 2^R (P.Egate, P.R):
      * r = rh + rl with |r - (|x| - n pi/2)| <= 2^-(p+G+3) |r| and
        rh = RN(rh + rl);
      * |r| <= pi/4 (1 + 2^-30) at fp64, fp128 and fp256, but only
        pi/4 (1 + 2^-11) at fp32 (G = 18). The third quadrant count rounds
        the high word of the exact sum alone, and what it does not see - that
        sum's rounding error (2^-p of U), the mid sum's low word lw and the
        pieces below the bottom - can carry |r| past pi/4: with U >= 1/2,
        2 |t| - 1 <= 2^(1-p) + 4 (|lw| + |lower|), COMPUTED from the static
        bounds in Build.meta["reduction_mid"]: 2^-11.66 at fp32, 2^-33.04 at
        fp64, 2^-64.0 at fp128 and 2^-62.0 at fp256 (fp128 and fp256 have no
        lw);
      * n mod 4 is q's encoding & 3, q = MAGIC + n;
      * `small` is nonzero where |x| < RD(pi/4); there rh = |x|, rl = +0 and
        q = MAGIC;
      * `inrange` is None where R is None, else nonzero exactly where
        |x| < 2^R (one ICMPLT, in the phase "classify", which PHASE_ORDER
        has between "final" and "special"); the caller marks the lane where
        it is zero;
      * the reduction is of |x|: the caller applies x's sign.
    Below 2^Egate, at zero, infinities and NaNs, and past 2^R, the values mean
    nothing: the caller's paths take those lanes.
    Phases red-setup, red-window, red-products, red-coarse, red-mid,
    red-lower, red-scale and red-small (b.phase is restored at the end).
    Probes: rh, rl, q, small, sig, U, V, fI, xh, th, tl, and gm1, m, inv_m,
    M, P0, mid_h, inrange. Build.meta gains "exact" and "data" (the claims),
    "two_prod", "reduction" (the plan) and "reduction_mid" (the bounds
    above). A static proof that fails is a ValueError naming it. `plant`:
    one of REDUCTION_PLANTS; one that could not act is refused."""
    if plant is not None and plant not in REDUCTION_PLANTS:
        raise ValueError(f"unknown plant {plant!r}: "
                         f"{', '.join(REDUCTION_PLANTS)}")
    R = _Red(b, P, plant)
    entry = b.phase
    out = _tail(R, x, _front(R, x))
    b.phase = entry
    R.check_fired()
    return out


def _main_lane(fmt, P, x):
    """x is a finite normal argument with 2^Egate <= |x| < 2^R."""
    ef = (x >> fmt.man_w) & fmt.exp_mask
    if ef == 0 or ef == fmt.exp_mask:
        return False
    return P.Egate <= ef - fmt.bias <= P.Emax


def reduction_audit(b, x, *, tally=None):
    """[(index, opcode name, phase)]: every instruction the build `b` of
    trig_reduction() claims exact (Build.meta["exact"]) whose result is not
    the exact operation on its operands' exact values, on the lane x (the
    argument's bits); empty when every claim holds. Stricter than the
    model's, which skipped a lane with a non-finite operand and every opcode
    but ADD, SUB, MUL and FMA without a word: a claim on any other opcode is
    REPORTED (it cannot be audited), as is, on a main lane (a finite x with
    2^Egate <= |x| < 2^R), a claimed instruction with a non-finite operand
    or result. On a lane that is not main (zero, an infinity or NaN, below
    2^Egate, 2^R and above) the claims are not asserted, since the values mean
    nothing there; they are counted. `tally`, a dict, gains "claims" (examined,
    skipped ones included), "nonfinite" (reported on a main lane) and
    "skipped" (not asserted, the lane not being main)."""
    if b.meta.get("reduction") is None:
        raise ValueError("the build holds no trig_reduction()")
    return _audit_values(b, x, _values(b.fmt, b.body, b.words, x), tally)


def _audit_values(b, x, vals, tally):
    """reduction_audit() on the lane whose instruction values are `vals`
    (_values of the unpruned body), so that a test that has them runs the
    lane once."""
    fmt, P = b.fmt, b.meta["reduction"]
    get = _getter(vals, b.words, x)
    main = _main_lane(fmt, P, x)
    t = tally if tally is not None else {}
    for k in ("claims", "nonfinite", "skipped"):
        t.setdefault(k, 0)
    bad = []
    for ref in sorted(b.meta.get("exact", ())):
        i = ref[1]
        op, _r, srcs = b.body[i]
        t["claims"] += 1
        if op not in _AUDITED:
            bad.append((i, sf.OP_NAMES[op], b.phase_of[i]))
            continue
        if not main:
            t["skipped"] += 1
            continue
        try:
            a = [_dec(fmt, get(s)) for s in srcs]
            got = _dec(fmt, vals[i])
        except ValueError:
            t["nonfinite"] += 1
            bad.append((i, sf.OP_NAMES[op], b.phase_of[i]))
            continue
        if op == sf.OP_ADD:
            want = a[0] + a[1]
        elif op == sf.OP_SUB:
            want = a[0] - a[1]
        elif op == sf.OP_MUL:
            want = a[0] * a[1]
        else:
            want = a[0] * a[1] + a[2]
        if got != want:
            bad.append((i, sf.OP_NAMES[op], b.phase_of[i]))
    return bad


def build_reduction(fmt, rnd=RNE, *, G=None, R="default", plant=None):
    """The reduction alone, for tests: a Build whose result is r_h and whose
    flags are q (not a flag word: Build.run() reads them, nothing compiles
    it). `fmt` is one of the four, `rnd` the program's attribute (recorded and
    used by nothing here: the reduction is RNE, and RDN for the bucket's
    floor), `G` the guard (GUARD's, 40 at fp32, which is refused by name: fp32
    must be given G = 18, the double word's), `R` as plan_reduction()'s,
    `plant` one of REDUCTION_PLANTS. The probes are trig_reduction()'s; the
    lane's other values are in the unpruned body; Build.meta is
    trig_reduction()'s, with fn "reduction", G and R."""
    if fmt not in FORMATS:
        raise ValueError(f"{fmt!r} is not one of the four formats")
    if rnd not in sf.RND_NAMES:
        raise ValueError(f"rounding attribute {rnd!r} is not one of the five")
    if plant is not None and plant not in REDUCTION_PLANTS:
        raise ValueError(f"unknown plant {plant!r}: "
                         f"{', '.join(REDUCTION_PLANTS)}")
    G = GUARD[fmt.name] if G is None else G
    P = plan_reduction(fmt, G, R=R)
    b = Build(fmt, rnd, f"reduction-{fmt.name}-{sf.RND_NAMES[rnd]}")
    b.meta.update(fn="reduction", G=G, R=P.R, reduction_plant=plant)
    out = trig_reduction(b, ("in", "a"), P, plant=plant)
    return b.finish(out.rh, out.q)


# ---- what is proved of every fragment ---------------------------------------
#
# C4's routines.invariants() held a division's and a root's fragments; the
# study (section 6, question 12) found four ways it fails these, and Logan's
# answer widens them. From parcel E1 this module held ITS fragments to the
# widened form, here, while routines.py kept C4's for division and root. M1's
# build, item 4, moved the widened form into routines.py: one statement for
# the eight routines, per routine (routines.CONTRACT, routines.LIVE_CAP), the
# six's this module's form and division's and root's C4's, not loosened -
# and cftc's internal check holds every routine of an image to it. What
# follows are VIEWS of it, under the names this module's tests and callers
# have always read: FLAG_WORDS, LIVE_CAP (by format), flag_words() and
# invariants().

# The values a flag word can take: C4's six, and inexact, overflow with
# inexact and underflow with inexact each with the mark. Never bits [6:5].
FLAG_WORDS = routines.MARKED_FLAG_WORDS

# The most values a fragment may keep live at once, by format: the most any
# of the six routines keeps under any of the five attributes, in the order
# the scheduler gives (MEASURED, parcels MB1 and MB2; SHAPE in
# test_mathlib.py pins each routine's exact count). In the design's own order
# the exp family at the double word keeps 22 to 25 live and at fp32's triple
# word 33 to 36 - past seq.py's 32 registers, so that routines.program refused
# fp32's exp ("no register for the harness"); the log family keeps 14 to 18
# at the double word and 21 to 24 at fp32, which fit. Scheduled they keep
#
#           fp32      fp64, fp128, fp256
#   exp      19            11
#   exp2     20            13
#   expm1    21            13
#   log      19            13
#   log2     17            13
#   log1p    20            12
#
# and the cap is the largest of each column, because that is what the design
# measures, so a growth is a change to look at. The log family needed no more
# than the exp family's: its maxima, 19, 17 and 20 at fp32 and 13, 13 and 12
# at the double word, are under the cap, so the cap is by format as MB1 set
# it, not by function and format. It leaves NREG - cap of
# seq.py's 32 registers for the program's own values across a call - 11 at
# fp32, 19 at the double word's formats - which the compiler's allocator
# spills when it must (C4's allocator does so around any routine). The caps
# are not a minimum: the scheduler is two cheap heuristics, and the triple
# word's state (the three words of y and of the running sums, with the
# table's, the reduction's and the sum's terms) is itself most of fp32's 17
# to 21. Since M1's build, item 4, the caps are stated in routines.LIVE_CAP,
# by routine and format, each of the six at these values; this is its view
# by format, the largest of the six's at each.
LIVE_CAP = {fmt.name: max(routines.LIVE_CAP[name][fmt.name] for name in NAMES)
            for fmt in FORMATS}
_BY_FORMAT = object()            # invariants()'s default cap: LIVE_CAP's

# The walk of the flag word's values, with its IOR rule: routines.py's, the
# one walk for every routine since M1's build, item 4 (C4's walk had no IOR
# rule, so it could not see through the instruction that ORs the mark in).
flag_words = routines.flag_words


def invariants(f, live_cap=_BY_FORMAT):
    """[str]: what does not hold of the fragment, empty when all does - the
    six's statement, routines.invariants() under routines.MATH_CONTRACT,
    each clause by name:

      * well formed: values read only after they are defined, the words
        named exist and are encodings at the format, each opcode takes its
        operands, the result and the flag word are values;
      * the flag word's values, by flag_words(), within FLAG_WORDS: never
        bits [6:5], the mark only with inexact (an IOR rule in the walk);
      * at most `live_cap` values live at once (LIVE_CAP's, by default;
        None for no cap);
      * every instruction reading a word or an internal value, so none can
        be a language node's (cftc/inline.py's argument);
      * nothing left to simplify (routines.simplify), once specialised;
      * the attributes the routine's own: RNE, RTZ, RDN, RUP and the
        PROGRAM's (f.rnd), and none where an opcode does not round.

    It holds the fragment to the six's statement whatever routine it names,
    so that a study's fragment is held to it too (docs/studies/m2/
    costs.py's sin, cos and tan); for one of the six that is exactly
    routines.invariants(f), its routine's own, since routines.CONTRACT
    names MATH_CONTRACT for each and their caps are LIVE_CAP's at every
    format. C4's invariants, division's and root's still, admit RNE and RTZ
    only, cap the live count at 16 and allow no mark, which is how the
    study measured them failing these."""
    if live_cap is _BY_FORMAT:
        live_cap = LIVE_CAP.get(f.fmt.name)
    return routines.invariants(f, live_cap=live_cap,
                               contract=routines.MATH_CONTRACT)


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
        f = build(name, fmt, rnd).fragment()
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


def _show(v):
    """A rational for a message: 17 digits, or 2^k where it is too large for
    a float (a power of two of fp128 or fp256, as the range word is)."""
    try:
        return f"{float(v):.17g}"
    except OverflowError:
        return f"~2^{v.numerator.bit_length() - v.denominator.bit_length()}"


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
        if w == 0:
            # zero has no leading bit: it is the truncation of 0 alone (a
            # word dropped, as the log family's defect 2, is not one)
            ok = lo == hi == 0
        else:
            ok = (sig <= nbits and w <= lo
                  and hi < w + Fraction(2) ** (e - nbits + 1))
    else:
        raise ValueError(rule)
    if ok:
        return None
    return (f"{bits:#x} = {_show(w)} is not the {rule} rounding of "
            f"[{_show(lo)}, {_show(hi)}]")


def _check_scale(b: Build, findings):
    """The scale offsets, the fixed grid's words (exp, exp2), 2^-k and its
    clamp (expm1), the exactness of exp2's reduction and the table's wiring,
    where they act: lanes x = n ln2/8 (x = n/8 at exp2) over the range of k,
    each run through the unpruned body, its probes against exact values.
    -> lanes run."""
    fmt, p, mw = b.fmt, b.fmt.prec, b.fmt.man_w
    fn = b.meta["fn"]
    OFF = b.meta["OFF"]
    ks = [fmt.emin - p - 2, fmt.emin - 2, fmt.emin - 1, fmt.emin,
          fmt.emin + 1, fmt.emin + p, -2, -1, 0, 1, 2, fmt.emax - 1,
          fmt.emax, fmt.emax + 1]
    if fn == "expm1":
        # 2^-k and where it is taken as 0: the design's last k is p + G + 2
        clamp = p + b.meta["G"] + 2
        ks += [-(p + 3), -(p + 2), -(p + 1), p, p + 1, clamp - 2, clamp - 1,
               clamp, clamp + 1, clamp + 2, clamp + 4]
    ns = [8 * k + j for k in ks for j in (0, 3, 5, 7)]
    ns += [8 * k + 1 for k in range(-9, 10, 3)]
    l2 = _check_ln2()[0]
    tw = fmt.name == "fp32"
    ran = 0
    for n in ns:
        x = _enc_exact(fmt, Fraction(n, N)) if fn == "exp2" \
            else _enc(fmt, Fraction(n) * l2 / N)
        want = ["nf", "Ek", "S1", "S2", "rp"]
        want += ["NPK"] if fn == "expm1" else ["sub_p", "klt", "Cu", "hu"]
        want += ["T0", "T1", "T2"] if tw else ["Th", "Tl"]
        _res, _fl, pr = b.run(x, want)
        got_n = _dec(fmt, pr["nf"])
        if got_n.denominator != 1 or abs(got_n - n) > 1:
            findings.append(f"{fn} {fmt.name} {sf.RND_NAMES[b.rnd]}: n = {n} "
                            f"was reduced to {got_n}")
            continue
        n_ = int(got_n)
        k, j = n_ // N, n_ % N
        ran += 1
        where = f"{fn} {fmt.name} {sf.RND_NAMES[b.rnd]} n = {n_} (k = {k})"
        if pr["Ek"] != k + fmt.bias + OFF:
            findings.append(f"{where}: Ek = {pr['Ek']}, want "
                            f"{k + fmt.bias + OFF}")
        for nm, kk in (("S1", k // 2), ("S2", k - k // 2)):
            u = sf.unpack(fmt, pr[nm])
            if (u.kind != sf.NORM or u.sign or u.m != 1 << mw
                    or u.e + mw != kk):
                findings.append(f"{where}: {nm} = {pr[nm]:#x} is not 2^{kk}")
        if fn == "exp2" and pr["rp"] != 0:
            findings.append(f"{where}: x = n/8, and the remainder is "
                            f"{pr['rp']:#x}, not 0")
        if fn == "expm1":
            if k >= -(p + 4):
                two = Fraction(0) if k > clamp else Fraction(2) ** (-k)
                if _dec(fmt, pr["NPK"]) != two:
                    what = "0 (past the clamp)" if two == 0 else two
                    findings.append(f"{where}: 2^-k is {pr['NPK']:#x}, want "
                                    f"{what}")
        else:
            for nm, truth in (("sub_p", k <= fmt.emin), ("klt", k < fmt.emin)):
                if (pr[nm] == sf.one_bits(fmt)) != truth or pr[nm] not in (
                        0, sf.one_bits(fmt)):
                    findings.append(f"{where}: {nm} = {pr[nm]:#x}, want "
                                    f"{truth}")
            if k <= fmt.emin:
                cu = Fraction(2) ** (fmt.emin - k) if k < fmt.emin \
                    else Fraction(1, 16)
                if _dec(fmt, pr["Cu"]) != cu:
                    findings.append(f"{where}: Cu is not {cu}")
                if "hu" in pr and _dec(fmt, pr["hu"]) != \
                        Fraction(2) ** (fmt.emin - p - k):
                    findings.append(f"{where}: u/2 is not "
                                    f"2^{fmt.emin - p - k}")
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


def _check_plan(fmt, family, G, l2hi, rel_z=False):
    """The plan again, from the independent ln 2: (K, D) or (K3, K2, D),
    the smallest satisfying the study's conditions (plan_exp, plan_exp32);
    `rel_z` for expm1's, bounded relative to Z."""
    p = fmt.prec
    rho = (Fraction(1, 2) + Fraction(1, 2 ** _cushion(fmt))) * l2hi / N
    fact = math.factorial
    extra = 0 if rel_z else 1
    if family == "triple word":
        def fits(i, bits):
            return rho ** (i + extra) * 2 / fact(i + 1) <= \
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
        return 2 * u * rho ** (K + extra) / fact(K + 1)

    def trunc(D):
        return rho ** (D + 1 + extra) / fact(D + 2) * (1 + rho)
    K = next(k for k in range(1, 60) if tail(k) <= target / 2)
    D = next(d for d in range(K, 150)
             if tail(K) + trunc(d) + 10 * u * u <= target)
    return (K, D)


def _verifier(b: Build, findings):
    """(tag, verify, point, seen, count) for one built routine: verify(role,
    rule, lo, hi, nbits, negated) checks the constant `role` as the built
    fragment holds it (negated: the held word is the constant's negation)
    against the rounding `rule` of the enclosure [lo, hi] and returns its
    value, for the next word; point(role, value) is the exact rule. `seen`
    collects the roles asked, `count[0]` counts them."""
    fmt = b.fmt
    tag = f"{b.meta['fn']} {fmt.name} {sf.RND_NAMES[b.rnd]}"
    seen = set()
    count = [0]

    def verify(role, rule, lo, hi, nbits=None, negated=False):
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
    return tag, verify, point, seen, count


def _check_build(b: Build, findings):
    """Every derived constant of one built routine, against its independent
    derivation, and the scale words where they act. -> (constants checked,
    lanes run)."""
    fmt, p = b.fmt, b.fmt.prec
    fn = b.meta["fn"]
    tw = b.meta["family"] == "triple word"
    G = b.meta["G"]
    tag, verify, point, seen, count = _verifier(b, findings)

    l2lo, l2hi = _check_ln2()
    nb = _n_width(fmt)
    plan = _check_plan(fmt, b.meta["family"], G, l2hi, fn == "expm1")
    held_plan = ((b.meta["K3"], b.meta["K2"], b.meta["D"]) if tw
                 else (b.meta["K"], b.meta["D"]))
    if plan != held_plan:
        findings.append(f"{tag}: the plan {held_plan} is not the re-derived "
                        f"{plan}")
    point("MAGIC", Fraction(3, 2) * 2 ** (p - 1))
    if fn == "exp2":
        # n = round(8x), r' = x - n/8: 8 and -1/8 exact; r = r' ln 2 from
        # ln 2's nearest words, each the nearest to what the ones before leave
        point("EIGHT", N)
        point("NINV8", Fraction(-1, N))
        if tw:
            w0 = verify("LN2_0", "rn", l2lo, l2hi)
            w1 = verify("LN2_1", "rn", l2lo - w0, l2hi - w0)
            verify("LN2_2", "rn", l2lo - w0 - w1, l2hi - w0 - w1)
            point("NLN2_0", w0, negated=True)
            point("NLN2_1", w1, negated=True)
        else:
            w0 = verify("LN2H", "rn", l2lo, l2hi)
            point("NLN2H", w0, negated=True)
            verify("NLN2L", "rn", l2lo - w0, l2hi - w0, negated=True)
    else:
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
    # the screens, by the rounding direction that makes each one safe; exp2's
    # are integers
    if fn == "exp2":
        point("XOVF", fmt.emax + 1)
        point("XUNF", fmt.emin - p)
    else:
        verify("XOVF", "ru", (fmt.emax + 1) * l2lo, (fmt.emax + 1) * l2hi)
    if fn == "exp":
        verify("XUNF", "rd", (fmt.emin - p) * l2hi, (fmt.emin - p) * l2lo)
    if fn == "expm1":
        # -(p+2) ln 2 is negative: the enclosure's ends swap
        verify("XM1", "rd", -(p + 2) * l2hi, -(p + 2) * l2lo)
        point("TINYM1", Fraction(2) ** -(p + 2))
        point("MINN", Fraction(2) ** fmt.emin)
        if b.rnd in (RTZ, RUP):
            point("NMINN", -(Fraction(2) ** fmt.emin))
    else:
        point("TINYX", Fraction(2) ** -(p + 3))
        point("C0", Fraction(1, 16))
    point("BREL", Fraction(2) ** -(p + G) * 2 ** b.meta["shift"])
    if tw:
        point("HALF", Fraction(1, 2))
    # the answers of the screens under the program's attribute (754 7.4): a
    # quarter of the smallest subnormal, rounded; a number past the largest;
    # for expm1 -1 less 2^-(p+3), rounded
    if fn == "expm1":
        point("M1B", Fraction(-1) if b.rnd in (RNE, RMM, RDN)
              else -(1 - Fraction(1, 2 ** p)))
    else:
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


# ---- the log family's constants, checked ------------------------------------
#
# The same way as the exp family's, with these enclosures (integer arithmetic,
# nothing shared with the generator or with mpmath):
#
#   log(16/C)   2 atanh((16 - C)/(16 + C)) = 2 sum t^(2k+1)/(2k+1), floors of
#               2^3200 over each term, the loss counted: width 2^-3190
#   1/ln 2      the reciprocal of ln 2's enclosure
#   RECIP_SEED  each of the 512 cells' table entry from its definition (the
#               nearest integer to 2^18/(1 + (i + 1/2)/2^9)), read again from
#               the instruction itself at the cell's two ends, then C, c, the
#               wrap and max |r| over the cells, exactly
#   the plan    (K, D) or (K3, K2, D) again, from RHO_LOG, itself held to the
#               cells' max |r|

@functools.lru_cache(maxsize=None)
def _check_log16(C):
    """(lo, hi): log(16/C) enclosed, C = 9 to 16, from the atanh series in
    integers; (0, 0) at C = 16."""
    if C == 16:
        return Fraction(0), Fraction(0)
    bits = 3200
    one = 1 << bits
    n, d = 16 - C, 16 + C
    total, k, pn, pd = 0, 0, n, d
    while True:
        t = (one * pn) // (pd * (2 * k + 1))
        if t == 0:
            break
        total += t
        k += 1
        pn *= n * n
        pd *= d * d
    return Fraction(2 * total, one), Fraction(2 * (total + k + 2), one)


@functools.lru_cache(maxsize=None)
def _check_inv_ln2():
    """(lo, hi): 1/ln 2 enclosed, from ln 2's."""
    lo, hi = _check_ln2()
    return 1 / hi, 1 / lo


def _seed_entry(i):
    """RECIP_SEED's table entry for the mantissa cell i, again from its
    definition (softfloat.py): the nearest integer to 2^18/(1 + (i + 1/2)/2^9),
    a tie to even, in integers. The seed of m in cell i is entry / 2^18."""
    den = (1 << 10) + 2 * i + 1
    q, r = divmod(1 << 28, den)
    if 2 * r > den or (2 * r == den and q & 1):
        q += 1
    return q


def _seed_C(i, entry=_seed_entry):
    """C = round(16 seed) for the cell i, by the magic-number FMA's rounding
    (nearest, a tie to even): entry/2^14 rounded."""
    q, r = divmod(entry(i), 1 << 14)
    if 2 * r > (1 << 14) or (2 * r == (1 << 14) and q & 1):
        q += 1
    return q


_CELLS = {}                      # the default table's cells, by format


def _check_recip_cells(fmt: FpFormat, entry=_seed_entry):
    """(findings, max |r|, the set of C): over all 512 cells of RECIP_SEED at
    `fmt`, from the definition of the table (`entry`, which a test can fault):
    the instruction gives the table's value at both ends of the cell
    (softfloat.recip_seed on the cell's lowest and highest mantissa), C is 8
    to 16, and r = m' c - 1 (c = C/16, or m' = m/2 and c = 1 where C = 8
    wraps) has |r| at most RHO_LOG at both ends of every cell, with
    SMALL_LOG under it too; max |r| is returned exactly. r is a multiple of
    2^-(p+3) under 2^-4.08, so it holds p - 1 bits and the FMA is exact."""
    if entry is _seed_entry:
        if fmt.name not in _CELLS:
            _CELLS[fmt.name] = _check_recip_cells(fmt, lambda i: _seed_entry(i))
        return _CELLS[fmt.name]
    p = fmt.prec
    out, cs, rmax = [], set(), Fraction(0)
    ulp = Fraction(1, 2 ** (p - 1))
    for i in range(512):
        C = _seed_C(i, entry)
        cs.add(C)
        lo_m = 1 + Fraction(i, 512)
        hi_m = 1 + Fraction(i + 1, 512) - ulp
        for m in (lo_m, hi_m):
            got = sf.recip_seed(fmt, _enc(fmt, m))[0]
            want = Fraction(entry(i), 1 << 18)
            if _dec(fmt, got) != want:
                out.append(f"RECIP_SEED at {fmt.name}: the cell {i} gives "
                           f"{float(_dec(fmt, got))!r}, the table "
                           f"{float(want)!r}")
                break
        if not 8 <= C <= 16:
            out.append(f"RECIP_SEED at {fmt.name}: the cell {i} gives C = {C}, "
                       f"outside 8 to 16")
            continue
        for m in (lo_m, hi_m):
            r = abs((m / 2) * 1 - 1) if C == 8 else abs(m * Fraction(C, 16) - 1)
            rmax = max(rmax, r)
    if rmax > RHO_LOG:
        out.append(f"RECIP_SEED at {fmt.name}: max |r| = {float(rmax)!r} is "
                   f"past RHO_LOG = {float(RHO_LOG)!r}")
    if SMALL_LOG > RHO_LOG:
        out.append(f"SMALL_LOG = {float(SMALL_LOG)!r} is past RHO_LOG")
    return out, rmax, cs


def _check_plan_log(fmt: FpFormat, family, G):
    """The plan again: (K, D) or (K3, K2, D), the smallest satisfying the
    conditions of plan_log and plan_log32, from RHO_LOG."""
    p = fmt.prec
    rho = RHO_LOG
    if family == "triple word":
        def fits(i, bits):
            return rho ** i * 2 / (i + 1) <= Fraction(2) ** (bits - (p + G + 2))
        D = next(d for d in range(1, 150)
                 if rho ** (d + 1) / ((d + 2) * (1 - rho)) <=
                 Fraction(1, 2 ** (p + G + 3)))
        K3 = next(i for i in range(60) if fits(i, 2 * p - 2))
        K23 = next(i for i in range(K3, 80) if fits(i, p - 2))
        return (K3, K23 - K3, D)
    u = Fraction(1, 2 ** p)
    target = Fraction(1, 2 ** (p + G + 2))

    def tail(K):
        return 2 * u * rho ** K / (K + 1)

    def trunc(D):
        return rho ** (D + 1) / ((D + 2) * (1 - rho))
    K = next(k for k in range(1, 60) if tail(k) <= target / 2)
    D = next(d for d in range(K, 200)
             if tail(K) + trunc(d) + 12 * u * u <= target)
    return (K, D)


def _floor_log2(v):
    """floor(log2 v) for a positive Fraction, exactly."""
    e = v.numerator.bit_length() - v.denominator.bit_length()
    while Fraction(2) ** e > v:
        e -= 1
    while Fraction(2) ** (e + 1) <= v:
        e += 1
    return e


def _log_scale_lanes(fmt: FpFormat, fn, G):
    """The arguments the reduction's integer words are checked on: x = m 2^E
    for the mantissas at which C changes (the first and last float of each
    run of cells, from the table), 1, 1 + ulp and 2 - ulp, at exponents from
    the smallest subnormal's to the largest normal's (log, log2: the
    subnormal ones are scaled by 2^p); log1p: x = +-m 2^E and u - 1 for
    u = m 2^E, with the exponents at the r = x path's end, the tiny path's
    and 2^-k's clamp."""
    p, mw = fmt.prec, fmt.man_w
    ulp = Fraction(1, 2 ** (p - 1))
    ms = {Fraction(1), 1 + ulp, Fraction(3, 2), 2 - ulp}
    prev = None
    for i in range(512):
        C = _seed_C(i)
        if C != prev:
            ms.add(1 + Fraction(i, 512))
            if i:
                ms.add(1 + Fraction(i, 512) - ulp)
        prev = C
    ms = sorted(ms)
    xs = set()
    if fn != "log1p":
        es = [fmt.emin - mw, fmt.emin - mw + 3, fmt.emin - mw // 2,
              fmt.emin - 1, fmt.emin, fmt.emin + 1, -1, 0, 1, p, fmt.emax - 1,
              fmt.emax]
        for e in es:
            for m in ms:
                xs.add(_enc(fmt, m * Fraction(2) ** e))
    else:
        clamp = p + G + 2
        es = [-(p + 3), -(p + 2), -(p + 1), -5, -4, -3, -2, -1, 0, 1, 2, p,
              clamp - 1, clamp, clamp + 1, clamp + 2, fmt.emax - 1, fmt.emax]
        for e in es:
            for m in ms:
                v = m * Fraction(2) ** e
                for s in (1, -1):
                    xs.add(_enc(fmt, s * v))
                if -2 <= e <= p:
                    xs.add(_enc(fmt, v - 1))
        for s in (1, -1):
            edge = _enc(fmt, s * SMALL_LOG)
            xs.update(edge + d for d in (-1, 0, 1))
    return sorted(x for x in xs
                  if sf.unpack(fmt, x).kind in (sf.NORM, sf.SUB)
                  and x != fmt.sign_mask)


def _check_log_scale(b: Build, findings):
    """The log family's reduction where it acts: the integer words (the
    exponent offsets, the wrap compare, the 2^-k word and its clamp) cannot be
    rounded reals, so lanes are run through the UNPRUNED body and its probes
    compared with exact values: C and t = MAGIC + C, c, r = m' c - 1 and k as
    floats, the table words read for j = C mod 8, and, for log1p, 1 + x = u_h +
    u_l, 2^-k (0 past the clamp) and the r = x path's selection. C comes from
    the table of _seed_entry, not from the instruction under test. -> lanes
    run."""
    fmt, p = b.fmt, b.fmt.prec
    fn, G = b.meta["fn"], b.meta["G"]
    tw = b.meta["family"] == "triple word"
    where = f"{fn} {fmt.name} {sf.RND_NAMES[b.rnd]}"
    magic = Fraction(3, 2) * 2 ** (p - 1)
    clamp = p + G + 2
    want = ["tc", "cc", "r", "kf"] + (["L0", "L1", "L2"] if tw
                                      else ["Lh", "Ll"])
    if fn == "log1p":
        want += ["uh", "ul", "p2mk", "r_used", "kf_used", "small"]
    ran = 0
    for x in _log_scale_lanes(fmt, fn, G):
        xv = _dec(fmt, x)
        if fn == "log1p":
            u = 1 + xv
            if u <= 0:
                continue
            uh_bits = _enc(fmt, u)
            m_src = _dec(fmt, uh_bits)
        else:
            if xv <= 0:
                continue
            m_src = xv
        e = _floor_log2(m_src)
        m = m_src / Fraction(2) ** e
        cell = int((m - 1) * 512)
        C = _seed_C(cell)
        wrap = C == 8
        mp_, c_eff = (m / 2, Fraction(1)) if wrap else (m, Fraction(C, 16))
        r_exp = mp_ * c_eff - 1
        k_exp = e + (1 if wrap else 0)
        j = C % 8
        _res, _fl, pr = b.run(x, want)
        ran += 1
        at = f"{where} x = {x:#x}"

        def val(name):
            """The probe's exact value, or its bits as a string where it is
            not a finite number (a faulted build can make one)."""
            try:
                return _dec(fmt, pr[name])
            except ValueError:
                return f"{pr[name]:#x} (not finite)"

        def show(v):
            return f"{float(v)!r}" if isinstance(v, Fraction) else v

        def differs(what, name, exp):
            got = val(name)
            if got != exp:
                findings.append(f"{at}: {what} is "
                                f"{show(got if name != 'tc' else got - magic)}"
                                f", want {show(exp - magic if name == 'tc' else exp)}")
        differs("t - MAGIC (C)", "tc", magic + C)
        differs("c", "cc", c_eff)
        differs("r", "r", r_exp)
        differs("k", "kf", k_exp)
        names = (("L0", f"L{j}_0"), ("L1", f"L{j}_1"), ("L2", f"L{j}_2")) if tw \
            else (("Lh", f"LH{j}"), ("Ll", f"LL{j}"))
        for probe, role in names:
            if pr[probe] != b.words[b.roles[role][1]]:
                findings.append(f"{at}: the table's word {probe} for j = {j} "
                                f"is {pr[probe]:#x}, not {role}")
        if fn == "log1p":
            differs("u_h of 1 + x", "uh", m_src)
            differs("u_l of 1 + x", "ul", u - m_src)
            differs("2^-k", "p2mk",
                    Fraction(0) if k_exp > clamp else Fraction(2) ** -k_exp)
            small = abs(xv) < SMALL_LOG
            if (pr["small"] != 0) != small:
                findings.append(f"{at}: the r = x path's flag is "
                                f"{pr['small'] != 0}, want {small}")
            differs("the r used", "r_used", xv if small else r_exp)
            differs("the k used", "kf_used", 0 if small else k_exp)
    return ran


def _check_build_log(b: Build, findings, lanes=True):
    """Every derived constant of one built log, log2 or log1p, against its
    independent derivation, the plan, the seed table's cells, and, with
    `lanes`, the reduction's words where they act (they do not depend on the
    attribute, so check_constants runs the lanes for the first only).
    -> (constants checked, lanes run)."""
    fmt, p = b.fmt, b.fmt.prec
    fn = b.meta["fn"]
    tw = b.meta["family"] == "triple word"
    G = b.meta["G"]
    tag, verify, point, seen, count = _verifier(b, findings)

    plan = _check_plan_log(fmt, b.meta["family"], G)
    held_plan = ((b.meta["K3"], b.meta["K2"], b.meta["D"]) if tw
                 else (b.meta["K"], b.meta["D"]))
    if plan != held_plan:
        findings.append(f"{tag}: the plan {held_plan} is not the re-derived "
                        f"{plan}")
    magic = Fraction(3, 2) * 2 ** (p - 1)
    point("MAGIC", magic)
    point("SIXTEEN", 16)
    point("SIXTEENTH", Fraction(1, 16))
    point("NMAGIC16", -magic / 16)
    point("HALF", Fraction(1, 2))
    point("NEGONE", -1)
    point("MINN", Fraction(2) ** fmt.emin)
    if fn != "log1p":
        point("P2P", Fraction(2) ** p)
    # the table: log(16/C_j), each word the nearest to what the ones before
    # leave
    nwords = 3 if tw else 2
    for j in range(N):
        lo, hi = _check_log16(16 if j == 0 else 8 + j)
        for i in range(nwords):
            role = f"L{j}_{i}" if tw else ("LH" if i == 0 else "LL") + str(j)
            w = verify(role, "rn", lo, hi)
            lo, hi = lo - w, hi - w
    # the coefficients (-1)^i/(i+1): exact, then rounded word by word
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
        left = Fraction((-1) ** i, i + 1)
        for role in roles:
            left -= verify(role, "rn", left, left)
    # ln 2 (log, log1p) or 1/ln 2 (log2)
    if fn == "log2":
        lo, hi = _check_inv_ln2()
        if tw:
            w0 = verify("IL2_0", "rn", lo, hi)
            w1 = verify("IL2_1", "rn", lo - w0, hi - w0)
            verify("IL2_2", "rn", lo - w0 - w1, hi - w0 - w1)
            point("NIL2_0", w0, negated=True)
            point("NIL2_1", w1, negated=True)
        else:
            w0 = verify("IL2H", "rn", lo, hi)
            point("NIL2H", w0, negated=True)
            verify("NIL2L", "rn", lo - w0, hi - w0, negated=True)
    else:
        lo, hi = _check_ln2()
        if tw:
            w0 = verify("LN2_0", "rn", lo, hi)
            w1 = verify("LN2_1", "rn", lo - w0, hi - w0)
            verify("LN2_2", "rn", lo - w0 - w1, hi - w0 - w1)
            point("NLN2_0", w0, negated=True)
            point("NLN2_1", w1, negated=True)
        else:
            nk = _k_width(fmt)
            w0 = verify("LN2H", "trunc", lo, hi, nbits=p - nk)
            lo, hi = lo - w0, hi - w0
            w1 = verify("LN2M", "trunc", lo, hi, nbits=p - nk)
            verify("LN2L", "rn", lo - w1, hi - w1)
    if fn == "log1p":
        point("SMALL", SMALL_LOG)
        point("TINY", Fraction(2) ** -(p + 2))
    point("BREL", Fraction(2) ** -(p + G) * 2 ** b.meta["shift"])
    unchecked = sorted(set(b.roles) - seen)
    if unchecked:
        findings.append(f"{tag}: derived but not checked: {unchecked}")
    cells, _rmax, _cs = _check_recip_cells(fmt)
    findings.extend(f"{tag}: {s}" for s in cells)
    return count[0], _check_log_scale(b, findings) if lanes else 0


def check_constants(builder=None, formats=FORMATS, attrs=sf.RND_MODES,
                    names=NAMES):
    """(lines, findings): re-derive every derived constant of every built
    fragment (the section's comment above) and run the scale words. `lines`
    say what was checked; `findings` are the differences, empty when none.
    `builder(name, fmt, rnd)` is build, or a faulted one for a test."""
    builder = builder or build
    lines, findings = [], []
    for name in names:
        for fmt in formats:
            n_const = n_lanes = 0
            for rnd in attrs:
                b = builder(name, fmt, rnd)
                if name in LOG_NAMES:
                    c, ln = _check_build_log(b, findings, rnd == attrs[0])
                else:
                    c, ln = _check_build(b, findings)
                n_const += c
                n_lanes += ln
            meta = b.meta
            plan = ((meta["K3"], meta["K2"], meta["D"]) if "K3" in meta
                    else (meta["K"], meta["D"]))
            what = ("reduction, table and 2^-k words" if name in LOG_NAMES
                    else "scale, fixed-grid, 2^-k and table words")
            lines.append(
                f"{name} {fmt.name}: G = {meta['G']}, plan {plan}: "
                f"{n_const} derived constants in {len(attrs)} fragments, "
                f"each the rounding its rule gives for every value of an "
                f"enclosure of the true number; {n_lanes} lanes of the "
                f"{what}")
            if name in LOG_NAMES:
                lines[-1] += (f"; RECIP_SEED's 512 cells: C from 8 to 16, max "
                              f"|r| = {float(_check_recip_cells(fmt)[1])!r}, "
                              f"under RHO_LOG")
    return lines, findings


# ---- the reduction's constants, checked ---------------------------------------
#
# The reduction's derived words - 2/pi's chunks, pi/2 in two words, RD(pi/4),
# MAGIC and the split's magic, 1/b and the floor's offset, 2^R - are asked of
# the BUILT reduction by role, as the six's are, against derivations that share
# nothing with the generator or with mpmath:
#
#   pi            Machin's formula, pi = 16 atan(1/5) - 4 atan(1/239), the series
#                 in integers (floors of 2^bits over each term, the loss
#                 counted: width 2^-(bits - 8) or so)
#   2/pi's chunks floor(2/pi 2^((k+1) b)) mod 2^b of the enclosure of 2/pi from
#                 that pi; an enclosure that straddles the last bit of a chunk
#                 is REFUSED as undecidable, never passed
#   the header    host/src/mp_2opi.h's first bits (the file the library reduces
#                 with: a bit stream, most significant word and bit first,
#                 parsed as python/tests/test_mp_consts.py's _parse_2opi does,
#                 copied here since the golden model imports no test); a missing
#                 or unreadable header is a difference by name
#   the rest      the rounding rules of the six's check (_why_not), exact
#                 fractions: pi/2 nearest, then nearest to what is left; RD(pi/4)
#                 down; 1/b and (2b - 3)/(2b) nearest; MAGIC, the split's magic
#                 and 2^R exact
#
# The words that are not rounded reals - the bucket offset, the shift counts -
# are checked where they act, by python/tests/test_mathlib_reduction.py's
# `setup`, on every exponent of the range.

_PI_CHECK_BITS = 3200


@functools.lru_cache(maxsize=None)
def _check_pi(bits):
    """(lo, hi): pi enclosed, from Machin's formula in integers. Each series
    term is a floor of 2^bits over it (the loss under one unit), the series
    alternates (its tail is under the first term dropped, under one unit):
    16 and 4 times a count of terms plus one of units either way."""
    one = 1 << bits

    def atan_inv(n):
        total, k, pw, sign = 0, 0, n, 1
        while True:
            t = one // ((2 * k + 1) * pw)
            if t == 0:
                return total, k
            total += sign * t
            sign, k, pw = -sign, k + 1, pw * n * n
    a5, k5 = atan_inv(5)
    a239, k239 = atan_inv(239)
    centre = 16 * a5 - 4 * a239
    slack = 16 * (k5 + 1) + 4 * (k239 + 1)
    return Fraction(centre - slack, one), Fraction(centre + slack, one)


def _read_two_opi(path, nbits):
    """floor(2/pi 2^nbits) as the header at `path` holds it (its first
    `nbits` bits), or a ValueError saying why not: the header is a bit stream
    of 32-bit words, most significant first (test_mp_consts._parse_2opi)."""
    try:
        text = pathlib.Path(path).read_text()
    except OSError as e:
        raise ValueError(f"{path} cannot be read ({e.__class__.__name__})")
    try:
        bits = int(text.split("#define CFT_TWO_OVER_PI_BITS")[1].split()[0])
        words = int(text.split("#define CFT_TWO_OVER_PI_WORDS")[1].split()[0])
        body = text.split("cft_two_over_pi[CFT_TWO_OVER_PI_WORDS] = {")[1]
        vals = [int(tok[2:10], 16) for tok in
                body.split("};")[0].replace(",", " ").split()
                if tok.startswith("0x")]
    except (IndexError, ValueError):
        raise ValueError(f"{path} is not the 2/pi header (CFT_TWO_OVER_PI_* "
                         f"and the array)")
    if len(vals) != words or bits != 32 * words:
        raise ValueError(f"{path}: {len(vals)} words read, {words} stated "
                         f"({bits} bits)")
    if nbits > bits:
        raise ValueError(f"{path} holds {bits} bits of 2/pi, {nbits} wanted")
    nw = -(-nbits // 32)
    v = 0
    for w in vals[:nw]:
        v = (v << 32) | w
    return v >> (32 * nw - nbits)


def _check_reduction_build(b, findings, header):
    """Every derived constant of one built reduction against its independent
    derivation, and the chunks against the header. -> constants checked."""
    fmt, p = b.fmt, b.fmt.prec
    P = b.meta["reduction"]
    tag, verify, point, seen, count = _verifier(b, findings)
    lo_pi, hi_pi = _check_pi(max(_PI_CHECK_BITS,
                                 -(-(P.bits + 256) // 64) * 64))
    point("MAGIC", Fraction(3, 2) * Fraction(2) ** (p - 1))
    point("MQ", Fraction(3, 2) * Fraction(2) ** (p - 1 + P.bottom))
    verify("INVB", "rn", Fraction(1, P.b), Fraction(1, P.b))
    off = Fraction(2 * P.b - 3, 2 * P.b)
    verify("FLOOROFF", "rn", off, off)
    w0 = verify("PIO2H", "rn", lo_pi / 2, hi_pi / 2)
    verify("PIO2L", "rn", lo_pi / 2 - w0, hi_pi / 2 - w0)
    verify("PIO4D", "rd", lo_pi / 4, hi_pi / 4)
    if P.R is not None:
        point("RANGE", Fraction(2) ** P.R)
    elif "RANGE" in b.roles:
        findings.append(f"{tag}: the range word RANGE is held where the "
                        f"range is the whole")
    # 2/pi's chunks: the integer derivation, and the header
    lo2, hi2 = 2 / hi_pi, 2 / lo_pi
    try:
        head = _read_two_opi(header, P.bits)
        head_why = None
    except ValueError as e:
        head, head_why = None, str(e)
        findings.append(f"{tag}: the header of 2/pi is missing or unusable: "
                        f"{head_why}")
    mask = (1 << P.b) - 1
    for k in range(P.nchunks):
        role, n = f"CHUNK{k}", (k + 1) * P.b
        seen.add(role)
        if role not in b.roles:
            findings.append(f"{tag}: the fragment has no constant {role}")
            continue
        count[0] += 1
        got = _dec(fmt, b.words[b.roles[role][1]])
        n_lo, n_hi = math.floor(lo2 * 2 ** n), math.floor(hi2 * 2 ** n)
        if n_lo != n_hi:
            findings.append(f"{tag} {role}: undecidable: the enclosure of "
                            f"2/pi straddles a chunk's last bit, bit {n}")
        elif got != n_lo & mask:
            findings.append(f"{tag} {role}: {_hexfrac(got)} is not bits "
                            f"[{k * P.b}, {n}) of 2/pi, 0x{n_lo & mask:x} "
                            f"(Machin's formula)")
        if head is not None:
            want = (head >> (P.bits - n)) & mask
            if got != want:
                findings.append(f"{tag} {role}: {_hexfrac(got)} is not the "
                                f"header's bits [{k * P.b}, {n}), "
                                f"0x{want:x}")
    unchecked = sorted(set(b.roles) - seen)
    if unchecked:
        findings.append(f"{tag}: derived but not checked: {unchecked}")
    return count[0]


def _hexfrac(v):
    return f"0x{int(v):x}" if v.denominator == 1 else f"{float(v):.17g}"


def check_reduction_constants(builder=None, formats=(FP64, FP128, FP256),
                              header=None):
    """(lines, findings): re-derive every derived constant of the built
    reduction at each of `formats` (the section's comment above) and compare,
    by role. `lines` say what was checked; `findings` are the differences,
    empty when none. `builder(fmt)` is build_reduction, or a faulted one for
    a test; `header` the path of 2/pi's header (host/src/mp_2opi.h)."""
    builder = builder or build_reduction
    header = header or _TWO_OPI_HEADER
    lines, findings = [], []
    for fmt in formats:
        b = builder(fmt)
        P = b.meta["reduction"]
        n = _check_reduction_build(b, findings, header)
        lines.append(
            f"reduction {fmt.name}: G = {P.G}, b = {P.b}, L = {P.L}, "
            f"{P.nchunks} chunks of {P.b} bits ({P.bits} bits of 2/pi): {n} "
            f"derived constants, each the rounding its rule gives for every "
            f"value of an enclosure of the true number (Machin's formula in "
            f"integers), the chunks also the bits of host/src/mp_2opi.h")
    return lines, findings


# ---- the module as a program ------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="python -m cft_golden.mathlib",
        description="The math library's golden generator: the fragments of "
                    + ", ".join(NAMES) + ", and the trigonometric reduction "
                    "(reduction).")
    ap.add_argument("--check", action="store_true",
                    help="re-derive every constant the built fragments "
                         "hold, in integer arithmetic of its own, and exit "
                         "1 on a difference")
    ap.add_argument("--only", default="",
                    help="a comma-separated list of routines, and the word "
                         "reduction, to check or list (default: all, the "
                         "reduction checked but not listed)")
    args = ap.parse_args(argv)
    only = tuple(n for n in args.only.split(",") if n)
    for n in only:
        if n not in NAMES and n != "reduction":
            ap.error(f"--only {n!r}: one of {', '.join(NAMES)}, reduction")
    names = tuple(n for n in only if n in NAMES) or (() if only else NAMES)
    reduction = not only or "reduction" in only
    if args.check:
        failed = False
        if names:
            lines, findings = check_constants(formats=FORMATS, names=names)
            for ln in lines:
                print(ln)
            for fd in findings:
                print("DIFFERENCE:", fd)
            print(f"mathlib --check: {len(names)} routines, {len(FORMATS)} "
                  f"formats, {len(findings)} differences")
            failed = bool(findings)
        if reduction:
            lines, findings = check_reduction_constants()
            for ln in lines:
                print(ln)
            for fd in findings:
                print("DIFFERENCE:", fd)
            print(f"mathlib --check (reduction): {len(lines)} formats, "
                  f"{len(findings)} differences")
            failed = failed or bool(findings)
        return 1 if failed else 0
    if names:
        print(f"{'routine':8s} {'format':6s} {'rnd':4s} {'insns':>6s} "
              f"{'words':>6s} {'live':>5s}  cap")
    for name in names:
        for fmt in FORMATS:
            for rnd in sf.RND_MODES:
                f = fragment(name, fmt, rnd)
                print(f"{name:8s} {fmt.name:6s} {sf.RND_NAMES[rnd]:4s} "
                      f"{len(f):6d} {len(f.words):6d} {f.live_max():5d}  "
                      f"{LIVE_CAP[fmt.name]}")
    if "reduction" in only:
        for fmt in (FP64, FP128, FP256):
            b = build_reduction(fmt)
            P = b.meta["reduction"]
            by = {}
            for ph in b.phase_of:
                by[ph] = by.get(ph, 0) + 1
            print(f"reduction {fmt.name}: G = {P.G}, b = {P.b}, L = {P.L}, "
                  f"{P.K} words, {len(b.body)} instructions by phase {by}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
