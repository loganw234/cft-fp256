# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""pytest for cftmpfr: the binding is faithful, or this file says where.

Scope, deliberately: the LIBRARY is proven elsewhere (the golden
model's suites, 23.9B CPU cases, the 999,000-case MPFR parity run in
host/tools/mpfr_check.c). What a binding can break is everything in
between - byte order, operand slots, flag plumbing, conversions - so
that is what this file attacks: conversions must round-trip
bit-exactly, scalar results must match gmpy2's IEEE emulation bit for
bit, the batch path must equal the scalar path, and the flag words
must be the contract's. Values are compared as ENCODINGS, because
"close" is not a concept here.

RNDNA is compared against gmpy2 only on directed tie cases: MPFR has
no ties-to-away mode to compare against (that is the point of
exposing it), and its deep verification lives in mpfr_check.c's
oracle construction. The directed cases prove the attribute is
routed, not re-prove the arithmetic.

Runs without gmpy2 (interop tests skip, refusal tests still run) and
without numpy (container tests skip). A negative control proves the
comparison machinery can actually fail.
"""

import math
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cftmpfr
from cftmpfr import Context, batch, core

try:
    import gmpy2
except ImportError:
    gmpy2 = None

try:
    import numpy as np
except ImportError:
    np = None

needs_gmpy2 = pytest.mark.skipif(gmpy2 is None, reason="gmpy2 not installed")
needs_numpy = pytest.mark.skipif(np is None, reason="numpy not installed")

PRECISIONS = (24, 53, 113, 237)
WIDTH = {24: 32, 53: 64, 113: 128, 237: 256}
GMPY_MODES = {"RNDN": "RoundToNearest", "RNDZ": "RoundToZero",
              "RNDD": "RoundDown", "RNDU": "RoundUp"}


# ---------------------------------------------------------------------
# operand pools: the specials every format argument list should meet,
# plus exponent-banded randoms (uniform bits almost never land near
# the exponent edges where formats differ)
# ---------------------------------------------------------------------

def geometry(prec):
    fi = core._BY_PRECISION[prec]
    return fi.width, fi.exp_w, fi.man_w


def specials(prec):
    width, exp_w, man_w = geometry(prec)
    emask = (1 << exp_w) - 1
    mmask = (1 << man_w) - 1
    top = 1 << (width - 1)
    one = (emask >> 1) << man_w                      # biased bias -> 1.0
    return [
        0, top,                                      # +0 -0
        emask << man_w, top | (emask << man_w),      # +inf -inf
        (emask << man_w) | (1 << (man_w - 1)),       # canonical qNaN
        (emask << man_w) | 1,                        # sNaN
        1, mmask,                                    # min/max subnormal
        1 << man_w, ((emask - 1) << man_w) | mmask,  # min/max normal
        one, one | 1,                                # 1.0, 1.0+ulp
        one - 1,                                     # largest < 1.0
        one + (1 << man_w),                          # 2.0
        top | one,                                   # -1.0
        (one + (1 << man_w)) | (1 << (man_w - 1)),   # 3.0
    ]


def randoms(prec, count, seed):
    width, exp_w, man_w = geometry(prec)
    rng = random.Random(seed * 100003 + width)
    emask = (1 << exp_w) - 1
    out = []
    for _ in range(count):
        bits = rng.getrandbits(width)
        if rng.random() < 0.35:
            # band the exponent toward the edges, as the repo's own
            # harnesses do - that is where formats earn their keep
            e = rng.choice((0, 1, 2, emask >> 1, emask - 2, emask - 1))
            bits = (bits & ~(emask << man_w)) | (e << man_w)
        out.append(bits)
    return out


def pool(prec, count=28, seed=7):
    return specials(prec) + randoms(prec, count, seed)


# ---------------------------------------------------------------------
# gmpy2 oracle plumbing
# ---------------------------------------------------------------------

def gmpy_op(prec, mode, op, args):
    """One operation through gmpy2's IEEE emulation of the format, in
    the given mode. args are mpfr values; returns the mpfr result."""
    save = gmpy2.get_context()
    ctx = gmpy2.ieee(WIDTH[prec])
    ctx.round = getattr(gmpy2, GMPY_MODES[mode])
    gmpy2.set_context(ctx)
    try:
        if op == "add":
            return gmpy2.add(args[0], args[1])
        if op == "sub":
            return gmpy2.sub(args[0], args[1])
        if op == "mul":
            return gmpy2.mul(args[0], args[1])
        if op == "fma":
            return gmpy2.fma(args[0], args[1], args[2])
        if op == "div":
            return gmpy2.div(args[0], args[1])
        return gmpy2.sqrt(args[0])
    finally:
        gmpy2.set_context(save)


def cft_op(ctx, op, args):
    if op == "fma":
        return ctx.fma(*args)
    return getattr(ctx, op)(*args)


NARGS = {"add": 2, "sub": 2, "mul": 2, "fma": 3, "div": 2, "sqrt": 1}


# ---------------------------------------------------------------------
# conversions
# ---------------------------------------------------------------------

@pytest.mark.parametrize("prec", PRECISIONS)
def test_bits_roundtrip(prec):
    ctx = Context(prec)
    for bits in pool(prec):
        f = ctx.from_bits(bits)
        assert f.to_bits() == bits
        assert ctx.from_bytes(f.to_bytes()).to_bits() == bits


@pytest.mark.parametrize("prec", PRECISIONS)
def test_int_conversions_exact(prec):
    ctx = Context(prec)
    for n in (0, 1, -1, 2, 7, -100, 1 << (prec - 1), (1 << prec) - 1,
              -(1 << prec), 10**6):
        f = ctx.from_int(n)
        assert f.to_int() == n
        assert ctx.last_flags == 0    # each of these fits exactly
    # truncation toward zero, both signs
    assert ctx.div(ctx(7), ctx(2)).to_int() == 3
    assert ctx.div(ctx(-7), ctx(2)).to_int() == -3


def test_int_conversion_inexact_refuses_without_gmpy2(monkeypatch):
    ctx = Context(24)
    monkeypatch.setattr(core, "gmpy2", None)
    with pytest.raises(RuntimeError, match="gmpy2"):
        ctx.from_int((1 << 30) + 1)   # 31 significant bits into 24


@needs_gmpy2
@pytest.mark.parametrize("mode", ("RNDN", "RNDD"))
@pytest.mark.parametrize("prec", PRECISIONS)
def test_int_conversion_inexact_matches_gmpy2(prec, mode):
    ctx = Context(prec, mode)
    n = (1 << (prec + 9)) + 12345    # forces rounding at every precision
    got = ctx.from_int(n)
    assert ctx.last_flags & cftmpfr.FLAG_INEXACT
    save = gmpy2.get_context()
    ictx = gmpy2.ieee(WIDTH[prec])
    ictx.round = getattr(gmpy2, GMPY_MODES[mode])
    gmpy2.set_context(ictx)
    want = gmpy2.mpfr(n)
    gmpy2.set_context(save)
    assert got.same_bits(ctx.from_mpfr(want))


@pytest.mark.parametrize("prec", (53, 113, 237))
def test_from_float_exact_wide(prec):
    ctx = Context(prec)
    for x in (0.5, -1.5, 3.141592653589793, 2.0**-1074, -2.0**1023,
              float("inf"), -0.0):
        f = ctx.from_float(x)
        back = f.to_float()
        assert back == x or (x != x and back != back)
        # sign of zero survives
        if x == 0.0:
            assert str(back) == str(x)


@needs_gmpy2
def test_from_float_narrowing_matches_gmpy2():
    ctx = Context(24)
    for x in (0.1, 1.0 + 2**-30, 6e38, 1e-45, -1e-42):
        got = ctx.from_float(x)
        save = gmpy2.get_context()
        gmpy2.set_context(gmpy2.ieee(32))
        want = gmpy2.mpfr(x)
        gmpy2.set_context(save)
        assert got.same_bits(ctx.from_mpfr(want)), f"x={x}"


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
def test_mpfr_roundtrip_bit_exact(prec):
    """Float -> mpfr -> Float is the identity for every non-NaN
    encoding, and class-preserving for NaNs (MPFR has exactly one NaN;
    ours canonicalises to the contract's)."""
    ctx = Context(prec)
    for bits in pool(prec, count=60, seed=11):
        f = ctx.from_bits(bits)
        back = ctx.from_mpfr(f.to_mpfr())
        if f.is_nan:
            assert back.same_bits(ctx.nan())
        else:
            assert back.same_bits(f), hex(bits)


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
def test_str_roundtrip(prec):
    ctx = Context(prec)   # RNDN: to_str's readback guarantee is stated for it
    for bits in pool(prec, count=12, seed=13):
        f = ctx.from_bits(bits)
        if f.is_nan:
            assert ctx.from_str(f.to_str()).is_nan
        else:
            assert ctx.from_str(f.to_str()).same_bits(f), hex(bits)


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
def test_from_str_negative_zero(prec):
    """The sign of a parsed zero is the decimal's sign, on every gmpy2.
    gmpy2 2.1.2 parses "-0" to an unsigned zero inside an ieee()
    context, which turned -0 into +0 through from_str on that version
    and failed test_str_roundtrip at every precision (2026-09-02). A
    negative decimal below the format's smallest subnormal rounds to
    -0 under RNDN as well: rounding never changes a sign."""
    ctx = Context(prec)
    for s in ("-0", "-0.0", "-0e0", " -0.0e+00", "-1e-99999"):
        f = ctx.from_str(s)
        assert f.is_zero and f.sign == 1, (s, f)
    for s in ("0", "+0", "0.0", "1e-99999"):
        f = ctx.from_str(s)
        assert f.is_zero and f.sign == 0, (s, f)
    # and the round trip that found it, on both zeros explicitly
    for f in (ctx.zero(0), ctx.zero(1)):
        assert ctx.from_str(f.to_str()).same_bits(f), f


@pytest.mark.parametrize("prec", PRECISIONS)
def test_from_str_specials_need_no_library(prec):
    """to_str writes nan, inf, -inf and the zeros without gmpy2, so
    from_str reads them back without it - and without gmpy2 2.1.2's
    opinion, which is "invalid digits" for every spelling of inf and
    nan. Whitespace either side is tolerated on every version."""
    ctx = Context(prec)
    for s in ("nan", "NaN", "-nan", "+NAN", " nan "):
        f = ctx.from_str(s)
        assert f.is_nan, s
        assert ctx.last_flags == 0
    for s, sign in (("inf", 0), ("+inf", 0), ("Infinity", 0), ("-inf", 1),
                    ("-INFINITY", 1), (" -inf ", 1)):
        f = ctx.from_str(s)
        assert f.is_inf and f.sign == sign, s
    for f in (ctx.nan(), ctx.inf(0), ctx.inf(1), ctx.zero(0), ctx.zero(1)):
        back = ctx.from_str(f.to_str())
        assert back.is_nan if f.is_nan else back.same_bits(f), f


@needs_gmpy2
def test_to_float_narrowing_from_fp256():
    ctx = Context(237)
    third = ctx.div(ctx(1), ctx(3))
    assert third.to_float() == 1.0 / 3.0   # both correctly rounded RNE


def test_specials_constructors():
    ctx = Context(53)
    assert ctx.nan().is_nan and not ctx.nan().sign
    assert ctx.inf(1).is_inf and ctx.inf(1).sign == 1
    assert ctx.zero(1).is_zero and ctx.zero(1).sign == 1
    assert ctx.nan().to_bits() == 0x7FF8000000000000


# ---------------------------------------------------------------------
# scalar arithmetic against gmpy2's IEEE emulation
# ---------------------------------------------------------------------

@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", tuple(GMPY_MODES))
def test_scalar_ops_vs_gmpy2(prec, mode):
    ctx = Context(prec, mode)
    ops_pool = pool(prec, count=24, seed=17)
    floats = [ctx.from_bits(b) for b in ops_pool]
    mpfrs = [f.to_mpfr() for f in floats]
    rng = random.Random(prec * 31 + len(mode))
    for op, nargs in NARGS.items():
        cases = [tuple(rng.randrange(len(floats)) for _ in range(nargs))
                 for _ in range(90)]
        # and every special meets the op at least once
        cases += [tuple((i + k) % len(floats) for k in range(nargs))
                  for i in range(len(specials(prec)))]
        for idx in cases:
            got = cft_op(ctx, op, [floats[i] for i in idx])
            want = gmpy_op(prec, mode, op, [mpfrs[i] for i in idx])
            wantf = ctx.from_mpfr(want)
            if wantf.is_nan:
                assert got.is_nan, (op, mode, [hex(ops_pool[i]) for i in idx])
            else:
                assert got.same_bits(wantf), \
                    (op, mode, [hex(ops_pool[i]) for i in idx],
                     hex(got.to_bits()), hex(wantf.to_bits()))


@pytest.mark.parametrize("prec", PRECISIONS)
def test_rndna_directed_ties(prec):
    """RNDNA has no gmpy2 oracle (MPFR's RNDA is away-on-ANY-inexact,
    not ties-away), so the routing is proven on constructed ties where
    ties-away and ties-even disagree; the arithmetic behind it is
    mpfr_check.c's 999,000-case burden, not this test's."""
    fi = core._BY_PRECISION[prec]
    na = Context(prec, "RNDNA")
    ne = Context(prec, "RNDN")
    one = ((1 << (fi.exp_w - 1)) - 1) << fi.man_w
    half_ulp = na.from_bits((fi.bias - fi.prec) << fi.man_w)  # 2^-prec
    # 1 + 2^-prec is an exact tie: even keeps 1, away takes the ulp
    away = na.add(na.from_bits(one), half_ulp)
    even = ne.add(ne.from_bits(one), ne.from_bits(half_ulp.to_bits()))
    assert away.to_bits() == one + 1
    assert even.to_bits() == one
    # mirrored in the negative direction: away is away from ZERO
    neg = na.sub(na.zero(), na.add(na.from_bits(one), half_ulp))
    assert neg.to_bits() == (1 << (fi.width - 1)) | (one + 1)
    # a tie on the subnormal grid: min_subnormal / 2
    grid_tie = na.mul(na.from_bits(1), na.from_float(0.5))
    assert grid_tie.to_bits() == 1                 # away: up to min_sub
    assert na.last_flags & cftmpfr.FLAG_UNDERFLOW
    even_tie = ne.mul(ne.from_bits(1), ne.from_float(0.5))
    assert even_tie.to_bits() == 0                 # even: down to +0


# ---------------------------------------------------------------------
# batch == scalar, containers, broadcast
# ---------------------------------------------------------------------

@pytest.mark.parametrize("prec", PRECISIONS)
def test_batch_bit_identical_to_scalar_with_flags(prec):
    ctx = Context(prec)
    bits = pool(prec, count=40, seed=23)
    xs = [ctx.from_bits(b) for b in bits]
    ys = list(reversed(xs))
    zs = xs[1:] + xs[:1]
    for op, args in (("add", (xs, ys)), ("sub", (xs, ys)),
                     ("mul", (xs, ys)), ("fma", (xs, ys, zs)),
                     ("div", (xs, ys)), ("sqrt", (xs,))):
        out, batch_flags = getattr(batch, op)(ctx, *args)
        want_flags = 0
        for i, row in enumerate(zip(*args)):
            s = cft_op(ctx, op, list(row))
            want_flags |= ctx.last_flags
            assert out[i].same_bits(s), (op, i, hex(bits[i]))
        # the batch flag word is the OR across elements, not the last one
        assert batch_flags == want_flags, op


@pytest.mark.parametrize("prec", (53, 237))
def test_batch_containers_and_broadcast(prec):
    ctx = Context(prec)
    esz = core._BY_PRECISION[prec].esz
    xs = [ctx.from_int(i) for i in range(1, 9)]
    packed = b"".join(f.to_bytes() for f in xs)
    # bytes in -> bytes out, same values as list in -> list out
    out_l, fl_l = batch.mul(ctx, xs, xs)
    out_b, fl_b = batch.mul(ctx, packed, packed)
    assert isinstance(out_b, bytes)
    assert out_b == b"".join(f.to_bytes() for f in out_l)
    assert fl_l == fl_b
    # broadcast Float coefficient (the Horner step)
    out_c, _ = batch.fma(ctx, xs, xs, ctx.from_int(1))
    assert [f.to_int() for f in out_c] == [i * i + 1 for i in range(1, 9)]
    # a lone scalar everywhere is refused with directions
    with pytest.raises(TypeError, match="broadcast"):
        batch.sqrt(ctx, ctx.from_int(2))
    # ragged lengths are refused
    with pytest.raises(ValueError, match="lengths"):
        batch.add(ctx, xs, xs[:-1])


@needs_numpy
def test_batch_numpy_containers():
    # native dtype at binary64
    ctx = Context(53)
    a = np.array([1.0, 2.5, -3.0, 0.125], dtype=np.float64)
    out, fl = batch.add(ctx, a, a)
    assert isinstance(out, np.ndarray) and out.dtype == np.float64
    assert out.tolist() == (a + a).tolist()   # exact ops: numpy agrees
    # void dtype at binary256
    c256 = Context(237)
    xs = [c256.from_int(i) for i in (2, 3, 5, 7)]
    va = np.frombuffer(b"".join(f.to_bytes() for f in xs), dtype="V32")
    out, fl = batch.mul(c256, va, va)
    assert isinstance(out, np.ndarray) and out.dtype == np.dtype("V32")
    squares = [c256.from_bytes(bytes(v)).to_int() for v in out]
    assert squares == [4, 9, 25, 49]
    # a float64 array is NOT a binary256 batch, and says so
    with pytest.raises(ValueError, match="convert explicitly"):
        batch.add(c256, a, a)


@pytest.mark.parametrize("prec", (24, 237))
def test_tree_reductions(prec):
    ctx = Context(prec)
    xs = [ctx.from_int(i) for i in range(1, 12)]   # 11: not a power of two
    total, fl = batch.tree_sum(ctx, xs)
    assert total.to_int() == 66 and fl == 0
    dot, fl = batch.tree_dot(ctx, xs, xs)
    assert dot.to_int() == sum(i * i for i in range(1, 12))
    # the contract's edges: n=0 is +0 raising nothing; n=1 is verbatim
    empty, fl = batch.tree_sum(ctx, [])
    assert empty.is_zero and empty.sign == 0 and fl == 0
    lone, fl = batch.tree_sum(ctx, [ctx.nan()])
    assert lone.same_bits(ctx.nan()) and fl == 0


@pytest.mark.parametrize("prec", (24, 237))
def test_tree_sumsq_and_sumabs(prec):
    """The other two of 9.4's sum reductions, and the identities that
    are how the two backends are made to agree."""
    ctx = Context(prec)
    xs = [ctx.from_int(i) for i in range(1, 12)]     # 11: not a power of two
    signed = [x if i % 2 else ctx.neg(x) for i, x in enumerate(xs)]

    sq, fl = batch.tree_sumsq(ctx, xs)
    assert sq.to_int() == sum(i * i for i in range(1, 12)) and fl == 0
    ab, fl = batch.tree_sumabs(ctx, signed)
    assert ab.to_int() == sum(range(1, 12)) and fl == 0

    # the identities, through the binding's own entry points
    dot, fdot = batch.tree_dot(ctx, signed, signed)
    sq2, fsq = batch.tree_sumsq(ctx, signed)
    assert sq2.same_bits(dot) and fsq == fdot

    # abs signals nothing at all (5.5.1), so the pass contributes no
    # flags and the tree's are the operation's
    absed = [ctx.abs(v) for v in signed]
    s, fs = batch.tree_sum(ctx, absed)
    ab2, fab = batch.tree_sumabs(ctx, signed)
    assert ab2.same_bits(s) and fab == fs

    # 9.4 puts an infinity ahead of a NaN for these two and only these
    mixed = [ctx.inf(), ctx.nan(), ctx(1)]
    sq3, fl = batch.tree_sumsq(ctx, mixed)
    assert sq3.same_bits(ctx.inf()) and fl == 0
    ab3, fl = batch.tree_sumabs(ctx, mixed)
    assert ab3.same_bits(ctx.inf()) and fl == 0
    # the negative control: the plain tree returns the quiet NaN there
    d3, _ = batch.tree_dot(ctx, mixed, mixed)
    assert d3.is_nan

    # the edges, which the sum tree decides
    empty, fl = batch.tree_sumsq(ctx, [])
    assert empty.is_zero and empty.sign == 0 and fl == 0
    empty, fl = batch.tree_sumabs(ctx, [])
    assert empty.is_zero and empty.sign == 0 and fl == 0


@pytest.mark.parametrize("prec", (24, 237))
def test_scaled_products(prec):
    """The three that return a pair, and the property they exist for."""
    ctx = Context(prec)
    F = cftmpfr

    # 2^100 four times over: the true product is 2^400, hundreds of
    # binades outside binary32, and it comes back exactly.
    big = ctx.from_int(2 ** 100)
    pr, sf, fl = batch.scaled_prod(ctx, [big] * 4)
    assert pr.to_int() == 1 and sf == 400 and fl == 0

    # pr is always in [1, 2): the invariant the operation rests on
    xs = [ctx.from_int(i) for i in range(1, 12)]
    pr, sf, fl = batch.scaled_prod(ctx, xs)
    one, two = ctx(1), ctx(2)
    assert not (pr < one) and pr < two
    # and the pair really is 11! = 39916800, which every rung holds
    # exactly (2^8 x 155925, and 155925 needs 18 bits)
    assert math.ldexp(pr.to_float(), sf) == 39916800.0 and fl == 0

    # 9.4's empty case: the multiplicative identity, silently
    pr, sf, fl = batch.scaled_prod(ctx, [])
    assert pr.to_int() == 1 and sf == 0 and fl == 0
    for fn in (batch.scaled_prod_sum, batch.scaled_prod_diff):
        pr, sf, fl = fn(ctx, [], [])
        assert pr.to_int() == 1 and sf == 0 and fl == 0

    # the sums and differences: (1+1)*(3+1) = 8, (1-1)*(3-1) = 0
    a = [ctx(1), ctx(3)]
    b = [ctx(1), ctx(1)]
    pr, sf, fl = batch.scaled_prod_sum(ctx, a, b)
    assert pr.to_int() == 1 and sf == 3 and fl == 0
    pr, sf, fl = batch.scaled_prod_diff(ctx, a, b)
    assert pr.is_zero and pr.sign == 0 and sf == 0 and fl == 0

    # 9.4's rows: inf x 0 is invalid, an infinity alone is not
    pr, sf, fl = batch.scaled_prod(ctx, [ctx.inf(), ctx.zero()])
    assert pr.is_nan and sf == 0 and fl == F.FLAG_INVALID
    pr, sf, fl = batch.scaled_prod(ctx, [ctx.inf(), ctx(-2)])
    assert pr.is_inf and pr.sign == 1 and sf == 0 and fl == 0
    pr, sf, fl = batch.scaled_prod(ctx, [ctx.zero(1), ctx(-2)])
    assert pr.is_zero and pr.sign == 0 and sf == 0 and fl == 0

    # a length disagreement is a refusal, not a short read
    with pytest.raises(ValueError):
        batch.scaled_prod_sum(ctx, [ctx(1), ctx(2)], [ctx(1)])


def test_scaled_prod_survives_what_the_plain_product_does_not():
    """The NEGATIVE CONTROL for the whole operation, at binary32 where
    the format's edge can be named by its bits: eight copies of the
    largest finite value have a product 900-odd binades outside the
    format, and scaledProd returns it with no overflow at all - where
    ONE multiply of two of them is already an infinity."""
    ctx = Context(24)
    F = cftmpfr
    big = ctx.from_bits(0x7F7FFFFF)                  # max normal
    pr, sf, fl = batch.scaled_prod(ctx, [big] * 8)
    assert not (fl & (F.FLAG_OVERFLOW | F.FLAG_UNDERFLOW | F.FLAG_INVALID))
    assert not pr.is_inf and not pr.is_nan and not pr.is_zero
    assert sf > 1000                                 # 8 x ~127 binades

    sq, mfl = batch.mul(ctx, [big], [big])
    assert sq[0].is_inf and (mfl & F.FLAG_OVERFLOW)

    # and the same at the other end: eight minimum subnormals
    tiny = ctx.from_bits(1)
    pr, sf, fl = batch.scaled_prod(ctx, [tiny] * 8)
    assert not (fl & (F.FLAG_OVERFLOW | F.FLAG_UNDERFLOW | F.FLAG_INVALID))
    assert sf == -8 * 149 and pr.to_int() == 1
    sq, mfl = batch.mul(ctx, [tiny], [tiny])
    assert sq[0].is_zero and (mfl & F.FLAG_UNDERFLOW)


# ---------------------------------------------------------------------
# flag words
# ---------------------------------------------------------------------

def test_flag_words_directed():
    ctx = Context(53)
    F = cftmpfr
    big = ctx.from_bits(0x7FEFFFFFFFFFFFFF)          # max normal
    tiny = ctx.from_bits(1)                          # min subnormal
    snan = ctx.from_bits(0x7FF0000000000001)

    ctx.add(ctx(1), ctx(1))
    assert ctx.last_flags == 0
    ctx.add(big, big)
    assert ctx.last_flags == F.FLAG_OVERFLOW | F.FLAG_INEXACT
    ctx.div(ctx(1), ctx.zero())
    assert ctx.last_flags == F.FLAG_DIVBYZERO
    ctx.div(ctx.zero(), ctx.zero())
    assert ctx.last_flags == F.FLAG_INVALID
    ctx.sqrt(ctx(-1))
    assert ctx.last_flags == F.FLAG_INVALID
    ctx.add(snan, ctx(1))
    assert ctx.last_flags == F.FLAG_INVALID
    ctx.mul(tiny, ctx.from_float(0.5))
    assert ctx.last_flags == F.FLAG_UNDERFLOW | F.FLAG_INEXACT
    ctx.div(ctx(1), ctx(3))
    assert ctx.last_flags == F.FLAG_INEXACT
    # the quiet predicates say exactly one thing, and it is not hidden:
    # invalid for a signaling NaN operand (754 5.11), nothing otherwise
    assert (snan == ctx(1)) is False
    assert ctx.last_flags == F.FLAG_INVALID
    assert (ctx.nan() < ctx(1)) is False
    assert ctx.last_flags == 0
    # the sticky word is the OR of everything above, and clears
    assert ctx.flags == (F.FLAG_INVALID | F.FLAG_DIVBYZERO |
                         F.FLAG_OVERFLOW | F.FLAG_UNDERFLOW |
                         F.FLAG_INEXACT)
    assert set(ctx.flag_names()) == {"invalid", "divbyzero", "overflow",
                                     "underflow", "inexact"}
    ctx.clear_flags()
    assert ctx.flags == 0


# ---------------------------------------------------------------------
# error paths and graceful degradation
# ---------------------------------------------------------------------

def test_unsupported_precision_names_the_four():
    with pytest.raises(ValueError) as e:
        Context(100)
    msg = str(e.value)
    for p in ("24", "53", "113", "237"):
        assert p in msg
    with pytest.raises(ValueError):
        Context("binary80")


def test_bad_rounding_is_named_not_numbered():
    with pytest.raises(ValueError, match="names, not numbers"):
        Context(53, rounding=2)
    with pytest.raises(ValueError, match="RNDN"):
        Context(53, rounding="RNDA")   # deliberately: RNDA is NOT RNDNA


def test_mixed_precision_refused():
    a = Context(53)
    b = Context(237)
    with pytest.raises(ValueError, match="mixed precisions"):
        a.add(a(1), b(1))
    with pytest.raises(ValueError, match="mixed precisions"):
        batch.add(b, [b(1)], a(1))


def test_rndna_inexact_conversions_refused():
    ctx = Context(24, "RNDNA")
    assert ctx.from_int(3).to_int() == 3            # exact: fine
    with pytest.raises(ValueError, match="ties"):
        ctx.from_int((1 << 30) + 1)
    # from_str no longer refuses under RNDNA: since the 0.6 step it
    # rounds through the LIBRARY's decimal parse, which implements the
    # attribute MPFR does not have. The refusal above is the from_int
    # route, which still goes through gmpy2.
    assert ctx.from_str("0.5").to_float() == 0.5
    away = ctx.from_str("16777217")          # exactly halfway at binary32
    assert away.to_bits() == 0x4b800001, hex(away.to_bits())
    assert Context(24).from_str("16777217").to_bits() == 0x4b800000


def test_gmpy2_absent_paths(monkeypatch):
    ctx = Context(237)
    exact = ctx.from_float(1.5)     # exact routes never need gmpy2
    monkeypatch.setattr(core, "gmpy2", None)
    assert ctx.from_int(10).to_int() == 10
    assert exact.to_float() == 1.5
    # from_str needs no gmpy2 since the 0.6 step - it is the library's
    # own decimal parse now, and this is the check that says so.
    assert ctx.from_str("0.1").to_decimal(17) == "1.0000000000000000e-1"
    assert ctx.from_decimal("0.1").same_bits(ctx.from_str("0.1"))
    assert ctx.from_hex("0x1.8p+1").to_decimal() == "3e+0"
    with pytest.raises(RuntimeError, match="gmpy2"):
        exact.to_mpfr()
    third = ctx.div(ctx.from_int(1), ctx.from_int(3))
    with pytest.raises(RuntimeError, match="gmpy2"):
        third.to_float()            # narrowing 237 -> 53 needs rounding
    # specials never need gmpy2 anywhere
    assert ctx.nan().to_str() == "nan"
    assert ctx.inf(1).to_str() == "-inf"


def test_type_refusals():
    ctx = Context(53)
    with pytest.raises(TypeError, match="bool"):
        ctx(True)
    with pytest.raises(TypeError):
        ctx.from_int(1.5)
    with pytest.raises(TypeError):
        batch.add(ctx, object(), [ctx(1)])


# ---------------------------------------------------------------------
# the bind-time audit of the transcribed constants
# ---------------------------------------------------------------------

def _rebind():
    """Force _lib to bind (and audit) a fresh handle, restoring the
    module's singleton afterwards whatever happens."""
    from cftmpfr import _lib
    saved = _lib._LIB
    _lib._LIB = None
    try:
        _lib.lib()
    finally:
        _lib._LIB = saved


def test_audit_accepts_the_library_it_ships_with():
    """The audit runs on every bind, so this is mostly a statement that
    the transcription and the built library agree right now."""
    _rebind()


def test_audit_rejects_a_mistranscribed_opcode():
    """The audit is why the numbers in _lib.py are allowed to be typed
    by hand at all; an audit never seen failing would not be. Move one
    opcode to a number the library calls something else and the bind
    must refuse - the failure it prevents is a wrong operation computed
    quietly, not a crash."""
    from cftmpfr import _lib
    saved = _lib.OP_MUL
    _lib.OP_MUL = _lib.OP_ABS          # the library calls 4 "abs"
    try:
        with pytest.raises(RuntimeError, match="disagrees with the library"):
            _rebind()
    finally:
        _lib.OP_MUL = saved
    _rebind()                          # and the restored value binds again


def test_audit_rejects_a_foreign_abi_major():
    """cft.h says to check the ABI of the library actually loaded, not
    the header this was written against. A different major means the
    opcode and format numbers cannot be assumed to still mean what they
    say, so the bind refuses rather than guessing."""
    from cftmpfr import _lib
    saved = _lib.ABI_MAJOR
    _lib.ABI_MAJOR = saved + 1
    try:
        with pytest.raises(RuntimeError, match="reports ABI"):
            _rebind()
    finally:
        _lib.ABI_MAJOR = saved
    _rebind()


# ---------------------------------------------------------------------
# the negative control: prove the comparison can fail
# ---------------------------------------------------------------------

def test_negative_control_bitflip_detected():
    """A comparison that cannot fail proves nothing. Corrupt one bit of
    a correct result and every equality used above must call it out."""
    ctx = Context(53)
    good = ctx.add(ctx(1), ctx(3))
    bad = ctx.from_bits(good.to_bits() ^ 1)
    assert not bad.same_bits(good)
    if gmpy2 is not None:
        want = ctx.from_mpfr(gmpy_op(53, "RNDN", "add",
                                     (gmpy2.mpfr(1), gmpy2.mpfr(3))))
        assert want.same_bits(good)
        assert not want.same_bits(bad)


@needs_gmpy2
def test_negative_control_wrong_rounding_detected():
    """The oracle comparison is sensitive to the rounding attribute: the
    same case under a deliberately wrong gmpy2 mode must disagree."""
    ctx = Context(53, "RNDN")
    got = ctx.div(ctx(1), ctx(3))
    right = ctx.from_mpfr(gmpy_op(53, "RNDN", "div",
                                  (gmpy2.mpfr(1), gmpy2.mpfr(3))))
    wrong = ctx.from_mpfr(gmpy_op(53, "RNDU", "div",
                                  (gmpy2.mpfr(1), gmpy2.mpfr(3))))
    assert got.same_bits(right)
    assert not got.same_bits(wrong)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))


