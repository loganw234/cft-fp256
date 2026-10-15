# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The variational equations (docs/LANGUAGE.md, "The variational
equations"; python/cft_golden/lang/tangent.py): the language's L3.

  the rules            each rule of the document's table, rendered on a
                       one-operation system for every pattern of zero
                       tangents, against the test's own copy of the table
                       - and the document's table against that copy; the
                       measure-zero values and the specials, bit for bit
  the derivative       the fourth check: the tangent sections evaluated
                       exactly against the test's own dual numbers, on
                       the references and generated systems at random
                       points, about half of them placed (a component
                       equal to another or zero), and at ties and zeros
                       placed where the conventions decide - operands
                       equal in value and different in tangent, where
                       the other conventions are asserted to give
                       another answer; three plants red on it, and the
                       rounding-order plant green on it and red on the
                       bytes
  A and B              the template on the extended system against the
                       step's own tangent: exactly equal everywhere, node
                       for node where no tangent is identically zero,
                       and parting in bits where one is
  the primal           unchanged by tangents: its sections, its run, its
                       flags; and every version-1 graph unchanged
  the interpreter      its tangents and their refusals, every shape
  writing them out     accepted where the derivation's, refused by name
                       where not; the intention-out's four checks, and
                       plants of the tangent's printed lines
  determinism, the document
"""

import functools
import os
import random
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from cft_golden import FORMATS, lang  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.lang import check as lang_check  # noqa: E402
from cft_golden.lang import constants as C  # noqa: E402
from cft_golden.lang import tangent as lang_tangent  # noqa: E402
from cft_golden.lang.graph import Node  # noqa: E402
from lang_mathform import MathForm  # noqa: E402
from lang_mathform import root as exact_root  # noqa: E402
from lang_mathform import transcendental as T6  # noqa: E402
import test_lang as TL  # noqa: E402

F = Fraction
SYSTEMS = REPO / "programs" / "systems"
COMPILED = SYSTEMS / "compiled"
DOC = REPO / "docs" / "LANGUAGE.md"
TREFS = [f"{n}-tangent-{f}" for n in ("lorenz63-rk4", "lorenz96-rk4")
         for f in ("fp64", "fp256")]


def compile_(text, source="<test>"):
    return lang.compile_text(text, source).graph


def with_tangent(text, names="v"):
    """A system's text with `tangent <names>` after its first state line."""
    lines = text.split("\n")
    k = next(i for i, ln in enumerate(lines) if ln.startswith("state"))
    lines.insert(k + 1, f"tangent {names}")
    return "\n".join(lines)


def tref(name):
    return lang.load(SYSTEMS / f"{name}.cftl").graph


# ---- the rules ---------------------------------------------------------------

# The test's own copy of docs/LANGUAGE.md's rule table: for each written
# operation, its tangent as the canonical form writes it, for each set of
# operands whose tangents are nonzero (the others are params). The target
# is y; a, b, c are state components when active and params when not.
RULES = [
    ("a + b", {"ab": "v.a + v.b", "a": "v.a", "b": "v.b"}),
    ("a - b", {"ab": "v.a - v.b", "a": "v.a", "b": "-v.b"}),
    ("-a", {"a": "-v.a"}),
    ("a * b", {"ab": "fma(v.a, b, a * v.b)", "a": "v.a * b",
               "b": "a * v.b"}),
    ("fma(a, b, c)", {"abc": "fma(v.a, b, fma(a, v.b, v.c))",
                      "ab": "fma(v.a, b, a * v.b)",
                      "ac": "fma(v.a, b, v.c)", "bc": "fma(a, v.b, v.c)",
                      "a": "v.a * b", "b": "a * v.b", "c": "v.c"}),
    # L4: the quotient and the root read r, their own result, written
    # again here since y's has no name
    ("a / b", {"ab": "fma(-(a / b), v.b, v.a) / b", "a": "v.a / b",
               "b": "(-(a / b)) * v.b / b"}),
    ("sqrt(a)", {"a": "v.a / (2 * sqrt(a))"}),
    ("abs(a)", {"a": "copysign(1, a) * v.a"}),
    ("copysign(a, b)", {"ab": "copysign(1, b) * (copysign(1, a) * v.a)",
                        "a": "copysign(1, b) * (copysign(1, a) * v.a)",
                        "b": "0"}),
    ("a < b", {"ab": "0", "a": "0"}),
    ("a <= b", {"ab": "0"}),
    ("a == b", {"ab": "0"}),
    ("select(c, a, b)", {"abc": "select(c, v.a, v.b)",
                         "ab": "select(c, v.a, v.b)",
                         "ac": "select(c, v.a, 0)", "bc": "select(c, 0, v.b)",
                         "c": "0"}),
] + [(f"{op}(a, b)", {"ab": f"select({op}(a, b) == a, v.a, v.b)",
                      "a": f"select({op}(a, b) == a, v.a, 0)",
                      "b": f"select({op}(a, b) == a, 0, v.b)"})
     for op in ("min", "max", "minnum", "maxnum")] + [
    # M1's build, item 3: r the function's own result, written again since
    # y's has no name; L ln 2 rounded once - at fp64 under rne, RN(ln 2) =
    # 0x3fe62e42fefa39ef, the hexadecimal significand below
    ("exp(a)", {"a": "exp(a) * v.a"}),
    ("expm1(a)", {"a": "(1 + expm1(a)) * v.a"}),
    ("exp2(a)", {"a": "0x1.62e42fefa39efp-1 * exp2(a) * v.a"}),
    ("log(a)", {"a": "select(log(a) == log(a), v.a / a, log(a))"}),
    ("log2(a)", {"a": "select(log2(a) == log2(a), "
                      "v.a / (0x1.62e42fefa39efp-1 * a), log2(a))"}),
    ("log1p(a)", {"a": "select(log1p(a) == log1p(a), v.a / (1 + a), "
                       "log1p(a))"})]

# the table's "its tangent" column, as the document writes it
DOC_RULES = {
    "`a + b`": "`da + db`", "`a - b`": "`da - db`", "`-a`": "`-da`",
    "`a * b`": "`fma(da, b, a * db)`",
    "`fma(a, b, c)`": "`fma(da, b, fma(a, db, dc))`",
    "`a / b`": "`fma(-r, db, da) / b`",
    "`sqrt(a)`": "`da / (2 * r)`",
    "`abs(a)`": "`copysign(1, a) * da`",
    "`copysign(a, b)`": "`copysign(1, b) * (copysign(1, a) * da)`",
    "`min(a, b)`, `max`, `minnum`, `maxnum`": "`select(r == a, da, db)`",
    "`a < b`, `<=`, `>`, `>=`, `==`": "zero",
    "`select(c, a, b)`": "`select(c, da, db)`",
    "`exp(a)`": "`r * da`",
    "`expm1(a)`": "`(1 + r) * da`",
    "`exp2(a)`": "`(L * r) * da`",
    "`log(a)`": "`select(r == r, da / a, r)`",
    "`log2(a)`": "`select(r == r, da / (L * a), r)`",
    "`log1p(a)`": "`select(r == r, da / (1 + a), r)`",
}


def _rule_system(expr, active):
    state = [x for x in "abc" if x in active] + ["y"]
    params = [x for x in "abc" if x not in active
              and re.search(rf"\b{x}\b", expr)]
    lines = ["system r", "format fp64", "state " + ", ".join(state),
             "tangent v"]
    if params:
        lines.append("param " + ", ".join(f"{p} = {k + 2}/7"
                                          for k, p in enumerate(params)))
    lines += [f"next {x} = {x}" for x in state if x != "y"]
    lines += [f"next y = {expr}", "step map"]
    return "\n".join(lines) + "\n"


def _tangent_line(g, comp="y", vec="v"):
    canon = lang.render_canonical(g)
    head = f"next {vec}.{comp} = "
    return next(ln[len(head):] for ln in canon.splitlines()
                if ln.startswith(head))


@pytest.mark.parametrize("expr,cases", RULES, ids=[r[0] for r in RULES])
def test_each_rule_as_the_table_writes_it(expr, cases):
    for active, want in cases.items():
        g = compile_(_rule_system(expr, active))
        assert _tangent_line(g) == want, (expr, active)


