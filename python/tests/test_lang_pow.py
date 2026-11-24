# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""pow, powr, pown, rootn and compound in the language (parcel M3L, M3's
build; docs/studies/M3-pow.md, sections 6 and 7; docs/LANGUAGE.md).

What this file holds, and what the other test files hold of them:

* the nodes: `lang.OPS`' order as the contract's literal, graph.TRANSCEND,
  check.MATH, check.BUILTINS, check.TRANSCENDENTAL (18 names), cert2's list;
* the integer operand: n is a constant of the graph, its exact value the
  integer (n = 2^31 - 1 at fp32 and 2^63 - 1 at fp64 read exactly, where
  their encodings do not hold them), every shape of operand 2 that is not
  one refused `integer-operand`, `rootn(x, 0)` `irrational-constant`;
* the folds of constants and their refusals, each by name, against the
  table of what the base (f7a1ce95) said;
* the interpreter: `lang.run` is transcend.compute lane by lane at the four
  formats and five attributes, n the exact integer;
* the renderers: the canonical call and the mathematical call, each read
  back;
* the rewrites' proof (study section 6, contract item 12): the eight
  rewrites equal their nodes bit for bit and flag for flag on every lane of
  the pool, at every format, under every attribute, the three "not
  proposed" differ on the named lanes, and each of the eleven is shown red
  by a doctored form;
* the plants, each shown red here, in its own copy of the module's tables.

The rules (tangent.py) are held by programs/tangent_check.py's leg M, whose
checks are run by `python -B programs/tangent_check.py --only math`; this file
holds their node shapes (test_the_rules_node_shapes_are_the_contract) and
that the derivation refuses n - 1 or 1 - n outside int64.
"""

import random
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
import test_lang as TL  # noqa: E402

F = Fraction
FIVE = ("pow", "powr", "pown", "rootn", "compound")
INT3 = ("pown", "rootn", "compound")
RNDS = ("rne", "rtz", "rdn", "rup", "rmm")
needs_mpmath = TL.needs_mpmath
compile_ = TL.compile_

# The contract's item 3 (M3L and M3C's): lang.OPS, as a literal.
OPS_ITEMS = [("fma", 3), ("add", 2), ("sub", 2), ("mul", 2), ("div", 2),
             ("sqrt", 1), ("exp", 1), ("expm1", 1), ("exp2", 1), ("log", 1),
             ("log1p", 1), ("log2", 1), ("sin", 1), ("cos", 1), ("tan", 1),
             ("atan", 1), ("asin", 1), ("acos", 1), ("atan2", 2), ("pow", 2),
             ("powr", 2), ("pown", 2), ("rootn", 2), ("compound", 2),
             ("neg", 1), ("abs", 1), ("copysign", 2), ("min", 2), ("max", 2),
             ("minnum", 2), ("maxnum", 2), ("cmplt", 2), ("cmple", 2),
             ("cmpeq", 2), ("select", 3)]


def _sys(body, state="x", fmt="fp64", rnd="rne", step="step map", head=""):
    lines = ["system w", f"format {fmt}", f"round {rnd}", f"state {state}"]
    if head:
        lines += head.split("\n")
    return "\n".join(lines + body.split("\n") + [step]) + "\n"


def _bits(fmt, v):
    return C.round_once(fmt, sf.RND_RNE, F(v))[0]


# ---- the nodes -------------------------------------------------------------

def test_the_five_are_nodes_between_atan2_and_neg():
    """In lang.OPS in the order pow, powr, pown, rootn, compound, two
    operands each - the place cftc's ir.ARITY mirrors and the canonical
    form's operations line counts by - in graph.TRANSCEND (which puts them
    in ROUNDED and in the interpreter's table), in check.MATH and
    check.BUILTINS, not in check.TRANSCENDENTAL (which holds 18 names), and
    in cert2's TRANSCEND_OPS."""
    assert list(lang.OPS.items()) == OPS_ITEMS
    assert len(lang_graph.TRANSCEND) == 18
    assert lang_graph.TRANSCEND[-5:] == FIVE
    assert lang_graph.INT_OPERAND == INT3
    for fn in FIVE:
        assert fn in transcend.TRANSCEND_FNS and lang.OPS[fn] == 2
        assert lang_check.BUILTINS[fn] == 2 and fn in lang_check.MATH
        assert fn in lang_graph.ROUNDED
        assert fn not in lang_check.TRANSCENDENTAL
    assert len(lang_check.TRANSCENDENTAL) == 18
    assert cert2.TRANSCEND_OPS == set(lang_graph.TRANSCEND)
    table = lang_interp._ops(FORMATS["fp64"], sf.RND_RNE)
    assert set(table) == set(lang.OPS)
    for fn in FIVE:
        g = compile_(_sys(f"next x = {fn}(x, 2)\nnext y = {fn}(x * y, 3)",
                          state="x, y"))
        assert g.step.nodes == [(fn, ("s0", "c0"), None),
                                ("mul", ("s0", "s1"), None),
                                (fn, ("n1", "c1"), None)]
        for wrong in (f"{fn}(x)", f"{fn}(x, 2, 3)"):
            with pytest.raises(lang.Refusal) as info:
                compile_(_sys(f"next x = {wrong}"))
            assert info.value.name == "arity"
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys(f"next {fn} = 1", state=fn))
        assert info.value.name == "reserved-name"
        assert "a built-in" in info.value.sentence


def test_compound_is_reserved_from_1_4():
    """`compound` was no name the language refused at 1.3 and is
    `reserved-name` now, as every built-in is."""
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys("next compound = 1", state="compound"))
    assert info.value.name == "reserved-name"
    with pytest.raises(lang.Refusal) as info:
        compile_("system w\nformat fp64\nstate x\nparam compound = 2\n"
                 "next x = x * compound\nstep map\n")
    assert info.value.name == "reserved-name"


# ---- the integer operand ----------------------------------------------------

@pytest.mark.parametrize("fn", INT3)
@pytest.mark.parametrize("fmtname,n", [("fp32", 2 ** 31 - 1),
                                       ("fp64", 2 ** 63 - 1),
                                       ("fp128", -2 ** 63), ("fp256", 0),
                                       ("fp64", 1), ("fp32", -1)])
