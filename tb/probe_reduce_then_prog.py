# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
# A diagnostic, not a bench: an engine run - a reduction, then an
# elementwise run - and then a sequencer program, through one cft_krnl,
# the way device-test drives the card. The lane array is shared between
# the engine and the sequencer, and since revision 5's overlap the
# sequencer's retire path runs in every state: this is the sequence in
# which the first revision-5 image hung a compute unit on 2026-09-14.
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cocotbext.axi import (  # noqa: E402
    AxiLiteBus, AxiLiteMaster, AxiRamRead, AxiRamWrite,
    AxiReadBus, AxiWriteBus,
)
from cft_golden import FP32, FP64, FP128, seq, softfloat as sf  # noqa: E402
from cft_golden.reduce import OP_SUM  # noqa: E402
from test_krnl_reduce import run_reduce  # noqa: E402
from test_krnl_seq import MAGIC, gen_stream, run_prog  # noqa: E402


@cocotb.test()
async def reduce_then_program(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 21)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 21, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 21, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 21, mem=ram_a.mem)
    ram = ram_a
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    assert await axil.read_dword(MAGIC) == 0x43465430

    rng = random.Random(4321)
    konst = (FP128.bias << FP128.man_w) | (1 << (FP128.man_w - 1))
    prog = seq.Program(FP128, [seq.alu(sf.OP_FMA, 4, 0, 1, 2), seq.deposit(4),
                               seq.halt()], consts=[konst], max_deposits=1)
    for efmt, en in ((FP128, 8), (FP128, 40), (FP128, 1000), (FP64, 40),
                     (FP32, 1000)):
        await run_reduce(dut, axil, ram, efmt, en, 0, seed=100 + en, op=OP_SUM)
        for pn in (8, 16, 34):
            await run_prog(dut, axil, ram, prog, gen_stream(FP128, pn, rng),
                           gen_stream(FP128, pn, rng), gen_stream(FP128, pn, rng),
                           f"fp128 fma+deposit n={pn} after {efmt.name} sum n={en}",
                           tries=20000)
    dut._log.info("every program after a reduction completed and scored")