def test_the_documents_rule_table_is_the_tests():
    text = DOC.read_text(encoding="utf-8")
    rules = text.split("### The rules", 1)[1].split("\n### ", 1)[0]
    rows = {}
    for line in rules.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`"):
            rows[cells[0]] = cells[1]
    for op, tangent in DOC_RULES.items():
        assert rows.get(op) == tangent, op


def _bits(fmt, v):
    return C.round_once(fmt, sf.RND_RNE, F(v))[0]


def _one_step(text, state, tangent):
    g = compile_(text)
    r = lang.run(g, [state], 1, tangents=[[tangent]])
    return r.states[0], r.tangents[0][0], r.flags


def test_the_measure_zero_values_bit_for_bit():
    """abs and copysign by the sign bit at ±0 and a NaN; the min family
    at a tie, ±0 included, and where the result is a NaN."""
    fmt = FORMATS["fp64"]
    one, two, three = (_bits(fmt, v) for v in (1, 2, 3))
    neg0, sign = fmt.sign_mask, fmt.sign_mask
    qnan = sf.qnan_bits(fmt)
    absy = ("system s\nformat fp64\nstate x, y\ntangent v\nnext x = x\n"
            "next y = abs(x)\nstep map\n")
    # at +0 the + side, at -0 the - side, at a NaN its sign bit
    assert _one_step(absy, [0, 0], [three, 0])[1][1] == three
    assert _one_step(absy, [neg0, 0], [three, 0])[1][1] == three ^ sign
    assert _one_step(absy, [qnan ^ sign, 0], [three, 0])[1][1] == \
        three ^ sign
    cs = ("system s\nformat fp64\nstate x, y\ntangent v\nnext x = x\n"
          "next y = copysign(x, y)\nstep map\n")
    # sgn(a) sgn(b) da: a = -0, b = -2: + ; a = +0, b = -2: -
    assert _one_step(cs, [neg0, two ^ sign], [three, one])[1][1] == three
    assert _one_step(cs, [0, two ^ sign], [three, one])[1][1] == \
        three ^ sign
    for op in ("min", "max", "minnum", "maxnum"):
        t = (f"system s\nformat fp64\nstate x, y\ntangent v\nnext x = x\n"
             f"next y = {op}(x, y)\nstep map\n")
        # a tie, and ±0 either way round: the first operand's tangent
        assert _one_step(t, [two, two], [three, one])[1][1] == three, op
        assert _one_step(t, [neg0, 0], [three, one])[1][1] == three, op
        assert _one_step(t, [0, neg0], [three, one])[1][1] == three, op
        # a NaN result: r == a is false, the second operand's
        if op in ("min", "max"):
            assert _one_step(t, [qnan, two], [three, one])[1][1] == one
        else:                           # the number is returned, and its
            assert _one_step(t, [qnan, two], [three, one])[1][1] == one
            assert _one_step(t, [two, qnan], [three, one])[1][1] == three


@pytest.mark.parametrize("fmtname", ["fp32", "fp64", "fp256"])
def test_a_product_by_plus_or_minus_one_is_exact(fmtname):
    """abs's rule multiplies the tangent by ±1: exact, no flag, at every
    special but a signalling NaN - RISC-V's FSGNJX for every tangent that
    is not a NaN (docs/LANGUAGE.md)."""
    fmt = FORMATS[fmtname]
    text = (f"system s\nformat {fmtname}\nstate x, y\ntangent v\n"
            f"next x = x\nnext y = abs(x)\nstep map\n")
    neg = _bits(fmt, -2)
    for t in (sf.min_subnormal_bits(fmt), (1 << fmt.man_w) - 1, 0,
              fmt.sign_mask, sf.round_pack(fmt, 0, 1, fmt.emax + 5)[0],
              _bits(fmt, F(1, 3))):
        _s, tan, flags = _one_step(text, [neg, 0], [t, 0])
        assert tan[1] == t ^ fmt.sign_mask and flags == 0, hex(t)
    _s, tan, flags = _one_step(text, [neg, 0], [sf.snan_bits(fmt, 1), 0])
    assert flags == sf.FLAG_INVALID and tan[1] == sf.qnan_bits(fmt)


# ---- the derivative: the fourth check ---------------------------------------

def _sgn(x, zero=1):
    return -1 if x < 0 else (zero if x == 0 else 1)


def _dual(op, a, tie=0, zero=1, L=None):
    """The test's own derivative: (value, derivative) pairs, the
    conventions at measure-zero points written again from the document's
    rule table - the + side of an exact zero (exact arithmetic has no
    -0), ties to the first operand. tie=1 (a tie takes the second
    operand's tangent) and zero=-1 (a zero's sign is -) are the other
    conventions, which a placed point must tell apart from the table's;
    values are the same under any of them. The math library's six (M1)
    take each value as the exact evaluation takes it, the reader's fixed
    function (lang_mathform.transcendental), and the derivative the
    textbook's with ln 2 as L, the test's own: transcend.log of 2 at the
    program's format under its attribute (`L`)."""
    v = [p[0] for p in a]
    d = [p[1] for p in a]
    if op in TL.SIX:
        x, dx = v[0], d[0]
        if op in ("exp", "expm1"):
            e = T6("exp", x)
            return (e if op == "exp" else e - 1), e * dx
        if op == "exp2":
            r = T6("2^", x)
            return r, L * r * dx
        if op == "log":
            return T6("ln", x), dx / x
        if op == "log2":
            return T6("log₂", x), dx / (L * x)
        return T6("log1p", x), dx / (1 + x)
    if op == "add":
        return v[0] + v[1], d[0] + d[1]
    if op == "sub":
        return v[0] - v[1], d[0] - d[1]
    if op == "mul":
        return v[0] * v[1], d[0] * v[1] + v[0] * d[1]
    if op == "fma":
        return v[0] * v[1] + v[2], d[0] * v[1] + v[0] * d[1] + d[2]
    if op == "div":                     # the textbook's rule, not the form
        return v[0] / v[1], (d[0] * v[1] - v[0] * d[1]) / (v[1] * v[1])
    if op == "sqrt":                    # the root as both evaluations take it
        r = exact_root(v[0])
        return r, d[0] / (2 * r)
    if op == "neg":
        return -v[0], -d[0]
    if op == "abs":
        return abs(v[0]), _sgn(v[0], zero) * d[0]
    if op == "copysign":
        return (_sgn(v[1]) * abs(v[0]),
                _sgn(v[0], zero) * _sgn(v[1], zero) * d[0])
    if op in ("min", "minnum", "max", "maxnum"):
        if v[0] == v[1]:
            return v[tie], d[tie]
        first = (v[0] < v[1]) == (op in ("min", "minnum"))
        return (v[0], d[0]) if first else (v[1], d[1])
    if op == "cmplt":
        return F(1 if v[0] < v[1] else 0), F(0)
    if op == "cmple":
        return F(1 if v[0] <= v[1] else 0), F(0)
    if op == "cmpeq":
        return F(1 if v[0] == v[1] else 0), F(0)
    if op == "select":                  # golden order: a if c else b
        return (v[0], d[0]) if v[2] != 0 else (v[1], d[1])
    raise AssertionError(op)


def dual_eval(g, section, state, tangent, params, lanes, tie=0, zero=1):
    """The exact directional derivative of a primal section's outputs."""
    sec = g.section(section)
    vals = {"s": list(zip(state, tangent)),
            "l": [(F(x), F(0)) for x in lanes],
            "p": [(F(x), F(0)) for x in params],
            "c": [(v, F(0)) for v, _fa, _b, _f in g.const]}
    nodes = []
    L = _ln2(g.fmt, g.rnd) if {"exp2", "log2"} & {op for op, _a, _l in
                                                   sec.nodes} else None

    def get(r):
        k, i = r[0], int(r[1:])
        return nodes[i] if k == "n" else vals[k][i]
    for op, args, _l in sec.nodes:
        nodes.append(_dual(op, [get(a) for a in args], tie, zero, L))
    return [get(o)[1] for o in sec.out]


_LN2 = {}


def _ln2(fmt, rnd):
    """The test's own L, as an exact rational: transcend.log of 2 at the
    format under the attribute - the decided definition (M1's question 6),
    which the language computes otherwise (constants.ln2_bits)."""
    from cft_golden import transcend
    key = (fmt.name, rnd)
    if key not in _LN2:
        two = C.round_once(fmt, sf.RND_RNE, F(2))[0]
        _LN2[key] = C.value_of(fmt, transcend.compute(fmt, "log", two, 0,
                                                       rnd)[0])
    return _LN2[key]


def _q(rng):
    return F(rng.randint(-5000, 5000), rng.randint(1, 4000))


def _point(rng, n):
    """A state: random rationals, and half the time PLACED - one component
    set equal to another (a tie wherever the step compares the two or
    takes their min or max) or to zero (a zero of whatever reads it
    alone). The tangent stays random, so at a placed tie the operands'
    tangents differ, and a convention there changes the derivative."""
    state = [_q(rng) for _ in range(n)]
    r = rng.random()
    i = rng.randrange(n)
    if r < 0.25 and n > 1:
        state[rng.choice([j for j in range(n) if j != i])] = state[i]
    elif r < 0.5:
        state[i] = F(0)
    return state


def derivative_misses(g, rng, points=3):
    """(points, points where the tangent is not the derivative), over the
    field (a flow's) and the step, at random rational points, about
    half of them placed. A point at which the test's own derivative is
    undefined - a zero divisor, a negative root's argument, the root's
    derivative at zero (L4) - decides nothing and is not counted; where
    it is defined, the tangent sections must be too, and equal."""
    bad = tot = 0
    for section, tsection in (("field", "tangent_field"),
                              ("step", "tangent_step")):
        if g.section(section) is None:
            continue
        for _ in range(points):
            state = _point(rng, g.n_state)
            tangent = [_q(rng) for _ in range(g.n_state)]
            params = [_q(rng) for _ in g.param]
            lanes = [_q(rng) for _ in g.lane]
            try:
                want = dual_eval(g, section, state, tangent, params, lanes)
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


def tangent_corpus(count=60, seed="tangent corpus"):
    """Generated systems with tangent vectors - test_lang's random
    systems, which cover every operation, each given `tangent v` (one in
    four `tangent v, w`)."""
    rng = random.Random(seed)
    out, k = [], 0
    while len(out) < count:
        text = TL.random_system(rng, k)
        k += 1
        names = "v, w" if k % 4 == 0 else "v"
        try:
            out.append(compile_(with_tangent(text, names), f"random-{k}"))
        except lang.Refusal as r:
            assert r.name in TL._ARTIFACTS, f"{r}\n{text}"
    return out


# Ties and zeros placed where the conventions decide: operands EQUAL in
# value and DIFFERENT in tangent. Each system is evaluated at x = z with
# v.x != v.z - min(x, z), a tie inside an expression (min(x*y, z*y) and
# lets r = x*y, s = z*y), abs(x - z) and copysign's two sources at x - z
# - so that a tie given the second operand's tangent, or a zero's sign
# taken as -, changes the derivative there; the test asserts that it
# does at every point. (verifier-VL3: the ties this list placed before -
# min(x, x), abs(x - x) - had equal or zero tangents, where no
# convention can change the answer, and two planted conventions passed.)
# The value says which convention each system's points must tell apart.
TIES = {
    "the min family at a tie": (
        "system t\nformat fp64\nstate x, y, z, w\ntangent v\n"
        "next x = min(x, z) + y\nnext y = max(z, x) * y\n"
        "next z = minnum(x, z) * w\nnext w = maxnum(z, x) - w\n"
        "step map\n", ("tie",)),
    "abs and copysign's two sources at a zero": (
        "system t\nformat fp64\nstate x, y, z\ntangent v\n"
        "next x = abs(x - z) * y + x\nnext y = copysign(y, x - z)\n"
        "next z = copysign(x - z, y) + z\nstep map\n", ("zero",)),
    "a tie and a zero inside expressions": (
        "system t\nformat fp64\nstate x, y, z, w\ntangent v\n"
        "let r = x * y\nlet s = z * y\nnext x = min(r, s)\n"
        "next y = max(s, r) * w + abs(r - s)\n"
        "next z = minnum(x * w, z * w) - maxnum(z * y, x * y)\n"
        "next w = select(r < s, x, abs(z * w - x * w))\nstep map\n",
        ("tie", "zero")),
    "a flow's field at a tie and a zero": (
        "system t\nformat fp64\nstate x, y, z\ntangent v\n"
        "d/dt x = min(x, z) - y\nd/dt y = abs(x - z) * y\n"
        "d/dt z = maxnum(z, x) * x\nstep euler, h = 1/8\n",
        ("tie", "zero")),
}
OTHER = {"tie": {"tie": 1}, "zero": {"zero": -1}}


def placed(rng, g):
    """A point of a TIES system: x = z, every value nonzero, v.x != v.z."""
    while True:
        state = [_q(rng) for _ in range(g.n_state)]
        state[2] = state[0]
        tangent = [_q(rng) for _ in range(g.n_state)]
        if all(state) and tangent[0] != tangent[2]:
            return state, tangent


def test_the_tangent_is_the_derivative():
    """The fourth check, on the references with tangents, sixty
    generated systems that cover every operation, and the systems placed
    on ties and zeros, at random points, about half of them placed."""
    rng = random.Random("the derivative")
    tot = bad = 0
    ops = set()
    graphs = [tref(n) for n in TREFS] + tangent_corpus() + \
        [compile_(t) for t, _d in TIES.values()]
    for g in graphs:
        a, b = derivative_misses(g, rng)
        tot += a
        bad += b
        ops.update(g.op_counts("step"))
    assert tot > 300 and bad == 0, (tot, bad)
    # every operation but the math library's six, which have systems of
    # their own (test_m1_the_fourth_check_on_the_six, below)
    assert ops == set(lang.OPS) - set(TL.SIX)


def test_ties_and_zeros_are_placed_where_they_decide():
    """At every placed point of every TIES system, field and step: the
    tangent is the table's derivative, and it is NOT the derivative under
    the other convention the system's points decide - so a tie or zero
    convention that differs from the table fails here."""
    rng = random.Random("ties")
    points = 0
    for what, (text, decides) in TIES.items():
        g = compile_(text)
        for _ in range(6):
            state, tangent = placed(rng, g)
            for section, tsection in (("field", "tangent_field"),
                                      ("step", "tangent_step")):
                if g.section(section) is None:
                    continue
                got = g.exact_eval(tsection, state, tangent=tangent)
                want = dual_eval(g, section, state, tangent, [], [])
                assert got == want, (what, section, state, tangent)
                for d in decides:
                    other = dual_eval(g, section, state, tangent, [], [],
                                      **OTHER[d])
                    assert other != want, (what, section, d)
                points += 1
    assert points == 6 * (len(TIES) + 1)


class _Plant(lang_tangent.Derivation):
    kind = None

    def rule(self, node):
        a = node.args
        if node.op in ("mul", "fma"):
            da, db = self.of(a[0]), self.of(a[1])
            dc = self.of(a[2]) if node.op == "fma" else None
            R = self.read

            def N(o, *args):
                return Node(o, args, node.line)
            if da is not None and db is not None:
                if self.kind == "product":      # d(ab) = da db
                    p = N("mul", da, db)
                    return p if dc is None else N("add", p, dc)
                if self.kind == "primal":       # reads a where b is due
                    inner = N("mul", R(a[0]), db) if dc is None else \
                        N("fma", R(a[0]), db, dc)
                    return N("fma", da, R(a[0]), inner)
                if self.kind == "order":        # da*b + a*db, three roundings
                    s = N("add", N("mul", da, R(a[1])), N("mul", R(a[0]), db))
                    return s if dc is None else N("add", s, dc)
                if self.kind == "dropped" and dc is not None:
                    return N("fma", da, R(a[1]), N("mul", R(a[0]), db))
        return super().rule(node)


def _planted(kind, monkeypatch):
    class P(_Plant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check, "Derivation", P)


@pytest.mark.parametrize("kind", ["product", "dropped", "primal", "order"])
def test_the_plants(kind, monkeypatch):
    """Three wrong derivations, each red on the fourth check; and the
    rounding-order plant, which no exact check can see, green on it and
    red on the graph's bytes, which the committed compiled references and
    this document's rule table hold."""
    rng = random.Random(f"plant {kind}")
    clean = {n: tref(n).to_bytes() for n in TREFS}
    _planted(kind, monkeypatch)
    graphs = [tref(n) for n in TREFS]
    graphs += tangent_corpus(30, f"plant corpus {kind}")
    tot = bad = 0
    systems_red = 0
    for g in graphs:
        a, b = derivative_misses(g, rng, points=2)
        tot += a
        bad += b
        systems_red += b > 0
    changed = [n for n, g in zip(TREFS, graphs) if g.to_bytes() != clean[n]]
    if kind == "order":
        assert bad == 0 and changed, (bad, changed)
    else:
        assert bad > 0 and systems_red > 0, (kind, bad, tot)


# ---- construction A and B -----------------------------------------------------

def extended_source(g):
    """The system with its tangent written as more state (construction
    A): the canonical form's tangent equations, each v.x renamed v_x, as
    equations of a state v_x ...; no expansion block, so the template
    expands A from the extended right-hand sides."""
    canon = lang.render_canonical(g)
    body = canon.split("\nexpansion\n")[0]
    vec = g.tangent[0]
    out = []
    for line in body.splitlines():
        if line.startswith(";") or line.startswith(f"tangent "):
            continue
        line = re.sub(rf"\b{vec}\.", f"{vec}_", line)
        if line.startswith("state "):
            names = [x.strip() for x in line[6:].split(",")]
            line += ", " + ", ".join(f"{vec}_{x}" for x in names)
        m = re.match(r"step stormer-verlet(.*)q = \(([^)]*)\), p = \(([^)]*)\)",
                     line)
        if m:
            def ext(names):
                xs = [x.strip() for x in names.split(",")]
                return ", ".join(xs + [f"{vec}_{x}" for x in xs])
            line = (f"step stormer-verlet{m.group(1)}q = ({ext(m.group(2))}),"
                    f" p = ({ext(m.group(3))})")
        out.append(line)
    return "\n".join(out) + "\n"


class _Ids:
    def __init__(self):
        self.table = {}

    def __call__(self, key):
        return self.table.setdefault(key, len(self.table))


def _leaf(g, ref, n, ids):
    k, i = ref[0], int(ref[1:])
    if k == "s":
        return ids(("S", i) if i < n else ("T", i - n))
    if k == "t":
        return ids(("T", i))
    if k == "p":
        return ids(("P", g.param[i][0]))
    if k == "l":
        return ids(("L", g.lane[i][0]))
    v, fa, _b, _f = g.const[i]
    return ids(("C", v, fa))


def _ids_a(gA, n, ids):
    nodes = []
    for op, args, _l in gA.step.nodes:
        nodes.append(ids((op, tuple(nodes[int(a[1:])] if a[0] == "n"
                                    else _leaf(gA, a, n, ids)
                                    for a in args))))
    return [nodes[int(o[1:])] if o[0] == "n" else _leaf(gA, o, n, ids)
            for o in gA.step.out]


def _ids_b(g, ids):
    n = g.n_state
    nodes = []
    for op, args, _l in g.step.nodes:
        nodes.append(ids((op, tuple(nodes[int(a[1:])] if a[0] == "n"
                                    else _leaf(g, a, n, ids)
                                    for a in args))))
    tnodes = []

    def tget(a):
        if a[0] == "d":
            return tnodes[int(a[1:])]
        if a[0] == "n":
            return nodes[int(a[1:])]
        return _leaf(g, a, 10 ** 9, ids)
    for op, args, _l in g.tangent_step.nodes:
        tnodes.append(ids((op, tuple(tget(a) for a in args))))
    outs = [nodes[int(o[1:])] if o[0] == "n" else _leaf(g, o, n, ids)
            for o in g.step.out]
    return outs + [tget(o) for o in g.tangent_step.out]


def _zero_component(g):
    """Has the tangent field a component that is identically zero?"""
    return any(o[0] == "c" and g.const[int(o[1:])][0] == 0
               for o in g.tangent_field.out)


def test_a_and_b_agree_exactly_and_node_for_node_where_nothing_is_zero():
    rng = random.Random("A and B")
    flows = [g for g in [tref("lorenz63-rk4-tangent-fp64"),
                         compile_(with_tangent(
                             (SYSTEMS / "henonheiles-lf-fp64.cftl")
                             .read_text()))] + tangent_corpus(80, "a and b")
             if g.is_flow and len(g.tangent) == 1]
    same = differ = 0

    def outcome(fn):
        # a zero divisor or a negative root's argument (L4): undefined in
        # both constructions alike, which evaluate the same operations
        try:
            return fn()
        except ArithmeticError:
            return "undefined"
    for g in flows:
        gA = compile_(extended_source(g), "A")
        n = g.n_state
        for _ in range(2):
            state = [_q(rng) for _ in range(n)]
            tangent = [_q(rng) for _ in range(n)]
            params = [_q(rng) for _ in g.param]
            lanes = [_q(rng) for _ in g.lane]
            a = outcome(lambda: gA.exact_eval("step", state + tangent,
                                              params, lanes)[n:])
            b = outcome(lambda: g.exact_eval("tangent_step", state, params,
                                             lanes, tangent=tangent))
            assert a == b
        ids = _Ids()
        equal = _ids_a(gA, n, ids) == _ids_b(g, ids)
        if _zero_component(g):
            assert not equal
            differ += 1
        else:
            assert equal
            same += 1
    assert same >= 10 and differ >= 5, (same, differ)


def test_where_a_component_is_zero_a_rounds_and_b_does_not():
    """d/dt t = 1: A computes fma(h/2, 0, v.t), turning -0 into +0 and a
    signalling NaN into the canonical one; B leaves the term out."""
    text = ("system tdep\nformat fp64\nstate t, x\ntangent v\nd/dt t = 1\n"
            "d/dt x = fma(x, t, -x)\nstep rk4, h = 1/8\n")
    g = compile_(text)
    gA = compile_(extended_source(g))
    fmt = g.fmt
    third, two, one = (_bits(fmt, v) for v in (F(1, 3), 2, 1))
    for vt, a_bits in ((fmt.sign_mask, 0),
                       (sf.snan_bits(fmt, 1), sf.qnan_bits(fmt))):
        rb = lang.run(g, [[third, two]], 1, tangents=[[[vt, one]]])
        ra = lang.run(gA, [[third, two, vt, one]], 1)
        assert rb.tangents[0][0][0] == vt
        assert ra.states[0][2] == a_bits


# ---- the primal, unchanged ----------------------------------------------------

def _sections_by_value(g):
    """field and step, each const ref written as its (value, factor)."""
    def norm(sec):
        if sec is None:
            return None

        def r(a):
            return ("c", g.const[int(a[1:])][:2]) if a[0] == "c" else a
        return ([(op, tuple(r(a) for a in args), lb)
                 for op, args, lb in sec.nodes], [r(o) for o in sec.out])
    return norm(g.field), norm(g.step)


def test_the_primal_is_unchanged_by_tangents():
    rng = random.Random("primal unchanged")
    texts = [(SYSTEMS / f"{n}.cftl").read_text() for n in TREFS]
    texts += [lang.render_canonical(g) for g in tangent_corpus(40, "primal")]
    renumbered = 0
    for text in texts:
        g = compile_(text)
        g0 = compile_(_strip_tangent(text))
        if g.const == g0.const:
            # byte for byte: every line of the version-1 graph up to its
            # step's last, the version number and that line's closing aside
            b0 = g0.to_bytes().split(b"\n")
            b1 = g.to_bytes().split(b"\n")
            assert b1[0] == b0[0].replace(b'"cftl_graph":1,',
                                          b'"cftl_graph":2,')
            assert b1[1:len(b0) - 2] == b0[1:-2]
            assert b1[len(b0) - 2] == b0[-2][:-1] + b","
        else:
            renumbered += 1
            # only 0, 1, -1 and 2 may join the table (2 by the root's rule)
            added = {v for v, _fa, _b, _f in g.const} - \
                {v for v, _fa, _b, _f in g0.const}
            assert added <= {F(0), F(1), F(-1), F(2)}
        assert _sections_by_value(g) == _sections_by_value(g0)
        states = [[_bits(g.fmt, _q(rng)) for _ in range(g.n_state)]
                  for _ in range(3)]
        tans = [[[_bits(g.fmt, _q(rng)) for _ in range(g.n_state)]
                 for _ in g.tangent] for _ in states]
        lanes = [[_bits(g.fmt, F(rng.randint(1, 9), 4)) for _ in g.lane]
                 for _ in states] if g.lane else None
        r0 = lang.run(g0, states, 3, lane_params=lanes)
        r1 = lang.run(g, states, 3, lane_params=lanes, tangents=tans)
        assert r0.states == r1.states and r0.flags == r1.primal_flags
    assert renumbered > 0


def _strip_tangent(canon):
    """A canonical form without its tangent: the declaration, the tangent
    equations and lets, and the block's tangent lines dropped."""
    out = []
    for line in canon.split("\n"):
        s = line.strip()
        if line.startswith("tangent ") or line.startswith(";"):
            continue
        if re.match(r"(let|next|d/dt) (v|w)\.", s):
            continue
        out.append(line)
    return "\n".join(out)


def test_every_version_1_graph_is_unchanged():
    """The six references' graphs are the committed compiled .graph.json
    files, byte for byte, version 1."""
    for name in TL.REFS:
        g = TL.ref(name)
        assert g.version == 1
        assert (COMPILED / f"{name}.graph.json").read_bytes() == g.to_bytes()


# ---- the interpreter --------------------------------------------------------

def test_the_interpreters_tangents_and_their_refusals():
    g = tref("lorenz63-rk4-tangent-fp64")
    fmt = g.fmt
    s = [_bits(fmt, v) for v in (1, 2, 20)]
    t = [_bits(fmt, 1), 0, 0]
    r = lang.run(g, [s], 4, at=(2,), tangents=[[t]])
    assert len(r.tangents) == 1 and len(r.tangents[0]) == 1
    assert r.at_tangents[2][0][0] != t
    cases = [
        ("lane-shape", dict(states=[s], steps=1)),
        ("lane-shape", dict(states=[s], steps=1, tangents=[[t, t]])),
        ("lane-shape", dict(states=[s], steps=1, tangents=[[t[:2]]])),
        ("lane-shape", dict(states=[s], steps=1, tangents=[[t], [t]])),
        ("lane-value", dict(states=[s], steps=1, tangents=[[[1 << 64, 0,
                                                            0]]])),
    ]
    for name, kw in cases:
        with pytest.raises(lang.Refusal) as e:
            lang.run(g, **kw)
        assert e.value.name == name, (kw, e.value)
    with pytest.raises(lang.Refusal) as e:
        lang.run(TL.ref("lorenz63-rk4-fp64"), [s], 1, tangents=[[t]])
    assert e.value.name == "lane-shape"


def test_two_vectors_are_two_runs_of_one():
    """Each vector is the generic tangent applied to its own inputs."""
    g2 = compile_(with_tangent((SYSTEMS / "lorenz63-rk4-fp64.cftl")
                               .read_text(), "v, w"))
    g1 = tref("lorenz63-rk4-tangent-fp64")
    fmt = g1.fmt
    s = [[_bits(fmt, v) for v in (1, 2, 20)]]
    a, b = [_bits(fmt, 1), 0, 0], [0, _bits(fmt, F(1, 3)), 0]
    r2 = lang.run(g2, s, 7, tangents=[[a, b]])
    ra = lang.run(g1, s, 7, tangents=[[a]])
    rb = lang.run(g1, s, 7, tangents=[[b]])
    assert r2.tangents[0] == [ra.tangents[0][0], rb.tangents[0][0]]
    assert r2.flags == ra.flags | rb.flags


# ---- writing them out ------------------------------------------------------------

def test_a_written_tangent_that_is_the_derivations_is_accepted():
    for name in TREFS:
        g = tref(name)
        assert compile_(lang.render_canonical(g)).to_bytes() == g.to_bytes()
    doc = DOC.read_text(encoding="utf-8")
    l96 = doc.split("Lorenz-96, its tangent equation written out:", 1)[1]
    l96 = l96.split("```\n", 2)[1]
    assert compile_(l96).to_bytes() == \
        tref("lorenz96-rk4-tangent-fp64").to_bytes()


