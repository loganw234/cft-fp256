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

import functools
import os
import random
import sys
import types
from collections import Counter
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, with_timeout
from cocotb.utils import get_sim_time

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


def _seq_generic(name, default):
    """One of cft_seq's capacities as THIS build of the DUT has it: the
    CFT_GENERICS entry the target built it with, or else the module's own
    default, which this file keeps in step with the module as it always
    has. Revision 7 (2026-09-29) made the kernel's three capacities a
    build's parameters, and tb/Makefile's seq_coreu50 runs this bench at
    the U50's - rtl/cft_krnl.sv's SEQ_* defaults, read out of that file
    by tb/krnl_caps.py - handing the same words to the simulator as -P
    and to this bench here, from one list."""
    for g in os.environ.get("CFT_GENERICS", "").split():
        gname, _, value = g.partition("=")
        if gname == name:
            return int(value)
    return default


MAXD = _seq_generic("MAXD", 64)
IMEM_D = _seq_generic("IMEM_D", 1024)
# 256 -> 512 at revision 3 (R7): the ninth kx index bit made the
# second half of the bank reachable, and cft_seq's DEFAULT moved with
# it because tb/test_krnl.py holds cft_krnl's SEQ_KIDX_W against it.
# Not a build's to set: a deeper bank is an instruction-format change.
KMEM_D = 512
# Scratch slots a lane (revision 3, R4), and the reduction the indexed
# forms apply. A power of two by construction.
SCRATCH_D = _seq_generic("SCRATCH_D", 256)

# EVERY MODEL CALL IN THIS BENCH IS AT THE DUT'S DEPTH (revision 7). The
# depth is part of what a non-strict STX/LDX means, so a model left at
# its default of 256 would score a 2,048-slot build against a different
# machine. Rather than thread the argument through a hundred call sites
# and leave one behind, the name `seq` from here on is the golden model
# with its five depth-taking entry points bound to SCRATCH_D - run, the
# Program class, stl, ldl and the fuzz generator - and everything else
# the module itself. At cft_seq's default build SCRATCH_D is 256 and
# every call is exactly the call it always was.
_seq = seq


class _ProgramAtDepth(_seq.Program):
    """seq.Program, written for the DUT's depth unless told otherwise."""

    def __init__(self, *args, scratch_depth=SCRATCH_D, **kwargs):
        super().__init__(*args, scratch_depth=scratch_depth, **kwargs)

    @classmethod
    def from_bytes(cls, data, scratch_depth=SCRATCH_D):
        return super(_ProgramAtDepth, cls).from_bytes(
            data, scratch_depth=scratch_depth)


seq = types.SimpleNamespace(**{k: v for k, v in vars(_seq).items()
                               if not k.startswith("__")})
seq.Program = _ProgramAtDepth
seq.run = functools.partial(_seq.run, scratch_depth=SCRATCH_D)
seq.stl = functools.partial(_seq.stl, scratch_depth=SCRATCH_D)
seq.ldl = functools.partial(_seq.ldl, scratch_depth=SCRATCH_D)
seq.random_program = functools.partial(_seq.random_program,
                                       scratch_depth=SCRATCH_D)
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

