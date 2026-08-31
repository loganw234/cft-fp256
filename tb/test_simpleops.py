# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The rewritten non-arithmetic block against the one it replaced.

cft_simpleops was restructured for area: twenty-odd W-bit sources
feeding one mux became eight, two barrel shifters became one plus a
bit reversal, two adders became one carry chain, and three magnitude
comparators became one. None of that is supposed to change a single
output bit, and this bench is the claim that it does not.

The comparison is against tb/wrappers/cft_simpleops_ref.sv - a frozen
copy of the previous implementation - and not against the golden
model, for the same reason test_mulshare compares two multiplier
arrangements to each other. Equivalence is best tested by subtraction:
nothing has to agree about what the right answer IS for a difference
to be caught, so the check covers ground the model comparison cannot
reach at all. Three examples that matter here:

  * reserved opcodes. 15 and everything above 23 must answer with the
    canonical qNaN and raise invalid. The model has no opinion about
    an opcode it does not define.
  * the arithmetic group. Opcodes 0-3 leave `valid` low and `d`
    unread, but the rewrite still has to produce the same unread
    value, because "unread" is a property of the engine and not of
    this module.
  * flags on operands the model never emits, such as a signaling NaN
    reaching min/max, where the flag is raised but the payload is not
    canonicalised.

All four rungs run from one 256-bit operand word on every drive, so a
mistake in the bit reversal that only appears past 32 bits cannot hide
behind a passing fp32 check. Each directed pass in turn places one
format's specials in the low bits, so every format meets real NaNs,
infinities, subnormals and signed zeros rather than random patterns.

    CFT_RANDOM   random drives (default 6000)
    CFT_SEED     vector seed (default 7)
