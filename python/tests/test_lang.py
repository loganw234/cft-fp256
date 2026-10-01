# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The language's definition: its parser, checker, exact constants, step
graph and intention-out (python/cft_golden/lang, docs/LANGUAGE.md).

The interpreter against seq.py, and the plants, are test_lang_refs.py.
Here:

  the references       parse, and their fp64 and fp256 files differ in
                       the format line only; their node counts against
                       the images' ALU instructions a step
  the constants        each classic bank slot is its exact value rounded
                       once, at fp64 and fp256; the fp32 h/6 that differs
                       from the bank's route; a const's negation and a
                       param's under rdn and rup; unary minus's precedence
                       under rdn; zero as +0; the once-rounding checked
                       against its neighbours
  the refusals         every name in the catalogue made by a test, and a
                       fuzz of the references that compiles or refuses by
                       name and never raises anything else
  determinism          the same source gives the same bytes, in this
                       process and under two other hash seeds
  the intention-out    the canonical form parses back to the same graph,
                       byte for byte; the mathematical form, evaluated
                       exactly at random rational points, equals the step
                       graph evaluated exactly; every other line of both
                       read back and held - on the references, written
                       systems with Greek names and random systems
  the characters       .cfta's rule, in asm.py's words: each line break
                       but LF and CR LF, NUL and Ctrl-Z refused anywhere,
                       only printable ASCII outside a comment, UTF-8
  a run's h            of the graph's sign, the system compiled at that h;
                       of the other sign, refused
  the documents        docs/LANGUAGE.md's refusal table and its copy of
                       the integrators are the code's
"""

import hashlib
import os
import random
import re
import subprocess
import sys
import unicodedata
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from cft_golden import FORMATS, asm, chars, lang  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.lang import check as lang_check  # noqa: E402
from cft_golden.lang import constants as C  # noqa: E402
from cft_golden.lang import syntax as lang_syntax  # noqa: E402
from cft_golden.lang.graph import Section  # noqa: E402
from lang_mathform import MathForm  # noqa: E402
from lang_mathform import constant as mathform_constant  # noqa: E402

PROGRAMS = REPO / "programs"
SYSTEMS = PROGRAMS / "systems"
DOC = REPO / "docs" / "LANGUAGE.md"
NAMES = ("lorenz63-rk4", "lorenz96-rk4", "henonheiles-lf")
REFS = [f"{n}-{f}" for n in NAMES for f in ("fp64", "fp256")]
F = Fraction


@lru_cache(maxsize=None)
def ref(name):
    return lang.load(SYSTEMS / f"{name}.cftl").graph


def compile_(text, source="<test>"):
    return lang.compile_text(text, source).graph


# ---- the references --------------------------------------------------------

@pytest.mark.parametrize("name", NAMES)
def test_fp64_and_fp256_differ_in_format_only(name):
    a = (SYSTEMS / f"{name}-fp64.cftl").read_text().splitlines()
    b = (SYSTEMS / f"{name}-fp256.cftl").read_text().splitlines()
    assert len(a) == len(b)
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    assert diff == [("format fp64", "format fp256")]


# Each step's operations, as literals - and each image's ALU instructions
# a step, read off the image below.
COUNTS = {
    "lorenz63-rk4": ({"fma": 2, "sub": 2, "mul": 2, "neg": 2},
                     {"fma": 26, "add": 3, "sub": 8, "mul": 8, "neg": 8}),
    "lorenz96-rk4": ({"fma": 40, "sub": 80},
                     {"fma": 400, "add": 40, "sub": 320}),
    "henonheiles-lf": ({"fma": 2, "sub": 1, "mul": 2, "neg": 2},
                       {"fma": 8, "sub": 1, "mul": 2, "neg": 2}),
}


def image_alu(name, fmtname):
    """{op: count} of the ALU instructions in the image's REPEAT body."""
    text = (PROGRAMS / f"{name}-{fmtname}.cfta").read_text()
    img = asm.assemble_image(text, name)
    out, inside = {}, False
    for word in img.insns:
        d = asm.decode(word)
        if d["ctrl"]:
            if d["op"] == asm.REPEAT:
                inside = True
            elif d["op"] == asm.ENDREP:
                inside = False
            continue
        if inside:
            op = sf.OP_NAMES[d["op"]]
            out[op] = out.get(op, 0) + 1
    return out


@pytest.mark.parametrize("name", REFS)
def test_node_counts_against_the_image(name):
    base, fmtname = name.rsplit("-", 1)
    g = ref(name)
    field, step = COUNTS[base]
    assert g.op_counts("field") == field
    assert g.op_counts("step") == step
    alu = image_alu(base, fmtname)
    if base == "henonheiles-lf":
        # one neg more a step: the force's sign is kept by the force
        # (fma(h, -t0, px)), where the image moves it into -h (fma(MH,
        # t0, px)) - the same bits (test_lang_refs.py)
        assert alu == dict(step, neg=1)
    else:
        assert alu == step


# ---- the constants -----------------------------------------------------------

BANK_SLOTS = {
    "lorenz63-rk4": [("H", F(1, 100)), ("H2", F(1, 200)), ("H6", F(1, 600)),
                     ("TWO", F(2)), ("SIGMA", F(10)), ("RHO", F(28)),
                     ("BETA", F(8, 3))],
    "lorenz96-rk4": [("H", F(1, 100)), ("H2", F(1, 200)), ("H6", F(1, 600)),
                     ("TWO", F(2)), ("F", F(8))],
    "henonheiles-lf": [("H", F(1, 100)), ("H2", F(1, 200)),
                       ("MH", F(-1, 100)), ("ONE", F(1)), ("TWO", F(2))],
}


@pytest.mark.parametrize("name", REFS)
def test_bank_is_the_once_rounded_rule(name):
    """Each classic bank slot is its exact value rounded once, slot for
    slot, and the graph's const or param of the same exact value has the
    same encoding; every graph constant is one of the bank's values."""
    base, fmtname = name.rsplit("-", 1)
    fmt = FORMATS[fmtname]
    raw = (PROGRAMS / f"{base}-{fmtname}.classic.bank").read_bytes()
    esz = fmt.width // 8
    got = [int.from_bytes(raw[i:i + esz], "little")
           for i in range(0, len(raw), esz)]
    slots = BANK_SLOTS[base]
    assert len(got) == len(slots)
    g = ref(name)
    mine = {v: b for v, _fa, b, _f in g.const}
    mine.update({v: b for _n, v, b, _f in g.param})
    values = {v for _n, v in slots}
    for (_slot, value), bits in zip(slots, got):
        assert C.round_once(fmt, sf.RND_RNE, value)[0] == bits
        if value in mine:
            assert mine[value] == bits
    assert set(mine) <= values


def test_the_constant_report():
    """Each constant's exact value, encoding, flags and relative error,
    as the compiler's manifest reads them (Lorenz-63 at fp64, the values
    measured when the design was written)."""
    rows = {r["name"]: r for r in ref("lorenz63-rk4-fp64").constant_report()}
    assert set(rows) == {"h", "h/2", "h/6", "2", "sigma", "rho", "beta"}
    want = {"h": (F(1, 100), F(1), 0x3f847ae147ae147b, "+2.0817e-17"),
            "h/2": (F(1, 200), F(1, 2), 0x3f747ae147ae147b, "+2.0817e-17"),
            "h/6": (F(1, 600), F(1, 6), 0x3f5b4e81b4e81b4f, "+6.4185e-17"),
            "2": (F(2), None, 0x4000000000000000, "0"),
            "beta": (F(8, 3), None, 0x4005555555555555, "-5.5511e-17")}
    for name, (exact, factor, bits, rel) in want.items():
        r = rows[name]
        assert (r["exact"], r["h_factor"], r["bits"]) == (exact, factor, bits)
        assert C.sig(r["relative_error"]) == rel
        assert bool(r["flags"] & sf.FLAG_INEXACT) == (rel != "0")


def test_fp32_h6_is_rn_of_one_six_hundredth():
    """At fp32 the language's h/6 is RN(1/600), once; the bank's route,
    RN(RN(1/100)/6), is one ulp below it. No fp32 image exists, so this
    states the value and the difference."""
    text = (SYSTEMS / "lorenz63-rk4-fp64.cftl").read_text()
    g = compile_(text.replace("format fp64", "format fp32"))
    fmt = FORMATS["fp32"]
    h6 = [b for v, fa, b, _f in g.const if fa == F(1, 6)]
    assert h6 == [0x3ada740e]
    h, _ = C.round_once(fmt, sf.RND_RNE, F(1, 100))
    six, _ = C.round_once(fmt, sf.RND_RNE, F(6))
    route, _ = sf.div(fmt, h, six)
    assert route == 0x3ada740d
    assert h6[0] - route == 1
    assert C.sig(C.relative_error(fmt, h6[0], F(1, 600))) == "+2.4214e-08"
    assert C.sig(C.relative_error(fmt, route, F(1, 600))) == "-4.5635e-08"


def _one_step(text, values):
    g = compile_(text)
    return lang.run(g, [values], 1).states[0]


def test_const_and_param_negation_under_rdn_and_rup():
    """A const's negation is the attribute's rounding of the negated
    exact value; a param's is a run-time neg of its rounded value. Under
    rdn and rup the two differ for an inexact constant (8/3), and agree
    for an exact one (2)."""
    fmt = FORMATS["fp64"]
    one = sf.one_bits(fmt)
    for rnd in ("rdn", "rup"):
        code = C.RND_BY_NAME[rnd]
        for value, differ in (("8/3", True), ("2", False)):
            c = _one_step(f"system s\nformat fp64\nround {rnd}\nstate x\n"
                          f"const c = {value}\nnext x = x * -c\nstep map\n",
                          [one])[0]
            p = _one_step(f"system s\nformat fp64\nround {rnd}\nstate x\n"
                          f"param p = {value}\nnext x = x * -p\nstep map\n",
                          [one])[0]
            exact = -F(value)
            assert c == C.round_once(fmt, code, exact)[0]
            assert p == sf.negate(fmt, C.round_once(fmt, code, -exact)[0])
            assert (c != p) == differ


