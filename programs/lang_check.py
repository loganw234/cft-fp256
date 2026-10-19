#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The `lang` and `lang-routines` runner stages: the compiler (python/cftc)
held to the language.

    python programs/lang_check.py [--segrun host/cft-segrun[.exe]]
                                  [--audit host/cft-audit[.exe]]
                                  [--corpus N] [--group G,...]
                                  [--only A,B,...]
    python programs/lang_check.py --write     regenerate the committed
                                              compiled references
    python programs/lang_check.py --record    append to cftc's output-version
                                              record what its rules allow

The language's reference interpreter, lang.run, is the definition of
correct (docs/LANGUAGE.md); every image the compiler writes must equal it
on seq.py, bit for bit, FLAGS included. A wrong semantics can hide on one
lane at the final step - the step map is many-to-one at the ulp scale
(L1's finding 1; the 2026-09-25 census) - so every comparison here is on
many lanes and at several step counts: the image's REPEAT patched to 1,
2 and 5 as well as its own count, against the interpreter's checkpoints.

Every comparison is made under the marked-lane rule (M1's build, item 5;
the section "the marked-lane rule" below states it, and tangent_check.py
shares it). The interpreter is run lane by lane, so that each lane's own
flags are known; an image of the math library's six can MARK a lane (bit 7
of R23's byte, STATUS[6]) whose last bit its own test could not decide,
and that lane is replayed - the definition's values and flags stand in for
the image's, whose guess is counted and never required - while every
other lane equals the definition bit for bit, its byte's five flags
included, and FLAGS and STATUS are held to the bytes. An image that
marks no lane is held as it was before the rule, and its per-lane bytes
besides.

  A  the corpus: the three references at fp32, fp64, fp128 and fp256 and
     Lorenz-63 and Henon-Heiles under every attribute, then systems a
     seeded generator writes as .cftl text - every built-in, arrays
     cyclic and not, lets, params, lane params, every integrator, maps
     with and without h, and the shapes the lowering must get right
     (sharing, the fold, spills, swaps and rotations, leaf outputs, an
     empty step) - at every format L1 takes them; each with lanes that
     overflow, hold a signalling NaN and hold subnormals
  B  the references against gen_odes.py's images: the compiled banks the
     classic banks byte for byte at fp64 and fp256, the hand-written
     image on its classic bank equal to the compiled one on its own and
     to the interpreter, and the costs side by side, pinned
  C  the halved bank against lang.run at h/2; every param's slot at a
     random value against lang.run on those encodings; values past
     Python's 4,300-digit limit (a const of 1e-5000 and an h of 1e-4400
     at fp256, a param's and a lane param's 5,000-digit defaults, a
     5,000-digit run value), compiled, their exact values read back from
     the manifest, and run against lang.run
  D  resume: one segment of 2S equals two of S
  E  libcft's software backend: cft-segrun certifies each compiled
     reference (a main run, a half-step run on the halved bank, a
     step-halving estimate) - Kepler's, whose image holds routines, among
     them (C4); the golden reader, the golden audit and cft-audit accept
     each, in full and sampled; and version 1's wider run refused for an
     image holding a routine (C4): cft-segrun refuses to write a wider
     run of Kepler's image, `aux-image` (exit 5, nothing made), and
     cft-audit refuses the certificate the instrument
     CFT_SEGRUN_PLANT=wider-routine makes of it, `aux-image` at run 1;
     the same construction on Lorenz-63, which holds none, is written and
     accepted, so the rule alone refuses (the golden half is certificate
     version 2's parcel's)
  F  determinism: two processes under two PYTHONHASHSEEDs write the same
     bytes, and the committed compiled references are those bytes; and
     cftc's VERSION as an output version (C4): the record,
     programs/systems/cftc-outputs.txt, ends with VERSION's block, which
     names every committed compiled file - compiled/ and compiled-tangent/
     - with its digest and nothing else, so a compiler change that moves
     a committed byte fails here until VERSION is bumped (python/cftc/
     outputs.py); the record's check caught on five plants in memory
  G  every refusal of the compiler's, by name, and the language's
     bank-capacity, which it raises for its routines' words (C4); and the
     eighth since M1's build, item 4, `routine-unavailable`, a run-time
     call of the six with mpmath taken out of sys.modules (simulated), on
     revision 7's single before target-feature; the two sources the
     interim `math-library` refused here until item 4 - log1p at run time
     and a fold of exp2 alone - each compiled (the run-time one, and its
     run by lang.run, skipped by name on a host without mpmath, which the
     six's golden functions and routines need; the fold compiles there)
  H  plants in a copy of the package: each stopped by the internal check,
     and with the check off each red on seq.py, its failing lanes counted;
     with the routines' (C4): a raise dropped, a raise inside its quiet
     region, a region dropped, a routine reading another word; and the
     call loop's (C4), its constant lowered in the copy: the index not
     stepped past a record, a call's raise dropped, a loop a call short
  I  the core legs' coverage, every tally nonzero: every operation the
     compiler carries as one instruction, every attribute, format and
     integrator, the lowering's shapes, the four flags (I2 is the
     routines')
  J  every source the language accepts reads back (D2): maps reading h at
     random - forms that scale with h, that fold away, that are
     nonlinear - chains at the parser's 100 - negations used as
     multiplicands, nested calls under every integrator, an unnamed
     product's and a min chain's tangent, a compound constant - and chains
     of lets past where Python's recursion limit once stopped them, with
     and without a tangent, and a cycle of them; each compiled, its
     canonical form read back, or refused by the name its source decides;
     never an InternalError. No class of these reached a generator above,
     and each stopped the compiler at exit 70 until D2's rules.
  K  run-time division and square root (L4), inlined as routines (C4):
     every flag of both through the interpreter at every format; Kepler's
     reference (kepler-sv) at every format and under every attribute
     against the interpreter, its costs pinned; and generated sources the
     language accepts that divide or take a root - in equations and lets,
     with and without tangent vectors, under every integrator, format and
     attribute - each read back through its canonical form, compiled for
     the software targets (one image for sw, sw:4096 and sw:32768) and
     run on seq.py against the interpreter at 1, 2 and 5 steps, states,
     tangents and FLAGS, on lanes that overflow, hold a signalling NaN,
     hold subnormals and hold zeros; each refused `target-feature`,
     naming FLAG_CONTROL, on revision 7's targets and through the command
     line (exit 3, never 70); each one's canonical form with its
     written-out step and its tangent lines moved above its equations
     compiling to the same image
  K2 the routines on their full pools: each of the 40 fragments
     (cft_golden/routines.py: division and root, four formats, five
     attributes) run as a program on seq.py against softfloat, its bits and
     each lane's own flag word, over test_divfull's pools whole
  L  the call loop (C4, python/cftc/callloop.py): planar N bodies under rk4
     at N = 8, whose step with its 224 routines inlined passes the
     constant, 32,768 - compiled with its largest batch looped alone, as
     the rule says, inside sw's 256 slots, and run on seq.py against the
     interpreter at 1 and 2 steps, states and FLAGS, on lanes that
     overflow, hold a signalling NaN, hold subnormals and hold zeros; and
     Kepler under rk4 at fp64 and fp256 with the constant lowered, every
     batch looped and the largest alone, at 1, 2 and 5 steps - the fp64
     image with every batch looped certified through cft-segrun on
     libcft's software backend (a main run and a half-step run) and
     accepted by the golden reader, the golden audit and cft-audit, in
     full and sampled. Leg H holds three plants of the loop's own

  I2 the routines' coverage: each of div and sqrt compiled and run at
     every format and under every attribute and integrator, the five
     flags raised by those runs, and call loops run of both; and, since
     M1's build, item 5, the same for each of the math library's six -
     every format, attribute and integrator, the five flags, the marks
     seen and replayed (at fp64, fp128 and fp256 for the four with a
     structured family), the call loops of the six, the refusals on
     revision 7
  O  the marked-lane rule's controls (M1's build, item 5): the golden
     corpus's markstep, a hand-written image that marks lanes on purpose
     (certificates/programs/markstep-fp64.cfta; no mpmath), run as it is
     and with a fault planted in a copy of its runs - a bit of an
     unmarked lane's value or byte, a flag, STATUS[6] against the bytes,
     FLAGS against the bytes, a mark lost between checkpoints, a marked
     lane's guess wrong in its value or its flags - each required to fail
     the check it breaks and no other, and the guesses to pass
  N  the math library's six, compiled and run (M1's build, item 5; needs
     mpmath, else skipped by name): (N1) each alone, at every format and
     attribute, each integrator among the twenty, on ordinary, special,
     edge and structured-family arguments - the families' centres
     (python/tests/mathlib_family.py), the anchors whose guess is wrong
     among them, every lane the theory demands marked, marked - equal to
     the interpreter under the rule, and refused `target-feature` on
     revision 7's four targets; (N2) generated sources that call them
     beside division, the root and the other operations, in equations and
     lets, with and without tangent vectors, under every integrator,
     format and attribute, compiled for the software targets, refused on
     revision 7's and through the command line, run at 1, 2 and 5 steps
     with structured arguments in the components the calls read; (N3) the
     call loop over batches of the six, the constant lowered as leg L
     lowers it

The legs come in two groups, each with its tally (GROUPS, below): core,
legs A to H and J with I its tally, which is the `lang` stage, in the
quick budget; and routines, legs K, K2, L, O and N with I2 its tally, the
`lang-routines` stage, in the gate budget (verify/run.sh). `--group`
runs a group; with no selection both run. `--six N` is the number of
generated sources in leg N2, and `--six-all` the larger draw of N1 and N2
(every centre of each family, both neighbours, twelve ordinary lanes, every
edge), minutes more than the gate-sized default. A tally runs when every leg
of its group ran; where `--only` ran part of a group, its tally is a
SKIP line.

A check skipped prints a line that starts with SKIP, which the runner
counts and names on its VERDICT line.
"""

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import cftc                                               # noqa: E402
from cftc import outputs as O                             # noqa: E402
from cftc import targets as TG                            # noqa: E402
from cft_golden import routines as R                      # noqa: E402
from cftc.schedule import cycles                          # noqa: E402
from cftc.regalloc import Ins                             # noqa: E402
from cft_golden import FORMATS, asm, cert, lang, seq      # noqa: E402
from cft_golden import softfloat as sf                    # noqa: E402
from cft_golden.lang import constants as K                # noqa: E402

SYSTEMS = ROOT / "programs" / "systems"
COMPILED = SYSTEMS / "compiled"
PROGRAMS = ROOT / "programs"
REFS = {"lorenz63-rk4": 100, "lorenz96-rk4": 20, "henonheiles-lf": 100}
REF_LANES = {"lorenz63-rk4": 32, "lorenz96-rk4": 6, "henonheiles-lf": 32}
BOX = {"lorenz63-rk4": [(-20, 20), (-25, 25), (5, 45)],
       "henonheiles-lf": [(-0.4, 0.4)] * 4,
       "lorenz96-rk4": None}
CHECKPOINTS = (1, 2, 5)

# The costs the compiler measured on the references (section 4 of the
# design, L2.md), pinned so that a change that costs more is seen. Each
# row: image instructions, ALU a step, loads and stores a step, registers,
# scratch slots a lane, bank slots.
PINNED = {
    "lorenz63-rk4": (62, 53, 0, 0, 12, 3, 7),
    "lorenz96-rk4": (873, 760, 60, 50, 29, 48, 5),
    "henonheiles-lf": (23, 12, 0, 0, 9, 4, 5),
}
# The reference that divides and takes a root at run time (C4): Kepler's
# problem under Stormer-Verlet, three routines a step. No gen_odes.py image
# or classic bank stands beside it, so leg K holds it (every format, every
# attribute, its costs pinned), leg E certifies it and leg F commits it.
ROUTINE_REFS = {"kepler-sv": 10}
ROUTINE_REF_LANES = {"kepler-sv": 12}
BOX["kepler-sv"] = [(-2, 2), (-2, 2), (-1, 1), (-1, 1)]
PINNED["kepler-sv"] = (545, 525, 0, 0, 29, 4, 40)


# ---- reporting ---------------------------------------------------------

class _Tally:
    ok = bad = skip = 0


TALLY = _Tally()
FAILURES = []


def ok(what):
    TALLY.ok += 1
    print(f"  ok    {what}", flush=True)


def bad(what):
    TALLY.bad += 1
    FAILURES.append(what)
    print(f"  FAIL  {what}", flush=True)


def check(cond, what, why=""):
    if cond:
        ok(what)
    else:
        bad(f"{what}" + (f": {why}" if why else ""))
    return cond


def skip(what, why):
    TALLY.skip += 1
    print(f"SKIP  {what}: {why}", flush=True)


def have_mpmath():
    """Whether mpmath can be imported here, without importing it: only the
    math library's six need it (their golden functions, python/cft_golden/
    transcend.py, and their routines' generator, mathlib.py), so only a
    check that runs or compiles them skips by name without it. A host
    where sys.modules holds None for it has none."""
    return importlib.util.find_spec("mpmath") is not None


_ABSENT = object()      # a module sys.modules did not hold (leg G)


def section(title):
    print(f"\n== {title}", flush=True)


# ---- lanes ---------------------------------------------------------------

def full_value(fmt, rng, lo, hi):
    """A value in [lo, hi] with twice the format's precision, rounded once:
    a full significand, so that no product is exact by accident."""
    num = rng.randrange(1 << (2 * fmt.prec))
    v = Fraction(lo) + (Fraction(hi) - Fraction(lo)) * \
        Fraction(num, 1 << (2 * fmt.prec))
    return K.round_once(fmt, sf.RND_RNE, v)[0] if v else 0


def lanes_for(fmt, n, rng, count, box=None):
    out = []
    for _ in range(count):
        row = []
        for comp in range(n):
            lo, hi = (box[comp] if isinstance(box, list) else
                      (box or (-3, 3)))
            row.append(full_value(fmt, rng, lo, hi))
        out.append(row)
    return out


def special_lanes(fmt, n, base, rng):
    """Three lanes, each there to raise something: one that overflows,
    one holding a signalling NaN, one holding subnormals."""
    huge = sf.round_pack(fmt, 0, 1, fmt.emax // 2 + 10)[0]
    over = list(base)
    over[0] = huge
    if n > 1:
        over[1] = huge
    snan = list(base)
    snan[0] = sf.snan_bits(fmt, 1)
    sub = [sf.min_subnormal_bits(fmt)] + \
        [rng.randrange(1, 1 << fmt.man_w) for _ in range(n - 1)]
    return [over, snan, sub]


# ---- running an image ------------------------------------------------------

def image_at(image, steps):
    """The image with its segment's REPEAT - its first - counting `steps`,
    every other word the same, as programs/check.py's _patch_trip makes a
    run of another length. A call loop's REPEATs (C4) are inside the step
    and keep their counts."""
    img = asm.Image.from_bytes(image)
    words = list(img.insns)
    for k, w in enumerate(words):
        d = asm.decode(w)
        if d["ctrl"] and d["op"] == asm.REPEAT:
            words[k] = asm.repeat(steps)
            break
    return asm.Image(img.fmt, words, img.consts, img.max_deposits, img.flags,
                     scratch_depth=img.scratch_depth,
                     scratch_io=img.scratch_io).to_bytes()


def run_image(image, c, states, lane_params=None, bank=None, depth=None,
              block=None):
    d = depth or c.depth
    prog = seq.Program.from_bytes(image, scratch_depth=d)
    n = len(states)
    vals = c.lowered.bank_values() if bank is None else list(bank)
    sin = block if block is not None else c.scratch_block(states,
                                                          lane_params)
    return seq.run(prog, [0] * n, [0] * n, [0] * n, bank=vals,
                   scratch_in=sin, scratch_depth=d)


# ---- the marked-lane rule (M1's build, item 5) ------------------------------------
#
# A routine of the math library's six marks a lane whose last bit its own
# test could not decide (R24's raise with bit 7: the lane's byte in R23's
# block carries [7], and STATUS[6] is set). The image's value in that lane is
# a GUESS, and the definition - lang.run - decides it: the lane is REPLAYED
# by lang.run of that lane alone, over the same steps from the same start,
# as python/cft_golden/cert2.py's replay_segment replays a certified
# segment's marked lanes (docs/LANGUAGE.md, "A marked lane"). Every
# comparison of an image with lang.run, in this file and in tangent_check.py,
# is this one: compare(), compare_routine() and the tangent stage's compare()
# call rule_compare(), which runs the image on seq.py at each checkpoint and
# hands the run to judge().
#
# THE RULE, at every checkpoint (1, 2, 5 and the image's own steps):
#   R1  an unmarked lane equals the definition bit for bit: its state, its
#       tangents and its lane params;
#   R2  an unmarked lane's byte is exactly the definition's flags for that
#       lane: [4:0] the lane's own five, [7:5] clear;
#   R3  a marked lane is replayed: the definition's values and flags stand in
#       for its own. Its guess is compared as a guess - counted, and
#       reported when it is wrong in its values or in its flags - and never
#       required. A marked lane's byte may carry [4:0] and the mark, and
#       nothing in [6:5];
#   R4  the run's FLAGS after the replay - the OR of the corrected bytes'
#       [4:0], a marked lane's the definition's - equal lang.run's FLAGS;
#   R5  STATUS is zero but for STATUS[6];
#   R6  STATUS[6] is set exactly when some lane's byte is marked;
#   R7  the block is the run's own: FLAGS, as the run reports it, is the OR of
#       the raw bytes' [4:0] (seq.py's statement of R23, as the model's
#       docstring makes it);
#   R8  a mark is never lost between checkpoints: a lane marked at one is
#       marked at every later one.
# For an image that marks no lane the rule is the one before it - states,
# tangents, lane params, FLAGS and STATUS equal the interpreter's - and the
# per-lane bytes of R2 beside it: what the lockstep run could not show, since
# it gave the OR of the lanes' FLAGS and no lane's own.
#
# A LANE MARKED AT ONE CHECKPOINT AND THE NEXT. Each checkpoint is its own
# run of the image from the initial states, the image's REPEAT patched to the
# checkpoint's steps (image_at), judged against the definition of that many
# steps from the same initial states: nothing is carried from one checkpoint's
# replay to the next, as cert2 carries a segment's corrected end state into
# the next segment's start - there is no chain here, and each checkpoint is
# one segment whose start is the initial state. That is the definition's own
# rule: a lane's value after s steps is lang.run of that lane for s steps, a
# function of its initial state alone. The runs are one deterministic
# computation of which each shorter is the prefix, so a lane marked at s is
# marked at every later checkpoint (R8) and its replay at the later one is the
# definition again from the initial state, never the earlier replay's end; a
# lane marked only at the later one (its mark came after step s) is judged
# unmarked, bit for bit, at s.

LANE_IEEE = seq.LANE_FLAGS_IEEE                 # R23's byte: [4:0] the five flags
LANE_AUX = seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_SCRATCH_RANGE      # [6:5]
LANE_MARKED = seq.LANE_MARKED                   # [7]
STATUS_MARKED = seq.STATUS_MARKED               # STATUS[6]

# The checks a verdict names: lane-value and lane-byte (R1, R2) fail a lane,
# and these fail the run's FLAGS and STATUS part (flags_ok): flags-replayed
# (R4), status-other (R5, and a marked lane's byte carrying [6:5]),
# status-mark (R6), flags-word (R7), marks-vanish (R8), and block-length, a
# run whose block is not a byte a lane.
RULE_RUN = ("flags-word", "flags-replayed", "status-other", "status-mark",
            "marks-vanish", "block-length")


class Ref:
    """The definition, lane by lane: lang.run of each lane ALONE, which is
    the lane as it is in the lockstep run (the interpreter's lanes are
    independent, docs/LANGUAGE.md), through every checkpoint. It answers what
    a lang.run Run answers (.states, .flags, .at, .tangents, .at_tangents,
    .primal_flags), and what a Run cannot: each lane's own FLAGS, which R2
    holds a lane's byte to. A marked lane's replay is this: its values and
    flags at the checkpoint, from the initial state."""

    def __init__(self, graph, states, top, marks, lane_params=None,
                 tangents=None, interp=None):
        self.top, self.marks = top, tuple(marks)
        at = tuple(s for s in marks if s != top)
        self.lanes = [lang.run(
            graph, [st], top, at=at,
            lane_params=None if lane_params is None else [lane_params[k]],
            tangents=None if tangents is None else [tangents[k]],
            **(interp or {})) for k, st in enumerate(states)]

    def _lane(self, s, k):
        r = self.lanes[k]
        if s == self.top:
            return r.states[0], r.flags, (r.tangents[0] if r.tangents
                                          else None)
        (sts, fl) = r.at[s]
        return sts[0], fl, (r.at_tangents[s][0] if r.at_tangents else None)

    def lane_flags(self, s, k):
        """Lane k's own flags through s steps: lang.run of it alone."""
        return self._lane(s, k)[1]

    def vector(self, s, k, lane_params):
        """What the image's lane k must hold after s steps: the state, the
        tangent vectors in order, the lane params."""
        st, _fl, tv = self._lane(s, k)
        return list(st) + [v for vec in (tv or ()) for v in vec] \
            + list(lane_params)

    def flags_at(self, s):
        """lang.run's FLAGS through s steps: the OR of the lanes'."""
        out = 0
        for k in range(len(self.lanes)):
            out |= self.lane_flags(s, k)
        return out

    @property
    def states(self):
        return [r.states[0] for r in self.lanes]

    @property
    def flags(self):
        return self.flags_at(self.top)

    @property
    def primal_flags(self):
        out = 0
        for r in self.lanes:
            out |= r.primal_flags
        return out

    @property
    def tangents(self):
        return [r.tangents[0] for r in self.lanes] if self.lanes and \
            self.lanes[0].tangents is not None else None

    @property
    def at(self):
        return {s: ([self._lane(s, k)[0] for k in range(len(self.lanes))],
                    self.flags_at(s)) for s in self.marks if s != self.top}

    @property
    def at_tangents(self):
        if not self.lanes or self.lanes[0].tangents is None:
            return {}
        return {s: [self._lane(s, k)[2] for k in range(len(self.lanes))]
                for s in self.marks if s != self.top}


class Checkpoint:
    """One checkpoint's verdict (judge): the unmarked lanes that differ, the
    lanes replayed with the guesses that were wrong, and the names of the
    rule's checks that failed."""

    def __init__(self):
        self.failing = set()
        self.marked = []            # lanes whose byte carries the mark
        self.wrong = []             # of them, guessed values that differ
        self.wrong_tangents = []    # of those, the tangents among them
        self.wrong_flags = []       # of them, a guessed byte that differs
        self.broken = set()
        self.why = []

    @property
    def flags_ok(self):
        return not self.broken & set(RULE_RUN)

    def fail(self, name, why):
        self.broken.add(name)
        if len(self.why) < 4:
            self.why.append(f"{name}: {why}")


def judge(outs, wants, got_bytes, got_flags, got_status, want_lane_flags,
          want_flags, before=None, spans=(("values", 0, None),)):
    """The rule (above) on one run. `outs` and `wants` are each lane's
    values as the image left them and as the definition has them, `spans`
    the parts of a lane they hold ((name, from, to): its states, its
    tangents, its lane params); `got_*` the run's block, FLAGS and STATUS;
    `want_lane_flags` each lane's own flags by the definition and
    `want_flags` their OR; `before` the lanes marked at the previous
    checkpoint, if there was one. -> a Checkpoint."""
    cp = Checkpoint()
    n = len(outs)
    if len(got_bytes) != n:
        cp.fail("block-length", f"{len(got_bytes)} bytes for {n} lanes")
        return cp
    raw = corrected = 0
    for k in range(n):
        b = got_bytes[k]
        raw |= b & LANE_IEEE
        differ = [name for name, lo, hi in spans
                  if outs[k][lo:hi] != wants[k][lo:hi]]
        if b & LANE_MARKED:
            # R3: replayed, the guess counted and never required
            cp.marked.append(k)
            if differ:
                cp.wrong.append(k)
                if "tangents" in differ:
                    cp.wrong_tangents.append(k)
            if b & LANE_IEEE != want_lane_flags[k]:
                cp.wrong_flags.append(k)
            if b & LANE_AUX:
                cp.fail("status-other", f"marked lane {k}'s byte {b:#04x} "
                        f"carries [6:5]")
            corrected |= want_lane_flags[k]
        else:
            # R1, R2: bit for bit, values and byte
            if differ:
                cp.failing.add(k)
                cp.fail("lane-value", f"lane {k}'s {' and '.join(differ)} "
                        f"differ from the definition's")
            if b != want_lane_flags[k]:
                cp.failing.add(k)
                cp.fail("lane-byte", f"lane {k}'s byte is {b:#04x}, the "
                        f"definition's flags {want_lane_flags[k]:#04x}")
            corrected |= b & LANE_IEEE
    if corrected != want_flags:                                     # R4
        cp.fail("flags-replayed", f"FLAGS after the replay {corrected:#04x}, "
                f"lang.run's {want_flags:#04x}")
    if got_status & ~STATUS_MARKED:                                 # R5
        cp.fail("status-other", f"STATUS {got_status:#04x}")
    if bool(got_status & STATUS_MARKED) != bool(cp.marked):         # R6
        cp.fail("status-mark", f"STATUS {got_status:#04x} with "
                f"{len(cp.marked)} lanes marked")
    if got_flags != raw:                                            # R7
        cp.fail("flags-word", f"FLAGS {got_flags:#04x}, the bytes' OR "
                f"{raw:#04x}")
    if before is not None and not set(before) <= set(cp.marked):    # R8
        cp.fail("marks-vanish", f"lanes {sorted(set(before) - set(cp.marked))}"
                f" were marked at the checkpoint before")
    return cp