WRITTEN = {   # a written tangent, and the refusal and line it meets
    "a different rounding order": (
        "system s\nformat fp64\nstate x\ntangent v\nnext x = x * x\n"
        "next v.x = v.x * x + x * v.x\nstep map\n", "tangent-mismatch", 6),
    "a primal value read by name where it is written again": (
        "system s\nformat fp64\nstate x, y\ntangent v\nlet r = y - x\n"
        "next x = x * (y - x)\nnext y = r\nnext v.x = fma(v.x, r, x * "
        "(v.y - v.x))\nnext v.y = v.y - v.x\nstep map\n",
        "tangent-mismatch", 8),
    "half of a vector's equations": (
        "system s\nformat fp64\nstate x, y\ntangent v\nnext x = y\n"
        "next y = x\nnext v.x = v.y\nstep map\n", "missing-equation", 7),
    "a tangent read by the state": (
        "system s\nformat fp64\nstate x\ntangent v\nnext x = x + v.x\n"
        "step map\n", "tangent-scope", 5),
    "another vector's component": (
        "system s\nformat fp64\nstate x\ntangent v, w\nnext x = x * x\n"
        "next v.x = fma(v.x, x, x * w.x)\nnext w.x = fma(w.x, x, x * w.x)\n"
        "step map\n", "tangent-scope", 6),
    "a vector read whole": (
        "system s\nformat fp64\nstate x\ntangent v\nnext x = x\n"
        "next v.x = v\nstep map\n", "tangent-scope", 6),
    "a tangent in a constant": (
        "system s\nformat fp64\nstate x\ntangent v\nconst c = v.x\n"
        "next x = x * c\nstep map\n", "tangent-scope", 5),
    "a tangent of no state component": (
        "system s\nformat fp64\nstate x\ntangent v\nnext x = x\n"
        "next v.q = v.x\nstep map\n", "not-state", 6),
    "a tangent let of no let": (
        "system s\nformat fp64\nstate x\ntangent v\nnext x = x\n"
        "let v.r = v.x\nnext v.x = v.r\nstep map\n", "undefined-name", 6),
    "a tangent let without the equations": (
        "system s\nformat fp64\nstate x\ntangent v\nlet r = x * x\n"
        "next x = r\nlet v.r = fma(v.x, x, x * v.x)\nstep map\n",
        "missing-equation", 7),
    "a flow's tangent written as a map's": (
        "system s\nformat fp64\nstate x\ntangent v\nd/dt x = -x\n"
        "next v.x = -v.x\nstep euler, h = 1/8\n", "mixed-equations", 6),
    "a vector named after a stage": (
        "system s\nformat fp64\nstate x\ntangent Y2\nd/dt x = -x\n"
        "step rk4, h = 1/8\n", "reserved-name", 4),
    "a vector named twice": (
        "system s\nformat fp64\nstate x\ntangent v, v\nnext x = x\n"
        "step map\n", "duplicate-name", 4),
    "a vector named as the state": (
        "system s\nformat fp64\nstate x\ntangent x\nnext x = x\n"
        "step map\n", "duplicate-name", 4),
    "a dotted vector": (
        "system s\nformat fp64\nstate x\ntangent v.w\nnext x = x\n"
        "step map\n", "syntax", 4),
    "too many tangent vectors for a lane": (
        "system s\nformat fp64\nstate x[20000]\ntangent v\n"
        "next x[i] = x[i]\nstep map\n", "lane-capacity", 3),
}


