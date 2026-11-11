# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""atan, asin, acos and atan2 in the language (parcel M4L, M4's build;
docs/studies/M4-invtrig.md, sections 6 and 7; docs/LANGUAGE.md).

Golden-first, as sin, cos and tan were (test_lang_trig.py): the nodes, the
folds and refusals, the exact evaluation, the two renderers, and the four
derivative rules. Here:

  the nodes        atan, asin, acos and atan2 directly after tan and before
                   neg in lang.OPS, in that order (the place is byte-
                   relevant: the canonical form's "; operations:" line
                   counts nodes in OPS's order, and cftc's ir.ARITY mirrors
                   it); atan2 the language's first node of two operands, y
                   first; `transcendental` still refused for the other 22
  the golden       a lane's result is transcend.compute's for the node's
  functions        own name under the program's attribute, bits and flags;
                   atan2's with its operands as the node holds them
  the folds        atan(0), asin(0), acos(1) and atan2(0, c) for a constant
                   c >= 0 are 0, of constants exactly so only; every other
                   constant is refused `irrational-constant` with its
                   reason, asin and acos outside [-1, 1] as "not a real
                   number"; a function of h is `h-nonlinear`; and no
                   constant division by zero
  the exact        exact at the folds' points, mpmath's at 1,024 bits
  evaluation       elsewhere, the reader of lang_mathform.py taking the same
                   value; Undefined for asin and acos outside [-1, 1]
  the renderers    arctan(x), arcsin(x), arccos(x) and atan2(y, x) in the
                   mathematical form, the generic call in the canonical
                   one, each read back
  the rules        the four rules (one division a vector; atan2's three
                   cases), each rendered on a one-operation system, their
                   node shapes (the contract between parcels M4L and M4C);
                   the derivative by exact dual numbers and by a central
                   difference in high precision, the step and tolerance
                   named where asin's and acos's roots forbid 2^-256; each
                   rule's rounding bit for bit at every format and
                   attribute; the specials
  the plants       each rule made wrong, each rounded otherwise, atan2's
                   operands swapped in the interpreter, atan's golden
                   function swapped for asin's, a fold left inexact, a
                   refusal's name swapped
  mpmath           needed only by a graph holding one of the thirteen

The compiled forms are parcel M4C's; on a branch with this file alone,
cftc does not carry the four.
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
FOUR = ("atan", "asin", "acos", "atan2")
ONE = ("atan", "asin", "acos")
RNDS = ("rne", "rtz", "rdn", "rup", "rmm")
DOC = REPO / "docs" / "LANGUAGE.md"
needs_mpmath = TL.needs_mpmath
compile_ = TL.compile_
_sys1 = TL._sys1
SYSTEMS = REPO / "programs" / "systems"

# the step of the central differences: 2^-256 within 2^-300 where the exact
# evaluation holds no root (atan, atan2), and 2^-64 within 2^-100 where the
# rule's own square root, rounded down to 2^-256 by the exact evaluation,
# would be measured instead (asin, acos)
EPS_HI, TOL_HI = F(1, 1 << 256), F(1, 1 << 300)
EPS_ROOT, TOL_ROOT = F(1, 1 << 64), F(1, 1 << 100)


# ---- the nodes -------------------------------------------------------------

# The contract's item 3, the order of lang.OPS, as a literal.
OPS_ITEMS = [("fma", 3), ("add", 2), ("sub", 2), ("mul", 2), ("div", 2),
             ("sqrt", 1), ("exp", 1), ("expm1", 1), ("exp2", 1), ("log", 1),
             ("log1p", 1), ("log2", 1), ("sin", 1), ("cos", 1), ("tan", 1),
             ("atan", 1), ("asin", 1), ("acos", 1), ("atan2", 2), ("neg", 1),
             ("abs", 1), ("copysign", 2), ("min", 2), ("max", 2),
             ("minnum", 2), ("maxnum", 2), ("cmplt", 2), ("cmple", 2),
             ("cmpeq", 2), ("select", 3)]


def test_the_four_are_nodes_between_tan_and_neg():
    """Named as transcend.py names them, directly after tan and before neg
    in lang.OPS in the order atan, asin, acos, atan2, atan2 of two operands
    and the other three of one - the place cftc's ir.ARITY mirrors and the
    canonical form's operations line counts by - and in graph.TRANSCEND,
    which puts them in ROUNDED and in the interpreter's table."""
    assert list(lang.OPS.items()) == OPS_ITEMS
    assert lang_graph.TRANSCEND == ("exp", "expm1", "exp2", "log", "log1p",
                                    "log2", "sin", "cos", "tan", "atan",
                                    "asin", "acos", "atan2")
    for fn in FOUR:
        arity = 2 if fn == "atan2" else 1
        assert fn in transcend.TRANSCEND_FNS
        assert transcend.TRANSCEND_ARITY[fn] == arity
        assert lang.OPS[fn] == arity and lang_check.BUILTINS[fn] == arity
        assert fn in lang_graph.ROUNDED and fn in lang_check.MATH
    assert lang_graph.ROUNDED >= set(lang_graph.TRANSCEND)
    table = lang_interp._ops(FORMATS["fp64"], sf.RND_RNE)
    assert set(table) == set(lang.OPS)
    assert not set(FOUR) & lang_check.TRANSCENDENTAL
    for fn in FOUR:
        n = lang.OPS[fn]
        names = ", ".join("xy"[:n])
        g = compile_(_sys1(f"next x = {fn}({names})\nnext y = {fn}(x * y"
                           f"{', y' if n == 2 else ''})"))
        if n == 1:
            assert g.step.nodes == [(fn, ("s0",), None),
                                    ("mul", ("s0", "s1"), None),
                                    (fn, ("n1",), None)]
        else:
            assert g.step.nodes == [(fn, ("s0", "s1"), None),
                                    ("mul", ("s0", "s1"), None),
                                    (fn, ("n1", "s1"), None)]
        wrong = [f"{fn}()", f"{fn}(x, y, x)"] + \
            ([f"{fn}(x)"] if n == 2 else [f"{fn}(x, y)"])
        for call in wrong:
            with pytest.raises(lang.Refusal) as info:
                compile_(_sys1(f"next x = {call}\nnext y = y"))
            assert (info.value.name, info.value.line) == ("arity", 5)
            given = call.count(",") + (call != f"{fn}()")
            assert info.value.sentence == (
                f"{fn} takes {n} argument{'s' if n > 1 else ''}, and "
                f"{given} {'is' if given == 1 else 'are'} given"), \
                info.value.sentence
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next {fn} = 1", state=fn))
        assert info.value.name == "reserved-name"
        assert "a built-in" in info.value.sentence
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next x = x * {fn}", state="x"))
        assert info.value.name == "syntax"


def test_the_graph_bytes_write_the_four():
    """The IR form of a node is [op, [ref, ...], label or null], as every
    node's is - atan2's two refs y first - a graph without the four writes
    what it wrote before, and the canonical form's operations line counts
    the nodes in OPS's order, after tan's and before neg's."""
    g = compile_(_sys1("next x = atan2(y, x) + asin(x)\n"
                       "next y = -(atan(x) * acos(y))"))
    data = g.to_bytes().decode("ascii")
    for line in ('["atan2",["s1","s0"],null]', '["asin",["s0"],null]',
                 '["atan",["s0"],null]', '["acos",["s1"],null]'):
        assert line in data
    nodes = json.loads(data.split('"step":', 1)[1].rsplit("}", 1)[0]
                       .split('"tangent"')[0].rstrip(",\n"))["nodes"]
    assert [n[0] for n in nodes] == ["atan2", "asin", "add", "atan", "acos",
                                     "mul", "neg"]
    canon = lang.render_canonical(g)
    assert ("; operations: a step 7 (1 add, 1 mul, 1 atan, 1 asin, 1 acos, "
            "1 atan2, 1 neg)") in canon
    plain = compile_(_sys1("next x = exp(y) + tan(x)\nnext y = -x"))
    assert plain.to_bytes().decode("ascii").count('"atan') == 0
    assert "(1 add, 1 exp, 1 tan, 1 neg)" in lang.render_canonical(plain)
    assert compile_(canon).to_bytes() == g.to_bytes()


def test_a_graph_holding_atan2_is_read_back_with_two_operands():
    """The graph's reader holds every node to OPS' operand count: the
    bytes of an atan2 graph read back to the same bytes and to a graph with
    no problem, and the same bytes with atan2 given one ref, or three, are
    refused `graph-format`, the sentence naming the operand count."""
    g = compile_(_sys1("next x = atan2(x, y)\nnext y = y"))
    data = g.to_bytes().decode("ascii")
    assert '["atan2",["s0","s1"],null]' in data
    back = type(g).from_bytes(data.encode("ascii"))
    assert back.to_bytes() == g.to_bytes() and back.problem() is None
    for bad in ('["atan2",["s0"],null]', '["atan2",["s0","s1","s0"],null]'):
        broken = data.replace('["atan2",["s0","s1"],null]', bad)
        assert broken != data
        with pytest.raises(lang.Refusal) as info:
            type(g).from_bytes(broken.encode("ascii"))
        assert info.value.name == "graph-format"
        assert info.value.sentence.endswith(
            ": step node 0: atan2 takes 2 operands"), info.value.sentence


def test_transcendental_is_still_raised_for_the_other_22():
    """atan, asin, acos and atan2 left the reserved list with M4's build;
    the other 22 stay on it, refused `transcendental` at run time and
    `irrational-constant` of a constant, for the rounds after M4."""
    rest = {"exp10", "log10", "pow", "pown", "powr", "rootn", "hypot",
            "sinpi", "cospi", "tanpi", "asinpi", "acospi", "atanpi",
            "atan2pi", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh",
            "cbrt", "rsqrt"}
    assert len(rest) == 22 and set(lang_check.TRANSCENDENTAL) == rest
    for name in sorted(rest):
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next x = {name}(x)", state="x"))
        assert (info.value.name, info.value.line) == ("transcendental", 5)
        with pytest.raises(lang.Refusal) as info:
            compile_(_sys1(f"next x = x * {name}(1)", state="x"))
        assert info.value.name == "irrational-constant"


# ---- the golden functions ---------------------------------------------------

def _bits(fmt, v):
    return C.round_once(fmt, sf.RND_RNE, F(v))[0]


def unary_lanes(fmt, fn, rng, extra=6):
    """Encodings for atan, asin or acos: the specials, the edges of the
    domain [-1, 1] and just outside it, and random ones inside, across a
    few binades, and (atan only) far outside."""
    named = [0, fmt.sign_mask, sf.inf_bits(fmt), sf.inf_bits(fmt, 1),
             sf.qnan_bits(fmt), sf.snan_bits(fmt, 1), 1,
             fmt.sign_mask | 1, sf.max_normal_bits(fmt),
             sf.max_normal_bits(fmt) ^ fmt.sign_mask]
    named += [_bits(fmt, v) for v in (1, -1, 2, F(1, 2), -2, F(-1, 2),
                                      F(3, 4), F(-7, 8), 100, -100)]
    out = list(named)
    while len(out) < len(named) + extra:
        if fn == "atan":
            out.append(_bits(fmt, F(rng.randint(-1 << 40, 1 << 40),
                                    1 << 38)))
        else:
            out.append(_bits(fmt, F(rng.randint(-1 << 30, 1 << 30),
                                    1 << 30)))
    return out


