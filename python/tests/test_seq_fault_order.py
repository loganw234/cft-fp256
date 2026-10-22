# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The model's order of refusals, held where it is defined (KL-438).

python/cft_golden/seq.py is the authority on what a program loader refuses,
and an image with two faults is refused for the first one the model reaches.
host/src/program.c follows the model's order (host/tests/loader_order_check.py
holds the two together, image by image, and needs the built library); this
file holds the model's own order, and its sentence for a constant under kx,
with no build, so that the authority cannot move unseen and the two move
together or not at all.

The images are the ones that check builds (the module is imported by its
path; its main() is not run).
"""

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import seq  # noqa: E402

CHECK = Path(__file__).resolve().parents[2] / "host" / "tests" / \
    "loader_order_check.py"
spec = importlib.util.spec_from_file_location("loader_order_check_images",
                                               CHECK)
lo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lo)

W, REPEAT, ENDREP = lo.W, lo.REPEAT, lo.ENDREP
ADD, QUIET = lo.ADD, lo.QUIET


def image(words, **header):
    s = lo.base()
    s["insns"] = list(words)
    s.update(header)
    return lo.assemble(s)


def refusal(img):
    with pytest.raises(seq.ProgramError) as e:
        seq.Program.from_bytes(img)
    return str(e.value)


def test_each_fault_alone_is_the_rule_its_row_says():
    for name, change, key in lo.HEADER:
        s = lo.base()
        s.update(change)
        assert lo.named(refusal(lo.assemble(s)), 0)[0] == key, name
    for name, words, key in lo.STREAM:
        assert lo.named(refusal(image(words)), 0)[0] == key, name


# (what the image has, the image, the rule the model names, the instruction)
ORDER = [
    ("an unknown flag bit and a scratch word without its flag",
     image([ADD], flags=0x80, word7=0x00010002), "flags", None),
    ("a wrong length and too many deposits",
     image([ADD], trailer=b"\0", maxdep=(1 << 20) + 1), "length", None),
    ("a wrong length and 513 constants",
     image([ADD], trailer=b"\0", flags=lo.FL_BANK_EXT, n_consts=513,
           consts=[]), "length", None),
    ("too many deposits and 513 constants",
     image([ADD], maxdep=(1 << 20) + 1, flags=lo.FL_BANK_EXT, n_consts=513,
           consts=[]), "max_deposits", None),
    ("kx naming no constant and imm[31]",
     image([W(1, rd=1, kx=1, imm=1 << 31)]), "kx_selects_nothing", 0),
    # the register high bits of all three operands come before any index
    ("a four-bit index past the bank on a, a high bit on constant b",
     image([W(1, rd=1, ra=5, ka=1, kb=1, imm=1 << 26)]),
     "high_bit_on_constant", 0),
    # a register operand under kx: its byte of imm, then its ninth bit
    ("a register operand under kx with a byte of imm and its ninth bit",
     image([W(1, rd=1, kb=1, kx=1, imm=5 | (1 << 8) | (1 << 28))]),
     "byte_on_register", 0),
    # a static scratch slot is the model's, ahead of every later rule
    ("STL slot 300 and, after it, an ENDREP with no REPEAT",
     image([W(6, ctrl=1, imm=300), ENDREP]), "scratch_slot", 0),
    # the bound is met at the control instruction after the ALU that
    # takes the count over it
    ("an ALU instruction takes the count past 2^40, then an ENDREP",
     image([REPEAT(1 << 20), REPEAT(1 << 20), ADD, ENDREP, ENDREP]),
     "worst_case", 3),
    ("a trip count whose product passes 2^40 and no instruction after it",
     image([REPEAT(1 << 20), REPEAT(1 << 21), ENDREP, ENDREP]),
     "worst_case", 2),
    ("the bound passed only by the ALU instructions after the last loop",
     image([REPEAT(2097148), REPEAT(524287), ENDREP, ENDREP, ADD, ADD, ADD,
            ADD]), "worst_case", None),
    ("a loop and a quiet region both left open",
     image([REPEAT(2), QUIET]), "loops_left_open", None),
]


@pytest.mark.parametrize("what,img,key,pc", ORDER,
                         ids=[o[0] for o in ORDER])
def test_two_faults_are_refused_for_the_models_first(what, img, key, pc):
    msg = refusal(img)
    assert lo.named(msg, 0) == (key, pc), msg


def test_a_constant_under_kx_is_named_by_its_nine_bit_index():
    # rb names constant 257 = 0x101 through imm: byte 1, ninth bit imm[29]
    # (KL-438: the sentence used to say `rb names constant 1`)
    msg = refusal(image([W(1, rd=1, rb=3, kb=1, kx=1,
                           imm=(1 << 8) | (1 << 29))]))
    assert "rb names constant 257 through imm under kx" in msg, msg
    assert "the rb field must be zero and it is 3" in msg, msg
    # and with the ninth bit clear it is the byte, as before
    msg = refusal(image([W(1, rd=1, rb=3, kb=1, kx=1, imm=1 << 8)]))
    assert "rb names constant 1 through imm under kx" in msg, msg
