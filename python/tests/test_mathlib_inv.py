# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""atan, and the core of atan, asin, acos and atan2, of python/cft_golden/
mathlib.py (parcel M4G1, M4's build, wave 1) at fp64, fp128 and fp256, held to
the study's section 8 (docs/studies/M4-invtrig.md): quick enough for the golden
stage; the larger runs are `python python/tests/mathlib_runs.py inv-pools` and
`inv-bound`. Parcels M4G2 (asin, acos) and M4G3 (atan2) add a test file of
their own, each with its own table of plants, and import this file's helpers
and the harness's by function.

The checks are python/tests/mathlib_inv_harness.py's, each returning findings
that begin with its own name; the lanes are the unary pool (333, 285 and 285
arguments), the seq slice, the study's placed regions, the committed
structured lanes and the audit's. Nine checks:

  pools  seq  bound  structured  specials  shape  audit  core  constants

and for every check a planted fault shown red in it, the control green in all
(mathlib.INV_PLANTS: twelve), every leg of every check shown failing alone on a
doctored input, the interface, the refusals, the two-input evaluate, the
phases, the scheduler's choice, the `--check` output and the two commands of
mathlib_runs.py. The port against the study's model is a scratch script of the
parcel's entry (nothing here imports docs/studies/m4): the dag digests of the
fifteen fragments, recorded when it passed, are pinned below.
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
from cft_golden.formats import FpFormat  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_inv_harness as I  # noqa: E402

PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
FORMATS = I.FORMATS
FUNCS = I.FUNCS
RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = I.RNE, I.RTZ, I.RDN, I.RUP, I.RMM
BY_NAME = I.BY_NAME


def fid(f):
    return f.name


def rid(r):
    return sf.RND_NAMES[r]


build_of = I.build_of
fragment_of = I.fragment_of

# ---- what the study states and the model measured ----------------------------
POOL_SIZES = {"fp64": 333, "fp128": 285, "fp256": 285}
PLAN = {"fp64": (6, 12), "fp128": (6, 20), "fp256": (6, 35)}
GUARD = {"fp64": 44, "fp128": 46, "fp256": 46}
# the dag digest of each atan fragment (the first 32 hex digits), equal to the
# study's model's `to_fragment()` digest at the port (docs/studies/m4/m4inv.py
# at 0f336e45, the parcel's scratch script: 15 of 15, with the lane compare)
DIGESTS = {
    "fp64/rne": "256968880ab686ff97d8a69bac0fb357",
    "fp64/rtz": "b4cdaf0442da70f17e5f8a9893446687",
    "fp64/rdn": "a06c074a6d0706fc7392646c899e75ce",
    "fp64/rup": "d5ab14a08fa46dc5165e1b58269a2403",
    "fp64/rmm": "02cb1608b86913b6f2e94b880b90e1d7",
    "fp128/rne": "65c64c8b7ff762c7581e361ba6cc6a54",
    "fp128/rtz": "c641792f1b51480fa474be678860107b",
    "fp128/rdn": "336f0470f912bb0fb1f96b89cc1acb55",
    "fp128/rup": "1188e951d9e1c3fe61988217799065d0",
    "fp128/rmm": "53bee1440b05f0eb3c2f5a88f12b4a75",
    "fp256/rne": "1803fbf2edfa4f1fbdc2b508451baa59",
    "fp256/rtz": "ce8586c45829038367833d46f55441ea",
    "fp256/rdn": "db898f3266e84b7e6fa569939b82f1bc",
    "fp256/rup": "58ec77e620c6c7c7963ad0b9794838c5",
    "fp256/rmm": "1c554806d12ee374282820d49df98bba",
}
# the golden stage's configurations: the pools through all fifteen, seq at
# fp64, fp128 and fp256 under rne and rtz
POOL_CONFIGS = [(f, r) for f in FORMATS for r in RND]
SEQ_CONFIGS = [(f, r) for f in FORMATS for r in (RNE, RTZ)]
INV_PLANT_NAMES = {
    "table_entry", "coef", "newton_short", "sterbenz_bias", "zl_dropped",
    "sl_dropped", "pio2_low", "bound_loose", "mark_silenced", "tiny_gate_off",
    "tiny_side", "two_sum_all"}
# the plants inv_core acts on (build_inv_core accepts them; the others are
# refused by name there, "does not apply")
CORE_PLANTS = {"table_entry", "coef", "newton_short", "sterbenz_bias",
               "zl_dropped", "sl_dropped", "two_sum_all"}


def _doctor(results, i, bits=0, orwith=0, andnot=0):
    out = list(results)
    b, f = out[i]
    out[i] = ((b ^ bits), (f | orwith) & ~andnot)
    return out


# =====================================================================
# the interface
# =====================================================================

INTERFACE = ("INV_NAMES", "INV_FORMATS", "INV_LIVE_CAP", "INV_PLANTS",
             "inv_cells", "inv_rho", "plan_inv", "inv_core", "inv_recon",
             "inv_final", "build_inv_core", "check_inv_constants")


def test_the_interface_is_public_and_documented():
    for name in INTERFACE:
        assert name in ml.__all__, name
        obj = getattr(ml, name)
        if callable(obj):
            doc = obj.__doc__ or ""
            assert len(doc) > 200, name
    # the guarantees are stated: inv_core's contract has its three parts
    doc = ml.inv_core.__doc__
    for word in ("Requires", "Guarantees", "Returns", "Private", "n_h <= d_h",
                 "UNNORMALISED", "Kk", "sh0", "rem0"):
        assert word in doc, word
    assert "sx" in ml.inv_recon.__doc__ and "sigc" in ml.inv_recon.__doc__
    assert "Bv" in ml.inv_final.__doc__ and "mk" in ml.inv_final.__doc__
    assert "evaluate" in ml.__all__ and "tuple" in ml.evaluate.__doc__


def test_inv_names_is_beside_the_six_and_the_trig_names():
    assert ml.INV_NAMES == ("atan", "asin", "acos", "atan2")
    assert ml.NAMES == ("exp", "exp2", "expm1", "log", "log2", "log1p")
    assert ml.TRIG_NAMES == ("sin", "cos", "tan")
    assert not set(ml.INV_NAMES) & set(ml.NAMES + ml.TRIG_NAMES)
    assert ml.INV_FORMATS == (FP64, FP128, FP256)
    assert tuple(ml._INV_BUILDERS) == ("atan",)
    assert FUNCS == ("atan",)


def test_the_caps_are_logans_answer_9():
    assert ml.INV_LIVE_CAP == {
        "atan": {"fp32": 25, "fp64": 15, "fp128": 15, "fp256": 15},
        "asin": {"fp32": 25, "fp64": 16, "fp128": 16, "fp256": 16},
        "acos": {"fp32": 25, "fp64": 16, "fp128": 16, "fp256": 16},
        "atan2": {"fp32": 31, "fp64": 19, "fp128": 19, "fp256": 19}}
    # routines.py names none of the four: the caps are kept here until M4C
    assert not set(ml.INV_NAMES) & set(routines.LIVE_CAP)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_an_inverse_fragment_is_a_specialised_fragment_built_once(fmt):
    for rnd in RND:
        f = ml.fragment("atan", fmt, rnd)
        assert isinstance(f, routines.Fragment)
        assert (f.op, f.fmt, f.rnd, f.inputs, f.stage) == (
            "atan", fmt, rnd, ("a",), "specialised")
        assert f.result[0] == f.flags[0] == "v"
        assert ml.fragment("atan", fmt, rnd) is f
        assert ml.invariants(f) == []


def test_an_inverse_fragment_is_held_to_its_own_row_and_to_no_fallback(
        monkeypatch):
    f = ml.fragment("atan", FP64, RNE)
    assert f.live_max() == 15 > ml.LIVE_CAP["fp64"] == 13
    assert ml.invariants(f) == []           # not the six's 13
    assert ml.invariants(f, live_cap=14) == ["15 values live at once, past 14"]
    caps = {**ml.INV_LIVE_CAP, "atan": {**ml.INV_LIVE_CAP["atan"], "fp64": 14}}
    monkeypatch.setattr(ml, "INV_LIVE_CAP", caps)
    assert ml.invariants(f) == ["15 values live at once, past 14"]
    # a name of no table still falls back as it did: the six's by format
    g = ml.fragment("exp", FP64, RNE)
    assert ml.invariants(g) == []


def test_the_refusals_are_by_name():
    for name in ml.INV_NAMES:
        for call in (ml.build, ml.fragment):
            with pytest.raises(ValueError, match="parcel M4F1's") as e:
                call(name, FP32, RNE)
            assert f"{name} at fp32 is not built" in str(e.value)
    for name, parcel in (("asin", "M4G2"), ("acos", "M4G2"),
                         ("atan2", "M4G3")):
        for call in (ml.build, ml.fragment):
            with pytest.raises(ValueError, match=f"parcel {parcel}'s") as e:
                call(name, FP64, RNE)
            assert repr(name) in str(e.value) and "not built yet" in str(e.value)
    with pytest.raises(ValueError, match="attribute"):
        ml.build("atan", FP64, 7)
    with pytest.raises(ValueError, match="formats"):
        ml.build("atan", FpFormat("fp16", 5, 10), RNE)
    with pytest.raises(ValueError, match="no_such_plant") as e:
        ml.build("atan", FP64, RNE, plant="no_such_plant")
    assert "table_entry" in str(e.value) and "two_sum_all" in str(e.value)
    # the six's and the trig routines' plants are not the inverse routines'
    for plant in ("head_short", "quadrant_sign", "chunk"):
        with pytest.raises(ValueError, match=plant):
            ml.build("atan", FP64, RNE, plant=plant)
    # the message of a name that is not built lists the inverse names that are
    with pytest.raises(ValueError) as e:
        ml.fragment("atanh", FP64, RNE)
    assert "log1p, sin, cos, tan, atan" in str(e.value)
    with pytest.raises(ValueError, match="parcel M4F1's"):
        ml.build_inv_core(FP32)


def test_inv_core_takes_single_or_double_words_not_one_of_each():
    b = ml.Build(FP64, RNE, "x")
    b.meta.update(G=44, N=8, K=6, D=12, data=set(), shift=0, plant=None)
    with pytest.raises(ValueError, match="both single words .* or both double"):
        ml.inv_core(b, ("in", "a"), ("in", "b"), nl=("in", "c"))
    with pytest.raises(ValueError, match="both single words"):
        ml.inv_core(b, ("in", "a"), ("in", "b"), dl=("in", "c"))
    bare = ml.Build(FP64, RNE, "y")
    with pytest.raises(ValueError, match="meta holds G, N, K and D"):
        ml.inv_core(bare, ("in", "a"), ("in", "b"))


# ---- the build keeps what the budget and the sequel read -----------------------

PROBES = ("Vh", "Vl", "Bv", "R", "R1", "R2", "mk", "th", "tl", "tt", "Kk", "c",
          "nh", "P", "Nh0", "Nh", "Nl", "Dh", "Dl", "sh", "sl", "rem0")
PHASES = ("front", "index", "num", "den", "quotient", "z", "tail", "head",
          "atan_s", "table", "recon", "final", "classify", "special")


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_build_keeps_what_the_budget_and_the_sequel_read(fmt):
    b = build_of("atan", fmt, RNE)
    assert set(PROBES) <= set(b.probes), set(PROBES) - set(b.probes)
    assert all(b.probes[k][0] == "v" for k in PROBES)
    m = b.meta
    assert m["fn"] == "atan" and m["G"] == GUARD[fmt.name]
    assert (m["N"], m["K"], m["D"]) == (8,) + PLAN[fmt.name]
    assert isinstance(m["rho"], Fraction) and m["rho"] == ml.inv_rho()[0]
    assert (m["shift"], m["plant"], m["family"]) == (0, None, "double word")
    assert (m["fast_two_sum"], m["two_sum"]) == (12, 0)
    # the order of the phases is the design's, and every phase is in the tuple
    assert tuple(dict.fromkeys(b.phase_of)) == PHASES
    assert set(b.phase_of) <= set(ml.PHASE_ORDER)
    # data: the index's magic-number FMA (what M4G4's budget freezes)
    (tag, ref), = m["data"]
    assert tag == "index" and b.body[ref][0] == sf.OP_FMA
    assert b.phase_of[ref] == "index"
    assert b.words[b.roles["MAGIC"][1]] == b.words[b.body[ref][2][2][1]]
    assert b.inputs == ("a",)


def test_guard_and_bound_shift_are_the_builds_own():
    b = ml.build("atan", FP64, RNE, guard=30, bound_shift=3)
    assert b.meta["G"] == 30 and b.meta["shift"] == 3
    assert (b.meta["K"], b.meta["D"]) == ml.plan_inv(FP64, 30, ml.inv_rho()[0])
    clean = build_of("atan", FP64, RNE)
    assert (b.meta["K"], b.meta["D"]) != (clean.meta["K"], clean.meta["D"]) \
        or b.words != clean.words
    assert b.words[b.roles["BREL"][1]] == ml._pow2(FP64, -(53 + 30) + 3)


def test_the_plan_the_cells_and_rho_are_the_studys():
    cells = ml.inv_cells()
    assert len(cells) == 8 and cells[0][0] == 0
    assert cells[7][1] == 1 + Fraction(1, 2 ** 20)
    assert all(lo < hi for lo, hi in cells)
    assert all(cells[k][1] >= cells[k + 1][0] for k in range(7))   # a cover
    assert all(isinstance(v, Fraction) for c in cells for v in c)
    rho, lo_r, hi_r = ml.inv_rho()
    assert f"{float(rho):.7f}" == "0.0666671"          # 1/15 and a hair
    assert Fraction(1, 15) < rho < Fraction(2, 29)
    assert Fraction(1, 2) < lo_r and hi_r <= 2
    assert round(float(lo_r), 4) == 0.5065 and round(float(hi_r), 4) == 1.5281
    for fmt in FORMATS:
        assert ml.plan_inv(fmt, GUARD[fmt.name], rho) == PLAN[fmt.name]
    # the bias is 63/64, MSEL = 7.875 exact
    assert ml.INV_BIAS == Fraction(63, 64) and 8 * ml.INV_BIAS == Fraction(63, 8)
    # at the bound the plan truncates: the term after D is under 2^-(p+G+3)
    for fmt in FORMATS:
        K, D = PLAN[fmt.name]
        z = rho * rho
        assert Fraction(1, 2 * D + 3) * z ** (D + 1) \
            <= Fraction(1, 2 ** (fmt.prec + GUARD[fmt.name] + 3))
        assert Fraction(1, 2 * D + 1) * z ** D \
            > Fraction(1, 2 ** (fmt.prec + GUARD[fmt.name] + 3)) or D == K


def test_rho_refuses_by_name_the_proof_it_cannot_make(monkeypatch):
    monkeypatch.setattr(ml, "INV_BIAS", Fraction(1))
    with pytest.raises(ValueError, match="Sterbenz's premise fails at N = 8"):
        ml.inv_rho.__wrapped__(8)
    monkeypatch.setattr(ml, "INV_BIAS", Fraction(63, 64))
    real = ml.inv_cells
    monkeypatch.setattr(ml, "inv_cells", lambda N=8: real(N, Fraction(1, 4)))
    with pytest.raises(ValueError, match="Sterbenz's premise fails"):
        ml.inv_rho.__wrapped__(8)


# ---- the two-input evaluate ------------------------------------------------------

def test_evaluate_and_run_take_a_tuple_for_a_fragment_of_two_inputs():
    b = ml.build_inv_core(FP64)
    assert b.inputs == ("a", "b") and b.meta["fn"] == "inv_core"
    one, three = sf.one_bits(FP64), ml._enc(FP64, Fraction(3))
    th, tl, pr = b.run((one, three), ("c", "Kk"))
    # 1/3: k = round(7.875 t~) = 3 (t~ = 0.3333), c = 3/8
    assert ml._dec(FP64, pr["c"]) == Fraction(3, 8)
    swapped = b.run((three, one), ("c",))
    assert swapped != (th, tl, {"c": pr["c"]})
    f = b.fragment(schedule=False)
    assert f.inputs == ("a", "b")
    assert ml.evaluate(f, (one, three)) == (th, tl)
    assert ml.evaluate(f, (three, one)) == swapped[:2]
    # the names are read each its own: a is n, b is d
    t1 = ml._dec(FP64, th) + ml._dec(FP64, tl)
    assert abs(t1 - Fraction(math.atan(1 / 3))) < Fraction(1, 2 ** 50)
    # an int for two inputs, a tuple of the wrong length, and a tuple for one
    for bad in (one, (one,), (one, one, one)):
        with pytest.raises(ValueError, match="inputs"):
            b.run(bad)
        with pytest.raises(ValueError, match="inputs"):
            ml.evaluate(f, bad)
    atan = build_of("atan", FP64, RNE)
    with pytest.raises(ValueError, match="inputs"):
        atan.run((one, one))
    with pytest.raises(ValueError, match="not an encoding"):
        ml.evaluate(ml.fragment("atan", FP64, RNE), 1 << 64)
    with pytest.raises(ValueError, match="not an encoding"):
        ml.evaluate(f, (one, 1 << 64))
    # one input exactly as it was
    g = ml.fragment("atan", FP64, RNE)
    assert ml.evaluate(g, one) == atan.run(one)[:2] \
        == (0x3fe921fb54442d18, 0x10)


def test_the_double_word_core_takes_four_inputs():
    b = ml.build_inv_core(FP64, double=True)
    assert b.inputs == ("a", "b", "c", "d")
    one, tiny = sf.one_bits(FP64), ml._pow2(FP64, -60)
    r1 = b.run((one, tiny, one, 0))
    r0 = b.run((one, 0, one, 0))
    assert r1 != r0                      # n_l is read
    r2 = b.run((one, 0, one, tiny))
    assert r2 != r0                      # d_l is read
    assert b.run((one, 0, one, 0)) == r0


# ---- the phases and the scheduler --------------------------------------------------

def test_phase_order_has_the_inverse_phases_in_one_block():
    order = ml.PHASE_ORDER
    new = ("front", "sqrt", "index", "num", "den", "atan_s", "table")
    i = order.index("red-small")
    assert order[i + 1:i + 1 + len(new)] == new
    assert order[i + 1 + len(new)] == "lowword"
    assert len(set(order)) == len(order)
    for ph in ("z", "tail", "head", "quotient", "recon", "final", "classify",
               "special"):
        assert ph in order                     # the names already there
    used = set(build_of("atan", FP64, RNE).phase_of)
    assert used <= set(order) and "setup" not in used


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_scheduler_takes_the_designs_order_for_atan(fmt):
    b = build_of("atan", fmt, RNE)
    g = b.fragment(schedule=False)
    ph = [b.phase_of[i] for i in b.live_indices()]
    live = {"design": g.live_max(),
            "ranked": ml.permuted(g, ml._ranked_order(g, ph)).live_max(),
            "dfs": ml.permuted(g, ml._dfs_order(g)).live_max()}
    assert live["design"] == 15
    assert live["ranked"] > 30 and live["dfs"] == 16     # MEASURED: 36, 16
    assert min(live.values()) == live["design"]
    f = b.fragment()
    assert f.live_max() == 15 == ml.INV_LIVE_CAP["atan"][fmt.name]
    assert f.body == g.body                  # the design's order, unpermuted
    assert H.check_reorder(b, f) == []
    # the other two candidates are what the docstring says they are, and the
    # six's, the trig routines' and the reduction's orders are the baseline's
    # (test_routines.py's 220 digests; the parcel's entry's 200 builds)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_dag_digests_are_the_models(fmt):
    for rnd in RND:
        got = ml.dag_digest(fragment_of("atan", fmt, rnd))[:32]
        assert got == DIGESTS[f"{fmt.name}/{rid(rnd)}"], (fmt.name, rid(rnd))
        # the design's order and the scheduled fragment are one graph
        assert ml.dag_digest(build_of("atan", fmt, rnd).fragment(
            schedule=False))[:32] == got


# =====================================================================
# the checks, clean
# =====================================================================

@pytest.mark.parametrize("fmt,rnd", POOL_CONFIGS, ids=lambda v: v.name
                         if hasattr(v, "name") else rid(v))
def test_pools(fmt, rnd):
    f = fragment_of("atan", fmt, rnd)
    xs = I.pool("atan", fmt)
    assert len(xs) == POOL_SIZES[fmt.name]
    out, t = I.check_pools(f)
    assert out == [] and t.n == len(xs)
    # MEASURED: the pools through all fifteen configurations mark no lane
    assert t.marked == [] and t.wrong == [] and I.INV_POOL_MARKS == ()


@pytest.mark.parametrize("fmt,rnd", SEQ_CONFIGS, ids=lambda v: v.name
                         if hasattr(v, "name") else rid(v))
def test_seq(fmt, rnd):
    f = fragment_of("atan", fmt, rnd)
    out, lanes = I.check_seq(f)
    assert out == []
    extra = 1 if (fmt, rnd) == (FP64, RNE) else 0
    assert len(lanes) > 80          # MEASURED 94 to 96 (the committed lanes too)
    if extra:
        # atan(3 2^-26) under rne at fp64 is the marked lane
        assert 0x3e68000000000000 in lanes
        assert ml.evaluate(f, 0x3e68000000000000)[1] & ml.MARK


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_bound(fmt):
    b = build_of("atan", fmt, RNE)
    worst, lanes = -1e9, 0
    for region, xs in I.placed_points("atan", fmt).items():
        assert len(xs) == 48
        out, (w, main, n) = I.check_bound(b, xs, region)
        assert out == [] and main == n == 48, (region, out)
        worst, lanes = max(worst, w), lanes + n
    # the largest is a SAMPLED lower bound (192 points, seed 11): MEASURED
    # 2^-7.1 (fp64), 2^-5.9 and 2^-6.9 (fp128, fp256) of Bv
    assert -9 < worst < -5, worst


def test_structured():
    n = 0
    for fmt in FORMATS:
        for rnd in RND:
            f = fragment_of("atan", fmt, rnd)
            out, lanes = I.check_structured(f)
            assert out == [], out
            n += len(lanes)
            lanes_ok = [ml.evaluate(f, x)[1] & ml.MARK for x in lanes]
            assert all(lanes_ok)
    assert n == 106, n      # fp64 34, fp128 36, fp256 36 (both signs counted)
    # the configurations the list has none for pass with none run
    assert I.structured_lanes("atan", FP64, RUP) == [
        x for x in I.structured_lanes("atan", FP64, RUP)]
    assert I.structured_lanes("atan", FP64, RNE) != []
    assert len(I.structured_lanes("atan", FP128, RNE)) == 6


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_specials(fmt):
    for rnd in RND:
        f = fragment_of("atan", fmt, rnd)
        out, n = I.check_specials(f)
        assert out == [] and n == 26, (out, n)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_shape(fmt):
    builds = {("atan", r): build_of("atan", fmt, r) for r in RND}
    assert I.check_shape(fmt, builds) == []
    # the study's totals (READ: costs.fp64, fp128, fp256.out.txt)
    f = fragment_of("atan", fmt, RNE)
    assert (len(f), len(f.words), f.live_max()) == {
        "fp64": (176, 54, 15), "fp128": (186, 62, 15),
        "fp256": (203, 77, 15)}[fmt.name]


def test_the_audit_is_the_studys_and_sterbenz_bias_is_red_only_there():
    want = {"fp64": (-7.3, 44.0), "fp128": (-5.1, 46.0),
            "fp256": (-5.8, 46.0)}
    for fmt in FORMATS:
        out, t = I.check_audit(fmt)
        assert out == [] and t["lanes"] == 214
        assert (t["premise"], t["inexact"], t["past"]) == (0, 0, 0)
        assert round(t["largest"], 1) == want[fmt.name][0]
        out, t = I.check_audit(fmt, "sterbenz_bias")
        assert [s.split(":")[0] for s in out] == ["audit"] * 3
        assert (t["lanes"], t["premise"], t["inexact"], t["past"]) == (
            214, 86, 24, 24)
        assert round(t["largest"], 1) == want[fmt.name][1]
    # and on atan's own lanes the plant is red in nothing but the audit
    # (the core's Kk and the constants see it, the pools, structured lanes,
    # bound and specials do not)
    red = I.red_checks("sterbenz_bias")
    assert set(red) == {"audit", "core", "constants"}


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_core(fmt):
    for double in (False, True):
        b = I.core_of(fmt, None, double)
        assert b.inputs == (("a", "b", "c", "d") if double else ("a", "b"))
    out, t = I.check_core(fmt)
    assert out == [] and t["lanes"] == 60
    assert (t["past"], t["kk"], t["negative"]) == (0, 0, 0)
    assert t["largest"] < -5
    # th is at most pi/4 and under an ulp of it (MEASURED over the lanes,
    # three of them t = 1): the contract of inv_core states this figure
    assert t["over_pi4"] < 1.0


def test_core_single_word_lanes_are_the_same_function():
    b1, b2 = I.core_of(FP64, None, False), I.core_of(FP64, None, True)
    for n, d in ((0x3fd0000000000000, 0x3ff0000000000000),
                 (0x3fee000000000000, 0x3ff4000000000000),
                 (0x3fb0000000000000, 0x4000000000000000)):
        assert b1.run((n, d))[:2] == b2.run((n, 0, d, 0))[:2]


def test_constants_in_process():
    findings, lines = I.check_constants()
    assert findings == []
    assert len(lines) == 1 + 3 + 3          # the identity, the seed, atan
    assert lines[0].startswith("atan(7/8) + atan(1/15) = pi/4")
    assert all("derived constants in 5 fragments" in s for s in lines[4:])
    counts = {s.split(":")[0]: int(s.split(": ")[2].split()[0])
              for s in lines[4:]}
    assert counts == {"atan fp64": 295, "atan fp128": 335, "atan fp256": 410}


def _run_module(*args):
    return subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                           *args], cwd=PYTHON_DIR, capture_output=True,
                          text=True)


