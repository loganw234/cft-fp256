"""pown and rootn at fp32, the triple word (parcel M3F2): the golden
generator's build of mathlib.py's section "fp32: pown and rootn on the triple
word", held to the model (docs/studies/m3/pw32n.py, parcel M3XN: its pins are
the harness's literals, never imported here) by dag digest and instruction
counts, the registers (pown 28 live and r27, rootn 27 and r26), the pools, the
regions, the specials, the structured lanes, seq.py's compiled shape, the
direct error |V - f| / Bv, the constants of the integer operand, and the
plants: every plant red in a named check, every check red for some plant.

compound is NOT built at fp32 (parcel M3F2's split): its refusal is held here
by name, and the tests that say so read the table, so a later parcel that
builds it fails them by name.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, routines  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_pow_harness as P  # noqa: E402
import mathlib_runs as R  # noqa: E402

RNE, RTZ = sf.RND_RNE, sf.RND_RTZ
MODES = sf.RND_MODES
FNS = P.TW_N_FUNS
THREE_WORDS = 2 ** 62 + 2 ** 37 + 1


def all_n():
    return [(fn, n) for fn in FNS for n in P.TW_N_NS[fn]]


# ---- the tables, as they were -----------------------------------------------

def test_the_tables_other_parcels_read_are_what_they_were():
    """D1 and D2: POW_FORMATS stays the double word's three, _POW_TW_BUILDERS
    and _POW_TW_PLANTS stay pow's and powr's (nine plants), pown and rootn have
    tables of their own, and routines.LIVE_CAP names pown 28 and rootn 27 at
    fp32 and compound none."""
    assert ml.POW_FORMATS == (FP64, FP128, FP256)
    assert tuple(ml._POW_TW_BUILDERS) == ("pow", "powr")
    assert tuple(ml._POW_TW_N_BUILDERS) == ("pown", "rootn")
    assert len(ml._POW_TW_PLANTS) == 9
    assert not set(ml._POW_TW_N_PLANTS) & set(ml._POW_TW_PLANTS) \
        or set(ml._POW_TW_N_PLANTS) <= set(ml.POW_PLANTS)
    assert set(ml._POW_TW_N_PLANTS) == {"n_word_ulp", "n_low_dropped",
                                        "n_word3_dropped", "n_row_loud",
                                        "rootn_m0_neg"}
    assert all(isinstance(t, str) and len(t) > 20
               for t in ml._POW_TW_N_PLANTS.values())
    assert ml.POW_LIVE_CAP["pown"]["fp32"] == 28
    assert ml.POW_LIVE_CAP["rootn"]["fp32"] == 27
    assert routines.LIVE_CAP["pown"]["fp32"] == 28
    assert "fp32" not in routines.LIVE_CAP["compound"]
    assert ml.POW_LIVE_CAP["pow"]["fp32"] == 32
    assert ml.POW_LIVE_CAP["powr"]["fp32"] == 29


# ---- routing and the refusals ---------------------------------------------------

@pytest.mark.parametrize("kw", ({}, {"n": 3}, {"n": 1000}, {"n": 0},
                                {"n": 1}))
def test_compound_at_fp32_is_refused_by_name_whatever_n(kw):
    """compound is not built at fp32: build and fragment refuse it with the
    words 'compound at fp32 is not built:' (the sweep generator's skip reads
    'is not built'), under every attribute. This test names compound, so it
    fails by name when a later parcel builds it."""
    assert "compound" not in ml._POW_TW_N_BUILDERS
    for call in (ml.build, ml.fragment):
        for rnd in MODES:
            with pytest.raises(ValueError,
                               match="compound at fp32 is not built:"):
                call("compound", FP32, rnd, **kw)
    assert "fp32" not in ml.POW_LIVE_CAP["compound"]
    with pytest.raises(ValueError, match="compound at fp32 is not built:"):
        routines.fragment("compound", FP32, RNE, 3)


def test_a_name_in_neither_table_is_refused_by_name(monkeypatch):
    """Taking pown out of the table of the integer operand's builders (and its
    fragment out of the cache) sends it to the refusal of a name in neither
    table: held as test_mathlib_inv.py:196 holds the double word's."""
    monkeypatch.setattr(ml, "_POW_TW_N_BUILDERS", {"rootn": ml._build_rootn_tw})
    monkeypatch.setattr(ml, "_CACHE", {})
    for call in (ml.build, ml.fragment):
        with pytest.raises(ValueError, match="pown at fp32 is not built"):
            call("pown", FP32, RNE, n=3)
    assert ml.build("rootn", FP32, RNE, n=3).meta["family"] == "triple word"


