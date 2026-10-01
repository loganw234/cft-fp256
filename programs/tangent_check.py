#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The `tangent` runner stage: the variational equations held (L3).

    python programs/tangent_check.py [--segrun host/cft-segrun[.exe]]
                                     [--audit host/cft-audit[.exe]]
                                     [--corpus N] [--only A,B,...]
    python programs/tangent_check.py --write   regenerate the committed
                                               compiled variational
                                               references

A system that declares `tangent v` carries its step's derivative along
tangent vectors (docs/LANGUAGE.md, "The variational equations"). The
language's interpreter, lang.run, is the definition of correct: every
image the compiler writes for such a system must equal it on seq.py, bit
for bit, FLAGS included, states and tangents, on many lanes and at
several step counts - the `lang` stage's discipline (programs/
lang_check.py, whose helpers this reuses), with tangents:

  A  the references with tangent vectors - Lorenz-63 and Henon-Heiles at
     four formats, Lorenz-96 at fp64 and fp256, Lorenz-63 with two
     vectors and under every attribute - on lanes that include the
     primal's three special lanes and three of the tangent's (a
     signalling NaN; a -0 and a subnormal; the largest finite, signs
     alternating), the first and last asserted to raise what they are
     there for in the tangent and not in the primal
  B  the `lang` stage's written shapes and this stage's (time in the
     state, three placed on ties and zeros - with two lanes each whose
     third component is their first - one side of a min or a select
     zero, every activity pattern of fma, lets with lane params under
     stormer-verlet, a map with h, a tangent written out in full) and a
     seeded generated corpus with one or two vectors, at every format
  C  the primal unchanged: on every system of A and B, a run's states
     and primal flags are the run's without the tangent, and the graph's
     primal lines the version-1 graph's
  D  the derivative: the tangent sections evaluated exactly against this
     stage's own exact dual numbers, at random rational points, about
     half of them placed (a component equal to another, or zero); and at
     the ties and zeros the placed shapes put where a convention decides -
     operands equal in value and different in tangent - where a tie
     given its second operand's tangent, or a zero's sign taken as -, is
     asserted to give another answer, so that a convention other than
     the table's fails there
  E  Lorenz-63's largest Lyapunov exponent: the compiled reference on
     libcft's software backend through cft-segrun, one invocation a
     segment, the tangent renormalised on the host by an exact power of
     two between segments (not certified as a chain); the
     renormalisation's exactness; cft-segrun's segment against seq.py
  F  the same exponent at fp256 from ONE certified chain with no
     renormalisation: cft-audit in full and sampled, the golden audit
     sampled, line for line
  G  cft-segrun certifies each compiled variational reference (a main
     run, a half-step run on the halved bank, a step-halving estimate);
     the golden reader and audit and cft-audit accept each
  H  determinism: two processes under two PYTHONHASHSEEDs; the committed
     programs/systems/compiled-tangent/ is what the compiler writes, and
     the `lang` stage's 48 committed files still are
  I  refusals by name, the language's and the compiler's, with tangents
  J  plants: three wrong derivations, red on D and on the exponent; the
     same rule rounded otherwise, green on D and red on the committed
     bytes; three in a copy of the compiler, each stopped by its internal
     check and, with that off, red on seq.py
  K  coverage: every operation the rules write, every activity pattern
     of fma, every format, attribute and integrator, one and two vectors

