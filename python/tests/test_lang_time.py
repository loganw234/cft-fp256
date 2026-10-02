# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Time in the language: docs/LANGUAGE.md's section "Time", every figure
it states computed through the templates by the reference interpreter and
compared, so that a change in a template, in the interpreter or in the
section fails here by name (parcel T1, 2026-10-02).

  t in the state       t is a name; undeclared it is time-dependence; what
                       each template makes of d/dt t = 1, from the
                       canonical form
  a dyadic step        h = 1/64 keeps t exact at every step to 10^4 under
                       rne; at fp64, euler and stormer-verlet under every
                       attribute, rk4 under rmm, rk4's directed figures,
                       and h = 3/64
  drift otherwise      h = 1/100: the section's table, rk4 against euler at
                       every step, fp128's rows against fp64's and h = 1/19,
                       the directed attributes and rmm at fp64
  the step counter     the refusals; an exact count at every step under rne
                       (and rmm at fp64); the directed attributes; the limit
                       at fp32; a step-halving run
  t from the counter   one rounding; each stage's count and time inside rk4,
                       the midpoint under stormer-verlet; the exact residual
  forcing              sin refused today; the rotation's table, its
                       rounding's share and its exact factor, the phase,
                       w = 3/10; the forced oscillator against its exact
                       solution; every source the section shows compiles

Each figure is read from the section's own text - its tables parsed, its
sentences matched - and computed here, so the document and the
measurement cannot part. An ulp count is the encoding of t less the
encoding of RN(n h), the time rounded once to nearest: the signed number
of floats between them (every value here is positive).
"""

import math
import re
import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from functools import lru_cache
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE.parent))

from cft_golden import FORMATS, lang  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.lang import check as lang_check  # noqa: E402
from cft_golden.lang import constants as C  # noqa: E402
from cft_golden.lang import interp  # noqa: E402

F = Fraction
DOC = REPO / "docs" / "LANGUAGE.md"
N = 10_000
MARKS = (100, 1_000, 10_000)
FMTS = ("fp32", "fp64", "fp128", "fp256")
ATTRS = ("rne", "rtz", "rdn", "rup", "rmm")
DIRECTED = ("rtz", "rdn", "rup")
SV = "stormer-verlet"
INTEGRATORS = ("rk4", "euler", SV)


# ---- the section ----------------------------------------------------------

@lru_cache(maxsize=None)
def section():
    text = DOC.read_text(encoding="utf-8")
    return text.split("\n## Time\n", 1)[1].split("\n## ", 1)[0]


def said(phrase):
    """True when the section says `phrase`, line breaks and indents aside."""
    return " ".join(phrase.split()) in " ".join(section().split())


def signed(n):
    return f"{n:+,}"


def sci(x):
    return f"{float(x):+.4e}"


def blocks():
    """The section's code blocks, dedented."""
    out = []
    for m in re.finditer(r"^( *)```\n(.*?)^\1```$", section(), re.M | re.S):
        pad = len(m.group(1))
        out.append("".join(ln[pad:] + "\n"
                           for ln in m.group(2).splitlines()))
    return out


def block(first):
    found = [b for b in blocks() if b.startswith(first)]
    assert len(found) == 1, first
    return found[0]


def table(after, rows):
    """The cells of the section's table under the heading line `after`,
    {row label: [cell, ...]} for each label in `rows`."""
    text = section().split(after, 1)[1]
    out = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] in rows:
            out[cells[0]] = cells[1:]
        if out and not line.startswith("|"):
            break
    assert set(out) == set(rows), (set(rows) - set(out))
    return out


# ---- running systems ------------------------------------------------------

def compile_(text):
    return lang.compile_text(text, "time.cftl").graph


# The steps whose t the section reads; at the others a clock only counts.
T_STEPS = ("1/64", "1/100", "3/64")


def clock(fmt, rnd, integ, h, rate):
    """A step counter at `rate`, h's reciprocal written as a number, with
    t carried in the state beside it where the section reads t: under
    stormer-verlet t and the counter kq are positions and the counter kp
    the momentum."""
    head = f"system clock\nformat {fmt}\nround {rnd}\n"
    t = h in T_STEPS
    if integ == SV:
        return head + (f"state {'t, ' if t else ''}kq, kp\n"
                       f"{'d/dt t = 1' if t else ''}\nd/dt kq = {rate}\n"
                       f"d/dt kp = {rate}\nstep {SV}, h = {h}, "
                       f"q = ({'t, ' if t else ''}kq), p = (kp)\n")
    return head + (f"state {'t, ' if t else ''}k\n"
                   f"{'d/dt t = 1' if t else ''}\nd/dt k = {rate}\n"
                   f"step {integ}, h = {h}\n")


def history(fmt, rnd, integ, h, rate, steps=N, run_h=None):
    """The clock's state at every step 0..steps, from 0: a tuple of state
    tuples (t first where it has one, then the counters). One run for
    every call with the same arguments, however they are spelled."""
    return _history(fmt, rnd, integ, h, str(rate), steps, run_h)


@lru_cache(maxsize=None)
def _history(fmt, rnd, integ, h, rate, steps, run_h):
    g = compile_(clock(fmt, rnd, integ, h, rate))
    r = lang.run(g, [[0] * g.n_state], steps, at=range(steps + 1), h=run_h)
    return tuple(tuple(r.at[s][0][0]) for s in range(steps + 1))