def test_unary_minus_binds_tighter_than_times():
    """-x * y is (-x) * y. Under rdn its rounding differs from -(x * y)
    whenever the product is inexact; under rne, rtz and rmm the two
    agree. The canonical form prints the parentheses either way."""
    fmt = FORMATS["fp64"]
    x, _ = C.round_once(fmt, sf.RND_RNE, F(1, 3))
    y, _ = C.round_once(fmt, sf.RND_RNE, F(3, 7))
    texts = {}
    results = {}
    for rnd in ("rne", "rtz", "rmm", "rdn", "rup"):
        for body in ("-x * y", "-(x * y)"):
            src = (f"system s\nformat fp64\nround {rnd}\nstate x, y\n"
                   f"next x = {body}\nnext y = y\nstep map\n")
            g = compile_(src)
            texts[(rnd, body)] = lang.render_canonical(g)
            results[(rnd, body)] = lang.run(g, [[x, y]], 1).states[0][0]
    for rnd in ("rne", "rtz", "rmm"):
        assert results[(rnd, "-x * y")] == results[(rnd, "-(x * y)")]
    for rnd in ("rdn", "rup"):
        assert results[(rnd, "-x * y")] != results[(rnd, "-(x * y)")]
    assert "next x = (-x) * y" in texts[("rdn", "-x * y")]
    assert "next x = -(x * y)" in texts[("rdn", "-(x * y)")]


@pytest.mark.parametrize("rnd", ["rne", "rtz", "rdn", "rup", "rmm"])
def test_a_zero_constant_is_plus_zero(rnd):
    """A constant whose exact value is zero is +0 under every attribute:
    the rational has no sign of zero."""
    g = compile_(f"system s\nformat fp64\nround {rnd}\nstate x\n"
                 f"next x = x + (1 - 1)\nstep map\n")
    assert [(v, b) for v, _fa, b, _f in g.const] == [(0, 0)]


@pytest.mark.parametrize("name", REFS)
def test_the_rounding_is_once_and_nearest(name):
    """Each encoding is the nearest to its exact value - neither
    neighbour is nearer, and a tie goes to the even one - checked with
    nextUp, nextDown and Fractions, apart from the rounding code."""
    g = ref(name)
    fmt = g.fmt
    values = [(v, b) for v, _fa, b, _f in g.const]
    values += [(v, b) for _n, v, b, _f in g.param]
    for value, bits in values:
        r = C.value_of(fmt, bits)
        for nb in (sf.next_up(fmt, bits)[0], sf.next_down(fmt, bits)[0]):
            other = C.value_of(fmt, nb)
            assert abs(r - value) <= abs(other - value)
            if abs(r - value) == abs(other - value):
                assert bits & 1 == 0


# ---- the refusals ------------------------------------------------------------

def _src(*body, step="step map"):
    return "\n".join(("system s", "format fp64") + body + (step,)) + "\n"


_MAP = ("state x",)
REFUSALS = {
    "character": (_src("state x", "; a form feed \x0c in a comment",
                       "next x = x"), 4),
    "syntax": (_src("state x", "next x = x +"), 4),
    "too-deep": (_src("state x", "next x = " + "(" * 101 + "x" + ")" * 101),
                 4),
    "constant-range": (_src("state x", "next x = x * 1e400000"), 4),
    "missing-system": ("format fp64\nstate x\nnext x = x\nstep map\n", None),
    "missing-format": ("system s\nstate x\nnext x = x\nstep map\n", None),
    "missing-state": ("system s\nformat fp64\nstep map\n", None),
    "missing-step": ("system s\nformat fp64\nstate x\nnext x = x\n", None),
    "duplicate-declaration": (_src("format fp64", "state x", "next x = x"), 3),
    "unknown-format": ("system s\nformat fp80\nstate x\nnext x = x\n"
                       "step map\n", 2),
    "unknown-rounding": (_src("round rnd", "state x", "next x = x"), 3),
    "unknown-integrator": (_src("state x", "d/dt x = x",
                                step="step rk45, h = 1/8"), 5),
    "duplicate-name": (_src("state x", "param x = 1", "next x = x"), 4),
    "reserved-name": (_src("state fma", "next fma = 1"), 3),
    "undefined-name": (_src("state x", "next x = x * gamma"), 4),
    "array-length": (_src("state x[0]", "next x[i] = 1"), 3),
    "lane-capacity": (_src("state x[20000], y[20000]", "next x[i] = x[i]",
                           "next y[i] = y[i]"), 3),
    "unused": (_src("state x", "const c = 2", "next x = x"), 4),
    "cycle": (_src("state x", "const a = b + 1", "const b = a * 2",
                   "next x = x * a"), 5),
    "not-constant": (_src("state x", "param p = x", "next x = x * p"), 4),
    "bank-capacity": (_src("state x", "next x = x * " + " * ".join(
        str(k) for k in range(1, 514))), None),
    "missing-equation": (_src("state x, y", "next x = y"), 3),
    "duplicate-equation": (_src("state x", "next x = x", "next x = 2 * x"), 5),
    "mixed-equations": (_src("state x, y", "next x = y", "d/dt y = x"), 5),
    "not-state": (_src("state x", "param p = 1", "next x = p", "next p = 1"),
                  6),
    "integrator-mismatch": (_src("state x", "next x = x",
                                 step="step rk4, h = 1/8"), 5),
    "index-range": (_src("state x[3]", "next x[i] = x[i+1]"), 4),
    "index-not-integer": (_src("state x[4] cyclic", "next x[i] = x[i/2]"), 4),
    "array-index": (_src("state x[3]", "next x[i] = x"), 4),
    "unbound-index": (_src("state x[3]", "next x[j+1] = 1"), 4),
    "missing-step-size": (_src("state x", "d/dt x = -x", step="step rk4"), 5),
    "step-size-zero": (_src("state x", "d/dt x = -x",
                            step="step rk4, h = 1 - 1"), 5),
    "h-nonlinear": (_src("state x", "next x = x * (h * h)",
                         step="step map, h = 1/8"), 4),
    "h-scope": (_src("state x", "d/dt x = h * x",
                     step="step euler, h = 1/8"), 4),
    "step-option": (_src("state x", "d/dt x = -x",
                         step="step rk4, h = 1/8, q = (x)"), 5),
    "verlet-partition": (_src("state x, p", "d/dt x = p", "d/dt p = -x",
                              step="step stormer-verlet, h = 1/8, "
                                   "q = (x), p = (x)"), 6),
    "verlet-not-separable": (_src("state x, p", "d/dt x = p + x",
                                  "d/dt p = -x",
                                  step="step stormer-verlet, h = 1/8, "
                                       "q = (x), p = (p)"), 4),
    "runtime-division": (_src("state x", "next x = x / 3"), 4),
    "runtime-sqrt": (_src("state x", "next x = sqrt(x)"), 4),
    "transcendental": (_src("state x", "next x = exp(x)"), 4),
    "irrational-constant": (_src("state x", "next x = x * sqrt(2)"), 4),
    "power": (_src("state x", "next x = x^2"), 4),
    "not-equal": (_src("state x", "next x = select(x != 1, 1, 2)"), 4),
    "chained-comparison": (_src("state x", "next x = 0 < x < 1"), 4),
    "time-dependence": (_src("state x", "d/dt x = t",
                             step="step euler, h = 1/8"), 4),
    "unknown-function": (_src("state x", "next x = foo(x)"), 4),
    "arity": (_src("state x", "next x = fma(x, x)"), 4),
    "constant-negative-zero": (_src("state x", "next x = x + -0"), 4),
    "constant-infinity": (_src("state x", "next x = x * inf"), 4),
    "constant-nan": (_src("state x", "next x = x + nan"), 4),
    "constant-division-by-zero": (_src("state x", "next x = x * (1/0)"), 4),
    "constant-overflow": (_src("state x", "next x = x * 1e400"), 4),
    "constant-rounds-to-zero": (_src("state x", "next x = x * 1e-400"), 4),
}


def _mismatched_expansion():
    """A flow's canonical form with one let of its expansion changed:
    (text, the changed line)."""
    g = compile_(_src("state x", "d/dt x = -x", step="step rk4, h = 1/8"))
    lines = lang.render_canonical(g).splitlines()
    k = next(i for i, ln in enumerate(lines)
             if ln.strip().startswith("let Y2.x ="))
    assert "fma(h/2, k1.x, x)" in lines[k]
    lines[k] = lines[k].replace("fma(h/2,", "fma(h,")
    return "\n".join(lines) + "\n", k + 1


@pytest.mark.parametrize("name", sorted(REFUSALS) + ["expansion-mismatch"])
def test_each_refusal_by_name(name):
    if name == "expansion-mismatch":
        text, line = _mismatched_expansion()
    else:
        text, line = REFUSALS[name]
    with pytest.raises(lang.Refusal) as info:
        compile_(text, "probe.cftl")
    r = info.value
    assert r.name == name, str(r)
    assert r.line == line, str(r)
    assert r.source == "probe.cftl"
    assert str(r).startswith("probe.cftl")
    assert r.sentence


def test_a_long_chain_costs_no_depth():
    """A sum of 3,000 terms - a left-deep chain 3,000 operations long - is
    checked, written out and read back in loops, not frames; a chain of
    lets that long is refused by name, never a bare RecursionError."""
    g = compile_(_src("state x", "next x = x" + " + x" * 3000))
    assert g.op_counts() == {"add": 3000}
    assert compile_(lang.render_canonical(g)).to_bytes() == g.to_bytes()
    assert MathForm(lang.render_math(g)).step([F(1, 3)]) == [F(3001, 3)]
    lets = [f"let r{k} = r{k - 1} + 1" for k in range(1, 2001)]
    with pytest.raises(lang.Refusal) as info:
        compile_(_src("state x", "let r0 = x", *lets, "next x = r2000"))
    assert info.value.name == "too-deep"


def test_the_class_carries_the_compilers_names():
    """The compiler raises its seven through this one class: each is
    accepted, and a name in neither list is an internal error."""
    for name in lang.COMPILER_REFUSALS:
        r = lang.Refusal(name, "a sentence", 3, "x.cftl")
        assert str(r) == f"x.cftl:3: {name}: a sentence"
    assert {"segment-steps", "halving-underflow", "target-format",
            "target-feature", "program-capacity", "scratch-capacity",
            "loader-bound"} == set(lang.COMPILER_REFUSALS)
    assert not set(lang.COMPILER_REFUSALS) & set(lang.CATALOGUE)
    with pytest.raises(AssertionError):
        lang.Refusal("no-such-name", "x")


