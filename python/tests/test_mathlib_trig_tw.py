# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""fp32's sin, cos and tan, the triple word at G = 40 (parcel M2F2, M2's build,
wave 3): python/cft_golden/mathlib.py's _build_trig_tw, parcel M2X's model
(docs/studies/m2/tw32.py) ported onto parcel M2F1's reduction and M2G2a's
trig_after. The model is NOT imported here (nothing in the tree imports it):
what it computed is recorded below, READ from its outputs (tw32_costs.out.txt,
tw32_anchors.out.txt, tw32_live.out.txt) or MEASURED by running it, and the
port is held to those; the run that put the port beside the model lane for
lane is in docs/VALIDATION.md.

HOW fp32 JOINS THE TESTS (the brief's choice, argued). fp32 has a file of its
own, and the harness's FORMATS stay the double word's three
(mathlib_trig_harness.ALL_FORMATS adds fp32 for the box commands). test_
mathlib_trig.py's 242 parametrized tests, pinned lists and 18 statistics are
therefore as they were but for the pins the brief's own changes force (the
phase order, the "4 formats" of `--check`, the fp32 refusals, the cap's key set,
the `--only trig` listing and TRIG_FAMILY's cell count), and nothing of them is
weakened. The price is that the harness's checks are called here again for
one format; the benefit is that fp32's legs which run NO LANE at G = 40 (the
structured, family and window legs: the theory finds no centre) are named and
replaced by legs that can fail, not carried along as passes with none run.

The legs, each able to fail alone (the plant table says which plant turns
which red):
  shape      the 15 fragments against the model: instructions, bank words,
             live values, instructions by phase, the 28 static proofs by name,
             the error-free transformations, the claims, the dag fingerprint
  pools      the 760 radian arguments through the fragments: 0 wrong, 0 marked
  seq        the fragments as programs on seq.py
  bound      |V - f(x)| / Bv under 1 at the study's five regions, the deepest
             cancellations and parcel M2X's sixth region, quad
  budget     the first-order budget on the real triple word, at the model's own
             anchor lanes to the digits
  rate       the mark-rate law at G' = 6
  audit      every Fast2Sum and every claim of the whole routine, lane by lane
  constants  `--check`: every coefficient word, the plan and rho re-derived
  family     the lanes the theory finds at G = 18 (the double word's) next to
             its centres, run through the G = 40 fragment: none may mark
  census_counts  the census (48 arguments at G = 40; the double word's 144) :
             none marked, and the zeros pinned
"""

import copy
import functools
import hashlib
import pathlib
import random
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

import mathlib_harness as H  # noqa: E402
import mathlib_trig_budget as TB  # noqa: E402
import mathlib_trig_family as TF  # noqa: E402
import mathlib_trig_harness as T  # noqa: E402
import test_mathlib_reduction as RT  # noqa: E402
import test_mathlib_reduction_tw as W  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
FMT = FP32
G = ml.GUARD["fp32"]                                   # 40
FUNCS = T.FUNCS
RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = T.RNE, T.RTZ, T.RDN, T.RUP, T.RMM


def rid(r):
    return sf.RND_NAMES[r]


# ---- what the model states and measured (READ, MEASURED on the model) --------

INSTRUCTIONS = {"sin": 939, "cos": 936, "tan": 993}      # every attribute
# TwoSum, Fast2Sum, TwoProd (tw32_costs.out.txt)
EFT = {"sin": (69, 29, 40), "cos": (69, 29, 40), "tan": (73, 30, 42)}
# the instructions claimed exact: 64 of the reduction and 27 Fast2Sums' two
# each (tw32_pools-audit.out.txt: 118, 118, 120), and the 13 data claims
CLAIMS = {"sin": 118, "cos": 118, "tan": 120}
# the 15 Fast2Sum orderings of the heads, after the reduction's 13 proofs
HEAD_PROOFS = ([f"S k={k}: |c_k| > |z y| (Fast2Sum ordered)"
                for k in range(6, -1, -1)]
               + [f"C k={k}: |c_k| > |z y| (Fast2Sum ordered)"
                  for k in range(7, -1, -1)])
PLAN = ((4, 3, 9), (5, 3, 9))                # (K3, K2, D) of S and of C
# sha256 of the 15 fragments' dag digests, sorted, one a line
# (tw32_costs.out.txt:113): the port's, MEASURED equal
FINGERPRINT = "090e33b8ae85dcb40323dc4e08c392065a60249d6da5e3b4373cd55f97b79c26"
# the model's budget over the 34 anchor lanes, both signs (tw32_anchors.out.txt,
# tw32_run.py's ANCHORS): the largest error, the method error, the second-order
# residual and the bound, as the model printed them
ANCHORS = ([0x3f490fdb + j for j in range(-3, 4)]
           + [0x44264edd + j for j in range(-2, 3)]
           + [0x4bb9109b, 0x7bdd447c, 0x63d8c0f2, 0x73fa22b3, 0x5b90c020])
MODEL_ANCHORS = {"sin": ("0.09461", "0.08617", "0.000326", "0.1707"),
                 "cos": ("0.08911", "0.08626", "0.000462", "0.1762"),
                 "tan": ("0.1202", "0.0871", "0.000747", "0.2306")}
# the base's fingerprints (sha256 of the sorted dag digests), RECORDED at
# 77dfc230, the merge of parcel M2F1, by `git archive`: the six's 120
# fragments, M2G2a's 45 (by format) and M2G1's 20 reduction builds. Parcel M2F2
# moves none of them
BASE = {"six": "654e47f47527d004f9183954b4d860109751462cc0f85b78157e97143b0d8636",
        "fp64": "319f8387a83485c62da7583bbafc81628d0adfefc47a217feda9d2031a3780d2",
        "fp128": "f0da5743ebf0e39faac4aacb67f31ce0c3be65f93e77e979cd2bcddc35556dbf",
        "fp256": "51d12b3332af932bd99d44a22a4bbdc3f46c1b4041c7e439a79240cd0b508a8e",
        "reduction": "ed4a917fe60ddc2a5577b4dfae1d5bc438157b6a4b708017d0cd5c1e5fa8d44a"}
# the rate cells (3 functions, rne and rtz): 720 lanes at seed 7, judged as the
# 6 statistics they are, never added to test_mathlib_trig.py's 18
RATE_N, RATE_SEED = 720, 7
RATE_STATISTICS = H.rate_statistics(FUNCS, (FMT,), (RNE, RTZ))
POOL_N, SLICE_N = 760, 163


def fingerprint(digests):
    return hashlib.sha256("\n".join(sorted(digests)).encode()).hexdigest()


@functools.lru_cache(maxsize=None)
def build_of(fn, rnd, plant=None):
    return T.build_of(fn, FMT, rnd, plant)


def all_builds(plant=None, fn=None):
    """The 15 builds, `plant` in the one function `fn` where given."""
    return {(f, r): build_of(f, r, plant if f == fn else None)
            for f in FUNCS for r in RND}


# =====================================================================
# the build is the model's
# =====================================================================

def test_the_fifteen_fragments_are_the_models():
    """939, 936 and 993 instructions under every attribute, the model's bank
    words, its instructions by phase, 23 values live in the design's order and
    scheduled, TwoSum / Fast2Sum / TwoProd, the claims, the 28 static proofs
    by name in order, the plan, the cap, routines.program accepting both
    orders (30 of 30), and the 15 dag digests' fingerprint the model's."""
    builds = all_builds()
    assert T.check_shape(FMT, builds) == []              # the harness's legs
    digests = []
    for (fn, r), b in sorted(builds.items()):
        f, g = b.fragment(schedule=False), b.fragment()
        where = (fn, rid(r))
        assert len(f) == len(g) == INSTRUCTIONS[fn], where
        assert (b.meta["two_sum"], b.meta["fast_two_sum"],
                b.meta["two_prod"]) == EFT[fn], where
        assert (len(b.meta["exact"]), len(b.meta["data"])) == (CLAIMS[fn], 13)
        assert b.meta["proofs"] == W.PROOFS + HEAD_PROOFS, where
        assert (b.meta["family"], b.meta["G"], b.meta["R"]) == (
            "triple word", G, None)
        assert b.meta["poly"] == PLAN and (b.meta["KS"], b.meta["DS"],
                                           b.meta["KC"], b.meta["DC"]) == (
            7, 9, 8, 9)
        assert f.live_max() == g.live_max() == 23, where
        assert ml.invariants(g) == [] and ml.invariants(f) == [], where
        for h in (f, g):                          # both orders fit the registers
            prog, bank = routines.program(h)
            assert len(bank) == len(h.words)
        digests.append(ml.dag_digest(f))
        assert ml.dag_digest(g) == digests[-1]
    assert fingerprint(digests) == FINGERPRINT
    assert ml.TRIG_FORMATS == (FP64, FP128, FP256, FP32)
    assert ml.TRIG_LIVE_CAP["sin"]["fp32"] == ml.TRIG_LIVE_CAP["cos"]["fp32"] \
        == ml.TRIG_LIVE_CAP["tan"]["fp32"] == 23


def test_the_flag_words_and_the_words_are_the_models():
    """The flag word takes the study's values (sin and tan {0x0, 0x1, 0x10,
    0x18, 0x90}, cos without 0x18) and the bank words are 99, 96 and 96 over
    the five attributes of each function and 102 over all fifteen."""
    words, per = set(), {}
    for fn in FUNCS:
        per[fn] = set()
        for r in RND:
            f = ml.fragment(fn, FMT, r)
            assert routines.flag_words(f) == T.FLAG_WORDS[fn], (fn, rid(r))
            per[fn] |= set(f.words.values())
        words |= per[fn]
    assert {fn: len(w) for fn, w in per.items()} == {"sin": 99, "cos": 96,
                                                     "tan": 96}
    assert len(words) == T.UNION_WORDS["fp32"] == 102


def test_the_cap_has_no_slack_and_the_default_form_of_abs_costs_a_value(
        monkeypatch):
    """23 is the measured maximum of all 15, and the cap of 23 has no slack: a
    classification that forms |x| as trig_after does by default, iand(x,
    ABSM), SHARES red-small's instruction (Build.ins hash-conses) and holds |x|
    live from the reduction to the end: 24 live and 938, 934 and 992
    instructions (parcel M2F1 MEASURED the same on the model with that one
    line changed). fp32's builder passes abs_by_xor, the model's
    ixor(x, iand(x, SIGN)); the default stays for M2G2a's 45 (BASE)."""
    for fn in FUNCS:
        lives = {ml.fragment(fn, FMT, r).live_max() for r in RND}
        assert lives == {23}
    real = ml.trig_after
    seen = []

    def default_form(b, fn, x, q, s, c, **kw):
        seen.append(kw.pop("abs_by_xor"))
        return real(b, fn, x, q, s, c, **kw, abs_by_xor=False)
    monkeypatch.setattr(ml, "trig_after", default_form)
    for fn, want in (("sin", 938), ("cos", 934), ("tan", 992)):
        b = ml.build(fn, FMT, RNE)
        f, g = b.fragment(schedule=False), b.fragment()
        assert len(f) == want and f.live_max() == g.live_max() == 24, fn
        assert ml.invariants(g) == [f"24 values live at once, past 23"]
    assert seen == [True] * 3                   # fp32's builder asks for it


