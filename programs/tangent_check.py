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
     run, a half-step run on the halved bank, a step-halving estimate) -
     Kepler's, whose image holds routines, among them (C4), and since M1's
     build, item 4, the three holding the math library's six
     (Lotka-Volterra, the diodes, the culture); the golden reader and
     audit and cft-audit accept each. A segment that marks a lane
     (STATUS[6]) fails here by name: version 1 certifies the machine's
     guess, and this leg replays nothing (item 5's). The six's references
     are skipped by name on a host without mpmath, which builds them
  H  determinism: two processes under two PYTHONHASHSEEDs; the committed
     programs/systems/compiled-tangent/ is what the compiler writes, and
     the `lang` stage's 64 committed files still are (the six's
     references held only where mpmath imports, skipped by name elsewhere)
  I  refusals by name, the language's and the compiler's, with tangents;
     a quotient and a root with two tangent vectors compiled for the
     software targets and run as the interpreter runs them, and refused
     `target-feature` on revision 7's (C4)
  J  plants: three wrong derivations, red on D and on the exponent; the
     same rule rounded otherwise, green on D and red on the committed
     bytes - every committed graph holding a product of two tangent-
     carrying operands, and only those (Lotka-Volterra's and the diodes'
     multiply a state value only by a param); three in a copy of the
     compiler, each stopped by its internal check and, with that off, red
     on seq.py
  K  coverage: every operation the rules write, every activity pattern
     of fma, every format, attribute and integrator, one and two vectors
  L  the quotient's and the root's rules (L4): written shapes and
     lang_check's generated sources that divide or take a root, with
     tangent vectors - the tangent exactly against this stage's own dual
     numbers (the quotient rule; the root as the exact evaluation takes
     it) and against a central difference at 2^-64 in exact rationals;
     the primal unchanged; each compiled, its routines inlined (C4), and
     run on seq.py against the interpreter at 1, 2 and 5 steps, states,
     every tangent and FLAGS, at every format; the specials bit for bit;
     and plants - a root without its 2 and a quotient's wrong sign red on
     both, a right root derivative written through r * r = a green on the
     difference and red on the exact check
  M  the math library's six rules (M1's build, item 3), golden: written
     shapes and generated systems holding exp, expm1, exp2, log, log1p
     and log2, with tangent vectors - the tangent exactly against this
     stage's own dual numbers (each value as the exact evaluation takes
     it, L the stage's own: transcend.log of 2) and against a central
     difference in high precision (eps = 2^-256 of 1,024-bit values,
     within 2^-300, ln 2 exact in L's place); the primal unchanged; each
     rule's rounding on y = f(a), every format and attribute, bit for
     bit, its exact value before its last rounding the derivative within
     its operands' roundings; the specials below each domain and at the
     poles; and plants - log's rule rounded otherwise (green on both
     exact checks, red on the rounding), L rounded the wrong way (red on
     all three), log's select form dropped (red below the domain), a
     golden function swapped for a sibling's (red on the rounding's
     derivative). The compiler carries the six since M1's build, item 4,
     and its committed references holding them are legs G, H and J's;
     compiled images of generated sources holding them, a marked lane
     replayed, are item 5's legs. The six's golden functions need
     mpmath, so on a host without it this leg is skipped by name, as are
     legs G and H's references holding the six; legs A to L never need it
     otherwise

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
from cft_golden import FORMATS, cert, lang, seq           # noqa: E402
from cft_golden import softfloat as sf                    # noqa: E402
from cft_golden.lang import check as lang_check_mod       # noqa: E402
from cft_golden.lang import constants as K                # noqa: E402
from cft_golden.lang import tangent as lang_tangent       # noqa: E402
from cft_golden.lang.graph import Node                    # noqa: E402
import lang_check as LC                                   # noqa: E402

SYSTEMS = ROOT / "programs" / "systems"
COMPILED = SYSTEMS / "compiled-tangent"
TREFS = {"lorenz63-rk4-tangent": 100, "lorenz96-rk4-tangent": 20,
         "kepler-sv-tangent": 10,       # Kepler's: routines (C4)
         # the math library's six and their rules (M1's build, item 4):
         # Lotka-Volterra in logarithmic variables (exp), two diodes
         # (expm1, log1p) and a self-heating culture (exp2, log, log2)
         "lotkavolterra-rk4-tangent": 10, "diode-rk4-tangent": 10,
         "culture-rk4-tangent": 10}
# The references holding the six: compiled only where mpmath imports, since
# the routines' generator derives their constants through it (a leg that
# compiles them skips them by name elsewhere), and run on lanes whose boxes
# keep the logarithms in their domains; leg G's lanes mark none, and the leg
# fails by name a segment that marks one
MATH_TREFS = ("lotkavolterra-rk4-tangent", "diode-rk4-tangent",
              "culture-rk4-tangent")
MATH_BOX = {"lotkavolterra-rk4": [(-1, 1), (-2, Fraction(1, 2))],
            "diode-rk4": [(0, 4), (0, 4)],
            "culture-rk4": [(Fraction(1, 20), Fraction(19, 20)), (0, 2)]}
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
    # 0, 1 and -1 by L3's rules, 2 by the square root's (L4), and L by
    # exp2's and log2's (M1's build, item 3), only where one is held
    allowed = {Fraction(0), Fraction(1), Fraction(-1), Fraction(2)}
    if {"exp2", "log2"} & set(g.op_counts("step")):
        allowed.add(_ln2(g.fmt, g.rnd))
    return added <= allowed and by_value(g) == by_value(g0)


# ---- D: the derivative, this stage's own dual numbers ---------------------

def _sgn(x, zero=1):
    return -1 if x < 0 else (zero if x == 0 else 1)


ROOT_BITS = 256


