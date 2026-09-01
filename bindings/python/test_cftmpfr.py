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
    if gmpy2 is not None:
        # an EXACT decimal is fine under any attribute...
        assert ctx.from_str("0.5").to_float() == 0.5
        # ...only one that actually needs rounding refuses
        with pytest.raises(ValueError, match="ties"):
            ctx.from_str("0.1")


def test_gmpy2_absent_paths(monkeypatch):
    ctx = Context(237)
    exact = ctx.from_float(1.5)     # exact routes never need gmpy2
    monkeypatch.setattr(core, "gmpy2", None)
    assert ctx.from_int(10).to_int() == 10
    assert exact.to_float() == 1.5
    with pytest.raises(RuntimeError, match="gmpy2"):
        ctx.from_str("0.1")
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
