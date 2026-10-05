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


# ---- revision 7, R18: what a control code costs -----------------------
#
# Twenty control codes a program, the shapes the card's probes and the
# ODE census price (docs/SEQUENCER.md R12, "What that wait costs";
# docs/VALIDATION.md, steps 0 and 1a), beside the twenty-IAND row above
# as the arithmetic reference. Every row ends in one deposit so that
# the drain is the same small constant in each. The streams are 1.0 in
# every lane, so r0 and r1 are non-zero (SETACT keeps every lane) and
# an indexed slot is the low bits of 1.0's pattern (slot 0).

def control_programs():
    iand = seq.alu(sf.OP_IAND, 3, 0, 0)
    yield ("iand x 20 (the reference)",
           [iand] * 20 + [seq.deposit(3), seq.halt()], 1)
    yield ("stl x 20, independent",
           [seq.stl(0, k) for k in range(20)]
           + [seq.deposit(0), seq.halt()], 1)
    yield ("ldl x 20, independent",
           [seq.ldl(3 + k, k) for k in range(20)]
           + [seq.deposit(22), seq.halt()], 1)
    pair = []
    for k in range(10):
        pair += [seq.stl(3, k), seq.ldl(3, k)]
    yield ("stl/ldl x 10, one register", pair + [seq.deposit(3), seq.halt()], 1)
    pair = []
    for k in range(10):
        pair += [seq.stx(0, 1), seq.ldx(3 + k, 1)]
    yield ("stx/ldx x 10", pair + [seq.deposit(12), seq.halt()], 1)
    yield ("setact x 20", [seq.setact(0)] * 20
           + [seq.deposit(0), seq.halt()], 1)
    pair = []
    for k in range(10):
        pair += [iand, seq.setact(1)]
    yield ("iand, setact (not dependent) x 10",
           pair + [seq.deposit(3), seq.halt()], 1)
    pair = []
    for k in range(10):
        pair += [seq.alu(sf.OP_IAND, 3 + k, 0, 0), seq.stl(3 + k, k)]
    yield ("iand, stl of it x 10", pair + [seq.deposit(3), seq.halt()], 1)
    pair = []
    for k in range(10):
        pair += [seq.ldl(3 + k, k), seq.alu(sf.OP_IAND, 13 + k, 3 + k, 3 + k)]
    yield ("ldl, iand of it x 10", pair + [seq.deposit(13), seq.halt()], 1)
    yield ("deposit x 16", [seq.deposit(0)] * 16 + [seq.halt()], 16)
    # Revision 8's R24: a quiet region's two brackets walk no beats and
    # cost what REPEAT does, a decode and a refetch each; a raise walks the
    # block's live beats as SETACT does, reading its word at F. Against
    # "iand x 20 (the reference)" above: the first row is ten IANDs and
    # twenty brackets, the second twenty raises.
    quiet_pair = []
    for k in range(10):
        quiet_pair += [seq.quiet(), iand, seq.endquiet()]
    yield ("quiet, iand, endquiet x 10 (R24)",
           quiet_pair + [seq.deposit(3), seq.halt()], 1)
    yield ("raise x 20 (R24)", [seq.raise_(0)] * 20
           + [seq.deposit(0), seq.halt()], 1)


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


@cocotb.test()
async def control_codes_per_block(dut):
    """R18's before- and after-side: the rows above, for the control
    codes. Four blocks at each of fp32, fp64 and fp128; the answers are
    not compared here (test_seq_core.py does that), only the cost."""
    b = Bench(dut)
    await b.start()
    for fmt in (FP32, FP64, FP128):
        lpb = lanes_per_block(fmt)
        blocks = 4
        n = lpb * blocks
        one = sf.one_bits(fmt)
        pool = [one] * n
        dut._log.info(f"== R18 {fmt.name}: {n} lanes = {blocks} blocks of {lpb}")
        for label, insns, maxdep in control_programs():
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


# ---- revision 7, R19: a beat with no active lane -----------------------
#
# The R17 rows above mask every other lane, so every beat keeps a live
# lane and no beat can ever be skipped: they are R19's before-side only
# for "all masked". These masks kill WHOLE BEATS - the low half of every
# block, all but one lane of every block, every lane - on a program
# with twenty instructions to skip (twenty IANDs and a deposit), and on
# a program of control codes (twenty stores and a deposit). What is
# printed is the cost; the answers are test_seq_core.py's.

