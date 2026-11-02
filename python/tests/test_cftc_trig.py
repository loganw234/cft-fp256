# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cftc compiling sin, cos and tan as routines (parcel M2C, M2's build, item 5).

The language gains the three as nodes (parcel M2L, language 1.2) and cftc
carries them as routines, the nine of the math library: each run-time node
is inlined as its fragment (cft_golden/mathlib.py's, handed out by
routines.fragment), quiet, then a RAISE of its flag word, whose bit 7 MARKS
the lane where the in-lane test cannot decide the last bit. This file holds
what is new in cftc; the six's tests are test_cftc.py's and the routines'
own statements test_routines.py's.

BELOW THE LANGUAGE (this part needs no node of M2L's). The step graph's
bytes are the compiler's one input (cftc/ir.py), so the three are tested
before the language has them: the bytes of an `exp` system with the node's
operation swapped for `sin`, `cos` or `tan` are a graph the compiler reads
exactly as it reads the language's own (a later test shows the bytes are the
same). From there the pipeline is the compiler's: ir.Graph, lower,
best_program, the text, the assembler and the internal check (verify), then
seq.py against routines.GOLDEN, which is transcend.py's:

* the tables: cftc.MATH, ir.ROUTINES and ARITY, emit.ROUTINE_SOURCE and the
  manifest's RADIAN name the nine as routines.py does, in the language's
  order, with no mpmath imported by a program without them;
* each of the three at every format and attribute (60 images) compiles,
  passes the internal check and runs on seq.py equal to the golden function
  lane by lane, bits and flags, a marked lane compared only as a guess;
* MIN and MAX inside a routine (sin's and cos's clamp, which no other
  routine has) are accepted by the emitter, the assembler and the internal
  check, and held by it: a MAX emitted as a MIN is refused;
* the internal check holds an instruction to its attribute, a bank word to
  its bits, the mark to the flag word, and each fragment to its format,
  attribute and live cap;
* the spills: the first k at which a value is spilled, measured at every k.
"""

import hashlib
import json
import random
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

import cftc                                      # noqa: E402
from cftc import callloop, emit, ir, manifest, regalloc  # noqa: E402
from cftc import check as cftc_check             # noqa: E402
from cftc import targets as T                    # noqa: E402
from cftc.ir import Graph                        # noqa: E402
from cftc.lower import halve, lower              # noqa: E402
from cftc.regalloc import best_program           # noqa: E402
from cft_golden import FORMATS, asm, lang, seq   # noqa: E402
from cft_golden import routines as R             # noqa: E402
from cft_golden import softfloat as sf           # noqa: E402
from cft_golden.lang import check as lang_check_mod  # noqa: E402
from cft_golden.lang import constants as K       # noqa: E402
from cft_golden.lang import tangent as lang_tangent  # noqa: E402
from cft_golden.lang.graph import Node           # noqa: E402
from lang_mathform import NO_MPMATH, have_mpmath  # noqa: E402

SIX = ("exp", "expm1", "exp2", "log", "log1p", "log2")
THREE = ("sin", "cos", "tan")
NINE = SIX + THREE
FMT_NAMES = ("fp32", "fp64", "fp128", "fp256")
RND_NAMES = sf.RND_NAMES
needs_mpmath = pytest.mark.skipif(not have_mpmath(), reason=NO_MPMATH)


# ---- the tables -------------------------------------------------------------

def test_the_tables_name_the_three_as_routines_routines_py_does():
    """cftc.MATH is routines.BUILT (a routine left out of it would be an
    ImportError on a host without mpmath, where the rule is `routine-
    unavailable`); emit.ROUTINE_SOURCE names every routine (a looped call's
    comment is a KeyError otherwise); ir.ROUTINES is the routines; and
    ir.ARITY, whose order is the manifest's graph_by_op, holds the three of
    arity one directly after log2 and before neg, the place the language
    gives them (test_routines.py pins the whole of it to lang.OPS)."""
    assert cftc.MATH == R.BUILT == NINE
    assert set(emit.ROUTINE_SOURCE) == set(R.ROUTINES) == \
        {"div", "sqrt", *NINE}
    assert [emit.ROUTINE_SOURCE[op] for op in THREE] == \
        ["mathlib's sin", "mathlib's cos", "mathlib's tan"]
    assert ir.ROUTINES == frozenset(R.ROUTINES)
    names = list(ir.ARITY)
    at = names.index("log2")
    assert names[at + 1:at + 5] == ["sin", "cos", "tan", "neg"]
    assert [ir.ARITY[op] for op in THREE] == [1, 1, 1]
    assert manifest.RADIAN == THREE
    assert set(manifest.RADIAN) <= set(cftc.MATH)
    assert list(callloop.ORDER) == list(R.ROUTINES)
    assert [callloop.ORDER[op] for op in THREE] == [8, 9, 10]


_NO_MPMATH_TABLES = r"""
import sys
root = sys.argv[1]
sys.path.insert(0, root + "/python")
import cftc
from cft_golden import FORMATS, routines as R
from cft_golden import softfloat as sf
assert "mpmath" not in sys.modules, "importing cftc imported mpmath"
try:
    import mpmath
    print("MPMATH IMPORTS HERE")
    sys.exit(1)
except ImportError:
    pass
assert cftc.MATH == R.BUILT and list(R.ROUTINES)[-3:] == ["sin", "cos", "tan"]
assert R.LIVE_CAP["sin"] == {"fp32": 23, "fp64": 26, "fp128": 17,
                             "fp256": 16}
# division's fragment needs no mpmath; one of the nine's is an ImportError
# (the compiler refuses such a source routine-unavailable before it)
R.fragment("div", FORMATS["fp64"], sf.RND_RNE)
assert "mpmath" not in sys.modules
for op in R.BUILT:
    try:
        R.fragment(op, FORMATS["fp64"], sf.RND_RNE)
    except ImportError:
        continue
    print("NO IMPORTERROR FOR", op)
    sys.exit(1)
print("ok")
"""


def test_the_tables_and_division_need_no_mpmath():
    """In a child process under `python -B -I -S` - isolated, no site
    directory, so mpmath is not importable at all, which is a host without
    it - cftc and routines.py import without mpmath, the three's cap rows
    are there, division's fragment is built, and a fragment of any of the
    nine is an ImportError (never reached by the compiler, which refuses
    the source `routine-unavailable` first)."""
    r = subprocess.run([sys.executable, "-B", "-I", "-S", "-c",
                        _NO_MPMATH_TABLES, str(ROOT)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "ok", \
        (r.returncode, r.stdout, r.stderr)


_NO_MPMATH_REFUSAL = r"""
import json, sys, types
sys.modules["mpmath"] = None            # import mpmath raises ImportError
sys.path.insert(0, sys.argv[1] + "/python")
import cftc
from cft_golden import lang


def graph(*ops):
    sec = types.SimpleNamespace(nodes=[(op, ["s0"], None) for op in ops])
    return types.SimpleNamespace(
        section=lambda name: sec if name == "step" else None)


out = {}
for ops in (("sin",), ("cos",), ("tan",), ("tan", "exp"),
            ("sin", "cos", "tan"), ("div", "sqrt"), ("fma",)):
    try:
        cftc.refuse_unavailable(graph(*ops), "src.cftl")
        out[",".join(ops)] = None
    except lang.Refusal as e:
        out[",".join(ops)] = [e.name, e.line, e.sentence]
