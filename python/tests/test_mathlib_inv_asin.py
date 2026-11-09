# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""asin and acos of python/cft_golden/mathlib.py (parcel M4G2, M4's build, wave
2) at fp64, fp128 and fp256, on the one core parcel M4G1 built for atan
(docs/studies/M4-invtrig.md, sections 2.1 and 8): the shared front
(_asin_acos_front), the two builders, the four plants of their own and their
role checks, held to the same eight checks as atan by the harness
(python/tests/mathlib_inv_harness.py, its "asin and acos" section):

  pools  seq  bound  structured  specials  shape  audit  constants

(the core's check, `core`, is atan's and M4G1's file's; asin and acos reach the
core's double-word branch, which `test_the_cores_double_word_branch_*` below
runs on the lanes the fragments' own probes give). The plant matrix is at fp64:
a row for every (plant, function) the plant acts on, listing every check, red
or green. The port against the study's model is a scratch script of the
parcel's entry (nothing here imports docs/studies/m4): the dag digests of the
thirty fragments, recorded when it passed, are pinned below.

This file pins its own names and figures only: parcel M4G3's atan2 meets it at
the merge, and nothing here counts the functions built.
"""

import functools
import pathlib
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import FP64, FP128, FP256, routines  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_inv_harness as I  # noqa: E402
import test_mathlib_inv as T  # noqa: E402

FORMATS = I.FORMATS
FN2 = ("asin", "acos")
RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = I.RNE, I.RTZ, I.RDN, I.RUP, I.RMM
MARK = ml.MARK
fid, rid = T.fid, T.rid
build_of, fragment_of = I.build_of, I.fragment_of
BY_NAME = I.BY_NAME

CONFIGS = [(fn, f, r) for fn in FN2 for f in FORMATS for r in RND]
POOL_SIZES = {"fp64": 333, "fp128": 285, "fp256": 285}
PLAN = {"fp64": (6, 12), "fp128": (6, 20), "fp256": (6, 35)}
NEW_PLANTS = ("domain_edge", "u_low_dropped", "sqrt_product", "acos_quadrant")

# the dag digest of each fragment (the first 32 hex digits), equal to the
# study's model's `to_fragment()` digest at the port (docs/studies/m4/m4inv.py
# at fd37791d, the parcel's scratch script: 30 of 30, with the lane compare)
DIGESTS = {
    "asin/fp64/rne": "4659783ff511db05b4b168a1b336e16d",
    "asin/fp64/rtz": "dcd23770fd9bebaa949720e5187f742f",
    "asin/fp64/rdn": "75eefd779d9b3c3f08fde0d9b3dd98e0",
    "asin/fp64/rup": "becf1cced0c581a1059677f346c0d4f7",
    "asin/fp64/rmm": "89a68680c455f879aec1d6d58affb1c2",
    "asin/fp128/rne": "504723851fe0927e4e4058c571cf4f0d",
    "asin/fp128/rtz": "0de638be11ec880cf26b07fdefe05d1b",
    "asin/fp128/rdn": "de98903e87329561f6291fda0630a168",
    "asin/fp128/rup": "3f65e6f23b7331d208eedd7455f046a2",
    "asin/fp128/rmm": "9a748d0b47436ed8537664279cb7ffaf",
    "asin/fp256/rne": "2190722d939aee1558d7861ec5698fa3",
    "asin/fp256/rtz": "4a2c186a66ae688f8fb9b700a18381fa",
    "asin/fp256/rdn": "0310f463be2b0dbf6260949b590a4859",
    "asin/fp256/rup": "534e74e84da95225e7f818689b3f99a5",
    "asin/fp256/rmm": "49c7eb1dfecb3911785305ad8be1462f",
    "acos/fp64/rne": "a40e0365c3c650eee80ce1abc2657619",
    "acos/fp64/rtz": "34326162c7a5661790be772bca6d8289",
    "acos/fp64/rdn": "6c45a4c4fc52de78ec0124ffb868a65a",
    "acos/fp64/rup": "f479600095413653b2fe3759f27b73fc",
    "acos/fp64/rmm": "2982d2a14e510fc7596c7a9a95fe216c",
    "acos/fp128/rne": "85ef402b82d8408f01d46e1f27fbcc98",
    "acos/fp128/rtz": "530dbdb0b4404018bb2762bd89a73313",
    "acos/fp128/rdn": "b3d9c2b3bb6eadc1e104015e35b88490",
    "acos/fp128/rup": "dd31e0c956486ddb3d271eb94bf24d61",
    "acos/fp128/rmm": "f1b7887ff1bbf7a84d84a13963d71308",
    "acos/fp256/rne": "ebb42b052d839b723f0072b0a8aecbb8",
    "acos/fp256/rtz": "e3d5c10bced8e446662e3681ff4c159b",
    "acos/fp256/rdn": "cc7b69b8c76f182e081dde26fff52d76",
    "acos/fp256/rup": "ccf81a95c0ea2efe66d5f8a1133a4fa2",
    "acos/fp256/rmm": "ec7aaa72f86bf04382bdcce998eab66c",
}
# (instructions, words, values live) of every attribute, MEASURED by this
# parcel and equal to the study's costs.*.out.txt (asin 221, 235, 256; acos
# 217, 231, 252)
SHAPE_WANT = {("asin", "fp64"): (221, 56, 16), ("asin", "fp128"): (235, 64, 16),
              ("asin", "fp256"): (256, 79, 16), ("acos", "fp64"): (217, 54, 16),
              ("acos", "fp128"): (231, 62, 16), ("acos", "fp256"): (252, 77, 16)}
PHASES = ("front", "sqrt", "index", "num", "den", "quotient", "z", "tail",
          "head", "atan_s", "table", "recon", "final", "classify", "special")
PROBES = ("Vh", "Vl", "Bv", "R", "R1", "R2", "mk", "th", "tl", "tt", "Kk", "c",
          "nh", "P", "Nh0", "Nh", "Nl", "Dh", "Dl", "sh", "sl", "rem0", "uh",
          "ul", "wh", "wl", "nl", "dh", "dl")


# mathlib.__all__ at fd37791d, the base of this parcel (READ: the tuple in
# `git show fd37791d:python/cft_golden/mathlib.py`)
BASE_ALL = (
    'fragment', 'evaluate', 'invariants', 'flag_words', 'build',
    'build_exp', 'build_exp2', 'build_expm1', 'build_log', 'build_log2',
    'build_log1p', 'Build', 'plan_exp', 'plan_exp32', 'plan_log',
    'plan_log32', 'GUARD', 'LIVE_CAP', 'PLANTS', 'FORMATS', 'NAMES',
    'EXP_NAMES', 'LOG_NAMES', 'PHASE_ORDER', 'dag_digest', 'schedule_order',
    'check_constants', 'main', 'TRIG_RANGE', 'TRIG_LOST', 'trig_gates',
    'plan_reduction', 'ReductionValue', 'reduction_front', 'trig_reduction',
    'reduction_audit', 'build_reduction', 'REDUCTION_PLANTS',
    'check_reduction_constants', 'plan_reduction_tw', 'trig_reduction_tw',
    'TRIG_TW_PLANTS', 'check_reduction_tw_constants', 'TRIG_NAMES',
    'TRIG_LIVE_CAP', 'TRIG_PLANTS', 'plan_trig', 'trig_rho', 'trig_after',
    'check_trig_constants', 'TRIG_FORMATS', 'TRIG_TW_ROUTINE_PLANTS',
    'plan_trig_tw', 'INV_NAMES', 'INV_FORMATS', 'INV_LIVE_CAP',
    'INV_PLANTS', 'inv_cells', 'inv_rho', 'plan_inv', 'inv_core',
    'inv_recon', 'inv_final', 'build_inv_core', 'check_inv_constants')


# =====================================================================
# what is built, and where it is registered
# =====================================================================

def test_asin_then_acos_are_registered_after_atan_in_inv_names_order():
    names = list(ml._INV_BUILDERS)
    assert names[:3] == ["atan", "asin", "acos"]
    assert names == [n for n in ml.INV_NAMES if n in names]
    assert ml._INV_BUILDERS["asin"] is ml._build_asin
    assert ml._INV_BUILDERS["acos"] is ml._build_acos
    assert I.FUNCS[:3] == ("atan", "asin", "acos")
    # the role checks are assigned beside atan's
    assert {"atan", "asin", "acos"} <= set(ml._INV_ROLE_CHECKS)
    assert ml._INV_ROLE_CHECKS["asin"] is ml._check_asin_roles
    assert ml._INV_ROLE_CHECKS["acos"] is ml._check_acos_roles
    # mathlib's __all__ is the base's (fd37791d), recorded as a literal: this
    # parcel adds no name to it
    assert tuple(ml.__all__) == BASE_ALL


def test_the_four_plants_are_in_the_table_and_described():
    for name in NEW_PLANTS:
        assert name in ml.INV_PLANTS
        assert isinstance(ml.INV_PLANTS[name], str) \
            and len(ml.INV_PLANTS[name]) > 20, name
    # M4G1's twelve are as they were (the first twelve keys, in order)
    assert list(ml.INV_PLANTS)[:12] == sorted(
        T.INV_PLANT_NAMES, key=list(ml.INV_PLANTS).index)
    assert all(t not in T.INV_PLANT_NAMES for t in NEW_PLANTS)


@pytest.mark.parametrize("fn", FN2)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_an_asin_or_acos_fragment_is_a_specialised_fragment_built_once(fn, fmt):
    for rnd in RND:
        f = ml.fragment(fn, fmt, rnd)
        assert isinstance(f, routines.Fragment)
        assert (f.op, f.fmt, f.rnd, f.inputs, f.stage) == (
            fn, fmt, rnd, ("a",), "specialised")
        assert ml.fragment(fn, fmt, rnd) is f
        assert ml.invariants(f) == []
        assert f.live_max() == ml.INV_LIVE_CAP[fn][fmt.name] == 16


@pytest.mark.parametrize("fn", FN2)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_build_keeps_what_the_budget_and_the_sequel_read(fn, fmt):
    b = build_of(fn, fmt, RNE)
    assert set(PROBES) <= set(b.probes), set(PROBES) - set(b.probes)
    assert all(b.probes[k][0] == "v" for k in PROBES)
    m = b.meta
    assert m["fn"] == fn and m["G"] == T.GUARD[fmt.name]
    assert (m["N"], m["K"], m["D"]) == (8,) + PLAN[fmt.name]
    assert (m["shift"], m["plant"], m["family"]) == (0, None, "double word")
    # MEASURED: fourteen Fast2Sums and one TwoSum (the core's double-word
    # numerator), the study's (costs.*.out.txt)
    assert (m["fast_two_sum"], m["two_sum"]) == (14, 1)
    assert tuple(dict.fromkeys(b.phase_of)) == PHASES
    assert set(b.phase_of) <= set(ml.PHASE_ORDER)
    (tag, ref), = m["data"]
    assert tag == "index" and b.body[ref][0] == sf.OP_FMA
    assert b.inputs == ("a",)
    # the front's own probes (the core's operands as double words) are values
    # of the body; th and tl against the core's output are
    # test_the_cores_double_word_branch_runs_on_the_fragments_own_operands
    assert b.probes["nh"][0] == b.probes["dh"][0] == "v"


@pytest.mark.parametrize("fn", FN2)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_scheduler_takes_the_designs_order(fn, fmt):
    b = build_of(fn, fmt, RNE)
    g = b.fragment(schedule=False)
    ph = [b.phase_of[i] for i in b.live_indices()]
    live = {"design": g.live_max(),
            "ranked": ml.permuted(g, ml._ranked_order(g, ph)).live_max(),
            "dfs": ml.permuted(g, ml._dfs_order(g)).live_max()}
    # MEASURED, the drafter's table: the design's 16, the ranked 35 (acos 34)
    # and the depth-first 20
    assert live["design"] == 16
    assert live["ranked"] == {"asin": 35, "acos": 34}[fn]
    assert live["dfs"] == 20
    f = b.fragment()
    assert f.live_max() == 16 and f.body == g.body
    assert T.H.check_reorder(b, f) == []


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_dag_digests_are_the_models(fmt):
    for fn in FN2:
        for rnd in RND:
            got = ml.dag_digest(fragment_of(fn, fmt, rnd))[:32]
            assert got == DIGESTS[f"{fn}/{fmt.name}/{rid(rnd)}"], \
                (fn, fmt.name, rid(rnd))
            assert ml.dag_digest(build_of(fn, fmt, rnd).fragment(
                schedule=False))[:32] == got


def test_the_cores_double_word_branch_runs_on_the_fragments_own_operands():
    """build_inv_core(double=True) run on (n_h, n_l, d_h, d_l) read from the
    fragment's probes gives the fragment's th and tl: the same core on the
    same lanes (the lanes: the pool's sample and the audit's)."""
    for fmt in FORMATS:
        core = I.core_of(fmt, None, True)
        assert core.inputs == ("a", "b", "c", "d")
        for fn in FN2:
            b = build_of(fn, fmt, RNE)
            xs = list(I.sample(fn, fmt, "random", 6, 3)) \
                + list(I.sample(fn, fmt, "edge", 6, 3)) \
                + list(I.sample(fn, fmt, "diag", 4, 3)) \
                + I.audit_own_lanes(fmt)[::97]
            xs = [x for x in xs if I.in_main(fn, fmt, x)]
            assert len(xs) > 20
            nonzero_nl = 0
            for x in xs:
                _r, _f, pr = b.run(x, ("nh", "nl", "dh", "dl", "th", "tl"))
                th, tl, _ = core.run((pr["nh"], pr["nl"], pr["dh"], pr["dl"]))
                assert (th, tl) == (pr["th"], pr["tl"]), (fn, fmt.name,
                                                          hex(x))
                nonzero_nl += bool(pr["nl"]) or bool(pr["dl"])
            assert nonzero_nl > len(xs) // 2     # the low words do work


# =====================================================================
# the checks, clean
# =====================================================================

@pytest.mark.parametrize("fn,fmt,rnd", CONFIGS, ids=lambda v: v.name
                         if hasattr(v, "name") else (
                             rid(v) if isinstance(v, int) else v))
def test_pools(fn, fmt, rnd):
    f = fragment_of(fn, fmt, rnd)
    xs = I.pool(fn, fmt)
    assert len(xs) == POOL_SIZES[fmt.name]
    out, t = I.check_pools(f)
    assert out == [] and t.n == len(xs)
    # MEASURED (the model by the drafter, these fragments by this parcel): the
    # pools through asin and acos mark no lane and get none wrong
    assert t.marked == [] and t.wrong == []
    assert I.INV_POOL_MARKS == () or not [m for m in I.INV_POOL_MARKS
                                          if m[0] in FN2]


SEQ_CONFIGS = [(fn, f, r) for fn in FN2 for f in FORMATS for r in (RNE, RTZ)]


@pytest.mark.parametrize("fn,fmt,rnd", SEQ_CONFIGS, ids=lambda v: v.name
                         if hasattr(v, "name") else (
                             rid(v) if isinstance(v, int) else v))
def test_seq(fn, fmt, rnd):
    f = fragment_of(fn, fmt, rnd)
    out, lanes = I.check_seq(f)
    assert out == []
    assert len(lanes) > 80          # MEASURED 88 to 94 (the committed lanes too)
    for x in I.structured_lanes(fn, fmt, rnd):
        assert x in lanes and ml.evaluate(f, x)[1] & MARK
    if (fn, fmt, rnd) == ("asin", FP64, RTZ):
        # asin(3 2^-25) under rtz at fp64: the card's case, marked
        assert 0x3e78000000000000 in lanes
        assert ml.evaluate(f, 0x3e78000000000000)[1] & MARK


@pytest.mark.parametrize("fn", FN2)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_bound(fn, fmt):
    b = build_of(fn, fmt, RNE)
    worst, lanes = -1e9, 0
    pts = I.placed_points(fn, fmt)
    assert tuple(pts) == ("edge", "big", "small", "random", "diag")
    for region, xs in pts.items():
        assert len(xs) == 48
        out, (w, main, n) = I.check_bound(b, xs, region)
        assert out == [] and main == n == 48, (region, out)
        worst, lanes = max(worst, w), lanes + n
    # the largest is a SAMPLED lower bound (240 points, seed 11): MEASURED
    # 2^-7.0, 2^-6.75, 2^-6.3 (asin) and 2^-7.4, 2^-5.9, 2^-7.2 (acos) of Bv
    want = {("asin", "fp64"): -7.0, ("asin", "fp128"): -6.75,
            ("asin", "fp256"): -6.3, ("acos", "fp64"): -7.4,
            ("acos", "fp128"): -5.93, ("acos", "fp256"): -7.16}[(fn, fmt.name)]
    assert round(worst, 2) == pytest.approx(want, abs=0.01), worst
    assert lanes == 240


def test_the_regions_and_the_samplers_are_the_models():
    assert I.REGIONS_BY_FN["atan"] == I.REGIONS
    for fn in FN2:
        assert I.REGIONS_BY_FN[fn] == I.REGIONS + ("diag",)
        with pytest.raises(ValueError, match="region 'nope'"):
            I.sample(fn, FP64, "nope", 3, 11)
    # the first three lanes of each mode at seed 11, fp64, recorded from the
    # sampler and equal to docs/studies/m4/m4measure.py's sample() on all five
    # modes at the three formats (the scratch port)
    want = {("asin", "edge"): [0xbfee7d8ea39a8960, 0x3fe46818d6bade6d,
                               0x3fe24b39c2eb0294],
            ("asin", "big"): [0xbfeffffff8000000, 0x3fe8000000000000,
                              0xbfeffffffffe0000],
            ("asin", "diag"): [0xbfe6a09e667f3bce, 0x3fe6a09e667f3bcd,
                               0x3fe6a09e667f3bc5],
            ("asin", "small"): [0xbed433b56742c9a9, 0x3e44ee47cde567a6,
                                0xbf959a34e7b37c76],
            ("acos", "small"): [0xbdc433b56742c9a9, 0x3b94ee47cde567a6,
                                0xbe2b958f4db5e66b],
            ("acos", "random"): [0xbdc433b56742c9a9, 0x3b94ee47cde567a6,
                                 0xbe2b958f4db5e66b],
            ("asin", "random"): [0xbed433b56742c9a9, 0x3e44ee47cde567a6,
                                 0xbfce7b37af731523]}
    for (fn, mode), lanes in want.items():
        assert I.sample(fn, FP64, mode, 3, 11) == lanes, (fn, mode)
    # atan's sampler is untouched: edge, big, small, random
    assert I.placed_points("atan", FP64, 4).keys() == set(I.REGIONS)


def test_in_main_is_the_models():
    one, S = sf.one_bits(FP64), FP64.sign_mask
    gs = ml.trig_gates(FP64)[0]
    gate = ml._pow2(FP64, gs)
    for x in (0, S, sf.inf_bits(FP64), sf.qnan_bits(FP64)):
        assert I.in_main("asin", FP64, x) is False
        assert I.in_main("acos", FP64, x) is (x in (0, S))   # acos(+-0) main
    assert I.in_main("acos", FP64, one) is False         # acos(+1) is special
    assert I.in_main("acos", FP64, sf.one_bits(FP64, 1)) is True  # acos(-1)
    assert I.in_main("asin", FP64, one) is False and \
        I.in_main("asin", FP64, one + 1) is False
    assert I.in_main("asin", FP64, gate) is True
    assert I.in_main("asin", FP64, gate - 1) is False    # under the tiny gate
    assert I.in_main("acos", FP64, gate - 1) is True     # acos has no tiny path
    assert I.in_main("asin", FP64, ml._pow2(FP64, -1)) is True


@pytest.mark.parametrize("fn", FN2)
def test_structured(fn):
    n = 0
    for fmt in FORMATS:
        for rnd in RND:
            f = fragment_of(fn, fmt, rnd)
            out, lanes = I.check_structured(f)
            assert out == [], out
            n += len(lanes)
            assert all(ml.evaluate(f, x)[1] & MARK for x in lanes)
    # asin: fp64 3 lanes x 2 signs x 3 attributes, then 1 x 2 x 3 at fp128 and
    # fp256; acos: 3 lanes x 5 attributes (one sign) at each format
    assert n == {"asin": 30, "acos": 45}[fn], n
    assert I.structured_lanes(fn, FP64, RTZ) != []
    assert I.structured_lanes("asin", FP64, RNE) == []   # nothing under rne


def test_asins_tiny_family_centre_and_its_neighbours_mark_under_rtz():
    """The study's 3.5: asin(x) = x + x^3/6: at fp64 one centre, 3 2^-25 =
    0x3e78000000000000 (also 6 2^-26 and 12 2^-27 the same float), under rtz,
    rdn and rup, +-1 and +-2 ulps of it too (MEASURED by the drafter on the
    model, here on the fragment)."""
    x0 = 0x3e78000000000000
    for rnd in (RTZ, RDN, RUP):
        f = fragment_of("asin", FP64, rnd)
        for j in (-2, -1, 0, 1, 2):
            for s in (0, FP64.sign_mask):
                assert ml.evaluate(f, (x0 + j) | s)[1] & MARK, (rid(rnd), j)
    for rnd in (RNE, RMM):
        f = fragment_of("asin", FP64, rnd)
        assert not ml.evaluate(f, x0)[1] & MARK
    assert I.structured_lanes("asin", FP64, RTZ) == [
        v for x in (x0 - 1, x0, x0 + 1) for v in (x, x | FP64.sign_mask)]


def test_acos_windows_are_one_signed_and_minus_x0_marks_under_no_attribute():
    """acos is not odd (acos(-x) = pi - acos(x)): the windows next to pi/2 are
    at positive x only; -x0 is not marked under any attribute and is right.
    The census ran positive x (census.py:107 to :108) though its comment says
    +-; MEASURED here on the fragment."""
    assert "acos" in I.ONE_SIGN and "asin" not in I.ONE_SIGN
    for fmt in FORMATS:
        grid, mid = I._ACOS_GRID[fmt.name], I._ACOS_MID[fmt.name]
        S = fmt.sign_mask
        for rnd in RND:
            f = fragment_of("acos", fmt, rnd)
            kinds = (grid if rnd in I._DIRECTED else mid)
            other = (mid if rnd in I._DIRECTED else grid)
            for j in (-1, 0, 1):
                assert ml.evaluate(f, kinds + j)[1] & MARK
                assert not ml.evaluate(f, other + j)[1] & MARK
            for x0 in (grid, mid):
                for j in (-2, -1, 0, 1, 2):
                    xn = (x0 + j) | S
                    bits, fw = ml.evaluate(f, xn)
                    assert not fw & MARK and (bits, fw) == I.golden(
                        fmt, rnd, xn, "acos"), (fmt.name, rid(rnd), j)
        # the lanes are the list's own, no sign flipped
        assert I.structured_lanes("acos", fmt, RTZ) == [grid - 1, grid,
                                                        grid + 1]
        assert I.structured_lanes("acos", fmt, RNE) == [mid - 1, mid, mid + 1]
    # and the specials hold -x0 as a row at every format
    for fmt in FORMATS:
        rows = dict(I.special_rows("acos", fmt))
        assert any("-x0" in k for k in rows)
        assert all(x & fmt.sign_mask for k, v in rows.items() if "-x0" in k
                   for x in v)


@pytest.mark.parametrize("fn", FN2)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_specials(fn, fmt):
    for rnd in RND:
        f = fragment_of(fn, fmt, rnd)
        out, n = I.check_specials(f)
        assert out == [] and n == {"asin": 32, "acos": 34}[fn], (out, n)
    # the study's 23 rows (specials.py) are among the lanes
    lanes = {x for _, rows in I.special_rows(fn, fmt) for x in rows}
    one, S = sf.one_bits(fmt), fmt.sign_mask
    for x in (0, S, sf.inf_bits(fmt), sf.inf_bits(fmt) | S, one, one | S,
              one - 1, (one - 1) | S, one + 1, (one + 1) | S,
              sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)):
        assert x in lanes, hex(x)


def test_the_domain_edge_and_the_specials_by_value():
    """+-1 are main-path lanes; |x| > 1 (infinities, +maxN, 1 + ulp) is the
    quiet NaN and invalid; acos(+1) is +0 exact; asin(+-1) is +-pi/2, inexact."""
    for fmt in FORMATS:
        one, S = sf.one_bits(fmt), fmt.sign_mask
        qn = sf.qnan_bits(fmt)
        for rnd in RND:
            a, c = (fragment_of(fn, fmt, rnd) for fn in FN2)
            for x in (one + 1, (one + 1) | S, sf.max_normal_bits(fmt),
                      sf.inf_bits(fmt), sf.inf_bits(fmt) | S):
                assert ml.evaluate(a, x) == ml.evaluate(c, x) == (qn, 0x01)
            assert ml.evaluate(c, one) == (0, 0)
            bits, fw = ml.evaluate(a, one)
            assert fw == 0x10 and bits == I.golden(fmt, rnd, one, "asin")[0]
            assert ml.evaluate(a, one | S)[1] == 0x10
            assert ml.evaluate(c, 0) == I.golden(fmt, rnd, 0, "acos")
            assert ml.evaluate(c, S)[1] == I.golden(fmt, rnd, S, "acos")[1]
            # sNaN: a quiet NaN and invalid; qNaN: quiet, no flag
            sn = sf.snan_bits(fmt)
            assert ml.evaluate(a, sn) == ml.evaluate(c, sn) == (qn, 0x01)
            assert ml.evaluate(a, qn) == ml.evaluate(c, qn) == (qn, 0x00)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_shape(fmt):
    builds = {(fn, r): build_of(fn, fmt, r) for fn in FN2 for r in RND}
    assert I.check_shape_unary2(fmt, builds) == []
    for fn in FN2:
        f = fragment_of(fn, fmt, RNE)
        assert (len(f), len(f.words), f.live_max()) == SHAPE_WANT[(fn, fmt.name)]
        assert I.SHAPE[(fn, fmt.name)] == [SHAPE_WANT[(fn, fmt.name)]] * 5
        c = f.counts()
        assert (c.get("min", 0), c.get("max", 0)) == (1, 1)
        # the model's phases (costs.*.out.txt, READ by the drafter)
        b = build_of(fn, fmt, RNE)
        by = {}
        for i in b.live_indices():
            by[b.phase_of[i]] = by.get(b.phase_of[i], 0) + 1
        assert by == I.model_phases(fn, fmt.name)
        assert by["sqrt"] == {"fp64": 36, "fp128": 40, "fp256": 44}[fmt.name]
    # the caps are the measured maxima, and one under fails by name
    for fn in FN2:
        f = fragment_of(fn, fmt, RNE)
        assert ml.invariants(f, live_cap=16) == []
        assert ml.invariants(f, live_cap=15) == ["16 values live at once, "
                                                 "past 15"]
        assert ml.INV_LIVE_CAP[fn][fmt.name] == 16
    # the flag words: asin takes five, acos four (no underflow: no tiny path)
    assert routines.flag_words(fragment_of("asin", fmt, RNE)) == \
        frozenset({0x0, 0x1, 0x10, 0x18, 0x90})
    assert routines.flag_words(fragment_of("acos", fmt, RNE)) == \
        frozenset({0x0, 0x1, 0x10, 0x90})


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_front_is_shared(fmt):
    """The study's 2.1: asin's and acos's fragments of one argument under
    cftc's keying come to 255, 269, 290 instructions together (438, 466, 508
    apart): a front written twice is larger."""
    want = {"fp64": (255, 438), "fp128": (269, 466), "fp256": (290, 508)}
    assert I.SHARE == want
    assert I.check_share(fmt) == []
    for rnd in RND:
        a, c = fragment_of("asin", fmt, rnd), fragment_of("acos", fmt, rnd)
        assert I.share_count([a, c]) == want[fmt.name]
        assert len(a) + len(c) == want[fmt.name][1]
    # the instructions up to C and sigma are the same: acos adds only its own
    a, c = fragment_of("asin", fmt, RNE), fragment_of("acos", fmt, RNE)
    together, apart = I.share_count([a, c])
    assert together - len(a) == {"fp64": 34, "fp128": 34, "fp256": 34}[fmt.name]
    # ... and the replay can tell: two copies of asin are one asin
    assert I.share_count([a, a])[0] == len(a)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_audit(fmt):
    for fn in FN2:
        out, t = I.check_audit_own(fmt, fn)
        assert out == [], out
        assert t["lanes"] == 1260 == len(I.audit_own_lanes(fmt))
        assert (t["premise"], t["inexact"], t["past"], t["wrong"]) == \
            (0, 0, 0, 0)
        # MEASURED: the largest |theta0 - atan(n/d)| over the bound, log2
        assert -7 < t["largest"] < -5
        # M4G1's leg, through the core, and the matrix's audit are green
        assert I.check_audit_both(fmt, fn) == []


def test_the_audit_through_the_own_lanes_cannot_see_sterbenz_bias():
    """The study's 8, item 2, MEASURED by the drafter on the model and here on
    the fragments: the plant breaks no premise, leaves no difference inexact
    and makes no lane wrong on asin's and acos's own lanes (the index never
    reaches k = 1 below t = 1/16 on them: the seed underestimates 1/d there,
    d being about 0.998 at the bottom of RECIP_SEED's cell 510); it is M4G1's
    audit through the core that holds it, and the matrix's audit sees it
    there."""
    for fmt in (FP64, FP128):
        for fn in FN2:
            out, t = I.check_audit_own(fmt, fn, "sterbenz_bias")
            assert out == [] and (t["premise"], t["inexact"], t["past"],
                                  t["wrong"]) == (0, 0, 0, 0), (fmt.name, fn)
            both = I.check_audit_both(fmt, fn, "sterbenz_bias")
            assert both and all(s.startswith("audit: ") for s in both)
            core = I.check_audit(fmt, "sterbenz_bias")[0]
            assert both == core and "outside [1/2, 2]" in core[0]


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_constants(fmt):
    findings, lines = I.check_constants(formats=(fmt,))
    assert findings == []
    got = {s.split(":")[0]: int(s.split(": ")[2].split()[0])
           for s in lines if "derived constants" in s}
    # MEASURED (derived constants in five fragments): atan's 295, 335, 410 and
    # beside it asin's and acos's own roles (TINYU, HALF for both; GATE and
    # TINY_EPS for asin; PIH and PIL for acos): ten more for asin, ten for acos
    assert got[f"asin {fmt.name}"] == got[f"acos {fmt.name}"] \
        == {"fp64": 305, "fp128": 345, "fp256": 420}[fmt.name]


def test_constants_as_a_program_list_asin_and_acos_at_three_formats():
    r = T._run_module("--check", "--only", "inv")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    for fn in FN2:
        assert sum(s.startswith(f"{fn} fp") for s in lines) == 3, fn
    assert "DIFFERENCE" not in r.stdout
    assert lines[-1].endswith("0 differences")


# =====================================================================
# every leg of every check can fail alone
# =====================================================================

class Doctored:
    """A Build whose run() is the base's with `fix(res, fl, probes)` applied:
    a stand-in for the one leg a test makes fail."""

    def __init__(self, base, fix):
        self.base, self.fix = base, fix
        self.meta, self.fmt, self.rnd = base.meta, base.fmt, base.rnd

    def run(self, lane, want=()):
        res, fl, pr = self.base.run(lane, want)
        return self.fix(res, fl, dict(pr))


def test_each_leg_of_the_own_lane_audit_can_fail_alone():
    fmt, fn = FP64, "asin"
    base = build_of(fn, fmt, RNE)
    lanes = I.audit_own_lanes(fmt)[::5]
    # a lane the index sends to k >= 1, to doctor the premise on
    assert any(base.run(x, ("Kk",))[2]["Kk"] != ml._enc_exact(
        fmt, Fraction(3, 2) * 2 ** 52) for x in lanes)
    out, t = I.check_audit_own(fmt, fn, lanes=lanes, b=Doctored(
        base, lambda r, f, p: (r, f, p)))
    assert out == [] and t["lanes"] == len(lanes)

    def premise(r, f, p):
        # n_h = 1, P = 1/8: the ratio is 8, and 1 - 1/8 = 7/8 is exact
        p["nh"], p["P"] = ml._enc(fmt, Fraction(1)), ml._enc(fmt,
                                                              Fraction(1, 8))
        p["Nh0"] = ml._enc(fmt, Fraction(7, 8))
        return r, f, p
    # (the doctored n_h also moves the bound's n: the other legs are checked
    # by their own counts)
    out, t = I.check_audit_own(fmt, fn, lanes=lanes, b=Doctored(base, premise))
    assert t["premise"] > 0 and t["inexact"] == 0
    assert any("outside [1/2, 2]" in s and s.startswith("audit: ")
               for s in out)

    def inexact(r, f, p):
        p["Nh0"] += 1
        return r, f, p
    out, t = I.check_audit_own(fmt, fn, lanes=lanes, b=Doctored(base, inexact))
    assert t["inexact"] > 0 and t["premise"] == 0 and t["past"] == 0 \
        and t["wrong"] == 0
    assert len(out) == 1 and "n_h - P inexact" in out[0] \
        and out[0].startswith("audit: ")

    def past(r, f, p):
        p["th"] += 1
        return r, f, p
    out, t = I.check_audit_own(fmt, fn, lanes=lanes, b=Doctored(base, past))
    assert t["past"] > 0 and t["premise"] == 0 and t["inexact"] == 0 \
        and t["wrong"] == 0
    assert len(out) == 1 and "past 2^-(p+G) theta0" in out[0]

    def wrong(r, f, p):
        return r ^ 1, f & ~MARK, p
    out, t = I.check_audit_own(fmt, fn, lanes=lanes, b=Doctored(base, wrong))
    assert t["wrong"] == len(lanes) and t["past"] == 0 and t["premise"] == 0
    assert len(out) == 1 and "unmarked lanes differ from transcend.asin" \
        in out[0]

    def marked(r, f, p):             # a marked lane may differ: not a finding
        return r ^ 1, f | MARK, p
    assert I.check_audit_own(fmt, fn, lanes=lanes,
                             b=Doctored(base, marked))[1]["wrong"] == 0
    # the matrix's audit is both legs: the core's, and then this one
    assert I.check_audit_both(fmt, fn, lanes=lanes) == []
    # a plant outside the core leaves the core leg green (refused there by
    # name) and the own-lane leg red: u_low_dropped
    out = I.check_audit_both(fmt, fn, "u_low_dropped", lanes)
    assert out and all(s.startswith("audit: ") for s in out)
    with pytest.raises(ValueError, match="does not apply to inv_core"):
        I.core_of(fmt, "u_low_dropped")


def test_the_audit_lanes_are_placed_at_the_cells_ends_and_1_16():
    lanes = I.audit_own_lanes(FP64)
    assert len(lanes) == 63 * 2 * 5 * 2
    assert len(set(lanes)) == len(lanes)
    # both mirrors, both signs: n = |x| (x < w) and n = w (|x| > w)
    b = build_of("asin", FP64, RNE)
    swaps = set()
    ts = []
    for x in lanes[::10]:
        _r, _f, pr = b.run(x, ("nh", "nl", "dh", "dl", "wh"))
        swaps.add(pr["nh"] == pr["wh"])
        n = ml._dec(FP64, pr["nh"]) + ml._dec(FP64, pr["nl"])
        d = ml._dec(FP64, pr["dh"]) + ml._dec(FP64, pr["dl"])
        assert 0 < n <= d + Fraction(1, 2 ** 50)
        ts.append(n / d)
    assert swaps == {True, False}
    # t just below and just above 1/16, and the cells' ends
    assert min(abs(t - Fraction(1, 16)) for t in ts) < Fraction(1, 2 ** 12)
    assert any(t < Fraction(1, 16) for t in ts) and any(
        t > Fraction(1, 16) for t in ts)


def test_each_leg_of_the_sharing_can_fail_alone():
    fmt = FP64
    frags = {(fn, r): fragment_of(fn, fmt, r) for fn in FN2 for r in RND}
    assert I.check_share(fmt, fragments=frags) == []
    g = frags[("acos", RNE)]

    def with_body(body):
        return routines.Fragment(g.op, g.fmt, g.rnd, g.inputs, body, g.result,
                                 g.flags, g.words, g.stage)
    # one front instruction changed: the first IAND (|x|) reads its operands
    # in the other order (the same function, a different key), so nothing of
    # acos's front is asin's: the leg is red and nothing else is
    body = list(g.body)
    op, r, srcs = body[0]
    assert op == sf.OP_IAND and srcs[0][0] == "in"
    body[0] = (op, r, tuple(reversed(srcs)))
    doc = with_body(body)
    out = I.check_share(fmt, fragments={**frags, ("acos", RNE): doc})
    assert len(out) == 1 and out[0].startswith("shape: asin and acos fp64 rne:")
    assert "the front is not shared" in out[0]
    together, apart = I.share_count([frags[("asin", RNE)], doc])
    assert apart == 438 and together > 255
    # and in the middle of the front: the first FMA's attribute changed
    body = list(g.body)
    k = next(i for i, (o, r_, s) in enumerate(body) if o == sf.OP_FMA)
    o, r_, s = body[k]
    body[k] = (o, RTZ if r_ != RTZ else RDN, s)
    out = I.check_share(fmt, fragments={**frags, ("acos", RNE): with_body(body)})
    assert len(out) == 1 and "the front is not shared" in out[0]
    # a pinned figure that is wrong
    out = I.check_share(fmt, want={"fp64": (256, 438)})
    assert len(out) == 5 and all("256 (438)" in s for s in out)
    # shape's own sharing leg sees it too (beside the reorder leg, which the
    # changed operand order also fails: the graph is no longer the build's)
    builds = {(fn, r): build_of(fn, fmt, r) for fn in FN2 for r in RND}
    out = I.check_shape_unary2(fmt, builds, fragments={
        **frags, ("acos", RNE): doc})
    assert sum("the front is not shared" in s for s in out) == 1


def test_each_other_leg_of_shape_can_fail_alone():
    fmt = FP64
    builds = {(fn, r): build_of(fn, fmt, r) for fn in FN2 for r in RND}
    assert I.check_shape_unary2(fmt, builds) == []

    def legs(text, tables, n):
        out = I.check_shape(fmt, builds, tables=tables)
        assert len(out) == n and all(text in s and s.startswith("shape: ")
                                     for s in out), (text, out)
    shape = dict(I.SHAPE)
    shape[("asin", "fp64")] = [(222, 56, 16)] + I.SHAPE[("asin", "fp64")][1:]
    legs("pinned 222, 56, 16", I.Tables(shape=shape), 1)
    shape = dict(I.SHAPE)
    shape[("acos", "fp64")] = [(217, 55, 16)] * 5
    legs("pinned 217, 55, 16", I.Tables(shape=shape), 5)
    legs("instructions by phase differ from the model's",
         I.Tables(phases=lambda fn, name: dict(I.model_phases(fn, name),
                                               sqrt=35)), 10)
    legs("the flag word takes", I.Tables(flag_words={
        **I.FLAG_WORDS, "acos": I.FLAG_WORDS["acos"] | {0x18}}), 5)
    legs("MIN and", I.Tables(min_max={**I.MIN_MAX, "asin": (2, 1)}), 5)
    legs("MAX instructions", I.Tables(min_max={**I.MIN_MAX,
                                               "acos": (1, 0)}), 5)
    caps = {**ml.INV_LIVE_CAP, "asin": {**ml.INV_LIVE_CAP["asin"],
                                        "fp64": 17}}
    legs("the cap is 17", I.Tables(caps=caps), 1)
    # a cap one under fails by name
    caps = {**ml.INV_LIVE_CAP, "acos": {**ml.INV_LIVE_CAP["acos"],
                                        "fp64": 15}}
    out = I.check_shape(fmt, builds, tables=I.Tables(caps=caps))
    assert any("the cap is 15, the most values live under any attribute is "
               "16" in s for s in out)
    assert any("invariants: 16 values live at once, past 15" in s for s in out)
    # the reorder leg: a misnumbered operand, and a forward read
    frags = {k: b.fragment() for k, b in builds.items()}
    key = ("asin", RNE)
    out = I.check_shape(fmt, builds, fragments={
        **frags, key: ml._misnumbered(frags[key])})
    assert any("reorder" in s and "dataflow graph is not the design's" in s
               for s in out)
    out = I.check_shape(fmt, builds, fragments={
        **frags, key: ml._forward(frags[key])})
    assert any("not a topological order" in s for s in out)


def test_each_leg_of_pools_can_fail_alone():
    f = fragment_of("asin", FP64, RTZ)
    listed, plain, one = 0x3e78000000000000, 0x3fe0000000000000,         0x3ff0000000000000
    xs = [listed, plain, one]
    clean = [ml.evaluate(f, x) for x in xs]
    assert clean[0][1] & MARK and not clean[1][1] & MARK
    # no lane is committed for asin: the list is empty, so the marked lane is
    # off it, and a list that holds it makes the run clean
    out, t = I.check_pools(f, xs, results=clean)
    assert len(out) == 1 and "marked off the committed list" in out[0]
    out, t = I.check_pools(f, xs, results=clean, marks={listed: "x"})
    assert out == [] and (t.n, len(t.marked), t.marked_right) == (3, 1, 1)
    cases = {
        "unmarked lanes differ from transcend.asin":
            T._doctor(clean, 1, bits=1),
        "flag words carry bits other than [4:0] and the mark":
            T._doctor(clean, 0, orwith=0x20),
        "marked off the committed list": T._doctor(clean, 1, orwith=0x80),
        "on the committed list are not marked":
            T._doctor(clean, 0, andnot=0x80),
    }
    for text, results in cases.items():
        out, t = I.check_pools(f, xs, results=results, marks={listed: "x"})
        assert len(out) == 1 and text in out[0]             and out[0].startswith("pools: "), (text, out)
    out, t = I.check_pools(f, xs, results=T._doctor(clean, 0, bits=1),
                           marks={listed: "x"})
    assert out == [] and len(t.guess_wrong) == 1 and t.marked_right == 0
    marks = (("acos", "fp64", "rne", listed, "a reason"),)
    assert I.pool_marks("acos", "fp64", "rne", marks) == {listed: "a reason"}
    assert I.pool_marks("asin", "fp64", "rne", marks) == {}


def test_each_leg_of_structured_can_fail_alone():
    f = fragment_of("asin", FP64, RTZ)
    out, lanes = I.check_structured(f)
    assert out == [] and len(lanes) == 6
    out, _ = I.check_structured(
        f, evaluator=lambda g, x: (lambda r: (r[0], r[1] & 0x1F))(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "6 of the 6 committed lanes are not marked" \
        in out[0] and out[0].startswith("structured: ")
    out, _ = I.check_structured(
        f, evaluator=lambda g, x: (lambda r: (r[0] ^ 1, r[1]))(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "marked lanes have a guess that differs from " \
        "transcend.asin" in out[0]
    # a listed lane whose guess is right
    out, _ = I.check_structured(f, wrong={("asin", "fp64", RTZ): {
        0x3e78000000000000}})
    assert len(out) == 1 and "listed as having a wrong guess have the right" \
        in out[0]
    # acos: the lanes are one-signed, so a table of one lane gives one lane,
    # and the pinned wrong guess of fp128's centre is a pin that can fail
    g = fragment_of("acos", FP128, RTZ)
    out, lanes = I.check_structured(g)
    assert out == [] and len(lanes) == 3
    assert I.STRUCT_GUESS_WRONG[("acos", "fp128", RTZ)] == {
        I._ACOS_GRID["fp128"]}
    out, _ = I.check_structured(g, wrong={})
    assert len(out) == 1 and "1 marked lanes have a guess" in out[0]
    out, _ = I.check_structured(g, table={"acos": {}})
    assert (out, _) == ([], [])
    # the sign: a table lane is taken as listed for acos (ONE_SIGN), flipped
    # for asin (and for atan, unchanged by this parcel)
    tab = {"acos": {"fp64": [((RTZ,), [0x3c91a62633145c07])]},
           "asin": {"fp64": [((RTZ,), [0x3e78000000000000])]},
           "atan": {"fp64": [((RTZ,), [0x3e68000000000000])]}}
    assert I.structured_lanes("acos", FP64, RTZ, tab) == [0x3c91a62633145c07]
    assert I.structured_lanes("asin", FP64, RTZ, tab) == [
        0x3e78000000000000, 0xbe78000000000000]
    assert I.structured_lanes("atan", FP64, RTZ, tab) == [
        0x3e68000000000000, 0xbe68000000000000]
    # a pair is flipped in y alone (the function of the other parcel), for a
    # function not in ONE_SIGN
    tab = {"pairfn": {"fp64": [((RTZ,), [(0x3ff0000000000000, 5)])]}}
    assert I.structured_lanes("pairfn", FP64, RTZ, tab) == [
        (0x3ff0000000000000, 5), (0xbff0000000000000, 5)]


def test_each_leg_of_seq_can_fail_alone():
    f = fragment_of("asin", FP64, RTZ)
    xs = [0x3ff0000000000000, 0x3fe0000000000000, 0x3e78000000000000, 0x1,
          0x7ff0000000000000]
    out, lanes = I.check_seq(f, xs)
    assert out == [] and len(lanes) == len(set(lanes))
    assert set(I.structured_lanes("asin", FP64, RTZ)) <= set(lanes)
    assert len(lanes) > 5
    out, _ = I.check_seq(f, xs, evaluator=lambda g, x: (
        ml.evaluate(g, x)[0] ^ 1, ml.evaluate(g, x)[1]))
    assert len(out) == 1 and f"seq.py and evaluate() differ on {len(lanes)} " \
        "lanes" in out[0]
    # a flag left loud: the harness moves QUIET past the third MUL by default,
    # which for atan raises on +inf; asin's and acos's first MULs are the
    # root's and raise nothing on a lane the result does not, so the default
    # shows nothing (a limit of the leg, not of the fragments) and the leg is
    # run with the eighth MUL, which raises invalid on +inf (MEASURED: 0x11
    # raised, 0x1 wanted)
    assert I.check_seq(f, xs, loud=True)[0] == []
    real = I._loud
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(I, "_loud", lambda prog, bank, fmt: real(prog, bank, fmt, 8))
        for fn in FN2:
            out, _ = I.check_seq(fragment_of(fn, FP64, RTZ), xs, loud=True)
            assert out and all("raised" in s for s in out)
            assert any("lane 0x7ff0000000000000 raised 0x11, want 0x1" in s
                       for s in out), out
    assert I.check_seq(f, xs, loud=False)[0] == []
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(r, "flags", r.flags
                                                        ^ 1), r)[1])
    assert len(out) == 1 and "FLAGS" in out[0] and "OR of the lanes" in out[0]
    out, _ = I.check_seq(f, xs, post=lambda r: (setattr(
        r, "status", r.status ^ 0x40), r)[1])
    assert len(out) == 1 and "STATUS[6]" in out[0]
    # unmarked lanes wrong the same way on seq.py and in evaluate()
    bad = fragment_of("asin", FP64, RNE, "sl_dropped")
    out, _ = I.check_seq(bad, [0x3fe0000000000001 + 5 * 2 ** 40])
    out, _ = I.check_seq(fragment_of("asin", FP64, RNE, "domain_edge"),
                         [0x3ff0000000000000])
    assert any("unmarked lanes on seq.py differ from transcend.asin" in s
               for s in out) and any("deposited" in s for s in out)
    assert not any("seq.py and evaluate()" in s for s in out)
    # the card case: asin(3 2^-25) under rtz is the marked lane, and a
    # fragment that never marks it is red here
    silent = fragment_of("asin", FP64, RTZ, "mark_silenced")
    out, _ = I.check_seq(silent, [0x3ff0000000000000])
    assert any("committed lanes are not marked in the lane's byte" in s
               for s in out)
    assert I.SEQ_MARKED[("asin", "fp64", RTZ)] == 0x3e78000000000000


def test_each_leg_of_bound_can_fail_alone():
    b = build_of("acos", FP64, RNE)
    xs = I.sample("acos", FP64, "edge", 6, 5)
    out, (worst, main, lanes) = I.check_bound(b, xs)
    assert out == [] and main == lanes == 6 and worst < 0
    wide = build_of("acos", FP64, RNE, "bound_loose")
    out, _ = I.check_bound(wide, xs)
    assert len(out) == 1 and "6 of 6 main-path lanes are past the bound" \
        in out[0] and out[0].startswith("bound: ")
    # a lane that differs from transcend.py with V right (not a main-path
    # lane): acos(+1) answered by the domain edge, at the edge
    off = build_of("acos", FP64, RNE, "domain_edge")
    out, (worst, main, lanes) = I.check_bound(off, [0x3ff0000000000000])
    assert len(out) == 1 and "1 unmarked lanes differ from transcend.acos" \
        in out[0] and main == 0
    # V exact: a lane where V equals the true value contributes no ratio
    assert I.check_bound(b, [0])[1][1] == 1       # acos(0) = pi/2: in main


def test_each_leg_of_specials_can_fail_alone():
    f = fragment_of("acos", FP64, RNE)
    out, n = I.check_specials(f)
    assert out == [] and n == 34
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] ^ 1) if x == sf.inf_bits(FP64) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+inf, -inf': 1 of 2 lanes differ" in out[0]
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0] ^ 1, r[1]) if x == 0 else r)(ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+0, -0'" in out[0]
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == sf.one_bits(FP64) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+1, -1'" in out[0] \
        and "differ or are marked" in out[0]
    # -x0 of the windows is a row, and a marked answer there is a finding
    x0 = I._ACOS_GRID["fp64"] | FP64.sign_mask
    out, _ = I.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] | 0x80) if x == x0 else r)(ml.evaluate(g, x)))
    assert len(out) == 1 and "-x0 of the windows next to pi/2" in out[0]
    out, n = I.check_specials(f, rows=[("one row", [0x3ff0000000000000])])
    assert out == [] and n == 1


def test_each_leg_of_constants_can_fail_alone():
    """One word changed at a time: the difference is named by fragment and
    word, for every role of asin's and acos's own and the shared ones they
    ask beside atan's."""
    own = {"asin": ["PIO2H", "PIO2L", "TINYU", "HALF", "GATE", "TINY_EPS"],
           "acos": ["PIO2H", "PIO2L", "PIH", "PIL", "TINYU", "HALF"]}
    shared = ["TH3", "TL4", "A_Y9", "A_CH3", "A_CL3", "MAGIC", "MSEL", "KBIT1",
              "BREL", "MINN", "SIGN", "INF", "QNAN", "ABSM", "ONE", "ZERO",
              "FL_UNDER_INEXACT"]
    for fn in FN2:
        assert T._constants_of(ml.build(fn, FP64, RNE)) == []
        for role in own[fn] + shared:
            for fmt, rnd in ((FP64, RNE), (FP128, RDN), (FP256, RUP)):
                if role == "A_Y9" and fmt is FP256:
                    continue
                bad = T._fresh_with(fn, fmt, rnd, role)
                found = T._constants_of(bad)
                assert found and all(s.startswith("constants: ")
                                     for s in found), (fn, role)
                assert any(f"{fn} {fmt.name} {rid(rnd)} {role}:" in s
                           for s in found), (fn, fmt.name, role, found)
    # the low words are checked against what the high word leaves, and the
    # exponent of TINYU against the IEEE fields (not fmt.emin): one exponent
    # off, in both directions
    for delta in (1 << 52, -(1 << 52)):
        found = T._constants_of(T._fresh_with("asin", FP64, RNE, "TINYU",
                                              delta))
        assert any("asin fp64 rne TINYU:" in s for s in found)
    # a role no derivation asks, and a word with no role
    found = T._constants_of(T._fresh_with("acos", FP64, RNE,
                                          extra_role=("EXTRA", 0x1234)))
    assert len(found) == 1 and "derived but not checked: ['EXTRA']" in found[0]
    b = ml.build("asin", FP64, RNE)
    name = b.roles["TINYU"][1]
    b.roles = {r: ref for r, ref in b.roles.items() if ref[1] != name}
    assert any("words the fragment holds with no role" in s
               for s in T._constants_of(b))
    # a role the build lacks is named
    b = ml.build("acos", FP64, RNE)
    del b.roles["PIL"]
    assert any("acos fp64 rne: the fragment has no constant PIL" in s
               for s in T._constants_of(b))
    # the tiny path's eps has its sign checked: asin's +2^-(p+2), not atan's
    b = ml.build("asin", FP64, RNE)
    name = b.roles["TINY_EPS"][1]
    b.words[name] = ml._enc(FP64, -Fraction(1, 2 ** 55))
    assert any("asin fp64 rne TINY_EPS:" in s for s in T._constants_of(b))


# =====================================================================
# the plants: each red in its checks and green in the others
# =====================================================================

# Every row lists EVERY check, red or green (a test fails on a row that omits
# one). MEASURED on fp64 by this parcel: python/tests/mathlib_inv_harness.py
# red_checks_asin_acos(plant, fn) is the run (pools and seq under rne and rtz,
# bound over five regions of 48 points under rne, structured, specials and
# shape, with the sharing, under all five attributes, audit and constants
# under rne). Where the study (docs/studies/m4/plants.fp64.out.txt) has the
# cell, the cell is its: newton-short, sl-dropped, bound-loose and
# mark-silenced red in structured; sl-dropped in specials; domain-edge in pools
# and specials; u-low-dropped in pools, bound and specials; and sqrt-product in
# the bound alone among the lane checks (pools, seq, structured, specials,
# audit green). The rest are this parcel's, and where a cell differs from what
# the study's table would suggest it says so:
#   * sterbenz_bias: red in audit through the CORE leg (M4G1's check_audit, the
#     only audit leg that sees it); the own-lane leg is green by design (the
#     index never reaches k = 1 below t = 1/16 on these lanes), shown in
#     test_the_audit_through_the_own_lanes_cannot_see_sterbenz_bias. Its
#     shape cell is the sharing's: the plant changes asin's (or acos's) body
#     and not the other's, so the two no longer share their front.
#   * every plant that changes an instruction, a word or the front is red in
#     shape; two_sum_all is red in shape alone (a fault of the shape).
#   * domain_edge is also red in constants: its ONEM word has no role (the
#     derivation asks none), the wanted "derived but not checked".
#   * acos_quadrant is red in audit through the own-lane leg's "wrong" part
#     (the lane differs from transcend.py), not through the index.
CHECKS_ASIN = I.CHECKS_ASIN
_CORE10 = ("table_entry", "coef", "newton_short", "sterbenz_bias",
           "zl_dropped", "sl_dropped", "pio2_low", "bound_loose",
           "mark_silenced", "two_sum_all")
PLANTED_ASIN = [
    ("table_entry", ("pools", "seq", "bound", "shape", "audit", "constants"),
     ("structured", "specials")),
    ("coef", ("bound", "shape", "audit", "constants"),
     ("pools", "seq", "structured", "specials")),
    ("newton_short", ("seq", "bound", "structured", "shape", "audit"),
     ("pools", "specials", "constants")),
    ("sterbenz_bias", ("shape", "audit", "constants"),
     ("pools", "seq", "bound", "structured", "specials")),
    ("zl_dropped", ("bound", "shape", "audit"),
     ("pools", "seq", "structured", "specials", "constants")),
    ("sl_dropped", ("pools", "seq", "bound", "structured", "specials", "shape",
                    "audit"), ("constants",)),
    ("pio2_low", ("pools", "seq", "bound", "specials", "shape", "audit",
                  "constants"), ("structured",)),
    ("bound_loose", ("seq", "bound", "structured", "constants"),
     ("pools", "specials", "shape", "audit")),
    ("mark_silenced", ("seq", "structured", "shape"),
     ("pools", "bound", "specials", "audit", "constants")),
    ("two_sum_all", ("shape",),
     ("pools", "seq", "bound", "structured", "specials", "audit",
      "constants")),
    ("tiny_gate_off", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "structured", "audit")),
    ("tiny_side", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "structured", "audit")),
    ("domain_edge", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "structured", "audit")),
    ("u_low_dropped", ("pools", "seq", "bound", "specials", "shape", "audit"),
     ("structured", "constants")),
    ("sqrt_product", ("bound", "shape"),
     ("pools", "seq", "structured", "specials", "audit", "constants")),
]
PLANTED_ACOS = [
    ("table_entry", ("pools", "bound", "shape", "audit", "constants"),
     ("seq", "structured", "specials")),
    ("coef", ("bound", "shape", "audit", "constants"),
     ("pools", "seq", "structured", "specials")),
    ("newton_short", ("bound", "structured", "shape", "audit"),
     ("pools", "seq", "specials", "constants")),
    ("sterbenz_bias", ("shape", "audit", "constants"),
     ("pools", "seq", "bound", "structured", "specials")),
    ("zl_dropped", ("bound", "shape", "audit"),
     ("pools", "seq", "structured", "specials", "constants")),
    ("sl_dropped", ("pools", "seq", "bound", "structured", "specials", "shape",
                    "audit"), ("constants",)),
    ("pio2_low", ("pools", "seq", "bound", "structured", "specials", "shape",
                  "audit", "constants"), ()),
    ("bound_loose", ("seq", "bound", "structured", "constants"),
     ("pools", "specials", "shape", "audit")),
    ("mark_silenced", ("seq", "structured", "shape"),
     ("pools", "bound", "specials", "audit", "constants")),
    ("two_sum_all", ("shape",),
     ("pools", "seq", "bound", "structured", "specials", "audit",
      "constants")),
    ("domain_edge", ("pools", "seq", "specials", "shape", "constants"),
     ("bound", "structured", "audit")),
    ("u_low_dropped", ("pools", "bound", "specials", "shape", "audit"),
     ("seq", "structured", "constants")),
    ("sqrt_product", ("bound", "shape"),
     ("pools", "seq", "structured", "specials", "audit", "constants")),
    ("acos_quadrant", ("pools", "seq", "bound", "specials", "shape", "audit"),
     ("structured", "constants")),
]
PLANTED = {"asin": PLANTED_ASIN, "acos": PLANTED_ACOS}
ROWS = [(fn, row) for fn in FN2 for row in PLANTED[fn]]