def rn(fmt, value):
    """value rounded once to nearest, even: its encoding."""
    return C.round_once(FORMATS[fmt], sf.RND_RNE, value)[0]


def rn_steps(fmt, h, steps=N):
    """RN(n h) for n = 0..steps."""
    return _rn_steps(fmt, F(h), steps)


@lru_cache(maxsize=None)
def _rn_steps(fmt, h, steps):
    return tuple(rn(fmt, n * h) for n in range(steps + 1))


def column(hist, i):
    return tuple(st[i] for st in hist)


def counters(integ, h):
    """The counter columns of a clock under each integrator."""
    first = 1 if h in T_STEPS else 0
    return (first, first + 1) if integ == SV else (first,)


def ulps(fmt, bits, value):
    return bits - rn(fmt, value)


def labelled(graph, state, steps, labels, lane=None):
    """Each step's values of the step graph's nodes labelled `labels`,
    evaluated as lang.run evaluates them - every node in order by the
    interpreter's own table of golden functions, the slots laid out as it
    lays them out: (states at each step 0..steps, {label: [value at each
    step 0..steps-1]})."""
    fns = interp._ops(graph.fmt, graph.rnd)
    n, m = graph.n_state, len(graph.lane)
    pbits = [p[2] for p in graph.param]
    cbits = [c[2] for c in graph.const]
    base = {"s": 0, "l": n, "p": n + m, "c": n + m + len(pbits)}
    nbase = base["c"] + len(cbits)

    def slot(ref):
        i = int(ref[1:])
        return nbase + i if ref[0] == "n" else base[ref[0]] + i
    seen = {lab: [] for lab in labels}
    prog = [(fns[op], tuple(slot(a) for a in args), seen.get(label))
            for op, args, label in graph.step.nodes]
    outs = [slot(o) for o in graph.step.out]
    v = [0] * (nbase + len(prog))
    v[0:n] = state
    v[n:n + m] = lane if lane is not None else [b for _n, _d, b in graph.lane]
    v[n + m:base["c"]] = pbits
    v[base["c"]:nbase] = cbits
    states = [tuple(state)]
    for _ in range(steps):
        k = nbase
        for fn, args, record in prog:
            if len(args) == 3:
                res = fn(v[args[0]], v[args[1]], v[args[2]])[0]
            elif len(args) == 2:
                res = fn(v[args[0]], v[args[1]])[0]
            else:
                res = fn(v[args[0]])[0]
            v[k] = res
            if record is not None:
                record.append(res)
            k += 1
        v[0:n] = [v[o] for o in outs]
        states.append(tuple(v[0:n]))
    return states, seen


def held_to_lang_run(graph, state, lane=None, steps=200):
    """The evaluator above gives lang.run's states at every step."""
    mine, _ = labelled(graph, state, steps, (), lane)
    r = lang.run(graph, [list(state)], steps, at=range(steps + 1),
                 lane_params=None if lane is None else [list(lane)])
    assert [tuple(r.at[s][0][0]) for s in range(steps + 1)] == mine


# ---- t in the state -------------------------------------------------------

def test_t_is_a_name_like_any_other():
    """t is no reserved name: declared as state, a const or a param it is
    accepted; read and declared nowhere it is time-dependence, whose
    sentence is the advice the section follows."""
    assert "t" not in lang_check.RESERVED
    snippet = block("state t, x")
    for integ in ("rk4", "euler"):
        compile_(f"system s\nformat fp64\n{snippet}step {integ}, h = 1/100\n")
    compile_("system s\nformat fp64\nstate x\nconst t = 1/2\nd/dt x = t * x\n"
             "step rk4, h = 1/100\n")
    compile_("system s\nformat fp64\nstate x\nparam t = 0\nd/dt x = t * x\n"
             "step rk4, h = 1/100\n")
    with pytest.raises(lang.Refusal) as info:
        compile_("system s\nformat fp64\nstate x\nd/dt x = t * x\n"
                 "step rk4, h = 1/100\n")
    assert (info.value.name, info.value.sentence) == (
        "time-dependence", "t is not declared, and v1 has no explicit time: "
        "carry it in the state (state t, d/dt t = 1)")
    # the precedent: a keyword refuses a value named after it, where it is
    # declared (reserved-name) and where it is read (syntax)
    for text, name in (
            ("state x, tangent\nnext x = x\nnext tangent = 1\n",
             "reserved-name"),
            ("state x\nnext x = x * tangent\n", "syntax")):
        with pytest.raises(lang.Refusal) as info:
            compile_(f"system s\nformat fp64\n{text}step map\n")
        assert info.value.name == name
    assert said("`reserved-name` where it declares t, as making `tangent` a "
                "keyword refused every value named `tangent`")


def expansion(text):
    g = compile_(text)
    can = lang.render_canonical(g)
    return can.split("\nexpansion\n", 1)[1].split("\nend\n", 1)[0]