def test_constants_as_a_program():
    r = _run_module("--check", "--only", "inv")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert lines[-1] == "mathlib --check (inv): 1 routines, 3 formats, " \
        "0 differences"
    assert len(lines) == 8 and "DIFFERENCE" not in r.stdout
    assert lines[0].startswith("atan(7/8) + atan(1/15) = pi/4")
    assert sum(s.startswith("atan fp") for s in lines) == 3
    assert sum(s.startswith("RECIP_SEED") for s in lines) == 3


def test_check_prints_inv_lines_only_under_only_and_exits_1_on_a_difference(
        monkeypatch, capsys):
    for name in ("check_constants", "check_reduction_constants",
                 "check_reduction_tw_constants", "check_trig_constants"):
        monkeypatch.setattr(ml, name, lambda *a, **k: ([], []))
    monkeypatch.setattr(ml, "check_inv_constants",
                        lambda *a, **k: (["an inv line"], ["inv x differs"]))
    assert ml.main(["--check"]) == 1
    shown = capsys.readouterr().out
    # the default run prints only the DIFFERENCE lines of inv, and none of the
    # lines every other check prints is changed (no inv line of its own)
    assert "DIFFERENCE: inv x differs" in shown
    assert "an inv line" not in shown and "(inv)" not in shown
    assert ml.main(["--check", "--only", "inv"]) == 1
    shown = capsys.readouterr().out.splitlines()
    assert shown == ["an inv line", "DIFFERENCE: inv x differs",
                     "mathlib --check (inv): 1 routines, 3 formats, "
                     "1 differences"]
    # clean: the default run prints nothing of inv
    monkeypatch.setattr(ml, "check_inv_constants",
                        lambda *a, **k: (["an inv line"], []))
    assert ml.main(["--check"]) == 0
    assert "inv" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        ml.main(["--check", "--only", "nonesuch"])
    assert "inv" in capsys.readouterr().err