A check skipped prints a line that starts with SKIP, which the runner
counts and names on its VERDICT line.
"""

import argparse
import hashlib
import json
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "programs"))

import cftc                                               # noqa: E402
from cftc import targets as TG                            # noqa: E402
from cft_golden import cert, lang, seq                    # noqa: E402
from cft_golden import softfloat as sf                    # noqa: E402
from cft_golden.lang import check as lang_check_mod       # noqa: E402
from cft_golden.lang import constants as K                # noqa: E402
from cft_golden.lang import tangent as lang_tangent       # noqa: E402
from cft_golden.lang.graph import Node                    # noqa: E402
import lang_check as LC                                   # noqa: E402

SYSTEMS = ROOT / "programs" / "systems"
COMPILED = SYSTEMS / "compiled-tangent"
TREFS = {"lorenz63-rk4-tangent": 100, "lorenz96-rk4-tangent": 20}
# Lorenz-63's largest Lyapunov exponent at sigma 10, rho 28, beta 8/3, as
# the round's brief gives it (the figure commonly quoted, to four places)
LITERATURE = Fraction(9056, 10000)
ok, bad, check, skip, section = LC.ok, LC.bad, LC.check, LC.skip, LC.section


def with_tangent(text, names="v"):
    lines = text.split("\n")
    k = next(i for i, ln in enumerate(lines) if ln.startswith("state"))
    lines.insert(k + 1, f"tangent {names}")
    return "\n".join(lines)


def without_tangent(text):
    return "\n".join(ln for ln in text.split("\n")
                     if not ln.startswith("tangent "))


def tref_text(base, fmt):
    """A variational reference's text: the committed source at fp64 and
    fp256, its fp64 source with another format line otherwise."""
    p = SYSTEMS / f"{base}-tangent-{fmt}.cftl"
    if p.exists():
        return p.read_bytes().decode("ascii")
    src = (SYSTEMS / f"{base}-tangent-fp64.cftl").read_bytes()
    return LC.with_format(src.decode("ascii"), fmt)


# ---- lanes ----------------------------------------------------------------

def tangent_values(fmt, n, T, rng):
    return [[LC.full_value(fmt, rng, -2, 2) for _ in range(n)]
            for _ in range(T)]


def tangent_specials(fmt, n, T, base):
    """Three lanes' tangents: a signalling NaN; a -0 and a subnormal; the
    largest finite, its sign alternating, so that a difference overflows."""
    top = ((fmt.exp_mask - 1) << fmt.man_w) | fmt.man_mask
    snan = [list(t) for t in base]
    snan[0][0] = sf.snan_bits(fmt, 1)
    small = [list(t) for t in base]
    small[0][0] = fmt.sign_mask
    if n > 1:
        small[0][1] = sf.min_subnormal_bits(fmt)
    huge = [[top | (fmt.sign_mask if i % 2 else 0) for i in range(n)]
            for _ in range(T)]
    return [snan, small, huge]


def lanes_with_tangents(c, rng, count, box=None, placed=False):
    """(states, tangents, lane params or None, roles): random lanes, the
    primal's three special lanes with ordinary tangents, and three lanes
    on lane 0's state whose tangents are special; with `placed`, two more
    whose third component is their first, the tangents random - the
    placed shapes' ties and zeros, decided on the image as in the
    interpreter. `roles` names the two whose tangent must raise a flag
    its primal does not."""
    g = c.ir
    n, T = g.n_primal, g.T
    states = LC.lanes_for(g.fmt, n, rng, count, box)
    states += LC.special_lanes(g.fmt, n, states[0], rng)
    if placed:
        for _ in range(2):
            lane = LC.lanes_for(g.fmt, n, rng, 1, box)[0]
            lane[2] = lane[0]
            states.append(lane)
    tans = [tangent_values(g.fmt, n, T, rng) for _ in states]
    tspec = tangent_specials(g.fmt, n, T, tans[0])
    states += [list(states[0]) for _ in tspec]
    tans += tspec
    roles = {len(states) - 3: ("a signalling-NaN tangent", sf.FLAG_INVALID,
                               "invalid"),
             len(states) - 1: ("the largest finite tangent",
                               sf.FLAG_OVERFLOW, "overflow")}
    lp = None
    if g.lane:
        lp = [[LC.full_value(g.fmt, rng, Fraction(1, 2), 2) for _ in g.lane]
              for _ in states]
    return states, tans, lp, roles


# ---- running an image -----------------------------------------------------

def run_block(image, c, block, nlanes, bank=None):
    prog = seq.Program.from_bytes(image, scratch_depth=c.depth)
    vals = c.lowered.bank_values() if bank is None else list(bank)
    return seq.run(prog, [0] * nlanes, [0] * nlanes, [0] * nlanes,
                   bank=vals, scratch_in=block, scratch_depth=c.depth)


def compare(c, states, tangents, top, lane_params=None):
    """seq.py on the image at 1, 2, 5 and `top` steps against lang.run's
    checkpoints: states, tangents, lane params and FLAGS. -> (failing
    lanes, FLAGS equal everywhere, the interpreter's run)."""
    marks = sorted({s for s in LC.CHECKPOINTS if s < top} | {top})
    ref = lang.run(c.graph, states, top, lane_params=lane_params,
                   at=tuple(s for s in marks if s != top), tangents=tangents)
    g = c.ir
    n, m, T = g.n_primal, g.m, g.T
    lp = lane_params or [[b for _n, _d, b in g.lane] for _ in states]
    block = c.scratch_block(states, lane_params, tangents)
    failing, flags_ok = set(), True
    for s in marks:
        r = run_block(LC.image_at(c.image, s), c, block, len(states))
        if s == top:
            want_s, want_f, want_t = ref.states, ref.flags, ref.tangents
        else:
            (want_s, want_f), want_t = ref.at[s], ref.at_tangents[s]
        for k in range(len(states)):
            out = r.scratch_out[k * m:(k + 1) * m]
            tv = [out[n * (j + 1):n * (j + 2)] for j in range(T)]
            if out[:n] != want_s[k] or tv != want_t[k] or \
                    out[n * (T + 1):] != list(lp[k]):
                failing.add(k)
        if r.flags != want_f or r.status != 0:
            flags_ok = False
    return failing, flags_ok, ref


def by_value(g):
    """field and step, each const ref written as its (value, factor)."""
    def norm(sec):
        if sec is None:
            return None

        def r(a):
            return ("c", g.const[int(a[1:])][:2]) if a[0] == "c" else a
        return ([(op, tuple(r(a) for a in args), lb)
                 for op, args, lb in sec.nodes], [r(o) for o in sec.out])
    return norm(g.field), norm(g.step)


def primal_unchanged(g, primal_text, states, top, lane_params=None):
    """Leg C on one system: run without its tangents, the same states and
    the same primal flags; the version-1 graph's lines, byte for byte up
    to its step's last where no rule added a constant, and by value where
    one did (0, 1 and -1 only)."""
    g0 = lang.compile_text(primal_text, "primal").graph
    r0 = lang.run(g0, states, top, lane_params=lane_params)
    tans = [[[0] * g.n_state for _ in g.tangent] for _ in states]
    r1 = lang.run(g, states, top, lane_params=lane_params, tangents=tans)
    if r0.states != r1.states or r0.flags != r1.primal_flags:
        return False
    if g.const == g0.const:
        b0, b1 = g0.to_bytes().split(b"\n"), g.to_bytes().split(b"\n")
        return (b1[0] == b0[0].replace(b'"cftl_graph":1,', b'"cftl_graph":2,')
                and b1[1:len(b0) - 2] == b0[1:-2]
                and b1[len(b0) - 2] == b0[-2][:-1] + b",")
    added = {v for v, *_r in g.const} - {v for v, *_r in g0.const}
    return added <= {Fraction(0), Fraction(1), Fraction(-1)} and \
        by_value(g) == by_value(g0)


# ---- D: the derivative, this stage's own dual numbers ---------------------

def _sgn(x, zero=1):
    return -1 if x < 0 else (zero if x == 0 else 1)


def _dual(op, a, tie=0, zero=1):
    """One operation on (value, derivative) pairs, exactly, by calculus -
    with the rule table's choices at its measure-zero points (a tie gives
    the first operand's, a zero's sign is +) - written again here, not
    read from the derivation. tie=1 and zero=-1 are the other choices,
    which a placed point must tell apart from the table's; a value is
    the same under any of them."""
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
    if op in ("cmplt", "cmple", "cmpeq"):
        t = {"cmplt": v[0] < v[1], "cmple": v[0] <= v[1],
             "cmpeq": v[0] == v[1]}[op]
        return Fraction(1 if t else 0), Fraction(0)
    if op == "select":
        return (v[0], d[0]) if v[2] != 0 else (v[1], d[1])
    raise AssertionError(op)


def dual_derivative(g, section, st, tv, pa, la, tie=0, zero=1):
    """The exact derivative of a primal section along tv, by _dual."""
    sec = g.section(section)
    nil = Fraction(0)
    vals = {"s": list(zip(st, tv)), "l": [(x, nil) for x in la],
            "p": [(x, nil) for x in pa],
            "c": [(v, nil) for v, *_r in g.const]}
    nodes = []

    def get(r):
        return nodes[int(r[1:])] if r[0] == "n" else vals[r[0]][int(r[1:])]
    for op, args, _l in sec.nodes:
        nodes.append(_dual(op, [get(a) for a in args], tie, zero))
    return [get(o)[1] for o in sec.out]


def _q(rng):
    return Fraction(rng.randint(-5000, 5000), rng.randint(1, 4000))


def derivative_misses(g, rng, points=2):
    """(points tried, points where a tangent section's exact value is not
    the dual numbers' derivative of the section it differentiates). About
    half the points are placed: one component set equal to another or to
    zero, the tangent random, so that a tie or a zero there has operands
    whose tangents differ."""
    bad_n = tot = placed = 0
    for primal, tangent in (("field", "tangent_field"),
                            ("step", "tangent_step")):
        if g.section(primal) is None:
            continue
        for _ in range(points):
            n = g.n_state
            st = [_q(rng) for _ in range(n)]
            r, i = rng.random(), rng.randrange(n)
            if r < 0.25 and n > 1:
                st[rng.choice([j for j in range(n) if j != i])] = st[i]
            elif r < 0.5:
                st[i] = Fraction(0)
            placed += r < 0.25 and n > 1 or 0.25 <= r < 0.5
            tv = [_q(rng) for _ in range(n)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            want = dual_derivative(g, primal, st, tv, pa, la)
            got = g.exact_eval(tangent, st, pa, la, tangent=tv)
            tot += 1
            bad_n += got != want
    return tot, bad_n, placed


def placed_misses(g, rng, decides, points=6):
    """At points with the third component equal to the first, every value
    nonzero, the tangents of the two different: (points, points where the
    tangent is not the table's derivative, points where a convention the
    system decides gives the same answer as the table's - a placement
    that cannot fail)."""
    other = {"tie": {"tie": 1}, "zero": {"zero": -1}}
    tot = bad_n = blind = 0
    for primal, tangent in (("field", "tangent_field"),
                            ("step", "tangent_step")):
        if g.section(primal) is None:
            continue
        for _ in range(points):
            while True:
                st = [_q(rng) for _ in range(g.n_state)]
                st[2] = st[0]
                tv = [_q(rng) for _ in range(g.n_state)]
                if all(st) and tv[0] != tv[2]:
                    break
            want = dual_derivative(g, primal, st, tv, [], [])
            tot += 1
            bad_n += g.exact_eval(tangent, st, tangent=tv) != want
            blind += any(dual_derivative(g, primal, st, tv, [], [],
                                         **other[d]) == want
                         for d in decides)
    return tot, bad_n, blind


# ---- coverage -------------------------------------------------------------

COVER = {"tangent_ops": {}, "fma_patterns": set(), "rounds": set(),
         "formats": set(), "integrators": set(), "vectors": set(),
         "systems": 0, "flags": 0}


def fma_patterns(g):
    """Which of each step fma's operands carry a tangent - the rules'
    activity, read again here for the coverage count."""
    act = []

    def a(r):
        k, i = r[0], int(r[1:])
        return True if k == "s" else (act[i] if k == "n" else False)
    pats = set()
    for op, args, _l in g.step.nodes:
        if op in ("cmplt", "cmple", "cmpeq"):
            act.append(False)
        elif op == "select":
            act.append(a(args[0]) or a(args[1]))
        elif op == "copysign":
            act.append(a(args[0]))
        else:
            act.append(any(a(x) for x in args))
        if op == "fma" and act[-1]:
            pats.add(tuple(int(a(x)) for x in args))
    return pats


def cover(c, flags):
    COVER["systems"] += 1
    for op, k in c.graph.op_counts("tangent_step").items():
        COVER["tangent_ops"][op] = COVER["tangent_ops"].get(op, 0) + k
    COVER["fma_patterns"] |= fma_patterns(c.graph)
    COVER["rounds"].add(c.ir.rnd_name)
    COVER["formats"].add(c.ir.fmt_name)
    COVER["integrators"].add(c.ir.integrator[0])
    COVER["vectors"].add(c.ir.T)
    COVER["flags"] |= flags


# ---- A: the references ----------------------------------------------------

def run_system(c, primal_text, rng, top, count, box=None, what=""):
    """A (or B) and C on one compiled system."""
    states, tans, lp, roles = lanes_with_tangents(c, rng, count, box)
    failing, fok, ref = compare(c, states, tans, top, lp)
    cover(c, ref.flags)
    check(not failing and fok, f"{what}: {len(states)} lanes at 1, 2, 5 and "
          f"{top} steps equal the interpreter, states and tangents, FLAGS "
          f"{ref.flags:#x} included",
          f"{len(failing)} lanes differ, FLAGS {'equal' if fok else 'differ'}")
    missed = []
    for k, (role, flag, word) in roles.items():
        r1 = lang.run(c.graph, [states[k]], top, tangents=[tans[k]],
                      lane_params=[lp[k]] if lp else None)
        if not (r1.flags & flag) or r1.primal_flags & flag:
            missed.append(f"{role}: {word} {'not ' * (not r1.flags & flag)}"
                          f"in FLAGS {r1.flags:#x}, primal's "
                          f"{r1.primal_flags:#x}")
    check(not missed, f"{what}: a signalling-NaN tangent raises invalid and "
          f"the largest finite tangent overflow, in FLAGS and not in the "
          f"primal's flags", "; ".join(missed))
    check(primal_unchanged(c.graph, primal_text, states[:6], min(top, 5),
                           lp[:6] if lp else None),
          f"{what}: the primal unchanged - its states and flags without "
          f"the tangent, its graph's lines")


def leg_references(rng):
    section("A. the references with tangent vectors against the "
            "interpreter, C. the primal unchanged")
    cases = []
    for fmt in ("fp32", "fp64", "fp128", "fp256"):
        cases.append(("lorenz63-rk4", fmt, None, "v"))
        cases.append(("henonheiles-lf", fmt, None, "v"))
    cases += [("lorenz96-rk4", "fp64", None, "v"),
              ("lorenz96-rk4", "fp256", None, "v"),
              ("lorenz63-rk4", "fp64", None, "v, w")]
    for rnd in ("rtz", "rdn", "rup", "rmm"):
        cases.append(("lorenz63-rk4", "fp64", rnd, "v"))
    for base, fmt, rnd, names in cases:
        if base == "henonheiles-lf" or names != "v":
            text = with_tangent(LC.ref_text(base, fmt), names)
        else:
            text = tref_text(base, fmt)
        if rnd:
            text = LC.with_round(text, rnd)
        c = cftc.compile_text(text, LC.REFS[base],
                              source=f"{base} {fmt} tangent {names}",
                              stem="t")
        count = 3 if base == "lorenz96-rk4" else (4 if rnd else 8)
        what = (f"{base} {fmt}" + (f" {rnd}" if rnd else "")
                + f" tangent {names}")
        run_system(c, without_tangent(text), rng, LC.REFS[base], count,
                   LC.BOX[base], what=what)


# ---- B: shapes and a corpus -----------------------------------------------

SHAPES = {
    "time-in-the-state": "system tdep\nformat fp64\nstate t, x\ntangent v\n"
                         "d/dt t = 1\nd/dt x = fma(x, t, -x)\n"
                         "step rk4, h = 1/8\n",
    "placed-ties": "system pt\nformat fp64\nstate x, y, z, w\ntangent v\n"
                   "next x = max(x, z) * y\nnext y = min(z, x) - w\n"
                   "next z = maxnum(z, x) + y\nnext w = minnum(x, z) * w\n"
                   "step map\n",
    "placed-zeros": "system pz\nformat fp64\nstate x, y, z\ntangent v\n"
                    "next x = y * abs(z - x)\n"
                    "next y = copysign(x - z, y) - x\n"
                    "next z = copysign(y, z - x) * y\nstep map\n",
    "placed-inside": "system pi\nformat fp64\nstate x, y, z\ntangent v\n"
                     "let p = x * y\nlet q = z * y\n"
                     "d/dt x = min(p, q) - abs(p - q)\nd/dt y = -y\n"
                     "d/dt z = maxnum(q, p) * y\nstep rk4, h = 1/16\n",
    "one-side-zero": "system one\nformat fp64\nstate x, y\ntangent v\n"
                     "param p = 1/3\n"
                     "next x = min(x, p) + select(x < y, y, p)\n"
                     "next y = maxnum(p, y) * select(y < p, p, x)\n"
                     "step map\n",
    "fma-patterns": "system fp\nformat fp64\nstate x, y, z\ntangent v\n"
                    "param p = 1/3, q = 2/7, r = 5/3\n"
                    "next x = fma(x, y, z) + fma(x, q, z) + fma(p, y, z)\n"
                    "next y = fma(x, y, r) + fma(x, q, r) + fma(p, y, r)\n"
                    "next z = fma(p, q, z) + z * fma(p, q, r)\nstep map\n",
    "lets-lanes-sv": "system lsv\nformat fp128\nround rup\n"
                     "state q0, q1, m0, m1\ntangent v, w\n"
                     "lane param k = 3/2\nlet d = q0 - q1\n"
                     "d/dt q0 = m0\nd/dt q1 = m1\n"
                     "d/dt m0 = -(k * d * d * d)\nd/dt m1 = k * d * d * d\n"
                     "step stormer-verlet, h = 1/32, q = (q0, q1), "
                     "p = (m0, m1)\n",
    "map-with-h": "system mh\nformat fp256\nround rdn\nstate a[4] cyclic\n"
                  "tangent v\nnext a[i] = fma(h, a[i+1] * a[i-1], a[i])\n"
                  "step map, h = 1/16\n",
}


def corpus(count, seed):
    out = []
    for k, (text, shape) in enumerate(LC.corpus_texts(count, seed)):
        names = "v, w" if k % 5 == 4 else "v"
        out.append((with_tangent(text, names), f"{shape} {k}"))
    return out


def leg_corpus(count, rng):
    texts = [(with_tangent(t), f"lang shape {s}", t)
             for s, t in LC.SHAPES.items()]
    texts += [(t, f"shape {s}", without_tangent(t))
              for s, t in SHAPES.items()]
    l63 = tref_text("lorenz63-rk4", "fp64")
    written = lang.render_canonical(lang.compile_text(l63).graph)
    texts.append((written, "Lorenz-63's tangent written out in full (its "
                  "canonical form)", without_tangent(l63)))
    texts += [(t, w, without_tangent(t)) for t, w in
              corpus(count, "tangent corpus")]
    section(f"B. {len(texts) - count} written shapes and {count} generated "
            f"systems with tangent vectors, at every format L1 takes them; "
            f"C. the primal unchanged in each")
    runs = 0
    refused = {}
    failed = []
    t0 = time.perf_counter()
    for text, what, primal in texts:
        own = next(ln.split()[1] for ln in text.split("\n")
                   if ln.startswith("format "))
        fmts = [own] if what.startswith("pressure") else \
            ["fp32", "fp64", "fp128", "fp256"]
        for fmt in fmts:
            t = LC.with_format(text, fmt)
            try:
                c = cftc.compile_text(t, 4, source=f"{what} {fmt}", stem="g")
            except lang.Refusal as e:
                if e.name not in LC.ARTIFACTS:
                    failed.append(f"{what} {fmt}: refused {e.name}: {e}")
                else:
                    refused[e.name] = refused.get(e.name, 0) + 1
                continue
            except cftc.InternalError as e:
                failed.append(f"{what} {fmt}: internal error: {e}")
                continue
            states, tans, lp, _roles = lanes_with_tangents(
                c, rng, 3, placed=what.startswith("shape placed-"))
            failing, fok, ref = compare(c, states, tans, 4, lp)
            cover(c, ref.flags)
            runs += 1
            if failing or not fok:
                failed.append(f"{what} {fmt}: {len(failing)} of "
                              f"{len(states)} lanes differ, FLAGS "
                              f"{'equal' if fok else 'differ'}")
            if not primal_unchanged(c.graph, LC.with_format(primal, fmt),
                                    states[:4], 3, lp[:4] if lp else None):
                failed.append(f"{what} {fmt}: the primal changed")
    for f in failed[:10]:
        print(f"        {f}")
    check(not failed and runs > 0, f"{runs} compiled systems equal the "
          f"interpreter on 9 lanes (11 for the placed shapes, two lanes on "
          f"their ties and zeros) at 1, 2 and 4 steps, states and tangents, "
          f"FLAGS included, the primal unchanged in each "
          f"({time.perf_counter() - t0:.1f} s)", f"{len(failed)} failed")
    print(f"  refused as a writer would be, by name: "
          f"{dict(sorted(refused.items())) or 'none'}")


# ---- D --------------------------------------------------------------------

def leg_derivative(rng):
    section("D. the tangent is the derivative: exact, against this stage's "
            "own dual numbers")
    graphs = [lang.compile_text(tref_text("lorenz63-rk4", "fp64")).graph,
              lang.compile_text(tref_text("lorenz96-rk4", "fp64")).graph,
              lang.compile_text(with_tangent(LC.ref_text("henonheiles-lf",
                                                         "fp64"))).graph]
    graphs += [lang.compile_text(t).graph for t in SHAPES.values()]
    graphs += [lang.compile_text(with_tangent(t)).graph
               for t in LC.SHAPES.values()]
    for text, _w in corpus(60, "tangent derivative"):
        try:
            graphs.append(lang.compile_text(text).graph)
        except lang.Refusal:
            pass
    tot = bad_n = placed = 0
    for g in graphs:
        a, b, c = derivative_misses(g, rng, 4)
        tot += a
        bad_n += b
        placed += c
    check(bad_n == 0 and tot > 100, f"{len(graphs)} systems, {tot} points, "
          f"{placed} of them placed: the tangent sections evaluated exactly "
          f"equal the exact derivative of the step at every one",
          f"{bad_n} points differ")
    # the ties and zeros placed where a convention decides: the third
    # component equal to the first, their tangents different
    decides = {"placed-ties": ("tie",), "placed-zeros": ("zero",),
               "placed-inside": ("tie", "zero")}
    tot = bad_n = blind = 0
    for name, d in decides.items():
        a, b, c = placed_misses(lang.compile_text(SHAPES[name]).graph, rng, d)
        tot += a
        bad_n += b
        blind += c
    check(bad_n == 0 and blind == 0 and tot > 0, f"{tot} points on the "
          f"three placed shapes - min, max, minnum and maxnum at a tie, abs "
          f"and copysign's two sources at a zero, alone and inside "
          f"expressions, operands equal in value and different in tangent: "
          f"the tangent is the table's derivative at every one, and a tie "
          f"given its second operand's tangent, or a zero's sign taken as "
          f"-, gives another answer at every one",
          f"{bad_n} differ from the table's, {blind} where another "
          f"convention gives the same answer")


# ---- E: the Lyapunov smoke test -------------------------------------------

# Sized from a measurement (L3's ledger, 2026-10-01): 16 lanes at t = 1,000
# gave 0.9051, one lane's standard deviation 0.0054; 4-lane means 0.9014 to
# 0.9088. Eight lanes at t = 1,000 put the mean's deviation near 0.002;
# the tolerance is five of those.
S_FP64 = 10000          # steps a segment: t = 100 at h = 1/100
N_FP64 = 10             # segments: t = 1,000 a lane
LANES_FP64 = 8
TOL_FP64 = Fraction(1, 100)
# One certified chain at fp256: t = 1,000 without renormalisation (the
# tangent grows by about e^906, inside binary256's range and not
# binary64's), in segments of 2,500 steps so that the golden audit's
# sample re-runs one in seconds.
S_FP256 = 2500
N_FP256 = 40
LANES_FP256 = 4
TOL_FP256 = Fraction(2, 100)


def starts(fmt, count, seed):
    """Lanes from rational starts, spread over the attractor's box."""
    rng = random.Random(seed)

    def q(lo, hi):
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(lo, hi), 100))[0]
    return [[q(-1000, 1000), q(-1000, 1000), q(1000, 3000)]
            for _ in range(count)]


