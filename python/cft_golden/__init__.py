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
    OP_ABS, OP_NEG, OP_COPYSIGN, OP_MIN, OP_MAX, OP_MINNUM, OP_MAXNUM,
    OP_SELECT, OP_CMPLT, OP_CMPLE, OP_CMPEQ,
    OP_IAND, OP_IOR, OP_IXOR, OP_IADD,
    OP_ISUB, OP_ISHL, OP_ISHR, OP_ICMPLT, INT_OPS,
    iand, ior, ixor, iadd, isub, ishl, ishr, icmplt,
    select, cmplt, cmple, cmpeq,
    OP_RECIP_SEED, OP_RSQRT_SEED, SEED_OPS, recip_seed, rsqrt_seed,
    ARITH_OPS, SIMPLE_OPS, SIMPLE_IMPL,
    fabs, neg, copysign, fmin, fmax, fminnum, fmaxnum,
    RND_RNE, RND_RTZ, RND_RDN, RND_RUP, RND_RMM, RND_NAMES, RND_MODES,
    RND_RTTZ, RND_RTTZ_NAME,
    add, sub, mul, fma, div, sqrt, compute, steer, unpack,
    zero_bits, one_bits, inf_bits, qnan_bits, snan_bits,
    min_subnormal_bits, max_subnormal_bits, min_normal_bits, max_normal_bits,
    negate, is_nan,
    round_int, convert, from_int, to_int, scaleb, logb,
    next_up, next_down, classify, total_order, total_order_mag,
    cmplt_sig, cmple_sig, cmpeq_sig, remainder,
    CLASS_NEG_INF, CLASS_NEG_NORM, CLASS_NEG_SUB, CLASS_NEG_ZERO,
    CLASS_POS_ZERO, CLASS_POS_SUB, CLASS_POS_NORM, CLASS_POS_INF,
    CLASS_SNAN, CLASS_QNAN, CLASS_NAMES,
)
from .transcend import (
    TRANSCEND_FNS, TRANSCEND_ARITY, TRANSCEND_IMPL, ZivEscalation,
    FN_EXP, FN_EXPM1, FN_EXP2, FN_LOG, FN_LOG1P, FN_LOG2, FN_LOG10,
    FN_POW, FN_HYPOT,
    FN_SINPI, FN_COSPI, FN_TANPI, FN_ASIN, FN_ACOS, FN_ATAN, FN_ATAN2,
    FN_ASINPI, FN_ACOSPI, FN_ATANPI, FN_ATAN2PI, TRIG_FNS,
    exp, expm1, exp2, log, log1p, log2, log10, pow, hypot,
    sinpi, cospi, tanpi, asin, acos, atan, atan2,
    asinpi, acospi, atanpi, atan2pi,
    prec_cap, start_prec,
)
from .augmented import (
    AUG_FNS, AUG_IMPL, FN_AUG_ADD, FN_AUG_SUB, FN_AUG_MUL,
    augmented_add, augmented_sub, augmented_mul,
)
from .reduce import (
    OP_SUM, OP_DOT, OP_SUMSQ, OP_SUMABS, REDUCE_OPS, REDUCE_OP_NAMES,
    SP_PROD, SP_PROD_SUM, SP_PROD_DIFF, SCALED_KINDS, SCALED_KIND_NAMES,
    SCALE_MIN, SCALE_MAX, ScaleOverflow,
    split, tree_adds, canonical_ranges, reduce_bits, fsum, fdot, combine,
    stream_reduce, fsumsq, fsumabs, norm_split, scaled_prod,
)
from . import augmented, transcend, vectors