# One memory, generously spaced. The deposit region comes after the
# inputs and has two megabytes behind it, because it is the only region
# whose size grows with max_deposits; the image has the top megabyte.
#
# The image sat at 0x1000 until revision 7 (2026-09-29), below the bank
# and the streams, which held while IMEM_D was 1,024 - an 8 KB image.
# At the U50's 32,768 (seq_coreu50) the refusal matrix's IMEM_D + 1
# image is 256 KB, and at 0x1000 it ran over the bank, the three
# streams and the counts, so the refusal's own "the count region was
# written" check fired on the bench's staging rather than on the tile.
# A megabyte holds an image of 131,068 instructions; 4 KB aligned, as
# 0x1000 was, so every image splits into the same bursts it always did.
RAM_BYTES = 1 << 22
PROG_BASE = 0x30_0000
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
# The four index tables (ABI 0.14, R16), each in its own region and all
# of them far from the buffers they index, for the reason BANK_BASE is
# far from the image: a gather that read its entries out of the stream
# it was indexing, or read the A table for the B stream, would pass
# every check here if the regions were adjacent. Sixty-four kilobytes
# apart is 16,384 entries, far more than any case below uses.
IA_BASE = 0x0A_0000
IB_BASE = 0x0B_0000
IC_BASE = 0x0C_0000
ISI_BASE = 0x0D_0000
# The lane mask (ABI 0.14, R17), in its own region for the same reason:
# a mask fetch that read the A stream, or a table, would pass every
# check here if the regions were adjacent. One bit a lane, so 64 KB is
# half a million lanes - far more than any case below uses.
MASK_BASE = 0x0E_0000
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

    Revision 8 (R8S, parcel RD1) gave it a round trip and a depth, for
    the instruction fetch, whose read engine keeps bursts in flight:
    `rd_latency` cycles from an AR's acceptance to its first beat, a
    PIPELINED delay as tb/busfx.py's latency() is - each burst is
    stamped with its release cycle when accepted and served in order,
    one beat a cycle - and `rd_depth` bursts accepted and unfinished
    before ARREADY drops. At the defaults, 0 and 4, it is the slave it
    always was, cycle for cycle. `clk` names the clock where the DUT's
    is not `ap_clk`, and a DUT with no write master (cft_ifetch) is
    served the read half alone. Two hooks let a bench be uncooperative
    on purpose, both None by default: `rresp_at(burst, beat)` gives a
    beat's RRESP, and `beats_for(burst, asked)` how many beats a burst
    really returns, RLAST on the last - shorter or longer than ARLEN
    asked is a length fault. Bursts are numbered from 0 in issue order,
    as arlog lists them.
    """

    def __init__(self, dut, size=RAM_BYTES, rd_latency=0, rd_depth=4,
                 clk=None):
        self.dut = dut
        self.size = size
        self.mem = bytearray(size)
        self.rd_latency = rd_latency
        self.rd_depth = rd_depth
        self.clk = dut.ap_clk if clk is None else clk
        self.has_wr = hasattr(dut, "m_wr_awvalid")
        self.rresp_at = None
        self.beats_for = None
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
        # Every read burst, in the order it was issued: (address,
        # beats). A gather's whole behaviour is visible here - which
        # entries it read, from where, in what order and how many -
        # and R16's read count is asserted against it rather than
        # inferred from the answer being right.
        self.arlog = []

    def stage(self, addr, data):
        assert addr + len(data) <= self.size, "staging past the model RAM"
        self.mem[addr:addr + len(data)] = data

    def fetch(self, addr, nbytes):
        return bytes(self.mem[addr:addr + nbytes])

    def reads_in(self, lo, hi):
        """Every read burst that landed in [lo, hi), in order."""
        return [(a, b) for (a, b) in self.arlog if lo <= a < hi]

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
        if self.has_wr:
            dut.m_wr_awready.value = 1
            dut.m_wr_wready.value = 1
            dut.m_wr_bvalid.value = 0
            dut.m_wr_bresp.value = 0

        # A pending read is [address of its next beat, beats it will
        # still send, the first cycle it may be presented in, its number,
        # beats sent so far]. `cyc` numbers the cycle whose ReadOnly this
        # pass is in; a burst accepted in it is presentable from cycle
        # cyc + 1 + rd_latency, which at latency 0 is the very next
        # cycle - the slave this class has always been.
        pend, cur_r = [], None
        awq, wq, bq, cur_w = [], [], 0, None
        arready, rvalid, rlast, rdata, rresp = 1, 0, 0, 0, 0
        bvalid = 0
        cyc = 0

        while True:
            await ReadOnly()

            # ---- read master -------------------------------------------
            if arready and _i(dut.m_rd_arvalid):
                addr, alen = _i(dut.m_rd_araddr), _i(dut.m_rd_arlen)
                self._check_burst(addr, alen, "read")
                if addr % BEAT_BYTES:
                    self.unaligned_ar += 1
                n = len(self.arlog)
                beats = (alen + 1 if self.beats_for is None
                         else self.beats_for(n, alen + 1))
                pend.append([addr, beats, cyc + 1 + self.rd_latency, n, 0])
                self.ar_count += 1
                self.arlog.append((addr, alen + 1))
            if rvalid and _i(dut.m_rd_rready):
                cur_r[0] += BEAT_BYTES
                cur_r[1] -= 1
                cur_r[4] += 1
                if cur_r[1] == 0:
                    cur_r = None
            if cur_r is None and pend and pend[0][2] <= cyc + 1:
                cur_r = pend.pop(0)

            was_valid, rvalid = rvalid, int(cur_r is not None)
            if rvalid:
                rlast = int(cur_r[1] == 1)
                rdata = int.from_bytes(
                    self.mem[cur_r[0]:cur_r[0] + BEAT_BYTES], "little")
                if self.rresp_at is not None:
                    rresp = self.rresp_at(cur_r[3], cur_r[4])
            else:
                rlast = 0
            arready = int(len(pend) < self.rd_depth)

            # ---- write master ------------------------------------------
            if self.has_wr:
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

            await RisingEdge(self.clk)
            cyc += 1
            dut.m_rd_arready.value = arready
            if self.has_wr:
                dut.m_wr_bvalid.value = bvalid
            if rvalid or was_valid:
                dut.m_rd_rvalid.value = rvalid
                dut.m_rd_rlast.value = rlast
                if rvalid:
                    dut.m_rd_rdata.value = rdata
                    if self.rresp_at is not None:
                        dut.m_rd_rresp.value = rresp


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
    # ...and revision 7 the depth the program is written for. run()
    # takes its own depth and does not read this one, but __init__
    # would have set it, and "every field" is the rule above.
    p.scratch_depth = SCRATCH_D
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
                     "cfg_cnt", "cfg_indexed", "cfg_idx_a", "cfg_idx_b",
                     "cfg_idx_c", "cfg_idx_si", "cfg_mask_en", "cfg_mask",
                     "cfg_lflags_en", "cfg_lflags"):
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
        # Cycles from the start pulse to `done`, kept for the cases that
        # hold a cost (revision 7's hold bench): the same count
        # probe_seq_cycles.py prints, taken the same way.
        t_start = get_sim_time("ns")
        await RisingEdge(dut.ap_clk)
        dut.start.value = 0
        try:
            await with_timeout(RisingEdge(dut.done), budget * CLK_NS, "ns")
            self.last_cycles = (get_sim_time("ns") - t_start) / CLK_NS
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

    def _drive_cfg(self, fmt, n, bank_ptr=None, scratch=False,
                   idx_mask=0, lane_mask=False):
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
        # ...and the four index tables on the same terms (R16). A table
        # whose MODE bit is clear must never be read, so its pointer is
        # aimed at nothing; with the bit set it is the staged region.
        dut.cfg_indexed.value = idx_mask
        dut.cfg_idx_a.value = IA_BASE if idx_mask & 1 else 0xDEAD_3000
        dut.cfg_idx_b.value = IB_BASE if idx_mask & 2 else 0xDEAD_4000
        dut.cfg_idx_c.value = IC_BASE if idx_mask & 4 else 0xDEAD_5000
        dut.cfg_idx_si.value = ISI_BASE if idx_mask & 8 else 0xDEAD_6000
        # ...and the lane mask on exactly those terms (R17). A run
        # without MODE[23] must never read MASK_PTR, so its pointer is
        # aimed at nothing and the model RAM's window assertion is what
        # says it was not read.
        dut.cfg_mask_en.value = 1 if lane_mask else 0
        dut.cfg_mask.value = MASK_BASE if lane_mask else 0xDEAD_7000
        # ...and revision 8's R23 flag block (its seam, 2026-10-02): no
        # run here asks for it, and the CSR refuses MODE[24] on every
        # build until R23 is built, so the pointer is aimed at nothing -
        # a write there trips the write logger's window assertion.
        dut.cfg_lflags_en.value = 0
        dut.cfg_lflags.value = 0xDEAD_8000

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

    # -- an INDEXED run (revision 6, R16) --------------------------------

    async def gathered(self, fmt, prog, a, b, c, n, label, *,
                       idx_a=None, idx_b=None, idx_c=None,
                       scratch_in=None, idx_scratch_in=None,
                       check_flags=True, check_reads=True):
        """Run `prog` over `n` lanes with some of its input blocks
        fetched through index tables, and compare the whole machine -
        the same comparison `program()` makes, against the model run
        with the same tables.

        `a`, `b`, `c` are SOURCES where the matching table is given:
        arbitrarily long, indexed by entry, and staged whole. Where it
        is not, they are the dense streams they always were.

        `check_reads` asserts the gather's READ TRAFFIC against the
        table: one burst per table beat at the block's own entry
        offset, then one single-beat read per non-sentinel entry at
        that element's beat, in table order. That is the assertion
        that fails when the block offset is scaled by the element size
        rather than by four - the failure that otherwise reads as a
        plausible neighbour's value.
        """
        dut = self.dut
        ebytes = fmt.width // 8
        maxdep = prog.max_deposits
        image = prog.to_bytes()
        dep_bytes = n * maxdep * ebytes
        cnt_bytes = 4 * n
        tables = (idx_a, idx_b, idx_c)
        idx_mask = ((1 if idx_a is not None else 0) |
                    (2 if idx_b is not None else 0) |
                    (4 if idx_c is not None else 0) |
                    (8 if idx_scratch_in is not None else 0))
        assert idx_mask, f"{label}: a gathered run with no table"
        # ACTALL over a ragged block is the one place the model and the
        # hardware read the padding differently (see the module
        # docstring), and a gathered block's padding is +0 rather than
        # the caller's bytes - so the two ambiguities would compound.
        # Every case here is therefore ACTALL-free, which is checked
        # rather than remembered.
        assert not has_actall(prog.insns), (
            f"{label}: a gathered case must not contain ACTALL")

        want = seq.run(prog, list(a), list(b), list(c),
                       scratch_in=scratch_in,
                       idx_a=idx_a, idx_b=idx_b, idx_c=idx_c,
                       idx_scratch_in=idx_scratch_in)
        sout_bytes = n * prog.n_scratch_out * ebytes

        self._stage(fmt, image, a, b, c, n, dep_bytes, cnt_bytes,
                    scratch_in=scratch_in)
        for base, table in ((IA_BASE, idx_a), (IB_BASE, idx_b),
                            (IC_BASE, idx_c), (ISI_BASE, idx_scratch_in)):
            if table is None:
                continue
            # Beat-padded, as the ABI says a table is - the tile reads
            # whole beats and the last one of a block may reach past
            # the entries the caller has.
            raw = b"".join(int(t).to_bytes(4, "little") for t in table)
            raw += bytes(POISON for _ in
                         range(-len(raw) % BEAT_BYTES))
            self.ram.stage(base, raw)
        self._drive_cfg(fmt, n, scratch=prog.scratch_io, idx_mask=idx_mask)

        budget = self._budget(fmt, prog, n, len(image))
        # ...plus the gather's own traffic, which the dense budget knows
        # nothing about: every entry is a round trip through this
        # bench's RAM and the state machine spends a handful of cycles
        # on each. Derived from the tables, never typed.
        entries = sum(len(t) for t in tables if t is not None)
        entries += len(idx_scratch_in) if idx_scratch_in is not None else 0
        budget += 64 * (entries + 64)

        refused, flags, err = await self._go(budget, label)
        assert refused == 0, f"{label}: the module refused a valid program"

        windows = []
        if dep_bytes:
            windows.append((D_BASE, dep_bytes, "deposit"))
        if cnt_bytes:
            windows.append((CNT_BASE, cnt_bytes, "count"))
        if sout_bytes:
            windows.append((SOUT_BASE, sout_bytes, "scratch-out"))
        self.ram.assert_writes_inside(windows, label)
        self.ram.assert_guards(windows, label)

        if check_reads:
            for r, (tbase, sbase, table) in enumerate((
                    (IA_BASE, A_BASE, idx_a), (IB_BASE, B_BASE, idx_b),
                    (IC_BASE, C_BASE, idx_c))):
                if table is None:
                    continue
                self._check_gather_reads(
                    fmt, tbase, sbase, table, n, 1,
                    f"{label}: stream {'abc'[r]}")
            if idx_scratch_in is not None:
                self._check_gather_reads(
                    fmt, ISI_BASE, SIN_BASE, idx_scratch_in, n,
                    prog.n_scratch_in, f"{label}: the scratch block")

        self._compare(fmt, prog, n, want, flags, err, a, b, c, label,
                      check_flags)
        self._compare_scratch_out(fmt, prog, n, want, label)
        self.cases["gathered"] += 1
        return want

    def _check_gather_reads(self, fmt, tbase, sbase, table, n, per_lane,
                            label):
        """The gather's reads, derived from the table and the format.

        Two claims, and each of them is a defect this bench has to be
        able to see:

        * the table's beats start at the block's own ENTRY offset -
          blk_base * per_lane entries, four bytes each, and NOT the
          dense stream's offset, which is scaled by the element size;
        * one single-beat read per NON-SENTINEL entry, at the beat that
          holds `source[idx]`, in the table's order - so a sentinel
          costs no read at all and a mis-scaled address is visible as
          an address and not as a wrong answer.
        """
        ebytes = fmt.width // 8
        lpb = lanes_per_block(fmt)
        entries_per_beat = BEAT_BYTES // 4
        want_tbl, want_el = [], []
        for base in range(0, n, lpb):
            blk_n = min(lpb, n - base)
            first = base * per_lane
            count = blk_n * per_lane
            beats = -(-count // entries_per_beat)
            for j in range(beats):
                want_tbl.append((tbase + first * 4 + j * BEAT_BYTES, 1))
            for e in range(first, first + count):
                if table[e] == seq.IDX_NONE:
                    continue
                want_el.append(
                    (sbase + ((table[e] * ebytes) & ~(BEAT_BYTES - 1)), 1))
        got_tbl = self.ram.reads_in(tbase, tbase + (1 << 16))
        got_el = self.ram.reads_in(sbase, sbase + (1 << 16))
        assert got_tbl == want_tbl, (
            f"{label}: the table's reads are not the block's entries. "
            f"got {got_tbl[:6]}... ({len(got_tbl)} bursts), want "
            f"{want_tbl[:6]}... ({len(want_tbl)}). A block's entries "
            f"start at entry blk_base * {per_lane}, four bytes each.")
        assert got_el == want_el, (
            f"{label}: the element reads are not the table's. got "
            f"{got_el[:6]}... ({len(got_el)} bursts), want "
            f"{want_el[:6]}... ({len(want_el)}). "
            f"{sum(1 for t in table if t == seq.IDX_NONE)} of "
            f"{len(table)} entries are CFT_IDX_NONE and must cost no "
            f"read at all.")

    # -- a MASKED run (revision 6, R17) ----------------------------------

    async def masked(self, fmt, prog, a, b, c, n, keep, label, *,
                     check_flags=True, check_reads=True, scratch_in=None,
                     pre=None, idx_a=None, idx_b=None, idx_c=None,
                     idx_scratch_in=None):
        """Run `prog` over `n` lanes with a lane mask and compare the
        whole machine: the lanes the mask keeps against the model, and
        the lanes it clears against the BYTES THAT WERE THERE BEFORE.

        That second half is the whole of R17 and it is why this is a
        separate method rather than a flag on `program()`. The model's
        arrays are fresh, so a masked lane reads +0 there; the tile
        writes into the caller's memory, so a masked lane must read
        whatever the caller left - which in this bench is POISON,
        everywhere, because `_stage` poisons the RAM before each run.
        A drain that wrote the model's +0 over a masked lane would
        agree with the model and still be wrong.

        `keep` is n booleans, one a lane, global. `pre` is an optional
        coroutine run on this instance BEFORE the masked run, for the
        two-run flag cases: the sticky word is a register, so "a lane
        that was loud in the last run is quiet in this one" is a claim
        about state and not about one run.
        """
        ebytes = fmt.width // 8
        maxdep = prog.max_deposits
        image = prog.to_bytes()
        dep_bytes = n * maxdep * ebytes
        cnt_bytes = 4 * n
        assert len(keep) == n, f"{label}: a mask is one bit a lane"

        # FIRST, so that this run's staging - which poisons the whole
        # model RAM and clears the traffic log - is what the masked run
        # actually sees, and so the reads asserted below are its own.
        if pre is not None:
            await pre()

        # R16 and R17 on one run where the caller asks for it: the
        # mask decides which lanes run, the table decides what they
        # read, and the model resolves both.
        idx_mask = ((1 if idx_a is not None else 0) |
                    (2 if idx_b is not None else 0) |
                    (4 if idx_c is not None else 0) |
                    (8 if idx_scratch_in is not None else 0))
        want = seq.run(prog, list(a), list(b), list(c),
                       scratch_in=scratch_in, lane_mask=list(keep),
                       idx_a=idx_a, idx_b=idx_b, idx_c=idx_c,
                       idx_scratch_in=idx_scratch_in)
        sout_bytes = n * prog.n_scratch_out * ebytes

        self._stage(fmt, image, a, b, c, n, dep_bytes, cnt_bytes,
                    scratch_in=scratch_in)
        for base, table in ((IA_BASE, idx_a), (IB_BASE, idx_b),
                            (IC_BASE, idx_c), (ISI_BASE, idx_scratch_in)):
            if table is None:
                continue
            tb = b"".join(int(t).to_bytes(4, "little") for t in table)
            tb += bytes(POISON for _ in range(-len(tb) % BEAT_BYTES))
            self.ram.stage(base, tb)
        # The mask itself: one bit a lane, little-endian within the
        # byte, and the tail of the last byte and the rest of the beat
        # left POISON - the tile reads whole beats, so bits past the
        # block's own lanes must be ones it cannot use. Built from
        # `keep` here rather than typed.
        raw = bytearray((n + 7) // 8)
        for i, k in enumerate(keep):
            if k:
                raw[i >> 3] |= 1 << (i & 7)
        pad = -len(raw) % BEAT_BYTES
        self.ram.stage(MASK_BASE, bytes(raw) + bytes([POISON]) * pad)
        self._drive_cfg(fmt, n, scratch=prog.scratch_io, lane_mask=True,
                        idx_mask=idx_mask)

        budget = self._budget(fmt, prog, n, len(image))
        # ...plus the mask fetch, one round trip a block, and the
        # gather's own traffic where there is a table. Derived from the
        # tables and the geometry, never typed.
        budget += 64 * (1 + -(-n // lanes_per_block(fmt)))
        entries = sum(len(t) for t in
                      (idx_a, idx_b, idx_c, idx_scratch_in)
                      if t is not None)
        budget += 64 * (entries + 64) if entries else 0
        refused, flags, err = await self._go(budget, label)
        assert refused == 0, f"{label}: the module refused a valid program"

        windows = []
        if dep_bytes:
            windows.append((D_BASE, dep_bytes, "deposit"))
        if cnt_bytes:
            windows.append((CNT_BASE, cnt_bytes, "count"))
        if sout_bytes:
            windows.append((SOUT_BASE, sout_bytes, "scratch-out"))
        self.ram.assert_writes_inside(windows, label)
        self.ram.assert_guards(windows, label)

        if check_reads:
            self._check_mask_reads(fmt, n, label)
        self._compare_masked(fmt, prog, n, keep, want, flags, err, label,
                             check_flags)
        self.cases["masked"] += 1
        return want

    def _check_mask_reads(self, fmt, n, label):
        """The mask fetch's traffic, derived from the block geometry.

        One single-beat read a block, at the beat holding that block's
        first lane's bit - `MASK_BASE + (blk_base // 256) * 32`, which
        is a count of LANES and not of elements. A mask offset scaled
        by the element size, or by the byte count of a block's bits,
        would give a block somebody else's lanes and the deposits would
        still look plausible, so this is asserted as an ADDRESS.
        """
        lpb = lanes_per_block(fmt)
        want = []
        for base in range(0, n, lpb):
            want.append((MASK_BASE + (base // (BEAT_BYTES * 8)) * BEAT_BYTES,
                         1))
        got = self.ram.reads_in(MASK_BASE, MASK_BASE + (1 << 16))
        assert got == want, (
            f"{label}: the mask fetch read {got} and the block geometry "
            f"says {want} - one single-beat read a block, at the beat "
            f"holding bit blk_base. n={n}, {lpb} lanes a block.")

    def _compare_masked(self, fmt, prog, n, keep, want, flags, err, label,
                        check_flags):
        ebytes = fmt.width // 8
        maxdep = prog.max_deposits
        nsout = prog.n_scratch_out if prog.scratch_io else 0
        poison_el = bytes([POISON]) * ebytes

        got_dep = self.ram.fetch(D_BASE, n * maxdep * ebytes)
        for idx in range(n * maxdep):
            lane, slot = divmod(idx, maxdep)
            raw = got_dep[idx * ebytes:(idx + 1) * ebytes]
            if keep[lane]:
                g = int.from_bytes(raw, "little")
                assert g == want.deposits[idx], (
                    f"{label}: deposit[lane {lane} slot {slot}] got {g:#x} "
                    f"want {want.deposits[idx]:#x} - an unmasked lane must "
                    f"be exactly the run without the mask")
            else:
                assert raw == poison_el, (
                    f"{label}: deposit[lane {lane} slot {slot}] at "
                    f"{D_BASE + idx * ebytes:#x} was WRITTEN ({raw.hex()}); "
                    f"a masked lane's slots keep the caller's bytes, and "
                    f"+0 over them is still a write")

        got_cnt = self.ram.fetch(CNT_BASE, 4 * n)
        for i in range(n):
            raw = got_cnt[i * 4:i * 4 + 4]
            if keep[i]:
                g = int.from_bytes(raw, "little")
                assert g == want.counts[i], (
                    f"{label}: count[lane {i}] got {g} want {want.counts[i]}")
            else:
                assert raw == bytes([POISON]) * 4, (
                    f"{label}: count[lane {i}] at {CNT_BASE + 4 * i:#x} was "
                    f"written ({raw.hex()}); a masked lane has no count")

        if nsout:
            got_so = self.ram.fetch(SOUT_BASE, n * nsout * ebytes)
            for idx in range(n * nsout):
                lane, slot = divmod(idx, nsout)
                raw = got_so[idx * ebytes:(idx + 1) * ebytes]
                if keep[lane]:
                    g = int.from_bytes(raw, "little")
                    assert g == want.scratch_out[idx], (
                        f"{label}: scratch_out[lane {lane} slot {slot}] got "
                        f"{g:#x} want {want.scratch_out[idx]:#x}")
                else:
                    assert raw == poison_el, (
                        f"{label}: scratch_out[lane {lane} slot {slot}] was "
                        f"written; the scratch-out drain is not masked by "
                        f"the ACTIVE bit, and it IS masked by the caller's")

        if check_flags:
            assert flags == want.flags, (
                f"{label}: FLAGS {flags:#07b}, model says {want.flags:#07b}. "
                f"A masked lane contributes nothing, so a surplus bit is a "
                f"lane that ran when the caller did not ask for it.")
        want_ovf = bool(want.status & seq.STATUS_DEPOSIT_OVERFLOW)
        assert bool(err & 0x8) == want_ovf, (
            f"{label}: err[3] (deposit overflow) is {bool(err & 0x8)}, "
            f"model says {want_ovf}")
        assert (err & 0x7) == 0, (
            f"{label}: err[2:0]={err & 0x7} - the model memory answered "
            f"OKAY on every beat")

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
        # revision 3 has exactly the budget it had. Since revision 7 the
        # wipe is the lesser of that and what the previous block wrote,
        # so this stays a bound.
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
        # Per block: RF_D cycles that WERE the register-file wipe until
        # 2026-09-14 (valid bits replaced it; the term stays as slack,
        # this is a bound), the scratch wipe, the scratch-in preload
        # (an element a cycle plus its beats), the three operand
        # streams, the instructions, the deposit drain, and the
        # scratch-out drain.
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
        # Revision 8's R24 mark, err[5] -> STATUS[6] since the revision's
        # seam (2026-10-02), held here for the reason err[4] is: every
        # program this file runs holds the tile to the model on it. No
        # program here raises one, and the seam's tile ties it to zero,
        # so both say clear until R24 is built.
        want_mark = bool(want.status & seq.STATUS_MARKED)
        assert bool(err & 0x20) == want_mark, (
            f"{label}: err[5] (a RAISE marked a lane -> STATUS[6]) is "
            f"{bool(err & 0x20)}, model says {want_mark}")
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


@cocotb.test()
async def scratch_index_past_256_at_the_dut_depth(dut):
    """Revision 7: an index past 256, where the DUT's depth decides.

    Every indexed case above builds its indices from SCRATCH_D itself,
    so they land on the same slots whatever the depth. These do not:
    9 + 256k is slot 9 on a 256-slot build and a different slot for each
    k on a deeper one (seq_coreu50's 2,048), and past the depth only on
    the 256-slot one. Plain and strict, held to the model at the DUT's
    depth - so seq_core holds the 256-slot machine and seq_coreu50 the
    2,048-slot one - and on a deeper build the plain run's deposits and
    the strict run's STATUS are asserted to DIFFER from a 256-slot
    model's, so a bench whose model still ran at 256 would fail here.
    """
    bench = Bench(dut)
    await bench.start()
    deeper = SCRATCH_D > 256
    for name, n in (("fp32", 20), ("fp64", 10)):
        fmt = FORMATS[name]
        body = [
            seq.stl(0, 9),           # slot 9 := a
            seq.ldx(24, 1),          # r24 := scratch[r1], r1 == 9 + 256k
            seq.deposit(24),
            seq.stx(24, 1),          # scratch[r1] := r24
            seq.ldl(25, 9),          # slot 9, the static way
            seq.deposit(25),
            seq.halt()]
        idx = [_int_bits(fmt, 9 + 256 * (i % 5)) for i in range(n)]
        a, c = operands(fmt, n, 1600), operands(fmt, n, 1602)
        for flags, tag in ((0, "plain"),
                           (seq.FLAG_SCRATCH_STRICT, "strict")):
            prog = seq.Program(fmt, body, max_deposits=2, flags=flags)
            want = await bench.program(
                fmt, prog, a, idx, c, n,
                f"{name} index 9 + 256k, {tag}, at {SCRATCH_D} slots")
            at256 = _seq.run(prog, a, idx, c, scratch_depth=256)
            reported = bool(want.status & seq.STATUS_SCRATCH_RANGE)
            assert reported == (bool(flags) and not deeper), (
                f"{name} {tag}: STATUS {want.status:#x} at {SCRATCH_D} "
                f"slots - an index of 9 + 256k is past a 256-slot tile "
                f"and inside a deeper one")
            if deeper and not flags:
                # plain: the 256-slot machine wraps every index to slot 9
                assert want.deposits != at256.deposits, (
                    f"{name} {tag}: the same deposits at {SCRATCH_D} slots "
                    f"as at 256, so this case cannot tell the depths "
                    f"apart")
            elif deeper:
                # strict: past the depth a load reads +0 - what an
                # untouched slot inside it reads too - and the store it
                # suppresses is of that +0, so the deposits agree and the
                # REPORT is what tells the machines apart
                assert want.status != at256.status, (
                    f"{name} {tag}: STATUS {want.status:#x} at "
                    f"{SCRATCH_D} slots and at 256 alike")
            else:
                assert want.deposits == at256.deposits
                assert want.status == at256.status

    dut._log.info(f"an index past 256: {bench.cases['program']} runs, "
                  f"plain and strict, at {SCRATCH_D} slots")


# ---- revision 7: the wipe follows what was written -------------------
#
# rtl/cft_seq.sv keeps a dirty high-water mark a word bank and wipes a
# block only as far as the marks say anything was written since the last
# wipe, where it used to wipe all SCRATCH_D slots for any program that
# indexes - 4,096 cycles a block at 256 slots, 32,768 at the U50's 2,048.
# Two claims, and a test each: nothing a block can read is left from
# another block or another run; and an indexing program's block costs
# what it wrote, not what the build has.

def _walk_prog(fmt):
    """scratch[r0] := r2; r3 := scratch[r1]; deposit r3."""
    return seq.Program(fmt, [
        seq.stx(2, 0),
        seq.ldx(3, 1),
        seq.deposit(3),
        seq.halt()], max_deposits=1)


@cocotb.test()
async def scratch_blocks_see_only_their_own_writes(dut):
    """Three blocks of fp32 lanes, run twice. Block 0 stores each lane's
    value near the TOP of the scratch and reads it back; block 1 stores
    at slot 3 and reads the top slot block 0 wrote in the same physical
    lane position, which a wipe that stopped short would hand it; block
    2 stores at slot 7 and reads block 1's slot 3. The model has no
    blocks - every lane's scratch starts at +0 - so every read of a slot
    the lane never wrote must be +0, and anything else is a slot leaking
    from one block, or one run, into another."""
    bench = Bench(dut)
    await bench.start()
    watch = _BroadcastWatch(dut)
    fmt = FP32
    lpb = lanes_per_block(fmt)
    n = 3 * lpb
    top = [SCRATCH_D - 1 - (i % 8) for i in range(n)]
    wr = [top[i] if i < lpb else (3 if i < 2 * lpb else 7) for i in range(n)]
    rd = [top[i] if i < lpb else (top[i] if i < 2 * lpb else 3)
          for i in range(n)]
    vals = [0x3F80_0000 + i for i in range(n)]      # 1.0 and up, all nonzero
    prog = _walk_prog(fmt)
    for rep in range(2):
        want = await bench.program(
            fmt, prog, [_int_bits(fmt, v) for v in wr],
            [_int_bits(fmt, v) for v in rd], vals, n,
            f"three blocks, top slot then 3 then 7 (run {rep})")
        assert want.deposits[:lpb] == vals[:lpb], \
            "block 0 must read back what it wrote"
        assert want.deposits[lpb:] == [0] * (2 * lpb), \
            "blocks 1 and 2 read slots their lanes never wrote: +0"

    # Across runs, and the one rule the marks could get wrong: a STATIC
    # program wipes only what it can observe, so its short wipe must not
    # declare clean the slots above it that an earlier run dirtied. Run
    # A indexes near the top; run S names slot 3 alone and wipes 0..3;
    # run B indexes again and reads what run A wrote in the same lane
    # positions - which must be +0, so B's wipe had to reach A's slots.
    n1 = lpb
    high = [SCRATCH_D - 9 - (i % 8) for i in range(n1)]
    await bench.program(fmt, prog, [_int_bits(fmt, v) for v in high],
                        [_int_bits(fmt, v) for v in high], vals[:n1], n1,
                        "run A: near the top")
    stat = seq.Program(fmt, [seq.stl(0, 3), seq.ldl(3, 3), seq.deposit(3),
                             seq.halt()], max_deposits=1)
    await bench.program(fmt, stat, vals[:n1], vals[:n1], vals[:n1], n1,
                        "run S: slot 3 alone")
    want = await bench.program(fmt, prog, [_int_bits(fmt, 5)] * n1,
                               [_int_bits(fmt, v) for v in high], vals[:n1],
                               n1, "run B: reads run A's slots")
    assert want.deposits == [0] * n1, "run B's lanes never wrote those slots"
    watch.check(expect_some=SCRATCH_D > SUB_SLOTS)
    dut._log.info(f"dirty marks: {bench.cases['program']} runs, every "
                  f"block and run clean of the last; {watch.seen} broadcast "
                  f"wipe(s), every mark 0 after each")


@cocotb.test()
async def scratch_wipe_costs_what_was_written(dut):
    """What an indexing program's block costs, against the slots it
    wrote. Three runs of four fp32 blocks, each run once to set the marks
    and once to time:

      wide    STX through a register whose values stay below 32
      narrow  the same program, its values below 8
      static  STL at slot 31, wide's static twin

    wide and narrow differ only in the slots they write, so their blocks
    must differ by exactly the wipe's difference, (32 - 8) * NBEATS
    cycles. wide and static both write at most 32 slots a lane and both
    wipe 32, so wide must cost static's within a small constant: STX's
    own cost against STL's, NBEATS + 2 = 18 cycles a block, measured
    2026-09-29 before the marks and after them, at 256 slots and at
    2,048 alike. The slack is four slots' wipe, room for the issue rework
    beside this one; the exact difference above is what catches a wipe
    that is off by a slot. Before revision 7's marks wide cost static's
    plus (SCRATCH_D - 32) * NBEATS - 3,584 cycles a block at 256 slots,
    32,256 at 2,048 - and static costs the same at every depth, so this
    holding at both depths is wide costing at 2,048 what it costs at
    256."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    lpb = lanes_per_block(fmt)
    blocks = 4
    n = blocks * lpb
    one = sf.one_bits(fmt)
    stx = seq.Program(fmt, [seq.stx(0, 1), seq.halt()], max_deposits=0)
    stl = seq.Program(fmt, [seq.stl(0, 31), seq.halt()], max_deposits=0)
    per_block = {}
    for label, prog, below in (("wide", stx, 32), ("narrow", stx, 8),
                               ("static", stl, 32)):
        idx = [_int_bits(fmt, i % below) for i in range(n)]
        await bench.program(fmt, prog, [one] * n, idx, [one] * n, n,
                            f"{label}, setting the marks")
        bench._stage(fmt, prog.to_bytes(), [one] * n, idx, [one] * n, n,
                     0, 4 * n)
        bench._drive_cfg(fmt, n)
        t0 = get_sim_time("ns")
        refused, flags, err = await bench._go(4_000_000, label)
        assert refused == 0 and err == 0, (label, refused, err)
        per_block[label] = (get_sim_time("ns") - t0) / CLK_NS / blocks
        dut._log.info(f"{label}: {per_block[label]:.1f} cycles a block "
                      f"at {SCRATCH_D} slots")
    step = per_block["wide"] - per_block["narrow"]
    assert step == (32 - 8) * NBEATS, (
        f"slots 8 to 31 cost {step:.1f} cycles a block, where their wipe "
        f"is {(32 - 8) * NBEATS}: the wipe is not following what was "
        f"written (SCRATCH_D {SCRATCH_D})")
    slack = 4 * NBEATS
    assert per_block["wide"] <= per_block["static"] + slack, (
        f"an indexing block costs {per_block['wide']:.1f} cycles and its "
        f"static twin {per_block['static']:.1f}: the wipe is paying for "
        f"slots nothing wrote (SCRATCH_D {SCRATCH_D})")


# ---- revision 7, the second send-back: the widest wipe, and a preload
#      nothing reads (verifier-R5, 08:03:27 and 08:16:48) ----------------
#
# The marks start all dirty at a reset, so the first indexing block after
# one wiped the whole depth - 32,768 cycles at 2,048 slots, where every
# indexing block at 256 had paid 4,096 - and so did the block after a
# program that wrote the top slot. cft_seq now BROADCASTS a wipe wider
# than one sub-array (4,096 entries, 256 slots at NBEATS 16): +0 at the
# same local address in every sub-array at once, the whole memory in
# 4,096 cycles, every mark clean after it. And a block that can observe
# no scratch slot - no scratch instruction, no scratch-out - loads none
# of its scratch-in block, which revision 3 did only by accident.

SUB_SLOTS = min(SCRATCH_D, 4096 // NBEATS)    # one sub-array's slots


async def _reset(dut):
    """ap_rst_n, as Bench.start pulls it: every mark comes back dirty."""
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)


async def _timed(bench, fmt, prog, a, b, c, n, label, *, scratch_in=None,
                 idx_scratch_in=None):
    """One run, staged as program() stages it and not compared: its
    cycles from start to done (and the eight _go waits after it)."""
    ebytes = fmt.width // 8
    bench._stage(fmt, prog.to_bytes(), a, b, c, n,
                 n * prog.max_deposits * ebytes, 4 * n,
                 scratch_in=scratch_in)
    if idx_scratch_in is not None:
        raw = b"".join(int(t).to_bytes(4, "little") for t in idx_scratch_in)
        raw += bytes(POISON for _ in range(-len(raw) % BEAT_BYTES))
        bench.ram.stage(ISI_BASE, raw)
    bench._drive_cfg(fmt, n, scratch=prog.scratch_io,
                     idx_mask=8 if idx_scratch_in is not None else 0)
    t0 = get_sim_time("ns")
    refused, flags, err = await bench._go(4_000_000, label)
    assert refused == 0 and err == 0, (label, refused, err)
    return (get_sim_time("ns") - t0) / CLK_NS


class _BroadcastWatch:
    """Every broadcast wipe's clean, held where it happens: in the cycle
    scr_clean_go is high with scr_bcast, the clean's bound must be
    SCRATCH_D, and on the next edge every mark must read 0 - the whole
    memory is +0 after a broadcast, and the marks must say so."""

    def __init__(self, dut):
        self.dut, self.seen, self.bad = dut, 0, []
        cocotb.start_soon(self._run())

    async def _run(self):
        dut = self.dut
        while True:
            await RisingEdge(dut.ap_clk)
            await ReadOnly()
            if _i(dut.scr_clean_go) and _i(dut.scr_bcast):
                bnd = _i(dut.scr_wipe_bnd)
                await RisingEdge(dut.ap_clk)
                await ReadOnly()
                hwm = _i(dut.scr_hwm, -1)
                self.seen += 1
                if bnd != SCRATCH_D or hwm != 0:
                    self.bad.append((bnd, hwm))

    def check(self, expect_some):
        assert not self.bad, (
            f"a broadcast wipe's clean left (bound, marks) {self.bad[:3]}: "
            f"the bound must be {SCRATCH_D} and every mark 0 after it")
        if expect_some:
            assert self.seen, (
                "no broadcast wipe happened on a build whose banks are "
                "sub-arrays: a wipe wider than one sub-array must take it")
        else:
            assert not self.seen, (
                f"{self.seen} broadcast wipe(s) on a build of one array a "
                f"bank ({SCRATCH_D} slots)")


@cocotb.test()
async def scratch_first_block_after_reset_costs_one_sub_array(dut):
    """The first indexing block after a reset, and the block after a
    program that stored at the top slot, against a block whose wipe is
    one sub-array's slots - f681dee's wipe of EVERY indexing block at
    256. One block of 128 fp32 lanes each: `ldl r4, SUB_SLOTS - 1` after
    a reset (a 256-slot wipe), `ldx r4, r0` after a reset (every mark
    dirty: the whole depth, broadcast at 2,048), and `ldx` again after a
    store at the top slot. Each ldx block may cost the ldl block plus
    four slots' wipe - STX/LDX's own cost against STL/LDL is 18 - and no
    more, at 256 slots and at 2,048. Before the broadcast the first ldx
    block at 2,048 cost 32,921 cycles against about 4,235.

    And verifier-R5's own row, logged: the first four-block ldx run
    after a reset, its block 0 by R5's arithmetic - four times the run's
    mean less three of the next run's blocks (f681dee 4,249)."""
    bench = Bench(dut)
    await bench.start()
    watch = _BroadcastWatch(dut)
    fmt = FP32
    lpb = lanes_per_block(fmt)
    n = lpb
    zeros = [0] * n
    one = sf.one_bits(fmt)
    ldl = seq.Program(fmt, [seq.ldl(4, SUB_SLOTS - 1), seq.halt()],
                      max_deposits=0)
    ldx = seq.Program(fmt, [seq.ldx(4, 0), seq.halt()], max_deposits=0)
    top = seq.Program(fmt, [seq.stx(1, 0), seq.halt()], max_deposits=0)

    await _reset(dut)
    t_ldl = await _timed(bench, fmt, ldl, zeros, zeros, zeros, n,
                         "ldl of the last slot of a sub-array, after a reset")
    await _reset(dut)
    t_ldx = await _timed(bench, fmt, ldx, zeros, zeros, zeros, n,
                         "ldx, the first block after a reset")
    await _timed(bench, fmt, top, [_int_bits(fmt, SCRATCH_D - 1)] * n,
                 [one] * n, zeros, n, "stx at the top slot")
    t_top = await _timed(bench, fmt, ldx, zeros, zeros, zeros, n,
                         "ldx, the block after a store at the top slot")
    dut._log.info(f"one block at {SCRATCH_D} slots: ldl of slot "
                  f"{SUB_SLOTS - 1} after a reset {t_ldl:.0f} cycles; ldx "
                  f"after a reset {t_ldx:.0f}; ldx after the top slot "
                  f"{t_top:.0f}")
    slack = 4 * NBEATS
    for label, t in (("the first ldx block after a reset", t_ldx),
                     ("the ldx block after a store at the top slot", t_top)):
        assert t <= t_ldl + slack, (
            f"{label} costs {t:.0f} cycles and a block that wipes one "
            f"sub-array's {SUB_SLOTS} slots {t_ldl:.0f}: a wipe is paying "
            f"for more than one sub-array (SCRATCH_D {SCRATCH_D})")

    await _reset(dut)
    n4 = 4 * lpb
    first = await _timed(bench, fmt, ldx, [0] * n4, [0] * n4, [0] * n4, n4,
                         "ldx, four blocks, the first run after a reset")
    later = await _timed(bench, fmt, ldx, [0] * n4, [0] * n4, [0] * n4, n4,
                         "ldx, four blocks, the next run")
    dut._log.info(f"verifier-R5's row at {SCRATCH_D} slots: the first run "
                  f"after a reset {first / 4:.1f} cycles a block, the next "
                  f"{later / 4:.1f}; its block 0 by R5's arithmetic "
                  f"{first - 3 * later / 4:.1f} (f681dee 4,249)")
    watch.check(expect_some=SCRATCH_D > SUB_SLOTS)


@cocotb.test()
async def scratch_broadcast_just_over_one_sub_array(dut):
    """A block whose wipe is one slot more than a sub-array holds takes
    the broadcast, and reads +0 everywhere. Block 0 stores at slot
    SUB_SLOTS - the first slot of the second sub-array - in every lane,
    so every mark is SUB_SLOTS + 1 and block 1's need is one past a
    sub-array's 256; block 1 stores low and reads, lane by lane, slots
    spread over the whole depth, block 0's slot among them in the same
    lane positions, every one of which must be +0 against the model. The
    watch holds each broadcast's clean. On a 256-slot build a bank is
    one array, block 0 stores at the top slot, and no broadcast may
    happen at all."""
    bench = Bench(dut)
    await bench.start()
    watch = _BroadcastWatch(dut)
    fmt = FP32
    lpb = lanes_per_block(fmt)
    n = 2 * lpb
    deep = SCRATCH_D > SUB_SLOTS
    wslot = SUB_SLOTS if deep else SUB_SLOTS - 1
    spread = sorted({0, 1, 5 + 1, SUB_SLOTS - 1, wslot,
                     min(wslot + 1, SCRATCH_D - 1), SCRATCH_D // 2 + 3,
                     SCRATCH_D - 1})
    wr = [wslot if i < lpb else 5 for i in range(n)]
    rd = [wslot if i < lpb else spread[i % len(spread)] for i in range(n)]
    vals = [0x3F80_0000 + i for i in range(n)]
    want = await bench.program(
        fmt, _walk_prog(fmt), [_int_bits(fmt, v) for v in wr],
        [_int_bits(fmt, v) for v in rd], vals, n,
        f"block 0 at slot {wslot}, block 1 reading {spread}")
    assert want.deposits[:lpb] == vals[:lpb], \
        "block 0 must read back what it wrote"
    assert want.deposits[lpb:] == [0] * lpb, \
        "block 1 reads slots its lanes never wrote: +0"
    # Block 0's wipe follows a reset (every mark dirty) and block 1's
    # follows block 0 (every mark SUB_SLOTS + 1): both broadcast.
    if deep:
        assert watch.seen >= 2, (
            f"{watch.seen} broadcast(s): block 1's need was "
            f"{SUB_SLOTS + 1} slots, one past a sub-array, and had to "
            f"broadcast")
    watch.check(expect_some=deep)
    dut._log.info(f"a need of {wslot + 1} slots at {SCRATCH_D}: "
                  f"{watch.seen} broadcast(s), every mark 0 after each, "
                  f"every slot read +0")


@cocotb.test()
async def scratch_preload_nothing_reads_is_not_loaded(dut):
    """A declared scratch-in block that no instruction and no drain can
    read is not loaded, dense or gathered. One block of 128 fp32 lanes,
    n_scratch_in = SUB_SLOTS (256), n_scratch_out 0, the program [halt]:
    it must cost what [halt] alone costs, and not one read may land in
    its block, pool or table. Before the skip: 36,947 cycles at 256
    slots and 36,950 at 2,048 (f681dee 80). The control reads the last
    slot of the same block: the model's answer, the preload really made
    (at least a cycle an element dearer than the unread block), and its
    cycles logged against R5's 41,300."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    lpb = lanes_per_block(fmt)
    n = lpb
    k = SUB_SLOTS
    zeros = [0] * n
    halt = seq.Program(fmt, [seq.halt()], max_deposits=0)
    unread = seq.Program(fmt, [seq.halt()], max_deposits=0,
                         flags=seq.FLAG_SCRATCH_IO, n_scratch_in=k,
                         n_scratch_out=0)
    block = operands(fmt, n * k, 9700)
    t_halt = await _timed(bench, fmt, halt, zeros, zeros, zeros, n,
                          "[halt], no block")
    t_dense = await _timed(bench, fmt, unread, zeros, zeros, zeros, n,
                           f"[halt] with a {k}-slot block, dense",
                           scratch_in=block)
    got = bench.ram.reads_in(SIN_BASE, SIN_BASE + n * k * 4 + BEAT_BYTES)
    assert not got, (
        f"the unread block was read {len(got)} time(s): {got[:4]}")
    pool = operands(fmt, 64, 9701)
    tbl = [(7 * i) % len(pool) for i in range(n * k)]
    t_gath = await _timed(bench, fmt, unread, zeros, zeros, zeros, n,
                          f"[halt] with a {k}-slot block, gathered",
                          scratch_in=pool, idx_scratch_in=tbl)
    got = (bench.ram.reads_in(ISI_BASE, ISI_BASE + n * k * 4 + BEAT_BYTES)
           + bench.ram.reads_in(SIN_BASE, SIN_BASE + len(pool) * 4
                                + BEAT_BYTES))
    assert not got, (
        f"the unread gathered block's table or pool was read {len(got)} "
        f"time(s): {got[:4]}")
    dut._log.info(f"one block at {SCRATCH_D} slots: [halt] {t_halt:.0f} "
                  f"cycles; with an unread {k}-slot block {t_dense:.0f} "
                  f"dense, {t_gath:.0f} gathered (f681dee 80 dense)")
    for label, t in (("dense", t_dense), ("gathered", t_gath)):
        assert t <= t_halt, (
            f"an unread {k}-slot block, {label}, costs {t:.0f} cycles and "
            f"[halt] alone {t_halt:.0f}: a block nothing can read was "
            f"loaded")

    read = seq.Program(fmt, [seq.ldl(4, k - 1), seq.deposit(4), seq.halt()],
                       max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
                       n_scratch_in=k, n_scratch_out=0)
    await bench.program(fmt, read, zeros, zeros, zeros, n,
                        f"the same block, slot {k - 1} read", scratch_in=block)
    t_read = await _timed(bench, fmt, read, zeros, zeros, zeros, n,
                          "the read block, timed", scratch_in=block)
    dut._log.info(f"the same block with slot {k - 1} read: {t_read:.0f} "
                  f"cycles (R5: 41,300 at f681dee and at 2276052)")
    assert t_read >= t_dense + n * k, (
        f"a block whose slot {k - 1} is read costs {t_read:.0f} cycles, "
        f"under the {n * k} elements it must load one a cycle")


# ---- the marks' other writers, and the wait they made load-bearing ------
#
# verifier-R5 (08:34:13) planted four faults at 256 slots that no case
# above could see: the preload's writes and the gather's flagged as the
# wipe's (the marks blind to them), S_ZERO's wait for the two scratch
# products removed, and scr_dirty_q's tree reading four banks of eight.
# Each case below is red for one of them, at 256 slots and at 2,048 -
# where every dirty region here is wider than a sub-array, so the wipe
# that must cover it is the BROADCAST.

def _nonzero(count, seed):
    """Distinct fp32 values in [1, 2): never +0, so a slot that should
    have been wiped and was not, or loaded and was not, cannot pass."""
    return [0x3F80_0000 | ((seed * 7919 + i * 104729) & 0x7F_FFFF)
            for i in range(count)]


async def _clean_marks(bench, fmt, label):
    """An indexing block that stores nothing: its wipe covers every dirty
    slot and cleans every mark. It reads slot 0, which must be +0."""
    n = lanes_per_block(fmt)
    await bench.program(
        fmt, seq.Program(fmt, [seq.ldx(4, 0), seq.deposit(4), seq.halt()],
                         max_deposits=1),
        [0] * n, [0] * n, [0] * n, n, f"{label}: an indexing block cleans "
        f"the marks")


@cocotb.test()
async def scratch_preload_and_gather_raise_the_marks(dut):
    """The scratch-in block's writes are writes: they must raise the
    marks, dense and gathered, or the next run's wipe stops short of
    them. From clean marks, run A preloads K slots a lane and reads slot
    0 (so the block is observed and loaded whole); run B, with no block,
    reads slot K - 7 through STX/LDX's index - a slot its lanes never
    wrote, so +0 against the model, which only a wipe reaching past the
    preload can give. K is 256 on a 256-slot build and 300 at 2,048,
    where run B's wipe is the broadcast. Forty-eight lanes, six in each
    word bank: the gathered block's table is then under the 64 KiB
    window this bench's read check watches (48 x 300 entries)."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    n = 48
    k = 300 if SCRATCH_D > SUB_SLOTS else SCRATCH_D
    rslot = k - 7
    zeros = [0] * n
    load = seq.Program(fmt, [seq.ldl(4, 0), seq.deposit(4), seq.halt()],
                       max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
                       n_scratch_in=k, n_scratch_out=0)
    probe = seq.Program(fmt, [seq.ldx(4, 0), seq.deposit(4), seq.halt()],
                        max_deposits=1)
    for form in ("dense", "gathered"):
        await _clean_marks(bench, fmt, form)
        if form == "dense":
            await bench.program(fmt, load, zeros, zeros, zeros, n,
                                f"run A: a {k}-slot block, dense",
                                scratch_in=_nonzero(n * k, 1))
        else:
            pool = _nonzero(97, 2)
            await bench.gathered(fmt, load, zeros, zeros, zeros, n,
                                 f"run A: a {k}-slot block, gathered",
                                 scratch_in=pool,
                                 idx_scratch_in=[(5 * i + 1) % len(pool)
                                                 for i in range(n * k)])
        want = await bench.program(
            fmt, probe, [_int_bits(fmt, rslot)] * n, zeros, zeros, n,
            f"run B: an indexing read of slot {rslot} after a {form} block")
        assert want.deposits == [0] * n, \
            "run B's lanes never wrote the slot: +0"
    dut._log.info(f"a {k}-slot block, dense and gathered, raises the marks: "
                  f"the next run's wipe reached slot {rslot}")


@cocotb.test()
async def scratch_preload_read_with_the_marks_clean(dut):
    """S_ZERO waits for the scratch-in and scratch-out products. With the
    marks clean a block whose scratch nothing has written wipes nothing,
    so S_ZERO would otherwise last only its CW + 1 multiplier steps - 8
    at MAXD 64 - and a nine-bit n_scratch_in of 256 would be cut to 0:
    nothing preloaded, nothing drained. From clean marks, a block of
    SUB_SLOTS slots in and out reads its last slot; and at 2,048 the
    whole depth as well, twelve bits against MAXD 1,024's twelve steps -
    over eight lanes, one a word bank: at 2,048 slots a lane, 128 lanes'
    blocks in and out are a mebibyte each way and run over this bench's
    memory map, where eight lanes' are 64 KiB. The product's steps are
    the count's bits whatever the lane count."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    for k in sorted({SUB_SLOTS, SCRATCH_D}):
        n = lanes_per_block(fmt) if k <= SUB_SLOTS else 8
        zeros = [0] * n
        await _clean_marks(bench, fmt, f"{k} slots")
        prog = seq.Program(fmt, [seq.ldl(4, k - 1), seq.deposit(4),
                                 seq.halt()],
                           max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
                           n_scratch_in=k, n_scratch_out=k)
        want = await bench.program(
            fmt, prog, zeros, zeros, zeros, n,
            f"a {k}-slot block in and out, slot {k - 1} read, marks clean",
            scratch_in=_nonzero(n * k, 3 + k))
        assert all(d != 0 for d in want.deposits), \
            "every lane reads a preloaded, nonzero slot"
    dut._log.info("a preload and a drain with the marks clean: whole, at "
                  f"{sorted({SUB_SLOTS, SCRATCH_D})} slots")


@cocotb.test()
async def scratch_marks_are_per_bank(dut):
    """The dirty register is the maximum over EVERY bank's mark. For each
    word bank b in turn, from clean marks: run A stores high in bank b's
    lanes alone (slot H) and low in the rest (slot 3); run S, static,
    names slot 3 alone, so its wipe cleans every mark but bank b's; run B
    reads slot H in every lane, which its lanes never wrote - +0 against
    the model only if run B's wipe saw bank b's mark. H is 200 on a
    256-slot build and 2,000 at 2,048, where the wipe is the broadcast."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    n = lanes_per_block(fmt)
    words = BEAT_BITS // 32
    per_beat = BEAT_BITS // fmt.width
    high = 2000 if SCRATCH_D > SUB_SLOTS else 200
    vals = _nonzero(n, 4)
    walk = _walk_prog(fmt)
    stat = seq.Program(fmt, [seq.stl(0, 3), seq.ldl(3, 3), seq.deposit(3),
                             seq.halt()], max_deposits=1)
    for b in range(words):
        await _clean_marks(bench, fmt, f"bank {b}")
        # fp32: a beat holds eight lanes, lane i in word bank i % 8
        wr = [high if (i % per_beat) == b else 3 for i in range(n)]
        want = await bench.program(
            fmt, walk, [_int_bits(fmt, v) for v in wr],
            [_int_bits(fmt, v) for v in wr], vals, n,
            f"run A: bank {b} at slot {high}, the rest at 3")
        assert want.deposits == vals, "run A reads back its own stores"
        await bench.program(fmt, stat, vals, vals, vals, n,
                            f"run S: slot 3 alone, after bank {b}")
        want = await bench.program(
            fmt, walk, [_int_bits(fmt, 5)] * n, [_int_bits(fmt, high)] * n,
            vals, n, f"run B: slot {high} in every lane, after bank {b}")
        assert want.deposits == [0] * n, \
            "run B's lanes never wrote the slot: +0"
    dut._log.info(f"each of the {words} banks' marks alone kept run B's "
                  f"wipe at slot {high}")


@cocotb.test()
async def scratch_drain_is_the_preloads_only_reader(dut):
    """A scratch-in block whose ONLY reader is the scratch-out drain:
    [halt], n_scratch_in = n_scratch_out = K. No instruction names a
    slot, but the drain reads K slots a lane, so the span the skip rule
    reads is K and the block must load whole - the scratch-out block is
    the preload, element for element, against the model. K is 7 and then
    256, or 300 at 2,048, where the block reaches past a sub-array.
    verifier-R5's plant q2 (the skip rule blind to the drain) skips the
    preload and drains something else."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    n = 48
    zeros = [0] * n
    for k in (7, 300 if SCRATCH_D > SUB_SLOTS else SCRATCH_D):
        block = _nonzero(n * k, 5 + k)
        prog = seq.Program(fmt, [seq.halt()], max_deposits=0,
                           flags=seq.FLAG_SCRATCH_IO, n_scratch_in=k,
                           n_scratch_out=k)
        want = await bench.program(
            fmt, prog, zeros, zeros, zeros, n,
            f"[halt], a {k}-slot block in and drained out, no instruction "
            f"reading it", scratch_in=block)
        assert want.scratch_out == block, \
            "the model drains the preload it was given"
    dut._log.info("a preload whose only reader is the drain: loaded whole "
                  "and drained, at 7 slots and past 256")


# ======================================================================
# 10b. the whole divide and square root: two hundred instructions of
#      real register traffic, with every hazard the overlap can meet
# ======================================================================

def _mixed_operands(fmt, n, seed):
    """Every class in both signs, then randoms: the operands that make a
    divide take every path through its program."""
    rng = random.Random(seed)
    w, mw = fmt.width, fmt.man_w
    pool = [0, fmt.sign_mask, sf.inf_bits(fmt, 0), sf.inf_bits(fmt, 1),
            sf.qnan_bits(fmt), sf.snan_bits(fmt), 1, fmt.man_mask,
            sf.min_normal_bits(fmt), sf.one_bits(fmt), sf.one_bits(fmt, 1),
            sf.max_normal_bits(fmt), (fmt.bias - 1) << mw, (fmt.bias + 1) << mw]
    out = list(pool[:n])
    while len(out) < n:
        out.append(rng.getrandbits(w))
    return out


@cocotb.test()
async def the_whole_divide_and_root(dut):
    """divfull's programs through the machine: the raw operands in, the
    correctly rounded result and its flags out, over a block boundary,
    in two rounding attributes, against the model's executor.

    Why this case exists (2026-09-14): the instruction overlap lets an
    ALU instruction issue while the previous one retires, gated by one
    read-after-write check. These programs are ~210 instructions of
    dense register reuse - the same register written and read three
    instructions apart, written twice in a row, read by a SELECT that
    the previous instruction wrote - and a masked lane (a special) beside
    an active one in every beat. If the overlap ever issued a read
    against a destination still in flight, this is where a bit would
    move; the model, which runs one instruction at a time, is the
    definition.
    """
    from cft_golden import divfull
    bench = Bench(dut)
    await bench.start()
    for name, n in (("fp32", 40), ("fp64", 40), ("fp128", 40)):
        fmt = FORMATS[name]
        for rnd in (sf.RND_RNE, sf.RND_RDN):
            a = _mixed_operands(fmt, n, 900 + rnd)
            b = _mixed_operands(fmt, n, 950 + rnd)
            c = operands(fmt, n, 990)
            await bench.program(fmt, divfull.div_full_program_for(fmt),
                                a, b, c, n, f"{name} whole divide rnd={rnd}",
                                bank=divfull.bank(fmt, rnd))
            await bench.program(fmt, divfull.sqrt_full_program_for(fmt),
                                a, b, c, n, f"{name} whole root rnd={rnd}",
                                bank=divfull.bank_sqrt(fmt, rnd))


# ======================================================================
# 10c. the issue pipe at every block length, with every hazard shape
# ======================================================================

def _pipe_program(fmt):
    """Every shape the streaming issue has to get right, in one program:
    a dependent chain, a read of two producers at once, a write after a
    write and a write after a read of the same register, constants at
    an instruction boundary, three independent instructions then one
    that reads all three, a loop whose body depends on itself, a mask
    change in the middle, a register nothing wrote, and deposits."""
    A, M, F = sf.OP_ADD, sf.OP_MUL, sf.OP_FMA
    one, two = sf.one_bits(fmt), sf.from_int(fmt, 2)[0]
    insns = [
        seq.alu(A, 3, 0, 1),               # r3  = a + b
        seq.alu(M, 4, 3, 2),               # r4  = r3 * c        (reads the one before)
        seq.alu(A, 5, 4, 3),               # r5  = r4 + r3       (two producers)
        seq.alu(F, 6, 5, 4, 3),            # r6  = r5 * r4 + r3  (three)
        seq.alu(A, 7, 0, 1),               # r7  = a + b
        seq.alu(M, 7, 7, 2),               # r7  = r7 * c        (write after write, and read)
        seq.alu(A, 8, 7, 0),               # r8  = r7 + a        (reads r7...)
        seq.alu(A, 7, 1, 2),               # r7  = b + c         (...which is then overwritten)
        seq.alu(F, 9, 3, 0, 1, kb=True, kc=True),   # r9 = r3 * K0 + K1 (constants at a boundary)
        seq.alu(A, 10, 0, 1),              # three with nothing between them
        seq.alu(A, 11, 1, 2),
        seq.alu(A, 12, 0, 2),
        seq.alu(F, 13, 10, 11, 12),        # r13 = r10 * r11 + r12 (all three in flight)
        seq.alu(A, 14, 9, 0),              # r14 = r9 + a
        seq.repeat(3),
        seq.alu(F, 14, 14, 3, 1, kc=True), # r14 = r14 * r3 + K1  (a loop on itself)
        seq.endrep(),
        seq.alu(sf.OP_CMPLT, 15, 0, 1),    # r15 = a < b
        seq.setact(15),                    # half the lanes go quiet...
        seq.alu(A, 3, 3, 4),               # r3  = r3 + r4  (masked write over a live value)
        seq.alu(M, 16, 13, 6),             # r16 = r13 * r6 (a high register, masked)
        seq.actall(),                      # ...and come back
        seq.alu(A, 17, 16, 3),             # r17 = r16 + r3 (reads what the mask left)
        seq.deposit(6), seq.deposit(8), seq.deposit(9), seq.deposit(13),
        seq.deposit(14), seq.deposit(17), seq.deposit(29),   # r29: never written, +0
        seq.halt(),
    ]
    return seq.Program(fmt, insns, consts=[one, two], max_deposits=7)


@cocotb.test()
async def the_pipe_at_every_block_length(dut):
    """The streaming issue (docs/SEQUENCER.md, R14) against the model at
    every block length a run can have.

    The issue is a three-stage pipe that fetches the next instruction
    under this one and admits it the cycle after this one's last
    address; up to three instructions are in flight and a dependent
    beat waits, at its address, for the producer's beat to land. Every
    one of those mechanisms changes shape with the block length: a
    one-beat block never admits by continuation, a two-beat block has
    the producer's beat still in the fire stage when the consumer's
    address comes up (the hang of the first attempt), a five-beat block
    fills the queue, a sixteen-beat block never holds. So the same
    program runs at 1, 2, 3, 5, 9 and 16 beats and ragged in between,
    across a block boundary, at three formats.
    """
    bench = Bench(dut)
    await bench.start()
    for name, ns in (("fp32", (8, 9, 16, 24, 40, 72, 128, 136, 150)),
                     ("fp64", (4, 5, 8, 20, 64, 66)),
                     ("fp128", (2, 3, 10, 32, 33))):
        fmt = FORMATS[name]
        prog = _pipe_program(fmt)
        for n in ns:
            await bench.program(fmt, prog, operands(fmt, n, 1200 + n),
                                operands(fmt, n, 1300 + n),
                                operands(fmt, n, 1400 + n), n,
                                f"{name} the pipe at n={n}")


# ======================================================================
# 10d. revision 7, R18: the control codes in the pipe, at every block
#      length, with every hazard shape the change creates
# ======================================================================
#
# Until R18 every control code that read the file, moved the mask or
# ended the block waited for the queue of results to EMPTY and then
# walked the block's beats in states of its own. Now DEPOSIT, SETACT and
# the four scratch codes go through the issue pipe one beat a cycle and
# wait, a beat at a time, only for a queued producer of what they read;
# the loads ride the array (IOR(v, v)) and take a queue slot, so they
# are producers themselves; the active row is taken when a beat FIRES
# rather than when its result retires; and ACTALL, and what ends the
# block, wait for the pipe rather than for nothing or the queue. The
# rules are docs/SEQUENCER.md's R18. Every case below runs against the
# model's one-instruction-at-a-time executor, which is the definition.

def _r18_index_stream(fmt, n, seed):
    """Integers as bit patterns, a third of them in range: what an
    indexed code reads as rb. The rest are past the depth by whole
    multiples of it, so the modulo lands them on the same slots the
    in-range lanes use, and SCRATCH_STRICT suppresses them."""
    rng = random.Random(seed)
    return [_int_bits(fmt, rng.randrange(8) + SCRATCH_D * (i % 3))
            for i in range(n)]


def _ctl_program(fmt, strict=False):
    """Every hazard shape R18 creates, in one program.

    (1) a control code reading a destination still in flight (a deposit
    and a store of the ADD before them, both forwarded at F), and one
    reading nothing queued; (2) a store then a load of the same slot at
    once - which a short block makes the store's write and the load's
    read adjacent - then the loaded register used at once; (3) a load
    into a register a queued FMA writes, and the other order; (4) a
    store reading a register the instruction behind it overwrites;
    (5) the indexed forms with a COMPUTED index, a store then an indexed
    load of the same slot, two LDXs back to back, an instruction that
    does NOT depend on an LDX straight after one (the only shape the
    LDX gap is for), an LDL straight after an LDX (one scratch read
    port), a static store and load straight after an LDX, and an index
    that is a LOADED value;
    (6) a loop whose body loads, computes, stores and narrows the mask;
    (7) the mask moving while an FMA's results are still in the array,
    and SETACT reading a loaded register; then ACTALL, the FMA's
    destination deposited for every lane - a lane the SETACT dropped
    shows whether its result was written under the row it FIRED with -
    and nothing after it that could raise a flag, so a ragged block
    reads the same whether or not ACTALL wakes the padding (the bench's
    precondition).
    """
    A, M, F = sf.OP_ADD, sf.OP_MUL, sf.OP_FMA
    IADD, CMPLT = sf.OP_IADD, sf.OP_CMPLT
    insns = [
        # (1)
        seq.alu(A, 3, 0, rc=1),              # r3 = a + b
        seq.deposit(3),                      # r3 in flight
        seq.stl(3, 0),                       # slot 0 := r3, in flight
        seq.deposit(1),                      # nothing queued writes r1
        # (2)
        seq.ldl(4, 0),                       # r4 = slot 0, just stored
        seq.alu(M, 5, 4, 1),                 # r5 = r4 * b: reads the load
        seq.deposit(5),
        # (3)
        seq.alu(F, 6, 0, 1, 3),              # r6 = a*b + r3, in flight...
        seq.ldl(6, 0),                       # ...when the load writes r6
        seq.deposit(6),                      # the load's value, not the FMA's
        seq.ldl(7, 0),
        seq.alu(A, 7, 0, rc=2),              # r7 = a + c, after the load
        seq.deposit(7),
        # (4)
        seq.alu(A, 8, 1, rc=0),              # r8 = b + a
        seq.stl(8, 1),                       # slot 1 := r8 (waits on the ADD)
        seq.alu(M, 8, 0, 0),                 # r8 = a * a, after the store read
        seq.ldl(9, 1),                       # r9 = slot 1 = the OLD r8
        seq.deposit(9),
        # (5)
        seq.alu(IADD, 10, 2, 0, kb=True),    # r10 = c + 5, an integer
        seq.stx(3, 10),                      # scratch[r10] := r3
        seq.ldx(11, 10),                     # r11 = scratch[r10], the same slot
        seq.deposit(11),                     # an LDX's result, at once
        seq.ldx(12, 2),                      # two LDXs back to back
        seq.ldx(13, 10),
        seq.alu(A, 24, 0, rc=1),             # INDEPENDENT of them: the gap
        seq.ldx(25, 2),
        seq.ldl(26, 1),                      # an LDL straight after an LDX:
                                             # one scratch read port
        seq.deposit(24),
        seq.deposit(26),
        seq.stl(12, 2),                      # a store straight after them
        seq.ldl(14, 2),                      # and a load straight after it
        seq.alu(A, 15, 13, rc=14),           # r15 = r13 + r14
        seq.deposit(15),
        seq.ldx(16, 11),                     # an index that was LOADED
        seq.deposit(16),
        # (6)
        seq.repeat(3),
        seq.ldl(21, 4),
        seq.alu(F, 21, 21, 0, 1),            # r21 = r21 * a + b
        seq.stl(21, 4),
        seq.alu(CMPLT, 22, 21, 0),           # r22 = r21 < a
        seq.setact(22),                      # lanes drop out
        seq.endrep(),
        # (7)
        seq.alu(CMPLT, 17, 0, 1),            # r17 = a < b
        seq.alu(F, 18, 0, 1, 3),             # r18 = a*b + r3, in flight...
        seq.setact(17),                      # ...when the mask narrows
        seq.alu(A, 19, 18, rc=0),            # r19 = r18 + a, narrowed
        seq.deposit(18),
        seq.deposit(19),
        seq.stl(19, 3),                      # a store under the narrowed mask
        seq.setact(4),                       # SETACT reading a LOADED register
        seq.ldl(20, 3),
        seq.deposit(20),
        seq.actall(),
        seq.deposit(18),                     # a dropped lane's FMA result:
                                             # written under the row it FIRED
                                             # with, before the SETACT
        seq.deposit(19),                     # a dropped lane's r19: +0
        seq.deposit(20),
        seq.ldl(23, 4),
        seq.deposit(23),
        seq.halt(),
    ]
    flags = seq.FLAG_SCRATCH_IO
    if strict:
        flags |= seq.FLAG_SCRATCH_STRICT
    return seq.Program(fmt, insns, consts=[_int_bits(fmt, 5),
                                           sf.one_bits(fmt)],
                       max_deposits=19, flags=flags,
                       n_scratch_in=0, n_scratch_out=6)


@cocotb.test()
async def control_codes_at_every_block_length(dut):
    """R18 against the model at every block length a run can have.

    The same block lengths the_pipe_at_every_block_length uses, because
    the same mechanisms change shape with them: a one-beat block puts a
    store's write and the next load's read in adjacent steps (the
    store-then-load wait), a two-beat block has an LDX's value still in
    G or H when the next instruction's first beat comes up (the LDX
    gap), five beats fill the queue, and sixteen never hold. Each run
    twice: the modulo, and SCRATCH_STRICT with two lanes in three
    indexing past the depth, whose loads fire +0 and whose stores do
    not land.
    """
    bench = Bench(dut)
    await bench.start()
    for name, ns in (("fp32", (8, 9, 16, 24, 40, 72, 128, 136, 150)),
                     ("fp64", (4, 5, 8, 20, 64, 66)),
                     ("fp128", (2, 3, 10, 32, 33))):
        fmt = FORMATS[name]
        for strict in (False, True):
            prog = _ctl_program(fmt, strict)
            for n in ns:
                await bench.program(
                    fmt, prog, operands(fmt, n, 1700 + n),
                    operands(fmt, n, 1800 + n),
                    _r18_index_stream(fmt, n, 1900 + n), n,
                    f"{name} control codes, {'strict' if strict else 'modulo'},"
                    f" n={n}")
    dut._log.info(f"R18 hazard shapes: {bench.cases['program']} runs")


@cocotb.test()
async def mask_moves_while_results_are_in_flight(dut):
    """The smallest program that says WHEN the active bit is sampled.

    An FMA over every lane, then a SETACT that drops half of them while
    the FMA's results are still in the array, then ACTALL, then the FMA's
    destination deposited. The model runs one instruction at a time, so
    every lane was active when the FMA ran and every lane's r3 is the
    FMA's result. A retire that masked by the mask as it stands when a
    result COMES BACK - which is what the RTL did until R18, when no
    code could move the mask before the queue had emptied - would leave
    the dropped lanes' r3 at +0, and the deposit shows it. At sixteen
    beats the FMA's beat b lands one cycle after the SETACT's beat b
    has narrowed its row; at one beat, many cycles after.
    """
    bench = Bench(dut)
    await bench.start()
    for name, ns in (("fp32", (8, 16, 40, 128, 150)),
                     ("fp64", (4, 20, 64)),
                     ("fp128", (2, 10, 32))):
        fmt = FORMATS[name]
        zero, one = sf.zero_bits(fmt), sf.one_bits(fmt)
        prog = seq.Program(fmt, [
            seq.alu(sf.OP_FMA, 3, 0, 1, 2),     # every lane, in flight...
            seq.setact(1),                      # ...when half drop out
            seq.alu(sf.OP_ADD, 4, 3, rc=0),     # r4 = r3 + a, the survivors
            seq.actall(),
            seq.deposit(3),                     # every lane's FMA result
            seq.deposit(4),                     # the dropped lanes' +0
            seq.halt()], max_deposits=2)
        for n in ns:
            half = [one if (i % 2) == 0 else zero for i in range(n)]
            await bench.program(fmt, prog, dense(fmt, n, 2000 + n), half,
                                dense(fmt, n, 2100 + n), n,
                                f"{name} FMA in flight under a SETACT, n={n}")


def _halt_program(fmt):
    """HALT with an FMA's results still in the array and a store and a
    deposit just ahead of them: the FMA's FLAGS, the store's slot (the
    scratch-out block) and the deposit must all be there - the end of
    the block waits for the queue AND the pipe."""
    return seq.Program(fmt, [
        seq.alu(sf.OP_FMA, 3, 0, 1, 2),
        seq.stl(3, 0),
        seq.alu(sf.OP_MUL, 4, 3, 0),
        seq.deposit(4),
        seq.stl(4, 1),
        seq.alu(sf.OP_FMA, 5, 0, 1, 2),
        seq.halt()], max_deposits=1,
        flags=seq.FLAG_SCRATCH_IO, n_scratch_in=0, n_scratch_out=2)


@cocotb.test()
async def halt_right_after_arithmetic(dut):
    """HALT (and, in the second program, the implicit halt) straight
    after arithmetic, a store and a deposit, at every block length."""
    bench = Bench(dut)
    await bench.start()
    for name, ns in (("fp32", (8, 9, 24, 128, 136)),
                     ("fp64", (4, 5, 64, 66)),
                     ("fp128", (2, 3, 32, 33))):
        fmt = FORMATS[name]
        explicit = _halt_program(fmt)
        implicit = seq.Program(fmt, explicit.insns[:-1], max_deposits=1,
                               flags=seq.FLAG_SCRATCH_IO, n_scratch_in=0,
                               n_scratch_out=2)
        for prog, how in ((explicit, "HALT"), (implicit, "the implicit halt")):
            for n in ns:
                await bench.program(fmt, prog, operands(fmt, n, 2200 + n),
                                    operands(fmt, n, 2300 + n),
                                    operands(fmt, n, 2400 + n), n,
                                    f"{name} {how} after arithmetic, n={n}")


def _r18_random_program(fmt, rng):
    """A program that is mostly control codes, over FOUR registers and
    FOUR slots, so nearly every instruction depends on one a step or two
    before it: the densest hazard traffic the pipe can be given. Loops,
    SETACT inside them, and an ACTALL at the top level now and then."""
    regs = (3, 4, 5, 6)
    slots = (0, 1, 2, 3)
    arith = (sf.OP_ADD, sf.OP_MUL, sf.OP_FMA, sf.OP_IAND, sf.OP_IXOR,
             sf.OP_CMPLT, sf.OP_SELECT, sf.OP_MIN)
    body, depth, deposits = [], 0, 0

    def one():
        nonlocal deposits
        r = rng.random()
        rd = rng.choice(regs)
        ra, rb, rc = (rng.choice(regs + (0, 1, 2)) for _ in range(3))
        if r < 0.25:
            op = rng.choice(arith)
            return seq.alu(op, rd, ra, rb, rc)
        if r < 0.40:
            return seq.stl(ra, rng.choice(slots))
        if r < 0.55:
            return seq.ldl(rd, rng.choice(slots))
        if r < 0.63:
            return seq.stx(ra, rng.choice((2, 10)))
        if r < 0.71:
            return seq.ldx(rd, rng.choice((2, 10)))
        if r < 0.80 and deposits < 12:
            deposits += 1
            return seq.deposit(ra)
        if r < 0.86:
            return seq.setact(rng.choice((0, 1, 2) + regs))
        return seq.alu(sf.OP_IADD, 10, 2, rng.choice(regs))

    for _ in range(rng.randrange(18, 34)):
        if depth == 0 and rng.random() < 0.08:
            body.append(seq.repeat(rng.randrange(2, 4)))
            depth += 1
            continue
        if depth and rng.random() < 0.12:
            body.append(seq.endrep())
            depth -= 1
            continue
        if depth == 0 and rng.random() < 0.05:
            body.append(seq.actall())
            continue
        body.append(one())
    while depth:
        body.append(seq.endrep())
        depth -= 1
    if rng.random() < 0.5:
        body.append(seq.halt())
    strict = rng.random() < 0.5
    flags = seq.FLAG_SCRATCH_IO | (seq.FLAG_SCRATCH_STRICT if strict else 0)
    return seq.Program(fmt, body, max_deposits=12, flags=flags,
                       n_scratch_in=0, n_scratch_out=4)


@cocotb.test()
async def control_code_fuzz_at_short_blocks(dut):
    """Programs that are mostly control codes, over four registers and
    four slots, at one, two, three and sixteen beats and across a block
    boundary - the block lengths where the pipe's holds bind. Every run
    against the model, whole machine: deposits, counts, the scratch-out
    block, FLAGS and STATUS. ACTALL can read a ragged block two ways
    (the module docstring), so a program that has one runs block-
    aligned."""
    bench = Bench(dut)
    await bench.start()
    rng = random.Random(20260929)
    runs = 0
    for name, ns in (("fp32", (8, 16, 24, 128, 136)),
                     ("fp64", (4, 8, 12, 64, 68)),
                     ("fp128", (2, 4, 6, 32, 34))):
        fmt = FORMATS[name]
        for n in ns:
            for _ in range(3):
                while True:
                    try:
                        prog = _r18_random_program(fmt, rng)
                    except seq.ProgramError:
                        continue           # a shape the loader refuses
                    break
                m = n
                if has_actall(prog.insns):
                    lpb = lanes_per_block(fmt)
                    m = -(-n // lpb) * lpb
                await bench.program(fmt, prog,
                                    operands(fmt, m, rng.randrange(1 << 20)),
                                    operands(fmt, m, rng.randrange(1 << 20)),
                                    _r18_index_stream(fmt, m,
                                                      rng.randrange(1 << 20)),
                                    m, f"{name} R18 fuzz n={m} #{runs}")
                runs += 1
    dut._log.info(f"R18 control-code fuzz: {runs} programs")


def _hold_programs(fmt):
    """The two control-code-heavy programs R18's cost is held on."""
    F = sf.OP_FMA
    indep = []
    for k in range(8):
        indep += [seq.stl(0, k), seq.ldl(3 + k, 8 + k), seq.setact(1)]
    indep += [seq.deposit(10), seq.halt()]
    chain = []
    for k in range(8):
        chain += [seq.ldl(3 + k, k), seq.alu(F, 11 + k, 3 + k, 0, 1),
                  seq.stl(11 + k, 8 + k)]
    chain += [seq.deposit(18), seq.halt()]
    return (("24 control codes, independent", indep),
            ("8 x (load, FMA of it, store of that)", chain))