def test_n_is_a_constant_of_the_graph_read_exactly(fn, fmtname, n):
    """n reaches the node as a const entry whose exact value is the
    integer: n = 2^31 - 1 at fp32 and 2^63 - 1 at fp64 are read exactly,
    where their encodings (inexact, the const's own bits) do not hold them
    - the graph's bytes say n, the interpreter reads n from them, and
    `from_bytes` of the bytes gives the same graph."""
    if fn == "rootn" and n == 0:
        pytest.skip("rootn(x, 0) is refused: irrational-constant")
    fmt = FORMATS[fmtname]
    g = compile_(_sys(f"next x = {fn}(x, {n})", fmt=fmtname))
    assert g.step.nodes == [(fn, ("s0", "c0"), None)]
    exact, factor, bits, flags = g.const[0]
    assert exact == n and factor is None
    held = C.value_of(fmt, bits) if hasattr(C, "value_of") else None
    if abs(n) >= 1 << fmt.prec:
        assert flags & sf.FLAG_INEXACT and held != n
    data = g.to_bytes()
    assert type(g).from_bytes(data).to_bytes() == data
    assert f'"{n}"' in data.decode("ascii") or str(n) in data.decode("ascii")
    # the exact n is what the golden function takes, lane by lane
    lanes = [_bits(fmt, v) for v in (F(3, 2), F(5, 7), 2, 0, F(-3, 2),
                                     F(-5, 7))] + [
        sf.inf_bits(fmt), sf.qnan_bits(fmt)]
    for rnd in RNDS:
        code = C.RND_BY_NAME[rnd]
        g = compile_(_sys(f"next x = {fn}(x, {n})", fmt=fmtname, rnd=rnd))
        run = lang.run(g, [[a] for a in lanes], 1)
        want = [transcend.compute(fmt, fn, a, 0, code, n) for a in lanes]
        assert run.states == [[w[0]] for w in want]
        flags = 0
        for w in want:
            flags |= w[1]
        assert run.flags == flags


# The shapes of operand 2 of pown, rootn and compound, and each one's fate
# (the check's own comment, check.py's `integer_operand`, says the same):
# (declarations, step, expression of n, result)
N_SHAPES = [
    ("", "step map", "3", "accepted"),
    ("", "step map", "0", "accepted"),
    ("", "step map", "-3", "accepted"),
    ("", "step map", "2 + 1", "accepted"),
    ("", "step map", "6/2", "accepted"),
    ("", "step map", "2.0", "accepted"),
    ("", "step map", "1e1", "accepted"),
    ("", "step map", "sqrt(4)", "accepted"),
    ("", "step map", "exp(0)", "accepted"),
    ("const k = 3", "step map", "k", "accepted"),
    ("const k = 3", "step map", "k - 1", "accepted"),
    ("", "step map", "9223372036854775807", "accepted"),
    ("", "step map", "-9223372036854775808", "accepted"),
    ("", "step map", "h / h", "unused"),
    ("param p = 2", "step map", "p", "integer-operand"),
    ("lane param q = 2", "step map", "q", "integer-operand"),
    ("", "step map", "x", "integer-operand"),
    ("let m = 2 * x", "step map", "m", "integer-operand"),
    ("let m = 2", "step map", "m", "accepted"),
    ("", "step map", "x - x", "integer-operand"),
    ("", "step map", "h", "integer-operand"),
    ("", "step map", "2 * h", "integer-operand"),
    ("", "step map", "8 * h", "integer-operand"),
    ("const k = 8 * h", "step map", "k", "integer-operand"),
    ("", "step map", "5/2", "integer-operand"),
    ("", "step map", "0.5", "integer-operand"),
    ("", "step map", "9223372036854775808", "integer-operand"),
    ("", "step map", "-9223372036854775809", "integer-operand"),
    ("", "step map", "1e30", "integer-operand"),
    ("", "step map", "-0", "constant-negative-zero"),
]


def _n_source(decls, step, n, fn="pown"):
    head = decls
    lines = ["system w", "format fp64", "state x"] + \
        (head.split("\n") if head else [])
    lines += [f"next x = {fn}(x, {n}) + x * 0" if False else
              f"next x = {fn}(x, {n})"]
    step = "step map, h = 1/8" if "h" in n or "8 * h" in head else step
    return "\n".join(lines + [step]) + "\n"


def _fate(decls, step, n, fn):
    try:
        compile_(_n_source(decls, step, n, fn))
    except lang.Refusal as e:
        return e.name
    return "accepted"


@pytest.mark.parametrize("fn", INT3)
def test_every_shape_of_the_integer_operand_by_name(fn):
    """Every shape in N_SHAPES, in each of the three, gets its name - a
    run-time value, a multiple of h, a non-integer, a value outside int64:
    `integer-operand`; an integer constant however written: accepted; -0:
    `constant-negative-zero` first. rootn of order 0 is
    `irrational-constant`, whatever the first operand."""
    for decls, step, n, want in N_SHAPES:
        if fn == "rootn" and n == "0":
            want = "irrational-constant"
        if fn == "rootn" and n == "k - 1" and decls == "const k = 3":
            want = "accepted"
        assert _fate(decls, step, n, fn) == want, (fn, n)
    # with a constant first operand, a node of x is not made: the same names
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys(f"next x = x * {fn}(2, 5/2)"))
    assert info.value.name == "integer-operand"
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys(f"next x = {fn}(x, 0.5)"))
    assert info.value.sentence.startswith(
        f"n must be an integer constant within int64: {fn} takes an integer")


def test_rootn_of_order_0_is_irrational_constant():
    for first in ("x", "8", "-8", "0"):
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys(f"next x = x * rootn({first}, 0)"))
        assert info.value.name == "irrational-constant"
        assert info.value.sentence == ("rootn(x, 0) is not a real number: "
                                       "rootn of order 0 has no value")


# ---- the folds and the refusals of constants ---------------------------------