def test_what_the_templates_make_of_t():
    """The canonical form's expansion of d/dt t = 1 under each template,
    as the section quotes it."""
    head = "system s\nformat fp64\n"
    rk4 = expansion(head + "state t, x\nd/dt t = 1\nd/dt x = fma(-t, x, 1)\n"
                    "step rk4, h = 1/100\n").splitlines()
    for line in ("let Y2.t = fma(h/2, 1, t)", "let Y3.t = fma(h/2, 1, t)",
                 "let Y4.t = fma(h, 1, t)", "next t = fma(h/6, 6, t)"):
        assert "  " + line in rk4
    assert said("`let Y2.t = fma(h/2, 1, t)`, Y3.t the same, `let Y4.t = "
                "fma(h, 1, t)` and `next t = fma(h/6, 6, t)`")
    euler = expansion(head + "state t, x\nd/dt t = 1\n"
                      "d/dt x = fma(-t, x, 1)\nstep euler, h = 1/100\n")
    assert "  next t = fma(h, 1, t)" in euler.splitlines()
    assert said("euler: `next t = fma(h, 1, t)`")
    sv = expansion(head + "state t, x, p\nd/dt t = 1\nd/dt x = p\n"
                   "d/dt p = fma(-t, x, 1)\nstep stormer-verlet, h = 1/100, "
                   "q = (t, x), p = (p)\n").splitlines()
    assert "  let Q1.t = fma(h/2, 1, t)" in sv
    assert "  next t = fma(h/2, 1, Q1.t)" in sv
    assert "  let P1.p = fma(h, fma(-Q1.t, Q1.x, 1), p)" in sv   # the force
    assert said("`let Q1.t = fma(h/2, 1, t)` and `next t = fma(h/2, 1, "
                "Q1.t)`, and the kick's force reads Q1.t")
    # among the momenta: kicked once by RN(h), and no force reads it
    svp = expansion(head + "state x, t\nd/dt x = t\nd/dt t = 1\n"
                    "step stormer-verlet, h = 1/100, q = (x), p = (t)\n")
    assert "  let P1.t = fma(h, 1, t)" in svp.splitlines()
    with pytest.raises(lang.Refusal) as info:
        compile_(head + "state x, t, p\nd/dt x = p\nd/dt t = 1\nd/dt p = t\n"
                 "step stormer-verlet, h = 1/100, q = (x), p = (t, p)\n")
    assert info.value.name == "verlet-not-separable"
    assert said("Among the momenta t is kicked once by RN(h), and no force "
                "can read it.")


# ---- a dyadic step ----------------------------------------------------------

@pytest.mark.parametrize("fmt", FMTS)
def test_a_dyadic_step_keeps_t_exact(fmt):
    """h = 1/64 under rne: t is n h at every step to 10^4, under every
    integrator."""
    exact = rn_steps(fmt, F(1, 64))
    for integ in INTEGRATORS:
        assert column(history(fmt, "rne", integ, "1/64", 64), 0) == exact, \
            integ
    assert said("With h = 1/64, t stayed exactly n h at every step to 10^4, "
                "under every integrator and at every format.")


def test_a_dyadic_step_under_the_other_attributes():
    """At fp64: euler and stormer-verlet stay exact under every attribute,
    rk4 under rmm only; rk4 parts from the first step under a directed
    one, by the section's figures. h = 3/64 keeps rk4's t and count exact
    under every attribute."""
    fmt, h = "fp64", F(1, 64)
    exact = rn_steps(fmt, h)
    for integ in ("euler", SV):
        for rnd in ATTRS:
            assert column(history(fmt, rnd, integ, "1/64", 64), 0) == exact, \
                (integ, rnd)
    assert column(history(fmt, "rmm", "rk4", "1/64", 64), 0) == exact
    figures = {}
    for rnd in DIRECTED:
        t = column(history(fmt, rnd, "rk4", "1/64", 64), 0)
        assert t[1] != exact[1], rnd                   # from the first step
        figures[rnd] = [ulps(fmt, t[n], n * h) for n in MARKS]
    a, b = figures["rdn"], figures["rup"]
    assert figures["rtz"] == a and max(a) < 0 < min(b)
    assert said("Under the other attributes, at fp64: - euler and "
                "stormer-verlet stayed exact under every one.")
    assert said("- rk4 stayed exact under rmm only.")
    assert said(f"falls behind under rtz and rdn, {signed(a[0])}, "
                f"{signed(a[1])} and {signed(a[2])} ulps after 10^2, "
                f"10^3 and 10^4 steps at fp64, and runs ahead under rup, "
                f"{signed(b[0])}, {signed(b[1])} and {signed(b[2])}")
    # h = 3/64: h/2 = 3/128 and h/6 = 1/128 are dyadic
    for rnd in ATTRS:
        hist = history(fmt, rnd, "rk4", "3/64", "64/3")
        assert column(hist, 0) == rn_steps(fmt, F(3, 64)), rnd
        assert column(hist, 1) == rn_steps(fmt, F(1)), rnd
    assert said("With h = 3/64, whose half and sixth are dyadic, rk4 keeps "
                "t exact under every attribute.")
    assert said("Under rk4 a step whose sixth is dyadic counts exactly under "
                "every attribute at fp64: h = 3/64, rate 64/3.")


# ---- drift otherwise --------------------------------------------------------

DRIFT_HEAD = "| format | rk4 and euler, n = 10^2 |"


@lru_cache(maxsize=None)
def apart(fmt):
    """The steps at which rk4's t and euler's differ, h = 1/100, rne."""
    rk4 = column(history(fmt, "rne", "rk4", "1/100", 100), 0)
    eul = column(history(fmt, "rne", "euler", "1/100", 100), 0)
    return tuple(n for n in range(N + 1) if rk4[n] != eul[n])