@pytest.mark.parametrize("what", sorted(WRITTEN))
def test_what_is_written_is_held_by_name(what):
    text, name, line = WRITTEN[what]
    with pytest.raises(lang.Refusal) as e:
        compile_(text, "probe.cftl")
    assert (e.value.name, e.value.line) == (name, line), str(e.value)


def test_a_mismatch_is_named_at_its_first_difference():
    g = tref("lorenz63-rk4-tangent-fp64")
    canon = lang.render_canonical(g)
    bad = canon.replace("let v.k2.y = fma(v.Y2.x, rho - Y2.z,",
                        "let v.k2.y = fma(v.Y2.x, Y2.z - rho,")
    assert bad != canon
    with pytest.raises(lang.Refusal) as e:
        compile_(bad, "probe.cftl")
    assert e.value.name == "tangent-mismatch"
    line = bad.splitlines()[e.value.line - 1]
    assert line.strip().startswith("let v.k2.y"), line
    assert "v.k2.y" in e.value.sentence


def test_a_block_writes_all_of_a_vectors_lines_or_none():
    g = tref("lorenz63-rk4-tangent-fp64")
    canon = lang.render_canonical(g)
    # none: accepted, and the same graph
    none = "\n".join(ln for ln in canon.split("\n")
                     if not re.match(r"  (let|next) v\.", ln))
    assert compile_(none).to_bytes() == g.to_bytes()
    part = "\n".join(ln for ln in canon.split("\n")
                     if not ln.startswith("  next v.z"))
    with pytest.raises(lang.Refusal) as e:
        compile_(part)
    assert e.value.name == "missing-equation"


# ---- the intention-out --------------------------------------------------------

NAMED = {
    "eta-flow": ("system g\nformat fp128\nround rdn\nstate Theta, omega\n"
                 "tangent eta\nparam gamma = 1/10\nlane param mu = 2/3\n"
                 "let phi = mu * Theta\nd/dt Theta = omega\n"
                 "d/dt omega = -(phi + gamma * omega)\nstep rk4, h = 1/64\n"),
    "two-sv": ("system sv\nformat fp32\nround rup\nstate xi, pi\n"
               "tangent v, w\nlane param kappa\nd/dt xi = pi\n"
               "d/dt pi = -(kappa * xi * xi)\n"
               "step stormer-verlet, h = 0.01, q = (xi), p = (pi)\n"),
    "map-lets": ("system m\nformat fp256\nround rmm\nstate a[3] cyclic\n"
                 "tangent nu\nlet Delta[i] = a[i+1] - a[i] for i in 0..2\n"
                 "next a[i] = fma(h * 3, Delta[i] * Delta[i], a[i])\n"
                 "step map, h = 1/2\n"),
    "time-euler": ("system e\nformat fp64\nround rtz\nstate t, lambda\n"
                   "tangent v\nparam tau = 1/3\nd/dt t = 1\n"
                   "d/dt lambda = -(tau * abs(lambda - t))\n"
                   "step euler, h = 1/8\n"),
}


@pytest.mark.parametrize("name", TREFS + sorted(NAMED))
def test_intention_out_of_variational_systems(name):
    g = tref(name) if name in TREFS else compile_(NAMED[name], name)
    TL.check_intention_out(g, random.Random(f"tangent io {name}"))


def test_intention_out_of_random_variational_systems():
    rng = random.Random("tangent io random")
    for g in tangent_corpus(40, "io corpus"):
        TL.check_intention_out(g, rng, points=2)