def test_pown_and_rootn_build_as_the_triple_word_and_their_n_is_checked():
    for fn in FNS:
        b = ml.build(fn, FP32, RNE, n=3)
        assert b.meta["family"] == "triple word" and b.meta["n"] == 3
        assert b.inputs == ("a",)
        f = ml.fragment(fn, FP32, RNE, 3)
        assert (f.op, f.fmt, f.rnd, f.inputs) == (fn, FP32, RNE, ("a",))
        assert f is ml.fragment(fn, FP32, RNE, 3)
        assert f is not ml.fragment(fn, FP32, RNE, 5)
        assert routines.fragment(fn, FP32, RNE, 3) is f
        with pytest.raises(ValueError, match="needs its integer operand"):
            ml.build(fn, FP32, RNE)
        for bad in (True, 1.0, "3", 2 ** 63, -2 ** 63 - 1):
            with pytest.raises(ValueError):
                ml.fragment(fn, FP32, RNE, bad)
            with pytest.raises(ValueError):
                ml.build(fn, FP32, RNE, n=bad)
        with pytest.raises(ValueError, match="attribute"):
            ml.build(fn, FP32, 7, n=3)
    with pytest.raises(ValueError, match="rootn.x, 0. is invalid"):
        ml.fragment("rootn", FP32, RNE, 0)
    for fn in ("pow", "powr"):
        with pytest.raises(ValueError, match="takes no integer operand"):
            ml.build(fn, FP32, RNE, n=3)
    # the small fragments are the double word's own builder, at fp32
    for fn, n in (("pown", 0), ("pown", 1), ("rootn", 1)):
        b = ml.build(fn, FP32, RNE, n=n)
        assert b.meta["family"] == "small", (fn, n)
        assert len(ml.fragment(fn, FP32, RNE, n)) == 6, (fn, n)
        with pytest.raises(ValueError, match="small fragment has no core"):
            ml.build(fn, FP32, RNE, n=n, plant="n_row_loud")


@pytest.mark.parametrize("key", [k for k in ml._POW_TW_PLANTS
                                 if k not in ml._POW_TW_N_SHARED_PLANTS])
def test_the_seven_plants_of_pow_are_refused_at_pown_and_rootn_by_name(key):
    for fn in FNS:
        with pytest.raises(ValueError, match=f"plant '{key}' does not apply "
                           f"to {fn} at fp32: the fault is not reached"):
            ml.build(fn, FP32, RNE, n=3, plant=key)


def test_plants_the_build_cannot_reach_are_refused_by_name():
    with pytest.raises(ValueError, match="unknown plant"):
        ml.build("pown", FP32, RNE, n=3, plant="no_such_plant")
    with pytest.raises(ValueError, match="n has one word"):
        ml.build("pown", FP32, RNE, n=3, plant="n_low_dropped")
    with pytest.raises(ValueError, match="does not apply to rootn"):
        ml.build("rootn", FP32, RNE, n=3, plant="n_low_dropped")
    with pytest.raises(ValueError, match="pown has no lane at a three-word n"):
        ml.build("pown", FP32, RNE, n=THREE_WORDS, plant="n_word3_dropped")
    with pytest.raises(ValueError, match="1/n has 1 words"):
        ml.build("rootn", FP32, RNE, n=2 ** 40, plant="n_word3_dropped")
    with pytest.raises(ValueError, match="rootn at an even n only"):
        ml.build("rootn", FP32, RNE, n=3, plant="rootn_m0_neg")
    with pytest.raises(ValueError, match="rootn at an even n only"):
        ml.build("pown", FP32, RNE, n=2, plant="rootn_m0_neg")
    with pytest.raises(ValueError, match="G = 40"):
        ml.build("pown", FP32, RNE, n=3, guard=50)


# ---- the words of n, and the static proofs --------------------------------------------

def test_the_words_of_n():
    w = ml._pow_tw_y_words
    assert [len(w("pown", n)) for n in (3, -2, 2 ** 24, 2 ** 24 + 1, 2 ** 40,
                                        2 ** 48 + 1, THREE_WORDS)] == \
        [1, 1, 1, 2, 1, 2, 3]
    assert [len(w("rootn", n)) for n in (3, -3, 17, 1000, 2 ** 40, 2)] == \
        [3, 3, 3, 3, 1, 1]
    for n in (3, 2 ** 24 + 1, THREE_WORDS, -2 ** 63, 2 ** 63 - 1):
        assert sum(ml._dec(FP32, x) for x in w("pown", n)) == n
    assert P.TW_N_NS["pown"].count(THREE_WORDS) == 1
    assert THREE_WORDS not in P.TW_N_NS["rootn"]


def _held(fn, n, ws=None, **over):
    P_ = ml._plan_pow_tw()
    ws = ml._pow_tw_y_words(fn, n) if ws is None else ws
    return ml._pow_tw_n_proofs(fn, n, P_.G, P_.GL, P_.KL, P_.KE, ws, **over)


