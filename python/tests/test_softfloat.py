# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for the golden model, against arbiters that share no code
with it.

Three independent checks, per docs/DETERMINISM.md:

1. fp64 arithmetic against CPython's native binary64 - the host CPU's
   IEEE hardware, reached through a completely different lineage.
2. All four formats against mpmath's correctly-rounded arbitrary
   precision arithmetic (normal-range results; mpmath has no exponent
   bounds, so subnormal/overflow behaviour is out of its reach).
3. Hand-computed IEEE 754 edge cases with expected bit patterns written
   as literals, including the fused-vs-double-rounding witness and the
   tininess-after-rounding boundary.

A model that passes 1 and 2 but not 3 is rounding correctly and
handling the edges wrong; 3 is where FMA implementations actually die.
"""

import math
import struct
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    FLAG_INVALID, FLAG_OVERFLOW, FLAG_UNDERFLOW, FLAG_INEXACT,
    OP_FMA, OP_ADD, OP_SUB, OP_MUL,
    add, sub, mul, fma, compute, unpack,
    zero_bits, one_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits, negate, is_nan, vectors,
)

ALL_FORMATS = (FP32, FP64, FP128, FP256)


def f64_to_bits(x: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", x))[0]


def bits_to_f64(b: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", b))[0]


# ---- 1. fp64 vs native binary64 hardware -----------------------------

def _native_check(op, xa, xb, xc):
    a, c = bits_to_f64(xa), bits_to_f64(xc)
    b = bits_to_f64(xb)
    if op == OP_ADD:
        return f64_to_bits(a + c)
    if op == OP_SUB:
        return f64_to_bits(a - c)
    if op == OP_MUL:
        return f64_to_bits(a * b)
    return None


def test_fp64_add_sub_mul_match_native():
    cases = vectors.directed_cases(FP64, 6000, seed=11) + \
        vectors.random_cases(FP64, 4000, seed=12)
    checked = 0
    for op, xa, xb, xc in cases:
        if op == OP_FMA:
            continue
        got, _ = compute(FP64, op, xa, xb, xc)
        want = _native_check(op, xa, xb, xc)
        if is_nan(FP64, want):
            assert is_nan(FP64, got), (op, hex(xa), hex(xb), hex(xc))
        else:
            assert got == want, (op, hex(xa), hex(xb), hex(xc), hex(got), hex(want))
        checked += 1
    assert checked > 3000


@pytest.mark.skipif(not hasattr(math, "fma"), reason="math.fma needs Python 3.13+")
def test_fp64_fma_matches_math_fma():
    cases = vectors.random_cases(FP64, 4000, seed=13)
    checked = 0
    for op, xa, xb, xc in cases:
        a, b, c = (bits_to_f64(v) for v in (xa, xb, xc))
        if not all(math.isfinite(v) for v in (a, b, c)):
            continue
        got, flags = fma(FP64, xa, xb, xc)
        try:
            want = f64_to_bits(math.fma(a, b, c))
        except OverflowError:
            assert flags & FLAG_OVERFLOW, (hex(xa), hex(xb), hex(xc))
            continue
        assert got == want, (hex(xa), hex(xb), hex(xc), hex(got), hex(want))
        checked += 1
    assert checked > 2000


# ---- 2. all formats vs mpmath ---------------------------------------

def _mp_exact(mp, u):
    """Exact mpf of an unpacked finite value (workprec must cover m)."""
    v = mp.ldexp(u.m, u.e)
    return -v if u.sign else v


def _is_normal_or_exact_zero(fmt, bits, flags):
    ef = (bits >> fmt.man_w) & fmt.exp_mask
    frac = bits & fmt.man_mask
    if ef == fmt.exp_mask:
        return False
    if ef == 0:
        return frac == 0 and flags == 0
    return True


@pytest.mark.parametrize("fmt", ALL_FORMATS, ids=lambda f: f.name)
def test_matches_mpmath(fmt):
    mpmath = pytest.importorskip("mpmath")
    mp = mpmath.mp
    p = fmt.prec
    cases = vectors.directed_cases(fmt, 1200, seed=21) + \
        vectors.random_cases(fmt, 800, seed=22)
    checked = 0
    with mp.workprec(4 * p + 64):
        for op, xa, xb, xc in cases:
            ua, ub, uc = unpack(fmt, xa), unpack(fmt, xb), unpack(fmt, xc)
            if any(u.kind in ("inf", "nan") for u in (ua, ub, uc)):
                continue
            got, flags = compute(fmt, op, xa, xb, xc)
            if flags & (FLAG_OVERFLOW | FLAG_UNDERFLOW):
                continue
            if not _is_normal_or_exact_zero(fmt, got, flags):
                continue  # subnormal rounding is outside mpmath's model
            a, b, c = (_mp_exact(mpmath, u) for u in (ua, ub, uc))
            if op == OP_ADD:
                want = mpmath.fadd(a, c, prec=p, rounding="n")
            elif op == OP_SUB:
                want = mpmath.fsub(a, c, prec=p, rounding="n")
            elif op == OP_MUL:
                want = mpmath.fmul(a, b, prec=p, rounding="n")
            else:
                prod = mpmath.fmul(a, b, exact=True)
                want = mpmath.fadd(prod, c, prec=p, rounding="n")
            ug = unpack(fmt, got)
            got_mp = _mp_exact(mpmath, ug) if ug.kind != "zero" else mpmath.mpf(0)
            assert got_mp == want, \
                (fmt.name, op, hex(xa), hex(xb), hex(xc), hex(got))
            checked += 1
    assert checked > 400


# ---- 3. hand-computed anchors (fp32 literals) ------------------------

def test_signed_zero_rules():
    for fmt in ALL_FORMATS:
        p0, n0 = zero_bits(fmt, 0), zero_bits(fmt, 1)
        assert add(fmt, p0, n0) == (p0, 0)
        assert add(fmt, n0, p0) == (p0, 0)
        assert add(fmt, n0, n0) == (n0, 0)
        assert add(fmt, p0, p0) == (p0, 0)
        one = one_bits(fmt)
        assert sub(fmt, one, one) == (p0, 0)          # exact cancel -> +0
        assert mul(fmt, one_bits(fmt, 1), p0) == (n0, 0)   # -1 * +0 -> -0
        assert mul(fmt, one_bits(fmt, 1), one_bits(fmt, 1))[0] == one


def test_fp32_tie_to_even():
    one = 0x3F800000
    half_ulp = 0x33800000  # 2^-24
    assert add(FP32, one, half_ulp) == (one, FLAG_INEXACT)
    assert add(FP32, 0x3F800001, half_ulp) == (0x3F800002, FLAG_INEXACT)


def test_fp32_fused_single_rounding_witness():
    # (1 + 2^-23)(1 - 2^-23) - 1 == -2^-46 exactly. A double-rounded
    # mul-then-add returns +0 here; only a true fused op survives.
    got, flags = fma(FP32, 0x3F800001, 0x3F7FFFFE, 0xBF800000)
    assert got == 0xA8800000 and flags == 0
    two_step = add(FP32, mul(FP32, 0x3F800001, 0x3F7FFFFE)[0], 0xBF800000)[0]
    assert two_step == 0x00000000  # what unfused arithmetic collapses to


def test_fp32_overflow_underflow_flags():
    two = 0x40000000
    assert mul(FP32, max_normal_bits(FP32), two) == \
        (inf_bits(FP32), FLAG_OVERFLOW | FLAG_INEXACT)
    half = 0x3F000000
    # min_sub * 0.5: an exact tie at zero -> ties to even -> 0
    assert mul(FP32, min_subnormal_bits(FP32), half) == \
        (0x00000000, FLAG_UNDERFLOW | FLAG_INEXACT)
    # min_sub * 0.75 -> rounds up to min_sub
    assert mul(FP32, min_subnormal_bits(FP32), 0x3F400000) == \
        (0x00000001, FLAG_UNDERFLOW | FLAG_INEXACT)
    # max_sub * 0.5 = (2^23-1)/2 subnormal ulps: a tie, and the even
    # neighbour is 2^22 ulps -> 0x00400000, still tiny and inexact
    assert mul(FP32, max_subnormal_bits(FP32), half) == \
        (0x00400000, FLAG_UNDERFLOW | FLAG_INEXACT)


def test_fp32_tininess_after_rounding_boundary():
    # 0.75 * min_sub + max_sub rounds (at the subnormal ulp) UP to
    # exactly min_normal. Tininess detected after rounding: the
    # as-if-unbounded result is min_normal, not tiny, so the underflow
    # flag must NOT rise. A before-rounding implementation raises it.
    got, flags = fma(FP32, 0x3F400000, min_subnormal_bits(FP32),
                     max_subnormal_bits(FP32))
    assert got == min_normal_bits(FP32)
    assert flags == FLAG_INEXACT


def test_subnormal_boundary_exact():
    for fmt in ALL_FORMATS:
        # max_sub + min_sub == min_normal exactly, no flags
        assert add(fmt, max_subnormal_bits(fmt), min_subnormal_bits(fmt)) == \
            (min_normal_bits(fmt), 0)


def test_nan_and_invalid():
    for fmt in ALL_FORMATS:
        q = qnan_bits(fmt)
        assert add(fmt, q | 0x5, one_bits(fmt)) == (q, 0)       # canonical out
        assert add(fmt, fmt.sign_mask | q, one_bits(fmt)) == (q, 0)
        assert add(fmt, snan_bits(fmt), one_bits(fmt)) == (q, FLAG_INVALID)
        assert mul(fmt, inf_bits(fmt), zero_bits(fmt)) == (q, FLAG_INVALID)
        assert add(fmt, inf_bits(fmt, 0), inf_bits(fmt, 1)) == (q, FLAG_INVALID)
        assert add(fmt, inf_bits(fmt, 0), inf_bits(fmt, 0)) == (inf_bits(fmt), 0)
        assert fma(fmt, max_normal_bits(fmt), max_normal_bits(fmt),
                   inf_bits(fmt, 1)) == (inf_bits(fmt, 1), 0)


def test_generic_ladder_edges():
    # format-algebra versions of the fp32 anchors, all four widths
    for fmt in ALL_FORMATS:
        one = one_bits(fmt)
        # 1 + 2^-p ties to even -> 1, inexact
        half_ulp = (fmt.bias - fmt.prec) << fmt.man_w
        assert add(fmt, one, half_ulp) == (one, FLAG_INEXACT)
        assert add(fmt, one | 1, half_ulp) == (one | 2, FLAG_INEXACT)
        # all-ones mantissa + 1 ulp carries out to the next binade
        allones = one | fmt.man_mask
        ulp = (fmt.bias - fmt.man_w) << fmt.man_w
        assert add(fmt, allones, ulp) == (one + (1 << fmt.man_w), 0)


def test_steering_composition():
    # the engine's operand-steering trick must be exactly equivalent to
    # the direct definitions, specials and signed zeros included
    for fmt in (FP32, FP256):
        cases = vectors.directed_cases(fmt, 3000, seed=31) + \
            vectors.random_cases(fmt, 1000, seed=32)
        for _, xa, xb, xc in cases:
            assert compute(fmt, OP_ADD, xa, 0, xc) == add(fmt, xa, xc)
            assert compute(fmt, OP_SUB, xa, 0, xc) == sub(fmt, xa, xc)
            assert compute(fmt, OP_MUL, xa, xb, 0) == mul(fmt, xa, xb)


def test_pack_unpack_roundtrip():
    import random
    rng = random.Random(41)
    for fmt in ALL_FORMATS:
        for _ in range(2000):
            bits = rng.getrandbits(fmt.width)
            u = unpack(fmt, bits)
            if u.kind in ("nan", "inf", "zero"):
                continue
            got, flags = add(fmt, bits, zero_bits(fmt))
            assert got == bits and flags == 0