_TANGENT_PLANTS = [
    ("canonical", lambda t: t.replace("d/dt v.y = fma(v.x, rho - z,",
                                      "d/dt v.y = fma(rho - z, v.x,", 1)),
    ("math", lambda t: t.replace("+ x·(−v.z) − v.y", "− v.y", 1)),
    ("math", lambda t: t.replace("of the tangent vector v",
                                 "of the tangent vector w", 1)),
    ("math", lambda t: t.replace(
        "  δk4 = Df(Y + h·k3)·(δY + h·δk3)\n",
        "  δk4 = Df(Y + h·k3)·(δY + h·δk3)\n"
        "  δk5 = Df(Y + h·k4)·(δY + h·δk4)\n", 1)),
    ("math", lambda t: t.replace("  δY = (v.x, v.y, v.z)",
                                 "  δY = (v.y, v.x, v.z)", 1)),
    ("canonical", lambda t: t.replace(";             and its step 65",
                                      ";             and its step 64", 1)),
]


def test_the_tangents_printed_lines_have_teeth():
    """Each plant changes one printed thing of Lorenz-63's tangent - a
    swapped multiplicand, a dropped term, the vector's name, an extra
    stage, δY's order, a count - and one of the four checks catches it."""
    g = tref("lorenz63-rk4-tangent-fp64")
    canon, math = lang.render_canonical(g), lang.render_math(g)
    for which, plant in _TANGENT_PLANTS:
        c2 = plant(canon) if which == "canonical" else canon
        m2 = plant(math) if which == "math" else math
        assert (c2, m2) != (canon, math), which
        caught = False
        try:
            TL.check_comments(g, c2, m2)
        except AssertionError:
            caught = True
        if not caught and c2 != canon:
            try:
                caught = compile_(c2).to_bytes() != g.to_bytes()
            except lang.Refusal:
                caught = True
        if not caught and m2 != math:
            form = MathForm(m2)
            rng = random.Random("teeth")
            state, params, lanes = TL._point(g, rng)
            tangent = TL._point(g, rng)[0]
            caught = (form.tangent_field(0, state, tangent, params, lanes)
                      != g.exact_eval("tangent_field", state, params, lanes,
                                      tangent=tangent))
        assert caught, (which, plant)


# ---- L4: the quotient's and the root's rules --------------------------------------
#
# d(a / b) = fma(-r, db, da) / b and d sqrt(a) = da / (2 * r), r the
# operation's own result (docs/LANGUAGE.md, "The quotient and the root").

def _l4_one(text, state, tangent, params=None):
    g = compile_(text)
    r = lang.run(g, [state], 1, tangents=[[tangent]], params=params)
    return r.states[0], r.tangents[0][0], r.flags, r.primal_flags


def test_l4_the_quotient_and_the_root_at_their_specials():
    """Bit for bit through the interpreter: the root's tangent at +0 and -0
    (an infinity with divide-by-zero, the zero's sign; a NaN with invalid
    where the tangent is zero too), below zero (a NaN, the primal's invalid
    only), at +infinity (a zero, no flag), exact at a square and one
    rounding off it; the quotient's at a zero divisor (with and without
    the divisor's tangent), exact, inexact, and by a param, zero too."""
    fmt = FORMATS["fp64"]

    def b(v):
        return _bits(fmt, v)
    sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
    root = ("system s\nformat fp64\nstate x, y\ntangent v\nnext x = x\n"
            "next y = sqrt(x)\nstep map\n")
    cases = [   # x, v.x -> y's tangent, FLAGS, the primal's flags
        (0, b(3), inf, sf.FLAG_DIVZERO, 0),
        (sign, b(3), inf ^ sign, sf.FLAG_DIVZERO, 0),
        (0, 0, qnan, sf.FLAG_INVALID, 0),
        (b(-1), b(3), qnan, sf.FLAG_INVALID, sf.FLAG_INVALID),
        (inf, b(3), 0, 0, 0),
        (b(4), b(3), b(F(3, 4)), 0, 0),
    ]
    for x, vx, want, flags, pflags in cases:
        _s, t, f, pf = _l4_one(root, [x, 0], [vx, 0])
        assert (t[1], f, pf) == (want, flags, pflags), (hex(x), hex(vx))
    _s, t, f, _pf = _l4_one(root, [b(2), 0], [b(1), 0])
    s2 = sf.sqrt(fmt, b(2))[0]
    assert t[1] == sf.div(fmt, b(1), sf.mul(fmt, b(2), s2)[0])[0]
    assert f == sf.FLAG_INEXACT
    quo = ("system s\nformat fp64\nstate x, y, z\ntangent v\nnext x = x\n"
           "next y = y\nnext z = x / y\nstep map\n")
    one = b(1)
    # r = 1/0 = +inf; fma(-inf, 1, 1) = -inf, over +0 -inf: no new flag
    _s, t, f, pf = _l4_one(quo, [one, 0, 0], [one, one, 0])
    assert (t[2], f, pf) == (inf ^ sign, sf.FLAG_DIVZERO, sf.FLAG_DIVZERO)
    # the same with v.y = 0: -inf * 0 is invalid
    _s, t, f, _pf = _l4_one(quo, [one, 0, 0], [one, 0, 0])
    assert (t[2], f) == (qnan, sf.FLAG_DIVZERO | sf.FLAG_INVALID)
    # r = 6/3 = 2: (7 - 2 * 2) / 3 = 1, exact; (1 - 2 * 1) / 3 rounds once
    _s, t, f, _pf = _l4_one(quo, [b(6), b(3), 0], [b(7), b(2), 0])
    assert (t[2], f) == (one, 0)
    _s, t, f, _pf = _l4_one(quo, [b(6), b(3), 0], [one, one, 0])
    assert (t[2], f) == (b(F(-1, 3)), sf.FLAG_INEXACT)
    # by a param, db identically zero: v.x / p, and a zero p an infinity
    byp = ("system s\nformat fp64\nstate x, y\ntangent v\nparam p = 3\n"
           "next x = x\nnext y = x / p\nstep map\n")
    _s, t, f, _pf = _l4_one(byp, [b(3), 0], [b(6), 0])
    assert (t[1], f) == (b(2), 0)
    _s, t, f, _pf = _l4_one(byp, [b(3), 0], [b(6), 0], params={"p": 0})
    assert (t[1], f) == (inf, sf.FLAG_DIVZERO)


def _structural(g):
    """(the primal step's node ids, the tangent step's ops and ids), each
    id an operation on ids - so a value written again in the tangent has
    the primal's id, as the compiler's sharing makes it one operation."""
    ids = _Ids()
    n = g.n_state
    pn = []
    for op, args, _l in g.step.nodes:
        pn.append(ids((op, tuple(pn[int(a[1:])] if a[0] == "n"
                                 else _leaf(g, a, n, ids) for a in args))))
    tn = []

    def get(a):
        if a[0] == "d":
            return tn[int(a[1:])]
        if a[0] == "n":
            return pn[int(a[1:])]
        return _leaf(g, a, 10 ** 9, ids)
    for op, args, _l in g.tangent_step.nodes:
        tn.append(ids((op, tuple(get(a) for a in args))))
    return set(pn), [(op, i) for (op, _a, _l), i in
                     zip(g.tangent_step.nodes, tn)]


def _reading_state(sec):
    """For each node of a primal section, whether its tangent can be other
    than zero - whether it reads the state through an operand whose
    tangent its rule reads (none of a comparison's, a select's arms and
    not its condition, copysign's first) - by the test's own walk."""
    reads = []
    for op, args, _l in sec.nodes:
        rel = () if op in ("cmplt", "cmple", "cmpeq") else \
            args[:2] if op == "select" else \
            args[:1] if op == "copysign" else args
        reads.append(any(a[0] == "s" or (a[0] == "n" and reads[int(a[1:])])
                         for a in rel))
    return reads


def _read_by_tangent(sec):
    """For each node of a primal section, whether the section's tangent
    reads its tangent: whether it reaches an output through operands whose
    tangents the rules read (none of a comparison's, a select's arms and
    not its condition, copysign's first) - the derivation's walk from the
    outputs, by the test's own code."""
    read = [False] * len(sec.nodes)
    stack = [int(o[1:]) for o in sec.out if o[0] == "n"]
    while stack:
        k = stack.pop()
        if read[k]:
            continue
        read[k] = True
        op, args, _l = sec.nodes[k]
        rel = () if op in ("cmplt", "cmple", "cmpeq") else \
            args[:2] if op == "select" else \
            args[:1] if op == "copysign" else args
        stack += [int(a[1:]) for a in rel if a[0] == "n"]
    return read


def test_l4_each_vector_pays_one_division_a_quotient_or_root():
    """After sharing what the tangent writes again, a tangent vector's step
    holds one division of its own for each division and each root of the
    step whose tangent the step's tangent reads - not zero, and reaching an
    output through operands the rules differentiate - none for any other,
    and no root of its own: rk4 with one division and one root in its
    right-hand sides performs eight a step, and each vector adds eight;
    with params p and q, x * (p / q) and y / p + sqrt(q) perform three a
    step, and each vector adds one (verifier-VL4's (b)2). A division or
    root that reads the state only through a comparison, a select's
    condition or copysign's sign costs nothing either: select(x < 0, p, q)
    / p reads x and costs 0, as do copysign(p, x) / q and
    sqrt(select(y < 0, p, q)), beside the control x / p * q, which costs 1
    (verifier-VL4's re-check). And one whose tangent is not zero costs
    nothing where it reaches the outputs only through those operands, since
    the derivation forms no tangent of it there: select(x / y < 1, x, y),
    select(sqrt(abs(x)) < 1, x, y), copysign(x, x / y) and y + (y / z < 1)
    cost 0, beside the control z / x (verifier-VL4's third check)."""
    for text, per_step, per_vector in (
            ("system c\nformat fp64\nstate x, y\ntangent v\n"
             "d/dt x = x / (y * y + 1)\nd/dt y = -sqrt(abs(x) + 1)\n"
             "step rk4, h = 1/8\n", 8, 8),
            ("system c\nformat fp64\nstate x, y\ntangent v, w\n"
             "next x = x / y\nnext y = sqrt(x * x + y)\nstep map\n", 2, 2),
            ("system c\nformat fp64\nstate x, y\ntangent v\n"
             "param p = 2, q = 3\nnext x = x * (p / q)\n"
             "next y = y / p + sqrt(q)\nstep map\n", 3, 1),
            ("system c\nformat fp64\nstate x, y\ntangent v\n"
             "param p = 2, q = 3\nnext x = x + select(x < 0, p, q) / p\n"
             "next y = y\nstep map\n", 1, 0),
            ("system c\nformat fp64\nstate x, y, z\ntangent v\n"
             "param p = 2, q = 3\nnext x = x + copysign(p, x) / q\n"
             "next y = y + sqrt(select(y < 0, p, q))\nnext z = x / p * q\n"
             "step map\n", 3, 1),
            ("system c\nformat fp64\nstate x, y\ntangent v\n"
             "next x = select(x / y < 1, x, y)\n"
             "next y = select(sqrt(abs(x)) < 1, x, y)\nstep map\n", 2, 0),
            ("system c\nformat fp64\nstate x, y, z\ntangent v, w\n"
             "next x = copysign(x, x / y)\nnext y = y + (y / z < 1)\n"
             "next z = z / x\nstep map\n", 3, 1)):
        g = compile_(text)
        primal, tangent = _structural(g)
        routines = [k for k, (op, _a, _l) in enumerate(g.step.nodes)
                    if op in ("div", "sqrt")]
        assert len(routines) == per_step, text
        nonzero, read = _reading_state(g.step), _read_by_tangent(g.step)
        assert sum(nonzero[k] and read[k] for k in routines) == per_vector, \
            text
        own_div = {i for op, i in tangent if op == "div" and i not in primal}
        own_sqrt = {i for op, i in tangent if op == "sqrt" and i not in primal}
        assert (len(own_div), len(own_sqrt)) == (per_vector, 0), text