def test_the_five_static_proofs_of_n_each_fire_on_a_doctored_input():
    assert len(_held("pown", 3)) == 17 and len(_held("rootn", 3)) == 17
    assert _held("pown", 3)[-1] == "n-words-exact"
    assert _held("rootn", 3)[-1] == "rootn-1/n-words"
    ws3 = ml._pow_tw_y_words("pown", THREE_WORDS)
    cases = [
        ("n-int64", lambda: _held("pown", 2 ** 63)),
        ("n-not-0-1", lambda: _held("pown", 1)),
        ("words-at-most-3", lambda: _held("pown", THREE_WORDS, ws3 + ws3[:1])),
        ("n-words-exact", lambda: _held("pown", THREE_WORDS, ws3[:2])),
        ("rootn-1/n-words", lambda: _held(
            "rootn", 3, ml._pow_tw_y_words("rootn", 3, words=2))),
    ]
    for name, call in cases:
        with pytest.raises(ValueError,
                           match=f"static proof '{name}' failed"):
            call()
    # the proof of the product's floor, on a plan whose GL is past it
    P_ = ml._plan_pow_tw()
    with pytest.raises(ValueError,
                       match="static proof 'product-floor-3-words' failed"):
        ml._pow_tw_n_proofs("pown", 3, P_.G, 49, P_.KL, P_.KE,
                            ml._pow_tw_y_words("pown", 3))
    # a truncation the plant makes leaves the last proof out and no other
    assert len(_held("pown", 3, truncated=True)) == 16


# ---- the port: the model's pins, the registers -----------------------------------------

@pytest.mark.parametrize("fn,n", all_n(), ids=lambda v: str(v))
def test_shape_registers_and_port_equal_the_models_pins(fn, n):
    """check_shape_tw_n: per attribute the instructions, bank words, live
    values, dag digest and instructions by phase (the model's literals), the
    Fast2Sum and TwoSum counts, the flag words, no MIN or MAX, the reordered
    design, the invariants under the cap; the highest register; and the Build's
    dag digest, the scheduled fragment's and its emitted order (the model's)."""
    assert P.check_shape_tw_n(fn, n) == []


def test_registers_and_caps_over_the_list_and_n_5_and_2_35_plus_7():
    """The cap of each function is the MAXIMUM over n: pown keeps 28 live at
    every odd n of the list and 27 at the even, rootn 27 and 26, so 28 and 27
    are reached; the highest registers are r27 and r26. n = 5 and 2^35 + 7 (odd,
    as VM3XN showed) give the same."""
    for fn, top, cap in (("pown", 27, 28), ("rootn", 26, 27)):
        assert ml.POW_LIVE_CAP[fn]["fp32"] == cap
        assert P.check_caps_tw_n(fn) == []
        for n in (5, 2 ** 35 + 7):
            frags = {rnd: P.tw_n_fragment_of(fn, rnd, n) for rnd in MODES}
            assert max(f.live_max() for f in frags.values()) == cap
            tops = {highest(f) for f in frags.values()}
            assert max(tops) == top, (fn, n, tops)
        even = max(P.tw_n_fragment_of(fn, rnd, 2).live_max() for rnd in MODES)
        assert even == cap - 1
        # a cap one under fails, by name
        f = max((P.tw_n_fragment_of(fn, rnd, 3) for rnd in MODES),
                key=lambda f: f.live_max())
        assert ml.invariants(f, live_cap=cap - 1) == [
            f"{cap} values live at once, past {cap - 1}"]
    # the caller's room, the model's figure: 30 less the cap
    assert [30 - ml.POW_LIVE_CAP[fn]["fp32"] for fn in FNS] == [2, 3]


def highest(f):
    prog, _bank = routines.program(f)
    return P.highest_register(prog)