def test_a_constant_output_is_refused_at_its_equation():
    """A right-hand side that is itself a constant is rounded once where
    it becomes the step's output, and refused at its own line."""
    with pytest.raises(lang.Refusal) as info:
        compile_(_src("state x, y", "next x = y", "next y = 1e400"))
    assert (info.value.name, info.value.line) == ("constant-overflow", 5)


def _l63():
    return ref("lorenz63-rk4-fp64")


RUN_REFUSALS = {
    "lane-shape": lambda: lang.run(_l63(), [[0, 0]], 1),
    "lane-value": lambda: lang.run(_l63(), [[0, 0, 1 << 64]], 1),
    "unknown-param": lambda: lang.run(_l63(), [[0, 0, 0]], 1,
                                      params={"gamma": 1}),
    "param-value": lambda: lang.run(_l63(), [[0, 0, 0]], 1,
                                    params={"sigma": 0.5}),
    "step-count": lambda: lang.run(_l63(), [[0, 0, 0]], -1),
    "step-size-sign": lambda: lang.run(_l63(), [[0, 0, 0]], 1,
                                       h=F(-1, 100)),
    "graph-format": lambda: lang.StepGraph.from_bytes(b"{}"),
}


@pytest.mark.parametrize("name", sorted(RUN_REFUSALS))
def test_each_run_refusal_by_name(name):
    with pytest.raises(lang.Refusal) as info:
        RUN_REFUSALS[name]()
    assert info.value.name == name, str(info.value)
    assert info.value.line is None


def test_a_tampered_graph_is_refused():
    """Bytes whose encoding is not its exact value rounded once, or that
    are not canonical, are not a step graph."""
    data = ref("lorenz63-rk4-fp64").to_bytes()
    bad = data.replace(b"0x3f847ae147ae147b", b"0x3f847ae147ae147c", 1)
    with pytest.raises(lang.Refusal) as info:
        lang.StepGraph.from_bytes(bad)
    assert info.value.name == "graph-format"
    with pytest.raises(lang.Refusal) as info:
        lang.StepGraph.from_bytes(data.replace(b",", b", ", 1))
    assert info.value.name == "graph-format"


def test_every_catalogued_name_is_made_by_a_test():
    made = set(REFUSALS) | {"expansion-mismatch"} | set(RUN_REFUSALS)
    assert made == set(lang.CATALOGUE)


def test_the_documents_table_is_the_catalogue():
    """docs/LANGUAGE.md names every refusal - the checker's and the
    compiler's - in its tables, and no other."""
    text = DOC.read_text(encoding="utf-8")
    section = text.split("## Every refusal, by name", 1)[1].split("\n## ", 1)[0]
    names = set(re.findall(r"^\| `([a-z0-9-]+)` \|", section, re.M))
    assert names == set(lang.CATALOGUE) | set(lang.COMPILER_REFUSALS)


_POOL = ["x", "y", "(", ")", "*", "-", "+", "/", "1", "0", ".", "[", "]",
         ",", "=", " ", "\n", "h", "fma", "e", "i", "<", ";", "x[i]", "-0",
         "nan", "d/dt", "next", "let r = ", "2/0", "\r", "\r\n", "\x0c",
         " ", "﻿", "\x00", "é", "\t"]


@pytest.mark.parametrize("name", ["lorenz63-rk4-fp64", "lorenz96-rk4-fp64",
                                  "henonheiles-lf-fp64"])
def test_mutations_compile_or_refuse_by_name(name):
    """Seeded edits of a reference - characters deleted, inserted and
    replaced, lines dropped and doubled. Each result compiles or is a
    Refusal; nothing else may escape the parser or the checker."""
    text = (SYSTEMS / f"{name}.cftl").read_text()
    rng = random.Random(f"mutate {name}")
    count = 60 if name.startswith("lorenz96") else 150
    outcomes = {}
    for _ in range(count):
        t = text
        for _k in range(rng.randint(1, 3)):
            i = rng.randrange(len(t) + 1)
            how = rng.randrange(5)
            if how == 0 and t:
                t = t[:i] + t[i + 1:]
            elif how == 1:
                t = t[:i] + rng.choice(_POOL) + t[i:]
            elif how == 2 and t:
                t = t[:i] + rng.choice(_POOL) + t[i + 1:]
            else:
                lines = t.split("\n")
                j = rng.randrange(len(lines))
                if how == 3:
                    del lines[j]
                else:
                    lines.insert(j, lines[j])
                t = "\n".join(lines)
        try:
            compile_(t)
            outcomes["compiled"] = outcomes.get("compiled", 0) + 1
        except lang.Refusal as r:
            assert r.name in lang.CATALOGUE
            outcomes[r.name] = outcomes.get(r.name, 0) + 1
    assert sum(outcomes.values()) == count
    assert len(outcomes) > 3


# ---- determinism -------------------------------------------------------------

def test_the_same_source_gives_the_same_bytes():
    for name in REFS:
        text = (SYSTEMS / f"{name}.cftl").read_text()
        assert compile_(text).to_bytes() == compile_(text).to_bytes()


def test_the_bytes_do_not_depend_on_the_hash_seed():
    """Each reference's graph digest in two fresh interpreters with
    different PYTHONHASHSEEDs, against this process's."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]);"
            "from cft_golden import lang;"
            "print(' '.join(lang.load(p).graph.digest() "
            "for p in sys.argv[2:]))")
    paths = [str(SYSTEMS / f"{n}.cftl") for n in REFS]
    here = " ".join(ref(n).digest() for n in REFS)
    for seed in ("0", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, "-c", code, str(HERE.parent)]
                             + paths, capture_output=True, text=True,
                             env=env, check=True)
        assert out.stdout.split() == here.split()


def test_a_written_out_expansion_is_accepted():
    """A flow whose source carries its expansion block, as the canonical
    form writes it, compiles to the graph the flow alone gives - so a
    writer may pin an expansion in a source."""
    for name in REFS:
        g = ref(name)
        assert compile_(lang.render_canonical(g)).to_bytes() == g.to_bytes()


# ---- the intention-out -----------------------------------------------------------

def _point(g, rng):
    def q():
        return F(rng.randint(-9, 9), rng.randint(1, 7))
    return ([q() for _ in range(g.n_state)], [q() for _ in g.param],
            [q() for _ in g.lane])


_UNICODE_GREEK = {}
for _n in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta",
           "theta", "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron",
           "pi", "rho", "sigma", "tau", "upsilon", "phi", "chi", "psi",
           "omega"):
    _u = "LAMDA" if _n == "lambda" else _n.upper()    # Unicode's spelling
    _UNICODE_GREEK[_n] = unicodedata.lookup(f"GREEK SMALL LETTER {_u}")
    _UNICODE_GREEK[_n.capitalize()] = unicodedata.lookup(
        f"GREEK CAPITAL LETTER {_u}")


def _glyph(name):
    """A name as the mathematical form should print it - from Unicode's
    own table, not the renderer's."""
    base, bracket, rest = name.partition("[")
    return _UNICODE_GREEK.get(base, base) + bracket + rest


# The names the intention-out restates, from IEEE 754-2019 (4.3, the
# rounding-direction attributes; 3.6, the binary interchange formats) and
# from the integrators' own names - the test's tables, not the renderer's.
ATTR_754 = {"rne": "roundTiesToEven", "rtz": "roundTowardZero",
            "rdn": "roundTowardNegative", "rup": "roundTowardPositive",
            "rmm": "roundTiesToAway"}
BINARY = {"fp32": "binary32", "fp64": "binary64", "fp128": "binary128",
          "fp256": "binary256"}
SCHEME = {"euler": "the forward Euler method (euler)",
          "rk4": "the classical Runge-Kutta method (rk4)",
          "stormer-verlet": "Stormer-Verlet, drift-kick-drift "
                            "(stormer-verlet)",
          "map": "the map (map)"}


class _Lines:
    """A form's lines, read in order, each held to what is expected: a
    line the reader does not expect, or one left over, fails."""

    def __init__(self, text, what):
        assert text.endswith("\n"), f"the {what} does not end its last line"
        self.lines = text[:-1].split("\n")
        self.k = 0
        self.what = what

    def peek(self):
        return self.lines[self.k] if self.k < len(self.lines) else None

    def take(self, want=None):
        assert self.k < len(self.lines), f"the {self.what} ends early"
        line = self.lines[self.k]
        assert want is None or line == want, \
            f"{self.what} line {self.k + 1}: {line!r}, where {want!r}"
        self.k += 1
        return line

    def after(self, head):
        """The rest of the next line, which must start with `head`."""
        line = self.take()
        assert line.startswith(head), \
            f"{self.what} line {self.k}: {line!r} does not start {head!r}"
        return line[len(head):]

    def done(self):
        assert self.k == len(self.lines), \
            f"{self.what} line {self.k + 1}, {self.lines[self.k]!r}, is " \
            f"one the test does not expect"


def _counts_said(text, sec):
    """`53 (26 fma, 3 add, ...)` against the section's own nodes, or `0`
    for a section of none."""
    if not sec.nodes:
        assert text == "0", text
        return
    m = re.fullmatch(r"(\d+) \(([^)]*)\)", text)
    assert m, text
    mine = {}
    for op, _a, _l in sec.nodes:
        mine[op] = mine.get(op, 0) + 1
    said = {}
    for part in m.group(2).split(", "):
        n, op = part.split(" ")
        assert op not in said and int(n) > 0
        said[op] = int(n)
    assert int(m.group(1)) == len(sec.nodes) and said == mine


def _encoding_said(fmt, bits_text, hex_text, bits):
    """An encoding, in hex and as a hexadecimal significand."""
    assert bits_text == "0x" + format(bits, f"0{fmt.width // 4}x")
    assert chars.from_hex(fmt, hex_text, sf.RND_RNE)[0] == bits