class Verdict:
    """rule_compare's answer: the rule over every checkpoint of a run."""

    def __init__(self, ref):
        self.ref = ref
        self.per = {}
        self.failing = set()
        self.first = None
        self.flags_ok = True
        self.broken = set()

    def add(self, s, cp):
        self.per[s] = cp
        self.failing |= cp.failing
        self.broken |= cp.broken
        if cp.failing or not cp.flags_ok:
            self.first = s if self.first is None else self.first
        self.flags_ok = self.flags_ok and cp.flags_ok

    @property
    def top(self):
        return self.per[self.ref.top]

    def _union(self, attr):
        return sorted({k for cp in self.per.values()
                       for k in getattr(cp, attr)})

    @property
    def marked(self):
        """The lanes marked at any checkpoint (R8 makes the last
        checkpoint's the same)."""
        return self._union("marked")

    @property
    def wrong(self):
        """The lanes whose guess was wrong in its values at any checkpoint:
        a later step can absorb a wrong last bit, which was wrong all the
        same."""
        return self._union("wrong")

    @property
    def wrong_tangents(self):
        return self._union("wrong_tangents")

    @property
    def wrong_flags(self):
        return self._union("wrong_flags")

    def describe(self):
        """What failed, for a check's message: the names, and the first
        sentences of the first checkpoint that failed."""
        if self.first is None:
            return "none"
        cp = self.per[self.first]
        return (f"{', '.join(sorted(self.broken))}; at {self.first} steps: "
                + "; ".join(cp.why))


# the stage's tally of what the rule saw, every comparison counted once a lane
# over its checkpoints: lanes judged, lanes marked (and so replayed), the
# guesses that were wrong in their values and in their flags at any
# checkpoint; by a leg's tag too
MARKS = {"comparisons": 0, "lanes": 0, "marked": 0, "wrong": 0,
         "wrong_tangents": 0, "wrong_flags": 0, "by_tag": {}}


def note_marks(v, tag=None):
    for d in [MARKS] + ([MARKS["by_tag"].setdefault(
            tag, {"comparisons": 0, "lanes": 0, "marked": 0, "wrong": 0,
                  "wrong_tangents": 0, "wrong_flags": 0})] if tag else []):
        d["comparisons"] += 1
        d["lanes"] += len(v.ref.lanes)
        d["marked"] += len(v.marked)
        d["wrong"] += len(v.wrong)
        d["wrong_tangents"] += len(v.wrong_tangents)
        d["wrong_flags"] += len(v.wrong_flags)


def checkpoints(top):
    """The steps an image is run for: CHECKPOINTS below `top`, and `top`."""
    return sorted({s for s in CHECKPOINTS if s < top} | {top})


def rule_compare(c, states, top, *, lane_params=None, tans=None, bank=None,
                 interp=None, width=None, runner=None, ref=None, tag=None,
                 tally=True):
    """seq.py on the image at 1, 2, 5 and `top` steps, judged by the rule
    against lang.run's definition of every lane. `tans` are the tangent
    vectors of a system that carries them (lang.run's), `width` how much of
    each lane the comparison reads (all of it: states, tangents, lane
    params; a routine's legs read states and tangents), `runner(s)` a
    stand-in for the run (the rule's controls plant their faults in it),
    `ref` a definition already made, `tag` the leg's name for the tally and
    `tally` false for a control, which is not the stage's own evidence.
    -> a Verdict."""
    marks = checkpoints(top)
    if ref is None:
        ref = Ref(c.graph, states, top, marks, lane_params, tans, interp)
    g = c.ir
    m = g.m
    w = m if width is None else width
    lp = lane_params
    if lp is None:
        lp = [[b for _n, _d, b in g.lane] for _ in states]
    block = c.scratch_block(states, lane_params, tans)
    if runner is None:
        def runner(s):
            return run_image(image_at(c.image, s), c, states, lane_params,
                             bank, block=block)
    # a lane's parts, as far as the comparison reads them
    spans = [(name, lo, min(hi, w)) for name, lo, hi in
             (("states", 0, g.n_primal), ("tangents", g.n_primal, g.n_state),
              ("lane params", g.n_state, m)) if lo < min(hi, w)]
    v = Verdict(ref)
    before = None
    for s in marks:
        r = runner(s)
        cp = judge([r.scratch_out[k * m:k * m + w]
                    for k in range(len(states))],
                   [ref.vector(s, k, lp[k])[:w] for k in range(len(states))],
                   r.lane_flags, r.flags, r.status,
                   [ref.lane_flags(s, k) for k in range(len(states))],
                   ref.flags_at(s), before, spans)
        v.add(s, cp)
        before = cp.marked
    if tally:
        note_marks(v, tag)
    return v


def compare(c, states, lane_params, top, bank=None, interp=None):
    """seq.py on the image at 1, 2, 5 and `top` steps against lang.run's
    checkpoints, under the marked-lane rule above. -> (failing lanes, first
    step a lane or FLAGS parts, flags equal everywhere, the definition)."""
    v = rule_compare(c, states, top, lane_params=lane_params, bank=bank,
                     interp=interp)
    return v.failing, v.first, v.flags_ok, v.ref


# ---- the generator ------------------------------------------------------

LITS = ["1", "2", "3", "0.5", "0.25", "1.5", "(1/3)", "(2/7)", "0.1", "7",
        "0x1.8p+1", "2.5e-1"]
CMPS = ["<", "<=", ">", ">=", "=="]
FNS2 = ["copysign", "min", "max", "minnum", "maxnum"]


def g_expr(rng, ops, depth):
    if depth <= 0 or rng.random() < 0.3:
        if ops and rng.random() < 0.85:
            return rng.choice(ops)
        return rng.choice(LITS[:6])
    kind = rng.choice(["+", "-", "*", "neg", "fma", "abs", "fn2", "cmp",
                       "select", "const", "fold", "dup"])

    def sub():
        return g_expr(rng, ops, depth - 1)
    if kind in ("+", "-", "*"):
        return f"({sub()} {kind} {sub()})"
    if kind == "neg":
        return f"-({sub()})"
    if kind == "fma":
        return f"fma({sub()}, {sub()}, {sub()})"
    if kind == "abs":
        return f"abs({sub()})"
    if kind == "fn2":
        return f"{rng.choice(FNS2)}({sub()}, {sub()})"
    if kind == "cmp":
        return f"({sub()} {rng.choice(CMPS)} {sub()})"
    if kind == "select":
        return f"select({sub()}, {sub()}, {sub()})"
    if kind == "fold":                    # a neg beside a constant
        return f"({rng.choice(LITS)} * -({sub()}))"
    if kind == "dup":                     # sharing: one expression twice
        e = sub()
        return f"(({e}) * ({e}))"
    return f"({rng.choice(LITS)} {rng.choice(['+', '-', '*', '/'])} " \
           f"{rng.choice(LITS)})"


def g_system(rng, k):
    """(text, shape) - a random system the language takes, or one L1
    refuses for a reason a random source may meet (counted, not run)."""
    shape = rng.choice(["rk4", "euler", "sv", "map", "maph", "rk4", "map",
                        "pressure", "permute", "ranges"])
    fmt = rng.choice(["fp32", "fp64", "fp128", "fp256"])
    rnd = rng.choice(["rne", "rne", "rtz", "rdn", "rup", "rmm"])
    lines = [f"system g{k}", f"format {fmt}", f"round {rnd}"]
    params = [f"p{i}" for i in range(rng.randint(0, 2))]
    lanes = [f"l{i}" for i in range(rng.randint(0, 2))]
    consts = [f"c{i}" for i in range(rng.randint(0, 2))]
    if params:
        lines.append("param " + ", ".join(f"{p} = {rng.choice(LITS)}"
                                          for p in params))
    for ln in lanes:
        lines.append(f"lane param {ln}" + (f" = {rng.choice(LITS)}"
                                           if rng.random() < 0.5 else ""))
    for cn in consts:
        lines.append(f"const {cn} = {rng.choice(LITS)} * {rng.choice(LITS)}")
    extra = params + consts + lanes
    h = rng.choice(["1/8", "0.01", "1/3", "0x1p-4"])
    if shape == "pressure":
        n = rng.randint(28, 44)
        lines.append(f"state a[{n}] cyclic")
        ops = ["a[i+1]", "a[i-1]", "a[i-2]", "a[i+2]", "a[i]"] + extra
        body = g_expr(rng, ops, 2)
        lines.append(f"d/dt a[i] = fma(a[i+1] - a[i-2], a[i-1], -a[i]) + "
                     f"{body}" + "".join(f" + {e}" for e in extra))
        lines.append(f"step {rng.choice(['rk4', 'euler'])}, h = {h}")
        return "\n".join(lines) + "\n", shape
    if shape == "permute":
        n = rng.randint(2, 5)
        lines.append(f"state a[{n}] cyclic, x, y")
        rot = rng.choice(["a[i+1]", "a[i-1]", "a[i]"])
        lines.append(f"next a[i] = {rot}")
        leaves = ["y"] + params + lanes
        lines.append(f"next x = {rng.choice(leaves)}")
        lines.append(f"next y = {g_expr(rng, ['x', 'y', 'a[0]'], 2)}"
                     + "".join(f" + {e}" for e in extra))
        lines.append("step map")
        return "\n".join(lines) + "\n", shape
    if shape == "sv":
        nq = rng.randint(1, 3)
        qs = [f"q{i}" for i in range(nq)]
        ms = [f"m{i}" for i in range(nq)]
        lines.append("state " + ", ".join(qs + ms))
        eqs = [f"d/dt {q} = {g_expr(rng, ms + extra, 2)}" for q in qs]
        eqs += [f"d/dt {m} = {g_expr(rng, qs + extra, 3)}" for m in ms]
        if extra:
            eqs[0] += " + " + " + ".join(extra)
        lines += eqs
        lines.append(f"step stormer-verlet, h = {h}, q = ({', '.join(qs)}),"
                     f" p = ({', '.join(ms)})")
        return "\n".join(lines) + "\n", shape
    integ = {"rk4": "rk4", "euler": "euler", "map": "map", "maph": "maph",
             "ranges": "rk4"}[shape]
    scal = [f"s{i}" for i in range(rng.randint(1, 3))]
    arr = None
    if rng.random() < 0.5 or shape == "ranges":
        arr = (rng.randint(3, 6), shape != "ranges" and rng.random() < 0.6)
    decl = scal + ([f"a[{arr[0]}]" + (" cyclic" if arr[1] else "")]
                   if arr else [])
    lines.append("state " + ", ".join(decl))
    word = "next" if integ.startswith("map") else "d/dt"
    operands = scal + extra + (["h", "(h/2)"] if integ == "maph" else [])
    lets = [f"r{i}" for i in range(rng.randint(0, 2))]
    for i, r in enumerate(lets):
        lines.append(f"let {r} = {g_expr(rng, operands + lets[:i], 2)}")
    eqs = []
    for s in scal:
        tail = ["a[0]"] if arr else []
        eqs.append(f"{word} {s} = {g_expr(rng, operands + lets + tail, 3)}")
    if arr:
        if arr[1]:
            near = ["a[i]", "a[i+1]", "a[i-1]"]
            eqs.append(f"{word} a[i] = {g_expr(rng, near + scal, 2)}")
        else:
            last = arr[0] - 1
            eqs.append(f"{word} a[i] = {g_expr(rng, ['a[i-1]', 'a[i]', 'a[i+1]'] + scal, 2)} for i in 1..{last - 1}")
            eqs.append(f"{word} a[0] = {g_expr(rng, ['a[0]', 'a[1]'] + scal, 2)}")
            eqs.append(f"{word} a[{last}] = {g_expr(rng, [f'a[{last}]', f'a[{last - 1}]'] + scal, 2)}")
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
    return "\n".join(lines) + "\n", shape


# A random source may meet a refusal a writer could meet too: a negated
# constant that is exactly zero, a constant mixing h with a rational, a
# constant past a narrow format. Those are counted and named; any other
# refusal is a defect in the generator, and fails.
ARTIFACTS = {"constant-negative-zero", "h-nonlinear", "constant-overflow",
             "constant-rounds-to-zero", "halving-underflow"}


def with_format(text, fmt):
    lines = text.split("\n")
    return "\n".join(f"format {fmt}" if ln.startswith("format ") else ln
                     for ln in lines)


def with_round(text, rnd):
    lines = text.split("\n")
    out, done = [], False
    for ln in lines:
        if ln.startswith("round "):
            out.append(f"round {rnd}")
            done = True
        else:
            out.append(ln)
            if ln.startswith("format ") and not done and \
                    not any(x.startswith("round ") for x in lines):
                out.append(f"round {rnd}")
                done = True
    return "\n".join(out)


# ---- coverage ---------------------------------------------------------------

COVER = {"ops": {}, "rounds": set(), "formats": set(), "integrators": set(),
         "shared": 0, "folded": 0, "spilled": 0, "copies": 0,
         "empty_step": 0, "lane_params": 0, "homed": 0, "pinned": 0,
         "flags": 0, "systems": 0}


def cover(c, flags):
    COVER["systems"] += 1
    for op, k in c.ir.op_counts().items():
        COVER["ops"][op] = COVER["ops"].get(op, 0) + k
    COVER["rounds"].add(c.ir.rnd_name)
    COVER["formats"].add(c.ir.fmt_name)
    COVER["integrators"].add(c.ir.integrator[0])
    COVER["shared"] += c.lowered.shared
    COVER["folded"] += len(c.lowered.folds)
    COVER["spilled"] += c.program.spill_slots
    COVER["copies"] += c.program.step_counts()["copies"]
    COVER["empty_step"] += not c.lowered.nodes
    COVER["lane_params"] += len(c.ir.lane)
    COVER["homed"] += c.program.pinning != "all"
    COVER["pinned"] += c.program.pinning != "none"
    COVER["flags"] |= flags


# The routines' own tally (C4), fed by the routines group's legs alone (K
# and L), so that the core tally above holds from the core legs and this
# one from its own: for each of div and sqrt, the formats, attributes and
# integrators an image holding it was compiled under and run at; the
# flags those runs raised; and the call loops run - their count, their
# calls, and which routines they looped.
RCOVER = {"images": 0, "flags": 0, "loops": 0, "looped_calls": 0,
          "looped_ops": set(),
          "by_op": {op: {"formats": set(), "rounds": set(),
                         "integrators": set(), "images": 0}
                    for op in ("div", "sqrt")}}


def rcover(c, flags):
    RCOVER["images"] += 1
    ops = c.ir.op_counts()
    for op, d in RCOVER["by_op"].items():
        if ops.get(op):
            d["images"] += 1
            d["formats"].add(c.ir.fmt_name)
            d["rounds"].add(c.ir.rnd_name)
            d["integrators"].add(c.ir.integrator[0])
    RCOVER["flags"] |= flags
    for b in getattr(c, "looped", ()):
        RCOVER["loops"] += 1
        RCOVER["looped_calls"] += len(b.calls)
        RCOVER["looped_ops"].add(b.op)


# ---- A and B: the references -------------------------------------------

def ref_text(base, fmt):
    src = SYSTEMS / f"{base}-fp64.cftl"
    # the file's bytes, decoded and not newline-translated: a text-mode
    # read would turn a lone CR into a line end before the language's
    # character rule could refuse it (D1's finding, L1's rule)
    return with_format(src.read_bytes().decode("ascii"), fmt)


def ref_compile(base, fmt, rnd=None, steps=None):
    text = ref_text(base, fmt)
    if rnd is not None:
        text = with_round(text, rnd)
    name = f"{base}-{fmt}" + (f"-{rnd}" if rnd else "")
    return cftc.compile_text(text, steps or REFS[base],
                             source=f"programs/systems/{name}.cftl",
                             stem=name)


def ref_lanes(base, fmt, n, rng):
    lanes = lanes_for(fmt, n, rng, REF_LANES[base], BOX[base])
    specials = special_lanes(fmt, n, lanes[0], rng)
    return lanes, specials


def hand_image(base, fmt):
    name = f"{base}-{fmt}"
    data = asm.assemble((PROGRAMS / f"{name}.cfta").read_text(
        encoding="ascii"), name)
    man = {}
    for line in (PROGRAMS / "MANIFEST").read_text(encoding="utf-8") \
            .splitlines():
        if line.strip() and not line.startswith("#"):
            hsh, fname = line.split()
            man[fname] = hsh
    return data, hashlib.sha256(data).hexdigest() == man.get(name + ".cftp")


def hand_costs(image):
    """gen_odes.py's image in the same terms as the compiled one."""
    img = asm.Image.from_bytes(image)
    words = [asm.decode(w) for w in img.insns]
    s = next(k for k, d in enumerate(words) if d["ctrl"] and
             d["op"] == asm.REPEAT)
    e = next(k for k, d in enumerate(words) if d["ctrl"] and
             d["op"] == asm.ENDREP)
    body = []
    regs = set()
    slots = set()
    for d in words[s + 1:e]:
        if d["ctrl"]:
            slot = d["imm"] & asm.SLOT_MASK
            slots.add(slot)
            if d["op"] == asm.LDL:
                body.append(Ins("ldl", rd=d["rd"], slot=slot))
                regs.add(d["rd"])
            else:
                body.append(Ins("stl", srcs=(("r", d["ra"]),), slot=slot))
                regs.add(d["ra"])
            continue
        srcs = []
        for (idx, kk), f in zip(asm.sources(d), ("ra", "rb", "rc")):
            if f in asm.OP_FIELDS[d["op"]]:
                srcs.append(("b", idx) if kk else ("r", idx))
                if not kk:
                    regs.add(idx)
        regs.add(d["rd"])
        body.append(Ins("alu", rd=d["rd"], srcs=srcs, op="x"))
    for d in words:
        if d["ctrl"] and d["op"] in (asm.LDL, asm.STL):
            slots.add(d["imm"] & asm.SLOT_MASK)
            regs.add(d["rd"] if d["op"] == asm.LDL else d["ra"])
    alu = sum(1 for i in body if i.kind == "alu")
    loads = sum(1 for i in body if i.kind == "ldl")
    stores = sum(1 for i in body if i.kind == "stl")
    return {"instructions": len(img.insns), "alu": alu, "loads": loads,
            "stores": stores, "registers": len(regs),
            "slots": max(slots) + 1 if slots else 0,
            "bank": img.n_consts, "one_beat": cycles(body, 1),
            "sixteen_beats": cycles(body, 16)}


def compiled_costs(c):
    pc = c.program.step_counts()
    return {"instructions": len(c.image_obj.insns), "alu": pc["alu"],
            "loads": pc["loads"], "stores": pc["stores"],
            "registers": len(c.program.registers()),
            "slots": c.program.slots_used, "bank": len(c.lowered.slots),
            "one_beat": c.cycles_one_beat,
            "sixteen_beats": c.cycles_sixteen_beats}


def leg_references(rng):
    section("A. the references, at every format, against the interpreter; "
            "B. against gen_odes.py's images")
    table = []
    for base in REFS:
        for fmt in ("fp32", "fp64", "fp128", "fp256"):
            c = ref_compile(base, fmt)
            n = c.ir.n_state
            lanes, specials = ref_lanes(base, c.ir.fmt, n, rng)
            allv = lanes + specials
            failing, first, fok, ref = compare(c, allv, None, REFS[base])
            cover(c, ref.flags)
            check(not failing and fok,
                  f"{base} {fmt}: {len(allv)} lanes at 1, 2, 5 and "
                  f"{REFS[base]} steps equal the interpreter, FLAGS "
                  f"{ref.flags:#x} included",
                  f"{len(failing)} lanes differ from step {first}, FLAGS "
                  f"{'equal' if fok else 'differ'}")
            roles = [("overflow", specials[0], sf.FLAG_OVERFLOW, "overflow"),
                     ("signalling NaN", specials[1], sf.FLAG_INVALID,
                      "invalid")]
            if base != "lorenz96-rk4":
                roles.append(("subnormal", specials[2], sf.FLAG_UNDERFLOW,
                              "underflow"))
            for role, lane, flag, word in roles:
                r1 = lang.run(c.graph, [lane], REFS[base])
                check(r1.flags & flag,
                      f"{base} {fmt}: the {role} lane raises {word}")
            if base == "lorenz96-rk4":
                # At F = 8 every right-hand side is F - x_i plus a product,
                # so a subnormal state is lost in a result near F and nothing
                # tiny is rounded: this lane raises inexact alone, at every
                # format (measured, and asserted here). Leg C runs it at
                # F = 0, where it underflows.
                r1 = lang.run(c.graph, [specials[2]], REFS[base])
                check(r1.flags == sf.FLAG_INEXACT,
                      f"{base} {fmt}: the subnormal lane raises inexact "
                      f"alone at F = 8 (FLAGS {r1.flags:#x}); leg C runs it "
                      f"at F = 0",
                      f"FLAGS {r1.flags:#x}, not {sf.FLAG_INEXACT:#x}")
            if fmt in ("fp64", "fp256"):
                classic = (PROGRAMS / f"{base}-{fmt}.classic.bank") \
                    .read_bytes()
                check(c.bank == classic, f"{base} {fmt}: the compiled bank "
                      f"is the classic bank byte for byte "
                      f"({len(c.lowered.slots)} slots)")
                hand, in_manifest = hand_image(base, fmt)
                check(in_manifest, f"{base} {fmt}: gen_odes.py's image is "
                      f"programs/MANIFEST's")
                hfail = set()
                for s in sorted({*CHECKPOINTS, REFS[base]}):
                    hr = run_image(image_at(hand, s), c, allv,
                                   bank=c.lowered.bank_values(), depth=256)
                    cr = run_image(image_at(c.image, s), c, allv)
                    m = c.ir.m
                    for k in range(len(allv)):
                        if hr.scratch_out[k * m:(k + 1) * m] != \
                                cr.scratch_out[k * m:(k + 1) * m]:
                            hfail.add(k)
                    if hr.flags != cr.flags:
                        hfail.add(-1)
                check(not hfail, f"{base} {fmt}: gen_odes.py's image on the "
                      f"classic bank equals the compiled image at every "
                      f"checkpoint, states and FLAGS",
                      f"{len(hfail)} differences")
                if fmt == "fp64":
                    table.append((base, hand_costs(hand), compiled_costs(c)))
                    got = compiled_costs(c)
                    row = (got["instructions"], got["alu"], got["loads"],
                           got["stores"], got["registers"], got["slots"],
                           got["bank"])
                    check(row == PINNED[base], f"{base}: the compiled costs "
                          f"are the pinned {PINNED[base]}",
                          f"measured {row}")
    print("\n  the references' costs, a step unless said (gen_odes.py "
          "against compiled; cycles from the revision-7 model, believed):")
    keys = ("instructions", "alu", "loads", "stores", "registers", "slots",
            "bank", "one_beat", "sixteen_beats")
    print("  " + "system".ljust(16) + "".join(k.rjust(15) for k in keys))
    for base, h, cpl in table:
        print("  " + base.ljust(16) + "".join(
            f"{h[k]:>7}/{cpl[k]:<7}" for k in keys))
    section("A. Lorenz-63 and Henon-Heiles under every attribute")
    for base in ("lorenz63-rk4", "henonheiles-lf"):
        for rnd in ("rtz", "rdn", "rup", "rmm"):
            c = ref_compile(base, "fp64", rnd)
            n = c.ir.n_state
            lanes = lanes_for(c.ir.fmt, n, rng, 16, BOX[base])
            lanes += special_lanes(c.ir.fmt, n, lanes[0], rng)
            failing, first, fok, ref = compare(c, lanes, None, REFS[base])
            cover(c, ref.flags)
            check(not failing and fok, f"{base} fp64 {rnd}: {len(lanes)} "
                  f"lanes at four checkpoints equal the interpreter",
                  f"{len(failing)} lanes differ from step {first}")


# ---- A: the generated corpus --------------------------------------------

# Shapes the lowering must get right, written out so that no draw of the
# generator can leave one out: every built-in once, an empty step, a swap
# and a rotation (the closing copies' cycles, pinned and homed), outputs
# that are a param and a lane param, the fold in a flow and in a map, and
# sharing. Each runs at every format.
SHAPES = {
    "every-builtin": (
        "system builtins\nformat fp64\nround rne\nstate x, y, z\n"
        "param a = 0.75\nlane param w = 1.5\n"
        "next x = select(x < y, copysign(x, z), -(abs(y)))"
        " + min(x, z) + max(y, a)\n"
        "next y = fma(x, y, z) - (minnum(y, w) * maxnum(z, x))"
        " + (x <= z) + (y > z)\n"
        "next z = (z >= x) + (x == y) - z\nstep map\n"),
    "empty-step": "system idm\nformat fp64\nstate x, y\nnext x = x\n"
                  "next y = y\nstep map\n",
    "swap": "system swp\nformat fp64\nstate x, y, z\nnext x = y\n"
            "next y = x\nnext z = z * 2\nstep map\n",
    "rotation": "system rot\nformat fp64\nstate a[30] cyclic\n"
                "next a[i] = a[i+1]\nstep map\n",
    "rotation-homed": "system roth\nformat fp64\nstate a[40] cyclic, s\n"
                      "next a[i] = a[i-1]\nnext s = s + a[0] * a[39]\n"
                      "step map\n",
    "leaf-outputs": "system leaves\nformat fp64\nstate x, y, z\n"
                    "param p = 2.5\nlane param m\nnext x = p\nnext y = m\n"
                    "next z = z * x + y\nstep map\n",
    "fold-flow": "system nf\nformat fp64\nround rup\nstate x, y\n"
                 "d/dt x = -(x * y)\nd/dt y = 3 * -(x + y)\n"
                 "step euler, h = 1/3\n",
    "fold-map": "system nfm\nformat fp64\nround rdn\nstate x\n"
                "next x = fma(h, -(x * x), x)\nstep map, h = 0.1\n",
    "shared": "system sh\nformat fp64\nstate x, y\n"
              "next x = (x - y) * (x - y)\nnext y = (y - x) + (x - y)\n"
              "step map\n",
}