print(json.dumps(out))
"""


def test_a_graph_holding_the_three_is_routine_unavailable_without_mpmath():
    """On a host without mpmath (a child process with it taken away) a step
    graph holding a run-time sin, cos or tan is refused `routine-
    unavailable` by refuse_unavailable - by name, no line, the sentence
    naming the functions in MATH's order, mathlib.py and mpmath - and one
    holding division, root and fma alone is not. This is cftc.MATH
    extended to the nine: left at the six it returns nothing for the three,
    and the compile goes on to build a fragment and meets an ImportError.
    (A compile of a source naming them, through the language, is the same
    test with the language's part: test_routine_unavailable_*.)"""
    r = subprocess.run([sys.executable, "-B", "-c", _NO_MPMATH_REFUSAL,
                        str(ROOT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for ops in ("sin", "cos", "tan", "tan,exp", "sin,cos,tan"):
        name, line, sentence = got[ops]
        names = ", ".join(op for op in cftc.MATH if op in ops.split(","))
        assert (name, line) == ("routine-unavailable", None), (ops, got[ops])
        assert sentence.startswith(f"this system computes {names} at run "
                                   f"time"), sentence
        assert "mathlib.py" in sentence and "mpmath" in sentence
    assert got["div,sqrt"] is None and got["fma"] is None


# ---- below the language ------------------------------------------------------

def _exp_text(fmt, rnd="rne", states=("x",), body=None):
    """A one-exp system: x' = exp(x), or `body` on `states`."""
    body = body or {"x": "exp(x)"}
    nexts = "".join(f"next {s} = {body[s]}\n" for s in states)
    return (f"system t\nformat {fmt}\nround {rnd}\nstate {', '.join(states)}"
            f"\n{nexts}step map\n")


def swapped(text, fn):
    """The step graph's bytes of `text`, an exp system, with its one exp
    node's operation swapped for `fn`: the graph of the same system with
    `fn` in place of exp, as the compiler reads it."""
    b = lang.compile_text(text, "src.cftl").graph.to_bytes()
    assert b.count(b'["exp",') == 1
    return b.replace(b'["exp",', b'["%s",' % fn.encode("ascii"))


def build(graph_bytes, steps=1):
    """The compiler's pipeline from the graph's bytes, below the language:
    ir.Graph, lower, best_program, the .cfta text, the assembler and the
    internal check (cftc/__init__.py's compile_graph without the language's
    part, the canonical form read back). -> a cftc.Compilation with what
    run() and the check need."""
    g = Graph(graph_bytes)
    low = lower(g, None, source="<bytes>")
    half = halve(low, "<bytes>") if low.h_slots else None
    prog = best_program(low)
    meta = {"stem": "t", "source": "<bytes>", "target": "sw",
            "source_sha256": "(none: a graph)", "format_override": None}
    text = emit.cfta(low, prog, steps, meta)
    img = emit.assemble(text, "t")
    image = img.to_bytes()
    cftc_check.verify(low, prog, image, steps, half)
    c = cftc.Compilation()
    c.ir, c.lowered, c.program, c.image, c.image_obj = g, low, prog, image, img
    c.depth = emit.scratch_declared(prog.slots_used)
    c.cfta, c.steps, c.half = text, steps, half
    return c


def lanes(fmt, rnd, seed):
    """22 arguments: the specials (zeros, infinities, both NaNs, the
    smallest subnormal, both signs), ten rationals about 0 to 2.3, 2^-26 and
    3 2^-26 (a cos and a tan centre at fp64: the first marks under rtz, rdn
    and rup, the second under rne and rmm for tan), pi to seven digits and
    10^6 + 1/3."""
    rng = random.Random(seed)

    def val(q):
        return K.round_once(fmt, rnd, q)[0]
    xs = [0, fmt.sign_mask, sf.inf_bits(fmt, 0), sf.inf_bits(fmt, 1),
          sf.qnan_bits(fmt), sf.snan_bits(fmt), 1, 1 | fmt.sign_mask]
    xs += [val(Fraction(rng.randint(-900, 900), 397)) for _ in range(10)]
    xs += [val(Fraction(1, 2 ** 26)), val(Fraction(3, 2 ** 26)),
           val(Fraction(31415926, 10 ** 7)),
           val(Fraction(10 ** 6) + Fraction(1, 3))]
    return xs


def against_golden(c, fn, fmt, rnd, xs):
    """The image on seq.py, one step, against routines.GOLDEN (transcend's
    function, the definition): every unmarked lane's value and lane byte's
    flags equal to the golden function's, bit for bit; a marked lane (byte
    [7]) a guess, compared only as one, within an encoding of the
    definition's value. -> (the Result, the marked lanes)."""
    r = c.run([[x] for x in xs])
    m = c.ir.m
    marked = []
    for k, x in enumerate(xs):
        byte = r.lane_flags[k]
        out = r.scratch_out[k * m]
        want, flags = R.GOLDEN[fn](fmt, x, rnd)
        where = (fn, fmt.name, RND_NAMES[rnd], hex(x))
        if byte & seq.LANE_MARKED:
            marked.append(k)
            assert abs(out - want) <= 1, (where, "the guess", hex(out),
                                          hex(want))
            continue
        assert out == want, (where, hex(out), hex(want))
        assert byte & seq.LANE_FLAGS_IEEE == flags, (where, "flags", byte,
                                                     flags)
        assert not byte & (seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_SCRATCH_RANGE)
    assert bool(r.status & seq.STATUS_MARKED) == bool(marked)
    return r, marked


@needs_mpmath
@pytest.mark.parametrize("fn", THREE)
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_each_of_the_three_runs_below_the_language_as_its_golden_function(
        fn, fmt_name):
    """At the format under all five attributes: the graph's bytes through
    ir.Graph, lower, best_program, the text, the assembler and the internal
    check; the image on seq.py against transcend's function through
    routines.GOLDEN, lane by lane (see against_golden). The marked lanes of
    the pool are listed by the structured families (docs/studies/M2-trig.md,
    3.5): at fp64, cos at 2^-26 and 3 2^-26 under rtz, rdn and rup and tan at
    3 2^-26 under rne and rmm, and no lane at the other formats."""
    fmt = FORMATS[fmt_name]
    want_marked = {}
    if fmt_name == "fp64":
        want_marked = {("cos", sf.RND_RTZ): [18, 19],
                       ("cos", sf.RND_RDN): [18, 19],
                       ("cos", sf.RND_RUP): [18, 19],
                       ("tan", sf.RND_RNE): [19], ("tan", sf.RND_RMM): [19]}
    for rnd in sf.RND_MODES:
        c = build(swapped(_exp_text(fmt_name, RND_NAMES[rnd]), fn))
        assert c.lowered.routines == [fn]
        assert "FLAG_CONTROL" in [T.ASM_FEATURE.get(f, f)
                                  for f in c.image_obj.features()]
        r, marked = against_golden(c, fn, fmt, rnd,
                                   lanes(fmt, rnd, f"{fn}{rnd}"))
        assert marked == want_marked.get((fn, rnd), []), \
            (fn, fmt_name, RND_NAMES[rnd], marked)
        assert bool(r.status & seq.STATUS_MARKED) == bool(marked)


# ---- MIN and MAX inside a routine, and the internal check holding them ------

def _decoded(c):
    return [asm.decode(w) for w in c.image_obj.insns]


def _inside_quiet(dec):
    """The indices of the image's instructions inside a QUIET .. ENDQUIET
    region."""
    out, depth = [], 0
    for k, d in enumerate(dec):
        if d["ctrl"]:
            name = asm.CTRL_NAMES.get(d["op"])
            depth += (name == "quiet") - (name == "endquiet")
        elif depth:
            out.append(k)
    return out


def _of(dec, name):
    return [k for k, d in enumerate(dec)
            if not d["ctrl"] and asm.OP_NAMES.get(d["op"]) == name]


def _image_with(c, words):
    img = asm.Image.from_bytes(c.image)
    return asm.Image(img.fmt, words, img.consts, img.max_deposits, img.flags,
                     scratch_depth=img.scratch_depth,
                     scratch_io=img.scratch_io).to_bytes()


def _refused(c, words):
    with pytest.raises(cftc.InternalError):
        cftc_check.verify(c.lowered, c.program, _image_with(c, words),
                          c.steps, c.half)


def _with_op(word, name):
    """`word` with its opcode changed to `name`'s, every other bit alone."""
    return (word & ~0xFF) | asm.OP_BY_NAME[name]


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
@pytest.mark.parametrize("fn", THREE)
def test_min_and_max_inside_a_routine_are_accepted_and_held(fn, fmt_name):
    """sin's and cos's clamp is two MIN and two MAX against bank words
    inside the routine (`max rk kx`: a register and a bank word, the
    indexed form), which no other routine has and which parcel M2P found no
    other program of the corpora has. The emitter writes them, the
    assembler takes them, and the internal check - which reads the
    assembled words, not the allocator's notes - accepts the image as it
    is and refuses it with a MAX emitted as a MIN, or a MIN as a MAX, each
    in either of its two places. tan holds neither."""
    c = build(swapped(_exp_text(fmt_name), fn))
    dec = _decoded(c)
    mins, maxs = _of(dec, "min"), _of(dec, "max")
    if fn == "tan":
        assert mins == maxs == []
        return
    assert len(mins) == len(maxs) == 2
    quiet = set(_inside_quiet(dec))
    assert set(mins + maxs) <= quiet
    for k in mins + maxs:
        d = dec[k]
        assert (d["ka"], d["kb"], d["kc"], d["kx"]) == (False, True, False,
                                                          True), (fn, k)
    words = list(c.image_obj.insns)
    for k in maxs:
        w = list(words)
        w[k] = _with_op(w[k], "min")
        assert w[k] != words[k]
        _refused(c, w)
    for k in mins:
        w = list(words)
        w[k] = _with_op(w[k], "max")
        assert w[k] != words[k]
        _refused(c, w)
    cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)


@needs_mpmath
def test_select_with_two_bank_words_by_plain_index_is_accepted():
    """The other form M2P found: `select kkr` - two bank words and a
    register - by a plain bank index (under 16), which the six reach only
    through the indexed form. At fp32 the one-routine image holds it in all
    three routines; the check accepted the image (build verified it)."""
    for fn in THREE:
        c = build(swapped(_exp_text("fp32"), fn))
        dec = _decoded(c)
        plain = [k for k in _of(dec, "select")
                 if (dec[k]["ka"], dec[k]["kb"], dec[k]["kc"]) ==
                 (True, True, False) and not dec[k]["kx"]]
        assert plain, fn
        assert set(plain) <= set(_inside_quiet(dec))


@needs_mpmath
def test_the_internal_check_holds_an_instruction_to_its_attribute_and_the_mark():
    """sin at fp64 under rne: an instruction of the routine made to round
    under another attribute (an add.rdn made rne), the select that carries
    the mark in the flag word re-pointed at the unmarked inexact word (the
    nine's marks are SELECT arms - the word 0x90 - where the six's are
    IORs), and a bank word's bits changed are each refused; the image as
    written passes."""
    c = build(swapped(_exp_text("fp64"), "sin"))
    dec = _decoded(c)
    words = list(c.image_obj.insns)
    quiet = _inside_quiet(dec)
    k = next(k for k in quiet if dec[k]["rnd"] == sf.RND_RDN)
    w = list(words)
    w[k] = (words[k] & ~(0x7 << 24)) | (sf.RND_RNE << 24)
    assert w[k] != words[k]
    _refused(c, w)
    # the mark: the one SELECT whose arm is the word 0x90
    mark, plain = (c.lowered.slot_of[("w", 0x90)],
                   c.lowered.slot_of[("w", 0x10)])
    k = next(k for k in _of(dec, "select")
             if (mark, True) in asm.sources(dec[k]))
    d = dec[k]
    srcs = [(plain if (i, isk) == (mark, True) else i, isk)
            for i, isk in asm.sources(d)]
    fields = ("ra", "rb", "rc")
    kw = {f: v for f, (v, _k) in zip(fields, srcs)}
    flags = {"k" + f[1]: isk for f, (_v, isk) in zip(fields, srcs)}
    w = list(words)
    w[k] = asm.alu(d["op"], d["rd"], rnd=d["rnd"], **kw, **flags)
    assert w[k] != words[k]
    _refused(c, w)
    # a word of the bank changed
    slot = c.lowered.slots[mark]
    slot.bits ^= 0x80
    try:
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)
    finally:
        slot.bits ^= 0x80
    cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)


@needs_mpmath
def test_the_internal_check_holds_each_fragment_to_its_format_attribute_and_cap(
        monkeypatch):
    """check.held_fragment, the one door to every fragment the compiler
    reads: a sin fragment made for another attribute, or another format, is
    refused naming sin and what it was made for; and the three's cap rows
    are enforced - sin's fragment at fp64 keeps 26 live, and with the row
    lowered by one it is refused by name, past 25 (the row is one dict:
    routines.LIVE_CAP's, which mathlib.TRIG_LIVE_CAP views)."""
    from cft_golden import mathlib as ml
    fp64, fp32 = FORMATS["fp64"], FORMATS["fp32"]
    good = R.fragment
    cftc_check._HELD.clear()
    monkeypatch.setattr(R, "fragment", lambda op, f, r: good(
        op, f, sf.RND_RTZ if r == sf.RND_RNE else r))
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment("sin", fp64, sf.RND_RNE)
    assert "is sin's at fp64 under 1" in str(e.value)
    cftc_check._HELD.clear()
    monkeypatch.setattr(R, "fragment", lambda op, f, r: good(op, fp32, r))
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment("sin", fp64, sf.RND_RNE)
    assert "is sin's at fp32 under 0" in str(e.value)
    monkeypatch.setattr(R, "fragment", good)
    cftc_check._HELD.clear()
    assert cftc_check.held_fragment("sin", fp64, sf.RND_RNE).live_max() == 26
    monkeypatch.setitem(R.LIVE_CAP["sin"], "fp64", 25)
    assert ml.TRIG_LIVE_CAP["sin"]["fp64"] == 25
    cftc_check._HELD.clear()
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment("sin", fp64, sf.RND_RNE)
    assert "26 values live at once, past 25" in str(e.value)
    monkeypatch.undo()
    cftc_check._HELD.clear()
    assert cftc_check.held_fragment("sin", fp64, sf.RND_RNE).live_max() == 26


# ---- the spills ----------------------------------------------------------------
# A call keeps its fragment's values live and the step's own beside them;
# the allocator has r3 to r31 (regalloc.REGS: 29), so a value beside a call
# is spilled once the fragment's live count and the others come to more than
# 29. M1's build measured exp's first spill with k other values live beside
# it at k = 11 at fp32 and 19 at the double word's formats (exp keeps 19 and
# 11 live scheduled: k + live = 30), by compiling
#
#     next x = exp(x) + y0 + ... + y(k-1);   next y(i) = y(i) * x
#
# at every k and reading the program's spill_slots. The three keep 23, 26,
# 17 and 16 live (R.LIVE_CAP), so their first spills come at k = 30 - 23,
# 30 - 26, 30 - 17 and 30 - 16 = 7, 4, 13 and 14: measured here at every k
# from 0 to one past it, for each of the three, by the same construction on
# the same pipeline (the bytes of the exp system with the node swapped).

def _spill_text(fmt, k):
    ys = [f"y{i}" for i in range(k)]
    body = {"x": " + ".join(["exp(x)"] + ys),
            **{y: f"{y} * x" for y in ys}}
    return _exp_text(fmt, "rne", ["x"] + ys, body)


def spill_slots(fmt_name, k, fn):
    """program.spill_slots of the construction at k other values, for the
    routine `fn` (exp itself, or one of the three by the swap)."""
    b = lang.compile_text(_spill_text(fmt_name, k), "s.cftl").graph.to_bytes()
    assert b.count(b'["exp",') == 1
    b = b.replace(b'["exp",', b'["%s",' % fn.encode("ascii"))
    return best_program(lower(Graph(b), None, source="<bytes>")).spill_slots


@needs_mpmath
@pytest.mark.parametrize("fn", THREE)
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_the_first_spill_beside_a_call_comes_at_30_less_the_cap(fn, fmt_name):
    """For each of the three at each format, at every k from 0 to one past
    the threshold: no spill at any k under 30 - the cap (23, 26, 17, 16: so
    7, 4, 13, 14), one at it and two at the next. fp32's 23 live leave 6 of
    the 29 registers beside a call: the 7th other value is the first one
    spilled."""
    cap = R.LIVE_CAP[fn][fmt_name]
    assert len(regalloc.REGS) == 29
    first = len(regalloc.REGS) + 1 - cap
    got = [spill_slots(fmt_name, k, fn) for k in range(first + 2)]
    assert got == [0] * first + [1, 2], (fn, fmt_name, first, got)
    if fmt_name == "fp32":
        assert (cap, first, len(regalloc.REGS) - cap) == (23, 7, 6)


@needs_mpmath
def test_the_spill_construction_reproduces_the_sixs_published_thresholds():
    """The control for the construction: exp at fp32, which keeps 19 live
    scheduled, first spills at k = 11 (10 give none, 12 give two) as M1's
    build measured it at 97076f3 and VMC re-measured it."""
    got = [spill_slots("fp32", k, "exp") for k in range(13)]
    assert got == [0] * 11 + [1, 2]


# ---- compiled through the language (needs M2L's nodes: language 1.2) ------------
# From here a source names sin, cos or tan and goes through the language's
# checker, cftc.compile_text and lang.run - the definition the image is held to.

REV8 = ("u50-rev8", "u50-rev8-quad", "u50-rev8-deep")
# the targets without flag control (CAPS2[14]): revision 7's and the round-2
# and open-core builds
NO_FLAG_CONTROL = ("u50-rev7", "u50-rev7-quad", "u50-round2", "open-core")


def _one(fn, fmt, rnd="rne"):
    return (f"system t\nformat {fmt}\nround {rnd}\nstate x\n"
            f"next x = {fn}(x)\nstep map\n")


def held_by_lang_run(c, xs, steps):
    """The image on seq.py against lang.run, lane by lane, each lane alone
    through the interpreter (docs/LANGUAGE.md, "A marked lane"): an
    unmarked lane's state and its lane byte's five flags equal the
    interpreter's, bit for bit; a marked lane's value is a guess, compared
    only as one (within an encoding of the definition's) and counted.
    -> (the seq.py Result, the marked lanes)."""
    r = c.run([[x] for x in xs])
    m = c.ir.m
    marked = []
    for k, x in enumerate(xs):
        byte = r.lane_flags[k]
        ref = lang.run(c.graph, [[x]], steps)
        out = r.scratch_out[k * m]
        if byte & seq.LANE_MARKED:
            marked.append(k)
            assert abs(out - ref.states[0][0]) <= 1, (k, hex(x), "the guess")
            continue
        assert out == ref.states[0][0], (k, hex(x), hex(out),
                                         hex(ref.states[0][0]))
        assert byte & seq.LANE_FLAGS_IEEE == ref.flags, (k, hex(x), "flags")
        assert not byte & (seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_SCRATCH_RANGE)
    assert bool(r.status & seq.STATUS_MARKED) == bool(marked)
    if not marked:
        ref = lang.run(c.graph, [[x] for x in xs], steps)
        assert r.flags == ref.flags
    return r, marked


def test_the_hand_built_bytes_are_the_languages_bytes():
    """Below the language the step graph was the bytes of an exp system with
    the node swapped (build(), swapped()). The language writes the same
    bytes for the system with sin, cos or tan in exp's place - at every
    format and attribute - so the tests above read the graph the compiler
    is really given."""
    for fmt in FMT_NAMES:
        for rnd in RND_NAMES.values():
            for fn in THREE:
                mine = swapped(_exp_text(fmt, rnd), fn)
                theirs = lang.compile_text(_one(fn, fmt, rnd),
                                           "src.cftl").graph.to_bytes()
                assert mine == theirs, (fn, fmt, rnd)


@needs_mpmath
@pytest.mark.parametrize("fn", THREE)
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_each_of_the_three_compiles_and_runs_as_lang_run_at_every_attribute(
        fn, fmt_name):
    """sin(x), cos(x) and tan(x) at the format under all five attributes,
    two steps: cftc.compile_text, the image on seq.py against lang.run lane
    by lane under the marked-lane rule (held_by_lang_run). The routine is
    one call, the image says version 7 and needs FLAG_CONTROL; under rne,
    the other targets that publish it compile the same image and bank
    (revision 8's three, and sw:4096), and the four that do not refuse it
    `target-feature`, naming the bit and the routine. The marked lanes of
    the first step are the structured families' (docs/studies/M2-trig.md,
    3.5): at fp64, cos at 2^-26 and 3 2^-26 under rtz, rdn and rup and tan
    at 3 2^-26 under rne and rmm."""
    fmt = FORMATS[fmt_name]
    first = {}
    if fmt_name == "fp64":
        first = {("cos", sf.RND_RTZ): [18, 19], ("cos", sf.RND_RDN): [18, 19],
                 ("cos", sf.RND_RUP): [18, 19], ("tan", sf.RND_RNE): [19],
                 ("tan", sf.RND_RMM): [19]}
    for rnd in sf.RND_MODES:
        text = _one(fn, fmt_name, RND_NAMES[rnd])
        c = cftc.compile_text(text, 2, source="t.cftl")
        assert c.version == cftc.VERSION == 7
        assert c.manifest["compiler"] == {"name": "cftc", "version": 7}
        assert c.manifest["routines"]["calls"] == {fn: 1}
        assert "FLAG_CONTROL" in c.features
        assert c.accepted_by == ["sw", *REV8]
        xs = lanes(fmt, rnd, f"{fn}{rnd}")
        r, marked = held_by_lang_run(c, xs, 2)
        assert set(first.get((fn, rnd), [])) <= set(marked), \
            (fn, fmt_name, RND_NAMES[rnd], marked)
        if rnd != sf.RND_RNE:
            continue
        for t in REV8 + ("sw:4096",):
            ct = cftc.compile_text(text, 2, target=t, source="t.cftl")
            assert (ct.image, ct.bank) == (c.image, c.bank), t
        for t in NO_FLAG_CONTROL:
            with pytest.raises(lang.Refusal) as e:
                cftc.compile_text(text, 2, target=t, source="t.cftl")
            assert e.value.name == "target-feature", (t, str(e.value))
            assert "FLAG_CONTROL (CAPS2[14])" in e.value.sentence
            assert fn in e.value.sentence


@needs_mpmath
def test_a_marked_lane_through_a_compiled_image_cos_at_2_to_the_minus_26():
    """cos at fp64 under rtz on a lane at 2^-26, the first structured centre
    (docs/studies/M2-trig.md, 3.5): cos x = 1 - x^2/2 + ..., and x^2/2 =
    2^-53 is a whole step of the grid below 1, so the true value sits
    x^4/24 above a rounding boundary - closer than the in-lane test's
    bound, which cannot decide the last bit. Through the image's RAISE the
    lane is MARKED - R23's byte [7] - and STATUS[6] is set; its value is
    the routine's best guess, compared only as one; an ordinary lane is
    unmarked, the interpreter's bit for bit with its flags; and the same
    lane under rne is not marked (the centre is a directed one)."""
    fmt = FORMATS["fp64"]
    x = K.round_once(fmt, sf.RND_RTZ, Fraction(1, 2 ** 26))[0]
    plain = K.round_once(fmt, sf.RND_RTZ, Fraction(1, 3))[0]
    c = cftc.compile_text(_one("cos", "fp64", "rtz"), 1, source="t.cftl")
    r, marked = held_by_lang_run(c, [plain, x], 1)
    assert marked == [1]
    assert r.lane_flags[1] & seq.LANE_MARKED and r.status & seq.STATUS_MARKED
    assert not r.lane_flags[0] & seq.LANE_MARKED
    # the definition's value is correctly rounded (toward zero): below 1
    ref = lang.run(c.graph, [[x]], 1).states[0][0]
    assert ref == sf.one_bits(fmt) - 1
    assert abs(r.scratch_out[c.ir.m] - ref) <= 1
    c2 = cftc.compile_text(_one("cos", "fp64", "rne"), 1, source="t.cftl")
    x2 = K.round_once(fmt, sf.RND_RNE, Fraction(1, 2 ** 26))[0]
    r2, marked2 = held_by_lang_run(c2, [x2], 1)
    assert marked2 == [] and not r2.status & seq.STATUS_MARKED


def _calls(c):
    return c.manifest["routines"]["calls"]


def _node_counts(c, routine, op, pred=lambda low, j, nd: True):
    """How many nodes of the lowered step are `op` reading the result of the
    routine node `routine` (a refs' ("n", index)) in some operand."""
    low = c.lowered
    js = [j for j, nd in enumerate(low.nodes) if nd.op == routine]
    assert len(js) == 1, (routine, js)
    return sum(1 for j, nd in enumerate(low.nodes)
               if nd.op == op and ("n", js[0]) in nd.args
               and pred(low, j, nd))


@needs_mpmath
@pytest.mark.parametrize("vectors", ["v", "v, w"])
def test_the_tangents_routines_are_one_call_a_call_and_share_the_primals(
        vectors):
    """The three rules write routines the primal need not hold: sin's reads
    cos(a), cos's reads sin(a). With one tangent vector and with two, each
    is ONE call of its routine, not one a vector - and sharing the primal
    routine's reduction and polynomials, so that the pair costs 434
    instructions at fp64 (sin 406, cos 402 apart: 808), not a second routine
    - and its negation (cos) and tan's fma(r, r, 1) are one node, read by
    each vector's product."""
    one = Fraction(1)
    for fn, other in (("sin", "cos"), ("cos", "sin"), ("tan", None)):
        text = (f"system p\nformat fp64\nstate x, y\ntangent {vectors}\n"
                f"next x = {fn}(x * y)\nnext y = y\nstep map\n")
        c = cftc.compile_text(text, 2, source="p.cftl")
        T = len(vectors.split(","))
        assert c.ir.T == T
        want = {fn: 1} if other is None else {fn: 1, other: 1}
        assert _calls(c) == want, (fn, vectors, _calls(c))
        quiet = c.manifest["routines"]["instructions_quiet"]
        assert quiet == {"sin": 434, "cos": 434, "tan": 419}[fn], (fn, quiet)
        assert c.manifest["routines"]["raises"] == len(want)
        if fn == "tan":
            # r twice and a constant 1: one fma, whatever the vectors
            assert _node_counts(c, "tan", "fma") == 1
        if fn == "cos":
            # sin(a) negated exactly: one neg, whatever the vectors
            assert _node_counts(c, "sin", "neg") == 1
        # a vector adds its products, never a routine's instruction
        ref = cftc.compile_text(
            text.replace(f"tangent {vectors}", "tangent v"), 2,
            source="p.cftl")
        assert ref.manifest["routines"]["instructions_quiet"] == quiet
        states, tans = _lanes_with_tangents(c.ir, f"{fn}{vectors}")
        r = c.run(states, tangents=tans)
        m, n, N = c.ir.m, c.ir.n_primal, c.ir.n_state
        for k, st in enumerate(states):
            if r.lane_flags[k] & seq.LANE_MARKED:
                continue
            want_run = lang.run(c.graph, [st], 2, tangents=[tans[k]])
            out = r.scratch_out[k * m:(k + 1) * m]
            assert out[:n] == want_run.states[0], (fn, k, "states")
            assert out[n:N] == [v for vec in want_run.tangents[0]
                                for v in vec], (fn, k, "tangents")
            assert r.lane_flags[k] & seq.LANE_FLAGS_IEEE == want_run.flags


def _lanes_with_tangents(g, seed):
    fmt = g.fmt
    rng = random.Random(seed)

    def val():
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(-900, 900), 397))[0]
    n = g.n_primal
    states = [[val() for _ in range(n)] for _ in range(5)]
    states += [[0] * n, [sf.snan_bits(fmt)] * n]
    tans = [[[val() for _ in range(n)] for _ in g.tangent] for _ in states]
    return states, tans


