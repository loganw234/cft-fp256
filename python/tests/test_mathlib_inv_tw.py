# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""atan at fp32 of python/cft_golden/mathlib.py (parcel M4F1, M4's build, wave
3): the TRIPLE word at G = 40, the core, the reconstruction and the final
through round-to-odd (the study's 2.8, docs/studies/M4-invtrig.md; the model is
docs/studies/m4/m4tw.py, which nothing here imports), held to the harness's
fp32 checks (python/tests/mathlib_inv_harness.py, "fp32: the triple word"),
quick enough for the golden stage; the larger runs are
`python python/tests/mathlib_runs.py inv-pools` and `inv-bound` with
`--formats fp32`. Eight checks:

  pools  seq  bound  census  specials  shape  core  constants

and for every check a planted fault shown red in it, the control green in all
(mathlib._INV_TW_PLANTS: atan's ten (parcel M4F2 adds the others' after them), private), every leg of every check shown failing
alone on a doctored input (seq's leg for the committed lanes that must mark has
no lane to run at fp32: it has no structured lane that marks, and says so), the
routing and the refusals, and the port's pins.
The port against the model is a scratch script of the parcel's entry (nothing
here imports docs/studies/m4): the five dag digests, the instructions by phase,
the words, (K3, K2, D), the TwoSum and Fast2Sum counts, and (result, flag
word, Vh, Vl, V2, R, R1, R2) on every lane compared are recorded there, and the
digests pinned below.