@pytest.mark.parametrize("fmt", FMTS)
def test_the_drift_table(fmt):
    """h = 1/100 under rne: the table's ulps at 10^2, 10^3 and 10^4 for
    rk4 and euler (equal at the marks) and stormer-verlet; rk4 and euler
    part at the steps the section counts, and meet again: the last step
    is equal, so every run of steps apart ends. At fp64 rmm's figures are
    rne's."""
    h = F(1, 100)
    row = table(DRIFT_HEAD, [fmt])[fmt]
    got = {}
    for integ in INTEGRATORS:
        t = column(history(fmt, "rne", integ, "1/100", 100), 0)
        got[integ] = [signed(ulps(fmt, t[n], n * h)) for n in MARKS]
        if fmt == "fp64":
            trm = column(history(fmt, "rmm", integ, "1/100", 100), 0)
            assert [trm[n] for n in MARKS] == [t[n] for n in MARKS], integ
    assert got["rk4"] == got["euler"]
    assert row == got["rk4"] + got[SV]
    assert N not in apart(fmt)
    count = {"fp32": 46, "fp64": 1, "fp128": 1, "fp256": 0}[fmt]
    assert len(apart(fmt)) == count
    if count == 1:
        assert apart(fmt) == (3,)
    assert said(f"round apart at {len(apart('fp32'))} of the 10^4 steps at "
                f"fp32, at one (the third) at fp64 and fp128, and at none at "
                f"fp256, meeting again each time")
    assert said("rmm's figures at fp64 are rne's.")


def order_of_two(q):
    while q % 2 == 0:
        q //= 2
    k, x = 1, 2 % q
    while x != 1:
        x, k = x * 2 % q, k + 1
    return k


def test_fp128_is_fp64_where_the_period_divides_sixty():
    """1/100 repeats every 20 bits and fp128 carries 60 more than fp64, so
    their ulps agree; 1/19 repeats every 18, and they differ."""
    assert (FORMATS["fp128"].prec - FORMATS["fp64"].prec,
            order_of_two(100), order_of_two(19)) == (60, 20, 18)
    rows = table(DRIFT_HEAD, ["fp64", "fp128"])
    assert rows["fp64"] == rows["fp128"]
    marks = {}
    for fmt in ("fp64", "fp128"):
        g = compile_(f"system t19\nformat {fmt}\nstate t\nd/dt t = 1\n"
                     f"step euler, h = 1/19\n")
        r = lang.run(g, [[0]], N, at=MARKS)
        marks[fmt] = [ulps(fmt, r.at[n][0][0][0], F(n, 19)) for n in MARKS]
    assert marks["fp64"] != marks["fp128"]
    assert said("In binary 1/100 repeats every 20 bits, and fp128 carries 60 "
                "bits more than fp64")
    assert said("At h = 1/19, which repeats every 18 bits, the two formats "
                "differ.")


def test_a_directed_attribute_drifts_one_way():
    """At fp64 after 10^4 steps of h = 1/100, rk4 and euler: rtz and rdn
    alike, below; rup above; by the section's figures."""
    h = F(1, 100)
    got = {}
    for rnd in DIRECTED:
        for integ in ("rk4", "euler"):
            t = column(history("fp64", rnd, integ, "1/100", 100), 0)
            got[rnd, integ] = ulps("fp64", t[N], N * h)
    assert len({got["rtz", i] for i in ("rk4", "euler")}
               | {got["rdn", i] for i in ("rk4", "euler")}) == 1
    assert got["rup", "rk4"] == got["rup", "euler"]
    assert got["rtz", "rk4"] < 0 < got["rup", "rk4"]
    assert said(f"rk4 and euler are {signed(got['rtz', 'rk4'])} ulps off "
                f"under rtz and rdn and {signed(got['rup', 'rk4'])} under rup")


# ---- the step counter -------------------------------------------------------

def test_a_flow_cannot_reach_h():
    """h's reciprocal cannot be written as 1/h, nor the time as k h: each
    is h-scope, with the sentence the section quotes."""
    head = "system s\nformat fp64\n"
    sources = [
        "state k\nd/dt k = 1/h\nstep rk4, h = 1/100\n",
        "state k, x\nparam t0 = 0\nd/dt k = 100\nlet t = fma(k, h, t0)\n"
        "d/dt x = t\nstep rk4, h = 1/100\n",
        "state k, x\nconst dt = h\nd/dt k = 100\nlet t = k * dt\n"
        "d/dt x = t\nstep rk4, h = 1/100\n",
        "state k\nconst c = 1/h\nd/dt k = c\nstep rk4, h = 1/100\n",
    ]
    for text in sources:
        for integ in ("rk4", "euler"):
            with pytest.raises(lang.Refusal) as info:
                compile_(head + text.replace("rk4", integ))
            assert info.value.name == "h-scope", text
    with pytest.raises(lang.Refusal) as info:
        compile_(head + sources[0])
    quoted = "a flow's equations cannot read h, whatever it folds to"
    assert info.value.sentence.startswith(quoted)
    assert said(f'`h-scope`: "{quoted}"')
    # the counter as the section writes it compiles
    compile_(head + block("state k, x"))