# Cycles a block at fp32, four blocks of 128 lanes, through this bench's
# harness (the unit bench's model RAM answers at once). BEFORE is
# f681dee's tile, where every one of these codes waited for the queue to
# empty and walked the block at three cycles a beat, five for a load;
# AFTER is revision 7's. The ceiling sits between the two: a change that
# took the control codes back out of the pipe lands above it, and one
# that only moves a cycle or two does not. Measured under Verilator
# (2026-09-29), cycles a block:
#
#   24 control codes, independent    before 2011.2   after 898.2 (898.2 at MC=10)
#   8 x (load, FMA of it, store)     before 1891.2   after 920.2 (960.2 at MC=10)
HOLD_CEILING = {
    "24 control codes, independent": 1400,
    "8 x (load, FMA of it, store of that)": 1400,
}


@cocotb.test()
async def control_codes_hold_their_overlap(dut):
    """R18's gain, HELD: two control-code-heavy programs must cost less
    a block than the ceiling that sits between the before- and the
    after-side, and must answer exactly what the model says.

    The first program is twenty-four control codes with no dependence
    between them (a store, a load and a SETACT, eight times over); the
    second is the pattern the ODE census priced - a load, an FMA of what
    it loaded, a store of what the FMA made, eight times over - where
    every code waits on the one before it. fp32 is single-pass at every
    MUL_PASSES, so the ceiling holds on the multi-pass tile too; there
    the dependent program pays R14's rule instead of forwarding, which
    is still well under it. The measured numbers are in
    docs/SEQUENCER.md's revision-7 section.
    """
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    n = 4 * lanes_per_block(fmt)
    # Every program measured before any is judged, so a red run still
    # prints every number.
    cost = {}
    for label, insns in _hold_programs(fmt):
        prog = seq.Program(fmt, insns, max_deposits=1)
        await bench.program(fmt, prog, operands(fmt, n, 2500),
                            operands(fmt, n, 2501), operands(fmt, n, 2502),
                            n, f"hold: {label}")
        cost[label] = bench.last_cycles / 4
        dut._log.info(f"hold: {label}: {cost[label]:.1f} cycles a block "
                      f"(ceiling {HOLD_CEILING[label]})")
    for label, per_block in cost.items():
        assert per_block < HOLD_CEILING[label], (
            f"hold: {label} costs {per_block:.1f} cycles a block, at or above "
            f"the ceiling of {HOLD_CEILING[label]} - the control codes have "
            f"left the issue pipe (docs/SEQUENCER.md, revision 7, R18)")


