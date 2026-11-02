# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""sin, cos and tan in the language (parcel M2L, M2's build, 2026-11-02;
docs/studies/M2-trig.md, sections 6 and 7; docs/LANGUAGE.md).

Golden-first, as M1's six were (test_lang.py's test_m1_*, test_lang_tangent
.py's test_m1_*): the nodes, the folds and refusals, the exact evaluation,
the two renderers, and the three derivative rules. Here:

  the nodes        sin, cos and tan directly after log2 and before neg in
                   lang.OPS (the place is byte-relevant: the canonical
                   form's "; operations:" line counts nodes in OPS's
                   order, and cftc's ir.ARITY mirrors it); the IR form;
                   `transcendental` still refused for the other 26
  the golden       a lane's result is transcend.compute's for the node's
  functions        own name under the program's attribute, bits and flags
  the folds        sin(0) and tan(0) are 0 and cos(0) is 1, of a constant
                   exactly 0 only; every other constant is refused
                   `irrational-constant` with its reason; a function of h
                   is `h-nonlinear`; and no constant division by zero
  the exact        exact at 0, mpmath's at 1,024 bits elsewhere, the
  evaluation       reader of lang_mathform.py taking the same value
  the renderers    sin(x), cos(x) and tan(x) in both forms, read back
  the rules        `cos(a) * da`, `(-sin(a)) * da` and `fma(r, r, 1) *
                   da`, each rendered on a one-operation system and held
                   to the document's table; their node shapes (the
                   contract between parcels M2L and M2C); the derivative
                   by exact dual numbers and by a central difference at
                   2^-256 of 1,024-bit values; each rule's rounding bit for
                   bit at every format and attribute; the specials
  the plants       each rule made wrong; cos's and tan's rounded
                   otherwise - cos's red under rdn and rup only, where its
                   two forms differ; sin's golden function swapped for
                   cos's
  mpmath           needed only by a graph holding the three

The compiled forms are parcel M2C's (test_cftc_trig.py); on a branch with
this file alone, cftc does not carry the three.
"""

import functools
import json
import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from cft_golden import FORMATS, cert2, lang, transcend  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.lang import check as lang_check  # noqa: E402
from cft_golden.lang import constants as C  # noqa: E402
from cft_golden.lang import graph as lang_graph  # noqa: E402
from cft_golden.lang import interp as lang_interp  # noqa: E402
from cft_golden.lang import tangent as lang_tangent  # noqa: E402
from cft_golden.lang.graph import Node  # noqa: E402
from lang_mathform import MathForm  # noqa: E402
from lang_mathform import transcendental as T9  # noqa: E402
import test_lang as TL  # noqa: E402
import test_lang_tangent as TT  # noqa: E402

F = Fraction
THREE = ("sin", "cos", "tan")
RNDS = ("rne", "rtz", "rdn", "rup", "rmm")
DOC = REPO / "docs" / "LANGUAGE.md"
needs_mpmath = TL.needs_mpmath
compile_ = TL.compile_
_sys1 = TL._sys1
SYSTEMS = REPO / "programs" / "systems"


# ---- the nodes -------------------------------------------------------------

def test_the_three_are_nodes_between_log2_and_neg():
    """Named as transcend.py names them, each of one operand, directly
    after log2 and before neg in lang.OPS, in the order sin, cos, tan -
    the place M2C's ir.ARITY mirrors and the canonical form's operations
    line counts by - and in graph.TRANSCEND, which puts them in ROUNDED and
    in the interpreter's table."""
    ops = list(lang.OPS)
    k = ops.index("log2")
    assert ops[k + 1:k + 5] == ["sin", "cos", "tan", "neg"]
    assert ops[:k + 1] == ["fma", "add", "sub", "mul", "div", "sqrt", "exp",
                           "expm1", "exp2", "log", "log1p", "log2"]
    assert lang_graph.TRANSCEND == ("exp", "expm1", "exp2", "log", "log1p",
                                    "log2", "sin", "cos", "tan")
    for fn in THREE:
        assert fn in transcend.TRANSCEND_FNS and lang.OPS[fn] == 1
        assert fn in lang_graph.ROUNDED
        assert transcend.TRANSCEND_ARITY[fn] == 1
    fmt = FORMATS["fp64"]
    table = lang_interp._ops(fmt, sf.RND_RNE)
    assert set(table) == set(lang.OPS)
    assert not set(THREE) & lang_check.TRANSCENDENTAL
    assert {fn for fn in THREE if fn in lang_check.BUILTINS} == set(THREE)
    for fn in THREE:
        g = compile_(_sys1(f"next x = {fn}(x)\nnext y = {fn}(x * y)"))
        assert g.step.nodes == [(fn, ("s0",), None),
                                ("mul", ("s0", "s1"), None),
                                (fn, ("n1",), None)]
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next x = {fn}(x, y)\nnext y = y"))
        assert (info.value.name, info.value.line) == ("arity", 5)
        assert info.value.sentence == f"{fn} takes 1 argument, and 2 are given"
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next {fn} = 1", state=fn))
        assert info.value.name == "reserved-name"
        assert "a built-in" in info.value.sentence
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next x = x * {fn}", state="x"))
        assert info.value.name == "syntax"


def test_the_graph_bytes_write_the_three():
    """The IR form of a node is [op, [ref], label or null], as every
    node's is; a graph without the three writes what it wrote before; and
    the canonical form's operations line counts the nodes in OPS's order,
    after log2's and before neg's."""
    g = compile_(_sys1("next x = sin(y) + cos(x) * tan(y)\nnext y = -x"))
    data = g.to_bytes().decode("ascii")
    for line in ('["sin",["s1"],null]', '["cos",["s0"],null]',
                 '["tan",["s1"],null]'):
        assert line in data
    nodes = json.loads(data.split('"step":', 1)[1].rsplit("}", 1)[0]
                       .split('"tangent"')[0].rstrip(",\n"))["nodes"]
    assert [n[0] for n in nodes] == ["sin", "cos", "tan", "mul", "add", "neg"]
    canon = lang.render_canonical(g)
    assert ("; operations: a step 6 (1 add, 1 mul, 1 sin, 1 cos, 1 tan, "
            "1 neg)") in canon
    plain = compile_(_sys1("next x = exp(y) + log2(x)\nnext y = -x"))
    assert plain.to_bytes().decode("ascii").count('"sin"') == 0
    assert "(1 add, 1 exp, 1 log2, 1 neg)" in lang.render_canonical(plain)


def test_transcendental_is_still_raised_for_the_other_26():
    """sin, cos and tan left the reserved list; the other 26 stay on it,
    refused `transcendental` at run time and `irrational-constant` of a
    constant, for the rounds after M2."""
    rest = {"exp10", "log10", "pow", "pown", "powr", "rootn", "hypot",
            "sinpi", "cospi", "tanpi", "asin", "acos", "atan", "atan2",
            "asinpi", "acospi", "atanpi", "atan2pi", "sinh", "cosh", "tanh",
            "asinh", "acosh", "atanh", "cbrt", "rsqrt"}
    assert len(rest) == 26 and set(lang_check.TRANSCENDENTAL) == rest
    for name in sorted(rest):
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next x = {name}(x)", state="x"))
        assert (info.value.name, info.value.line) == ("transcendental", 5)
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next x = x * {name}(1)", state="x"))
        assert info.value.name == "irrational-constant"


# ---- the golden functions ---------------------------------------------------

