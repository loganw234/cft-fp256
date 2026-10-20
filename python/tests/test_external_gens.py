# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Tests of the code that puts three outside test sources to work against
libcft (docs/EXTERNAL-GENERATORS.md): python/external_tf.py, external_ibm.py,
external_ucblib.py and fetch_external.py. The C halves are held by
host/tests/tf_subject_check.py (make -C host tf-subject-test), which needs a
compiler and so is not in this file.

Every case here is written by us, on the spot: not one byte of Berkeley
TestFloat or SoftFloat, UCBTEST or IBM's vectors is in this repository, and
none of these tests needs one. What they hold is the glue - that a flag word
means what it should, that an error line is read back to the bits it printed,
that a class of disagreement is named for the right reason and that a
planted libcft defect is NOT filed as a convention - and that the
fetch-and-verify script refuses what it must and never touches the network
or a test run.
"""

import hashlib
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import external_ibm as ibm  # noqa: E402
import external_tf as xtf  # noqa: E402
import external_ucblib as ucb  # noqa: E402
import fetch_external as fx  # noqa: E402
from cft_golden import FP32, softfloat as sf  # noqa: E402


# ---- IBM: the operand syntax ------------------------------------------------

def test_ibm_numbers_encode_to_the_bits_they_name():
    enc = ibm.encode
    assert enc("+1.000000P0", "b32") == ("bits", 0x3F800000)
    assert enc("-1.7FFFFFP127", "b32") == ("bits", 0xFF7FFFFF)   # -max finite
    assert enc("+1.000000P-126", "b32") == ("bits", 0x00800000)  # min normal
    assert enc("+0.000001P-126", "b32") == ("bits", 0x00000001)  # min subnormal
    assert enc("+0.7FFFFFP-126", "b32") == ("bits", 0x007FFFFF)  # max subnormal
    assert enc("-Zero", "b32") == ("bits", 0x80000000)
    assert enc("+Inf", "b32") == ("bits", 0x7F800000)
    assert enc("-Inf", "b32") == ("bits", 0xFF800000)
    assert enc("+1.0000000000000P0", "b64") == ("bits", 0x3FF0000000000000)
    # the largest-magnitude negative binary64: sign, exponent 2046, all-ones fraction
    assert enc("-1.FFFFFFFFFFFFFP1023", "b64") == (
        "bits", (1 << 63) | (2046 << 52) | ((1 << 52) - 1))


def test_ibm_the_fraction_field_is_right_aligned_not_a_hex_fraction():
    # the field's own bits: one more in the last digit is one ulp up
    a = ibm.encode("+1.7FFFFBP127", "b32")[1]
    b = ibm.encode("+1.7FFFFCP127", "b32")[1]
    assert b == a + 1


def test_ibm_nan_words():
    kind, q = ibm.encode("Q", "b32")
    kind2, s = ibm.encode("S", "b32")
    kind3, nq = ibm.encode("-Q", "b32")
    assert (kind, kind2, kind3) == ("nan", "nan", "nan")
    assert q == 0x7FC00000 and s == 0x7F800001 and nq == 0xFFC00000
    assert ibm.encode("#", "b32") == ("none", 0)


@pytest.mark.parametrize("tok", [
    "+1.800000P0",      # the fraction field is wider than 23 bits
    "+1.000000P128",    # a normal number cannot have exponent 128
    "+1.000000P-127",   # nor -127: that is the subnormal's place
    "+0.000001P-125",   # a subnormal is written at exponent -126
    "+0.000000P-126",   # a zero is written Zero
    "1.000000P0",       # no sign
    "+Infinity",
])
def test_ibm_operands_the_reader_will_not_interpret_are_refused(tok):
    with pytest.raises(ibm.Refusal):
        ibm.encode(tok, "b32")


def test_ibm_lines_parse_into_cases():
    c = ibm.parse_line("b32+ =0 +1.000000P0 +1.000000P0 -> +1.000000P1 ")
    assert (c["fmt"], c["op"], c["round"], c["traps"]) == ("b32", "+", "near_even", "")
    assert [o[1] for o in c["ops"]] == [0x3F800000, 0x3F800000]
    assert c["res"] == ("bits", 0x40000000) and c["flags"] == 0
    c = ibm.parse_line("b32* > xo +1.7FFFFFP127 +1.000000P1 -> +Inf xo")
    assert c["round"] == "max" and c["traps"] == "xo"
    assert c["res"] == ("bits", 0x7F800000)
    assert c["flags"] == ibm.OVERFLOW | ibm.INEXACT
    c = ibm.parse_line("b32V =0 -1.000000P0 -> Q i")
    assert c["res"][0] == "nan" and c["flags"] == ibm.INVALID
    c = ibm.parse_line("b32*+ < +1.000000P0 +1.000000P0 -Zero -> +1.000000P0")
    assert len(c["ops"]) == 3 and c["round"] == "min"
    c = ibm.parse_line("b32V > i -1.400000P0 -> # i")
    assert c["res"] == ("none", 0) and c["traps"] == "i"
    # the three letters for underflow are one flag here
    for letter in "uvw":
        c = ibm.parse_line(f"b32* =0 +1.000000P-126 +1.000000P-1 -> +0.400000P-126 x{letter}")
        assert c["flags"] == ibm.INEXACT | ibm.UNDERFLOW
    assert ibm.parse_line("synthetic header, no arrow") is None
    assert ibm.parse_line("") is None


@pytest.mark.parametrize("line,reason", [
    ("b128+ =0 +1.000000P0 +1.000000P0 -> +1.000000P1", "format b128"),
    ("b32cff =0 +1.000000P0 -> +1.000000P0", "operation"),
    ("b32+ =x +1.000000P0 +1.000000P0 -> +1.000000P1", "rounding word"),
    ("b32+ =0 +1.000000P0 -> +1.000000P0", "operands"),
    ("b32+ =0 +1.000000P0 +1.000000P0 -> +1.000000P1 x extra", "flag word"),
])
def test_ibm_lines_the_reader_refuses_say_why(line, reason):
    with pytest.raises(ibm.Refusal) as e:
        ibm.parse_line(line)
    assert reason in str(e.value)


def test_ibm_trapped_cases_are_told_apart():
    def k(line):
        return ibm.classify(ibm.parse_line(line))[0]
    base = "b32* =0 {t}+1.7FFFFFP127 +1.000000P1 -> +Inf {f}"
    assert k(base.format(t="", f="xo")) == "comparable"        # no traps at all
    assert k(base.format(t="xo ", f="xo")) == "trap taken"     # overflow trap, overflow raised
    assert k(base.format(t="x ", f="xo")) == "comparable"      # only inexact enabled and raised
    assert k(base.format(t="o ", f="x")) == "comparable"       # an enabled exception that does not occur
    assert k("b32V > i -1.400000P0 -> # i") == "no result"
    assert k("b32* =0 xu +1.000000P-126 +1.000000P-1 -> +1.000000P66 u") == "trap taken"


# ---- IBM: the flag words and the tininess prediction -----------------------

def test_testfloat_flag_bits_run_the_other_way_round():
    for tf_bit, cft_bit in ((1, 16), (2, 8), (4, 4), (8, 2), (16, 1)):
        assert ibm.tf_to_cft(tf_bit) == cft_bit
    assert ibm.tf_to_cft(0) == 0 and ibm.tf_to_cft(31) == 31
    # the five words of testfloat_ver's flag display, v i o u x, the same way
    for text, word in (("v....", 1), (".i...", 2), ("..o..", 4), ("...u.", 8),
                       ("....x", 16), (".....", 0), ("vioux", 31)):
        assert xtf.decode_flags(text) == word


def test_tininess_before_rounding_is_predicted_from_the_exact_result():
    # 2^-126 (1 + 2^-23) times (1 - 2^-23): the exact product is 2^-126 (1 - 2^-46),
    # tiny; rounded to 24 bits with the exponent range unbounded it is 2^-126
    # exactly, which is not tiny. The two detections differ on exactly this.
    c = ibm.parse_line("b32* =0 +1.000001P-126 +1.7FFFFEP-1 -> +1.000000P-126 x")
    assert [o[1] for o in c["ops"]] == [0x00800001, 0x3F7FFFFE]
    bits, gf = sf.mul(FP32, c["ops"][0][1], c["ops"][1][1], sf.RND_RNE)
    assert bits == 0x00800000 and gf == sf.FLAG_INEXACT      # golden: not tiny after
    assert ibm.tiny_before(c) is True
    assert ibm.before_rounding_flags(c, gf) == sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW
    # rounded toward zero the same product is a subnormal: tiny by either rule,
    # so the two detections agree and the prediction leaves golden's flags alone
    c = ibm.parse_line("b32* 0 +1.000001P-126 +1.7FFFFEP-1 -> +0.7FFFFFP-126 xu")
    bits, gf = sf.mul(FP32, c["ops"][0][1], c["ops"][1][1], sf.RND_RTZ)
    assert bits == 0x007FFFFF and gf == sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW
    assert ibm.before_rounding_flags(c, gf) == gf
    # an exact product at the smallest normal is not tiny before either
    c = ibm.parse_line("b32* > +1.000000P-126 +1.000000P0 -> +1.000000P-126")
    assert ibm.tiny_before(c) is False
    assert ibm.before_rounding_flags(c, 0) == 0
    # tiny but exact (a subnormal times one): no loss, no underflow
    c = ibm.parse_line("b32* > +0.000001P-126 +1.000000P0 -> +0.000001P-126")
    assert ibm.tiny_before(c) is True
    assert ibm.before_rounding_flags(c, 0) == 0
    # a square root, or a NaN, has no before-rounding prediction
    assert ibm.tiny_before(ibm.parse_line("b32V =0 +1.000000P0 -> +1.000000P0")) is None
    assert ibm.tiny_before(ibm.parse_line("b32* =0 Q +1.000000P0 -> Q")) is None


def test_ibm_a_disagreement_is_judged_by_golden_and_a_planted_defect_is_not_excused():
    # the tininess row (see above): libcft raises inexact alone, a vector that
    # expects underflow too is the other detection of tininess
    line = "b32* =0 +1.000001P-126 +1.7FFFFEP-1 -> +1.000000P-126 xu"
    c = ibm.parse_line(line)
    gb, gf = sf.mul(FP32, c["ops"][0][1], c["ops"][1][1], sf.RND_RNE)
    assert (gb, gf) == (0x00800000, sf.FLAG_INEXACT)
    # libcft agrees with golden: the vector is the odd one, and it is named for the cause
    cls = ibm.judge(c, gb, gf, gb, gf)
    assert cls == ("libcft = golden, IBM expects otherwise: underflow flag only, "
                   "= tininess BEFORE rounding, result = smallest normal")
    # a vector that expects what libcft gives: no disagreement
    ok = ibm.parse_line("b32* =0 +1.000001P-126 +1.7FFFFEP-1 -> +1.000000P-126 x")
    assert ibm.judge(ok, gb, gf, gb, gf) is None
    # a vector that expects underflow where tininess before rounding would NOT
    # give it: not explained, and it says so
    odd = ibm.parse_line("b32+ =0 +1.000000P0 +1.000000P0 -> +1.000000P1 u")
    gb2, gf2 = sf.add(FP32, 0x3F800000, 0x3F800000, sf.RND_RNE)
    assert (gb2, gf2) == (0x40000000, 0)
    cls = ibm.judge(odd, gb2, gf2, gb2, gf2)
    assert "NOT explained by tininess before rounding" in cls
    assert "result NOT the smallest normal" in cls
    # a value disagreement is named a value, a flag disagreement names its flags
    wrong_value = ibm.parse_line("b32+ =0 +1.000000P0 +1.000000P0 -> +1.000001P1")
    assert ibm.judge(wrong_value, gb2, gf2, gb2, gf2) == \
        "libcft = golden, IBM expects otherwise: value"
    wrong_flag = ibm.parse_line("b32+ =0 +1.000000P0 +1.000000P0 -> +1.000000P1 xo")
    assert ibm.judge(wrong_flag, gb2, gf2, gb2, gf2) == \
        "libcft = golden, IBM expects otherwise: flags ox"
    # a PLANTED libcft defect: libcft's sum is one ulp off and IBM, like golden, has 2.0
    good = ibm.parse_line("b32+ =0 +1.000000P0 +1.000000P0 -> +1.000000P1")
    assert ibm.judge(good, gb2 + 1, gf2, gb2, gf2) == \
        "LIBCFT DEFECT: libcft differs from golden = IBM"
    # and when golden agrees with neither: libcft 2.0 + 2 ulp, the vector 2.0 + 1 ulp
    assert ibm.judge(wrong_value, gb2 + 2, gf2, gb2, gf2) == "all three differ"
    # a NaN result matches any NaN, not an infinity or a number
    nan = ibm.parse_line("b32V =0 -1.000000P0 -> Q i")
    g, gfl = sf.sqrt(FP32, 0xBF800000, sf.RND_RNE)
    assert (g, gfl) == (0x7FC00000, sf.FLAG_INVALID)
    assert ibm.judge(nan, 0x7FC00000, sf.FLAG_INVALID, g, gfl) is None
    assert ibm.judge(nan, 0xFFC00001, sf.FLAG_INVALID, g, gfl) is None
    assert ibm.judge(nan, 0x7F800000, sf.FLAG_INVALID, g, gfl) is not None


# ---- UCBTEST's vectors ---------------------------------------------------

def test_ucb_exception_fields_read_as_ucbtest_reads_them():
    f = ucb.parse_exceptions
    assert f("-") == (0, 31)
    assert f("xo") == (ibm.INEXACT | ibm.OVERFLOW, 31)
    assert f("v") == (ibm.INVALID, 31)
    assert f("d") == (ibm.DIVZERO, 31)
    assert f("?x") == (0, 31 & ~ibm.INEXACT)              # inexact left unchecked
    assert f("v?x") == (ibm.INVALID, 31 & ~ibm.INEXACT)
    assert f("?") == (0, 0)                               # nothing checked
    with pytest.raises(ibm.Refusal):
        f("xq")


def test_ucb_vector_lines_parse_into_cases():
    c = ucb.parse_line("adds n eq - 3f800000 3f800000 40000000", "t:1")
    assert (c["fmt"], c["op"], c["round"]) == ("b32", "+", "near_even")
    assert [o[1] for o in c["ops"]] == [0x3F800000, 0x3F800000]
    assert c["res"] == ("bits", 0x40000000) and c["flags"] == 0 and c["mask"] == 31
    # a double is two words, the high one first; p is toward +inf, m toward -inf, z toward zero
    c = ucb.parse_line("muld p eq x 3ff00000 00000000 3ff00000 00000001 3ff00000 00000002", "t:2")
    assert (c["fmt"], c["op"], c["round"]) == ("b64", "*", "max")
    assert [o[1] for o in c["ops"]] == [0x3FF0000000000000, 0x3FF0000000000001]
    assert c["res"] == ("bits", 0x3FF0000000000002) and c["flags"] == ibm.INEXACT
    assert ucb.parse_line("divs m eq - 3f800000 40000000 3f000000", "t")["round"] == "min"
    assert ucb.parse_line("sqrtd z eq - 40100000 00000000 40000000 00000000", "t")["round"] == "minMag"
    assert len(ucb.parse_line("sqrts n eq - 40800000 40000000", "t")["ops"]) == 1
    # eqz keeps the answer but for its sign; uo asks for a NaN
    assert ucb.parse_line("subs n eqz - 3f800000 3f800000 00000000", "t")["res"][0] == "bitsnz"
    assert ucb.parse_line("divs n uo v 00000000 00000000 7fffffff", "t")["res"][0] == "nan"
    # not vectors: comments and other functions
    assert ucb.parse_line("/* a comment line */", "t") is None
    assert ucb.parse_line("", "t") is None
    assert ucb.parse_line("sins n eq - 3f800000 3f800000", "t") is None
    # refused by name: another relation, a rounding word it does not know, a
    # wrong number of fields
    with pytest.raises(ibm.Refusal):
        ucb.parse_line("adds q eq - 3f800000 3f800000 40000000", "t")
    with pytest.raises(ibm.Refusal):
        ucb.parse_line("adds n vn - 3f800000 3f800000 40000000", "t")
    with pytest.raises(ibm.Refusal):
        ucb.parse_line("adds n eq - 3f800000 3f800000", "t")


def test_ucb_flags_a_vector_leaves_unchecked_are_not_compared():
    gb, gf = sf.add(FP32, 0x3F800000, 0x3F800001, sf.RND_RNE)       # inexact
    assert gf == sf.FLAG_INEXACT
    word = "%08x" % gb
    c = ucb.parse_line(f"adds n eq - 3f800000 3f800001 {word}", "t")       # says: no flags
    assert ibm.judge(c, gb, gf, gb, gf) == (
        "libcft = golden, IBM expects otherwise: flags x")
    c = ucb.parse_line(f"adds n eq ?x 3f800000 3f800001 {word}", "t")      # inexact unchecked
    assert ibm.judge(c, gb, gf, gb, gf) is None
    c = ucb.parse_line(f"adds n eq x 3f800000 3f800001 {word}", "t")       # says: inexact
    assert ibm.judge(c, gb, gf, gb, gf) is None
    # a zero of either sign satisfies eqz, but not eq
    z = ucb.parse_line("subs n eqz - 3f800000 3f800000 80000000", "t")
    assert ibm.judge(z, 0x00000000, 0, 0x00000000, 0) is None
    z = ucb.parse_line("subs n eq - 3f800000 3f800000 80000000", "t")
    assert ibm.judge(z, 0x00000000, 0, 0x00000000, 0) is not None


# ---- TestFloat: the run table, and the reading back of an error line ------

def test_the_pipeline_table_is_the_212_the_level_one_run_made():
    rows = xtf.function_table()
    pipelines = [(fn, m, x) for fn, modes, exacts in rows
                 for m in modes for x in exacts]
    assert len(pipelines) == 212
    assert len({p for p in pipelines}) == 212
    assert not any("_r_minMag" in fn for fn, _, _ in pipelines)
    names = {fn for fn, _, _ in pipelines}
    for f in ("f32", "f64"):
        for op in ("add", "sub", "mul", "mulAdd", "div", "sqrt", "rem",
                   "roundToInt", "eq", "le", "lt", "eq_signaling",
                   "le_quiet", "lt_quiet"):
            assert f"{f}_{op}" in names
        for i in ("ui32", "ui64", "i32", "i64"):
            assert f"{f}_to_{i}" in names and f"{i}_to_{f}" in names
    # only roundToInt and the conversions to integer have an exact variant
    for fn, modes, exacts in rows:
        assert (len(exacts) == 2) == (fn.endswith("roundToInt")
                                       or (fn.startswith(("f32_to_", "f64_to_"))
                                           and fn[7:] in ("ui32", "ui64", "i32", "i64")))
    # mulAdd at level 2 is refused without a limit: 2 * 1936^3 cases a mode


def test_the_binary128_table_and_its_error_lines():
    rows = xtf.function_table(wide=True)
    pipelines = [(fn, m, x) for fn, modes, exacts in rows
                 for m in modes for x in exacts]
    assert len(pipelines) == 103 and len(set(pipelines)) == 103
    assert all("f128" in fn for fn, _, _ in pipelines)
    assert not any(fn.startswith(("f32_", "f64_")) and "f128" not in fn
                   for fn, _, _ in pipelines)
    # the display: a sign, four hex digits of exponent, a point, 28 of fraction
    assert xtf.decode_value("+3FFF.0000000000000000000000000000", "f128") == 0x3FFF << 112
    assert xtf.decode_value("-7FFF.8000000000000000000000000000", "f128") == \
        (1 << 127) | (0x7FFF << 112) | (1 << 111)
    assert xtf.is_nan("f128", (0x7FFF << 112) | 1)
    assert not xtf.is_nan("f128", 0x7FFF << 112)
    assert xtf.kinds_for("f128_to_f32") == (["f128", "f32"], 1)
    assert xtf.kinds_for("ui64_to_f128") == (["int", "f128"], 1)
    assert xtf.kinds_for("f64_to_f128") == (["f64", "f128"], 1)

    def show(b):
        return "%s%04X.%028X" % ("-" if b >> 127 else "+", (b >> 112) & 0x7FFF,
                                 b & ((1 << 112) - 1))
    zero, inf, qnan = 0, 0x7FFF << 112, (0x7FFF << 112) | (1 << 111)
    line = (f"{show(zero)}  {show(inf)}  {show(qnan)}\n\t=> {show(qnan)} .....  "
            f"expected {show((1 << 127) | qnan)} v....")
    cls = xtf.classify_error("f128_mulAdd", "near_even", False, line)
    assert cls == ("libcft = golden, SoftFloat differs",
                   "f128_mulAdd: NaN bits, flag invalid; product 0*inf, quiet-NaN addend")


def test_error_lines_are_read_back_to_the_bits_they_printed():
    assert xtf.decode_value("+7F.000000", "f32") == 0x3F800000
    assert xtf.decode_value("-FF.400000", "f32") == 0xFFC00000
    assert xtf.decode_value("+3FF.0000000000000", "f64") == 0x3FF0000000000000
    assert xtf.decode_value("-7FF.8000000000000", "f64") == 0xFFF8000000000000
    assert xtf.decode_value("00000042", "int") == 0x42
    assert xtf.decode_value("1", "bool") == 1
    text = ("Errors found in f32_mulAdd, rounding near_even, tininess after rounding:\n"
            "+00.000000  +FF.000000  +FF.7FFFFF\n"
            "\t=> +FF.400000 .....  expected -FF.400000 v....\n"
            "+01.000000  +7F.000000  +7F.000000\n"
            "\t=> +80.000000 .....  expected +80.000001 ....x\n")
    lines = xtf.split_error_lines(text)
    assert len(lines) == 2 and "=>" in lines[0]
    kinds, n = xtf.kinds_for("f32_mulAdd")
    ops, ov, ofl, ev, efl = xtf.parse_error(lines[0], n, kinds)
    assert ops == [0x00000000, 0x7F800000, 0x7FFFFFFF]
    assert (ov, ofl, ev, efl) == (0x7FC00000, 0, 0xFFC00000, 1)


def test_the_fma_row_is_recognised_by_its_operands_not_assumed():
    q32, s32 = 0x7FC00000, 0x7F800001
    yes = xtf.fma_inf_zero_qnan
    assert yes("f32", (0x00000000, 0x7F800000, q32))          # 0 * inf + qNaN
    assert yes("f32", (0xFF800000, 0x80000000, 0xFFC00001))   # -inf * -0 + a signed qNaN
    assert not yes("f32", (0x00000000, 0x7F800000, s32))      # a signaling addend: both raise invalid
    assert not yes("f32", (0x00000000, 0x3F800000, q32))      # 0 * 1 + qNaN: no row
    assert not yes("f32", (0x7F800000, 0x7F800000, q32))      # inf * inf: no row
    assert yes("f64", (0x0000000000000000, 0x7FF0000000000000, 0x7FF8000000000000))
    assert not yes("f64", (0x0000000000000001, 0x7FF0000000000000, 0x7FF8000000000000))


def test_nan_bits_are_compared_only_when_asked():
    assert xtf.same_value("f32", 0x7FC00000, 0xFFC00000)       # NaN against NaN
    assert not xtf.same_value("f32", 0x7FC00000, 0x7F800000)   # NaN against infinity
    assert not xtf.same_value("f32", 0x3F800000, 0x3F800001)
    assert xtf.same_value("int", 5, 5) and not xtf.same_value("int", 5, 6)


def _show32(bits):
    return "%s%02X.%06X" % ("-" if bits >> 31 else "+", (bits >> 23) & 0xFF, bits & 0x7FFFFF)


def _line(ops, obs, ofl, exp, efl):
    head = "  ".join(_show32(o) for o in ops)
    sep = "\n\t" if len(ops) == 3 else "  "
    return f"{head}{sep}=> {_show32(obs)} {ofl}  expected {_show32(exp)} {efl}"


def test_a_disagreement_is_filed_under_the_right_class():
    # 1.0 + 1.0, which golden says is 2.0 with no flag
    one, two = 0x3F800000, 0x40000000
    # (1) libcft = golden, SoftFloat odd: the fma row, 0 * inf + qNaN
    line = _line([0, 0x7F800000, 0x7FFFFFFF], 0x7FC00000, ".....", 0xFFC00000, "v....")
    cls = xtf.classify_error("f32_mulAdd", "near_even", False, line)
    assert cls == ("libcft = golden, SoftFloat differs",
                   "f32_mulAdd: NaN bits, flag invalid; product 0*inf, quiet-NaN addend")
    # (2) a planted libcft defect: libcft's sum is one ulp off, SoftFloat has golden's
    line = _line([one, one], two + 1, ".....", two, ".....")
    cls = xtf.classify_error("f32_add", "near_even", False, line)
    assert cls[0].startswith("LIBCFT DEFECT")
    # (2b) the same through the flags alone
    line = _line([one, one], two, "....x", two, ".....")
    assert xtf.classify_error("f32_add", "near_even", False, line)[0].startswith("LIBCFT DEFECT")
    # (3) all three differ
    line = _line([one, one], two + 1, ".....", two + 2, ".....")
    assert xtf.classify_error("f32_add", "near_even", False, line)[0] == "all three differ"
    # (4) the error line is no error
    line = _line([one, one], two, ".....", two, ".....")
    assert xtf.classify_error("f32_add", "near_even", False, line)[0].startswith("both agree")
    # (5) the tininess row: 2^-126 (1 + 2^-23) times (1 - 2^-23) rounded to nearest.
    # libcft (after rounding) raises inexact alone; a SoftFloat told -tininessbefore
    # adds underflow
    line = _line([0x00800001, 0x3F7FFFFE], 0x00800000, "....x", 0x00800000, "...ux")
    cls = xtf.classify_error("f32_mul", "near_even", False, line)
    assert cls == ("libcft = golden, SoftFloat differs", "f32_mul: flags only, flag underflow")
    # (6) -checkNaNs: a NaN's bits are held to golden's
    line = _line([0, 0x7F800000, 0x7FFFFFFF], 0x7FC00000, ".....", 0xFFC00000, "v....")
    assert xtf.classify_error("f32_mulAdd", "near_even", False, line,
                              nan_bits=True)[0] == "libcft = golden, SoftFloat differs"


def test_the_golden_functions_agree_with_the_model_they_wrap():
    g = xtf.golden_for("f32_add", "near_even", False)
    assert g(0x3F800000, 0x3F800000) == sf.add(FP32, 0x3F800000, 0x3F800000, sf.RND_RNE)
    g = xtf.golden_for("f32_to_i32", "minMag", True)
    # 2.5 toward zero is 2, inexact (the exact variant)
    assert g(0x40200000) == (2, sf.FLAG_INEXACT)
    g = xtf.golden_for("f32_to_ui32", "near_even", False)
    # a negative number rounds below zero: invalid, the minimum 0 (the contract's table)
    assert g(0xBF800000) == (0, sf.FLAG_INVALID)
    g = xtf.golden_for("i32_to_f32", "near_even", False)
    assert g(0xFFFFFFFF) == sf.from_int(FP32, -1, sf.RND_RNE)   # TestFloat prints i32 two's complement
    assert xtf.golden_for("f32_eq", "near_even", False)(0x3F800000, 0x3F800000)[0] != 0
    assert xtf.golden_for("f16_add", "near_even", False) is None


# ---- the orchestrator's health check ---------------------------------------

class _Done:
    def __init__(self, stdout):
        self.stdout, self.stderr = stdout, ""


def _fake_shell(statuses, ver_err, ver_out="Errors found in f32_add.\n"):
    """What subprocess.run gives run_one in place of the shell: the two files
    the script redirects the verifier to (named in the script text) written,
    and the pipeline's exit statuses printed as `echo ${PIPESTATUS[@]}` does."""
    def run(cmd, **kwargs):
        m = re.search(r"> '([^']*)' 2> '([^']*)'\n", cmd[2])
        Path(m.group(1)).write_text(ver_out)
        Path(m.group(2)).write_text(ver_err)
        return _Done(statuses + "\n")
    return run