# the instructions the routines of one operand cost in one image, MEASURED
# here by compiling `next x = f(y)` (the manifest's instructions_quiet): the
# double word's three are the study's share.py figures (M2-trig.md, 2.1),
# fp32's triple word is new
SHARING = {   # format: alone (sin, cos, tan), then sin+cos, sin+tan,
    #           cos+tan, all three
    "fp32": ((939, 936, 993), 988, 1043, 1039, 1088),
    "fp64": ((406, 402, 419), 434, 449, 446, 475),
    "fp128": ((382, 378, 397), 411, 428, 425, 455),
    "fp256": ((389, 385, 406), 418, 437, 434, 464),
}


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_the_routines_of_one_operand_share_their_prefix(fmt_name):
    """sin(y), cos(y) and tan(y) in one step compute the reduction and both
    polynomials once (inline.py's hash-consing of a routine's instructions
    by opcode, attribute and operands): sin and cos together cost 28 to 49
    instructions more than sin alone, all three 69 to 149 more than sin
    alone - where apart they would cost the sum. The figures are the manifest's instructions_quiet,
    the study's (fp64, fp128, fp256) and fp32's new."""
    alone, sc, st, ct, allthree = SHARING[fmt_name]

    def quiet(expr):
        text = (f"system s\nformat {fmt_name}\nstate x, y\nnext x = {expr}\n"
                f"next y = y\nstep map\n")
        return cftc.compile_text(text, 1, source="s.cftl").manifest[
            "routines"]["instructions_quiet"]
    got = tuple(quiet(f"{fn}(y)") for fn in THREE)
    assert got == alone
    assert quiet("sin(y) + cos(y)") == sc
    assert quiet("sin(y) + tan(y)") == st
    assert quiet("cos(y) + tan(y)") == ct
    assert quiet("sin(y) + cos(y) + tan(y)") == allthree
    assert sc < alone[0] + alone[1] and allthree < sum(alone)
    # a different operand shares nothing
    assert quiet("sin(y) + cos(x)") == alone[0] + alone[1]


