# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""host/fuzz/fuzz_ckpt.py's verdicts on a cft-orbits resume that met an
infinity (KL-481).

cft-orbits refuses a checkpoint whose state or invariants hold an
infinity where it reads it: a sentence, exit 2. A run stops at the flag
that makes an infinity, so it never writes one; before this the resume
ran its first step into the flag certificate and stopped at exit 3, or,
for an invariant, finished at exit 0. The fuzz lane called the first a
refusal and the second an acceptance, so a reader that went back to
either could not be seen. These hold the classifier to the contract
without a build: it is a pure function of an exit code, a stderr and the
checkpoint's text. (The tool's own refusals are held by
host/tests/orbits_check.py, [8].)
"""

import importlib.util
import types
from pathlib import Path

FUZZ = Path(__file__).resolve().parents[2] / "host" / "fuzz" / "fuzz_ckpt.py"

spec = importlib.util.spec_from_file_location("fuzz_ckpt_under_test", FUZZ)
fz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fz)

FLAGSTOP = ("cft-orbits: a sequencer-program segment raised 0x11 - this "
            "workload can only ever raise inexact, so invalid, divide-by-"
            "zero, overflow or underflow means the integration or the tool "
            "is wrong (docs/ORBITS.md, \"Flags\")\n")
SENTENCE = ("cft-orbits: the checkpoint x.ckpt, line 18: member 1's state "
            "value `inf` is an infinity\n")

FINITE = "h 1.25e-1\nstate 1 1.5 -2.5 0 0.5\ninv 0 -3.25e-1 0\nend\n"
WITH_INF = "h 1.25e-1\nstate 1 inf -2.5 0 0.5\ninv 0 -3.25e-1 0\nend\n"
INV_INF = "h 1.25e-1\nstate 1 1.5 -2.5 0 0.5\ninv 0 -INF 0\nend\n"


def proc(code, err=""):
    return types.SimpleNamespace(returncode=code, stderr=err)


def test_holds_infinity_reads_state_and_inv_lines_only():
    assert fz.holds_infinity(WITH_INF)
    assert fz.holds_infinity(INV_INF)            # either sign, either case
    assert fz.holds_infinity("state 0 +Infinity 1\n")
    assert not fz.holds_infinity(FINITE)
    assert not fz.holds_infinity("")
    assert not fz.holds_infinity(None)
    # a word that merely contains the letters, or any other line
    assert not fz.holds_infinity("state 0 info 1\n")
    assert not fz.holds_infinity("cert note inf\nh inf\n")


def test_a_flag_stop_over_an_infinity_is_the_wrong_code():
    # exit 3 was the old outcome; the reader's refusal is exit 2
    assert fz.classify(proc(3, FLAGSTOP), False, WITH_INF) == "WRONG-CODE"
    assert fz.classify(proc(3, FLAGSTOP), False, INV_INF) == "WRONG-CODE"
    assert fz.is_finding("WRONG-CODE")


def test_a_flag_stop_over_a_finite_state_is_still_a_refusal():
    # a finite state can leave the domain on its own; that stop is named
    assert fz.classify(proc(3, FLAGSTOP), False, FINITE) == "REFUSE"
    assert fz.classify(proc(3, FLAGSTOP), False) == "REFUSE"


def test_an_acceptance_over_an_infinity_is_a_finding():
    assert fz.classify(proc(0), False, INV_INF) == "ACCEPT-INFINITY"
    assert fz.is_finding("ACCEPT-INFINITY")
    assert fz.classify(proc(0), False, FINITE) == "ACCEPT"
    assert not fz.is_finding("ACCEPT")


def test_the_readers_own_refusal_of_an_infinity_is_the_intended_outcome():
    assert fz.classify(proc(2, SENTENCE), False, WITH_INF) == "REFUSE"