def segrun(segrun_path, work, image, bank, block, fmt, steps, segments,
           depth=256):
    """One cft-segrun run of `segments` segments of `steps` steps on the
    software backend. -> (each boundary's values, the certificate, the
    states directory)."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "image.cftp").write_bytes(image)
    (work / "bank.bin").write_bytes(bank)
    (work / "init.bin").write_bytes(cert.state_bytes(fmt, block))
    out, states = work / "c.cert", work / "states"
    if out.exists():
        out.unlink()
    if states.exists():
        shutil.rmtree(states)
    args = ["--out", out, "--states", states, "--open", "--device", "sw"]
    if depth != 256:
        args += ["--scratch-depth", depth]
    args += ["--run", "main", "--image", work / "image.cftp", "--bank",
             work / "bank.bin", "--init", work / "init.bin", "--segments",
             segments, "--steps", steps]
    r = subprocess.run([str(segrun_path)] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"cft-segrun rc {r.returncode}: "
                           f"{r.stderr.strip()[-300:]}")
    return [cert.state_values(fmt, (states / f"run-0-boundary-{b}.bin")
                              .read_bytes())
            for b in range(segments + 1)], out, states


def renormalised(fmt, vec):
    """The tangent scaled by 2^-k, k its largest component's binary
    exponent - exact, each product's flags asserted 0. -> (vector, k)."""
    big = max(abs(K.value_of(fmt, b)) for b in vec)
    k = big.numerator.bit_length() - big.denominator.bit_length()
    if Fraction(2) ** k > big:
        k -= 1
    p = K.round_once(fmt, sf.RND_RNE, Fraction(2) ** -k)[0]
    out = []
    for b in vec:
        r, fl = sf.mul(fmt, b, p, sf.RND_RNE)
        if fl:
            raise ArithmeticError("a power-of-two scaling that is not exact")
        out.append(r)
    return out, k


