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
from cocotb.triggers import ClockCycles, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cocotbext.axi import AxiBus, AxiLiteBus, AxiLiteMaster, AxiRam  # noqa: E402

from cft_golden import (  # noqa: E402
    FP32, FP256, PREC_CODE, OP_FMA, OP_ADD, OP_SUB, OP_MUL, OP_NAMES,
    compute, vectors,
)

# CSR map (cft_csr.sv / hw/kernel.xml)
CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION = 0x40, 0x44, 0x48

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


async def run_op(dut, axil, ram, fmt, op, n, seed):
    ebytes = fmt.width // 8
    rng = random.Random(seed)
    va = gen_stream(fmt, n, rng)
    vb = gen_stream(fmt, n, rng)
    vc = gen_stream(fmt, n, rng)

    exp = [compute(fmt, op, va[i], vb[i], vc[i]) for i in range(n)]
    exp_d = [e[0] for e in exp]
    exp_f = 0
    for e in exp:
        exp_f |= e[1]

    ram.write(A_BASE, b"".join(v.to_bytes(ebytes, "little") for v in va))
    ram.write(B_BASE, b"".join(v.to_bytes(ebytes, "little") for v in vb))
    ram.write(C_BASE, b"".join(v.to_bytes(ebytes, "little") for v in vc))
    ram.write(D_BASE, b"\xAA" * (n * ebytes))  # prove full overwrite

    await axil.write_dword(MODE, op | (PREC_CODE[fmt.name] << 4))
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)

    for _ in range(5000):
        await ClockCycles(dut.ap_clk, 10)
        status = await axil.read_dword(CTRL)
        if status & 0x2:  # ap_done (clear-on-read)
            break
    else:
        raise AssertionError(f"{fmt.name} {OP_NAMES[op]}: kernel never finished")

    got = ram.read(D_BASE, n * ebytes)
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
    dut._log.info(f"{fmt.name} {OP_NAMES[op]} n={n}: bit-exact, flags {got_f:#07b}")


@cocotb.test()
async def krnl_end_to_end(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram = AxiRam(AxiBus.from_prefix(dut, "m00_axi"),
                 dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                 size=2 ** 20)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    assert await axil.read_dword(VERSION) == 0x00000100
    status = await axil.read_dword(CTRL)
    assert status & 0x4, "kernel must come up idle"

    await run_op(dut, axil, ram, FP32, OP_FMA, 48, seed=101)
    await run_op(dut, axil, ram, FP32, OP_ADD, 32, seed=102)
    await run_op(dut, axil, ram, FP32, OP_SUB, 32, seed=103)
    await run_op(dut, axil, ram, FP32, OP_MUL, 32, seed=104)
    await run_op(dut, axil, ram, FP256, OP_FMA, 6, seed=105)
    await run_op(dut, axil, ram, FP256, OP_MUL, 4, seed=106)
    await run_op(dut, axil, ram, FP32, OP_FMA, 16, seed=107)  # single-beat run