@functools.lru_cache(maxsize=None)
def _red(plant, fn):
    # every third of the own-lane audit's 1,260 lanes (a saving of the golden
    # stage's time: the full run, MEASURED in the entry, gives the same rows)
    return I.red_checks_asin_acos(plant, fn, audit_n=3)


def test_the_control_is_green_in_every_check():
    for fn in FN2:
        red = _red(None, fn)
        assert red == {}, (fn, {k: v[:1] for k, v in red.items()})


@pytest.mark.parametrize("fn,row", ROWS, ids=lambda v: v if isinstance(v, str)
                         else v[0])
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(fn, row):
    plant, red, green = row
    got = _red(plant, fn)
    for check in red:
        assert check in got, f"{fn} {plant}: {check} stays green"
        assert all(s.startswith(check + ": ") for s in got[check]), \
            got[check][:2]
    for check in green:
        assert check not in got, f"{fn} {plant}: {check} is red: " \
            f"{got[check][:2]}"


def _check_row(row):
    plant, red, green = row
    assert set(red) | set(green) == set(CHECKS_ASIN), \
        (plant, set(CHECKS_ASIN) - set(red) - set(green))
    assert not set(red) & set(green), plant
    assert len(red) + len(green) == len(CHECKS_ASIN), plant
    assert red, plant


