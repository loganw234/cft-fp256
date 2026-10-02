# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Every source the language accepts has a canonical form that reads back
(parcel D2 of the language round, 2026-10-01).

An accepted source compiles or is refused by name; cftc's exit 70 is kept
for a defect in the compiler. Three classes of accepted source broke that,
each stopping cftc with an internal error because the canonical form it
rendered did not read back:

  h folded away   a map that names its step, `step map, h = 1/8`, and
                  reads h only in constants that do not scale with it
                  (h - h, h/h, copysign(1, h)): its step graph holds no
                  h-scaled constant, so the canonical form declares an h
                  nothing reads, which read back was `unused` (the
                  challenge suite's finding 1). Such a source is now
                  `unused` itself, at the step line, its sentence naming
                  the uses that folded, by line, with their values.
  too deep        a source whose canonical form nests past the 100 the
                  parser reads - written with its own parentheses, as a
                  negation used as a multiplicand, a compound constant,
                  the tangent of an unnamed product or of a min chain, or
                  euler's and stormer-verlet's step around an inline
                  right-hand side (verifier-VL3's 14:34:53 entry; D2's
                  probe; verifier-VD2). Such a source is now `too-deep`
                  at the line of the equation or let whose rendered line
                  is too deep, its sentence naming that line and depth.
  a long chain    a chain of lets read by name recursed a definition a
                  level, held to Python's own recursion limit; the
                  canonical form's expansion block chains the stages, so
                  rk4 with 81 to 246 lets was accepted and its canonical
                  form did not read back (verifier-VD2), and the verdict
                  itself hung on the Python version and the caller's
                  stack. The checker now evaluates a definition met deep
                  from the top (check.py, BUDGET): chains of lets, labels
                  and consts may be any length, with the same verdict
                  everywhere.

Here: each variant refused by name, with its line and value; the controls
accepted and read back; the challenge suite's four investigation sources,
verbatim; VL3's depth cases at their boundaries, each accepted one read
back; the measure of nesting (lang/nesting.py) equal to this file's own
count of what render_canonical writes, line by line, and the depth rule
refusing exactly the sources whose canonical form would not read back;
neither rule a read-back; the sentences restated - h-nonlinear for the min
family, the comparisons and select and for a sum, h-scope in a flow - true
of the inputs that made them false; and chains of lets at VD2's boundaries
and far past them, accepted and read back, cycles of any length refused by
name, and the evaluation of a definition met deep held to the recursion
itself, run with no limit in reach, and to a budget forced to 3 frames.
"""

import hashlib
import random
import sys
import threading
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from cft_golden import lang  # noqa: E402
from cft_golden.lang import check as lang_check  # noqa: E402
from cft_golden.lang import nesting  # noqa: E402
from cft_golden.lang import render  # noqa: E402
from cft_golden.lang import syntax  # noqa: E402

SYSTEMS = REPO / "programs" / "systems"
NL = "\n"
MAX = syntax.MAX_NESTING


def compile_(text, source="<test>"):
    return lang.compile_text(text, source).graph


@lru_cache(maxsize=None)
def graph(text):
    """compile_, once a text: the boundary cases are the costly ones (a
    min chain's tangent of 100 terms is 9,999 nodes)."""
    return compile_(text)


def refused(text):
    with pytest.raises(lang.Refusal) as info:
        compile_(text, "probe.cftl")
    assert info.value.source == "probe.cftl"
    return info.value


def reads_back(g):
    """The canonical form, read back, is the same graph byte for byte, and
    written out again is the same text."""
    canon = lang.render_canonical(g)
    again = compile_(canon, "canonical")
    assert again.to_bytes() == g.to_bytes()
    assert lang.render_canonical(again) == canon
    return canon


def nest(text):
    """How deep a text nests, as syntax.lex counts it - each ( and [ opens
    a level, each ) and ] closes one and never below zero, a comment is
    skipped. This file's own count, sharing no code with nesting.py."""
    depth = best = i = 0
    while i < len(text):
        c = text[i]
        if c == ";":
            j = text.find(NL, i)
            i = len(text) if j < 0 else j
            continue
        if c in "([":
            depth += 1
            best = max(best, depth)
        elif c in ")]":
            depth = max(0, depth - 1)
        i += 1
    return best


def src(*body, step="step map, h = 1/8", head="state x"):
    """A system: line 1 its name, 2 its format, 3 `head`, then `body`, then
    the step line."""
    return NL.join(("system s", "format fp64", head) + body + (step,)) + NL


# ---- h folded away: `unused` -----------------------------------------------

FOLDED = {   # the body, and the use as the sentence names it
    "h - h": (("next x = x + (h - h)",), "h - h at line 4 is 0"),
    "(h*h)/(h*h)": (("next x = x + ((h*h)/(h*h))",),
                    "(h * h) / (h * h) at line 4 is 1"),
    "h/h": (("next x = x * (h/h)",), "h / h at line 4 is 1"),
    "copysign(1, h)": (("next x = x * copysign(1, h)",),
                       "copysign(1, h) at line 4 is 1"),
    "abs(h)/h": (("next x = x * (abs(h)/h)",), "abs(h) / h at line 4 is 1"),
    "0*h": (("next x = x + 0*h",), "0 * h at line 4 is 0"),
    "const c = h/h": (("const c = h/h", "next x = x * c"),
                      "h / h at line 4 is 1"),
}


@pytest.mark.parametrize("name", list(FOLDED))
def test_a_map_whose_every_use_of_h_folds_away_is_unused(name):
    """The suite's finding 1 and its five more variants: each accepted until
    D2, and cftc's exit 70. Refused at the step line, naming the use."""
    body, use = FOLDED[name]
    r = refused(src(*body))
    assert (r.name, r.line) == ("unused", len(body) + 4), str(r)
    assert r.sentence == (
        f"no constant of the step scales with h, so h is never used: it is "
        f"read only where it folds to a constant that does not ({use}); "
        f"write the constant, or leave h out of the step line")


def test_the_sentence_names_each_folded_use_by_line_and_value():
    r = refused(src("next x = x * (h/h) + (h - h)",
                    "next y = y * copysign(1, h)",
                    "next z = z + 0*h + abs(h)/h", head="state x, y, z"))
    assert r.line == 7
    assert ("(h / h at line 4 is 1, h - h at line 4 is 0, copysign(1, h) "
            "at line 5 is 1, and 2 more); write the constants,") in r.sentence
    cases = [
        # an index variable the range binds, named with its value
        (src("next x[i] = x[i] + (h/h) * i", head="state x[3]"),
         "(h / h) * i at line 4 is 0 where i = 0"),
        # a const that scales, read so that it does not
        (src("const c = h", "next x = x + (c - c)"), "c - c at line 5 is 0"),
        # a constant output, a constant let
        (src("next x = h - h", "next y = y", head="state x, y"),
         "h - h at line 4 is 0"),
        (src("let r = h - h", "next x = x + r"), "h - h at line 4 is 0"),
        # h's sign, fixed when the graph is compiled
        (src("next x = x * copysign(1, h)", step="step map, h = -1/8"),
         "copysign(1, h) at line 4 is -1"),
        # with a tangent vector
        (src("tangent v", "next x = x * x * copysign(1, h)"),
         "copysign(1, h) at line 5 is 1"),
        # a value named briefly (C.brief), as every sentence names one
        (src("next x = x * ((h/h) / 7 * 1e-50)"),
         "(h / h / 7) * 1e-50 at line 4 is 1.4286e-51 (to five digits)"),
        (src("next x = x * ((h*h*h*h*h*h*h*h*h*h)/(h*h*h*h*h*h*h*h*h*h))"),
         "(h * h * h * h * h * h * h * h * h * ... at line 4 is 1"),
    ]
    for text, use in cases:
        r = refused(text)
        assert r.name == "unused" and f"({use});" in r.sentence, str(r)


CONTROLS = {
    "x + h": src("next x = x + h"),
    "x + (h - h + h), factor 1": src("next x = x + (h - h + h)"),
    "abs(h) in a map": src("next x = x + abs(h)"),
    "abs(h) in a map, h < 0": src("next x = x + abs(h)",
                                  step="step map, h = -1/8"),
    "(h*h)/h is h": src("next x = x + (h*h)/h"),
    "a folded use beside a scaled one": src("next x = x * (h/h) + h"),
    "a constant output h": src("next x = h", "next y = y",
                               head="state x, y"),
    "a map without h": src("next x = x + 1", step="step map"),
    "a flow reading only h/h, every integrator": src(
        "const one = h/h", "d/dt x = one * x", step="step euler, h = 1/8"),
    "rk4": src("const one = h/h", "d/dt x = one * x",
               step="step rk4, h = 1/8"),
    "stormer-verlet": src("const one = h/h", "d/dt x = one * p",
                          "d/dt p = -x", head="state x, p",
                          step="step stormer-verlet, h = 1/8, q = (x), "
                               "p = (p)"),
}


@pytest.mark.parametrize("name", list(CONTROLS))
def test_the_controls_are_accepted_and_read_back(name):
    g = compile_(CONTROLS[name])
    reads_back(g)
    scaled = [fa for _v, fa, _b, _f in g.const if fa is not None]
    # the rule: h is named exactly when some constant scales with it
    assert bool(scaled) == (g.integrator[1] is not None)


def test_h_never_read_keeps_its_sentence():
    r = refused(src("next x = x + 1"))
    assert (r.name, r.line, r.sentence) == (
        "unused", 5, "h is declared and never used, and every operation "
        "written is performed")
    # another unused name at an earlier line is named first, as before
    r = refused(src("let r = x", "next x = x * (h/h)"))
    assert (r.name, r.line) == ("unused", 4)
    assert r.sentence.startswith("the let r is never used")


def test_a_constant_output_of_another_power_is_h_nonlinear_still():
    """h*h as a map's whole right-hand side meets the step when the graph
    is assembled, and is h-nonlinear there, as before: never `unused`."""
    r = refused(src("next x = h*h", "next y = y", head="state x, y"))
    assert (r.name, r.line) == ("h-nonlinear", 4)


# The challenge suite's own files (cases/investigate/), verbatim: their
# catalogued SHA-256s are asserted, so a copy that drifted would fail.
INVESTIGATIONS = {
    "h_cancel_zero": (
        b"system h_cancel_zero\nformat fp64\nround rne\nstate x\n"
        b"next x=x+(h-h)\nstep map, h=1/8\n",
        "64773c2eaba94a8fd520793d58a20dde83392b3b547aa3d36ac8b6ca6d713efd",
        "unused", 6, "(h - h at line 5 is 0)"),
    "h_cancel_nonlinear_intermediate": (
        b"system h_cancel_nonlinear_intermediate\nformat fp64\nround rne\n"
        b"state x\nnext x=x+((h*h)/(h*h))\nstep map, h=1/8\n",
        "b67f95c67808239c8a7a9ac5ec433cbfbec8274ac15bd674e52ee632110fb3b8",
        "unused", 6, "((h * h) / (h * h) at line 5 is 1)"),
    "h_homogeneous_min": (
        b"system h_homogeneous_min\nformat fp64\nround rne\nstate x\n"
        b"next x=x+(min(h,2*h))\nstep map, h=1/8\n",
        "cfb4d4183b6e967dbf0053ebd4e5da9d2744f08288f1addda5402cd5ee708e54",
        "h-nonlinear", 5, "min of a constant that changes with h's size"),
    "h_homogeneous_select": (
        b"system h_homogeneous_select\nformat fp64\nround rne\nstate x\n"
        b"next x=x+(select(h<0,2*h,h))\nstep map, h=1/8\n",
        "994632733f6fb23af9a7e47c8de08951337912465ff2b88a8e96cae085b166b5",
        "h-nonlinear", 5,
        "a comparison of a constant that changes with h's size"),
}


@pytest.mark.parametrize("name", list(INVESTIGATIONS))
def test_the_suites_investigation_sources(name):
    data, digest, want, line, words = INVESTIGATIONS[name]
    assert hashlib.sha256(data).hexdigest() == digest
    r = refused(data)
    assert (r.name, r.line) == (want, line), str(r)
    assert words in r.sentence


# ---- the h sentences, true of every input that reaches them ---------------

MIN_FAMILY = {   # the body, and how the sentence names the operation
    "min(h, 2*h), h at h > 0": ("next x = x + min(h, 2*h)", "min"),
    "select(h < 0, 2*h, h), fixed by h's sign": (
        "next x = x + select(h < 0, 2*h, h)", "a comparison"),
    "select(1, 2*h, h), 2*h": ("next x = x + select(1, 2*h, h)", "select"),
    "max(h, 1)": ("next x = x + max(h, 1)", "max"),
    "minnum(2*h, h)": ("next x = x + minnum(2*h, h)", "minnum"),
    "maxnum(h, 3*h)": ("next x = x + maxnum(h, 3*h)", "maxnum"),
    "h <= 2*h": ("next x = x + (h <= 2*h)", "a comparison"),
    "h == h": ("next x = x + (h == h)", "a comparison"),
}


@pytest.mark.parametrize("name", list(MIN_FAMILY))
def test_the_min_family_sentence_is_the_rule(name):
    """It said "<op> of a constant that depends on h is not a fixed
    multiple of h, and would not halve with it": untrue of min(h, 2*h),
    h at h > 0, and of h < 0, fixed by h's sign (the suite's finding 2).
    The refusal stays; the sentence is the rule applied."""
    body, what = MIN_FAMILY[name]
    r = refused(src(body))
    assert (r.name, r.line) == ("h-nonlinear", 4)
    assert r.sentence == (
        f"{what} of a constant that changes with h's size is refused, even "
        f"where, at h's sign, the result would be fixed or a multiple of h: "
        f"a constant is a rational or a rational multiple of h, and h's sign "
        f"enters one only through copysign and abs")


def test_the_sum_sentence_claims_no_halving():
    """"does not halve with h" was untrue of 2 + h*h at h = 2: 6 there, 3 at
    h = 1. The sum is refused where it is made, whatever surrounds it, so
    (h + 1) - 1 is refused although its value is h; a product or quotient
    of powers is not, so (h*h)/h is h (a control above)."""
    value = (lambda h: 2 + h * h)
    assert value(Fraction(1)) == value(Fraction(2)) / 2
    for body, step in (("next x = x + (2 + h*h)", "step map, h = 2"),
                       ("next x = x + ((h + 1) - 1)", "step map, h = 1/8"),
                       ("next x = x + (h - 1/h)", "step map, h = 1/8")):
        r = refused(src(body, step=step))
        assert (r.name, r.line) == ("h-nonlinear", 4)
        assert r.sentence == ("a sum of h and a constant, or of different "
                              "powers of h, is neither a rational nor a "
                              "rational multiple of h, which a constant is")


def test_the_leaf_sentence_is_kept_and_true():
    """c h^d halves with h only where d is 1, so "does not halve with h" is
    true of every power the leaf refuses (h*h, 1/h, h*h*h)."""
    for body, d in (("x * (h*h)", 2), ("x * (1/h)", -1), ("x * (h*h*h)", 3)):
        r = refused(src(f"next x = {body}"))
        assert r.name == "h-nonlinear"
        assert f"a multiple of h^{d}, which does not halve with h" in r.sentence
        h = Fraction(1, 8)
        assert (h / 2) ** d != h ** d / 2


def test_the_h_scope_sentence_claims_no_motion():
    """"the right-hand side would move with it" was untrue of (h/h) * x and
    of (c/c) * x with const c = h: x * 1 does not move. Both are refused
    (h read directly, a const that scales read at all), by the rule."""
    for extra, body, sentence in (
            ((), "d/dt x = (h/h) * x",
             "a flow's equations cannot read h, whatever it folds to: a "
             "step-halving run halves h, and a right-hand side must not move "
             "with it (a const whose value does not change with h's size, "
             "such as const c = h/h, is a plain rational they may read)"),
            (("const c = h",), "d/dt x = (c/c) * x",
             "a flow's equations cannot read the const c, whose value changes "
             "with h's size: a step-halving run halves h, and a right-hand "
             "side must not move with it")):
        r = refused(src(*extra, body, step="step euler, h = 1/8"))
        assert (r.name, r.sentence) == ("h-scope", sentence), str(r)
    # a default's sentence is true of every input and kept
    r = refused(src("param p = h/h", "next x = x * p"))
    assert r.sentence == ("a default cannot read h (h): a step-halving run "
                          "halves h, and the default would not follow it")


# ---- the canonical form nests at most 100: `too-deep` --------------------------

def negmul(k, var="x", factor="y"):
    """-(-(...) * y) * y, k levels: the canonical form writes each negation
    used as a multiplicand in parentheses, (-a) * y, so 2k - 1 deep."""
    e = var
    for _ in range(k):
        e = f"-({e}) * {factor}"
    return e


def chain(kind, n):
    """An unnamed product, or min chain, of x0 .. x(n-1), with `tangent v`:
    the equation for x0 is line 5."""
    names = [f"x{i}" for i in range(n)]
    if kind == "mul":
        e = " * ".join(names)
    else:
        e = names[0]
        for nm in names[1:]:
            e = f"min({e}, {nm})"
    return NL.join(["system c", "format fp64", "state " + ", ".join(names),
                    "tangent v", f"next x0 = {e}"]
                   + [f"next {x} = {x}" for x in names[1:]]
                   + ["step map"]) + NL


def nested(d, inner="x"):
    e = inner
    for _ in range(d):
        e = f"abs({e})"
    return e


def deep(text, want_line, desc, depth):
    """Refused too-deep at `want_line`, naming `desc` and `depth`."""
    r = refused(text)
    assert (r.name, r.line) == ("too-deep", want_line), str(r)
    assert r.sentence == (
        f"the canonical form would write {desc} {depth} deep, and the "
        f"language reads nesting {MAX} deep at most: name parts of this "
        f"line's expression with lets, which the canonical form keeps as "
        f"names, so that its depth is bounded")


def accepted(text, depth):
    """Accepted, read back, and its canonical form `depth` deep."""
    g = graph(text)
    canon = reads_back(g)
    assert nest(canon) == depth
    return g


SV = "step stormer-verlet, h = 1/8, q = (x), p = (p)"
BOUNDARIES = {   # name: (accepted source and its depth, refused source and
    #               its line, the line's description, its depth)
    "a negation used as a multiplicand, k = 50 and 51": (
        (src(f"next x = {negmul(50)}", "next y = y", head="state x, y",
             step="step map"), 99),
        (src(f"next x = {negmul(51)}", "next y = y", head="state x, y",
             step="step map"), 4, "next x", 101)),
    "the same in a let": (
        (src(f"let r = {negmul(50)}", "next x = r", "next y = y",
             head="state x, y", step="step map"), 99),
        (src(f"let r = {negmul(51)}", "next x = r", "next y = y",
             head="state x, y", step="step map"), 4, "let r", 101)),
    "an array's equation, its index one level more": (
        (src(f"next x[i] = {negmul(49, 'x[i]')}", "next y = y",
             head="state x[2], y", step="step map"), 98),
        (src(f"next x[i] = {negmul(51, 'x[i]')}", "next y = y",
             head="state x[2], y", step="step map"), 4, "next x[0]", 102)),
    "an unnamed product's tangent, 101 and 102 terms": (
        (chain("mul", 101), 100),
        (chain("mul", 102), 5, "next v.x0, the tangent of next x0,", 101)),
    "a min chain's tangent, nesting 99 and 100": (
        (chain("min", 100), 100),
        (chain("min", 101), 5, "next v.x0, the tangent of next x0,", 101)),
    "euler's step around a right-hand side nesting 99 and 100": (
        (src(f"d/dt x = {nested(99)}", step="step euler, h = 1/8"), 100),
        (src(f"d/dt x = {nested(100)}", step="step euler, h = 1/8"), 4,
         "next x, in its expansion block,", 101)),
    "stormer-verlet's drift, the same": (
        (src(f"d/dt x = {nested(99, 'p')}", "d/dt p = -x",
             head="state x, p", step=SV), 100),
        (src(f"d/dt x = {nested(100, 'p')}", "d/dt p = -x",
             head="state x, p", step=SV), 4,
         "let Q1.x, in its expansion block,", 101)),
    # verifier-VD2's cases/compound101.cftl: a compound constant as an
    # operand is written in parentheses, x * (1/3) - one of the roads the
    # rule needs no list of
    "a compound constant, its own parentheses": (
        (src("const k = 1/3", "next x = " + nested(99, "x * k"),
             step="step map"), 100),
        (src("const k = 1/3", "next x = " + nested(100, "x * k"),
             step="step map"), 5, "next x", 101)),
}


@pytest.mark.parametrize("name", list(BOUNDARIES))
def test_the_canonical_form_at_the_limit(name):
    """Each was accepted and stopped cftc at exit 70 one step past the
    boundary (verifier-VL3, D2's probe, measured on 3fa0319)."""
    (good, depth), (bad, line, desc, bad_depth) = BOUNDARIES[name]
    accepted(good, depth)
    deep(bad, line, desc, bad_depth)


def test_rk4_and_a_map_at_the_parsers_own_limit_are_accepted():
    """rk4 writes a stage as a let (k1.x = <rhs>), a map writes its
    equation as written: neither nests past its source, 100 deep."""
    accepted(src(f"d/dt x = {nested(100)}", step="step rk4, h = 1/8"), 100)
    accepted(src(f"next x = {nested(100)}", step="step map"), 100)


def p_chain(k, var):
    """-(-(-x * p) * p) * p: a negation multiplicand chain written k - 1
    deep, whose canonical form is 2k - 1 deep - and so is its tangent's,
    since p, a param, has none."""
    e = var
    for _ in range(k):
        e = f"-{e} * p" if e == var else f"-({e}) * p"
    return e


def test_a_written_tangent_is_named_at_its_own_line():
    """Where the source writes a tangent equation or tangent let, a tangent
    line too deep is refused at that line; where it does not, at the
    equation or let it is the tangent of."""
    head = ("system w", "format fp64", "state x", "tangent v",
            "param p = 1/3")
    eqs = [f"next v.x = {p_chain(51, 'v.x')}", f"next x = {p_chain(51, 'x')}"]
    for order, line, desc in ((eqs, 6, "next v.x, the tangent of next x,"),
                              (eqs[::-1], 6, "next x")):
        deep(NL.join(head + tuple(order) + ("step map",)) + NL, line, desc,
             101)
    lets = (f"let v.r = {p_chain(51, 'v.x')}", f"let r = {p_chain(51, 'x')}",
            "d/dt x = r", "d/dt v.x = v.r", "step rk4, h = 1/8")
    deep(NL.join(head + lets) + NL, 6, "let v.r, the tangent of let r,", 101)
    unwritten = (lets[1], "d/dt x = r", "step rk4, h = 1/8")
    deep(NL.join(head + unwritten) + NL, 6, "let r", 101)
    # at 50 levels, written and not, all of it reads back
    for k_text in (NL.join(head + (f"next v.x = {p_chain(50, 'v.x')}",
                                   f"next x = {p_chain(50, 'x')}",
                                   "step map")) + NL,):
        accepted(k_text, 99)


def test_the_rule_refuses_exactly_what_would_not_read_back(monkeypatch):
    """With the rule switched off in a copy of the check, each source it
    refuses gives a graph whose canonical form the parser refuses
    `too-deep`, at the depth the sentence named: the rule refuses nothing
    whose canonical form reads back (a conservative bound would be a wrong
    answer)."""
    cases = [b[1] for b in BOUNDARIES.values()]
    named = []
    for text, _line, _desc, depth in cases:
        r = refused(text)
        named.append(depth)
        assert f" {depth} deep," in r.sentence
    monkeypatch.setattr(lang_check.Checker, "canonical_nesting",
                        lambda self, graph: None)
    for (text, *_rest), depth in zip(cases, named):
        g = compile_(text)
        canon = lang.render_canonical(g)
        assert nest(canon) == depth
        with pytest.raises(lang.Refusal) as info:
            compile_(canon)
        assert info.value.name == "too-deep"


def test_neither_rule_renders_or_reads_back(monkeypatch):
    """The checker never writes the canonical form to decide: with the
    renderer made to fail, every reference, every control and every
    boundary case gets the verdict it gets with it. The read-back stays
    cftc's internal check, and a renderer's defect stays loud there
    (test_cftc.py's test_a_renderer_fault_is_an_internal_error)."""
    def broken(_g):
        raise AssertionError("the checker rendered the canonical form")
    # the min chain's cases left out for time: the mul chain's are the
    # tangent's, and every other road is here
    cheap = [b for name, b in BOUNDARIES.items() if "min chain" not in name]
    texts = [p.read_bytes() for p in sorted(SYSTEMS.glob("*.cftl"))]
    texts += list(CONTROLS.values())
    texts += [b[0][0] for b in cheap]
    want = [graph(t).digest() for t in texts]
    bad = [b[1][0] for b in cheap] + \
        [src(*body) for body, _use in FOLDED.values()]
    names = [refused(t).name for t in bad]
    monkeypatch.setattr(render, "render_canonical", broken)
    monkeypatch.setattr(render, "_render_canonical", broken)
    monkeypatch.setattr(lang, "render_canonical", broken)
    assert [compile_(t).digest() for t in texts] == want
    assert [refused(t).name for t in bad] == names


# ---- the measure is the lexer's, line by line --------------------------------

def measured(g):
    """{a line's left side: its depth} from nesting.lines, every vector."""
    return {code: depth for code, depth, *_ in
            nesting.lines(g, every_vector=True)}


def counted(g):
    """{a line's left side: its depth} from render_canonical's own text,
    each let, d/dt and next line counted as the lexer counts it."""
    out = {}
    for ln in lang.render_canonical(g).splitlines():
        code = ln.split(";", 1)[0].strip()
        if code.startswith(("let ", "next ", "d/dt ")) and " = " in code:
            out[code.split(" = ", 1)[0]] = nest(ln)
    return out


_LEAVES_LIT = ["2", "3", "0.5", "(1/3)", "(-2)", "-3", "0x1.8p+1", "(2/7)"]


def _expr(rng, leaves, depth):
    """A random expression, chains mixing kinds unparenthesised and
    negations as operands of every operator - the shapes that decide where
    the canonical form puts its parentheses."""
    if depth <= 0 or rng.random() < 0.25:
        return rng.choice(leaves if rng.random() < 0.8 else _LEAVES_LIT)

    def a():
        return _expr(rng, leaves, depth - 1)
    k = rng.randrange(17)
    if k == 14:                         # L4: `/` is a product's kind
        return f"{a()} * {a()} / {a()}"
    if k == 15:
        return f"{a()} / {a()} * {a()} - -{a()} / {a()}"
    if k == 16:
        return f"sqrt({a()})"
    if k == 0:
        return f"{a()} + {a()} - {a()}"
    if k == 1:
        return f"{a()} * {a()} + {a()}"
    if k == 2:
        return f"({a()} - {a()}) * {a()}"
    if k == 3:
        return f"-{a()} * {a()}"
    if k == 4:
        return f"-({a()}) - {a()}"
    if k == 5:
        return f"- -({a()})"
    if k == 6:
        return f"fma({a()}, {a()}, {a()})"
    if k == 7:
        return f"abs({a()})"
    if k == 8:
        return f"{rng.choice(['min', 'max', 'minnum', 'maxnum', 'copysign'])}" \
               f"({a()}, {a()})"
    if k == 9:
        return f"({a()} {rng.choice(['<', '<=', '>', '>=', '=='])} {a()})"
    if k == 10:
        return f"select({a()}, {a()}, {a()})"
    if k == 11:
        return f"({a()} < {a()}) * {a()} + ({a()} == {a()})"
    if k == 12:
        return f"{a()} * {rng.choice(_LEAVES_LIT)}"
    return f"({a()})"


def random_system(rng, k):
    """A random system of any integrator, with lets, an array, params, lane
    params and tangent vectors - every line the canonical form can write."""
    integ = rng.choice(["map", "maph", "rk4", "euler", "stormer-verlet"])
    lines = [f"system r{k}", f"format {rng.choice(['fp32', 'fp64', 'fp256'])}"]
    tangents = rng.choice(["", "", "v", "v, w"])
    if integ == "stormer-verlet":
        lines.append("state q, m, a[2] cyclic")
        if tangents:
            lines.append(f"tangent {tangents}")
        # positions read momenta only, and momenta positions only
        lines += ["param k = 3/2", "lane param c = 1/3",
                  f"d/dt q = {_expr(rng, ['m', 'k', 'c'], 3)}",
                  f"d/dt a[i] = {_expr(rng, ['m', 'c'], 2)}",
                  f"d/dt m = {_expr(rng, ['q', 'a[1]', 'k'], 3)} + k + c",
                  "step stormer-verlet, h = 1/8, q = (q, a), p = (m)"]
        return NL.join(lines) + NL
    word = "next" if integ.startswith("map") else "d/dt"
    lines.append("state x, y, a[3]")
    if tangents:
        lines.append(f"tangent {tangents}")
    lines += ["param k = 3/2", "lane param c = 1/3"]
    leaves = ["x", "y", "a[1]", "k", "c"] + \
        (["h", "(h/2)", "(2*h)", "(-h)"] if integ == "maph" else [])
    lines.append(f"let r = {_expr(rng, leaves, 2)}")
    lines.append(f"let d[i] = {_expr(rng, ['a[i]', 'x'], 2)} for i in 0..2")
    lines.append(f"{word} x = {_expr(rng, leaves + ['r'], 4)} + r + k + c"
                 + (" + h" if integ == "maph" else ""))
    lines.append(f"{word} y = {_expr(rng, leaves + ['d[0]'], 3)} + d[2]")
    lines.append(f"{word} a[i] = {_expr(rng, ['a[i]', 'y'], 2)} + d[i]")
    lines.append({"map": "step map", "maph": "step map, h = 1/8",
                  "rk4": "step rk4, h = 1/8",
                  "euler": "step euler, h = 1/8"}[integ])
    return NL.join(lines) + NL


def test_the_measure_is_the_lexers_count_line_by_line():
    """nesting.lines against this file's count of render_canonical's text,
    on every committed source, the boundary cases and 150 random systems:
    the same lines, each the same depth."""
    graphs = [lang.load(p).graph for p in sorted(SYSTEMS.glob("*.cftl"))]
    graphs += [graph(b[0][0]) for b in BOUNDARIES.values()]
    graphs += [graph(t) for t in CONTROLS.values()]
    rng = random.Random("D2 nesting")
    made = refusals = 0
    integrators, tangents, deepest = set(), 0, 0
    while made < 150:
        text = random_system(rng, made + refusals)
        try:
            graphs.append(compile_(text))
            made += 1
        except lang.Refusal as r:
            # and since L4 a constant's root no rational carries, or a
            # constant over a constant zero
            assert r.name in ("constant-negative-zero", "h-nonlinear",
                              "irrational-constant",
                              "constant-division-by-zero"), f"{r}\n{text}"
            refusals += 1
    assert refusals < made
    for g in graphs:
        want = measured(g)
        assert want == counted(g), g.system
        integrators.add(g.integrator[0])
        tangents += bool(g.tangent)
        deepest = max(deepest, max(want.values()))
    assert integrators == {"map", "rk4", "euler", "stormer-verlet"}
    assert tangents and deepest == 100


# ---- chains of any length: a definition met deep, evaluated from the top ----

def letchain(kind, n):
    """A chain of n lets - `let a1 = x + y`, `let aj = a(j-1) + y`, or
    through a call, `abs(a(j-1)) + y` - read by x's equation, in a system
    of `kind`: map, euler, rk4 or sv (stormer-verlet), "+v" with `tangent
    v`, "call-" for the chain through a call (verifier-VD2's shapes)."""
    tan = kind.endswith("+v")
    base = kind[:-2] if tan else kind
    call = base.startswith("call-")
    base = base[5:] if call else base
    step = {"map": "step map", "euler": "step euler, h = 1/8",
            "rk4": "step rk4, h = 1/8",
            "sv": "step stormer-verlet, h = 1/8, q = (x), p = (y)"}[base]
    nxt = "abs(a{p}) + y" if call else "a{p} + y"
    lines = ["system s", "format fp64", "state x, y"]
    lines += ["tangent v"] if tan else []
    lines.append("let a1 = " + ("y + y" if base == "sv" else "x + y"))
    lines += [f"let a{j} = " + nxt.format(p=j - 1) for j in range(2, n + 1)]
    w = "next" if base == "map" else "d/dt"
    lines += [f"{w} x = a{n}", f"{w} y = " + ("-x" if base == "sv" else "y"),
              step]
    return NL.join(lines) + NL


# Each at the length where, at Python's own limit and from a script, the
# checker or the read-back of its canonical form stopped (measured on
# 87c4df9: verifier-VD2's table and D2's): rk4 read back to 80 lets,
# stormer-verlet 122, rk4 + v 64, stormer-verlet + v 97, euler + v and
# map + v 197, and every kind was accepted to 246 or 247; a chain through a
# call to 164 on Python 3.12 and 141 on 3.10, the same source taking two
# verdicts. And far past them.
CHAINS = [("rk4", 80), ("rk4", 81), ("rk4", 246), ("rk4", 247),
          ("sv", 123), ("rk4+v", 65), ("sv+v", 98), ("euler+v", 198),
          ("map+v", 198), ("map", 247), ("euler", 247), ("call-map", 142),
          ("call-map", 165), ("call-rk4", 150), ("rk4", 2500),
          ("map+v", 2500)]


@pytest.mark.parametrize("kind,n", CHAINS)
def test_a_chain_of_lets_is_any_length_and_reads_back(kind, n):
    """Each but rk4's 80 - the last whose canonical form read back - was,
    on Python 3.10 or 3.12, refused too-deep by Python's recursion limit
    or accepted with a canonical form that did not read back, cftc's exit
    70. Each is accepted now on every Python, and reads back (D2; Logan,
    2026-10-01: no limit on a chain)."""
    g = graph(letchain(kind, n))
    reads_back(g)
    assert g.op_counts("step")["add"] >= n


def letcycle(c, entry):
    """Lets a1 .. a{c} in a cycle - a1 reads a{c} - and x reading a{entry}.
    a{j} is line 3 + j."""
    lines = ["system cy", "format fp64", "state x, y", f"let a1 = a{c} + y"]
    lines += [f"let a{j} = a{j - 1} + y" for j in range(2, c + 1)]
    lines += [f"next x = a{entry}", "next y = y", "step map"]
    return NL.join(lines) + NL


@pytest.mark.parametrize("c", [3, 300, 1200])
def test_a_cycle_of_any_length_is_named(c):
    """A cycle of lets longer than Python's limit was refused too-deep; it
    is `cycle` now, naming the let the recursion re-enters at the reference
    that re-enters it, as a short one always was."""
    for entry in sorted({1, c // 2 or 1, c}):
        r = refused(letcycle(c, entry))
        closer = entry + 1 if entry < c else 1      # the let that reads it
        assert (r.name, r.line, r.sentence) == (
            "cycle", 3 + closer, f"a{entry} depends on itself"), str(r)


def test_a_cycle_of_consts_names_its_path():
    for c in (3, 400):
        lines = ["system cc", "format fp64", "state x",
                 f"const c1 = c{c} + 1"]
        lines += [f"const c{j} = c{j - 1} + 1" for j in range(2, c + 1)]
        r = refused(NL.join(lines + ["next x = x * c1", "step map"]) + NL)
        path = ", ".join(["c1"] + [f"c{j}" for j in range(c, 1, -1)] + ["c1"])
        assert (r.name, r.line, r.sentence) == (
            "cycle", 5, f"c1 depends on itself: {path}")


def test_the_suites_deep_let_chain_is_accepted():
    """The challenge suite's cases/refuse/deep_let_chain.cftl, rebuilt here
    and held to its catalogued SHA-256: 10,001 lets, expected too-deep by
    the suite, as LANGUAGE.md stood ("long chains of lets ... held to
    Python's own recursion limit"). Accepted now, and read back."""
    lines = ["system deep_let_chain", "format fp64", "round rne", "state x",
             "let a0=x"] + [f"let a{j}=a{j - 1}+x" for j in range(1, 10001)]
    data = (NL.join(lines + ["next x=a10000", "step map"]) + NL).encode()
    assert hashlib.sha256(data).hexdigest() == \
        "e425ceafbaf931604703b0a8ba33a7e73d8bd4b5fab80f29a2897422ca9106ec"
    g = compile_(data)
    assert g.op_counts("step") == {"add": 10000}
    reads_back(g)


def _outcome(text):
    try:
        g = compile_(text)
    except lang.Refusal as r:
        return ("refused", r.name, r.line, r.sentence)
    return ("accepted", g.to_bytes())


def _far_from_the_limit(fn):
    """fn() in a thread with a 255 MB stack (the largest Windows takes) and
    Python's recursion limit at 1,000,000: the recursion with no limit in
    reach. Restores both."""
    box = []

    def run():
        try:
            box.append(("value", fn()))
        except BaseException as e:            # noqa: BLE001
            box.append(("error", e))
    size = threading.stack_size(255 * 1024 * 1024)
    limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(1_000_000)
        t = threading.Thread(target=run)
        t.start()
        t.join()
    finally:
        sys.setrecursionlimit(limit)
        threading.stack_size(size)
    kind, value = box[0]
    if kind == "error":
        raise value
    return value


EXACT = [letchain(k, 700) for k in ("map", "rk4", "sv", "rk4+v", "map+v",
                                    "call-map")]
EXACT += [letcycle(800, 400), letcycle(800, 800)]
EXACT += [NL.join(["system cc", "format fp64", "state x", "const c1 = 1/7"]
                  + [f"const c{j} = c{j - 1} + 1" for j in range(2, 901)]
                  + ["next x = x * c900", "step map"]) + NL,
          NL.join(["system ac", "format fp64", "state x[900], y",
                   "let d[0] = y", "let d[i] = d[i - 1] + y for i in 1..899",
                   "next x[i] = d[i]", "next y = y", "step map"]) + NL,
          NL.join(["system cb", "format fp64", "state x, y", "let a1 = x + y"]
                  + [f"let a{j} = a{j - 1} + y" for j in range(2, 595)]
                  + ["let a595 = a594 + a700"]
                  + [f"let a{j} = a{j - 1} + y" for j in range(596, 700)]
                  + ["let a700 = a699 + a595", "next x = a700", "next y = y",
                     "step map"]) + NL,
          # a fault met only after the deep read returns; and a fault in a
          # let's prefix, before its read, with another deeper down that the
          # recursion never reaches - so neither may the deferral
          NL.join(["system f", "format fp64", "state x, y", "let a1 = x + y"]
                  + [f"let a{j} = a{j - 1} + y" for j in range(2, 700)]
                  + ["let a700 = a699 * 1e400", "next x = a700", "next y = y",
                     "step map"]) + NL,
          # (the prefix's fault was `y / 0`, runtime-division, until L4
          # made a run-time division an operation, 2026-10-02: a constant
          # over a constant zero is a fault of the same place and kind)
          NL.join(["system f", "format fp64", "state x, y",
                   "let a1 = x * 1e400"]
                  + [f"let a{j} = a{j - 1} + y" for j in range(2, 350)]
                  + ["let a350 = (y * (1/0)) + a349"]
                  + [f"let a{j} = a{j - 1} + y" for j in range(351, 701)]
                  + ["next x = a700", "next y = y", "step map"]) + NL]


def test_a_definition_met_deep_is_the_recursion(monkeypatch):
    """The checker sets a definition met deep aside and evaluates it from
    the top (check.py, BUDGET). Held to the recursion itself, run with the
    budget out of reach and Python's limit far away: with the budget as
    shipped, and forced to 3 frames - a definition set aside at nearly
    every read - every source gets the same graph, byte for byte, or the
    same refusal, name, line and sentence: a fault after the deep read and
    one before it, a cycle's named let, a const chain, a let array's chain."""
    shipped = lang_check.BUDGET
    monkeypatch.setattr(lang_check, "BUDGET", 10 ** 9)
    oracle = _far_from_the_limit(lambda: [_outcome(t) for t in EXACT])
    assert [o[0] for o in oracle].count("accepted") == 8
    assert [o[1:3] for o in oracle if o[0] == "refused"] == \
        [("cycle", 404), ("cycle", 4), ("cycle", 598),
         ("constant-overflow", 703), ("constant-division-by-zero", 353)]
    for budget in (shipped, 3):
        monkeypatch.setattr(lang_check, "BUDGET", budget)
        assert [_outcome(t) for t in EXACT] == oracle, budget


def test_the_verdict_is_the_same_from_a_deep_caller():
    """The verdict once moved with the caller's own stack: a 230-let map
    accepted from a script was refused 100 frames down. Called 300 frames
    deeper, a 700-let chain and rk4 with 81 lets get the graph they get from
    here, and read back there."""
    def down(k, fn):
        return fn() if k == 0 else down(k - 1, fn)
    for text in (letchain("map", 700), letchain("rk4", 81)):
        g = down(300, lambda: compile_(text))
        assert g.to_bytes() == graph(text).to_bytes()
        canon = lang.render_canonical(g)
        assert down(300, lambda: compile_(canon)).to_bytes() == g.to_bytes()


def test_a_default_reading_a_folded_const_is_named():
    """h read only through a param's or a lane param's default was refused
    `unused` naming no use: a default is evaluated outside the step
    (verifier-VD2's cases/default_fold.cftl). Its fold is named now."""
    for decl in ("param p = c", "lane param p = c"):
        r = refused(src("const c = h/h", decl, "next x = x * p"))
        assert (r.name, r.line) == ("unused", 7)
        assert "(h / h at line 4 is 1); write the constant," in r.sentence
