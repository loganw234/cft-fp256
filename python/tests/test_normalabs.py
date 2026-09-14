# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The normal-only mask (seqprogs.normal_abs_program) against softfloat's
class: |x| for a normal of either sign, +0 for everything else, and no
flag raised - every class, both signs, randoms, every format."""

import pathlib
import random
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from cft_golden import FP32, FP64, FP128, FP256, asm, seqprogs  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

FORMATS = (FP32, FP64, FP128, FP256)
PROGRAMS = pathlib.Path(__file__).resolve().parents[2] / "programs"


def classes(fmt):
    xs = [0, sf.inf_bits(fmt, 0), sf.qnan_bits(fmt), sf.snan_bits(fmt), 1,
          fmt.man_mask, sf.min_normal_bits(fmt), sf.max_normal_bits(fmt),
          sf.one_bits(fmt), (1 << fmt.man_w) | 1]
    return xs + [x | fmt.sign_mask for x in xs]


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_every_class_both_signs_and_randoms(fmt):
    rng = random.Random(fmt.width)
    xs = classes(fmt) + [rng.getrandbits(fmt.width) for _ in range(400)]
    outs, flags = seqprogs.run_normal_abs(fmt, xs)
    for x, o in zip(xs, outs):
        ua = sf.unpack(fmt, x)
        want = (x & ~fmt.sign_mask) if ua.kind == sf.NORM else 0
        assert o == want, f"{fmt.name} {x:#x}: {o:#x} vs {want:#x}"
        assert o == seqprogs.normal_abs(fmt, x)
    assert flags == 0, "the mask must not signal, signaling NaNs included"


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_the_source_is_the_model(fmt):
    src = PROGRAMS / f"normalabs-{fmt.name}.cfta"
    got = asm.assemble(src.read_text(encoding="utf-8"), src.name)
    assert got == seqprogs.normal_abs_program_for(fmt).to_bytes()


def test_a_maximum_over_the_mask_is_the_maximum_over_the_normals():
    """The property the mask exists for: max from +0 over masked values
    equals pc_error's max over the normal |x| - by bit order, which is
    numeric order for non-negative encodings."""
    fmt = FP64
    rng = random.Random(64)
    for _ in range(50):
        xs = [rng.choice(classes(fmt) + [rng.getrandbits(64)]) for _ in range(24)]
        outs, _ = seqprogs.run_normal_abs(fmt, xs)
        want = 0
        for x in xs:
            if sf.unpack(fmt, x).kind == sf.NORM:
                want = max(want, x & ~fmt.sign_mask)
        assert max([0] + outs) == want
