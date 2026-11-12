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
     Kepler's, whose image holds routines, among them (C4), the three
     holding the math library's six since M1's build, item 4
     (Lotka-Volterra, the diodes, the culture), the two holding sin,
     cos and tan since M2's build (the pendulum at round rne, the attitude
     of a rigid body at round rdn), and the one holding atan, asin, acos
     and atan2 since M4's build (the phase follower at round rdn, whose
     lanes keep the oscillator in the half plane c > 0, so that atan2's
     primal never meets its jump, and q and v inside [-2, 2], asin's and
     acos's domain); the golden reader and audit and
     cft-audit accept each. A segment that marks a lane (STATUS[6]) fails
     here by name: version 1 holds the machine's guess, STATUS[6] on the
     segment; cft-segrun's version-2 writer, which this leg does not use,
     refuses a marked lane `replay-missing` without a replay image and
     `replay-undecided` with one that marks it too - so a certificate stays
     what the machine ran, and the replay of M1's build, item 5 is the
     stages' own comparisons' (leg N below), never this leg's. The six
     references holding the math library's routines are skipped by name on
     a host without mpmath, which builds them
  H  determinism: two processes under two PYTHONHASHSEEDs; the committed
     programs/systems/compiled-tangent/ is what the compiler writes, and
     the `lang` stage's 64 committed files still are (the references
     holding the math library's routines held only where mpmath imports,
     skipped by name elsewhere)
  I  refusals by name, the language's and the compiler's, with tangents;
     a quotient and a root with two tangent vectors compiled for the
     software targets and run as the interpreter runs them, and refused
     `target-feature` on revision 7's (C4)
  J  plants: three wrong derivations, red on D and on the exponent; the
     same rule rounded otherwise, green on D and red on the committed
     bytes - every committed graph holding a product of two tangent-
     carrying operands, and only those (Lotka-Volterra's, the diodes', the
     pendulum's and the phase follower's multiply a state value only by a
     param, as its atan2 and the unary three are of one); three in a
     copy of the compiler, each stopped by its internal check and, with
     that off, red on seq.py
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
  M  the math library's rules, golden - the six (M1's build, item 3)
     and sin, cos and tan (M2's build): written shapes and generated
     systems holding exp, expm1, exp2, log, log1p and log2, and then sin,
     cos and tan, with tangent vectors. Two derivative checks, named for
     what they are: the tangent exactly against this stage's own dual
     numbers (leg D's discipline made on these systems; each value as the
     exact evaluation takes it, L the stage's own: transcend.log of 2;
     tan's derivative 1 + tan^2 of tan's value) and, leg M's own, against
     a central difference in high precision (eps = 2^-256 of 1,024-bit
     values, within 2^-300, ln 2 exact in L's place), which assumes none
     of the identities; the primal unchanged; each rule's rounding on y =
     f(a), every format and attribute, bit for bit, its exact value
     before its last rounding the derivative within its operands'
     roundings (for the three, cos(a) and -sin(a) the routines' correctly
     rounded results under the attribute, then fma(r, r, 1); and the
     node's own result the golden function's); the specials below each
     logarithm's domain and at the poles, and the three's at +-0, at
     +-infinity and at a NaN under every attribute; and plants - log's
     rule rounded otherwise (green on both exact checks, red on the
     rounding), L rounded the wrong way (red on all three), log's select
     form dropped (red below the domain), a golden function swapped for a
     sibling's (red on the rounding's derivative); for the three, each
     rule made wrong (red on the exact check, the difference and the
     rounding under every attribute), tan's rule rounded otherwise
     (fma(r, r * da, da): green on both exact checks, red on the rounding
     under every attribute), cos's rounded otherwise (-(sin(a) * da):
     green on both exact checks, red on the rounding at finite lanes
     under rdn and rup only, where its two forms differ, and green under
     rne, rtz and rmm there - but red at a NaN lane under every attribute,
     the second form's sign bit being the negation's), and sin's golden
     function swapped for cos's (red on the golden check and on cos's
     rounding). The compiler carries the six since M1's build, item 4,
     and its committed references holding them are legs G, H and J's;
     compiled images of generated sources holding them, a marked lane
     replayed, are leg N's; the three's compiled forms are leg T's. The
     thirteen golden functions need mpmath, so on a host without it
     this leg is skipped by name, as are legs G and H's references holding
     the six and leg N; legs A to L never need it otherwise. atan, asin, acos and atan2 (M4's build) are held by the same five
     checks and ten plants (math_four): written shapes and generated
     systems with tangent vectors; the tangent exactly against this
     stage's own dual numbers, with a floor of ten decided points per
     function; leg M's own central difference, at eps = 2^-256 within
     2^-300 where the graph holds no asin, acos or square root and at
     eps = 2^-64 within 2^-100 where it does - asin's and acos's rules
     hold a root the exact evaluation rounds down to 2^-256, which a
     difference at 2^-256 would measure - run on points whose arguments
     are at most 7/8, never left out; the primal unchanged; each rule's
     rounding bit for bit at every format and attribute (atan2 in its
     three cases: both tangents, db zero, da zero); the specials (asin and
     acos at +-1, past +-1, atan at +-inf, atan2 at the origin and its
     axes); and plants - each rule made wrong, each rounded otherwise
     (red at the attributes where its two forms differ), atan's golden
     function swapped for asin's, atan2's operands swapped in the
     interpreter (red on the golden check)
  N  the math library's six compiled, with tangent vectors (M1's build,
     item 5): generated systems that call them beside division, the root
     and the other operations, all with one tangent vector or two, under
     every integrator, format and attribute, compiled for the software
     backend and run on seq.py at 1, 2 and 5 steps against lang.run -
     states, every tangent and FLAGS, three lanes with special tangents
     among them - under the marked-lane rule of lang_check.py, which every
     leg of this stage shares: a lane whose byte carries the mark is
     replayed whole, its states and its tangents the definition's, and the
     image's guess counted, never required; every other lane equal to
     the definition bit for bit with its byte's five flags. The structured
     families' centres (python/tests/mathlib_family.py) are put in the
     primal where the calls read it, every lane the theory demands marked
     asserted marked, so that a mark reaches the tangent comparison; and
     controls with a tangent vector - exp at fp64 under rne, x = 2^-53,
     whose guess is wrong and whose tangent, r * da with r the guess, is
     wrong with it - show the replay whole and a fault planted in an
     unmarked lane's tangent red. Skipped by name without mpmath
  T  sin, cos and tan compiled, with tangent vectors (M2's build, wave 4):
     leg M's written shapes and generated systems and lang_check's g_three
     sources (calls to the three beside three of the six - exp, log1p and
     expm1 - division and the root), one vector or two, run as leg N runs the six; the families'
     centres in the primal, every lane the theory demands marked asserted
     marked in the sources whose calls are known, and lanes at 2^2048 and
     past at fp128 and fp256, marked whatever the test says, some of whose
     guesses are wrong in the state and, sin's tangent reading cos(a), in
     the tangent - which ones is mathlib's and is not asserted, only a
     count of each, nonzero at both formats, so that a marked lane's
     tangents left unreplayed is red on a real lane and not on the controls
     alone. Controls with a tangent vector: cos(2^-26) under rtz at fp64
     (marked, the guess right); a lane at 2^4096 at fp256 (marked, wrong in
     state and tangent), with an unmarked lane's tangent flipped and the
     wrong-guess lane unmarked, both red; and the pendulum's shape under
     rdn at fp64 at a cos centre, a lane that only the tangent's cos(a)
     marks - R23's byte is one a lane, so the mark excuses the lane's
     primal state as well, and a flip in it is replayed, not red.
     Skipped by name without mpmath
  U  atan, asin, acos and atan2 compiled, with tangent vectors (M4's build,
     wave 5): leg M's written shapes and generated systems and
     lang_check's g_four sources (calls to the four beside exp, log1p and
     sin, division and the root), one vector or two, run as leg T runs the
     three; the families' centres (python/tests/mathlib_inv_family.py) and
     atan2's tiny-quotient range pairs, at every format, in the primal,
     every lane the theory demands marked asserted marked in the sources
     whose calls are known. No lane is marked by the tangent's routine
     alone: the four's tangent rules write no routine node of their own
     but the div and sqrt they name, which never mark, and the calls of
     the four that a tangent section holds in the compiled image (a rule
     that reads a primal call a second time is given the call written
     again) are copies of primal calls - checked on the images U0e reads
     (the written shapes and the systems leg M draws: the tangent section
     of each holds no routine but the four, div and sqrt, and each call of
     the four there repeats a primal call's operation and operand
     structure), not on every image. Controls with a tangent vector: atan(3 2^-26) under rne at
     fp64 (marked); an atan2 pair in the tiny-quotient range at fp64 and
     at fp32 (marked); a flip in an unmarked lane's tangent, red, and the
     same flip in a marked lane's tangent, replayed and counted, not red
     (R23's byte is one a lane); and a lane of the harness's pin on wrong
     guesses (atan at fp64 under rmm). Skipped by name without mpmath

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
from cft_golden import transcend                          # noqa: E402
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
         "culture-rk4-tangent": 10,
         # sin, cos and tan and their rules (M2's build): the pendulum
         # (sin in the step, cos in the tangent) at round rne, and a rigid
         # body's attitude, the 3-2-1 Euler angles' kinematics (all three,
         # in the step and in the tangent), at round rdn, where cos's rule
         # rounded otherwise rounds to another value (its bytes move under
         # any attribute; its output rarely shows the value)
         "pendulum-rk4-tangent": 10, "attitude-rk4-tangent": 10,
         # atan, asin, acos and atan2 and their rules (M4's build): the
         # phase follower, atan2 of two state components and each of the
         # unary three of one, at round rdn, where acos's and atan2's rules
         # rounded otherwise are other bytes (and other values)
         "phasefollower-rk4-tangent": 10}
# The references holding the math library's routines, the six, sin, cos and
# tan, and atan, asin, acos and atan2: compiled only where mpmath imports,
# since the routines' generator derives their constants through it (a leg
# that compiles them skips them by name elsewhere), and run on lanes whose
# boxes keep the logarithms in their domains, the angles away from tan's
# poles and the follower's oscillator off atan2's jump; leg G's lanes mark
# none, and the leg fails by name a segment that marks one
MATH_TREFS = ("lotkavolterra-rk4-tangent", "diode-rk4-tangent",
              "culture-rk4-tangent", "pendulum-rk4-tangent",
              "attitude-rk4-tangent", "phasefollower-rk4-tangent")
