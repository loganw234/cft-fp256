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

from test_krnl import (  # noqa: E402
    run_op, check_seq_caps, check_caps2, krnl_param, krnl_param_bit,
    check_seam_words, PREC_MASK,
)

# The tile's instruction capacity, PARSED from the RTL rather than
# restated: a number in a test that copies a number in the RTL is a
# defect (docs/VERIFICATION.md), and this one moved at revisions 2, 3
# and 7. Since revision 7 it is a PARAMETER of cft_krnl, and a target
# that builds another value hands it here as CFT_GENERICS
# (test_krnl.krnl_param), so this is the number THIS build has.
SEQ_IMEM_D = krnl_param("SEQ_IMEM_D")
# ...and since revision 8 (R8S) the CAPACITY beside it: SEQ_IMEM_D is the
# instruction store, and past it a program streams from card memory up to
# SEQ_STREAM_D instructions - 2^24 on the U50, equal to the store on the
# open-core configurations, which do not stream.
SEQ_STREAM_D = krnl_param("SEQ_STREAM_D")
# ...and the scratch's depth, on the same terms. It moved into existence
# at revision 3 and to 2,048 at revision 7 - and unlike the other two it
# is part of what an instruction MEANS (a non-strict STX/LDX reduces
# modulo it), so every model run below is at this depth
# (seq.run(..., scratch_depth=SEQ_SCRATCH_D)), never at the model's
# default.
SEQ_SCRATCH_D = krnl_param("SEQ_SCRATCH_D")
# ...and the deposit budget, which the header check holds max_deposits to.
SEQ_MAXD = krnl_param("SEQ_MAXD")
# Cycles a block spends wiping a program's WHOLE scratch: SCRATCH_D slots x
# NBEATS beats, one a cycle (cft_seq's S_ZERO), 4,096 at 256 and 32,768 at
# 2,048, which is past the default budget below on its own. A block of an
# indexing program, or of one whose static slots or scratch-out reach the
# top, can pay it - since revision 7 only as far as something wrote since
# the last wipe, so this is a bound - and a case that may asks for this
# much more per block (poll_done counts polls of ten cycles).
WIPE_TRIES = SEQ_SCRATCH_D * 16 // 10

# CSR map (rtl/cft_csr.sv == hw/kernel.xml == docs/ARCHITECTURE.md)
CTRL, MODE, NREG = 0x00, 0x10, 0x18
APTR, BPTR, CPTR, DPTR = 0x20, 0x28, 0x30, 0x38
FLAGS, MAGIC, VERSION, CAPS, STATUS = 0x40, 0x44, 0x48, 0x4C, 0x50
PROGPTR, CNTPTR, BANKPTR = 0x54, 0x5C, 0x64
# Revision 3's three: the second capability word, and the two pointers
# the per-run scratch block rides on.
CAPS2, SINPTR, SOUTPTR = 0x6C, 0x70, 0x78
# ABI 0.14: the four index-table pointers and the lane mask's.
IDXAPTR, IDXBPTR, IDXCPTR = 0x88, 0x90, 0x98
IDXSIPTR, MASKPTR = 0xA0, 0xA8
# Revision 8's seam (VERSION 0xB00): R23's per-lane flag block.
LFLAGSPTR = 0xB0

MODE_SEQ = 1 << 15          # this run belongs to cft_seq
CAPS_SEQ = 1 << 15          # ... and this bitstream has one
# MODE[22:19]: which input blocks are fetched through a table (R16),
# and MODE[23]: the lane mask (R17). Both are honoured on this build
# and each is refused on one whose feature localparam is clear.
MODE_IDX_A, MODE_IDX_B = 1 << 19, 1 << 20
MODE_IDX_C, MODE_IDX_SI = 1 << 21, 1 << 22
MODE_LANE_MASK = 1 << 23
CAPS2_INDEXED = 1 << 9
CAPS2_LANE_MASK = 1 << 10
# MODE[24]: R23's per-lane flag block (revision 8), honoured only under
# CAPS2[13] - which no build set at revision 8's seam, and every build has
# set since R23 was built (round 2).
MODE_LANE_FLAGS = 1 << 24
CAPS2_LANE_FLAGS = 1 << 13
# CAPS2[11]: R21's augadd and augerr, where the build carries them
# (EN_AUGADD; the quad's tile does not - tb/Makefile's krnlseqnoaug).
CAPS2_AUGADD = 1 << 11
# CAPS2[12]: R22's post-step on STX and LDX, on every build since round 2.
CAPS2_SCRATCH_STEP = 1 << 12
# CAPS2[14]: R24's flag control (QUIET, ENDQUIET, RAISE; STATUS[6]),
# published since revision 8's round 2 built it.
CAPS2_FLAG_CONTROL = 1 << 14

ST_REFUSED = 1 << 3
ST_DEPOSIT_OVF = 1 << 4

# Far enough apart that a run cannot reach its neighbour's region even
# with the whole deposit window and a generous guard band.
A_BASE, B_BASE, C_BASE = 0x00000, 0x20000, 0x40000
D_BASE, CNT_BASE = 0x60000, 0xA0000
# The image gets the TOP of the model RAM, and needs it: at IMEM_D
# 16384 a full program is 32 + 8 * 16384 = 131,104 bytes, which is four
# times what revision 2 held. It used to sit at 0x80000 with 0xA0000
# above it, and the first 16,384-instruction case staged an image whose
# last ninety-six bytes ran into the count region - which the run then
# poisoned, so the tile fetched twelve corrupted instructions and every
# deposit differed. 0x180000 leaves 512 KB clear below the 2 MB the
# model RAM is.
PROG_BASE = 0x180000
# The per-run constant bank (revision 2). Its own region, far from the
# image: the whole point of BANK_EXT is that the two are separate
# buffers, and a tile that quietly read the constants out of the image
# would pass every check here if they shared one.
# The elementwise regression's own corner of the same memory.
BANK_BASE = 0xB0000
# The two scratch blocks (revision 3), each in its own region: the
# preload is read through m_axi_a with the image and the bank, and the
# scratch-out block is written through m_axi_d beside the deposits and
# the counts, so an overlap would hide exactly the mistakes these
# regions exist to catch.
SIN_BASE, SOUT_BASE = 0x110000, 0x140000
# The four index tables (ABI 0.14), each in its own region and far from
# the buffers it indexes, for the reason BANK_BASE is far from the
# image: a gather that read its entries out of the stream it indexes
# would pass every check here if the two regions touched.
IA_BASE, IB_BASE = 0x150000, 0x158000
IC_BASE, ISI_BASE = 0x160000, 0x168000
# ...and the lane mask (R17), in its own region for the same reason: a
# fetch that read the mask out of a table, or out of a stream, would
# pass every check here if the regions touched. One bit a lane, so
# 64 KB is half a million lanes.
MASK_BASE = 0x170000
# R23's per-lane flag block (revision 8), a byte a lane at LFLAGS_PTR
# (0xB0), in its own region for the reason every block above has one:
# the 64 KB between the elementwise corner and the scratch-in block.
LF_BASE = 0x100000
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


def pack_idx(table):
    """An index table as the device receives it: u32 little-endian,
    dense, and BEAT-PADDED - the tile reads whole beats and a block's
    last one may reach past the entries the caller has."""
    raw = b"".join(int(t).to_bytes(4, "little") for t in table)
    return raw + bytes(POISON for _ in range(-len(raw) % 32))


