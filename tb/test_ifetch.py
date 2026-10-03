# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The instruction fetch unit alone: rtl/cft_ifetch.sv against SeqRam.

Revision 8's streaming (docs/studies/R8S-streaming.md; parcel RD1). The
unit is driven the way cft_seq will drive it, by a cycle-level model of
the sequencer's fetch states - S_FETCH, S_FETCH2, S_DECODE, S_ISSUE and
the skip - presenting `want`/`addr`, taking `word` on `ok`, strobing
`cap` as a REPEAT enters a body and `quiesce` as a block ends, and
deciding its control flow from the words the unit hands it. Each
program is also walked with no unit at all, straight from its words,
under the same decisions (the lanes' activity is a seeded script, since
there are no lanes here), and the two walks must visit the same
addresses in the same order with the same words: every word the unit
hands over is held to the image's word at the address presented.

The memory is test_seq_core.py's SeqRam, given a round trip for this
unit - 0, 125 and 256 cycles (the card's bound is 144, and the design is
sized for 256; S8, section 1) - and a depth of eight bursts. Its
`_check_burst` refuses a burst that crosses 4 KB. A monitor beside it
holds every AR to the instruction section, to the AXI rule that an AR
stands unchanged until taken, and to silence after a quiesce or a
fault; RREADY never high while the unit is idle; and `ok` never high
once a fault is seen.

The cases: a program the store holds (no read in any block), a loop
body that starts in the store and runs past it, a body past the store
that fits it (captured) and one that does not, nesting four deep with
early exits and skips at every depth, block restarts after a retarget,
every 4-byte granule offset of the instruction section, a section
across 4 KB, a program of exactly the capacity ending in HALT and by the
implicit halt, and the faults - a non-OKAY beat, a short burst, a long
one, and a fault on a burst a quiesce has abandoned.

    make -C tb ifetch                 Icarus (the suite's default)
    make -C tb ifetch SIM=verilator   while iterating

The unit's parameters arrive as CFT_GENERICS (tb/Makefile's
IFETCH_GENERICS): a 64-word store and a 4,096-word capacity, so that a
program of exactly the capacity costs eight thousand cycles; everything
else is the U50's.
"""

import os
import random
import struct
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import seq                         # noqa: E402

import test_seq_core as core                       # noqa: E402

_i = core._i


def _generics():
    g = dict(BEAT_BITS=256, GW=32, ADDR_W=64, STORE_D=4096,
             STREAM_D=1 << 24, FIFO_LOG2=9, BURST=8, LIVE_MAX=4, OUT_MAX=8)
    for tok in os.environ.get("CFT_GENERICS", "").split():
        k, v = tok.split("=", 1)
        g[k] = int(v, 0)
    return g


G = _generics()
STORE_D, STREAM_D = G["STORE_D"], G["STREAM_D"]
BURST, OUT_MAX = G["BURST"], G["OUT_MAX"]
BB = G["BEAT_BITS"] // 8            # a beat's bytes
assert BB == core.BEAT_BYTES, "SeqRam serves 32-byte beats"
WPB = BB // 8                       # instructions a beat
LATENCIES = tuple(int(x) for x in
                  os.environ.get("CFT_IFETCH_LATENCIES", "0,125,256").split(","))
CLK_NS = 4
SEED = int(os.environ.get("CFT_SEED", "20261002"))

PIPED = {seq.DEPOSIT, seq.SETACT, seq.STL, seq.LDL, seq.STX, seq.LDX}


def is_ctrl(w):
    return (w >> 31) & 1


def code(w):
    return w & 0xFF


def piped(w):
    return not is_ctrl(w) or code(w) in PIPED


def rep(trip):
    # encode(), not seq.repeat(): the loader refuses `repeat 0` and the
    # hardware is defined to skip it, so the skip cases need the word.
    return seq.encode(seq.REPEAT, ctrl=True, imm=trip)


def endrep():
    return seq.endrep()


def halt():
    return seq.halt()


def alu(rng):
    """A word the unit cannot tell from any other: random, with the
    control bit clear, so the consumer issues it as an arithmetic
    instruction and a wrong word is a wrong value, not only a wrong
    path."""
    return rng.getrandbits(64) & ~(1 << 31)


def alus(rng, k):
    return [alu(rng) for _ in range(k)]


def image(words, nconsts=0, esz=4, bank_ext=False, rng=None):
    """A program image's bytes and its instruction section's offset in
    them. The unit reads only the section; the header and constants are
    there so the section sits where a real image puts it."""
    rng = rng or random.Random(1)
    hdr = struct.pack("<8I", seq.MAGIC, seq.VERSION, len(words),
                      nconsts, 1, 0, 1 if bank_ext else 0, 0)
    consts = b"" if bank_ext else bytes(rng.getrandbits(8)
                                        for _ in range(nconsts * esz))
    body = b"".join(struct.pack("<Q", w) for w in words)
    return hdr + consts + body, 32 + len(consts)


class Script:
    """Whether a REPEAT or an ENDREP finds an active lane: seeded, and
    consumed in program order, so the reference walk and the unit's walk
    draw the same answers for the same decisions."""

    def __init__(self, seed, p_active):
        self.rng = random.Random(seed)
        self.p = p_active

    def active(self):
        return self.p >= 1.0 or self.rng.random() < self.p


def ref_walk(words, nblocks, script):
    """The addresses a sequencer visits, block by block, straight from
    the words: cft_seq's S_DECODE and skip, with no fetch at all."""
    n, out = len(words), []
    for _ in range(nblocks):
        pc, stack, tr = 0, [], []
        while pc < n:
            w = words[pc]
            tr.append(pc)
            if piped(w):
                pc += 1
                continue
            c = code(w)
            if c == seq.REPEAT:
                trip = w >> 32
                if trip == 0 or not script.active():
                    depth, pc, found = 1, pc + 1, False
                    while pc < n:
                        w2 = words[pc]
                        tr.append(pc)
                        pc += 1
                        if is_ctrl(w2) and code(w2) == seq.REPEAT:
                            depth += 1
                        elif is_ctrl(w2) and code(w2) == seq.ENDREP:
                            if depth == 1:
                                found = True
                                break
                            depth -= 1
                    if not found:
                        break
                else:
                    stack.append([pc + 1, trip])
                    pc += 1
            elif c == seq.ENDREP:
                if not stack:
                    break
                if stack[-1][1] > 1 and script.active():
                    stack[-1][1] -= 1
                    pc = stack[-1][0]
                else:
                    stack.pop()
                    pc += 1
            else:
                break
        out.append(tr)
    return out


