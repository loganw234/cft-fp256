# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""pow and powr at fp32, the TRIPLE word (parcel M3F1, M3's build, wave 2), of
python/cft_golden/mathlib.py, the section "fp32: the triple word, pow and powr":
the port of parcel M3X's model (docs/studies/m3/pw32.py), held to it by dag
digest and emitted order (the ten digests below are literals recorded from the
model), and the pools (794 and 823 lanes, the marks 57, 55, 55, 55, 57 and 34,
33, 33, 33, 34), the placed regions, the specials, the structured lanes, seq,
the direct bound, the shape and the registers, and the constants: eight checks
(python/tests/mathlib_pow_harness.py's section for fp32), each shown failing
alone on a doctored input, and nine planted faults (_POW_TW_PLANTS) red where
the table says by measurement, the control green in all. The model is not
imported here; the port against it is the parcel's scratch script.

b1_dropped is NOT a plant: with B1 = 0 the direct error stays under the weakened
Bv (test_b1_dropped_is_a_known_limit below says over what), the first-order
budget alone sees it.
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

import mathlib_pow_harness as P  # noqa: E402

RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = P.RNE, P.RTZ, P.RDN, P.RUP, P.RMM
FNS = P.TW_FUNS
CONFIGS = [(fn, rnd) for fn in FNS for rnd in RND]


def cid(v):
    return v if isinstance(v, str) else sf.RND_NAMES[v]


@functools.lru_cache(maxsize=None)
def results_of(fn, rnd):
    f = P.tw_fragment_of(fn, rnd)
    return tuple(ml.evaluate(f, x) for x in P.pool(fn, FP32))


PROOFS = ["log-truncation", "log-step-7-fits", "log-step-13-fits",
          "log-three-word-steps-first", "exp-truncation", "exp-rho",
          "exp-magic-range", "exp-scale-words-in-range", "ln2-three-words",
          "exp-r-level-3", "inv-ln2-three-words", "log-product-floor"]


# =====================================================================
# the interface, the refusals, the plan
# =====================================================================

def test_fp32_pow_and_powr_are_built_and_the_rest_refused_by_name():
    for fn in FNS:
        for rnd in RND:
            b = ml.build(fn, FP32, rnd)
            assert b.meta["family"] == "triple word"
            f = ml.fragment(fn, FP32, rnd)
            assert (f.op, f.fmt, f.rnd) == (fn, FP32, rnd)
    for name in ("pown", "rootn", "compound"):
        for call in (ml.build, ml.fragment):
            for kw in ({}, {"n": 3}):
                with pytest.raises(ValueError, match=f"{name} at fp32 is not "
                                   f"built: parcel M3F2's"):
                    call(name, FP32, RNE, **kw)
    for fn in FNS:
        with pytest.raises(ValueError, match=f"{fn} takes no integer operand"):
            ml.build(fn, FP32, RNE, n=3)
        with pytest.raises(ValueError, match=f"{fn} takes no integer operand"):
            ml.fragment(fn, FP32, RNE, n=3)
    with pytest.raises(ValueError, match="attribute"):
        ml.build("pow", FP32, 7)
    with pytest.raises(ValueError, match="no_such_plant") as e:
        ml.build("pow", FP32, RNE, plant="no_such_plant")
    assert "l3_dropped" in str(e.value) and "two_sum_all" in str(e.value)
    # the double word's plants are not the triple word's
    with pytest.raises(ValueError, match="exact_unmarked"):
        ml.build("pow", FP32, RNE, plant="exact_unmarked")
    # a guard other than 40, by name
    with pytest.raises(ValueError, match="G = 41: pow and powr at fp32 are "
                       "built at G = 40"):
        ml.build("pow", FP32, RNE, guard=41)
    # the double word's plan and core still refuse fp32, with their words
    with pytest.raises(ValueError, match="triple word, parcel M3F1's"):
        ml.plan_pow(FP32)
    with pytest.raises(ValueError, match="triple word"):
        ml.build_pow_core(FP32)


def test_the_tables_of_the_double_word_are_as_they_were():
    assert ml.POW_FORMATS == (FP64, FP128, FP256) == P.FORMATS
    assert tuple(ml._POW_BUILDERS)[:2] == ("pow", "powr")
    assert set(ml._POW_TW_PLANTS) & set(ml.POW_PLANTS) == {
        "mark_silenced", "y_one_loud", "two_sum_all", "il2h_ulp"}
    assert len(ml.POW_PLANTS) >= 23
    assert "b1_dropped" not in ml._POW_TW_PLANTS
    assert ml.POW_LIVE_CAP["pow"]["fp32"] == 32
    assert ml.POW_LIVE_CAP["powr"]["fp32"] == 29
    assert ml.POW_LIVE_CAP["pow"]["fp64"] == 30
    assert set(ml._POW_TW_BUILDERS) == {"pow", "powr"}


def test_the_plan_is_the_models():
    p = ml._plan_pow_tw()
    assert (p.G, p.GL, p.GE, p.KL, p.KE) == (40, 48, 40, (7, 6, 17),
                                             (3, 4, 9))
    assert (p.B1, p.B2) == (Fraction(1, 2 ** 66), Fraction(1, 2 ** 67))
    assert 48 == 40 + (152 - 1).bit_length() and ml._pow_t_reach(FP32) == 152
    assert p.KL == ml.plan_log32(FP32, 48) and p.KE == ml.plan_exp32(FP32, 40)
    b = P.tw_build_of("pow", RNE)
    m = b.meta
    assert (m["fn"], m["G"], m["GL"], m["GE"], m["KL"], m["KE"], m["B1"],
            m["B2"], m["shift"], m["plant"], m["family"], m["n"]) == (
        "pow", 40, 48, 40, (7, 6, 17), (3, 4, 9), Fraction(1, 2 ** 66),
        Fraction(1, 2 ** 67), 0, None, "triple word", None)
    assert m["proofs"] == PROOFS and m["N"] == 8
    for probe in ("L0 L1 L2 t0 t1 t2 th0 r0 r1 r2 V0 V1 V2 Vh R R1 R2 Bv mk "
                  "ex FIN tinyt nf tq rp kf r").split():
        assert probe in b.probes, probe
    assert b.inputs == ("a", "b")


def test_no_new_phase_every_label_maps_to_a_phase_order_name():
    assert set(ml._POW_TW_PHASE_MAP.values()) <= set(ml.PHASE_ORDER)
    assert set(ml._POW_TW_PHASE_MAP) == set(ml._POW_TW_PARTS)
    for fn in FNS:
        b = P.tw_build_of(fn, RNE)
        assert len(b.label_of) == len(b.body)
        assert set(b.label_of) <= set(ml._POW_TW_PHASE_MAP)
        assert set(b.phase_of) <= set(ml.PHASE_ORDER)


# ---- the static proofs: each fires on a doctored plan ----------------------------

def _doctored(name):
    """(G, GL, plog, pexp, over) in which the proof `name` fails (others may
    fail with it: a doctored plan names each proof it breaks)."""
    G, GL, plog, pexp, over = 40, 48, (7, 6, 17), (3, 4, 9), {}
    if name == "log-truncation":
        plog = (7, 6, 12)
    elif name.startswith("log-step-"):
        GL = 52          # i = 7 and 13 each need more bits than the words hold
    elif name == "log-three-word-steps-first":
        plog = (7, 6, 12)
    elif name == "exp-truncation":
        pexp = (3, 4, 5)
    elif name == "exp-rho":
        over = {"ln2_hi": Fraction(1)}
    elif name == "exp-magic-range":
        over = {"tf": 10 ** 6}
    elif name == "exp-scale-words-in-range":
        over = {"off": 0}
    elif name == "ln2-three-words":
        w = ml._words(FP32, ml._ln2(), 3)
        over = {"ln2": [w[0], w[1], 0]}
    elif name == "exp-r-level-3":
        G = 50
    elif name == "inv-ln2-three-words":
        w = ml._words(FP32, ml._inv_ln2(), 3)
        over = {"iln2": [w[0], w[1], 0]}
    elif name == "log-product-floor":
        GL = 60
    return G, GL, plog, pexp, over


def test_the_twelve_static_proofs_hold_and_each_fires_on_a_doctored_plan():
    assert ml._pow_tw_proofs(40, 48, (7, 6, 17), (3, 4, 9)) == PROOFS
    for name in PROOFS:
        G, GL, plog, pexp, over = _doctored(name)
        with pytest.raises(ValueError, match="static proof '%s' failed"
                           % name) as e:
            ml._pow_tw_proofs(G, GL, plog, pexp, **over)
        assert not isinstance(e.value, AssertionError)
    # a build with a doctored plan does not get as far as a lane
    # (the proofs run in the build; build refuses G != 40 earlier, by name)


# =====================================================================
# the port is the model
# =====================================================================

@pytest.mark.parametrize("fn", FNS)
def test_the_port_is_the_model_by_digest_order_and_part(fn):
    builds = {rnd: P.tw_build_of(fn, rnd) for rnd in RND}
    assert P.check_port_tw(fn, builds) == []
    # the model's words not read by powr: the Build's bank holds one fewer
    # than the model's (the unread SIGN word), the fragment's the same
    for rnd in RND:
        f = builds[rnd].fragment()
        assert len(f.words) == P.SHAPE_TW[(fn, rnd)][1]


def test_each_leg_of_the_port_fails_alone_on_a_doctored_digest():
    builds = {rnd: P.tw_build_of("pow", rnd) for rnd in (RNE,)}
    good = P.DIGESTS_TW[("pow", RNE)]
    for leg in range(3):
        bad = list(good)
        bad[leg] = "0" * 64
        out = P.check_port_tw("pow", builds, {("pow", RNE): tuple(bad)})
        assert len(out) == 1 and out[0].startswith("port: pow fp32 rne")
        assert ("Build's dag digest", "scheduled fragment's dag digest",
                "emitted order")[leg] in out[0]
    parts = dict(P.PARTS_TW[("pow", RNE)])
    P.PARTS_TW[("pow", RNE)]["test"] += 1
    try:
        out = P.check_port_tw("pow", builds)
    finally:
        P.PARTS_TW[("pow", RNE)].clear()
        P.PARTS_TW[("pow", RNE)].update(parts)
    assert len(out) == 1 and "by part" in out[0]


def test_the_scheduler_takes_the_depth_first_order_at_the_models_live():
    for fn in FNS:
        for rnd in RND:
            b = P.tw_build_of(fn, rnd)
            f = b.fragment()
            assert f.live_max() == P.SHAPE_TW[(fn, rnd)][2]
            assert b.fragment(schedule=False).live_max() > f.live_max()


# =====================================================================
# the checks, on the control
# =====================================================================

@pytest.mark.parametrize("fn,rnd", CONFIGS, ids=cid)
def test_pools(fn, rnd):
    f = P.tw_fragment_of(fn, rnd)
    out, t = P.check_pools_tw(f, None, list(results_of(fn, rnd)))
    assert out == [] and t.n == P.POOL_SIZES_TW[fn]
    assert len(t.marked) == P.POOL_MARKS_TW[(fn, rnd)]
    assert t.wrong == [] and t.stray == []
    # the exact cases are marked with the inexact flag set, a marked guess is
    # counted and never a failure: most are wrong (the model: 54 of 57 at rne)
    if (fn, rnd) == ("pow", RNE):
        assert len(t.guess_wrong) == 54 and t.marked_right == 3


@pytest.mark.parametrize("fn,rnd", CONFIGS, ids=cid)
def test_regions(fn, rnd):
    f = P.tw_fragment_of(fn, rnd)
    out, (lanes, marked) = P.check_regions_tw(f, 12)
    assert out == []
    want = 12 * len(P.REGION_NAMES[fn]) + len(P.first_lanes(fn, FP32))
    assert lanes == want
    # the regions powr has no lane of are not in its table at all
    assert ("negint" in P.REGION_NAMES[fn]) == (fn == "pow")


@pytest.mark.parametrize("fn", FNS)
def test_specials(fn):
    frags = {rnd: P.tw_fragment_of(fn, rnd) for rnd in RND}
    out, n = P.check_specials_tw(fn, frags)
    assert out == [] and n > 1000


@pytest.mark.parametrize("fn,rnd", CONFIGS, ids=cid)
def test_structured(fn, rnd):
    out, n = P.check_structured_tw(P.tw_fragment_of(fn, rnd))
    assert out == [] and n > 90


@pytest.mark.parametrize("fn,rnd", [("pow", RNE), ("pow", RTZ), ("pow", RUP),
                                    ("powr", RNE), ("powr", RDN)], ids=cid)
def test_seq(fn, rnd):
    out, lanes = P.check_seq_tw(P.tw_fragment_of(fn, rnd), stride=32)
    assert out == [] and len(lanes) > 100


@pytest.mark.parametrize("fn", FNS)
def test_bound(fn):
    b = P.tw_build_of(fn, RNE)
    out, worst = P.bound_regions_tw(b, 24)
    assert out == []
    nm = dict(P.not_measured_tw(fn, worst))
    # a region that measured nothing is named, and is outside the pass count
    assert nm["hugey"] == 0 if fn == "pow" else True
    if fn == "powr":
        assert nm["negint"] == 0 and nm["negedge"] == 0
        assert "negint" not in worst and "negedge" not in worst
    measured = [r for r, w in worst.items() if w[1] > 0]
    assert len(measured) + len([r for r in nm if r in worst]) == len(worst)
    for r in measured:
        assert worst[r][0] < 0, r      # under 1 Bv (2^x with x < 0)


@pytest.mark.parametrize("fn", FNS)
def test_shape_and_registers(fn):
    assert P.check_shape_tw(fn) == []
    frags = {rnd: P.tw_fragment_of(fn, rnd) for rnd in RND}
    assert P.check_registers_tw(fn, frags) == []
    # routines.program accepts all five; the highest register is the pin
    for f in frags.values():
        prog, _bank = routines.program(f)
        assert P.highest_register(prog) == P.REG_TOP_TW[fn]
    assert P.REG_TOP_TW == {"pow": 31, "powr": 28}
    # the cap is the measured maximum; 30 less the cap is -2 and +1 (M4C)
    caps = {fn_: ml.POW_LIVE_CAP[fn_]["fp32"] for fn_ in FNS}
    assert (30 - caps["pow"], 30 - caps["powr"]) == (-2, 1)
    worst = max(frags.values(), key=lambda f: f.live_max())
    assert ml.invariants(worst) == []
    assert ml.invariants(worst, live_cap=caps[fn] - 1) == [
        f"{caps[fn]} values live at once, past {caps[fn] - 1}"]


def test_constants_in_process_and_as_a_program():
    out, lines = P.check_constants_tw()
    assert out == [] and len(lines) == 2
    assert all("(triple word)" in ln for ln in lines)
    findings, text = P.check_constants_cli_tw()
    assert findings == [] and text[-1] == (
        "mathlib --check (pow, triple word): 2 routines, 1 format, "
        "0 differences")


# =====================================================================
# every leg of every check fails alone on a doctored input
# =====================================================================

def _flip(results, i, bits=0, orwith=0, andnot=0):
    out = list(results)
    b, f = out[i]
    out[i] = (b ^ bits, (f | orwith) & ~andnot)
    return out


def test_each_leg_of_pools_fails_alone():
    f = P.tw_fragment_of("pow", RNE)
    res = list(results_of("pow", RNE))
    mk = next(i for i, (_b, fw) in enumerate(res) if fw & ml.MARK)
    um = next(i for i, (_b, fw) in enumerate(res) if not fw & ml.MARK)
    legs = {
        "unmarked lanes differ": _flip(res, um, bits=1),
        "flag words carry bits": _flip(res, um, orwith=0x40),
        "lanes marked, the model's count": _flip(res, mk, andnot=ml.MARK),
        "lanes, the model's pool has": res[:-1],
    }
    for text, doctored in legs.items():
        out = P.check_pools_tw(f, None, doctored)[0]
        assert len(out) >= 1 and all(o.startswith("pools: pow fp32 rne")
                                     for o in out), text
        assert any(text in o for o in out), (text, out)
    # the table's own pins: doctoring a pin shows the count leg alone
    old = P.POOL_MARKS_TW[("pow", RNE)]
    P.POOL_MARKS_TW[("pow", RNE)] = old + 1
    try:
        out = P.check_pools_tw(f, None, res)[0]
    finally:
        P.POOL_MARKS_TW[("pow", RNE)] = old
    assert len(out) == 1 and "the model's count is 58" in out[0]


def test_each_leg_of_regions_fails_alone():
    f = P.tw_fragment_of("pow", RNE)
    regs = {"wide": P.regions_tw("pow", 4)["wide"]}
    bad = lambda f_, x: _doctor_eval(f_, x)          # noqa: E731
    out = P.check_regions_tw(f, regions=regs, first=[], evaluator=bad)[0]
    assert len(out) == 1 and out[0].startswith("regions: pow fp32 rne wide")
    first = [("pow(1.2, minSub)", P.first_lanes("pow", FP32)[0][1])]
    out = P.check_regions_tw(f, regions={}, first=first, evaluator=bad)[0]
    assert len(out) == 1 and "the first design's lane" in out[0]


def _doctor_eval(f, x):
    bits, fw = ml.evaluate(f, x)
    return bits ^ 1, fw & ~ml.MARK


def test_each_leg_of_specials_fails_alone():
    f = P.tw_fragment_of("pow", RNE)
    frags = {RNE: f}
    out = P.check_specials_tw("pow", frags, evaluator=_doctor_eval)[0]
    assert out and all(o.startswith("specials: pow fp32") for o in out)
    five = {rnd: P.tw_fragment_of("pow", rnd) for rnd in RND}
    marks = {k: dict(v) for k, v in P.SPECIAL_MARKS_TW.items()}
    marks["pow"]["subnormal operands"] += 1
    out = P.check_specials_tw("pow", five, marks=marks["pow"])[0]
    assert len(out) == 1 and "marks over the five attributes" in out[0] \
        and "subnormal operands" in out[0]


def test_each_leg_of_structured_fails_alone():
    f = P.tw_fragment_of("pow", RNE)
    lane = (P._V(FP32, 0, 3, 0), P._V(FP32, 0, 2, 0))
    one = P.sf.one_bits(FP32)
    rows = [("decided but marked", [lane], "decided"),
            ("marked but not", [lane], "marked"),
            ("wrong and unmarked", [(lane[0], one)], "free")]

    def ev(f_, x):
        if x == lane and rows_state[0] == "decided":
            return 0x40100000, 0x90
        if x == lane and rows_state[0] == "marked":
            return 0x41100000, 0x10
        return 0x1, 0x0
    for i, (label, lanes, _e) in enumerate(rows):
        rows_state = [rows[i][2]]
        out = P.check_structured_tw(f, ev, [rows[i]])[0]
        assert len(out) == 1 and out[0].startswith("structured: pow fp32 rne")
        assert label in out[0]
    # the midpoint expectation is not in fp32's rows (u^2 > the bound)
    assert all(e != "midpoint" for _l, _x, e in P.structured_rows_tw("pow"))


def test_each_leg_of_seq_fails_alone():
    f = P.tw_fragment_of("pow", RNE)
    xs = list(P.seq_lanes_tw("pow", 200))
    rows = P.structured_rows_tw("pow")
    assert P.check_seq_tw(f, xs=xs)[0] == []
    out = P.check_seq_tw(f, xs=xs, evaluator=_doctor_eval)[0]
    assert any("seq.py and evaluate() differ" in o for o in out)
    out = P.check_seq_tw(f, xs=xs, loud=True)[0]
    assert out and all(o.startswith("seq: pow fp32 rne") for o in out)

    def post(res):
        res.status = res.status | 0     # STATUS[6] flipped below
        res.flags = res.flags ^ 0x10
        return res
    out = P.check_seq_tw(f, xs=xs, post=post)[0]
    assert any("FLAGS" in o for o in out)
    del rows


def test_each_leg_of_bound_fails_alone():
    b = P.tw_build_of("pow", RNE)
    lanes = P.region(FP32, "pow", "wide", 4, 1)
    assert P.check_bound_tw(b, lanes, "wide")[0] == []
    # past the bound: a build whose bound is 2^-30 too small
    bad = P.tw_build_of("pow", RNE, None, 0)
    shrunk = ml.build("pow", FP32, RNE, plant="l3_dropped")
    out = P.check_bound_tw(shrunk, lanes, "wide")[0]
    assert any("past the bound" in o for o in out)
    # no main-path lane: a finding, but not for hugey; none at all: NOT MEASURED
    special = [(sf.inf_bits(FP32), P._V(FP32, 0, 3, 0))]
    out = P.check_bound_tw(bad, special, "wide")[0]
    assert any("measures nothing" in o for o in out)
    assert P.check_bound_tw(bad, special, "hugey")[0] == []
    # an unmarked lane that differs from transcend.py
    orig = P.golden
    try:
        P.golden = lambda fmt, rnd, lane, fn: (0, 0)
        out = P.check_bound_tw(bad, lanes[:2], "wide")[0]
    finally:
        P.golden = orig
    assert any("differ from transcend.pow" in o for o in out)
    # the powr regions with no lane: counted at 0, outside the pass count
    assert dict(P.not_measured_tw("powr", {})) == {"negint": 0, "negedge": 0}


def test_each_leg_of_shape_fails_alone():
    builds = {rnd: P.tw_build_of("pow", rnd) for rnd in RND}
    assert P.check_shape_tw("pow", builds) == []
    pins = dict(P.SHAPE_TW)
    t = P.tables_tw()
    t.shape[("pow", "fp32")][0] = (926, 143, 32)
    out = P.check_shape_tw("pow", builds, t)
    assert len(out) == 1 and "pinned 926" in out[0]
    t = P.tables_tw(eft={("pow", "fp32"): (60, 42)})
    assert any("Fast2Sums" in o for o in P.check_shape_tw("pow", builds, t))
    t = P.tables_tw(phases=lambda fn, nm, rnd: dict(P.PHASES_TW[(fn, RTZ)]))
    assert any("by phase" in o for o in P.check_shape_tw("pow", builds, t))
    t = P.tables_tw(flag_words={"pow": frozenset({0, 1})})
    assert any("flag word takes" in o for o in P.check_shape_tw("pow", builds,
                                                                t))
    t = P.tables_tw(min_max={"pow": (1, 0)})
    assert any("MIN" in o for o in P.check_shape_tw("pow", builds, t))
    t = P.tables_tw(caps={"pow": {"fp32": 31}})
    assert any("the cap is 31" in o for o in P.check_shape_tw("pow", builds, t))
    # registers: the pin, the acceptance, the cap row
    frags = {rnd: b.fragment() for rnd, b in builds.items()}
    out = P.check_registers_tw("pow", frags, top=30)
    assert len(out) == 5 and all("highest register is r31" in o for o in out)
    old = ml.POW_LIVE_CAP["pow"]["fp32"]
    ml.POW_LIVE_CAP["pow"]["fp32"] = 31
    try:
        out = P.check_registers_tw("pow", frags)
    finally:
        ml.POW_LIVE_CAP["pow"]["fp32"] = old
    assert len(out) == 1 and "POW_LIVE_CAP is 31" in out[0]
    assert pins == P.SHAPE_TW


def test_each_leg_of_constants_fails_alone():
    def doctor(name, fn_):
        def builder(n, fmt, rnd):
            b = ml.build(n, fmt, rnd)
            fn_(b)
            return b
        return builder
    legs = {
        "IL2_0": lambda b: b.words.__setitem__(b.roles["IL2_0"][1],
                                               b.words[b.roles["IL2_0"][1]]
                                               + 1),
        "LN2_2": lambda b: b.words.__setitem__(b.roles["LN2_2"][1], 0)
        if b.words[b.roles["LN2_2"][1]] else None,
        "EB0_1": lambda b: b.words.__setitem__(b.roles["EB0_1"][1],
                                               b.words[b.roles["EB0_1"][1]]
                                               ^ 1),
        "LB0_2": lambda b: b.words.__setitem__(b.roles["LB0_2"][1],
                                               b.words[b.roles["LB0_2"][1]]
                                               ^ 1),
        "T3_0": lambda b: b.words.__setitem__(b.roles["T3_0"][1],
                                              b.words[b.roles["T3_0"][1]] + 1),
        "L3_1": lambda b: b.words.__setitem__(b.roles["L3_1"][1],
                                              b.words[b.roles["L3_1"][1]] + 1),
        "B2": lambda b: b.words.__setitem__(b.roles["B2"][1],
                                            b.words[b.roles["B2"][1]] - 1),
        "TOVF": lambda b: b.words.__setitem__(b.roles["TOVF"][1],
                                              b.words[b.roles["TOVF"][1]] + 1),
        "BREL": lambda b: b.words.__setitem__(b.roles["BREL"][1],
                                              b.words[b.roles["BREL"][1]] + 1),
    }
    for role, fn_ in legs.items():
        out, _ = P.check_constants_tw(builder=doctor(role, fn_), attrs=(RNE,),
                                      names=("pow",))
        assert out and all(o.startswith("constants: pow fp32 rne") for o in
                           out), role
        assert any(role in o for o in out), (role, out)
    # a plan drift, a role with no check, a word with no role
    def plan(b):
        b.meta["GL"] = 47
    out, _ = P.check_constants_tw(builder=doctor("plan", plan), attrs=(RNE,),
                                  names=("pow",))
    assert any("re-derived" in o for o in out)

    def stray(b):
        b.const("STRAY_ROLE", 0x12345)
    out, _ = P.check_constants_tw(builder=doctor("stray", stray),
                                  attrs=(RNE,), names=("pow",))
    assert any("derived but not checked" in o and "STRAY_ROLE" in o
               for o in out)

    def proofs(b):
        b.meta["proofs"] = b.meta["proofs"][:-1]
    out, _ = P.check_constants_tw(builder=doctor("proofs", proofs),
                                  attrs=(RNE,), names=("pow",))
    assert any("static proofs that held" in o for o in out)

    def scale(b):
        r = b.roles["K_SUBMIN"][1]
        b.words[r] += 1
    out, _ = P.check_constants_tw(builder=doctor("scale", scale),
                                  attrs=(RNE,), names=("pow",))
    assert any("K_SUBMIN" in o for o in out)


# =====================================================================
# the plants
# =====================================================================

# (plant, fn, the checks it is red in at red_checks_tw's scope, pool_step):
# MEASURED by this table's own test (each row's other checks are green). The
# regions are green for every plant but il2h_ulp at six lanes a region (they
# are the pools' sibling and see a fault only where it moves an unmarked lane);
# shape is red for every plant that changes an instruction count or a word, as
# a pinned count does. mark_silenced and y_one_loud are green in bound (the
# bound reads V and the answers of lanes, not the mark; y = 1 is not a main-path
# lane); v2_dropped is red in pools only by its COUNT of marks (63 against 57),
# so its row runs the whole pool.
PLANTED = [
    ("l3_dropped", "pow", {"pools", "specials", "structured", "seq", "bound",
                           "shape"}, 2),
    ("mark_silenced", "pow", {"pools", "specials", "structured", "seq",
                              "shape"}, 2),
    ("v2_dropped", "pow", {"pools", "bound", "shape"}, 1),
    ("lv2_dropped", "pow", {"pools", "specials", "structured", "seq", "bound",
                            "shape"}, 2),
    ("r2_dropped", "pow", {"pools", "specials", "structured", "seq", "bound",
                           "shape"}, 2),
    ("il2h_ulp", "pow", {"pools", "regions", "specials", "structured", "seq",
                         "bound", "shape", "constants"}, 2),
    ("y_one_loud", "pow", {"pools", "specials", "structured", "seq", "shape"},
     2),
    ("two_sum_all", "pow", {"shape"}, 2),
]


@functools.lru_cache(maxsize=None)
def red_of(plant, fn="pow", pool_step=2):
    return P.red_checks_tw(plant, fn, pool_step=pool_step)


def test_the_control_is_green_in_every_check():
    red = P.red_checks_tw(None, "pow", pool_step=1)
    assert set(red) == set(P.CHECKS_TW)
    assert {k: v for k, v in red.items() if v} == {}
    red = P.red_checks_tw(None, "powr")
    assert {k: v for k, v in red.items() if v} == {}


@pytest.mark.parametrize("row", PLANTED, ids=lambda r: r[0])
def test_each_plant_is_red_where_the_table_says_and_green_elsewhere(row):
    plant, fn, want, step = row
    red = red_of(plant, fn, step)
    assert set(red) == set(P.CHECKS_TW)          # a row lists every check
    assert {k for k, v in red.items() if v} == want
    for name, found in red.items():
        assert all(s.startswith(name + ":") for s in found), (name, found[:1])


def test_every_check_has_a_plant_red_in_it_and_the_rows_list_every_check():
    seen = set()
    for plant, fn, want, step in PLANTED:
        seen |= want
        red = red_of(plant, fn, step)
        assert set(red) == set(P.CHECKS_TW)
    assert seen == set(P.CHECKS_TW)
    # a doctored row that omits a check is refused by the same assertion
    row = dict(red_of("two_sum_all"))
    del row["bound"]
    assert set(row) != set(P.CHECKS_TW)


def test_the_plants_not_in_the_table_are_ln2_ulp_and_the_table_is_all_of_it():
    # ln2_ulp is in _POW_TW_PLANTS and red in constants (measured below); the
    # table above has eight rows, its ninth is this one
    red = red_of("ln2_ulp")
    assert red["constants"] and red["bound"] and red["pools"]
    assert {r[0] for r in PLANTED} | {"ln2_ulp"} == set(ml._POW_TW_PLANTS)


def test_the_plants_are_refused_by_name_where_they_cannot_act(monkeypatch):
    # a plant that never reaches its fault: the check refuses it by name
    b0 = P.tw_build_of("powr", RNE)
    with pytest.raises(ValueError, match="plant 'mark_silenced' does not "
                       "apply to powr at fp32"):
        monkeypatch.setattr(ml, "_act", lambda b, name: False)
        ml.build("powr", FP32, RNE, plant="mark_silenced")
    del b0


def test_every_plant_changes_the_build():
    for plant in ml._POW_TW_PLANTS:
        base = P.tw_build_of("pow", RNE)
        b = P.tw_build_of("pow", RNE, plant)
        assert (ml.dag_digest(b.fragment(schedule=False))
                != ml.dag_digest(base.fragment(schedule=False))), plant


def test_b1_dropped_is_a_known_limit_the_direct_bound_does_not_see(
        monkeypatch):
    """The model's measurement: b1_dropped is not red in the brief's region
    `edge` and is red in `near1` in the first-order budget, which this build
    does not port. Here, with B1 = 0 (B1's term out of Bv), the direct error
    stays under the WEAKENED Bv over 300 lanes of near1 and of edge (MEASURED
    by the parcel: 2^-1.36 and 2^-3.69 of the weakened bound; 2,000 lanes of
    near1 and of zone, 1,500 of edge: 2^-0.86, 2^-0.71, 2^-2.44), so the plant
    is not added to _POW_TW_PLANTS (the budget alone sees it, as the double
    word's zone_bound_off)."""
    monkeypatch.setitem(ml._POW_TW_PLANTS, "b1_dropped", "B1 = 0")
    b = ml.build("pow", FP32, RNE, plant="b1_dropped")
    assert "B1" not in b.roles and "B1" in P.tw_build_of("pow", RNE).roles
    for region in ("near1", "edge"):
        lanes = P.region(FP32, "pow", region, 60, 31)
        out, (worst, main, _n) = P.check_bound_tw(b, lanes, region)
        assert out == [] and main > 40 and worst < 0, region


# =====================================================================
# the commands
# =====================================================================

def test_the_pow_commands_run_at_fp32_and_say_what_is_not_measured(
        tmp_path, capsys):
    import mathlib_runs as R
    R.FINDINGS.clear()
    R.OUT = None
    R.main(["pow-pools", "--quick", "--formats", "fp32", "--out",
            str(tmp_path / "p.txt")])
    shown = capsys.readouterr().out
    assert "pow-pools pow fp32 rne:" in shown and "RESULT: ok" in shown
    assert "pow-regions powr fp32 rtz seed 1: 10 regions, 120 lanes" in shown
    R.FINDINGS.clear()
    R.OUT = None
    R.main(["pow-bound", "--quick", "--formats", "fp32", "--out",
            str(tmp_path / "b.txt")])
    shown = capsys.readouterr().out
    assert "pow-bound powr fp32 negint: NOT MEASURED (0 lanes" in shown
    assert "pow-bound powr fp32 negedge: NOT MEASURED (0 lanes" in shown
    assert "pow-bound pow fp32 rne hugey seed 129: NOT MEASURED" in shown
    assert "21 regions measured (the pass count), 4 NOT MEASURED" in shown \
        or "regions measured (the pass count)" in shown
    assert "RESULT: ok" in shown
    R.FINDINGS.clear()
    R.OUT = None
    with pytest.raises(SystemExit, match="parcel M3F2's"):
        R._pow_formats("fp32", [], ["pow", "pown"])
    with pytest.raises(SystemExit, match="fp64, fp128 or fp256"):
        R._pow_formats("fp16", [], ["pow"])