# ---------------------------------------------------------------------
# The phase-1 transcendentals (ABI 0.3)
#
# The package's claim is that libcft and MPFR return the same bits.
# For add and mul that is a claim about rounding; for exp and pow it is
# a claim about the FUNCTION, since a merely accurate implementation
# would differ from MPFR in the last bit on a percent or so of inputs
# and there would be no way to say which was right. So these tests are
# the ones that would fail loudest if the accelerator were not doing
# what this package says it does.
# ---------------------------------------------------------------------

TRANSCEND_UNARY = ("exp", "expm1", "exp2", "log", "log1p", "log2", "log10")
TRANSCEND_BINARY = ("pow", "hypot")
#: ABI 0.4. gmpy2 2.2.1 binds asin, acos, atan and atan2 but none of
#: MPFR 4.2.0's Pi-variants, so the interop comparison covers the four
#: it has and the rest are covered by the batch-vs-scalar and
#: special-row tests below, plus host/tools/mpfr_check.c, which calls
#: mpfr_sinpi and friends directly.
TRIG_GMPY = ("asin", "acos", "atan")
TRIG_UNARY = ("sinpi", "cospi", "tanpi", "asin", "acos", "atan",
              "asinpi", "acospi", "atanpi")
TRIG_BINARY = ("atan2", "atan2pi")