What these show and what they do not: the pools, the specials, the census and
the sampled regions are clean and the plants are red; fp32's triple word has no
budget in this build (Logan's answer 3), so that the bound holds on every
argument is not shown here: it is the samples on the box and the card's
exhaustive sweep of all 2^32 arguments.
"""

import functools
import pathlib
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, routines  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_inv_harness as I  # noqa: E402

RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = I.RNE, I.RTZ, I.RDN, I.RUP, I.RMM
MARK = ml.MARK


def rid(r):
    return sf.RND_NAMES[r]


# ---- what the model measured (box-out2/twrun-costs.fp32-tw.out.txt) ----------
# the dag digest of each atan fragment (the first 32 hex digits; the brief's
# 16 are their start), equal to the model's `to_fragment()` digest, scheduled
# and not, at the port (the parcel's scratch script, 5 of 5)
DIGESTS = {
    "rne": "0cc469e865fa74833e10afff21fd96a8",
    "rtz": "fe4369dad918e845185b1f96d14c1e38",
    "rdn": "5c64ab68bc21b60a003e2d0aa9247fc2",
    "rup": "077b1f93f0d54fda67b896e1cacd8ac4",
    "rmm": "b7022437c6fcbcad43670574c0fb4451",
}
# the model's own plants that act on atan, built by the model and by the tree:
# the first 16 hex digits of the design's-order digest, rne rtz rdn rup rmm (the
# scratch script compared them with the model's plant fragments, 15 of 15), and
# rem0_fma's, which the model's final form does not have (the study's 3.6, item
# 5: the first version, made in memory by the drafter: 463 instructions)
PLANT_DIGESTS = {
    "q2_dropped": ("aec8b0aaddb8e231", "389bd15ab048dfbf", "e9a97b9914f5cd14",
                   "4235401ad2989888", "6c96ad93cab6f12f"),
    "z2_dropped": ("3b8d6a59f9817ca2", "c6982d687450f1f0", "2cd5f11b44f32694",
                   "f4a5ca3eb7f1529e", "28618ebcae25bb36"),
    "head3_two": ("602b568f24ac0439", "16cf89c22af0d99e", "5fa7eb313b8b4a11",
                  "ebd06fdf48a3b25c", "7b6d9f960f0f301e"),
    "rem0_fma": ("d24dc034b8e2e520", "ddf37777925f8a03", "fa39c8945c002342",
                 "0bc821b366bbb041", "0dc59ba4c2a7cff1"),
}
PLANT_INSNS = {"q2_dropped": 431, "z2_dropped": 470, "head3_two": 378,
               "rem0_fma": 463}
PHASES = tuple(I.model_phases_tw("atan", "fp32"))
TW_PLANTS = ("q2_dropped", "z2_dropped", "head3_two", "rem0_fma",
             "tiny_gate_off", "tiny_side", "table_entry", "bound_loose",
             "bound_wide", "mark_silenced")


def _doctor(results, i, bits=0, orwith=0, andnot=0):
    out = list(results)
    b, f = out[i]
    out[i] = ((b ^ bits), (f | orwith) & ~andnot)
    return out


# =====================================================================
# the port, and what is private
# =====================================================================

def test_the_builders_and_the_plants_are_private_and_the_double_words_are_as_they_were():
    assert tuple(ml._INV_TW_BUILDERS)[:1] == ("atan",)
    assert tuple(ml._INV_TW_PLANTS)[:len(TW_PLANTS)] == TW_PLANTS
    assert all(isinstance(t, str) and len(t) > 20
               for t in ml._INV_TW_PLANTS.values())
    # no public name: the interface the double word pinned is whole
    assert ml.INV_FORMATS == (FP64, FP128, FP256, FP32)
    assert ml.INV_NAMES == ("atan", "asin", "acos", "atan2")
    assert tuple(ml._INV_BUILDERS) == ("atan", "asin", "acos", "atan2")
    assert not any(n.startswith("_") for n in ml.__all__)
    for name in ("_INV_TW_BUILDERS", "_INV_TW_PLANTS", "_inv_core_tw",
                 "_build_atan_tw", "_build_inv_core_tw", "_plan_inv_tw",
                 "_check_inv_tw_constants"):
        assert name not in ml.__all__ and hasattr(ml, name)
    # and no key of INV_PLANTS is the triple word's alone
    only_tw = {"q2_dropped", "z2_dropped", "head3_two", "rem0_fma",
               "bound_wide", "w2_dropped", "root_fma", "num_two_words",
               "range_low"}
    assert not only_tw & set(ml.INV_PLANTS)
    assert set(ml._INV_TW_PLANTS) - only_tw <= set(ml.INV_PLANTS)
    # the study's variant is not a plant: it is measured in the model, not built
    assert "head3_short" not in ml._INV_TW_PLANTS
    with pytest.raises(ValueError, match="unknown plant 'head3_short'"):
        ml.build("atan", FP32, RNE, plant="head3_short")


def test_the_new_helpers_do_not_shadow_the_trig_triple_words_steps():
    """A first draft named its TwoProd _tw_prod, M2F2's name, and sin at fp32
    stopped building: the section's helpers are _itw_*, and M2F2's four are
    still the functions they were."""
    assert ml._tw_prod.__code__.co_argcount == 4        # (b, a, na, c)
    for name in ("_itw_neg", "_itw_prod", "_itw_chain", "_itw_plain",
                 "_itw_renorm", "_itw_words3", "_itw_sel3", "_itw_theta"):
        assert hasattr(ml, name)
    assert ml.build("sin", FP32, RNE).meta["family"] == "triple word"


@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_the_dag_digests_are_the_models(rnd):
    b = I.tw_build_of(rnd)
    got = ml.dag_digest(b.fragment())[:32]
    assert got == DIGESTS[rid(rnd)], rid(rnd)
    # the design's order and the scheduled fragment are one graph
    assert ml.dag_digest(b.fragment(schedule=False))[:32] == got
    # fragment() is the library's: built once, held to INV_LIVE_CAP's row
    assert ml.dag_digest(ml.fragment("atan", FP32, rnd))[:32] == got


@pytest.mark.parametrize("plant", sorted(PLANT_DIGESTS))
def test_the_plants_are_the_models_by_digest(plant):
    for rnd, want in zip(RND, PLANT_DIGESTS[plant]):
        b = I.tw_build_of(rnd, plant)
        assert ml.dag_digest(b.fragment(schedule=False))[:16] == want
        assert len(b.fragment().body) == PLANT_INSNS[plant]


def test_the_shape_is_the_models():
    b = I.tw_build_of(RNE)
    f = b.fragment()
    assert (len(f), len(f.words), f.live_max()) == (472, 60, 25)
    by = {}
    for i in b.live_indices():
        by[b.phase_of[i]] = by.get(b.phase_of[i], 0) + 1
    assert by == I.model_phases_tw("atan", "fp32") and sum(by.values()) == 472
    assert tuple(dict.fromkeys(b.phase_of)) == (
        "front", "index", "num", "den", "quotient", "z", "tail", "head2",
        "head3", "atan_s", "table", "recon", "final", "classify", "special")
    assert set(b.phase_of) <= set(ml.PHASE_ORDER)
    assert (b.meta["two_sum"], b.meta["fast_two_sum"]) == (22, 31)
    m = b.meta
    assert m["fn"] == "atan" and m["G"] == 40 and m["N"] == 8
    assert (m["K3"], m["K2"], m["D"]) == (3, 3, 8)
    assert isinstance(m["rho"], Fraction) and m["rho"] == ml.inv_rho()[0]
    assert (m["shift"], m["plant"], m["family"]) == (0, None, "triple word")
    assert ml._plan_inv_tw(FP32, 40, m["rho"]) == (3, 3, 8)
    # the same function of the rate-law's other guess: a different plan
    assert ml._plan_inv_tw(FP32, 30, m["rho"]) != (3, 3, 8)
    (tag, ref), = m["data"]
    assert tag == "index" and b.body[ref][0] == sf.OP_FMA
    assert b.phase_of[ref] == "index"
    assert b.words[b.roles["MAGIC"][1]] == b.words[b.body[ref][2][2][1]]
    assert b.inputs == ("a",)
    # the probes: the model's, and the three beside them
    for k in ("Vh", "Vl", "V2", "R", "R1", "R2", "Bv", "mk", "s0", "s1", "s2",
              "rem0", "tt", "Kk"):
        assert b.probes[k][0] == "v", k
    assert {"q0", "N0", "D0"} <= set(b.probes)
    # the flag word, MIN and MAX
    assert routines.flag_words(f) == frozenset({0x0, 0x1, 0x10, 0x18, 0x90})
    assert (f.counts().get("min"), f.counts().get("max", 0)) == (1, 0)


def test_the_scheduler_takes_the_depth_first_order_and_the_cap_is_the_measured_maximum():
    b = I.tw_build_of(RNE)
    g = b.fragment(schedule=False)
    ph = [b.phase_of[i] for i in b.live_indices()]
    live = {"design": g.live_max(),
            "ranked": ml.permuted(g, ml._ranked_order(g, ph)).live_max(),
            "dfs": ml.permuted(g, ml._dfs_order(g)).live_max()}
    assert live == {"design": 26, "ranked": 38, "dfs": 25}      # MEASURED
    f = b.fragment()
    assert f.live_max() == 25 == ml.INV_LIVE_CAP["atan"]["fp32"]
    assert f.body == ml.permuted(g, ml._dfs_order(g)).body
    assert ml.invariants(f) == [] and ml.invariants(f, live_cap=25) == []
    assert ml.invariants(f, live_cap=24) == ["25 values live at once, past 24"]
    assert H.check_reorder(b, f) == []


def test_the_fragment_and_its_build_agree_on_30_random_lanes_and_atan_of_1():
    """The fragment and the unpruned Build agree on 30 random lanes under rne
    and rdn, and atan(1) is right. (The comparison with the model is not this
    test: the scratch script compared 333
    pool, 26 special, 800 region and 772 census lanes under five attributes
    with the model's (result, flag word, Vh, Vl, V2, R, R1, R2) and found 0
    differences, and nothing in this file imports the model.)"""
    for rnd in (RNE, RDN):
        b, f = I.tw_build_of(rnd), I.tw_fragment_of(rnd)
        for x in I.sample("atan", FP32, "random", 30, 3):
            res, fl, _ = b.run(x)
            assert (res, fl) == ml.evaluate(f, x)
    one = sf.one_bits(FP32)
    assert ml.evaluate(I.tw_fragment_of(RNE), one) == (0x3f490fdb, 0x10)


# =====================================================================
# the routing and the refusals
# =====================================================================

def test_the_refusals_are_by_name():
    # asin, acos and atan2 are built at fp32 since parcel M4F2
    # a plant of the double word's alone, at fp32; one of the triple word's
    # alone, at fp64 and the others
    for plant in sorted(set(ml.INV_PLANTS) - set(ml._INV_TW_PLANTS)):
        with pytest.raises(ValueError, match=f"plant {plant!r} does not apply "
                           "to atan at fp32: it is a fault of the double "
                           "word's"):
            ml.build("atan", FP32, RNE, plant=plant)
    for plant in ("q2_dropped", "z2_dropped", "head3_two", "rem0_fma",
                  "bound_wide"):
        for fmt in (FP64, FP128, FP256):
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to atan at {fmt.name}: it is a fault "
                               "of the triple word's, fp32's"):
                ml.build("atan", fmt, RNE, plant=plant)
    with pytest.raises(ValueError, match="unknown plant 'no_such_plant'"):
        ml.build("atan", FP32, RNE, plant="no_such_plant")
    # build_inv_core is the double word's, by name; fp32's core is private
    with pytest.raises(ValueError, match="triple word"):
        ml.build_inv_core(FP32)
    with pytest.raises(ValueError, match="triple word"):
        ml.build_inv_core(FP32, double=True)
    with pytest.raises(ValueError, match="not fp64's"):
        ml._build_inv_core_tw(FP64)
    b = ml.build_inv_core(FP64)
    assert b.meta["family"] == "double word"
    # the double word's atan is as it was
    assert ml.build("atan", FP64, RNE).meta["family"] == "double word"
    assert ml.build("atan", FP32, RNE).meta["family"] == "triple word"


def test_a_plant_the_build_cannot_reach_is_refused_by_name(monkeypatch):
    monkeypatch.setitem(ml._INV_TW_PLANTS, "unreached",
                        "a fault the builder never acts on")
    with pytest.raises(ValueError, match="plant 'unreached' does not apply to "
                       "atan at fp32: the fault is not reached"):
        ml.build("atan", FP32, RNE, plant="unreached")
    with pytest.raises(ValueError, match="does not apply to inv_core"):
        ml._build_inv_core_tw(FP32, plant="unreached")
    # the core alone reaches the core's plants and refuses the others by name
    for plant in TW_PLANTS:
        if plant in {"q2_dropped", "z2_dropped", "head3_two", "rem0_fma",
                     "table_entry"}:
            assert ml._build_inv_core_tw(FP32, plant=plant).meta["plant"] \
                == plant
        else:
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to inv_core at fp32"):
                ml._build_inv_core_tw(FP32, plant=plant)


def test_every_plant_changes_the_build():
    clean = I.tw_build_of(RNE)
    for plant in TW_PLANTS:
        b = I.tw_build_of(RNE, plant)
        same = (b.body == clean.body and b.words == clean.words
                and b.result == clean.result and b.flags == clean.flags)
        assert not same, plant


def test_guard_and_bound_shift_are_the_builds_own():
    b = ml.build("atan", FP32, RNE, bound_shift=34)
    assert b.meta["shift"] == 34 and b.meta["G"] == 40
    assert b.words[b.roles["BREL"][1]] == ml._pow2(FP32, -(24 + 40) + 34)
    c = ml.build("atan", FP32, RNE, guard=30)
    assert c.meta["G"] == 30 and (c.meta["K3"], c.meta["K2"], c.meta["D"]) \
        == ml._plan_inv_tw(FP32, 30, ml.inv_rho()[0])


# =====================================================================
# the core: both branches, and the three-word one alone
# =====================================================================

def test_the_core_has_two_branches_and_the_three_word_one_is_longer():
    one, three = I.tw_core_of(None, False), I.tw_core_of(None, True)
    assert one.inputs == ("a", "b") and three.inputs == (
        "a", "b", "c", "d", "e", "f")
    assert one.meta["fn"] == three.meta["fn"] == "inv_core"
    assert (len(one.body), len(three.body)) == (383, 448)     # MEASURED
    # the lanes: atan(1/3) both ways, a word in each position is read
    x, y = sf.one_bits(FP32), ml._enc(FP32, Fraction(3))
    tiny = ml._pow2(FP32, -30)
    a = three.run((x, 0, 0, y, 0, 0), ("th0",))
    assert a[2]["th0"] == one.run((x, y), ("th0",))[2]["th0"]
    for k in range(6):
        lane = [x, 0, 0, y, 0, 0]
        lane[k] = tiny if k not in (0, 3) else lane[k]
        if k in (1, 2, 4, 5):
            assert three.run(tuple(lane), ("th0", "th1", "th2")) != \
                three.run((x, 0, 0, y, 0, 0), ("th0", "th1", "th2")), k
    out, t = I.check_core_tw(None, False)
    assert out == [] and t["lanes"] == 60
    assert (t["past"], t["kk"], t["negative"]) == (0, 0, 0)
    out, t3 = I.check_core_tw(None, True)
    assert out == [] and t3["lanes"] == 60
    assert (t3["past"], t3["kk"], t3["negative"]) == (0, 0, 0)
    assert t["largest"] < -5 and t3["largest"] < -5
    # the lanes: n <= d, three at t = 1 in the single-word branch; in the
    # three-word one the low words are present and of both signs
    for n, d in I.core_lanes_tw():
        assert 0 < ml._dec(FP32, n) <= ml._dec(FP32, d)
    assert sum(1 for n, d in I.core_lanes_tw() if n == d) == 3
    lanes3 = I.core_lanes_tw(triple=True)
    signs = {(v >> 31) for l in lanes3 for v in (l[1], l[2], l[4], l[5])
             if v & 0x7fffffff}
    assert signs == {0, 1}
    for l in lanes3:
        N = sum(ml._dec(FP32, v) for v in l[:3])
        D = sum(ml._dec(FP32, v) for v in l[3:])
        assert 0 < N <= D and l[0] <= l[3]


def test_each_leg_of_core_can_fail_alone():
    for triple in (False, True):
        lanes = I.core_lanes_tw(triple=triple)[:12]
        base = I.tw_core_of(None, triple)

        def runner(fix, base=base):
            def run(lane, want=()):
                a, b_, pr = base.run(lane, want)
                return fix(a, b_, dict(pr))
            return run
        out, t = I.check_core_tw(None, triple, lanes=lanes, b=base,
                                 runner=runner(lambda a, b_, c: (a, b_, c)))
        assert out == [] and t["lanes"] == 12
        # the bound leg alone: theta0's first word one ulp off
        out, t = I.check_core_tw(None, triple, lanes=lanes, b=base,
                                 runner=runner(lambda a, b_, c: (
                                     a, b_, {**c, "th0": c["th0"] + 1})))
        assert len(out) == 1 and "past 2^-(p+G) theta0" in out[0] \
            and out[0].startswith("core: ") and t["kk"] == t["negative"] == 0

        # Kk's contract alone: low bits k + 1 (mod 8)
        def kk(a, b_, c):
            return a, b_, {**c, "Kk": c["Kk"] + 1}
        out, t = I.check_core_tw(None, triple, lanes=lanes, b=base,
                                 runner=runner(kk))
        assert len(out) == 1 and "break Kk's contract" in out[0] \
            and t["past"] == 0 and t["negative"] == 0

        # th0 < 0 alone: the sign flipped and the other words flipped with it
        def neg(a, b_, c):
            return a, b_, {k: (v | (1 << 31) if k.startswith("th") else v)
                           for k, v in c.items()}
        out, t = I.check_core_tw(None, triple, lanes=lanes, b=base,
                                 runner=runner(neg))
        assert any("have th0 < 0" in s for s in out)
        assert all(s.startswith("core: ") for s in out)
    # and a plant that reaches the core is red in its bound leg, on both
    # branches
    for plant in ("q2_dropped", "z2_dropped", "head3_two", "table_entry"):
        for triple in (False, True):
            out, t = I.check_core_tw(plant, triple)
            assert any("past 2^-(p+G) theta0" in s for s in out), (plant,
                                                                   triple)
    # rem0_fma is green in the core's 60 lanes: only a committed lane of the
    # whole routine reaches it
    assert I.check_core_tw("rem0_fma", False)[0] == []


# =====================================================================
# the checks, clean
# =====================================================================

@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_pools(rnd):
    f = I.tw_fragment_of(rnd)
    xs = I.pool("atan", FP32)
    assert len(xs) == 333                     # MEASURED: I._unary_pool(FP32)
    out, t = I.check_pools_tw(rnd)
    assert out == [] and t.n == 333
    # MEASURED: the pools through all five attributes mark no lane, and no
    # fp32 row of INV_POOL_MARKS is needed
    assert t.marked == [] and t.wrong == []
    assert not any(m[1] == "fp32" for m in I.INV_POOL_MARKS)


@pytest.mark.parametrize("rnd", (RNE, RTZ), ids=rid)
def test_seq(rnd):
    out, lanes = I.check_seq_tw(rnd)
    assert out == [] and len(lanes) > 80      # MEASURED 88
    # fp32 has no committed structured lane that marks, and says so
    assert I.structured_lanes("atan", FP32, rnd) == []
    assert ("atan", "fp32", rnd) not in I.SEQ_MARKED
    f = I.tw_fragment_of(rnd)
    assert not any(ml.evaluate(f, x)[1] & MARK for x in lanes)


def test_seq_on_the_inflated_bound_marks_lanes_and_runs_the_mark_through_seq():
    out, lanes = I.check_seq_tw(RNE, None, I.TW_SEQ_SHIFT)
    assert out == []
    f = I.tw_fragment_of(RNE, None, I.TW_SEQ_SHIFT)
    marked = [x for x in lanes if ml.evaluate(f, x)[1] & MARK]
    assert len(marked) >= 3, len(marked)      # MEASURED 5 of 388
    b = I.tw_build_of(RNE, None, I.TW_SEQ_SHIFT)
    assert b.meta["shift"] == 34 and b.meta["G"] == 40
    # G' = 6: Bv = 2^-(p + G - 34)
    assert b.words[b.roles["BREL"][1]] == ml._pow2(FP32, -30)
    # the marked lanes' byte has the mark and STATUS[6] is set: through
    # mathlib_harness.r24_program and seq.run
    prog, bank = H.r24_program(f)
    from cft_golden import seq
    res = seq.run(prog, *I._split(lanes), bank=bank)
    idx = {x: i for i, x in enumerate(lanes)}
    assert all(res.lane_flags[idx[x]] & seq.LANE_MARKED for x in marked)
    assert res.status & seq.STATUS_MARKED
    # a marked lane's guess is not promised: counted, not a finding
    right = sum(1 for x in marked
                if (lambda r: (r[0], r[1] & 0x1F))(ml.evaluate(f, x))
                == I.golden(FP32, RNE, x, "atan"))
    assert right <= len(marked)


def test_bound():
    out, worst = I.check_bound_tw()
    assert out == [], out
    assert set(worst) == {"edge", "big", "small", "random", "rem0"}
    for region in ("edge", "big", "small", "random"):
        w, main, n = worst[region]
        assert main == n == 48, region
    # the largest is a SAMPLED lower bound (192 points, seed 11, plus the 16
    # committed lanes, which the clean build holds): MEASURED 2^-8.1 (edge),
    # -8.4, -8.3 and -9.1 of Bv, and 2^-9.0 on the committed lanes
    top = max(w for w, _m, _n in worst.values())
    assert -10 < top < -6, worst
    assert worst["rem0"][1:] == (16, 16)


def test_the_bound_sums_all_three_words():
    """bound_log2 reads V2 where the build has it: without it the same lane is
    far past the bound (V2 is 2^-48 of V, the bound 2^-64)."""
    b = I.tw_build_of(RNE)
    x = I.sample("atan", FP32, "edge", 4, 5)[0]
    with_v2 = I.bound_log2(b, x)
    _r, _f, pr = b.run(x, ("Vh", "Vl", "V2", "Bv"))
    assert "V2" in b.probes and pr["V2"] & 0x7fffffff
    import mpmath
    with mpmath.workprec(4 * 24 + 200):
        V = I.value(FP32, pr["Vh"]) + I.value(FP32, pr["Vl"])
        err = abs(I._mp(V) - I.true_value("atan", FP32, x))
        short = float(mpmath.log(err / I._mp(abs(I.value(FP32, pr["Bv"]))), 2))
    assert with_v2 < -5 and short > 10
    # the double word's builds have no V2 and are read as they were
    d = ml.build("atan", FP64, RNE)
    assert "V2" not in d.probes and I.bound_log2(d, 0x3fd7ffffffffffff) < 0


def test_census():
    tiny = I.census_tiny_tw()
    near = I.census_near_tw()
    assert len(tiny) == 256 and len(set(tiny)) == 144
    assert [len(x[3]) for x in near] == [129] * 4
    out, t = I.check_census_tw()
    assert out == [] and t["marked"] == 0 and t["wrong"] == 0
    assert t["lanes"] == (256 + 4 * 129) * 5       # five attributes
    # the families have no centre at fp32: every window lane sits 2^12 or more
    # bounds from its boundary (MEASURED, mpmath at 400 bits): the four
    # windows' centres are 2^-50.9 to 2^-47.0 from their boundary, their edges
    # 2^-43.8 to 2^-39.6, and the bound is about 2^-63.4
    d = I.census_distances()
    assert [x[0] for x in d] == ["grid boundary 0", "grid boundary 1",
                                 "midpoint boundary 0", "midpoint boundary 1"]
    for label, centre, edge in d:
        assert -52 < centre < -46 and -45 < edge < -39, (label, centre, edge)


def test_the_census_lanes_are_what_they_say():
    """The lanes are held to predicates the construction does not give: the
    tiny lanes are +-c 2^-e for c 1 to 16 and e 12 to 19, both signs, read
    back from the bits; each window is 129 consecutive arguments, and its
    centre is the argument whose atan lies nearest the boundary it was placed
    about (a neighbour is farther)."""
    seen = set()
    for x in I.census_tiny_tw():
        v = ml._dec(FP32, x & 0x7fffffff)
        k = [(c, e) for e in range(12, 20) for c in range(1, 17)
             if Fraction(c, 2 ** e) == v]
        assert k, hex(x)
        seen.add(((x >> 31), k[0]))
    assert len(seen) == 144 * 2 // 2 * 1 or len(seen) >= 144
    import mpmath
    with mpmath.workprec(400):
        for label, bd, x0, lanes in I.census_near_tw():
            assert lanes == list(range(x0 - 64, x0 + 65)), label
            assert bd < ml._pi() / 2                  # below pi/2, nearest
            err = {j: abs(mpmath.atan(I._mp(I.value(FP32, x0 + j)))
                          - I._mp(bd)) for j in (-1, 0, 1)}
            assert err[0] < err[-1] and err[0] < err[1], label
    # the boundaries: grid points and midpoints of fp32 nearest pi/2 from below
    grid = [b for _l, b, _x, _ in I.census_near_tw()[:2]]
    mid = [b for _l, b, _x, _ in I.census_near_tw()[2:]]
    u = Fraction(1, 2 ** 23)                          # ulp of pi/2 at fp32
    assert grid[0] - grid[1] == u and mid[0] - mid[1] == u
    assert all(ml._dec(FP32, ml._enc(FP32, g)) == g for g in grid)
    assert all(ml._dec(FP32, ml._enc(FP32, m)) != m for m in mid)
    assert mid[0] - grid[0] == u / 2 or grid[0] - mid[0] == u / 2


@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_specials(rnd):
    out, n = I.check_specials(I.tw_fragment_of(rnd))
    assert out == [] and n == 26, (out, n)


def test_shape():
    builds = {("atan", r): I.tw_build_of(r) for r in RND}
    assert I.check_shape_tw() == []
    # the pinned (472, 60, 25), five times
    assert I.SHAPE_TW[("atan", "fp32")] == [(472, 60, 25)] * 5
    assert ml.INV_LIVE_CAP["atan"]["fp32"] == 25
    for r, b in zip(RND, builds.values()):
        f = b.fragment()
        assert (len(f), len(f.words), f.live_max()) == (472, 60, 25)


def test_constants_in_process_and_as_a_program():
    findings, lines = I.check_constants_tw()
    assert findings == []
    assert len(lines) == 6
    assert lines[0].startswith("atan(7/8) + atan(1/15) = pi/4")
    assert lines[1].startswith("RECIP_SEED at fp32")
    assert "atan fp32 (triple word): G = 40, plan (K3, K2, D) = (3, 3, 8): " \
        "330 derived constants in 5 fragments" in lines[2]       # MEASURED
    import subprocess
    run = lambda *a: subprocess.run(            # noqa: E731
        [sys.executable, "-B", "-m", "cft_golden.mathlib", *a],
        cwd=pathlib.Path(__file__).resolve().parents[1], capture_output=True,
        text=True)
    r = run("--check", "--only", "inv-tw")
    assert r.returncode == 0, r.stdout + r.stderr
    got = r.stdout.splitlines()
    assert got[:6] == lines
    assert got[6] == ("mathlib --check (inv, triple word): 4 routines, 1 "
                      "format, 0 differences") and len(got) == 7
    # the list names inv-tw, and a name outside it is refused
    r = run("--check", "--only", "nonesuch")
    assert r.returncode != 0 and "inv-tw" in r.stderr


def test_check_prints_inv_tw_lines_only_under_only_and_exits_1_on_a_difference(
        monkeypatch, capsys):
    for name in ("check_constants", "check_reduction_constants",
                 "check_reduction_tw_constants", "check_trig_constants",
                 "check_inv_constants"):
        monkeypatch.setattr(ml, name, lambda *a, **k: ([], []))
    monkeypatch.setattr(ml, "_check_inv_tw_constants",
                        lambda *a, **k: (["a tw line"], ["tw x differs"]))
    assert ml.main(["--check"]) == 1
    shown = capsys.readouterr().out
    # the default run prints only the DIFFERENCE lines of the triple word
    assert "DIFFERENCE: tw x differs" in shown
    assert "a tw line" not in shown and "triple word" not in shown
    assert ml.main(["--check", "--only", "inv-tw"]) == 1
    shown = capsys.readouterr().out.splitlines()
    assert shown == ["a tw line", "DIFFERENCE: tw x differs",
                     "mathlib --check (inv, triple word): 4 routines, 1 "
                     "format, 1 differences"]
    # clean: the default run prints nothing of it
    monkeypatch.setattr(ml, "_check_inv_tw_constants",
                        lambda *a, **k: (["a tw line"], []))
    assert ml.main(["--check"]) == 0
    shown = capsys.readouterr().out.splitlines()
    assert all(s.startswith("mathlib --check") for s in shown)
    assert not any("triple word" in s for s in shown)
    # and --only inv does not run it
    called = []
    monkeypatch.setattr(ml, "_check_inv_tw_constants",
                        lambda *a, **k: called.append(1) or ([], []))
    assert ml.main(["--check", "--only", "inv"]) == 0
    assert called == []
    capsys.readouterr()


# =====================================================================
# 3.6 item 5: the first remainder by one FMA
# =====================================================================

def test_rem0_fma_is_red_on_the_committed_lanes_and_on_no_sampled_lane():
    lanes = I.rem0_lanes()
    assert len(lanes) == 16 and len(set(lanes)) == 16
    assert 0x404a17f5 in lanes                      # the drafter's lane
    clean, plant = I.tw_build_of(RNE), I.tw_build_of(RNE, "rem0_fma")
    for x in lanes:
        # the independent predicate: N0 - q0 D0 is NOT representable in one
        # word, in exact rationals from the CLEAN build's probes
        assert I.rem0_inexact(x), hex(x)
        assert I.bound_log2(clean, x) < -5, hex(x)
        r = I.bound_log2(plant, x)
        assert r > 10, (hex(x), r)                  # 2^11.4 to 2^12.2 of Bv
    out, worst = I.check_bound_tw("rem0_fma")
    assert len(out) == 1 and out[0].startswith("bound: atan fp32 rne rem0: "
                                                "16 of 16 main-path lanes")
    # the four sampled regions of 48 points are green: red in nothing there
    for region in ("edge", "big", "small", "random"):
        assert worst[region][0] < -5, region
    # and the pools are green under every attribute
    for rnd in RND:
        assert I.check_pools_tw(rnd, "rem0_fma")[0] == [], rid(rnd)
    # the predicate is the definition: where the remainder is representable
    # the plant IS the clean build (V, bit for bit), on 120 lanes of the
    # regions; where it is not, the plant's V differs on the committed lanes
    same = differ = 0
    for region in ("edge", "random", "small", "big"):
        for x in I.sample("atan", FP32, region, 30, 17):
            if not I.in_main("atan", FP32, x):
                continue
            a = plant.run(x, ("Vh", "Vl", "V2"))[2]
            b = clean.run(x, ("Vh", "Vl", "V2"))[2]
            if I.rem0_inexact(x):
                differ += 1
            else:
                same += 1
                assert a == b, hex(x)
    assert same > 50 and differ >= 0
    for x in lanes:
        assert plant.run(x, ("Vh", "Vl", "V2"))[2] != \
            clean.run(x, ("Vh", "Vl", "V2"))[2]


def test_rem0_fma_changes_the_remainder_and_nothing_before_it():
    clean, plant = I.tw_build_of(RNE), I.tw_build_of(RNE, "rem0_fma")
    assert len(clean.fragment().body) - len(plant.fragment().body) == 9
    x = 0x404a17f5
    pc = clean.run(x, ("q0", "N0", "D0", "rem0", "tt", "Kk"))[2]
    pp = plant.run(x, ("q0", "N0", "D0", "rem0", "tt", "Kk"))[2]
    for k in ("q0", "N0", "D0", "tt", "Kk"):
        assert pc[k] == pp[k], k
    n0, q0, d0 = (I.value(FP32, pc[k]) for k in ("N0", "q0", "D0"))
    exact = n0 - q0 * d0
    assert I.value(FP32, pc["rem0"]) != exact       # the clean one is its head
    # the plant's remainder is the single rounding of the exact one
    assert pp["rem0"] == ml._enc(FP32, exact)


def test_head3_short_is_a_variant_and_not_a_plant():
    """The model's head3-short (one triple-word head step in two words) stays
    inside the bound (2^-3.37 Bv on the edge region of 200 lanes, MEASURED on
    the model by the parcel's scratch script): it cannot turn a check red and
    is not in the tree's table. head3_two (two steps) is, and is red."""
    assert "head3_short" not in ml._INV_TW_PLANTS
    two = I.tw_build_of(RNE, "head3_two")
    assert (two.meta["K3"], two.meta["K2"]) == (1, 5)
    assert I.check_bound_tw("head3_two")[0]


# =====================================================================
# the plants: each red in its checks and green in the others
# =====================================================================

# Every row lists EVERY check, red, green or NOT RUN (a test fails on a row that
# omits one, or that lists a check green that did not run). A check that does
# not run for a plant is neither red nor green: the core is refused by name
# ("does not apply") for tiny_gate_off, tiny_side, bound_loose, bound_wide and
# mark_silenced, which hold no fault the core can reach, and is run on both
# branches for the other five. MEASURED by this parcel: python/tests/mathlib_inv_harness.
# red_checks_tw(plant) is the run (pools under rne and rtz, census under rtz,
# the clean census under all five attributes being test_census's, seq
# under rne and rtz and once on the bound inflated to G' = 6, bound over the
# four regions of 48 points and the committed lanes of rem0_fma under rne,
# specials and shape under all five attributes, core on both branches where it
# runs, and constants under rne). The brief expected bound_wide red in pools and census:
# it is red in census and constants, and green in pools, whose 333 lanes would
# each mark with probability about 2^-17 at the bound 2^22 wide (ESTIMATE: 2 Bv
# over the spacing 2^-24 of results, Bv = 2^-42 |V|). Every plant
# that changes an instruction or a word count is red in shape.
CHECKS = I.CHECKS_TW
NR = ("core",)                     # not run: the core holds no such fault
PLANTED = [
    ("q2_dropped", ("bound", "shape", "core"),
     ("pools", "seq", "census", "specials", "constants"), ()),
    ("z2_dropped", ("bound", "shape", "core"),
     ("pools", "seq", "census", "specials", "constants"), ()),
    ("head3_two", ("bound", "shape", "core", "constants"),
     ("pools", "seq", "census", "specials"), ()),
    ("rem0_fma", ("bound", "shape"),
     ("pools", "seq", "census", "specials", "core", "constants"), ()),
    ("tiny_gate_off", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "census"), NR),
    ("tiny_side", ("pools", "seq", "census", "specials", "shape", "constants"),
     ("bound",), NR),
    ("table_entry", ("pools", "seq", "bound", "core", "constants"),
     ("census", "specials", "shape"), ()),
    ("bound_loose", ("seq", "bound", "constants"),
     ("pools", "census", "specials", "shape"), NR),
    ("bound_wide", ("census", "constants"),
     ("pools", "seq", "bound", "specials", "shape"), NR),
    ("mark_silenced", ("seq", "shape"),
     ("pools", "bound", "census", "specials", "constants"), NR),
]



def _row_id(r):
    return r[0]


def _check_row(row):
    plant, red, green, notrun = row
    every = set(red) | set(green) | set(notrun)
    assert every == set(CHECKS), (plant, set(CHECKS) - every)
    assert not (set(red) & set(green) or set(red) & set(notrun)
                or set(green) & set(notrun)), plant
    assert len(red) + len(green) + len(notrun) == len(CHECKS), plant
    assert red, plant


@functools.lru_cache(maxsize=None)
def _run(plant):
    """(red, not_run) of red_checks_tw(plant)."""
    not_run = {}
    red = I.red_checks_tw(plant, not_run=not_run)
    return red, not_run


def _red(plant):
    return _run(plant)[0]


def _judge(row):
    """The plant's run against its row: red checks red, green checks green AND
    run, not-run checks reported as not run (with the reason)."""
    plant, red, green, notrun = row
    got, nr = _run(plant)
    for check in red:
        assert check in got, f"{plant}: {check} stays green"
        assert all(s.startswith(check + ":") or s.startswith("shape: ")
                   for s in got[check]), (plant, check, got[check][:2])
    for check in green:
        assert check not in got, f"{plant}: {check} is red: {got[check][:2]}"
        assert check not in nr, (f"{plant}: {check} is listed green, but did "
                                 f"not run: {nr[check][:80]}")
    assert set(nr) == set(notrun), (plant, sorted(nr), sorted(notrun))
    for check in notrun:
        assert nr[check].startswith(check + ": not run (the core holds no "
                                    "such fault)"), nr[check]
        assert check not in got, f"{plant}: {check} did not run but is red"


def test_the_control_is_green_in_every_check():
    red, nr = _run(None)
    assert red == {}, {k: v[:1] for k, v in red.items()}
    assert nr == {}, "the control runs every check"


@pytest.mark.parametrize("row", PLANTED, ids=_row_id)
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(row):
    _judge(row)


def test_a_check_that_did_not_run_is_not_listed_green():
    """The row of tiny_side with core listed GREEN, as it was: the core did not
    run for it, so the judge refuses it by name; so is a row that omits the
    not-run report, and one that reports a core that ran as not run."""
    plant, red, green, notrun = next(r for r in PLANTED if r[0] == "tiny_side")
    assert notrun == ("core",)
    with pytest.raises(AssertionError, match="core is listed green, but did "
                       "not run"):
        _judge((plant, red, green + ("core",), ()))
    with pytest.raises(AssertionError):
        _judge((plant, red, green, ()))
    q = next(r for r in PLANTED if r[0] == "q2_dropped")
    with pytest.raises(AssertionError):
        _judge((q[0], ("bound", "shape"), q[2], ("core",)))
    # and the harness says which checks did not run, for every plant
    holds_none = {"tiny_gate_off", "tiny_side", "bound_loose", "bound_wide",
                  "mark_silenced"}
    for p in TW_PLANTS:
        assert set(_run(p)[1]) == ({"core"} if p in holds_none else set()), p


def test_every_plant_is_in_the_table_and_every_row_lists_every_check():
    named = [row[0] for row in PLANTED]
    # atan's ten; the others' twelve are test_mathlib_inv_tw2.py's
    assert tuple(named) == TW_PLANTS and set(named) <= set(ml._INV_TW_PLANTS)
    assert len(CHECKS) == 8
    for row in PLANTED:
        _check_row(row)
    # the row check itself is shown to refuse a row that omits a check, one
    # that names a check red and green, and one red in nothing
    rest = tuple(c for c in CHECKS if c not in ("bound", "pools"))
    for bad in (("q2_dropped", ("bound",), ("pools",), ()),
                ("q2_dropped", ("bound", "pools"), ("pools",) + rest, ()),
                ("q2_dropped", ("bound",), ("pools",) + rest, ("core",)),
                ("q2_dropped", (), tuple(CHECKS), ())):
        with pytest.raises(AssertionError):
            _check_row(bad)
    _check_row(("q2_dropped", ("bound",), ("pools",) + rest, ()))
    _check_row(("q2_dropped", ("bound",), ("pools",) + tuple(
        c for c in rest if c != "core"), ("core",)))


def test_every_check_has_a_plant_red_in_it_and_every_plant_is_red_somewhere():
    red = {c for row in PLANTED for c in row[1]}
    assert red == set(CHECKS), set(CHECKS) - red
    assert all(row[1] for row in PLANTED)
    # a plant red in nothing is a check that cannot fail: the rows say every
    # plant is red somewhere, and the run agrees with the rows
    for plant in TW_PLANTS:
        assert _red(plant), plant


# =====================================================================
# every leg of every check can fail alone
# =====================================================================

def test_each_leg_of_pools_can_fail_alone():
    f = I.tw_fragment_of(RNE)
    plain, one = 0x40400000, 0x3f800000
    xs = [plain, one, 0x3e800000]
    clean = [ml.evaluate(f, x) for x in xs]
    assert not any(fw & MARK for _b, fw in clean)
    out, t = I.check_pools(f, xs, results=clean)
    assert out == [] and (t.n, len(t.marked)) == (3, 0)
    cases = {
        "unmarked lanes differ from transcend.atan":
            _doctor(clean, 1, bits=1),
        "marked off the committed list": _doctor(clean, 1, orwith=0x80),
    }
    for text, results in cases.items():
        out, t = I.check_pools(f, xs, results=results)
        assert len(out) == 1 and text in out[0] \
            and out[0].startswith("pools: "), (text, out)
    # a stray bit on a lane that is listed and marked: only the stray leg
    out, t = I.check_pools(f, xs, results=_doctor(clean, 0, orwith=0xA0),
                           marks={plain: "x"})
    assert len(out) == 1 and out[0].startswith("pools: ") and \
        "flag words carry bits other than [4:0] and the mark" in out[0]
    # a listed lane that does not mark
    out, t = I.check_pools(f, xs, results=clean, marks={plain: "x"})
    assert len(out) == 1 and "on the committed list are not marked" in out[0]
    # a marked lane's guess is replayed and counted, and is not a finding
    out, t = I.check_pools(f, xs, results=_doctor(clean, 0, bits=1, orwith=0x80),
                           marks={plain: "x"})
    assert out == [] and len(t.guess_wrong) == 1 and t.marked_right == 0
    # the wrapper is the pool of fp32, 333 lanes, and a plant is red in it
    assert I.check_pools_tw(RNE, "table_entry")[0]


def test_each_leg_of_seq_can_fail_alone():
    f = I.tw_fragment_of(RNE)
    # +inf is the lane a loud third MUL shows on: P = c d = 0 x inf raises
    # invalid, which the lane's flag word (inexact alone) does not
    xs = [0x3f800000, 0x40400000, 0x1, 0x7f800000, 0x3f9b9037]
    out, lanes = I.check_seq(f, xs)
    assert out == [] and len(lanes) == 5
    out, _ = I.check_seq(f, xs, evaluator=lambda g, x: (
        ml.evaluate(g, x)[0] ^ 1, ml.evaluate(g, x)[1]))
    assert len(out) == 1 and "seq.py and evaluate() differ on 5 lanes" \
        in out[0]
    # (the scheduled fragment's order is the depth-first one, so it is the
    # fourth MUL that is outside the moved QUIET here, not the third)
    out, _ = I.check_seq(f, xs, loud=4)
    assert out and all("raised" in s for s in out)
    assert any("lane 0x7f800000 raised 0x11, want 0x10" in s for s in out), out
    assert I.check_seq(f, xs, loud=1)[0] == []
    assert I.check_seq(f, xs, loud=False)[0] == []
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(r, "flags", r.flags
                                                        ^ 1), r)[1])
    assert len(out) == 1 and "FLAGS" in out[0] and "OR of the lanes" in out[0]
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(
        r, "status", r.status ^ 0x40), r)[1])
    assert len(out) == 1 and "STATUS[6]" in out[0]
    # a fragment wrong the same way on seq.py and in evaluate()
    bad = I.tw_fragment_of(RNE, "table_entry")
    out, _ = I.check_seq(bad, [0x3ebfffff])
    assert any("unmarked lanes on seq.py differ from transcend.atan" in s
               for s in out) and any("deposited" in s for s in out)
    assert not any("seq.py and evaluate()" in s for s in out)
    # the wrapper's own leg: a bound inflated to G' = 6 that marks no lane
    # leaves the mark unexercised (mark_silenced: the flag word never says it)
    out, lanes = I.check_seq_tw(RNE, "mark_silenced", I.TW_SEQ_SHIFT)
    assert any("marks none of the" in s and "the mark is not exercised" in s
               for s in out)
    out, lanes = I.check_seq_tw(RNE, None, I.TW_SEQ_SHIFT,
                                xs=[0x3f800000, 0x40400000])
    assert any("marks none of the 2 lanes" in s for s in out)
    # and a marked lane the byte does not carry: a doctored seq result
    sf_ = I.tw_fragment_of(RNE, None, I.TW_SEQ_SHIFT)
    ms = [x for x in I.check_seq_tw(RNE, None, I.TW_SEQ_SHIFT)[1]
          if ml.evaluate(sf_, x)[1] & MARK][:2]
    out, _ = I.check_seq(sf_, ms, post=lambda r: (setattr(
        r, "status", r.status & ~0x40), r)[1])
    assert any("STATUS[6]" in s for s in out)