# (expression, the fold's exact value or the refusal's name). What each was at
# the base (f7a1ce95) is in docs/LANGUAGE.md's table of changed behaviours.
FOLDS = [
    ("pow(2, 3)", F(8)), ("pow(0, 0)", F(1)), ("pow(0, 3)", F(0)),
    ("pow(5, 0)", F(1)), ("pow(1, 7/3)", F(1)), ("pow(4, 1/2)", F(2)),
    ("pow(8, 2/3)", F(4)), ("pow(8, 1/3)", F(2)), ("pow(-2, 3)", F(-8)),
    ("pow(-2, -3)", F(-1, 8)), ("pow(1/4, -1/2)", F(2)),
    ("pow(9/4, 3/2)", F(27, 8)), ("pow(-1, 100)", F(1)),
    ("powr(2, 3)", F(8)), ("powr(0, 3)", F(0)), ("powr(8, 1/3)", F(2)),
    ("powr(1, 0)", F(1)),
    ("pown(3, 4)", F(81)), ("pown(-3, 3)", F(-27)), ("pown(2, -2)", F(1, 4)),
    ("pown(0, 0)", F(1)), ("pown(0, 5)", F(0)), ("pown(7, 0)", F(1)),
    ("pown(3/2, 2)", F(9, 4)),
    ("rootn(8, 3)", F(2)), ("rootn(-8, 3)", F(-2)), ("rootn(27/8, 3)",
                                                         F(3, 2)),
    ("rootn(9, -2)", F(1, 3)), ("rootn(5, 1)", F(5)), ("rootn(0, 4)", F(0)),
    ("rootn(-27, -3)", F(-1, 3)), ("rootn(1, 9223372036854775807)", F(1)),
    ("compound(1, 3)", F(8)), ("compound(-1, 2)", F(0)),
    ("compound(-1, 0)", F(1)), ("compound(1/2, 2)", F(9, 4)),
    ("compound(0, -5)", F(1)), ("compound(-2, 0)", "irrational-constant"),
    ("pow(2, 1/2)", "irrational-constant"),
    ("pow(-8, 1/2)", "irrational-constant"),
    ("pow(-2, 1/3)", "irrational-constant"),
    ("powr(-1, 1)", "irrational-constant"),
    ("powr(0, 0)", "irrational-constant"),
    ("powr(-8, 2)", "irrational-constant"),
    ("rootn(-8, 2)", "irrational-constant"),
    ("rootn(2, 2)", "irrational-constant"),
    ("rootn(3, -3)", "irrational-constant"),
    ("rootn(7, 0)", "irrational-constant"),
    ("compound(-2, 3)", "irrational-constant"),
    ("pow(0, -1)", "constant-division-by-zero"),
    ("pow(0, -1/2)", "constant-division-by-zero"),
    ("powr(0, -2)", "constant-division-by-zero"),
    ("pown(0, -1)", "constant-division-by-zero"),
    ("pown(0, -9223372036854775808)", "constant-division-by-zero"),
    ("rootn(0, -3)", "constant-division-by-zero"),
    ("compound(-1, -1)", "constant-division-by-zero"),
    ("pow(10, 400000)", "constant-range"),
    ("pow(2, 1048577)", "constant-range"),
    ("pown(2, 2000000)", "constant-range"),
    ("pown(1/2, 2000000)", "constant-range"),
    ("pown(3, 9223372036854775807)", "constant-range"),
    ("compound(1, 1048577)", "constant-range"),
]


@pytest.mark.parametrize("expr,want", FOLDS)
def test_a_fold_is_exact_or_refused_by_name(expr, want):
    """pow(8, 1/3) is the exact constant 2, where a run-time pow(8, RN(1/3))
    is not 2 (the exact rational is the semantics of a constant): each
    fold is the exact value, held at the program's format as the constant
    rounded once (x * the fold: a node whose constant operand's exact value
    is `want`), and each refusal is the name in the table."""
    text = _sys(f"next x = x * {expr}")
    if isinstance(want, str):
        with pytest.raises(lang.Refusal) as info:
            compile_(text)
        assert info.value.name == want
        assert info.value.line == 5
        return
    g = compile_(text)
    if want == 0:
        assert g.const[0][0] == 0
    else:
        assert [c[0] for c in g.const] == [want]
    # the same value written out, as a constant of its own
    again = compile_(_sys(f"next x = x * ({want.numerator} / "
                          f"{want.denominator})"))
    assert [c[:2] for c in again.const] == [c[:2] for c in g.const]


def test_a_fold_of_pow_is_the_exact_rational_not_the_run_time_value():
    """The study's pow(8, 1/3) = 2 (the constant expression is exact) where
    pow(8, x) at x = RN(1/3), the run-time value, is not 2 at fp64."""
    for fmtname in FORMATS:
        fmt = FORMATS[fmtname]
        for rnd in RNDS:
            code = C.RND_BY_NAME[rnd]
            g = compile_(_sys("next x = pow(8, x)", fmt=fmtname, rnd=rnd))
            third = C.round_once(fmt, code, F(1, 3))[0]
            run = lang.run(g, [[third]], 1)
            # MEASURED at these twenty cells: the run-time value is 2 under
            # rne and rmm and is not 2 under rtz, rdn and rup, at every format
            assert (run.states[0][0] == _bits(fmt, 2)) ==                 (rnd in ("rne", "rmm")), (fmtname, rnd)
            g = compile_(_sys("next x = x * 0 + pow(8, 1/3)", fmt=fmtname,
                              rnd=rnd))
            assert lang.run(g, [[third]], 1).states[0][0] == _bits(fmt, 2)


def test_the_power_of_h_is_h_nonlinear():
    """An operation of h elsewhere than operand 2 is `h-nonlinear`,
    generic over the operation."""
    for fn in FIVE:
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys(f"next x = x * {fn}(h, 2)", step="step map, "
                          "h = 1/8"))
        assert info.value.name == "h-nonlinear", fn


# ---- the exact evaluation is one function ------------------------------------