# ---- the call loop over unary radian batches -----------------------------------

def _looped(monkeypatch, text, above, steps=2, **kw):
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", above)
    return cftc.compile_text(text, steps, source="loop.cftl", **kw)


def _batches(c):
    return [(b.op, b.depth, len(b.calls)) for b in c.looped]


@needs_mpmath
def test_a_call_loop_of_the_three_in_the_stated_order(monkeypatch):
    """With the constant lowered to 0, a step with three sin, three cos and
    three tan calls at one depth loops all three batches - one copy of each
    routine in a REPEAT over records of one slot (a unary routine's, as
    sqrt's) - held by the internal check and run on seq.py as lang.run runs
    it. The ORDER the batches are looped in is the callloop's: largest first
    (calls times the fragment's instructions: tan's 419, sin's 406 and cos's
    402 at fp64), and the order batches() lists them in - by depth, then
    callloop.ORDER, which is routines.ROUTINES, the language's - sin, cos,
    tan. The same step inlined has no loop."""
    text = ("system loop\nformat fp64\nstate x[3], y[3]\n"
            "next x[i] = sin(x[i]) * 0.5 + cos(y[i])\n"
            "next y[i] = tan(y[i]) - x[i]\nstep map\n")
    inl = cftc.compile_text(text, 2, source="loop.cftl")
    assert inl.looped == [] and _calls(inl) == {"sin": 3, "cos": 3, "tan": 3}
    c = _looped(monkeypatch, text, 0)
    assert _batches(c) == [("tan", 1, 3), ("sin", 1, 3), ("cos", 1, 3)]
    sizes = {op: len(R.fragment(op, FORMATS["fp64"], sf.RND_RNE))
             for op in THREE}
    assert sorted(sizes, key=lambda op: -3 * sizes[op]) == \
        [b[0] for b in _batches(c)]
    assert [b.op for b in callloop.batches(c.lowered)] == list(THREE)
    assert callloop.ORDER == {op: k for k, op in enumerate(R.ROUTINES)}
    loops = c.manifest["routines"]["call_loops"]["loops"]
    assert {e["op"] for e in loops} == set(THREE)
    assert all(e["calls"] == 3 and e["records"][1] - e["records"][0] == 2
               for e in loops)
    states, _t = _lanes_with_tangents(c.ir, "loop three")
    r = c.run(states)
    m, n = c.ir.m, c.ir.n_primal
    for k, st in enumerate(states):
        if r.lane_flags[k] & seq.LANE_MARKED:
            continue
        want = lang.run(c.graph, [st], 2)
        assert r.scratch_out[k * m:k * m + n] == want.states[0], k
        assert r.lane_flags[k] & seq.LANE_FLAGS_IEEE == want.flags, k


