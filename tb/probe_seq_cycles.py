# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
# A diagnostic probe, not a bench (`make seqcycles`, not part of `make
# sim`): cycles per block and per lane for the programs the card was
# measured with (docs/VALIDATION.md, 2026-09-14, "the sequencer is the
# wall"), through the unit bench's harness. Model RAM answers at once,
# so HBM latency is not in these numbers; what is in them is every
# cycle the state machine spends per block, per lane and per
# instruction, which is what a change to cft_seq.sv moves.
import sys
from pathlib import Path

import cocotb
from cocotb.utils import get_sim_time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import FP32, FP64, FP128, seq, softfloat as sf  # noqa: E402
from test_seq_core import Bench, CLK_NS, lanes_per_block  # noqa: E402


def programs():
    iand = seq.alu(sf.OP_IAND, 3, 0, 0)
    fma = seq.alu(sf.OP_FMA, 3, 0, 1, 3)
    yield "halt only, no deposit", [seq.halt()], 0
    yield "iand, 1 deposit", [iand, seq.deposit(3), seq.halt()], 1
    yield "iand, 4 deposits", [iand] + [seq.deposit(3)] * 4 + [seq.halt()], 4
    yield "iand x 20, 1 deposit", [iand] * 20 + [seq.deposit(3), seq.halt()], 1
    yield "fma x 20 (dependent), 1 deposit", [fma] * 20 + [seq.deposit(3), seq.halt()], 1
    yield "iand r0 only, 1 deposit", [iand, seq.deposit(3), seq.halt()], 1


@cocotb.test()
async def cycles_per_block(dut):
    b = Bench(dut)
    await b.start()
    for fmt in (FP32, FP64, FP128):
        lpb = lanes_per_block(fmt)
        blocks = 4
        n = lpb * blocks
        one = sf.one_bits(fmt)
        pool = [one] * n
        dut._log.info(f"== {fmt.name}: {n} lanes = {blocks} blocks of {lpb}")
        for label, insns, maxdep in programs():
            prog = seq.Program(fmt, insns, consts=(), max_deposits=maxdep)
            esz = fmt.width // 8
            b._stage(fmt, prog.to_bytes(), pool, pool, pool, n,
                     n * maxdep * esz, 4 * n)
            b._drive_cfg(fmt, n)
            t0 = get_sim_time("ns")
            refused, flags, err = await b._go(4_000_000, label)
            cyc = (get_sim_time("ns") - t0) / CLK_NS
            assert refused == 0 and err == 0, (label, refused, err)
            dut._log.info(f"  {label:<34} {cyc:9.0f} cycles  "
                          f"{cyc / blocks:8.1f} /block  {cyc / n:6.2f} /lane")
