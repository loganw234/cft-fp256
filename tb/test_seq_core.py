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

import os
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
LATENCY = 16
NBEATS = 16
# The pass budget the DUT was built with, for the cycle budgets only:
# the multi-cycle targets export it, the default is the shipping tile.
MUL_PASSES = int(os.getenv("CFT_MUL_PASSES", "1"))
MAXD = 64
IMEM_D = 1024
# 256 -> 512 at revision 3 (R7): the ninth kx index bit made the
# second half of the bank reachable, and cft_seq's DEFAULT moved with
# it because tb/test_krnl.py holds cft_krnl's SEQ_KIDX_W against it.
KMEM_D = 512
# Scratch slots a lane (revision 3, R4), and the reduction the indexed
# forms apply. A power of two by construction.
SCRATCH_D = 256
# Registers a lane owns, and so the register file's depth (revision 2:
# 16 -> 32). It appears here only in the CYCLE BUDGET: cft_seq wipes
# the whole file once per lane block, so the doubling is 256 more
# cycles of fixed cost per block and a budget that did not know about
# it timed the geometry suite out at n=300. A bound, not a value under
# test - but a bound written from the parameter rather than as a
# number, because the last one was a number and this is what happened.
REGS = 32
RF_D = REGS * NBEATS

CLK_NS = 4