def test_every_row_lists_every_check_and_the_rows_are_the_plants_that_act():
    assert CHECKS_ASIN == ("pools", "seq", "bound", "structured", "specials",
                           "shape", "audit", "constants")
    # asin fifteen: M4G1's twelve and three of ours; acos fourteen: M4G1's ten
    # that act and our four
    assert [r[0] for r in PLANTED_ASIN] == list(_CORE10) + [
        "tiny_gate_off", "tiny_side", "domain_edge", "u_low_dropped",
        "sqrt_product"]
    assert [r[0] for r in PLANTED_ACOS] == list(_CORE10) + [
        "domain_edge", "u_low_dropped", "sqrt_product", "acos_quadrant"]
    assert len(PLANTED_ASIN) == 15 and len(PLANTED_ACOS) == 14
    for fn in FN2:
        for row in PLANTED[fn]:
            _check_row(row)
    rest = tuple(c for c in CHECKS_ASIN if c not in ("bound", "pools"))
    for bad in (("coef", ("bound",), ("pools",)),
                ("coef", ("bound", "pools"), ("pools",) + rest),
                ("coef", (), tuple(CHECKS_ASIN))):
        with pytest.raises(AssertionError):
            _check_row(bad)
    _check_row(("coef", ("bound",), ("pools",) + rest))


