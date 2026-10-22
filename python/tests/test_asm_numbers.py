# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The assembler's refusals of a number: located, and never an uncaught
error (KL-378 and KL-377).

KL-378. asm.py's two refusals of a number - "is not a number" and the digit
bound - carried no file and no line, because the directives called
_parse_uint directly; a refusal of a line is `file:line: message`. They
come through _Asm.uint now, at every site that reads a number: `.deposits`,
`.scratch N`, `.scratch in`, `.scratch out`, `.slot`, a slot operand,
`repeat` and a post-step. Not every refusal has a line: the `.deposits` cap
is checked once the whole image is read, so it names the source alone
(`prog.cfta: max_deposits=2000000, cap 1048576`), as before, and a source
without a `.deposits` is refused at line 0;
test_the_located_refusal_is_the_assemblers_own_and_one_line says so.

KL-377. A `0x` number has any length (docs/PROGRAMS.md), and a refusal that
printed one in decimal raised an uncaught ValueError once it was past
Python's own digit limit (4,300 digits by default: about 3,600 hex digits):
`.deposits 0x...` in validate's message, a post-step in step's. And with
that limit LOWERED below the text form's own bound of 4,300 digits
(sys.set_int_max_str_digits, -X int_max_str_digits, PYTHONINTMAXSTRDIGITS),
int() raised on a decimal the text form accepts. Both are refusals by name
now (the number named by its leading hex digits and their count), and a
decimal within the text form's bound is read whatever the limit.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import asm  # noqa: E402

HEAD = ".format fp64\n.deposits 1\n"


def refusal(src, name="<t>"):
    with pytest.raises(asm.AsmError) as exc:
        asm.assemble(src, name)
    return str(exc.value)


# ---- KL-378: the file and the line --------------------------------------

# (site, source, the line of the bad number, what the refusal calls it, the token)
NOT_A_NUMBER = [
    (".deposits", ".format fp64\n.deposits abc\nhalt\n", 2, ".deposits", "abc"),
    (".scratch N", HEAD + ".scratch abc\nhalt\n", 3, ".scratch", "abc"),
    (".scratch in", HEAD + ".scratch in abc\nhalt\n", 3, ".scratch in", "abc"),
    (".scratch out", HEAD + ".scratch out 0xq\nhalt\n", 3, ".scratch out",
     "0xq"),
    (".slot", HEAD + ".scratch 16\n.slot S = x1\nhalt\n", 4, ".slot", "x1"),
    ("a slot operand", HEAD + "stl r0, 0xzz\nhalt\n", 3, "a scratch slot",
     "0xzz"),
    ("repeat", HEAD + "repeat 0xq\nendrep\nhalt\n", 3, "repeat", "0xq"),
    ("a post-step", HEAD + "ldx r3, r1, +q\nhalt\n", 3, "a post-step", "q"),
]


@pytest.mark.parametrize("site, src, line, what, tok", NOT_A_NUMBER,
                         ids=[c[0] for c in NOT_A_NUMBER])
def test_a_token_that_is_not_a_number_is_refused_at_its_file_and_line(
        site, src, line, what, tok):
    assert refusal(src, "prog.cfta") == \
        f"prog.cfta:{line}: {what}: {tok!r} is not a number"
    # the same from a file's bytes, and under CRLF line ends
    assert refusal(src.encode(), "prog.cfta").startswith(f"prog.cfta:{line}: ")
    crlf = src.replace("\n", "\r\n")
    assert refusal(crlf, "prog.cfta").startswith(f"prog.cfta:{line}: ")


TOO_LONG = "1" * 4301
DIGIT_BOUND = [
    (".deposits", f".format fp64\n.deposits {TOO_LONG}\nhalt\n", 2, ".deposits",
     TOO_LONG),
    (".scratch N", HEAD + f".scratch {TOO_LONG}\nhalt\n", 3, ".scratch",
     TOO_LONG),
    (".scratch in", HEAD + f".scratch in {TOO_LONG}\nhalt\n", 3,
     ".scratch in", TOO_LONG),
    (".slot", HEAD + f".scratch 16\n.slot S = {TOO_LONG}\nhalt\n", 4, ".slot",
     TOO_LONG),
    ("a slot operand", HEAD + f"stl r0, {TOO_LONG}\nhalt\n", 3,
     "a scratch slot", TOO_LONG),
    ("repeat", HEAD + f"repeat {TOO_LONG}\nendrep\nhalt\n", 3, "repeat",
     TOO_LONG),
    ("a post-step", HEAD + f"ldx r3, r1, +{TOO_LONG}\nhalt\n", 3,
     "a post-step", TOO_LONG),
]


@pytest.mark.parametrize("site, src, line, what, tok", DIGIT_BOUND,
                         ids=[c[0] for c in DIGIT_BOUND])
def test_a_decimal_past_the_digit_bound_is_refused_at_its_file_and_line(
        site, src, line, what, tok):
    assert refusal(src, "prog.cfta") == (
        f"prog.cfta:{line}: {what}: {tok!r} has 4301 digits, and a decimal "
        f"number has at most 4300")