def test_l4_unnamed_quotients_and_roots_grow_with_the_square():
    """The known limit's figures for the quotient and the root (L4,
    verifier-VL4): their rules read the operation's own result, so an
    unnamed chain writes it again at every level, as a product's does."""
    names = [f"x{i}" for i in range(100)]
    head = f"system c\nformat fp64\nstate {', '.join(names)}\ntangent v\n"
    tail = "".join(f"next {x} = {x}\n" for x in names[1:]) + "step map\n"
    chain = head + "next x0 = " + " / ".join(names) + "\n" + tail
    assert len(compile_(chain).tangent_step.nodes) == 5247
    lets = "".join(f"let q{k} = {'x0' if k == 1 else f'q{k - 1}'} / x{k}\n"
                   for k in range(1, 100))
    named = head + lets + "next x0 = q99\n" + tail
    assert len(compile_(named).tangent_step.nodes) == 297
    e = "x"
    for _ in range(99):
        e = f"sqrt({e})"
    roots = f"system r\nformat fp64\nstate x\ntangent v\nnext x = {e}\nstep map\n"
    assert len(compile_(roots).tangent_step.nodes) == 5148


L4_SYSTEMS = {
    "map": ("system m\nformat fp64\nstate x, y, z\ntangent v\n"
            "param p = 3/7\nnext x = x / y + sqrt(z * z + 1)\n"
            "next y = fma(y, p, 1) / (x * x + 2)\n"
            "next z = sqrt(abs(x - y)) / p\nstep map\n"),
    "rk4": ("system f\nformat fp64\nstate x, y\ntangent v\n"
            "let q = x / (y * y + 1)\nd/dt x = q - sqrt(abs(x) + 1)\n"
            "d/dt y = x / sqrt(y * y + 2)\nstep rk4, h = 1/8\n"),
    "stormer-verlet": ("system k\nformat fp64\nstate q, p\ntangent v\n"
                       "d/dt q = p / sqrt(p * p + 1)\n"
                       "d/dt p = -(q / sqrt(q * q + 4))\n"
                       "step stormer-verlet, h = 1/16, q = (q), p = (p)\n"),
    "euler, two vectors": ("system e\nformat fp64\nstate x\ntangent v, w\n"
                           "d/dt x = 1 / (x * x + 1)\nstep euler, h = 1/8\n"),
}
FD_EPS = F(1, 1 << 64)
FD_TOL = F(1, 1 << 100)