MATH_BOX = {"lotkavolterra-rk4": [(-1, 1), (-2, Fraction(1, 2))],
            "diode-rk4": [(0, 4), (0, 4)],
            "culture-rk4": [(Fraction(1, 20), Fraction(19, 20)), (0, 2)],
            "pendulum-rk4": [(-1, 1), (-1, 1)],
            "attitude-rk4": [(-1, 1), (-1, 1)],
            # the phase follower: c in [1/2, 1] and s in [-1/2, 1/2] keep
            # the angle atan2(s, c) inside (-pi/2, pi/2), far from atan2's
            # jump on the negative axis, and q and v keep asin(q/2) and
            # acos(v/2) inside their domain; none of the lanes' boxes is
            # a structured centre (the lanes mark none: leg G fails a
            # segment that marks one)
            "phasefollower-rk4": [(Fraction(1, 2), 1),
                                  (-Fraction(1, 2), Fraction(1, 2)),
                                  (-1, 1), (-1, 1), (-1, 1)]}
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
    checkpoints: states, tangents, lane params and FLAGS - under the
    marked-lane rule of lang_check.py (item 5 of M1's build), which this
    shares: a lane whose byte carries the mark is replayed whole, its
    states and its tangents the definition's, and the image's guess is
    counted and never required. -> (failing lanes, FLAGS and STATUS fine
    everywhere, the definition)."""
    v = LC.rule_compare(c, states, top, lane_params=lane_params,
                        tans=tangents)
    return v.failing, v.flags_ok, v.ref


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
    """One of the math library's nine as the exact evaluations take it
    (cft_golden/lang/graph.py's exact_transcendental, computed again here):
    exact where the value is rational - exp(0), exp2(n), log(1),
    log2(2^k), and sin(0) = tan(0) = 0 and cos(0) = 1 - otherwise mpmath's
    value at 1,024 bits of the argument rounded to nearest at 1,024 bits;
    expm1 is exp - 1 and log1p log(1 + a); an ArithmeticError at a
    logarithm's pole or below its domain, or past 2^+-1048576."""
    q = Fraction(q)
    if op in THREE and q == 0:
        return Fraction(1 if op == "cos" else 0)
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
         "log2": lambda v: ctx.log(v) / ctx.ln2, "sin": ctx.sin,
         "cos": ctx.cos, "tan": ctx.tan}[op](x)
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
THREE = ("sin", "cos", "tan")           # M2's build


def _dual(op, a, tie=0, zero=1, L=None):
    """One operation on (value, derivative) pairs, exactly, by calculus -
    with the rule table's choices at its measure-zero points (a tie gives
    the first operand's, a zero's sign is +) - written again here, not
    read from the derivation. tie=1 and zero=-1 are the other choices,
    which a placed point must tell apart from the table's; a value is
    the same under any of them. The six (M1) take each value as the exact
    evaluations take it (_trans), and ln 2 as `L`, the stage's own; so do
    sin, cos and tan (M2), whose derivatives are cos, -sin and sec^2 =
    1 + tan^2, the last with tan the exact evaluation's value so that the
    rule's exact value is the derivative itself - the central difference of
    leg M, which does not use the identity, is the evidence for it."""
    v = [p[0] for p in a]
    d = [p[1] for p in a]
    if op in THREE:
        x, dx = v[0], d[0]
        if op == "sin":
            return _trans("sin", x), _trans("cos", x) * dx
        if op == "cos":
            return _trans("cos", x), -_trans("sin", x) * dx
        t = _trans("tan", x)
        return t, (1 + t * t) * dx
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
    (STATUS[6] on its segment); cft-segrun's version-2 writer, which this
    leg does not use, refuses a marked lane `replay-missing` without a
    replay image and `replay-undecided` with one that marks it too; the
    stages' own comparisons replay a marked lane
    by the definition since M1's build, item 5 (lang_check.py's rule, this
    stage's leg N), and a certificate does not - so a segment that marks a
    lane fails here, by name, rather than pass on a guess."""
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
                 f"routine's undecided guess, which a version-1 "
                 f"certificate holds as the machine ran it (cft-segrun's "
                 f"version-2 writer refuses it replay-missing, or "
                 f"replay-undecided with a replay image that marks it "
                 f"too; the stages' comparisons replay it, leg N)"):
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
          f"{len(files)} files, Kepler's and the math library's references' "
          f"with routines among them",
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
    # no mpmath, the math library's routines included)
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
                # param, as the pendulum (M2's build) and the phase follower (M4's) do
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
# them are leg N's (item 5, below; the committed references are legs G, H
# and J's).

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


M2_SHAPES = {       # sin, cos and tan (M2's build) under each integrator
    "one of each, a map": (
        "system three\nformat fp64\nstate x, y, z\ntangent v\n"
        "next x = sin(y) - cos(z * x)\nnext y = tan(x * y) + sin(z)\n"
        "next z = cos(x * x + 1) * tan(y)\nstep map\n"),
    "the pendulum, rk4": (
        "system pendulum\nformat fp64\nstate theta, omega\ntangent v\n"
        "param g = 9.81\nparam len = 1.5\n"
        "d/dt theta = omega\nd/dt omega = -(g / len) * sin(theta)\n"
        "step rk4, h = 1/64\n"),
    "a let, rdn": (
        "system rotor\nformat fp128\nround rdn\nstate phi, w\ntangent v\n"
        "param kappa = 1/3\nlet s = sin(phi)\n"
        "d/dt phi = w + cos(phi) * kappa\n"
        "d/dt w = -(kappa * s) - tan(w) / 4\nstep rk4, h = 1/64\n"),
    "stormer-verlet": (
        "system pot\nformat fp32\nround rup\nstate q, p\ntangent v\n"
        "d/dt q = p + tan(p / 8)\nd/dt p = -sin(q) * cos(q)\n"
        "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
    "euler, two vectors": (
        "system e\nformat fp256\nround rmm\nstate x\ntangent v, w\n"
        "d/dt x = cos(-x) + sin(x * x)\nstep euler, h = 1/8\n"),
}


def _m2_expr(rng, names, depth):
    """A random expression with sin, cos and tan, each of an operand that
    reads one of `names`."""
    if depth <= 0 or rng.random() < 0.3:
        return rng.choice(names + ["2", "(1/3)", "0.5"])
    k = rng.choice(["+", "-", "*", "/", "fma", "three", "three", "three"])

    def sub():
        return _m2_expr(rng, names, depth - 1)
    if k == "three":
        return f"{rng.choice(THREE)}({sub()} * {rng.choice(names)})"
    if k == "fma":
        return f"fma({sub()}, {sub()}, {sub()})"
    return f"({sub()} {k} {sub()})"


def m1_texts(count, seed, shapes=None, expr=None):
    """The written shapes, then generated systems with the six, one or two
    tangent vectors, every integrator, format and attribute: (text, what).
    `shapes` and `expr` make them for sin, cos and tan (M2_SHAPES,
    _m2_expr) instead."""
    shapes = M1_SHAPES if shapes is None else shapes
    make = _m1_expr if expr is None else expr
    out = [(t, f"shape {s}") for s, t in shapes.items()]
    rng = random.Random(seed)
    for k in range(count):
        fmt = ("fp32", "fp64", "fp128", "fp256")[k % 4]
        rnd = rng.choice(("rne", "rtz", "rdn", "rup", "rmm"))
        integ = ("map", "rk4", "euler", "stormer-verlet")[(k // 4) % 4]
        vecs = "v, w" if k % 5 == 4 else "v"
        head = f"system m{k}\nformat {fmt}\nround {rnd}\n"
        if integ == "stormer-verlet":
            text = (head + f"state q, p\ntangent {vecs}\nparam c = 3/4\n"
                    f"d/dt q = {make(rng, ['p', 'c'], 2)} + c * p\n"
                    f"d/dt p = {make(rng, ['q', 'c'], 2)} - q\n"
                    f"step stormer-verlet, h = 1/16, q = (q), p = (p)\n")
        else:
            word = "next" if integ == "map" else "d/dt"
            names = ["x", "y", "c"]
            step = "step map" if integ == "map" else f"step {integ}, h = 1/32"
            text = (head + f"state x, y\ntangent {vecs}\nparam c = 2/3\n"
                    f"{word} x = {make(rng, names, 2)} + c\n"
                    f"{word} y = {make(rng, names, 2)} - y\n{step}\n")
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
    if fn in THREE:                 # radians, away from tan's poles by grid
        return Fraction(rng.randint(-64000, 64000), 1000)
    if fn.startswith("exp"):
        return Fraction(rng.randint(-8000, 8000), 1000)
    return Fraction(rng.randint(-999 if fn == "log1p" else 1, 64000), 1000)


def rounding_misses(fn, fmtname, rnd, rng, lanes=6):
    """(lanes, lanes whose tangent is not the table's last operation rounded
    once, lanes whose last operation's exact value is not the derivative
    within its operands' roundings) on y = f(a): the operands the primal's
    own r or a, and the primal-only value the table rounds once first,
    1 + r, L * r, L * a or 1 + a, L the stage's own - for sin, cos and tan
    (M2's build) cos(a) and -sin(a), the routines' correctly rounded
    results under the attribute, and fma(r, r, 1); the derivative by a
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
        if fn in THREE:
            if fn == "sin":
                q = transcend.compute(fmt, "cos", a, 0, code)[0]
            elif fn == "cos":
                q = sf.neg(fmt, transcend.compute(fmt, "sin", a, 0,
                                                  code)[0])[0]
            else:
                q = sf.fma(fmt, r, r, one, code)[0]
            want, exact = sf.mul(fmt, q, da, code)[0], val(q) * val(da)
        elif fn == "exp":
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
             "log1p": 1, "sin": 1, "cos": 1, "tan": 3}[fn]
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


def trig_golden_misses(fn, fmtname, rnd, rng):
    """(lanes, lanes where the interpreter's y = fn(a) is not transcend.
    compute's bits) on y = fn(a): random radians and the specials, at one
    format and attribute - the node's golden function, which sin's rule
    never reads (it reads cos(a), a node of its own)."""
    g = _one(fn, fmtname, rnd)
    fmt, code = g.fmt, K.RND_BY_NAME[rnd]
    lanes = [K.round_once(fmt, sf.RND_RNE, _domain(fn, rng))[0]
             for _ in range(6)]
    lanes += [0, fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)]
    run = lang.run(g, [[a, 0] for a in lanes], 1,
                   tangents=[[[0, 0]] for _ in lanes])
    bad_n = sum(st[1] != transcend.compute(fmt, fn, a, 0, code)[0]
                for a, st in zip(lanes, run.states))
    return len(lanes), bad_n


def trig_specials_misses():
    """At fp64 under every attribute, bit for bit: at +-0 sin's and tan's
    tangent is da and cos's is (-sin(+-0)) * da, a zero of the sign the
    product has; at an infinity either way and at a NaN each tangent is the
    positive NaN, the primal's own. -> a list of what missed, each naming
    the attribute: cos's second form, -(sin(a) * da), gives the NaN the
    negation's sign bit under every one of them."""
    fmt = FORMATS["fp64"]

    def b(v):
        return K.round_once(fmt, sf.RND_RNE, Fraction(v))[0]
    sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
    miss = []

    def one(fn, rnd, a, da):
        r = lang.run(_one(fn, "fp64", rnd), [[a, 0]], 1,
                     tangents=[[[da, 0]]])
        return r.states[0][1], r.tangents[0][0][1], r.flags
    for rnd in ("rne", "rtz", "rdn", "rup", "rmm"):
        for fn in THREE:
            for a, name in ((inf, "+inf"), (inf ^ sign, "-inf"),
                            (qnan, "a NaN")):
                if one(fn, rnd, a, b(3))[:2] != (qnan, qnan):
                    miss.append(f"{fn} at {name} under {rnd}")
            for zero in (0, sign):
                for da in (b(3), b(-3)):
                    r, t, f = one(fn, rnd, zero, da)
                    if fn == "cos":
                        # -(+-0) * da: the sign of -(zero's sign) xor da's
                        want = ((zero ^ sign) ^ da) & sign
                        ok = (r, t) == (b(1), want)
                    else:
                        ok = (r, t) == (zero, da)
                    if not ok or f:
                        miss.append(f"{fn} at {hex(zero)} under {rnd}")
    return miss


class _M2Plant(lang_tangent.Derivation):
    """The derivation with one of sin's, cos's or tan's rules changed
    (kind)."""
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        if node.op in THREE and self.of(a[0]) is not None:
            da, k = self.of(a[0]), self.kind
            if node.op == "sin" and k == "sin's rule: sin(a) * da":
                return N("mul", R(node), da)
            if node.op == "cos" and k == "cos's rule without its minus":
                return N("mul", N("sin", R(a[0])), da)
            if node.op == "tan" and k == "tan's rule: r * da":
                return N("mul", R(node), da)
            if node.op == "cos" and k == "cos's rule rounded otherwise":
                return N("neg", N("mul", N("sin", R(a[0])), da))
            if node.op == "tan" and k == "tan's rule rounded otherwise":
                # the study's alternative, fma(r, r * da, da): the same
                # value, two roundings a vector with nothing shared. It reads
                # da twice, which only a leaf or a named node may bear, so
                # where da is an unnamed expression the rule is the table's;
                # the rounding check's one-operation system has a leaf
                if isinstance(da, Node) and da.label is None:
                    return super().rule(node)
                return N("fma", R(node), N("mul", R(node), da), da)
        return super().rule(node)


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


RNDS5 = ("rne", "rtz", "rdn", "rup", "rmm")


def math_three(count, rng):
    """Leg M's checks for sin, cos and tan (M2's build), after the six's:
    the same five, then six plants. The exact dual numbers are leg D's
    discipline, made on these systems; the central difference at 2^-256 of
    1,024-bit values is this leg's own, and does not assume the identity
    sec^2 = 1 + tan^2 that tan's dual numbers use."""
    t0 = time.perf_counter()
    texts = m1_texts(count, "tangent math three", M2_SHAPES, _m2_expr)
    graphs = m1_graphs(texts)
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
    check(bad_n == 0 and tot >= 2 * len(graphs) and set(THREE) <= ops,
          f"{len(graphs)} systems holding sin, cos and tan, {tot} points: "
          f"the tangent sections evaluated exactly equal this stage's own "
          f"derivative (leg D's check, made on the three), each value as the "
          f"exact evaluation takes it and tan's derivative 1 + tan^2 of "
          f"that value", f"{bad_n} differ")
    check(hbad == 0 and htot >= len(graphs), f"{htot} points: every tangent "
          f"component within 2^-300 of the central difference at eps = "
          f"2^-256 of 1,024-bit values - leg M's own check, which does not "
          f"assume sec^2 = 1 + tan^2", f"{hbad} differ")
    check(not changed, "the primal unchanged in each: its states and flags "
          "without the tangent, on lanes that overflow, hold a signalling "
          "NaN and hold subnormals, its graph's lines (1 the only constant "
          "the three's rules add, tan's)", f"changed: {changed[:4]}")
    lanes = bits = value = glanes = gbad = 0
    for fn in THREE:
        for fmtname in ("fp32", "fp64", "fp128", "fp256"):
            for rnd in RNDS5:
                n, b, v = rounding_misses(fn, fmtname, rnd, rng)
                lanes, bits, value = lanes + n, bits + b, value + v
                n, b = trig_golden_misses(fn, fmtname, rnd, rng)
                glanes, gbad = glanes + n, gbad + b
    check(bits == 0 and value == 0 and gbad == 0 and lanes == 3 * 4 * 5 * 6,
          f"{lanes} lanes of y = f(a), sin, cos and tan at every format and "
          f"attribute: each tangent the table's product rounded once, on the "
          f"factor the table rounds once first (cos(a), -sin(a) the "
          f"routines' correctly rounded results under the attribute, or "
          f"fma(r, r, 1)), and that product's exact value the derivative "
          f"within its factor's roundings; and {glanes} lanes in which the "
          f"node's own result is the golden function's, bit for bit",
          f"{bits} in bits, {value} in value, {gbad} golden")
    miss = trig_specials_misses()
    check(not miss, "the specials, bit for bit under every attribute: at "
          "+-0 sin's and tan's tangent da and cos's (-sin(+-0)) * da, a "
          "zero of the product's sign; at an infinity either way and at a "
          "NaN the positive NaN, the primal's own, with no flag at the "
          "zeros", "; ".join(miss[:6]))
    plant_texts = m1_texts(6, "tangent math plants three", M2_SHAPES,
                           _m2_expr)
    original = lang_check_mod.Derivation
    from cft_golden.lang import interp as lang_interp
    orig_t = lang_interp._transcend
    plants = ("sin's rule: sin(a) * da", "cos's rule without its minus",
              "tan's rule: r * da", "cos's rule rounded otherwise",
              "tan's rule rounded otherwise",
              "sin's golden function swapped for cos's")
    try:
        for kind in plants:
            # each plant alone: the last one's classes restored first
            lang_check_mod.Derivation = original
            lang_interp._transcend = orig_t
            swap = kind.startswith("sin's golden")
            if swap:
                lang_interp._transcend = (
                    lambda fmt, fn, rnd: orig_t(fmt, "cos" if fn == "sin"
                                                else fn, rnd))
            else:
                class P(_M2Plant):
                    pass
                P.kind = kind
                lang_check_mod.Derivation = P
            ex = hp = 0
            for g, _text, _w in m1_graphs(plant_texts):
                ex += derivative_misses(g, rng, 2)[1]
                hp += hp_misses(g, rng, 2)[1]
            # the rule under test; sin's golden function is read by cos's
            # rule (sin(a)), not by sin's own, whose cos(a) is a node of its
            # own: the swap is red on cos's rounding and on the golden check
            fn = "cos" if swap else kind[:3]
            per = dict.fromkeys(RNDS5, 0)
            for fmtname in ("fp32", "fp64", "fp256"):
                for rnd in RNDS5:
                    per[rnd] += rounding_misses(fn, fmtname, rnd, rng, 8)[1]
            gold = sum(trig_golden_misses("sin", "fp64", rnd, rng)[1]
                       for rnd in RNDS5)
            sp = trig_specials_misses()
            said = (f"plant {kind!r}: the exact check {ex}, the central "
                    f"difference {hp}, the rounding in bits at finite lanes "
                    f"under rne, rtz, rdn, rup, rmm "
                    f"{', '.join(str(per[r]) for r in RNDS5)}, the golden "
                    f"check {gold}, the specials {len(sp)}")
            if swap:
                check(ex == 0 and hp == 0 and gold > 0 and
                      all(v > 0 for v in per.values()), said + " - red on "
                      "the golden check and on cos's rounding, which reads "
                      "sin(a); green on the exact checks, which never run "
                      "the interpreter's table")
            elif kind in plants[:3]:
                check(ex > 0 and hp > 0 and all(v > 0 for v in per.values()),
                      said + " - red on the exact check, the difference and "
                      "the rounding, under every attribute")
            elif kind.startswith("tan"):
                check(ex == 0 and hp == 0 and all(v > 0 for v in per.values()),
                      said + " - exact in rationals: green on both exact "
                      "checks, red on the rounding under every attribute")
            else:
                finite_ok = (per["rne"] == per["rtz"] == per["rmm"] == 0
                             and per["rdn"] > 0 and per["rup"] > 0)
                nan_rne = "cos at a NaN under rne" in sp
                nan_all = all(f"cos at a NaN under {r}" in sp for r in RNDS5)
                check(ex == 0 and hp == 0 and finite_ok and nan_rne and
                      nan_all, said + " - exact in rationals: green on both "
                      "exact checks; red on the rounding at finite lanes "
                      "under rdn and rup only, where the two forms differ, "
                      "green under rne, rtz and rmm; and red at a NaN lane "
                      "under every attribute, rne among them, where the "
                      "second form's sign bit is the negation's")
    finally:
        lang_check_mod.Derivation = original
        lang_interp._transcend = orig_t
    print(f"  (sin, cos and tan: {time.perf_counter() - t0:.1f} s)")


FOUR = ("atan", "asin", "acos", "atan2")                # M4's build
ONE4 = ("atan", "asin", "acos")
# asin's and acos's rules hold a square root, which the exact evaluation
# rounds down to 2^-256 (graph.ROOT_BITS): a central difference at 2^-256
# within 2^-300 would measure that rounding, so they are held at 2^-64
# within 2^-100 (leg L's pair), on points whose arguments are at most 7/8
ROOT_EPS = Fraction(1, 1 << 64)
ROOT_TOL = Fraction(1, 1 << 100)

M4_SHAPES = {       # atan, asin, acos and atan2 under each integrator
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
        "asin(omega / (1 + abs(omega))) / 4\nstep rk4, h = 1/64\n"),
    "a let, rdn": (
        "system rotor\nformat fp128\nround rdn\nstate phi, w\ntangent v\n"
        "param kappa = 1/3\nlet s = acos(phi / (1 + abs(phi)))\n"
        "d/dt phi = w + atan2(w, 1 + phi * phi) * kappa\n"
        "d/dt w = -(kappa * s) - atan(w) / 4\nstep rk4, h = 1/64\n"),
    "stormer-verlet": (
        "system pot\nformat fp32\nround rup\nstate q, p\ntangent v\n"
        "d/dt q = p + atan2(p, 2 + p * p) / 8\n"
        "d/dt p = -atan(q) * asin(q / (1 + abs(q)))\n"
        "step stormer-verlet, h = 1/32, q = (q), p = (p)\n"),
    "euler, two vectors": (
        "system e\nformat fp256\nround rmm\nstate x\ntangent v, w\n"
        "d/dt x = acos(-x / (1 + abs(x))) + atan2(x, 1 + x * x)\n"
        "step euler, h = 1/8\n"),
}