COUNTERS = (("1/100", 100), ("1/10", 10), ("1/3", 3), ("1/64", 64))


@pytest.mark.parametrize("fmt", FMTS)
def test_the_counter_is_exact_under_the_nearest_attributes(fmt):
    """k = n at every step to 10^4 for each step and rate, under rk4, euler
    and stormer-verlet with k a position and a momentum: under rne at
    every format, and under rmm too at fp64."""
    count = rn_steps(fmt, F(1))
    for h, rate in COUNTERS:
        for integ in INTEGRATORS:
            for rnd in ("rne", "rmm") if fmt == "fp64" else ("rne",):
                hist = history(fmt, rnd, integ, h, rate)
                for i in counters(integ, h):
                    assert column(hist, i) == count, (h, integ, rnd, i)
    assert said("k = n at every step to 10^4, for h = 1/100, 1/10, 1/3 and "
                "1/64 (rates 100, 10, 3 and 64), under rk4, euler and "
                "stormer-verlet with k among the positions or the momenta, "
                "at every format, and at fp64 under rmm too.")


@pytest.mark.parametrize("fmt", FMTS)
def test_the_counter_under_the_directed_attributes(fmt):
    """Wrong after the first step for every h and integrator but h = 1/64
    under euler and stormer-verlet, which at fp64 stays exact at every
    step."""
    one = rn(fmt, F(1))
    for h, rate in COUNTERS:
        for integ in INTEGRATORS:
            for rnd in DIRECTED:
                if h == "1/64" and integ != "rk4":
                    steps = N if fmt == "fp64" else 1
                    hist = history(fmt, rnd, integ, h, rate, steps=steps)
                    for i in counters(integ, h):
                        assert column(hist, i) == rn_steps(fmt, F(1), steps), \
                            (h, integ, rnd)
                    continue
                hist = history(fmt, rnd, integ, h, rate, steps=1)
                for i in counters(integ, h):
                    assert hist[1][i] != one, (h, integ, rnd, i)
    assert said("Under rtz, rdn and rup the count was wrong after the first "
                "step, for each of those h under each integrator at every "
                "format, except h = 1/64 under euler and stormer-verlet, "
                "whose increments are exact: at fp64 it stayed exact at every "
                "step.")


def test_the_counters_limit_at_fp32():
    """From 2^24 - 2: euler's counter stops at 2^24, rk4's counts by
    twos."""
    fmt = FORMATS["fp32"]
    start = (1 << 24) - 2
    got = {}
    for integ in ("euler", "rk4"):
        g = compile_(f"system c\nformat fp32\nstate k\nd/dt k = 100\n"
                     f"step {integ}, h = 1/100\n")
        r = lang.run(g, [[rn("fp32", F(start))]], 6, at=range(7))
        got[integ] = [int(C.value_of(fmt, r.at[s][0][0][0])) - start
                      for s in range(7)]
    assert got == {"euler": [0, 1, 2, 2, 2, 2, 2],
                   "rk4": [0, 1, 2, 4, 6, 8, 10]}
    assert 2 ** FORMATS["fp32"].prec == 16_777_216
    assert said("2^24 = 16,777,216 steps at fp32, 2^53 at fp64. Started at "
                "2^24 - 2 at fp32 with h = 1/100, euler's counter stopped at "
                "2^24 and rk4's counted by twos.")


def test_a_step_halving_run_counts_halves():
    """lang.run at h = 1/200 of a counter written for h = 1/100, at fp64:
    k = n/2 at every step of 2 x 10^4."""
    halves = rn_steps("fp64", F(1, 2), 2 * N)
    for integ in INTEGRATORS:
        hist = history("fp64", "rne", integ, "1/100", 100, steps=2 * N,
                       run_h=F(1, 200))
        for i in counters(integ, "1/100"):
            assert column(hist, i) == halves, (integ, i)
    assert said("k = n/2 at every step of 2 x 10^4 at h = 1/200, under rk4, "
                "euler and stormer-verlet, at fp64.")


# ---- t from the counter ----------------------------------------------------

STAGES = """\
system stages
format {fmt}
state k, x
const dt = 1/100
d/dt k = 100
let t = k * dt
d/dt x = t
step rk4, h = 1/100
"""

START = """\
system start
format {fmt}
state k, x
const dt = 1/100
{t0}
d/dt k = 100
let t = fma(k, dt, t0)
d/dt x = t
step rk4, h = 1/100
"""


