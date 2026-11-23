# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The first-order budget of pow, powr, pown, rootn and compound and the
mark-rate law (parcel M3G3): python/tests/mathlib_pow_budget.py and
mathlib_pow_rate.py, and the budget's two plants in their table of their own.

What each section holds:

  the plants        _POW_BUDGET_PLANTS is a table of its own: POW_PLANTS stays
                    the 28 keys M3G1's and M3G2's tests read, build accepts a
                    key of either, the two plants are refused by name where
                    B1 and B2 are 0 (fp128, fp256)
  the reference     the tool's digits equal the model's at the model's lanes
                    (MODEL_FIGURES, 11 of the 19 cells here), each key of the
                    reference leg shown failing ALONE on a doctored figure
  the legs          each leg of check `budget` shown failing alone on a
                    doctored summary of its own, and the Build never mutated
  the tool plants   each red in the leg it names, the control green
  NOT MEASURED      a region with no main-path lane is named, counted apart,
                    and crashes nothing
  the analytic leg  the study's 3.2 bound of the zone from the build's own
                    B1 and B2: red on a doctored B2 at any lane count
  the matrix        the three budget plants and the control against all
                    twelve checks (M3G1's nine, budget, rate, family), each
                    row through the real row assertion, shown on four
                    doctored rows
  the rate law      the Bernoulli law of mathlib_pow_rate, each leg shown
                    failing alone, the tool plants and the fragment plants
"""

import copy
import functools
import math
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cft_golden import FP64, FP128, FP256  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_inv_budget as IB  # noqa: E402
import mathlib_pow_budget as PB  # noqa: E402
import mathlib_pow_harness as P  # noqa: E402
import mathlib_pow_rate as PR  # noqa: E402
import mathlib_runs as R  # noqa: E402

RNE, RTZ = sf.RND_RNE, sf.RND_RTZ
ROOT = pathlib.Path(__file__).resolve().parents[2]


def fid(f):
    return f.name


# =====================================================================
# the plants
# =====================================================================

def test_the_budget_plants_are_a_table_of_their_own():
    assert set(ml._POW_BUDGET_PLANTS) == {"bound_tight", "zone_bound_off"}
    # POW_PLANTS stays the 28 keys the other parcels' tests read
    assert len(ml.POW_PLANTS) == 28
    assert not set(ml._POW_BUDGET_PLANTS) & set(ml.POW_PLANTS)
    assert "bound_tight" not in ml.POW_PLANTS
    assert "zone_bound_off" not in ml.POW_PLANTS
    assert "log_short" in ml.POW_PLANTS
    assert "_POW_BUDGET_PLANTS" not in ml.__all__
    assert all(n not in ml.__all__ for n in ml._POW_BUDGET_PLANTS)


@pytest.mark.parametrize("fn,n", [("pow", None), ("powr", None),
                                  ("pown", 1000), ("rootn", 3),
                                  ("compound", 1000)])
def test_the_budget_plants_act_at_fp64_and_are_refused_by_name_above(fn, n):
    kw = {} if n is None else {"n": n}
    clean = ml.build(fn, FP64, RNE, **kw)
    assert clean.meta["B1"] and clean.meta["B2"]
    tight = ml.build(fn, FP64, RNE, plant="bound_tight", **kw)
    assert (tight.meta["B1"], tight.meta["B2"]) == (0, 0)
    off = ml.build(fn, FP64, RNE, plant="zone_bound_off", **kw)
    assert off.meta["B1"] == clean.meta["B1"] and off.meta["B2"] == 0
    for plant in ("bound_tight", "zone_bound_off"):
        b = ml.build(fn, FP64, RNE, plant=plant, **kw)
        assert b.meta["plant"] == plant
        assert (b.body, b.words) != (clean.body, clean.words), plant
        for fmt in (FP128, FP256):
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to {fn} at {fmt.name}: the fault is "
                               f"not reached"):
                ml.build(fn, fmt, RNE, plant=plant, **kw)
    # the fragment and the core take them as well, and the unknown-plant
    # message names the keys of both tables
    assert ml.fragment(fn, FP64, RNE, *(() if n is None else (n,))) \
        is not None
    with pytest.raises(ValueError) as e:
        ml.build(fn, FP64, RNE, plant="no_such_plant", **kw)
    msg = str(e.value)
    assert "log_short" in msg and "bound_tight" in msg \
        and "zone_bound_off" in msg


def test_the_cores_take_the_budget_plants_where_they_act():
    for plant in ("bound_tight", "zone_bound_off"):
        assert ml.build_pow_core(FP64, RNE, plant=plant).meta["plant"] == plant
        with pytest.raises(ValueError, match=f"plant {plant!r} does not apply "
                           f"to pow_core at fp128: the fault is not reached"):
            ml.build_pow_core(FP128, RNE, plant=plant)


def test_the_budget_plants_change_the_bound_word_and_nothing_else_by_name():
    clean = P.build_of("pow", FP64, RNE)
    for plant in ("bound_tight", "zone_bound_off"):
        b = P.build_of("pow", FP64, RNE, plant)
        # a different build, the same function: the probes and inputs equal
        assert b.inputs == clean.inputs and set(b.probes) == set(clean.probes)
        assert len(b.body) < len(clean.body)


# =====================================================================
# the Build is never mutated
# =====================================================================

def test_a_budget_leaves_the_memoised_build_as_it_found_it():
    b = P.build_of("pow", FP64, RNE)
    before = PB.snapshot(b)
    meta_fn, phases = b.meta["fn"], list(b.phase_of)
    lanes = PB.cell_lanes(FP64, "pow", "edge", 6, 1)
    s, _bud = PB.budget_of(b, lanes)
    assert s["lanes"] > 0
    assert PB.snapshot(b) == before
    assert b.meta["fn"] == meta_fn == "pow" and list(b.phase_of) == phases
    assert "fixed-grid" in b.phase_of                 # not remapped on it
    # the proxy is what carries the base class's fn and the remapped phases
    v = PB._view(b)
    assert v.meta["fn"] == "atan2" and v.meta is not b.meta
    assert "fixed-grid" not in v.phase_of and "fixed-grid" in b.phase_of
    assert v.phase_of != b.phase_of and v.body is b.body
    assert PB._view(b, remap=False).phase_of == list(b.phase_of)
    # check_budget_pow asserts it, on a build whose body a fault changes
    class Mutating(PB.PowBudget):
        def add(self, lanes):
            self.an.b.body = list(self.an.b.body)       # a check that mutates
            return super().add(lanes)
    b2 = copy.copy(P.build_of("pow", FP64, RNE))
    b2.meta = dict(b2.meta)
    orig = PB.PowBudget
    PB.PowBudget = Mutating
    try:
        with pytest.raises(AssertionError, match="mutated a Build"):
            PB.check_budget_pow(b2, lanes, "edge")
    finally:
        PB.PowBudget = orig


# =====================================================================
# the reference: the model's digits at the model's lanes
# =====================================================================

# the cells held here (MODEL_FIGURES has 19; the rest are `pow-budget --set
# reference`): three at each format, one of each function's kind, compound's
# int1000 and zone1000 and pown's zone12000 at fp64
REFERENCE_CELLS = [
    ("fp64", "pow", "edge", None), ("fp64", "powr", "near1", None),
    ("fp64", "pown", "zone12000", None), ("fp64", "compound", "int1000", None),
    ("fp64", "compound", "zone1000", None),
    ("fp128", "pow", "rhoedge", None), ("fp128", "compound", "zone188000",
                                         None),
    ("fp128", "rootn", "int17", None),
    ("fp256", "pow", "zone", None), ("fp256", "powr", "edge", None),
    ("fp256", "pown", "int", None),
]


def test_the_model_s_figures_cover_nineteen_cells():
    assert len(PB.MODEL_FIGURES) == 19
    for key in REFERENCE_CELLS:
        assert key in PB.MODEL_FIGURES
    for (f, fn, reg, plant), v in PB.MODEL_FIGURES.items():
        assert fn in ml.POW_NAMES and f in ("fp64", "fp128", "fp256")
        assert len(v) == 8 and v[2] and len(v[2]) == 16


@pytest.fixture(scope="module")
def ref_runs():
    """{cell: (findings, summary)} of check_reference, run once."""
    return {k: PB.check_reference(P.BY_NAME[k[0]], k[1], k[2], k[3])
            for k in REFERENCE_CELLS}


@pytest.mark.parametrize("key", REFERENCE_CELLS,
                         ids=lambda k: "-".join(str(v) for v in k if v))
def test_the_budget_equals_the_model_at_the_model_s_lanes(ref_runs, key):
    found, s = ref_runs[key]
    assert found == [], found
    n, main, digest, expect = PB.model_cell(*key)
    assert s["lanes"] == main
    # the equality is what the leg compares: four figures
    for k, v in expect.items():
        if k == "rounding":
            assert s[k] == v
        else:
            assert f"{s[k]:.4g}" == f"{v:.4g}", (key, k)


def test_each_key_of_the_reference_leg_fails_alone(ref_runs):
    _f, s = ref_runs[("fp64", "compound", "zone1000", None)]
    n, main, digest, expect = PB.model_cell("fp64", "compound", "zone1000",
                                            None)
    where = "budget: compound fp64 rne zone1000"
    assert [f for f in IB.judge(s, where, expect)
            if "differs from the model" in f] == []
    for key in expect:
        doctored = dict(expect)
        doctored[key] = expect[key] + 1 if key == "rounding" \
            else expect[key] * 1.01
        found = [f for f in IB.judge(s, where, doctored)
                 if "differs from the model" in f]
        assert len(found) == 1 and key in found[0], (key, found)
        # and no other leg answers a doctored reference
        assert all(PB.leg_of(f) in (None, "reference")
                   for f in IB.judge(s, where, doctored))
    # the lanes' digest: a generator that moved its draws is named
    lanes = PB.cell_lanes(FP64, "compound", "zone1000", n, PB.MODEL_SEED)
    assert PB.lanes_digest(lanes) == digest
    assert PB.lanes_digest(lanes[::-1]) != digest
    assert PB.lanes_digest(lanes[1:]) != digest


# =====================================================================
# the legs, each failing alone on a doctored summary of its own
# =====================================================================

WHERE = "budget: compound fp64 rne zone1000"


@pytest.fixture(scope="module")
def control(ref_runs):
    """The summary of the control cell (compound zone1000 at fp64, the
    model's 120 lanes): every leg green."""
    return ref_runs[("fp64", "compound", "zone1000", None)][1]


def legs_of(found):
    return {PB.leg_of(f) for f in found}


def test_the_control_summary_is_green_in_every_leg(control):
    assert PB.judge(control, WHERE, head=True) == []
    assert 0 < control["resid"] and control["bound"] < 1
    assert control["Emax"] <= control["bound"] * 1.001
    assert control["log_sum_cap"] > 0 and control["rest"] > 0


def test_each_leg_of_the_budget_fails_alone_on_a_doctored_summary(control):
    s = control
    judge = PB.judge
    # bound: the bound past 1 (M and the capacities, not the residual's)
    bad = dict(s, Mmax=0.9, S_cap=0.2, bound=1.1)
    assert legs_of(judge(bad, WHERE)) == {"bound"}
    # lane: a sampled lane's error past the bound by more than 0.1 %
    bad = dict(s, Emax=s["bound"] * 1.002)
    assert legs_of(judge(bad, WHERE)) == {"lane"}
    assert judge(dict(s, Emax=s["bound"] * 1.0009), WHERE) == []
    # residual: the bound with it past 1, and a residual of exactly 0
    bad = dict(s, resid=1.0 - s["bound"] + 1e-3)
    assert legs_of(judge(bad, WHERE)) == {"residual"}
    bad = dict(s, resid=0.0)
    found = judge(bad, WHERE)
    assert legs_of(found) == {"residual"} and "exactly 0" in found[0]
    # reach: no rounding instruction reached by the sweep
    bad = dict(s, rounding=0, S_obs=0.0, resid=1e-9)
    assert legs_of(judge(bad, WHERE)) == {"reach"}
    bad = dict(s, S_obs=0.0, resid=1e-9)
    assert legs_of(judge(bad, WHERE)) == {"reach"}
    # head: on edge, the head phase's capacity 0
    bad = dict(s, by_phase=dict(s["by_phase"], head=(0.0, 0.0)))
    assert legs_of(judge(bad, WHERE, head=True)) == {"head"}
    assert judge(bad, WHERE, head=False) == []
    # no lane on the main path
    assert "no lane of the sample is on the main path" in \
        judge(dict(s, lanes=0), WHERE)[0]


def test_a_region_whose_every_v_is_exact_is_not_a_failed_sweep(control):
    """V exactly f on every lane (fp256's tinyy): the error is 0, there is
    nothing to bound, and the reach and zero-residual legs do not apply; a
    sweep that STOPPED SHORT (the tool plant fixed_grid_as_before_v) has a
    true error that is not 0, so the lane leg holds."""
    s = dict(control, Emax=0.0, Mmax=0.0, S_cap=0.0, S_obs=0.0, bound=0.0,
             resid=0.0)
    assert PB.exact_v(s) and PB.judge(s, WHERE) == []
    assert not PB.exact_v(dict(s, Emax=1e-9))
    assert legs_of(PB.judge(dict(s, Emax=1e-9), WHERE)) >= {"lane"}
    assert not PB.exact_v(dict(s, lanes=0))


def test_the_attributes_leg_is_green_on_the_pow_family_and_red_on_a_fault():
    lanes = PB.cell_lanes(FP64, "pow", "zone", 10, 1)
    builds = {r: P.build_of("pow", FP64, r) for r in sf.RND_MODES}
    out, (n, bad) = PB.check_attributes(builds, lanes, "zone")
    assert out == [] and n > 0 and bad == 0
    # a directed rounding before V (the last ADD of the reconstruction): V
    # differs across the attributes on a lane, and the leg names it
    faulty = dict(builds)
    faulty[RTZ] = IB.with_directed_before_v(builds[RTZ])
    out, (n, bad) = PB.check_attributes(faulty, lanes, "zone")
    assert bad > 0 and len(out) == 1
    assert "V differs across the attributes" in out[0]
    assert PB.leg_of(out[0]) == "attributes"
    # check_budget_pow runs it through its `attrs` argument
    f, s = PB.check_budget_pow(builds[RNE], lanes, "zone", attrs=builds)
    assert f == [] and s["attr_lanes"] == n and s["attr_differ"] == 0
    f, s = PB.check_budget_pow(builds[RNE], lanes, "zone", attrs=faulty)
    assert legs_of(f) == {"attributes"}


# =====================================================================
# the analytic bound of the zone (the study's 3.2, zonebound.py)
# =====================================================================

def test_the_analytic_zone_bound_is_the_studys_computed_figures():
    """COMPUTED by the study (zonebound.out.txt): the sum's five roundings 7.885
    2^-106 in L, 0.171 Bv with the |Y k| term whatever |Y|, 0.898 Bv at n =
    1000 without it, 0.980 at the limit; compound's nine by the reduction's
    cells 0.231 Bv at the largest, cell C = 9."""
    fmt = FP64
    b = P.build_n("pown", fmt, RNE, 1000)
    rows = PB.zone_rows(53, 0.64, math.log(16 / 9), -0.0625, 0.0625, 0.0, 0.0,
                        False)
    U = PB.zone_U(53, rows)
    assert abs(U / 2.0 ** -106 - 7.885) < 5e-4
    meta = dict(b.meta)
    assert abs(PB.zone_analytic(meta, fmt, "pown", None) - 0.171) < 5e-4
    off = dict(meta, B2=0)
    assert abs(PB.zone_analytic(off, fmt, "pown", 1000.0) - 0.898) < 5e-4
    assert abs(PB.zone_analytic(off, fmt, "pown", 12000.0) - 0.973) < 5e-4
    assert abs(PB.zone_analytic(off, fmt, "pown", None) - 0.980) < 5e-4
    bc = P.build_n("compound", fmt, RNE, 1000)
    assert abs(PB.zone_analytic(dict(bc.meta), fmt, "compound", None)
               - 0.231) < 5e-4
    Xb, cells = PB.zone_cells("fp64")
    assert abs(Xb - 241 / 256) < 1e-12 and [c[0] for c in cells] == \
        [16, 15, 14, 13, 12, 11, 10, 9]
    assert cells[0][1] == 0.5 and cells[-1][2] == Xb


def test_the_analytic_leg_is_red_on_a_doctored_b2_at_any_lane_count():
    """zone_bound_off drops B2: the bound of the sum alone is 0.898 at n =
    1000 and the sum with the sampled rest passes 1 whatever the lanes: red at
    60, 120 and 300 lanes and at every seed, where the sampled bound is
    1.015 at one seed (a 1.5 % margin) and under 1 at most."""
    b = P.build_n("compound", FP64, RNE, 1000, "zone_bound_off")
    clean = P.build_n("compound", FP64, RNE, 1000)
    assert b.meta["B2"] == 0 and clean.meta["B2"] != 0
    for seed, count in ((1, 12), (2, 20)):
        lanes = PB.cell_lanes(FP64, "compound", "zone1000", count, seed)
        f, s = PB.check_budget_pow(b, [ln for ln in lanes], "zone1000")
        assert "analytic" in legs_of(f), (seed, count, f)
        f, s = PB.check_budget_pow(clean, lanes, "zone1000")
        assert f == [], f
    # the leg alone, on the clean build's measured summary with its meta's B2
    # doctored to 0 (nothing else changed)
    sc = PB.budget_of(clean, lanes)[0]
    where = "budget: compound fp64 rne zone1000"
    assert PB.judge_analytic(sc, clean.meta, FP64, "compound", where,
                             sc["ymax"]) == []
    found = PB.judge_analytic(sc, dict(clean.meta, B2=0), FP64, "compound",
                              where, sc["ymax"])
    assert legs_of(found) == {"analytic"}
    # and a measured capacity past the analytic bound
    a = PB.zone_analytic(clean.meta, FP64, "compound", sc["ymax"])
    found = PB.judge_analytic(dict(sc, log_sum_cap=a * 1.01), clean.meta,
                              FP64, "compound", where, sc["ymax"])
    assert len(found) == 1 and "past the analytic bound" in found[0]


# =====================================================================
# the tool plants: each red in a named leg, the control green
# =====================================================================

def _cell(fmt, fn, region, count, seed=1):
    lanes = PB.cell_lanes(fmt, fn, region, count, seed)
    (n, ls), = PB.by_n(fn, lanes)
    return PB.build_for(fn, fmt, RNE, n), ls


def test_the_tool_plants_are_a_table_of_this_module_and_refused_by_name():
    assert set(PB.POW_TOOL_PLANTS) == {
        "fixed_grid_as_before_v", "scale_unscaled", "inputs_swapped",
        "negation_as_data", "capacities_dropped"}
    assert not set(PB.POW_TOOL_PLANTS) & set(IB.TOOL_PLANTS) - {
        "inputs_swapped", "negation_as_data", "capacities_dropped"}
    b, ls = _cell(FP64, "pow", "edge", 4)
    with pytest.raises(ValueError, match="unknown tool plant 'nope'"):
        PB.PowBudget(b, "nope")
    # a plant that cannot act: inputs_swapped on a one-input build
    bn = P.build_n("pown", FP64, RNE, 3)
    with pytest.raises(ValueError, match="tool plant 'inputs_swapped' does "
                       "not apply to pown at fp64: it has one input"):
        PB.PowBudget(bn, "inputs_swapped")
    # the base class's names stay the base class's table
    assert "fixed_grid_as_before_v" not in IB.TOOL_PLANTS
    assert "scale_unscaled" not in IB.TOOL_PLANTS