__all__ = [
    "FP32", "FP64", "FP128", "FP256", "FORMATS", "PREC_CODE", "FpFormat",
    "FLAG_INVALID", "FLAG_DIVZERO", "FLAG_OVERFLOW", "FLAG_UNDERFLOW",
    "FLAG_INEXACT", "OP_FMA", "OP_ADD", "OP_SUB", "OP_MUL", "OP_NAMES",
    "OP_ABS", "OP_NEG", "OP_COPYSIGN", "OP_MIN", "OP_MAX", "OP_MINNUM",
    "OP_MAXNUM", "OP_SELECT", "OP_CMPLT", "OP_CMPLE", "OP_CMPEQ", "OP_IAND",
    "OP_IOR", "OP_IXOR", "OP_IADD", "OP_ISUB", "OP_ISHL", "OP_ISHR",
    "OP_ICMPLT", "INT_OPS", "iand", "ior", "ixor", "iadd", "isub", "ishl",
    "ishr", "icmplt", "select", "cmplt", "cmple", "cmpeq", "OP_RECIP_SEED",
    "OP_RSQRT_SEED", "SEED_OPS", "recip_seed", "rsqrt_seed", "ARITH_OPS",
    "SIMPLE_OPS", "SIMPLE_IMPL", "fabs", "neg", "copysign", "fmin", "fmax",
    "fminnum", "fmaxnum", "RND_RNE", "RND_RTZ", "RND_RDN", "RND_RUP",
    "RND_RMM", "RND_NAMES", "RND_MODES", "RND_RTTZ", "RND_RTTZ_NAME", "add",
    "sub", "mul", "fma", "compute", "steer", "unpack", "zero_bits",
    "one_bits", "inf_bits", "qnan_bits", "snan_bits", "min_subnormal_bits",
    "max_subnormal_bits", "min_normal_bits", "max_normal_bits", "negate",
    "is_nan", "vectors", "round_int", "convert", "from_int", "to_int",
    "scaleb", "logb", "next_up", "next_down", "classify", "total_order",
    "total_order_mag", "cmplt_sig", "cmple_sig", "cmpeq_sig", "remainder",
    "CLASS_NEG_INF", "CLASS_NEG_NORM", "CLASS_NEG_SUB", "CLASS_NEG_ZERO",
    "CLASS_POS_ZERO", "CLASS_POS_SUB", "CLASS_POS_NORM", "CLASS_POS_INF",
    "CLASS_SNAN", "CLASS_QNAN", "CLASS_NAMES", "TRANSCEND_FNS",
    "TRANSCEND_ARITY", "TRANSCEND_IMPL", "ZivEscalation", "FN_EXP",
    "FN_EXPM1", "FN_EXP2", "FN_LOG", "FN_LOG1P", "FN_LOG2", "FN_LOG10",
    "FN_POW", "FN_HYPOT", "FN_SINPI", "FN_COSPI", "FN_TANPI", "FN_ASIN",
    "FN_ACOS", "FN_ATAN", "FN_ATAN2", "FN_ASINPI", "FN_ACOSPI", "FN_ATANPI",
    "FN_ATAN2PI", "TRIG_FNS", "exp", "expm1", "exp2", "log", "log1p", "log2",
    "log10", "pow", "hypot", "sinpi", "cospi", "tanpi", "asin", "acos",
    "atan", "atan2", "asinpi", "acospi", "atanpi", "atan2pi", "prec_cap",
    "start_prec", "transcend", "AUG_FNS", "AUG_IMPL", "FN_AUG_ADD",
    "FN_AUG_SUB", "FN_AUG_MUL", "augmented_add", "augmented_sub",
    "augmented_mul", "augmented", "OP_SUM", "OP_DOT", "REDUCE_OPS",
    "REDUCE_OP_NAMES", "OP_SUMSQ", "OP_SUMABS", "SP_PROD", "SP_PROD_SUM",
    "SP_PROD_DIFF", "SCALED_KINDS", "SCALED_KIND_NAMES", "SCALE_MIN",
    "SCALE_MAX", "ScaleOverflow", "split", "tree_adds", "canonical_ranges",
    "reduce_bits", "fsum", "fdot", "combine", "stream_reduce", "fsumsq",
    "fsumabs", "norm_split", "scaled_prod",
]

__version__ = "0.1.0"
