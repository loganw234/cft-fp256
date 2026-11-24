# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The routines the compiler inlines (cft_golden/routines.py, C4),
against the contract and against divfull.

* the read form IS divfull's program: instruction for instruction (each
  opcode, each attribute, each word by its bank index's name), and run as
  a program it deposits what divfull deposits, lane for lane, the flag
  word included;
* each specialised fragment, at every format and every attribute, run on
  seq.py against softfloat's div and sqrt lane by lane: the bits AND each
  lane's own flag word, over test_divfull's pools (the light cut here;
  the lang stage runs the full pools);
* what is proved of every fragment (routines.invariants): the flag word's
  values within the six a division or root can raise, never bit 7; at
  most sixteen values live; every instruction reading a word or an
  internal value; nothing left to simplify; the attributes the
  routine's own - one truncating fma in the division, none in the root;
* each specialisation rule planted wrong - a SELECT fold picking the
  other arm, an IOR taken for its first operand - red on the pools;
* the eight (M1's build, item 4): ROUTINES in the language's order, the
  six's fragments mathlib.py's own by name, and the one statement of the
  invariants per routine - the six's widened, division's and root's
  C4's, not loosened: the six's fragment named a division fails
  division's statement by its flag word, its attributes and its live
  count, and a division made to mark a lane, to round under RDN or under
  the program's attribute fails it too;
* the eleven (M2's build, item 5): sin, cos and tan join ROUTINES after
  log2, in the language's order; their fragments are mathlib.py's own,
  under the six's contract and a live cap of their own per format (23, 26,
  17 and 16: a row of LIVE_CAP each, which mathlib.TRIG_LIVE_CAP views,
  while mathlib.LIVE_CAP stays the six's 21, 13, 13 and 13); `sinh` is the
  name a fragment of no routine takes now; and all 220 fragments - the
  60 of the three, the six's 120, division's and root's 40 - are what they
  were at 19de866c, digest for digest (routine_digests.py);
* the fifteen (M4's build, wave 4): atan, asin, acos and atan2 join ROUTINES
  after tan, in the language's order; their fragments are mathlib.py's own,
  under the six's contract and a live cap of their own per function and
  format (a row of LIVE_CAP each, which mathlib.INV_LIVE_CAP views); atan2
  is the first routine of two inputs beside division, ("a", "b") = (y, x);
  and their 80 fragments are what they were at 21b98aec, digest for digest
  (routine_digests_inv.py), beside the 220 of the eleven at 19de866c;
* the twenty (M3's build, parcel M3C): pow, powr, pown, rootn and compound
  join ROUTINES after atan2, in the language's order; pow and powr take
  atan2's two inputs, the three ONE and an integer n that keys their
  fragment (N_KEYED, tied to the language's two-operand nodes); their cap
  rows are pinned (the three with no fp32 key until parcel M3F2) and
  mathlib.POW_LIVE_CAP is a view of them; and their 205 fragments are what
  they were at f7a1ce95, digest for digest (routine_digests_pow.py).
"""

import hashlib
import importlib.util
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cft_golden import FP32, FP64, FP128, FP256, asm, divfull, seq  # noqa: E402
from cft_golden import routines as R  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.softfloat import RND_MODES  # noqa: E402

from routine_digests import DIGESTS  # noqa: E402
from routine_digests_inv import DIGESTS_INV  # noqa: E402
from routine_digests_pow import DIGESTS_POW  # noqa: E402
from routine_pools import div_pairs, sqrt_xs  # noqa: E402

FORMATS = (FP32, FP64, FP128, FP256)


def lanes(op, fmt, light=True):
    return div_pairs(fmt, light) if op == "div" else sqrt_xs(fmt, light)


def wrong_lanes(f, ls):
    """[(lane, got, want)] where the fragment is not softfloat's."""
    if f.op == "div":
        outs, words = R.run(f, [p[0] for p in ls], [p[1] for p in ls])
    else:
        outs, words = R.run(f, ls)
    bad = []
    for i, x in enumerate(ls):
        args = x if f.op == "div" else (x,)
        want = R.GOLDEN[f.op](f.fmt, *args, f.rnd)
        if (outs[i], words[i]) != want:
            bad.append((x, (outs[i], words[i]), want))
    return bad


@pytest.mark.parametrize("op", ["div", "sqrt"])
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_the_read_form_is_divfull_instruction_for_instruction(op, fmt):
    prog = (divfull.div_full_program_for(fmt) if op == "div"
            else divfull.sqrt_full_program_for(fmt))
    names = divfull._NAMES_DIV if op == "div" else divfull._NAMES_SQRT
    f = R.read(op, fmt, sf.RND_RNE)
    alu = [seq.decode(w) for w in prog.insns if not seq.decode(w)["ctrl"]]
    assert len(f) == len(alu) == len(prog.insns) - 3
    for (opc, rnd, srcs), d in zip(f.body, alu):
        assert opc == d["op"]
        assert rnd == (d["rnd"] if opc in R.ROUNDED else None)
        consts = [names[idx] for (idx, k), field in
                  zip(seq.sources(d), ("ra", "rb", "rc"))
                  if k and field in asm.OP_FIELDS[d["op"]]]
        assert [s[1] for s in srcs if s[0] == "w"] == consts
    # run as a program it deposits what divfull deposits, lane for lane
    ls = lanes(op, fmt)[:300]
    a = [x[0] for x in ls] if op == "div" else ls
    b = [x[1] for x in ls] if op == "div" else [0] * len(ls)
    for rnd in (sf.RND_RNE, sf.RND_RDN):
        bank = divfull.bank(fmt, rnd) if op == "div" else \
            divfull.bank_sqrt(fmt, rnd)
        ref = seq.run(prog, a, b, bank=bank)
        outs, words = R.run(R.read(op, fmt, rnd), a, b)
        assert outs == ref.deposits[0::2] and words == ref.deposits[1::2]


@pytest.mark.parametrize("rnd", RND_MODES)
@pytest.mark.parametrize("op", ["div", "sqrt"])
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_each_fragment_is_softfloats_bits_and_flags_lane_by_lane(fmt, op,
                                                                  rnd):
    f = R.fragment(op, fmt, rnd)
    bad = wrong_lanes(f, lanes(op, fmt))
    assert not bad, (f"{op} {fmt.name} rnd={rnd}: {len(bad)} lanes, first "
                     f"{bad[0]}")


@pytest.mark.parametrize("op", ["div", "sqrt"])
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_what_is_proved_of_every_fragment(fmt, op):
    for rnd in RND_MODES:
        f = R.fragment(op, fmt, rnd)
        assert R.invariants(f) == []
        assert R.flag_words(f) <= R.FLAG_WORDS
        assert all(not w & 0x80 for w in R.FLAG_WORDS)
        assert f.live_max() <= R.LIVE_MAX
        assert f.result[0] == f.flags[0] == "v"
        rtz = [i for i, (_o, r, _s) in enumerate(f.body) if r == sf.RND_RTZ]
        assert len(rtz) == (1 if op == "div" else 0)
        if op == "div":
            assert f.body[rtz[0]][0] == sf.OP_FMA        # q2, truncated
        assert len(f) < len(R.read(op, fmt, rnd))
        # the words are divfull's, at this attribute, by name
        bank = divfull.bank(fmt, rnd) if op == "div" else \
            divfull.bank_sqrt(fmt, rnd)
        names = divfull._NAMES_DIV if op == "div" else divfull._NAMES_SQRT
        for name, bits in f.words.items():
            assert bits == bank[names.index(name)]
    assert R.fragment(op, fmt, sf.RND_RNE) is R.fragment(op, fmt, sf.RND_RNE)


def test_a_routine_is_refused_for_an_unknown_op():
    with pytest.raises(ValueError):
        R.read("exp", FP64, sf.RND_RNE)


@pytest.mark.parametrize("plant", ["select picks the other arm",
                                   "ior taken for its first operand"])
def test_each_specialisation_rule_planted_wrong_is_red(plant, monkeypatch):
    """Each rule of step 3 changed to a wrong one - a SELECT fold that
    picks the arm the condition does not, an IOR with distinct operands
    taken for its first - makes some lane wrong on the light pools at
    fp64 under rne: the tests above see the rules, not just the code."""
    good = R.simplify

    def wrong(op, srcs, bits_of, sign_mask):
        if plant.startswith("select") and op == sf.OP_SELECT:
            c = bits_of(srcs[2])
            if c is not None:
                return srcs[1] if c & ~sign_mask else srcs[0]
        if plant.startswith("ior") and op == sf.OP_IOR:
            return srcs[0]
        return good(op, srcs, bits_of, sign_mask)
    monkeypatch.setattr(R, "simplify", wrong)
    red = 0
    for op in ("div", "sqrt"):
        f = R.specialise(R.read(op, FP64, sf.RND_RNE))
        try:
            red += len(wrong_lanes(f, lanes(op, FP64)))
        except AssertionError:
            red += 1                            # it did not even run
    assert red, f"{plant}: green on the pools"


# ---- the eight (M1's build, item 4), the eleven (M2's, item 5), the fifteen
# (M4's) --------------------------------------------------------------------
# routines.py names the fifteen, hands out the thirteen's fragments from
# mathlib.py by name, and holds every fragment to ONE statement of what it
# may be, per routine: the six's widened (the mark, RDN, RUP and the
# program's attribute, more live), the three's and the four's the same under
# live caps of their own, division's and root's C4's, not loosened.

SIX = ("exp", "expm1", "exp2", "log", "log1p", "log2")
THREE = ("sin", "cos", "tan")
NINE = SIX + THREE
ELEVEN = ("div", "sqrt", *NINE)
FOUR = ("atan", "asin", "acos", "atan2")
THIRTEEN = NINE + FOUR
FIFTEEN = ("div", "sqrt", *THIRTEEN)
FIVE = ("pow", "powr", "pown", "rootn", "compound")
N_KEYED = ("pown", "rootn", "compound")
EIGHTEEN = THIRTEEN + FIVE
TWENTY = ("div", "sqrt", *EIGHTEEN)
HAVE_MPMATH = importlib.util.find_spec("mpmath") is not None
needs_mpmath = pytest.mark.skipif(
    not HAVE_MPMATH, reason="the thirteen's fragments are built through mpmath "
    "(python/cft_golden/mathlib.py), and python has no mpmath module")
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)


def test_the_twenty_are_routines():
    """ROUTINES, the arity map, is division, root, the six, sin, cos and
    tan, atan, asin, acos and atan2, and pow, powr, pown, rootn and
    compound, in that order; cftc's ir.ROUTINES is the same set; the
    thirteen of them take one input, `a`, but atan2's, pow's and powr's two,
    `a` and `b`, as division's, and pown's, rootn's and compound's ONE (their
    integer operand is a key, N_KEYED, not an input); division's and root's
    are read from divfull's programs and the eighteen's are not (read()
    refuses them by name); and a name that is no routine, `sinh`, is refused
    by name by fragment()."""
    from cftc import ir
    assert list(R.ROUTINES) == list(TWENTY)
    assert R.ROUTINES == {"div": 2, "sqrt": 1, **{op: 1 for op in NINE},
                          "atan": 1, "asin": 1, "acos": 1, "atan2": 2,
                          "pow": 2, "powr": 2, "pown": 1, "rootn": 1,
                          "compound": 1}
    assert ir.ROUTINES == frozenset(R.ROUTINES)
    assert R.READ == ("div", "sqrt") and R.BUILT == EIGHTEEN
    assert R.N_KEYED == N_KEYED
    assert R.INPUTS == {"div": ("a", "b"), "sqrt": ("a",),
                        **{op: ("a",) for op in NINE},
                        "atan": ("a",), "asin": ("a",), "acos": ("a",),
                        "atan2": ("a", "b"), "pow": ("a", "b"),
                        "powr": ("a", "b"), "pown": ("a",), "rootn": ("a",),
                        "compound": ("a",)}
    assert all(len(R.INPUTS[op]) == R.ROUTINES[op] for op in R.ROUTINES)
    assert set(R.GOLDEN) == set(R.ROUTINES)
    for op in EIGHTEEN:
        with pytest.raises(ValueError, match="mathlib.py builds"):
            R.read(op, FP64, RNE)
    for call in (R.fragment, R.read):
        with pytest.raises(ValueError, match="'sinh' is not a routine"):
            call("sinh", FP64, RNE)


def test_the_routines_are_in_the_languages_order():
    """The one order of the routines is the language's own: R.ROUTINES is
    lang.graph.OPS filtered to the routines, and cftc's ir.ARITY, whose
    order the manifest's graph_by_op reads, is OPS itself item for item.
    Both hold only with the language that has sin, cos and tan after log2
    (M2L's), atan, asin, acos and atan2 after tan (M4L's) and pow, powr,
    pown, rootn and compound after atan2 (M3L's), so this test is red on a
    tree without them. The three that take an integer n have two operands
    in the language and ONE input here: the tuple N_KEYED is exactly the
    routines whose arity differs, and ir.ARITY's is routines.ROUTINES'
    plus one for them and equal for the other seventeen."""
    from cft_golden import lang
    from cftc import ir
    assert list(R.ROUTINES) == [op for op in lang.OPS if op in R.ROUTINES]
    assert list(ir.ARITY.items()) == list(lang.OPS.items())
    assert [op for op in lang.OPS
            if op in R.ROUTINES and lang.OPS[op] != R.ROUTINES[op]] == \
        list(R.N_KEYED)
    assert all(ir.ARITY[op] == R.ROUTINES[op] + (op in R.N_KEYED)
               for op in R.ROUTINES)


@needs_mpmath
@pytest.mark.parametrize("op", THIRTEEN)
def test_the_thirteen_are_mathlibs_fragments_by_name(op):
    """routines.fragment hands out mathlib.fragment's own object, unchanged,
    at every format and attribute, and it holds its routine's statement;
    its inputs are the routine's (R.INPUTS: ("a",), or atan2's ("a", "b"));
    the golden function is transcend's."""
    from cft_golden import mathlib as ml
    from cft_golden import transcend
    for fmt in FORMATS:
        for rnd in RND_MODES:
            f = R.fragment(op, fmt, rnd)
            assert f is ml.fragment(op, fmt, rnd)
            assert (f.op, f.fmt, f.rnd, f.inputs) == (op, fmt, rnd,
                                                      R.INPUTS[op])
            assert R.invariants(f) == []
            assert R.invariants(f) == ml.invariants(f)
    x = sf.one_bits(FP64) + 12345
    if op == "atan2":
        y = sf.one_bits(FP64) + 777
        assert R.GOLDEN[op](FP64, y, x, RDN) == transcend.compute(
            FP64, op, y, x, RDN)
    else:
        assert R.GOLDEN[op](FP64, x, RDN) == transcend.compute(
            FP64, op, x, 0, RDN)


def test_one_statement_per_routine():
    """CONTRACT and LIVE_CAP name every routine. Division's and root's are
    C4's exactly: the six flag words, never bit 7; RNE and RTZ, not the
    program's attribute; 16 live at every format (LIVE_MAX). The six's are
    the widened form: the three marked words besides; RNE, RTZ, RDN, RUP
    and the program's; 21 live at fp32 and 13 at the double word's
    formats, which mathlib.py's LIVE_CAP views by format. The three's are
    the six's contract under caps of their own, each row's four values
    pinned: 23, 26, 17 and 16 live at fp32, fp64, fp128 and fp256, which
    mathlib.py's TRIG_LIVE_CAP views (the same dicts) while its LIVE_CAP
    stays the six's. The four's are the six's contract too, each row's four
    values pinned (Logan's answer 9 of 2026-10-23): atan 25, 15, 15 and 15,
    asin and acos 25, 16, 16 and 16, atan2 31, 19, 19 and 19, at fp32,
    fp64, fp128 and fp256, which mathlib.py's INV_LIVE_CAP views."""
    assert set(R.CONTRACT) == set(R.LIVE_CAP) == set(R.ROUTINES)
    c4 = R.Contract(R.FLAG_WORDS, (RNE, RTZ), False)
    for op in ("div", "sqrt"):
        assert R.CONTRACT[op] == c4
        assert R.LIVE_CAP[op] == {f.name: R.LIVE_MAX for f in FORMATS}
    assert R.LIVE_MAX == 16
    assert all(not w & 0x80 for w in R.FLAG_WORDS) and len(R.FLAG_WORDS) == 6
    marked = R.MARKED_FLAG_WORDS - R.FLAG_WORDS
    assert marked == {sf.FLAG_INEXACT | 0x80,
                      sf.FLAG_OVERFLOW | sf.FLAG_INEXACT | 0x80,
                      sf.FLAG_UNDERFLOW | sf.FLAG_INEXACT | 0x80}
    assert all(not w & 0x60 for w in R.MARKED_FLAG_WORDS)
    six = R.Contract(R.MARKED_FLAG_WORDS, (RNE, RTZ, RDN, RUP), True)
    for op in SIX:
        assert R.CONTRACT[op] == six
        assert R.LIVE_CAP[op] == {"fp32": 21, "fp64": 13, "fp128": 13,
                                  "fp256": 13}
    for op in THREE:
        assert R.CONTRACT[op] == six
        assert R.LIVE_CAP[op] == {"fp32": 23, "fp64": 26, "fp128": 17,
                                  "fp256": 16}
    for op in FOUR:
        assert R.CONTRACT[op] == six
    assert R.LIVE_CAP["atan"] == {"fp32": 25, "fp64": 15, "fp128": 15,
                                  "fp256": 15}
    assert R.LIVE_CAP["asin"] == R.LIVE_CAP["acos"] == {
        "fp32": 25, "fp64": 16, "fp128": 16, "fp256": 16}
    assert R.LIVE_CAP["atan2"] == {"fp32": 31, "fp64": 19, "fp128": 19,
                                   "fp256": 19}
    if HAVE_MPMATH:
        from cft_golden import mathlib as ml
        assert ml.LIVE_CAP == {"fp32": 21, "fp64": 13, "fp128": 13,
                               "fp256": 13}
        assert ml.TRIG_LIVE_CAP == {op: R.LIVE_CAP[op] for op in THREE}
        assert all(ml.TRIG_LIVE_CAP[op] is R.LIVE_CAP[op] for op in THREE)
        assert ml.INV_LIVE_CAP == {op: R.LIVE_CAP[op] for op in FOUR}
        assert all(ml.INV_LIVE_CAP[op] is R.LIVE_CAP[op] for op in FOUR)
        assert ml.FLAG_WORDS == R.MARKED_FLAG_WORDS
        assert ml.flag_words is R.flag_words


@pytest.mark.parametrize("op", FIFTEEN + ("pow", "powr"))
def test_every_cap_row_names_all_four_formats(op):
    """A format left out of a row is no cap at that format, silently:
    invariants() holds a fragment to LIVE_CAP.get(op, {}).get(format) only
    if it finds one. So each row names exactly the four formats - all but
    pown's, rootn's and compound's, which name the three they are built at
    (test_the_threes_rows_name_the_three_formats_they_are_built_at)."""
    assert set(R.LIVE_CAP[op]) == {f.name for f in FORMATS}
    assert all(isinstance(v, int) and v > 0 for v in R.LIVE_CAP[op].values())


@needs_mpmath
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
@pytest.mark.parametrize("op", THREE)
def test_the_threes_caps_are_the_measured_maximum_with_no_slack(op, fmt):
    """The cap of each of the three at a format is the most values live any
    of its five fragments there keeps (MEASURED: 23, 26, 17 and 16), and
    that fragment fails a cap one under by name - so a cap row lowered by
    one, or a fragment growing past it, is red here and in
    routines.fragment()."""
    cap = R.LIVE_CAP[op][fmt.name]
    frags = [R.fragment(op, fmt, rnd) for rnd in RND_MODES]
    most = max(f.live_max() for f in frags)
    assert most == cap, (op, fmt.name, [f.live_max() for f in frags])
    f = next(f for f in frags if f.live_max() == cap)
    assert R.invariants(f) == []
    assert R.invariants(f, live_cap=cap - 1) == [
        f"{cap} values live at once, past {cap - 1}"]


@needs_mpmath
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
@pytest.mark.parametrize("op", FOUR)
def test_the_fours_caps_are_the_measured_maximum_with_no_slack(op, fmt):
    """The cap of each of the four at a format is the most values live any
    of its five fragments there keeps (MEASURED: 15, 16, 16 and 19 at fp64,
    fp128 and fp256, 25, 25, 25 and 31 at fp32), and that fragment fails a
    cap one under by name - so a cap row lowered by one, or a fragment
    growing past it, is red here and in routines.fragment()."""
    cap = R.LIVE_CAP[op][fmt.name]
    frags = [R.fragment(op, fmt, rnd) for rnd in RND_MODES]
    most = max(f.live_max() for f in frags)
    assert most == cap, (op, fmt.name, [f.live_max() for f in frags])
    f = next(f for f in frags if f.live_max() == cap)
    assert R.invariants(f) == []
    assert R.invariants(f, live_cap=cap - 1) == [
        f"{cap} values live at once, past {cap - 1}"]


def test_atan2_pow_and_powr_are_the_built_routines_of_two_inputs():
    """The inputs of the eighteen built routines: atan2's, pow's and powr's
    are ("a", "b") - atan2's y, then x, pow's and powr's x, then y, mathlib's
    own names - and the other fifteen's ("a",); the golden function of atan2
    takes (fmt, a, b, rnd) as sf.div's does and so do pow's and powr's, the
    twelve one-input ones' (fmt, a, rnd) (R.GOLDEN's shapes, checked by
    calling them, atan2 with one operand short; the three keyed by an n
    have their own third shape, test_the_three_are_keyed_by_n)."""
    two = [op for op in R.BUILT if len(R.INPUTS[op]) == 2]
    assert two == ["atan2", "pow", "powr"] and R.INPUTS["atan2"] == ("a", "b")
    assert all(R.INPUTS[op] == ("a",) for op in R.BUILT
               if op not in ("atan2", "pow", "powr"))
    one = sf.one_bits(FP64)
    twice = one + (1 << 52)            # 2: the exponent one above
    if HAVE_MPMATH:
        assert R.fragment("atan2", FP64, RNE).inputs == ("a", "b")
        assert R.GOLDEN["atan2"](FP64, one, twice, RNE) != \
            R.GOLDEN["atan2"](FP64, twice, one, RNE)
        assert len(R.GOLDEN["atan"](FP64, one, RNE)) == 2
    assert len(R.GOLDEN["div"](FP64, one, twice, RNE)) == 2
    with pytest.raises(TypeError):
        R.GOLDEN["atan2"](FP64, one, RNE)    # one operand short


@needs_mpmath
@pytest.mark.parametrize("op", FOUR)
def test_the_four_fragments_are_what_they_were_at_21b98aec(op):
    """All 80 fragments of atan, asin, acos and atan2, digest for digest as
    the tree at 21b98aec made them (routine_digests_inv.py: that commit's
    mathlib.fragment, which routines.fragment hands out unchanged), at every
    format and attribute, fp32's included. Adding the four to the routines
    moved no fragment. (The 220 of the eleven are held, at 19de866c, by
    test_the_fragments_are_what_they_were_at_19de866c.)"""
    assert set(DIGESTS_INV) == set(FOUR)
    for fmt in FORMATS:
        assert len(DIGESTS_INV[op][fmt.name]) == len(RND_MODES)
        for rnd in RND_MODES:
            got = fragment_digest(R.fragment(op, fmt, rnd))
            assert got == DIGESTS_INV[op][fmt.name][rnd], \
                f"{op} {fmt.name} {sf.RND_NAMES[rnd]}"


def _named(f, op):
    """f under another routine's name, nothing else changed."""
    return R.Fragment(op, f.fmt, f.rnd, f.inputs, f.body, f.result, f.flags,
                      f.words, f.stage)


def _with_attribute(f, rnd):
    """f with its first instruction rounding under rne made to round under
    `rnd`."""
    body = list(f.body)
    k = next(i for i, (op, r, _s) in enumerate(body)
             if op in R.ROUNDED and r == RNE)
    body[k] = (body[k][0], rnd, body[k][2])
    return R.Fragment(f.op, f.fmt, f.rnd, f.inputs, body, f.result, f.flags,
                      f.words, f.stage)


def _with_mark(f):
    """f whose flag word is ORed with a word holding the mark - a division
    that could mark a lane."""
    words = dict(f.words, MARK_PLANTED=0x80)
    body = list(f.body) + [(sf.OP_IOR, None, (f.flags, ("w", "MARK_PLANTED")))]
    return R.Fragment(f.op, f.fmt, f.rnd, f.inputs, body, f.result,
                      ("v", len(body) - 1), words, f.stage)


@pytest.mark.parametrize("op", ["div", "sqrt"])
def test_division_and_root_are_not_loosened(op):
    """A division or a root that could mark a lane, that rounds an
    instruction under RDN or RUP, or under the program's attribute (rmm
    here), fails its routine's statement by name - the attributes being
    ones the six's statement admits; and so does a fragment keeping more
    live than its cap."""
    for fmt in (FP32, FP256):
        f = R.fragment(op, fmt, RMM)
        assert R.invariants(f) == []
        marked = _with_mark(f)
        assert all(w & 0x80 for w in R.flag_words(marked))
        bad = R.invariants(marked)
        assert any("flag word's values" in s for s in bad), bad
        for rnd in (RDN, RUP, RMM):
            g = _with_attribute(f, rnd)
            bad = R.invariants(g)
            assert any("is not the routine's own" in s for s in bad), bad
            assert R.invariants(g, contract=R.MATH_CONTRACT) == []
        live = f.live_max()
        assert R.invariants(f, live_cap=live - 1) == [
            f"{live} values live at once, past {live - 1}"]


@needs_mpmath
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_the_sixs_fragment_named_a_division_fails_divisions_statement(fmt):
    """exp's fragment carries the mark among its flag word's values, rounds
    under RDN and RUP and the program's attribute, and keeps up to 21 live
    at fp32: named a division (or a root) it fails C4's statement on each
    clause that differs - and under its own name holds the six's."""
    for rnd in (RNE, RMM):
        f = R.fragment("exp", fmt, rnd)
        assert R.invariants(f) == []
        for op in ("div", "sqrt"):
            bad = R.invariants(_named(f, op))
            assert any("flag word's values" in s for s in bad), bad
            assert any("is not the routine's own" in s for s in bad), bad
            if fmt.name == "fp32":
                assert any("values live at once, past 16" in s
                           for s in bad), bad


def test_the_walk_sees_through_an_ior_and_proves_c4s_words_as_before():
    """flag_words' IOR rule (M1's question 12): on division's and root's
    flag words, which no IOR reaches, it proves exactly the sets of C4's
    walk without the rule (computed here); through an IOR of two known sets
    it is the set of their pairwise ORs, where C4's walk knew nothing."""
    def c4_walk(f):
        sets = {}

        def val(s):
            if s[0] == "w":
                return {f.words[s[1]]}
            return sets.get(s[1]) if s[0] == "v" else None
        for i, (op, _r, srcs) in enumerate(f.body):
            if op == sf.OP_SELECT:
                a, b = val(srcs[0]), val(srcs[1])
                sets[i] = a | b if a is not None and b is not None else None
            elif op == sf.OP_IAND and any(val(s) == {0} for s in srcs):
                sets[i] = {0}
            else:
                sets[i] = None
        return sets.get(f.flags[1])
    for op in ("div", "sqrt"):
        for fmt in FORMATS:
            for rnd in RND_MODES:
                f = R.fragment(op, fmt, rnd)
                assert R.flag_words(f) == c4_walk(f) <= R.FLAG_WORDS
    plain = R.fragment("div", FP64, RNE)
    f = _with_mark(plain)
    assert c4_walk(f) is None
    assert R.flag_words(f) == {w | 0x80 for w in R.flag_words(plain)}


def test_a_fragment_of_no_routine_is_refused_by_name():
    """invariants() holds a fragment to its routine's statement; a fragment
    naming no routine has none, and says so - unless a statement is given,
    as mathlib.invariants gives the six's to a study's fragment."""
    f = _named(R.fragment("div", FP64, RNE), "sinh")
    assert R.invariants(f) == ["'sinh' is not a routine, so no statement "
                               "holds it: div, sqrt, exp, expm1, exp2, log, "
                               "log1p, log2, sin, cos, tan, atan, asin, acos, "
                               "atan2, pow, powr, pown, rootn, compound"]
    assert R.invariants(f, contract=R.C4_CONTRACT) == []


def fragment_digest(f):
    """The sha256 of a fragment's content: the repr of its operation,
    format, attribute, inputs, body, result, flag word, words sorted by name
    and stage (routine_digests.py says what the table holds)."""
    return hashlib.sha256(repr((
        f.op, f.fmt.name, f.rnd, tuple(f.inputs), tuple(f.body), f.result,
        f.flags, sorted(f.words.items()), f.stage)).encode("ascii")
        ).hexdigest()


@pytest.mark.parametrize("op", ELEVEN)
def test_the_fragments_are_what_they_were_at_19de866c(op):
    """All 220 fragments, digest for digest as the tree at 19de866c made
    them - the 60 of sin, cos and tan, the six's 120 and division's and
    root's 40 - at every format and attribute, through routines.fragment,
    which hands out mathlib.fragment's own object for the nine. Adding the
    three to the routines moved no fragment."""
    if op in NINE and not HAVE_MPMATH:
        pytest.skip("the nine's fragments are built through mpmath")
    assert set(DIGESTS) == set(ELEVEN)
    for fmt in FORMATS:
        for rnd in RND_MODES:
            got = fragment_digest(R.fragment(op, fmt, rnd))
            assert got == DIGESTS[op][fmt.name][rnd], \
                f"{op} {fmt.name} {sf.RND_NAMES[rnd]}"


# ---- the twenty (M3's build, parcel M3C) -------------------------------------

N_SET = (2, 3, -2, -2 ** 63)     # the n whose fragments reach the caps


def test_the_five_have_their_cap_rows_pinned():
    """Logan's answer 8 of 2026-11-19: pow 30 at fp64, fp128 and fp256 and 32
    at fp32 (parcel M3F1's), powr 23, 22 and 22 and 29 at fp32, pown 21, rootn
    19 and compound 22 at fp64, fp128 and fp256, each row's values pinned; the
    five are under the six's contract; and the three (pown, rootn, compound)
    have NO fp32 key until parcel M3F2 - a format left out of a row is no
    cap there, silently, so the absence is itself pinned."""
    assert R.LIVE_CAP["pow"] == {"fp32": 32, "fp64": 30, "fp128": 30,
                                 "fp256": 30}
    assert R.LIVE_CAP["powr"] == {"fp32": 29, "fp64": 23, "fp128": 22,
                                  "fp256": 22}
    assert R.LIVE_CAP["pown"] == {"fp64": 21, "fp128": 21, "fp256": 21}
    assert R.LIVE_CAP["rootn"] == {"fp64": 19, "fp128": 19, "fp256": 19}
    assert R.LIVE_CAP["compound"] == {"fp64": 22, "fp128": 22, "fp256": 22}
    six = R.Contract(R.MARKED_FLAG_WORDS, (RNE, RTZ, RDN, RUP), True)
    for op in FIVE:
        assert R.CONTRACT[op] == six
    for op in N_KEYED:
        assert "fp32" not in R.LIVE_CAP[op]


@needs_mpmath
def test_mathlibs_pow_live_cap_is_a_view_of_the_five_rows():
    """mathlib.POW_LIVE_CAP is {name: routines.LIVE_CAP[name]} for the five:
    the same dicts, so that a cap is stated once - and a write to one is
    seen through the other. mathlib.py's two fp32 assignments write the
    values the rows already hold (idempotent)."""
    from cft_golden import mathlib as ml
    assert list(ml.POW_LIVE_CAP) == list(ml.POW_NAMES) == list(FIVE)
    for op in FIVE:
        assert ml.POW_LIVE_CAP[op] is R.LIVE_CAP[op]
    old = R.LIVE_CAP["pown"]["fp64"]
    try:
        R.LIVE_CAP["pown"]["fp64"] = old - 1
        assert ml.POW_LIVE_CAP["pown"]["fp64"] == old - 1
    finally:
        R.LIVE_CAP["pown"]["fp64"] = old
    assert ml.POW_LIVE_CAP["pown"]["fp64"] == old
    assert ml.POW_LIVE_CAP["pow"]["fp32"] == 32
    assert ml.POW_LIVE_CAP["powr"]["fp32"] == 29


def test_the_threes_rows_name_the_three_formats_they_are_built_at():
    """pown, rootn and compound are built at fp64, fp128 and fp256 alone
    (mathlib.fragment refuses them at fp32 by name, parcel M3F2's), so their
    rows name those three formats and no cap exists at fp32: when parcel M3F2
    builds them this test and the rows change together."""
    for op in N_KEYED:
        assert set(R.LIVE_CAP[op]) == {"fp64", "fp128", "fp256"}
        assert all(isinstance(v, int) and v > 0
                   for v in R.LIVE_CAP[op].values())


@needs_mpmath
@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
@pytest.mark.parametrize("op", FIVE)
def test_the_fives_caps_are_the_measured_maximum_with_no_slack(op, fmt):
    """The cap of each of the five at a format is the most values live any
    of its fragments there keeps over the five attributes (pown, rootn and
    compound at n = 2, 3, -2 and -2^63 as well; MEASURED at the base, f7a1ce95:
    30, 23, 21, 19 and 22 at fp64, 30, 22, 21, 19 and 22 at fp128 and fp256,
    and 32 and 29 at fp32 for pow and powr), and that fragment fails a cap
    one under by name - so a cap row lowered by one, or a fragment growing
    past it, is red here and in routines.fragment()."""
    if op in N_KEYED and fmt.name == "fp32":
        pytest.skip(f"{op} has no fp32 fragment: parcel M3F2's")
    cap = R.LIVE_CAP[op][fmt.name]
    ns = N_SET if op in N_KEYED else (None,)
    frags = [R.fragment(op, fmt, rnd, n) for rnd in RND_MODES for n in ns]
    most = max(f.live_max() for f in frags)
    assert most == cap, (op, fmt.name, sorted({f.live_max() for f in frags}))
    f = next(f for f in frags if f.live_max() == cap)
    assert R.invariants(f) == []
    assert R.invariants(f, live_cap=cap - 1) == [
        f"{cap} values live at once, past {cap - 1}"]


@needs_mpmath
@pytest.mark.parametrize("op", ("pow", "powr"))
def test_pow_and_powr_are_mathlibs_fragments_by_name(op):
    """routines.fragment hands out mathlib.fragment's own object for pow and
    powr, unchanged, at all four formats and five attributes (fp32's the
    triple word, parcel M3F1's), under the routine's statement, inputs ("a",
    "b") = (x, y); the golden function takes (fmt, a, b, rnd) as atan2's
    does, transcend's, and x first (pow(2, 1.5) is not pow(1.5, 2))."""
    from cft_golden import mathlib as ml
    from cft_golden import transcend
    for fmt in FORMATS:
        for rnd in RND_MODES:
            f = R.fragment(op, fmt, rnd)
            assert f is ml.fragment(op, fmt, rnd)
            assert (f.op, f.fmt, f.rnd, f.inputs) == (op, fmt, rnd,
                                                      ("a", "b"))
            assert R.invariants(f) == []
            assert R.invariants(f) == ml.invariants(f)
    two = sf.one_bits(FP64) + (1 << 52)            # 2
    one_and_half = sf.one_bits(FP64) + (1 << 51)   # 1.5
    assert R.GOLDEN[op](FP64, two, one_and_half, RDN) == transcend.compute(
        FP64, op, two, one_and_half, RDN)
    assert R.GOLDEN[op](FP64, two, one_and_half, RDN) != R.GOLDEN[op](
        FP64, one_and_half, two, RDN)


@needs_mpmath
@pytest.mark.parametrize("op", N_KEYED)
def test_the_three_are_keyed_by_n(op):
    """pown, rootn and compound take the integer n, required: a fragment is
    mathlib.fragment's own object FOR THAT n (a Fragment holds no n, so the
    cache's key does), two n are two fragments and one n one, a bool or a
    float is refused by name before any key is made (True, 1.0 and 1 are
    one dict key: M3G2's finding), n outside int64 is refused, fp32 is
    refused by name (parcel M3F2's), and the golden function takes
    (fmt, a, rnd, n) with n a Python int."""
    from cft_golden import mathlib as ml
    from cft_golden import transcend
    with pytest.raises(ValueError, match="needs its integer operand"):
        R.fragment(op, FP64, RNE)
    f3, f5 = R.fragment(op, FP64, RNE, 3), R.fragment(op, FP64, RNE, 5)
    assert f3 is ml.fragment(op, FP64, RNE, n=3)
    assert f5 is ml.fragment(op, FP64, RNE, n=5)
    assert f3 is not f5 and fragment_digest(f3) != fragment_digest(f5)
    assert R.fragment(op, FP64, RNE, 3) is f3
    assert not hasattr(f3, "n")
    assert (f3.op, f3.inputs) == (op, ("a",))
    assert (op, "fp64", RNE, 3) in R._HELD
    assert (op, "fp64", RNE, 5) in R._HELD
    R.fragment(op, FP64, RNE, 1)         # n = 1 held: True is the same key
    for bad in (True, 1.0, 3.0, "3", 2 ** 63, -2 ** 63 - 1):
        with pytest.raises(ValueError):
            R.fragment(op, FP64, RNE, bad)
    for edge in (-2 ** 63, 2 ** 63 - 1):
        assert R.fragment(op, FP128, RNE, edge) is ml.fragment(
            op, FP128, RNE, n=edge)
    with pytest.raises(ValueError, match="parcel M3F2's"):
        R.fragment(op, FP32, RNE, 3)
    x = sf.one_bits(FP64) + 12345
    assert R.GOLDEN[op](FP64, x, RDN, 3) == transcend.compute(
        FP64, op, x, 0, RDN, 3)
    assert R.GOLDEN[op](FP64, x, RDN, 3) != R.GOLDEN[op](FP64, x, RDN, 5)
    with pytest.raises(TypeError):
        R.GOLDEN[op](FP64, x, RDN)             # n is required


@needs_mpmath
def test_rootn_of_order_zero_and_the_small_fragments():
    """rootn(x, 0) is refused by name (it has no value for any x: the
    language refuses it before the compiler sees it), and the n = 0 and
    n = 1 fragments of the others are the small ones mathlib.py builds
    (6, 6 and 6 instructions for pown at 0, pown at 1 and rootn at 1, and 9
    and 25 for compound at 0 and 1: MEASURED at f7a1ce95, fp64, rne)."""
    with pytest.raises(ValueError, match="invalid for every x"):
        R.fragment("rootn", FP64, RNE, 0)
    assert [len(R.fragment("pown", FP64, RNE, n)) for n in (0, 1)] == [6, 6]
    assert len(R.fragment("rootn", FP64, RNE, 1)) == 6
    assert [len(R.fragment("compound", FP64, RNE, n)) for n in (0, 1)] == \
        [9, 25]


@pytest.mark.parametrize("op", [op for op in TWENTY if op not in N_KEYED])
def test_n_is_refused_by_name_for_the_other_seventeen(op):
    """A routine that is not keyed by an integer takes none: the other
    seventeen refuse n by name, before anything is built or asked."""
    with pytest.raises(ValueError, match="takes no integer operand"):
        R.fragment(op, FP64, RNE, 3)


@needs_mpmath
@pytest.mark.parametrize("key", sorted(DIGESTS_POW, key=repr), ids=repr)
def test_the_five_fragments_are_what_they_were_at_f7a1ce95(key):
    """All 205 fragments of pow, powr, pown, rootn and compound, digest for
    digest as the tree at f7a1ce95 made them (routine_digests_pow.py: that
    commit's mathlib.fragment, which routines.fragment hands out unchanged):
    pow and powr at the four formats and five attributes (40), pown at
    n = 0, 1, 3 and -2^63, rootn at 1, 3 and -2^63 and compound at 0, 1, 3
    and -2^63 at fp64, fp128 and fp256 (165). Adding the five to the
    routines moved no fragment. (The 220 of the eleven are held at
    19de866c and the 80 of the four at 21b98aec.)"""
    assert len(DIGESTS_POW) == 13
    assert sum(len(rows) for by in DIGESTS_POW.values()
               for rows in by.values()) == 205
    op, n = key
    for fmt in FORMATS:
        if fmt.name not in DIGESTS_POW[key]:
            assert n is not None and fmt.name == "fp32", (key, fmt.name)
            continue
        assert len(DIGESTS_POW[key][fmt.name]) == len(RND_MODES)
        for rnd in RND_MODES:
            got = fragment_digest(R.fragment(op, fmt, rnd, n))
            assert got == DIGESTS_POW[key][fmt.name][rnd], \
                f"{op} n={n} {fmt.name} {sf.RND_NAMES[rnd]}"