# =====================================================================
# the plants: each red in its checks and green in the others
# =====================================================================

# Every row lists EVERY check, red or green (a test fails on a row that omits
# one). MEASURED on fp64 by this parcel: python/tests/mathlib_inv_harness.
# red_checks(plant) is the run (pools and seq under rne and rtz, bound over
# 4 regions of 48 points under rne, structured, specials and shape under all
# five attributes, audit, core and constants under rne). The cells for pools,
# structured, bound and specials are the study's (docs/studies/m4/
# plants.fp64.out.txt) except where a row says otherwise; the cells for seq,
# shape, audit, core and constants are this parcel's. Differences from the
# study's table: sl_dropped is also red in structured, and the reason is a pin,
# not a fault of the lane: STRUCT_GUESS_WRONG pins the fragment's current guesses
# for 0x43349ff16b9c1e3e (both signs) under rne and rmm, which differ from
# transcend.py's (a marked lane's guess is not promised, the replay decides it),
# and with s's low word dropped the guess becomes right, so the check's leg
# "listed as having a wrong guess have the right one" goes red; mark_silenced also in seq (a lane's byte) and in shape
# (the instruction count), and every plant that changes an instruction or a
# word count is red in shape.
CHECKS = I.CHECKS
PLANTED = [
    ("table_entry", ("pools", "bound", "audit", "core", "constants"),
     ("seq", "structured", "specials", "shape")),
    ("coef", ("bound", "shape", "audit", "core", "constants"),
     ("pools", "seq", "structured", "specials")),
    ("newton_short", ("seq", "bound", "structured", "shape", "audit", "core"),
     ("pools", "specials", "constants")),
    ("sterbenz_bias", ("audit", "core", "constants"),
     ("pools", "seq", "bound", "structured", "specials", "shape")),
    ("zl_dropped", ("bound", "shape", "audit", "core"),
     ("pools", "seq", "structured", "specials", "constants")),
    ("sl_dropped", ("pools", "bound", "structured", "shape", "audit", "core"),
     ("seq", "specials", "constants")),
    ("pio2_low", ("pools", "seq", "bound", "structured", "specials", "shape",
                  "constants"),
     ("audit", "core")),
    ("bound_loose", ("seq", "bound", "structured", "constants"),
     ("pools", "specials", "shape", "audit", "core")),
    ("mark_silenced", ("seq", "structured", "shape"),
     ("pools", "bound", "specials", "audit", "core", "constants")),
    ("tiny_gate_off", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "structured", "audit", "core")),
    ("tiny_side", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "structured", "audit", "core")),
    ("two_sum_all", ("shape",),
     ("pools", "seq", "bound", "structured", "specials", "audit", "core",
      "constants")),
]