@pytest.mark.parametrize("statuses, limit, err, ok, tests, errs", [
    ("0 0 0", 0, "46464 tests performed.\n", True, 46464, 0),
    ("0 0 1", 0, "46464 tests performed; 40 errors found.\n", True, 46464, 40),
    ("0 0 1", 0, "46464 tests performed; 1 error found.\n", True, 46464, 1),
    ("141 0 0 0", 5, "5 tests performed.\n", True, 5, 0),          # head closed the generator on purpose
    ("0 0 0 0", 5, "5 tests performed.\n", True, 5, 0),
    ("0 2 0", 0, "46464 tests performed.\n", False, 46464, 0),      # the subject refused or died
    ("0 0 2", 0, "46464 tests performed.\n", False, 46464, 0),      # the verifier itself failed
    ("141 0 0", 0, "46464 tests performed.\n", False, 46464, 0),    # the generator cut off, none asked
    ("0 0", 0, "46464 tests performed.\n", False, 46464, 0),        # a process missing
    ("0 0 0 0", 0, "46464 tests performed.\n", False, 46464, 0),    # one too many
    ("0 0 0", 0, "the verifier said nothing\n", False, -1, -1),     # no count line at all
    ("141 0 2 0", 5, "5 tests performed.\n", False, 5, 0),          # the subject died behind a cut generator
])
def test_a_pipeline_is_healthy_only_when_every_process_ended_as_it_should(
        statuses, limit, err, ok, tests, errs, tmp_path, monkeypatch):
    (tmp_path / "errors").mkdir()
    monkeypatch.setattr(xtf.subprocess, "run", _fake_shell(statuses, err))
    row = xtf.run_one("TF", "SUBJECT", str(tmp_path), "f32_add", "near_even", False, 1, limit, "", "after")
    assert row[:6] == (1, "f32_add", "near_even", "notexact", tests, errs)
    assert row[-1] == ("ok" if ok else "BAD")
    kept = sorted(p.name for p in (tmp_path / "errors").iterdir())
    # a clean healthy run leaves nothing behind; one with errors, or one not
    # healthy, keeps both files for the arbitration to read
    clean = ok and errs == 0
    assert kept == ([] if clean else ["L1.f32_add.near_even.n.err", "L1.f32_add.near_even.n.out"])


