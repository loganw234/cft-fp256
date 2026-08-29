# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft_golden: the exact reference model for the cft-fp256 tile.

Pure-Python, integer-exact IEEE 754-2019 binary arithmetic for the
interchange ladder fp32/fp64/fp128/fp256, plus deterministic
conformance-vector generation. See softfloat.py for the semantics.
"""

from .formats import FP32, FP64, FP128, FP256, FORMATS, PREC_CODE, FpFormat
from .softfloat import (
    FLAG_INVALID, FLAG_DIVZERO, FLAG_OVERFLOW, FLAG_UNDERFLOW, FLAG_INEXACT,
    OP_FMA, OP_ADD, OP_SUB, OP_MUL, OP_NAMES,
    add, sub, mul, fma, compute, steer, unpack,
    zero_bits, one_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits, max_normal_bits,
    negate, is_nan,
)
from . import vectors

__all__ = [
    "FP32", "FP64", "FP128", "FP256", "FORMATS", "PREC_CODE", "FpFormat",
    "FLAG_INVALID", "FLAG_DIVZERO", "FLAG_OVERFLOW", "FLAG_UNDERFLOW",
    "FLAG_INEXACT",
    "OP_FMA", "OP_ADD", "OP_SUB", "OP_MUL", "OP_NAMES",
    "add", "sub", "mul", "fma", "compute", "steer", "unpack",
    "zero_bits", "one_bits", "inf_bits", "qnan_bits", "snan_bits",
    "min_subnormal_bits", "max_subnormal_bits", "min_normal_bits",
    "max_normal_bits", "negate", "is_nan", "vectors",
]

__version__ = "0.1.0"