def _every_bit_pattern(fmt, n, seed):
    """The encodings a pass-through could get wrong, then random bits:
    both zeros, both infinities, quiet and signalling NaNs of both signs
    with payloads (the smallest, the largest, random), the smallest and
    largest subnormal and random ones of both signs, the smallest
    normal, the largest finite of both signs."""
    rng = random.Random(seed)
    w, mw = fmt.width, fmt.man_w
    top = 1 << (w - 1)
    inf = sf.inf_bits(fmt, 0)
    quiet = 1 << (mw - 1)
    pool = [sf.zero_bits(fmt, 0), sf.zero_bits(fmt, 1),
            inf, inf | top,
            inf | quiet, inf | quiet | top,              # canonical quiet NaNs
            inf | quiet | 1, inf | fmt.man_mask | top,   # quiet, payloads
            inf | 1, inf | 1 | top,                      # signalling, smallest
            inf | (quiet - 1), inf | (quiet - 1) | top,  # signalling, largest
            sf.min_subnormal_bits(fmt), sf.min_subnormal_bits(fmt) | top,
            fmt.man_mask, fmt.man_mask | top,            # largest subnormal
            sf.min_normal_bits(fmt), sf.max_normal_bits(fmt),
            sf.max_normal_bits(fmt) | top]
    for _ in range(4):
        pool.append(inf | quiet | rng.getrandbits(mw - 1) | (top * rng.getrandbits(1)))
        pool.append(inf | (rng.getrandbits(mw - 1) | 1) | (top * rng.getrandbits(1)))
        pool.append(rng.getrandbits(mw) | (top * rng.getrandbits(1)))  # subnormal
    out = list(pool)
    rng.shuffle(out)
    while len(out) < n:
        out.append(rng.getrandbits(w))
    return out[:n] if n >= len(pool) else [pool[(i + seed) % len(pool)]
                                            for i in range(n)]