def fd_misses(g, rng, points=3):
    """(points, points where a tangent component is not the central
    difference): (S(x + eps v) - S(x - eps v)) / (2 eps) of a primal
    section S in exact rationals, eps = 2^-64, each root the evaluation's
    2^-256 one - so the difference's error is O(eps^2) plus at most about
    2^-190 - against the tangent section, every component within 2^-100
    max(1, |tangent|). The derivative itself, whatever the root's
    convention. Unplaced random points: a difference is no derivative at
    a kink; an undefined point decides nothing."""
    tot = bad = 0
    for section, tsection in (("field", "tangent_field"),
                              ("step", "tangent_step")):
        if g.section(section) is None:
            continue
        for _ in range(points):
            st = [_q(rng) for _ in range(g.n_state)]
            tv = [_q(rng) for _ in range(g.n_state)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            try:
                up = g.exact_eval(section, [s + FD_EPS * t for s, t in
                                            zip(st, tv)], pa, la)
                dn = g.exact_eval(section, [s - FD_EPS * t for s, t in
                                            zip(st, tv)], pa, la)
                got = g.exact_eval(tsection, st, pa, la, tangent=tv)
            except ArithmeticError:
                continue
            tot += 1
            bad += any(abs((u - d) / (2 * FD_EPS) - t) >
                       FD_TOL * max(1, abs(t)) for u, d, t in zip(up, dn, got))
    return tot, bad


def _l4_graphs(corpus=24, seed="l4 corpus"):
    """The written L4 systems, and generated systems with tangent vectors
    that divide or take a root."""
    graphs = [compile_(t) for t in L4_SYSTEMS.values()]
    graphs += [g for g in tangent_corpus(corpus, seed)
               if {"div", "sqrt"} & set(g.op_counts("step"))]
    return graphs


def test_l4_the_rules_are_the_derivative():
    """The fourth check (exact dual numbers, the quotient by the textbook's
    rule) and a central difference, on the written L4 systems - a map, rk4
    with a let, stormer-verlet, euler with two vectors - and on generated
    ones that divide or take a root: no miss at any point."""
    rng = random.Random("l4 derivative")
    graphs = _l4_graphs()
    assert len(graphs) >= 12
    tot = bad = ftot = fbad = 0
    for g in graphs:
        a, b = derivative_misses(g, rng, points=4)
        tot, bad = tot + a, bad + b
        a, b = fd_misses(g, rng, points=3)
        ftot, fbad = ftot + a, fbad + b
    assert bad == 0 and tot >= 60, (tot, bad)
    assert fbad == 0 and ftot >= 60, (ftot, fbad)


class _L4Plant(lang_tangent.Derivation):
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        if node.op == "sqrt" and self.of(a[0]) is not None:
            da = self.of(a[0])
            if self.kind == "root without its 2":       # da / r
                return N("div", da, R(node))
            if self.kind == "root through r*r = a":     # da r / (2 a)
                return N("div", N("mul", da, R(node)),
                         N("mul", self.two, R(a[0])))
        if node.op == "div" and self.kind == "quotient's sign":
            da, db = self.of(a[0]), self.of(a[1])
            if da is not None and db is not None:       # (da + r db) / b
                return N("div", N("fma", R(node), db, da), R(a[1]))
        return super().rule(node)


@pytest.mark.parametrize("kind", ["root without its 2", "quotient's sign",
                                  "root through r*r = a"])
def test_l4_the_plants(kind, monkeypatch):
    """Two wrong rules, each red on the exact check and on the central
    difference; and a right derivative written through r * r = a, green on
    the difference and red on the exact check, which holds the rule's form
    as the committed bytes hold a rounding order."""
    class P(_L4Plant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check, "Derivation", P)
    rng = random.Random(f"l4 plant {kind}")
    tot = bad = ftot = fbad = 0
    for g in _l4_graphs(12, f"l4 plant corpus {kind}"):
        a, b = derivative_misses(g, rng, points=2)
        tot, bad = tot + a, bad + b
        a, b = fd_misses(g, rng, points=2)
        ftot, fbad = ftot + a, fbad + b
    assert tot and ftot
    assert bad > 0, (kind, tot)
    if kind == "root through r*r = a":
        assert fbad == 0, (kind, ftot, fbad)
    else:
        assert fbad > 0, (kind, ftot)


# ---- M1's build, item 3: the math library's six rules ----------------------------
#
# r the operation's own result and L ln 2 rounded once at the program's format
# under its attribute (docs/LANGUAGE.md, "The rules"):
#   exp(a)    r * da                            one rounding
#   expm1(a)  (1 + r) * da                      two: 1 + r primal-only
#   exp2(a)   (L * r) * da                      two: L * r primal-only
#   log(a)    select(r == r, da / a, r)         one: the division
#   log2(a)   select(r == r, da / (L * a), r)   two: L * a primal-only
#   log1p(a)  select(r == r, da / (1 + a), r)   two: 1 + a primal-only
# The study's expm1 rule was fma(r, da, da), which reads da twice: the step
# graph gives an unlabelled node one use (graph.canonical), and writing da
# again would double the tangent at each nested expm1, so the lead decided
# (1 + r) * da (2026-10-15). The three logarithms take the select form, so
# that below the domain the tangent is the NaN r (question 7, decided).
# A test that runs or evaluates the six skips by name without mpmath
# (test_lang.needs_mpmath); the rule table and the structure tests run.

RNDS = ("rne", "rtz", "rdn", "rup", "rmm")
M1_SYSTEMS = {   # the six under each integrator, in lets and equations
    "one of each, a map": (
        "system six\nformat fp64\nstate x, y, z\ntangent v\n"
        "next x = exp(y) - expm1(z * x)\n"
        "next y = exp2(x * y) + log(abs(z) + 1)\n"
        "next z = log2(x * x + 1) * log1p(abs(y))\nstep map\n"),
    "rk4, a let": (
        "system decay\nformat fp128\nround rdn\nstate y, mu\ntangent v\n"
        "param kappa = 1/3\nlet eta = expm1(-(kappa * y))\n"
        "d/dt y = eta * exp(mu)\nd/dt mu = -(exp2(y) * mu)\n"
        "step rk4, h = 1/64\n"),
    "stormer-verlet": (
        "system pot\nformat fp32\nround rup\nstate q, p\ntangent v\n"
        "d/dt q = p / log1p(p * p + 1)\n"
        "d/dt p = -(log(q * q + 1) * log2(q * q + 2))\n"
        "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
    "euler, two vectors": (
        "system e\nformat fp256\nround rmm\nstate x\ntangent v, w\n"
        "d/dt x = exp2(-x) + log(x * x + 1)\nstep euler, h = 1/8\n"),
}


def _m1_graphs(count=16, seed="m1 corpus"):
    """The written M1 systems, and generated systems with tangent vectors
    holding the six beside every other operation (test_lang's generator)."""
    graphs = [compile_(t, w) for w, t in M1_SYSTEMS.items()]
    rng = random.Random(seed)
    k = 0
    while len(graphs) < len(M1_SYSTEMS) + count:
        text = TL.random_system(rng, k, expr=TL._m1_expr)
        k += 1
        try:
            g = compile_(with_tangent(text, "v, w" if k % 4 == 0 else "v"),
                         f"m1-{k}")
        except lang.Refusal as r:
            assert r.name in TL._M1_ARTIFACTS, f"{r}\n{text}"
            continue
        if set(TL.SIX) & set(g.op_counts("step")):
            graphs.append(g)
    return graphs


HP_EPS = F(1, 1 << 256)
HP_TOL = F(1, 1 << 300)
_LN2_HP = []


def _ln2_hp():
    """ln 2 to 1,100 bits, an exact rational: mpmath's."""
    if not _LN2_HP:
        import mpmath
        ctx = mpmath.MPContext()
        ctx.prec = 1100
        sign, man, exp, _bc = ctx.mpf(ctx.ln2)._mpf_
        _LN2_HP.append(F(int(man), 1 << -exp))
    return _LN2_HP[0]


def hp_misses(g, rng, points=3):
    """(points, points where a tangent component is not the central
    difference in high precision): (S(x + eps v) - S(x - eps v)) / (2 eps)
    of a primal section S, eps = 2^-256, each of the six the exact
    evaluation's 1,024-bit value, against the tangent section, every
    component within 2^-300 max(1, |tangent|) - the derivative itself, as
    L4's central difference holds the root's. L is ln 2 rounded once, so
    the rules of exp2 and log2 are the derivative only with ln 2 in its
    place: the const equal to the test's own L (transcend.log of 2) is
    evaluated as ln 2 to 1,100 bits - and a graph whose L is not the
    test's keeps it, and misses by its rounding, 2^-p and more. Unplaced
    random points; an undefined point decides nothing."""
    L = _ln2(g.fmt, g.rnd)
    g2 = g.copy(const=[(_ln2_hp() if v == L and fa is None else v, fa, b, f)
                       for v, fa, b, f in g.const])
    tot = bad = 0
    for section, tsection in (("field", "tangent_field"),
                              ("step", "tangent_step")):
        if g.section(section) is None:
            continue
        for _ in range(points):
            st = [_q(rng) for _ in range(g.n_state)]
            tv = [_q(rng) for _ in range(g.n_state)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            try:
                up = g2.exact_eval(section, [s + HP_EPS * t for s, t in
                                             zip(st, tv)], pa, la)
                dn = g2.exact_eval(section, [s - HP_EPS * t for s, t in
                                             zip(st, tv)], pa, la)
                got = g2.exact_eval(tsection, st, pa, la, tangent=tv)
            except ArithmeticError:
                continue
            tot += 1
            bad += any(abs((u - d) / (2 * HP_EPS) - t) >
                       HP_TOL * max(1, abs(t)) for u, d, t in zip(up, dn, got))
    return tot, bad


@TL.needs_mpmath
def test_m1_the_rules_are_the_derivative():
    """The fourth check - the tangent evaluated exactly against the test's
    own dual numbers, each of the six as the exact evaluation takes it and
    ln 2 as the test's L - and the central difference in high precision,
    on the written M1 systems and on generated ones: no miss at any point,
    and most points decide."""
    rng = random.Random("m1 derivative")
    graphs = _m1_graphs()
    assert len(graphs) == len(M1_SYSTEMS) + 16
    tot = bad = htot = hbad = 0
    for g in graphs:
        a, b = derivative_misses(g, rng, points=3)
        tot, bad = tot + a, bad + b
        a, b = hp_misses(g, rng, points=2)
        htot, hbad = htot + a, hbad + b
    assert bad == 0 and tot >= 40, (tot, bad)
    assert hbad == 0 and htot >= 30, (htot, hbad)


def _one(fn, fmtname="fp64", rnd="rne"):
    return compile_(f"system r\nformat {fmtname}\nround {rnd}\nstate a, y\n"
                    f"tangent v\nnext a = a\nnext y = {fn}(a)\nstep map\n")


def _domain(fn, rng):
    """A random rational in the function's domain, away from its poles."""
    if fn.startswith("exp"):
        return F(rng.randint(-8000, 8000), 1000)
    lo = -999 if fn == "log1p" else 1
    return F(rng.randint(lo, 64000), 1000)


def _cd(fn, a, da):
    """The derivative of the function at a along da, by a central
    difference at 2^-256 of the reader's 1,024-bit values (the high
    precision the six need: question 10)."""
    name = {"exp": "exp", "expm1": "expm1", "exp2": "2^", "log": "ln",
            "log1p": "log1p", "log2": "log₂"}[fn]
    return (T6(name, a + HP_EPS * da) - T6(name, a - HP_EPS * da)) \
        / (2 * HP_EPS)


def _rule_bits(fn, fmt, code, a, da, r, Lb):
    """The table's rule on one lane, in softfloat: its primal-only operand
    rounded once, then its last operation once -> (bits, the last
    operation's exact value before its rounding)."""
    one = C.round_once(fmt, sf.RND_RNE, F(1))[0]
    val = functools.partial(C.value_of, fmt)
    if fn == "exp":
        return sf.mul(fmt, r, da, code)[0], val(r) * val(da)
    if fn in ("expm1", "exp2"):
        q = sf.add(fmt, one, r, code)[0] if fn == "expm1" else \
            sf.mul(fmt, Lb, r, code)[0]
        return sf.mul(fmt, q, da, code)[0], val(q) * val(da)
    q = a if fn == "log" else sf.mul(fmt, Lb, a, code)[0] if fn == "log2" \
        else sf.add(fmt, one, a, code)[0]
    return sf.div(fmt, da, q, code)[0], val(da) / val(q)


@TL.needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_m1_each_rule_rounds_as_the_table_says(fmtname):
    """y = f(a) under every attribute, at random a in each domain and random
    tangents: the interpreter's tangent is the table's last operation - a
    product, or a division - rounded once, on operands that are the
    primal's own values, r, or a value the table rounds once first: 1 + r,
    L * r, L * a, 1 + a, L the test's own (transcend.log of 2). And that
    last operation's exact value is the derivative f'(a) da, by a central
    difference in high precision, within the roundings of its operands:
    r's and L's and the primal-only value's, 2^(1-p) each relatively, and
    none for log, whose da / a is the derivative exactly - each beside the
    difference's own error, below 2^-400 relatively. So a rule rounded
    otherwise - log's da * (1 / a), the study's example, exact in
    rationals - is red here."""
    fmt = FORMATS[fmtname]
    u = F(1, 1 << (fmt.prec - 1))           # 2^(1-p): one rounding, any way
    rng = random.Random(f"m1 rounds {fmtname}")
    for fn in TL.SIX:
        for rnd in RNDS:
            code = C.RND_BY_NAME[rnd]
            g = _one(fn, fmtname, rnd)
            Lb = C.round_once(fmt, sf.RND_RNE, _ln2(fmt, code))[0]
            lanes = [(_bits(fmt, _domain(fn, rng)),
                      _bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)))
                     for _ in range(6)]
            run = lang.run(g, [[a, 0] for a, _d in lanes], 1,
                           tangents=[[[da, 0]] for _a, da in lanes])
            for (a, da), st, tv in zip(lanes, run.states, run.tangents):
                r, t = st[1], tv[0][1]
                want, exact = _rule_bits(fn, fmt, code, a, da, r, Lb)
                assert t == want, (fn, rnd, hex(a), hex(da))
                d = _cd(fn, C.value_of(fmt, a), C.value_of(fmt, da))
                k = {"exp": 1, "expm1": 2, "exp2": 3, "log": 0, "log2": 2,
                     "log1p": 1}[fn]
                bound = k * u * F(101, 100)
                if fn == "expm1":
                    # 1 + r: r's error is relative to expm1(a), not e^a
                    vr = C.value_of(fmt, r)
                    bound = u * (abs(vr) + abs(1 + vr)) / abs(1 + vr) \
                        * F(101, 100)
                assert abs(exact - d) <= bound * abs(d) + \
                    F(1, 1 << 400) * abs(d), (fn, rnd, hex(a), hex(da))


def _run_one(g, a, da):
    r = lang.run(g, [[a, 0]], 1, tangents=[[[da, 0]]])
    return r.states[0][1], r.tangents[0][0][1], r.flags, r.primal_flags


@TL.needs_mpmath
def test_m1_the_rules_at_their_specials_and_below_the_domain():
    """Bit for bit at fp64: each logarithm below its domain - a < 0, log1p's
    a < -1 - gives the NaN r for its tangent, the select form's (question 7,
    held for all three); at its pole the division's convention, da / +-0,
    an infinity with divideByZero; at a NaN the NaN; and the exp family at
    +-infinity and at a NaN as their products give."""
    fmt = FORMATS["fp64"]

    def b(v):
        return _bits(fmt, v)
    sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
    dz, inv = sf.FLAG_DIVZERO, sf.FLAG_INVALID
    for fn, below in (("log", b(-3)), ("log2", b(F(-1, 2))),
                      ("log1p", b(-2)), ("log1p", inf ^ sign)):
        r, t, f, pf = _run_one(_one(fn), below, b(3))
        assert (r, t) == (qnan, qnan), (fn, hex(below))
        assert pf == inv and f & inv, (fn, f, pf)
    for fn, pole in (("log", 0), ("log2", 0), ("log1p", b(-1))):
        r, t, f, pf = _run_one(_one(fn), pole, b(3))
        assert (r, t, pf) == (inf ^ sign, inf, dz), (fn, hex(r), hex(t))
        assert f == dz
        r, t, _f, _pf = _run_one(_one(fn), pole, b(-3))
        assert t == inf ^ sign, fn
    for fn in ("log", "log2"):           # at -0 the division's other side
        r, t, _f, _pf = _run_one(_one(fn), sign, b(3))
        assert (r, t) == (inf ^ sign, inf ^ sign), fn
    for fn in TL.SIX:
        r, t, _f, _pf = _run_one(_one(fn), qnan, b(3))
        assert (r, t) == (qnan, qnan), fn
    # exp at +inf: r = +inf, inf * 3 = +inf; at -inf: r = +0, the product 0
    assert _run_one(_one("exp"), inf, b(3))[:3] == (inf, inf, 0)
    assert _run_one(_one("exp"), inf ^ sign, b(3))[:3] == (0, 0, 0)
    # expm1 at -inf: r = -1, (1 + -1) * 3 = +0; exp2 overflowing: r = +inf
    assert _run_one(_one("expm1"), inf ^ sign, b(3))[:3] == (b(-1), 0, 0)
    r, t, f, _pf = _run_one(_one("exp2"), b(2000), b(3))
    assert (r, t) == (inf, inf) and f & sf.FLAG_OVERFLOW
    # inside the domain, log's tangent is the division da / a, exactly
    r, t, f, _pf = _run_one(_one("log"), b(4), b(2))
    assert t == b(F(1, 2))


def _reads_tangent(g):
    """For each tangent-step node, whether it reads the tangent input,
    by the test's own walk: its per-vector operations."""
    reads = []
    for _op, args, _l in g.tangent_step.nodes:
        reads.append(any(a[0] == "t" or (a[0] == "d" and reads[int(a[1:])])
                         for a in args))
    return reads


def test_m1_each_vector_pays_one_operation_a_call():
    """After sharing what the tangent writes again, each call of the six
    costs a tangent vector one product (exp, expm1, exp2) or one division
    and its select (the logarithms), and the values its rule reads besides
    are primal-only - 1 + r, L * r, L * a, 1 + a and r == r read no tangent
    - so the compiler shares them across vectors, as the quotient's -r
    (the study, section 7)."""
    want = {"exp": (["mul"], []), "expm1": (["mul"], ["add"]),
            "exp2": (["mul"], ["mul"]),
            "log": (["div", "select"], ["cmpeq"]),
            "log2": (["div", "select"], ["mul", "cmpeq"]),
            "log1p": (["div", "select"], ["add", "cmpeq"])}
    for fn, (per_vector, primal_only) in want.items():
        g = _one(fn)
        primal, tangent = _structural(g)
        reads = _reads_tangent(g)
        own = [(op, r) for (op, i), r in zip(tangent, reads)
               if i not in primal]
        assert sorted(op for op, r in own if r) == sorted(per_vector), fn
        assert sorted(op for op, r in own if not r) == sorted(primal_only), fn
        # a tangent written again is the primal's own call, shared
        assert all(i in primal for op, i in tangent if op == fn), fn


def test_m1_unnamed_chains_of_the_six_grow_with_the_square():
    """The known limit's figures for the six (docs/LANGUAGE.md, "Known
    limits"): each rule reads r, and a logarithm's reads it three times and
    a once, so 99 calls nested unnamed write what is below them again at
    every level, as 99 nested roots do (5,148), and a logarithm's chain
    about four times as much; named by lets, each level reads the one below
    by name. At 100 nested logarithms the tangent would print 101 deep, and
    the source is refused `too-deep`, as a root's is; 100 nested exps
    print 100 deep and are not."""
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

    want = {"exp": (5049, 99), "expm1": (5148, 198), "exp2": (5148, 198),
            "log": (19998, 297), "log1p": (20097, 396), "log2": (20097, 396)}
    for fn, (unnamed, lets) in want.items():
        assert len(compile_(nested(fn)).tangent_step.nodes) == unnamed, fn
        assert len(compile_(named(fn)).tangent_step.nodes) == lets, fn
    assert len(compile_(nested("exp", 100)).tangent_step.nodes) == 5150
    with pytest.raises(lang.Refusal) as info:
        compile_(nested("log", 100))
    assert (info.value.name, info.value.line) == ("too-deep", 5)


@TL.needs_mpmath
def test_m1_the_primal_is_unchanged_by_tangents():
    """With tangents, the primal sections are the system's without them,
    by value, and a run's states and primal flags too; the rules add only
    constants the table lacks among 0, 1, -1, 2 and L - and L only where
    exp2's or log2's rule reads it."""
    rng = random.Random("m1 primal unchanged")
    for g in _m1_graphs(8, "m1 primal"):
        text = lang.render_canonical(g)
        g0 = compile_(_strip_tangent(text))
        added = {v for v, _fa, _b, _f in g.const} - \
            {v for v, _fa, _b, _f in g0.const}
        L = _ln2(g.fmt, g.rnd)
        assert added <= {F(0), F(1), F(-1), F(2), L}, added
        if L in added:
            assert {"exp2", "log2"} & set(g.op_counts("step"))
        assert _sections_by_value(g) == _sections_by_value(g0)
        states = [[_bits(g.fmt, _q(rng)) for _ in range(g.n_state)]
                  for _ in range(2)]
        tans = [[[_bits(g.fmt, _q(rng)) for _ in range(g.n_state)]
                 for _ in g.tangent] for _ in states]
        lanes = [[_bits(g.fmt, F(rng.randint(1, 9), 4)) for _ in g.lane]
                 for _ in states] if g.lane else None
        r0 = lang.run(g0, states, 2, lane_params=lanes)
        r1 = lang.run(g, states, 2, lane_params=lanes, tangents=tans)
        assert r0.states == r1.states and r0.flags == r1.primal_flags


@TL.needs_mpmath
def test_m1_l_is_ln_2_rounded_once():
    """The checker's L (constants.ln2_bits, an integer series) is
    transcend.log of 2 at every format under every attribute, and the
    const a rule adds is its exact value, rounded again to itself, exactly.
    RNE rounds ln 2 up at fp32 and fp128 and down at fp64 and fp256."""
    from cft_golden import transcend
    up = {}
    for fmtname, fmt in FORMATS.items():
        two = _bits(fmt, 2)
        for rnd in RNDS:
            code = C.RND_BY_NAME[rnd]
            want = transcend.compute(fmt, "log", two, 0, code)[0]
            assert C.ln2_bits(fmt, code) == want, (fmtname, rnd)
            g = _one("exp2", fmtname, rnd)
            L = C.value_of(fmt, want)
            assert (L, None, want, 0) in g.const
        up[fmtname] = C.ln2_bits(fmt, sf.RND_RNE) == \
            C.ln2_bits(fmt, sf.RND_RUP)
    assert up == {"fp32": True, "fp64": False, "fp128": True,
                  "fp256": False}


class _M1Plant(lang_tangent.Derivation):
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        if node.op == "log" and self.of(a[0]) is not None:
            da = self.of(a[0])
            if self.kind == "log's rule rounded otherwise":     # da * (1/a)
                return N("select", N("mul", da, N("div", self.one, R(a[0]))),
                         R(node), N("cmpeq", R(node), R(node)))
            if self.kind == "log's select form dropped":         # da / a
                return N("div", da, R(a[0]))
        return super().rule(node)


def _wrong_ln2(fmt, rnd):
    """L rounded the wrong way: the other neighbour of ln 2."""
    right = C.ln2_bits(fmt, rnd)
    lo, hi = C.ln2_bits(fmt, sf.RND_RDN), C.ln2_bits(fmt, sf.RND_RUP)
    return C.value_of(fmt, hi if right == lo else lo)


@TL.needs_mpmath
@pytest.mark.parametrize("kind", ["log's rule rounded otherwise",
                                  "log's select form dropped",
                                  "L rounded the wrong way"])
def test_m1_the_plants(kind, monkeypatch):
    """Each planted, and each red where it must be: the rule rounded
    otherwise, exact in rationals, green on the fourth check and the
    central difference's value and red on the rounding check and the rule
    table; the select form dropped green inside the domain and red below
    it; L rounded the wrong way red on the fourth check, the central
    difference and the rounding check alike."""
    if kind == "L rounded the wrong way":
        monkeypatch.setattr(lang_check.C, "ln2_value", _wrong_ln2)
    else:
        class P(_M1Plant):
            pass
        P.kind = kind
        monkeypatch.setattr(lang_check, "Derivation", P)
    rng = random.Random(f"m1 plant {kind}")
    fns = ("exp2", "log2") if kind.startswith("L ") else ("log",)
    exact = hp = bits = below = 0
    for fn in fns:
        for fmtname in ("fp32", "fp64", "fp256"):
            for rnd in ("rne", "rup", "rdn"):
                g = _one(fn, fmtname, rnd)
                exact += derivative_misses(g, rng, points=3)[1]
                hp += hp_misses(g, rng, points=2)[1]
                fmt, code = g.fmt, C.RND_BY_NAME[rnd]
                Lb = C.round_once(fmt, sf.RND_RNE, _ln2(fmt, code))[0]
                for _ in range(8):
                    a = _bits(fmt, _domain(fn, rng))
                    da = _bits(fmt, F(rng.randint(1, 4000), 1000))
                    r, t, _f, _pf = _run_one(g, a, da)
                    bits += t != _rule_bits(fn, fmt, code, a, da, r, Lb)[0]
                r, t, _f, _pf = _run_one(g, _bits(fmt, -3), _bits(fmt, 3))
                below += t != sf.qnan_bits(fmt)
    table = _tangent_line(compile_(_rule_system(
        "log(a)" if fns == ("log",) else "exp2(a)", "a")))
    right = dict(RULES)["log(a)" if fns == ("log",) else "exp2(a)"]["a"]
    if kind == "log's rule rounded otherwise":
        assert (exact, hp) == (0, 0) and bits > 0 and table != right
    elif kind == "log's select form dropped":
        assert (exact, hp, bits) == (0, 0, 0) and below > 0
    else:
        assert exact > 0 and hp > 0 and bits > 0 and table != right


# ---- the known limit, measured -----------------------------------------------------

def test_an_unnamed_product_chain_grows_with_its_square():
    names = [f"x{i}" for i in range(100)]
    chain = (f"system c\nformat fp64\nstate {', '.join(names)}\n"
             f"tangent v\nnext x0 = {' * '.join(names)}\n"
             + "".join(f"next {x} = {x}\n" for x in names[1:]) + "step map\n")
    g = compile_(chain)
    assert len(g.tangent_step.nodes) == 5049
    lets = "".join(f"let p{k} = {' * '.join(names[k * 10:k * 10 + 10])}\n"
                   for k in range(10))
    named = (f"system c\nformat fp64\nstate {', '.join(names)}\n"
             f"tangent v\n{lets}next x0 = {' * '.join(f'p{k}' for k in range(10))}\n"
             + "".join(f"next {x} = {x}\n" for x in names[1:]) + "step map\n")
    # ten lets of ten terms: 11 chains of 10, 54 tangent nodes each
    assert len(compile_(named).tangent_step.nodes) == 11 * 54


# ---- determinism and the documents --------------------------------------------------

def test_the_bytes_do_not_depend_on_the_hash_seed():
    code = ("import sys; sys.path.insert(0, sys.argv[1]);"
            "from cft_golden import lang;"
            "print(' '.join(lang.load(p).graph.digest() "
            "for p in sys.argv[2:]))")
    paths = [str(SYSTEMS / f"{n}.cftl") for n in TREFS]
    here = " ".join(tref(n).digest() for n in TREFS)
    for seed in ("0", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run([sys.executable, "-c", code, str(HERE.parent)]
                             + paths, capture_output=True, text=True,
                             env=env, check=True)
        assert out.stdout.split() == here.split()


def test_the_variational_sources_are_the_references_and_a_line():
    for base in ("lorenz63-rk4", "lorenz96-rk4"):
        for fmt in ("fp64", "fp256"):
            def code(path):
                return [ln for ln in path.read_text().splitlines()
                        if ln and not ln.startswith(";")]
            a = code(SYSTEMS / f"{base}-tangent-{fmt}.cftl")
            b = code(SYSTEMS / f"{base}-{fmt}.cftl")
            assert [ln for ln in a if ln != "tangent v"] == b
            assert a.count("tangent v") == 1


def test_the_document_shows_lorenz63s_tangent_as_rendered():
    text = DOC.read_text(encoding="utf-8")
    part = text.split("### Lorenz-63's variational equations, as the "
                      "renderers write them", 1)[1].split("\n### ", 1)[0]
    blocks = re.findall(r"```\n(.*?)```", part, re.S)
    assert len(blocks) == 5
    g = tref("lorenz63-rk4-tangent-fp64")
    canon, math = lang.render_canonical(g), lang.render_math(g)
    for block in blocks:
        assert block in canon or block in math, block[:60]
    source = text.split("`programs/systems/lorenz63-rk4-tangent-fp64.cftl`:",
                        1)[1]
    source = source.split("```\n", 2)[1]
    code = [ln for ln in (SYSTEMS / "lorenz63-rk4-tangent-fp64.cftl")
            .read_text().splitlines() if ln and not ln.startswith(";")]
    assert source.splitlines() == code