def pair_lanes(fmt, rng, extra=12):
    """(y, x) pairs for atan2: every pair of the specials and a few
    ordinary values (the axes, the origin, the infinities, the NaNs, both
    signs of zero among them), and random pairs across the plane."""
    vals = [0, fmt.sign_mask, sf.inf_bits(fmt), sf.inf_bits(fmt, 1),
            sf.qnan_bits(fmt), sf.snan_bits(fmt, 1), 1,
            sf.max_normal_bits(fmt)]
    vals += [_bits(fmt, v) for v in (1, -1, 3, F(-3, 2), 1000)]
    pairs = [(y, x) for y in vals for x in vals]
    for _ in range(extra):
        pairs.append(tuple(_bits(fmt, F(rng.randint(-1 << 30, 1 << 30),
                                        rng.randint(1, 1 << 20)))
                           for _ in range(2)))
    return pairs


def golden_misses(fn, fmtname, rnd, rng, extra=6):
    """(lanes, lanes where the interpreter's result is not
    transcend.compute's bits, whether the run's FLAGS are the lanes' OR),
    for y = fn(x) or, for atan2, x = atan2(x, y) over (y, x) pairs held in
    the state as (x, y) = (y_in, x_in) - the node's first operand is the
    state's first component."""
    fmt = FORMATS[fmtname]
    code = C.RND_BY_NAME[rnd]
    if fn == "atan2":
        pairs = pair_lanes(fmt, rng, extra)
        g = compile_(_sys1("next x = atan2(x, y)\nnext y = y", fmt=fmtname,
                           rnd=rnd))
        run = lang.run(g, [list(p) for p in pairs], 1)
        union = bad = 0
        for (a, b), out in zip(pairs, run.states):
            bits, flags = transcend.compute(fmt, "atan2", a, b, code)
            bad += out != [bits, b]
            union |= flags
        return len(pairs), bad, run.flags == union
    lanes = unary_lanes(fmt, fn, rng, extra)
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
    the specials, the edges of the domain and ordinary arguments among
    the lanes; atan2's over every pair of the specials (the axes and the
    origin, both signs of zero, the infinities and the NaNs) and random
    pairs, y first."""
    rng = random.Random(f"m4 golden {fmtname}")
    for fn in FOUR:
        for rnd in RNDS:
            n, bad, flags_ok = golden_misses(fn, fmtname, rnd, rng)
            assert n == (175 if fn == "atan2" else 26), (fn, n)
            assert bad == 0 and flags_ok, (fn, rnd)
    fmt = FORMATS[fmtname]
    # a lane at +-0, bit for bit: atan(+-0) = +-0 and asin(+-0) = +-0 (the
    # argument's sign), acos(0) = pi/2 rounded, whatever its sign
    for fn in ("atan", "asin"):
        g = compile_(_sys1(f"next x = {fn}(x)", state="x", fmt=fmtname))
        run = lang.run(g, [[0], [fmt.sign_mask]], 1)
        assert run.states == [[0], [fmt.sign_mask]] and run.flags == 0
    g = compile_(_sys1("next x = acos(x)", state="x", fmt=fmtname))
    run = lang.run(g, [[_bits(fmt, 1)], [_bits(fmt, 2)]], 1)
    assert run.states == [[0], [sf.qnan_bits(fmt)]]
    assert run.flags == sf.FLAG_INVALID
    # atan2's axes: y = +-0 against x = +1 is +-0; against x = -1 it is
    # +-pi, rounded; y = 1 against x = 0 is pi/2, rounded
    g = compile_(_sys1("next x = atan2(x, y)\nnext y = y", fmt=fmtname))
    one, mone = _bits(fmt, 1), _bits(fmt, -1)
    run = lang.run(g, [[0, one], [fmt.sign_mask, one], [0, 0],
                       [fmt.sign_mask, fmt.sign_mask]], 1)
    assert [s[0] for s in run.states][:3] == [0, fmt.sign_mask, 0]
    run = lang.run(g, [[0, mone], [fmt.sign_mask, mone]], 1)
    assert run.states[0][0] == transcend.compute(fmt, "atan2", 0, mone,
                                                 0)[0]
    assert run.states[1][0] == run.states[0][0] | fmt.sign_mask


# ---- the folds and the refusals --------------------------------------------

# A fold is the exact rational value, rounded once where it meets the run.
FOLDS = ["atan(0)", "asin(0)", "acos(1)", "atan2(0, 1)", "atan2(0, 0)",
         "atan2(0, 5)", "atan2(0, 1/3)", "atan(1 - 1)", "asin(2 * 0)",
         "acos(2 - 1)", "atan2(1 - 1, 3)", "atan2(0, 1 - 1)",
         "atan(sin(0))", "acos(cos(0))", "asin(atan(0))",
         "atan2(atan(0), acos(1))", "atan2(0 / 3, 1e300)",
         "atan2(0, 1e-300)"]


@pytest.mark.parametrize("expr", FOLDS)
def test_the_four_fold_at_their_zeros(expr):
    """atan(0), asin(0), acos(1) and atan2(0, c) for a constant c >= 0
    (c = 0 included) are the constant 0, exactly, rounded once at every
    format under every attribute, in a const and a default too (Logan's
    answer 8 to the M4 study); the constant is a bank constant of the
    node it meets, never a call."""
    for fmtname in FORMATS:
        fmt = FORMATS[fmtname]
        for rnd in RNDS:
            g = compile_(_sys1(f"next x = x + {expr}", state="x",
                               fmt=fmtname, rnd=rnd))
            assert g.step.nodes == [("add", ("s0", "c0"), None)]
            assert g.const == [(F(0), None)
                               + C.round_once(fmt, C.RND_BY_NAME[rnd],
                                              F(0))]
    g = compile_(_sys1(f"const k = {expr}\nparam p = {expr} + 1\n"
                       f"next x = x + k * p", state="x"))
    assert g.param[0][1] == 1


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_a_fold_is_the_run_time_value_at_its_point(fmtname):
    """The folded constant is what the node computes at its point, bits
    and flags (no flag: each is exact there): the language folds only
    where the answer is the golden function's own, at every attribute."""
    fmt = FORMATS[fmtname]
    one, five = _bits(fmt, 1), _bits(fmt, 5)
    for rnd in RNDS:
        code = C.RND_BY_NAME[rnd]
        for fn, args in (("atan", (0, 0)), ("asin", (0, 0)),
                         ("acos", (one, 0)), ("atan2", (0, one)),
                         ("atan2", (0, 0)), ("atan2", (0, five))):
            assert transcend.compute(fmt, fn, *args, code) == (0, 0), \
                (fn, args, rnd)


def test_the_exact_evaluation_is_exact_at_the_folds_points():
    """The step graph's exact evaluation (graph.exact_transcendental) is
    the rational the fold is where the fold applies - 0 for atan(0),
    asin(0), acos(1) and atan2(0, c) for c >= 0, c = 0 included - and
    Undefined for asin and acos outside [-1, 1]; atan2(0, c) for c < 0 is
    not 0 (it is pi, mpmath's)."""
    ex = lang_graph.exact_transcendental
    assert ex("atan", F(0)) == ex("asin", F(0)) == ex("acos", F(1)) == 0
    for c in (F(0), F(1), F(5), F(1, 3), F(10) ** 300, F(1, 10 ** 300)):
        assert ex("atan2", F(0), c) == 0 and isinstance(
            ex("atan2", F(0), c), F)
    for fn in ("asin", "acos"):
        for v in (F(2), F(-2), F(1) + F(1, 10 ** 30), F(-10) ** 20):
            with pytest.raises(lang_graph.Undefined):
                ex(fn, v)
    with pytest.raises(lang_graph.Undefined):
        lang_graph.exact_transcendental("asin", F(3, 2))


# Every refusal of the four, by name, with the name the same source met at
# 21b98aec, before M4's build (each compiled there, under a copy of that
# commit's python/, and here): (body, step, name, line, the name before).
# A body with a y is compiled with `next y = y` added when it has no
# equation of y, and state x, y; otherwise state x.
M4_REFUSALS = [
    ("next x = x * atan(1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(-1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(1/2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(1e30)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(1e-300)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(0.5)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(-3)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(-1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(1/2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(0)", "step map", "accepted", 0, "irrational-constant"),
    ("next x = x * asin(0.5)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(-1/3)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(1)", "step map", "accepted", 0, "irrational-constant"),
    ("next x = x * acos(-1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(1/2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(0)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(0.5)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(-1/3)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(-3/2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(-1e10)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * asin(1.0000001)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(-3/2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(-1e10)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * acos(1.0000001)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2(1, 1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2(0, -1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2(1, 0)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2(-1, 2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2(0, 1/3)", "step map",
     "accepted", 0, "irrational-constant"),
    ("next x = x * atan2(0, 5)", "step map",
     "accepted", 0, "irrational-constant"),
    ("next x = x * atan2(0, 0)", "step map",
     "accepted", 0, "irrational-constant"),
    ("next x = x * atan2(0 * 3, 2)", "step map",
     "accepted", 0, "irrational-constant"),
    ("next x = x * atan2(0, 1 - 1)", "step map",
     "accepted", 0, "irrational-constant"),
    ("next x = x * atan2(1/3, 1/2)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2(1e30, 1e-30)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2(0, -1e-300)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan(h)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * asin(h)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * acos(2 * h)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * atan2(h, 1)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * atan2(1, h)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * atan2(h, h)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * atan2(0, h)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * atan2(h * h, 1)", "step map, h = 1/8",
     "h-nonlinear", 5, "irrational-constant"),
    ("next x = x * atan(0 * h)", "step map, h = 1/8",
     "unused", 6, "irrational-constant"),
    ("next x = x * asin(0 * h)", "step map, h = 1/8",
     "unused", 6, "irrational-constant"),
    ("next x = x * acos(1 + 0 * h)", "step map, h = 1/8",
     "unused", 6, "irrational-constant"),
    ("next x = x * atan2(0 * h, 1)", "step map, h = 1/8",
     "unused", 6, "irrational-constant"),
    ("next x = x * atan2(0, 1 + 0 * h)", "step map, h = 1/8",
     "unused", 6, "irrational-constant"),
    ("d/dt x = x * atan(h)", "step euler, h = 1/8", "h-scope", 5, "h-scope"),
    ("next x = atan(x, x)", "step map", "arity", 5, "transcendental"),
    ("next x = atan()", "step map", "arity", 5, "transcendental"),
    ("next x = asin(x, x)", "step map", "arity", 5, "transcendental"),
    ("next x = acos()", "step map", "arity", 5, "transcendental"),
    ("next x = atan2(x)", "step map", "arity", 5, "transcendental"),
    ("next x = atan2()", "step map", "arity", 5, "transcendental"),
    ("next x = atan2(x, x, x)", "step map", "arity", 5, "transcendental"),
    ("next x = x * atan2(-0, 1)", "step map",
     "constant-negative-zero", 5, "constant-negative-zero"),
    ("next x = x * atan2(0, -0)", "step map",
     "constant-negative-zero", 5, "constant-negative-zero"),
    ("next x = x * atan2(1/0, 1)", "step map",
     "constant-division-by-zero", 5, "constant-division-by-zero"),
    ("next x = x * atan2(1, 1/0)", "step map",
     "constant-division-by-zero", 5, "constant-division-by-zero"),
    ("next x = x * atan(inf)", "step map",
     "constant-infinity", 5, "constant-infinity"),
    ("next x = x * atan(nan)", "step map", "constant-nan", 5, "constant-nan"),
    ("next x = x * asin(-0)", "step map",
     "constant-negative-zero", 5, "constant-negative-zero"),
    ("next x = x * atan(1/0)", "step map",
     "constant-division-by-zero", 5, "constant-division-by-zero"),
    ("next x = x * atan2(inf, 1)", "step map",
     "constant-infinity", 5, "constant-infinity"),
    ("next x = x * acos(nan)", "step map", "constant-nan", 5, "constant-nan"),
    ("next x = x * atan", "step map", "syntax", 5, "syntax"),
    ("next x = x * atan2", "step map", "syntax", 5, "syntax"),
    ("next x = atan(x)", "step map", "accepted", 0, "transcendental"),
    ("next x = asin(x)", "step map", "accepted", 0, "transcendental"),
    ("next x = acos(x)", "step map", "accepted", 0, "transcendental"),
    ("next x = atan2(x, y)", "step map", "accepted", 0, "transcendental"),
    ("next x = atan2(x, 1)", "step map", "accepted", 0, "transcendental"),
    ("next x = atan2(1, x)", "step map", "accepted", 0, "transcendental"),
    ("next x = atan2(0, x)", "step map", "accepted", 0, "transcendental"),
    ("next x = atan2(x, 0)", "step map", "accepted", 0, "transcendental"),
    ("next x = atan2(x, 0 * 5)", "step map", "accepted", 0, "transcendental"),
    ("next x = atan(x) + asin(y) * acos(x) - atan2(y, x)", "step map",
     "accepted", 0, "transcendental"),
    ("next x = asinpi(x)", "step map", "transcendental", 5, "transcendental"),
    ("next x = acospi(x)", "step map", "transcendental", 5, "transcendental"),
    ("next x = atanpi(x)", "step map", "transcendental", 5, "transcendental"),
    ("next x = atan2pi(x, y)", "step map",
     "transcendental", 5, "transcendental"),
    ("next x = sinh(x)", "step map", "transcendental", 5, "transcendental"),
    ("next x = x * asinpi(1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * atan2pi(0, 1)", "step map",
     "irrational-constant", 5, "irrational-constant"),
    ("next x = x * sinh(0)", "step map",
     "irrational-constant", 5, "irrational-constant"),
]


