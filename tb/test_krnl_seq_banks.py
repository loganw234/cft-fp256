# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The sequencer against BANKED memory: each master gets its own store.

Why this exists, precisely. `test_krnl_seq.py` backs all four masters
with ONE memory and asserts that they share it, deliberately - so a
wrong PROG_PTR cannot read a program that exists nowhere the tile could
have put it. That is the right call for what that bench tests, and it
is also what let a real bug through untouched for a day.

A sequencer run loads r0, r1 and r2 from the caller's A, B and C
buffers. Those reads used to leave through m_axi_a regardless of which
buffer they were for, and with one shared store that is invisible: the
bytes are correct whichever master fetches them. On the card they are
not. hw/link.cfg binds every master to one HBM pseudo-channel, XRT puts
the B buffer in HBM[1] at 0x10000000, and the A master's window ends at
0x0FFFFFFF - so the first hardware-emulation run of the sequencer
answered DECERR on every program while the elementwise engine, which
has a master per stream, passed on the same image.

So this bench models the property the shared store cannot: each master
sees ONLY its own buffer. The A store holds the program image and the A
operand, B holds B, C holds C, and nothing is mirrored. A read that
leaves through the wrong master finds poison instead of operands and
the deposits disagree - which is the failure this file exists to
produce.

It is a companion to test_krnl_seq.py, not a replacement: that bench
proves the sequencer's semantics against seq.py, this one proves its
reads reach the right memory. Neither subsumes the other, and the
shared-store bench must keep sharing for the reason its own comment
gives.
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

from cft_golden import FP32, FP64, PREC_CODE, seq  # noqa: E402
from cft_golden.softfloat import one_bits  # noqa: E402

CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50
PROGPTR, CNTPTR = 0x54, 0x5C
MODE_SEQ = 1 << 15

# Deliberately the SAME offsets in every store. The addresses are
# identical; only the master differs. That is the point - if the select
# were ignored, the address alone would still land somewhere plausible,
# exactly as it did on the shared store, and only the DATA can tell the
# two apart.
A_BASE = B_BASE = C_BASE = 0x1000
PROG_BASE = 0x8000
D_BASE, CNT_BASE = 0x2000, 0x4000
POISON = 0x5A


async def write64(axil, addr, val):
    await axil.write_dword(addr, val & 0xFFFFFFFF)
    await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)


def pack(fmt, values):
    eb = fmt.width // 8
    return b"".join(v.to_bytes(eb, "little") for v in values)


async def poll_done(dut, axil, what, tries=4000):
    for _ in range(tries):
        await ClockCycles(dut.ap_clk, 10)
        if (await axil.read_dword(CTRL)) & 0x2:
            return
    raise AssertionError(f"{what}: the kernel never finished")


async def run_banked(dut, fmt):
    """One program that deposits r0, r1 and r2, with each operand
    reachable through exactly one master."""
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)

    # FOUR private stores. No mem= sharing anywhere: that is the whole
    # experiment.
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 20)
    assert ram_b.mem is not ram_a.mem and ram_c.mem is not ram_a.mem, \
        "this bench is worthless if the stores are shared"

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    assert await axil.read_dword(MAGIC) == 0x43465430

    n = 8
    rng = random.Random(0xBA5E)
    # Distinct, recognisable operands per stream: if a read leaves
    # through the wrong master the deposits carry the wrong stream's
    # values, not merely wrong bits.
    va = [one_bits(fmt) for _ in range(n)]
    vb = [(fmt.bias + 1) << fmt.man_w for _ in range(n)]      # 2.0
    vc = [(fmt.bias + 2) << fmt.man_w for _ in range(n)]      # 4.0

    prog = seq.Program(fmt,
                       [seq.deposit(0), seq.deposit(1), seq.deposit(2),
                        seq.halt()],
                       max_deposits=3)
    image = prog.to_bytes()

    # Each buffer into its OWN store, and poison everywhere else so a
    # read down the wrong master cannot accidentally find the right
    # answer.
    for r in (ram_a, ram_b, ram_c):
        r.write(0x0, bytes([POISON]) * 0x10000)
    ram_a.write(A_BASE, pack(fmt, va))
    ram_b.write(B_BASE, pack(fmt, vb))
    ram_c.write(C_BASE, pack(fmt, vc))
    ram_a.write(PROG_BASE, image)          # prog travels with the A master
    eb = fmt.width // 8
    ram_d.write(D_BASE, bytes([POISON]) * (n * 3 * eb + 64))
    ram_d.write(CNT_BASE, bytes([POISON]) * (n * 4 + 64))

    await axil.write_dword(MODE, (PREC_CODE[fmt.name] << 8) | MODE_SEQ)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await write64(axil, PROGPTR, PROG_BASE)
    await write64(axil, CNTPTR, CNT_BASE)
    await axil.write_dword(CTRL, 1)
    await poll_done(dut, axil, f"{fmt.name} banked sequencer run")

    status = await axil.read_dword(STATUS)
    assert (status & 0x7) == 0, \
        f"{fmt.name}: STATUS {status:#07b} - the memory system faulted, " \
        "which is what a read down the wrong master looks like on a card"

    got = ram_d.read(D_BASE, n * 3 * eb)
    bad = 0
    for i in range(n):
        for d, want in enumerate((va[i], vb[i], vc[i])):
            off = (i * 3 + d) * eb
            g = int.from_bytes(got[off:off + eb], "little")
            if g != want:
                bad += 1
                if bad <= 6:
                    dut._log.error(
                        f"{fmt.name} lane {i} deposit {d}: got {g:#x} "
                        f"want {want:#x} - operand {'abc'[d]} did not come "
                        f"from the {'ABC'[d]} master")
    assert bad == 0, f"{fmt.name}: {bad} deposits came from the wrong store"
    dut._log.info(f"{fmt.name}: r0/r1/r2 each fetched through their own "
                  f"master, {n} lanes x 3 deposits exact")


@cocotb.test()
async def sequencer_reads_reach_the_right_bank(dut):
    await run_banked(dut, FP32)