def _check_described(fmt, value, bits, flags, desc):
    """`exact`, or `inexact[, underflow], relative error +x.xxxxe-yy`,
    against the test's own relative error, to 1e-4 relative (a last
    printed digit off by one can pass: verifier-VL1)."""
    if desc == "exact":
        assert flags == 0 and C.value_of(fmt, bits) == value
        return
    m = re.fullmatch(r"(inexact|underflow|inexact, underflow), relative "
                     r"error ([+-]\d\.\d{4}e[+-]\d+)", desc)
    assert m, desc
    words = m.group(1).split(", ")
    assert ("inexact" in words) == bool(flags & sf.FLAG_INEXACT)
    assert ("underflow" in words) == bool(flags & sf.FLAG_UNDERFLOW)
    true = (C.value_of(fmt, bits) - value) / value
    printed = Fraction(m.group(2))
    assert (printed > 0) == (true > 0)
    assert abs(printed - true) <= abs(true) * Fraction(1, 10 ** 4)


def _default_said(g, comment, value, bits, flags):
    """A param's or a lane param's comment: its default's encoding."""
    bits_text, hex_text, *desc = comment.split()
    _encoding_said(g.fmt, bits_text, hex_text, bits)
    _check_described(g.fmt, value, bits, flags, " ".join(desc))


def check_canonical_said(g, canon):
    """Every comment of the canonical form, line by line: the system's
    name, the sha256 line (the test's own sha256 of the graph's bytes),
    the attribute and the format each time they are named, the
    operation counts, each constant's spelling, exact value, encoding,
    flags and relative error, the h-scaled list, each param's and lane
    param's default; and no comment on any other line. The code between
    is held by the round trips."""
    fmt, attr = g.fmt.name, g.round_name
    r = _Lines(canon, "canonical form")
    r.take(f"; {g.system} - the canonical form, regenerated from the step "
           f"graph")
    r.take(f"; sha256 {hashlib.sha256(g.to_bytes()).hexdigest()}")
    r.take(";")
    r.take("; Read back, this text gives the same step graph, byte for "
           "byte. Every")
    r.take("; operation is written once, in the order it is performed; each "
           "one")
    r.take(f"; that rounds rounds once, under {attr} ({ATTR_754[attr]}), in "
           f"{BINARY[fmt]}.")
    r.take(";")
    if g.is_flow:
        said = r.after("; operations: the equations ")
        assert said.endswith(";")
        _counts_said(said[:-1], g.field)
        _counts_said(r.after(";             a step "), g.step)
    else:
        _counts_said(r.after("; operations: a step "), g.step)
    r.take(";")
    if not g.const:
        r.take("; constants: none")
    else:
        r.take(f"; constants, exact value -> {BINARY[fmt]} under {attr}:")
        for value, factor, bits, flags in g.const:
            name, exact_text, bits_text, hex_text, *desc = \
                r.after(";   ").split()
            if factor is None:
                assert lang_check.constant_of(name) == value
            else:
                # h/2 is its factor times h: read with h as 1, and the
                # value is that factor times the graph's own h
                assert lang_check.constant_of(name.replace("h", "(1)")) \
                    == factor
                assert value == factor * g.integrator[1]
            assert lang_check.constant_of(exact_text) == value
            assert C.round_once(g.fmt, g.rnd, value) == (bits, flags)
            _encoding_said(g.fmt, bits_text, hex_text, bits)
            _check_described(g.fmt, value, bits, flags, " ".join(desc))
        scaled = [fa for _v, fa, _b, _f in g.const if fa is not None]
        if scaled:
            items = r.after("; h-scaled, halved by a step-halving bank: ")
            assert [lang_check.constant_of(t.replace("h", "(1)"))
                    for t in items.split(", ")] == scaled
    r.take("")
    params = {name: (value, bits, flags) for name, value, bits, flags
              in g.param}
    lanes = {name: (value, bits) for name, value, bits in g.lane}
    seen = []
    while r.peek() is not None:
        line = r.take()
        if ";" not in line:
            continue
        code, comment = line.split(";", 1)
        words = code.split()
        if words[:1] == ["param"]:
            name = words[1]
            _default_said(g, comment, *params[name])
        elif words[:2] == ["lane", "param"]:
            name = words[2]
            value, bits = lanes[name]
            if value is None:
                assert comment == " no default: each lane gives it"
            else:
                rounded, flags = C.round_once(g.fmt, g.rnd, value)
                assert rounded == bits
                _default_said(g, comment, value, bits, flags)
        else:
            raise AssertionError(f"a comment on a line of code: {line!r}")
        seen.append(name)
    assert sorted(seen) == sorted(list(params) + list(lanes))
    r.done()


def check_math_said(g, math):
    """Every line of the mathematical form but its expressions, which
    check 2 evaluates: the title and the header (format and attribute),
    the fixed sentences word for word, each param's and lane param's
    name and default, each let's name, each state component's name
    wherever it is printed, the integrator's name, h's value and the
    vectors Y, Q and P - each name against Unicode's own Greek letters."""
    fmt, attr = g.fmt.name, g.round_name
    integ, h, options = g.integrator
    comps = g.components()
    r = _Lines(math, "mathematical form")
    r.take(f"{g.system} - the mathematical form, regenerated from the step "
           f"graph")
    r.take(f"{BINARY[fmt]} ({fmt}), {ATTR_754[attr]}")
    r.take("")
    r.take("Each operation here is exact. The program performs the same")
    r.take("operations, each rounded once, in the order the canonical form")
    r.take("writes them.")
    r.take("")

    def value_of(name):
        return mathform_constant(r.after(f"  {_glyph(name)} = "))
    if g.param:
        r.take("parameters, the run's (defaults)")
        for name, value, _b, _f in g.param:
            assert value_of(name) == value
        r.take("")
    if g.lane:
        r.take("lane parameters, each lane's (defaults)")
        for name, value, _b in g.lane:
            if value is None:
                r.take(f"  {_glyph(name)}")
            else:
                assert value_of(name) == value
        r.take("")
    sec = g.field if g.is_flow else g.step
    labels = [lb for _o, _a, lb in sec.nodes if lb is not None]
    if labels:
        r.take("where")
        for lb in labels:
            r.after(f"  {_glyph(lb)} = ")
        r.take("")
    y = "  Y = (" + ", ".join(_glyph(c) for c in comps) + ")"
    if g.is_flow:
        r.take("the equations")
        for c in comps:
            r.after(f"  d{_glyph(c)}/dt = ")
        r.take("")
        if integ == "stormer-verlet":
            r.take(f"one step: {SCHEME[integ]}, with v the right-hand sides "
                   f"of dQ/dt and a those of dP/dt")
        else:
            r.take(f"one step: {SCHEME[integ]}, with f the right-hand sides "
                   f"above")
        assert value_of("h") == h
        r.take(y)
        if integ == "stormer-verlet":
            for key, vec in (("q", "Q"), ("p", "P")):
                names = [c for d in options[key] for c in comps
                         if c == d or c.startswith(d + "[")]
                r.take(f"  {vec} = (" + ", ".join(_glyph(c) for c in names)
                       + ")")
        # the scheme's own lines, which check 2 evaluates
        while r.peek() is not None:
            assert re.fullmatch(r"  \S+ (=|↦) .+", r.take())
    else:
        r.take(f"one step: {SCHEME['map']}")
        if h is not None:
            assert value_of("h") == h
        r.take(y)
        for c in comps:
            r.after(f"  {_glyph(c)} ↦ ")
    r.done()


def check_comments(g, canon, math):
    """What the intention-out says besides its code, every line of it,
    read back and held to the graph and to the test's own arithmetic
    and tables (docs/LANGUAGE.md, the third check). A line that cannot
    even be read is a failure of the same kind."""
    try:
        check_canonical_said(g, canon)
        check_math_said(g, math)
    except AssertionError:
        raise
    except Exception as e:  # noqa: BLE001 - a form the reader cannot read
        raise AssertionError(f"what the intention-out says cannot be read: "
                             f"{type(e).__name__}: {e}") from e


def check_intention_out(g, rng, points=3):
    canon = lang.render_canonical(g)
    again = compile_(canon, "canonical")
    assert again.to_bytes() == g.to_bytes(), "the canonical form parses " \
        "back to a different graph"
    assert lang.render_canonical(again) == canon, "the canonical text, " \
        "comments included, does not come back the same"
    math = lang.render_math(g)
    check_comments(g, canon, math)
    form = MathForm(math)
    for _ in range(points):
        state, params, lanes = _point(g, rng)
        if g.is_flow:
            assert form.field(state, params, lanes) == \
                g.exact_eval("field", state, params, lanes)
        assert form.step(state, params, lanes) == \
            g.exact_eval("step", state, params, lanes)


@pytest.mark.parametrize("name", REFS)
def test_intention_out_of_the_references(name):
    check_intention_out(ref(name), random.Random(f"io {name}"))


# Greek names in every place a name is printed - params, lane params with
# and without defaults, lets and an indexed let, state components, q and
# p - each integrator, and an h-scaled constant in a map: what the
# random systems (named p0, l0, s0 ...) never print as a letter
# (verifier-VL1's map first: its lane default printed as 2/3 for 1/3
# passed the check before 2026-10-01).
NAMED_SYSTEMS = {
    "vl1-map": ("system g\nformat fp64\nstate x\nparam sigma = 2\n"
                "lane param rho = 1/3, beta\nlet theta = x * x\n"
                "next x = fma(theta, rho, beta) * sigma\nstep map\n"),
    "pendulum-rk4": ("system pendulum\nformat fp128\nround rdn\n"
                     "state Theta, omega\nparam gamma = 1/10\n"
                     "lane param mu = 2/3\nlet phi = mu * Theta\n"
                     "d/dt Theta = omega\n"
                     "d/dt omega = -(phi + gamma * omega)\n"
                     "step rk4, h = 1/64\n"),
    "sv": ("system sv\nformat fp32\nround rup\nstate xi, pi\n"
           "lane param kappa\nd/dt xi = pi\nd/dt pi = -(kappa * xi)\n"
           "step stormer-verlet, h = 0.01, q = (xi), p = (pi)\n"),
    "eta-map": ("system wave\nformat fp256\nround rmm\nstate eta[3] cyclic\n"
                "lane param nu = 3\nlet Delta[i] = eta[i+1] - eta[i] "
                "for i in 0..2\nnext eta[i] = fma(h * nu, Delta[i], eta[i])\n"
                "step map, h = 1/2\n"),
    "euler": ("system decay\nformat fp64\nround rtz\nstate lambda\n"
              "param tau = 1/3\nd/dt lambda = -(tau * lambda)\n"
              "step euler, h = 1/8\n"),
}


