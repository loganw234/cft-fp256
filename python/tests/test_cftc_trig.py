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
from cft_golden.lang import constants as K       # noqa: E402
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