@needs_mpmath
def test_the_real_constant_loops_sin_at_80_calls_and_not_at_79():
    """The constant is 32,768 instructions (callloop.CALL_LOOP_ABOVE), no
    target's. MEASURED at every n from 76 to 80 sin calls at fp64: the
    inlined step is 31,237, 31,648, 32,059, 32,470 and - at 80 - 32,881
    instructions, 411 a call, so the first n past it is 80: n = 79 compiles
    inlined and n = 80 loops all 80 calls in one batch (736 instructions
    written, 33,363 run a step). Here the two sides of the threshold,
    80 run against lang.run."""
    def text(n):
        return (f"system big\nformat fp64\nstate x[{n}]\n"
                f"next x[i] = sin(x[i])\nstep map\n")
    c79 = cftc.compile_text(text(79), 1, source="big.cftl")
    assert c79.looped == [] and len(c79.program.body) + 1 == 32470
    assert 32470 + 411 > callloop.CALL_LOOP_ABOVE >= 32470
    c80 = cftc.compile_text(text(80), 1, source="big.cftl")
    assert _batches(c80) == [("sin", 1, 80)]
    assert (len(c80.program.body) + 1, c80.program.executed()) == (736, 33363)
    states, _t = _lanes_with_tangents(c80.ir, "sin 80")
    r = c80.run(states[:3])
    m, n = c80.ir.m, c80.ir.n_primal
    for k, st in enumerate(states[:3]):
        if r.lane_flags[k] & seq.LANE_MARKED:
            continue
        want = lang.run(c80.graph, [st], 1)
        assert r.scratch_out[k * m:k * m + n] == want.states[0], k