@pytest.mark.parametrize("name", sorted(NAMED_SYSTEMS))
def test_intention_out_of_named_systems(name):
    g = compile_(NAMED_SYSTEMS[name], name)
    check_intention_out(g, random.Random(f"io {name}"))


_LITS = ["1", "2", "3", "0.5", "0.25", "1.5", "(1/3)", "(2/7)", "(5/3)",
         "0.1", "7"]
_CMPS = ["<", "<=", ">", ">=", "=="]


def _expr(rng, operands, depth):
    if depth <= 0 or rng.random() < 0.25:
        return rng.choice(operands + _LITS[:3])
    k = rng.choice(["+", "-", "*", "neg", "fma", "abs", "copysign", "min",
                    "max", "minnum", "maxnum", "cmp", "select", "const"])

    def sub():
        return _expr(rng, operands, depth - 1)
    if k in ("+", "-", "*"):
        return f"({sub()} {k} {sub()})"
    if k == "neg":
        return f"-({sub()})"
    if k == "fma":
        return f"fma({sub()}, {sub()}, {sub()})"
    if k == "abs":
        return f"abs({sub()})"
    if k in ("copysign", "min", "max", "minnum", "maxnum"):
        return f"{k}({sub()}, {sub()})"
    if k == "cmp":
        return f"({sub()} {rng.choice(_CMPS)} {sub()})"
    if k == "select":
        return f"select({sub()}, {sub()}, {sub()})"
    return (f"({rng.choice(_LITS)} {rng.choice(['+', '-', '*', '/'])} "
            f"{rng.choice(_LITS)})")


def random_system(rng, k):
    """A random system the language takes: every operation, constants
    folded, lets, params and lane params, an array, each integrator."""
    integ = rng.choice(["rk4", "euler", "stormer-verlet", "map", "maph"])
    fmt = rng.choice(["fp32", "fp64", "fp128", "fp256"])
    rnd = rng.choice(["rne", "rtz", "rdn", "rup", "rmm"])
    lines = [f"system r{k}", f"format {fmt}", f"round {rnd}"]
    params = [f"p{i}" for i in range(rng.randint(0, 2))]
    lanes = [f"l{i}" for i in range(rng.randint(0, 1))]
    consts = [f"c{i}" for i in range(rng.randint(0, 2))]
    if params:
        lines.append("param " + ", ".join(f"{p} = {rng.choice(_LITS)}"
                                          for p in params))
    for ln in lanes:
        lines.append(f"lane param {ln}"
                     + (f" = {rng.choice(_LITS)}" if rng.random() < 0.5
                        else ""))
    for c in consts:
        lines.append(f"const {c} = {rng.choice(_LITS)} * {rng.choice(_LITS)}")
    extra = params + consts + lanes
    h = rng.choice(["1/8", "0.01", "1/3"])
    if integ == "stormer-verlet":
        nq = rng.randint(1, 2)
        qs = [f"q{i}" for i in range(nq)]
        ms = [f"m{i}" for i in range(nq)]
        lines.append("state " + ", ".join(qs + ms))
        eqs = []
        for q in qs:
            eqs.append(f"d/dt {q} = {_expr(rng, ms + extra, 2)}")
        for m in ms:
            eqs.append(f"d/dt {m} = {_expr(rng, qs + extra, 3)}")
        if extra:
            eqs[0] += " + " + " + ".join(extra)
        lines += eqs
        lines.append(f"step stormer-verlet, h = {h}, q = ({', '.join(qs)}),"
                     f" p = ({', '.join(ms)})")
        return "\n".join(lines) + "\n"
    scal = [f"s{i}" for i in range(rng.randint(1, 3))]
    arr = None
    if rng.random() < 0.4:
        arr = (rng.randint(2, 4), rng.random() < 0.5)
    decl = scal + ([f"a[{arr[0]}]" + (" cyclic" if arr[1] else "")]
                   if arr else [])
    lines.append("state " + ", ".join(decl))
    word = "next" if integ.startswith("map") else "d/dt"
    operands = scal + extra + (["h", "(h/2)"] if integ == "maph" else [])
    lets = [f"r{i}" for i in range(rng.randint(0, 2))]
    for i, r in enumerate(lets):
        lines.append(f"let {r} = {_expr(rng, operands + lets[:i], 2)}")
    eqs = []
    for s in scal:
        eqs.append(f"{word} {s} = "
                   f"{_expr(rng, operands + lets + (['a[0]'] if arr else []), 3)}")
    if arr:
        near = ["a[i]"] + (["a[i+1]", "a[i-1]"] if arr[1] else [])
        eqs.append(f"{word} a[i] = {_expr(rng, near + scal + extra, 2)}")
    used = extra + lets + (["h"] if integ == "maph" else [])
    if used:
        eqs[0] += " + " + " + ".join(used)
    lines += eqs
    if integ == "map":
        lines.append("step map")
    elif integ == "maph":
        lines.append(f"step map, h = {h}")
    else:
        lines.append(f"step {integ}, h = {h}")
    return "\n".join(lines) + "\n"


# A random source may fold to a constant the language refuses: -0 where
# a negated subexpression is exactly zero, or a constant mixing h with a
# rational. Those are skipped and counted; any other refusal fails.
_ARTIFACTS = {"constant-negative-zero", "h-nonlinear"}


def test_intention_out_of_random_systems():
    rng = random.Random("lang random systems")
    done = skipped = 0
    kinds, ops, fmts, rnds = set(), set(), set(), set()
    arrays = lanes = lets = 0
    while done < 60:
        text = random_system(rng, done + skipped)
        try:
            g = compile_(text, f"random-{done + skipped}")
        except lang.Refusal as r:
            assert r.name in _ARTIFACTS, f"{r}\n{text}"
            skipped += 1
            continue
        try:
            check_intention_out(g, rng, points=2)
        except AssertionError:
            raise AssertionError(f"the intention-out fails on:\n{text}")
        kinds.add(g.integrator[0])
        ops.update(g.op_counts("step"))
        fmts.add(g.fmt.name)
        rnds.add(g.round_name)
        arrays += any(ln for _n, ln in g.state)
        lanes += bool(g.lane)
        lets += any(lb and "." not in lb
                    for _o, _a, lb in (g.field or g.step).nodes)
        done += 1
    assert skipped < done
    # the coverage docs/LANGUAGE.md claims of these systems, held
    assert kinds == {"rk4", "euler", "stormer-verlet", "map"}
    assert ops == set(lang.OPS)
    assert fmts == set(FORMATS) and rnds == set(C.RND_BY_NAME)
    assert arrays and lanes and lets


# ---- verifier-VL1's cases (the send-back of 2026-10-01) ----------------------------

F1_CASES = [  # format, attribute, the const's expression, its exact value
    ("fp256", "rne", "abs(1/(3*h)) * h", F(1, 3)),
    ("fp64", "rup", "abs(1/(3*h)) * h", F(1, 3)),
    ("fp256", "rne", "copysign(1/(3*h), 1) * h", F(1, 3)),
    ("fp256", "rne", "abs(1e-400/h) * h", F(1, 10 ** 400)),
    ("fp256", "rne", "abs(1e600/h) * h", F(10 ** 600)),
]


@pytest.mark.parametrize("fmtname,rnd,expr,value", F1_CASES)
def test_f1_a_constant_through_a_power_of_h_is_exact(fmtname, rnd, expr,
                                                      value):
    """abs and copysign of a negative power of h once went through
    binary64 (1 ** -1 is the float 1.0): binary64's 1/3 at fp256, the
    wrong RU at fp64, +0 for 1e-400/h, a bare OverflowError for 1e600/h.
    Each is now its exact value rounded once."""
    g = compile_(f"system s\nformat {fmtname}\nround {rnd}\nstate x\n"
                 f"const c = {expr}\nd/dt x = c * x\n"
                 f"step euler, h = 1/100\n")
    got = [(v, b) for v, fa, b, _f in g.const if fa is None]
    want = C.round_once(FORMATS[fmtname], C.RND_BY_NAME[rnd], value)[0]
    assert got == [(value, want)]


def test_f1_no_float_reaches_the_constant_code():
    """A sweep over every power of h from -3 to 3, both signs of h, abs
    and copysign of both signs: each result exact, as the test computes
    it. The guard that would stop a float is there (K and round_once
    refuse one), and the sweep never reaches it."""
    fmt = FORMATS["fp256"]
    for h_text, h in (("1/100", F(1, 100)), ("-1/64", F(-1, 64))):
        for d in range(-3, 4):
            if d > 0:
                hd, back = "(" + "*".join(["h"] * d) + ")", \
                    "(1/(" + "*".join(["h"] * d) + "))"
            elif d < 0:
                hd, back = "(1/(" + "*".join(["h"] * -d) + "))", \
                    "(" + "*".join(["h"] * -d) + ")"
            else:
                hd, back = "(h/h)", "(h/h)"     # h^0, written with h
            for c_text, c in (("(1/3)", F(1, 3)), ("(-2/7)", F(-2, 7))):
                cases = {f"abs({c_text} * {hd}) * {back}":
                         abs(c * h ** d) / h ** d}
                for s_text, s in (("1", 1), ("-1", -1)):
                    cases[f"copysign({c_text} * {hd}, {s_text}) * {back}"] = \
                        abs(c * h ** d) * s / h ** d
                for expr, value in cases.items():
                    g = compile_(f"system s\nformat fp256\nstate x\n"
                                 f"const k = {expr}\nnext x = k * x\n"
                                 f"step map, h = {h_text}\n")
                    got = [(v, b) for v, fa, b, _f in g.const]
                    assert got == [(value, C.round_once(fmt, sf.RND_RNE,
                                                        value)[0])], expr
    with pytest.raises(AssertionError):
        lang_check.K(0.5)
    with pytest.raises(AssertionError):
        C.round_once(fmt, sf.RND_RNE, 0.5)


