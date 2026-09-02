# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The quarter-tile: a 64-bit beat carrying fp32 and fp64 only.

Same golden model, same CSR contract, a quarter of the geometry. This
is what proves BEAT_BITS is a working parameter rather than a declared
one - and it is the configuration an Alchitry Au conformance node and
a deposition-buffer-heavy chiplet both want.

Two things it checks that the full-tile bench structurally cannot:

* **CAPS tells the truth about a trimmed build - and the build backs
  it up.** The precision mask must report fp32 and fp64 only, and a
  MODE that selects anything else must be REFUSED: STATUS[3], no
  memory touched, done asserted anyway. Before that gate existed, a
  host that trusted the full tile's 0xF here got a deterministic but
  meaningless beat from banks that do not exist - garbage with clean
  flags, the worst shape a wrong answer can take.
* **The beat arithmetic follows the parameter.** Elements per beat,
  the AXI transfer size, and the byte address step are all derived
  from BEAT_BITS; if any of them stayed at 256 the run would read the
  wrong addresses and mismatch immediately.
"""

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
    FP32, FP64, OP_FMA, OP_ADD, OP_MUL, OP_MIN, OP_ISHR, OP_SELECT,
    RND_RDN, RND_RNE, RND_RUP,
)

from test_krnl import (run_op, check_op_groups,  # noqa: E402
                       CAPS, MAGIC, VERSION, CTRL)
from test_krnl_reduce import run_sum  # noqa: E402
import busfx  # noqa: E402


@cocotb.test()
async def quarter_tile_end_to_end(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    # Four masters, one shared memory - see test_krnl for why the
    # sharing is what makes this bench able to fail.
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    # Bound rather than discarded: the backpressure below has to reach
    # every channel of every master, and a slave nothing holds a
    # reference to is a slave nothing can stall.
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 20, mem=ram_a.mem)
    ram = ram_a

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)

    assert await axil.read_dword(MAGIC) == 0x43465430
    assert await axil.read_dword(VERSION) == 0x00000600

    caps = await axil.read_dword(CAPS)
    assert (caps & 0xF) == 0b0011, (
        f"quarter tile must advertise fp32+fp64 only, got {caps & 0xF:#06b}")
    # Trimming rungs must not trim opcode groups - every group still
    # works on the formats that remain, reductions included.
    check_op_groups(caps)

    status = await axil.read_dword(CTRL)
    assert status & 0x4, "kernel must come up idle"

    # Two fp32 lanes per beat now, and one fp64. Sizes chosen to cross
    # several bursts and to leave a ragged tail.
    await run_op(dut, axil, ram, FP32, OP_FMA, 64, seed=301)
    await run_op(dut, axil, ram, FP32, OP_ADD, 34, seed=302)   # 17 beats
    await run_op(dut, axil, ram, FP32, OP_MUL, 2, seed=303)    # single beat
    await run_op(dut, axil, ram, FP64, OP_FMA, 24, seed=304)
    await run_op(dut, axil, ram, FP64, OP_ADD, 1, seed=305)    # single beat

    # the non-arithmetic groups still work at the narrow geometry
    await run_op(dut, axil, ram, FP32, OP_MIN, 32, seed=306)
    await run_op(dut, axil, ram, FP32, OP_ISHR, 32, seed=307)
    await run_op(dut, axil, ram, FP64, OP_SELECT, 8, seed=308)

    # and so do the rounding attributes
    await run_op(dut, axil, ram, FP32, OP_FMA, 32, seed=309, rnd=RND_RDN)
    await run_op(dut, axil, ram, FP64, OP_FMA, 16, seed=310, rnd=RND_RUP)

    # Reductions, which this bench asserted CAPS for and never ran.
    #
    # That gap had already cost something. The serializer's
    # elements-per-beat was a hardcoded 8/4/2/1 while the beat COUNT
    # was derived from LANE_SH, and the two only agree at
    # BEAT_BITS=256. Here a beat holds 2 fp32, not 8, so the
    # serializer walked four elements off the end of every beat and
    # the remaining-element count underflowed on the second beat -
    # twelve "elements" folded for an n of four. Nothing could see it,
    # because the only bench at this geometry ran no reductions and
    # the only reduction bench ran at 256.
    #
    # The sizes are chosen against that: n=4 is the exact case above,
    # and 1, 3 and 5 are partial final beats at 2 elements per beat.
    # fp64 is 1 element per beat here, so its beats are all full and
    # it isolates the count rather than the serializer.
    await run_sum(dut, axil, ram, FP32, 1, RND_RNE, seed=320)
    await run_sum(dut, axil, ram, FP32, 2, RND_RNE, seed=321)
    await run_sum(dut, axil, ram, FP32, 3, RND_RNE, seed=322)
    await run_sum(dut, axil, ram, FP32, 4, RND_RNE, seed=323)
    await run_sum(dut, axil, ram, FP32, 5, RND_RNE, seed=324)
    await run_sum(dut, axil, ram, FP32, 33, RND_RNE, seed=325)
    await run_sum(dut, axil, ram, FP64, 1, RND_RNE, seed=326)
    await run_sum(dut, axil, ram, FP64, 7, RND_RNE, seed=327)
    await run_sum(dut, axil, ram, FP32, 9, RND_RDN, seed=328)

    # ---- across a 4KB page ------------------------------------------
    #
    # AXI4 forbids a burst from crossing a 4KB boundary, so both the
    # reader and the writer shorten a burst that would. No bench had
    # ever reached a boundary at any geometry: every base here is
    # page-aligned and the largest run was 64 elements, which at 8
    # bytes per beat is 512 bytes into a 4096-byte page.
    #
    # That is where the write path's hardcoded shift hid. It divided
    # the distance-to-boundary by 32 bytes per beat instead of this
    # tile's 8, so near a page end it computed ZERO beats - and a zero
    # target clears w_go permanently, which is a hang rather than a
    # wrong answer: wr_done stops advancing, ap_done never asserts, and
    # the only thing left is the host's timeout.
    #
    # 1100 fp32 is 550 beats, so it crosses one boundary on every
    # stream and on the writer. 600 fp64 is 600 beats and crosses on a
    # different element size, so a shift that is wrong per-format
    # rather than globally still shows.
    await run_op(dut, axil, ram, FP32, OP_FMA, 1100, seed=340)
    await run_op(dut, axil, ram, FP64, OP_ADD, 600, seed=341)

    # And once more with the bus stalling, because the boundary case
    # and the refill case interact: a burst shortened by the boundary
    # is also the burst most likely to be in flight when a FIFO drains.
    busfx.stall(ram_a, ram_b, ram_c, ram_d, seed=7700, duty=0.4)
    await run_op(dut, axil, ram, FP32, OP_FMA, 1100, seed=342)
    busfx.unstall(ram_a, ram_b, ram_c, ram_d)

    # ---- refusal: the trimmed build's answer to a run it cannot do.
    #
    # Drive MODE at the two precisions this build does not carry, at
    # two codes no build carries (4-15 of the field), and - at a
    # precision it DOES carry - with MODE[15] asking for the sequencer,
    # whose program image needs a 256-bit beat and this tile's is 64.
    # Each attempt must complete - ap_done, because a hang costs a card
    # reset - with STATUS[3] set, FLAGS clean, and the D buffer
    # byte-identical to the pattern written before the attempt: nothing
    # started, so nothing may have moved. The accepted run afterwards
    # proves the sticky clears at the next real start (run_op asserts
    # STATUS==0).
    from test_krnl import (MODE, NREG, APTR, BPTR, CPTR, DPTR, FLAGS,
                           STATUS, A_BASE, B_BASE, C_BASE, D_BASE, write64)
    attempts = [(f"prec code {c}", 0 | (c << 8)) for c in (2, 3, 5, 15)]
    attempts.append(("sequencer on a 64-bit beat", (1 << 15) | (0 << 8)))
    for prec_code, mode_word in attempts:
        ram.write(D_BASE, b"\xAA" * 64)
        if mode_word & (1 << 15):
            # A VALID image header at A, not operand data: magic and
            # version sit in the low 64 bits, so on this tile's 64-bit
            # beat they arrive intact while the precision field and all
            # three counts read as zero - and zero counts pass the
            # loader's limits. Without the kernel's refusal that is an
            # ACCEPTED fp32 run of no instructions with clean flags,
            # which is exactly the plausible-looking nothing the refusal
            # exists to prevent; with it, STATUS[3] and nothing read.
            # The negative control (run_ok reverted to prec_ok) turns
            # this attempt's STATUS from 0x8 to 0x0 (2026-09-02).
            ram.write(A_BASE, (0x5054_4643).to_bytes(4, "little")
                              + (1).to_bytes(4, "little") + bytes(56))
        fl_before = await axil.read_dword(FLAGS)
        await axil.write_dword(MODE, mode_word)              # FMA, fp32 for the seq case
        await write64(axil, NREG, 4)
        await write64(axil, APTR, A_BASE)
        await write64(axil, BPTR, B_BASE)
        await write64(axil, CPTR, C_BASE)
        await write64(axil, DPTR, D_BASE)
        await axil.write_dword(CTRL, 1)
        got_done = False
        for _ in range(200):
            await ClockCycles(dut.ap_clk, 5)
            if (await axil.read_dword(CTRL)) & 0x2:
                got_done = True
                break
        assert got_done, (
            f"{prec_code}: a refused run must still complete")
        st = await axil.read_dword(STATUS)
        fl = await axil.read_dword(FLAGS)
        assert st == 0x8, (
            f"{prec_code}: STATUS {st:#x}, want the refusal "
            f"bit alone (0x8)")
        # FLAGS clears at an ACCEPTED start, so a refusal must leave it
        # exactly as it was - a refused run that scrubbed the previous
        # run's flags would be quietly rewriting history.
        assert fl == fl_before, (
            f"{prec_code}: refusal changed FLAGS "
            f"{fl_before:#04x} -> {fl:#04x}")
        assert ram.read(D_BASE, 64) == b"\xAA" * 64, (
            f"{prec_code}: a refused run wrote to memory")
    await run_op(dut, axil, ram, FP32, OP_ADD, 8, seed=343)

    dut._log.info("quarter tile (BEAT_BITS=64, fp32+fp64): bit-exact "
                  "against the same golden model as the full tile, "
                  "elementwise and reductions - and fp128/fp256/"
                  "unassigned MODE codes and a sequencer start "
                  "refused with STATUS[3]")
