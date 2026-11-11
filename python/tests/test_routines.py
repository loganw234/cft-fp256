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
  (routine_digests_inv.py), beside the 220 of the eleven at 19de866c.
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
HAVE_MPMATH = importlib.util.find_spec("mpmath") is not None
needs_mpmath = pytest.mark.skipif(
    not HAVE_MPMATH, reason="the thirteen's fragments are built through mpmath "
    "(python/cft_golden/mathlib.py), and python has no mpmath module")
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)


def test_the_fifteen_are_routines():
    """ROUTINES, the arity map, is division, root, the six, sin, cos and
    tan, and atan, asin, acos and atan2, in that order; cftc's ir.ROUTINES
    is the same set; the thirteen take one input, `a`, but atan2's two, `a`
    and `b`, as division's; division's and root's are read from divfull's
    programs and the thirteen's are not (read() refuses them by name); and a
    name that is no routine, `sinh`, is refused by name by fragment()."""
    from cftc import ir
    assert list(R.ROUTINES) == list(FIFTEEN)
    assert R.ROUTINES == {"div": 2, "sqrt": 1, **{op: 1 for op in NINE},
                          "atan": 1, "asin": 1, "acos": 1, "atan2": 2}
    assert ir.ROUTINES == frozenset(R.ROUTINES)
    assert R.READ == ("div", "sqrt") and R.BUILT == THIRTEEN
    assert R.INPUTS == {"div": ("a", "b"), "sqrt": ("a",),
                        **{op: ("a",) for op in NINE},
                        "atan": ("a",), "asin": ("a",), "acos": ("a",),
                        "atan2": ("a", "b")}
    assert all(len(R.INPUTS[op]) == R.ROUTINES[op] for op in R.ROUTINES)
    assert set(R.GOLDEN) == set(R.ROUTINES)
    for op in THIRTEEN:
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
    (M2L's) and atan, asin, acos and atan2 after tan (M4L's), so this test
    is red on a tree without them."""
    from cft_golden import lang
    from cftc import ir
    assert list(R.ROUTINES) == [op for op in lang.OPS if op in R.ROUTINES]
    assert list(ir.ARITY.items()) == list(lang.OPS.items())


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


@pytest.mark.parametrize("op", FIFTEEN)
def test_every_cap_row_names_all_four_formats(op):
    """A format left out of a row is no cap at that format, silently:
    invariants() holds a fragment to LIVE_CAP.get(op, {}).get(format) only
    if it finds one. So each row names exactly the four formats."""
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


def test_atan2_is_the_one_built_routine_of_two_inputs():
    """The inputs of the thirteen built routines: atan2's are ("a", "b") -
    y, then x, mathlib's own names - and the other twelve's ("a",); the
    golden function of atan2 takes (fmt, a, b, rnd) as sf.div's does and
    the others (fmt, a, rnd) (R.GOLDEN's shapes, checked by calling them,
    atan2 with one operand short)."""
    two = [op for op in R.BUILT if len(R.INPUTS[op]) == 2]
    assert two == ["atan2"] and R.INPUTS["atan2"] == ("a", "b")
    assert all(R.INPUTS[op] == ("a",) for op in R.BUILT if op != "atan2")
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
                               "atan2"]
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