def gmpy_transcend(prec, mode, fn, args):
    save = gmpy2.get_context()
    gctx = gmpy2.ieee(WIDTH[prec])
    gctx.round = getattr(gmpy2, GMPY_MODES[mode])
    gmpy2.set_context(gctx)
    try:
        if fn == "pow":
            return args[0] ** args[1]
        if fn == "hypot":
            return gmpy2.hypot(args[0], args[1])
        return getattr(gmpy2, fn)(args[0])
    finally:
        gmpy2.set_context(save)


def is_snan(ctx, f):
    """A signaling NaN, on the encoding. MPFR has none, so these are
    excluded from the interop comparison and checked against the
    contract instead - the same one-sided help host/tools/mpfr_check.c
    documents."""
    bits = f.to_bits()
    fi = core._format_for(ctx.precision)
    if not f.is_nan:
        return False
    return not (bits >> (fi.man_w - 1)) & 1


def transcend_pool(prec, seed):
    """Operands where these functions are worth testing: the specials,
    a few exact cases, and randoms."""
    ctx = Context(prec)
    out = [ctx.from_float(v) for v in
           (0.0, -0.0, 1.0, -1.0, 2.0, -2.0, 0.5, 3.0, 4.0, 9.0, 10.0,
            100.0, 0.25, 1.5, -0.5, 8.0, 1e-8, 7.0)]
    out += [ctx.from_bits(b) for b in pool(prec, count=14, seed=seed)]
    return out


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", ("RNDN", "RNDZ", "RNDD", "RNDU"))
@pytest.mark.parametrize("fn", TRANSCEND_UNARY + TRANSCEND_BINARY)
def test_transcend_matches_gmpy2(prec, mode, fn):
    """Bit for bit against MPFR at a matching IEEE context. RNDNA is
    absent because MPFR has no ties-to-away - the same asterisk the
    package docstring carries for the arithmetic."""
    ctx = Context(prec, rounding=mode)
    ops = transcend_pool(prec, seed=17)
    checked = 0
    for i, x in enumerate(ops):
        args = [x] if fn in TRANSCEND_UNARY else [x, ops[(i * 7 + 3) % len(ops)]]
        if any(is_snan(ctx, a) for a in args):
            continue          # MPFR has no signaling NaN to compare against
        got = getattr(ctx, fn)(*args)
        want = gmpy_transcend(prec, mode, fn,
                              [a.to_mpfr() for a in args])
        if got.is_nan:
            assert gmpy2.is_nan(want), (fn, i)
        else:
            assert got.same_bits(ctx.from_mpfr(want)), \
                f"{fn} {prec} {mode} arg {i}: {got.to_str()} vs {want}"
        checked += 1
    assert checked >= 20


