# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The orbit sequencer through the whole kernel.

Same shape as test_krnl.py and for the same reason: cocotbext-axi
provides the host (AxiLiteMaster on s_axi_control) and the HBM (one
AxiRam behind all four masters), the CSRs are written exactly as XRT
writes them, and every observable is compared bit-for-bit against
python/cft_golden/seq.py - which is the definition of correct.

What this bench covers that no unit bench can:

* **MODE[15] actually selects.** The two engines share the A and D
  masters, so "the sequencer runs" and "the elementwise engine still
  runs" are one claim about one mux, not two. An elementwise run sits
  in the middle of this file for exactly that reason: a sequencer run
  before it and after it, and if the mux ever hands the wrong engine
  the bus the regression run is what says so.

* **The program image is data the tile fetches.** It is written into
  the RAM and its address handed over in PROG_PTR, so the DMA path and
  the header checks are exercised the way a host exercises them, not
  through a backdoor load.

* **Deposits are addressed by index, and every slot is written.** The
  deposit and count windows are poisoned with 0xAA before every run.
  A slot no lane deposited into must come back +0 (SEQUENCER.md calls
  that normative, because a run whose untouched slots kept the host's
  previous contents would not be reproducible), and the bytes past the
  windows must still be poison - the tail of the caller's buffer
  belongs to the caller.

* **A refusal is not a run.** Two ways to be refused, one answer:
  STATUS exactly 0x8, deposits and counts untouched, and FLAGS still
  the PREVIOUS run's, because scrubbing them would be rewriting
  history.