# verifier-VL2's reproducer (its probes, sc63min.cftl): two homed outputs
# due at one position, and reloading the first evicted the second, whose
# only later use was its own store - "output 5's value is nowhere".
SC63MIN = """system sc63
format fp64
state c[44]
let L0 = c[1] * c[35] + 1
let L1 = c[26] * c[39] + 2
let L2 = c[39] * c[19] + 3
let L3 = c[17] * c[26] + 4
let L4 = c[32] * c[37] + 5
let L5 = c[35] * c[4] + 6
let L6 = c[35] * c[20] + 7
let L7 = c[23] * c[8] + 8
let L8 = c[6] * c[3] + 9
next c[0] = fma(c[39], c[30], c[0]) + L5 + L0
next c[1] = c[33] * c[15]
next c[2] = c[2]
next c[3] = fma(c[42], c[6], c[3])
next c[4] = c[4]
next c[5] = c[0] * c[40]
next c[6] = c[6]
next c[7] = c[22] * c[26]
next c[8] = c[8]
next c[9] = c[9]
next c[10] = fma(c[33], c[42], c[10]) + L2 + L1
next c[11] = c[11]
next c[12] = c[12]
next c[13] = c[13]
next c[14] = fma(c[24], c[8], c[14]) + L5
next c[15] = c[15]
next c[16] = c[16]
next c[17] = c[17]
next c[18] = c[31] * c[39] + L2
next c[19] = (c[19] - c[2])
next c[20] = c[20]
next c[21] = c[21]
next c[22] = c[22]
next c[23] = c[23]
next c[24] = c[24]
next c[25] = c[22] * c[10] + L5
next c[26] = c[26]
next c[27] = c[20] * c[10]
next c[28] = c[40] * c[24] + L8 + L2 + L0
next c[29] = c[29]
next c[30] = (c[30] - c[11])
next c[31] = c[35] * c[30] + L7 + L8
next c[32] = c[15] * c[6]
next c[33] = fma(c[0], c[9], c[33]) + L3
next c[34] = (c[34] - c[39]) + L8 + L6 + L5
next c[35] = c[2] * c[3] + L6 + L1 + L3 + L8
next c[36] = c[36]
next c[37] = c[37]
next c[38] = fma(c[20], c[33], c[38]) + L4 + L6
next c[39] = c[39]
next c[40] = fma(c[3], c[22], c[40])
next c[41] = c[41]
next c[42] = (c[42] - c[32]) + L6 + L2
next c[43] = c[8] * c[24]
step map
"""


def g_letmap(rng, k):
    """A let-heavy homed map: 26 to 48 components, up to 40 lets of
    products, outputs that are products, fmas, state leaves and identities
    with lets added - the shape in which two outputs fall due for their
    homes at one position with the registers full (verifier-VL2's hunt;
    this generator is written again here, after its shape)."""
    n = rng.randint(26, 48)
    nl = rng.randint(0, 40)
    lines = [f"system lm{k}",
             f"format {rng.choice(['fp32', 'fp64', 'fp128', 'fp256'])}",
             f"round {rng.choice(['rne', 'rtz', 'rdn', 'rup', 'rmm'])}",
             f"state c[{n}]"]
    lets = []
    for j in range(nl):
        a, b = rng.randrange(n), rng.randrange(n)
        lines.append(f"let L{j} = c[{a}] * c[{b}] + {j + 1}")
        lets.append(f"L{j}")
    used = {name: 0 for name in lets}
    eqs = []
    for i in range(n):
        kind = rng.random()
        a, b = rng.randrange(n), rng.randrange(n)
        picks = rng.sample(lets, min(len(lets), rng.randint(0, 4))) \
            if lets else []
        tail = "".join(f" + {name}" for name in picks)
        if kind < 0.35:
            eqs.append(f"next c[{i}] = c[{a}] * c[{b}]{tail}")
        elif kind < 0.55:
            eqs.append(f"next c[{i}] = c[{a}] * c[{b}]")
            picks = []
        elif kind < 0.7:
            eqs.append(f"next c[{i}] = fma(c[{a}], c[{b}], c[{i}]){tail}")
        elif kind < 0.8:
            eqs.append(f"next c[{i}] = c[{a}]")
            picks = []
        else:
            eqs.append(f"next c[{i}] = (c[{i}] - c[{a}]){tail}")
        for name in picks:
            used[name] += 1
    for name, u in used.items():
        if not u:
            i = rng.randrange(n)
            eqs[i] += f" + {name}"
    lines += eqs + ["step map"]
    return "\n".join(lines) + "\n"


def leg_letmaps(count, rng):
    section(f"A. {count} let-heavy homed maps, and verifier-VL2's reproducer")
    texts = [("vl2-sc63min", SC63MIN)] + \
        [(f"letmap {k}", g_letmap(random.Random(f"lang letmap {k}"), k))
         for k in range(count)]
    runs = bad_n = 0
    t0 = time.perf_counter()
    for name, text in texts:
        try:
            c = cftc.compile_text(text, 4, source=name, stem="lm")
        except lang.Refusal as e:
            if e.name not in ARTIFACTS:
                bad(f"{name}: refused {e.name}: {e}")
                bad_n += 1
            continue
        except cftc.InternalError as e:
            bad(f"{name}: internal error: {e}")
            bad_n += 1
            continue
        g = c.ir
        lanes = lanes_for(g.fmt, g.n_state, rng, 6)
        lanes += special_lanes(g.fmt, g.n_state, lanes[0], rng)
        failing, first, fok, ref = compare(c, lanes, None, 4)
        cover(c, ref.flags)
        runs += 1
        if failing or not fok:
            bad(f"{name}: {len(failing)} of {len(lanes)} lanes differ from "
                f"step {first}")
            bad_n += 1
    check(bad_n == 0, f"the let-heavy maps: {runs} compiled and equal to the "
          f"interpreter on 9 lanes at 1, 2 and 4 steps "
          f"({time.perf_counter() - t0:.1f} s)",
          f"{bad_n} of {len(texts)} failed")


def corpus_texts(count, seed="lang corpus"):
    rng = random.Random(seed)
    out = []
    k = 0
    while len(out) < count:
        text, shape = g_system(rng, k)
        k += 1
        out.append((text, shape))
    return out


def leg_corpus(count, rng):
    section(f"A. {len(SHAPES)} written shapes and {count} generated systems, "
            f"at every format L1 takes them")
    refused = {}
    texts = [(t, s) for s, t in SHAPES.items()] + corpus_texts(count)
    runs = 0
    for k, (text, shape) in enumerate(texts):
        own = next(ln.split()[1] for ln in text.split("\n")
                   if ln.startswith("format "))
        fmts = [own] if shape == "pressure" else \
            ["fp32", "fp64", "fp128", "fp256"]
        for fmt in fmts:
            t = with_format(text, fmt)
            try:
                c = cftc.compile_text(t, 4, source=f"corpus {k} {fmt}",
                                      stem=f"g{k}")
            except lang.Refusal as e:
                if e.name not in ARTIFACTS:
                    bad(f"corpus {k} ({shape}) {fmt}: refused {e.name}, "
                        f"which no generated system should meet: {e}")
                    print(t)
                else:
                    refused[e.name] = refused.get(e.name, 0) + 1
                continue
            except cftc.InternalError as e:
                bad(f"corpus {k} ({shape}) {fmt}: internal error: {e}")
                print(t)
                continue
            g = c.ir
            lanes = lanes_for(g.fmt, g.n_state, rng, 8)
            lanes += special_lanes(g.fmt, g.n_state, lanes[0], rng)
            lp = None
            if g.lane:
                lp = [[full_value(g.fmt, rng, Fraction(1, 2), 2)
                       for _ in g.lane] for _ in lanes]
            failing, first, fok, ref = compare(c, lanes, lp, 4)
            cover(c, ref.flags)
            runs += 1
            if failing or not fok:
                bad(f"corpus {k} ({shape}) {fmt}: {len(failing)} of "
                    f"{len(lanes)} lanes differ from step {first}, FLAGS "
                    f"{'equal' if fok else 'differ'}")
                print(t)
    check(runs > 0, f"the corpus: {runs} compiled systems equal the "
          f"interpreter on 11 lanes at 1, 2 and 4 steps (each one held "
          f"above)")
    print(f"  refused as a writer would be, by name: "
          f"{dict(sorted(refused.items())) or 'none'}")


# ---- C and D: banks, params, resume ---------------------------------------

def leg_banks(rng):
    section("C. the halved bank and the params; D. resume")
    for base in REFS:
        c = ref_compile(base, "fp64")
        g = c.ir
        lanes = lanes_for(g.fmt, g.n_state, rng, 8, BOX[base])
        h = g.integrator[1]
        failing, first, fok, _ref = compare(
            c, lanes, None, REFS[base], bank=c.lowered.half_bits,
            interp={"h": h / 2})
        check(not failing and fok, f"{base}: the halved bank equals the "
              f"interpreter at h/2 = {K.literal(h / 2)}",
              f"{len(failing)} lanes from step {first}")
        if g.param:
            vals = c.lowered.bank_values()
            pbits = {}
            for s_idx, s in enumerate(c.lowered.slots):
                if s.kind == "param":
                    v = full_value(g.fmt, rng, Fraction(1, 2), 30)
                    vals[s_idx] = v
                    pbits[g.param[s.index][0]] = v
            failing, first, fok, _ref = compare(
                c, lanes, None, REFS[base], bank=vals,
                interp={"param_bits": pbits})
            check(not failing and fok, f"{base}: every param's slot at a "
                  f"random value equals the interpreter on those "
                  f"encodings ({', '.join(pbits)})",
                  f"{len(failing)} lanes from step {first}")
        # resume: 2S in one segment against two segments of S
        S = REFS[base] // 2
        whole = run_image(image_at(c.image, 2 * S), c, lanes)
        half1 = run_image(image_at(c.image, S), c, lanes)
        half2 = run_image(image_at(c.image, S), c, lanes,
                          block=half1.scratch_out)
        check(whole.scratch_out == half2.scratch_out and
              whole.flags == half1.flags | half2.flags,
              f"{base}: one segment of {2 * S} steps is two segments of "
              f"{S}, states and FLAGS")
    # Lorenz-96's subnormal lane underflows only where F does not swamp it
    c = ref_compile("lorenz96-rk4", "fp64")
    g = c.ir
    lanes = lanes_for(g.fmt, g.n_state, rng, 2, BOX["lorenz96-rk4"])
    sub = special_lanes(g.fmt, g.n_state, lanes[0], rng)[2]
    vals = c.lowered.bank_values()
    fslot = next(k for k, s in enumerate(c.lowered.slots)
                 if s.kind == "param")
    vals[fslot] = 0
    failing, first, fok, ref = compare(c, lanes + [sub], None, REFS[
        "lorenz96-rk4"], bank=vals, interp={"param_bits": {"F": 0}})
    alone = lang.run(c.graph, [sub], REFS["lorenz96-rk4"],
                     param_bits={"F": 0})
    check(not failing and fok and alone.flags & sf.FLAG_UNDERFLOW,
          f"lorenz96-rk4: at F = 0 the image equals the interpreter and the "
          f"subnormal lane raises underflow (FLAGS {alone.flags:#x})",
          f"{len(failing)} lanes from step {first}")

    def param_slot(c, name):
        return next(s for s in c.lowered.slots if s.kind == "param"
                    and c.ir.param[s.index][0] == name)
    c = cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 5,
                          params={"sigma": "12", "beta": "8/3"})
    want = K.round_once(c.ir.fmt, c.ir.rnd, Fraction(12))[0]
    check(param_slot(c, "sigma").bits == want and
          [o["name"] for o in c.manifest["param_overrides"]] ==
          ["sigma", "beta"],
          "--param sigma=12 writes RN(12) into sigma's slot, and the "
          "manifest records both overrides")
    # Two values a binary64 route gets wrong, so these checks can tell the
    # language's reading from Python's float: 0.1 at fp128 (RN128 of 1/10,
    # not 0.1's binary64 value widened), and at fp32 1 + 2^-24 + 2^-60,
    # whose binary64 rounding is the fp32 tie 1 + 2^-24 and so rounds to
    # even, to 1, where the value itself rounds up to 1 + 2^-23.
    for fmt, text, exact in (("fp128", "0.1", Fraction(1, 10)),
                             ("fp32", "0x1.000001000000001p+0",
                              1 + Fraction(1, 1 << 24) +
                              Fraction(1, 1 << 60))):
        c = cftc.compile_text(ref_text("lorenz63-rk4", fmt), 3,
                              source=f"lorenz63-rk4-{fmt}",
                              params={"sigma": text})
        right = K.round_once(c.ir.fmt, sf.RND_RNE, exact)[0]
        via64 = K.round_once(c.ir.fmt, sf.RND_RNE,
                             Fraction(float(exact)))[0]
        got = param_slot(c, "sigma").bits
        check(got == right != via64,
              f"--param sigma={text} at {fmt} is RN of the exact value, "
              f"{K.bits_hex(c.ir.fmt, right)}, where a binary64 route gives "
              f"{K.bits_hex(c.ir.fmt, via64)}",
              f"the slot holds {K.bits_hex(c.ir.fmt, got)}")
    big_values(rng)


# ---- C: values past Python's 4,300-digit limit ------------------------------

# The language holds a constant to 2^+-1048576 and reads a literal at any
# length, so a const of 1e-5000 or an h of 1e-4400 at fp256 is a system
# L1's checker, to_bytes and from_bytes all take - and Python's own
# Fraction() and str() raise ValueError past 4,300 digits. The compiler
# read and wrote exact values through them until verifier-VL2's re-check
# (a bare ValueError, exit 1). Each case here is compiled, its exact
# values read back from the manifest's bytes by the gate's own reader,
# and its image run against the interpreter.

BIG_STEPS = 20


def big_int(text):
    """A decimal integer at any length, read in chunks below Python's
    limit - the gate's own reader, not the language's."""
    n = 0
    for k in range(0, len(text), 1000):
        chunk = text[k:k + 1000]
        n = n * 10 ** len(chunk) + int(chunk)
    return n


def read_frac(text):
    """p or p/q, as the manifest writes an exact value, at any length."""
    neg = text.startswith("-")
    num, _, den = text[neg:].partition("/")
    v = Fraction(big_int(num), big_int(den) if den else 1)
    return -v if neg else v


def long_decimal(rng, digits):
    """(text, exact): 1.ddd...d with `digits` significant digits, the last
    odd and not 5, so that its p/q in lowest terms has `digits` digits in
    the numerator and in the denominator alike."""
    body = "".join(rng.choice("0123456789") for _ in range(digits - 2)) + \
        rng.choice("1379")
    return "1." + body, Fraction(big_int("1" + body), 10 ** (digits - 1))


def big_values(rng):
    section("C. values past Python's 4,300-digit limit, compiled, read back "
            "from the manifest, and run against the interpreter")
    rne = sf.RND_RNE
    fmt = FORMATS["fp256"]

    def rn(v):
        return K.bits_hex(fmt, K.round_once(fmt, rne, v)[0])
    p_text, p_exact = long_decimal(rng, 5000)
    q_text, q_exact = long_decimal(rng, 5000)
    r_text, r_exact = long_decimal(rng, 5000)
    tiny, h = Fraction(1, 10 ** 5000), Fraction(1, 10 ** 4400)
    cases = [
        ("a const of 1e-5000",
         "system bigconst\nformat fp256\nstate x, y\nconst c = 1e-5000\n"
         "next x = x * c\nnext y = y + c\nstep map\n", None),
        ("an h of 1e-4400",
         "system bigh\nformat fp256\nstate x\nd/dt x = -x\n"
         "step rk4, h = 1e-4400\n", None),
        ("a param's and a lane param's 5,000-digit defaults",
         f"system bigdefault\nformat fp256\nstate x, y\nparam p = {p_text}\n"
         f"lane param q = {q_text}\nnext x = x * p\nnext y = y * q\n"
         f"step map\n", None),
        ("a 5,000-digit run value",
         "system bigrun\nformat fp256\nstate x\nparam p = 2\n"
         "next x = x * p\nstep map\n", {"p": r_text}),
    ]
    for what, text, params in cases:
        try:
            c = cftc.compile_text(text, BIG_STEPS, source=what,
                                  params=params)
            m = json.loads(c.manifest_bytes)
        except Exception as e:      # noqa: BLE001 - a crash is the finding
            bad(f"{what}: cftc raised {type(e).__name__}: {str(e)[:120]}")
            continue
        bank = {e["name"]: e for e in m["bank"]}
        said = []
        if what.startswith("a const"):
            e = bank["1e-5000"]
            said.append(("the const's exact value", read_frac(e["exact"]),
                         tiny, e["encoding"], rn(tiny)))
        elif what.startswith("an h"):
            said.append(("the integrator's h",
                         read_frac(m["integrator"]["h"]), h, None, None))
            for e in m["bank"]:
                if e["h_factor"] is not None and \
                        read_frac(e["h_factor"]) != 0:
                    v = read_frac(e["h_factor"]) * h
                    said.append((f"bank slot {e['slot']} ({e['name']})",
                                 read_frac(e["exact"]), v, e["encoding"],
                                 rn(v)))
                    said.append((f"bank slot {e['slot']} halved", None, None,
                                 e["halved"], rn(v / 2)))
        elif what.startswith("a param's"):
            e = bank["p"]
            said.append(("p's default", read_frac(e["exact"]), p_exact,
                         e["encoding"], rn(p_exact)))
            lp = next(x for x in m["scratch"]["layout"]
                      if x["name"] == "q")
            said.append(("q's default", read_frac(lp["default"]), q_exact,
                         lp["default_encoding"], rn(q_exact)))
        else:
            o = m["param_overrides"][0]
            said.append(("the override's value", read_frac(o["value"]),
                         r_exact, o["encoding"], rn(r_exact)))
            said.append(("the override's default", read_frac(o["default"]),
                         Fraction(2), None, None))
            said.append(("p's bank slot", None, None, bank["p"]["encoding"],
                         rn(r_exact)))
        wrong = [f"{name}: {'value' if got != want else 'encoding'}"
                 for name, got, want, enc, renc in said
                 if got != want or enc != renc]
        longest = max(len(e["exact"]) for e in m["bank"])
        check(not wrong, f"{what}: the manifest's exact values read back "
              f"equal to the source's, each encoding RN of its value "
              f"({len(said)} read; the longest bank value "
              f"{longest:,} characters)", "; ".join(wrong))
        n = c.ir.n_state
        lanes = lanes_for(c.ir.fmt, n, rng, 6)
        lanes += special_lanes(c.ir.fmt, n, lanes[0], rng)
        interp = None
        if params:
            interp = {"param_bits": {"p": param_slot_bits(c, "p")}}
        failing, first, fok, ref = compare(c, lanes, None, BIG_STEPS,
                                           interp=interp)
        check(not failing and fok, f"{what}: {len(lanes)} lanes at 1, 2, 5 "
              f"and {BIG_STEPS} steps equal the interpreter (FLAGS "
              f"{ref.flags:#x})",
              f"{len(failing)} lanes differ from step {first}, FLAGS "
              f"{'equal' if fok else 'differ'}")
        if c.lowered.half_bits is not None:
            failing, first, fok, ref = compare(
                c, lanes, None, BIG_STEPS, bank=c.lowered.half_bits,
                interp={"h": c.ir.integrator[1] / 2})
            check(not failing and fok, f"{what}: the halved bank equals the "
                  f"interpreter at h/2 (FLAGS {ref.flags:#x})",
                  f"{len(failing)} lanes from step {first}")


def param_slot_bits(c, name):
    return next(s.bits for s in c.lowered.slots if s.kind == "param"
                and c.ir.param[s.index][0] == name)


# ---- E: libcft's software backend -----------------------------------------

def leg_libcft(segrun, audit, rng, work):
    section("E. cft-segrun certifies the compiled references; both "
            "auditors accept; a wider run of a routine image refused by "
            "both C tools")
    if not segrun or not Path(segrun).is_file():
        skip("E: cft-segrun's certificates of the compiled images",
             f"no cft-segrun at {segrun!r} (the stage builds it)")
        return
    segrun = Path(segrun).resolve()
    have_audit = bool(audit) and Path(audit).is_file()
    if have_audit:
        audit = Path(audit).resolve()
    if not have_audit:
        skip("E: cft-audit on each certificate",
             f"no cft-audit at {audit!r} (the stage builds it)")
    for base, steps in {**REFS, **ROUTINE_REFS}.items():
        for fmt in ("fp64", "fp256"):
            c = cftc.compile_file(SYSTEMS / f"{base}-{fmt}.cftl", steps,
                                  source=f"programs/systems/{base}-{fmt}"
                                         ".cftl")
            certify(c, f"{base}-{fmt}", segrun, audit if have_audit else None,
                    rng, work)
    text, _shape = next((t, s) for t, s in corpus_texts(40, "lang e")
                        if "lane param" in t and "h = " in t
                        and "step map\n" not in t)
    try:
        c = cftc.compile_text(with_format(text, "fp64"), 6,
                              source="generated", stem="generated")
    except lang.Refusal as e:
        skip("E: a generated system with lane params", f"L1 refused it: {e}")
        return
    certify(c, "generated-lane-params", segrun,
            audit if have_audit else None, rng, work)
    wider_routine_controls(segrun, audit if have_audit else None, rng, work)


def wider_routine_controls(segrun, audit, rng, work):
    """C4: version 1 has no wider run of an image holding a routine - its
    words and its bank words are its format's - so both C tools refuse
    one, `aux-image` (exit 5): cft-segrun will not write it, and cft-audit
    refuses one made through the gate's instrument
    (CFT_SEGRUN_PLANT=wider-routine). The wider image is the main image's
    own words one rung up, its bank and start exactly widened - all that
    version 1's relation holds - so the routine rule alone refuses it; the
    same construction on Lorenz-63, which holds no routine, is written and
    accepted. (The golden writer's and audit's half is certificate version
    2's parcel's.)"""
    sizes = {"fp64": 8, "fp128": 16}
    for base, routine in (("kepler-sv", True), ("lorenz63-rk4", False)):
        steps = ROUTINE_REFS.get(base) or REFS[base]
        c = cftc.compile_file(SYSTEMS / f"{base}-fp64.cftl", steps,
                              source=f"programs/systems/{base}-fp64.cftl")
        g = c.ir
        d = work / "certs" / f"wider-{base}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        block = c.scratch_block(lanes_for(g.fmt, g.n_state, rng, 2,
                                          BOX.get(base)))
        wide = bytearray(c.image)
        wide[20:24] = (2).to_bytes(4, "little")     # the precision code
        files = {
            "image.cftp": c.image, "main.bank": c.bank,
            "init.bin": cert.state_bytes("fp64", block),
            "wide.cftp": bytes(wide),
            "wide.bank": b"".join(cert.widen(g.fmt_name, v).to_bytes(
                sizes["fp128"], "little") for v in c.lowered.bank_values()),
            "wide.bin": cert.state_bytes("fp128", [cert.widen(g.fmt_name, v)
                                                   for v in block])}
        for name, data in files.items():
            (d / name).write_bytes(data)
        # version 1 (--format-version 1): cft-segrun writes version 2 by
        # default since version 2's C half; this leg holds version 1's
        # routine rule, and its control is audited as version 1
        args = ["--format-version", "1", "--out", d / "c.cert", "--states",
                d / "states", "--open", "--device", "sw",
                "--run", "main", "--image", d / "image.cftp", "--bank",
                d / "main.bank", "--init", d / "init.bin", "--segments", 1,
                "--steps", steps,
                "--run", "wider", "--image", d / "wide.cftp", "--bank",
                d / "wide.bank", "--init", d / "wide.bin", "--segments", 1,
                "--steps", steps]
        cmd = [str(segrun)] + [str(a) for a in args]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if routine:
            check(r.returncode == 5 and r.stderr.startswith(
                "cft-segrun: refused aux-image: run 1 (wider)") and
                not (d / "c.cert").exists() and not (d / "states").exists(),
                f"{base}: cft-segrun refuses a wider run of its image, which "
                f"holds routines, aux-image (exit 5), nothing made",
                f"rc {r.returncode}: {r.stderr.strip()[-200:]}")
            env = dict(os.environ, CFT_SEGRUN_PLANT="wider-routine")
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=600, env=env)
            if not check(r.returncode == 0 and (d / "c.cert").is_file(),
                         f"{base}: through the instrument "
                         f"CFT_SEGRUN_PLANT=wider-routine it is written",
                         f"rc {r.returncode}: {r.stderr.strip()[-200:]}"):
                continue
        elif not check(r.returncode == 0, f"{base}: cft-segrun writes the "
                       f"same construction for an image with no routine",
                       f"rc {r.returncode}: {r.stderr.strip()[-200:]}"):
            continue
        if not audit:
            skip(f"{base}: cft-audit on the wider run", "no cft-audit")
            continue
        seed = hashlib.sha256(f"lang wider {base}".encode()).digest()
        a = subprocess.run(
            [str(audit)] + [str(x) for x in (
                "--cert", d / "c.cert", "--states", d / "states", "--seed",
                seed.hex(), "--run", "0", "--image", d / "image.cftp",
                "--bank", d / "main.bank", "--choose", "all", "--run", "1",
                "--image", d / "wide.cftp", "--bank", d / "wide.bank",
                "--choose", "all")],
            capture_output=True, text=True, timeout=600)
        if routine:
            check(a.returncode == 5 and "cft-audit: refused aux-image: run 1 "
                  "(wider): the main image holds a routine" in a.stderr and
                  "location line=- run=1 segment=- entry=-" in a.stderr,
                  f"{base}: cft-audit refuses that certificate, aux-image at "
                  f"run 1 (exit 5): version 1 has no wider run of a routine "
                  f"image", f"rc {a.returncode}: {a.stderr.strip()[-200:]}")
        else:
            check(a.returncode == 0, f"{base}: cft-audit accepts it - the "
                  f"rule refuses routine images alone",
                  f"rc {a.returncode}: {a.stderr.strip()[-200:]}")