def golden_misses(fn, fmtname, rnd, rng, extra=6):
    """(lanes, lanes where the interpreter's y = fn(x) is not
    transcend.compute's bits, whether the run's FLAGS are the lanes' OR)."""
    fmt = FORMATS[fmtname]
    code = C.RND_BY_NAME[rnd]
    lanes = TL._m1_lanes(fmt, rng, extra)
    g = compile_(_sys1(f"next x = {fn}(x)", state="x", fmt=fmtname, rnd=rnd))
    run = lang.run(g, [[x] for x in lanes], 1)
    union = bad = 0
    for x, out in zip(lanes, run.states):
        bits, flags = transcend.compute(fmt, fn, x, 0, code)
        bad += out != [bits]
        union |= flags
    return len(lanes), bad, run.flags == union


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_the_golden_functions_are_transcends(fmtname):
    """Through the interpreter, under every attribute: each lane's result
    is transcend.compute's for the node's own name under the program's
    attribute, its flags each lane's own, and the run's FLAGS their OR -
    the specials, the edges and ordinary arguments among the lanes."""
    rng = random.Random(f"m2 golden {fmtname}")
    for fn in THREE:
        for rnd in RNDS:
            n, bad, flags_ok = golden_misses(fn, fmtname, rnd, rng)
            assert n == 25 and bad == 0 and flags_ok, (fn, rnd)
    fmt = FORMATS[fmtname]
    # a lane at +-0 and at +-inf, bit for bit: sin(-0) = -0, cos(0) = 1,
    # tan(-0) = -0, and at an infinity an invalid NaN
    for fn, at_zero in (("sin", 0), ("cos", C.round_once(
            fmt, sf.RND_RNE, F(1))[0]), ("tan", 0)):
        g = compile_(_sys1(f"next x = {fn}(x)", state="x", fmt=fmtname))
        run = lang.run(g, [[0], [fmt.sign_mask], [sf.inf_bits(fmt)]], 1)
        assert run.states[0] == [at_zero]
        assert run.states[1] == [at_zero if fn == "cos"
                                 else fmt.sign_mask]
        assert run.states[2] == [sf.qnan_bits(fmt)]
        assert run.flags == sf.FLAG_INVALID


# ---- the folds and the refusals --------------------------------------------

# A fold is the exact rational value, rounded once where it meets the run.
FOLDS = [("sin(0)", F(0)), ("cos(0)", F(1)), ("tan(0)", F(0)),
         ("sin(1 - 1)", F(0)), ("cos(2 * 0)", F(1)), ("tan(0 / 3)", F(0)),
         ("cos(sin(0))", F(1)), ("sin(cos(0) - 1)", F(0)),
         ("cos(tan(0 * 8))", F(1))]


@pytest.mark.parametrize("expr,value", FOLDS)
def test_the_three_fold_at_exactly_zero(expr, value):
    """sin(0) = tan(0) = 0 and cos(0) = 1, of a constant exactly 0: a
    constant, exactly, rounded once at every format under every attribute,
    in a const and in a default too (Logan's answer 8 to the M2 study)."""
    for fmtname in FORMATS:
        fmt = FORMATS[fmtname]
        for rnd in RNDS:
            g = compile_(_sys1(f"next x = x + {expr}", state="x",
                               fmt=fmtname, rnd=rnd))
            assert g.step.nodes == [("add", ("s0", "c0"), None)]
            assert g.const == [(value, None)
                               + C.round_once(fmt, C.RND_BY_NAME[rnd], value)]
    g = compile_(_sys1(f"const k = {expr}\nparam p = {expr} + 1\n"
                       f"next x = x + k * p", state="x"))
    assert g.param[0][1] == value + 1


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_a_fold_is_the_run_time_value_at_zero(fmtname):
    """The folded constant is what the node computes at +0, bits and
    flags (no flag: the three are exact at 0): the language folds only
    where the answer is the golden function's own."""
    fmt = FORMATS[fmtname]
    for fn, value in (("sin", F(0)), ("cos", F(1)), ("tan", F(0))):
        for rnd in RNDS:
            bits, flags = transcend.compute(fmt, fn, 0, 0, C.RND_BY_NAME[rnd])
            assert (bits, flags) == (C.round_once(fmt, C.RND_BY_NAME[rnd],
                                                  value)[0], 0), (fn, rnd)


# Every refusal of the three, by name, with the name the same source met at
# 19de866c, before M2's build (each measured there, by compiling it under
# that commit's python/): (body, step, name, line, the name before).
M2_REFUSALS = [
    # a nonzero rational: refused before and refused still, the sentence
    # now saying why
    ("next x = x * sin(1)", "step map", "irrational-constant", 5,
     "irrational-constant"),
    ("next x = x * cos(1/2)", "step map", "irrational-constant", 5,
     "irrational-constant"),
    ("next x = x * tan(-3)", "step map", "irrational-constant", 5,
     "irrational-constant"),
    ("next x = x * sin(0.5)", "step map", "irrational-constant", 5,
     "irrational-constant"),
    ("next x = x * tan(1/3)", "step map", "irrational-constant", 5,
     "irrational-constant"),
    ("next x = x * sin(1e30)", "step map", "irrational-constant", 5,
     "irrational-constant"),
    ("next x = x * cos(1e-300)", "step map", "irrational-constant", 5,
     "irrational-constant"),
    # h: a function of a constant that changes with h's size
    ("next x = x * sin(h)", "step map, h = 1/8", "h-nonlinear", 5,
     "irrational-constant"),
    ("next x = x * cos(2 * h)", "step map, h = 1/8", "h-nonlinear", 5,
     "irrational-constant"),
    ("next x = x * tan(h * h)", "step map, h = 1/8", "h-nonlinear", 5,
     "irrational-constant"),
    ("d/dt x = x * sin(h)", "step euler, h = 1/8", "h-scope", 5, "h-scope"),
    # sin(0 * h) folds, and h is then used by nothing
    ("next x = x * sin(0 * h)", "step map, h = 1/8", "unused", 6,
     "irrational-constant"),
    # an argument count is checked now that the name is a built-in
    ("next x = sin(x, x)", "step map", "arity", 5, "transcendental"),
    ("next x = cos()", "step map", "arity", 5, "transcendental"),
    # unchanged in name
    ("next x = x * tan", "step map", "syntax", 5, "syntax"),
    ("next x = x * sin(1/0)", "step map", "constant-division-by-zero", 5,
     "constant-division-by-zero"),
    ("next x = x * cos(inf)", "step map", "constant-infinity", 5,
     "constant-infinity"),
    ("next x = x * tan(nan)", "step map", "constant-nan", 5, "constant-nan"),
    ("next x = x * sin(-0)", "step map", "constant-negative-zero", 5,
     "constant-negative-zero"),
    # the reserved name that took sin's place as the example
    ("next x = sinh(x)", "step map", "transcendental", 5, "transcendental"),
    ("next x = x * sinh(0)", "step map", "irrational-constant", 5,
     "irrational-constant"),
]

# What 19de866c refused and this tree accepts (the same measurement): the
# operation as a node, and the folds at zero.
M2_ACCEPTED = [
    ("next x = sin(x)", "transcendental"), ("next x = cos(x)", "transcendental"),
    ("next x = tan(x)", "transcendental"),
    ("next x = x * sin(0)", "irrational-constant"),
    ("next x = x * cos(0)", "irrational-constant"),
    ("next x = x * tan(0)", "irrational-constant"),
    ("next x = x * sin(1 - 1)", "irrational-constant"),
    ("next x = x * cos(0 * 5)", "irrational-constant"),
    ("next x = sin(x) + cos(x) * tan(x)", "transcendental"),
]