def test_nothing_else_moved_the_base_fingerprints():
    """Switches off, nothing moves (the brief's 6): the six's 120 fragments,
    M2G2a's 45 and M2G1's 20 reduction builds have the dag digests they had at
    77dfc230 (BASE; MEASURED also, in the entry, by the scheduled bodies: 185
    of 185 identical)."""
    got = {k: [] for k in BASE}
    for name in ml.NAMES:
        for fmt in ml.FORMATS:
            for r in RND:
                got["six"].append(ml.dag_digest(ml.fragment(name, fmt, r)))
    for name in ml.TRIG_NAMES:
        for fmt in (FP64, FP128, FP256):
            for r in RND:
                got[fmt.name].append(ml.dag_digest(ml.fragment(name, fmt, r)))
    for fmt in ml.FORMATS:
        for r in RND:
            b = (ml.build_reduction(fmt, r, G=18) if fmt is FP32
                 else ml.build_reduction(fmt, r))
            got["reduction"].append(ml.dag_digest(b.fragment()))
    assert {k: fingerprint(v) for k, v in got.items()} == BASE
    assert [len(got[k]) for k in BASE] == [120, 15, 15, 15, 20]


def test_each_leg_of_shape_can_fail_alone_at_fp32():
    builds = all_builds()
    assert T.check_shape(FMT, builds) == []

    def legs(text, tables, n):
        out = T.check_shape(FMT, builds, tables=tables)
        assert len(out) == n and all(text in s and s.startswith("shape: ")
                                     for s in out), (text, out)
    shape = dict(T.SHAPE)
    shape[("sin", "fp32")] = [(940, 97, 23)] + T.SHAPE[("sin", "fp32")][1:]
    legs("pinned 940, 97, 23", T.Tables(shape=shape), 1)
    shape[("sin", "fp32")] = [(939, 97, 22)] + T.SHAPE[("sin", "fp32")][1:]
    legs("pinned 939, 97, 22", T.Tables(shape=shape), 1)
    legs("instructions by phase differ from the model's",
         T.Tables(phases=lambda fn, name: dict(T.port_phases(fn, name), z=6)
                  if fn == "sin" else T.port_phases(fn, name)), 5)
    legs("the flag word takes", T.Tables(flag_words=dict(
        T.FLAG_WORDS, sin=T.FLAG_WORDS["sin"] | {0x2})), 5)
    legs("MIN and", T.Tables(min_max=dict(T.MIN_MAX, cos=(1, 2))), 5)
    # a cap above the maximum is refused (no slack), one below fails the cap
    legs("the cap is 24, the most values live under any attribute is 23",
         T.Tables(caps={**ml.TRIG_LIVE_CAP, "sin": {
             **ml.TRIG_LIVE_CAP["sin"], "fp32": 24}}), 1)
    out = T.check_shape(FMT, builds, tables=T.Tables(caps={
        **ml.TRIG_LIVE_CAP, "tan": {**ml.TRIG_LIVE_CAP["tan"], "fp32": 22}}))
    assert any("a cap one under (22)" not in s and "the cap is 22" in s
               for s in out)
    assert any("invariants: 23 values live at once, past 22" in s for s in out)
    legs("bank words over the three functions", T.Tables(
        union=dict(T.UNION_WORDS, fp32=101)), 1)
    legs("of one argument are", T.Tables(shared=dict(T.SHARED, fp32=1089)), 5)
    assert T.SHARED["fp32"] == 1088          # tw32_share.out.txt: 1,088