def test_a_doctored_pin_fails_by_name_in_each_leg_of_shape_and_port():
    """Each leg of the shape check fails alone on a doctored input (the real
    assertion run on it): the instruction count, the dag digest, the Fast2Sum
    count, the register's top, the model's digest of the Build, the flag
    word."""
    key = ("pown", "fp32", "rne", 3)
    pins = dict(P.PINS_TW_N)
    pins[key] = (pins[key][0] + 1,) + pins[key][1:]
    out = P.check_shape_n("pown", FP32, 3, (RNE,), pins=pins,
                          eft=P.EFT_TW_N)
    assert len(out) == 1 and "instructions" in out[0]
    pins = dict(P.PINS_TW_N)
    pins[key] = pins[key][:3] + ("0" * 32,) + pins[key][4:]
    out = P.check_shape_n("pown", FP32, 3, (RNE,), pins=pins,
                          eft=P.EFT_TW_N)
    assert len(out) == 1 and "dag digest" in out[0]
    eft = dict(P.EFT_TW_N)
    eft[("pown", "fp32", 3)] = (0, 0)
    out = P.check_shape_n("pown", FP32, 3, (RNE,), pins=P.PINS_TW_N, eft=eft)
    assert len(out) == 1 and "Fast2Sums" in out[0]
    tops = dict(P.REG_TOP_TW_N)
    tops[("pown", 3, "rne")] -= 1
    frags = {RNE: P.tw_n_fragment_of("pown", RNE, 3)}
    out = P.check_registers_tw_n("pown", 3, frags, tops)
    assert len(out) == 1 and "highest register" in out[0]
    digests = dict(P.DIGESTS_TW_N)
    d = list(digests[("rootn", 3, "rne")])
    d[0] = "0" * 64
    digests[("rootn", 3, "rne")] = tuple(d)
    out = P.check_port_tw_n("rootn", 3, {RNE: P.tw_n_build_of("rootn", RNE, 3)},
                            digests)
    assert len(out) == 1 and "the Build's dag digest" in out[0]
    caps = {k: dict(v) for k, v in ml.POW_LIVE_CAP.items()}
    caps["pown"]["fp32"] = 27
    out = P.check_caps_tw_n("pown", caps=caps)
    assert out and all("the cap is 27" in s for s in out[:1])


# ---- the lanes: pools, regions, specials, structured, seq ---------------------------------

LANE_NS = (3, -3, 2, 17, 2 ** 31 - 1, -2 ** 63, 1000, 2 ** 24 + 1, 2 ** 40)


@pytest.mark.parametrize("fn", FNS)
def test_pools_regions_specials_structured_and_seq_are_green(fn):
    """0 wrong unmarked lanes, the model's marks (the pins are the model's), at
    several n and attributes. The pools' pinned marks are read where the pool
    has lanes of n (n = 2^31 - 1 and up: none, a named limit)."""
    for n in LANE_NS:
        for rnd in (RNE, RTZ):
            out, t = P.check_pools_tw_n(fn, rnd, n)
            assert out == [], out
            assert len(t.wrong) == 0
        assert P.check_specials_tw_n(fn, n)[0] == []
        assert P.check_structured_tw_n(fn, RNE, n)[0] == []
    for n in (3, 2, 1000):
        assert P.check_seq_tw_n(fn, RNE, n)[0] == []
    assert P.check_seq_tw_n(fn, RTZ, 3)[0] == []
    # the pools with no lane of n: the check measures nothing there, said
    assert P.tw_n_pool_lanes(fn, 3) > 0
    assert [P.tw_n_pool_lanes(fn, n) for n in (2 ** 40, 2 ** 48 + 1)] == [0, 0]
    for name in P.REGION_NAMES_TW_N:
        out, (lanes, marked, main) = P.check_regions_tw_n(fn, RNE, name, 8)
        assert out == [], (fn, name, out)


def test_the_models_marks_are_pinned_not_read_from_the_code_under_test():
    """The pins' keys cover every n and attribute of the lists; a lane's pool
    mark count of the model at n = 3 is non-zero (the check can fail)."""
    for fn, n in all_n():
        if n in (0, 1):
            continue
        assert (fn, "fp32", n) in P.POOL_MARKS_TW_N
        assert (fn, "fp32", n) in P.SPECIAL_MARKS_TW_N
    assert P.POOL_MARKS_TW_N[("pown", "fp32", 3)]["rne"] == 15
    assert sum(P.SPECIAL_MARKS_TW_N[("pown", "fp32", 3)]) == 10


# ---- the direct error, and the regions that measure nothing ---------------------------------

def test_the_bound_over_the_regions_and_the_regions_that_measure_nothing():
    """|V - f| / Bv under 1 over the placed regions at 6 points a region, seed
    11, under rne (a sampled lower bound: never the budget's, whose regions
    are the box's). pown's int31 (n = 2^31 - 1), int63 (-2^63), int2^40 and
    int2^48 + 1 have no main-path lane at all and are NOT MEASURED, outside
    the pass count, as at the box; rootn measures all 13 (the direct error;
    the budget's tinyt gate is the box's and is not claimed here). n = 2 and
    -2 have no region."""
    out, worst = P.bound_regions_tw_n("pown", RNE, 6, 11)
    assert out == []
    missing = P.not_measured_tw_n(worst)
    assert [m[0] for m in missing] == ["int1099511627776",
                                       "int281474976710657", "int31", "int63"]
    measured = [k for k, w in worst.items() if w[1]]
    assert len(measured) == 9 and len(worst) == 13
    assert all(worst[k][0] < 0 for k in measured)
    out, worst = P.bound_regions_tw_n("rootn", RNE, 6, 11)
    assert out == [] and P.not_measured_tw_n(worst) == []
    assert len(worst) == 13 and all(w[0] < 0 for w in worst.values())
    for n in (2, -2):
        assert not [r for r in P.REGION_NAMES_TW_N
                    if P.region_n_of(r) == n]