@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("fn", TRANSCEND_UNARY + TRANSCEND_BINARY)
def test_transcend_batch_matches_scalar(prec, fn):
    """One C call for the array must equal N calls for the elements.
    Correct rounding makes that a THEOREM rather than a hope - there is
    no vectorised approximation here to drift from a scalar one - so a
    difference would be a marshalling bug, which is exactly what this
    checks."""
    ctx = Context(prec)
    ops = transcend_pool(prec, seed=23)
    ys = [ops[(i * 5 + 1) % len(ops)] for i in range(len(ops))]
    want, want_or = [], 0
    if fn in TRANSCEND_UNARY:
        got, fl = getattr(batch, fn)(ctx, ops)
        for x in ops:
            want.append(getattr(ctx, fn)(x))
            want_or |= ctx.last_flags
    else:
        got, fl = getattr(batch, fn)(ctx, ops, ys)
        for x, y in zip(ops, ys):
            want.append(getattr(ctx, fn)(x, y))
            want_or |= ctx.last_flags
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g.same_bits(w), f"{fn} {prec}"
    assert fl == want_or, f"{fn} {prec}: batch flags are the OR"


@pytest.mark.parametrize("prec", PRECISIONS)
def test_transcend_exact_cases_raise_nothing(prec):
    """Where the contract says a case is exact, the flags must be
    EMPTY - which is the observable difference between a correctly
    rounded implementation and an accurate one."""
    ctx = Context(prec)
    ctx.clear_flags()
    cases = [
        ("exp", (0.0,), 1.0),
        ("expm1", (0.0,), 0.0),
        ("exp2", (10.0,), 1024.0),
        ("log", (1.0,), 0.0),
        ("log1p", (0.0,), 0.0),
        ("log2", (8.0,), 3.0),
        ("log10", (1000.0,), 3.0),
        ("pow", (3.0, 4.0), 81.0),
        ("hypot", (3.0, 4.0), 5.0),
    ]
    for fn, args, want in cases:
        ctx.clear_flags()
        got = getattr(ctx, fn)(*args)
        assert got.to_float() == want, fn
        assert ctx.last_flags == 0, (fn, ctx.flag_names())
    # and an inexact one really is inexact
    ctx.clear_flags()
    ctx.exp(1.0)
    assert "inexact" in ctx.flag_names()


@pytest.mark.parametrize("prec", PRECISIONS)
def test_transcend_special_rows(prec):
    """The clause 9.2.1 rows a drop-in replacement has to keep, and the
    two implementations most often differ on."""
    ctx = Context(prec)
    assert ctx.exp(ctx.inf(1)).is_zero
    assert ctx.exp(ctx.inf(1)).sign == 0
    assert ctx.expm1(ctx.inf(1)).to_float() == -1.0
    assert ctx.log(ctx.zero()).is_inf
    assert ctx.log(ctx.zero()).sign == 1
    assert "divbyzero" in ctx.flag_names(ctx.last_flags)
    assert ctx.log(ctx.from_float(-1.0)).is_nan
    assert ctx.log1p(ctx.from_float(-1.0)).is_inf
    # pow(x, +-0) is 1 for ANY x, including a quiet NaN
    assert ctx.pow(ctx.nan(), ctx.zero()).to_float() == 1.0
    assert ctx.pow(ctx.nan(), ctx.zero(1)).to_float() == 1.0
    # pow(1, y) is 1 for ANY y
    assert ctx.pow(ctx.from_float(1.0), ctx.nan()).to_float() == 1.0
    # pow(-1, +-inf) is 1
    assert ctx.pow(ctx.from_float(-1.0), ctx.inf()).to_float() == 1.0
    # an infinity beats a quiet NaN in hypot
    assert ctx.hypot(ctx.inf(1), ctx.nan()).is_inf
    assert ctx.hypot(ctx.inf(1), ctx.nan()).sign == 0
    # the signed zero survives expm1 and log1p, which is why they exist
    assert ctx.expm1(ctx.zero(1)).sign == 1
    assert ctx.log1p(ctx.zero(1)).sign == 1


# ---------------------------------------------------------------------
# The phase-2 trigonometrics (ABI 0.4)
# ---------------------------------------------------------------------

def trig_pool(prec, seed):
    """Operands where these functions are worth testing: the
    half-integers and quarter-integers where sinPi and tanPi are exact,
    the two sides of 1 where asin's domain ends, and randoms."""
    ctx = Context(prec)
    out = [ctx.from_float(v) for v in
           (0.0, -0.0, 0.5, -0.5, 1.0, -1.0, 1.5, 2.0, 2.5, 3.0, -3.0,
            0.25, 0.75, -0.25, 1.25, 0.125, 0.375, 4.0, 17.0, 0.9375,
            1e-8, -1e-8, 0.7, -0.3)]
    out += [ctx.from_bits(b) for b in pool(prec, count=10, seed=seed)]
    return out


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", ("RNDN", "RNDZ", "RNDD", "RNDU"))
@pytest.mark.parametrize("fn", TRIG_GMPY + ("atan2",))
def test_trig_matches_gmpy2(prec, mode, fn):
    """Bit for bit against MPFR at a matching IEEE context, for the four
    inverse functions gmpy2 binds. The Pi-variants are MPFR 4.2.0
    functions gmpy2 2.2.1 does not expose; host/tools/mpfr_check.c calls
    them directly instead, and saying so is better than composing
    sin(pi*x) here and calling the result a comparison."""
    ctx = Context(prec, rounding=mode)
    ops = trig_pool(prec, seed=29)
    checked = 0
    for i, x in enumerate(ops):
        args = [x] if fn != "atan2" else [x, ops[(i * 5 + 2) % len(ops)]]
        if any(is_snan(ctx, a) for a in args):
            continue
        got = getattr(ctx, fn)(*args)
        save = gmpy2.get_context()
        gctx = gmpy2.ieee(WIDTH[prec])
        gctx.round = getattr(gmpy2, GMPY_MODES[mode])
        gmpy2.set_context(gctx)
        try:
            ms = [a.to_mpfr() for a in args]
            want = gmpy2.atan2(*ms) if fn == "atan2" \
                else getattr(gmpy2, fn)(ms[0])
        finally:
            gmpy2.set_context(save)
        if got.is_nan:
            assert gmpy2.is_nan(want), (fn, i)
        else:
            assert got.same_bits(ctx.from_mpfr(want)), \
                f"{fn} {prec} {mode} arg {i}: {got.to_str()} vs {want}"
        checked += 1
    assert checked >= 20