# =====================================================================
# the lanes: pools, seq, specials, bound
# =====================================================================

@pytest.mark.parametrize("fn", FUNCS)
def test_pools(fn):
    """The 760 radian arguments (parcel M2X's pools) under rne: every unmarked
    lane equal to transcend.py in bits and flag word, and ZERO marked: the
    double word's cos marked 4 a configuration there, at G = 40 none does. The
    committed list of marks is empty (a claim: pinned), so any mark is one off
    the list. The other four attributes run the slice (next test); the box runs
    all 15 configurations whole (trig-pools --formats fp32 --seq)."""
    rnd = RNE
    f = ml.fragment(fn, FMT, rnd)
    out, t = T.check_pools(f)
    assert out == [], out
    assert t.n == POOL_N == len(T.radian_pools(FMT))
    assert not t.marked and not t.range_marked and not t.range_unmarked
    assert not t.wrong and not t.guess_wrong and not t.off and not t.missing
    assert T.pool_marks(fn, "fp32", rid(rnd)) == {}


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("rnd", [RTZ, RDN, RUP, RMM], ids=rid)
def test_pools_slice_under_the_other_attributes(fn, rnd):
    out, t = T.check_pools(ml.fragment(fn, FMT, rnd),
                           xs=list(T.pool_slice(FMT)))
    assert out == [] and t.n == SLICE_N and not t.marked


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("rnd", [RNE, RTZ], ids=rid)
def test_seq(fn, rnd):
    """The fragment as a stand-alone program on seq.py and as the compiled
    shape (QUIET, the body, ENDQUIET, RAISE): the slice (163, every fourth
    under rtz), equal to evaluate() lane by lane and to transcend.py where
    unmarked."""
    xs = list(T.pool_slice(FMT))[::1 if rnd == RNE else 4]
    out, lanes = T.check_seq(ml.fragment(fn, FMT, rnd), xs=xs)
    assert out == [], out
    assert len(set(lanes)) == len(lanes) == len(xs)  # no structured lane at fp32


@pytest.mark.parametrize("fn", FUNCS)
def test_specials(fn):
    for rnd in RND:
        out, n = T.check_specials(ml.fragment(fn, FMT, rnd))
        assert out == [], out
        assert n == 24                               # 9 rows, no range rows
    assert [len(l) for _a, _b, l in T.special_rows(FMT)] == [
        2, 2, 2, 2, 4, 2, 4, 4, 2]
    assert {k for _l, k, _x in T.special_rows(FMT)} == {"equal"}


@pytest.mark.parametrize("fn", FUNCS)
def test_bound(fn):
    """|V - f(x)| / Bv under 1 at 64 placed points of each of the study's five
    regions, at the deepest cancellations (all inside: fp32 has no range) and
    at parcel M2X's sixth region, quad (the floats next to the odd multiples
    of pi/4 from k = 0; numpy), each lane also against transcend.py. The
    sampled worst keeps the model's margin (the budget's 0.43 Bv at most)."""
    b = build_of(fn, RNE)
    worst = -1e9
    regions = [(r, T.sample(FMT, r, 64, 5)) for r in T.REGIONS]
    try:
        import numpy  # noqa: F401
        regions.append(("quad", T.sample(FMT, "quad", 64, 5)))
    except ImportError:
        pass
    for region, xs in regions:
        out, (w, main, lanes) = T.check_bound(b, xs, region)
        assert out == [], out
        assert lanes == 64 and main > 0
        worst = max(worst, w)
    deep = list(T.deepest_in_range(FMT))
    assert deep == list(T.deepest(FMT)) and len(deep) == 48
    out, (w, main, lanes) = T.check_bound(b, deep, "deepest")
    assert out == [] and main == lanes == 48
    assert max(worst, w) < -2.0, max(worst, w)


def test_bound_log2_sums_all_three_words_of_v():
    """bound_log2 sums V0, V1 and V2: a triple word has no Vl, and the sum of
    two words alone (V0 + V1) leaves V2 as an error of about 2^-48 of V, past
    2^+8 Bv at fp32 where the real error is under 2^-3."""
    import mpmath
    b = build_of("sin", RNE)
    x = 0x3f800000                                           # 1.0
    _r, _f, pr = b.run(x, ("V0", "V1", "V2", "Bv"))
    assert "Vl" not in b.probes and T.v_names(b) == ("V0", "V1", "V2")
    assert T.v_names(ml.build("sin", FP64, RNE)) == ("Vh", "Vl")
    got = T.bound_log2(b, x)
    assert got < -3.0
    with mpmath.workprec(4 * 24 + 200):
        true = T.true_value("sin", Fraction(1))
        v = [T.value(FMT, pr[k]) for k in ("V0", "V1", "V2")]
        bv = T._mp(abs(T.value(FMT, pr["Bv"])))
        three = abs(T._mp(sum(v)) - true) / bv
        two = abs(T._mp(v[0] + v[1]) - true) / bv
        assert abs(float(mpmath.log(three, 2)) - got) < 1e-6
        assert float(mpmath.log(two, 2)) > 8 > got      # the dropped word


def test_the_quad_region_is_the_models():
    """tw32.quad_sample's population: 18,266 arguments (tw32_box.sh), both
    signs, drawn by the seed; fp32's alone."""
    pytest.importorskip("numpy")
    fam = T.quad_sample(FMT, 10 ** 9, 1)
    assert len(fam) == 18266 and fam == sorted(set(fam))
    xs = T.sample(FMT, "quad", 50, 126)
    assert xs == sorted(random.Random(126).sample(fam, 50))
    with pytest.raises(ValueError, match="fp32's"):
        T.sample(FP64, "quad", 4, 1)
    assert T.REGIONS_TW == T.REGIONS + ("quad",)


# =====================================================================
# the audit, the constants, the plan
# =====================================================================

def test_the_audit_of_the_whole_routine_is_empty():
    """Every instruction the routine calls exact, the reduction's 64 and the
    Fast2Sums of the heads, of sin(r0) and of the quotient (118, 118 and 120),
    on the slice and on every third (every fifth for cos and tan) of the
    products' binade edges (the lanes the exact-add / carry-dropped plants
    need), 0 lanes with a claim that fails."""
    edges = list(RT.edge_args(FMT, W.plan_tw()))
    assert len(edges) == 940
    for fn in FUNCS:
        b = build_of(fn, RNE)
        assert len(b.meta["exact"]) == CLAIMS[fn]
        xs = list(T.pool_slice(FMT)) + edges[::3 if fn == "sin" else 5]
        out, tally = T.check_audit(b, xs)
        assert out == [], out
        main = sum(1 for x in xs if ml._main_lane(FMT, W.plan_tw(), x))
        assert tally["claims"] == CLAIMS[fn] * len(xs)
        assert tally["claims"] - tally["skipped"] == CLAIMS[fn] * main
        assert main > len(xs) // 2 and tally["nonfinite"] == 0