def _m4_source(body, step):
    two = "y" in body
    b = body + ("\nnext y = y" if two and "next y" not in body else "")
    return _sys1(b, state="x, y" if two else "x", step=step)


@pytest.mark.parametrize("body,step,name,line,before", M4_REFUSALS,
                         ids=[f"{r[0][9:]}|{r[1]}" for r in M4_REFUSALS])
def test_m4_each_changed_behaviour_by_name(body, step, name, line, before):
    """Each source by what this tree makes of it, and the name it had at
    21b98aec (the table above): a changed name is the new behaviour, an
    unchanged one is held. A constant of the four is never
    `constant-division-by-zero` unless the source divides by zero itself
    (1/0), and the sentence of an `irrational-constant` gives its reason."""
    if name == "accepted":
        assert before in lang.CATALOGUE
        assert compile_(_m4_source(body, step), "m4.cftl").step.nodes
        return
    with pytest.raises(lang.Refusal) as info:
        compile_(_m4_source(body, step), "m4.cftl")
    r = info.value
    assert (r.name, r.line, r.source) == (name, line, "m4.cftl"), str(r)
    assert r.sentence and name in lang.CATALOGUE and before in lang.CATALOGUE
    if name == "irrational-constant" and "pi" not in body:
        if any(f"{fn}(" in body for fn in FOUR):
            if "is not a real number" in r.sentence:
                assert "asin(" in body or "acos(" in body
            else:
                assert "write its value as a decimal or a/b" in r.sentence
                assert "Hermite-Lindemann" in r.sentence, r.sentence


def test_an_irrational_constant_is_refused_with_its_reason():
    """Every rational but the fold's in a spread of sizes and signs, for
    each of the four: `irrational-constant` at the source line, the
    sentence naming the function and its arguments and the theorem - and
    for asin and acos outside [-1, 1] saying it is not a real number, as
    sqrt(-4) is - never `constant-division-by-zero`."""
    rng = random.Random("m4 refusals")
    values = ["1", "-1", "2", "1/2", "-1/3", "7/5", "100", "0.001", "1e10",
              "-1e-10", "355/113", "1e300", "(22/7)"]
    values += [f"{rng.randint(-999, 999) or 1}/{rng.randint(1, 99)}"
               for _ in range(20)]
    inside = {"1", "-1", "1/2", "-1/3", "0.001", "-1e-10"}
    for fn in ONE:
        for v in values:
            if fn == "acos" and v == "1":
                continue                    # the fold
            with pytest.raises(lang.Refusal) as info:
                compile_(_sys1(f"next x = x * {fn}({v})", state="x"))
            r = info.value
            assert (r.name, r.line) == ("irrational-constant", 5), (fn, v)
            assert r.sentence.startswith(f"{fn}(")
            if fn == "atan" or v in inside:
                assert "is irrational" in r.sentence and \
                    "Hermite-Lindemann" in r.sentence, (fn, v, r.sentence)
            else:
                assert "is not a real number" in r.sentence, (fn, v)
    for y in values:
        for x in ("1", "-1", "0", "2/3"):
            with pytest.raises(lang.Refusal) as info:
                compile_(_sys1(f"next x = x * atan2({y}, {x})", state="x"))
            r = info.value
            assert (r.name, r.line) == ("irrational-constant", 5), (y, x)
            assert r.sentence.startswith("atan2(") and \
                "Hermite-Lindemann" in r.sentence
    # the exact zeros and the exactly-fixed values apart: atan2(0, c < 0)
    # is pi, refused; atan2(0, c >= 0) is the fold
    with pytest.raises(lang.Refusal):
        compile_(_sys1("next x = x * atan2(0, -1)", state="x"))
    assert compile_(_sys1("next x = x * atan2(0, 1/1000000)", state="x")).const


def test_atan2_of_a_constant_and_a_node_is_a_node():
    """One constant operand and one that is not: a node, the constant a
    bank constant rounded once at the program's format and attribute -
    atan2(0, x) and atan2(x, 0) included, which fold nothing."""
    for body, nodes in (
            ("atan2(x, 1)", [("atan2", ("s0", "c0"), None)]),
            ("atan2(1, x)", [("atan2", ("c0", "s0"), None)]),
            ("atan2(0, x)", [("atan2", ("c0", "s0"), None)]),
            ("atan2(x, 0)", [("atan2", ("s0", "c0"), None)]),
            ("atan2(x, 1/3)", [("atan2", ("s0", "c0"), None)])):
        g = compile_(_sys1(f"next x = {body}", state="x"))
        assert g.step.nodes == nodes, body
        assert len(g.const) == 1


# ---- the exact evaluation ---------------------------------------------------

@needs_mpmath
def test_the_exact_evaluation_of_the_four_is_one_function():
    """The step graph's exact evaluation and the test's own reader take the
    same value of each of the four at the same arguments: exact at their
    zeros and otherwise mpmath's at 1,024 bits of the arguments rounded to
    nearest at 1,024 bits. Each is within 2^-1000 of the function of the
    rounded arguments, relatively (mpmath at 1,200 bits); and the
    identities hold to the same width: asin + acos = pi/2, atan(q) +
    atan(1/q) = +-pi/2 by the sign of q, and atan2(y, x) is atan(y / x) for
    x > 0."""
    import mpmath
    ctx = mpmath.MPContext()
    ctx.prec = 1200
    lib = mpmath.libmp

    def rounded(q):
        return ctx.make_mpf(lib.from_rational(q.numerator, q.denominator,
                                              1024, lib.round_nearest))
    rng = random.Random("m4 transcendentals")
    two = ctx.mpf(2) ** -1000
    qs = [F(rng.randint(-10 ** 6, 10 ** 6), rng.randint(1, 10 ** 4))
          for _ in range(40)]
    qs += [F(1), F(-1), F(355, 113), F(1, 10 ** 30), F(10) ** 30,
           F(2) ** 1000 + 1, F(-3, 2), F(1 << 40, 7)]
    ex = lang_graph.exact_transcendental

    def rel(a, want):
        return abs((ctx.mpf(a.numerator) / a.denominator - want) / want)
    for q in qs:
        a = ex("atan", q)
        assert isinstance(a, F) and T9("atan", q) == a, q
        assert rel(a, ctx.atan(rounded(q))) < two or q == 0, q
        if q != 0:
            inv = ex("atan", 1 / q)
            assert abs(ctx.mpf(a.numerator) / a.denominator
                       + ctx.mpf(inv.numerator) / inv.denominator
                       - (ctx.pi / 2 if q > 0 else -ctx.pi / 2)) \
                < two * 4, q
    ins = [F(rng.randint(-10 ** 6, 10 ** 6), 10 ** 6) for _ in range(40)]
    ins += [F(1), F(-1), F(1, 2), F(-1, 3), F(1, 10 ** 30), F(999999, 10 ** 6)]
    half_pi = ctx.pi / 2
    for q in ins:
        s, c = ex("asin", q), ex("acos", q)
        assert T9("asin", q) == s and T9("acos", q) == c, q
        if q not in (0, 1):
            assert rel(c, ctx.acos(rounded(q))) < two, q
        if q != 0:
            assert rel(s, ctx.asin(rounded(q))) < two, q
        assert abs(ctx.mpf(s.numerator) / s.denominator
                   + ctx.mpf(c.numerator) / c.denominator - half_pi) \
            < two * 4, q
    pairs = [(F(rng.randint(-10 ** 5, 10 ** 5), rng.randint(1, 10 ** 3)),
              F(rng.randint(-10 ** 5, 10 ** 5), rng.randint(1, 10 ** 3)))
             for _ in range(40)]
    pairs += [(F(1), F(0)), (F(-1), F(0)), (F(0), F(-1)), (F(0), F(-5, 3)),
              (F(1, 10 ** 30), F(-1)), (F(-1, 10 ** 30), F(-1)),
              (F(10) ** 30, F(10) ** -30)]
    for y, x in pairs:
        a = ex("atan2", y, x)
        assert isinstance(a, F) and T9("atan2", y, x) == a, (y, x)
        if y == 0 and x >= 0:
            assert a == 0
            continue
        want = ctx.atan2(rounded(y), rounded(x))
        assert rel(a, want) < two, (y, x)
        if x > 0:
            av = ctx.mpf(a.numerator) / a.denominator
            assert abs(av - ctx.atan(rounded(y) / rounded(x))) < two * 4, \
                (y, x)
    # the exact evaluation of a node and of the function agree on a graph,
    # and a tangent section reaches the same functions
    g = compile_(_sys1("next x = atan(x)\nnext y = atan2(y, x) * acos(x / 4)"))
    point = [F(3, 2), F(-5, 7)]
    got = g.exact_eval("step", point)
    assert got == [ex("atan", point[0]),
                   ex("atan2", point[1], point[0])
                   * ex("acos", point[0] / 4)]
    gt = compile_(TL._sys1("next x = atan(x)", state="x").replace(
        "state x\n", "state x\ntangent v\n"))
    assert gt.exact_eval("tangent_step", [F(1, 3)], tangent=[F(2)]) == \
        [F(2) / (F(1, 9) + 1)]
    with pytest.raises(lang_graph.Undefined):
        compile_(_sys1("next x = asin(x)", state="x")).exact_eval(
            "step", [F(2)])


# ---- the renderers ----------------------------------------------------------