@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("fn", TRIG_UNARY + TRIG_BINARY)
def test_trig_batch_matches_scalar(prec, fn):
    """One C call for the array must equal N calls for the elements."""
    ctx = Context(prec)
    ops = trig_pool(prec, seed=31)
    ys = [ops[(i * 3 + 1) % len(ops)] for i in range(len(ops))]
    want, want_or = [], 0
    if fn in TRIG_UNARY:
        got, fl = getattr(batch, fn)(ctx, ops)
        for x in ops:
            want.append(getattr(ctx, fn)(x))
            want_or |= ctx.last_flags
    else:
        got, fl = getattr(batch, fn)(ctx, ops, ys)
        for x, y in zip(ops, ys):
            want.append(getattr(ctx, fn)(x, y))
            want_or |= ctx.last_flags
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g.same_bits(w), f"{fn} {prec}"
    assert fl == want_or, f"{fn} {prec}: batch flags are the OR"


@pytest.mark.parametrize("prec", PRECISIONS)
def test_trig_exact_cases_raise_nothing(prec):
    """The exact table of ABI 0.4, which is far larger than 0.3's -
    Niven's theorem, not a tolerance. Every one of these must leave the
    flag word EMPTY."""
    ctx = Context(prec)
    cases = [
        ("sinpi", (0.5,), 1.0),
        ("sinpi", (1.5,), -1.0),
        ("sinpi", (3.0,), 0.0),
        ("cospi", (1.0,), -1.0),
        ("cospi", (2.0,), 1.0),
        ("cospi", (0.5,), 0.0),
        ("tanpi", (0.25,), 1.0),
        ("tanpi", (0.75,), -1.0),
        ("tanpi", (2.0,), 0.0),
        ("acos", (1.0,), 0.0),
        ("asin", (0.0,), 0.0),
        ("atan", (0.0,), 0.0),
        ("asinpi", (1.0,), 0.5),
        ("asinpi", (-1.0,), -0.5),
        ("acospi", (0.0,), 0.5),
        ("acospi", (-1.0,), 1.0),
        ("acospi", (1.0,), 0.0),
        ("atanpi", (1.0,), 0.25),
        ("atanpi", (-1.0,), -0.25),
        ("atan2pi", (1.0, 1.0), 0.25),
        ("atan2pi", (1.0, -1.0), 0.75),
        ("atan2pi", (-2.0, 2.0), -0.25),
    ]
    for fn, args, want in cases:
        ctx.clear_flags()
        got = getattr(ctx, fn)(*args)
        assert got.to_float() == want, (fn, args, got.to_str())
        assert ctx.last_flags == 0, (fn, args, ctx.flag_names())
    # and the neighbours of those are inexact, so the table is a proof
    # and not a coincidence
    for fn, args in (("sinpi", (0.375,)), ("cospi", (0.125,)),
                     ("tanpi", (0.125,)), ("asin", (0.5,)),
                     ("asinpi", (0.5,)), ("atan", (1.0,)),
                     ("atan2", (1.0, 1.0))):
        ctx.clear_flags()
        getattr(ctx, fn)(*args)
        assert "inexact" in ctx.flag_names(), (fn, args)


@pytest.mark.parametrize("prec", PRECISIONS)
def test_trig_special_rows(prec):
    """The clause 9.2.1 rows a drop-in has to keep, and the ones two
    implementations most often differ on."""
    ctx = Context(prec)
    # sinPi of an integer takes the sign of the ARGUMENT
    assert ctx.sinpi(1.0).is_zero and ctx.sinpi(1.0).sign == 0
    assert ctx.sinpi(-1.0).is_zero and ctx.sinpi(-1.0).sign == 1
    # cosPi is even, so its zero has no sign to carry
    assert ctx.cospi(0.5).sign == 0
    assert ctx.cospi(-0.5).sign == 0
    # tanPi is sinPi/cosPi, signs included: tanPi(1) is -0
    assert ctx.tanpi(1.0).is_zero and ctx.tanpi(1.0).sign == 1
    assert ctx.tanpi(2.0).sign == 0
    # a pole is +-infinity with divideByZero
    ctx.clear_flags()
    p = ctx.tanpi(0.5)
    assert p.is_inf and p.sign == 0
    assert "divbyzero" in ctx.flag_names(ctx.last_flags)
    n = ctx.tanpi(1.5)
    assert n.is_inf and n.sign == 1
    # sin, cos and tan of an infinity have no limit
    for fn in ("sinpi", "cospi", "tanpi"):
        ctx.clear_flags()
        assert getattr(ctx, fn)(ctx.inf()).is_nan
        assert "invalid" in ctx.flag_names(ctx.last_flags)
    # out of domain
    for fn in ("asin", "acos", "asinpi", "acospi"):
        ctx.clear_flags()
        assert getattr(ctx, fn)(2.0).is_nan
        assert "invalid" in ctx.flag_names(ctx.last_flags)
    assert ctx.atanpi(ctx.inf()).to_float() == 0.5
    assert ctx.atanpi(ctx.inf(1)).to_float() == -0.5
    # atan2(+-0, -0) is +-pi, and its Pi form is +-1 and EXACT
    ctx.clear_flags()
    assert ctx.atan2pi(ctx.zero(), ctx.zero(1)).to_float() == 1.0
    assert ctx.last_flags == 0
    assert ctx.atan2pi(ctx.zero(1), ctx.zero(1)).to_float() == -1.0
    assert ctx.atan2pi(ctx.zero(), ctx.zero()).is_zero
    assert ctx.atan2pi(ctx.zero(1), ctx.zero()).sign == 1
    # a quiet NaN does NOT outrank atan2's table the way it does pow's
    assert ctx.atan2(ctx.nan(), ctx.zero()).is_nan
    assert ctx.atan2pi(ctx.from_float(1.0), ctx.nan()).is_nan


# ---- the phase-3 radian trigonometry and the hyperbolics (ABI 0.5) ------

P3_UNARY = ("sin", "cos", "tan", "sinh", "cosh", "tanh",
            "asinh", "acosh", "atanh")


def p3_pool(prec, seed):
    """Operands for the nine: the tiny and the huge (which is where the
    reduction against pi earns its keep), the two sides of 1 (acosh's
    edge and atanh's pole), the sinh/cosh overflow region, a few
    multiples of pi/2 as doubles, and randoms."""
    ctx = Context(prec)
    out = [ctx.from_float(v) for v in
           (0.0, -0.0, 1.0, -1.0, 0.5, -0.5, 2.0, -2.0, 3.0, -3.0, 0.25,
            1.5, 10.0, -10.0, 100.0, 1e-8, -1e-8, 1e-40, 0.9999, -0.9999,
            1.0001, 1e6, 1e30, -1e30, 1e300, 1e-300,
            3.141592653589793, 1.5707963267948966, 6.283185307179586,
            0.7853981633974483, 88.0, 710.0, 11356.0, 181704.0)]
    out += [ctx.from_bits(b) for b in pool(prec, count=10, seed=seed)]
    return out


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", ("RNDN", "RNDZ", "RNDD", "RNDU"))
@pytest.mark.parametrize("fn", P3_UNARY)
def test_p3_matches_gmpy2(prec, mode, fn):
    """Bit for bit against MPFR at a matching IEEE context. gmpy2 binds
    all nine, so unlike the Pi-variants every one of these has a Python-
    side oracle - including sin of 1e300, which MPFR reduces against its
    own pi."""
    ctx = Context(prec, rounding=mode)
    ops = p3_pool(prec, seed=41)
    checked = 0
    for i, x in enumerate(ops):
        if is_snan(ctx, x):
            continue
        got = getattr(ctx, fn)(x)
        save = gmpy2.get_context()
        gctx = gmpy2.ieee(WIDTH[prec])
        gctx.round = getattr(gmpy2, GMPY_MODES[mode])
        gmpy2.set_context(gctx)
        try:
            want = getattr(gmpy2, fn)(x.to_mpfr())
        finally:
            gmpy2.set_context(save)
        if got.is_nan:
            assert gmpy2.is_nan(want), (fn, i)
        else:
            assert got.same_bits(ctx.from_mpfr(want)), \
                f"{fn} {prec} {mode} arg {i}: {got.to_str()} vs {want}"
        checked += 1
    assert checked >= 30


@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("fn", P3_UNARY)
def test_p3_batch_matches_scalar(prec, fn):
    """One C call for the array must equal N calls for the elements."""
    ctx = Context(prec)
    ops = p3_pool(prec, seed=43)
    got, fl = getattr(batch, fn)(ctx, ops)
    want, want_or = [], 0
    for x in ops:
        want.append(getattr(ctx, fn)(x))
        want_or |= ctx.last_flags
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g.same_bits(w), f"{fn} {prec}"
    assert fl == want_or, f"{fn} {prec}: batch flags are the OR"


# ---- the rest of table 9.1 (part of the 0.6 step) -----------------------

T91_UNARY = ("exp2m1", "exp10", "exp10m1", "log2p1", "log10p1", "rsqrt")
T91_INT = ("pown", "compound", "rootn")

#: Of the ten, gmpy2 2.2.1 binds three: exp10, rec_sqrt (as rsqrt) and
#: rootn - and rootn only for a NON-NEGATIVE n, since it goes to
#: mpfr_rootn_ui. exp2m1, exp10m1, log2p1, log10p1, powr, pown and
#: compound exist in MPFR 4.2.2 but not in this gmpy2, so they are
#: checked against MPFR by host/tools/mpfr_check.c calling the C entry
#: points directly, and here against the library's own contract. Naming
#: the gap is better than claiming a comparison this file cannot make.
GMPY_T91 = {"exp10": "exp10", "rsqrt": "rec_sqrt"}


