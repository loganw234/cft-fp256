# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft-segrun held to the golden writer: the differential gate of the plan
of record's step 3 (docs/ROADMAP.md, "Segments, certificates and the
audit tool"; docs/CERTIFICATES.md, "The segment runner").

    python host/tests/segrun_check.py --tool host/cft-segrun[.exe]
                                      [--serve host/cft-serve[.exe]]
                                      [--audit host/cft-audit[.exe]]
                                      [--cc CC --lib-src "SRC ..."]
                                      [--keep DIR] [--salt-hex HEX]
    python host/tests/segrun_check.py --tool host/cft-segrun
                                      --device <image.xclbin>
                                      --expect-xclbin HEX --expect-version HEX
                                      --expect-caps "HEX [HEX]"
                                      --expect-tiles N [--no-wider]
                                      [--audit host/cft-audit]

`make -C host segruntest` runs the first with the tree's build id in
CFT_EXPECT_BUILD_ID, and verify/run.sh's `programs` stage runs that. The
second is the card leg, which hw/card-segrun.sh runs on the box with the
card, the identity it expects measured apart from the tool (sha256sum of
the image, device-test -i): each certificate is made on the card, held to
everything below, and made again on the software backend, its run blocks
and its accuracy block compared byte for byte.

First, git ignores the binary in both its forms, so a build of it leaves
the next build id clean. Then, for each program below, keyed and then
open, on the software backend, with its ACCURACY ENTRIES (ENTRIES; the
plan's step 5, 2026-09-30):
  1. cft-segrun runs it as consecutive segments, writes every boundary
     state, reads the states its entries need back from them, and writes
     the certificate, its entries' values included;
  2. the golden reader (cert.parse) accepts the certificate - with the
     salt, its commitment too;
  3. the golden writer - cert.run_chain, certify_run, derive, make_value
     and encode, handed the certificate's identity lines, the salt, the
     INITIAL states and the same entries' definitions - runs every
     segment itself and writes the same bytes, which holds the
     arithmetic, the carrying of state and every entry's value as well as
     the encoding;
  4. the states directory holds exactly the boundary files, each the
     golden chain's state at that boundary, lane-major;
  5. cert.audit accepts the certificate from the states the tool wrote:
     every segment of every run and every entry re-derived, and then a
     sample the auditor draws (its seed printed, so a red sample can be
     drawn again) - or, for the one program certified with a relation
     broken on purpose, refuses it by the name the relation's check has
     (aux-start); and with --audit, cft-audit, the C auditor, gives the
     same verdict in full, line for line, or the same refusal by name;
  6. the identity lines are the library's: build-id is what the binary's
     own `--build-id` prints and what the tree builds (CFT_EXPECT_BUILD_ID);
     the software backend's device lines are `none` and its tiles 1.
The entries between them have every method, both scopes, every form and
every rounding direction: a step-halving estimate on every ODE program, a
wider one on every fp64 one, and Henon-Heiles' energy drift, exact, whose
denominator has a 3. main() holds that, and that each direction but rup
rounds some entry's value otherwise than rup, so that a writer that
swapped its direction is seen by step 3.
Then:
  7. the page's test vectors through `cft-segrun --hash`, and every tag,
     keyed and open, against an HMAC written here from RFC 2104;
  8. every refusal an input or the instrument can cause, by its name and
     exit code (the page lists those only a failure can reach), a refusal
     before the run leaving nothing behind; for each of the page's names,
     the golden writer refusing the same defect by the same name; and each
     refusal whose command line has an --out of its own again with a file
     already there, which must come through it byte for byte - the tool
     removes only what it created;
  9. with --serve: lorenz63 and flagstep certified through a loopback
     cft-serve, stopped by its PID - backend remote, the device lines the
     page's remote rule gives, and every run block byte for byte the
     software backend's, flagstep's flag words and STATUS among them;
 10. memory. What a run beside the main run costs: flagstep on 65,535
     lanes, a main run and two half-step runs, against the main run alone
     - no more than the two runs' inputs and one state to spare, where
     4eed552 held every run's working set at once (verifier-C7's
     regression); peak commit on Windows, on Linux the least address
     space the run writes its certificate in (ulimit -v), found by
     bisection. What the accuracy entries cost: the same three runs with
     two entries that read four states back, against the runs alone - no
     more than ENTRY_ALLOWANCE (on Linux, and a bisection step), so no
     state held beside the runs', where one would be 1,024 KiB; and
     `slotstep`, written here (16 slots a lane, 8 MiB states), one run
     with two drifts of it against the run alone, within WIDE_ALLOWANCE (a
     quarter of its state) - there the entries' own phase is the peak, so
     an entry that holds a state more than its pair, or entries that hold
     more than one pair at once, fail it (verifier-W1: in flagstep's shape
     neither did). Its entries are drifts: a fault in an estimate's
     read-back alone passes both shapes (verifier-W1b). And what the
     trial costs the runs, to the page: the least address space with the
     trial and with its allocations skipped
     (CFT_SEGRUN_PLANT=trial-skipped), in two small shapes where eb2d1ae's
     trial cost them up to 40 KiB (verifier-C7), and in a third with two
     entries - on Linux; on Windows, where identical runs' peak commit
     differs by several pages, NOT TESTED, by name. A host whose hard
     address-space limit stops a measurement says NOT TESTED too, and the
     gate goes on.
 11. --scratch-depth, on the software backend (not the card leg's): the
     tool opens the backend at N through cft_open_ex and states `parameter
     scratch-depth N` in every run block, in byte order among the run's
     parameters. `deepstep`, written here, reads index 256 through a
     non-strict LDX, which is its own slot 0 at 256 slots and a slot
     nothing wrote at 2,048: certified at each, it is byte for byte the
     golden writer's at that depth, each boundary file the golden chain's,
     and the golden audit accepts it, re-running at the depth the
     certificate states; and the two depths' end states differ, so the
     program does test the depth. lorenz63's main, half-step and wider
     runs at 2,048 carry the parameter in every block and audit green.
     Its refusals - beside a device, a depth that is not a power of two in
     1..32,768 or not in its one spelling, the option twice, beside --hash
     or --build-id, and a `--param scratch-depth=` of the user's - are in
     step 8, and so are 1 and 32,768 taken, each refused only by the
     loader of a program that cannot load there.
 12. accuracy entries: every refusal an entry can meet, by its name and
     exit code, and the golden writer refusing the same defect by the same
     name wherever it has one (a spelling it cannot hold, such as a
     coefficient 2/4, it has none): the command line's own (usage); each
     spelling (malformed, and width by a coefficient's digits); the
     entry against the runs in cert.derive's order (accuracy-run, among
     them a negative run and an estimate whose run has other lanes than
     run 0; accuracy-scope and accuracy-slot, among them a negative lane
     and a negative slot) - each before anything is made,
     nothing left behind; and the values after the runs (accuracy-finite,
     width at an element, a product, a partial sum, an enclosure's end),
     each leaving the boundary files, said so. The page's orders, each
     with a control:
     1/a, 1/b, -1/b refused width where 1/b, -1/b, 1/a is written; a final
     +inf beside an initial 1,024-bit value accuracy-finite, not width;
     1/(3 x 2^900) enclosed in fp256 refused at its lower end, and written
     in fp64.
 13. the builds only this gate compiles (with --cc and --lib-src; not the
     card leg's): cft-segrun narrow, CFT_MAX_FORMAT=2 at its own 576-bit
     bigint - an entry refused build-width, nothing made, and the runs
     without entries written as the default build writes them but for
     build-id - and at CFT_BN_LIMBS=64 - exact and fp128 values written as
     the default build writes them, fp256 ones refused build-format. And
     the plant build, -DCFT_SEGRUN_PLANT_STATE_CHANGED: the first state
     read back has a bit flipped, and the run is refused `output` by the
     state's hash, no certificate written and the boundary files left;
     without entries it writes the default build's certificate. The shipped
     binary carries none of the plant build's words.

The programs: lorenz63-rk4, lorenz96-rk4 and henonheiles-lf at fp64 and
fp256, each image held to programs/MANIFEST, with its classic bank, a
half-step run beside it (the bank slots that carry h exactly halved,
twice the segments), and at fp64 a wider run - the same source assembled
at fp128 (gen_odes builds none), the bank and the initial state exactly
widened. And `flagstep`, written here: its segments raise flags 20, 0,
1, 0, 20 and STATUS 48, 48, 0, 48, 48. Every ODE segment raises 16 and 0,
so the ODE programs alone cannot tell a writer that drops STATUS, or
writes one segment's flags against another, from one that does not.
And lorenz63 at fp64 once more, its half-step run entered from an
initial state of its OWN, unlike the main run's: every other half-step
run shares run 0's, so a writer that entered a half-step run from run
0's --init would pass them all (verifier-C6's plant). The tool must
still write the golden writer's bytes for what it was handed; the audit
refuses the certificate `aux-start`.

Exit 0 only if every check passed; the last line says so.
"""

import argparse
import dataclasses
import hashlib
import hmac
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = HERE.parent
ROOT = HOST.parent
PROGRAMS = ROOT / "programs"
DOC = ROOT / "docs" / "CERTIFICATES.md"
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(PROGRAMS))

from cft_golden import FORMATS, asm, cert, chars, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
import gen_odes  # noqa: E402

# The tool's own refusals, beside the page's table (docs/CERTIFICATES.md,
# "The segment runner"): a command line, a device, memory, an output.
TOOL_OWN = {"usage": 64, "device": 69, "memory": 71, "output": 73}

# How long one run of the tool may take here before it is stopped and
# failed by name: every run the gate asks for takes well under a second,
# and a refusal that did not come - a run of 10^12 segments started -
# must end the check, not the afternoon.
TOOL_TIMEOUT = 120

# lanes and segments a main run, chosen for time: lorenz96 carries forty
# slots a lane and costs the golden executor about 0.24 s a lane-segment
# at either format (measured 2026-09-28), lorenz63 0.06 s, henonheiles
# 0.015 s.
SIZES = {"lorenz63-rk4": (3, 3), "lorenz96-rk4": (2, 2),
         "henonheiles-lf": (4, 4)}
# the bank slots that carry the step h, by their names in gen_odes
H_NAMES = ("H", "H2", "H6", "MH")

FLAGSTEP = """.format   fp64
.deposits 0
.scratch  in 2
.scratch  out 2
.scratch  strict
.const    ONE   = 0x3ff0000000000000
.const    THIRD = 0x3fd5555555555555
.const    HUGE  = 0x7fe0000000000000
.const    INF   = 0x7ff0000000000000
; slot 0 is a counter c, slot 1 a value x. Each segment: c <- c - 1;
; c/3 is inexact where c is not a power of two, c * 2^1023 overflows
; where |c| >= 2, c * inf is invalid where c = 0; x <- x c.
ldl    r3, 0
ldl    r4, 1
sub    r3, r3, ONE
mul    r5, r3, THIRD
mul    r6, r3, HUGE
mul    r7, r3, INF
mul    r4, r4, r3
stl    r3, 0
stl    r4, 1
; STATUS: an indexed load at c's bit pattern is past the scratch in a
; strict image unless c = +0 (bit 5); setact leaves active every lane
; whose c is not 0, and each deposits past max_deposits 0 (bit 4)
ldx    r8, r3
setact r3
deposit r4
actall
halt
"""
FLAGSTEP_FLAGS = [20, 0, 1, 0, 20]
FLAGSTEP_STATUS = [48, 48, 0, 48, 48]

# The mark's leg (revision 8's R24, ABI 0.17): STATUS[6], CFT_STATUS_MARKED,
# from the software backend into a certificate's segment line - through
# cft-segrun, the golden writer, both auditors, and a loopback cft-serve.
# Slot 0 holds an integer bit pattern c; each segment decrements it and
# raises it, so its low five bits are the segment's flags and its bit 7
# marks the lane. Lane 0 starts at 0x83 and lane 1 at 0x05: lane 0 marks in
# the first three segments (0x82, 0x81, 0x80) and not after (0x7f, 0x7e).
MARKSTEP = """.format   fp64
.deposits 0
.scratch  in 1
.scratch  out 1
.const    ONE = 0x0000000000000001
; slot 0: an integer c. Each segment: c <- c - 1, then raise c - its
; bits [4:0] reach FLAGS and its bit 7 marks the lane (STATUS[6])
ldl    r3, 0
isub   r3, r3, ONE
raise  r3
stl    r3, 0
halt
"""
MARKSTEP_FLAGS = [6, 3, 2, 31, 30]
MARKSTEP_STATUS = [64, 64, 64, 0, 0]

# The depth leg's program (section 11): its answer depends on the scratch
# depth. It is written here rather than taken from certificates/, so that
# the tool's gate and the golden-certificate corpus share no input.
DEEPSTEP = """.format   fp64
.deposits 0
.scratch  in 2
.scratch  out 2
.const    I256 = 0x0000000000000100
.const    ONE  = 0x3ff0000000000000
; slot 0 is x, slot 1 is y. Each segment: y <- y + scratch[256 mod D],
; then x <- x + 1. A non-strict LDX reduces its index modulo the depth D:
; at 256 slots index 256 is slot 0, so y gathers x; at 2,048 it is a
; slot nothing wrote, +0, so y holds.
ldl    r3, 0
ldl    r4, 1
iadd   r6, r6, I256
ldx    r5, r6
add    r4, r4, r5
add    r3, r3, ONE
stl    r3, 0
stl    r4, 1
halt
"""
DEPTH_PARAM = "scratch-depth"

CHECKS = 0
FAILED = []
SKIPS = []


def ok(what):
    global CHECKS
    CHECKS += 1
    print(f"  ok    {what}", flush=True)


def bad(what):
    global CHECKS
    CHECKS += 1
    FAILED.append(what)
    print(f"  FAIL  {what}", flush=True)


def check(cond, what, why=""):
    if cond:
        ok(what)
    else:
        bad(what + (f" - {why}" if why else ""))
    return cond


def skip(what, why):
    SKIPS.append(what)
    print(f"SKIP  {what}: {why}", flush=True)


def dec(fmt, text):
    return chars.from_decimal(FORMATS[fmt], text, sf.RND_RNE)[0]


# ---- the programs -------------------------------------------------------

@dataclasses.dataclass
class RunSpec:
    kind: str           # main, half-step or wider
    image: bytes
    bank: bytes
    init: list          # the initial state's values, lane-major
    fmt: str
    segments: int
    steps: int
    params: tuple = ()
    h_slots: tuple = ()


@dataclasses.dataclass
class Program:
    name: str
    runs: list
    # None: the golden audit must accept the certificate. A refusal's
    # name: the certificate carries a relation broken on purpose, and the
    # audit must refuse it by that name, full and sampled alike.
    audit_refuses: str = None
    # the accuracy entries it is certified with (attach_entries)
    entries: list = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class EntrySpec:
    """An accuracy entry's definition, as the tool takes it on its command
    line and the golden writer as a cert.Entry: never its value."""
    method: str             # drift, step-halving or wider
    uses: int
    lane: object            # a lane, or None for max-lanes
    form: str               # exact, rounded or enclosed
    fmt: str = None
    rnd: str = None
    label: str = None       # a drift's
    terms: tuple = ()       # a drift's: ((coefficient, (slot, ...)), ...)


# Henon-Heiles' energy over (x, y, px, py) = slots (0, 1, 2, 3):
# (px^2 + py^2)/2 + (x^2 + y^2)/2 + x^2 y - y^3/3, the page's example's
# quantity, whose y^3/3 leaves a 3 in the drift's denominator
ENERGY = ((Fraction(1, 2), (2, 2)), (Fraction(1, 2), (3, 3)),
          (Fraction(1, 2), (0, 0)), (Fraction(1, 2), (1, 1)),
          (Fraction(1), (0, 0, 1)), (Fraction(-1, 3), (1, 1, 1)))
FLAG_C = ((Fraction(1), (0,)),)     # flagstep's counter, slot 0

# Each program's entries: between them every method, scope, form and
# rounding direction. A step-halving estimate on every ODE program, a
# wider one on every fp64 one, and Henon-Heiles' energy drift, exact,
# whose denominator has a 3. A difference of two values of one format is
# exact in it when they have one sign and each is within a factor of two
# of the other (Sterbenz's lemma), and the step-halving runs here end
# that close: all 210 pairs of final elements, run 0's beside its
# half-step run's, meet the condition and differ exactly (measured
# 2026-09-30). So a rounded or enclosed estimate names a
# narrower format, and a drift, with its 3, rounds inexactly in any:
# main() holds that each direction but rup rounds otherwise than rup
# somewhere, so that a writer that swapped its direction is seen.
ENTRIES = {
    "lorenz63-rk4-fp64": [
        EntrySpec("step-halving", 1, None, "enclosed", "fp32"),
        EntrySpec("wider", 2, None, "rounded", "fp32", "rne"),
        EntrySpec("wider", 2, 0, "enclosed", "fp64")],
    "lorenz63-rk4-fp256": [
        EntrySpec("step-halving", 1, 1, "rounded", "fp128", "rmm")],
    "lorenz96-rk4-fp64": [
        EntrySpec("step-halving", 1, None, "exact"),
        EntrySpec("wider", 2, None, "rounded", "fp32", "rtz")],
    "lorenz96-rk4-fp256": [
        EntrySpec("step-halving", 1, 0, "enclosed", "fp128")],
    "henonheiles-lf-fp64": [
        EntrySpec("drift", 0, 1, "exact", label="energy", terms=ENERGY),
        EntrySpec("drift", 0, None, "rounded", "fp64", "rdn",
                  label="energy", terms=ENERGY),
        EntrySpec("step-halving", 1, None, "rounded", "fp64", "rup"),
        EntrySpec("wider", 2, 3, "enclosed", "fp32")],
    "henonheiles-lf-fp256": [
        EntrySpec("drift", 0, None, "exact", label="energy", terms=ENERGY),
        EntrySpec("drift", 0, 2, "enclosed", "fp64", label="energy",
                  terms=ENERGY),
        EntrySpec("step-halving", 1, 0, "exact")],
    # every lane's counter falls by one a segment, 3 to -2: each drift is
    # -5, so a max-lanes that took the signed maximum writes -5, not 5
    "flagstep-fp64": [
        EntrySpec("drift", 0, None, "exact", label="c", terms=FLAG_C)],
}


def attach_entries(programs):
    """Each program's entries (ENTRIES), leaving out any that uses a run
    the program does not have (--no-wider drops the wider runs). No
    check() here: audit_check's section 3 counts the constructors'."""
    for p in programs:
        p.entries = [e for e in ENTRIES.get(p.name, [])
                     if e.uses < len(p.runs)]
    return programs


def entry_options(entries):
    """cft-segrun's options for entries (docs/CERTIFICATES.md, "The
    segment runner"), written again here from the page, not imported."""
    a = []
    for e in entries:
        a += ["--entry", e.method, "--uses", str(e.uses), "--scope",
              "max-lanes" if e.lane is None else f"lane:{e.lane}"]
        if e.label is not None:
            a += ["--quantity", e.label]
        for c, slots in e.terms:
            a += ["--term", ",".join([cert.rational_text(Fraction(c))]
                                     + [f"s{s}" for s in slots])]
        a += ["--value", "exact" if e.form == "exact" else
              f"rounded:{e.fmt}:{e.rnd}" if e.form == "rounded" else
              f"enclosed:{e.fmt}"]
    return a


def golden_entries(entries, runs, specs, chains):
    """The golden writer's entries: cert.derive on the golden chains' first
    and last states, then cert.make_value, as corpus.py's golden_entries
    and test_cert's entry_with make them."""
    ends = {}
    for r, (st, _) in enumerate(chains):
        ends[(r, 0)] = st[0]
        ends[(r, len(st) - 1)] = st[-1]
    shapes = [(FORMATS[s.fmt], seq.Program.from_bytes(s.image).n_scratch_in)
              for s in specs]
    out = []
    for e in entries:
        probe = cert.Entry(e.method, cert.METHOD_KIND.get(e.method, "bound"),
                           e.uses, e.lane,
                           cert.Value("exact", exact=Fraction(0)), e.label,
                           tuple(e.terms))
        q = cert.derive(probe, runs, shapes, ends)
        out.append(dataclasses.replace(probe, value=cert.make_value(
            q, e.form, e.fmt, e.rnd)))
    return tuple(out)


def halved(fmt, bank, slots):
    """The bank with each named slot exactly halved (test_cert's
    `halved`): the half-step bank of the plan."""
    vals = cert.state_values(fmt, bank)
    for s in slots:
        vals[s], fl = sf.mul(FORMATS[fmt], vals[s], dec(fmt, "0.5"))
        assert fl == 0, "halving is exact for these banks"
    return cert.state_bytes(fmt, vals)


def ensemble(base, fmt, lanes):
    """Each lane displaced from the first by an exact dyadic amount, as
    programs/check.py's ensembles are - written again here, not imported."""
    out = []
    for i in range(lanes):
        if base == "lorenz63-rk4":
            out += [dec(fmt, repr(1 + i / 64)), dec(fmt, "1"), dec(fmt, "1")]
        elif base == "lorenz96-rk4":
            out += [dec(fmt, repr(8 + (i + 1) / 1024))] + \
                   [dec(fmt, "8")] * (gen_odes.L96_N - 1)
        else:
            out += [dec(fmt, "0"), dec(fmt, repr(0.1 + i / 1024)),
                    dec(fmt, "0.5"), dec(fmt, "0")]
    return out


def manifest():
    m = {}
    text = (PROGRAMS / "MANIFEST").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            h, name = line.split()
            m[name] = h
    return m


def ode_program(base, fmt, man):
    name = f"{base}-{fmt}"
    src = (PROGRAMS / f"{name}.cfta").read_text(encoding="utf-8")
    img = asm.assemble(src, name)
    check(cert.sha256(img) == man.get(name + ".cftp"),
          f"{name}: the image assembled here is programs/MANIFEST's "
          f"({cert.sha256(img)[:16]}...)")
    bank = (PROGRAMS / f"{name}.classic.bank").read_bytes()
    names = [n for n, _ in gen_odes.bank_values(base, FORMATS[fmt])]
    h_slots = tuple(i for i, n in enumerate(names) if n in H_NAMES)
    lanes, S = SIZES[base]
    init = ensemble(base, fmt, lanes)
    steps = gen_odes.STEPS[base]
    runs = [RunSpec("main", img, bank, init, fmt, S, steps,
                    params=(("ensemble-spread", 64), ("members", lanes))),
            RunSpec("half-step", img, halved(fmt, bank, h_slots), init, fmt,
                    2 * S, steps, params=(("members", lanes),),
                    h_slots=h_slots)]
    if fmt == "fp64":
        # one format wider, as test_cert.py builds it: the source's format
        # line changed, the bank and the start exactly widened
        line = ".format   fp64"
        assert src.count(line) == 1, f"{name}: no single '{line}' line"
        img128 = asm.assemble(src.replace(line, ".format   fp128"),
                              f"{base}-fp128")
        bank_w = cert.state_bytes("fp128", [cert.widen("fp64", x) for x in
                                            cert.state_values("fp64", bank)])
        runs.append(RunSpec("wider", img128, bank_w,
                            [cert.widen("fp64", x) for x in init], "fp128", S,
                            steps))
    return Program(name, runs)


def flagstep_program():
    img = asm.assemble(FLAGSTEP, "flagstep")
    init = [dec("fp64", "3"), dec("fp64", "1"), dec("fp64", "3"),
            dec("fp64", "5")]
    return Program("flagstep-fp64",
                   [RunSpec("main", img, b"", init, "fp64", 5, 1)])


def markstep_program():
    img = asm.assemble(MARKSTEP, "markstep")
    return Program("markstep-fp64",
                   [RunSpec("main", img, b"", [0x83, 0x05], "fp64", 5, 1)])


def half_init_program(l63):
    """lorenz63 at fp64 (`l63`, the gate's own) with its half-step run
    entered from an initial state of its own: every lane's x a further
    1/128 along, exactly. Every other half-step run in the gate shares run
    0's initial state, so a writer that entered a half-step run from run
    0's --init would pass them all (verifier-C6, 2026-09-28). The
    certificate states a relation that does not hold, and the audit
    refuses it aux-start; the tool is still held to the golden writer's
    bytes for what it was handed."""
    main, half = l63.runs[0], l63.runs[1]
    assert (main.kind, half.kind) == ("main", "half-step")
    lanes = len(main.init) // 3
    other = []
    for i in range(lanes):
        other += [dec("fp64", repr(1 + i / 64 + 1 / 128)), dec("fp64", "1"),
                  dec("fp64", "1")]
    assert other != main.init and len(other) == len(main.init)
    return Program("lorenz63-rk4-fp64-half-init",
                   [main, dataclasses.replace(half, init=other)],
                   audit_refuses="aux-start")


# ---- the tool -------------------------------------------------------------

TOOL = SERVE = None
SALT = None
EXPECT_ID = None


def as_v1(args):
    """A certificate's command line as sections 1 to 13 give it: since
    certificate version 2's C half cft-segrun writes version 2 by default,
    and those sections hold version 1, byte for byte what the tool wrote
    before, so each asks for it - `--format-version 1` before the rest -
    unless it names a version itself. A command line with no --out (the
    small modes, and the refusals that leave it out) is as given."""
    a = [str(x) for x in args]
    if "--out" in a and "--format-version" not in a:
        return ["--format-version", "1"] + a
    return a


def run_tool(args, env=None, binary=None, v2=False):
    """The tool (or another build of it, `binary`) on `args`, version 1's
    command line (as_v1) unless `v2` (section 14)."""
    e = dict(os.environ)
    e.pop("CFT_SEGRUN_PLANT", None)
    if env:
        e.update(env)
    if not v2:
        args = as_v1(args)
    try:
        # the tool writes UTF-8 (its paths and values are the process's
        # own text, section 14's leg i), which a console's code page
        # cannot always decode
        r = subprocess.run([str(binary or TOOL)] + [str(a) for a in args],
                           capture_output=True, encoding="utf-8",
                           errors="replace", env=e, timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return (-1, "", f"segrun_check: the tool ran past {TOOL_TIMEOUT} s "
                        f"and was stopped")
    return r.returncode, r.stdout, r.stderr


def write_inputs(work, prog):
    d = work / "inputs" / prog.name
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for r, spec in enumerate(prog.runs):
        img = d / f"run{r}.cftp"
        img.write_bytes(spec.image)
        bank = None
        if spec.bank:
            bank = d / f"run{r}.bank"
            bank.write_bytes(spec.bank)
        init = d / f"run{r}.init"
        init.write_bytes(cert.state_bytes(spec.fmt, spec.init))
        out.append((img, bank, init))
    return out


def tool_args(prog, paths, out, states, salt_path, device="sw"):
    """Version 1's command line for `prog` (section 14 has its own): it
    names the version itself, so a caller that runs the tool directly -
    audit_check's section 3 - gets version 1 as these sections do."""
    args = ["--format-version", "1", "--out", out, "--states", states]
    args += ["--salt", salt_path] if salt_path else ["--open"]
    args += ["--device", device]
    for spec, (img, bank, init) in zip(prog.runs, paths):
        args += ["--run", spec.kind]
        if spec.kind == "half-step":
            args += ["--h-slots", ",".join(str(s) for s in spec.h_slots)]
        args += ["--image", img]
        if bank:
            args += ["--bank", bank]
        args += ["--init", init, "--segments", spec.segments,
                 "--steps", spec.steps]
        for n, v in spec.params:
            args += ["--param", f"{n}={v}"]
    return args + entry_options(prog.entries)


# ---- the golden writer -------------------------------------------------

def golden_certificate(prog, chains, salt, identity):
    runs = tuple(cert.certify_run(spec.kind, spec.image, spec.bank, salt, st,
                                  rs, steps=spec.steps,
                                  parameters=spec.params,
                                  h_slots=spec.h_slots,
                                  scratch_depth=DEPTH,
                                  main_image=prog.runs[0].image)
                 for spec, (st, rs) in zip(prog.runs, chains))
    return cert.encode(cert.Certificate(
        "keyed" if salt is not None else "open",
        cert.salt_commitment(salt) if salt is not None else None,
        identity, runs, golden_entries(prog.entries, runs, prog.runs,
                                       chains)))


def first_difference(a, b):
    la = a.decode("ascii", "replace").split("\n")
    lb = b.decode("ascii", "replace").split("\n")
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"line {i + 1}: the tool's {x[:110]!r}, golden {y[:110]!r}"
    return f"{len(la)} lines against {len(lb)}"


def boundary_file(sdir, r, b):
    return sdir / f"run-{r}-boundary-{b}.bin"


def hold_identity(what, idn, backend):
    rc, out, _ = run_tool(["--build-id"])
    own = out.strip()
    check(rc == 0 and idn.build_id == own,
          f"{what}: build-id is cft_build_id() as the binary prints it",
          f"the certificate says {idn.build_id!r}, --build-id {own!r}")
    if EXPECT_ID is not None:
        check(idn.build_id == EXPECT_ID,
              f"{what}: build-id is the tree's ({EXPECT_ID[:22]}...)",
              f"the certificate says {idn.build_id!r}: a stale binary, or an "
              f"id from somewhere other than the library")
    want = {"software": ("software", "none", "none", "none", 1),
            "remote": ("remote", "unknown", "unknown", "unknown", 1),
            "xrt": EXPECT_XRT}[backend]
    got = (idn.backend, idn.device_xclbin, idn.device_version,
           idn.device_caps, idn.device_tiles)
    check(got == want, f"{what}: backend and device lines are the library's "
          f"answers for a {backend} handle {want}", f"got {got}")


def certify_and_hold(prog, chains, mode, work, device="sw", tag="",
                     may_refuse_load=False):
    """Steps 1 to 6 for one program in one mode. -> (bytes, states dir),
    or None. With may_refuse_load, a device that refuses to load the
    image (program-image) is a NOTE, not a failure: the card leg's
    `flagstep`, which needs features the brief's six programs do not."""
    salt = SALT if mode == "keyed" else None
    what = f"{prog.name} {mode}{tag}"
    stem = work / "out" / f"{prog.name}-{mode}{tag.replace(' ', '-')}"
    stem.parent.mkdir(parents=True, exist_ok=True)
    out, sdir = Path(str(stem) + ".cert"), Path(str(stem) + ".states")
    salt_path = work / "salt.bin" if salt is not None else None
    t0 = time.perf_counter()
    rc, so, se = run_tool(tool_args(prog, PATHS[prog.name], out, sdir,
                                    salt_path, device))
    if may_refuse_load and rc == cert.REFUSALS["program-image"] and \
            "refused program-image: " in se and "cft_program_load" in se:
        print(f"  NOTE  {what}: NOT TESTED - this device refuses the image: "
              f"{se.strip()[-300:]}", flush=True)
        return None
    if not check(rc == 0, f"{what}: cft-segrun exits 0 "
                 f"({time.perf_counter() - t0:.1f} s)",
                 f"rc {rc}: {se.strip()[-400:]}"):
        return None
    data = out.read_bytes()
    try:
        parsed = cert.parse(data, salt=salt)
        ok(f"{what}: the golden reader accepts it ({len(data)} bytes"
           f"{', the salt its commitment' if salt is not None else ''})")
    except cert.Refusal as e:
        bad(f"{what}: the golden reader refuses it: {e}")
        return None
    gold = golden_certificate(prog, chains, salt, parsed.identity)
    check(gold == data, f"{what}: the golden writer, running every segment "
          f"itself from the initial states, writes the same bytes",
          first_difference(data, gold))
    want = sorted(boundary_file(sdir, r, b).name
                  for r, (st, _) in enumerate(chains) for b in range(len(st)))
    have = sorted(os.listdir(sdir)) if sdir.is_dir() else []
    check(have == want, f"{what}: the states directory holds exactly the "
          f"{len(want)} boundary files", f"it holds {have[:6]}...")
    wrong = [(r, b) for r, (st, _) in enumerate(chains)
             for b in range(len(st))
             if not boundary_file(sdir, r, b).is_file()
             or boundary_file(sdir, r, b).read_bytes()
             != cert.state_bytes(prog.runs[r].fmt, st[b])]
    check(not wrong, f"{what}: every boundary file is the golden chain's "
          f"state there, lane-major", f"(run, boundary) {wrong[:4]} differ")
    states = {r: {b: boundary_file(sdir, r, b).read_bytes()
                  for b in range(len(st))
                  if boundary_file(sdir, r, b).is_file()}
              for r, (st, _) in enumerate(chains)}
    progs = {r: (spec.image, spec.bank) for r, spec in enumerate(prog.runs)}
    choose = {r: ("sample", max(1, spec.segments // 2))
              for r, spec in enumerate(prog.runs)}
    golden_full = None
    if prog.audit_refuses:
        # a relation broken on purpose: the audit must refuse it by its
        # check's name, full and sampled alike (relations come before any
        # re-run)
        golden_full = ("refused", prog.audit_refuses)
        for how, kw in (("in full", {}), ("sampled", {"choose": choose})):
            try:
                cert.audit(data, salt, progs, states=states, **kw)
                bad(f"{what}: the golden audit ACCEPTS it {how}, and its "
                    f"relation is broken on purpose")
            except cert.Refusal as e:
                check(e.name == prog.audit_refuses,
                      f"{what}: the golden audit refuses it {how}, "
                      f"{prog.audit_refuses}, as its broken relation must be",
                      f"it says {e.name}: {e.message}")
    else:
        try:
            t0 = time.perf_counter()
            v = cert.audit(data, salt, progs, states=states)
            golden_full = ("accepted", v.lines())
            check([len(x["rerun"]) for x in v.runs] ==
                  [spec.segments for spec in prog.runs],
                  f"{what}: the golden audit ACCEPTS it, every segment of "
                  f"every run re-run from the states the tool wrote"
                  f"{', every entry re-derived' if prog.entries else ''} "
                  f"({time.perf_counter() - t0:.1f} s)")
        except cert.Refusal as e:
            bad(f"{what}: the golden audit refuses it: {e.name}: "
                f"{e.message}")
        try:
            v = cert.audit(data, salt, progs, states=states, choose=choose)
            ok(f"{what}: the golden audit ACCEPTS a sample of "
               f"{[len(x['rerun']) for x in v.runs]} segments, seed "
               f"{v.runs[0]['seed']}")
        except cert.Refusal as e:
            bad(f"{what}: the golden audit refuses a sample: {e.name}: "
                f"{e.message}")
    if AUDIT is not None and golden_full is not None:
        hold_cft_audit(what, prog, data, salt, sdir, golden_full, work)
    hold_identity(what, parsed.identity,
                  "remote" if device.startswith("cft://") else
                  "software" if device == "sw" else "xrt")
    return data, sdir


def hold_cft_audit(what, prog, data, salt, sdir, golden_full, work):
    """The C auditor, cft-audit, on the tool's certificate, in full from
    the states the tool wrote: the golden audit's verdict line for line,
    each entry's re-derived value among them, or its refusal by name - so
    that both auditors accept each certificate (the plan's step 5)."""
    d = work / "audit" / re.sub(r"[^A-Za-z0-9.-]+", "-", what)
    d.mkdir(parents=True, exist_ok=True)
    cp = d / "c.cert"
    cp.write_bytes(data)
    args = ["--cert", cp, "--states", sdir]
    if salt is not None:
        (d / "salt.bin").write_bytes(salt)
        args += ["--salt", d / "salt.bin"]
    for r, (img, bank, _) in enumerate(PATHS[prog.name]):
        args += ["--run", str(r), "--image", img]
        if bank:
            args += ["--bank", bank]
    e = dict(os.environ)
    e.pop("CFT_AUDIT_PLANT", None)
    try:
        p = subprocess.run([str(AUDIT)] + [str(a) for a in args],
                           capture_output=True, text=True, env=e,
                           timeout=TOOL_TIMEOUT)
        rc, out, err = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        rc, out, err = -1, "", f"stopped after {TOOL_TIMEOUT} s"
    if golden_full[0] == "accepted":
        got = out.split("\n")
        if got and got[-1] == "":
            got = got[:-1]
        diff = next((f"line {i + 1}: golden {x!r}, cft-audit {y!r}"
                     for i, (x, y) in enumerate(zip(golden_full[1], got))
                     if x != y), f"{len(golden_full[1])} lines against "
                                 f"{len(got)}")
        check(rc == 0 and got == list(golden_full[1]),
              f"{what}: cft-audit ACCEPTS it in full from the states the "
              f"tool wrote, the golden verdict line for line"
              f"{' (its entries re-derived)' if prog.entries else ''}",
              f"exit {rc}: {err.strip()[-240:] or diff}")
    else:
        name = golden_full[1]
        m = re.search(r"cft-audit: refused ([a-z-]+):", err)
        check(rc == cert.REFUSALS[name] and m is not None and
              m.group(1) == name, f"{what}: cft-audit refuses it {name}, as "
              f"the golden audit does", f"exit {rc}: {err.strip()[-240:]}")


def runs_part(data):
    """A certificate's body from its `runs` line to `end`: every run
    block, without the identity lines."""
    L = cert.body_of(data).decode("ascii").split("\n")
    return L[next(i for i, x in enumerate(L) if x.startswith("runs ")):]


# ---- the hashes against the page and RFC 2104 ----------------------------

def rfc2104(key, msg):
    """HMAC-SHA-256 written out from RFC 2104 with hashlib alone."""
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key = key.ljust(64, b"\x00")
    inner = hashlib.sha256(bytes(x ^ 0x36 for x in key) + msg).digest()
    return hashlib.sha256(bytes(x ^ 0x5C for x in key) + inner).hexdigest()


def hold_ignored():
    """The binary, in both its forms, is ignored by git, so building it
    never makes the next build id untracked=present. .gitignore says
    adding a tool needs a line there as well as in host/Makefile; this
    tool went without it until its own Linux build showed `?? host/
    cft-segrun` (2026-09-28)."""
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse",
                            "--is-inside-work-tree"], capture_output=True,
                           text=True)
    except OSError:
        r = None
    if r is None or r.returncode != 0 or r.stdout.strip() != "true":
        skip("git ignores host/cft-segrun", "this tree is in no git "
             "repository")
        return
    for p in ("host/cft-segrun", "host/cft-segrun.exe"):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", p])
        check(r.returncode == 0, f"git ignores {p}, so a build of it leaves "
              f"the next build id clean", f"git check-ignore exits "
              f"{r.returncode}")


def hold_hashes(work):
    print("== 7. the hashes: the page's test vectors, and every tag against "
          "RFC 2104", flush=True)
    text = DOC.read_text(encoding="utf-8")
    at = text.index("<!-- the test vectors -->")
    block = re.search(r"```[a-z]*\n(.*?)```", text[at:], re.S).group(1)
    rows = dict(ln.split(None, 1) for ln in block.strip().split("\n"))
    d = work / "vectors"
    d.mkdir(parents=True, exist_ok=True)
    (d / "salt").write_bytes(bytes.fromhex(rows["salt"]))
    (d / "state").write_bytes(bytes.fromhex(rows["state-bytes"]))
    (d / "stream").write_bytes(bytes.fromhex(rows["stream-a-bytes"]))
    for row, args in (
            ("salt-commitment", ["--hash", "commitment", "--salt", d / "salt"]),
            ("state-hash", ["--hash", "state", d / "state", "--salt",
                            d / "salt"]),
            ("open-state-hash", ["--hash", "state", d / "state", "--open"]),
            ("stream-a-hash", ["--hash", "stream-a", d / "stream", "--salt",
                               d / "salt"])):
        rc, out, err = run_tool(args)
        check(rc == 0 and out.strip() == rows[row],
              f"the page's {row}: {rows[row][:16]}...",
              f"cft-segrun --hash says {out.strip() or err.strip()!r}")
    # every tag, keyed and open, on bytes the page does not print
    salt = hashlib.sha256(b"segrun_check: a salt for the tag check").digest()
    body = bytes(range(256)) * 3 + b"\x00\x01"
    (d / "salt2").write_bytes(salt)
    (d / "body").write_bytes(body)
    tags = {"state": b"cft-certificate 1 state\x00",
            "stream-a": b"cft-certificate 1 stream a\x00",
            "stream-b": b"cft-certificate 1 stream b\x00",
            "stream-c": b"cft-certificate 1 stream c\x00"}
    seen = set()
    for kind, tag in tags.items():
        rc, out, _ = run_tool(["--hash", kind, d / "body", "--salt",
                               d / "salt2"])
        check(rc == 0 and out.strip() == rfc2104(salt, tag + body),
              f"{kind}, keyed: HMAC-SHA-256 of its tag, the NUL and the bytes")
        rc2, out2, _ = run_tool(["--hash", kind, d / "body", "--open"])
        check(rc2 == 0 and out2.strip()
              == hashlib.sha256(tag + body).hexdigest(),
              f"{kind}, open: SHA-256 of its tag, the NUL and the bytes")
        seen |= {out.strip(), out2.strip()}
    rc, out, _ = run_tool(["--hash", "commitment", "--salt", d / "salt2"])
    check(rc == 0 and out.strip()
          == rfc2104(salt, b"cft-certificate 1 salt"),
          "the salt commitment: HMAC of the tag alone, no NUL")
    check(len(seen) == 8, "eight tags and modes, eight different hashes")


# ---- the refusals -----------------------------------------------------------

REFUSED = re.compile(r"cft-segrun: refused ([a-z-]+):")


def golden_write(runs_specs, salt=None):
    """The golden writer on RunSpecs: run_chain, certify_run, encode."""
    runs = []
    for spec in runs_specs:
        st, rs = cert.run_chain(spec.image, spec.bank, spec.init,
                                spec.segments, scratch_depth=DEPTH)
        runs.append(cert.certify_run(spec.kind, spec.image, spec.bank, salt,
                                     st, rs, steps=spec.steps,
                                     parameters=spec.params,
                                     h_slots=spec.h_slots,
                                     scratch_depth=DEPTH,
                                     main_image=runs_specs[0].image))
    return cert.encode(cert.Certificate(
        "keyed" if salt is not None else "open",
        cert.salt_commitment(salt) if salt is not None else None,
        cert.Identity(), tuple(runs), ()))


def golden_flags(spec, flags):
    """The golden writer handed one segment whose flag word is `flags`,
    as a producer's own results (certify_run takes them)."""
    st, rs = cert.run_chain(spec.image, spec.bank, spec.init, 1,
                            scratch_depth=DEPTH)
    run = cert.certify_run("main", spec.image, spec.bank, None, st,
                           [(flags, rs[0][1])], steps=spec.steps,
                           scratch_depth=DEPTH)
    return cert.encode(cert.Certificate("open", None, cert.Identity(),
                                        (run,), ()))


def hold_refusals(work, l63, flag):
    print("== 8. the refusals: each by its name and exit code; the page's "
          "names, the golden writer's for the same defect", flush=True)
    d = work / "refusals"
    d.mkdir(parents=True, exist_ok=True)
    main = l63.runs[0]
    fmt = main.fmt
    img, bank = main.image, main.bank
    init = cert.state_bytes(fmt, main.init)
    fimg, finit = flag.runs[0].image, cert.state_bytes(
        "fp64", flag.runs[0].init)

    def f(name, data):
        p = d / name
        p.write_bytes(data)
        return p

    P = {"img": f("l63.cftp", img), "bank": f("l63.bank", bank),
         "init": f("l63.init", init), "fimg": f("flag.cftp", fimg),
         "finit": f("flag.init", finit),
         "salt": f("salt.bin", bytes(range(32)))}
    P["salt31"] = f("salt31.bin", bytes(31))
    P["salt33"] = f("salt33.bin", bytes(33))
    P["bank-short"] = f("bank-short", bank[:-8])
    P["eight"] = f("eight", bytes(8))
    P["img-trunc"] = f("trunc.cftp", img[:-8])
    # the flagstep image with its last word, HALT, made an unknown control
    # code: the header describes the bytes, and the loader refuses them
    bad_ctl = bytearray(fimg)
    assert bad_ctl[-8:-4] == (1 << 31).to_bytes(4, "little"), "HALT last"
    bad_ctl[-8:-4] = ((1 << 31) | 0x7F).to_bytes(4, "little")
    P["img-ctl"] = f("ctl.cftp", bytes(bad_ctl))
    try:
        seq.Program.from_bytes(bytes(bad_ctl))
        bad("the planted control code: the golden loader accepts it, so it "
            "tests nothing")
    except seq.ProgramError:
        pass
    div = asm.assemble((PROGRAMS / "div-fp64.cfta").read_text(
        encoding="utf-8"), "div-fp64")
    P["img-noio"] = f("div.cftp", div)
    inout = asm.assemble(".format   fp64\n.deposits 0\n.scratch  in 2\n"
                         ".scratch  out 1\nldl  r3, 0\nstl  r3, 0\nhalt\n",
                         "in2out1")
    P["img-inout"] = f("inout.cftp", inout)
    depo = asm.assemble(".format   fp64\n.deposits 1\n.scratch  in 1\n"
                        ".scratch  out 1\nldl  r3, 0\ndeposit r3\n"
                        "stl  r3, 0\nhalt\n", "deposits")
    P["img-dep"] = f("dep.cftp", depo)
    P["init-part"] = f("init-part", init[:-8])
    P["init-ragged"] = f("init-ragged", init[:-1])
    P["init-empty"] = f("init-empty", b"")
    half_bank = f("l63.half", l63.runs[1].bank)
    exists = d / "exists"
    exists.mkdir(exist_ok=True)
    # a file already at --out: every refusal must leave it byte for byte
    kept = b"a file that was at --out before the run\n" + bytes(range(256))
    P["existing"] = f("existing.cert", kept)

    def base(out, sdir, image="img", bnk="bank", ini="init", seg="1",
             steps="100", mode=("--salt", P["salt"]), extra=(), runs=None):
        a = ["--out", out, "--states", sdir, *mode]
        if runs is not None:
            return a + list(runs) + list(extra)
        a += ["--run", "main", "--image", P[image]]
        if bnk:
            a += ["--bank", P[bnk]]
        a += ["--init", P[ini], "--segments", seg, "--steps", steps]
        return a + list(extra)

    def spec(**kw):
        s = dict(kind="main", image=img, bank=bank, init=main.init, fmt=fmt,
                 segments=1, steps=100)
        s.update(kw)
        return RunSpec(**s)

    half_run = ["--run", "half-step", "--h-slots", "0,1,2", "--image",
                P["img"], "--bank", half_bank, "--init", P["init"],
                "--segments", "2", "--steps", "100"]
    main_run = ["--run", "main", "--image", P["img"], "--bank", P["bank"],
                "--init", P["init"], "--segments", "1", "--steps", "100"]
    half_spec = spec(kind="half-step", bank=l63.runs[1].bank, segments=2,
                     h_slots=(0, 1, 2))

    # (label, name, the tool's arguments, env, the golden writer's twin)
    cases = [
        ("a 31-byte salt", "salt-length",
         lambda o, s: base(o, s, mode=("--salt", P["salt31"])), None,
         lambda: cert.salt_commitment(bytes(31))),
        ("a 33-byte salt", "salt-length",
         lambda o, s: base(o, s, mode=("--salt", P["salt33"])), None,
         lambda: cert.salt_commitment(bytes(33))),
        ("an image cut short", "program-image",
         lambda o, s: base(o, s, image="img-trunc"), None, None),
        ("an image the loader refuses (an unknown control code)",
         "program-image",
         lambda o, s: base(o, s, image="img-ctl", bnk=None, ini="finit"),
         None, None),
        ("a bank one element short", "program-image",
         lambda o, s: base(o, s, bnk="bank-short"), None,
         lambda: golden_write([spec(bank=bank[:-8])])),
        ("no bank for a BANK_EXT image", "program-image",
         lambda o, s: base(o, s, bnk=None), None,
         lambda: golden_write([spec(bank=b"")])),
        ("a bank for an image that carries its constants", "program-image",
         lambda o, s: base(o, s, image="fimg", bnk="eight", ini="finit"),
         None,
         lambda: golden_write([spec(image=fimg, bank=bytes(8),
                                    init=flag.runs[0].init)])),
        ("no scratch block (div-fp64)", "program-shape",
         lambda o, s: base(o, s, image="img-noio", bnk=None), None,
         lambda: golden_write([spec(image=div, bank=b"", init=[])])),
        ("scratch in 2, out 1", "program-shape",
         lambda o, s: base(o, s, image="img-inout", bnk=None), None,
         lambda: golden_write([spec(image=inout, bank=b"")])),
        ("a program that deposits", "program-shape",
         lambda o, s: base(o, s, image="img-dep", bnk=None), None,
         lambda: golden_write([spec(image=depo, bank=b"")])),
        ("an initial state a lane short of whole", "state-shape",
         lambda o, s: base(o, s, ini="init-part"), None,
         lambda: golden_write([spec(init=main.init[:-1])])),
        ("an initial state that is not whole elements", "state-shape",
         lambda o, s: base(o, s, ini="init-ragged"), None, None),
        # no twin: the golden writer has no name for an empty initial
        # state - cert.run_chain hands seq.run an empty block, and it
        # raises seq.ProgramError (found 2026-09-28; for P1c)
        ("an empty initial state", "state-shape",
         lambda o, s: base(o, s, ini="init-empty"), None, None),
        ("0 segments", "malformed", lambda o, s: base(o, s, seg="0"), None,
         lambda: golden_write([spec(segments=0)])),
        ("0 steps", "malformed", lambda o, s: base(o, s, steps="0"), None,
         lambda: golden_write([spec(steps=0)])),
        ("segments '03'", "malformed", lambda o, s: base(o, s, seg="03"),
         None, None),
        ("segments 2^63", "malformed",
         lambda o, s: base(o, s, seg=str(1 << 63)), None, None),
        ("a half-step run with no h-slots", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             x for x in half_run if x not in ("--h-slots", "0,1,2")]),
         None, lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=())])),
        ("h-slot 512", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             "512" if x == "0,1,2" else x for x in half_run]), None,
         lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=(512,))])),
        ("h-slots 2,1", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             "2,1" if x == "0,1,2" else x for x in half_run]), None,
         lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=(2, 1))])),
        ("h-slots 1,1", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             "1,1" if x == "0,1,2" else x for x in half_run]), None,
         lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=(1, 1))])),
        ("a parameter name with a capital", "malformed",
         lambda o, s: base(o, s, extra=["--param", "Spread=1"]), None,
         lambda: golden_write([spec(params=(("Spread", 1),))])),
        ("a parameter value of 2^63", "malformed",
         lambda o, s: base(o, s, extra=["--param", f"n={1 << 63}"]), None,
         lambda: golden_write([spec(params=(("n", 1 << 63),))])),
        ("a parameter named twice", "line-unexpected",
         lambda o, s: base(o, s, extra=["--param", "a=1", "--param", "a=2"]),
         None, lambda: golden_write([spec(params=(("a", 1), ("a", 2)))])),
        ("parameters out of byte order", "line-order",
         lambda o, s: base(o, s, extra=["--param", "a0=1", "--param",
                                        "a-b=2"]),
         None, lambda: golden_write([spec(params=(("a0", 1), ("a-b", 2)))])),
        ("run 0 a half-step run", "malformed",
         lambda o, s: base(o, s, runs=half_run), None,
         lambda: golden_write([half_spec])),
        ("two main runs", "malformed",
         lambda o, s: base(o, s, runs=main_run + main_run), None,
         lambda: golden_write([spec(), spec()])),
        ("no run at all", "malformed", lambda o, s: base(o, s, runs=[]),
         None, lambda: cert.encode(cert.Certificate(
             "open", None, cert.Identity(), (), ()))),
        ("an unknown option", "usage",
         lambda o, s: base(o, s, extra=["--lanes", "3"]), None, None),
        ("no --out", "usage",
         lambda o, s: base(o, s)[2:], None, None),
        ("--salt and --open", "usage",
         lambda o, s: base(o, s, extra=["--open"]), None, None),
        ("neither --salt nor --open", "usage",
         lambda o, s: base(o, s, mode=()), None, None),
        ("a run option before any --run", "usage",
         lambda o, s: ["--image", P["img"]] + base(o, s), None, None),
        ("--run sideways", "usage",
         lambda o, s: base(o, s, runs=["--run", "sideways"]), None, None),
        ("an image file that is not there", "usage",
         lambda o, s: base(o, s, runs=["--run", "main", "--image",
                                       d / "absent.cftp", "--init",
                                       P["init"], "--segments", "1",
                                       "--steps", "1"]), None, None),
        ("--h-slots on the main run", "usage",
         lambda o, s: base(o, s, extra=["--h-slots", "0"]), None, None),
        ("CFT_SEGRUN_PLANT=bogus", "usage", lambda o, s: base(o, s),
         {"CFT_SEGRUN_PLANT": "bogus"}, None),
        # the two small modes' own
        ("--hash with a kind there is not", "usage",
         lambda o, s: ["--hash", "sideways", P["init"], "--open"], None,
         None),
        ("--hash state with neither --salt nor --open", "usage",
         lambda o, s: ["--hash", "state", P["init"]], None, None),
        ("--hash commitment with no salt", "usage",
         lambda o, s: ["--hash", "commitment", "--open"], None, None),
        ("--build-id with anything else", "usage",
         lambda o, s: ["--build-id", "--open"], None, None),
        ("a device that does not open", "device",
         lambda o, s: base(o, s, extra=["--device", d / "absent.xclbin"]),
         None, None),
        ("a device that cannot read its flags (planted)", "device",
         lambda o, s: base(o, s), {"CFT_SEGRUN_PLANT": "flags-unreadable"},
         None),
        # these two are refused at the first segment, after boundary 0 was
        # written: no certificate, and the one boundary file left, said so
        ("a flag word the library left unwritten (planted)", "device",
         lambda o, s: base(o, s), {"CFT_SEGRUN_PLANT": "flags-unwritten"},
         None),
        ("a flag word past the five sticky flags (planted)", "malformed",
         lambda o, s: base(o, s), {"CFT_SEGRUN_PLANT": "flags-wide"},
         lambda: golden_flags(spec(), 16 | 0x20)),
        ("a states directory that already exists", "output",
         lambda o, s: base(o, exists), None, None),
        ("a certificate in a directory that is not there", "output",
         lambda o, s: base(d / "absent" / "c.cert", s), None, None),
        # P3b (verifier-C6's findings): no run overwrites a file it did not
        # make; the certificate can never be a boundary file; and a run the
        # process cannot hold is refused by name before anything runs
        ("an --out that is there already", "output",
         lambda o, s: base(P["existing"], s), None, None),
        ("an --out inside --states, named as boundary 0", "output",
         lambda o, s: base(s / "run-0-boundary-0.bin", s), None, None),
        ("run 1 asking 2^63 - 1 segments, run 0 one", "memory",
         lambda o, s: base(o, s, runs=main_run + [
             str((1 << 63) - 1) if x == "2" else x for x in half_run]),
         None, None),
        ("10^12 segments", "memory",
         lambda o, s: base(o, s, seg=str(10 ** 12)), None, None),
        # verifier-C7's Windows findings: an existing directory at --out
        # was refused as "Permission denied", and the null device accepted
        ("an --out that is a directory there already", "output",
         lambda o, s: base(exists, s), None, None),
        ("the null device as --out", "output",
         lambda o, s: base(os.devnull, s), None, None),
        # --scratch-depth (section 11): the software backend only, a
        # power of two in 1..32,768 in its one spelling, given once, and
        # the parameter it writes is the option's alone. The golden
        # writer has no twin for any: it is handed a depth, not a line.
        ("--scratch-depth beside an xclbin", "usage",
         lambda o, s: base(o, s, extra=["--device", d / "absent.xclbin",
                                        "--scratch-depth", "2048"]),
         None, None),
        ("--scratch-depth beside a cft:// device", "usage",
         lambda o, s: base(o, s, extra=["--device", "cft://127.0.0.1:1",
                                        "--scratch-depth", "2048"]),
         None, None),
        ("--scratch-depth 0", "usage",
         lambda o, s: base(o, s, extra=["--scratch-depth", "0"]), None, None),
        ("--scratch-depth 3", "usage",
         lambda o, s: base(o, s, extra=["--scratch-depth", "3"]), None, None),
        ("--scratch-depth 65536", "usage",
         lambda o, s: base(o, s, extra=["--scratch-depth", "65536"]), None,
         None),
        ("--scratch-depth 02048", "usage",
         lambda o, s: base(o, s, extra=["--scratch-depth", "02048"]), None,
         None),
        ("--scratch-depth 2048x", "usage",
         lambda o, s: base(o, s, extra=["--scratch-depth", "2048x"]), None,
         None),
        ("--scratch-depth -2048", "usage",
         lambda o, s: base(o, s, extra=["--scratch-depth", "-2048"]), None,
         None),
        ("--scratch-depth given twice", "usage",
         lambda o, s: base(o, s, extra=["--scratch-depth", "256",
                                        "--scratch-depth", "256"]), None,
         None),
        ("--param scratch-depth=2048", "usage",
         lambda o, s: base(o, s, extra=["--param", "scratch-depth=2048"]),
         None, None),
        ("--hash with --scratch-depth", "usage",
         lambda o, s: ["--hash", "state", P["init"], "--open",
                       "--scratch-depth", "256"], None, None),
        ("--build-id with --scratch-depth", "usage",
         lambda o, s: ["--build-id", "--scratch-depth", "256"], None, None),
        # the ends of the range are TAKEN: each is refused only by the
        # library's loader, at the depth it was opened at, for a program
        # that cannot load there - flagstep's two slots at a depth of 1,
        # and at 32,768 an image the loader refuses, so that nothing runs
        # there (a scratch run's lane block is 545 MB at 32,768; cft.h)
        ("--scratch-depth 1, a program of 2 slots", "program-image",
         lambda o, s: base(o, s, image="fimg", bnk=None, ini="finit",
                           extra=["--scratch-depth", "1"]), None, None),
        ("--scratch-depth 32768, an image the loader refuses",
         "program-image",
         lambda o, s: base(o, s, image="img-ctl", bnk=None, ini="finit",
                           extra=["--scratch-depth", "32768"]), None, None),
    ]
    # refused by a check the tool makes only after the outputs are made:
    # the library's loader, which needs the device, opened after them
    AFTER_OUTPUTS = {"an image the loader refuses (an unknown control code)",
                     "--scratch-depth 1, a program of 2 slots",
                     "--scratch-depth 32768, an image the loader refuses"}

    def survive(i, label, name, argf, env):
        """The same refusal with a file already at --out, which it must
        leave byte for byte. A defect found only after the outputs are
        made - the device, the library's loader, the flag words, the states
        directory - is met first by the --out that is there, refused
        `output`. A case whose command line has no --out of its own to give
        it (none at all, the two small modes, or an --out the case fixes)
        has nothing to keep, and is not counted."""
        keep, sdir2 = d / f"case{i}.kept", d / f"case{i}.states2"
        args2 = [str(a) for a in argf(keep, sdir2)]
        if "--out" not in args2 or \
                args2[args2.index("--out") + 1] != str(keep):
            return
        keep.write_bytes(kept)
        rc2, _, se2 = run_tool(args2, env)
        m2 = REFUSED.search(se2)
        got2 = m2.group(1) if m2 else None
        late = (name in ("device", "output") or label in AFTER_OUTPUTS
                or (env or {}).get("CFT_SEGRUN_PLANT", "").startswith(
                    "flags-"))
        want2 = "output" if late else name
        code2 = cert.REFUSALS.get(want2, TOOL_OWN.get(want2))
        same = keep.is_file() and keep.read_bytes() == kept
        check(rc2 == code2 and got2 == want2 and same and not sdir2.exists(),
              f"  and a file already at --out comes through it byte for "
              f"byte, refused {want2}: {label}",
              f"exit {rc2}, {got2 or 'no refusal named'}, the file "
              f"{'kept' if same else 'CHANGED or gone'}, states "
              f"{'left' if sdir2.exists() else 'none'}: "
              f"{se2.strip()[-200:]}")

    # what a refusal's words must begin with (a regular expression), where
    # the name alone would not show the check it was made by: an --out
    # inside --states must be refused as the --out it is, not later as a
    # boundary file that collides with it; a run too long to hold, by what
    # is held before any segment runs - run 1 by its own size, before run
    # 0 has run. 10^12 segments are refused by the boundary hashes'
    # allocation where memory is not overcommitted (the Windows desktop),
    # and by the certificate's text, 200 TB, past what a process can
    # address, where it is (WSL cft2204, vm.overcommit_memory 1).
    says = {"an --out that is there already": r"--out .+ is there already",
            "an --out inside --states, named as boundary 0":
                r"--out .+ cannot be created",
            "run 1 asking 2^63 - 1 segments, run 0 one":
                r"run 1: \d+ segments need more memory than this process "
                r"can address",
            "10^12 segments":
                r"(run 0: \d+ x 65 bytes for the boundary hashes|\d+ x 1 "
                r"bytes for the certificate's text) could not be had; .*"
                r"before anything is made",
            "an --out that is a directory there already":
                r"--out .+ is there already",
            "the null device as --out":
                r"--out .+ (is not a file|is there already)",
            "--scratch-depth beside an xclbin":
                r"--scratch-depth 2048 beside --device ",
            "--scratch-depth 3":
                r"--scratch-depth 3 is not a power of two from 1 to 32768",
            "--param scratch-depth=2048":
                r"--param scratch-depth=2048: scratch-depth is the parameter "
                r"--scratch-depth writes",
            "--scratch-depth 1, a program of 2 slots":
                r"run 0: cft_program_load",
            "--scratch-depth 32768, an image the loader refuses":
                r"run 0: cft_program_load"}
    for i, (label, name, argf, env, twin) in enumerate(cases):
        out, sdir = d / f"case{i}.cert", d / f"case{i}.states"
        args = argf(out, sdir)
        rc, so, se = run_tool(args, env)
        m = REFUSED.search(se)
        got = m.group(1) if m else None
        code = cert.REFUSALS.get(name, TOOL_OWN.get(name))
        check(rc == code and got == name,
              f"refused {name} (exit {code}): {label}",
              f"exit {rc}, {got or 'no refusal named'}: {se.strip()[-240:]}")
        if label in says:
            words = se[m.end():].lstrip() if m else ""
            check(re.match(says[label], words) is not None,
                  f"  and its words begin {says[label]!r}: {label}",
                  f"they are {words.strip()[:200]!r}")
        if env and env["CFT_SEGRUN_PLANT"] in ("flags-unwritten",
                                                "flags-wide"):
            files = sorted(os.listdir(sdir)) if sdir.is_dir() else None
            check(not out.exists() and files == ["run-0-boundary-0.bin"]
                  and "the 1 boundary state file written so far is left" in se,
                  f"  and no certificate; boundary 0, written before the "
                  f"refusal, left and said so: {label}",
                  f"certificate {out.exists()}, states {files}")
        else:
            left = [p.name for p in (out, sdir) if p.exists()]
            if name == "output" and label.startswith("a states directory"):
                left = [p.name for p in (out,) if p.exists()]
            check(not left, f"  and nothing left behind: {label}",
                  f"left {left}")
        survive(i, label, name, argf, env)
        if twin is not None:
            try:
                twin()
                bad(f"  the golden writer ACCEPTS {label}, which the tool "
                    f"refuses as {name}")
            except cert.Refusal as e:
                check(e.name == name, f"  the golden writer refuses {label} "
                      f"by the same name", f"it says {e.name}: {e.message}")
            except Exception as e:      # noqa: BLE001 - reported, not raised
                bad(f"  the golden writer has no name for {label}: "
                    f"{type(e).__name__}: {e}")
    check(not (d / "absent").exists(), "a refused --out made no directory")
    # read only if it is there: a tool that removed it fails here by name,
    # and the gate goes on to the remote leg and removes its work directory
    # (verifier-C7's plant F crashed this line at 4eed552)
    check(P["existing"].is_file() and P["existing"].read_bytes() == kept,
          "the file at --out in 'an --out that is there already' is as it "
          "was, byte for byte",
          "it is CHANGED" if P["existing"].is_file() else "it is GONE")


