# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""exp's routine, golden-first (step 6, M1's build, parcel E1):
python/cft_golden/mathlib.py held to the study's section 8, items 1 to 5
(docs/studies/M1-exp-log.md), quick enough for the golden stage; the larger
runs are python/tests/mathlib_runs.py.

  interface   fragment() returns C4's Fragment shape, specialised, cached,
              refused by name for anything but exp; evaluate() one lane
  proved      the widened invariants of every fragment (the flag word's
              eight values, the live cap, the attributes), each shown able
              to fail; the instruction, word and live counts; the error-free
              sums; fp32's live count, which seq.py's registers cannot hold
  item 1      every lane of the transcend pools, and of the signed
              thresholds the pools lose, through each fragment at every
              format and attribute: unmarked lanes equal transcend.exp in
              bits AND flag word, a mark only on the committed structured
              list, the marked guesses counted; and on seq.py through C4's
              routines.program and routines.run; and the compiled shape
              (QUIET, body, ENDQUIET, RAISE) on seq.py
  item 2      |V - mpmath| / Bv under 1 at 4p + 200 bits, over random
              arguments with every bit random, over each path's largest |r|
              and over the weighted sampler; and VM1b's first-order budget
              under 1 at fp64, fp128 and fp256 (fp32 has none)
  item 3      the mark-rate law with the bound inflated to 2^-(p+6): the 15
              cells of fp64, fp128 and fp256 under every attribute, three
              sigma, every unmarked lane right, the marked guesses counted
  item 4      the structured family as a committed list (mathlib_family):
              equal to the theory's generation; the centres and their
              neighbours inside and outside the windows at fp64, fp128 and
              fp256; at fp32 the census (240 arguments) finds no window
  item 5      the constants' --check, in process and as a program

