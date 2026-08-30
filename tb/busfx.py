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

import random

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
    """Back to the cooperative slave, for a clean reference run."""
    for ram in rams:
        for name in _CHANNELS:
            ch = getattr(ram, name, None)
            if ch is not None:
                ch.set_pause_generator(None)


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