# ---- the fetch-and-verify script ------------------------------------------

def _manifest(files):
    return tuple((rel, hashlib.sha256(data).hexdigest(), len(data), "https://example.invalid/" + rel)
                 for rel, data in files.items())


def test_the_fetch_table_is_the_eleven_files_and_well_formed():
    rels = [m[0] for m in fx.MANIFEST]
    assert len(rels) == len(set(rels)) == 11
    assert sorted(r for r in rels if not r.startswith("ibm-fptest/")) == [
        "softfloat-3e/SoftFloat-3e.zip", "testfloat-3e/TestFloat-3e.zip", "ucbtest/ucbtest.tgz"]
    assert sum(r.startswith("ibm-fptest/") for r in rels) == 8
    for rel, sha, size, url in fx.MANIFEST:
        assert len(sha) == 64 and set(sha) <= set("0123456789abcdef")
        assert size > 0 and url.startswith("https://") and not rel.startswith(("/", ".."))
        assert ".." not in rel.split("/")


def test_fetch_accepts_what_matches_and_refuses_and_withholds_what_does_not(tmp_path, monkeypatch):
    # no network under any circumstance in a test
    def no_network(*a, **k):
        raise AssertionError("a test touched the network")
    monkeypatch.setattr(fx.urllib.request, "urlopen", no_network)
    files = {"d1/a.bin": b"alpha" * 100, "d1/b.bin": b"beta" * 50, "d2/c.txt": b"gamma\n"}
    table = _manifest(files)
    served = dict((m[3], files[m[0]]) for m in table)
    # a clean fetch writes all three
    out = []
    refused = fx.fetch_all(str(tmp_path / "clean"), table, lambda u, n: served[u], out.append)
    assert refused == []
    for rel, data in files.items():
        assert (tmp_path / "clean" / rel).read_bytes() == data
    # one corrupted by a single bit: refused, named, NOT written; the others are
    bad = dict(served)
    url_b = table[1][3]
    bad[url_b] = bytes([bad[url_b][0] ^ 1]) + bad[url_b][1:]
    out = []
    refused = fx.fetch_all(str(tmp_path / "bad"), table, lambda u, n: bad[u], out.append)
    assert [r[0] for r in refused] == ["d1/b.bin"] and "sha256" in refused[0][1]
    assert not (tmp_path / "bad" / "d1" / "b.bin").exists()
    assert not (tmp_path / "bad" / "d1" / "b.bin.part").exists()
    assert (tmp_path / "bad" / "d1" / "a.bin").exists() and (tmp_path / "bad" / "d2" / "c.txt").exists()
    assert any(o.startswith("REFUSED d1/b.bin") for o in out)
    # a short body, and a fetcher that raises, are refusals too
    short = dict(served)
    short[table[0][3]] = short[table[0][3]][:-1]
    refused = fx.fetch_all(str(tmp_path / "short"), table, lambda u, n: short[u], lambda s: None)
    assert [r[0] for r in refused] == ["d1/a.bin"] and "bytes" in refused[0][1]

    def boom(u, n):
        raise OSError("connection refused")
    refused = fx.fetch_all(str(tmp_path / "boom"), table, boom, lambda s: None)
    assert len(refused) == 3 and "OSError" in refused[0][1]


