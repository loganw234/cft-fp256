# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The call loop's room (parcel M4LF, 2026-11-11).

A looped batch's body needs plan()'s n registers, all held at once while the
loop is placed, in the allocator's 29 (regalloc.REGS). atan2 at fp32 needs
32, or 31 with an input from one bank slot, under every attribute: the
fifteen plans past the room of the 380 (the routines at four formats and
five attributes, div and atan2 at three `fixed`s each). Before the fix a
step that looped such a batch ended in InternalError ("no register to
evict"), which is neither a result nor a refusal by name. Now the loop
DECLINES the batch it reaches and cannot hold: it stays inlined, where the
allocator spills, the loop goes on to the next batch, and the manifest says
so (routines.call_loop_declined: op, depth, calls, registers, room).

* the room table, recomputed from plan(): exactly those fifteen are past it;
* each of the fifteen, in a looped step (threshold 0): compiles, passes the
  internal check, is declined by name in the manifest, and runs on seq.py
  equal to lang.run under the marked-lane rule;
* the lead's two reproductions and M4SL's (rtz), the 64 and the 96 calls at
  the default threshold;
* the loop goes on past a declined batch; a declined batch it never reached
  is no entry; a batch inside the room loops as before, with no key;
* the control: with the room taken out (declining nothing), the same steps
  are InternalError, so the cases above are the ones that raised.
"""

import random
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import cftc                                      # noqa: E402
from cftc import callloop, regalloc              # noqa: E402
from cftc.refusals import InternalError          # noqa: E402
from cft_golden import FORMATS, lang, seq        # noqa: E402
from cft_golden import routines as R             # noqa: E402
from cft_golden import softfloat as sf           # noqa: E402
from cft_golden.lang import constants as K       # noqa: E402
from lang_mathform import NO_MPMATH, have_mpmath  # noqa: E402

needs_mpmath = pytest.mark.skipif(not have_mpmath(), reason=NO_MPMATH)
ROOM = len(regalloc.REGS)
FIXED = ((), ("a",), ("b",))
# atan2's fixed input, as the source writes it: x from one constant, or y
FORM = {(): "atan2(x[i], y[i])", ("b",): "atan2(x[i], 1.5)",
        ("a",): "atan2(1.5, x[i])"}


def _fixed_of(op):
    names = R.INPUTS[op]
    return [()] + [(n,) for n in names] if len(names) == 2 else [()]


def test_the_room_table_has_exactly_fifteen_plans_past_the_room():
    """Every routine at every format, attribute and fixed (13 one-input
    routines at 20 plans, div and atan2 at 60 each, 380 in all): only atan2
    at fp32 needs more than ROOM, at every attribute and every fixed."""
    assert ROOM == 29
    rows = []
    for op in R.ROUTINES:
        for fn in ("fp32", "fp64", "fp128", "fp256"):
            for rnd in sf.RND_MODES:
                for fx in _fixed_of(op):
                    n = callloop.plan(op, FORMATS[fn], rnd, fx)[1]
                    rows.append((op, fn, rnd, fx, n))
    assert len(rows) == 380
    past = [r for r in rows if r[4] > ROOM]
    assert len(past) == 15
    assert {(r[0], r[1]) for r in past} == {("atan2", "fp32")}
    assert {(r[3], r[4]) for r in past} == {((), 32), (("a",), 31),
                                            (("b",), 31)}
    assert max(r[4] for r in rows if r[4] <= ROOM) == 27


def _text(fmt, rnd, form, n=3):
    return (f"system loop\nformat {fmt}\nround {rnd}\nstate x[{n}], y[{n}]\n"
            f"next x[i] = {form}\nnext y[i] = y[i]\nstep map\n")


def _run(c, seed):
    rng = random.Random(str(seed))
    fmt = c.ir.fmt

    def val():
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(-300, 300), 397))[0]
    n = c.ir.n_primal
    rows = [[val() for _ in range(n)] for _ in range(4)]
    r = c.run(rows)
    m = c.ir.m
    for k, row in enumerate(rows):
        if r.lane_flags[k] & seq.LANE_MARKED:
            continue
        want = lang.run(c.graph, [row], 2)
        assert r.scratch_out[k * m:k * m + n] == want.states[0], k
        assert r.lane_flags[k] & seq.LANE_FLAGS_IEEE == want.flags, k


def _declined(c):
    return c.manifest["routines"].get("call_loop_declined")


@needs_mpmath
@pytest.mark.parametrize("fixed", FIXED, ids=["none", "a", "b"])
@pytest.mark.parametrize("rnd", list(sf.RND_NAMES.values()))
def test_every_atan2_fp32_plan_past_the_room_is_declined_and_runs(
        monkeypatch, rnd, fixed):
    """Three atan2 calls in one batch, the threshold at 0: the loop reaches
    the batch, declines it by name (its registers, the room), the step
    stays inlined and equal to lang.run."""
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    c = cftc.compile_text(_text("fp32", rnd, FORM[fixed]), 2,
                          source="room.cftl")
    assert c.looped == []
    assert _declined(c) == [{"op": "atan2", "depth": 1, "calls": 3,
                             "registers": 32 - len(fixed), "room": 29}]
    assert "call_loops" not in c.manifest["routines"]
    _run(c, (rnd, fixed))


@needs_mpmath
@pytest.mark.parametrize("rnd", ["rne", "rtz"])
def test_the_leads_pair_and_m4sls_rtz(monkeypatch, rnd):
    """The reproduction: next a = atan2(a, b); next b = atan2(b, a) at fp32,
    threshold 0 (rne is the lead's, rtz M4SL's). The same at fp64 loops."""
    text = ("system s\nformat {f}\nround {r}\nstate a, b\n"
            "next a = atan2(a, b)\nnext b = atan2(b, a)\nstep map\n")
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    c = cftc.compile_text(text.format(f="fp32", r=rnd), 5, stem="n")
    assert c.looped == [] and _declined(c)[0]["registers"] == 32
    c64 = cftc.compile_text(text.format(f="fp64", r=rnd), 5, stem="n")
    assert [(b.op, len(b.calls)) for b in c64.looped] == [("atan2", 2)]
    assert _declined(c64) is None


@needs_mpmath
@pytest.mark.parametrize("n", [64, 96])
def test_a_generated_system_at_the_default_threshold(n):
    """A program a user can write: n atan2 calls a step, the last wrapping
    to the first, fp32, CALL_LOOP_ABOVE untouched (32,768). The loop reaches
    the batch (the inlined step is past it), declines it, and the step
    compiles inlined - the target's capacities then decide, and sw takes
    it."""
    assert callloop.CALL_LOOP_ABOVE == 32768
    names = [f"x{i}" for i in range(n)]
    body = "".join(f"next {names[i]} = atan2({names[i]}, "
                   f"{names[(i + 1) % n]})\n" for i in range(n))
    text = (f"system big\nformat fp32\nround rne\nstate {', '.join(names)}\n"
            f"{body}step map\n")
    c = cftc.compile_text(text, 1, stem="n")
    assert c.looped == []
    assert _declined(c) == [{"op": "atan2", "depth": 1, "calls": n,
                             "registers": 32, "room": 29}]
    assert len(c.program.body) + 1 > callloop.CALL_LOOP_ABOVE


_MIXED = ("system loop\nformat fp32\nstate x[3], y[3]\n"
          "next x[i] = sin(x[i]) + atan2(x[i], y[i])\n"
          "next y[i] = y[i]\nstep map\n")


@needs_mpmath
def test_the_loop_goes_on_past_a_declined_batch(monkeypatch):
    """Three sin and three atan2 calls, fp32, threshold 0: the loop reaches
    both, declines atan2 and loops sin, and the step runs equal to
    lang.run. The manifest holds the loop and the declined batch."""
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    c = cftc.compile_text(_MIXED, 2, source="room.cftl")
    assert [(b.op, len(b.calls)) for b in c.looped] == [("sin", 3)]
    assert [d["op"] for d in _declined(c)] == ["atan2"]
    assert [x["op"] for x in
            c.manifest["routines"]["call_loops"]["loops"]] == ["sin"]
    _run(c, "mixed")


@needs_mpmath
def test_a_declined_batch_the_loop_never_reached_is_no_entry(monkeypatch):
    """The same step with the threshold at the length the sin loop alone
    gives: the loop is enough before it reaches atan2 (sin's batch is the
    larger, so first), so nothing is declined, as at the base, and the
    manifest has no key."""
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    first = cftc.compile_text(_MIXED, 2, source="room.cftl")
    assert [d["op"] for d in _declined(first)] == ["atan2"]
    above = len(first.program.body) + 1
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", above)
    c = cftc.compile_text(_MIXED, 2, source="room.cftl")
    assert [(b.op, len(b.calls)) for b in c.looped] == [("sin", 3)]
    assert _declined(c) is None
    assert c.manifest["routines"]["call_loops"]["above"] == above


@needs_mpmath
@pytest.mark.parametrize("fmt", ["fp64", "fp128", "fp256"])
def test_a_batch_inside_the_room_loops_and_has_no_key(monkeypatch, fmt):
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    c = cftc.compile_text(_text(fmt, "rne", FORM[()]), 2, source="room.cftl")
    assert [(b.op, len(b.calls)) for b in c.looped] == [("atan2", 3)]
    assert _declined(c) is None
    assert "call_loop_declined" not in c.manifest["routines"]
    _run(c, fmt)


@needs_mpmath
@pytest.mark.parametrize("fixed", FIXED, ids=["none", "a", "b"])
def test_control_without_the_room_the_same_steps_are_internal_errors(
        monkeypatch, fixed):
    """Taking the fix out (the room infinite, so nothing is declined) puts
    the cases above back to the defect: InternalError, 'no register to
    evict'. The cases are reached."""
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    monkeypatch.setattr(callloop, "room", lambda: 10 ** 6)
    with pytest.raises(InternalError, match="no register to evict"):
        cftc.compile_text(_text("fp32", "rne", FORM[fixed]), 2,
                          source="room.cftl")
