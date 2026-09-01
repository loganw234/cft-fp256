# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The orbit sequencer's RTL against the golden model, bit for bit.

`rtl/cft_seq.sv` carries the behavioural contract in its header;
`python/cft_golden/seq.py` is the definition of correct. This bench
holds the module to both. Every case stages a program image and three
operand streams in one memory, runs the module, and compares EVERY
observable against `seq.run()` over the same program and the same
bits: every deposit slot in the window - including the `+0` of the
slots no lane reached - every per-lane deposit count, the sticky
FLAGS word, the deposit-overflow bit in `err`, and the refusal.

Three things this bench does that a results-only comparison would not:

* **The window is checked from the outside as well as the inside.**
  Memory is filled with poison before every run, and every write beat
  is logged with its strobe. A byte written outside `n * max_deposits`
  deposit elements or `n` counts is a failure NAMED BY ADDRESS, not a
  poison mismatch discovered three regions away. Lanes at or beyond
  `cfg_n` must get neither deposits nor counts, and the tail of the
  caller's buffer is the easiest thing in this design to trample.

* **A refusal must be quiet.** Each header-validation failure is run
  with an armed write logger, and the assertion is that the log is
  EMPTY - not that the result happened to be poison. A module that
  refuses after writing one beat has still corrupted a host buffer.

* **Blocking is invisible, and that is load-bearing.** The RTL runs
  lanes in blocks of `NBEATS` beats; the model runs the whole array at
  once. That the two agree IS the P2/P3 argument of docs/SEQUENCER.md,
  executed rather than asserted - the same argument `host/tests/
  seq_check.py` makes for libcft's 64-lane blocking, and the same one
  that lets the library split a run across compute units.

WHY THE MEMORY MODEL IS HAND-ROLLED. `cft_seq`'s masters are real but
SUBSET AXI4: address, length, valid/ready, data, last, resp - no
AxSIZE, AxBURST, or ID. cocotbext-axi's RAM can be coaxed onto that,
but the two things this bench most needs from a slave are not things a
stock RAM offers: a per-beat write log with strobes (for the window
and refusal assertions above) and control over what a read past the
staged region returns. Sixty lines of slave buys both, and the
protocol checks it does make - burst length, the 4KB boundary, WLAST
where AWLEN says it goes - are asserted here rather than assumed.