# ---- the manifest's wording ------------------------------------------------------

def _routines_block(text, steps=1):
    return cftc.compile_text(text, steps, source="w.cftl").manifest["routines"]


@needs_mpmath
def test_the_manifest_words_the_three_only_where_a_step_holds_one():
    """The routines block says where the fragments come from and what their
    raises do. A step with the six alone, or with division and root, has the
    sentences it had at 19de866c - the committed Lotka-Volterra's and
    Kepler's manifests are those words - and a step with sin, cos or tan
    adds a sentence of the three's own; a step with none of the six omits
    the six's."""
    lv = json.loads((ROOT / "programs" / "systems" / "compiled-tangent" /
                     "lotkavolterra-rk4-tangent-fp64.manifest.json"
                     ).read_text(encoding="ascii"))["routines"]
    kp = json.loads((ROOT / "programs" / "systems" / "compiled-tangent" /
                     "kepler-sv-tangent-fp64.manifest.json"
                     ).read_text(encoding="ascii"))["routines"]
    six_only = _routines_block("system a\nformat fp64\nstate x\n"
                               "next x = exp(x)\nstep map\n")
    assert (six_only["source"], six_only["flags"]) == (lv["source"],
                                                       lv["flags"])
    assert "the math library's six also set" in six_only["flags"]
    c4_only = _routines_block("system a\nformat fp64\nstate x, y\n"
                              "next x = x / (y * y + 1) + sqrt(abs(x))\n"
                              "next y = y\nstep map\n")
    assert c4_only["source"].startswith("cft_golden/routines.py: divfull's")
    assert "math library" not in c4_only["source"] + c4_only["flags"]
    assert (kp["source"], kp["flags"]) == (c4_only["source"],
                                           c4_only["flags"])
    three = " likewise set the raised word's bit 7"
    for fn in THREE:
        b = _routines_block(f"system a\nformat fp64\nstate x\n"
                            f"next x = {fn}(x)\nstep map\n")
        assert "the math library's sin, cos and tan" + three in b["flags"]
        assert "the math library's six" not in b["flags"]
        assert b["source"] == ("cft_golden/routines.py: the math library's "
                               "fragments, cft_golden/mathlib.py's, built at "
                               "the program's format and attribute")
        assert b["flags"].startswith(six_only["flags"].split("; the math "
                                                              "library's")[0])
    both = _routines_block("system a\nformat fp64\nstate x, y\n"
                           "next x = exp(x) + sin(y)\nnext y = y\n"
                           "step map\n")
    assert six_only["flags"] in both["flags"]
    assert both["flags"].index("the math library's six") < \
        both["flags"].index("the math library's sin, cos and tan")
    mixed = _routines_block("system a\nformat fp64\nstate x, y\n"
                            "next x = x / (y * y + 1) + tan(y)\nnext y = y\n"
                            "step map\n")
    assert mixed["source"].count("; ") == 1 and \
        mixed["source"].startswith("cft_golden/routines.py: divfull's")
    assert "the math library's sin, cos and tan" in mixed["flags"] and \
        "the math library's six" not in mixed["flags"]