# ---- accuracy entries: the refusals, and the page's orders -----------------

def golden_write_entries(specs, entries, salt=None):
    """The golden writer on RunSpecs and EntrySpecs: run_chain,
    certify_run, derive, make_value, encode."""
    runs, chains = [], []
    for spec in specs:
        st, rs = cert.run_chain(spec.image, spec.bank, spec.init,
                                spec.segments, scratch_depth=DEPTH)
        chains.append((st, rs))
        runs.append(cert.certify_run(spec.kind, spec.image, spec.bank, salt,
                                     st, rs, steps=spec.steps,
                                     parameters=spec.params,
                                     h_slots=spec.h_slots,
                                     scratch_depth=DEPTH,
                                     main_image=specs[0].image))
    return cert.encode(cert.Certificate(
        "keyed" if salt is not None else "open",
        cert.salt_commitment(salt) if salt is not None else None,
        cert.Identity(), tuple(runs),
        golden_entries(entries, runs, specs, chains)))


FP64_MAX = 0x7FEFFFFFFFFFFFFF       # (2^53 - 1) x 2^971: a 1,024-bit value
FP64_INF = 0x7FF0000000000000
WA, WB = (1 << 600) + 1, (1 << 601) - 1     # the page's partial-sum pair


def hold_entries(work, l63, flag):
    """Section 12: every refusal an entry can meet, by its name and code,
    and the golden writer's name for the same defect where it has one; a
    refusal before the runs leaving nothing, one after them the boundary
    files, said so; and the page's orders, each with a control."""
    print("== 12. accuracy entries: every refusal by its name and code, the "
          "golden writer's for the same defect; the page's orders",
          flush=True)
    d = work / "entries"
    d.mkdir(parents=True, exist_ok=True)
    main, half = l63.runs[0], l63.runs[1]
    wide = next((r for r in l63.runs if r.kind == "wider"), None)
    fimg = flag.runs[0].image

    def f(name, data):
        p = d / name
        p.write_bytes(data)
        return p

    P = {"img": f("l63.cftp", main.image), "bank": f("l63.bank", main.bank),
         "half": f("l63.half", half.bank),
         "init": f("l63.init", cert.state_bytes("fp64", main.init)),
         "init2": f("l63-2.init", cert.state_bytes("fp64", main.init[:6])),
         "fimg": f("flag.cftp", fimg)}
    if wide is not None:
        P["img128"] = f("l128.cftp", wide.image)
        P["bank128"] = f("l128.bank", wide.bank)
        P["init128"] = f("l128.init", cert.state_bytes("fp128", wide.init))
    three, one = dec("fp64", "3"), dec("fp64", "1")
    flag_inits = {
        "flag": [three, dec("fp64", "1"), three, dec("fp64", "5")],
        "flag-inf": [three, FP64_INF],
        "flag-max": [three, FP64_MAX],
        "flag-big": [one, dec("fp64", str(1 << 1023))],
        "flag-tiny": [one, dec("fp64", repr(2.0 ** -600))]}
    for k, v in flag_inits.items():
        P[k] = f(f"{k}.init", cert.state_bytes("fp64", v))
    hs = ",".join(str(s) for s in half.h_slots)

    def specs_of(which, segs=1):
        if which == "flag" or which.startswith("flag-"):
            return [RunSpec("main", fimg, b"", flag_inits[which], "fp64", segs,
                            1)]
        s = [dataclasses.replace(main, segments=1, params=()),
             dataclasses.replace(half, segments=2, params=())]
        if which == "l63-other":
            s[1] = dataclasses.replace(s[1], init=main.init[:6])
        elif wide is not None:
            s.append(dataclasses.replace(wide, segments=1, params=()))
        return s

    def runs_of(which, segs=1):
        if which == "flag" or which.startswith("flag-"):
            return ["--run", "main", "--image", P["fimg"], "--init", P[which],
                    "--segments", str(segs), "--steps", "1"]
        a = ["--run", "main", "--image", P["img"], "--bank", P["bank"],
             "--init", P["init"], "--segments", "1", "--steps", "100",
             "--run", "half-step", "--h-slots", hs, "--image", P["img"],
             "--bank", P["half"], "--init",
             P["init2"] if which == "l63-other" else P["init"],
             "--segments", "2", "--steps", "100"]
        if which != "l63-other" and wide is not None:
            a += ["--run", "wider", "--image", P["img128"], "--bank",
                  P["bank128"], "--init", P["init128"], "--segments", "1",
                  "--steps", "100"]
        return a

    E = EntrySpec
    sh = ["--entry", "step-halving", "--uses", "1", "--scope", "max-lanes",
          "--value", "exact"]
    SH = E("step-halving", 1, None, "exact")
    dr = ["--entry", "drift", "--uses", "0", "--scope", "max-lanes",
          "--quantity", "q"]
    third = cert.rational_text(Fraction(-1, 15 << 900))

    def drift(*terms, value="exact", run="0", scope="max-lanes"):
        a = ["--entry", "drift", "--uses", run, "--scope", scope,
             "--quantity", "q"]
        for t in terms:
            a += ["--term", t]
        return a + ["--value", value]

    def D(terms, lane=None, form="exact", fmt=None, uses=0):
        return E("drift", uses, lane, form, fmt, label="q", terms=terms)

    big = cert.rational_text(Fraction(1 << 1100))
    # (label, name or "accepted", runs, the entries' options, their golden
    # twin (EntrySpecs) or None, segments of a flagstep run)
    cases = [
        # the command line's own
        ("an entry option before any --entry", "usage", "l63",
         ["--uses", "1"] + sh, None, 1),
        ("--run after --entry", "usage", "l63",
         sh + ["--run", "main", "--image", P["img"]], None, 1),
        ("a run option after --entry", "usage", "l63",
         sh + ["--image", P["img"]], None, 1),
        ("--uses twice in one entry", "usage", "l63",
         sh + ["--uses", "1"], None, 1),
        ("an entry with no --value", "usage", "l63", sh[:-2], None, 1),
        ("an entry with no --scope", "usage", "l63",
         sh[:4] + sh[6:], None, 1),
        ("an entry with no --uses", "usage", "l63", sh[:2] + sh[4:], None, 1),
        # the words and spellings, the reader's
        ("method 'sideways'", "malformed", "l63",
         ["--entry", "sideways"] + sh[2:], None, 1),
        ("--uses '01'", "malformed", "l63",
         sh[:3] + ["01"] + sh[4:], None, 1),
        # a minus spells a negative run, lane or slot (accuracy-run, -scope,
        # -slot, below) only before a nonzero index in its one spelling
        ("--uses '-0'", "malformed", "l63", sh[:3] + ["-0"] + sh[4:], None,
         1),
        ("--uses '-01'", "malformed", "l63", sh[:3] + ["-01"] + sh[4:], None,
         1),
        ("--scope 'lane:-0'", "malformed", "l63",
         sh[:5] + ["lane:-0"] + sh[6:], None, 1),
        ("--scope 'lane:-01'", "malformed", "l63",
         sh[:5] + ["lane:-01"] + sh[6:], None, 1),
        ("a factor 's-0'", "malformed", "l63", drift("1/1,s-0"), None, 1),
        ("a factor 's-01'", "malformed", "l63", drift("1/1,s-01"), None, 1),
        ("--scope 'lane:01'", "malformed", "l63",
         sh[:5] + ["lane:01"] + sh[6:], None, 1),
        ("--scope 'lanes'", "malformed", "l63",
         sh[:5] + ["lanes"] + sh[6:], None, 1),
        ("--scope 'lane:'", "malformed", "l63",
         sh[:5] + ["lane:"] + sh[6:], None, 1),
        ("a drift with no --quantity", "malformed", "l63",
         ["--entry", "drift", "--uses", "0", "--scope", "max-lanes",
          "--term", "1/1,s0", "--value", "exact"],
         [E("drift", 0, None, "exact", terms=((Fraction(1), (0,)),))], 1),
        ("a drift with no --term", "malformed", "l63",
         dr + ["--value", "exact"], [D(())], 1),
        ("label 'Energy'", "malformed", "l63",
         dr[:-1] + ["Energy", "--term", "1/1,s0", "--value", "exact"],
         [E("drift", 0, None, "exact", label="Energy",
            terms=((Fraction(1), (0,)),))], 1),
        ("a drift of 65 terms", "malformed", "l63",
         drift(*(["1/1,s0"] * 65)), [D(((Fraction(1), (0,)),) * 65)], 1),
        ("an estimate given --quantity", "malformed", "l63",
         sh[:6] + ["--quantity", "q"] + sh[6:],
         [E("step-halving", 1, None, "exact", label="q")], 1),
        ("an estimate given --term", "malformed", "l63",
         sh[:6] + ["--term", "1/1,s0"] + sh[6:],
         [E("step-halving", 1, None, "exact",
            terms=((Fraction(1), (0,)),))], 1),
        ("a coefficient 2/4, not in lowest terms", "malformed", "l63",
         drift("2/4,s0"), None, 1),
        ("a coefficient 0/3, zero not spelt 0/1", "malformed", "l63",
         drift("0/3,s0"), None, 1),
        ("a coefficient 1/0", "malformed", "l63", drift("1/0,s0"), None, 1),
        ("a coefficient 01/3", "malformed", "l63", drift("01/3,s0"), None, 1),
        ("a coefficient +1/3", "malformed", "l63", drift("+1/3,s0"), None, 1),
        ("a coefficient 1/A", "malformed", "l63", drift("1/A,s0"), None, 1),
        ("a factor 'x1'", "malformed", "l63", drift("1/1,x1"), None, 1),
        ("a factor 's01'", "malformed", "l63", drift("1/1,s01"), None, 1),
        ("a term of nine factors", "malformed", "l63",
         drift("1/1" + ",s0" * 9), [D(((Fraction(1), (0,) * 9),))], 1),
        ("factors out of order", "malformed", "l63", drift("1/1,s1,s0"),
         [D(((Fraction(1), (1, 0)),))], 1),
        ("--value 'approx'", "malformed", "l63", sh[:-1] + ["approx"],
         [E("step-halving", 1, None, "approx")], 1),
        ("--value 'rounded:fp512:rne'", "malformed", "l63",
         sh[:-1] + ["rounded:fp512:rne"],
         [E("step-halving", 1, None, "rounded", "fp512", "rne")], 1),
        ("--value 'rounded:fp64:rnx'", "malformed", "l63",
         sh[:-1] + ["rounded:fp64:rnx"],
         [E("step-halving", 1, None, "rounded", "fp64", "rnx")], 1),
        ("--value 'rounded:fp64', no direction", "malformed", "l63",
         sh[:-1] + ["rounded:fp64"],
         [E("step-halving", 1, None, "rounded", "fp64")], 1),
        ("--value 'enclosed', no format", "malformed", "l63",
         sh[:-1] + ["enclosed"], [E("step-halving", 1, None, "enclosed")],
         1),
        ("--value 'exact:fp64'", "malformed", "l63", sh[:-1] + ["exact:fp64"],
         None, 1),
        ("a coefficient past the width rule by its digits (2^1100)", "width",
         "l63", drift(big + ",s0"), [D(((Fraction(1 << 1100), (0,)),))], 1),
        # against the runs, in cert.derive's order
        ("--uses naming no run", "accuracy-run", "l63",
         sh[:3] + [str(len(specs_of("l63")))] + sh[4:],
         [E("step-halving", len(specs_of("l63")), None, "exact")], 1),
        ("--uses past 2^63 - 1", "accuracy-run", "l63",
         sh[:3] + ["1" + "0" * 20] + sh[4:],
         [E("step-halving", 10 ** 20, None, "exact")], 1),
        # a negative run names none: cert.derive's first check, `not 0 <=
        # r < len(runs)` (verifier-W1, 2026-09-30: it was malformed)
        ("--uses -1, a negative run", "accuracy-run", "l63",
         sh[:3] + ["-1"] + sh[4:], [E("step-halving", -1, None, "exact")],
         1),
        ("--uses -5 on a drift", "accuracy-run", "l63",
         drift("1/1,s0", run="-5"), [D(((Fraction(1), (0,)),), uses=-5)], 1),
        ("--uses -10^20, a negative run past -(2^63 - 1)", "accuracy-run",
         "l63", sh[:3] + ["-1" + "0" * 20] + sh[4:],
         [E("step-halving", -10 ** 20, None, "exact")], 1),
        ("step-halving on run 0", "accuracy-run", "l63",
         sh[:3] + ["0"] + sh[4:], [E("step-halving", 0, None, "exact")], 1),
        ("wider on the half-step run", "accuracy-run", "l63",
         ["--entry", "wider"] + sh[2:], [E("wider", 1, None, "exact")], 1),
        ("an estimate whose half-step run has other lanes than run 0",
         "accuracy-run", "l63-other", sh, [SH], 1),
        ("lane 3 of 3", "accuracy-scope", "l63",
         sh[:5] + ["lane:3"] + sh[6:], [E("step-halving", 1, 3, "exact")], 1),
        ("a lane past 2^63 - 1", "accuracy-scope", "l63",
         sh[:5] + ["lane:" + "9" * 21] + sh[6:],
         [E("step-halving", 1, int("9" * 21), "exact")], 1),
        ("slot 3 of 3", "accuracy-slot", "l63", drift("1/1,s3"),
         [D(((Fraction(1), (3,)),))], 1),
        ("slot 70000", "accuracy-slot", "l63", drift("1/1,s70000"),
         [D(((Fraction(1), (70000,)),))], 1),
        # a negative lane or slot names none either: cert.derive bounds
        # both from below too (the lead's decision, 2026-09-30; verifier-
        # W1b: it read one by Python's index from the end - another lane's
        # value, an IndexError, or another lane's accuracy-finite)
        ("lane:-1, a negative lane", "accuracy-scope", "l63",
         sh[:5] + ["lane:-1"] + sh[6:], [E("step-halving", 1, -1, "exact")],
         1),
        ("lane:-4 of 3 lanes", "accuracy-scope", "l63",
         drift("1/1,s0", scope="lane:-4"),
         [D(((Fraction(1), (0,)),), lane=-4)], 1),
        ("lane:-1 where the last lane holds +inf: accuracy-scope, not "
         "accuracy-finite", "accuracy-scope", "flag-inf",
         drift("1/1,s1", scope="lane:-1"),
         [D(((Fraction(1), (1,)),), lane=-1)], 1),
        ("a factor s-1, a negative slot", "accuracy-slot", "l63",
         drift("1/1,s-1"), [D(((Fraction(1), (-1,)),))], 1),
        ("a factor s-10 of a state of 9 elements", "accuracy-slot", "l63",
         drift("1/1,s-10"), [D(((Fraction(1), (-10,)),))], 1),
        ("s-1 before s0, in order", "accuracy-slot", "l63",
         drift("1/1,s-1,s0"), [D(((Fraction(1), (-1, 0)),))], 1),
        ("s-1 on lane 0 where the state's last element is +inf: "
         "accuracy-slot, not accuracy-finite", "accuracy-slot", "flag-inf",
         drift("1/1,s-1", scope="lane:0"),
         [D(((Fraction(1), (-1,)),), lane=0)], 1),
        # after the runs: the values, in the page's order
        ("an element that is not finite (flagstep's x from +inf: NaN)",
         "accuracy-finite", "flag-inf", drift("1/1,s1"),
         [D(((Fraction(1), (1,)),))], 5),
        ("Q(final) before Q(initial): a final +inf beside an initial 1,024-"
         "bit value is accuracy-finite, not width", "accuracy-finite",
         "flag-max", drift("1/1,s1"), [D(((Fraction(1), (1,)),))], 1),
        ("an element past the width rule (x = 2^1023 at the start)",
         "width", "flag-big", drift("1/1,s1"), [D(((Fraction(1), (1,)),))],
         1),
        ("a product past the width rule (x^2 with x = 2^-600)", "width",
         "flag-tiny", drift("1/1,s1,s1"), [D(((Fraction(1), (1, 1)),))], 1),
        ("a partial sum past the width rule: 1/a + 1/b of 1/a, 1/b, -1/b",
         "width", "l63",
         drift(*(cert.rational_text(Fraction(n, d)) for n, d in
                 ((1, WA), (1, WB), (-1, WB)))),
         [D(tuple((Fraction(n, d_), ()) for n, d_ in
                  ((1, WA), (1, WB), (-1, WB))))], 1),
        ("the same terms as 1/b, -1/b, 1/a: within the rule at every step",
         "accepted", "l63",
         drift(*(cert.rational_text(Fraction(n, d)) for n, d in
                 ((1, WB), (-1, WB), (1, WA)))),
         [D(tuple((Fraction(n, d_), ()) for n, d_ in
                  ((1, WB), (-1, WB), (1, WA))))], 1),
        ("1/(3 x 2^900) enclosed in fp256: the lower end past the rule",
         "width", "flag", drift(third + ",s0", value="enclosed:fp256"),
         [D(((Fraction(-1, 15 << 900), (0,)),), form="enclosed",
            fmt="fp256")], 5),
        ("the same value enclosed in fp64: both ends within the rule",
         "accepted", "flag", drift(third + ",s0", value="enclosed:fp64"),
         [D(((Fraction(-1, 15 << 900), (0,)),), form="enclosed",
            fmt="fp64")], 5),
    ]
    if wide is not None:
        cases.append(("step-halving on the wider run", "accuracy-run", "l63",
                      sh[:3] + ["2"] + sh[4:],
                      [E("step-halving", 2, None, "exact")], 1))
    before = ("usage", "malformed", "accuracy-run", "accuracy-scope",
              "accuracy-slot")
    for i, (label, name, which, eargs, twin, segs) in enumerate(cases):
        out, sdir = d / f"e{i}.cert", d / f"e{i}.states"
        args = ["--out", out, "--states", sdir, "--open"] + \
            runs_of(which, segs) + eargs
        rc, so, se = run_tool(args)
        m = REFUSED.search(se)
        got = m.group(1) if m else None
        if name == "accepted":
            if check(rc == 0, f"accepted: {label}", f"rc {rc}: "
                     f"{se.strip()[-240:]}"):
                data = out.read_bytes()
                gold = golden_write_entries(specs_of(which, segs), twin)
                gold = cert.encode(dataclasses.replace(
                    cert.parse(gold), identity=cert.parse(data).identity))
                check(gold == data, f"  and byte for byte the golden "
                      f"writer's: {label}", first_difference(data, gold))
            continue
        code = cert.REFUSALS.get(name, TOOL_OWN.get(name))
        # width by a coefficient's digits is found before anything is made
        early = name in before or label.startswith("a coefficient past")
        check(rc == code and got == name,
              f"refused {name} (exit {code}): {label}",
              f"exit {rc}, {got or 'no refusal named'}: {se.strip()[-240:]}")
        if early:
            left = [p.name for p in (out, sdir) if p.exists()]
            check(not left, f"  and nothing left behind: {label}",
                  f"left {left}")
        else:
            files = sorted(os.listdir(sdir)) if sdir.is_dir() else []
            want = sorted(boundary_file(sdir, r, b).name
                          for r, s in enumerate(specs_of(which, segs))
                          for b in range(s.segments + 1))
            check(not out.exists() and files == want and
                  "written so far are left in" in se,
                  f"  and no certificate; the {len(want)} boundary files, "
                  f"every run having run, left and said so: {label}",
                  f"certificate {out.exists()}, states {files[:4]}")
        if twin is not None:
            try:
                golden_write_entries(specs_of(which, segs), twin)
                bad(f"  the golden writer ACCEPTS {label}, which the tool "
                    f"refuses as {name}")
            except cert.Refusal as e:
                check(e.name == name, f"  the golden writer refuses {label} "
                      f"by the same name", f"it says {e.name}: {e.message}")
            except Exception as e:      # noqa: BLE001 - reported, not raised
                bad(f"  the golden writer has no name for {label}: "
                    f"{type(e).__name__}: {e}")
    # the small modes take no entry
    rc, _, se = run_tool(["--hash", "state", P["init"], "--open"] + sh)
    m = REFUSED.search(se)
    check(rc == 64 and m is not None and m.group(1) == "usage",
          "refused usage (exit 64): --hash with --entry",
          f"exit {rc}: {se.strip()[-200:]}")