def test_every_check_has_a_plant_red_in_it_and_every_plant_is_red_somewhere():
    for fn in FN2:
        red = {c for row in PLANTED[fn] for c in row[1]}
        assert red == set(CHECKS_ASIN), (fn, set(CHECKS_ASIN) - red)
        assert all(row[1] for row in PLANTED[fn])
    for name in ("test_pools", "test_seq", "test_bound", "test_structured",
                 "test_specials", "test_shape", "test_audit",
                 "test_constants"):
        assert callable(globals()[name]), name


def test_the_plants_that_do_not_reach_a_function_are_refused_by_name():
    # asin's tiny path is not acos's, and acos_quadrant is not asin's
    for plant in ("tiny_gate_off", "tiny_side"):
        for fmt in FORMATS:
            with pytest.raises(ValueError, match=f"plant {plant!r} does not "
                               f"apply to acos at {fmt.name}: the fault is "
                               f"not reached"):
                ml.build("acos", fmt, RNE, plant=plant)
            assert ml.build("asin", fmt, RNE, plant=plant).meta["plant"] == plant
    with pytest.raises(ValueError, match="plant 'acos_quadrant' does not apply "
                       "to asin at fp64: the fault is not reached"):
        ml.build("asin", FP64, RNE, plant="acos_quadrant")
    # wave 2's plants are refused by the core by name, as they should be
    for plant in NEW_PLANTS:
        with pytest.raises(ValueError, match=f"plant {plant!r} does not apply "
                           f"to inv_core at fp64"):
            ml.build_inv_core(FP64, plant=plant)
        with pytest.raises(ValueError, match=f"plant {plant!r} does not apply "
                           f"to atan at fp64"):
            ml.build("atan", FP64, RNE, plant=plant)
    for fn in FN2:
        for plant in ("domain_edge", "u_low_dropped", "sqrt_product"):
            assert ml.build(fn, FP128, RTZ, plant=plant).meta["plant"] == plant
        with pytest.raises(ValueError, match="no_such_plant"):
            ml.build(fn, FP64, RNE, plant="no_such_plant")


