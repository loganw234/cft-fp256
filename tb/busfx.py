# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Hostile bus behaviour for the kernel benches.

Every bench in this directory attaches a stock cocotbext-axi RAM, and a
stock RAM is the most cooperative slave that can exist: it answers in
zero cycles, never withholds ARREADY, never returns anything but OKAY,
and puts RLAST exactly where AxLEN says it goes. That is fine for
proving arithmetic and useless for proving a bus interface, and the gap
is not theoretical - two independent reviews of this engine found four
bugs between them and three were invisible to a cooperative slave:

  * ARADDR/ARLEN were combinational on a FIFO count while ARVALID was
    asserted, violating AXI4 A3.2.1. A slave that samples the address
    once, on whatever cycle it likes, never notices.
  * The write path's 4KB-boundary term used a hardcoded beat size, so
    it computed zero beats near a page end and stalled forever - at a
    geometry no bench ran, at an address no bench reached.
  * A CSR sampled write data one cycle after the handshake, invisible
    to any master that waits for BRESP before moving on.

WHY BACKPRESSURE IS THE INTERESTING ONE HERE. For most designs it asks
"does it still work". For this one it asks something sharper. The whole
product is that the answer depends on nothing but the inputs - so a run
under a hostile schedule must return not merely a valid result but the
SAME BITS as the same run under a cooperative one. Timing is the most
plausible thing that could quietly reach the answer, and this is how
that gets ruled out instead of asserted.

