# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""IEEE 754-2019 binary interchange format descriptors.

The tile's precision ladder is exactly the interchange ladder - no
bfloat, no TF32, no vendor variants. Bit-exact identity across
implementations is the product, and identity needs one definition.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FpFormat:
    name: str
    exp_w: int  # exponent field width in bits
    man_w: int  # trailing significand field width in bits

    @property
    def width(self) -> int:
        return 1 + self.exp_w + self.man_w

    @property
    def prec(self) -> int:
        """Precision p: significand bits including the hidden bit."""
        return self.man_w + 1

    @property
    def bias(self) -> int:
        return (1 << (self.exp_w - 1)) - 1

    @property
    def emax(self) -> int:
        """Largest unbiased exponent of a normal number."""
        return self.bias

    @property
    def emin(self) -> int:
        """Smallest unbiased exponent of a normal number."""
        return 1 - self.bias

    @property
    def exp_mask(self) -> int:
        return (1 << self.exp_w) - 1

    @property
    def man_mask(self) -> int:
        return (1 << self.man_w) - 1

    @property
    def sign_mask(self) -> int:
        return 1 << (self.width - 1)


FP32 = FpFormat("fp32", 8, 23)
FP64 = FpFormat("fp64", 11, 52)
FP128 = FpFormat("fp128", 15, 112)
FP256 = FpFormat("fp256", 19, 236)

FORMATS = {f.name: f for f in (FP32, FP64, FP128, FP256)}

# Precision-mode encoding shared with rtl/ (the CSR MODE precision
# field, currently MODE[11:8]) and hw/kernel.xml. Prefer the name to
# the bit position: docs/ARCHITECTURE.md is the one normative map.
PREC_CODE = {"fp32": 0, "fp64": 1, "fp128": 2, "fp256": 3}
