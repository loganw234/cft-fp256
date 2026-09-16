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
from test_krnl_seq import D_BASE, MAGIC, gen_stream, run_prog  # noqa: E402


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


def prog_fold_scratch(fmt, slots):
    """cft-rebound's accumulate as a program: r3 starts at +0 and names
    no stream; every scratch slot is added in order; one deposit. The
    slots are what the index table fills - a lane's row of gathered
    contributions - so this is ask 1 in three instructions a slot."""
    insns = []
    for slot in range(slots):
        insns.append(seq.ldl(4, slot))
        insns.append(seq.alu(sf.OP_ADD, rd=3, ra=3, rc=4))
    insns.append(seq.deposit(3))
    insns.append(seq.halt())
    return seq.Program(fmt, insns, consts=[], max_deposits=1,
                       flags=seq.FLAG_SCRATCH_IO, n_scratch_in=slots,
                       n_scratch_out=0)


@cocotb.test()
async def indexed_program_between_reductions(dut):
    """The seam of round 2's wave 1 (docs/ROUND2.md, "What the lead
    keeps"): the engine's segmented reduction, then a program whose
    scratch block is gathered through its table, then the engine
    again, then a gathered program that crosses a lane block - on the
    same tile, the shared array handed back and forth. Every result is
    the model's; a phantom retire, a table read against the wrong
    base after a reduction, or a segment boundary left in the
    accumulator would show here and in no single-mechanism bench."""
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
    rng = random.Random(0x5EA1)

    def gathered_run(fmt, lanes, slots, pool_len, holes):
        pool = gen_stream(fmt, pool_len, rng, tame=True)
        table = [rng.randrange(pool_len) for _ in range(lanes * slots)]
        for k in holes:
            table[k] = seq.IDX_NONE
        va = gen_stream(fmt, lanes, rng, tame=True)
        vb = gen_stream(fmt, lanes, rng, tame=True)
        vc = gen_stream(fmt, lanes, rng, tame=True)
        return pool, table, va, vb, vc

    # 1. a segmented reduction on the engine
    await run_reduce(dut, axil, ram, FP64, 100, 0, seed=7001, op=OP_SUM,
                     seg=20)
    # 2. a gathered fold, one partial block at fp64 (64 lanes a block)
    pg = prog_fold_scratch(FP64, 6)
    pool, table, va, vb, vc = gathered_run(FP64, 40, 6, 50,
                                           holes=range(3, 240, 7))
    await run_prog(dut, axil, ram, pg, va, vb, vc,
                   "fp64 gathered fold after a segmented reduction",
                   scratch_in=pool, idx=(None, None, None, table), n=40)
    # 3. the engine again, a different format and a whole-array sum
    await run_reduce(dut, axil, ram, FP32, 1000, 0, seed=7002, op=OP_SUM,
                     seg=8)
    await run_reduce(dut, axil, ram, FP128, 40, 0, seed=7003, op=OP_SUM)
    # 4. a gathered fold across a lane block at fp32 (128 lanes a block):
    #    the table's second block starts at a nonzero scratch offset
    pg32 = prog_fold_scratch(FP32, 3)
    pool, table, va, vb, vc = gathered_run(FP32, 150, 3, 31,
                                           holes=range(5, 450, 11))
    await run_prog(dut, axil, ram, pg32, va, vb, vc,
                   "fp32 gathered fold across a lane block, after two "
                   "reductions", scratch_in=pool,
                   idx=(None, None, None, table), n=150)
    # 5. and the engine once more, so a phantom left by the program
    #    would meet a reduction rather than silence
    await run_reduce(dut, axil, ram, FP64, 64, 0, seed=7004, op=OP_SUM,
                     seg=16)
    dut._log.info("indexed programs between reductions: every result the "
                  "model's")