def log_norm(fmt, vec):
    """ln |v| from the exact values: |v|^2 a Fraction, its binary exponent
    taken out before the float."""
    n2 = sum(K.value_of(fmt, b) ** 2 for b in vec)
    e = n2.numerator.bit_length() - n2.denominator.bit_length()
    return (e * math.log(2) + math.log(float(n2 / Fraction(2) ** e))) / 2


def lyapunov_fp64(segrun_path, work, lanes, segments):
    """The renormalised run on `lanes` lanes: a transient of one segment
    (t = 100) with the tangent zero, then the tangent (1, 0, 0) and
    `segments` segments. -> (the mean exponent, each lane's)."""
    src = SYSTEMS / "lorenz63-rk4-tangent-fp64.cftl"
    c = cftc.compile_file(src, S_FP64, source=src.as_posix())
    fmt, n = c.ir.fmt, 3
    one = K.round_once(fmt, sf.RND_RNE, Fraction(1))[0]
    block = [v for s in starts(fmt, lanes, "lyapunov") for v in s + [0, 0, 0]]
    b, _o, _s = segrun(segrun_path, work, c.image, c.bank, block, "fp64",
                       S_FP64, 1, c.depth)
    cur = [b[1][k * 6:k * 6 + 3] + [one, 0, 0] for k in range(lanes)]
    Ks = [0] * lanes
    for _ in range(segments):
        b, _o, _s = segrun(segrun_path, work, c.image, c.bank,
                           [v for lane in cur for v in lane], "fp64", S_FP64,
                           1, c.depth)
        nxt = []
        for k in range(lanes):
            lane = b[1][k * 6:(k + 1) * 6]
            vec, e = renormalised(fmt, lane[n:])
            Ks[k] += e
            nxt.append(lane[:n] + vec)
        cur = nxt
    t = segments * S_FP64 / 100
    lams = [(Ks[k] * math.log(2) + log_norm(fmt, cur[k][n:])) / t
            for k in range(lanes)]
    return sum(lams) / lanes, lams