def test_the_bound_check_fails_on_a_lane_over_it():
    """A bound check that cannot fail is worth nothing: the same lanes through
    the build the plant l3_dropped made (3 words of L short) are over 1 Bv at
    pown n = 1000, and the check says so by name."""
    b = P.tw_n_build_of("pown", RNE, 1000, "l3_dropped")
    lanes = P.region_n_cached(FP32, "pown", "int1000", 40, 11)
    out, (worst, main, total) = P.check_bound_tw_n(b, lanes, "int1000")
    assert main > 0 and worst >= 0 and out
    assert "past the bound" in out[0]


def test_a_region_with_no_main_path_lane_is_a_finding_unless_named():
    b = P.tw_n_build_of("pown", RNE, 3)
    lanes = [(sf.inf_bits(FP32), 3)] * 4
    out, (_w, main, _t) = P.check_bound_tw_n(b, lanes, "int")
    assert main == 0 and len(out) == 1 and "measures nothing" in out[0]
    out, _ = P.check_bound_tw_n(b, lanes, "int63")      # named: no finding
    assert out == []


# ---- the constants ---------------------------------------------------------------------------

def test_constants_in_process_and_as_a_program():
    out, lines = P.check_constants_tw_n()
    assert out == [] and len(lines) == 2
    assert all("(triple word, integer operand)" in ln for ln in lines)
    assert "pown fp32" in lines[0] and "rootn fp32" in lines[1]
    findings, text = P.check_constants_cli_tw_n()
    assert findings == []
    assert text[-1] == ("mathlib --check (pow, triple word): 2 routines, "
                        "1 format, 0 differences")
    assert ("mathlib --check (pow, triple word, integer operand): 2 "
            "routines, 1 format, 0 differences") in text


def test_every_new_role_of_the_constants_check_fails_alone():
    """YB2 one ulp off, a word of n one ulp off (plant n_word_ulp), a zero
    word, SIGN held at an even n: each named by the real check."""
    def with_word(role, delta):
        def make(name, fmt, rnd, n):
            b = ml.build(name, fmt, rnd, n=n)
            ref = b.roles[role]
            b.words[ref[1]] += delta
            return b
        return make
    for role, fn, n in (("YB2", "pown", 3), ("YB2", "rootn", 3),
                        ("N0", "pown", 2 ** 24 + 1),
                        ("N1", "pown", 2 ** 24 + 1), ("R0", "rootn", 17),
                        ("R2", "rootn", 17)):
        out, _ = P.check_constants_tw_n(builder=with_word(role, 1),
                                        attrs=(RNE,), names=(fn,), ns=(n,))
        assert out and any(role in s for s in out), (role, out)

    def with_sign(name, fmt, rnd, n):
        b = ml.build(name, fmt, rnd, n=n)
        b.const("SIGN", fmt.sign_mask)
        return b
    out, _ = P.check_constants_tw_n(builder=with_sign, attrs=(RNE,),
                                    names=("pown",), ns=(2,))
    assert out and any("SIGN is held at an even n" in s for s in out)
    # the plant n_word_ulp is red in the check by role and by sum
    out, _ = P.check_constants_tw_n(
        builder=lambda nm, f, r, n: ml.build(nm, f, r, n=n,
                                             plant="n_word_ulp"),
        attrs=(RNE,), names=("pown",), ns=(3,))
    assert out and any("N0" in s for s in out)


# ---- the plants: every check on every plant ---------------------------------------------------

# (plant, function, n) and the checks each must turn red at least; the control
# (no plant) must be green in every check. MEASURED over the checks' scope at
# the sizes of red_checks_tw_n (the matrix's rows list red and green, and no
# check is "not run" at these n: pools has lanes of n = 3 and 2^24 + 1 is the
# n_low_dropped's two-word n, whose pool has none, so pools is not run there)
MATRIX = [
    ("l3_dropped", "pown", 1000, {"bound", "shape"}),
    ("l3_dropped", "rootn", 3, {"pools", "bound", "shape"}),
    ("mark_silenced", "pown", 3, {"pools", "seq", "shape"}),
    ("mark_silenced", "rootn", 3, {"pools", "seq", "shape"}),
    ("n_word_ulp", "pown", 3, {"pools", "constants", "shape"}),
    ("n_word_ulp", "rootn", 3, {"pools", "constants", "shape"}),
    ("n_low_dropped", "pown", 2 ** 24 + 1, {"constants", "shape", "bound"}),
    ("n_word3_dropped", "rootn", 3, {"pools", "constants", "shape"}),
    ("n_row_loud", "pown", 3, {"specials", "seq", "shape"}),
    ("n_row_loud", "rootn", 3, {"specials", "seq", "shape"}),
    ("rootn_m0_neg", "rootn", 2, {"specials", "seq", "shape"}),
    ("rootn_m0_neg", "rootn", -2, {"specials", "seq", "shape"}),
]