async def stage_and_start(axil, ram, image, prog, va, vb, vc, n,
                          prec_code, op_noise=0, bank=None,
                          scratch_in=None, idx=(None, None, None, None),
                          mode_extra=0, mask=None, lane_flags=False):
    """Everything a host does between having a program and having an
    answer, in the order XRT does it.

    `bank` is a BANK_EXT program's constants, staged in their own region
    and handed over in BANK_PTR exactly as PROG_PTR hands over the
    image - which is the whole of what the new register has to do.
    `scratch_in` is the same story one revision later, through
    SCRATCH_IN_PTR, with SCRATCH_OUT_PTR as its answer.
    """
    ebytes = prog.fmt.width // 8
    dep_bytes = n * prog.max_deposits * ebytes
    cnt_bytes = n * 4
    sout_bytes = n * prog.n_scratch_out * ebytes

    if n:
        # The streams as given: with a table these are the SOURCES and
        # have no reason to hold n elements.
        ram.write(A_BASE, pack(prog.fmt, va))
        ram.write(B_BASE, pack(prog.fmt, vb))
        ram.write(C_BASE, pack(prog.fmt, vc))
    ram.write(PROG_BASE, image)
    # Poison, so "+0 in a slot nobody deposited into" is a statement
    # about what the tile wrote and not about what the buffer held.
    ram.write(D_BASE, bytes([POISON]) * (dep_bytes + GUARD))
    ram.write(CNT_BASE, bytes([POISON]) * (cnt_bytes + GUARD))
    # ...and a fixed 256 bytes past whatever this program's block
    # needs, so the NEGATIVE half - a program that declares no scratch
    # output must not write here at all - has ground to stand on even
    # when the window is zero bytes wide.
    ram.write(SOUT_BASE, bytes([POISON]) * (sout_bytes + 256 + GUARD))

    # ABI 0.14's four tables, staged and pointed at exactly as the
    # scratch block is, and their MODE bits set only where a table was
    # given. A pointer with no bit set is POISONED, so a tile that read
    # an unselected table would read nothing that exists.
    idx_mode = 0
    for table, bit, base, reg in (
            (idx[0], MODE_IDX_A, IA_BASE, IDXAPTR),
            (idx[1], MODE_IDX_B, IB_BASE, IDXBPTR),
            (idx[2], MODE_IDX_C, IC_BASE, IDXCPTR),
            (idx[3], MODE_IDX_SI, ISI_BASE, IDXSIPTR)):
        if table is None:
            await write64(axil, reg, 0xDEAD_7000 | bit)
            continue
        ram.write(base, pack_idx(table))
        await write64(axil, reg, base)
        idx_mode |= bit
    # ABI 0.14's lane mask, on the tables' terms: staged where MASK_PTR
    # points and MODE[23] set only when one was given, and the pointer
    # POISONED when it was not - a tile that read a mask it was not
    # given would read nothing that exists. One bit a lane, little end
    # first, built from `mask` here rather than typed.
    if mask is not None:
        raw = bytearray((n + 7) // 8)
        for _i, _k in enumerate(mask):
            if _k:
                raw[_i >> 3] |= 1 << (_i & 7)
        # The tile reads whole beats, so the bits past the run's lanes
        # are left POISON: a fetch that used them would give a block
        # lanes the caller does not have.
        ram.write(MASK_BASE, bytes(raw) + bytes([POISON]) * 64)
        await write64(axil, MASKPTR, MASK_BASE)
        idx_mode |= MODE_LANE_MASK
    else:
        await write64(axil, MASKPTR, 0xDEAD_8000)
    # R23's block (revision 8): MODE[24] and LFLAGS_PTR at 0xB0, the region
    # poisoned so a byte the tile did not write reads as the caller's. Where
    # no block is asked for, the pointer still aims at LF_BASE, so that a
    # tile ignoring MODE[24] writes where krnl_lane_flags looks - aimed at
    # 0xDEAD_9000, as it was, those bursts landed in the AXI RAM unseen and
    # the "nothing written without MODE[24]" leg could not fail
    # (verifier-VC34's plant k2, cfg_lflags_en tied high).
    if lane_flags:
        ram.write(LF_BASE, bytes([POISON]) * (n + GUARD))
        await write64(axil, LFLAGSPTR, LF_BASE)
        idx_mode |= MODE_LANE_FLAGS
    else:
        await write64(axil, LFLAGSPTR, LF_BASE)
    await axil.write_dword(MODE, op_noise | (prec_code << 8) | MODE_SEQ |
                           idx_mode | mode_extra)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await write64(axil, PROGPTR, PROG_BASE)
    await write64(axil, CNTPTR, CNT_BASE)
    if bank is not None:
        ram.write(BANK_BASE, pack(prog.fmt, bank))
        await write64(axil, BANKPTR, BANK_BASE)
    else:
        # Deliberately POISONED rather than left alone: a program that
        # is not BANK_EXT must never read this register, and pointing it
        # at an address with no constants at it is how that is checked
        # rather than asserted.
        await write64(axil, BANKPTR, 0xDEAD_0000)
    # The two scratch pointers, written the way PROG_PTR and BANK_PTR
    # are, and poisoned on the same terms: a program without
    # flags.SCRATCH_IO must read neither and write neither, and the
    # write one is the sharper check - a scratch-out block nobody asked
    # for would land in a host buffer that does not exist.
    if scratch_in is not None:
        ram.write(SIN_BASE, pack(prog.fmt, scratch_in))
    if prog.scratch_io:
        await write64(axil, SINPTR, SIN_BASE)
        await write64(axil, SOUTPTR, SOUT_BASE)
    else:
        await write64(axil, SINPTR, 0xDEAD_1000)
        await write64(axil, SOUTPTR, 0xDEAD_2000)
    await axil.write_dword(CTRL, 1)


async def run_prog(dut, axil, ram, prog, va, vb, vc, name, op_noise=0,
                   bank=None, scratch_in=None, tries=3000,
                   idx=(None, None, None, None), n=None, mask=None,
                   lane_flags=False, image=None):
    """One sequencer run, scored against the model on every observable.

    With an index table, `va`/`vb`/`vc` are the SOURCES that table
    indexes rather than the run's elements, so `n` stops being
    len(va) and is passed - which is the whole shape of R16 on the
    host side too."""
    fmt = prog.fmt
    ebytes = fmt.width // 8
    n = len(va) if n is None else n
    maxd = prog.max_deposits
    dep_bytes = n * maxd * ebytes
    cnt_bytes = n * 4

    res = seq.run(prog, va, vb, vc, bank=bank, scratch_in=scratch_in,
                  idx_a=idx[0], idx_b=idx[1], idx_c=idx[2],
                  idx_scratch_in=idx[3], lane_mask=mask,
                  scratch_depth=SEQ_SCRATCH_D)
    sout_bytes = n * prog.n_scratch_out * ebytes
    # R17: a masked lane's slots are the CALLER'S bytes, which here are
    # the poison written a few lines above. The model's arrays are
    # fresh and read +0 there, so comparing a masked lane against the
    # model would accept a drain that had overwritten the buffer.
    keep = [True] * n if mask is None else list(mask)

    # `image` is what the tile runs where it is not the model's program:
    # the quad's tile, built without R21, runs an augadd image the model
    # scores as the same program with HALT where the code stands.
    await stage_and_start(axil, ram,
                          prog.to_bytes() if image is None else image,
                          prog, va, vb, vc, n,
                          PREC_CODE[fmt.name], op_noise, bank=bank,
                          scratch_in=scratch_in, idx=idx, mask=mask,
                          lane_flags=lane_flags)
    await poll_done(dut, axil, name, tries=tries)

    # R23's block, where the run asked: lane i's byte at LF_BASE + i - the
    # address LFLAGS_PTR at 0xB0 was written with, so a register at 0xB0
    # that did not drive the pointer lands it elsewhere - and a masked
    # lane's byte the caller's poison; GUARD bytes past it untouched.
    if lane_flags:
        got_lf = ram.read(LF_BASE, n + GUARD)
        for i in range(n):
            if keep[i]:
                assert got_lf[i] == res.lane_flags[i], (
                    f"{name}: lane {i}'s flag byte {got_lf[i]:#04x}, model "
                    f"{res.lane_flags[i]:#04x}")
            else:
                assert got_lf[i] == POISON, (
                    f"{name}: lane {i} is masked and its flag byte was "
                    f"written")
        assert got_lf[n:] == bytes([POISON]) * GUARD, (
            f"{name}: the tile wrote past the lane-flag block")

    got_dep = ram.read(D_BASE, dep_bytes + GUARD)
    bad = 0
    for k in range(n * maxd):
        if not keep[k // maxd]:
            assert got_dep[k * ebytes:(k + 1) * ebytes] == \
                bytes([POISON]) * ebytes, (
                f"{name}: deposit slot {k} belongs to lane {k // maxd}, "
                f"which the mask cleared, and it was WRITTEN")
            continue
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
        if not keep[i]:
            assert got_cnt[i * 4:(i + 1) * 4] == bytes([POISON]) * 4, (
                f"{name}: lane {i} is masked and its count was written")
            continue
        g = int.from_bytes(got_cnt[i * 4:(i + 1) * 4], "little")
        assert g == res.counts[i], (
            f"{name}: lane {i} deposit count {g}, model says "
            f"{res.counts[i]} - and the count is not recoverable from the "
            f"buffer, because +0 is a legal deposit")
    assert got_cnt[cnt_bytes:] == bytes([POISON]) * GUARD, \
        f"{name}: the tile wrote past the count window"

    # The block the run hands back, read the way a host reads it: out
    # of the buffer SCRATCH_OUT_PTR named. A program that declares none
    # must have left the region entirely poison, which is the negative
    # half and runs on every other case in this file.
    got_so = ram.read(SOUT_BASE, sout_bytes + GUARD)
    for k in range(n * prog.n_scratch_out):
        if not keep[k // prog.n_scratch_out]:
            assert got_so[k * ebytes:(k + 1) * ebytes] == \
                bytes([POISON]) * ebytes, (
                f"{name}: scratch_out element {k} belongs to a masked "
                f"lane and was written - the scratch-out drain is not "
                f"masked by the ACTIVE bit and it IS masked by the "
                f"caller's")
            continue
        g = int.from_bytes(got_so[k * ebytes:(k + 1) * ebytes], "little")
        assert g == res.scratch_out[k], (
            f"{name}: scratch_out element {k} (lane "
            f"{k // prog.n_scratch_out}, slot {k % prog.n_scratch_out}) "
            f"got {g:#x} want {res.scratch_out[k]:#x}")
    assert got_so[sout_bytes:] == bytes([POISON]) * GUARD, \
        f"{name}: the tile wrote past the scratch-out window"
    if not prog.scratch_io:
        assert ram.read(SOUT_BASE, 256) == bytes([POISON]) * 256, (
            f"{name}: a program that declares no scratch output wrote "
            f"the scratch-out region anyway")

    got_f = await axil.read_dword(FLAGS)
    assert got_f == res.flags, \
        f"{name}: FLAGS {got_f:#07b}, model says {res.flags:#07b}"
    got_st = await axil.read_dword(STATUS)
    assert got_st == res.status, \
        f"{name}: STATUS {got_st:#07b}, model says {res.status:#07b}"

    dut._log.info(f"{name}: {n} lanes x {maxd} deposits bit-exact, "
                  f"flags {got_f:#07b}, status {got_st:#07b}")
    return res


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


async def run_refused_mode(dut, axil, ram, prog, va, vb, vc, n,
                           mode_extra, name, want_flags,
                           idx=(None, None, None, None)):
    """A run the CSR throws back for a MODE bit this build does not
    carry: STATUS[3], no write anywhere, and the previous run's FLAGS
    left alone. The refusal is the CSR's, so the image is valid and the
    only thing wrong with the run is the bit."""
    ebytes = prog.fmt.width // 8
    dep_bytes = n * prog.max_deposits * ebytes
    cnt_bytes = n * 4
    ram.write(D_BASE, bytes([POISON]) * (dep_bytes + GUARD))
    ram.write(CNT_BASE, bytes([POISON]) * (cnt_bytes + GUARD))
    await stage_and_start(axil, ram, prog.to_bytes(), prog, va, vb, vc, n,
                          PREC_CODE[prog.fmt.name], mode_extra=mode_extra,
                          idx=idx)
    await poll_done(dut, axil, name)
    got_st = await axil.read_dword(STATUS)
    assert got_st == ST_REFUSED, (
        f"{name}: STATUS {got_st:#07b}, want exactly {ST_REFUSED:#07b} - a "
        f"MODE bit this build does not honour must be REFUSED and never "
        f"ignored, because a run that quietly read the dense stream "
        f"would answer from the wrong elements with clean flags")
    assert ram.read(D_BASE, dep_bytes + GUARD) == \
        bytes([POISON]) * (dep_bytes + GUARD), \
        f"{name}: a refused run wrote deposits"
    assert ram.read(CNT_BASE, cnt_bytes + GUARD) == \
        bytes([POISON]) * (cnt_bytes + GUARD), \
        f"{name}: a refused run wrote counts"
    got_f = await axil.read_dword(FLAGS)
    assert got_f == want_flags, (
        f"{name}: FLAGS {got_f:#07b} after a refusal, want the previous "
        f"run's {want_flags:#07b}")
    dut._log.info(f"{name}: refused, STATUS {got_st:#07b}")


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



def prog_high_registers(fmt):
    """Revision 2 R1, through the whole kernel: a chain that lives
    entirely in r16..r31 and deposits from there.

    Not a decoding check - test_seq_core.py's fuzz does that at volume.
    What this is for is the register FILE: it doubled, its read and
    write addresses grew a bit, and the beat field moved from a fixed
    four bits to NBSH. A program that only ever names r0..r15 exercises
    the low half of the file and would pass with the high half wired to
    nothing at all.

    r31 is deposited LAST and r16 first, so a file whose high addresses
    aliased onto the low ones would show up as the wrong value in a
    slot rather than as a bus fault - which is the failure mode worth
    catching, because it is the quiet one.
    """
    return seq.Program(fmt, [
        seq.alu(OP_ADD, rd=16, ra=0, rc=2),      # r16 = a + c
        seq.alu(OP_MUL, rd=31, ra=16, rb=1),     # r31 = r16 * b
        seq.alu(OP_ADD, rd=23, ra=31, rc=16),    # r23 = r31 + r16
        seq.deposit(16),
        seq.deposit(23),
        seq.deposit(31),
        seq.deposit(20),                          # never written: +0
        seq.halt(),
    ], consts=[], max_deposits=4)


def prog_bank_ext(fmt):
    """Revision 2 R3: an image with no constant section, whose four
    constants arrive per run through BANK_PTR.

    `bytes == 32 + 8 * n_insns`, asserted here rather than trusted,
    because that identity IS the feature: if the image still carried
    the constants there would be nothing for the new register to do.
    """
    p = seq.Program(fmt, [
        seq.alu(OP_MUL, rd=17, ra=0, rb=1),
        seq.alu(OP_ADD, rd=18, ra=17, rc=0, kc=True),   # + bank[0]
        seq.deposit(18),
        seq.alu(OP_ADD, rd=19, ra=18, rc=3, kc=True),   # + bank[3]
        seq.deposit(19),
        seq.halt(),
    ], flags=seq.FLAG_BANK_EXT, n_consts=4, max_deposits=2)
    assert len(p.to_bytes()) == 32 + 8 * len(p.insns), \
        "a BANK_EXT image carries no constant section"
    return p



def prog_fills_imem(fmt, n_insns):
    """Revision 2 R2: a program of exactly `n_insns` instructions, the
    tile's whole instruction memory.

    The point is the deep addresses. IMEM_D went 1024 -> 4096 and PCW
    with it, so `pc`, `skip_depth` and the loop stack's body pointer
    all grew a bit, and imem's write cursor now needs twelve. A program
    that merely DECLARES 4,096 instructions proves only the header
    check; this one has to reach the last four.

    Executing 4,096 instructions the ordinary way would cost about
    forty cycles each, which is a bench nobody runs. So the bulk of the
    program is SKIPPED rather than executed, which is two cycles an
    instruction and is a stronger test of the memory than executing
    would be: the skip walks every word from the REPEAT to its matching
    ENDREP counting nesting, so an imem entry that came back as the
    wrong word - the aliasing a too-narrow address would cause -
    lands the skip on the wrong ENDREP and the program diverges. The
    filler is deliberately half REPEAT/ENDREP pairs so the nesting
    counter is exercised rather than a run of identical words.

    The last four instructions then execute for real, at PC 4092..4095,
    which is where all twelve bits of the address are needed:

        0            setact r5    - r5 is +0, so every lane drops out
        1            repeat 2     - no lane is active, so it is SKIPPED
        2 .. N-5     filler       - walked by the skip, never executed
        N-5          endrep       - where the skip must land
        N-4          actall       - lanes back (top level, so legal)
        N-3          r20 = a + c
        N-2          deposit r20
        N-1          halt
    """
    body = [seq.setact(5), seq.repeat(2)]
    fill_end = n_insns - 5
    i = 2
    while i < fill_end:
        # pairs where they fit, a plain ALU word otherwise, so the
        # skip's nesting counter sees real structure
        if i + 1 < fill_end and (i % 3):
            body += [seq.repeat(2), seq.endrep()]
            i += 2
        else:
            body.append(seq.alu(OP_ADD, rd=(i % 32), ra=0, rc=1))
            i += 1
    body += [seq.endrep(), seq.actall(),
             seq.alu(OP_ADD, rd=20, ra=0, rc=2),
             seq.deposit(20), seq.halt()]
    assert len(body) == n_insns, (
        f"the filler must land exactly on {n_insns}; it made {len(body)}")
    # the instructions that matter really are at the top of the memory
    assert seq.decode(body[n_insns - 1])["op"] == seq.HALT
    assert seq.decode(body[n_insns - 2])["op"] == seq.DEPOSIT
    return seq.Program(fmt, body, consts=[], max_deposits=1)


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
    assert await axil.read_dword(VERSION) == 0x00000B00, \
        ("the map grew again at v0.8.0 - CAPS2 at 0x6C and the two "
         "scratch pointers at 0x70/0x74 and 0x78/0x7C - at v0.9.0, by "
         "SEG/NRES at 0x80/0x84, at v0.10.0 by round 2's five pointers "
         "at 0x88..0xA8, and at v0.11.0 by revision 8's LFLAGS_PTR at "
         "0xB0")
    caps = await axil.read_dword(CAPS)
    check_seq_caps(caps)
    # CAPS2 against the localparam cft_krnl elaborates the scratch
    # from, so the register cannot drift from the memory it describes.
    check_caps2(await axil.read_dword(CAPS2))
    assert caps & CAPS_SEQ, (
        "CAPS bit 15 must advertise the sequencer - it is what a host asks "
        "before it writes PROG_PTR, and the alternative is guessing from "
        "VERSION")

    # The two new registers store and read back like every other
    # pointer. Trivial, and the first thing to check: a map entry that
    # decodes to the default reads zero, starts a run against address
    # zero, and looks exactly like a sequencer bug.
    for addr, val in ((PROGPTR, 0x0000_0001_2345_6780),
                      (CNTPTR,  0x0000_0002_4680_ACE0),
                      (BANKPTR, 0x0000_0003_1470_2580),
                      (SINPTR,  0x0000_0004_1357_9BD0),
                      (SOUTPTR, 0x0000_0005_2468_ACE0),
                      # revision 8's seam: R23's block, read by nothing
                      # yet, stored and read back like the rest
                      (LFLAGSPTR, 0x0000_0006_1357_2468)):
        await write64(axil, addr, val)
        lo = await axil.read_dword(addr)
        hi = await axil.read_dword(addr + 4)
        assert (hi << 32) | lo == val, \
            f"CSR {addr:#x} read back {(hi << 32) | lo:#x}, wrote {val:#x}"
    # ...and CAPS2 is READ-ONLY, which the map says and nothing else
    # checks: a writable capability register is a capability register a
    # host can be lied to by.
    caps2_before = await axil.read_dword(CAPS2)
    await axil.write_dword(CAPS2, 0xFFFF_FFFF)
    assert await axil.read_dword(CAPS2) == caps2_before, \
        "CAPS2 took a write; it is read-only like CAPS, MAGIC and VERSION"

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
    res_loop = await run_prog(dut, axil, ram, prog_loop_setact(FP32),
                              va, vb, gen_stream(FP32, n, rng),
                              "fp32 loop+setact")
    flags_loop = res_loop.flags

    await run_prog(dut, axil, ram, prog_consts(FP32),
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng), "fp32 constant bank")


    # ---- revision 2 R1: the high half of the register file ------------
    await run_prog(dut, axil, ram, prog_high_registers(FP32),
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng), "fp32 registers 16..31")

    # ---- revision 2 R3: a BANK_EXT program through BANK_PTR ----------
    #
    # The same image, run TWICE with different banks. One run would
    # prove the pointer is read; two prove the answer follows the bank,
    # which is the claim - a tile that ignored BANK_PTR and read four
    # zeros would give the same wrong answer both times, and a tile that
    # cached the first bank would give the first answer twice.
    pbank = prog_bank_ext(FP32)
    for tag, bank in (
            ("A", [one_bits(FP32), zero_bits(FP32),
                   max_normal_bits(FP32), one_bits(FP32)]),
            ("B", [zero_bits(FP32, 1), min_subnormal_bits(FP32),
                   qnan_bits(FP32), max_normal_bits(FP32)])):
        await run_prog(dut, axil, ram, pbank,
                       gen_stream(FP32, n, rng, tame=True),
                       gen_stream(FP32, n, rng, tame=True),
                       gen_stream(FP32, n, rng),
                       f"fp32 BANK_EXT, bank {tag}", bank=bank)

    # The wide rung too: a 256-bit constant is four beats of bank where
    # an fp32 one is a fraction of a beat, so the bank parser's byte
    # arithmetic is a different problem at each end of the ladder.
    pbank256 = prog_bank_ext(FP256)
    await run_prog(dut, axil, ram, pbank256,
                   gen_stream(FP256, 2, rng, tame=True),
                   gen_stream(FP256, 2, rng, tame=True),
                   gen_stream(FP256, 2, rng),
                   "fp256 BANK_EXT",
                   bank=[one_bits(FP256), zero_bits(FP256),
                         max_normal_bits(FP256), one_bits(FP256)])

    # ...and an ordinary image still runs with BANK_PTR pointing at
    # rubbish, which stage_and_start arranges on every non-bank run.
    # It is the negative half of the same claim: the register is read
    # only when flags.BANK_EXT says to read it.
    await run_prog(dut, axil, ram, prog_consts(FP32),
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng),
                   "fp32 constants in the image, BANK_PTR poisoned")

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


    # Revision 2's two new header refusals, and the reason CAPS[6]
    # exists. The 0x600 tile checked NEITHER reserved word, so an image
    # built for a later revision - one whose flags say something this
    # tile has never heard of - would have been half-understood and run.
    # This tile throws it back at the header, before a byte is computed.
    # flags[1] became SCRATCH_IO at revision 3 and flags[2]
    # SCRATCH_STRICT at revision 4, so the first bit this tile does not
    # know has moved up twice, to [3]; the second header word is
    # `scratch_io` and is still reserved while its flag is clear.
    #
    # MOVE this at revision 5 rather than deleting it. The check is
    # about a flag the tile does not know, whichever bit that happens to
    # be, so it needs one the header check still refuses - and the day
    # there is no such bit left is the day flags needs a VERSION step.
    for offset, value, why in (
            (24, 1 << 3, "flags[3], a flag bit this tile does not know"),
            (27, 0x80,   "flags[31], the top of the same word"),
            (28, 1,      "scratch_io set without flags.SCRATCH_IO")):
        bad = bytearray(p32.to_bytes())
        bad[offset] |= value
        await run_refused(dut, axil, ram, bytes(bad), p32,
                          gen_stream(FP32, 8, rng), gen_stream(FP32, 8, rng),
                          gen_stream(FP32, 8, rng), 8, PREC_CODE["fp32"],
                          f"header {why}", flags_before)

    # The positive control for those three: flags[0] is BANK_EXT and IS
    # known, so the identical mechanism must NOT refuse it. Without this
    # line a tile that refused every non-zero flags word would pass the
    # loop above and fail nothing.
    pbank_ctl = prog_bank_ext(FP32)
    assert pbank_ctl.to_bytes()[24] == 1, \
        "the positive control must actually set flags[0]"
    await run_prog(dut, axil, ram, pbank_ctl,
                   gen_stream(FP32, 8, rng, tame=True),
                   gen_stream(FP32, 8, rng, tame=True),
                   gen_stream(FP32, 8, rng),
                   "fp32 BANK_EXT is a KNOWN flag",
                   bank=[one_bits(FP32), zero_bits(FP32),
                         one_bits(FP32), zero_bits(FP32, 1)])

    # A refusal must not have poisoned the machine either.
    await run_prog(dut, axil, ram, p32,
                   gen_stream(FP32, n, rng), gen_stream(FP32, n, rng),
                   gen_stream(FP32, n, rng), "fp32 after two refusals")


    # ---- revision 2 R2: a program that fills the instruction memory --
    #
    # SEQ_IMEM_D was 4096 when this was written (32,768 at revision 7),
    # so this is the largest program the tile can hold - 32 + 8 *
    # SEQ_IMEM_D bytes of image - and four instructions that execute at
    # the last four PCs, where every address bit is needed. The
    # bulk is skipped rather than executed - see prog_fills_imem - so
    # the case costs about 8,200 cycles of skip rather than the 160,000
    # that executing every instruction would.
    #
    # Since revision 8 (R8S) a tile that streams holds SEQ_IMEM_D in its
    # store and takes SEQ_STREAM_D: the case is then an image of 32,769
    # instructions - one past revision 7's capacity, the image device-test
    # loads on a card - streamed through the kernel's A master past the
    # store, its last words at addresses past 2^15. A tile that does not
    # stream runs its store full, as before.
    n_imem = 16
    n_full = 32769 if SEQ_STREAM_D > SEQ_IMEM_D else SEQ_IMEM_D
    pimem = prog_fills_imem(FP32, n_full)
    assert len(pimem.to_bytes()) == 32 + 8 * n_full
    await run_prog(dut, axil, ram, pimem,
                   gen_stream(FP32, n_imem, rng, tame=True),
                   gen_stream(FP32, n_imem, rng, tame=True),
                   gen_stream(FP32, n_imem, rng, tame=True),
                   f"fp32 {n_full} instructions, "
                   + ("streamed past the store" if n_full > SEQ_IMEM_D
                      else "IMEM full"),
                   # The default budget is 30,000 cycles and this run
                   # needed more than twice that at IMEM_D 16384: about
                   # 20,500 to parse a 131 KB image an instruction a
                   # cycle, and about 33,000 more for the skip to walk
                   # every word of it to the matching ENDREP. It was
                   # inside the default at 4,096 and is the one case
                   # whose cost grows with IMEM_D: about 107,000 at
                   # 32,768 (revision 7), inside the 300,000 given.
                   tries=30000)

    # ...and one more than the capacity is refused at the header, which
    # is the boundary the capacity actually is. Where the capacity is the
    # store the image is emitted in full and honestly, so the refusal is
    # unambiguous about which check fired; where it streams, 2^24 + 1
    # instructions would be a 128 MB image, so it is the header alone -
    # the count is what is refused (R8S-streaming.md, section 8).
    if SEQ_STREAM_D > SEQ_IMEM_D:
        too_big = bytearray(pimem.to_bytes()[:32])
        too_big[8:12] = (SEQ_STREAM_D + 1).to_bytes(4, "little")
    else:
        too_big = bytearray(pimem.to_bytes())
        too_big[8:12] = (SEQ_IMEM_D + 1).to_bytes(4, "little")
        too_big += bytes(8)   # the honest body for one more insn
    # Re-read FLAGS here rather than reusing the word captured before
    # the refusal block: run_refused asserts the refusal did not scrub
    # the PREVIOUS RUN's flags, and the previous run is the IMEM-full
    # one just above, which raised inexact.
    flags_now = await axil.read_dword(FLAGS)
    await run_refused(dut, axil, ram, bytes(too_big), pimem,
                      gen_stream(FP32, 8, rng), gen_stream(FP32, 8, rng),
                      gen_stream(FP32, 8, rng), 8, PREC_CODE["fp32"],
                      f"n_insns {SEQ_STREAM_D + 1} exceeds the capacity",
                      flags_now)

    # ---- revision 7: the deposit budget at the cap, and one past it --
    #
    # MAXD is a pure capacity, like IMEM_D above: a program that fits
    # gets the model's answer, and one that asks for a slot more is
    # refused at the header before a byte is computed. This bench had
    # never held the KERNEL's value - the unit bench holds cft_seq's
    # default, 64 - and revision 7 moved it to 1,024 on the U50. At the
    # cap the window is n * SEQ_MAXD elements and the drain writes every
    # one, +0 where a lane never reached, so this is also the widest
    # window a program can ask the tile for.
    pcap = seq.Program(FP32, [
        seq.deposit(0),
        seq.alu(OP_MUL, rd=3, ra=0, rb=1),
        seq.deposit(3),
        seq.halt()], max_deposits=SEQ_MAXD)
    n_cap = 8
    await run_prog(dut, axil, ram, pcap,
                   gen_stream(FP32, n_cap, rng), gen_stream(FP32, n_cap, rng),
                   gen_stream(FP32, n_cap, rng),
                   f"fp32 max_deposits == MAXD ({SEQ_MAXD})",
                   tries=3000 + 2 * n_cap * SEQ_MAXD // 10)
    over = bytearray(pcap.to_bytes())
    over[16:20] = (SEQ_MAXD + 1).to_bytes(4, "little")
    flags_now = await axil.read_dword(FLAGS)
    await run_refused(dut, axil, ram, bytes(over), pcap,
                      gen_stream(FP32, n_cap, rng),
                      gen_stream(FP32, n_cap, rng),
                      gen_stream(FP32, n_cap, rng), n_cap, PREC_CODE["fp32"],
                      f"max_deposits {SEQ_MAXD + 1} exceeds MAXD", flags_now)

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

    # ---- revision 3 R4/R5: the scratch, and its per-run block --------
    #
    # What only a full-kernel bench can say about this feature is that
    # the two new CSRs reach cft_seq and that the scratch-out block
    # comes back through m_axi_d - the write master - rather than
    # through the master the preload arrives on. The unit bench
    # (tb/test_seq_core.py) owns the semantics; this owns the plumbing.
    n_s = 24
    pscr = seq.Program(FP32, [
        seq.stl(0, 0),                       # slot 0 := a
        seq.stl(1, SEQ_SCRATCH_D - 1,        # ...and b at the top slot
                SEQ_SCRATCH_D),
        seq.ldl(20, SEQ_SCRATCH_D - 1, SEQ_SCRATCH_D),
        seq.deposit(20),
        seq.stx(20, 2),                      # scratch[c mod D] := b
        seq.ldx(21, 2),
        seq.deposit(21),
        seq.halt()], max_deposits=2, scratch_depth=SEQ_SCRATCH_D)
    # One block, and it indexes, so it may wipe the whole scratch.
    await run_prog(dut, axil, ram, pscr,
                   gen_stream(FP32, n_s, rng), gen_stream(FP32, n_s, rng),
                   [i * 5 + SEQ_SCRATCH_D * (i % 3) for i in range(n_s)],
                   f"fp32 STL/LDL/STX/LDX, top slot {SEQ_SCRATCH_D - 1}",
                   tries=3000 + WIPE_TRIES)

    # ---- revision 7: an index past 256, where the tile's depth decides -
    #
    # The case above builds its indices from the tile's own depth, so
    # they land on the same slots whatever that depth is. These do not:
    # 5 + 256 * (i % 4) is slot 5 four times over on a 256-slot tile and
    # four different slots on a deeper one. A lane whose index lands on
    # 5 reads a and leaves b there (a, b); any other reads an untouched
    # slot and stores b in it (+0, a). Plain, the index reduces modulo
    # the depth; strict, one past the depth is reported, suppressed and
    # reads +0. The model runs at SEQ_SCRATCH_D, so the U50's kernel
    # (2,048) and the open-core configurations (256, boardseq) are each
    # held to their own machine - and a bench that ran its model at 256
    # against a 2,048-slot tile would fail here, on lanes 1..3 of each 4.
    for flags, tag in ((0, "plain"), (seq.FLAG_SCRATCH_STRICT, "strict")):
        pdeep = seq.Program(FP32, [
            seq.stl(0, 5, SEQ_SCRATCH_D),    # slot 5 := a
            seq.ldx(4, 2),                   # r4 := scratch[c]
            seq.deposit(4),
            seq.stx(1, 2),                   # scratch[c] := b
            seq.ldl(5, 5, SEQ_SCRATCH_D),    # r5 := slot 5
            seq.deposit(5),
            seq.halt()], max_deposits=2, flags=flags,
            scratch_depth=SEQ_SCRATCH_D)
        n_d = 16
        await run_prog(dut, axil, ram, pdeep,
                       gen_stream(FP32, n_d, rng, tame=True),
                       gen_stream(FP32, n_d, rng, tame=True),
                       [5 + 256 * (i % 4) for i in range(n_d)],
                       f"fp32 an index past 256, {tag}, at "
                       f"{SEQ_SCRATCH_D} slots",
                       tries=3000 + WIPE_TRIES)

    # The block, in and out, through SCRATCH_IN_PTR and
    # SCRATCH_OUT_PTR. run_prog reads the scratch-out region back the
    # way a host does and compares it to the model element for element,
    # and asserts the guard band past it is untouched.
    pio = seq.Program(FP32, [
        seq.ldl(3, 0), seq.ldl(4, 1),
        seq.alu(OP_ADD, rd=5, ra=3, rc=4),
        seq.stl(5, 2),
        seq.deposit(5),
        seq.halt()], max_deposits=1,
        flags=seq.FLAG_SCRATCH_IO, n_scratch_in=2, n_scratch_out=3)
    assert pio.to_bytes()[28:32] == (2 | (3 << 16)).to_bytes(4, "little"), \
        "the header's second word must carry the two counts, packed"
    sin = gen_stream(FP32, 2 * n_s, rng, tame=True)
    await run_prog(dut, axil, ram, pio,
                   gen_stream(FP32, n_s, rng), gen_stream(FP32, n_s, rng),
                   gen_stream(FP32, n_s, rng),
                   "fp32 scratch in 2, out 3", scratch_in=sin)

    # ...and the wide rung, where an element is a whole beat and the
    # preload's transpose is a different problem: at fp256 one lane
    # owns every word of a beat, at fp32 eight lanes share one.
    pio256 = seq.Program(FP256, [
        seq.ldl(3, 0),
        seq.alu(OP_MUL, rd=4, ra=3, rb=3),
        seq.stl(4, 1),
        seq.deposit(4),
        seq.halt()], max_deposits=1,
        flags=seq.FLAG_SCRATCH_IO, n_scratch_in=1, n_scratch_out=2)
    n_s256 = 3
    await run_prog(dut, axil, ram, pio256,
                   gen_stream(FP256, n_s256, rng, tame=True),
                   gen_stream(FP256, n_s256, rng, tame=True),
                   gen_stream(FP256, n_s256, rng),
                   "fp256 scratch in 1, out 2",
                   scratch_in=gen_stream(FP256, n_s256, rng, tame=True))

    # A run RESUMED through the two pointers: the second call's
    # deposits must equal the second half of a single call's, which is
    # the ask R5 answers and the one thing a single run cannot show.
    body = [seq.ldl(3, 0),
            seq.alu(OP_ADD, rd=3, ra=3, rc=0, kc=True),
            seq.stl(3, 0), seq.deposit(3)]

    def resumable(trips, maxdep):
        return seq.Program(FP32, [seq.repeat(trips)] + body
                           + [seq.endrep(), seq.halt()],
                           consts=[one_bits(FP32)], max_deposits=maxdep,
                           flags=seq.FLAG_SCRATCH_IO,
                           n_scratch_in=1, n_scratch_out=1)

    n_r = 16
    va_r = gen_stream(FP32, n_r, rng)
    vb_r = gen_stream(FP32, n_r, rng)
    vc_r = gen_stream(FP32, n_r, rng)
    zeros = [zero_bits(FP32)] * n_r
    whole = await run_prog(dut, axil, ram, resumable(4, 4),
                           va_r, vb_r, vc_r, "fp32 four trips in one call",
                           scratch_in=zeros)
    half = await run_prog(dut, axil, ram, resumable(2, 2),
                          va_r, vb_r, vc_r, "fp32 two trips, state out",
                          scratch_in=zeros)
    # The state really came back OUT of the tile's buffer: read it from
    # the RAM rather than from the model, so the round trip goes
    # through memory the way a host's would.
    carried = [int.from_bytes(ram.read(SOUT_BASE + i * 4, 4), "little")
               for i in range(n_r)]
    assert carried == half.scratch_out, \
        "the scratch-out buffer does not hold what the model says it does"
    rest = await run_prog(dut, axil, ram, resumable(2, 2),
                          va_r, vb_r, vc_r, "fp32 ...and two more, state in",
                          scratch_in=carried)
    for i in range(n_r):
        assert rest.deposits[i * 2:(i + 1) * 2] == \
            whole.deposits[i * 4 + 2:(i + 1) * 4], (
                f"lane {i}: the resumed half does not equal the second "
                f"half of a single run - the state did not survive the "
                f"round trip through SCRATCH_OUT_PTR and SCRATCH_IN_PTR")

    # The header refusals R5 adds, and the positive control that stops
    # "refuse everything" from passing them.
    io_flag = seq.FLAG_SCRATCH_IO
    flags_before = await axil.read_dword(FLAGS)
    for word, why in (
            ((SEQ_SCRATCH_D + 1), "n_scratch_in past the depth"),
            ((SEQ_SCRATCH_D + 1) << 16, "n_scratch_out past the depth")):
        bad = bytearray(p32.to_bytes())
        bad[24] |= io_flag
        bad[28:32] = word.to_bytes(4, "little")
        await run_refused(dut, axil, ram, bytes(bad), p32,
                          gen_stream(FP32, 8, rng), gen_stream(FP32, 8, rng),
                          gen_stream(FP32, 8, rng), 8, PREC_CODE["fp32"],
                          f"header {why}", flags_before)
    # SCRATCH_D exactly is the largest legal count, which is what says
    # the comparison is a `>` and not a `>=`.
    pmax = seq.Program(FP32, [seq.ldl(3, SEQ_SCRATCH_D - 1, SEQ_SCRATCH_D),
                              seq.deposit(3), seq.halt()],
                       max_deposits=1, flags=io_flag,
                       n_scratch_in=SEQ_SCRATCH_D,
                       n_scratch_out=SEQ_SCRATCH_D,
                       scratch_depth=SEQ_SCRATCH_D)
    n_max = 4
    # At most the whole scratch wiped, then n_max * SCRATCH_D elements
    # preloaded and as many drained, each one a cycle.
    await run_prog(dut, axil, ram, pmax,
                   gen_stream(FP32, n_max, rng), gen_stream(FP32, n_max, rng),
                   gen_stream(FP32, n_max, rng),
                   f"fp32 scratch in and out at exactly {SEQ_SCRATCH_D}",
                   scratch_in=gen_stream(FP32, n_max * SEQ_SCRATCH_D, rng),
                   tries=3000 + WIPE_TRIES + 2 * n_max * SEQ_SCRATCH_D // 10)

    # ---- revision 3 R7: a constant at index 511 through kx -----------
    #
    # The whole 512-entry bank, addressed through the ninth index bit
    # on all three operand ports - imm[28], imm[29], imm[30] for ka, kb
    # and kc - so a decode that wired one of the three to the wrong
    # operand gets two right and one wrong.
    deep = [((i * 0x0101_0101) ^ (i << 3) ^ 0x11) & 0xFFFF_FFFF
            for i in range(512)]
    pdeep = seq.Program(FP32, [
        # kc's ninth bit is imm[30], kb's imm[29], ka's imm[28] - one
        # port each, so a decode that crossed two of them gets one
        # answer right and one wrong rather than all three wrong.
        seq.alu(OP_ADD, 6, ra=0, rc=511, kc=True, kx=True),
        seq.deposit(6),
        seq.alu(OP_MUL, 7, ra=0, rb=300, kb=True, kx=True),
        seq.deposit(7),
        seq.alu(OP_CMPLT, 8, ra=256, rb=1, ka=True, kx=True),
        seq.deposit(8),
        seq.halt()], consts=deep, max_deposits=3)
    n_k = 12
    await run_prog(dut, axil, ram, pdeep,
                   gen_stream(FP32, n_k, rng), gen_stream(FP32, n_k, rng),
                   gen_stream(FP32, n_k, rng),
                   "fp32 kx9: constants 256, 300 and 511")

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

    # ---- ABI 0.14, R16: an input block through its index table -------
    #
    # The whole kernel this time: the CSR decodes MODE[22:19], the
    # pointers arrive through the register map, and the reads go out on
    # the master hw/kernel.xml binds each argument to. What the unit
    # bench proves about the gather's addresses, this proves about the
    # path a host actually drives.
    assert (await axil.read_dword(CAPS2)) & CAPS2_INDEXED, (
        "CAPS2[9] must be set on a build whose cft_seq gathers - a host "
        "asks this register before it sets a MODE bit, and the "
        "alternative is guessing from VERSION")
    rng_ix = random.Random(0x1D60)
    for fmt in (FP32, FP64, FP256):
        pg = prog_two_deposits(fmt)
        n_ix = 40 if fmt is FP32 else (20 if fmt is FP64 else 9)
        src = gen_stream(fmt, 31, rng_ix, tame=True)
        dense_b = gen_stream(fmt, n_ix, rng_ix, tame=True)
        dense_c = gen_stream(fmt, n_ix, rng_ix, tame=True)
        table = [rng_ix.randrange(len(src)) for _ in range(n_ix)]
        for k in range(0, n_ix, 4):
            table[k] = seq.IDX_NONE
        await run_prog(dut, axil, ram, pg, src, dense_b, dense_c,
                       f"{fmt.name} gathered a from a {len(src)}-element "
                       f"source", idx=(table, None, None, None), n=n_ix)
    # ...and an identity table is the dense run, through the same path.
    pg32 = prog_two_deposits(FP32)
    n_id = 24
    a_id = gen_stream(FP32, n_id, rng_ix, tame=True)
    b_id = gen_stream(FP32, n_id, rng_ix, tame=True)
    c_id = gen_stream(FP32, n_id, rng_ix, tame=True)
    await run_prog(dut, axil, ram, pg32, a_id, b_id, c_id,
                   "fp32 identity table through the CSR",
                   idx=(list(range(n_id)), None, None, None), n=n_id)
    dense_dep = ram.read(D_BASE, n_id * pg32.max_deposits * 4)
    await run_prog(dut, axil, ram, pg32, a_id, b_id, c_id,
                   "fp32 the same run, dense")
    assert ram.read(D_BASE, n_id * pg32.max_deposits * 4) == dense_dep, (
        "an identity table must be bit-identical to the dense run, and "
        "both of these came off the tile")

    # ---- the guard is still armed on the bits above ours --------------
    #
    # MODE[24] is revision 8's R23 bit since its seam (2026-10-02): the
    # per-lane flag block, honoured only where CAPS2[13] is set, and the
    # seam sets it on no build - so it must be REFUSED here exactly as it
    # was while it was reserved. MODE[25] is now the bottom of what is
    # left of the reserved range and MODE[31] its top: both must be
    # REFUSED with STATUS[3] and no memory touched, which is what says
    # that opening [22:19], [23] and [24] did not open the window above
    # them.
    if (await axil.read_dword(CAPS2)) & CAPS2_LANE_FLAGS:
        # R23 is built (revision 8's round 2): MODE[24] is honoured, and
        # the block's own case is krnl_lane_flags.
        flags_before = await axil.read_dword(FLAGS)
    else:
        flags_before = await axil.read_dword(FLAGS)
        await run_refused_mode(dut, axil, ram, pg32, a_id, b_id, c_id, n_id,
                               MODE_LANE_FLAGS, "MODE[24], R23's lane-flags "
                               "block, on a build whose CAPS2[13] is clear",
                               flags_before)
    await run_refused_mode(dut, axil, ram, pg32, a_id, b_id, c_id, n_id,
                           1 << 25, "MODE[25], reserved on every build",
                           flags_before)
    await run_refused_mode(dut, axil, ram, pg32, a_id, b_id, c_id, n_id,
                           1 << 31, "MODE[31], reserved on every build",
                           flags_before)
    # ...and MODE[22] on an image that declares NO SCRATCH INPUT. The
    # bit is honoured by this build, so the CSR lets it through: what
    # refuses it is the sequencer's header check, because the table
    # indexes a block this image does not have and a MODE bit a run
    # cannot honour is refused rather than ignored. The pointer is a
    # REAL staged table, so the refusal is about the image and not
    # about a poisoned address.
    assert not pg32.scratch_io,         "this case needs a program that declares no scratch I/O"
    await run_refused_mode(dut, axil, ram, pg32, a_id, b_id, c_id, n_id,
                           0, "MODE[22] with no scratch block to gather "
                           "into", flags_before,
                           idx=(None, None, None, list(range(n_id))))
    # ...and the term's OTHER half (V1, 2026-09-15): SCRATCH_IO set
    # with NO input slot and one output slot - the image an assembler
    # emits for a program that only WRITES the block. A different
    # header state from the case above (flags[1] set, scratch_io[15:0]
    # zero), refused the same way, because the table would index a
    # block of zero slots. The tile refused it before this case
    # existed; the case is here so that half of the OR has a gate.
    pwo = seq.Program(FP32, [
        seq.alu(OP_ADD, rd=5, ra=0, rc=1),
        seq.stl(5, 0),
        seq.deposit(5),
        seq.halt()], max_deposits=1,
        flags=seq.FLAG_SCRATCH_IO, n_scratch_in=0, n_scratch_out=1)
    assert pwo.scratch_io and pwo.n_scratch_in == 0 and pwo.n_scratch_out, \
        "this case needs SCRATCH_IO set with no input slot and an output slot"
    await run_refused_mode(dut, axil, ram, pwo, a_id, b_id, c_id, n_id,
                           0, "MODE[22] with SCRATCH_IO set and no input "
                           "slot to gather into", flags_before,
                           idx=(None, None, None, list(range(n_id))))

    # ---- and elementwise still works after all of it ------------------
    await run_op(dut, axil, ram, FP32, OP_MUL, 24, seed=903, bases=EW_BASES)
    dut._log.info(f"sequencer bench complete "
                  f"(loop run raised flags {flags_loop:#07b})")


@cocotb.test()
async def krnl_flag_control(dut):
    """Revision 8's R24 through the kernel: CAPS2[14] published, a quiet
    region silencing an instruction's flags and a raise's, a raise outside
    it standing, and the mark - [7] of the raised word, every fourth lane -
    reaching STATUS[6] through cft_krnl's eng_err[6] and the CSR, as the
    model's status says (run_prog compares FLAGS and STATUS whole). Then a
    run with no mark reads STATUS 0 (the mark is the run's, cleared at
    start), and a refusal after a marked run reads exactly STATUS[3]: the
    kernel masks the mark with the other run reports while a refusal is
    the last start."""
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n,
                         reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n,
                       reset_active_level=False, size=2 ** 21)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"), dut.ap_clk,
                dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
                mem=ram_a.mem)
    ram = ram_a
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert (await axil.read_dword(CAPS2)) & CAPS2_FLAG_CONTROL, (
        "this build's CAPS2[14] is clear, so flag control would be refused "
        "by the host and decoded as HALT here")
    n = 40
    rng = random.Random(0x24)
    a = gen_stream(FP32, n, rng)
    b = gen_stream(FP32, n, rng)
    # The raised words: [4:0] random, [7] every fourth lane, the rest
    # random too (read by nothing).
    words = [(rng.getrandbits(32) & ~0x80) | (0x80 if i % 4 == 0 else 0)
             for i in range(n)]
    loud = seq.alu(OP_MUL, 5, ra=0, rb=1)
    prog = seq.Program(FP32, [
        seq.quiet(), loud, seq.raise_(2), seq.endquiet(),
        seq.alu(OP_ADD, 6, ra=0, rc=1), seq.raise_(2),
        seq.deposit(5), seq.deposit(6), seq.halt()], max_deposits=2)
    res = await run_prog(dut, axil, ram, prog, a, b, words,
                         "fp32 quiet region, raises in and out, marks")
    assert res.status & seq.STATUS_MARKED, "the model marked no lane"
    # ...a run with no mark: the mark is the run's
    unmarked = [w & ~0x80 for w in words]
    res = await run_prog(dut, axil, ram, prog, a, b, unmarked,
                         "fp32 the same with no mark")
    assert not res.status & seq.STATUS_MARKED
    # ...a marked run, then a refusal: exactly STATUS[3]
    await run_prog(dut, axil, ram, prog, a, b, words,
                   "fp32 marked, before a refusal")
    flags_now = await axil.read_dword(FLAGS)
    bad = bytearray(prog.to_bytes())
    bad[0] ^= 0xFF                       # the magic
    await run_refused(dut, axil, ram, bytes(bad), prog, a, b, words, n,
                      PREC_CODE["fp32"], "a refusal after a marked run",
                      flags_now)


