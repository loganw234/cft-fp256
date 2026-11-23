# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""pow and powr, and the core of the pow family, of python/cft_golden/
mathlib.py (parcel M3G1, M3's build, wave 1) at fp64, fp128 and fp256, held to
the study's section 8 (docs/studies/M3-pow.md): quick enough for the golden
stage; the larger runs are `python python/tests/mathlib_runs.py pow-pools` and
`pow-bound`. Parcels M3G2 (pown, rootn, compound) and M3F1 (fp32) add a test
file of their own, each with its own table of plants, and import this file's
helpers and the harness's by function.

The checks are python/tests/mathlib_pow_harness.py's, each returning findings
that begin with its own name; the lanes are the vector sets' and the stage's
pools (794, 746 and 746 lanes of pow, 823, 775 and 775 of powr), the study's
placed regions, the committed structured lanes and the specials' rows. Nine
checks:

  pools  regions  specials  structured  seq  bound  shape  core  constants

and for every check a planted fault shown red in it, the control green in all
(mathlib.POW_PLANTS: 23), every leg of every check shown failing alone on a
doctored input, the interface, the refusals, the two-input evaluate, the
phases, the scheduler's choice, the `--check` output and the two commands of
mathlib_runs.py. The port against the study's model is a scratch script of the
parcel's entry (nothing here imports docs/studies/m3): the dag digests of the
thirty fragments, recorded when it passed, are pinned below.
"""

import functools
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
from cft_golden.formats import FpFormat  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_pow_harness as P  # noqa: E402

PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
FORMATS = P.FORMATS
FUNCS = P.FUNCS
RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = P.RNE, P.RTZ, P.RDN, P.RUP, P.RMM
BY_NAME = P.BY_NAME


def fid(f):
    return f.name


def rid(r):
    return sf.RND_NAMES[r]


build_of = P.build_of
fragment_of = P.fragment_of

# ---- what the study states and the model measured ----------------------------
GUARD = {"fp64": 44, "fp128": 46, "fp256": 46}
# (G, GL, GE, KL, DL, KE, DE) and (B1, B2) exponents: the study's (READ in the
# brief at 96d99d84, MEASURED by the model, and by this port's plan_pow)
PLAN = {"fp64": (44, 47, 46, 12, 24, 7, 13, 100, 101),
        "fp128": (46, 63, 48, 16, 42, 8, 20, None, None),
        "fp256": (46, 67, 48, 17, 73, 8, 33, None, None)}
# the dag digest of each fragment (the first 32 hex digits), equal to the
# model's (docs/studies/m3/m3pow.py at 96d99d84, `build(fn, fmt, rnd)
# .fragment()`, the parcel's scratch script: 30 of 30 at the Build's order and
# at the scheduled fragment's, with the lane compare)
DIGESTS = {
    "pow/fp64/rne": "a913b26ce65145803cfcd8bc15c72f4f",
    "pow/fp64/rtz": "75bc0e17c80965d57b79474be53b4f60",
    "pow/fp64/rdn": "f2350c009e4a1142242830b2c298091c",
    "pow/fp64/rup": "d6ce44939631ae00309becb62bc89fc7",
    "pow/fp64/rmm": "257c583b06961af7a503069818be93db",
    "powr/fp64/rne": "7a6c4bb7109598e6a501d5bff52e789f",
    "powr/fp64/rtz": "4b29585c3d3962ae762f9e6b5c9b43e7",
    "powr/fp64/rdn": "e37d80630948e487541b536228b0fc4d",
    "powr/fp64/rup": "c95899c559e9c1dfcd43cc41f33d77c1",
    "powr/fp64/rmm": "c63ca6d5099afe49ae452a9985fbeb08",
    "pow/fp128/rne": "e8750af534c14f741c13887797637d73",
    "pow/fp128/rtz": "a51babe08834c58a08ab538d1515a60f",
    "pow/fp128/rdn": "1f674ee2b3c7e85c708dfb5ec89459e9",
    "pow/fp128/rup": "90d2b5ed416744e1cd0d707559d33239",
    "pow/fp128/rmm": "24318919b7682e4286e6ba34eb1ca3cd",
    "powr/fp128/rne": "838070e4e5b14aabba14063cb9706ca3",
    "powr/fp128/rtz": "338df5b5441aaa04131c62ad9eb3ae53",
    "powr/fp128/rdn": "0af98de90653b032d0dd4c57cbbcb273",
    "powr/fp128/rup": "bbb2f92168663643da0369e09502a707",
    "powr/fp128/rmm": "4773614e908498450f964c851dc9b95b",
    "pow/fp256/rne": "e7249f9c281767eca70bb2a97faaebe7",
    "pow/fp256/rtz": "4990cccb9dead135776ffe1fb0241551",
    "pow/fp256/rdn": "b87ca60c898134bb36f2cf8dc93ed833",
    "pow/fp256/rup": "3a7315d023026e9cb540ea4c78f0b400",
    "pow/fp256/rmm": "7c10a04bc0796488e6093bdf16c43c84",
    "powr/fp256/rne": "22199ab278aef69e399ed3009470310d",
    "powr/fp256/rtz": "607525331933a91bd65a711d8ef01484",
    "powr/fp256/rdn": "1b6eca758a1a6c22a86ffb063aca2ef8",
    "powr/fp256/rup": "307b412314c1fdacf3ff8ade7cb1e612",
    "powr/fp256/rmm": "74cb81acb6871e647771d60abb425fd1",
}
# the golden stage's configurations: the pools through all thirty, seq at fp64,
# fp128 and fp256 under rne and rtz
POOL_CONFIGS = [(fn, f, r) for fn in FUNCS for f in FORMATS for r in RND]
SEQ_CONFIGS = [(fn, f, r) for fn in FUNCS for f in FORMATS
               for r in (RNE, RTZ)]
POW_PLANT_NAMES = {
    "exact_unmarked", "exact_rule_off", "exact_rule_no_tl",
    "midpoint_unmarked", "pow_zero_nan", "pow_one_nan", "sign_even",
    "integrality_wide", "sign_odd_lost", "powr_neg_ok", "powr_zero_zero",
    "near_one_gate_off", "side_rule_off", "screen_low", "mark_silenced",
    "bound_loose", "zero_sign_lost", "log_table_entry", "il2h_ulp",
    "screen_ulp", "y_one_loud", "two_sum_all", "log_short"}
# the five plants parcel M3G2 added to the table (test_mathlib_pow_n.py holds
# them; this file's rows, PLANTED and the plant tests are M3G1's 23)
M3G2_PLANT_NAMES = {
    "rootn_m0_neg", "compound_onep_rounded", "n_low_dropped", "n_word_ulp",
    "n_row_loud"}
# the plants build_pow_core accepts (the others are refused by name there,
# "does not apply"): what pow_core acts on
CORE_PLANTS = {"exact_unmarked", "exact_rule_off", "exact_rule_no_tl",
               "midpoint_unmarked", "near_one_gate_off", "side_rule_off",
               "screen_low", "mark_silenced", "bound_loose",
               "log_table_entry", "il2h_ulp", "screen_ulp", "two_sum_all",
               "log_short"}


def _cls(f, fn, rnd):
    return "pow" if fn == "pow" else "powr"


# =====================================================================
# the interface
# =====================================================================

INTERFACE = ("POW_NAMES", "POW_FORMATS", "POW_LIVE_CAP", "POW_PLANTS",
             "plan_pow", "pow_core", "build_pow_core", "check_pow_constants")


def test_the_interface_is_public_documented_and_not_in_all():
    for name in INTERFACE:
        assert hasattr(ml, name), name
        # the lead's word (2026-11-23): test_mathlib_inv_asin.py:142 pins
        # tuple(__all__) to M4G1's base, so the names are module attributes
        assert name not in ml.__all__, name
        obj = getattr(ml, name)
        if callable(obj):
            assert len(obj.__doc__ or "") > 200, name
    assert ml.pow_core is P.ml.pow_core and ml.POW_NAMES is P.ml.POW_NAMES
    doc = ml.pow_core.__doc__
    for word in ("Takes", "Requires", "Guarantees", "Returns", "Private",
                 "ybound", "exact_tl", "negres", "sgnw", "up", "Vh + Vl",
                 "Bv", "special lane", "beside 1"):
        assert word in doc, word
    assert "double word" in ml.build_pow_core.__doc__ and \
        "y_l" in ml.build_pow_core.__doc__
    assert "tuple" in ml.build.__doc__ and "POW_NAMES" in ml.build.__doc__
    for word in ("POW_NAMES", "pow_core", "plan_pow", "check_pow_constants",
                 "test_mathlib_inv_asin.py:142"):
        assert word in ml.__doc__, word


def test_pow_names_is_beside_the_other_tuples_which_are_as_they_were():
    assert ml.POW_NAMES == ("pow", "powr", "pown", "rootn", "compound")
    assert ml.NAMES == ("exp", "exp2", "expm1", "log", "log2", "log1p")
    assert ml.TRIG_NAMES == ("sin", "cos", "tan")
    assert ml.INV_NAMES == ("atan", "asin", "acos", "atan2")
    assert not set(ml.POW_NAMES) & set(ml.NAMES + ml.TRIG_NAMES
                                       + ml.INV_NAMES)
    assert ml.POW_FORMATS == (FP64, FP128, FP256) == FORMATS
    assert tuple(ml._POW_BUILDERS) == ("pow", "powr") == FUNCS
    assert ml._POW_PARCEL == {"pow": "M3G1", "powr": "M3G1", "pown": "M3G2",
                              "rootn": "M3G2", "compound": "M3G2"}
    assert {fn: ml.POW_LIVE_CAP[fn] for fn in ml.POW_NAMES} == {
        "pow": {"fp64": 30, "fp128": 30, "fp256": 30, "fp32": 32},
        "powr": {"fp64": 23, "fp128": 22, "fp256": 22, "fp32": 29},
        "pown": {"fp64": 21, "fp128": 21, "fp256": 21},
        "rootn": {"fp64": 19, "fp128": 19, "fp256": 19},
        "compound": {"fp64": 22, "fp128": 22, "fp256": 22}}
    assert set(ml.POW_PLANTS) == POW_PLANT_NAMES | M3G2_PLANT_NAMES
    assert all(isinstance(t, str) and len(t) > 20
               for t in ml.POW_PLANTS.values())


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_plan_is_the_studys(fmt):
    p = ml.plan_pow(fmt)
    G, GL, GE, KL, DL, KE, DE, e1, e2 = PLAN[fmt.name]
    assert (p.G, p.GL, p.GE, p.KL, p.DL, p.KE, p.DE) == \
        (G, GL, GE, KL, DL, KE, DE)
    assert G == ml.GUARD[fmt.name] == GUARD[fmt.name]
    for v in (p.B1, p.B2):
        assert isinstance(v, Fraction)
    if e1:
        assert (p.B1, p.B2) == (Fraction(1, 2 ** (2 * fmt.prec - 6)),
                                Fraction(1, 2 ** (2 * fmt.prec - 5)))
        assert (p.B1, p.B2) == (Fraction(1, 2 ** e1), Fraction(1, 2 ** e2))
    else:
        assert (p.B1, p.B2) == (0, 0)
    # GL = G + ceil(log2 T_f) + 2 where plan_log accepts it: fp128 and fp256
    # reach it; fp64 steps down from 57 to 47 (the double word's floor)
    tf = max(fmt.emax + 2, fmt.prec - fmt.emin + 2)
    want = G + (tf - 1).bit_length() + 2
    assert want - GL == {"fp64": 10, "fp128": 0, "fp256": 0}[fmt.name]
    assert (p.KL, p.DL) == ml.plan_log(fmt, GL)
    assert (p.KE, p.DE) == ml.plan_exp(fmt, GE)
    with pytest.raises(ValueError):
        ml.plan_log(fmt, fmt.prec)            # the floor is real
    # G is a parameter
    q = ml.plan_pow(fmt, G - 4)
    assert (q.G, q.GE) == (G - 4, G - 2)


def test_plan_pow_steps_down_and_refuses_by_name_the_proof_it_cannot_make(
        monkeypatch):
    real = ml.plan_log

    def short(fmt, G):
        if G > 50:
            raise ValueError(f"G = {G} is past the double word's floor")
        return real(fmt, G)
    monkeypatch.setattr(ml, "plan_log", short)
    p = ml.plan_pow(FP128)             # target 63: stepped down to 50
    assert p.GL == 50 and p.B1 == Fraction(1, 2 ** (2 * 113 - 6)) \
        and p.B2 == Fraction(1, 2 ** (2 * 113 - 5))

    def never(fmt, G):
        raise ValueError("no")
    monkeypatch.setattr(ml, "plan_log", never)
    with pytest.raises(ValueError, match="cannot be planned at fp64 even at "
                       "G = 44"):
        ml.plan_pow(FP64)
    monkeypatch.undo()
    for bad in (FP32, FpFormat("fp16", 5, 10)):
        with pytest.raises(ValueError, match=f"plan_pow: {bad.name}"):
            ml.plan_pow(bad)
    with pytest.raises(ValueError, match="triple word, parcel M3F1's"):
        ml.plan_pow(FP32)


# ---- the refusals, by name ---------------------------------------------------

def test_pown_rootn_compound_need_n_and_refuse_a_bad_one():
    """Parcel M3G2 builds them: n is a constant of the fragment, required and
    checked (python/tests/test_mathlib_pow_n.py holds the rest)."""
    for name in ("pown", "rootn", "compound"):
        for call in (ml.build, ml.fragment):
            with pytest.raises(ValueError, match=f"{name} needs its integer "
                               f"operand n"):
                call(name, FP64, RNE)
        with pytest.raises(ValueError, match="is outside int64"):
            ml.build(name, FP64, RNE, n=2 ** 63)
        with pytest.raises(ValueError, match="is not an integer"):
            ml.fragment(name, FP64, RNE, n=2.5)
        assert ml.fragment(name, FP64, RNE, n=3).op == name


def test_names_not_built_and_fp32_are_refused_by_name():
    # pow and powr at fp32 are built (parcel M3F1): see
    # test_mathlib_pow_tw.py::test_fp32_pow_and_powr_are_built_and_the_rest_
    # refused_by_name
    with pytest.raises(ValueError, match="pow takes no integer operand"):
        ml.build("pow", FP64, RNE, n=3)
    with pytest.raises(ValueError, match="powr takes no integer operand"):
        ml.fragment("powr", FP64, RNE, n=3)
    with pytest.raises(ValueError, match="exp takes no integer operand"):
        ml.build("exp", FP64, RNE, n=3)
    with pytest.raises(ValueError, match="atan takes no integer operand"):
        ml.build("atan", FP64, RNE, n=1)
    with pytest.raises(ValueError, match="attribute"):
        ml.build("pow", FP64, 7)
    with pytest.raises(ValueError, match="no_such_plant") as e:
        ml.build("pow", FP64, RNE, plant="no_such_plant")
    assert "exact_unmarked" in str(e.value) and "two_sum_all" in str(e.value)
    # the six's, the trig routines' and the inverse routines' plants are not
    # the pow family's
    for plant in ("head_short", "quadrant_sign", "table_entry", "coef"):
        with pytest.raises(ValueError, match=plant):
            ml.build("pow", FP64, RNE, plant=plant)
    # the message of a name that is not built lists the pow names that are,
    # after the inverse names (test_mathlib_trig.py's order is kept)
    with pytest.raises(ValueError) as e:
        ml.fragment("sinh", FP64, RNE)
    assert "log1p, sin, cos, tan, atan, asin, acos, atan2, pow, powr" \
        in str(e.value)
    with pytest.raises(ValueError, match="triple word"):
        ml.build_pow_core(FP32)


def test_fragment_is_built_once_per_n_and_held_to_its_own_cap():
    f = ml.fragment("pow", FP64, RNE)
    assert ml.fragment("pow", FP64, RNE) is f
    assert isinstance(f, routines.Fragment) and (f.op, f.fmt, f.rnd) == (
        "pow", FP64, RNE)
    assert f.inputs == ("a", "b") and f.stage == "specialised"
    assert ml.invariants(f) == []
    # a pow-family fragment is held to its own row, no fallback to the six's
    # cap (13): 30 values live pass, 29 fail by name
    assert ml.LIVE_CAP["fp64"] == 13 < f.live_max() == 30
    assert ml.invariants(f, live_cap=29) == ["30 values live at once, past 29"]
    saved = ml.POW_LIVE_CAP["pow"]["fp64"]
    try:
        ml.POW_LIVE_CAP["pow"]["fp64"] = 29
        assert ml.invariants(f) == ["30 values live at once, past 29"]
        del ml.POW_LIVE_CAP["pow"]["fp64"]
        with pytest.raises(ValueError, match="pow has no live cap at fp64"):
            ml.invariants(f)
    finally:
        ml.POW_LIVE_CAP["pow"]["fp64"] = saved
    assert ml.invariants(f) == []
    # the cap is the maximum over the attributes, per function and format
    for fn in FUNCS:
        for fmt in FORMATS:
            top = max(fragment_of(fn, fmt, r).live_max() for r in RND)
            assert top == ml.POW_LIVE_CAP[fn][fmt.name], (fn, fmt.name)


# ---- the two-input evaluate, the Build's keeps ----------------------------------

def test_evaluate_and_run_take_a_tuple_in_inputs_order():
    b = build_of("pow", FP64, RNE)
    f = b.fragment()
    assert b.inputs == f.inputs == ("a", "b")
    two, three = P._V(FP64, 0, 1, 1), P._V(FP64, 0, 3, 0)
    nine = P._V(FP64, 0, 9, 0)
    bits, fl, pr = b.run((three, two), ("Vh", "Vl"))
    assert ml.evaluate(f, (three, two)) == (bits, fl)
    assert (bits, fl) == (nine - 1, 0x90) or (bits, fl) == (nine, 0x90)  # 3^2
    swapped = b.run((two, three))                    # 2^3 = 8, exact
    assert swapped[:2] == (P._V(FP64, 0, 1, 3), 0)
    assert swapped[:2] != (bits, fl)
    assert ml.evaluate(f, (two, three)) == swapped[:2]
    # an int for two inputs, a tuple of the wrong length
    for bad in (two, (two,), (two, two, two)):
        with pytest.raises(ValueError, match="inputs"):
            b.run(bad)
        with pytest.raises(ValueError, match="inputs"):
            ml.evaluate(f, bad)
    with pytest.raises(ValueError, match="not an encoding"):
        ml.evaluate(f, (two, 1 << 64))
    # the core's lanes: (x, y), and (x, y_h, y_l) for the double
    c1, c2 = P.core_of(FP64, RNE, None, False), P.core_of(FP64, RNE, None,
                                                           True)
    assert c1.inputs == ("a", "b") and c2.inputs == ("a", "b", "c")
    assert c1.meta["fn"] == c2.meta["fn"] == "pow_core"
    r0 = c2.run((three, two, 0))
    assert r0 == c1.run((three, two))
    tiny = P._V(FP64, 0, 1, -60)
    assert c2.run((three, two, tiny)) != r0       # y_l is read (in V_l)
    assert c2.run((three, two, tiny | FP64.sign_mask)) != r0
    assert c2.run((three, two, tiny)) != c2.run((three, two,
                                                 tiny | FP64.sign_mask))


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_build_keeps_what_the_budget_and_the_sequel_read(fmt):
    b = build_of("pow", fmt, RNE)
    probes = ("Vh", "Vl", "Bv", "R", "R1", "R2", "mk", "th0", "th", "tl",
              "ex", "tinyt", "FIN", "r", "Lh", "Ll", "tq", "rp", "rh", "nrl")
    assert set(probes) <= set(b.probes), set(probes) - set(b.probes)
    assert all(b.probes[k][0] == "v" for k in probes)
    m = b.meta
    G, GL, GE, KL, DL, KE, DE, e1, e2 = PLAN[fmt.name]
    assert (m["fn"], m["G"], m["GL"], m["GE"], m["KL"], m["DL"], m["KE"],
            m["DE"]) == ("pow", G, GL, GE, KL, DL, KE, DE)
    assert (m["B1"], m["B2"]) == (ml.plan_pow(fmt).B1, ml.plan_pow(fmt).B2)
    assert (m["n"], m["shift"], m["plant"], m["family"], m["N"]) == (
        None, 0, None, "double word", 8)
    assert (m["fast_two_sum"], m["two_sum"]) == P.EFT[("pow", fmt.name)]
    assert "OFF" in m
    # the phases: every one is in PHASE_ORDER, which gained none
    assert set(b.phase_of) <= set(ml.PHASE_ORDER)
    assert len(ml.PHASE_ORDER) == 45 and "setup" not in set(b.phase_of)
    assert tuple(dict.fromkeys(b.phase_of))[:2] == ("classify", "front")
    # the design's order of the phases, from the instrumented Build
    seen = tuple(dict.fromkeys(b.phase_of))
    assert seen == ("classify", "front", "reduce", "table", "tail", "head",
                    "Z", "recon", "head2", "lookup", "scale", "final",
                    "fixed-grid", "special")


def test_guard_and_bound_shift_are_the_builds_own():
    b = ml.build("pow", FP64, RNE, guard=30, bound_shift=3)
    assert b.meta["G"] == 30 and b.meta["shift"] == 3
    assert b.meta["GE"] == 32
    assert b.words[b.roles["BREL"][1]] == ml._pow2(FP64, -(53 + 30) + 3)
    clean = build_of("pow", FP64, RNE)
    assert b.words != clean.words
    # at fp128 (B1 = B2 = 0) the bound is BREL alone, inflated by the shift
    c = ml.build("powr", FP128, RNE, bound_shift=5)
    assert "B1" not in c.roles and "B2" not in c.roles
    assert c.words[c.roles["BREL"][1]] == ml._pow2(FP128, -(113 + 46) + 5)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_scheduler_takes_the_depth_first_order(fmt):
    for fn in FUNCS:
        b = build_of(fn, fmt, RNE)
        g = b.fragment(schedule=False)
        ph = [b.phase_of[i] for i in b.live_indices()]
        live = {"design": g.live_max(),
                "ranked": ml.permuted(g, ml._ranked_order(g, ph)).live_max(),
                "dfs": ml.permuted(g, ml._dfs_order(g)).live_max()}
        f = b.fragment()
        assert f.live_max() == live["dfs"] == min(live.values())
        assert live["dfs"] < live["ranked"] < live["design"]
        assert f.live_max() == ml.POW_LIVE_CAP[fn][fmt.name]
        assert H.check_reorder(b, f) == []


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_dag_digests_are_the_models(fmt):
    for fn in FUNCS:
        for rnd in RND:
            key = f"{fn}/{fmt.name}/{rid(rnd)}"
            got = ml.dag_digest(fragment_of(fn, fmt, rnd))[:32]
            assert got == DIGESTS[key], key
            # the design's order and the scheduled fragment are one graph
            assert ml.dag_digest(build_of(fn, fmt, rnd).fragment(
                schedule=False))[:32] == got


# =====================================================================
# the checks, clean
# =====================================================================

@pytest.mark.parametrize("fn,fmt,rnd", POOL_CONFIGS, ids=lambda v: v.name
                         if hasattr(v, "name") else (
                             v if isinstance(v, str) else rid(v)))
def test_pools(fn, fmt, rnd):
    f = fragment_of(fn, fmt, rnd)
    xs = P.pool(fn, fmt)
    assert len(xs) == P.POOL_SIZES[(fn, fmt.name)]
    out, t = P.check_pools(f)
    assert out == [] and t.n == len(xs)
    assert len(t.marked) == P.POOL_MARKS[(fn, fmt.name)][RND.index(rnd)]
    assert t.wrong == [] and t.stray == []
    # a marked lane's guess is counted, not a failure; most are right
    assert 0 < t.marked_right < len(t.marked)


@pytest.mark.parametrize("fn,fmt,rnd", SEQ_CONFIGS, ids=lambda v: v.name
                         if hasattr(v, "name") else (
                             v if isinstance(v, str) else rid(v)))
def test_seq(fn, fmt, rnd):
    f = fragment_of(fn, fmt, rnd)
    out, lanes = P.check_seq(f)
    assert out == []
    assert len(lanes) > 150          # the pool's every 8th and the committed
    must = [lane for _l, ls, e in P.STRUCT_ROWS[fn](fmt) if e == "marked"
            for lane in ls]
    assert len(must) == 4 and all(
        ml.evaluate(f, lane)[1] & ml.MARK for lane in must)


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_regions(fmt, fn):
    n = P.REGION_LANES[(fn, fmt.name)] // 10
    regs = {r: P.region(fmt, fn, r, n, 1) for r in P.REGION_NAMES[fn]}
    assert set(regs) == set(P.REGION_NAMES[fn])
    assert all(len(v) == n for v in regs.values()), \
        {k: len(v) for k, v in regs.items()}
    total = marked = 0
    for rnd in RND:
        f = fragment_of(fn, fmt, rnd)
        out, (lanes, mk) = P.check_regions(f, regs)
        assert out == [], out
        total, marked = lanes, marked + mk
    assert total == n * len(regs) + len(P.first_lanes(fn, fmt))
    # the study's regions mark nothing (3.3: 0 marked in every region)
    assert marked == 0
    # the regions pow has and powr has not
    assert ("negint" in regs) == ("negedge" in regs) == (fn == "pow")
    assert P.region(fmt, "powr", "negint", 5, 1) == []
    assert P.region(fmt, "powr", "negedge", 5, 1) == []
    with pytest.raises(ValueError):
        P.region(fmt, fn, "nonesuch", 5, 1)


def test_the_first_designs_lanes_are_there_by_name():
    for fmt in FORMATS:
        labels = [lab for lab, _ in P.first_lanes("pow", fmt)]
        assert "pow(6/5, minSub)" in labels and "pow(5/6, -minSub)" in labels
        assert "pow(-67.6, -177)" in labels
        assert ("pow(-(1 + 0x389 ulp), 0x43285fac64090d34)" in labels) == \
            (fmt.name == "fp64")
    assert P.first_lanes("powr", FP64) == []
    # the lanes are literal: item 2's, fp64's own bits
    lane = dict(P.first_lanes("pow", FP64))[
        "pow(-(1 + 0x389 ulp), 0x43285fac64090d34)"]
    assert lane == (0xbff0000000000389, 0x43285fac64090d34)
    # transcend.py's answer to item 7: pow(-67.6, -177) is -0 with underflow
    # under rne, the first design's +0 (3.6, item 7)
    x, y = dict(P.first_lanes("pow", FP64))["pow(-67.6, -177)"]
    assert P.golden(FP64, RNE, (x, y), "pow") == (FP64.sign_mask, 0x18)
    # and the control equals it
    f = fragment_of("pow", FP64, RNE)
    assert ml.evaluate(f, (x, y)) == (FP64.sign_mask, 0x18)
    # item 1, pow(1.2, minSub) under rup: 1 + 2^-52, not 1
    x, y = dict(P.first_lanes("pow", FP64))["pow(6/5, minSub)"]
    assert P.golden(FP64, RUP, (x, y), "pow") == (
        sf.one_bits(FP64) + 1, 0x10)
    assert ml.evaluate(fragment_of("pow", FP64, RUP), (x, y)) == (
        sf.one_bits(FP64) + 1, 0x10)


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_specials(fmt, fn):
    frags = {r: fragment_of(fn, fmt, r) for r in RND}
    out, n = P.check_specials(fmt, fn, frags)
    assert out == [], out
    rows = P.special_rows(fn, fmt)
    assert len(rows) == (15 if fn == "pow" else 17)
    assert n == 5 * sum(len(ls) for _l, ls in rows)
    # the row each of 9.2.1's pow entries names is there, both signs of every
    # zero and infinity where the row has them
    lanes = {x for _l, ls in rows for x, _y in ls}
    for bits in (0, fmt.sign_mask, sf.inf_bits(fmt),
                 sf.inf_bits(fmt, 1), sf.qnan_bits(fmt), sf.snan_bits(fmt)):
        assert bits in lanes, hex(bits)
    ylanes = {y for _l, ls in rows for _x, y in ls}
    for bits in (0, fmt.sign_mask, sf.inf_bits(fmt), sf.inf_bits(fmt, 1)):
        assert bits in ylanes, hex(bits)


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_structured(fmt, fn):
    n = 0
    for rnd in RND:
        f = fragment_of(fn, fmt, rnd)
        out, lanes = P.check_structured(f)
        assert out == [], out
        n += lanes
    assert n >= 5 * 80
    rows = {label: (ls, e) for label, ls, e in P.STRUCT_ROWS[fn](fmt)}
    # the exact families are marked, in every attribute (the leg is the row)
    ls, e = rows["exact cases that must mark by family"]
    assert e == "marked" and len(ls) == 4
    # (3 +- ulp)^2 is within the bound of a midpoint: the design cannot decide
    ls, e = rows["3^2's neighbours in x: within the bound of a midpoint"]
    assert e == "midpoint" and len(ls) == 2


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_bound(fmt, fn):
    b = build_of(fn, fmt, RNE)
    worst, lanes, main = -1e9, 0, 0
    for region, xs in P.placed_points(fn, fmt).items():
        assert len(xs) == 48
        out, (w, m, n) = P.check_bound(b, xs, region)
        assert out == [] and n == 48, (region, out)
        if region in P.BOUND_NO_MAIN:
            # nothing measured: kept out of the tally (the run's own line says
            # NOT MEASURED: test_the_pow_commands_...)
            assert m == 0 and w < -1e8
            continue
        assert m >= 40, (region, m)
        worst, lanes, main = max(worst, w), lanes + n, main + m
    # the largest is a SAMPLED lower bound (48 points a region, seed 11): the
    # direct error is under 1 Bv with room (MEASURED: 2^-4.5 to 2^-3.9; the
    # floor is the loose side of the in-lane bound)
    assert -12 < worst < -2, worst


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_shape(fmt):
    for fn in FUNCS:
        builds = {(fn, r): build_of(fn, fmt, r) for r in RND}
        assert P.check_shape(fmt, builds) == []
    # the study's totals (READ: costs.fp64, fp128, fp256.out.txt)
    for fn, want in (("pow", {"fp64": 434, "fp128": 489, "fp256": 540}),
                     ("powr", {"fp64": 413, "fp128": 468, "fp256": 519})):
        f = fragment_of(fn, fmt, RNE)
        assert len(f) == want[fmt.name]
        assert f.live_max() == {"pow": 30, "powr": {
            "fp64": 23, "fp128": 22, "fp256": 22}[fmt.name]}[fn]


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_core(fmt):
    for double in (False, True):
        b = P.core_of(fmt, RNE, None, double)
        assert b.inputs == (("a", "b", "c") if double else ("a", "b"))
    out, (worst, n) = P.check_core(fmt)
    assert out == [] and n >= 36 and worst < -4, (out, worst, n)
    # the Fraction ybound (parcel M3G2's |n|), where B2 is not 0 (fp64)
    out, n = P._check_ybound(fmt)
    assert out == [] and n == (24 if fmt.name == "fp64" else 0)


def test_core_single_word_lanes_are_the_same_function():
    b1, b2 = P.core_of(FP64, RNE, None, False), P.core_of(FP64, RNE, None,
                                                           True)
    for lane in P.core_lanes(FP64)[:6]:
        x, yh, _yl = lane
        assert b1.run((x, yh))[:2] == b2.run((x, yh, 0))[:2]


def test_constants_in_process():
    findings, lines = P.check_constants()
    assert findings == []
    # each built function at three formats
    assert len(lines) == 3 * len(FUNCS)
    assert all("derived constants in 5 fragments" in s for s in lines)
    counts = {s.split(":")[0]: int(s.split(": ")[2].split()[0])
              for s in lines}
    assert len(counts) == 3 * len(FUNCS)
    # the counts of derived constants (MEASURED by this parcel)
    assert counts == {"pow fp64": 747, "pow fp128": 882, "pow fp256": 1107,
                      "powr fp64": 707, "powr fp128": 842,
                      "powr fp256": 1067}


def _run_module(*args):
    return subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                           *args], cwd=PYTHON_DIR, capture_output=True,
                          text=True)


def test_constants_as_a_program():
    findings, out = P.check_constants_cli()
    assert findings == [], findings
    assert len(out) == 3 * len(FUNCS) + 1 and not any(
        "DIFFERENCE" in ln for ln in out)
    assert out[-1] == (f"mathlib --check (pow): {len(FUNCS)} routines, 3 "
                       f"formats, 0 differences")
    assert sum(ln.startswith("pow fp") for ln in out) == 3
    assert sum(ln.startswith("powr fp") for ln in out) == 3
    r = _run_module("--only", "pow")           # the listing, not the check
    assert r.returncode == 0, r.stderr
    rows = [ln for ln in r.stdout.splitlines() if ln.startswith("pow")]
    assert len(rows) == 2 * 3 * 5
    assert _check_listing(rows) == []
    assert r.stdout.splitlines()[0].split()[-3:] == ["words", "live", "cap"]
    # shown red where a column is doctored: the live column one more and one
    # fewer, the cap column, the instruction count
    for i, fix in ((0, lambda p: p[:-2] + [str(int(p[-2]) + 1), p[-1]]),
                   (3, lambda p: p[:-2] + [str(int(p[-2]) - 1), p[-1]]),
                   (7, lambda p: p[:-1] + [str(int(p[-1]) + 1)]),
                   (11, lambda p: p[:3] + [str(int(p[3]) + 1)] + p[4:])):
        bad = list(rows)
        bad[i] = " ".join(fix(bad[i].split()))
        found = _check_listing(bad)
        assert len(found) >= 1 and all(s.startswith("listing: ")
                                       for s in found), (i, found)
    # live past the cap is its own finding (pow fp64 rne: 31 against 30)
    p = rows[0].split()
    over = [" ".join(p[:-2] + [str(int(p[-2]) + 1), p[-1]])] + rows[1:]
    assert any("live past its cap" in s for s in _check_listing(over))


def _check_listing(rows):
    """[finding]: listing. Each row of `--only pow`'s listing (routine, format,
    attribute, instructions, words, live, cap) against the fragment itself: the
    instructions, words and live columns the fragment's own counts, the cap
    column POW_LIVE_CAP's (a table's, which the listing prints), and live not
    past the cap."""
    out = []
    names = {sf.RND_NAMES[r]: r for r in RND}
    for ln in rows:
        fn, fm, rn, ins, wds, live, cap = ln.split()
        f = fragment_of(fn, BY_NAME[fm], names[rn])
        if (int(ins), int(wds), int(live)) != (len(f), len(f.words),
                                               f.live_max()):
            out.append(f"listing: {ln!r}: the fragment has {len(f)}, "
                       f"{len(f.words)}, {f.live_max()}")
        if int(cap) != ml.POW_LIVE_CAP[fn][fm]:
            out.append(f"listing: {ln!r}: the cap is "
                       f"{ml.POW_LIVE_CAP[fn][fm]}")
        if int(live) > int(cap):
            out.append(f"listing: {ln!r}: live past its cap")
    return out


def test_check_prints_pow_lines_only_under_only_and_exits_1_on_a_difference(
        monkeypatch, capsys):
    for name in ("check_constants", "check_reduction_constants",
                 "check_reduction_tw_constants", "check_trig_constants",
                 "check_inv_constants", "_check_inv_tw_constants"):
        monkeypatch.setattr(ml, name, lambda *a, **k: ([], []))
    monkeypatch.setattr(ml, "check_pow_constants",
                        lambda *a, **k: (["a pow line"], ["pow x differs"]))
    assert ml.main(["--check"]) == 1
    shown = capsys.readouterr().out
    # the default run prints only the DIFFERENCE lines of pow, and none of the
    # lines every other check prints is changed (no pow line of its own)
    assert "DIFFERENCE: pow x differs" in shown
    assert "a pow line" not in shown and "(pow)" not in shown
    assert ml.main(["--check", "--only", "pow"]) == 1
    shown = capsys.readouterr().out.splitlines()
    assert shown == ["a pow line", "DIFFERENCE: pow x differs",
                     f"mathlib --check (pow): {len(FUNCS)} routines, "
                     "3 formats, 1 differences"]
    monkeypatch.setattr(ml, "check_pow_constants",
                        lambda *a, **k: (["a pow line"], []))
    assert ml.main(["--check"]) == 0
    assert "pow" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        ml.main(["--check", "--only", "nonesuch"])
    assert "pow" in capsys.readouterr().err



# =====================================================================
# every leg of every check fails alone on a doctored input
# =====================================================================

MARK = ml.MARK


def _doctor(results, i, bits=0, orwith=0, andnot=0):
    out = list(results)
    b, f = out[i]
    out[i] = ((b ^ bits), (f | orwith) & ~andnot)
    return out


def test_each_leg_of_pools_can_fail_alone():
    f = fragment_of("pow", FP64, RNE)
    xs = list(P.pool("pow", FP64))[:300]
    clean = [ml.evaluate(f, x) for x in xs]
    out, t = P.check_pools(f, xs, results=clean)
    assert out == [] and t.n == 300 and t.wrong == []
    un = next(i for i, (_b, fl) in enumerate(clean) if not fl & MARK)
    mk = next(i for i, (_b, fl) in enumerate(clean) if fl & MARK)
    cases = {
        # an unmarked lane wrong in its bits, in its flag word alone
        "1 unmarked lanes differ from transcend.pow":
            _doctor(clean, un, bits=1),
        "1 unmarked lanes differ from transcend.pow ":
            _doctor(clean, un, orwith=0x01),
        # a flag word with a bit outside [4:0] and the mark: on a MARKED lane,
        # whose guess is compared under the mask
        "1 flag words carry bits other than [4:0] and the mark":
            _doctor(clean, mk, orwith=0x20),
    }
    for text, results in cases.items():
        out, t = P.check_pools(f, xs, results=results)
        assert len(out) == 1 and text.strip() in out[0] \
            and out[0].startswith("pools: "), (text, out)
    # a marked lane's guess is replayed and counted, and is not a finding
    out, t = P.check_pools(f, xs, results=_doctor(clean, mk, bits=1))
    assert out == [] and len(t.guess_wrong) >= 1
    # the pins: the lanes' count and the marks' count are the model's
    out, t = P.check_pools(f, xs, results=clean, size=301)
    assert len(out) == 1 and "300 lanes, the model's pool has 301" in out[0]
    n_marked = len(t.marked)
    out, t = P.check_pools(f, xs, results=clean, marks=n_marked + 1)
    assert len(out) == 1 and f"{n_marked} lanes marked, the model's count " \
        f"is {n_marked + 1}" in out[0]
    # a part of the pool pins nothing by default; the whole pool pins both
    assert P.check_pools(f, xs, results=clean)[0] == []
    bad = fragment_of("pow", FP64, RNE, "mark_silenced")
    out, t = P.check_pools(bad)
    assert any("0 lanes marked, the model's count is 129" in s for s in out)


def test_each_leg_of_regions_can_fail_alone():
    f = fragment_of("pow", FP64, RNE)
    regs = {"wide": P.region(FP64, "pow", "wide", 6, 1),
            "negint": P.region(FP64, "pow", "negint", 6, 1)}
    out, (n, marked) = P.check_regions(f, regs, first=[])
    assert out == [] and n == 12
    # an unmarked lane wrong in one region names the region
    lane = regs["negint"][0]
    out, _ = P.check_regions(f, regs, first=[], evaluator=lambda g, x: (
        lambda r: (r[0] ^ 1, r[1]) if x == lane and not r[1] & MARK else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "negint: 1 of 6 unmarked lanes differ from " \
        "transcend.pow" in out[0] and out[0].startswith("regions: ")
    # the first design's lanes, by name, alone (no region)
    side = fragment_of("pow", FP64, RUP, "side_rule_off")
    out, (n, _m) = P.check_regions(side, {})
    assert n == 6 and len(out) == 2 \
        and "the first design's lane pow(6/5, minSub)" in out[0] \
        and "pow(5/6, -minSub)" in out[1] \
        and all(s.startswith("regions: ") for s in out)
    # zero_sign_lost is the study's item 7, the lane pow(-67.6, -177)
    zs = fragment_of("pow", FP64, RNE, "zero_sign_lost")
    out, _ = P.check_regions(zs, {})
    assert len(out) == 1 and "pow(-67.6, -177)" in out[0]
    # integrality_wide is item 2's
    iw = fragment_of("pow", FP64, RNE, "integrality_wide")
    out, _ = P.check_regions(iw, {})
    assert any("0x389 ulp" in s for s in out)
    # marked lanes are counted, not failures
    out, (n, marked) = P.check_regions(f, regs, first=[], evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x90))(ml.evaluate(g, x)))
    assert out == [] and marked == 12


def test_each_leg_of_specials_can_fail_alone():
    frags = {r: fragment_of("pow", FP64, r) for r in RND}
    out, n = P.check_specials(FP64, "pow", frags)
    assert out == [] and n > 1000
    inf = sf.inf_bits(FP64)
    # a row: a flag word
    out, _ = P.check_specials(FP64, "pow", frags, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] ^ 1) if x == (inf, sf.one_bits(FP64)) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row 'x = +-inf': 5 unmarked lanes differ" \
        in out[0] and out[0].startswith("specials: ")
    # a row: the bits
    y1 = (P._V(FP64, 0, 3, -2), sf.one_bits(FP64))
    out, _ = P.check_specials(FP64, "pow", frags, evaluator=lambda g, x: (
        lambda r: (r[0] ^ 1, r[1]) if x == y1 else r)(ml.evaluate(g, x)))
    assert len(out) == 1 and "row 'y = 1: x itself (exact)'" in out[0]
    # a mark in a row that marks nothing, and a row's marks that are missing
    out, _ = P.check_specials(FP64, "pow", frags, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | MARK | 0x10)
        if x == (inf, sf.one_bits(FP64)) else r)(ml.evaluate(g, x)))
    assert len(out) == 1 and "row 'x = +-inf'" in out[0] \
        and "5 marks over the five attributes, the model's 0" in out[0]
    out, _ = P.check_specials(FP64, "pow", frags, marks={
        **P.SPECIAL_MARKS["pow"], "subnormal operands": 4})
    assert len(out) == 1 and "subnormal operands" in out[0] \
        and "5 marks over the five attributes, the model's 4" in out[0]
    # a part of the attributes counts no marks (the plants' scope)
    assert P.check_specials(FP64, "pow", {RNE: frags[RNE]})[0] == []
    # the model's marks: the three rows of pow, the one of powr
    assert P.SPECIAL_MARKS["pow"]["subnormal operands"] == 5
    assert set(P.SPECIAL_MARKS["powr"]) == {"subnormal operands"}
    # powr's own rows
    labels = [lab for lab, _ in P.special_rows("powr", FP64)]
    assert "powr: x < 0 (every y, qNaN included)" in labels


def test_each_leg_of_structured_can_fail_alone():
    f = fragment_of("pow", FP64, RNE)
    rows = P.structured_rows("pow", FP64)
    out, n = P.check_structured(f, rows=rows)
    assert out == [] and n > 100

    def ev(fix):
        return lambda g, x: fix(x, *ml.evaluate(g, x))
    exact = dict((lab, ls) for lab, ls, e in rows)
    two3 = exact["exact powers of two (2^n, 0.5^n, integer t, both signs of "
                 "n)"][0]
    pow2 = [("2^n", [two3], "decided")]
    # decided: marked, and unmarked but wrong
    out, _ = P.check_structured(f, rows=pow2, evaluator=ev(
        lambda x, b, fl: (b, fl | MARK | 0x10)))
    assert len(out) == 1 and "is marked, the design decides it" in out[0] \
        and out[0].startswith("structured: ")
    out, _ = P.check_structured(f, rows=pow2, evaluator=ev(
        lambda x, b, fl: (b ^ 1, fl)))
    assert len(out) == 1 and "unmarked (" in out[0] and "want (" in out[0]
    # marked: not marked
    fam = exact["exact cases that must mark by family"]
    famrow = [("family", fam, "marked")]
    out, _ = P.check_structured(f, rows=famrow, evaluator=ev(
        lambda x, b, fl: (b, fl & 0x1F)))
    assert len(out) == 1 and "4 of 4 lanes wrong" in out[0] \
        and "is not marked, the in-lane test cannot decide it" in out[0]
    # nearest: a neighbour marked under rne (decided) but not under rtz (free)
    nb = exact["their neighbours one ulp of x or y away"][0]
    nbrow = [("neighbour", [nb], "nearest")]
    mark_nb = ev(lambda x, b, fl: (b, fl | MARK | 0x10))
    out, _ = P.check_structured(f, rows=nbrow, evaluator=mark_nb)
    assert len(out) == 1 and "is marked, the design decides it" in out[0]
    out, _ = P.check_structured(fragment_of("pow", FP64, RTZ), rows=nbrow,
                                evaluator=mark_nb)
    assert out == []
    # midpoint: unmarked under rne is a finding (the design cannot decide it),
    # and under rtz it is free
    mid = exact["3^2's neighbours in x: within the bound of a midpoint"]
    midrow = [("midpoint", mid, "midpoint")]
    strip = ev(lambda x, b, fl: (b, fl & 0x1F))
    out, _ = P.check_structured(f, rows=midrow, evaluator=strip)
    assert len(out) == 1 and "is not marked" in out[0]
    # free: an unmarked wrong answer, a marked one is not a finding
    freerow = [("a free lane", [two3], "free")]
    out, _ = P.check_structured(f, rows=freerow, evaluator=ev(
        lambda x, b, fl: (b ^ 1, fl)))
    assert len(out) == 1 and "'a free lane'" in out[0]
    assert P.check_structured(f, rows=freerow, evaluator=ev(
        lambda x, b, fl: (b ^ 1, fl | MARK | 0x10)))[0] == []
    # the lanes beside 1 are decided on the side below the gate and free above
    labels = {lab: e for lab, _ls, e in rows}
    assert labels["beside 1, t below 2^-(p+3) (the gate, both signs of y)"] \
        == "decided"
    assert labels["beside 1, t above the gate"] == "free"


def test_each_leg_of_seq_can_fail_alone():
    f = fragment_of("pow", FP64, RNE)
    one, two, three = sf.one_bits(FP64), P._V(FP64, 0, 1, 1), \
        P._V(FP64, 0, 3, 0)
    mx = sf.max_normal_bits(FP64)
    # max_normal with y = 0 is the lane a loud first rounded instruction shows
    # on: its early multiplication overflows (flags 0x14), the flag word of
    # pow(x, 0) = 1 is quiet
    xs = [(three, two), (two, three), (mx, 0), (one, one)]
    rows = []
    out, lanes = P.check_seq(f, xs, rows=rows)
    assert out == [] and len(lanes) == 4
    out, lanes = P.check_seq(f, xs)
    assert out == [] and len(lanes) == 7       # the exact families added
    # the evaluator: seq.py and evaluate() differ
    out, _ = P.check_seq(f, xs, rows=rows, evaluator=lambda g, x: (
        ml.evaluate(g, x)[0] ^ 1, ml.evaluate(g, x)[1]))
    assert len(out) == 1 and "seq.py and evaluate() differ on 4 lanes" \
        in out[0] and out[0].startswith("seq: ")
    # a flag left loud: outside QUIET, the first rounded instruction raises
    out, _ = P.check_seq(f, xs, rows=rows, loud=True)
    assert out and all("raised" in s for s in out)
    assert any("lane (0x7fefffffffffffff, 0x0) raised 0x14, want 0x0" in s
               for s in out), out
    assert P.check_seq(f, xs, rows=rows, loud=False)[0] == []
    # FLAGS is not the OR of the lanes' bytes
    out, _ = P.check_seq(f, xs, rows=rows, post=lambda r: (
        setattr(r, "flags", r.flags ^ 1), r)[1])
    assert len(out) == 1 and "FLAGS" in out[0] and "OR of the lanes" in out[0]
    # STATUS[6] and a marked lane disagree
    out, _ = P.check_seq(f, xs, rows=rows, post=lambda r: (
        setattr(r, "status", r.status ^ 0x40), r)[1])
    assert len(out) == 1 and "STATUS[6]" in out[0]
    # a fragment wrong the same way on seq.py and in evaluate(): the unmarked
    # lanes differ from transcend.py, in the result and the deposit
    bad = fragment_of("pow", FP64, RNE, "log_table_entry")
    out, _ = P.check_seq(bad, [(three, three)], rows=rows)
    assert any("unmarked lanes on seq.py differ from transcend.pow" in s
               for s in out) and any("deposited" in s for s in out)
    assert not any("seq.py and evaluate()" in s for s in out)
    # the committed lanes that must be marked are marked in the byte: a
    # fragment that never marks them is red here
    silent = fragment_of("pow", FP64, RNE, "mark_silenced")
    out, _ = P.check_seq(silent, [(one, one)])
    assert any("committed lanes are not marked in the lane's byte" in s
               for s in out)


def test_each_leg_of_bound_can_fail_alone():
    b = build_of("pow", FP64, RNE)
    lanes = P.region(FP64, "pow", "edge", 8, 5)
    out, (worst, main, n) = P.check_bound(b, lanes)
    assert out == [] and main == n == 8 and worst < 0
    # a main-path lane past 1 Bv, every lane right in transcend.py's sense
    # (marked: the mark is where the bound is too tight)
    wide = build_of("pow", FP64, RNE, "bound_loose")
    out, _ = P.check_bound(wide, lanes)
    assert len(out) == 1 and "main-path lanes are past the bound" in out[0] \
        and out[0].startswith("bound: ")
    # a lane that differs from transcend.py with V right: the first design's
    # side rule off, pow(1.2, minSub) under rup
    side = build_of("pow", FP64, RUP, "side_rule_off")
    lane = dict(P.first_lanes("pow", FP64))["pow(6/5, minSub)"]
    out, (w, m, n) = P.check_bound(side, [lane])
    assert len(out) == 1 and "1 unmarked lanes differ from transcend.pow" \
        in out[0] and m == 1
    # the region that measures nothing is a finding, except the ones that
    # cannot reach the main path (hugey: the screens answer every lane)
    hugey = P.region(FP64, "pow", "hugey", 8, 3)
    out, (w, m, n) = P.check_bound(b, hugey, "hugey")
    assert out == [] and m == 0 and w < -1e8
    out, _ = P.check_bound(b, hugey, "wide")
    assert len(out) == 1 and "the region measures nothing" in out[0]
    # a product that overflowed to an infinity is a screened lane, not a crash
    # (the first full-size run of pow-bound met one in `hugey`), and so are
    # t_h0 at emax + 2 and at emin - p - 2 exactly, but not the lane before
    assert P._screened(FP64, {"th0": sf.inf_bits(FP64)})
    assert P._screened(FP64, {"th0": sf.inf_bits(FP64, 1)})
    assert P._screened(FP64, {"th0": P._enc(FP64, FP64.emax + 2)})
    assert not P._screened(FP64, {"th0": P._enc(FP64, FP64.emax + 1)})
    assert P._screened(FP64, {"th0": P._enc(FP64, FP64.emin - 53 - 2)})
    assert not P._screened(FP64, {"th0": P._enc(FP64, FP64.emin - 53 - 1)})
    # V exact: a lane where V equals the true value contributes no ratio
    four = (P._V(FP64, 0, 1, 1), P._V(FP64, 0, 2, 0))
    assert P.bound_log2(b, four) is None
    # V is the scaled domain's: the probes of 2^3 are not 8 (k = floor(n/8))
    assert P.value(FP64, b.run(four, ("Vh",))[2]["Vh"]) == 1


def test_each_leg_of_shape_can_fail_alone():
    builds = {("pow", r): build_of("pow", FP64, r) for r in RND}
    assert P.check_shape(FP64, builds) == []

    def legs(text, tables, n):
        out = P.check_shape(FP64, builds, tables=tables)
        assert len(out) == n and all(text in s and s.startswith("shape: ")
                                     for s in out), (text, out)
    shape = dict(P.SHAPE)
    shape[("pow", "fp64")] = [(435, 129, 30)] + P.SHAPE[("pow", "fp64")][1:]
    legs("pinned 435, 129, 30", P.Tables(shape=shape), 1)
    legs("instructions by phase differ from the model's",
         P.Tables(phases=lambda fn, name, rnd: dict(
             P.model_phases(fn, name, rnd), Z=5)), 5)
    legs("Fast2Sums and 0 TwoSums, the model's 27", P.Tables(eft={
        **P.EFT, ("pow", "fp64"): (27, 0)}), 5)
    legs("the flag word takes", P.Tables(flag_words={
        "pow": P.FLAG_WORDS["pow"] | {0x20}}), 5)
    legs("the design's 1 and 0", P.Tables(min_max={"pow": (1, 0)}), 5)
    legs("the design's 0 and 1", P.Tables(min_max={"pow": (0, 1)}), 5)
    legs("the cap is 31", P.Tables(caps={
        **ml.POW_LIVE_CAP, "pow": {**ml.POW_LIVE_CAP["pow"], "fp64": 31}}), 1)
    # a cap one under fails by name; the cap itself holds
    f = ml.fragment("pow", FP64, RNE)
    assert ml.invariants(f, live_cap=30) == []
    assert ml.invariants(f, live_cap=29) == ["30 values live at once, past 29"]
    out = P.check_shape(FP64, builds, tables=P.Tables(caps={
        **ml.POW_LIVE_CAP, "pow": {**ml.POW_LIVE_CAP["pow"], "fp64": 29}}))
    assert any("the cap is 29, the most values live under any attribute is "
               "30" in s for s in out)
    assert any("invariants: 30 values live at once, past 29" in s
               for s in out)
    # no MIN, no MAX: counted in the fragment
    assert f.counts().get("min", 0) == 0 and f.counts().get("max", 0) == 0


def test_the_reorder_leg_of_shape_fails_alone_on_a_doctored_fragment():
    builds = {("pow", r): build_of("pow", FP64, r) for r in RND}
    frags = {k: b.fragment() for k, b in builds.items()}
    key = ("pow", RNE)
    g = frags[key]
    # still a topological order, one value changed (renumbered operand)
    out = P.check_shape(FP64, builds,
                        fragments={**frags, key: ml._misnumbered(g)})
    assert out and all(s.startswith("shape: ") for s in out)
    assert any("reorder" in s and "dataflow graph is not the design's" in s
               for s in out)
    # an order that reads a value before it is defined
    out = P.check_shape(FP64, builds,
                        fragments={**frags, key: ml._forward(g)})
    assert any("not a topological order" in s for s in out)


def test_each_leg_of_core_can_fail_alone():
    lanes = P.core_lanes(FP64)[:12]
    base = P.core_of(FP64, RNE, None, True)

    class Doctored:
        meta = base.meta
        fmt = base.fmt

        def __init__(self, fix):
            self.fix = fix

        def run(self, lane, want=()):
            vh, vl, pr = base.run(lane, want)
            return self.fix(vh, vl, dict(pr))
    out, (worst, n) = P.check_core(FP64, lanes=lanes,
                                   b=Doctored(lambda a, b_, c: (a, b_, c)))
    assert out == [] and n == 12 and worst < -4
    # the bound leg alone: V_h one ulp up on every lane
    out, _ = P.check_core(FP64, lanes=lanes, b=Doctored(
        lambda vh, vl, pr: (vh, vl, {**pr, "Vh": pr["Vh"] + 1})))
    assert len(out) == 1 and "lanes are past the bound" in out[0] \
        and out[0].startswith("core: ")
    # the low word of one sign only: the lanes' y_l made positive
    pos = [(x, yh, yl & ~FP64.sign_mask) for x, yh, yl in lanes]
    out, _ = P.check_core(FP64, lanes=pos, b=base)
    assert len(out) == 1 and "only one sign" in out[0]
    # the plain build alone: a fault (1/ln 2's word) the core's build does not
    # have, found on the same x and y_h
    out, _ = P.check_core(FP64, lanes=lanes, b=base,
                          plain=build_of("pow", FP64, RNE, "il2h_ulp"))
    assert len(out) == 1 and "the plain build is past the bound" in out[0]
    # y_l is read: the double word's lanes differ from the single word's
    lane = lanes[0]
    assert base.run(lane)[:2] != base.run((lane[0], lane[1], 0))[:2]
    # the Fraction ybound: the exact bound, upward rounded, and a doctored
    # one that is not
    out, n = P._check_ybound(FP64)
    assert out == [] and n == 24
    out, n = P._check_ybound(FP64, ybound=Fraction(1, 2))
    assert len(out) == 1 and "the Fraction ybound's Bv is not the exact " \
        "bound" in out[0] and out[0].startswith("core: ")
    assert P._check_ybound(FP128) == ([], 0)       # B2 is 0: no term built
    # ybound as a ref or a Fraction: Bv is the same to 2^-p, where both are made
    b0 = ml._pow_setup("pow_core", FP64, RNE, 44, 0, None)
    b0.inputs = ("a", "b")
    k_ = ml._pow_words(b0)
    cl = ml._classify_common(b0, k_)
    c0 = ml.pow_core(b0, k_, cl, ("in", "b"), None,
                     b0.iand(("in", "b"), k_["ABSM"]), negres=None,
                     sgnw=None, up=lambda: b0.icmplt(k_["ONE"], cl.ax))
    b0.finish(c0.Vh, c0.Vl)
    x, y = P._enc(FP64, Fraction(7, 10)), P._enc(FP64, 1000)
    bv_ref = P.value(FP64, b0.run((x, y), ("Bv",))[2]["Bv"])
    b1 = ml._pow_setup("pow_core", FP64, RNE, 44, 0, None)
    b1.inputs = ("a",)
    k1 = ml._pow_words(b1)
    cl1 = ml._classify_common(b1, k1)
    c1 = ml.pow_core(b1, k1, cl1, b1.word(y, "NH"), None, Fraction(1000),
                     negres=None, sgnw=None,
                     up=lambda: b1.icmplt(k1["ONE"], cl1.ax))
    b1.finish(c1.Vh, c1.Vl)
    bv_fr = P.value(FP64, b1.run(x, ("Bv",))[2]["Bv"])
    assert abs(bv_ref - bv_fr) <= bv_ref * Fraction(1, 2 ** 50)


def _fresh(fn, fmt, rnd, role=None, delta=1):
    """A fresh (never shared) build of fn with the word of `role` changed by
    `delta` in its bits."""
    b = ml.build(fn, fmt, rnd)
    if role is not None:
        name = b.roles[role][1]
        b.words[name] = (b.words[name] + delta) & ((1 << fmt.width) - 1)
    return b


def _constants_of(b):
    lines, findings = ml.check_pow_constants(
        builder=lambda n, f, r: b, formats=(b.fmt,), attrs=(b.rnd,),
        names=(b.meta["fn"],))
    return findings


def test_each_leg_of_constants_can_fail_alone():
    """The build with one word changed, one role at a time: the difference is
    named by fragment and word. Every kind of word: the table's, the
    coefficients (first, middle and last of each tail and head), 1/ln 2's and
    ln 2's, the screens, the bound's, the neighbours of 1, the responses, the
    integers."""
    assert _constants_of(_fresh("pow", FP64, RNE)) == []
    roles = ["LH3", "LL3", "LH0", "LY12", "LY24", "LY18", "LCH0", "LCL2",
             "LCH11", "LCL11", "IL2H", "NIL2H", "NIL2L", "LN2H", "NLN2H",
             "NLN2L", "TH3", "TL3", "TH0", "EY7", "EY13", "ECH0", "ECH6",
             "ECL6", "EIGHT", "NINV8", "MAGIC", "SIXTEEN", "SIXTEENTH",
             "NMAGIC16", "HALF", "NEGONE", "MINN", "P2P", "BREL", "B1", "B2",
             "TOVF", "TUNF", "TINYT", "NB00", "NB01", "NB10", "NB11",
             "OVFB_P", "OVFB_N", "UNFB_P", "UNFB_N", "SIGN", "SIGN_SHIFT",
             "MANTISSA_WIDTH", "MANTISSA_MASK", "K_OFFSET", "K_OFFSET_SUB",
             "C_WRAP", "KOFFSET", "KBIAS1", "K_EMIN_P1", "K_EMIN", "K_KD",
             "K_KD_P", "K_SUBMIN", "C0", "P2PM2", "P2PM1", "P2P_Y", "INF",
             "QNAN", "QBIT", "ABSM", "FL_INVALID", "FL_INEXACT",
             "FL_UNDER_INEXACT", "FL_OVER_INEXACT", "FL_MARK", "FL_DIVZERO",
             "I2", "I3", "I4", "I7", "INT1", "ONE"]
    for role in roles:
        b = _fresh("pow", FP64, RNE, role)
        assert role in b.roles, role
        found = _constants_of(b)
        assert found, role
        assert all(s.startswith(f"pow fp64 rne") for s in found), found[:2]
        assert any(f" {role}:" in s for s in found), (role, found[:2])
    # the rounding rule of each word, not only its value: one ulp the other way
    for role in ("LH5", "IL2H", "LN2H", "TH5", "EY9"):
        assert _constants_of(_fresh("pow", FP64, RNE, role, -1)), role
    # a word at fp128 and fp256 (B1 and B2 are not held there)
    for fmt in (FP128, FP256):
        for role in ("LH2", "LCH3", "IL2H", "TH7", "ECH2", "TOVF", "NB01",
                     "K_SUBMIN"):
            assert _constants_of(_fresh("powr", fmt, RMM, role)), (fmt, role)
        assert "B1" not in ml.build("pow", fmt, RNE).roles
    # powr: no sign words
    b = ml.build("powr", FP64, RNE)
    assert "SIGN" not in b.roles and "NB11" not in b.roles
    assert "OVFB_N" not in b.roles and "P2PM2" not in b.roles


def test_the_other_legs_of_constants_can_fail_alone():
    b = _fresh("pow", FP64, RNE)
    # the plan: GL, (KL, DL, KE, DE), B1 and B2, OFF, each from the meta
    for key, bad, text in (("GL", 48, "(GL, GE)"), ("DL", 25, "the plan"),
                           ("KE", 8, "the plan"), ("B1", Fraction(0), "(B1, "
                                                                  "B2)"),
                           ("OFF", 70, "OFF = 70")):
        c = _fresh("pow", FP64, RNE)
        c.meta[key] = bad
        found = _constants_of(c)
        assert any(text in s for s in found), (key, found)
        assert all(s.startswith("pow fp64 rne") for s in found)
    # a role no derivation asks: derived but not checked
    c = _fresh("pow", FP64, RNE)
    c.roles["EXTRA"] = c.roles["ZERO"]
    assert _constants_of(c) == ["pow fp64 rne: derived but not checked: "
                                "['EXTRA']"]
    # a word the fragment holds with no role: a stray word the result reads
    c = _fresh("pow", FP64, RNE)
    res = c.ixor(c.result, c.word(0x1234, "STRAY"))
    c.finish(res, c.flags)
    found = _constants_of(c)
    assert len(found) == 1 and "words the fragment holds with no role: " \
        "[('STRAY', '0x1234')]" in found[0]
    # a coefficient held where it is exact in one word, and B1 where it is 0
    c = ml.build("pow", FP128, RNE)
    c.roles["B1"] = c.roles["ONE"]
    c.roles["ECL0"] = c.roles["ZERO"]
    found = _constants_of(c)
    assert any("B1 is held, B1 is 0 where GL reached its target" in s
               for s in found)
    assert any("ECL0 is held, but the coefficient is exact in one word" in s
               for s in found)
    # a role the fragment lacks (a fault of the build: integrality_wide has no
    # P2PM2)
    found = _constants_of(ml.build("pow", FP64, RNE, plant="integrality_wide"))
    assert any("the fragment has no constant P2PM2" in s for s in found)
    # the scale words where they act: Ek, S1, S2 and the fixed grid's, on
    # lanes pow(2, n/8); a build whose OFF is not the one it was built with
    c = _fresh("pow", FP64, RNE)
    c.meta["OFF"] += 2
    found = _constants_of(c)
    assert any(" Ek = " in s for s in found), found[:3]
    ran = P.ml._check_pow_scale(_fresh("pow", FP64, RNE), [])
    assert ran == 63
    # the neighbours of 1 and the responses by the rules, per attribute
    p = 53
    assert ml._check_pow_neighbour(RNE, 0, 1, p) == 1
    assert ml._check_pow_neighbour(RTZ, 0, 1, p) == 1
    assert ml._check_pow_neighbour(RTZ, 0, 0, p) == 1 - Fraction(1, 2 ** p)
    assert ml._check_pow_neighbour(RDN, 1, 1, p) == -(1 + Fraction(1, 2 ** 52))
    assert ml._check_pow_neighbour(RUP, 1, 1, p) == -1
    assert ml._check_pow_responses(FP64, RNE, 0) == (0x7ff0000000000000, 0)
    assert ml._check_pow_responses(FP64, RTZ, 1) == (0xffefffffffffffff,
                                                     1 << 63)
    assert ml._check_pow_responses(FP64, RDN, 1) == (0xfff0000000000000,
                                                     (1 << 63) | 1)
    assert ml._check_pow_responses(FP64, RUP, 0) == (0x7ff0000000000000, 1)
    # the plan again, from exact rationals and the IEEE fields
    want, GL, KD, KDe, B1, B2 = ml._check_pow_plan(FP64, 44)
    assert (want, GL, KD, KDe) == (57, 47, (12, 24), (7, 13))
    assert (B1, B2) == (Fraction(1, 2 ** 100), Fraction(1, 2 ** 101))
    assert ml._check_pow_plan(FP128, 46)[1:3] == (63, (16, 42))
    assert ml._check_pow_plan(FP256, 46)[1:3] == (67, (17, 73))


# =====================================================================
# the plants: each red in its checks and green in the others
# =====================================================================

# Every row lists EVERY check, red or green (a test fails on a row that omits
# one). MEASURED on fp64 by this parcel: python/tests/mathlib_pow_harness.
# red_checks(plant) is the run (pools, specials and seq under rne; the regions
# at 6 lanes a region under rne, rtz and rup (side_rule_off's first-design
# lanes are directed ones); bound over the placed regions at 8 points a region
# under rne; structured and shape under all five attributes; core and
# constants under rne; exact_unmarked and midpoint_unmarked act under the nearest attributes
# only, rne and rmm, and their runs are under those: the others refuse them by
# name). GREEN means green at that scope, which is smaller than the clean
# tests'. The study's table (docs/studies/m3/plants.fp64.out.txt) is of named
# lanes, not of checks: each plant's named lane is reproduced below
# (test_the_studys_named_case_is_reproduced), and the checks that see it are
# these. Remarks that explain a cell the reader would not expect:
#   exact_unmarked   red in `specials` as well as pools: the lanes of the row
#                    "subnormal operands" are exact powers of two
#   midpoint_unmarked  red only in `shape`: it removes instructions and no lane
#                    differs from the control (redundant by design, the study's
#                    3.1: the fixed grid's midpoint is also a grid point of V's
#                    interval, which the nearest attributes' test marks)
#   side_rule_off    red in `regions` by the first design's lanes by name, in
#                    no pool (the study's 3.6, item 1: no pool reached it)
#   screen_ulp       red in `constants` alone: the word is one ulp off and no
#                    lane of any pool or region lies between the two screens
#   log_short        red in `bound` at fp128 and fp256 over the region rhoedge
#                    (test_log_short...), green in it at fp64 and here: its
#                    cells are fp64's
#   two_sum_all      red in `shape` alone: the same values, 3 more
#                    instructions each (a fault of the shape)
CHECKS = P.CHECKS
PLANTED = [
    ("exact_unmarked",
     ('pools', 'specials', 'structured', 'seq', 'shape'),
     ('regions', 'bound', 'core', 'constants')),
    ("exact_rule_off",
     ('pools', 'structured', 'shape'),
     ('regions', 'specials', 'seq', 'bound', 'core', 'constants')),
    ("exact_rule_no_tl",
     ('structured', 'seq', 'shape'),
     ('pools', 'regions', 'specials', 'bound', 'core', 'constants')),
    ("midpoint_unmarked",
     ('shape',),
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound', 'core', 'constants')),
    ("pow_zero_nan",
     ('pools', 'specials', 'structured', 'seq', 'shape'),
     ('regions', 'bound', 'core', 'constants')),
    ("pow_one_nan",
     ('pools', 'specials', 'structured', 'seq', 'shape'),
     ('regions', 'bound', 'core', 'constants')),
    ("sign_even",
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound'),
     ('shape', 'core', 'constants')),
    ("integrality_wide",
     ('regions', 'specials', 'structured', 'seq', 'bound', 'shape', 'constants'),
     ('pools', 'core')),
    ("sign_odd_lost",
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound', 'shape', 'constants'),
     ('core',)),
    ("powr_neg_ok",
     ('pools', 'specials', 'structured', 'seq', 'shape'),
     ('regions', 'bound', 'core', 'constants')),
    ("powr_zero_zero",
     ('pools', 'specials', 'structured', 'seq'),
     ('regions', 'bound', 'shape', 'core', 'constants')),
    ("near_one_gate_off",
     ('pools', 'structured', 'shape', 'constants'),
     ('regions', 'specials', 'seq', 'bound', 'core')),
    ("side_rule_off",
     ('regions', 'structured', 'shape', 'constants'),
     ('pools', 'specials', 'seq', 'bound', 'core')),
    ("screen_low",
     ('structured', 'seq', 'constants'),
     ('pools', 'regions', 'specials', 'bound', 'shape', 'core')),
    ("mark_silenced",
     ('pools', 'specials', 'structured', 'seq', 'shape'),
     ('regions', 'bound', 'core', 'constants')),
    ("bound_loose",
     ('pools', 'specials', 'structured', 'seq', 'bound', 'core', 'constants'),
     ('regions', 'shape')),
    ("zero_sign_lost",
     ('regions', 'structured', 'seq', 'bound', 'shape'),
     ('pools', 'specials', 'core', 'constants')),
    ("log_table_entry",
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound', 'core', 'constants'),
     ('shape',)),
    ("il2h_ulp",
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound', 'core', 'constants'),
     ('shape',)),
    ("screen_ulp",
     ('constants',),
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound', 'shape', 'core')),
    ("y_one_loud",
     ('pools', 'specials', 'structured', 'seq'),
     ('regions', 'bound', 'shape', 'core', 'constants')),
    ("two_sum_all",
     ('shape',),
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound', 'core', 'constants')),
    ("log_short",
     ('shape', 'constants'),
     ('pools', 'regions', 'specials', 'structured', 'seq', 'bound', 'core')),
]


def _row_id(r):
    return r[0]


@functools.lru_cache(maxsize=None)
def _red(plant, fmt_name="fp64"):
    return P.red_checks(plant, BY_NAME[fmt_name])


def test_the_control_is_green_in_every_check():
    red = _red(None)
    assert red == {}, {k: v[:1] for k, v in red.items()}


@pytest.mark.parametrize("row", PLANTED, ids=_row_id)
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
    assert set(named) == POW_PLANT_NAMES == (set(ml.POW_PLANTS)
                                             - M3G2_PLANT_NAMES)
    assert len(named) == len(set(named)) == 22 + 1
    for row in PLANTED:
        _check_row(row)
    # the row check itself is shown to refuse a row that omits a check, one
    # that names a check red and green, and one red in nothing
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
    # and a clean test for each check
    for name in ("test_pools", "test_regions", "test_specials",
                 "test_structured", "test_seq", "test_bound", "test_shape",
                 "test_core", "test_constants_in_process"):
        assert callable(globals()[name]), name
    # the budget plants of parcel M3G3: bound_tight and zone_bound_off are
    # red in the first-order budget alone and are not here; log_short is, for
    # the direct bound sees it
    assert "bound_tight" not in ml.POW_PLANTS
    assert "zone_bound_off" not in ml.POW_PLANTS
    assert "log_short" in ml.POW_PLANTS


def test_log_short_is_red_in_bound_over_rhoedge_at_fp128_and_fp256():
    """The study's 3.6, item 8: the logarithm planned at G is green in `wide`
    and red where L is the polynomial's term alone with |r| near its rho
    (x in [0.94, 0.97]) and |t| is large. MEASURED here: past 1 Bv at fp128 and
    fp256, green at fp64 (where B1 and B2 carry it) and in `wide`."""
    for fmt in (FP128, FP256):
        b = build_of("pow", fmt, RNE, "log_short")
        assert b.meta["GL"] == b.meta["G"]
        lanes = P.region(fmt, "pow", "rhoedge", 48, 11)
        out, (worst, main, n) = P.check_bound(b, lanes, "rhoedge")
        assert len(out) == 1 and "main-path lanes are past the bound" in out[0]
        assert worst > 0, worst
        lanes = P.region(fmt, "pow", "wide", 48, 11)
        out, (worst, main, n) = P.check_bound(b, lanes, "wide")
        assert out == [] and worst < 0
        clean = build_of("pow", fmt, RNE)
        out, (worst, _m, _n) = P.check_bound(
            clean, P.region(fmt, "pow", "rhoedge", 48, 11), "rhoedge")
        assert out == [] and worst < -5
    b = build_of("pow", FP64, RNE, "log_short")
    out, _ = P.check_bound(b, P.region(FP64, "pow", "rhoedge", 48, 11))
    assert out == []


def test_the_plants_that_do_not_reach_the_core_are_refused_by_name():
    for plant in ml.POW_PLANTS:
        if plant in CORE_PLANTS | {"log_short"}:
            b = ml.build_pow_core(FP64, RNE, plant=plant)
            assert b.meta["plant"] == plant
        else:
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to pow_core at fp64: the fault is not "
                               f"reached"):
                ml.build_pow_core(FP64, RNE, plant=plant)
    with pytest.raises(ValueError, match="no_such_plant"):
        ml.build_pow_core(FP64, plant="no_such_plant")


def test_a_plant_the_build_cannot_reach_is_refused_by_name(monkeypatch):
    monkeypatch.setitem(ml.POW_PLANTS, "ghost", "a fault pow cannot have")
    with pytest.raises(ValueError, match="plant 'ghost' does not apply to "
                       "pow at fp128: the fault is not reached"):
        ml.build("pow", FP128, RNE, plant="ghost")
    with pytest.raises(ValueError, match="does not apply to pow_core"):
        ml.build_pow_core(FP64, plant="ghost")
    monkeypatch.undo()
    # powr's plants in pow, pow's in powr, and the nearest attributes' two
    # under the directed ones
    for plant in ("powr_neg_ok", "powr_zero_zero"):
        with pytest.raises(ValueError, match=f"plant {plant!r} does not apply "
                           f"to pow at fp64"):
            ml.build("pow", FP64, RNE, plant=plant)
        assert ml.build("powr", FP64, RNE, plant=plant).meta["plant"] == plant
    for plant in ("sign_even", "integrality_wide", "sign_odd_lost",
                  "pow_zero_nan", "pow_one_nan", "zero_sign_lost"):
        with pytest.raises(ValueError, match=f"plant {plant!r} does not apply "
                           f"to powr at fp64"):
            ml.build("powr", FP64, RNE, plant=plant)
        assert ml.build("pow", FP64, RNE, plant=plant).meta["plant"] == plant
    for plant in ("exact_unmarked", "midpoint_unmarked"):
        for rnd in (RTZ, RDN, RUP):
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to pow at fp64"):
                ml.build("pow", FP64, rnd, plant=plant)
        for rnd in (RNE, RMM):
            assert ml.build("pow", FP64, rnd, plant=plant).meta["plant"] == \
                plant


def test_every_plant_changes_the_build():
    """A plant that did nothing would pass every row green: each is a
    different build from the clean one, in its body or its words."""
    for plant in sorted(POW_PLANT_NAMES):
        fn = P.plant_fn(plant)
        clean = build_of(fn, FP64, RNE)
        b = build_of(fn, FP64, RNE, plant)
        same = (b.body == clean.body and b.words == clean.words
                and b.result == clean.result and b.flags == clean.flags)
        assert not same, plant


def _state(fmt, fn, lane, rnd, plant):
    f = fragment_of(fn, fmt, rnd, plant)
    bits, fw = ml.evaluate(f, lane)
    want = P.golden(fmt, rnd, lane, fn)
    if fw & MARK:
        return "marked", bits, fw
    return ("right" if (bits, fw) == want else "WRONG"), bits, fw


# the lanes of the plants' named cases that a format has: all 20 rows at fp64
# and fp128, 19 at fp256
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_studys_named_case_is_reproduced(fmt):
    n_lane = n_mark = n_redundant = 0
    for plant, fn, rnd, kind, lane in P.plant_cases(fmt):
        if lane is None:
            # the only row without a lane: midpoint_unmarked's at fp256 (the
            # study printed "no lane at this format"); fp64 and fp128 have it
            assert (plant, fmt.name) == ("midpoint_unmarked", "fp256")
            continue
        ctl = _state(fmt, fn, lane, rnd, None)
        got = _state(fmt, fn, lane, rnd, plant)
        if kind == "lane":
            assert got[0] == "WRONG" and ctl[0] in ("right", "marked"), \
                (plant, fmt.name, ctl, got)
            n_lane += 1
        elif kind == "mark":
            assert got[0] == "marked" and ctl[0] == "right", \
                (plant, fmt.name, ctl, got)
            n_mark += 1
        else:
            # redundant by design: equal to the control, shown equal, and not
            # counted (the study's 3.1)
            assert got == ctl, (plant, fmt.name, ctl, got)
            n_redundant += 1
    # at fp64: 19 counted cases (the study's 22 less rootn's and compound's
    # two and midpoint_unmarked's), every one found
    if fmt.name == "fp64":
        assert (n_lane, n_mark, n_redundant) == (16, 3, 1)
        rows = [r for r in P.plant_cases(fmt) if r[4] is not None
                and r[3] != "redundant"]
        assert len(rows) == 19


def test_the_plants_cases_name_the_study_s_plants():
    names = {plant for plant, *_ in P.plant_cases(FP64)}
    assert names == POW_PLANT_NAMES - {"log_table_entry", "il2h_ulp",
                                       "screen_ulp", "y_one_loud",
                                       "two_sum_all", "log_short"}
    assert len(names) == 17
    kinds = {k for _p, _f, _r, k, _l in P.plant_cases(FP64)}
    assert kinds == {"lane", "mark", "redundant"}


# =====================================================================
# the commands of mathlib_runs.py
# =====================================================================

def test_the_pow_commands_run_at_small_sizes_and_refuse_an_existing_out(
        tmp_path, capsys):
    import mathlib_runs as R
    out = tmp_path / "pools.txt"
    R.FINDINGS.clear()
    R.main(["pow-pools", "--quick", "--out", str(out)])
    shown = capsys.readouterr().out
    assert "pow-pools pow fp128 rne:" in shown and "RESULT: ok" in shown
    assert "pow-pools powr fp128 rtz:" in shown and "peak memory" in shown
    assert "pow-regions pow fp128 rne seed 1: 12 regions, 149 lanes" in shown
    text = out.read_text(encoding="utf-8")
    assert "pow-pools pow fp128 rtz:" in text
    # an output path that exists is refused, before any work
    with pytest.raises(SystemExit, match="the file exists"):
        R.main(["pow-pools", "--quick", "--out", str(out)])
    R.FINDINGS.clear()
    R.OUT = None
    out2 = tmp_path / "bound.txt"
    R.main(["pow-bound", "--quick", "--formats", "fp64", "--fn", "pow",
            "--out", str(out2)])
    shown = capsys.readouterr().out
    assert "pow-bound pow fp64 rne wide seed 121: 12 lanes" in shown
    assert "a sampled lower bound" in shown and "RESULT: ok" in shown
    assert "pow-bound pow fp64 rne hugey seed 129: NOT MEASURED (0 " \
        "main-path lanes of 12" in shown
    assert "11 regions measured (the pass count), 1 NOT MEASURED (0 " \
        "main-path lanes), outside it" in shown        # pow has 12 regions
    assert "pow-bound pow fp64 rne wide seed 121: 12 lanes" in shown
    with pytest.raises(SystemExit, match="the file exists"):
        R.main(["pow-bound", "--quick", "--out", str(out2)])
    R.OUT = None
    R.FINDINGS.clear()
    with pytest.raises(SystemExit, match="fp64, fp128 or fp256"):
        R.main(["pow-pools", "--formats", "fp16"])
    with pytest.raises(SystemExit, match="parcel M3F2's"):
        # pow-bound's default --fn holds all five names (parcel M3G2), and at
        # fp32 pown, rootn and compound are parcel M3F2's (since wave 2's merge)
        R.main(["pow-bound", "--formats", "fp32"])
    with pytest.raises(SystemExit, match="parcel M3F2's"):
        R._pow_formats("fp32", [], ["pow", "pown"])
    with pytest.raises(SystemExit, match="rootn.x, 0. is invalid for every x"):
        R.main(["pow-bound", "--fn", "rootn", "--ns", "0"])
    # --seq runs the compiled shape over the same lanes, --lanes sizes the
    # regions (0: none) and --step takes part of the pool
    R.FINDINGS.clear()
    R.main(["pow-pools", "--formats", "fp64", "--fn", "powr", "--attrs",
            "rne", "--seq", "--step", "40", "--lanes", "0"])
    shown = capsys.readouterr().out
    assert "seq.py and the compiled shape over" in shown \
        and "0 findings" in shown and "pow-regions" not in shown
    R.main(["pow-pools", "--formats", "fp64", "--fn", "powr", "--attrs",
            "rne", "--step", "40", "--lanes", "5", "--seed", "3"])
    shown = capsys.readouterr().out
    assert "pow-regions powr fp64 rne seed 3: 10 regions, 50 lanes" in shown
    R.FINDINGS.clear()
    R.OUT = None