def _m4_expr_of(fns):
    """A random expression with `fns` among atan, asin, acos and atan2,
    each call of operands that read one of `names`; asin's and acos's
    argument is x / (1 + |x|), inside (-1, 1) at every point."""
    def expr(rng, names, depth):
        if depth <= 0 or rng.random() < 0.3:
            return rng.choice(names + ["2", "(1/3)", "0.5"])
        k = rng.choice(["+", "-", "*", "/", "fma", "inv", "inv", "inv"])

        def sub():
            return expr(rng, names, depth - 1)
        if k == "inv":
            fn = rng.choice(fns)
            r = rng.choice(names)
            if fn == "atan2":
                return f"atan2({sub()} * {r}, {sub()} * {rng.choice(names)})"
            if fn == "atan":
                return f"atan({sub()} * {r})"
            return f"{fn}({r} / (1 + abs({r})))"
        if k == "fma":
            return f"fma({sub()}, {sub()}, {sub()})"
        return f"({sub()} {k} {sub()})"
    return expr


_m4_expr = _m4_expr_of(FOUR)
_m4_expr_atan = _m4_expr_of(("atan", "atan2"))


def _inv(fn, y, x=None):
    """atan, asin, acos or atan2(y, x) as the exact evaluations take it,
    computed again here: exact at the folds' points, otherwise mpmath's at
    1,024 bits of the arguments rounded to nearest at 1,024 bits; an
    ArithmeticError for asin or acos outside [-1, 1]."""
    import mpmath
    y = Fraction(y)
    if fn == "atan2":
        x = Fraction(x)
        if y == 0 and x >= 0:
            return Fraction(0)
    else:
        if fn != "atan" and abs(y) > 1:
            raise ArithmeticError(f"{fn}({y}) is outside [-1, 1]")
        if y == (1 if fn == "acos" else 0):
            return Fraction(0)
    if not _MP:
        ctx = mpmath.MPContext()
        ctx.prec = TRANS_BITS
        _MP.append((mpmath.libmp, ctx))
    lib, ctx = _MP[0]

    def rd(q):
        return ctx.make_mpf(lib.from_rational(q.numerator, q.denominator,
                                              TRANS_BITS, lib.round_nearest))
    v = ctx.atan2(rd(y), rd(x)) if fn == "atan2" else \
        getattr(ctx, fn)(rd(y))
    sign, man, exp, _bc = v._mpf_
    man = int(man)
    r = Fraction(man << exp) if exp >= 0 else Fraction(man, 1 << -exp)
    return -r if sign else r


def _dual4(op, a, tie=0, zero=1, L=None):
    """_dual with the four: atan's derivative 1 / (1 + x^2), asin's and
    acos's +-1 / sqrt(1 - x^2) with the root as the exact evaluations take
    it (_root), atan2(y, x)'s (x dy - y dx) / (x^2 + y^2); undefined (an
    ArithmeticError) at |x| = 1 for asin and acos and at the origin for
    atan2."""
    if op not in FOUR:
        return _dual(op, a, tie, zero, L)
    v = [p[0] for p in a]
    d = [p[1] for p in a]
    if op == "atan":
        return _inv("atan", v[0]), d[0] / (1 + v[0] * v[0])
    if op in ("asin", "acos"):
        val = _inv(op, v[0])
        if abs(v[0]) == 1:
            raise ArithmeticError(f"{op}'({v[0]})")
        root = _root(1 - v[0] * v[0])
        return val, (d[0] if op == "asin" else -d[0]) / root
    y, x = v
    if x == 0 and y == 0:
        raise ArithmeticError("atan2'(0, 0)")
    return _inv("atan2", y, x), (x * d[0] - y * d[1]) / (x * x + y * y)


def dual_derivative4(g, section, st, tv, pa, la):
    """dual_derivative's, by _dual4."""
    sec = g.section(section)
    nil = Fraction(0)
    vals = {"s": list(zip(st, tv)), "l": [(x, nil) for x in la],
            "p": [(x, nil) for x in pa],
            "c": [(v, nil) for v, *_r in g.const]}
    nodes = []

    def get(r):
        return nodes[int(r[1:])] if r[0] == "n" else vals[r[0]][int(r[1:])]
    for op, args, _l in sec.nodes:
        nodes.append(_dual4(op, [get(a) for a in args]))
    return [get(o)[1] for o in sec.out]


def _inside4(rng, n, bound):
    return [Fraction(rng.randint(-1000 * bound + 1, 1000 * bound - 1), 1000)
            for _ in range(n)]