def test_fetch_never_overwrites(tmp_path):
    (tmp_path / "taken").mkdir()
    (tmp_path / "taken" / "x").write_bytes(b"mine")
    with pytest.raises(SystemExit):
        fx.fetch_all(str(tmp_path / "taken"), (), lambda u, n: b"", lambda s: None)
    assert (tmp_path / "taken" / "x").read_bytes() == b"mine"
    (tmp_path / "empty").mkdir()
    assert fx.fetch_all(str(tmp_path / "empty"), (), lambda u, n: b"", lambda s: None) == []


def test_fetch_refuses_to_run_in_a_test_a_stage_or_ci(tmp_path, monkeypatch):
    # we are inside pytest right now: PYTEST_CURRENT_TEST is set (CI may be
    # too, on a hosted runner: take those out so the one under test shows)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert fx.refusal() == "PYTEST_CURRENT_TEST"
    dest = tmp_path / "never"
    assert fx.main([str(dest)]) == 2
    assert not dest.exists()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    for var in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv("CI", raising=False)
        monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
        monkeypatch.setenv(var, "true")
        assert fx.refusal() == var
        assert fx.main([str(dest)]) == 2
        assert not dest.exists()
    # unset, the refusal lifts (nothing is fetched here: the guard is all we ask)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert fx.refusal() is None