@cocotb.test()
async def krnl_augadd(dut):
    """Revision 8's R21 through the kernel, on the array the elementwise
    engine shares, either way the build has it.

    With R21 (CAPS2[11], EN_AUGADD=1, the single and the deep build):
    augadd and augerr, both orders, over every family of the plan's list
    (test_seq_core's r21_pairs) at fp32 and fp256, bit-exact against the
    model with each lane's byte; then an elementwise ADD straight after a
    run whose last array request was an augerr - the sequencer's sideband
    register still holds augerr's code, and the kernel hands the array the
    sequencer's sideband in a sequencer run only (the plan's plant "the
    sideband left live in the engine" is red here).

    Without it (CAPS2[11] clear, EN_AUGADD=0 - the quad's tile, built
    without R21 because probe L measured R21's lanes at +10,595 LUTs a
    tile and Logan's answer to the plan's question 9 was "Only if probe L
    finds it cheap"): CAPS and CAPS2 at the plan's words for that tile; an
    augadd image and an augerr image each ending its block where the code
    stands, as an unknown code does on revision 7 (HALT, the determinism
    contract's rule for an unassigned code); and an R21-free program
    bit-exact."""
    from test_seq_core import r21_pairs, R21_FAMILIES
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n,
                         reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n,
                       reset_active_level=False, size=2 ** 21)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"), dut.ap_clk,
                dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
                mem=ram_a.mem)
    ram = ram_a
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    caps = await axil.read_dword(CAPS)
    caps2 = await axil.read_dword(CAPS2)
    check_caps2(caps2)
    check_seam_words(caps, caps2, PREC_MASK)
    built = bool(caps2 & CAPS2_AUGADD)
    assert built == bool(krnl_param_bit("EN_AUGADD")), (
        f"CAPS2[11] is {int(built)} on a build with EN_AUGADD="
        f"{krnl_param_bit('EN_AUGADD')}")
    rng = random.Random(0x21)

    if built:
        for fmt, n in ((FP32, 72), (FP256, 21)):
            pairs, fams = r21_pairs(fmt, n, 0x2101)
            assert all(fams[f] for f in R21_FAMILIES), (fmt.name, fams)
            a = [x for x, _ in pairs]
            b = [y for _, y in pairs]
            prog = seq.Program(fmt, [
                seq.augerr(3, 0, 1), seq.augadd(4, 0, 1),
                seq.augerr(5, 1, 0), seq.augadd(6, 1, 0),
                seq.deposit(3), seq.deposit(4), seq.deposit(5),
                seq.deposit(6), seq.halt()], max_deposits=4)
            await run_prog(dut, axil, ram, prog, a, b, [0] * n,
                           f"{fmt.name} augadd and augerr, every family",
                           lane_flags=True)
        # The sideband after the run: the last request this program makes
        # of the array is an augerr's, so the sequencer's register holds 2
        # when the elementwise run starts.
        n = 32
        a = gen_stream(FP32, n, rng)
        b = gen_stream(FP32, n, rng)
        prog = seq.Program(FP32, [
            seq.augadd(3, 0, 1), seq.augerr(4, 0, 1),
            seq.deposit(3), seq.deposit(4), seq.halt()], max_deposits=2)
        await run_prog(dut, axil, ram, prog, a, b, [0] * n,
                       "fp32 a run ending on an augerr")
        await run_op(dut, axil, ram, FP32, OP_ADD, n, seed=0x2102,
                     bases=EW_BASES)
        return

    # The quad's tile: the two codes are unknown ones.
    for fmt, n in ((FP32, 40), (FP256, 9)):
        a = gen_stream(fmt, n, rng)
        b = gen_stream(fmt, n, rng)
        c = gen_stream(fmt, n, rng)
        head = [seq.alu(OP_MUL, 3, ra=0, rb=1), seq.deposit(3)]
        tail = [seq.deposit(4), seq.halt()]
        for code in (seq.augadd(4, 0, 1), seq.augerr(4, 0, 1)):
            name = seq.CTRL_NAMES[seq.decode(code)["op"]]
            image = seq.Program(fmt, head + [code] + tail, max_deposits=2)
            model = seq.Program(fmt, head + [seq.halt()] + tail,
                                max_deposits=2)
            await run_prog(dut, axil, ram, model, a, b, c,
                           f"{fmt.name} {name} without R21 ends the block",
                           image=image.to_bytes(), lane_flags=True)
        prog = seq.Program(fmt, [
            seq.alu(OP_FMA, 3, ra=0, rb=1, rc=2),
            seq.alu(OP_MUL, 4, ra=3, rb=3),
            seq.deposit(3), seq.deposit(4), seq.halt()], max_deposits=2)
        await run_prog(dut, axil, ram, prog, a, b, c,
                       f"{fmt.name} an R21-free program on the quad's tile",
                       lane_flags=True)