def test_every_plant_changes_the_build():
    """A plant that did nothing would pass every row green: each is a different
    build from the clean one, in its body or its words."""
    for fn in FN2:
        clean = build_of(fn, FP64, RNE)
        for plant, *_ in PLANTED[fn]:
            b = build_of(fn, FP64, RNE, plant)
            same = (b.body == clean.body and b.words == clean.words
                    and b.result == clean.result and b.flags == clean.flags)
            assert not same, (fn, plant)


# The named cases at fp64 (the study's plants.fp64.out.txt, and this parcel's
# measured lanes where it has none): (function, plant, attribute, lane, kind).
NAMED = [
    ("asin", "domain_edge", RNE, 0x3ff0000000000000, "wrong"),
    ("asin", "domain_edge", RNE, 0xbff0000000000000, "wrong"),
    ("acos", "domain_edge", RNE, 0x3ff0000000000000, "wrong"),
    ("acos", "domain_edge", RNE, 0xbff0000000000000, "wrong"),
    ("asin", "u_low_dropped", RNE, 0x3e58000000000000, "wrong"),
    ("asin", "u_low_dropped", RTZ, 0x3e40000000000000, "wrong"),
    ("acos", "u_low_dropped", RNE, 0xbfe3ffffffffffff, "wrong"),
    ("acos", "acos_quadrant", RNE, 0xbfe0000000000000, "wrong"),
    ("asin", "tiny_gate_off", RNE, 0x1, "wrong"),
    ("asin", "tiny_side", RTZ, 0x1, "wrong"),
    ("asin", "pio2_low", RNE, 0x3fe7ffffffffffff, "wrong"),
]