def _row_id(r):
    return r[0]


@functools.lru_cache(maxsize=None)
def _red(plant, fmt_name="fp64"):
    return I.red_checks(plant, BY_NAME[fmt_name])


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


def test_every_plant_is_in_the_table_and_every_row_lists_every_check():
    named = [row[0] for row in PLANTED]
    assert set(named) == INV_PLANT_NAMES == set(ml.INV_PLANTS)
    assert len(named) == len(set(named))
    assert all(isinstance(t, str) and len(t) > 20
               for t in ml.INV_PLANTS.values())
    for plant, red, green in PLANTED:
        assert set(red) | set(green) == set(CHECKS), \
            (plant, set(CHECKS) - set(red) - set(green))
        assert not set(red) & set(green), plant
        assert len(red) + len(green) == len(CHECKS), plant
        assert red, plant
        if plant in CORE_PLANTS:
            continue
    # a row that omitted a check would be caught here, and the test itself is
    # shown to catch it on a doctored table
    doctored = ("coef", ("bound",), ("pools",))
    assert set(doctored[1]) | set(doctored[2]) != set(CHECKS)


def test_every_check_has_a_plant_red_in_it_and_every_plant_is_red_somewhere():
    red = {c for row in PLANTED for c in row[1]}
    assert red == set(CHECKS), set(CHECKS) - red
    assert all(row[1] for row in PLANTED)
    # and a clean test for each check
    for name in ("test_pools", "test_seq", "test_bound", "test_structured",
                 "test_specials", "test_shape", "test_core",
                 "test_the_audit_is_the_studys_and_sterbenz_bias_is_red_only_"
                 "there", "test_constants_in_process"):
        assert callable(globals()[name]), name


