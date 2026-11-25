# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cftc compiling pow, powr, pown, rootn and compound as routines (parcel M3C,
M3's build, wave 4).

The language gains the five as nodes (parcel M3L, language 1.4) and cftc
carries them as routines, the eighteen of the math library: each run-time node
is inlined as its fragment (cft_golden/mathlib.py's, handed out by
routines.fragment), quiet, then a RAISE of its flag word, whose bit 7 MARKS the
lane where the in-lane test cannot decide the last bit. pow and powr take TWO
inputs, x then y, as atan2 does; pown, rootn and compound take ONE, x, and an
INTEGER n that is a const entry of the graph read for its exact value alone and
that KEYS the fragment: the lowering drops it from the node's operands, so it
is in no bank slot, and keeps it in the node (lower.LNode.n), part of the
hash-consing key, the instance's name (`pown(3)`), the call loop's batch key.

BELOW THE LANGUAGE (this part needs none of M3L's nodes). The step graph's
bytes are the compiler's one input (cftc/ir.py), so the five are tested before
the language has them: the bytes of a `div` system with the operation swapped
for `pow` or `powr` (both of arity two), and of the bytes of `next x = x * 3`
with `mul` swapped for `pown`, `rootn` or `compound` and the const entry's
exact value edited to n (the entry's `bits` stay 3's: cftc never reads them for
n), are graphs the compiler reads exactly as it reads the language's own. From
there the pipeline is the compiler's: ir.Graph, lower, best_program, the text,
the assembler and the internal check (verify), then seq.py against
routines.GOLDEN, which is transcend.py's. This is M2C's and M4C's method
(test_cftc_trig.py's helpers, which this file reuses).

* the tables: cftc.MATH, ir.ROUTINES and ARITY, emit.ROUTINE_SOURCE, the
  manifest's POWER and the call loop's order name the five as routines.py
  does, in the language's order, with no mpmath imported by a program without
  them; NOT_BUILT_FP32 is what mathlib refuses at fp32;
* n travels: pown(x, 3) and pown(x, 5) in one source are two fragments, two
  keys; n = -2^63, 2^63 - 1, 3, 0 and 1 are each the golden function's; a
  const read as n alone is in no bank slot; n is never read from the const's
  encoding;
* pow's and powr's two inputs are bound in order: a binding that swaps them
  is stopped by the internal check, and with the check off is red on seq.py;
  coincident and constant operands are what the golden function says;
* the rewrites of the exponents 2, 1 and -1 (ir.REWRITE), applied at the IR:
  each of the eight equal to the node's golden function, bit for bit and flag
  for flag, at every format where the node compiles, and the three not
  proposed compile as routines;
* the internal check holds an instruction to its attribute, and each
  fragment to its format, attribute and live cap;
* the spills: the first k at which a value is spilled beside a call, measured
  at every k from 0 to 20.
"""

import json
import random
import subprocess
import sys
import types
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cftc                                      # noqa: E402
from cftc import callloop, emit, inline, ir, lower as lowering  # noqa: E402
from cftc import manifest, regalloc              # noqa: E402
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
from test_cftc_trig import build, lanes          # noqa: E402

FIVE = ("pow", "powr", "pown", "rootn", "compound")
N_KEYED = ("pown", "rootn", "compound")
TWO = ("pow", "powr")
FMT_NAMES = ("fp32", "fp64", "fp128", "fp256")
THREE_FMT = ("fp64", "fp128", "fp256")
RND_NAMES = sf.RND_NAMES
needs_mpmath = pytest.mark.skipif(not have_mpmath(), reason=NO_MPMATH)
INT64 = (-2 ** 63, 2 ** 63 - 1)


def formats_of(op):
    """The formats the compiler builds `op` at: compound has no fp32 (its
    first-order budget is over 1 Bv at n = 1000 in the model); pown and rootn
    are built there, the triple word, parcel M3F2's."""
    return THREE_FMT if op == "compound" else FMT_NAMES


# the (op, format) pairs of the tests that ran the five, or the three, at the
# double word's three formats: pown and rootn gain fp32 (parcel M3F2)
FIVE_AT = [(op, f) for op in FIVE
           for f in THREE_FMT + (("fp32",) if op in ("pown", "rootn") else ())]
N_KEYED_AT = [(op, f) for op in N_KEYED for f in formats_of(op)]


# ---- the tables --------------------------------------------------------------

def test_the_tables_name_the_five_as_routines_routines_py_does():
    """cftc.MATH is routines.BUILT (a routine left out of it would be an
    ImportError on a host without mpmath, where the rule is `routine-
    unavailable`); emit.ROUTINE_SOURCE names every routine (a looped call's
    comment is a KeyError otherwise); ir.ROUTINES is the routines; ir.ARITY
    holds the five, of arity TWO each (pown's, rootn's and compound's n is
    the second operand of the language's node), directly after atan2 and
    before neg, the place the language gives them (test_routines.py pins the
    whole of it to lang.OPS); routines.ROUTINES' arity for the three is ONE
    (the integer is a key, not an input); the manifest's POWER is the five
    and none of RADIAN or INVERSE; and the call loop's order is the
    routines'."""
    assert cftc.MATH == R.BUILT
    assert cftc.MATH[-5:] == FIVE
    assert set(emit.ROUTINE_SOURCE) == set(R.ROUTINES)
    assert [emit.ROUTINE_SOURCE[op] for op in FIVE] == \
        [f"mathlib's {op}" for op in FIVE]
    assert ir.ROUTINES == frozenset(R.ROUTINES)
    names = list(ir.ARITY)
    at = names.index("atan2")
    assert names[at + 1:at + 7] == list(FIVE) + ["neg"]
    assert [ir.ARITY[op] for op in FIVE] == [2, 2, 2, 2, 2]
    assert [R.ROUTINES[op] for op in FIVE] == [2, 2, 1, 1, 1]
    assert ir.N_KEYED == R.N_KEYED == N_KEYED
    assert manifest.POWER == FIVE
    assert set(manifest.POWER) <= set(cftc.MATH)
    assert not set(manifest.POWER) & set(manifest.RADIAN + manifest.INVERSE)
    assert list(callloop.ORDER) == list(R.ROUTINES)
    assert [callloop.ORDER[op] for op in FIVE] == [15, 16, 17, 18, 19]
    assert cftc.NOT_BUILT_FP32 == ("compound",)


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
assert cftc.MATH == R.BUILT and list(R.ROUTINES)[-5:] == [
    "pow", "powr", "pown", "rootn", "compound"]
assert R.INPUTS["pow"] == R.INPUTS["powr"] == ("a", "b")
assert R.INPUTS["pown"] == R.INPUTS["rootn"] == R.INPUTS["compound"] == ("a",)
assert R.N_KEYED == ("pown", "rootn", "compound")
assert R.LIVE_CAP["pow"] == {"fp32": 32, "fp64": 30, "fp128": 30,
                             "fp256": 30}
assert R.LIVE_CAP["pown"] == {"fp32": 28, "fp64": 21, "fp128": 21,
                              "fp256": 21}
assert "fp32" not in R.LIVE_CAP["compound"]
R.fragment("div", FORMATS["fp64"], sf.RND_RNE)
assert "mpmath" not in sys.modules
for op in R.BUILT:
    n = 3 if op in R.N_KEYED else None
    try:
        R.fragment(op, FORMATS["fp64"], sf.RND_RNE, n)
    except ImportError:
        continue
    print("NO IMPORTERROR FOR", op)
    sys.exit(1)
# the arguments are refused by name before mathlib is asked
for bad in (("pown", None), ("pow", 3), ("div", 1)):
    try:
        R.fragment(bad[0], FORMATS["fp64"], sf.RND_RNE, bad[1])
    except ValueError:
        continue
    print("NO REFUSAL FOR", bad)
    sys.exit(1)
print("ok")
"""


def test_the_tables_need_no_mpmath():
    """In a child process under `python -B -I -S` - isolated, no site
    directory, so mpmath is not importable at all, which is a host without it
    - cftc and routines.py import without mpmath, the five's cap rows, their
    inputs and the N_KEYED tuple are there, division's fragment is built, a
    fragment of any of the eighteen is an ImportError (never reached by the
    compiler, which refuses the source `routine-unavailable` first), and a
    missing n, or one given to a routine that has none, is refused by name
    before mathlib is asked."""
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
for ops in (("pow",), ("powr",), ("pown",), ("rootn",), ("compound",),
            ("pown", "exp"), ("pow", "powr", "pown", "rootn", "compound"),
            ("div", "sqrt"), ("fma",)):
    try:
        cftc.refuse_unavailable(graph(*ops), "src.cftl")
        out[",".join(ops)] = None
    except lang.Refusal as e:
        out[",".join(ops)] = [e.name, e.line, e.sentence]
print(json.dumps(out))
"""


def test_a_graph_holding_the_five_is_routine_unavailable_without_mpmath():
    """On a host without mpmath (a child process with it taken away) a step
    graph holding a run-time pow, powr, pown, rootn or compound is refused
    `routine-unavailable` by refuse_unavailable - by name, no line, the
    sentence naming the functions in MATH's order, mathlib.py and mpmath - and
    one holding division, root and fma alone is not. This is cftc.MATH
    extended to the eighteen: left at the thirteen it returns nothing for the
    five, and the compile goes on to build a fragment and meets an
    ImportError. (A compile of a source naming them, through the language, is
    lang_check.py's leg G.)"""
    r = subprocess.run([sys.executable, "-B", "-c", _NO_MPMATH_REFUSAL,
                        str(ROOT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)
    for ops in ("pow", "powr", "pown", "rootn", "compound", "pown,exp",
                "pow,powr,pown,rootn,compound"):
        name, line, sentence = got[ops]
        names = ", ".join(op for op in cftc.MATH if op in ops.split(","))
        assert (name, line) == ("routine-unavailable", None), (ops, got[ops])
        assert sentence.startswith(f"this system computes {names} at run "
                                   f"time"), sentence
        assert "mathlib.py" in sentence and "mpmath" in sentence
    assert got["div,sqrt"] is None and got["fma"] is None


# ---- the graphs below the language ---------------------------------------------

def _two_text(fmt, rnd="rne", body=None, states=("x", "y")):
    """A one-div system on two states: x' = x / y, y' = y, or `body`."""
    body = body or {"x": "x / y", "y": "y"}
    nexts = "".join(f"next {s} = {body[s]}\n" for s in states)
    return (f"system t\nformat {fmt}\nround {rnd}\nstate {', '.join(states)}"
            f"\n{nexts}step map\n")


def _swap_two(text, op):
    """The step graph's bytes of `text`, a system with one div node, with the
    node's operation swapped for `op` (pow or powr, of arity two as div is:
    the node's operands are (x, y) of the power in the order of div's
    (a, b))."""
    b = lang.compile_text(text, "src.cftl").graph.to_bytes()
    assert b.count(b'["div",') == 1
    return b.replace(b'["div",', b'["%s",' % op.encode("ascii"))


def two_graph(op, fmt, rnd="rne", body=None, states=("x", "y")):
    return _swap_two(_two_text(fmt, rnd, body, states), op)


def n_graph(op, n, fmt, rnd="rne"):
    """The bytes of `next x = x * 3` with its mul swapped for `op` and the
    const entry's exact value edited to n: the graph of op(x, n) as the
    language writes one (a const operand 2), whose entry's `bits` are 3's -
    cftc reads n from the exact value alone."""
    text = (f"system t\nformat {fmt}\nround {rnd}\nstate x\n"
            f"next x = x * 3\nstep map\n")
    obj = json.loads(lang.compile_text(text, "s.cftl").graph.to_bytes())
    assert [nd[0] for nd in obj["step"]["nodes"]] == ["mul"]
    assert obj["const"][0][0] == "3"
    obj["const"][0][0] = str(n)
    if str(n) == "1":
        # the entry of exact value 1 is a bank constant when a rewrite reads
        # it as the multiplicand 1 (ir.REWRITE), so its encoding is 1's, as
        # the language writes it; any other n keeps 3's, which cftc never reads
        bits, flags = K.round_once(FORMATS[fmt], RND_CODE[rnd], Fraction(1))
        obj["const"][0][2] = K.bits_hex(FORMATS[fmt], bits)
        obj["const"][0][3] = flags
    obj["step"]["nodes"][0][0] = op
    return json.dumps(obj).encode("ascii")


def graph_of(op, fmt, rnd="rne", n=3):
    return n_graph(op, n, fmt, rnd) if op in N_KEYED \
        else two_graph(op, fmt, rnd)


def pow_pairs(fmt, rnd, seed):
    """Lanes of (x, y) for pow and powr: every special against every special
    and a few finite values (the zeros of either sign, the infinities, a NaN
    of either kind, the smallest subnormal), a pool of rationals of either
    sign and magnitude, equal pairs, opposite pairs, integer exponents of
    either sign on negative bases, and exponents past the range."""
    rng = random.Random(seed)

    def val(q):
        return K.round_once(fmt, rnd, Fraction(q))[0]
    sp = [0, fmt.sign_mask, sf.inf_bits(fmt, 0), sf.inf_bits(fmt, 1),
          sf.qnan_bits(fmt), sf.snan_bits(fmt), 1,
          val(1), val(Fraction(-3, 2)), val(2), val(-2), val(Fraction(1, 2))]
    out = [(a, b) for a in sp for b in sp]
    rat = [val(Fraction(rng.randint(-900, 900), rng.randint(1, 397)))
           for _ in range(24)]
    out += [(rat[i], rat[i + 1]) for i in range(0, 24, 2)]
    out += [(r, r) for r in rat[:3]]
    out += [(r, r ^ fmt.sign_mask) for r in rat[3:6]]
    out += [(val(-2), val(3)), (val(-2), val(-3)), (val(10), val(-5)),
            (val(3), val(2)), (val(Fraction(1, 2)), val(1100)),
            (val(2), val(1100)), (val(2), val(-1100)), (val(7), val(0)),
            (val(Fraction(9, 4)), val(Fraction(1, 2)))]
    return out


def n_lanes(fmt, rnd, seed):
    """The 22 arguments of M2C's pool (lanes()) and the ones the integer
    powers live on: -2, 2, 1/2, -1/3, 8, -8, 27, 10^6 + 1/3."""
    def val(q):
        return K.round_once(fmt, rnd, Fraction(q))[0]
    xs = lanes(fmt, rnd, seed)
    xs += [val(-2), val(2), val(Fraction(1, 2)), val(Fraction(-1, 3)),
           val(8), val(-8), val(27), val(-27)]
    return xs


def pool(op, fmt, rnd):
    return (pow_pairs if op in TWO else n_lanes)(fmt, rnd, f"{op}{rnd}")


def against_golden(c, op, fmt, rnd, xs, n=None):
    """The image on seq.py, one step, against routines.GOLDEN (transcend's
    function, the definition): every unmarked lane's value and lane byte's
    flags equal to the golden function's, bit for bit; a marked lane (byte
    [7]) a guess, compared only as one, within an encoding of the
    definition's value, and counted. `xs` are (x, y) pairs for pow and powr
    (two states, the next x read) and arguments for the three, whose n is
    the keyword. -> (the Result, the marked lanes)."""
    two = op in TWO
    r = c.run([list(x) if two else [x] for x in xs])
    m = c.ir.m
    marked = []
    for k, x in enumerate(xs):
        byte = r.lane_flags[k]
        out = r.scratch_out[k * m]
        want, flags = (R.GOLDEN[op](fmt, x[0], x[1], rnd) if two
                       else R.GOLDEN[op](fmt, x, rnd, n))
        where = (op, n, fmt.name, RND_NAMES[rnd],
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


# n of the rewrites (ir.REWRITE) is no routine: the instances that remain
ROUTINE_N = {"pown": (3, 5, -3, 0, 1 - 2, 2 ** 63 - 1, -2 ** 63),
             "rootn": (3, 5, -3, 2, 2 ** 63 - 1, -2 ** 63),
             "compound": (3, 5, -3, 0, 1, 2 ** 63 - 1, -2 ** 63)}


# ---- n travels below the language ------------------------------------------------

@needs_mpmath
@pytest.mark.parametrize("op,fmt_name", FIVE_AT)
def test_each_of_the_five_runs_below_the_language_as_its_golden_function(
        op, fmt_name):
    """At the format under all five attributes: the graph's bytes through
    ir.Graph, lower, best_program, the text, the assembler and the internal
    check; the image on seq.py against transcend's function through
    routines.GOLDEN, lane by lane (see against_golden), for pow and powr and,
    for the three, n = 3 (a routine; 2, 1 and -1 are rewritten). The image
    needs revision 8's flag control."""
    fmt = FORMATS[fmt_name]
    for rnd in sf.RND_MODES:
        c = build(graph_of(op, fmt_name, RND_NAMES[rnd]))
        assert c.lowered.routines == [R.instance(op, 3 if op in N_KEYED
                                                 else None)]
        against_golden(c, op, fmt, rnd, pool(op, fmt, rnd),
                       3 if op in N_KEYED else None)


def _obj(text):
    return json.loads(lang.compile_text(text, "s.cftl").graph.to_bytes())


def _bytes(obj):
    return json.dumps(obj).encode("ascii")


def _set_const(obj, i, exact, fmt, rnd, with_bits):
    """Const entry i's exact value, as text; with its `bits` and `flags` the
    value rounded once as the language writes them when `with_bits` (an
    exponent read as a value), else left as they were (an n, which cftc
    never reads the encoding of)."""
    obj["const"][i][0] = str(exact)
    if with_bits:
        bits, flags = K.round_once(FORMATS[fmt], rnd, K.parse_frac(str(exact)))
        obj["const"][i][2] = K.bits_hex(FORMATS[fmt], bits)
        obj["const"][i][3] = flags


RND_CODE = {name: code for code, name in RND_NAMES.items()}


def exp_graph(op, exact, fmt, rnd="rne"):
    """`next x = x * 3` with its mul swapped for `op` and the const entry
    made `exact` with its encoding right: op(x, exact) with a CONSTANT second
    operand read as a value (pow's and powr's exponent) or as n (the
    three's)."""
    text = (f"system t\nformat {fmt}\nround {rnd}\nstate x\n"
            f"next x = x * 3\nstep map\n")
    obj = _obj(text)
    _set_const(obj, 0, exact, fmt, RND_CODE[rnd], op in TWO)
    obj["step"]["nodes"][0][0] = op
    return _bytes(obj)


def lane_values(fmt, rnd, extra=()):
    return n_lanes(fmt, rnd, f"v{rnd}") + list(extra)


# ---- n travels --------------------------------------------------------------------

N_RUN = (-2 ** 63, 2 ** 63 - 1, 3, 5, -3, 0, 1)


def _instance_of(op, n):
    """What the lowering holds for op(x, n): the routine instance, or none
    where ir.REWRITE writes a mul or a div in its place."""
    return [] if (op, n) in ir.REWRITE else [R.instance(op, n)]


@needs_mpmath
@pytest.mark.parametrize("op,fmt_name", N_KEYED_AT)
def test_n_travels_to_the_fragment_and_equals_the_golden_function(op, fmt_name):
    """For n = -2^63, 2^63 - 1, 3, 5, -3, 0 and 1 (rootn: not 0, which the
    language refuses): the graph whose second operand is the const entry
    holding n EXACTLY (its encoding stays 3's: at fp64, 2^63 - 1 does not
    even round to itself) compiles, passes the internal check and runs on
    seq.py equal to GOLDEN[op](fmt, x, rnd, n) lane by lane under all five
    attributes, a marked lane compared only as a guess. n = 1 and rootn's
    +-1 and pown's -1 are the rewrites (a mul or a div, no routine), every
    other n the instance `op(n)`."""
    fmt = FORMATS[fmt_name]
    for n in N_RUN:
        if op == "rootn" and n == 0:
            continue
        for rnd in sf.RND_MODES:
            c = build(n_graph(op, n, fmt_name, RND_NAMES[rnd]))
            assert c.lowered.routines == _instance_of(op, n), (op, n)
            against_golden(c, op, fmt, rnd, pool(op, fmt, rnd), n)


@needs_mpmath
def test_two_n_in_one_source_are_two_instances_one_n_twice_is_one():
    """pown(x, 3) and pown(y, 5) in one source are two instances, `pown(3)`
    and `pown(5)`, two fragments - the bank holds the union of their words,
    fewer than the sum, since a new n adds a word or two - and each result
    is its own n's golden function; pown(x, 3) twice (one expression, two
    nodes of the graph) is ONE instance and one node, merged by sharing; and
    the same n on two operands is one instance of two nodes."""
    fmt_name = "fp64"
    fmt = FORMATS[fmt_name]
    obj = _obj("system t\nformat fp64\nround rne\nstate x, y\n"
               "next x = x * 3\nnext y = y * 5\nstep map\n")
    assert [nd[0] for nd in obj["step"]["nodes"]] == ["mul", "mul"]
    assert [e[0] for e in obj["const"]] == ["3", "5"]
    for nd in obj["step"]["nodes"]:
        nd[0] = "pown"
    c = build(_bytes(obj))
    low = c.lowered
    assert low.routines == ["pown(3)", "pown(5)"]
    fa = R.fragment("pown", fmt, sf.RND_RNE, 3)
    fb = R.fragment("pown", fmt, sf.RND_RNE, 5)
    union = set(fa.words.values()) | set(fb.words.values())
    assert sum(1 for s in low.slots if s.kind == "word") == len(union)
    assert len(union) < len(set(fa.words.values())) + len(
        set(fb.words.values()))
    labels = {nm for s in low.slots if s.kind == "word" for nm in s.names}
    assert {op for op, _w in labels} == {"pown(3)", "pown(5)"}
    xs = [(0x4000000000000000, 0x3ff8000000000000),
          (0x3ff0000000000000, 0xc000000000000000)]
    r = c.run([list(x) for x in xs])
    m = c.ir.m
    for k, (x, y) in enumerate(xs):
        assert r.scratch_out[k * m] == R.GOLDEN["pown"](
            fmt, x, sf.RND_RNE, 3)[0]
        assert r.scratch_out[k * m + 1] == R.GOLDEN["pown"](
            fmt, y, sf.RND_RNE, 5)[0]
    # one n twice: one instance
    obj2 = _obj("system t\nformat fp64\nround rne\nstate x, y\n"
                "next x = x * 3\nnext y = y * 3\nstep map\n")
    for nd in obj2["step"]["nodes"]:
        nd[0] = "pown"
    low2 = lower(Graph(_bytes(obj2)), None, source="<bytes>")
    assert low2.routines == ["pown(3)"] and len(low2.nodes) == 2
    assert {nd.n for nd in low2.nodes} == {3}
    # the same node twice is merged into one
    obj3 = _obj("system t\nformat fp64\nround rne\nstate x\n"
                "next x = x * 3 + x * 3\nstep map\n")
    nodes = obj3["step"]["nodes"]
    assert [nd[0] for nd in nodes] == ["mul", "mul", "add"]
    for nd in nodes[:2]:
        nd[0] = "pown"
    low3 = lower(Graph(_bytes(obj3)), None, source="<bytes>")
    assert low3.shared == 1 and sum(nd.op == "pown" for nd in low3.nodes) == 1


@needs_mpmath
def test_rootn_of_order_zero_is_an_internal_error_naming_the_node():
    """The language refuses rootn(x, 0) (irrational-constant), so a graph
    with one is not the language's: the lowering raises an InternalError
    naming the node, never a ValueError from the math library."""
    with pytest.raises(cftc.InternalError, match=r"step node 0.*rootn"):
        lower(Graph(n_graph("rootn", 0, "fp64")), None, source="<bytes>")


def test_an_integer_operand_that_is_no_int64_constant_is_an_internal_error():
    """n is read by Graph.integer from the exact value of a const entry,
    int64 only: a fraction, 2^63 and -2^63 - 1, a state or a node are each
    an InternalError naming the node (the language refuses them all before
    the compiler sees one)."""
    for exact in ("1/2", "9223372036854775808", "-9223372036854775809"):
        with pytest.raises(cftc.InternalError, match="step node 0"):
            lower(Graph(n_graph("pown", exact, "fp64")), None,
                  source="<bytes>")
    obj = _obj("system t\nformat fp64\nround rne\nstate x, y\n"
               "next x = x * 3\nnext y = y\nstep map\n")
    obj["step"]["nodes"][0] = ["pown", ["s0", "s1"], None]
    with pytest.raises(cftc.InternalError, match="not a constant"):
        lower(Graph(_bytes(obj)), None, source="<bytes>")


@needs_mpmath
def test_n_is_read_from_the_exact_value_never_from_the_encoding():
    """The const entry's `bits` are 3's in every graph above; at fp64 2^63 - 1
    rounds to 2^63 and at fp32 to 2^31 (24 bits). Here the entry says
    n = 7 exactly and its encoding says 5: the instance is pown(7), and the
    image is pown(7)'s golden function, not pown(5)'s."""
    fmt = FORMATS["fp64"]
    obj = _obj("system t\nformat fp64\nround rne\nstate x\n"
               "next x = x * 5\nstep map\n")
    obj["const"][0][0] = "7"            # exact 7, encoding 5's
    obj["step"]["nodes"][0][0] = "pown"
    c = build(_bytes(obj))
    assert c.lowered.routines == ["pown(7)"]
    x = 0x4000000000000000
    r = c.run([[x]])
    assert r.scratch_out[0] == R.GOLDEN["pown"](fmt, x, sf.RND_RNE, 7)[0]
    assert r.scratch_out[0] != R.GOLDEN["pown"](fmt, x, sf.RND_RNE, 5)[0]


@needs_mpmath
def test_a_const_read_as_n_alone_takes_no_bank_slot_and_counts_nowhere():
    """`next x = x * 3` made pown(x, 3): the const entry 3 is read as n only,
    so the bank holds the routine's words and nothing else (no `const` slot);
    with the same entry also read as a mul's operand (`next y = y * 3`) it
    keeps its slot. bank-capacity counts the slot too: a source of 384 params
    and pown(x, 3), whose words are 128 at fp64, is 512 slots and compiles;
    its const also read by a mul is 513 and is refused bank-capacity."""
    only = lower(Graph(n_graph("pown", 3, "fp64")), None, source="<bytes>")
    assert [s.kind for s in only.slots] == ["word"] * len(only.slots)
    assert ("c", 0) not in only.slot_of and len(only.slots) == 128
    obj = _obj("system t\nformat fp64\nround rne\nstate x, y\n"
               "next x = x * 3\nnext y = y * 3\nstep map\n")
    obj["step"]["nodes"][0][0] = "pown"
    both = lower(Graph(_bytes(obj)), None, source="<bytes>")
    assert ("c", 0) in both.slot_of and len(both.slots) == 129
    assert [s.kind for s in both.slots].count("const") == 1
    # bank-capacity at the boundary: 384 params + 128 words = 512
    params = 384
    ps = "".join(f"param p{i} = {i + 1}\n" for i in range(params))
    sums = " + ".join(f"p{i}" for i in range(params))
    text = (f"system t\nformat fp64\nround rne\nstate x\n{ps}"
            f"next x = x * 3 + {sums}\nstep map\n")
    obj = _obj(text)
    muls = [nd for nd in obj["step"]["nodes"] if nd[0] == "mul"]
    assert len(muls) == 1
    muls[0][0] = "pown"
    ok = lower(Graph(_bytes(obj)), None, source="<bytes>")
    assert len(ok.slots) == 512 and len(ok.graph.param) == params
    text2 = (f"system t\nformat fp64\nround rne\nstate x, y\n{ps}"
             f"next x = x * 3 + {sums}\nnext y = y * 3\nstep map\n")
    obj2 = _obj(text2)
    muls = [nd for nd in obj2["step"]["nodes"] if nd[0] == "mul"]
    assert len(muls) == 2
    muls[0][0] = "pown"
    with pytest.raises(cftc.lang.Refusal) as e:
        lower(Graph(_bytes(obj2)), None, source="<bytes>")
    assert e.value.name == "bank-capacity" and "513" in e.value.sentence


# ---- pow's and powr's two inputs, in order ---------------------------------------------

def test_pow_and_powr_take_their_inputs_in_mathlibs_order_and_the_node_binds_them():
    """routines.INPUTS names pow's and powr's ("a", "b") = (x, y); the
    golden function takes (fmt, x, y, rnd) as atan2's does; and the
    fragment's inputs are the names the compiler binds to the node's
    operands in order (inline.py, check.py: dict(zip(f.inputs, args)))."""
    fmt = FORMATS["fp64"]
    one, two = (K.round_once(fmt, sf.RND_RNE, Fraction(q))[0] for q in (1, 2))
    for op in TWO:
        assert R.INPUTS[op] == ("a", "b") and R.ROUTINES[op] == 2
        f = R.fragment(op, fmt, sf.RND_RNE)
        assert f.inputs == ("a", "b") == ml.fragment(op, fmt,
                                                     sf.RND_RNE).inputs
        assert R.GOLDEN[op](fmt, two, one, sf.RND_RNE) != \
            R.GOLDEN[op](fmt, one, two, sf.RND_RNE)


def _swap_binding(monkeypatch, module):
    """Plant: `module` reads pow's and powr's fragment with its inputs named
    the other way round, so zip(f.inputs, args) binds the node's first
    operand to y and its second to x."""
    good = module.held_fragment

    def planted(op, fmt, rnd, n=None):
        f = good(*cftc_check.fragment_args(op, fmt, rnd, n))
        if op not in TWO:
            return f
        return R.Fragment(f.op, f.fmt, f.rnd, tuple(reversed(f.inputs)),
                          f.body, f.result, f.flags, f.words, f.stage)
    monkeypatch.setattr(module, "held_fragment", planted)


@needs_mpmath
@pytest.mark.parametrize("op", TWO)
@pytest.mark.parametrize("fmt_name", ("fp64", "fp256"))
def test_a_binding_that_swaps_the_inputs_is_stopped_by_the_internal_check(
        op, fmt_name, monkeypatch):
    """The plant: inline.py (the expansion the allocator and the emitter
    take) binds the fragment's inputs the wrong way round. build() runs the
    internal check, which binds them itself (check.py), reads the assembled
    words and refuses the image: an InternalError. With the check off (the
    plant's image built without verify) the image runs on seq.py RED against
    the golden function - it computes op(y, x) - so the check is what stands
    between the plant and a wrong answer; the image as it should be, with no
    plant, passes both; and a plant in the check's own binding is stopped as
    well."""
    fmt = FORMATS[fmt_name]
    b = graph_of(op, fmt_name)
    c = build(b)
    xs = pow_pairs(fmt, sf.RND_RNE, "plant")
    against_golden(c, op, fmt, sf.RND_RNE, xs)
    with monkeypatch.context() as mp:
        _swap_binding(mp, inline)
        with pytest.raises(cftc.InternalError):
            build(b)
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
            against_golden(bad, op, fmt, sf.RND_RNE, xs)
    with monkeypatch.context() as mp:
        _swap_binding(mp, cftc_check)
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)
    cftc_check.verify(c.lowered, c.program, c.image, c.steps, c.half)


def _constant_text(fmt, body, rnd="rne"):
    return (f"system t\nformat {fmt}\nround {rnd}\nstate x\n"
            f"next x = {body}\nstep map\n")


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
@pytest.mark.parametrize("op", TWO)
def test_coincident_and_constant_operands_are_the_golden_function(
        op, fmt_name):
    """pow(x, x), pow(x, -x), pow(x, c) and pow(c, x) for a bank constant c
    (0.5 and 3.5: not 2, 1 or -1, which are rewritten) - the same for powr -
    each the golden function lane by lane (the second operand the same
    state, its negation, or a constant from one bank slot), under all five
    attributes; a coincident pair also binds both inputs to one value, which
    the fragment's simplifier sees."""
    fmt = FORMATS[fmt_name]
    shapes = {"x ^ x": "x / x", "x ^ -x": "x / (-x)", "x ^ 0.5": "x / 0.5",
              "x ^ 3.5": "x / 3.5", "0.5 ^ x": "0.5 / x",
              "3.5 ^ x": "3.5 / x"}
    for label, body in shapes.items():
        for rnd in sf.RND_MODES:
            obj = _obj(_constant_text(fmt_name, body, RND_NAMES[rnd]))
            nodes = [nd for nd in obj["step"]["nodes"] if nd[0] == "div"]
            assert len(nodes) == 1
            nodes[0][0] = op
            c = build(_bytes(obj))
            assert c.lowered.routines == [op]
            xs = n_lanes(fmt, rnd, f"co{rnd}")
            r = c.run([[x] for x in xs])
            m = c.ir.m
            for k, x in enumerate(xs):
                a, b = {"x ^ x": (x, x), "x ^ -x": (x, x ^ fmt.sign_mask),
                        "x ^ 0.5": (x, K.round_once(fmt, rnd,
                                                    Fraction(1, 2))[0]),
                        "x ^ 3.5": (x, K.round_once(fmt, rnd,
                                                    Fraction(7, 2))[0]),
                        "0.5 ^ x": (K.round_once(fmt, rnd,
                                                 Fraction(1, 2))[0], x),
                        "3.5 ^ x": (K.round_once(fmt, rnd,
                                                 Fraction(7, 2))[0], x)}[label]
                want, flags = R.GOLDEN[op](fmt, a, b, rnd)
                byte = r.lane_flags[k]
                where = (op, label, fmt_name, RND_NAMES[rnd], hex(x))
                if byte & seq.LANE_MARKED:
                    assert abs(r.scratch_out[k * m] - want) <= 1, where
                    continue
                assert r.scratch_out[k * m] == want, where
                assert byte & seq.LANE_FLAGS_IEEE == flags, where


# ---- fp32: pow and powr, and the refusal of the three ------------------------------------

@needs_mpmath
@pytest.mark.parametrize("op", TWO)
def test_pow_and_powr_at_fp32_compile_inline_and_are_exact(op):
    """pow's fp32 fragment keeps 32 values live and powr's 29, against the
    allocator's 29 registers (regalloc.REGS: r3 to r31): M4C's first-spill
    rule, 30 less the cap, is -2 for pow and +1 for powr. Both compile, pass
    the internal check and run on seq.py as the golden function under all
    five attributes; the call spills at k = 0 beside pow (3 slots, where
    the cap is 32) and from k = 1 beside powr (the vectors below)."""
    fmt = FORMATS["fp32"]
    assert R.LIVE_CAP[op]["fp32"] == {"pow": 32, "powr": 29}[op]
    for rnd in sf.RND_MODES:
        c = build(graph_of(op, "fp32", RND_NAMES[rnd]))
        assert (c.program.spill_slots > 0) == (op == "pow")
        against_golden(c, op, fmt, rnd, pow_pairs(fmt, rnd, f"{op}{rnd}"))


def _stand_in(b, fmt_name):
    """A language-graph stand-in for refuse_unavailable: the graph's bytes,
    its format and its step section's nodes, read from the bytes alone."""
    obj = json.loads(b)
    sec = types.SimpleNamespace(nodes=[tuple(nd) for nd in obj["step"]["nodes"]])
    return types.SimpleNamespace(
        fmt=FORMATS[fmt_name], to_bytes=lambda: b,
        section=lambda name: sec if name == "step" else None)


def test_compound_at_fp32_is_refused_by_name_and_a_rewritten_n_is_not():
    """compound has no fp32 (pown and rootn are built there, parcel M3F2's):
    refuse_unavailable refuses `routine-unavailable` (no line) naming the
    instance (compound(1000)) and "compound is not built at fp32", FIRST
    - the sentence is the same with mpmath taken away - and a node the
    rewrites take (pown(x, 2), 1 and -1, rootn(x, 1) and -1) is a mul or a
    div by then and is not refused; at any other format nothing is
    refused. pow and powr are never refused at fp32."""
    refused = {("compound", 1000): "compound(1000)",
               ("compound", 1): "compound(1)", ("compound", 3): "compound(3)",
               ("compound", -2 ** 63): "compound(-9223372036854775808)"}
    for (op, n), name in refused.items():
        b = n_graph(op, n, "fp32")
        with pytest.raises(lang.Refusal) as e:
            cftc.refuse_unavailable(_stand_in(b, "fp32"), "src.cftl")
        assert (e.value.name, e.value.line) == ("routine-unavailable", None)
        assert name in e.value.sentence
        assert "compound is not built at fp32" in e.value.sentence
        assert "parcel M3F2's" not in e.value.sentence
        if have_mpmath():
            cftc.refuse_unavailable(_stand_in(b, "fp64"), "src.cftl")
    # pown and rootn are built at fp32: refused nothing, whatever n
    for op, n in (("pown", 3), ("rootn", -2), ("pown", 0), ("rootn", 2),
                  ("pown", -2 ** 63), ("rootn", 2 ** 63 - 1)):
        b = n_graph(op, n, "fp32")
        assert cftc.unbuilt_at_fp32(_stand_in(b, "fp32")) == []
        cftc.refuse_unavailable(_stand_in(b, "fp32"), "src.cftl")
    for op, n in (("pown", 2), ("pown", 1), ("pown", -1), ("rootn", 1),
                  ("rootn", -1)):
        b = n_graph(op, n, "fp32")
        assert (op, n) in ir.REWRITE
        assert cftc.unbuilt_at_fp32(_stand_in(b, "fp32")) == []
        cftc.refuse_unavailable(_stand_in(b, "fp32"), "src.cftl")
    for op in TWO:
        cftc.refuse_unavailable(_stand_in(graph_of(op, "fp32"), "fp32"),
                                "src.cftl")
    assert cftc.unbuilt_at_fp32(_stand_in(n_graph("pown", 3, "fp64"),
                                          "fp64")) == []
    # two instances, sorted: the routines' order, then n signed
    obj = _obj("system t\nformat fp32\nround rne\nstate x, y\n"
               "next x = x * 3\nnext y = y * -2\nstep map\n")
    obj["step"]["nodes"][0][0] = "compound"
    obj["step"]["nodes"][1][0] = "compound"
    b = _bytes(obj)
    assert cftc.unbuilt_at_fp32(_stand_in(b, "fp32")) == \
        [("compound", -2), ("compound", 3)]


_NO_MPMATH_FP32 = r"""
import json, sys, types
sys.modules["mpmath"] = None
sys.path.insert(0, sys.argv[1] + "/python")
import cftc
from cft_golden import FORMATS, lang
b = sys.stdin.buffer.read()
obj = json.loads(b)
sec = types.SimpleNamespace(nodes=[tuple(nd) for nd in obj["step"]["nodes"]])
g = types.SimpleNamespace(fmt=FORMATS["fp32"], to_bytes=lambda: b,
                          section=lambda name: sec if name == "step" else None)
try:
    cftc.refuse_unavailable(g, "src.cftl")
    print("null")
except lang.Refusal as e:
    print(json.dumps([e.name, e.line, e.sentence]))
"""


def test_the_fp32_refusal_comes_before_the_mpmath_test():
    """On a host without mpmath a compound(x, 3) at fp32 is refused by the
    fp32 sentence, not the mpmath one: the refusal needs no import."""
    b = n_graph("compound", 3, "fp32")
    r = subprocess.run([sys.executable, "-B", "-c", _NO_MPMATH_FP32,
                        str(ROOT)], input=b, capture_output=True)
    assert r.returncode == 0, r.stderr
    name, line, sentence = json.loads(r.stdout)
    assert (name, line) == ("routine-unavailable", None)
    assert "compound is not built at fp32" in sentence \
        and "mpmath" not in sentence


@needs_mpmath
def test_not_built_fp32_is_exactly_what_mathlib_refuses_at_fp32():
    """cftc.NOT_BUILT_FP32 lists the routines of N_KEYED that mathlib does
    not build at fp32 (compound): this test fails by name when mathlib builds
    one of them and the table still lists it - and when the table stops
    listing one mathlib still refuses - so that the parcel that builds
    compound cannot leave it. pow, powr, pown and rootn are built there and
    are not in it."""
    fp32 = FORMATS["fp32"]
    built = {}
    for op in N_KEYED:
        try:
            ml.fragment(op, fp32, sf.RND_RNE, n=3)
            built[op] = True
        except ValueError as e:
            assert f"{op} at fp32 is not built:" in str(e)
            built[op] = False
    stale = [op for op in cftc.NOT_BUILT_FP32 if built[op]]
    assert not stale, (f"mathlib builds {stale} at fp32 and "
                       f"cftc.NOT_BUILT_FP32 still refuses them: delete them "
                       f"from the table and this test's fp32 clause")
    missing = [op for op in N_KEYED if not built[op]
               and op not in cftc.NOT_BUILT_FP32]
    assert not missing, f"mathlib refuses {missing} at fp32 and cftc " \
                        f"does not say so"
    assert not set(TWO) & set(cftc.NOT_BUILT_FP32)
    assert set(cftc.NOT_BUILT_FP32) <= set(cftc.MATH)


# ---- the rewrites of the exponents 2, 1 and -1 (ir.REWRITE) -----------------------------

EIGHT = (("pow", 2), ("pown", 2), ("pow", 1), ("pown", 1), ("rootn", 1),
         ("pow", -1), ("pown", -1), ("rootn", -1))
NOT_PROPOSED = (("rootn", 2, "sqrt"), ("compound", 1, "1 + x"),
                ("pow", "1/2", "sqrt"))


def rewrite_graph(op, n, fmt_name, rnd="rne"):
    """The graph of op(x, n) with n a constant operand: pow's exponent is a
    VALUE (its encoding is right), the three's n an integer."""
    if op in TWO:
        return exp_graph(op, n, fmt_name, rnd)
    return n_graph(op, n, fmt_name, rnd)


def against_fn(c, fmt, rnd, xs, want, label):
    """The image on seq.py, one step, against want(x) -> (bits, flags): the
    marked-lane rule of against_golden. -> the marked lanes."""
    r = c.run([[x] for x in xs])
    m = c.ir.m
    marked = []
    for k, x in enumerate(xs):
        byte = r.lane_flags[k]
        out = r.scratch_out[k * m]
        bits, flags = want(x)
        where = (label, fmt.name, RND_NAMES[rnd], hex(x))
        if byte & seq.LANE_MARKED:
            marked.append(k)
            assert abs(out - bits) <= 1, (where, "the guess")
            continue
        assert out == bits, (where, hex(out), hex(bits))
        assert byte & seq.LANE_FLAGS_IEEE == flags, (where, "flags")
    return marked


def golden_of(op, n, fmt, rnd):
    """The definition of op(x, n): transcend's function through
    routines.GOLDEN, the exponent of pow its encoding."""
    if op in TWO:
        e = K.round_once(fmt, rnd, K.parse_frac(str(n)))[0]
        return lambda x: R.GOLDEN[op](fmt, x, e, rnd)
    return lambda x: R.GOLDEN[op](fmt, x, rnd, n)


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
@pytest.mark.parametrize("op,n", EIGHT, ids=lambda v: str(v))
def test_each_of_the_eight_rewrites_is_the_nodes_golden_function(
        op, n, fmt_name):
    """pow(x, 2) and pown(x, 2) as x * x; pow(x, 1), pown(x, 1) and
    rootn(x, 1) as x * 1; pow(x, -1), pown(x, -1) and rootn(x, -1) as
    1 / x: ir.Graph writes the one operation in the node's place before
    anything lowers it, so the image holds a mul or a div and no routine of
    the five (the manifest's lowering.rewritten says so), and it is the
    GOLDEN function of the node - transcend's, the unrewritten node's
    definition - lane by lane, bits and flags, under all five attributes at
    EVERY format where the function compiles: fp32 too, for the three
    (pown 2, 1 and -1, rootn 1 and -1), where their routines are refused.
    The pool is n_lanes (28 values: the specials, the pools of M2C and
    -2, 2, 1/2, -1/3, 8, -8, 27, -27)."""
    fmt = FORMATS[fmt_name]
    written = "div" if n == -1 else "mul"
    assert ir.REWRITE[(op, n)][0] == written
    for rnd in sf.RND_MODES:
        c = build(rewrite_graph(op, n, fmt_name, RND_NAMES[rnd]))
        assert c.ir.rewritten == [(0, op, n, written)]
        assert [nd.op for nd in c.lowered.nodes] == [written]
        assert c.lowered.routines == (["div"] if n == -1 else [])
        against_fn(c, fmt, rnd, n_lanes(fmt, rnd, f"rw{n}{rnd}"),
                   golden_of(op, n, fmt, rnd), f"{op}({n})")


@needs_mpmath
@pytest.mark.parametrize("op,n,twin,fmt_name", [
    (op, n, twin, f) for op, n, twin in NOT_PROPOSED
    for f in formats_of(op)], ids=lambda v: str(v))
def test_the_three_not_proposed_compile_as_routines(op, n, twin, fmt_name):
    """rootn(x, 2) (sqrt), compound(x, 1) (1 + x) and pow(x, 1/2) (sqrt) are
    NOT rewritten: each compiles as its routine, equal to the golden
    function lane by lane, and the twin the study considered differs from
    it on named lanes - rootn(-0, 2) is +0 where sqrt(-0) is -0, compound
    at x < -1 and at x = -1 under rdn is not 1 + x, pow(-0, 1/2) is +0 and
    pow(-inf, 1/2) is +inf where sqrt(-0) is -0 and sqrt(-inf) is invalid
    - measured here as the lanes of the pool where the two disagree."""
    fmt = FORMATS[fmt_name]
    twins_differ = 0
    for rnd in sf.RND_MODES:
        c = build(rewrite_graph(op, n, fmt_name, RND_NAMES[rnd]))
        assert c.ir.rewritten == []
        inst = n if op != "pow" else None
        assert c.lowered.routines == [R.instance(op, inst)]
        xs = n_lanes(fmt, rnd, f"np{rnd}") + [
            K.round_once(fmt, rnd, Fraction(-1))[0],
            K.round_once(fmt, rnd, Fraction(-3, 2))[0]]
        want = golden_of(op, n, fmt, rnd)
        against_fn(c, fmt, rnd, xs, want, f"{op}({n})")
        one = K.round_once(fmt, rnd, Fraction(1))[0]
        for x in xs:
            other = {"sqrt": lambda: sf.sqrt(fmt, x, rnd),
                     "1 + x": lambda: sf.add(fmt, one, x, rnd)}[twin]()
            twins_differ += other != want(x)
    assert twins_differ > 0, (op, n, fmt_name)


def test_a_rewrite_of_the_wrong_exponent_is_not_made():
    """Only an exponent of EXACT value 2, 1 or -1 is rewritten: pow(x, 3),
    pown(x, 3), pown(x, 0), rootn(x, 2), rootn(x, 3), compound(x, 1),
    compound(x, 2), powr(x, 2) and pow(x, 1/2), pow(x, 3/2) - and a pow
    whose exponent is a run-time value, even one that is 2 at run time - are
    left as the routines they are; an exponent that depends on h (an
    h-scaled const) is none either."""
    for op, n in (("pow", 3), ("pown", 3), ("pown", 0), ("rootn", 2),
                  ("rootn", 3), ("compound", 1), ("compound", 2),
                  ("powr", 2), ("pow", "1/2"), ("pow", "3/2"),
                  ("pow", "2/3"), ("pown", -2), ("rootn", -3)):
        g = Graph(rewrite_graph(op, n, "fp64"))
        assert g.rewritten == [] and g.nodes[0][0] == op, (op, n)
    g = Graph(two_graph("pow", "fp64", body={"x": "x / y", "y": "y"}))
    assert g.rewritten == [] and g.nodes[0][0] == "pow"


def test_the_rewrite_reads_the_graphs_own_one_or_appends_one():
    """`a * 1` and `1 / a` read a const entry of exact value 1: the graph's
    own where it has one (pown(x, 1) reads its own n's entry, as the
    language's graph has one entry per value), else one appended to
    Graph.const with the encoding of 1 at the format - a bank constant like
    any, counted by bank-capacity. graph_counts, the manifest's graph_by_op,
    stays the graph's: it counts the pown."""
    g = Graph(n_graph("pown", 1, "fp64"))
    assert len(g.const) == 1 and g.nodes == [("mul", (("s", 0), ("c", 0)),
                                              None)]
    low = lower(g, None, source="<bytes>")
    assert [s.kind for s in low.slots] == ["const"]
    assert low.slots[0].exact == 1 and low.slots[0].bits == 0x3ff0000000000000
    g = Graph(n_graph("pown", -1, "fp64"))
    assert len(g.const) == 2 and g.const[1][0] == 1 and g.const[1][1] is None
    assert g.const[1][2] == 0x3ff0000000000000
    assert g.nodes == [("div", (("c", 1), ("s", 0)), None)]
    low = lower(g, None, source="<bytes>")
    assert low.routines == ["div"]
    assert [s.kind for s in low.slots].count("const") == 1
    assert g.graph_counts() == {"pown": 1} and g.op_counts() == {"div": 1}
    g = Graph(n_graph("pown", 2, "fp64"))
    assert len(g.const) == 1 and g.nodes[0][1] == (("s", 0), ("s", 0))
    low = lower(g, None, source="<bytes>")
    assert low.slots == [] and low.routines == []


# ---- the spills ------------------------------------------------------------------------
# A call keeps its fragment's values live and the step's own beside them; the
# allocator has r3 to r31 (regalloc.REGS: 29), so a value beside a call is
# spilled once the fragment's live count and the others come to more than 29:
# M2C's rule, 30 less the cap in other values live, measured here at every k
# from 0 to 20 by M2C's construction
#
#     next x = f(x) + y0 + ... + y(k-1); next y(i) = y(i) * x
#
# for the three of one input (f(x) is `x * 3` with its mul swapped for the
# routine, n = 3 or the n named) and, for pow and powr, whose second operand
# needs a state of its own,
#
#     next x = (x / w) + y0 + ... + y(k-1); next w = w * x;
#     next y(i) = y(i) * x
#
# with the division's node swapped for the routine (x is x, w is y of the
# power).

def _spill_text(fmt, k, two):
    ys = [f"y{i}" for i in range(k)]
    if two:
        body = {"x": " + ".join(["(x / w)"] + ys), "w": "w * x",
                **{y: f"{y} * x" for y in ys}}
        states = ["x", "w"] + ys
    else:
        body = {"x": " + ".join(["(x * 3)"] + ys),
                **{y: f"{y} * x" for y in ys}}
        states = ["x"] + ys
    nexts = "".join(f"next {s} = {body[s]}\n" for s in states)
    return (f"system t\nformat {fmt}\nround rne\nstate {', '.join(states)}"
            f"\n{nexts}step map\n")


def spill_slots(fmt_name, k, op, n=None):
    """program.spill_slots of the construction at k other values, for `op`
    (and n) swapped in for the one node that holds it."""
    two = op in TWO
    obj = _obj(_spill_text(fmt_name, k, two))
    hits = 0
    for nd in obj["step"]["nodes"]:
        if two and nd[0] == "div":
            nd[0] = op
            hits += 1
        elif not two and nd[0] == "mul" and nd[1][1].startswith("c"):
            nd[0] = op
            obj["const"][int(nd[1][1][1:])][0] = str(n)
            hits += 1
    assert hits == 1
    low = lower(Graph(_bytes(obj)), None, source="<bytes>")
    return best_program(low).spill_slots


# MEASURED at f7a1ce95 plus this parcel (python -B, rne), the whole vector
# of k = 0 to 20 for each routine at each format it is built at. From k = 15
# the allocator's chosen candidate pins no component and the count falls to
# what the call alone costs (pow 1 or 3, powr 0), as atan2's does at fp32.
SPILL = {
    ("pow", "fp32", None): [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
                            17, 3, 3, 3, 3, 3, 3],
    ("pow", "fp64", None): [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                            15, 1, 1, 1, 1, 1, 1],
    ("pow", "fp128", None): [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                             15, 1, 1, 1, 1, 1, 1],
    ("pow", "fp256", None): [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
                             15, 1, 1, 1, 1, 1, 1],
    ("powr", "fp32", None): [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13,
                             14, 0, 0, 0, 0, 0, 0],
    ("powr", "fp64", None): [0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
                             10, 11, 12, 13, 14],
    ("powr", "fp128", None): [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8,
                              9, 10, 11, 12, 13],
    ("powr", "fp256", None): [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8,
                              9, 10, 11, 12, 13],
    ("pown", "fp64", 3): [0] * 9 + list(range(1, 13)),
    ("pown", "fp128", 3): [0] * 10 + list(range(1, 12)),
    ("pown", "fp256", 3): [0] * 10 + list(range(1, 12)),
    ("pown", "fp64", -2 ** 63): [0] * 9 + list(range(1, 13)),
    ("pown", "fp128", -2 ** 63): [0] * 9 + list(range(1, 13)),
    ("pown", "fp256", -2 ** 63): [0] * 9 + list(range(1, 13)),
    ("rootn", "fp64", 3): [0] * 11 + list(range(1, 11)),
    ("rootn", "fp128", 3): [0] * 11 + list(range(1, 11)),
    ("rootn", "fp256", 3): [0] * 11 + list(range(1, 11)),
    ("compound", "fp64", 3): [0] * 8 + list(range(1, 14)),
    ("compound", "fp128", 3): [0] * 8 + list(range(1, 14)),
    ("compound", "fp256", 3): [0] * 8 + list(range(1, 14)),
}


# 30 less the fragment's live count under rne: the first k at which the
# value count spilled is not zero (negative: the call spills at k = 0 with
# live - 29 slots)
FIRST = {("pow", "fp32", None): -2, ("pow", "fp64", None): 0,
         ("pow", "fp128", None): 0, ("pow", "fp256", None): 0,
         ("powr", "fp32", None): 1, ("powr", "fp64", None): 7,
         ("powr", "fp128", None): 8, ("powr", "fp256", None): 8,
         ("pown", "fp64", 3): 9, ("pown", "fp128", 3): 10,
         ("pown", "fp256", 3): 10, ("pown", "fp64", -2 ** 63): 9,
         ("pown", "fp128", -2 ** 63): 9, ("pown", "fp256", -2 ** 63): 9,
         ("rootn", "fp64", 3): 11, ("rootn", "fp128", 3): 11,
         ("rootn", "fp256", 3): 11, ("compound", "fp64", 3): 8,
         ("compound", "fp128", 3): 8, ("compound", "fp256", 3): 8}


@needs_mpmath
@pytest.mark.parametrize("op,fmt_name,n", sorted(SPILL, key=repr),
                         ids=lambda v: str(v))
def test_the_first_spill_beside_a_call_comes_at_30_less_the_live_count(
        op, fmt_name, n):
    """For each of the five at each format it is built at, at every k from 0
    to 20 (the whole vector pinned): no spill at any k under 30 less the
    fragment's live count, then one more spill slot a value - 0, 7, 8 and 8
    for pow and powr's rows (the caps 30 and 23, 22, 22: pow at fp64 to fp256
    spills from k = 0, one slot), 9, 11 and 8 for pown, rootn and compound at
    the n whose fragment keeps the cap's worth live (pown at -2^63, 21 at
    each format; pown at 3 keeps 20 at fp128 and fp256 and spills one k
    later, at 10), -2 and +1 at fp32: pow's 32 live, past the 29 registers by
    3, spills at k = 0 with 3 slots and powr's 29 from k = 1. (The rule is
    M2C's, measured for sin, cos and tan and M4C's for the four; the
    construction is theirs.) The count is the fragment's own under rne: the
    cap is the most any attribute keeps, and pown(3)'s fragment may keep
    fewer."""
    assert len(regalloc.REGS) == 29
    got = [spill_slots(fmt_name, k, op, n) for k in range(21)]
    assert got == SPILL[(op, fmt_name, n)], (op, fmt_name, n, got)
    live = R.fragment(op, FORMATS[fmt_name], sf.RND_RNE, n).live_max()
    first = len(regalloc.REGS) + 1 - live
    if first > 0:
        assert got[:first] == [0] * first and got[first] == 1, \
            (op, fmt_name, n, first, got)
    else:
        assert got[0] == live - len(regalloc.REGS), (op, fmt_name, n, got)
    cap = R.LIVE_CAP[op][fmt_name]
    assert live <= cap
    assert (live == cap) == ((op, fmt_name, n) != ("pown", fmt_name, 3)
                             or fmt_name == "fp64")
    assert first == FIRST[(op, fmt_name, n)]


# ---- the internal check holds the five ------------------------------------------------------

def _decoded(c):
    return [asm.decode(w) for w in c.image_obj.insns]


def _inside_quiet(dec):
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


def _refused(c, words):
    img = asm.Image.from_bytes(c.image)
    bad = asm.Image(img.fmt, words, img.consts, img.max_deposits, img.flags,
                    scratch_depth=img.scratch_depth,
                    scratch_io=img.scratch_io).to_bytes()
    with pytest.raises(cftc.InternalError):
        cftc_check.verify(c.lowered, c.program, bad, c.steps, c.half)


@needs_mpmath
@pytest.mark.parametrize("op", FIVE)
def test_no_fragment_of_the_five_holds_a_min_or_a_max(op):
    """sin's and cos's clamp is two MIN and two MAX against bank words, and
    asin's, acos's, atan's and atan2's one or two: none of the five holds a
    MIN, a MAX, a MINNUM or a MAXNUM (MEASURED at fp32 where built, fp64 and
    fp256 under rne, n = 3), so there is no MAX to emit as a MIN."""
    for fmt_name in formats_of(op):
        c = build(graph_of(op, fmt_name))
        dec = _decoded(c)
        for name in ("min", "max", "minnum", "maxnum"):
            assert _of(dec, name) == [], (op, fmt_name, name)


@needs_mpmath
@pytest.mark.parametrize("fmt_name", ("fp64", "fp256"))
@pytest.mark.parametrize("op", FIVE)
def test_the_internal_check_holds_an_instruction_to_its_attribute_and_the_mark(
        op, fmt_name):
    """Each of the five at fp64 and fp256 under rne (n = 3): the one SELECT
    that reads the mark word (FL_MARK, 0x80) re-pointed at the ZERO word,
    an instruction of the routine made to round under another attribute and
    a bank word's bits changed are each refused by the internal check, which
    reads the assembled words and the golden model's fragment; the image as
    written passes. (The mark of the six, sin, cos and tan and the four is a
    SELECT arm too; here the word is FL_MARK, which pow's, powr's and the
    three's flag word selects.)"""
    c = build(graph_of(op, fmt_name))
    low = c.lowered
    dec = _decoded(c)
    words = list(c.image_obj.insns)
    quiet = _inside_quiet(dec)
    rounded = [k for k in quiet if dec[k]["rnd"] != sf.RND_RNE
               and asm.OP_NAMES.get(dec[k]["op"]) in ("fma", "add", "sub",
                                                      "mul")]
    for k in rounded[:3]:
        w = list(words)
        w[k] = (words[k] & ~(0x7 << 24)) | (sf.RND_RNE << 24)
        assert w[k] != words[k]
        _refused(c, w)
    # one rounded instruction of each routine made to round under RUP
    k = next(k for k in quiet
             if asm.OP_NAMES.get(dec[k]["op"]) in ("fma", "add", "sub", "mul"))
    w = list(words)
    w[k] = (words[k] & ~(0x7 << 24)) | (sf.RND_RUP << 24)
    if w[k] != words[k]:
        _refused(c, w)
    mark, zero = low.slot_of[("w", 0x80)], low.slot_of[("w", 0)]
    ks = [k for k in _of(dec, "select") if (mark, True) in asm.sources(dec[k])]
    assert len(ks) == 1
    for k in ks:
        d = dec[k]
        srcs = [(zero if (i, isk) == (mark, True) else i, isk)
                for i, isk in asm.sources(d)]
        fields = ("ra", "rb", "rc")
        kw = {f: v for f, (v, _k) in zip(fields, srcs)}
        flags = {"k" + f[1]: isk for f, (_v, isk) in zip(fields, srcs)}
        w = list(words)
        w[k] = asm.alu(d["op"], d["rd"], rnd=d["rnd"], **kw, **flags)
        assert w[k] != words[k]
        _refused(c, w)
    slot = low.slots[mark]
    slot.bits ^= 0x100
    try:
        with pytest.raises(cftc.InternalError):
            cftc_check.verify(low, c.program, c.image, c.steps, c.half)
    finally:
        slot.bits ^= 0x100
    cftc_check.verify(low, c.program, c.image, c.steps, c.half)


@needs_mpmath
@pytest.mark.parametrize("op", FIVE)
def test_the_internal_check_holds_each_fragment_to_its_format_attribute_and_cap(
        op, monkeypatch):
    """check.held_fragment, the one door to every fragment the compiler
    reads: a fragment of `op` (n = 3 for the three) made for another
    attribute, or another format, is refused naming it and what it was made
    for - for pown, rootn and compound, which also asks for the n; and the
    cap row is enforced - the fragment at fp64 keeps as many live as its row
    says, and with the row lowered by one it is refused by name, past that
    (the row is one dict: routines.LIVE_CAP's, which mathlib.POW_LIVE_CAP
    views)."""
    fp64, fp128 = FORMATS["fp64"], FORMATS["fp128"]
    n = 3 if op in N_KEYED else None
    cap = R.LIVE_CAP[op]["fp64"]
    good = R.fragment
    cftc_check._HELD.clear()
    monkeypatch.setattr(R, "fragment", lambda op, f, r, n=None: good(
        *cftc_check.fragment_args(op, f, sf.RND_RTZ if r == sf.RND_RNE else r,
                                  n)))
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment(*cftc_check.fragment_args(
            op, fp64, sf.RND_RNE, n))
    assert f"is {op}'s at fp64 under 1" in str(e.value)
    cftc_check._HELD.clear()
    monkeypatch.setattr(R, "fragment", lambda op, f, r, n=None: good(
        *cftc_check.fragment_args(op, fp128, r, n)))
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment(*cftc_check.fragment_args(
            op, fp64, sf.RND_RNE, n))
    assert f"is {op}'s at fp128 under 0" in str(e.value)
    monkeypatch.setattr(R, "fragment", good)
    cftc_check._HELD.clear()
    live = cftc_check.held_fragment(*cftc_check.fragment_args(
        op, fp64, sf.RND_RNE, n)).live_max()
    assert live == cap
    monkeypatch.setitem(R.LIVE_CAP[op], "fp64", cap - 1)
    assert ml.POW_LIVE_CAP[op]["fp64"] == cap - 1
    cftc_check._HELD.clear()
    with pytest.raises(cftc.InternalError) as e:
        cftc_check.held_fragment(*cftc_check.fragment_args(
            op, fp64, sf.RND_RNE, n))
    assert f"{cap} values live at once, past {cap - 1}" in str(e.value)
    monkeypatch.undo()
    cftc_check._HELD.clear()
    assert cftc_check.held_fragment(*cftc_check.fragment_args(
        op, fp64, sf.RND_RNE, n)).live_max() == cap


@needs_mpmath
def test_the_checks_fragment_door_is_keyed_by_n_and_refuses_a_bad_n():
    """check._HELD is keyed (op, format, attribute, n): pown(x, 3) and
    pown(x, 5) are two entries and two fragments, each the one routines.py
    makes for that n (a Fragment holds no n, so a key without it would hand
    one's fragment to the other); a bool or a float n is an InternalError
    naming it, before any key is made; and rootn of order 0, which the
    language never gives, is an InternalError, not a ValueError."""
    fmt = FORMATS["fp64"]
    cftc_check._HELD.clear()
    f3 = cftc_check.held_fragment("pown", fmt, sf.RND_RNE, 3)
    f5 = cftc_check.held_fragment("pown", fmt, sf.RND_RNE, 5)
    assert f3 is R.fragment("pown", fmt, sf.RND_RNE, 3)
    assert f5 is R.fragment("pown", fmt, sf.RND_RNE, 5)
    assert f3 is not f5
    assert {k for k in cftc_check._HELD if k[0] == "pown"} == {
        ("pown", "fp64", sf.RND_RNE, 3), ("pown", "fp64", sf.RND_RNE, 5)}
    cftc_check.held_fragment("pown", fmt, sf.RND_RNE, 1)
    for bad in (True, 1.0, "3"):
        with pytest.raises(cftc.InternalError, match="not an int"):
            cftc_check.held_fragment("pown", fmt, sf.RND_RNE, bad)
    with pytest.raises(cftc.InternalError, match="rootn"):
        cftc_check.held_fragment("rootn", fmt, sf.RND_RNE, 0)
    with pytest.raises(cftc.InternalError, match="needs its integer"):
        cftc_check.held_fragment("pown", fmt, sf.RND_RNE)


# ---- the call loop's room -------------------------------------------------------------------

ROOM = len(regalloc.REGS)


def _plans(op):
    """[(format, attribute, fixed, n, registers)] for every plan of `op`:
    each format it is built at, each attribute, each `fixed` (none, or each
    of its inputs from one bank slot: a division's 1, a constant), each n of
    N_PLANS for the three."""
    rows = []
    for fn in formats_of(op):
        for rnd in sf.RND_MODES:
            fixeds = [()] + ([(i,) for i in R.INPUTS[op]]
                              if len(R.INPUTS[op]) == 2 else [])
            for fx in fixeds:
                for n in (N_PLANS if op in N_KEYED else (None,)):
                    rows.append((fn, rnd, fx, n, callloop.plan(
                        op, FORMATS[fn], rnd, fx, n)[1]))
    return rows


N_PLANS = (3, -2, -2 ** 63)


@needs_mpmath
def test_the_room_table_of_the_five_pow_is_past_it_at_every_format_and_powr_at_fp32():
    """A looped batch's body needs plan()'s registers, all held at once in
    the allocator's 29 (callloop.room, M4LF). Of the five, MEASURED at every
    plan - each format a routine is built at, the five attributes, a call
    with its inputs in records and with each from one bank slot, and the
    three at n = 3, -2 and -2^63 - only pow and powr at fp32 and pow at the
    other three formats are past it: pow needs 33 (no input fixed) or 32
    (one fixed) at fp32 under every attribute, and 31 or 30 at fp64, fp128
    and fp256 under the two attributes that keep 30 live (rne and rmm); powr
    needs 30 at fp32 with nothing fixed and 29, the room exactly, with an
    input fixed. pown, rootn and compound are within it at every n: at the
    double word's three formats their most is 23 registers, and pown and
    rootn at fp32 (parcel M3F2's, the triple word) need 28 or 29 and 27 or 28
    (MEASURED here by cftc's own allocator, over the five attributes and the
    three n; 29 is the room exactly, so a pown call at fp32 fits with no
    value beside it to spare)."""
    assert ROOM == 29
    got = {op: _plans(op) for op in FIVE}
    assert len(got["pow"]) == len(got["powr"]) == 4 * 5 * 3
    assert all(len(got[op]) == len(formats_of(op)) * 5 * len(N_PLANS)
               for op in N_KEYED)
    past = {op: [r for r in rows if r[4] > ROOM] for op, rows in got.items()}
    assert past["pown"] == past["rootn"] == past["compound"] == []
    assert max(r[4] for op in N_KEYED for r in got[op]
               if r[0] != "fp32") == 23
    assert {r[4] for r in got["pown"] if r[0] == "fp32"} == {28, 29}
    assert {r[4] for r in got["rootn"] if r[0] == "fp32"} == {27, 28}
    assert not [r for r in got["compound"] if r[0] == "fp32"]
    assert len(past["pow"]) == 33 and len(past["powr"]) == 5
    assert {(r[0], r[2], r[4]) for r in past["powr"]} == {("fp32", (), 30)}
    assert {(r[0], r[2], r[4]) for r in past["pow"]
            if r[0] == "fp32"} == {("fp32", (), 33), ("fp32", ("a",), 32),
                                   ("fp32", ("b",), 32)}
    other = {(r[0], r[1], r[2], r[4]) for r in past["pow"] if r[0] != "fp32"}
    assert {(fn, fx, k) for fn, _r, fx, k in other} == {
        (fn, fx, k) for fn in THREE_FMT
        for fx, k in (((), 31), (("a",), 30), (("b",), 30))}
    assert {r[1] for r in past["pow"] if r[0] != "fp32"} == \
        {sf.RND_RNE, sf.RND_RMM}
    assert max(r[4] for r in got["powr"] if r[0] != "fp32") <= 24


# ---- compiled through the language (needs M3L's nodes: language 1.4) -----------------------
# From here a source names pow, powr, pown, rootn or compound and goes through
# the language's checker, cftc.compile_text and lang.run - the definition the
# image is held to.

from test_cftc_invtrig import NO_FLAG_CONTROL, REV8       # noqa: E402


def held_by_lang_run(c, rows, steps):
    """The image on seq.py against lang.run, lane by lane, each lane alone
    through the interpreter (docs/LANGUAGE.md, "A marked lane"): an unmarked
    lane's state and its lane byte's five flags equal the interpreter's, bit
    for bit; a marked lane's value is the routine's best guess, which the
    definition replays: it is COUNTED and named in the returned list, never
    required to be within any distance of the definition's value (this
    file's own comparison; test_cftc_invtrig.py's holds a marked guess to
    one encoding, which is more than the rule says, and a program that adds
    two marked guesses can be two away). -> (the seq.py Result, the marked
    lanes' indices)."""
    r = c.run([list(x) for x in rows])
    m = c.ir.m
    marked = []
    for k, row in enumerate(rows):
        byte = r.lane_flags[k]
        if byte & seq.LANE_MARKED:
            marked.append(k)
            continue
        ref = lang.run(c.graph, [list(row)], steps)
        out = r.scratch_out[k * m]
        assert out == ref.states[0][0], (k, row, hex(out),
                                         hex(ref.states[0][0]))
        assert byte & seq.LANE_FLAGS_IEEE == ref.flags, (k, row, "flags")
        assert not byte & (seq.LANE_DEPOSIT_OVERFLOW | seq.LANE_SCRATCH_RANGE)
    assert bool(r.status & seq.STATUS_MARKED) == bool(marked)
    return r, marked


def source(op, fmt, rnd="rne", n=3, body=None):
    """The one-operation source: x' = op(x, y) with y kept (pow, powr), or
    x' = op(x, n) (the three), or `body` over the same states."""
    if op in TWO:
        return (f"system t\nformat {fmt}\nround {rnd}\nstate x, y\n"
                f"next x = {body or f'{op}(x, y)'}\nnext y = y\nstep map\n")
    return (f"system t\nformat {fmt}\nround {rnd}\nstate x\n"
            f"next x = {body or f'{op}(x, {n})'}\nstep map\n")


def rows_for(op, fmt, rnd):
    """Lanes of states: (x, y) pairs for pow and powr, [x] for the three."""
    xs = pool(op, fmt, rnd)
    return [list(x) for x in xs] if op in TWO else [[x] for x in xs]


# the marked lanes of each pool (a lane count under each of the five
# attributes), MEASURED at the commit that wrote this test: pow's pool
# (pow_pairs, 171 pairs) marks 3 lanes at every format, powr's 2, and the
# three's (n_lanes, 30 values, n = 3) pown 3, rootn 2 and compound 4 at fp64
# and 6 at fp128 and fp256
MARKED = {("pow", "fp32"): 3, ("pow", "fp64"): 3, ("pow", "fp128"): 3,
          ("pow", "fp256"): 3, ("powr", "fp32"): 2, ("powr", "fp64"): 2,
          ("powr", "fp128"): 2, ("powr", "fp256"): 2, ("pown", "fp64"): 3,
          ("pown", "fp128"): 3, ("pown", "fp256"): 3, ("pown", "fp32"): 3,
          ("rootn", "fp32"): 2, ("rootn", "fp64"): 2,
          ("rootn", "fp128"): 2, ("rootn", "fp256"): 2, ("compound", "fp64"): 4,
          ("compound", "fp128"): 6, ("compound", "fp256"): 6}


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
@pytest.mark.parametrize("op", FIVE)
def test_each_of_the_five_compiles_and_runs_as_lang_run_at_every_attribute(
        op, fmt_name):
    """At every format where the routine compiles (the three not at fp32:
    test_the_three_at_fp32_are_routine_unavailable_on_every_target) under
    all five attributes: `next x = pow(x, y)` or `next x = pown(x, 3)` through
    cftc.compile_text, the manifest's routines naming the one instance, the
    image on seq.py against lang.run lane by lane - an unmarked lane's state
    and its five flags equal, a marked lane compared only as a guess within
    an encoding and counted - and, under rne, the same image bank for bank
    on sw, sw:4096 and revision 8's three targets, and refused
    `target-feature` on revision 7's four (the sentence naming the
    routine)."""
    if op == "compound" and fmt_name == "fp32":
        pytest.skip("compound has no fp32: it is not built there")
    fmt = FORMATS[fmt_name]
    name = R.instance(op, 3 if op in N_KEYED else None)
    marks = {}
    for rnd in sf.RND_MODES:
        text = source(op, fmt_name, RND_NAMES[rnd])
        c = cftc.compile_text(text, 1, source="t.cftl")
        assert c.version == cftc.VERSION == 9
        assert c.manifest["routines"]["calls"] == {name: 1}
        assert "FLAG_CONTROL" in c.features
        assert c.accepted_by == ["sw", *REV8]
        _r, marked = held_by_lang_run(c, rows_for(op, fmt, rnd), 1)
        marks[RND_NAMES[rnd]] = len(marked)
        if rnd != sf.RND_RNE:
            continue
        for t in REV8 + ("sw:4096",):
            ct = cftc.compile_text(text, 1, target=t, source="t.cftl")
            assert (ct.image, ct.bank) == (c.image, c.bank), t
        for t in NO_FLAG_CONTROL:
            with pytest.raises(lang.Refusal) as e:
                cftc.compile_text(text, 1, target=t, source="t.cftl")
            assert e.value.name == "target-feature", (t, str(e.value))
            assert "FLAG_CONTROL (CAPS2[14])" in e.value.sentence
            assert name in e.value.sentence
    # the marked lanes are the exact cases (an exact power, whose in-lane
    # test cannot decide the last bit: the structured families), counted,
    # never required: the same count under all five attributes
    assert marks == {r: MARKED[(op, fmt_name)] for r in RND_NAMES.values()},         marks


@needs_mpmath
@pytest.mark.parametrize("op,fmt_name", N_KEYED_AT)
def test_the_three_at_the_edges_of_int64_compile_and_run_as_lang_run(
        op, fmt_name):
    """n = -2^63, 2^63 - 1, 0 and 1 (not rootn's 0) through the source: the
    constant is the language's, cftc reads its exact value, and at fp64
    2^63 - 1 does not even round to itself. Under rne and rdn, the image on
    seq.py equals lang.run lane by lane (marked lanes as guesses)."""
    fmt = FORMATS[fmt_name]
    for n in (-2 ** 63, 2 ** 63 - 1, 0, 1):
        if op == "rootn" and n == 0:
            continue
        for rnd in (sf.RND_RNE, sf.RND_RDN):
            c = cftc.compile_text(source(op, fmt_name, RND_NAMES[rnd], n), 1,
                                  source="t.cftl")
            want = [] if (op, n) in ir.REWRITE else [R.instance(op, n)]
            assert c.lowered.routines == want, (op, n)
            held_by_lang_run(c, rows_for(op, fmt, rnd), 1)


@needs_mpmath
def test_two_n_in_one_compiled_source_are_two_keys_one_n_twice_one_key():
    """pown(x, 3) and pown(y, 5) in one source: two keys in the manifest's
    calls and per_call, the bank the union of the two fragments' words;
    pown(x, 3) and pown(y, 3): one key, calls 2; and each result equals
    lang.run."""
    fmt = FORMATS["fp64"]
    t = ("system t\nformat fp64\nround rne\nstate x, y\n"
         "next x = pown(x, 3)\nnext y = pown(y, 5)\nstep map\n")
    c = cftc.compile_text(t, 2, source="t.cftl")
    calls = c.manifest["routines"]["calls"]
    assert calls == {"pown(3)": 1, "pown(5)": 1}
    assert set(c.manifest["routines"]["per_call"]) == set(calls)
    assert c.manifest["routines"]["per_call"]["pown(3)"] == \
        len(R.fragment("pown", fmt, sf.RND_RNE, 3))
    xs = [[x, y] for x in n_lanes(fmt, 0, "a")[:12]
          for y in n_lanes(fmt, 0, "b")[8:14]]
    held_by_lang_run(c, xs, 2)
    t2 = t.replace("pown(y, 5)", "pown(y, 3)")
    c2 = cftc.compile_text(t2, 2, source="t.cftl")
    assert c2.manifest["routines"]["calls"] == {"pown(3)": 2}
    assert c2.manifest["routines"]["words"] < c.manifest["routines"]["words"]


@needs_mpmath
def test_a_const_read_as_n_alone_is_no_constant_of_the_manifest_bank():
    """`pown(x, 3)`: the bank holds the routine's words only (no slot is a
    const), and the same 3 also read as a multiplier (`y * 3`) is a slot of
    kind const: the const entry is one, the slot is the use."""
    t = ("system t\nformat fp64\nround rne\nstate x\n"
         "next x = pown(x, 3)\nstep map\n")
    c = cftc.compile_text(t, 1, source="t.cftl")
    assert {e["kind"] for e in c.manifest["bank"]} == {"word"}
    t2 = ("system t\nformat fp64\nround rne\nstate x, y\n"
          "next x = pown(x, 3)\nnext y = y * 3\nstep map\n")
    c2 = cftc.compile_text(t2, 1, source="t.cftl")
    assert [e["kind"] for e in c2.manifest["bank"]].count("const") == 1


@needs_mpmath
def test_a_marked_lane_through_a_compiled_image_pow_3_2_under_rtz_at_fp64():
    """pow(3, 2) with a RUN-TIME exponent 2 at fp64 under rtz is the study's
    structured example (docs/studies/M3-pow.md, section 8 item 11): the
    result 9 is exact and the in-lane test cannot decide the last bit of a
    value that sits on a boundary from below, so the lane is MARKED (R23's
    byte [7], STATUS[6]); its value is the routine's best guess, within an
    encoding of the definition's, and an ordinary lane beside it is unmarked
    and equal to lang.run with its flags. Written `pow(x, 2)` with the
    constant the compiler rewrites it as x * x: the same lane is 9, exact,
    unmarked, equal to lang.run - what the rewrite does instead."""
    fmt = FORMATS["fp64"]
    three, two, plain = (K.round_once(fmt, sf.RND_RTZ, Fraction(q))[0]
                         for q in (3, 2, Fraction(7, 3)))
    c = cftc.compile_text(source("pow", "fp64", "rtz"), 1, source="t.cftl")
    r, marked = held_by_lang_run(c, [[plain, two], [three, two]], 1)
    assert marked == [1]
    assert r.lane_flags[1] & seq.LANE_MARKED and r.status & seq.STATUS_MARKED
    assert not r.lane_flags[0] & seq.LANE_MARKED
    ref = lang.run(c.graph, [[three, two]], 1).states[0][0]
    assert ref == K.round_once(fmt, sf.RND_RTZ, Fraction(9))[0]
    assert abs(r.scratch_out[c.ir.m] - ref) <= 1
    t = source("pow", "fp64", "rtz", body="pow(x, 2)").replace(
        "state x, y", "state x, y")
    c2 = cftc.compile_text(t, 1, source="t.cftl")
    assert c2.ir.rewritten == [(0, "pow", 2, "mul")]
    r2, marked2 = held_by_lang_run(c2, [[three, two], [plain, two]], 1)
    assert marked2 == [] and r2.scratch_out[0] == ref


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
def test_pow_and_powr_of_the_same_operands_share_their_front(fmt_name):
    """pow(x, y) and powr(x, y) in one source: the routines' instructions
    are hash-consed across the two (the front: classification, the
    logarithm, the exponential's reduction), so the quiet instructions of
    the image are fewer than the two alone's sum, by the same number in
    either order, MEASURED from the image (program.routine_alu, rne):
    329, 384, 435 and 800 at fp64, fp128, fp256 and fp32 (the study's
    section 5.4: 329 to 435); and two powers of one base, pow(x, y) and
    pow(x, z), share the logarithm: 173, 217, 255 and 434."""
    def alu(body, states="x, y, z"):
        ss = states.split(", ")
        nexts = "".join(f"next {s} = {body if s == 'x' else s}\n"
                        for s in ss)
        t = (f"system t\nformat {fmt_name}\nround rne\nstate {states}\n"
             f"{nexts}step map\n")
        return cftc.compile_text(t, 1, source="t.cftl").program.routine_alu()
    p, r = alu("pow(x, y)"), alu("powr(x, y)")
    both, other = (alu("pow(x, y) + powr(x, y)"),
                   alu("powr(x, y) + pow(x, y)"))
    assert both == other
    assert p + r - both == {"fp64": 329, "fp128": 384, "fp256": 435,
                            "fp32": 800}[fmt_name]
    pp = alu("pow(x, y) + pow(x, z)")
    assert 2 * p - pp == {"fp64": 173, "fp128": 217, "fp256": 255,
                          "fp32": 434}[fmt_name]


# ---- the rewrites, compiled, in the primal and in a tangent section ----------------------------

REWRITES = {("pow", 2): "x * x", ("pown", 2): "x * x", ("pow", 1): "x * 1",
            ("pown", 1): "x * 1", ("rootn", 1): "x * 1",
            ("pow", -1): "1 / x", ("pown", -1): "1 / x",
            ("rootn", -1): "1 / x"}


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
@pytest.mark.parametrize("op,n", EIGHT, ids=lambda v: str(v))
def test_each_of_the_eight_rewrites_compiled_is_lang_run_of_the_node(
        op, n, fmt_name):
    """`next x = op(x, n)` through the language: the graph holds the node
    (the manifest's graph_by_op counts it), the image holds the one
    multiplication or division (lowering.rewritten says which, and no
    routine of the five is in it), and the image on seq.py equals lang.run
    OF THE UNREWRITTEN NODE lane by lane, bits and flags, under all five
    attributes at every format - fp32 included for the three, where their
    routines are refused. The pool is n_lanes (28 values)."""
    fmt = FORMATS[fmt_name]
    for rnd in sf.RND_MODES:
        t = (f"system t\nformat {fmt_name}\nround {RND_NAMES[rnd]}\n"
             f"state x\nnext x = {op}(x, {n})\nstep map\n")
        c = cftc.compile_text(t, 1, source="t.cftl")
        assert c.manifest["lowering"]["graph_by_op"] == {op: 1}
        assert c.manifest["lowering"]["rewritten"] == {
            f"{op}({n})": {"nodes": 1, "as": ir.REWRITE[(op, n)][0]}}
        assert "routines" not in c.manifest or \
            set(c.manifest["routines"]["calls"]) <= {"div"}
        _r, marked = held_by_lang_run(c, [[x] for x in
                                          n_lanes(fmt, rnd, f"cr{rnd}")], 1)
        assert marked == []


@needs_mpmath
@pytest.mark.parametrize("op,n,twin", NOT_PROPOSED, ids=lambda v: str(v))
def test_the_three_not_proposed_are_compiled_as_routines_and_match_lang_run(
        op, n, twin):
    """rootn(x, 2), compound(x, 1) and pow(x, 1/2) are not rewritten: the
    manifest names the routine and no `rewritten`, and the image equals
    lang.run on the lanes where the study's two forms differ (rootn(-0, 2)
    is +0, compound at x < -1 and at -1 under rdn, pow(-0, 1/2) and
    pow(-inf, 1/2)) under all five attributes at fp64."""
    fmt = FORMATS["fp64"]
    for rnd in sf.RND_MODES:
        body = {"rootn": "rootn(x, 2)", "compound": "compound(x, 1)",
                "pow": "pow(x, 1/2)"}[op]
        c = cftc.compile_text(
            f"system t\nformat fp64\nround {RND_NAMES[rnd]}\nstate x\n"
            f"next x = {body}\nstep map\n", 1, source="t.cftl")
        assert "rewritten" not in c.manifest["lowering"]
        inst = R.instance(op, n if op != "pow" else None)
        assert c.manifest["routines"]["calls"] == {inst: 1}
        xs = n_lanes(fmt, rnd, f"np{rnd}") + [
            K.round_once(fmt, rnd, Fraction(-1))[0],
            K.round_once(fmt, rnd, Fraction(-3, 2))[0]]
        held_by_lang_run(c, [[x] for x in xs], 1)


# a tangent section's own nodes: the rules write pown(a, n - 1), pow(a,
# b - 1) and pown(rootn, 1 - n), and where that exponent is 2, 1 or -1 the
# rewrite applies to them too
TANGENT_SOURCES = {
    "pown(x, 3)": "pown(2)", "pown(x, 2)": "pown(1)",
    "pow(x, 3)": "pow(2)", "pow(x, 2)": "pow(1)", "pow(x, 0)": "pow(-1)",
    "rootn(x, 2)": "pown(-1)", "rootn(x, -1)": "pown(2)",
}


def _held_tangent(c, xs, steps):
    """The image with one tangent vector against lang.run, lane by lane:
    state, tangent and the five flags, a marked lane as a guess. -> the
    marked lanes."""
    fmt = c.ir.fmt
    one = K.round_once(fmt, c.ir.rnd, Fraction(1))[0]
    rows = [[x] for x in xs]
    tans = [[[one]] for _ in xs]
    r = c.run(rows, tangents=tans)
    m = c.ir.m
    marked = []
    for k, row in enumerate(rows):
        byte = r.lane_flags[k]
        ref = lang.run(c.graph, [row], steps, tangents=[tans[k]])
        out, tout = r.scratch_out[k * m], r.scratch_out[k * m + 1]
        if byte & seq.LANE_MARKED:
            marked.append(k)
            continue
        assert out == ref.states[0][0], (k, row, "state")
        assert tout == ref.tangents[0][0][0], (k, row, "tangent")
        assert byte & seq.LANE_FLAGS_IEEE == ref.flags, (k, row, "flags")
    return marked


@needs_mpmath
@pytest.mark.parametrize("fmt_name", FMT_NAMES)
@pytest.mark.parametrize("expr", sorted(TANGENT_SOURCES))
def test_the_rewrites_apply_in_a_tangent_section_and_equal_lang_run(
        expr, fmt_name):
    """A source with one tangent vector: the derivative rules write routine
    nodes of their own (pown(a, n - 1) for pown, pow(a, b - 1) for pow,
    pown(root, 1 - n) for rootn), and where the exponent is 2, 1 or -1 the
    rewrite is applied in the tangent section's nodes as in the step's
    (the manifest's lowering.rewritten counts them; the graph's own counts,
    graph_tangent_by_op, are before it). The image on seq.py equals lang.run
    - states, tangents and flags - lane by lane under all five attributes,
    at every format where the source compiles, fp32 included since parcel
    M3F2 (pown(x, 3) and rootn(x, 2) are routines of the step there, the
    triple word; rootn(x, -1) is a division in the step and a pown(root, 2),
    a multiplication, in the tangent, with pown(x, 2), pow(x, 3), pow(x, 2)
    and pow(x, 0))."""
    fmt = FORMATS[fmt_name]
    t3 = lambda rnd: (f"system t\nformat {fmt_name}\nround {rnd}\nstate x\n"
                      f"tangent w\nnext x = {expr}\nstep map\n")
    want = TANGENT_SOURCES[expr]
    for rnd in sf.RND_MODES:
        c = cftc.compile_text(t3(RND_NAMES[rnd]), 1, source="t.cftl")
        rw = c.manifest["lowering"]["rewritten"]
        assert want in rw, (expr, rw)
        # the tangent section has ONE such node a vector: counted twice
        # where the step's own node is the same instance
        _t = _held_tangent(c, n_lanes(fmt, rnd, f"tg{rnd}"), 1)


@needs_mpmath
@pytest.mark.parametrize("op", ("compound",))
def test_compound_at_fp32_is_routine_unavailable_on_every_target(op):
    """compound(x, 3) at fp32 is refused `routine-unavailable` (line None, the
    sentence naming the instance and "compound is not built at fp32") on sw
    and on revision 8's and revision 7's targets alike
    - BEFORE `target-feature`, which revision 7's targets would otherwise
    say - and a rewritten n at fp32 (pown(x, 2)) is not refused by name on
    sw, and is refused nothing on revision 7's, being a multiplication."""
    t = source(op, "fp32")
    for target in ("sw", *REV8, *NO_FLAG_CONTROL):
        with pytest.raises(lang.Refusal) as e:
            cftc.compile_text(t, 1, target=target, source="t.cftl")
        assert (e.value.name, e.value.line) == ("routine-unavailable", None)
        assert f"{op}(3)" in e.value.sentence
        assert "compound is not built at fp32" in e.value.sentence
    ok = cftc.compile_text(source("pown", "fp32", n=2), 1,
                           target="u50-rev7", source="t.cftl")
    assert ok.manifest["lowering"]["rewritten"]


@needs_mpmath
def test_pow_and_powr_are_target_feature_on_revision_7s_targets():
    """pow and powr need revision 8's flag control like every routine:
    revision 7's four targets refuse them `target-feature`, the sentence
    naming the routine, at fp64 and at fp32."""
    for fmt_name in ("fp64", "fp32"):
        for op in TWO:
            for t in NO_FLAG_CONTROL:
                if fmt_name == "fp32" and t == "open-core":
                    continue
                with pytest.raises(lang.Refusal) as e:
                    cftc.compile_text(source(op, fmt_name), 1, target=t,
                                      source="t.cftl")
                assert e.value.name in ("target-feature", "target-format"), \
                    (op, fmt_name, t, e.value.name)
                if e.value.name == "target-feature":
                    assert op in e.value.sentence


# ---- the call loop over batches of the five ---------------------------------------------------

def loop_source(op, fmt, rnd, form):
    return (f"system loop\nformat {fmt}\nround {rnd}\nstate x[3], y[3]\n"
            f"next x[i] = {form}\nnext y[i] = y[i]\nstep map\n")


def _run_rows(c, seed):
    rng = random.Random(str(seed))
    fmt = c.ir.fmt
    n = c.ir.n_primal

    def val():
        return K.round_once(fmt, sf.RND_RNE,
                            Fraction(rng.randint(1, 300), 97))[0]
    return [[val() for _ in range(n)] for _ in range(4)]


@needs_mpmath
@pytest.mark.parametrize("fmt_name", ("fp32", "fp64"))
@pytest.mark.parametrize("op", TWO)
def test_a_batch_of_pow_or_powr_loops_or_is_declined_as_the_room_says(
        op, fmt_name, monkeypatch):
    """Three calls of one routine in one batch, the threshold at 0 (the
    loop reaches the batch): the loop is the call loop of a routine of TWO
    inputs - a record is two slots a call, x then y - unless the plan needs
    more registers than the allocator's 29 (callloop.declined: the same
    arithmetic as the room table above), in which case the batch stays
    inlined, the manifest says so (call_loop_declined: op, depth, calls,
    registers, room), and the step is lang.run's all the same. MEASURED at
    every attribute: pow is declined at fp32 under all five (33
    registers), and at fp64 under rne and rmm (31); powr is declined at
    fp32 (30) under all five and loops at fp64 under all five; and with
    y one constant for every call (`pow(x[i], 3/2)`: y fixed, one slot a
    call) pow is still declined where it needs 32 or 30, and powr at fp32,
    which needs 29 with an input fixed, LOOPS."""
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    fmt = FORMATS[fmt_name]
    past = {("pow", "fp32"): set(sf.RND_MODES),
            ("pow", "fp64"): {sf.RND_RNE, sf.RND_RMM},
            ("powr", "fp32"): set(sf.RND_MODES), ("powr", "fp64"): set()}
    for rnd in sf.RND_MODES:
        c = cftc.compile_text(
            loop_source(op, fmt_name, RND_NAMES[rnd], f"{op}(x[i], y[i])"), 1,
            source="loop.cftl")
        rows = _run_rows(c, f"{op}{fmt_name}{rnd}")
        r = c.run(rows)
        m = c.ir.m
        for k, row in enumerate(rows):
            if r.lane_flags[k] & seq.LANE_MARKED:
                continue
            want = lang.run(c.graph, [row], 1)
            assert r.scratch_out[k * m:k * m + 6] == want.states[0], k
            assert r.lane_flags[k] & seq.LANE_FLAGS_IEEE == want.flags, k
        declined = c.manifest["routines"].get("call_loop_declined")
        if rnd in past[(op, fmt_name)]:
            assert c.looped == [] and declined is not None, (op, rnd)
            assert [(d["op"], d["calls"], d["room"]) for d in declined] == \
                [(op, 3, 29)] and declined[0]["registers"] > 29
            assert "call_loops" not in c.manifest["routines"]
        else:
            assert declined is None and len(c.looped) == 1, (op, rnd)
            loop = c.manifest["routines"]["call_loops"]["loops"][0]
            assert (loop["op"], loop["calls"]) == (op, 3)
            lo, hi = loop["records"]
            assert hi - lo + 1 == 2 * 3          # two slots a call
            assert "n" not in loop and loop["fixed"] == {}
    # y one constant: the room's `fixed` rows
    for rnd in (sf.RND_RNE, sf.RND_RTZ):
        c = cftc.compile_text(
            loop_source(op, fmt_name, RND_NAMES[rnd], f"{op}(x[i], 3/2)"), 1,
            source="loop.cftl")
        declined = c.manifest["routines"].get("call_loop_declined")
        looped = (op == "powr" and fmt_name == "fp32") or \
            (op == "pow" and fmt_name == "fp64" and rnd != sf.RND_RNE) or \
            (op == "powr" and fmt_name == "fp64")
        assert (declined is None) == looped, (op, fmt_name, RND_NAMES[rnd])
        if looped:
            loop = c.manifest["routines"]["call_loops"]["loops"][0]
            lo, hi = loop["records"]
            assert hi - lo + 1 == 3 and list(loop["fixed"]) == ["b"]


@needs_mpmath
@pytest.mark.parametrize("op", N_KEYED)
def test_a_batch_of_the_three_is_one_n_a_batch_and_loops(op, monkeypatch):
    """pown(x[i], 3) and pown(y[i], 5) at one depth are TWO batches: the
    manifest's loops name each with its n, one slot a call, and a looped
    call's result is lang.run's - a loop is one copy of ONE fragment, and a
    fragment is a function of n. The order of two batches of one routine
    at one depth is by n, signed. The same n in all six calls is one batch
    of six."""
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    ns = (5, 3) if op != "rootn" else (5, -3)
    t = (f"system loop\nformat fp64\nround rne\nstate x[3], y[3]\n"
         f"next x[i] = {op}(x[i], {ns[0]})\n"
         f"next y[i] = {op}(y[i], {ns[1]})\nstep map\n")
    c = cftc.compile_text(t, 1, source="loop.cftl")
    loops = c.manifest["routines"]["call_loops"]["loops"]
    assert sorted((lp["op"], lp["n"], lp["calls"], lp["depth"])
                  for lp in loops) == [(op, n, 3, 1) for n in sorted(ns)]
    # the batches, in callloop's order: by depth, the routines' order, n
    assert [(bt.op, bt.n) for bt in callloop.batches(c.lowered)] == \
        [(op, n) for n in sorted(ns)]
    assert all(lp["records"][1] - lp["records"][0] + 1 == 3 for lp in loops)
    assert c.manifest["routines"]["calls"] == {
        R.instance(op, n): 3 for n in sorted(ns)}
    fmt = FORMATS["fp64"]
    rows = _run_rows(c, op)
    r = c.run(rows)
    m = c.ir.m
    for k, row in enumerate(rows):
        if r.lane_flags[k] & seq.LANE_MARKED:
            continue
        want = lang.run(c.graph, [row], 1)
        assert r.scratch_out[k * m:k * m + 6] == want.states[0], (op, k)
        assert r.lane_flags[k] & seq.LANE_FLAGS_IEEE == want.flags
    t1 = t.replace(f"{op}(y[i], {ns[1]})", f"{op}(y[i], {ns[0]})")
    c1 = cftc.compile_text(t1, 1, source="loop.cftl")
    loops = c1.manifest["routines"]["call_loops"]["loops"]
    assert [(lp["n"], lp["calls"]) for lp in loops] == [(ns[0], 6)]
    assert [(bt.n, len(bt.calls)) for bt in callloop.batches(c1.lowered)] \
        == [(ns[0], 6)]
    assert fmt.name == "fp64"


@needs_mpmath
def test_the_call_loops_order_is_the_routines_order_then_n(monkeypatch):
    """Batches at one depth are in R.ROUTINES' order (callloop.ORDER, the
    language's: ... atan2, pow, powr, pown, rootn, compound), then by n
    signed: pown(3) and pown(-2) in one source are listed -2 first, and a
    pow batch comes before a pown batch, before a compound's."""
    monkeypatch.setattr(callloop, "CALL_LOOP_ABOVE", 0)
    t = ("system loop\nformat fp64\nround rtz\nstate a[2], b[2], c[2], d[2], "
         "e[2], w[2]\nnext a[i] = pown(a[i], 3)\nnext b[i] = pown(b[i], -2)\n"
         "next c[i] = compound(c[i], 2)\nnext d[i] = pow(d[i], w[i])\n"
         "next e[i] = rootn(e[i], 3)\nnext w[i] = w[i]\nstep map\n")
    c = cftc.compile_text(t, 1, source="loop.cftl")
    got = [(bt.op, bt.n) for bt in callloop.batches(c.lowered)]
    assert len(c.manifest["routines"]["call_loops"]["loops"]) == 5
    want = sorted(got, key=lambda e: (callloop.ORDER[e[0]], e[1] or 0))
    assert got == want and ("pown", -2) in got and got.index(
        ("pown", -2)) < got.index(("pown", 3))
    assert [e[0] for e in got] == ["pow", "pown", "pown", "rootn",
                                   "compound"]


# ---- the manifest ------------------------------------------------------------------------------

@needs_mpmath
def test_the_manifest_words_the_five_only_where_a_step_holds_one():
    """The routines block of a step with pown(3) and exp carries the radian
    -free, inverse-free sentence of the six and, for the five, its own: "the
    math library's pow, powr, pown, rootn and compound likewise set the
    raised word's bit 7"; the five are never called the six (a manifest of
    a step with the five alone has no six's sentence); a step without one of
    the five carries no such sentence; calls and per_call are keyed by
    instance (`pown(3)`, `pown(5)`), each per_call the fragment's own
    length; the 'rewritten' entry is under lowering, only where a rewrite
    was made, and its absence leaves a manifest as it was."""
    def flags(t):
        c = cftc.compile_text(t, 1, source="t.cftl")
        return c, c.manifest["routines"]["flags"]
    base = "system t\nformat fp64\nround rne\nstate x\n"
    c, f = flags(base + "next x = pown(x, 3)\nstep map\n")
    assert "pow, powr, pown, rootn and compound likewise" in f
    assert "the math library's six also set" not in f
    assert "atan, asin, acos and atan2 likewise" not in f
    c, f = flags(base + "next x = pown(x, 3) + exp(x)\nstep map\n")
    assert "the math library's six also set" in f and \
        "pow, powr, pown, rootn and compound likewise" in f
    c, f = flags(base + "next x = exp(x)\nstep map\n")
    assert "pow, powr" not in f
    c, f = flags(base + "next x = x / 3 + pown(x, 5) + pown(x, 3)\n"
                 "step map\n")
    assert set(c.manifest["routines"]["calls"]) == {"div", "pown(3)",
                                                    "pown(5)"}
    assert "rewritten" not in c.manifest["lowering"]
    c2 = cftc.compile_text(base + "next x = pown(x, 2) / 3\nstep map\n", 1,
                           source="t.cftl")
    assert c2.manifest["lowering"]["rewritten"] == {
        "pown(2)": {"nodes": 1, "as": "mul"}}
    assert c2.manifest["lowering"]["graph_by_op"] == {"div": 1, "pown": 1}


@needs_mpmath
def test_every_committed_manifest_without_the_five_says_what_it_said():
    """A manifest of a step without the five has no `rewritten`, no instance
    key and none of the five's sentence: the committed ones differ from the
    base's in the version line alone (python/cftc/__init__.py's VERSION 9
    paragraph names the sets; here the committed programs/systems/compiled
    and compiled-tangent manifests are read for the keys)."""
    import glob
    seen = 0
    for path in glob.glob(str(ROOT / "programs" / "systems" / "compiled*" /
                              "*.manifest.json")):
        m = json.loads(Path(path).read_text(encoding="utf-8"))
        assert m["compiler"]["version"] == 9, path
        if "atmosphere" in path:
            continue
        seen += 1
        assert "rewritten" not in m["lowering"], path
        flags = m.get("routines", {}).get("flags", "")
        assert "pow, powr" not in flags, path
        assert not any("(" in k for k in m.get("routines", {}).get(
            "calls", {})), path
    assert seen == 26


# ---- the reference: a body falling through a power-law atmosphere -----------------------------

from cft_golden.lang import check as lang_check_mod        # noqa: E402
from cft_golden.lang import tangent as lang_tangent         # noqa: E402
from cft_golden.lang.graph import Node                      # noqa: E402

SYSTEMS = ROOT / "programs" / "systems"
ATM_NAMES = ("atmosphere-rk4-tangent-fp64", "atmosphere-rk4-tangent-fp256")
# alt in [0, 4] keeps the base 1 + alt / 8 in [1, 3/2]; v in [-1, 1], m in
# [1, 2] (programs/tangent_check.py's MATH_BOX)
ATM_BOX = [(0, 4), (-1, 1), (1, 2)]


def _tref(name):
    return lang.load(SYSTEMS / f"{name}.cftl").graph


def test_the_two_sources_are_one_system_at_two_formats_and_hold_pow_and_pown():
    """The fp256 source is the fp64 source with the format line changed,
    comments too: nothing else differs; it is round rdn, one tangent vector,
    and holds a pow with a non-integer constant exponent and a pown with
    n = 3 in its equations."""
    a = (SYSTEMS / f"{ATM_NAMES[0]}.cftl").read_text(
        encoding="ascii").splitlines()
    b = (SYSTEMS / f"{ATM_NAMES[1]}.cftl").read_text(
        encoding="ascii").splitlines()
    assert len(a) == len(b)
    assert [(x, y) for x, y in zip(a, b) if x != y] == \
        [("format fp64", "format fp256")]
    code = [ln for ln in a if ln and not ln.startswith(";")]
    assert code.count("tangent w") == 1 and "round  rdn" in code
    eqs = " ".join(ln for ln in code if ln.startswith("d/dt"))
    assert "pow(1 + alt / H, -4.5)" in eqs and "pown(v, 3)" in eqs


@needs_mpmath
@pytest.mark.parametrize("name", ATM_NAMES)
def test_the_committed_atmosphere_is_what_the_compiler_writes(name):
    """Eight files each, byte for byte what cftc writes for the committed
    source at 10 steps (tangent_check.py --write made them), the manifest
    saying version 9; the image calls pow (the primal's four and the
    tangent's four, pow(a, -5.5), each a routine of its own exponent, a
    routine node with a constant exponent that no rewrite takes), pown(3)
    four times and division - and no pown(2): the rule's pown(v, 2) is
    written as the product v * v (lowering.rewritten counts the four), so
    the compiled bytes hold a mul where the graph holds a pown."""
    c = cftc.compile_file(SYSTEMS / f"{name}.cftl", 10,
                          source=f"programs/systems/{name}.cftl")
    files = c.files()
    assert len(files) == 8
    for fname, data in files.items():
        assert (SYSTEMS / "compiled-tangent" / fname).read_bytes() == data, \
            fname
    assert c.manifest["compiler"] == {"name": "cftc", "version": 9}
    assert c.accepted_by == ["sw", *REV8]
    calls = c.manifest["routines"]["calls"]
    assert calls == {"div": 8, "pow": 8, "pown(3)": 4}, calls
    assert c.manifest["lowering"]["rewritten"] == {
        "pown(2)": {"nodes": 4, "as": "mul"}}
    assert c.manifest["lowering"]["graph_tangent_by_op"]["pown"] == 4
    assert c.manifest["lowering"]["graph_by_op"]["pown"] == 4
    assert "pow, powr, pown, rootn and compound" in \
        c.manifest["routines"]["flags"]
    g = _tref(name)
    assert g.to_bytes() == (SYSTEMS / "compiled-tangent" /
                            f"{name}.graph.json").read_bytes()


def _atm_rows(fmt, rnd, n, seed):
    rng = random.Random(seed)

    def val(lo, hi):
        q = lo + (hi - lo) * Fraction(rng.randint(1, 10 ** 6 - 1), 10 ** 6)
        return K.round_once(fmt, rnd, q)[0]
    states = [[val(lo, hi) for lo, hi in ATM_BOX] for _ in range(n)]
    tans = [[[K.round_once(fmt, rnd, Fraction(rng.randint(-100, 100), 53))[0]
              for _ in ATM_BOX]] for _ in states]
    return states, tans


@needs_mpmath
@pytest.mark.parametrize("name", ATM_NAMES)
def test_the_atmospheres_lanes_mark_none_and_are_the_interpreters(name):
    """The reference's lanes - 24 in ATM_BOX, with tangents, at 10 steps -
    mark no lane (leg G of tangent_check.py fails a marked segment by name:
    the pow family marks the exact cases by design, and the box has none),
    and every lane's states, tangent and flags are lang.run's, bit for bit.
    It is 0 of 24 marked."""
    fmt_name = name.rsplit("-", 1)[1]
    fmt, rnd = FORMATS[fmt_name], sf.RND_RDN
    c = cftc.compile_file(SYSTEMS / f"{name}.cftl", 10,
                          source=f"programs/systems/{name}.cftl")
    states, tans = _atm_rows(fmt, rnd, 24, "atmosphere " + fmt_name)
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
    """The derivation with the rule of `kind` = (op, how) written in
    another shape: how "commuted" has the rule's outermost product's
    operands (or, for rootn, the numerator's) the other way round - another
    node shape, the same value; how "regrouped" is (n * pown(a, n - 1)) *
    da written n * (pown(a, n - 1) * da) - another shape and, under rdn,
    another value where the two roundings differ."""
    kind = None

    def rule(self, node):
        res = super().rule(node)
        op, how = self.kind
        if node.op != op or res is None:
            return res
        line = node.line

        def N(o, *args):
            return Node(o, args, line)
        if how == "commuted":
            if res.op in ("mul", "add"):
                return N(res.op, res.args[1], res.args[0])
            top = res.args[0]
            return N("div", N(top.op, top.args[1], top.args[0]),
                     res.args[1])
        if how == "regrouped" and res.op == "mul" and res.args[0].op == "mul":
            return N("mul", res.args[0].args[0],
                     N("mul", res.args[0].args[1], res.args[1]))
        return res


@pytest.mark.parametrize("kind", [("pow", "commuted"), ("pown", "commuted"),
                                  ("pow", "regrouped"),
                                  ("pown", "regrouped")], ids=str)
def test_the_rules_of_pow_and_pown_written_otherwise_move_the_atmospheres_bytes(
        kind, monkeypatch):
    """The pow rule and the pown rule, each written in another shape (the
    product's operands commuted, or regrouped), move the committed graph of
    the atmosphere at fp64 and fp256 and of no other committed variational
    reference - none holds a pow or a pown: under any attribute a node shape
    moves the graph's bytes (M2C's finding). Checking a source needs no
    mpmath, so neither does this."""
    comp = SYSTEMS / "compiled-tangent"
    names = sorted(p.name[:-len(".graph.json")] for p in comp.glob(
        "*.graph.json"))
    assert set(ATM_NAMES) <= set(names) and len(names) == 20
    committed = {n: (comp / f"{n}.graph.json").read_bytes() for n in names}

    class P(_RulePlant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check_mod, "Derivation", P)
    moved = sorted(n for n in names if _tref(n).to_bytes() != committed[n])
    assert moved == sorted(ATM_NAMES), (kind, moved)


@pytest.mark.parametrize("kind", [("powr", "commuted"),
                                  ("rootn", "commuted"),
                                  ("compound", "commuted"),
                                  ("powr", "regrouped"),
                                  ("compound", "regrouped")], ids=str)
def test_the_other_three_rules_written_otherwise_move_a_graph_but_no_committed_one(
        kind, monkeypatch):
    """powr's, rootn's and compound's rules are held by no committed
    reference (the atmosphere holds pow and pown alone, as the study's
    reference does), so a rule of those three written in another shape moves
    no committed graph - MEASURED: none of the 20 - but does move the
    graph of a one-operation system with a tangent, which is where their
    rules' bytes are held (test_lang_pow.py holds their text)."""
    comp = SYSTEMS / "compiled-tangent"
    names = sorted(p.name[:-len(".graph.json")] for p in comp.glob(
        "*.graph.json"))
    committed = {n: (comp / f"{n}.graph.json").read_bytes() for n in names}
    body = {"powr": "powr(x, 3/2)", "rootn": "rootn(x, 3)",
            "compound": "compound(x, 3)"}[kind[0]]
    text = ("system t\nformat fp64\nround rdn\nstate x\ntangent w\n"
            f"next x = {body}\nstep map\n")
    good = lang.compile_text(text, "t.cftl").graph.to_bytes()

    class P(_RulePlant):
        pass
    P.kind = kind
    monkeypatch.setattr(lang_check_mod, "Derivation", P)
    assert [n for n in names if _tref(n).to_bytes() != committed[n]] == []
    planted = lang.compile_text(text, "t.cftl").graph.to_bytes()
    assert planted != good, kind


# the lanes (of 60, 10 steps, round rdn) in which the planted rule's value
# differs from the committed rule's, by rule, format and the shape written,
# MEASURED at the commit that wrote this test (also under rne, in a scratch
# run: the same counts but for pow's regrouped rule, which is none under rne
# at fp64): the commuted shapes are the same value on every lane; the
# regrouped pown rule is the same value on all 60 as well, at both formats,
# and the regrouped pow rule is another value on ONE lane at fp64 and on none
# at fp256
VARIANT_LANES = {("pown", "fp64"): {"commuted": 0, "regrouped": 0},
                 ("pown", "fp256"): {"commuted": 0, "regrouped": 0},
                 ("pow", "fp64"): {"commuted": 0, "regrouped": 1},
                 ("pow", "fp256"): {"commuted": 0, "regrouped": 0}}


@needs_mpmath
@pytest.mark.parametrize("fmt_name", ("fp64", "fp256"))
@pytest.mark.parametrize("op", ("pown", "pow"))
def test_the_rules_written_otherwise_are_other_bytes_and_the_values_are_counted(
        op, fmt_name, monkeypatch):
    """Value-only variants measured on the atmosphere itself, compiled round
    rdn, run for 10 steps on 60 lanes of ATM_BOX with
    tangents, the good and the planted image against each other: each
    variant is other bytes (the graph and the image), the commuted shapes
    are the same value on every lane, and the regrouped shapes differ on the
    number of lanes VARIANT_LANES says - one lane, pow's at fp64 under rdn;
    pown's rule regrouped is the same value on all 60 here: a fact of these
    lanes, not a theorem (the two groupings round differently in general)."""
    src = (SYSTEMS / f"atmosphere-rk4-tangent-{fmt_name}.cftl").read_text(
        encoding="ascii")
    fmt = FORMATS[fmt_name]
    got = {}
    for how in ("commuted", "regrouped"):
        class P(_RulePlant):
            pass
        P.kind = (op, how)
        for rname in ("rdn",):
            rnd = RND_CODE[rname]
            text = src.replace("round  rdn", f"round  {rname}")
            good = cftc.compile_text(text, 10, source="f.cftl")
            monkeypatch.setattr(lang_check_mod, "Derivation", P)
            planted = cftc.compile_text(text, 10, source="f.cftl")
            monkeypatch.undo()
            assert planted.graph_bytes != good.graph_bytes, (how, rname)
            assert planted.image != good.image, (how, rname)
            states, tans = _atm_rows(fmt, rnd, 60, "variants")
            rg = good.run(states, tangents=tans)
            rp = planted.run(states, tangents=tans)
            assert not any(b & seq.LANE_MARKED for b in rg.lane_flags +
                           rp.lane_flags)
            m = good.ir.m
            got[how] = sum(
                rg.scratch_out[k * m:(k + 1) * m] !=
                rp.scratch_out[k * m:(k + 1) * m] for k in range(len(states)))
    assert got == VARIANT_LANES[(op, fmt_name)], got


@needs_mpmath
@pytest.mark.parametrize("op", N_KEYED)
def test_one_operand_two_n_is_two_nodes_never_merged_by_sharing(op):
    """`op(x, 3) + op(x, 5)`: the same operand and two n. The hash-consing key
    is (op, operands, n), so the two are two lowered nodes, two instances
    (shared = 0) and two fragments whose results differ - a key without n
    would merge them into one node and give the second its first's value.
    Under rne and rdn every unmarked lane equals lang.run, every marked
    lane is counted and named (a marked pair's guesses are summed, so such
    a lane may be two encodings from lang.run's: pown(-27, 3) is exact and
    left to the mark, fp64 rdn), and every lane, marked or not, equals bit
    for bit the program's own composition of its fragments' outputs
    (routines.run): the add of the two guesses rounded under the attribute,
    their flag words ORed with the add's."""
    fmt = FORMATS["fp64"]
    ns = (3, 5) if op != "rootn" else (3, 5)
    for rnd in (sf.RND_RNE, sf.RND_RDN):
        t = (f"system t\nformat fp64\nround {RND_NAMES[rnd]}\nstate x\n"
             f"next x = {op}(x, {ns[0]}) + {op}(x, {ns[1]})\nstep map\n")
        c = cftc.compile_text(t, 1, source="t.cftl")
        assert c.lowered.shared == 0
        assert [nd.n for nd in c.lowered.nodes if nd.op == op] == list(ns)
        assert c.manifest["routines"]["calls"] == {
            R.instance(op, n): 1 for n in ns}
        xs = n_lanes(fmt, rnd, f"one{rnd}")
        r, marked = held_by_lang_run(c, [[x] for x in xs], 1)
        # the program's own composition of its fragments' outputs: the
        # image's lane is the program's add of the two fragments' values
        # (their guesses, where a lane is marked), rounded under the
        # attribute, flags the fragments' words ORed with the add's
        outs = [R.run(R.fragment(op, fmt, rnd, n), xs) for n in ns]
        m = c.ir.m
        for k in range(len(xs)):
            want, fl = sf.add(fmt, outs[0][0][k], outs[1][0][k], rnd)
            flags = (outs[0][1][k] | outs[1][1][k]) & seq.LANE_FLAGS_IEEE
            assert r.scratch_out[k * m] == want, (op, rnd, k, hex(xs[k]))
            assert r.lane_flags[k] & seq.LANE_FLAGS_IEEE == flags | fl, \
                (op, rnd, k, hex(xs[k]))
        assert sorted(marked) == sorted(
            k for k in range(len(xs)) if (outs[0][1][k] | outs[1][1][k])
            & 0x80)