@cocotb.test()
async def krnl_scratch_step(dut):
    """Revision 8's R22 through the kernel, on the array the elementwise
    engine shares: a stepped STX fires its IADD into that array at its own
    F, and a stepped LDX's internal IADD follows it as an instruction of
    its own. A walk up by stores and down by loads, with lanes that wrap
    through 0 and cross zero downward, `ldx rX, rX` keeping its load, and
    the index deposited, at fp32 and fp64 (a negative step's high word),
    against the model."""
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n,
                         reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n,
                       reset_active_level=False, size=2 ** 21)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"), dut.ap_clk,
                dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
                mem=ram_a.mem)
    ram = ram_a
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert (await axil.read_dword(CAPS2)) & CAPS2_SCRATCH_STEP, (
        "this build's CAPS2[12] is clear, so a stepped STX or LDX would be "
        "refused by the loader")
    rng = random.Random(0x22)
    for fmt, n in ((FP32, 40), (FP64, 13)):
        top = (1 << fmt.width) - 2
        idx = [top if i % 5 == 1 else 1 if i % 5 == 2 else 40 + rng.randrange(200)
               for i in range(n)]
        a = gen_stream(fmt, n, rng)
        c = gen_stream(fmt, n, rng)
        prog = seq.Program(fmt, [
            seq.repeat(3), seq.stx(0, 1, 1), seq.endrep(),
            seq.repeat(3), seq.ldx(4, 1, -1), seq.deposit(4), seq.endrep(),
            seq.ldx(1, 1, 5),        # rd is rb: the load wins, no step
            seq.deposit(1),
            seq.halt()], max_deposits=4)
        await run_prog(dut, axil, ram, prog, a, idx, c,
                       f"{fmt.name} a stepped walk through the kernel",
                       lane_flags=True)