class Monitor:
    """Every cycle, at ReadOnly: the AR channel and the R channel's
    RREADY, held to what the unit promises the port (cft_ifetch.sv's
    header, "What the unit guarantees the port")."""

    def __init__(self, dut, lo, hi):
        self.dut = dut
        self.lo, self.hi = lo, hi        # first and last beat of the section
        self.ars = []                    # (cycle, address, beats)
        self.quiet = True                # no AR may begin
        self.cyc = 0
        self.err = []

    def bad(self, msg):
        if len(self.err) < 8:
            self.err.append(f"cycle {self.cyc}: {msg}")

    async def run(self):
        dut = self.dut
        pend = None              # an AR presented and not yet taken
        fault_before = False
        while True:
            await ReadOnly()
            av, ar = _i(dut.m_rd_arvalid), _i(dut.m_rd_arready)
            if av:
                a, ln = _i(dut.m_rd_araddr), _i(dut.m_rd_arlen) + 1
                if pend is not None:
                    if (a, ln) != pend:
                        self.bad(f"AR changed while waiting: {pend} -> {(a, ln)} (AXI4 A3.2.1)")
                else:
                    if self.quiet:
                        self.bad(f"an AR at {a:#x} began while the fetch was quiesced")
                    if fault_before:
                        self.bad(f"an AR at {a:#x} began after a fault")
                    if a % BB:
                        self.bad(f"AR {a:#x} not beat-aligned")
                    if not 1 <= ln <= BURST:
                        self.bad(f"AR of {ln} beats, BURST is {BURST}")
                    if a < self.lo or a + (ln - 1) * BB > self.hi:
                        self.bad(f"AR {a:#x} x{ln} leaves the section "
                                 f"[{self.lo:#x}, {self.hi:#x}] - past n_insns or before it")
                    self.ars.append((self.cyc, a, ln))
                pend = None if ar else (a, ln)
            else:
                if pend is not None:
                    self.bad("ARVALID dropped before ARREADY (AXI4 A3.2.1)")
                pend = None
            if _i(dut.m_rd_rready) and _i(dut.idle):
                self.bad("RREADY high while idle - a beat the unit did not ask for")
            flt = _i(dut.fault_rd) or _i(dut.fault_len)
            if flt and _i(dut.ok):
                self.bad("ok high after a fault")
            fault_before = flt
            await RisingEdge(dut.clk)
            self.cyc += 1


