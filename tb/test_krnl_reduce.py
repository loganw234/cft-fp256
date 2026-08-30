# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""CFT_SUM through the whole kernel, against the golden model's tree.

cft_reduce_acc is already proven on its own. This is the integration:
the CSR carrying opcode 24, the engine serialising beats into the
accumulator instead of computing elementwise, lane 0 of the active bank
doubling as the accumulator's adder, and the writer emitting ONE beat
instead of n.

The sizes matter more than the count of them. A reduction's tree shape
depends on the element count, and the engine has a second size
dependence on top of it: the last beat is usually partial, and the
serializer must stop at the real element count rather than running to
the end of the beat, because the beat padding is zeros and adding +0.0
is not the identity. So the sizes here straddle beat boundaries in both
directions at every precision - n, n-1 and n+1 around multiples of 8, 4,
2 and 1 elements per beat.

CFT_DOT is deliberately not tested here because it is deliberately not
built: the contract makes dot(a,b) == sum(mul(a,b)) exact, so the host
issues a MUL then a SUM. That composition is checked in the model and
in libcft; what the hardware owes is SUM.
"""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cocotbext.axi import (  # noqa: E402
    AxiLiteBus, AxiLiteMaster, AxiRamRead, AxiRamWrite,
    AxiReadBus, AxiWriteBus,
)

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, PREC_CODE, RND_NAMES, vectors,
)
from cft_golden.reduce import OP_SUM, fsum  # noqa: E402

CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50
A_BASE, B_BASE, C_BASE, D_BASE = 0x00000, 0x40000, 0x80000, 0xC0000

FORMATS = [FP32, FP64, FP128, FP256]


async def write64(axil, addr, val):
    await axil.write_dword(addr, val & 0xFFFFFFFF)
    await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)


async def run_sum(dut, axil, ram, fmt, n, rnd, seed):
    rng = random.Random(seed)
    pool = vectors.interesting_operands(fmt)
    ebytes = fmt.width // 8

    vals = []
    for _ in range(n):
        if rng.random() < 0.30:
            vals.append(pool[rng.randrange(len(pool))])
        else:
            sign = rng.getrandbits(1)
            e = fmt.bias + rng.randint(-20, 20)
            m = rng.getrandbits(fmt.man_w)
            vals.append((sign << (fmt.width - 1)) | (e << fmt.man_w) | m)

    ram.write(A_BASE, b"".join(v.to_bytes(ebytes, "little") for v in vals))
    # b and c are unread by a sum, but the engine streams all three and
    # the FIFOs share a read enable, so they have to be real memory.
    ram.write(B_BASE, b"\x00" * max(n * ebytes, 32))
    ram.write(C_BASE, b"\x00" * max(n * ebytes, 32))
    ram.write(D_BASE, b"\xAA" * 32)

    await axil.write_dword(MODE, (rnd << 12) | (PREC_CODE[fmt.name] << 8)
                           | OP_SUM)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)

    for _ in range(8000):
        await ClockCycles(dut.ap_clk, 20)
        status = await axil.read_dword(CTRL)
        if status & 0x2:
            break
    else:
        raise AssertionError(
            f"{fmt.name} sum n={n}: kernel never finished - the reduction "
            f"never reached its flush, or the writer never emitted its beat")

    got = int.from_bytes(ram.read(D_BASE, ebytes), "little")
    got_f = await axil.read_dword(FLAGS)
    st = await axil.read_dword(STATUS)
    assert st == 0, f"{fmt.name} n={n}: STATUS {st:#x} - a bus fault"

    want, want_f = fsum(fmt, vals, rnd)
    assert got == want, (
        f"{fmt.name} sum n={n} {RND_NAMES[rnd]}: got {got:#x} want {want:#x}\n"
        f"  first inputs {[hex(v) for v in vals[:6]]}")
    assert got_f == want_f, (
        f"{fmt.name} sum n={n} {RND_NAMES[rnd]}: flags {got_f:#07b} "
        f"want {want_f:#07b}")
    return n


@cocotb.test()
async def sum_end_to_end(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    assert await axil.read_dword(VERSION) == 0x00000500, \
        "reductions are v0.5.0"
    caps = await axil.read_dword(CAPS)
    assert (caps >> 8) & (1 << 5), \
        "CAPS must advertise the reduction group once SUM is built"

    total = 0
    # Sizes straddling the beat boundary at each precision, so the
    # partial-tail path is exercised rather than assumed.
    per_fmt = {
        FP32:  [1, 2, 7, 8, 9, 15, 16, 17, 31, 33],
        FP64:  [1, 3, 4, 5, 7, 8, 9, 16, 17],
        FP128: [1, 2, 3, 4, 5, 8, 9],
        FP256: [1, 2, 3, 5, 8, 13],
    }
    for fmt in FORMATS:
        for n in per_fmt[fmt]:
            total += await run_sum(dut, axil, ram_a, fmt, n, 0, seed=100 + n)
        dut._log.info(f"{fmt.name}: sums over {len(per_fmt[fmt])} sizes "
                      f"straddling the beat boundary, bit-exact")
    dut._log.info(f"reduction end-to-end: {total} elements summed, exact")


@cocotb.test()
async def sum_every_rounding_attribute(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    total = 0
    for rnd in range(5):
        for fmt, n in ((FP32, 21), (FP64, 11), (FP128, 7), (FP256, 5)):
            total += await run_sum(dut, axil, ram_a, fmt, n, rnd,
                                   seed=900 + rnd)
    dut._log.info(f"all five rounding attributes x four precisions: "
                  f"{total} elements, exact")


@cocotb.test()
async def elementwise_still_works_after_a_reduction(dut):
    """A reduction must not leave the engine in a state that breaks the
    next run. The accumulator, the serializer and the one-shot result
    push all latch, and all of them are cleared at ap_start rather than
    at reset - so a sum followed by an fma is the case that catches a
    clear that was never wired."""
    from test_krnl import run_op  # noqa: E402
    from cft_golden import OP_FMA, OP_ADD  # noqa: E402

    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    await run_sum(dut, axil, ram_a, FP32, 13, 0, seed=7)
    await run_op(dut, axil, ram_a, FP32, OP_FMA, 24, seed=8)
    await run_sum(dut, axil, ram_a, FP64, 9, 0, seed=9)
    await run_op(dut, axil, ram_a, FP32, OP_ADD, 16, seed=10)
    await run_sum(dut, axil, ram_a, FP256, 5, 0, seed=11)
    dut._log.info("reduction and elementwise runs interleave cleanly")