@pytest.mark.parametrize("fmt", FMTS)
def test_t_from_the_counter_and_each_stages_time(fmt):
    """Inside rk4 the field reads each stage's counter, exactly n + 1/2 and
    n + 1, and `k * dt` is one rounding of the stage's count times RN(dt);
    against RN(n h), the counts the section gives. `fma(k, dt, t0)`, t0 a
    param or a lane param, is one rounding of n RN(dt) + t0."""
    g = compile_(STAGES.format(fmt=fmt))
    held_to_lang_run(g, (0, 0))
    labels = ("Y2.k", "Y3.k", "Y4.k", "k1.t", "k2.t", "k3.t", "k4.t")
    _states, seen = labelled(g, (0, 0), N + 1, labels)
    dt = C.value_of(FORMATS[fmt], rn(fmt, F(1, 100)))
    for n in range(N + 1):
        half, whole = F(2 * n + 1, 2), F(n + 1)
        assert seen["Y2.k"][n] == seen["Y3.k"][n] == rn(fmt, half), n
        assert seen["Y4.k"][n] == rn(fmt, whole), n
        assert seen["k1.t"][n] == rn(fmt, n * dt), n
        assert seen["k2.t"][n] == seen["k3.t"][n] == rn(fmt, half * dt), n
        assert seen["k4.t"][n] == rn(fmt, whole * dt), n
    # nothing accumulates: t from the count against RN(n h)
    off = [seen["k1.t"][n] - rn(fmt, F(n, 100)) for n in range(N + 1)]
    assert set(off) <= {-1, 0, 1}
    equal = off.count(0)
    assert equal == {"fp32": 7_332, "fp64": 8_674, "fp128": 8_674,
                     "fp256": 9_105}[fmt]
    if fmt == "fp64":
        assert said(f"at fp64 t equalled RN(n h) at {equal:,} of the 10,001 "
                    f"counts from 0 to 10^4 and was one ulp off at the rest")
    else:
        assert said(f"{fmt} {equal:,}")
    assert said("Y2.k = Y3.k = n + 1/2 and Y4.k = n + 1, at every step and "
                "format")
    assert said("k2.t is RN((n + 1/2) RN(1/100))")
    # a start t0, a param or a lane param: one rounding of n RN(dt) + t0
    t0 = rn(fmt, F(1, 3))
    t0v = C.value_of(FORMATS[fmt], t0)
    want = [rn(fmt, n * dt + t0v) for n in range(100)]
    for decl, lane in (("param t0 = 1/3", None), ("lane param t0", [t0])):
        gs = compile_(START.format(fmt=fmt, t0=decl))
        held_to_lang_run(gs, (0, 0), lane, steps=20)
        _s, seen = labelled(gs, (0, 0), 100, ("k1.t",), lane=lane)
        assert seen["k1.t"] == want, decl
    assert said("`fma(k, dt, t0)`, with t0 a param or a lane param, rounds "
                "n RN(dt) + t0 once")


@pytest.mark.parametrize("fmt", FMTS)
def test_the_midpoint_time_under_stormer_verlet(fmt):
    """k among the positions: the kick's force reads Q1.k = n + 1/2, and
    its t is one rounding of that count times RN(dt)."""
    g = compile_(f"system mid\nformat {fmt}\nstate k, p\nconst dt = 1/100\n"
                 f"d/dt k = 100\nlet t = k * dt\nd/dt p = t\n"
                 f"step stormer-verlet, h = 1/100, q = (k), p = (p)\n")
    held_to_lang_run(g, (0, 0))
    _states, seen = labelled(g, (0, 0), N, ("Q1.k", "a1.t"))
    dt = C.value_of(FORMATS[fmt], rn(fmt, F(1, 100)))
    for n in range(N):
        half = F(2 * n + 1, 2)
        assert seen["Q1.k"][n] == rn(fmt, half), n
        assert seen["a1.t"][n] == rn(fmt, half * dt), n
    assert said("the kick's force reads Q1.k = n + 1/2, the midpoint time")


RESIDUAL_MAP = """\
system residual
format {fmt}
round {rnd}
state k, u
const dt = 1/100
next k = k + 1
{lets}next u = t
step map
"""


@pytest.mark.parametrize("fmt", FMTS)
def test_the_correctly_rounded_time(fmt):
    """The section's three lets, from an exact count: RN(n/100) at every
    count from 0 to 10^4 - from a map's count under rne at every format
    and under rmm at fp64, and at fp64 from the flow's count under both;
    at fp64 in the map, no directed rounding, missing rtz's and rdn's at
    the counts the section gives; the map's count exact under every
    attribute at fp64."""
    lets = block("let q = k * dt")
    rnds = ATTRS if fmt == "fp64" else ("rne",)
    missed = {}
    for rnd in rnds:
        g = compile_(RESIDUAL_MAP.format(fmt=fmt, rnd=rnd, lets=lets))
        r = lang.run(g, [[0, 0]], N + 1, at=range(N + 2))
        assert [r.at[s][0][0][0] for s in range(N + 2)] == list(
            rn_steps(fmt, F(1), N + 1)), rnd
        t = [r.at[n + 1][0][0][1] for n in range(N + 1)]
        code = C.RND_BY_NAME[rnd]
        want = [C.round_once(FORMATS[fmt], code, F(n, 100))[0]
                for n in range(N + 1)]
        missed[rnd] = sum(1 for a, b in zip(t, want) if a != b)
    assert missed["rne"] == 0
    if fmt == "fp64":
        assert missed["rmm"] == missed["rup"] == 0
        assert said(f"in that map at fp64 it missed rtz's rounding of n/100 "
                    f"at {missed['rtz']:,} of the counts and rdn's at "
                    f"{missed['rdn']:,}")
        # the flow: the same lets in the counter's field
        for rnd in ("rne", "rmm"):
            g = compile_(f"system flow\nformat fp64\nround {rnd}\n"
                         f"state k, x\nconst dt = 1/100\nd/dt k = 100\n"
                         + lets + "d/dt x = t\nstep euler, h = 1/100\n")
            held_to_lang_run(g, (0, 0))
            _s, seen = labelled(g, (0, 0), N + 1, ("f1.t",))
            assert seen["f1.t"] == list(rn_steps("fp64", F(1, 100))), rnd
    assert said("It equalled RN(n/100) at every count from 0 to 10^4 - from "
                "the count of a map that counts with `next k = k + 1`, at "
                "every format under rne and at fp64 under rmm, and at fp64 "
                "from the flow's count under both.")
    assert said("A map counts with `next k = k + 1`, exactly under every "
                "attribute")