# ---- no mpmath -----------------------------------------------------------------

_NO_MPMATH_COMPILE = r"""
import hashlib, json, sys
if sys.argv[2] == "modules":
    sys.modules["mpmath"] = None            # import mpmath raises ImportError
sys.path.insert(0, sys.argv[1] + "/python")
import cftc
from cft_golden import lang
out = {}
for name, (text, kind) in json.loads(sys.argv[3]).items():
    for target in ("sw", "u50-rev8", "u50-rev7"):
        for steps in (3, 0):
            try:
                c = cftc.compile_text(text, steps, target=target,
                                      source="src.cftl")
                out[f"{name} {target} {steps}"] = {
                    k: hashlib.sha256(v).hexdigest()
                    for k, v in c.files().items()}
            except lang.Refusal as e:
                out[f"{name} {target} {steps}"] = [e.name, e.line, e.sentence]
assert "mpmath" not in sys.modules or sys.modules["mpmath"] is None
if sys.argv[2] == "isolated":
    try:
        import mpmath
        out["MPMATH"] = "importable"
    except ImportError:
        pass
print(json.dumps(out, sort_keys=True))
"""


@pytest.mark.parametrize("how", ["modules", "isolated"])
def test_routine_unavailable_for_the_three_without_mpmath(how):
    """Without mpmath - taken out of sys.modules in a child process
    (`modules`: simulated), and in a child under `python -B -I -S` (`isolated`:
    no site directory, so it is not importable at all, which is a host
    without it) - a source with a run-time sin, cos or tan is refused
    `routine-unavailable` on every target, revision 7's included where with
    mpmath it is `target-feature`, with no line, its sentence naming the
    functions, mathlib.py and mpmath; at 0 steps `segment-steps` first. A
    fold (sin(0) and cos(0)) and a quotient compile there to the very bytes
    they compile to here."""
    cases = {
        "sin": ("system a\nformat fp64\nstate x\nnext x = sin(x)\n"
                "step map\n", "routine"),
        "all three": ("system a\nformat fp32\nstate x, y\n"
                      "next x = sin(x) * y\nnext y = cos(x) + tan(y)\n"
                      "step map\n", "routine"),
        "a fold": ("system a\nformat fp64\nstate x\nconst k = cos(0) + "
                   "sin(0)\nnext x = x * k + tan(0)\nstep map\n", "fold"),
        "a quotient": ("system a\nformat fp64\nstate x, y\n"
                       "next x = x / (y * y + 1)\nnext y = y\nstep map\n",
                       "quotient"),
    }
    flags = ["-B", "-I", "-S"] if how == "isolated" else ["-B"]
    r = subprocess.run([sys.executable, *flags, "-c", _NO_MPMATH_COMPILE,
                        str(ROOT), how, json.dumps(cases)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    assert "MPMATH" not in got
    for name, (text, kind) in cases.items():
        for target in ("sw", "u50-rev8", "u50-rev7"):
            assert got[f"{name} {target} 0"][0] == "segment-steps", name
            res = got[f"{name} {target} 3"]
            if kind == "routine":
                assert res[:2] == ["routine-unavailable", None], res
                ops = {"sin": "sin", "all three": "sin, cos, tan"}[name]
                assert res[2].startswith(f"this system computes {ops} at run "
                                         f"time"), res
                assert "mathlib.py" in res[2] and "mpmath" in res[2]
                continue
            if kind == "quotient" and target == "u50-rev7":
                assert res[0] == "target-feature", res
                continue
            here = cftc.compile_text(text, 3, target=target,
                                     source="src.cftl")
            assert res == {k: hashlib.sha256(v).hexdigest()
                           for k, v in here.files().items()}, (name, target)


# ---- the committed references ------------------------------------------------
# programs/systems/compiled-tangent/ holds two systems that carry sin, cos and
# tan, each at fp64 and fp256 (parcel M2C, decisions 3 and 4 of the contract):
# the pendulum (sin in the step, cos(a) * da in the tangent; round rne) and a
# rigid body's attitude (all three in the step and in the tangent; round rdn,
# where cos's rule rounded otherwise is another value as well as other
# bytes). The study's section 7: "A rule rounded otherwise must move its
# bytes", and the committed bytes hold the three rules between them.

SYSTEMS = ROOT / "programs" / "systems"
# the ones the primal holds, and the routines the image calls (the pendulum's
# tangent reads a cos its primal does not hold)
M2_PRIMAL = {"pendulum-rk4": ("sin",), "attitude-rk4": THREE}
M2_CALLS = {"pendulum-rk4": {"sin", "cos"}, "attitude-rk4": set(THREE)}
M2_NAMES = [f"{b}-tangent-{f}" for b in M2_PRIMAL for f in ("fp64", "fp256")]


def _tref(name):
    """A reference's step graph, from its committed source."""
    return lang.load(SYSTEMS / f"{name}.cftl").graph


def test_the_two_sources_are_one_system_at_two_formats():
    """Each reference's fp256 source is its fp64 source with the format
    line changed, comments too: nothing else differs."""
    for base in M2_PRIMAL:
        a = (SYSTEMS / f"{base}-tangent-fp64.cftl").read_text(
            encoding="ascii").splitlines()
        b = (SYSTEMS / f"{base}-tangent-fp256.cftl").read_text(
            encoding="ascii").splitlines()
        assert len(a) == len(b)
        assert [(x, y) for x, y in zip(a, b) if x != y] == \
            [("format fp64", "format fp256")]
        code = [ln for ln in a if ln and not ln.startswith(";")]
        assert code.count("tangent w") == 1
        assert ("round  rne" if base == "pendulum-rk4" else "round  rdn") \
            in code


@needs_mpmath
@pytest.mark.parametrize("name", M2_NAMES)
def test_the_committed_references_are_what_the_compiler_writes(name):
    """Eight files each, byte for byte what cftc writes for the committed
    source at 10 steps (tangent_check.py --write made them), the manifest
    saying version 7."""
    c = cftc.compile_file(SYSTEMS / f"{name}.cftl", 10,
                          source=f"programs/systems/{name}.cftl")
    files = c.files()
    assert len(files) == 8
    for fname, data in files.items():
        assert (SYSTEMS / "compiled-tangent" / fname).read_bytes() == data, \
            fname
    assert c.manifest["compiler"] == {"name": "cftc", "version": 7}
    assert c.accepted_by == ["sw", *REV8]
    base, fmt = name.rsplit("-", 1)
    assert set(_calls(c)) == M2_CALLS[base.replace("-tangent", "")], \
        (name, _calls(c))


def test_between_them_the_references_hold_the_three_rules():
    """The committed graphs carry each rule in their tangent step: sin's
    cos(a) * da (the pendulum's tangent holds a cos the primal does not,
    four stages' worth), cos's (-sin(a)) * da and tan's fma(r, r, 1) * da
    (the attitude's), each routine one the step reads again - at fp64 and
    fp256."""
    for name in M2_NAMES:
        g = _tref(name)
        base = name.split("-tangent")[0]
        prim = g.op_counts("field")
        tang = g.op_counts("tangent_field")
        step_p, step_t = g.op_counts("step"), g.op_counts("tangent_step")
        for op in THREE:
            assert bool(prim.get(op)) == (op in M2_PRIMAL[base]), \
                (name, op, prim)
        if base == "pendulum-rk4":
            assert tang.get("cos") and not tang.get("sin")
            assert not tang.get("tan") and step_t.get("cos") == 4
        else:
            assert tang.get("sin") and tang.get("cos") and tang.get("tan")
            assert tang.get("neg") and tang.get("fma")
            assert (step_p["sin"], step_p["cos"], step_p["tan"]) == (8, 8, 4)
        graph = (SYSTEMS / "compiled-tangent" / f"{name}.graph.json"
                 ).read_bytes()
        assert g.to_bytes() == graph


class _RulePlant(lang_tangent.Derivation):
    """The derivation with one of the three's rules changed (kind)."""
    kind = None

    def rule(self, node):
        op, a, line = node.op, node.args, node.line
        if op != self.kind[0]:
            return super().rule(node)
        da = self.of(a[0])
        if da is None:
            return None
        R = self.read

        def N(o, *args):
            return Node(o, args, line)
        how = self.kind[1]
        if how.startswith("sin(a) for cos(a)"):
            return N("mul", N("sin", R(a[0])), da)
        if how.startswith("da * cos(a)"):
            return N("mul", da, N("cos", R(a[0])))
        if how.startswith("-(sin(a) * da)"):
            return N("neg", N("mul", N("sin", R(a[0])), da))
        if how.startswith("sin(a) * da"):
            return N("mul", N("sin", R(a[0])), da)
        if how.startswith("(1 + r * r)"):
            return N("mul", N("add", self.one, N("mul", R(node), R(node))),
                     da)
        return N("mul", R(node), da)                  # r * da


M2_RULE_PLANTS = [("sin", "sin(a) for cos(a), made wrong"),
                  ("sin", "da * cos(a), the other order"),
                  ("cos", "-(sin(a) * da), rounded otherwise"),
                  ("cos", "sin(a) * da, the sign dropped"),
                  ("tan", "(1 + r * r) * da, three roundings"),
                  ("tan", "r * da, made wrong")]


@pytest.mark.parametrize("kind", M2_RULE_PLANTS, ids=lambda k: k[1])
def test_each_rule_changed_moves_the_committed_references_holding_it(
        kind, monkeypatch):
    """Each of the three rules changed - rounded otherwise where it rounds
    twice or more, made wrong or written in the other order where it rounds
    once - moves the committed graphs of the references that hold it, at
    fp64 and fp256, and no other committed graph: the six's references among
    them stay (checking a source needs no mpmath, so neither does this)."""
    names = M2_NAMES + [f"{b}-tangent-{f}" for b in (
        "lotkavolterra-rk4", "diode-rk4", "culture-rk4", "lorenz63-rk4",
        "lorenz96-rk4", "kepler-sv") for f in ("fp64", "fp256")]
    committed = {n: (SYSTEMS / "compiled-tangent" / f"{n}.graph.json"
                     ).read_bytes() for n in names}

    class P(_RulePlant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check_mod, "Derivation", P)
    moved = sorted(n for n in names if _tref(n).to_bytes() != committed[n])
    want = sorted(f"{b}-tangent-{f}" for b, ops in M2_PRIMAL.items()
                  if kind[0] in ops for f in ("fp64", "fp256"))
    assert want and moved == want, (kind, moved)




@needs_mpmath
def test_cos_rounded_otherwise_is_another_value_under_rdn_and_rup_only(
        monkeypatch):
    """Why the attitude is compiled round rdn. cos's rule is `(-sin(a)) *
    da`, one product of an exact negation; `-(sin(a) * da)` rounds the
    product and then negates. A one-operation image shows what the rule
    gives (`next y = cos(x)`, whose tangent IS the rule's product): the
    planted derivation's image and the right one run on seq.py agree on every
    finite lane under rne, rtz and rmm - roundings symmetric about zero - and
    differ on a fair share of lanes under rdn and rup, the study's section 7
    (M2L measured the same of the rule alone). The bytes move under every
    attribute: that is the committed references' plant, red on the bytes
    whichever attribute they use. And in the attitude itself the rule's
    product is one term among sums, so the step's output rarely shows it
    (MEASURED when this was written: 0 of 40 lanes at one step and 1 of 12
    at four, under rdn): the rule is held at the attribute where its
    rounding order is a value, not where the output is sensitive to it."""
    class P(_RulePlant):
        pass
    P.kind = ("cos", "-(sin(a) * da), rounded otherwise")
    fmt = FORMATS["fp64"]
    rng = random.Random("cos rounded otherwise")

    def val():
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(-900, 900), 397))[0]
    states = [[val(), val()] for _ in range(40)]
    tans = [[[val(), val()]] for _ in states]
    differ, moved = {}, {}
    for rnd in RND_NAMES.values():
        text = (f"system c\nformat fp64\nround {rnd}\nstate x, y\n"
                f"tangent v\nnext x = x\nnext y = cos(x)\nstep map\n")
        good = cftc.compile_text(text, 1, source="c.cftl")
        monkeypatch.setattr(lang_check_mod, "Derivation", P)
        planted = cftc.compile_text(text, 1, source="c.cftl")
        monkeypatch.undo()
        moved[rnd] = (planted.graph_bytes != good.graph_bytes,
                      planted.image != good.image)
        rg = good.run(states, tangents=tans)
        rp = planted.run(states, tangents=tans)
        assert not any(b & seq.LANE_MARKED for b in rg.lane_flags +
                       rp.lane_flags)
        m = good.ir.m
        differ[rnd] = sum(
            rg.scratch_out[k * m:(k + 1) * m] !=
            rp.scratch_out[k * m:(k + 1) * m] for k in range(len(states)))
    assert set(moved.values()) == {(True, True)}, moved
    assert differ["rne"] == differ["rtz"] == differ["rmm"] == 0, differ
    assert differ["rdn"] > 5 and differ["rup"] > 5, differ


@needs_mpmath
def test_the_attitudes_bytes_move_under_rdn_and_rne_alike(monkeypatch):
    """The rounded-otherwise plant moves the attitude's bytes whichever
    attribute it is compiled under - rdn as committed, rne as a variant."""
    src = (SYSTEMS / "attitude-rk4-tangent-fp64.cftl").read_text(
        encoding="ascii")

    class P(_RulePlant):
        pass
    P.kind = ("cos", "-(sin(a) * da), rounded otherwise")
    for rnd in ("rdn", "rne"):
        text = src.replace("round  rdn", f"round  {rnd}")
        assert f"round  {rnd}" in text
        good = cftc.compile_text(text, 4, source="a.cftl")
        monkeypatch.setattr(lang_check_mod, "Derivation", P)
        planted = cftc.compile_text(text, 4, source="a.cftl")
        monkeypatch.undo()
        assert planted.graph_bytes != good.graph_bytes, rnd
        assert planted.image != good.image, rnd