"""

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import Timer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import FP32, FP64, FP128, FP256, vectors  # noqa: E402

SETTLE_NS = 1

# (name, format, width) - the width is the slice of the 256-bit operand
# word that instance sees, and the suffix pairs the ref and new ports.
RUNGS = [
    ("32", FP32, 32),
    ("64", FP64, 64),
    ("128", FP128, 128),
    ("256", FP256, 256),
]

OP_NAMES = {
    0: "fma", 1: "add", 2: "sub", 3: "mul",
    4: "abs", 5: "neg", 6: "copysign",
    7: "min", 8: "max", 9: "minnum", 10: "maxnum",
    11: "select", 12: "cmplt", 13: "cmple", 14: "cmpeq",
    16: "iand", 17: "ior", 18: "ixor", 19: "iadd", 20: "isub",
    21: "ishl", 22: "ishr", 23: "icmplt",
}

# Everything this module answers, plus the arithmetic group whose
# unread default still has to match.
HANDLED_OPS = [o for o in range(24) if o != 15]


def _int(sig):
    """Read a signal, refusing X/Z rather than silently comparing them."""
    val = sig.value
    binstr = val.binstr.lower()
    if "x" in binstr or "z" in binstr:
        raise AssertionError(f"{sig._name} is {val.binstr}")
    return int(val)


class Checker:
    """Drives one (op, a, b, c) and compares all four rungs."""

    def __init__(self, dut):
        self.dut = dut
        self.checks = 0

    async def drive(self, op, a, b, c, note=""):
        dut = self.dut
        dut.op.value = op
        dut.a.value = a
        dut.b.value = b
        dut.c.value = c
        await Timer(SETTLE_NS, units="ns")

        for name, fmt, width in RUNGS:
            d_r = _int(getattr(dut, f"d{name}_r"))
            d_n = _int(getattr(dut, f"d{name}_n"))
            f_r = _int(getattr(dut, f"f{name}_r"))
            f_n = _int(getattr(dut, f"f{name}_n"))
            v_r = _int(getattr(dut, f"v{name}_r"))
            v_n = _int(getattr(dut, f"v{name}_n"))

            if (d_r, f_r, v_r) != (d_n, f_n, v_n):
                mask = (1 << width) - 1
                opname = OP_NAMES.get(op, f"reserved({op})")
                raise AssertionError(
                    f"fp{name} {opname} {note}\n"
                    f"  a     = 0x{a & mask:0{width // 4}x}\n"
                    f"  b     = 0x{b & mask:0{width // 4}x}\n"
                    f"  c     = 0x{c & mask:0{width // 4}x}\n"
                    f"  ref   d=0x{d_r:0{width // 4}x} flags=0b{f_r:05b} valid={v_r}\n"
                    f"  new   d=0x{d_n:0{width // 4}x} flags=0b{f_n:05b} valid={v_n}"
                )
            self.checks += 1


def _pool(fmt, rng, count):
    """Directed specials for `fmt`, padded out with random patterns."""
    ops = list(vectors.interesting_operands(fmt))
    mask = (1 << fmt.width) - 1
    # The pattern SELECT is easiest to get wrong: it tests c's
    # MAGNITUDE, so negative zero selects b, not a.
    ops.append(fmt.sign_mask)
    while len(ops) < count:
        ops.append(rng.getrandbits(fmt.width) & mask)
    return ops


def _widen(value, fmt, rng):
    """Place a format-sized operand in the low bits of a 256-bit word.

    The high bits are random rather than zero. Zeroing them would make
    every wider instance see a subnormal on every drive, which is one
    operand class repeated 6000 times instead of four rungs of
    coverage - and the equivalence claim holds for arbitrary patterns,
    so there is nothing to lose by filling them.
    """
    if fmt.width >= 256:
        return value
    return value | (rng.getrandbits(256 - fmt.width) << fmt.width)


@cocotb.test()
async def test_opcode_map(dut):
    """Every one of the 256 opcodes, including all 233 reserved ones.

    The reserved trap is the reason to sweep the whole space rather
    than the defined subset: `is_reserved` is (op == 15) || (op > 23),
    and an off-by-one there is invisible to any bench that only drives
    opcodes it knows the names of.
    """
    rng = random.Random(int(os.environ.get("CFT_SEED", "7")))
    chk = Checker(dut)

    operands = []
    for fmt in (FP32, FP256):
        pool = _pool(fmt, rng, 12)
        for _ in range(4):
            operands.append((
                _widen(rng.choice(pool), fmt, rng),
                _widen(rng.choice(pool), fmt, rng),
                _widen(rng.choice(pool), fmt, rng),
            ))

    for op in range(256):
        for a, b, c in operands:
            await chk.drive(op, a, b, c, note="opcode sweep")

    dut._log.info("opcode sweep: %d comparisons over 256 opcodes", chk.checks)


@cocotb.test()
async def test_directed(dut):
    """Every handled opcode against every pair of one format's specials.

    Run once per rung with that rung's operands in the low bits, so
    fp128's signaling NaNs and fp256's subnormals are real patterns and
    not whatever a random draw happened to land on.
    """
    rng = random.Random(int(os.environ.get("CFT_SEED", "7")) + 1)
    chk = Checker(dut)

    for _, fmt, _width in RUNGS:
        pool = _pool(fmt, rng, 0)
        # c drives SELECT only, and only through "is the magnitude
        # nonzero", so three cases exhaust its influence: zero, a
        # sign-only word whose magnitude is still zero, and anything
        # else.
        cs = [0, fmt.sign_mask, rng.getrandbits(fmt.width) | 1]
        for op in HANDLED_OPS:
            for a in pool:
                for b in pool:
                    c = cs[(a ^ b) % len(cs)]
                    await chk.drive(
                        op,
                        _widen(a, fmt, rng),
                        _widen(b, fmt, rng),
                        _widen(c, fmt, rng),
                        note=f"directed {fmt.name}",
                    )

    dut._log.info("directed: %d comparisons", chk.checks)


@cocotb.test()
async def test_shift_counts(dut):
    """Every shift count at every width.

    The rewrite replaced the right-shift ladder with a bit reversal
    around the left-shift ladder, so the count is the axis a mistake
    would live on: an off-by-one in the reversal shows as a one-bit
    rotation, which only some counts expose. b's low 8 bits are the
    fp256 count and its low 5 the fp32 count, so sweeping 0-255 sweeps
    all four rungs at once.
    """
    rng = random.Random(int(os.environ.get("CFT_SEED", "7")) + 2)
    chk = Checker(dut)

    patterns = [
        (1 << 256) - 1,                      # all ones: fill direction
        1,                                    # lowest bit
        1 << 255,                             # highest bit
        0x5555555555555555 * ((1 << 192) + 1),  # alternating
    ]
    patterns += [rng.getrandbits(256) for _ in range(6)]

    for op in (21, 22):                       # ISHL, ISHR
        for shamt in range(256):
            for a in patterns:
                b = (rng.getrandbits(256) & ~0xFF) | shamt
                await chk.drive(op, a, b, 0, note=f"shamt={shamt}")

    dut._log.info("shift counts: %d comparisons", chk.checks)


@cocotb.test()
async def test_random(dut):
    """Unstructured drives, to cover what the directed sets do not name."""
    budget = int(os.environ.get("CFT_RANDOM", "6000"))
    rng = random.Random(int(os.environ.get("CFT_SEED", "7")) + 3)
    chk = Checker(dut)

    pools = {fmt.name: _pool(fmt, rng, 48) for _, fmt, _w in RUNGS}

    for i in range(budget):
        _, fmt, _w = RUNGS[i % len(RUNGS)]
        pool = pools[fmt.name]
        # Blend directed specials with raw patterns: the integer group
        # has no notion of a special, and the float group has little
        # use for a uniformly random word.
        def operand():
            if rng.random() < 0.5:
                return _widen(rng.choice(pool), fmt, rng)
            return rng.getrandbits(256)

        op = rng.choice(HANDLED_OPS) if rng.random() < 0.9 else rng.getrandbits(8)
        await chk.drive(op, operand(), operand(), operand(), note="random")

    dut._log.info("random: %d comparisons over %d drives", chk.checks, budget)