# ---- forcing -----------------------------------------------------------------

def test_sin_of_t_waits_for_the_math_library():
    with pytest.raises(lang.Refusal) as info:
        compile_("system s\nformat fp64\nstate t, x\nparam w = 1\nd/dt t = 1\n"
                 "d/dt x = sin(w * t)\nstep rk4, h = 1/100\n")
    assert (info.value.name, info.value.sentence) == (
        "transcendental", "sin is not computed by a program in v1")
    assert said('`transcendental` ("sin is not computed by a program in v1")')


ROTATION = """\
system rotation
format {fmt}
round  rne
{block}step   {integ}, h = 1/100{opts}
"""


def rotation(fmt, integ, w="1"):
    text = block("state c, s").replace("param w = 1", f"param w = {w}")
    opts = ", q = (c), p = (s)" if integ == SV else ""
    return compile_(ROTATION.format(fmt=fmt, block=text, integ=integ,
                                    opts=opts))


@lru_cache(maxsize=None)
def rotation_history(fmt, integ, w="1", steps=N):
    g = rotation(fmt, integ, w)
    one = rn(fmt, F(1))
    r = lang.run(g, [[one, 0]], steps, at=range(steps + 1))
    return tuple(tuple(r.at[s][0][0]) for s in range(steps + 1))


EXACT = {"fma": lambda a, b, c: a * b + c, "add": lambda a, b: a + b,
         "sub": lambda a, b: a - b, "mul": lambda a, b: a * b,
         "neg": lambda a: -a}


def exact_matrix(graph, rounded=True):
    """One step of a two-component linear system without rounding: every
    operation exact, the constants and params as rounded (or, with
    rounded=False, the constants' exact values). Its columns are the
    steps from (1, 0) and (0, 1)."""
    fmt = graph.fmt
    pv = [C.value_of(fmt, p[2]) if rounded else p[1] for p in graph.param]
    cv = [C.value_of(fmt, c[2]) if rounded else c[0] for c in graph.const]
    cols = []
    for state in ((F(1), F(0)), (F(0), F(1))):
        vals = {"s": state, "p": pv, "c": cv}
        nodes = []

        def get(ref):
            i = int(ref[1:])
            return nodes[i] if ref[0] == "n" else vals[ref[0]][i]
        for op, args, _label in graph.step.nodes:
            nodes.append(EXACT[op](*(get(a) for a in args)))
        cols.append([get(o) for o in graph.step.out])
    return [[cols[0][0], cols[1][0]], [cols[0][1], cols[1][1]]]


def method(graph, n):
    """c^2 + s^2 - 1 after n steps from (1, 0) without rounding, to 120
    digits: the integrator's own."""
    M = exact_matrix(graph)
    with localcontext() as ctx:
        ctx.prec = 120
        A = [[Decimal(x.numerator) / Decimal(x.denominator) for x in row]
             for row in M]
        R = [[Decimal(1), Decimal(0)], [Decimal(0), Decimal(1)]]
        while n:
            if n & 1:
                R = [[R[i][0] * A[0][j] + R[i][1] * A[1][j] for j in (0, 1)]
                     for i in (0, 1)]
            A = [[A[i][0] * A[0][j] + A[i][1] * A[1][j] for j in (0, 1)]
                 for i in (0, 1)]
            n >>= 1
        return R[0][0] * R[0][0] + R[1][0] * R[1][0] - 1


def norm_drift(fmt, bits):
    c, s = (C.value_of(FORMATS[fmt], b) for b in bits)
    return c * c + s * s - 1


def rounding_share(fmt, graph, bits, n):
    with localcontext() as ctx:
        ctx.prec = 120
        d = norm_drift(fmt, bits)
        return Decimal(d.numerator) / Decimal(d.denominator) - method(graph, n)


ROT_HEAD = "| integrator, format | n = 10^2 |"
ROT_ROWS = {"rk4, fp32": ("rk4", ["fp32"]), "rk4, fp64": ("rk4", ["fp64"]),
            "rk4, fp256": ("rk4", ["fp256"]),
            "stormer-verlet, fp32": (SV, ["fp32"]),
            "stormer-verlet, fp64 and fp256": (SV, ["fp64", "fp256"])}


@pytest.mark.parametrize("label", sorted(ROT_ROWS))
def test_the_rotation_table(label):
    """c^2 + s^2 - 1 at 10^2, 10^3 and 10^4 exactly from the encodings, and
    at 10^4 the rounding's share: the measured value less the same step
    without rounding."""
    integ, fmts = ROT_ROWS[label]
    cells = table(ROT_HEAD, [label])[label]
    shares = []
    for fmt in fmts:
        hist = rotation_history(fmt, integ)
        assert cells[:3] == [sci(norm_drift(fmt, hist[n])) for n in MARKS], fmt
        shares.append(sci(rounding_share(fmt, rotation(fmt, integ), hist[N],
                                         N)))
    joined = shares[0] if len(shares) == 1 else (
        ", ".join(shares[:-1]) + " and " + shares[-1])
    assert cells[3] == joined


