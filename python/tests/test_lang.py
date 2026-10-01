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
                       graph evaluated exactly - on the references and on
                       random systems
  the documents        docs/LANGUAGE.md's refusal table and its copy of
                       the integrators are the code's
"""

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
from cft_golden.lang.graph import Section  # noqa: E402
from lang_mathform import MathForm  # noqa: E402

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
         "nan", "d/dt", "next", "let r = ", "2/0"]


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


def _sig_value(text):
    """`+2.0817e-17` as an exact rational."""
    return Fraction(text)


def check_comments(g, canon, math):
    """What the intention-out says besides its code, read back and held
    to the graph and to the test's own arithmetic: each constant's exact
    value, encoding and relative error, each default's, the operation
    counts, and the mathematical form's printed defaults and names."""
    fmt = g.fmt
    lines = canon.splitlines()
    rows = []
    k = next(i for i, ln in enumerate(lines)
             if ln.startswith("; constants")) + 1
    while lines[k].startswith(";   "):
        rows.append(lines[k][4:].split())
        k += 1
    assert len(rows) == len(g.const)
    for row, (value, factor, bits, flags) in zip(rows, g.const):
        name, exact_text, bits_text, hex_text = row[:4]
        assert lang_check.constant_of(exact_text) == value
        if factor is not None:
            assert lang_check.constant_of(name.replace("h", f"({value / factor})")) \
                == value
        else:
            assert lang_check.constant_of(name) == value
        assert int(bits_text, 16) == bits
        assert chars.from_hex(fmt, hex_text, sf.RND_RNE)[0] == bits
        _check_described(fmt, value, bits, flags, " ".join(row[4:]))
    for name, value, bits, flags in g.param:
        line = next(ln for ln in lines if ln.startswith(f"param  {name} = "))
        code, comment = line.split(";", 1)
        assert lang_check.constant_of(code.split("=", 1)[1]) == value
        bits_text, hex_text, *desc = comment.split()
        assert int(bits_text, 16) == bits
        assert chars.from_hex(fmt, hex_text, sf.RND_RNE)[0] == bits
        _check_described(fmt, value, bits, flags, " ".join(desc))
    counts = {"field": g.field, "step": g.step}
    for line in lines:
        m = re.search(r"(the equations|a step) (\d+) \(([^)]*)\)", line)
        if not m:
            continue
        sec = counts["field" if m.group(1) == "the equations" else "step"]
        mine = {}
        for op, _a, _l in sec.nodes:
            mine[op] = mine.get(op, 0) + 1
        said = {op: int(n) for n, op in
                (part.split() for part in m.group(3).split(", "))}
        assert int(m.group(2)) == len(sec.nodes) and said == mine
    mlines = math.splitlines()
    if g.param:
        k = mlines.index("parameters, the run's (defaults)") + 1
        for name, value, _b, _f in g.param:
            printed, default = mlines[k].strip().split(" = ")
            assert printed == _glyph(name)
            assert Fraction(default.replace("−", "-")) == value
            k += 1
    y = next(ln for ln in mlines if ln.startswith("  Y = ("))
    assert y[7:-1].split(", ") == [_glyph(c) for c in g.components()]


def _check_described(fmt, value, bits, flags, desc):
    """`exact`, or `inexact[, underflow], relative error +x.xxxxe-yy`,
    against the test's own relative error, to the five digits shown."""
    if desc == "exact":
        assert flags == 0 and C.value_of(fmt, bits) == value
        return
    words, _sep, rel_text = desc.partition("relative error ")
    assert ("inexact" in words) == bool(flags & sf.FLAG_INEXACT)
    assert ("underflow" in words) == bool(flags & sf.FLAG_UNDERFLOW)
    true = (C.value_of(fmt, bits) - value) / value
    printed = _sig_value(rel_text)
    assert (printed > 0) == (true > 0)
    assert abs(printed - true) <= abs(true) * Fraction(1, 10 ** 4)


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


def test_line_ends_and_a_byte_order_mark(tmp_path):
    text = (SYSTEMS / "henonheiles-lf-fp64.cftl").read_text()
    want = ref("henonheiles-lf-fp64").to_bytes()
    assert compile_(text.replace("\n", "\r")).to_bytes() == want
    assert compile_(text.replace("\n", "\r\n")).to_bytes() == want
    p = tmp_path / "bom.cftl"
    p.write_bytes(b"\xef\xbb\xbf" + text.encode("ascii"))
    assert lang.load(p).graph.to_bytes() == want


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