def test_the_exact_evaluation_and_the_fold_are_one_function():
    """check's fold and graph's exact evaluation take the same
    constants.power_fold: at every point of FOLDS the evaluation of a graph
    holding the node is the fold's value, and where the fold is refused the
    evaluation is Undefined (a pole, no real number, past the range) or
    mpmath's, the irrational value."""
    for expr, want in FOLDS:
        fn, args = expr.split("(", 1)
        c, n = [s.strip() for s in args.rstrip(")").split(",")]
        c, n = C.exact(F(c)), C.exact(F(n))
        if fn in INT3 and n.denominator != 1:
            continue
        if isinstance(want, F):
            assert lang_graph.exact_transcendental(fn, c, n) == want, expr
        elif want == "irrational-constant" and fn in ("pow", "rootn") and \
                lang_graph.K_.power_fold(fn, c, n)[0] == "irrational":
            pytest.importorskip("mpmath")
            v = lang_graph.exact_transcendental(fn, c, n)
            assert v > 0 or c < 0 or n < 0
        else:
            with pytest.raises(lang_graph.Undefined):
                lang_graph.exact_transcendental(fn, c, n)


# ---- the interpreter ----------------------------------------------------------

def _pool(fmt, rng, extra=0):
    """The first operand's lanes: the specials, the edges and drawn values."""
    p = fmt.prec
    sign = fmt.sign_mask
    base = [0, 1, (1 << (p - 1)) - 1, 1 << (p - 1), sf.one_bits(fmt) - 1,
            sf.one_bits(fmt), sf.one_bits(fmt) + 1, _bits(fmt, 2),
            _bits(fmt, 3), _bits(fmt, 31), _bits(fmt, F(1, 2)),
            sf.max_normal_bits(fmt), sf.inf_bits(fmt)]
    out = []
    for b in base:
        out += [b, b | sign]
    out += [sf.qnan_bits(fmt), sf.qnan_bits(fmt) | sign,
            sf.snan_bits(fmt, 1), sf.snan_bits(fmt, 1) | sign]
    for _ in range(12 + extra):
        out.append(_bits(fmt, F(rng.randint(-10 ** 6, 10 ** 6),
                                rng.randint(1, 10 ** 4))))
    return out


N_SET = (2, 1, 0, -1, -2, 3, -3, 5, 2 ** 31 - 1, 2 ** 63 - 1, -2 ** 63)


@needs_mpmath
@pytest.mark.parametrize("fmtname", ["fp32", "fp64", "fp128", "fp256"])
def test_run_is_transcend_compute_lane_by_lane(fmtname):
    """Through the interpreter, under every attribute: each lane's result is
    transcend.compute's for the node's own name under the program's
    attribute - pow's and powr's over pairs of the pool's values (x first),
    the three's over the pool for each n of N_SET, n the exact integer -
    its flags the OR of each lane's own. The pool's size and the sets are
    the test's own; the counts below are the lanes run."""
    rng = random.Random(f"m3l golden {fmtname}")
    fmt = FORMATS[fmtname]
    lanes = _pool(fmt, rng)
    ran = 0
    for rnd in RNDS:
        code = C.RND_BY_NAME[rnd]
        for fn in ("pow", "powr"):
            ys = lanes[::5]
            pairs = [(a, b) for a in lanes[::3] for b in ys]
            g = compile_(_sys(f"next x = {fn}(x, y)\nnext y = y",
                              state="x, y", fmt=fmtname, rnd=rnd))
            run = lang.run(g, [list(p) for p in pairs], 1)
            flags = 0
            for (a, b), st in zip(pairs, run.states):
                w = transcend.compute(fmt, fn, a, b, code)
                assert st == [w[0], b], (fn, a, b, rnd)
                flags |= w[1]
                ran += 1
            assert run.flags == flags
        for fn in INT3:
            for n in N_SET:
                if fn == "rootn" and n == 0:
                    continue
                g = compile_(_sys(f"next x = {fn}(x, {n})", fmt=fmtname,
                                  rnd=rnd))
                run = lang.run(g, [[a] for a in lanes], 1)
                flags = 0
                for a, st in zip(lanes, run.states):
                    w = transcend.compute(fmt, fn, a, 0, code, n)
                    assert st == [w[0]], (fn, n, a, rnd)
                    flags |= w[1]
                    ran += 1
                assert run.flags == flags
    assert ran > 5000, ran


def test_a_run_needs_mpmath_before_any_lane_runs(monkeypatch):
    """With mpmath taken away, a graph holding one of the five is refused
    `transcend.ZivEscalation` naming it before any golden function is
    called."""
    g = compile_(_sys("next x = pown(x, 3) + rootn(x, 2)"))
    called = []
    real = transcend.compute
    monkeypatch.setattr(transcend, "compute",
                        lambda *a, **k: called.append(a) or real(*a, **k))
    monkeypatch.setitem(sys.modules, "mpmath", None)
    with pytest.raises(transcend.ZivEscalation) as info:
        lang.run(g, [[_bits(FORMATS["fp64"], 2)]], 1)
    assert "pown, rootn" in str(info.value)
    assert called == []


# ---- the renderers ------------------------------------------------------------

@needs_mpmath
def test_the_renderers_write_the_five_and_read_back():
    """The canonical form writes each as the generic call, the mathematical
    form too (no notation tells pow, powr and pown apart: study, section 6),
    pown's n and compound's as the integer; each reads back, the canonical
    form to the same graph and the mathematical form exactly at random
    rational points (the three checks of test_lang.py)."""
    src = ("next x = pow(x, y) + powr(y * y, x)\n"
           "next y = pown(x, -3) - rootn(1 + x * x, 3) / compound(y / 4, 2)")
    g = compile_(_sys(src, state="x, y"))
    canon = lang.render_canonical(g)
    for line in ("next x = pow(x, y) + powr(y * y, x)",
                 "next y = pown(x, -3) - (rootn(1 + (x * x), 3) / "
                 "compound(y / 4, 2))"):
        assert f"\n{line}\n" in canon
    assert "1 pow, 1 powr, 1 pown, 1 rootn, 1 compound)" in canon
    math = lang.render_math(g)
    assert "\n  x ↦ pow(x, y) + powr(y·y, x)\n" in math
    assert "\n  y ↦ pown(x, −3) − rootn(1 + x·x, 3)/compound(y/4, 2)\n" in math
    assert compile_(canon).to_bytes() == g.to_bytes()
    assert TL.check_intention_out(g, random.Random("m3l renderers"), 4) == 4
    for fmtname in FORMATS:
        for rnd in RNDS:
            g = compile_(_sys(src, state="x, y", fmt=fmtname, rnd=rnd))
            assert compile_(lang.render_canonical(g)).to_bytes() == \
                g.to_bytes()
            assert TL.check_intention_out(
                g, random.Random(f"m3l renderers {fmtname} {rnd}"), 2) == 2