class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.ram = core.SeqRam(dut, rd_latency=0, rd_depth=OUT_MAX,
                               clk=dut.clk)
        self.mon = None
        self.mon_task = None

    async def start(self):
        dut = self.dut
        cocotb.start_soon(Clock(dut.clk, CLK_NS, units="ns").start())
        for name in ("init", "ld", "ld_word", "want", "addr", "take", "cap",
                     "cap_pc", "quiesce", "cfg_ibase", "cfg_n"):
            getattr(dut, name).value = 0
        dut.rst_n.value = 0
        cocotb.start_soon(self.ram.serve())
        await ClockCycles(dut.clk, 6)
        dut.rst_n.value = 1
        await ClockCycles(dut.clk, 2)

    async def reset(self):
        dut = self.dut
        await FallingEdge(dut.clk)
        dut.rst_n.value = 0
        await ClockCycles(dut.clk, 3)
        await FallingEdge(dut.clk)
        dut.rst_n.value = 1

    def stage(self, base, words, nconsts=0, bank_ext=False):
        """Place an image at `base`; returns the instruction section's
        byte address, cfg_ibase."""
        data, off = image(words, nconsts=nconsts, bank_ext=bank_ext)
        self.ram.stage(base, data)
        return base + off

    async def load(self, ibase, n, words):
        """The run's start and the parse: init, then one strobe a
        cycle for every instruction, as S_IMG_PARSE hands them over."""
        dut = self.dut
        await FallingEdge(dut.clk)
        dut.cfg_ibase.value = ibase
        dut.cfg_n.value = n
        dut.init.value = 1
        await FallingEdge(dut.clk)
        dut.init.value = 0
        for w in words:
            dut.ld.value = 1
            dut.ld_word.value = w
            await FallingEdge(dut.clk)
        dut.ld.value = 0
        dut.ld_word.value = 0

    def watch(self, ibase, n):
        if self.mon_task is not None:
            self.mon_task.kill()
        lo = ibase & ~(BB - 1)
        hi = (ibase + 8 * n - 1) & ~(BB - 1)
        self.mon = Monitor(self.dut, lo, hi)
        self.mon_task = cocotb.start_soon(self.mon.run())
        return self.mon