def leg_lyapunov(segrun_path, work):
    section("E. Lorenz-63's largest Lyapunov exponent, the tangent "
            "renormalised on the host between segments")
    if not segrun_path or not Path(segrun_path).is_file():
        skip("E: the Lyapunov smoke test", f"no cft-segrun at "
             f"{segrun_path!r} (the stage builds it)")
        return
    t0 = time.perf_counter()
    lam, lams = lyapunov_fp64(segrun_path, work / "lyap", LANES_FP64, N_FP64)
    check(abs(Fraction(lam) - LITERATURE) <= TOL_FP64,
          f"{LANES_FP64} lanes x t = {N_FP64 * S_FP64 // 100:,} at fp64 "
          f"({N_FP64} segments of {S_FP64:,} steps after a transient of "
          f"one, renormalised by exact powers of two): the exponent "
          f"{lam:.4f}, against {float(LITERATURE):.4f} within "
          f"{float(TOL_FP64)} (lanes {', '.join(f'{x:.4f}' for x in lams)};"
          f" {time.perf_counter() - t0:.1f} s)", f"{lam:.4f}")
    # the host's scaling is exact: two renormalised segments against one
    # unrenormalised segment of twice the steps (t = 200, inside binary64)
    src = SYSTEMS / "lorenz63-rk4-tangent-fp64.cftl"
    c = cftc.compile_file(src, S_FP64, source=src.as_posix())
    fmt, n = c.ir.fmt, 3
    one = K.round_once(fmt, sf.RND_RNE, Fraction(1))[0]
    lanes = [s + [one, 0, 0] for s in starts(fmt, 2, "renormalisation")]
    cur, Ks = [list(x) for x in lanes], [0, 0]
    for _ in range(2):
        b, _o, _s = segrun(segrun_path, work / "renorm", c.image, c.bank,
                           [v for lane in cur for v in lane], "fp64",
                           S_FP64, 1, c.depth)
        nxt = []
        for k in range(2):
            lane = b[1][k * 6:(k + 1) * 6]
            vec, e = renormalised(fmt, lane[n:])
            Ks[k] += e
            nxt.append(lane[:n] + vec)
        cur = nxt
    whole, _o, _s = segrun(segrun_path, work / "whole",
                           LC.image_at(c.image, 2 * S_FP64), c.bank,
                           [v for lane in lanes for v in lane], "fp64",
                           2 * S_FP64, 1, c.depth)
    same = True
    for k in range(2):
        lane = whole[1][k * 6:(k + 1) * 6]
        p = K.round_once(fmt, sf.RND_RNE, Fraction(2) ** -Ks[k])[0]
        scaled = [sf.mul(fmt, x, p, sf.RND_RNE) for x in lane[n:]]
        same = same and lane[:n] == cur[k][:n] and \
            [x for x, _f in scaled] == cur[k][n:] and \
            not any(f for _x, f in scaled)
    check(same, f"the renormalisation is exact: two renormalised segments "
          f"are one unrenormalised segment of {2 * S_FP64:,} steps, the "
          f"states equal and the tangent times 2^-K bit for bit, on 2 "
          f"lanes (K = {Ks})")
    # cft-segrun's software backend against seq.py, one short segment
    img = LC.image_at(c.image, 1000)
    block = [v for lane in lanes for v in lane]
    b, _o, _s = segrun(segrun_path, work / "short", img, c.bank, block,
                       "fp64", 1000, 1, c.depth)
    r = run_block(img, c, block, 2)
    check(b[1] == list(r.scratch_out), "cft-segrun's segment of 1,000 steps "
          "on 2 lanes is seq.py's scratch-out, byte for byte")


# ---- F: the certified fp256 chain -----------------------------------------

def leg_certified(segrun_path, audit_path, work):
    section("F. the exponent at fp256 from one certified chain, no "
            "renormalisation: both auditors accept")
    if not segrun_path or not Path(segrun_path).is_file():
        skip("F: the certified chain", f"no cft-segrun at {segrun_path!r}")
        return
    src = SYSTEMS / "lorenz63-rk4-tangent-fp256.cftl"
    c = cftc.compile_file(src, S_FP256, source=src.as_posix())
    fmt, n = c.ir.fmt, 3
    g0 = lang.compile_text(without_tangent(src.read_bytes().decode("ascii")))
    t0 = time.perf_counter()
    lanes = lang.run(g0.graph, starts(fmt, LANES_FP256, "certified"),
                     2000).states
    one = K.round_once(fmt, sf.RND_RNE, Fraction(1))[0]
    block = [v for s in lanes for v in s + [one, 0, 0]]
    d = work / "cert256"
    try:
        bounds, out, states = segrun(segrun_path, d, c.image, c.bank, block,
                                     "fp256", S_FP256, N_FP256, c.depth)
    except RuntimeError as e:
        bad(f"F: {e}")
        return
    final = bounds[-1]
    t = N_FP256 * S_FP256 / 100
    lams = [(log_norm(fmt, final[k * 6 + n:k * 6 + 6])
             - log_norm(fmt, block[k * 6 + n:k * 6 + 6])) / t
            for k in range(LANES_FP256)]
    lam = sum(lams) / len(lams)
    check(abs(Fraction(lam) - LITERATURE) <= TOL_FP256,
          f"{LANES_FP256} lanes x t = {N_FP256 * S_FP256 // 100:,} at fp256, "
          f"one certified chain of {N_FP256} segments of {S_FP256:,} steps "
          f"with no renormalisation: the exponent from the certified final "
          f"state {lam:.4f}, against {float(LITERATURE):.4f} within "
          f"{float(TOL_FP256)} (lanes {', '.join(f'{x:.4f}' for x in lams)};"
          f" {time.perf_counter() - t0:.1f} s with the transient)",
          f"{lam:.4f}")
    data = out.read_bytes()
    progs = {0: (c.image, c.bank)}
    sb = {0: {b: (states / f"run-0-boundary-{b}.bin").read_bytes()
              for b in range(N_FP256 + 1)}}
    seed = hashlib.sha256(b"tangent certified fp256").digest()
    try:
        t0 = time.perf_counter()
        cert.parse(data)
        sampled = cert.audit(data, None, progs, states=sb,
                             choose={0: ("sample", 1)}, seed=seed)
        ok(f"F: the golden reader accepts the certificate ({len(data):,} "
           f"bytes) and the golden audit a sample of the chain "
           f"({time.perf_counter() - t0:.1f} s)")
    except cert.Refusal as e:
        bad(f"F: the golden model refuses the chain: {e.name}: {e.message}")
        return
    if not audit_path or not Path(audit_path).is_file():
        skip("F: cft-audit on the chain", f"no cft-audit at {audit_path!r}")
        return
    for how, choose, verdict in (("in full", "all", None),
                                 ("sampled", "sample:1", sampled)):
        t0 = time.perf_counter()
        r = subprocess.run([str(audit_path), "--cert", str(out), "--states",
                            str(states), "--seed", seed.hex(), "--run", "0",
                            "--image", str(d / "image.cftp"), "--bank",
                            str(d / "bank.bin"), "--choose", choose],
                           capture_output=True, text=True, timeout=1800)
        got = r.stdout.split("\n")
        if got and got[-1] == "":
            got = got[:-1]
        same = verdict is None or got == list(verdict.lines())
        check(r.returncode == 0 and same, f"F: cft-audit accepts the chain "
              f"{how}" + ("" if verdict is None else ", the golden verdict "
                          "line for line")
              + f" ({time.perf_counter() - t0:.1f} s)",
              f"rc {r.returncode}: {r.stderr.strip()[-300:]}")


# ---- G: libcft certifies the variational references -----------------------