def test_each_leg_of_bound_can_fail_alone():
    b = I.tw_build_of(RNE)
    xs = I.sample("atan", FP32, "edge", 6, 5)
    out, (worst, main, lanes) = I.check_bound(b, xs)
    assert out == [] and main == lanes == 6 and worst < 0
    # a main-path lane past 1 Bv, every lane right in transcend.py's sense
    wide = I.tw_build_of(RNE, "bound_loose")
    out, _ = I.check_bound(wide, xs)
    assert len(out) == 1 and "6 of 6 main-path lanes are past the bound" \
        in out[0] and out[0].startswith("bound: ")
    # a lane that differs from transcend.py with V right (not a main-path
    # lane): the tiny path off, the main path answering a tiny argument
    off = I.tw_build_of(RNE, "tiny_gate_off")
    out, (worst, main, lanes) = I.check_bound(off, [0x1, 0x80000001])
    assert len(out) == 1 and "2 unmarked lanes differ from transcend.atan" \
        in out[0] and main == 0
    # the committed lanes are a region of the check: the plant is red there
    out, w = I.check_bound_tw("rem0_fma")
    assert [s for s in out if "rem0" in s] and \
        not [s for s in out if "rem0" not in s]
    assert w["rem0"][0] > 10
    # and `extra` stands for the table: no lane, no finding
    assert I.check_bound_tw("rem0_fma", extra=[])[0] == []
    # a region of the control's is green, the fifth too
    assert I.check_bound_tw(extra=[0x404a17f5])[0] == []


