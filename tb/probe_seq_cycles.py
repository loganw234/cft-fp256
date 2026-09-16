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

from cft_golden import FORMATS, FP32, FP64, FP128, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from test_seq_core import (  # noqa: E402
    Bench, BEAT_BYTES, CLK_NS, IA_BASE, MASK_BASE, POISON,
    lanes_per_block,
)

FP256 = FORMATS["fp256"]


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


# ---- revision 6, R16: what a gathered block costs ---------------------
#
# The dense table above is unchanged and must stay so; this is beside
# it, not in it. One program at each of the FOUR formats, run dense and
# then with an identity table on `a` - identical answers by
# construction, so the only difference in the two numbers is the
# fetch. The program reads r0 alone, so exactly one stream is loaded
# and the comparison is a gather against a load rather than against
# two loads and a gather.
#
# Model RAM answers in the cycle it is asked, so what these numbers
# hold is the STATE MACHINE's cost per element: the table beat, the
# address, the return, the pack. On the card each of those reads is an
# HBM round trip and the read side carries ONE burst at a time, so the
# card's cost per gathered element is a round trip and not this - which
# is what host/tools/gathertime.py measures on a card and what the read
# counts printed here predict.

@cocotb.test()
async def gathered_against_dense(dut):
    b = Bench(dut)
    await b.start()
    iand = seq.alu(sf.OP_IAND, 3, 0, 0)
    insns = [iand, seq.deposit(3), seq.halt()]
    dut._log.info("== R16: one stream, dense against gathered "
                  "(identity table, so the answers are identical)")
    for fmt in (FP32, FP64, FP128, FP256):
        lpb = lanes_per_block(fmt)
        blocks = 4
        n = lpb * blocks
        pool = [sf.one_bits(fmt)] * n
        prog = seq.Program(fmt, insns, consts=(), max_deposits=1)
        esz = fmt.width // 8
        out = {}
        for mask, what in ((0, "dense"), (1, "gathered")):
            b._stage(fmt, prog.to_bytes(), pool, pool, pool, n,
                     n * esz, 4 * n)
            if mask:
                b.ram.stage(IA_BASE, b"".join(
                    int(i).to_bytes(4, "little") for i in range(n)))
            b._drive_cfg(fmt, n, idx_mask=mask)
            t0 = get_sim_time("ns")
            refused, _flags, err = await b._go(8_000_000, what)
            assert refused == 0 and err == 0, (what, refused, err)
            out[what] = ((get_sim_time("ns") - t0) / CLK_NS,
                         b.ram.ar_count)
        (dc, dr), (gc, gr) = out["dense"], out["gathered"]
        dut._log.info(
            f"  {fmt.name:<6} {n:4d} lanes  dense {dc:8.0f} cyc "
            f"({dc / n:6.2f}/lane, {dr:4d} reads)   gathered {gc:8.0f} cyc "
            f"({gc / n:6.2f}/lane, {gr:4d} reads)   "
            f"x{gc / dc:5.2f} cycles, +{gr - dr:4d} reads, "
            f"{(gc - dc) / n:6.2f} extra cycles a lane")


# ---- revision 6, R17: what a lane mask costs --------------------------
#
# Two numbers, at each of the four formats, on the same program the
# table above runs: the DENSE run, and the same run with HALF THE LANES
# masked. The mask costs one single-beat read a block at block setup
# and saves whatever the masked lanes would have computed - and on this
# model RAM, which answers in the cycle it is asked, the read is four
# cycles rather than a round trip, so what is left in the difference is
# the state machine's own cost per block against the issue cost per
# lane. On the card the fetch is one HBM round trip a block (the read
# side carries one burst at a time, P1's measurement) and the saving is
# unchanged, so the card's number is this one plus a round trip a
# block.
#
# The requester's item 4 (cft-rebound/docs/HARDWARE.md) asks what idle
# lanes cost inside a program run, and this is the half of the answer
# that lives in this repository: the tile's side of it, in cycles, with
# the block setup priced separately below.