def test_the_plants_that_do_not_reach_the_core_are_refused_by_name():
    for plant in ml.INV_PLANTS:
        if plant in CORE_PLANTS:
            b = ml.build_inv_core(FP64, plant=plant)
            assert b.meta["plant"] == plant
        else:
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to inv_core at fp64: the fault is not "
                               f"reached"):
                ml.build_inv_core(FP64, plant=plant)
    with pytest.raises(ValueError, match="no_such_plant"):
        ml.build_inv_core(FP64, plant="no_such_plant")


def test_a_plant_the_build_cannot_reach_is_refused_by_name(monkeypatch):
    """A fault of asin's, say, in atan: the table has it, atan never acts on
    it, and the build is refused ("does not apply")."""
    monkeypatch.setitem(ml.INV_PLANTS, "asin_only", "a fault atan cannot have")
    with pytest.raises(ValueError, match="plant 'asin_only' does not apply to "
                       "atan at fp128: the fault is not reached"):
        ml.build("atan", FP128, RNE, plant="asin_only")
    with pytest.raises(ValueError, match="does not apply to inv_core"):
        ml.build_inv_core(FP64, plant="asin_only")


def test_every_plant_changes_the_build():
    """A plant that did nothing would pass every row green: each is a different
    build from the clean one, in its body or its words."""
    clean = build_of("atan", FP64, RNE)
    for plant in ml.INV_PLANTS:
        b = build_of("atan", FP64, RNE, plant)
        same = (b.body == clean.body and b.words == clean.words
                and b.result == clean.result and b.flags == clean.flags)
        assert not same, plant


# The study's named cases at fp64 (docs/studies/m4/plants.fp64.out.txt and the
# brief's table), reproduced: (plant, attribute, argument, what it is).
# "wrong": the lane unmarked and not transcend.py's, the clean one equal to it;
# "unmarked": a lane the clean fragment marks, the plant does not.
NAMED = [
    ("table_entry", RNE, 0x3fd7ffffffffffff, "wrong"),
    ("newton_short", RNE, 0x3e68000000000000, "unmarked and wrong"),
    ("sl_dropped", RTZ, 0x4014000000000001, "wrong"),
    ("pio2_low", RNE, 0x3ff4000000000001, "wrong"),
    ("pio2_low", RTZ, 0x434d02967c31cdb3, "unmarked"),
    ("bound_loose", RNE, 0x3e68000000000000, "unmarked"),
    ("mark_silenced", RNE, 0x3e68000000000000, "unmarked"),
    ("tiny_gate_off", RNE, 0x1, "wrong"),
    ("tiny_side", RTZ, 0x1, "wrong"),
]
# |V - f| / Bv, 2^k, at one lane under rne: (plant, lane, k)
NAMED_BOUND = [
    ("table_entry", 0xc0091d4f83b9ba08, 42.7),
    ("coef", 0xc0091d4f83b9ba08, 28.2),
    ("newton_short", 0x3fea7e15c78f9c67, 3.3),
    ("zl_dropped", 0xc0091d4f83b9ba08, 27.1),
    ("sl_dropped", 0xc0091d4f83b9ba08, 36.3),
    ("pio2_low", 0xc0091d4f83b9ba08, 42.8),
    ("bound_loose", 0xc0091d4f83b9ba08, 28.9),
]


@pytest.mark.parametrize("plant,rnd,lane,kind", NAMED,
                         ids=[f"{p}-{rid(r)}-{x:#x}" for p, r, x, _ in NAMED])
def test_the_studys_named_case_is_reproduced(plant, rnd, lane, kind):
    gold = I.golden(FP64, rnd, lane, "atan")
    bits, fw = ml.evaluate(fragment_of("atan", FP64, rnd, plant), lane)
    cbits, cfw = ml.evaluate(fragment_of("atan", FP64, rnd), lane)
    if kind == "wrong":
        assert not fw & ml.MARK and (bits, fw) != gold
        assert (cbits, cfw) == gold
    elif kind == "unmarked and wrong":
        assert not fw & ml.MARK and (bits, fw) != gold and cfw & ml.MARK
    else:
        assert not fw & ml.MARK and cfw & ml.MARK
        assert (bits, fw) == gold


@pytest.mark.parametrize("plant,lane,k", NAMED_BOUND,
                         ids=[p for p, _, _ in NAMED_BOUND])
def test_the_bound_of_the_studys_named_cases(plant, lane, k):
    r = I.bound_log2(build_of("atan", FP64, RNE, plant), lane)
    assert round(r, 1) == k, r
    assert I.bound_log2(build_of("atan", FP64, RNE), lane) < -5
    assert I.in_main("atan", FP64, lane)


def test_the_specials_rows_name_the_study_s_cases():
    # pio2_low: the row 2^55 under rtz (the study's "2^55"); tiny: the row of
    # the minimum subnormal
    out, _ = I.check_specials(fragment_of("atan", FP64, RTZ, "pio2_low"))
    assert any("row '2^55, both signs'" in s for s in out), out
    out, _ = I.check_specials(fragment_of("atan", FP64, RNE, "tiny_gate_off"))
    assert any("row 'minSub, both signs'" in s for s in out), out
    out, _ = I.check_specials(fragment_of("atan", FP64, RTZ, "tiny_side"))
    assert any("row 'minSub, both signs'" in s for s in out), out


def test_the_control_bound_is_the_studys():
    """The control's largest over the study's three regions (edge, small, big;
    48 points each, seed 11, plants.py's) is 2^-7.12 Bv, as the model's."""
    b = build_of("atan", FP64, RNE)
    worst = -1e9
    for region in ("edge", "small", "big"):
        xs = [x for x in I.sample("atan", FP64, region, 48, 11)
              if I.in_main("atan", FP64, x)]
        out, (w, _n, _l) = I.check_bound(b, xs, region)
        assert out == []
        worst = max(worst, w)
    assert round(worst, 2) == -7.12


# =====================================================================
# every leg of every check can fail alone
# =====================================================================

