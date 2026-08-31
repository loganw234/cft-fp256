# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""One segmented normalise shifter against the fifteen it would replace.

cft_fpfma_pipe carries a private normalise shifter per lane - S11 shifts
by whole 64-bit granules, S12 by the remainder - and there are fifteen
lanes. A shifter's cost is linear in the format width and every bank
consumes exactly one 256-bit beat, so the four banks' aggregate window
widths are 624 / 660 / 690 / 717: one 717-bit ladder can host all four.

That is a geometry argument, and cft_mulfrac is the standing reminder
that a geometry argument is not an area result. So the two questions
are asked separately. This bench answers only the first one - does the
shared ladder produce the same bits as fifteen private shifters - and
the synthesis run answers the second.

WHAT WOULD GO WRONG, and therefore what this drives:

  * a lane pulling its neighbour's bits across a slot boundary. This
    is the whole failure mode of a segmented shifter, and it is
    invisible unless adjacent lanes hold DIFFERENT data and at least
    one shifts far. Every vector here gives each lane its own pattern,
    and one test drives every lane to the maximum legal shift with
    all-ones underneath it.
  * the fine amount not travelling with the data. The coarse stage
    consumes csh when the operand arrives and the fine stage runs a
    cycle later, so a shared shifter that reads the live fsh port
    mixes two operations whenever the amounts change cycle to cycle.
    Every burst here changes both amounts on every cycle.
  * the slot pitch. Lane l sits at l*(90<<mode), not at l*NW, and
    getting that wrong shows up only at fp64 and fp128 where the two
    differ.

Mode is held constant across each burst, which is not a convenience:
prec_r cannot move while anything is in flight, so a mode change
mid-pipeline is not a case the hardware can present.

    CFT_RANDOM   random vectors per mode (default 400)
    CFT_SEED     vector seed (default 11)
"""

import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

CLK_NS = 2                  # clock period
SAMPLE_NS = CLK_NS // 2     # sample mid-cycle, after the edge has settled

SLOTS = 8
SLOTW = 90
WT = SLOTS * SLOTW          # 720

# GW = 3P + 6 per rung, and 256/width lanes.
NW = [3 * 24 + 6, 3 * 53 + 6, 3 * 113 + 6, 3 * 237 + 6]   # 78 165 345 717
LN = [8, 4, 2, 1]
MODE_NAME = ["fp32", "fp64", "fp128", "fp256"]

LATENCY = 2


def pitch(mode):
    """Bit distance between adjacent lanes of `mode`."""
    return SLOTW << mode


def live_mask(mode):
    """The bits a consumer actually reads back.

    Padding inside a slot is deliberately excluded: the shared ladder
    carries bits above NW that a private NW-wide shifter truncates
    away, and no lane reads them. Comparing them would fail on a
    difference that cannot reach a result.
    """
    m = 0
    field = (1 << NW[mode]) - 1
    for lane in range(LN[mode]):
        m |= field << (lane * pitch(mode))
    return m


def split_amount(total):
    """The pipe's own split: whole 64-bit granules, then the remainder."""
    return total >> 6, total & 63