def certify(c, name, segrun, audit, rng, work):
    g = c.ir
    d = work / "certs" / name
    d.mkdir(parents=True, exist_ok=True)
    lanes = lanes_for(g.fmt, g.n_state, rng, 4, BOX.get(name.rsplit("-", 1)[0]))
    lp = None
    if g.lane:
        lp = [[full_value(g.fmt, rng, Fraction(1, 2), 2) for _ in g.lane]
              for _ in lanes]
    block = c.scratch_block(lanes, lp)
    (d / "image.cftp").write_bytes(c.image)
    (d / "main.bank").write_bytes(c.bank)
    (d / "half.bank").write_bytes(c.half_bank)
    (d / "init.bin").write_bytes(cert.state_bytes(g.fmt_name, block))
    out, states = d / "c.cert", d / "states"
    for p in (out,):
        if p.exists():
            p.unlink()
    if states.exists():
        shutil.rmtree(states)
    # version 1 (--format-version 1): cft-segrun writes version 2 by default
    # since version 2's C half, and a routine image would then need its
    # source and a replay route; this leg certifies version 1
    args = ["--format-version", "1", "--out", out, "--states", states,
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
    r = subprocess.run([str(segrun)] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=600)
    if not check(r.returncode == 0, f"{name}: cft-segrun certifies it, a "
                 f"main run of 2 segments and a half-step run of 4 on the "
                 f"halved bank, h-slots {c.lowered.h_slots} "
                 f"({time.perf_counter() - t0:.1f} s)",
                 f"rc {r.returncode}: {r.stderr.strip()[-300:]}"):
        return
    data = out.read_bytes()
    try:
        cert.parse(data)
        ok(f"{name}: the golden reader accepts it ({len(data)} bytes)")
    except cert.Refusal as e:
        bad(f"{name}: the golden reader refuses it: {e}")
        return
    sb = {}
    for run_i, segs in ((0, 2), (1, 4)):
        sb[run_i] = {b: (states / f"run-{run_i}-boundary-{b}.bin")
                     .read_bytes() for b in range(segs + 1)}
    progs = {0: (c.image, c.bank), 1: (c.image, c.half_bank)}
    seed = hashlib.sha256(f"lang {name}".encode()).digest()
    full = sampled = None
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
    if not audit:
        return
    for how, verdict, extra in (
            ("in full", full, ["--choose", "all", "--choose", "all"]),
            ("sampled", sampled, ["--choose", "sample:1", "--choose",
                                  "sample:2"])):
        args = ["--cert", out, "--states", states, "--seed", seed.hex(),
                "--run", "0", "--image", d / "image.cftp", "--bank",
                d / "main.bank", "--choose", extra[1],
                "--run", "1", "--image", d / "image.cftp", "--bank",
                d / "half.bank", "--choose", extra[3]]
        r = subprocess.run([str(audit)] + [str(a) for a in args],
                           capture_output=True, text=True, timeout=600)
        got = r.stdout.split("\n")
        if got and got[-1] == "":
            got = got[:-1]
        check(r.returncode == 0 and got == list(verdict.lines()),
              f"{name}: cft-audit accepts it {how}, the golden verdict line "
              f"for line",
              f"rc {r.returncode}: {r.stderr.strip()[-300:]}")


# ---- F: determinism ----------------------------------------------------------

def compiled_references():
    out = {}
    for base, steps in {**REFS, **ROUTINE_REFS}.items():
        for fmt in ("fp64", "fp256"):
            c = cftc.compile_file(SYSTEMS / f"{base}-{fmt}.cftl", steps,
                                  source=f"programs/systems/{base}-{fmt}"
                                         ".cftl")
            out.update(c.files())
    return out


def digests_main(path):
    """The child of leg F: compile what the file lists, print digests."""
    jobs = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for name, data in compiled_references().items():
        out[name] = hashlib.sha256(data).hexdigest()
    for k, text in enumerate(jobs):
        try:
            c = cftc.compile_text(text, 4, source=f"corpus {k}", stem=f"g{k}")
        except lang.Refusal as e:
            out[f"g{k}"] = f"refused {e.name}"
            continue
        for name, data in c.files().items():
            out[name] = hashlib.sha256(data).hexdigest()
    print(json.dumps(out, sort_keys=True))
    return 0


def leg_determinism(work):
    section("F. determinism: two processes, two hash seeds, the committed "
            "references")
    jobs = [t for t, _s in corpus_texts(6, "lang determinism")]
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
    nrefs = 2 * (len(REFS) + len(ROUTINE_REFS))
    check(seen[0] == seen[1] and len(seen[0]) > 50,
          f"PYTHONHASHSEED 0 and 4242 write the same bytes: {len(seen[0])} "
          f"files (the {nrefs} references and six generated systems, every "
          f"output)")
    files = compiled_references()
    have = sorted(p.name for p in COMPILED.iterdir()) if COMPILED.is_dir() \
        else []
    check(have == sorted(files), f"programs/systems/compiled/ holds exactly "
          f"the {nrefs} references' {len(files)} files, Kepler's with "
          f"routines among them",
          f"it holds {len(have)}: run programs/lang_check.py --write")
    wrong = [n for n, data in files.items()
             if (COMPILED / n).is_file() and (COMPILED / n).read_bytes()
             != data]
    check(not wrong, "every committed compiled reference is what the "
          "compiler writes, byte for byte", f"differ: {wrong[:6]}")
    leg_output_version()


def leg_output_version():
    """cftc's VERSION is an output version (C4; python/cftc/outputs.py):
    the record's last block is VERSION's and names every committed
    compiled file with its true digest. So a compiler change that moves
    a committed byte fails here until VERSION is bumped and a block
    appended (--record). And the check is held itself: each of its
    refusals made on a copy of the record, in memory."""
    rec = SYSTEMS / O.RECORD_NAME
    text = rec.read_text(encoding="ascii") if rec.is_file() else ""
    files = O.committed(SYSTEMS)
    probs = O.problems(text, files, cftc.VERSION) if text else \
        [f"no {rec.name}"]
    blocks = O.parse(text) if not probs else []
    check(not probs, f"cftc's output version {cftc.VERSION}: the record's "
          f"last block names the {len(files)} committed compiled files, "
          f"each with its digest, and nothing else (versions "
          f"{', '.join(str(v) for v, _b in blocks)})", "; ".join(probs))
    if probs:
        return
    some = sorted(files)[0]
    moved = dict(files, **{some: "0" * 64})
    planted = {
        "a committed byte moved, VERSION not bumped":
            O.problems(text, moved, cftc.VERSION),
        "VERSION bumped with no block": O.problems(text, files,
                                                   cftc.VERSION + 1),
        "a committed file not recorded": O.problems(
            text, dict(files, **{"compiled/x.cfta": "1" * 64}),
            cftc.VERSION),
        "a recorded file gone": O.problems(
            text, {p: d for p, d in files.items() if p != some},
            cftc.VERSION),
        "a version out of turn": O.problems(
            text.replace(f"version {cftc.VERSION}\n",
                         f"version {cftc.VERSION + 1}\n"), files,
            cftc.VERSION + 1),
    }
    missed = [k for k, v in planted.items() if not v]
    check(not missed, f"the record's check catches each of "
          f"{len(planted)} plants: {', '.join(planted)}",
          f"missed: {missed}")


# ---- G: refusals -------------------------------------------------------------

def leg_refusals():
    section("G. every refusal the compiler makes, by name")
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
    l63 = SYSTEMS / "lorenz63-rk4-fp64.cftl"
    l96 = SYSTEMS / "lorenz96-rk4-fp64.cftl"
    trim = TG.Target("u50-trim", ("fp64", "fp128"), 32768, 512, 2048, 1024,
                     TG.TILE_FEATURES)
    pre_r4 = TG.Target("pre-r4", TG.ALL_FORMATS, 16384, 512, 256, 64,
                       TG.TILE_FEATURES & ~TG.FEATURE_BITS["SCRATCH_STRICT"])
    tiny = TG.Target("tiny", TG.ALL_FORMATS, 16, 512, 256, 64,
                     TG.TILE_FEATURES)
    big = ("system big\nformat fp64\nstate x[257]\n"
           "next x[i] = x[i] + 1\nstep map\n")
    halving = ("system hu\nformat fp32\nstate x\nnext x = x + h\n"
               "step map, h = 3 * 0x1p-149\n")
    expect("target-format",
           lambda: cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp256.cftl", 3,
                                     target=trim),
           "fp256 for a build that carries fp64 and fp128")
    expect("target-feature",
           lambda: cftc.compile_file(l63, 3, target=pre_r4),
           "a strict image for a tile without CAPS2[6]")
    expect("program-capacity",
           lambda: cftc.compile_file(l63, 3, target=tiny),
           "62 instructions for a target that holds 16")
    expect("scratch-capacity",
           lambda: cftc.compile_text(big, 2, target="sw"),
           "257 state values a lane on the software backend's 256")
    try:
        c = cftc.compile_text(big, 2, target="u50-rev7")
        check(c.program.slots_used == 257 and c.depth == 512,
              "the same program is accepted where the scratch is deep "
              "enough (u50-rev7), declaring .scratch 512")
    except lang.Refusal as e:
        bad(f"the 257-slot program is refused on u50-rev7: {e}")
    expect("loader-bound",
           lambda: cftc.compile_file(l96, cftc.MAX_STEPS),
           "4,294,967,295 steps of Lorenz-96")
    expect("segment-steps", lambda: cftc.compile_file(l63, 0), "0 steps")
    expect("segment-steps", lambda: cftc.compile_file(l63, 1 << 32),
           "2^32 steps")
    expect("halving-underflow", lambda: cftc.compile_text(halving, 2),
           "h = 3 x 2^-149 at fp32, whose half is not exact")
    routine = ("system dv\nformat fp64\nstate x, y\nnext x = x\n"
               "next y = sqrt(abs(x)) / y\nstep map\n")
    expect("target-feature",
           lambda: cftc.compile_text(routine, 2, target="u50-rev7"),
           "a run-time root and division on revision 7's tile, which has no "
           "flag control for their routines (C4; leg K holds every target)")
    words = len({b for op in ("div", "sqrt") for b in R.fragment(
        op, FORMATS["fp64"], sf.RND_RNE).words.values()})
    k = 512 - words + 1
    wide = ("system wide\nformat fp64\nstate x, y\nparam "
            + ", ".join(f"p{i} = {i + 1}" for i in range(k))
            + "\nnext x = sqrt(abs(x)) / y + ("
            + " + ".join(f"p{i}" for i in range(k)) + ")\nnext y = y\n"
            "step map\n")
    expect("bank-capacity", lambda: cftc.compile_text(wide, 2),
           f"{k} params and the {words} words of a division's and a root's "
           f"routines, past the bank's 512 - the language's name, raised by "
           f"the compiler for the words the checker cannot see (C4)")
    # the eighth since M1's build, item 4: a run-time call of the math
    # library's six on a host without mpmath, through which their routines'
    # generator derives every constant - the one refusal that depends on the
    # host. It is made here on every host as the tests make it, mpmath taken
    # out of sys.modules for these compiles alone (simulated, not a host
    # without it): first, on a revision-7 target, where with mpmath the same
    # source is target-feature. The two sources the interim math-library
    # refused here until item 4 - log1p at run time, and a fold of exp2
    # alone - compile with mpmath, and the fold without it too.
    runtime = ("system m\nformat fp64\nstate x, y\nnext x = x * y\n"
               "next y = log1p(abs(x))\nstep map\n")
    fold = ("system m\nformat fp64\nstate x\nconst k = exp2(-3)\n"
            "next x = x * k\nstep map\n")
    held = sys.modules.get("mpmath", _ABSENT)
    sys.modules["mpmath"] = None
    try:
        expect("routine-unavailable",
               lambda: cftc.compile_text(runtime, 2, target="u50-rev7",
                                         source="m.cftl"),
               "log1p at run time with mpmath taken away (sys.modules), on "
               "revision 7's single, before target-feature")
        try:
            image = cftc.compile_text(fold, 2, source="m.cftl").image
        except lang.Refusal as e:
            image = None
            bad(f"a fold of exp2 alone, in a const, with mpmath taken away: "
                f"refused {e.name}")
    finally:
        if held is _ABSENT:
            del sys.modules["mpmath"]
        else:
            sys.modules["mpmath"] = held
    if image is not None:
        check(image == cftc.compile_text(fold, 2, source="m.cftl").image,
              "a fold of exp2 alone, in a const - math-library's until M1's "
              "build, item 4 - compiles with mpmath taken away, the same "
              "image as with it")
    if not have_mpmath():
        skip("the six at run time: log1p compiled and run by lang.run",
             "python has no mpmath module, which the six's golden functions "
             "and routines need")
    else:
        c = cftc.compile_text(runtime, 2, source="m.cftl")
        check("log1p" in c.manifest["routines"]["calls"] and
              len(lang.run(c.graph, [[1] * c.ir.n_state], 2).states) == 1,
              "log1p at run time - math-library's until M1's build, item 4 - "
              "compiles for sw, its routine inlined, and lang.run runs it")
    want = set(cftc.NAMES) | set(cftc.refusals.SHARED)
    check(made == want, f"every one of the compiler's {len(cftc.NAMES)} "
          f"names was made, and the language's bank-capacity it raises "
          f"too", f"missing {sorted(want - made)}")


# ---- H: plants -----------------------------------------------------------------

CHECK_OFF = ("__init__.py", "    verify(low, prog, c.image, steps, half)\n",
             "    pass  # PLANT: the internal check, off\n")

PLANTS = {
    "a dropped node": [
        ("regalloc.py", '        self.emit(Ins("alu", op=nd.op,',
         '        (self.emit if j != len(self.low.nodes) // 2 else '
         '(lambda _i: None))(Ins("alu", op=nd.op,')],
    "a swapped fma operand that changes the sum": [
        ("regalloc.py",
         "        dying = [k for k in keys if self.next_use(k, q) is None]\n",
         "        if nd.op == 'fma' and srcs[1] != srcs[2] and j == min(\n"
         "                x for x, y in enumerate(self.low.nodes)\n"
         "                if y.op == 'fma' and y.args[1] != y.args[2]):\n"
         "            srcs = (srcs[0], srcs[2], srcs[1])\n"
         "        dying = [k for k in keys if self.next_use(k, q) is None]\n")],
    "a register reused while live": [
        ("__init__.py", "    c.lowered, c.program = low, prog\n",
         "    c.lowered, c.program = low, prog\n"
         "    _plant_reuse(prog)\n"),
        ("__init__.py", "def compile_text(",
         "def _plant_reuse(prog):\n"
         "    body = prog.body\n"
         "    for i, ins in enumerate(body):\n"
         "        if ins.kind != 'alu':\n"
         "            continue\n"
         "        for j in range(i + 1, len(body)):\n"
         "            for r in body[j].reads():\n"
         "                if r == ins.rd:\n"
         "                    continue\n"
         "                live = all(r != body[x].rd for x in range(i, j)\n"
         "                           if body[x].rd is not None)\n"
         "                if live and any(r in body[x].reads() or r == body[x].rd\n"
         "                                for x in range(0, i)):\n"
         "                    ins.rd = r\n"
         "                    return\n"
         "\n\n"
         "def compile_text(")],
    "a wrong h-scaled slot": [
        ("regalloc.py",
         '                     else ("b", self.low.slot_of[a]) for a in nd.args)',
         '                     else ("b", _plant_slot(self.low, a)) for a in nd.args)'),
        ("regalloc.py", "def allocate(low, order, pinning=\"none\"):",
         "def _plant_slot(low, a):\n"
         "    k = low.slot_of[a]\n"
         "    if low.slots[k].factor == __import__('fractions').Fraction(1, 2):\n"
         "        for kk, s in enumerate(low.slots):\n"
         "            if s.kind == 'const' and s.factor == 1:\n"
         "                return kk\n"
         "    return k\n"
         "\n\n"
         "def allocate(low, order, pinning=\"none\"):")],
    "a fold that is not bit-identical (RN(-c) for -RN(c))": [
        ("lower.py", "                            bits ^ sign, flags))",
         "                            __import__('cft_golden.lang.constants',"
         " fromlist=['x']).round_once(graph.fmt, graph.rnd, -exact)[0],"
         " flags))")],
}
PLANT_SYSTEMS = {
    "a fold that is not bit-identical (RN(-c) for -RN(c))":
        [("henonheiles-lf", "fp64", "rdn"), ("henonheiles-lf", "fp64", "rup"),
         ("henonheiles-lf", "fp64", None)],
}
DEFAULT_PLANT_SYSTEMS = [("lorenz63-rk4", "fp64", None),
                         ("henonheiles-lf", "fp64", None)]