def test_constants_in_process_and_as_a_program():
    findings, lines = T.check_constants(formats=(FMT,))
    assert findings == [] and len(lines) == 3
    for fn in FUNCS:
        assert any(ln.startswith(f"{fn} fp32: G = 40, plan S (7, 9) = 4 "
                                 f"triple + 3 double word steps, C (8, 9) = "
                                 f"5 + 3: ") for ln in lines)
    b = build_of("sin", RNE)
    assert {"S_Y8", "S_CH6", "S_CL6", "S_CH3", "S_CL3", "S_CT3", "S_CT1",
            "C_Y8", "C_CH7", "C_CT4", "NHALF", "MQ_MID", "PIO2_2", "CHUNK14",
            "GATE", "BREL", "U1", "L1", "TINY_EPS", "MINN"} <= set(b.roles)
    assert "CHUNK15" not in b.roles          # 18 words of 2/pi, 3 of them zero
    # a coefficient exact in one word holds no low word: S k=0 is 1, C k=1 is
    # -1/2, C k=0 is 1; S k=1 is -1/6, which needs all three
    assert not {"S_CL0", "S_CT0", "C_CL1", "C_CT1", "C_CL0", "C_CT0"} \
        & set(b.roles) and {"S_CL1", "S_CT1"} <= set(b.roles)
    # the listing (`--only trig`) takes the four formats; the check's own line
    # and exit code are test_mathlib_trig.py's, pinned there at "4 formats"
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert ml.main(["--only", "trig"]) == 0
    rows = [ln.split() for ln in buf.getvalue().splitlines()]
    assert len(rows) == 1 + 60
    assert ["sin", "fp32", "rne", "939", "97", "23", "23"] in rows
    assert ["cos", "fp32", "rtz", "936", "95", "23", "23"] in rows
    assert ["tan", "fp32", "rmm", "993", "96", "23", "23"] in rows


def _constants_of(b):
    findings = []
    ml._check_trig_build(b, findings, ml._clean_reduction_words(FMT))
    return findings


def test_each_leg_of_the_fp32_constants_can_fail_alone():
    """One word of a fresh fp32 build altered (its bits + 1), the finding
    names the role; a role no derivation asks, a third word held where the
    coefficient is exact in two, the plan, rho and the cushion each fail."""
    for role in ("S_Y8", "S_CH6", "S_CL6", "S_CH2", "S_CL2", "S_CT2", "C_CH5",
                 "C_CL4", "C_CT3", "NHALF", "PIO2_2", "MQ_MID", "CHUNK9",
                 "BREL", "GATE", "TINY_EPS"):
        b = ml.build("sin", FMT, RNE)
        b.words[b.roles[role][1]] += 1
        found = _constants_of(b)
        assert any(f" {role}: " in s or f" {role} " in s for s in found), \
            (role, found[:2])
    found = _constants_of(ml.build("sin", FMT, RNE))
    assert found == []
    b = ml.build("sin", FMT, RNE)
    b.roles["EXTRA"] = b.word(0x1234, "EXTRA")
    found = _constants_of(b)
    assert len(found) == 1 and "derived but not checked: ['EXTRA']" in found[0]
    b = ml.build("sin", FMT, RNE)
    b.roles["S_CT0"] = b.word(0x3c90000000 & 0xffffffff, "S_CT0")
    found = _constants_of(b)
    assert any("S_CT0 is held, but the coefficient is exact in one word" in s
               for s in found), found
    # a plan the build does not hold, and a rho that is not pi/4 (1 + over)
    b = ml.build("sin", FMT, RNE)
    b.meta["poly"] = ((4, 3, 9), (5, 3, 10))
    assert any("is not the re-derived ((4, 3, 9), (5, 3, 9))" in s
               for s in _constants_of(b))
    b = ml.build("sin", FMT, RNE)
    b.meta["rho"] = b.meta["rho"] + Fraction(1, 2 ** 40)
    assert any("rho is not pi/4 (1 + over) rounded up to 96 bits" in s
               for s in _constants_of(b))


def test_the_plan_of_the_polynomials_and_its_proofs_by_name(monkeypatch):
    """plan_trig_tw: (K3, K2, D) from plan_trig's (K, D) and plan_exp32's
    rule with its 2 bits of slack, at the build's rho and at the study's 2^-30,
    2^-11.66 and 2^-10 (the same at every one: parcel M2X's finding); the two
    static proofs of the plan, and each head step's ordering, are ValueErrors
    by name."""
    rho = build_of("sin", RNE).meta["rho"]
    assert ml.plan_trig(FMT, G, rho) == ((7, 9), (8, 9))
    pio4 = ml._pi() / 4
    for e in (Fraction(1, 2 ** 30), Fraction(309, 10 ** 6), Fraction(1, 2 ** 10),
              build_of("sin", RNE).meta["overshoot"]):
        assert ml.plan_trig_tw(FMT, G, pio4 * (1 + e)) == PLAN
    # the rule against plan_trig: slack 4 (the rule's is 2; 3 changes nothing)
    # moves the end of S's head from 7 to 8
    assert ml.plan_trig_tw(FMT, G, rho, slack=3) == PLAN
    with pytest.raises(ValueError, match="static proof 'K3 \\+ K2 is "
                       "plan_trig's K' fails: S at fp32, G = 40: the head "
                       "ends at 8 by the rule \\(slack 4\\) and at 7 by "
                       "plan_trig"):
        ml.plan_trig_tw(FMT, G, rho, slack=4)
    # no term needs a triple word at a small G: K3 = 0 is refused by name
    with pytest.raises(ValueError, match="static proof 'a triple-word step is "
                       "needed' fails: S at fp32, G = 10: K3 = 0"):
        ml.plan_trig_tw(FMT, 10, rho, slack=0)
    # each head step's Fast2Sum is ordered: |z y| / |c_k| is under 1 (the
    # figures are the bound by the series' absolute values), and a ratio past 1
    # refuses the build by name, the first step first
    assert max(float(ml._order_ratio(n, k, rho))
               for n, ks in (("S", range(7)), ("C", range(8)))
               for k in ks) < 0.5
    monkeypatch.setattr(ml, "_order_ratio", lambda *a: Fraction(2))
    with pytest.raises(ValueError, match=r"static proof 'S k=6: \|c_k\| > "
                       r"\|z y\| \(Fast2Sum ordered\)' fails: ratio 2.000"):
        ml.build("sin", FMT, RNE)
    monkeypatch.undo()
    # the cushion proof: a rho under the computed overshoot is refused by name
    b = ml.build_reduction(FMT)
    ml._check_trig_cushion_tw(b, b.meta["rho"])
    with pytest.raises(ValueError, match="triple word's computed cushion"):
        ml._check_trig_cushion_tw(b, ml.trig_rho(30))
    # G other than 40 is refused by name, by the reduction's plan
    with pytest.raises(ValueError, match="G = 18"):
        ml.build("sin", FMT, RNE, guard=18)
    with pytest.raises(ValueError, match="G = 41"):
        ml.build("tan", FMT, RNE, guard=41)


# =====================================================================
# the error budget and the mark-rate law, on the real triple word
# =====================================================================

