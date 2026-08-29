# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
import cocotb

from cft_golden import FP32
from fpfma_common import run_fma_pipe_test


@cocotb.test()
async def fma_fp32_vs_golden(dut):
    await run_fma_pipe_test(dut, FP32, directed_default=1500,
                            random_default=2500)