@pytest.mark.parametrize("fmtname,body,want", [
    ("fp128", "next x = x * 1e4400", "compiles"),
    ("fp256", "next x = x * 1e-5000", "compiles"),
    ("fp256", "next x = x * 1e5000", "compiles"),
    ("fp256", "next x = x * 3" + "7" * 4999, "compiles"),
    ("fp64", "next x = x * 1e5000", "constant-overflow"),
    ("fp128", "next x = x * 1" + "0" * 4999, "constant-overflow"),
    ("fp256", "next x = x * 1e300000", "constant-overflow"),
    ("fp256", "next x = x * 1e-300000", "constant-rounds-to-zero"),
    ("fp256", "next x = x * 1e400000", "constant-range"),
])
def test_f2_the_bound_is_the_languages(fmtname, body, want):
    """Python's 4,300-digit int-to-str limit was the working bound: a
    value inside binary128 or binary256 with more digits raised a bare
    ValueError, to compile or to write out. Now a constant compiles,
    writes, renders and reads back at any size inside 2^+-1048576, and a
    refusal past a format names it."""
    text = f"system s\nformat {fmtname}\nstate x\n{body}\nstep map\n"
    if want != "compiles":
        with pytest.raises(lang.Refusal) as info:
            compile_(text)
        assert (info.value.name, info.value.line) == (want, 4)
        assert len(str(info.value)) < 300
        return
    g = compile_(text)
    data = g.to_bytes()
    assert lang.StepGraph.from_bytes(data).to_bytes() == data
    canon = lang.render_canonical(g)
    assert compile_(canon).to_bytes() == data
    lang.render_math(g)


def test_f2_run_values_and_defaults_past_a_format():
    g = ref("lorenz63-rk4-fp64")
    one = sf.one_bits(g.fmt)
    for kw, name in (({"params": {"sigma": 10 ** 5000}}, "constant-overflow"),
                     ({"params": {"sigma": F(1, 3 ** 10000)}},
                      "constant-rounds-to-zero"),
                     ({"h": 10 ** 5000}, "constant-overflow"),
                     ({"params": {"sigma": 2 ** (1 << 21)}}, "constant-range"),
                     ({"params": {"sigma": "1e400000"}}, "constant-range")):
        with pytest.raises(lang.Refusal) as info:
            lang.run(g, [[one] * 3], 1, **kw)
        assert info.value.name == name
        assert len(str(info.value)) < 300
    with pytest.raises(lang.Refusal) as info:
        compile_(_src("state x", "param p = 1e5000", "next x = x * p"))
    assert (info.value.name, info.value.line) == ("constant-overflow", 4)


@pytest.mark.parametrize("k", [101, 102, 1000])
def test_f3_a_run_of_minuses_reads_back(k):
    """102 or more minuses in a row compiled, and their canonical form
    nested 101 parentheses that read back as too-deep. A run is written
    flat now, and reads back at any length."""
    for body in ("-" * k + "x", "-" * k + "x * y"):
        g = compile_(_src("state x, y", f"next x = {body}", "next y = y"))
        assert g.op_counts()["neg"] == k
        canon = lang.render_canonical(g)
        again = compile_(canon)
        assert again.to_bytes() == g.to_bytes()
        assert lang.render_canonical(again) == canon
        form = MathForm(lang.render_math(g))
        point = [F(3, 7), F(-2, 5)]
        assert form.step(point) == g.exact_eval("step", point)


def _l63_graph_variants():
    """Graphs that are not what the language makes, each in the canonical
    JSON layout: what from_bytes must refuse by name."""
    g = ref("lorenz63-rk4-fp64")
    s = g.step
    out = {}
    nodes = list(s.nodes)
    dead = [("mul", ("s0", "s0"), None)] + [
        (op, tuple(f"n{int(a[1:]) + 1}" if a[0] == "n" else a for a in args),
         lb) for op, args, lb in nodes]
    out["a dead node"] = g.copy(step=Section(
        [f"n{int(o[1:]) + 1}" for o in s.out], dead))
    # nodes 8 and 9 read only leaves (sub(p1, s2) and neg(s1)): swapped,
    # every ref still points back, and the order is not the walk's
    assert [a[0] for a in nodes[8][1] + nodes[9][1]] == ["p", "s", "s"]
    swapped = list(nodes)
    swapped[8], swapped[9] = swapped[9], swapped[8]
    remap = {"n8": "n9", "n9": "n8"}
    swapped = [(op, tuple(remap.get(a, a) for a in args), lb)
               for op, args, lb in swapped]
    out["a node order not the walk's"] = g.copy(step=Section(s.out, swapped))
    out["an unreferenced const"] = g.copy(
        const=g.const + [(F(5), None, C.round_once(g.fmt, g.rnd, F(5))[0], 0)])
    out["options on rk4"] = g.copy(integrator=("rk4", g.integrator[1],
                                               {"q": ["x"], "p": ["y", "z"]}))
    two_labels = [(op, args, "k1.x" if lb == "Y2.x" else lb)
                  for op, args, lb in nodes]
    out["one label twice"] = g.copy(step=Section(s.out, two_labels))
    out["a field that is not the step's"] = g.copy(field=Section(
        g.field.out, [(op if op != "sub" else "add", args, lb)
                      for op, args, lb in g.field.nodes]))
    return out


def test_from_bytes_refuses_what_the_language_would_not_make():
    """from_bytes once checked the JSON layout only: a dead node (FLAGS
    0x10 became 0x18), an order not the walk's, a stray const, options
    on the wrong integrator and a field unrelated to its step all came
    back as graphs. Each is refused by name now, and deep JSON too."""
    for what, bad in _l63_graph_variants().items():
        with pytest.raises(lang.Refusal) as info:
            lang.StepGraph.from_bytes(bad.to_bytes())
        assert info.value.name == "graph-format", what
    with pytest.raises(lang.Refusal) as info:
        lang.StepGraph.from_bytes(b"[" * 100000)
    assert info.value.name == "graph-format"
    for name in REFS:
        data = ref(name).to_bytes()
        assert lang.StepGraph.from_bytes(data).to_bytes() == data


@pytest.mark.parametrize("body,name,line", [
    (("state x[32769]", "next x[i] = x[i]"), "array-length", 3),
    (("state x[4.0]", "next x[i] = x[i]"), "array-length", 3),
    (("state x[0x1p+2]", "next x[i] = x[i]"), "array-length", 3),
    (("state x[4] cyclic", "next x[i] = x[i] for i in 0..32768"),
     "index-range", 4),
    (("state x[4]", "lane param a, b", "next x[i] = fma(x[i], a, b)"),
     None, None),
])
def test_arrays_and_ranges_are_bounded(body, name, line):
    """state x[1000000000] once took 1.5 GB in seconds. An array, a range
    and a lane hold at most 32,768 values - the deepest scratch any tile
    publishes - and a length is written as a whole number."""
    text = _src(*body)
    if name is None:
        assert compile_(text).n_state == 4
        return
    with pytest.raises(lang.Refusal) as info:
        compile_(text)
    assert (info.value.name, info.value.line) == (name, line)


def test_the_sentences_made_true():
    # h-scope keeps out a value that moves with h, read directly or
    # through a const; a const whose value does not move is a rational
    g = compile_(_src("state x", "const c = h/h", "d/dt x = c * x",
                      step="step euler, h = 1/8"))
    assert [v for v, _fa, _b, _f in g.const] == [F(1, 8), F(1)]
    for bad in ("d/dt x = (h/h) * x", "d/dt x = c * x"):
        extra = ("const c = h/2",) if "c *" in bad else ()
        with pytest.raises(lang.Refusal) as info:
            compile_(_src("state x", *extra, bad, step="step euler, h = 1/8"))
        assert info.value.name == "h-scope"
    # a decimal reads as chars.lex_decimal reads it; an integer with a
    # leading zero is C's octal, and refused
    for text, value in (("05.5", F(11, 2)), ("007e-3", F(7, 1000)),
                        ("00.25", F(1, 4))):
        assert chars.lex_decimal(FORMATS["fp64"], text)[0] == "finite"
        g = compile_(_src("state x", f"next x = x * {text}"))
        assert [v for v, _fa, _b, _f in g.const] == [value]
    with pytest.raises(lang.Refusal) as info:
        compile_(_src("state x", "next x = x * 05"))
    assert info.value.name == "syntax"
    # a minus written on a zero literal is refused; any other zero is +0
    for body in ("next x[i] = -i * x[i]", "next x[i] = x[i] + -(1 - 1)",
                 "next x[i] = x[i] * -(i - i)"):
        g = compile_(_src("state x[4]", body))
        assert all(b == 0 for v, _fa, b, _f in g.const if v == 0)
    for zero in ("-0", "-(0)", "-0.0", "- -0", "-0x0p+0"):
        with pytest.raises(lang.Refusal) as info:
            compile_(_src("state x", f"next x = x + {zero}"))
        assert info.value.name == "constant-negative-zero"


def test_a_const_read_only_by_the_expansion_block_is_used():
    base = compile_(_src("state x", "d/dt x = -x", step="step euler, h = 1/8"))
    canon = lang.render_canonical(base).replace(
        "step euler, h = 0.125", "const half = h/2\nstep euler, h = 0.125")
    g = compile_(canon.replace("fma(h, ", "fma(2 * half, "))
    assert g.to_bytes() == base.to_bytes()


def test_the_expansion_mismatch_names_the_label():
    """An operand swap at S4.x once was named at the block's first line,
    citing node 0; it is named at its own line, by its label."""
    canon = lang.render_canonical(ref("lorenz63-rk4-fp64"))
    lines = canon.splitlines()
    k = lines.index("  let S4.x = S3.x + k4.x")
    lines[k] = "  let S4.x = k4.x + S3.x"
    with pytest.raises(lang.Refusal) as info:
        compile_("\n".join(lines) + "\n")
    assert (info.value.name, info.value.line) == ("expansion-mismatch", k + 1)
    assert "S4.x" in info.value.sentence


def test_long_chains_anywhere():
    """An index chain of 2,000 terms, and a wide state written out: both
    linear now (render_canonical took 154 s for 30,000 components)."""
    g = compile_(_src("state x[4] cyclic",
                      "next x[i] = x[i" + " + 0" * 2000 + "]"))
    assert g.n_state == 4
    g = compile_(_src("state x[2000]", "next x[i] = x[i] * 2"))
    assert compile_(lang.render_canonical(g)).to_bytes() == g.to_bytes()