def _root(q):
    """A square root as the exact evaluations take it (cft_golden/lang/
    graph.py's exact_root, computed again here): exact where q is a
    rational's square, otherwise rounded down to a multiple of 2^-256; an
    ArithmeticError below zero."""
    q = Fraction(q)
    if q < 0:
        raise ArithmeticError(f"the square root of {q}")
    n, d = q.numerator, q.denominator
    rn, rd = math.isqrt(n), math.isqrt(d)
    if rn * rn == n and rd * rd == d:
        return Fraction(rn, rd)
    return Fraction(math.isqrt((n << (2 * ROOT_BITS)) // d), 1 << ROOT_BITS)


TRANS_BITS = 1024
_MP = []


def _trans(op, q):
    """One of the math library's six as the exact evaluations take it
    (cft_golden/lang/graph.py's exact_transcendental, computed again here):
    exact where the value is rational - exp(0), exp2(n), log(1),
    log2(2^k) - otherwise mpmath's value at 1,024 bits of the argument
    rounded to nearest at 1,024 bits; expm1 is exp - 1 and log1p log(1 +
    a); an ArithmeticError at a logarithm's pole or below its domain, or
    past 2^+-1048576."""
    q = Fraction(q)
    if op == "expm1":
        return _trans("exp", q) - 1
    if op == "log1p":
        return _trans("log", 1 + q)
    if op in ("log", "log2") and q <= 0:
        raise ArithmeticError(f"{op}({q}), at or below zero")
    if op == "exp":
        if q == 0:
            return Fraction(1)
        if abs(q) > 1 << 21:
            raise ArithmeticError(f"exp({q}) is past 2^+-1048576")
    if op == "exp2":
        if abs(q) > 1 << 20:
            raise ArithmeticError(f"exp2({q}) is past 2^+-1048576")
        if q.denominator == 1:
            return Fraction(2) ** q.numerator
    n, d = q.numerator, q.denominator
    if op == "log" and q == 1:
        return Fraction(0)
    if op == "log2" and n & (n - 1) == 0 and d & (d - 1) == 0:
        return Fraction(n.bit_length() - d.bit_length())
    if not _MP:
        import mpmath
        ctx = mpmath.MPContext()
        ctx.prec = TRANS_BITS
        _MP.append((mpmath.libmp, ctx))
    lib, ctx = _MP[0]
    x = ctx.make_mpf(lib.from_rational(n, d, TRANS_BITS, lib.round_nearest))
    y = {"exp": ctx.exp, "exp2": lambda v: ctx.power(2, v), "log": ctx.log,
         "log2": lambda v: ctx.log(v) / ctx.ln2}[op](x)
    sign, man, exp, bc = y._mpf_
    man = int(man)
    if man == 0 or abs(exp + bc) > 1 << 20:
        raise ArithmeticError(f"{op}({q}) is past 2^+-1048576")
    v = Fraction(man << exp) if exp >= 0 else Fraction(man, 1 << -exp)
    return -v if sign else v


_LN2 = {}


def _ln2(fmt, rnd):
    """The stage's own L, as an exact rational: transcend.log of 2 at the
    format under the attribute (M1's question 6) - the decided definition,
    which the language computes otherwise (constants.ln2_bits)."""
    from cft_golden import transcend
    key = (fmt.name, rnd)
    if key not in _LN2:
        two = K.round_once(fmt, sf.RND_RNE, Fraction(2))[0]
        _LN2[key] = K.value_of(fmt, transcend.compute(fmt, "log", two, 0,
                                                      rnd)[0])
    return _LN2[key]


SIX = ("exp", "expm1", "exp2", "log", "log1p", "log2")


def _dual(op, a, tie=0, zero=1, L=None):
    """One operation on (value, derivative) pairs, exactly, by calculus -
    with the rule table's choices at its measure-zero points (a tie gives
    the first operand's, a zero's sign is +) - written again here, not
    read from the derivation. tie=1 and zero=-1 are the other choices,
    which a placed point must tell apart from the table's; a value is
    the same under any of them. The six (M1) take each value as the exact
    evaluations take it (_trans), and ln 2 as `L`, the stage's own."""
    v = [p[0] for p in a]
    d = [p[1] for p in a]
    if op in SIX:
        x, dx = v[0], d[0]
        if op in ("exp", "expm1"):
            e = _trans("exp", x)
            return (e if op == "exp" else e - 1), e * dx
        if op == "exp2":
            r = _trans("exp2", x)
            return r, L * r * dx
        if op == "log":
            return _trans("log", x), dx / x
        if op == "log2":
            return _trans("log2", x), dx / (L * x)
        return _trans("log1p", x), dx / (1 + x)
    if op == "add":
        return v[0] + v[1], d[0] + d[1]
    if op == "sub":
        return v[0] - v[1], d[0] - d[1]
    if op == "mul":
        return v[0] * v[1], d[0] * v[1] + v[0] * d[1]
    if op == "fma":
        return v[0] * v[1] + v[2], d[0] * v[1] + v[0] * d[1] + d[2]
    if op == "div":                     # the quotient rule, not the form
        return v[0] / v[1], (d[0] * v[1] - v[0] * d[1]) / (v[1] * v[1])
    if op == "sqrt":
        r = _root(v[0])
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
    L = _ln2(g.fmt, g.rnd) if {"exp2", "log2"} & \
        {op for op, _a, _l in sec.nodes} else None

    def get(r):
        return nodes[int(r[1:])] if r[0] == "n" else vals[r[0]][int(r[1:])]
    for op, args, _l in sec.nodes:
        nodes.append(_dual(op, [get(a) for a in args], tie, zero, L))
    return [get(o)[1] for o in sec.out]


def _q(rng):
    return Fraction(rng.randint(-5000, 5000), rng.randint(1, 4000))


def derivative_misses(g, rng, points=2):
    """(points tried, points where a tangent section's exact value is not
    the dual numbers' derivative of the section it differentiates, points
    placed with one component equal to another, points placed with one
    component zero). About half the points are placed, the tangent random,
    so that a tie or a zero there has operands whose tangents differ;
    each is counted where it is placed (a system of one component has no
    other to tie with, so its every placement is a zero)."""
    bad_n = tot = ties = zeros = 0
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
                ties += 1
            elif r < 0.5:
                st[i] = Fraction(0)
                zeros += 1
            tv = [_q(rng) for _ in range(n)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            try:
                want = dual_derivative(g, primal, st, tv, pa, la)
            except ArithmeticError:
                # a zero divisor, a negative root's argument, the root's
                # derivative at zero (L4): the point decides nothing
                continue
            tot += 1
            try:
                got = g.exact_eval(tangent, st, pa, la, tangent=tv)
            except ArithmeticError:
                bad_n += 1
                continue
            bad_n += got != want
    return tot, bad_n, ties, zeros


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
    tot = bad_n = ties = zeros = 0
    for g in graphs:
        a, b, t, z = derivative_misses(g, rng, 4)
        tot += a
        bad_n += b
        ties += t
        zeros += z
    check(bad_n == 0 and tot > 100, f"{len(graphs)} systems, {tot} points, "
          f"{ties + zeros} of them placed ({ties} with one component set "
          f"equal to another, {zeros} with one set to zero): the tangent "
          f"sections evaluated exactly equal the exact derivative of the "
          f"step at every one", f"{bad_n} points differ")
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
    # version 1 (--format-version 1): cft-segrun writes version 2 by
    # default since version 2's C half, and this leg reads version 1's
    args = ["--format-version", "1", "--out", out, "--states", states,
            "--open", "--device", "sw"]
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
        if base in MATH_TREFS and not LC.have_mpmath():
            skip(f"G: {base} at fp64 and fp256", "python has no mpmath "
                 "module, through which the math library's routines are "
                 "built (python/cft_golden/mathlib.py)")
            continue
        for fmt in ("fp64", "fp256"):
            src = SYSTEMS / f"{base}-{fmt}.cftl"
            c = cftc.compile_file(src, steps,
                                  source=f"programs/systems/{base}-{fmt}.cftl")
            certify(c, f"{base}-{fmt}", segrun_path,
                    audit_path if have_audit else None, rng, work)


def certify(c, name, segrun_path, audit_path, rng, work):
    """lang_check's certify, its lanes given tangents. A certificate of
    version 1 holds what the machine ran, a marked lane's guess included
    (STATUS[6] on its segment), and this leg replays nothing - the replay
    in the stages is M1's build, item 5's - so a segment that marks a lane
    fails here, by name, rather than pass on a guess."""
    g = c.ir
    d = work / "certs" / name
    d.mkdir(parents=True, exist_ok=True)
    key = name.split("-tangent")[0]
    box = MATH_BOX.get(key) or LC.BOX.get(key)
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
    # version 1 (--format-version 1): cft-segrun writes version 2 by
    # default since version 2's C half, and this leg's audits are version 1's
    args = ["--format-version", "1", "--out", out, "--states", states_dir,
            "--open", "--device", "sw"]
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
        parsed = cert.parse(data)
        ok(f"{name}: the golden reader accepts it ({len(data):,} bytes)")
    except cert.Refusal as e:
        bad(f"{name}: the golden reader refuses it: {e}")
        return
    marked = [(ri, k) for ri, run in enumerate(parsed.runs)
              for k, s in enumerate(run.chain)
              if s.status & seq.STATUS_MARKED]
    if not check(not marked, f"{name}: no segment marks a lane (STATUS[6] "
                 f"clear in every segment of both runs)",
                 f"a lane marked in run and segment {marked[:4]}: a "
                 f"routine's undecided guess, which this leg does not "
                 f"replay (M1's build, item 5)"):
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

def compiled_references(math=True):
    """{name: bytes} of every committed variational reference's outputs;
    with `math` false, of those not holding the six (MATH_TREFS), which a
    host without mpmath cannot compile."""
    out = {}
    for base, steps in TREFS.items():
        if base in MATH_TREFS and not math:
            continue
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
           for n, d in compiled_references(LC.have_mpmath()).items()}
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
    math = LC.have_mpmath()
    if not math:
        skip("H: the references holding the math library's six "
             f"({', '.join(MATH_TREFS)})", "python has no mpmath module, "
             "through which their routines are built (python/cft_golden/"
             "mathlib.py); the others are held below")
    nrefs = 2 * len([b for b in TREFS if math or b not in MATH_TREFS])
    check(seen[0] == seen[1] and len(seen[0]) > 40,
          f"PYTHONHASHSEED 0 and 4242 write the same bytes: {len(seen[0])} "
          f"files (the {nrefs} variational references and five generated "
          f"systems with tangents, every output)")
    files = compiled_references(math)
    held = {f"{b}-{f}" for b in MATH_TREFS for f in ("fp64", "fp256")}
    have = sorted(p.name for p in COMPILED.iterdir()
                  if math or not any(p.name.startswith(h + ".")
                                     for h in held)) \
        if COMPILED.is_dir() else []
    check(have == sorted(files), f"programs/systems/compiled-tangent/ holds "
          f"exactly the {nrefs} variational references' "
          f"{len(files)} files, Kepler's and the six's references' with "
          f"routines among them",
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
    nv1 = 16 * (len(LC.REFS) + len(LC.ROUTINE_REFS))
    check(len(v1) == nv1 and not wrong and all(
        json.loads(v1[n])["cftl_graph"] == 1 for n in graphs),
        f"the `lang` stage's {nv1} committed compiled files are still what "
        f"the compiler writes, byte for byte, its {len(graphs)} graphs "
        f"version 1", f"differ: {wrong[:6]}")


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
    # L4 and C4: a quotient and a root with tangent vectors, whose rules
    # divide too - compiled for the software targets, the same image for
    # each, and run as the interpreter runs it; refused by name on revision
    # 7's, which have no flag control
    routine = ("system dv\nformat fp64\nstate x, y\ntangent v, w\n"
               "d/dt x = y / sqrt(x * x + 1)\nd/dt y = -x\n"
               "step rk4, h = 1/16\n")
    images = set()
    for t in LC.SW_TARGETS:
        c = cftc.compile_text(routine, 2, target=t)
        images.add(c.image)
    g = c.ir
    states = [[K.round_once(g.fmt, sf.RND_RNE, Fraction(v, 7))[0]] * 2
              for v in (3, -11, 0)]
    tans = [[[K.round_once(g.fmt, sf.RND_RNE, Fraction(u, 5))[0]] * 2
             for u in (1, -2)] for _ in states]
    failing, first, fok, _ref = LC.compare_routine(c, states, tans, 2)
    check(len(images) == 1 and not failing and fok,
          f"a quotient and a root with two tangent vectors compile for "
          f"{', '.join(LC.SW_TARGETS)} - one image - and run as the "
          f"interpreter runs them, states, both tangents and FLAGS, a zero "
          f"lane among them ({c.manifest['routines']['calls']} routines a "
          f"step)", f"{len(failing)} lanes differ from step {first}")
    for t in LC.REV7_TARGETS:
        expect("target-feature", lambda: cftc.compile_text(routine, 2,
                                                           target=t),
               f"the same on {t}, which has no flag control for its "
               f"routines (C4)")
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
                   "program-capacity", "lane-shape", "target-feature"},
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


def products_of_two_tangents(graph):
    """How many products of the section the derivation reads - the field
    for a flow, the step for a map - multiply two operands that both carry
    a tangent (each reading the state): the product rule's branch that
    leg J's "the same rule rounded otherwise" plants. A constant, a param
    or a lane param carries none."""
    sec = graph.field if graph.field is not None else graph.step
    active = []
    count = 0

    def carries(ref):
        return ref[0] in "st" or (ref[0] == "n" and active[int(ref[1:])])
    for op, args, _label in sec.nodes:
        active.append(any(carries(a) for a in args))
        if op in ("mul", "fma") and carries(args[0]) and carries(args[1]):
            count += 1
    return count


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
    # each committed source's graph without a plant (checking a source needs
    # no mpmath, the six's included)
    original_graphs = {n: lang.compile_text(tref_text(
        n.rsplit("-tangent-", 1)[0], n.rsplit("-", 1)[1])).graph
        for n in committed}
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
                a, b, _t, _z = derivative_misses(g, rng)
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
                # it changes the product rule where both operands carry a
                # tangent, so it moves exactly the committed graphs holding
                # such a product: every one until M1's build, item 4, whose
                # Lotka-Volterra and diode multiply a state value only by a
                # param
                reach = sorted(n for n in committed if products_of_two_tangents(
                    original_graphs[n]))
                check(bad_n == 0 and reach and sorted(moved) == reach,
                      said + " - green on D, as the document says, and red "
                      f"on the committed bytes: it moves each of the "
                      f"{len(reach)} that holds a product of two tangent-"
                      f"carrying operands, and no other",
                      f"moved {sorted(moved)}, holding one {reach}")
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


# ---- L: the quotient's and the root's rules (L4) ---------------------------
#
# d(a / b) = fma(-r, db, da) / b and d sqrt(a) = da / (2 * r), r the
# operation's own result (docs/LANGUAGE.md, "The quotient and the root").
# The derivative exactly against this stage's own dual numbers and by a
# central difference, the primal unchanged, the specials bit for bit, and
# plants; and since parcel C4, which compiles both as inlined routines,
# each system compiled and run on seq.py against the interpreter (leg I
# makes revision 7's `target-feature` refusal). Until C4 this leg was the
# golden model's alone.

L4_SHAPES = {
    "map": "system m\nformat fp64\nstate x, y, z\ntangent v\n"
           "param p = 3/7\nnext x = x / y + sqrt(z * z + 1)\n"
           "next y = fma(y, p, 1) / (x * x + 2)\n"
           "next z = sqrt(abs(x - y)) / p\nstep map\n",
    "rk4": "system f\nformat fp128\nround rdn\nstate x, y\ntangent v\n"
           "let q = x / (y * y + 1)\nd/dt x = q - sqrt(abs(x) + 1)\n"
           "d/dt y = x / sqrt(y * y + 2)\nstep rk4, h = 1/8\n",
    "stormer-verlet": "system k\nformat fp256\nstate q, p\ntangent v\n"
                      "d/dt q = p / sqrt(p * p + 1)\n"
                      "d/dt p = -(q / sqrt(q * q + 4))\n"
                      "step stormer-verlet, h = 1/16, q = (q), p = (p)\n",
    "euler, two vectors": "system e\nformat fp32\nround rup\nstate x\n"
                          "tangent v, w\nd/dt x = 1 / (x * x + 1)\n"
                          "step euler, h = 1/8\n",
}
FD_EPS = Fraction(1, 1 << 64)
FD_TOL = Fraction(1, 1 << 100)


def fd_misses(g, rng, points=2):
    """(points, points where a tangent component is not the central
    difference (S(x + eps v) - S(x - eps v)) / (2 eps) of the section S it
    differentiates, in exact rationals at eps = 2^-64 - each root the
    exact evaluation's, to 2^-256 - within 2^-100 max(1, |tangent|)): the
    derivative itself, whatever the root's convention. Unplaced random
    points, since a difference is no derivative at a kink; an undefined
    point decides nothing."""
    tot = bad_n = 0
    for primal, tangent in (("field", "tangent_field"),
                            ("step", "tangent_step")):
        if g.section(primal) is None:
            continue
        for _ in range(points):
            st = [_q(rng) for _ in range(g.n_state)]
            tv = [_q(rng) for _ in range(g.n_state)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            try:
                up = g.exact_eval(primal, [s + FD_EPS * t for s, t in
                                           zip(st, tv)], pa, la)
                dn = g.exact_eval(primal, [s - FD_EPS * t for s, t in
                                           zip(st, tv)], pa, la)
                got = g.exact_eval(tangent, st, pa, la, tangent=tv)
            except ArithmeticError:
                continue
            tot += 1
            bad_n += any(abs((u - d) / (2 * FD_EPS) - t) >
                         FD_TOL * max(1, abs(t))
                         for u, d, t in zip(up, dn, got))
    return tot, bad_n


class _L4Plant(lang_tangent.Derivation):
    """The derivation with the quotient's or the root's rule wrong (kind),
    or right and written through r * r = a."""
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        if node.op == "sqrt" and self.of(a[0]) is not None:
            da = self.of(a[0])
            if self.kind == "the root without its 2":
                return N("div", da, R(node))
            if self.kind == "the root through r * r = a":
                return N("div", N("mul", da, R(node)),
                         N("mul", self.two, R(a[0])))
        if node.op == "div" and self.kind == "the quotient's sign":
            da, db = self.of(a[0]), self.of(a[1])
            if da is not None and db is not None:
                return N("div", N("fma", R(node), db, da), R(a[1]))
        return super().rule(node)


def l4_texts(count, seed):
    """The written shapes, then generated sources that divide or take a
    root (lang_check's leg K generator), each with a tangent vector:
    (text, what)."""
    out = [(t, f"shape {s}") for s, t in L4_SHAPES.items()]
    for k in range(count):
        text, _line = LC.g_routine(random.Random(f"{seed} {k}"), k)
        if "\ntangent " not in text:
            text = with_tangent(text, "v, w" if k % 5 == 4 else "v")
        out.append((text, f"generated {k}"))
    return out


def l4_graphs(texts):
    graphs = []
    for text, what in texts:
        try:
            graphs.append((lang.compile_text(text, what).graph, text, what))
        except lang.Refusal as e:
            if e.name not in LC.ARTIFACTS:
                bad(f"{what}: the language refused {e}")
    return graphs


def leg_routines(count, rng):
    section(f"L. the quotient's and the root's rules (L4): {len(L4_SHAPES)} "
            f"written shapes and {count} generated systems that divide or "
            f"take a root, with tangent vectors - the derivative exactly and "
            f"by a central difference, the primal unchanged, each compiled "
            f"and run against the interpreter (C4), the specials, plants")
    t0 = time.perf_counter()
    graphs = l4_graphs(l4_texts(count, "tangent routines"))
    tot = bad_n = ftot = fbad = 0
    changed = []
    for g, text, what in graphs:
        a, b, _t, _z = derivative_misses(g, rng, 3)
        tot, bad_n = tot + a, bad_n + b
        a, b = fd_misses(g, rng, 2)
        ftot, fbad = ftot + a, fbad + b
        fmt = g.fmt
        states = LC.lanes_for(fmt, g.n_state, rng, 3)
        states += LC.special_lanes(fmt, g.n_state, states[0], rng)
        if not primal_unchanged(g, without_tangent(text), states, 2):
            changed.append(what)
    check(bad_n == 0 and tot >= 3 * len(graphs), f"{len(graphs)} systems, "
          f"{tot} points: the tangent sections evaluated exactly equal this "
          f"stage's own derivative - the quotient by the quotient rule, "
          f"the root as the exact evaluation takes it", f"{bad_n} differ")
    check(fbad == 0 and ftot >= 2 * len(graphs), f"{ftot} points: every "
          f"tangent component within 2^-100 of the central difference at "
          f"eps = 2^-64, in exact rationals", f"{fbad} differ")
    check(not changed, f"the primal unchanged in each: its states and flags "
          f"without the tangent, on lanes that overflow, hold a signalling "
          f"NaN and hold subnormals, its graph's lines",
          f"changed: {changed[:4]}")
    # compiled (C4): each system's image, its routines inlined, on seq.py
    # against the interpreter - states, every tangent and FLAGS
    held, missed, formats = 0, [], set()
    for g, text, what in graphs:
        try:
            c = cftc.compile_text(text, 5, source=what)
        except lang.Refusal as e:
            missed.append(f"{what}: refused {e.name}: {e.sentence[:80]}")
            continue
        fmt = g.fmt
        states = LC.lanes_for(fmt, g.n_state, rng, 3)
        states += LC.special_lanes(fmt, g.n_state, states[0], rng)
        states.append([0] * g.n_state)
        tans = [[LC.lanes_for(fmt, g.n_state, rng, 1)[0] for _ in g.tangent]
                for _ in states]
        failing, first, fok, _ref = LC.compare_routine(c, states, tans, 5)
        if failing or not fok:
            missed.append(f"{what}: {len(failing)} lanes from step {first}, "
                          f"FLAGS {'equal' if fok else 'differ'}")
        else:
            held += 1
            formats.add(fmt.name)
    check(not missed and formats == {"fp32", "fp64", "fp128", "fp256"},
          f"{held} of them compiled for the software backend, their routines "
          f"inlined, and run on seq.py as the interpreter runs them at 1, 2 "
          f"and 5 steps - states, every tangent and FLAGS, on lanes that "
          f"overflow, hold a signalling NaN, hold subnormals and hold zeros - "
          f"at {', '.join(sorted(formats))}", "; ".join(missed[:4]))
    # the specials, bit for bit, against the rules computed with softfloat
    fmt = FORMATS["fp64"]

    def b(v):
        return K.round_once(fmt, sf.RND_RNE, Fraction(v))[0]
    sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
    root = lang.compile_text("system s\nformat fp64\nstate x, y\ntangent v\n"
                             "next x = x\nnext y = sqrt(x)\nstep map\n").graph
    quo = lang.compile_text("system s\nformat fp64\nstate x, y, z\n"
                            "tangent v\nnext x = x\nnext y = y\n"
                            "next z = x / y\nstep map\n").graph
    cases = [(root, [0, 0], [b(3), 0], 1, inf, sf.FLAG_DIVZERO),
             (root, [sign, 0], [b(3), 0], 1, inf ^ sign, sf.FLAG_DIVZERO),
             (root, [0, 0], [0, 0], 1, qnan, sf.FLAG_INVALID),
             (root, [b(4), 0], [b(3), 0], 1, b(Fraction(3, 4)), 0),
             (quo, [b(1), 0, 0], [b(1), b(1), 0], 2, inf ^ sign,
              sf.FLAG_DIVZERO),
             (quo, [b(6), b(3), 0], [b(7), b(2), 0], 2, b(1), 0)]
    miss = []
    for g, st, tv, comp, want, flags in cases:
        r = lang.run(g, [st], 1, tangents=[[tv]])
        if (r.tangents[0][0][comp], r.flags) != (want, flags):
            miss.append(f"{g.op_counts()} at {[hex(x) for x in st]}: "
                        f"{hex(r.tangents[0][0][comp])} FLAGS {r.flags:#x}")
    check(not miss, f"the rules at their specials, bit for bit: the root's "
          f"at +0 and -0 an infinity with divide-by-zero, at 0 along 0 a "
          f"NaN with invalid, exact at a square; the quotient's at a zero "
          f"divisor an infinity, exact at 6/3", "; ".join(miss))
    # the plants
    texts = l4_texts(12, "tangent routine plants")
    original = lang_check_mod.Derivation
    try:
        for kind in ("the root without its 2", "the quotient's sign",
                     "the root through r * r = a"):
            class P(_L4Plant):
                pass
            P.kind = kind
            lang_check_mod.Derivation = P
            ex = fd = ex_tot = fd_tot = 0
            for g, _text, _what in l4_graphs(texts):
                a, b_, _t, _z = derivative_misses(g, rng, 2)
                ex_tot, ex = ex_tot + a, ex + b_
                a, b_ = fd_misses(g, rng, 2)
                fd_tot, fd = fd_tot + a, fd + b_
            said = (f"plant {kind!r}: the exact check {ex} of {ex_tot} "
                    f"points, the central difference {fd} of {fd_tot}")
            if kind == "the root through r * r = a":
                check(ex > 0 and fd == 0, said + " - a right derivative in "
                      "another form: green on the difference, red on the "
                      "exact check, which holds the rule's form")
            else:
                check(ex > 0 and fd > 0, said + " - red on both")
    finally:
        lang_check_mod.Derivation = original
    print(f"  ({time.perf_counter() - t0:.1f} s)")


# ---- M: the math library's six rules (M1's build, item 3), golden ----------
#
# exp: r * da; expm1: (1 + r) * da; exp2: (L * r) * da; log: select(r == r,
# da / a, r); log2: select(r == r, da / (L * a), r); log1p: select(r == r,
# da / (1 + a), r) - r the function's own result, L ln 2 rounded once at the
# program's format under its attribute (docs/LANGUAGE.md, "The rules"). Dual
# numbers in exact rationals have no exp, so beside them - each value as the
# exact evaluations take it - a central difference in high precision holds
# the derivative itself (M1's question 10, mpmath accepted). The compiler
# carries the six since item 4; compiled images of generated sources holding
# them are item 5's legs (the committed references are legs G, H and J's).

M1_SHAPES = {
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
HP_EPS = Fraction(1, 1 << 256)
HP_TOL = Fraction(1, 1 << 300)


def _m1_expr(rng, names, depth):
    """A random expression with the six, each of an operand that reads one
    of `names`, a logarithm's a magnitude plus one half the time."""
    if depth <= 0 or rng.random() < 0.3:
        return rng.choice(names + ["2", "(1/3)", "0.5"])
    k = rng.choice(["+", "-", "*", "/", "fma", "six", "six", "six"])

    def sub():
        return _m1_expr(rng, names, depth - 1)
    if k == "six":
        fn = rng.choice(SIX)
        inner = f"{sub()} * {rng.choice(names)}"
        if fn.startswith("log") and rng.random() < 0.5:
            inner = f"abs({inner}) + 1"
        return f"{fn}({inner})"
    if k == "fma":
        return f"fma({sub()}, {sub()}, {sub()})"
    return f"({sub()} {k} {sub()})"


def m1_texts(count, seed):
    """The written shapes, then generated systems with the six, one or two
    tangent vectors, every integrator, format and attribute: (text,
    what)."""
    out = [(t, f"shape {s}") for s, t in M1_SHAPES.items()]
    rng = random.Random(seed)
    for k in range(count):
        fmt = ("fp32", "fp64", "fp128", "fp256")[k % 4]
        rnd = rng.choice(("rne", "rtz", "rdn", "rup", "rmm"))
        integ = ("map", "rk4", "euler", "stormer-verlet")[(k // 4) % 4]
        vecs = "v, w" if k % 5 == 4 else "v"
        head = f"system m{k}\nformat {fmt}\nround {rnd}\n"
        if integ == "stormer-verlet":
            text = (head + f"state q, p\ntangent {vecs}\nparam c = 3/4\n"
                    f"d/dt q = {_m1_expr(rng, ['p', 'c'], 2)} + c * p\n"
                    f"d/dt p = {_m1_expr(rng, ['q', 'c'], 2)} - q\n"
                    f"step stormer-verlet, h = 1/16, q = (q), p = (p)\n")
        else:
            word = "next" if integ == "map" else "d/dt"
            names = ["x", "y", "c"]
            step = "step map" if integ == "map" else f"step {integ}, h = 1/32"
            text = (head + f"state x, y\ntangent {vecs}\nparam c = 2/3\n"
                    f"{word} x = {_m1_expr(rng, names, 2)} + c\n"
                    f"{word} y = {_m1_expr(rng, names, 2)} - y\n{step}\n")
        out.append((text, f"generated {k}"))
    return out


def m1_graphs(texts):
    graphs = []
    for text, what in texts:
        try:
            graphs.append((lang.compile_text(text, what).graph, text, what))
        except lang.Refusal as e:
            # a fold of a constant the language refuses: a power past every
            # format, or one that overflows; anything else is a defect
            if e.name not in LC.ARTIFACTS | {"constant-range",
                                              "constant-overflow",
                                              "constant-rounds-to-zero"}:
                bad(f"{what}: the language refused {e}")
    return graphs


def hp_misses(g, rng, points=2):
    """(points, points where a tangent component is not the central
    difference in high precision): (S(x + eps v) - S(x - eps v)) / (2 eps)
    of the primal section S at eps = 2^-256, each of the six the exact
    evaluation's 1,024-bit value, against the tangent section, within
    2^-300 max(1, |t|). L is ln 2 rounded once: the const equal to the
    stage's own L is evaluated as ln 2 to 1,100 bits, so the rules are the
    derivative itself - and a graph whose L is another keeps it and
    misses by its rounding, 2^-p and more. Unplaced random points; an
    undefined one decides nothing."""
    import mpmath
    ctx = mpmath.MPContext()
    ctx.prec = 1100
    _s, man, exp, _b = ctx.mpf(ctx.ln2)._mpf_
    ln2 = Fraction(int(man), 1 << -exp)
    L = _ln2(g.fmt, g.rnd)
    g2 = g.copy(const=[(ln2 if v == L and fa is None else v, fa, b, f)
                       for v, fa, b, f in g.const])
    tot = bad_n = 0
    for primal, tangent in (("field", "tangent_field"),
                            ("step", "tangent_step")):
        if g.section(primal) is None:
            continue
        for _ in range(points):
            st = [_q(rng) for _ in range(g.n_state)]
            tv = [_q(rng) for _ in range(g.n_state)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            try:
                up = g2.exact_eval(primal, [s + HP_EPS * t for s, t in
                                            zip(st, tv)], pa, la)
                dn = g2.exact_eval(primal, [s - HP_EPS * t for s, t in
                                            zip(st, tv)], pa, la)
                got = g2.exact_eval(tangent, st, pa, la, tangent=tv)
            except ArithmeticError:
                continue
            tot += 1
            bad_n += any(abs((u - d) / (2 * HP_EPS) - t) >
                         HP_TOL * max(1, abs(t)) for u, d, t in zip(up, dn, got))
    return tot, bad_n


def _one(fn, fmt="fp64", rnd="rne"):
    return lang.compile_text(f"system r\nformat {fmt}\nround {rnd}\n"
                             f"state a, y\ntangent v\nnext a = a\n"
                             f"next y = {fn}(a)\nstep map\n").graph


def _domain(fn, rng):
    if fn.startswith("exp"):
        return Fraction(rng.randint(-8000, 8000), 1000)
    return Fraction(rng.randint(-999 if fn == "log1p" else 1, 64000), 1000)


def rounding_misses(fn, fmtname, rnd, rng, lanes=6):
    """(lanes, lanes whose tangent is not the table's last operation rounded
    once, lanes whose last operation's exact value is not the derivative
    within its operands' roundings) on y = f(a): the operands the primal's
    own r or a, and the primal-only value the table rounds once first,
    1 + r, L * r, L * a or 1 + a, L the stage's own; the derivative by a
    central difference at 2^-256 of the 1,024-bit values."""
    g = _one(fn, fmtname, rnd)
    fmt, code = g.fmt, K.RND_BY_NAME[rnd]
    u = Fraction(1, 1 << (fmt.prec - 1))
    Lb = K.round_once(fmt, sf.RND_RNE, _ln2(fmt, code))[0]
    one = K.round_once(fmt, sf.RND_RNE, Fraction(1))[0]
    pairs = [(K.round_once(fmt, sf.RND_RNE, _domain(fn, rng))[0],
              K.round_once(fmt, sf.RND_RNE,
                           Fraction(rng.randint(-4000, 4000) or 1, 1000))[0])
             for _ in range(lanes)]
    run = lang.run(g, [[a, 0] for a, _d in pairs], 1,
                   tangents=[[[da, 0]] for _a, da in pairs])
    bits_bad = value_bad = 0
    for (a, da), st, tv in zip(pairs, run.states, run.tangents):
        r, t = st[1], tv[0][1]
        val = lambda b: K.value_of(fmt, b)          # noqa: E731
        if fn == "exp":
            want, exact = sf.mul(fmt, r, da, code)[0], val(r) * val(da)
        elif fn in ("expm1", "exp2"):
            q = sf.add(fmt, one, r, code)[0] if fn == "expm1" else \
                sf.mul(fmt, Lb, r, code)[0]
            want, exact = sf.mul(fmt, q, da, code)[0], val(q) * val(da)
        else:
            q = a if fn == "log" else sf.mul(fmt, Lb, a, code)[0] \
                if fn == "log2" else sf.add(fmt, one, a, code)[0]
            want, exact = sf.div(fmt, da, q, code)[0], val(da) / val(q)
        bits_bad += t != want
        x, dx = val(a), val(da)
        d = (_trans(fn, x + HP_EPS * dx) - _trans(fn, x - HP_EPS * dx)) \
            / (2 * HP_EPS)
        k = {"exp": 1, "expm1": 0, "exp2": 3, "log": 0, "log2": 2,
             "log1p": 1}[fn]
        bound = k * u * Fraction(101, 100)
        if fn == "expm1":
            vr = val(r)
            bound = u * (abs(vr) + abs(1 + vr)) / abs(1 + vr) \
                * Fraction(101, 100)
        value_bad += abs(exact - d) > (bound + Fraction(1, 1 << 400)) * abs(d)
    return len(pairs), bits_bad, value_bad


def specials_misses():
    """At fp64, bit for bit: below each logarithm's domain its tangent is
    the NaN r; at its pole da / +-0, an infinity with divideByZero; at a
    NaN the NaN. -> a list of what missed."""
    fmt = FORMATS["fp64"]

    def b(v):
        return K.round_once(fmt, sf.RND_RNE, Fraction(v))[0]
    sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
    miss = []

    def one(fn, a, da):
        r = lang.run(_one(fn), [[a, 0]], 1, tangents=[[[da, 0]]])
        return r.states[0][1], r.tangents[0][0][1], r.flags
    for fn, below in (("log", b(-3)), ("log2", b(Fraction(-1, 2))),
                      ("log1p", b(-2))):
        if one(fn, below, b(3))[:2] != (qnan, qnan):
            miss.append(f"{fn} below its domain")
    for fn, pole in (("log", 0), ("log2", 0), ("log1p", b(-1))):
        if one(fn, pole, b(3)) != (inf ^ sign, inf, sf.FLAG_DIVZERO):
            miss.append(f"{fn} at its pole")
    for fn in SIX:
        if one(fn, qnan, b(3))[:2] != (qnan, qnan):
            miss.append(f"{fn} at a NaN")
    return miss


class _M1Plant(lang_tangent.Derivation):
    """The derivation with log's rule wrong (kind)."""
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        if node.op == "log" and self.of(a[0]) is not None:
            da = self.of(a[0])
            if self.kind == "log's rule rounded otherwise":
                return N("select", N("mul", da, N("div", self.one, R(a[0]))),
                         R(node), N("cmpeq", R(node), R(node)))
            if self.kind == "log's select form dropped":
                return N("div", da, R(a[0]))
        return super().rule(node)


def _wrong_ln2(fmt, rnd):
    right = K.ln2_bits(fmt, rnd)
    lo, hi = K.ln2_bits(fmt, sf.RND_RDN), K.ln2_bits(fmt, sf.RND_RUP)
    return K.value_of(fmt, hi if right == lo else lo)


def leg_math(count, rng):
    section(f"M. the math library's six rules (M1's build, item 3), golden: "
            f"{len(M1_SHAPES)} written shapes and {count} generated systems "
            f"with tangent vectors - the derivative exactly and by a central "
            f"difference in high precision, the primal unchanged, each rule's "
            f"rounding bit for bit at every format and attribute, the "
            f"specials, plants")
    if not LC.have_mpmath():
        skip("M: the math library's six rules", "python has no mpmath "
             "module, which their golden functions (python/cft_golden/"
             "transcend.py) and this leg's values in high precision need "
             "(pip install mpmath)")
        return
    t0 = time.perf_counter()
    graphs = m1_graphs(m1_texts(count, "tangent math"))
    tot = bad_n = htot = hbad = 0
    changed, ops = [], set()
    for g, text, what in graphs:
        a, b, _t, _z = derivative_misses(g, rng, 3)
        tot, bad_n = tot + a, bad_n + b
        a, b = hp_misses(g, rng, 2)
        htot, hbad = htot + a, hbad + b
        ops |= set(g.op_counts("step"))
        states = LC.lanes_for(g.fmt, g.n_state, rng, 3)
        states += LC.special_lanes(g.fmt, g.n_state, states[0], rng)
        if not primal_unchanged(g, without_tangent(text), states, 2):
            changed.append(what)
    check(bad_n == 0 and tot >= 3 * len(graphs) and set(SIX) <= ops,
          f"{len(graphs)} systems holding all six, {tot} points: the tangent "
          f"sections evaluated exactly equal this stage's own derivative, each "
          f"of the six as the exact evaluation takes it and ln 2 as L, "
          f"transcend.log of 2", f"{bad_n} differ")
    check(hbad == 0 and htot >= 2 * len(graphs), f"{htot} points: every "
          f"tangent component within 2^-300 of the central difference at "
          f"eps = 2^-256 of 1,024-bit values, ln 2 exact in L's place",
          f"{hbad} differ")
    check(not changed, "the primal unchanged in each: its states and flags "
          "without the tangent, on lanes that overflow, hold a signalling "
          "NaN and hold subnormals, its graph's lines (L and 1 the only "
          "constants the six's rules add)", f"changed: {changed[:4]}")
    lanes = bits = value = 0
    for fn in SIX:
        for fmtname in ("fp32", "fp64", "fp128", "fp256"):
            for rnd in ("rne", "rtz", "rdn", "rup", "rmm"):
                n, b, v = rounding_misses(fn, fmtname, rnd, rng)
                lanes, bits, value = lanes + n, bits + b, value + v
    check(bits == 0 and value == 0 and lanes == 6 * 4 * 5 * 6,
          f"{lanes} lanes of y = f(a), the six at every format and attribute: "
          f"each tangent the table's last operation rounded once, on the "
          f"primal's own values and the primal-only value rounded once "
          f"first, and that operation's exact value the derivative within "
          f"its operands' roundings", f"{bits} in bits, {value} in value")
    miss = specials_misses()
    check(not miss, "the specials, bit for bit: each logarithm's tangent the "
          "NaN r below its domain, da / +-0 at its pole with divideByZero, a "
          "NaN at a NaN, for all six", "; ".join(miss))
    # the plants, each in the golden model's own classes, restored after
    plant_texts = [t for t in m1_texts(6, "tangent math plants")]
    original = lang_check_mod.Derivation
    orig_ln2 = lang_check_mod.C.ln2_value
    from cft_golden.lang import interp as lang_interp
    orig_t = lang_interp._transcend
    plants = ("log's rule rounded otherwise", "log's select form dropped",
              "L rounded the wrong way", "exp's golden function swapped for "
              "exp2's")
    try:
        for kind in plants:
            # each plant alone: the last one's classes restored first
            lang_check_mod.Derivation = original
            lang_check_mod.C.ln2_value = orig_ln2
            lang_interp._transcend = orig_t
            if kind.startswith("log's"):
                class P(_M1Plant):
                    pass
                P.kind = kind
                lang_check_mod.Derivation = P
            elif kind.startswith("L "):
                lang_check_mod.C.ln2_value = _wrong_ln2
            else:
                lang_interp._transcend = (
                    lambda fmt, fn, rnd: orig_t(fmt, "exp2" if fn == "exp"
                                                else fn, rnd))
            ex = hp = 0
            for g, _text, _w in m1_graphs(plant_texts):
                ex += derivative_misses(g, rng, 2)[1]
                hp += hp_misses(g, rng, 2)[1]
            fns = ("log",) if kind.startswith("log's") else \
                ("exp2", "log2") if kind.startswith("L ") else ("exp",)
            rb = rv = 0
            for fn in fns:
                for fmtname in ("fp32", "fp64", "fp256"):
                    for rnd in ("rne", "rup", "rdn"):
                        _n, b, v = rounding_misses(fn, fmtname, rnd, rng, 8)
                        rb, rv = rb + b, rv + v
            sp = len(specials_misses())
            said = (f"plant {kind!r}: the exact check {ex}, the central "
                    f"difference {hp}, the rounding {rb} in bits and {rv} in "
                    f"value, the specials {sp}")
            if kind == "log's rule rounded otherwise":
                check(ex == 0 and hp == 0 and rb > 0, said + " - exact in "
                      "rationals: green on both exact checks, red on the "
                      "rounding")
            elif kind == "log's select form dropped":
                check(ex == 0 and hp == 0 and rb == 0 and sp > 0, said +
                      " - red below the domain alone")
            elif kind.startswith("L "):
                check(ex > 0 and hp > 0 and rb > 0, said + " - red on all "
                      "three")
            else:
                check(rv > 0, said + " - red on the rounding's derivative "
                      "(r is exp2's, so r * da is no derivative of exp)")
    finally:
        lang_check_mod.Derivation = original
        lang_check_mod.C.ln2_value = orig_ln2
        lang_interp._transcend = orig_t
    print(f"  ({time.perf_counter() - t0:.1f} s)")


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
    ap.add_argument("--routines", type=int, default=24,
                    help="generated systems that divide or take a root in "
                         "leg L (default 24)")
    ap.add_argument("--math", type=int, default=16,
                    help="generated systems holding the math library's six "
                         "in leg M (default 16)")
    ap.add_argument("--only", default="",
                    help="a comma list of legs: refs,corpus,derivative,"
                         "lyapunov,certified,libcft,determinism,refusals,"
                         "plants,routines,math")
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
            ("plants", lambda: leg_plants(rng("plants"), segrun_path, work)),
            ("routines", lambda: leg_routines(a.routines,
                                              rng("routines"))),
            ("math", lambda: leg_math(a.math, rng("math")))]
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
