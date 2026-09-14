# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The whole divide ON the chip (divfull.py) against the contract, bit
for bit and flag for flag.

seqprogs.py's route leaves classification and round_pack on the host;
divfull.py puts both in the instruction stream and deposits the
quotient and its flag word. So this matrix is test_seqprogs.py's with
the specials INCLUDED in the lanes (there is no host filter any more)
and every flag read off a deposit rather than off round_pack:

  * the special pairings, every class against every class, per lane,
    so INVALID and DIVZERO are compared exactly where softfloat.div
    raises them;
  * the subnormal boundary, where tininess-after-rounding is decided
    and the one configuration that is NOT tiny lives (a value at
    emin - 1 carried up to emin by the unbounded rounding);
  * the overflow boundary in every attribute, where 7.4 hands out an
    infinity or the largest finite;
  * test_sequences' operand pool and the hard families, as batches;
  * a random stress at binary64.

And, first, that factoring the core out of seqprogs.div_program left
the committed library images byte-identical - the refactor that made
this module possible must not have moved a bit of the old route.
"""

import pathlib
import random
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    one_bits, min_normal_bits,
)
from cft_golden import asm, divfull, seqprogs  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.softfloat import RND_MODES  # noqa: E402

from test_sequences import pool_for  # noqa: E402

FORMATS = (FP32, FP64, FP128, FP256)
PROGRAMS = pathlib.Path(__file__).resolve().parents[2] / "programs"


def specials(fmt):
    mw = fmt.man_w
    return [
        0, fmt.sign_mask,
        sf.inf_bits(fmt, 0), sf.inf_bits(fmt, 1),
        sf.qnan_bits(fmt), sf.qnan_bits(fmt) | fmt.sign_mask,
        sf.snan_bits(fmt), sf.snan_bits(fmt) | fmt.sign_mask,
        1, fmt.man_mask,                                   # the subnormal ends
        min_normal_bits(fmt), one_bits(fmt), one_bits(fmt) | fmt.sign_mask,
        sf.max_normal_bits(fmt), sf.max_normal_bits(fmt, 1),
        (fmt.bias - 1) << mw, (fmt.bias + 1) << mw,       # 0.5 and 2
        one_bits(fmt) + 1, one_bits(fmt) - 1,
        (fmt.bias - fmt.prec) << mw, (fmt.bias + fmt.prec) << mw,
    ]


def check_lane(fmt, a, b, rnd):
    outs, flags = divfull.run_div_full(fmt, [a], [b], rnd)
    want = sf.div(fmt, a, b, rnd)
    assert (outs[0], flags) == want, (
        f"{fmt.name} rnd={rnd} {a:#x}/{b:#x}: "
        f"chip=({outs[0]:#x}, {flags:#x}) contract=({want[0]:#x}, {want[1]:#x})")


def check_batch(fmt, pairs, rnd):
    outs, flags = divfull.run_div_full(fmt, [p[0] for p in pairs],
                                       [p[1] for p in pairs], rnd)
    want_flags = 0
    for i, (a, b) in enumerate(pairs):
        wbits, wfl = sf.div(fmt, a, b, rnd)
        want_flags |= wfl
        assert outs[i] == wbits, (
            f"{fmt.name} rnd={rnd} {a:#x}/{b:#x}: "
            f"chip={outs[i]:#x} contract={wbits:#x}")
    assert flags == want_flags, (
        f"{fmt.name} rnd={rnd}: batch flags {flags:#x} contract {want_flags:#x}")


@pytest.mark.parametrize("name,fmt", [
    ("div-fp32", FP32), ("div-fp64", FP64), ("div-fp128", FP128), ("div-fp256", FP256),
])
def test_the_old_route_did_not_move(name, fmt):
    src = PROGRAMS / (name + ".cfta")
    got = asm.assemble(src.read_text(encoding="utf-8"), src.name)
    assert got == seqprogs.div_program_for(fmt).to_bytes(), name


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_every_special_pairing_per_lane(fmt):
    S = specials(fmt)
    for rnd in RND_MODES:
        for a in S:
            for b in S:
                check_lane(fmt, a, b, rnd)


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_the_subnormal_boundary(fmt):
    """Quotients that land on, above and below the subnormal grid, and
    the not-tiny carry at emin - 1; both signs, every attribute."""
    rng = random.Random(fmt.width)
    mw = fmt.man_w
    pairs = []
    for _ in range(80):
        ea = fmt.emin + rng.randrange(-2, fmt.prec + 3)
        if ea + fmt.bias > 0:
            a = ((ea + fmt.bias) << mw) | rng.getrandbits(mw)
        else:
            a = rng.getrandbits(mw)                         # a subnormal dividend
        b = (fmt.bias << mw) | rng.getrandbits(mw)         # in [1, 2)
        pairs.append((a, b))
        pairs.append((a | fmt.sign_mask, b))
        pairs.append((a, b | fmt.sign_mask))
    # exactly emin - 1 with a full significand: the carry that is not tiny
    a = ((fmt.emin - 1 + fmt.bias) << mw) | fmt.man_mask
    pairs += [(a, one_bits(fmt)), (a | fmt.sign_mask, one_bits(fmt)),
              (a, one_bits(fmt) + 1), (a, one_bits(fmt) - 1)]
    for rnd in RND_MODES:
        check_batch(fmt, pairs, rnd)
        for a, b in pairs[-4:]:
            check_lane(fmt, a, b, rnd)


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_the_overflow_boundary(fmt):
    rng = random.Random(fmt.width + 1)
    mw = fmt.man_w
    pairs = []
    for _ in range(60):
        a = ((fmt.emax - rng.randrange(0, 3) + fmt.bias) << mw) | rng.getrandbits(mw)
        b = ((fmt.bias - rng.randrange(0, 3)) << mw) | rng.getrandbits(mw)
        pairs += [(a, b), (a | fmt.sign_mask, b), (a, b | fmt.sign_mask)]
    pairs += [(sf.max_normal_bits(fmt), (fmt.bias - 1) << mw),      # max / 0.5
              (sf.max_normal_bits(fmt, 1), (fmt.bias - 1) << mw),
              (sf.max_normal_bits(fmt), one_bits(fmt) - 1)]
    for rnd in RND_MODES:
        check_batch(fmt, pairs, rnd)
        for a, b in pairs[-3:]:
            check_lane(fmt, a, b, rnd)


@pytest.mark.parametrize("fmt,extra", [
    (FP32, 24), (FP64, 24), (FP128, 8), (FP256, 6),
], ids=lambda v: getattr(v, "name", str(v)))
def test_the_pool_and_the_hard_families(fmt, extra):
    pool = pool_for(fmt, extra)
    dens = pool[:min(len(pool), 18 if fmt.width <= 64 else 8)]
    pairs = [(a, b) for a in pool for b in dens]
    one = one_bits(fmt)
    hard = [(one, one - 1), (one, one + 1), (one - 1, one), (one + 1, one),
            (one, one | fmt.man_mask), (one | fmt.man_mask, one)]
    for rnd in RND_MODES:
        check_batch(fmt, pairs + hard, rnd)
        for a, b in hard:
            check_lane(fmt, a, b, rnd)


def test_stress_binary64():
    rng = random.Random(0x64)
    n = 1500
    for rnd in RND_MODES:
        xs_a = [rng.getrandbits(64) for _ in range(n)]
        xs_b = [rng.getrandbits(64) for _ in range(n)]
        check_batch(FP64, list(zip(xs_a, xs_b)), rnd)


def test_the_program_is_one_image_a_format_with_the_mode_as_data():
    for fmt in FORMATS:
        for prog, bank_for, n in (
                (divfull.div_full_program_for(fmt), divfull.bank, divfull.N_CONSTS),
                (divfull.sqrt_full_program_for(fmt), divfull.bank_sqrt,
                 divfull.N_CONSTS_SQRT)):
            assert prog.bank_ext and prog.n_consts == n
            assert prog.max_deposits == 2
            banks = {rnd: bank_for(fmt, rnd) for rnd in RND_MODES}
            heads = {tuple(b[:-5]) for b in banks.values()}
            assert len(heads) == 1, "only the five mode words may differ"
            assert {tuple(b[-5:]) for b in banks.values()} == {
                (1, 0, 0, 0, 0), (0, 1, 0, 0, 0), (0, 0, 1, 0, 0),
                (0, 0, 0, 1, 0), (0, 0, 0, 0, 1)}


# ---- the square root ----------------------------------------------------

@pytest.mark.parametrize("name,fmt", [
    ("sqrt-fp32", FP32), ("sqrt-fp64", FP64), ("sqrt-fp128", FP128),
    ("sqrt-fp256", FP256),
])
def test_the_old_sqrt_route_did_not_move(name, fmt):
    src = PROGRAMS / (name + ".cfta")
    got = asm.assemble(src.read_text(encoding="utf-8"), src.name)
    assert got == seqprogs.sqrt_program_for(fmt).to_bytes(), name


def check_sqrt_lane(fmt, a, rnd):
    outs, flags = divfull.run_sqrt_full(fmt, [a], rnd)
    want = sf.sqrt(fmt, a, rnd)
    assert (outs[0], flags) == want, (
        f"{fmt.name} rnd={rnd} sqrt({a:#x}): "
        f"chip=({outs[0]:#x}, {flags:#x}) contract=({want[0]:#x}, {want[1]:#x})")


def check_sqrt_batch(fmt, xs, rnd):
    outs, flags = divfull.run_sqrt_full(fmt, xs, rnd)
    want_flags = 0
    for i, a in enumerate(xs):
        wbits, wfl = sf.sqrt(fmt, a, rnd)
        want_flags |= wfl
        assert outs[i] == wbits, (
            f"{fmt.name} rnd={rnd} sqrt({a:#x}): "
            f"chip={outs[i]:#x} contract={wbits:#x}")
    assert flags == want_flags, (
        f"{fmt.name} rnd={rnd}: batch flags {flags:#x} contract {want_flags:#x}")


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_sqrt_every_special_per_lane(fmt):
    """Both signs of every class: -0 is itself, a negative anything else
    (subnormal, -inf included) is invalid, +inf is itself, NaN is the
    canonical quiet NaN and invalid iff signaling."""
    S = specials(fmt) + [1 | fmt.sign_mask, fmt.man_mask | fmt.sign_mask,
                         min_normal_bits(fmt) | fmt.sign_mask]
    for rnd in RND_MODES:
        for a in S:
            check_sqrt_lane(fmt, a, rnd)


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_sqrt_subnormals_and_the_exponent_parity(fmt):
    """Subnormal operands (scaled by an even power on the chip), and
    odd/even exponents on both sides of the bias, which decide whether
    the centred operand is doubled into [2, 4)."""
    rng = random.Random(fmt.width + 3)
    mw = fmt.man_w
    xs = []
    for _ in range(80):
        xs.append(rng.getrandbits(mw))                              # subnormal
    for _ in range(80):
        e = fmt.emin + rng.randrange(0, 2 * fmt.prec)
        xs.append(((e + fmt.bias) << mw) | rng.getrandbits(mw))
    for _ in range(80):
        e = rng.randrange(-8, 9)
        xs.append(((fmt.bias + e) << mw) | rng.getrandbits(mw))
    for _ in range(40):
        e = fmt.emax - rng.randrange(0, 4)
        xs.append(((fmt.bias + e) << mw) | rng.getrandbits(mw))
    for rnd in RND_MODES:
        check_sqrt_batch(fmt, xs, rnd)


@pytest.mark.parametrize("fmt,extra", [
    (FP32, 24), (FP64, 24), (FP128, 8), (FP256, 6),
], ids=lambda v: getattr(v, "name", str(v)))
def test_sqrt_the_pool_and_the_hard_families(fmt, extra):
    pool = pool_for(fmt, extra)
    one = one_bits(fmt)
    mn = min_normal_bits(fmt)
    hard = [one + 1, mn + 1, mn - 1, one - 1, one, one | fmt.man_mask,
            mn | (fmt.man_mask >> 1), ((fmt.bias + 1) << fmt.man_w) + 1]
    for rnd in RND_MODES:
        check_sqrt_batch(fmt, pool + hard, rnd)
        for a in hard:
            check_sqrt_lane(fmt, a, rnd)


def test_sqrt_stress_binary64():
    rng = random.Random(0x5)
    n = 2000
    for rnd in RND_MODES:
        check_sqrt_batch(FP64, [rng.getrandbits(64) for _ in range(n)], rnd)