class Consumer:
    """cft_seq's fetch states, cycle by cycle, against the unit.

    Driven at the falling edge, read at the falling edge: `ok` and `word`
    are registered in the unit, so what is read is the answer to the
    address driven a cycle before. An arithmetic word issues for a drawn
    number of steps (cft_seq's live beats, 1 to 16), with drawn holds
    (rd_hold); its last unheld step takes the next word if `ok`, and
    falls to S_FETCH if not, exactly as S_ISSUE's continuation does.
    `want` is low in a cycle that takes, as the interface requires.
    """

    def __init__(self, dut, words, script, rng, mon, p_hold=0.1,
                 steps=(1, 1, 1, 2, 2, 3, 16)):
        self.dut, self.words, self.n = dut, words, len(words)
        self.script, self.rng, self.mon = script, rng, mon
        self.p_hold, self.steps = p_hold, steps
        self.stalls = 0          # cycles a wanted word was not there
        self.max_wait = 0        # the longest such run
        self.cycles = 0
        self.starts = []         # the monitor's cycle at each block's first want

    def _drive(self, want=0, addr=0, take=0, cap=0, cap_pc=0, quiesce=0):
        d = self.dut
        d.want.value = want
        d.addr.value = addr
        d.take.value = take
        d.cap.value = cap
        d.cap_pc.value = cap_pc
        d.quiesce.value = quiesce

    def _check(self, a, w):
        if not 0 <= a < self.n:
            raise AssertionError(
                f"the unit handed a word ({w:#018x}) for address {a}, at or "
                f"past n_insns = {self.n}: it never returns a word there")
        want = self.words[a]
        if w != want:
            raise AssertionError(
                f"the unit handed {w:#018x} for address {a}, whose word is "
                f"{want:#018x} - a word the memory did not deliver there")

    async def block(self, limit):
        """One block, pc 0 to its end; -> (trace, ended_by_fault)."""
        dut = self.dut
        st, pc, cur, steps, depth = "FETCH", 0, 0, 0, 0
        stack, tr, wait = [], [], 0
        first_want = True
        for cyc in range(limit):
            await FallingEdge(dut.clk)
            self.cycles += 1
            okv = _i(dut.ok)
            wv = _i(dut.word) if okv else None
            if _i(dut.fault_rd) or _i(dut.fault_len):
                # The abort (round 2's): the run ends. Nothing more is
                # asked for; the unit drains on its own.
                self._drive()
                self.mon.quiet = True
                return tr, True
            st0 = st
            want = take = cap = quiesce = 0
            addr = cap_pc = 0
            if st == "FETCH":
                if pc >= self.n:
                    st = "END"
                else:
                    want, addr, st = 1, pc, "FETCH2"
            elif st == "FETCH2":
                if okv:
                    take = 1
                    self._check(pc, wv)
                    tr.append(pc)
                    cur, st = wv, "DECODE"
                else:
                    want, addr = 1, pc
            elif st == "DECODE":
                if piped(cur):
                    steps, st = self.rng.choice(self.steps), "ISSUE"
                else:
                    c = code(cur)
                    if c == seq.REPEAT:
                        trip = cur >> 32
                        if trip == 0 or not self.script.active():
                            depth, pc, st = 1, pc + 1, "SKIP_F"
                        else:
                            stack.append([pc + 1, trip])
                            cap, cap_pc = 1, pc + 1
                            pc, st = pc + 1, "FETCH"
                    elif c == seq.ENDREP:
                        if not stack:
                            st = "END"
                        elif stack[-1][1] > 1 and self.script.active():
                            stack[-1][1] -= 1
                            pc, st = stack[-1][0], "FETCH"
                        else:
                            stack.pop()
                            pc, st = pc + 1, "FETCH"
                    else:
                        st = "END"
            elif st == "ISSUE":
                if self.rng.random() < self.p_hold:
                    want, addr = 1, pc + 1
                elif steps > 1:
                    steps -= 1
                    want, addr = 1, pc + 1
                elif okv:
                    take = 1
                    self._check(pc + 1, wv)
                    tr.append(pc + 1)
                    cur, pc = wv, pc + 1
                    if piped(cur):
                        steps = self.rng.choice(self.steps)
                    else:
                        st = "DECODE"
                else:
                    pc, st = pc + 1, "FETCH"
                    want, addr = 1, pc
            elif st == "SKIP_F":
                if pc >= self.n:
                    st = "END"
                else:
                    want, addr, st = 1, pc, "SKIP_D"
            elif st == "SKIP_D":
                if okv:
                    take = 1
                    self._check(pc, wv)
                    tr.append(pc)
                    w2, pc, st = wv, pc + 1, "SKIP_F"
                    if is_ctrl(w2) and code(w2) == seq.REPEAT:
                        depth += 1
                    elif is_ctrl(w2) and code(w2) == seq.ENDREP:
                        if depth == 1:
                            st = "FETCH"
                        else:
                            depth -= 1
                else:
                    want, addr = 1, pc
            elif st == "END":
                quiesce, st = 1, "IDLE"
                self.mon.quiet = True
            elif st == "IDLE":
                if _i(dut.idle):
                    self._drive()
                    return tr, False
            # a cycle spent waiting for a word that was asked for is a
            # stall - judged from the state the cycle began in
            if st0 in ("FETCH2", "SKIP_D") and not okv:
                wait += 1
                self.stalls += 1
                self.max_wait = max(self.max_wait, wait)
            elif take:
                wait = 0
            if want and first_want:
                self.mon.quiet = False
                self.starts.append(self.mon.cyc)
                first_want = False
            self._drive(want, addr, take, cap, cap_pc, quiesce)
        raise AssertionError(f"a block did not end within {limit} cycles "
                             f"(state {st}, pc {pc}) - a hang")