def test_each_leg_of_pools_can_fail_alone():
    f = fragment_of("atan", FP64, RNE)
    listed, plain, one = 0x3e68000000000000, 0x4008000000000000, \
        0x3ff0000000000000
    xs = [listed, plain, one]
    clean = [ml.evaluate(f, x) for x in xs]
    assert clean[0][1] & ml.MARK and not clean[1][1] & ml.MARK
    # no lane is committed for atan: the list is empty, so the marked lane is
    # off it, and a list that holds it makes the run clean
    out, t = I.check_pools(f, xs, results=clean)
    assert len(out) == 1 and "marked off the committed list" in out[0]
    out, t = I.check_pools(f, xs, results=clean, marks={listed: "x"})
    assert out == [] and (t.n, len(t.marked), t.marked_right) == (3, 1, 1)
    cases = {
        "unmarked lanes differ from transcend.atan":
            _doctor(clean, 1, bits=1),
        "flag words carry bits other than [4:0] and the mark":
            _doctor(clean, 0, orwith=0x20),
        "marked off the committed list": _doctor(clean, 1, orwith=0x80),
        "on the committed list are not marked":
            _doctor(clean, 0, andnot=0x80),
    }
    for text, results in cases.items():
        out, t = I.check_pools(f, xs, results=results, marks={listed: "x"})
        assert len(out) == 1 and text in out[0] \
            and out[0].startswith("pools: "), (text, out)
    # a marked lane's guess is replayed and counted, and is not a finding
    out, t = I.check_pools(f, xs, results=_doctor(clean, 0, bits=1),
                           marks={listed: "x"})
    assert out == [] and len(t.guess_wrong) == 1 and t.marked_right == 0
    # the committed list is the harness's: INV_POOL_MARKS, by (function,
    # format, attribute), a lane off it fails and a listed lane unmarked fails
    marks = (("atan", "fp64", "rne", listed, "a reason"),)
    assert I.pool_marks("atan", "fp64", "rne", marks) == {listed: "a reason"}
    assert I.pool_marks("atan", "fp64", "rtz", marks) == {}


def test_each_leg_of_structured_can_fail_alone():
    f = fragment_of("atan", FP64, RNE)
    out, lanes = I.check_structured(f)
    assert out == [] and len(lanes) == 8
    out, _ = I.check_structured(
        f, evaluator=lambda g, x: (lambda r: (r[0], r[1] & 0x1F))(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "8 of the 8 committed lanes are not marked" \
        in out[0] and out[0].startswith("structured: ")
    out, _ = I.check_structured(
        f, evaluator=lambda g, x: (lambda r: (r[0] ^ 1, r[1]))(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "marked lanes have a guess that differs from " \
        "transcend.atan" in out[0] and out[0].startswith("structured: ")
    # the listed lanes whose guess differs: a listed lane with the right guess
    out, _ = I.check_structured(f, wrong={("atan", "fp64", RNE): {
        0x3e68000000000000, 0x43349ff16b9c1e3e, 0x43349ff16b9c1e3e | 1 << 63}})
    assert len(out) == 1 and "listed as having a wrong guess have the right" \
        in out[0]
    # and one that is wrong and not listed
    out, _ = I.check_structured(f, wrong={})
    assert len(out) == 1 and "2 marked lanes have a guess" in out[0]
    # a configuration with no lanes runs none and passes (every configuration
    # of the committed list has some, so the table is the argument)
    assert I.check_structured(f, table={"atan": {}}) == ([], [])
    assert I.check_structured(f, table={"atan": {"fp128": []}}) == ([], [])
    assert I.check_structured(fragment_of("atan", FP64, RUP))[1] != []


def test_each_leg_of_seq_can_fail_alone():
    f = fragment_of("atan", FP64, RNE)
    # +inf is the lane a loud third MUL shows on: P = c d_h = 0 x inf raises
    # invalid, which the lane's flag word (inexact alone) does not
    xs = [0x3ff0000000000000, 0x4008000000000000, 0x3e68000000000000, 0x1,
          0x7ff0000000000000]
    out, lanes = I.check_seq(f, xs)
    assert out == [] and len(lanes) == 5 + 7      # the committed lanes added
    # the evaluator: seq.py and evaluate() differ
    out, _ = I.check_seq(f, xs, evaluator=lambda g, x: (
        ml.evaluate(g, x)[0] ^ 1, ml.evaluate(g, x)[1]))
    assert len(out) == 1 and "seq.py and evaluate() differ on 12 lanes" \
        in out[0]
    # a flag left loud: the third MUL, outside QUIET, raises invalid on +inf
    out, _ = I.check_seq(f, xs, loud=True)
    assert out and all("raised" in s for s in out)
    assert any("lane 0x7ff0000000000000 raised 0x11, want 0x10" in s
               for s in out), out
    assert sum("raised" in s for s in out) == 1
    assert I.check_seq(f, xs, loud=False)[0] == []
    # FLAGS is not the OR of the lanes' bytes
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(r, "flags", r.flags
                                                        ^ 1), r)[1])
    assert len(out) == 1 and "FLAGS" in out[0] and "OR of the lanes" in out[0]
    # STATUS[6] and a marked lane disagree
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(
        r, "status", r.status ^ 0x40), r)[1])
    assert len(out) == 1 and "STATUS[6]" in out[0]
    # a fragment wrong the same way on seq.py and in evaluate(): the unmarked
    # lanes differ from transcend.py, in the result and the deposit
    bad = fragment_of("atan", FP64, RNE, "table_entry")
    out, _ = I.check_seq(bad, [0x3fd7ffffffffffff])
    assert any("unmarked lanes on seq.py differ from transcend.atan" in s
               for s in out) and any("deposited" in s for s in out)
    assert not any("seq.py and evaluate()" in s for s in out)
    # the card case: atan(3 2^-26) under rne is the marked lane, and a
    # fragment that never marks it is red here
    silent = fragment_of("atan", FP64, RNE, "mark_silenced")
    out, _ = I.check_seq(silent, [0x3ff0000000000000])
    assert any("committed lanes are not marked in the lane's byte" in s
               for s in out)


def test_each_leg_of_bound_can_fail_alone():
    b = build_of("atan", FP64, RNE)
    xs = I.sample("atan", FP64, "edge", 6, 5)
    out, (worst, main, lanes) = I.check_bound(b, xs)
    assert out == [] and main == lanes == 6 and worst < 0
    # a main-path lane past 1 Bv, every lane right in transcend.py's sense
    wide = build_of("atan", FP64, RNE, "bound_loose")
    out, _ = I.check_bound(wide, xs)
    assert len(out) == 1 and "6 of 6 main-path lanes are past the bound" \
        in out[0] and out[0].startswith("bound: ")
    # a lane that differs from transcend.py with V right (not a main-path
    # lane): the tiny path off, the main path answering a tiny argument
    off = build_of("atan", FP64, RNE, "tiny_gate_off")
    out, (worst, main, lanes) = I.check_bound(off, [0x1, 0x8000000000000001])
    assert len(out) == 1 and "2 unmarked lanes differ from transcend.atan" \
        in out[0] and main == 0
    # V exact: a lane where V equals the true value contributes no ratio
    assert I.check_bound(b, [0x3ff0000000000000])[1][1] == 1


