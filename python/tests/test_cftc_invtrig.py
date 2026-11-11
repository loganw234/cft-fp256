# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cftc compiling atan, asin, acos and atan2 as routines (parcel M4C, M4's
build, wave 4).

The language gains the four as nodes (parcel M4L, language 1.3) and cftc
carries them as routines, the thirteen of the math library: each run-time
node is inlined as its fragment (cft_golden/mathlib.py's, handed out by
routines.fragment), quiet, then a RAISE of its flag word, whose bit 7 MARKS
the lane where the in-lane test cannot decide the last bit. atan2 is the
first built routine of TWO inputs, y first: its fragment's inputs are
("a", "b") = (y, x), bound in that order to the node's operands.

BELOW THE LANGUAGE (this part needs no node of M4L's). The step graph's
bytes are the compiler's one input (cftc/ir.py), so the four are tested
before the language has them: the bytes of an `exp` system with the node's
operation swapped for `atan`, `asin` or `acos`, and of a `div` system with
its operation swapped for `atan2` (both of arity two), are graphs the
compiler reads exactly as it reads the language's own. From there the
pipeline is the compiler's: ir.Graph, lower, best_program, the text, the
assembler and the internal check (verify), then seq.py against
routines.GOLDEN, which is transcend.py's. This is M2C's method
(test_cftc_trig.py, whose helpers this file reuses).

* the tables: cftc.MATH, ir.ROUTINES and ARITY, emit.ROUTINE_SOURCE and the
  manifest's INVERSE name the four as routines.py does, in the language's
  order, with no mpmath imported by a program without them;
* each of the four at every format and attribute (80 images) compiles,
  passes the internal check and runs on seq.py equal to the golden function
  lane by lane, bits and flags, a marked lane compared only as a guess, the
  marked lanes counted;
* MIN and MAX inside a routine are accepted by the emitter, the assembler
  and the internal check, and held by it;
* atan2's two inputs are bound in order: a binding that swaps them is
  stopped by the internal check, and with the check off is red on seq.py;
  coincident and constant operands are what the golden function says;
* the internal check holds an instruction to its attribute, a bank word to
  its bits, the mark to the flag word, and each fragment to its format,
  attribute and live cap;
* the spills: the first k at which a value is spilled, measured at every k
  from 0 to 20.
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
from cftc import callloop, emit, inline, ir, manifest, regalloc  # noqa: E402
from cftc import check as cftc_check             # noqa: E402
from cftc.ir import Graph                        # noqa: E402
from cftc.lower import lower                     # noqa: E402
from cftc.regalloc import best_program           # noqa: E402
from cft_golden import FORMATS, asm, lang, seq   # noqa: E402
from cft_golden import mathlib as ml             # noqa: E402
from cft_golden import routines as R             # noqa: E402
from cft_golden import softfloat as sf           # noqa: E402
from cft_golden.lang import constants as K       # noqa: E402
from cft_golden.lang import check as lang_check_mod  # noqa: E402
from cft_golden.lang import tangent as lang_tangent  # noqa: E402
from cft_golden.lang.graph import Node           # noqa: E402
from lang_mathform import NO_MPMATH, have_mpmath  # noqa: E402
# M2C's helpers, reused: they build and read an image below the language
from test_cftc_trig import (_decoded, _exp_text, _image_with,  # noqa: E402
                            _inside_quiet, _of, _refused, _with_op, build,
                            lanes, swapped)

THREE_ONE = ("atan", "asin", "acos")
FOUR = THREE_ONE + ("atan2",)
NINE = ("exp", "expm1", "exp2", "log", "log1p", "log2", "sin", "cos", "tan")
FMT_NAMES = ("fp32", "fp64", "fp128", "fp256")
RND_NAMES = sf.RND_NAMES
needs_mpmath = pytest.mark.skipif(not have_mpmath(), reason=NO_MPMATH)


# ---- the tables -------------------------------------------------------------

def test_the_tables_name_the_four_as_routines_routines_py_does():
    """cftc.MATH is routines.BUILT (a routine left out of it would be an
    ImportError on a host without mpmath, where the rule is `routine-
    unavailable`); emit.ROUTINE_SOURCE names every routine (a looped call's
    comment is a KeyError otherwise); ir.ROUTINES is the routines; ir.ARITY
    holds atan, asin and acos of arity one and atan2 of arity two directly
    after tan and before neg, the place the language gives them
    (test_routines.py pins the whole of it to lang.OPS); the manifest's
    INVERSE is the four; and the call loop's order is the routines'."""
    assert cftc.MATH == R.BUILT == NINE + FOUR
    assert set(emit.ROUTINE_SOURCE) == set(R.ROUTINES) == \
        {"div", "sqrt", *NINE, *FOUR}
    assert [emit.ROUTINE_SOURCE[op] for op in FOUR] == \
        ["mathlib's atan", "mathlib's asin", "mathlib's acos",
         "mathlib's atan2"]
    assert ir.ROUTINES == frozenset(R.ROUTINES)
    names = list(ir.ARITY)
    at = names.index("tan")
    assert names[at + 1:at + 6] == ["atan", "asin", "acos", "atan2", "neg"]
    assert [ir.ARITY[op] for op in FOUR] == [1, 1, 1, 2]
    assert {op: R.ROUTINES[op] for op in FOUR} == \
        {op: ir.ARITY[op] for op in FOUR}
    assert manifest.INVERSE == FOUR
    assert set(manifest.INVERSE) <= set(cftc.MATH)
    assert not set(manifest.INVERSE) & set(manifest.RADIAN)
    assert list(callloop.ORDER) == list(R.ROUTINES)
    assert [callloop.ORDER[op] for op in FOUR] == [11, 12, 13, 14]


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
assert cftc.MATH == R.BUILT and list(R.ROUTINES)[-4:] == [
    "atan", "asin", "acos", "atan2"]
assert R.INPUTS["atan2"] == ("a", "b") and R.INPUTS["atan"] == ("a",)
assert R.LIVE_CAP["atan2"] == {"fp32": 31, "fp64": 19, "fp128": 19,
                               "fp256": 19}
# division's fragment needs no mpmath; one of the thirteen's is an
# ImportError (the compiler refuses such a source routine-unavailable
# before it)
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
    it - cftc and routines.py import without mpmath, the four's cap rows
    and atan2's two inputs are there, division's fragment is built, and a
    fragment of any of the thirteen is an ImportError (never reached by the
    compiler, which refuses the source `routine-unavailable` first)."""
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
for ops in (("atan",), ("asin",), ("acos",), ("atan2",), ("atan2", "exp"),
            ("atan", "asin", "acos", "atan2"), ("div", "sqrt"), ("fma",)):
    try:
        cftc.refuse_unavailable(graph(*ops), "src.cftl")
        out[",".join(ops)] = None
    except lang.Refusal as e:
        out[",".join(ops)] = [e.name, e.line, e.sentence]
print(json.dumps(out))
"""


def test_a_graph_holding_the_four_is_routine_unavailable_without_mpmath():
    """On a host without mpmath (a child process with it taken away) a step
    graph holding a run-time atan, asin, acos or atan2 is refused `routine-
    unavailable` by refuse_unavailable - by name, no line, the sentence
    naming the functions in MATH's order, mathlib.py and mpmath - and one
    holding division, root and fma alone is not. This is cftc.MATH
    extended to the thirteen: left at the nine it returns nothing for the
    four, and the compile goes on to build a fragment and meets an
    ImportError. (A compile of a source naming them, through the language,
    is lang_check.py's leg G.)"""
    r = subprocess.run([sys.executable, "-B", "-c", _NO_MPMATH_REFUSAL,
                        str(ROOT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for ops in ("atan", "asin", "acos", "atan2", "atan2,exp",
                "atan,asin,acos,atan2"):
        name, line, sentence = got[ops]
        names = ", ".join(op for op in cftc.MATH if op in ops.split(","))
        assert (name, line) == ("routine-unavailable", None), (ops, got[ops])
        assert sentence.startswith(f"this system computes {names} at run "
                                   f"time"), sentence
        assert "mathlib.py" in sentence and "mpmath" in sentence
    assert got["div,sqrt"] is None and got["fma"] is None


# ---- below the language ------------------------------------------------------

def _div_text(fmt, rnd="rne", body=None, states=("x", "y")):
    """A one-div system on two states: x' = x / y, y' = y, or `body`."""
    body = body or {"x": "x / y", "y": "y"}
    nexts = "".join(f"next {s} = {body[s]}\n" for s in states)
    return (f"system t\nformat {fmt}\nround {rnd}\nstate {', '.join(states)}"
            f"\n{nexts}step map\n")


def swapped2(text, fn="atan2"):
    """The step graph's bytes of `text`, a system with one div node, with
    that node's operation swapped for `fn` (atan2, of arity two as div is):
    the node's operands are (y, x) of atan2 in the order of div's (a, b)."""
    b = lang.compile_text(text, "src.cftl").graph.to_bytes()
    assert b.count(b'["div",') == 1
    return b.replace(b'["div",', b'["%s",' % fn.encode("ascii"))


def graph_of(fn, fmt, rnd="rne"):
    """The one-operation system of `fn`: x' = fn(x), or x' = atan2(x, y)."""
    if fn == "atan2":
        return swapped2(_div_text(fmt, rnd))
    return swapped(_exp_text(fmt, rnd), fn)


def inv_lanes(fmt, rnd, seed):
    """The 22 arguments of M2C's pool (lanes()) and six that the inverse
    functions live on: 1, -1, 1/2, -1/3, the last value under 1 and 2 (asin
    and acos have no value past |x| = 1)."""
    def val(q):
        return K.round_once(fmt, rnd, q)[0]
    xs = lanes(fmt, rnd, seed)
    xs += [val(Fraction(1)), val(Fraction(-1)), val(Fraction(1, 2)),
           val(Fraction(-1, 3)), val(1 - Fraction(1, 2 ** 20)),
           val(Fraction(2))]
    return xs


def pairs(fmt, rnd, seed):
    """Lanes of (y, x) for atan2: every special against every special and a
    few finite values (the zeros of either sign, the infinities, a NaN of
    either kind), a pool of rationals of either sign and magnitude, equal
    pairs, opposite pairs and 3 2^-26 against 1."""
    rng = random.Random(seed)

    def val(q):
        return K.round_once(fmt, rnd, q)[0]
    sp = [0, fmt.sign_mask, sf.inf_bits(fmt, 0), sf.inf_bits(fmt, 1),
          sf.qnan_bits(fmt), sf.snan_bits(fmt), 1,
          val(Fraction(1)), val(Fraction(-3, 2))]
    out = [(a, b) for a in sp for b in sp]
    rat = [val(Fraction(rng.randint(-900, 900), rng.randint(1, 397)))
           for _ in range(24)]
    out += [(rat[i], rat[i + 1]) for i in range(0, 24, 2)]
    out += [(r, r) for r in rat[:3]]
    out += [(r, r ^ fmt.sign_mask) for r in rat[3:6]]
    out += [(val(Fraction(3, 2 ** 26)), val(Fraction(1))),
            (val(Fraction(1)), val(Fraction(3, 2 ** 26))),
            (val(Fraction(1, 7)), val(Fraction(10 ** 6) + Fraction(1, 3)))]
    return out


def against_golden(c, fn, fmt, rnd, xs):
    """The image on seq.py, one step, against routines.GOLDEN (transcend's
    function, the definition): every unmarked lane's value and lane byte's
    flags equal to the golden function's, bit for bit; a marked lane (byte
    [7]) a guess, compared only as one, within an encoding of the
    definition's value. `xs` are arguments (one state) or (y, x) pairs
    (atan2: two states, the next x read). -> (the Result, the marked
    lanes)."""
    two = fn == "atan2"
    r = c.run([list(x) if two else [x] for x in xs])
    m = c.ir.m
    marked = []
    for k, x in enumerate(xs):
        byte = r.lane_flags[k]
        out = r.scratch_out[k * m]
        want, flags = (R.GOLDEN[fn](fmt, x[0], x[1], rnd) if two
                       else R.GOLDEN[fn](fmt, x, rnd))
        where = (fn, fmt.name, RND_NAMES[rnd],
                 tuple(map(hex, x)) if two else hex(x))
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


def pool(fn, fmt, rnd):
    return (pairs if fn == "atan2" else inv_lanes)(fmt, rnd, f"{fn}{rnd}")


# the marked lanes of the pools above, by routine, format and attribute
# (a lane's index in the pool), MEASURED at the commit that wrote this test:
# atan(3 2^-26) at fp64 under rne and rmm (lane 19 of inv_lanes: the
# structured family of docs/studies/M4-invtrig.md), and for atan2 lane 61
# of pairs() - (the smallest subnormal, 1.0) - under every attribute at every
# format, and lane 99 - (3 2^-26, 1.0) - at fp64 under rne and rmm. Anything
# not listed marks none.
MARKED = {("atan", "fp64", "rne"): [19], ("atan", "fp64", "rmm"): [19],
          **{("atan2", f, r): [61] for f in FMT_NAMES
             for r in ("rne", "rtz", "rdn", "rup", "rmm")},
          ("atan2", "fp64", "rne"): [61, 99],
          ("atan2", "fp64", "rmm"): [61, 99]}


@needs_mpmath
@pytest.mark.parametrize("fn", FOUR)
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_each_of_the_four_runs_below_the_language_as_its_golden_function(
        fn, fmt_name):
    """At the format under all five attributes: the graph's bytes through
    ir.Graph, lower, best_program, the text, the assembler and the internal
    check; the image on seq.py against transcend's function through
    routines.GOLDEN, lane by lane (see against_golden), the marked lanes
    equal to MARKED's list for the pool. The image holds one routine, and
    needs FLAG_CONTROL."""
    fmt = FORMATS[fmt_name]
    for rnd in sf.RND_MODES:
        c = build(graph_of(fn, fmt_name, RND_NAMES[rnd]))
        assert c.lowered.routines == [fn]
        assert "FLAG_CONTROL" in [asm_feature(f)
                                  for f in c.image_obj.features()]
        r, marked = against_golden(c, fn, fmt, rnd, pool(fn, fmt, rnd))
        assert marked == MARKED.get((fn, fmt_name, RND_NAMES[rnd]), []), \
            (fn, fmt_name, RND_NAMES[rnd], marked)


def asm_feature(f):
    from cftc import targets as T
    return T.ASM_FEATURE.get(f, f)


# ---- atan2's two inputs, in order ------------------------------------------------

def test_atan2_takes_its_inputs_in_mathlibs_order_and_the_node_binds_them():
    """routines.INPUTS names atan2's ("a", "b") = (y, x) and the other
    twelve's ("a",); its golden function takes (fmt, y, x, rnd) as sf.div
    does; and the fragment's inputs are the names the compiler binds to the
    node's operands in order (inline.py, check.py: dict(zip(f.inputs,
    args)))."""
    assert R.INPUTS["atan2"] == ("a", "b")
    assert all(R.INPUTS[op] == ("a",) for op in R.ROUTINES
               if op not in ("div", "atan2"))
    assert R.ROUTINES["atan2"] == len(R.INPUTS["atan2"]) == 2
    f = R.fragment("atan2", FORMATS["fp64"], sf.RND_RNE)
    assert f.inputs == ("a", "b") == ml.fragment(
        "atan2", FORMATS["fp64"], sf.RND_RNE).inputs
    fmt = FORMATS["fp64"]
    one, two = K.round_once(fmt, sf.RND_RNE, Fraction(1))[0], \
        K.round_once(fmt, sf.RND_RNE, Fraction(2))[0]
    assert R.GOLDEN["atan2"](fmt, one, two, sf.RND_RNE) != \
        R.GOLDEN["atan2"](fmt, two, one, sf.RND_RNE)


def _swap_binding(monkeypatch, module):
    """Plant: `module` reads atan2's fragment with its inputs named the
    other way round, so zip(f.inputs, args) binds the node's first operand
    to x and its second to y."""
    good = module.held_fragment

    def planted(op, fmt, rnd):
        f = good(op, fmt, rnd)
        if op != "atan2":
            return f
        g = R.Fragment(f.op, f.fmt, f.rnd, tuple(reversed(f.inputs)),
                       f.body, f.result, f.flags, f.words, f.stage)
        return g
    monkeypatch.setattr(module, "held_fragment", planted)


@needs_mpmath
@pytest.mark.parametrize("fmt_name", ("fp64", "fp256"))
def test_a_binding_that_swaps_atan2s_inputs_is_stopped_by_the_internal_check(
        fmt_name, monkeypatch):
    """The plant: inline.py (the expansion the allocator and the emitter
    take) binds atan2's fragment inputs the wrong way round. build() runs
    the internal check, which binds them itself (check.py), reads the
    assembled words and refuses the image: an InternalError. With the check
    off (the plant's image built without verify) the image runs on seq.py
    RED against the golden function - it computes atan2(x, y) - so the
    check is what stands between the plant and a wrong answer; and the
    image as it should be, with no plant, passes both."""
    fmt = FORMATS[fmt_name]
    b = graph_of("atan2", fmt_name)
    c = build(b)
    xs = pairs(fmt, sf.RND_RNE, "plant")
    against_golden(c, "atan2", fmt, sf.RND_RNE, xs)
    with monkeypatch.context() as mp:
        _swap_binding(mp, inline)
        with pytest.raises(cftc.InternalError):
            build(b)
        # the check off: lower and emit as build() does, without verify
        g = Graph(b)
        low = lower(g, None, source="<bytes>")
        prog = best_program(low)
        text = emit.cfta(low, prog, 1, {"stem": "t", "source": "<bytes>",
                                        "target": "sw",
                                        "source_sha256": "(none: a graph)",
                                        "format_override": None})
        img = emit.assemble(text, "t")
        bad = cftc.Compilation()
        bad.ir, bad.lowered, bad.program = g, low, prog
        bad.image, bad.image_obj = img.to_bytes(), img
        bad.depth = emit.scratch_declared(prog.slots_used)
        bad.cfta, bad.steps, bad.half = text, 1, None
        with pytest.raises(AssertionError):
            against_golden(bad, "atan2", fmt, sf.RND_RNE, xs)
    # a plant in the check's own binding is stopped as well
    with monkeypatch.context() as mp:
        _swap_binding(mp, cftc_check)
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)
    cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_coincident_and_constant_operands_are_the_golden_function(fmt_name):
    """atan2(x, x), atan2(x, -x), atan2(x, c), atan2(c, x) for a bank
    constant c = 3/2, and atan2(x, 0) and atan2(0, x) for the constant zero
    (a node, never a fold of the language's, and never constant-division-
    by-zero: the zero is put into the constant of the 3/2 system's bytes,
    since `div` refuses it), under all five attributes: each image passes
    the internal check - where the two inputs are one value
    routines.simplify and the hash-consing apply - and runs on seq.py equal
    to the golden function lane by lane (a marked lane a guess). The pool is
    inv_lanes(): the specials, the rationals and +-1."""
    fmt = FORMATS[fmt_name]
    neg = fmt.sign_mask
    forms = {                # name: (the div system's step, operands of x)
        "x, x": ("x / x", lambda x, c: (x, x)),
        "x, -x": ("x / -x", lambda x, c: (x, x ^ neg)),
        "x, c": ("x / 1.5", lambda x, c: (x, c)),
        "c, x": ("1.5 / x", lambda x, c: (c, x)),
        "x, 0": ("x / 1.5", lambda x, c: (x, 0)),
        "0, x": ("1.5 / x", lambda x, c: (0, x)),
    }
    for rnd in sf.RND_MODES:
        c15 = K.round_once(fmt, rnd, Fraction(3, 2))[0]
        xs = inv_lanes(fmt, rnd, f"co{rnd}")
        for name, (step, operands) in forms.items():
            text = (f"system t\nformat {fmt_name}\nround "
                    f"{RND_NAMES[rnd]}\nstate x\nnext x = {step}\n"
                    f"step map\n")
            b = lang.compile_text(text, "src.cftl").graph.to_bytes()
            if name in ("x, 0", "0, x"):
                old = b'"0x%0*x"' % (fmt.width // 4, c15)
                assert b.count(old) == 1, (name, b)
                b = b.replace(old, b'"0x%s"' % (b"0" * (fmt.width // 4)))
                b = b.replace(b'"3/2"', b'"0"')
            assert b.count(b'["div",') == 1, (name, b)
            c = build(b.replace(b'["div",', b'["atan2",'))
            assert c.lowered.routines == ["atan2"], name
            r = c.run([[x] for x in xs])
            m = c.ir.m
            for k, x in enumerate(xs):
                y, xx = operands(x, c15)
                want, flags = R.GOLDEN["atan2"](fmt, y, xx, rnd)
                byte = r.lane_flags[k]
                out = r.scratch_out[k * m]
                where = (name, fmt_name, RND_NAMES[rnd], hex(x))
                if byte & seq.LANE_MARKED:
                    assert abs(out - want) <= 1, (where, "guess")
                    continue
                assert out == want, (where, hex(out), hex(want))
                assert byte & seq.LANE_FLAGS_IEEE == flags, (where, "flags")


# ---- MIN and MAX inside a routine, and the internal check holding them ------

MINMAX = {"atan": (1, 0), "asin": (1, 1), "acos": (1, 1), "atan2": (1, 0)}


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
@pytest.mark.parametrize("fn", FOUR)
def test_min_and_max_inside_a_routine_are_accepted_and_held(fn, fmt_name):
    """atan and atan2 hold one MIN and no MAX, asin and acos one of each
    (the clamp of |x| against 1 and the front's swap), each a register and
    a bank word - `min rk kx` or `min rk k` - inside the routine's quiet
    region. The emitter writes them, the assembler takes them and the
    internal check - which reads the assembled words, not the allocator's
    notes - accepts the image as it is and refuses it with a MAX emitted as
    a MIN, or a MIN as a MAX. (The counts are those of the instructions of
    the image: MINNUM and MAXNUM are in none of the four.)"""
    c = build(graph_of(fn, fmt_name))
    dec = _decoded(c)
    mins, maxs = _of(dec, "min"), _of(dec, "max")
    assert (len(mins), len(maxs)) == MINMAX[fn], (fn, fmt_name)
    assert _of(dec, "minnum") == _of(dec, "maxnum") == []
    quiet = set(_inside_quiet(dec))
    assert set(mins + maxs) <= quiet
    for k in mins + maxs:
        d = dec[k]
        assert (d["ka"], d["kb"], d["kc"]) == (False, True, False), (fn, k)
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
@pytest.mark.parametrize("fn", FOUR)
def test_the_internal_check_holds_an_instruction_to_its_attribute_and_the_mark(
        fn):
    """Each of the four at fp64 under rne: an instruction of the routine
    made to round under another attribute, each SELECT that carries the
    mark in the flag word (the word 0x90 is a SELECT arm, no IOR, as in the
    nine: atan2 has two such selects, the others one) re-pointed at the
    unmarked inexact word, and a bank word's bits changed are each refused;
    the image as written passes."""
    c = build(graph_of(fn, "fp64"))
    dec = _decoded(c)
    words = list(c.image_obj.insns)
    quiet = _inside_quiet(dec)
    k = next(k for k in quiet if dec[k]["rnd"] == sf.RND_RDN)
    w = list(words)
    w[k] = (words[k] & ~(0x7 << 24)) | (sf.RND_RNE << 24)
    assert w[k] != words[k]
    _refused(c, w)
    mark, plain = (c.lowered.slot_of[("w", 0x90)],
                   c.lowered.slot_of[("w", 0x10)])
    ks = [k for k in _of(dec, "select") if (mark, True) in asm.sources(dec[k])]
    assert len(ks) == (2 if fn == "atan2" else 1)
    for k in ks:
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
    slot = c.lowered.slots[mark]
    slot.bits ^= 0x80
    try:
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)
    finally:
        slot.bits ^= 0x80
    cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)


@needs_mpmath
@pytest.mark.parametrize("fn", FOUR)
def test_the_internal_check_holds_each_fragment_to_its_format_attribute_and_cap(
        fn, monkeypatch):
    """check.held_fragment, the one door to every fragment the compiler
    reads: a fragment of `fn` made for another attribute, or another
    format, is refused naming it and what it was made for; and the cap row
    is enforced - the fragment at fp64 keeps as many live as its row says,
    and with the row lowered by one it is refused by name, past that
    (the row is one dict: routines.LIVE_CAP's, which mathlib.INV_LIVE_CAP
    views)."""
    fp64, fp32 = FORMATS["fp64"], FORMATS["fp32"]
    cap = R.LIVE_CAP[fn]["fp64"]
    good = R.fragment
    cftc_check._HELD.clear()
    monkeypatch.setattr(R, "fragment", lambda op, f, r: good(
        op, f, sf.RND_RTZ if r == sf.RND_RNE else r))
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment(fn, fp64, sf.RND_RNE)
    assert f"is {fn}'s at fp64 under 1" in str(e.value)
    cftc_check._HELD.clear()
    monkeypatch.setattr(R, "fragment", lambda op, f, r: good(op, fp32, r))
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment(fn, fp64, sf.RND_RNE)
    assert f"is {fn}'s at fp32 under 0" in str(e.value)
    monkeypatch.setattr(R, "fragment", good)
    cftc_check._HELD.clear()
    live = cftc_check.held_fragment(fn, fp64, sf.RND_RNE).live_max()
    assert live == cap
    monkeypatch.setitem(R.LIVE_CAP[fn], "fp64", cap - 1)
    assert ml.INV_LIVE_CAP[fn]["fp64"] == cap - 1
    cftc_check._HELD.clear()
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment(fn, fp64, sf.RND_RNE)
    assert f"{cap} values live at once, past {cap - 1}" in str(e.value)
    monkeypatch.undo()
    cftc_check._HELD.clear()
    assert cftc_check.held_fragment(fn, fp64, sf.RND_RNE).live_max() == cap


# ---- the spills ----------------------------------------------------------------
# A call keeps its fragment's values live and the step's own beside them;
# the allocator has r3 to r31 (regalloc.REGS: 29), so a value beside a call
# is spilled once the fragment's live count and the others come to more than
# 29. M2C measured the rule 30 less the cap for sin, cos and tan
# (test_cftc_trig.py). For the four it predicts 15, 14, 14 and 11 at fp64,
# fp128 and fp256 and 5, 5, 5 and (31 is above 29: none) at fp32. Measured
# here at every k from 0 to 20, by M2C's construction
#
#     next x = f(x) + y0 + ... + y(k-1); next y(i) = y(i) * x
#
# for atan, asin and acos, and for atan2, whose second operand needs a
# state of its own,
#
#     next x = (x / w) + y0 + ... + y(k-1); next w = w * x;
#     next y(i) = y(i) * x
#
# with the division's node swapped for atan2 (x is y, w is x).

def _spill_text(fmt, k, two):
    ys = [f"y{i}" for i in range(k)]
    if two:
        body = {"x": " + ".join(["(x / w)"] + ys), "w": "w * x",
                **{y: f"{y} * x" for y in ys}}
        return _div_text(fmt, "rne", body, ["x", "w"] + ys)
    body = {"x": " + ".join(["exp(x)"] + ys), **{y: f"{y} * x" for y in ys}}
    return _exp_text(fmt, "rne", ["x"] + ys, body)


def spill_slots(fmt_name, k, fn):
    """program.spill_slots of the construction at k other values, for the
    routine `fn` (one of the four, by the swap)."""
    two = fn == "atan2"
    b = lang.compile_text(_spill_text(fmt_name, k, two),
                          "s.cftl").graph.to_bytes()
    src = b'["div",' if two else b'["exp",'
    assert b.count(src) == 1
    b = b.replace(src, b'["%s",' % fn.encode("ascii"))
    return best_program(lower(Graph(b), None, source="<bytes>")).spill_slots


# the measured vectors that are not "no spill below 30 - the cap, then one
# more a value": atan2 at fp32, whose cap, 31, is past the 29 registers, so
# a call spills at k = 0; from k = 15 the allocator's chosen candidate pins
# no component and the count is 2
ATAN2_FP32 = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
              2, 2, 2, 2, 2, 2]


@needs_mpmath
@pytest.mark.parametrize("fn", FOUR)
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_the_first_spill_beside_a_call_comes_at_30_less_the_cap(fn, fmt_name):
    """For each of the four at each format, at every k from 0 to 20: no
    spill at any k under 30 less the cap (15, 14, 14 and 11 at fp64, fp128
    and fp256 for atan, asin, acos and atan2; 5 for atan, asin and acos at
    fp32), then one more spill slot a value; atan2 at fp32, whose cap is
    31, spills at k = 0 (ATAN2_FP32: the whole vector)."""
    cap = R.LIVE_CAP[fn][fmt_name]
    assert len(regalloc.REGS) == 29
    got = [spill_slots(fmt_name, k, fn) for k in range(21)]
    if (fn, fmt_name) == ("atan2", "fp32"):
        assert cap > len(regalloc.REGS)
        assert got == ATAN2_FP32
        return
    first = len(regalloc.REGS) + 1 - cap
    assert got == [0] * first + list(range(1, 21 - first + 1)), \
        (fn, fmt_name, first, got)
    if fmt_name != "fp32":
        assert first == {"atan": 15, "asin": 14, "acos": 14,
                         "atan2": 11}[fn]
    else:
        assert first == 5


@needs_mpmath
def test_atan2_at_fp32_with_a_cap_past_the_registers_compiles_and_is_exact():
    """atan2's fp32 fragment keeps 31 values live, two past the allocator's
    29: the call spills at k = 0 (above) and the image still passes the
    internal check and runs on seq.py as the golden function, under all
    five attributes (checked by build(), then the lanes)."""
    fmt = FORMATS["fp32"]
    for rnd in sf.RND_MODES:
        c = build(graph_of("atan2", "fp32", RND_NAMES[rnd]))
        assert c.program.spill_slots > 0
        against_golden(c, "atan2", fmt, rnd, pairs(fmt, rnd, f"s{rnd}"))


# ---- compiled through the language (needs M4L's nodes: language 1.3) ------------
# From here a source names atan, asin, acos or atan2 and goes through the
# language's checker, cftc.compile_text and lang.run - the definition the
# image is held to.

REV8 = ("u50-rev8", "u50-rev8-quad", "u50-rev8-deep")
# the targets without flag control (CAPS2[14]): revision 7's and the round-2
# and open-core builds
NO_FLAG_CONTROL = ("u50-rev7", "u50-rev7-quad", "u50-round2", "open-core")


def _one(fn, fmt, rnd="rne"):
    """The one-operation source: x' = fn(x), or, for atan2, x' = atan2(x, y)
    with y kept (x is the node's first operand, y of atan2)."""
    if fn == "atan2":
        return (f"system t\nformat {fmt}\nround {rnd}\nstate x, y\n"
                f"next x = atan2(x, y)\nnext y = y\nstep map\n")
    return (f"system t\nformat {fmt}\nround {rnd}\nstate x\n"
            f"next x = {fn}(x)\nstep map\n")


def held_by_lang_run(c, rows, steps):
    """The image on seq.py against lang.run, lane by lane, each lane alone
    through the interpreter (docs/LANGUAGE.md, "A marked lane"): an
    unmarked lane's state and its lane byte's five flags equal the
    interpreter's, bit for bit; a marked lane's value is a guess, compared
    only as one (within an encoding of the definition's) and counted.
    `rows` are the lanes' states. -> (the seq.py Result, the marked lanes)."""
    r = c.run([list(x) for x in rows])
    m = c.ir.m
    marked = []
    for k, row in enumerate(rows):
        byte = r.lane_flags[k]
        ref = lang.run(c.graph, [list(row)], steps)
        out = r.scratch_out[k * m]
        if byte & seq.LANE_MARKED:
            marked.append(k)
            assert abs(out - ref.states[0][0]) <= 1, (k, row, "the guess")
            continue
        assert out == ref.states[0][0], (k, row, hex(out),
                                         hex(ref.states[0][0]))
        assert byte & seq.LANE_FLAGS_IEEE == ref.flags, (k, row, "flags")
        assert not byte & (seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_SCRATCH_RANGE)
    assert bool(r.status & seq.STATUS_MARKED) == bool(marked)
    return r, marked


def rows_of(fn, fmt, rnd, seed):
    """The pools above as lanes of states: one state, or (y, x) pairs."""
    xs = pool(fn, fmt, rnd)
    return xs if fn == "atan2" else [[x] for x in xs]


def test_the_hand_built_bytes_are_the_languages_bytes():
    """Below the language the step graph was the bytes of an exp system with
    the node swapped (swapped(), graph_of()). The language writes the same
    bytes for the system with atan, asin or acos in exp's place, and of
    atan2(x, y) for x / y's with the division swapped - at every format and
    attribute - so the tests above read the graph the compiler is really
    given."""
    for fmt in FMT_NAMES:
        for rnd in RND_NAMES.values():
            for fn in FOUR:
                mine = graph_of(fn, fmt, rnd)
                theirs = lang.compile_text(_one(fn, fmt, rnd),
                                           "src.cftl").graph.to_bytes()
                assert mine == theirs, (fn, fmt, rnd)


@needs_mpmath
@pytest.mark.parametrize("fn", FOUR)
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_each_of_the_four_compiles_and_runs_as_lang_run_at_every_attribute(
        fn, fmt_name):
    """atan(x), asin(x), acos(x) and atan2(x, y) at the format under all
    five attributes, two steps: cftc.compile_text, the image on seq.py
    against lang.run lane by lane under the marked-lane rule
    (held_by_lang_run). The routine is one call, the image says version 8
    and needs FLAG_CONTROL; under rne, the other targets that publish it
    compile the same image and bank (revision 8's three, and sw:4096), and
    the four that do not refuse it `target-feature`, naming the bit and the
    routine. The marked lanes of the first step (MARKED) are marked in the
    two-step run as well."""
    fmt = FORMATS[fmt_name]
    for rnd in sf.RND_MODES:
        text = _one(fn, fmt_name, RND_NAMES[rnd])
        c = cftc.compile_text(text, 2, source="t.cftl")
        assert c.version == cftc.VERSION == 8
        assert c.manifest["compiler"] == {"name": "cftc", "version": 8}
        assert c.manifest["routines"]["calls"] == {fn: 1}
        assert "FLAG_CONTROL" in c.features
        assert c.accepted_by == ["sw", *REV8]
        r, marked = held_by_lang_run(c, rows_of(fn, fmt, rnd, "x"), 2)
        want = MARKED.get((fn, fmt_name, RND_NAMES[rnd]), [])
        assert set(want) <= set(marked), (fn, fmt_name, RND_NAMES[rnd],
                                          marked)
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


# the instructions the routines of one operand cost in one image, MEASURED
# here by compiling `next x = f(y)` (the manifest's instructions_quiet):
# asin(y) + acos(y) share their front (the clamp of |y| against 1, the
# swap, the root of 1 - y^2 and the quotient's phases) and cost 255 at
# fp64 against 221 + 217 = 438 apart (the study's question 1,
# docs/studies/M4-invtrig.md), in either order
INV_SHARING = {   # format: (atan, asin, acos, atan2), asin+acos
    "fp32": ((472, 637, 633, 518), 711),
    "fp64": ((176, 221, 217, 218), 255),
    "fp128": ((186, 235, 231, 228), 269),
    "fp256": ((203, 256, 252, 245), 290),
}


def _quiet(fmt_name, expr):
    text = (f"system s\nformat {fmt_name}\nstate x, y\nnext x = {expr}\n"
            f"next y = y\nstep map\n")
    return cftc.compile_text(text, 1, source="s.cftl").manifest[
        "routines"]["instructions_quiet"]


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_asin_and_acos_of_one_operand_share_their_front(fmt_name):
    """asin(y) and acos(y) in one step, in either order, cost the figures of
    INV_SHARING (the manifest's instructions_quiet) against their sum apart;
    the four alone cost mathlib's fragment lengths. A different operand
    shares nothing."""
    alone, both = INV_SHARING[fmt_name]
    assert tuple(_quiet(fmt_name, e) for e in
                 ("atan(y)", "asin(y)", "acos(y)", "atan2(x, y)")) == alone
    assert alone == tuple(len(R.fragment(op, FORMATS[fmt_name], sf.RND_RNE))
                          for op in FOUR)
    assert _quiet(fmt_name, "asin(y) + acos(y)") == both
    assert _quiet(fmt_name, "acos(y) + asin(y)") == both
    assert both < alone[1] + alone[2]
    assert _quiet(fmt_name, "asin(y) + acos(x)") == alone[1] + alone[2]


# ---- the call loop over atan2's two-slot records ----------------------------------

def _looped(monkeypatch, text, above, steps=2, **kw):
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", above)
    return cftc.compile_text(text, steps, source="loop.cftl", **kw)


def _batches(c):
    return [(b.op, b.depth, len(b.calls)) for b in c.looped]


def _run_loop(c, seed):
    rng = random.Random(seed)
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


@needs_mpmath
def test_a_call_loop_of_the_four_in_the_stated_order(monkeypatch):
    """With the constant lowered to 0, a step with three atan, three asin,
    three acos and six atan2 calls at one depth loops all four batches -
    one copy of each routine in a REPEAT over records: one slot a call for
    the first three and TWO for atan2 (y, then x; the record is the inputs
    in the fragment's order, R.INPUTS) - held by the internal check and run
    on seq.py as lang.run runs it. The order the batches are looped in is
    the callloop's: largest first (calls times the fragment's instructions),
    and batches() lists them by depth, then callloop.ORDER, which is
    routines.ROUTINES, the language's - atan, asin, acos, atan2. The same
    step inlined has no loop."""
    text = ("system loop\nformat fp64\nstate x[3], y[3]\n"
            "next x[i] = atan(x[i]) * 0.5 + asin(y[i]) + atan2(x[i], y[i])\n"
            "next y[i] = acos(y[i]) - atan2(y[i], 1.5)\nstep map\n")
    inl = cftc.compile_text(text, 2, source="loop.cftl")
    assert inl.looped == []
    calls = {"atan": 3, "asin": 3, "acos": 3, "atan2": 6}
    assert inl.manifest["routines"]["calls"] == calls
    c = _looped(monkeypatch, text, 0)
    assert _batches(c) == [("atan2", 1, 6), ("asin", 1, 3), ("acos", 1, 3),
                           ("atan", 1, 3)]
    sizes = {op: len(R.fragment(op, FORMATS["fp64"], sf.RND_RNE))
             for op in FOUR}
    assert sorted(sizes, key=lambda op: -calls[op] * sizes[op]) == \
        [b[0] for b in _batches(c)]
    assert [b.op for b in callloop.batches(c.lowered)] == list(FOUR)
    assert callloop.ORDER == {op: k for k, op in enumerate(R.ROUTINES)}
    loops = {e["op"]: e
             for e in c.manifest["routines"]["call_loops"]["loops"]}
    assert set(loops) == set(FOUR)
    for op, e in loops.items():
        # the record slots are the calls times the inputs of the routine
        assert e["records"][1] - e["records"][0] + 1 == \
            e["calls"] * R.ROUTINES[op], (op, e)
    assert (loops["atan2"]["calls"], loops["atan2"]["fixed"]) == (6, {})
    _run_loop(c, "loop four")


@needs_mpmath
@pytest.mark.parametrize("form,fixed", [
    ("atan2(x[i], 1.5)", {"b": 0}), ("atan2(1.5, x[i])", {"a": 0}),
    ("atan2(x[i], y[i])", {})])
def test_an_atan2_input_every_call_takes_from_one_slot_is_out_of_the_records(
        monkeypatch, form, fixed):
    """A looped batch of three atan2 calls whose one operand is the same
    bank constant in every call keeps that operand out of its records: one
    slot a call, the loop body reading the constant's slot itself (the
    manifest's `fixed`: b for the x operand, a for y); with both operands
    varying the record is two slots a call. Each runs equal to lang.run."""
    text = (f"system loop\nformat fp64\nstate x[3], y[3]\n"
            f"next x[i] = {form}\nnext y[i] = y[i]\nstep map\n")
    c = _looped(monkeypatch, text, 0)
    assert _batches(c) == [("atan2", 1, 3)]
    e = c.manifest["routines"]["call_loops"]["loops"][0]
    assert e["fixed"] == fixed
    assert e["records"][1] - e["records"][0] + 1 == 3 * (2 - len(fixed))
    _run_loop(c, form)


# ---- the manifest's wording ------------------------------------------------------

def _routines_block(text, steps=1):
    return cftc.compile_text(text, steps, source="w.cftl").manifest["routines"]


@needs_mpmath
def test_the_manifest_words_the_four_only_where_a_step_holds_one():
    """The routines block says where the fragments come from and what their
    raises do. A step with the six alone, with sin, cos or tan, or with
    division and root, has the sentences it had; a step with atan, asin,
    acos or atan2 adds a sentence of the four's own and no more, and says
    nothing of "the six" where it holds none of them (`six` leaves the four
    out); with the six or the three too, the sentences come in that order."""
    four = (" likewise set the raised word's bit 7 where their in-lane test "
            "cannot decide the last bit, and mark the lane as the six do")
    six_only = _routines_block("system a\nformat fp64\nstate x\n"
                               "next x = exp(x)\nstep map\n")
    three_only = _routines_block("system a\nformat fp64\nstate x\n"
                                 "next x = sin(x)\nstep map\n")
    for fn in FOUR:
        b = _routines_block(_one(fn, "fp64"))
        assert "the math library's atan, asin, acos and atan2" + four in \
            b["flags"], fn
        assert "the math library's six" not in b["flags"]
        assert "sin, cos and tan" not in b["flags"]
        assert b["source"] == ("cft_golden/routines.py: the math library's "
                               "fragments, cft_golden/mathlib.py's, built at "
                               "the program's format and attribute")
        # the block's head is the C4 sentence; the four's is its tail
        assert b["flags"].startswith(
            "each runs in a quiet region and raises exactly its "
            "operation's flags")
        assert b["flags"].count("; the math library's") == 1
    mixed = _routines_block("system a\nformat fp64\nstate x, y\n"
                            "next x = exp(x) + sin(y) + atan2(x, y)\n"
                            "next y = y\nstep map\n")
    fl = mixed["flags"]
    assert six_only["flags"].split("; the math library's")[1] in fl
    assert three_only["flags"].split("; the math library's")[1] in fl
    assert fl.index("the math library's six") < \
        fl.index("the math library's sin, cos and tan") < \
        fl.index("the math library's atan, asin, acos and atan2")
    quotient = _routines_block("system a\nformat fp64\nstate x, y\n"
                               "next x = x / (y * y + 1) + atan(y)\n"
                               "next y = y\nstep map\n")
    assert quotient["source"].count("; ") == 1 and \
        quotient["source"].startswith("cft_golden/routines.py: divfull's")
    assert "the math library's six" not in quotient["flags"]


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
def test_routine_unavailable_for_the_four_without_mpmath(how):
    """Without mpmath - taken out of sys.modules in a child process
    (`modules`: simulated), and in a child under `python -B -I -S`
    (`isolated`: no site directory, so it is not importable at all, which is
    a host without it) - a source with a run-time atan, asin, acos or atan2
    is refused `routine-unavailable` on every target, revision 7's included
    where with mpmath it is `target-feature`, with no line, its sentence
    naming the functions in MATH's order, mathlib.py and mpmath; at 0 steps
    `segment-steps` first. A fold (atan(0) + asin(0) + acos(1) +
    atan2(0, 1)) and a quotient compile there to the very bytes they compile
    to here."""
    cases = {
        "atan2": ("system a\nformat fp64\nstate x, y\n"
                  "next x = atan2(x, y)\nnext y = y\nstep map\n", "routine"),
        "all four": ("system a\nformat fp32\nstate x, y\n"
                     "next x = atan(x) * y + asin(y)\n"
                     "next y = acos(x) + atan2(y, x)\nstep map\n",
                     "routine"),
        "a fold": ("system a\nformat fp64\nstate x\nconst k = atan(0) + "
                   "asin(0) + acos(1) + atan2(0, 1)\nnext x = x * k + "
                   "atan(0)\nstep map\n", "fold"),
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
                ops = {"atan2": "atan2",
                       "all four": "atan, asin, acos, atan2"}[name]
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
# programs/systems/compiled-tangent/ holds one system that carries atan, asin,
# acos and atan2, at fp64 and fp256 (parcel M4C, decisions 5 and 6 of the
# contract): the phase follower, d/dt c = -(om * s), d/dt s = om * c, d/dt
# phi = k * (atan2(s, c) - phi), d/dt q = asin(q * 0.5) - atan(q) and d/dt v =
# acos(v * 0.5) - v under rk4 with one tangent vector, round rdn. The study's
# section 7: "A rule rounded otherwise must move its bytes", and the
# committed bytes hold the four rules in one system. The known limit
# (contract decision 5): atan2's two one-zero-tangent shapes are in no
# committed reference; the golden checks and test_lang_invtrig.py hold them.

SYSTEMS = ROOT / "programs" / "systems"
PF_NAMES = [f"phasefollower-rk4-tangent-{f}" for f in ("fp64", "fp256")]
# the box of the follower's lanes (tangent_check.MATH_BOX): the oscillator in
# the half plane c > 0, so that atan2's primal (which jumps on the negative
# axis) does not, and q and v inside [-2, 2], asin's and acos's domain
PF_BOX = [(Fraction(1, 2), Fraction(1)), (-Fraction(1, 2), Fraction(1, 2)),
          (Fraction(-1), Fraction(1)), (Fraction(-1), Fraction(1)),
          (Fraction(-1), Fraction(1))]


def _tref(name):
    """A reference's step graph, from its committed source."""
    return lang.load(SYSTEMS / f"{name}.cftl").graph


def test_the_two_sources_are_one_system_at_two_formats():
    """The fp256 source is the fp64 source with the format line changed,
    comments too: nothing else differs; it is round rdn, one tangent vector,
    and holds each of the four in its equations."""
    a = (SYSTEMS / PF_NAMES[0]).with_suffix(".cftl").read_text(
        encoding="ascii").splitlines()
    b = (SYSTEMS / PF_NAMES[1]).with_suffix(".cftl").read_text(
        encoding="ascii").splitlines()
    assert len(a) == len(b)
    assert [(x, y) for x, y in zip(a, b) if x != y] == \
        [("format fp64", "format fp256")]
    code = [ln for ln in a if ln and not ln.startswith(";")]
    assert code.count("tangent w") == 1 and "round  rdn" in code
    eqs = " ".join(ln for ln in code if ln.startswith("d/dt"))
    for fn in FOUR:
        assert f"{fn}(" in eqs, fn


@needs_mpmath
@pytest.mark.parametrize("name", PF_NAMES)
def test_the_committed_references_are_what_the_compiler_writes(name):
    """Eight files each, byte for byte what cftc writes for the committed
    source at 10 steps (tangent_check.py --write made them), the manifest
    saying version 8, the image calling each of the four, and division and
    root (the rules' quotients and roots)."""
    c = cftc.compile_file(SYSTEMS / f"{name}.cftl", 10,
                          source=f"programs/systems/{name}.cftl")
    files = c.files()
    assert len(files) == 8
    for fname, data in files.items():
        assert (SYSTEMS / "compiled-tangent" / fname).read_bytes() == data, \
            fname
    assert c.manifest["compiler"] == {"name": "cftc", "version": 8}
    assert c.accepted_by == ["sw", *REV8]
    assert set(c.manifest["routines"]["calls"]) == {*FOUR, "div", "sqrt"}
    assert "the math library's atan, asin, acos and atan2" in \
        c.manifest["routines"]["flags"]


def test_the_follower_holds_the_four_rules_in_its_tangent():
    """The committed graph carries each rule in its tangent step: atan's,
    asin's and acos's quotients and atan2's, both operands differentiated
    (the numerator an fma of a product and an exact negation), none of them
    a routine node - the tangent step's only routine nodes are the
    divisions and roots the rules write - at fp64 and fp256, and the bytes
    are the graph the checker makes."""
    for name in PF_NAMES:
        g = _tref(name)
        prim = g.op_counts("field")
        tang = g.op_counts("tangent_field")
        step_p, step_t = g.op_counts("step"), g.op_counts("tangent_step")
        for fn, n in (("atan", 1), ("asin", 1), ("acos", 1), ("atan2", 1)):
            assert prim.get(fn) == n, (name, fn, prim)
            assert step_p[fn] == 4 * n and not step_t.get(fn), (name, fn)
        assert not any(tang.get(fn) for fn in FOUR)
        assert tang["div"] == 4 and tang["sqrt"] == 2
        graph = (SYSTEMS / "compiled-tangent" / f"{name}.graph.json"
                 ).read_bytes()
        assert g.to_bytes() == graph


def _pf_rows(fmt, rnd, n, seed):
    """n lanes in PF_BOX, and a tangent vector for each."""
    rng = random.Random(seed)

    def val(lo, hi):
        q = lo + (hi - lo) * Fraction(rng.randint(0, 10 ** 6), 10 ** 6)
        return K.round_once(fmt, rnd, q)[0]
    states = [[val(lo, hi) for lo, hi in PF_BOX] for _ in range(n)]
    tans = [[[K.round_once(fmt, rnd, Fraction(rng.randint(-100, 100), 53))[0]
              for _ in PF_BOX]] for _ in states]
    return states, tans


@needs_mpmath
@pytest.mark.parametrize("name", PF_NAMES)
def test_the_followers_lanes_mark_none_and_are_the_interpreters(name):
    """The follower's lanes - 24 in PF_BOX, with tangents, at 10 steps - mark
    no lane (leg G of tangent_check.py fails a marked segment by name), and
    every lane's states, tangent and flags are lang.run's, bit for bit. The
    count of marked lanes is printed by the assert's message on failure; it
    is 0 of 24 here."""
    fmt_name = name.rsplit("-", 1)[1]
    fmt, rnd = FORMATS[fmt_name], sf.RND_RDN
    c = cftc.compile_file(SYSTEMS / f"{name}.cftl", 10,
                          source=f"programs/systems/{name}.cftl")
    states, tans = _pf_rows(fmt, rnd, 24, "follower " + fmt_name)
    r = c.run(states, tangents=tans)
    m, n, N = c.ir.m, c.ir.n_primal, c.ir.n_state
    marked = [k for k, b in enumerate(r.lane_flags) if b & seq.LANE_MARKED]
    assert marked == [], f"{len(marked)} of {len(states)} lanes marked"
    assert not r.status & seq.STATUS_MARKED
    for k, st in enumerate(states):
        want = lang.run(c.graph, [st], 10, tangents=[tans[k]])
        out = r.scratch_out[k * m:(k + 1) * m]
        assert out[:n] == want.states[0], (name, k, "states")
        assert out[n:N] == [v for vec in want.tangents[0] for v in vec], \
            (name, k, "tangents")
        assert r.lane_flags[k] & seq.LANE_FLAGS_IEEE == want.flags, (name, k)


class _RulePlant(lang_tangent.Derivation):
    """The derivation with one of the four's rules written in another shape
    (kind = (operation, how))."""
    kind = None

    def rule(self, node):
        op, a, line = node.op, node.args, node.line
        if op != self.kind[0]:
            return super().rule(node)
        R = self.read
        how = self.kind[1]

        def N(o, *args):
            return Node(o, args, line)
        if op == "atan2":
            da, db = self.of(a[0]), self.of(a[1])
            if da is None or db is None:
                return super().rule(node)
            sq = N("mul", R(a[0]), R(a[0]))
            if how.startswith("(-a) * db"):
                minus = N("mul", N("neg", R(a[0])), db)
                num = N("fma", R(a[1]), da, minus)
                den = N("fma", R(a[1]), R(a[1]), sq)
            elif how.startswith("b * da - a * db"):
                num = N("sub", N("mul", R(a[1]), da), N("mul", R(a[0]), db))
                den = N("fma", R(a[1]), R(a[1]), sq)
            else:                                   # a * a + b * b
                num = N("fma", R(a[1]), da, N("neg", N("mul", R(a[0]), db)))
                den = N("add", sq, N("mul", R(a[1]), R(a[1])))
            return N("div", num, den)
        da = self.of(a[0])
        if da is None:
            return super().rule(node)
        aa = N("mul", R(a[0]), R(a[0]))
        if how.startswith("da / (1 + a * a)"):
            return N("div", da, N("add", self.one, aa))
        if how.startswith("da / sqrt(1 - a * a)"):
            return N("div", da, N("sqrt", N("sub", self.one, aa)))
        if how.startswith("-(da / sqrt"):
            return N("neg", N("div", da, N("sqrt", N("fma", N("neg", R(a[0])),
                                                     R(a[0]), self.one))))
        return N("div", da, N("neg", N("sqrt", N("sub", self.one, aa))))


RULE_PLANTS = [("atan", "da / (1 + a * a), two roundings"),
               ("asin", "da / sqrt(1 - a * a), two roundings"),
               ("acos", "-(da / sqrt(fma(-a, a, 1))), rounded otherwise"),
               ("acos", "da / -sqrt(1 - a * a), two roundings"),
               ("atan2", "(-a) * db, the negation inside the product"),
               ("atan2", "b * da - a * db, two products and a sub"),
               ("atan2", "a * a + b * b, the denominator's other order")]


@pytest.mark.parametrize("kind", RULE_PLANTS, ids=lambda k: k[1])
def test_each_of_the_four_rules_written_otherwise_moves_the_followers_bytes(
        kind, monkeypatch):
    """Each of the four rules written in another shape - rounded otherwise
    where it rounds twice or more, or the negation inside or outside - moves
    the committed graph of the follower at fp64 and fp256 and of no other
    committed variational reference (checking a source needs no mpmath, so
    neither does this): under any attribute a node shape moves the graph's
    bytes (M2C's finding)."""
    comp = SYSTEMS / "compiled-tangent"
    names = sorted(p.name[:-len(".graph.json")] for p in comp.glob(
        "*.graph.json"))
    assert set(PF_NAMES) <= set(names) and len(names) == 18
    committed = {n: (comp / f"{n}.graph.json").read_bytes() for n in names}

    class P(_RulePlant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check_mod, "Derivation", P)
    moved = sorted(n for n in names if _tref(n).to_bytes() != committed[n])
    assert moved == sorted(PF_NAMES), (kind, moved)


@needs_mpmath
@pytest.mark.parametrize("fmt_name", ("fp64", "fp256"))
@pytest.mark.parametrize("kind", [RULE_PLANTS[2], RULE_PLANTS[4]],
                         ids=lambda k: k[1])
def test_acos_and_atan2s_value_only_variants_in_the_follower(
        kind, fmt_name, monkeypatch):
    """The two value-only variants - acos's `-(da / sqrt(...))` and atan2's
    `(-a) * db` - are other bytes under every attribute, and a value
    question under rdn and rup only (the negation outside or inside a
    rounding is the same value where roundings are symmetric about zero).
    MEASURED here on the follower itself, compiled round rdn and round rne,
    run for 10 steps on 60 lanes of PF_BOX with tangents, the good and the
    planted image against each other: VARIANT_LANES lanes differ in a state
    or tangent (the count is a fact of these lanes: both variants are a
    value under rdn on some of them, 1 and 3 at fp64, 8 and 3 at fp256), and
    none under rne."""
    src = (SYSTEMS / f"phasefollower-rk4-tangent-{fmt_name}.cftl"
           ).read_text(encoding="ascii")

    class P(_RulePlant):
        pass
    P.kind = kind
    fmt = FORMATS[fmt_name]
    got = {}
    for rname in ("rdn", "rne"):
        rnd = {v: k for k, v in RND_NAMES.items()}[rname]
        text = src.replace("round  rdn", f"round  {rname}")
        good = cftc.compile_text(text, 10, source="f.cftl")
        monkeypatch.setattr(lang_check_mod, "Derivation", P)
        planted = cftc.compile_text(text, 10, source="f.cftl")
        monkeypatch.undo()
        assert planted.graph_bytes != good.graph_bytes, rname
        assert planted.image != good.image, rname
        states, tans = _pf_rows(fmt, rnd, 60, "variants")
        rg = good.run(states, tangents=tans)
        rp = planted.run(states, tangents=tans)
        assert not any(b & seq.LANE_MARKED for b in rg.lane_flags +
                       rp.lane_flags)
        m = good.ir.m
        got[rname] = sum(rg.scratch_out[k * m:(k + 1) * m] !=
                         rp.scratch_out[k * m:(k + 1) * m]
                         for k in range(len(states)))
    assert got == VARIANT_LANES[(kind[0], fmt_name)], got


# lanes of 60 that differ, by variant, format and attribute, MEASURED when
# this was written (see the test above)
VARIANT_LANES = {("acos", "fp64"): {"rdn": 1, "rne": 0},
                 ("acos", "fp256"): {"rdn": 8, "rne": 0},
                 ("atan2", "fp64"): {"rdn": 3, "rne": 0},
                 ("atan2", "fp256"): {"rdn": 3, "rne": 0}}
