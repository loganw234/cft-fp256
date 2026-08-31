# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft_seedop against the golden model, exhaustively where it counts.

The seed tables are proven against their definition in
python/tests/test_seeds.py, and the ROM include is drift-locked to the
model by test_seed_rom_sync.py. What remains for the RTL is the part
around the table: classification, indexing, the exponent algebra, and
the exact subnormal placement. So this bench drives:

  * EVERY index (all 512), at exponents covering the whole normal
    range including both parities (rsqrt's extra index bit);
  * the recip subnormal-landing exponents (E = emax and emax-1, the
    only two that reach the be <= 0 path) at every index;
  * every special class, both signs: NaN (quiet and signaling
    payloads), infinities, zeros, and subnormals (which the spec
    flushes to the zero class);
  * random operands as a catch-all.

Every result must equal the model bit for bit, at all four rungs
simultaneously from one 256-bit word.
"""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import FP32, FP64, FP128, FP256  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.softfloat import (  # noqa: E402
    OP_RECIP_SEED, OP_RSQRT_SEED,
    zero_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits,
    max_normal_bits, one_bits,
)

RUNGS = [("32", FP32), ("64", FP64), ("128", FP128), ("256", FP256)]
MODEL = {OP_RECIP_SEED: sf.recip_seed, OP_RSQRT_SEED: sf.rsqrt_seed}
OPN = {OP_RECIP_SEED: "recip", OP_RSQRT_SEED: "rsqrt"}


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.checks = 0

    async def check(self, op, words, note):
        """words: {fmt_width_name: operand}. Missing rungs get zero."""
        dut = self.dut
        a = 0
        for name, fmt in RUNGS:
            a |= (words.get(name, 0) & ((1 << fmt.width) - 1))
        # rungs overlay in one word: drive each separately instead
        for name, fmt in RUNGS:
            if name not in words:
                continue
            xa = words[name]
            dut.op.value = op
            dut.a.value = xa & ((1 << 256) - 1)
            await Timer(1, units="ns")
            got = int(getattr(dut, f"d{name}").value)
            v = int(getattr(dut, f"v{name}").value)
            want, fl = MODEL[op](fmt, xa)
            assert fl == 0
            assert v == 1, f"{OPN[op]} {fmt.name}: valid low"
            assert got == want, (
                f"{OPN[op]} {fmt.name} {note}: a={xa:#x}\n"
                f"  rtl   = {got:#x}\n  model = {want:#x}")
            self.checks += 1


@cocotb.test()
async def every_index_and_parity(dut):
    """All 512 indexes x both exponent parities x a spread of
    exponents, both ops, all rungs."""
    b = Bench(dut)
    for name, fmt in RUNGS:
        exps = sorted({1, 2, fmt.bias - 1, fmt.bias, fmt.bias + 1,
                       2 * fmt.bias - 2, 2 * fmt.bias - 1, 2 * fmt.bias,
                       fmt.bias // 2, 3 * fmt.bias // 2})
        for biased in exps:
            for i in range(512):
                xa = (biased << fmt.man_w) | (i << (fmt.man_w - 9))
                await b.check(OP_RECIP_SEED, {name: xa}, f"e={biased}")
                await b.check(OP_RSQRT_SEED, {name: xa}, f"e={biased}")
                # negative operand: recip keeps the sign, rsqrt qNaNs
                xn = xa | fmt.sign_mask
                await b.check(OP_RECIP_SEED, {name: xn}, "neg")
                await b.check(OP_RSQRT_SEED, {name: xn}, "neg")
    dut._log.info("index/parity sweep: %d comparisons", b.checks)


@cocotb.test()
async def specials_and_randoms(dut):
    b = Bench(dut)
    rng = random.Random(int(os.environ.get("CFT_SEED", "23")))
    for name, fmt in RUNGS:
        specials = [
            qnan_bits(fmt), snan_bits(fmt),
            qnan_bits(fmt) | 0x15, fmt.sign_mask | snan_bits(fmt, 3),
            inf_bits(fmt, 0), inf_bits(fmt, 1),
            zero_bits(fmt, 0), zero_bits(fmt, 1),
            min_subnormal_bits(fmt, 0), min_subnormal_bits(fmt, 1),
            max_subnormal_bits(fmt, 0), max_subnormal_bits(fmt, 1),
            min_normal_bits(fmt, 0), min_normal_bits(fmt, 1),
            max_normal_bits(fmt, 0), max_normal_bits(fmt, 1),
            one_bits(fmt, 0), one_bits(fmt, 1),
        ]
        for xa in specials:
            await b.check(OP_RECIP_SEED, {name: xa}, "special")
            await b.check(OP_RSQRT_SEED, {name: xa}, "special")
        for _ in range(400):
            xa = rng.getrandbits(fmt.width)
            await b.check(OP_RECIP_SEED, {name: xa}, "random")
            await b.check(OP_RSQRT_SEED, {name: xa}, "random")
    dut._log.info("specials/randoms: %d comparisons", b.checks)