def pack(values, width):
    v = 0
    for i, x in enumerate(values):
        v |= (x & ((1 << width) - 1)) << (i * width)
    return v


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.checks = 0

    async def burst(self, mode, vectors, note):
        """Drive `vectors` back-to-back at one mode and check every result.

        Back-to-back matters. A shifter that latches the wrong cycle's
        shift amount is correct on isolated vectors and wrong on a
        stream, and a stream is the only thing the engine ever issues.
        """
        dut = self.dut
        dut.mode.value = mode
        mask = live_mask(mode)
        pending = deque()
        dut.dir_v.value = 0

        # A vector written now is captured by the NEXT edge, and both
        # halves have two register stages, so the output settling after
        # an edge belongs to the vector written LATENCY edges earlier -
        # that is, the moment the queue reaches LATENCY entries, not one
        # past it.
        #
        # Sampling happens MID-CYCLE, not immediately after the edge.
        # Reading .value straight after RisingEdge returns the value
        # from BEFORE the edge, which skews both halves equally and so
        # hides inside a burst - and then fails on the first check after
        # a mode change, where the stale in-flight result was produced
        # by the shared ladder under the old mode while the reference
        # re-interprets the same bits under the new one. That looks
        # exactly like a shifter bug and is not one.
        for din, cshs, fshs in vectors:
            dut.din.value = din
            dut.csh_v.value = pack(cshs, 4)
            dut.fsh_v.value = pack(fshs, 6)
            pending.append((din, cshs, fshs))
            await RisingEdge(dut.clk)
            await Timer(SAMPLE_NS, units="ns")
            if len(pending) >= LATENCY:
                self._check(mode, mask, pending.popleft(), note)

        # Drain what is still in flight. Nothing new is driven, so the
        # ports hold the last vector - harmless, since the results being
        # drained were captured before it.
        while pending:
            await RisingEdge(dut.clk)
            await Timer(SAMPLE_NS, units="ns")
            self._check(mode, mask, pending.popleft(), note)

    def _check(self, mode, mask, vec, note):
        dut = self.dut
        got = int(getattr(dut, "dout").value) & mask
        want = int(getattr(dut, f"r{mode}").value) & mask
        # The bidirectional build of the same ladder, driven left: the
        # BIDIR generate must collapse to the identical function, and
        # this holds it to that at every vector of every test.
        got_b = int(getattr(dut, "dout_b").value) & mask
        if got_b != got:
            raise AssertionError(
                f"{MODE_NAME[mode]} {note}: BIDIR=1 at dir=0 diverges from "
                f"the left-only ladder\n"
                f"  left  = 0x{got:0180x}\n"
                f"  bidir = 0x{got_b:0180x}")
        if got != want:
            din, cshs, fshs = vec
            diff = got ^ want
            lane = (diff.bit_length() - 1) // pitch(mode)
            raise AssertionError(
                f"{MODE_NAME[mode]} {note}: highest differing bit is in lane {lane}\n"
                f"  shifts = {[c * 64 + f for c, f in zip(cshs, fshs)][:LN[mode]]}\n"
                f"  din    = 0x{din:0180x}\n"
                f"  shared = 0x{got:0180x}\n"
                f"  15-way = 0x{want:0180x}\n"
                f"  xor    = 0x{diff:0180x}"
            )
        self.checks += 1


def lane_word(rng, mode, lane, style):
    """One lane's operand, distinct per lane so leakage is visible."""
    w = NW[mode]
    if style == "ones":
        return (1 << w) - 1
    if style == "low":
        return 1
    if style == "high":
        return 1 << (w - 1)
    if style == "id":
        # A pattern keyed by the lane index: any bit that arrives from
        # the wrong lane names the lane it came from.
        return ((lane + 1) * 0x0101010101010101) & ((1 << w) - 1)
    return rng.getrandbits(w)


def build(rng, mode, styles, shifts):
    din = 0
    for lane in range(LN[mode]):
        din |= lane_word(rng, mode, lane, styles[lane]) << (lane * pitch(mode))
    cshs = [0] * SLOTS
    fshs = [0] * SLOTS
    for lane in range(LN[mode]):
        c, f = split_amount(shifts[lane])
        cshs[lane] = c
        fshs[lane] = f
    return din, cshs, fshs


async def start(dut):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, units="ns").start())
    dut.mode.value = 0
    dut.din.value = 0
    dut.csh_v.value = 0
    dut.fsh_v.value = 0
    for _ in range(4):
        await RisingEdge(dut.clk)


@cocotb.test()
async def every_shift_amount(dut):
    """Sweep every legal shift, at every rung, all lanes together.

    The legal range is 0..NW-1 because the pipe derives the amount as
    NW-1-msb from a leading-zero count. Nothing else can be presented,
    so nothing else is claimed.
    """
    await start(dut)
    rng = random.Random(int(os.environ.get("CFT_SEED", "11")))
    b = Bench(dut)

    for mode in range(4):
        vectors = []
        for total in range(NW[mode]):
            styles = ["random"] * LN[mode]
            shifts = [total] * LN[mode]
            vectors.append(build(rng, mode, styles, shifts))
        await b.burst(mode, vectors, "shift sweep")

    dut._log.info("every shift amount: %d comparisons", b.checks)


@cocotb.test()
async def boundary_leak(dut):
    """The failure a segmented shifter has that a private one cannot.

    All-ones in every lane and the maximum legal shift in every lane:
    if any stage lets a lane reach below its own group, the zeros that
    should fill from the bottom arrive as ones instead.
    """
    await start(dut)
    rng = random.Random(int(os.environ.get("CFT_SEED", "11")) + 1)
    b = Bench(dut)

    for mode in range(4):
        vectors = []
        for total in (NW[mode] - 1, NW[mode] - 2, 64, 63, 1):
            if total < 0:
                continue
            vectors.append(build(rng, mode, ["ones"] * LN[mode],
                                 [total] * LN[mode]))
            vectors.append(build(rng, mode, ["id"] * LN[mode],
                                 [total] * LN[mode]))
        # Staggered: each lane a different distance, which is the
        # arrangement a single shared amount would get wrong.
        for base in (0, 17, 64, 65):
            shifts = [(base + 13 * i) % NW[mode] for i in range(LN[mode])]
            vectors.append(build(rng, mode, ["ones"] * LN[mode], shifts))
            vectors.append(build(rng, mode, ["id"] * LN[mode], shifts))
        await b.burst(mode, vectors, "boundary")

    dut._log.info("boundary leak: %d comparisons", b.checks)