def leg_libcft(segrun_path, audit_path, rng, work):
    section("G. cft-segrun certifies the compiled variational references; "
            "both auditors accept")
    if not segrun_path or not Path(segrun_path).is_file():
        skip("G: certificates", f"no cft-segrun at {segrun_path!r}")
        return
    have_audit = bool(audit_path) and Path(audit_path).is_file()
    if not have_audit:
        skip("G: cft-audit on each certificate", f"no cft-audit at "
             f"{audit_path!r}")
    for base, steps in TREFS.items():
        for fmt in ("fp64", "fp256"):
            src = SYSTEMS / f"{base}-{fmt}.cftl"
            c = cftc.compile_file(src, steps,
                                  source=f"programs/systems/{base}-{fmt}.cftl")
            certify(c, f"{base}-{fmt}", segrun_path,
                    audit_path if have_audit else None, rng, work)


def certify(c, name, segrun_path, audit_path, rng, work):
    """lang_check's certify, its lanes given tangents."""
    g = c.ir
    d = work / "certs" / name
    d.mkdir(parents=True, exist_ok=True)
    box = LC.BOX.get(name.split("-tangent")[0])
    states = LC.lanes_for(g.fmt, g.n_primal, rng, 4, box)
    tans = [tangent_values(g.fmt, g.n_primal, g.T, rng) for _ in states]
    block = c.scratch_block(states, None, tans)
    (d / "image.cftp").write_bytes(c.image)
    (d / "main.bank").write_bytes(c.bank)
    (d / "half.bank").write_bytes(c.half_bank)
    (d / "init.bin").write_bytes(cert.state_bytes(g.fmt_name, block))
    out, states_dir = d / "c.cert", d / "states"
    if out.exists():
        out.unlink()
    if states_dir.exists():
        shutil.rmtree(states_dir)
    args = ["--out", out, "--states", states_dir, "--open", "--device", "sw"]
    if c.depth != 256:
        args += ["--scratch-depth", c.depth]
    args += ["--run", "main", "--image", d / "image.cftp", "--bank",
             d / "main.bank", "--init", d / "init.bin", "--segments", 2,
             "--steps", c.steps,
             "--run", "half-step", "--h-slots",
             ",".join(str(s) for s in c.lowered.h_slots),
             "--image", d / "image.cftp", "--bank", d / "half.bank",
             "--init", d / "init.bin", "--segments", 4, "--steps", c.steps,
             "--entry", "step-halving", "--uses", 1, "--scope", "max-lanes",
             "--value", f"rounded:{g.fmt_name}:rup"]
    t0 = time.perf_counter()
    r = subprocess.run([str(segrun_path)] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=900)
    if not check(r.returncode == 0, f"{name}: cft-segrun certifies it, a main "
                 f"run of 2 segments and a half-step run of 4 on the halved "
                 f"bank ({time.perf_counter() - t0:.1f} s)",
                 f"rc {r.returncode}: {r.stderr.strip()[-300:]}"):
        return
    data = out.read_bytes()
    try:
        cert.parse(data)
        ok(f"{name}: the golden reader accepts it ({len(data):,} bytes)")
    except cert.Refusal as e:
        bad(f"{name}: the golden reader refuses it: {e}")
        return
    sb = {ri: {b: (states_dir / f"run-{ri}-boundary-{b}.bin").read_bytes()
               for b in range(segs + 1)} for ri, segs in ((0, 2), (1, 4))}
    progs = {0: (c.image, c.bank), 1: (c.image, c.half_bank)}
    seed = hashlib.sha256(f"tangent {name}".encode()).digest()
    try:
        t0 = time.perf_counter()
        full = cert.audit(data, None, progs, states=sb)
        ok(f"{name}: the golden audit accepts it in full, the step-halving "
           f"estimate re-derived ({time.perf_counter() - t0:.1f} s)")
        sampled = cert.audit(data, None, progs, states=sb,
                             choose={0: ("sample", 1), 1: ("sample", 2)},
                             seed=seed)
        ok(f"{name}: the golden audit accepts a sample")
    except cert.Refusal as e:
        bad(f"{name}: the golden audit refuses it: {e.name}: {e.message}")
        return
    if not audit_path:
        return
    for how, verdict, chooses in (("in full", full, ("all", "all")),
                                  ("sampled", sampled,
                                   ("sample:1", "sample:2"))):
        a = ["--cert", out, "--states", states_dir, "--seed", seed.hex(),
             "--run", "0", "--image", d / "image.cftp", "--bank",
             d / "main.bank", "--choose", chooses[0],
             "--run", "1", "--image", d / "image.cftp", "--bank",
             d / "half.bank", "--choose", chooses[1]]
        r = subprocess.run([str(audit_path)] + [str(x) for x in a],
                           capture_output=True, text=True, timeout=900)
        got = r.stdout.split("\n")
        if got and got[-1] == "":
            got = got[:-1]
        check(r.returncode == 0 and got == list(verdict.lines()),
              f"{name}: cft-audit accepts it {how}, the golden verdict line "
              f"for line", f"rc {r.returncode}: {r.stderr.strip()[-300:]}")


# ---- H: determinism and the committed files -------------------------------

def compiled_references():
    out = {}
    for base, steps in TREFS.items():
        for fmt in ("fp64", "fp256"):
            c = cftc.compile_file(SYSTEMS / f"{base}-{fmt}.cftl", steps,
                                  source=f"programs/systems/{base}-{fmt}"
                                         ".cftl")
            out.update(c.files())
    return out


def digests_main(path):
    """The child of leg H: compile what the file lists, print digests."""
    jobs = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {n: hashlib.sha256(d).hexdigest()
           for n, d in compiled_references().items()}
    for k, text in enumerate(jobs):
        try:
            c = cftc.compile_text(text, 4, source=f"corpus {k}", stem=f"g{k}")
        except lang.Refusal as e:
            out[f"g{k}"] = f"refused {e.name}"
            continue
        for n, d in c.files().items():
            out[n] = hashlib.sha256(d).hexdigest()
    print(json.dumps(out, sort_keys=True))
    return 0


def leg_determinism(work):
    section("H. determinism: two processes, two hash seeds; the committed "
            "compiled references, the variational and the `lang` stage's")
    jobs = [t for t, _w in corpus(5, "tangent determinism")]
    jf = work / "determinism.json"
    jf.write_text(json.dumps(jobs), encoding="utf-8")
    seen = []
    for seed in ("0", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--digests", str(jf)], capture_output=True,
                           text=True, env=env, timeout=900)
        if not check(r.returncode == 0, f"the compile under PYTHONHASHSEED "
                     f"{seed} ran", r.stderr.strip()[-300:]):
            return
        seen.append(json.loads(r.stdout))
    check(seen[0] == seen[1] and len(seen[0]) > 40,
          f"PYTHONHASHSEED 0 and 4242 write the same bytes: {len(seen[0])} "
          f"files (the four variational references and five generated "
          f"systems with tangents, every output)")
    files = compiled_references()
    have = sorted(p.name for p in COMPILED.iterdir()) if COMPILED.is_dir() \
        else []
    check(have == sorted(files), f"programs/systems/compiled-tangent/ holds "
          f"exactly the four variational references' {len(files)} files",
          f"it holds {len(have)}: run programs/tangent_check.py --write")
    wrong = [n for n, d in files.items()
             if (COMPILED / n).is_file() and (COMPILED / n).read_bytes() != d]
    check(not wrong, "every committed compiled variational reference is what "
          "the compiler writes, byte for byte", f"differ: {wrong[:6]}")
    v1 = LC.compiled_references()
    wrong = [n for n, d in v1.items()
             if not (LC.COMPILED / n).is_file()
             or (LC.COMPILED / n).read_bytes() != d]
    graphs = [n for n in v1 if n.endswith(".graph.json")]
    check(len(v1) == 48 and not wrong and all(
        json.loads(v1[n])["cftl_graph"] == 1 for n in graphs),
        f"the `lang` stage's 48 committed compiled files are still what the "
        f"compiler writes, byte for byte, its {len(graphs)} graphs version 1",
        f"differ: {wrong[:6]}")