The programs are directed rather than fuzzed. The fuzz lives where it
is cheap - python/tests and host/tests run tens of thousands of random
programs against the model - and what a full-kernel bench under Icarus
buys is the plumbing, once per feature, at a size that finishes.
"""

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
    FP32, FP64, FP256, PREC_CODE,
    OP_FMA, OP_ADD, OP_MUL, OP_CMPLT,
    zero_bits, one_bits, inf_bits, qnan_bits,
    min_subnormal_bits, max_normal_bits,
)
from cft_golden import seq  # noqa: E402

from test_krnl import run_op  # noqa: E402

# CSR map (rtl/cft_csr.sv == hw/kernel.xml == docs/ARCHITECTURE.md)
CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50
PROGPTR, CNTPTR = 0x54, 0x5C

MODE_SEQ = 1 << 15          # this run belongs to cft_seq
CAPS_SEQ = 1 << 15          # ... and this bitstream has one

ST_REFUSED = 1 << 3
ST_DEPOSIT_OVF = 1 << 4

# Far enough apart that a run cannot reach its neighbour's region even
# with the whole deposit window and a generous guard band.
A_BASE, B_BASE, C_BASE = 0x00000, 0x20000, 0x40000
D_BASE, PROG_BASE, CNT_BASE = 0x60000, 0x80000, 0xA0000
# The elementwise regression's own corner of the same memory.
EW_BASES = (0xC0000, 0xD0000, 0xE0000, 0xF0000)

POISON = 0xAA
GUARD = 64                  # bytes checked past each window


async def write64(axil, addr, val):
    await axil.write_dword(addr, val & 0xFFFFFFFF)
    await axil.write_dword(addr + 4, (val >> 32) & 0xFFFFFFFF)


def pack(fmt, values):
    ebytes = fmt.width // 8
    return b"".join(v.to_bytes(ebytes, "little") for v in values)


def gen_stream(fmt, n, rng, tame=False):
    """Operands for a program rather than for one operation.

    `tame` keeps magnitudes near 1 so an orbit that squares its input
    three times still lands on finite numbers - which is what makes a
    loop's later iterations test anything. The untamed pool is the
    usual one: signed zeros, infinities, NaN, the subnormal edge.
    """
    pool = [zero_bits(fmt), zero_bits(fmt, 1), one_bits(fmt),
            inf_bits(fmt), qnan_bits(fmt), min_subnormal_bits(fmt),
            max_normal_bits(fmt)]
    tame_pool = [one_bits(fmt), zero_bits(fmt), zero_bits(fmt, 1)]
    out = []
    for _ in range(n):
        if tame:
            if rng.random() < 0.4:
                out.append(rng.choice(tame_pool))
            else:
                # a normal number with an exponent within a few of the
                # bias, so squaring stays representable
                exp = fmt.bias + rng.randint(-3, 3)
                sign = rng.getrandbits(1)
                man = rng.getrandbits(fmt.man_w)
                out.append((sign << (fmt.width - 1)) |
                           (exp << fmt.man_w) | man)
        elif rng.random() < 0.35:
            out.append(rng.choice(pool))
        else:
            out.append(rng.getrandbits(fmt.width))
    return out


async def poll_done(dut, axil, what, tries=3000):
    for _ in range(tries):
        await ClockCycles(dut.ap_clk, 10)
        if (await axil.read_dword(CTRL)) & 0x2:      # ap_done, clear-on-read
            return
    raise AssertionError(f"{what}: the kernel never finished")


async def stage_and_start(axil, ram, image, prog, va, vb, vc, n,
                          prec_code, op_noise=0):
    """Everything a host does between having a program and having an
    answer, in the order XRT does it."""
    ebytes = prog.fmt.width // 8
    dep_bytes = n * prog.max_deposits * ebytes
    cnt_bytes = n * 4

    if n:
        ram.write(A_BASE, pack(prog.fmt, va))
        ram.write(B_BASE, pack(prog.fmt, vb))
        ram.write(C_BASE, pack(prog.fmt, vc))
    ram.write(PROG_BASE, image)
    # Poison, so "+0 in a slot nobody deposited into" is a statement
    # about what the tile wrote and not about what the buffer held.
    ram.write(D_BASE, bytes([POISON]) * (dep_bytes + GUARD))
    ram.write(CNT_BASE, bytes([POISON]) * (cnt_bytes + GUARD))

    await axil.write_dword(MODE, op_noise | (prec_code << 8) | MODE_SEQ)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await write64(axil, PROGPTR, PROG_BASE)
    await write64(axil, CNTPTR, CNT_BASE)
    await axil.write_dword(CTRL, 1)


async def run_prog(dut, axil, ram, prog, va, vb, vc, name, op_noise=0):
    """One sequencer run, scored against the model on every observable."""
    fmt = prog.fmt
    ebytes = fmt.width // 8
    n = len(va)
    maxd = prog.max_deposits
    dep_bytes = n * maxd * ebytes
    cnt_bytes = n * 4

    res = seq.run(prog, va, vb, vc)

    await stage_and_start(axil, ram, prog.to_bytes(), prog, va, vb, vc, n,
                          PREC_CODE[fmt.name], op_noise)
    await poll_done(dut, axil, name)

    got_dep = ram.read(D_BASE, dep_bytes + GUARD)
    bad = 0
    for k in range(n * maxd):
        g = int.from_bytes(got_dep[k * ebytes:(k + 1) * ebytes], "little")
        if g != res.deposits[k]:
            bad += 1
            if bad <= 8:
                dut._log.error(
                    f"{name}: deposit slot {k} (lane {k // maxd}, "
                    f"d={k % maxd}) got {g:#x} want {res.deposits[k]:#x}")
    assert bad == 0, f"{name}: {bad}/{n * maxd} deposit slots differ"
    assert got_dep[dep_bytes:] == bytes([POISON]) * GUARD, \
        f"{name}: the tile wrote past the deposit window"

    got_cnt = ram.read(CNT_BASE, cnt_bytes + GUARD)
    for i in range(n):
        g = int.from_bytes(got_cnt[i * 4:(i + 1) * 4], "little")
        assert g == res.counts[i], (
            f"{name}: lane {i} deposit count {g}, model says "
            f"{res.counts[i]} - and the count is not recoverable from the "
            f"buffer, because +0 is a legal deposit")
    assert got_cnt[cnt_bytes:] == bytes([POISON]) * GUARD, \
        f"{name}: the tile wrote past the count window"

    got_f = await axil.read_dword(FLAGS)
    assert got_f == res.flags, \
        f"{name}: FLAGS {got_f:#07b}, model says {res.flags:#07b}"
    got_st = await axil.read_dword(STATUS)
    assert got_st == res.status, \
        f"{name}: STATUS {got_st:#07b}, model says {res.status:#07b}"

    dut._log.info(f"{name}: {n} lanes x {maxd} deposits bit-exact, "
                  f"flags {got_f:#07b}, status {got_st:#07b}")
    return got_f


async def run_refused(dut, axil, ram, image, prog, va, vb, vc, n,
                      prec_code, name, want_flags):
    """A run the tile throws back. The assertions are the elementwise
    refusal test's, plus the two a sequencer adds: the deposit and
    count buffers are the caller's until a run writes them."""
    ebytes = prog.fmt.width // 8
    dep_bytes = n * prog.max_deposits * ebytes
    cnt_bytes = n * 4

    await stage_and_start(axil, ram, image, prog, va, vb, vc, n, prec_code)
    await poll_done(dut, axil, name)

    got_st = await axil.read_dword(STATUS)
    assert got_st == ST_REFUSED, (
        f"{name}: STATUS {got_st:#07b}, want exactly {ST_REFUSED:#07b} - a "
        f"refusal is not a bus fault and must not read as one")
    assert ram.read(D_BASE, dep_bytes + GUARD) == \
        bytes([POISON]) * (dep_bytes + GUARD), \
        f"{name}: a refused run wrote deposits"
    assert ram.read(CNT_BASE, cnt_bytes + GUARD) == \
        bytes([POISON]) * (cnt_bytes + GUARD), \
        f"{name}: a refused run wrote counts"
    got_f = await axil.read_dword(FLAGS)
    assert got_f == want_flags, (
        f"{name}: FLAGS {got_f:#07b} after a refusal, want the previous "
        f"run's {want_flags:#07b} - a refusal is not a run, and scrubbing "
        f"the last one's flags is rewriting history")
    dut._log.info(f"{name}: refused, STATUS {got_st:#07b}, "
                  f"FLAGS held at {got_f:#07b}")