def test_run_values_read_as_the_language_reads_them():
    g = ref("lorenz63-rk4-fp64")
    one = sf.one_bits(g.fmt)
    a = lang.run(g, [[one] * 3], 2, params={"sigma": "0x1p-3"})
    b = lang.run(g, [[one] * 3], 2, params={"sigma": F(1, 8)})
    assert a.states == b.states
    with pytest.raises(lang.Refusal) as info:
        lang.run(g, [[one] * 3], 1, params={"sigma": "-0"})
    assert info.value.name == "constant-negative-zero"
    with pytest.raises(lang.Refusal) as info:
        lang.run(g, [[one] * 3], 1, params={"sigma": 3},
                 param_bits={"sigma": one})
    assert info.value.name == "param-value"


# ---- verifier-VL1's re-check (the second send-back of 2026-10-01) ----------------
#
# The text's characters: .cftl holds .cfta's rule (docs/PROGRAMS.md;
# asm.py's lines()), in its words. Before, a lone CR ended a line here and
# in no LF-only reader, so `; rounding: the default<CR>round rdn` compiled
# as rdn while grep showed a comment; and VT, FF, 0x1c-0x1e, NEL, U+2028
# or U+2029 in a comment left the parser at rne where splitlines() showed
# `round rdn`; a byte-order mark was dropped (verifier-VL1).

_RULE_HEAD = "system s\nformat fp64\nstate x\n"
_RULE_TAIL = "next x = x * 3\nstep map\n"
_ANYWHERE = {
    "\r": "a carriage return (0x0d) that is not part of a CRLF line end",
    "\x0b": "a vertical tab (0x0b)",
    "\x0c": "a form feed (0x0c)",
    "\x1c": "a file separator (0x1c)",
    "\x1d": "a group separator (0x1d)",
    "\x1e": "a record separator (0x1e)",
    "\x85": "a next line (U+0085)",
    " ": "a line separator (U+2028)",
    " ": "a paragraph separator (U+2029)",
    "\x00": "a NUL (0x00)",
    "\x1a": "a Ctrl-Z (0x1a)",
}


def _char_refused(text, line):
    with pytest.raises(lang.Refusal) as info:
        compile_(text, "<t>")
    r = info.value
    assert (r.name, r.line) == ("character", line), str(r)
    return r.sentence