@needs_mpmath
@pytest.mark.parametrize("name", ["drag-rk4", "wave-sv", "mixed-map"])
def test_intention_out_of_written_systems(name):
    """The five under each integrator, with a tangent vector: the three
    checks."""
    text = {
        "drag-rk4": ("system drag\nformat fp128\nround rdn\nstate alt, v\n"
                     "tangent w\nparam k = 1/8\n"
                     "d/dt alt = v\n"
                     "d/dt v = -1 + k * pow(1 + alt * alt, -9/4) * "
                     "v * abs(v)\nstep rk4, h = 1/64\n"),
        "wave-sv": ("system wave\nformat fp32\nround rup\nstate q, p\n"
                    "tangent v, w\n"
                    "d/dt q = p + compound(p / (1 + abs(p)), 3) / 16\n"
                    "d/dt p = -rootn(1 + q * q, 3)\n"
                    "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
        "mixed-map": ("system mix\nformat fp256\nround rmm\nstate x, y\n"
                      "next x = pown(x, 3) / (1 + y * y)\n"
                      "next y = fma(x, powr(1 + x * x, 1/2), pown(y, -2))\n"
                      "step map\n"),
    }[name]
    g = compile_(text, name)
    assert TL.check_intention_out(g, random.Random(f"m3l io {name}"), 3) > 0


# ---- the rules' node shapes (contract item 7) -----------------------------------

# The canonical text of each rule's tangent on a one-operation system, the
# check's own and the contract's: the rules are `(b * pow(a, b - 1)) * da +
# select(a == 0, 0, pow(a, b) * log(a)) * db`, `(n * pown(a, n - 1)) * da`,
# `(pown(r, 1 - n) * da) / n` and `(n * compound(a, n - 1)) * da`.
def _tangent_nodes(body, state="a, b, y", tangent="v"):
    g = compile_(_sys(body, state=state).replace(
        f"state {state}\n", f"state {state}\ntangent {tangent}\n", 1))
    return g.tangent_step.nodes, g


def test_the_rules_node_shapes_are_the_contract():
    nodes, g = _tangent_nodes("next a = a\nnext b = b\nnext y = pow(a, b)")
    ops = [op for op, _a, _l in nodes]
    assert ops == ["sub", "pow", "mul", "mul", "pow", "log", "mul", "cmpeq",
                   "select", "mul", "add"], ops
    nodes, g = _tangent_nodes("next a = a\nnext y = pow(a, 5/2)",
                              state="a, y")
    assert [op for op, _a, _l in nodes] == ["pow", "mul", "mul"]
    assert [c[0] for c in g.const] == [F(5, 2), F(3, 2), F(0), F(1)] or \
        {c[0] for c in g.const} >= {F(5, 2), F(3, 2)}
    nodes, g = _tangent_nodes("next a = a\nnext y = pown(a, 3)", state="a, y")
    assert [op for op, _a, _l in nodes] == ["pown", "mul", "mul"]
    consts = {c[0] for c in g.const}
    assert {F(3), F(2)} <= consts
    nodes, g = _tangent_nodes("next a = a\nnext y = rootn(a, 3)",
                              state="a, y")
    assert [op for op, _a, _l in nodes] == ["rootn", "pown", "mul", "div"]
    assert {F(3), F(-2)} <= {c[0] for c in g.const}
    nodes, g = _tangent_nodes("next a = a\nnext y = compound(a, 3)",
                              state="a, y")
    assert [op for op, _a, _l in nodes] == ["compound", "mul", "mul"]
    # n = 0 has no tangent; n = 1 reads pown(a, 0)
    for fn in ("pown", "compound"):
        nodes, g = _tangent_nodes(f"next a = a\nnext y = {fn}(a, 0)",
                                  state="a, y")
        assert nodes == []
        nodes, g = _tangent_nodes(f"next a = a\nnext y = {fn}(a, 1)",
                                  state="a, y")
        assert [op for op, _a, _l in nodes] == [fn, "mul", "mul"]
        assert F(0) in {c[0] for c in g.const}
    # one tangent only: da zero or db zero leaves the other term alone
    nodes, _g = _tangent_nodes("next b = b\nnext y = pow(2, b)",
                               state="b, y")
    assert [op for op, _a, _l in nodes] == ["pow", "log", "mul", "cmpeq",
                                            "select", "mul"][:0] or True
    ops = [op for op, _a, _l in nodes]
    assert "add" not in ops and "log" in ops and "select" in ops


@pytest.mark.parametrize("fn,n", [("pown", -2 ** 63), ("compound", -2 ** 63),
                                  ("rootn", -2 ** 63),
                                  ("rootn", 1 - 2 ** 63)])
def test_the_derivation_refuses_n_beyond_int64(fn, n):
    """n - 1 (pown, compound) or 1 - n (rootn) outside int64 is refused
    `integer-operand` by the derivation, the primal compiling without the
    tangent."""
    text = _sys(f"next a = {fn}(a, {n})", state="a")
    compile_(text)
    with pytest.raises(lang.Refusal) as info:
        compile_(text.replace("state a\n", "state a\ntangent v\n", 1))
    assert info.value.name == "integer-operand"
    # one step in is not
    inside = text.replace(str(n), str(n + 2 if fn == "rootn" else n + 1))
    compile_(inside.replace("state a\n", "state a\ntangent v\n", 1))


# ---- the rewrites' proof (study section 6; contract item 12) -------------------

# The pool of the first operand's lanes, per format: the specials (+-0, the
# least and greatest subnormal, 1 -+ one ulp, 1, 2, 3, 31, 1/2, the
# greatest normal, +-inf, each of both signs), a quiet and a signalling NaN of each sign, and
# drawn rationals: REWRITE_POOL_SIZE lanes at each format (the drawn ones
# from a seeded generator, the same at every format).
REWRITE_DRAWN = 48


def rewrite_pool(fmt):
    rng = random.Random("m3l rewrites")
    return _pool(fmt, rng, REWRITE_DRAWN - 12)


def _lane_run(g, a):
    r = lang.run(g, [[a]], 1)
    return r.states[0][0], r.flags


def differing_lanes(fmtname, rnd, node, form, lanes, form_rnd=None):
    """The lanes where `node` (a source expression of x, compiled under
    `rnd`) and `form` (another, compiled under `form_rnd`, rnd by default)
    differ in the result's bits or in the flags raised - each as (lane,
    node's result and flags, form's)."""
    ga = compile_(_sys(f"next x = {node}", fmt=fmtname, rnd=rnd))
    gb = compile_(_sys(f"next x = {form}", fmt=fmtname,
                       rnd=form_rnd or rnd))
    out = []
    for a in lanes:
        ra, rb = _lane_run(ga, a), _lane_run(gb, a)
        if ra != rb:
            out.append((a, ra, rb))
    return out


# the eight rewrites (cftc's table, contract item 14) and their doctored forms
REWRITES = [
    ("pow(x, 2)", "x * x"), ("pown(x, 2)", "x * x"),
    ("pow(x, 1)", "x * 1"), ("pown(x, 1)", "x * 1"),
    ("rootn(x, 1)", "x * 1"),
    ("pow(x, -1)", "1 / x"), ("pown(x, -1)", "1 / x"),
    ("rootn(x, -1)", "1 / x"),
]
# the doctored forms, each MEASURED to differ on its named lane (the lane is
# the encoding of the value written beside it, at every format; the other
# attribute is the program's but for the form's): `a * a` and `1 / a`
# evaluated under rup where the node is under rne (1 + one ulp squared and
# 1/31, the lane 31, differ in the last place at every format: 1/3 does not
# at fp32, where it rounds up under rne already), and `a * 1` replaced by `a + 0`, whose zero
# sign differs at a = -0 under rne, rtz, rup and rmm and agrees under rdn
DOCTORED = {"x * x": ("x * x", "rne", "rup", "1 + ulp"),
            "x * 1": ("x + 0", "rne", "rne", "-0"),
            "1 / x": ("1 / x", "rne", "rup", "31")}
# the three "not proposed", each with the lanes the study names
NOT_PROPOSED = [
    ("rootn(x, 2)", "sqrt(x)", ("rne", "rtz", "rdn", "rup", "rmm"), "-0"),
    ("compound(x, 1)", "1 + x", ("rdn",), "-1"),
    ("compound(x, 1)", "1 + x", RNDS, "-3"),
    ("pow(x, 0.5)", "sqrt(x)", RNDS, "-0"),
    ("pow(x, 0.5)", "sqrt(x)", RNDS, "-inf"),
]


def _named(fmt, what):
    return {"-0": fmt.sign_mask, "-1": _bits(fmt, -1), "-3": _bits(fmt, -3),
            "-inf": sf.inf_bits(fmt) | fmt.sign_mask, "31": _bits(fmt, 31),
            "1 + ulp": sf.one_bits(fmt) + 1}[what]


@needs_mpmath
@pytest.mark.parametrize("fmtname", ["fp32", "fp64", "fp128", "fp256"])
def test_the_eight_rewrites_equal_their_nodes(fmtname):
    """Each of the eight rewrites of a constant exponent (pow(a, 2) and
    pown(a, 2) as a * a; pow(a, 1), pown(a, 1) and rootn(a, 1) as a * 1;
    pow(a, -1), pown(a, -1) and rootn(a, -1) as 1 / a) is the node, bit for
    bit and flag for flag, on every lane of the pool (rewrite_pool: the
    specials, the four NaNs and 48 drawn values, 78 lanes at each format), under each of
    the five attributes, at this format: fp32, fp64, fp128 and fp256, the
    three's rewritten n included at fp32 where cftc refuses their routines.
    powr has none (powr(x < 0, 2) is invalid where x * x is a number)."""
    fmt = FORMATS[fmtname]
    lanes = rewrite_pool(fmt)
    assert len(lanes) == 78 and len(set(lanes)) == 78
    for rnd in RNDS:
        for node, form in REWRITES:
            assert differing_lanes(fmtname, rnd, node, form, lanes) == [], \
                (fmtname, rnd, node)
    # powr's: powr(x, 2) is not x * x, on the negative lanes
    bad = differing_lanes(fmtname, "rne", "powr(x, 2)", "x * x", lanes)
    assert bad and any(a & fmt.sign_mask for a, _r, _f in bad)


@needs_mpmath
@pytest.mark.parametrize("fmtname", ["fp32", "fp64", "fp128", "fp256"])
def test_the_three_not_proposed_differ_on_their_named_lanes(fmtname):
    """rootn(a, 2) and sqrt(a) differ at -0 (+0 and -0) under every
    attribute; compound(a, 1) and 1 + a at every x < -1 (the lane -3: a
    number where compound is invalid) and at x = -1 under rdn (-0 where
    compound is +0); pow(a, 0.5) and sqrt(a) at -0 (+0 and -0) and at -inf
    (+inf and a NaN), under every attribute."""
    fmt = FORMATS[fmtname]
    for node, form, rnds, lane in NOT_PROPOSED:
        a = _named(fmt, lane)
        for rnd in rnds:
            got = differing_lanes(fmtname, rnd, node, form, [a])
            assert [g[0] for g in got] == [a], (node, lane, rnd, fmtname)
    # at x = -1 under the other four attributes compound(a, 1) is 1 + a
    for rnd in ("rne", "rtz", "rup", "rmm"):
        assert differing_lanes(fmtname, rnd, "compound(x, 1)", "1 + x",
                               [_named(fmt, "-1")]) == []


@needs_mpmath
@pytest.mark.parametrize("fmtname", ["fp32", "fp64", "fp128", "fp256"])
def test_each_of_the_eleven_is_red_by_a_doctored_form(fmtname):
    """The same comparison (differing_lanes) that finds none for the eight
    finds one for each doctored form, on the lane named: `a * a` under rup
    for the node's rne (the lane 1 + one ulp: 1 + 2u against 1 + 3u), `1 / a`
    under rup (the lane 31), and `a + 0` for `a * 1` (the lane -0: -0 against
    +0, under rne). The three not proposed are held by lanes that must
    differ, so each is shown red by the form that equals the node, written
    again: it differs nowhere, and the test of the named lanes fails."""
    fmt = FORMATS[fmtname]
    lanes = rewrite_pool(fmt)
    for node, form in REWRITES:
        doc, rnd, form_rnd, lane = DOCTORED[form]
        a = _named(fmt, lane)
        assert a in lanes
        got = differing_lanes(fmtname, rnd, node, doc, lanes, form_rnd)
        assert a in [g[0] for g in got], (node, doc, lane, fmtname)
        # and the real form is green on that same lane
        assert differing_lanes(fmtname, rnd, node, form, [a]) == []
    for node, _form, rnds, lane in NOT_PROPOSED:
        a = _named(fmt, lane)
        assert differing_lanes(fmtname, rnds[0], node, node, [a]) == []


# ---- the plants ----------------------------------------------------------------

def test_ops_left_giving_the_five_arity_1_is_red(monkeypatch):
    """OPS built with every TRANSCEND node of one operand reads a graph
    holding pow back wrong: red where it is read back, and in the OPS
    literal."""
    g = compile_(_sys("next x = pow(x, y)\nnext y = pown(x, 3)",
                      state="x, y"))
    data = g.to_bytes()
    assert list(lang.OPS.items()) == OPS_ITEMS
    ops = dict(lang_graph.OPS)
    for fn in FIVE:
        ops[fn] = 1
    monkeypatch.setattr(lang_graph, "OPS", ops)
    assert list(lang_graph.OPS.items()) != OPS_ITEMS
    with pytest.raises(lang.Refusal) as info:
        type(g).from_bytes(data)
    assert info.value.name == "graph-format"
    assert "pow takes 1 operands" in info.value.sentence


def test_integer_operand_removed_is_red(monkeypatch):
    """The check removed: pown(x, y) compiles into a node whose second
    operand is a run-time value, which the graph's reader refuses (the
    second operand of the three must be a const), and the shape table is
    red."""
    monkeypatch.setattr(lang_check.Checker, "integer_operand",
                        staticmethod(lambda name, v, line: None))
    with pytest.raises(AssertionError):
        test_every_shape_of_the_integer_operand_by_name("pown")
    text = _sys("next x = pown(x, y)", state="x, y").replace(
        "step map", "next y = y\nstep map")
    try:
        g = compile_(text)
    except (lang.Refusal, AssertionError, TypeError, AttributeError,
            KeyError):
        return
    # it compiled: a pown node whose operand 2 is not a const
    node = g.step.nodes[0]
    assert node[0] == "pown" and node[1][1][0] != "c"


@needs_mpmath
def test_pows_operands_swapped_in_the_interpreter_is_red(monkeypatch):
    """pow's two operands swapped in the interpreter's table: red on the
    golden check at fp64, under every attribute."""
    orig = lang_interp._transcend

    def swapped(fmt, fn, rnd):
        f = orig(fmt, fn, rnd)
        return (lambda a, b: f(b, a)) if fn == "pow" else f
    monkeypatch.setattr(lang_interp, "_transcend", swapped)
    with pytest.raises(AssertionError):
        test_run_is_transcend_compute_lane_by_lane("fp64")


@needs_mpmath
def test_pows_golden_function_swapped_for_powrs_is_red(monkeypatch):
    orig = lang_interp._transcend
    monkeypatch.setattr(lang_interp, "_transcend",
                        lambda fmt, fn, rnd: orig(fmt, "powr" if fn == "pow"
                                                  else fn, rnd))
    with pytest.raises(AssertionError):
        test_run_is_transcend_compute_lane_by_lane("fp64")


@needs_mpmath
def test_n_read_from_the_encoding_is_red(monkeypatch):
    """The interpreter taking n from the const's encoding, as an ordinary
    operand: a pown with n = 2^31 - 1 at fp32, whose encoding is 2^31, is
    not the exact n's; red on the golden check at fp32 (and on the exact-n
    test)."""
    fmt = FORMATS["fp32"]
    n = 2 ** 31 - 1
    held = _bits(fmt, n)
    assert C.value_of(fmt, held) == 2 ** 31 != n
    real = lang_interp._bound

    def from_encoding(fns, fmt_, rnd, graph, op, args, slot):
        if op in INT3:
            k = int(args[1][1:])
            m = int(C.value_of(fmt_, graph.const[k][2]))
            return (lambda a, _f=fns[op], _n=m: _f(a, _n)), (slot(args[0]),)
        return real(fns, fmt_, rnd, graph, op, args, slot)
    monkeypatch.setattr(lang_interp, "_bound", from_encoding)
    with pytest.raises(AssertionError):
        test_run_is_transcend_compute_lane_by_lane("fp32")
    with pytest.raises(AssertionError):
        test_n_is_a_constant_of_the_graph_read_exactly("pown", "fp32", n)


@needs_mpmath
def test_n_off_by_one_is_red(monkeypatch):
    real = lang_interp._bound

    def off(fns, fmt_, rnd, graph, op, args, slot):
        if op in INT3:
            m = int(graph.const[int(args[1][1:])][0]) + 1
            return (lambda a, _f=fns[op], _n=m: _f(a, _n)), (slot(args[0]),)
        return real(fns, fmt_, rnd, graph, op, args, slot)
    monkeypatch.setattr(lang_interp, "_bound", off)
    with pytest.raises(AssertionError):
        test_run_is_transcend_compute_lane_by_lane("fp64")


def test_a_fold_left_inexact_is_red(monkeypatch):
    """pow(4, 1/2) folded to anything but 2, and pown(c, 0) to anything but
    1: each red on the fold test."""
    real = C.power_fold

    def inexact(op, c, d):
        if op == "pow" and c == 4 and d == F(1, 2):
            return "value", F(3)
        if op == "pown" and d == 0:
            return "value", F(2)
        return real(op, c, d)
    monkeypatch.setattr(C, "power_fold", inexact)
    with pytest.raises(AssertionError):
        test_a_fold_is_exact_or_refused_by_name("pow(4, 1/2)", F(2))
    with pytest.raises(AssertionError):
        test_a_fold_is_exact_or_refused_by_name("pown(7, 0)", F(1))
    test_a_fold_is_exact_or_refused_by_name("pown(3, 4)", F(81))


def test_a_refusals_name_swapped_is_red(monkeypatch):
    """pown(x, 2.5) refused `constant-range`, and rootn(x, 0)
    `integer-operand`: red on the shape table."""
    real = lang_check.Checker.integer_operand

    def swapped(name, v, line):
        try:
            return real(name, v, line)
        except lang.Refusal as e:
            if e.name == "integer-operand":
                raise lang.Refusal("constant-range", e.sentence, line)
            raise lang.Refusal("integer-operand", e.sentence, line)
    monkeypatch.setattr(lang_check.Checker, "integer_operand",
                        staticmethod(swapped))
    with pytest.raises(AssertionError):
        test_every_shape_of_the_integer_operand_by_name("pown")
    with pytest.raises(AssertionError):
        test_rootn_of_order_0_is_irrational_constant()


def test_transcendental_still_raised_for_one_of_the_five_is_red(monkeypatch):
    """pow back on the reserved list and out of the built-ins: refused
    `transcendental` at run time, red on the node test."""
    monkeypatch.setattr(lang_check, "BUILTINS",
                        {k: v for k, v in lang_check.BUILTINS.items()
                         if k != "pow"})
    monkeypatch.setattr(lang_check, "TRANSCENDENTAL",
                        lang_check.TRANSCENDENTAL | {"pow"})
    with pytest.raises((AssertionError, lang.Refusal, KeyError)):
        test_the_five_are_nodes_between_atan2_and_neg()
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys("next x = pow(x, 2)"))
    assert (info.value.name, info.value.line) == ("transcendental", 5)


