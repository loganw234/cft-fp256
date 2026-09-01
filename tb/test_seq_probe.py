# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Diagnostic probe for cft_seq, not part of any suite.

`test_seq_core.py` says WHETHER the sequencer agrees with the golden
model. This says WHERE it is when it does not get that far: one
trivial program - add, deposit, halt over twelve fp32 lanes - driven
into a quiet module, with the state register, both bus channels and
the WALL-CLOCK cost of each cycle printed as it goes.

The wall clock is the part worth having, and it exists because of a
failure this bench could not otherwise have described. cft_seq stops
advancing simulation time on entering the deposit drain: Icarus sits
at 100% CPU inside one timestep and never leaves it. Every timeout
test_seq_core has is a SIMULATION-time timeout, so none of them can
fire - the symptom is a target that runs forever with no output, which
is indistinguishable from a slow simulator until something measures
the difference. This did: 310 cycles per wall second up to the drain,
then nothing, ever.

    make seqprobe

It follows tb/test_normseg_probe.py, which exists for the same reason
one level down.
"""

import sys
import time
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import FORMATS, PREC_CODE          # noqa: E402
from cft_golden import softfloat as sf             # noqa: E402
from cft_golden import seq                         # noqa: E402

import test_seq_core as core                       # noqa: E402

CYCLES = 4000
STALL_S = 2.0        # report any cycle that took longer than this


@cocotb.test()
async def probe(dut):
    fmt, n = FORMATS["fp32"], 12
    prog = seq.Program(fmt, [seq.alu(sf.OP_ADD, 4, 0, 1, 2),
                             seq.deposit(4), seq.halt()], max_deposits=1)
    ram = core.SeqRam(dut)

    cocotb.start_soon(Clock(dut.ap_clk, core.CLK_NS, units="ns").start())
    dut.start.value = 0
    dut.cfg_prec.value = 0
    for name in ("cfg_n", "cfg_a", "cfg_b", "cfg_c", "cfg_d",
                 "cfg_prog", "cfg_cnt"):
        getattr(dut, name).value = 0
    cocotb.start_soon(ram.serve())
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    ram.poison()
    ram.stage(core.PROG_BASE, prog.to_bytes())
    ones = b"".join(sf.one_bits(fmt).to_bytes(4, "little") for _ in range(n))
    for base in (core.A_BASE, core.B_BASE, core.C_BASE):
        ram.stage(base, ones)

    dut.cfg_prec.value = PREC_CODE[fmt.name]
    dut.cfg_n.value = n
    dut.cfg_a.value = core.A_BASE
    dut.cfg_b.value = core.B_BASE
    dut.cfg_c.value = core.C_BASE
    dut.cfg_d.value = core.D_BASE
    dut.cfg_prog.value = core.PROG_BASE
    dut.cfg_cnt.value = core.CNT_BASE

    await RisingEdge(dut.ap_clk)
    dut.start.value = 1
    await RisingEdge(dut.ap_clk)
    dut.start.value = 0

    t0 = last = time.monotonic()
    prev = None
    for cyc in range(CYCLES):
        await ReadOnly()
        st = core._i(dut.st, -1)
        now = time.monotonic()
        row = (st, core._i(dut.m_rd_arvalid), core._i(dut.m_rd_rvalid),
               core._i(dut.m_wr_awvalid), core._i(dut.m_wr_wvalid),
               core._i(dut.m_wr_bvalid))
        if row != prev or now - last > STALL_S or cyc % 50 == 0:
            dut._log.info(
                f"[{cyc:5d}] st={st:2d} arv={row[1]} rv={row[2]} "
                f"awv={row[3]} wv={row[4]} bv={row[5]} "
                f"ar={ram.ar_count} aw={ram.aw_count} "
                f"wbeats={len(ram.wbeats)} "
                f"wall={now - t0:7.2f}s step={now - last:6.3f}s")
        prev, last = row, now
        if core._i(dut.done):
            dut._log.info(
                f"done at cycle {cyc} in {now - t0:.2f}s wall "
                f"(refuse={core._i(dut.refuse)} flags={core._i(dut.flags):#07b}"
                f" err={core._i(dut.err):#06b}); "
                f"{ram.ar_count} reads, {ram.aw_count} writes, "
                f"{len(ram.wbeats)} beats")
            break
        await RisingEdge(dut.ap_clk)
    else:
        raise AssertionError(
            f"no done in {CYCLES} cycles ({time.monotonic() - t0:.1f}s "
            f"wall); last state {prev}. A module that reaches this line "
            f"is at least still advancing time - if the target hangs "
            f"with no output at all, it is not slow, it is stopped.")