@cocotb.test()
async def krnl_lane_flags(dut):
    """Revision 8's R23 through the kernel: CAPS2[13] published, MODE[24]
    honoured, and the block written at the address the register at 0xB0
    holds - verifier-VRA's note on the seam, whose bus leg held a distinct
    register at each argument's offset and not that 0xB0 drives the pointer
    cft_seq reads. Every lane's byte against the model, masked and not,
    over two blocks and a ragged third; and a run without MODE[24] leaves
    the region untouched."""
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n,
                         reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n,
                       reset_active_level=False, size=2 ** 21)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"), dut.ap_clk,
                dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
                mem=ram_a.mem)
    ram = ram_a
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert (await axil.read_dword(CAPS2)) & CAPS2_LANE_FLAGS, (
        "this build's CAPS2[13] is clear, so MODE[24] would be refused")
    rng = random.Random(0x23)
    for fmt in (FP32, FP256):
        n = 2 * 16 * (256 // fmt.width) + 5
        a = gen_stream(fmt, n, rng)
        b = gen_stream(fmt, n, rng)
        words = [(rng.getrandbits(fmt.width) & ~0x80) |
                 (0x80 if i % 4 == 0 else 0) for i in range(n)]
        prog = seq.Program(fmt, [
            seq.alu(OP_MUL, 3, ra=0, rb=1),
            seq.quiet(), seq.raise_(2), seq.endquiet(),
            seq.deposit(3), seq.setact(1), seq.deposit(3),
            seq.raise_(2), seq.halt()], max_deposits=1)
        await run_prog(dut, axil, ram, prog, a, b, words,
                       f"{fmt.name} the lane-flag block through the kernel",
                       lane_flags=True)
        keep = [i % 3 != 1 for i in range(n)]
        await run_prog(dut, axil, ram, prog, a, b, words,
                       f"{fmt.name} the lane-flag block under a mask",
                       lane_flags=True, mask=keep)
        ram.write(LF_BASE, bytes([POISON]) * (n + GUARD))
        await run_prog(dut, axil, ram, prog, a, b, words,
                       f"{fmt.name} no MODE[24]")
        assert ram.read(LF_BASE, n + GUARD) == bytes([POISON]) * (n + GUARD), (
            f"{fmt.name}: a run without MODE[24] wrote the lane-flag region")


@cocotb.test()
async def krnl_lane_mask(dut):
    """ABI 0.14's lane mask (docs/SEQUENCER.md R17) through the CSR, on
    the tile whose ALU array is SHARED with the elementwise engine.

    Its own test rather than more cases inside `krnl_sequencer`: R17 is
    one feature with one setup, and a reset between it and everything
    else is worth having when what it asserts is that a masked lane's
    flag does not reach the run after it.
    """
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n,
                         reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n,
                       reset_active_level=False, size=2 ** 21)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"), dut.ap_clk,
                dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
                mem=ram_a.mem)
    ram = ram_a

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    pg32 = prog_two_deposits(FP32)
    # ---- the lane mask through the CSR (R17) --------------------------
    #
    # MODE[23] with MASK_PTR, on the shared array: the same program
    # run masked and dense, with the masked lanes' slots left poison.
    # This is the path the software backend's CAPS2[10] refusal exists
    # to protect, and the only one where the mask, the CSR and the
    # shared array are all in play at once.
    assert (await axil.read_dword(CAPS2)) & CAPS2_LANE_MASK, (
        "this build's CAPS2[10] is clear, so the lane mask below would "
        "be refused rather than honoured")
    n_mk = 96
    rng_mk = random.Random(0x17A7)
    a_mk = gen_stream(FP32, n_mk, rng_mk, tame=True)
    b_mk = gen_stream(FP32, n_mk, rng_mk, tame=True)
    c_mk = gen_stream(FP32, n_mk, rng_mk, tame=True)
    keep_mk = [i % 3 != 0 for i in range(n_mk)]
    await run_prog(dut, axil, ram, pg32, a_mk, b_mk, c_mk,
                   "fp32 a lane mask through the CSR", mask=keep_mk)
    masked_dep = ram.read(D_BASE, n_mk * pg32.max_deposits * 4)
    await run_prog(dut, axil, ram, pg32, a_mk, b_mk, c_mk,
                   "fp32 the same run, all lanes", mask=[True] * n_mk)
    ones_dep = ram.read(D_BASE, n_mk * pg32.max_deposits * 4)
    await run_prog(dut, axil, ram, pg32, a_mk, b_mk, c_mk,
                   "fp32 the same run, no mask at all")
    dense_dep = ram.read(D_BASE, n_mk * pg32.max_deposits * 4)
    assert ones_dep == dense_dep, (
        "an all-ones mask must be bit-identical to no mask, and both of "
        "these came off the tile")
    assert masked_dep != dense_dep, (
        "a mask with holes gave the unmasked run's bits, so the "
        "all-ones half of this control could not have failed")

    # ...and the flags, the two cases the wave-1 ledger asks for on a
    # tile whose ALU array is SHARED with the elementwise engine. The
    # first: the only lane that would signal is masked. The second: a
    # run in which lane k overflowed, then a masked run with lane k
    # masked and nothing else able to signal - whose FLAGS must be
    # clear, which is a claim about the sticky word and the array
    # between two runs and not about either run alone.
    loud_a = [one_bits(FP32)] * n_mk
    loud_b = [one_bits(FP32)] * n_mk
    k_mk = 41
    loud_b[k_mk] = max_normal_bits(FP32)
    loud_a[k_mk] = max_normal_bits(FP32)
    pg_mul = seq.Program(FP32, [seq.alu(OP_MUL, rd=3, ra=0, rb=1),
                                seq.deposit(3), seq.halt()],
                         max_deposits=1)
    res_loud = await run_prog(dut, axil, ram, pg_mul, loud_a, loud_b,
                              loud_b, "fp32 lane k overflows, unmasked")
    assert res_loud.flags, \
        "lane k did not overflow, so the masked run below proves nothing"
    await run_prog(dut, axil, ram, pg_mul, loud_a, loud_b, loud_b,
                   "fp32 lane k masked, after the run it was loud in",
                   mask=[i != k_mk for i in range(n_mk)])
    assert (await axil.read_dword(FLAGS)) == 0, (
        "a masked lane's flag reached the run after it - the sticky "
        "word or the array's lane flags outlived the run that raised "
        "them")

    dut._log.info("lane mask through the CSR: masked == model, all-ones "
                  "== dense, holed != dense, and a masked lane's flag "
                  "does not reach the run after it")