# One memory, generously spaced. The deposit region is last and has
# the rest of the RAM behind it, because it is the only region whose
# size grows with max_deposits.
RAM_BYTES = 1 << 22
PROG_BASE = 0x00_1000
# The per-run constant bank (revision 2 R3), in its own region well
# away from the image: BANK_EXT exists precisely so the two are
# separate buffers, and a FETCH that quietly read the constants from
# the image would pass every check here if they shared a region.
BANK_BASE = 0x00_8000
A_BASE = 0x01_0000
B_BASE = 0x02_0000
C_BASE = 0x03_0000
CNT_BASE = 0x04_0000
# The two scratch blocks (revision 3, R5), each in its own region and
# each far from the other four for the reason BANK_BASE is far from
# the image: a preload that quietly read the A stream, or a drain that
# quietly overwrote the counts, would pass every check here if the
# regions overlapped.
SIN_BASE = 0x05_0000
SOUT_BASE = 0x08_0000
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
    # __init__ is skipped deliberately, so every field it would have
    # set is set here. These two arrived with revision 2 and `run()`
    # reads both on entry: without them the bypass raises instead of
    # running, and a case that exists to execute an unloadable program
    # would fail for the wrong reason.
    p.flags = 0
    p._n_consts = len(p.consts)
    # Revision 3 adds two more `run()` reads on entry, on the same
    # terms.
    p.n_scratch_in = 0
    p.n_scratch_out = 0
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
                     "cfg_prog", "cfg_bank", "cfg_sin", "cfg_sout",
                     "cfg_cnt"):
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

    def _stage(self, fmt, image, a, b, c, n, dep_bytes, cnt_bytes,
               bank=None, scratch_in=None):
        ram = self.ram
        ram.poison()
        ram.stage(PROG_BASE, image)
        ebytes = fmt.width // 8
        if bank is not None:
            # Laid out exactly as an image's constant section is -
            # dense, format-width, little-endian - which is what lets
            # FETCH read one the way it reads the other.
            ram.stage(BANK_BASE, b"".join(
                int(v).to_bytes(ebytes, "little") for v in bank))
        if scratch_in is not None:
            # Lane-major and dense, in the same encoding: lane i's slot
            # s at element i * n_scratch_in + s.
            ram.stage(SIN_BASE, b"".join(
                int(v).to_bytes(ebytes, "little") for v in scratch_in))
        for base, vals in ((A_BASE, a), (B_BASE, b), (C_BASE, c)):
            ram.stage(base, b"".join(
                int(v).to_bytes(ebytes, "little") for v in vals))
        assert D_BASE + dep_bytes + GUARD <= ram.size, (
            "the deposit window does not fit the model RAM; shrink n or "
            "max_deposits for this case")
        assert CNT_BASE + cnt_bytes + GUARD <= D_BASE

    def _drive_cfg(self, fmt, n, bank_ptr=None, scratch=False):
        dut = self.dut
        dut.cfg_prec.value = PREC_CODE[fmt.name]
        dut.cfg_n.value = n
        dut.cfg_a.value = A_BASE
        dut.cfg_b.value = B_BASE
        dut.cfg_c.value = C_BASE
        dut.cfg_d.value = D_BASE
        dut.cfg_prog.value = PROG_BASE
        dut.cfg_cnt.value = CNT_BASE
        # Poisoned unless this run supplies a bank: a program without
        # flags.BANK_EXT must never read the pointer, and aiming it at
        # an address with no constants at it is how that is CHECKED
        # rather than asserted.
        dut.cfg_bank.value = BANK_BASE if bank_ptr else 0xDEAD_0000
        # ...and the same for the two scratch pointers, which a program
        # without flags.SCRATCH_IO must never read OR WRITE. The write
        # one matters more: a run that wrote a scratch-out block it was
        # not asked for would land on a host buffer that does not exist,
        # and here it lands on the write logger's window assertion.
        dut.cfg_sin.value = SIN_BASE if scratch else 0xDEAD_1000
        dut.cfg_sout.value = SOUT_BASE if scratch else 0xDEAD_2000

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
                      *, check_flags=True, image=None, bank=None,
                      scratch_in=None):
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

        want = seq.run(prog, list(a), list(b), list(c), bank=bank,
                       scratch_in=scratch_in)
        sout_bytes = n * prog.n_scratch_out * ebytes

        self._stage(fmt, image, a, b, c, n, dep_bytes, cnt_bytes, bank=bank,
                    scratch_in=scratch_in)
        self._padding_selfcheck(fmt, prog, a, b, c, n, want, label,
                                bank=bank, scratch_in=scratch_in)
        self._drive_cfg(fmt, n, bank_ptr=bank is not None,
                        scratch=prog.scratch_io)

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
        if sout_bytes:
            windows.append((SOUT_BASE, sout_bytes, "scratch-out"))
        self.ram.assert_writes_inside(windows, label)
        self.ram.assert_guards(windows, label)

        self._compare(fmt, prog, n, want, flags, err, a, b, c, label,
                      check_flags)
        self._compare_scratch_out(fmt, prog, n, want, label)
        self.cases["program"] += 1
        return want

    def _budget(self, fmt, prog, n, image_bytes):
        blocks = max(1, -(-n // lanes_per_block(fmt)))
        worst = worst_case_insns(prog.insns)
        # On the multi-cycle tile (tb/Makefile seq_coremc, MUL_PASSES
        # through CFT_MUL_PASSES) the array takes a beat and returns a
        # result every pass period instead of every cycle, so the
        # per-instruction cost of a block scales by the budget - the
        # widest rung's period is the budget itself, and using it for
        # every rung keeps this a bound rather than a fit.
        # A scratch LOAD is five cycles a beat - the register file's
        # two, the scratch's own two, and the write-back - and it does
        # not go near the array, so the pass budget does not pace it.
        # At NBEATS 16 that is 80 cycles, more than an ALU instruction
        # costs at MUL_PASSES 1, so the per-instruction term is the
        # larger of the two rather than the ALU's alone.
        per_insn = max((NBEATS + LATENCY) * MUL_PASSES + 8, 5 * NBEATS + 8)
        # ...and the per-block fixed cost gains the scratch wipe, which
        # cft_seq sizes from what the program can reach: every slot if
        # it indexes, otherwise the highest static slot it names and
        # the slots the scratch-out drain will read. A program that
        # names none wipes none, which is why every case that predates
        # revision 3 has exactly the budget it had.
        slots, indexed = 0, False
        for word in prog.insns:
            d = seq.decode(word)
            if not d["ctrl"]:
                continue
            if d["op"] in (seq.STL, seq.LDL):
                slots = max(slots, (d["imm"] & seq.SCRATCH_SLOT_MASK) + 1)
            elif d["op"] in (seq.STX, seq.LDX):
                indexed = True
        nsin = prog.n_scratch_in if prog.scratch_io else 0
        nsout = prog.n_scratch_out if prog.scratch_io else 0
        wipe = SCRATCH_D if indexed else max(slots, nsout)
        # Per block: the register-file wipe (RF_D cycles, the whole
        # file, so that the previous block cannot leak), the scratch
        # wipe, the scratch-in preload (an element a cycle plus its
        # beats), the three operand streams, the instructions, the
        # deposit drain, and the scratch-out drain.
        #
        # The two DRAINS are counted per element rather than folded
        # into the fixed term they used to hide in. Each visits (lane,
        # slot) at three cycles an element plus a send per beat, so a
        # block of 128 lanes at three deposits apiece is 1,152 cycles -
        # more than the whole fixed term. That was covered by accident
        # while every multi-block case deposited once; the first case
        # to run three lane blocks with three deposits and three
        # scratch slots landed within 1% of the bound.
        blk = min(n, lanes_per_block(fmt))
        cycles = (3000 + (image_bytes // BEAT_BYTES + 8) * 8
                  + blocks * (worst * per_insn
                              + RF_D + wipe * NBEATS
                              + blk * nsin * 2 + 64
                              + blk * nsout * 4 + 64
                              + blk * prog.max_deposits * 4 + 64
                              + 6 * NBEATS + 400))
        return min(cycles, 8_000_000)

    def _compare_scratch_out(self, fmt, prog, n, want, label):
        """The block the run hands back through SCRATCH_OUT_PTR, against
        the model's, element for element.

        A program that declares NO scratch output must leave the region
        entirely alone; the write-window assertion above already says
        so by address, and this says it again by content, because a
        write of the right bytes to the right place is not the same
        claim as a write that never happened."""
        nsout = prog.n_scratch_out if prog.scratch_io else 0
        ebytes = fmt.width // 8
        if not nsout:
            assert self.ram.fetch(SOUT_BASE, 1024) == bytes([POISON]) * 1024, \
                (f"{label}: the scratch-out region was written by a run "
                 f"whose program declares none")
            return
        got = self.ram.fetch(SOUT_BASE, n * nsout * ebytes)
        bad = 0
        for idx in range(n * nsout):
            g = int.from_bytes(got[idx * ebytes:(idx + 1) * ebytes],
                               "little")
            if g == want.scratch_out[idx]:
                continue
            bad += 1
            if bad <= 8:
                lane, slot = divmod(idx, nsout)
                self.dut._log.error(
                    f"{label}: scratch_out[lane {lane} slot {slot}] "
                    f"(element {idx}, {SOUT_BASE + idx * ebytes:#x}) "
                    f"got {g:#x} want {want.scratch_out[idx]:#x}")
        assert bad == 0, (
            f"{label}: {bad}/{n * nsout} scratch-out elements differ from "
            f"the model. n_scratch_in={prog.n_scratch_in} "
            f"n_scratch_out={nsout} n={n} "
            f"program={[hex(w) for w in prog.insns]}")
        self.cases["scratch_out"] += 1

    def _padding_selfcheck(self, fmt, prog, a, b, c, n, want, label,
                           bank=None, scratch_in=None):
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

        # The scratch-in block is sized by the model's OWN lane count,
        # so the padded re-run needs the padding lanes' slots appended -
        # and they must be read as +0, because the tile's element count
        # is blk_n * n_scratch_in and its stream simply ends before
        # they would begin.
        nsin = prog.n_scratch_in if prog.scratch_io else 0
        pad_sin = (list(scratch_in) + [0] * ((padded - n) * nsin)
                   if nsin else None)
        pad = seq.run(prog, stream(A_BASE, a), stream(B_BASE, b),
                      stream(C_BASE, c), bank=bank, scratch_in=pad_sin,
                      n_active=n)
        nsout = prog.n_scratch_out if prog.scratch_io else 0
        same = (pad.deposits[:n * prog.max_deposits] == want.deposits
                and pad.counts[:n] == want.counts
                and pad.scratch_out[:n * nsout] == want.scratch_out
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
        # Revision 4's R8. Checked here rather than only in the directed
        # case, so every program this file runs - both fuzz corpora
        # included - holds the tile to the model on it.
        want_rng = bool(want.status & seq.STATUS_SCRATCH_RANGE)
        assert bool(err & 0x10) == want_rng, (
            f"{label}: err[4] (scratch index past the depth -> STATUS[5]) "
            f"is {bool(err & 0x10)}, model says {want_rng}. The flag is "
            f"{'set' if prog.flags & seq.FLAG_SCRATCH_STRICT else 'clear'}; "
            f"with it clear the index is reduced modulo the depth and this "
            f"bit must never be raised.")
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

    # A constant region LONGER THAN ONE BEAT, at every element size.
    #
    # This is the image-parse path rather than the operand mux, and
    # until 2026-09-07 nothing reached it: every case above and the
    # whole fuzz corpus carry four constants or fewer, which is 16
    # bytes at fp32 and never crosses a 32-byte beat. The parser peels
    # one field per cycle and raises `rready` only when the window is
    # too empty to peel again, so the condition that decides "too
    # empty" has to be the size of the NEXT field. It was 8 bytes for
    # every element size, which is right at fp64 and wider and one
    # beat too eager at fp32: the window still held four bytes, the
    # parser peeled instead of absorbing, and the beat the memory had
    # already handed over on that cycle's handshake fell on the floor.
    # A program whose bank spans two beats then starved forever.
    #
    # The bank is deliberately larger than the sixteen an operand
    # field can name, which is legal and always was - the extra
    # constants are simply unaddressable without `kx`. That keeps this
    # case about the PARSER and not about the addressing mode.
    for name, n, count in (("fp32", 9, 40), ("fp64", 6, 20),
                           ("fp128", 4, 12), ("fp256", 2, 6)):
        fmt = FORMATS[name]
        ebytes = fmt.width // 8
        assert count * ebytes > BEAT_BYTES, (
            f"{name}: {count} constants fit in one beat, so this case "
            f"does not reach the path it exists for")
        bank = [(i * 0x0303_0303 + 0x21) & ((1 << fmt.width) - 1)
                for i in range(count)]
        top = min(seq.KADDR_PLAIN, count) - 1
        prog = seq.Program(
            fmt,
            [seq.alu(sf.OP_IOR, 4, ra=5, rb=top, kb=True),  # the last
             seq.deposit(4),                                # addressable
             seq.alu(sf.OP_IOR, 5, ra=5, rb=0, kb=True),    # ...and the
             seq.deposit(5),                                # first
             seq.halt()],
            consts=bank, max_deposits=2)
        await bench.program(fmt, prog, operands(fmt, n, 430),
                            operands(fmt, n, 431), operands(fmt, n, 432),
                            n, f"{name} {count} constants, "
                               f"{count * ebytes} bytes over "
                               f"{-(-count * ebytes // BEAT_BYTES)} beats")

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
# 8. indexed constants and IMUL (2026-09-07)
# ======================================================================

@cocotb.test()
async def indexed_constants_and_imul(dut):
    """The two additions of docs/ATLAS.md's "what the program model
    lacks", through the whole module rather than through the lane.

    `kx` (instruction bit 30, formerly reserved-must-be-zero) moves the
    three constant indices into imm[7:0], imm[15:8] and imm[23:16], so
    the addressable bank grows from sixteen to KMEM_D. Three things
    have to be true of the RTL for that to be a widening rather than a
    change, and each has its own case here:

      * a constant ABOVE fifteen reaches the operand it names. This is
        the whole feature, and it is the one thing no program could
        express before, so nothing already in this file covers it;
      * the same program written both ways computes the same thing.
        Below sixteen the two encodings are two spellings of one
        operation, and a module that muxed the index wrongly would
        still pass every case above by reading `ra` when it should
        read `imm`;
      * a bank the run never wrote is never read. A program whose
        n_consts is far below KMEM_D leaves most of the memory
        undefined, and the operand mux must not depend on it.

    IMUL rides along here rather than in its own suite because the
    sequencer's obligation for a new opcode is exactly the one P1
    states - steer the operands to the lane and put the answer back -
    and `lowbias32`, the draw hash the opcode exists for, is a program
    that exercises the steering under five instructions of dependency.

    Everything is scored the standard way: seq.run() over the same
    program and the same bits, whole machine compared.
    """
    bench = Bench(dut)
    await bench.start()

    # A bank as deep as the RTL will store, with every entry distinct
    # and its own index in the low bits: a mis-indexed read then
    # produces a value that names the slot it came from.
    def deep_bank(fmt, count):
        mask = (1 << fmt.width) - 1
        return [((i * 0x0101_0101_0101_0101) ^ (i << 3) ^ 0x11) & mask
                for i in range(count)]

    # -- 1. an index above fifteen, on each of the three operand ports
    for name, n in (("fp32", 12), ("fp64", 8), ("fp256", 3)):
        fmt = FORMATS[name]
        bank = deep_bank(fmt, KMEM_D)
        assert len(set(bank)) == len(bank), "the bank must be distinguishable"
        prog = seq.Program(
            fmt,
            [seq.alu(sf.OP_IOR, 4, ra=KMEM_D - 1, rb=5, rc=5,
                     ka=True, kx=True),
             seq.deposit(4),
             seq.alu(sf.OP_IOR, 5, ra=5, rb=16, rc=5, kb=True, kx=True),
             seq.deposit(5),
             seq.alu(sf.OP_SELECT, 6, ra=0, rb=1, rc=200, kc=True, kx=True),
             seq.deposit(6),
             seq.alu(sf.OP_IXOR, 7, ra=17, rb=131, rc=0,
                     ka=True, kb=True, kx=True),
             seq.deposit(7),
             seq.halt()],
            consts=bank, max_deposits=4)
        # the case is only meaningful if the indices are past the old
        # ceiling, which no four-bit field could have named
        for w in prog.insns:
            d = seq.decode(w)
            if d["ctrl"]:
                continue
            assert any(is_k and idx >= 16 for idx, is_k in seq.sources(d)), \
                "an instruction here names no constant past fifteen"
        await bench.program(fmt, prog, operands(fmt, n, 900),
                            operands(fmt, n, 901), operands(fmt, n, 902),
                            n, f"{name} kx: constants 16..{KMEM_D - 1}")

        # -- 1b. revision 3's NINTH index bit, on all three ports at
        # once. imm[28], imm[29] and imm[30] are ka's, kb's and kc's,
        # so an index past 255 uses a different bit on each port and a
        # decode that wired one of the three to the wrong operand
        # produces the right answer twice and the wrong one once.
        # These indices are the whole point of R7: a revision-2 tile
        # reads eight bits and would answer with constant 5 where the
        # program meant 261.
        deep = seq.Program(
            fmt,
            [seq.alu(sf.OP_IOR, 8, ra=KMEM_D - 1, rb=5, rc=5,
                     ka=True, kx=True),
             seq.deposit(8),
             seq.alu(sf.OP_IOR, 9, ra=5, rb=261, rc=5, kb=True, kx=True),
             seq.deposit(9),
             seq.alu(sf.OP_SELECT, 10, ra=0, rb=1, rc=256,
                     kc=True, kx=True),
             seq.deposit(10),
             seq.alu(sf.OP_IXOR, 11, ra=300, rb=511, rc=0,
                     ka=True, kb=True, kx=True),
             seq.deposit(11),
             seq.halt()],
            consts=bank, max_deposits=4)
        for w in deep.insns:
            d = seq.decode(w)
            if d["ctrl"]:
                continue
            assert any(is_k and idx >= 256 for idx, is_k in seq.sources(d)), \
                "an instruction here names no constant past 255, so the " \
                "ninth index bit is not under test"
        await bench.program(fmt, deep, operands(fmt, n, 910),
                            operands(fmt, n, 911), operands(fmt, n, 912),
                            n, f"{name} kx9: constants 256..{KMEM_D - 1}")

    # -- 2. the two encodings agree where both can express the operand
    for name, n in (("fp32", 9), ("fp128", 4)):
        fmt = FORMATS[name]
        bank = deep_bank(fmt, 16)
        body = [(sf.OP_FMA, 4, 0, 3, 2), (sf.OP_MUL, 5, 0, 11, 2),
                (sf.OP_IMUL, 6, 0, 7, 0), (sf.OP_SELECT, 7, 0, 1, 15)]
        for use_kx in (False, True):
            prog = seq.Program(
                fmt,
                [seq.alu(op, rd, ra, rb, rc, kb=True, kx=use_kx)
                 for op, rd, ra, rb, rc in body]
                + [seq.deposit(4), seq.deposit(5), seq.deposit(6),
                   seq.deposit(7), seq.halt()],
                consts=bank, max_deposits=4)
            await bench.program(fmt, prog, dense(fmt, n, 910),
                                dense(fmt, n, 911), dense(fmt, n, 912), n,
                                f"{name} {'kx' if use_kx else 'plain'} "
                                f"form over the low sixteen")

    # -- 3. a shallow bank in a deep memory: the slots past n_consts are
    #       never written by this run and must never be read either
    for name, n in (("fp64", 8),):
        fmt = FORMATS[name]
        prog = seq.Program(
            fmt,
            [seq.alu(sf.OP_ADD, 4, ra=0, rb=0, rc=2, kc=True, kx=True),
             seq.deposit(4), seq.halt()],
            consts=deep_bank(fmt, 3), max_deposits=1)
        await bench.program(fmt, prog, operands(fmt, n, 920),
                            operands(fmt, n, 921), operands(fmt, n, 922),
                            n, f"{name} kx over a three-entry bank")

    # -- 4. IMUL, and the hash it exists for
    K1, K2 = 0x7FEB352D, 0x846CA68B          # atlas-engine's lowbias32
    for name, n in (("fp32", 12), ("fp64", 8), ("fp128", 4), ("fp256", 2)):
        fmt = FORMATS[name]
        prog = seq.Program(
            fmt, [seq.alu(sf.OP_IMUL, 4, 0, 1), seq.deposit(4), seq.halt()],
            max_deposits=1)
        await bench.program(fmt, prog, operands(fmt, n, 930),
                            operands(fmt, n, 931), operands(fmt, n, 932),
                            n, f"{name} imul on stream operands")

    fmt = FP32
    prog = seq.Program(
        fmt,
        [seq.alu(sf.OP_ISHR, 1, 0, 0, kb=True),        # r1 = x >> 16
         seq.alu(sf.OP_IXOR, 0, 0, 1),
         seq.alu(sf.OP_IMUL, 0, 0, 2, kb=True),        # x *= 0x7feb352d
         seq.alu(sf.OP_ISHR, 1, 0, 1, kb=True),        # r1 = x >> 15
         seq.alu(sf.OP_IXOR, 0, 0, 1),
         seq.alu(sf.OP_IMUL, 0, 0, 3, kb=True),        # x *= 0x846ca68b
         seq.alu(sf.OP_ISHR, 1, 0, 0, kb=True),        # r1 = x >> 16
         seq.alu(sf.OP_IXOR, 0, 0, 1),
         seq.deposit(0), seq.halt()],
        consts=[16, 15, K1, K2], max_deposits=1)
    n = 16
    seeds_ = [i * 0x9E3779B1 & 0xFFFFFFFF for i in range(n)]
    want = seq.run(prog, seeds_, [0] * n, [0] * n)
    assert want.flags == 0, "the draw stream must not signal"
    assert len(set(want.deposits)) == n, (
        "the hash collapsed these seeds, so this case would pass on a "
        "module that computed nothing")
    await bench.program(fmt, prog, seeds_, [0] * n, [0] * n, n,
                        "fp32 lowbias32 as a program")

    # -- 5. the version guard, from the hardware's side. The loader
    #       refuses a kx program to an old library; an old TILE has no
    #       such rule, so what protects it is the CAPS bit the library
    #       will read - not anything this module does. Stated here as a
    #       fact about the RTL rather than left implied: this module
    #       executes bit 30 and does not refuse it.
    fmt = FP32
    word = seq.alu(sf.OP_ADD, 4, ra=0, rb=200, rc=0, kb=True, kx=True)
    assert (word >> 30) & 1

    dut._log.info("indexed constants and imul: %d runs",
                  bench.cases["program"])




# ======================================================================
# 9. revision 2: five-bit register fields, the per-run constant bank
# ======================================================================

@cocotb.test()
async def wide_registers(dut):
    """R1: a lane owns 32 registers, and the fifth bit of each field
    lives in imm[27:24].

    The file doubled, its read and write addresses grew a bit, and the
    beat index moved from a fixed four bits to NBSH. What could go
    wrong is aliasing - r20 landing on r4 - and aliasing is invisible
    to a program that names only one of any colliding pair. So every
    case here names BOTH halves and puts different values in them:

      * a chain that walks r0 -> r16 -> r1 -> r17 -> ..., so a file
        whose high addresses folded onto the low ones would overwrite a
        value it is about to read;
      * a deposit from a high register that was never written, which
        must be +0 exactly as r3..r15 are;
      * the fuzz generator's wide arm, which draws destinations and
        sources from all 32 across four rungs.
    """
    bench = Bench(dut)
    await bench.start()

    # -- 1. low and high halves interleaved, on every rung
    for name, n in (("fp32", 16), ("fp64", 8), ("fp128", 4), ("fp256", 2)):
        fmt = FORMATS[name]
        body = []
        # r16 = a + c; then alternate halves, each step reading the
        # previous two, so nothing can be dropped without changing the
        # answer.
        body.append(seq.alu(sf.OP_ADD, 16, ra=0, rc=2))
        body.append(seq.alu(sf.OP_MUL, 4, ra=16, rb=1))
        pairs = [(17, 5), (24, 6), (31, 7), (20, 12)]
        prev_hi, prev_lo = 16, 4
        for hi, lo in pairs:
            body.append(seq.alu(sf.OP_ADD, hi, ra=prev_hi, rc=prev_lo))
            body.append(seq.alu(sf.OP_MUL, lo, ra=hi, rb=prev_hi))
            prev_hi, prev_lo = hi, lo
        body += [seq.deposit(prev_hi), seq.deposit(prev_lo),
                 seq.deposit(29),          # never written: must be +0
                 seq.halt()]
        prog = seq.Program(fmt, body, max_deposits=3)
        # the case is only meaningful if it really names the high half
        named = set()
        for w in prog.insns:
            d = seq.decode(w)
            named |= {d["rd"], d["ra"], d["rb"], d["rc"]}
        assert max(named) >= 16, "no register above fifteen is named"
        await bench.program(fmt, prog, operands(fmt, n, 1100),
                            operands(fmt, n, 1101), operands(fmt, n, 1102),
                            n, f"{name} r16..r31 interleaved with r0..r15")

    # -- 2. the fuzz generator's wide arm
    #
    # Same generator, same corpus shape, `wide_regs` on - which draws
    # every register from 0..31 instead of 0..15 and draws exactly as
    # many values from `rng`, so this is the existing fuzz aimed at the
    # other half of the file rather than a different fuzz.
    made = 0
    for name, trials, n in (("fp32", 8, 16), ("fp64", 5, 8),
                            ("fp256", 3, 2)):
        fmt = FORMATS[name]
        rng = random.Random(20260908 ^ (fmt.width * 7919))
        got = 0
        attempts = 0
        while got < trials and attempts < trials * 60:
            attempts += 1
            insns, consts = seq.random_program(fmt, rng, wide_regs=True)
            if worst_case_insns(insns) > 400:
                continue
            if has_actall(insns):
                continue          # ragged-block seam; covered elsewhere
            try:
                prog = seq.Program(fmt, insns, consts,
                                   rng.choice([1, 2, 4]))
            except seq.ProgramError:
                continue
            a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
            await bench.program(fmt, prog, a, b, c, n,
                                f"wide-register fuzz {name} #{got}")
            got += 1
            made += 1
        assert got == trials, (
            f"{name}: only {got} of {trials} wide-register programs were "
            f"generated in {attempts} attempts")
    assert made >= 16, f"only {made} wide-register programs were fuzzed"
    dut._log.info(f"wide registers: {made} fuzzed programs drawing from "
                  f"r0..r{seq.NREG - 1}")


@cocotb.test()
async def constant_bank_per_run(dut):
    """R3: a BANK_EXT image carries no constant section, and its
    constants arrive per run from BANK_PTR.

    FETCH becomes two passes - the bank, then the instructions from
    cfg_prog + 32 - so what has to be true is that the two land in the
    right memories and that the second does not disturb the first.
    Three cases:

      * the SAME image run twice with different banks gives two
        different answers, each equal to what the self-contained
        program with those constants inlined gives. One run would only
        prove the pointer is read; two prove the answer follows it;
      * a bank that reaches past the plain form's sixteen, through
        `kx`, because the two features have to compose;
      * an ordinary image still runs with BANK_PTR aimed at rubbish -
        the negative half, arranged by _drive_cfg on every run without
        a bank.
    """
    bench = Bench(dut)
    await bench.start()

    def values(fmt, seed):
        rng = random.Random(seed)
        pool = [sf.zero_bits(fmt), sf.zero_bits(fmt, 1), sf.one_bits(fmt),
                sf.inf_bits(fmt), sf.qnan_bits(fmt),
                sf.min_subnormal_bits(fmt), sf.max_normal_bits(fmt)]
        return pool

    # -- 1. one image, two banks, on every rung
    for name, n in (("fp32", 16), ("fp64", 8), ("fp128", 4), ("fp256", 2)):
        fmt = FORMATS[name]
        body = [seq.alu(sf.OP_MUL, 17, ra=0, rb=1),
                seq.alu(sf.OP_ADD, 18, ra=17, rc=0, kc=True),
                seq.deposit(18),
                seq.alu(sf.OP_ADD, 19, ra=18, rc=3, kc=True),
                seq.deposit(19),
                seq.halt()]
        ext = seq.Program(fmt, body, flags=seq.FLAG_BANK_EXT, n_consts=4,
                          max_deposits=2)
        image = ext.to_bytes()
        assert len(image) == 32 + 8 * len(body), (
            "a BANK_EXT image is header then instructions; if it still "
            "carried the constants there would be nothing for BANK_PTR "
            "to do")
        pool = values(fmt, 0)
        for tag, bank in (("A", pool[:4]), ("B", pool[3:7])):
            await bench.program(fmt, ext, operands(fmt, n, 1200),
                                operands(fmt, n, 1201),
                                operands(fmt, n, 1202), n,
                                f"{name} BANK_EXT bank {tag}", bank=bank)
        # ...and the self-contained program with bank A inlined must
        # agree with the BANK_EXT run of bank A, which is what makes
        # "where the constants live" a non-observable.
        inline = seq.Program(fmt, body, consts=pool[:4], max_deposits=2)
        await bench.program(fmt, inline, operands(fmt, n, 1200),
                            operands(fmt, n, 1201),
                            operands(fmt, n, 1202), n,
                            f"{name} the same constants, inlined")

    # -- 2. a bank reached through kx, past the plain form's sixteen
    fmt = FORMATS["fp32"]
    mask = (1 << fmt.width) - 1
    deep = [((i * 0x0101_0101) ^ (i << 3) ^ 0x11) & mask for i in range(40)]
    ext = seq.Program(
        fmt,
        [seq.alu(sf.OP_IXOR, 21, ra=0, rb=39, kb=True, kx=True),
         seq.deposit(21),
         seq.alu(sf.OP_IOR, 22, ra=21, rb=16, kb=True, kx=True),
         seq.deposit(22),
         seq.halt()],
        flags=seq.FLAG_BANK_EXT, n_consts=40, max_deposits=2)
    await bench.program(fmt, ext, operands(fmt, 16, 1210),
                        operands(fmt, 16, 1211), operands(fmt, 16, 1212),
                        16, "fp32 BANK_EXT reached through kx", bank=deep)

    # -- 3. the header refusals revision 2 adds. The 0x600 tile checked
    # NEITHER reserved word; this one checks both, which is what makes
    # an image built for a later revision thrown back rather than
    # half-understood.
    body = [seq.alu(sf.OP_ADD, 4, 0, 1, 2), seq.halt()]
    # flags[1] became SCRATCH_IO at revision 3 and is now IMPLEMENTED,
    # so the first unknown bit moved up to [2]. The scratch cases below
    # carry the positive control for [1]; here what matters is that the
    # rule still bites on the first bit this tile does not know.
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(1 << 3, 0)),
        "header flags[3]: a flag bit this tile does not implement")
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(1 << 31, 0)),
        "header flags[31]: the top of the same word")
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(0, 1)),
        "header word 7 without flags.SCRATCH_IO: still reserved")
    # The positive control: flags[0] is BANK_EXT and IS implemented, so
    # the identical mechanism must not refuse it. Without this a tile
    # that refused every non-zero flags word would pass all three above.
    await bench.program(
        fmt,
        seq.Program(fmt, [seq.alu(sf.OP_ADD, 23, ra=0, rc=0, kc=True),
                          seq.deposit(23), seq.halt()],
                    flags=seq.FLAG_BANK_EXT, n_consts=1, max_deposits=1),
        operands(fmt, 16, 1220), operands(fmt, 16, 1221),
        operands(fmt, 16, 1222), 16,
        "fp32 BANK_EXT is a KNOWN flag", bank=[sf.one_bits(fmt)])




