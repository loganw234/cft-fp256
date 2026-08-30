# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""What the kernel does when the memory system misbehaves.

Every other bench here attaches a slave that always answers OKAY and
always puts RLAST exactly where AxLEN said. So STATUS - the register
whose entire job is to say "the memory did not vouch for this data" -
had never been non-zero in simulation, and the code paths that set it
had never executed.

Two different behaviours are expected, and the difference is the point:

  * A bad RESPONSE (SLVERR/DECERR) still delivers its beat, so the run
    finishes normally and STATUS is read afterwards. Nothing special
    has to happen.

  * A bad LENGTH does not. A short burst withholds beats that were
    promised, so compute starves and the run never ends - which used
    to mean ap_done never asserted and the host's only recourse was a
    twenty-minute timeout and a poisoned handle. The engine now
    abandons the run instead, and these tests are what pin that.

The tests assert three things per fault, and the third is the one that
matters: the right STATUS bit, a D buffer the host is told not to
trust, and ap_done ACTUALLY ASSERTING - within a bounded number of
cycles rather than eventually.
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
from cocotbext.axi.constants import AxiResp  # noqa: E402

from cft_golden import FP32, OP_FMA, RND_RNE  # noqa: E402

import busfx  # noqa: E402
from test_krnl import (write64, CTRL, MODE, NREG, APTR, BPTR, CPTR,  # noqa: E402
                       DPTR, FLAGS, STATUS, A_BASE, B_BASE, C_BASE, D_BASE)

PREC_FP32 = 0

# STATUS bits, from rtl/cft_csr.sv and docs/ARCHITECTURE.md.
ST_RRESP = 1 << 0      # a read response was not OKAY
ST_BRESP = 1 << 1      # a write response was not OKAY
ST_RLEN = 1 << 2       # a read burst delivered the wrong beat count

# A run must end within this many cycles of being started. Generous -
# 200 beats of work is a few hundred cycles - but FINITE, which is the
# whole assertion. "It finished eventually" is what the old behaviour
# could not promise.
DONE_LIMIT = 20000


async def _bringup(dut):
    cocotb.start_soon(Clock(dut.ap_clk, 4, units="ns").start())
    axil = AxiLiteMaster(AxiLiteBus.from_prefix(dut, "s_axi_control"),
                         dut.ap_clk, dut.ap_rst_n, reset_active_level=False)
    ram_a = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_a"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20)
    ram_b = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_b"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_c = AxiRamRead(AxiReadBus.from_prefix(dut, "m_axi_c"),
                       dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                       size=2 ** 20, mem=ram_a.mem)
    ram_d = AxiRamWrite(AxiWriteBus.from_prefix(dut, "m_axi_d"),
                        dut.ap_clk, dut.ap_rst_n, reset_active_level=False,
                        size=2 ** 20, mem=ram_a.mem)
    for r in (ram_a, ram_b, ram_c, ram_d):
        busfx.instrument(r)

    dut.ap_rst_n.value = 0
    await ClockCycles(dut.ap_clk, 8)
    dut.ap_rst_n.value = 1
    await ClockCycles(dut.ap_clk, 4)
    return axil, ram_a, ram_b, ram_c, ram_d


async def _start_run(dut, axil, ram, n, seed):
    """Stage operands and start one fp32 FMA run. Does not wait."""
    rng = random.Random(seed)
    ebytes = 4
    vals = [rng.getrandbits(31) for _ in range(3 * n)]
    blob = b"".join(v.to_bytes(ebytes, "little") for v in vals)
    ram.write(A_BASE, blob[:n * ebytes])
    ram.write(B_BASE, blob[n * ebytes:2 * n * ebytes])
    ram.write(C_BASE, blob[2 * n * ebytes:])
    ram.write(D_BASE, b"\x5A" * (n * ebytes))

    await axil.write_dword(MODE, (RND_RNE << 12) | (PREC_FP32 << 8) | OP_FMA)
    await write64(axil, NREG, n)
    await write64(axil, APTR, A_BASE)
    await write64(axil, BPTR, B_BASE)
    await write64(axil, CPTR, C_BASE)
    await write64(axil, DPTR, D_BASE)
    await axil.write_dword(CTRL, 1)