@pytest.mark.parametrize("fn,plant,rnd,lane,kind", NAMED,
                         ids=[f"{f}-{p}-{rid(r)}-{x:#x}" for f, p, r, x, _
                              in NAMED])
def test_the_named_case_is_reproduced(fn, plant, rnd, lane, kind):
    gold = I.golden(FP64, rnd, lane, fn)
    bits, fw = ml.evaluate(fragment_of(fn, FP64, rnd, plant), lane)
    cbits, cfw = ml.evaluate(fragment_of(fn, FP64, rnd), lane)
    assert not fw & MARK and (bits, fw) != gold and (cbits, cfw) == gold


def test_domain_edge_is_red_on_plus_and_minus_one_and_nowhere_else():
    # the study: asin rne 1 wrong, "+1" (the row of the specials); the plant
    # answers invalid where the definition answers +-pi/2 and acos(+1) = 0
    for fmt in FORMATS:
        one, S = sf.one_bits(fmt), fmt.sign_mask
        for fn in FN2:
            f = fragment_of(fn, fmt, RNE, "domain_edge")
            for x in (one, one | S):
                assert ml.evaluate(f, x) == (sf.qnan_bits(fmt), 0x01)
                assert ml.evaluate(f, x) != I.golden(fmt, RNE, x, fn)
            for x in (one - 1, (one - 1) | S, one + 1, ml._pow2(fmt, -1)):
                assert ml.evaluate(f, x) == ml.evaluate(
                    fragment_of(fn, fmt, RNE), x)
            out = I.check_specials(f)[0]
            assert [s for s in out if "'+1, -1'" in s], (fn, fmt.name)