@pytest.mark.parametrize("body,step,name,line,before", M2_REFUSALS,
                         ids=[r[0][9:] + "|" + r[1] for r in M2_REFUSALS])
def test_m2_each_refusal_by_name(body, step, name, line, before):
    """Each by its name and line; where it was refused another way before
    M2's build, the table says which, and the sentence is the new name's.
    A constant of the three is never `constant-division-by-zero`: no
    constant is a pole of tan (pi/2 is irrational)."""
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys1(body, state="x", step=step), "m2.cftl")
    r = info.value
    assert (r.name, r.line, r.source) == (name, line, "m2.cftl"), str(r)
    assert r.sentence and name in lang.CATALOGUE and before in lang.CATALOGUE
    if name == "irrational-constant" and "sinh" not in body:
        assert "Hermite-Lindemann" in r.sentence, r.sentence
        assert "write its value as a decimal or a/b" in r.sentence
    if body.startswith("next x = x * ") and "(1/0)" not in body \
            and name != "constant-division-by-zero":
        assert name != "constant-division-by-zero"


@pytest.mark.parametrize("body,before", M2_ACCEPTED,
                         ids=[r[0][9:] for r in M2_ACCEPTED])
def test_m2_what_was_refused_is_accepted(body, before):
    g = compile_(_sys1(body, state="x"))
    assert before in lang.CATALOGUE
    assert g.step.nodes


def test_a_nonzero_constant_is_refused_with_its_reason():
    """Every nonzero rational in a spread of sizes and signs, for each of
    the three: `irrational-constant` at the source line, the sentence
    naming the function, the constant, the function's word (sine, cosine,
    tangent) and the theorem - never `constant-division-by-zero`, since no
    rational is a pole of tan."""
    word = {"sin": "sine", "cos": "cosine", "tan": "tangent"}
    rng = random.Random("m2 refusals")
    values = ["1", "-1", "2", "1/2", "-1/3", "7/5", "100", "0.001", "1e10",
              "-1e-10", "355/113", "1e300", "(22/7)"]
    values += [f"{rng.randint(-999, 999) or 1}/{rng.randint(1, 99)}"
               for _ in range(20)]
    for fn in THREE:
        for v in values:
            with pytest.raises(lang.Refusal) as info:
                compile_(_sys1(f"next x = x * {fn}({v})", state="x"))
            r = info.value
            assert (r.name, r.line) == ("irrational-constant", 5), (fn, v)
            assert r.sentence.startswith(f"{fn}(") and "is irrational" in \
                r.sentence
            assert f"the {word[fn]} of a nonzero rational is transcendental" \
                in r.sentence and "Hermite-Lindemann" in r.sentence
    # tan's reason is its own: e^(2ic) = (1 + ia)/(1 - ia)
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys1("next x = x * tan(1)", state="x"))
    assert "(1 + ia)/(1 - ia)" in info.value.sentence
    # the exact zeros are the only folds: no constant but 0 reaches one
    for fn in THREE:
        assert compile_(_sys1(f"next x = x * {fn}(0)", state="x")).const


# ---- the exact evaluation ---------------------------------------------------

@needs_mpmath
def test_the_exact_evaluation_of_the_three_is_one_function():
    """The step graph's exact evaluation and the test's own reader take the
    same value of each of the three at the same argument: exact at 0 - 0, 1
    and 0 - and otherwise mpmath's at 1,024 bits of the argument rounded to
    nearest at 1,024 bits. Each is within 2^-1000 of the function of that
    rounded argument, relatively (mpmath at 1,200 bits) - the argument's own
    rounding, 2^-1024 relatively, is the convention, and moves a value at
    2^40 by 2^-984 - and sin^2 + cos^2 = 1 and tan = sin / cos hold to the
    same width; an argument of 2^1000 + 1 or of 10^30 needs no limit, and
    the value never raises Undefined."""
    import mpmath
    ctx = mpmath.MPContext()
    ctx.prec = 1200
    lib = mpmath.libmp

    def rounded(q):
        return ctx.make_mpf(lib.from_rational(q.numerator, q.denominator,
                                              1024, lib.round_nearest))
    true = {"sin": ctx.sin, "cos": ctx.cos, "tan": ctx.tan}
    rng = random.Random("m2 transcendentals")
    two = ctx.mpf(2) ** -1000
    qs = [F(rng.randint(-10 ** 6, 10 ** 6), rng.randint(1, 10 ** 4))
          for _ in range(40)]
    qs += [F(1), F(-1), F(355, 113), F(1, 10 ** 30), F(10) ** 30,
           F(2) ** 1000 + 1, F(-3, 2), F(1 << 40, 7)]
    for q in qs:
        v = {}
        for op in THREE:
            a = lang_graph.exact_transcendental(op, q)
            assert isinstance(a, F) and T9(op, q) == a, (op, q)
            want = true[op](rounded(q))
            assert abs((ctx.mpf(a.numerator) / a.denominator - want)
                       / want) < two, (op, q)
            v[op] = a
        assert abs(v["sin"] ** 2 + v["cos"] ** 2 - 1) < F(1, 1 << 1000), q
        assert abs(v["tan"] * v["cos"] - v["sin"]) < F(1, 1 << 1000), q
    exact = lang_graph.exact_transcendental
    assert (exact("sin", F(0)), exact("cos", F(0)), exact("tan", F(0))) == \
        (0, 1, 0)
    assert all(isinstance(exact(op, F(0)), F) for op in THREE)
    # the exact evaluation of a node and of the function agree on a graph
    g = compile_(_sys1("next x = sin(x)\nnext y = cos(y) * tan(x)"))
    point = [F(3, 2), F(-5, 7)]
    got = g.exact_eval("step", point)
    assert got == [exact("sin", point[0]),
                   exact("cos", point[1]) * exact("tan", point[0])]
    # a tangent section reaches the same functions
    gt = compile_(TL._sys1("next x = sin(x)", state="x").replace(
        "state x\n", "state x\ntangent v\n"))
    assert gt.exact_eval("tangent_step", [F(1, 3)], tangent=[F(2)]) == \
        [exact("cos", F(1, 3)) * 2]


# ---- the renderers ----------------------------------------------------------

@needs_mpmath
def test_the_renderers_write_the_three_and_read_back():
    """The canonical form writes each as the generic call; the mathematical
    form as sin(a), cos(a) and tan(a), one operation each; each reads back
    - the canonical form to the same graph, the mathematical form exactly
    at random rational points (each of the three a fixed function of its
    exact argument on both sides), every line held (the three checks)."""
    g = compile_(_sys1("next x = sin(y) + cos(x)\nnext y = tan(x) * sin(x)"))
    canon = lang.render_canonical(g)
    assert "\nnext x = sin(y) + cos(x)\n" in canon
    assert "\nnext y = tan(x) * sin(x)\n" in canon
    math = lang.render_math(g)
    assert "\n  x ↦ sin(y) + cos(x)\n" in math
    assert "\n  y ↦ tan(x)·sin(x)\n" in math
    assert compile_(canon).to_bytes() == g.to_bytes()
    assert TL.check_intention_out(g, random.Random("m2 renderers"), 4) == 4
    form = MathForm(math)
    point = [F(3, 2), F(5, 7)]
    assert form.step(point) == g.exact_eval("step", point)
    # a negation and a quotient around a call keep their brackets
    g = compile_(_sys1("next x = -sin(x) / cos(y)\nnext y = tan(x / y) - 1"))
    math = lang.render_math(g)
    assert "\n  x ↦ (−sin(x))/cos(y)\n" in math
    assert "\n  y ↦ tan(x/y) − 1\n" in math
    TL.check_intention_out(g, random.Random("m2 renderers 2"))