def t91_pool(prec, seed):
    """Operands where the ten can be got wrong: the integers (exp2m1 is
    exact on them), the powers of ten (exp10 and exp10m1 are), 2^k - 1
    and 10^k - 1 (log2p1 and log10p1 are), the even and odd powers of
    two (rSqrt's whole split), the neighbourhood of -1, and the tiny."""
    ctx = Context(prec)
    out = [ctx.from_float(v) for v in
           (0.0, -0.0, 1.0, -1.0, 2.0, -2.0, 3.0, -3.0, 4.0, 7.0, 8.0,
            9.0, 10.0, 16.0, 24.0, 25.0, 26.0, 0.5, -0.5, 0.25, -0.25,
            99.0, 100.0, 1000.0, 0.125, 1e-8, -1e-8, 1e-40, 1.5, -0.75,
            1023.0, 1e20)]
    out += [ctx.from_bits(b) for b in pool(prec, count=10, seed=seed)]
    return out


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", ("RNDN", "RNDZ", "RNDD", "RNDU"))
@pytest.mark.parametrize("fn", sorted(GMPY_T91))
def test_t91_matches_gmpy2(prec, mode, fn):
    """The three of the ten gmpy2 reaches, bit for bit at a matching
    IEEE context - with rSqrt(-0) held back, because MPFR returns
    +infinity there and 754-2019 9.2.1 asks for -infinity. That row is
    pinned against the STANDARD below instead."""
    ctx = Context(prec, rounding=mode)
    ops = t91_pool(prec, seed=61)
    checked = 0
    for i, x in enumerate(ops):
        if is_snan(ctx, x):
            continue
        if fn == "rsqrt" and x.is_zero and x.sign == 1:
            continue
        got = getattr(ctx, fn)(x)
        save = gmpy2.get_context()
        gctx = gmpy2.ieee(WIDTH[prec])
        gctx.round = getattr(gmpy2, GMPY_MODES[mode])
        gmpy2.set_context(gctx)
        try:
            want = getattr(gmpy2, GMPY_T91[fn])(x.to_mpfr())
        finally:
            gmpy2.set_context(save)
        if got.is_nan:
            assert gmpy2.is_nan(want), (fn, i)
        else:
            assert got.same_bits(ctx.from_mpfr(want)), \
                f"{fn} {prec} {mode} arg {i}: {got.to_str()} vs {want}"
        checked += 1
    assert checked >= 30


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", ("RNDN", "RNDZ", "RNDD", "RNDU"))
def test_rootn_matches_gmpy2(prec, mode):
    """rootn against mpfr_rootn_ui, which gmpy2 exposes for a positive n
    and a non-negative operand - a different MPFR entry point from
    anything else this file calls."""
    ctx = Context(prec, rounding=mode)
    ops = [x for x in t91_pool(prec, seed=62)
           if not is_snan(ctx, x) and not x.is_nan and x.sign == 0]
    checked = 0
    for n in (1, 2, 3, 5, 8):
        for x in ops:
            got = ctx.rootn(x, n)
            save = gmpy2.get_context()
            gctx = gmpy2.ieee(WIDTH[prec])
            gctx.round = getattr(gmpy2, GMPY_MODES[mode])
            gmpy2.set_context(gctx)
            try:
                want = gmpy2.rootn(x.to_mpfr(), n)
            finally:
                gmpy2.set_context(save)
            if got.is_nan:
                assert gmpy2.is_nan(want), (n, x.to_str())
            else:
                assert got.same_bits(ctx.from_mpfr(want)), \
                    f"rootn {prec} {mode} n={n}: {got.to_str()} vs {want}"
            checked += 1
    assert checked >= 60


@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("fn", T91_UNARY)
def test_t91_batch_matches_scalar(prec, fn):
    """One C call for the array must equal N calls for the elements."""
    ctx = Context(prec)
    ops = t91_pool(prec, seed=63)
    got, fl = getattr(batch, fn)(ctx, ops)
    want, want_or = [], 0
    for x in ops:
        want.append(getattr(ctx, fn)(x))
        want_or |= ctx.last_flags
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert g.same_bits(w), f"{fn} {prec}"
    assert fl == want_or, f"{fn} {prec}: batch flags are the OR"


# ---------------------------------------------------------------------
# Character sequences (754-2019 5.12) and NaN payloads (9.7)
#
# Part of the 0.6 step, and the first conversions in this package that
# need no optional dependency at all: the rounding is the library's,
# not gmpy2's. So the tests here run on a bare box, and the ones that
# compare against gmpy2 are extra rather than load-bearing.
#
# What a binding can break in this area is the shape rather than the
# arithmetic - the sizing protocol, the batch marshalling, which flag
# word gets recorded, and whether a refusal reaches the caller as a
# refusal. That is what these attack.
# ---------------------------------------------------------------------

@pytest.mark.parametrize("prec", PRECISIONS)
def test_decimal_digits_is_pmin(prec):
    """5.12.2's Pmin, from the LIBRARY rather than from a table here:
    9, 17, 36 and 73 for the four rungs."""
    assert Context(prec).decimal_digits == {24: 9, 53: 17, 113: 36,
                                            237: 73}[prec]


@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", ("RNDN", "RNDZ", "RNDD", "RNDU", "RNDNA"))
def test_decimal_round_trip_at_pmin(prec, mode):
    """to_decimal(Pmin) then from_decimal reproduces the encoding under
    a nearest attribute - 5.12's opening requirement. The directed
    attributes are checked for the weaker property that actually holds
    there: the sequence still names a value on the right side."""
    ctx = Context(prec, rounding=mode)
    h = ctx.decimal_digits
    for bits in pool(prec, count=24, seed=31):
        f = ctx.from_bits(bits)
        if f.is_nan:
            continue
        back = ctx.from_decimal(f.to_decimal(h))
        if mode in ("RNDN", "RNDNA"):
            assert back.same_bits(f), (mode, hex(bits), f.to_decimal(h))


@pytest.mark.parametrize("prec", PRECISIONS)
def test_exact_decimal_round_trips_in_every_attribute(prec):
    """The EXACT conversion writes the value and nothing else, so
    reading it back cannot round and cannot raise - in any attribute.
    That is a stronger claim than the Pmin round trip and the one the
    exact mode exists to make."""
    for mode in ("RNDN", "RNDZ", "RNDD", "RNDU", "RNDNA"):
        ctx = Context(prec, rounding=mode)
        for bits in pool(prec, count=10, seed=32):
            f = ctx.from_bits(bits)
            if f.is_nan or f.is_inf:
                continue
            text = f.to_decimal()
            back = ctx.from_decimal(text)
            assert back.same_bits(f), (mode, hex(bits), text[:60])
            assert ctx.last_flags == 0, (mode, hex(bits))


@pytest.mark.parametrize("prec", PRECISIONS)
def test_hex_round_trips_and_is_exact(prec):
    ctx = Context(prec)
    for bits in pool(prec, count=16, seed=33):
        f = ctx.from_bits(bits)
        if f.is_nan:
            continue
        back = ctx.from_hex(f.to_hex())
        assert back.same_bits(f), (hex(bits), f.to_hex())
        assert ctx.last_flags == 0
    assert ctx.from_hex("0x1.8p+1").to_decimal() == "3e+0"
    # 5.12.3's grammar requires the binary exponent
    with pytest.raises(cftmpfr.CftError):
        ctx.from_hex("0x1.8")
    # and the hex parser is not the decimal one
    with pytest.raises(cftmpfr.CftError):
        ctx.from_hex("1.5")


@pytest.mark.parametrize("prec", PRECISIONS)
def test_specials_and_payloads_survive_the_round_trip(prec):
    """5.12.1's words, including the payload suffix 6.2.3 asks language
    standards to provide. A signaling NaN comes back SIGNALING and
    raises nothing on the way, which is the spelling this contract
    chose out of the two 5.12.1 offers."""
    ctx = Context(prec)
    fi = ctx._fi
    top = 1 << (fi.man_w - 1)
    allones = ((1 << fi.exp_w) - 1) << fi.man_w
    for bits in (allones | top,                          # canonical qNaN
                 allones | top | 5,                      # qNaN, payload 5
                 allones | 1,                            # sNaN, payload 1
                 allones | (top - 1),                    # sNaN, max payload
                 (1 << (fi.width - 1)) | allones | top | 3):
        f = ctx.from_bits(bits)
        ctx.clear_flags()
        text = f.to_decimal()
        assert ctx.from_decimal(text).same_bits(f), (hex(bits), text)
        assert ctx.from_hex(text).same_bits(f), (hex(bits), text)
        assert ctx.flags == 0, (hex(bits), text)
    for text, sign in (("inf", 0), ("-inf", 1), ("INFINITY", 0)):
        f = ctx.from_decimal(text)
        assert f.is_inf and f.sign == sign
    assert ctx.from_decimal("-0").sign == 1
    assert ctx.from_decimal("0").to_decimal(9) == "0"


@pytest.mark.parametrize("prec", PRECISIONS)
def test_from_decimal_refuses_rather_than_guesses(prec):
    ctx = Context(prec)
    for s in ("", "+", ".", "1e", "1 ", " 1", "1.5.5", "1,5", "0x1p+0",
              "nan()", "nan(0x)", "1_000"):
        with pytest.raises(cftmpfr.CftError):
            ctx.from_decimal(s)
    # a payload the format cannot hold is in the syntax and refused
    with pytest.raises(cftmpfr.CftError):
        ctx.from_decimal("nan(0x%x)" % (1 << (ctx._fi.man_w - 1)))
    with pytest.raises(TypeError):
        ctx.from_decimal(1.5)


@pytest.mark.parametrize("prec", PRECISIONS)
def test_batch_from_decimal_equals_the_scalar_path(prec):
    """The batch path against the scalar path, which is this file's
    standing question for every operation - here with the flag word as
    the OR across the batch."""
    ctx = Context(prec)
    seqs = []
    for bits in pool(prec, count=20, seed=34):
        f = ctx.from_bits(bits)
        if f.is_nan or f.is_inf:
            continue
        seqs.append(f.to_decimal(ctx.decimal_digits))
    seqs += ["0.1", "1e400", "1e-400", "inf", "-0", "nan(0x1)"]
    ctx.clear_flags()
    got, fl = batch.from_decimal(ctx, seqs)
    want, acc = [], 0
    single = Context(prec)
    for s in seqs:
        want.append(single.from_decimal(s))
        acc |= single.last_flags
    assert len(got) == len(want)
    for a, b, s in zip(got, want, seqs):
        assert a.same_bits(b), (s[:60], a, b)
    assert fl == acc
    with pytest.raises(TypeError):
        batch.from_decimal(ctx, "1.5")


@pytest.mark.parametrize("prec", PRECISIONS)
def test_payload_operations(prec):
    """9.7, which signals nothing - so the flag state must be untouched
    by every one of the three."""
    ctx = Context(prec)
    top = 1 << (ctx._fi.man_w - 1)
    ctx.clear_flags()
    for payload in (1, 5, top - 1):
        made = ctx.set_payload(ctx.from_int(payload))
        assert made.is_nan and made.get_payload().to_int() == payload
        sig = ctx.set_payload_signaling(ctx.from_int(payload))
        assert sig.is_nan and sig.get_payload().to_int() == payload
        assert sig.to_decimal().startswith("snan")
    # outside the admissible set the answer is +0, per 9.7
    for bad in (ctx.from_int(top), ctx.from_int(-1), ctx.inf(0), ctx.nan()):
        assert ctx.set_payload(bad).is_zero
        assert ctx.set_payload_signaling(bad).is_zero
    # payload 0 is admissible quiet and NOT signaling
    assert ctx.set_payload(ctx.zero(0)).is_nan
    assert ctx.set_payload_signaling(ctx.zero(0)).is_zero
    # getPayload of anything that is not a NaN is -1
    assert ctx.get_payload(ctx.from_int(3)).to_int() == -1
    assert ctx.flags == 0, "9.7 says these signal no exceptions"
    # the batch form agrees with the scalar one
    xs = [ctx.from_int(1), ctx.nan(), ctx.zero(0), ctx.inf(1)]
    for name in ("get_payload", "set_payload", "set_payload_signaling"):
        got = getattr(batch, name)(ctx, xs)
        for g, x in zip(got, xs):
            assert g.same_bits(getattr(ctx, name)(x)), (name, x)


