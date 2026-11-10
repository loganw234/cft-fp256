# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The first-order budget of atan, asin, acos and atan2 (parcel M4G4,
python/tests/mathlib_inv_budget.py), held to the study's model: the
`reference` leg at the model's own lanes in every cell of 3.2's table (57
cells at fp64, fp128 and fp256); every leg failing alone on a doctored
summary; the head leg red under the tool plant that brings 3.6, item 3 back
and green on the control; the tool plants' matrix, each row listing every leg;
the thresholds of the families held to the study's cells.

Nothing here imports docs/studies/m4: the model's digits are the literals
MODEL_FIGURES of the tool (the model run apart on the model's lanes).
"""

import functools
import pathlib
import sys

import mpmath
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_inv_budget as IB  # noqa: E402
import mathlib_inv_family as IF  # noqa: E402
import mathlib_inv_harness as I  # noqa: E402

FORMATS = I.FORMATS
FUNCS = ("atan", "asin", "acos", "atan2")
CELLS = sorted(IB.MODEL_FIGURES)


@functools.lru_cache(maxsize=None)
def _build(fn, fmt_name, rnd=I.RNE):
    return ml.build(fn, I.BY_NAME[fmt_name], rnd)


@functools.lru_cache(maxsize=None)
def _run(fn, fmt_name, region, plant=None):
    fmt = I.BY_NAME[fmt_name]
    lanes, ex = IB.model_expect(fmt_name, fn, region)
    xs = IB.model_lanes(fmt, fn, region)
    attrs = {r: _build(fn, fmt_name, r) for r in sf.RND_MODES}
    out, s = IB.check_budget(_build(fn, fmt_name), xs, region, plant=plant,
                             expect=ex, attrs=attrs)
    return out, s, lanes


def legs(findings):
    return {IB.leg_of(f) for f in findings}


def test_the_table_is_the_studys_57_cells():
    assert len(CELLS) == 57
    assert {(f, fn) for f, fn, _r in CELLS} == {
        (f.name, fn) for f in FORMATS for fn in FUNCS}
    for fn in FUNCS:
        want = set(I.REGIONS_BY_FN[fn])
        assert {r for f, n, r in CELLS if n == fn and f == "fp64"} == want


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_every_cell_equals_the_models_digits_at_the_models_lanes(fmt):
    for fn in FUNCS:
        for region in I.REGIONS_BY_FN[fn]:
            out, s, lanes = _run(fn, fmt.name, region)
            # six or sixteen lanes of the region's far end can reach no
            # rounding at all (every capacity 0 in the model's own digits):
            # the reach leg says so, and nothing else is red
            reached = IB.MODEL_FIGURES[(fmt.name, fn, region)][3] > 0
            assert legs(out) == (set() if reached else {"reach"}),                 (fn, fmt.name, region, out[:1])
            assert s["lanes"] == lanes, (fn, fmt.name, region)
            assert s["bound"] < 1 and s["Emax"] <= s["bound"] * 1.001


def test_the_models_figures_are_not_the_tools_own_output():
    # the literals are four significant digits of a run of the model apart:
    # a doctored one is refused by the reference leg alone
    lanes, ex = IB.model_expect("fp64", "atan", "edge")
    fmt = I.FP64
    xs = IB.model_lanes(fmt, "atan", "edge")
    for key in ("rounding", "Mmax", "S_cap", "bound", "resid"):
        bad = dict(ex)
        bad[key] = bad[key] + 1 if key == "rounding" else bad[key] * 1.01
        out, _s = IB.check_budget(_build("atan", "fp64"), xs, "edge",
                                  expect=bad)
        assert legs(out) == {"reference"}, (key, out)


def _clean():
    out, s, _lanes = _run("atan", "fp64", "edge")
    assert out == []
    return dict(s)


def test_each_leg_fails_alone_on_a_doctored_summary():
    s0 = _clean()
    where = "budget: atan fp64 rne edge"
    assert IB.judge(s0, where, None, head=True) == []

    def only(leg, **kw):
        s = dict(s0)
        s.update(kw)
        found = IB.judge(s, where, None, head=True)
        assert found and legs(found) == {leg}, (leg, found)
        assert all(f.startswith("budget: ") for f in found)
    only("bound", bound=1.2, Mmax=1.1)
    only("lane", Emax=s0["bound"] * 1.5)
    only("residual", resid=1 - s0["bound"] + 0.01)
    only("reach", rounding=0)
    only("reach", S_obs=0.0)
    only("head", by_phase=dict(s0["by_phase"], head=(1e-3, 0.0)))
    only("head", resid=0.0)
    # the head leg is the edge region's: off elsewhere unless asked
    s = dict(s0, resid=0.0)
    assert IB.judge(s, where, None, head=False) == []
    # the reference leg
    bad = {"rounding": s0["rounding"], "Mmax": s0["Mmax"] * 2}
    found = IB.judge(s0, where, bad)
    assert legs(found) == {"reference"}
    # no lane on the main path
    assert IB.judge(dict(s0, lanes=0), where)[0].endswith(
        "no lane of the sample is on the main path")


def test_the_attributes_leg_fails_alone_on_a_directed_rounding_before_v():
    fn, fmt = "atan", I.FP64
    xs = IB.model_lanes(fmt, fn, "edge") + I.sample(fn, fmt, "random", 120, 3)
    attrs = {r: _build(fn, "fp64", r) for r in sf.RND_MODES}
    found, (n, differ) = IB.check_attributes(attrs, xs, "edge")
    assert found == [] and differ == 0 and n == len(xs)
    bad = dict(attrs)
    bad[I.RTZ] = IB.with_directed_before_v(attrs[I.RTZ])
    found, (n, differ) = IB.check_attributes(bad, xs, "edge")
    assert differ > 0 and legs(found) == {"attributes"}
    with pytest.raises(ValueError, match="does not apply under rne"):
        IB.with_directed_before_v(attrs[I.RNE])


def test_the_head_leg_is_red_under_the_sign_select_and_green_on_the_control():
    # the study's 3.6, item 3: a SELECT between 0 and SIGN taken as a value
    # makes the IXOR that applies sigma integer data and freezes every
    # rounding before the reconstruction into M. The tells were a residual of
    # exactly 0 and zero capacity in every phase but the reconstruction.
    for fn in ("atan", "atan2"):
        out, s, _l = _run(fn, "fp64", "edge")
        assert out == []
        assert s["resid"] != 0.0
        assert s["by_phase"]["head"][1] > 0
        bad, sb, _l = _run(fn, "fp64", "edge", "sign_select_as_value")
        assert "head" in legs(bad), bad
        assert sb["by_phase"]["head"][1] == 0.0 and sb["resid"] == 0.0
        # the cause: the sweep's capacities sit in the reconstruction alone
        live = {ph for ph, (_o, c) in sb["by_phase"].items() if c > 0}
        assert live <= {"recon"}, live


# (plant, the legs it is red in, the legs it is green in), measured on the
# edge region at the model's lanes at fp64 (atan2 and atan; asin the same).
LEGS = IB.LEGS
PLANTED = [
    ("sign_select_as_value", ("head", "reference"),
     ("bound", "lane", "residual", "reach", "attributes")),
    ("seed_source_frozen", ("reference",),
     ("bound", "lane", "residual", "reach", "head", "attributes")),
    ("negation_as_data", ("reach", "head", "reference"),
     ("bound", "lane", "residual", "attributes")),
    ("capacities_dropped", ("lane", "head", "reference"),
     ("bound", "residual", "reach", "attributes")),
    ("inputs_swapped", ("bound", "reference"),
     ("lane", "residual", "reach", "head", "attributes")),
]


def _check_row(row):
    plant, red, green = row
    assert set(red) | set(green) == set(LEGS), (plant, set(LEGS) - set(red)
                                                - set(green))
    assert not set(red) & set(green), plant
    assert len(red) + len(green) == len(LEGS), plant
    assert red, plant


def test_every_tool_plant_is_in_the_matrix_and_every_row_lists_every_leg():
    assert [r[0] for r in PLANTED] == list(IB.TOOL_PLANTS)
    for row in PLANTED:
        _check_row(row)
    # the row check refuses a row that omits a leg, names one red and green,
    # or is red in nothing
    rest = tuple(x for x in LEGS if x not in ("bound", "head"))
    for bad in (("p", ("bound",), ("head",)),
                ("p", ("bound", "head"), ("head",) + rest),
                ("p", (), tuple(LEGS))):
        with pytest.raises(AssertionError):
            _check_row(bad)
    _check_row(("p", ("bound",), ("head",) + rest))
    # every leg but the residual and the attributes' is red under a plant of
    # the tool; those two are shown red on doctored inputs above
    red = {x for row in PLANTED for x in row[1]}
    assert red == set(LEGS) - {"residual", "attributes"}


@pytest.mark.parametrize("row", PLANTED, ids=lambda r: r[0])
def test_each_tool_plant_is_red_in_its_legs_and_green_in_the_others(row):
    plant, red, green = row
    fn = "atan2" if plant == "inputs_swapped" else "atan"
    out, _s, _l = _run(fn, "fp64", "edge", plant)
    got = legs(out)
    assert got == set(red), (plant, got, [f[:90] for f in out])
    assert not got & set(green)
    # the control is green in every leg
    assert _run(fn, "fp64", "edge")[0] == []


def test_a_plant_that_cannot_act_is_refused_by_name():
    with pytest.raises(ValueError, match="does not apply.*one input"):
        IB.InvAnalyzer(_build("asin", "fp64"), "inputs_swapped")
    with pytest.raises(ValueError, match="unknown tool plant"):
        IB.InvAnalyzer(_build("atan", "fp64"), "nonesuch")
    with pytest.raises(ValueError, match="inverse functions"):
        IB.InvAnalyzer(ml.build("exp", I.FP64, I.RNE))


def test_two_inputs_are_read_in_build_order_and_swapping_them_fails():
    b = _build("atan2", "fp64")
    assert b.inputs == ("a", "b")
    an = IB.InvAnalyzer(b)
    y, x = I.sample("atan2", I.FP64, "random", 4, 5)[0]
    L = an.analyze((y, x))
    assert L.xa == (y, x)
    _res, _fl, pr = b.run((y, x), ("Vh", "Vl"))
    with mpmath.workprec(an.prec):
        assert L.V == IB.B.to_mp(ml._dec(I.FP64, pr["Vh"])) + IB.B.to_mp(
            ml._dec(I.FP64, pr["Vl"]))


def test_the_cell_figure_is_the_largest_of_its_three_and_says_which():
    s = {"bound": 0.01, "resid": 0.002}
    assert IB.cell_figure(s, 0.005) == (0.012, "the budget's bound with its "
                                                  "residual")
    assert IB.cell_figure(s, 0.02) == (0.02, "the sampled worst")
    s = {"bound": 0.01, "resid": 0.0}
    assert IB.cell_figure(s, 0.005)[1] == "the budget's bound with its " \
        "residual" or IB.cell_figure(s, 0.005)[1] == "the budget's bound"
    fmt = I.FP64
    xs = IB.model_lanes(fmt, "atan", "edge")
    w = IB.sampled_worst(_build("atan", "fp64"), xs)
    out, s2, _l = _run("atan", "fp64", "edge")
    assert 0 < w <= s2["bound"] * 1.001      # the sampled worst is below it


# the study's cells (bound_table.py's output, READ, the largest cell of each
# function and format over its regions, in Bv)
STUDY_MAX = {
    ("acos", "fp128"): 0.03026, ("asin", "fp128"): 0.03038,
    ("atan", "fp128"): 0.03027, ("atan2", "fp128"): 0.03027,
    ("acos", "fp256"): 0.02279, ("asin", "fp256"): 0.0228,
    ("atan", "fp256"): 0.0228, ("atan2", "fp256"): 0.02278,
    ("acos", "fp64"): 0.06558, ("asin", "fp64"): 0.07298,
    ("atan", "fp64"): 0.03324, ("atan2", "fp64"): 0.03761,
}


def test_the_thresholds_b_are_the_studys_cells_rounded_up_to_two_figures():
    import math
    assert set(IF.THRESHOLD_B) == set(STUDY_MAX)
    for key, m in STUDY_MAX.items():
        up = math.ceil(m * 1000) / 1000                 # two figures here
        assert IF.THRESHOLD_B[key] >= up - 1e-12, key
        assert IF.THRESHOLD_B[key] < 0.1, key
    # and the tool's budgets at the model's lanes are under them
    for (f, fn, region) in CELLS:
        assert IB.MODEL_FIGURES[(f, fn, region)][4] <= IF.THRESHOLD_B[
            (fn, f)], (f, fn, region)


def test_a_lanes_own_figure_is_under_its_samples_bound_and_none_off_path():
    # b(x) = this lane's method error plus the capacities of the instructions
    # that round on it: under the bound of any sample that holds the lane
    for fn, region in (("atan", "edge"), ("atan2", "edge"),
                       ("acos", "big")):
        b = _build(fn, "fp64")
        _out, s, _l = _run(fn, "fp64", region)
        xs = IB.model_lanes(I.FP64, fn, region)
        figs = [IB.lane_figure(b, x) for x in xs]
        assert all(f is not None and f >= 0 for f in figs)
        assert max(figs) <= s["bound"] * (1 + 1e-12), (fn, max(figs))
        assert max(figs) > 0
    # a gated lane has none
    assert IB.lane_figure(_build("atan", "fp64"), 0) is None
    assert IB.lane_figure(_build("atan2", "fp64"), (0, 0)) is None
    # an instruction that does not round on the lane adds nothing, whatever
    # its capacity: the tiny centre's figure is far under the cell's
    x = 0x3e68000000000000
    assert IB.lane_figure(_build("atan", "fp64"), x) < 1e-3