def test_each_leg_of_census_can_fail_alone():
    lanes = [("tiny", I.census_tiny_tw()[:8]),
             ("window", I.census_near_tw()[0][3][:8])]
    out, t = I.check_census_tw((RNE,), lanes=lanes)
    assert out == [] and t == {"lanes": 16, "marked": 0, "wrong": 0}
    # a marked lane (zero marks is the claim)
    out, t = I.check_census_tw((RNE,), lanes=lanes, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == lanes[1][1][0] else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "1 of 8 lanes are marked (zero is the claim)" \
        in out[0] and out[0].startswith("census: ") and t["wrong"] == 0
    # an unmarked lane that is not transcend.py's
    out, t = I.check_census_tw((RNE,), lanes=lanes, evaluator=lambda g, x: (
        lambda r: (r[0] ^ 1, r[1]) if x == lanes[0][1][0] else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "1 of 8 unmarked lanes differ from " \
        "transcend.atan" in out[0] and t["marked"] == 0
    # a flag word alone
    out, t = I.check_census_tw((RTZ,), lanes=lanes, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] ^ 1) if x == lanes[0][1][1] else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "rtz" in out[0]
    # the attributes are each run: a fault under one attribute only
    out, t = I.check_census_tw((RNE, RTZ), lanes=lanes,
                               evaluator=lambda g, x: (
                                   ml.evaluate(g, x)[0] ^ (1 if g.rnd == RTZ
                                                           else 0),
                                   ml.evaluate(g, x)[1]))
    assert out and all("rtz" in s for s in out) and t["lanes"] == 32
    # a plant is red in the real lanes: tiny_side in the tiny family
    out, t = I.check_census_tw((RTZ,), "tiny_side")
    assert out and "tiny" in out[0] and t["marked"] == 0 and t["wrong"] > 0
    # bound_wide marks the windows
    out, t = I.check_census_tw((RNE,), "bound_wide")
    assert t["marked"] > 100 and all("marked" in s for s in out)


def test_each_leg_of_specials_can_fail_alone():
    f = I.tw_fragment_of(RNE)
    out, n = I.check_specials(f)
    assert out == [] and n == 26
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] ^ 1) if x == sf.inf_bits(FP32) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+inf, -inf': 1 of 2 lanes differ" in out[0]
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0] ^ 1, r[1]) if x == 0 else r)(ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+0, -0'" in out[0]
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == sf.one_bits(FP32) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+1, -1'" in out[0] \
        and "differ or are marked" in out[0]
    out, n = I.check_specials(f, rows=[("one row", [0x3f800000])])
    assert out == [] and n == 1
    # the rows are fp32's own: the gate, the minimum subnormal and 2^p
    labels = [lab for lab, _ in I.special_rows("atan", FP32)]
    assert "gate 2^-13, both signs" in labels
    assert any(lab.startswith("2^24") for lab in labels)


def test_each_leg_of_shape_can_fail_alone():
    builds = {("atan", r): I.tw_build_of(r) for r in RND}
    assert I.check_shape_tw() == []

    def legs(text, tables, n):
        out = I.check_shape(FP32, builds, tables=tables)
        assert len(out) == n and all(text in s and s.startswith("shape: ")
                                     for s in out), (text, out)
    shape = {("atan", "fp32"): [(473, 60, 25)] + [(472, 60, 25)] * 4}
    legs("pinned 473, 60, 25", I.tables_tw(shape=shape), 1)
    legs("instructions by phase differ from the model's",
         I.tables_tw(phases=lambda fn, name: dict(
             I.model_phases_tw(fn, name), z=28)), 5)
    legs("the flag word takes", I.tables_tw(flag_words={
        "atan": I.FLAG_WORDS["atan"] | {0x2}}), 5)
    legs("MIN and", I.tables_tw(min_max={"atan": (2, 0)}), 5)
    legs("MAX instructions", I.tables_tw(min_max={"atan": (1, 1)}), 5)
    legs("the cap is 26", I.tables_tw(caps={
        **ml.INV_LIVE_CAP, "atan": {**ml.INV_LIVE_CAP["atan"], "fp32": 26}}),
         1)
    # a cap one under fails by name; the cap itself holds
    f = ml.fragment("atan", FP32, RNE)
    assert ml.invariants(f, live_cap=25) == []
    assert ml.invariants(f, live_cap=24) == ["25 values live at once, past 24"]
    out = I.check_shape(FP32, builds, tables=I.tables_tw(caps={
        **ml.INV_LIVE_CAP, "atan": {**ml.INV_LIVE_CAP["atan"], "fp32": 24}}))
    assert any("the cap is 24, the most values live under any attribute is "
               "25" in s for s in out)
    assert any("invariants: 25 values live at once, past 24" in s
               for s in out)
    # the reorder leg, on a doctored fragment
    frags = {k: b.fragment() for k, b in builds.items()}
    key = ("atan", RNE)
    out = I.check_shape(FP32, builds, tables=I.tables_tw(),
                        fragments={**frags, key: ml._misnumbered(frags[key])})
    assert any("reorder" in s and "dataflow graph is not the design's" in s
               for s in out)
    out = I.check_shape(FP32, builds, tables=I.tables_tw(),
                        fragments={**frags, key: ml._forward(frags[key])})
    assert any("not a topological order" in s for s in out)
    # the pinned tables are fp32's alone
    with pytest.raises(ValueError, match="no phases of atan at fp64"):
        I.model_phases_tw("atan", "fp64")


def _fresh_with(role=None, delta=1, extra_role=None, rnd=RNE):
    """A fresh (never shared) build of atan at fp32 with the word of `role`
    changed by `delta` in its bits, or with an extra role no derivation asks."""
    b = ml.build("atan", FP32, rnd)
    if role is not None:
        name = b.roles[role][1]
        b.words[name] = (b.words[name] + delta) & ((1 << 32) - 1)
    if extra_role is not None:
        b.const(*extra_role)
    return b


def _constants_of(b):
    lines, findings = ml._check_inv_tw_constants(
        builder=lambda n, f, r: b, attrs=(b.rnd,), names=("atan",))
    return [f"constants: {s}" for s in findings if not s.startswith("seed")]


def test_each_leg_of_constants_can_fail_alone():
    """The build with one word changed, one role at a time: the difference is
    named by fragment and word. Every role the build holds."""
    clean = ml.build("atan", FP32, RNE)
    assert _constants_of(clean) == []
    roles = sorted(clean.roles)
    assert len(roles) == 66
    for role in roles:
        found = _constants_of(_fresh_with(role))
        assert found and all(s.startswith("constants: ") for s in found), role
        assert any(f"atan fp32 rne {role}:" in s for s in found), (role, found)
    # a role no derivation asks, a word where the constant is used up, a word
    # with no role
    found = _constants_of(_fresh_with(extra_role=("EXTRA", 0x1234)))
    assert len(found) == 1 and "derived but not checked: ['EXTRA']" in found[0]
    found = _constants_of(_fresh_with(extra_role=("A_W1_0", 0x3c800000)))
    assert len(found) == 1 and "A_W1_0 is held, but the constant is used up" \
        in found[0]
    b = ml.build("atan", FP32, RNE)
    name = next(iter(b.words))
    b.roles = {r: ref for r, ref in b.roles.items() if ref[1] != name}
    assert any("words the fragment holds with no role" in s
               for s in _constants_of(b))
    # a role the build lacks
    b = ml.build("atan", FP32, RNE)
    del b.roles["A_Y7"]
    assert any("the fragment has no constant A_Y7" in s
               for s in _constants_of(b))
    # the plan and rho, written into the build's meta
    b = ml.build("atan", FP32, RNE)
    b.meta["K3"] = 4
    found = _constants_of(b)
    assert len(found) == 1 and "the plan (K3, K2, D) (4, 3, 8) is not the " \
        "re-derived (3, 3, 8)" in found[0]
    b = ml.build("atan", FP32, RNE)
    b.meta["rho"] = Fraction(1, 15)
    found = _constants_of(b)
    assert len(found) == 1 and "is not the cells' re-derived" in found[0]
    # an enclosure that straddles a rounding boundary decides nothing: refused
    real = ml._check_atan_rational
    mp = pytest.MonkeyPatch()
    try:
        mp.setattr(ml, "_check_atan_rational", lambda a, b, bits: (
            lambda lo_hi: (lo_hi[0], lo_hi[0] + Fraction(1, 2 ** 20)))(
                real(a, b, bits)))
        found = _constants_of(ml.build("atan", FP32, RNE))
    finally:
        mp.undo()
    assert any("T0_1: undecidable: the enclosure of atan(1/8) straddles a "
               "rounding boundary" in s for s in found)
    # the shift moves BREL, and the check reads the build's own
    b = ml.build("atan", FP32, RNE, bound_shift=34)
    assert _constants_of(b) == []
    b.meta["shift"] = 0
    assert any("BREL" in s for s in _constants_of(b))


def test_the_plan_the_seed_and_the_identity_legs_of_constants(monkeypatch):
    # the plan re-derived in another form is the model's, and a coarser rho
    # moves it
    (plan, rho) = ml._check_inv_tw_plan(FP32, 40)
    assert plan == (3, 3, 8) and rho == ml.inv_rho()[0]
    monkeypatch.setattr(ml, "_check_inv_plan",
                        lambda fmt, G: ((0, 0), Fraction(1, 10)))
    assert ml._check_inv_tw_plan(FP32, 40)[0] != (3, 3, 8)
    findings = _constants_of(ml.build("atan", FP32, RNE))
    assert any("the plan (K3, K2, D) (3, 3, 8) is not the re-derived (3, 4, 9)"
               in s for s in findings)
    assert any("rho = " in s and "is not the cells' re-derived" in s
               for s in findings)
    monkeypatch.undo()
    # the seed's premise and the identity
    monkeypatch.setattr(ml, "_check_inv_seed",
                        lambda fmt: (["premise broken"], 0.5))
    lines, findings = ml._check_inv_tw_constants(attrs=(RNE,))
    assert findings == ["seed: premise broken"]
    monkeypatch.undo()
    real = ml._check_atan_rational
    monkeypatch.setattr(ml, "_check_atan_rational", lambda a, b, bits: (
        lambda lo_hi: (lo_hi[0] + 1, lo_hi[1] + 1))(real(a, b, bits)))
    lines, findings = ml._check_inv_tw_constants(attrs=(RNE,))
    assert any("do not overlap" in s for s in findings)
    assert any("T0_" in s for s in findings)


# =====================================================================
# the commands of mathlib_runs.py, and the generator
# =====================================================================

def test_the_inv_commands_take_fp32_for_atan_and_refuse_the_others_by_name(
        tmp_path, capsys):
    import mathlib_runs as R
    R.FINDINGS.clear()
    out = tmp_path / "pools32.txt"
    R.main(["inv-pools", "--fn", "atan", "--formats", "fp32", "--quick",
            "--seq", "--out", str(out)])
    shown = capsys.readouterr().out
    assert "inv-pools atan fp32 rne: 42 lanes, 0 marked" in shown
    assert "472 instructions, 25 live" in shown and "RESULT: ok" in shown
    assert "0 findings" in shown
    R.OUT = None
    R.FINDINGS.clear()
    R.main(["inv-bound", "--fn", "atan", "--formats", "fp32", "--quick"])
    shown = capsys.readouterr().out
    assert "inv-bound atan fp32 rne edge seed 121: 12 lanes" in shown
    assert "a sampled lower bound" in shown and "RESULT: ok" in shown
    R.FINDINGS.clear()
    with pytest.raises(SystemExit, match="fp32 is the triple word"):
        R.main(["inv-pools", "--formats", "fp16", "--fn", "atan"])
    # fp32 is never a default: the sizes are the double word's three, and the
    # box's sample is fp32's own
    import inspect
    src = inspect.getsource(R.cmd_inv_bound)
    assert '"fp32": 20000' in src
    R.OUT = None
    R.FINDINGS.clear()


def test_the_sweep_generator_builds_atan_at_fp32(tmp_path):
    """Runs host/tools/gen_sweep_images.py into tmp_path (rc 0) and checks
    what it wrote: atan's five image files and banks and five EMPTY marks
    files (no lane of atan must mark at fp32: the census); the manifest's
    `digest atan` line equal to the manifest's own rule over the five atan
    images and banks (the first 32 bits of the sha256 of rne to rmm, image
    then bank); the thirteen `digest` lines equal to
    hw/card_stress_lib.py's ROUTINE_DIGESTS row for row, and none skipped. And the
    program of each atan fragment has 477 instructions and 60 words
    (MEASURED: the compiled shape adds QUIET, ENDQUIET, RAISE, the deposit and
    HALT to the body's 472)."""
    import hashlib
    import importlib.util
    import subprocess
    root = pathlib.Path(__file__).resolve().parents[2]
    out = tmp_path / "imgs"
    r = subprocess.run([sys.executable, "-B", str(
        root / "host" / "tools" / "gen_sweep_images.py"), "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    h = hashlib.sha256()
    for x in ("rne", "rtz", "rdn", "rup", "rmm"):
        stem = out / f"atan-fp32-{x}"
        assert stem.with_suffix(".cftp").stat().st_size > 0
        assert stem.with_suffix(".bank").stat().st_size == 4 * 60
        assert stem.with_suffix(".marks").read_bytes() == b""
        h.update(stem.with_suffix(".cftp").read_bytes())
        h.update(stem.with_suffix(".bank").read_bytes())
    manifest = (out / "manifest.txt").read_text(encoding="utf-8").splitlines()
    digests = [ln.split() for ln in manifest if ln.startswith("digest ")]
    assert [d for d in digests if d[1] == "atan"] == [
        ["digest", "atan", h.hexdigest()[:8]]]
    spec = importlib.util.spec_from_file_location(
        "card_stress_lib", root / "hw" / "card_stress_lib.py")
    lib = importlib.util.module_from_spec(spec)
    sys.modules["card_stress_lib"] = lib
    try:
        spec.loader.exec_module(lib)
    finally:
        sys.modules.pop("card_stress_lib", None)
    cat = {d[1]: d[2] for d in digests if d[1] in lib.ROUTINE_DIGESTS}
    assert len(cat) == 13 and cat == dict(lib.ROUTINE_DIGESTS)
    assert all(n in lib.ROUTINE_DIGESTS
               for n in ("atan", "asin", "acos", "atan2"))
    assert not any(ln.startswith("skipped ") for ln in manifest)
    assert sum(1 for ln in manifest if ln.startswith("image atan ")) == 5
    for rnd in RND:
        prog, bank = H.r24_program(I.tw_fragment_of(rnd))
        assert len(prog.insns) == 477 and len(bank) == 60