def test_sqrt_product_is_red_in_the_bound_alone_of_the_lane_checks():
    """The study's 2.4 and 3.6: 1 - x^2 formed directly is exact as a sum, so
    every pool, the specials and the structured lanes pass; the bound check
    finds the root's residual step cannot absorb the unnormalised double word
    near |x| = 1. MEASURED at fp64 on the placed points (48 a region, seed 11):
    asin 6 of 48 big lanes past, the worst 2^+19.35 of Bv; acos 1 of 48 edge
    lanes past at 2^+0.52, and at the worst k of the study's 2.4, x = 1 - k
    2^-p with k = 2^26: asin 2^+24.3 (the study: 2^24.0), acos 2^+38.0 (the
    study: 2.7 x 10^11 Bv = 2^37.9)."""
    one = sf.one_bits(FP64)
    for fn, want_k in (("asin", 24.3), ("acos", 38.0)):
        red = _red("sqrt_product", fn)
        assert set(red) == {"bound", "shape"}, (fn, sorted(red))
        assert all(s.startswith("bound: ") and "past the bound" in s
                   for s in red["bound"])
        b = build_of(fn, FP64, RNE, "sqrt_product")
        c = build_of(fn, FP64, RNE)
        for k in (1 << 20, 3 << 24, 1 << 26):
            r = I.bound_log2(b, one - k)
            assert r > 9 and I.bound_log2(c, one - k) < -5
        assert round(I.bound_log2(b, one - (1 << 26)), 1) == want_k
        # the shape finding is the count: one Fast2Sum fewer, three FMAs
        # fewer, and the two no longer share their front
        f = fragment_of(fn, FP64, RNE, "sqrt_product")
        assert len(f) == {"asin": 216, "acos": 212}[fn]
        # the pools, specials and structured lanes are clean
        for rnd in RND:
            g = fragment_of(fn, FP64, rnd, "sqrt_product")
            assert I.check_specials(g)[0] == [] and \
                I.check_structured(g)[0] == []
        assert I.check_pools(fragment_of(fn, FP64, RNE, "sqrt_product"))[0] \
            == []