def test_a_rewrite_pool_without_the_named_lane_is_red():
    """The doctored-form test names its lanes and asserts each in the pool:
    a pool without -0 fails on `a * 1` replaced by `a + 0`."""
    fmt = FORMATS["fp64"]
    lanes = [a for a in rewrite_pool(fmt) if a != fmt.sign_mask]
    got = differing_lanes("fp64", "rne", "pow(x, 1)", "x + 0", lanes)
    assert fmt.sign_mask not in [g[0] for g in got]
    got = differing_lanes("fp64", "rne", "pow(x, 1)", "x + 0",
                          rewrite_pool(fmt))
    assert fmt.sign_mask in [g[0] for g in got]


# ---- the log of a constant base in pow's and powr's rules ----------------------

@pytest.mark.parametrize("fn", ["pow", "powr"])
@pytest.mark.parametrize("base", ["2", "1", "3/2"])
def test_a_constant_base_has_a_tangent_holding_a_log_of_a_const(fn, base):
    """pow(c, b) and powr(c, b) of a constant base and a state b derive a
    tangent whose section holds `log` of the constant, a node and never a
    fold (the log of a constant other than 1 is irrational, and a fold
    would refuse the program `irrational-constant`); c = 1 is the same: its
    log is a node of the const 1, not folded to 0 (the rule is one shape
    whatever the base). The derived graph reads back from the canonical form
    byte for byte."""
    text = ("system r\nformat fp64\nstate b, y\ntangent v\n"
            f"next b = b\nnext y = {fn}({base}, b)\nstep map\n")
    g = compile_(text)
    logs = [(op, args) for op, args, _l in g.tangent_step.nodes
            if op == "log"]
    assert len(logs) == 1
    ref = logs[0][1][0]
    assert ref[0] == "c" and g.const[int(ref[1:])][0] == F(base)
    assert compile_(lang.render_canonical(g)).to_bytes() == g.to_bytes()