# ---- the programs ----------------------------------------------------
#
# Each one is chosen for a feature of the machine rather than for an
# interesting orbit; the orbits are the model's business.

def prog_two_deposits(fmt):
    """The straight line: two ALU instructions, two deposits, halt.
    ADD reads a and c (b is steered to 1.0), which is why r1 arrives
    through rc rather than rb - a bench that got that backwards would
    agree with itself and with nothing else."""
    return seq.Program(fmt, [
        seq.alu(OP_MUL, rd=3, ra=0, rb=0),        # r3 = a*a
        seq.deposit(3),
        seq.alu(OP_ADD, rd=4, ra=3, rc=1),        # r4 = r3 + b
        seq.deposit(4),
        seq.halt(),
    ], consts=[], max_deposits=2)


def prog_loop_setact(fmt):
    """A bounded loop whose lanes drop out: three squarings, a deposit
    each time, and SETACT narrowing on r1. Lanes whose r1 is +-0 leave
    after the first iteration and deposit once; the rest deposit three
    times. That divergence in the COUNTS is P2 and P3 together - the
    slot a lane writes depends on its own deposit count, and the early
    exit must not change it."""
    return seq.Program(fmt, [
        seq.repeat(3),
        seq.alu(OP_MUL, rd=0, ra=0, rb=0),        # r0 = r0*r0
        seq.deposit(0),
        seq.setact(1),
        seq.endrep(),
        seq.halt(),
    ], consts=[], max_deposits=3)