_RUNS = {}


def matrix_run(plant, fn, n):
    """(red, not_run) of red_checks_tw_n, once."""
    key = (plant, fn, n)
    if key not in _RUNS:
        _RUNS[key] = P.red_checks_tw_n(plant, fn, n)
    return _RUNS[key]


@pytest.mark.parametrize("fn,n", [("pown", 3), ("rootn", 3), ("pown", 2),
                                  ("rootn", 2 ** 40)])
def test_the_control_is_green_in_every_check_it_ran(fn, n):
    red, not_run = matrix_run(None, fn, n)
    assert all(v == [] for v in red.values()), red
    assert not (set(red) & set(not_run))
    assert set(red) | set(not_run) == set(P.CHECKS_TW_N)


@pytest.mark.parametrize("plant,fn,n,expect", MATRIX,
                         ids=[f"{p}-{f}-{n}" for p, f, n, _ in MATRIX])
def test_each_plant_is_red_in_a_named_check(plant, fn, n, expect):
    red, not_run = matrix_run(plant, fn, n)
    red_names = {k for k, v in red.items() if v}
    assert expect <= red_names, (plant, fn, n, red_names)
    # the rows: red, green and not run are disjoint and cover every check
    green = set(red) - red_names
    assert not (red_names & green) and not (red_names & set(not_run))
    assert red_names | green | set(not_run) == set(P.CHECKS_TW_N)


def test_every_check_is_red_for_some_plant_and_every_plant_is_in_the_matrix():
    reds = set()
    for plant, fn, n, _e in MATRIX:
        red, _nr = matrix_run(plant, fn, n)
        reds |= {k for k, v in red.items() if v}
    assert reds == set(P.CHECKS_TW_N), set(P.CHECKS_TW_N) - reds
    assert {m[0] for m in MATRIX} == set(ml._POW_TW_N_PLANTS) | {
        "l3_dropped", "mark_silenced"}
    # pown n_word3_dropped, exact_rule_no_tl and b1_dropped are not plants of
    # this table: the first is refused for pown by name (above), the others
    # are green in every mode or seen by the first-order budget alone
    assert "exact_rule_no_tl" not in ml._POW_TW_N_PLANTS
    assert "b1_dropped" not in ml._POW_TW_N_PLANTS


def test_a_doctored_row_listing_a_red_check_green_fails_the_real_assertion():
    """The matrix test's assertion, run on a row doctored to say 'green' for a
    check that is red in the real run: it must fail (a leg asserting a fact
    about a literal set cannot)."""
    plant, fn, n, expect = MATRIX[0]
    red, not_run = matrix_run(plant, fn, n)
    red_names = {k for k, v in red.items() if v}
    doctored_expect = expect | {"pools"}          # pools is green here
    assert "pools" not in red_names
    with pytest.raises(AssertionError):
        assert doctored_expect <= red_names
    doctored_not_run = set(not_run) | {"bound"}   # bound ran and is red
    assert red_names & doctored_not_run


# ---- the commands, at fp32 ---------------------------------------------------------------------

def run_cmd(capsys, *argv):
    R.OUT = None
    R.FINDINGS.clear()
    R.main(list(argv))
    return capsys.readouterr().out


def test_pow_pools_reads_every_option_at_fp32_for_pown_and_rootn(capsys):
    out = run_cmd(capsys, "pow-pools", "--fn", "pown,rootn", "--formats",
                  "fp32", "--attrs", "rne", "--ns", "3,5", "--step", "8",
                  "--lanes", "6", "--seed", "7", "--seq")
    lines = out.splitlines()
    pools = [ln for ln in lines if "pow-pools pown fp32 rne n = " in ln]
    assert [ln.split(" n = ")[1].split(":")[0] for ln in pools] == ["3", "5"]
    assert all("seq.py and the compiled shape over" in ln for ln in pools)
    assert not [ln for ln in lines if " rtz " in ln]          # --attrs
    regs = [ln for ln in lines if "pow-regions pown fp32 rne" in ln]
    assert [ln for ln in regs if " rne int:" in ln][0].split(": ")[1] \
        .startswith("6 lanes")
    assert not [ln for ln in regs if " int17 " in ln]          # --ns
    assert "RESULT: ok" in out
    assert "compound" not in out