def exact_misses4(g, rng, points, bound=3):
    """(points decided, points where the tangent section's exact value is
    not the dual numbers' derivative), at states of magnitude below
    `bound`; a point where the derivative is undefined decides nothing."""
    tot = bad_n = 0
    for primal, tangent in (("field", "tangent_field"),
                            ("step", "tangent_step")):
        if g.section(primal) is None:
            continue
        for _ in range(points):
            st = _inside4(rng, g.n_state, bound)
            tv = [_q(rng) for _ in range(g.n_state)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            try:
                want = dual_derivative4(g, primal, st, tv, pa, la)
            except ArithmeticError:
                continue
            tot += 1
            try:
                got = g.exact_eval(tangent, st, pa, la, tangent=tv)
            except ArithmeticError:
                bad_n += 1
                continue
            bad_n += got != want
    return tot, bad_n


def cd_misses4(g, rng, points, eps, tol, bound):
    """(points decided, points where a tangent component is not the
    central difference (S(x + eps v) - S(x - eps v)) / (2 eps) of the
    primal section within tol max(1, |t|)), at states of magnitude below
    `bound`; a point where the exact evaluation is undefined decides
    nothing."""
    tot = bad_n = 0
    for primal, tangent in (("field", "tangent_field"),
                            ("step", "tangent_step")):
        if g.section(primal) is None:
            continue
        for _ in range(points):
            st = _inside4(rng, g.n_state, bound)
            tv = [_q(rng) for _ in range(g.n_state)]
            pa = [_q(rng) for _ in g.param]
            la = [_q(rng) for _ in g.lane]
            try:
                up = g.exact_eval(primal, [s + eps * t for s, t in
                                           zip(st, tv)], pa, la)
                dn = g.exact_eval(primal, [s - eps * t for s, t in
                                           zip(st, tv)], pa, la)
                got = g.exact_eval(tangent, st, pa, la, tangent=tv)
            except ArithmeticError:
                continue
            tot += 1
            bad_n += any(abs((u - d) / (2 * eps) - t) > tol * max(1, abs(t))
                         for u, d, t in zip(up, dn, got))
    return tot, bad_n


def _bits4(fmt, v):
    return K.round_once(fmt, sf.RND_RNE, Fraction(v))[0]


def _atan2_graph(case, fmtname="fp64", rnd="rne"):
    """atan2's three cases: both operands states; b a lane param (a's
    tangent alone); a a lane param (b's alone)."""
    head = f"system r\nformat {fmtname}\nround {rnd}\n"
    body = {"both": "state a, b, y\ntangent v\nnext a = a\nnext b = b\n",
            "db0": "state a, y\nlane param b\ntangent v\nnext a = a\n",
            "da0": "state b, y\nlane param a\ntangent v\nnext b = b\n"}[case]
    return lang.compile_text(head + body + "next y = atan2(a, b)\n"
                             "step map\n").graph


def _run4(case, g, y, x, da, db):
    """(the primal y, the tangent of y, FLAGS, the primal's FLAGS) of one
    lane of atan2's `case` system; for the other three, case is None and
    x the tangent."""
    if case is None:
        r = lang.run(g, [[y, 0]], 1, tangents=[[[da, 0]]])
    elif case == "both":
        r = lang.run(g, [[y, x, 0]], 1, tangents=[[[da, db, 0]]])
    elif case == "db0":
        r = lang.run(g, [[y, 0]], 1, lane_params=[[x]], tangents=[[[da, 0]]])
    else:
        r = lang.run(g, [[x, 0]], 1, lane_params=[[y]], tangents=[[[db, 0]]])
    return r.states[0][-1], r.tangents[0][0][-1], r.flags, r.primal_flags


def _rule4(fn, case, fmt, code, a, b, da, db):
    """The table's tangent on one lane in softfloat -> (bits, the last
    operation's exact value or None). a is the first operand (y for
    atan2), b the second."""
    val = lambda q: K.value_of(fmt, q)                      # noqa: E731
    one = _bits4(fmt, 1)
    if fn == "atan2":
        den = sf.fma(fmt, b, b, sf.mul(fmt, a, a, code)[0], code)[0]
        if case == "both":
            num = sf.fma(fmt, b, da, sf.neg(fmt, sf.mul(
                fmt, a, db, code)[0])[0], code)[0]
        elif case == "db0":
            num = sf.mul(fmt, b, da, code)[0]
        else:
            num = sf.neg(fmt, sf.mul(fmt, a, db, code)[0])[0]
    else:
        num = da
        if fn == "atan":
            den = sf.fma(fmt, a, a, one, code)[0]
        else:
            den = sf.sqrt(fmt, sf.fma(fmt, sf.neg(fmt, a)[0], a, one,
                                      code)[0], code)[0]
            if fn == "acos":
                den = sf.neg(fmt, den)[0]
    bits = sf.div(fmt, num, den, code)[0]
    try:
        return bits, val(num) / val(den), val(num), val(den)
    except (ValueError, ZeroDivisionError):
        return bits, None, None, None


def rounding_misses4(fn, case, fmtname, rnd, rng, lanes=6):
    """(lanes, lanes whose tangent is not the table's rule rounded as the
    table says, lanes whose last division's exact value is not the
    derivative within the roundings of its operands) on y = fn(a) (atan2
    in `case`): the derivative by a central difference at 2^-256 of the
    1,024-bit values; a is within 7/8 for asin and acos."""
    g = _atan2_graph(case, fmtname, rnd) if fn == "atan2" else \
        _one(fn, fmtname, rnd)
    fmt, code = g.fmt, K.RND_BY_NAME[rnd]
    u = Fraction(1, 1 << (fmt.prec - 1))

    def draw():
        if fn in ("asin", "acos"):
            return Fraction(rng.randint(-875, 875), 1000)
        q = Fraction(rng.randint(-64000, 64000), 1000)
        return q + 1 if fn == "atan2" and abs(q) < Fraction(1, 100) else q
    rows = [(_bits4(fmt, draw()), _bits4(fmt, draw()),
             _bits4(fmt, Fraction(rng.randint(-4000, 4000) or 1, 1000)),
             _bits4(fmt, Fraction(rng.randint(-4000, 4000) or 1, 1000)))
            for _ in range(lanes)]
    bits_bad = value_bad = 0
    for a, b, da, db in rows:
        if fn == "atan2":
            db_ = 0 if case == "db0" else db
            da_ = 0 if case == "da0" else da
            _y, t, _f, _pf = _run4(case, g, a, b, da_, db_)
        else:
            da_, db_ = da, 0
            _y, t, _f, _pf = _run4(None, g, a, 0, da_, 0)
        want, exact, num, den = _rule4(fn, case, fmt, code, a, b, da_, db_)
        bits_bad += t != want
        av, bv = K.value_of(fmt, a), K.value_of(fmt, b)
        dav, dbv = K.value_of(fmt, da_), K.value_of(fmt, db_)
        if fn == "atan2":
            d = (_inv("atan2", av + HP_EPS * dav, bv + HP_EPS * dbv)
                 - _inv("atan2", av - HP_EPS * dav, bv - HP_EPS * dbv)) \
                / (2 * HP_EPS)
            eps = (u * abs(av * dbv) + u * abs(num)) / (av * av + bv * bv)
            bound = (eps + Fraction(21, 10) * u * abs(d)) * Fraction(11, 10)
        else:
            d = (_inv(fn, av + HP_EPS * dav) - _inv(fn, av - HP_EPS * dav)) \
                / (2 * HP_EPS)
            bound = (1 if fn == "atan" else 2) * u * Fraction(101, 100) \
                * abs(d)
        value_bad += abs(exact - d) > bound + Fraction(1, 1 << 400)
    return len(rows), bits_bad, value_bad


def inv_golden_misses(fn, fmtname, rnd, rng):
    """(lanes, lanes where the interpreter's node is not transcend.compute's
    bits and flags) for atan, asin, acos on y = fn(a) and for atan2 over
    pairs of the specials, y first."""
    fmt, code = FORMATS[fmtname], K.RND_BY_NAME[rnd]
    sp = [0, fmt.sign_mask, sf.inf_bits(fmt), sf.inf_bits(fmt) ^ fmt.sign_mask,
          sf.qnan_bits(fmt), sf.snan_bits(fmt, 1), _bits4(fmt, 1),
          _bits4(fmt, -1)]
    if fn == "atan2":
        sp += [_bits4(fmt, Fraction(rng.randint(-1 << 20, 1 << 20), 997))
               for _ in range(4)]
        pairs = [(y, x) for y in sp for x in sp]
        g = lang.compile_text(f"system r\nformat {fmtname}\nround {rnd}\n"
                              "state x, y\nnext x = atan2(x, y)\nnext y = y\n"
                              "step map\n").graph
        run = lang.run(g, [list(p) for p in pairs], 1)
        bad_n = sum(st != [transcend.compute(fmt, "atan2", y, x, code)[0], x]
                    for (y, x), st in zip(pairs, run.states))
        return len(pairs), bad_n
    sp += [_bits4(fmt, Fraction(rng.randint(-1000, 1000), 1000))
           for _ in range(8)]
    g = _one(fn, fmtname, rnd)
    run = lang.run(g, [[a, 0] for a in sp], 1,
                   tangents=[[[0, 0]] for _ in sp])
    bad_n = sum(st[1] != transcend.compute(fmt, fn, a, 0, code)[0]
                for a, st in zip(sp, run.states))
    return len(sp), bad_n


def inv_specials_misses():
    """At every format under every attribute, bit for bit against the
    table's own operations (_rule4): asin and acos at +-1, +-0, past +-1,
    +-inf and a NaN, atan likewise, atan2 at its axes, the origin and
    the infinities; and by name, where the rule is not the derivative:
    asin's and acos's tangent at a = +-1 is an infinity with
    divideByZero (da / +0, da / -0 under rdn for asin, the sign flipped
    for acos), atan2's at the origin the invalid NaN in each of its three
    cases. -> a list of what missed."""
    miss = []
    for fmtname in FORMATS:
        fmt = FORMATS[fmtname]
        sign, inf, qnan = fmt.sign_mask, sf.inf_bits(fmt), sf.qnan_bits(fmt)
        three, two = _bits4(fmt, 3), _bits4(fmt, 2)
        pts = [_bits4(fmt, v) for v in (1, -1, 2, -2)] + [
            0, sign, inf, inf ^ sign, qnan, sf.snan_bits(fmt, 1), 1]
        for rnd in RNDS5:
            code = K.RND_BY_NAME[rnd]
            for fn in ONE4:
                g = _one(fn, fmtname, rnd)
                for a in pts:
                    _y, t, f, pf = _run4(None, g, a, 0, three, 0)
                    if t != _rule4(fn, None, fmt, code, a, 0, three, 0)[0]:
                        miss.append(f"{fn} at {hex(a)} under {rnd} "
                                    f"at {fmtname}")
                if fn != "atan":
                    for a in pts[:2]:
                        _y, t, f, pf = _run4(None, g, a, 0, three, 0)
                        zero = sign if rnd == "rdn" else 0
                        flip = sign if fn == "acos" else 0
                        if t != inf ^ zero ^ flip or not f & sf.FLAG_DIVZERO:
                            miss.append(f"{fn} at +-1 under {rnd} at "
                                        f"{fmtname}")
            for case in ("both", "db0", "da0"):
                g = _atan2_graph(case, fmtname, rnd)
                for y, x in [(0, 0), (sign, 0), (0, sign), (sign, sign),
                             (pts[0], 0), (0, pts[1]), (pts[0], pts[1]),
                             (inf, pts[0]), (pts[0], inf), (inf, inf),
                             (qnan, pts[0]), (pts[0], qnan)]:
                    da_, db_ = (0 if case == "da0" else three,
                                0 if case == "db0" else two)
                    _y, t, f, pf = _run4(case, g, y, x, da_, db_)
                    if t != _rule4("atan2", case, fmt, code, y, x, da_,
                                   db_)[0]:
                        miss.append(f"atan2 {case} at {hex(y)}, {hex(x)} "
                                    f"under {rnd} at {fmtname}")
                for y, x in ((0, 0), (sign, 0), (0, sign), (sign, sign)):
                    da_, db_ = (0 if case == "da0" else three,
                                0 if case == "db0" else two)
                    _y, t, f, pf = _run4(case, g, y, x, da_, db_)
                    if t != qnan or not f & sf.FLAG_INVALID or \
                            pf & sf.FLAG_INVALID:
                        miss.append(f"atan2 {case} at the origin under "
                                    f"{rnd} at {fmtname}")
    return miss


class _M4Plant(lang_tangent.Derivation):
    """The derivation with one of the four's rules changed (kind)."""
    kind = None

    def rule(self, node):
        a, R = node.args, self.read

        def N(o, *args):
            return Node(o, args, node.line)
        k = self.kind
        t = [self.of(x) for x in a]
        if node.op in ONE4 and t[0] is not None:
            da = t[0]
            if node.op == "atan":
                den = N("fma", R(a[0]), R(a[0]), self.one)
                if k == "atan's rule: da * fma(a, a, 1)":
                    return N("mul", da, den)
                if k == "atan's rule rounded otherwise":
                    return N("mul", N("div", self.one, den), da)
            else:
                inner = N("fma", N("neg", R(a[0])), R(a[0]), self.one)
                if node.op == "asin":
                    if k == "asin's rule without its root":
                        return N("div", da, inner)
                    if k == "asin's rule rounded otherwise":
                        prod = N("mul", N("sub", self.one, R(a[0])),
                                 N("add", self.one, R(a[0])))
                        return N("div", da, N("sqrt", prod))
                else:
                    if k == "acos's rule without its minus":
                        return N("div", da, N("sqrt", inner))
                    if k == "acos's rule rounded otherwise":
                        return N("neg", N("div", da, N("sqrt", inner)))
        if node.op == "atan2" and t[0] is not None and t[1] is not None:
            den = N("fma", R(a[1]), R(a[1]), N("mul", R(a[0]), R(a[0])))
            if k == "atan2's rule: a da - b db":
                return N("div", N("fma", R(a[0]), t[0], N("neg", N(
                    "mul", R(a[1]), t[1]))), den)
            if k == "atan2's rule rounded otherwise":
                return N("div", N("fma", R(a[1]), t[0], N(
                    "mul", N("neg", R(a[0])), t[1])), den)
        return super().rule(node)


def math_four(count, rng):
    """Leg M's checks for atan, asin, acos and atan2 (M4's build), after
    the three's: the same five, then ten plants. The exact dual numbers are
    leg D's discipline, made on these systems; the central difference in
    high precision is this leg's own, at 2^-256 within 2^-300 where the
    graph holds no square root (atan, atan2) and at 2^-64 within 2^-100
    where it does (asin, acos: the rule's root is rounded down to 2^-256 by
    the exact evaluation, so a difference at 2^-256 would measure that
    rounding)."""
    t0 = time.perf_counter()
    texts = m1_texts(count, "tangent math four", M4_SHAPES, _m4_expr)
    texts += m1_texts(count // 2, "tangent math four atan", {},
                      _m4_expr_atan)
    graphs = m1_graphs(texts)
    tot = bad_n = 0
    hi = rt = 0
    hi_bad = rt_bad = 0
    decided = dict.fromkeys(FOUR, 0)
    cd_decided = dict.fromkeys(FOUR, 0)
    changed = []
    for g, text, what in graphs:
        held = set(FOUR) & set(g.op_counts("step"))
        a, b = exact_misses4(g, rng, 3)
        tot, bad_n = tot + a, bad_n + b
        for fn in held:
            decided[fn] += a
        if {"asin", "acos", "sqrt"} & set(g.op_counts("step")):
            a, b = cd_misses4(g, rng, 3, ROOT_EPS, ROOT_TOL, 2)
            rt, rt_bad = rt + a, rt_bad + b
        else:
            a, b = cd_misses4(g, rng, 3, HP_EPS, HP_TOL, 3)
            hi, hi_bad = hi + a, hi_bad + b
        for fn in held:
            cd_decided[fn] += a
        states = LC.lanes_for(g.fmt, g.n_state, rng, 3)
        states += LC.special_lanes(g.fmt, g.n_state, states[0], rng)
        if not primal_unchanged(g, without_tangent(text), states, 2):
            changed.append(what)
    ops = set()
    for g, _t, _w in graphs:
        ops |= set(g.op_counts("step"))
    check(bad_n == 0 and set(FOUR) <= ops and
          all(v >= 10 for v in decided.values()),
          f"{len(graphs)} systems holding atan, asin, acos and atan2, {tot} "
          f"points: the tangent sections evaluated exactly equal this "
          f"stage's own derivative (leg D's check, made on the four); "
          f"points decided per function (the floor is 10): "
          f"{', '.join(f'{k} {decided[k]}' for k in FOUR)}",
          f"{bad_n} differ, decided {decided}")
    check(hi_bad == 0 and hi >= 20, f"{hi} points: every tangent component "
          f"within 2^-300 of the central difference at eps = 2^-256 of "
          f"1,024-bit values, on the graphs holding no asin, acos or "
          f"square root - leg M's own check", f"{hi_bad} differ, {hi} "
          f"decided")
    check(rt_bad == 0 and rt >= 40, f"{rt} points: every tangent component "
          f"within 2^-100 of the central difference at eps = 2^-64, states "
          f"of magnitude below 2 (arguments of asin and acos at most 2/3), "
          f"on the graphs holding asin, acos or a square root", f"{rt_bad} "
          f"differ, {rt} decided")
    # asin and acos as y = f(a), a within 7/8: their central difference,
    # run on its own points, never left out
    one_tot = one_bad = 0
    for fn in ("asin", "acos"):
        for fmtname in FORMATS:
            g = _one(fn, fmtname, "rne")
            for _ in range(8):
                a = Fraction(rng.randint(-875, 875), 1000)
                tv = _q(rng)
                up = g.exact_eval("step", [a + ROOT_EPS * tv, Fraction(0)])
                dn = g.exact_eval("step", [a - ROOT_EPS * tv, Fraction(0)])
                got = g.exact_eval("tangent_step", [a, Fraction(0)],
                                   tangent=[tv, Fraction(0)])
                one_tot += 1
                one_bad += any(abs((u - d) / (2 * ROOT_EPS) - t) >
                               ROOT_TOL * max(1, abs(t))
                               for u, d, t in zip(up, dn, got))
    check(one_bad == 0 and one_tot == 2 * 4 * 8,
          f"{one_tot} points of y = asin(a) and y = acos(a), |a| at most "
          f"7/8, four formats: the tangent within 2^-100 of the central "
          f"difference at eps = 2^-64 - run, none skipped", f"{one_bad} "
          f"differ of {one_tot}")
    check(all(v >= 10 for k, v in cd_decided.items()), "points decided by "
          f"the central difference per function (the floor is 10): "
          f"{', '.join(f'{k} {cd_decided[k]}' for k in FOUR)}",
          f"{cd_decided}")
    check(not changed, "the primal unchanged in each: its states and flags "
          "without the tangent, on lanes that overflow, hold a signalling "
          "NaN and hold subnormals", f"changed: {changed[:4]}")
    lanes = bits = value = glanes = gbad = 0
    cells = []
    for fn in FOUR:
        for case in (("both", "db0", "da0") if fn == "atan2" else (None,)):
            for fmtname in ("fp32", "fp64", "fp128", "fp256"):
                for rnd in RNDS5:
                    n, b, v = rounding_misses4(fn, case, fmtname, rnd, rng)
                    lanes, bits, value = lanes + n, bits + b, value + v
                    cells.append((fn, case, fmtname, rnd))
        for fmtname in ("fp32", "fp64", "fp128", "fp256"):
            for rnd in RNDS5:
                n, b = inv_golden_misses(fn, fmtname, rnd, rng)
                glanes, gbad = glanes + n, gbad + b
    check(bits == 0 and value == 0 and gbad == 0 and
          len(cells) == 6 * 4 * 5 and lanes == 6 * len(cells),
          f"{lanes} lanes of y = f(a) over {len(cells)} cells (atan, asin, "
          f"acos and atan2's three cases, every format and attribute): each "
          f"tangent the table's last division rounded once on the "
          f"denominator and numerator the table rounds first, and that "
          f"division's exact value the derivative within their roundings; "
          f"and {glanes} lanes in which the node's own result is the "
          f"golden function's, bit for bit (atan2 over pairs of the "
          f"specials, y first)", f"{bits} in bits, {value} in value, "
          f"{gbad} golden")
    miss = inv_specials_misses()
    check(not miss, "the specials, bit for bit at every format under every "
          "attribute: asin and acos at +-1 an infinity with divideByZero, "
          "past +-1 the NaN, atan at +-inf a zero, atan2 at the origin the "
          "invalid NaN in each case", "; ".join(miss[:6]))
    plant_texts = m1_texts(4, "tangent math plants four", M4_SHAPES,
                           _m4_expr)
    original = lang_check_mod.Derivation
    from cft_golden.lang import interp as lang_interp
    orig_t = lang_interp._transcend
    plants = ("atan's rule: da * fma(a, a, 1)", "asin's rule without its root",
              "acos's rule without its minus", "atan2's rule: a da - b db",
              "atan's rule rounded otherwise", "asin's rule rounded otherwise",
              "acos's rule rounded otherwise",
              "atan2's rule rounded otherwise",
              "atan's golden function swapped for asin's",
              "atan2's operands swapped in the interpreter")
    try:
        for kind in plants:
            lang_check_mod.Derivation = original
            lang_interp._transcend = orig_t
            golden = "golden" in kind or "swapped" in kind
            if kind.startswith("atan's golden"):
                lang_interp._transcend = (
                    lambda fmt, fn, rnd: orig_t(fmt, "asin" if fn == "atan"
                                                else fn, rnd))
            elif golden:
                def swapped(fmt, fn, rnd):
                    f = orig_t(fmt, fn, rnd)
                    return (lambda a, b: f(b, a)) if fn == "atan2" else f
                lang_interp._transcend = swapped
            else:
                class P(_M4Plant):
                    pass
                P.kind = kind
                lang_check_mod.Derivation = P
            fn = kind.split("'")[0]
            case = "both" if fn == "atan2" else None
            graph_of = (lambda f: _atan2_graph("both", f)) if fn == "atan2" \
                else (lambda f: _one(fn, f))
            ex = hp = exd = 0
            for fmtname in ("fp32", "fp64", "fp256"):
                g = graph_of(fmtname)
                # asin's and acos's points inside (-1, 1), where they decide
                a, b = exact_misses4(g, rng, 3, 1 if fn in ("asin", "acos")
                                     else 3)
                exd, ex = exd + a, ex + b
                if fn in ("asin", "acos"):
                    hp += cd_misses4(g, rng, 3, ROOT_EPS, ROOT_TOL, 2)[1]
                else:
                    hp += cd_misses4(g, rng, 3, HP_EPS, HP_TOL, 3)[1]
            per = dict.fromkeys(RNDS5, 0)
            for fmtname in ("fp32", "fp64", "fp256"):
                for rnd in RNDS5:
                    per[rnd] += rounding_misses4(fn, case, fmtname, rnd, rng,
                                                 24)[1]
            gold = sum(inv_golden_misses(fn, "fp64", rnd, rng)[1]
                       for rnd in RNDS5)
            said = (f"plant {kind!r}: the exact check {ex}, the central "
                    f"difference {hp}, the rounding in bits at finite lanes "
                    f"under rne, rtz, rdn, rup, rmm "
                    f"{', '.join(str(per[r]) for r in RNDS5)}, the golden "
                    f"check {gold}")
            if not golden:
                check(exd >= 6, f"plant {kind!r}: the exact check decided "
                      f"{exd} points (the floor is 6), so a check that "
                      f"decides none is red", f"{exd}")
            if golden:
                check(ex == 0 and hp == 0 and gold > 0, said + " - red on "
                      "the golden check; green on both exact checks, which "
                      "never run the interpreter's table")
            elif "rounded otherwise" in kind:
                if fn in ("atan", "asin"):
                    check(ex == 0 and hp == 0 and
                          all(v > 0 for v in per.values()), said + " - "
                          "exact in rationals: green on both exact checks, "
                          "red on the rounding under every attribute")
                else:
                    check(ex == 0 and hp == 0 and
                          per["rne"] == per["rtz"] == per["rmm"] == 0 and
                          per["rdn"] > 0 and per["rup"] > 0, said + " - "
                          "exact in rationals: green on both exact checks; "
                          "red on the rounding at finite lanes under rdn "
                          "and rup only, where the two forms differ, green "
                          "under rne, rtz and rmm (atan2: the case with "
                          "both tangents)")
            else:
                check(ex > 0 and hp > 0 and all(v > 0 for v in per.values()),
                      said + " - red on the exact check, the difference "
                      "and the rounding, under every attribute")
    finally:
        lang_check_mod.Derivation = original
        lang_interp._transcend = orig_t
    print(f"  (atan, asin, acos and atan2: {time.perf_counter() - t0:.1f} s)")


def leg_math(count, rng):
    section(f"M. the math library's rules, golden - the six (M1's build, "
            f"item 3) and sin, cos and tan (M2's build): "
            f"{len(M1_SHAPES) + len(M2_SHAPES)} written shapes and "
            f"{2 * count} generated systems with tangent vectors - the "
            f"derivative exactly (leg D's check) and by a central "
            f"difference in high precision (this leg's own), the primal "
            f"unchanged, each rule's rounding bit for bit at every format "
            f"and attribute, the specials, plants")
    if not LC.have_mpmath():
        skip("M: the math library's nine rules", "python has no mpmath "
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
    print(f"  (the six: {time.perf_counter() - t0:.1f} s)")
    math_three(count, rng)
    math_four(count, rng)


# ---- N: the math library's six, compiled with tangent vectors (item 5) -----
#
# Leg M holds the six's rules in the golden model; the compiler carries the
# six since M1's build, item 4, and these are the compiled legs its record
# names: generated systems that call them, with one tangent vector and with
# two, under every integrator, format and attribute, compiled for the software
# backend and run on seq.py against lang.run - states, every tangent, lane
# params and FLAGS - under the marked-lane rule of lang_check.py (which the
# whole stage shares): a lane whose byte carries the mark is replayed whole,
# its states and its tangents the definition's, and the image's guess is
# counted. The structured families' centres (python/tests/mathlib_family.py)
# are put in the lanes' primal where the calls read it, so that a mark
# reaches the tangent comparison: a marked lane's guess can be wrong, and its
# tangents, which the image computes from that guess, are wrong with it.
# Leg G's guard stands: version 1 holds the machine's guess, STATUS[6] on
# the segment; cft-segrun's version-2 writer, which leg G does not use,
# refuses a marked lane `replay-missing` without a replay image and
# `replay-undecided` with one that marks it too; and a certified segment
# that marks a lane still fails there by name.

def six_controls():
    """The rule's controls with a tangent vector (lang_check's leg O has the
    rest): exp at fp64 under rne, x = 2^-53 - the one lane there whose guess
    is wrong, 1.0 for 1 + 2^-52 - x = 3 * 2^-53, whose guess is right, and
    two ordinary lanes, with tangents; each fault planted in a copy of the
    runs and judged by the rule."""
    c = cftc.compile_text("system te\nformat fp64\nround rne\nstate x\n"
                          "tangent v\nnext x = exp(x)\nstep map\n", 5,
                          source="tangent controls", stem="t")
    fam = LC.family()
    f64 = FORMATS["fp64"]
    states = [[fam.argument(f64, (1, 53))], [fam.argument(f64, (3, 53))],
              [K.round_once(f64, sf.RND_RNE, Fraction(3, 10))[0]],
              [K.round_once(f64, sf.RND_RNE, Fraction(-7, 10))[0]]]
    tans = [[[K.round_once(f64, sf.RND_RNE, Fraction(q))[0]]]
            for q in (Fraction(3, 2), Fraction(-5, 4), Fraction(1, 3),
                      Fraction(7, 5))]
    fx = LC.Fixture(c, states, 2, tans=tans)
    m = c.ir.m                  # values a lane: x, then its tangent
    base = fx.verdict()
    per = base.per

    def tangent(k, bit=0):
        return LC.value_edit(k, m, 1, bit)
    t_ok = (0 in per[1].wrong_tangents and per[1].wrong == [0] and
            1 not in per[1].wrong)
    LC.check(not base.failing and base.flags_ok and per[1].marked == [0, 1]
             and t_ok and base.first is None,
             "N0a. exp at fp64 under rne with a tangent vector, x = 2^-53 "
             "(marked, the guess 1.0 where 1 + 2^-52 is due) and 3 * 2^-53 "
             "(marked, right): both replayed whole - the first's guess wrong "
             "in its state and in its tangent, r * da with r the guess - the "
             "ordinary lanes bit for bit, FLAGS and STATUS fine",
             base.describe())
    v = fx.verdict(LC.at_step(2, tangent(3)))
    LC.check(v.failing == {3} and "lane-value" in v.broken and v.first == 2
             and "tangents" in " ".join(v.per[2].why) and v.flags_ok,
             "N0b. a bit flipped in an unmarked lane's tangent (lane 3 at 2 "
             "steps) is red there - lane-value, in its tangents", v.describe())
    v = fx.verdict(LC.at_step(1, tangent(1, 40)))
    LC.check(not v.failing and v.flags_ok and v.per[1].wrong == [0, 1] and
             v.per[1].wrong_tangents == [0, 1],
             "N0c. a marked lane whose guess is wrong in its tangent alone "
             "(lane 1, a bit flipped, at 1 step) is replayed whole and the "
             "guess counted wrong in its tangents - the rule requires "
             "nothing of a guess, a tangent's included", v.describe())
    v = fx.verdict(LC.at_step(1, LC.byte_edit(0, clear=LC.LANE_MARKED),
                              onward=True))
    LC.check(0 in v.failing and "lane-value" in v.broken and v.first == 1,
             "N0d. the wrong-guess lane with its mark silenced (lane 0, from "
             "1 step) is a fault - its state and its tangent are wrong and "
             "unmarked: lane-value", v.describe())


def leg_six(count, rng, everything=False):
    section(f"N. the math library's six compiled, with tangent vectors "
            f"(M1's build, item 5): {count} generated systems that call "
            f"them, one vector and two, run on seq.py against the "
            f"interpreter - states, every tangent and FLAGS - with marked "
            f"lanes replayed whole")
    if not LC.have_mpmath():
        skip("N: the math library's six, compiled with tangent vectors",
             "python has no mpmath module, which their golden functions and "
             "their routines' generator need (leg M, G and H skip by name "
             "with it)")
        return
    fam = LC.family()
    t0 = time.perf_counter()
    six_controls()
    wrong, internal, tally = [], [], {}
    held = marked = guess = gtan = demanded = refused = flags = 0
    seen = {"formats": set(), "rounds": set(), "integrators": set(),
            "vectors": set(), "six": set()}
    t_compile = t_run = 0.0
    for k in range(count):
        text, direct, comps = LC.g_six(random.Random(f"tangent six {k}"), k,
                                       tangent=True)
        what = f"tangent six {k}"
        try:
            g = lang.compile_text(text, what).graph
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            if e.name not in LC.SIX_ARTIFACTS:
                wrong.append(f"{what}: the language refused {e}")
            continue
        if not g.tangent or not {op for op in g.op_counts("step")
                                 if op in LC.SIX}:
            wrong.append(f"{what}: no tangent vector, or none of the six")
        try:
            t1 = time.perf_counter()
            c = cftc.compile_text(text, 5, source=what, stem="t")
            t_compile += time.perf_counter() - t1
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            wrong.append(f"{what}: refused {e.name}: {e.sentence[:100]}")
            continue
        except cftc.InternalError as e:
            internal.append(f"{what}: internal error (exit 70): "
                            f"{str(e)[:120]}")
            continue
        lanes, roles = LC.six_source_lanes(g, rng, direct, comps, k,
                                           everything)
        n, T = g.n_state, len(g.tangent)
        tans = [[LC.lanes_for(g.fmt, n, rng, 1)[0] for _ in g.tangent]
                for _ in lanes]
        # the three lanes whose tangents are special - a signalling NaN; a
        # -0 and a subnormal; the largest finite - on the first lane's state
        tspec = tangent_specials(g.fmt, n, T, tans[0])
        lanes += [list(lanes[0]) for _ in tspec]
        tans += tspec
        roles += ["special tangent"] * 3
        t1 = time.perf_counter()
        v = LC.rule_compare(c, lanes, 5, tans=tans, tag="tangent six")
        t_run += time.perf_counter() - t1
        flags |= v.ref.flags
        must = [i for i, r in enumerate(roles)
                if isinstance(r, tuple) and fam.classify(
                    g.fmt, LC.RND_CODE[g.round_name], lanes[i][r[3]], None,
                    r[1]) == "mark"]
        lost = [roles[i][1:3] for i in must if i not in v.per[1].marked]
        marked += len(v.marked)
        guess += len(v.wrong)
        gtan += len(v.wrong_tangents)
        demanded += len(must)
        seen["formats"].add(g.fmt.name)
        seen["rounds"].add(g.round_name)
        seen["integrators"].add(g.integrator[0])
        seen["vectors"].add(T)
        seen["six"] |= {op for op in g.op_counts("step") if op in LC.SIX}
        if v.failing or not v.flags_ok:
            wrong.append(f"{what}: {len(v.failing)} unmarked lanes differ; "
                         f"{v.describe()}")
        elif lost:
            wrong.append(f"{what}: demanded and not marked: {lost[:3]}")
        else:
            held += 1
        if k == 0:
            refused += LC.check_refused_rev7(text, what, wrong, internal, 5)
    for f in (internal + wrong)[:10]:
        print(f"        {f}")
    print(f"  outcomes: {dict(sorted(tally.items())) or 'none refused'}; "
          f"compile {t_compile:.1f} s, run under the rule {t_run:.1f} s; "
          f"FLAGS over the {held} systems held: {flags:#x}")
    check(not internal, f"no InternalError: {count} generated systems that "
          f"call the six with tangent vectors",
          f"{len(internal)} stopped the compiler with an internal error, "
          f"exit 70")
    check(not wrong and held >= count // 2 and
          seen["formats"] == {"fp32", "fp64", "fp128", "fp256"} and
          seen["rounds"] == {"rne", "rtz", "rdn", "rup", "rmm"} and
          seen["integrators"] >= {"rk4", "euler", "stormer-verlet", "map"}
          and seen["vectors"] == {1, 2} and seen["six"] == set(LC.SIX),
          f"N. {held} generated systems holding all six, with one tangent "
          f"vector and with two, at every format, under every attribute and "
          f"under {', '.join(sorted(seen['integrators']))}, compiled for sw "
          f"and run on seq.py at 1, 2 and 5 steps equal to the interpreter, "
          f"states, every tangent and FLAGS, under the marked-lane rule: "
          f"structured arguments of the families in the primal "
          f"({demanded} the theory demands marked, every one marked), "
          f"{marked} lanes marked and replayed whole, {guess} guesses wrong "
          f"in their states and {gtan} of them in their tangents too; the "
          f"first refused `target-feature`, naming FLAG_CONTROL, by revision "
          f"7's {len(LC.REV7_TARGETS)} targets ({refused}) "
          f"({time.perf_counter() - t0:.1f} s)",
          f"{len(wrong)} otherwise; seen {seen}")


# ---- T: sin, cos and tan compiled, with tangent vectors (M2's build, wave 4) -
#
# Leg M holds the three's rules golden-only; this leg compiles systems that
# call them - leg M's written shapes (M2_SHAPES) and generated systems
# (_m2_expr, through m1_texts), and lang_check's g_three sources - with one
# tangent vector and two, and runs them on seq.py under the rule. Structured
# centres of the families (python/tests/mathlib_trig_family.py) are put in the
# primal, and at fp128 and fp256 lanes past the range, which are marked
# whatever the test says and whose guesses are wrong far enough out: sin's
# tangent reads cos(a), a second call whose guess is wrong there too, so a
# marked lane's tangents, replayed whole, are counted wrong in a real lane
# and M1's plant P6 (a marked lane's tangents left unreplayed) has a lane to
# be red on besides the controls.
#
# A LANE MARKED BY THE TANGENT'S COS ALONE (control T0c). The pendulum's
# primal holds sin and its tangent cos: at a cos centre that is not a sin
# centre only cos(theta), the tangent's call, marks. R23's byte is one a lane,
# so the mark excuses the lane's primal state as well as its tangents: the
# lane is replayed whole.

def three_controls():
    """T0a to T0d, the rule's controls with a tangent vector for the three
    (lang_check's leg O has the rest): each fault planted in a copy of the
    runs and judged by the rule."""
    f64, f256 = FORMATS["fp64"], FORMATS["fp256"]
    tf, _th = LC.trig()

    def d(F, q):
        return K.round_once(F, sf.RND_RNE, Fraction(q))[0]

    def tans_of(F, qs):
        return [[[d(F, q)]] for q in qs]
    # T0a: cos(2^-26) under rtz at fp64, marked, the guess right
    c = cftc.compile_text("system te\nformat fp64\nround rtz\nstate x\n"
                          "tangent v\nnext x = cos(x)\nstep map\n", 5,
                          source="three controls a", stem="t")
    states = [[tf.argument(f64, (1, 26))], [d(f64, Fraction(3, 10))],
              [d(f64, Fraction(-7, 10))]]
    fx = LC.Fixture(c, states, 2, tans=tans_of(
        f64, (Fraction(3, 2), Fraction(-5, 4), Fraction(1, 3))))
    v = fx.verdict()
    LC.check(not v.failing and v.flags_ok and v.per[1].marked == [0] and
             v.per[1].wrong == [] and v.per[1].wrong_tangents == [] and
             v.first is None,
             "T0a. cos at fp64 under rtz with a tangent vector, x = 2^-26 "
             "(a cos centre: marked, the guess right in its state and its "
             "tangent), the ordinary lanes bit for bit, FLAGS and STATUS "
             "fine", v.describe())
    # T0b: sin at fp256, a lane far past the range: marked, wrong in its
    # state and in its tangent (cos(a) is wrong there too)
    c = cftc.compile_text("system te\nformat fp256\nround rne\nstate x\n"
                          "tangent v\nnext x = sin(x)\nstep map\n", 5,
                          source="three controls b", stem="t")
    far = dict((r, b) for b, r in LC.range_lanes(f256))
    states = [[far["range 2^4096"]], [far["range 2^R successor"]],
              [d(f256, Fraction(3, 10))], [d(f256, Fraction(-7, 10))]]
    fx = LC.Fixture(c, states, 2, tans=tans_of(
        f256, (Fraction(3, 2), Fraction(-5, 4), Fraction(1, 3),
               Fraction(7, 5))))
    m = c.ir.m
    v = fx.verdict()
    LC.check(not v.failing and v.flags_ok and v.per[1].marked == [0, 1] and
             v.per[1].wrong == [0] and v.per[1].wrong_tangents == [0] and
             v.first is None,
             "T0b. sin at fp256 under rne with a tangent vector, x = 2^4096 "
             "and 2^1024's successor (both past the range, so both marked "
             "whatever the test says): the first's guess wrong in its state "
             "and in its tangent, cos(a) being wrong there too, the second's "
             "right; both replayed whole, the ordinary lanes bit for bit",
             v.describe())
    v = fx.verdict(LC.at_step(2, LC.value_edit(3, m, 1, 0)))
    LC.check(v.failing == {3} and "lane-value" in v.broken and v.first == 2
             and "tangents" in " ".join(v.per[2].why) and v.flags_ok,
             "T0b'. a bit flipped in an unmarked lane's tangent (lane 3 at 2 "
             "steps) is red there - lane-value, in its tangents",
             v.describe())
    v = fx.verdict(LC.at_step(1, LC.byte_edit(0, clear=LC.LANE_MARKED),
                              onward=True))
    LC.check(0 in v.failing and "lane-value" in v.broken and v.first == 1,
             "T0d. the wrong-guess lane past the range with its mark "
             "silenced (lane 0, from 1 step) is a fault - its state and its "
             "tangent are wrong and unmarked: lane-value", v.describe())
    # T0c: the pendulum's shape at a cos centre under a directed attribute
    # at fp64: only the tangent's cos(theta) marks the lane
    head = ("system pend\nformat fp64\nround rdn\nstate theta, omega\n")
    body = ("param g = 9.81\nparam len = 1.5\nd/dt theta = omega\n"
            "d/dt omega = -(g / len) * sin(theta)\nstep rk4, h = 1/64\n")
    c = cftc.compile_text(head + "tangent v\n" + body, 5,
                          source="three controls c", stem="t")
    c0 = cftc.compile_text(head + body, 5, source="three controls c0",
                           stem="t")
    states = [[tf.argument(f64, (1, 26)), d(f64, Fraction(1, 5))],
              [d(f64, Fraction(3, 10)), d(f64, Fraction(1, 5))],
              [d(f64, Fraction(-7, 10)), d(f64, Fraction(-1, 3))]]
    tans = [[[d(f64, q1), d(f64, q2)]] for q1, q2 in
            ((Fraction(3, 2), Fraction(1, 7)), (Fraction(-5, 4), Fraction(2)),
             (Fraction(1, 3), Fraction(-3, 4)))]
    fx = LC.Fixture(c, states, 2, tans=tans)
    m = c.ir.m
    v = fx.verdict()
    alone = LC.rule_compare(c0, states, 2, tally=False)
    LC.check(not v.failing and v.flags_ok and v.per[1].marked == [0] and
             alone.marked == [] and not alone.failing,
             "T0c. the pendulum's shape under rdn at fp64, theta = 2^-26 (a "
             "cos centre): the lane is marked with the tangent vector, "
             "and not marked without it - sin(theta) alone does not mark it, "
             "so the tangent's cos does", f"{v.describe()}; marked "
             f"{v.per[1].marked}, without the tangent {alone.marked}")
    v = fx.verdict(LC.at_step(1, LC.value_edit(0, m, 0, 40)))
    w = fx.verdict(LC.at_step(1, LC.value_edit(1, m, 0, 40)))
    LC.check(not v.failing and v.flags_ok and 0 in v.per[1].wrong and
             w.failing == {1} and "lane-value" in w.broken,
             "T0c'. R23 is one byte a lane, so that mark excuses the lane's "
             "primal state too: a bit flipped in the marked lane's theta "
             "(lane 0, 1 step) is replayed and counted wrong, not red; the "
             "same flip in the unmarked lane 1 is red - lane-value",
             f"{v.describe()}; {w.describe()}")


def leg_three(count, rng, everything=False):
    section(f"T. sin, cos and tan compiled, with tangent vectors (M2's "
            f"build, wave 4): leg M's written shapes and generated systems "
            f"and {count} of lang_check's sources that call them, one "
            f"vector and two, run on seq.py against the interpreter - "
            f"states, every tangent and FLAGS - with marked lanes replayed "
            f"whole")
    if not LC.have_mpmath():
        skip("T: sin, cos and tan compiled with tangent vectors",
             "python has no mpmath module, which their golden functions and "
             "their routines' generator need (leg M, G and H skip by name "
             "with it)")
        return
    tf, _th = LC.trig()
    t0 = time.perf_counter()
    three_controls()
    texts = [(t, w, None) for t, w in m1_texts(max(1, count // 2),
                                               "tangent three", M2_SHAPES,
                                               _m2_expr)]
    for k in range(count):
        t, direct, comps = LC.g_three(random.Random(f"tangent three {k}"), k,
                                      tangent=True)
        texts.append((t, f"tangent three {k}", (direct, comps, k)))
    wrong, internal, tally = [], [], {}
    held = marked = guess = gtan = demanded = refused = flags = 0
    by_fmt = {f: [0, 0, 0] for f in LC.FORMATS4}      # marked, wrong, tangents
    seen = {"formats": set(), "rounds": set(), "integrators": set(),
            "vectors": set(), "three": set()}
    t_compile = t_run = 0.0
    for text, what, known in texts:
        try:
            g = lang.compile_text(text, what).graph
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            if e.name not in LC.SIX_ARTIFACTS:
                wrong.append(f"{what}: the language refused {e}")
            continue
        used = {op for op in g.op_counts("step") if op in LC.THREE}
        # a generated system of leg M's may draw none of the three; the
        # sources of lang_check's g_three always call one
        if not g.tangent or (known is not None and not used):
            wrong.append(f"{what}: no tangent vector, or none of the three")
        try:
            t1 = time.perf_counter()
            c = cftc.compile_text(text, 5, source=what, stem="t")
            t_compile += time.perf_counter() - t1
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            wrong.append(f"{what}: refused {e.name}: {e.sentence[:100]}")
            continue
        except cftc.InternalError as e:
            internal.append(f"{what}: internal error (exit 70): "
                            f"{str(e)[:120]}")
            continue
        n, T = g.n_state, len(g.tangent)
        if known is not None:
            direct, comps, k = known
            lanes, roles = LC.three_source_lanes(g, rng, direct, comps, k,
                                                 everything, far_wrong=True)
        else:
            lanes = LC.lanes_for(g.fmt, n, rng, 3)
            lanes += LC.special_lanes(g.fmt, n, lanes[0], rng)
            lanes.append([0] * n)
            roles = ["ordinary"] * 3 + ["special"] * 3 + ["zero"]
            far = [b for b, _r in LC.range_lanes(g.fmt)][4:]
            for j in range(n):
                fn = LC.THREE[(len(what) + j) % 3]
                cs = [x for x in LC.trig_centres(fn, g.fmt.name,
                                                 g.round_name) if x[0] != "m"]
                if cs:
                    lane = list(lanes[j % 3])
                    lane[j] = tf.argument(g.fmt, cs[(len(what) + j) % len(cs)])
                    lanes.append(lane)
                    roles.append("structured")
                if far:
                    lane = list(lanes[j % 3])
                    lane[j] = far[(len(what) + j) % len(far)]
                    lanes.append(lane)
                    roles.append("range")
        tans = [[LC.lanes_for(g.fmt, n, rng, 1)[0] for _ in g.tangent]
                for _ in lanes]
        # the three lanes whose tangents are special, on the first lane's
        # state, as leg N has them
        tspec = tangent_specials(g.fmt, n, T, tans[0])
        lanes += [list(lanes[0]) for _ in tspec]
        tans += tspec
        roles += ["special tangent"] * 3
        t1 = time.perf_counter()
        v = LC.rule_compare(c, lanes, 5, tans=tans, tally=False)
        t_run += time.perf_counter() - t1
        flags |= v.ref.flags
        must = [i for i, r in enumerate(roles) if isinstance(r, tuple) and
                LC.trig_demand(r[1], g.fmt, g.round_name, lanes[i][r[3]])]
        lost = [roles[i][1:3] for i in must if i not in v.per[1].marked]
        marked += len(v.marked)
        guess += len(v.wrong)
        gtan += len(v.wrong_tangents)
        demanded += len(must)
        b = by_fmt[g.fmt.name]
        b[0] += len(v.marked)
        b[1] += len(v.wrong)
        b[2] += len(v.wrong_tangents)
        seen["formats"].add(g.fmt.name)
        seen["rounds"].add(g.round_name)
        seen["integrators"].add(g.integrator[0])
        seen["vectors"].add(T)
        seen["three"] |= used
        if v.failing or not v.flags_ok:
            wrong.append(f"{what}: {len(v.failing)} unmarked lanes differ; "
                         f"{v.describe()}")
        elif lost:
            wrong.append(f"{what}: demanded and not marked: {lost[:3]}")
        else:
            held += 1
        if what.endswith("three 0"):
            refused += LC.check_refused_rev7(text, what, wrong, internal, 5,
                                             cover=LC.TCOVER)
    for f in (internal + wrong)[:10]:
        print(f"        {f}")
    fmt_line = ", ".join(f"{f}: {a} marked, {b} wrong, {c} in the tangents"
                         for f, (a, b, c) in by_fmt.items())
    print(f"  outcomes: {dict(sorted(tally.items())) or 'none refused'}; "
          f"compile {t_compile:.1f} s, run under the rule {t_run:.1f} s; "
          f"FLAGS over the {held} systems held: {flags:#x}; {fmt_line}")
    check(not internal, f"no InternalError: {len(texts)} systems that call "
          f"the three with tangent vectors",
          f"{len(internal)} stopped the compiler with an internal error, "
          f"exit 70")
    far_wrong = all(by_fmt[f][1] > 0 and by_fmt[f][2] > 0
                    for f in ("fp128", "fp256"))
    check(not wrong and held >= len(texts) // 2 and far_wrong and
          seen["formats"] == {"fp32", "fp64", "fp128", "fp256"} and
          seen["rounds"] == {"rne", "rtz", "rdn", "rup", "rmm"} and
          seen["integrators"] >= {"rk4", "euler", "stormer-verlet", "map"}
          and seen["vectors"] == {1, 2} and seen["three"] == set(LC.THREE),
          f"T. {held} of {len(texts)} systems holding sin, cos and tan, with "
          f"one tangent vector and with two, at every format, under every "
          f"attribute and under {', '.join(sorted(seen['integrators']))}, "
          f"compiled for sw and run on seq.py at 1, 2 and 5 steps equal to "
          f"the interpreter, states, every tangent and FLAGS, under the "
          f"marked-lane rule: structured centres and lanes past the range in "
          f"the primal ({demanded} demanded marked in the sources whose "
          f"calls are known, every one marked), {marked} lanes marked and "
          f"replayed whole, {guess} guesses wrong in their states and "
          f"{gtan} of them in their tangents too, a nonzero count of both "
          f"at fp128 and at fp256 ({fmt_line}); the first source refused "
          f"`target-feature`, naming FLAG_CONTROL, by revision 7's "
          f"{len(LC.REV7_TARGETS)} targets ({refused}) "
          f"({time.perf_counter() - t0:.1f} s)",
          f"{len(wrong)} otherwise; seen {seen}; {fmt_line}")


# ---- U: atan, asin, acos and atan2 compiled, with tangent vectors (M4's build, wave 5)
#
# Leg M holds the four's rules golden-only; this leg compiles systems that
# call the four - leg M's written shapes (M4_SHAPES), its generated systems
# (_m4_expr, through m1_texts) and lang_check's g_four sources - with one
# tangent vector and two, and runs them on seq.py under the rule, as leg T
# does for the three. Structured centres of the families
# (python/tests/mathlib_inv_family.py) are put in the primal, and atan2's
# tiny-quotient range pairs at every format (a pair below the range's lower
# edge is marked whatever the test says; one in the band at the edge may go
# either way, and one above it is the test's).
#
# NO LANE IS MARKED BY THE TANGENT'S ROUTINE ALONE, as leg T's third control
# shows for cos. That is a reading of the rules, not a measurement of every
# lane: no rule of the four writes a routine node of its own beyond the div
# and sqrt it names (the interpreter's tangent rules, and leg M's
# `math_four`), and div and sqrt never mark. That is a statement about the
# rules; the compiled images are another matter, because the step graph
# gives an unlabelled node one use, so a rule that reads a primal call a
# second time (a product or a quotient of a call by another value does) is
# given the call written again: `next x = atan(y) * x` with a tangent vector
# holds one atan in its primal step and a second in its tangent step. The
# reading is therefore checked on the images, not on lanes: control U0e reads
# the routine nodes of the tangent section of each written shape's image, and
# of the generated systems leg M draws, and requires every routine there to
# be the four, div or sqrt, and every call of the four a copy of a primal
# call - the same operation on the same operand structure, so that it marks
# exactly as the call it copies. That is shown of those images (the count is
# in U0e's line), not of every image the compiler can write.

def four_controls():
    """U0a to U0f, the rule's controls with a tangent vector for the four
    (lang_check's leg O has the rest): each fault planted in a copy of the
    runs and judged by the rule. -> the routine nodes the control images
    hold, for U0e's tally (a set)."""
    iv, ih = LC.inv()
    f64 = FORMATS["fp64"]

    def d(F, q):
        return K.round_once(F, sf.RND_RNE, Fraction(q))[0]

    def tans_of(F, rows):
        return [[[d(F, q) for q in row]] for row in rows]
    # U0a: the study's own case, atan(3 2^-26) under rne at fp64: marked
    c = cftc.compile_text("system te\nformat fp64\nround rne\nstate x\n"
                          "tangent v\nnext x = atan(x)\nstep map\n", 5,
                          source="four controls a", stem="t")
    states = [[iv.tiny_argument(f64, 3, 26)], [d(f64, Fraction(3, 10))],
              [d(f64, Fraction(-7, 10))]]
    fx = LC.Fixture(c, states, 2, tans=tans_of(
        f64, [(Fraction(3, 2),), (Fraction(-5, 4),), (Fraction(1, 3),)]))
    m = c.ir.m
    v = fx.verdict()
    gw = LC.golden_guess("atan", f64, "rne", states[0][0]) != \
        fx.real[1].scratch_out[0]
    LC.check(not v.failing and v.flags_ok and v.per[1].marked == [0] and
             v.first is None and (v.per[1].wrong == [0]) == gw,
             "U0a. atan at fp64 under rne with a tangent vector, "
             "x = 3 2^-26 (INV_FAMILY's own tiny centre: marked), the "
             "guess's value "
             f"{'wrong' if gw else 'right'} against the golden function "
             f"(MEASURED, and the rule's count agrees: {v.per[1].wrong}), "
             "the ordinary lanes bit for bit, FLAGS and STATUS fine",
             v.describe())
    # U0c: a bit flipped in an unmarked lane's tangent is red
    w = fx.verdict(LC.at_step(2, LC.value_edit(2, m, 1, 0)))
    LC.check(w.failing == {2} and "lane-value" in w.broken and w.first == 2
             and "tangents" in " ".join(w.per[2].why) and w.flags_ok,
             "U0c. a bit flipped in an unmarked lane's tangent (lane 2 at 2 "
             "steps) is red there - lane-value, in its tangents",
             w.describe())
    # U0d: the same flip in the marked lane's tangent is replayed, not red
    w = fx.verdict(LC.at_step(1, LC.value_edit(0, m, 1, 0)))
    LC.check(not w.failing and w.flags_ok and 0 in w.per[1].wrong and
             0 in w.per[1].wrong_tangents,
             "U0d. the same flip in the marked lane's tangent (lane 0, 1 "
             "step) is not red: R23's byte is one a lane, so the mark "
             "excuses the lane's tangent as it does its state - the rule "
             "replays the lane whole and counts the guess wrong, in its "
             "tangents", w.describe())
    ops = set(c.ir.op_counts())
    # U0b: an atan2 range lane with a tangent vector, at fp64 and fp32
    for fmt in ("fp64", "fp32"):
        F = FORMATS[fmt]
        c = cftc.compile_text(f"system te\nformat {fmt}\nround rne\n"
                              "state y, x\ntangent v\n"
                              "next y = atan2(y, x)\nnext x = x\n"
                              "step map\n", 5,
                              source=f"four controls b {fmt}", stem="t")
        rng_pairs = LC.four_range_pairs(F)
        pair = rng_pairs[0][0]
        states = [list(pair), [d(F, Fraction(3, 10)), d(F, Fraction(7, 5))],
                  [d(F, Fraction(-7, 10)), d(F, Fraction(2, 3))]]
        fx = LC.Fixture(c, states, 2, tans=tans_of(
            F, [(Fraction(3, 2), Fraction(1, 7)),
                (Fraction(-5, 4), Fraction(2)),
                (Fraction(1, 3), Fraction(-3, 4))]))
        v = fx.verdict()
        demanded = LC.four_demand("atan2", F, "rne", pair)
        LC.check(not v.failing and v.flags_ok and v.per[1].marked == [0] and
                 demanded == "mark" and v.first is None,
                 f"U0b. atan2 at {fmt} under rne with a tangent vector, a "
                 f"pair in the tiny-quotient range ({rng_pairs[0][1]}: "
                 f"marked whatever the test says), the guess "
                 f"{'wrong' if v.per[2].wrong else 'right'} in its state "
                 f"and {'wrong' if v.per[2].wrong_tangents else 'right'} "
                 f"in its tangents at 2 steps (MEASURED), the ordinary "
                 f"lanes bit for bit", v.describe())
        ops |= set(c.ir.op_counts())
    # U0f: a lane of the harness's pin, atan at fp64 under rmm, whose guess
    # is wrong (mathlib_inv_harness.STRUCT_GUESS_WRONG): marked, replayed
    c = cftc.compile_text("system te\nformat fp64\nround rmm\nstate x\n"
                          "tangent v\nnext x = atan(x)\nstep map\n", 5,
                          source="four controls f", stem="t")
    pinned = 0x43349ff16b9c1e3e
    states = [[pinned], [d(f64, Fraction(3, 10))],
              [d(f64, Fraction(-7, 10))]]
    fx = LC.Fixture(c, states, 2, tans=tans_of(
        f64, [(Fraction(3, 2),), (Fraction(-5, 4),), (Fraction(1, 3),)]))
    v = fx.verdict()
    in_pin = pinned in ih.STRUCT_GUESS_WRONG[("atan", "fp64", sf.RND_RMM)]
    LC.check(in_pin and not v.failing and v.flags_ok and
             v.per[1].marked == [0] and v.per[1].wrong == [0] and
             v.first is None,
             "U0f. atan at fp64 under rmm with a tangent vector, the lane "
             "the harness pins wrong (STRUCT_GUESS_WRONG): marked, the "
             "guess wrong in its state against the golden function, "
             "replayed, nothing red; "
             f"in its tangents at 1 step: {v.per[1].wrong_tangents}, at 2 "
             f"steps: {v.per[2].wrong_tangents} (MEASURED)",
             f"{v.describe()}; pinned {in_pin}")
    ops |= set(c.ir.op_counts())
    return ops


ROUTINE_OPS = set(LC.R.ROUTINES)


def _call_key(nodes, j, memo):
    """The structure of node j: its operation and, recursively, its operands'
    structures (a state, parameter or constant by its reference). Two nodes
    with one structure hold one value, bit for bit."""
    if j not in memo:
        op, args, _l = nodes[j]
        memo[j] = (op, tuple(_call_key(nodes, a[1], memo) if a[0] == "n"
                             else tuple(a) for a in args))
    return memo[j]


def four_routines():
    """U0e: the routine nodes the four's tangent images hold. For each of
    leg M's written shapes and the systems it draws (only the four among the
    routines), the tangent section of the image (the nodes after the
    primal's) holds no routine but the four, div and sqrt; and every call of
    the four there is a copy of a primal call - the same operation on the
    same operand structure, a primal subexpression the tangent section
    derives again - so that it marks a lane exactly when that primal call
    does. -> (images compared, copies found, extra routine ops seen,
    findings)."""
    shapes = [(t, f"shape {s}") for s, t in M4_SHAPES.items()]
    texts = shapes + m1_texts(8, "tangent four routines", {}, _m4_expr)
    copies, extra, bad, n = 0, set(), [], 0
    for text, what in texts:
        try:
            ir = cftc.compile_text(text, 5, source=what, stem="t").ir
        except lang.Refusal as e:
            if e.name not in LC.ARTIFACTS | LC.SIX_ARTIFACTS:
                bad.append(f"{what}: refused {e.name}")
            continue
        n += 1
        memo, k0 = {}, ir.primal_step_nodes
        primal = {_call_key(ir.nodes, j, memo) for j in range(k0)
                  if ir.nodes[j][0] in FOUR}
        for j in range(k0, len(ir.nodes)):
            op = ir.nodes[j][0]
            if op in FOUR:
                copies += 1
                if _call_key(ir.nodes, j, memo) not in primal:
                    bad.append(f"{what}: node {j}, a call of {op} in the "
                               f"tangent section, is no primal call")
            elif op in LC.R.ROUTINES:
                extra.add(op)
    return n, copies, extra, bad


def leg_four(count, rng, everything=False):
    section(f"U. atan, asin, acos and atan2 compiled, with tangent vectors "
            f"(M4's build, wave 5): leg M's written shapes and generated "
            f"systems and {count} of lang_check's sources that call them, "
            f"one vector and two, run on seq.py against the interpreter - "
            f"states, every tangent and FLAGS - with marked lanes replayed "
            f"whole")
    if not LC.have_mpmath():
        skip("U: atan, asin, acos and atan2 compiled with tangent vectors",
             "python has no mpmath module, which their golden functions and "
             "their routines' generator need (leg M, G and H skip by name "
             "with it)")
        return
    iv, _ih = LC.inv()
    t0 = time.perf_counter()
    LC.check(LC.FOUR == FOUR, f"U. lang_check's FOUR is this stage's: "
             f"{LC.FOUR} against {FOUR}")
    four_controls()
    n_cmp, copies, extra, bad = four_routines()
    LC.check(not bad and n_cmp >= len(M4_SHAPES) and
             extra <= {"div", "sqrt"} and "div" in extra,
             f"U0e. the tangent sections of {n_cmp} written and generated "
             f"systems' images hold no routine but div and sqrt "
             f"({', '.join(sorted(extra))}) beside {copies} calls of the "
             f"four, each a copy of a primal call - the same operation on "
             f"the same operand structure, so it marks a lane exactly when "
             f"that call does and no lane is marked by the tangent's "
             f"routine alone - a reading of the rules, checked on these "
             f"images", f"{bad[:3]}; extra {sorted(extra)}")
    texts = [(t, w, None) for t, w in m1_texts(max(1, count // 2),
                                               "tangent four", M4_SHAPES,
                                               _m4_expr)]
    for k in range(count):
        t, direct, comps = LC.g_four(random.Random(f"tangent four {k}"), k,
                                     tangent=True)
        texts.append((t, f"tangent four {k}", (direct, comps, k)))
    wrong, internal, tally = [], [], {}
    held = marked = guess = gtan = demanded = refused = flags = 0
    by_fmt = {f: [0, 0, 0] for f in LC.FORMATS4}      # marked, wrong, tangents
    seen = {"formats": set(), "rounds": set(), "integrators": set(),
            "vectors": set(), "four": set()}
    t_compile = t_run = 0.0
    for text, what, known in texts:
        try:
            g = lang.compile_text(text, what).graph
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            if e.name not in LC.SIX_ARTIFACTS:
                wrong.append(f"{what}: the language refused {e}")
            continue
        used = {op for op in g.op_counts("step") if op in FOUR}
        # a generated system of leg M's may draw none of the four; the
        # sources of lang_check's g_four always call one
        if not g.tangent or (known is not None and not used):
            wrong.append(f"{what}: no tangent vector, or none of the four")
        try:
            t1 = time.perf_counter()
            c = cftc.compile_text(text, 5, source=what, stem="t")
            t_compile += time.perf_counter() - t1
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            wrong.append(f"{what}: refused {e.name}: {e.sentence[:100]}")
            continue
        except cftc.InternalError as e:
            internal.append(f"{what}: internal error (exit 70): "
                            f"{str(e)[:120]}")
            continue
        n, T = g.n_state, len(g.tangent)
        if known is not None:
            direct, comps, k = known
            lanes, roles = LC.four_source_lanes(g, rng, direct, comps, k,
                                                everything)
        else:
            lanes = LC.lanes_for(g.fmt, n, rng, 3, (-2, 2))
            lanes += LC.special_lanes(g.fmt, n, lanes[0], rng)
            lanes.append([0] * n)
            roles = ["ordinary"] * 3 + ["special"] * 3 + ["zero"]
            for j in range(n):
                fn = FOUR[(len(what) + j) % 4]
                cs = [] if g.fmt.name == "fp32" else \
                    [x for x in iv.expand(
                        iv.INV_FAMILY[fn][g.fmt.name][g.round_name])
                     if x[0] in ("tiny", "win")]
                ops = [iv.centre_lane(fn, g.fmt, cs[(len(what) + j) %
                                                    len(cs)])] if cs else []
                if fn == "atan2":
                    far = LC.four_range_pairs(g.fmt)
                    ops.append(far[(len(what) + j) % len(far)][0])
                for op in ops:
                    lane = list(lanes[j % 3])
                    if fn == "atan2":
                        if n < 2:
                            continue
                        lane[j], lane[(j + 1) % n] = op
                    else:
                        lane[j] = op
                    lanes.append(lane)
                    roles.append("structured")
        tans = [[LC.lanes_for(g.fmt, n, rng, 1)[0] for _ in g.tangent]
                for _ in lanes]
        # the three lanes whose tangents are special, on the first lane's
        # state, as leg N has them
        tspec = tangent_specials(g.fmt, n, T, tans[0])
        lanes += [list(lanes[0]) for _ in tspec]
        tans += tspec
        roles += ["special tangent"] * 3
        t1 = time.perf_counter()
        v = LC.rule_compare(c, lanes, 5, tans=tans, tally=False)
        t_run += time.perf_counter() - t1
        flags |= v.ref.flags
        must = [i for i, r in enumerate(roles) if isinstance(r, tuple) and
                LC.four_demand(r[1], g.fmt, g.round_name, r[3]) == "mark"]
        lost = [roles[i][1:3] for i in must if i not in v.per[1].marked]
        marked += len(v.marked)
        guess += len(v.wrong)
        gtan += len(v.wrong_tangents)
        demanded += len(must)
        b = by_fmt[g.fmt.name]
        b[0] += len(v.marked)
        b[1] += len(v.wrong)
        b[2] += len(v.wrong_tangents)
        seen["formats"].add(g.fmt.name)
        seen["rounds"].add(g.round_name)
        seen["integrators"].add(g.integrator[0])
        seen["vectors"].add(T)
        seen["four"] |= used
        if v.failing or not v.flags_ok:
            wrong.append(f"{what}: {len(v.failing)} unmarked lanes differ; "
                         f"{v.describe()}")
        elif lost:
            wrong.append(f"{what}: demanded and not marked: {lost[:3]}")
        else:
            held += 1
        if what.endswith("four 0"):
            refused += LC.check_refused_rev7(text, what, wrong, internal, 5,
                                             cover=LC.FOURCOVER)
    for f in (internal + wrong)[:10]:
        print(f"        {f}")
    fmt_line = ", ".join(f"{f}: {a} marked, {b} wrong, {c} in the tangents"
                         for f, (a, b, c) in by_fmt.items())
    print(f"  outcomes: {dict(sorted(tally.items())) or 'none refused'}; "
          f"compile {t_compile:.1f} s, run under the rule {t_run:.1f} s; "
          f"FLAGS over the {held} systems held: {flags:#x}; {fmt_line}")
    check(not internal, f"no InternalError: {len(texts)} systems that call "
          f"the four with tangent vectors",
          f"{len(internal)} stopped the compiler with an internal error, "
          f"exit 70")
    check(not wrong and held >= len(texts) // 2 and
          seen["formats"] == {"fp32", "fp64", "fp128", "fp256"} and
          seen["rounds"] == {"rne", "rtz", "rdn", "rup", "rmm"} and
          seen["integrators"] >= {"rk4", "euler", "stormer-verlet", "map"}
          and seen["vectors"] == {1, 2} and seen["four"] == set(FOUR),
          f"U. {held} of {len(texts)} systems holding atan, asin, acos and "
          f"atan2, with one tangent vector and with two, at every format, "
          f"under every attribute and under "
          f"{', '.join(sorted(seen['integrators']))}, compiled for sw and "
          f"run on seq.py at 1, 2 and 5 steps equal to the interpreter, "
          f"states, every tangent and FLAGS, under the marked-lane rule: "
          f"structured centres and atan2's range pairs in the primal "
          f"({demanded} demanded marked in the sources whose calls are "
          f"known, every one marked), {marked} lanes marked and replayed "
          f"whole, {guess} guesses wrong in their states and {gtan} of them "
          f"in their tangents too ({fmt_line}); the first source refused "
          f"`target-feature`, naming FLAG_CONTROL, by revision 7's "
          f"{len(LC.REV7_TARGETS)} targets ({refused}) "
          f"({time.perf_counter() - t0:.1f} s)",
          f"{len(wrong)} otherwise; seen {seen}; {fmt_line}")


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
    ap.add_argument("--six", type=int, default=12,
                    help="generated systems holding the math library's six, "
                         "compiled and run with tangent vectors in leg N "
                         "(default 12)")
    ap.add_argument("--six-all", action="store_true",
                    help="the larger draw of leg N: every centre of each "
                         "structured family and both neighbours of each in "
                         "the lanes (minutes more; the default is "
                         "gate-sized)")
    ap.add_argument("--three", type=int, default=12,
                    help="generated systems that call sin, cos and tan, "
                         "compiled and run with tangent vectors in leg T "
                         "(default 12; half as many beside leg M's written "
                         "shapes and generated systems)")
    ap.add_argument("--three-all", action="store_true",
                    help="the larger draw of leg T: up to twelve centres of "
                         "each family for each distinct (component, function) "
                         "pair of a source's direct calls, in the lanes of "
                         "lang_check's sources (minutes more; the "
                         "default is gate-sized)")
    ap.add_argument("--four", type=int, default=12,
                    help="generated systems that call atan, asin, acos and "
                         "atan2, compiled and run with tangent vectors in "
                         "leg U (default 12; half as many beside leg M's "
                         "written shapes and generated systems)")
    ap.add_argument("--four-all", action="store_true",
                    help="the larger draw of leg U: up to twelve centres of "
                         "each family for each distinct direct call of a "
                         "source, in the lanes of lang_check's sources "
                         "(minutes more; the default is gate-sized)")
    ap.add_argument("--only", default="",
                    help="a comma list of legs: refs,corpus,derivative,"
                         "lyapunov,certified,libcft,determinism,refusals,"
                         "plants,routines,math,six,three,four")
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
            ("math", lambda: leg_math(a.math, rng("math"))),
            ("six", lambda: leg_six(a.six, rng("six"), a.six_all)),
            ("three", lambda: leg_three(a.three, rng("three"),
                                        a.three_all)),
            ("four", lambda: leg_four(a.four, rng("four"), a.four_all))]
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