# ---- the narrow builds, and the plant build ------------------------------

# cft-segrun compiled narrow, as audit_check.py compiles cft-audit
# (NARROW_BUILDS there): CFT_MAX_FORMAT=2 at the 576-bit bigint that
# ceiling gives by default, with the transcendentals and the conformance
# replay out, as cft_config.h requires; and at CFT_BN_LIMBS=64, the full
# bigint under a lower ceiling. And the plant build: the default build
# with -DCFT_SEGRUN_PLANT_STATE_CHANGED, whose first state read back has
# a bit flipped - compiled here and nowhere else (the lead's condition,
# 2026-09-30: the shipped tool has no plant path).
SEGRUN_BUILDS = {
    "narrow": ("-O2", ["-DCFT_MAX_FORMAT=2", "-DCFT_NO_TRANSCEND",
                       "-DCFT_NO_CONFORMANCE"]),
    "narrow64": ("-O1", ["-DCFT_MAX_FORMAT=2", "-DCFT_BN_LIMBS=64"]),
    "plant": ("-O1", ["-DCFT_SEGRUN_PLANT_STATE_CHANGED"]),
}


def compile_segrun(cc, lib_src, out, opt, defs):
    """cc on the library's sources and tools/segrun.c, from host/, with no
    object of the tree's: -> (ok, stderr). A compiler named by its path
    finds its own programs beside it: its directory goes on PATH for the
    compiler's process alone."""
    env = dict(os.environ)
    first = cc.split()[0]
    if os.path.dirname(first):
        env["PATH"] = os.path.dirname(first) + os.pathsep + env.get("PATH",
                                                                    "")
    cmd = cc.split() + ["-std=c99", opt] + defs + ["-Iinclude"] + \
        lib_src.split() + ["tools/segrun.c", "-o", str(out)]
    r = subprocess.run(cmd, cwd=str(HOST), capture_output=True, text=True,
                       env=env)
    return r.returncode == 0 and out.is_file(), r.stderr


