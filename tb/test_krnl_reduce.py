# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""CFT_SUM through the whole kernel, against the golden model's tree.

cft_reduce_acc is already proven on its own. This is the integration:
the CSR carrying opcode 24, the engine serialising beats into the
accumulator instead of computing elementwise, lane 0 of the active bank
doubling as the accumulator's adder, and the writer emitting ONE beat
instead of n.

The sizes matter more than the count of them. A reduction's tree shape
depends on the element count, and the engine has a second size
dependence on top of it: the last beat is usually partial, and the
serializer must stop at the real element count rather than running to
the end of the beat, because the beat padding is zeros and adding +0.0
is not the identity. So the sizes here straddle beat boundaries in both
directions at every precision - n, n-1 and n+1 around multiples of 8, 4,
2 and 1 elements per beat.

CFT_DOT is deliberately not tested here because it is deliberately not
built: the contract makes dot(a,b) == sum(mul(a,b)) exact, so the host
issues a MUL then a SUM. That composition is checked in the model and
in libcft; what the hardware owes is SUM.
"""

import os
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

from cft_golden import (  # noqa: E402
    FP32, FP64, FP128, FP256, PREC_CODE, RND_NAMES, vectors,
)
from cft_golden.reduce import (  # noqa: E402
    OP_SUM, OP_MAXALL, fsum, fmaxall, freduce_seg,
)

CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50
CAPS2, SEGREG = 0x6C, 0x80          # SEG in the low word, NRES in the high
A_BASE, B_BASE, C_BASE, D_BASE = 0x00000, 0x40000, 0x80000, 0xC0000

FORMATS = [FP32, FP64, FP128, FP256]


async def write64(axil, addr, val):
    await axil.write_dword(addr, val & 0xFFFFFFFF)
    await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)


async def run_sum(dut, axil, ram, fmt, n, rnd, seed, specials=True):
    """One CFT_SUM run, scored against the model's tree.

    `specials` draws 30% of the operands from the interesting pool -
    infinities, NaNs, subnormals, zeros - which is what a reduction
    over a handful of elements should see, and is the default so every
    caller written before this argument existed is unchanged.

    IT MUST BE OFF FOR A LONG RUN, and the reason is the third rule in
    docs/VERIFICATION.md. One NaN anywhere in a sum makes the sum a
    NaN, and over hundreds of elements a 30% special rate makes that a
    certainty - so `got == want` holds no matter WHICH elements were
    summed, which elements were dropped, or how many times each was
    counted. A long run drawn that way is a check that cannot fail.
    Found exactly that way: a deliberately broken FIFO reservation
    dropped 136 of 700 beats and the assertion here never moved
    (docs/VALIDATION.md, 2026-09-09).
    """
    rng = random.Random(seed)
    pool = vectors.interesting_operands(fmt)
    ebytes = fmt.width // 8

    vals = []
    for _ in range(n):
        if specials and rng.random() < 0.30:
            vals.append(pool[rng.randrange(len(pool))])
        else:
            sign = rng.getrandbits(1)
            e = fmt.bias + rng.randint(-20, 20)
            m = rng.getrandbits(fmt.man_w)
            vals.append((sign << (fmt.width - 1)) | (e << fmt.man_w) | m)

    ram.write(A_BASE, b"".join(v.to_bytes(ebytes, "little") for v in vals))
    # b and c are unread by a sum, but the engine streams all three and
    # the FIFOs share a read enable, so they have to be real memory.
    ram.write(B_BASE, b"\x00" * max(n * ebytes, 32))
    ram.write(C_BASE, b"\x00" * max(n * ebytes, 32))
    ram.write(D_BASE, b"\xAA" * 32)

    await axil.write_dword(MODE, (rnd << 12) | (PREC_CODE[fmt.name] << 8)
                           | OP_SUM)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)

    for _ in range(8000):
        await ClockCycles(dut.ap_clk, 20)
        status = await axil.read_dword(CTRL)
        if status & 0x2:
            break
    else:
        raise AssertionError(
            f"{fmt.name} sum n={n}: kernel never finished - the reduction "
            f"never reached its flush, or the writer never emitted its beat")

    got = int.from_bytes(ram.read(D_BASE, ebytes), "little")
    got_f = await axil.read_dword(FLAGS)
    st = await axil.read_dword(STATUS)
    assert st == 0, f"{fmt.name} n={n}: STATUS {st:#x} - a bus fault"

    want, want_f = fsum(fmt, vals, rnd)
    assert got == want, (
        f"{fmt.name} sum n={n} {RND_NAMES[rnd]}: got {got:#x} want {want:#x}\n"
        f"  first inputs {[hex(v) for v in vals[:6]]}")
    assert got_f == want_f, (
        f"{fmt.name} sum n={n} {RND_NAMES[rnd]}: flags {got_f:#07b} "
        f"want {want_f:#07b}")
    return n


@cocotb.test()
async def sum_end_to_end(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    assert await axil.read_dword(VERSION) == 0x00000A00, \
        "reductions arrived at v0.5.0; the map grew again at v0.6.0, " \
        "once more at v0.7.0 when BANK_PTR was appended, at v0.8.0 " \
        "when CAPS2 and the two scratch pointers were, and at v0.9.0 " \
        "when SEG/NRES were"
    caps = await axil.read_dword(CAPS)
    assert (caps >> 8) & (1 << 5), \
        "CAPS must advertise the reduction group once SUM is built"

    total = 0
    # Sizes straddling the beat boundary at each precision, so the
    # partial-tail path is exercised rather than assumed.
    per_fmt = {
        FP32:  [1, 2, 7, 8, 9, 15, 16, 17, 31, 33],
        FP64:  [1, 3, 4, 5, 7, 8, 9, 16, 17],
        FP128: [1, 2, 3, 4, 5, 8, 9],
        FP256: [1, 2, 3, 5, 8, 13],
    }
    for fmt in FORMATS:
        for n in per_fmt[fmt]:
            total += await run_sum(dut, axil, ram_a, fmt, n, 0, seed=100 + n)
        dut._log.info(f"{fmt.name}: sums over {len(per_fmt[fmt])} sizes "
                      f"straddling the beat boundary, bit-exact")

    # ---- and one long enough to SATURATE the operand FIFOs -----------
    #
    # Every size above is a beat-boundary case, and none of them is
    # more than 33 elements. That leaves one thing in the read path
    # untested by anything in this repository: the FIFO reservation
    # under load, which only binds when a stream FIFO is actually FULL.
    #
    # A reduction is the cheapest way to get there, and it is the only
    # cheap way. Elementwise consumes a beat about as fast as a master
    # can deliver one, so the FIFO gains a tenth of a beat a cycle and
    # a run would need four thousand beats to fill 512 of them. The
    # reduction's serialiser consumes one beat per ~11 cycles while the
    # reads still arrive at one a cycle, so the FIFOs fill within a few
    # hundred and STAY full for the rest of the run - which is the
    # regime where `burst_room` decides whether an AR may go out, and
    # where an off-by-one in it overwrites operands that have not been
    # read yet.
    #
    # ORDINARY OPERANDS ONLY, and that is load-bearing rather than
    # tidy: one NaN makes the whole sum a NaN, and at the 30% special
    # rate every other run here uses, a 700-beat sum is a NaN with
    # certainty - which would compare equal however many beats the
    # engine had lost. See run_sum's docstring.
    #
    # 5,600 fp32 elements is 700 beats: saturated after roughly the
    # first 550 and reserving against a full FIFO for the rest. The
    # answer is one number scored against the model, so the failure is
    # a wrong SUM rather than a hang. This is the run that catches the
    # deliberately over-promising reservation of docs/VALIDATION.md's
    # 2026-09-09 negative control; without it the fault passed every
    # bench in this repository.
    total += await run_sum(dut, axil, ram_a, FP32, 5600, 0, seed=7700,
                           specials=False)
    dut._log.info("fp32: a 700-beat sum, operand FIFOs saturated for most "
                  "of it, bit-exact")

    dut._log.info(f"reduction end-to-end: {total} elements summed, exact")


@cocotb.test()
async def sum_every_rounding_attribute(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    total = 0
    for rnd in range(5):
        for fmt, n in ((FP32, 21), (FP64, 11), (FP128, 7), (FP256, 5)):
            total += await run_sum(dut, axil, ram_a, fmt, n, rnd,
                                   seed=900 + rnd)
    dut._log.info(f"all five rounding attributes x four precisions: "
                  f"{total} elements, exact")


@cocotb.test()
async def elementwise_still_works_after_a_reduction(dut):
    """A reduction must not leave the engine in a state that breaks the
    next run. The accumulator, the serializer and the one-shot result
    push all latch, and all of them are cleared at ap_start rather than
    at reset - so a sum followed by an fma is the case that catches a
    clear that was never wired."""
    from test_krnl import run_op  # noqa: E402
    from cft_golden import OP_FMA, OP_ADD  # noqa: E402

    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    await run_sum(dut, axil, ram_a, FP32, 13, 0, seed=7)
    await run_op(dut, axil, ram_a, FP32, OP_FMA, 24, seed=8)
    await run_sum(dut, axil, ram_a, FP64, 9, 0, seed=9)
    await run_op(dut, axil, ram_a, FP32, OP_ADD, 16, seed=10)
    await run_sum(dut, axil, ram_a, FP256, 5, 0, seed=11)
    dut._log.info("reduction and elementwise runs interleave cleanly")


# ======================================================================
# segments and the streaming maximum (ask 7, 2026-09-14, CAPS2[8])
# ======================================================================

async def run_reduce(dut, axil, ram, fmt, n, rnd, seed, op=OP_SUM, seg=0,
                     specials=False):
    """One reduction run, opcode 24 or 31, whole (seg=0) or segmented,
    scored slice by slice against freduce_seg. Ordinary operands by
    default for the reason run_sum's docstring gives; `specials` is for
    the flags run, where a NaN segment is the point."""
    rng = random.Random(seed)
    pool = vectors.interesting_operands(fmt)
    ebytes = fmt.width // 8
    vals = []
    for _ in range(n):
        if specials and rng.random() < 0.30:
            vals.append(pool[rng.randrange(len(pool))])
        else:
            sign = rng.getrandbits(1)
            e = fmt.bias + rng.randint(-20, 20)
            m = rng.getrandbits(fmt.man_w)
            vals.append((sign << (fmt.width - 1)) | (e << fmt.man_w) | m)
    nres = n // seg if seg else 1
    ram.write(A_BASE, b"".join(v.to_bytes(ebytes, "little") for v in vals))
    ram.write(B_BASE, b"\x00" * max(n * ebytes, 32))
    ram.write(C_BASE, b"\x00" * max(n * ebytes, 32))
    # poison past the results too: a writer that wrote a beat too many
    # would show there
    ram.write(D_BASE, b"\xAA" * (((nres * ebytes + 31) // 32) * 32 + 64))

    await axil.write_dword(MODE, (rnd << 12) | (PREC_CODE[fmt.name] << 8) | op)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await write64(axil, SEGREG, (nres << 32) | seg if seg else 0)
    await axil.write_dword(CTRL, 1)
    for _ in range(20000):
        await ClockCycles(dut.ap_clk, 20)
        if (await axil.read_dword(CTRL)) & 0x2:
            break
    else:
        raise AssertionError(
            f"{fmt.name} op {op} n={n} seg={seg}: kernel never finished")
    st = await axil.read_dword(STATUS)
    assert st == 0, f"{fmt.name} op {op} n={n} seg={seg}: STATUS {st:#x}"
    got_f = await axil.read_dword(FLAGS)
    got = [int.from_bytes(ram.read(D_BASE + s * ebytes, ebytes), "little")
           for s in range(nres)]
    # nothing past the last result beat was touched
    tail = ((nres * ebytes + 31) // 32) * 32
    assert ram.read(D_BASE + tail, 64) == b"\xAA" * 64, (
        f"{fmt.name} op {op} n={n} seg={seg}: the writer went past the "
        f"result beats")
    want, want_f = freduce_seg(op, fmt, vals, seg if seg else n, rnd)
    for s, (g, w) in enumerate(zip(got, want)):
        assert g == w, (
            f"{fmt.name} op {op} n={n} seg={seg} {RND_NAMES[rnd]}: result "
            f"{s} got {g:#x} want {w:#x}")
    assert got_f == want_f, (
        f"{fmt.name} op {op} n={n} seg={seg}: flags {got_f:#07b} want "
        f"{want_f:#07b}")
    return n


async def _bring_up(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
               dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
               size=2 ** 20, mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                size=2 ** 20, mem=ram_a.mem)
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    caps2 = await axil.read_dword(CAPS2)
    assert caps2 & (1 << 8), "CAPS2[8] must announce SEG/NRES and maxall"
    return axil, ram_a


@cocotb.test()
async def sum_segmented(dut):
    """d[s] is the tree over slice s: segment lengths that straddle the
    beat at every precision, result counts that straddle a result beat,
    and a segment that is the whole array, which must equal the single
    result the unsegmented run writes."""
    axil, ram = await _bring_up(dut)
    per_fmt = {
        FP32:  [(1, 9), (2, 5), (3, 5), (7, 3), (8, 3), (9, 2), (16, 2),
                (5, 20), (33, 2)],
        FP64:  [(1, 5), (2, 3), (3, 4), (4, 3), (5, 2), (8, 2), (9, 2), (17, 3)],
        FP128: [(1, 3), (2, 3), (3, 3), (4, 2), (5, 2), (9, 2)],
        FP256: [(1, 3), (2, 2), (3, 2), (5, 2), (8, 2)],
    }
    total = 0
    for fmt in FORMATS:
        for seg, k in per_fmt[fmt]:
            total += await run_reduce(dut, axil, ram, fmt, seg * k, 0,
                                      seed=300 + seg * 31 + k, seg=seg)
        # one segment that is the whole array, beside the unsegmented run
        n = per_fmt[fmt][-1][0] * per_fmt[fmt][-1][1]
        await run_reduce(dut, axil, ram, fmt, n, 0, seed=777, seg=n)
        await run_reduce(dut, axil, ram, fmt, n, 0, seed=777, seg=0)
        dut._log.info(f"{fmt.name}: segmented sums over "
                      f"{len(per_fmt[fmt])} shapes, bit-exact")
    # rounding attributes ride along
    for rnd in (1, 2, 3, 4):
        total += await run_reduce(dut, axil, ram, FP32, 24, rnd,
                                  seed=900 + rnd, seg=6)
    dut._log.info(f"segmented reductions: {total} elements, exact")


@cocotb.test()
async def maxall_on_the_tile(dut):
    """Opcode 31 as a reduction: the accumulator folding with the
    elementwise maximum, whole and segmented, against fmaxall - the
    same bits as the host's halving, as 754 maximum's associativity
    says they must be."""
    axil, ram = await _bring_up(dut)
    per_fmt = {
        FP32:  [1, 2, 7, 8, 9, 17, 33, 100],
        FP64:  [1, 3, 4, 5, 9, 17],
        FP128: [1, 2, 3, 5, 9],
        FP256: [1, 2, 3, 5],
    }
    for fmt in FORMATS:
        for n in per_fmt[fmt]:
            await run_reduce(dut, axil, ram, fmt, n, 0, seed=500 + n,
                             op=OP_MAXALL)
        await run_reduce(dut, axil, ram, fmt, 24, 0, seed=600, op=OP_MAXALL,
                         seg=4)
        await run_reduce(dut, axil, ram, fmt, 30, 0, seed=601, op=OP_MAXALL,
                         seg=3)
        dut._log.info(f"{fmt.name}: streaming maxall, whole and segmented, "
                      f"bit-exact")


# ======================================================================
# the beat-wide tree (2026-09-15)
# ======================================================================
#
# The tree reduces a whole beat in the lanes a reduction leaves idle
# and hands the accumulator one partial at level log2(epb), instead of
# handing it epb elements one at a time. The PAIRING is unchanged and
# every assertion above is the proof of that - they pass or they do
# not.
#
# What they cannot show is that the tree ran at all. A build that
# quietly fell back to the serializer at every size returns exactly the
# same bits, so the tree's own beat counter is read here and held to a
# number DERIVED from n, seg and the format. It must be nonzero where
# the sizes allow the tree and zero where they do not, and both halves
# are cases below.

def wide_beats_expected(fmt, n, seg):
    """Beats the tree may take, from the shape alone.

    A beat goes through the tree when it is FULL and its elements are
    one aligned group of the segment - which is exactly "seg is a
    multiple of epb", the whole array (seg = 0) included. Only the last
    beat of a run can be short. fp256 is one element a beat and has no
    tree.
    """
    # A tile built without the tree (EN_WIDE=0, `make reducenowide`)
    # takes no beat through it anywhere; the environment says which
    # build this is, the way CFT_RD_LATENCY says the memory's latency.
    if os.environ.get("CFT_NO_WIDE") == "1":
        return 0
    epb = 256 // fmt.width
    if epb == 1:
        return 0
    if seg and (seg % epb) != 0:
        return 0
    return n // epb


def wide_beats_seen(dut):
    return int(dut.u_engine.wide_beats.value)


@cocotb.test()
async def the_wide_path_is_taken_exactly_where_the_sizes_allow(dut):
    """Bits against the model AND the tree's beat count against the
    shape, at every format, across the seams: a segment boundary inside
    a beat, a segment one element short of a beat, a whole-array
    reduction whose n is one more than a multiple of epb."""
    axil, ram = await _bring_up(dut)
    total = 0
    zero_seen = 0
    wide_seen = 0
    for fmt in FORMATS:
        epb = 256 // fmt.width
        shapes = [
            # whole array, exactly beats
            (4 * epb, 0),
            # whole array, one element PAST a beat: every full beat
            # goes wide and a one-element tail goes serial, which is
            # the seam between the two paths
            (4 * epb + 1, 0),
            # whole array, one element short: the last beat is partial
            (4 * epb - 1, 0),
            # segments that are whole beats
            (8 * epb, epb),
            (8 * epb, 2 * epb),
            (4 * epb, 4 * epb),
            # a segment boundary INSIDE a beat: the tree must stand
            # down entirely
            (5 * 7, 7),
            (6 * 3, 3),
            # a segment one element short of a beat
            (6 * (epb - 1), epb - 1) if epb > 1 else (6, 1),
            # a segment one element past a beat
            (5 * (epb + 1), epb + 1),
        ]
        for n, seg in shapes:
            total += await run_reduce(dut, axil, ram, fmt, n, 0,
                                      seed=1300 + n * 7 + seg, seg=seg)
            got = wide_beats_seen(dut)
            want = wide_beats_expected(fmt, n, seg)
            assert got == want, (
                f"{fmt.name} n={n} seg={seg}: the tree took {got} beats, "
                f"the shape allows {want} - a fallback that still gives "
                f"the right bits is exactly what this counter is for")
            if want:
                wide_seen += 1
            else:
                zero_seen += 1
    # Both halves of the control must actually have happened - except
    # on the tree-less build, where every shape must have read zero.
    if os.environ.get("CFT_NO_WIDE") == "1":
        assert wide_seen == 0, (
            f"EN_WIDE=0 and {wide_seen} shapes still counted a wide beat")
    else:
        assert wide_seen > 0 and zero_seen > 0, (
            f"the sizes above must cover both: {wide_seen} shapes took the "
            f"tree and {zero_seen} refused it")
    dut._log.info(f"the wide path: {wide_seen} shapes took it and "
                  f"{zero_seen} correctly did not, {total} elements exact")


@cocotb.test()
async def the_wide_path_at_every_attribute_and_opcode(dut):
    """Five rounding attributes x four formats x sum and maxall, on
    shapes the tree takes, with the count asserted each time. The tree
    is epb-1 adds in the lanes beside the accumulator's, so every one
    of them has to round the way the run asks."""
    axil, ram = await _bring_up(dut)
    total = 0
    for rnd in range(5):
        for fmt in FORMATS:
            epb = 256 // fmt.width
            for op in (OP_SUM, OP_MAXALL):
                for n, seg in ((6 * epb, 0), (6 * epb, 2 * epb),
                               (6 * epb + 1, 0)):
                    total += await run_reduce(
                        dut, axil, ram, fmt, n, rnd,
                        seed=2100 + rnd * 17 + n + seg, seg=seg, op=op,
                        specials=(rnd == 0))
                    got = wide_beats_seen(dut)
                    want = wide_beats_expected(fmt, n, seg)
                    assert got == want, (
                        f"{fmt.name} op {op} n={n} seg={seg} rnd={rnd}: "
                        f"tree took {got} beats, shape allows {want}")
    dut._log.info(f"the wide path at five attributes x four formats x "
                  f"two opcodes: {total} elements, exact")


@cocotb.test()
async def the_wide_path_under_load(dut):
    """Long enough to saturate the operand FIFOs and the tree's own
    credit, with ORDINARY operands for the reason run_sum's docstring
    gives: one NaN would make every wrong answer compare equal. This is
    the run where the tree is admitting a beat a cycle, the credit
    counter is the throttle, and the partial queue is never empty."""
    axil, ram = await _bring_up(dut)
    for fmt, n, seg in ((FP32, 5600, 0), (FP32, 5600, 32),
                        (FP64, 2800, 0), (FP128, 1400, 0),
                        (FP64, 2800, 8)):
        await run_reduce(dut, axil, ram, fmt, n, 0, seed=8800 + n + seg,
                         seg=seg)
        got = wide_beats_seen(dut)
        want = wide_beats_expected(fmt, n, seg)
        assert got == want, (
            f"{fmt.name} n={n} seg={seg}: tree took {got}, want {want}")
    dut._log.info("the wide path under load: FIFOs saturated, bit-exact")


async def run_underflowing_elementwise(dut, axil, ram, fmt, n):
    """An elementwise FMA whose every lane underflows to zero.

    Operands DERIVED from the format rather than typed: exponent field
    1 is the smallest normal, and its square is far below the smallest
    subnormal at every width, so the product flushes to zero with
    UNDERFLOW and INEXACT. Returns the run's FLAGS.
    """
    from cft_golden import OP_FMA  # noqa: E402
    ebytes = fmt.width // 8
    tiny = (1 << fmt.man_w).to_bytes(ebytes, "little")
    ram.write(A_BASE, tiny * n)
    ram.write(B_BASE, tiny * n)
    ram.write(C_BASE, b"\x00" * (n * ebytes))
    ram.write(D_BASE, b"\x00" * (n * ebytes + 32))
    await axil.write_dword(MODE, (PREC_CODE[fmt.name] << 8) | OP_FMA)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await write64(axil, SEGREG, 0)
    await axil.write_dword(CTRL, 1)
    for _ in range(20000):
        await ClockCycles(dut.ap_clk, 20)
        if (await axil.read_dword(CTRL)) & 0x2:
            break
    else:
        raise AssertionError(f"{fmt.name} elementwise n={n}: never finished")
    assert await axil.read_dword(STATUS) == 0
    return await axil.read_dword(FLAGS)


@cocotb.test()
async def a_reductions_flags_do_not_depend_on_the_run_before_it(dut):
    """THE smallest shape that catches a flag path with no delay line.

    Two runs, no sequencer, and the second one EXACT: an elementwise
    FMA whose every lane underflows, then a sum of 1.0 with itself a
    thousand times. Every partial of the counter's tree over 1.0s is a
    whole number well below the format's exact-integer limit, so the
    model raises nothing and ANY bit in the reduction's FLAGS came from
    somewhere that is not this run.

    At P4's first tip that bit was the previous run's UNDERFLOW, still
    coming out of lane 4 of the shared array for the first LATENCY
    accepted edges of the reduction, with the BITS identical either way
    (V4's minimal reproduction, 2026-09-15). Only FLAGS holds this, and
    only against a preceding run that raised something - which is why
    the first run's flags are asserted too: without them the case tests
    nothing and would pass for the wrong reason.

    Determinism, not cosmetics: the same reduction over the same
    operands must not answer differently for having been run second.
    """
    axil, ram = await _bring_up(dut)
    for fmt, en, rn in ((FP32, 4096, 1000), (FP64, 2048, 1000),
                        (FP128, 1024, 500), (FP256, 512, 250)):
        ef = await run_underflowing_elementwise(dut, axil, ram, fmt, en)
        assert ef != 0, (
            f"{fmt.name}: the elementwise run raised nothing, so the "
            f"reduction after it cannot inherit anything and this case "
            f"is testing the wrong thing")
        one = fmt.bias << fmt.man_w          # 1.0, derived not typed
        want, want_f = fsum(fmt, [one] * rn, 0)
        assert want_f == 0, (
            f"{fmt.name}: {rn} copies of 1.0 must sum exactly; the model "
            f"says {want_f:#07b}, so pick a smaller count")
        ebytes = fmt.width // 8
        ram.write(A_BASE, one.to_bytes(ebytes, "little") * rn)
        ram.write(B_BASE, b"\x00" * max(rn * ebytes, 32))
        ram.write(C_BASE, b"\x00" * max(rn * ebytes, 32))
        ram.write(D_BASE, b"\xAA" * 64)
        await axil.write_dword(MODE, (PREC_CODE[fmt.name] << 8) | OP_SUM)
        await write64(axil, NREG, rn)
        await write64(axil, APTR, A_BASE)
        await write64(axil, BPTR, B_BASE)
        await write64(axil, CPTR, C_BASE)
        await write64(axil, DPTR, D_BASE)
        await write64(axil, SEGREG, 0)
        await axil.write_dword(CTRL, 1)
        for _ in range(20000):
            await ClockCycles(dut.ap_clk, 20)
            if (await axil.read_dword(CTRL)) & 0x2:
                break
        else:
            raise AssertionError(f"{fmt.name} sum n={rn}: never finished")
        got = int.from_bytes(ram.read(D_BASE, ebytes), "little")
        got_f = await axil.read_dword(FLAGS)
        assert await axil.read_dword(STATUS) == 0
        assert got == want, (
            f"{fmt.name} sum of {rn} ones: got {got:#x} want {want:#x}")
        assert got_f == want_f, (
            f"{fmt.name} sum of {rn} ones, straight after an elementwise "
            f"run whose FLAGS were {ef:#07b}: FLAGS {got_f:#07b} want "
            f"{want_f:#07b} - an exact reduction inherited the previous "
            f"run's flags from the shared array")
        # and the tree really did run, where the shape allows it
        assert wide_beats_seen(dut) == wide_beats_expected(fmt, rn, 0)
    dut._log.info("an exact reduction after a flag-raising elementwise run: "
                  "FLAGS are its own at every format")


@cocotb.test()
async def a_reduction_straight_after_a_sequencer_program(dut):
    """FLAGS after a run of a DIFFERENT KIND on the shared array.

    Every other case in this file runs reductions back to back, and
    between two of them the tree's lanes hold +0 - so nothing is left
    in the array to leak and a flag path that reads those lanes
    unqualified looks correct. It takes a run of another kind
    immediately before the reduction to put something there, and on
    this tile that means a SEQUENCER PROGRAM: cft_seq and the engine
    share one cft_lanes, and `lane_flags` is not gated on out_valid, so
    for the first LATENCY accepted edges of a run the per-lane flags
    are still the program's.

    That is a real defect this bench did not hold: the beat-wide tree's
    first flag collection ORed lanes 1.. at every accepted edge, and an
    fp32 sum after an fp128 program reported the PROGRAM's UNDERFLOW -
    `flags 0b11000 want 0b10000`, bits correct
    (tb/probe_reduce_then_prog.py, found by V4, 2026-09-15). The probe
    is a diagnostic and is not in SIM_BENCHES; this is the same shape
    where `make sim` will see it.

    run_reduce scores FLAGS against the model on every run, so the
    assertion is already there - what this case adds is the sequence.
    """
    from cft_golden import seq, softfloat as sf          # noqa: E402
    from test_krnl_seq import gen_stream, run_prog       # noqa: E402

    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    # 2**21, not the 2**20 every other case here uses: the sequencer's
    # program image lives at 0x180000 (test_krnl_seq's PROG_BASE).
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
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    assert await axil.read_dword(MAGIC) == 0x43465430

    rng = random.Random(9101)
    # The probe's program: fp128 fma against a constant, one deposit.
    # fp128 because the leak is loudest across a precision change - the
    # fp32 ladder that the reduction then selects was idle throughout.
    konst = (FP128.bias << FP128.man_w) | (1 << (FP128.man_w - 1))
    prog = seq.Program(FP128, [seq.alu(sf.OP_FMA, 4, 0, 1, 2), seq.deposit(4),
                               seq.halt()], consts=[konst], max_deposits=1)
    total = 0
    for pn in (8, 34):
        await run_prog(dut, axil, ram_a, prog,
                       gen_stream(FP128, pn, rng), gen_stream(FP128, pn, rng),
                       gen_stream(FP128, pn, rng),
                       f"fp128 fma+deposit n={pn}, before a reduction",
                       tries=20000)
        # Every format and both eligibilities, because each has its own
        # lane map and its own set of levels; fp32 n=1000 whole is the
        # shape the probe failed on.
        for fmt, n, seg in ((FP32, 1000, 0), (FP32, 512, 64),
                            (FP64, 500, 0), (FP64, 480, 16),
                            (FP128, 250, 0), (FP256, 40, 0)):
            total += await run_reduce(dut, axil, ram_a, fmt, n, 0,
                                      seed=9200 + n + seg, seg=seg)
            got = wide_beats_seen(dut)
            want = wide_beats_expected(fmt, n, seg)
            assert got == want, (
                f"{fmt.name} n={n} seg={seg} after a program: tree took "
                f"{got} beats, shape allows {want}")
    dut._log.info(f"a reduction straight after a sequencer program: FLAGS "
                  f"are the reduction's own at every format, "
                  f"{total} elements exact")


@cocotb.test()
async def segmented_flags_are_the_or_over_segments(dut):
    """Specials in: a NaN segment beside a clean one, invalid from a
    signalling NaN in one slice only, overflow in another - the run's
    FLAGS is the OR, each result its own slice's."""
    axil, ram = await _bring_up(dut)
    for fmt in (FP32, FP64):
        for seed in (41, 42, 43):
            await run_reduce(dut, axil, ram, fmt, 40, 0, seed=seed, seg=5,
                             specials=True)
            await run_reduce(dut, axil, ram, fmt, 40, 0, seed=seed, seg=8,
                             op=OP_MAXALL, specials=True)
    dut._log.info("segmented flags: the OR over segments, results per slice")