# ---- I: refusals by name --------------------------------------------------

def leg_refusals():
    section("I. refusals by name, with tangent vectors")
    made = set()

    def expect(name, fn, what):
        try:
            fn()
        except lang.Refusal as e:
            if check(e.name == name, f"{name}: {what}",
                     f"refused {e.name} instead: {e}"):
                made.add(name)
            print(f"        {e}")
            return
        bad(f"{name}: {what} - accepted")

    def l96(N):
        return (f"system lorenz96\nformat fp64\nround rne\nstate x[{N}] "
                f"cyclic\ntangent v\nparam F = 8\nd/dt x[i] = fma(x[i+1] - "
                f"x[i-2], x[i-1], F - x[i])\nstep rk4, h = 1/100\n")
    l63 = SYSTEMS / "lorenz63-rk4-tangent-fp64.cftl"
    expect("tangent-mismatch", lambda: cftc.compile_text(
        "system s\nformat fp64\nstate x\ntangent v\nnext x = x * x\n"
        "next v.x = v.x * x + x * v.x\nstep map\n", 2),
        "a written tangent rounded otherwise than the rule")
    expect("tangent-scope", lambda: cftc.compile_text(
        "system s\nformat fp64\nstate x\ntangent v\nnext x = x + v.x\n"
        "step map\n", 2), "the state reading a tangent")
    expect("scratch-capacity", lambda: cftc.compile_text(l96(99), 2,
                                                         target="sw"),
           "Lorenz-96 at N = 99 with one tangent vector on the software "
           "backend's 256 slots")
    c = cftc.compile_text(l96(98), 2, target="sw")
    check(c.program.slots_used == 255, f"Lorenz-96 at N = 98 with one "
          f"tangent vector fits the software backend: "
          f"{c.program.slots_used} slots")
    c = cftc.compile_text(l96(99), 2, target="u50-rev7")
    check(c.program.slots_used == 257, f"N = 99 is accepted where the scratch "
          f"is deeper (u50-rev7): {c.program.slots_used} slots")
    tiny = TG.Target("tiny", TG.ALL_FORMATS, 100, 512, 256, 64,
                     TG.TILE_FEATURES)
    plain = cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 3,
                              target=tiny)
    check(len(plain.image_obj.insns) <= 100, f"Lorenz-63 without its tangent "
          f"fits a target that holds 100 instructions "
          f"({len(plain.image_obj.insns)})")
    expect("program-capacity", lambda: cftc.compile_file(l63, 3, target=tiny),
           "Lorenz-63 with its tangent on that target")
    expect("lane-shape", lambda: lang.run(lang.load(l63).graph, [[0, 0, 0]],
                                          1),
           "lang.run of a system with a tangent vector, given none")
    try:
        cftc.compile_file(l63, 3).scratch_block([[0, 0, 0]])
        bad("a compiled variational image's block without its tangents - "
            "accepted")
    except ValueError as e:
        ok(f"a compiled variational image's block without its tangents is "
           f"refused: {e}")
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    with tempfile.TemporaryDirectory() as tmp:
        part = Path(tmp) / "part.cftl"
        part.write_bytes(l63.read_bytes().replace(
            b"d/dt z = fma(x, y, -(beta * z))\n",
            b"d/dt z = fma(x, y, -(beta * z))\nd/dt v.x = 0\n"))
        r = subprocess.run(py + [str(part), "--steps", "3", "--out",
                                 str(Path(tmp) / "o")], capture_output=True,
                           text=True)
        check(r.returncode == 3 and "cftc: refused " in r.stderr
              and not (Path(tmp) / "o").exists(),
              f"the command line refuses a tangent written in part, by name, "
              f"exit 3, writing nothing: {r.stderr.strip()[:120]}",
              f"rc {r.returncode}: {r.stderr.strip()[-200:]}")
        r = subprocess.run(py + [str(l63), "--steps", "3", "--out",
                                 str(Path(tmp) / "o")], capture_output=True,
                           text=True)
        check(r.returncode == 0 and (Path(tmp) / "o" /
                                     "lorenz63-rk4-tangent-fp64.cftp")
              .is_file(), "the command line compiles a variational source")
    check(made == {"tangent-mismatch", "tangent-scope", "scratch-capacity",
                   "program-capacity", "lane-shape"},
          "every refusal named here was made", f"made {sorted(made)}")


# ---- J: plants ------------------------------------------------------------

class _PlantedDerivation(lang_tangent.Derivation):
    """The derivation with one rule wrong (kind), for leg J."""
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
                if self.kind == "a wrong product rule, d(ab) = da db":
                    p = N("mul", da, db)
                    return p if dc is None else N("add", p, dc)
                if self.kind == "a tangent reading the wrong primal value":
                    inner = N("mul", R(a[0]), db) if dc is None else \
                        N("fma", R(a[0]), db, dc)
                    return N("fma", da, R(a[0]), inner)
                if self.kind == "the same rule rounded otherwise":
                    s = N("add", N("mul", da, R(a[1])), N("mul", R(a[0]), db))
                    return s if dc is None else N("add", s, dc)
                if self.kind == "fma's third tangent dropped" and \
                        dc is not None:
                    return N("fma", da, R(a[1]), N("mul", R(a[0]), db))
        return super().rule(node)


DEFINITION_PLANTS = ("a wrong product rule, d(ab) = da db",
                     "fma's third tangent dropped",
                     "a tangent reading the wrong primal value",
                     "the same rule rounded otherwise")

# Each compiler plant: where it is, and so which net should see it. The
# internal check (cftc/check.py) holds the image to the lowering, so a
# plant past the IR is its to stop; a misreading of the graph in ir.py
# makes a lowering the image then computes faithfully, and only seq.py
# against the interpreter - this stage - can see it (L2's design: "the
# other net").
COMPILER_PLANTS = {
    "a tangent node dropped from the image": ("image", [
        ("regalloc.py", '        self.emit(Ins("alu", op=nd.op,',
         '        (self.emit if j != min(x for x, y in enumerate('
         'self.low.nodes) if min(y.origin) >= '
         'self.low.graph.primal_step_nodes) else (lambda _i: None))'
         '(Ins("alu", op=nd.op,')]),
    "a tangent reading the wrong primal node": ("ir", [
        ("ir.py", '                    return ("n", i)\n',
         '                    return ("n", max(i - 1, 0))\n')]),
    "the tangent's outputs rotated": ("ir", [
        ("ir.py", "            self.outs += outs\n",
         "            self.outs += outs[1:] + outs[:1]\n")]),
    "one vector reading another's inputs": ("ir", [
        ("ir.py", '                    return ("s", n * (k + 1) + i)\n',
         '                    return ("s", n + i)\n')]),
}


def plant_lyapunov(segrun_path, work):
    """The smoke test's figure on 4 lanes at t = 200, for a plant."""
    try:
        lam, _l = lyapunov_fp64(segrun_path, work, 4, 2)
    except (ArithmeticError, ValueError, ZeroDivisionError):
        return float("nan")         # a tangent that became NaN, inf or 0
    return lam