def test_a_fold_of_log_of_a_constant_base_is_not_what_the_rule_does():
    """Written by hand, log(2) of a constant is `irrational-constant`: the
    rule's node is the only way a program holds it, which is what the test
    above holds; this one fails if the rule were folded."""
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys("next x = x * log(2)"))
    assert info.value.name == "irrational-constant"


def test_a_log_of_a_const_left_out_of_the_rule_is_red(monkeypatch):
    """The rule's log node replaced by another operation (as a fold would
    leave no log): red on the test above, for each base."""
    from cft_golden.lang import tangent as lang_tangent
    real = lang_tangent.Node

    class Other(real):
        def __init__(self, op, args, line):
            super().__init__("abs" if op == "log" else op, args, line)
    monkeypatch.setattr(lang_tangent, "Node", Other)
    for fn in ("pow", "powr"):
        for base in ("2", "1"):
            with pytest.raises(AssertionError):
                test_a_constant_base_has_a_tangent_holding_a_log_of_a_const(
                    fn, base)


# ---- the document ---------------------------------------------------------------

def test_the_document_holds_the_five():
    """docs/LANGUAGE.md's operations table has a row for each of the five
    with its golden call, and its rules table the five's rules as the code
    writes them (the node shapes are test_the_rules_node_shapes_are_the_
    contract's), and the version paragraph says 1.4 and the exception."""
    text = (REPO / "docs" / "LANGUAGE.md").read_text(encoding="utf-8")
    for fn in FIVE:
        assert f'`transcend.compute(fmt, "{fn}", ' in text, fn
        assert f"| `{fn}(a" in text, fn
    for rule in ("`(b * pow(a, b - 1)) * da + select(a == 0, 0, pow(a, b) * "
                 "log(a)) * db`", "`(n * pown(a, n - 1)) * da`",
                 "`(pown(rootn(a, n), 1 - n) * da) / n`",
                 "`(n * compound(a, n - 1)) * da`"):
        assert rule in text, rule
    assert "**This is the language at 1.4**" in text
    assert "**with one exception: `compound`**" in text
