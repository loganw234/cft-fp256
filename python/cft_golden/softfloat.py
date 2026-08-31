# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Exact software model of the tile's arithmetic, in Python integers.

This file is the definition of correct. The RTL is verified against it,
conformance vectors are generated from it, and any GPU-side library
claiming identity is scored against the same vectors. It therefore
avoids every source of ambient arithmetic: no floats, no numpy, no
mpmath - only integers, which Python evaluates exactly at any size.
(mpmath appears in python/tests/ as an independent cross-check, never
here.)

Semantics implemented - the determinism contract of docs/DETERMINISM.md:

* rounding: all five IEEE 754-2019 rounding-direction attributes
  (4.3.1, 4.3.2), selected per operation and defaulting to
  roundTiesToEven. Every mode is a separate deterministic contract:
  the same inputs and the same mode always give the same bits.
* subnormals: full support, never flushed, in or out
* NaN: any NaN in -> the one canonical qNaN out (sign 0, quiet bit set,
  payload 0); a signaling NaN in raises invalid
* signed zero: IEEE 754-2019 6.3 - an exact zero sum or difference of
  non-zero operands is +0 in every mode except roundTowardNegative,
  where it is -0; zero sums of like-signed zeros keep the sign; the
  zero product keeps the XOR sign
* overflow: 7.4 - the delivered result depends on the mode and the
  sign, so roundTowardZero never produces an infinity and the two
  directed modes produce one only on their own side
* fusedMultiplyAdd: the product is exact internally (it cannot
  overflow or underflow before the addend joins); one rounding at
  the end
* underflow flag: tininess detected after rounding (as RISC-V does),
  raised only when the result is both tiny and inexact
* exception flags are sticky data, not traps: every op returns
  (bits, flags)