@cocotb.test()
async def loads_carry_every_bit_pattern(dut):
    """A load's value comes back BIT FOR BIT, whichever way it takes:
    written into the file by the retire's port (a FAST load, the queue
    ahead of it holding only loads), or riding the array as IOR(v, v)
    (behind an array writer still in flight, on the single-pass tile).
    Nothing on the way may quieten a signalling NaN, touch a payload,
    flush a subnormal or raise a flag. Every encoding class a
    pass-through could get wrong is stored and loaded back through LDL
    and LDX, by static slot and by index, both ways, at one beat and at
    a whole block and ragged, at every format; the array writers ahead
    of the second group are integer codes, and the program does no
    arithmetic at all - so FLAGS must be the model's zero. IOR raises no
    flag for any operand, so the flag enable a load's request carries
    (off) cannot show in any answer: verifier-R4's plant that left it on
    is green here, as it must be. The multi-pass tile runs it too
    (seq_coremc), where the second group waits and goes fast."""
    bench = Bench(dut)
    await bench.start()
    prog_for = {}
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        prog_for[name] = seq.Program(fmt, [
            seq.stl(0, 3),              # slot 3 := a
            seq.stx(1, 2),              # scratch[c] := b
            seq.ldl(10, 3),             # r10 := slot 3, static
            seq.ldx(11, 2),             # r11 := scratch[c], indexed
            seq.ldx(12, 2),             # ...straight after, an LDX
            seq.ldl(13, 3),             # ...and an LDL straight after that
            seq.deposit(10), seq.deposit(11),
            seq.deposit(12), seq.deposit(13),
            seq.stl(11, 4),             # a loaded value stored again
            seq.ldl(14, 4),             # and loaded again
            seq.deposit(14),
            # behind an array writer, an integer code that raises
            # nothing: these ride the array as IOR(v, v)
            seq.alu(sf.OP_IAND, 20, 0, 1), seq.ldl(15, 3),
            seq.alu(sf.OP_IAND, 21, 0, 1), seq.ldx(16, 2),
            seq.alu(sf.OP_IAND, 22, 0, 1), seq.ldl(17, 4),
            seq.deposit(15), seq.deposit(16), seq.deposit(17),
            seq.halt()], max_deposits=8)
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        lpbeat, lpb = lanes_per_beat(fmt), lanes_per_block(fmt)
        for n in (lpbeat, lpb, lpb + lpbeat + 1):
            idx = [_int_bits(fmt, (i * 5) % 7) for i in range(n)]
            want = await bench.program(
                fmt, prog_for[name], _every_bit_pattern(fmt, n, 4000 + n),
                _every_bit_pattern(fmt, n, 4100 + n), idx, n,
                f"{name} every bit pattern through LDL and LDX, n={n}")
            assert want.flags == 0, (
                f"{name}: the model raised {want.flags:#07b} for a program "
                f"with no arithmetic - this case is not testing what it says")


# ======================================================================
# 10e. revision 7, R19: a beat with no active lane is not issued, and a
#      stream beat no lane can read is not loaded
# ======================================================================
#
# The sequencer issued every beat of a block and let the active bit
# decide what was written (R17's "all masked costs what half masked
# costs"). Now the issue skips a beat whose every lane is inactive - a
# lane the caller masked, a lane past n, a lane a SETACT dropped - and
# the dense stream loads read only the beats a lane the caller has sits
# in. Nothing a program can observe moves: a skipped beat's lanes are
# inactive, so it would have written nothing, deposited nothing and
# raised nothing. What moves is the retire's bookkeeping, which counted
# beats: a result now carries the beat it fired from, and an instruction
# that writes a register always fires its block's LAST beat, so its
# queue slot is released by a result even when every lane is out.