def test_u_low_dropped_and_acos_quadrant_are_what_they_say():
    # u_low_dropped: the residual without u_l, so w is wrong in its low bits
    # near |x| = 1: red in pools, bound and specials (the study)
    for fn in FN2:
        red = _red("u_low_dropped", fn)
        assert {"pools", "bound", "specials"} <= set(red)
    # acos_quadrant: acos(-x) answered as acos(|x|), for every x < 0
    f = fragment_of("acos", FP64, RNE, "acos_quadrant")
    g = fragment_of("acos", FP64, RNE)
    for x in (0x3fe0000000000000, 0x3fb999999999999a, 0x3fee666666666666):
        assert ml.evaluate(f, x) == ml.evaluate(g, x)          # x >= 0: the same
        assert ml.evaluate(f, x | FP64.sign_mask) == ml.evaluate(f, x) \
            != ml.evaluate(g, x | FP64.sign_mask)               # x < 0: acos(|x|)
    assert ml.build("acos", FP64, RNE, plant="acos_quadrant").meta["plant"] \
        == "acos_quadrant"


# =====================================================================
# the harness blocks shared with M4G3 (H1 to H3) and the commands
# =====================================================================

def test_the_shared_blocks_leave_atan_as_it_was():
    assert I.ONE_SIGN == {"acos"} or "acos" in I.ONE_SIGN
    lanes = I.structured_lanes("atan", FP64, RNE)
    assert len(lanes) == 8 and lanes[:2] == [
        0x3e68000000000000, 0x3e68000000000000 | FP64.sign_mask]
    assert all(lanes[i] | FP64.sign_mask == lanes[i + 1] | FP64.sign_mask
               and lanes[i + 1] == lanes[i] | FP64.sign_mask
               for i in range(0, 8, 2))
    assert I.placed_points("atan", FP64, 3).keys() == set(I.REGIONS)
    assert I.REGIONS == ("edge", "big", "small", "random")
    assert I.model_phases("atan", "fp64")["recon"] == 23
    with pytest.raises(ValueError, match="no phases of atanh pinned"):
        I.model_phases("atanh", "fp64")
    assert I.model_phases("asin", "fp128")["tail"] == 14
    assert I.model_phases("acos", "fp256")["quotient"] == 21
    assert I.model_phases("acos", "fp64")["recon"] == 22
    assert I.model_phases("asin", "fp64")["special"] == 14


def test_the_inv_commands_take_asin_and_acos(tmp_path, capsys):
    import mathlib_runs as R
    out = tmp_path / "pools.txt"
    R.FINDINGS.clear()
    R.main(["inv-pools", "--fn", "asin,acos", "--quick", "--seq", "--out",
            str(out)])
    shown = capsys.readouterr().out
    for fn in FN2:
        assert f"inv-pools {fn} fp128 rne:" in shown
        assert f"inv-pools {fn} fp128 rtz:" in shown
    assert "RESULT: ok" in shown and "seq.py and the compiled shape" in shown
    R.OUT = None
    R.FINDINGS.clear()
    out2 = tmp_path / "bound.txt"
    R.main(["inv-bound", "--fn", "asin,acos", "--quick", "--formats", "fp64",
            "--out", str(out2)])
    shown = capsys.readouterr().out
    for fn in FN2:
        for region in ("edge", "big", "small", "random", "diag"):
            assert f"inv-bound {fn} fp64 rne {region} seed" in shown, \
                (fn, region)
    assert "a sampled lower bound" in shown and "RESULT: ok" in shown
    R.OUT = None
    R.FINDINGS.clear()
