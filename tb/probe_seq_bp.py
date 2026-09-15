# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
# A diagnostic, not a bench (`make seqbp`, not part of `make sim`): the
# sequencer's programs through the whole kernel with busfx.stall on
# every AXI channel - READY withheld on AR/AW/W, VALID withheld on R/B
# at three duties - which is what the card does to the drains and what
# no sequencer bench applied before 2026-09-14. Written the evening the
# first image of revision 5 hung a compute unit on the card while every
# bench was green: a hang here is the card's hang reproduced; a pass
# here says the difference is elsewhere.
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
import busfx  # noqa: E402
from cft_golden import FP32, FP64, FP128, PREC_CODE, seq  # noqa: E402
from test_krnl_seq import (  # noqa: E402
    MAGIC, CAPS, gen_stream, run_prog, prog_two_deposits, prog_loop_setact,
    prog_high_registers,
)


@cocotb.test()
async def programs_under_backpressure(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 21)
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 21, mem=ram_a.mem)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 21, mem=ram_a.mem)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 21, mem=ram_a.mem)
    ram = ram_a
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    assert await axil.read_dword(MAGIC) == 0x43465430
    caps = await axil.read_dword(CAPS)

    def carried(fmt):
        return bool(caps & (1 << PREC_CODE[fmt.name]))

    rng = random.Random(777)
    for i, duty in enumerate((0.15, 0.45, 0.75)):
        busfx.stall(ram_a, ram_b, ram_c, ram_d, seed=9100 + i, duty=duty)
        dut._log.info(f"backpressure: duty {duty} on every channel")
        for fmt, ns in ((FP32, (16, 40, 136)), (FP64, (12, 68)),
                        (FP128, (6, 34))):
            if not carried(fmt):
                continue
            for n in ns:
                p = prog_two_deposits(fmt)
                await run_prog(dut, axil, ram, p,
                               gen_stream(fmt, n, rng), gen_stream(fmt, n, rng),
                               gen_stream(fmt, n, rng),
                               f"{fmt.name} two deposits n={n} duty={duty}",
                               tries=20000)
        p = prog_loop_setact(FP32)
        await run_prog(dut, axil, ram, p, gen_stream(FP32, 40, rng),
                       gen_stream(FP32, 40, rng), gen_stream(FP32, 40, rng),
                       f"fp32 loop+setact duty={duty}", tries=20000)
        if carried(FP64):
            p = prog_high_registers(FP64)
            await run_prog(dut, axil, ram, p, gen_stream(FP64, 20, rng),
                           gen_stream(FP64, 20, rng), gen_stream(FP64, 20, rng),
                           f"fp64 high registers duty={duty}", tries=20000)
        # a halt-only program: no stream loads, the count drain alone
        p = seq.Program(FP32, [seq.halt()], max_deposits=0)
        await run_prog(dut, axil, ram, p, gen_stream(FP32, 200, rng),
                       gen_stream(FP32, 200, rng), gen_stream(FP32, 200, rng),
                       f"fp32 halt only n=200 duty={duty}", tries=20000)
    busfx.unstall(ram_a, ram_b, ram_c, ram_d)
    dut._log.info("every program completed and scored under back-pressure")