# ======================================================================
# 10. revision 3: the per-lane scratch and its per-run block
# ======================================================================

def _int_bits(fmt, v):
    """An integer as a format-width bit pattern - the shape the atlas
    emitter keeps a loop counter in, and what STX/LDX reduce."""
    return int(v) & ((1 << fmt.width) - 1)


@cocotb.test()
async def scratch_static_and_indexed(dut):
    """R4: STL/LDL by slot, STX/LDX by register, on every rung.

    Four things have to be true, and each is arranged to fail loudly
    on its own:

      * a value stored and loaded back comes back UNCHANGED, including
        at the highest slot the depth allows - the one an off-by-one in
        the address decode reaches past;
      * a slot no lane wrote reads +0, which is normative for the same
        reason an untouched deposit slot is;
      * the indexed forms take the slot from the LOW log2(SCRATCH_D)
        bits of rb, reduced modulo the depth rather than refused, so
        lanes whose indices differ by whole multiples of the depth
        collide on one slot;
      * lane i's slot s is lane i's alone - the scratch is beat-wide
        storage, so a beat's lanes writing DIVERGENT indexed slots is
        exactly the case a shared address would get wrong, and the
        streams below give every lane a different index.

    Neither form is arithmetic, so FLAGS must stay whatever the rest of
    the program made it; every case here is scored on the whole machine
    against seq.py, FLAGS included.
    """
    bench = Bench(dut)
    await bench.start()
    top = SCRATCH_D - 1

    for name, n in (("fp32", 40), ("fp64", 20), ("fp128", 12),
                    ("fp256", 6)):
        fmt = FORMATS[name]
        # -- static: two slots, one of them the top one, round-tripped
        # through registers the plain form could not even name.
        prog = seq.Program(fmt, [
            seq.stl(0, 0), seq.stl(1, top),
            seq.ldl(20, top), seq.ldl(21, 0),
            seq.deposit(20), seq.deposit(21),
            # a slot nothing wrote: +0, not whatever the last block left
            seq.ldl(22, 5), seq.deposit(22),
            seq.halt()], max_deposits=3)
        await bench.program(fmt, prog, operands(fmt, n, 1300),
                            operands(fmt, n, 1301), operands(fmt, n, 1302),
                            n, f"{name} STL/LDL, slot 0 and slot {top}")

        # -- indexed, with every lane on its own slot and a third of
        # them past the depth. r1 carries the index; the streams below
        # are integers, not the specials mix, because an index is a bit
        # pattern read as an unsigned integer.
        idx = [_int_bits(fmt, i * 7 + (SCRATCH_D * (i % 3)))
               for i in range(n)]
        rdx = [_int_bits(fmt, i * 7 + (SCRATCH_D * ((i + 1) % 4)))
               for i in range(n)]
        prog = seq.Program(fmt, [
            seq.stx(0, 1),          # scratch[r1 mod D] := r0
            seq.ldx(23, 2),         # r23 := scratch[r2 mod D]
            seq.deposit(23),
            seq.halt()], max_deposits=1)
        await bench.program(fmt, prog, operands(fmt, n, 1310), idx, rdx,
                            n, f"{name} STX/LDX, indices past the depth")

        # -- the two forms addressing the SAME slot from both sides,
        # which is what says the static and indexed address paths land
        # in one memory rather than two.
        prog = seq.Program(fmt, [
            seq.stl(0, 9),
            seq.ldx(24, 1),         # r1 == 9 for every lane below
            seq.deposit(24),
            seq.stx(24, 1),
            seq.ldl(25, 9),
            seq.deposit(25),
            seq.halt()], max_deposits=2)
        nine = [_int_bits(fmt, 9 + SCRATCH_D * (i % 5)) for i in range(n)]
        await bench.program(fmt, prog, operands(fmt, n, 1320), nine,
                            operands(fmt, n, 1322), n,
                            f"{name} one slot through both forms")

    # -- MORE THAN ONE LANE BLOCK, which nothing above reaches: 40
    # lanes at fp32 is one block of 128 and 20 at fp256 is two blocks
    # of 16. Two things are only testable here.
    #
    #   * the per-block WIPE. Each block loads slot 5 BEFORE it stores
    #     to it, so block 1 must read +0 there and not block 0's value.
    #     A tile that wiped once per run instead of once per block
    #     passes every case above and fails this one on lane 16.
    #   * the indexed form across blocks, where the slot is the lane's
    #     own data and the lane state is rebuilt between blocks.
    for name, n in (("fp32", 300), ("fp64", 150), ("fp256", 20)):
        fmt = FORMATS[name]
        blocks = -(-n // lanes_per_block(fmt))
        assert blocks >= 2, f"{name} n={n} is one block; the case is idle"
        prog = seq.Program(fmt, [
            seq.ldl(26, 5),          # +0 in EVERY block, wiped or not yet used
            seq.deposit(26),
            seq.stl(0, 5),
            seq.ldl(27, 5),
            seq.deposit(27),
            seq.stx(1, 2),
            seq.ldx(28, 2),
            seq.deposit(28),
            seq.halt()], max_deposits=3)
        idx = [_int_bits(fmt, i * 3 + SCRATCH_D * (i % 2)) for i in range(n)]
        await bench.program(fmt, prog, operands(fmt, n, 1390),
                            operands(fmt, n, 1391), idx, n,
                            f"{name} the scratch across {blocks} lane blocks")

    dut._log.info(f"scratch: {bench.cases['program']} runs")


@cocotb.test()
async def scratch_is_masked_by_the_active_bit(dut):
    """P3 for the scratch: a store in an all-inactive loop body does
    nothing at all.

    A store is a register write for the active mask's purposes and a
    load writes rd, so a loop body every lane has dropped out of must
    leave the scratch exactly as it was. That is not an optimisation
    the module may skip - it is what makes the early exit invisible,
    and the early exit is what the whole design is allowed to do.

    The check has two halves. The MODEL says the scratch is unchanged
    (python/tests/test_seq.py compares the run against the same run
    with the early exit forced off); here the RTL is scored against the
    model on deposits, counts and FLAGS, and the value deposited at the
    end IS the slot's contents - so a store that escaped the mask lands
    in the deposit buffer where the comparison can see it.
    """
    bench = Bench(dut)
    await bench.start()

    for name, n in (("fp32", 32), ("fp256", 8)):
        fmt = FORMATS[name]
        zero, one = sf.zero_bits(fmt), sf.one_bits(fmt)
        prog = seq.Program(fmt, [
            seq.stl(0, 4),          # slot 4 := r0, every lane still live
            seq.stl(0, 7),
            seq.setact(1),          # r1 is +0, so every lane drops out
            seq.repeat(6),
            seq.stl(2, 4),          # ...and neither of these may land
            seq.stx(2, 2),
            seq.ldl(9, 7),          # nor may this write r9
            seq.endrep(),
            seq.actall(),           # wake them to report
            seq.ldl(10, 4), seq.deposit(10),
            seq.deposit(9),
            seq.halt()], max_deposits=2)
        a = operands(fmt, n, 1330)
        b = [zero] * n
        c = [_int_bits(fmt, 0xDEAD_BEEF + i) for i in range(n)]
        await bench.program(fmt, prog, a, b, c, n,
                            f"{name} a store in an all-inactive loop body")
        # ...and the positive control, one letter apart: the same
        # program with a NON-zero SETACT operand, where the body DOES
        # run and the slot really is overwritten. Without it a module
        # that ignored STL entirely would pass the case above.
        await bench.program(fmt, prog, a, [one] * n, c, n,
                            f"{name} ...and the same body when it runs")
    assert one != zero
    dut._log.info("scratch masking: the dead body and its control")


@cocotb.test()
async def scratch_io_block(dut):
    """R5: the scratch as a per-run block, in and out.

    Three claims, and the third is the one that makes the feature worth
    having:

      * the block that goes IN is readable by LDL - lane-major and
        dense, so lane i's slot s is element i * n_scratch_in + s, and
        a transposed preload would deposit some other lane's value;
      * the block that comes OUT is what the program left in the
        slots, written after the last deposit, in the same layout;
      * a run whose state leaves through one and comes back through the
        other computes in two calls what one call computes - which is
        the resumable-integration ask docs/SEQUENCER.md records against
        orbits and Collatz.

    The write-window assertion in `program` covers the negative half on
    every OTHER case in this file: a program without flags.SCRATCH_IO
    has its two pointers aimed at rubbish, and a run that wrote a
    scratch-out block it was not asked for would be caught by address.
    """
    bench = Bench(dut)
    await bench.start()

    for name, n in (("fp32", 24), ("fp64", 12), ("fp128", 8), ("fp256", 5)):
        fmt = FORMATS[name]
        # in 2, out 3: read both slots, combine them, store the result
        # in a slot NEITHER of them occupies, and let all three leave.
        prog = seq.Program(fmt, [
            seq.ldl(3, 0), seq.ldl(4, 1),
            seq.alu(sf.OP_ADD, rd=5, ra=3, rc=4),
            seq.stl(5, 2),
            seq.deposit(5),
            seq.halt()], max_deposits=1,
            flags=seq.FLAG_SCRATCH_IO, n_scratch_in=2, n_scratch_out=3)
        block = operands(fmt, 2 * n, 1340)
        await bench.program(fmt, prog, operands(fmt, n, 1341),
                            operands(fmt, n, 1342), operands(fmt, n, 1343),
                            n, f"{name} scratch in 2, out 3",
                            scratch_in=block)

        # n_scratch_out > n_scratch_in: the slots between the two were
        # never preloaded and never written, so they must leave as +0 -
        # which is the wipe's job, and the case that fails if the wipe
        # is sized off n_scratch_in.
        prog = seq.Program(fmt, [
            seq.ldl(6, 0), seq.stl(6, 1), seq.deposit(6), seq.halt()],
            max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
            n_scratch_in=1, n_scratch_out=4)
        await bench.program(fmt, prog, operands(fmt, n, 1350),
                            operands(fmt, n, 1351), operands(fmt, n, 1352),
                            n, f"{name} out deeper than in",
                            scratch_in=operands(fmt, n, 1353))

    # -- more than one lane block, so the two BLOCK STRIDES are under
    # test. Each is a header count shifted by BLK_SH rather than a
    # product, which is right by accident at one block: lane 128's
    # slots have to come from element 128 * n_scratch_in of the
    # buffer and not from element 0 of a second read of the first.
    fmt = FP32
    n = 300
    assert -(-n // lanes_per_block(fmt)) >= 3, "fewer than three blocks"
    prog = seq.Program(fmt, [
        seq.ldl(3, 0), seq.ldl(4, 1), seq.ldl(5, 2),
        seq.alu(sf.OP_ADD, rd=6, ra=3, rc=5),
        seq.stl(6, 1),
        seq.deposit(4),
        seq.halt()], max_deposits=1,
        flags=seq.FLAG_SCRATCH_IO, n_scratch_in=3, n_scratch_out=3)
    await bench.program(fmt, prog, operands(fmt, n, 1370),
                        operands(fmt, n, 1371), operands(fmt, n, 1372),
                        n, "fp32 scratch in 3, out 3, three lane blocks",
                        scratch_in=operands(fmt, 3 * n, 1373))

    # -- the resumable run, on one rung, in full. Three iterations then
    # three more must equal six, deposit for deposit.
    fmt = FP32
    n = 24
    one = sf.one_bits(fmt)
    body = [seq.ldl(3, 0),
            seq.alu(sf.OP_ADD, rd=3, ra=3, rc=0, kc=True),
            seq.stl(3, 0), seq.deposit(3)]

    def resumable(trips, maxdep):
        return seq.Program(fmt, [seq.repeat(trips)] + body
                           + [seq.endrep(), seq.halt()],
                           consts=[one], max_deposits=maxdep,
                           flags=seq.FLAG_SCRATCH_IO,
                           n_scratch_in=1, n_scratch_out=1)

    zeros = [sf.zero_bits(fmt)] * n
    a = operands(fmt, n, 1360)
    b = operands(fmt, n, 1361)
    c = operands(fmt, n, 1362)
    whole = await bench.program(fmt, resumable(6, 6), a, b, c, n,
                                "fp32 six trips in one call",
                                scratch_in=zeros)
    first = await bench.program(fmt, resumable(3, 3), a, b, c, n,
                                "fp32 three trips, state out",
                                scratch_in=zeros)
    second = await bench.program(fmt, resumable(3, 3), a, b, c, n,
                                 "fp32 ...and three more, state in",
                                 scratch_in=first.scratch_out)
    for i in range(n):
        assert first.deposits[i * 3:(i + 1) * 3] == \
            whole.deposits[i * 6:i * 6 + 3], f"lane {i}: first half"
        assert second.deposits[i * 3:(i + 1) * 3] == \
            whole.deposits[i * 6 + 3:(i + 1) * 6], (
                f"lane {i}: the resumed half does not equal the second "
                f"half of a single run - the state did not survive the "
                f"round trip through the two pointers")
    dut._log.info(
        f"scratch I/O: {bench.cases['scratch_out']} blocks compared, "
        f"and a run resumed across two calls")


@cocotb.test()
async def scratch_header_refusals(dut):
    """The three the tile owes at the header, and their controls.

    An unknown flag bit, a count past the depth, and a non-zero
    scratch_io word without the flag. The last is the one that makes a
    revision-2 tile the version guard for this whole feature: it
    refuses a non-zero second header word, so an image built for
    revision 3 is thrown back rather than run with the scratch never
    loaded.
    """
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    body = [seq.alu(sf.OP_ADD, 4, 0, 1, 2), seq.halt()]
    io = seq.FLAG_SCRATCH_IO

    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(0, 1)),
        "scratch_io = 1 with flags.SCRATCH_IO clear")
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(0, 1 << 16)),
        "scratch_io's OUT half set with the flag clear")
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(io, SCRATCH_D + 1)),
        f"n_scratch_in {SCRATCH_D + 1} past the {SCRATCH_D} slots a lane owns")
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(io, (SCRATCH_D + 1) << 16)),
        f"n_scratch_out {SCRATCH_D + 1} past the depth")
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(io, 0xFFFF | (0xFFFF << 16))),
        "both halves at 65535")
    await bench.refuse(
        fmt, raw_image(fmt, body, rsv=(1 << 3, 0)),
        "flags[3]: the first bit above SCRATCH_STRICT, still unknown")

    # The positive controls, without which a tile that refused every
    # non-zero header word would pass all six above. SCRATCH_D exactly
    # is the largest legal count, which is what says the comparison is
    # a `>` and not a `>=`.
    n = 16
    await bench.program(
        fmt,
        seq.Program(fmt, [seq.ldl(3, 0), seq.deposit(3), seq.halt()],
                    max_deposits=1, flags=io, n_scratch_in=1,
                    n_scratch_out=1),
        operands(fmt, n, 1370), operands(fmt, n, 1371),
        operands(fmt, n, 1372), n,
        "SCRATCH_IO is a KNOWN flag", scratch_in=operands(fmt, n, 1373))
    big = seq.Program(fmt, [seq.stl(0, SCRATCH_D - 1),
                            seq.ldl(4, SCRATCH_D - 1),
                            seq.deposit(4), seq.halt()],
                      max_deposits=1, flags=io,
                      n_scratch_in=SCRATCH_D, n_scratch_out=SCRATCH_D)
    # ...at a small n, because n * SCRATCH_D elements is the whole
    # scratch of every lane in both directions.
    n = 8
    await bench.program(fmt, big, operands(fmt, n, 1380),
                        operands(fmt, n, 1381), operands(fmt, n, 1382), n,
                        f"n_scratch_in and out at exactly {SCRATCH_D}",
                        scratch_in=operands(fmt, n * SCRATCH_D, 1383))
    dut._log.info(f"scratch header: {bench.cases['refusal']} refusals "
                  f"and their controls")