def leg_plants(rng, segrun_path, work):
    section("J. plants: wrong derivations red on D and on the exponent, the "
            "rounding-order plant red on the committed bytes, compiler "
            "plants red on seq.py")
    texts = [tref_text(b, "fp64") for b in ("lorenz63-rk4", "lorenz96-rk4")]
    texts += [t for t, _w in corpus(24, "tangent plants")]
    committed = {n: (COMPILED / f"{n}.graph.json") for n in
                 (f"{b}-{f}" for b in TREFS for f in ("fp64", "fp256"))}
    have_segrun = bool(segrun_path) and Path(segrun_path).is_file()
    if have_segrun:
        lam = plant_lyapunov(segrun_path, work / "plant-clean")
        print(f"        without a plant, the exponent on 4 lanes at t = 200: "
              f"{lam:.4f}")
    original = lang_check_mod.Derivation
    try:
        for kind in DEFINITION_PLANTS:
            class P(_PlantedDerivation):
                pass
            P.kind = kind
            lang_check_mod.Derivation = P
            tot = bad_n = systems = 0
            for text in texts:
                try:
                    g = lang.compile_text(text).graph
                except lang.Refusal:
                    continue
                a, b, _p = derivative_misses(g, rng)
                tot += a
                bad_n += b
                systems += b > 0
            moved = [n for n, p in committed.items()
                     if not p.is_file() or lang.compile_text(tref_text(
                         n.rsplit("-tangent-", 1)[0],
                         n.rsplit("-", 1)[1])).graph.to_bytes()
                     != p.read_bytes()]
            lam = plant_lyapunov(segrun_path, work / "plant") \
                if have_segrun else None
            said = (f"plant {kind!r}: {bad_n} of {tot} points differ from "
                    f"the derivative, in {systems} systems; the committed "
                    f"variational graphs it moves: {len(moved)} of "
                    f"{len(committed)}"
                    + ("" if lam is None else
                       f"; the exponent under it {lam:.4f}"))
            if kind == "the same rule rounded otherwise":
                check(bad_n == 0 and len(moved) == len(committed),
                      said + " - green on D, as the document says, and red "
                      "on the committed bytes")
            else:
                far = lam is None or not abs(lam - float(LITERATURE)) \
                    <= 10 * float(TOL_FP64)
                check(bad_n > 0 and far, said + " - red on D" +
                      ("" if lam is None else " and on the exponent"))
    finally:
        lang_check_mod.Derivation = original
    for k, (what, (where, edits)) in enumerate(COMPILER_PLANTS.items()):
        try:
            on = LC.plant_copy(edits, f"t{k}on", work)
            off = LC.plant_copy(edits + [LC.CHECK_OFF], f"t{k}off", work)
        except AssertionError as e:
            bad(f"plant {what!r}: {e}")
            continue
        names = "v, w" if "another" in what else "v"
        text = with_tangent(LC.ref_text("lorenz63-rk4", "fp64"), names)
        try:
            on.compile_text(text, 100, source="plant")
            stopped = "accepted"
        except on.InternalError as e:
            stopped = "stopped by the internal check"
            print(f"        {str(e)[:150]}")
        except Exception as e:                       # noqa: BLE001
            stopped = type(e).__name__
        # the image the compiler wrote, where its check let it through;
        # with the check off where it did not
        mod = on if stopped == "accepted" else off
        try:
            c = mod.compile_text(text, 100, source="plant")
        except Exception as e:                       # noqa: BLE001
            bad(f"plant {what!r}: with the check off it does not compile "
                f"({type(e).__name__}: {e})")
            continue
        states = LC.lanes_for(c.ir.fmt, 3, rng, 16, LC.BOX["lorenz63-rk4"])
        tans = [tangent_values(c.ir.fmt, 3, c.ir.T, rng) for _ in states]
        failing, fok, _ref = compare(c, states, tans, 100)
        if where == "image":
            check(stopped == "stopped by the internal check",
                  f"plant {what!r}: {stopped}")
        else:
            print(f"        plant {what!r}, in the IR's reading of the "
                  f"graph: {stopped} by the internal check, which holds the "
                  f"image to the lowering; seq.py against the interpreter "
                  f"is the net for it")
        check(failing or not fok, f"plant {what!r}: "
              f"{'with the check off, ' if mod is off else ''}red on "
              f"seq.py: {len(failing)} of {len(states)} lanes differ"
              + ("" if fok else ", FLAGS differ"), "no lane differs")


# ---- K: coverage ----------------------------------------------------------

def leg_coverage():
    section("K. what the stage covered")
    print(f"  {COVER['systems']} systems; tangent ops "
          f"{dict(sorted(COVER['tangent_ops'].items()))}")
    rules_out = {"fma", "add", "sub", "mul", "neg", "copysign", "cmpeq",
                 "select"}
    check(rules_out <= set(COVER["tangent_ops"]), "every operation the rules "
          "write appeared in a compiled tangent",
          f"missing {sorted(rules_out - set(COVER['tangent_ops']))}")
    pats = {(a, b, c) for a in (0, 1) for b in (0, 1) for c in (0, 1)} - \
        {(0, 0, 0)}
    seen = COVER["fma_patterns"]
    check(seen == pats, f"every activity pattern of fma's operands: "
          f"{len(seen)} of 7", f"missing {sorted(pats - seen)}")
    check(COVER["rounds"] == {"rne", "rtz", "rdn", "rup", "rmm"},
          "every attribute", f"{sorted(COVER['rounds'])}")
    check(COVER["formats"] == {"fp32", "fp64", "fp128", "fp256"},
          "every format", f"{sorted(COVER['formats'])}")
    check(COVER["integrators"] >= {"rk4", "euler", "stormer-verlet", "map"},
          "every integrator", f"{sorted(COVER['integrators'])}")
    check(COVER["vectors"] >= {1, 2}, "one tangent vector and two")
    for flag, word in ((sf.FLAG_OVERFLOW, "overflow"),
                       (sf.FLAG_INVALID, "invalid"),
                       (sf.FLAG_UNDERFLOW, "underflow"),
                       (sf.FLAG_INEXACT, "inexact")):
        check(COVER["flags"] & flag, f"a run raised {word}")


# ---- the committed references ---------------------------------------------

def write_references():
    COMPILED.mkdir(parents=True, exist_ok=True)
    files = compiled_references()
    for p in COMPILED.iterdir():
        if p.name not in files:
            p.unlink()
    for name, data in files.items():
        (COMPILED / name).write_bytes(data)
        print(f"  wrote programs/systems/compiled-tangent/{name} "
              f"({len(data)} bytes)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--segrun", help="host/cft-segrun, for legs E, F, G, J")
    ap.add_argument("--audit", help="host/cft-audit, for legs F and G")
    ap.add_argument("--corpus", type=int, default=24,
                    help="generated systems in leg B (default 24)")
    ap.add_argument("--only", default="",
                    help="a comma list of legs: refs,corpus,derivative,"
                         "lyapunov,certified,libcft,determinism,refusals,"
                         "plants")
    ap.add_argument("--write", action="store_true",
                    help="write programs/systems/compiled-tangent/ and exit")
    ap.add_argument("--digests", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.digests:
        return digests_main(a.digests)
    if a.write:
        return write_references()
    only = {x for x in a.only.split(",") if x}
    t0 = time.perf_counter()
    work = Path(tempfile.mkdtemp(prefix="tangent-check-"))

    def rng(leg):
        # one generator a leg, so that a leg's lanes and counts are the
        # same whichever legs ran before it (--only)
        return random.Random(f"tangent check {leg}")
    segrun_path = Path(a.segrun).resolve() if a.segrun else None
    audit_path = Path(a.audit).resolve() if a.audit else None
    legs = [("refs", lambda: leg_references(rng("refs"))),
            ("corpus", lambda: leg_corpus(a.corpus, rng("corpus"))),
            ("derivative", lambda: leg_derivative(rng("derivative"))),
            ("lyapunov", lambda: leg_lyapunov(segrun_path, work)),
            ("certified", lambda: leg_certified(segrun_path, audit_path,
                                                work)),
            ("libcft", lambda: leg_libcft(segrun_path, audit_path,
                                          rng("libcft"), work)),
            ("determinism", lambda: leg_determinism(work)),
            ("refusals", leg_refusals),
            ("plants", lambda: leg_plants(rng("plants"), segrun_path, work))]
    try:
        for name, fn in legs:
            if only and name not in only:
                continue
            t = time.perf_counter()
            fn()
            print(f"  ({name}: {time.perf_counter() - t:.1f} s)", flush=True)
        if not only or {"refs", "corpus"} <= only:
            leg_coverage()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    dt = time.perf_counter() - t0
    print(f"\ntangent_check: {LC.TALLY.ok} ok, {LC.TALLY.bad} FAIL, "
          f"{LC.TALLY.skip} SKIP in {dt:.0f} s")
    for f in LC.FAILURES[:20]:
        print(f"  FAIL  {f}")
    return 1 if LC.TALLY.bad else 0


if __name__ == "__main__":
    sys.exit(main())