IMPLEMENTATION NOTE. The faults are injected by wrapping the R and B
channels' send() rather than by re-implementing the slave's
_process_read/_process_write. Those methods hardcode `rresp = OKAY`
with no hook, so the obvious route is to copy ~60 lines of a pinned
dependency's internals into this repository - which then silently rots
the day the pin moves. Wrapping one method touches one documented
entry point instead. The only upstream detail relied on is that the
slave builds each beat as a transaction object and hands it to
`send()`, which is the shape of every channel in the library.
"""

import collections
import os
import random

import cocotb
from cocotb.triggers import RisingEdge

from cocotbext.axi.constants import AxiResp


# --------------------------------------------------------------------
# A. Backpressure
# --------------------------------------------------------------------

_CHANNELS = ("ar_channel", "r_channel", "aw_channel", "w_channel",
             "b_channel")


def _pauses(seed, duty):
    """A deterministic pause pattern.

    Seeded, so a failure reproduces from the test name alone rather
    than from whatever the simulator happened to do that evening. A
    stall pattern nobody can reproduce is a bug report nobody can act
    on.
    """
    rng = random.Random(seed)
    while True:
        yield rng.random() < duty


def stall(*rams, seed=0, duty=0.35):
    """Pause every channel of every attached master.

    On a Sink (AR, AW, W) pausing withholds READY, so the DUT is made
    to HOLD its payload - which is where a design that lets ARADDR
    drift under an asserted ARVALID gets caught. On a Source (R, B)
    pausing withholds VALID, so data arrives in gaps, which is what
    exercises FIFO occupancy and the reservation accounting.

    Every channel gets its own seed offset. One shared generator would
    stall every channel on the same cycles - a schedule far more
    regular than anything real, and one that would systematically miss
    the interleavings that matter.
    """
    n = 0
    for ram in rams:
        for name in _CHANNELS:
            ch = getattr(ram, name, None)
            if ch is None:
                continue            # read-only and write-only masters
            ch.set_pause_generator(_pauses(seed + n * 977, duty))
            n += 1
    return n


def unstall(*rams):
    """Back to the cooperative slave, for a clean reference run.

    set_pause_generator(None) alone is NOT that: it kills the pause
    coroutine and leaves `pause` FROZEN at whatever the generator last
    yielded, so at duty 0.35 roughly a third of the channels stay
    wedged - VALID or READY withheld forever. Latent since the day
    this file was written, because every bench that unstalled ended
    right there; the first test to drive traffic AFTER an unstall
    hung on its first read burst and spent an evening looking like a
    refusal-logic bug. Hence the explicit release below.
    """
    for ram in rams:
        for name in _CHANNELS:
            ch = getattr(ram, name, None)
            if ch is not None:
                ch.set_pause_generator(None)
                ch.pause = False


# --------------------------------------------------------------------
# B and C. Faults: error responses, and burst-length violations
# --------------------------------------------------------------------
#
# The engine records three things in err_acc, and they are NOT
# equivalent - which only became clear from reading it closely:
#
#   ERR_RRESP / ERR_BRESP  The beat still arrives; RVALID is asserted
#                          alongside the error response. So the run
#                          COMPLETES, STATUS comes back non-zero, and
#                          the host reports CFT_ERR_BUS_FAULT. Correct
#                          behaviour that had simply never been run.
#
#   ERR_RLEN               A short burst means the beats never arrive.
#                          The FIFO never fills, compute stalls, and
#                          ap_done never asserts. The bit is latched and
#                          nothing can read it, because nothing can read
#                          anything until the run ends.
#
# The second is why the engine now TERMINATES on a length error rather
# than waiting. A master that deadlocks because a slave violated the
# protocol is the one option no comparable design takes: AXI4 requires
# a slave to return exactly AxLEN+1 transfers (A3.4.1) and says nothing
# about master recovery, so the convention comes from the rest of the
# stack - PCIe logs the error and completes the transaction, a Xilinx
# AXI interconnect answers SLVERR rather than stalling the fabric, and
# ap_ctrl_hs has no representation for a run that never finishes. A
# hang costs a card reset; a clean CFT_ERR_BUS_FAULT costs a retry.


class Faults:
    """Fault state for one attached master.

    resp_at    global R-beat index to answer with `resp` instead of
               OKAY; None disables. Counted across the whole run rather
               than within a burst, so a test can aim at "the third
               beat the engine ever receives" without knowing how the
               engine chose to divide it into bursts.
    resp       AxiResp.SLVERR or AxiResp.DECERR.
    bresp_at   write-response index to answer with `resp`.
    short_at   burst index to truncate: RLAST arrives one beat early,
               so the master is told the burst ended before AxLEN said
               it would. The AXI4 violation ERR_RLEN exists to catch.
    long_at    burst index to overrun: one extra beat after the one
               that should have been last.
    """

    def __init__(self):
        self.reset()

    def reset(self):
        self.resp_at = None
        self.bresp_at = None
        self.resp = AxiResp.SLVERR
        self.short_at = None
        self.long_at = None
        self.beat_n = 0
        self.burst_n = 0
        self.bresp_n = 0
        self._swallow = False
        return self

    def arm(self, **kw):
        """Set a fault and zero the counters, between runs."""
        self.reset()
        for k, v in kw.items():
            if not hasattr(self, k):
                raise AttributeError(f"no such fault: {k}")
            setattr(self, k, v)
        return self


def instrument(ram):
    """Give `ram` a .fx you can arm. Idempotent."""
    if hasattr(ram, "fx"):
        return ram.fx
    ram.fx = Faults()
    fx = ram.fx

    r_ch = getattr(ram, "r_channel", None)
    if r_ch is not None:
        orig_send = r_ch.send

        async def send_r(r):
            # Swallowing the tail of a truncated burst. The beats are
            # dropped rather than sent, because the point is that the
            # master was told the burst was over and must not receive
            # more of it.
            if fx._swallow:
                if int(r.rlast):
                    fx._swallow = False
                    fx.burst_n += 1
                return

            if fx.resp_at is not None and fx.beat_n == fx.resp_at:
                r.rresp = fx.resp
            fx.beat_n += 1

            last = int(r.rlast)

            if (fx.short_at is not None and fx.burst_n == fx.short_at
                    and not last):
                # End it here instead of where ARLEN said.
                r.rlast = 1
                fx._swallow = True
                await orig_send(r)
                return

            if last and fx.long_at is not None and fx.burst_n == fx.long_at:
                # This beat should have been last; send it without
                # RLAST and follow it with one the master never asked
                # for.
                r.rlast = 0
                await orig_send(r)
                extra = r_ch._transaction_obj()
                extra.rid = r.rid
                extra.rdata = r.rdata
                extra.rresp = AxiResp.OKAY
                extra.rlast = 1
                fx.beat_n += 1
                fx.burst_n += 1
                await orig_send(extra)
                return

            if last:
                fx.burst_n += 1
            await orig_send(r)

        r_ch.send = send_r

    b_ch = getattr(ram, "b_channel", None)
    if b_ch is not None:
        orig_bsend = b_ch.send

        async def send_b(b):
            if fx.bresp_at is not None and fx.bresp_n == fx.bresp_at:
                b.bresp = fx.resp
            fx.bresp_n += 1
            await orig_bsend(b)

        b_ch.send = send_b

    return fx


# --------------------------------------------------------------------
# D. Latency
# --------------------------------------------------------------------
#
# WHY THIS EXISTS. A stock cocotbext-axi RAM answers in ZERO cycles:
# the first R beat of a burst lands one or two cycles after ARVALID,
# and BVALID follows the last W beat just as fast. Every throughput
# number this repository has ever taken in simulation - `make cycles`
# and its 1.250 marginal cycles a beat - was taken against that slave.
#
# On the card the same RTL sustained 2.25 cycles a beat at every
# format and every size (docs/BENCHMARKS.md, "The engine, measured"),
# and a ceiling flat across format and size, well under both the
# masters' own limit and HBM's bandwidth, is the signature of a path
# bounded by LATENCY rather than by bandwidth: so many bytes in flight
# per stream, divided by the controller's round trip, IS the rate. The
# cocotb model could not show it because the cocotb model has no round
# trip. This is the knob that gives it one.
#
# THE MODEL IS PIPELINED, not serialising, and that distinction is the
# whole point. Delaying inside the slave's own `_process_read` would
# make each burst cost its latency before the next one started, which
# is a memory with ONE outstanding transaction - the opposite of what
# HBM does and a model that could never be beaten by a deeper
# read-ahead. Instead each beat is stamped with a release cycle as the
# slave produces it and a consumer coroutine emits it when that cycle
# arrives, in order. The slave still produces at one beat a cycle, so
# what the DUT sees is a memory of one beat per cycle of bandwidth and
# `cycles` of latency: exactly the shape whose remedy is more bytes in
# flight.
#
# The delay lands on R and B - the response channels - and not on the
# AR/AW/W sinks, because withholding a READY is backpressure, which
# `stall()` above already models and which is a different fault.
#
# Zero (the default everywhere) installs NOTHING: no wrapper, no
# coroutine, no behaviour change, so every bench that does not ask for
# latency draws exactly the slave it always drew.


def env_latency():
    """(read, write) latency in clock cycles from the environment.

    CFT_RD_LATENCY delays every R beat, CFT_WR_LATENCY every write
    response. tb/Makefile exposes them as RD_LATENCY and WR_LATENCY.
    Unset or empty means zero, which means "do not install anything".
    """
    def get(name):
        v = os.environ.get(name, "")
        return int(v) if v.strip() else 0
    return get("CFT_RD_LATENCY"), get("CFT_WR_LATENCY")


class _Cycles:
    """A monotone cycle counter for one clock.

    Deadlines are compared in CYCLES rather than in simulated time so
    the knob means the same thing whatever period a bench clocks at,
    and so nothing here has to know the period.
    """

    def __init__(self, clk):
        self.n = 0
        self.clk = clk
        cocotb.start_soon(self._run())

    async def _run(self):
        while True:
            await RisingEdge(self.clk)
            self.n += 1


def _delay_channel(ch, ticks, cycles, cap):
    """Put `cycles` of pipelined delay in front of one source channel."""
    orig_send = ch.send
    queue = collections.deque()

    async def send(obj):
        # A bound, so a runaway model cannot allocate without limit.
        # It is far above anything the engine can have in flight - the
        # cap is a safety net, not a throttle, and a cap that throttled
        # would silently change what is being measured.
        while len(queue) >= cap:
            await RisingEdge(ticks.clk)
        queue.append((ticks.n + cycles, obj))

    async def drain():
        while True:
            if not queue:
                await RisingEdge(ticks.clk)
                continue
            # In order, always: the head's deadline is the earliest,
            # because deadlines are stamped in production order and the
            # delay is constant. AXI responses on one ID must not be
            # reordered, and this is where that is guaranteed.
            due, obj = queue[0]
            while ticks.n < due:
                await RisingEdge(ticks.clk)
            queue.popleft()
            await orig_send(obj)

    ch.send = send
    cocotb.start_soon(drain())


def latency(*rams, clk, read=0, write=0, cap=8192):
    """Give every attached model `read` cycles of read-data latency and
    `write` cycles of write-response latency.

    Returns the (read, write) pair actually installed, so a bench can
    print what it measured against. Call AFTER instrument(): the fault
    wrappers belong at the slave's end of the pipe, where a real
    controller would decide a response, and the delay in front of them.
    """
    if not read and not write:
        return (0, 0)
    ticks = _Cycles(clk)
    for ram in rams:
        if read:
            ch = getattr(ram, "r_channel", None)
            if ch is not None:
                _delay_channel(ch, ticks, read, cap)
        if write:
            ch = getattr(ram, "b_channel", None)
            if ch is not None:
                _delay_channel(ch, ticks, write, cap)
    return (read, write)