@cocotb.test()
async def scratch_fuzz(dut):
    """The model's own generator with the scratch arm on, whole state
    compared - the same discipline the revision-2 fuzz applies to the
    features it added.

    seq.random_program's `scratch` arm emits all four codes at every
    loop depth, with slots chosen to COLLIDE (a corpus that scattered
    its slots over 256 would spend its time reading +0 out of untouched
    storage) and with the highest slot among them.
    """
    bench = Bench(dut)
    await bench.start()
    rng = random.Random(20260908)
    kinds = Counter()
    runs = 0

    # Caps well below fuzz_programs', and deliberately: a scratch LOAD
    # is five cycles a beat where an ALU instruction is paced by the
    # pipe, and an INDEXED program makes the per-block wipe the whole
    # depth. The same corpus at fuzz_programs' bounds ran for over
    # fifteen minutes on one rung; what this suite is for is the four
    # codes through the RTL, not a second census.
    for name, sizes, cap in (("fp32", (8, 33), 120), ("fp64", (12,), 100),
                             ("fp128", (7,), 80), ("fp256", (5,), 50)):
        fmt = FORMATS[name]
        for n in sizes:
            for _ in range(3):
                while True:
                    insns, consts = seq.random_program(
                        fmt, rng, scratch=True, wide_regs=True)
                    if worst_case_insns(insns) > cap:
                        continue
                    try:
                        prog = seq.Program(fmt, insns, consts, 3)
                    except seq.ProgramError:
                        continue
                    break
                m = n
                if has_actall(insns):
                    m = max(1, -(-n // lanes_per_block(fmt))) \
                        * lanes_per_block(fmt)
                    if m > 64:
                        m = lanes_per_block(fmt)
                for w in insns:
                    d = seq.decode(w)
                    if d["ctrl"] and d["op"] in (seq.STL, seq.LDL,
                                                 seq.STX, seq.LDX):
                        kinds[d["op"]] += 1
                await bench.program(fmt, prog, operands(fmt, m, rng.randrange(1 << 20)),
                                    operands(fmt, m, rng.randrange(1 << 20)),
                                    operands(fmt, m, rng.randrange(1 << 20)),
                                    m, f"{name} scratch fuzz n={m}")
                runs += 1
    assert set(kinds) == {seq.STL, seq.LDL, seq.STX, seq.LDX}, (
        f"the corpus did not exercise all four codes: {dict(kinds)} - a "
        f"fuzz that never reaches the instruction it is named for passes "
        f"for the wrong reason")
    dut._log.info(f"scratch fuzz: {runs} programs, "
                  f"STL {kinds[seq.STL]} LDL {kinds[seq.LDL]} "
                  f"STX {kinds[seq.STX]} LDX {kinds[seq.LDX]}")


@cocotb.test()
async def scratch_strict_range(dut):
    """R8: an indexed slot at or past the depth is REPORTED, not reduced.

    The same program twice, and the PAIR is the case. Without
    SCRATCH_STRICT the index is taken modulo the depth - what every
    image built before revision 4 means, and what this tile did
    unconditionally until now. With it the access is suppressed, LDX
    reads +0, and STATUS[5] says a lane asked for a slot that is not
    there.

    The indices are 9 + 256k, so one lane in five is IN range. That is
    deliberate: a case where every lane was out of range would pass
    just as well against a tile that suppressed every indexed access it
    ever saw, which is the opposite defect and an easy one to write.

    The deposits differing between the two runs is what says the flag
    changed the ANSWER rather than only raising a bit beside it.
    """
    bench = Bench(dut)
    await bench.start()
    for name, n in (("fp32", 24), ("fp64", 12), ("fp256", 5)):
        fmt = FORMATS[name]
        body = [
            seq.stl(0, 9),           # slot 9 := a
            seq.ldx(24, 1),          # r24 := scratch[r1], r1 == 9 + 256k
            seq.deposit(24),
            seq.stx(24, 1),          # scratch[r1] := r24
            seq.ldl(25, 9),          # and read slot 9 back the static way
            seq.deposit(25),
            seq.halt()]
        idx = [_int_bits(fmt, 9 + SCRATCH_D * (i % 5)) for i in range(n)]
        lanes_in = sum(1 for i in range(n) if (i % 5) == 0)
        assert 0 < lanes_in < n, (
            f"{name} n={n}: {lanes_in} lanes in range - this case needs "
            f"both kinds, or it cannot tell a correct suppression from a "
            f"tile that suppresses everything")

        loose  = seq.Program(fmt, body, max_deposits=2)
        strict = seq.Program(fmt, body, max_deposits=2,
                             flags=seq.FLAG_SCRATCH_STRICT)

        w_loose = await bench.program(
            fmt, loose, operands(fmt, n, 1500), idx,
            operands(fmt, n, 1502), n, f"{name} indexed, modulo (no flag)")
        w_strict = await bench.program(
            fmt, strict, operands(fmt, n, 1500), idx,
            operands(fmt, n, 1502), n, f"{name} indexed, SCRATCH_STRICT")

        assert not (w_loose.status & seq.STATUS_SCRATCH_RANGE), (
            f"{name}: the model raised STATUS[5] without the flag - the "
            f"modulo is not an error and never was")
        assert w_strict.status & seq.STATUS_SCRATCH_RANGE, (
            f"{name}: the model did not raise STATUS[5] with the flag and "
            f"{n - lanes_in} lanes indexing past the depth, so this case "
            f"proves nothing about suppression")
        assert w_loose.deposits != w_strict.deposits, (
            f"{name}: the two runs deposited the same bytes, so the flag "
            f"changed nothing observable and both sides could be wrong "
            f"together")

    dut._log.info(f"strict range: {bench.cases['program']} runs, "
                  f"each paired with its own modulo control")


# ======================================================================
# 11. the one that has to go last
# ======================================================================

@cocotb.test()
async def zero_max_deposits_is_legal(dut):
    """`max_deposits == 0` is ACCEPTED, and every deposit overflows.

    This test asserted a refusal until the adversarial review of
    2026-09-01 traced the claim to its sources and found it standing
    alone: the model's validator accepts zero, SEQUENCER.md's
    loader-refusal list never mentions it, cft_seq's contract header
    calls it legal, and the RTL's drain has an explicit zero guard
    rather than an underflowing loop bound. The dangerous "fix" would
    have been teaching the RTL to refuse - diverging the tile from
    libcft in one edit - so the test inverted instead: the run
    completes, the deposit window is zero bytes wide and never
    written, every deposit attempt lands in STATUS[4], and the counts
    stream is n zeroes. All of that is what seq.run says, so the
    standard whole-machine comparison scores it.
    """
    bench = Bench(dut)
    await bench.start()
    prog = seq.Program(FP32, [seq.alu(sf.OP_ADD, 4, 0, 1, 2),
                              seq.deposit(4), seq.halt()],
                       [sf.one_bits(FP32)], max_deposits=0)
    n = 12
    await bench.program(FP32, prog,
                        operands(FP32, n, 990), operands(FP32, n, 991),
                        operands(FP32, n, 992), n,
                        "fp32 max_deposits=0: accepted, all overflow")