@cocotb.test()
async def independent_lanes(dut):
    """Random data, independent per-lane shifts, changing every cycle.

    This is the case the engine actually issues: a stream where each
    lane's normalise distance comes from its own leading-zero count and
    has nothing to do with its neighbours'.
    """
    await start(dut)
    budget = int(os.environ.get("CFT_RANDOM", "400"))
    rng = random.Random(int(os.environ.get("CFT_SEED", "11")) + 2)
    b = Bench(dut)

    styles = ["random", "ones", "low", "high", "id"]
    for mode in range(4):
        vectors = []
        for _ in range(budget):
            st = [rng.choice(styles) for _ in range(LN[mode])]
            sh = [rng.randrange(NW[mode]) for _ in range(LN[mode])]
            vectors.append(build(rng, mode, st, sh))
        await b.burst(mode, vectors, "independent")

    dut._log.info("independent lanes: %d comparisons over %d vectors",
                  b.checks, budget * 4)


@cocotb.test()
async def directions(dut):
    """The aligner contract: per-lane left OR right, neighbours free to
    disagree, boundaries zero-filling in both orientations.

    The reference shifts each lane's window right with a plain `>>`, so
    the shared ladder's right path is held to the same bits the private
    aligner would produce. The leak this exists to catch is the mirror
    of the left one: a right shift pulling the HIGHER neighbour's bits
    down across a slot boundary, which only shows when neighbours hold
    different data - `id` patterns name the offender.
    """
    await start(dut)
    rng = random.Random(int(os.environ.get("CFT_SEED", "11")) + 3)
    chk = Bench(dut)
    budget = int(os.environ.get("CFT_RANDOM", "400"))

    for mode in range(4):
        lanes = LN[mode]
        mask = live_mask(mode)
        pending = deque()
        dut.mode.value = mode

        vectors = []
        # Directed: every-lane-right at boundary-crossing amounts with
        # loud neighbours, alternating directions, then random.
        for total in (1, 63, 64, 65, NW[mode] - 1):
            vectors.append(("ones", [total] * lanes, (1 << lanes) - 1))
            vectors.append(("id",   [total] * lanes, (1 << lanes) - 1))
            vectors.append(("id",   [total] * lanes,
                            sum(1 << i for i in range(0, lanes, 2))))
        for _ in range(budget // 4):
            st = rng.choice(["random", "ones", "id", "high"])
            sh = [rng.randrange(NW[mode]) for _ in range(lanes)]
            vectors.append((st, sh, rng.getrandbits(lanes)))

        for st, shifts, dirs in vectors:
            din = 0
            for lane in range(lanes):
                din |= lane_word(rng, mode, lane, st) << (lane * pitch(mode))
            cshs = [0] * SLOTS
            fshs = [0] * SLOTS
            for lane in range(lanes):
                c, f = split_amount(shifts[lane])
                cshs[lane] = c
                fshs[lane] = f
            dut.din.value = din
            dut.csh_v.value = pack(cshs, 4)
            dut.fsh_v.value = pack(fshs, 6)
            dut.dir_v.value = dirs
            pending.append((din, shifts, dirs))
            await RisingEdge(dut.clk)
            await Timer(SAMPLE_NS, units="ns")
            if len(pending) >= LATENCY:
                _dircheck(dut, chk, mode, mask, pending.popleft())
        while pending:
            await RisingEdge(dut.clk)
            await Timer(SAMPLE_NS, units="ns")
            _dircheck(dut, chk, mode, mask, pending.popleft())

    dut._log.info("directions: %d comparisons", chk.checks)


def _dircheck(dut, chk, mode, mask, vec):
    got = int(dut.dout_b.value) & mask
    want = int(getattr(dut, f"r{mode}").value) & mask
    if got != want:
        din, shifts, dirs = vec
        diff = got ^ want
        lane = (diff.bit_length() - 1) // pitch(mode)
        raise AssertionError(
            f"{MODE_NAME[mode]} directions: highest differing bit in lane {lane}\n"
            f"  shifts = {shifts}  dirs = 0b{dirs:08b}\n"
            f"  din   = 0x{din:0180x}\n"
            f"  bidir = 0x{got:0180x}\n"
            f"  ref   = 0x{want:0180x}")
    chk.checks += 1
