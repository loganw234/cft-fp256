# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cftmpfr - libcft as a drop-in accelerator for MPFR at IEEE precisions.

    from cftmpfr import Context, batch
    ctx = Context(237)                     # binary256, roundTiesToEven
    y, flags = batch.fma(ctx, xs, cs, zs)  # one C call for the array

WHAT THIS ACCELERATES, PRECISELY. The common way MPFR is used from
Python (gmpy2) for reproducible binary arithmetic is as an IEEE
binary-format EMULATOR: precision fixed at an interchange format's,
exponent range bounded (mpfr_set_emin/set_emax per the MPFR manual's
recipe - gmpy2.ieee() is exactly this), subnormals via
mpfr_subnormalize, IEEE flags observed. That usage pattern - and only
that pattern - is what this package accelerates, at the four
precisions the CFT tile implements: 24 (binary32), 53 (binary64), 113
(binary128) and 237 (binary256) bits. Raw MPFR with its unbounded
exponent range, or any other precision, is OUT OF SCOPE: libcft
computes interchange formats, and pretending otherwise would sell the
one thing this project refuses to sell.

WHAT IS ACCELERATED, part two: the TRANSCENDENTALS. exp, expm1, exp2,
log, log1p, log2, log10, pow and hypot arrived with ABI 0.3, correctly
rounded at all four precisions under every attribute, with 754-2019
clause 9.2.1's special values and exact flags. That is a sharper claim
than it sounds: for add and mul, agreeing with MPFR is a statement
about rounding, but for exp and pow it is a statement about the
FUNCTION - a merely accurate implementation differs from MPFR in the
last bit on a percentage of inputs, and nothing decides which is right.
Correct rounding makes them the same operation, so the drop-in stays a
drop-in. host/tools/mpfr_check.c drives 95,680 transcendental cases
against MPFR across the four formats and five attributes with zero
value and zero flag mismatches.

WHY THE SAME BITS. libcft's software backend is proven against three
oracles: the project's golden model over its full differential and
conformance suites, 23.9 billion CPU-checked cases at binary32/64,
and GNU MPFR itself - host/tools/mpfr_check.c drives add, sub, mul,
fma, div and sqrt against MPFR 4.2's IEEE emulation at all four
precisions under all five rounding attributes: 999,000 cases, values
AND flags, zero disagreements. One asterisk, stated rather than
buried: MPFR has no roundTiesToAway, so the RNDNA rows of that suite
compare against a ties-to-away oracle BUILT from pure-MPFR
intermediates (the p+1 guard/sticky construction), not against a
native MPFR mode - there is nothing native to compare against, which
is also why this package's RNDNA exists at all: libcft provides the
attribute MPFR lacks. The same calls made here run unchanged on the
FPGA tile (pass an artifact path to Context) and return identical
bits; that is cft.h's contract, not a goal.

SEMANTICS FINE PRINT, honestly stated:

* NaNs: libcft arithmetic returns the one canonical quiet NaN (sign 0,
  quiet bit, payload 0) for any NaN input or invalid operation, and a
  signaling NaN raises invalid - docs/DETERMINISM.md. MPFR keeps no
  payloads and no NaN sign, so NaN interop is by class, which the two
  sides' conventions make lossless in practice: everything MPFR can
  say about a NaN survives the trip.
* Flags: per call, as the OR across the batch (cft.h's contract), with
  the contract's definitions - underflow is tininess AFTER rounding
  AND inexact. Sticky accumulation on the Context mirrors MPFR's flag
  model.
* Conversions: bit-exact or refused; the only rounding ever performed
  on the way in or out is gmpy2's own (see core.py's docstring).

Dependencies: none. The core is stdlib ctypes against the C ABI - no
build step, no binding generator, which is why the C library is C.
gmpy2 is optional (decimal strings and inexact int/float conversions
refuse loudly without it); numpy is optional (arrays are simply one
more container batch understands when it is present).
"""

from ._lib import (
    CftError,
    FLAG_DIVBYZERO,
    FLAG_INEXACT,
    FLAG_INVALID,
    FLAG_OVERFLOW,
    FLAG_UNDERFLOW,
    flag_names,
)
from .core import (
    RNDD,
    RNDN,
    RNDNA,
    RNDU,
    RNDZ,
    SUPPORTED_PRECISIONS,
    Context,
    Float,
)
from . import batch

__version__ = "0.1.0"

__all__ = [
    "Context", "Float", "batch", "CftError", "flag_names",
    "SUPPORTED_PRECISIONS",
    "RNDN", "RNDZ", "RNDD", "RNDU", "RNDNA",
    "FLAG_INVALID", "FLAG_DIVBYZERO", "FLAG_OVERFLOW",
    "FLAG_UNDERFLOW", "FLAG_INEXACT",
    "__version__",
]