# ---- revision 7, R18: the real programs ---------------------------------
#
# The three ODE segment programs programs/gen_odes.py writes, assembled
# from their committed sources and run with their committed banks,
# through the kernel - here and not in the unit bench because Lorenz-96
# is 1,500 instructions and the unit bench's cft_seq holds 1,024. They
# are the census's programs (docs/VALIDATION.md, steps 0 and 1a): a
# Lorenz-96 step is 760 ALU instructions and 692 scratch accesses, the
# pattern R18 exists for - a store of what the instruction before it
# computed, a load used by the instruction after it. The segment's trip
# count is cut (the loop body is the program's own) so that a run
# finishes in seconds, and each run is TIMED, start to done, so the same
# case is the before-side on an older tile and the after-side on this
# one.

PROGRAMS = Path(__file__).resolve().parents[1] / "programs"


def _ode_case(name, steps):
    """(Program with its segment cut to `steps` trips, bank values)."""
    from cft_golden import asm
    img = asm.assemble_image((PROGRAMS / f"{name}.cfta").read_text(),
                             f"{name}.cfta")
    prog = seq.Program.from_bytes(img.to_bytes())
    for i, w in enumerate(prog.insns):
        d = seq.decode(w)
        if d["ctrl"] and d["op"] == seq.REPEAT:
            prog.insns[i] = seq.repeat(steps)
            break
    else:
        raise AssertionError(f"{name}: no segment loop to cut")
    raw = (PROGRAMS / f"{name}.classic.bank").read_bytes()
    e = prog.fmt.width // 8
    bank = [int.from_bytes(raw[i:i + e], "little")
            for i in range(0, len(raw), e)]
    return prog, bank