@needs_mpmath
def test_the_renderers_write_the_four_and_read_back():
    """The canonical form writes each as the generic call; the mathematical
    form as arctan(a), arcsin(a), arccos(a) and atan2(y, x), one operation
    each; each reads back - the canonical form to the same graph, the
    mathematical form exactly at random rational points (each of the four a
    fixed function of its exact argument on both sides), every line held
    (the three checks)."""
    g = compile_(_sys1("next x = atan2(y, x) + asin(x / 4)\n"
                       "next y = acos(x / 8) * atan(y)"))
    canon = lang.render_canonical(g)
    assert "\nnext x = atan2(y, x) + asin(x / 4)\n" in canon
    assert "\nnext y = acos(x / 8) * atan(y)\n" in canon
    math = lang.render_math(g)
    assert "\n  x ↦ atan2(y, x) + arcsin(x/4)\n" in math
    assert "\n  y ↦ arccos(x/8)·arctan(y)\n" in math
    assert compile_(canon).to_bytes() == g.to_bytes()
    assert TL.check_intention_out(g, random.Random("m4 renderers"), 4) == 4
    form = MathForm(math)
    point = [F(3, 2), F(5, 7)]
    assert form.step(point) == g.exact_eval("step", point)
    # a negation and a quotient around a call keep their brackets, and
    # atan2's operands are whole expressions
    g = compile_(_sys1("next x = -atan(x) / acos(y / 2)\n"
                       "next y = atan2(-x, y - 1) - atan2(x / y, 1)"))
    math = lang.render_math(g)
    assert "\n  x ↦ (−arctan(x))/arccos(y/2)\n" in math
    assert "\n  y ↦ atan2(−x, y − 1) − atan2(x/y, 1)\n" in math
    TL.check_intention_out(g, random.Random("m4 renderers 2"))


@needs_mpmath
@pytest.mark.parametrize("name", ["pendulum-rk4", "wave-sv", "mixed-map",
                                  "folds-euler"])