def test_each_leg_of_specials_can_fail_alone():
    f = fragment_of("atan", FP64, RNE)
    out, n = I.check_specials(f)
    assert out == [] and n == 26
    # a row: a flag word
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] ^ 1) if x == sf.inf_bits(FP64) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+inf, -inf': 1 of 2 lanes differ" in out[0]
    # a row: the bits
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0] ^ 1, r[1]) if x == 0 else r)(ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+0, -0'" in out[0]
    # a lane marked in a row that must not mark
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == sf.one_bits(FP64) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+1, -1'" in out[0] \
        and "differ or are marked" in out[0]
    # the rows are the table's: a doctored table of one row
    out, n = I.check_specials(f, rows=[("one row", [0x3ff0000000000000])])
    assert out == [] and n == 1


def test_each_leg_of_audit_can_fail_alone():
    lanes = I.audit_lanes(FP64)
    assert len(lanes) == 214
    base = I.core_of(FP64)

    class Doctored:
        meta = base.meta
        fmt = base.fmt

        def __init__(self, fix):
            self.fix = fix

        def run(self, lane, want=()):
            th, tl, pr = base.run(lane, want)
            return self.fix(th, tl, dict(pr))

    def scaled(v, k):
        return ml._enc(FP64, ml._dec(FP64, v) * k)
    # the premise leg alone (the differences exact, the bound as it was)
    def premise(th, tl, pr):
        # n_h = 1, P = 1/8: the ratio is 8, and 1 - 1/8 = 7/8 is exact
        pr["nh"], pr["P"] = ml._enc(FP64, Fraction(1)), ml._enc(
            FP64, Fraction(1, 8))
        pr["Nh0"] = ml._enc(FP64, Fraction(7, 8))
        return th, tl, pr
    out, t = I.check_audit(FP64, lanes=lanes, b=Doctored(premise))
    assert t["premise"] > 0 and t["inexact"] == 0 and t["past"] == 0
    assert len(out) == 1 and "outside [1/2, 2]" in out[0] \
        and out[0].startswith("audit: ")
    # the inexact leg alone: Nh0 one ulp off
    def inexact(th, tl, pr):
        pr["Nh0"] += 1
        return th, tl, pr
    out, t = I.check_audit(FP64, lanes=lanes, b=Doctored(inexact))
    assert t["inexact"] > 0 and t["premise"] == 0 and t["past"] == 0
    assert len(out) == 1 and "n_h - P inexact" in out[0]
    # the bound leg alone: th one ulp off
    def past(th, tl, pr):
        return th + 1, tl, pr
    out, t = I.check_audit(FP64, lanes=lanes, b=Doctored(past))
    assert t["past"] > 0 and t["premise"] == 0 and t["inexact"] == 0
    assert len(out) == 1 and "past 2^-(p+G) theta0" in out[0]
    # a lane with n > d is sorted, not refused
    n, d = lanes[0]
    assert I.check_audit(FP64, lanes=[(d, n)])[1]["lanes"] == 1
    assert I.check_audit(FP64, lanes=[(d, n)])[0] == []


def test_each_leg_of_core_can_fail_alone():
    lanes = I.core_lanes(FP64)[:12]
    base = I.core_of(FP64, None, True)

    class Doctored:
        meta = base.meta
        fmt = base.fmt

        def __init__(self, fix):
            self.fix = fix

        def run(self, lane, want=()):
            th, tl, pr = base.run(lane, want)
            return self.fix(th, tl, dict(pr))
    out, t = I.check_core(FP64, lanes=lanes, b=Doctored(lambda a, b_, c:
                                                        (a, b_, c)))
    assert out == [] and t["lanes"] == 12
    # the bound leg alone
    out, t = I.check_core(FP64, lanes=lanes, b=Doctored(
        lambda th, tl, pr: (th + 1, tl, pr)))
    assert len(out) == 1 and "past 2^-(p+G) theta0" in out[0] \
        and t["kk"] == 0 and t["negative"] == 0
    # Kk's contract alone: low bits k + 1 (mod 8), and MAGIC where k = 0
    def kk(th, tl, pr):
        pr["Kk"] = pr["Kk"] + 1
        return th, tl, pr
    out, t = I.check_core(FP64, lanes=lanes, b=Doctored(kk))
    assert len(out) == 1 and "break Kk's contract" in out[0] \
        and t["past"] == 0 and t["negative"] == 0
    # th < 0 alone: th's sign flipped, tl set to cancel it
    def negative(th, tl, pr):
        return th | (1 << 63), tl, pr
    out, t = I.check_core(FP64, lanes=lanes, b=Doctored(negative))
    assert any("have th < 0" in s for s in out)
    assert all(s.startswith("core: ") for s in out)
    # the lanes: n <= d, n_h <= d_h, three at t = 1
    for nh, nl, dh, dl in lanes:
        N = ml._dec(FP64, nh) + ml._dec(FP64, nl)
        D = ml._dec(FP64, dh) + ml._dec(FP64, dl)
        assert 0 < N <= D and nh <= dh
    assert sum(1 for l in lanes if l[0] == l[2] and l[1] == l[3] == 0) == 3


def _fresh_with(fn, fmt, rnd, role=None, delta=1, extra_role=None):
    """A fresh (never shared) build of fn with the word of `role` changed by
    `delta` in its bits, or with an extra role no derivation asks."""
    b = ml.build(fn, fmt, rnd)
    if role is not None:
        name = b.roles[role][1]
        b.words[name] = (b.words[name] + delta) & ((1 << fmt.width) - 1)
    if extra_role is not None:
        b.const(*extra_role)
    return b


def _constants_of(b, fmt=None):
    fmt = fmt or b.fmt
    lines, findings = ml.check_inv_constants(
        builder=lambda n, f, r: b, formats=(fmt,), attrs=(b.rnd,),
        names=(b.meta["fn"],))
    return [f"constants: {s}" for s in findings if not s.startswith("seed")]


def test_each_leg_of_constants_can_fail_alone():
    """The build with one word changed, one role at a time: the difference is
    named by fragment and word. Every kind of word: pi/2, the table's, the
    coefficients (first, middle and last of the tail and head), the index's,
    the specials' and the integers."""
    clean = ml.build("atan", FP64, RNE)
    assert _constants_of(clean) == []
    roles = ["PIO2H", "PIO2L", "TH1", "TH3", "TH7", "TL1", "TL4", "TL7",
             "A_Y6", "A_Y9", "A_Y12", "A_CH0", "A_CH3", "A_CH5", "A_CL1",
             "A_CL3", "A_CL5", "MAGIC", "MSEL", "MAGICN1", "INVN", "KBIT0",
             "KBIT2", "GATE", "BREL", "TINY_EPS", "MINN", "ZERO", "ONE",
             "SIGN", "INF", "QNAN", "ABSM", "QBIT", "INT1", "FL_INVALID",
             "FL_INEXACT", "FL_INEXACT_MARK", "FL_UNDER_INEXACT"]
    for role in roles:
        bad = _fresh_with("atan", FP64, RNE, role)
        found = _constants_of(bad)
        assert found and all(s.startswith("constants: ") for s in found), role
        assert any(f"atan fp64 rne {role}:" in s for s in found), (role, found)
    # the other formats' own: INF, QNAN, the tail's last
    found = _constants_of(_fresh_with("atan", FP256, RTZ, "QNAN"))
    assert any("atan fp256 rtz QNAN:" in s for s in found)
    found = _constants_of(_fresh_with("atan", FP128, RUP, "A_Y20"))
    assert any("atan fp128 rup A_Y20:" in s for s in found)
    # a role no derivation asks, a low word where one word is exact, a word
    # with no role
    found = _constants_of(_fresh_with("atan", FP64, RNE,
                                      extra_role=("EXTRA", 0x1234)))
    assert len(found) == 1 and "derived but not checked: ['EXTRA']" in found[0]
    found = _constants_of(_fresh_with(
        "atan", FP64, RNE, extra_role=("A_CL0", 0x3c90000000000000)))
    assert len(found) == 1 and "A_CL0 is held, but the coefficient is exact " \
        "in one word" in found[0]
    b = ml.build("atan", FP64, RNE)
    name = next(iter(b.words))
    keep = {r: ref for r, ref in b.roles.items() if ref[1] != name}
    assert len(keep) < len(b.roles)
    b.roles = keep
    found = _constants_of(b)
    assert any("words the fragment holds with no role" in s for s in found)


def test_the_plan_the_seed_and_the_identity_legs_of_constants(monkeypatch):
    real = ml.plan_inv
    monkeypatch.setattr(ml, "plan_inv", lambda fmt, G, rho: (
        lambda p: (p[0], p[1] + 1))(real(fmt, G, rho)))
    bad = ml.build("atan", FP64, RNE)
    monkeypatch.undo()
    found = _constants_of(bad)
    assert any("the plan (6, 13) is not the re-derived (6, 12)" in s
               for s in found), found
    # rho is the cells' re-derived one
    b = ml.build("atan", FP64, RNE)
    b.meta["rho"] = b.meta["rho"] + Fraction(1, 10 ** 9)
    assert any("is not the cells' re-derived" in s for s in _constants_of(b))
    # the seed's premise: a table whose worst entry is past EPS_T less 2^-(p-1)
    out, worst = ml._check_inv_seed(FP64)
    assert out == [] and worst == Fraction(1, 2 ** 10)
    out, worst = ml._check_inv_seed(
        FP64, entry=lambda i: ml._seed_entry(i) + (1 << 10))
    assert len(out) == 1 and "past EPS_T less 2^-(p-1)" in out[0]
    lines, findings = ml.check_inv_constants(
        formats=(FP64,), attrs=(RNE,),
        names=())            # no routine: only the identity and the seed
    assert findings == [] and len(lines) == 2
    monkeypatch.setattr(ml, "_seed_entry", lambda i: 1 << 18)
    lines, findings = ml.check_inv_constants(formats=(FP64,), attrs=(RNE,),
                                             names=())
    assert any(s.startswith("seed: RECIP_SEED at fp64") for s in findings)
    monkeypatch.undo()
    # the identity atan(7/8) + atan(1/15) = pi/4: an enclosure off by 2^-100
    real_at = ml._check_atan_rational
    monkeypatch.setattr(ml, "_check_atan_rational", lambda a, b, bits: tuple(
        v + Fraction(1, 2 ** 100) for v in real_at.__wrapped__(a, b, bits)))
    lines, findings = ml.check_inv_constants(formats=(FP64,), attrs=(RNE,),
                                             names=())
    assert any("do not overlap" in s for s in findings), findings


def test_the_series_enclosure_and_its_refusal_to_decide(monkeypatch):
    lo, hi = ml._check_atan_rational(1, 1 + 1, 200)     # atan(1/2)
    import mpmath
    with mpmath.workprec(300):
        v = mpmath.atan(mpmath.mpf(1) / 2)
        q = Fraction(int(v.man) * 2 ** int(v.exp)) if v.exp >= 0 else \
            Fraction(int(v.man), 2 ** -int(v.exp))
    assert lo < q < hi and hi - lo < Fraction(1, 2 ** 180)
    assert ml._check_atan_rational(0, 1, 100) == (Fraction(-1, 2 ** 100),
                                                  Fraction(1, 2 ** 100))
    for a, b in ((1, 1), (2, 1), (-1, 2)):
        with pytest.raises(ValueError, match="needs 0 <= a < b"):
            ml._check_atan_rational(a, b, 100)
    # a fault of the series (a floor lost, the loss not counted: the enclosure
    # shifted by 2^-20 of itself) is a difference by name
    real = ml._check_atan_rational
    monkeypatch.setattr(ml, "_check_atan_rational", lambda a, b, bits: tuple(
        v + Fraction(1, 2 ** 70) for v in real.__wrapped__(a, b, bits)))
    found = _constants_of(ml.build("atan", FP64, RNE))
    assert any(s.startswith("constants: atan fp64 rne TH") or
               s.startswith("constants: atan fp64 rne TL") for s in found), \
        found
    # an enclosure too wide to decide: refused as undecidable, never passed
    monkeypatch.setattr(ml, "_check_atan_rational", lambda a, b, bits: tuple(
        v + s * Fraction(1, 2 ** 40) for v, s in zip(
            real.__wrapped__(a, b, bits), (-1, 1))))
    found = _constants_of(ml.build("atan", FP64, RNE))
    assert any("undecidable" in s for s in found), found


def test_each_leg_of_shape_can_fail_alone():
    builds = {("atan", r): build_of("atan", FP64, r) for r in RND}
    assert I.check_shape(FP64, builds) == []

    def legs(text, tables, n):
        out = I.check_shape(FP64, builds, tables=tables)
        assert len(out) == n and all(text in s and s.startswith("shape: ")
                                     for s in out), (text, out)
    shape = dict(I.SHAPE)
    shape[("atan", "fp64")] = [(177, 54, 15)] + I.SHAPE[("atan", "fp64")][1:]
    legs("pinned 177, 54, 15", I.Tables(shape=shape), 1)
    legs("instructions by phase differ from the model's",
         I.Tables(phases=lambda fn, name: dict(I.model_phases(fn, name),
                                               z=5)), 5)
    legs("the flag word takes", I.Tables(flag_words={
        "atan": I.FLAG_WORDS["atan"] | {0x2}}), 5)
    legs("MIN and", I.Tables(min_max={"atan": (2, 0)}), 5)
    legs("MAX instructions", I.Tables(min_max={"atan": (1, 1)}), 5)
    legs("the cap is 16", I.Tables(caps={
        **ml.INV_LIVE_CAP, "atan": {**ml.INV_LIVE_CAP["atan"], "fp64": 16}}),
         1)
    # a cap one under fails by name; the cap itself holds
    f = ml.fragment("atan", FP64, RNE)
    assert ml.invariants(f, live_cap=15) == []
    assert ml.invariants(f, live_cap=14) == ["15 values live at once, past 14"]
    out = I.check_shape(FP64, builds, tables=I.Tables(caps={
        **ml.INV_LIVE_CAP, "atan": {**ml.INV_LIVE_CAP["atan"], "fp64": 14}}))
    assert any("the cap is 14, the most values live under any attribute is "
               "15" in s for s in out)
    assert any("invariants: 15 values live at once, past 14" in s
               for s in out)
    # no MIN but the index's, no MAX: counted in the fragment
    assert f.counts().get("min") == 1 and f.counts().get("max", 0) == 0


def test_the_reorder_leg_of_shape_fails_alone_on_a_doctored_fragment():
    builds = {("atan", r): build_of("atan", FP64, r) for r in RND}
    frags = {k: b.fragment() for k, b in builds.items()}
    key = ("atan", RNE)
    g = frags[key]
    # still a topological order, one value changed (renumbered operand)
    out = I.check_shape(FP64, builds, fragments={**frags, key: ml._misnumbered(g)})
    assert out and all(s.startswith("shape: ") for s in out)
    assert any("reorder" in s and "dataflow graph is not the design's" in s
               for s in out)
    # an order that reads a value before it is defined
    out = I.check_shape(FP64, builds, fragments={**frags, key: ml._forward(g)})
    assert any("not a topological order" in s for s in out)


# =====================================================================
# the commands of mathlib_runs.py
# =====================================================================

def test_the_inv_commands_run_at_small_sizes_and_refuse_an_existing_out(
        tmp_path, capsys):
    import mathlib_runs as R
    out = tmp_path / "pools.txt"
    R.FINDINGS.clear()
    R.main(["inv-pools", "--quick", "--out", str(out)])
    shown = capsys.readouterr().out
    assert "inv-pools atan fp128 rne:" in shown and "RESULT: ok" in shown
    assert "peak memory" in shown
    text = out.read_text(encoding="utf-8")
    assert "inv-pools atan fp128 rtz:" in text
    # an output path that exists is refused, before any work
    with pytest.raises(SystemExit, match="the file exists"):
        R.main(["inv-pools", "--quick", "--out", str(out)])
    R.FINDINGS.clear()
    R.OUT = None
    out2 = tmp_path / "bound.txt"
    R.main(["inv-bound", "--quick", "--formats", "fp64", "--out", str(out2)])
    shown = capsys.readouterr().out
    assert "inv-bound atan fp64 rne edge seed 121: 12 lanes" in shown
    assert "a sampled lower bound" in shown and "RESULT: ok" in shown
    with pytest.raises(SystemExit, match="the file exists"):
        R.main(["inv-bound", "--quick", "--out", str(out2)])
    R.OUT = None
    R.FINDINGS.clear()
    with pytest.raises(SystemExit, match="fp32 is parcel M4F1's"):
        R.main(["inv-pools", "--formats", "fp32"])
    with pytest.raises(SystemExit, match="--fn 'asin'"):
        R.main(["inv-bound", "--fn", "asin"])
    # --seq runs the compiled shape over the same lanes
    R.FINDINGS.clear()
    R.main(["inv-pools", "--quick", "--formats", "fp64", "--attrs", "rne",
            "--seq", "--step", "40"])
    shown = capsys.readouterr().out
    assert "seq.py and the compiled shape over" in shown \
        and "0 findings" in shown
    R.FINDINGS.clear()
