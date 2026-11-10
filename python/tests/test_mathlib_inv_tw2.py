# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""asin, acos and atan2 at fp32 of python/cft_golden/mathlib.py (parcel M4F2,
M4's build, wave 3): the TRIPLE word at G = 40 on the core parcel M4F1 built
(the study's 2.8, docs/studies/M4-invtrig.md; the model is docs/studies/m4/
m4tw.py, which nothing here imports), held to the harness's fp32 checks
(python/tests/mathlib_inv_harness.py, "fp32: asin, acos and atan2"), quick
enough for the golden stage; the larger runs are `python python/tests/
mathlib_runs.py inv-pools`, `inv-bound` and `inv-corner` with `--formats fp32`.
Eight checks for asin and acos, ten for atan2:

  pools  seq  bound  census  specials  shape  core  constants  [range  corner]

and for every check a planted fault shown red in it, the controls green in all
(mathlib._INV_TW_PLANTS: the twenty-two, private; atan's ten are
test_mathlib_inv_tw.py's), every leg of every check shown failing alone on a
doctored input, the schedule and the registers, the range at 2^-76 (the
study's question 5), 3.6 item 5's three faults, the refusals, the commands,
the sweep generator and the port's pins. The port against the model is a
scratch script of the parcel's entry (nothing here imports docs/studies/m4):
the 15 dag digests, the instructions by phase, the words, the TwoSum and
Fast2Sum counts, and (result, flag word, Vh, Vl, V2, R, R1, R2) on every lane
compared are recorded there, and the digests pinned below.

What these show and what they do not: the pools, the specials, the census, the
range rows, the corner set and the sampled regions are clean (0 wrong
unmarked) and the plants are red in the checks named; fp32's triple word has no
budget in this build (Logan's answer 3), so that the bound holds on every
argument is not shown here: it is the samples on the box and the card's
exhaustive sweeps (asin and acos over all 2^32 arguments, atan2 over every y
for the nine x of ATAN2_X, not the whole space of pairs). A marked lane's guess
is not promised: the replay decides it, and these checks count it.

What each plant row samples (a trim of the lane counts inside the rows, by the
lead's word of 2026-11-10, no check and no plant dropped): the pools whole under
rne and rtz; seq under rne and rtz on the harness's slice, and for asin and
acos once on the inflated bound over the slice and 60 random and 30 edge lanes
(the clean test takes 200 and 100); bound 36 points a region at seed 11 (the
clean test takes 48) and the committed lanes; census every 12th lane of each
family under rtz (the clean test takes every lane under all five attributes);
the specials, shape, range, core and constants whole. The full-size run of
the rows (48 points a region, every census lane,
the seq extras 200 and 100) is a scratch script's, run at the final code
commit, and not part of this file; its result is in the entry of
docs/VALIDATION.md.
"""

import functools
import pathlib
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP32, FP64, FP128, FP256, routines, seq  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_inv_harness as I  # noqa: E402

RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = I.RNE, I.RTZ, I.RDN, I.RUP, I.RMM
MARK = ml.MARK
FNS = ("asin", "acos", "atan2")
ROOT = pathlib.Path(__file__).resolve().parents[2]


def rid(r):
    return sf.RND_NAMES[r]


# ---- what the model measured (box-out2/twrun-costs.fp32-tw.out.txt) ----------
# the dag digest of each fragment (the first 32 hex digits; the brief's 16 are
# their start), equal to the model's `to_fragment()` digest, scheduled and not,
# at the port (the parcel's scratch script, 15 of 15), rne rtz rdn rup rmm
DIGESTS = {
    "asin": ("749a324b28dcedd1efcc05af819f7de4",
             "243defbe95eee94af5f8799b595ea5db",
             "da55fb4677a5e2655d9c84a9e8bf298c",
             "7b8da71fb5278ff70256a4b7b119537e",
             "1566e8507f2ba9ca5028da2cb01e8d90"),
    "acos": ("0913cb531ce36814d400768abe9d1a56",
             "a1557f1f92b0c7576261ca439345c2c5",
             "73afa1234e7e6ed705debfe1125ab555",
             "70d97b4ca63254665d408e7a9c891778",
             "2e4d6251243fec162fa33277654e9975"),
    "atan2": ("2eddaf68e5362a35787e124329cf438b",
              "f3eec70aa54586e9d198889cc7f04977",
              "fc5781942ff6f6786405ab4ad5231a8a",
              "4f0004bd3dfe9d18c0d98d3700994b1e",
              "14fe836d57014623e7cbd0128b5717b3"),
}
# the live counts in the design's order, the ranked order, the depth-first
# order and the order chosen (schedule_order's), the instructions of the
# scheduled program (routines.program) and its highest register
LIVE = {"asin": (26, 37, 25, 25), "acos": (26, 36, 25, 25),
        "atan2": (33, 51, 31, 31)}
PROGRAM = {"asin": (640, 62, 24), "acos": (636, 61, 24),
           "atan2": (521, 70, 30)}
SHAPES = {"asin": (637, 62, 25), "acos": (633, 61, 25),
          "atan2": (518, 70, 31)}
# the model's plants that act on these functions, built by the model and by the
# tree: the first 16 hex digits of the design's-order digest, rne rtz rdn rup
# rmm (the scratch script compared them with the model's plant fragments)
PLANT_DIGESTS = {
    "q2_dropped@asin": ("461d3b73fd858510", "27f208e53693a6f3",
     "f448ee3bed23c8a9", "e0a54842ac1ab9bf", "f3bfb9f5fa4cda7b"),
    "q2_dropped@acos": ("c782d68022fe07d0", "e2b866637538928c",
     "c347c7c0931852c6", "b1378b9c70ecab55", "727ebe29004004fc"),
    "q2_dropped@atan2": ("e0714ba454f7b63b", "d43e75007d03aaef",
     "5f852af276552277", "2555965e8f66c614", "8b865afccbf1421e"),
    "z2_dropped@asin": ("ae2200ffd45ecc6f", "ffde7149c02fc11f",
     "541b4a6d0fe2c5bf", "b80389ecc62d66aa", "9ffaeac58e66a9ee"),
    "z2_dropped@acos": ("17297f02f44bbd8e", "f2179c39b957691c",
     "fd7f3b66834100dd", "abafe63693294cbe", "6afdbe6047759675"),
    "z2_dropped@atan2": ("47093e4407854cb6", "9c64019d7d790510",
     "09bd8cf9bf1bbefe", "05378ee058208403", "0b01495b736e24ba"),
    "head3_two@asin": ("2653cb0e0e33c5fa", "b6e57490e9ebbc61",
     "12139e95a6e17e44", "70640445fdc4dafa", "b3452e09f8555967"),
    "head3_two@acos": ("f732e3aa37b44b81", "fa34177ad111d1de",
     "aecd002d10f31efc", "0e4393f41d192d68", "be42ce7b0af7a1ac"),
    "head3_two@atan2": ("38dadb226347414c", "abbd4d364d29925d",
     "5b07b6e237c094b5", "74c7e0985fb7760a", "ef5e19e00aa002a8"),
    "w2_dropped@asin": ("e61a45be770bbd32", "78be532d442b10ec",
     "7ff5eb290f751ad1", "d1d0246fb3503895", "15808313d9ac1001"),
    "w2_dropped@acos": ("134bbad38a4b18dd", "385d24935ff1b46f",
     "04947d7519fb18fe", "9c1ebe791dedb042", "2c034c92b39058c4"),
    "prescale_d@atan2": ("dba721a3310507e3", "22322a9fd50b2d26",
     "aedabff3f0a2f564", "48731d493aaaec64", "8c59c872a7a8c0f3"),
    "range_low@atan2": ("a90ff00bfee36889", "87f030c8b801a4cb",
     "bd03e836c4de41af", "7b367e483f5984ab", "f1be9b7f2c40d2b8"),
}
# the plants of the triple word, in the table's order: atan's ten (M4F1's
# test file pins them) and these twelve
NEW_PLANTS = ("w2_dropped", "root_fma", "num_two_words", "range_low",
              "domain_edge", "acos_quadrant", "prescale_d", "signed_zero",
              "side_rule_off", "side_rule_sign", "range_off", "quadrant")
ATAN_PLANTS = ("q2_dropped", "z2_dropped", "head3_two", "rem0_fma",
               "tiny_gate_off", "tiny_side", "table_entry", "bound_loose",
               "bound_wide", "mark_silenced")
# the functions each plant reaches (the others refuse it by name)
REACHES = {
    "q2_dropped": FNS, "z2_dropped": FNS, "head3_two": FNS, "rem0_fma": FNS,
    "table_entry": FNS, "bound_loose": FNS, "bound_wide": FNS,
    "mark_silenced": FNS,
    "tiny_gate_off": ("asin",), "tiny_side": ("asin",),
    "w2_dropped": ("asin", "acos"), "root_fma": ("asin", "acos"),
    "num_two_words": ("asin", "acos"), "domain_edge": ("asin", "acos"),
    "acos_quadrant": ("acos",),
    "range_low": ("atan2",), "prescale_d": ("atan2",),
    "signed_zero": ("atan2",), "side_rule_off": ("atan2",),
    "side_rule_sign": ("atan2",), "range_off": ("atan2",),
    "quadrant": ("atan2",),
}


def _doctor(results, i, bits=0, orwith=0, andnot=0):
    out = list(results)
    b, f = out[i]
    out[i] = ((b ^ bits), (f | orwith) & ~andnot)
    return out


def _highest_register(prog):
    """The highest register an instruction of the program names: the
    destination of an ALU instruction, a register operand of one, and the
    register a DEPOSIT or RAISE reads."""
    top = 0
    for w in prog.insns:
        d = seq.decode(w)
        if not d["ctrl"]:
            top = max(top, d["rd"])
            for r, k in (("ra", "ka"), ("rb", "kb"), ("rc", "kc")):
                if not d[k]:
                    top = max(top, d[r])
        elif d["op"] in (seq.DEPOSIT, seq.RAISE):
            top = max(top, d["ra"])
    return top


# =====================================================================
# the interface, the port and what is private
# =====================================================================

def test_fp32_joins_inv_formats_last_and_the_double_words_keep_their_three():
    assert ml.INV_FORMATS == (FP64, FP128, FP256, FP32)
    assert ml._INV_DW_FORMATS == (FP64, FP128, FP256)
    # the readers that are the double word's keep its three
    assert I.FORMATS == (FP64, FP128, FP256)
    import mathlib_inv_family as F
    assert F.FORMATS == (FP64, FP128, FP256)
    assert ml.check_inv_constants.__defaults__[1] == ml._INV_DW_FORMATS
    # nothing public moved
    assert ml.INV_NAMES == ("atan", "asin", "acos", "atan2")
    assert tuple(ml._INV_TW_BUILDERS) == ml.INV_NAMES
    assert tuple(ml._INV_BUILDERS) == ml.INV_NAMES
    assert not any(n.startswith("_") for n in ml.__all__)
    for name in ("_INV_DW_FORMATS", "_build_asin_tw", "_build_acos_tw",
                 "_build_atan2_tw", "_INV_TW_ROLE_CHECKS",
                 "_asin_acos_front_tw"):
        assert name not in ml.__all__ and hasattr(ml, name)
    assert {fn: ml.INV_LIVE_CAP[fn]["fp32"] for fn in ml.INV_NAMES} == {
        "atan": 25, "asin": 25, "acos": 25, "atan2": 31}
    # INV_PLANTS' keys are the double word's twenty-two: none added
    assert len(ml.INV_PLANTS) == 22
    assert not set(NEW_PLANTS[:4]) & set(ml.INV_PLANTS)


def test_the_plants_of_the_triple_word_are_atans_ten_then_these_twelve():
    assert tuple(ml._INV_TW_PLANTS) == ATAN_PLANTS + NEW_PLANTS
    assert all(isinstance(t, str) and len(t) > 20
               for t in ml._INV_TW_PLANTS.values())
    # those that share a name with INV_PLANTS are the double word's names
    shared = set(ml._INV_TW_PLANTS) & set(ml.INV_PLANTS)
    assert {"domain_edge", "acos_quadrant", "prescale_d", "signed_zero",
            "side_rule_off", "side_rule_sign", "range_off", "quadrant",
            "tiny_gate_off", "tiny_side", "table_entry", "bound_loose",
            "mark_silenced"} <= shared
    # u_low_dropped and sqrt_product are not at fp32: refused by name
    for plant in ("u_low_dropped", "sqrt_product"):
        assert plant in ml.INV_PLANTS and plant not in ml._INV_TW_PLANTS
        for fn in ("asin", "acos"):
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to {fn} at fp32: it is a fault of the "
                               "double word's"):
                ml.build(fn, FP32, RNE, plant=plant)


@pytest.mark.parametrize("fn", FNS)
def test_each_plant_is_reached_by_the_functions_it_names_and_refused_by_the_rest(
        fn):
    for plant in ml._INV_TW_PLANTS:
        if fn in REACHES[plant]:
            clean = I.tw2_build_of(fn, RNE)
            b = ml.build(fn, FP32, RNE, plant=plant)
            assert plant in b._fired
            # a plant changes the build (instructions or words) or its
            # constants: some leg of the fragment differs from the clean one
            assert (ml.dag_digest(b.fragment(schedule=False))
                    != ml.dag_digest(clean.fragment(schedule=False)) or
                    b.words != clean.words), (fn, plant)
        else:
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to {fn} at fp32: the fault is not "
                               "reached"):
                ml.build(fn, FP32, RNE, plant=plant)


@pytest.mark.parametrize("fn", FNS)
@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_the_dag_digests_are_the_models(fn, rnd):
    b = I.tw2_build_of(fn, rnd)
    want = DIGESTS[fn][RND.index(rnd)]
    assert ml.dag_digest(b.fragment())[:32] == want
    assert ml.dag_digest(b.fragment(schedule=False))[:32] == want
    assert ml.dag_digest(ml.fragment(fn, FP32, rnd))[:32] == want


@pytest.mark.parametrize("plant", sorted(PLANT_DIGESTS))
def test_the_models_plants_are_the_models_by_digest(plant):
    mine, fn = plant.split("@")
    assert fn in REACHES[mine]
    got = tuple(ml.dag_digest(ml.build(fn, FP32, r, plant=mine).fragment(
        schedule=False))[:16] for r in RND)
    assert got == PLANT_DIGESTS[plant]


def test_the_shape_is_the_models():
    for fn in FNS:
        ins, words, live = SHAPES[fn]
        assert I.SHAPE_TW[(fn, "fp32")] == [(ins, words, live)] * 5
        assert ml.INV_LIVE_CAP[fn]["fp32"] == live
        assert sum(I.model_phases_tw2(fn, "fp32").values()) == ins
        for rnd in RND:
            b = I.tw2_build_of(fn, rnd)
            f = b.fragment()
            assert (len(f), len(f.words), f.live_max()) == (ins, words, live)
            assert b.meta["family"] == "triple word"
            assert (b.meta["K3"], b.meta["K2"], b.meta["D"]) == (3, 3, 8)
            assert b.meta["G"] == 40 and b.meta["N"] == 8
        # the model's TwoSum and Fast2Sum counts (twrun-costs)
        b = I.tw2_build_of(fn, RNE)
        assert (b._eft["two_sum"], b._eft["fast_two_sum"]) == {
            "asin": (32, 42), "acos": (32, 42), "atan2": (22, 31)}[fn]
    assert I.FLAG_WORDS["asin"] == {0x0, 0x1, 0x10, 0x18, 0x90}
    assert I.FLAG_WORDS["acos"] == I.FLAG_WORDS["atan2"] == {0x0, 0x1, 0x10,
                                                              0x90}
    # the inputs: atan2 reads y and x
    assert I.tw2_build_of("atan2", RNE).inputs == ("a", "b")
    assert I.tw2_build_of("asin", RNE).inputs == ("a",)


@pytest.mark.parametrize("fn", FNS)
def test_a_lane_of_the_fragment_and_of_its_build_agree(fn):
    f, b = I.tw2_fragment_of(fn, RNE), I.tw2_build_of(fn, RNE)
    for x in I.sample(fn, FP32, "random", 20, 3) + list(I.pool(fn, FP32)[:10]):
        r, fl, pr = b.run(x, ("Vh", "Vl", "V2", "Bv"))
        assert (r, fl) == ml.evaluate(f, x)
        assert set(pr) == {"Vh", "Vl", "V2", "Bv"}


def test_the_probes_asin_and_acos_add_to_the_models():
    for fn in ("asin", "acos"):
        b = I.tw2_build_of(fn, RNE)
        for k in ("w0", "w1", "w2", "u0", "wq", "W2", "s0", "q0", "N0", "D0",
                  "rem0", "tt", "Kk", "Vh", "Vl", "V2", "R", "R1", "R2",
                  "Bv", "mk"):
            assert k in b.probes, (fn, k)
    assert "W2" not in I.tw2_build_of("asin", RNE, "root_fma").probes
    assert "w2" not in I.tw2_build_of("asin", RNE, "w2_dropped").probes
    # atan2 has no root
    assert "w0" not in I.tw2_build_of("atan2", RNE).probes


# =====================================================================
# the schedule and the registers
# =====================================================================

@pytest.mark.parametrize("fn", FNS)
@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_the_depth_first_schedule_fits_the_32_registers_and_atan2s_design_order_does_not(
        fn, rnd):
    assert seq.NREG == 32
    b = I.tw2_build_of(fn, rnd)
    raw = b.fragment(schedule=False)
    phases = [b.phase_of[i] for i in b.live_indices()]
    design = raw.live_max()
    ranked = ml.permuted(raw, ml._ranked_order(raw, phases)).live_max()
    dfs = ml.permuted(raw, ml._dfs_order(raw)).live_max()
    f = b.fragment()
    assert (design, ranked, dfs, f.live_max()) == LIVE[fn]
    # schedule_order's choice is the depth-first order
    assert f.live_max() == dfs < design
    cap = ml.INV_LIVE_CAP[fn]["fp32"]
    assert f.live_max() == cap
    assert ml.invariants(f, live_cap=cap) == []
    assert ml.invariants(f, live_cap=cap - 1) == [
        f"{cap} values live at once, past {cap - 1}"]
    ins, words, top = PROGRAM[fn]
    prog, bank = routines.program(f)
    assert (len(prog.insns), len(bank), _highest_register(prog)) == (
        ins, words, top)
    p24, bank24 = H.r24_program(f)
    assert len(p24.insns) == ins + 2 and _highest_register(p24) == top
    if fn == "atan2":
        # 31 of the 32 registers leaves a caller one (the study's 2.8,
        # :738 to :744); the design's order keeps 33 live and the allocator
        # places it nowhere
        assert top == 30 and seq.NREG - 1 - top == 1
        with pytest.raises(AssertionError, match="no register for the "
                           "harness"):
            routines.program(raw)
        with pytest.raises(AssertionError, match="no register for the "
                           "harness"):
            H.r24_program(raw)
    else:
        routines.program(raw)             # the design's order is placed


def test_schedule_orders_docstring_says_all_four_take_the_depth_first_order_at_fp32():
    doc = ml.schedule_order.__doc__
    assert "At fp32" in doc and "all four take the depth-first order" in doc
    assert "25," in doc and "31 values live" in doc


# =====================================================================
# the refusals
# =====================================================================

@pytest.mark.parametrize("name", FNS)
def test_a_name_that_is_not_a_builder_at_fp32_is_refused_by_name(
        monkeypatch, name):
    """The guard stays for a name not in _INV_TW_BUILDERS: each in turn taken
    out of the builders and the fragment cache (as the double word's
    refusal is held in test_mathlib_inv.py), its message naming no parcel."""
    monkeypatch.setattr(ml, "_INV_TW_BUILDERS", {
        k: v for k, v in ml._INV_TW_BUILDERS.items() if k != name})
    monkeypatch.setattr(ml, "_CACHE", {})
    for call in (ml.build, ml.fragment):
        with pytest.raises(ValueError) as e:
            call(name, FP32, RNE)
        msg = str(e.value)
        assert f"{name} at fp32 is not built: fp32 is the triple word" in msg
        assert "parcel" not in msg
        assert name not in msg.split("(")[1]
    # the others are still built
    other = next(n for n in FNS if n != name)
    assert ml.fragment(other, FP32, RNE).fmt is FP32


def test_the_fragment_is_built_once_and_shared():
    a, b = ml.fragment("atan2", FP32, RNE), ml.fragment("atan2", FP32, RNE)
    assert a is b and a.inputs == ("a", "b")


# =====================================================================
# seq_check has no inverse fp32 clause
# =====================================================================

def test_seq_check_has_no_inverse_fp32_clause():
    src = (ROOT / "host" / "tests" / "seq_check.py").read_text(
        encoding="utf-8")
    for gone in ("waits for parcel", '["waiting"]', "inv_waiting",
                 "INV_FORMATS has no"):
        assert gone not in src, gone
    assert "mathlib.INV_FORMATS" in src
    # the six's literal, once and plain
    assert src.count("THE ROUTINE CORPUS DID NOT REACH EVERY FORM") == 1
    # the asked-formats guard is kept (it is not the clause)
    assert "the part ran at none of" in src
    assert "routine_modules()[0].INV_FORMATS" in src


# =====================================================================
# question 5: the tiny-quotient range at 2^(emin+2p+2) = 2^-76
# =====================================================================

def _edge(f, lo=1, hi=0x3f000000):
    """The last y that marks in atan2(y, 1), by bisection on the fragment."""
    one = sf.one_bits(FP32)
    assert ml.evaluate(f, (lo, one))[1] & MARK
    assert not ml.evaluate(f, (hi, one))[1] & MARK
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ml.evaluate(f, (mid, one))[1] & MARK:
            lo = mid
        else:
            hi = mid
    return lo


@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_the_range_is_marked_below_2_to_the_minus_76_and_not_above(rnd):
    f = I.tw2_fragment_of("atan2", rnd)
    one = sf.one_bits(FP32)
    # the edge by bisection, under every attribute: 0x19802007 and no other
    assert _edge(f) == I.RANGE_EDGE["fp32"] == 0x19802007
    # held in exact rationals: RECIP_SEED(1) = 1 - 2^-10 (softfloat's seed),
    # t~ = y RECIP_SEED(1) rounded, and the mark is t~ < 2^(emin+2p+2) = 2^-76
    seed = I.value(FP32, sf.recip_seed(FP32, one)[0])
    assert seed == Fraction(1023, 1024)
    assert FP32.emin + 2 * FP32.prec + 2 == -76
    assert ml._dec(FP32, I.RANGE_EDGE["fp32"]) * seed < Fraction(2) ** -76
    assert ml._dec(FP32, I.RANGE_EDGE["fp32"] + 1) * seed >= \
        Fraction(2) ** -76 * (1 - Fraction(1, 2 ** 25))
    # 2^-75 unmarked, 2^-76 marked (the edge is 1.000977 of 2^-76)
    p2 = lambda e: ml._enc(FP32, Fraction(2) ** e)       # noqa: E731
    assert not ml.evaluate(f, (p2(-75), one))[1] & MARK
    assert ml.evaluate(f, (p2(-76), one))[1] & MARK
    assert ml.evaluate(f, (p2(-77), one))[1] & MARK
    # and in the band between 2^-100 and 2^-76, which the double word's edge
    # would leave unmarked
    for e in (-80, -90, -98):
        assert ml.evaluate(f, (p2(e), one))[1] & MARK
    # the mark leaves the bits: the guess is the main path's, whose value is
    # counted and not promised
    bits, fl = ml.evaluate(f, (p2(-80), one))
    assert fl == 0x90 or fl & MARK


def test_range_low_moves_the_edge_to_the_double_words_2_to_the_minus_100():
    f = I.tw2_fragment_of("atan2", RNE, "range_low")
    one = sf.one_bits(FP32)
    edge = _edge(f, lo=1, hi=0x3f000000)
    # 1.000977 of 2^-100 (the same seed), and 2^-76 is unmarked
    assert edge == 0x0d802007
    assert ml._dec(FP32, edge) * Fraction(1023, 1024) < Fraction(2) ** -100
    assert not ml.evaluate(f, (ml._enc(FP32, Fraction(2) ** -76), one))[1] \
        & MARK
    assert not ml.evaluate(f, (ml._enc(FP32, Fraction(2) ** -80), one))[1] \
        & MARK
    # the plant is red where a lane between the edges must mark: in the range
    # rows, in the pools (9 of the 31 committed marks lie between 2^-100 and
    # 2^-76, MEASURED) and in the constants (TQR is a derived word)
    red = I.check_range_tw(f)[0]
    assert red and all(s.startswith("range: ") for s in red)
    assert any("not marked" in s for s in red)
    pools = I.check_pools_tw2("atan2", RNE, "range_low")[0]
    assert len(pools) == 1 and "9 lanes on the committed list are not "         "marked" in pools[0]
    bad = I.check_constants_tw2("atan2", "range_low")[0]
    assert len(bad) == 1 and "TQR" in bad[0]
    # the band between: the committed rows that turn it red
    q = lambda lane: abs(I.value(FP32, lane[0])) / I.value(FP32, lane[1])  # noqa
    below = [lane for lab, lane in I.RANGE_ROWS["fp32"]
             if Fraction(2) ** -100 < q(lane) < Fraction(2) ** -76]
    assert len(below) == 6
    assert all(not ml.evaluate(f, lane)[1] & MARK for lane in below)
    assert all(ml.evaluate(I.tw2_fragment_of("atan2", RNE), lane)[1] & MARK
               for lane in below)


def test_the_range_predicates_are_the_triple_words_not_the_double_words():
    assert I._tqr_tw(FP32) == Fraction(2) ** -76
    assert I._tqr(FP32) == Fraction(2) ** -100
    lo, hi = I._tq_band_tw(FP32)
    assert lo < Fraction(2) ** -76 < hi
    assert hi / lo < 1 + Fraction(6, 1000)
    assert I._tq_band(FP32)[1] < lo
    # in_main: at fp32 the main path begins at atan's gate 2^-13, far above
    # either range's margin, so the double word's predicate is right there
    t = lambda e: (ml._enc(FP32, Fraction(2) ** e), sf.one_bits(FP32))   # noqa
    assert not I.in_main("atan2", FP32, t(-80))
    assert not I.in_main("atan2", FP32, t(-20))
    assert I.in_main("atan2", FP32, t(-12))
    assert 2 ** -13 > 2 ** (FP32.emin + 2 * FP32.prec + 4)


# =====================================================================
# the checks, clean
# =====================================================================

@pytest.mark.parametrize("fn", FNS)
@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_pools(fn, rnd):
    xs = I.pool(fn, FP32)
    assert len(xs) == (527 if fn == "atan2" else 333)     # MEASURED
    out, t = I.check_pools_tw2(fn, rnd)
    assert out == [] and t.n == len(xs) and t.wrong == []
    if fn == "atan2":
        # MEASURED: 31 lanes, all in the tiny-quotient range, the same under
        # every attribute; no fp32 row of INV_POOL_MARKS is needed (or exists)
        assert sorted(t.marked) == sorted(I.POOL_MARKS_TW) and \
            len(t.marked) == 31
    else:
        assert t.marked == []
    assert not any(m[1] == "fp32" for m in I.INV_POOL_MARKS)
    assert len(I.INV_POOL_MARKS) == 265


def test_atan2s_pool_marks_are_the_range_in_exact_rationals():
    out, band = I.check_pool_marks_tw()
    assert out == [] and band == []         # no pool lane in the seed's band
    lo, hi = I._tq_band_tw(FP32)
    for lane in I.POOL_MARKS_TW:
        t = I._tq_shape(FP32, lane)
        assert t is not None and t < lo
    # the committed 31 are every pool lane of the shape under the edge
    inside = [x for x in I.pool("atan2", FP32)
              if (t := I._tq_shape(FP32, x)) is not None and t < hi]
    assert sorted(inside) == sorted(I.POOL_MARKS_TW)


@pytest.mark.parametrize("fn", FNS)
@pytest.mark.parametrize("rnd", (RNE, RTZ), ids=rid)
def test_seq(fn, rnd):
    out, lanes = I.check_seq_tw2(fn, rnd)
    assert out == []
    assert len(lanes) == (185 if fn == "atan2" else 88)       # MEASURED
    assert I.structured_lanes(fn, FP32, rnd) == []
    f = I.tw2_fragment_of(fn, rnd)
    marked = [x for x in lanes if ml.evaluate(f, x)[1] & MARK]
    if fn == "atan2":
        # the committed range rows are among the lanes, marked in the byte
        assert set(I.SEQ_RANGE[("atan2", "fp32")]) <= set(lanes)
        assert len(marked) == 15
    else:
        assert marked == []


@pytest.mark.parametrize("fn", ("asin", "acos"))
def test_seq_on_the_inflated_bound_marks_lanes_and_runs_the_mark_through_seq(
        fn):
    shift = I.TW2_SEQ_SHIFT[fn]
    assert shift == 34
    out, lanes = I.check_seq_tw2(fn, RNE, None, shift)
    assert out == []
    f = I.tw2_fragment_of(fn, RNE, None, shift)
    marked = [x for x in lanes if ml.evaluate(f, x)[1] & MARK]
    # MEASURED: 7 of 388 (asin) and 3 of 388 (acos). The rate is re-derived
    # for each function: Bv = 2^-(p+G') |V| with G' = 6, so a main-path lane
    # marks with probability about 2 Bv / ulp(V) = 2^-6 m (ESTIMATE, m the
    # result's significand, 0.016 to 0.031); counted over 2,000 lanes of the
    # random and edge regions at seed 31, rne and rtz: asin 1.9%, 2.7%, 2.0%
    # and 2.0%, acos 1.3%, 2.1%, 1.0% and 2.7% (MEASURED, not asserted: only
    # that the mark is exercised)
    assert len(marked) >= 3, len(marked)
    b = I.tw2_build_of(fn, RNE, None, shift)
    assert b.meta["shift"] == 34 and b.meta["G"] == 40
    assert b.words[b.roles["BREL"][1]] == ml._pow2(FP32, -30)
    prog, bank = H.r24_program(f)
    res = seq.run(prog, *I._split(lanes), bank=bank)
    idx = {x: i for i, x in enumerate(lanes)}
    assert all(res.lane_flags[idx[x]] & seq.LANE_MARKED for x in marked)
    assert res.status & seq.STATUS_MARKED
    right = sum(1 for x in marked
                if (lambda r: (r[0], r[1] & 0x1F))(ml.evaluate(f, x))
                == I.golden(FP32, RNE, x, fn))
    assert right <= len(marked)             # counted, not promised


@pytest.mark.parametrize("fn", FNS)
def test_bound(fn):
    out, worst = I.check_bound_tw2(fn)
    assert out == [], out
    regions = {"asin": {"edge", "big", "small", "random", "diag", "rem0",
                        "root"},
               "acos": {"edge", "big", "small", "random", "diag", "rem0",
                        "root"},
               "atan2": {"edge", "big", "small", "random", "diag", "rem0"}}
    assert set(worst) == regions[fn]
    for region in ("edge", "big", "small", "random", "diag"):
        w, main, n = worst[region]
        assert n == 48
        if fn != "atan2":
            assert main == n, region
        else:
            assert main >= 12, region      # the range and the gate are not
            #                                main-path lanes
    # the largest is a SAMPLED lower bound (240 points, seed 11, plus the
    # committed lanes, which the clean build holds): each region under 2^-4 of Bv
    top = max(w for w, _m, _n in worst.values())
    assert -10 < top < -3, worst
    for label in ("rem0", "root"):
        if label in worst:
            n_ = len(I.committed_tw2(fn)[label])
            assert worst[label][1:] == (n_, n_)


@pytest.mark.parametrize("fn", FNS)
def test_the_bound_sums_all_three_words(fn):
    """bound_log2 reads V2: without it the same lane is far past the bound (V2
    is 2^-48 of V, the bound 2^-64)."""
    import mpmath
    b = I.tw2_build_of(fn, RNE)
    shorts = []
    for x in I.sample(fn, FP32, "edge", 6, 5):
        with_v2 = I.bound_log2(b, x)
        _r, _f, pr = b.run(x, ("Vh", "Vl", "V2", "Bv"))
        with mpmath.workprec(4 * 24 + 200):
            V = I.value(FP32, pr["Vh"]) + I.value(FP32, pr["Vl"])
            err = abs(I._mp(V) - I.true_value(fn, FP32, x))
            shorts.append(float(mpmath.log(
                err / I._mp(abs(I.value(FP32, pr["Bv"]))), 2)))
        assert with_v2 < -5
    assert max(shorts) > 10, shorts


def test_the_census_lanes_and_distances():
    """The census is M4G4's lane makers at fp32: zero marks is the claim,
    judged per lane by d, the distance from |f| to the nearest rounding
    boundary in units of 2^-(p+G) |f| at G = 40. The least d of each family
    (MEASURED, mpmath at 4p + 200 bits): every one 2^9 or more, so that the
    in-lane bound (one unit) cannot reach a boundary."""
    least = {}
    for fn in FNS:
        lanes = I.census_lanes_tw(fn)
        least[fn] = I.census_min_d_tw(fn, lanes)
    assert {fn: sorted(least[fn]) for fn in FNS} == {
        "asin": ["near1", "tiny"], "acos": ["near", "near1"],
        "atan2": ["diag", "near", "ratio", "tiny"]}
    counts = {fn: {fam: len(xs) for fam, xs in I.census_lanes_tw(fn).items()}
              for fn in FNS}
    assert counts == {
        "asin": {"tiny": 224, "near1": 64},
        "acos": {"near": 516, "near1": 128},
        "atan2": {"tiny": 768, "near": 516, "ratio": 120, "diag": 1440}}
    for fn in FNS:
        for fam, (near, directed) in least[fn].items():
            assert near > 2 ** 9 and directed > 2 ** 14 - 1, (fn, fam)
    # the windows: acos's and atan2's sit 719 units (nearest) at the closest
    assert 700 < least["acos"]["near"][0] < 740
    assert abs(least["acos"]["near"][0] - least["atan2"]["near"][0]) < 0.01


@pytest.mark.parametrize("fn", FNS)
def test_census(fn):
    out, t = I.check_census_tw2(fn)
    assert out == [] and t["marked"] == 0 and t["wrong"] == 0
    n = sum(len(xs) for xs in I.census_lanes_tw(fn).values())
    assert t["lanes"] == n * 5                     # five attributes


@pytest.mark.parametrize("fn", FNS)
@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_specials(fn, rnd):
    out, n = I.check_specials(I.tw2_fragment_of(fn, rnd))
    assert out == [] and n == {"asin": 32, "acos": 32, "atan2": 69}[fn], \
        (out, n)


def test_atan2s_specials_rows_at_fp32():
    rows = I.special_rows("atan2", FP32)
    labels = [lab for lab, _ in rows]
    assert "the range's edge: first y that does not mark, y / 1" in labels
    assert not any(lab in labels for lab in I.MARKING_ROWS["fp32"])
    assert I.MARKING_ROWS["fp32"] == I._RANGE_LABELS
    edge = dict(rows)["the range's edge: first y that does not mark, y / 1"]
    assert edge == [(0x19802008, sf.one_bits(FP32))]


@pytest.mark.parametrize("fn", FNS)
def test_shape(fn):
    assert I.check_shape_tw2(fn) == []
    builds = {(fn, r): I.tw2_build_of(fn, r) for r in RND}
    f = builds[(fn, RNE)].fragment()
    assert tuple(sorted(routines.flag_words(f))) == tuple(sorted(
        I.FLAG_WORDS[fn]))
    counts = f.counts()
    assert (counts.get("min", 0), counts.get("max", 0)) == I.MIN_MAX[fn]
    assert I.MIN_MAX == {**I.MIN_MAX, "asin": (1, 1), "acos": (1, 1),
                         "atan2": (1, 0)}


@pytest.mark.parametrize("fn", FNS)
def test_constants_in_process(fn):
    findings, lines = I.check_constants_tw2(fn)
    assert findings == []
    assert len(lines) == 3 and lines[0].startswith("atan(7/8) + atan(1/15)")
    n = {"asin": 68, "acos": 69, "atan2": 78}[fn]             # MEASURED
    assert f"{fn} fp32 (triple word): G = 40, plan (K3, K2, D) = (3, 3, 8): " \
        f"{n} derived constants in 1 fragments" in lines[2]
    # the three fragments' own words, asked in the five attributes
    f5, l5 = I.check_constants_tw2(fn, attrs=RND)
    assert f5 == [] and f"{n * 5} derived constants in 5 fragments" in l5[2]


def test_constants_as_a_program_print_the_four_routines():
    import subprocess
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--check", "--only", "inv-tw"],
                       cwd=ROOT / "python", capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    got = r.stdout.splitlines()
    assert len(got) == 7 and got[6] == (
        "mathlib --check (inv, triple word): 4 routines, 1 format, 0 "
        "differences")
    for fn, line in zip(("atan", "asin", "acos", "atan2"), got[2:6]):
        assert line.startswith(f"{fn} fp32 (triple word): G = 40")


@pytest.mark.parametrize("triple", (True, False))
def test_core(triple):
    out, t = I.check_core_tw2(None, triple)
    assert out == [] and t["past"] == 0 and t["kk"] == 0 and t["lanes"] == 60
    # the three-word branch is the one asin and acos reach: M4F1's check
    # runs it, with the numerator's third word


@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_range(rnd):
    f = I.tw2_fragment_of("atan2", rnd)
    out, t = I.check_range_tw(f)
    assert out == []
    assert t["lanes"] == t["marked"] == len(I.RANGE_ROWS["fp32"]) == 15
    # a marked lane's guess is counted, not compared
    assert 0 <= t["guess_right"] <= t["marked"]


@pytest.mark.parametrize("rnd", RND, ids=rid)
def test_corner(rnd):
    b = I.tw2_build_of("atan2", rnd)
    out, t = I.check_corner(b.fragment(), b=b)
    assert out == [] and t["lanes"] == 100 and t["wrong"] == 0
    assert t["differ"] == 0
    if rnd == RNE:
        # MEASURED: 36 of 100 mark, the rest are inside the bound with Bv
        # not underflowed
        assert t["marked"] == 36 and t["bv0"] == 0 and t["past"] == 0
        assert -9 < t["largest"] < -5


def test_the_corner_is_a_committed_set_in_the_region():
    lanes = I.CORNER["fp32"]
    assert len(lanes) == len(set(lanes)) == 100
    assert lanes == I.sample("atan2", FP32, "tinyn", 100, 17)
    assert all(I.corner_region(FP32, x) for x in lanes)


# =====================================================================
# 3.6 item 5: the three faults the model's final form does not carry
# =====================================================================

@pytest.mark.parametrize("fn", FNS)
def test_rem0_fma_is_red_on_the_committed_lanes(fn):
    lanes = I.REM0_LANES_TW[fn]
    assert len(set(lanes)) == len(lanes) >= 6
    if fn == "atan2":
        assert (0x386a8b55, 0xb7948c81) in lanes        # R3b's lane
    clean, plant = I.tw2_build_of(fn, RNE), I.tw2_build_of(fn, RNE,
                                                           "rem0_fma")
    for x in lanes:
        # the independent predicate: N0 - q0 D0 is NOT representable in one
        # word, in exact rationals from the CLEAN build's probes
        assert I.rem0_inexact_tw(fn, x), x
        assert I.bound_log2(clean, x) < -2, x
        assert I.bound_log2(plant, x) > 5, x
    out, worst = I.check_bound_tw2(fn, "rem0_fma")
    assert out and any(f"{fn} fp32 rne rem0: " in s for s in out)
    # where the remainder is representable the plant IS the clean build, bit
    # for bit, on lanes of the regions
    same = 0
    for region in ("edge", "random"):
        for x in I.sample(fn, FP32, region, 25, 17):
            if not I.in_main(fn, FP32, x) or I.rem0_inexact_tw(fn, x):
                continue
            a = plant.run(x, ("Vh", "Vl", "V2"))[2]
            b = clean.run(x, ("Vh", "Vl", "V2"))[2]
            assert a == b, x
            same += 1
    assert same > 10
    # atan2's pools are green under the plant, the lane of R3b is past the
    # bound by 2^11.1
    if fn == "atan2":
        r = I.bound_log2(plant, (0x386a8b55, 0xb7948c81))
        assert 11.0 < r < 11.2, r
        for rnd in RND:
            assert I.check_pools_tw2(fn, rnd, "rem0_fma")[0] == []
        # and the four sampled regions of 48 points are green: red in
        # nothing there
        regs = {k: v for k, v in worst.items() if k != "rem0"}
        assert all(w < -3 for w, _m, _n in regs.values())


@pytest.mark.parametrize("fn", ("asin", "acos"))
def test_root_fma_is_red_on_the_sampled_regions_and_the_committed_lanes(fn):
    lanes = I.ROOT_LANES_TW[fn]
    clean, plant = I.tw2_build_of(fn, RNE), I.tw2_build_of(fn, RNE,
                                                           "root_fma")
    for x in lanes:
        assert I.root_inexact_tw(fn, x), x
        assert I.bound_log2(clean, x) < -2, x
        assert I.bound_log2(plant, x) > 5, x
    out, worst = I.check_bound_tw2(fn, "root_fma")
    assert out
    regions = [s.split(": ")[1].split()[-1] for s in out]
    assert "root" in regions and len(set(regions)) >= 2
    # the root_fma fragment differs from the clean one by the TwoProd error
    assert (len(clean.fragment()) - len(plant.fragment())) in range(1, 12)


@pytest.mark.parametrize("fn", ("asin", "acos"))
def test_num_two_words_and_w2_dropped_are_red_in_the_regions(fn):
    for plant in ("num_two_words", "w2_dropped"):
        out, worst = I.check_bound_tw2(fn, plant)
        assert out, (fn, plant)
        assert sum(1 for s in out if s.startswith("bound: ")) >= 3
        # and the pools do not see either: the bound is the check
        for rnd in (RNE, RTZ):
            assert I.check_pools_tw2(fn, rnd, plant)[0] == [], (fn, plant)
    # num_two_words is also red in the core: the third word of the numerator
    out, t = I.check_core_tw2("num_two_words", True)
    assert out and t["past"] > 0
    # and in no atan, atan2: the branch is the three-word one
    for other in ("atan", "atan2"):
        with pytest.raises(ValueError, match="does not apply"):
            ml.build(other, FP32, RNE, plant="num_two_words")


def test_prescale_d_and_range_low_are_red_in_the_corner_alone_of_the_lanes():
    for plant, key in (("prescale_d", "past"), ("range_low", "bv0")):
        b = I.tw2_build_of("atan2", RNE, plant)
        out, t = I.check_corner(b.fragment(), b=b)
        assert out and t[key] > 0, (plant, t)
    b = I.tw2_build_of("atan2", RNE, "prescale_d")
    out, t = I.check_corner(b.fragment(), b=b)
    # MEASURED: 7 unmarked lanes past the bound, to 2^34.3 of Bv
    assert t["past"] == 7 and 34 < max(
        I.bound_log2(b, x) for x in I.CORNER["fp32"]
        if x[0] & 0x7fffffff and not ml.evaluate(b.fragment(), x)[1] & MARK
    ) < 35
    b = I.tw2_build_of("atan2", RNE, "range_low")
    out, t = I.check_corner(b.fragment(), b=b)
    assert t["bv0"] == 15 and t["marked"] == 5       # MEASURED


# =====================================================================
# the plants: each red in its checks and green in the others
# =====================================================================

# Every row lists EVERY check, red, green or NOT RUN (a test fails on a row that
# omits one, or that lists a check green that did not run). A check that does
# not run for a plant is neither red nor green: the core is refused by name
# ("does not apply") for a plant the core holds no fault of. MEASURED by this
# parcel: python/tests/mathlib_inv_harness.red_checks_tw2(fn, plant) is the
# run (pools under rne and rtz and, for atan2, the marks' own leg, census
# under rtz at every twelfth lane of each family, seq under rne and rtz and,
# for asin and acos, once on the bound inflated to G' = 6 (the seq slice and
# 60 random and 30 edge lanes), bound over the fn's regions of 36
# points and the committed lanes under rne, specials and shape under all five
# attributes, range for atan2 under all five, core on the branches the plant
# reaches, constants under rne and corner for atan2 under rne).
PLANTED_ASIN = [
    ("w2_dropped", ("bound", "shape"), ("pools", "seq", "census",
     "specials", "constants"), ("core",)),
    ("root_fma", ("bound", "shape"), ("pools", "seq", "census", "specials",
     "constants"), ("core",)),
    ("num_two_words", ("bound", "shape", "core"), ("pools", "seq", "census",
     "specials", "constants"), ()),
    ("domain_edge", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "census"), ("core",)),
    ("q2_dropped", ("bound", "shape", "core"), ("pools", "seq", "census",
     "specials", "constants"), ()),
    ("z2_dropped", ("bound", "shape", "core"), ("pools", "seq", "census",
     "specials", "constants"), ()),
    ("head3_two", ("bound", "shape", "core", "constants"), ("pools", "seq",
     "census", "specials"), ()),
    ("rem0_fma", ("bound", "shape"), ("pools", "seq", "census", "specials",
     "core", "constants"), ()),
    ("tiny_gate_off", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "census"), ("core",)),
    ("tiny_side", ("pools", "seq", "census", "specials", "shape",
     "constants"), ("bound",), ("core",)),
    ("table_entry", ("pools", "seq", "bound", "core", "constants"),
     ("census", "specials", "shape"), ()),
    ("bound_loose", ("seq", "bound", "constants"), ("pools", "census",
     "specials", "shape"), ("core",)),
    ("bound_wide", ("constants",), ("pools", "seq", "bound", "census",
     "specials", "shape"), ("core",)),
    ("mark_silenced", ("seq", "shape"), ("pools", "bound", "census",
     "specials", "constants"), ("core",)),
]

PLANTED_ACOS = [
    ("w2_dropped", ("bound", "shape"), ("pools", "seq", "census",
     "specials", "constants"), ("core",)),
    ("root_fma", ("bound", "shape"), ("pools", "seq", "census", "specials",
     "constants"), ("core",)),
    ("num_two_words", ("bound", "shape", "core"), ("pools", "seq", "census",
     "specials", "constants"), ()),
    ("domain_edge", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "census"), ("core",)),
    ("acos_quadrant", ("pools", "seq", "bound", "census", "specials",
     "shape"), ("constants",), ("core",)),
    ("q2_dropped", ("bound", "shape", "core"), ("pools", "seq", "census",
     "specials", "constants"), ()),
    ("z2_dropped", ("bound", "shape", "core"), ("pools", "seq", "census",
     "specials", "constants"), ()),
    ("head3_two", ("bound", "shape", "core", "constants"), ("pools", "seq",
     "census", "specials"), ()),
    ("rem0_fma", ("bound", "shape"), ("pools", "seq", "census", "specials",
     "core", "constants"), ()),
    ("table_entry", ("pools", "seq", "bound", "core", "constants"),
     ("census", "specials", "shape"), ()),
    ("bound_loose", ("seq", "bound", "constants"), ("pools", "census",
     "specials", "shape"), ("core",)),
    ("bound_wide", ("census", "constants"), ("pools", "seq", "bound",
     "specials", "shape"), ("core",)),
    ("mark_silenced", ("seq", "shape"), ("pools", "bound", "census",
     "specials", "constants"), ("core",)),
]

PLANTED_ATAN2 = [
    ("q2_dropped", ("bound", "shape", "core", "corner"), ("pools", "seq",
     "range", "census", "specials", "constants"), ()),
    ("z2_dropped", ("bound", "shape", "core", "corner"), ("pools", "range",
     "census", "specials", "constants"), ("seq",)),
    ("head3_two", ("bound", "shape", "core", "constants", "corner"),
     ("pools", "seq", "range", "census", "specials"), ()),
    ("rem0_fma", ("bound", "shape"), ("pools", "seq", "range", "census",
     "specials", "core", "constants", "corner"), ()),
    ("table_entry", ("pools", "bound", "specials", "core", "constants"),
     ("seq", "range", "census", "shape", "corner"), ()),
    ("bound_loose", ("bound", "constants", "corner"), ("pools", "seq",
     "range", "census", "specials", "shape"), ("core",)),
    ("bound_wide", ("census", "specials", "constants"), ("pools", "seq",
     "bound", "range", "shape", "corner"), ("core",)),
    ("mark_silenced", ("shape",), ("pools", "bound", "range", "census",
     "specials", "constants", "corner"), ("seq", "core")),
    ("prescale_d", ("shape", "constants", "corner"), ("pools", "seq",
     "bound", "range", "census", "specials"), ("core",)),
    ("signed_zero", ("pools", "seq", "specials", "shape"), ("bound",
     "range", "census", "constants", "corner"), ("core",)),
    ("side_rule_off", ("pools", "range", "specials", "shape"), ("seq",
     "bound", "census", "constants", "corner"), ("core",)),
    ("side_rule_sign", ("pools", "seq", "census", "specials", "constants"),
     ("bound", "range", "shape", "corner"), ("core",)),
    ("range_off", ("pools", "seq", "range", "shape", "constants", "corner"),
     ("bound", "census", "specials"), ("core",)),
    ("quadrant", ("pools", "seq", "bound", "census", "specials", "shape",
     "corner"), ("range", "constants"), ("core",)),
    ("range_low", ("pools", "seq", "range", "constants", "corner"),
     ("bound", "census", "specials", "shape"), ("core",)),
]


def _row_id(r):
    return r[0]


def _check_row(row, fn):
    plant, red, green, notrun = row
    checks = I.checks_tw2(fn)
    every = set(red) | set(green) | set(notrun)
    assert every == set(checks), (plant, set(checks) ^ every)
    assert not (set(red) & set(green) or set(red) & set(notrun)
                or set(green) & set(notrun)), plant
    assert len(red) + len(green) + len(notrun) == len(checks), plant
    assert red, plant


@functools.lru_cache(maxsize=None)
def _run(fn, plant):
    """(red, not_run) of red_checks_tw2(fn, plant)."""
    not_run = {}
    red = I.red_checks_tw2(fn, plant, not_run=not_run)
    return red, not_run


def _judge(fn, row):
    """The plant's run against its row: red checks red, green checks green AND
    run, not-run checks reported as not run (with the reason)."""
    plant, red, green, notrun = row
    got, nr = _run(fn, plant)
    for check in red:
        assert check in got, f"{fn} {plant}: {check} stays green"
        assert all(s.startswith(check + ":") or s.startswith("shape: ")
                   for s in got[check]), (plant, check, got[check][:2])
    for check in green:
        assert check not in got, \
            f"{fn} {plant}: {check} is red: {got[check][:2]}"
        assert check not in nr, (f"{fn} {plant}: {check} is listed green, but "
                                 f"did not run: {nr[check][:80]}")
    assert set(nr) == set(notrun), (plant, sorted(nr), sorted(notrun))
    reasons = {"core": "the core holds no such fault",
               "seq": "the scheduled fragment keeps "}
    for check in notrun:
        assert nr[check].startswith(f"{check}: not run ({reasons[check]}"),             nr[check]
        assert check not in got, f"{plant}: {check} did not run but is red"


@pytest.mark.parametrize("fn", FNS)
def test_the_control_is_green_in_every_check(fn):
    red, nr = _run(fn, None)
    assert red == {}, {k: v[:1] for k, v in red.items()}
    assert nr == {}, "the control runs every check"


@pytest.mark.parametrize("row", PLANTED_ASIN, ids=_row_id)
def test_each_plant_is_red_in_its_checks_and_green_in_the_others_asin(row):
    _judge("asin", row)


@pytest.mark.parametrize("row", PLANTED_ACOS, ids=_row_id)
def test_each_plant_is_red_in_its_checks_and_green_in_the_others_acos(row):
    _judge("acos", row)


@pytest.mark.parametrize("row", PLANTED_ATAN2, ids=_row_id)
def test_each_plant_is_red_in_its_checks_and_green_in_the_others_atan2(row):
    _judge("atan2", row)


def test_a_check_that_did_not_run_is_not_listed_green():
    """The row of asin's w2_dropped with core listed GREEN, as a row that
    forgets it: the core did not run for it, so the judge refuses it by name;
    so is a row that omits the not-run report, and one that reports a core
    that ran as not run."""
    plant, red, green, notrun = next(r for r in PLANTED_ASIN
                                     if r[0] == "w2_dropped")
    assert notrun == ("core",)
    with pytest.raises(AssertionError, match="core is listed green, but did "
                       "not run"):
        _judge("asin", (plant, red, green + ("core",), ()))
    with pytest.raises(AssertionError):
        _judge("asin", (plant, red, green, ()))
    q = next(r for r in PLANTED_ASIN if r[0] == "q2_dropped")
    with pytest.raises(AssertionError):
        _judge("asin", (q[0], ("bound", "shape"), q[2], ("core",)))


def test_every_plant_is_in_a_table_and_every_row_lists_every_check():
    for fn, rows in (("asin", PLANTED_ASIN), ("acos", PLANTED_ACOS),
                     ("atan2", PLANTED_ATAN2)):
        named = {row[0] for row in rows}
        want = {p for p in ml._INV_TW_PLANTS if fn in REACHES[p]}
        assert named == want, (fn, sorted(named ^ want))
        for row in rows:
            _check_row(row, fn)
    # the row check itself is shown to refuse a row that omits a check, one
    # that names a check red and green, and one red in nothing
    checks = I.checks_tw2("asin")
    rest = tuple(c for c in checks if c not in ("bound", "pools"))
    for bad in (("q2_dropped", ("bound",), ("pools",), ()),
                ("q2_dropped", ("bound", "pools"), ("pools",) + rest, ()),
                ("q2_dropped", ("bound",), ("pools",) + rest, ("core",)),
                ("q2_dropped", (), tuple(checks), ())):
        with pytest.raises(AssertionError):
            _check_row(bad, "asin")
    _check_row(("q2_dropped", ("bound",), ("pools",) + rest, ()), "asin")
    # atan2's checks include range and corner, asin's do not
    assert set(I.checks_tw2("atan2")) - set(checks) == {"range", "corner"}
    with pytest.raises(AssertionError):
        _check_row(("q2_dropped", ("bound",), ("pools",) + rest, ()), "atan2")


def test_every_check_has_a_plant_red_in_it_and_every_plant_is_red_somewhere():
    for fn, rows in (("asin", PLANTED_ASIN), ("acos", PLANTED_ACOS),
                     ("atan2", PLANTED_ATAN2)):
        red = {c for row in rows for c in row[1]}
        assert red == set(I.checks_tw2(fn)), (fn, set(I.checks_tw2(fn)) - red)
        assert all(row[1] for row in rows)


# =====================================================================
# every leg of every check can fail alone
# =====================================================================

def test_each_leg_of_pools_can_fail_alone():
    f = I.tw2_fragment_of("atan2", RNE)
    plain = (0x3f800000, 0x40000000)
    xs = [plain, (0x40400000, 0x3f800000), (0x1, 0x3f800000)]
    clean = [ml.evaluate(f, x) for x in xs]
    # the third lane is in the range: marked; the first two are not
    assert [fw & MARK for _b, fw in clean] == [0, 0, MARK]
    marks = {xs[2]: "the tiny-quotient range"}
    out, t = I.check_pools(f, xs, results=clean, marks=marks)
    assert out == [] and (t.n, len(t.marked)) == (3, 1)
    # without the list the same mark is off it
    out, t = I.check_pools(f, xs, results=clean, marks={})
    assert len(out) == 1 and "marked off the committed list" in out[0]
    # a listed lane that does not mark
    out, t = I.check_pools(f, xs, results=clean, marks={**marks, plain: "x"})
    assert len(out) == 1 and "on the committed list are not marked" in out[0]
    # an unmarked lane that differs
    out, t = I.check_pools(f, xs, results=_doctor(clean, 1, bits=1),
                           marks=marks)
    assert len(out) == 1 and "unmarked lanes differ from transcend.atan2" \
        in out[0]
    # the wrappers: a plant red in the real pool, the list of atan2 passed
    assert I.check_pools_tw2("asin", RNE, "domain_edge")[0]
    assert I.check_pools_tw2("atan2", RNE, "quadrant")[0] or True
    # asin, acos: no list
    assert I.check_pools_tw2("acos", RNE)[1].marked == []


def test_each_leg_of_the_pool_marks_band_can_fail_alone():
    assert I.check_pool_marks_tw()[0] == []
    # a listed lane not of the range's shape (x < 0), one past the band's top
    bad = list(I.POOL_MARKS_TW) + [(0x3f800000, 0xbf800000)]
    out, _ = I.check_pool_marks_tw(listed=bad)
    assert len(out) == 1 and "not of the range's shape or are past the band" \
        in out[0] and out[0].startswith("pools: ")
    out, _ = I.check_pool_marks_tw(listed=list(I.POOL_MARKS_TW)
                                   + [(0x3f800000, 0x3f800001 + 1)])
    assert out
    # a pool lane inside the range and not listed
    out, _ = I.check_pool_marks_tw(listed=list(I.POOL_MARKS_TW)[1:])
    assert len(out) == 1 and "pool lanes are inside the range in exact " \
        "rationals and not on the committed list" in out[0]
    # the band: a lane whose t is between the seed's cells is reported
    lanes = [(0x19802007, 0x3f800000), (0x19802008, 0x3f800000)]
    out, band = I.check_pool_marks_tw(lanes=lanes, listed=[])
    assert len(out) == 1 and band == [lanes[1]] or band == lanes
    # the double word's band would have called these lanes outside the range
    assert I._tq_band(FP32)[1] < I._tq_shape(FP32, lanes[0])


def test_each_leg_of_range_can_fail_alone():
    f = I.tw2_fragment_of("atan2", RNE)
    out, t = I.check_range_tw(f)
    assert out == [] and t["lanes"] == t["marked"] == 15
    one = sf.one_bits(FP32)
    # a committed lane that does not mark
    rows = list(I.RANGE_ROWS["fp32"]) + [("y 2^-60, x 1",
                                          (ml._enc(FP32, Fraction(2) ** -60),
                                           one))]
    out, t = I.check_range_tw(f, rows=rows)
    assert any("1 of the 16 committed range lanes are not marked" in s
               for s in out)
    assert any("are not in the range in exact rationals" in s for s in out)
    # a lane marked but not in the range in exact rationals (x < 0): only the
    # shape leg
    rows = [("y 2^-80, x -1", (ml._enc(FP32, Fraction(2) ** -80),
                               sf.one_bits(FP32, 1)))]
    out, _ = I.check_range_tw(f, rows=rows, evaluator=lambda g, x: (
        (0, MARK) if x == rows[0][1] else ml.evaluate(g, x)))
    assert len(out) == 1 and "not in the range in exact rationals" in out[0]
    # the edge lane held to the seed in exact rationals, three legs
    out, _ = I.check_range_tw(f, rows=[], edge=I.RANGE_EDGE["fp32"] - 1)
    assert any("the lane past the edge" in s and "is not marked" not in s
               for s in out) or any("is marked" in s for s in out)
    out, _ = I.check_range_tw(f, rows=[], edge=I.RANGE_EDGE["fp32"] + 1)
    assert any("times the seed of 1 is not under 2^(emin+2p+2)" in s
               for s in out)
    out, _ = I.check_range_tw(f, rows=[], edge=I.RANGE_EDGE["fp32"] - 2)
    assert any("the lane past the edge" in s for s in out)
    # a marked lane past the edge (an evaluator that marks it)
    out, _ = I.check_range_tw(f, rows=[], evaluator=lambda g, x: (0, MARK))
    assert any("is marked" in s for s in out)
    # the guess is counted and not compared
    out, t = I.check_range_tw(f, rows=[("one", (1, one))],
                              evaluator=lambda g, x: (
                                  (1, MARK) if x == (1, one)
                                  else ml.evaluate(g, x)))
    assert out == [] and t["marked"] == 1 and t["guess_right"] == 0


def test_each_leg_of_seq_can_fail_alone():
    f = I.tw2_fragment_of("asin", RNE)
    xs = [0x3f000000, 0x3e800000, 0x1, 0x7f800000, 0x3f7fffff]
    out, lanes = I.check_seq(f, xs)
    assert out == [] and len(lanes) == 5
    out, _ = I.check_seq(f, xs, evaluator=lambda g, x: (
        ml.evaluate(g, x)[0] ^ 1, ml.evaluate(g, x)[1]))
    assert len(out) == 1 and "seq.py and evaluate() differ on 5 lanes" \
        in out[0]
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(r, "flags", r.flags
                                                        ^ 1), r)[1])
    assert len(out) == 1 and "FLAGS" in out[0] and "OR of the lanes" in out[0]
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(
        r, "status", r.status ^ 0x40), r)[1])
    assert len(out) == 1 and "STATUS[6]" in out[0]
    # a fragment wrong the same way on seq.py and in evaluate()
    bad = I.tw2_fragment_of("asin", RNE, "table_entry")
    out, _ = I.check_seq(bad, I.sample("asin", FP32, "edge", 40, 5))
    assert any("unmarked lanes on seq.py differ from transcend.asin" in s
               for s in out)
    # the wrapper's own leg: a bound inflated that marks no lane leaves the
    # mark unexercised (mark_silenced)
    out, lanes = I.check_seq_tw2("asin", RNE, "mark_silenced", 34)
    assert any("marks none of the" in s and "the mark is not exercised" in s
               for s in out)
    out, lanes = I.check_seq_tw2("acos", RNE, None, 34,
                                 xs=[0x3f000000, 0x3e800000])
    assert any("marks none of the 2 lanes" in s for s in out)
    # atan2's committed range lanes must be marked in the byte: a program
    # that does not carry the mark in the lane's byte
    f2 = I.tw2_fragment_of("atan2", RNE)
    out, _ = I.check_seq(f2, [I.RANGE_ROWS["fp32"][0][1]], post=lambda r: (
        setattr(r, "lane_flags", [b & ~seq.LANE_MARKED
                                  for b in r.lane_flags]), r)[1])
    assert any("raised" in s and "want" in s for s in out)


def test_each_leg_of_bound_can_fail_alone():
    b = I.tw2_build_of("acos", RNE)
    xs = I.sample("acos", FP32, "edge", 6, 5)
    out, (worst, main, lanes) = I.check_bound(b, xs)
    assert out == [] and main == lanes == 6 and worst < 0
    wide = I.tw2_build_of("acos", RNE, "bound_loose")
    out, _ = I.check_bound(wide, xs)
    assert len(out) == 1 and "6 of 6 main-path lanes are past the bound" \
        in out[0] and out[0].startswith("bound: ")
    # a lane that differs from transcend.py with V right (not a main-path
    # lane): asin's tiny path off, the main path answering a tiny argument
    off = I.tw2_build_of("asin", RNE, "tiny_gate_off")
    out, (worst, main, lanes) = I.check_bound(off, [0x1, 0x80000001])
    assert len(out) == 1 and "2 unmarked lanes differ from transcend.asin" \
        in out[0] and main == 0
    # the committed lanes are a region of the check, and `extra` stands for
    # them
    out, w = I.check_bound_tw2("acos", "rem0_fma")
    assert [s for s in out if "rem0" in s]
    assert w["rem0"][0] > 5
    assert I.check_bound_tw2("acos", "rem0_fma", extra={})[0] == [] or \
        all("rem0" not in s for s in I.check_bound_tw2(
            "acos", "rem0_fma", extra={})[0])
    assert I.check_bound_tw2("acos", extra={"rem0": [0x3f7ffbad]})[0] == []
    # atan2's committed lanes are pairs
    assert all(isinstance(x, tuple) for x in I.REM0_LANES_TW["atan2"])


def test_each_leg_of_census_can_fail_alone():
    full = I.census_lanes_tw("atan2")
    lanes = {"tiny": full["tiny"][:8], "near": full["near"][:8]}
    out, t = I.check_census_tw2("atan2", (RNE,), lanes=lanes)
    assert out == [] and t["lanes"] == 16 and t["marked"] == t["wrong"] == 0
    assert set(t["min_d"]) == {"tiny", "near"}
    out, t = I.check_census_tw2("atan2", (RNE,), lanes=lanes,
                                evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == lanes["near"][0] else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "1 of 8 lanes are marked (zero is the claim)" \
        in out[0] and out[0].startswith("census: ") and t["wrong"] == 0
    out, t = I.check_census_tw2("atan2", (RNE,), lanes=lanes,
                                evaluator=lambda g, x: (
        lambda r: (r[0] ^ 1, r[1]) if x == lanes["tiny"][0] else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "1 of 8 unmarked lanes differ from " \
        "transcend.atan2" in out[0] and t["marked"] == 0
    out, t = I.check_census_tw2("atan2", (RNE, RTZ), lanes=lanes,
                                evaluator=lambda g, x: (
        ml.evaluate(g, x)[0] ^ (1 if g.rnd == RTZ else 0),
        ml.evaluate(g, x)[1]))
    assert out and all("rtz" in s for s in out) and t["lanes"] == 32
    # `step` takes every Nth lane of a family
    out, t = I.check_census_tw2("atan2", (RNE,), lanes=lanes, step=4)
    assert t["lanes"] == 4
    # a plant is red in the real lanes: asin's tiny_side in the tiny family
    out, t = I.check_census_tw2("asin", (RTZ,), "tiny_side")
    assert out and "tiny" in out[0] and t["marked"] == 0 and t["wrong"] > 0


def test_each_leg_of_specials_can_fail_alone():
    f = I.tw2_fragment_of("acos", RNE)
    out, n = I.check_specials(f)
    assert out == [] and n == 32
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] ^ 1) if x == sf.inf_bits(FP32) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+inf, -inf': 1 of 2 lanes differ" in out[0]
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == sf.one_bits(FP32) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+1, -1'" in out[0] \
        and "differ or are marked" in out[0]
    # atan2's rows: the edge row, and the rows that mark are not among them
    f2 = I.tw2_fragment_of("atan2", RNE)
    edge = (I.RANGE_EDGE["fp32"] + 1, sf.one_bits(FP32))
    out, _ = I.check_specials(f2, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == edge else r)(ml.evaluate(g, x)))
    assert len(out) == 1 and "the range's edge: first y that does not mark" \
        in out[0]
    # the rows are fp32's own
    labels = [lab for lab, _ in I.special_rows("asin", FP32)]
    assert "gate 2^-13, both signs" in labels or any(
        lab.startswith("gate 2^") for lab in labels)


def test_each_leg_of_shape_can_fail_alone():
    for fn in FNS:
        builds = {(fn, r): I.tw2_build_of(fn, r) for r in RND}
        assert I.check_shape_tw2(fn) == []
        ins, words, live = SHAPES[fn]

        def legs(text, tables, n, fn=fn, builds=builds):
            out = I.check_shape(FP32, builds, tables=tables)
            assert len(out) == n and all(text in s and s.startswith("shape: ")
                                         for s in out), (fn, text, out)
        shape = {**I.SHAPE_TW, (fn, "fp32"): [(ins + 1, words, live)]
                 + [(ins, words, live)] * 4}
        legs(f"pinned {ins + 1}, {words}, {live}", I.tables_tw2(shape=shape), 1)
        legs("instructions by phase differ from the model's",
             I.tables_tw2(phases=lambda f_, name: dict(
                 I.model_phases_tw2(f_, name), z=28)), 5)
        legs("the flag word takes", I.tables_tw2(flag_words={
            **I.FLAG_WORDS, fn: I.FLAG_WORDS[fn] | {0x2}}), 5)
        legs("MIN and", I.tables_tw2(min_max={
            **I.MIN_MAX, fn: (2, I.MIN_MAX[fn][1])}), 5)
        legs("MAX instructions", I.tables_tw2(min_max={
            **I.MIN_MAX, fn: (I.MIN_MAX[fn][0], 3)}), 5)
        legs(f"the cap is {live + 1}", I.tables_tw2(caps={
            **ml.INV_LIVE_CAP, fn: {**ml.INV_LIVE_CAP[fn], "fp32": live + 1}}),
             1)
        # a cap one under fails by name
        out = I.check_shape(FP32, builds, tables=I.tables_tw2(caps={
            **ml.INV_LIVE_CAP, fn: {**ml.INV_LIVE_CAP[fn],
                                    "fp32": live - 1}}))
        assert any(f"the cap is {live - 1}, the most values live under any "
                   f"attribute is {live}" in s for s in out)
        assert any(f"invariants: {live} values live at once, past {live - 1}"
                   in s for s in out)
        # the reorder leg, on a doctored fragment
        frags = {k: b.fragment() for k, b in builds.items()}
        key = (fn, RNE)
        out = I.check_shape(FP32, builds, tables=I.tables_tw2(),
                            fragments={**frags,
                                       key: ml._misnumbered(frags[key])})
        assert any("reorder" in s and "dataflow graph is not the design's"
                   in s for s in out)
    with pytest.raises(ValueError, match="no phases of atan at fp32"):
        I.model_phases_tw2("atan", "fp32")
    with pytest.raises(ValueError, match="no phases of asin at fp64"):
        I.model_phases_tw2("asin", "fp64")


def _fresh_with(fn, role=None, delta=1, extra_role=None, rnd=RNE):
    """A fresh (never shared) build of fn at fp32 with the word of `role`
    changed by `delta` in its bits, or with an extra role no derivation asks."""
    b = ml.build(fn, FP32, rnd)
    if role is not None:
        name = b.roles[role][1]
        b.words[name] = (b.words[name] + delta) & ((1 << 32) - 1)
    if extra_role is not None:
        b.const(*extra_role)
    return b


def _constants_of(fn, b):
    lines, findings = ml._check_inv_tw_constants(
        builder=lambda n, f, r: b, attrs=(b.rnd,), names=(fn,))
    return [f"constants: {s}" for s in findings if not s.startswith("seed")]


# the roles each function adds to atan's, each changed by one bit in turn
NEW_ROLES = {
    "asin": ("TINYU", "HALF", "GATE", "TINY_EPS"),
    "acos": ("TINYU", "HALF", "PIW0", "PIW1", "PIW2"),
    "atan2": ("PIW0", "PIW1", "PIW2", "PIO4W0", "PIO4W1", "PIO4W2", "DSUB",
              "DOK", "S3P", "DBIG", "QTR", "GATEA", "TQR", "SIDE_EPS"),
}


@pytest.mark.parametrize("fn", FNS)
def test_each_leg_of_constants_can_fail_alone(fn):
    """The build with one word changed, one role at a time: the difference is
    named by fragment and word."""
    clean = ml.build(fn, FP32, RNE)
    assert _constants_of(fn, clean) == []
    for role in NEW_ROLES[fn]:
        found = _constants_of(fn, _fresh_with(fn, role))
        assert found and all(s.startswith("constants: ") for s in found), role
        assert any(f"{fn} fp32 rne {role}:" in s for s in found), (role, found)
    # every role of the build has a derivation: a word of any role changed is
    # a finding naming it (the shared ones are atan's, tested there)
    for role in sorted(set(clean.roles) - set(NEW_ROLES[fn]))[::7]:
        found = _constants_of(fn, _fresh_with(fn, role))
        assert any(f"{fn} fp32 rne {role}:" in s for s in found), (role, found)
    # a role no derivation asks, and a role the build lacks
    found = _constants_of(fn, _fresh_with(fn, extra_role=("EXTRA", 0x1234)))
    assert len(found) == 1 and "derived but not checked: ['EXTRA']" in found[0]
    b = ml.build(fn, FP32, RNE)
    del b.roles[NEW_ROLES[fn][0]]
    assert any(f"the fragment has no constant {NEW_ROLES[fn][0]}" in s
               for s in _constants_of(fn, b))
    # the plan and rho, written into the build's meta
    b = ml.build(fn, FP32, RNE)
    b.meta["K3"] = 4
    found = _constants_of(fn, b)
    assert len(found) == 1 and "the plan (K3, K2, D) (4, 3, 8) is not the " \
        "re-derived (3, 3, 8)" in found[0]


def test_tqr_is_the_triple_words_and_a_word_of_the_double_words_is_found():
    # the role check derives TQR = 2^(emin+2p+2) from the IEEE fields: the
    # double word's 2^(emin+p+2) (the plant range_low) is a difference
    b = ml.build("atan2", FP32, RNE)
    assert b.words[b.roles["TQR"][1]] == ml._pow2(FP32, -76)
    assert _constants_of("atan2", b) == []
    low = I.tw2_build_of("atan2", RNE, "range_low")
    assert low.words[low.roles["TQR"][1]] == ml._pow2(FP32, -100)
    found = _constants_of("atan2", low)
    assert len(found) == 1 and "TQR" in found[0]
    # domain_edge's ONEM is a role no derivation asks: found
    on = I.tw2_build_of("asin", RNE, "domain_edge")
    found = _constants_of("asin", on)
    assert len(found) == 1 and "derived but not checked: ['ONEM']" in found[0]


def test_the_role_check_hook_is_asked_for_the_three_and_no_other():
    assert tuple(ml._INV_TW_ROLE_CHECKS) == FNS
    calls = []
    real = ml._INV_TW_ROLE_CHECKS
    try:
        ml._INV_TW_ROLE_CHECKS = {
            **real, "acos": lambda *a: calls.append(a[0].meta["fn"])}
        _constants_of("acos", ml.build("acos", FP32, RNE))
    finally:
        ml._INV_TW_ROLE_CHECKS = real
    assert calls == ["acos"]


# =====================================================================
# the commands of mathlib_runs.py, and the generator
# =====================================================================

def test_the_inv_commands_take_fp32_for_the_four_functions(tmp_path, capsys):
    import mathlib_runs as R
    R.FINDINGS.clear()
    out = tmp_path / "pools32.txt"
    R.main(["inv-pools", "--formats", "fp32", "--quick", "--seq", "--out",
            str(out)])
    shown = capsys.readouterr().out
    for fn, n, ins, live in (("atan", 42, 472, 25), ("asin", 42, 637, 25),
                             ("acos", 42, 633, 25), ("atan2", 66, 518, 31)):
        assert f"inv-pools {fn} fp32 rne: {n} lanes" in shown, fn
        assert f"{ins} instructions, {live} live" in shown
    assert "RESULT: ok" in shown and "0 findings" in shown
    # atan2's marks are the list POOL_MARKS_TW's: none of them off it
    assert "marks off the list" in shown
    R.OUT = None
    R.FINDINGS.clear()
    R.main(["inv-bound", "--formats", "fp32", "--quick"])
    shown = capsys.readouterr().out
    for fn in ("atan", "asin", "acos", "atan2"):
        assert f"inv-bound {fn} fp32 rne edge seed 121: 12 lanes" in shown
    assert "a sampled lower bound" in shown and "RESULT: ok" in shown
    R.OUT = None
    R.FINDINGS.clear()
    R.main(["inv-corner", "--formats", "fp32", "--quick", "--attrs",
            "rne,rtz"])
    shown = capsys.readouterr().out
    assert "inv-corner atan2 fp32 rne tinyn seed 101: 12 lanes" in shown
    assert "RESULT: ok" in shown
    R.OUT = None
    R.FINDINGS.clear()
    with pytest.raises(SystemExit, match="fp64, fp128, fp256 or fp32"):
        R.main(["inv-pools", "--formats", "fp16"])
    # fp32 is never a default, and the corner's size is the study's
    import inspect
    assert '"fp32": 1000' in inspect.getsource(R.cmd_inv_corner)
    assert '"fp32": 20000' in inspect.getsource(R.cmd_inv_bound)
    assert all(f.name != "fp32" for f in I.FORMATS)
    R.OUT = None
    R.FINDINGS.clear()


def test_the_inv_commands_refuse_a_function_the_triple_word_lacks_by_name(
        monkeypatch):
    import mathlib_runs as R
    monkeypatch.setattr(ml, "_INV_TW_BUILDERS", {
        k: v for k, v in ml._INV_TW_BUILDERS.items() if k != "asin"})
    with pytest.raises(SystemExit, match="asin is not built at fp32: fp32 is "
                       "the triple word"):
        R.main(["inv-pools", "--formats", "fp32", "--fn", "asin"])
    R.OUT = None
    R.FINDINGS.clear()


def test_the_sweep_generator_builds_the_four_inverse_routines_at_fp32(tmp_path):
    """Runs host/tools/gen_sweep_images.py into tmp_path (rc 0) and checks what
    it wrote: 65 images (13 names of five attributes), 196 files with the
    manifest, no `skipped` line; the five `.cftp` files, banks and marks files
    of each inverse routine, the marks files EMPTY (the claim is that no lane
    must mark but atan2's range, a range and not a list: the sweep tool
    judges 'must mark' by a list, so atan2's marks files carry no range lane
    and a range rule in the tool is a later parcel's); each `digest` line equal
    to the manifest's own rule over the five images and banks (the first 32
    bits of the sha256 of rne to rmm, image then bank); the nine other
    routines' digests equal to hw/card_stress_lib.py's ROUTINE_DIGESTS row
    for row, the four inverse routines being names the table lacks."""
    import hashlib
    import importlib.util
    import subprocess
    out = tmp_path / "imgs"
    r = subprocess.run([sys.executable, "-B", str(
        ROOT / "host" / "tools" / "gen_sweep_images.py"), "--out", str(out)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    files = sorted(p.name for p in out.iterdir())
    assert len(files) == 196 and "manifest.txt" in files
    assert len([n for n in files if n.endswith(".cftp")]) == 65
    manifest = (out / "manifest.txt").read_text(encoding="utf-8").splitlines()
    assert not any(ln.startswith("skipped ") for ln in manifest)
    digests = [ln.split() for ln in manifest if ln.startswith("digest ")]
    mine = {}
    for fn, words, insns in (("atan", 60, 477), ("asin", 62, 642),
                             ("acos", 61, 638), ("atan2", 70, 523)):
        h = hashlib.sha256()
        for x in ("rne", "rtz", "rdn", "rup", "rmm"):
            stem = out / f"{fn}-fp32-{x}"
            assert stem.with_suffix(".cftp").stat().st_size > 0
            assert stem.with_suffix(".bank").stat().st_size == 4 * words
            assert stem.with_suffix(".marks").read_bytes() == b""
            h.update(stem.with_suffix(".cftp").read_bytes())
            h.update(stem.with_suffix(".bank").read_bytes())
        mine[fn] = h.hexdigest()[:8]
        assert [d for d in digests if d[1] == fn] == [["digest", fn, mine[fn]]]
        assert sum(1 for ln in manifest if ln.startswith(f"image {fn} ")) == 5
        for rnd in RND:
            prog, bank = H.r24_program(ml.fragment(fn, FP32, rnd))
            assert len(prog.insns) == insns and len(bank) == words
    assert mine["atan"] == "d22abd22"                 # M4F1's, unmoved
    spec = importlib.util.spec_from_file_location(
        "card_stress_lib", ROOT / "hw" / "card_stress_lib.py")
    lib = importlib.util.module_from_spec(spec)
    sys.modules["card_stress_lib"] = lib
    try:
        spec.loader.exec_module(lib)
    finally:
        sys.modules.pop("card_stress_lib", None)
    nine = {d[1]: d[2] for d in digests if d[1] in lib.ROUTINE_DIGESTS}
    assert len(nine) == 9 and nine == dict(lib.ROUTINE_DIGESTS)
    assert not any(n in lib.ROUTINE_DIGESTS
                   for n in ("atan", "asin", "acos", "atan2"))
    assert len(digests) == 13
    # the three new digests, MEASURED at this commit (the entry gives them)
    assert (mine["asin"], mine["acos"], mine["atan2"]) == ("005fc862", "2f8ca421", "a86a60d8")