def test_intention_out_of_written_systems(name):
    """The four under each integrator, in lets and equations, with Greek
    names, with a tangent vector, and beside folds: the three checks."""
    text = {
        "pendulum-rk4": ("system pendulum\nformat fp128\nround rdn\n"
                         "state theta, omega\ntangent v\n"
                         "param lambda = 1/3\nlet phi = atan(theta)\n"
                         "d/dt theta = omega\n"
                         "d/dt omega = -(lambda * phi) - "
                         "atan2(theta, 2 + omega * omega) / 8\n"
                         "step rk4, h = 1/64\n"),
        "wave-sv": ("system wave\nformat fp32\nround rup\nstate q, p\n"
                    "lane param kappa = 3/2\ntangent v, w\n"
                    "d/dt q = p + asin(kappa * p / (2 + abs(p))) / 16\n"
                    "d/dt p = -(kappa * acos(q / (1 + abs(q))))\n"
                    "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
        "mixed-map": ("system mix\nformat fp256\nround rmm\nstate x, y\n"
                      "next x = atan(abs(x) + 1) * acos(y / (1 + abs(y)))\n"
                      "next y = fma(x, atan2(y - x, 1 + x * x), "
                      "asin(x / (1 + abs(x))))\n"
                      "step map\n"),
        "folds-euler": ("system folds\nformat fp64\nstate x\n"
                        "param sigma = atan(0) + asin(0) + acos(1) + "
                        "atan2(0, 0) + atan2(0, 7)\n"
                        "d/dt x = sigma * atan(x) + acos(1)\n"
                        "step euler, h = 1/8\n"),
    }[name]
    g = compile_(text, name)
    assert TL.check_intention_out(g, random.Random(f"m4 io {name}"), 3) > 0


def _m4_expr_of(fns):
    """_expr's operations and `fns`, each call of operands that read a
    value of the run - the state, a param, a lane param or a let - so that
    few fold (a constant's, refused where irrational, is
    test_m4_each_changed_behaviour_by_name's); asin's and acos's argument
    is x / (1 + |x|), inside (-1, 1) at every point, so that the exact
    evaluation decides there."""
    def expr(rng, operands, depth):
        run = [o for o in operands if o[0] in "splraqm"]
        if depth > 0 and rng.random() < 0.35:
            fn = rng.choice(fns)
            r1 = rng.choice(run)
            if fn == "atan2":
                return (f"atan2({expr(rng, operands, depth - 1)} * {r1}, "
                        f"{expr(rng, operands, depth - 1)} * "
                        f"{rng.choice(run)})")
            if fn == "atan":
                return f"atan({expr(rng, operands, depth - 1)} * {r1})"
            return f"{fn}({r1} / (1 + abs({r1})))"
        return TL._expr(rng, operands, depth, sub=expr)
    return expr


_m4_expr = _m4_expr_of(FOUR)
_m4_expr_atan = _m4_expr_of(("atan", "atan2"))


# A random source with the four may fold to a constant the language refuses
# besides _ARTIFACTS': a fold that overflows or rounds to zero.
_M4_ARTIFACTS = TL._ARTIFACTS | {"constant-range", "constant-overflow",
                                 "constant-rounds-to-zero"}


@needs_mpmath
def test_intention_out_of_random_systems():
    """Random systems with the four beside every other operation - lets,
    params, lane params, arrays, every integrator, format and attribute,
    a third with a tangent vector - each through the three checks."""
    rng = random.Random("lang random m4 systems")
    done = skipped = decided = 0
    ops, kinds, tangents = set(), set(), 0
    while done < 30:
        text = TL.random_system(rng, done + skipped, expr=_m4_expr)
        if done % 3 == 2:
            lines = text.split("\n")
            k = next(i for i, ln in enumerate(lines) if ln.startswith("state"))
            text = "\n".join(lines[:k + 1] + ["tangent v"] + lines[k + 1:])
        try:
            g = compile_(text, f"random-m4-{done + skipped}")
        except lang.Refusal as r:
            assert r.name in _M4_ARTIFACTS, f"{r}\n{text}"
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
    assert set(FOUR) <= ops and tangents >= 9
    assert kinds == {"rk4", "euler", "stormer-verlet", "map"}


# ---- the rules ---------------------------------------------------------------

# The test's own copy of docs/LANGUAGE.md's rows for the four: each written
# operation, its tangent as the canonical form writes it, for each set of
# operands whose tangent is nonzero (test_lang_tangent.RULES' form).
RULES4 = [
    ("atan(a)", {"a": "v.a / fma(a, a, 1)"}),
    ("asin(a)", {"a": "v.a / sqrt(fma(-a, a, 1))"}),
    ("acos(a)", {"a": "v.a / (-sqrt(fma(-a, a, 1)))"}),
    ("atan2(a, b)", {"ab": "fma(b, v.a, -(a * v.b)) / fma(b, b, a * a)",
                     "a": "b * v.a / fma(b, b, a * a)",
                     "b": "(-(a * v.b)) / fma(b, b, a * a)"}),
]
DOC_RULES4 = {
    "`atan(a)`": "`da / fma(a, a, 1)`",
    "`asin(a)`": "`da / sqrt(fma(-a, a, 1))`",
    "`acos(a)`": "`da / (-sqrt(fma(-a, a, 1)))`",
}


@pytest.mark.parametrize("expr,cases", RULES4, ids=[r[0] for r in RULES4])
def test_each_rule_as_the_table_writes_it(expr, cases):
    """Each rule rendered on a one-operation system, as the canonical form
    writes it; a param operand has a zero tangent, which leaves the term
    out: atan2's three cases are both tangents, a alone (b a param) and b
    alone (a a param), and the tangent of y is the constant 0 when neither
    is."""
    for active, want in cases.items():
        g = compile_(TT._rule_system(expr, active))
        assert TT._tangent_line(g) == want, (expr, active)
    g = compile_(TT._rule_system(expr, ""))
    assert TT._tangent_line(g) == "0"
    assert not [1 for op, _a, _l in g.tangent_step.nodes
                if op in ("mul", "fma", "neg", "div", "sqrt", *FOUR)]


def test_the_rules_node_shapes_are_the_contract():
    """The operands in this order (the contract between parcels M4L and
    M4C), c1 the constant 1, a and b read by name where named: atan
    div(da, fma(a, a, c1)); asin div(da, sqrt(fma(neg(a), a, c1))); acos
    div(da, neg(sqrt(fma(neg(a), a, c1)))); atan2, both tangents nonzero,
    div(fma(b, da, neg(mul(a, db))), fma(b, b, mul(a, a))); db zero
    div(mul(b, da), fma(b, b, mul(a, a))); da zero div(neg(mul(a, db)),
    fma(b, b, mul(a, a))). No rule writes a routine node."""
    shapes = {
        "atan": [("fma", ("s0", "s0", "c0"), None),
                 ("div", ("t0", "d0"), None)],
        "asin": [("neg", ("s0",), None), ("fma", ("d0", "s0", "c0"), None),
                 ("sqrt", ("d1",), None), ("div", ("t0", "d2"), None)],
        "acos": [("neg", ("s0",), None), ("fma", ("d0", "s0", "c0"), None),
                 ("sqrt", ("d1",), None), ("neg", ("d2",), None),
                 ("div", ("t0", "d3"), None)],
    }
    for fn, nodes in shapes.items():
        g = TT._one(fn)
        assert g.step.nodes == [(fn, ("s0",), None)]
        assert g.tangent_step.nodes == nodes, fn
        assert g.tangent_step.out == ["t0", f"d{len(nodes) - 1}"]
        assert [v for v, *_r in g.const] == [F(1)]
        assert not {op for op, _a, _l in g.tangent_step.nodes} & set(FOUR)
    # atan2, the three cases (state a, b, y with both; one a param)
    both = compile_("system r\nformat fp64\nstate a, b, y\ntangent v\n"
                    "next a = a\nnext b = b\nnext y = atan2(a, b)\n"
                    "step map\n")
    assert both.step.nodes == [("atan2", ("s0", "s1"), None)]
    assert both.tangent_step.nodes == [
        ("mul", ("s0", "t1"), None), ("neg", ("d0",), None),
        ("fma", ("s1", "t0", "d1"), None), ("mul", ("s0", "s0"), None),
        ("fma", ("s1", "s1", "d3"), None), ("div", ("d2", "d4"), None)]
    assert both.tangent_step.out == ["t0", "t1", "d5"]
    a_only = compile_("system r\nformat fp64\nstate a, y\ntangent v\n"
                      "param b = 2/7\nnext a = a\nnext y = atan2(a, b)\n"
                      "step map\n")
    assert a_only.tangent_step.nodes == [
        ("mul", ("p0", "t0"), None), ("mul", ("s0", "s0"), None),
        ("fma", ("p0", "p0", "d1"), None), ("div", ("d0", "d2"), None)]
    b_only = compile_("system r\nformat fp64\nstate b, y\ntangent v\n"
                      "param a = 2/7\nnext b = b\nnext y = atan2(a, b)\n"
                      "step map\n")
    assert b_only.tangent_step.nodes == [
        ("mul", ("p0", "t0"), None), ("neg", ("d0",), None),
        ("mul", ("p0", "p0"), None), ("fma", ("s0", "s0", "d2"), None),
        ("div", ("d1", "d3"), None)]
    for g in (both, a_only, b_only):
        assert not {op for op, _a, _l in g.tangent_step.nodes} & set(FOUR)
    # a named operand is read by name, not written again
    for fn, want in (("atan", "v.b / fma(b, b, 1)"),
                     ("asin", "v.b / sqrt(fma(-b, b, 1))"),
                     ("acos", "v.b / (-sqrt(fma(-b, b, 1)))")):
        g = compile_(f"system r\nformat fp64\nstate a, y\ntangent v\n"
                     f"let b = a * a\nnext a = a\nnext y = {fn}(b)\n"
                     f"step map\n")
        assert TT._tangent_line(g) == want, fn
    g = compile_("system r\nformat fp64\nstate a, y\ntangent v\n"
                 "let b = a * a\nnext a = a\nnext y = atan2(b, a)\n"
                 "step map\n")
    assert TT._tangent_line(g) == (
        "fma(a, v.b, -(b * v.a)) / fma(a, a, b * b)")


# ---- the derivative ---------------------------------------------------------

def _dual4(op, v, d):
    """(value, derivative) of the four, the test's own calculus: each value
    as the exact evaluation takes it (lang_mathform.transcendental), and
    the derivative the textbook's - 1/(1 + x^2), +-1/sqrt(1 - x^2) with
    the root as both evaluations take it (graph.exact_root, a fixed
    function of its exact argument), and (x dy - y dx)/(x^2 + y^2) for
    atan2(y, x) - undefined (ArithmeticError) where the derivative is: at
    |x| = 1 for asin and acos, at the origin for atan2."""
    x, dx = v[0], d[0]
    if op == "atan":
        return T9("atan", x), dx / (1 + x * x)
    if op in ("asin", "acos"):
        val = T9(op, x)
        if abs(x) == 1:
            raise ArithmeticError(f"{op}'({x})")
        root = lang_graph.exact_root(1 - x * x)
        return val, (dx if op == "asin" else -dx) / root
    y, dy = v[0], d[0]
    x, dx = v[1], d[1]
    if x == 0 and y == 0:
        raise ArithmeticError("atan2'(0, 0)")
    return T9("atan2", y, x), (x * dy - y * dx) / (x * x + y * y)


def dual4(g, section, state, tangent, params, lanes):
    """TT.dual_eval's, with the four: the exact directional derivative of
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
        if op in FOUR:
            nodes.append(_dual4(op, [p[0] for p in a], [p[1] for p in a]))
        else:
            nodes.append(TT._dual(op, a, 0, 1, None))
    return [get(o)[1] for o in sec.out]


def _inside(rng, n, bound):
    """A state whose components are random rationals in (-bound, bound)."""
    return [F(rng.randint(-1000 * bound + 1, 1000 * bound - 1),
              1000) for _ in range(n)]


def _case(g, rng, bound):
    state = _inside(rng, g.n_state, bound)
    tangent = [TT._q(rng) for _ in range(g.n_state)]
    params = [TT._q(rng) for _ in g.param]
    lanes = [TT._q(rng) for _ in g.lane]
    return state, tangent, params, lanes


def exact_misses(g, rng, points=3, bound=3):
    """(points decided, points where the tangent is not the derivative),
    over the field and the step at random rational points of magnitude
    below `bound`, TT.derivative_misses' with the four. A point at which
    the test's own derivative is undefined (a zero divisor, a root of a
    negative, asin or acos outside [-1, 1], atan2 at the origin) decides
    nothing and is not counted; where it is defined, the tangent sections
    must be too, and equal."""
    bad = tot = 0
    for section, tsection in (("field", "tangent_field"),
                              ("step", "tangent_step")):
        if g.section(section) is None:
            continue
        for _ in range(points):
            state, tangent, params, lanes = _case(g, rng, bound)
            try:
                want = dual4(g, section, state, tangent, params, lanes)
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


def cd_misses(g, rng, points, eps, tol, bound):
    """(points decided, points where a tangent component is not the
    central difference in high precision): (S(x + eps v) - S(x - eps v)) /
    (2 eps) of a primal section S, each of the four the exact evaluation's
    1,024-bit value, against the tangent section, every component within
    `tol` max(1, |tangent|). Points of magnitude below `bound`; one where
    the exact evaluation is undefined decides nothing."""
    tot = bad = 0
    for section, tsection in (("field", "tangent_field"),
                              ("step", "tangent_step")):
        if g.section(section) is None:
            continue
        for _ in range(points):
            st, tv, pa, la = _case(g, rng, bound)
            try:
                up = g.exact_eval(section, [s + eps * t for s, t in
                                            zip(st, tv)], pa, la)
                dn = g.exact_eval(section, [s - eps * t for s, t in
                                            zip(st, tv)], pa, la)
                got = g.exact_eval(tsection, st, pa, la, tangent=tv)
            except ArithmeticError:
                continue
            tot += 1
            bad += any(abs((u - d) / (2 * eps) - t) >
                       tol * max(1, abs(t)) for u, d, t in zip(up, dn, got))
    return tot, bad


M4_SYSTEMS = {   # the four under each integrator, in lets and equations
    "atan and atan2, a map": (
        "system two\nformat fp64\nstate x, y, z\ntangent v\n"
        "next x = atan(y) - atan2(z, x * x + 1)\n"
        "next y = atan2(x, y * y + 1) + atan(z)\n"
        "next z = atan(x * x + 1) * atan2(y, 2 + z * z)\nstep map\n"),
    "the four, a map": (
        "system four\nformat fp64\nstate x, y, z\ntangent v\n"
        "next x = asin(x / (1 + abs(x))) - acos(z / (1 + abs(z)))\n"
        "next y = atan2(y, 1 + x * x) + asin(y / (2 + abs(y)))\n"
        "next z = acos(x / (1 + abs(x))) * atan(z)\nstep map\n"),
    "a pendulum, rk4": (
        "system pendulum\nformat fp64\nstate theta, omega\ntangent v\n"
        "param g = 9.81\nparam len = 1.5\n"
        "d/dt theta = omega\n"
        "d/dt omega = -(g / len) * atan(theta) - "
        "asin(omega / (1 + abs(omega))) / 4\n"
        "step rk4, h = 1/64\n"),
    "a let, rdn": (
        "system rotor\nformat fp128\nround rdn\nstate phi, w\ntangent v\n"
        "param kappa = 1/3\nlet s = acos(phi / (1 + abs(phi)))\n"
        "d/dt phi = w + atan2(w, 1 + phi * phi) * kappa\n"
        "d/dt w = -(kappa * s) - atan(w) / 4\n"
        "step rk4, h = 1/64\n"),
    "stormer-verlet": (
        "system pot\nformat fp32\nround rup\nstate q, p\ntangent v\n"
        "d/dt q = p + atan2(p, 2 + p * p) / 8\n"
        "d/dt p = -atan(q) * asin(q / (1 + abs(q)))\n"
        "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
    "euler, two vectors": (
        "system e\nformat fp256\nround rmm\nstate x\ntangent v, w\n"
        "d/dt x = acos(-x / (1 + abs(x))) + atan2(x, 1 + x * x)\n"
        "step euler, h = 1/8\n"),
    "atan2 against a param and a lane param": (
        "system pl\nformat fp64\nstate x, y\ntangent v\n"
        "param p = 3/7\nlane param k = 5/3\n"
        "next x = atan2(x + p, y * y + 1) + atan2(k, y + 2)\n"
        "next y = atan2(x, k) - atan2(p, x * x + 1)\nstep map\n"),
}


def m4_graphs(count=16, seed="m4 corpus", atan_only=8):
    """The written systems, and generated systems with tangent vectors
    holding the four beside every other operation - `count` of them - and
    `atan_only` more holding atan and atan2 and neither asin nor acos (the
    central difference at 2^-256 runs on those alone)."""
    graphs = [compile_(t, w) for w, t in M4_SYSTEMS.items()]
    rng = random.Random(seed)
    k = 0
    while len(graphs) < len(M4_SYSTEMS) + count + atan_only:
        atan_phase = len(graphs) >= len(M4_SYSTEMS) + count
        text = TL.random_system(rng, k, expr=_m4_expr_atan if atan_phase
                                else _m4_expr)
        k += 1
        try:
            g = compile_(TT.with_tangent(text, "v, w" if k % 4 == 0 else "v"),
                         f"m4-{k}")
        except lang.Refusal as r:
            assert r.name in _M4_ARTIFACTS, f"{r}\n{text}"
            continue
        held = set(FOUR) & set(g.op_counts("step"))
        if held and not (atan_phase and {"asin", "acos"} & held):
            graphs.append(g)
    return graphs


@needs_mpmath
def test_the_rules_are_the_derivative():
    """Two derivative checks, named for what they are.

    The EXACT check: the tangent evaluated exactly against the test's own
    dual numbers (_dual4: the textbook's derivative of each of the four, at
    the value the exact evaluation takes), on the written systems and on
    generated ones, with points of magnitude below 3 - atan's and atan2's
    anywhere, asin's and acos's arguments inside (-1, 1) by their
    x / (1 + |x|) forms. No miss at any point, and most points decide.

    The CENTRAL DIFFERENCE in high precision, independent of the dual
    numbers: (S(x + eps v) - S(x - eps v)) / (2 eps), S the primal section
    at the exact evaluation's values. Two step and tolerance pairs, named
    in the assertions: eps 2^-256 within 2^-300 for a graph without asin,
    acos or a square root, which hold a root the exact evaluation rounds
    down to 2^-256 (a difference at 2^-256 would measure that rounding;
    L4's difference is at 2^-64), and eps 2^-64 within 2^-100, points of
    magnitude below 2, for one with any of them. A graph holding asin or
    acos is run at the second pair only, and the count of what each pair
    decided is asserted."""
    rng = random.Random("m4 derivative")
    graphs = m4_graphs()
    assert len(graphs) == len(M4_SYSTEMS) + 16 + 8
    tot = bad = hi_tot = hi_bad = rt_tot = rt_bad = 0
    for g in graphs:
        a, b = exact_misses(g, rng, points=3)
        tot, bad = tot + a, bad + b
        if {"asin", "acos", "sqrt"} & set(g.op_counts("step")):
            a, b = cd_misses(g, rng, 3, EPS_ROOT, TOL_ROOT, 2)
            rt_tot, rt_bad = rt_tot + a, rt_bad + b
        else:
            a, b = cd_misses(g, rng, 3, EPS_HI, TOL_HI, 3)
            hi_tot, hi_bad = hi_tot + a, hi_bad + b
    assert bad == 0 and tot >= 60, (tot, bad)
    assert hi_bad == 0 and hi_tot >= 20, ("2^-256 within 2^-300", hi_tot,
                                          hi_bad)
    assert rt_bad == 0 and rt_tot >= 60, ("2^-64 within 2^-100", rt_tot,
                                          rt_bad)
    ops = set()
    for g in graphs:
        ops |= set(g.op_counts("step"))
    assert set(FOUR) <= ops


# ---- each rule's rounding ---------------------------------------------------

def _domain(fn, rng):
    """An argument inside the function's domain with the central
    difference well defined: |a| at most 7/8 for asin and acos, any of a
    few binades for atan."""
    if fn == "atan":
        return F(rng.randint(-64000, 64000), 1000)
    return F(rng.randint(-875, 875), 1000)


def _cd(fn, a, da, eps=EPS_HI):
    """The derivative of the function at a along da, by a central
    difference at eps of the reader's 1,024-bit values."""
    return (T9(fn, a + eps * da) - T9(fn, a - eps * da)) / (2 * eps)


def rule_bits(fn, fmt, code, a, da):
    """The table's rule on one lane, in softfloat: its primal-only
    denominator rounded as the table says - atan one fma; asin and acos one
    fma, one root, and for acos the root's exact negation - then the
    division once -> (bits, the division's exact value before its
    rounding)."""
    val = functools.partial(C.value_of, fmt)
    one = C.round_once(fmt, sf.RND_RNE, F(1))[0]
    if fn == "atan":
        q = sf.fma(fmt, a, a, one, code)[0]
    else:
        q = sf.fma(fmt, sf.neg(fmt, a)[0], a, one, code)[0]
        q = sf.sqrt(fmt, q, code)[0]
        if fn == "acos":
            q = sf.neg(fmt, q)[0]
    bits = sf.div(fmt, da, q, code)[0]
    try:
        exact = val(da) / val(q)
    except (ValueError, ZeroDivisionError):     # not finite, or a zero root
        exact = None
    return bits, exact


def rounding_misses(fn, fmtname, rnd, rng, lanes=6):
    """(lanes, lanes whose tangent is not the table's rule rounded as the
    table says, lanes whose division's exact value is not the derivative
    within its denominator's roundings) on y = fn(a): the denominator
    rounded first, the derivative by a central difference at 2^-256 of the
    1,024-bit values. One rounding of the denominator for atan (u), and
    for asin and acos the fma's and the root's - at most 2u relatively,
    u = 2^(1-p)."""
    g = TT._one(fn, fmtname, rnd)
    fmt, code = g.fmt, C.RND_BY_NAME[rnd]
    u = F(1, 1 << (fmt.prec - 1))
    pairs = [(TT._bits(fmt, _domain(fn, rng)),
              TT._bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)))
             for _ in range(lanes)]
    run = lang.run(g, [[a, 0] for a, _d in pairs], 1,
                   tangents=[[[da, 0]] for _a, da in pairs])
    bits_bad = value_bad = 0
    for (a, da), tv in zip(pairs, run.tangents):
        t = tv[0][1]
        want, exact = rule_bits(fn, fmt, code, a, da)
        bits_bad += t != want
        d = _cd(fn, C.value_of(fmt, a), C.value_of(fmt, da))
        bound = (1 if fn == "atan" else 2) * u * F(101, 100)
        value_bad += abs(exact - d) > (bound + F(1, 1 << 400)) * abs(d)
    return len(pairs), bits_bad, value_bad