async def _await_done(dut, axil, what):
    """ap_done within DONE_LIMIT cycles, or the test fails.

    This is the assertion the whole file exists for. A design that
    latches the fault and then waits forever passes every other check
    in this repository.
    """
    for _ in range(DONE_LIMIT // 20):
        await ClockCycles(dut.ap_clk, 20)
        if (await axil.read_dword(CTRL)) & 0x2:
            return
    raise AssertionError(
        f"{what}: the kernel never asserted ap_done. A memory fault must "
        f"END the run - a latched error in a register nobody can read is "
        f"a hang, and on a card it costs a reset.")


@cocotb.test()
async def read_response_faults_are_reported_and_the_run_completes(dut):
    """SLVERR and DECERR on a read, on each of the three read masters.

    A bad response still carries a beat, so nothing stalls. What has to
    happen is that the engine notices - every read master's verdict
    counts, not just the one that used to be shared - and that STATUS
    says so afterwards.
    """
    axil, ram_a, ram_b, ram_c, ram_d = await _bringup(dut)

    for name, ram in (("a", ram_a), ("b", ram_b), ("c", ram_c)):
        for resp, label in ((AxiResp.SLVERR, "SLVERR"),
                            (AxiResp.DECERR, "DECERR")):
            for r in (ram_a, ram_b, ram_c, ram_d):
                r.fx.reset()
            ram.fx.arm(resp_at=3, resp=resp)

            await _start_run(dut, axil, ram_a, 64, seed=int(resp) * 10)
            await _await_done(dut, axil, f"{label} on stream {name}")

            st = await axil.read_dword(STATUS)
            assert st & ST_RRESP, (
                f"{label} on read stream {name}: STATUS {st:#x} has no "
                f"read-response bit, so a fault on this master is invisible")
            assert not (st & ST_RLEN), (
                f"{label} on stream {name}: STATUS {st:#x} claims a length "
                f"error too - a bad response is not a bad length")
            dut._log.info(f"{label} on stream {name}: STATUS {st:#x}")


@cocotb.test()
async def a_write_response_fault_is_reported(dut):
    """SLVERR on the write response.

    The data left the kernel correctly and the memory refused it, which
    is exactly as fatal as a bad read: the result the host reads back
    is not the result the kernel produced.
    """
    axil, ram_a, ram_b, ram_c, ram_d = await _bringup(dut)
    ram_d.fx.arm(bresp_at=0, resp=AxiResp.SLVERR)

    await _start_run(dut, axil, ram_a, 64, seed=77)
    await _await_done(dut, axil, "BRESP SLVERR")

    st = await axil.read_dword(STATUS)
    assert st & ST_BRESP, (
        f"STATUS {st:#x} has no write-response bit; a memory that refused "
        f"the result would look like a successful run")


@cocotb.test()
async def a_short_burst_ends_the_run_instead_of_hanging(dut):
    """The one that used to hang.

    A slave that asserts RLAST before AxLEN said it would has withheld
    beats the engine is waiting for. Compute starves, the writer never
    gets a full burst, and nothing ever finishes: ERR_RLEN is latched
    into a register the host cannot read until a run that will not end
    ends.

    AXI4 A3.4.1 requires exactly AxLEN+1 transfers and is silent on
    master recovery, so the behaviour is chosen from the neighbouring
    conventions - PCIe completes the transaction and logs, an AXI
    interconnect answers SLVERR rather than stalling, ap_ctrl_hs cannot
    express a run that never ends. The engine abandons the run.
    """
    axil, ram_a, ram_b, ram_c, ram_d = await _bringup(dut)
    # Burst 1 rather than 0: let one burst complete normally first, so
    # the FIFOs have real content and the abort has to unwind a machine
    # that is genuinely mid-flight rather than one still starting up.
    ram_b.fx.arm(short_at=1)

    await _start_run(dut, axil, ram_a, 512, seed=101)
    await _await_done(dut, axil, "short burst on stream b")

    st = await axil.read_dword(STATUS)
    assert st & ST_RLEN, (
        f"STATUS {st:#x} has no length bit after a truncated burst")
    dut._log.info(f"short burst: run abandoned, STATUS {st:#x}")


@cocotb.test()
async def a_long_burst_ends_the_run_instead_of_corrupting_it(dut):
    """The other half of the same fault.

    An overrunning slave sends a beat past the one that should have
    been last. That beat was never reserved, so it lands in a FIFO with
    no room promised for it - which corrupts operands rather than
    stalling, and is the more dangerous direction because the run would
    otherwise complete and look fine.
    """
    axil, ram_a, ram_b, ram_c, ram_d = await _bringup(dut)
    ram_c.fx.arm(long_at=1)

    await _start_run(dut, axil, ram_a, 512, seed=202)
    await _await_done(dut, axil, "long burst on stream c")

    st = await axil.read_dword(STATUS)
    assert st & ST_RLEN, (
        f"STATUS {st:#x} has no length bit after an overrunning burst")
    dut._log.info(f"long burst: run abandoned, STATUS {st:#x}")


@cocotb.test()
async def a_clean_run_after_a_fault_is_clean(dut):
    """The negative control, and a real requirement.

    STATUS is sticky WITHIN a run and cleared by hardware at ap_start.
    If it were not, one bad run would poison every run after it and the
    host would discard good results forever. This also proves the abort
    path leaves the engine in a state a later run can use - the FIFOs,
    the reservation counters and the writer all have to come back.
    """
    axil, ram_a, ram_b, ram_c, ram_d = await _bringup(dut)

    ram_b.fx.arm(short_at=1)
    await _start_run(dut, axil, ram_a, 512, seed=303)
    await _await_done(dut, axil, "short burst, first run")
    assert (await axil.read_dword(STATUS)) & ST_RLEN

    for r in (ram_a, ram_b, ram_c, ram_d):
        r.fx.reset()
    await _start_run(dut, axil, ram_a, 64, seed=304)
    await _await_done(dut, axil, "clean run after a fault")

    st = await axil.read_dword(STATUS)
    assert st == 0, (
        f"STATUS {st:#x} after a clean run: the previous run's fault "
        f"leaked, so every run after a single bus error would be "
        f"discarded")

    # And the answer has to be right, not merely unflagged - an engine
    # that came back from an abort in a subtly wrong state would pass
    # the STATUS check and fail here.
    from test_krnl import run_op
    await run_op(dut, axil, ram_a, FP32, OP_FMA, 64, seed=305)
    dut._log.info("recovered: a clean run after an abort is bit-exact")