async def run_case(bench, words, nblocks, seed, lat, label, base=0x40000,
                   nconsts=0, bank_ext=False, p_active=1.0, limit=None,
                   expect_fault=None):
    """One program at one read latency: the parse, `nblocks` blocks, and
    every check. Returns the consumer and the monitor for the case's own
    assertions."""
    dut = bench.dut
    bench.ram.rd_latency = lat
    bench.ram.arlog = []
    await bench.reset()
    n = len(words)
    ibase = bench.stage(base, words, nconsts=nconsts, bank_ext=bank_ext)
    mon = bench.watch(ibase, n)
    await bench.load(ibase, n, words)
    rng = random.Random(seed * 7 + lat)
    cons = Consumer(dut, words, Script(seed, p_active), rng, mon)
    ref = ref_walk(words, nblocks, Script(seed, p_active))
    limit = limit or (40 * n * 8 + 200 * (lat + 40))
    got, faulted = [], False
    for b in range(nblocks):
        tr, faulted = await cons.block(limit)
        got.append(tr)
        if faulted:
            break
    if expect_fault is None:
        assert not faulted, f"{label}: a fault where none was planted"
        for b in range(nblocks):
            if got[b] != ref[b]:
                k = next((i for i, (x, y) in enumerate(zip(got[b], ref[b]))
                          if x != y), min(len(got[b]), len(ref[b])))
                raise AssertionError(
                    f"{label} @ latency {lat}: block {b} visited "
                    f"{got[b][max(0, k - 3):k + 3]} where the program visits "
                    f"{ref[b][max(0, k - 3):k + 3]} (step {k} of {len(ref[b])})")
    else:
        assert faulted, f"{label} @ latency {lat}: a planted fault went unseen"
        fr, fl = _i(dut.fault_rd), _i(dut.fault_len)
        assert (fr, fl) == expect_fault, (
            f"{label} @ latency {lat}: STATUS bits rd={fr} len={fl}, "
            f"expected rd={expect_fault[0]} len={expect_fault[1]}")
        # it ends: idle within the drain of everything in flight
        bound = 4 * (lat + 2 * BURST * OUT_MAX + 64)
        for c in range(bound):
            if _i(dut.idle):
                break
            await FallingEdge(dut.clk)
        else:
            raise AssertionError(f"{label}: not idle {bound} cycles after a fault")
        await ClockCycles(dut.clk, 3 * lat + 64)
        assert _i(dut.idle) and not _i(dut.m_rd_arvalid), (
            f"{label}: a read after the fault had drained")
    await ClockCycles(dut.clk, 4)
    assert not mon.err, f"{label} @ latency {lat}: " + "; ".join(mon.err)
    dut._log.info(
        f"{label} @ lat {lat}: {n} insns, {nblocks} blocks, {cons.cycles} cycles, "
        f"{len(mon.ars)} bursts, stalls {cons.stalls}, longest wait {cons.max_wait}")
    return cons, mon


def beat_of(ibase, k):
    return (ibase + 8 * k) & ~(BB - 1)