def _atan2_system(case, fmtname, rnd):
    """atan2's three cases as systems: both operands states, b a lane
    param (a's tangent alone), a a lane param (b's alone). Lane params so
    that a run draws their values."""
    head = f"system r\nformat {fmtname}\nround {rnd}\n"
    if case == "both":
        return compile_(head + "state a, b, y\ntangent v\nnext a = a\n"
                        "next b = b\nnext y = atan2(a, b)\nstep map\n")
    if case == "db0":
        return compile_(head + "state a, y\nlane param b\ntangent v\n"
                        "next a = a\nnext y = atan2(a, b)\nstep map\n")
    return compile_(head + "state b, y\nlane param a\ntangent v\n"
                    "next b = b\nnext y = atan2(a, b)\nstep map\n")


def _atan2_rule(case, fmt, code, a, b, da, db):
    """atan2's rule on one lane in softfloat: the denominator fma(b, b,
    a * a), the numerator fma(b, da, -(a * db)) when both tangents are
    not zero, b * da when db is zero and -(a * db) when da is, then the
    division -> (bits, the numerator's and the division's exact values
    before their roundings)."""
    val = functools.partial(C.value_of, fmt)
    aa = sf.mul(fmt, a, a, code)[0]
    den = sf.fma(fmt, b, b, aa, code)[0]
    if case == "both":
        ab = sf.neg(fmt, sf.mul(fmt, a, db, code)[0])[0]
        num = sf.fma(fmt, b, da, ab, code)[0]
    elif case == "db0":
        num = sf.mul(fmt, b, da, code)[0]
    else:
        num = sf.neg(fmt, sf.mul(fmt, a, db, code)[0])[0]
    bits = sf.div(fmt, num, den, code)[0]
    try:
        return bits, val(num), val(den)
    except ValueError:                          # a lane that is not finite
        return bits, None, None


def atan2_rounding_misses(case, fmtname, rnd, rng, lanes=6):
    """(lanes, lanes whose tangent is not atan2's rule rounded as the
    table says, lanes whose last operations' exact values are not the
    derivative within their operands' roundings) on y = atan2(a, b). The
    bound is absolute in the numerator - fma(b, da, -(a db)) can cancel -
    u |a db| for the product's rounding and u |numerator| for the fma's,
    over the true denominator, plus 2.1 u of the quotient for the
    denominator's two roundings."""
    g = _atan2_system(case, fmtname, rnd)
    fmt, code = g.fmt, C.RND_BY_NAME[rnd]
    u = F(1, 1 << (fmt.prec - 1))

    def draw():
        a = F(rng.randint(-64000, 64000), 1000)
        if abs(a) < F(1, 100):
            a += 1
        return a
    rows = [(TT._bits(fmt, draw()), TT._bits(fmt, draw()),
             TT._bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)),
             TT._bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)))
            for _ in range(lanes)]
    zero = 0
    if case == "both":
        run = lang.run(g, [[a, b, 0] for a, b, _x, _y in rows], 1,
                       tangents=[[[da, db, 0]] for _a, _b, da, db in rows])
    elif case == "db0":
        run = lang.run(g, [[a, 0] for a, _b, _x, _y in rows], 1,
                       lane_params=[[b] for _a, b, _x, _y in rows],
                       tangents=[[[da, 0]] for _a, _b, da, _y in rows])
    else:
        run = lang.run(g, [[b, 0] for _a, b, _x, _y in rows], 1,
                       lane_params=[[a] for a, _b, _x, _y in rows],
                       tangents=[[[db, 0]] for _a, _b, _x, db in rows])
    bits_bad = value_bad = 0
    for (a, b, da, db), tv in zip(rows, run.tangents):
        t = tv[0][-1]
        if case == "db0":
            db = zero
        if case == "da0":
            da = zero
        want, num, den = _atan2_rule(case, fmt, code, a, b, da, db)
        bits_bad += t != want
        av, bv = C.value_of(fmt, a), C.value_of(fmt, b)
        dav = C.value_of(fmt, da) if case != "da0" else F(0)
        dbv = C.value_of(fmt, db) if case != "db0" else F(0)
        d = (T9("atan2", av + EPS_HI * dav, bv + EPS_HI * dbv)
             - T9("atan2", av - EPS_HI * dav, bv - EPS_HI * dbv)) \
            / (2 * EPS_HI)
        got = num / den
        eps = (u * abs(av * dbv) + u * abs(num)) / (av * av + bv * bv)
        value_bad += abs(got - d) > (eps + F(21, 10) * u * abs(d)) \
            * F(11, 10) + F(1, 1 << 400)
    return len(rows), bits_bad, value_bad


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_each_rule_rounds_as_the_table_says(fmtname):
    """y = f(a) (and y = atan2(a, b), each of its three cases) under every
    attribute, at random arguments and random tangents: the interpreter's
    tangent is the table's last operation, a division, rounded once, on a
    denominator that is the primal-only value the table rounds first -
    fma(a, a, 1), sqrt(fma(-a, a, 1)) or its exact negation, fma(b, b, a *
    a) - and on a numerator likewise. And the exact values of those last
    operations are the derivative, by a central difference in high
    precision for atan, asin and acos, within the roundings of the
    denominator. So a rule rounded otherwise (the next tests) is red here
    wherever its two forms differ."""
    rng = random.Random(f"m4 rounds {fmtname}")
    for fn in ONE:
        for rnd in RNDS:
            n, bits, value = rounding_misses(fn, fmtname, rnd, rng)
            assert (n, bits, value) == (6, 0, 0), (fn, rnd)
    for case in ("both", "db0", "da0"):
        for rnd in RNDS:
            n, bits, value = atan2_rounding_misses(case, fmtname, rnd, rng)
            assert (n, bits, value) == (6, 0, 0), (case, rnd)


# ---- the rounded-otherwise forms --------------------------------------------

def _lanes_otherwise(fmt, rng, count):
    """(a, da, b, db) lanes away from the domain's edges, for the forms
    below."""
    return [(TT._bits(fmt, _domain("atan", rng)),
             TT._bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)),
             TT._bits(fmt, _domain("asin", rng)),
             TT._bits(fmt, F(rng.randint(-4000, 4000) or 1, 1000)))
            for _ in range(count)]


def _form_differs(kind, fmt, code, a, da, b, db):
    """Whether the rule's table form and its rounded-otherwise form give
    different bits on this lane (all in softfloat): atan's `da / fma(a, a,
    1)` and `(1 / fma(a, a, 1)) * da`; asin's 1 - b^2 as fma(-b, b, 1) and
    as (1 - b) * (1 + b); acos's `da / (-sqrt(r))` and `-(da / sqrt(r))`,
    r = fma(-b, b, 1); atan2's `-(a * db)` and `(-a) * db`."""
    one = C.round_once(fmt, sf.RND_RNE, F(1))[0]
    if kind == "atan":
        q = sf.fma(fmt, a, a, one, code)[0]
        return sf.div(fmt, da, q, code)[0] != sf.mul(
            fmt, sf.div(fmt, one, q, code)[0], da, code)[0]
    nb = sf.neg(fmt, b)[0]
    if kind == "asin":
        q1 = sf.sqrt(fmt, sf.fma(fmt, nb, b, one, code)[0], code)[0]
        q2 = sf.sqrt(fmt, sf.mul(fmt, sf.sub(fmt, one, b, code)[0],
                                 sf.add(fmt, one, b, code)[0], code)[0],
                     code)[0]
        return sf.div(fmt, da, q1, code)[0] != sf.div(fmt, da, q2, code)[0]
    if kind == "acos":
        q = sf.sqrt(fmt, sf.fma(fmt, nb, b, one, code)[0], code)[0]
        return sf.div(fmt, da, sf.neg(fmt, q)[0], code)[0] != sf.neg(
            fmt, sf.div(fmt, da, q, code)[0])[0]
    first = sf.neg(fmt, sf.mul(fmt, a, db, code)[0])[0]
    other = sf.mul(fmt, sf.neg(fmt, a)[0], db, code)[0]
    return first != other


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_which_forms_differ_when_rounded_otherwise(fmtname):
    """The four rules' alternative forms, each against the table's on 40
    finite lanes a format from this test's seeded generator, at every
    attribute (the counts are the test's own, over these lanes): atan's
    `(1 / fma(a, a, 1)) * da` and asin's 1 - a^2 as `(1 - a) * (1 + a)`
    differ from the table's on some lanes under every attribute; acos's
    `-(da / sqrt(fma(-a, a, 1)))` and atan2's `(-a) * db` for `-(a * db)`
    differ on none under rne, rtz and rmm and on more than 5 of 40 under
    rdn and rup (the quotient, and the product, round the other way once
    negated). At a NaN lane the negation's sign bit is set in the second
    form of acos, and in atan2's second product, under every attribute run
    here; acos's negation is the rule's last operation, so a NaN lane is
    red under rne too (the specials' check, not the rounding check's),
    while atan2's product feeds an fma or a division, whose NaN is the
    same quiet NaN either way (test_the_plants)."""
    fmt = FORMATS[fmtname]
    rng = random.Random(f"m4 otherwise {fmtname}")
    lanes = _lanes_otherwise(fmt, rng, 40)
    table = {}
    for kind in FOUR:
        for rnd in RNDS:
            code = C.RND_BY_NAME[rnd]
            table[kind, rnd] = sum(
                _form_differs(kind, fmt, code, a, da, b, db)
                for a, da, b, db in lanes)
    for rnd in RNDS:
        assert table["atan", rnd] > 0 and table["asin", rnd] > 0, \
            (rnd, table)
    for kind in ("acos", "atan2"):
        for rnd in ("rne", "rtz", "rmm"):
            assert table[kind, rnd] == 0, (kind, rnd, table)
        for rnd in ("rdn", "rup"):
            assert table[kind, rnd] > 5, (kind, rnd, table)
    qn = sf.qnan_bits(fmt)
    da = lanes[0][1]
    for rnd in RNDS:
        code = C.RND_BY_NAME[rnd]
        q = sf.sqrt(fmt, qn, code)[0]
        first = sf.div(fmt, da, sf.neg(fmt, q)[0], code)[0]
        other = sf.neg(fmt, sf.div(fmt, da, q, code)[0])[0]
        assert first ^ other == fmt.sign_mask, ("acos", rnd)
        first = sf.neg(fmt, sf.mul(fmt, qn, da, code)[0])[0]
        other = sf.mul(fmt, sf.neg(fmt, qn)[0], da, code)[0]
        assert first ^ other == fmt.sign_mask, ("atan2", rnd)


# ---- the rules at their specials ---------------------------------------------