@pytest.mark.parametrize("fn", FUNCS)
def test_the_budget_reproduces_the_models_at_its_anchor_lanes(fn):
    """The budget tool had never run on a real triple-word build. At the 34
    lanes parcel M2X named (tw32_anchors.out.txt) it gives the model's figures
    to the digits it printed, the frozen phases including red-products-low."""
    b = build_of(fn, RNE)
    xs = sorted({x for a in ANCHORS for x in (a, a | FMT.sign_mask)})
    s, _bud = TB.budget_of(b, xs)
    assert (s["lanes"], s["skipped"]) == (34, 0)
    assert (f"{s['Emax']:.4g}", f"{s['Mmax']:.4g}", f"{s['resid']:.3g}",
            f"{s['bound']:.4g}") == MODEL_ANCHORS[fn]
    assert TB.judge(s, "budget: x") == []
    assert TB.exact_phases_of(b) == TB.EXACT_PHASES_TW \
        and TB.exact_phases_of(ml.build("sin", FP64, RNE)) == TB.EXACT_PHASES
    assert "red-products-low" in b.phase_of


@pytest.mark.parametrize("fn", FUNCS)
def test_the_budget_check_over_a_small_sample_of_each_region(fn):
    """The check `budget` at 5 lanes of each of the five regions and of quad
    (seed 11) of each function: the bound under 1 Bv (the model's 0.43 at
    most over 12,000 lanes), no lane past it, the residual stated, and V
    bit-identical across the five attributes on every lane, so that the rne
    budget is every attribute's (parcel M2X: 517 lanes a function)."""
    b = build_of(fn, RNE)
    attrs = {r: build_of(fn, r) for r in RND}
    xs = [x for r in T.REGIONS for x in T.sample(FMT, r, 5, 11)]
    out, s = TB.check_budget(b, xs, "small", attrs=attrs)
    assert out == [], out
    assert s["lanes"] == 25 and s["attr_lanes"] == 25 and s["attr_differ"] == 0
    assert 0 < s["Emax"] <= s["bound"] < 0.5 and s["resid"] < 0.01
    assert s["rounding"] > 250 and s["S_obs"] > 0       # the model's: 313


def test_the_budget_without_the_late_products_frozen_is_not_under_1():
    """The leg that makes the frozen set matter: red-products-low left out of
    it (the double word's EXACT_PHASES), sin's bound over the 60 lanes is 1.0042
    Bv where with it it is 0.1363 (MEASURED)."""
    b = build_of("sin", RNE)
    xs = [x for r in T.REGIONS for x in T.sample(FMT, r, 12, 5)]
    out, s = TB.check_budget(b, xs, exact_phases=TB.EXACT_PHASES)
    assert len(out) == 1 and "not under 1" in out[0]
    assert round(s["bound"], 4) == 1.0042
    out, s = TB.check_budget(b, xs)
    assert out == [] and round(s["bound"], 4) == 0.1363


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("rnd", [RNE, RTZ], ids=rid)
def test_the_mark_rate_law_at_g_prime_6(fn, rnd):
    """The mark-rate law with the bound inflated to G' = 6: the count of marks
    against the sample's own expectation (the model: 6 cells within 2.5 sigma
    at 2,000 lanes, 276 marked; the lead's box run: 1.75 sigma at 50,000),
    every unmarked lane right and every marked guess right."""
    out, st = T.check_rate(FMT, rnd, fn, RATE_N, RATE_SEED,
                           statistics=RATE_STATISTICS)
    assert out == [], out
    assert st["wrong"] == 0 and st["guess_wrong"] == 0
    assert 5 <= st["marked"] <= 40 and abs(st["z"]) < 3
    assert st["class"] == H.rate_class(rnd)


# =====================================================================
# the legs that run no lane at fp32, and the ones that can fail
# =====================================================================

