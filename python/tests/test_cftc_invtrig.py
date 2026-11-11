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