def stream_bursts(ibase, k0, n):
    """The bursts a stream from instruction k0 to the program's end
    issues, by the unit's rule: from the beat holding k0's first byte to
    the beat holding instruction n-1's last, BURST beats at most, never
    across 4 KB."""
    a, last, out = beat_of(ibase, k0), (ibase + 8 * n - 1) & ~(BB - 1), []
    while a <= last:
        ln = min(BURST, (last - a) // BB + 1, (4096 - (a & 0xFFF)) // BB)
        out.append((a, ln))
        a += ln * BB
    return out


async def bench_up(dut):
    b = Bench(dut)
    await b.start()
    return b


# ----------------------------------------------------------------------
# the cases
# ----------------------------------------------------------------------

@cocotb.test()
async def resident_program_reads_nothing(dut):
    """A program the store holds: the parse fills it, and no block issues
    a read - every cycle is today's (S8: "Nothing streams, no read is
    issued during a block")."""
    b = await bench_up(dut)
    rng = random.Random(SEED)
    n = min(STORE_D, 60)
    words = alus(rng, 3) + [rep(5)] + alus(rng, n - 7) + [endrep()] + alus(rng, 1) + [halt()]
    assert len(words) == n
    for lat in LATENCIES:
        cons, mon = await run_case(b, words, 3, SEED + 1, lat, "resident")
        assert not mon.ars, f"a resident program read {len(mon.ars)} bursts: {mon.ars[:4]}"
        assert cons.stalls == 0, f"a resident program stalled {cons.stalls} cycles"


@cocotb.test()
async def loop_body_runs_past_the_store(dut):
    """A body that starts inside the store and runs past it - every image
    cftc emits that is larger than the store. Each back-jump lands in the
    store and redirects the stream to the store's end, once: the count of
    bursts at that beat is the number of passes, no more."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 2)
    trips, blocks = 3, 2
    words = alus(rng, 4) + [rep(trips)] + alus(rng, 200) + [endrep()] + alus(rng, 10) + [halt()]
    for lat in LATENCIES:
        cons, mon = await run_case(b, words, blocks, SEED + 3, lat, "past-the-store")
        ib = 0x40000 + 32
        at_end = [x for x in mon.ars if x[1] == beat_of(ib, STORE_D)]
        assert len(at_end) == trips * blocks, (
            f"{len(at_end)} bursts at the store's end, beat {beat_of(ib, STORE_D):#x}; "
            f"a pass redirects once, so {trips * blocks}")


@cocotb.test()
async def loop_past_the_store_is_captured(dut):
    """A body that starts past the store and fits it: the REPEAT retargets
    the store, the first pass captures the body, and the later passes read
    nothing inside it. The next block's restart at pc 0 then misses the
    store and is refetched, and its entry into the body redirects the
    stream once to the body's end."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 4)
    pre, body, trips = STORE_D + 36, STORE_D // 2, 4
    words = alus(rng, pre) + [rep(trips)] + alus(rng, body) + [endrep()] + alus(rng, 20) + [halt()]
    for lat in LATENCIES:
        cons, mon = await run_case(b, words, 2, SEED + 5, lat, "captured")
        ib = 0x40000 + 32
        # Block 1 is one stream, from the store's end to the program's:
        # the capture redirects nothing, so its bursts are exactly the
        # sequential list. A replayed pass that read the body again, or a
        # back-jump that redirected, would add to it.
        first = [(a, ln) for (c, a, ln) in mon.ars if c < cons.starts[1]]
        want = stream_bursts(ib, STORE_D, len(words))
        assert first == want, (
            f"block 1 read {len(first)} bursts where one stream reads "
            f"{len(want)}: {first[:6]} against {want[:6]}")


@cocotb.test()
async def body_larger_than_the_store(dut):
    """A body past the store and longer than it: the first STORE_D words
    are captured and the rest stream, every pass. Each later pass costs
    one redirect - to the captured part's end - and no other."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 6)
    pre, body, trips = STORE_D + 6, 3 * STORE_D + 8, 3
    words = alus(rng, pre) + [rep(trips)] + alus(rng, body) + [endrep()] + [halt()]
    for lat in LATENCIES:
        cons, mon = await run_case(b, words, 1, SEED + 7, lat, "larger-than-store")
        ib = 0x40000 + 32
        cap_end = beat_of(ib, pre + 1 + STORE_D)
        at = [x for x in mon.ars if x[1] == cap_end]
        # pass 1 streams through that beat once (a burst may start there
        # or not), then each of the trips - 1 later passes starts one
        assert trips - 1 <= len(at) <= trips, (
            f"{len(at)} bursts at the captured part's end {cap_end:#x}, "
            f"expected one a later pass ({trips - 1}), plus at most one in pass 1")


@cocotb.test()
async def nesting_four_deep(dut):
    """Four nested loops, bodies on both sides of the store's range, a
    skip (REPEAT 0) at every depth and early exits drawn at every
    REPEAT and ENDREP: the store follows the innermost body that starts
    past it, and an enclosing back-jump that misses redirects."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 8)

    def skipped(k):
        return [rep(0)] + alus(rng, k) + [rep(2)] + alus(rng, 2) + [endrep()] + [endrep()]

    l4 = [rep(3)] + alus(rng, 6) + skipped(2) + alus(rng, 3) + [endrep()]
    l3 = [rep(2)] + alus(rng, 5) + skipped(3) + l4 + alus(rng, 4) + [endrep()]
    l2 = [rep(2)] + alus(rng, STORE_D // 2) + skipped(1) + l3 + alus(rng, STORE_D) + [endrep()]
    l1 = [rep(3)] + alus(rng, 6) + skipped(4) + l2 + alus(rng, 7) + [endrep()]
    words = alus(rng, 2) + l1 + alus(rng, 5) + [halt()]
    for lat in LATENCIES:
        for p in (1.0, 0.85):
            await run_case(b, words, 3, SEED + 9, lat, f"nesting p={p}", p_active=p)


@cocotb.test()
async def every_granule_offset(dut):
    """The instruction section at every 4-byte offset modulo 32: n_consts
    fp32 constants put it at 32 + 4 n_consts. A BANK_EXT image too, whose
    section is at 32. Each streams past the store and loops back."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 10)
    words = alus(rng, STORE_D + 9) + [rep(2)] + alus(rng, 37) + [endrep()] + alus(rng, 3) + [halt()]
    for lat in LATENCIES:
        for g in range(8):
            await run_case(b, words, 1, SEED + 11 + g, lat, f"granule {g}",
                           base=0x40000 + 0x1000 * g, nconsts=g)
        await run_case(b, words, 1, SEED + 19, lat, "bank_ext", base=0x50000,
                       nconsts=5, bank_ext=True)


@cocotb.test()
async def section_across_4k(dut):
    """A section placed so that bursts of eight beats from its start
    would cross a 4 KB boundary: SeqRam refuses a crossing burst, and the
    monitor holds every AR to the section."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 20)
    words = alus(rng, STORE_D + 300) + [rep(2)] + alus(rng, 40) + [endrep()] + [halt()]
    for lat in LATENCIES:
        for k in (STORE_D + 5, STORE_D + 37):
            # put instruction k at the page boundary, at a 4-byte offset
            base = 0x60000 - 32 - 8 * k + 4
            base -= base % 32
            await run_case(b, words, 1, SEED + 21, lat, f"across 4K at {k}",
                           base=base, nconsts=1)


@cocotb.test()
async def program_of_exactly_the_capacity(dut):
    """STREAM_D instructions, in prog_fills_imem's shape: a REPEAT 0 at pc
    0 skips the bulk at two cycles an instruction, so every word crosses
    the stream, and the last two execute at the capacity's edge - one
    image ending in HALT, one whose last word is arithmetic, so the block
    ends by the implicit halt with pc equal to the capacity. A position
    a bit short would wrap to 0 and the block would restart for ever."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 22)
    n = STREAM_D
    bulk = alus(rng, n - 4)
    for last in (halt(), alu(rng)):
        words = [rep(0)] + bulk + [endrep(), alu(rng), last]
        assert len(words) == n
        for lat in LATENCIES:
            await run_case(b, words, 1, SEED + 23, lat,
                           "capacity, " + ("HALT" if is_ctrl(last) else "implicit halt"),
                           base=0x100000, limit=4 * n + 40 * (lat + 64))


# ---- the faults -------------------------------------------------------

def _streaming_program(rng):
    return alus(rng, STORE_D + 200) + [rep(2)] + alus(rng, 60) + [endrep()] + [halt()]


@cocotb.test()
async def fault_rresp_ends_delivery(dut):
    """A non-OKAY beat on a live burst: STATUS[0], no word from that beat
    or after it, the stream drains and is idle, and no read follows."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 30)
    words = _streaming_program(rng)
    for lat in LATENCIES:
        b.ram.rresp_at = lambda burst, beat: 2 if (burst == 1 and beat == 1) else 0
        try:
            await run_case(b, words, 1, SEED + 31, lat, "rresp fault",
                           expect_fault=(1, 0))
        finally:
            b.ram.rresp_at = None


@cocotb.test()
async def fault_short_burst_ends_delivery(dut):
    """A burst that ends early (RLAST before ARLEN's beat): STATUS[2], and
    the unit does not wait for beats that will never come."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 32)
    words = _streaming_program(rng)
    for lat in LATENCIES:
        b.ram.beats_for = lambda burst, asked: asked - 3 if burst == 1 else asked
        try:
            await run_case(b, words, 1, SEED + 33, lat, "short burst",
                           expect_fault=(0, 1))
        finally:
            b.ram.beats_for = None


@cocotb.test()
async def fault_long_burst_ends_delivery(dut):
    """A burst one beat longer than ARLEN: STATUS[2]; the extra beat is
    drained to its RLAST and dropped, never handed on."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 34)
    words = _streaming_program(rng)
    for lat in LATENCIES:
        b.ram.beats_for = lambda burst, asked: asked + 1 if burst == 2 else asked
        try:
            await run_case(b, words, 1, SEED + 35, lat, "long burst",
                           expect_fault=(0, 1))
        finally:
            b.ram.beats_for = None


@cocotb.test()
async def fault_on_an_abandoned_burst(dut):
    """A block that halts while the stream is prefetching past the store:
    its bursts are abandoned by the quiesce, and one comes back non-OKAY
    after it. The fault is still raised: the memory failed on a read of
    the image, and the run must not go on as if it had not."""
    b = await bench_up(dut)
    rng = random.Random(SEED + 36)
    words = alus(rng, 9) + [halt()] + alus(rng, STORE_D + 300)
    for lat in [x for x in LATENCIES if x > 0]:
        b.ram.rresp_at = lambda burst, beat: 3 if (burst == 0 and beat == 2) else 0
        try:
            dut2 = b.dut
            b.ram.rd_latency = lat
            b.ram.arlog = []          # bursts are numbered from 0 a run
            await b.reset()
            ibase = b.stage(0x70000, words)
            mon = b.watch(ibase, len(words))
            await b.load(ibase, len(words), words)
            cons = Consumer(dut2, words, Script(SEED, 1.0), random.Random(lat), mon)
            tr, faulted = await cons.block(20 * lat + 4000)
            # The block ran to its HALT; the fault may show while it
            # waits for idle, which is the abandoned bursts draining.
            assert tr == list(range(10)), tr
            for _ in range(8 * lat + 400):
                await FallingEdge(dut2.clk)
                if _i(dut2.fault_rd):
                    break
            assert _i(dut2.fault_rd) == 1, (
                "a non-OKAY beat on an abandoned burst raised no fault")
            for _ in range(8 * lat + 400):
                if _i(dut2.idle):
                    break
                await FallingEdge(dut2.clk)
            assert _i(dut2.idle), "not idle after the abandoned bursts drained"
            assert not mon.err, "; ".join(mon.err)
            dut2._log.info(f"abandoned-burst fault @ lat {lat}: raised, idle")
        finally:
            b.ram.rresp_at = None