def _beat_mask(n, lpb, lpbeat, pattern, seed=0):
    """Masks that kill WHOLE BEATS, which R17's every-third-lane masks
    never do: a beat is `lpbeat` lanes, a block `lpb`."""
    rng = random.Random(seed)
    dead_beats = set()
    keep = []
    for i in range(n):
        j = i % lpb                      # lane within its block
        b = j // lpbeat                  # beat within its block
        if pattern == "low half":
            k = j >= lpb // 2
        elif pattern == "high half":
            k = j < lpb // 2
        elif pattern == "last lane":
            k = j == lpb - 1
        elif pattern == "first lane":
            k = j == 0
        elif pattern == "none":
            k = False
        elif pattern == "beats":
            # a random set of whole beats, a fresh draw each block
            if j == 0:
                dead_beats = {x for x in range(lpb // lpbeat)
                              if rng.random() < 0.5}
            k = b not in dead_beats
        else:
            raise ValueError(pattern)
        keep.append(k)
    return keep


@cocotb.test()
async def masked_beats_at_every_block_length(dut):
    """R19 against the model: masks that kill whole beats - the low half
    of every block, the high half, all but the last lane, all but the
    first, every lane, and random sets of whole beats - over the pipe
    program, R18's control-code program and R17's own, at every format
    and at block lengths from one beat to several blocks. Bench.masked
    holds the lanes the mask keeps to the model and the lanes it clears
    to the caller's bytes."""
    bench = Bench(dut)
    await bench.start()
    pats = ("low half", "high half", "last lane", "first lane", "none",
            "beats")
    for name, ns in (("fp32", (8, 24, 128, 136, 256)),
                     ("fp64", (4, 20, 64, 68)),
                     ("fp128", (2, 10, 32, 34)),
                     ("fp256", (1, 5, 16, 17))):
        fmt = FORMATS[name]
        lpb, lpbeat = lanes_per_block(fmt), lanes_per_beat(fmt)
        progs = ((_mask_prog(fmt), "R17's"),
                 (_pipe_program(fmt), "the pipe"),
                 (_ctl_program(fmt), "R18's control codes"))
        for k, n in enumerate(ns):
            for prog, what in progs:
                if fmt is FP256 and what == "the pipe":
                    continue                   # the pipe program is fp32-128
                pat = pats[(k + len(what)) % len(pats)]
                keep = _beat_mask(n, lpb, lpbeat, pat, seed=n)
                idx = _r18_index_stream(fmt, n, 2600 + n)
                await bench.masked(
                    fmt, prog, operands(fmt, n, 2700 + n),
                    operands(fmt, n, 2800 + n),
                    idx if what == "R18's control codes"
                    else operands(fmt, n, 2900 + n),
                    n, keep, f"{name} {what}, {pat} masked, n={n}")
    dut._log.info(f"R19 whole beats masked: {bench.cases['masked']} runs")


@cocotb.test()
async def converged_beats_are_skipped(dut):
    """A beat whose lanes have all CONVERGED is skipped too - the active
    bit a SETACT cleared is the one the issue reads - and the escape map
    comes out as the model says. Seeds are grouped by beat, so whole beats
    converge at different iterations, and some never do."""
    bench = Bench(dut)
    await bench.start()
    for name, n in (("fp32", 128), ("fp32", 40), ("fp64", 64), ("fp64", 9),
                    ("fp128", 32), ("fp256", 16)):
        fmt = FORMATS[name]
        lpbeat = lanes_per_beat(fmt)
        rng = random.Random(3000 + n)
        a = []
        for i in range(n):
            if (i // lpbeat) % 3 == 0:
                a.append(sf.zero_bits(fmt))           # stays small: never escapes
            else:
                e = fmt.bias + 1 + (i // lpbeat) % 3  # escapes early
                a.append((e << fmt.man_w) | rng.getrandbits(fmt.man_w))
        b = [sf.one_bits(fmt)] * n
        prog = escape_program(fmt, 8, sf.from_int(fmt, 64)[0])
        await bench.program(fmt, prog, a, b, operands(fmt, n, 3100 + n), n,
                            f"{name} escape map, whole beats converging, n={n}")


@cocotb.test()
async def a_beat_no_lane_has_is_not_loaded(dut):
    """The stream loads read only the beats a lane the caller has sits
    in: one burst a stream a block, from the first such beat to the last,
    and none at all for a block with no such beat. Asserted as ADDRESSES
    in the read log, derived from the mask, so a load that still read the
    whole block shows as a burst that is too long."""
    bench = Bench(dut)
    await bench.start()
    for name, n, pat in (("fp32", 256, "low half"), ("fp32", 256, "high half"),
                         ("fp64", 128, "last lane"), ("fp128", 64, "none"),
                         ("fp32", 136, "first lane")):
        fmt = FORMATS[name]
        lpb, lpbeat = lanes_per_block(fmt), lanes_per_beat(fmt)
        keep = _beat_mask(n, lpb, lpbeat, pat)
        prog = _mask_prog(fmt)          # reads r0 and r1: streams a and b
        await bench.masked(fmt, prog, operands(fmt, n, 3200 + n),
                           operands(fmt, n, 3300 + n),
                           operands(fmt, n, 3400 + n), n, keep,
                           f"{name} {pat} masked, n={n}: the loads")
        ebytes = fmt.width // 8
        for base, stream in ((A_BASE, "a"), (B_BASE, "b")):
            want = []
            for blk in range(0, n, lpb):
                blk_n = min(lpb, n - blk)
                live = [bt for bt in range(-(-blk_n // lpbeat))
                        if any(keep[blk + bt * lpbeat + p]
                               for p in range(lpbeat)
                               if bt * lpbeat + p < blk_n)]
                if not live:
                    continue
                lo, hi = live[0], live[-1]
                want.append((base + blk * ebytes + lo * BEAT_BYTES,
                             hi - lo + 1))
            got = bench.ram.reads_in(base, base + (1 << 16))
            assert got == want, (
                f"{name} {pat} n={n}: stream {stream} read {got}, and the "
                f"mask says {want} - one burst a block, from the first beat "
                f"a lane the caller has sits in to the last")


# Cycles a block, fp32, four blocks, twenty IANDs and a deposit - R17's
# probe program with more to skip. BEFORE is revision 7's R18 tile, where
# every mask cost the dense run plus four cycles a block (the mask's one
# read); AFTER is R19's. The ceilings sit between the two. Measured under
# Verilator (2026-09-29), cycles a block:
#
#   low half of each block masked   before 561.25 (R18, 1c82d4c)   after 410.0
#   every lane masked               before 561.25                  after 344.0
#
# What is left of the all-masked block is the block's own machinery -
# setup and the mask's read - about four cycles an instruction (its only
# issued step is its first, so it cannot take the next by continuation),
# about seven an arithmetic one (its forced last beat still crosses the
# array, and three queue slots cover twelve of its seventeen cycles), and
# the drains, which keep a masked lane's place and lose its strobe (R17).
# verifier-R4 measured 7.0 and 4.3 (fp32, every lane masked), where this
# comment said one cycle a writer.
R19_CEILING = {
    "low half of each block masked": 485,
    "every lane masked": 450,
}


@cocotb.test()
async def masked_beats_hold_their_saving(dut):
    """R19's gain, HELD: a run whose masked lanes fill whole beats costs
    less than a ceiling between the before-side (every mask costing the
    dense run) and the after-side, and answers what the model says."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    lpb, lpbeat = lanes_per_block(fmt), lanes_per_beat(fmt)
    n = 4 * lpb
    iand = seq.alu(sf.OP_IAND, 3, 0, 0)
    prog = seq.Program(fmt, [iand] * 20 + [seq.deposit(3), seq.halt()],
                       max_deposits=1)
    cost = {}
    for label, pat in (("low half of each block masked", "low half"),
                       ("every lane masked", "none")):
        keep = _beat_mask(n, lpb, lpbeat, pat)
        await bench.masked(fmt, prog, operands(fmt, n, 3500),
                           operands(fmt, n, 3501), operands(fmt, n, 3502), n,
                           keep, f"hold: {label}")
        cost[label] = bench.last_cycles / 4
        dut._log.info(f"hold: {label}: {cost[label]:.1f} cycles a block "
                      f"(ceiling {R19_CEILING[label]})")
    for label, per_block in cost.items():
        assert per_block < R19_CEILING[label], (
            f"hold: {label} costs {per_block:.1f} cycles a block, at or "
            f"above the ceiling of {R19_CEILING[label]} - a beat with no "
            f"active lane is being issued again (docs/SEQUENCER.md, "
            f"revision 7, R19)")


# ======================================================================
# 10f. fast loads (2026-09-29, verifier-R4's send-back of R18)
# ======================================================================
#
# R18 sent every load's value into the file through the array, as
# IOR(v, v). At sixteen beats the pipelining hides the array's depth; at
# ONE beat nothing does, and verifier-R4 measured a program that uses a
# loaded value at once running slower there than on f681dee's tile, whose
# LDL wrote the file itself. A load is now FAST when every queued writer
# ahead of it is a fast load: it keeps its queue slot, but the retire's
# write port writes its value into the file at F (an LDL) or H (an LDX),
# and it never enters the array. On a multi-pass tile a load that cannot
# be fast waits until it can. The rules are docs/SEQUENCER.md's.

def _load_programs(fmt):
    """verifier-R4's load-heavy programs (verifier-R4.md 08:18:52 and
    08:39:43), rebuilt from its descriptions - and, after them, three
    with a load straight behind an array writer still in flight, the one
    shape where a load cannot be fast and the multi-pass tile's choice
    (ride the array, or wait for the writer and go fast) shows. R4's
    seven have none: in each, every load finds the queue holding only
    loads, or its census chain's store has already waited for the FMA."""
    F = sf.OP_FMA
    pairs, use, chain, indep = [], [], [], []
    b_ldl, b_ldx, b_use = [], [], []
    for k in range(10):
        pairs += [seq.stl(3, k), seq.ldl(3, k)]
        use += [seq.ldl(3, 0), seq.deposit(3)]
    for k in range(8):
        chain += [seq.ldl(3 + k, k), seq.alu(F, 11 + k, 3 + k, 0, 1),
                  seq.stl(11 + k, 8 + k)]
        indep += [seq.stl(0, k), seq.ldl(3 + k, 8 + k), seq.setact(1)]
        writer = seq.alu(F, 11 + k, 0, 1, 1)      # an FMA nothing reads
        b_ldl += [writer, seq.ldl(3 + k, k), seq.deposit(3 + k)]
        b_ldx += [writer, seq.ldx(3 + k, 2), seq.deposit(3 + k)]
        b_use += [writer, seq.ldl(3 + k, k), seq.alu(F, 19 + k, 3 + k, 0, 1)]
    lds = [seq.ldl(3 + k, k) for k in range(20)]
    ldxs = [seq.ldx(3 + k, 2) for k in range(20)]
    return (("twenty LDLs, DEPOSIT of the last",
             lds + [seq.deposit(22), seq.halt()], 1),
            ("twenty LDLs, no deposit", lds + [seq.halt()], 1),
            ("ten times LDL, DEPOSIT of it", use + [seq.halt()], 10),
            ("ten STL/LDL pairs on one register",
             pairs + [seq.deposit(3), seq.halt()], 1),
            ("twenty LDXs, DEPOSIT of the last",
             ldxs + [seq.deposit(22), seq.halt()], 1),
            ("eight times LDL, FMA of it, STL of that",
             chain + [seq.deposit(18), seq.halt()], 1),
            ("eight times STL, LDL, SETACT",
             indep + [seq.deposit(10), seq.halt()], 1),
            ("eight times FMA, LDL behind it, DEPOSIT of that",
             b_ldl + [seq.halt()], 8),
            ("eight times FMA, LDX behind it, DEPOSIT of that",
             b_ldx + [seq.halt()], 8),
            ("eight times FMA, LDL behind it, FMA of that",
             b_use + [seq.deposit(26), seq.halt()], 1))


def _pass_period(fmt):
    """The array's pass period for fmt at this bench's MUL_PASSES, as
    rtl/cft_mulgeom.svh derives it: the chunks of the significand's
    24-bit multiplier columns, the columns a lane builds under the
    budget, the passes they take. 1 on the single-pass tile, and for
    fp32 on every tile; 3, 5 and 10 for fp64, fp128 and fp256 at 10."""
    p = {32: 24, 64: 53, 128: 113, 256: 237}[fmt.width]
    chunks = -(-p // 24)
    cols = -(-chunks // MUL_PASSES)
    return -(-chunks // cols)


def _load_sizes(fmt):
    """One, two and three beats of lanes at every format, and four whole
    blocks at fp128 and fp256 - the sizes of verifier-R4's tables. Four
    blocks at fp32 and fp64 are measured in the table below and not run:
    they cost most of the case's time, and R4 found nothing there."""
    lpbeat, lpb = lanes_per_beat(fmt), lanes_per_block(fmt)
    out = [("1 beat", lpbeat), ("2 beats", 2 * lpbeat),
           ("3 beats", 3 * lpbeat)]
    if fmt.width >= 128:
        out.append(("4 blocks", 4 * lpb))
    return tuple(out)


# f681dee's cycles for those programs, start to done, through this
# bench's harness, measured under Verilator on a copy of this tree with
# f681dee's rtl/cft_seq.sv (2026-09-29), on the single-pass tile
# (MUL_PASSES 1) and the multi-pass one (MUL_PASSES 10), at the unit
# bench's default capacities. Per MUL_PASSES, format and size, the ten
# programs in _load_programs' order; None where a size was not measured
# (four blocks at fp32 and fp64 are measured but not run, see
# _load_sizes). f681dee's loads never entered the array, so at
# MUL_PASSES 10 only the programs with an FMA cost more than at 1 - and
# at fp32, single-pass at every MUL_PASSES, not even those.
_F681DEE_LOADS = {
    1: {
        "fp32": {
            "1 beat": (553, 546, 294, 373, 4332, 620, 500, 541, 4512, 493),
            "2 beats": (666, 656, 456, 466, 4446, 707, 603, 681, 4653, 543),
            "3 beats": (779, 766, 618, 559, 4560, 794, 706, 821, 4794, 614),
            "4 blocks": (8872, 8667, 10779, 6952, 24048, 7565, 8045, None,
                         None, None),
        },
        "fp64": {
            "1 beat": (549, 542, 254, 369, 4328, 616, 496, 509, 4480, 489),
            "2 beats": (656, 646, 374, 456, 4436, 697, 593, 615, 4587, 533),
            "3 beats": (765, 752, 496, 545, 4546, 780, 692, 723, 4696, 600),
            "4 blocks": (8552, 8347, 8155, 6632, 23728, 7245, 7725, None,
                         None, None),
        },
        "fp128": {
            "1 beat": (547, 540, 234, 367, 4326, 614, 494, 493, 4464, 487),
            "2 beats": (652, 642, 334, 452, 4432, 693, 589, 583, 4555, 529),
            "3 beats": (757, 744, 434, 537, 4538, 772, 684, 673, 4646, 592),
            "4 blocks": (8392, 8187, 6859, 6472, 23568, 7085, 7565, 7272,
                         23216, 5533),
        },
        "fp256": {
            "1 beat": (546, 539, 224, 366, 4325, 613, 493, 485, 4456, 486),
            "2 beats": (650, 640, 314, 450, 4430, 691, 587, 567, 4539, 527),
            "3 beats": (754, 741, 404, 534, 4535, 769, 681, 649, 4622, 589),
            "4 blocks": (8312, 8107, 6211, 6392, 23488, 7005, 7485, 6748,
                         22692, 5453),
        },
    },
    10: {
        "fp32": {
            "1 beat": (553, 546, 294, 373, 4332, 620, 500, 541, 4512, 493),
            "2 beats": (666, 656, 456, 466, 4446, 707, 603, 681, 4653, 543),
            "3 beats": (779, 766, 618, 559, 4560, 794, 706, 821, 4794, 614),
            "4 blocks": (8872, 8667, 10779, 6952, 24048, 7565, 8045, 10432,
                         26376, 6013),
        },
        "fp64": {
            "1 beat": (549, 542, 254, 369, 4328, 887, 496, 779, 4752, 786),
            "2 beats": (656, 646, 374, 456, 4436, 969, 593, 889, 4860, 867),
            "3 beats": (765, 752, 496, 545, 4546, 1077, 692, 1018, 4992, 975),
            "4 blocks": (8552, 8347, 8155, 6632, 23728, 9285, 7725, 10365,
                         26310, 8889),
        },
        "fp128": {
            "1 beat": (547, 540, 234, 367, 4326, 1135, 494, 1014, 4986, 1089),
            "2 beats": (652, 642, 334, 452, 4432, 1258, 589, 1150, 5121, 1215),
            "3 beats": (757, 744, 434, 537, 4538, 1348, 684, 1251, 5226, 1341),
            "4 blocks": (8392, 8187, 6859, 6472, 23568, 11085, 7565, 11280,
                         27221, 11862),
        },
        "fp256": {
            "1 beat": (546, 539, 224, 366, 4325, 1780, 493, 1648, 5621, 1886),
            "2 beats": (650, 640, 314, 450, 4430, 1945, 587, 1813, 5791, 2054),
            "3 beats": (754, 741, 404, 534, 4535, 2104, 681, 1988, 5961, 2292),
            "4 blocks": (8312, 8107, 6211, 6392, 23488, 15971, 7485, 15724,
                         31681, 19603),
        },
    },
}
F681DEE_LOAD_CYCLES = {
    (label, size, name, mp): cyc
    for mp, by_fmt in _F681DEE_LOADS.items()
    for name, by_size in by_fmt.items()
    for size, row in by_size.items()
    for (label, _i, _m), cyc in zip(_load_programs(FP32), row)
    if cyc is not None
}


@cocotb.test()
async def loads_cost_no_more_than_before(dut):
    """The send-back's HOLD: verifier-R4's load-heavy programs and three
    with a load behind an array writer, at the sizes of R4's tables
    (_load_sizes), at every format, cost no more than on f681dee's tile
    - on this tile, single-pass or multi-pass. Every run is held to the
    model first, and every number is measured before any is judged, so
    a red run prints them all. The ceilings are the unit bench's default
    capacities', so elsewhere (seq_coreu50) the case does not run."""
    if (SCRATCH_D, MAXD) != (256, 64):
        dut._log.info("loads hold: not at these capacities")
        return
    bench = Bench(dut)
    await bench.start()
    cost = {}
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        for size, n in _load_sizes(fmt):
            for label, insns, maxdep in _load_programs(fmt):
                prog = seq.Program(fmt, insns, max_deposits=maxdep)
                await bench.program(fmt, prog, operands(fmt, n, 5000),
                                    operands(fmt, n, 5001),
                                    _r18_index_stream(fmt, n, 5002), n,
                                    f"{name} {label}, {size}")
                key = (label, size, name, MUL_PASSES)
                cost[key] = bench.last_cycles
                want = F681DEE_LOAD_CYCLES.get(key)
                dut._log.info(f"LOADROW {key!r}: {cost[key]:.0f}"
                              + (f"  (f681dee {want})" if want else ""))
    # On a multi-pass tile the array's enable counts wall cycles from
    # the reset (rtl/cft_lanes.sv, `ph`), so a run starts at whatever
    # phase of the pass period the runs before it left, and its count
    # moves with that phase by up to a period less one: f681dee's
    # census chain at fp256 measured 1,937 in one run of this case and
    # 1,945 in another. A row is held to f681dee's plus that much.
    worse = [(k, c, F681DEE_LOAD_CYCLES[k]) for k, c in cost.items()
             if k in F681DEE_LOAD_CYCLES and c > F681DEE_LOAD_CYCLES[k]
             + _pass_period(FORMATS[k[2]]) - 1]
    assert not worse, (
        f"{len(worse)} of {len(cost)} load rows cost more than on "
        f"f681dee's tile (MUL_PASSES {MUL_PASSES}), the first: "
        + "; ".join(f"{k[2]} {k[1]}, {k[0]}: {c:.0f} against {w}"
                    for k, c, w in worse[:4])
        + " (docs/SEQUENCER.md, R18's fast loads)")


@cocotb.test()
async def store_then_load_costs_what_the_sentence_says(dut):
    """docs/SEQUENCER.md's store-then-LDL sentence, HELD as measured
    (verifier-R4, 08:18:52): an LDL waits while ANY store beat is in B or
    F, so at sixteen beats a store straight before a load still costs two
    cycles - ten such adjacencies, twenty a block - beside the same
    program with an IAND where the store is. Held as an upper bound: the
    wait may bind less (the per-beat refinement SEQUENCER.md records as a
    possible gain), never more."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    n = 4 * lanes_per_block(fmt)
    iand = seq.alu(sf.OP_IAND, 4, 0, 0)
    per_block = {}
    for label, first in (("STL s0, LDL s1", seq.stl(0, 0)),
                         ("IAND, LDL s1", iand)):
        insns = []
        for _ in range(10):
            insns += [first, seq.ldl(3, 1)]
        # the same wipe on both sides: slots 0 and 1
        insns += [seq.stl(0, 0), seq.deposit(3), seq.halt()]
        prog = seq.Program(fmt, insns, max_deposits=1)
        await bench.program(fmt, prog, operands(fmt, n, 5100),
                            operands(fmt, n, 5101), operands(fmt, n, 5102),
                            n, f"sentence: {label} x10")
        per_block[label] = bench.last_cycles / 4
        dut._log.info(f"sentence: {label} x10: {per_block[label]:.2f} "
                      f"cycles a block")
    extra = per_block["STL s0, LDL s1"] - per_block["IAND, LDL s1"]
    dut._log.info(f"sentence: a store straight before a load costs "
                  f"{extra / 10:.2f} cycles more than an IAND there")
    assert extra <= 2 * 10, (
        f"ten store-then-load adjacencies cost {extra:.2f} cycles a block "
        f"more than the IAND program, past the two an adjacency "
        f"docs/SEQUENCER.md says")


def _fast_program(fmt, strict=False):
    """Every shape a fast load meets, in one program: loads first in the
    block (the queue empty), back to back in all four orders of LDL and
    LDX, each read at once by every kind of reader (a deposit, a store's
    value, an indexed code's index, an ALU operand, a SETACT); a load into
    a register an ALU instruction still in flight writes (it must NOT be
    fast - the ALU's result would land after it); a load behind an ALU
    instruction that writes something else; loads in a loop that stores
    what it loads; an indexed load past the depth under SCRATCH_STRICT
    (+0, through the fast write); and a SETACT that narrows the mask while
    a fast load's value is written, with ACTALL after."""
    A, M, F = sf.OP_ADD, sf.OP_MUL, sf.OP_FMA
    IADD = sf.OP_IADD
    insns = [
        seq.stl(0, 0), seq.stl(1, 1),
        seq.ldl(3, 0),                   # fast: the queue is empty
        seq.deposit(3),                  # ...read by a deposit at once
        seq.ldl(4, 1), seq.ldl(5, 0),    # LDL, LDL
        seq.alu(A, 6, 4, rc=5),          # an ALU reading both
        seq.ldx(7, 2), seq.ldx(8, 2),    # LDX, LDX (the index stream c)
        seq.stl(7, 2),                   # a store of a fast LDX's value
        seq.ldl(9, 2), seq.ldx(10, 2),   # LDL, LDX
        seq.ldx(11, 2), seq.ldl(12, 0),  # LDX, LDL
        seq.deposit(9), seq.deposit(10),
        seq.alu(IADD, 13, 2, 0, kb=True),  # an index, computed
        seq.stx(12, 13),                 # the store's value a fast load's
        seq.ldx(14, 13),
        seq.ldx(15, 14),                 # an index that is a fast LDX's value
        seq.deposit(15),
        seq.alu(F, 16, 0, 1, 3),         # r16 in flight...
        seq.ldl(16, 1),                  # ...when a load writes it: not fast
        seq.deposit(16),                 # the load's value, not the FMA's
        seq.alu(M, 17, 0, 0),            # something else in flight...
        seq.ldl(18, 0),                  # ...a load behind it: not fast
        seq.alu(A, 19, 18, rc=17),
        seq.deposit(19),
        seq.repeat(3),
        seq.ldl(20, 3),
        seq.alu(F, 20, 20, 0, 1),
        seq.stl(20, 3),
        seq.endrep(),
        seq.ldl(21, 3), seq.deposit(21),
        seq.alu(sf.OP_CMPLT, 22, 0, 1),
        seq.setact(22),                  # the mask narrows...
        seq.ldl(23, 1),                  # ...before a fast load writes
        seq.actall(),
        seq.deposit(23),                 # a dropped lane's r23: +0
        seq.ldl(24, 0), seq.setact(24),  # SETACT reading a fast load at once
        seq.deposit(24),
        seq.halt(),
    ]
    flags = seq.FLAG_SCRATCH_IO
    if strict:
        flags |= seq.FLAG_SCRATCH_STRICT
    return seq.Program(fmt, insns, consts=[_int_bits(fmt, 5)],
                       max_deposits=12, flags=flags,
                       n_scratch_in=0, n_scratch_out=4)


@cocotb.test()
async def fast_loads_at_every_block_length(dut):
    """Fast loads against the model at every block length the other
    shape cases use - one, two, three, five, nine and sixteen beats,
    ragged, across a block boundary - spread over fp32/64/128 and fp256,
    modulo, and strict at a short block and a long one."""
    bench = Bench(dut)
    await bench.start()
    for name, modulo, strict_ns in (
            ("fp32", (8, 9, 24, 40, 72, 136), (16, 150)),
            ("fp64", (4, 5, 20, 66), (8,)),
            ("fp128", (2, 3, 10, 33), (32,)),
            ("fp256", (1, 2, 3, 17), (16,))):
        fmt = FORMATS[name]
        for strict, ns in ((False, modulo), (True, strict_ns)):
            prog = _fast_program(fmt, strict)
            for n in ns:
                await bench.program(
                    fmt, prog, operands(fmt, n, 5200 + n),
                    operands(fmt, n, 5300 + n),
                    _r18_index_stream(fmt, n, 5400 + n), n,
                    f"{name} fast loads, "
                    f"{'strict' if strict else 'modulo'}, n={n}")
    dut._log.info(f"fast loads: {bench.cases['program']} runs")


def _chain_mask(n, lpb, lpbeat, kind):
    """verifier-R4's masks (verifier-R4.md 08:42:45), per block of lpb
    lanes: every lane kept, the low half or the low quarter masked, the
    last lane only, every other lane (at fp256, where a lane is a beat,
    every other beat), the high half masked."""
    keep = []
    for i in range(n):
        j = i % lpb
        keep.append({"every lane kept": True,
                     "low half masked": j >= lpb // 2,
                     "low quarter masked": j >= lpb // 4,
                     "last lane only": j == lpb - 1,
                     "every other lane": (j % 2) == 0,
                     "high half masked": j < lpb // 2}[kind])
    return keep


CHAIN_MASKS = ("every lane kept", "low half masked", "low quarter masked",
               "last lane only", "every other lane", "high half masked")

# f681dee's cycles for verifier-R4's chains, start to done over four
# blocks, through this bench's harness (Bench.masked), measured under
# Verilator on a copy of this tree with f681dee's rtl/cft_seq.sv
# (2026-09-29), MUL_PASSES 1, the unit bench's default capacities. Per
# link count and format, the masks in CHAIN_MASKS' order. R18's (1c82d4c)
# on the same bench, the design's own target, for the record:
#
#     60: {
#         "fp32": (4737, 4737, 4737, 4737, 4737, 4737),
#         "fp64": (4673, 4673, 4673, 4673, 4673, 4673),
#         "fp128": (4641, 4641, 4641, 4641, 4641, 4641),
#         "fp256": (4625, 4625, 4625, 4625, 4625, 4625),
#     },
#     20: {
#         "fp32": (1887, 1887, 1887, 1887, 1887, 1887),
#         "fp64": (1823, 1823, 1823, 1823, 1823, 1823),
#         "fp128": (1791, 1791, 1791, 1791, 1791, 1791),
#         "fp256": (1775, 1775, 1775, 1775, 1775, 1775),
#     },
_F681DEE_CHAINS = {
    60: {
        "fp32": (4741, 4741, 4741, 4741, 4741, 4741),
        "fp64": (4677, 4677, 4677, 4677, 4677, 4677),
        "fp128": (4645, 4645, 4645, 4645, 4645, 4645),
        "fp256": (4629, 4629, 4629, 4629, 4629, 4629),
    },
    20: {
        "fp32": (1891, 1891, 1891, 1891, 1891, 1891),
        "fp64": (1827, 1827, 1827, 1827, 1827, 1827),
        "fp128": (1795, 1795, 1795, 1795, 1795, 1795),
        "fp256": (1779, 1779, 1779, 1779, 1779, 1779),
    },
}
F681DEE_CHAIN_CYCLES = {
    (links, kind, name): cyc
    for links, by_fmt in _F681DEE_CHAINS.items()
    for name, row in by_fmt.items()
    for kind, cyc in zip(CHAIN_MASKS, row)
}


@cocotb.test()
async def masked_chains_cost_no_more_than_before(dut):
    """The send-back's second HOLD (verifier-R4's third (a)): a chain of
    dependent FMAs and nothing else but HALT, under masks that empty
    beats, costs no more than on f681dee's tile. Under R19 a producer
    whose first issued beat is 3 or later, or whose issued beats have a
    gap, used to lose forwarding's look-ahead at that beat - two cycles a
    link. Measured on the single-pass tile, where forwarding exists;
    every run also held to the model (bytes, counts, FLAGS, the mask's
    reads). The chain that ends in a DEPOSIT is logged beside them. Its
    ceilings are the single-pass tile's at the default capacities, so
    elsewhere the case does not run."""
    if MUL_PASSES != 1 or (SCRATCH_D, MAXD) != (256, 64):
        dut._log.info("chains hold: not on this tile")
        return
    bench = Bench(dut)
    await bench.start()
    F = sf.OP_FMA
    cost = {}
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        lpb, lpbeat = lanes_per_block(fmt), lanes_per_beat(fmt)
        n = 4 * lpb
        for links in (60, 20):
            prog = seq.Program(fmt, [seq.alu(F, 3, 0, 1, 3)] * links
                               + [seq.halt()], max_deposits=0)
            for kind in CHAIN_MASKS:
                keep = _chain_mask(n, lpb, lpbeat, kind)
                if not any(keep):
                    continue
                await bench.masked(fmt, prog, dense(fmt, n, 5500),
                                   dense(fmt, n, 5501),
                                   dense(fmt, n, 5502), n, keep,
                                   f"{name} {links} links, {kind}")
                key = (links, kind, name)
                cost[key] = bench.last_cycles
                want = F681DEE_CHAIN_CYCLES.get(key)
                dut._log.info(f"CHAINROW {key!r}: {cost[key]:.0f}"
                              + (f"  (f681dee {want})" if want else ""))
    fmt = FP32
    n = 4 * lanes_per_block(fmt)
    prog = seq.Program(fmt, [seq.alu(F, 3, 0, 1, 3)] * 20
                       + [seq.deposit(3), seq.halt()], max_deposits=1)
    await bench.masked(fmt, prog, dense(fmt, n, 5600), dense(fmt, n, 5601),
                       dense(fmt, n, 5602), n,
                       _chain_mask(n, lanes_per_block(fmt),
                                   lanes_per_beat(fmt), "low half masked"),
                       "fp32 20 links and a DEPOSIT, low half masked")
    dut._log.info(f"CHAINROW (20, 'low half masked, then DEPOSIT', 'fp32'): "
                  f"{bench.last_cycles:.0f} (logged, not held)")
    worse = [(k, c, F681DEE_CHAIN_CYCLES[k]) for k, c in cost.items()
             if k in F681DEE_CHAIN_CYCLES and c > F681DEE_CHAIN_CYCLES[k]]
    assert not worse, (
        f"{len(worse)} of {len(cost)} masked chains cost more than on "
        f"f681dee's tile, the first: "
        + "; ".join(f"{k[2]} {k[0]} links, {k[1]}: {c:.0f} against {w}"
                    for k, c, w in worse[:4])
        + " (docs/SEQUENCER.md, R19's look-ahead by tag)")



# ======================================================================
# 10g. verifier-R4's shapes (2026-09-29): what four of its plants needed
# ======================================================================
#
# verifier-R4 planted seven faults in e610b78's sequencer and the lead ran
# them against every bench (verifier-R4.md 09:18:53). Four passed this
# file's cases and were caught only by R4's own: an LDX's index dropped
# from its read set, the mask sampled at issue rather than at fire, the
# live-beat vector three cycles late, and ACTALL not waiting for an LDX's
# G and H. Each case below is the shape that sees one of them, adapted
# from R4's tb/test_r4.py and test_r4b.py (scratch), at every block
# length, on the single-pass and the multi-pass tile.

def _r4_lengths(fmt):
    """One, two, three, five, nine and sixteen beats; a block and one
    beat (across a block boundary); a block and a ragged tail; and a
    ragged short block of two beats, the second part-empty."""
    lp, lb = lanes_per_beat(fmt), lanes_per_block(fmt)
    out = [lp, 2 * lp, 3 * lp, 5 * lp, 9 * lp, lb, lb + lp,
           lb + 3 * lp - (1 if lp > 1 else 0)]
    if lp > 1:
        out.append(lp + 1)
    return out


def _small_index_stream(fmt, n, seed):
    """Integers 0..7 as bit patterns, every one in range."""
    rng = random.Random(seed)
    return [_int_bits(fmt, rng.randrange(8)) for _ in range(n)]


def _index_queued_program(fmt):
    """Every way an indexed code's index can still be in flight when the
    code reads it: an IADD straight before, one and two instructions
    before, a chain of three IADDs, a fast LDL, an LDX, and the index
    register overwritten straight before - and the same for an STX. Each
    index names a slot filled with a value the stale index's slot does
    not hold, so an index read before it lands shows in a deposit."""
    I, IAND, IXOR = sf.OP_IADD, sf.OP_IAND, sf.OP_IXOR
    K5, K9, K20, K2, K3, K4 = range(6)
    insns = [
        seq.alu(I, 10, 2, K5, kb=True),      # r10 = c + 5
        seq.stx(0, 10),                      # [c + 5] = a
        seq.alu(I, 11, 2, K9, kb=True),      # r11 = c + 9
        seq.stx(1, 11),                      # [c + 9] = b
        # an IADD makes the index, the LDX reads it at once...
        seq.alu(I, 12, 2, K5, kb=True), seq.ldx(3, 12), seq.deposit(3),
        # ...one instruction later...
        seq.alu(I, 13, 2, K9, kb=True), seq.alu(IAND, 20, 0, 1),
        seq.ldx(4, 13), seq.deposit(4),
        # ...two later
        seq.alu(I, 14, 2, K5, kb=True), seq.alu(IAND, 20, 0, 1),
        seq.alu(IXOR, 21, 0, 1), seq.ldx(5, 14), seq.deposit(5),
        # three IADDs build it, c + 2, + 3, + 4: every stale step names
        # another slot
        seq.alu(I, 15, 2, K2, kb=True), seq.alu(I, 15, 15, K3, kb=True),
        seq.alu(I, 15, 15, K4, kb=True), seq.ldx(6, 15), seq.deposit(6),
        # a fast LDL brings it in (slot 30 holds c + 5)...
        seq.stl(10, 30), seq.ldl(16, 30), seq.ldx(7, 16), seq.deposit(7),
        # ...and an LDX ([c] holds c + 9)
        seq.stx(11, 2), seq.ldx(17, 2), seq.ldx(8, 17), seq.deposit(8),
        # the index register overwritten straight before: c + 9 now
        seq.alu(I, 10, 2, K9, kb=True), seq.ldx(9, 10), seq.deposit(9),
        # an STX's index made straight before it, read back
        seq.alu(I, 18, 2, K20, kb=True), seq.stx(0, 18), seq.ldx(19, 18),
        seq.deposit(19),
        seq.halt(),
    ]
    consts = [_int_bits(fmt, v) for v in (5, 9, 20, 2, 3, 4)]
    return seq.Program(fmt, insns, consts=consts, max_deposits=8)


@cocotb.test()
async def an_index_a_queued_instruction_writes(dut):
    """verifier-R4's ldx_idx_nowait: an LDX's index is a register it
    must wait for like any operand. An IADD, a load or an LDX that
    writes it may still be in flight - in the array, or a fast load
    still in the pipe - when the LDX's first beat is addressed."""
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        prog = _index_queued_program(fmt)
        lp, lb = lanes_per_beat(fmt), lanes_per_block(fmt)
        for n in (lp, 2 * lp, 3 * lp, lb):
            await bench.program(fmt, prog, dense(fmt, n, 7000 + n),
                                dense(fmt, n, 7100 + n),
                                _small_index_stream(fmt, n, 7200 + n), n,
                                f"{name} index in flight, n={n}")
    dut._log.info(f"indices in flight: {bench.cases['program']} runs")


def _drop_inputs(fmt, n, seed):
    """a = inf and b = +0 on odd lanes (SETACT b drops exactly them, and
    an FMA of a and b there is inf * 0, INVALID); c indexes past the
    depth there, in range elsewhere (strict: reported only there)."""
    rng = random.Random(seed)
    d, e = dense(fmt, n, seed), dense(fmt, n, seed + 1)
    a = [sf.inf_bits(fmt, 0) if i % 2 else d[i] for i in range(n)]
    b = [0 if i % 2 else e[i] for i in range(n)]
    c = [_int_bits(fmt, (SCRATCH_D if i % 2 else 0) + rng.randrange(8))
         for i in range(n)]
    return a, b, c


def _drop_programs():
    """A SETACT that drops lanes, and straight after it, before the drop
    can have reached a beat the next code addresses at once: codes whose
    dropped lanes would show - a flag, a strict report, a load's write.
    And, the other way round, a flag raised by an FMA in flight when the
    drop comes, which the model counts."""
    F, M, IAND = sf.OP_FMA, sf.OP_MUL, sf.OP_IAND
    S = seq.FLAG_SCRATCH_IO | seq.FLAG_SCRATCH_STRICT
    return (
        ("an FMA straight after the drop", [
            seq.setact(1), seq.alu(F, 3, 0, 1, 2), seq.deposit(3),
            seq.halt()], 1, S, 1),
        ("a MUL after the drop, an integer code between", [
            seq.setact(1), seq.alu(IAND, 5, 0, 0), seq.alu(M, 3, 0, 1),
            seq.deposit(3), seq.halt()], 1, S, 1),
        ("an FMA in flight when the drop comes", [
            seq.alu(F, 3, 0, 1, 2), seq.setact(1), seq.deposit(3),
            seq.halt()], 1, S, 1),
        ("a strict LDX and STX straight after the drop", [
            seq.setact(1), seq.ldx(5, 2), seq.stx(0, 2), seq.deposit(5),
            seq.halt()], 1, S, 1),
        ("a fast LDL straight after the drop, then ACTALL", [
            seq.stl(0, 3), seq.setact(1), seq.ldl(4, 3), seq.actall(),
            seq.deposit(4), seq.halt()], 1, S, 4),
        ("an LDL behind an FMA straight after the drop, then ACTALL", [
            seq.stl(0, 3), seq.setact(1), seq.alu(F, 6, 0, 1, 2),
            seq.ldl(4, 3), seq.actall(), seq.deposit(4), seq.halt()],
         1, S, 4),
    )


@cocotb.test()
async def the_mask_is_taken_at_fire_not_at_issue(dut):
    """verifier-R4's mask_at_issue: a beat takes its row of the mask when
    it fires (F; an LDX at H), not when it is addressed. Where the next
    code is addressed by continuation within two steps of a SETACT's
    beat - a block of two beats, or a long block whose mask leaves one
    or two beats alive - that beat has not acted yet, so a row taken at
    issue is the row before the drop: a flag the model does not raise,
    a write it does not make. (A one-beat block fetches the next code
    through decode, by when the drop has acted.) Run at one to three
    beats and ragged, and on a whole block whose lane mask keeps only
    its last beat."""
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        lp, lb = lanes_per_beat(fmt), lanes_per_block(fmt)
        for label, insns, maxdep, flags, nsout in _drop_programs():
            prog = seq.Program(fmt, insns, max_deposits=maxdep,
                               flags=flags, n_scratch_in=0,
                               n_scratch_out=nsout)
            ns = [lp, 2 * lp, 3 * lp] + ([lp + 1] if lp > 1 else [])
            if "LDX" in label:
                ns = ns[:2]         # its wipe is the case's cost
            for n in ns:
                a, b, c = _drop_inputs(fmt, n, 7300 + n)
                want = await bench.program(fmt, prog, a, b, c, n,
                                           f"{name} {label}, n={n}")
                if n >= 2 and label.startswith("an FMA straight"):
                    assert not (want.flags & sf.FLAG_INVALID), (
                        "precondition: the model raises no invalid here")
                if n >= 2 and label.startswith("an FMA in flight"):
                    assert want.flags & sf.FLAG_INVALID, (
                        "precondition: the model raises invalid here")
            # a whole block whose lane mask keeps only the last beat,
            # so each instruction issues one beat
            n = lb
            a, b, c = _drop_inputs(fmt, n, 7400)
            keep = [i >= lb - lp for i in range(n)]
            await bench.masked(fmt, prog, a, b, c, n, keep,
                               f"{name} {label}, n={n}, last beat alive")
    dut._log.info(f"mask at fire: {bench.cases['program']} runs")


def _dead_beats_c(fmt, n, pattern, seed):
    """c = +0 on every lane of a dead beat, 1.0 elsewhere, block by
    block: SETACT c empties whole beats, which R19 then skips."""
    rng = random.Random(seed)
    lp, lb = lanes_per_beat(fmt), lanes_per_block(fmt)
    one = sf.one_bits(fmt)
    out = []
    for blk in range(0, n, lb):
        nb = -(-min(lb, n - blk) // lp)
        dead = {"low half": {j for j in range(nb) if j < max(1, nb // 2)},
                "odd beats": {j for j in range(nb) if j % 2},
                "all but the last": set(range(nb - 1)),
                "all but the first": set(range(1, nb)),
                "random": {j for j in range(nb) if rng.random() < 0.5},
                }[pattern]
        for j in range(min(lb, n - blk)):
            out.append(0 if (j // lp) in dead else one)
    return out


def _revive_programs():
    """A producer that skips the beats a SETACT emptied, ACTALL, and the
    producer's readers AT ONCE - a DEPOSIT, an ALU code, a SETACT, an
    STX's index - which must issue the revived beats and read in them
    what the producer left there (the value from before it, since it
    skipped them). The indexed pair is a program of its own, run at two
    lengths: its whole-depth wipe is most of any run's cost."""
    F, I, IOR = sf.OP_FMA, sf.OP_IADD, sf.OP_IOR
    S = seq.FLAG_SCRATCH_IO
    return (
        ("an FMA and an LDL skip, ACTALL, their readers at once", [
            seq.alu(IOR, 3, 0, 0),              # r3 = a, the old value
            seq.alu(IOR, 4, 1, 1),              # r4 = b, the old value
            seq.stl(1, 4),
            seq.setact(2),                      # empties whole beats
            seq.alu(F, 3, 0, 1, 3),             # skips them
            seq.ldl(4, 4),                      # skips them too
            seq.actall(),
            seq.deposit(3), seq.deposit(4),
            seq.alu(I, 5, 3, 4),
            seq.deposit(5),
            seq.setact(3), seq.deposit(0),
            seq.halt()], 4, S, 5),
        ("an index and an LDX skip, ACTALL, read at once", [
            seq.alu(IOR, 4, 1, 1),
            seq.alu(I, 10, 2, 0, kb=True),      # r10 = c + 5, an index
            seq.stx(0, 10),
            seq.setact(2),
            seq.alu(I, 10, 10, 1, kb=True),     # skips: r10 = c + 14 live
            seq.ldx(4, 10),                     # skips, fires at H
            seq.actall(),
            seq.deposit(4),
            seq.stx(1, 10), seq.ldx(12, 10), seq.deposit(12),
            seq.halt()], 2, S, 1),
        ("a chain through skipped beats, ACTALL, read at once", [
            seq.alu(IOR, 3, 0, 0),
            seq.setact(2),
            seq.alu(F, 3, 3, 1, 0), seq.alu(F, 3, 3, 1, 0),
            seq.alu(F, 3, 3, 1, 0), seq.stl(3, 0), seq.ldl(4, 0),
            seq.actall(),
            seq.alu(I, 5, 3, 4), seq.deposit(5), seq.deposit(3),
            seq.halt()], 2, S, 1),
    )


@cocotb.test()
async def beats_revived_by_actall_are_read_at_once(dut):
    """verifier-R4's live_late3: the vector of beats with a live lane is
    what the issue skips by, so it must follow the mask at once. After
    ACTALL the next code must issue every beat again - here the readers
    straight after it, of producers that skipped the beats a SETACT had
    emptied - or the revived lanes read nothing and write nothing."""
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        consts = [_int_bits(fmt, 5), _int_bits(fmt, 9)]
        for label, insns, maxdep, flags, nsout in _revive_programs():
            prog = seq.Program(fmt, insns, consts=consts,
                               max_deposits=maxdep, flags=flags,
                               n_scratch_in=0, n_scratch_out=nsout)
            lp, lb = lanes_per_beat(fmt), lanes_per_block(fmt)
            ns = ((2 * lp, lb) if "LDX" in label
                  else (lp, 2 * lp, 3 * lp, lb, lb + lp))
            for k, n in enumerate(ns):
                for pattern in ("low half", "all but the last"):
                    seed = 7500 + 13 * n + k
                    await bench.program(
                        fmt, prog, dense(fmt, n, seed),
                        dense(fmt, n, seed + 1),
                        _dead_beats_c(fmt, n, pattern, seed + 2), n,
                        f"{name} {label}, {pattern}, n={n}")
    dut._log.info(f"revived beats: {bench.cases['program']} runs")


@cocotb.test()
async def actall_waits_for_an_ldx_in_g_and_h(dut):
    """ACTALL widens the mask, so every beat before it must have taken
    its row first - an LDX's at H, two steps after F, whether the LDX
    rides the array or writes the file itself (fast). Without G and H in
    the pipe's idle, ACTALL straight after an LDX lands while the LDX's
    last beat is in G, and at H that beat writes the lanes the mask had
    dropped. verifier-R4's test_r4b.py (scratch), carried here: every
    index in range and the value loaded each lane's own non-zero a, so a
    wrong write shows in the deposit. With the LDX fast (the queue empty
    of arithmetic) and not (an FMA straight before it), and with the
    drop on the odd lanes and on the last lane of each block, whose beat
    is the LDX's last - so a block of one fp256 lane sees it too - at
    one beat, two, and a whole block."""
    bench = Bench(dut)
    await bench.start()
    F, I, IXOR = sf.OP_FMA, sf.OP_IADD, sf.OP_IXOR
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        lb = lanes_per_block(fmt)
        for behind in (False, True):
            prog = seq.Program(fmt, [
                seq.alu(IXOR, 31, 0, 0),              # r31 = 0
                seq.alu(I, 10, 31, 0, kb=True),       # r10 = 5, in range
                seq.stx(0, 10),                       # scratch[5] = a
                seq.setact(1)]                        # b = +0 drops a lane
                + ([seq.alu(F, 20, 0, 1, 1)] if behind else [])
                + [seq.ldx(4, 10),                    # survivors load a
                   seq.actall(),                      # straight after
                   seq.deposit(4),                    # a dropped lane: +0
                   seq.halt()], consts=[_int_bits(fmt, 5)], max_deposits=1)
            lp = lanes_per_beat(fmt)
            for n in (lp, 2 * lp, lb):
                a = dense(fmt, n, 9100 + n)
                e = dense(fmt, n, 9200 + n)
                # the odd lanes and each block's last lane dropped
                out = [i % 2 == 1 or i % lb == lb - 1 or i == n - 1
                       for i in range(n)]
                b = [0 if out[i] else e[i] for i in range(n)]
                c = dense(fmt, n, 9300 + n)
                want = await bench.program(
                    fmt, prog, a, b, c, n,
                    f"{name} ACTALL after an LDX"
                    f"{' behind an FMA' if behind else ''}, n={n}")
                dropped = [i for i in range(n) if out[i]]
                assert all(want.deposits[i] == 0 for i in dropped), (
                    "precondition: a dropped lane deposits +0 in the model")
    dut._log.info(f"ACTALL after an LDX: {bench.cases['program']} runs")


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


# ======================================================================
# 13. revision 6, R16: an input block fetched through an index table
#
# The mechanism is a gather, so the cases are about ADDRESSES as much
# as about answers: `Bench.gathered` asserts the read traffic against
# the table - one burst per table beat at the block's own entry
# offset, one single-beat read per non-sentinel entry at that
# element's beat, in order - and then compares every observable
# against `seq.run()` with the same tables. A one-beat slip in the
# block offset is an address here, not a plausible neighbour's value.
# ======================================================================

def _perm_table(n, src_len, seed, none_every=0):
    """A table with a DISTINCT value in every lane where the source is
    long enough to have one, so a slip of one entry cannot land on the
    value the right entry would have given.

    `none_every` puts CFT_IDX_NONE at every k-th lane; those lanes read
    +0 and must cost no read at all."""
    rng = random.Random(seed)
    if src_len >= n:
        vals = rng.sample(range(src_len), n)
    else:
        vals = [(i * 7 + 3) % src_len for i in range(n)]
    if none_every:
        for i in range(0, n, none_every):
            vals[i] = seq.IDX_NONE
    return vals


def _gather_prog(fmt):
    """r0 + r2 deposited, then r1 * r2: two indexed streams reaching two
    registers an instruction reads, and a third answer that depends on
    both, so a table delivered to the wrong register is an answer and
    not an unread value."""
    A, M = sf.OP_ADD, sf.OP_MUL
    return seq.Program(fmt, [
        seq.alu(A, 3, ra=0, rc=2),
        seq.alu(M, 4, ra=1, rb=2),
        seq.alu(A, 5, ra=3, rc=4),
        seq.deposit(3), seq.deposit(4), seq.deposit(5),
        seq.halt()], max_deposits=3)


@cocotb.test()
async def gathered_streams_at_every_block_length(dut):
    """The sweep. Every block length at every format, with a distinct
    index in every lane and the block's table beats landing where they
    fall - including `n` a block and a half, where the block's entries
    start partway through the table and the last beat of a block is
    short.

    This is the case the block-offset trap has to survive: an entry is
    indexed by the GLOBAL lane and is four bytes wide at every format,
    so block b's entries begin at entry blk_base. Scaling that offset
    by the element size instead - the natural mistake, because every
    other per-block offset in the module is scaled that way - reads
    the wrong entries at fp64 and above, and reads them from an
    address this bench prints.
    """
    bench = Bench(dut)
    await bench.start()
    for name, ns in (("fp32", (8, 129, 192, 256)),
                     ("fp64", (5, 65, 96, 128)),
                     ("fp128", (3, 33, 48)),
                     ("fp256", (1, 17, 24, 32))):
        fmt = FORMATS[name]
        prog = _gather_prog(fmt)
        for n in ns:
            src = operands(fmt, max(n, 37), 4100 + n)
            ta = _perm_table(n, len(src), 5100 + n)
            tc = _perm_table(n, len(src), 5200 + n)
            await bench.gathered(
                fmt, prog, src, operands(fmt, n, 4200 + n), src, n,
                f"{name} n={n}: a and c gathered",
                idx_a=ta, idx_c=tc)
    dut._log.info(f"gathered at every block length: "
                  f"{bench.cases['gathered']} runs")


@cocotb.test()
async def gathered_identity_is_the_dense_run(dut):
    """Control (a). An identity table must be BIT-IDENTICAL to the dense
    run over the same stream - every deposit, every count, the flags -
    and a permuted table must differ from it and equal the model. The
    second half is what makes the first half a gate: an identity table
    that agreed because the tile ignored the MODE bit would pass the
    first and fail the second.
    """
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        prog = _gather_prog(fmt)
        n = lanes_per_block(fmt) + lanes_per_block(fmt) // 2
        a = operands(fmt, n, 6100)
        b = operands(fmt, n, 6200)
        c = operands(fmt, n, 6300)
        dense = await bench.program(fmt, prog, a, b, c, n,
                                    f"{name}: the dense run")
        ident = await bench.gathered(fmt, prog, a, b, c, n,
                                     f"{name}: an identity table",
                                     idx_a=list(range(n)))
        assert ident.deposits == dense.deposits and \
            ident.counts == dense.counts and ident.flags == dense.flags, \
            (f"{name}: an identity table is not the dense run - and both "
             f"came back from the tile, so this is the tile's answer")
        perm = _perm_table(n, n, 6400)
        got = await bench.gathered(fmt, prog, a, b, c, n,
                                   f"{name}: a permuted table",
                                   idx_a=perm)
        assert got.deposits != dense.deposits, (
            f"{name}: the permuted table gave the dense run's deposits, "
            f"so this control could not have failed. The permutation is "
            f"{perm[:8]}...")
    dut._log.info("identity == dense, permuted != dense, at four formats")


@cocotb.test()
async def gathered_sentinel_reads_plus_zero_and_costs_no_read(dut):
    """Control (b). CFT_IDX_NONE is +0 in exactly those lanes, and the
    run issues exactly that many fewer reads.

    The count is measured twice and both are derived: `gathered`
    asserts the element reads one for one against the table (so a
    sentinel that issued a read is an extra address), and the run is
    then repeated with the sentinels replaced by real indices, with the
    DIFFERENCE in total read bursts asserted against the number of
    sentinels. Neither number is typed.
    """
    bench = Bench(dut)
    await bench.start()
    for name, every in (("fp32", 3), ("fp64", 2), ("fp256", 4)):
        fmt = FORMATS[name]
        prog = _gather_prog(fmt)
        n = lanes_per_block(fmt) + 3
        src = operands(fmt, max(n, 29), 7100)
        full = _perm_table(n, len(src), 7200)
        holey = list(full)
        for i in range(0, n, every):
            holey[i] = seq.IDX_NONE
        holes = sum(1 for t in holey if t == seq.IDX_NONE)
        assert holes, f"{name}: this case has no sentinels in it"

        # c is DENSE here and so has exactly n elements; only `a` is
        # the source, and a source has no reason to be n long.
        cdense = operands(fmt, n, 7400)
        await bench.gathered(fmt, prog, src, operands(fmt, n, 7300),
                             cdense, n, f"{name}: {holes} sentinels",
                             idx_a=holey)
        with_holes = bench.ram.ar_count
        await bench.gathered(fmt, prog, src, operands(fmt, n, 7300),
                             cdense, n, f"{name}: no sentinels",
                             idx_a=full)
        dense_reads = bench.ram.ar_count
        assert dense_reads - with_holes == holes, (
            f"{name}: a table with {holes} sentinels issued "
            f"{dense_reads - with_holes} fewer read bursts than the same "
            f"table without them. +0 is the format's zero and needs no "
            f"element, so the saving must be exactly one read a "
            f"sentinel.")
        dut._log.info(f"{name}: {holes} sentinels, {dense_reads} reads "
                      f"dense against {with_holes} gathered")


@cocotb.test()
async def gathered_scratch_block(dut):
    """The scratch block through its table: n * n_scratch_in entries,
    lane-major as the block is.

    n_scratch_in is three, so a table read slot-major or a lane's
    entries taken from the wrong stride lands on another lane's slot
    and the scratch-out block says so. The pool is deliberately shorter
    than the block, which is the shape the feature exists for - the
    gravity fold's contributions are a short array read many times.
    """
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64", "fp256"):
        fmt = FORMATS[name]
        k = 3
        prog = seq.Program(fmt, [
            seq.ldl(3, 0), seq.ldl(4, 1), seq.ldl(5, 2),
            seq.alu(sf.OP_ADD, 6, ra=3, rc=4),
            seq.alu(sf.OP_ADD, 6, ra=6, rc=5),
            seq.stl(6, 3),
            seq.deposit(6), seq.halt()],
            max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
            n_scratch_in=k, n_scratch_out=4)
        n = lanes_per_block(fmt) + lanes_per_block(fmt) // 2 + 1
        pool = operands(fmt, 23, 8100 + len(name))
        tbl = _perm_table(n * k, len(pool), 8200, none_every=5)
        await bench.gathered(
            fmt, prog, operands(fmt, n, 8300), operands(fmt, n, 8400),
            operands(fmt, n, 8500), n,
            f"{name} n={n}: the scratch block gathered from a "
            f"{len(pool)}-element pool",
            scratch_in=pool, idx_scratch_in=tbl)
    dut._log.info("the scratch block gathers lane-major at three formats")


@cocotb.test()
async def gathered_stream_no_instruction_reads_is_never_fetched(dut):
    """R10 and R16 together: a stream no instruction reads is not
    loaded, and that must hold for an indexed one - table included.

    The saving is the reason the fold program in the gravity shape can
    index one stream and leave the other two alone. Asserted by
    ADDRESS: with the MODE bit set on b and c and a program that reads
    r0 alone, not one burst may land in either table's region or in
    either stream's.
    """
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    prog = seq.Program(fmt, [
        seq.alu(sf.OP_ADD, 3, ra=0, rc=0),
        seq.deposit(3), seq.halt()], max_deposits=1)
    n = 40
    src = operands(fmt, 64, 9100)
    ta = _perm_table(n, len(src), 9200)
    tb = _perm_table(n, len(src), 9300)
    tc = _perm_table(n, len(src), 9400)
    await bench.gathered(fmt, prog, src, src, src, n,
                         "fp32: b and c indexed and never read",
                         idx_a=ta, idx_b=tb, idx_c=tc, check_reads=False)
    for base, what in ((IB_BASE, "the b table"), (IC_BASE, "the c table"),
                       (B_BASE, "the b stream"), (C_BASE, "the c stream")):
        got = bench.ram.reads_in(base, base + (1 << 16))
        assert not got, (
            f"{what} was read {len(got)} time(s) by a program that names "
            f"r0 alone: {got[:4]}. R10 skips a stream no instruction "
            f"reads, and an indexed stream's TABLE is part of what is "
            f"skipped.")
    # ...and the one stream that IS read was gathered, so the case is
    # not passing because nothing happened at all.
    bench._check_gather_reads(fmt, IA_BASE, A_BASE, ta, n, 1,
                              "fp32: the a stream")
    dut._log.info("an unread indexed stream costs no read, table included")


# ======================================================================
# 14. R10's rule, corrected 2026-09-15: a stream is needed when the
#     OPCODE reads it, not when an operand field happens to name it
#
# The old rule marked a stream from the field alone, so
# `alu(op, rd, ra=.., rc=..)` - rb defaulted to 0 - marked stream a.
# Dense that was one extra beat read a block and the section that
# introduced it called it free. Through an index table it is the whole
# table plus one round trip an entry, which is the most expensive path
# the module has, for a stream nothing reads.
#
# Under-approximating the other way is a silent wrong answer: the
# stream is not loaded and its register reads +0. So the RTL's table is
# derived from the MODEL here and asserted opcode by opcode, and the
# read counts are measured on the tile beside it.
# ======================================================================

def _model_reads(op):
    """Which operand positions opcode `op` consumes, taken from the
    model's own code rather than from a second copy of the table.

    For the four arithmetic opcodes the authority is `sf.steer`, which
    maps (op, a, b, c) onto the FMA's three inputs exactly as the RTL's
    operand mux does: vary one input, and if the mapped triple does not
    move, the ALU cannot read it. (Membership would be wrong here -
    SUB passes `negate(xc)`, which is not `xc`.)

    For the simple group the authority is the implementation's own
    SIGNATURE: `def fabs(fmt, xa, *_)` reads a and nothing else, and
    `*_` is exactly the statement "the rest is not read".

    An opcode the model does not implement reads all three, which is
    what the RTL must also assume."""
    import inspect
    if op in sf.ARITH_OPS:
        fmt = FP64
        base = (0x3FF1_1111_1111_1111, 0x4002_2222_2222_2222,
                0x4008_3333_3333_3333)
        alt = (0x3FF4_4444_4444_4444, 0x4005_5555_5555_5555,
               0x400A_6666_6666_6666)
        ref = sf.steer(fmt, op, *base)
        out = []
        for i in range(3):
            args = list(base)
            args[i] = alt[i]
            out.append(sf.steer(fmt, op, *args) != ref)
        return tuple(out)
    impl = sf.SIMPLE_IMPL.get(op)
    if impl is None:
        return (True, True, True)
    names = [p.name for p in inspect.signature(impl).parameters.values()
             if p.kind is p.POSITIONAL_OR_KEYWORD]
    return ("xa" in names, "xb" in names, "xc" in names)


def _rtl_op_reads():
    """The RTL's own table, parsed out of rtl/cft_seq.sv's `op_reads`
    rather than retyped: `8'dN: op_reads = 3'bCBA;`, with the default
    arm filling every opcode the case does not name."""
    import re
    src = (Path(__file__).resolve().parents[1] / "rtl" /
           "cft_seq.sv").read_text(encoding="utf-8")
    body = src.split("function automatic [2:0] op_reads", 1)[1]
    body = body.split("endfunction", 1)[0]
    table = {}
    for m in re.finditer(r"8'd(\d+):\s*op_reads\s*=\s*3'b([01]{3})", body):
        bits = m.group(2)
        table[int(m.group(1))] = (bits[2] == "1", bits[1] == "1",
                                  bits[0] == "1")
    dm = re.search(r"default:\s*op_reads\s*=\s*3'b([01]{3})", body)
    assert dm, "cft_seq.sv's op_reads has no default arm"
    d = dm.group(1)
    default = (d[2] == "1", d[1] == "1", d[0] == "1")
    assert table, "cft_seq.sv's op_reads named no opcode"
    return table, default


@cocotb.test()
async def operand_use_is_the_opcode_s(dut):
    """The RTL's `op_reads` against the model, for all 256 opcodes.

    This is the assertion that stands between a narrowed rd_need and a
    silent wrong answer: an opcode whose table says "does not read b"
    while the ALU reads b would leave r1 at +0 for a whole run.
    """
    table, default = _rtl_op_reads()
    bad = []
    for op in range(256):
        want = _model_reads(op)
        got = table.get(op, default)
        # The RTL may over-approximate (loading a stream nobody reads
        # is only slower); it may never under-approximate.
        for p in range(3):
            if want[p] and not got[p]:
                bad.append((op, "abc"[p], "model reads it, the RTL "
                                          "would skip the stream"))
    assert not bad, (
        f"rtl/cft_seq.sv's op_reads under-approximates for "
        f"{len(bad)} (opcode, operand) pair(s), each of which would "
        f"leave a stream register at +0: {bad[:8]}")
    # ...and it is not simply "all three everywhere", which would pass
    # the loop above and buy nothing.
    narrowed = sum(1 for op, r in table.items() if not all(r))
    assert narrowed >= 20, (
        f"only {narrowed} opcodes have a narrowed operand use, so this "
        f"case is passing on an over-approximation that would leave "
        f"R16's saving inverted")
    dut._log.info(f"op_reads: {len(table)} opcodes named, {narrowed} of "
                  f"them narrower than a, b and c, none under the model")


@cocotb.test()
async def an_unread_stream_costs_nothing_dense_or_gathered(dut):
    """V1's case, measured. `ADD rd, ra, rc` with rb defaulted to zero
    names r0 in its rb FIELD and does not read it; neither the stream
    nor - when it is indexed - its table may be touched.

    Both halves are here because they are different failures: dense it
    is beats the module did not need, gathered it is a round trip an
    entry."""
    bench = Bench(dut)
    await bench.start()
    fmt = FP64
    # ADD reads ra and rc. Both are registers at or above three, so no
    # stream is read at all - but rb defaults to 0, which is r0.
    prog = seq.Program(fmt, [
        seq.ldl(3, 0), seq.ldl(4, 1),
        seq.alu(sf.OP_ADD, rd=6, ra=3, rc=4),
        seq.deposit(6), seq.halt()],
        max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
        n_scratch_in=2, n_scratch_out=0)
    assert seq.decode(prog.insns[2])["rb"] == 0, \
        "this case needs the defaulted rb field that names r0"
    n = 70
    block = operands(fmt, n * 2, 4400)
    await bench.program(fmt, prog, operands(fmt, n, 4401),
                        operands(fmt, n, 4402), operands(fmt, n, 4403),
                        n, "fp64: ADD with a defaulted rb, dense",
                        scratch_in=block)
    got = bench.ram.reads_in(A_BASE, A_BASE + (1 << 16))
    assert not got, (
        f"the a stream was read {len(got)} time(s) by a program whose "
        f"only mention of r0 is an rb field an ADD does not read: "
        f"{got[:4]}. R10 skips a stream no instruction READS.")

    # ...and the same program with a table on a. Nothing may be read
    # from either region - the table above all, which is the cost R16
    # turned from one beat into one round trip an entry.
    src = operands(fmt, 23, 4404)
    tbl = _perm_table(n, len(src), 4405)
    await bench.gathered(
        fmt, prog, src, operands(fmt, n, 4402), operands(fmt, n, 4403),
        n, "fp64: ADD with a defaulted rb, a indexed",
        idx_a=tbl, scratch_in=block,
        idx_scratch_in=_perm_table(n * 2, len(block), 4406),
        check_reads=False)
    for base, what in ((IA_BASE, "the a table"), (A_BASE, "the a stream")):
        got = bench.ram.reads_in(base, base + (1 << 16))
        assert not got, (
            f"{what} was read {len(got)} time(s) for a stream the "
            f"program does not read: {got[:4]}. Through a table that "
            f"is the whole table plus a round trip an entry.")
    # ...while the block that IS indexed was gathered, so the case is
    # not passing because nothing happened.
    bench._check_gather_reads(fmt, ISI_BASE, SIN_BASE,
                              _perm_table(n * 2, len(block), 4406), n, 2,
                              "fp64: the scratch block")
    dut._log.info("an operand field the opcode does not read costs no "
                  "stream and no table")


# ----------------------------------------------------------------------
# revision 6, R17: a per-run lane mask
#
# Every case below compares the kept lanes against the model and the
# masked lanes against the POISON the bench wrote before the run - see
# Bench.masked. The two halves are different failures: a drain that
# packed only the kept lanes would move every later lane's slot, and a
# drain that wrote the model's +0 over a masked lane would agree with
# the model and still have overwritten the caller's memory.
# ----------------------------------------------------------------------

def _mask_prog(fmt, maxdep=1):
    """r0 + r1, deposited. Both streams are read, so a lane that ran
    when it should not have shows in the deposits, in the counts and -
    with a signalling operand - in the flags."""
    insns = [seq.alu(sf.OP_ADD, rd=3, ra=0, rc=1)]
    insns += [seq.deposit(3)] * maxdep
    return seq.Program(fmt, insns + [seq.halt()], max_deposits=maxdep)


def _keep(n, seed, frac=3):
    """A mask with holes, derived rather than typed: every `frac`th
    lane cleared, offset by the seed so the holes fall in different
    places in different cases - including on a beat boundary, on a
    block boundary and in the middle of a byte."""
    return [(i + seed) % frac != 0 for i in range(n)]


@cocotb.test()
async def masked_at_every_block_length(dut):
    """The sweep. Every format, every interesting block length - a
    partial block, a whole one, a block and a half, several - with the
    mask's holes falling at a different offset each time.

    This is where a mask fetched from the wrong beat shows up: a block
    reads 256 consecutive lanes' bits at every format, so block b's
    bits begin at BIT blk_base, and the natural mistakes (scaling the
    offset by the element size, or by the block's byte count) give a
    block somebody else's lanes. Bench.masked asserts the fetch as an
    ADDRESS as well as comparing the answer.
    """
    bench = Bench(dut)
    await bench.start()
    # n=384 at fp32 and n=320 at fp64 are the ones that matter most:
    # their third and fifth blocks start at global lane 256, which is
    # the FIRST BIT OF THE SECOND BEAT of the mask. Every other case
    # here reads beat zero, so a fetch that ignored the beat index
    # entirely - or scaled it by the element size, or by the block's
    # byte count - would pass all of them.
    for name, ns in (("fp32", (8, 128, 129, 192, 256, 384)),
                     ("fp64", (5, 64, 65, 96, 128, 320)),
                     ("fp128", (3, 32, 33, 48)),
                     ("fp256", (1, 16, 17, 24, 32))):
        fmt = FORMATS[name]
        prog = _mask_prog(fmt)
        for n in ns:
            await bench.masked(
                fmt, prog, operands(fmt, n, 7100 + n),
                operands(fmt, n, 7200 + n), operands(fmt, n, 7300 + n),
                n, _keep(n, n), f"{name} n={n}: a mask with holes")
    # ...and that the second beat is really reached, derived from the
    # geometry rather than believed: a block at global lane 256 or
    # beyond reads MASK_BASE + 32 or further.
    assert any(base >= BEAT_BYTES * 8
               for base in range(0, 384, lanes_per_block(FP32))), \
        "no case above crosses a mask beat boundary"
    dut._log.info(f"masked at every block length: "
                  f"{bench.cases['masked']} runs")


@cocotb.test()
async def masked_all_ones_is_the_unmasked_run(dut):
    """Control (a). An all-ones mask must be BIT-IDENTICAL to no mask
    at all - every deposit, every count, every scratch-out slot, the
    flags and the status - and a mask with holes must differ from it.
    The second half is what makes the first a gate: an all-ones mask
    that agreed because the tile ignored MODE[23] would pass the first
    half and prove nothing.
    """
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        n = lanes_per_block(fmt) + lanes_per_block(fmt) // 2
        prog = seq.Program(fmt, [
            seq.ldl(4, 0),
            seq.alu(sf.OP_ADD, rd=3, ra=0, rc=4),
            seq.deposit(3), seq.stl(3, 1), seq.halt()],
            max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
            n_scratch_in=1, n_scratch_out=2)
        a = operands(fmt, n, 7400 + n)
        b = operands(fmt, n, 7500 + n)
        blk = operands(fmt, n, 7600 + n)
        ebytes = fmt.width // 8

        await bench.program(fmt, prog, a, b, b, n,
                            f"{name}: the dense run beside the mask",
                            scratch_in=blk)
        plain = (bench.ram.fetch(D_BASE, n * ebytes),
                 bench.ram.fetch(CNT_BASE, 4 * n),
                 bench.ram.fetch(SOUT_BASE, n * 2 * ebytes))

        await bench.masked(fmt, prog, a, b, b, n, [True] * n,
                           f"{name}: an all-ones mask", scratch_in=blk)
        ones = (bench.ram.fetch(D_BASE, n * ebytes),
                bench.ram.fetch(CNT_BASE, 4 * n),
                bench.ram.fetch(SOUT_BASE, n * 2 * ebytes))
        assert ones == plain, (
            f"{name}: an all-ones mask is not bit-identical to no mask - "
            f"deposits {'differ' if ones[0] != plain[0] else 'agree'}, "
            f"counts {'differ' if ones[1] != plain[1] else 'agree'}, "
            f"scratch_out {'differ' if ones[2] != plain[2] else 'agree'}")

        keep = _keep(n, 1)
        await bench.masked(fmt, prog, a, b, b, n, keep,
                           f"{name}: a mask with holes", scratch_in=blk)
        holed = (bench.ram.fetch(D_BASE, n * ebytes),
                 bench.ram.fetch(CNT_BASE, 4 * n),
                 bench.ram.fetch(SOUT_BASE, n * 2 * ebytes))
        assert holed != plain, (
            f"{name}: a mask with holes was indistinguishable from no "
            f"mask, so the all-ones half above could not have failed")
    dut._log.info("all-ones is the unmasked run, and a holed mask is not")


@cocotb.test()
async def masked_lanes_contribute_no_flag(dut):
    """The flags, both cases the wave-1 ledger asks for.

    (1) The only lane that would signal is masked: the run's FLAGS are
    clear, and the same run unmasked is loud - which is what says the
    program really would have raised it.

    (2) An unmasked program overflows in lane k, and the NEXT run on
    the same instance masks lane k and signals nowhere: FLAGS clear.
    That is a claim about a REGISTER rather than about one run, which
    is why it is two runs on one Bench and not a second instance.
    """
    bench = Bench(dut)
    await bench.start()
    fmt = FP32
    n = lanes_per_block(fmt)
    k = 37
    prog = _mask_prog(fmt)

    # (1) the signalling lane, masked.
    a = [sf.one_bits(fmt)] * n
    b = [sf.one_bits(fmt)] * n
    b[k] = sf.snan_bits(fmt, 1)
    loud = await bench.program(fmt, prog, a, b, b, n,
                               "fp32: the signalling lane runs")
    assert loud.flags != 0, "the program does not signal; nothing is proved"
    await bench.masked(fmt, prog, a, b, b, n, [i != k for i in range(n)],
                       "fp32: the only signalling lane is masked")

    # (2) lane k overflows in one run; the next run masks it and is
    # quiet. The masked run's operands cannot signal anywhere, so any
    # bit in its FLAGS came from the run before it.
    big = sf.max_normal_bits(fmt)
    mul = seq.Program(fmt, [seq.alu(sf.OP_MUL, rd=3, ra=0, rb=1),
                            seq.deposit(3), seq.halt()], max_deposits=1)
    over_a = [sf.one_bits(fmt)] * n
    over_b = [sf.one_bits(fmt)] * n
    over_a[k] = over_b[k] = big

    async def overflowing_run():
        res = await bench.program(fmt, mul, over_a, over_b, over_b, n,
                                  "fp32: lane k overflows, unmasked")
        assert res.flags & sf.FLAG_OVERFLOW, \
            "lane k did not overflow, so the second run proves nothing"

    await bench.masked(fmt, mul, over_a, over_b, over_b, n,
                       [i != k for i in range(n)],
                       "fp32: lane k masked, after a run in which it "
                       "overflowed", pre=overflowing_run)
    dut._log.info("a masked lane contributes no flag, in its own run or "
                  "after a run in which it was loud")


@cocotb.test()
async def masked_actall_does_not_revive_a_masked_lane(dut):
    """ACTALL reactivates every lane THE CALLER HAS, and a masked lane
    is not one. A program that drops every lane with SETACT and then
    calls ACTALL must come back with exactly the unmasked lanes: if
    ACTALL read the block's lanes rather than the caller's, every
    masked lane would deposit into the caller's buffer from there on.
    """
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64"):
        fmt = FORMATS[name]
        n = lanes_per_block(fmt) + 3
        zero = sf.zero_bits(fmt)
        prog = seq.Program(fmt, [
            seq.deposit(0),            # every lane the caller has
            seq.setact(5),             # r5 is +0: all of them drop out
            seq.deposit(0),            # nothing
            seq.actall(),
            seq.deposit(0),            # the caller's lanes again
            seq.halt()], max_deposits=3)
        a = operands(fmt, n, 7700)
        await bench.masked(fmt, prog, a, [zero] * n, [zero] * n, n,
                           _keep(n, 2), f"{name}: ACTALL under a mask")
    dut._log.info("ACTALL does not revive a masked lane")


@cocotb.test()
async def masked_every_lane_completes_with_nothing_written(dut):
    """"A run whose every lane is masked completes with nothing written
    and nothing raised" - and the early exit sees an empty active mask
    from the first cycle, so a loop must not run its trip count. The
    operands are signalling NaNs: any flag at all would be a lane that
    ran.
    """
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp256"):
        fmt = FORMATS[name]
        n = lanes_per_block(fmt) + 1
        loud = [sf.snan_bits(fmt, 1)] * n
        prog = seq.Program(fmt, [
            seq.repeat(8),
            seq.alu(sf.OP_ADD, rd=3, ra=0, rc=1),
            seq.deposit(3), seq.endrep(), seq.halt()], max_deposits=8)
        t0 = get_sim_time("ns")
        await bench.masked(fmt, prog, loud, loud, loud, n, [False] * n,
                           f"{name}: every lane masked")
        empty = get_sim_time("ns") - t0
        # ...and the same program with the mask lifted takes longer,
        # which is the early exit having fired rather than a loop that
        # ran eight times over dead lanes.
        t0 = get_sim_time("ns")
        res = await bench.program(fmt, prog, loud, loud, loud, n,
                                  f"{name}: every lane running",
                                  check_flags=True)
        full = get_sim_time("ns") - t0
        assert res.flags != 0, "the program does not signal; nothing proved"
        assert empty < full, (
            f"{name}: an all-masked run took {empty} ns and the same "
            f"program with every lane live took {full} ns - the early "
            f"exit did not see the mask")
    dut._log.info("an all-masked run writes nothing, raises nothing and "
                  "exits its loops at once")


@cocotb.test()
async def masked_and_gathered_compose(dut):
    """R16 and R17 on one run: the mask decides which lanes run and the
    table decides what they read. The expectation is the model with
    both, so a mask that reached the gather - or a gather that skipped
    a lane because of the mask - is a wrong ANSWER here and not a cycle
    count.
    """
    bench = Bench(dut)
    await bench.start()
    fmt = FP64
    n = lanes_per_block(fmt) + 7
    src = operands(fmt, 29, 7800)
    tbl = _perm_table(n, len(src), 7801, none_every=5)
    prog = seq.Program(fmt, [
        seq.alu(sf.OP_ADD, rd=3, ra=0, rc=2),
        seq.deposit(3), seq.halt()], max_deposits=1)
    await bench.masked(
        fmt, prog, src, operands(fmt, n, 7802), operands(fmt, n, 7803),
        n, _keep(n, 4), "fp64: a gathered block, masked", idx_a=tbl)
    dut._log.info("a mask and a table compose")


@cocotb.test()
async def masked_actall_is_invisible_in_bytes_and_must_be_caught_elsewhere(dut):
    """V3's gate hole, closed (2026-09-15).

    `ACTALL` reading the block's lanes instead of the CALLER's revives a
    masked lane in hardware - and every case above still PASSES, because
    a revived lane's deposits, its count and its scratch-out slots are
    each held back by their own drain strobe. The bytes cannot show it.

    What is NOT behind a strobe is the run's sticky FLAGS word and the
    err bits beside it, so those are what this case reads:

    1. every lane dropped by SETACT, then ACTALL, then a MUL that
       overflows IN THE MASKED LANE ALONE. FLAGS must be 0; a build
       whose ACTALL ignores the mask gives 0b10100 (overflow, inexact).
    2. the same shape for DEPOSIT OVERFLOW: after ACTALL, a second
       SETACT leaves only the masked lane a candidate, and two deposits
       into a one-slot budget. err[3] must be clear; a build that
       revived the lane raises it.

    Both at more than one format, because the block geometry the revived
    lane sits in differs at each.
    """
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp64", "fp256"):
        fmt = FORMATS[name]
        lpb = lanes_per_block(fmt)
        n = lpb + max(1, lpb // 4)          # a ragged block, on purpose
        keep = _keep(n, 0)                  # every third lane masked
        k = next(i for i in range(n) if not keep[i])
        one = sf.one_bits(fmt)
        big = sf.max_normal_bits(fmt)

        # 1. the flags. Only lane k's operands can signal, and lane k is
        #    masked; every other lane multiplies 1.0 by 1.0.
        a = [one] * n
        b = [one] * n
        a[k] = b[k] = big
        prog = seq.Program(fmt, [
            seq.setact(5),                  # r5 is +0: every lane drops
            seq.actall(),                   # ...and the caller's return
            seq.alu(sf.OP_MUL, rd=3, ra=0, rb=1),
            seq.deposit(3), seq.halt()], max_deposits=1)
        want = seq.run(prog, a, b, b, lane_mask=keep)
        assert want.flags == 0, (
            f"{name}: the model says this masked run signals "
            f"{want.flags:#07b}, so the case is not the one intended")
        loud = seq.run(prog, a, b, b)
        assert loud.flags & sf.FLAG_OVERFLOW, (
            f"{name}: lane {k} does not overflow unmasked, so a revived "
            f"lane would raise nothing and this case could not fail")
        await bench.masked(fmt, prog, a, b, b, n, keep,
                           f"{name}: ACTALL, then an overflow in the "
                           f"masked lane alone")

        # 2. the deposit-overflow status bit. After ACTALL the caller's
        #    lanes are back; the second SETACT drops every lane whose
        #    stream-a element is +0, which is all of them EXCEPT lane k -
        #    and lane k is masked, so in a correct build nothing is left
        #    active and nothing deposits at all.
        a2 = [sf.zero_bits(fmt)] * n
        a2[k] = one
        prog2 = seq.Program(fmt, [
            seq.setact(5),                  # every lane drops
            seq.actall(),                   # the caller's lanes return
            seq.setact(0),                  # ...and only lane k survives
            seq.deposit(0), seq.deposit(0), # two into a one-slot budget
            seq.halt()], max_deposits=1)
        want2 = seq.run(prog2, a2, [one] * n, [one] * n, lane_mask=keep)
        assert want2.status == 0 and want2.counts == [0] * n, (
            f"{name}: the model's masked run already deposits or "
            f"overflows, so this case is not the one intended")
        unmasked2 = seq.run(prog2, a2, [one] * n, [one] * n)
        assert unmasked2.status & seq.STATUS_DEPOSIT_OVERFLOW, (
            f"{name}: lane {k} does not overflow its budget when it is "
            f"NOT masked, so a revived lane would raise nothing")
        await bench.masked(fmt, prog2, a2, [one] * n, [one] * n, n, keep,
                           f"{name}: ACTALL, then a deposit overflow "
                           f"reachable only in the masked lane")
    dut._log.info("ACTALL that revived a masked lane would be invisible "
                  "in the deposits and is caught in FLAGS and err[3]")


@cocotb.test()
async def masked_scratch_out_drains_a_converged_lane(dut):
    """V3's case (2026-09-15): the scratch-out drain is NOT masked by
    the active bit and IS masked by the caller's, and only a run with
    both kinds of lane in it can tell the two apart.

    Every case above masks lanes but never drops one with SETACT, so
    "a lane that converged still drains its scratch-out" went untested:
    a drain masked by the ACTIVE bit would have passed all of them.
    Here a quarter of the lanes converge and a third are masked, so
    every combination is present in one run - and at fp256 as well as
    fp32, because the drain's element selection differs with the beat.
    """
    bench = Bench(dut)
    await bench.start()
    for name in ("fp32", "fp256"):
        fmt = FORMATS[name]
        lpb = lanes_per_block(fmt)
        n = lpb + max(1, lpb // 3)
        keep = _keep(n, 0)                    # every third lane masked
        one = sf.one_bits(fmt)
        zero = sf.zero_bits(fmt)
        # r1 is +0 in every fourth lane, so SETACT drops exactly those -
        # and they are NOT the same lanes the mask clears.
        b = [one if i % 4 else zero for i in range(n)]
        conv = [i for i in range(n) if b[i] == zero]
        assert any(keep[i] for i in conv), (
            f"{name}: no lane both converges and is the caller's, so "
            f"this case cannot see the difference it exists for")
        prog = seq.Program(fmt, [
            seq.stl(0, 0),                    # slot 0 <- r0, every lane
            seq.setact(1),                    # the +0 lanes drop out
            seq.stl(0, 1),                    # slot 1 <- r0, the rest
            seq.deposit(0), seq.halt()],
            max_deposits=1, flags=seq.FLAG_SCRATCH_IO,
            n_scratch_in=0, n_scratch_out=2)
        a = operands(fmt, n, 7900 + n)
        want = await bench.masked(
            fmt, prog, a, b, b, n, keep,
            f"{name}: a converged lane drains its scratch-out under a "
            f"mask")
        # ...and the run really did have all three kinds of lane in it.
        assert any(not keep[i] for i in range(n)), f"{name}: no masked lane"
        assert any(keep[i] and b[i] == zero for i in conv), \
            f"{name}: no lane that converged AND belongs to the caller"
        assert any(keep[i] and b[i] != zero for i in range(n)), \
            f"{name}: no lane that stayed active"
        # slot 1 separates them: a converged lane never reached the
        # second STL, so its slot 1 is +0 while an active lane's is r0.
        for i in range(n):
            if not keep[i]:
                continue
            want_s1 = zero if b[i] == zero else (a[i] & ((1 << fmt.width) - 1))
            assert want.scratch_out[i * 2 + 1] == want_s1, (
                f"{name}: lane {i}: the model's slot 1 is not what "
                f"convergence says, so the case is mis-built")
    dut._log.info("the scratch-out drain skips a masked lane and keeps a "
                  "converged one")