THE ONE AMBIGUITY, RECORDED. `ACTALL` in seq.py sets EVERY lane
active, padding lanes included; SEQUENCER.md's padding argument wants
them to stay out. The two readings differ only in FLAGS, and only for
a program containing `ACTALL` run at an `n` that does not fill its
lane block. Every ACTALL case below is therefore run block-aligned,
where the readings coincide - except `actall_over_a_ragged_block`,
which runs the case deliberately and REPORTS which reading the RTL
took without asserting either. See its docstring.
"""

import random
import sys
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, with_timeout

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import FORMATS, PREC_CODE  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import seq  # noqa: E402

FP32, FP64, FP128, FP256 = (FORMATS[k] for k in
                            ("fp32", "fp64", "fp128", "fp256"))

# rtl/cft_seq.sv parameter defaults. Keep in step with the module.
BEAT_BITS = 256
BEAT_BYTES = BEAT_BITS // 8
LATENCY = 15
NBEATS = 16
MAXD = 64
IMEM_D = 1024
KMEM_D = 256

CLK_NS = 4

# One memory, generously spaced. The deposit region is last and has
# the rest of the RAM behind it, because it is the only region whose
# size grows with max_deposits.
RAM_BYTES = 1 << 22
PROG_BASE = 0x00_1000
A_BASE = 0x01_0000
B_BASE = 0x02_0000
C_BASE = 0x03_0000
CNT_BASE = 0x04_0000
D_BASE = 0x10_0000

POISON = 0xA5
GUARD = 512          # bytes either side of a window that must stay poison


# ----------------------------------------------------------------------
# signal helpers
# ----------------------------------------------------------------------

def _i(sig, default=0):
    """int(sig) with X/Z read as `default`.

    Nothing in this bench should sample an X on a signal it cares
    about, but a hard crash inside a slave coroutine is the worst way
    to find out - it kills the memory model and the DUT then hangs on
    its next burst, which reads as a timeout in a completely different
    place.
    """
    try:
        return int(sig.value)
    except Exception:
        return default


# ----------------------------------------------------------------------
# the memory
# ----------------------------------------------------------------------

class SeqRam:
    """An AXI4 slave for cft_seq's simplified read and write masters.

    Cooperative by construction: OKAY on every response, no withheld
    handshakes. This is a semantics bench - the arithmetic and the
    addressing are what is under test - and the schedule-independence
    argument that hostile timing exists to make already has a home in
    test_krnl.py's backpressure runs against the same AXI style.
    """

    def __init__(self, dut, size=RAM_BYTES):
        self.dut = dut
        self.size = size
        self.mem = bytearray(size)
        self.reset_log()

    # -- test-side access ------------------------------------------------

    def poison(self):
        self.mem[:] = bytes([POISON]) * self.size
        self.reset_log()

    def reset_log(self):
        self.wbeats = []        # (addr, strb) per accepted W beat
        self.aw_count = 0
        self.ar_count = 0
        self.unaligned_ar = 0

    def stage(self, addr, data):
        assert addr + len(data) <= self.size, "staging past the model RAM"
        self.mem[addr:addr + len(data)] = data

    def fetch(self, addr, nbytes):
        return bytes(self.mem[addr:addr + nbytes])

    # -- checks ----------------------------------------------------------

    def assert_no_writes(self, label):
        if not self.wbeats and not self.aw_count:
            return
        where = (f"the first landed at {self.wbeats[0][0]:#x}"
                 if self.wbeats else "with no W beats")
        raise AssertionError(
            f"{label}: a refused run must write nothing, and this one "
            f"issued {self.aw_count} AW transaction(s) and "
            f"{len(self.wbeats)} W beat(s) - {where}. A module that "
            f"refuses after one beat has still corrupted a host buffer.")

    def assert_writes_inside(self, windows, label):
        """`windows` is [(base, nbytes, name)]. Every strobed byte of
        every write beat must land in one of them."""
        for addr, strb in self.wbeats:
            for k in range(BEAT_BYTES):
                if not (strb >> k) & 1:
                    continue
                byte = addr + k
                if any(base <= byte < base + size
                       for base, size, _ in windows):
                    continue
                near = ", ".join(f"{nm} [{base:#x},{base + size:#x})"
                                 for base, size, nm in windows) or "none"
                raise AssertionError(
                    f"{label}: wrote byte {byte:#x} (beat at {addr:#x}, "
                    f"strb {strb:#010x}) outside every legal window - "
                    f"the windows are {near}. Lanes at or beyond n get "
                    f"neither deposits nor counts, so the tail of the "
                    f"caller's buffers must come back untouched.")

    def assert_guards(self, windows, label):
        """Belt and braces for the log: the poison either side of each
        window must be intact even if a write escaped the logger."""
        for base, size, name in windows:
            for lo, what in ((max(0, base - GUARD), "below"),
                             (base + size, "above")):
                span = min(GUARD, self.size - lo)
                got = self.fetch(lo, span)
                if got != bytes([POISON]) * span:
                    off = next(i for i, v in enumerate(got) if v != POISON)
                    raise AssertionError(
                        f"{label}: poison {what} the {name} window was "
                        f"disturbed at {lo + off:#x} (found {got[off]:#04x})")

    # -- protocol --------------------------------------------------------

    def _check_burst(self, addr, alen, what):
        assert 0 <= alen <= 255, f"{what}: A{what[0].upper()}LEN {alen}"
        assert addr + (alen + 1) * BEAT_BYTES <= self.size, (
            f"{what} burst at {addr:#x} x{alen + 1} runs past the model "
            f"RAM ({self.size:#x} bytes) - either an address escaped or "
            f"the burst length did")
        last = addr + (alen + 1) * BEAT_BYTES - 1
        assert (addr & ~0xFFF) == (last & ~0xFFF), (
            f"{what} burst {addr:#x}..{last:#x} crosses a 4KB boundary, "
            f"which AXI4 forbids (A3.4.1)")

    async def serve(self):
        """Both masters, one coroutine, one pass per clock.

        Deliberately one and not two. Every trigger a bench awaits is a
        round trip through the simulator's VPI, and at ~40 wall seconds
        per million round trips a second coroutine doubles the cost of
        a target that runs for hundreds of thousands of cycles. The
        two masters never interact, so serving them from one loop
        costs nothing but this sentence. For the same reason the wide
        signals - a 256-bit ARADDR sibling, WDATA, RDATA - are read
        and written only on the cycles a handshake needs them.
        """
        dut = self.dut
        dut.m_rd_arready.value = 1
        dut.m_rd_rvalid.value = 0
        dut.m_rd_rdata.value = 0
        dut.m_rd_rlast.value = 0
        dut.m_rd_rresp.value = 0
        dut.m_wr_awready.value = 1
        dut.m_wr_wready.value = 1
        dut.m_wr_bvalid.value = 0
        dut.m_wr_bresp.value = 0

        pend, cur_r = [], None
        awq, wq, bq, cur_w = [], [], 0, None
        arready, rvalid, rlast, rdata = 1, 0, 0, 0
        bvalid = 0

        while True:
            await ReadOnly()

            # ---- read master -------------------------------------------
            if arready and _i(dut.m_rd_arvalid):
                addr, alen = _i(dut.m_rd_araddr), _i(dut.m_rd_arlen)
                self._check_burst(addr, alen, "read")
                if addr % BEAT_BYTES:
                    self.unaligned_ar += 1
                pend.append([addr, alen + 1])
                self.ar_count += 1
            if rvalid and _i(dut.m_rd_rready):
                cur_r[0] += BEAT_BYTES
                cur_r[1] -= 1
                if cur_r[1] == 0:
                    cur_r = None
            if cur_r is None and pend:
                cur_r = pend.pop(0)

            was_valid, rvalid = rvalid, int(cur_r is not None)
            if rvalid:
                rlast = int(cur_r[1] == 1)
                rdata = int.from_bytes(
                    self.mem[cur_r[0]:cur_r[0] + BEAT_BYTES], "little")
            else:
                rlast = 0
            arready = int(len(pend) < 4)

            # ---- write master ------------------------------------------
            if _i(dut.m_wr_awvalid):
                addr, alen = _i(dut.m_wr_awaddr), _i(dut.m_wr_awlen)
                self._check_burst(addr, alen, "write")
                awq.append([addr, alen + 1])
                self.aw_count += 1
            if _i(dut.m_wr_wvalid):
                wq.append((_i(dut.m_wr_wdata), _i(dut.m_wr_wstrb),
                           _i(dut.m_wr_wlast)))
            if bvalid and _i(dut.m_wr_bready):
                bvalid = 0

            while True:
                if cur_w is None:
                    if not awq:
                        break
                    base, beats = awq.pop(0)
                    cur_w = [base, beats, 0]
                if not wq:
                    break
                data, strb, last = wq.pop(0)
                at = cur_w[0] + cur_w[2] * BEAT_BYTES
                for k in range(BEAT_BYTES):
                    if (strb >> k) & 1:
                        self.mem[at + k] = (data >> (8 * k)) & 0xFF
                self.wbeats.append((at, strb))
                cur_w[2] += 1
                ends = cur_w[2] == cur_w[1]
                assert bool(last) == ends, (
                    f"WLAST at beat {cur_w[2]} of a burst AWLEN said was "
                    f"{cur_w[1]} beats long (AXI4 A3.4.1)")
                if ends:
                    bq += 1
                    cur_w = None
            if not bvalid and bq:
                bq -= 1
                bvalid = 1

            await RisingEdge(dut.ap_clk)
            dut.m_rd_arready.value = arready
            dut.m_wr_bvalid.value = bvalid
            if rvalid or was_valid:
                dut.m_rd_rvalid.value = rvalid
                dut.m_rd_rlast.value = rlast
                if rvalid:
                    dut.m_rd_rdata.value = rdata


# ----------------------------------------------------------------------
# program images
# ----------------------------------------------------------------------

def unchecked(fmt, insns, consts=(), max_deposits=1):
    """A Program that skips validate().

    The loader refuses several shapes the HARDWARE is defined to
    execute anyway - `repeat 0` is the one the contract calls out by
    name, because the obvious RTL tests `imm == 0` and skips. A bench
    that could only build programs the loader accepts could never run
    that case.
    """
    p = seq.Program.__new__(seq.Program)
    p.fmt = fmt
    p.insns = list(insns)
    p.consts = list(consts)
    p.max_deposits = max_deposits
    return p


def raw_image(fmt, insns, consts=(), *, magic=seq.MAGIC,
              version=seq.VERSION, n_insns=None, n_consts=None,
              max_deposits=1, prec=None, rsv=(0, 0)):
    """A program image with every header word under the test's control,
    so the refusal matrix can bend one field at a time.

    The BODY is always emitted in full and honestly: header counts that
    lie about it are a separate corruption, and mixing the two would
    leave a refusal ambiguous about which check fired.
    """
    ebytes = fmt.width // 8
    if n_insns is None:
        n_insns = len(insns)
    if n_consts is None:
        n_consts = len(consts)
    if prec is None:
        prec = PREC_CODE[fmt.name]
    out = bytearray()
    for word in (magic, version, n_insns, n_consts, max_deposits, prec,
                 rsv[0], rsv[1]):
        out += int(word & 0xFFFFFFFF).to_bytes(4, "little")
    for k in consts:
        out += int(k).to_bytes(ebytes, "little")
    for w in insns:
        out += int(w).to_bytes(8, "little")
    return bytes(out)


def worst_case_insns(insns):
    """The static worst-case instruction count, as validate() computes
    it. Used for the run timeout and to keep the fuzz's cost bounded."""
    mult, worst = [1], 0
    for word in insns:
        d = seq.decode(word)
        worst += mult[-1]
        if not d["ctrl"]:
            continue
        if d["op"] == seq.REPEAT:
            mult.append(mult[-1] * max(d["imm"], 1))
        elif d["op"] == seq.ENDREP and len(mult) > 1:
            mult.pop()
    return worst


def lanes_per_beat(fmt):
    return BEAT_BITS // fmt.width


def lanes_per_block(fmt):
    return NBEATS * lanes_per_beat(fmt)