def test_the_rotation_is_the_integrators():
    """Without rounding, with h's exact multiples: rk4 multiplies c^2 + s^2
    by 1 - (wh)^6/72 + (wh)^8/576 a step, -1.3889e-10 after 10^4; euler by
    1 + (wh)^2, and the run at fp64 is +1.7181e+00 after 10^4;
    stormer-verlet's step keeps a quadratic form (det 1, |trace| < 2) that
    is not c^2 + s^2. The right-hand sides are one product each."""
    th = F(1, 100)
    g = rotation("fp64", "rk4")
    assert g.op_counts("field") == {"mul": 2, "neg": 1}
    M = exact_matrix(g, rounded=False)
    assert M[0][0] ** 2 + M[1][0] ** 2 == 1 - th ** 6 / 72 + th ** 8 / 576
    assert M[0][1] ** 2 + M[1][1] ** 2 == 1 - th ** 6 / 72 + th ** 8 / 576
    with localcontext() as ctx:
        ctx.prec = 60
        f = 1 - th ** 6 / 72 + th ** 8 / 576
        drift = (Decimal(f.numerator) / Decimal(f.denominator)) ** N - 1
    assert said(f"which comes to {sci(drift)} after 10^4 steps")
    assert said("rk4's step multiplies c^2 + s^2 by 1 - (wh)^6/72 + "
                "(wh)^8/576")
    M = exact_matrix(rotation("fp64", "euler"), rounded=False)
    assert M[0][0] ** 2 + M[1][0] ** 2 == 1 + th ** 2
    hist = rotation_history("fp64", "euler")
    assert said(f"euler multiplies it by 1 + (wh)^2 a step: "
                f"{sci(norm_drift('fp64', hist[N]))} after 10^4 steps at "
                f"fp64")
    M = exact_matrix(rotation("fp64", SV), rounded=False)
    det = M[0][0] * M[1][1] - M[0][1] * M[1][0]
    assert det == 1 and abs(M[0][0] + M[1][1]) < 2
    assert M[0][0] ** 2 + M[1][0] ** 2 != 1          # not c^2 + s^2
    assert said("stormer-verlet keeps a nearby quadratic form, not "
                "c^2 + s^2")


def test_the_phase_and_a_rounded_product():
    """At fp64 after 10^4 steps, atan2(s, c) against w t: behind under rk4,
    ahead under stormer-verlet. With w = 3/10, rk4's drift after 10^3
    steps and its rounding's share."""
    phase = {}
    for integ in ("rk4", SV):
        cb, sb = rotation_history("fp64", integ)[N]
        c, s = (float(C.value_of(FORMATS["fp64"], b)) for b in (cb, sb))
        phase[integ] = math.remainder(math.atan2(s, c) - 100.0, math.tau)
    assert phase["rk4"] < 0 < phase[SV]
    assert said(f"atan2(s, c) is {-phase['rk4']:.4e} rad behind w t under "
                f"rk4, about (wh)^5/120 a step, and {phase[SV]:.4e} rad "
                f"ahead under stormer-verlet")
    n = 1_000
    hist = rotation_history("fp64", "rk4", "3/10", n)
    g = rotation("fp64", "rk4", "3/10")
    assert said(f"at fp64 rk4's drift after 10^3 steps is "
                f"{sci(norm_drift('fp64', hist[n]))}, of which "
                f"{sci(rounding_share('fp64', g, hist[n], n))} is the "
                f"rounding's")


def test_the_forced_oscillator():
    """The section's example: accepted; its c and s are the rotation's at
    every step, bit for bit; x against the exact solution of
    x'' + gamma x' + x = F cos t from rest, at every step to t = 100."""
    g = compile_(block("system forced"))
    assert compile_(lang.render_canonical(g)).to_bytes() == g.to_bytes()
    one = rn("fp64", F(1))
    r = lang.run(g, [[one, 0, 0, 0]], N, at=range(N + 1))
    rot = rotation_history("fp64", "rk4")
    assert all(tuple(r.at[n][0][0][:2]) == rot[n] for n in range(N + 1))
    gamma, amp = 0.1, 5.0                  # F/gamma
    wd = math.sqrt(1 - gamma * gamma / 4)
    worst = 0.0
    for n in range(N + 1):
        t = n / 100
        exact = amp * (math.sin(t) - math.exp(-gamma * t / 2)
                       * math.sin(wd * t) / wd)
        x = float(C.value_of(FORMATS["fp64"], r.at[n][0][0][2]))
        worst = max(worst, abs(x - exact))
    assert said(f"x stayed within {worst:.4e} of the exact solution")


def test_every_source_the_section_shows_is_accepted():
    """Each code block compiles - with a system, a format and a step
    added where it shows only the lines that matter."""
    head = "system s\nformat fp64\n"
    shown = blocks()
    assert len(shown) == 5
    for b in shown:
        if b.startswith("system"):
            compile_(b)
        elif b.startswith("let q"):
            compile_(head + "state k, x\nconst dt = 1/100\nd/dt k = 100\n"
                     + b + "d/dt x = t\nstep rk4, h = 1/100\n")
        elif "step " in b:
            compile_(head + b)
        else:
            compile_(head + b + "step rk4, h = 1/100\n")