def _ode_start(name, fmt, n, nstate):
    """A small ensemble near each system's usual start, every member
    displaced by an exact dyadic amount: lane-major, nstate a lane."""
    from cft_golden import chars, RND_RNE

    def d(text):
        return chars.from_decimal(fmt, text, RND_RNE)[0]
    out = []
    for i in range(n):
        if name.startswith("lorenz63"):
            out += [d(repr(1 + i / 64)), d("1"), d("1")]
        elif name.startswith("lorenz96"):
            out += [d(repr(8 + (i + 1) / 1024))] + [d("8")] * (nstate - 1)
        else:
            out += [d("0"), d(repr(0.1 + i / 1024)), d("0.5"), d("0")]
    assert len(out) == n * nstate
    return out


@cocotb.test()
async def krnl_ode_programs(dut):
    """The ODE programs against the model through the whole kernel, at a
    full block and a short ragged one, fp64 and fp256; each timed."""
    from cocotb.utils import get_sim_time
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n,
                         reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n,
                       reset_active_level=False, size=2 ** 21)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"), dut.ap_clk,
               dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
               mem=ram_a.mem)
    AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"), dut.ap_clk,
                dut.ap_rst_n, reset_active_level=False, size=2 ** 21,
                mem=ram_a.mem)
    ram = ram_a
    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    for name, steps, ns in (
            ("lorenz63-rk4-fp64", 10, (64, 5)),
            ("henonheiles-lf-fp64", 10, (64, 5)),
            ("lorenz96-rk4-fp64", 2, (64, 5)),
            ("lorenz63-rk4-fp256", 4, (16, 3)),
            ("henonheiles-lf-fp256", 4, (16, 3)),
            ("lorenz96-rk4-fp256", 1, (16, 3))):
        prog, bank = _ode_case(name, steps)
        fmt = prog.fmt
        for n in ns:
            s_in = _ode_start(name, fmt, n, prog.n_scratch_in)
            zeros = [0] * n
            t0 = get_sim_time("ns")
            res = await run_prog(dut, axil, ram, prog, zeros, zeros, zeros,
                                 f"{name} x{steps} n={n}", bank=bank,
                                 scratch_in=s_in, tries=200000)
            cyc = (get_sim_time("ns") - t0) / 4
            assert res.scratch_out != s_in, f"{name}: the state did not move"
            dut._log.info(f"{name} x{steps} steps, n={n}: about {cyc:.0f} "
                          f"cycles start to done (the CSR writes included)")