@cocotb.test()
async def indexed_and_masked_program_between_reductions(dut):
    """The seam of round 2's wave 2 (docs/ROUND2.md, "What the lead
    keeps": after P3, an indexed AND masked run against the model): a
    gathered fold whose lanes are also masked, between reductions on
    the same tile. R16 and R17 were built by two parcels that never ran
    together; what could go wrong lives in their meeting - a masked
    lane whose table entries are still fetched and wrongly deposited, a
    gathered block whose opening active mask lost the caller's bits, a
    masked lane's flag reaching the reduction after it - and in the
    shared array's hand-off, which is where 2026-09-14's hang lived.
    Every result is the model's; the masked lanes' slots stay poison;
    the all-ones mask is bit-identical to the unmasked gathered run."""
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
    rng = random.Random(0x5EA2)

    def gathered_run(fmt, lanes, slots, pool_len, holes):
        pool = gen_stream(fmt, pool_len, rng, tame=True)
        table = [rng.randrange(pool_len) for _ in range(lanes * slots)]
        for k in holes:
            table[k] = seq.IDX_NONE
        va = gen_stream(fmt, lanes, rng, tame=True)
        vb = gen_stream(fmt, lanes, rng, tame=True)
        vc = gen_stream(fmt, lanes, rng, tame=True)
        return pool, table, va, vb, vc

    # 1. a segmented reduction on the engine
    await run_reduce(dut, axil, ram, FP32, 1000, 0, seed=7101, op=OP_SUM,
                     seg=8)
    # 2. a gathered AND masked fold across a lane block at fp32 (128
    #    lanes a block): every third lane masked, one whole block's
    #    worth of the table pointing at sentinels, the mask's bits
    #    straddling the block boundary
    pg32 = prog_fold_scratch(FP32, 3)
    pool, table, va, vb, vc = gathered_run(FP32, 150, 3, 31,
                                           holes=range(5, 450, 11))
    keep = [i % 3 != 1 for i in range(150)]
    await run_prog(dut, axil, ram, pg32, va, vb, vc,
                   "fp32 gathered and masked fold across a lane block, "
                   "after a segmented reduction", scratch_in=pool,
                   idx=(None, None, None, table), n=150, mask=keep)
    # 3. the same run with every lane kept must be the unmasked
    #    gathered run, bit for bit, on the tile
    await run_prog(dut, axil, ram, pg32, va, vb, vc,
                   "fp32 the same gathered fold, all lanes kept",
                   scratch_in=pool, idx=(None, None, None, table), n=150,
                   mask=[True] * 150)
    ones_dep = ram.read(D_BASE, 150 * pg32.max_deposits * 4)
    await run_prog(dut, axil, ram, pg32, va, vb, vc,
                   "fp32 the same gathered fold, no mask",
                   scratch_in=pool, idx=(None, None, None, table), n=150)
    assert ram.read(D_BASE, 150 * pg32.max_deposits * 4) == ones_dep, (
        "an all-ones mask over a gathered run must be bit-identical to "
        "the gathered run with no mask, and both came off the tile")
    # 4. the engine again, whole-array sums at two formats
    await run_reduce(dut, axil, ram, FP128, 40, 0, seed=7102, op=OP_SUM)
    await run_reduce(dut, axil, ram, FP64, 100, 0, seed=7103, op=OP_SUM,
                     seg=20)
    # 5. a gathered and masked fold at fp64, one partial block, the
    #    masked lanes exactly the ones whose table rows are all sentinels
    #    - so a lane that would deposit +0 is instead left alone
    pg = prog_fold_scratch(FP64, 6)
    pool, table, va, vb, vc = gathered_run(FP64, 40, 6, 50,
                                           holes=range(3, 240, 7))
    keep64 = [True] * 40
    for lane in (4, 11, 30):
        for slot in range(6):
            table[lane * 6 + slot] = seq.IDX_NONE
        keep64[lane] = False
    keep64[17] = False
    await run_prog(dut, axil, ram, pg, va, vb, vc,
                   "fp64 gathered and masked fold after two reductions",
                   scratch_in=pool, idx=(None, None, None, table), n=40,
                   mask=keep64)
    # 6. and the engine once more, so a phantom or a masked lane's flag
    #    left by the program would meet a reduction rather than silence
    await run_reduce(dut, axil, ram, FP64, 64, 0, seed=7104, op=OP_SUM,
                     seg=16)
    dut._log.info("indexed and masked programs between reductions: every "
                  "result the model's, every masked slot untouched")
