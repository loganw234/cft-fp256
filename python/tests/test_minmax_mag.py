# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Self-tests for 754-2019 9.6's four magnitude forms of minimum and
maximum, against arbiters that share no code with the model.

The standard defines them by deferral:

    minimumMagnitude(x, y) is x if |x| < |y|, y if |y| < |x|,
    otherwise minimum(x, y).

and the same shape for the other three. So the tests below split into
the two halves that sentence has:

1. The MAGNITUDE half, where an answer is forced. Arbitrated by an
   independent restatement built from Python's own exact integers and
   `Fraction`-free real value of the encoding - `_value()` here reads
   sign/exponent/significand out of the bit pattern with no help from
   softfloat.py - so "which operand has the smaller |.|" is decided by
   arithmetic this model never touches. At fp64 the same question is
   put to CPython's native binary64 through `abs()`, a fourth lineage.
2. The DEFERRAL half, where 9.6 hands the case to minimum /
   minimumNumber / maximum / maximumNumber. Those are hand-derived
   from the standard's own text for the two ties that reach them -
   equal magnitudes of opposite sign, and a NaN operand - because
   there is no external implementation of 2019's minimumNumber to ask:
   the C library's `fmin`/`fmax` are 2008's minNum, whose signaling-NaN
   rule 2019 deliberately changed (5.3.1's NOTE: "The minNum and maxNum
   operations of the 2008 version of the standard have been replaced by
   the recommended operations of 9.6").

The invariant that ties both halves together, and the one an
implementation cannot fake: every result is one of the two operand
ENCODINGS, bit for bit, unless the result is a NaN - and then it is
this contract's canonical quiet NaN.
"""

import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, FLAG_INVALID,
    fmin, fmax, fminnum, fmaxnum,
    fminmag, fmaxmag, fminnummag, fmaxnummag,
    MINMAX_MAG_FNS, MINMAX_MAG_754, MINMAX_MAG_IMPL,
    zero_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits, unpack, is_nan, vectors,
)
from cft_golden.softfloat import NAN  # noqa: E402

FMTS = (FP32, FP64, FP128, FP256)

# The four, paired with the base operation 9.6's last clause names.
PAIRS = (
    ("min_mag",    fminmag,    fmin),
    ("minnum_mag", fminnummag, fminnum),
    ("max_mag",    fmaxmag,    fmax),
    ("maxnum_mag", fmaxnummag, fmaxnum),
)
MAXIMA = ("max_mag", "maxnum_mag")
NUMBERS = ("minnum_mag", "maxnum_mag")


# ---- an independent reading of the encoding --------------------------

def _value(fmt, bits):
    """The exact real value of a finite encoding, as a Fraction-free
    pair (sign, |x| as a Python Fraction-equivalent rational tuple).

    Written from the format descriptor alone - no call into
    softfloat.py - so that the magnitude ordering it produces is a
    second opinion rather than the model's own."""
    sign = (bits >> (fmt.width - 1)) & 1
    ef = (bits >> fmt.man_w) & fmt.exp_mask
    man = bits & fmt.man_mask
    if ef == fmt.exp_mask:
        return sign, None            # inf or NaN: no finite value
    if ef == 0:
        num, exp = man, fmt.emin - fmt.man_w
    else:
        num, exp = man | (1 << fmt.man_w), ef - fmt.bias - fmt.man_w
    return sign, (num, exp)


def _abs_cmp(fmt, xa, xb):
    """-1, 0 or 1 for |a| against |b|, from _value() alone. Infinities
    are larger than every finite magnitude and equal to each other.
    Both operands must be non-NaN."""
    sa, va = _value(fmt, xa)
    sb, vb = _value(fmt, xb)
    if va is None and vb is None:
        return 0                                     # inf vs inf
    if va is None:
        return 1
    if vb is None:
        return -1
    (na, ea), (nb, eb) = va, vb
    # Compare na*2^ea against nb*2^eb exactly, in integers.
    if ea < eb:
        nb <<= (eb - ea)
    else:
        na <<= (ea - eb)
    return (na > nb) - (na < nb)


def _is_nan_bits(fmt, bits):
    return (((bits >> fmt.man_w) & fmt.exp_mask) == fmt.exp_mask and
            (bits & fmt.man_mask) != 0)


# ---- the pool --------------------------------------------------------

def _pool(fmt):
    """Every interesting encoding, both signs, plus a signaling NaN and
    a payload-carrying quiet NaN."""
    mags = [
        zero_bits(fmt, 0),
        min_subnormal_bits(fmt),
        max_subnormal_bits(fmt),
        min_normal_bits(fmt),
        max_normal_bits(fmt),
        inf_bits(fmt, 0),
    ]
    # a couple of ordinary values between the extremes
    one = (fmt.bias << fmt.man_w)
    mags += [one, one | 1, one + (1 << fmt.man_w)]
    out = []
    for m in mags:
        out.append(m)
        out.append(m | fmt.sign_mask)
    out.append(qnan_bits(fmt))
    out.append(qnan_bits(fmt) | 5)                 # a payload
    out.append(qnan_bits(fmt) | fmt.sign_mask)     # a negative quiet NaN
    out.append(snan_bits(fmt))
    out.append(snan_bits(fmt) | fmt.sign_mask)
    return out


# ---- 1. the magnitude half, against the independent reading ----------

@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
@pytest.mark.parametrize("name,fn,base", PAIRS, ids=lambda v: getattr(v, "__name__", v))
def test_magnitude_half_matches_an_independent_ordering(fmt, name, fn, base):
    """When neither operand is a NaN and the magnitudes differ, 9.6
    forces the answer, and _abs_cmp - which reads the encoding by
    hand - is the arbiter of which."""
    pool = [b for b in _pool(fmt) if not _is_nan_bits(fmt, b)]
    checked = 0
    for xa in pool:
        for xb in pool:
            c = _abs_cmp(fmt, xa, xb)
            if c == 0:
                continue
            want = (xa if (c > 0) == (name in MAXIMA) else xb)
            got, flags = fn(fmt, xa, xb)
            assert got == want, (
                f"{name}({xa:x}, {xb:x}) at {fmt.name}: "
                f"got {got:x}, |.| ordering says {want:x}")
            assert flags == 0, f"{name} signalled {flags} on two numbers"
            checked += 1
    assert checked > 0


def test_magnitude_half_against_native_binary64():
    """The fp64 leg again, arbitrated by CPython's own binary64 abs()."""
    import struct
    fmt = FP64

    def as_float(bits):
        return struct.unpack("<d", struct.pack("<Q", bits))[0]

    pool = [b for b in _pool(fmt) if not _is_nan_bits(fmt, b)]
    for xa in pool:
        for xb in pool:
            fa, fb = abs(as_float(xa)), abs(as_float(xb))
            if fa == fb:
                continue
            assert fminmag(fmt, xa, xb)[0] == (xa if fa < fb else xb)
            assert fmaxmag(fmt, xa, xb)[0] == (xa if fa > fb else xb)
            assert fminnummag(fmt, xa, xb)[0] == (xa if fa < fb else xb)
            assert fmaxnummag(fmt, xa, xb)[0] == (xa if fa > fb else xb)


# ---- 2. the deferral half -------------------------------------------

@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
@pytest.mark.parametrize("name,fn,base", PAIRS, ids=lambda v: getattr(v, "__name__", v))
def test_equal_magnitudes_defer_to_the_base_operation(fmt, name, fn, base):
    """|x| == |y| is 9.6's "otherwise", so the answer is the base
    operation's - including its signed-zero rule. Checked against the
    base operation itself over every equal-magnitude pair the pool
    holds, which is the whole opposite-sign family plus x with x."""
    seen_opposite = 0
    for xa in _pool(fmt):
        if _is_nan_bits(fmt, xa):
            continue
        for xb in (xa, xa ^ fmt.sign_mask):
            assert fn(fmt, xa, xb) == base(fmt, xa, xb), (
                f"{name}({xa:x}, {xb:x}) at {fmt.name} must be "
                f"{MINMAX_MAG_754[name].replace('Magnitude', '')}")
            if xa != xb:
                seen_opposite += 1
    assert seen_opposite > 0


@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
def test_equal_magnitudes_opposite_sign_the_named_cases(fmt):
    """The four hand-derived rows the deferral exists for. +3 and -3
    have equal magnitude, so 9.6 hands the pair to minimum/maximum,
    and 9.6's own text for those says -0 compares less than +0 and
    +0 greater than -0."""
    three = (fmt.bias + 1) << fmt.man_w | (1 << (fmt.man_w - 1))  # 3.0
    neg3 = three | fmt.sign_mask
    assert fminmag(fmt, three, neg3)[0] == neg3
    assert fminmag(fmt, neg3, three)[0] == neg3
    assert fmaxmag(fmt, three, neg3)[0] == three
    assert fmaxmag(fmt, neg3, three)[0] == three
    assert fminnummag(fmt, three, neg3)[0] == neg3
    assert fmaxnummag(fmt, three, neg3)[0] == three

    pz, nz = zero_bits(fmt, 0), zero_bits(fmt, 1)
    assert fminmag(fmt, pz, nz)[0] == nz
    assert fminmag(fmt, nz, pz)[0] == nz
    assert fmaxmag(fmt, pz, nz)[0] == pz
    assert fmaxmag(fmt, nz, pz)[0] == pz
    assert fminnummag(fmt, pz, nz)[0] == nz
    assert fmaxnummag(fmt, nz, pz)[0] == pz

    pinf, ninf = inf_bits(fmt, 0), inf_bits(fmt, 1)
    assert fminmag(fmt, pinf, ninf)[0] == ninf
    assert fmaxmag(fmt, pinf, ninf)[0] == pinf
    assert fminnummag(fmt, ninf, pinf)[0] == ninf
    assert fmaxnummag(fmt, ninf, pinf)[0] == pinf


@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
@pytest.mark.parametrize("name,fn,base", PAIRS, ids=lambda v: getattr(v, "__name__", v))
def test_nan_operands_defer_to_the_base_operation(fmt, name, fn, base):
    """|NaN| is unordered, so BOTH magnitude tests are false and every
    NaN case is 9.6's "otherwise" - one NaN, the other NaN, and both."""
    nans = [qnan_bits(fmt), qnan_bits(fmt) | 5, qnan_bits(fmt) | fmt.sign_mask,
            snan_bits(fmt), snan_bits(fmt) | fmt.sign_mask]
    numbers = [b for b in _pool(fmt) if not _is_nan_bits(fmt, b)]
    for nan in nans:
        for other in numbers + nans:
            assert fn(fmt, nan, other) == base(fmt, nan, other)
            assert fn(fmt, other, nan) == base(fmt, other, nan)


@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
def test_nan_rules_written_out(fmt):
    """The NaN rows hand-derived from 9.6's text rather than from the
    base operation, so that a wrong base operation cannot make the
    previous test vacuous.

    9.6 for minimum: "a quiet NaN if either operand is a NaN".
    9.6 for minimumNumber: "the number if one operand is a number and
    the other is a NaN ... If both operands are NaNs, a quiet NaN is
    returned ... If either operand is a signaling NaN, an invalid
    operation exception is signaled, but unless both operands are
    NaNs, the signaling NaN is otherwise ignored"."""
    q, s = qnan_bits(fmt), snan_bits(fmt)
    x = min_normal_bits(fmt)

    # the propagating pair: a quiet NaN out whichever operand is one
    for f in (fminmag, fmaxmag):
        assert f(fmt, q, x) == (q, 0)
        assert f(fmt, x, q) == (q, 0)
        assert f(fmt, s, x) == (q, FLAG_INVALID)
        assert f(fmt, x, s) == (q, FLAG_INVALID)
        assert f(fmt, q, q) == (q, 0)
        assert f(fmt, s, q) == (q, FLAG_INVALID)
        assert f(fmt, s, s) == (q, FLAG_INVALID)

    # the ...Number pair: the number survives, and a lone signaling NaN
    # signals invalid WITHOUT becoming the result
    for f in (fminnummag, fmaxnummag):
        assert f(fmt, q, x) == (x, 0)
        assert f(fmt, x, q) == (x, 0)
        assert f(fmt, s, x) == (x, FLAG_INVALID)
        assert f(fmt, x, s) == (x, FLAG_INVALID)
        assert f(fmt, q, q) == (q, 0)
        assert f(fmt, s, q) == (q, FLAG_INVALID)
        assert f(fmt, s, s) == (q, FLAG_INVALID)


# ---- 3. subnormals and infinities, the magnitude ladder --------------

@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
def test_subnormal_and_infinite_ladder(fmt):
    """A magnitude ladder that crosses the subnormal/normal boundary and
    ends at infinity: each rung must beat the one below it, in both
    signs, for all four operations."""
    ladder = [zero_bits(fmt, 0), min_subnormal_bits(fmt),
              max_subnormal_bits(fmt), min_normal_bits(fmt),
              max_normal_bits(fmt), inf_bits(fmt, 0)]
    for i in range(len(ladder)):
        for j in range(i + 1, len(ladder)):
            lo, hi = ladder[i], ladder[j]
            for sa in (0, fmt.sign_mask):
                for sb in (0, fmt.sign_mask):
                    a, b = lo | sa, hi | sb
                    assert fminmag(fmt, a, b)[0] == a
                    assert fminmag(fmt, b, a)[0] == a
                    assert fmaxmag(fmt, a, b)[0] == b
                    assert fmaxmag(fmt, b, a)[0] == b
                    assert fminnummag(fmt, a, b)[0] == a
                    assert fmaxnummag(fmt, b, a)[0] == b


# ---- 4. the invariant ------------------------------------------------

@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
@pytest.mark.parametrize("name", MINMAX_MAG_FNS)
def test_result_is_an_operand_or_the_canonical_quiet_nan(fmt, name):
    """9.6 selects; it never computes. So the result is one of the two
    operand encodings bit for bit - except where the base operation
    delivers a NaN, which this contract canonicalises (docs/
    DETERMINISM.md), and then it is exactly qnan_bits."""
    fn = MINMAX_MAG_IMPL[name]
    pool = _pool(fmt)
    for xa in pool:
        for xb in pool:
            got, flags = fn(fmt, xa, xb)
            if is_nan(fmt, got):
                assert got == qnan_bits(fmt), (
                    f"{name}({xa:x}, {xb:x}) returned a non-canonical NaN")
            else:
                assert got in (xa, xb), (
                    f"{name}({xa:x}, {xb:x}) invented {got:x}")
            # nothing but invalid, and only from a signaling operand
            sig = any(unpack(fmt, v).kind == NAN and unpack(fmt, v).signaling
                      for v in (xa, xb))
            assert flags == (FLAG_INVALID if sig else 0)


@pytest.mark.parametrize("fmt", FMTS, ids=lambda f: f.name)
@pytest.mark.parametrize("name", MINMAX_MAG_FNS)
def test_definitional_identity_over_a_random_sweep(fmt, name):
    """The definition itself, restated over a seeded random sweep: the
    answer is x when |x| < |y|, y when |y| < |x|, and the base
    operation's otherwise. The pools come from vectors.py, which is
    where the conformance sets get theirs."""
    fn = MINMAX_MAG_IMPL[name]
    base = {"min_mag": fmin, "minnum_mag": fminnum,
            "max_mag": fmax, "maxnum_mag": fmaxnum}[name]
    ops = vectors.random_cases(fmt, 400, seed=41)
    vals = [v for case in ops for v in case[1:3]]
    for xa, xb in zip(vals[::2], vals[1::2]):
        got = fn(fmt, xa, xb)
        if _is_nan_bits(fmt, xa) or _is_nan_bits(fmt, xb):
            want = base(fmt, xa, xb)
        else:
            c = _abs_cmp(fmt, xa, xb)
            if c == 0:
                want = base(fmt, xa, xb)
            elif (c < 0) != (name in MAXIMA):
                want = (xa, 0)
            else:
                want = (xb, 0)
        assert got == want, f"{name}({xa:x}, {xb:x}) at {fmt.name}"


def test_names_table_matches_the_standards_spelling():
    """The set of four, and 754's own spelling of each - the table the
    vector sets and the C entry points are both named from."""
    assert set(MINMAX_MAG_FNS) == set(MINMAX_MAG_IMPL)
    assert set(MINMAX_MAG_FNS) == set(MINMAX_MAG_754)
    assert sorted(MINMAX_MAG_754.values()) == [
        "maximumMagnitude", "maximumMagnitudeNumber",
        "minimumMagnitude", "minimumMagnitudeNumber",
    ]
