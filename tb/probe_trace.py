# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
# A diagnostic, not a bench (`make seqtrace`, not part of `make sim`):
# one run of the every-block-length program at fp128 over a full
# block, every cycle of the issue pipe, the register file's ports, the
# retire and the deposit path written to sim_build/trace/trace.txt, one
# row a cycle, hex, a header line naming the columns. It is how the
# drain's stall slip was found on 2026-09-14 (docs/VALIDATION.md): the
# file showed the right value written and the wrong one drained.
# Change `fmt`, `n` and `prog` below to trace something else.
import sys
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge, ReadOnly

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import FORMATS, softfloat as sf  # noqa: E402
from test_seq_core import Bench, operands, _pipe_program  # noqa: E402


def _v(sig):
    try:
        return int(sig.value)
    except Exception:
        return -1


@cocotb.test()
async def trace(dut):
    b = Bench(dut)
    await b.start()
    fmt = FORMATS["fp128"]
    n = 32
    prog = _pipe_program(fmt)
    out = open("/work/tb/sim_build/trace/trace.txt", "w")
    names = ["st", "pc", "bt", "q_n", "q_rd0", "q_rd1", "q_rd2", "wb_bt",
             "dep_v_a", "dep_pos_a", "dep_v_b", "dep_pos_b", "dep_v_c", "dep_pos_c",
             "raw_hold", "pb_v", "pf_v", "pf_ka", "pf_kb", "pf_kc", "al_valid", "al_ov",
             "rf_we", "rf_waddr", "rf_raddr_a", "rf_raddr_b", "rf_raddr_c",
             "q_push", "wb_pop", "nxt_ok", "cur", "al_a", "al_b", "al_c", "al_d",
             "rf_rdata_a", "rf_rdata_b", "rf_rdata_c", "kq2_c", "rf_wdata", "al_op",
             "db_we", "db_waddr", "dcnt", "bt_dep_go", "active", "bt_cnt"]
    sigs = {nm: getattr(dut, nm) for nm in names}
    out.write(" ".join(names) + "\n")

    async def mon():
        cyc = 0
        while True:
            await RisingEdge(dut.ap_clk)
            await ReadOnly()
            row = [str(cyc)] + [("%x" % _v(sigs[nm])) for nm in names]
            out.write(" ".join(row) + "\n")
            cyc += 1

    cocotb.start_soon(mon())
    try:
        await b.program(fmt, prog, operands(fmt, n, 1200 + n),
                        operands(fmt, n, 1300 + n), operands(fmt, n, 1400 + n),
                        n, "fp128 the pipe at n=32 (traced)")
    finally:
        out.close()
