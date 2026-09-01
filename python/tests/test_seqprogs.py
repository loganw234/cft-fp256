# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The div/sqrt SEQUENCER PROGRAMS against the contract, bit for bit.

seqprogs.py restates sequences.div_seq / sqrt_seq as on-chip programs:
host classify/centre, one seq.run over the core lanes, host round_pack
from the deposits. This matrix holds that route bit-identical to
softfloat.div / softfloat.sqrt - bits AND flags - over the same operand
pool test_sequences.py uses, which carries the family every broken
construction fell to. If the branchless restore (CMPLT/SELECT/IADD in
place of the model's per-lane loop) diverged anywhere, the exact-tie
and binade-crossing families are where it would show.

Two shapes are exercised deliberately:

  * per-element runs (n=1) over the named hard families, so per-lane
    FLAGS are compared exactly, not as a batch union;
  * one big mixed batch per format and attribute - specials
    interleaved with core lanes - so the prep's lane filtering, the
    deposit indexing (i * 3 + k) and the flag accumulation are the
    thing under test, exactly the shape the C library reproduces.
"""

import random
import sys

import pytest

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256,
    one_bits, min_normal_bits,
)
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import seqprogs  # noqa: E402
from cft_golden.softfloat import RND_MODES  # noqa: E402

from test_sequences import pool_for  # noqa: E402


@pytest.mark.parametrize("fmt,extra", [
    (FP32, 24), (FP64, 24), (FP128, 8), (FP256, 6),
], ids=lambda v: getattr(v, "name", str(v)))
def test_div_program_matches_contract_batch(fmt, extra):
    pool = pool_for(fmt, extra)
    dens = pool[:min(len(pool), 18 if fmt.width <= 64 else 8)]
    pairs = [(a, b) for a in pool for b in dens]
    for rnd in RND_MODES:
        outs, flags = seqprogs.run_div(fmt, [p[0] for p in pairs],
                                       [p[1] for p in pairs], rnd)
        want_flags = 0
        for i, (a, b) in enumerate(pairs):
            wbits, wfl = sf.div(fmt, a, b, rnd)
            want_flags |= wfl
            assert outs[i] == wbits, (
                f"{fmt.name} rnd={rnd} {a:#x}/{b:#x}: "
                f"prog={outs[i]:#x} want={wbits:#x}")
        assert flags == want_flags, (
            f"{fmt.name} rnd={rnd}: batch flags {flags:#x} "
            f"want {want_flags:#x}")


@pytest.mark.parametrize("fmt", (FP32, FP64, FP128, FP256),
                         ids=lambda f: f.name)
def test_div_program_families_per_element(fmt):
    """n=1 runs so each lane's flags are compared exactly."""
    one = one_bits(fmt)
    mn = min_normal_bits(fmt)
    hard = [(one, one - 1), (one, one + 1), (one - 1, one),
            (mn, one - 1), (mn + 1, one + 1),
            (one | fmt.sign_mask, one - 1), (one, (one - 1) | fmt.sign_mask)]
    for rnd in RND_MODES:
        for a, b in hard:
            outs, flags = seqprogs.run_div(fmt, [a], [b], rnd)
            want = sf.div(fmt, a, b, rnd)
            assert (outs[0], flags) == want, (
                f"{fmt.name} rnd={rnd} {a:#x}/{b:#x}: "
                f"prog={outs[0]:#x},{flags} want={want[0]:#x},{want[1]}")


@pytest.mark.parametrize("fmt,extra", [
    (FP32, 40), (FP64, 40), (FP128, 16), (FP256, 12),
], ids=lambda v: getattr(v, "name", str(v)))
def test_sqrt_program_matches_contract_batch(fmt, extra):
    pool = pool_for(fmt, extra)
    for rnd in RND_MODES:
        outs, flags = seqprogs.run_sqrt(fmt, pool, rnd)
        want_flags = 0
        for i, a in enumerate(pool):
            wbits, wfl = sf.sqrt(fmt, a, rnd)
            want_flags |= wfl
            assert outs[i] == wbits, (
                f"{fmt.name} rnd={rnd} {a:#x}: "
                f"prog={outs[i]:#x} want={wbits:#x}")
        assert flags == want_flags


@pytest.mark.parametrize("fmt", (FP32, FP64, FP128, FP256),
                         ids=lambda f: f.name)
def test_sqrt_program_families_per_element(fmt):
    one = one_bits(fmt)
    mn = min_normal_bits(fmt)
    hard = [one + 1, mn + 1, mn - 1, one - 1, one,
            (one + 1) | fmt.sign_mask]
    for rnd in RND_MODES:
        for a in hard:
            outs, flags = seqprogs.run_sqrt(fmt, [a], rnd)
            want = sf.sqrt(fmt, a, rnd)
            assert (outs[0], flags) == want


def test_div_program_stress_binary64():
    rng = random.Random(4242)
    xs_a = [rng.getrandbits(64) for _ in range(400)]
    xs_b = [rng.getrandbits(64) for _ in range(400)]
    for rnd in RND_MODES:
        outs, _ = seqprogs.run_div(FP64, xs_a, xs_b, rnd)
        for i in range(len(xs_a)):
            assert outs[i] == sf.div(FP64, xs_a[i], xs_b[i], rnd)[0]


def test_sqrt_program_stress_binary64():
    rng = random.Random(4343)
    xs = [rng.getrandbits(64) for _ in range(600)]
    for rnd in RND_MODES:
        outs, _ = seqprogs.run_sqrt(FP64, xs, rnd)
        for i in range(len(xs)):
            assert outs[i] == sf.sqrt(FP64, xs[i], rnd)[0]


@pytest.mark.parametrize("fmt", (FP32, FP64, FP128, FP256),
                         ids=lambda f: f.name)
def test_programs_are_canonical(fmt):
    """Same emitter, same bytes: the digest is what a host attests, so
    the builder must be deterministic; and the images must stay inside
    the envelopes the RTL provisions (IMEM_D=1024, KREG=16)."""
    for build in (seqprogs.div_program, seqprogs.sqrt_program):
        p1, p2 = build(fmt), build(fmt)
        assert p1.digest() == p2.digest()
        assert len(p1.insns) <= 80
        assert len(p1.consts) <= 16
        assert p1.max_deposits == 3