def hold_builds(work, cc, lib_src, l63):
    """Section 13: a narrow build refuses an entry by the build's own name,
    as cft-audit's does, and writes what it can byte for byte as the
    default build; the plant build refuses a changed state `output`."""
    print("== 13. the narrow builds (build-width, build-format) and the "
          "plant build (a state read back changed: output)", flush=True)
    if not cc or not lib_src:
        skip("the narrow builds and the plant build", "no --cc and --lib-src "
             "given (make -C host segruntest gives both)")
        return
    d = work / "builds"
    d.mkdir(parents=True, exist_ok=True)
    exe = {}
    for which, (opt, defs) in SEGRUN_BUILDS.items():
        p = d / (f"cft-segrun-{which}" + (".exe" if os.name == "nt" else ""))
        t0 = time.perf_counter()
        built, err = compile_segrun(cc, lib_src, p, opt, defs)
        if check(built, f"cft-segrun and libcft built {which}: {opt} "
                 f"{' '.join(defs)} ({time.perf_counter() - t0:.0f} s)",
                 err[-400:]):
            exe[which] = p
    spec = [dataclasses.replace(l63.runs[0], segments=1, params=()),
            dataclasses.replace(l63.runs[1], segments=2, params=())]
    paths = write_inputs(d, Program("l63-small", spec))
    prog = Program("l63-small", spec)

    def make(binary, label, entries):
        stem = re.sub(r"[^A-Za-z0-9.-]+", "-", label)
        out, sdir = d / f"{stem}.cert", d / f"{stem}.states"
        args = tool_args(dataclasses.replace(prog, entries=entries), paths,
                         out, sdir, None)
        rc, _, se = run_tool(args, binary=binary)
        return rc, se, out, sdir

    E = EntrySpec
    exact = [E("step-halving", 1, None, "exact")]
    r128 = [E("step-halving", 1, 0, "rounded", "fp128", "rne")]
    ref = {}
    for label, ents in (("none", []), ("exact", exact), ("r128", r128)):
        rc, se, out, _ = make(TOOL, f"default-{label}", ents)
        check(rc == 0, f"the default build writes l63 (1 segment and 2) with "
              f"{label} entries", se.strip()[-240:])
        ref[label] = out.read_bytes() if rc == 0 else None

    def refused_by(binary, label, ents, name, code):
        rc, se, out, sdir = make(binary, label, ents)
        m = REFUSED.search(se)
        check(rc == code and m is not None and m.group(1) == name and
              not out.exists() and not sdir.exists(),
              f"refused {name} (exit {code}), nothing made: {label}",
              f"exit {rc}: {se.strip()[-240:]}")

    def lines(data):
        """A body's lines but build-id: a build compiled here names no
        build (`build-id unknown`, src/build_id.c without the header make
        generates), and the hash line covers that line."""
        return [ln for ln in cert.body_of(data).decode("ascii").split("\n")
                if not ln.startswith("build-id ")]

    def same_as(binary, label, ents, key):
        rc, se, out, _ = make(binary, label, ents)
        mine = out.read_bytes() if rc == 0 else b""
        check(rc == 0 and ref[key] is not None and
              lines(mine) == lines(ref[key]),
              f"{label}: written, byte for byte the default build's but for "
              f"build-id and the hash line",
              f"rc {rc}: {se.strip()[-240:]}" if rc else
              first_difference(ref[key] or b"", mine))
    if "narrow" in exe:
        refused_by(exe["narrow"], "narrow: an exact entry (576-bit bigint)",
                   exact, "build-width", 78)
        same_as(exe["narrow"], "narrow: the same runs, no entry", [], "none")
    if "narrow64" in exe:
        same_as(exe["narrow64"], "narrow64: an exact entry (CFT_BN_LIMBS=64)",
                exact, "exact")
        same_as(exe["narrow64"], "narrow64: a value rounded into fp128",
                r128, "r128")
        refused_by(exe["narrow64"], "narrow64: a value rounded into fp256",
                   [E("step-halving", 1, None, "rounded", "fp256", "rne")],
                   "build-format", 78)
        refused_by(exe["narrow64"], "narrow64: a value enclosed in fp256",
                   [E("step-halving", 1, None, "enclosed", "fp256")],
                   "build-format", 78)
    if "plant" in exe:
        rc, se, out, sdir = make(exe["plant"], "plant: an entry", exact)
        m = REFUSED.search(se)
        files = sorted(os.listdir(sdir)) if sdir.is_dir() else []
        check(rc == 73 and m is not None and m.group(1) == "output" and
              "CFT_SEGRUN_PLANT_STATE_CHANGED" in se and
              "is not the state this run wrote there" in se and
              not out.exists() and len(files) == 5 and
              "written so far are left in" in se,
              "the plant build: the first state read back changed is "
              "refused output (exit 73) by its hash; no certificate, the "
              "boundary files left and said so",
              f"exit {rc}, states {files}: {se.strip()[-300:]}")
        same_as(exe["plant"], "plant: the same runs, no entry", [], "none")
    rc, out_, _ = run_tool(["--help"])
    check(rc == 0 and "CFT_SEGRUN_PLANT_STATE_CHANGED" not in out_,
          "the shipped tool names no plant build")
    blob = TOOL.read_bytes()
    check(b"CFT_SEGRUN_PLANT_STATE_CHANGED" not in blob and
          b"a plant build" not in blob,
          "the shipped binary holds no plant build's words: it was compiled "
          "without -DCFT_SEGRUN_PLANT_STATE_CHANGED")