def _mask_bits(n, lpb, pattern):
    raw = bytearray((n + 7) // 8)
    for i in range(n):
        j = i % lpb
        keep = {"dense": True,
                "every other lane": (j % 2) == 0,
                "low half of each block masked": j >= lpb // 2,
                "one lane a block": j == lpb - 1,
                "all masked": False}[pattern]
        if keep:
            raw[i >> 3] |= 1 << (i & 7)
    return bytes(raw)


@cocotb.test()
async def masked_beats_against_dense(dut):
    b = Bench(dut)
    await b.start()
    iand = seq.alu(sf.OP_IAND, 3, 0, 0)
    progs = (("iand x 20, 1 deposit",
              [iand] * 20 + [seq.deposit(3), seq.halt()]),
             ("stl x 20, 1 deposit",
              [seq.stl(0, k) for k in range(20)]
              + [seq.deposit(0), seq.halt()]))
    pats = ("dense", "every other lane", "low half of each block masked",
            "one lane a block", "all masked")
    dut._log.info("== R19: whole beats masked (four blocks)")
    for fmt in (FP32, FP64, FP128, FP256):
        lpb = lanes_per_block(fmt)
        blocks = 4
        n = lpb * blocks
        pool = [sf.one_bits(fmt)] * n
        esz = fmt.width // 8
        for plabel, insns in progs:
            prog = seq.Program(fmt, insns, consts=(), max_deposits=1)
            row = []
            for pat in pats:
                b._stage(fmt, prog.to_bytes(), pool, pool, pool, n,
                         n * esz, 4 * n)
                masked = pat != "dense"
                if masked:
                    raw = _mask_bits(n, lpb, pat)
                    pad = -len(raw) % BEAT_BYTES
                    b.ram.stage(MASK_BASE, raw + bytes([POISON]) * pad)
                b._drive_cfg(fmt, n, lane_mask=masked)
                t0 = get_sim_time("ns")
                refused, _flags, err = await b._go(8_000_000, pat)
                assert refused == 0 and err == 0, (pat, refused, err)
                row.append(((get_sim_time("ns") - t0) / CLK_NS,
                            b.ram.ar_count))
            dut._log.info(
                f"  {fmt.name:<6} {plabel:<22} " + "  ".join(
                    f"{p}: {c:6.0f} cyc {r:3d} rd"
                    for p, (c, r) in zip(pats, row)))


# ---- revision 8, R8S: what streaming costs -----------------------------
#
# Rows for a tile whose store is smaller than its programs (`make
# seqcyclesstr`: a 64-word store and a 2^16 capacity), at SeqRam read
# latencies 0, 125 and 256 - the round trip the design is sized for -
# against the cycles the same programs cost resident. A straight program
# past the store over four full blocks (the stream prefetches from the
# store's end at each block's start, hidden behind the store's words); a
# loop body past the store and longer than it, a pass at one beat and at
# sixteen (a redirect a pass, to the captured part's end, hidden or not by
# the captured words); and a captured loop over four one-beat blocks,
# whose every block restart at pc 0 is a redirect the store cannot hide -
# S8's one-beat column and "a redirect at the 64-word store". A tile that
# does not stream says so and prints nothing.
@cocotb.test()
async def streaming_costs(dut):
    from test_seq_core import (STREAMS, IMEM_D, STREAM_D, _indep,
                               _loop_prog)
    b = Bench(dut)
    await b.start()
    if not STREAMS:
        dut._log.info(f"== R8S: this build does not stream (store {IMEM_D}, "
                      f"capacity {STREAM_D}); `make seqcyclesstr` has the rows")
        return
    fmt = FP32
    one = sf.one_bits(fmt)
    dut._log.info(f"== R8S: a {IMEM_D}-word store, a {STREAM_D} capacity; "
                  f"cycles at read latencies 0, 125, 256")

    async def run(prog, n, label):
        pool = [one] * n
        esz = fmt.width // 8
        b._stage(fmt, prog.to_bytes(), pool, pool, pool, n,
                 n * prog.max_deposits * esz, 4 * n)
        b._drive_cfg(fmt, n)
        t0 = get_sim_time("ns")
        refused, flags, err = await b._go(8_000_000, label)
        assert refused == 0 and err == 0, (label, refused, err)
        return (get_sim_time("ns") - t0) / CLK_NS

    lats = (0, 125, 256)
    straight = seq.Program(fmt, _indep(200) + [seq.deposit(3), seq.halt()],
                           max_deposits=1)
    row = []
    for lat in lats:
        b.pin = lat
        row.append(await run(straight, 4 * lanes_per_block(fmt),
                             f"straight 200, latency {lat}") / 4)
    dut._log.info("  straight 200 insns, 16 beats   " +
                  "  ".join(f"{c:8.1f}" for c in row) + "   /block")
    for beats, n in ((1, 8), (16, lanes_per_block(fmt))):
        for start, body, what in ((5, 50, "resident 50 from pc 5"),
                                  (100, 200, "200 from pc 100")):
            row = []
            for lat in lats:
                b.pin = lat
                c2 = await run(_loop_prog(fmt, start, body, 2), n, what)
                c4 = await run(_loop_prog(fmt, start, body, 4), n, what)
                row.append((c4 - c2) / 2)
            dut._log.info(f"  loop {what:<22} {beats:2d} beat  " +
                          "  ".join(f"{c:8.1f}" for c in row) + "   /pass")
    row = []
    for lat in lats:
        b.pin = lat
        row.append(await run(_loop_prog(fmt, 100, 40, 2), 4 * 8,
                             "captured 40, four one-beat blocks") / 4)
    dut._log.info("  captured 40 from pc 100, 1 beat " +
                  "  ".join(f"{c:8.1f}" for c in row) + "   /block "
                  "(a block restart at pc 0 is a redirect)")
    b.pin = None