@needs_gmpy2
@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("mode", ("RNDN", "RNDZ", "RNDD", "RNDU"))
def test_from_decimal_agrees_with_gmpy2(prec, mode):
    """The library's decimal parse against MPFR's, which is what
    from_str used before the 0.6 step. Encodings only: MPFR's underflow
    flag has its own definition and raises on a decimal that lands
    EXACTLY on a subnormal, where 754 7.5 says an exact result raises
    nothing - which is the one row the two disagree on and the reason
    from_str moved."""
    ctx = Context(prec, rounding=mode)
    ref = Context(prec, rounding=mode)
    for s in ("0.1", "0.5", "2.5", "1e300", "1e-300", "1e400", "-1e400",
              "3.14159265358979323846264338327950288", "9" * 30,
              "16777217", "1e-45", "123456789012345678901234567890e-15"):
        got = ctx.from_decimal(s)
        want = ref._rounded_via_gmpy2(lambda: gmpy2.mpfr(s), s)
        assert got.same_bits(want), (prec, mode, s, got, want)


@pytest.mark.parametrize("prec", PRECISIONS)
@pytest.mark.parametrize("fn", T91_INT)
def test_t91_int_batch_reads_n_per_element(prec, fn):
    """The batch form of pown, compound and rootn takes a sequence of
    exponents, one per element - which an implementation that hoisted n
    out of the loop would pass every scalar test and fail here."""
    ctx = Context(prec)
    ops = t91_pool(prec, seed=64)
    ns = [((i % 7) - 3) or 1 for i in range(len(ops))]
    got, fl = getattr(batch, fn)(ctx, ops, ns)
    want, want_or = [], 0
    for x, n in zip(ops, ns):
        want.append(getattr(ctx, fn)(x, n))
        want_or |= ctx.last_flags
    for g, w in zip(got, want):
        assert g.same_bits(w), f"{fn} {prec}"
    assert fl == want_or
    # and a scalar n applies to every element
    got2, _ = getattr(batch, fn)(ctx, ops, 3)
    for g, x in zip(got2, ops):
        assert g.same_bits(getattr(ctx, fn)(x, 3))
    with pytest.raises(ValueError):
        getattr(batch, fn)(ctx, ops, [1, 2])


@pytest.mark.parametrize("prec", PRECISIONS)
def test_t91_exact_cases_and_rows(prec):
    """The exact cases decided by exact arithmetic, and the 9.2.1 rows
    for the ten - including the three where this contract follows the
    standard and MPFR does not."""
    ctx = Context(prec)
    F = ctx.from_float
    exact = [
        ("exp2m1", 3.0, 7.0), ("exp2m1", -3.0, -0.875),
        ("exp2m1", -0.0, -0.0), ("exp10", 2.0, 100.0),
        ("exp10", -0.0, 1.0), ("exp10m1", 2.0, 99.0),
        ("log2p1", 3.0, 2.0), ("log2p1", -0.5, -1.0),
        ("log10p1", 99.0, 2.0), ("log10p1", 9.0, 1.0),
        ("rsqrt", 4.0, 0.5), ("rsqrt", 0.25, 2.0),
    ]
    for fn, arg, want in exact:
        ctx.clear_flags()
        got = getattr(ctx, fn)(F(arg))
        assert got.to_float() == want, (fn, arg, got.to_str())
        assert ctx.last_flags == 0, (fn, arg, ctx.flag_names())
    # log2p1(1) is log2(2) = 1 and IS exact, which is why the inexact
    # list uses 2 - the exact table here is larger than it looks
    for fn, arg in (("exp10", -1.0), ("rsqrt", 2.0), ("exp2m1", 0.5),
                    ("log2p1", 2.0), ("log10p1", 1.0)):
        ctx.clear_flags()
        getattr(ctx, fn)(F(arg))
        assert "inexact" in ctx.flag_names(), (fn, arg)
    # rSqrt keeps the sign of a zero; MPFR does not
    ctx.clear_flags()
    p = ctx.rsqrt(ctx.zero())
    assert p.is_inf and p.sign == 0
    assert "divbyzero" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    m = ctx.rsqrt(ctx.zero(1))
    assert m.is_inf and m.sign == 1, "rSqrt(-0) is MINUS infinity"
    assert "divbyzero" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    assert ctx.rsqrt(F(-1.0)).is_nan
    assert "invalid" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    assert ctx.rsqrt(ctx.inf()).is_zero and ctx.last_flags == 0
    # log2p1 and log10p1: the pole at -1 and the domain below it
    for fn in ("log2p1", "log10p1"):
        ctx.clear_flags()
        r = getattr(ctx, fn)(F(-1.0))
        assert r.is_inf and r.sign == 1
        assert "divbyzero" in ctx.flag_names(ctx.last_flags)
        ctx.clear_flags()
        assert getattr(ctx, fn)(F(-2.0)).is_nan
        assert "invalid" in ctx.flag_names(ctx.last_flags)
    # powr is not pow
    ctx.clear_flags()
    assert ctx.powr(F(1.0), ctx.nan()).is_nan, "powr(1, qNaN) is a NaN"
    assert ctx.last_flags == 0
    ctx.clear_flags()
    assert ctx.pow(F(1.0), ctx.nan()).to_float() == 1.0, "pow(1, qNaN) is 1"
    ctx.clear_flags()
    assert ctx.powr(F(-1.0), F(2.0)).is_nan
    assert "invalid" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    assert ctx.powr(ctx.zero(), ctx.zero()).is_nan
    assert "invalid" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    assert ctx.powr(F(2.0), F(3.0)).to_float() == 8.0
    assert ctx.last_flags == 0
    # pown, compound, rootn
    ctx.clear_flags()
    assert ctx.pown(ctx.nan(), 0).to_float() == 1.0
    assert ctx.pown(F(-2.0), 3).to_float() == -8.0
    assert ctx.last_flags == 0
    ctx.clear_flags()
    z = ctx.pown(ctx.zero(1), -3)
    assert z.is_inf and z.sign == 1
    assert "divbyzero" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    assert ctx.compound(ctx.nan(), 0).to_float() == 1.0
    assert ctx.compound(F(1.0), 3).to_float() == 8.0
    assert ctx.last_flags == 0
    ctx.clear_flags()
    assert ctx.compound(F(-2.0), 0).is_nan, "compound(x < -1, 0) is invalid"
    assert "invalid" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    assert ctx.rootn(F(-8.0), 3).to_float() == -2.0
    assert ctx.rootn(F(4.0), -1).to_float() == 0.25
    assert ctx.last_flags == 0
    ctx.clear_flags()
    assert ctx.rootn(ctx.nan(), 0).is_nan
    assert "invalid" in ctx.flag_names(ctx.last_flags)


@pytest.mark.parametrize("prec", PRECISIONS)
def test_rootn_two_is_sqrt_except_at_minus_zero(prec):
    """rootn(x, 2) is sqrt(x) on every operand but -0, where 754-2019's
    own NOTE says they differ: rootn(-0, 2) is +0 and squareRoot(-0) is
    -0. The difference is asserted, not skipped."""
    ctx = Context(prec)
    for x in t91_pool(prec, seed=65):
        if is_snan(ctx, x):
            continue
        r = ctx.rootn(x, 2)
        s = ctx.sqrt(x)
        if x.is_zero and x.sign == 1:
            assert r.is_zero and r.sign == 0
            assert s.is_zero and s.sign == 1
        elif r.is_nan:
            assert s.is_nan
        else:
            assert r.same_bits(s), (x.to_str(), r.to_str(), s.to_str())


@pytest.mark.parametrize("prec", PRECISIONS)
def test_p3_exact_cases_are_the_zeros(prec):
    """Hermite-Lindemann: the only exact cases are the zeros, cos and
    cosh at 0, acosh at 1 - and tanh at an infinity, which is a limit
    that happens to be representable. Every one leaves the flag word
    EMPTY, and every neighbour of the table is inexact."""
    ctx = Context(prec)
    cases = [
        ("sin", 0.0, 0.0, 0), ("sin", -0.0, -0.0, 1),
        ("cos", 0.0, 1.0, 0), ("cos", -0.0, 1.0, 0),
        ("tan", -0.0, -0.0, 1),
        ("sinh", -0.0, -0.0, 1), ("cosh", -0.0, 1.0, 0),
        ("tanh", 0.0, 0.0, 0), ("asinh", -0.0, -0.0, 1),
        ("acosh", 1.0, 0.0, 0), ("atanh", -0.0, -0.0, 1),
    ]
    for fn, arg, want, sign in cases:
        ctx.clear_flags()
        got = getattr(ctx, fn)(ctx.from_float(arg))
        assert got.to_float() == want and got.sign == sign, \
            (fn, arg, got.to_str())
        assert ctx.last_flags == 0, (fn, arg, ctx.flag_names())
    ctx.clear_flags()
    assert ctx.tanh(ctx.inf()).to_float() == 1.0
    assert ctx.tanh(ctx.inf(1)).to_float() == -1.0
    assert ctx.last_flags == 0
    for fn, arg in (("sin", 1.0), ("cos", 1.0), ("tan", 0.5),
                    ("sinh", 1.0), ("cosh", 1.0), ("tanh", 0.5),
                    ("asinh", 1.0), ("acosh", 2.0), ("atanh", 0.5)):
        ctx.clear_flags()
        getattr(ctx, fn)(ctx.from_float(arg))
        assert "inexact" in ctx.flag_names(), (fn, arg)


@pytest.mark.parametrize("prec", PRECISIONS)
def test_p3_special_rows(prec):
    """The clause 9.2.1 rows for the nine: no limit at an infinity for
    the radian three, the hyperbolic infinities, acosh's domain, and
    atanh's pole with divideByZero."""
    ctx = Context(prec)
    for fn in ("sin", "cos", "tan"):
        for s in (0, 1):
            ctx.clear_flags()
            assert getattr(ctx, fn)(ctx.inf(s)).is_nan, (fn, s)
            assert "invalid" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    assert ctx.sinh(ctx.inf(1)).is_inf and ctx.sinh(ctx.inf(1)).sign == 1
    assert ctx.cosh(ctx.inf(1)).is_inf and ctx.cosh(ctx.inf(1)).sign == 0
    assert ctx.asinh(ctx.inf(1)).is_inf and ctx.asinh(ctx.inf(1)).sign == 1
    assert ctx.acosh(ctx.inf()).is_inf and ctx.acosh(ctx.inf()).sign == 0
    assert ctx.last_flags == 0
    for arg in (ctx.inf(1), ctx.zero(), ctx.zero(1), ctx.from_float(0.5),
                ctx.from_float(-2.0)):
        ctx.clear_flags()
        assert ctx.acosh(arg).is_nan
        assert "invalid" in ctx.flag_names(ctx.last_flags)
    ctx.clear_flags()
    p = ctx.atanh(ctx.from_float(1.0))
    assert p.is_inf and p.sign == 0
    assert "divbyzero" in ctx.flag_names(ctx.last_flags)
    n = ctx.atanh(ctx.from_float(-1.0))
    assert n.is_inf and n.sign == 1
    for arg in (ctx.from_float(2.0), ctx.from_float(-1.5), ctx.inf(),
                ctx.inf(1)):
        ctx.clear_flags()
        assert ctx.atanh(arg).is_nan
        assert "invalid" in ctx.flag_names(ctx.last_flags)
    # the odd ones keep a signed zero's sign; cosh does not
    assert ctx.sinh(ctx.zero(1)).sign == 1
    assert ctx.tanh(ctx.zero(1)).sign == 1
    assert ctx.cosh(ctx.zero(1)).sign == 0