# ---- --scratch-depth: the software backend at a tile's depth ----------------

def with_depth(params, depth):
    """A run's parameters with `scratch-depth` in its place in byte order,
    as the tool writes it under --scratch-depth."""
    return tuple(sorted(tuple(params) + ((DEPTH_PARAM, depth),),
                        key=lambda p: p[0].encode("ascii")))


def audit_both(what, data, salt, progs, states, segments):
    """The golden audit in full and sampled; each must accept."""
    choose = {r: ("sample", max(1, s // 2)) for r, s in enumerate(segments)}
    for how, kw in (("in full", {}), ("sampled", {"choose": choose})):
        try:
            v = cert.audit(data, salt, progs, states=states, **kw)
            want = segments if how == "in full" else \
                [max(1, s // 2) for s in segments]
            check([len(x["rerun"]) for x in v.runs] == want,
                  f"{what}: the golden audit ACCEPTS it {how}, re-running at "
                  f"the depth the certificate states")
        except cert.Refusal as e:
            bad(f"{what}: the golden audit refuses it {how}: {e.name}: "
                f"{e.message}")


def hold_depth(work, l63):
    """Section 11: --scratch-depth. The tool's certificate at each depth is
    the golden writer's at that depth, with the depth stated in every run
    block, and the golden audit re-runs it there."""
    print("== 11. --scratch-depth: the software backend at a tile's depth, "
          "stated in every run block", flush=True)
    d = work / "depth"
    d.mkdir(parents=True, exist_ok=True)
    img = asm.assemble(DEEPSTEP, "deepstep")
    init = [dec("fp64", t) for t in ("1", "0.5", "2", "0.25")]
    pi, pn = d / "deepstep.cftp", d / "deepstep.init"
    pi.write_bytes(img)
    pn.write_bytes(cert.state_bytes("fp64", init))
    ends = {}
    for depth, mode in ((256, "open"), (2048, "open"), (2048, "keyed")):
        salt = SALT if mode == "keyed" else None
        what = f"deepstep at --scratch-depth {depth}, {mode}"
        out, sdir = d / f"{depth}-{mode}.cert", d / f"{depth}-{mode}.states"
        rc, _, se = run_tool(
            ["--out", out, "--states", sdir] +
            (["--salt", work / "salt.bin"] if salt else ["--open"]) +
            ["--scratch-depth", str(depth), "--run", "main", "--image", pi,
             "--init", pn, "--segments", "3", "--steps", "1",
             "--param", "alpha=1", "--param", "zeta=2"])
        if not check(rc == 0, f"{what}: cft-segrun exits 0",
                     f"rc {rc}: {se.strip()[-300:]}"):
            continue
        data = out.read_bytes()
        got = [ln for ln in data.decode("ascii").split("\n")
               if ln.startswith("parameter")]
        check(got == ["parameters 3", "parameter alpha 1",
                      f"parameter {DEPTH_PARAM} {depth}",
                      "parameter zeta 2"],
              f"{what}: the run block states the depth, in byte order among "
              f"the run's own parameters", f"it says {got}")
        st, rs = cert.run_chain(img, b"", init, 3, scratch_depth=depth)
        ends[(depth, mode)] = st[-1]
        run = cert.certify_run("main", img, b"", salt, st, rs, steps=1,
                               parameters=with_depth((("alpha", 1),
                                                      ("zeta", 2)), depth),
                               scratch_depth=depth)
        idn = cert.parse(data).identity
        gold = cert.encode(cert.Certificate(
            mode, cert.salt_commitment(salt) if salt else None, idn, (run,),
            ()))
        check(gold == data, f"{what}: the golden writer at {depth} slots "
              f"writes the same bytes", first_difference(data, gold))
        check(all(boundary_file(sdir, 0, b).read_bytes()
                  == cert.state_bytes("fp64", st[b]) for b in range(4)),
              f"{what}: every boundary file is the golden chain's state "
              f"at {depth} slots")
        audit_both(what, data, salt, {0: (img, None)},
                   {0: {b: boundary_file(sdir, 0, b).read_bytes()
                        for b in range(4)}}, [3])
    if (256, "open") in ends and (2048, "open") in ends:
        check(ends[(256, "open")] != ends[(2048, "open")],
              "deepstep ends on other states at 256 and at 2,048 slots, so "
              "the leg above holds the depth and not only the line")
    # every run block: lorenz63's main, half-step and wider runs at 2,048
    what = f"{l63.name} at --scratch-depth 2048, open"
    out, sdir = d / "l63-2048.cert", d / "l63-2048.states"
    # the run blocks at a depth, without the program's accuracy entries,
    # which section 12 and the programs' own certificates hold
    args = [str(a) for a in tool_args(dataclasses.replace(l63, entries=[]),
                                      PATHS[l63.name], out, sdir, None)]
    args[args.index("--open") + 1:args.index("--open") + 1] = \
        ["--scratch-depth", "2048"]
    rc, _, se = run_tool(args)
    if check(rc == 0, f"{what}: cft-segrun exits 0",
             f"rc {rc}: {se.strip()[-300:]}"):
        data = out.read_bytes()
        runs, states, wrong = [], {}, []
        for r, spec in enumerate(l63.runs):
            st, rs = cert.run_chain(spec.image, spec.bank, spec.init,
                                    spec.segments, scratch_depth=2048)
            runs.append(cert.certify_run(
                spec.kind, spec.image, spec.bank, None, st, rs,
                steps=spec.steps, parameters=with_depth(spec.params, 2048),
                h_slots=spec.h_slots, scratch_depth=2048,
                main_image=l63.runs[0].image))
            states[r] = {b: boundary_file(sdir, r, b).read_bytes()
                         for b in range(len(st))}
            wrong += [(r, b) for b in range(len(st)) if states[r][b]
                      != cert.state_bytes(spec.fmt, st[b])]
        gold = cert.encode(cert.Certificate("open", None,
                                            cert.parse(data).identity,
                                            tuple(runs), ()))
        check(gold == data, f"{what}: every run block states the depth, and "
              f"the golden writer at 2,048 writes the same bytes",
              first_difference(data, gold))
        check(not wrong, f"{what}: every boundary file is the golden chain's "
              f"state at 2,048 slots", f"(run, boundary) {wrong[:4]}")
        audit_both(what, data, None,
                   {r: (s.image, s.bank or None)
                    for r, s in enumerate(l63.runs)}, states,
                   [s.segments for s in l63.runs])


# ---- memory: what a run costs, and what the trial costs --------------------

# flagstep at fp64: 16 bytes a lane, so 1,048,560 bytes of state - 16
# short of 1 MiB, so that the tool reads each initial state into a buffer
# of exactly 1 MiB
PEAK_LANES = 65535
# What the accuracy entries may cost beyond the runs' own peak: their
# definitions and lines, and the software handle the rounding goes
# through - a small constant, where holding one more state beside the
# runs' would be 1,024 KiB here. Measured on the desktop (2026-09-30,
# four runs of the gate): the three runs' peak commit 10,224 to 10,284
# KiB from run to run, and with the entries 12 KiB less, 12 KiB less, 28
# KiB more and 40 KiB more than the same run's three runs - a span of 52
# KiB. So a quarter of a state: about five times that span, and a
# quarter of what one more state held beside the runs' would cost.
ENTRY_ALLOWANCE = 256 << 10
# The entries' own phase, where it is the process's peak (verifier-W1,
# 2026-09-30: in flagstep's shape an entry that held a third state, or
# entries that kept every pair, cost nothing measurable, since run 0's
# peak was far above them). A run's peak is the library's lane block (its
# registers, and for a program with a scratch its scratch, about 4.6 MiB
# at the default depth whatever the lanes) beside the run's two states
# and streams, or the initial state or a hash's copy beside those. So
# `slotstep`, written here: sixteen slots a lane, each one more a
# segment, at 65,535 lanes, 8,388,480 bytes of state - short of 8 MiB, as
# flagstep's is of 1 MiB. Its run holds two states, its streams (a
# sixteenth of a state) and a third state's worth, past the library's
# block; its entries hold a pair and a hash's copy, half a MiB less; and
# a state more at once, 7,680 KiB more (by arithmetic).
WIDE_SLOTS = 16
WIDE_LANES = 65535
# What the entries may cost there. Not ENTRY_ALLOWANCE: one command line's
# peak commit is steady from run to run, but between command lines - no
# entry, one or two, from a shorter or a longer path - it steps by about
# 470 KiB (measured on the desktop, 2026-09-30: the run alone 26,780 to
# 26,792 KiB from short paths and 26,316 to 26,344 KiB from long ones;
# with one drift 26,812 to 26,852; with two 26,304 to 26,368). The step is
# read_file's first buffers for the initial state, 64 to 512 KiB, in the C
# heap (verifier-W1b, measured: with a first buffer of 1 MiB there is no
# step, and every command line sits at the UPPER level), so the lower
# level is a command line whose later allocations reuse their freed
# memory; it is at most theirs, 960 KiB. So a quarter of this state
# (8,192 KiB), 2,048 KiB: twice that bound. A state more at once costs
# 7,680 KiB past the run's peak, not a whole state, since the run holds
# its streams (512 KiB) and the entries do not; for the same reason the
# entries' own phase may grow by 2,560 KiB before the check fails (W1b:
# a quarter of a state held, +1,548 and +1,524 KiB, passes), and a state
# more fails it by 5,632 KiB.
WIDE_ALLOWANCE = WIDE_SLOTS * WIDE_LANES * 8 // 4
SLOTSTEP = "\n".join(
    [".format   fp64", ".deposits 0", f".scratch  in {WIDE_SLOTS}",
     f".scratch  out {WIDE_SLOTS}", ".const    ONE = 0x3ff0000000000000"] +
    [line for i in range(WIDE_SLOTS) for line in
     (f"ldl    r3, {i}", "add    r3, r3, ONE", f"stl    r3, {i}")] +
    ["halt"]) + "\n"


def read_buffer(n):
    """What cft-segrun's read_file holds an n-byte file in: 64 KiB,
    doubled until the file's bytes and its end both fit."""
    cap = 1 << 16
    while cap <= n:
        cap *= 2
    return cap


class Unmeasured(Exception):
    """This host cannot take the measurement: named NOT TESTED, never a
    failure of the tool and never a crash of the gate."""


class Unwritten(Exception):
    """The run did not write its certificate under all the memory the
    measurement may give it: the tool's failure, by name."""


def tool_env(env):
    e = dict(os.environ)
    e.pop("CFT_SEGRUN_PLANT", None)
    if env:
        e.update(env)
    return e


def peak_commit(args, env=None):
    """Windows: the run's peak commit (PeakPagefileUsage), read from its
    process handle once it has exited. -> (rc, stderr, bytes)"""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.K32GetProcessMemoryInfo.argtypes = [
            wt.HANDLE, ctypes.POINTER(Counters), wt.DWORD]
        k32.K32GetProcessMemoryInfo.restype = wt.BOOL
        p = subprocess.Popen([str(TOOL)] + as_v1(args),
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=tool_env(env))
    except (ImportError, AttributeError, OSError, ValueError) as e:
        raise Unmeasured(f"the peak commit cannot be read here: "
                         f"{type(e).__name__}: {e}")
    try:
        _, se = p.communicate(timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return -1, f"stopped after {TOOL_TIMEOUT} s", 0
    c = Counters()
    c.cb = ctypes.sizeof(c)
    if not k32.K32GetProcessMemoryInfo(int(p._handle), ctypes.byref(c),
                                       c.cb):
        raise Unmeasured(f"GetProcessMemoryInfo failed "
                         f"({ctypes.get_last_error()})")
    return p.returncode, se, c.PeakPagefileUsage


def least_address_space(argf, d, tag, env=None, step=4096):
    """Linux: the least address space - RLIMIT_AS, verifier-C7's `ulimit
    -v` - under which the run writes its certificate, to `step` bytes:
    doubled from 16 MiB until it writes, then bisected. Only the soft
    limit is set, and never past the hard limit this process has, which
    an unprivileged process may not raise (verifier-C7 ran the gate as
    `nobody` under a hard limit of about 8 GB: the 16 GiB this asked for
    at eb2d1ae stopped it with a traceback). -> bytes; Unmeasured when
    the hard limit stops the measurement, Unwritten when 16 GiB does not
    let the run write."""
    try:
        import resource
        hard = resource.getrlimit(resource.RLIMIT_AS)[1]
    except (ImportError, OSError, ValueError) as e:
        raise Unmeasured(f"RLIMIT_AS cannot be read here: {e}")
    cap = 1 << 34
    if hard != resource.RLIM_INFINITY and hard < cap:
        cap = hard
    n = [0]
    last = [""]

    def ok(limit):
        n[0] += 1
        out, sdir = d / f"{tag}{n[0]}.cert", d / f"{tag}{n[0]}.states"

        def lim():
            resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
        try:
            r = subprocess.run([str(TOOL)] + as_v1(argf(out, sdir)),
                               capture_output=True, text=True,
                               preexec_fn=lim, env=tool_env(env),
                               timeout=TOOL_TIMEOUT)
            good, last[0] = r.returncode == 0, r.stderr
        except subprocess.TimeoutExpired:
            good, last[0] = False, f"stopped after {TOOL_TIMEOUT} s"
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            raise Unmeasured(f"the tool cannot be started under an address-"
                             f"space limit here: {type(e).__name__}: {e}")
        finally:
            if out.exists():
                out.unlink()
            shutil.rmtree(sdir, ignore_errors=True)
        return good

    lo, hi = 0, min(1 << 24, cap)
    while not ok(hi):
        if hi >= cap and cap < 1 << 34:
            raise Unmeasured(f"the run does not write its certificate under "
                             f"{hi} bytes, this process's hard address-"
                             f"space limit: {last[0].strip()[-200:]}")
        if hi >= cap:
            raise Unwritten(f"not even under {hi} bytes: "
                            f"{last[0].strip()[-240:]}")
        lo, hi = hi, min(hi * 2, cap)
    while hi - lo > step:
        mid = (lo + hi) // 2 // step * step
        if mid <= lo:
            break
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi


def kib(n):
    return f"{n / 1024:,.0f} KiB"


def hold_peak(work, flag):
    """verifier-C7's regressions, held.
    4eed552 held every run's two states and streams at once, where
    99f1b43 held one run's: a main run and two half-step runs must cost
    what the main run alone does, and no more than the two further runs'
    inputs beside it and one state to spare. Measured as the platform
    measures a process: its peak commit on Windows, and on Linux the least
    address space it writes its certificate in.
    The accuracy entries (the plan's step 5): beside the three runs, no
    state held beside the runs'; and beside slotstep's one run, where their
    own phase is the peak, a pair at a time, for its two drifts
    (verifier-W1; it holds no estimate: verifier-W1b).
    eb2d1ae's trial took its pieces under 64 KiB from the C library's heap
    and left the heap bigger, so the runs needed up to 40 KiB more than
    99f1b43's: the trial must cost the runs nothing, to the page. Held on
    Linux, where the least address space is the same run after run; on
    Windows, identical runs' peak commit differs by several pages, so
    there it is NOT TESTED."""
    print("== 10. memory: a run beside the main run costs its own inputs, "
          "and the trial costs the runs nothing", flush=True)
    d = work / "peak"
    d.mkdir(parents=True, exist_ok=True)
    img = flag.runs[0].image
    lane = list(flag.runs[0].init[:2])
    pi = d / "flag.cftp"
    pi.write_bytes(img)
    inits = {}
    for lanes in (PEAK_LANES, 1, 16):
        inits[lanes] = d / f"flag-{lanes}.init"
        inits[lanes].write_bytes(cert.state_bytes("fp64", lane * lanes))
    salt = d / "salt.bin"
    salt.write_bytes(bytes(range(32)))

    def argf(lanes, segments, n_half, keyed=False, entries=()):
        pn = inits[lanes]

        def f(out, sdir):
            a = ["--out", out, "--states", sdir,
                 *(("--salt", salt) if keyed else ("--open",)),
                 "--run", "main", "--image", pi, "--init", pn,
                 "--segments", str(segments), "--steps", "1"]
            for _ in range(n_half):
                a += ["--run", "half-step", "--h-slots", "0", "--image", pi,
                      "--init", pn, "--segments", str(2 * segments),
                      "--steps", "1"]
            return a + entry_options(entries)
        return f

    # two entries that read four states once the runs have run: an
    # estimate of run 0 against run 1, and a drift of run 2, rounded (so
    # the software handle for the rounding is opened too)
    two = (EntrySpec("step-halving", 1, None, "exact"),
           EntrySpec("drift", 2, None, "rounded", "fp64", "rne", label="c",
                     terms=FLAG_C))
    # slotstep's run alone, and with two drifts of it, exact and rounded,
    # reading four of its states back (WIDE_SLOTS). Drifts only: an
    # estimate needs a second run, and before the runs the trial holds
    # every run's initial state beside the larger run's two states and
    # streams - by arithmetic, that run's streams above an estimate's
    # phase with a state more, so no shape of the tool as shipped shows
    # one (measured, 2026-09-30: slotstep's main run beside its fp128
    # wider run peaks at 59,244 KiB, and with a wider estimate 59,248;
    # with the trial skipped, its instrument, 51,472 and 51,496). The
    # read-back is one code for every method (derive_entry), but a fault
    # in an estimate's alone passes both shapes (verifier-W1b's plant).
    pw = d / "slotstep.cftp"
    pw.write_bytes(asm.assemble(SLOTSTEP, "slotstep"))
    wide_init = d / f"slotstep-{WIDE_LANES}.init"
    wide_init.write_bytes(cert.state_bytes("fp64", [dec("fp64", "1")]) *
                          (WIDE_SLOTS * WIDE_LANES))
    wide_state = WIDE_SLOTS * WIDE_LANES * 8
    drifts = (EntrySpec("drift", 0, None, "exact", label="x",
                        terms=FLAG_C),
              EntrySpec("drift", 0, None, "rounded", "fp64", "rne",
                        label="x", terms=FLAG_C))

    def wide(entries=()):
        def f(out, sdir):
            return ["--out", out, "--states", sdir, "--open", "--run",
                    "main", "--image", pw, "--init", wide_init, "--segments",
                    "1", "--steps", "1"] + entry_options(entries)
        return f

    linux = sys.platform.startswith("linux")
    what_run = "what a run beside the main run costs"
    try:
        # 1. a run's own working set: one run against three; the accuracy
        # entries against the runs (the plan's step 5): none held beside
        # the three runs', and their own phase, where it is slotstep's peak
        shapes = (
            (f"the main run alone, {PEAK_LANES} lanes",
             argf(PEAK_LANES, 1, 0)),
            (f"the main run and two half-step runs, {PEAK_LANES} lanes",
             argf(PEAK_LANES, 1, 2)),
            (f"the same three runs with two entries reading four states, "
             f"{PEAK_LANES} lanes", argf(PEAK_LANES, 1, 2, entries=two)),
            (f"slotstep's main run alone, {WIDE_LANES} lanes of "
             f"{WIDE_SLOTS} slots", wide()),
            (f"the same run with two drifts of it reading four states, "
             f"{WIDE_LANES} lanes", wide(drifts)))
        vals = []
        if os.name == "nt":
            how = "peak commit"
            for i, (label, f) in enumerate(shapes):
                out, sdir = d / f"w{i}.cert", d / f"w{i}.states"
                rc, se, pk = peak_commit(f(out, sdir))
                if not check(rc == 0, f"{label}: written, and its peak "
                             f"commit read", f"rc {rc}: {se.strip()[-240:]}"):
                    return
                vals.append(pk)
        elif linux:
            how = "least address space (ulimit -v)"
            for i, (label, f) in enumerate(shapes):
                try:
                    vals.append(least_address_space(f, d, f"l{i}-",
                                                    step=1 << 16))
                except Unwritten as e:
                    bad(f"{label}: written, under a limit found by "
                        f"bisection - {e}")
                    return
                ok(f"{label}: written, under a limit found by bisection")
        else:
            raise Unmeasured(f"no way to measure a process's peak here "
                             f"({sys.platform})")
        one, three, entries, wide_one, wide_two = vals
        inputs = 2 * (read_buffer(PEAK_LANES * 16) + read_buffer(len(img)))
        state = PEAK_LANES * 16
        check(three - one <= inputs + state,
              f"{how}: the main run alone {kib(one)}, with two half-step "
              f"runs {kib(three)} - {kib(three - one)} more, within the two "
              f"runs' inputs ({kib(inputs)}) and one state ({kib(state)})",
              f"{kib(three - one)} more, past {kib(inputs + state)}: a run "
              f"holds a working set of its own beside the others' (4eed552 "
              f"held every run's states at once; verifier-C7)")
        # the entries cost no more than ENTRY_ALLOWANCE (their own
        # structures and lines, the rounding's software handle) and, on
        # Linux, one bisection step. Beside the three runs, that holds no
        # state beside the runs': the entries' own phase is more than two
        # states under run 0's peak there, and is not seen (verifier-W1)
        allow = ENTRY_ALLOWANCE + (0 if os.name == "nt" else 1 << 16)
        delta = entries - three
        said = (f"{kib(delta)} more" if delta >= 0 else
                f"{kib(-delta)} less")
        check(delta <= allow,
              f"{how}: the three runs {kib(three)}, with the two entries "
              f"{kib(entries)} - {said}, within {kib(allow)} more: the "
              f"entries hold no state beside the runs' (one would be "
              f"{kib(state)} more)",
              f"{kib(entries - three)} more, past {kib(allow)}: the entries "
              f"hold memory beside the runs'")
        # beside slotstep's one run, where the entries' phase is the peak:
        # an entry holds its two states and a hash's copy, and lets them
        # go before the next reads its own
        wallow = WIDE_ALLOWANCE + (0 if os.name == "nt" else 1 << 16)
        delta = wide_two - wide_one
        said = (f"{kib(delta)} more" if delta >= 0 else
                f"{kib(-delta)} less")
        check(delta <= wallow,
              f"{how}: slotstep's run alone {kib(wide_one)}, with its two "
              f"drifts {kib(wide_two)} - {said}, within {kib(wallow)} more: "
              f"the drifts read their states back a pair at a time (a state "
              f"more at once would be "
              f"{kib(wide_state - wide_state // WIDE_SLOTS)} past the run's "
              f"own peak, by arithmetic)",
              f"{kib(delta)} more, past {kib(wallow)}: an entry holds more "
              f"than its two states and a hash's copy at once, or the "
              f"entries more than one pair at once, or memory beside the run")
    except Unmeasured as e:
        skip(what_run, f"NOT TESTED here - {e}")

    # 2. the trial's cost to the runs, to the page: the least address
    # space with the trial and with its allocations skipped (the
    # instrument), in two small shapes verifier-C7 found it in
    trial_shapes = (
        ("1 lane, open, a main run of 100 segments and a half-step run "
         "of 200", argf(1, 100, 1)),
        ("16 lanes, keyed, a main run of 30 segments and two half-step "
         "runs of 60", argf(16, 30, 2, keyed=True)),
        ("16 lanes, open, a main run of 30 segments, two half-step runs "
         "of 60 and two entries", argf(16, 30, 2, entries=two)))
    what_trial = "what the trial costs the runs, to the page"
    if not linux:
        skip(what_trial, "NOT TESTED here - " + (
             "identical runs' peak commit differs by several pages on "
             "Windows, so a page is below what it can see; held on Linux"
             if os.name == "nt" else
             f"no way to measure a process's address space here "
             f"({sys.platform})"))
        return
    try:
        for i, (label, f) in enumerate(trial_shapes):
            try:
                with_trial = least_address_space(f, d, f"t{i}-")
                without = least_address_space(
                    f, d, f"s{i}-", env={"CFT_SEGRUN_PLANT": "trial-skipped"})
            except Unwritten as e:
                bad(f"what the trial costs the runs ({label}): the run "
                    f"written under a limit found by bisection - {e}")
                continue
            check(with_trial <= without,
                  f"least address space with the trial {kib(with_trial)}, "
                  f"with its allocations skipped {kib(without)}: the trial "
                  f"costs the runs nothing ({label})",
                  f"the trial costs the runs {kib(with_trial - without)} - "
                  f"it has left the heap bigger (eb2d1ae's pieces under "
                  f"64 KiB from calloc; verifier-C7)")
    except Unmeasured as e:
        skip(what_trial, f"NOT TESTED here - {e}")


# ---- the remote leg ---------------------------------------------------------

def hold_mark_lines(what, data):
    """The mark in the certificate itself (R24, ABI 0.17): markstep's five
    segment lines carry the flags and STATUS words the golden chain gives,
    STATUS 64 - CFT_STATUS_MARKED - on the first three. A writer, a backend
    or a protocol that dropped STATUS[6] on the way would write 0 there."""
    got = [(int(m.group(1)), int(m.group(2)))
           for m in re.finditer(rb"^segment \d+ start \S+ end \S+ flags "
                                rb"(\d+) status (\d+)$", data, re.M)]
    check(got == list(zip(MARKSTEP_FLAGS, MARKSTEP_STATUS)),
          f"{what}: the segment lines carry flags {MARKSTEP_FLAGS} and STATUS "
          f"{MARKSTEP_STATUS} - the mark, STATUS[6], reached the certificate",
          f"they carry {got}")


def hold_remote(work, legs):
    """`legs`: (program, its golden chains, its keyed software certificate)
    for each program certified through the server - lorenz63, whose every
    segment is flags 16 and STATUS 0, flagstep, whose are not, so that
    a flag word or STATUS lost on the way back from a server is seen, and
    markstep, whose STATUS[6] is the mark (R24): a server or client that
    masked the word to bits 4 and 5 would lose it."""
    print("== 9. through a loopback cft-serve: the page's remote rule, and "
          "the same chains", flush=True)
    rd = work / "remote"
    rd.mkdir(parents=True, exist_ok=True)
    port_file, pid_file = rd / "port", rd / "pid"
    log = open(rd / "serve.log", "w")
    proc = subprocess.Popen([str(SERVE), "--port", "0", "--port-file",
                             str(port_file), "--pid-file", str(pid_file),
                             "--max-conns", str(len(legs))],
                            stdout=log, stderr=subprocess.STDOUT)
    print(f"  cft-serve pid {proc.pid}", flush=True)
    try:
        port = None
        deadline = time.time() + 30
        while time.time() < deadline and proc.poll() is None:
            if port_file.is_file() and port_file.read_text().strip():
                port = int(port_file.read_text().split()[0])
                break
            time.sleep(0.1)
        if not check(port is not None, "cft-serve reports its port",
                     f"exit {proc.poll()}"):
            return
        for prog, chains, sw_data in legs:
            res = certify_and_hold(prog, chains, "keyed", work,
                                   device=f"cft://127.0.0.1:{port}",
                                   tag=" remote")
            if res is None:
                continue
            check(runs_part(res[0]) == runs_part(sw_data),
                  f"{prog.name} keyed remote: every run block, byte for "
                  f"byte, the software backend's")
    finally:
        if proc.poll() is None:
            proc.terminate()              # by PID: this child and no other
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
        log.close()
        print(f"  cft-serve pid {proc.pid} stopped (exit {proc.returncode})",
              flush=True)


# ---- main -------------------------------------------------------------------

PATHS = {}
EXPECT_XRT = None
AUDIT = None        # cft-audit, the C auditor, held beside the golden one
DEPTH_V2 = None     # section 14's golden depth: DEPTH, or a run's stated one
# The scratch depth the golden writer runs at (revision 7): the DEVICE's,
# read out of the CAPS2 its expected identity names (cert.scratch_depth_of,
# which is also what the audit re-runs at), or the software backend's 256.
# Every program below names only static slots under 256 - the ODE rows'
# highest is lorenz96's 200 - so their chains are the same bytes at any
# depth that holds them; the golden writer takes the device's anyway, so a
# program that indexed past 256 could not pass here by computing another
# machine's answer.
DEPTH = seq.SCRATCH_D


def rounding_seen(programs, chains):
    """For each rounding direction a rounded entry names: whether some such
    entry's value rounds to other bits under rup. Where it does, a writer
    that swapped that direction for rup writes other bytes than the golden
    writer, and the byte-for-byte comparison sees it."""
    seen = {}
    for prog in programs:
        rounded = [e for e in prog.entries if e.form == "rounded"]
        if not rounded:
            continue
        runs = [cert.certify_run(s.kind, s.image, s.bank, None, st, rs,
                                 steps=s.steps, parameters=s.params,
                                 h_slots=s.h_slots, scratch_depth=DEPTH,
                                 main_image=prog.runs[0].image)
                for s, (st, rs) in zip(prog.runs, chains[prog.name])]
        for e, g in zip(prog.entries, golden_entries(prog.entries, runs,
                                                     prog.runs,
                                                     chains[prog.name])):
            if e.form != "rounded":
                continue
            ends = {}
            for r, (st, _) in enumerate(chains[prog.name]):
                ends[(r, 0)], ends[(r, len(st) - 1)] = st[0], st[-1]
            shapes = [(FORMATS[s.fmt],
                       seq.Program.from_bytes(s.image).n_scratch_in)
                      for s in prog.runs]
            q = cert.derive(g, runs, shapes, ends)
            seen[e.rnd] = seen.get(e.rnd, False) or \
                cert.round_rational(e.fmt, q, e.rnd) != \
                cert.round_rational(e.fmt, q, "rup")
    return seen


def main():
    global TOOL, SERVE, SALT, EXPECT_ID, EXPECT_XRT, DEPTH, AUDIT, DEPTH_V2
    # a check's words can carry what no console code page spells (the
    # tool's own text, section 14's leg i): escaped, never a crash
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tool", required=True, help="the cft-segrun binary")
    ap.add_argument("--serve", help="cft-serve, for the remote leg")
    ap.add_argument("--audit", help="cft-audit, the C auditor: it must "
                    "accept each certificate as the golden audit does")
    ap.add_argument("--cc", help="the C compiler, for the narrow builds and "
                    "the plant build (section 13)")
    ap.add_argument("--lib-src", help="libcft's sources, relative to host/ "
                    "(make print-src), for section 13")
    ap.add_argument("--keep", help="write everything here and keep it")
    ap.add_argument("--salt-hex", help="the keyed salt (default: drawn "
                    "from the operating system and printed)")
    ap.add_argument("--device", default="sw",
                    help="make the certificates on this xclbin (the card "
                    "leg, hw/card-segrun.sh); each is also made on the "
                    "software backend and its run blocks compared")
    ap.add_argument("--expect-xclbin", help="with --device: the image's "
                    "SHA-256, measured apart from the library (sha256sum)")
    ap.add_argument("--expect-version", help="with --device: VERSION, 8 hex")
    ap.add_argument("--expect-caps", help="with --device: CAPS [CAPS2], "
                    "8 hex each")
    ap.add_argument("--expect-tiles", type=int, help="with --device: tiles")
    ap.add_argument("--no-wider", action="store_true",
                    help="no wider runs: for a device without fp128")
    ap.add_argument("--programs", help="certify only these, by name, "
                    "comma-separated (the card leg's negative control)")
    ap.add_argument("--v2-only", action="store_true",
                    help="section 14 alone, certificate version 2 (for "
                    "iterating; the gate runs every section)")
    args = ap.parse_args()
    TOOL = Path(args.tool).resolve()
    SERVE = Path(args.serve).resolve() if args.serve else None
    AUDIT = Path(args.audit).resolve() if args.audit else None
    if not TOOL.is_file():
        sys.exit(f"segrun_check: {TOOL} is not built (make -C host "
                 f"cft-segrun)")
    if AUDIT is not None and not AUDIT.is_file():
        sys.exit(f"segrun_check: {AUDIT} is not built (make -C host "
                 f"cft-audit)")
    SALT = bytes.fromhex(args.salt_hex) if args.salt_hex else os.urandom(32)
    EXPECT_ID = os.environ.get("CFT_EXPECT_BUILD_ID") or None
    card = args.device != "sw"
    if card:
        need = (args.expect_xclbin, args.expect_version, args.expect_caps,
                args.expect_tiles)
        if any(x is None for x in need):
            sys.exit("segrun_check: --device takes --expect-xclbin, "
                     "--expect-version, --expect-caps and --expect-tiles, "
                     "each measured apart from this tool")
        EXPECT_XRT = ("xrt", args.expect_xclbin, args.expect_version,
                      tuple(args.expect_caps.split()), args.expect_tiles)
        DEPTH = cert.scratch_depth_of(
            cert.Identity(device_caps=tuple(args.expect_caps.split())))
        print(f"  the golden writer at {DEPTH} scratch slots a lane, the "
              f"device's (CAPS2)", flush=True)
    work = Path(args.keep).resolve() if args.keep else \
        Path(tempfile.mkdtemp(prefix="segrun-check-"))
    work.mkdir(parents=True, exist_ok=True)
    (work / "salt.bin").write_bytes(SALT)
    t_all = time.perf_counter()
    print(f"segrun_check: {TOOL}", flush=True)
    print(f"  keyed salt {SALT.hex()} (reproduce with --salt-hex)", flush=True)
    print(f"  work in {work}", flush=True)
    if EXPECT_ID is None:
        skip("the build-id line held to the tree's id",
             "CFT_EXPECT_BUILD_ID is not set (make -C host segruntest sets "
             "it)")
    if AUDIT is None:
        skip("cft-audit beside the golden audit", "no --audit given (make "
             "-C host segruntest gives it)")
    DEPTH_V2 = DEPTH
    if args.v2_only:
        import segrun_check_v2
        segrun_check_v2.hold_v2(sys.modules[__name__], work, card,
                                args.device, SERVE)
        return finish(work, args, t_all)

    print("== the binary, ignored by git", flush=True)
    hold_ignored()
    print("== the programs", flush=True)
    man = manifest()
    programs = [ode_program(b, f, man) for b in SIZES for f in
                ("fp64", "fp256")]
    if args.no_wider:
        print("  NOTE  --no-wider: no fp128 run beside the fp64 programs",
              flush=True)
        for p in programs:
            p.runs = [r for r in p.runs if r.kind != "wider"]
    flag = flagstep_program()
    programs.append(flag)
    mark = markstep_program()
    programs.append(mark)
    programs.append(half_init_program(
        next(p for p in programs if p.name == "lorenz63-rk4-fp64")))
    attach_entries(programs)
    chains = {}
    for prog in programs:
        PATHS[prog.name] = write_inputs(work, prog)
        t0 = time.perf_counter()
        chains[prog.name] = [cert.run_chain(s.image, s.bank, s.init,
                                            s.segments, scratch_depth=DEPTH)
                             for s in prog.runs]
        shape = ", ".join(
            f"{s.kind} {s.fmt} "
            f"{len(st[0]) // seq.Program.from_bytes(s.image).n_scratch_in}"
            f" lanes x {s.segments}"
            for s, (st, _) in zip(prog.runs, chains[prog.name]))
        print(f"  {prog.name}: {shape}; the golden chains in "
              f"{time.perf_counter() - t0:.1f} s", flush=True)
    fl = [x[0] for x in chains[flag.name][0][1]]
    stt = [x[1] for x in chains[flag.name][0][1]]
    check(fl == FLAGSTEP_FLAGS and stt == FLAGSTEP_STATUS,
          f"flagstep's segments raise flags {FLAGSTEP_FLAGS} and STATUS "
          f"{FLAGSTEP_STATUS} in the golden model",
          f"flags {fl}, STATUS {stt}")
    fl = [x[0] for x in chains[mark.name][0][1]]
    stt = [x[1] for x in chains[mark.name][0][1]]
    check(fl == MARKSTEP_FLAGS and stt == MARKSTEP_STATUS,
          f"markstep's segments raise flags {MARKSTEP_FLAGS} and STATUS "
          f"{MARKSTEP_STATUS} in the golden model - a raise's word and its "
          f"mark, STATUS[6]",
          f"flags {fl}, STATUS {stt}")
    # the entries' coverage, as the plan's step 5 asks for it
    ents = [(p, e) for p in programs for e in p.entries]
    if args.no_wider:
        print("  NOTE  --no-wider: the wider estimates go with the wider "
              "runs, so the entries' coverage is the software gate's to "
              "hold", flush=True)
    else:
        check({e.method for _, e in ents} ==
              {"drift", "step-halving", "wider"}
              and {e.lane is None for _, e in ents} == {True, False}
              and {e.form for _, e in ents} ==
              {"exact", "rounded", "enclosed"}
              and {e.rnd for _, e in ents if e.form == "rounded"} ==
              {"rne", "rtz", "rdn", "rup", "rmm"},
              "the entries have every method, both scopes, every form and "
              "every rounding direction")
        odes = [p for p in programs if p.name.split("-")[0] in
                ("lorenz63", "lorenz96", "henonheiles")
                and not p.audit_refuses]
        check(all(any(e.method == "step-halving" for e in p.entries)
                  for p in odes) and
              all(any(e.method == "wider" for e in p.entries) for p in odes
                  if p.name.endswith("fp64")) and
              any(e.method == "drift" and e.form == "exact" and
                  p.name.startswith("henonheiles") for p, e in ents),
              "a step-halving estimate on each ODE program, a wider one on "
              "each fp64 one, and Henon-Heiles' energy drift, exact")
        seen = rounding_seen(programs, chains)
        check(all(seen.get(r) for r in seen if r != "rup") and
              any(seen.get(r) for r in seen if r != "rup"),
              f"each rounding direction but rup rounds some entry's value to "
              f"other bits than rup does, so a writer that swapped it for "
              f"rup is seen ({sorted(r for r in seen if seen[r])})",
              f"{seen}")

    sw_keyed = {}
    only = set(args.programs.split(",")) if args.programs else None
    if only and not only <= {p.name for p in programs}:
        sys.exit(f"segrun_check: --programs names "
                 f"{sorted(only - {p.name for p in programs})}, which are not "
                 f"programs here: {[p.name for p in programs]}")
    for prog in programs:
        if only and prog.name not in only:
            continue
        made = {}
        for mode in ("keyed", "open"):
            where = f" on {args.device}" if card else ""
            print(f"== {prog.name}, {mode}{where}", flush=True)
            res = certify_and_hold(prog, chains[prog.name], mode, work,
                                   device=args.device,
                                   tag=" card" if card else "",
                                   may_refuse_load=card and (prog is flag or
                                                             prog is mark))
            if res:
                made[mode] = res[0]
                if prog is mark:
                    hold_mark_lines(f"{prog.name} {mode}", res[0])
        if not card:
            if "keyed" in made:
                sw_keyed[prog.name] = made["keyed"]
            continue
        if "keyed" not in made:
            continue
        # the card's chain against the software backend's: the same
        # program, inputs and salt, made again on sw
        salt_path = work / "salt.bin"
        stem = work / "out" / f"{prog.name}-keyed-sw"
        rc, _, se = run_tool(tool_args(prog, PATHS[prog.name],
                                       Path(str(stem) + ".cert"),
                                       Path(str(stem) + ".states"),
                                       salt_path, "sw"))
        if check(rc == 0, f"{prog.name} keyed: made on the software backend "
                 f"too", f"rc {rc}: {se.strip()[-300:]}"):
            sw = Path(str(stem) + ".cert").read_bytes()
            sw_keyed[prog.name] = sw
            check(runs_part(made["keyed"]) == runs_part(sw),
                  f"{prog.name} keyed on the card: every run block, byte for "
                  f"byte, the software backend's")

    hold_hashes(work)
    l63 = next(p for p in programs if p.name == "lorenz63-rk4-fp64")
    hold_refusals(work, l63, flag)
    hold_entries(work, l63, flag)
    if card:
        print("  NOTE  section 11, --scratch-depth, is the software "
              "backend's: beside a device the tool refuses it (step 8)",
              flush=True)
        print("  NOTE  section 13, the narrow builds and the plant build, is "
              "the software backend's, compiled here", flush=True)
    else:
        hold_depth(work, l63)
        hold_builds(work, args.cc, args.lib_src, l63)
    if SERVE is None:
        if card:
            print("  NOTE  the remote leg is not the card leg's: "
                  "hw/card-identity.sh holds a remote handle with a card "
                  "behind its server", flush=True)
        else:
            skip("the remote leg", "no --serve given")
    elif (l63.name in sw_keyed and flag.name in sw_keyed
          and mark.name in sw_keyed):
        hold_remote(work, [(p, chains[p.name], sw_keyed[p.name])
                           for p in (l63, flag, mark)])
    else:
        bad("the remote leg: a software certificate it compares with was "
            "not made")
    hold_peak(work, flag)
    # section 14: certificate format version 2 (host/tests/segrun_check_v2.py)
    import segrun_check_v2
    segrun_check_v2.hold_v2(sys.modules[__name__], work, card, args.device,
                            SERVE)
    return finish(work, args, t_all)


def finish(work, args, t_all):
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print(f"segrun_check: {CHECKS} checks, {len(FAILED)} failed, "
          f"{len(SKIPS)} skipped, {time.perf_counter() - t_all:.0f} s",
          flush=True)
    if FAILED:
        for w in FAILED:
            print(f"  FAILED: {w}")
        return 1
    print("SEGRUN CHECK OK" if not SKIPS else
          "SEGRUN CHECK OK, with the skips above named")
    return 0


if __name__ == "__main__":
    sys.exit(main())