def test_the_located_refusal_is_the_assemblers_own_and_one_line():
    """The file and line are the ones a refusal of an opcode carries: the
    same `source:line: ` prefix, the line counted from 1 over the whole
    source. And what has no line, which docs/PROGRAMS.md says: the
    `.deposits` cap is checked once the whole image is read, and a missing
    `.deposits` is found at the end (line 0)."""
    other = refusal(HEAD + "\n\nnosuch r3, r0\nhalt\n", "prog.cfta")
    ours = refusal(HEAD + "\n\n.scratch abc\nhalt\n", "prog.cfta")
    assert other.startswith("prog.cfta:5: ") and ours.startswith("prog.cfta:5: ")
    assert refusal(".format fp64\n.deposits 2000000\nhalt\n", "prog.cfta") == \
        "prog.cfta: max_deposits=2000000, cap 1048576"
    assert refusal(".format fp64\nhalt\n", "prog.cfta") == \
        "prog.cfta:0: .deposits is required"


# ---- KL-377: a refusal by name, whatever the length ---------------------

needs_limit = pytest.mark.skipif(
    not hasattr(sys, "set_int_max_str_digits"),
    reason="this Python has no integer string-conversion limit to set "
           "(before 3.10.7): nothing is past it")


def _with_limit(n):
    old = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(n)
    try:
        yield n
    finally:
        sys.set_int_max_str_digits(old)


@pytest.fixture
def limit_4300():
    """Python's default, whatever the environment set (PYTHONINTMAXSTRDIGITS)."""
    yield from _with_limit(4300)


@pytest.fixture
def limit_640():
    """The lowest value Python allows, below the text form's bound."""
    yield from _with_limit(640)


@needs_limit
@pytest.mark.parametrize("digits", [3500, 3585, 3999, 20000])
def test_a_huge_hex_deposits_is_refused_by_name(digits, limit_4300):
    msg = refusal(".format fp64\n.deposits 0x" + "1" * digits + "\nhalt\n")
    assert msg.startswith("<t>: max_deposits="), msg
    assert msg.endswith(f", cap {asm.MAX_DEPOSITS}"), msg[-60:]
    if digits >= 3585:                           # past Python's own digit limit
        assert f"({digits} hex digits)" in msg, msg
        assert len(msg) < 200, len(msg)          # bounded however long it was
    else:                                        # within it: the decimal, as before
        assert "hex digits" not in msg and len(msg) > 4000


@needs_limit
@pytest.mark.parametrize("sign", ["", "-"])
@pytest.mark.parametrize("op", ["stx", "ldx"])
def test_a_huge_hex_post_step_is_refused_by_name(op, sign, limit_4300):
    src = HEAD + f"{op} r3, r1, {sign}0x" + "1" * 4000 + "\nhalt\n"
    msg = refusal(src)
    assert msg.startswith(f"<t>:3: step {sign}0x111111111111... (4000 hex "
                          f"digits) outside {asm.STEP_MIN}..{asm.STEP_MAX}: "), msg
    assert len(msg) < 200


@needs_limit
def test_a_number_that_str_can_print_is_printed_as_before(limit_4300):
    assert asm._int_text(0) == "0" and asm._int_text(-5) == "-5"
    assert asm._int_text(10 ** 4000) == str(10 ** 4000)
    big = 10 ** 5000
    assert asm._int_text(big) == f"0x{big:x}"[:14] + "... (" + \
        str(len(f"{big:x}")) + " hex digits)"
    assert asm._int_text(-big).startswith("-0x") and \
        asm._int_text(-big).endswith(" hex digits)")


@needs_limit
def test_a_decimal_within_the_text_forms_bound_is_read_under_a_lowered_limit(
        limit_640):
    """Numbers written with 1,000 and 2,000 digits (leading zeros): within the
    text form's bound of 4,300, so read - but under a limit lowered to 640
    int() raised an uncaught ValueError on each. The same bytes at the
    lowered limit as with none."""
    zeros = "0" * 999
    sources = [
        ".format fp64\n.deposits " + "0" * 1999 + "2\ndeposit r0\nhalt\n",
        HEAD + "deposit r" + zeros + "5\nhalt\n",
        HEAD + "repeat " + zeros + "3\nadd r3, r0, r1\nendrep\nhalt\n",
        HEAD + "op" + zeros + "1 r3, r0, r1, r2\nhalt\n",
        HEAD + ".reg X = r" + zeros + "4\ndeposit X\nhalt\n",
        HEAD + "ldx r3, r1, +" + zeros + "7\nhalt\n",
    ]
    lowered = [asm.assemble(s, "<t>") for s in sources]
    assert sys.get_int_max_str_digits() == 640     # put back, not left lifted
    sys.set_int_max_str_digits(0)                  # no limit at all
    try:
        unlimited = [asm.assemble(s, "<t>") for s in sources]
    finally:
        sys.set_int_max_str_digits(640)
    assert lowered == unlimited


@needs_limit
def test_a_long_decimal_out_of_range_is_refused_by_name_under_a_lowered_limit(
        limit_640):
    msg = refusal(".format fp64\n.deposits " + "1" * 1000 + "\nhalt\n")
    assert msg.startswith("<t>: max_deposits=") and \
        msg.endswith(f", cap {asm.MAX_DEPOSITS}"), msg
    msg = refusal(HEAD + "deposit r" + "1" * 1000 + "\nhalt\n")
    assert msg.startswith("<t>:3: r") and \
        msg.endswith(" is outside r0..r31"), msg
    msg = refusal(HEAD + "ldx r3, r1, -" + "1" * 1000 + "\nhalt\n")
    assert msg.startswith("<t>:3: step -") and \
        " outside -2048..2047: " in msg, msg
    assert sys.get_int_max_str_digits() == 640