def test_pow_bound_reads_every_option_at_fp32_and_says_what_measures_nothing(
        capsys):
    out = run_cmd(capsys, "pow-bound", "--fn", "pown,rootn", "--formats",
                  "fp32", "--attrs", "rne", "--n", "6", "--seed", "11")
    assert "pow-bound pown fp32 rne int31 seed 14: NOT MEASURED" in out
    assert "pow-bound pown fp32 rne int63 seed 15: NOT MEASURED" in out
    assert "pow-bound pown fp32: n = 2 and n = -2 have no region" in out
    # the count line exactly: pown measures 9 of 13 regions, rootn 13
    assert ("pow-bound: 22 regions measured (the pass count), 4 NOT "
            "MEASURED (0 main-path lanes), outside it") in out
    assert "RESULT: ok" in out
    with pytest.raises(SystemExit, match="--guard 50: the triple word"):
        run_cmd(capsys, "pow-bound", "--fn", "pown", "--formats", "fp32",
                "--quick", "--guard", "50")
    quick = run_cmd(capsys, "pow-bound", "--fn", "rootn", "--formats", "fp32",
                    "--quick", "--ns", "3")
    assert quick.count("pow-bound rootn fp32 rne") == 2          # int, zone


def test_the_commands_refuse_compound_and_the_budgetless_ones_by_name(capsys):
    with pytest.raises(SystemExit, match="compound.*not built at fp32.*--fn "
                       "pow,powr,pown,rootn"):
        run_cmd(capsys, "pow-bound", "--formats", "fp32")        # default --fn
    with pytest.raises(SystemExit, match="compound.*not built at fp32"):
        run_cmd(capsys, "pow-pools", "--fn", "compound", "--formats", "fp32")
    assert R._pow_formats("fp32", [], ["pown", "rootn"]) == [P.FP32]
    for cmd, words in (("pow-budget", "no first-order budget"),
                       ("pow-rate", "no rate check"),
                       ("pow-family", "no structured families")):
        with pytest.raises(SystemExit, match=words):
            run_cmd(capsys, cmd, "--fn", "pown", "--formats", "fp32")


# ---- seq_check's pow part at fp32 ---------------------------------------------------------------

import collections  # noqa: E402
import subprocess  # noqa: E402

SEQ = ROOT / "host" / "tests" / "seq_check.py"
FORBIDDEN = ("waits for parcel", '["waiting"]', "inv_waiting",
             "INV_FORMATS has no", "not built (parcel", "(parcel M2F's)",
             '["absent"]', "if fmt not in ml.TRIG_FORMATS")


def seq_module():
    sys.path.insert(0, str(ROOT / "host" / "tests"))
    import seq_check
    return seq_check


def test_seq_check_runs_the_pow_part_at_fp32_for_four_names_in_its_source():
    text = SEQ.read_text(encoding="utf-8")
    assert text.count("THE ROUTINE CORPUS DID NOT REACH EVERY FORM") == 1
    assert text.count("THE ROUTINE CORPUS'S POW PART DID NOT RUN EVERY "
                      "FRAGMENT") == 1
    assert "mathlib.POW_FORMATS" in text
    for bad in FORBIDDEN:
        assert bad not in text, bad
    sc = seq_module()
    fp32 = sc.routine_fragments(ml, "pow", "fp32")
    assert fp32 == [("pow", None), ("powr", None), ("pown", 0), ("pown", 1),
                    ("pown", 3), ("pown", -2 ** 63), ("rootn", 1),
                    ("rootn", 3), ("rootn", -2 ** 63)]
    assert not [f for f in fp32 if f[0] == "compound"]
    for k in ("fp64", "fp128", "fp256"):
        assert len(sc.routine_fragments(ml, "pow", k)) == 13
    assert len(sc.routine_fragments(ml, "pow")) == 13
    # the part's own count: 9 pairs x 5 attributes = 45 fragments, 90 programs
    # at fp32; 65 and 130 at each of the three; 240 and 480 over the four
    per = {k: len(sc.routine_fragments(ml, "pow", k)) * len(MODES)
           for k in ("fp32", "fp64", "fp128", "fp256")}
    assert per == {"fp32": 45, "fp64": 65, "fp128": 65, "fp256": 65}
    assert sum(per.values()) == 240 and 2 * sum(per.values()) == 480
    # the other parts' fragment lists do not take the format
    for part in ("six", "trig", "inv"):
        assert sc.routine_fragments(ml, part, "fp32") == \
            sc.routine_fragments(ml, part)
    # the absence is named, in words, no SKIP
    C = sc.routine_counters()
    C["unbuilt"].append(("fp32", ("compound",)))
    clause = sc.pow_clause(C)
    assert "fp32: compound is not run (refused by name at fp32" in clause
    assert "SKIP" not in clause
    assert sc.pow_clause(sc.routine_counters()) == ""


def counters(lanes, fmts=("fp32",), progs=2, n_op=3):
    sc = seq_module()
    C = sc.routine_counters()
    for k in fmts:
        for rnd in MODES:
            key = (k, "pown", rnd, n_op)
            C["fragments"].add(key)
            C["frag_lanes"][key] = lanes
            C["frag_progs"][key] = progs
    return C


