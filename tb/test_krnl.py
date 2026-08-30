# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Kernel-level end-to-end test: the full cft_krnl RTL against the
golden model, through the same interfaces XRT uses on the card.

cocotbext-axi provides the host (AxiLiteMaster on s_axi_control) and
the HBM (AxiRam on m00_axi). Operand arrays are staged in the RAM, the
CSRs are programmed exactly as host/cft_host does, and every result
element plus the sticky FLAGS register is compared bit-for-bit against
cft_golden.compute - which makes this one test cover the CSR block,
the engine FSM, the AXI master, the operand steering muxes, and both
compute banks."""

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cocotbext.axi import (  # noqa: E402
    AxiLiteBus, AxiLiteMaster, AxiRamRead, AxiRamWrite,
    AxiReadBus, AxiWriteBus,
)

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, PREC_CODE,
    OP_FMA, OP_ADD, OP_SUB, OP_MUL, OP_NAMES, SIMPLE_OPS,
    OP_COPYSIGN, OP_MAX, OP_MINNUM, OP_SELECT, OP_CMPLT,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_NAMES,
    compute, vectors,
)

# CSR map (cft_csr.sv / hw/kernel.xml)
CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50

A_BASE, B_BASE, C_BASE, D_BASE = 0x00000, 0x40000, 0x80000, 0xC0000


async def write64(axil, addr, val):
    await axil.write_dword(addr, val & 0xFFFFFFFF)
    await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)


def gen_stream(fmt, n, rng):
    """Operand stream: a blend of raw random patterns and the directed
    specials, so the engine meets NaN, inf, and subnormals in flight."""
    pool = vectors.interesting_operands(fmt)
    out = []
    for _ in range(n):
        if rng.random() < 0.25:
            out.append(rng.choice(pool))
        else:
            out.append(rng.getrandbits(fmt.width))
    return out


async def run_op(dut, axil, ram, fmt, op, n, seed, bases=None, rnd=RND_RNE):
    ba, bb, bc, bd = bases if bases else (A_BASE, B_BASE, C_BASE, D_BASE)
    ebytes = fmt.width // 8
    rng = random.Random(seed)
    va = gen_stream(fmt, n, rng)
    vb = gen_stream(fmt, n, rng)
    vc = gen_stream(fmt, n, rng)

    exp = [compute(fmt, op, va[i], vb[i], vc[i], rnd) for i in range(n)]
    exp_d = [e[0] for e in exp]
    exp_f = 0
    for e in exp:
        exp_f |= e[1]

    ram.write(ba, b"".join(v.to_bytes(ebytes, "little") for v in va))
    ram.write(bb, b"".join(v.to_bytes(ebytes, "little") for v in vb))
    ram.write(bc, b"".join(v.to_bytes(ebytes, "little") for v in vc))
    ram.write(bd, b"\xAA" * (n * ebytes))  # prove full overwrite

    await axil.write_dword(MODE, op | (PREC_CODE[fmt.name] << 8) | (rnd << 12))
    await write64(axil, NREG, n)
    await write64(axil, APTR, ba)
    await write64(axil, BPTR, bb)
    await write64(axil, CPTR, bc)
    await write64(axil, DPTR, bd)
    await axil.write_dword(CTRL, 1)

    for _ in range(5000):
        await ClockCycles(dut.ap_clk, 10)
        status = await axil.read_dword(CTRL)
        if status & 0x2:  # ap_done (clear-on-read)
            break
    else:
        raise AssertionError(f"{fmt.name} {OP_NAMES[op]}: kernel never finished")

    got = ram.read(bd, n * ebytes)
    bad = 0
    for i in range(n):
        g = int.from_bytes(got[i * ebytes:(i + 1) * ebytes], "little")
        if g != exp_d[i]:
            bad += 1
            if bad <= 10:
                dut._log.error(
                    f"{fmt.name} {OP_NAMES[op]} [{i}]: a={va[i]:#x} "
                    f"b={vb[i]:#x} c={vc[i]:#x} got={g:#x} want={exp_d[i]:#x}")
    assert bad == 0, f"{fmt.name} {OP_NAMES[op]}: {bad}/{n} elements differ"

    got_f = await axil.read_dword(FLAGS)
    assert got_f == exp_f, \
        f"{fmt.name} {OP_NAMES[op]}: FLAGS {got_f:#07b} want {exp_f:#07b}"
    # the memory system vouched for every beat: a clean STATUS is what
    # makes the bit-exactness above mean anything
    got_err = await axil.read_dword(STATUS)
    assert got_err == 0, \
        f"{fmt.name} {OP_NAMES[op]}: STATUS {got_err:#05b}, bus faults during the run"
    dut._log.info(f"{fmt.name} {OP_NAMES[op]} {RND_NAMES[rnd]} n={n}: "
                  f"bit-exact, flags {got_f:#07b}")


@cocotb.test()
async def krnl_end_to_end(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    # Four masters, ONE memory.
    #
    # The engine has a dedicated port per stream now, but a, b, c and d
    # are regions of a single address space - the same HBM - so the four
    # attachments must share a backing store. Give them separate ones
    # and the test still passes for the wrong reason: each reader sees
    # the operands the test wrote into its own private copy, and a
    # genuine address-decode bug in the engine goes unnoticed because
    # every stream reads from a memory where only its own data exists.
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 20, mem=ram_a.mem)
    # Staging and readback both go through the shared store; which
    # attachment is used to reach it does not matter, and naming one
    # `ram` keeps run_op unchanged.
    ram = ram_a
    assert ram_b.mem is ram_a.mem and ram_c.mem is ram_a.mem \
        and ram_d.mem is ram_a.mem, \
        "the four masters must address one memory or this bench proves " \
        "nothing about address decode"

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    assert await axil.read_dword(VERSION) == 0x00000410
    caps = await axil.read_dword(CAPS)
    assert (caps & 0xF) == 0xF, "full tile advertises all four rungs"
    assert ((caps >> 8) & 0xFF) == 0b0001_1111, (
        "arithmetic, sign, min/max, predicate and integer groups present; "
        "reduction, divide/sqrt and conversion not yet built")
    status = await axil.read_dword(CTRL)
    assert status & 0x4, "kernel must come up idle"

    await run_op(dut, axil, ram, FP32, OP_FMA, 48, seed=101)
    await run_op(dut, axil, ram, FP32, OP_ADD, 32, seed=102)
    await run_op(dut, axil, ram, FP32, OP_SUB, 32, seed=103)
    await run_op(dut, axil, ram, FP32, OP_MUL, 32, seed=104)
    await run_op(dut, axil, ram, FP256, OP_FMA, 6, seed=105)
    await run_op(dut, axil, ram, FP256, OP_MUL, 4, seed=106)
    await run_op(dut, axil, ram, FP32, OP_FMA, 16, seed=107)  # single-beat run
    await run_op(dut, axil, ram, FP64, OP_FMA, 24, seed=108)
    await run_op(dut, axil, ram, FP64, OP_SUB, 16, seed=109)
    await run_op(dut, axil, ram, FP128, OP_FMA, 8, seed=110)
    await run_op(dut, axil, ram, FP128, OP_ADD, 6, seed=111)
    await run_op(dut, axil, ram, FP64, OP_MUL, 4, seed=112)  # single-beat run

    # stream-engine stressors: multi-burst runs, a ragged tail, and
    # buffers placed so bursts must split at 4KB AXI boundaries
    await run_op(dut, axil, ram, FP32, OP_FMA, 296, seed=113)  # 37 beats
    await run_op(dut, axil, ram, FP64, OP_ADD, 128, seed=114)  # 32 beats
    await run_op(dut, axil, ram, FP256, OP_FMA, 40, seed=115)  # 3 bursts
    await run_op(dut, axil, ram, FP32, OP_MUL, 64, seed=116,
                 bases=(0x00FE0, 0x41FC0, 0x82FA0, 0xC3F20))

    # every rounding attribute, end to end through the CSR field
    for rnd in (RND_RTZ, RND_RDN, RND_RUP, RND_RMM):
        await run_op(dut, axil, ram, FP32, OP_FMA, 32, seed=120 + rnd, rnd=rnd)
    await run_op(dut, axil, ram, FP64, OP_FMA, 16, seed=130, rnd=RND_RDN)
    await run_op(dut, axil, ram, FP128, OP_MUL, 6, seed=131, rnd=RND_RUP)
    await run_op(dut, axil, ram, FP256, OP_FMA, 4, seed=132, rnd=RND_RTZ)

    # back-to-back runs that differ only in attribute must differ in
    # results the way the contract says, and the CSR must not leak the
    # previous run's mode into the next one
    await run_op(dut, axil, ram, FP32, OP_ADD, 32, seed=140, rnd=RND_RUP)
    await run_op(dut, axil, ram, FP32, OP_ADD, 32, seed=140, rnd=RND_RDN)
    await run_op(dut, axil, ram, FP32, OP_ADD, 32, seed=140, rnd=RND_RNE)

    # the non-arithmetic opcodes, end to end through the MODE field.
    # These bypass the datapath, so the run also proves the engine's
    # collection path delivers a bypassed result at the same latency as
    # a computed one - the two share a delay line.
    for i, op in enumerate(SIMPLE_OPS):
        await run_op(dut, axil, ram, FP32, op, 32, seed=200 + i)
    await run_op(dut, axil, ram, FP64, OP_MINNUM, 16, seed=210)
    await run_op(dut, axil, ram, FP128, OP_COPYSIGN, 8, seed=211)
    await run_op(dut, axil, ram, FP256, OP_MAX, 4, seed=212)
    await run_op(dut, axil, ram, FP64, OP_CMPLT, 16, seed=213)
    await run_op(dut, axil, ram, FP256, OP_SELECT, 4, seed=214)
    # select is the only non-arithmetic opcode that reads c, so it is
    # the only end-to-end check that each bank's c slice is wired to
    # that bank's own operand. Run it on every rung, not just two.
    await run_op(dut, axil, ram, FP64, OP_SELECT, 16, seed=215)
    await run_op(dut, axil, ram, FP128, OP_SELECT, 8, seed=216)


# ---- raw AXI4-Lite corner cases --------------------------------------
#
# cocotbext-axi's AxiLiteMaster issues one write at a time and waits for
# BVALID before starting the next, which is also what XRT's MMIO path
# does. That politeness hides a whole class of CSR bugs: anything the
# slave gets wrong about WHEN it samples the bus is invisible to a
# master that never changes the bus. These tests drive the control
# signals by hand to close that gap.

async def _raw_idle(dut):
    dut.s_axi_control_awvalid.value = 0
    dut.s_axi_control_wvalid.value = 0
    dut.s_axi_control_arvalid.value = 0
    dut.s_axi_control_bready.value = 1
    dut.s_axi_control_rready.value = 1
    dut.s_axi_control_wstrb.value = 0xF


async def _raw_read(dut, addr):
    await RisingEdge(dut.ap_clk)
    dut.s_axi_control_araddr.value = addr
    dut.s_axi_control_arvalid.value = 1
    while True:
        await ReadOnly()
        accepted = int(dut.s_axi_control_arready.value)
        await RisingEdge(dut.ap_clk)
        if accepted:
            break
    dut.s_axi_control_arvalid.value = 0
    while True:
        await ReadOnly()
        if int(dut.s_axi_control_rvalid.value):
            val = int(dut.s_axi_control_rdata.value)
            await RisingEdge(dut.ap_clk)
            return val
        await RisingEdge(dut.ap_clk)


@cocotb.test()
async def csr_latches_the_handshake_beat(dut):
    """A register must keep the WDATA that was on the bus at the W
    handshake, not whatever the master drives afterwards.

    AXI4-Lite requires WDATA to be valid only while WVALID is asserted;
    once the handshake completes the master may drive anything. This
    slave commits the write a cycle later (it waits for both AW and W),
    so reading the live bus at commit time captures the wrong cycle.
    Here the master hands over a value and immediately drives garbage,
    which is exactly what a pipelined master or a FIFO-fed W channel
    does between beats."""
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    await _raw_idle(dut)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    POISON = 0xDEADBEEF
    for addr, want in ((NREG, 0x12345678), (MODE, 0x00000123),
                       (APTR, 0x0000BEE0)):
        await RisingEdge(dut.ap_clk)
        dut.s_axi_control_awaddr.value = addr
        dut.s_axi_control_awvalid.value = 1
        dut.s_axi_control_wdata.value = want
        dut.s_axi_control_wvalid.value = 1
        await ReadOnly()
        assert int(dut.s_axi_control_awready.value) == 1
        assert int(dut.s_axi_control_wready.value) == 1
        await RisingEdge(dut.ap_clk)      # the handshake edge
        # the master moves on the very next cycle
        dut.s_axi_control_awvalid.value = 0
        dut.s_axi_control_wvalid.value = 0
        dut.s_axi_control_wdata.value = POISON
        dut.s_axi_control_awaddr.value = 0
        await ClockCycles(dut.ap_clk, 6)

        got = await _raw_read(dut, addr)
        assert got == want, (
            f"CSR {addr:#x}: read back {got:#010x}, wrote {want:#010x} "
            f"(bus carried {POISON:#010x} the cycle after the handshake)")
    dut._log.info("CSR latches the handshake beat, not the following cycle")
