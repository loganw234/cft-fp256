# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""atan2 of python/cft_golden/mathlib.py (parcel M4G3, M4's build, wave 2) at
fp64, fp128 and fp256, the first built routine with two inputs, held to the
study's section 8 (docs/studies/M4-invtrig.md): the same ten-check shape as
test_mathlib_inv.py's atan, with the three checks atan2 needs of its own.

  pools  seq  bound  structured  range  specials  shape  audit  constants
  corner

`range` holds the tiny-quotient range's committed lanes (marked, their guesses
counted and not compared) and `corner` the committed set of the region
`tinyn` that no pool reaches (the study's 3.6, item 9: the first prescale, keyed
on d, was wrong and unmarked there, and the plant prescale_d is red in the
corner alone among the lane checks). Every check is shown failing, each leg
alone, on a doctored input; the plants' matrix is a row for each of the sixteen
plants atan2 reaches, each row listing every check; the port against the
study's model is a scratch script of the parcel's entry (nothing here imports
docs/studies/m4): the fifteen dag digests, recorded when it passed, are pinned.
Nothing here counts the functions built: this file pins atan2's names, rows and
figures only.
"""

import functools
import math
import pathlib
import subprocess
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, routines  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_inv_harness as I  # noqa: E402
import mathlib_runs as R  # noqa: E402

PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
FORMATS = I.FORMATS
RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = I.RNE, I.RTZ, I.RDN, I.RUP, I.RMM
MARK = ml.MARK
BY_NAME = I.BY_NAME
FN = "atan2"


def fid(f):
    return f.name


def rid(r):
    return sf.RND_NAMES[r]


def build_of(fmt, rnd, plant=None):
    return I.build_of(FN, fmt, rnd, plant)


def fragment_of(fmt, rnd, plant=None):
    return I.fragment_of(FN, fmt, rnd, plant)


POOL_SIZES = {"fp64": 527, "fp128": 479, "fp256": 479}
POOL_MARKED = {"fp64": 19, "fp128": 15, "fp256": 19}
# instructions, words, live (READ: costs.*.out.txt of box-out2/ for the
# instructions and words; MEASURED for the live)
SHAPE_NOW = {"fp64": (218, 62, 19), "fp128": (228, 70, 19),
             "fp256": (245, 85, 19)}
PLAN = {"fp64": (6, 12), "fp128": (6, 20), "fp256": (6, 35)}
# the dag digest of each atan2 fragment (the first 32 hex digits), equal to the
# study's model's `to_fragment()` digest at the port (docs/studies/m4/m4inv.py
# at fd37791d, the parcel's scratch script: 15 of 15, scheduled and in the
# design's order, with the lane compare)
DIGESTS = {
    "fp64/rne": "ebc92fd2d075710a068e16ce5227c483",
    "fp64/rtz": "01ce3d1a5b13a70c8d7bc6010dd0da34",
    "fp64/rdn": "698cbdce178a3f57f882edf41c251bfa",
    "fp64/rup": "264bb40353667d10115e48ed59d53f40",
    "fp64/rmm": "f7ee7ae8fda9bf601072ddc24d895408",
    "fp128/rne": "06eee5c513001a79133027f80fee8bc6",
    "fp128/rtz": "1c799bc6544c6a825d9d6878f4b272c9",
    "fp128/rdn": "1a74a9f50d738c49d1eb61a0168274f8",
    "fp128/rup": "b232dc0808e36e533c5076be0c97698c",
    "fp128/rmm": "4c8ffc672bf809bb4813aa78e5e029e5",
    "fp256/rne": "08e0683064d447dd3f9cf4d5b0c3f28b",
    "fp256/rtz": "7ebed7936800f387c740e0e0a00eb794",
    "fp256/rdn": "73ad5516154cd9aeb662afb35e573fb1",
    "fp256/rup": "c3f803be36190b84717fd6f5b693e6a2",
    "fp256/rmm": "fd39f6a70d5ac03cc52540e0cddb8805",
}
POOL_CONFIGS = [(f, r) for f in FORMATS for r in RND]
SEQ_CONFIGS = [(f, r) for f in FORMATS for r in (RNE, RTZ)]
ATAN2_PLANTS = ("signed_zero", "side_rule_off", "side_rule_sign", "range_off",
                "quadrant", "prescale_d")
# M4G1's plants that act on atan2 (tiny_gate_off and tiny_side are atan's)
CORE_PLANTS = ("table_entry", "coef", "newton_short", "sterbenz_bias",
               "zl_dropped", "sl_dropped", "pio2_low", "bound_loose",
               "mark_silenced", "two_sum_all")


def _flip(results, i, bits=0, orwith=0, andnot=0):
    out = list(results)
    b, f = out[i]
    out[i] = (b ^ bits, (f | orwith) & ~andnot)
    return out


def ids(v):
    return v.name if hasattr(v, "name") else rid(v)


# =====================================================================
# the interface and the builds
# =====================================================================

def test_atan2_is_built_with_two_inputs_y_first():
    assert "atan2" in ml._INV_BUILDERS and "atan2" in ml._INV_ROLE_CHECKS
    b = build_of(FP64, RNE)
    assert b.inputs == ("a", "b") and b.meta["fn"] == "atan2"
    f = fragment_of(FP64, RNE)
    assert f.inputs == ("a", "b") and f.op == "atan2"
    # y first: atan2(1, 0) = pi/2 and atan2(0, -1) = pi, not the other way
    y_one, x_zero = sf.one_bits(FP64), 0
    assert ml.evaluate(f, (y_one, x_zero))[0] == 0x3ff921fb54442d18
    assert ml.evaluate(f, (0, sf.one_bits(FP64, 1)))[0] == 0x400921fb54442d18
    # one operand, or a bare encoding, is refused by name
    with pytest.raises(ValueError):
        ml.evaluate(f, sf.one_bits(FP64))
    with pytest.raises(ValueError):
        ml.evaluate(f, (1, 2, 3))


def test_the_six_plants_are_assigned_and_documented():
    for name in ATAN2_PLANTS:
        assert name in ml.INV_PLANTS and len(ml.INV_PLANTS[name]) > 20


def test_plants_that_do_not_reach_atan2_are_refused_by_name():
    for plant in ("tiny_gate_off", "tiny_side"):
        with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                           f"apply to atan2 at fp64: the fault is not "
                           f"reached"):
            ml.build(FN, FP64, RNE, plant=plant)
    with pytest.raises(ValueError, match="no_such_plant"):
        ml.build(FN, FP64, RNE, plant="no_such_plant")
    with pytest.raises(ValueError, match="a fault of the double word's"):
        ml.build(FN, FP32, RNE, plant="two_sum_all")


def test_every_plant_changes_the_build():
    clean = build_of(FP64, RNE)
    for plant in CORE_PLANTS + ATAN2_PLANTS:
        b = build_of(FP64, RNE, plant)
        assert not (b.body == clean.body and b.words == clean.words
                    and b.result == clean.result
                    and b.flags == clean.flags), plant


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_plan_and_the_guard(fmt):
    b = build_of(fmt, RNE)
    assert (b.meta["K"], b.meta["D"]) == PLAN[fmt.name]


@pytest.mark.parametrize("fmt,rnd", POOL_CONFIGS, ids=ids)
def test_the_digests_are_the_models(fmt, rnd):
    f = fragment_of(fmt, rnd)
    assert ml.dag_digest(f)[:32] == DIGESTS[f"{fmt.name}/{rid(rnd)}"]
    # the design's own order is the same graph
    assert ml.dag_digest(build_of(fmt, rnd).fragment(schedule=False))[:32] \
        == DIGESTS[f"{fmt.name}/{rid(rnd)}"]


# =====================================================================
# pools
# =====================================================================

def test_the_pool_is_pairs_deduplicated_in_a_fixed_order():
    for fmt in FORMATS:
        xs = I.pool(FN, fmt)
        assert len(xs) == POOL_SIZES[fmt.name] == len(set(xs))
        assert all(isinstance(x, tuple) and len(x) == 2 for x in xs)
        assert xs == I._atan2_pool(fmt)
    # the stage's pairs come first, the brute pool's new ones last
    xs = I.pool(FN, FP64)
    tc = I.H._transcend_check()
    assert xs[:5] == tuple(tc.atan2_pairs(FP64, 64, 5))[:5]


@pytest.mark.parametrize("fmt,rnd", POOL_CONFIGS, ids=ids)
def test_pools(fmt, rnd):
    f = fragment_of(fmt, rnd)
    out, t = I.check_pools(f)
    assert out == [] and t.n == POOL_SIZES[fmt.name]
    assert t.wrong == [] and t.off == [] and t.missing == [] and t.stray == []
    assert len(t.marked) == POOL_MARKED[fmt.name]
    # every marked guess differs from transcend.py (MEASURED; INFERRED why:
    # the main path raises inexact alone where the definition's tiny result
    # raises underflow with it): a marked guess is not promised
    assert len(t.guess_wrong) == len(t.marked)


def test_the_committed_marks_are_the_same_under_every_attribute():
    for fmt in FORMATS:
        sets = []
        for rnd in RND:
            sets.append(I.pool_marks(FN, fmt.name, rid(rnd)))
        assert all(set(s) == set(sets[0]) for s in sets)
        assert len(sets[0]) == POOL_MARKED[fmt.name]
        assert set(sets[0].values()) == {"the tiny-quotient range"}
        assert set(sets[0]) == set(I._TQR_MARKED[fmt.name])


def test_the_marks_against_the_exact_rational_predicate():
    for fmt in FORMATS:
        out, band = I.check_pool_marks(fmt)
        assert out == []
        # no pool lane sits in the band where a seed's error decides: every
        # one is either inside the range or outside it (MEASURED)
        assert band == []


def test_pool_marks_legs_fail_alone():
    fmt = FP64
    one = sf.one_bits(fmt)
    # a listed lane of the wrong shape (x > 0, |y| < |x|): t = 1
    out, _ = I.check_pool_marks(fmt, listed=I._TQR_MARKED["fp64"]
                                + [(one, one)])
    assert len(out) == 1 and "not of the range's shape" in out[0]
    # a lane inside the range missing from the list
    out, _ = I.check_pool_marks(fmt, listed=I._TQR_MARKED["fp64"][1:])
    assert len(out) == 1 and "not on the committed list" in out[0]
    assert all(s.startswith("pools: ") for s in out)


def test_check_pools_legs_fail_alone_on_pairs():
    f = fragment_of(FP64, RNE)
    xs = list(I.pool(FN, FP64))
    res = [ml.evaluate(f, x) for x in xs]
    i = next(i for i, (b, fw) in enumerate(res) if not fw & MARK)
    out, t = I.check_pools(f, xs, _flip(res, i, bits=1))
    assert len(out) == 1 and out[0].startswith("pools: ") and "(0x" in out[0]
    out, t = I.check_pools(f, xs, _flip(res, i, orwith=0x20))
    # the stray bit also makes the word differ from the definition's
    assert len(out) == 2 and "other than [4:0]" in out[1]
    # a marked lane off the list, and a listed lane not marked
    out, t = I.check_pools(f, xs, marks={})
    assert len(out) == 1 and "marked off the committed list" in out[0]
    extra = {xs[i]: "x"}
    full = dict(I.pool_marks(FN, "fp64", "rne"))
    full.update(extra)
    out, t = I.check_pools(f, xs, marks=full)
    assert len(out) == 1 and "not marked" in out[0]


# =====================================================================
# seq
# =====================================================================

@pytest.mark.parametrize("fmt,rnd", SEQ_CONFIGS, ids=ids)
def test_seq(fmt, rnd):
    f = fragment_of(fmt, rnd)
    out, lanes = I.check_seq(f)
    assert out == []
    assert all(isinstance(x, tuple) for x in lanes)
    assert len(lanes) > 150
    # the compiled shape: y in r0, x in r1, the lane's byte the IEEE flags
    # with the mark in bit 7
    prog, bank = I.H.r24_program(f)
    ys, xs = I._split(lanes)
    res = I.seq.run(prog, ys, xs, bank=bank)
    for i, x in enumerate(lanes):
        bits, fw = ml.evaluate(f, x)
        assert res.lane_flags[i] == ((fw & 0x1F) | I.seq.LANE_MARKED
                                     if fw & MARK else fw)
    marked = [x for x in lanes if ml.evaluate(f, x)[1] & MARK]
    assert marked and bool(res.status & I.seq.STATUS_MARKED)
    # the range lanes and (fp64 rne) atan2(3 2^-26, 1) are among the lanes
    for _label, lane in I.RANGE_ROWS[fmt.name]:
        assert lane in lanes
    if (fmt, rnd) == (FP64, RNE):
        assert (0x3e68000000000000, 0x3ff0000000000000) in lanes
        assert ml.evaluate(f, (0x3e68000000000000, 0x3ff0000000000000))[1] \
            & MARK


def test_seq_legs_fail_alone_and_print_pairs():
    f = fragment_of(FP64, RNE)
    ok = lambda f_, x: ml.evaluate(f_, x)             # noqa: E731
    out, lanes = I.check_seq(f, evaluator=lambda f_, x: (0, 0))
    assert out and "seq.py and evaluate() differ" in out[0] and "(0x" in out[0]
    # seq.py against transcend.py, where unmarked: the fragment of a plant
    out, _ = I.check_seq(fragment_of(FP64, RNE, "quadrant"))
    assert any("differ from transcend.atan2" in s and "(0x" in s for s in out)
    # the byte: a doctored result of seq.run
    def post(res):
        res.lane_flags[0] ^= 0x01
        return res
    out, _ = I.check_seq(f, post=post)
    assert any("raised" in s and "(0x" in s for s in out)
    # FLAGS is the OR of the bytes, STATUS[6] the marked
    def post2(res):
        res.flags ^= 0x01
        return res
    out, _ = I.check_seq(f, post=post2)
    assert any("FLAGS" in s for s in out)
    def post3(res):
        res.status ^= I.seq.STATUS_MARKED
        return res
    out, _ = I.check_seq(f, post=post3)
    assert any("STATUS[6]" in s for s in out)
    # the QUIET moved past a MUL (an int says which): the byte sees it
    for k in (1, 3, True):
        out, _ = I.check_seq(f, loud=k)
        assert any(s.startswith("seq: ") and "raised" in s for s in out), k
    # a committed lane not marked in the byte
    def post4(res):
        res.lane_flags[0] &= ~I.seq.LANE_MARKED
        return res
    out, _ = I.check_seq(f, xs=[(0x3e68000000000000, 0x3ff0000000000000)],
                         post=post4)
    assert any("not marked in the lane's byte" in s for s in out)


def test_seq_lanes_are_the_pairs_the_brief_names():
    from test_transcend import _brute_pool
    for fmt in FORMATS:
        lanes = I.seq_slice(FN, fmt)
        bp = _brute_pool(fmt)[:9]
        assert {(a, b) for a in bp for b in bp} <= set(lanes)
        assert set(I.sample(FN, fmt, "random", 64, 11)) <= set(lanes)
        assert list(lanes) == sorted(lanes)
    # atan's, and the other unary functions', are unchanged
    assert not isinstance(I.seq_slice("atan", FP64)[0], tuple)


# =====================================================================
# bound
# =====================================================================

def test_the_regions_are_atan_s_and_the_diagonal():
    assert I.REGIONS_BY_FN["atan2"] == I.REGIONS + ("diag",)
    assert I.REGIONS_BY_FN["atan"] == I.REGIONS
    pts = I.placed_points(FN, FP64)
    assert list(pts) == ["edge", "big", "small", "random", "diag"]
    assert all(len(v) == 48 for v in pts.values())


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_bound(fmt):
    b = build_of(fmt, RNE)
    worst, mains = -1e9, 0
    for region, xs in I.placed_points(FN, fmt).items():
        out, (w, main, n) = I.check_bound(b, xs, region)
        assert out == [] and n == 48, (region, out)
        worst, mains = max(worst, w), mains + main
    # the largest is a SAMPLED lower bound (240 points, seed 11): MEASURED
    # 2^-6.7 (fp64), 2^-7.2 (fp128) and 2^-6.8 (fp256) of Bv, over the
    # main-path lanes (both operands finite, outside the range and the rule's
    # region); the corner is left out of the bound (in_main) and held by its
    # own check
    assert -9 < worst < -5, worst
    assert mains > 100


def test_the_bound_check_prints_pairs_and_does_not_crash(monkeypatch):
    b = build_of(FP64, RNE, "coef")
    out, _ = I.check_bound(b, I.sample(FN, FP64, "edge", 6, 11), "edge")
    assert out and "past the bound" in out[0] and "(0x" in out[0]
    # an unmarked lane that differs from transcend.py
    b = build_of(FP64, RNE)
    monkeypatch.setattr(I, "golden", lambda fmt, rnd, x, fn: (0, 0))
    out, _ = I.check_bound(b, I.sample(FN, FP64, "edge", 4, 11), "edge")
    assert any("differ from transcend.atan2" in s and "(0x" in s for s in out)


def test_in_main_leaves_the_range_and_the_rule_out():
    fmt = FP64
    one = sf.one_bits(fmt)
    assert I.in_main(FN, fmt, (one, one))
    assert not I.in_main(FN, fmt, (0, one))
    assert not I.in_main(FN, fmt, (one, sf.inf_bits(fmt)))
    assert not I.in_main(FN, fmt, (sf.qnan_bits(fmt), one))
    assert not I.in_main(FN, fmt, (sf.min_subnormal_bits(fmt), one))
    assert not I.in_main(FN, fmt, (ml._pow2(fmt, -60), one))   # the rule's
    assert I.in_main(FN, fmt, (ml._pow2(fmt, -60), sf.one_bits(fmt, 1)))


def test_the_sampler_is_a_function_of_its_seed_and_refuses_a_region():
    a = I.sample(FN, FP64, "tinyn", 20, 5)
    assert a == I.sample(FN, FP64, "tinyn", 20, 5) != I.sample(
        FN, FP64, "tinyn", 20, 6)
    with pytest.raises(ValueError, match="region 'nonesuch'"):
        I.sample(FN, FP64, "nonesuch", 1, 1)
    for mode in ("random", "edge", "big", "small", "diag", "tinyn"):
        assert all(len(x) == 2 for x in I.sample(FN, FP128, mode, 5, 1))


# =====================================================================
# structured
# =====================================================================

def test_structured():
    n = 0
    for fmt in FORMATS:
        for rnd in RND:
            f = fragment_of(fmt, rnd)
            out, lanes = I.check_structured(f)
            assert out == [], out
            n += len(lanes)
            assert all(ml.evaluate(f, x)[1] & MARK for x in lanes)
            # each lane also with y's sign flipped
            assert len(lanes) % 2 == 0
            assert all((x[0] | fmt.sign_mask,) + x[1:] in lanes
                       for x in lanes)
    assert n == 118      # fp64 46, fp128 36, fp256 36 (both signs counted)
    # counted per format and attribute (both signs): fp64 8, 10, 10, 10, 8;
    # fp128 and fp256 6, 8, 8, 8, 6
    for fmt, want in ((FP64, [8, 10, 10, 10, 8]), (FP128, [6, 8, 8, 8, 6]),
                      (FP256, [6, 8, 8, 8, 6])):
        assert [len(I.structured_lanes(FN, fmt, r)) for r in RND] == want


def test_structured_lanes_flip_y_alone():
    lanes = I.structured_lanes(FN, FP64, RNE)
    y, x = lanes[0]
    assert lanes[1] == (y | FP64.sign_mask, x)
    # a function of ONE_SIGN takes its lanes as listed
    assert I.structured_lanes("atan", FP64, RNE)[1] == \
        I.structured_lanes("atan", FP64, RNE)[0] | FP64.sign_mask


def test_structured_guess_pins():
    pins = {k: v for k, v in I.STRUCT_GUESS_WRONG.items() if k[0] == FN}
    assert {(k[1], k[2]) for k in pins} == {
        ("fp64", RTZ), ("fp64", RDN), ("fp64", RUP), ("fp128", RNE),
        ("fp128", RTZ), ("fp128", RDN), ("fp128", RUP), ("fp128", RMM)}
    for (fn, name, rnd), lanes in pins.items():
        fmt = BY_NAME[name]
        f = fragment_of(fmt, rnd)
        for x in lanes:
            bits, fw = ml.evaluate(f, x)
            assert fw & MARK
            assert (bits, fw & 0x1F) != I.golden(fmt, rnd, x, FN)
        assert all(x in I.structured_lanes(FN, fmt, rnd) for x in lanes)


def test_structured_legs_fail_alone():
    f = fragment_of(FP64, RTZ)
    # unmarked
    out, _ = I.check_structured(
        f, evaluator=lambda f_, x: (ml.evaluate(f_, x)[0], 0x10))
    assert len(out) == 1 and "not marked" in out[0] and "(0x" in out[0]
    # an unlisted wrong guess
    out, _ = I.check_structured(f, wrong={})
    assert len(out) == 1 and "guess that differs" in out[0]
    # a listed lane whose guess is right
    lane = I.structured_lanes(FN, FP64, RTZ)[0]      # a neighbour: right
    out, _ = I.check_structured(
        f, wrong={(FN, "fp64", RTZ): {lane}
                  | set(I.STRUCT_GUESS_WRONG[(FN, "fp64", RTZ)])})
    assert len(out) == 1 and "have the right one" in out[0]


# =====================================================================
# range
# =====================================================================

def test_range_rows_and_edges():
    for fmt in FORMATS:
        rows = I.RANGE_ROWS[fmt.name]
        assert len(rows) == 9 and rows[-1][0].startswith("the range's edge")
        assert [l for l, _ in rows[:-1]] == list(I._RANGE_LABELS)
        for rnd in RND:
            out, t = I.check_range(fragment_of(fmt, rnd))
            assert out == [] and t["lanes"] == t["marked"] == 9
            # the guesses are COUNTED and not compared: one of nine is right
            assert t["guess_right"] == 1
    # the edge: y = 0x380040100401003 at fp64, 2^(emin+p+2) times 1.000977
    assert I.RANGE_EDGE["fp64"] == 0x380040100401003
    r = ml._dec(FP64, I.RANGE_EDGE["fp64"] + 1) / I._tqr(FP64)
    assert 1.00097 < float(r) < 1.00098


def test_the_range_edge_is_found_on_the_fragment_by_bisection():
    for fmt in FORMATS:
        f = fragment_of(fmt, RNE)
        one = sf.one_bits(fmt)
        last = I.RANGE_EDGE[fmt.name]
        assert ml.evaluate(f, (last, one))[1] & MARK
        assert not ml.evaluate(f, (last + 1, one))[1] & MARK
        # and the first that does not mark answers equal to transcend.py,
        # as a specials row
        label, lanes = I.special_rows(FN, fmt)[-2 if fmt.name == "fp64"
                                               else -1]
        assert label.startswith("the range's edge")
        assert lanes == [(last + 1, one)]


def test_range_legs_fail_alone():
    f = fragment_of(FP64, RNE)
    one = sf.one_bits(FP64)
    out, _ = I.check_range(f, evaluator=lambda f_, x: (0, 0))
    assert len(out) == 1 and "not marked" in out[0] and "(0x" in out[0]
    out, _ = I.check_range(f, rows=I.RANGE_ROWS["fp64"] + [("t = 1", (one, one))])
    # (t = 1 is also not marked, a second finding)
    assert len(out) == 2 and "not in the range in exact rationals" in out[1]
    last = I.RANGE_EDGE["fp64"]
    out, _ = I.check_range(f, edge=last + 5)
    assert len(out) == 1 and "times the seed of 1 is not under" in out[0]
    out, _ = I.check_range(f, edge=last - 5)      # past it is still marked
    assert len(out) == 2 and "is still under" in out[0] \
        and "is marked" in out[1]
    out, _ = I.check_range(f, evaluator=lambda f_, x: (
        ml.evaluate(f_, x)[0], ml.evaluate(f_, x)[1] | MARK
        if x[1] == one else ml.evaluate(f_, x)[1]))
    assert any("past the edge" in s and s.startswith("range: ") for s in out)


# =====================================================================
# specials
# =====================================================================

def test_the_specials_rows():
    # specials.py's 76 rows less those that mark at the format (nine at fp64,
    # eight above), plus the range's edge row and, at fp64, the first j that
    # does not mark: 69 lanes at each format
    for fmt in FORMATS:
        allrows = I._all_rows_atan2(fmt)
        assert len(allrows) == 76
        rows = I.special_rows(FN, fmt)
        assert sum(len(l) for _, l in rows) == 69
        marking = I.MARKING_ROWS[fmt.name]
        assert len(marking) == (9 if fmt.name == "fp64" else 8)
        assert not {l for l, _ in rows} & set(marking)
    # both signs of every zero: 9.2.1's table is seven y against seven x
    labels = [l for l, _ in I._all_rows_atan2(FP64)]
    for y in ("+0", "-0"):
        for x in ("+0", "-0"):
            assert f"9.2.1 y {y}, x {x}" in labels


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_specials(fmt):
    for rnd in RND:
        f = fragment_of(fmt, rnd)
        out, n = I.check_specials(f)
        assert out == [], out
        assert n == 69


def test_the_rows_that_mark_are_the_rows_the_table_says():
    """MEASURED on the fragment under every attribute: exactly MARKING_ROWS
    mark (the eight of the range everywhere, and the ninth, the quotient beside
    a grid point, at fp64 under rtz, rdn and rup)."""
    for fmt in FORMATS:
        for rnd in RND:
            f = fragment_of(fmt, rnd)
            got = {l for l, lane in I._all_rows_atan2(fmt)
                   if ml.evaluate(f, lane)[1] & MARK}
            want = set(I._RANGE_LABELS)
            if fmt.name == "fp64" and rnd in (RTZ, RDN, RUP):
                want.add(I._GRID_LABEL)
            assert got == want, (fmt.name, rid(rnd))


def test_the_rule_at_the_gate_one_past_it_and_the_other_rows():
    fmt = FP64
    ga = ml.trig_gates(fmt)[1]
    labels = {l for l, _ in I.special_rows(FN, fmt)}
    for l in (f"exact quotient at the gate 2^{ga - 1}",
              f"exact quotient past the gate 2^{ga}",
              "exact quotient 2^-60 / 1", "exact quotient 3 2^-60 / 3",
              "exact quotient -2^-40 / 2", "exact quotient 2^-60 against x < 0",
              "one ulp off exact 2^-60 / 1"):
        assert l in labels, l
    # the rule decides the exact quotient: atan2(2^-60, 1) is a hair below
    # 2^-60 (one ulp under it) toward zero and the pole under rup, inexact
    f = fragment_of(fmt, RTZ)
    y, one = ml._pow2(fmt, -60), sf.one_bits(fmt)
    assert ml.evaluate(f, (y, one)) == (y - 1, sf.FLAG_INEXACT)
    assert ml.evaluate(fragment_of(fmt, RNE), (y, one)) == (y, sf.FLAG_INEXACT)


def test_the_grid_family_threshold_at_fp64():
    """atan2(2^-(p+10), 1 + j ulp): j = 1 to 11 mark under the directed three
    (the study's 3.5, j < 2^((p - G - 2)/2) = 11.3), j = 12 does not, under
    any attribute; no j marks under rne or rmm."""
    fmt = FP64
    one = sf.one_bits(fmt)
    y = ml._pow2(fmt, -(fmt.prec + 10))
    for rnd in RND:
        f = fragment_of(fmt, rnd)
        marked = [j for j in range(0, 40)
                  if ml.evaluate(f, (y, one + j))[1] & MARK]
        assert marked == (list(range(1, 12)) if rnd in (RTZ, RDN, RUP)
                          else []), (rid(rnd), marked)
    assert (y, one + 11) in [l for r, ls in I.STRUCT[FN]["fp64"]
                             for l in ls if RTZ in r]
    row = [l for lab, l in I.special_rows(FN, fmt)
           if lab.startswith("grid-point family")]
    assert row == [[(y, one + 12)]]


def test_specials_legs_fail_alone():
    f = fragment_of(FP64, RNE)
    out, n = I.check_specials(
        f, evaluator=lambda f_, x: (ml.evaluate(f_, x)[0] ^ 1,
                                    ml.evaluate(f_, x)[1]))
    assert out and all(s.startswith("specials: ") and "(0x" in s for s in out)
    out, n = I.check_specials(
        f, evaluator=lambda f_, x: (ml.evaluate(f_, x)[0],
                                    ml.evaluate(f_, x)[1] | MARK))
    assert out


# =====================================================================
# shape
# =====================================================================

@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_shape(fmt):
    builds = {(FN, r): build_of(fmt, r) for r in RND}
    assert I.check_shape(fmt, builds) == []
    f = fragment_of(fmt, RNE)
    assert (len(f), len(f.words), f.live_max()) == SHAPE_NOW[fmt.name]
    # the design's own order keeps 21, the scheduled fragment 19: the cap is
    # the measured maximum, and a cap one under fails by name
    assert build_of(fmt, RNE).fragment(schedule=False).live_max() == 21
    assert ml.INV_LIVE_CAP[FN][fmt.name] == 19
    under = ml.invariants(f, live_cap=18)
    assert under == ["19 values live at once, past 18"]
    assert ml.invariants(f) == []
    # the instructions by phase are the model's: no classify phase
    by = {}
    b = build_of(fmt, RNE)
    for i in b.live_indices():
        by[b.phase_of[i]] = by.get(b.phase_of[i], 0) + 1
    assert by == I.model_phases(FN, fmt.name)
    assert "classify" not in by and sum(by.values()) == len(f)
    assert (by["front"], by["recon"], by["special"]) == (19, 35, 32)
    # flag words {0x0, 0x1, 0x10, 0x90}, one MIN and no MAX
    assert routines.flag_words(f) == frozenset({0x0, 0x1, 0x10, 0x90})
    c = f.counts()
    assert (c.get("min", 0), c.get("max", 0)) == (1, 0)
    # fast2sums 12, two-sums 0 (the model's)
    assert (b.meta["fast_two_sum"], b.meta["two_sum"]) == (12, 0)


def test_shape_legs_fail_alone():
    fmt = FP64
    builds = {(FN, r): build_of(fmt, r) for r in RND}
    t = I.Tables(shape={(FN, "fp64"): [(219, 62, 19)] * 5})
    out = I.check_shape(fmt, builds, t)
    assert len(out) == 5 and all("219" in s for s in out[:1])
    t = I.Tables(phases=lambda fn, name: dict(I.model_phases(fn, name),
                                              front=18))
    assert all("by phase" in s for s in I.check_shape(fmt, builds, t))
    t = I.Tables(flag_words={FN: frozenset({0x0, 0x1})})
    assert all("flag word takes" in s for s in I.check_shape(fmt, builds, t))
    t = I.Tables(min_max={FN: (2, 0)})
    assert all("MIN" in s for s in I.check_shape(fmt, builds, t))
    caps = {FN: {"fp64": 20}}
    out = I.check_shape(fmt, builds, I.Tables(caps=caps))
    assert any("the cap is 20" in s for s in out)
    caps = {FN: {"fp64": 18}}
    out = I.check_shape(fmt, builds, I.Tables(caps=caps))
    assert any("the cap is 18" in s for s in out)


# =====================================================================
# audit
# =====================================================================

@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_audit(fmt):
    out, t = I.check_audit_atan2(fmt)
    assert out == [] and t["lanes"] == 214
    assert (t["premise"], t["inexact"], t["past"], t["wrong"]) == (0, 0, 0, 0)
    want = {"fp64": -7.3, "fp128": -5.1, "fp256": -5.8}[fmt.name]
    assert round(t["largest"], 1) == want


def test_sterbenz_bias_is_red_in_the_audit_and_the_audit_legs_fail_alone(
        monkeypatch):
    out, t = I.check_audit_atan2(FP64, "sterbenz_bias")
    assert [s.split(":")[0] for s in out] == ["audit"] * len(out)
    # the study's 86 premises broken, 24 inexact, 23 wrong unmarked of 214
    assert (t["premise"], t["inexact"], t["wrong"]) == (86, 24, 23)
    assert t["past"] > 0
    # the bound leg alone: coef breaks the polynomial and not the index
    out, t = I.check_audit_atan2(FP64, "coef")
    assert len(out) == 1 and "past 2^-(p+G)" in out[0]
    assert t["premise"] == t["inexact"] == 0 and "(0x" in out[0]
    # the lane leg alone: the definition's answer doctored
    monkeypatch.setattr(I, "golden", lambda fmt, rnd, x, fn: (0, 0))
    out, t = I.check_audit_atan2(FP64)
    assert len(out) == 1 and "differ from transcend.atan2" in out[0]
    assert t["wrong"] > 0


# =====================================================================
# constants
# =====================================================================

def test_constants_in_process():
    findings, lines = I.check_constants(names=(FN,))
    assert findings == []
    assert len(lines) == 1 + 3 + 3
    counts = {s.split(":")[0]: int(s.split(": ")[2].split()[0])
              for s in lines[4:]}
    assert counts == {"atan2 fp64": 345, "atan2 fp128": 385,
                      "atan2 fp256": 460}
    findings, lines = I.check_constants()
    assert findings == []
    assert {s.split(":")[0] for s in lines} >= {"atan fp64", "atan2 fp64",
                                                "atan2 fp256"}


def test_constants_as_a_program():
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--check", "--only", "inv"], cwd=PYTHON_DIR,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert sum(s.startswith("atan2 fp") for s in lines) == 3
    assert "DIFFERENCE" not in r.stdout


def test_every_role_is_asked_and_every_word_has_one():
    for fmt in FORMATS:
        b = build_of(fmt, RNE)
        want = {"PIO2H", "PIO2L", "PIH", "PIL", "PIO4H", "PIO4L", "DSUB",
                "DOK", "S3P", "DBIG", "QTR", "GATEA", "TQR", "SIDE_EPS"}
        assert want <= set(b.roles)
        findings = []
        ml._check_inv_build(b, findings)
        assert findings == []


def test_the_role_checks_use_the_ieee_fields_and_fail_on_a_wrong_word(
        monkeypatch):
    # a word doctored in the fragment is a finding by role
    def doctored(role, bits_fn):
        def builder(name, fmt, rnd):
            b = ml.build(name, fmt, rnd)
            ref = b.roles[role]
            b.words[ref[1]] = bits_fn(b.words[ref[1]])
            return b
        return builder
    for role, fn in (("DSUB", lambda w: w + (1 << 52)),
                     ("DOK", lambda w: w + 1), ("DBIG", lambda w: w + 1),
                     ("TQR", lambda w: w + (1 << 52)),
                     ("GATEA", lambda w: w + (1 << 52)),
                     ("S3P", lambda w: w - (1 << 52)),
                     ("QTR", lambda w: w + (1 << 52)),
                     ("PIL", lambda w: w ^ 1), ("PIO4H", lambda w: w + 1),
                     ("PIO4L", lambda w: w ^ 1), ("SIDE_EPS",
                                                  lambda w: w ^ (1 << 63))):
        _, findings = ml.check_inv_constants(
            builder=doctored(role, fn), formats=(FP64,), attrs=(RNE,),
            names=(FN,))
        assert any(role in s for s in findings), role


# =====================================================================
# corner
# =====================================================================

def test_the_corner_is_a_committed_set_in_the_region():
    assert {k: len(v) for k, v in I.CORNER.items()} == {
        "fp64": 101, "fp128": 40, "fp256": 40, "fp32": 100}
    for fmt in FORMATS:
        lanes = I.CORNER[fmt.name]
        assert len(set(lanes)) == len(lanes)
        assert all(I.corner_region(fmt, x) for x in lanes)
    named = [(0x812d63ff0271ce60, 0x3c3053b19c7200ec),
             (0x003871ec348e50c8, 0x2b8d56babd2a3847)]
    assert all(x in I.CORNER["fp64"] for x in named)
    # drawn once from the sampler (seed 17): the first 100 are its lanes
    assert I.CORNER["fp64"][:100] == I.sample(FN, FP64, "tinyn", 100, 17)
    assert I.CORNER["fp128"] == I.sample(FN, FP128, "tinyn", 40, 17)
    assert I.CORNER["fp256"] == I.sample(FN, FP256, "tinyn", 40, 17)


def test_the_region_predicate_can_fail():
    fmt = FP64
    one = sf.one_bits(fmt)
    assert not I.corner_region(fmt, (one, one))               # not tiny
    assert not I.corner_region(fmt, (0, one))
    assert not I.corner_region(fmt, (sf.inf_bits(fmt), one))
    assert I.corner_region(fmt, (sf.min_subnormal_bits(fmt), one))
    # one exponent under the least subnormal, and one over emin + 3p + 4
    assert not I.corner_region(fmt, (ml._pow2(fmt, fmt.emin + 3 * 53 + 5), one))
    assert I.corner_region(fmt, (ml._pow2(fmt, fmt.emin + 3 * 53 + 4), one))
    assert I._exp2_floor(Fraction(3, 4)) == -1
    assert I._exp2_floor(Fraction(4)) == 2


@pytest.mark.parametrize("fmt,rnd", [(f, r) for f in FORMATS
                                     for r in (RNE, RTZ, RDN)], ids=ids)
def test_corner(fmt, rnd):
    f = fragment_of(fmt, rnd)
    out, t = I.check_corner(f)
    assert out == [], out
    assert t["wrong"] == t["past"] == t["bv0"] == t["differ"] == 0
    assert t["lanes"] == len(I.CORNER[fmt.name]) and t["marked"] > 0
    if rnd == RNE:
        # MEASURED over the committed lanes' unmarked rne ones: the largest
        # is a sampled lower bound
        assert t["largest"] < -5


def test_prescale_d_is_red_in_the_corner_and_no_pool_reaches_it():
    for rnd in (RNE, RTZ):
        f = fragment_of(FP64, rnd, "prescale_d")
        out, t = I.check_corner(f, b=build_of(FP64, rnd, "prescale_d"))
        assert out and t["wrong"] > 0 and out[0].startswith("corner: ")
        # and the pools, structured lanes and specials stay green on it
        assert I.check_pools(f)[0] == []
        assert I.check_structured(f)[0] == []
        assert I.check_specials(f)[0] == []
    # verifier-VM4S's lane is wrong in it under rne and rmm (the study's
    # plants.py lane 0x812d63ff0271ce60 against 0x3c3053b19c7200ec is past
    # the bound by 2^26.0 and not wrong)
    lane = (0x003871ec348e50c8, 0x2b8d56babd2a3847)
    for rnd in (RNE, RMM):
        f = fragment_of(FP64, rnd, "prescale_d")
        assert ml.evaluate(f, lane) != I.golden(FP64, rnd, lane, FN)
        assert ml.evaluate(fragment_of(FP64, rnd), lane) == \
            I.golden(FP64, rnd, lane, FN)
    out, t = I.check_corner(fragment_of(FP64, RNE, "prescale_d"),
                            [(0x812d63ff0271ce60, 0x3c3053b19c7200ec)],
                            b=build_of(FP64, RNE, "prescale_d"))
    assert t["past"] == 1


def test_corner_legs_fail_alone():
    f = fragment_of(FP64, RNE)
    lanes = I.CORNER["fp64"][:30]
    one = sf.one_bits(FP64)
    # the region leg
    out, _ = I.check_corner(f, lanes + [(one, one)])
    assert len(out) == 1 and "not in the region" in out[0]
    # the lane leg
    out, t = I.check_corner(
        f, lanes, evaluator=lambda f_, x: (ml.evaluate(f_, x)[0] ^ 1,
                                           ml.evaluate(f_, x)[1]))
    assert any("differ from transcend.atan2" in s for s in out)
    assert all(s.startswith("corner: ") for s in out)
    # the bound leg: a Build whose bound is 2^40 too small (Bv underflows),
    # and a Build with the polynomial's term dropped (past the bound)
    out, t = I.check_corner(f, I.CORNER["fp64"], b=build_of(FP64, RNE,
                                                            "bound_loose"))
    assert t["bv0"] > 0 and any("underflowed to 0" in s for s in out)
    out, t = I.check_corner(f, I.CORNER["fp64"], b=build_of(FP64, RNE, "coef"))
    assert t["past"] > 0 and any("past the bound" in s for s in out)
    # the seq leg
    out, t = I.check_corner(f, lanes, seq_evaluator=lambda f_, x: (0, 0))
    assert t["differ"] > 0 and any("seq.py and evaluate()" in s for s in out)
    # seq=False leaves that leg out
    out, t = I.check_corner(f, lanes, seq_evaluator=lambda f_, x: (0, 0),
                            seq=False)
    assert out == [] and t["differ"] == 0


# =====================================================================
# the plants: each red in its checks and green in the others
# =====================================================================

CHECKS = I.CHECKS_ATAN2
# MEASURED on fp64 by this parcel: I.red_checks_atan2(plant) is the run (pools
# and seq under rne and rtz, bound over five regions of 48 points under rne,
# structured, range, specials and shape under all five attributes, audit and
# constants under rne, corner under rne and rtz). Every row lists EVERY check.
# Differences from the study's table (plants.fp64.out.txt of box-out2/): the
# study's specials excused a marked row (it flagged only wrong unmarked ones),
# ours fails a marked row, so side_rule_off, whose exact-quotient rows fall to
# the in-lane test and are marked under rtz, is red in specials and range
# beside pools; and several plants are red in seq, shape and constants, which
# the study's table has no column for.
PLANTED = [
    ("table_entry", ("pools", "seq", "bound", "specials", "audit",
                     "constants"),
     ("structured", "range", "shape", "corner")),
    ("coef", ("bound", "shape", "audit", "constants", "corner"),
     ("pools", "seq", "structured", "range", "specials")),
    ("newton_short", ("seq", "bound", "structured", "specials", "shape",
                      "audit", "corner"),
     ("pools", "range", "constants")),
    ("sterbenz_bias", ("audit", "constants"),
     ("pools", "seq", "bound", "structured", "range", "specials", "shape",
      "corner")),
    ("zl_dropped", ("bound", "shape", "audit", "corner"),
     ("pools", "seq", "structured", "range", "specials", "constants")),
    ("sl_dropped", ("pools", "seq", "bound", "structured", "specials",
                    "shape", "audit", "corner"),
     ("range", "constants")),
    ("pio2_low", ("pools", "seq", "bound", "specials", "shape", "constants",
                  "corner"),
     ("structured", "range", "audit")),
    ("bound_loose", ("seq", "bound", "structured", "constants", "corner"),
     ("pools", "range", "specials", "shape", "audit")),
    ("mark_silenced", ("seq", "structured", "shape"),
     ("pools", "bound", "range", "specials", "audit", "constants", "corner")),
    ("two_sum_all", ("shape",),
     ("pools", "seq", "bound", "structured", "range", "specials", "audit",
      "constants", "corner")),
    ("signed_zero", ("pools", "seq", "specials", "shape"),
     ("bound", "structured", "range", "audit", "constants", "corner")),
    ("side_rule_off", ("pools", "range", "specials", "shape"),
     ("seq", "bound", "structured", "audit", "constants", "corner")),
    ("side_rule_sign", ("pools", "seq", "specials", "constants"),
     ("bound", "structured", "range", "shape", "audit", "corner")),
    ("range_off", ("pools", "seq", "range", "shape", "constants", "corner"),
     ("bound", "structured", "specials", "audit")),
    ("quadrant", ("pools", "seq", "bound", "structured", "specials", "shape",
                  "corner"),
     ("range", "audit", "constants")),
    ("prescale_d", ("shape", "constants", "corner"),
     ("pools", "seq", "bound", "structured", "range", "specials", "audit")),
]


@functools.lru_cache(maxsize=None)
def _red(plant, fmt_name="fp64"):
    return I.red_checks_atan2(plant, BY_NAME[fmt_name])


def test_the_control_is_green_in_every_check():
    red = _red(None)
    assert red == {}, {k: v[:1] for k, v in red.items()}


@pytest.mark.parametrize("row", PLANTED, ids=lambda r: r[0])
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(row):
    plant, red, green = row
    got = _red(plant)
    for check in red:
        assert check in got, f"{plant}: {check} stays green"
        assert all(s.startswith(check + ": ") for s in got[check]), \
            got[check][:2]
    for check in green:
        assert check not in got, f"{plant}: {check} is red: {got[check][:2]}"


def _check_row(row):
    plant, red, green = row
    assert set(red) | set(green) == set(CHECKS), \
        (plant, set(CHECKS) - set(red) - set(green))
    assert not set(red) & set(green), plant
    assert len(red) + len(green) == len(CHECKS), plant
    assert red, plant


def test_every_plant_is_in_the_table_and_every_row_lists_every_check():
    named = [row[0] for row in PLANTED]
    assert sorted(named) == sorted(CORE_PLANTS + ATAN2_PLANTS)
    assert len(named) == len(set(named)) == 16
    for row in PLANTED:
        _check_row(row)
    rest = tuple(c for c in CHECKS if c not in ("bound", "pools"))
    for bad in (("coef", ("bound",), ("pools",)),
                ("coef", ("bound", "pools"), ("pools",) + rest),
                ("coef", (), tuple(CHECKS))):
        with pytest.raises(AssertionError):
            _check_row(bad)
    _check_row(("coef", ("bound",), ("pools",) + rest))


def test_every_check_has_a_plant_red_in_it_and_every_plant_is_red_somewhere():
    red = {c for row in PLANTED for c in row[1]}
    assert red == set(CHECKS), set(CHECKS) - red
    assert all(row[1] for row in PLANTED)
    assert CHECKS == ("pools", "seq", "bound", "structured", "range",
                      "specials", "shape", "audit", "constants", "corner")


def test_prescale_d_is_red_in_the_corner_among_the_lane_checks_alone():
    got = _red("prescale_d")
    lane_checks = {"pools", "seq", "bound", "structured", "range", "specials",
                   "audit"}
    assert set(got) & lane_checks == set()
    assert "corner" in got and "constants" in got and "shape" in got


def test_side_rule_off_is_red_in_pools():
    assert "pools" in _red("side_rule_off")


def test_sterbenz_bias_is_red_in_the_audit_and_the_constants_alone():
    assert set(_red("sterbenz_bias")) == {"audit", "constants"}


# =====================================================================
# the commands of mathlib_runs.py
# =====================================================================

def test_the_inv_commands_take_atan2_and_inv_corner_refuses_an_existing_out(
        tmp_path):
    for argv in (["inv-pools", "--fn", "atan2", "--quick", "--seq"],
                 ["inv-bound", "--fn", "atan2", "--quick"],
                 ["inv-corner", "--quick", "--seq"]):
        R.FINDINGS.clear()
        out = tmp_path / (argv[0] + ".txt")
        R.main(argv + ["--out", str(out)])
        R.OUT.close()
        R.OUT = None
        text = out.read_text(encoding="utf-8")
        assert "atan2" in text and text.rstrip().endswith("RESULT: ok"), text
        assert R.FINDINGS == []
        if argv[0] == "inv-corner":
            assert "inv-corner atan2 fp128 rne tinyn seed 101 on seq.py" \
                in text
            with pytest.raises(SystemExit, match="the file exists"):
                R.main(argv + ["--out", str(out)])
            R.OUT = None
    R.FINDINGS.clear()
    with pytest.raises(SystemExit, match="the corner is atan2's"):
        R.main(["inv-corner", "--fn", "atan"])
    R.OUT = None
    with pytest.raises(SystemExit, match="fp64, fp128, fp256 or fp32"):
        R.main(["inv-corner", "--formats", "fp16"])
