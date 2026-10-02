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
     for op in ("min", "max", "minnum", "maxnum")]

# the table's "its tangent" column, as the document writes it
DOC_RULES = {
    "`a + b`": "`da + db`", "`a - b`": "`da - db`", "`-a`": "`-da`",
    "`a * b`": "`fma(da, b, a * db)`",
    "`fma(a, b, c)`": "`fma(da, b, fma(a, db, dc))`",
    "`abs(a)`": "`copysign(1, a) * da`",
    "`copysign(a, b)`": "`copysign(1, b) * (copysign(1, a) * da)`",
    "`min(a, b)`, `max`, `minnum`, `maxnum`": "`select(r == a, da, db)`",
    "`a < b`, `<=`, `>`, `>=`, `==`": "zero",
    "`select(c, a, b)`": "`select(c, da, db)`",
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


def _dual(op, a, tie=0, zero=1):
    """The test's own derivative: (value, derivative) pairs, the
    conventions at measure-zero points written again from the document's
    rule table - the + side of an exact zero (exact arithmetic has no
    -0), ties to the first operand. tie=1 (a tie takes the second
    operand's tangent) and zero=-1 (a zero's sign is -) are the other
    conventions, which a placed point must tell apart from the table's;
    values are the same under any of them."""
    v = [p[0] for p in a]
    d = [p[1] for p in a]
    if op == "add":
        return v[0] + v[1], d[0] + d[1]
    if op == "sub":
        return v[0] - v[1], d[0] - d[1]
    if op == "mul":
        return v[0] * v[1], d[0] * v[1] + v[0] * d[1]
    if op == "fma":
        return v[0] * v[1] + v[2], d[0] * v[1] + v[0] * d[1] + d[2]
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

    def get(r):
        k, i = r[0], int(r[1:])
        return nodes[i] if k == "n" else vals[k][i]
    for op, args, _l in sec.nodes:
        nodes.append(_dual(op, [get(a) for a in args], tie, zero))
    return [get(o)[1] for o in sec.out]


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
    half of them placed."""
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
            got = g.exact_eval(tsection, state, params, lanes,
                               tangent=tangent)
            tot += 1
            bad += got != dual_eval(g, section, state, tangent, params,
                                    lanes)
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
    assert ops == set(lang.OPS)


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
    for g in flows:
        gA = compile_(extended_source(g), "A")
        n = g.n_state
        for _ in range(2):
            state = [_q(rng) for _ in range(n)]
            tangent = [_q(rng) for _ in range(n)]
            params = [_q(rng) for _ in g.param]
            lanes = [_q(rng) for _ in g.lane]
            assert gA.exact_eval("step", state + tangent, params, lanes)[n:] \
                == g.exact_eval("tangent_step", state, params, lanes,
                                tangent=tangent)
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
            # only 0, 1 and -1 may join the table
            added = {v for v, _fa, _b, _f in g.const} - \
                {v for v, _fa, _b, _f in g0.const}
            assert added <= {F(0), F(1), F(-1)}
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