def prog_actall(fmt):
    """ACTALL at the top level, after a SETACT has dropped lanes.

    The deposit after it must land for every lane - but with the value
    a dropped lane held BEFORE it dropped, because an inactive lane
    does not write. So the second deposit distinguishes "reactivated"
    from "never stopped", which a program without ACTALL cannot."""
    return seq.Program(fmt, [
        seq.alu(OP_FMA, rd=3, ra=0, rb=1, rc=2),  # r3 = a*b + c
        seq.deposit(3),
        seq.setact(3),
        seq.alu(OP_ADD, rd=4, ra=3, rc=0),        # r4 = r3 + a, active only
        seq.actall(),
        seq.deposit(4),
        seq.halt(),
    ], consts=[], max_deposits=2)


def prog_consts(fmt):
    """The constant bank, which is the one structure a program has that
    the elementwise engine has no analogue for. kb names a constant
    rather than a register, and CMPLT proves a non-arithmetic opcode
    reaches the same lane array."""
    return seq.Program(fmt, [
        seq.alu(OP_MUL, rd=3, ra=0, rb=1, kb=True),   # r3 = a * k1
        seq.deposit(3),
        seq.alu(OP_CMPLT, rd=4, ra=3, rb=2, kb=True),  # r4 = r3 < k2
        seq.deposit(4),
        seq.halt(),
    ], consts=[zero_bits(fmt), one_bits(fmt), max_normal_bits(fmt)],
        max_deposits=2)


def prog_overflow(fmt):
    """Two deposits into a one-slot budget. The first is kept, the
    second dropped, and STATUS[4] says so - in STATUS and not in
    FLAGS, because the five IEEE flags mean what 754 says they mean and
    "your buffer was too small" is not one of them."""
    return seq.Program(fmt, [
        seq.alu(OP_MUL, rd=3, ra=0, rb=1),
        seq.deposit(3),
        seq.deposit(0),
        seq.halt(),
    ], consts=[], max_deposits=1)


def prog_zero_deposits(fmt):
    """A budget of nothing, which is LEGAL and is not the same thing as
    a refusal.

    The model's validator accepts `0 <= max_deposits <= MAX_DEPOSITS`,
    cft_seq refuses only `max_deposits > MAXD`, and SEQUENCER.md's list
    of what the loader throws back does not mention zero. So the run
    happens: every DEPOSIT finds `counts[i] >= 0` already true, drops
    its value, and raises STATUS[4]. The deposit window is `n * 0`
    elements wide, so the whole of it is guard - which makes this the
    sharpest form of "the tile wrote nothing it was not asked to",
    since there is no legitimate byte for a stray write to hide in.

    Counts are still written, and are all zero. That is the distinction
    the run has to make: a lane that deposited nothing is not a lane the
    tile forgot, and a host reading n untouched poison words could not
    tell those apart."""
    return seq.Program(fmt, [
        seq.alu(OP_ADD, rd=3, ra=0, rc=1),
        seq.deposit(3),
        seq.halt(),
    ], consts=[], max_deposits=0)