def near_family(fmt=FMT, K=64, J=2):
    """parcel M2X's census.py near family: x = the floats nearest k pi/2 for
    k = 1 to K and j ulps either side (j = -J .. J), both signs, and the
    deepest cancellations pi_worstcase finds (the stage's sweep): 688 at fp32."""
    import pi_worstcase
    pio2 = ml._pi() / 2
    out = []
    for k in range(1, K + 1):
        b = ml._enc(fmt, k * pio2)
        for j in range(-J, J + 1):
            out += [b + j, (b + j) | fmt.sign_mask]
    stride, top = H._transcend_check().WORST_SWEEP[fmt.name]
    vmax = fmt.emax
    stride = max(1, min(stride, (vmax + 1) // 64))
    out += pi_worstcase.worst_encodings(fmt, stride, top, 0, vmax)
    return sorted(set(out))


def test_the_theory_finds_no_centre_at_g40_and_the_zeros_are_pinned():
    """At G = 40 the theory finds no centre for any function and attribute (E6:
    sin x - x ~ x^3/6 is 2^7 Bv away at the smallest main-path |x|), so the
    structured, family and window legs run NO LANE at fp32, and pass with none
    run. That is the finding; what is pinned here is that it stays true (the
    zero is a claim, and a change of the theory, the format or G moves it) and
    the legs that replace them are the next tests'."""
    for fn in FUNCS:
        assert set(TF.TRIG_FAMILY[fn]["fp32"]) == {rid(r) for r in RND}
        for r in RND:
            assert TF.TRIG_FAMILY[fn]["fp32"][rid(r)] == []
            assert TF.entries(FMT, r, fn) == [] and TF.centres(FMT, r, fn) == []
            assert T.structured_lanes(fn, FMT, r) == []
            assert T.pool_marks(fn, "fp32", rid(r)) == {}
            f = ml.fragment(fn, FMT, r)
            assert T.check_structured(f) == ([], [])      # passes with none run
        assert T.TINY_COUNTS["fp32"][fn] == (0, 0)
    assert not [m for m in T.TRIG_POOL_MARKS if m[1] == "fp32"]
    assert "fp32" not in TF.MINNBR_RANGE and len(TF.census(FMT)) == 48 \
        == T.CENSUS_SIZES[("tiny", "fp32")]
    assert len(TF.census(FMT, G=18)) == 144       # the double word's: G = 18
    # the committed fp32 cells are the theory's (test_mathlib_trig.py holds the
    # whole list to a fresh generation; this is fp32's cells alone, cheaply)
    assert T.check_family_list(
        {fn: {"fp32": TF.TRIG_FAMILY[fn]["fp32"]} for fn in FUNCS},
        TF.generate([FMT])) == []
    # and the census, classified at G = 40: clear or gated, never to be marked
    for fn in FUNCS:
        for r in (RNE, RTZ):                  # rdn, rup share rtz's class
            kinds = {TF.classify(FMT, r, x, None, fn) for x in TF.census(FMT)}
            assert kinds <= {"clear", "gated"}, (fn, rid(r), kinds)
    # sin's two gated: the arguments under its gate 2^-12 (cos's is 2^-13)
    assert sum(TF.classify(FMT, RNE, x, None, "sin") == "gated"
               for x in TF.census(FMT)) == 2


# the centres the theory finds at G = 18 (the double word's): sin x 3 2^-11 under
# rne, cos x 1, 3 and 5 2^-12 under rne and 2^-10 .. 2^-11 under the directed
# three; none for tan and none for sin under the directed three
G18 = {("sin", RNE): [(3, 11, 11)],
       ("cos", RNE): [(1, 12, 12), (3, 12, 12), (5, 12, 12)],
       ("cos", RTZ): [(1, 10, 11)]}


def test_the_g18_centres_are_the_theorys_at_g18():
    for fn in FUNCS:
        for r in (RNE, RTZ):
            assert TF.entries(FMT, r, fn, G=18) == G18.get((fn, r), [])
    assert sum(len(v) for v in G18.values()) == 5 \
        and all(TF.expand(TF.entries(FMT, r, fn, G=18)) for (fn, r) in G18)


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("rnd", [RNE, RTZ], ids=rid)
def test_the_g18_centres_do_not_mark_at_g40(fn, rnd):
    """M2X's G = 18 centres run through the G = 40 fragment must NOT mark: the
    lanes beside them (the theory at G = 40 calls every one clear) are right
    and unmarked. A leg that can fail where the committed centres are none:
    bound_wide, the bound 2^22 wider (the double word's G), marks them."""
    f = ml.fragment(fn, FMT, rnd)
    cen = TF.expand(TF.entries(FMT, rnd, fn, G=18))
    out, st = T.check_family(f, cen)
    assert out == [], out
    assert st["mark"] == 0 and st["wrong"] == 0 and st["guess_wrong"] == 0
    assert st["marked_clear"] == st["marked_either"] == st["marked_gated"] == 0
    assert (st["lanes"] > 0) == bool(cen)


@pytest.mark.parametrize("fn", FUNCS)
def test_the_census_does_not_mark_at_g40(fn):
    """The census: the 48 arguments of G = 40 and the double word's 144 (a
    superset; sin marks 2 and cos 6 of them at G = 18), none marked and none
    wrong (parcel M2X: 0 in 720 and 2,160 lanes), every lane the theory demands
    marked (none) marked and none it calls clear; and every eighth of the near
    family (688 arguments; 0 marked in 10,320 lanes there, M2X)."""
    near = near_family()
    assert len(near) == 688
    for r in RND:
        f = ml.fragment(fn, FMT, r)
        out, t = T.check_census_counts(f, "tiny", xs=TF.census(FMT, G=18))
        assert out == [] and t.n == 144 and not t.marked and not t.wrong
        if r in (RNE, RTZ):
            out, t = T.check_census_counts(f, "tiny")        # the 48
            assert out == [] and t.n == 48 and not t.marked
            out, t = T.check_census_counts(f, "tiny", xs=near[::8])
            assert out == [] and t.n == 86 and not t.marked and not t.wrong


def test_each_g18_leg_can_fail_alone_on_a_wider_bound():
    """bound_wide (Bv 2^22 wider: the double word's G = 18 at fp32): the lanes
    beside the G = 18 centres mark (the family leg: sin rne 4 lanes of 4, cos
    rne 11 of 12, cos rtz 8 of 8, all of them lanes the theory at G = 40 calls
    clear) and so does the census (MEASURED: sin 2 under rne, cos 6 under rne
    and rtz, of the 48, the same lanes as of the 144, which the double word
    marked: its 2 and 6), each a finding of its own leg, with no lane wrong."""
    for fn, r, census, family in (("sin", RNE, 2, 4), ("cos", RNE, 6, 11),
                                  ("cos", RTZ, 6, 8)):
        f = build_of(fn, r, "bound_wide").fragment()
        out, st = T.check_family(f, TF.expand(TF.entries(FMT, r, fn, G=18)))
        assert out and all(s.startswith("family: ") for s in out)
        assert any("is outside every window and marked" in s for s in out)
        assert st["marked_clear"] == family and st["wrong"] == 0
        out, t = T.check_census_counts(f, "tiny")
        assert all(s.startswith("census_counts: ") for s in out)
        assert (f"{census} of the census's 48 arguments are marked, the "
                f"study's count is 0") in out[0]
        assert len(t.marked) == census and not t.wrong
        out, t144 = T.check_census_counts(f, "tiny", xs=TF.census(FMT, G=18))
        assert out and len(t144.marked) == census and not t144.guess_wrong
    # tan has no centre at G = 18, and its census is quiet even so
    f = build_of("tan", RNE, "bound_wide").fragment()
    cen = TF.expand(TF.entries(FMT, RNE, "tan", G=18))
    assert cen == [] and T.check_family(f, cen)[0] == []
    assert T.check_census_counts(f, "tiny")[0] == []


# =====================================================================
# the plants
# =====================================================================
#
# Each plant is built into fresh fragments and run through the checks; a check
# is RED when it finds what it exists to find. The table says what each row was
# built to be seen by (red) and what it was shown to leave alone (green); the
# matrix is MEASURED (the parcel's entry). A row's check names the function and
# attribute it runs at. The lanes are the least that shows it: pools the 163-lane
# slice, bound 12 points of each of the five regions (seed 5) and the named lane,
# audit every sixth lane of the slice (and the lane parcel M2X's carry-dropped
# fails at), constants and shape the fragments of the format, the planted
# function among clean ones.

def region_lanes(n=12, seed=5):
    return [x for r in T.REGIONS for x in T.sample(FMT, r, n, seed)]


def planted_or_clean(fn, rnd, plant):
    try:
        return build_of(fn, rnd, plant)
    except ValueError as e:
        if "does not apply" not in str(e):
            raise
        return build_of(fn, rnd)


def applies(plant, fn):
    try:
        build_of(fn, RNE, plant)
    except ValueError as e:
        assert "does not apply" in str(e), (plant, fn, e)
        return False
    return True


# the lane parcel M2X's first quotient lost 2^-48 at (tan, 2^+16 Bv)
BOUND_EXTRA = {"quotient_fma": [0x3a410113]}


def run_check(check, plant, fn, rnd):
    b = build_of(fn, rnd, plant)
    f = b.fragment()
    if check == "pools":
        return T.check_pools(f, xs=list(T.pool_slice(FMT)))[0]
    if check == "seq":
        return T.check_seq(f)[0]
    if check == "bound":
        return T.check_bound(b, region_lanes() + BOUND_EXTRA.get(plant, []))[0]
    if check == "specials":
        return T.check_specials(f)[0]
    if check == "audit":
        xs = list(T.pool_slice(FMT)[::6])
        return T.check_audit(b, xs + ([0x447951d2] if plant == "carry_dropped"
                                      else []))[0]
    if check == "constants":
        return T.check_constants(
            builder=lambda n, ft, r: planted_or_clean(n, r, plant)
            if n == fn else build_of(n, r), formats=(FMT,))[0]
    if check == "shape":
        return T.check_shape(FMT, {(n, r): (planted_or_clean(n, r, plant)
                                            if n == fn else build_of(n, r))
                                   for n in FUNCS for r in RND})
    if check == "budget":
        return TB.check_budget(b, region_lanes())[0]
    if check == "rate":
        return T.check_rate(FMT, rnd, fn, RATE_N, RATE_SEED, plant=plant,
                            statistics=RATE_STATISTICS)[0]
    if check == "family":
        return T.check_family(f, TF.expand(TF.entries(FMT, rnd, fn, G=18)))[0]
    if check == "census_counts":
        return T.check_census_counts(f, "tiny")[0]
    raise ValueError(check)


CHECKS = ("pools", "seq", "bound", "specials", "shape", "audit", "constants",
          "budget", "rate", "family", "census_counts")
TRIG_PLANT_NAMES = set(ml.TRIG_PLANTS)
PLANTED = [
    ("quadrant_sign",
     {"pools": ("cos", RNE), "bound": ("cos", RNE), "constants": ("cos", RNE)},
     {"specials": ("cos", RNE), "audit": ("cos", RNE)}),
    ("clamp_tight",
     {"pools": ("sin", RNE), "shape": ("sin", RNE), "constants": ("sin", RNE),
      "census_counts": ("cos", RTZ)},
     {"bound": ("sin", RNE), "audit": ("sin", RNE)}),
    ("bound_loose",
     {"bound": ("sin", RNE), "constants": ("sin", RNE),
      "budget": ("sin", RNE)},
     {"pools": ("sin", RNE), "specials": ("sin", RNE)}),
    ("mark_silenced",
     {"shape": ("cos", RTZ), "rate": ("cos", RTZ)},
     {"pools": ("cos", RTZ), "bound": ("cos", RTZ), "constants": ("cos", RTZ)}),
    ("coef",
     {"pools": ("sin", RNE), "seq": ("sin", RNE), "constants": ("sin", RNE)},
     {"specials": ("sin", RNE), "audit": ("sin", RNE)}),
    ("newton_short",
     {"budget": ("tan", RNE), "shape": ("tan", RNE)},
     {"pools": ("tan", RNE), "bound": ("tan", RNE), "specials": ("tan", RNE)}),
    ("tiny_gate_off",
     {"pools": ("sin", RNE), "specials": ("sin", RNE),
      "constants": ("sin", RNE)},
     {"bound": ("sin", RNE), "audit": ("sin", RNE)}),
    ("rl_dropped",
     {"pools": ("sin", RNE), "bound": ("sin", RNE), "constants": ("sin", RNE)},
     {"audit": ("sin", RNE), "specials": ("sin", RNE)}),
    ("zl_dropped",
     {"pools": ("sin", RNE), "bound": ("sin", RNE)},
     {"specials": ("sin", RNE), "constants": ("sin", RNE)}),
    ("clamp_off",
     {"shape": ("sin", RTZ), "constants": ("sin", RTZ)},
     {"pools": ("sin", RTZ), "bound": ("sin", RTZ), "specials": ("sin", RTZ)}),
    ("sign_after_rounding",
     {"pools": ("sin", RDN), "bound": ("sin", RDN), "specials": ("sin", RDN),
      "census_counts": ("sin", RDN)},
     {"constants": ("sin", RDN), "audit": ("sin", RDN)}),
    ("cos_zero_operand",
     {"pools": ("cos", RNE), "specials": ("cos", RNE)},
     {"bound": ("cos", RNE), "constants": ("cos", RNE),
      "audit": ("cos", RNE)}),
    ("inf_flag_dropped",
     {"specials": ("sin", RNE)},
     {"pools": ("sin", RNE), "constants": ("sin", RNE)}),
    # parcel M2F2's: the faults only the triple word has
    ("c2_dropped",
     {"bound": ("sin", RNE), "budget": ("sin", RNE),
      "constants": ("sin", RNE)},
     {"pools": ("sin", RNE), "audit": ("sin", RNE)}),
    ("y2_dropped",
     {"bound": ("sin", RNE), "budget": ("sin", RNE), "shape": ("sin", RNE)},
     {"pools": ("sin", RNE), "constants": ("sin", RNE)}),
    ("quotient_fma",
     {"bound": ("tan", RNE), "shape": ("tan", RNE)},
     {"pools": ("tan", RNE), "constants": ("tan", RNE)}),
    ("bound_wide",
     {"family": ("sin", RNE), "census_counts": ("cos", RNE),
      "constants": ("sin", RNE)},
     {"pools": ("sin", RNE), "bound": ("sin", RNE), "audit": ("sin", RNE)}),
    # parcel M2X's three plants: carry-dropped, r2-dropped and mark-silenced
    ("carry_dropped",
     {"audit": ("sin", RNE)},
     {"pools": ("sin", RNE), "bound": ("sin", RNE)}),
    ("r2_dropped",
     {"bound": ("sin", RNE), "budget": ("sin", RNE)},
     {"pools": ("sin", RNE), "audit": ("sin", RNE)}),
]


def _row_id(r):
    return r[0]


@pytest.mark.parametrize("row", PLANTED, ids=_row_id)
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(row):
    plant, red, green = row
    for check, (fn, rnd) in red.items():
        found = run_check(check, plant, fn, rnd)
        assert found, f"{plant} at fp32: {check} stays green"
        assert all(s.startswith(check + ": ") for s in found), found[:2]
    for check, (fn, rnd) in green.items():
        found = run_check(check, plant, fn, rnd)
        assert found == [], f"{plant} at fp32: {check} is red: {found[:2]}"


@functools.lru_cache(maxsize=None)
def _control(check, fn, rnd):
    return run_check(check, None, fn, rnd)


def test_the_control_is_green_in_every_check_the_table_runs():
    """The clean fragments, on the lanes the rows use, in every check a row
    names red: nothing red, so that a red in a row is the plant's (a green of a
    row is the plant's alone to explain, and needs no control)."""
    seen = set()
    for plant, red, green in PLANTED:
        for check, (fn, rnd) in red.items():
            key = (check, fn, rnd)
            if key in seen or check == "seq":
                continue
            seen.add(key)
            assert _control(*key) == [], key
    assert len(seen) > 20
    assert _control("seq", "sin", RNE) == []


@pytest.mark.parametrize("plant", ["quotient_fma"])
def test_the_models_first_quotient_is_2_to_the_16_bv_at_its_lane(plant):
    """Parcel M2X's own first version lost 2^-48 in tan's first remainder (tan
    at 0x3a410113, 2^+16 Bv; the plant is that defect): 2^+16.41 here against
    the control's 2^-7.86, and the placed regions do not reach it."""
    b = build_of("tan", RNE, plant)
    out, (worst, main, lanes) = T.check_bound(b, [0x3a410113], "named")
    assert out and round(worst, 2) == 16.41 and main == lanes == 1
    out, (worst, _m, _l) = T.check_bound(build_of("tan", RNE), [0x3a410113])
    assert out == [] and round(worst, 2) == -7.86
    assert T.check_bound(b, region_lanes())[0] == []      # green without it


def test_carry_dropped_is_red_in_the_audit_on_the_binade_edges_only():
    """parcel M2X's finding for the carry-dropped plant (10 lanes in its 1,867
    arguments, the first 0x447951d2, instruction 111, red-mid): invisible to the
    slice, to the pools and to the bound, and the products' binade edges find it
    (11 of the 940 edges here, the same first lane; the test runs every
    fourth and that lane)."""
    b = build_of("sin", RNE, "carry_dropped")
    out, tally = T.check_audit(b, list(T.pool_slice(FMT)))
    assert out == []
    edges = list(RT.edge_args(FMT, W.plan_tw()))
    out, tally = T.check_audit(b, [0x447951d2] + edges[::4])
    assert len(out) == 1 and "0x447951d2" in out[0] \
        and "instruction 111 (add, red-mid)" in out[0]
    assert T.check_pools(b.fragment(), xs=list(T.pool_slice(FMT)))[0] == []


NOT_APPLICABLE = (
    {("quadrant_sign", fn) for fn in ("sin", "tan")}
    | {(p, "tan") for p in ("clamp_tight", "clamp_off")}
    | {("newton_short", fn) for fn in ("sin", "cos")}
    | {("sign_after_rounding", "cos")}
    | {("range_unmarked", fn) for fn in FUNCS}
    | {("cos_zero_operand", fn) for fn in ("sin", "tan")}
    | {("quotient_fma", fn) for fn in ("sin", "cos")})


def test_the_plants_that_do_not_apply_are_the_pinned_ones():
    """A plant that cannot act is refused by name ("does not apply"), as
    M2G1's and M2G2a's are, and counts as neither red nor green there. The
    pairs are pinned so that a plant that stops acting where it did is seen,
    and range_unmarked (fp32 has no range) is refused for all three."""
    names = list(ml.TRIG_PLANTS) + list(ml.TRIG_TW_ROUTINE_PLANTS) \
        + sorted(ml.TRIG_TW_PLANTS)
    got = {(p, fn) for p in names for fn in FUNCS if not applies(p, fn)}
    assert got == NOT_APPLICABLE
    with pytest.raises(ValueError, match="plant 'range_unmarked' does not "
                       "apply to sin at fp32: the fault is not reached"):
        ml.build("sin", FMT, RNE, plant="range_unmarked")
    # the triple word's faults are refused at the other formats, by name
    for plant in list(ml.TRIG_TW_ROUTINE_PLANTS) + sorted(ml.TRIG_TW_PLANTS):
        with pytest.raises(ValueError, match=f"plant '{plant}' does not apply "
                           f"to sin at fp64: it is a fault of the triple "
                           f"word's, fp32's"):
            ml.build("sin", FP64, RNE, plant=plant)
    with pytest.raises(ValueError, match="no_such_plant") as e:
        ml.build("sin", FMT, RNE, plant="no_such_plant")
    for name in ("quadrant_sign", "chunk", "c2_dropped", "carry_dropped"):
        assert name in str(e.value)


def test_every_plant_is_in_the_table_and_acts():
    """The table names every plant that acts at fp32 (the 14 of TRIG_PLANTS but
    range_unmarked, the three of TRIG_TW_ROUTINE_PLANTS and the bound's wide
    one, and parcel M2F1's carry_dropped and r2_dropped), each row has a red
    check and every check has a plant red in it; and a plant that did nothing
    would pass every row green, so each is a different build from the clean
    one."""
    named = {row[0] for row in PLANTED}
    assert named == (set(ml.TRIG_PLANTS) - {"range_unmarked"}) \
        | set(ml.TRIG_TW_ROUTINE_PLANTS) | set(ml.TRIG_TW_PLANTS)
    assert len(PLANTED) == len(named) == 19
    assert set(ml.TRIG_TW_ROUTINE_PLANTS) == {"c2_dropped", "y2_dropped",
                                              "quotient_fma", "bound_wide"}
    for plant, red, green in PLANTED:
        assert set(red) | set(green) <= set(CHECKS), plant
        assert not set(red) & set(green) and red, plant
        for check, (fn, rnd) in {**red, **green}.items():
            assert fn in FUNCS and rnd in RND
            assert applies(plant, fn), (plant, fn)
        clean = build_of(next(iter(red.values()))[0], RNE)
        fn = next(iter(red.values()))[0]
        b = build_of(fn, RNE, plant)
        clean = build_of(fn, RNE)
        assert not (b.body == clean.body and b.words == clean.words
                    and b.result == clean.result and b.flags == clean.flags), \
            plant
    assert {c for row in PLANTED for c in row[1]} == set(CHECKS)


def test_a_reduction_plant_passes_through_to_the_triple_words_tail():
    """build() passes REDUCTION_PLANTS and TRIG_TW_PLANTS to
    trig_reduction_tw; one that could not act is refused by it, by name, and
    the cushion proof is the clean build's."""
    acts, refused = [], []
    for plant in ml.REDUCTION_PLANTS:
        try:
            b = ml.build("sin", FMT, RNE, plant=plant)
        except ValueError as e:
            assert "does not apply" in str(e), (plant, e)
            refused.append(plant)
        else:
            assert b.meta["plant"] == plant
            acts.append(plant)
    # M2F1's: eight act (exact_add the lower group's first TwoSum), three are
    # refused by name (mid_inexact, range_short, split_unproved)
    assert sorted(refused) == ["mid_inexact", "range_short", "split_unproved"]
    assert "exact_add" in acts and "pio2_low" in acts and len(acts) == 9
    for plant in sorted(ml.TRIG_TW_PLANTS):
        assert ml.build("sin", FMT, RNE, plant=plant).meta["plant"] == plant


# =====================================================================
# the commands, the corpus and the docs
# =====================================================================

def _inproc(capsys, *args):
    import mathlib_runs as R
    R.FINDINGS.clear()
    try:
        rc = R.main(list(args))
    finally:
        if R.OUT is not None:
            R.OUT.close()
            R.OUT = None
    return rc, capsys.readouterr().out


def test_the_trig_commands_take_fp32(capsys, tmp_path):
    rc, out = _inproc(capsys, "trig-bound", "--formats", "fp32", "--fn", "tan",
                      "--attrs", "rne", "--n", "3")
    assert rc == 0 and "RESULT: ok" in out
    assert out.count("trig-bound tan fp32 rne") == 5
    rc, out = _inproc(capsys, "trig-rate", "--formats", "fp32", "--fn", "cos",
                      "--attrs", "rne", "--n", "100")
    assert rc == 0 and "trig-rate cos fp32 rne:" in out and "RESULT: ok" in out
    rc, out = _inproc(capsys, "trig-family", "--formats", "fp32", "--fn",
                      "cos", "--attrs", "rne", "--centres", "3")
    assert rc == 0 and "RESULT: ok" in out
    assert "census tiny: 48 arguments, 0 marked (the study's 0)" in out
    # the legs that run no lane say so: 0 centres, 0 lanes, 0 windows; and the
    # minimisers' neighbours were censused at three formats, not fp32
    assert "cos fp32 rne family: 0 of 0 centres, 0 lanes" in out
    assert "windows: 0 centres, 0 lanes" in out and "census minnbr" not in out
    rc, out = _inproc(capsys, "trig-budget", "--formats", "fp32", "--fn", "sin",
                      "--regions", "edge,near", "--n", "4", "--no-attrs")
    assert rc == 0 and out.count("trig-budget sin fp32 G = 40 rne") == 2
    assert "trig-budget sin fp32 G = 40 ALL REGIONS" in out
    pytest.importorskip("numpy")
    rc, out = _inproc(capsys, "trig-budget", "--formats", "fp32", "--fn", "sin",
                      "--regions", "quad", "--n", "4", "--no-attrs")
    assert rc == 0 and "rne quad seed 126" in out
    import mathlib_runs as R
    helps = subprocess.run([sys.executable, "-B", str(pathlib.Path(R.__file__)),
                            "trig-pools", "--help"], capture_output=True,
                           text=True).stdout
    assert "fp64,fp128,fp256,fp32" in helps
    # the sizes of the box (tw32_box.sh): 12,000 a region, 50,000 for the rate
    text = pathlib.Path(R.__file__).read_text()
    assert '"fp32": 12000' in text and '"fp32": 50000' in text


def test_seq_check_has_no_fp32_clause_and_keeps_its_marker():
    """The trig part takes fp32 from TRIG_FORMATS: the clause "sin, cos and tan
    not built (parcel M2F's)" and its absent list are gone, and the literal the
    card-stress build step reads stays where it is."""
    text = (ROOT / "host" / "tests" / "seq_check.py").read_text()
    assert "not built (parcel" not in text and "(parcel M2F's)" not in text
    assert '["absent"]' not in text and "if fmt not in ml.TRIG_FORMATS" \
        not in text
    assert text.count("THE ROUTINE CORPUS DID NOT REACH EVERY FORM") == 1
    assert "mathlib.TRIG_FORMATS" in text