def has_actall(insns):
    return any(seq.decode(w)["ctrl"] and seq.decode(w)["op"] == seq.ACTALL
               for w in insns)


# ----------------------------------------------------------------------
# the driver
# ----------------------------------------------------------------------

class Bench:
    def __init__(self, dut):
        self.dut = dut
        self.ram = SeqRam(dut)
        self.cases = Counter()

    async def start(self):
        dut = self.dut
        cocotb.start_soon(Clock(dut.ap_clk, CLK_NS, units="ns").start())
        dut.start.value = 0
        dut.cfg_prec.value = 0
        for name in ("cfg_n", "cfg_a", "cfg_b", "cfg_c", "cfg_d",
                     "cfg_prog", "cfg_cnt"):
            getattr(dut, name).value = 0
        cocotb.start_soon(self.ram.serve())
        dut.ap_rst_n.value = 0
        await ClockCycles(dut.ap_clk, 8)
        dut.ap_rst_n.value = 1
        await ClockCycles(dut.ap_clk, 4)

    async def _go(self, budget, label):
        dut = self.dut
        await RisingEdge(dut.ap_clk)
        dut.start.value = 1
        await RisingEdge(dut.ap_clk)
        dut.start.value = 0
        try:
            await with_timeout(RisingEdge(dut.done), budget * CLK_NS, "ns")
        except Exception as exc:                     # SimTimeoutError
            if type(exc).__name__ != "SimTimeoutError":
                raise
            raise AssertionError(
                f"{label}: no `done` within {budget} cycles. The module "
                f"issued {self.ram.ar_count} read burst(s) and "
                f"{self.ram.aw_count} write burst(s); busy="
                f"{_i(dut.busy)}.") from None
        await ReadOnly()
        got = (_i(dut.refuse), _i(dut.flags), _i(dut.err))
        await ClockCycles(dut.ap_clk, 8)
        assert _i(dut.busy) == 0, (
            f"{label}: busy still high eight cycles after done")
        return got

    def _stage(self, fmt, image, a, b, c, n, dep_bytes, cnt_bytes):
        ram = self.ram
        ram.poison()
        ram.stage(PROG_BASE, image)
        ebytes = fmt.width // 8
        for base, vals in ((A_BASE, a), (B_BASE, b), (C_BASE, c)):
            ram.stage(base, b"".join(
                int(v).to_bytes(ebytes, "little") for v in vals))
        assert D_BASE + dep_bytes + GUARD <= ram.size, (
            "the deposit window does not fit the model RAM; shrink n or "
            "max_deposits for this case")
        assert CNT_BASE + cnt_bytes + GUARD <= D_BASE

    def _drive_cfg(self, fmt, n):
        dut = self.dut
        dut.cfg_prec.value = PREC_CODE[fmt.name]
        dut.cfg_n.value = n
        dut.cfg_a.value = A_BASE
        dut.cfg_b.value = B_BASE
        dut.cfg_c.value = C_BASE
        dut.cfg_d.value = D_BASE
        dut.cfg_prog.value = PROG_BASE
        dut.cfg_cnt.value = CNT_BASE

    # -- a refused run ---------------------------------------------------

    async def refuse(self, fmt, image, why, n=8):
        """Run a program the hardware must refuse: `done` with `refuse`
        high, and not one byte of write traffic."""
        pool = [sf.one_bits(fmt)] * max(n, 1)
        self._stage(fmt, image, pool, pool, pool, n, 0, 0)
        self._drive_cfg(fmt, n)
        refused, flags, err = await self._go(20000, why)
        assert refused == 1, (
            f"{why}: the run was accepted (refuse=0). The header check "
            f"protects the hardware from an image that bypassed the "
            f"loader, so this one had to be turned away.")
        self.ram.assert_no_writes(why)
        assert flags == 0, f"{why}: a refused run raised FLAGS {flags:#07b}"
        assert (err & 0x8) == 0, (
            f"{why}: a refused run set the deposit-overflow bit")
        # nothing at all should have been disturbed, anywhere
        assert self.ram.fetch(D_BASE, 1024) == bytes([POISON]) * 1024, \
            f"{why}: the deposit region was written by a refused run"
        assert self.ram.fetch(CNT_BASE, 1024) == bytes([POISON]) * 1024, \
            f"{why}: the count region was written by a refused run"
        self.cases["refusal"] += 1
        self.dut._log.info(f"refused as it must: {why} (cfg_prec "
                           f"{fmt.name})")

    # -- an accepted run -------------------------------------------------

    async def program(self, fmt, prog, a, b, c, n, label,
                      *, check_flags=True, image=None):
        """Run `prog` over `n` lanes and compare the whole machine.

        `a`, `b`, `c` are the REAL streams, one value per lane in
        [0, n). The tail of each buffer stays poison: padding lanes
        start inactive, so what they would have read must not reach an
        observable.
        """
        dut = self.dut
        ebytes = fmt.width // 8
        maxdep = prog.max_deposits
        image = prog.to_bytes() if image is None else image
        dep_bytes = n * maxdep * ebytes
        cnt_bytes = 4 * n

        want = seq.run(prog, list(a), list(b), list(c))

        self._stage(fmt, image, a, b, c, n, dep_bytes, cnt_bytes)
        self._padding_selfcheck(fmt, prog, a, b, c, n, want, label)
        self._drive_cfg(fmt, n)

        budget = self._budget(fmt, prog, n, len(image))
        refused, flags, err = await self._go(budget, label)

        assert refused == 0, (
            f"{label}: the module refused a valid program. The header "
            f"is magic={seq.MAGIC:#010x} n_insns={len(prog.insns)} "
            f"n_consts={len(prog.consts)} max_deposits={maxdep} "
            f"prec={PREC_CODE[fmt.name]}, and cfg_prec matches.")

        windows = []
        if dep_bytes:
            windows.append((D_BASE, dep_bytes, "deposit"))
        if cnt_bytes:
            windows.append((CNT_BASE, cnt_bytes, "count"))
        self.ram.assert_writes_inside(windows, label)
        self.ram.assert_guards(windows, label)

        self._compare(fmt, prog, n, want, flags, err, a, b, c, label,
                      check_flags)
        self.cases["program"] += 1
        return want

    def _budget(self, fmt, prog, n, image_bytes):
        blocks = max(1, -(-n // lanes_per_block(fmt)))
        worst = worst_case_insns(prog.insns)
        cycles = (3000 + (image_bytes // BEAT_BYTES + 8) * 8
                  + blocks * (worst * (NBEATS + LATENCY + 8)
                              + 6 * NBEATS + 400))
        return min(cycles, 4_000_000)

    def _padding_selfcheck(self, fmt, prog, a, b, c, n, want, label):
        """The bench's own precondition, not a claim about the DUT.

        The model here is run over exactly `n` lanes, all of them
        active; the hardware runs whole lane blocks with the tail held
        inactive. Those agree for every program - unless `ACTALL`
        wakes the padding lanes, which changes what a padded array
        contributes to FLAGS. Rather than trust that, re-run the model
        over the padded array the hardware actually sees, reading the
        padding straight out of the staged memory, and confirm the two
        answers coincide. If they do not, this case is on the seam and
        the bench says so instead of blaming the RTL.
        """
        lpb = lanes_per_block(fmt)
        padded = max(1, -(-n // lpb)) * lpb if n else 0
        if padded == n or n == 0:
            return
        ebytes = fmt.width // 8

        def stream(base, vals):
            out = list(vals)
            for i in range(n, padded):
                out.append(int.from_bytes(
                    self.ram.fetch(base + i * ebytes, ebytes), "little"))
            return out

        pad = seq.run(prog, stream(A_BASE, a), stream(B_BASE, b),
                      stream(C_BASE, c), n_active=n)
        same = (pad.deposits[:n * prog.max_deposits] == want.deposits
                and pad.counts[:n] == want.counts
                and pad.flags == want.flags and pad.status == want.status)
        assert same, (
            f"{label}: BENCH PRECONDITION - this program run at n={n} "
            f"(lane block is {lpb}) reads differently depending on "
            f"whether ACTALL wakes the padding lanes, so no single "
            f"expectation is defensible. Run it block-aligned, or use "
            f"the dedicated actall_over_a_ragged_block case.")

    def _compare(self, fmt, prog, n, want, flags, err, a, b, c, label,
                 check_flags):
        dut = self.dut
        ebytes = fmt.width // 8
        maxdep = prog.max_deposits

        got_dep = self.ram.fetch(D_BASE, n * maxdep * ebytes)
        bad = 0
        for idx in range(n * maxdep):
            g = int.from_bytes(got_dep[idx * ebytes:(idx + 1) * ebytes],
                               "little")
            if g == want.deposits[idx]:
                continue
            bad += 1
            if bad <= 8:
                lane, slot = divmod(idx, maxdep)
                dut._log.error(
                    f"{label}: deposit[lane {lane} slot {slot}] "
                    f"(element {idx}, {D_BASE + idx * ebytes:#x}) "
                    f"got {g:#x} want {want.deposits[idx]:#x}"
                    + ("  <- an untouched slot must read +0"
                       if slot >= want.counts[lane] else ""))
        assert bad == 0, (
            f"{label}: {bad}/{n * maxdep} deposit slots differ from the "
            f"model. program={[hex(w) for w in prog.insns]} "
            f"consts={[hex(k) for k in prog.consts]} "
            f"max_deposits={maxdep} n={n} "
            f"a[0..3]={[hex(v) for v in a[:4]]} "
            f"b[0..3]={[hex(v) for v in b[:4]]} "
            f"c[0..3]={[hex(v) for v in c[:4]]}")

        got_cnt_raw = self.ram.fetch(CNT_BASE, 4 * n)
        got_cnt = [int.from_bytes(got_cnt_raw[i * 4:i * 4 + 4], "little")
                   for i in range(n)]
        if got_cnt != want.counts:
            first = next(i for i in range(n)
                         if got_cnt[i] != want.counts[i])
            raise AssertionError(
                f"{label}: deposit counts differ. First at lane {first} "
                f"({CNT_BASE + 4 * first:#x}): got {got_cnt[first]} want "
                f"{want.counts[first]}. got={got_cnt[:16]} "
                f"want={want.counts[:16]} "
                f"program={[hex(w) for w in prog.insns]}")

        if check_flags:
            assert flags == want.flags, (
                f"{label}: FLAGS {flags:#07b}, model says "
                f"{want.flags:#07b}. Only ACTIVE lanes contribute, so a "
                f"surplus bit is a lane that kept computing after it "
                f"dropped out. program={[hex(w) for w in prog.insns]} n={n}")

        want_ovf = bool(want.status & seq.STATUS_DEPOSIT_OVERFLOW)
        assert bool(err & 0x8) == want_ovf, (
            f"{label}: err[3] (deposit overflow -> STATUS[4]) is "
            f"{bool(err & 0x8)}, model says {want_ovf}. "
            f"max_deposits={maxdep}, counts={want.counts[:8]}")
        assert (err & 0x7) == 0, (
            f"{label}: err[2:0]={err & 0x7} - the model memory answered "
            f"OKAY on every beat, so a bus fault here is the module's")


# ----------------------------------------------------------------------
# programs the directed tests use
# ----------------------------------------------------------------------

def deposit_result(fmt, op, *, rnd=sf.RND_RNE, rd=4, ra=0, rb=1, rc=2):
    """One ALU instruction, its result deposited. The smallest program
    that can be wrong."""
    return seq.Program(fmt, [seq.alu(op, rd, ra, rb, rc, rnd=rnd),
                             seq.deposit(rd), seq.halt()], max_deposits=1)


def escape_program(fmt, iterations, limit_bits):
    """test_seq.py's escape map, unchanged: an fma chain, a magnitude
    test, a predicate, a deposition, and lanes dropping out as they
    converge. Kept identical so the RTL is scored against the exact
    program the model's own P3 tests use."""
    return seq.Program(
        fmt,
        [seq.repeat(iterations),
         seq.alu(sf.OP_FMA, 0, 0, 0, 1),
         seq.deposit(0),
         seq.alu(sf.OP_ABS, 2, 0),
         seq.alu(sf.OP_CMPLT, 3, 2, 0, kb=True),
         seq.setact(3),
         seq.endrep(),
         seq.halt()],
        consts=[limit_bits],
        max_deposits=iterations)


def seeds(fmt, n, seed):
    """Starting points either side of the escape radius, so lanes
    converge at visibly different iterations."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        e = fmt.bias + rng.randint(-3, 1)
        out.append((rng.getrandbits(1) << (fmt.width - 1))
                   | (e << fmt.man_w) | rng.getrandbits(fmt.man_w))
    return out


def operands(fmt, n, seed):
    """Half specials, half raw patterns - the mix that makes opcodes
    differ from one another."""
    rng = random.Random(seed)
    return seq.random_inputs(fmt, rng, n)


def dense(fmt, n, seed):
    """Finite normals with full-width significands.

    The specials-heavy mix above is the right default and the wrong
    input for the interval case: an fma over infinities and NaNs is
    EXACT, so roundTowardNegative and roundTowardPositive agree and a
    module that latched the attribute at start would sail through. A
    dense significand gives the attribute something to decide.
    """
    rng = random.Random(seed)
    return [(rng.getrandbits(1) << (fmt.width - 1))
            | ((fmt.bias + rng.randint(-6, 6)) << fmt.man_w)
            | rng.getrandbits(fmt.man_w) for _ in range(n)]


# ======================================================================
# 1. the refusal matrix
# ======================================================================

@cocotb.test()
async def refusal_matrix(dut):
    """Every header check the hardware still makes, one field at a time.

    The loader has already vetted a program that reaches a device, so
    the module re-checks only what protects the module: the magic, the
    format against cfg_prec, and the three capacities. Each failure
    must REFUSE - done with refuse high - and, the part that matters
    for a host buffer, write nothing at all.
    """
    bench = Bench(dut)
    await bench.start()

    body = [seq.alu(sf.OP_ADD, 4, 0, 1, 2), seq.deposit(4), seq.halt()]
    consts = [sf.one_bits(FP32)]

    await bench.refuse(
        FP32, raw_image(FP32, body, consts, magic=seq.MAGIC ^ 0xFF),
        "bad magic")
    await bench.refuse(
        FP32, raw_image(FP32, body, consts, magic=0),
        "zero magic")

    # A program is compiled for ONE format, because its constants are
    # format-width values; a mismatch would read the bank at the wrong
    # stride and compute confidently on garbage.
    for name, other in (("fp32", FP64), ("fp64", FP32),
                        ("fp128", FP256), ("fp256", FP128)):
        fmt = FORMATS[name]
        await bench.refuse(
            fmt, raw_image(fmt, body, [sf.one_bits(fmt)],
                           prec=PREC_CODE[other.name]),
            f"program says {other.name}, cfg_prec says {name}")

    # A precision code off the ladder cannot match cfg_prec either.
    await bench.refuse(
        FP32, raw_image(FP32, body, consts, prec=7),
        "precision code 7 is not on the ladder")

    await bench.refuse(
        FP32, raw_image(FP32, [seq.halt()] * (IMEM_D + 1)),
        f"n_insns {IMEM_D + 1} exceeds IMEM_D")
    await bench.refuse(
        FP32, raw_image(FP32, body,
                        [sf.one_bits(FP32)] * (KMEM_D + 1)),
        f"n_consts {KMEM_D + 1} exceeds KMEM_D")
    await bench.refuse(
        FP32, raw_image(FP32, body, consts, max_deposits=MAXD + 1),
        f"max_deposits {MAXD + 1} exceeds MAXD")
    await bench.refuse(
        FP32, raw_image(FP32, body, consts, max_deposits=1 << 20),
        "max_deposits 2^20 - the model's own cap, still past MAXD")
    # max_deposits == 0 is the other half of this check and lives at the
    # bottom of the file; see refuses_zero_max_deposits for why.

    # Every case here refuses, and that is on purpose: a test named for
    # refusals that also runs a program would report a compute failure
    # under a refusal heading. The legal side of the deposit cap -
    # max_deposits == MAXD, which must be ACCEPTED - is checked in
    # `deposition`, where the rest of the deposit behaviour lives.
    dut._log.info(f"refusal matrix: {bench.cases['refusal']} refusals, "
                  f"no write traffic on any of them")


# ======================================================================
# 2. one instruction at a time, on every rung
# ======================================================================

@cocotb.test()
async def single_op_programs(dut):
    """A program of one ALU instruction and one deposit, per opcode
    group and per format.

    P1 says the sequencer introduces no arithmetic - the ALU is the
    pipeline 441,000 conformance cases already cover - so these are not
    arithmetic tests. They test that the sequencer STEERS an operand to
    the lane the model says it goes to, at every element width, for a
    computed opcode, a bypassed one, an integer one and a seed one.
    """
    bench = Bench(dut)
    await bench.start()

    ops = [(sf.OP_FMA, 4), (sf.OP_ADD, 4), (sf.OP_MUL, 4),
           (sf.OP_IXOR, 4), (sf.OP_COPYSIGN, 4), (sf.OP_RECIP_SEED, 4)]
    sizes = {"fp32": 12, "fp64": 8, "fp128": 5, "fp256": 3}
    k = 0
    for name, n in sizes.items():
        fmt = FORMATS[name]
        for op, rd in ops:
            k += 1
            prog = deposit_result(fmt, op, rd=rd)
            await bench.program(
                fmt, prog, operands(fmt, n, 100 + k),
                operands(fmt, n, 200 + k), operands(fmt, n, 300 + k), n,
                f"{name} {sf.OP_NAMES[op]} n={n}")
    dut._log.info(f"single-op programs: {bench.cases['program']} runs")


# ======================================================================
# 3. the constant bank, and the attribute that changes per instruction
# ======================================================================

@cocotb.test()
async def constants_and_rounding(dut):
    """Constant-bank operands on all three source ports, and adjacent
    instructions rounding differently.

    The interval pattern is the reason the attribute is per
    instruction rather than per run: one pass produces both bounds. A
    module that latched `rnd` at start would pass every other test
    here and fail this one, so the case asserts up front that the two
    bounds the model computes actually DIFFER - otherwise it would
    pass for the wrong reason.
    """
    bench = Bench(dut)
    await bench.start()

    for name, n in (("fp32", 12), ("fp64", 8), ("fp128", 4)):
        fmt = FORMATS[name]
        bank = [sf.zero_bits(fmt), sf.one_bits(fmt),
                sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)]
        # ka, kb and kc each in turn, then all three at once
        prog = seq.Program(
            fmt,
            [seq.alu(sf.OP_FMA, 4, 1, 1, 2, ka=True),      # ra <- k[1]
             seq.deposit(4),
             seq.alu(sf.OP_FMA, 5, 0, 2, 2, kb=True),      # rb <- k[2]
             seq.deposit(5),
             seq.alu(sf.OP_FMA, 6, 0, 1, 3, kc=True),      # rc <- k[3]
             seq.deposit(6),
             seq.alu(sf.OP_MUL, 7, 2, 0, 0, ka=True, kb=True),
             seq.deposit(7),
             seq.halt()],
            consts=bank, max_deposits=4)
        await bench.program(fmt, prog, operands(fmt, n, 400),
                            operands(fmt, n, 401), operands(fmt, n, 402),
                            n, f"{name} constant bank ka/kb/kc")

        # the interval pattern: the same fma, twice, rounded outward
        interval = seq.Program(
            fmt,
            [seq.alu(sf.OP_FMA, 4, 0, 1, 2, rnd=sf.RND_RDN),
             seq.alu(sf.OP_FMA, 5, 0, 1, 2, rnd=sf.RND_RUP),
             seq.deposit(4), seq.deposit(5),
             seq.alu(sf.OP_FMA, 6, 0, 1, 2, rnd=sf.RND_RTZ),
             seq.alu(sf.OP_FMA, 7, 0, 1, 2, rnd=sf.RND_RMM),
             seq.deposit(6), seq.deposit(7),
             seq.halt()],
            max_deposits=4)
        a = dense(fmt, n, 410)
        b = dense(fmt, n, 411)
        c = dense(fmt, n, 412)
        want = seq.run(interval, a, b, c)
        lo = [want.deposits[i * 4 + 0] for i in range(n)]
        hi = [want.deposits[i * 4 + 1] for i in range(n)]
        assert lo != hi, (
            f"{name}: the two bounds came out identical for every lane, "
            f"so this case cannot see a module that latched `rnd` at "
            f"start; retune the operands")
        await bench.program(fmt, interval, a, b, c, n,
                            f"{name} interval pattern (rdn/rup/rtz/rmm)")

    # a program with NO constant bank at all - the fetch must not read
    # one, and the bank being empty must not upset the operand mux
    for name, n in (("fp32", 9), ("fp256", 2)):
        fmt = FORMATS[name]
        prog = seq.Program(
            fmt,
            [seq.alu(sf.OP_SUB, 4, 0, 0, 1), seq.deposit(4),
             seq.alu(sf.OP_MAXNUM, 5, 4, 2), seq.deposit(5), seq.halt()],
            consts=[], max_deposits=2)
        assert not prog.consts
        await bench.program(fmt, prog, operands(fmt, n, 420),
                            operands(fmt, n, 421), operands(fmt, n, 422),
                            n, f"{name} zero constants")
    dut._log.info(f"constants and rounding: {bench.cases['program']} runs")


# ======================================================================
# 4. loops, convergence, and the early exit
# ======================================================================

@cocotb.test()
async def loops_and_convergence(dut):
    """REPEAT/ENDREP, nested, zero-trip, and SETACT dropping lanes at
    different iterations.

    The escape map is the P3 case and the reason the whole design is
    allowed to exit early: lanes converge at different times, the
    module may notice as late as it likes, and the answer must be the
    model's regardless. The bench cannot see WHEN the module exited -
    which is the point - so it checks the only thing that may not
    change, which is everything else.
    """
    bench = Bench(dut)
    await bench.start()

    # -- flat loop -------------------------------------------------------
    for name, n in (("fp32", 12), ("fp64", 6)):
        fmt = FORMATS[name]
        prog = seq.Program(
            fmt,
            [seq.repeat(5),
             seq.alu(sf.OP_ADD, 0, 0, 0, 0, kc=True),
             seq.deposit(0),
             seq.endrep(), seq.halt()],
            consts=[sf.one_bits(fmt)], max_deposits=5)
        z = [sf.zero_bits(fmt)] * n
        await bench.program(fmt, prog, z, z, z, n, f"{name} repeat 5")

    # -- nested ----------------------------------------------------------
    nested = seq.Program(
        FP32,
        [seq.repeat(3),
         seq.repeat(4),
         seq.alu(sf.OP_ADD, 0, 0, 0, 0, kc=True),
         seq.endrep(),
         seq.deposit(0),
         seq.endrep(), seq.halt()],
        consts=[sf.one_bits(FP32)], max_deposits=3)
    z = [sf.zero_bits(FP32)] * 10
    want = await bench.program(FP32, nested, z, z, z, 10,
                               "fp32 nested repeat 3 x 4")
    assert want.counts[0] == 3, "the outer loop did not run three times"

    # three deep, so the loop stack is more than a flag
    deep = seq.Program(
        FP64,
        [seq.repeat(2), seq.repeat(2), seq.repeat(2),
         seq.alu(sf.OP_ADD, 0, 0, 0, 0, kc=True),
         seq.endrep(), seq.deposit(0), seq.endrep(), seq.endrep(),
         seq.halt()],
        consts=[sf.one_bits(FP64)], max_deposits=4)
    z = [sf.zero_bits(FP64)] * 5
    await bench.program(FP64, deep, z, z, z, 5, "fp64 repeat 2 x 2 x 2")

    # -- a loop nobody enters -------------------------------------------
    #
    # The loader refuses `repeat 0` - the doc says imm ITERATIONS, so
    # zero must mean zero - but the obvious RTL tests imm == 0 and
    # skips, and the model takes the same path so the two agree about a
    # program neither should accept. That agreement is worth checking.
    skipped = unchecked(
        FP32,
        [seq.encode(seq.REPEAT, ctrl=True, imm=0),
         seq.alu(sf.OP_ADD, 0, 0, 0, 0, kc=True),
         seq.deposit(0),
         seq.endrep(),
         seq.alu(sf.OP_ADD, 4, 0, 0, 0, kc=True),
         seq.deposit(4),
         seq.halt()],
        consts=[sf.one_bits(FP32)], max_deposits=2)
    z = [sf.zero_bits(FP32)] * 8
    want = await bench.program(FP32, skipped, z, z, z, 8,
                               "fp32 repeat 0 skips its body")
    assert want.counts == [1] * 8, (
        "the model ran a zero-trip body; the bench's own expectation is "
        "wrong before the RTL gets a say")

    # -- convergence -----------------------------------------------------
    for name, n, iters in (("fp32", 24, 8), ("fp64", 12, 6)):
        fmt = FORMATS[name]
        prog = escape_program(fmt, iters, sf.one_bits(fmt))
        a, b = seeds(fmt, n, 11), seeds(fmt, n, 12)
        want = await bench.program(fmt, prog, a, b, [0] * n, n,
                                   f"{name} escape map, {iters} iterations")
        assert 0 < sum(want.active) < n, (
            f"{name}: every lane converged the same way, so nothing "
            f"dropped out at a different iteration and the case proved "
            f"less than it claims; retune the seeds")
        assert len(set(want.counts)) > 1, (
            f"{name}: every lane made the same number of deposits")

    # -- everyone drops out on the first iteration -----------------------
    #
    # The extreme of the early exit: the rest of the loop is skipped
    # entirely. The deposits already made must survive it, and the
    # slots nobody reached must still be written as +0.
    fmt = FP32
    prog = escape_program(fmt, 20, sf.zero_bits(fmt))   # |z| < 0: never
    n = 8
    a = [sf.one_bits(fmt)] * n
    want = await bench.program(fmt, prog, a, [sf.zero_bits(fmt)] * n,
                               [0] * n, n, "fp32 every lane exits at once")
    assert not any(want.active)
    assert want.counts == [1] * n

    # -- an inactive lane contributes no flags ---------------------------
    #
    # The signaling NaN never reaches an active lane. If the mask
    # covered only register writes, the dead lanes would keep computing
    # on stale registers and push `invalid` into the sticky word.
    fmt = FP32
    quiet = seq.Program(
        fmt,
        [seq.alu(sf.OP_CMPLT, 3, 0, 0, kb=True),   # r0 < 0.0 -> false
         seq.setact(3),
         seq.repeat(4),
         seq.alu(sf.OP_ADD, 4, 1, 0, 1),           # would raise invalid
         seq.deposit(4),
         seq.endrep(), seq.halt()],
        consts=[sf.zero_bits(fmt)], max_deposits=4)
    n = 6
    want = await bench.program(
        fmt, quiet, [sf.one_bits(fmt)] * n, [sf.snan_bits(fmt, 1)] * n,
        [0] * n, n, "fp32 dead lanes raise nothing")
    assert want.flags == 0 and want.counts == [0] * n
    dut._log.info(f"loops and convergence: {bench.cases['program']} runs")


# ======================================================================
# 5. deposition
# ======================================================================

@cocotb.test()
async def deposition(dut):
    """The output window: overflow, the +0 of untouched slots, and a
    program that keeps all sixteen registers live.

    A slot no lane reached reads +0 and that is normative - a run whose
    untouched slots kept whatever the host buffer held would not be
    bit-exact, and two machines would disagree about memory neither
    computed. The bench stages POISON across the whole window before
    every run, so a slot that comes back +0 was written rather than
    lucky.
    """
    bench = Bench(dut)
    await bench.start()

    # -- overflow: the excess dropped, the prefix correct ----------------
    for name, n, cap, trips in (("fp32", 10, 2, 5), ("fp64", 6, 3, 7),
                                ("fp256", 2, 1, 4)):
        fmt = FORMATS[name]
        prog = seq.Program(
            fmt,
            [seq.repeat(trips),
             seq.alu(sf.OP_ADD, 0, 0, 0, 0, kc=True),
             seq.deposit(0),
             seq.endrep(), seq.halt()],
            consts=[sf.one_bits(fmt)], max_deposits=cap)
        z = [sf.zero_bits(fmt)] * n
        want = await bench.program(
            fmt, prog, z, z, z, n,
            f"{name} deposit overflow: {trips} pushes into {cap} slots")
        assert want.status & seq.STATUS_DEPOSIT_OVERFLOW
        assert want.counts == [cap] * n, "a lane deposited past the cap"

    # -- untouched slots ------------------------------------------------
    #
    # Half the lanes deposit twice and half deposit not at all, so the
    # +0 fill is checked beside real data rather than on its own.
    fmt = FP32
    n = 16
    prog = seq.Program(
        fmt,
        [seq.alu(sf.OP_CMPLT, 3, 0, 1),      # r3 = a < b
         seq.setact(3),
         seq.deposit(0), seq.deposit(1),
         seq.halt()],
        max_deposits=4)
    a = [sf.one_bits(fmt) if i % 2 else sf.zero_bits(fmt)
         for i in range(n)]
    b = [sf.one_bits(fmt)] * n
    want = await bench.program(fmt, prog, a, b, [0] * n, n,
                               "fp32 untouched slots read +0")
    assert set(want.counts) == {0, 2}, (
        "the case needs both a lane that deposited and a lane that did "
        "not, or the +0 fill is only checked where nothing else was")

    # -- every register live --------------------------------------------
    #
    # r0..r15, each written and then read by a later instruction, so a
    # register file that mirrored a port or dropped an index shows up.
    fmt = FP32
    n = 9
    insns = []
    for rd in range(3, 16):
        insns.append(seq.alu(sf.OP_ADD, rd, rd - 3, 0, rd - 1))
    insns.append(seq.alu(sf.OP_FMA, 0, 15, 14, 13))
    insns.append(seq.alu(sf.OP_FMA, 1, 12, 11, 10))
    insns.append(seq.alu(sf.OP_FMA, 2, 9, 8, 7))
    for rd in (0, 1, 2, 3, 7, 11, 15):
        insns.append(seq.deposit(rd))
    insns.append(seq.halt())
    prog = seq.Program(fmt, insns, max_deposits=7)
    await bench.program(fmt, prog, operands(fmt, n, 500),
                        operands(fmt, n, 501), operands(fmt, n, 502), n,
                        "fp32 r0..r15 all live")

    # the same shape at the widest rung, where the register file is one
    # lane per beat and an index slip is easiest to make
    n = 2
    prog = seq.Program(FP256, insns, max_deposits=7)
    await bench.program(FP256, prog, operands(FP256, n, 510),
                        operands(FP256, n, 511), operands(FP256, n, 512),
                        n, "fp256 r0..r15 all live")

    # -- the legal side of the deposit cap -------------------------------
    #
    # The refusal matrix proves max_deposits > MAXD is turned away; this
    # proves the comparison is a `>` and not a `>=`. MAXD slots for
    # eight lanes is a 2 KiB window drained from a buffer that is
    # exactly full, which is also the largest drain this bench runs.
    fmt, n = FP32, 8
    prog = seq.Program(
        fmt, [seq.alu(sf.OP_ADD, 4, 0, 1, 2), seq.deposit(4), seq.halt()],
        consts=[sf.one_bits(fmt)], max_deposits=MAXD)
    want = await bench.program(fmt, prog, operands(fmt, n, 520),
                               operands(fmt, n, 521), operands(fmt, n, 522),
                               n, f"fp32 max_deposits == MAXD ({MAXD})")
    assert want.counts == [1] * n, "one deposit per lane, MAXD-1 empty"
    dut._log.info(f"deposition: {bench.cases['program']} runs")


# ======================================================================
# 6. geometry
# ======================================================================

@cocotb.test()
async def geometry(dut):
    """n across every edge that exists: the beat, the lane block, and
    more than one block.

    A beat is 32 bytes at every format, so the lanes it holds - and
    therefore where the ragged tail falls - change with the rung. The
    sizes below straddle both edges on all four.
    """
    bench = Bench(dut)
    await bench.start()

    def short(fmt):
        return seq.Program(
            fmt,
            [seq.deposit(0),
             seq.alu(sf.OP_ADD, 4, 0, 0, 1),
             seq.deposit(4),
             seq.alu(sf.OP_MUL, 5, 4, 2),
             seq.deposit(5),
             seq.halt()],
            max_deposits=3)

    plan = {
        "fp32": [0, 1, 7, 8, 9, 127, 128, 129, 300],
        "fp64": [1, 3, 4, 5, 63, 64, 65, 150],
        "fp128": [1, 2, 3, 31, 32, 33, 70],
        "fp256": [1, 2, 15, 16, 17],
    }
    for name, ns in plan.items():
        fmt = FORMATS[name]
        prog = short(fmt)
        lpbeat, lpblock = lanes_per_beat(fmt), lanes_per_block(fmt)
        for n in ns:
            note = []
            if n and n % lpbeat == 0:
                note.append("beat edge")
            if n and n % lpblock == 0:
                note.append("block edge")
            if n > lpblock:
                note.append(f"{-(-n // lpblock)} blocks")
            await bench.program(
                fmt, prog, operands(fmt, n, 600 + n),
                operands(fmt, n, 700 + n), operands(fmt, n, 800 + n), n,
                f"{name} n={n}" + (f" ({', '.join(note)})" if note else ""))
    dut._log.info(f"geometry: {bench.cases['program']} runs across "
                  f"{sum(len(v) for v in plan.values())} sizes")


@cocotb.test()
async def actall_over_a_ragged_block(dut):
    """ACTALL at an n that does not fill its lane block: REPORTED, not
    asserted.

    seq.py's ACTALL sets every lane active, padding lanes included;
    SEQUENCER.md's padding argument - no value stays quiet through
    thirty iterations of an unknown map - wants them held out. The two
    readings agree on deposits and on counts, because a padding lane's
    slots are outside the window either way. They differ in FLAGS.

    That is a seam in the contract rather than a defect in the module,
    so this case asserts what both readings agree on and LOGS which
    one the FLAGS word matched. Every other ACTALL case in this bench
    runs block-aligned, where the question does not arise.
    """
    bench = Bench(dut)
    await bench.start()

    fmt = FP32
    n, lpb = 5, lanes_per_block(fmt)
    assert n % lpb, "the case needs a ragged block to say anything"
    prog = seq.Program(
        fmt,
        [seq.alu(sf.OP_CMPLT, 3, 0, 1),
         seq.setact(3),
         seq.actall(),
         seq.alu(sf.OP_MUL, 4, 0, 1),
         seq.deposit(4),
         seq.halt()],
        max_deposits=2)

    a = operands(fmt, n, 900)
    b = operands(fmt, n, 901)
    c = [0] * n
    want = seq.run(prog, a, b, c)

    ebytes = fmt.width // 8
    dep_bytes, cnt_bytes = n * prog.max_deposits * ebytes, 4 * n
    bench._stage(fmt, prog.to_bytes(), a, b, c, n, dep_bytes, cnt_bytes)

    def padded(base, vals):
        """The stream as the hardware's whole lane block sees it: the
        real values, then whatever the poison tail holds."""
        return list(vals) + [
            int.from_bytes(bench.ram.fetch(base + i * ebytes, ebytes),
                           "little") for i in range(n, lpb)]

    woken = seq.run(prog, padded(A_BASE, a), padded(B_BASE, b),
                    padded(C_BASE, c), n_active=n)

    bench._drive_cfg(fmt, n)
    refused, flags, err = await bench._go(
        bench._budget(fmt, prog, n, len(prog.to_bytes())), "ragged actall")
    assert refused == 0, "ragged actall: a valid program was refused"

    windows = [(D_BASE, dep_bytes, "deposit"), (CNT_BASE, cnt_bytes, "count")]
    bench.ram.assert_writes_inside(windows, "ragged actall")
    bench.ram.assert_guards(windows, "ragged actall")
    bench._compare(fmt, prog, n, want, flags, err, a, b, c,
                   "ragged actall", check_flags=False)

    held = want.flags
    if held == woken.flags:
        dut._log.info(f"ragged ACTALL: both readings agree on FLAGS "
                      f"({flags:#07b}); the case was not on the seam")
    elif flags == held:
        dut._log.info(
            f"ragged ACTALL: FLAGS {flags:#07b} - the module HOLDS "
            f"padding lanes out through ACTALL (SEQUENCER.md's reading). "
            f"seq.py, run over the padded array, would say "
            f"{woken.flags:#07b}.")
    elif flags == woken.flags:
        dut._log.warning(
            f"ragged ACTALL: FLAGS {flags:#07b} - the module lets ACTALL "
            f"WAKE padding lanes (seq.py's literal reading), so this "
            f"run's flags depend on buffer padding. SEQUENCER.md's "
            f"reading would say {held:#07b}. Worth settling in the "
            f"contract before it crosses a device boundary.")
    else:
        raise AssertionError(
            f"ragged ACTALL: FLAGS {flags:#07b} matches neither reading "
            f"of the contract - padding held out gives {held:#07b}, "
            f"padding woken gives {woken.flags:#07b}")

    # ACTALL where the block is full, so there is nothing to argue about
    n = lpb
    a = operands(fmt, n, 910)
    b = operands(fmt, n, 911)
    await bench.program(fmt, prog, a, b, [0] * n, n,
                        f"fp32 actall, block-aligned n={n}")
    n16 = lanes_per_block(FP256)
    await bench.program(FP256, seq.Program(FP256, prog.insns, [], 2),
                        operands(FP256, n16, 920), operands(FP256, n16, 921),
                        [0] * n16, n16,
                        f"fp256 actall, block-aligned n={n16}")


# ======================================================================
# 7. the fuzz
# ======================================================================

# (format, trials, ragged sizes, block-aligned size for ACTALL, and a
# static worst-case instruction cap). The cap is a RUNTIME bound, not a
# semantic one: a program's cost is lanes x instructions on both sides
# of the comparison, and the model's fp256 arithmetic is 236-bit
# integer work in Python. Narrower caps at the wide rungs keep the
# whole target inside a CI budget without narrowing what is covered -
# geometry and deposition already run fp256 directly.
FUZZ_PLAN = [
    ("fp32", 26, [1, 3, 7, 8, 9, 16, 17, 31, 33], 128, 600),
    ("fp64", 16, [1, 3, 4, 5, 7, 9, 15, 17, 31], 64, 500),
    ("fp128", 12, [1, 2, 3, 5, 7, 9, 15, 17], 32, 300),
    ("fp256", 8, [1, 2, 3, 5, 7, 9], 16, 150),
]


@cocotb.test()
async def fuzz_programs(dut):
    """Random valid programs from the model's own generator, on every
    rung, whole state compared.

    seq.random_program lives in the model rather than in a test file
    precisely so that every implementation is fuzzed over the same
    corpus - the model's property tests, libcft's cross-check, and now
    this. A generator private to this bench would compare two things
    neither of which is the thing under test.

    Programs are drawn until they pass validate() and their static
    worst-case instruction count fits the per-rung cap, which is a
    runtime bound rather than a semantic one. Sizes straddle the beat
    and lane block on each rung; a program containing ACTALL is run
    block-aligned, for the reason actall_over_a_ragged_block explains.
    """
    bench = Bench(dut)
    await bench.start()

    seen = Counter()
    loops = deposited = converged = overflowed = 0
    for name, trials, sizes, aligned, cap in FUZZ_PLAN:
        fmt = FORMATS[name]
        rng = random.Random(20260901 ^ (fmt.width * 7919))
        made = 0
        attempts = 0
        while made < trials and attempts < trials * 60:
            attempts += 1
            insns, consts = seq.random_program(fmt, rng)
            if worst_case_insns(insns) > cap:
                continue
            try:
                prog = seq.Program(fmt, insns, consts,
                                   rng.choice([1, 2, 4]))
            except seq.ProgramError:
                continue
            n = aligned if has_actall(insns) else rng.choice(sizes)
            a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
            want = await bench.program(
                fmt, prog, a, b, c, n,
                f"fuzz {name} #{made} n={n} "
                f"maxdep={prog.max_deposits}")
            made += 1
            seen[name] += 1
            if any(seq.decode(w)["ctrl"] and seq.decode(w)["op"] == seq.REPEAT
                   for w in insns):
                loops += 1
            if any(want.counts):
                deposited += 1
            if not all(want.active):
                converged += 1
            if want.status & seq.STATUS_DEPOSIT_OVERFLOW:
                overflowed += 1
        assert made == trials, (
            f"{name}: only {made} of {trials} programs were generated in "
            f"{attempts} attempts")

    total = sum(seen.values())
    dut._log.info(f"fuzz: {total} programs - " +
                  ", ".join(f"{k} {v}" for k, v in seen.items()))
    dut._log.info(f"      {loops} contained a loop, {deposited} deposited, "
                  f"{converged} had a lane drop out, {overflowed} "
                  f"overflowed the deposit window")
    assert total >= 60, f"only {total} programs were fuzzed"
    # A fuzz that never reached the interesting cases passes for the
    # wrong reason, so each of them is a gate on the run rather than a
    # statistic printed at the end.
    assert loops > total // 4, "hardly any fuzzed program contained a loop"
    assert deposited > total // 4, "hardly any fuzzed program deposited"
    assert converged > 0, "no fuzzed program ever dropped a lane"


# ======================================================================
# 8. the one that has to go last
# ======================================================================

@cocotb.test()
async def refuses_zero_max_deposits(dut):
    """`max_deposits == 0` must refuse, and this case is deliberately
    the LAST test in the file.

    It is the other half of the deposit-cap check in refusal_matrix,
    separated because of how it fails rather than because of what it
    tests. `max_deposits` sizes the drain: a module that accepts zero
    has a drain loop whose bound underflows, and the failure mode is
    not a wrong answer but a simulator that stops making progress.
    Every timeout this bench has is a SIMULATION-TIME timeout, and a
    simulation-time timeout cannot fire while the simulator is stuck
    inside one timestep - so a module with that defect takes down
    whatever runs after it, whatever that is.

    Putting it last means it is nothing. The other tests have already
    reported by the time it runs, and the only thing at risk is a
    result nobody was waiting on. Wrap the target in an external
    timeout (`timeout 900 make seq_core`) if a hang would block a
    pipeline; that is the only guard that works from outside a
    livelock, and it is a CI setting rather than a bench one.
    """
    bench = Bench(dut)
    await bench.start()
    body = [seq.alu(sf.OP_ADD, 4, 0, 1, 2), seq.deposit(4), seq.halt()]
    await bench.refuse(
        FP32, raw_image(FP32, body, [sf.one_bits(FP32)], max_deposits=0),
        "max_deposits 0 shapes an output buffer of nothing")