@pytest.mark.parametrize("prec", PRECISIONS)
def test_p3_tiny_arguments_take_a_side(prec):
    """The neighbour rules, one directed rounding each: the true value
    lies strictly on a known SIDE of the smallest subnormal (or of 1),
    which no working precision could ever separate."""
    one = Context(prec).from_float(1.0)
    below_one = Context(prec).from_bits(one.to_bits() - 1)
    above_one = Context(prec).from_bits(one.to_bits() + 1)
    for mode, fn, want in (
            ("RNDD", "sin", "zero"), ("RNDU", "sin", "same"),
            ("RNDU", "tan", "next"), ("RNDZ", "tan", "same"),
            ("RNDU", "sinh", "next"), ("RNDD", "sinh", "same"),
            ("RNDD", "tanh", "zero"), ("RNDN", "tanh", "same"),
            ("RNDD", "asinh", "zero"), ("RNDU", "asinh", "same"),
            ("RNDU", "atanh", "next"), ("RNDN", "atanh", "same")):
        ctx = Context(prec, rounding=mode)
        m = ctx.from_bits(1)
        ctx.clear_flags()
        got = getattr(ctx, fn)(m)
        if want == "zero":
            assert got.is_zero and got.sign == 0, (fn, mode)
        elif want == "same":
            assert got.same_bits(m), (fn, mode)
        else:
            assert got.same_bits(ctx.from_bits(2)), (fn, mode)
        names = ctx.flag_names(ctx.last_flags)
        assert "inexact" in names and "underflow" in names, (fn, mode)
    for mode, fn, want in (("RNDD", "cos", below_one),
                           ("RNDN", "cos", one),
                           ("RNDU", "cosh", above_one),
                           ("RNDN", "cosh", one)):
        ctx = Context(prec, rounding=mode)
        ctx.clear_flags()
        got = getattr(ctx, fn)(ctx.from_bits(1))
        assert got.same_bits(want), (fn, mode, got.to_str())
        assert tuple(ctx.flag_names(ctx.last_flags)) == ("inexact",), (fn, mode)


# ---------------------------------------------------------------------
# The augmented arithmetic operations (754-2019 clause 9.5)
#
# What a binding can break here that it cannot break anywhere else:
# there are TWO outputs, so the second could be dropped, swapped with
# the first, or handed back stale; and there is NO rounding argument,
# so the context's attribute could leak into the call. Both are
# attacked below. The values are scored against the GOLDEN MODEL, the
# way the rest of this repository scores them - gmpy2 is no oracle
# here, because MPFR has no roundTiesTowardZero at all, which is
# precisely why these three are worth exposing from a package that
# otherwise matches it call for call.
# ---------------------------------------------------------------------

try:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))
    from cft_golden import FORMATS as _GFORMATS          # noqa: E402
    from cft_golden import augmented as _gaug            # noqa: E402
    from cft_golden import softfloat as _gsf             # noqa: E402
    GOLDEN = {24: _GFORMATS["fp32"], 53: _GFORMATS["fp64"],
              113: _GFORMATS["fp128"], 237: _GFORMATS["fp256"]}
except ImportError:                                      # pragma: no cover
    GOLDEN = None

needs_golden = pytest.mark.skipif(GOLDEN is None,
                                  reason="the golden model is not importable")

AUG = ("augmented_add", "augmented_sub", "augmented_mul")


def _aug_model(name):
    return {"augmented_add": _gaug.augmented_add,
            "augmented_sub": _gaug.augmented_sub,
            "augmented_mul": _gaug.augmented_mul}[name]


@needs_golden
@pytest.mark.parametrize("prec", PRECISIONS)
def test_augmented_pairs_match_the_model(prec):
    """Both outputs and the flag word, per element, against
    python/cft_golden/augmented.py - which is the definition."""
    fmt = GOLDEN[prec]
    ctx = Context(prec)
    ops = pool(prec, count=26, seed=41)
    checked = 0
    for name in AUG:
        for xb in ops:
            for yb in ops:
                ctx.clear_flags()
                r, e = getattr(ctx, name)(ctx.from_bits(xb),
                                          ctx.from_bits(yb))
                want = _aug_model(name)(fmt, xb, yb)
                assert (r.to_bits(), e.to_bits(), ctx.last_flags) == want, \
                    (name, prec, hex(xb), hex(yb))
                checked += 1
    assert checked > 4000, checked


@needs_golden
@pytest.mark.parametrize("prec", PRECISIONS)
def test_augmented_ignores_the_context_attribute(prec):
    """9.5 fixes the rounding, so the SAME pair must come back under
    every attribute - RNDNA included, which nothing else in this
    package can even ask MPFR for. A binding that forwarded the
    context's attribute would pass every other test in this file."""
    ops = pool(prec, count=10, seed=43)
    base = Context(prec, rounding="RNDN")
    want = {}
    for name in AUG:
        for xb in ops:
            for yb in ops:
                r, e = getattr(base, name)(base.from_bits(xb),
                                           base.from_bits(yb))
                want[(name, xb, yb)] = (r.to_bits(), e.to_bits(),
                                        base.last_flags)
    for mode in ("RNDZ", "RNDD", "RNDU", "RNDNA"):
        ctx = Context(prec, rounding=mode)
        for (name, xb, yb), expected in want.items():
            r, e = getattr(ctx, name)(ctx.from_bits(xb), ctx.from_bits(yb))
            assert (r.to_bits(), e.to_bits(), ctx.last_flags) == expected, \
                (name, mode, prec, hex(xb), hex(yb))


@needs_golden
@pytest.mark.parametrize("prec", PRECISIONS)
def test_augmented_batch_equals_the_scalar_path(prec):
    """One C call over an array must give, element for element, what n
    calls of one element give - both arrays, and the flag OR."""
    ctx = Context(prec)
    ops = pool(prec, count=40, seed=47)
    xs = [ctx.from_bits(b) for b in ops]
    ys = [ctx.from_bits(b) for b in reversed(ops)]
    for name in AUG:
        ctx.clear_flags()
        rs, es, flags = getattr(batch, name)(ctx, xs, ys)
        assert len(rs) == len(xs) and len(es) == len(xs)
        want_or = 0
        for x, y, r, e in zip(xs, ys, rs, es):
            ctx.clear_flags()
            sr, se = getattr(ctx, name)(x, y)
            assert r.same_bits(sr) and e.same_bits(se), (name, prec)
            want_or |= ctx.last_flags
        assert flags == want_or, (name, prec, flags, want_or)


def _dyadic(fmt, bits):
    """(m, e) with value m * 2^e and m odd - or None if not finite."""
    u = _gsf.unpack(fmt, bits)
    if u.kind in (_gsf.INF, _gsf.NAN):
        return None
    if u.kind == _gsf.ZERO:
        return (0, 0)
    m = -u.m if u.sign else u.m
    t = (m & -m).bit_length() - 1
    return (m >> t, u.e + t)


def _dnorm(m, e):
    if m == 0:
        return (0, 0)
    t = (m & -m).bit_length() - 1
    return (m >> t, e + t)


def _dadd(p, q):
    e0 = min(p[1], q[1])
    return _dnorm((p[0] << (p[1] - e0)) + (q[0] << (q[1] - e0)), e0)


@needs_golden
@pytest.mark.parametrize("prec", PRECISIONS)
def test_augmented_pair_is_exact(prec):
    """r + e is x op y EXACTLY, in Python integers rather than through
    any floating-point arithmetic - the property the pair exists for.
    Two documented exclusions: an overflowed result, where both outputs
    are an infinity, and a product residual the format cannot hold,
    which 9.5 delivers rounded with underflow AND inexact."""
    fmt = GOLDEN[prec]
    ctx = Context(prec)
    ops = pool(prec, count=30, seed=53)
    exact = lost = 0
    for name in AUG:
        for xb in ops:
            for yb in ops:
                dx, dy = _dyadic(fmt, xb), _dyadic(fmt, yb)
                if dx is None or dy is None:
                    continue
                ctx.clear_flags()
                r, e = getattr(ctx, name)(ctx.from_bits(xb),
                                          ctx.from_bits(yb))
                names = set(ctx.flag_names(ctx.last_flags))
                if "overflow" in names:
                    continue
                if name == "augmented_mul" and "inexact" in names:
                    lost += 1
                    continue
                if name == "augmented_mul":
                    want = _dnorm(dx[0] * dy[0], dx[1] + dy[1])
                elif name == "augmented_sub":
                    want = _dadd(dx, (-dy[0], dy[1]))
                else:
                    want = _dadd(dx, dy)
                got = _dadd(_dyadic(fmt, r.to_bits()),
                            _dyadic(fmt, e.to_bits()))
                assert got == want, (name, prec, hex(xb), hex(yb))
                exact += 1
    assert exact > 2000, exact
    assert lost > 0, "the non-representable product residual was unreached"


@needs_golden
def test_augmented_named_rows():
    """The rows 9.5 states in words, reached through the binding: the
    tie toward the smaller magnitude, underflow without inexact, and
    the zero error term that takes r's sign."""
    ctx = Context(53)
    one_u = ctx.from_bits(0x3FF0000000000001)           # 1 + 2^-52
    half_u = ctx.from_bits(0x3CA0000000000000)          # 2^-53
    ctx.clear_flags()
    r, e = ctx.augmented_add(one_u, half_u)
    assert r.to_bits() == 0x3FF0000000000001
    assert e.to_bits() == 0x3CA0000000000000
    assert ctx.last_flags == 0
    # ordinary addition steps UP from the same midpoint, which is what
    # makes the assertion above a test rather than a coincidence
    assert ctx.add(one_u, half_u).to_bits() == 0x3FF0000000000002

    ctx.clear_flags()
    r, e = ctx.augmented_add(ctx.from_float(1.0), ctx.from_bits(1))
    assert e.to_bits() == 1
    assert tuple(ctx.flag_names(ctx.last_flags)) == ("underflow",)

    ctx.clear_flags()
    r, e = ctx.augmented_mul(ctx.from_bits(1), ctx.from_bits(1))
    assert r.is_zero and e.is_zero
    assert set(ctx.flag_names(ctx.last_flags)) == {"underflow", "inexact"}

    ctx.clear_flags()
    minus_one = ctx.from_float(-1.0)
    r, e = ctx.augmented_add(minus_one, ctx.zero())
    assert r.same_bits(minus_one)
    assert e.is_zero and e.sign == 1, "a zero e takes the sign of r"
    assert ctx.last_flags == 0


def test_augmented_refuses_an_unknown_name():
    ctx = Context(53)
    with pytest.raises(ValueError):
        cftmpfr._lib.augmented(ctx._dev, "div", ctx._fi.code, b"", b"", 0,
                               ctx._fi.esz)