def test_the_floor_names_a_fragment_that_compared_too_few_lanes():
    """pow_floor_findings, the reach check's own function (counters hold a
    fragment's lanes over a round's two programs): the plant 'one fragment's
    lanes cut to one' is red at fp64, fp128, fp256 and fp32, and so are totals
    of two, of twenty (every program cut to ten) and of the floor less one;
    the floor itself is green. The clean draw's tail is COMPUTED below."""
    sc = seq_module()
    floor = sc.POW_FRAG_FLOOR
    assert floor == 24
    # a clean fragment-round compares at least the 63 lanes of its guaranteed
    # program less its mask's, and one lane of the other program: under the
    # floor needs floor - 2 or fewer of 63 kept at 0.7, in the third of the
    # programs that are masked
    from fractions import Fraction
    from math import comb
    p = Fraction(7, 10)
    tail = sum(comb(63, k) * p ** k * (1 - p) ** (63 - k)
               for k in range(floor - 1)) / 3
    assert tail < Fraction(1, 10 ** 7), float(tail)
    assert float(tail) * 1000 < 1e-4
    for k in ("fp32", "fp64", "fp128", "fp256"):
        for cut in (1, 2, 20, floor - 1):
            out = sc.pow_floor_findings(counters(cut, (k,)), 1)
            assert len(out) == len(MODES), (k, cut, out)
            assert out[0].startswith(f"pown(x, n = 3) at {k} under ")
            assert f"compared {cut} lanes in 1 round" in out[0]
            assert f"the floor of {floor} a round" in out[0]
        assert sc.pow_floor_findings(counters(floor, (k,)), 1) == []
        assert sc.pow_floor_findings(counters(5 * floor, (k,)), 5) == []
        assert len(sc.pow_floor_findings(counters(5 * floor - 1, (k,)), 5)) \
            == len(MODES)
    # a fragment none of whose programs was compared (a device's refusals) is
    # not held to it, and the lane total does not hide a fragment: another
    # fragment with plenty of lanes does not carry this one
    assert sc.pow_floor_findings(counters(0, progs=0), 1) == []
    C = counters(1)
    C["frag_lanes"][("fp32", "pown", MODES[0], 0)] = 10 ** 6
    assert len(sc.pow_floor_findings(C, 1)) == len(MODES)


def seq_run(*extra, env_hook=None, timeout=1500):
    code = (
        "import sys; sys.path.insert(0, %r); import seq_check as sc;"
        " %s sys.argv = ['seq_check.py'] + %r; sys.exit(sc.main())"
        % (str(ROOT / "host" / "tests"),
           f"sc.POW_FRAGMENT_LANE_CUT.update({env_hook!r});" if env_hook else
           "", list(extra)))
    return subprocess.run([sys.executable, "-B", "-c", code],
                          capture_output=True, text=True, cwd=ROOT,
                          timeout=timeout)


@pytest.mark.skipif(not (ROOT / "host" / "cft.dll").exists()
                    and not (ROOT / "host" / "libcft.so").exists(),
                    reason="host/cft.dll (libcft) is not built here")
def test_seq_check_runs_the_pow_part_at_fp32_and_the_floor_plant_is_red():
    """The tool, run: `--trials 250 --formats fp32 fp64` (fp32 alone fails in the trig part at the base too: no marked lane there, VM4P) clean (exit 0, the pow
    part's summary line with 90 programs, its absence of compound named, the
    reach check passing); and with one fragment cut to one lane at pown n =
    3 (POW_FRAGMENT_LANE_CUT: the plant), red, naming the fragment and
    beginning with the part's own phrase."""
    clean = seq_run("--trials", "250", "--formats", "fp32", "fp64")
    out = clean.stdout + clean.stderr
    assert clean.returncode == 0, out[-1500:]
    line = [ln for ln in out.splitlines()
            if "programs from the routine corpus's pow part" in ln]
    assert len(line) == 1 and "fp32 90 programs" in line[0]
    assert "fp32: compound is not run (refused by name at fp32" in line[0]
    assert "THE ROUTINE CORPUS" not in out
    for cut in (10,):                       # 20 a round: red
        red = seq_run("--trials", "250", "--formats", "fp32", "fp64",
                      env_hook={("pown", 3): cut})
        assert red.returncode == 1 and "under the floor of 24 a round" in \
            red.stdout + red.stderr, cut
    plant = seq_run("--trials", "250", "--formats", "fp32", "fp64",
                    env_hook={("pown", 3): 1})
    out = plant.stdout + plant.stderr
    assert plant.returncode == 1, out[-1500:]
    assert ("THE ROUTINE CORPUS'S POW PART DID NOT RUN EVERY FRAGMENT - "
            "pown(x, n = 3) at fp32 under rne compared") in out
    assert "under the floor of 24 a round" in out
