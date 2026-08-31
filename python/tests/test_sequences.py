# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The composed div/sqrt sequences against the contract, bit for bit.

sequences.py builds division and square root from the tile's own
opcodes - seeds, FMA, the integer finish. softfloat.div/sqrt define
what they must produce. This holds the two identical: bits AND flags,
every format, every rounding attribute, with the operand pool that
carries the families each broken construction fell to:

  * a = 1, b = 1-ulp: the exact-tie divisor family that broke the
    mode-rounded Markstein finish (correction lands ON the RNE tie);
  * quotients crossing the [2,4) binade, where the doubled-dividend
    trick silently lost its extra bit;
  * negative divisors, which the positive-geometry restore mishandled
    until centring stripped signs;
  * sqrt(1+ulp) and sqrt(min_normal+ulp) under roundTiesToAway, the
    fabricated-midpoint family;
  * sqrt(max_subnormal), where the raw-scale residual lost exactness
    below the representable floor.

Each of those was found by this matrix while the sequences were being
built, which is the reason the pool and the modes are exhaustive
rather than sampled: the failures cluster in single families that
sampling misses.
"""

import random
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, vectors,
    one_bits, min_normal_bits, max_subnormal_bits,
)
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.sequences import div_seq, sqrt_seq  # noqa: E402
from cft_golden.softfloat import RND_MODES  # noqa: E402


def pool_for(fmt, extra_random):
    rng = random.Random(0xD5EED)
    pool = list(vectors.interesting_operands(fmt))
    # the named hard families, both signs
    for base in (one_bits(fmt), min_normal_bits(fmt)):
        pool += [base - 1, base + 1]
    pool += [max_subnormal_bits(fmt)]
    pool += [x | fmt.sign_mask for x in pool[:8]]
    pool += [rng.getrandbits(fmt.width) for _ in range(extra_random)]
    return pool


@pytest.mark.parametrize("fmt,na,nb", [
    (FP32, 0, 30), (FP64, 0, 30), (FP128, 0, 8), (FP256, 0, 6),
], ids=lambda v: getattr(v, "name", str(v)))
def test_div_seq_matches_contract(fmt, na, nb):
    pool = pool_for(fmt, nb)
    dens = pool[:min(len(pool), 22 if fmt.width <= 64 else 12)]
    for rnd in RND_MODES:
        for a in pool:
            for b in dens:
                got = div_seq(fmt, a, b, rnd)
                want = sf.div(fmt, a, b, rnd)
                assert got == want, (
                    f"{fmt.name} rnd={rnd} {a:#x}/{b:#x}: "
                    f"seq={got[0]:#x},{got[1]} want={want[0]:#x},{want[1]}")


@pytest.mark.parametrize("fmt", (FP32, FP64, FP128, FP256),
                         ids=lambda f: f.name)
def test_sqrt_seq_matches_contract(fmt):
    pool = pool_for(fmt, 60 if fmt.width <= 64 else 24)
    for rnd in RND_MODES:
        for a in pool:
            got = sqrt_seq(fmt, a, rnd)
            want = sf.sqrt(fmt, a, rnd)
            assert got == want, (
                f"{fmt.name} rnd={rnd} {a:#x}: "
                f"seq={got[0]:#x},{got[1]} want={want[0]:#x},{want[1]}")


def test_div_seq_stress_binary64():
    """A wider random sweep at the format where native hardware gives
    the contract an independent anchor (test_divsqrt ties sf.div to the
    host CPU; this ties the sequence to sf.div)."""
    rng = random.Random(99)
    for _ in range(1500):
        a = rng.getrandbits(64)
        b = rng.getrandbits(64)
        rnd = rng.choice(RND_MODES)
        assert div_seq(FP64, a, b, rnd) == sf.div(FP64, a, b, rnd)


def test_sqrt_seq_stress_binary64():
    rng = random.Random(100)
    for _ in range(2000):
        a = rng.getrandbits(64)
        rnd = rng.choice(RND_MODES)
        assert sqrt_seq(FP64, a, rnd) == sf.sqrt(FP64, a, rnd)