def _run_unary(g, a, da):
    r = lang.run(g, [[a, 0]], 1, tangents=[[[da, 0]]])
    return r.states[0][1], r.tangents[0][0][1], r.flags, r.primal_flags


def _run_atan2(case, g, y, x, da, db):
    if case == "both":
        r = lang.run(g, [[y, x, 0]], 1, tangents=[[[da, db, 0]]])
    elif case == "db0":
        r = lang.run(g, [[y, 0]], 1, lane_params=[[x]],
                     tangents=[[[da, 0]]])
    else:
        r = lang.run(g, [[x, 0]], 1, lane_params=[[y]],
                     tangents=[[[db, 0]]])
    return r.states[0][-1], r.tangents[0][0][-1], r.flags, r.primal_flags


@needs_mpmath
@pytest.mark.parametrize("fmtname", list(FORMATS))
def test_the_rules_at_their_specials(fmtname):
    """Under every attribute at each format, bit for bit against the
    rule's own operations in softfloat (rule_bits, _atan2_rule), at
    a = +-1, +-0, past +-1, +-inf, a quiet and a signalling NaN; and at
    the points where the rule is not the derivative, said by name:

    - asin and acos at a = +-1: the denominator is a root of an exact
      zero, +0 - and -0 under rdn, IEEE 754 6.3's exact zero sum - so the
      tangent is an infinity with divideByZero: da / +0 for asin (+inf for
      da > 0, -inf under rdn), da / -0 for acos (-inf for da > 0, +inf
      under rdn);
    - atan2 at the origin (+-0, +-0): the denominator and the numerator
      are zeros, and the tangent is the invalid NaN, in each of the three
      cases;
    - atan at +-inf: da / inf, a zero; past +-1 asin and acos are the
      invalid NaN, tangent too."""
    fmt = FORMATS[fmtname]
    sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
    snan = sf.snan_bits(fmt, 1)
    one, mone, two, three = (TT._bits(fmt, v) for v in (1, -1, 2, 3))
    mtwo = TT._bits(fmt, -2)
    for rnd in RNDS:
        code = C.RND_BY_NAME[rnd]
        for fn in ONE:
            g = TT._one(fn, fmtname, rnd)
            for a in (one, mone, 0, sign, two, mtwo, inf, inf ^ sign, qnan,
                      snan, 1):
                r, t, f, pf = _run_unary(g, a, three)
                assert t == rule_bits(fn, fmt, code, a, three)[0], \
                    (fn, rnd, hex(a))
            root_zero = sign if rnd == "rdn" else 0
            if fn in ("asin", "acos"):
                for a in (one, mone):
                    r, t, f, pf = _run_unary(g, a, three)
                    flip = sign if fn == "acos" else 0
                    assert t == inf ^ root_zero ^ flip, (fn, rnd, hex(a))
                    assert f & sf.FLAG_DIVZERO and not pf & sf.FLAG_DIVZERO
                for a in (two, mtwo, inf, inf ^ sign):
                    r, t, f, pf = _run_unary(g, a, three)
                    assert (r, t) == (qnan, qnan) and f & sf.FLAG_INVALID
            if fn == "atan":
                for a in (inf, inf ^ sign):
                    assert _run_unary(g, a, three)[1] == 0, (rnd, hex(a))
            for a in (qnan, snan):
                r, t, f, pf = _run_unary(g, a, three)
                assert (r, t) == (qnan, qnan), (fn, rnd, hex(a))
                assert pf == (0 if a == qnan else sf.FLAG_INVALID)
            # a tangent of zero: the quotient's zero
            r, t, f, pf = _run_unary(g, TT._bits(fmt, F(1, 2)), 0)
            assert t & ~sign == 0, (fn, rnd, hex(t))
        for case in ("both", "db0", "da0"):
            g = _atan2_system(case, fmtname, rnd)
            half = TT._bits(fmt, F(1, 2))
            pts = [(0, 0), (sign, 0), (0, sign), (sign, sign), (one, 0),
                   (mone, 0), (0, one), (0, mone), (one, mone), (inf, one),
                   (one, inf), (inf, inf), (inf ^ sign, inf), (half, mtwo)]
            for y, x in pts:
                r, t, f, pf = _run_atan2(case, g, y, x, three, two)
                want = _atan2_rule(case, fmt, code, y, x,
                                   three if case != "da0" else 0,
                                   two if case != "db0" else 0)[0]
                assert t == want, (case, rnd, hex(y), hex(x))
            for y, x in ((0, 0), (sign, 0), (0, sign), (sign, sign)):
                r, t, f, pf = _run_atan2(case, g, y, x, three, two)
                assert t == qnan and f == pf | sf.FLAG_INVALID \
                    and not pf & sf.FLAG_INVALID, (case, rnd, hex(y), hex(x))
            for y, x in ((qnan, one), (one, qnan)):
                r, t, f, pf = _run_atan2(case, g, y, x, three, two)
                assert (r, t, f) == (qnan, qnan, 0), (case, rnd)


# ---- what each vector pays ---------------------------------------------------

def test_each_vector_pays_one_division_a_call():
    """After sharing what the tangent writes again, each call of the four
    costs a tangent vector one division, and the operands it divides are
    primal-only - fma(a, a, 1); sqrt(fma(-a, a, 1)) and its negation;
    fma(b, b, a * a) - except atan2's numerator, which reads the vector's
    tangent through a product and an fma (the study's section 7). The
    walk below classifies the tangent section's nodes by whether they read
    a tangent input, and asserts the operations of each class."""
    want = {
        "atan": (["div"], ["fma"]),
        "asin": (["div"], ["fma", "neg", "sqrt"]),
        "acos": (["div"], ["fma", "neg", "neg", "sqrt"]),
    }
    for fn, (per_vector, primal_only) in want.items():
        g = TT._one(fn)
        reads = TT._reads_tangent(g)
        ops = [op for op, _a, _l in g.tangent_step.nodes]
        assert sorted(op for op, r in zip(ops, reads) if r) == per_vector, fn
        assert sorted(op for op, r in zip(ops, reads) if not r) == \
            primal_only, fn
    both = compile_("system r\nformat fp64\nstate a, b, y\ntangent v\n"
                    "next a = a\nnext b = b\nnext y = atan2(a, b)\n"
                    "step map\n")
    reads = TT._reads_tangent(both)
    ops = [op for op, _a, _l in both.tangent_step.nodes]
    assert sorted(op for op, r in zip(ops, reads) if r) == \
        ["div", "fma", "mul", "neg"]
    assert sorted(op for op, r in zip(ops, reads) if not r) == ["fma", "mul"]
    # two vectors: the tangent section is generic, one for every vector, so
    # it holds the nodes once; each vector's printed line writes the
    # primal-only denominator again over its own tangent input, which the
    # compiler shares
    g = compile_("system r\nformat fp64\nstate a, y\ntangent v, w\n"
                 "next a = a\nnext y = atan(a)\nstep map\n")
    assert [op for op, _a, _l in g.tangent_step.nodes] == ["fma", "div"]
    canon = lang.render_canonical(g)
    assert "\nnext v.y = v.a / fma(a, a, 1)\n" in canon
    assert "\nnext w.y = w.a / fma(a, a, 1)\n" in canon


@needs_mpmath
def test_the_primal_is_unchanged_by_tangents():
    """With tangents, the primal sections are the system's without them,
    by value, and a run's states and primal flags too; the rules add the
    constant 1 for atan's, asin's and acos's, and none for atan2's."""
    rng = random.Random("m4 primal unchanged")
    for g in m4_graphs(8, "m4 primal", 0):
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
    for fn in ONE:
        for fmtname in FORMATS:
            plain = (f"system r\nformat {fmtname}\nround rdn\nstate a, y\n"
                     f"next a = a\nnext y = {fn}(a)\nstep map\n")
            with_t = plain.replace("state a, y\n", "state a, y\ntangent v\n")
            g0, g1 = compile_(plain), compile_(with_t)
            added = {v for v, *_r in g1.const} - {v for v, *_r in g0.const}
            assert added == {F(1)}, (fn, fmtname)
            fmt = g1.fmt
            states = [[TT._bits(fmt, _domain(fn, rng)), 0] for _ in range(5)]
            r0 = lang.run(g0, states, 3)
            r1 = lang.run(g1, states, 3, tangents=[[[0, 0]] for _ in states])
            assert (r0.states, r0.flags) == (r1.states, r1.primal_flags)
    plain = ("system r\nformat fp64\nstate a, b, y\nnext a = a\nnext b = b\n"
             "next y = atan2(a, b)\nstep map\n")
    g0 = compile_(plain)
    g1 = compile_(plain.replace("state a, b, y\n",
                                "state a, b, y\ntangent v\n"))
    assert {v for v, *_r in g1.const} == {v for v, *_r in g0.const}


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
        "next x = atan(x) + acos(1) + atan2(0, 1)\n"
        "next y = atan2(y, x) * asin(x / 4)\nstep map\n")
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


def test_mpmath_is_needed_only_by_a_run_of_the_thirteen(tmp_path):
    """With mpmath taken away (sys.modules), a reference compiles and runs;
    a source holding the four, with acos(1) and atan2(0, 1) among its
    folds, is checked, rendered and read back, none of which needs mpmath;
    lang.run of it raises transcend.ZivEscalation naming mpmath and the
    functions, before any lane runs; and its exact evaluation, the tests'
    tool, raises ImportError, never an ArithmeticError that would make a
    point decide nothing."""
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
    assert lines[2] == ("ZivEscalation: s computes atan, asin, atan2, whose "
                        "golden functions (python/cft_golden/transcend.py) "
                        "decide each rounding through mpmath's enclosures, "
                        "and mpmath is not installed: lang.run cannot run it "
                        "here"), lines[2]
    assert lines[3] == "exact_eval ImportError"
    assert lines[4] == "needs True"


def test_a_definition_holding_the_four_needs_mpmath():
    """cert2's list of the nodes whose golden function is decided through
    mpmath is the language's TRANSCEND: a definition holding atan, asin,
    acos or atan2 - in its step, and written again in its tangent - needs
    it, and one without them does not."""
    assert cert2.TRANSCEND_OPS == set(lang_graph.TRANSCEND)
    for fn in FOUR:
        args = "x, y" if fn == "atan2" else "x"
        text = (f"system s\nformat fp64\nstate x, y\ntangent v\n"
                f"next x = x\nnext y = y + {fn}({args})\nstep map\n")
        d = cert2.Definition(compile_(text, "s"))
        assert d.needs_mpmath()
        plain = text.replace(f"{fn}({args})", "x * y")
        assert not cert2.Definition(compile_(plain, "s")).needs_mpmath()


# ---- the plants --------------------------------------------------------------

class _Plant(lang_tangent.Derivation):
    """The derivation with one of the four's rules changed (kind)."""
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        k = self.kind
        if node.op in FOUR and any(self.of(x) is not None for x in a):
            t = [self.of(x) for x in a]
            if node.op in ONE:
                da = t[0]
                if node.op == "atan":
                    den = N("fma", R(a[0]), R(a[0]), self.one)
                    if k == "atan's rule: da * fma(a, a, 1)":
                        return N("mul", da, den)
                    if k == "atan's rule rounded otherwise":
                        return N("mul", N("div", self.one, den), da)
                    return N("div", da, den)
                inner = N("fma", N("neg", R(a[0])), R(a[0]), self.one)
                if node.op == "asin":
                    if k == "asin's rule without its root":
                        return N("div", da, inner)
                    if k == "asin's rule rounded otherwise":
                        prod = N("mul", N("sub", self.one, R(a[0])),
                                 N("add", self.one, R(a[0])))
                        return N("div", da, N("sqrt", prod))
                    return N("div", da, N("sqrt", inner))
                if k == "acos's rule without its minus":
                    return N("div", da, N("sqrt", inner))
                if k == "acos's rule rounded otherwise":
                    return N("neg", N("div", da, N("sqrt", inner)))
                return N("div", da, N("neg", N("sqrt", inner)))
            da, db = t
            den = N("fma", R(a[1]), R(a[1]), N("mul", R(a[0]), R(a[0])))
            if k == "atan2's rule: a da - b db":
                num = N("fma", R(a[0]), da if da is not None else self.zero,
                        N("neg", N("mul", R(a[1]),
                                   db if db is not None else self.zero)))
                return N("div", num, den)
            if k == "atan2's rule rounded otherwise" and db is not None:
                minus = N("mul", N("neg", R(a[0])), db)
                if da is None:
                    return N("div", minus, den)
                return N("div", N("fma", R(a[1]), da, minus), den)
        return super().rule(node)


