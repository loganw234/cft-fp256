# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
import cocotb

from cft_golden import FP128
from fpfma_common import run_fma_pipe_test


@cocotb.test()
async def fma_fp128_vs_golden(dut):
    await run_fma_pipe_test(dut, FP128, directed_default=900,
                            random_default=1200)