def plant_copy(edits, tag, work):
    d = work / "plants" / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    pkg = d / f"cftc_plant_{tag}"
    shutil.copytree(ROOT / "python" / "cftc", pkg,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for fname, old, new in edits:
        p = pkg / fname
        text = p.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise AssertionError(f"the plant's anchor is in {fname} "
                                 f"{text.count(old)} times, not once: "
                                 f"{old.strip()[:60]!r}")
        p.write_text(text.replace(old, new), encoding="utf-8")
    sys.path.insert(0, str(d))
    try:
        mod = importlib.import_module(pkg.name)
    finally:
        sys.path.remove(str(d))
    return mod


def leg_plants(rng, work):
    section("H. plants in a copy of the package: the internal check stops "
            "each, and with it off seq.py turns each red")
    for k, (what, edits) in enumerate(PLANTS.items()):
        systems = PLANT_SYSTEMS.get(what, DEFAULT_PLANT_SYSTEMS)
        try:
            on = plant_copy(edits, f"{k}on", work)
            off = plant_copy(edits + [CHECK_OFF], f"{k}off", work)
        except AssertionError as e:
            bad(f"plant {what!r}: {e}")
            continue
        stopped = []
        lanes_red = {}
        firsts = []
        for base, fmt, rnd in systems:
            text = ref_text(base, fmt)
            if rnd:
                text = with_round(text, rnd)
            tag = f"{base} {fmt}{' ' + rnd if rnd else ''}"
            try:
                on.compile_text(text, REFS[base], source=tag)
                stopped.append((tag, "accepted"))
            except on.InternalError as e:
                stopped.append((tag, "stopped"))
                print(f"        {tag}: {str(e)[:150]}")
            except Exception as e:                     # noqa: BLE001
                stopped.append((tag, f"{type(e).__name__}"))
            try:
                c = off.compile_text(text, REFS[base], source=tag)
            except Exception as e:                     # noqa: BLE001
                bad(f"plant {what!r}: with the check off {tag} does not "
                    f"compile ({type(e).__name__}: {e})")
                continue
            lanes = lanes_for(c.ir.fmt, c.ir.n_state, rng, REF_LANES[base],
                              BOX[base])
            failing, first, fok, _ref = compare(c, lanes, None, REFS[base])
            lanes_red[tag] = (len(failing), len(lanes), first, fok)
            if failing or not fok:
                firsts.append(first)
        visible = [t for t, (nf, _n, _f, fok) in lanes_red.items()
                   if nf or not fok]
        check(any(s == "stopped" for _t, s in stopped) and
              all(s in ("stopped", "accepted") for _t, s in stopped),
              f"plant {what!r}: the internal check stops it "
              f"({', '.join(f'{t}: {s}' for t, s in stopped)})")
        check(bool(visible), f"plant {what!r}: red on seq.py with the check "
              f"off - " + "; ".join(
                  f"{t}: {nf} of {n} lanes from step {f}"
                  + ("" if fok else ", FLAGS differ")
                  for t, (nf, n, f, fok) in lanes_red.items()),
              "no lane differs")
    leg_routine_plants(rng, work, len(PLANTS))


# The routines' plants (C4), each with a system and lanes on which seq.py can
# see it: a dropped or silenced raise only where the routine is the one source
# of a flag (x / 3 raises inexact and nothing else does), and a region
# dropped only where the routine is exact (roots of squares), so that its
# scaffolding's inexact is the one flag of the run.
_DIV3 = "system pd\nformat fp64\nstate x\nnext x = x / 3\nstep map\n"
_ROOTS = "system pr\nformat fp64\nstate x\nnext x = sqrt(x)\nstep map\n"
_DIV2 = ("system pl\nformat fp64\nstate x, y\nnext x = x / 3\n"
         "next y = y / 7\nstep map\n")       # no flag but the routines'
_LOOPS = ("callloop.py", "CALL_LOOP_ABOVE = 32768", "CALL_LOOP_ABOVE = 0")
ROUTINE_PLANTS = {
    "a routine's raise dropped": (
        [("regalloc.py",
          '        self.emit(Ins("raise", srcs=(("r", self.where[k]),), '
          'node=j, key=k))',
          "        pass  # PLANT: the raise dropped")],
        _DIV3, None, 2),
    "a routine's raise inside its quiet region": (
        [("regalloc.py",
          '            here = getattr(self.low.nodes[j], "kind", "lang") == '
          '"quiet"',
          '            here = getattr(self.low.nodes[j], "kind", "lang") in '
          '("quiet", "raise")')],
        _DIV3, None, 2),
    "a routine's quiet region dropped": (
        [("regalloc.py", "            if here != quiet:",
          "            if False:  # PLANT: no region")],
        _ROOTS, [[4], [9], [1 << 52], [25]], 1),
    "a routine reading another word": (
        [("inline.py", '("w", f.words[s[1]])',
          '("w", f.words["K_MAN" if s[1] == "K_SIGN" else s[1]])')],
        _DIV3, None, 2),
    # the call loop's (C4), its constant lowered in the copy so that two
    # divisions loop
    "a call loop's index not stepped past its record": (
        [_LOOPS, ("callloop.py",
                  '    code.append(("stx", reg[f.result]))\n'
                  '    code.append(("step",))\n',
                  '    code.append(("stx", reg[f.result]))\n')],
        _DIV2, None, 2),
    "a call loop's raise dropped": (
        [_LOOPS, ("callloop.py", '    code.append(("raise", reg[f.flags]))\n',
                  "")],
        _DIV2, None, 2),
    "a call loop one call short": (
        [_LOOPS, ("regalloc.py",
                  '        self.emit(Ins("repeat", slot=K, node=j))',
                  '        self.emit(Ins("repeat", slot=K - 1, node=j))')],
        _DIV2, None, 2),
}


def leg_routine_plants(rng, work, base_k):
    for k, (what, (edits, text, lanes, steps)) in enumerate(
            ROUTINE_PLANTS.items(), base_k):
        try:
            on = plant_copy(edits, f"{k}on", work)
            off = plant_copy(edits + [CHECK_OFF], f"{k}off", work)
        except AssertionError as e:
            bad(f"plant {what!r}: {e}")
            continue
        try:
            on.compile_text(text, steps, source=what)
            stopped = "accepted"
        except on.InternalError as e:
            stopped = "stopped"
            print(f"        {str(e)[:150]}")
        except Exception as e:                         # noqa: BLE001
            stopped = type(e).__name__
        check(stopped == "stopped", f"plant {what!r}: the internal check "
              f"stops it", f"it was {stopped}")
        try:
            c = off.compile_text(text, steps, source=what)
        except Exception as e:                         # noqa: BLE001
            bad(f"plant {what!r}: with the check off it does not compile "
                f"({type(e).__name__}: {e})")
            continue
        fmt = c.ir.fmt
        if lanes is None:
            states = lanes_for(fmt, c.ir.n_state, rng, 8)
        else:
            states = [[K.round_once(fmt, sf.RND_RNE, Fraction(v))[0]
                       for v in row] for row in lanes]
        failing, first, fok, ref = compare(c, states, None, steps)
        check(bool(failing) or not fok, f"plant {what!r}: red on seq.py with "
              f"the check off - {len(failing)} of {len(states)} lanes, FLAGS "
              f"{'equal' if fok else 'differ'} (the interpreter's "
              f"{ref.flags:#x})", "no lane differs and FLAGS agree")


# ---- J: every source the language accepts reads back -----------------------

# The property this leg exercises: every source the language accepts
# compiles, its canonical form read back to the same graph (cftc's internal
# check), or is refused by name - never an InternalError, which is the
# compiler's own defect. Two classes broke it until D2 (2026-10-01), each a
# cftc exit 70, and no generator above made either: a map naming h whose
# every use folds away (the challenge suite's finding 1), and a source whose
# canonical form nests past the parser's 100 (verifier-VL3). Here maps read
# h at random, folding forms among them, and chains sit at the limit,
# primal and with tangents; each source's outcome is decided by the
# generator's own knowledge of what it wrote, and the language must agree.

# Forms of h, each one constant meeting a run-time operation (or a map's
# output), of a class the generator knows: SCALED scales with h, so h is
# used; FOLDED reads h and folds to a constant that does not; NONLINEAR is
# refused h-nonlinear where it is made.
H_SCALED = ["h", "(2*h)", "(h/2)", "((h*h)/h)", "(-h)", "abs(h)",
            "(h - h + h)", "(3*h/7)", "copysign(h, 1)", "(h/(h/h))"]
H_FOLDED = ["(h - h)", "(h/h)", "((h*h)/(h*h))", "copysign(1, h)",
            "(abs(h)/h)", "(0*h)", "((2*h)/(4*h))", "(h/h - 1)",
            "copysign(2, -h)", "(h*h/(h*h) + 1)"]
H_NONLINEAR = ["(h*h)", "(1/h)", "(h + 1)", "min(h, 2*h)", "(h < 1)",
               "select(h < 0, h, 2*h)", "max(h, 1)", "(h == h)"]


def g_hmap(rng, k):
    """(text, outcome, step line): a map reading h at random through forms
    of known class, in its equations, a const and a let. The outcome its
    forms decide: h-nonlinear if any is nonlinear, else compiles if any
    scales, else unused - at the step line - if h is named at all."""
    names = ["x", "y", "z"][:rng.randint(1, 3)]
    lines = [f"system hm{k}",
             f"format {rng.choice(['fp32', 'fp64', 'fp128', 'fp256'])}",
             f"round {rng.choice(['rne', 'rtz', 'rdn', 'rup', 'rmm'])}",
             f"state {', '.join(names)}"]
    if rng.random() < 0.3:
        lines.append("tangent v")
    classes = []
    p_scaled = rng.choice([0.0, 0.15, 0.4])

    def form():
        r = rng.random()
        cls = "scaled" if r < p_scaled else \
            "nonlinear" if r > 0.9 else "folded"
        classes.append(cls)
        return rng.choice({"scaled": H_SCALED, "folded": H_FOLDED,
                           "nonlinear": H_NONLINEAR}[cls])
    extra = []
    if rng.random() < 0.4:
        lines.append(f"const c0 = {form()}")
        extra.append("c0")
    if rng.random() < 0.3:
        lines.append(f"let r0 = {form()}")
        extra.append("r0")
    for i, x in enumerate(names):
        other = names[(i + 1) % len(names)]
        shape = rng.randrange(6)
        e = (f"{x} * {form()} + {other}" if shape == 0 else
             f"fma({x}, {form()}, {other})" if shape == 1 else
             f"{x} + {form()}" if shape == 2 else
             form() if shape == 3 else            # a constant output
             f"{x} * {other}")                    # no h here
        if i == 0 and extra:
            # each a leaf of its own: two forms are never summed, which
            # would make another constant than the one the class names
            e = f"{e} + " + " + ".join(f"{x} * {u}" for u in extra)
        lines.append(f"next {x} = {e}")
    if not classes and rng.random() < 0.5:
        lines.append("step map")                  # a map without h
        return "\n".join(lines) + "\n", "compiles", None
    lines.append(f"step map, h = "
                 f"{rng.choice(['1/8', '0.01', '-1/3', '0x1p-4', '3/7'])}")
    if "nonlinear" in classes:
        return "\n".join(lines) + "\n", "h-nonlinear", None
    if "scaled" in classes:
        return "\n".join(lines) + "\n", "compiles", None
    return "\n".join(lines) + "\n", "unused", len(lines)


def nest(text):
    """How deep a text nests as the language's lexer counts it: each ( and
    [ a level, a comment skipped - this leg's own count."""
    depth = best = 0
    for ln in text.split("\n"):
        for c in ln.split(";", 1)[0]:
            if c in "([":
                depth += 1
                best = max(best, depth)
            elif c in ")]":
                depth = max(0, depth - 1)
    return best


def g_chain(kind, size, rng):
    """(text, the depth its canonical form nests): a source at the edge of
    the parser's 100, each kind's depth from the canonical form's own rules
    (docs/LANGUAGE.md, "The intention-out"): a negation used as a
    multiplicand is written (-a) * y, two levels a level; an unnamed
    product's tangent nests one fma a term; a min chain's tangent one level
    past the chain; euler's and stormer-verlet's step write a right-hand
    side inside the template's fma."""
    head = [f"system ch{size}",
            f"format {rng.choice(['fp32', 'fp64', 'fp128', 'fp256'])}",
            f"round {rng.choice(['rne', 'rtz', 'rdn', 'rup', 'rmm'])}"]

    def neg(k, var):
        e = var
        for _ in range(k):
            e = f"-({e}) * y"
        return e

    def calls(d, var):
        e = var
        for j in range(d):
            e = (f"abs({e})", f"min({e}, {var})", f"fma({e}, y, y)",
                 f"select(y < 0, {e}, y)")[j % 4] if var != "p" else \
                f"abs({e})"
        return e
    names = [f"x{i}" for i in range(size)]
    body = {
        "negation multiplicands": (["state x, y", f"next x = {neg(size, 'x')}",
                                    "next y = y", "step map"], 2 * size - 1),
        "negation multiplicands, a let": (
            ["state x, y", f"let r = {neg(size, 'x')}", "next x = r",
             "next y = y", "step map"], 2 * size - 1),
        "calls, a map": (["state x, y", f"next x = {calls(size, 'x')}",
                          "next y = y", "step map"], size),
        "calls, rk4": (["state x, y", f"d/dt x = {calls(size, 'x')}",
                        "d/dt y = -y", "step rk4, h = 1/8"], size),
        "calls, euler": (["state x, y", f"d/dt x = {calls(size, 'x')}",
                          "d/dt y = -y", "step euler, h = 1/8"], size + 1),
        "calls, stormer-verlet": (
            ["state x, p", f"d/dt x = {calls(size, 'p')}", "d/dt p = -x",
             "step stormer-verlet, h = 1/8, q = (x), p = (p)"], size + 1),
        "a product's tangent": (
            ["state " + ", ".join(names), "tangent v",
             "next x0 = " + " * ".join(names)]
            + [f"next {x} = {x}" for x in names[1:]] + ["step map"],
            size - 1),
        "a min chain's tangent": (
            ["state " + ", ".join(names), "tangent v",
             "next x0 = " + "min(" * (size - 1) + names[0] + "".join(
                 f", {x})" for x in names[1:])]
            + [f"next {x} = {x}" for x in names[1:]] + ["step map"], size),
        # a compound constant as an operand is written in parentheses,
        # x * (1/3): one level the source does not write (verifier-VD2)
        "a compound constant": (
            ["state x, y", "const k = 1/3",
             "next x = " + "abs(" * size + "x * k" + ")" * size,
             "next y = y", "step map"], size + 1),
    }[kind]
    return "\n".join(head + body[0]) + "\n", body[1]


# Each kind with the size at which its canonical form reaches 100: the
# boundary and one past it, and a size drawn near it.
CHAIN_LIMITS = {"negation multiplicands": 50,
                "negation multiplicands, a let": 50,
                "calls, a map": 100, "calls, rk4": 100, "calls, euler": 99,
                "calls, stormer-verlet": 99, "a product's tangent": 101,
                "a min chain's tangent": 100, "a compound constant": 99}


def g_letchain(kind, n, rng):
    """A chain of n lets read by name - `let a1 = x + y`, `let aj = a(j-1)
    + y`, through a call for "a call chain", in a cycle for "a cycle" -
    read by x's equation, in a system of `kind`."""
    tan = kind.endswith(" + v")
    base = kind[:-4] if tan else kind
    step = {"map": "step map", "a call chain, map": "step map",
            "a cycle": "step map", "euler": "step euler, h = 1/8",
            "rk4": "step rk4, h = 1/8",
            "stormer-verlet": "step stormer-verlet, h = 1/8, q = (x), "
                              "p = (y)"}[base]
    nxt = "abs(a{p}) + y" if base.startswith("a call") else "a{p} + y"
    first = {"stormer-verlet": "y + y", "a cycle": f"a{n} + y"}.get(base,
                                                                   "x + y")
    w = "next" if step == "step map" else "d/dt"
    lines = [f"system lc{n}",
             f"format {rng.choice(['fp32', 'fp64', 'fp128', 'fp256'])}",
             f"round {rng.choice(['rne', 'rtz', 'rdn', 'rup', 'rmm'])}",
             "state x, y"] + (["tangent v"] if tan else [])
    lines.append(f"let a1 = {first}")
    lines += [f"let a{j} = " + nxt.format(p=j - 1) for j in range(2, n + 1)]
    lines += [f"{w} x = a{n // 2 if base == 'a cycle' else n}",
              f"{w} y = " + ("-x" if base == "stormer-verlet" else "y"), step]
    return "\n".join(lines) + "\n"


# The let-chain class (verifier-VD2): where the read-back of the canonical
# form, or the checker, stopped at Python's own limit on 87c4df9 (rk4 read
# back to 80 lets, stormer-verlet 122, rk4 + v 64, stormer-verlet + v 97,
# euler + v and map + v 197, a chain through a call 164 on Python 3.12),
# one past each; far past them; and a cycle longer than that limit. Each
# compiles, its canonical form read back - the cycle is refused by name.
LET_CHAINS = [("rk4", 81), ("stormer-verlet", 123), ("rk4 + v", 65),
              ("stormer-verlet + v", 98), ("euler + v", 198),
              ("map + v", 198), ("a call chain, map", 165), ("map", 1500),
              ("rk4", 600), ("rk4 + v", 300), ("a cycle", 600)]


def leg_readback(count, rng):
    section(f"J. every source the language accepts reads back: {count} maps "
            f"reading h at random, chains at the parser's limit, and chains "
            f"of lets past Python's")
    t0 = time.perf_counter()
    tally = {}
    internal, wrong = [], []

    def run(text, want, line, what):
        """The compiler's outcome against `want` (compiles, or a refusal's
        name and line): an InternalError is always a failure."""
        try:
            c = cftc.compile_text(text, 2, target="sw:4096", source=what,
                                  stem="j")
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            if e.name != want or (line is not None and e.line != line):
                wrong.append(f"{what}: refused {e.name} at line {e.line} "
                             f"where {want}"
                             + (f" at line {line}" if line else "")
                             + f" is due ({e.sentence[:100]})")
            return e
        except cftc.InternalError as e:
            tally["internal error"] = tally.get("internal error", 0) + 1
            internal.append(f"{what}: internal error (exit 70), where {want} "
                            f"is due: {str(e)[:150]}")
            return None
        tally["compiled"] = tally.get("compiled", 0) + 1
        if want != "compiles":
            wrong.append(f"{what}: compiled where {want} is due")
        return c
    for k in range(count):
        text, want, line = g_hmap(random.Random(f"lang readback {k}"), k)
        run(text, want, line, f"h-map {k}")
    hmaps = dict(tally)
    chains = 0
    for kind, limit in CHAIN_LIMITS.items():
        near = limit + rng.choice([-4, -2, 2, 3])
        for size in (limit, limit + 1, near):
            text, depth = g_chain(kind, size, rng)
            want = "compiles" if depth <= 100 else "too-deep"
            what = f"{kind}, {size}: canonical {depth} deep"
            out = run(text, want, None, what)
            chains += 1
            # a source past 100 itself is the parser's, in its own words
            if isinstance(out, lang.Refusal) and out.name == "too-deep" and \
                    nest(text) <= 100 and f" {depth} deep," not in out.sentence:
                wrong.append(f"{what}: the sentence names another depth: "
                             f"{out.sentence[:120]}")
            elif out is not None and not isinstance(out, lang.Refusal) and \
                    nest(out.canonical) != depth:
                wrong.append(f"{what}: the canonical form is "
                             f"{nest(out.canonical)} deep")
    for kind, n in LET_CHAINS:
        run(g_letchain(kind, n, rng), "cycle" if kind == "a cycle" else
            "compiles", None, f"lets, {kind}, {n}")
        chains += 1
    chain_tally = {n: tally[n] - hmaps.get(n, 0) for n in tally
                   if tally[n] - hmaps.get(n, 0)}
    for f in (internal + wrong)[:12]:
        print(f"        {f}")
    print(f"  maps reading h: {dict(sorted(hmaps.items()))}")
    print(f"  chains: {dict(sorted(chain_tally.items()))}")
    check(not internal, f"no InternalError: {count} maps reading h at "
          f"random and {chains} chains - at the parser's limit, and chains "
          f"of lets past Python's - each compiled with its canonical form "
          f"read back or refused by name",
          f"{len(internal)} stopped the compiler with an internal error, "
          f"exit 70")
    check(not wrong, f"each outcome the one its source decides - h folded "
          f"away `unused` at the step line, a nonlinear form h-nonlinear, a "
          f"canonical form past 100 `too-deep` naming its depth, every "
          f"accepted chain's canonical form the depth its kind gives, every "
          f"chain of lets compiled and a cycle of them `cycle` "
          f"({time.perf_counter() - t0:.1f} s)",
          f"{len(wrong)} otherwise")


# ---- K: run-time division and square root (L4, C4) -----------------------------

# The language has `a / b` and `sqrt(a)` with operands that are not constants
# (the nodes div and sqrt, softfloat's div and sqrt under the program's
# attribute, L4), and the compiler carries each as a routine inlined where it
# stands (C4): an image holding one needs revision 8's flag control, which
# the software targets and revision 8's publish and revision 7's do not. D2's
# rule holds: every source the language accepts compiles or is refused by
# name.

ROUTINE_TARGETS = ["sw", "sw:4096", "sw:32768", "u50-rev7", "u50-rev7-quad",
                   "u50-round2", "open-core"]
SW_TARGETS = ("sw", "sw:4096", "sw:32768")
REV7_TARGETS = ("u50-rev7", "u50-rev7-quad", "u50-round2", "open-core")
# the built-in targets that publish flag control, in the table's order: an
# image with a routine that fits their capacities lists these in its
# manifest's accepted_by (built in at cftc's output version 5)
FLAG_TARGETS = ["sw", "u50-rev8", "u50-rev8-quad", "u50-rev8-deep"]


def compare_routine(c, states, tans, top):
    """compare() with tangent vectors as well: seq.py on the image at 1, 2,
    5 and `top` steps against lang.run's checkpoints - states, tangents and
    FLAGS - under the marked-lane rule. -> (failing lanes, first step a lane
    or FLAGS parts, flags equal everywhere, the definition)."""
    v = rule_compare(c, states, top, tans=tans, width=c.ir.n_state)
    return v.failing, v.first, v.flags_ok, v.ref


def g_routine_expr(rng, states, ops, depth):
    """An expression that divides or takes a square root at run time: each
    form reads a state component (one of `states`) where it divides or
    roots, so the operation is a node however the rest folds."""
    x = rng.choice(states)
    lit = rng.choice(LITS[:6])
    form = rng.randrange(7)
    if form == 0:
        return f"({x} + {g_expr(rng, ops, depth)}) / ({x} * {x} + {lit})"
    if form == 1:
        return f"sqrt(abs({x}) + {lit})"
    if form == 2:
        return f"{x} / {rng.choice(LITS)}"
    if form == 3:
        return f"{lit} / ({x} * {x} + 1)"
    if form == 4:
        return f"{lit} / {x}"                     # a zero lane divides by 0
    if form == 5:
        return f"sqrt({x})"                       # a negative lane: invalid
    return f"fma({x}, {g_expr(rng, ops, depth)}, 1) / sqrt({x} * {x} + 1)"


def g_routine(rng, k):
    """(text, line): a system the language takes that divides or takes a
    root at run time somewhere - an equation, or a let one reads - under
    any integrator, format and attribute, with or without tangent vectors;
    and the first line holding one, by the generator's own count, which
    the compiler's refusal must name."""
    shape = rng.choice(["map", "maph", "rk4", "euler", "sv"])
    lines = [f"system dv{k}",
             f"format {rng.choice(['fp32', 'fp64', 'fp128', 'fp256'])}",
             f"round {rng.choice(['rne', 'rtz', 'rdn', 'rup', 'rmm'])}"]
    sv = shape == "sv"
    comps = ["q0", "q1", "m0", "m1"] if sv else ["x", "y", "z"]
    lines.append("state " + ", ".join(comps))
    if rng.random() < 0.4:
        lines.append("tangent v" + (", w" if rng.random() < 0.3 else ""))
    params = [f"p{i}" for i in range(rng.randint(0, 2))]
    if params:
        lines.append("param " + ", ".join(f"{p} = {rng.choice(LITS)}"
                                          for p in params))
    marked = []
    extra = list(params)
    if not sv and rng.random() < 0.4:
        lines.append(f"let r = {g_routine_expr(rng, comps, comps, 1)}")
        marked.append(len(lines))
        extra.append("r")
    if sv:
        # a position's right-hand side reads momenta, a momentum's positions
        reads = {"q0": ["m0", "m1"], "q1": ["m0", "m1"],
                 "m0": ["q0", "q1"], "m1": ["q0", "q1"]}
        word = "d/dt"
    else:
        reads = {c: comps + (["h"] if shape == "maph" else [])
                 for c in comps}
        word = "next" if shape.startswith("map") else "d/dt"
    pick = rng.randrange(len(comps)) if not marked or rng.random() < 0.5 \
        else None
    first_eq = len(lines) + 1
    for i, c in enumerate(comps):
        states = [s for s in reads[c] if s != "h"]
        if i == pick or rng.random() < 0.25:
            rhs = g_routine_expr(rng, states, reads[c], 1)
            marked.append(len(lines) + 1)
        else:
            rhs = g_expr(rng, reads[c], 2)
        lines.append(f"{word} {c} = {rhs}")
    used = extra + (["h"] if shape == "maph" else [])
    if used:
        lines[first_eq - 1] += " + " + " + ".join(used)
    lines.append({"map": "step map", "maph": "step map, h = 1/8",
                  "rk4": "step rk4, h = 1/8", "euler": "step euler, h = 1/8",
                  "sv": "step stormer-verlet, h = 1/8, q = (q0, q1), "
                        "p = (m0, m1)"}[shape])
    return "\n".join(lines) + "\n", min(marked)


def moved_up(canon):
    """A canonical form with its written-out step (the step line and its
    expansion block) and its tangent lines moved above its equations and
    lets - statements may come in any order, so it is the same system -
    and the first line in it that holds a run-time division or root. The
    canonical form writes a run-time division ` / ` and a root `sqrt(`,
    where a constant's spelling has no space (1/3, h/2, 2*h/3), so a line's
    code (before any `;`) shows which it holds. -> (text, that line, its
    kind: equation, tangent or block)."""
    head, step, tangent, primal = [], [], [], []
    block = False
    for ln in canon.split("\n")[:-1]:
        code = ln.split(";", 1)[0].strip()
        if block or code == "expansion" or code.startswith("step "):
            step.append(ln)
            block = (block or code == "expansion") and code != "end"
        elif re.match(r"(let|next|d/dt) [A-Za-z_]\w*\.", code):
            tangent.append(ln)
        elif code.startswith(("let ", "next ", "d/dt ")):
            primal.append(ln)
        else:
            head.append(ln)
    lines = head + step + tangent + primal
    for k, ln in enumerate(lines, 1):
        code = ln.split(";", 1)[0]
        if " / " in code or "sqrt(" in code:
            kind = "block" if k <= len(head) + len(step) else \
                "tangent" if k <= len(head) + len(step) + len(tangent) \
                else "equation"
            return "\n".join(lines) + "\n", k, kind
    return "\n".join(lines) + "\n", None, None


def _routine_flags():
    """Every flag of both operations through the interpreter at every
    format: one system a format, a lane a case, each lane's result and
    flags softfloat's, the union all five for div and invalid with inexact
    for sqrt. -> the failures."""
    out = []
    for fmtname in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[fmtname]

        def b(v):
            return K.round_once(fmt, sf.RND_RNE, Fraction(v))[0]
        inf, snan = sf.inf_bits(fmt), sf.snan_bits(fmt, 1)
        mx, mn = sf.max_normal_bits(fmt), sf.min_normal_bits(fmt)
        g = lang.compile_text(f"system f\nformat {fmtname}\nstate x, y\n"
                              f"next x = x / y\nnext y = sqrt(y)\n"
                              f"step map\n").graph
        lanes = [[b(6), b(3)], [b(1), b(3)], [b(1), 0], [0, b(-1)],
                 [inf, inf], [snan, b(4)], [mx, mn], [mn, mx], [b(2), snan]]
        r = lang.run(g, lanes, 1)
        union = 0
        for lane, st in zip(lanes, r.states):
            q, fq = sf.div(fmt, lane[0], lane[1], sf.RND_RNE)
            s, fs = sf.sqrt(fmt, lane[1], sf.RND_RNE)
            alone = lang.run(g, [lane], 1)
            if st != [q, s] or alone.flags != fq | fs:
                out.append(f"{fmtname} {[hex(v) for v in lane]}: "
                           f"{[hex(v) for v in st]} FLAGS {alone.flags:#x}, "
                           f"softfloat's {hex(q)} {hex(s)} {fq | fs:#x}")
            union |= fq | fs
        if r.flags != union or union != 0x1f:
            out.append(f"{fmtname}: FLAGS {r.flags:#x}, the lanes' OR "
                       f"{union:#x}, every flag 0x1f")
    return out


def leg_routines(count, rng):
    section(f"K. run-time division and square root (L4, C4): every flag of "
            f"both through the interpreter at every format; Kepler's "
            f"reference at every format and attribute; {count} generated "
            f"sources that divide or take a root, compiled for the software "
            f"targets and run against the interpreter, and refused "
            f"`target-feature` on revision 7's")
    t0 = time.perf_counter()
    fails = _routine_flags()
    check(not fails, "every flag of div and sqrt at fp32, fp64, fp128 and "
          "fp256: each lane's result and FLAGS softfloat's, div's five and "
          "sqrt's invalid and inexact among them", "; ".join(fails[:4]))
    # -- the reference that divides: every format, every attribute, pinned
    for base, steps in ROUTINE_REFS.items():
        for fmt in ("fp32", "fp64", "fp128", "fp256"):
            c = ref_compile(base, fmt, steps=steps)
            n = c.ir.n_state
            lanes = lanes_for(c.ir.fmt, n, rng, ROUTINE_REF_LANES[base],
                              BOX[base])
            lanes += special_lanes(c.ir.fmt, n, lanes[0], rng)
            lanes.append([0] * n)               # 0/0 and the root of 0
            failing, first, fok, ref = compare(c, lanes, None, steps)
            rcover(c, ref.flags)
            check(not failing and fok and "FLAG_CONTROL" in c.features and
                  c.accepted_by == FLAG_TARGETS,
                  f"{base} {fmt}: {len(lanes)} lanes at 1, 2, 5 and {steps} "
                  f"steps equal the interpreter, FLAGS {ref.flags:#x} "
                  f"included; its {c.manifest['routines']['calls']} routines "
                  f"need FLAG_CONTROL, and of the built-in targets "
                  f"{', '.join(c.accepted_by)} take it - those that "
                  f"publish the bit",
                  f"{len(failing)} lanes differ from step {first}, FLAGS "
                  f"{'equal' if fok else 'differ'}")
            if fmt == "fp64":
                got = compiled_costs(c)
                row = (got["instructions"], got["alu"], got["loads"],
                       got["stores"], got["registers"], got["slots"],
                       got["bank"])
                check(row == PINNED[base], f"{base}: the compiled costs are "
                      f"the pinned {PINNED[base]}", f"measured {row}")
        for rnd in ("rtz", "rdn", "rup", "rmm"):
            c = ref_compile(base, "fp64", rnd, steps=steps)
            lanes = lanes_for(c.ir.fmt, c.ir.n_state, rng, 8, BOX[base])
            lanes += special_lanes(c.ir.fmt, c.ir.n_state, lanes[0], rng)
            failing, first, fok, ref = compare(c, lanes, None, steps)
            rcover(c, ref.flags)
            check(not failing and fok, f"{base} fp64 {rnd}: {len(lanes)} "
                  f"lanes equal the interpreter, FLAGS included - the "
                  f"routines specialised at {rnd}",
                  f"{len(failing)} lanes differ from step {first}")
    # -- generated sources: compiled, run, and refused by name
    tally, wrong, internal, kinds = {}, [], [], {}
    flags = held = 0
    cli = []
    for k in range(count):
        text, _line = g_routine(random.Random(f"lang routines {k}"), k)
        try:
            g = lang.compile_text(text, f"routine-{k}").graph
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            if e.name not in ARTIFACTS:
                wrong.append(f"routine {k}: the language refused {e}")
            continue
        if not {"div", "sqrt"} & set(g.op_counts("step")):
            wrong.append(f"routine {k}: no division or root in its step")
        canon = lang.render_canonical(g)
        if lang.compile_text(canon, "canonical").graph.to_bytes() != \
                g.to_bytes():
            wrong.append(f"routine {k}: its canonical form reads back as "
                         f"another graph")
        lang.render_math(g)
        try:
            images = {}
            for t in SW_TARGETS:
                c = cftc.compile_text(text, 5, target=t,
                                      source=f"routine-{k}", stem="k")
                images[t] = c.image
            if len(set(images.values())) != 1:
                wrong.append(f"routine {k}: the software targets' images "
                             f"differ")
            # the canonical form, its written-out step and its tangent lines
            # moved above its equations: the same graph, so the same image
            text2, _l2, kind2 = moved_up(canon)
            c2 = cftc.compile_text(text2, 5, source=f"routine-{k}-moved",
                                   stem="k")
            if c2.image != c.image:
                wrong.append(f"routine {k}, moved up: another image")
            else:
                kinds[kind2] = kinds.get(kind2, 0) + 1
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            wrong.append(f"routine {k}: refused {e.name} on the software "
                         f"targets: {e.sentence[:100]}")
            continue
        except cftc.InternalError as e:
            internal.append(f"routine {k}: internal error (exit 70): "
                            f"{str(e)[:120]}")
            continue
        fmt = g.fmt
        lanes = lanes_for(fmt, g.n_state, rng, 3)
        lanes += special_lanes(fmt, g.n_state, lanes[0], rng)
        lanes.append([0] * g.n_state)
        tans = None
        if g.tangent:
            tans = [[lanes_for(fmt, g.n_state, rng, 1)[0] for _ in g.tangent]
                    for _ in lanes]
        failing, first, fok, ref = compare_routine(c, lanes, tans, 5)
        rcover(c, ref.flags)
        flags |= ref.flags
        if failing or not fok:
            wrong.append(f"routine {k}: {len(failing)} lanes differ from "
                         f"step {first}, FLAGS {'equal' if fok else 'differ'}")
        else:
            held += 1
        for t in REV7_TARGETS:
            try:
                cftc.compile_text(text, 5, target=t, source=f"routine-{k}",
                                  stem="k")
                wrong.append(f"routine {k} on {t}: compiled")
            except lang.Refusal as e:
                tally[e.name] = tally.get(e.name, 0) + 1
                if e.name != "target-feature" or \
                        "FLAG_CONTROL (CAPS2[14])" not in e.sentence:
                    wrong.append(f"routine {k} on {t}: refused {e.name}, "
                                 f"where target-feature naming FLAG_CONTROL "
                                 f"is due ({e.sentence[:80]})")
            except cftc.InternalError as e:
                internal.append(f"routine {k} on {t}: internal error (exit "
                                f"70): {str(e)[:120]}")
        if len(cli) < 3:
            cli.append((k, text))
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    with tempfile.TemporaryDirectory() as tmp:
        for k, text in cli:
            src = Path(tmp) / f"routine{k}.cftl"
            src.write_bytes(text.encode("ascii"))
            out = Path(tmp) / f"sw{k}"
            p = subprocess.run(py + [str(src), "--steps", "2", "--out",
                                     str(out)], capture_output=True,
                               text=True)
            cfta = out / f"routine{k}.cfta"
            if p.returncode != 0 or not cfta.is_file() or \
                    "\n  quiet " not in cfta.read_text(encoding="ascii"):
                wrong.append(f"routine {k} through the command line on sw: "
                             f"rc {p.returncode}, {p.stderr.strip()[:120]}")
            out = Path(tmp) / f"quad{k}"
            p = subprocess.run(py + [str(src), "--steps", "2", "--target",
                                     "u50-rev7-quad", "--out", str(out)],
                               capture_output=True, text=True)
            if p.returncode != 3 or not p.stderr.startswith(
                    "cftc: refused target-feature: ") or out.exists():
                wrong.append(f"routine {k} through the command line on "
                             f"u50-rev7-quad: rc {p.returncode}, "
                             f"{p.stderr.strip()[:120]}")
    for f in (internal + wrong)[:10]:
        print(f"        {f}")
    print(f"  outcomes: {dict(sorted(tally.items()))}")
    print(f"  moved up, the same image, by the kind of the first line "
          f"holding a division or root: {dict(sorted(kinds.items()))}")
    print(f"  FLAGS over the {held} images held: {flags:#x}")
    check(not internal, f"no InternalError: {count} generated sources that "
          f"divide or take a root, on {len(ROUTINE_TARGETS)} targets each, "
          f"and their canonical forms moved up",
          f"{len(internal)} stopped the compiler with an internal error, "
          f"exit 70")
    check(not wrong and held >= count // 2 and
          {"block", "tangent", "equation"} <= set(kinds),
          f"{held} sources accepted by the language read back, compiled for "
          f"the software targets - one image for the three - and run on "
          f"seq.py equal to the interpreter at 1, 2 and 5 steps, states, "
          f"tangents and FLAGS, on lanes that overflow, hold a signalling "
          f"NaN, hold subnormals and hold zeros; each refused "
          f"`target-feature`, naming FLAG_CONTROL, on revision 7's "
          f"{len(REV7_TARGETS)} targets, and {len(cli)} through the command "
          f"line (exit 0 on sw with the text's regions, exit 3 on "
          f"u50-rev7-quad, nothing written); each one's canonical form with "
          f"its written-out step and tangent lines moved above its "
          f"equations the same image - its first line holding one an "
          f"expansion block's {kinds.get('block', 0)} times, a written "
          f"tangent's {kinds.get('tangent', 0)}, an equation's or a let's "
          f"{kinds.get('equation', 0)} ({time.perf_counter() - t0:.1f} s)",
          f"{len(wrong)} otherwise")


def leg_routine_pools():
    section("K2. the routines on their full pools (C4): each of the 40 "
            "fragments - division and root, four formats, five attributes - "
            "softfloat's bits and each lane's own flag word")
    sys.path.insert(0, str(ROOT / "python" / "tests"))
    try:
        from routine_pools import div_pairs, sqrt_xs
    finally:
        sys.path.remove(str(ROOT / "python" / "tests"))
    t0 = time.perf_counter()
    total, bad_cases = 0, []
    for fmt in ("fp32", "fp64", "fp128", "fp256"):
        F = FORMATS[fmt]
        pairs, xs = div_pairs(F, light=False), sqrt_xs(F, light=False)
        for rnd in range(5):
            for op, ls in (("div", pairs), ("sqrt", xs)):
                f = R.fragment(op, F, rnd)
                if op == "div":
                    outs, words = R.run(f, [p[0] for p in ls],
                                        [p[1] for p in ls])
                else:
                    outs, words = R.run(f, ls)
                for i, x in enumerate(ls):
                    args = x if op == "div" else (x,)
                    if (outs[i], words[i]) != R.GOLDEN[op](F, *args, rnd):
                        bad_cases.append(f"{op} {fmt} rnd {rnd} {args}")
                total += len(ls)
    check(not bad_cases, f"{total:,} lanes over the 40 fragments, each "
          f"softfloat's result and flag word ({time.perf_counter() - t0:.0f} "
          f"s)", f"{len(bad_cases)} wrong, first {bad_cases[:2]}")


# ---- L: the call loop (C4) ---------------------------------------------------

KEPLER_RK4 = ("system kepler\nformat {fmt}\nstate x, y, px, py\n"
              "let r2 = fma(x, x, y * y)\nlet r3 = r2 * sqrt(r2)\n"
              "d/dt x = px\nd/dt y = py\nd/dt px = -(x / r3)\n"
              "d/dt py = -(y / r3)\nstep rk4, h = 1/100\n")


def nbody_source(n, fmt="fp64"):
    """Planar N bodies, unit masses and G = 1, under rk4: each pair's
    1 / (s sqrt(s)) - a root and a division of 1 - and the accelerations
    as fma chains over the pairs."""
    xs, ys = [f"x{i}" for i in range(n)], [f"y{i}" for i in range(n)]
    us, vs = [f"u{i}" for i in range(n)], [f"v{i}" for i in range(n)]
    lines = [f"system nbody{n}", f"format {fmt}",
             "state " + ", ".join(xs + ys + us + vs)]
    for i in range(n):
        for j in range(i + 1, n):
            p = f"{i}_{j}"
            lines += [f"let dx{p} = x{j} - x{i}", f"let dy{p} = y{j} - y{i}",
                      f"let s{p} = fma(dx{p}, dx{p}, dy{p} * dy{p})",
                      f"let k{p} = 1 / (s{p} * sqrt(s{p}))"]
    for i in range(n):
        lines += [f"d/dt x{i} = u{i}", f"d/dt y{i} = v{i}"]
    for i in range(n):
        for comp, tgt in (("x", "u"), ("y", "v")):
            expr = None
            for j in range(n):
                if j == i:
                    continue
                p = f"{min(i, j)}_{max(i, j)}"
                kk, dd = f"k{p}", f"d{comp}{p}"
                if expr is None:
                    expr = f"{kk} * {dd}" if i < j else f"-({kk} * {dd})"
                else:
                    expr = (f"fma({kk}, {dd}, {expr})" if i < j
                            else f"fma(-{kk}, {dd}, {expr})")
            lines.append(f"d/dt {tgt}{i} = {expr}")
    lines.append("step rk4, h = 1/100")
    return "\n".join(lines) + "\n"


def leg_call_loops(rng, segrun=None, audit=None, work=None):
    from cftc import callloop
    above = callloop.CALL_LOOP_ABOVE
    section(f"L. the call loop (C4): a step whose routines, inlined, would "
            f"pass {above:,} instructions runs batches of them in loops - "
            f"eight bodies under rk4 at the constant itself; Kepler under "
            f"rk4 with it lowered, every batch looped and the largest alone")
    t0 = time.perf_counter()
    c = cftc.compile_text(nbody_source(8), 2, source="nbody8", stem="nbody8")
    p = c.program
    looped = [(b.op, b.depth, len(b.calls)) for b in c.looped]
    check(looped == [("div", 2, 56)] and len(p.body) + 1 <= above and
          c.accepted_by == FLAG_TARGETS and p.slots_used <= 256,
          f"N = 8: the step, its 224 routines inlined, passes {above:,}; "
          f"its largest batch - the first two stages' 56 divisions of 1 - "
          f"looped alone brings it to {len(p.body) + 1:,} written, "
          f"{p.executed():,} run, {p.slots_used} scratch slots, accepted by "
          f"{', '.join(c.accepted_by)} ({time.perf_counter() - t0:.0f} s)",
          f"looped {looped}, {len(p.body) + 1:,} written, "
          f"{p.slots_used} slots, accepted by {c.accepted_by}")
    g = c.ir
    box = [(-1, 1)] * (2 * 8) + [(-0.5, 0.5)] * (2 * 8)
    lanes = lanes_for(g.fmt, g.n_state, rng, 3, box)
    lanes += special_lanes(g.fmt, g.n_state, lanes[0], rng)
    lanes.append([0] * g.n_state)
    t1 = time.perf_counter()
    failing, first, fok, ref = compare_routine(c, lanes, None, 2)
    rcover(c, ref.flags)
    check(not failing and fok, f"N = 8: {len(lanes)} lanes at 1 and 2 steps "
          f"equal the interpreter, FLAGS {ref.flags:#x} included - lanes "
          f"that overflow, hold a signalling NaN, hold subnormals and hold "
          f"zeros (0/0) among them ({time.perf_counter() - t1:.0f} s)",
          f"{len(failing)} lanes differ from step {first}, FLAGS "
          f"{'equal' if fok else 'differ'}")
    for fmt in ("fp64", "fp256"):
        text = KEPLER_RK4.format(fmt=fmt)
        size = len(cftc.compile_text(text, 5).program.body) + 1
        try:
            for low_to, what in ((0, "every batch"),
                                 (size - 1, "the largest batch alone")):
                callloop.CALL_LOOP_ABOVE = low_to
                c = cftc.compile_text(text, 5, source=f"kepler-rk4-{fmt}")
                looped = sorted((b.op, b.depth, len(b.calls))
                                for b in c.looped)
                want = ([("div", 2, 4), ("div", 4, 4), ("sqrt", 1, 2),
                         ("sqrt", 3, 2)] if low_to == 0 else [("div", 2, 4)])
                lanes = lanes_for(c.ir.fmt, 4, rng, 6, BOX["kepler-sv"])
                lanes += special_lanes(c.ir.fmt, 4, lanes[0], rng)
                lanes.append([0] * 4)
                failing, first, fok, ref = compare_routine(c, lanes, None, 5)
                rcover(c, ref.flags)
                check(looped == want and not failing and fok,
                      f"Kepler under rk4 at {fmt}, the constant at "
                      f"{low_to:,} ({what}): {len(lanes)} lanes at 1, 2 and "
                      f"5 steps equal the interpreter, FLAGS {ref.flags:#x} "
                      f"included",
                      f"looped {looped}; {len(failing)} lanes differ from "
                      f"step {first}, FLAGS {'equal' if fok else 'differ'}")
                if fmt == "fp64" and low_to == 0:
                    every = c
        finally:
            callloop.CALL_LOOP_ABOVE = above
    # libcft's software backend runs the loops as seq.py does: the image
    # with every batch looped, certified and audited by both auditors
    if not segrun or not Path(segrun).is_file():
        skip("L: cft-segrun's certificate of a looped image",
             f"no cft-segrun at {segrun!r} (the stage builds it)")
        return
    have_audit = bool(audit) and Path(audit).is_file()
    if not have_audit:
        skip("L: cft-audit on the looped image's certificate",
             f"no cft-audit at {audit!r} (the stage builds it)")
    certify(every, "kepler-rk4-looped-fp64", Path(segrun).resolve(),
            Path(audit).resolve() if have_audit else None, rng, work)


# ---- O: the marked-lane rule's controls (M1's build, item 5) ----------------------
#
# A check that cannot fail is a wrong answer, and the rule above can fail only
# on a run that breaks it - which the legs' real images never do, once they are
# right. So its controls are real runs with a fault planted in a copy of the
# run (a Result's values, bytes, FLAGS or STATUS), each judged by rule_compare
# itself and required to fail the check the fault breaks and no other, and the
# unplanted runs required to pass. The subject is the golden corpus's markstep
# (certificates/programs/markstep-fp64.cfta; its source, markstep-fp64.cftl,
# is the definition): a hand-written image that marks lanes on purpose without
# the math library's generator, so these controls need no mpmath and run on
# every host. A mutation of the rule in a copy of this file - the replay
# applied to every lane, a marked lane's guess required, the STATUS[6] check
# removed - turns the control that holds that check red, by name (the
# parcel's plants, docs/VALIDATION.md).

CERT_PROGRAMS = ROOT / "certificates" / "programs"
# markstep's lanes (k, x): the counter k decides where its test marks
MARKSTEP_LANES = (("7", "0.3333"),      # marked at step 1, a wrong last bit
                  ("106", "0.5"),       # marked at step 1, its value right
                  ("50", "0.2"),        # never marked
                  ("3", "0.7"),         # marked at step 5 only (k = 7 there)
                  ("20", None))         # never marked; x the least subnormal
MARKSTEP_TOP = 8


def markstep_subject():
    """markstep as a subject of the rule, in the shape rule_compare reads a
    compilation: its source's graph, its image and bank (the source's a and
    b rounded once, 1, 7, 106 and the raw words 1, 0x81 - invalid with the
    mark - and 0), and the layout of two values a lane."""
    import types
    f64 = FORMATS["fp64"]

    def d64(text):
        return K.round_once(f64, sf.RND_RNE, Fraction(text))[0]
    src = (CERT_PROGRAMS / "markstep-fp64.cftl").read_bytes().decode("ascii")
    g = lang.compile_text(src, "markstep").graph
    # the file's bytes, not a text-mode read (docs/PROGRAMS.md, on asm.py)
    img = asm.assemble((CERT_PROGRAMS / "markstep-fp64.cfta").read_bytes(),
                       "markstep-fp64")
    pa = {p[0]: p[2] for p in g.param}
    bank = [pa["a"], pa["b"], d64("1"), d64("7"), d64("106"), 1, 0x81, 0]
    c = types.SimpleNamespace(
        graph=g, image=img, depth=seq.SCRATCH_D,
        ir=types.SimpleNamespace(m=2, n_state=2, n_primal=2, T=0, lane=[]),
        lowered=types.SimpleNamespace(bank_values=lambda: list(bank)),
        scratch_block=lambda states, lp=None, tans=None:
        [v for st in states for v in st])
    lanes = [[d64(k), sf.min_subnormal_bits(f64) if x is None else d64(x)]
             for k, x in MARKSTEP_LANES]
    return c, lanes


class Fixture:
    """An image's real runs at the rule's checkpoints, and verdicts on copies
    of them with a fault planted: plant(step, run) edits the copy of the run
    at that checkpoint."""

    def __init__(self, c, states, top, tans=None, lane_params=None,
                 width=None):
        self.c, self.states, self.top, self.tans = c, states, top, tans
        self.lane_params, self.width = lane_params, width
        block = c.scratch_block(states, lane_params, tans)
        self.real = {s: run_image(image_at(c.image, s), c, states,
                                  lane_params, None, block=block)
                     for s in checkpoints(top)}
        self.ref = Ref(c.graph, states, top, checkpoints(top), lane_params,
                       tans)

    def verdict(self, plant=None):
        import types

        def runner(s):
            r = self.real[s]
            q = types.SimpleNamespace(scratch_out=list(r.scratch_out),
                                      lane_flags=list(r.lane_flags),
                                      flags=r.flags, status=r.status)
            if plant is not None:
                plant(s, q)
            return q
        return rule_compare(self.c, self.states, self.top, tans=self.tans,
                            lane_params=self.lane_params, width=self.width,
                            runner=runner, ref=self.ref, tally=False)


def at_step(step, *edits, onward=False):
    """A plant: each edit(run) at one checkpoint, or at it and every later
    one (a mark planted on a lane persists, as a real mark does)."""
    def plant(s, q):
        if s == step or (onward and s > step):
            for edit in edits:
                edit(q)
    return plant


def value_edit(k, m, slot, bit=0):
    """Flip one bit of lane k's value at `slot` of its m."""
    def edit(q):
        q.scratch_out[k * m + slot] ^= 1 << bit
    return edit


def byte_edit(k, mask=0, clear=0):
    """Set and clear bits of lane k's byte."""
    def edit(q):
        q.lane_flags[k] = (q.lane_flags[k] | mask) & ~clear
    return edit


def flags_edit(mask=0, clear=0):
    def edit(q):
        q.flags = (q.flags | mask) & ~clear
    return edit


def status_edit(mask=0, clear=0):
    def edit(q):
        q.status = (q.status | mask) & ~clear
    return edit


def leg_rule():
    section("O. the marked-lane rule's controls (M1's build, item 5): "
            "markstep, a hand-written image that marks lanes on purpose, run "
            "as it is and with a fault planted in a copy of its runs")
    fx = Fixture(*markstep_subject(), MARKSTEP_TOP)
    m = 2                               # values a lane: k, x

    def value(k, bit=0):
        return value_edit(k, m, 1, bit)
    byte, flags, status = byte_edit, flags_edit, status_edit

    base = fx.verdict()
    per = {s: cp for s, cp in base.per.items()}
    print(f"  markstep at 1, 2, 5 and 8 steps: lanes marked "
          f"{ {s: cp.marked for s, cp in per.items()} }; guesses wrong in "
          f"their values {  {s: cp.wrong for s, cp in per.items()} }, in "
          f"their flags {  {s: cp.wrong_flags for s, cp in per.items()} }")
    # O1: the unplanted run, a marking image
    check(not base.failing and base.flags_ok and base.first is None and
          per[1].marked == [0, 1] and per[2].marked == [0, 1] and
          per[5].marked == [0, 1, 3] and per[8].marked == [0, 1, 3] and
          per[1].wrong == [0] and per[2].wrong == [0] and
          3 in per[5].wrong and per[1].wrong_flags == [0, 1],
          "O1. markstep as it is: lanes k = 7 (a wrong last bit) and k = 106 "
          "(its value right) marked at step 1, k = 3 only from step 5; each "
          "marked lane replayed - a guess wrong in its value counted, and "
          "both guesses raising invalid, which the definition does not, "
          "counted - the other lanes bit for bit with their bytes, FLAGS "
          "after the replay lang.run's, STATUS[6] set exactly where a byte "
          "is marked, no mark lost between checkpoints",
          base.describe())
    # O2 to O4: a fault in an unmarked lane is red, in its value and in its byte
    v = fx.verdict(at_step(5, value(2)))
    check(v.failing == {2} and "lane-value" in v.broken and v.first == 5 and
          not v.per[1].failing and not v.per[2].failing and
          not v.per[8].failing and v.flags_ok,
          "O2. a bit flipped in an unmarked lane's value (lane 2 at 5 steps) "
          "is red there and only there - lane-value, FLAGS and STATUS fine",
          v.describe())
    v = fx.verdict(at_step(2, byte(2, mask=0x02), flags(mask=0x02)))
    check(v.failing == {2} and {"lane-byte", "flags-replayed"} <= v.broken and
          "flags-word" not in v.broken and v.first == 2,
          "O3. a flag in an unmarked lane's byte that the definition does "
          "not raise (divideByZero, FLAGS kept to the bytes' OR) is red - "
          "lane-byte, and FLAGS after the replay differ from lang.run's",
          v.describe())
    v = fx.verdict(at_step(1, byte(4, clear=0x08), flags(clear=0x08)))
    check(v.failing == {4} and "lane-byte" in v.broken and v.first == 1,
          "O4. a flag the definition raises missing from an unmarked lane's "
          "byte (underflow, lane 4) is red - lane-byte",
          v.describe())
    # O5: the unmarked lane with the mark set is replayed, harmlessly
    v = fx.verdict(at_step(2, byte(2, mask=LANE_MARKED), onward=True))
    check(not v.failing and v.flags_ok and v.per[1].marked == [0, 1] and
          v.per[2].marked == [0, 1, 2] and v.per[5].marked == [0, 1, 2, 3] and
          2 not in v.per[5].wrong and 2 not in v.per[5].wrong_flags,
          "O5. a lane marked that did not need to be (lane 2 from 2 steps on) "
          "is replayed, its guess - right in its value and its flags - "
          "counted as right: a mark is never a fault, and the lane, unmarked "
          "at 1 step, is judged unmarked there", v.describe())
    # O6, O7: a marked lane's guess is never required
    v = fx.verdict(at_step(1, value(1, 52)))
    check(not v.failing and v.flags_ok and v.per[1].wrong == [0, 1],
          "O6. a marked lane whose guess is wrong in its value (lane 1, a bit "
          "flipped, at 1 step) is replayed and the guess counted - the "
          "rule requires nothing of a guess", v.describe())
    v = fx.verdict(at_step(5, byte(1, mask=0x04), flags(mask=0x04)))
    check(not v.failing and v.flags_ok and 1 in v.per[5].wrong_flags and
          1 in v.per[5].marked,
          "O7. a marked lane whose guess raised a flag the definition does "
          "not (overflow, lane 1 at 5 steps) is replayed: its flags are the "
          "definition's and FLAGS after the replay lang.run's, the guess's "
          "flags counted", v.describe())
    # O8, O9: the guess of a lane that was not marked is a fault
    v = fx.verdict(at_step(1, byte(0, clear=LANE_MARKED)))
    check(0 in v.failing and {"lane-value", "lane-byte"} <= v.broken and
          v.first == 1,
          "O8. a lane marked at the run, whose mark is silenced in its byte "
          "(lane 0 at 1 step, the mark of a wrong last bit lost), is a fault: "
          "its guess is wrong and unmarked - lane-value, and lane-byte too, "
          "the guess having raised invalid", v.describe())
    # O9: the mark lost between checkpoints (R8): lane 1 unmarked at 5 steps,
    # its byte and its right value exactly the definition's
    d5 = fx.ref.lane_flags(5, 1)
    v = fx.verdict(at_step(5, byte(1, clear=0xFF), byte(1, mask=d5)))
    check("marks-vanish" in v.broken and v.first == 5 and not v.failing,
          "O9. a mark lost between checkpoints (lane 1, marked at 1 and 2 "
          "steps and not at 5, its value and byte exactly the definition's) "
          "is red - marks-vanish alone", v.describe())
    # O10 to O12: STATUS against the bytes
    v = fx.verdict(at_step(2, status(clear=STATUS_MARKED)))
    check(v.broken == {"status-mark"} and v.first == 2 and not v.failing,
          "O10. STATUS[6] clear while lanes are marked is red - "
          "status-mark", v.describe())
    quiet = Fixture(*markstep_subject(), MARKSTEP_TOP)
    keep = [2, 4]
    quiet = Fixture(quiet.c, [quiet.states[i] for i in keep], MARKSTEP_TOP)
    qbase = quiet.verdict()
    v = quiet.verdict(at_step(5, status(mask=STATUS_MARKED)))
    check(not qbase.failing and qbase.flags_ok and not qbase.marked and
          v.broken == {"status-mark"} and v.first == 5,
          "O11. an image that marks no lane is the rule before it - states, "
          "bytes, FLAGS and STATUS equal the interpreter's, no mark, nothing "
          "reported - and STATUS[6] set with no lane marked is red - "
          "status-mark", v.describe())
    v = fx.verdict(at_step(1, status(mask=0x10)))
    check(v.broken == {"status-other"} and v.first == 1,
          "O12. STATUS carrying a bit besides STATUS[6] (the deposit "
          "overflow's) is red - status-other", v.describe())
    v = fx.verdict(at_step(8, byte(0, mask=seq.LANE_DEPOSIT_OVERFLOW)))
    check("status-other" in v.broken and not v.failing and v.first == 8,
          "O13. a marked lane's byte carrying [5], the deposit overflow, "
          "which no STATUS may show, is red - status-other", v.describe())
    # O14, O15: FLAGS against the bytes
    v = fx.verdict(at_step(2, flags(mask=0x02)))
    check(v.broken == {"flags-word"} and v.first == 2 and not v.failing,
          "O14. FLAGS, as the run reports it, that is not the OR of the "
          "bytes' [4:0] is red - flags-word alone", v.describe())
    v = fx.verdict(at_step(1, lambda q: q.lane_flags.pop()))
    check(v.broken == {"block-length"} and v.first == 1,
          "O15. a block that is not one byte a lane is red - block-length",
          v.describe())
    check(base.per[8].broken == set() and quiet.verdict().per[8].marked == [],
          "O16. the controls pass what they should: the unplanted markstep "
          "and the unplanted markless run break no check",
          f"{base.per[8].broken}")


# ---- N: the math library's six, compiled and run (M1's build, item 5) -------------
#
# The compiler carries exp, expm1, exp2, log, log1p and log2 as routines since
# M1's build, item 4 (cftc's output version 6); the stage holds them as it holds
# division and the root: every image on seq.py against lang.run, at 1, 2, 5
# steps, under the marked-lane rule - which is what item 5 adds, since an image
# of the six can mark a lane. The structured families (python/tests/
# mathlib_family.py: the arguments next to an exact case, x = c 2^-e for exp,
# expm1 and log1p, 1 + c ulp for log; Logan's answer to question 4) are put in
# the lanes on purpose, each centre and its neighbours, so that marks occur
# where the study counts them; exp2 and log2 have none. All of this needs
# mpmath (the six's golden functions and their routines' generator), and a
# host without it skips these legs by name.

SIX = ("exp", "expm1", "exp2", "log", "log1p", "log2")
FAMILY_FNS = ("exp", "expm1", "log", "log1p")
FORMATS4 = ("fp32", "fp64", "fp128", "fp256")
ATTRS5 = ("rne", "rtz", "rdn", "rup", "rmm")
SHAPES5 = ("map", "maph", "rk4", "euler", "sv")
# one function alone at one format and attribute: twenty configurations, the
# shape by the configuration's place among them, so that a function meets each
# integrator and the rest are maps (a mark is raised at the first call)
ALONE_SHAPES = ("map", "rk4", "map", "euler", "map", "sv", "map", "maph",
                "map", "map")
RND_CODE = {name: code for code, name in sf.RND_NAMES.items()}
_FAMILY = []


def family():
    """python/tests/mathlib_family: the structured families' committed
    centres, and the theory that says which lane must mark."""
    if not _FAMILY:
        sys.path.insert(0, str(ROOT / "python" / "tests"))
        try:
            import mathlib_family
        finally:
            sys.path.remove(str(ROOT / "python" / "tests"))
        _FAMILY.append(mathlib_family)
    return _FAMILY[0]


def sample_centres(centres, fn, fmt, everything=False):
    """A gate-sized draw of a family's centres, in the list's order: the
    anchor whose guess is wrong under round-to-nearest if the list holds it
    (exp's x = 2^-p and expm1's 2^-(p-1), the study's census: python/tests/
    mathlib_family.py, 3.5; MEASURED over every centre of the committed
    lists at fp64, fp128 and fp256, the only six), the first three, the last
    and two spread between; every centre with `everything`."""
    if everything:
        return list(centres)
    anchor = {"exp": (1, fmt.prec), "expm1": (1, fmt.prec - 1)}.get(fn)
    pick = {anchor} if anchor in centres else set()
    pick |= set(centres[:3]) | set(centres[-1:])
    mid = centres[3:-1]
    if mid:
        pick |= {mid[i * len(mid) // 2] for i in range(2)}
    return [c for c in centres if c in pick]


def ulp_away(fmt, bits, k):
    """The encoding k ulps away in magnitude, kept finite and nonnegative."""
    mag = max(0, min((bits & ~fmt.sign_mask) + k, sf.inf_bits(fmt) - 1))
    return (bits & fmt.sign_mask) | mag


def six_edges(fn, fmt, everything=False):
    """Arguments beside where the result of exp, expm1 or exp2 overflows or
    underflows, found by mpmath at 400 digits - each and its next, and with
    `everything` the one before it and its negation too - and beside
    log1p's pole."""
    import mpmath
    p, rn = fmt.prec, K.round_once

    def enc(q):
        return rn(fmt, sf.RND_RNE, Fraction(q))[0]
    out = []
    with mpmath.workdps(400):
        ln2 = mpmath.log(2)
        pts = []
        if fn in ("exp", "expm1"):
            pts = [mpmath.log(mpmath.mpf(2) ** (fmt.emax + 1)),
                   -mpmath.log(mpmath.mpf(2) ** (p - fmt.emin + 1)),
                   -mpmath.log(mpmath.mpf(2) ** (p - fmt.emin)),
                   -(p + 1) * ln2, -p * ln2, -(p - 1) * ln2]
        elif fn == "exp2":
            pts = [fmt.emax + 1, fmt.emax, fmt.emin - 1, fmt.emin - p,
                   fmt.emin - p - 1, fmt.emin - p - 2,
                   mpmath.mpf(fmt.emax) + mpmath.mpf(1) / 2,
                   fmt.emin - p + mpmath.mpf(1) / 2]
        if not everything:
            pts = pts[:3]
        for v in pts:
            q = Fraction(int(mpmath.floor(mpmath.mpf(v) * 2 ** (p + 8))),
                         2 ** (p + 8))
            b = enc(q)
            out += [b, ulp_away(fmt, b, 1)]
            if everything:
                out += [ulp_away(fmt, b, -1), b ^ fmt.sign_mask]
    if fn == "log1p":
        out += [enc(-1), enc(Fraction(-1) + Fraction(1, 2 ** p)),
                enc(Fraction(-1) - Fraction(1, 2 ** (p - 1))), enc(-2)]
        if everything:
            out += [enc(Fraction(-1, 2)), enc(Fraction(-3, 4))]
    return out


def alone_lanes(fn, fmtname, rnd, rng, everything=False):
    """[(bits, role)]: the arguments one of the six is run on at one format
    and attribute - a few ordinary ones, the specials (zeros, infinities,
    both NaNs, one, the subnormal and normal ends), the edges of its range,
    and the structured family's centres (sample_centres), each with its
    neighbour a unit in the last place above and, for the first three, the
    one below. A role beginning `structured` is one the theory
    (mathlib_family.classify) may demand marked. With `everything` the
    ordinary lanes are twelve, the edges all, and every centre has both
    neighbours."""
    F = FORMATS[fmtname]
    fam = family()
    sign, one = F.sign_mask, sf.one_bits(F)
    lanes, seen = [], set()

    def add(bits, role):
        if bits not in seen:
            seen.add(bits)
            lanes.append((bits, role))
    lo, hi = (-3, 3) if fn.startswith("exp") or fn == "expm1"         else (Fraction(1, 100), 8)
    for _ in range(12 if everything else 3):
        add(full_value(F, rng, lo, hi), "ordinary")
    for bits, role in ((0, "+0"), (sign, "-0"), (sf.inf_bits(F), "+inf"),
                       (sf.inf_bits(F, 1), "-inf"), (sf.qnan_bits(F), "qNaN"),
                       (sf.snan_bits(F), "sNaN"), (one, "1"),
                       (one | sign, "-1"), (1, "least subnormal"),
                       (F.man_mask, "greatest subnormal"),
                       (1 << F.man_w, "least normal"),
                       (sf.max_normal_bits(F), "greatest normal"),
                       (sf.max_normal_bits(F, 1), "-greatest normal")):
        add(bits, role)
    for b in six_edges(fn, F, everything):
        add(b, "edge")
    for i, centre in enumerate(sample_centres(
            fam.FAMILY.get(fn, {}).get(fmtname, {}).get(rnd, []), fn, F,
            everything)):
        x = fam.argument(F, centre)
        for d, tag in ((0, "centre"), (1, "+1 ulp"), (-1, "-1 ulp")):
            if d >= 0 or i < 3 or everything:
                add(ulp_away(F, x, d), f"structured {centre} {tag}")
    return lanes


def alone_text(fn, fmt, rnd, shape):
    """`next x = fn(x)`, or its flow or Stormer-Verlet form: the call's
    operand is the state itself at the first step, whatever the integrator."""
    head = f"system v\nformat {fmt}\nround {rnd}\n"
    if shape == "sv":
        return (head + f"state q, p\nd/dt q = p\nd/dt p = {fn}(q)\n"
                f"step stormer-verlet, h = 1/16, q = (q), p = (p)\n")
    word, step = {"map": ("next", "step map"),
                  "maph": ("next", "step map, h = 1/8"),
                  "rk4": ("d/dt", "step rk4, h = 1/16"),
                  "euler": ("d/dt", "step euler, h = 1/16")}[shape]
    rhs = f"{fn}(x) + h" if shape == "maph" else f"{fn}(x)"
    return head + f"state x\n{word} x = {rhs}\n{step}\n"


# The six's own tally (the routines group's I2, from these legs alone): for
# each function the formats, attributes and integrators an image holding it
# was compiled and run under, the lanes the rule saw marked and the guesses
# wrong; the flags those runs raised; the call loops run.
SCOVER = {"images": 0, "flags": 0, "loops": 0, "looped_calls": 0,
          "looped_ops": set(), "refusals": 0,
          "by_op": {fn: {"formats": set(), "rounds": set(),
                         "integrators": set(), "images": 0, "marked": 0,
                         "wrong": 0, "wrong_flags": 0, "demanded": 0,
                         "marked_formats": set()} for fn in SIX}}


def scover(c, v, demanded=0):
    """Count one image of the six run under the rule: `v` its Verdict,
    `demanded` the lanes the theory demanded marked."""
    SCOVER["images"] += 1
    SCOVER["flags"] |= v.ref.flags
    ops = c.ir.op_counts()
    for fn, d in SCOVER["by_op"].items():
        if ops.get(fn):
            d["images"] += 1
            d["formats"].add(c.ir.fmt_name)
            d["rounds"].add(c.ir.rnd_name)
            d["integrators"].add(c.ir.integrator[0])
            if len([f for f in SIX if ops.get(f)]) == 1:
                # one function alone: its marks are its own
                d["marked"] += len(v.marked)
                d["wrong"] += len(v.wrong)
                d["wrong_flags"] += len(v.wrong_flags)
                d["demanded"] += demanded
                if v.marked:
                    d["marked_formats"].add(c.ir.fmt_name)
    for b in getattr(c, "looped", ()):
        if b.op in SIX:
            SCOVER["loops"] += 1
            SCOVER["looped_calls"] += len(b.calls)
            SCOVER["looped_ops"].add(b.op)


def check_refused_rev7(text, what, wrong, internal, steps=2,
                       targets=REV7_TARGETS):
    """Each of revision 7's four targets refuses the source `target-feature`,
    naming FLAG_CONTROL (CAPS2[14]). -> how many refused."""
    n = 0
    for t in targets:
        try:
            cftc.compile_text(text, steps, target=t, source=what, stem="n")
            wrong.append(f"{what} on {t}: compiled")
        except lang.Refusal as e:
            if e.name != "target-feature" or \
                    "FLAG_CONTROL (CAPS2[14])" not in e.sentence:
                wrong.append(f"{what} on {t}: refused {e.name}, where "
                             f"target-feature naming FLAG_CONTROL is due "
                             f"({e.sentence[:80]})")
            else:
                n += 1
        except cftc.InternalError as e:
            internal.append(f"{what} on {t}: internal error (exit 70): "
                            f"{str(e)[:120]}")
    SCOVER["refusals"] += n
    return n


def leg_six_alone(rng, everything=False, fns=None):
    section("N1. each of the math library's six alone, at every format and "
            "attribute and each integrator: structured-family arguments put "
            "in the lanes on purpose, the marks replayed (M1's build, item 5)")
    if not have_mpmath():
        skip("N1: the math library's six alone", "python has no mpmath "
             "module, which their golden functions (python/cft_golden/"
             "transcend.py) and their routines' generator (python/"
             "cft_golden/mathlib.py) need (pip install mpmath)")
        return
    fam = family()
    t0 = time.perf_counter()
    steps = 2
    for fn in (fns or SIX):
        wrong, internal, notmarked = [], [], []
        configs = lanes_n = marked = guess = gflags = gtang = 0
        demanded = refused = 0
        by_fmt = {}
        shapes = set()
        t1 = time.perf_counter()
        for fi, fmtname in enumerate(FORMATS4):
            F = FORMATS[fmtname]
            for ri, rnd in enumerate(ATTRS5):
                shape = ALONE_SHAPES[(fi * 5 + ri) % 10]
                shapes.add(shape)
                text = alone_text(fn, fmtname, rnd, shape)
                what = f"{fn} {fmtname} {rnd} {shape}"
                lanes = alone_lanes(fn, fmtname, rnd, rng, everything)
                # Stormer-Verlet drifts q by h/2 p before the force is
                # called: the call's operand is q itself where p is zero
                states = [[b] if shape != "sv" else
                          [b, full_value(F, rng, -1, 1) if role == "ordinary"
                           else 0] for b, role in lanes]
                try:
                    c = cftc.compile_text(text, steps, source=what, stem="n")
                except lang.Refusal as e:
                    wrong.append(f"{what}: refused {e.name}: "
                                 f"{e.sentence[:80]}")
                    continue
                except cftc.InternalError as e:
                    internal.append(f"{what}: internal error (exit 70): "
                                    f"{str(e)[:120]}")
                    continue
                v = rule_compare(c, states, steps, width=c.ir.n_state,
                                 tag=fn)
                must = [i for i, (b, role) in enumerate(lanes)
                        if role.startswith("structured") and
                        fam.classify(F, RND_CODE[rnd], b, None, fn) == "mark"]
                scover(c, v, len(must))
                configs += 1
                lanes_n += len(lanes)
                marked += len(v.marked)
                guess += len(v.wrong)
                gflags += len(v.wrong_flags)
                demanded += len(must)
                d = by_fmt.setdefault(fmtname, [0, 0, 0])
                d[0] += len(v.marked)
                d[1] += len(v.wrong)
                d[2] += len(must)
                if v.failing or not v.flags_ok:
                    wrong.append(f"{what}: {len(v.failing)} unmarked lanes "
                                 f"differ; {v.describe()}")
                lost = [lanes[i][1] for i in must if i not in v.per[1].marked]
                if lost:
                    notmarked.append(f"{what}: demanded and not marked: "
                                     f"{lost[:3]}")
            # the revision-7 refusals, once a function: at the format its
            # place among the six decides (a refusal costs a compile)
            if fmtname == FORMATS4[SIX.index(fn) % 4]:
                refused += check_refused_rev7(
                    alone_text(fn, fmtname, "rne", "map"), f"{fn} {fmtname}",
                    wrong, internal)
        for f in (internal + wrong + notmarked)[:8]:
            print(f"        {f}")
        fmt_line = ", ".join(f"{f}: {a} marked, {b} wrong, {m} demanded"
                             for f, (a, b, m) in by_fmt.items())
        print(f"  {fn}: {configs} configurations, {lanes_n} lanes; marked "
              f"{marked}, guesses wrong in value {guess}, in flags {gflags} "
              f"({fmt_line}) [{time.perf_counter() - t1:.1f} s]")
        at = " and ".join(str(s) for s in checkpoints(steps))
        check(not internal and not wrong and not notmarked and
              configs == 20 and refused == len(REV7_TARGETS),
              f"N1. {fn}: 20 configurations (4 formats x 5 attributes, "
              f"{', '.join(sorted(shapes))}), {lanes_n} lanes at {at} steps "
              f"- ordinary, special, edge and structured ({demanded} the "
              f"theory demands marked, every one marked) - equal the "
              f"interpreter under the marked-lane rule: {marked} lanes "
              f"marked and replayed, {guess} guesses wrong in their value, "
              f"{gflags} in their flags; refused `target-feature`, naming "
              f"FLAG_CONTROL, on revision 7's {len(REV7_TARGETS)} targets "
              f"({refused})",
              f"{len(wrong) + len(internal) + len(notmarked)} otherwise")
    print(f"  ({time.perf_counter() - t0:.1f} s)")


# ---- N2: generated sources that call the six --------------------------------------

def g_six(rng, k, tangent=None):
    """(text, direct, components): a system the language takes that calls
    the math library's six beside division, the root and the other
    operations - in equations and, one time in three, in a let - under the
    integrator, format and attribute that the index decides (all five, four
    and five within five systems), with or without tangent vectors (with,
    one vector or two by the index, where `tangent` is true). `direct`
    lists the (state component, function) pairs where a call reads a
    component as it is at the first step - a structured argument put in
    that component marks that call. Under Stormer-Verlet only the position
    equations' calls do (they are evaluated at the momenta before the half
    drift); a momentum equation's calls read the drifted position."""
    shape = SHAPES5[k % 5]
    fmt = FORMATS4[(k // 5 + k) % 4]
    rnd = ATTRS5[(k + k // 5) % 5]
    sv = shape == "sv"
    comps = ["q0", "q1", "m0", "m1"] if sv else \
        rng.choice([["x", "y"], ["x", "y", "z"]])
    lines = [f"system sx{k}", f"format {fmt}", f"round {rnd}",
             "state " + ", ".join(comps)]
    if tangent:
        lines.append("tangent v" + (", w" if k % 3 == 2 else ""))
    elif tangent is None and rng.random() < 0.4:
        lines.append("tangent v" + (", w" if rng.random() < 0.3 else ""))
    params = [f"p{i}" for i in range(rng.randint(0, 1))]
    if params:
        lines.append("param " + ", ".join(f"{p} = {rng.choice(LITS[:6])}"
                                          for p in params))
    direct, count = [], [0]

    def six_term(pool, allow_direct, force=False):
        fn = SIX[(k + count[0]) % 6]
        count[0] += 1
        s, t = rng.choice(pool), rng.choice(pool)
        lit = rng.choice(LITS[:6])
        form = rng.randrange(5) if allow_direct and (force or
                                                     rng.random() < 0.8) \
            else rng.choice((5, 6))
        expr = [f"{fn}({s})", f"{fn}({s}) * {lit}",
                f"fma({fn}({s}), {t}, {lit})",
                f"{fn}({s}) / ({t} * {t} + 1)",
                f"sqrt(abs({fn}({s}))) + {t}",
                f"{fn}({t} * {s})", f"{fn}(abs({s}) + 1)"][form]
        if form < 5:
            direct.append((s, fn))
        return expr
    extra = list(params)
    if not sv and rng.random() < 0.33:
        lines.append(f"let r = {six_term(comps, True)}")
        extra.append("r")
    if sv:
        reads = {"q0": ["m0", "m1"], "q1": ["m0", "m1"],
                 "m0": ["q0", "q1"], "m1": ["q0", "q1"]}
        word, first_eq = "d/dt", len(lines) + 1
    else:
        reads = {c: comps + (["h"] if shape == "maph" else [])
                 for c in comps}
        word, first_eq = "next" if shape.startswith("map") else "d/dt", \
            len(lines) + 1
    for i, c in enumerate(comps):
        pool = [s for s in reads[c] if s != "h"]
        allow = (c[0] == "q") if sv else True
        if (i == 0 and not direct) or rng.random() < 0.75:
            rhs = six_term(pool, allow, force=(i == 0 and not direct))
        else:
            rhs = g_expr(rng, reads[c], 2)
        lines.append(f"{word} {c} = {rhs}")
    used = extra + (["h"] if shape == "maph" else [])
    if used:
        lines[first_eq - 1] += " + " + " + ".join(used)
    lines.append({"map": "step map", "maph": "step map, h = 1/8",
                  "rk4": "step rk4, h = 1/8", "euler": "step euler, h = 1/8",
                  "sv": "step stormer-verlet, h = 1/8, q = (q0, q1), "
                        "p = (m0, m1)"}[shape])
    return "\n".join(lines) + "\n", direct, comps


def six_source_lanes(g, rng, direct, comps, k, everything=False):
    """The lanes a generated source of the six runs on: ordinary ones, the
    primal's three special lanes, a zero lane, and for each direct call two
    lanes (twelve with `everything`) with the structured family's centres
    of its function put in its component (the others ordinary).
    -> (lanes, roles)."""
    fmt, n = g.fmt, g.n_state
    fam = family()
    lanes = lanes_for(fmt, n, rng, 3)
    lanes += special_lanes(fmt, n, lanes[0], rng)
    lanes.append([0] * n)
    roles = ["ordinary"] * 3 + ["special"] * 3 + ["zero"]
    for s, fn in sorted(set(direct), key=lambda sf_: (comps.index(sf_[0]),
                                                      sf_[1])):
        picks = sample_centres(fam.FAMILY.get(fn, {}).get(fmt.name, {})
                               .get(g.round_name, []), fn, fmt, everything)
        for j in range(min(12 if everything else 2, len(picks))):
            centre = picks[(k + j) % len(picks)]
            lane = list(lanes[j % 3])
            lane[comps.index(s)] = family().argument(fmt, centre)
            lanes.append(lane)
            roles.append(("structured", fn, centre, comps.index(s)))
    return lanes, roles


# A refusal costs a compile, so a generated source is compiled for all three
# software targets and refused by all four of revision 7's for the first
# SIX_ALL_TARGETS of them, and for sw and u50-rev7 alone after that.
SIX_ALL_TARGETS = 2

# a generated source may fold a call of one of the six to a constant the
# language refuses, besides ARTIFACTS: a power of two past every format, a
# fold that overflows or rounds to zero
SIX_ARTIFACTS = ARTIFACTS | {"constant-range", "constant-overflow",
                             "constant-rounds-to-zero"}


def leg_six_generated(count, rng, everything=False):
    section(f"N2. {count} generated sources that call the math library's six "
            f"beside division, the root and the other operations, compiled "
            f"for the software targets and run against the interpreter "
            f"under the marked-lane rule, and refused `target-feature` on "
            f"revision 7's (M1's build, item 5)")
    if not have_mpmath():
        skip("N2: generated sources that call the math library's six",
             "python has no mpmath module (see N1)")
        return
    fam = family()
    t0 = time.perf_counter()
    tally, wrong, internal = {}, [], []
    held = marked = guess = gtan = demanded = flags = refused = 0
    sixes, kinds, cli = set(), set(), []
    t_compile = t_run = t_refuse = 0.0
    for k in range(count):
        text, direct, comps = g_six(random.Random(f"lang six {k}"), k)
        what = f"six {k}"
        try:
            g = lang.compile_text(text, what).graph
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            if e.name not in SIX_ARTIFACTS:
                wrong.append(f"{what}: the language refused {e}")
            continue
        used = {op for op in g.op_counts("step") if op in SIX}
        if not used:
            wrong.append(f"{what}: none of the six in its step")
        canon = lang.render_canonical(g)
        if lang.compile_text(canon, "canonical").graph.to_bytes() != \
                g.to_bytes():
            wrong.append(f"{what}: its canonical form reads back as "
                         f"another graph")
        lang.render_math(g)
        try:
            t1 = time.perf_counter()
            images, c = {}, None
            for t in (SW_TARGETS if k < SIX_ALL_TARGETS else SW_TARGETS[:1]):
                ct = cftc.compile_text(text, 5, target=t, source=what,
                                       stem="n")
                images[t] = ct.image
                c = c or ct             # the run is sw's, at its own depth
            t_compile += time.perf_counter() - t1
            if len(set(images.values())) != 1:
                wrong.append(f"{what}: the software targets' images differ")
        except lang.Refusal as e:
            tally[e.name] = tally.get(e.name, 0) + 1
            wrong.append(f"{what}: refused {e.name} on the software "
                         f"targets: {e.sentence[:100]}")
            continue
        except cftc.InternalError as e:
            internal.append(f"{what}: internal error (exit 70): "
                            f"{str(e)[:120]}")
            continue
        lanes, roles = six_source_lanes(g, rng, direct, comps, k, everything)
        tans = None
        if g.tangent:
            tans = [[lanes_for(g.fmt, g.n_state, rng, 1)[0]
                     for _ in g.tangent] for _ in lanes]
        t1 = time.perf_counter()
        v = rule_compare(c, lanes, 5, tans=tans, width=c.ir.n_state,
                         tag="generated")
        t_run += time.perf_counter() - t1
        scover(c, v)
        flags |= v.ref.flags
        must = [i for i, r in enumerate(roles)
                if isinstance(r, tuple) and fam.classify(
                    g.fmt, RND_CODE[g.round_name], lanes[i][r[3]], None,
                    r[1]) == "mark"]
        lost = [roles[i][1:3] for i in must if i not in v.per[1].marked]
        marked += len(v.marked)
        guess += len(v.wrong)
        gtan += len(v.wrong_tangents)
        demanded += len(must)
        sixes |= used
        kinds.add(g.integrator[0])
        if v.failing or not v.flags_ok:
            wrong.append(f"{what}: {len(v.failing)} unmarked lanes differ; "
                         f"{v.describe()}")
        elif lost:
            wrong.append(f"{what}: demanded and not marked: {lost[:3]}")
        else:
            held += 1
        t1 = time.perf_counter()
        refused += check_refused_rev7(
            text, what, wrong, internal, 5,
            REV7_TARGETS if k < SIX_ALL_TARGETS else REV7_TARGETS[:1])
        t_refuse += time.perf_counter() - t1
        if len(cli) < 2:
            cli.append((k, text))
    py = [sys.executable, str(ROOT / "python" / "cftc")]
    with tempfile.TemporaryDirectory() as tmp:
        for k, text in cli:
            src = Path(tmp) / f"six{k}.cftl"
            src.write_bytes(text.encode("ascii"))
            out = Path(tmp) / f"sw{k}"
            p = subprocess.run(py + [str(src), "--steps", "2", "--out",
                                     str(out)], capture_output=True,
                               text=True)
            cfta = out / f"six{k}.cfta"
            if p.returncode != 0 or not cfta.is_file() or \
                    "\n  quiet " not in cfta.read_text(encoding="ascii"):
                wrong.append(f"six {k} through the command line on sw: rc "
                             f"{p.returncode}, {p.stderr.strip()[:120]}")
            out = Path(tmp) / f"quad{k}"
            p = subprocess.run(py + [str(src), "--steps", "2", "--target",
                                     "u50-rev7-quad", "--out", str(out)],
                               capture_output=True, text=True)
            if p.returncode != 3 or not p.stderr.startswith(
                    "cftc: refused target-feature: ") or out.exists():
                wrong.append(f"six {k} through the command line on "
                             f"u50-rev7-quad: rc {p.returncode}, "
                             f"{p.stderr.strip()[:120]}")
    for f in (internal + wrong)[:10]:
        print(f"        {f}")
    print(f"  outcomes: {dict(sorted(tally.items()))}; the six used: "
          f"{sorted(sixes)}; integrators {sorted(kinds)}; FLAGS over the "
          f"{held} sources held: {flags:#x}")
    print(f"  compile {t_compile:.1f} s, run under the rule {t_run:.1f} s, "
          f"the refusals {t_refuse:.1f} s")
    check(not internal, f"no InternalError: {count} generated sources that "
          f"call the six, on {len(SW_TARGETS) + len(REV7_TARGETS)} targets "
          f"each", f"{len(internal)} stopped the compiler with an internal "
          f"error, exit 70")
    check(not wrong and held >= count // 2 and sixes == set(SIX),
          f"N2. {held} sources accepted by the language read back, compiled "
          f"for sw - the first {SIX_ALL_TARGETS} for sw:4096 and sw:32768 "
          f"too, one image for the three - and run on seq.py equal to the "
          f"interpreter at 1, 2 and 5 steps, states, tangents and FLAGS, "
          f"under the marked-lane rule: structured arguments of the families "
          f"in the lanes ({demanded} the theory demands marked, every one "
          f"marked), {marked} lanes marked and replayed, {guess} guesses "
          f"wrong in their values ({gtan} in their tangents too); all six "
          f"among them, under {', '.join(sorted(kinds))}; each refused "
          f"`target-feature`, naming FLAG_CONTROL, by u50-rev7, the first "
          f"{SIX_ALL_TARGETS} by all {len(REV7_TARGETS)} of revision 7's "
          f"targets ({refused} refusals), and {len(cli)} through the command "
          f"line (exit 0 on sw with the text's regions, exit 3 on "
          f"u50-rev7-quad, nothing written) "
          f"({time.perf_counter() - t0:.1f} s)",
          f"{len(wrong)} otherwise")


def leg_six(count, rng_for, everything=False):
    """N1 to N3, the math library's six compiled and run (each with its
    own generator, so that one's lanes do not move another's)."""
    leg_six_alone(rng_for("six alone"), everything)
    leg_six_generated(count, rng_for("six generated"), everything)
    leg_six_loops(rng_for("six loops"), everything)


# ---- N3: the call loop over a batch of the six -------------------------------------
#
# The step's routines are looped when, inlined, they would pass 32,768
# instructions (python/cftc/callloop.py), and the constant is the compiler's
# own. As leg L lowers it for Kepler, it is lowered here for a step whose
# batches are calls of the six: a batch of two or more calls of one function
# at one routine depth runs once in a loop, called a record at a time, and
# a lane that marks inside an iteration is marked all the same (R24's raise
# is in the loop). A and B differ in where the batches sit: A's three are all
# at depth 1 (exp, expm1 and log1p, each of two calls), B's log1p calls read
# the exp calls' results, so its log1p batch is at depth 2.

SIX_LOOPS = {
    "A": ("system sixloopa\nformat {fmt}\nround {rnd}\nstate a, b, c, d\n"
          "next a = exp(a) + b * 0.125\n"
          "next b = exp(b) - expm1(a)\n"
          "next c = expm1(c) + log1p(d)\n"
          "next d = log1p(c) * (1/3)\nstep map\n",
          # which centres go in which component: (component, function)
          (("a", "exp"), ("b", "exp"), ("c", "expm1"), ("d", "log1p")),
          [("exp", 1, 2), ("expm1", 1, 2), ("log1p", 1, 2)]),
    "B": ("system sixloopb\nformat {fmt}\nround {rnd}\nstate a, b, c, d\n"
          "next a = log1p(exp(a))\nnext b = log1p(exp(b)) * 0.5\n"
          "next c = expm1(c)\nnext d = expm1(d) - 0.25\nstep map\n",
          (("a", "exp"), ("b", "exp"), ("c", "expm1"), ("d", "expm1")),
          [("exp", 1, 2), ("expm1", 1, 2), ("log1p", 2, 2)]),
}
# source, format, attribute: A under rne at fp64 (exp's anchor, whose guess is
# wrong, marks inside the loop's first iteration), A at fp256 and B at fp128
# under directed attributes (the long lists of centres)
SIX_LOOP_CASES = (("A", "fp64", "rne"), ("A", "fp256", "rup"),
                  ("B", "fp128", "rdn"))


def leg_six_loops(rng, everything=False):
    from cftc import callloop
    above = callloop.CALL_LOOP_ABOVE
    section("N3. the call loop over a batch of the math library's six "
            "(M1's build, item 5): the constant lowered as leg L lowers it "
            "for Kepler, every batch looped and the largest alone, run "
            "against the interpreter under the marked-lane rule")
    if not have_mpmath():
        skip("N3: the call loop over a batch of the six", "python has no "
             "mpmath module (see N1)")
        return
    fam = family()
    t0 = time.perf_counter()
    wrong, internal = [], []
    marked = guess = demanded = images = 0
    for name, fmtname, rnd in SIX_LOOP_CASES:
        template, places, want_all = SIX_LOOPS[name]
        text = template.format(fmt=fmtname, rnd=rnd)
        F = FORMATS[fmtname]
        size = len(cftc.compile_text(text, 5, source=f"sixloop{name}")
                   .program.body) + 1
        try:
            for low_to, what in ((0, "every batch"),
                                 (size - 1, "the largest batch alone")):
                callloop.CALL_LOOP_ABOVE = low_to
                tag = f"six loop {name} {fmtname} {rnd}, {what}"
                try:
                    c = cftc.compile_text(text, 5, source=tag, stem="n")
                except cftc.InternalError as e:
                    internal.append(f"{tag}: internal error (exit 70): "
                                    f"{str(e)[:120]}")
                    continue
                looped = sorted((b.op, b.depth, len(b.calls))
                                for b in c.looped)
                if low_to == 0:
                    ok_loops = looped == want_all
                else:
                    fsize = {op: len(R.fragment(op, F, RND_CODE[rnd]))
                             for op, _d, _n in want_all}
                    best = max(want_all, key=lambda b: (b[2] * fsize[b[0]],
                                                        -b[1]))
                    ok_loops = looped == [best]
                if not ok_loops:
                    wrong.append(f"{tag}: looped {looped}")
                g = c.ir
                lanes = lanes_for(g.fmt, g.n_state, rng, 3, (-2, 2))
                lanes += special_lanes(g.fmt, g.n_state, lanes[0], rng)
                lanes.append([0] * g.n_state)
                roles = ["ordinary"] * 3 + ["special"] * 3 + ["zero"]
                comps = ["a", "b", "c", "d"]
                for ci, (comp, fn) in enumerate(places):
                    cs = fam.FAMILY.get(fn, {}).get(fmtname, {}).get(rnd, [])
                    for j, centre in enumerate(cs[:2]):
                        lane = list(lanes[j])
                        lane[comps.index(comp)] = fam.argument(F, centre)
                        lanes.append(lane)
                        roles.append((fn, comp, centre))
                lists = [fam.FAMILY.get(fn, {}).get(fmtname, {}).get(rnd, [])
                         for _c, fn in places]
                everyone = [lst[0] if lst else None for lst in lists]
                if all(x is not None for x in everyone):
                    # every component at a centre at once: all its calls mark
                    lanes.append([fam.argument(F, x) for x in everyone])
                    roles.append(("all", "abcd", tuple(everyone)))
                v = rule_compare(c, lanes, 5, width=c.ir.n_state,
                                 tag="loops")
                scover(c, v)
                must = [i for i, r in enumerate(roles)
                        if isinstance(r, tuple) and r[0] != "all" and
                        fam.classify(F, RND_CODE[rnd],
                                     lanes[i][comps.index(r[1])], None,
                                     r[0]) == "mark"]
                marked += len(v.marked)
                guess += len(v.wrong)
                demanded += len(must)
                images += 1
                lost = [roles[i] for i in must if i not in v.per[1].marked]
                if v.failing or not v.flags_ok:
                    wrong.append(f"{tag}: {len(v.failing)} unmarked lanes "
                                 f"differ; {v.describe()}")
                if lost:
                    wrong.append(f"{tag}: demanded and not marked: "
                                 f"{lost[:3]}")
        finally:
            callloop.CALL_LOOP_ABOVE = above
    for f in (internal + wrong)[:10]:
        print(f"        {f}")
    cases = ", ".join(f"{n} at {f} under {r}" for n, f, r in SIX_LOOP_CASES)
    check(not internal and not wrong and images == 2 * len(SIX_LOOP_CASES),
          f"N3. a step of the six looped, the constant lowered: {images} "
          f"images - source A (an exp, an expm1 and a log1p batch of two "
          f"calls, all at depth 1) and source B (a log1p batch at depth 2, "
          f"reading the exp calls): {cases}; each with every batch looped "
          f"and with the largest alone - run on seq.py at 1, 2 and 5 steps "
          f"equal to the interpreter under the marked-lane rule, FLAGS "
          f"included: structured arguments in the components the calls "
          f"read ({demanded} the theory demands marked, every one marked, "
          f"{marked} lanes marked and replayed, in the loops' iterations "
          f"and out, {guess} guesses wrong) "
          f"({time.perf_counter() - t0:.1f} s)",
          f"{len(wrong) + len(internal)} otherwise")


# ---- I: coverage ---------------------------------------------------------------

def leg_coverage():
    """The core group's tally, from the core legs alone (A to D: the
    references, the corpus, the let-heavy maps)."""
    section("I. what the core legs covered")
    ops = COVER["ops"]
    want_ops = ["fma", "add", "sub", "mul", "neg", "abs", "copysign", "min",
                "max", "minnum", "maxnum", "cmplt", "cmple", "cmpeq",
                "select"]
    print(f"  {COVER['systems']} systems; ops {dict(sorted(ops.items()))}")
    check(all(ops.get(o) for o in want_ops), "every operation the compiler "
          "carries as one instruction was compiled and run (div and sqrt, "
          "its routines, are the routines group's tally, I2)",
          f"missing {[o for o in want_ops if not ops.get(o)]}")
    check(COVER["rounds"] == {"rne", "rtz", "rdn", "rup", "rmm"},
          "every attribute", f"{sorted(COVER['rounds'])}")
    check(COVER["formats"] == {"fp32", "fp64", "fp128", "fp256"},
          "every format", f"{sorted(COVER['formats'])}")
    check(COVER["integrators"] >= {"rk4", "euler", "stormer-verlet",
                                   "map"}, "every integrator",
          f"{sorted(COVER['integrators'])}")
    for key, what in (("shared", "shared subexpressions"),
                      ("folded", "folds"), ("spilled", "spill slots"),
                      ("copies", "closing copies"),
                      ("empty_step", "empty steps"),
                      ("lane_params", "lane params"),
                      ("homed", "systems with homed values"),
                      ("pinned", "systems with pinned values")):
        check(COVER[key] > 0, f"{what}: {COVER[key]}")
    for flag, word in ((sf.FLAG_OVERFLOW, "overflow"),
                       (sf.FLAG_INVALID, "invalid"),
                       (sf.FLAG_UNDERFLOW, "underflow"),
                       (sf.FLAG_INEXACT, "inexact")):
        check(COVER["flags"] & flag, f"a run raised {word}")


def leg_routine_coverage():
    """The routines group's tally (C4), from its legs alone (K and L):
    each of div and sqrt compiled and run at every format, under every
    attribute and integrator; the five flags raised by those runs; and
    call loops run, of both routines."""
    section("I2. what the routines group covered")
    for op, d in RCOVER["by_op"].items():
        print(f"  {op}: {d['images']} images; formats {sorted(d['formats'])}"
              f"; attributes {sorted(d['rounds'])}; integrators "
              f"{sorted(d['integrators'])}")
        check(d["images"] and d["formats"] == {"fp32", "fp64", "fp128",
                                               "fp256"},
              f"{op}, a routine: compiled and run at every format",
              f"{d['images']} images, at {sorted(d['formats'])}")
        check(d["rounds"] == {"rne", "rtz", "rdn", "rup", "rmm"},
              f"{op}: under every attribute, the routine specialised at each",
              f"{sorted(d['rounds'])}")
        check(d["integrators"] >= {"rk4", "euler", "stormer-verlet", "map"},
              f"{op}: under every integrator", f"{sorted(d['integrators'])}")
    for flag, word in ((sf.FLAG_INVALID, "invalid"),
                       (sf.FLAG_DIVZERO, "divideByZero"),
                       (sf.FLAG_OVERFLOW, "overflow"),
                       (sf.FLAG_UNDERFLOW, "underflow"),
                       (sf.FLAG_INEXACT, "inexact")):
        check(RCOVER["flags"] & flag, f"a routine image's run raised {word}")
    check(RCOVER["loops"] and RCOVER["looped_ops"] == {"div", "sqrt"},
          f"call loops compiled and run: {RCOVER['loops']} loops of "
          f"{RCOVER['looped_calls']} calls, div's and sqrt's",
          f"{RCOVER['loops']} loops, of {sorted(RCOVER['looped_ops'])}")
    if have_mpmath():
        six_coverage()
    else:
        skip("I2: the math library's six", "python has no mpmath module, "
             "which their legs (N1 to N3) need; the tally of div and sqrt "
             "above stands alone")


def six_coverage():
    """The routines tally's second part (M1's build, item 5), from legs N1
    to N3 and the rule's: each of the math library's six compiled and run at
    every format, under every attribute and integrator; the five flags those
    runs raised; the marks seen and replayed, and the guesses that were
    wrong; the call loops of the six, run; and the refusals on revision 7."""
    section("I2 (the math library's six). what legs N1 to N3 covered")
    for fn, d in SCOVER["by_op"].items():
        print(f"  {fn}: {d['images']} images; formats {sorted(d['formats'])}; "
              f"attributes {sorted(d['rounds'])}; integrators "
              f"{sorted(d['integrators'])}; alone, {d['marked']} lanes "
              f"marked and replayed ({d['demanded']} demanded), "
              f"{d['wrong']} guesses wrong in value, {d['wrong_flags']} in "
              f"flags; marks at {sorted(d['marked_formats'])}")
        check(d["images"] and d["formats"] == set(FORMATS4),
              f"{fn}, a routine: compiled and run at every format",
              f"{d['images']} images, at {sorted(d['formats'])}")
        check(d["rounds"] == set(ATTRS5),
              f"{fn}: under every attribute, the routine specialised at "
              f"each", f"{sorted(d['rounds'])}")
        check(d["integrators"] >= {"rk4", "euler", "stormer-verlet", "map"},
              f"{fn}: under every integrator", f"{sorted(d['integrators'])}")
        if fn in FAMILY_FNS:
            check(d["marked_formats"] == {"fp64", "fp128", "fp256"} and
                  d["marked"] >= d["demanded"] > 0,
                  f"{fn}: marks seen and replayed at fp64, fp128 and fp256 "
                  f"- every format where its family has a centre - "
                  f"{d['marked']} lanes, {d['demanded']} of them demanded "
                  f"by the theory, {d['wrong']} guesses wrong in value",
                  f"marks at {sorted(d['marked_formats'])}: {d['marked']} "
                  f"lanes of {d['demanded']} demanded")
    for flag, word in ((sf.FLAG_INVALID, "invalid"),
                       (sf.FLAG_DIVZERO, "divideByZero"),
                       (sf.FLAG_OVERFLOW, "overflow"),
                       (sf.FLAG_UNDERFLOW, "underflow"),
                       (sf.FLAG_INEXACT, "inexact")):
        check(SCOVER["flags"] & flag,
              f"an image of the six's run raised {word}")
    check(SCOVER["loops"] and {"exp", "expm1", "log1p"} <= SCOVER["looped_ops"],
          f"call loops of the six compiled and run: {SCOVER['loops']} loops "
          f"of {SCOVER['looped_calls']} calls, "
          f"{', '.join(sorted(SCOVER['looped_ops']))}",
          f"{SCOVER['loops']} loops, of {sorted(SCOVER['looped_ops'])}")
    check(SCOVER["refusals"] > 0 and MARKS["marked"] > 0,
          f"{SCOVER['refusals']} refusals `target-feature` on revision 7's "
          f"targets; the rule saw {MARKS['marked']} lanes marked and "
          f"replayed in {MARKS['comparisons']} comparisons of "
          f"{MARKS['lanes']} lanes, {MARKS['wrong']} guesses wrong in "
          f"value ({MARKS['wrong_tangents']} in tangents too), "
          f"{MARKS['wrong_flags']} in flags",
          f"{SCOVER['refusals']} refusals, {MARKS['marked']} lanes marked")


# The legs in their two groups, each with its tally: `core` the `lang`
# stage's, in the quick budget, and `routines` the `lang-routines` stage's,
# in the gate budget (verify/run.sh; the lead's split, 2026-10-02, when
# the routines' legs took `lang` past quick's three minutes). A group's
# tally runs when every leg of the group ran - `--group`, or no selection
# at all, which runs both - and where `--only` ran part of a group its
# tally is a SKIP line, never left out silently.
GROUPS = (("core", ("refs", "corpus", "letmaps", "banks", "libcft",
                    "determinism", "refusals", "plants", "readback"),
           "I, the core tally"),
          ("routines", ("routines", "pools", "loops", "rule", "six"),
           "I2, the routines' tally"))


# ---- the committed references ----------------------------------------------

def write_references():
    COMPILED.mkdir(parents=True, exist_ok=True)
    files = compiled_references()
    for p in COMPILED.iterdir():
        if p.name not in files:
            p.unlink()
    for name, data in files.items():
        (COMPILED / name).write_bytes(data)
        print(f"  wrote programs/systems/compiled/{name} ({len(data)} bytes)")
    return 0


def record_main():
    """--record: the append-only rule applied (python/cftc/outputs.py)."""
    rec = SYSTEMS / O.RECORD_NAME
    text = rec.read_text(encoding="ascii") if rec.is_file() else ""
    try:
        new, what = O.append(text, O.committed(SYSTEMS), cftc.VERSION)
    except O.RecordError as e:
        print(f"lang_check --record: refused: {e}")
        return 1
    if new != text:
        rec.write_bytes(new.encode("ascii"))
    print(f"lang_check --record: {what}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--segrun", help="host/cft-segrun, for legs E and L")
    ap.add_argument("--audit", help="host/cft-audit, for legs E and L")
    ap.add_argument("--corpus", type=int, default=48,
                    help="generated systems in leg A (default 48)")
    ap.add_argument("--letmaps", type=int, default=120,
                    help="let-heavy homed maps in leg A (default 120)")
    ap.add_argument("--hmaps", type=int, default=160,
                    help="maps reading h at random in leg J (default 160)")
    ap.add_argument("--routines", type=int, default=40,
                    help="sources that divide or take a root in leg K "
                         "(default 40)")
    ap.add_argument("--six", type=int, default=12,
                    help="generated sources that call the math library's six "
                         "in leg N2 (default 12)")
    ap.add_argument("--six-all", action="store_true",
                    help="the larger draw of the six's legs: every centre of "
                         "each structured family, both neighbours of each, "
                         "twelve ordinary lanes and every edge a function "
                         "has, in N1 and N2 (minutes more; the default is "
                         "gate-sized)")
    ap.add_argument("--group", default="",
                    help="a comma list of groups, each its legs and its tally: "
                         "core (refs, corpus, letmaps, banks, libcft, "
                         "determinism, refusals, plants, readback; the lang "
                         "stage) and routines (routines, pools, loops, rule, "
                         "six; the lang-routines stage). With neither "
                         "--group nor --only, both")
    ap.add_argument("--only", default="",
                    help="a comma list of legs: refs, corpus, letmaps, banks, "
                         "libcft, determinism, refusals, plants, readback "
                         "(the core group), routines, pools, loops, rule, "
                         "six (the routines group); a group's tally runs "
                         "only when all its legs ran, and is a SKIP line "
                         "otherwise")
    ap.add_argument("--write", action="store_true",
                    help="write programs/systems/compiled/ and exit")
    ap.add_argument("--record", action="store_true",
                    help="append to programs/systems/cftc-outputs.txt what "
                         "its append-only rule allows - a block for a new "
                         "cftc VERSION, or a new committed file's lines - "
                         "and exit; refuse anything else")
    ap.add_argument("--digests", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.digests:
        return digests_main(a.digests)
    if a.write:
        return write_references()
    if a.record:
        return record_main()
    groups = {name: legs for name, legs, _t in GROUPS}
    asked = [x for x in a.group.split(",") if x]
    only = [x for x in a.only.split(",") if x]
    known = [leg for legs in groups.values() for leg in legs]
    for g in asked:
        if g not in groups:
            ap.error(f"--group {g}: the groups are {', '.join(groups)}")
    for leg in only:
        if leg not in known:
            ap.error(f"--only {leg}: the legs are {', '.join(known)}")
    if not asked and not only:
        asked = list(groups)
    selected = {leg for g in asked for leg in groups[g]} | set(only)
    t0 = time.perf_counter()
    work = Path(tempfile.mkdtemp(prefix="lang-check-"))

    def rng(leg):
        # one generator a leg, so that a leg's lanes - and so its counts,
        # a plant's failing lanes among them - are the same whichever
        # other legs ran before it (--only)
        return random.Random(f"lang check {leg}")
    legs = [("refs", lambda: leg_references(rng("refs"))),
            ("corpus", lambda: leg_corpus(a.corpus, rng("corpus"))),
            ("letmaps", lambda: leg_letmaps(a.letmaps, rng("letmaps"))),
            ("banks", lambda: leg_banks(rng("banks"))),
            ("libcft", lambda: leg_libcft(a.segrun, a.audit, rng("libcft"),
                                          work)),
            ("determinism", lambda: leg_determinism(work)),
            ("refusals", leg_refusals),
            ("plants", lambda: leg_plants(rng("plants"), work)),
            ("readback", lambda: leg_readback(a.hmaps, rng("readback"))),
            ("routines", lambda: leg_routines(a.routines,
                                              rng("routines"))),
            ("pools", leg_routine_pools),
            ("loops", lambda: leg_call_loops(rng("loops"), a.segrun,
                                             a.audit, work)),
            ("rule", leg_rule),
            ("six", lambda: leg_six(a.six, rng, a.six_all))]
    if sorted(name for name, _fn in legs) != sorted(known):
        raise AssertionError("a leg is in no group, or a group names a leg "
                             "there is not")
    tallies = {"core": leg_coverage, "routines": leg_routine_coverage}
    try:
        for name, fn in legs:
            if name not in selected:
                continue
            t = time.perf_counter()
            fn()
            print(f"  ({name}: {time.perf_counter() - t:.1f} s)")
        # each group's tally, where its legs ran (GROUPS)
        for gname, glegs, title in GROUPS:
            ran = [leg for leg in glegs if leg in selected]
            if len(ran) == len(glegs):
                tallies[gname]()
            elif ran:
                skip(title, f"its group's legs did not all run (--only): "
                            f"{', '.join(x for x in glegs if x not in ran)} "
                            f"did not")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    dt = time.perf_counter() - t0
    print(f"\nlang_check: {TALLY.ok} ok, {TALLY.bad} FAIL, {TALLY.skip} SKIP "
          f"in {dt:.0f} s")
    for f in FAILURES[:20]:
        print(f"  FAIL  {f}")
    return 1 if TALLY.bad else 0


if __name__ == "__main__":
    sys.exit(main())