@needs_mpmath
@pytest.mark.parametrize("name", ["pendulum-rk4", "wave-sv", "mixed-map",
                                  "folds-euler"])
def test_intention_out_of_written_systems(name):
    """The three under each integrator, in lets and equations, with Greek
    names, with a tangent vector, and beside folds: the three checks."""
    text = {
        "pendulum-rk4": ("system pendulum\nformat fp128\nround rdn\n"
                         "state theta, omega\ntangent v\n"
                         "param lambda = 1/3\nlet phi = sin(theta)\n"
                         "d/dt theta = omega\n"
                         "d/dt omega = -(lambda * phi) - cos(theta) / 8\n"
                         "step rk4, h = 1/64\n"),
        "wave-sv": ("system wave\nformat fp32\nround rup\nstate q, p\n"
                    "lane param kappa = 3/2\ntangent v, w\n"
                    "d/dt q = p + tan(kappa * p) / 16\n"
                    "d/dt p = -(kappa * sin(q))\n"
                    "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
        "mixed-map": ("system mix\nformat fp256\nround rmm\nstate x, y\n"
                      "next x = sin(abs(x) + 1) * cos(y)\n"
                      "next y = fma(x, tan(y - x), sin(cos(y)))\n"
                      "step map\n"),
        "folds-euler": ("system folds\nformat fp64\nstate x\n"
                        "param sigma = cos(0) + sin(0) + tan(0)\n"
                        "d/dt x = sigma * sin(x) + cos(0)\n"
                        "step euler, h = 1/8\n"),
    }[name]
    g = compile_(text, name)
    assert TL.check_intention_out(g, random.Random(f"m2 io {name}"), 3) > 0


def _m2_expr(rng, operands, depth):
    """_expr's operations and the three, each of an operand that reads a
    value of the run - the state, a param, a lane param or a let - so that
    few fold (a constant's, refused where irrational, is
    test_m2_each_refusal_by_name's)."""
    if depth > 0 and rng.random() < 0.35:
        fn = rng.choice(THREE)
        run = [o for o in operands if o[0] in "splraqm"]
        return f"{fn}({_m2_expr(rng, operands, depth - 1)} * {rng.choice(run)})"
    return TL._expr(rng, operands, depth, sub=_m2_expr)


# A random source with the three may fold to a constant the language refuses
# besides _ARTIFACTS': a fold that overflows or rounds to zero.
_M2_ARTIFACTS = TL._ARTIFACTS | {"constant-range", "constant-overflow",
                                 "constant-rounds-to-zero"}


@needs_mpmath
def test_intention_out_of_random_systems():
    """Random systems with the three beside every other operation - lets,
    params, lane params, arrays, every integrator, format and attribute,
    a third with a tangent vector - each through the three checks."""
    rng = random.Random("lang random m2 systems")
    done = skipped = decided = 0
    ops, kinds, tangents = set(), set(), 0
    while done < 30:
        text = TL.random_system(rng, done + skipped, expr=_m2_expr)
        if done % 3 == 2:
            lines = text.split("\n")
            k = next(i for i, ln in enumerate(lines) if ln.startswith("state"))
            text = "\n".join(lines[:k + 1] + ["tangent v"] + lines[k + 1:])
        try:
            g = compile_(text, f"random-m2-{done + skipped}")
        except lang.Refusal as r:
            assert r.name in _M2_ARTIFACTS, f"{r}\n{text}"
            skipped += 1
            continue
        try:
            decided += TL.check_intention_out(g, rng, points=2)
        except AssertionError:
            raise AssertionError(f"the intention-out fails on:\n{text}")
        ops.update(g.op_counts("step"))
        kinds.add(g.integrator[0])
        tangents += bool(g.tangent)
        done += 1
    assert skipped < done and decided >= 30, (skipped, decided)
    assert set(THREE) <= ops and tangents >= 9
    assert kinds == {"rk4", "euler", "stormer-verlet", "map"}


# ---- the rules ---------------------------------------------------------------

# The test's own copy of docs/LANGUAGE.md's rows for the three: each
# written operation, its tangent as the canonical form writes it, for each
# set of operands whose tangent is nonzero (test_lang_tangent.RULES' form).
# r is the call itself, written again since y's has no name.
RULES3 = [
    ("sin(a)", {"a": "cos(a) * v.a"}),
    ("cos(a)", {"a": "(-sin(a)) * v.a"}),
    ("tan(a)", {"a": "fma(tan(a), tan(a), 1) * v.a"}),
]
DOC_RULES3 = {"`sin(a)`": "`cos(a) * da`", "`cos(a)`": "`(-sin(a)) * da`",
              "`tan(a)`": "`fma(r, r, 1) * da`"}


@pytest.mark.parametrize("expr,cases", RULES3, ids=[r[0] for r in RULES3])
def test_each_rule_as_the_table_writes_it(expr, cases):
    """Each rule rendered on a one-operation system, as the canonical form
    writes it; a param operand has a zero tangent, which leaves the term
    out: the tangent of y is the constant 0."""
    for active, want in cases.items():
        g = compile_(TT._rule_system(expr, active))
        assert TT._tangent_line(g) == want, (expr, active)
    g = compile_(TT._rule_system(expr, ""))
    assert TT._tangent_line(g) == "0"
    assert not [1 for op, _a, _l in g.tangent_step.nodes
                if op in ("mul", "fma", "neg", *THREE)]


def test_the_rules_node_shapes_are_the_contract():
    """The operands in this order (the contract between parcels M2L and
    M2C): sin mul(cos(a), da); cos mul(neg(sin(a)), da); tan mul(fma(r, r,
    c1), da), r the node's own value and c1 the constant 1 - a routine
    node of the tangent written again where it has no name, like any
    primal value, and the product last."""
    shapes = {
        "sin": [("cos", ("s0",), None), ("mul", ("d0", "t0"), None)],
        "cos": [("sin", ("s0",), None), ("neg", ("d0",), None),
                ("mul", ("d1", "t0"), None)],
        "tan": [("tan", ("s0",), None), ("tan", ("s0",), None),
                ("fma", ("d0", "d1", "c0"), None),
                ("mul", ("d2", "t0"), None)],
    }
    for fn, nodes in shapes.items():
        g = TT._one(fn)
        assert g.step.nodes == [(fn, ("s0",), None)]
        assert g.tangent_step.nodes == nodes, fn
        assert g.tangent_step.out == ["t0", f"d{len(nodes) - 1}"]
        # only tan's rule adds a constant, 1; sin's and cos's add none
        assert [v for v, *_r in g.const] == ([F(1)] if fn == "tan" else [])
    # a named operand is read by name, not written again: tan(b) with b a
    # let writes the call again, twice, over b's name, and reads b's tangent
    for fn, want in (("tan", "fma(tan(b), tan(b), 1) * v.b"),
                     ("cos", "(-sin(b)) * v.b"), ("sin", "cos(b) * v.b")):
        g = compile_(f"system r\nformat fp64\nstate a, y\ntangent v\n"
                     f"let b = a * a\nnext a = a\nnext y = {fn}(b)\n"
                     f"step map\n")
        assert TT._tangent_line(g) == want, fn


def test_the_documents_rule_table_holds_the_three():
    text = DOC.read_text(encoding="utf-8")
    rules = text.split("### The rules", 1)[1].split("\n### ", 1)[0]
    rows = {}
    for line in rules.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`"):
            rows[cells[0]] = cells[1]
    for op, tangent in DOC_RULES3.items():
        assert rows.get(op) == tangent, op


def _dual3(op, v, d):
    """(value, derivative) of sin, cos and tan, the test's own calculus:
    each value as the exact evaluation takes it, and the derivative the
    textbook's - cos, -sin and sec^2 = 1 + tan^2, the last with tan the
    exact evaluation's value, so that the rule's exact value is the
    derivative itself (the central difference below is the independent
    evidence for the identity)."""
    x, dx = v[0], d[0]
    if op == "sin":
        return T9("sin", x), T9("cos", x) * dx
    if op == "cos":
        return T9("cos", x), -T9("sin", x) * dx
    t = T9("tan", x)
    return t, (1 + t * t) * dx


def dual3(g, section, state, tangent, params, lanes):
    """TT.dual_eval's, with the three: the exact directional derivative of
    a primal section's outputs."""
    sec = g.section(section)
    vals = {"s": list(zip(state, tangent)),
            "l": [(F(x), F(0)) for x in lanes],
            "p": [(F(x), F(0)) for x in params],
            "c": [(v, F(0)) for v, _fa, _b, _f in g.const]}
    nodes = []

    def get(r):
        k, i = r[0], int(r[1:])
        return nodes[i] if k == "n" else vals[k][i]
    for op, args, _l in sec.nodes:
        a = [get(x) for x in args]
        if op in THREE:
            nodes.append(_dual3(op, [p[0] for p in a], [p[1] for p in a]))
        else:
            nodes.append(TT._dual(op, a, 0, 1, None))
    return [get(o)[1] for o in sec.out]


def exact_misses(g, rng, points=3):
    """(points, points where the tangent is not the derivative), over the
    field and the step at random rational points, about half of them
    placed; TT.derivative_misses' with the three."""
    bad = tot = 0
    for section, tsection in (("field", "tangent_field"),
                              ("step", "tangent_step")):
        if g.section(section) is None:
            continue
        for _ in range(points):
            state = TT._point(rng, g.n_state)
            tangent = [TT._q(rng) for _ in range(g.n_state)]
            params = [TT._q(rng) for _ in g.param]
            lanes = [TT._q(rng) for _ in g.lane]
            try:
                want = dual3(g, section, state, tangent, params, lanes)
            except ArithmeticError:
                continue
            tot += 1
            try:
                got = g.exact_eval(tsection, state, params, lanes,
                                   tangent=tangent)
            except ArithmeticError:
                bad += 1
                continue
            bad += got != want
    return tot, bad


M2_SYSTEMS = {   # the three under each integrator, in lets and equations
    "one of each, a map": (
        "system three\nformat fp64\nstate x, y, z\ntangent v\n"
        "next x = sin(y) - cos(z * x)\n"
        "next y = tan(x * y) + sin(z)\n"
        "next z = cos(x * x + 1) * tan(y)\nstep map\n"),
    "the pendulum, rk4": (
        "system pendulum\nformat fp64\nstate theta, omega\ntangent v\n"
        "param g = 9.81\nparam len = 1.5\n"
        "d/dt theta = omega\nd/dt omega = -(g / len) * sin(theta)\n"
        "step rk4, h = 1/64\n"),
    "a let, rdn": (
        "system rotor\nformat fp128\nround rdn\nstate phi, w\ntangent v\n"
        "param kappa = 1/3\nlet s = sin(phi)\n"
        "d/dt phi = w + cos(phi) * kappa\nd/dt w = -(kappa * s) - tan(w) / 4\n"
        "step rk4, h = 1/64\n"),
    "stormer-verlet": (
        "system pot\nformat fp32\nround rup\nstate q, p\ntangent v\n"
        "d/dt q = p + tan(p / 8)\nd/dt p = -sin(q) * cos(q)\n"
        "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
    "euler, two vectors": (
        "system e\nformat fp256\nround rmm\nstate x\ntangent v, w\n"
        "d/dt x = cos(-x) + sin(x * x)\nstep euler, h = 1/8\n"),
}


def m2_graphs(count=16, seed="m2 corpus"):
    """The written systems, and generated systems with tangent vectors
    holding the three beside every other operation."""
    graphs = [compile_(t, w) for w, t in M2_SYSTEMS.items()]
    rng = random.Random(seed)
    k = 0
    while len(graphs) < len(M2_SYSTEMS) + count:
        text = TL.random_system(rng, k, expr=_m2_expr)
        k += 1
        try:
            g = compile_(TT.with_tangent(text, "v, w" if k % 4 == 0 else "v"),
                         f"m2-{k}")
        except lang.Refusal as r:
            assert r.name in _M2_ARTIFACTS, f"{r}\n{text}"
            continue
        if set(THREE) & set(g.op_counts("step")):
            graphs.append(g)
    return graphs


@needs_mpmath
def test_the_rules_are_the_derivative():
    """The exact dual numbers - the tangent evaluated exactly against the
    test's own derivative, each of the three as the exact evaluation takes
    it - and the central difference in high precision (eps = 2^-256 of
    1,024-bit values, within 2^-300), on the written systems and on
    generated ones: no miss at any point, and most points decide. The
    first is the exact check, the second the independent one: sec^2 = 1 +
    tan^2 is the identity the first assumes and the second tests. A graph
    holding a square root is left out of the second: the exact evaluation
    takes a root rounded down to 2^-256 (graph.exact_root), and a central
    difference at eps = 2^-256 would measure that rounding, not the
    derivative (L4's difference is at 2^-64)."""
    rng = random.Random("m2 derivative")
    graphs = m2_graphs()
    assert len(graphs) == len(M2_SYSTEMS) + 16
    tot = bad = htot = hbad = 0
    for g in graphs:
        a, b = exact_misses(g, rng, points=3)
        tot, bad = tot + a, bad + b
        if "sqrt" in g.op_counts("step"):
            continue
        a, b = TT.hp_misses(g, rng, points=2)
        htot, hbad = htot + a, hbad + b
    assert bad == 0 and tot >= 40, (tot, bad)
    assert hbad == 0 and htot >= 30, (htot, hbad)
    ops = set()
    for g in graphs:
        ops |= set(g.op_counts("step"))
    assert set(THREE) <= ops


# ---- each rule's rounding ---------------------------------------------------

def _domain(rng):
    """A radian argument away from the poles of tan and the grid's zeros."""
    return F(rng.randint(-64000, 64000), 1000)


def _cd(fn, a, da):
    """The derivative of the function at a along da, by a central
    difference at 2^-256 of the reader's 1,024-bit values."""
    return (T9(fn, a + TT.HP_EPS * da) - T9(fn, a - TT.HP_EPS * da)) \
        / (2 * TT.HP_EPS)


def rule_bits(fn, fmt, code, a, da, r):
    """The table's rule on one lane, in the golden model: its primal-only
    factor rounded once - cos(a) or sin(a) the routine's correctly rounded
    result under the attribute, 1 + r * r one fma - then the product once
    -> (bits, the product's exact value before its rounding)."""
    val = functools.partial(C.value_of, fmt)
    one = C.round_once(fmt, sf.RND_RNE, F(1))[0]
    if fn == "sin":
        q = transcend.compute(fmt, "cos", a, 0, code)[0]
    elif fn == "cos":
        q = sf.neg(fmt, transcend.compute(fmt, "sin", a, 0, code)[0])[0]
    else:
        q = sf.fma(fmt, r, r, one, code)[0]
    return sf.mul(fmt, q, da, code)[0], val(q) * val(da)


def rounding_misses(fn, fmtname, rnd, rng, lanes=6):
    """(lanes, lanes whose tangent is not the table's last operation
    rounded once, lanes whose last operation's exact value is not the
    derivative within its operands' roundings) on y = fn(a): the
    primal-only factor rounded once first; the derivative by a central
    difference at 2^-256 of the 1,024-bit values. One rounding of the
    factor for sin and cos, and tan's three - r's, the product r * r's
    carry and the fma's - each at most 2^(1-p) relatively."""
    g = TT._one(fn, fmtname, rnd)
    fmt, code = g.fmt, C.RND_BY_NAME[rnd]
    u = F(1, 1 << (fmt.prec - 1))
    pairs = [(TT._bits(fmt, _domain(rng)),
              TT._bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)))
             for _ in range(lanes)]
    run = lang.run(g, [[a, 0] for a, _d in pairs], 1,
                   tangents=[[[da, 0]] for _a, da in pairs])
    bits_bad = value_bad = 0
    for (a, da), st, tv in zip(pairs, run.states, run.tangents):
        r, t = st[1], tv[0][1]
        want, exact = rule_bits(fn, fmt, code, a, da, r)
        bits_bad += t != want
        d = _cd(fn, C.value_of(fmt, a), C.value_of(fmt, da))
        bound = {"sin": 1, "cos": 1, "tan": 3}[fn] * u * F(101, 100)
        value_bad += abs(exact - d) > (bound + F(1, 1 << 400)) * abs(d)
    return len(pairs), bits_bad, value_bad


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_each_rule_rounds_as_the_table_says(fmtname):
    """y = f(a) under every attribute, at random a and random tangents: the
    interpreter's tangent is the table's last operation, a product, rounded
    once, on a factor that is the primal-only value the table rounds once
    first - cos(a), -sin(a) or fma(r, r, 1), the routine's correctly
    rounded result under the attribute. And that product's exact value is
    the derivative f'(a) da, by a central difference in high precision,
    within the roundings of its factor. So a rule rounded otherwise -
    cos's -(sin(a) * da), tan's fma(r, r * da, da) - is red here (cos's
    under rdn and rup, where its two forms differ: the next test)."""
    rng = random.Random(f"m2 rounds {fmtname}")
    for fn in THREE:
        for rnd in RNDS:
            n, bits, value = rounding_misses(fn, fmtname, rnd, rng)
            assert (n, bits, value) == (6, 0, 0), (fn, rnd)


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_cos_rounded_otherwise_differs_only_under_rdn_and_rup(fmtname):
    """cos's rule `(-sin(a)) * da` negates sin(a) exactly and rounds the
    product once; `-(sin(a) * da)` rounds the product and then negates.
    Rounding to nearest (even or away) and toward zero are symmetric about
    zero, so the two are the same bits under rne, rtz and rmm, on every
    finite lane; under rdn and rup the product of the negated factor rounds
    the other way, and they differ on nearly every finite lane. On this
    test's own draw, 40 lanes a format from its seeded generator below,
    they differ on 40 of 40 under rdn and on 40 of 40 under rup at every
    format, and on none under rne, rtz and rmm (MEASURED). The assertion is
    weaker: none under rne, rtz and rmm and more than 5 of 40 under rdn and
    under rup. A plant that is invisible under rne is not one this check
    would see, which is why the rounding check covers all five. "Only under
    rdn and rup" is true of finite results: at a NaN, sin(a) = the invalid
    NaN and the second form is the first's with its sign bit set, under
    every attribute (measured here at each format), so a NaN lane is red
    under rne too - the specials test's, not the rounding check's."""
    fmt = FORMATS[fmtname]
    rng = random.Random(f"m2 cos otherwise {fmtname}")
    pairs = [(TT._bits(fmt, _domain(rng)),
              TT._bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)))
             for _ in range(40)]
    differ = {}
    nan_differs = {}
    for rnd in RNDS:
        code = C.RND_BY_NAME[rnd]
        n = 0
        for a, da in pairs:
            s = transcend.compute(fmt, "sin", a, 0, code)[0]
            right = sf.mul(fmt, sf.neg(fmt, s)[0], da, code)[0]
            otherwise = sf.neg(fmt, sf.mul(fmt, s, da, code)[0])[0]
            n += right != otherwise
        differ[rnd] = n
        s = sf.qnan_bits(fmt)
        da = pairs[0][1]
        nan_differs[rnd] = (sf.mul(fmt, sf.neg(fmt, s)[0], da, code)[0]
                            ^ sf.neg(fmt, sf.mul(fmt, s, da, code)[0])[0])
    assert differ["rne"] == differ["rtz"] == differ["rmm"] == 0, differ
    assert differ["rdn"] > 5 and differ["rup"] > 5, differ
    assert set(nan_differs.values()) == {fmt.sign_mask}, nan_differs


# ---- the rules at their specials ---------------------------------------------

@needs_mpmath
def test_the_rules_at_their_specials():
    """Bit for bit at fp64: at +0 and -0 sin's tangent is da (cos 0 is
    exactly 1), cos's is (-sin 0) * da, a zero of the sign the product of
    -(+-0) and da has, tan's is da (fma(0, 0, 1) is 1); at +-inf cos(a),
    sin(a) and tan(a) are the invalid NaN, so is the tangent, and the
    primal's flags are invalid alone; at a NaN the NaN; and a tangent of
    zero gives a zero (the primal's sign, the product's)."""
    fmt = FORMATS["fp64"]

    def b(v):
        return TT._bits(fmt, v)
    sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
    three, mthree = b(3), b(-3)
    one = b(1)
    for fn in THREE:
        g = TT._one(fn)
        # at +0 and -0
        for zero in (0, sign):
            r, t, f, pf = TT._run_one(g, zero, three)
            assert f == pf == 0
            assert r == (one if fn == "cos" else zero), (fn, hex(zero))
            if fn == "cos":
                # -(+-0) = -+0, times 3: the product's sign
                assert t == (sign if zero == 0 else 0), (fn, hex(zero))
                r2, t2, _f, _pf = TT._run_one(g, zero, mthree)
                assert t2 == (0 if zero == 0 else sign), (fn, hex(zero))
            else:
                assert t == three, (fn, hex(zero))
                assert TT._run_one(g, zero, mthree)[1] == mthree
        # at an infinity, a quiet NaN and a signalling NaN
        for bad_a, flag in ((inf, sf.FLAG_INVALID),
                            (inf ^ sign, sf.FLAG_INVALID), (qnan, 0),
                            (sf.snan_bits(fmt, 1), sf.FLAG_INVALID)):
            r, t, f, pf = TT._run_one(g, bad_a, three)
            assert (r, t) == (qnan, qnan), (fn, hex(bad_a))
            assert pf == flag and f == flag, (fn, hex(bad_a), f, pf)
        # a tangent of zero: the product's zero, the factor's sign
        r, t, f, pf = TT._run_one(g, b(1), 0)
        assert t & ~sign == 0 and f == pf == sf.FLAG_INEXACT, (fn, hex(t))
    # tan at a root of the rule's factor: no representable argument is a
    # pole, and the factor is finite at the largest finite argument
    g = TT._one("tan")
    r, t, f, pf = TT._run_one(g, sf.max_normal_bits(fmt), three)
    assert f & sf.FLAG_INEXACT and t not in (qnan, inf)


# ---- what each vector pays ---------------------------------------------------

def test_each_vector_pays_one_product_a_call():
    """After sharing what the tangent writes again, each call of the three
    costs a tangent vector one product, and the factor it multiplies is
    primal-only - cos(a), -sin(a) and 1 + r * r read no tangent - so the
    compiler shares them across vectors, as the quotient's -r (the study,
    section 7). sin's and cos's factors hold a routine of their own, a
    node the primal need not hold; tan's holds the primal's own call,
    written again twice."""
    want = {"sin": (["mul"], ["cos"]), "cos": (["mul"], ["sin", "neg"]),
            "tan": (["mul"], ["tan", "tan", "fma"])}
    for fn, (per_vector, primal_only) in want.items():
        g = TT._one(fn)
        primal, tangent = TT._structural(g)
        reads = TT._reads_tangent(g)
        own = [(op, r) for (op, i), r in zip(tangent, reads)
               if i not in primal]
        assert sorted(op for op, r in own if r) == sorted(per_vector), fn
        # tan's two reads of r are the primal's own call: one operation
        assert sorted(op for (op, i), r in zip(tangent, reads)
                      if not r and (fn == "tan" or i not in primal)) == \
            sorted(primal_only), fn
        if fn == "tan":
            assert all(i in primal for op, i in tangent if op == "tan")
        else:
            # the routine is not the primal's
            assert all(i not in primal for op, i in tangent
                       if op in ("cos", "sin"))
    # two vectors: the tangent section is generic, one for every vector, so
    # it holds the factor once and the product once; each vector's printed
    # line writes the factor again over its own tangent input, which is what
    # the compiler shares (it reads no vector's component)
    g = compile_("system r\nformat fp64\nstate a, y\ntangent v, w\n"
                 "next a = a\nnext y = sin(a)\nstep map\n")
    assert [op for op, _a, _l in g.tangent_step.nodes] == ["cos", "mul"]
    canon = lang.render_canonical(g)
    assert "\nnext v.y = cos(a) * v.a\n" in canon
    assert "\nnext w.y = cos(a) * w.a\n" in canon


def test_unnamed_chains_of_the_three_grow_with_the_square():
    """The known limit's figures for the three (docs/LANGUAGE.md, "Known
    limits"; MEASURED here, 99 nested calls, tangent_step's nodes): each
    rule writes its operand again, sin's and cos's once and tan's twice
    (r is read twice), so a chain nested unnamed grows with the square -
    5,049 for sin, 5,148 for cos and 10,098 for tan - against 198, 297 and
    198 named by lets. At 100 nested the tangent of cos and of tan would
    print 101 deep and the source is refused `too-deep`, as a root's is;
    100 nested sins print 100 deep and are not."""
    def nested(fn, k=99):
        e = "x"
        for _ in range(k):
            e = f"{fn}({e})"
        return (f"system r\nformat fp64\nstate x\ntangent v\nnext x = {e}\n"
                "step map\n")

    def named(fn):
        lets = "".join(f"let e{i} = {fn}({'x' if i == 1 else f'e{i - 1}'})\n"
                       for i in range(1, 100))
        return (f"system r\nformat fp64\nstate x\ntangent v\n{lets}"
                "next x = e99\nstep map\n")

    want = {"sin": (5049, 198), "cos": (5148, 297), "tan": (10098, 198)}
    for fn, (unnamed, lets) in want.items():
        assert len(compile_(nested(fn)).tangent_step.nodes) == unnamed, fn
        assert len(compile_(named(fn)).tangent_step.nodes) == lets, fn
    assert len(compile_(nested("sin", 100)).tangent_step.nodes) == 5150
    for fn in ("cos", "tan"):
        with pytest.raises(lang.Refusal) as info:
            compile_(nested(fn, 100))
        assert (info.value.name, info.value.line) == ("too-deep", 5), fn


@needs_mpmath
def test_the_primal_is_unchanged_by_tangents():
    """With tangents, the primal sections are the system's without them,
    by value, and a run's states and primal flags too; the rules add the
    constant 1 for tan's alone, and none for sin's and cos's."""
    rng = random.Random("m2 primal unchanged")
    for g in m2_graphs(8, "m2 primal"):
        text = lang.render_canonical(g)
        g0 = compile_(TT._strip_tangent(text))
        added = ({v for v, _fa, _b, _f in g.const}
                 - {v for v, _fa, _b, _f in g0.const})
        assert added <= {F(0), F(1), F(-1), F(2)}, added
        assert TT._sections_by_value(g) == TT._sections_by_value(g0)
        states = [[TT._bits(g.fmt, TT._q(rng)) for _ in range(g.n_state)]
                  for _ in range(2)]
        tans = [[[TT._bits(g.fmt, TT._q(rng)) for _ in range(g.n_state)]
                 for _ in g.tangent] for _ in states]
        lanes = [[TT._bits(g.fmt, F(rng.randint(1, 9), 4)) for _ in g.lane]
                 for _ in states] if g.lane else None
        r0 = lang.run(g0, states, 2, lane_params=lanes)
        r1 = lang.run(g, states, 2, lane_params=lanes, tangents=tans)
        assert r0.states == r1.states and r0.flags == r1.primal_flags
    for fn in THREE:
        for fmtname in FORMATS:
            plain = (f"system r\nformat {fmtname}\nround rdn\nstate a, y\n"
                     f"next a = a\nnext y = {fn}(a)\nstep map\n")
            with_t = plain.replace("state a, y\n", "state a, y\ntangent v\n")
            g0, g1 = compile_(plain), compile_(with_t)
            added = {v for v, *_r in g1.const} - {v for v, *_r in g0.const}
            assert added == ({F(1)} if fn == "tan" else set()), (fn, fmtname)
            fmt = g1.fmt
            states = [[TT._bits(fmt, _domain(rng)), 0] for _ in range(5)]
            r0 = lang.run(g0, states, 3)
            r1 = lang.run(g1, states, 3, tangents=[[[0, 0]] for _ in states])
            assert (r0.states, r0.flags) == (r1.states, r1.primal_flags)


# ---- mpmath ------------------------------------------------------------------

_NO_MPMATH = r"""
import sys
sys.modules["mpmath"] = None            # import mpmath raises ImportError
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, sys.argv[2])
from cft_golden import lang, transcend
out = []
ref = lang.load(sys.argv[3])
r = lang.run(ref.graph, [[1, 2, 3]], 2)
out.append(f"reference ran {len(r.states)}")
text = ("system s\nformat fp64\nstate x, y\ntangent v\n"
        "next x = sin(x) + cos(0)\nnext y = tan(y) * cos(x)\nstep map\n")
g = lang.compile_text(text, "s").graph
back = lang.compile_text(lang.render_canonical(g), "c").graph
out.append(f"checked and read back {back.to_bytes() == g.to_bytes()}")
lang.render_math(g)
try:
    lang.run(g, [[0, 0]], 1, tangents=[[[0, 0]]])
    out.append("ran")
except transcend.ZivEscalation as e:
    out.append(f"ZivEscalation: {e}")
from fractions import Fraction
try:
    g.exact_eval("step", [Fraction(1, 3), Fraction(1, 3)])
except ImportError:
    out.append("exact_eval ImportError")
from cft_golden import cert2
out.append(f"needs {cert2.Definition(g).needs_mpmath()}")
print("\n".join(out))
"""


def test_mpmath_is_needed_only_by_a_run_of_the_three(tmp_path):
    """With mpmath taken away (sys.modules), a reference compiles and runs;
    a source holding the three - cos(a) and sin(a) among its tangent
    rules - is checked, folded (cos(0)), rendered and read back, none of
    which needs mpmath; lang.run of it raises transcend.ZivEscalation
    naming mpmath and the functions, before any lane runs; and its exact
    evaluation, the tests' tool, raises ImportError, never an
    ArithmeticError that would make a point decide nothing."""
    script = tmp_path / "nompmath.py"
    script.write_text(_NO_MPMATH, encoding="utf-8")
    r = subprocess.run([sys.executable, str(script), str(HERE.parent),
                        str(HERE.parent),
                        str(SYSTEMS / "lorenz63-rk4-fp64.cftl")],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "reference ran 1"
    assert lines[1] == "checked and read back True"
    assert lines[2] == ("ZivEscalation: s computes sin, cos, tan, whose "
                        "golden functions (python/cft_golden/transcend.py) "
                        "decide each rounding through mpmath's enclosures, "
                        "and mpmath is not installed: lang.run cannot run it "
                        "here"), lines[2]
    assert lines[3] == "exact_eval ImportError"
    assert lines[4] == "needs True"


def test_a_definition_holding_the_three_needs_mpmath():
    """cert2's list of the nodes whose golden function is decided through
    mpmath is the language's TRANSCEND: a definition holding sin, cos or
    tan - in its step, and written again in its tangent - needs it, and
    one without them does not."""
    assert cert2.TRANSCEND_OPS == set(lang_graph.TRANSCEND)
    for fn in THREE:
        text = (f"system s\nformat fp64\nstate x, y\ntangent v\n"
                f"next x = x\nnext y = y + {fn}(x)\nstep map\n")
        d = cert2.Definition(compile_(text, "s"))
        assert d.needs_mpmath()
        plain = text.replace(f"{fn}(x)", "x * x")
        assert not cert2.Definition(compile_(plain, "s")).needs_mpmath()
    # the primal holds none, the tangent a routine of its own: sin of a
    # state read through a let the tangent writes again is still sin's
    g = compile_("system s\nformat fp64\nstate x\ntangent v\n"
                 "next x = x\nstep map\n")
    assert not cert2.Definition(g).needs_mpmath()


# ---- the plants --------------------------------------------------------------

class _Plant(lang_tangent.Derivation):
    """The derivation with one of the three's rules changed (kind)."""
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        if node.op in THREE and self.of(a[0]) is not None:
            da, k = self.of(a[0]), self.kind
            if node.op == "sin" and k == "sin's rule: sin(a) * da":
                return N("mul", R(node), da)
            if node.op == "cos" and k == "cos's rule without its minus":
                return N("mul", N("sin", R(a[0])), da)
            if node.op == "tan" and k == "tan's rule: r * da":
                return N("mul", R(node), da)
            if node.op == "cos" and k == "cos's rule rounded otherwise":
                return N("neg", N("mul", N("sin", R(a[0])), da))
            if node.op == "tan" and k == "tan's rule rounded otherwise":
                # the study's alternative, fma(r, r * da, da): the same
                # value, two roundings a vector with nothing shared. It
                # reads da twice, which only a leaf or a named node may
                # bear: where da is an unnamed expression the rule is the
                # table's (the rounding check's one-operation system has a
                # leaf)
                if isinstance(da, Node) and da.label is None:
                    return super().rule(node)
                return N("fma", R(node), N("mul", R(node), da), da)
        return super().rule(node)


WRONG = ["sin's rule: sin(a) * da", "cos's rule without its minus",
         "tan's rule: r * da"]
OTHERWISE = ["cos's rule rounded otherwise", "tan's rule rounded otherwise"]


@needs_mpmath
@pytest.mark.parametrize("kind", WRONG + OTHERWISE)
def test_the_plants(kind, monkeypatch):
    """Each planted, and each red where it must be. A wrong rule is red on
    the exact check, the central difference and the rounding check alike.
    A rule rounded otherwise is exact in rationals - green on the exact
    check and the central difference - and red on the rounding check: tan's
    `fma(r, r * da, da)` under every attribute, cos's `-(sin(a) * da)` under
    rdn and rup only at finite lanes, where its two forms differ, and green
    under rne, rtz and rmm there; at a NaN lane cos's second form is red
    under every attribute. Each also changes the rule table's line."""
    class P(_Plant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check, "Derivation", P)
    fn = kind[:3]
    rng = random.Random(f"m2 plant {kind}")
    exact = hp = 0
    for fmtname in ("fp32", "fp64", "fp256"):
        g = TT._one(fn, fmtname)
        exact += exact_misses(g, rng, points=3)[1]
        hp += TT.hp_misses(g, rng, points=2)[1]
    bits = {}
    for fmtname in ("fp32", "fp64", "fp256"):
        for rnd in RNDS:
            bits[fmtname, rnd] = rounding_misses(fn, fmtname, rnd, rng, 12)[1]
    table = TT._tangent_line(compile_(TT._rule_system(f"{fn}(a)", "a")))
    right = dict(RULES3)[f"{fn}(a)"]["a"]
    assert table != right
    # the specials' lane at an infinity (test_the_rules_at_their_specials):
    # the tangent is the invalid NaN, positive - and only cos's second form
    # gives the negation's sign bit, under every attribute
    f64 = FORMATS["fp64"]
    nan_red = {rnd: TT._run_one(TT._one(fn, "fp64", rnd), sf.inf_bits(f64),
                                TT._bits(f64, 3))[1] != sf.qnan_bits(f64)
               for rnd in RNDS}
    assert all(nan_red.values()) == (kind == "cos's rule rounded otherwise")
    assert any(nan_red.values()) == (kind == "cos's rule rounded otherwise")
    if kind in WRONG:
        assert exact > 0 and hp > 0 and min(bits.values()) > 0, \
            (exact, hp, bits)
    elif fn == "tan":
        assert (exact, hp) == (0, 0) and min(bits.values()) > 0, \
            (exact, hp, bits)
    else:
        # cos: invisible under rne, rtz and rmm; red under rdn and rup
        assert (exact, hp) == (0, 0)
        for (fmtname, rnd), n in bits.items():
            if rnd in ("rdn", "rup"):
                assert n > 0, (fmtname, rnd, bits)
            else:
                assert n == 0, (fmtname, rnd, bits)


@needs_mpmath
def test_sins_golden_function_swapped_for_coss_is_red(monkeypatch):
    """The interpreter's table swapped: sin's node computes cos. Red on the
    golden check (every attribute: all but the few lanes where sin and cos
    agree in bits), and, bit for bit, on cos's rule, which reads sin(a) as a
    node of its own - its tangent is then (-cos(a)) * da. Not red on sin's
    own rule, which reads cos(a) and never its own y, so that rule's checks
    are blind to sin's golden function (which is why the golden check
    exists); and not red on the exact evaluations, which do not run the
    interpreter's table at all."""
    rng = random.Random("m2 plant golden")
    good = [golden_misses("sin", "fp64", rnd, rng)[1] for rnd in RNDS]
    assert good == [0] * 5
    orig = lang_interp._transcend
    monkeypatch.setattr(lang_interp, "_transcend",
                        lambda fmt, fn, rnd: orig(fmt, "cos" if fn == "sin"
                                                  else fn, rnd))
    bad = [golden_misses("sin", "fp64", rnd, rng)[1] for rnd in RNDS]
    assert all(n > 10 for n in bad), bad
    cos_bits = sin_bits = 0
    for rnd in RNDS:
        cos_bits += rounding_misses("cos", "fp64", rnd, rng)[1]
        sin_bits += rounding_misses("sin", "fp64", rnd, rng)[1]
    assert cos_bits > 0 and sin_bits == 0, (cos_bits, sin_bits)