@cocotb.test()
async def krnl_sequencer(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    # Four masters, ONE memory - the argument is test_krnl.py's, and it
    # binds harder here: the sequencer's program image and its deposits
    # travel on the A and D masters respectively, so a private store
    # per attachment would let a wrong PROG_PTR read a program that
    # exists nowhere the tile could have put it.
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 21)
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 21, mem=ram_a.mem)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 21, mem=ram_a.mem)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 21, mem=ram_a.mem)
    ram = ram_a
    assert ram_b.mem is ram_a.mem and ram_c.mem is ram_a.mem \
        and ram_d.mem is ram_a.mem

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    assert await axil.read_dword(VERSION) == 0x00000600, \
        "the map grew by four registers at v0.6.0"
    caps = await axil.read_dword(CAPS)
    assert caps & CAPS_SEQ, (
        "CAPS bit 15 must advertise the sequencer - it is what a host asks "
        "before it writes PROG_PTR, and the alternative is guessing from "
        "VERSION")

    # The two new registers store and read back like every other
    # pointer. Trivial, and the first thing to check: a map entry that
    # decodes to the default reads zero, starts a run against address
    # zero, and looks exactly like a sequencer bug.
    for addr, val in ((PROGPTR, 0x0000_0001_2345_6780),
                      (CNTPTR,  0x0000_0002_4680_ACE0)):
        await write64(axil, addr, val)
        lo = await axil.read_dword(addr)
        hi = await axil.read_dword(addr + 4)
        assert (hi << 32) | lo == val, \
            f"CSR {addr:#x} read back {(hi << 32) | lo:#x}, wrote {val:#x}"

    rng = random.Random(4242)

    # ---- fp32: the straight line, then the loop ----------------------
    n = 16
    p = prog_two_deposits(FP32)
    await run_prog(dut, axil, ram, p,
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng), "fp32 two-deposits")

    # MODE[7:0] is IGNORED on a sequencer run - the program says what to
    # compute. Issue a hostile opcode byte alongside MODE[15] and the
    # answer must not move.
    await run_prog(dut, axil, ram, p,
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng), "fp32 two-deposits, op noise",
                   op_noise=0xA5)

    va = gen_stream(FP32, n, rng, tame=True)
    # Half the lanes carry a zero in r1 and leave the loop after one
    # iteration; the rest run all three. Chosen rather than drawn, so
    # the count divergence is guaranteed to be in the run.
    vb = [zero_bits(FP32) if i % 2 else one_bits(FP32) for i in range(n)]
    flags_loop = await run_prog(dut, axil, ram, prog_loop_setact(FP32),
                                va, vb, gen_stream(FP32, n, rng),
                                "fp32 loop+setact")

    await run_prog(dut, axil, ram, prog_consts(FP32),
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng), "fp32 constant bank")

    # ---- a refusal, straight after a run with flags to protect -------
    #
    # A program is compiled for one format, because its constants are
    # format-width values. Issue this fp32 image under MODE fp64 and the
    # tile must throw it back rather than read the constants as half as
    # many twice-as-wide ones.
    p32 = prog_two_deposits(FP32)
    flags_before = await axil.read_dword(FLAGS)
    await run_refused(dut, axil, ram, p32.to_bytes(), p32,
                      gen_stream(FP32, 8, rng), gen_stream(FP32, 8, rng),
                      gen_stream(FP32, 8, rng), 8, PREC_CODE["fp64"],
                      "format mismatch", flags_before)

    # The other refusal the hardware owes: an image that is not one.
    # Everything subtler belongs to cft_program_load; this is the check
    # that protects the tile from a stream that bypassed it.
    bad = bytearray(p32.to_bytes())
    bad[0] ^= 0xFF                                  # "CFTP" no longer
    await run_refused(dut, axil, ram, bytes(bad), p32,
                      gen_stream(FP32, 8, rng), gen_stream(FP32, 8, rng),
                      gen_stream(FP32, 8, rng), 8, PREC_CODE["fp32"],
                      "bad magic", flags_before)

    # A refusal must not have poisoned the machine either.
    await run_prog(dut, axil, ram, p32,
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng), "fp32 after two refusals")

    # ---- the deposit overflow ----------------------------------------
    n8 = 8
    povf = prog_overflow(FP32)
    va = gen_stream(FP32, n8, rng)
    vb = gen_stream(FP32, n8, rng)
    vc = gen_stream(FP32, n8, rng)
    # The model has to overflow on THESE inputs, or the run below
    # proves nothing about bit 4 - it would simply be another program
    # that happened to fit.
    assert seq.run(povf, va, vb, vc).status == ST_DEPOSIT_OVF, \
        "the overflow program must overflow in the model"
    await run_prog(dut, axil, ram, povf, va, vb, vc, "fp32 deposit overflow")

    # The degenerate budget, which is legal. Every deposit overflows and
    # the deposit window has no legitimate bytes at all, so this is the
    # one run where ANY write to D is a bug. It is a compute case and
    # not a refusal: STATUS must read exactly bit 4, and a tile that
    # answers 0x8 here has refused a program the loader would have
    # passed and the model would have run.
    pzero = prog_zero_deposits(FP32)
    vz = (gen_stream(FP32, n8, rng), gen_stream(FP32, n8, rng),
          gen_stream(FP32, n8, rng))
    rzero = seq.run(pzero, *vz)
    assert rzero.status == ST_DEPOSIT_OVF and not rzero.deposits, \
        "max_deposits=0 must run, overflow, and produce no deposit slots"
    await run_prog(dut, axil, ram, pzero, *vz, "fp32 max_deposits=0")

    # ---- the elementwise engine, mid-file ----------------------------
    #
    # MODE[15] clear must still reach cft_engine_stream with the A and D
    # masters wired to it, after four sequencer runs have owned them.
    # This is the regression the shared-master mux exists to survive,
    # and it runs BETWEEN sequencer runs rather than after them so that
    # the handover is tested in both directions.
    await run_op(dut, axil, ram, FP32, OP_FMA, 32, seed=901, bases=EW_BASES)
    await run_op(dut, axil, ram, FP64, OP_ADD, 16, seed=902, bases=EW_BASES)

    # ---- the wide rungs ----------------------------------------------
    # Six, and not the eight that would fill the beats exactly. ACTALL
    # widens the active mask, and the one thing it must NOT widen it to
    # is the padding: a 256-bit beat carries four fp64 lanes, so n=6 is
    # two beats with lanes 6 and 7 present in the hardware and absent
    # from the caller's problem. Those two start inactive and must stay
    # so, because `active := true` means the n lanes that exist and not
    # the lanes the beat happens to be made of.
    #
    # The model is run on exactly the six, so it has no opinion about 6
    # and 7 to compare against - which is the point. A tile that
    # reactivated them would deposit past `n * max_deposits` and write
    # a seventh and eighth count, and both land in the guard bands the
    # run already checks. At n=8 that bug is invisible, which is why
    # the count moved.
    n4 = 6
    await run_prog(dut, axil, ram, prog_actall(FP64),
                   gen_stream(FP64, n4, rng), gen_stream(FP64, n4, rng),
                   gen_stream(FP64, n4, rng), "fp64 actall")

    n2 = 2
    await run_prog(dut, axil, ram, prog_two_deposits(FP256),
                   gen_stream(FP256, n2, rng), gen_stream(FP256, n2, rng),
                   gen_stream(FP256, n2, rng), "fp256 two-deposits")

    # ---- n = 0 -------------------------------------------------------
    #
    # Completes immediately, touching nothing. It is here because an
    # engine that treats "no lanes" as "one block of padding lanes"
    # passes every test above and writes a block of deposits into a
    # buffer the caller sized at zero.
    ram.write(D_BASE, bytes([POISON]) * GUARD)
    ram.write(CNT_BASE, bytes([POISON]) * GUARD)
    await stage_and_start(axil, ram, p32.to_bytes(), p32, [], [], [], 0,
                          PREC_CODE["fp32"])
    await poll_done(dut, axil, "n=0")
    assert ram.read(D_BASE, GUARD) == bytes([POISON]) * GUARD, \
        "n=0 wrote deposits"
    assert ram.read(CNT_BASE, GUARD) == bytes([POISON]) * GUARD, \
        "n=0 wrote counts"
    assert (await axil.read_dword(STATUS)) == 0, "n=0 is not a fault"

    # ---- and elementwise still works after all of it ------------------
    await run_op(dut, axil, ram, FP32, OP_MUL, 24, seed=903, bases=EW_BASES)
    dut._log.info(f"sequencer bench complete "
                  f"(loop run raised flags {flags_loop:#07b})")