def test_nothing_in_a_stage_a_workflow_or_another_test_runs_the_fetch_script():
    root = Path(__file__).resolve().parents[2]
    scanned = [root / "verify" / "run.sh", root / "Makefile",
               root / "host" / "Makefile", root / "tb" / "Makefile"]
    scanned += sorted((root / ".github" / "workflows").glob("*.yml"))
    scanned += [p for p in sorted((root / "python" / "tests").glob("*.py"))
                if p.name != Path(__file__).name]
    scanned += sorted((root / "host" / "tests").glob("*"))
    present = [p for p in scanned if p.is_file()]
    assert len(present) > 20          # the scan did look at the tree
    hits = [str(p.relative_to(root)) for p in present
            if "fetch_external" in p.read_text(encoding="utf-8", errors="replace")]
    assert hits == []


def test_verify_and_the_manifest_comparison_read_local_files_only(tmp_path):
    files = {"x/one": b"1" * 10, "y/two": b"2" * 20}
    table = _manifest(files)
    for rel, data in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
    assert fx.verify_dir(str(tmp_path), table, lambda s: None) == []
    (tmp_path / "y" / "two").write_bytes(b"2" * 19 + b"3")
    bad = fx.verify_dir(str(tmp_path), table, lambda s: None)
    assert [b[0] for b in bad] == ["y/two"]
    (tmp_path / "x" / "one").unlink()
    assert [b[0] for b in fx.verify_dir(str(tmp_path), table, lambda s: None)] == ["x/one", "y/two"]
    text = "intro\n" + "\n".join(f"{m[1]}  {m[2]}  {m[0]}" for m in table) + "\nSources:\n"
    assert fx.compare_manifest(text, table) == []
    swapped = text.replace(table[0][1], "0" * 64)
    assert len(fx.compare_manifest(swapped, table)) == 1
    assert len(fx.compare_manifest(text, table[:1])) == 1