@cocotb.test()
async def masked_against_dense(dut):
    b = Bench(dut)
    await b.start()
    iand = seq.alu(sf.OP_IAND, 3, 0, 0)
    insns = [iand, seq.deposit(3), seq.halt()]
    dut._log.info("== R17: one stream, dense against half-masked "
                  "(the same program, half the lanes)")
    for fmt in (FP32, FP64, FP128, FP256):
        lpb = lanes_per_block(fmt)
        blocks = 4
        n = lpb * blocks
        pool = [sf.one_bits(fmt)] * n
        prog = seq.Program(fmt, insns, consts=(), max_deposits=1)
        esz = fmt.width // 8
        out = {}
        # ...and ALL the lanes masked, which BOUNDS the saving: if a
        # run that computes nothing at all costs what the dense run
        # costs, then masking a lane saves no issue cycle, and what the
        # mask buys is the bytes and the flags rather than the compute.
        # The bound is worth more than the half-masked number, because
        # it is the number the round's value statement rests on.
        for step, what in ((0, "dense"), (2, "half masked"),
                           (None, "all masked")):
            b._stage(fmt, prog.to_bytes(), pool, pool, pool, n,
                     n * esz, 4 * n)
            if step is not None and step:
                raw = bytearray((n + 7) // 8)
                for i in range(0, n, step):       # every `step`th lane
                    raw[i >> 3] |= 1 << (i & 7)
                pad = -len(raw) % BEAT_BYTES
                b.ram.stage(MASK_BASE,
                            bytes(raw) + bytes([POISON]) * pad)
            elif step is None:
                raw = bytearray((n + 7) // 8)     # every bit clear
                pad = -len(raw) % BEAT_BYTES
                b.ram.stage(MASK_BASE,
                            bytes(raw) + bytes([POISON]) * pad)
            b._drive_cfg(fmt, n, lane_mask=(step != 0))
            t0 = get_sim_time("ns")
            refused, _flags, err = await b._go(8_000_000, what)
            assert refused == 0 and err == 0, (what, refused, err)
            out[what] = ((get_sim_time("ns") - t0) / CLK_NS,
                         b.ram.ar_count)
        (dc, dr), (mc, mr) = out["dense"], out["half masked"]
        (zc, zr) = out["all masked"]
        dut._log.info(
            f"  {fmt.name:<6} {n:4d} lanes  dense {dc:8.0f} cyc "
            f"({dc / n:6.2f}/lane, {dr:4d} reads)   half masked "
            f"{mc:8.0f} cyc ({mc / n:6.2f}/lane, {mr:4d} reads)   "
            f"all masked {zc:8.0f} cyc ({zr:4d} reads)   "
            f"x{mc / dc:5.2f} half, x{zc / dc:5.2f} all, "
            f"{(mc - dc) / blocks:+7.1f} cycles a block")


# ---- and the block setup alone ---------------------------------------
#
# The same two runs over a program that computes NOTHING - a bare HALT,
# no deposit - so what is measured is the per-block machinery and the
# mask fetch inside it, with no issue and no drain to hide behind.
# This is the number that says what the fetch itself costs, which the
# two-percent ceiling in docs/ROUND2.md assumes is one burst.

@cocotb.test()
async def block_setup_dense_against_masked(dut):
    b = Bench(dut)
    await b.start()
    dut._log.info("== R17: block setup alone (HALT, no deposit), dense "
                  "against masked")
    for fmt in (FP32, FP64, FP128, FP256):
        lpb = lanes_per_block(fmt)
        blocks = 4
        n = lpb * blocks
        pool = [sf.one_bits(fmt)] * n
        prog = seq.Program(fmt, [seq.halt()], consts=(), max_deposits=0)
        out = {}
        for use_mask, what in ((False, "dense"), (True, "masked")):
            b._stage(fmt, prog.to_bytes(), pool, pool, pool, n, 0, 4 * n)
            if use_mask:
                raw = bytearray((n + 7) // 8)
                for i in range(0, n, 2):
                    raw[i >> 3] |= 1 << (i & 7)
                pad = -len(raw) % BEAT_BYTES
                b.ram.stage(MASK_BASE,
                            bytes(raw) + bytes([POISON]) * pad)
            b._drive_cfg(fmt, n, lane_mask=use_mask)
            t0 = get_sim_time("ns")
            refused, _flags, err = await b._go(4_000_000, what)
            assert refused == 0 and err == 0, (what, refused, err)
            out[what] = ((get_sim_time("ns") - t0) / CLK_NS,
                         b.ram.ar_count)
        (dc, dr), (mc, mr) = out["dense"], out["masked"]
        dut._log.info(
            f"  {fmt.name:<6} {n:4d} lanes in {blocks} blocks  dense "
            f"{dc:7.0f} cyc ({dc / blocks:6.1f}/block, {dr:3d} reads)   "
            f"masked {mc:7.0f} cyc ({mc / blocks:6.1f}/block, {mr:3d} "
            f"reads)   {(mc - dc) / blocks:+6.1f} cycles and "
            f"{(mr - dr) / blocks:+4.1f} reads a block")