WRONG4 = ["atan's rule: da * fma(a, a, 1)", "asin's rule without its root",
          "acos's rule without its minus", "atan2's rule: a da - b db"]
OTHERWISE4 = ["atan's rule rounded otherwise",
              "asin's rule rounded otherwise",
              "acos's rule rounded otherwise",
              "atan2's rule rounded otherwise"]


def _plant_graph(kind, fmtname="fp64"):
    if kind.startswith("atan2"):
        return _atan2_system("both", fmtname, "rne")
    return TT._one(kind.split("'")[0], fmtname)


@needs_mpmath
@pytest.mark.parametrize("kind", WRONG4 + OTHERWISE4)
def test_the_plants(kind, monkeypatch):
    """Each planted, and each red where it must be. A wrong rule is red on
    the exact check, the central difference (at the step its function
    allows: 2^-256 for atan2, 2^-64 for asin and acos, 2^-256 for atan) and
    the rounding check alike, in every (format, attribute) cell run: fp32,
    fp64 and fp256 under all five attributes. A rule rounded otherwise is
    exact in rationals - green on the exact check and the central
    difference - and red on the rounding check at the cells where its two
    forms differ: atan's and asin's in every cell run, acos's and atan2's
    under rdn and rup only, and green under rne, rtz and rmm there (atan2's
    is run in the case where both tangents are nonzero). At a NaN lane the
    second form of acos is red under every attribute run at fp64 (the
    specials' lane), and atan2's is green under every attribute run there:
    its negation sits inside an fma, whose NaN is the same either way. Each
    also changes the rule table's line."""
    class P(_Plant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check, "Derivation", P)
    name = kind.split("'")[0]
    rng = random.Random(f"m4 plant {kind}")
    exact = cd = 0
    for fmtname in ("fp32", "fp64", "fp256"):
        g = _plant_graph(kind, fmtname)
        exact += exact_misses(g, rng, points=3)[1]
        if name in ("asin", "acos"):
            cd += cd_misses(g, rng, 3, EPS_ROOT, TOL_ROOT, 2)[1]
        else:
            cd += cd_misses(g, rng, 3, EPS_HI, TOL_HI, 3)[1]
    cells = {}
    for fmtname in ("fp32", "fp64", "fp256"):
        for rnd in RNDS:
            if name == "atan2":
                cells[fmtname, rnd] = atan2_rounding_misses(
                    "both", fmtname, rnd, rng, 30)[1]
            else:
                cells[fmtname, rnd] = rounding_misses(
                    name, fmtname, rnd, rng, 30)[1]
    expr = "atan2(a, b)" if name == "atan2" else f"{name}(a)"
    active = "ab" if name == "atan2" else "a"
    line = TT._tangent_line(compile_(TT._rule_system(expr, active)))
    right = dict(RULES4)[expr][active]
    assert line != right, line
    f64 = FORMATS["fp64"]
    nan_red = {}
    if name in ("acos", "atan2"):
        for rnd in RNDS:
            if name == "acos":
                t = _run_unary(TT._one("acos", "fp64", rnd), sf.qnan_bits(f64),
                               TT._bits(f64, 3))[1]
            else:
                t = _run_atan2("both", _atan2_system("both", "fp64", rnd),
                               sf.qnan_bits(f64), TT._bits(f64, 2),
                               TT._bits(f64, 3), TT._bits(f64, 5))[1]
            nan_red[rnd] = t != sf.qnan_bits(f64)
    if kind in WRONG4:
        assert exact > 0 and cd > 0 and min(cells.values()) > 0, \
            (exact, cd, cells)
    else:
        assert (exact, cd) == (0, 0), (exact, cd)
        if name in ("atan", "asin"):
            assert min(cells.values()) > 0, cells
        else:
            for (fmtname, rnd), n in cells.items():
                if rnd in ("rdn", "rup"):
                    assert n > 0, (fmtname, rnd, cells)
                else:
                    assert n == 0, (fmtname, rnd, cells)
            if name == "acos":
                assert all(nan_red.values()), nan_red
            else:
                assert nan_red and not any(nan_red.values()), nan_red


@needs_mpmath
def test_atan2_rule_otherwise_is_the_same_where_db_is_zero(monkeypatch):
    """The `(-a) * db` plant changes nothing where db is identically zero
    (a lane param b): atan2's rule there has no db, so it is the table's
    `b * da / den`: green on the rounding check under every attribute at
    every format run, which is why the plant above runs the case where both
    tangents are nonzero."""
    class P(_Plant):
        pass
    P.kind = "atan2's rule rounded otherwise"
    monkeypatch.setattr(lang_check, "Derivation", P)
    rng = random.Random("m4 plant db0")
    for fmtname in ("fp32", "fp64", "fp256"):
        for rnd in RNDS:
            assert atan2_rounding_misses("db0", fmtname, rnd, rng, 12)[1] \
                == 0, (fmtname, rnd)


@needs_mpmath
def test_atan2s_operands_swapped_in_the_interpreter_is_red(monkeypatch):
    """The interpreter's table swapped: atan2's node computes
    atan2(x, y) for atan2(y, x). Red on the golden check under every
    attribute at fp64 (all but the pairs where the two orders agree in
    bits, the NaN pairs among them); and not red on the exact evaluations,
    which do not run the interpreter's table at all."""
    rng = random.Random("m4 plant swap")
    good = [golden_misses("atan2", "fp64", rnd, rng)[1] for rnd in RNDS]
    assert good == [0] * 5
    orig = lang_interp._transcend

    def swapped(fmt, fn, rnd):
        f = orig(fmt, fn, rnd)
        return (lambda a, b: f(b, a)) if fn == "atan2" else f
    monkeypatch.setattr(lang_interp, "_transcend", swapped)
    bad = [golden_misses("atan2", "fp64", rnd, rng)[1] for rnd in RNDS]
    assert all(n > 50 for n in bad), bad
    g = _atan2_system("both", "fp64", "rne")
    assert exact_misses(g, rng, points=3)[1] == 0


@needs_mpmath
def test_atans_golden_function_swapped_for_asins_is_red(monkeypatch):
    """The interpreter's table swapped: atan's node computes asin. Red on
    the golden check under every attribute at fp64 (everywhere but a few
    lanes where the two agree in bits), and on the rules' rounding check
    for atan, whose primal y it never reads: the rounding check runs the
    rule, which reads a and never atan's own value - so that check is blind
    to atan's golden function, which is why the golden check exists."""
    rng = random.Random("m4 plant golden")
    good = [golden_misses("atan", "fp64", rnd, rng)[1] for rnd in RNDS]
    assert good == [0] * 5
    orig = lang_interp._transcend
    monkeypatch.setattr(lang_interp, "_transcend",
                        lambda fmt, fn, rnd: orig(fmt, "asin" if fn == "atan"
                                                  else fn, rnd))
    bad = [golden_misses("atan", "fp64", rnd, rng)[1] for rnd in RNDS]
    assert all(n > 10 for n in bad), bad
    assert [rounding_misses("atan", "fp64", rnd, rng)[1:] for rnd in RNDS] \
        == [(0, 0)] * 5


def test_ops_left_giving_atan2_arity_1_is_red(monkeypatch):
    """OPS built with `**{fn: 1 for fn in TRANSCEND}` as it was for the
    nine gives atan2 one operand: red where an atan2 graph is read back,
    and in the OPS literal."""
    g = compile_(_sys1("next x = atan2(x, y)\nnext y = y"))
    data = g.to_bytes()
    assert list(lang.OPS.items()) == OPS_ITEMS
    ops = dict(lang_graph.OPS)
    ops["atan2"] = 1
    monkeypatch.setattr(lang_graph, "OPS", ops)
    assert list(lang_graph.OPS.items()) != OPS_ITEMS
    with pytest.raises(lang.Refusal) as info:
        type(g).from_bytes(data)
    assert info.value.name == "graph-format"
    assert "atan2 takes 1 operands" in info.value.sentence


def test_a_fold_left_inexact_is_red(monkeypatch):
    """acos(1) folded to a nonzero, and atan2(0, 1) left unfolded: each
    red on the fold test (at every format and attribute it runs over)."""
    real = lang_check._fold_math

    def inexact(op, c, line, c2=None):
        if op == "acos" and c == 1:
            return F(1)
        return real(op, c, line, c2)
    monkeypatch.setattr(lang_check, "_fold_math", inexact)
    with pytest.raises(AssertionError):
        test_the_four_fold_at_their_zeros("acos(1)")
    test_the_four_fold_at_their_zeros("atan(0)")

    def unfolded(op, c, line, c2=None):
        if op == "atan2" and c == 0 and c2 == 1:
            raise lang.Refusal("irrational-constant", "left unfolded", line)
        return real(op, c, line, c2)
    monkeypatch.setattr(lang_check, "_fold_math", unfolded)
    with pytest.raises(lang.Refusal):
        test_the_four_fold_at_their_zeros("atan2(0, 1)")
    test_the_four_fold_at_their_zeros("atan2(0, 5)")


def test_a_refusals_name_swapped_is_red(monkeypatch):
    """asin(2) refused `constant-division-by-zero` instead of
    `irrational-constant`: red on the table of changed behaviours."""
    real = lang_check._fold_inverse

    def swapped(op, c, c2, line):
        if op == "asin" and abs(c) > 1:
            raise lang.Refusal("constant-division-by-zero", "swapped", line)
        return real(op, c, c2, line)
    monkeypatch.setattr(lang_check, "_fold_inverse", swapped)
    row = next(r for r in M4_REFUSALS if r[0] == "next x = x * asin(2)")
    with pytest.raises(AssertionError):
        test_m4_each_changed_behaviour_by_name(*row)
    with pytest.raises(AssertionError):
        test_an_irrational_constant_is_refused_with_its_reason()


def test_transcendental_still_raised_for_one_of_the_four_is_red(monkeypatch):
    """asin back on the reserved list and out of the built-ins: refused
    `transcendental` at run time, red on the node test (which compiles
    it)."""
    monkeypatch.setattr(lang_check, "BUILTINS",
                        {k: v for k, v in lang_check.BUILTINS.items()
                         if k != "asin"})
    monkeypatch.setattr(lang_check, "TRANSCENDENTAL",
                        lang_check.TRANSCENDENTAL | {"asin"})
    with pytest.raises((AssertionError, lang.Refusal, KeyError)) as info:
        test_the_four_are_nodes_between_tan_and_neg()
    if isinstance(info.value, lang.Refusal):
        assert info.value.name == "transcendental"
    else:
        assert isinstance(info.value, (KeyError, AssertionError))
    with pytest.raises(lang.Refusal) as info:
        compile_(_sys1("next x = asin(x)", state="x"))
    assert (info.value.name, info.value.line) == ("transcendental", 5)