and, for every check, a planted fault shown red in the check it is meant
for, by name: the last section. A plant is a fault of the builder
(mathlib.PLANTS), of the budget tool (mathlib_budget.PLANTS), of an
independent derivation (TOOLS), or a mutation of a fresh build or of its
fragment (MUTATIONS); none touches a module-level cache, so every test passes
alone, in any order and under pytest-xdist. Each plant also says which checks
stay green, so that "caught by name" is not "everything is red".
"""

import pathlib
import subprocess
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, routines, seq  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.formats import FpFormat  # noqa: E402

import mathlib_budget as B  # noqa: E402
import mathlib_family as F  # noqa: E402
import mathlib_harness as H  # noqa: E402

RND = sf.RND_MODES
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
FORMATS = (FP32, FP64, FP128, FP256)
DOUBLE = (FP64, FP128, FP256)
PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]


def fid(v):
    return v.name


def rid(v):
    return sf.RND_NAMES[v]


# MEASURED (parcel E1's entry): the instructions, bank words and values live
# of each fragment, by format, in the order rne, rtz, rdn, rup, rmm. A change
# here is a change of design. The study's section 5.1 gives the same at fp128
# and fp256 and for fp32's 382 instructions (G = 40), but its fp64 counts are
# at G = 46 (178 to 181 instructions, one more than G = 44's) and its fp32
# bank words (72 to 73) are at G = 46 (G = 40's are 70 to 71).
SHAPE = {
    "fp32": ((382, 71, 34), (380, 71, 33), (380, 71, 33), (379, 70, 33),
             (382, 71, 34)),
    "fp64": ((180, 63, 23), (178, 63, 22), (178, 63, 22), (177, 62, 22),
             (180, 63, 23)),
    "fp128": ((188, 72, 23), (186, 72, 22), (186, 72, 22), (185, 71, 22),
              (188, 72, 23)),
    "fp256": ((201, 85, 23), (199, 85, 22), (199, 85, 22), (198, 84, 22),
              (201, 85, 23)),
}
# the transcend pools' sizes at the stage's default counts (MEASURED)
POOL_SIZES = {"fp32": 330, "fp64": 367, "fp128": 350, "fp256": 512}
# the study's census, through the fragments: (marked of 240 under rne and
# rmm, under the directed three); fp64 at the decided G = 44 (the lead's
# verifier's 39; the study's 23 is at G = 46), MEASURED
CENSUS_MARKS = {"fp32": (0, 0), "fp64": (16, 39), "fp128": (16, 184),
                "fp256": (16, 184)}
# the committed centres, by format: (rne and rmm, the directed three)
CENTRES = {"fp32": (0, 0), "fp64": (16, 34), "fp128": (16, 184),
           "fp256": (16, 184)}


# =====================================================================
# the interface
# =====================================================================

@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_a_fragment_is_a_specialised_c4_fragment_and_is_built_once(fmt, rnd):
    f = ml.fragment("exp", fmt, rnd)
    assert isinstance(f, routines.Fragment)
    assert (f.op, f.fmt, f.rnd, f.inputs, f.stage) == (
        "exp", fmt, rnd, ("a",), "specialised")
    assert f.result[0] == f.flags[0] == "v"
    assert ml.fragment("exp", fmt, rnd) is f
    assert H.check_shape(f, SHAPE[fmt.name][RND.index(rnd)]) == []


def test_a_name_that_is_not_built_is_refused_by_name():
    for name in ("expm1", "exp2", "log", "sqrt", ""):
        with pytest.raises(ValueError, match=repr(name)):
            ml.fragment(name, FP64, RNE)
    with pytest.raises(ValueError, match="attribute"):
        ml.build_exp(FP64, 7)
    with pytest.raises(ValueError, match="formats"):
        ml.build_exp(FpFormat("fp16", 5, 10), RNE)
    with pytest.raises(ValueError, match="no_such_plant"):
        ml.build_exp(FP64, RNE, plant="no_such_plant")
    with pytest.raises(ValueError, match="head_short.*triple-word"):
        ml.build_exp(FP32, RNE, plant="head_short")
    with pytest.raises(ValueError, match="square_term_dropped.*double-word"):
        ml.build_exp(FP64, RNE, plant="square_term_dropped")


def test_evaluate_is_one_lane_through_the_body_and_refuses_what_is_not_one():
    f = ml.fragment("exp", FP64, RNE)
    one = sf.one_bits(FP64)
    assert ml.evaluate(f, sf.zero_bits(FP64)) == (one, 0)
    bits, fw = ml.evaluate(f, one)                  # exp(1)
    assert (bits, fw) == H.golden(FP64, RNE, one) and fw == sf.FLAG_INEXACT
    for bad in (-1, 1 << 64):
        with pytest.raises(ValueError):
            ml.evaluate(f, bad)


# =====================================================================
# what is proved of every fragment
# =====================================================================

@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_every_fragment_holds_the_widened_invariants(fmt, rnd):
    f = ml.fragment("exp", fmt, rnd)
    assert ml.invariants(f) == []
    # the live count: capped at fp64 to fp256 (the double word's worst is
    # 23, so seq.py's 32 registers leave nine to the program); fp32's is
    # reported and past what 32 registers hold
    if fmt is FP32:
        assert ml.LIVE_CAP["fp32"] is None and f.live_max() > seq.NREG
    else:
        assert f.live_max() <= ml.LIVE_CAP[fmt.name] == 23 < seq.NREG


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_flag_word_takes_exactly_the_studys_eight_values(fmt, rnd):
    f = ml.fragment("exp", fmt, rnd)
    inx, unf, ovf = (sf.FLAG_INEXACT, sf.FLAG_INEXACT | sf.FLAG_UNDERFLOW,
                     sf.FLAG_OVERFLOW | sf.FLAG_INEXACT)
    want = {0, sf.FLAG_INVALID, inx, unf, ovf, inx | 0x80, unf | 0x80,
            ovf | 0x80}
    assert ml.flag_words(f) == want <= ml.FLAG_WORDS


def test_no_augmented_addition_and_the_error_free_sums_are_counted():
    """No augadd (revision 8's question 9): an ALU fragment cannot hold one,
    and its opcodes are the design's eighteen; its error-free sums are
    Fast2Sum where the exponents are ordered and TwoSum elsewhere: nine and
    one in the double word's exp, 20 and 18 in fp32's triple word."""
    for fmt in FORMATS:
        for rnd in RND:
            assert H.check_sums(ml.build_exp(fmt, rnd)) == []
    assert len(H.ALU_OPS) == 18 and H.EFT_COUNTS["fp32"] == (20, 18)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_fragment_is_specialised_and_the_unpruned_form_agrees(fmt):
    """The fragment is in C4's specialised normal form, so cftc's internal
    check will instantiate the same body; and the instrumented form (the
    unpruned body the budget reads) computes the same result and flag
    word. A fresh build is the cached fragment."""
    for rnd in (RNE, RDN):
        b = ml.build_exp(fmt, rnd)
        assert H.check_specialised(b) == []
        assert b.fragment().body == ml.fragment("exp", fmt, rnd).body


def _mutated(f, **kw):
    fields = dict(op=f.op, fmt=f.fmt, rnd=f.rnd, inputs=f.inputs, body=f.body,
                  result=f.result, flags=f.flags, words=f.words,
                  stage=f.stage)
    fields.update(kw)
    return routines.Fragment(fields["op"], fields["fmt"], fields["rnd"],
                             fields["inputs"], fields["body"],
                             fields["result"], fields["flags"],
                             fields["words"], fields["stage"])


def _bodies(f, **kw):
    """f's body with the instruction `index` replaced."""
    body = list(f.body)
    for i, new in kw.items():
        body[int(i[1:])] = new
    return tuple(body)


def invariant_plants():
    """(name, mutated fragment of exp at fp64 under rne, text its findings
    must hold): one for each clause of mathlib.invariants()."""
    f = ml.fragment("exp", FP64, RNE)
    mark_word = [k for k, v in f.words.items() if v == 0x80][0]
    ior = [i for i, (op, _r, s) in enumerate(f.body)
           if op == sf.OP_IOR and all(x[0] == "v" for x in s)]
    assert len(ior) == 1
    rounded = [i for i, (op, r, _s) in enumerate(f.body)
               if op in routines.ROUNDED and r == RNE][0]
    sel = [i for i, (op, _r, s) in enumerate(f.body)
           if op == sf.OP_SELECT and s[0][0] == "v"][0]
    op, r, s = f.body[0]
    return [
        ("the mark bit moved to bit 6", _mutated(
            f, words={**f.words, mark_word: 0x40}), "flag word's values"),
        ("the mark ORed by an add the walk cannot read", _mutated(
            f, body=_bodies(f, **{f"i{ior[0]}": (
                sf.OP_IADD, None, f.body[ior[0]][2])})),
         "flag word's values None"),
        ("an instruction rounding under a foreign attribute", _mutated(
            f, body=_bodies(f, **{f"i{rounded}": (
                f.body[rounded][0], RMM, f.body[rounded][2])})),
         "is not the routine's own"),
        ("an instruction reading only the routine's input", _mutated(
            f, body=_bodies(f, i0=(op, r, (("in", "a"), ("in", "a"))))),
         "reads only the routine's inputs"),
        ("a SELECT whose two arms are one value", _mutated(
            f, body=_bodies(f, **{f"i{sel}": (
                sf.OP_SELECT, None,
                (f.body[sel][2][0], f.body[sel][2][0], f.body[sel][2][2]))})),
         "simplifies further"),
        ("an instruction reading a value not yet defined", _mutated(
            f, body=_bodies(f, i3=(f.body[3][0], f.body[3][1],
                                   (("v", 30),) + f.body[3][2][1:]))),
         "before it is defined"),
        ("an instruction reading a word the fragment lacks", _mutated(
            f, body=_bodies(f, i1=(f.body[1][0], f.body[1][1],
                                   (("w", "NO_SUCH_WORD"),)
                                   + f.body[1][2][1:]))),
         "which the fragment does not hold"),
        ("a result that is an input", _mutated(f, result=("in", "a")),
         "is not a value of the body"),
    ]


@pytest.mark.parametrize("index", range(8))
def test_each_clause_of_the_invariants_can_fail(index):
    name, bad, text = invariant_plants()[index]
    found = ml.invariants(bad)
    assert found and any(text in s for s in found), (name, found)


def test_the_live_cap_can_fail_and_fp32_is_reported_not_capped():
    f = ml.fragment("exp", FP64, RNE)
    assert f.live_max() == 23 and ml.invariants(f, live_cap=22) == [
        "23 values live at once, past 22"]
    assert ml.invariants(ml.fragment("exp", FP64, RTZ), live_cap=22) == []
    g = ml.fragment("exp", FP32, RNE)
    assert g.live_max() == 34 and ml.invariants(g) == []
    assert any("past 32" in s for s in ml.invariants(g, live_cap=32))


@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_fp32_does_not_fit_seq_pys_registers_and_is_run_by_evaluate(rnd):
    """The triple-word exp keeps 33 or 34 values live; seq.py has 32
    registers, so routines.program refuses it by name (the plan's verifier
    measured the same). Its fit is M1's build; evaluate() runs it."""
    f = ml.fragment("exp", FP32, rnd)
    assert f.live_max() in (33, 34)
    with pytest.raises(AssertionError, match="no register for the harness"):
        routines.program(f)


# =====================================================================
# item 1: against transcend.exp
# =====================================================================

def test_the_pools_are_the_stages_pools():
    for fmt in FORMATS:
        assert len(H.pools(fmt)) == POOL_SIZES[fmt.name]


def test_the_pools_lose_their_negative_thresholds_and_the_edge_pool_has_them():
    """transcend.py's exp reaches 2^emin at the argument emin ln2 and
    underflows below its screen (emin - p) ln2, both negative. The pools
    hold their positive images (mpmath.libmp.to_man_exp returns an unsigned
    mantissa, vectors.py and transcend_check.py use it so), so the tininess
    decision at k = emin was never met; edge_pool holds both signs."""
    for fmt in DOUBLE:
        pool, edges = set(H.pools(fmt)), set(H.edge_pool(fmt))
        b = ml._enc(fmt, fmt.emin * ml._ln2())
        mirror = b & ~fmt.sign_mask
        near = range(-2, 3)
        assert b & fmt.sign_mask
        assert not {b + d for d in near} & pool
        assert {mirror + d for d in near} <= pool
        assert {b + d for d in near} <= edges
        unf = ml._screens(fmt)[1]
        assert unf & fmt.sign_mask and unf not in pool and unf in edges


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_pools_every_lane_equals_transcend_exp_or_is_marked_on_the_list(
        fmt, rnd):
    f = ml.fragment("exp", fmt, rnd)
    out, t = H.check_pools(f)
    assert out == []
    # the pools' only mark is exp(+2^-p) (rne, rmm) or exp(-2^-p), a
    # structured lane; its guess is wrong under rne (the true value is
    # above the midpoint 1 + 2^-p, the tie goes to even) and right under
    # the others: counted
    assert set(t.marked) == H.expected_pool_marks(fmt, rnd)
    assert len(t.guess_wrong) == (1 if fmt is not FP32 and rnd == RNE else 0)
    assert t.n == POOL_SIZES[fmt.name] and not t.wrong and not t.stray


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_random_lanes_equal_transcend_exp_and_none_is_marked(fmt, rnd):
    """Random arguments with every bit random, and the weighted sampler's:
    a random lane is marked with probability about 2^-(p+G), so none is."""
    f = ml.fragment("exp", fmt, rnd)
    out, t = H.check_random_lanes(f, 120, 3)
    assert out == [] and t.n >= 200 and not t.marked


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_signed_thresholds_and_cell_ends_equal_transcend_exp(fmt, rnd):
    f = ml.fragment("exp", fmt, rnd)
    out, t = H.check_edges(f)
    assert out == [] and not t.marked and t.n == len(H.edge_pool(fmt))


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
def test_on_seq_py_through_routines_program_and_run(fmt, rnd):
    f = ml.fragment("exp", fmt, rnd)
    xs = sorted(set(H.pools(fmt)) | set(H.edge_pool(fmt)))
    out, t = H.check_seq(f, xs)
    assert out == []
    assert not t.wrong and set(t.marked) <= H.structured_arguments(fmt, rnd)


@pytest.mark.parametrize("fmt,rnds", [(FP64, RND), (FP128, (RNE, RUP)),
                                      (FP256, (RNE, RDN))],
                         ids=["fp64", "fp128", "fp256"])
def test_the_compiled_shape_raises_exactly_the_operations_flags_and_marks(
        fmt, rnds):
    """QUIET, the body, ENDQUIET, RAISE of the flag word (cftc/inline.py's
    shape, R24): each lane's byte is transcend.exp's flags exactly, or on a
    marked lane the routine's own flags with bit 7; FLAGS is their OR and
    STATUS[6] says a lane was marked."""
    for rnd in rnds:
        assert H.check_r24(ml.fragment("exp", fmt, rnd)) == []


# =====================================================================
# the fixed grid's rounding, on states no argument is known to reach
# =====================================================================

def test_a_probe_can_be_replaced_and_what_follows_runs_on_the_new_state():
    b = ml.build_exp(FP64, RNE)
    x = sf.one_bits(FP64)
    res, fw, pr = b.run(x, want=("Vh", "Vl", "Ek"))
    assert b.run(x, over={})[:2] == (res, fw)
    assert b.run(x, over=pr)[:2] == (res, fw)         # its own values back
    # V_h and V_l both replaced (V_l is computed from V_h, so one alone is
    # rebuilt around): V = 1, and 2^k is 2 for this argument (k = 1)
    other = b.run(x, over={"Vh": sf.one_bits(FP64), "Vl": 0})
    assert other[0] == ml._enc(FP64, 2) != res
    b.probes["a_word"] = ("w", "ZERO")
    with pytest.raises(ValueError, match="not a value of the body"):
        b.run(x, over={"a_word": 0})


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_fixed_grids_rounding_is_right_where_round_to_odd_decides(fmt):
    """V_h exactly on a half-grid point, |V_l| = 8 Bv: the correct rounding
    of V 2^k under every attribute, unmarked, at two grids."""
    for rnd in RND:
        assert H.check_fixed_grid(ml.build_exp(fmt, rnd)) == []


def test_round_to_nearest_is_wrong_on_those_states_under_rne_and_rmm_only():
    """The plant odd_dropped builds the fixed grid's sum of V_l's share
    round-to-nearest: V_l is lost, the tie goes to even (rne) or away from
    zero (rmm), wrong for V_l > 0 under rne and for V_l < 0 under rmm, at
    both grids of each format (16 of 80 states), and right under the
    directed three. No other check sees it (the plants table)."""
    wrong = 0
    for fmt in FORMATS:
        for rnd in RND:
            found = H.check_fixed_grid(
                ml.build_exp(fmt, rnd, plant="odd_dropped"))
            if rnd == RNE:
                assert len(found) == 2 and all("V_l > 0" in s for s in found)
            elif rnd == RMM:
                assert len(found) == 2 and all("V_l < 0" in s for s in found)
            else:
                assert found == []
            assert all(s.startswith("fixed_grid:") and "marked" not in s
                       for s in found)
            wrong += len(found)
    assert wrong == 16


# =====================================================================
# item 2: the bound against mpmath, and the budget
# =====================================================================

# the largest |V - exp| / Bv over the samples below, as log2 (MEASURED:
# fp32 2^-5.0, fp64 2^-2.6, fp128 2^-6.1, fp256 2^-5.8): each must stay
# at least this far under the bound
BOUND_ROOM = {"fp32": -4.0, "fp64": -2.0, "fp128": -5.0, "fp256": -5.0}


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_bound_holds_against_mpmath_at_the_worst_points(fmt):
    b = ml.build_exp(fmt, RNE)
    for label, xs in (("random", H.random_main(fmt, 150, 1)),
                      ("placed", H.placed_exp(fmt)),
                      ("weighted", H.weighted_exp(fmt, 150, 2))):
        out, (worst, n) = H.check_bound(b, xs, label)
        assert out == [] and n >= 100, (label, out)
        assert worst < BOUND_ROOM[fmt.name], (label, worst)


# the budget's bound at G = 44 (fp64) and 46, in Bv: the study's 3.3 gives
# 0.164 at fp64; the room kept
BUDGET_ROOM = {"fp64": 0.25, "fp128": 0.1, "fp256": 0.1}


@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
def test_the_budget_states_the_bound_by_the_instructions_at_the_decided_g(fmt):
    b = ml.build_exp(fmt, RNE)
    xs = (H.uniform_unit(fmt, 30, 1) + H.weighted_exp(fmt, 30, 3)
          + H.placed_exp(fmt)[::6])
    out, s = H.check_budget(b, xs)
    assert out == []
    assert s["bound"] < BUDGET_ROOM[fmt.name], s
    assert s["rounding"] > 40 and s["lanes"] == len(xs)


def test_fp32_has_no_budget_and_says_so():
    with pytest.raises(ValueError, match="no budget"):
        B.Analyzer(ml.build_exp(FP32, RNE))


# =====================================================================
# item 3: the mark-rate law
# =====================================================================

@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
def test_the_mark_rate_law_in_its_fifteen_cells(fmt, rnd):
    """The bound inflated to 2^-(p+6), G' = 6: on 2,000 uniform main-path
    arguments (as the study's m1rate.py draws them) the marked fraction is
    within three sigma of 2^(0.53 - 6), every unmarked lane right, every
    marked guess counted - all right, as the study found."""
    out, st = H.check_rate(fmt, rnd, 2000, 7)
    assert out == [], st
    assert st["wrong"] == 0 and st["guess_wrong"] == 0
    assert abs(st["marked"] - st["expected"]) <= 3 * st["sigma"]


# =====================================================================
# item 4: the structured family
# =====================================================================

def test_the_committed_family_is_what_the_theory_generates():
    assert H.check_family_list(F.FAMILY) == []
    for fmt in FORMATS:
        for rnd in RND:
            rn = rnd in (RNE, RMM)
            assert len(F.FAMILY[fmt.name][sf.RND_NAMES[rnd]]) == \
                CENTRES[fmt.name][0 if rn else 1]


@pytest.mark.parametrize("rnd", RND, ids=rid)
@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
def test_the_windows_the_centres_and_their_neighbours_inside_and_outside(
        fmt, rnd):
    """Every committed centre of the cell, each with its neighbours at 1,
    W/8, W/4, 0.65 W ulps (inside the window, d < 0.7 by the theory: marked)
    and 1.35 W, 2 W, 8 W, 1024 W (outside: not), the census arguments that
    are not
    centres and, at fp128 and fp256, the deep arguments below the census
    (the windows' lower edge, where the bound's calibration shows): every
    lane the theory puts inside is marked, none outside, every unmarked
    lane equals transcend.exp."""
    f = ml.fragment("exp", fmt, rnd)
    cen = F.FAMILY[fmt.name][sf.RND_NAMES[rnd]]
    have = {F.argument(fmt, c) for c in cen}
    extra = [x for x in F.census(fmt) if x not in have]
    out, st = H.check_family(f, cen, extra=extra, deep=True)
    assert out == [], st
    assert st["mark"] >= len(cen) and st["lanes"] > 10 * len(cen)
    assert st["marked_mark"] == st["mark"] and st["marked_clear"] == 0
    assert st["wrong"] == 0 and st["gated"] == 0


@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_at_fp32_the_census_finds_no_window_and_the_theory_agrees(rnd):
    """Marks need an exponent from (p + G)/2 = 32 down to p = 24: none at
    G = 40. The study's 240 census arguments, through the fragment: none
    marked, every one right; the theory puts every one outside (d > 1.3) -
    and is not vacuous: at a guard of 16 it finds windows at fp32."""
    f = ml.fragment("exp", FP32, rnd)
    out, t = H.check_census_empty(f)
    assert out == [] and t.n == 240 and not t.marked and not t.wrong
    assert F.centres(FP32, rnd) == [] and F.FAMILY["fp32"][
        sf.RND_NAMES[rnd]] == []
    assert {F.classify(FP32, rnd, x) for x in F.census(FP32)} == {"clear"}
    assert any(F.classify(FP32, rnd, x, G=16) == "mark"
               for x in F.census(FP32))


@pytest.mark.parametrize("fmt", DOUBLE, ids=fid)
def test_the_census_counts_at_the_decided_g(fmt):
    """The study's 3.5 counts are at G = 46; at fp64's decided G = 44 the
    directed attributes mark 39 of 240 (the plan's verifier: 39). Every
    committed centre is among the marks."""
    for rnd in RND:
        f = ml.fragment("exp", fmt, rnd)
        assert H.check_census_counts(f, CENSUS_MARKS[fmt.name]) == []
        assert H.census_run(f).n == 240


# =====================================================================
# item 5: the constants
# =====================================================================

def test_the_constants_check_as_a_module_passes_and_can_exit_nonzero(
        monkeypatch, capsys):
    """`python -m cft_golden.mathlib --check` over the four formats: exit 0
    and what it checked; then, with exp built with a wrong table word at fp64,
    exit 1 and the difference by name."""
    done = subprocess.run([sys.executable, "-m", "cft_golden.mathlib",
                           "--check"], cwd=PYTHON_DIR, capture_output=True,
                          text=True)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "4 formats, 0 differences" in done.stdout
    for fmt in FORMATS:
        assert f"{fmt.name}: G = {ml.GUARD[fmt.name]}" in done.stdout
    real = ml.build_exp
    monkeypatch.setattr(ml, "FORMATS", (FP64,))
    monkeypatch.setattr(ml, "build_exp", lambda fmt, rnd, **kw: real(
        fmt, rnd, plant="table_entry", **kw))
    assert ml.main(["--check"]) == 1
    shown = capsys.readouterr().out
    assert "DIFFERENCE" in shown and "TH3" in shown


def test_the_derived_constants_are_what_the_independent_derivation_says():
    """Spot values read from outside the generator: ln 2 to 3,200 bits by
    its atanh series, 2^(j/8) by an integer root, against the words held:
    ln 2 as derived, the table's eight high words, the Cody-Waite sum."""
    assert H.check_spot() == []


# =====================================================================
# the plants: a fault for every check, shown caught by name
# =====================================================================

# The mutations of a fresh build or of its fragment, for the checks whose
# faults the builder cannot make because the specialised fragment and the
# instrumented form both come from one body: name -> (what it is, a function
# (build, fragment) -> (build, fragment)). Each works on the fresh build that
# run_check makes, never on the cache.

def _select_unsimplified(b, f):
    res = f.result
    body = f.body + ((sf.OP_SELECT, None, (res, res, res)),)
    return b, _mutated(f, body=body, result=("v", len(f.body)))


def _operand_swapped(b, f):
    i = [k for k, (op, _r, _s) in enumerate(f.body) if op == sf.OP_SUB][0]
    op, r, (s0, s1) = f.body[i]
    return b, _mutated(f, body=_bodies(f, **{f"i{i}": (op, r, (s1, s0))}))


def _phase_short(b, f):
    b.phase_of.pop()
    return b, f


def _probe_dropped(b, f):
    del b.probes["Bv"]
    return b, f


MUTATIONS = {
    "select_unsimplified": (
        "a SELECT of one value three times appended as the result: the "
        "same value, but the fragment is not in the specialised form",
        _select_unsimplified),
    "operand_swapped": (
        "the first SUB of the fragment with its operands swapped: the "
        "instrumented form no longer computes what the fragment does",
        _operand_swapped),
    "phase_short": (
        "an instruction without its phase in the instrumented form",
        _phase_short),
    "probe_dropped": (
        "the probe Bv, which the budget reads, missing", _probe_dropped),
}


# Faults of an independent derivation, for the spot check: name -> (what it
# is, the keyword arguments of H.check_spot that plant it).

def _ln2_wrong():
    return {"ln2": ml._ln2() + Fraction(1, 2 ** 200)}


def _enclosure_loose():
    lo, hi = ml._check_ln2()
    return {"enclosure": (lo - Fraction(1, 2 ** 100), hi)}


TOOLS = {
    "ln2_wrong": ("the generator's ln 2 off by 2^-200", _ln2_wrong),
    "enclosure_loose": ("the independent enclosure of ln 2 no tighter than "
                        "2^-100", _enclosure_loose),
}

# the checks of the table, and the harness function each is
CHECK_FUNCTIONS = {
    "pools": "check_pools", "edges": "check_edges",
    "lanes": "check_random_lanes", "bound": "check_bound",
    "budget": "check_budget", "rate": "check_rate",
    "family": "check_family", "constants": "check_constants",
    "census": "check_census_empty", "census_counts": "check_census_counts",
    "shape": "check_shape", "sums": "check_sums",
    "specialised": "check_specialised", "fixed_grid": "check_fixed_grid",
    "spot": "check_spot",
}
# the checks whose plants are tests of their own below
ELSEWHERE = {
    "check_seq": "test_the_seq_check_sees_a_faulted_evaluator",
    "check_r24": "test_the_r24_check_sees_a_flag_left_loud",
    "check_invariants": "test_each_clause_of_the_invariants_can_fail",
    "check_family_list": "test_the_census_and_family_list_checks_can_fail",
}
# the common comparison of pools, edges, lanes and seq, which has no name of
# its own in a finding: their plants are its
HELPERS = {"check_lanes"}


def run_check(check, plant, fmt, rnd):
    """The findings of the check `check` on exp built under `plant`: a fault
    of the builder (mathlib.PLANTS), of the budget tool
    (mathlib_budget.PLANTS), of an independent derivation (TOOLS) or a
    mutation of the fresh build or its fragment (MUTATIONS); None builds
    clean."""
    builder_plant = plant if plant in ml.PLANTS else None
    b = ml.build_exp(fmt, rnd, plant=builder_plant)
    f = b.fragment()
    if plant in MUTATIONS:
        b, f = MUTATIONS[plant][1](b, f)
    if check == "pools":
        return H.check_pools(f)[0]
    if check == "edges":
        return H.check_edges(f)[0]
    if check == "lanes":
        return H.check_random_lanes(f, 60, 3)[0]
    if check == "bound":
        return H.check_bound(b, H.random_main(fmt, 100, 1)
                             + H.placed_exp(fmt))[0]
    if check == "budget":
        return H.check_budget(
            b, H.weighted_exp(fmt, 20, 3) + H.placed_exp(fmt)[:30],
            plant=plant if plant in B.PLANTS else None)[0]
    if check == "family":
        cen = F.FAMILY[fmt.name][sf.RND_NAMES[rnd]]
        return H.check_family(f, [cen[0], cen[len(cen) // 2], cen[-1]],
                              deep=True)[0]
    if check == "rate":
        return H.check_rate(fmt, rnd, 1000, 7, plant=builder_plant)[0]
    if check == "constants":
        return H.check_constants(
            builder=lambda ff, rr: ml.build_exp(ff, rr, plant=builder_plant),
            formats=(fmt,), attrs=(rnd,))[0]
    if check == "census":
        return H.check_census_empty(f)[0]
    if check == "census_counts":
        return H.check_census_counts(f, CENSUS_MARKS[fmt.name])
    if check == "shape":
        return H.check_shape(f, SHAPE[fmt.name][RND.index(rnd)])
    if check == "sums":
        return H.check_sums(b, f)
    if check == "specialised":
        return H.check_specialised(b, f)
    if check == "fixed_grid":
        return H.check_fixed_grid(b)
    if check == "spot":
        kw = TOOLS[plant][1]() if plant in TOOLS else {}
        return H.check_spot(
            builder=lambda ff, rr: ml.build_exp(ff, rr, plant=builder_plant),
            formats=(fmt,), rnd=rnd, **kw)
    raise ValueError(check)


# (plant, format, attribute, the checks it must turn red, the checks that
# must stay green[, {check: text every one of its findings must hold}]).
# Each red check must return a finding that begins with its own name. The
# green ones are the study's "and only it": a fault in the reduction's low
# word or the polynomial is invisible to the pools and to the structured
# lanes and is the bound's alone. The last rows are the plants of the checks
# that look at the fragment and not at its values: its shape, its sums, its
# specialised form beside the instrumented one, the fixed grid's rounding on
# states no argument reaches, the independent constants, the budget tool.
_CLEAN = ("pools", "edges", "lanes", "bound", "constants")
PLANTED = [
    ("table_entry", FP64, RNE,
     ("pools", "edges", "lanes", "bound", "budget", "rate", "constants",
      "spot"),
     ("family", "shape", "sums", "specialised", "fixed_grid",
      "census_counts")),
    ("c1_ulp", FP64, RNE,
     ("pools", "edges", "lanes", "bound", "budget", "rate", "constants",
      "spot"),
     ("family", "shape", "sums", "specialised", "fixed_grid",
      "census_counts")),
    ("bound_loose", FP64, RNE,
     ("bound", "budget", "rate", "family", "constants", "census_counts"),
     ("pools", "edges", "shape", "sums", "specialised", "fixed_grid",
      "spot")),
    ("bound_wide", FP64, RNE, ("rate", "family", "constants", "fixed_grid"),
     ("bound", "shape", "sums", "specialised", "spot", "census_counts")),
    ("bound_half", FP128, RNE, ("family", "constants"),
     ("bound", "pools", "edges", "shape", "sums", "specialised",
      "fixed_grid", "spot", "census_counts")),
    ("bound_double", FP128, RNE, ("family", "rate", "constants"),
     ("bound", "pools", "edges", "shape", "sums", "specialised",
      "fixed_grid", "spot", "census_counts")),
    ("mark_silenced", FP64, RNE,
     ("pools", "rate", "family", "shape", "sums", "census_counts"),
     ("bound", "constants", "specialised", "fixed_grid", "spot")),
    ("mark_silenced", FP64, RDN,
     ("pools", "rate", "family", "shape", "sums", "census_counts"),
     ("bound", "lanes", "constants", "specialised", "fixed_grid", "spot")),
    ("rl_through_y", FP64, RNE, ("bound", "budget", "shape"),
     ("pools", "edges", "lanes", "rate", "family", "constants", "sums",
      "specialised", "fixed_grid", "spot", "census_counts")),
    ("c3_dropped", FP64, RNE,
     ("bound", "budget", "constants", "shape", "spot"),
     ("pools", "edges", "lanes", "rate", "family", "sums", "specialised",
      "fixed_grid", "census_counts")),
    ("tiny_gate_off", FP64, RDN, ("pools", "shape"),
     ("bound", "family", "constants", "sums", "specialised", "fixed_grid",
      "spot", "census_counts")),
    ("screen_ulp", FP64, RNE, ("pools", "edges", "constants"),
     ("bound", "family", "shape", "sums", "specialised", "fixed_grid",
      "spot", "census_counts")),
    ("head_short", FP64, RNE,
     ("bound", "budget", "constants", "shape", "sums"),
     ("pools", "edges", "rate", "family", "specialised", "fixed_grid",
      "spot", "census_counts")),
    ("tininess_klt_only", FP64, RNE, ("edges", "shape", "sums"),
     ("pools", "bound", "family", "constants", "specialised", "fixed_grid",
      "spot", "census_counts")),
    ("c0_wrong", FP64, RNE, ("edges", "constants"),
     ("pools", "bound", "family", "shape", "sums", "specialised",
      "fixed_grid", "spot", "census_counts")),
    ("square_term_dropped", FP32, RNE, ("bound", "constants", "shape"),
     ("pools", "edges", "census", "sums", "specialised", "fixed_grid",
      "spot")),
    ("bound_wide", FP32, RNE,
     ("census", "pools", "rate", "constants", "fixed_grid"),
     ("bound", "edges", "shape", "sums", "specialised", "spot")),
    ("two_sum_all", FP64, RNE, ("shape", "sums"),
     _CLEAN + ("budget", "specialised", "fixed_grid", "spot",
               "census_counts")),
    ("two_sum_all", FP32, RNE, ("shape", "sums"),
     _CLEAN + ("specialised", "fixed_grid", "spot")),
    ("abs_by_copysign", FP64, RNE, ("sums",),
     _CLEAN + ("budget", "shape", "specialised", "fixed_grid", "spot",
               "census_counts")),
    ("odd_dropped", FP64, RNE, ("fixed_grid", "shape"),
     _CLEAN + ("budget", "rate", "family", "sums", "specialised", "spot",
               "census_counts")),
    ("odd_dropped", FP32, RNE, ("fixed_grid", "shape"),
     _CLEAN + ("sums", "specialised", "spot", "census")),
    ("capacities_dropped", FP128, RNE, ("budget",), ("bound", "pools"),
     {"budget": "is past the budget's bound"}),
    ("ln2_wrong", FP64, RNE, ("spot",), ("constants", "pools")),
    ("enclosure_loose", FP64, RNE, ("spot",), ("constants", "pools")),
    ("select_unsimplified", FP64, RNE, ("specialised", "shape"),
     ("pools", "sums")),
    ("operand_swapped", FP64, RNE, ("specialised", "pools"), ("sums",)),
    ("phase_short", FP64, RNE, ("specialised",), ("pools", "sums", "shape")),
    ("probe_dropped", FP64, RNE, ("specialised",),
     ("pools", "sums", "shape")),
]


def test_every_plant_is_in_the_table_and_every_row_names_a_plant():
    named = {row[0] for row in PLANTED}
    kinds = (set(ml.PLANTS), set(B.PLANTS), set(TOOLS), set(MUTATIONS))
    assert named == set().union(*kinds)
    assert sum(len(k) for k in kinds) == len(named)     # one name, one kind
    for plant, (families, text) in ml.PLANTS.items():
        assert families and text
    for row in PLANTED:
        assert set(row[3]) | set(row[4]) <= set(CHECK_FUNCTIONS), row[:3]
        assert not set(row[3]) & set(row[4]), row[:3]


def test_every_check_of_the_harness_has_a_plant_that_turns_it_red():
    """No check without a fault shown caught by name: every check function
    of the harness is a column of the table with a plant red in it, or has
    a test of its own among those below."""
    assert {n for n in dir(H) if n.startswith("check_")} == \
        set(CHECK_FUNCTIONS.values()) | set(ELSEWHERE) | HELPERS
    red = {c for row in PLANTED for c in row[3]}
    assert set(CHECK_FUNCTIONS) <= red
    for name in ELSEWHERE.values():
        assert callable(globals()[name]), name


@pytest.mark.parametrize(
    "row", PLANTED, ids=lambda r: f"{r[0]}-{r[1].name}-{sf.RND_NAMES[r[2]]}")
def test_each_planted_fault_is_caught_by_name_and_the_others_stay_green(row):
    plant, fmt, rnd, red, green, *rest = row
    says = rest[0] if rest else {}
    for check in red:
        found = run_check(check, plant, fmt, rnd)
        assert found and all(s.startswith(check + ":") for s in found), \
            (plant, check, found)
        if check in says:
            assert all(says[check] in s for s in found), (plant, check, found)
    for check in green:
        assert run_check(check, plant, fmt, rnd) == [], (plant, check)


def test_a_clean_build_is_green_in_every_check_the_plants_use():
    for check in ("pools", "edges", "lanes", "bound", "budget", "rate",
                  "constants", "family", "census_counts", "shape", "sums",
                  "specialised", "fixed_grid", "spot"):
        assert run_check(check, None, FP64, RNE) == [], check
    assert run_check("census", None, FP32, RNE) == []
    for check in ("shape", "sums", "specialised", "fixed_grid", "spot"):
        assert run_check(check, None, FP32, RNE) == [], check


def test_a_mark_off_the_structured_list_fails_the_pools():
    """A planted mark OFF the list is test 1's rule 7: the tiny gate removed
    marks the subnormal and tiny arguments under the directed attributes
    (not under rne, where V = 1 + Z cannot straddle a midpoint of 1): at
    fp64 under rdn it marks lanes that are not on the structured list."""
    f = ml.build_exp(FP64, RDN, plant="tiny_gate_off").fragment()
    out, t = H.check_pools(f)
    assert len(out) == 1 and "marked off the structured list" in out[0]
    assert len(t.marked) > 1 and not t.wrong
    g = ml.build_exp(FP64, RNE, plant="tiny_gate_off").fragment()
    assert H.check_pools(g)[0] == []


def test_the_seq_check_sees_a_faulted_evaluator():
    f = ml.fragment("exp", FP64, RDN)
    forced = routines.Fragment(
        f.op, f.fmt, f.rnd, f.inputs,
        tuple((op, RNE if r is not None else None, s)
              for op, r, s in f.body), f.result, f.flags, f.words, f.stage)

    def ignores_the_attributes(frag, x):
        return ml.evaluate(forced, x)
    out, _t = H.check_seq(f, evaluator=ignores_the_attributes)
    assert out and out[0].startswith("seq:") and "differ" in out[0]
    assert H.check_seq(f)[0] == []


def test_the_r24_check_sees_a_flag_left_loud():
    """The first instruction that can raise a flag left outside the quiet
    region: the lanes whose argument makes it overflow carry a flag the
    operation does not raise."""
    f = ml.fragment("exp", FP64, RNE)
    found = H.check_r24(f, loud=True)
    assert found and all(s.startswith("r24:") for s in found)
    assert H.check_r24(f) == []


def test_the_census_and_family_list_checks_can_fail():
    f = ml.build_exp(FP32, RUP, plant="bound_wide").fragment()
    found, t = H.check_census_empty(f)
    assert found and found[0].startswith("census:") and t.marked
    tampered = {k: {r: list(v) for r, v in per.items()}
                for k, per in F.FAMILY.items()}
    tampered["fp64"]["rne"].pop()
    tampered["fp128"]["rtz"].append((1, 1))
    found = H.check_family_list(tampered)
    assert len(found) == 2 and all(s.startswith("family:") for s in found)
    assert H.check_family_list(F.FAMILY) == []