"""

import math

from .formats import FpFormat

# flag bits (sticky, OR-accumulated by callers; matches rtl/cft_fpfma.sv
# and the FLAGS CSR)
FLAG_INVALID = 1 << 0
FLAG_DIVZERO = 1 << 1  # raised only by div (754 7.3)
FLAG_OVERFLOW = 1 << 2
FLAG_UNDERFLOW = 1 << 3
FLAG_INEXACT = 1 << 4

# unpacked kinds
ZERO, SUB, NORM, INF, NAN = "zero", "sub", "norm", "inf", "nan"

# rounding-direction attributes (IEEE 754-2019 4.3). The encoding is
# RISC-V's frm, which this project already follows for tininess, so
# anyone porting between the two reads one table, not two. MODE[14:12]
# in the CSR carries it; encodings 5-7 are reserved (the hardware
# treats them as RNE, but no conforming host issues them, so the model
# rejects them rather than blessing a value the contract does not
# define).
RND_RNE = 0  # roundTiesToEven      - the default
RND_RTZ = 1  # roundTowardZero
RND_RDN = 2  # roundTowardNegative  - toward -infinity
RND_RUP = 3  # roundTowardPositive  - toward +infinity
RND_RMM = 4  # roundTiesToAway
RND_NAMES = {RND_RNE: "rne", RND_RTZ: "rtz", RND_RDN: "rdn",
             RND_RUP: "rup", RND_RMM: "rmm"}
RND_MODES = tuple(RND_NAMES)


class Unpacked:
    __slots__ = ("kind", "sign", "m", "e", "signaling")

    def __init__(self, kind, sign, m=0, e=0, signaling=False):
        self.kind = kind
        self.sign = sign
        self.m = m  # integer significand; value = (-1)^sign * m * 2^e
        self.e = e
        self.signaling = signaling


def unpack(fmt: FpFormat, bits: int) -> Unpacked:
    sign = (bits >> (fmt.width - 1)) & 1
    ef = (bits >> fmt.man_w) & fmt.exp_mask
    frac = bits & fmt.man_mask
    if ef == fmt.exp_mask:
        if frac == 0:
            return Unpacked(INF, sign)
        quiet = (frac >> (fmt.man_w - 1)) & 1
        return Unpacked(NAN, sign, signaling=not quiet)
    if ef == 0:
        if frac == 0:
            return Unpacked(ZERO, sign)
        return Unpacked(SUB, sign, m=frac, e=fmt.emin - fmt.man_w)
    return Unpacked(NORM, sign, m=frac | (1 << fmt.man_w), e=ef - fmt.bias - fmt.man_w)


# ---- packed constants ------------------------------------------------

def zero_bits(fmt, sign=0):
    return sign << (fmt.width - 1)


def inf_bits(fmt, sign=0):
    return (sign << (fmt.width - 1)) | (fmt.exp_mask << fmt.man_w)


def qnan_bits(fmt):
    """The canonical quiet NaN: the only NaN this hardware emits."""
    return (fmt.exp_mask << fmt.man_w) | (1 << (fmt.man_w - 1))


def snan_bits(fmt, payload=1):
    assert 0 < payload < (1 << (fmt.man_w - 1))
    return (fmt.exp_mask << fmt.man_w) | payload


def one_bits(fmt, sign=0):
    return (sign << (fmt.width - 1)) | (fmt.bias << fmt.man_w)


def min_subnormal_bits(fmt, sign=0):
    return (sign << (fmt.width - 1)) | 1


def max_subnormal_bits(fmt, sign=0):
    return (sign << (fmt.width - 1)) | fmt.man_mask


def min_normal_bits(fmt, sign=0):
    return (sign << (fmt.width - 1)) | (1 << fmt.man_w)


def max_normal_bits(fmt, sign=0):
    return (sign << (fmt.width - 1)) | ((fmt.exp_mask - 1) << fmt.man_w) | fmt.man_mask


def negate(fmt, bits):
    return bits ^ fmt.sign_mask


def is_nan(fmt, bits):
    return ((bits >> fmt.man_w) & fmt.exp_mask) == fmt.exp_mask and (bits & fmt.man_mask) != 0


# ---- rounding --------------------------------------------------------

def _check_mode(rnd: int):
    if rnd not in RND_NAMES:
        raise ValueError(f"bad rounding mode {rnd}; contract defines 0-4")


def _round_up(rnd: int, sign: int, guard: int, sticky: int, lsb: int) -> bool:
    """Should the retained magnitude be incremented? Everything here is
    magnitude-and-sign, never two's complement, so the directed modes
    are just 'away from zero on one side of it'."""
    if rnd == RND_RNE:
        return bool(guard and (sticky or lsb))
    if rnd == RND_RMM:
        return bool(guard)
    if rnd == RND_RTZ:
        return False
    if rnd == RND_RDN:
        return bool(sign and (guard or sticky))
    return bool((not sign) and (guard or sticky))  # RND_RUP


def _overflow_gives_inf(rnd: int, sign: int) -> bool:
    """IEEE 754-2019 7.4: which overflows deliver an infinity, and
    which deliver the largest finite magnitude instead."""
    if rnd in (RND_RNE, RND_RMM):
        return True
    if rnd == RND_RTZ:
        return False
    if rnd == RND_RDN:
        return bool(sign)
    return not sign  # RND_RUP


def zero_sign_for_exact_cancellation(rnd: int) -> int:
    """754 6.3: an exact zero sum of oppositely-signed operands is +0
    in every attribute except roundTowardNegative."""
    return 1 if rnd == RND_RDN else 0


def _round_at(m: int, e: int, q: int, sign: int = 0, rnd: int = RND_RNE):
    """Round the exact value (-1)^sign * m * 2^e (m > 0) to an integer
    multiple of 2^q under `rnd`. Returns (kept, inexact) with magnitude
    kept * 2^q."""
    shift = q - e
    if shift <= 0:
        return m << (-shift), False
    kept = m >> shift
    rem = m & ((1 << shift) - 1)
    if rem == 0:
        return kept, False
    half = 1 << (shift - 1)
    guard = 1 if rem >= half else 0
    sticky = 1 if (rem & (half - 1)) else 0
    if _round_up(rnd, sign, guard, sticky, kept & 1):
        kept += 1
    return kept, True


def round_pack(fmt: FpFormat, sign: int, m: int, e: int, rnd: int = RND_RNE):
    """Round the exact non-zero value (-1)^sign * m * 2^e into the
    format under `rnd`. Returns (bits, flags)."""
    assert m > 0
    _check_mode(rnd)
    p = fmt.prec
    e_norm = e + m.bit_length() - 1  # unbiased exponent of the value

    # Tininess after rounding: round as if the exponent range were
    # unbounded and ask whether the result lands below 2^emin.
    q_unb = e_norm - (p - 1)
    kept_u, _ = _round_at(m, e, q_unb, sign, rnd)
    e_after_unb = q_unb + kept_u.bit_length() - 1
    tiny = e_after_unb < fmt.emin

    # The real rounding position: the format's ulp, clamped so that
    # nothing below the subnormal ulp is ever representable.
    q = max(e_norm, fmt.emin) - (p - 1)
    kept, inexact = _round_at(m, e, q, sign, rnd)
    flags = FLAG_INEXACT if inexact else 0

    if kept == 0:
        # Underflowed past the smallest subnormal. (Only the modes that
        # round toward this side of zero can land here: RUP never does
        # so for a positive value, nor RDN for a negative one.)
        return zero_bits(fmt, sign), flags | FLAG_UNDERFLOW

    e_res = q + kept.bit_length() - 1
    if e_res > fmt.emax:
        # Overflow: signalled in every mode (the unbounded-exponent
        # result exceeded the format), but what gets delivered differs.
        if _overflow_gives_inf(rnd, sign):
            return inf_bits(fmt, sign), flags | FLAG_OVERFLOW | FLAG_INEXACT
        return max_normal_bits(fmt, sign), flags | FLAG_OVERFLOW | FLAG_INEXACT

    if tiny and inexact:
        flags |= FLAG_UNDERFLOW

    if e_res < fmt.emin:
        # Subnormal: kept has fewer than p bits and its LSB weight is
        # exactly emin - (p - 1), so it IS the fraction field.
        return zero_bits(fmt, sign) | kept, flags

    if kept.bit_length() == p + 1:
        # Rounding carried all the way out: kept == 2^p exactly.
        kept >>= 1
    frac = kept - (1 << (p - 1))
    biased = e_res + fmt.bias
    return zero_bits(fmt, sign) | (biased << fmt.man_w) | frac, flags


# ---- operations ------------------------------------------------------

def _nan_result(fmt, *ops):
    invalid = any(u.kind == NAN and u.signaling for u in ops)
    return qnan_bits(fmt), (FLAG_INVALID if invalid else 0)


def fma(fmt: FpFormat, xa: int, xb: int, xc: int, rnd: int = RND_RNE):
    """(bits, flags) of fusedMultiplyAdd(a, b, c) = a*b + c, one rounding."""
    _check_mode(rnd)
    ua, ub, uc = unpack(fmt, xa), unpack(fmt, xb), unpack(fmt, xc)
    if NAN in (ua.kind, ub.kind, uc.kind):
        return _nan_result(fmt, ua, ub, uc)
    sp = ua.sign ^ ub.sign

    if INF in (ua.kind, ub.kind):
        if ZERO in (ua.kind, ub.kind):
            return qnan_bits(fmt), FLAG_INVALID  # inf * 0
        if uc.kind == INF and uc.sign != sp:
            return qnan_bits(fmt), FLAG_INVALID  # inf - inf
        return inf_bits(fmt, sp), 0
    if uc.kind == INF:
        return inf_bits(fmt, uc.sign), 0

    if ZERO in (ua.kind, ub.kind):
        if uc.kind == ZERO:
            # exact zero + exact zero: keep the sign only when they agree
            rs = uc.sign if uc.sign == sp else \
                zero_sign_for_exact_cancellation(rnd)
            return zero_bits(fmt, rs), 0
        return xc, 0  # 0*b + c == c exactly, c representable

    mp, ep = ua.m * ub.m, ua.e + ub.e  # exact product, never overflows
    if uc.kind == ZERO:
        return round_pack(fmt, sp, mp, ep, rnd)

    e0 = min(ep, uc.e)
    t = (mp << (ep - e0)) * (-1 if sp else 1) \
        + (uc.m << (uc.e - e0)) * (-1 if uc.sign else 1)
    if t == 0:
        return zero_bits(fmt, zero_sign_for_exact_cancellation(rnd)), 0
    return round_pack(fmt, 1 if t < 0 else 0, abs(t), e0, rnd)


def add(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    _check_mode(rnd)
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)
    if NAN in (ua.kind, ub.kind):
        return _nan_result(fmt, ua, ub)
    if ua.kind == INF:
        if ub.kind == INF and ub.sign != ua.sign:
            return qnan_bits(fmt), FLAG_INVALID
        return inf_bits(fmt, ua.sign), 0
    if ub.kind == INF:
        return inf_bits(fmt, ub.sign), 0
    if ua.kind == ZERO and ub.kind == ZERO:
        rs = ua.sign if ua.sign == ub.sign else \
            zero_sign_for_exact_cancellation(rnd)
        return zero_bits(fmt, rs), 0
    if ua.kind == ZERO:
        return xb, 0
    if ub.kind == ZERO:
        return xa, 0
    e0 = min(ua.e, ub.e)
    t = (ua.m << (ua.e - e0)) * (-1 if ua.sign else 1) \
        + (ub.m << (ub.e - e0)) * (-1 if ub.sign else 1)
    if t == 0:
        return zero_bits(fmt, zero_sign_for_exact_cancellation(rnd)), 0
    return round_pack(fmt, 1 if t < 0 else 0, abs(t), e0, rnd)


def sub(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    return add(fmt, xa, negate(fmt, xb), rnd)


def mul(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    _check_mode(rnd)
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)
    if NAN in (ua.kind, ub.kind):
        return _nan_result(fmt, ua, ub)
    sp = ua.sign ^ ub.sign
    if INF in (ua.kind, ub.kind):
        if ZERO in (ua.kind, ub.kind):
            return qnan_bits(fmt), FLAG_INVALID
        return inf_bits(fmt, sp), 0
    if ZERO in (ua.kind, ub.kind):
        return zero_bits(fmt, sp), 0
    return round_pack(fmt, sp, ua.m * ub.m, ua.e + ub.e, rnd)


# The four ops as the engine sees them: an opcode plus three streams,
# with ADD/SUB/MUL realised by operand steering into the one FMA core.
# The steering is defined here so the golden model, the RTL (see
# cft_opmux.sv), and the docs cannot drift apart:
#   FMA: d = a*b + c
#   ADD: d = a + c        (b := 1.0)
#   SUB: d = a - c        (b := 1.0, c sign-flipped)
#   MUL: d = a*b          (c := zero signed with sign(a)^sign(b), which
#                          preserves the sign of an exact zero product)
def _fold_sticky(q: int, rem_nonzero: bool) -> int:
    """Append a sticky bit below an integer's LSB.

    Long division and integer square root produce a floor `q` plus the
    fact that something nonzero was discarded. Rounding needs that
    residue only as "is there anything below the last computed bit" -
    so shift q up one and OR the fact in. round_pack then derives its
    guard bit from q's own exact bits and its sticky from this appended
    one, which is faithful as long as the round position sits at least
    two bits above the fold - the p+3 computed bits below guarantee it.

    The same trick, in hardware, is the FMA pipe's appended-marker LSB.
    """
    return (q << 1) | (1 if rem_nonzero else 0)


def div(fmt: FpFormat, xa: int, xb: int, rnd: int = RND_RNE):
    """(bits, flags) of division(a, b), correctly rounded (754 5.4.1)."""
    _check_mode(rnd)
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)
    if NAN in (ua.kind, ub.kind):
        return _nan_result(fmt, ua, ub)
    sq = ua.sign ^ ub.sign

    if ua.kind == INF:
        if ub.kind == INF:
            return qnan_bits(fmt), FLAG_INVALID           # inf / inf
        return inf_bits(fmt, sq), 0                        # inf / finite
    if ub.kind == INF:
        return zero_bits(fmt, sq), 0                       # finite / inf
    if ub.kind == ZERO:
        if ua.kind == ZERO:
            return qnan_bits(fmt), FLAG_INVALID            # 0 / 0
        return inf_bits(fmt, sq), FLAG_DIVZERO             # x / 0
    if ua.kind == ZERO:
        return zero_bits(fmt, sq), 0

    # Exact long division carried to at least p+3 quotient bits, with
    # everything below the last computed bit folded into one sticky.
    p = fmt.prec
    k = (p + 3) + ub.m.bit_length() - ua.m.bit_length() + 1
    if k < 0:
        k = 0
    q, rem = divmod(ua.m << k, ub.m)
    assert q.bit_length() >= p + 3
    m = _fold_sticky(q, rem != 0)
    e = (ua.e - ub.e) - k - 1
    return round_pack(fmt, sq, m, e, rnd)


def sqrt(fmt: FpFormat, xa: int, rnd: int = RND_RNE):
    """(bits, flags) of squareRoot(a), correctly rounded (754 5.4.1)."""
    _check_mode(rnd)
    ua = unpack(fmt, xa)
    if ua.kind == NAN:
        return _nan_result(fmt, ua)
    if ua.kind == ZERO:
        return xa, 0                        # sqrt(+/-0) is +/-0
    if ua.sign:
        return qnan_bits(fmt), FLAG_INVALID # negative, including -inf
    if ua.kind == INF:
        return xa, 0

    # Exact integer square root of m * 2^e with e made even, carried to
    # at least p+3 result bits, remainder folded into one sticky.
    p = fmt.prec
    m, e = ua.m, ua.e
    t = 2 * (p + 3) - m.bit_length()
    if t < 0:
        t = 0
    t += (t ^ e) & 1                        # keep e - t even
    m <<= t
    e -= t
    assert (e & 1) == 0
    r = math.isqrt(m)
    assert r.bit_length() >= p + 3
    mres = _fold_sticky(r, r * r != m)
    eres = e // 2 - 1
    # A positive finite operand's root is finite, positive, and inside
    # the exponent range (|e_root| ~ |e|/2), so round_pack cannot
    # overflow or underflow here.
    return round_pack(fmt, 0, mres, eres, rnd)


# ---- seed operations for the composed divide and square root --------
#
# div and sqrt above are the CONTRACT operations - what a caller gets.
# The implementation route is the CFT_DOT one: the hardware supplies
# only what FMA cannot, and libcft composes the rest as a fixed
# sequence of ordinary operations (Newton iterations under RNE, then a
# Markstein-style exact-residual correction rounded once in the
# caller's attribute). What FMA cannot supply is the STARTING POINT,
# so these two opcodes exist: an initial approximation of 1/x and of
# 1/sqrt(x), from a 2^9-entry table plus exponent arithmetic.
#
# The definition below IS the table. The hardware ROM is generated
# from these functions - never transcribed - and the tests assert the
# error bound the Newton iteration counts are derived from:
# relative error < 2^-8.5 everywhere.
#
# Both are quiet: no flags, ever, like the sign operations. They are
# helpers on the way to a rounded result, not results. Both ignore the
# rounding attribute; the pack of the (10-bit-exact) seed value into a
# subnormal result at the range edges is defined as round-to-nearest-
# even and is part of the spec, not a mode choice.

SEED_INDEX_BITS = 9
SEED_TABLE_SIZE = 1 << SEED_INDEX_BITS


def _seed_recip_entry(i: int) -> int:
    """Table entry: nearest integer to 2^18 / (1 + (i + 1/2)/2^9),
    ties (impossible here, asserted by the tests) would round to even.
    Entries lie in (2^8, 2^9]."""
    num = 1 << (18 + 10)                 # 2^18 * 2^10
    den = (1 << 10) + (i << 1) + 1       # 2^10 + 2i + 1  (= mid * 2^10)
    q, r = divmod(num, den)
    if 2 * r > den or (2 * r == den and (q & 1)):
        q += 1
    return q


def _seed_rsqrt_entry(j: int) -> int:
    """Table entry j = (odd_exponent << 9) | i: nearest integer to
    2^17 / sqrt(mid), mid = (1 + (i + 1/2)/2^9) * 2^odd. Computed by
    exact integer comparison against the squared midpoint - no
    floating point anywhere in the spec. Entries lie in [2^16/2, 2^17)."""
    odd = j >> SEED_INDEX_BITS
    i = j & (SEED_TABLE_SIZE - 1)
    # mid = m2 / 2^10 with m2 = (2^10 + 2i + 1) << odd
    m2 = ((1 << 10) + (i << 1) + 1) << odd
    # want q = round(2^17 / sqrt(m2 / 2^10)) = round(2^22 / sqrt(m2))
    # floor first: largest q with q^2 * m2 <= 2^44
    target = 1 << 44
    q = math.isqrt(target // m2)
    while (q + 1) * (q + 1) * m2 <= target:
        q += 1
    # round: up when (q + 1/2)^2 * m2 < 2^44, i.e. (2q+1)^2 * m2 < 2^46
    if (2 * q + 1) * (2 * q + 1) * m2 < (1 << 46):
        q += 1
    return q


def _seed_pack(fmt: FpFormat, sign: int, m: int, e: int) -> int:
    """round_pack without the flags: seeds are quiet by specification."""
    bits, _ = round_pack(fmt, sign, m, e, RND_RNE)
    return bits


def recip_seed(fmt: FpFormat, xa: int, *_):
    """(bits, 0): an approximation of 1/a, relative error < 2^-8.5.

    NaN -> canonical qNaN (quiet). +/-inf -> +/-0. +/-0 and every
    +/-subnormal -> +/-inf (flush-at-input; see the body),
    which lets a composed divide inherit the right special without a
    branch. Finite nonzero, including subnormal, is value-based: the
    operand is normalised first, so the seed's accuracy does not decay
    at the bottom of the range. Range-edge results (1/x outside the
    finite range, or subnormal) saturate to infinity or round to the
    subnormal grid; the library sequences prescale so neither is ever
    hit mid-sequence, but the definition is total.
    """
    ua = unpack(fmt, xa)
    if ua.kind == NAN:
        return qnan_bits(fmt), 0
    if ua.kind == INF:
        return zero_bits(fmt, ua.sign), 0
    biased = (xa >> fmt.man_w) & fmt.exp_mask
    if biased == 0:
        # Zero OR subnormal: the zero-class result. Flush-at-input is a
        # deliberate spec choice made for the hardware - a value-based
        # seed on subnormals needs a leading-zero count and a
        # normalising shift per lane, most of a normaliser, spent on a
        # case NOTHING uses: the composed sequences prenormalise (exact
        # multiply by 2^p) before ever seeding, and sequences.py asserts
        # it. This keeps the seed datapath to exponent arithmetic and
        # one shared ROM.
        return inf_bits(fmt, ua.sign), 0
    E = biased - fmt.bias
    i = (xa >> (fmt.man_w - SEED_INDEX_BITS)) & (SEED_TABLE_SIZE - 1)
    r = _seed_recip_entry(i)
    # 1/(1.f * 2^E) ~ (r / 2^18) * 2^-E
    e_out = -E - 18
    if e_out + r.bit_length() - 1 > fmt.emax:
        return inf_bits(fmt, ua.sign), 0
    return _seed_pack(fmt, ua.sign, r, e_out), 0


def rsqrt_seed(fmt: FpFormat, xa: int, *_):
    """(bits, 0): an approximation of 1/sqrt(a), relative error
    < 2^-8.5. Quiet, like recip_seed.

    NaN -> qNaN. +inf -> +0, +0 -> +inf, -0 -> -inf (the limits the
    exact operations take, matching 754's rsqrt conventions where they
    exist). Negative -> qNaN, quietly - the INVALID for a real negative
    sqrt is raised by the contract-level sqrt, not by its scaffolding.
    """
    ua = unpack(fmt, xa)
    if ua.kind == NAN:
        return qnan_bits(fmt), 0
    biased = (xa >> fmt.man_w) & fmt.exp_mask
    if biased == 0:
        # Zero-class (including every subnormal, by the flush-at-input
        # choice recip_seed documents): the correspondingly-signed
        # infinity, matching the limit where 754 defines it.
        return inf_bits(fmt, ua.sign), 0
    if ua.sign:
        return qnan_bits(fmt), 0
    if ua.kind == INF:
        return zero_bits(fmt), 0
    E = biased - fmt.bias
    i = (xa >> (fmt.man_w - SEED_INDEX_BITS)) & (SEED_TABLE_SIZE - 1)
    odd = E & 1
    r = _seed_rsqrt_entry((odd << SEED_INDEX_BITS) | i)
    # 1/sqrt(1.f * 2^odd * 2^(E-odd)) ~ (r / 2^17) * 2^-((E-odd)/2)
    e_out = -((E - odd) // 2) - 17
    return _seed_pack(fmt, 0, r, e_out), 0


OP_FMA, OP_ADD, OP_SUB, OP_MUL = 0, 1, 2, 3
# Non-arithmetic operations. These do not round, do not depend on the
# rounding attribute, and reach the output through the pipeline's
# existing precomputed-result path rather than the datapath.
OP_ABS, OP_NEG, OP_COPYSIGN = 4, 5, 6
OP_MIN, OP_MAX, OP_MINNUM, OP_MAXNUM = 7, 8, 9, 10
# Comparison predicates and the select that consumes them. Together
# these are branchless conditional code, which is what the det library
# needs from hardware far more than it needs a sin().
#
# There is no GT or GE opcode and there does not need to be: the engine
# reads three independent pointers, so a > b is compute(LT, b, a) with
# the buffers swapped, at no cost. NE is SELECT over EQ, or an inverted
# read. Only the orderings that cannot be reached by swapping operands
# earn an opcode. MODE[7:0] is a byte; 15 and 24-255 are unassigned.
OP_SELECT, OP_CMPLT, OP_CMPLE, OP_CMPEQ = 11, 12, 13, 14
# Integer and bitwise operations on the encoding, treated as a W-bit
# unsigned word. Not floating point at all: they never round, never
# signal, and never canonicalise a NaN - the bits are just bits.
#
# These exist because the det library's algebraic kernels start from
# integer seeds. det_sqrt's first estimate is 0x5F375A86 - (m >> 1) on
# the bit pattern, and its special-case guards are unsigned magnitude
# compares. Without an integer group the tile can compute the Newton
# refinement but not the value it refines from.
OP_IAND, OP_IOR, OP_IXOR, OP_IADD = 16, 17, 18, 19
OP_ISUB, OP_ISHL, OP_ISHR, OP_ICMPLT = 20, 21, 22, 23
# Seed opcodes for the composed divide/sqrt (24 and 25 are the
# reductions, in reduce.py). Quiet, unary, attribute-independent.
OP_RECIP_SEED, OP_RSQRT_SEED = 26, 27
OP_NAMES = {
    OP_FMA: "fma", OP_ADD: "add", OP_SUB: "sub", OP_MUL: "mul",
    OP_ABS: "abs", OP_NEG: "neg", OP_COPYSIGN: "copysign",
    OP_MIN: "min", OP_MAX: "max",
    OP_MINNUM: "minnum", OP_MAXNUM: "maxnum",
    OP_SELECT: "select", OP_CMPLT: "cmplt",
    OP_CMPLE: "cmple", OP_CMPEQ: "cmpeq",
    OP_IAND: "iand", OP_IOR: "ior", OP_IXOR: "ixor", OP_IADD: "iadd",
    OP_ISUB: "isub", OP_ISHL: "ishl", OP_ISHR: "ishr",
    OP_ICMPLT: "icmplt",
    OP_RECIP_SEED: "recip_seed", OP_RSQRT_SEED: "rsqrt_seed",
}
INT_OPS = (OP_IAND, OP_IOR, OP_IXOR, OP_IADD,
           OP_ISUB, OP_ISHL, OP_ISHR, OP_ICMPLT)
ARITH_OPS = (OP_FMA, OP_ADD, OP_SUB, OP_MUL)
SIMPLE_OPS = (OP_ABS, OP_NEG, OP_COPYSIGN,
              OP_MIN, OP_MAX, OP_MINNUM, OP_MAXNUM,
              OP_SELECT, OP_CMPLT, OP_CMPLE, OP_CMPEQ,
              OP_IAND, OP_IOR, OP_IXOR, OP_IADD,
              OP_ISUB, OP_ISHL, OP_ISHR, OP_ICMPLT)
SEED_OPS = (OP_RECIP_SEED, OP_RSQRT_SEED)


# ---- non-arithmetic operations ---------------------------------------
#
# 754-2019 5.5.1 calls abs/negate/copySign "quiet-computational": they
# manipulate the sign bit and nothing else, signal no exception at all
# (not even on a signaling NaN), and pass every other bit through
# unchanged - including a NaN's payload.
#
# That is a deliberate exception to this contract's canonical-NaN rule,
# and it does not weaken it. The canonical rule exists because in
# ARITHMETIC the choice of which operand's payload survives is where
# implementations diverge. Here there is exactly one source for the
# payload, so the result is still a deterministic function of the
# input bits - and canonicalising instead would make copySign lossy,
# which the standard does not permit.

def fabs(fmt: FpFormat, xa: int, *_):
    return xa & ~fmt.sign_mask, 0


def neg(fmt: FpFormat, xa: int, *_):
    return xa ^ fmt.sign_mask, 0


def copysign(fmt: FpFormat, xa: int, xb: int, *_):
    return (xa & ~fmt.sign_mask) | (xb & fmt.sign_mask), 0


def _numeric_lt(fmt: FpFormat, xa: int, xb: int) -> bool:
    """x < y for non-NaN operands, IEEE comparison (so -0 == +0)."""
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)
    if ua.kind == ZERO and ub.kind == ZERO:
        return False                      # +-0 compare equal
    if ua.sign != ub.sign:
        return bool(ua.sign)              # negative < positive
    # same sign: the magnitude ordering of the encoding is monotone,
    # so the payload-free bit pattern compares directly
    ma, mb = xa & ~fmt.sign_mask, xb & ~fmt.sign_mask
    return (ma > mb) if ua.sign else (ma < mb)


def _minmax(fmt: FpFormat, xa: int, xb: int, want_max: bool, number: bool):
    """754-2019 9.6. `number` selects the ...Number variants, which
    return the non-NaN operand instead of propagating the NaN."""
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)
    a_nan, b_nan = ua.kind == NAN, ub.kind == NAN
    flags = FLAG_INVALID if ((a_nan and ua.signaling) or
                             (b_nan and ub.signaling)) else 0
    if a_nan or b_nan:
        if not number or (a_nan and b_nan):
            return qnan_bits(fmt), flags
        return (xb if a_nan else xa), flags
    # Signed zeros compare equal but are not interchangeable here: the
    # standard requires min(+0, -0) to be -0 and max(+0, -0) to be +0.
    if ua.kind == ZERO and ub.kind == ZERO:
        if ua.sign == ub.sign:
            return xa, flags
        neg_one = xa if ua.sign else xb
        pos_one = xb if ua.sign else xa
        return (pos_one if want_max else neg_one), flags
    a_lt_b = _numeric_lt(fmt, xa, xb)
    if want_max:
        return (xb if a_lt_b else xa), flags
    return (xa if a_lt_b else xb), flags


def fmin(fmt, xa, xb, *_):
    return _minmax(fmt, xa, xb, want_max=False, number=False)


def fmax(fmt, xa, xb, *_):
    return _minmax(fmt, xa, xb, want_max=True, number=False)


def fminnum(fmt, xa, xb, *_):
    return _minmax(fmt, xa, xb, want_max=False, number=True)


def fmaxnum(fmt, xa, xb, *_):
    return _minmax(fmt, xa, xb, want_max=True, number=True)


def _compare(fmt: FpFormat, xa: int, xb: int, want):
    """754-2019 5.11 quiet comparison. Returns (1.0 or +0.0, flags).

    A predicate that yields a float rather than a condition code is the
    point: it is the operand a later select consumes, and it lives in
    the same arrays as everything else. Quiet comparisons signal only
    on a signaling NaN; an unordered pair is simply false.
    """
    ua, ub = unpack(fmt, xa), unpack(fmt, xb)
    a_nan, b_nan = ua.kind == NAN, ub.kind == NAN
    flags = FLAG_INVALID if ((a_nan and ua.signaling) or
                             (b_nan and ub.signaling)) else 0
    if a_nan or b_nan:
        return zero_bits(fmt), flags          # unordered: every predicate false
    lt = _numeric_lt(fmt, xa, xb)
    gt = _numeric_lt(fmt, xb, xa)
    eq = not lt and not gt
    truth = {"lt": lt, "le": lt or eq, "eq": eq}[want]
    return (one_bits(fmt) if truth else zero_bits(fmt)), flags


def cmplt(fmt, xa, xb, *_):
    return _compare(fmt, xa, xb, "lt")


def cmple(fmt, xa, xb, *_):
    return _compare(fmt, xa, xb, "le")


def cmpeq(fmt, xa, xb, *_):
    return _compare(fmt, xa, xb, "eq")


def select(fmt: FpFormat, xa: int, xb: int, xc: int = 0):
    """d = c is not zero ? a : b. Signals nothing and inspects nothing
    but c's magnitude, so it moves NaNs and infinities intact.

    "Not zero" means not +0 and not -0. The comparison opcodes produce
    exactly 1.0 or +0.0, so the pairing is unambiguous in practice; the
    rule is stated in terms of the bit pattern so that any other
    producer is unambiguous too.
    """
    return (xa if (xc & ~fmt.sign_mask) != 0 else xb), 0


def _mask(fmt, v):
    return v & ((1 << fmt.width) - 1)


def _shift_amount(fmt, xb):
    """Shifts take their count from b's low bits, modulo the width. Every
    format here is a power-of-two number of bits, so this is exactly the
    low log2(width) bits and no count can be out of range."""
    return xb & (fmt.width - 1)


def iand(fmt, xa, xb, *_):
    return xa & xb, 0


def ior(fmt, xa, xb, *_):
    return xa | xb, 0


def ixor(fmt, xa, xb, *_):
    return xa ^ xb, 0


def iadd(fmt, xa, xb, *_):
    return _mask(fmt, xa + xb), 0


def isub(fmt, xa, xb, *_):
    return _mask(fmt, xa - xb), 0


def ishl(fmt, xa, xb, *_):
    return _mask(fmt, xa << _shift_amount(fmt, xb)), 0


def ishr(fmt, xa, xb, *_):
    return xa >> _shift_amount(fmt, xb), 0        # logical, never arithmetic


def icmplt(fmt, xa, xb, *_):
    """Unsigned compare of the encodings, yielding 1.0 or +0.0 so that
    a select consumes it exactly like a floating-point predicate."""
    return (one_bits(fmt) if xa < xb else zero_bits(fmt)), 0


SIMPLE_IMPL = {
    OP_ABS: fabs, OP_NEG: neg, OP_COPYSIGN: copysign,
    OP_MIN: fmin, OP_MAX: fmax,
    OP_MINNUM: fminnum, OP_MAXNUM: fmaxnum,
    OP_SELECT: select, OP_CMPLT: cmplt,
    OP_CMPLE: cmple, OP_CMPEQ: cmpeq,
    OP_IAND: iand, OP_IOR: ior, OP_IXOR: ixor, OP_IADD: iadd,
    OP_ISUB: isub, OP_ISHL: ishl, OP_ISHR: ishr, OP_ICMPLT: icmplt,
    OP_RECIP_SEED: recip_seed, OP_RSQRT_SEED: rsqrt_seed,
}


def steer(fmt: FpFormat, op: int, xa: int, xb: int, xc: int):
    """Map (op, a, b, c) to the raw FMA operand triple, exactly as the
    RTL operand mux does."""
    if op == OP_FMA:
        return xa, xb, xc
    if op == OP_ADD:
        return xa, one_bits(fmt), xc
    if op == OP_SUB:
        return xa, one_bits(fmt), negate(fmt, xc)
    if op == OP_MUL:
        sp = ((xa >> (fmt.width - 1)) ^ (xb >> (fmt.width - 1))) & 1
        return xa, xb, zero_bits(fmt, sp)
    raise ValueError(f"bad op {op}")


def compute(fmt: FpFormat, op: int, xa: int, xb: int, xc: int,
            rnd: int = RND_RNE):
    """The engine's view of one element. (bits, flags).

    Arithmetic goes through the operand steering and the one FMA;
    everything else is a direct function of the operand bits and
    ignores the rounding attribute entirely.
    """
    if op in SIMPLE_IMPL:
        return SIMPLE_IMPL[op](fmt, xa, xb, xc)
    if op in ARITH_OPS:
        return fma(fmt, *steer(fmt, op, xa, xb, xc), rnd=rnd)
    # An unassigned opcode is a defined result, not an exception. The
    # model used to raise here while the hardware quietly computed an
    # FMA - a divergence across 232 of the 256 opcode values, which is
    # a hole in "the model is the definition of correct" even though no
    # conforming host reaches it. Both now answer with the canonical
    # quiet NaN and raise invalid, so a host that issues an opcode this
    # build predates sees it in the flags.
    return qnan_bits(fmt), FLAG_INVALID