@pytest.mark.parametrize("c", list(_ANYWHERE),
                         ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize("where", ["comment", "tokens"])
def test_a_line_break_nul_or_ctrl_z_is_refused_anywhere(c, where):
    """In a comment too - VL1's case is the comment one - and from a str
    or a file's bytes alike, at its line, named as asm.py names it."""
    if where == "comment":
        src = _RULE_HEAD + f"; rounding: the default{c}round rdn\n" + \
            _RULE_TAIL
    else:
        src = _RULE_HEAD + f"next x = x{c}* 3\nstep map\n"
    for text in (src, src.encode()):
        sentence = _char_refused(text, 4)
        assert sentence.startswith(f"{_ANYWHERE[c]}: "), sentence


def test_a_crlf_file_compiles_as_its_lf_twin():
    """A CR immediately before an LF is part of that line end: a CRLF
    file, a mixed one and one without a final line end each give the LF
    file's graph, from bytes and from a str."""
    lf = (SYSTEMS / "henonheiles-lf-fp64.cftl").read_bytes()
    want = ref("henonheiles-lf-fp64").to_bytes()
    crlf = lf.replace(b"\n", b"\r\n")
    for data in (crlf, lf.replace(b"\n", b"\r\n", 2), crlf[:-2]):
        assert compile_(data).to_bytes() == want
        assert compile_(data.decode("utf-8")).to_bytes() == want


@pytest.mark.parametrize("tail", ["step map\r\r\n", "step map\r"],
                         ids=["CR CR LF", "a final CR"])
def test_a_carriage_return_not_before_a_line_feed_is_refused(tail):
    assert _ANYWHERE["\r"] in _char_refused(
        _RULE_HEAD + "next x = x * 3\n" + tail, 5)


@pytest.mark.parametrize("c, name", [
    (" ", "the character U+00A0"), (" ", "the character U+2003"),
    ("　", "the character U+3000"), ("﻿", "the character U+FEFF"),
    ("\x01", "the control character 0x01"),
    ("\x1b", "the control character 0x1b"),
    ("\x7f", "the control character 0x7f"),
    ("é", "the character U+00E9")],
    ids=lambda v: f"U+{ord(v):04X}" if len(v) == 1 else None)
def test_only_printable_ascii_space_and_tab_stand_outside_a_comment(c, name):
    """Between tokens refused, by name; in a comment only text."""
    sentence = _char_refused(_RULE_HEAD + f"next x = x{c}* 3\nstep map\n", 4)
    assert sentence == (f"{name} outside a comment, where a line holds only "
                        f"printable ASCII, spaces and tabs")
    compile_(_RULE_HEAD + f"; x{c}y\n" + _RULE_TAIL)
    compile_(_RULE_HEAD + "next x = x\t* 3\nstep map\n")


@pytest.mark.parametrize("bad, lead", [
    (b"\xff", 0xFF), (b"\x80", 0x80), (b"\xc0\x80", 0xC0),
    (b"\xe2\x28\xa1", 0xE2), (b"\xed\xa0\x80", 0xED),
    (b"\xf4\x90\x80\x80", 0xF4), (b"\xf0\x9f\x98\n", 0xF0)],
    ids=lambda v: v.hex() if isinstance(v, bytes) else None)
def test_a_source_that_is_not_utf8_is_refused_at_its_line(bad, lead):
    """The byte named is the lead byte of the first ill-formed sequence,
    as asm.py and cft-asm name it."""
    data = _RULE_HEAD.encode() + b"; " + bad + b"note\n" + _RULE_TAIL.encode()
    assert _char_refused(data, 4) == \
        f"the source is not UTF-8 (byte 0x{lead:02x})"
    data = (_RULE_HEAD + _RULE_TAIL).encode() + b"; \xe2\x82"
    assert _char_refused(data, 6).endswith("(byte 0xe2)")
    assert "lone surrogate, U+D800" in _char_refused(
        _RULE_HEAD + "; \ud800\n" + _RULE_TAIL, 4)


def test_the_source_is_held_whole_before_a_line_is_read():
    """Of two faults the first is named: UTF-8 over the whole source,
    then the characters, then the statements."""
    data = _RULE_HEAD.encode() + b"; \x0c\n; \xff\n" + _RULE_TAIL.encode()
    assert _char_refused(data, 5).endswith("(byte 0xff)")
    assert _ANYWHERE["\x0c"] in _char_refused(
        _RULE_HEAD + "nosuch x\n; \x0c\n" + _RULE_TAIL, 5)


def test_a_byte_order_mark_is_refused_not_dropped(tmp_path):
    """lang.load once dropped a leading byte-order mark; it is a
    character outside a comment like any other now, as in .cfta."""
    p = tmp_path / "bom.cftl"
    p.write_bytes(b"\xef\xbb\xbf" + (SYSTEMS / "lorenz63-rk4-fp64.cftl")
                  .read_bytes())
    with pytest.raises(lang.Refusal) as info:
        lang.load(p)
    assert (info.value.name, info.value.line) == ("character", 1)
    assert info.value.sentence.startswith("the character U+FEFF outside a "
                                          "comment")
    assert str(info.value).startswith(str(p))


def test_every_committed_source_holds_the_character_rule():
    """Every .cftl in programs/ - the references, and whatever is
    committed beside them - is held to the rule, whole, as bytes."""
    paths = sorted(PROGRAMS.glob("**/*.cftl"))
    assert len(paths) >= 6
    for p in paths:
        data = p.read_bytes()
        assert lang_syntax.source_text(data) == data.decode("utf-8"), p


# h's sign. A constant is c x h^d with c fixed by h's sign alone, so a run
# at an h of the graph's sign is the graph compiled at that h; across the
# sign it was not: `const s = copysign(1, h)` compiled at 1/8 and run at
# -1/8 stepped x = 1 to 0.875, where compiling at -1/8 gives 1.125
# (verifier-VL1). Such a run is refused by name.

def _sign_system(kind, h):
    if kind == "map":
        return (f"system s\nformat fp64\nround rdn\nstate x\n"
                f"next x = x + abs(h)\nstep map, h = {h}\n")
    return (f"system s\nformat fp64\nround rup\nstate x\nconst s = {kind}\n"
            f"d/dt x = s * x\nstep euler, h = {h}\n")


def _sign_carried(g):
    """What h's sign fixed: the constants that do not scale with h, and
    the factors of those that do."""
    return ([v for v, fa, _b, _f in g.const if fa is None],
            [fa for _v, fa, _b, _f in g.const if fa is not None])


@pytest.mark.parametrize("kind", ["copysign(1, h)", "abs(h)/h",
                                  "abs(1/(3*h))*h", "map"])
def test_a_run_h_keeps_the_graphs_sign(kind):
    g = compile_(_sign_system(kind, "1/8"))
    one = sf.one_bits(g.fmt)
    for h0, h in ((g, F(-1, 8)), (compile_(_sign_system(kind, "-1/8")),
                                  F(1, 8))):
        with pytest.raises(lang.Refusal) as info:
            lang.run(h0, [[one]], 1, h=h)
        assert info.value.name == "step-size-sign"
    # why: compiled at -1/8 the sign-carrying constants are others, so no
    # recomputing of the h-scaled ones could give that graph
    assert _sign_carried(compile_(_sign_system(kind, "-1/8"))) != \
        _sign_carried(g)
    for h in ("1/16", "3/7", "0x1p-10", "1e-300"):
        again = compile_(_sign_system(kind, h))
        assert _sign_carried(again) == _sign_carried(g)
        assert lang.run(g, [[one]], 3, h=h).states == \
            lang.run(again, [[one]], 3).states


def test_a_run_h_is_the_reference_compiled_at_that_h():
    """At h/2 and at 3h/7: each reference run with its h replaced equals
    the reference compiled at that h, bit for bit, FLAGS included."""
    rng = random.Random("run h")
    for name in REFS:
        g = ref(name)
        text = (SYSTEMS / f"{name}.cftl").read_text()
        assert g.integrator[1] == F(1, 100) and "h = 1/100" in text
        top = 3 << (g.fmt.width - 2)          # positive, below 2
        lanes = [[rng.getrandbits(g.fmt.width) & ~top
                  for _ in range(g.n_state)] for _ in range(2)]
        for new in (F(1, 200), F(3, 700)):
            again = compile_(text.replace("h = 1/100", f"h = {new}"))
            a = lang.run(g, lanes, 2, h=new)
            b = lang.run(again, lanes, 2)
            assert (a.states, a.flags) == (b.states, b.flags), name


# The nits: a long constant named rightly in a sentence, written out in
# time linear in its size, and read back by the test's own reader at any
# length.

_BRIEF = [
    (-10 ** 5000, "-1e5000"), (10 ** 300, "1e300"),
    (F(1, 10 ** 5000), "1e-5000"), (F(1, 3), "1/3"),
    (F(1, 2 ** 1074), "0x1p-1074"),
    (F(10 ** 5000, 3), "3.3333e+4999 (to five digits)"),
    (F(-2 * 10 ** 5000, 3), "-6.6667e+4999 (to five digits)"),
    (F(1, 3 * 10 ** 5000), "3.3333e-5001 (to five digits)"),
    (F(10 ** 300000, 7), "1.4286e+299999 (to five digits)"),
]


@pytest.mark.parametrize("value, text", _BRIEF,
                         ids=[text for _v, text in _BRIEF])
def test_a_constant_is_named_briefly_and_rightly(value, text):
    """-1e5000 was 'a value near 2^16609 (about 10^4999)'."""
    assert C.brief(value) == text


def test_five_digits_round_half_to_even():
    assert C.five_digits(F(999995 * 10 ** 4994)) == "1.0000e+5000"
    assert C.five_digits(F(999985 * 10 ** 4994)) == "9.9998e+4999"
    assert C.five_digits(F(999985 * 10 ** 4994 + 1)) == "9.9999e+4999"
    assert C.five_digits(F(-1, 7)) == "-1.4286e-1"
    assert C.five_digits(F(10 ** 5)) == "1.0000e+5"


def test_the_overflow_sentence_names_the_constant():
    with pytest.raises(lang.Refusal) as info:
        compile_(_src("state x", "next x = x * -1e5000"))
    assert info.value.sentence == "-1e5000 overflows binary64 under rne"


@pytest.mark.parametrize("lit", ["1e-78900", "1e78000", "3e-5000"])
def test_a_constant_is_written_out_in_linear_time(lit):
    """Rendering was quadratic in a constant's decimal exponent: 1e-20000
    took 3.2 s and 1e-78900 about a minute, a call (verifier-VL1). The
    bound here is far above the time measured, and far below that."""
    g = compile_(f"system s\nformat fp256\nstate x\nnext x = x * {lit}\n"
                 f"step map\n")
    import time
    t0 = time.perf_counter()
    canon = lang.render_canonical(g)
    lang.render_math(g)
    assert lang.StepGraph.from_bytes(g.to_bytes()).to_bytes() == g.to_bytes()
    assert time.perf_counter() - t0 < 5
    assert f"x * {lit}" in canon


@pytest.mark.parametrize("body", [
    "next x = x * 3" + "7" * 4999,
    "param p = 3" + "7" * 4999 + "\nnext x = x * p",
    "next x = x * (" + "1" * 4400 + "/" + "3" * 4401 + ")",
    "lane param p = " + "1" * 4400 + "/" + "3" * 4401 + "\nnext x = x * p",
])
def test_the_math_reader_reads_past_4300_digits(body):
    """The test's own reader of the mathematical form called Fraction() on
    a printed number, which stops at 4,300 digits (verifier-VL1)."""
    g = compile_(f"system s\nformat fp256\nstate x\n{body}\nstep map\n")
    check_intention_out(g, random.Random("long"), points=1)


def _last_hex_digit_bumped(match):
    text = match.group(0)
    return text[:-1] + ("0" if text[-1] != "0" else "1")


_SAID_PLANTS = [   # (which form, the change), each a wrong statement
    ("canonical", lambda t: re.sub(r"(?m)^; sha256 \w+$",
                                   _last_hex_digit_bumped, t)),
    ("canonical", lambda t: re.sub(r"under (\w+) \(", lambda m: "under " + {
        "rne": "rtz"}.get(m.group(1), "rne") + " (", t, count=1)),
    ("canonical", lambda t: t.replace("in binary", "in binary2", 1)),
    ("canonical", lambda t: t.replace(" - the canonical form",
                                      "x - the canonical form", 1)),
    ("canonical", lambda t: t.replace(", h/2", "", 1)),
    ("canonical", lambda t: re.sub(r"(?m)^lane param \w+ = [^;]*; 0x\w+",
                                   _last_hex_digit_bumped, t)),
    ("canonical", lambda t: re.sub(r"(?m)^((?:d/dt|next) [^;]*)$",
                                   r"\1  ; as written", t, count=1)),
    ("math", lambda t: t.replace("  ρ = 1/3", "  ρ = 2/3")
     .replace("  μ = 2/3", "  μ = 1/3")),
    ("math", lambda t: t.replace("ρ", "ϱ").replace("θ", "ϑ")
     .replace("φ", "ϕ").replace("σ", "ς")),
    ("math", lambda t: re.sub(r" \((fp\d+)\), ", lambda m: " (" + {
        "fp64": "fp32"}.get(m.group(1), "fp64") + "), ", t, count=1)),
    ("math", lambda t: t.replace("Runge-Kutta", "Runge-Kutta-Fehlberg", 1)
     .replace("one step: the map", "one step: a map", 1)),
]


def test_the_check_of_what_is_said_has_teeth():
    """VL1's map, its lane default printed as 2/3 for 1/3, passed the
    check before 2026-10-01's second send-back, and so did each change
    here that its forms carry: a sha256 digit, the attribute or the
    format restated, the title, the h-scaled list, a lane default's
    encoding, a comment on an equation, a lane param's or a let's glyph,
    the integrator's name. Each is caught now; the forms unchanged pass."""
    for g in (compile_(NAMED_SYSTEMS["vl1-map"]),
              compile_(NAMED_SYSTEMS["pendulum-rk4"]),
              ref("lorenz63-rk4-fp64")):
        canon, math = lang.render_canonical(g), lang.render_math(g)
        check_comments(g, canon, math)
        caught = 0
        for which, plant in _SAID_PLANTS:
            c2 = plant(canon) if which == "canonical" else canon
            m2 = plant(math) if which == "math" else math
            if (c2, m2) == (canon, math):
                continue
            with pytest.raises(AssertionError):
                check_comments(g, c2, m2)
            caught += 1
        assert caught >= 7, g.system


# ---- the documents -------------------------------------------------------------

def test_the_document_quotes_the_integrators():
    assert lang.TEMPLATE_TEXT in DOC.read_text(encoding="utf-8")


def test_the_document_shows_lorenz63_as_rendered():
    """docs/LANGUAGE.md shows Lorenz-63's intention-out as the renderers
    write it today."""
    text = DOC.read_text(encoding="utf-8")
    g = ref("lorenz63-rk4-fp64")
    for body in (lang.render_canonical(g), lang.render_math(g)):
        assert body in text


def test_one_character_rule_for_both_text_forms():
    """The language's character rule is the text form's, in the same words
    (docs/PROGRAMS.md and docs/LANGUAGE.md): the same characters ending no
    line, the same never-allowed ones, and every character named alike -
    held here, where both live in one tree (added at the language round's
    merge of L1, 2026-10-01; verifier-VL1 measured it across the two
    branches before)."""
    assert lang_syntax.LINE_BREAKS == asm._LINE_BREAKS
    assert lang_syntax.NEVER == asm._NEVER
    for cp in range(0x3100):
        assert lang_syntax.char_name(cp) == asm._char_name(cp), hex(cp)


@pytest.mark.parametrize("body", [
    "next x = x + (1e-5000 * h)",
    "next x = x + (3e5000 * h)",
    "next x = x + (1e-5000 * h / 7)",
])
def test_an_h_scaled_constant_past_4300_digits_renders(body):
    """render_math wrote an h-scaled constant's numerator and denominator
    with str(), so `1e-5000 * h` at fp256 passed the checker, to_bytes,
    from_bytes and render_canonical and then raised ValueError (Python's
    4,300-digit limit) - found by L2 at d50ccb0, fixed at the language
    round's integration. Its intention-out must hold whole."""
    lines = ("system s", "format fp256", "state x", body,
             "step map, h = 1/100")
    g = compile_("".join(line + chr(10) for line in lines))
    check_intention_out(g, random.Random(body), points=2)


# ---- verifier-VI: every refusal sentence names a value at any size ------------
# check.py's index-range sentences, lang.run's input refusals and cftc's
# segment-steps sentence formatted their integers with str() or repr(), so
# a value past Python's 4,300-digit limit raised a bare ValueError where a
# named refusal was due (the class of VL1's F2; found by verifier-VI at
# 30ee0fd, fixed at the language round's close).

_HUGE = 10 ** 5000


@pytest.mark.parametrize("body", [
    "next x[i] = x[i + 1" + "0" * 5000 + "] for i in 0..3",
    "next x[i] = x[i] for i in 0..1" + "0" * 5000,
    "next x[i] = x[i] for i in -1" + "0" * 5000 + "..3",
    "next x[i] = x[i] for i in 1" + "0" * 5000 + "..0",
])
def test_an_index_past_4300_digits_is_refused_by_name(body):
    lines = ("system s", "format fp64", "state x[4]", body, "step map")
    with pytest.raises(lang.Refusal) as e:
        compile_("".join(line + chr(10) for line in lines))
    assert e.value.name == "index-range"
    assert len(str(e.value)) < 400


def test_run_inputs_past_4300_digits_are_refused_by_name():
    g = compile_("".join(line + chr(10) for line in (
        "system s", "format fp64", "state x", "lane param a = 1",
        "param p = 1", "d/dt x = a * p * x", "step euler, h = 1/8")))
    one = C.round_once(FORMATS["fp64"], 0, Fraction(1))[0]
    cases = [
        ("lane-value", dict(states=[[_HUGE]], steps=1)),
        ("lane-value", dict(states=[[one]], steps=1, lane_params=[[_HUGE]])),
        ("param-value", dict(states=[[one]], steps=1,
                             param_bits={"p": _HUGE})),
        ("step-count", dict(states=[[one]], steps=1, at=(_HUGE,))),
        ("step-count", dict(states=[[one]], steps=-_HUGE)),
    ]
    for name, kw in cases:
        with pytest.raises(lang.Refusal) as e:
            lang.run(g, **kw)
        assert e.value.name == name, (name, kw.keys(), e.value.name)
        assert len(str(e.value)) < 400
