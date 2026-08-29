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

* rounding: roundTiesToEven only (mode field reserved for RZ/RU/RD)
* subnormals: full support, never flushed, in or out
* NaN: any NaN in -> the one canonical qNaN out (sign 0, quiet bit set,
  payload 0); a signaling NaN in raises invalid
* signed zero: IEEE 754-2019 6.3 - exact zero sums/differences of
  non-zero operands are +0 under RNE; zero sums of like-signed zeros
  keep the sign; the zero product keeps the XOR sign
* fusedMultiplyAdd: the product is exact internally (it cannot
  overflow or underflow before the addend joins); one rounding at
  the end
* underflow flag: tininess detected after rounding (as RISC-V does),
  raised only when the result is both tiny and inexact
* exception flags are sticky data, not traps: every op returns
  (bits, flags)
"""

from .formats import FpFormat

# flag bits (sticky, OR-accumulated by callers; matches rtl/cft_fpfma.sv
# and the FLAGS CSR)
FLAG_INVALID = 1 << 0
FLAG_DIVZERO = 1 << 1  # reserved: no divide op in v0
FLAG_OVERFLOW = 1 << 2
FLAG_UNDERFLOW = 1 << 3
FLAG_INEXACT = 1 << 4

# unpacked kinds
ZERO, SUB, NORM, INF, NAN = "zero", "sub", "norm", "inf", "nan"


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

def _round_at(m: int, e: int, q: int):
    """Round the exact value m * 2^e (m > 0) to an integer multiple of
    2^q, roundTiesToEven. Returns (kept, inexact) with value kept * 2^q."""
    shift = q - e
    if shift <= 0:
        return m << (-shift), False
    kept = m >> shift
    rem = m & ((1 << shift) - 1)
    if rem == 0:
        return kept, False
    half = 1 << (shift - 1)
    if rem > half or (rem == half and (kept & 1)):
        kept += 1
    return kept, True


def round_pack(fmt: FpFormat, sign: int, m: int, e: int):
    """Round the exact non-zero value (-1)^sign * m * 2^e into the
    format, RNE. Returns (bits, flags)."""
    assert m > 0
    p = fmt.prec
    e_norm = e + m.bit_length() - 1  # unbiased exponent of the value

    # Tininess after rounding: round as if the exponent range were
    # unbounded and ask whether the result lands below 2^emin.
    q_unb = e_norm - (p - 1)
    kept_u, _ = _round_at(m, e, q_unb)
    e_after_unb = q_unb + kept_u.bit_length() - 1
    tiny = e_after_unb < fmt.emin

    # The real rounding position: the format's ulp, clamped so that
    # nothing below the subnormal ulp is ever representable.
    q = max(e_norm, fmt.emin) - (p - 1)
    kept, inexact = _round_at(m, e, q)
    flags = FLAG_INEXACT if inexact else 0

    if kept == 0:
        # Underflowed past the smallest subnormal.
        return zero_bits(fmt, sign), flags | FLAG_UNDERFLOW

    e_res = q + kept.bit_length() - 1
    if e_res > fmt.emax:
        # RNE overflow response: infinity, and overflow implies inexact.
        return inf_bits(fmt, sign), flags | FLAG_OVERFLOW | FLAG_INEXACT

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


def fma(fmt: FpFormat, xa: int, xb: int, xc: int):
    """(bits, flags) of fusedMultiplyAdd(a, b, c) = a*b + c, one rounding."""
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
            rs = uc.sign if uc.sign == sp else 0
            return zero_bits(fmt, rs), 0
        return xc, 0  # 0*b + c == c exactly, c representable

    mp, ep = ua.m * ub.m, ua.e + ub.e  # exact product, never overflows
    if uc.kind == ZERO:
        return round_pack(fmt, sp, mp, ep)

    e0 = min(ep, uc.e)
    t = (mp << (ep - e0)) * (-1 if sp else 1) \
        + (uc.m << (uc.e - e0)) * (-1 if uc.sign else 1)
    if t == 0:
        return zero_bits(fmt, 0), 0  # exact cancellation: +0 under RNE
    return round_pack(fmt, 1 if t < 0 else 0, abs(t), e0)


def add(fmt: FpFormat, xa: int, xb: int):
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
        rs = ua.sign if ua.sign == ub.sign else 0
        return zero_bits(fmt, rs), 0
    if ua.kind == ZERO:
        return xb, 0
    if ub.kind == ZERO:
        return xa, 0
    e0 = min(ua.e, ub.e)
    t = (ua.m << (ua.e - e0)) * (-1 if ua.sign else 1) \
        + (ub.m << (ub.e - e0)) * (-1 if ub.sign else 1)
    if t == 0:
        return zero_bits(fmt, 0), 0
    return round_pack(fmt, 1 if t < 0 else 0, abs(t), e0)


def sub(fmt: FpFormat, xa: int, xb: int):
    return add(fmt, xa, negate(fmt, xb))


def mul(fmt: FpFormat, xa: int, xb: int):
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
    return round_pack(fmt, sp, ua.m * ub.m, ua.e + ub.e)


# The four ops as the engine sees them: an opcode plus three streams,
# with ADD/SUB/MUL realised by operand steering into the one FMA core.
# The steering is defined here so the golden model, the RTL (see
# cft_opmux.sv), and the docs cannot drift apart:
#   FMA: d = a*b + c
#   ADD: d = a + c        (b := 1.0)
#   SUB: d = a - c        (b := 1.0, c sign-flipped)
#   MUL: d = a*b          (c := zero signed with sign(a)^sign(b), which
#                          preserves the sign of an exact zero product)
OP_FMA, OP_ADD, OP_SUB, OP_MUL = 0, 1, 2, 3
OP_NAMES = {OP_FMA: "fma", OP_ADD: "add", OP_SUB: "sub", OP_MUL: "mul"}


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


def compute(fmt: FpFormat, op: int, xa: int, xb: int, xc: int):
    """The engine's view: steer, then one FMA. (bits, flags)."""
    return fma(fmt, *steer(fmt, op, xa, xb, xc))
