# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""sin, cos and tan of python/cft_golden/mathlib.py (parcel M2G2a, M2's build,
wave 2, first half) at fp64, fp128 and fp256, held to the study's section 8
(docs/studies/M2-trig.md): quick enough for the golden stage; the larger runs
are `python python/tests/mathlib_runs.py trig-pools` and `trig-bound`.

The checks are python/tests/mathlib_trig_harness.py's, each returning findings
that begin with its own name; the lanes are the radian pools (4,408, 620 and
614 arguments), plants.py's slice of them (387 at fp64), the study's five
placed regions and the structured centres. Eight checks:

  pools  seq  bound  structured  specials  shape  audit  constants

and for every check a planted fault shown red in it, the control green in all
(mathlib.TRIG_PLANTS and the reduction's four: chunk, window, mid_inexact,
exact_add), every leg of every check shown failing alone on a doctored input,
the interface, the refusals, the three-word after-V section, the static proof
of the cushion, the `--check` output and the two commands of mathlib_runs.py.
The port against the study's model is a scratch script of the parcel's entry
(nothing here imports docs/studies/m2): the model's totals are pinned in the
harness (SHAPE, port_phases, UNION_WORDS, SHARED).
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

import mathlib_trig_harness as T  # noqa: E402

PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
FORMATS = T.FORMATS
FUNCS = T.FUNCS
RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = T.RNE, T.RTZ, T.RDN, T.RUP, T.RMM
BY_NAME = T.BY_NAME


def fid(f):
    return f.name


def rid(r):
    return sf.RND_NAMES[r]


# ---- what the study states and the model measured (READ) ---------------------
POOL_SIZES = {"fp64": 4408, "fp128": 620, "fp256": 614}
# the lanes of the pools at or past 2^R (fp128, fp256), marked; none at fp64
RANGE_MARKED = {"fp64": 0, "fp128": 282, "fp256": 291}
# the golden stage's configurations: fp128 at all five attributes, fp64 and
# fp256 under rne and rtz (the box's trig-pools runs all 45)
POOL_CONFIGS = ([(FP128, r) for r in RND] + [(FP64, RNE), (FP64, RTZ),
                                              (FP256, RNE), (FP256, RTZ)])
SEQ_CONFIGS = [(f, r) for f in FORMATS for r in (RNE, RTZ)]
TRIG_PLANT_NAMES = {
    "quadrant_sign", "clamp_tight", "bound_loose", "mark_silenced", "coef",
    "newton_short", "tiny_gate_off", "rl_dropped", "zl_dropped", "clamp_off",
    "sign_after_rounding", "range_unmarked", "cos_zero_operand",
    "inf_flag_dropped"}
REDUCTION_PLANT_NAMES = {"chunk", "window", "mid_inexact", "exact_add"}
CHECKS = ("pools", "seq", "bound", "structured", "specials", "shape", "audit",
          "constants")


@functools.lru_cache(maxsize=None)
def build_of(fn, fmt, rnd, plant=None):
    return T.build_of(fn, fmt, rnd, plant)


def fragment_of(fn, fmt, rnd, plant=None):
    return T.fragment_of(fn, fmt, rnd, plant)


def planted_or_clean(fn, fmt, rnd, plant):
    """The build of fn with the plant, or the clean one where the plant is
    refused by name for fn ("does not apply")."""
    try:
        return build_of(fn, fmt, rnd, plant)
    except ValueError as e:
        if "does not apply" not in str(e):
            raise
        return build_of(fn, fmt, rnd)


def applies(plant, fn, fmt):
    try:
        build_of(fn, fmt, RNE, plant)
    except ValueError as e:
        assert "does not apply" in str(e), (plant, fn, fmt.name, e)
        return False
    return True


# ---- the lanes a plant's checks run on: the least that shows it ---------------

def region_lanes(fmt, n=12, seed=5):
    return [x for r in T.REGIONS for x in T.sample(fmt, r, n, seed)]


@functools.lru_cache(maxsize=None)
def binade_edges():
    """The products' binade edges at fp64 (test_mathlib_reduction.edge_args,
    imported, not edited): the lanes the exact-add plant is seen on and
    random arguments are not (the study's 3.6, item 8)."""
    import test_mathlib_reduction as R
    return tuple(R.edge_args(FP64, R.plan_of("fp64")))


def audit_lanes(plant, fmt):
    xs = list(T.pool_slice(fmt)[::6])
    return xs + list(binade_edges()) if plant == "exact_add" else xs


def run_check(check, plant, fmt, fn, rnd):
    """The findings of `check` on the fragment of fn under rnd planted with
    `plant` (None: the control), on the lanes the plant tables use."""
    b = build_of(fn, fmt, rnd, plant)
    f = b.fragment()
    if check == "pools":
        return T.check_pools(f, xs=list(T.pool_slice(fmt)))[0]
    if check == "seq":
        return T.check_seq(f)[0]
    if check == "bound":
        return T.check_bound(b, region_lanes(fmt)
                             + BOUND_EXTRA.get(plant, []))[0]
    if check == "structured":
        return T.check_structured(f)[0]
    if check == "specials":
        return T.check_specials(f)[0]
    if check == "audit":
        return T.check_audit(b, audit_lanes(plant, fmt))[0]
    if check == "constants":
        return T.check_constants(
            builder=lambda n, ft, r: planted_or_clean(n, ft, r, plant)
            if n == fn or plant in REDUCTION_PLANT_NAMES
            else build_of(n, ft, r), formats=(fmt,))[0]
    if check == "shape":
        builds = {(n, r): (planted_or_clean(n, fmt, r, plant)
                           if n == fn or plant in REDUCTION_PLANT_NAMES
                           else build_of(n, fmt, r))
                  for n in FUNCS for r in RND}
        return T.check_shape(fmt, builds)
    raise ValueError(check)


# =====================================================================
# the interface
# =====================================================================

INTERFACE = ("TRIG_NAMES", "TRIG_LIVE_CAP", "TRIG_PLANTS", "plan_trig",
             "trig_rho", "trig_after", "check_trig_constants")
MEASURED_CAP = {"sin": {"fp64": 26, "fp128": 17, "fp256": 16},
                "cos": {"fp64": 26, "fp128": 17, "fp256": 16},
                "tan": {"fp64": 26, "fp128": 17, "fp256": 16}}


def test_the_interface_is_public_and_documented():
    for n in INTERFACE:
        assert n in ml.__all__, n
    for fn in (ml.plan_trig, ml.trig_rho, ml.trig_after,
               ml.check_trig_constants, ml.build, ml.fragment):
        assert fn.__doc__ and len(fn.__doc__) > 200, fn.__name__
    # the contract the later waves are briefed against, in the docstrings
    for word in ("Vh", "Vl", "Bv", "R1", "R2", "sh", "sl", "ch", "cl", "rho",
                 "KS", "DS", "KC", "DC", "reduction_mid", "bound_shift",
                 "does not apply"):
        assert word in ml.build.__doc__, word
    for word in ("sin_words", "cos_words", "quotient", "inrange",
                 "round-to-odd", "three"):
        assert word in ml.trig_after.__doc__, word


def test_names_is_the_six_and_trig_names_is_beside_it():
    assert ml.NAMES == ("exp", "exp2", "expm1", "log", "log2", "log1p")
    assert ml.TRIG_NAMES == ("sin", "cos", "tan")
    assert not set(ml.NAMES) & set(ml.TRIG_NAMES)
    assert ml.LIVE_CAP == {"fp32": 21, "fp64": 13, "fp128": 13, "fp256": 13}
    assert "BESIDE the six" in ml.__doc__ and "TRIG_NAMES" in ml.__doc__


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_a_trig_fragment_is_a_specialised_fragment_built_once(fn, fmt):
    for rnd in RND:
        f = ml.fragment(fn, fmt, rnd)
        assert isinstance(f, routines.Fragment)
        assert (f.op, f.fmt, f.rnd, f.inputs, f.stage) == (
            fn, fmt, rnd, ("a",), "specialised")
        assert f.result[0] == f.flags[0] == "v"
        assert ml.fragment(fn, fmt, rnd) is f
        assert ml.invariants(f) == []
        # the fragment is the build's own, scheduled: the same graph
        b = build_of(fn, fmt, rnd)
        assert ml.dag_digest(f) == ml.dag_digest(b.fragment(schedule=False))


def test_fp32_is_refused_by_name_and_so_is_a_name_that_is_not_built():
    for fn in FUNCS:
        with pytest.raises(ValueError, match=r"fp32.*Logan's choice.*parcel "
                           r"M2X.*parcel M2F's to build"):
            ml.fragment(fn, FP32, RNE)
        with pytest.raises(ValueError, match="parcel M2F"):
            ml.build(fn, FP32, RNE)
    for name in ("sinh", "asin", "atan", "SIN", "sinpi", ""):
        with pytest.raises(ValueError, match=repr(name)) as e:
            ml.fragment(name, FP64, RNE)
        assert "log1p, sin, cos, tan" in str(e.value)       # both tuples
        with pytest.raises(ValueError, match=repr(name)) as e:
            ml.build(name, FP64, RNE)
        assert "log1p, sin, cos, tan" in str(e.value)
    with pytest.raises(ValueError, match="attribute"):
        ml.build("sin", FP64, 7)
    with pytest.raises(ValueError, match="formats"):
        ml.build("sin", FpFormat("fp16", 5, 10), RNE)
    with pytest.raises(ValueError, match="no_such_plant") as e:
        ml.build("sin", FP64, RNE, plant="no_such_plant")
    assert "quadrant_sign" in str(e.value) and "chunk" in str(e.value)  # both
    # the six's plants are not the trig routines' (only the names that are in
    # TRIG_PLANTS or REDUCTION_PLANTS build): head_short is exp's
    with pytest.raises(ValueError, match="head_short"):
        ml.build("sin", FP64, RNE, plant="head_short")


def test_the_build_has_min_and_max():
    """Build.fmin and Build.fmax (the clamp's): the MIN and MAX instructions
    of the ALU, hash-consed like the others, computing softfloat's."""
    b = ml.Build(FP64, RNE, "minmax")
    x = ("in", "a")
    one = b.word(sf.one_bits(FP64), "ONE")
    lo, hi = b.fmin(x, one), b.fmax(x, one)
    assert b.fmin(x, one) == lo and b.fmax(x, one) == hi != lo
    assert [op for op, _r, _s in b.body] == [sf.OP_MIN, sf.OP_MAX]
    b.finish(lo, hi)
    for bits in (ml._enc(FP64, Fraction(-3)), FP64.sign_mask,
                 ml._enc(FP64, Fraction(1, 2)), sf.one_bits(FP64),
                 ml._enc(FP64, Fraction(5, 2))):
        mn, mx, _p = b.run(bits)
        assert mn == sf.compute(FP64, sf.OP_MIN, bits, sf.one_bits(FP64),
                                0, RNE)[0]
        assert mx == sf.compute(FP64, sf.OP_MAX, bits, sf.one_bits(FP64),
                                0, RNE)[0]
    assert (mn, mx) == (sf.one_bits(FP64), ml._enc(FP64, Fraction(5, 2)))
    # and the six use neither
    for fn in ml.NAMES:
        assert not {op for op, _r, _s in ml.build(fn, FP64, RNE).body} \
            & {sf.OP_MIN, sf.OP_MAX}, fn


@pytest.mark.parametrize("fmt", (FP64, FP128), ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_the_build_keeps_what_the_budget_and_the_rate_law_read(fn, fmt):
    """The contract M2G2b is briefed against (build's docstring): the probes,
    the phases and the meta, and their relations on lanes: R is rnd(V_h +
    V_l) before the clamp, Bv is 2^-(p+G) |V_h| exactly, and the tan's mark is
    the xor of the test's two ends (sin's and cos's are clamped first)."""
    b = build_of(fn, fmt, RNE)
    need = {"Vh", "Vl", "Bv", "R", "R1", "R2", "mk", "sh", "sl", "ch", "cl",
            "rh", "rl", "q", "small"}
    assert need <= set(b.probes), need - set(b.probes)
    assert ("inrange" in b.probes) == (fmt is FP128)
    assert len(b.phase_of) == len(b.body)
    assert set(b.phase_of) <= set(ml.PHASE_ORDER)
    for key in ("fn", "G", "R", "rho", "KS", "DS", "KC", "DC", "exact", "data",
                "two_prod", "reduction", "reduction_mid"):
        assert key in b.meta, key
    p, G = fmt.prec, b.meta["G"]
    n = 0
    for x in (T.sample(fmt, "edge", 2, 5) + T.sample(fmt, "random", 2, 5)
              + T.sample(fmt, "small", 2, 5)):
        _res, _fl, pr = b.run(x, tuple(need))
        n += 1
        # ADD reads its operands a and c (asm.OP_FIELDS)
        assert pr["R"] == sf.compute(fmt, sf.OP_ADD, pr["Vh"], 0, pr["Vl"],
                                     RNE)[0]
        assert ml._dec(fmt, pr["Bv"]) == abs(ml._dec(fmt, pr["Vh"])) \
            / 2 ** (p + G)
        if fn == "tan":
            assert pr["mk"] == pr["R1"] ^ pr["R2"]
    assert n == 6


def test_the_cap_per_function_and_format_is_the_measured_maximum():
    assert ml.TRIG_LIVE_CAP == MEASURED_CAP
    for fn in FUNCS:
        assert set(ml.TRIG_LIVE_CAP[fn]) == {"fp64", "fp128", "fp256"}
        for fmt in FORMATS:
            lives = {ml.fragment(fn, fmt, r).live_max() for r in RND}
            assert max(lives) == ml.TRIG_LIVE_CAP[fn][fmt.name]
    # the six's view is untouched, and a trig fragment is held to its own
    f = ml.fragment("sin", FP64, RNE)
    assert f.live_max() > ml.LIVE_CAP["fp64"]
    assert ml.invariants(f) == []
    assert ml.invariants(f, live_cap=ml.LIVE_CAP["fp64"]) == [
        f"{f.live_max()} values live at once, past {ml.LIVE_CAP['fp64']}"]
    assert ml.invariants(f, live_cap=f.live_max() - 1) == [
        f"{f.live_max()} values live at once, past {f.live_max() - 1}"]
    g = ml.fragment("exp", FP64, RNE)
    assert ml.invariants(g) == [] and g.live_max() <= ml.LIVE_CAP["fp64"]


def test_the_plan_of_the_polynomials_for_a_rho():
    rho = ml.trig_rho()
    pio4 = ml._pi() / 4
    assert pio4 < rho < pio4 * (1 + Fraction(1, 2 ** 29))
    assert ml.trig_rho(11) == pio4 * (1 + Fraction(1, 2 ** 11))
    # the study's 2.4: K = 8 for S and for C at G = 44 and 46; D = 12, 18 and
    # 28 for S and 13, 19 and 29
    assert ml.plan_trig(FP64, 44, rho) == ((8, 12), (8, 13))
    assert ml.plan_trig(FP128, 46, rho) == ((8, 18), (8, 19))
    assert ml.plan_trig(FP256, 46, rho) == ((8, 28), (8, 29))
    # and it follows rho and G: a wider rho or a larger G needs more terms
    wide = ml.plan_trig(FP64, 44, Fraction(1))
    assert wide[0][1] >= 12 and wide[1][1] >= 13 and wide != ml.plan_trig(
        FP64, 44, rho)
    assert ml.plan_trig(FP64, 50, rho)[0][0] >= 8
    # the build's meta holds the plan it used
    m = build_of("sin", FP64, RNE).meta
    assert (m["KS"], m["DS"], m["KC"], m["DC"]) == (8, 12, 8, 13)
    assert m["rho"] == rho and m["fn"] == "sin" and m["G"] == 44 \
        and m["R"] is None
    assert build_of("tan", FP128, RNE).meta["R"] == 1024


def test_guard_and_bound_shift_are_the_builds_own():
    b0, b3 = build_of("cos", FP64, RNE), ml.build("cos", FP64, RNE,
                                                  bound_shift=3)
    w0 = b0.words[b0.roles["BREL"][1]]
    w3 = b3.words[b3.roles["BREL"][1]]
    assert ml._dec(FP64, w3) == 8 * ml._dec(FP64, w0) == Fraction(1, 2 ** 94)
    assert b3.meta["shift"] == 3
    g = ml.build("sin", FP64, RNE, guard=40)
    assert g.meta["G"] == 40 and ml._dec(
        FP64, g.words[g.roles["BREL"][1]]) == Fraction(1, 2 ** 93)
    # a wider bound marks more: at shift 43 (G = 1) most lanes of a small set mark
    wide = ml.build("sin", FP64, RNE, bound_shift=43).fragment()
    xs = [x for x in T.pool_slice(FP64) if T.in_main(FP64, "sin", x)][:20]
    assert sum(1 for x in xs if ml.evaluate(wide, x)[1] & ml.MARK) > 10


# =====================================================================
# the control: every check on the clean fragments
# =====================================================================

@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("fmt,rnd", POOL_CONFIGS,
                         ids=[f"{f.name}-{rid(r)}" for f, r in POOL_CONFIGS])
def test_pools(fn, fmt, rnd):
    f = ml.fragment(fn, fmt, rnd)
    out, t = T.check_pools(f)
    assert out == [], out
    assert t.n == POOL_SIZES[fmt.name]
    assert len(t.range_marked) == RANGE_MARKED[fmt.name]
    assert not t.range_unmarked and not t.wrong and not t.guess_wrong
    # the marks that are not past the range are the committed list's, all
    # of it, and every guess is right
    listed = T.pool_marks(fn, fmt.name, rid(rnd))
    assert sorted(t.marked) == sorted(listed)


@pytest.mark.parametrize("fn", FUNCS)
@pytest.mark.parametrize("fmt,rnd", SEQ_CONFIGS,
                         ids=[f"{f.name}-{rid(r)}" for f, r in SEQ_CONFIGS])
def test_seq(fn, fmt, rnd):
    f = ml.fragment(fn, fmt, rnd)
    out, xs = T.check_seq(f)
    assert out == [], out
    assert len(set(xs)) == len(xs) >= len(T.pool_slice(fmt))
    if fmt is FP64:
        assert len(T.pool_slice(fmt)) == 387


def test_the_slice_and_the_pools_are_the_studys():
    assert [len(T.radian_pools(f)) for f in FORMATS] == [4408, 620, 614]
    assert [len(T.pool_slice(f)) for f in FORMATS] == [387, 140, 140]
    # the slice is plants.py's: the brute pool, the deepest cancellations,
    # every 16th power of two and 64 random
    assert set(T.deepest(FP64)) <= set(T.pool_slice(FP64))


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_bound(fn, fmt):
    """|V - f(x)| / Bv under 1 at 64 placed points of each of the study's five
    regions and at the deepest cancellations, each lane also against
    transcend.py. The largest found is a lower bound on the true worst, and
    keeps the study's two bits (the budgets' margin: 0.166 Bv at most)."""
    b = build_of(fn, fmt, RNE)
    worst = -1e9
    for region in T.REGIONS:
        out, (w, main, lanes) = T.check_bound(
            b, T.sample(fmt, region, 64, 5), region)
        assert out == [], out
        assert lanes == 64 and main > 0
        worst = max(worst, w)
    deep = list(T.deepest_in_range(fmt))
    out, (w, main, lanes) = T.check_bound(b, deep, "deepest")
    assert out == [], out
    assert main == lanes == len(deep) > 0        # every one inside the range
    worst = max(worst, w)
    assert worst < -2.0, worst


def test_structured():
    """The committed centres, both signs, marked with a guess equal to
    transcend.py's: cos at 2^-26, 2^-25, 3 2^-26 and 2^-24 under rtz, rdn and
    rup, tan at 3 2^-26 under rne and rmm; none for the other
    configurations."""
    seen = 0
    for fmt in FORMATS:
        for fn in FUNCS:
            for rnd in RND:
                f = ml.fragment(fn, fmt, rnd)
                out, lanes = T.check_structured(f)
                assert out == [], out
                want = 0
                if fmt is FP64:
                    want = 8 if fn == "cos" and rnd in (RTZ, RDN, RUP) else \
                        2 if fn == "tan" and rnd in (RNE, RMM) else 0
                assert len(lanes) == want
                seen += len(lanes)
    assert seen == 3 * 8 + 2 * 2


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", FUNCS)
def test_specials(fn, fmt):
    for rnd in RND:
        out, n = T.check_specials(ml.fragment(fn, fmt, rnd))
        assert out == [], out
        assert n == (24 if fmt is FP64 else 28)


def test_the_specials_rows_are_the_studys_and_the_range_rows_are_marked():
    rows = {f.name: T.special_rows(f) for f in FORMATS}
    assert [len(rows[f.name]) for f in FORMATS] == [9, 10, 10]
    kinds = {f.name: [k for _l, k, _x in rows[f.name]] for f in FORMATS}
    assert kinds["fp64"] == ["equal"] * 9
    assert kinds["fp128"][-2:] == ["marked", "decided"]
    assert kinds["fp256"][-2:] == ["marked", "decided"]
    # the rows' lanes: 2^1024 and the largest finite marked, 2^1024's
    # predecessor decided
    for fmt in (FP128, FP256):
        top = ml._pow2(fmt, 1024)
        assert rows[fmt.name][-2][2][:1] == [top]
        assert rows[fmt.name][-1][2][:1] == [top - 1]
        assert T.past_range(fmt, top) and not T.past_range(fmt, top - 1)
        assert not T.past_range(fmt, sf.inf_bits(fmt)) \
            and not T.past_range(fmt, sf.qnan_bits(fmt))


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_shape(fmt):
    builds = {(fn, r): build_of(fn, fmt, r) for fn in FUNCS for r in RND}
    assert T.check_shape(fmt, builds) == []


def test_the_totals_are_the_models_and_the_range_compare_is_the_one_move():
    """sin, cos and tan: 406, 402, 419 / 382, 378, 397 / 389, 385, 406
    instructions under every attribute (costs.fp64, fp128, fp256.out.txt),
    bank words 111, 108 and 122 for all three under five attributes, live 26,
    17, 16; and by phase the model's, except that M2G1's `inrange` compare is
    in "classify" and not in "range"."""
    want = {"sin": (406, 382, 389), "cos": (402, 378, 385),
            "tan": (419, 397, 406)}
    for fn in FUNCS:
        for i, fmt in enumerate(FORMATS):
            assert {len(ml.fragment(fn, fmt, r)) for r in RND} == {want[fn][i]}
    for fmt in FORMATS:
        model = T.model_phases("sin", fmt.name)
        port = T.port_phases("sin", fmt.name)
        if fmt is FP64:
            assert model == port and "range" not in port
        else:
            assert (model["range"], model["classify"]) == (2, 6)
            assert (port["range"], port["classify"]) == (1, 7)
            assert sum(model.values()) == sum(port.values())
    words = {f.name: set() for f in FORMATS}
    for fmt in FORMATS:
        for fn in FUNCS:
            for r in RND:
                words[fmt.name] |= set(ml.fragment(fn, fmt, r).words.values())
    assert {k: len(v) for k, v in words.items()} == {
        "fp64": 111, "fp128": 108, "fp256": 122}


def test_the_scheduler_takes_the_designs_order_for_trig_and_leaves_the_six():
    """The finding: neither of schedule_order's own orders (by phase, depth
    first) is as low as the study's order for sin, cos and tan - 30, 21, 17
    and 31, 30, 30 against 26, 17, 16 - so the design's order is the third
    candidate, strictly the lowest here and for none of the six."""
    for fmt, (rk, dfs, design) in zip(FORMATS, ((30, 31, 26), (21, 30, 17),
                                                (17, 30, 16))):
        for fn in FUNCS:
            for r in RND:
                b = build_of(fn, fmt, r)
                g = b.fragment(schedule=False)
                ph = [b.phase_of[i] for i in b.live_indices()]
                ranked = ml.permuted(g, ml._ranked_order(g, ph)).live_max()
                depth = ml.permuted(g, ml._dfs_order(g)).live_max()
                assert (ranked, depth, g.live_max()) == (rk, dfs, design)
                assert ml.schedule_order(g, ph) == list(range(len(g.body)))
                assert b.fragment().body == g.body
    for fn in ml.NAMES:
        for fmt in (FP32, FP64):
            b = ml.build(fn, fmt, RNE)
            g = b.fragment(schedule=False)
            ph = [b.phase_of[i] for i in b.live_indices()]
            lives = [ml.permuted(g, o).live_max() for o in
                     (ml._ranked_order(g, ph), ml._dfs_order(g))]
            assert min(lives) < g.live_max()
            assert ml.schedule_order(g, ph) != list(range(len(g.body)))


def test_the_audit_of_the_routines_own_builds_is_empty():
    """reduction_audit() on sin's, cos's and tan's builds over the slice (all
    three formats) and, for sin, fp64's products' binade edges (the three
    builds record the same claims, and the reduction is one): every claim of
    exactness holds."""
    claims = {fn: build_of(fn, FP64, RNE).meta["exact"] for fn in FUNCS}
    assert len({frozenset(v) for v in claims.values()}) == 1
    assert len(claims["sin"]) == 42                    # M2G1's CLAIMS["fp64"]
    assert len(binade_edges()) == 1844                 # the study's, 2.2
    for fmt in FORMATS:
        for fn in FUNCS:
            b = build_of(fn, fmt, RNE)
            xs = list(T.pool_slice(fmt))
            if fmt is FP64 and fn == "sin":
                xs += list(binade_edges())
            out, tally = T.check_audit(b, xs)
            assert out == [], out
            assert tally["claims"] == len(b.meta["exact"]) * len(xs)
            assert tally["nonfinite"] == 0 or fmt is not FP64


def test_constants_in_process():
    findings, lines = T.check_constants()
    assert findings == [] and len(lines) == 9
    for fn in FUNCS:
        for fmt in FORMATS:
            assert any(ln.startswith(f"{fn} {fmt.name}: G = "
                                     f"{ml.GUARD[fmt.name]}") for ln in lines)
    # every role is asked: the build's roles are the derivations' (no role
    # derived and not checked is a finding, "derived but not checked")
    b = build_of("sin", FP64, RNE)
    assert {"S_Y12", "S_CH0", "S_CL1", "C_Y13", "C_CL7", "GATE", "BREL", "U1",
            "L1", "TINY_EPS", "MINN", "SIGN", "INF", "QNAN", "ABSM", "QBIT",
            "INT1", "INT2", "SHIFT_W2", "FL_INVALID", "FL_INEXACT",
            "FL_INEXACT_MARK", "FL_UNDER_INEXACT", "MAGIC", "CHUNK0",
            "PIO2H"} <= set(b.roles)
    assert "RANGE" not in b.roles
    assert "RANGE" in build_of("sin", FP128, RNE).roles


def _program(*args):
    return subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                           *args], cwd=PYTHON_DIR, capture_output=True,
                          text=True)


def test_constants_as_a_program():
    done = _program("--check", "--only", "trig")
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.splitlines()[-1] == (
        "mathlib --check (trig): 3 routines, 3 formats, 0 differences")
    for fn in FUNCS:
        for fmt in FORMATS:
            assert f"{fn} {fmt.name}: G = {ml.GUARD[fmt.name]}" in done.stdout
    assert "6 routines" not in done.stdout
    assert "mathlib --check (reduction)" not in done.stdout
    assert "reduction fp64: G =" not in done.stdout
    listing = _program("--only", "trig")
    assert listing.returncode == 0
    assert len(listing.stdout.splitlines()) == 1 + 45
    rows = [ln.split() for ln in listing.stdout.splitlines()]
    assert ["sin", "fp64", "rne", "406", "107", "26", "26"] in rows
    assert ["tan", "fp256", "rmm", "406", "117", "16", "16"] in rows
    assert _program("--check", "--only", "sinh").returncode == 2


def test_check_prints_the_routines_line_then_the_reductions_then_trigs(
        monkeypatch, capsys):
    """With no --only: the six routines' line exactly as it is, the
    reduction's line as it is, then a line of trig's own, in that order; exit 1
    on a difference in any of the three; --only trig runs trig alone."""
    monkeypatch.setattr(ml, "check_constants", lambda **kw: (["six"], []))
    monkeypatch.setattr(ml, "check_reduction_constants",
                        lambda **kw: (["reduction fp64 a"], []))
    monkeypatch.setattr(ml, "check_trig_constants",
                        lambda **kw: (["sin fp64 a", "cos fp128 b"], []))
    assert ml.main(["--check"]) == 0
    shown = capsys.readouterr().out.splitlines()
    assert shown == [
        "six", "mathlib --check: 6 routines, 4 formats, 0 differences",
        "reduction fp64 a",
        "mathlib --check (reduction): 1 formats, 0 differences",
        "sin fp64 a", "cos fp128 b",
        "mathlib --check (trig): 3 routines, 3 formats, 0 differences"]
    monkeypatch.setattr(ml, "check_trig_constants",
                        lambda **kw: (["sin fp64 a"], ["sin fp64 rne GATE: x"]))
    assert ml.main(["--check"]) == 1                      # trig differs
    shown = capsys.readouterr().out
    assert "DIFFERENCE: sin fp64 rne GATE: x" in shown
    assert "mathlib --check: 6 routines, 4 formats, 0 differences" in shown
    assert ml.main(["--check", "--only", "trig"]) == 1
    shown = capsys.readouterr().out
    assert "6 routines" not in shown
    assert "mathlib --check (reduction)" not in shown
    monkeypatch.setattr(ml, "check_trig_constants", lambda **kw: (["t"], []))
    monkeypatch.setattr(ml, "check_constants",
                        lambda **kw: (["six"], ["a difference"]))
    assert ml.main(["--check"]) == 1                      # the six differ
    assert ml.main(["--check", "--only", "trig"]) == 0
    capsys.readouterr()
    with pytest.raises(SystemExit):
        ml.main(["--check", "--only", "tangent"])
    capsys.readouterr()


# =====================================================================
# the plants
# =====================================================================
#
# Each plant is built into fresh fragments and run through the checks; a
# check is RED when it finds what it exists to find. A fault may well turn
# more checks red than the ones it exists for, and the table says what each
# row was built to be seen by (red) and what it was shown to leave alone
# (green); the matrix is MEASURED. A row's check names the function and
# attribute it runs at: the lane the study names is that function's (the
# study's 8, M2-trig.md:1440 to 1456, MEASURED at fp64 by plants.py). The
# lanes are the least that shows it: pools the 387-lane slice (140 at fp128),
# bound 12 points of each of the five regions (seed 5) and the named lane,
# audit every sixth lane of the slice (and the binade edges for exact_add),
# structured and specials whole, constants and shape the fragments of the
# format, the planted function among clean ones.

PLANTED = [
    ("quadrant_sign", FP64,
     {"pools": ("cos", RNE), "bound": ("cos", RNE), "specials": ("cos", RNE),
      "constants": ("cos", RNE), "shape": ("cos", RNE)},
     {"structured": ("cos", RTZ), "audit": ("cos", RNE)}),
    ("clamp_tight", FP64,
     {"pools": ("sin", RNE), "structured": ("cos", RTZ),
      "specials": ("cos", RTZ), "constants": ("sin", RNE),
      "shape": ("sin", RNE)},
     {"bound": ("sin", RNE), "audit": ("sin", RNE)}),
    ("bound_loose", FP64,
     {"structured": ("cos", RTZ), "bound": ("sin", RNE),
      "constants": ("sin", RNE), "shape": ("sin", RNE)},
     {"pools": ("sin", RNE), "specials": ("sin", RNE),
      "audit": ("sin", RNE)}),
    ("mark_silenced", FP64,
     {"structured": ("cos", RTZ), "seq": ("cos", RTZ),
      "shape": ("cos", RTZ)},
     {"pools": ("cos", RTZ), "bound": ("cos", RTZ), "specials": ("cos", RTZ),
      "constants": ("cos", RTZ), "audit": ("cos", RTZ)}),
    ("coef", FP64,
     {"pools": ("sin", RNE), "bound": ("sin", RNE),
      "constants": ("sin", RNE), "shape": ("sin", RNE)},
     {"structured": ("cos", RTZ), "specials": ("sin", RNE),
      "audit": ("sin", RNE)}),
    ("newton_short", FP64,
     {"structured": ("tan", RNE), "bound": ("tan", RNE),
      "shape": ("tan", RNE)},
     {"pools": ("tan", RNE), "specials": ("tan", RNE),
      "constants": ("tan", RNE), "audit": ("tan", RNE)}),
    ("tiny_gate_off", FP64,
     {"pools": ("sin", RNE), "specials": ("sin", RNE),
      "constants": ("sin", RNE), "shape": ("sin", RNE)},
     {"structured": ("cos", RTZ), "bound": ("sin", RNE),
      "audit": ("sin", RNE)}),
    ("rl_dropped", FP64,
     {"pools": ("sin", RNE), "bound": ("sin", RNE), "shape": ("sin", RNE)},
     {"structured": ("cos", RTZ), "constants": ("sin", RNE),
      "audit": ("sin", RNE)}),
    ("zl_dropped", FP64,
     {"pools": ("sin", RNE), "bound": ("sin", RNE), "shape": ("sin", RNE)},
     {"structured": ("cos", RTZ), "specials": ("sin", RNE),
      "constants": ("sin", RNE), "audit": ("sin", RNE)}),
    ("clamp_off", FP64,
     {"pools": ("sin", RTZ), "constants": ("sin", RTZ),
      "shape": ("sin", RTZ)},
     {"structured": ("cos", RTZ), "bound": ("sin", RTZ),
      "specials": ("sin", RTZ), "audit": ("sin", RTZ)}),
    ("sign_after_rounding", FP64,
     {"pools": ("sin", RDN), "bound": ("sin", RDN), "specials": ("sin", RDN),
      "shape": ("sin", RDN)},
     {"structured": ("tan", RNE), "constants": ("sin", RDN),
      "audit": ("sin", RDN)}),
    ("range_unmarked", FP128,
     {"pools": ("sin", RNE), "specials": ("sin", RNE), "shape": ("sin", RNE)},
     {"bound": ("sin", RNE), "constants": ("sin", RNE),
      "audit": ("sin", RNE)}),
    ("cos_zero_operand", FP64,
     {"pools": ("cos", RNE), "specials": ("cos", RNE)},
     {"structured": ("cos", RTZ), "bound": ("cos", RNE),
      "constants": ("cos", RNE), "audit": ("cos", RNE),
      "shape": ("cos", RNE)}),
    ("inf_flag_dropped", FP64,
     {"specials": ("sin", RNE)},
     {"pools": ("sin", RNE), "structured": ("cos", RTZ),
      "bound": ("sin", RNE), "constants": ("sin", RNE),
      "audit": ("sin", RNE), "shape": ("sin", RNE)}),
    ("chunk", FP64,
     {"pools": ("sin", RNE), "bound": ("sin", RNE),
      "constants": ("sin", RNE)},
     {"structured": ("cos", RTZ), "specials": ("sin", RNE),
      "audit": ("sin", RNE), "shape": ("sin", RNE)}),
    ("window", FP64,
     {"pools": ("sin", RNE), "bound": ("sin", RNE),
      "constants": ("sin", RNE), "shape": ("sin", RNE)},
     {"structured": ("cos", RTZ), "audit": ("sin", RNE)}),
    ("mid_inexact", FP64,
     {"pools": ("cos", RNE), "bound": ("cos", RNE), "shape": ("cos", RNE)},
     {"structured": ("cos", RTZ), "constants": ("cos", RNE),
      "audit": ("cos", RNE)}),
    ("exact_add", FP64,
     {"audit": ("sin", RNE)},
     {"pools": ("sin", RNE), "bound": ("sin", RNE),
      "structured": ("cos", RTZ), "specials": ("sin", RNE),
      "constants": ("sin", RNE), "shape": ("sin", RNE)}),
]

# The study's named cases, reproduced (fp64): (function, attribute, argument,
# what it is). "wrong": the lane unmarked and not transcend.py's; "marked off
# the list": marked, and not among TRIG_POOL_MARKS; "an unmarked centre": one
# of the committed centres, which the control marks, not marked.
NAMED = {
    "quadrant_sign": [("cos", RNE, 0x4008000000000000, "wrong")],
    "clamp_tight": [("sin", RNE, 0x597e3ca9b6c655cb, "marked off the list"),
                    ("cos", RTZ, 0x3e50000000000000, "an unmarked centre")],
    "bound_loose": [("cos", RTZ, 0x3e50000000000000, "an unmarked centre")],
    "mark_silenced": [("cos", RTZ, 0x3e50000000000000, "an unmarked centre")],
    "coef": [("sin", RNE, 0x541e146a1edcbc95, "wrong")],
    "newton_short": [("tan", RNE, 0x3e68000000000000, "an unmarked centre")],
    "tiny_gate_off": [("sin", RNE, 0x1, "wrong")],
    "rl_dropped": [("sin", RNE, 0x4570b04fbfd9356e, "wrong")],
    "zl_dropped": [("sin", RNE, 0xc96f96a1cd67f437, "wrong")],
    "clamp_off": [("sin", RTZ, 0x597e3ca9b6c655cb, "marked off the list")],
    "chunk": [("sin", RNE, 0x6500000000000000, "wrong")],
    "window": [("sin", RNE, 0x3fefffffffffffff, "wrong")],
    "mid_inexact": [("cos", RNE, 0x79ffce36f3ebfe43, "wrong")],
    "sign_after_rounding": [("sin", RDN, 0xbf00000000000000, "wrong")],
    "cos_zero_operand": [("cos", RNE, 0x0, "wrong")],
}
# lanes a bound check adds to the placed points: the named lane of a plant
# whose fault the placed points of a region do not reach
BOUND_EXTRA = {"quadrant_sign": [0x4008000000000000],
               "mid_inexact": [0x79ffce36f3ebfe43]}
# the plants that do not act, and are refused by name, at fp64, fp128, fp256:
# (plant, function, format)
NOT_APPLICABLE = (
    {("quadrant_sign", fn, f) for fn in ("sin", "tan") for f in
     ("fp64", "fp128", "fp256")}
    | {(p, "tan", f) for p in ("clamp_tight", "clamp_off")
       for f in ("fp64", "fp128", "fp256")}
    | {("newton_short", fn, f) for fn in ("sin", "cos") for f in
       ("fp64", "fp128", "fp256")}
    | {("sign_after_rounding", "cos", f) for f in ("fp64", "fp128", "fp256")}
    | {("range_unmarked", fn, "fp64") for fn in FUNCS}
    | {("cos_zero_operand", fn, f) for fn in ("sin", "tan") for f in
       ("fp64", "fp128", "fp256")}
    | {("exact_add", fn, f) for fn in FUNCS for f in ("fp128", "fp256")})


def _row_id(r):
    return f"{r[0]}-{r[1].name}"


@pytest.mark.parametrize("row", PLANTED, ids=_row_id)
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(row):
    plant, fmt, red, green = row
    for check, (fn, rnd) in red.items():
        found = run_check(check, plant, fmt, fn, rnd)
        assert found, f"{plant} at {fmt.name}: {check} stays green"
        assert all(s.startswith(check + ": ") for s in found), found[:2]
    for check, (fn, rnd) in green.items():
        found = run_check(check, plant, fmt, fn, rnd)
        assert found == [], f"{plant} at {fmt.name}: {check} is red: " \
                            f"{found[:2]}"


@functools.lru_cache(maxsize=None)
def _control(check, fmt, fn, rnd):
    return run_check(check, None, fmt, fn, rnd)


def test_the_control_is_green_in_every_check_the_table_runs():
    """The clean fragments, on the lanes the rows use: nothing red, so that a
    red in a row is the plant's."""
    seen = set()
    for plant, fmt, red, green in PLANTED:
        for check, (fn, rnd) in {**red, **green}.items():
            key = (check, fmt, fn, rnd)
            if key in seen or check == "seq":
                continue
            seen.add(key)
            assert _control(*key) == [], key
    assert len(seen) > 40


@pytest.mark.parametrize("plant", sorted(NAMED))
def test_the_studys_named_case_is_reproduced(plant):
    for fn, rnd, lane, kind in NAMED[plant]:
        fmt = FP64
        gold = T.golden(fmt, rnd, lane, fn)
        listed = T.pool_marks(fn, fmt.name, rid(rnd))
        bits, fw = ml.evaluate(fragment_of(fn, fmt, rnd, plant), lane)
        cbits, cfw = ml.evaluate(ml.fragment(fn, fmt, rnd), lane)
        if kind == "wrong":
            assert not fw & ml.MARK and (bits, fw) != gold, (plant, lane)
            assert (cbits, cfw) == gold
        elif kind == "marked off the list":
            assert fw & ml.MARK and lane not in listed, (plant, lane)
            assert not cfw & ml.MARK
        else:
            assert lane in listed and not fw & ml.MARK, (plant, lane)
            assert cfw & ml.MARK


def test_exact_add_is_red_in_the_audit_on_the_binade_edges_only():
    """The study's 3.6, item 8: the plant is invisible to the slice and the
    pools, and the products' binade edges find it: at fp64 27 lanes, the first
    0x46167c4c45c1b200, of the 1,844 edges; sin's build records the same
    claims as the reduction's own."""
    b = build_of("sin", FP64, RNE, "exact_add")
    out, tally = T.check_audit(b, list(binade_edges()))
    assert len(out) == 1 and out[0].startswith("audit: sin fp64 rne: 27 of "
                                               "1844 lanes have a claim")
    assert "0x46167c4c45c1b200" in out[0]
    assert T.check_audit(b, list(T.pool_slice(FP64)))[0] == []
    assert T.check_pools(b.fragment(), xs=list(T.pool_slice(FP64)))[0] == []


def test_the_bound_of_the_studys_named_cases():
    """newton_short is 2^+17.00 Bv in the zero region at 64 points (the
    study's 2^17.0, plants.py's seed 5), quadrant_sign 2^+98.00 at cos(3)
    (2^98); the rest are past the bound by the margins of the table."""
    b = build_of("tan", FP64, RNE, "newton_short")
    out, (worst, main, lanes) = T.check_bound(b, T.sample(FP64, "zero", 64, 5),
                                              "zero")
    assert out and round(worst, 2) == 17.0 and lanes == 64
    b = build_of("cos", FP64, RNE, "quadrant_sign")
    out, (worst, _m, _l) = T.check_bound(b, [0x4008000000000000])
    assert out and round(worst, 2) == 98.0


# ---- the table is complete, and the plants act ---------------------------------

def test_every_plant_is_in_the_table_and_every_row_names_a_plant():
    named = {row[0] for row in PLANTED}
    assert named == TRIG_PLANT_NAMES | REDUCTION_PLANT_NAMES
    assert set(ml.TRIG_PLANTS) == TRIG_PLANT_NAMES
    assert len(PLANTED) == len(named)
    assert all(ml.TRIG_PLANTS[p] for p in ml.TRIG_PLANTS)
    assert REDUCTION_PLANT_NAMES <= set(ml.REDUCTION_PLANTS)
    for plant, fmt, red, green in PLANTED:
        assert set(red) | set(green) <= set(CHECKS), plant
        assert not set(red) & set(green), plant
        assert red, plant
        for check, (fn, rnd) in {**red, **green}.items():
            assert fn in FUNCS and rnd in RND
            if check == "structured":
                # a claim about centres the configuration does not have
                # would be green whatever the plant did
                assert T.structured_lanes(fn, fmt, rnd), (plant, fn, rid(rnd))
        # a red is where the plant acts
        for check, (fn, rnd) in red.items():
            assert (plant, fn, fmt.name) not in NOT_APPLICABLE, (plant, check)
        assert plant in NAMED or plant in ("range_unmarked",
                                           "inf_flag_dropped", "exact_add")


def test_every_check_has_a_plant_red_in_it():
    red = {c for row in PLANTED for c in row[2]}
    assert red == set(CHECKS), set(CHECKS) - red
    # and a clean test for each
    for name in ("test_pools", "test_seq", "test_bound", "test_structured",
                 "test_specials", "test_shape",
                 "test_the_audit_of_the_routines_own_builds_is_empty",
                 "test_constants_in_process"):
        assert callable(globals()[name]), name


def test_the_plants_that_do_not_apply_are_the_pinned_ones():
    """A plant that could not act is refused by name ("does not apply"), as
    M2G1's are, and counts as neither red nor green there; the pairs are
    pinned so that a plant that stops acting where it did is seen, not read as
    green."""
    got = {(p, fn, fmt.name)
           for p in list(ml.TRIG_PLANTS) + ["exact_add"]
           for fn in FUNCS for fmt in FORMATS if not applies(p, fn, fmt)}
    assert got == NOT_APPLICABLE
    with pytest.raises(ValueError, match="plant 'newton_short' does not apply "
                       "to sin at fp64: the fault is not reached"):
        ml.build("sin", FP64, RNE, plant="newton_short")
    with pytest.raises(ValueError, match="exact_add' does not apply at fp128"):
        ml.build("sin", FP128, RNE, plant="exact_add")


def test_every_plant_changes_the_build_or_is_refused():
    """A plant that did nothing would pass every row green: each is a
    different build from the clean one, in its body or its words."""
    for fmt in (FP64, FP128):
        for fn in FUNCS:
            clean = build_of(fn, fmt, RNE)
            for plant in list(ml.TRIG_PLANTS) + sorted(REDUCTION_PLANT_NAMES):
                if not applies(plant, fn, fmt):
                    continue
                b = build_of(fn, fmt, RNE, plant)
                same = (b.body == clean.body and b.words == clean.words
                        and b.result == clean.result
                        and b.flags == clean.flags)
                assert not same, (plant, fn, fmt.name)


def test_a_reduction_plant_passes_through_and_the_cushion_proof_is_the_cleans():
    """build() passes REDUCTION_PLANTS to trig_reduction; one that could not
    act is refused by it. The cushion proof (_check_trig_cushion) is the clean
    build's, and refuses mid_inexact's by name."""
    for plant in ml.REDUCTION_PLANTS:
        try:
            b = ml.build("sin", FP64, RNE, plant=plant)
        except ValueError as e:
            assert "does not apply" in str(e) or "not exact" in str(e) \
                or "magic" in str(e), (plant, e)
        else:
            assert b.meta["plant"] == plant
    red = ml.build_reduction(FP64, plant="mid_inexact")
    with pytest.raises(ValueError, match=r"computed cushion past pi/4, "
                       r"2\^10\.96 at fp64"):
        ml._check_trig_cushion(red, ml.trig_rho())


# =====================================================================
# every leg of every check, failing alone on a doctored input
# =====================================================================

def _doctor(results, i, bits=None, fw=None, andnot=0, orwith=0):
    out = list(results)
    b, w = out[i]
    out[i] = (b ^ bits if bits is not None else b,
              (w if fw is None else fw) & ~andnot | orwith)
    return out


def test_each_leg_of_pools_can_fail_alone():
    f = ml.fragment("cos", FP64, RTZ)
    listed, plain, one = 0x3e50000000000000, 0x4008000000000000, \
        0x3ff0000000000000
    xs = [listed, plain, one]
    clean = [ml.evaluate(f, x) for x in xs]
    assert clean[0][1] & ml.MARK and not clean[1][1] & ml.MARK
    out, t = T.check_pools(f, xs, results=clean)
    assert out == [] and (t.n, len(t.marked), t.marked_right) == (3, 1, 1)
    cases = {
        "unmarked lanes differ from transcend.cos":
            _doctor(clean, 1, bits=1),
        "flag words carry bits other than [4:0] and the mark":
            _doctor(clean, 0, orwith=0x20),
        "marked off the committed list": _doctor(clean, 1, orwith=0x80),
        "on the committed list are not marked":
            _doctor(clean, 0, andnot=0x80),
    }
    for text, results in cases.items():
        out, t = T.check_pools(f, xs, results=results)
        assert len(out) == 1 and text in out[0] \
            and out[0].startswith("pools: "), (text, out)
    # a marked lane's guess is replayed and counted, and is not a finding
    out, t = T.check_pools(f, xs, results=_doctor(clean, 0, bits=1))
    assert out == [] and len(t.guess_wrong) == 1 and t.marked_right == 0
    # past the range (fp128): the lane must be marked
    g = ml.fragment("sin", FP128, RNE)
    top = ml._pow2(FP128, 1024)
    cl = [ml.evaluate(g, x) for x in (top, 0x3fff0000000000000000000000000000)]
    assert cl[0][1] & ml.MARK
    out, t = T.check_pools(g, [top, 0x3fff0000000000000000000000000000],
                           results=cl)
    assert out == [] and len(t.range_marked) == 1 and not t.marked
    out, t = T.check_pools(g, [top, 0x3fff0000000000000000000000000000],
                           results=_doctor(cl, 0, andnot=0x80))
    assert len(out) == 1 and "are not marked" in out[0] \
        and "2^1024" in out[0]


def test_each_leg_of_structured_can_fail_alone():
    f = ml.fragment("cos", FP64, RTZ)
    out, lanes = T.check_structured(f)
    assert out == [] and len(lanes) == 8
    out, _ = T.check_structured(
        f, evaluator=lambda g, x: (lambda r: (r[0], r[1] & 0x1F))(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "8 of the 8 committed centres are not marked" \
        in out[0] and out[0].startswith("structured: ")
    out, _ = T.check_structured(
        f, evaluator=lambda g, x: (lambda r: (r[0] ^ 1, r[1]))(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "marked centres have a guess that differs from " \
        "transcend.cos" in out[0] and out[0].startswith("structured: ")
    # a configuration with no centres runs none and passes
    assert T.check_structured(ml.fragment("sin", FP64, RNE)) == ([], [])


def test_each_leg_of_seq_can_fail_alone():
    f = ml.fragment("cos", FP64, RTZ)
    xs = [0x3ff0000000000000, 0x4008000000000000, 0x40522e5a572798d6, 0x0]
    out, lanes = T.check_seq(f, xs)
    assert out == [] and len(lanes) == 4 + 8        # the committed centres
    # the evaluator: seq.py and evaluate() differ
    out, _ = T.check_seq(f, xs, evaluator=lambda g, x: (
        ml.evaluate(g, x)[0] ^ 1, ml.evaluate(g, x)[1]))
    assert len(out) == 1 and "seq.py and evaluate() differ on 12 lanes" \
        in out[0]
    # a flag left loud: the first flag-raising instruction outside QUIET
    out, _ = T.check_seq(f, xs, loud=True)
    assert out and all("raised" in s for s in out)
    # FLAGS is not the OR of the lanes' bytes
    out, _ = T.check_seq(f, xs, post=lambda r: (setattr(r, "flags", r.flags
                                                       ^ 1), r)[1])
    assert len(out) == 1 and "FLAGS" in out[0] and "OR of the lanes" in out[0]
    # STATUS[6] and a marked lane disagree
    out, _ = T.check_seq(f, xs, post=lambda r: (setattr(
        r, "status", r.status ^ 0x40), r)[1])
    assert len(out) == 1 and "STATUS[6]" in out[0]
    # a fragment that is wrong the same way on seq.py and in evaluate(): the
    # unmarked lanes differ from transcend.py, in the result and the deposit
    bad = fragment_of("cos", FP64, RNE, "quadrant_sign")
    out, _ = T.check_seq(bad, xs)
    assert any("unmarked lanes on seq.py differ from transcend.cos" in s
               for s in out) and any("deposited" in s for s in out)
    assert not any("seq.py and evaluate()" in s for s in out)
    # the card case: cos(2^-26) under rtz at fp64 is the marked lane, and a
    # fragment that never marks it is red here
    silent = fragment_of("cos", FP64, RTZ, "mark_silenced")
    out, _ = T.check_seq(silent, xs)
    assert len(out) == 1 and "committed centres are not marked in the lane's " \
        "byte" in out[0]


def test_each_leg_of_bound_can_fail_alone():
    b = build_of("sin", FP64, RNE)
    xs = T.sample(FP64, "edge", 6, 5)
    out, (worst, main, lanes) = T.check_bound(b, xs)
    assert out == [] and main == lanes == 6 and worst < 0
    # a main-path lane past 1 Bv, every lane right in transcend.py's sense
    wide = build_of("sin", FP64, RNE, "bound_loose")
    out, _ = T.check_bound(wide, xs)
    assert len(out) == 1 and "6 of 6 main-path lanes are past the bound" \
        in out[0] and out[0].startswith("bound: ")
    # a lane that differs from transcend.py with V right (not a main-path
    # lane): cos(+0) answering the operand
    zero = build_of("cos", FP64, RNE, "cos_zero_operand")
    out, (worst, main, lanes) = T.check_bound(zero, [0x0, 0x8000000000000000])
    assert len(out) == 1 and "2 unmarked lanes differ from transcend.cos" \
        in out[0] and main == 0


def test_each_leg_of_specials_can_fail_alone():
    f = ml.fragment("sin", FP64, RNE)
    out, n = T.check_specials(f)
    assert out == [] and n == 24
    # an "equal" row: a flag word
    out, _ = T.check_specials(f, evaluator=lambda g, x: (
        lambda r: (r[0], r[1] ^ 1) if x == sf.inf_bits(FP64) else r)(
            ml.evaluate(g, x)))
    assert len(out) == 1 and "row '+inf, -inf': 1 of 2 lanes differ" in out[0]
    # a "marked" row (past the range): marked with the flag word inexact|mark
    g = ml.fragment("sin", FP128, RNE)
    top = ml._pow2(FP128, 1024)
    assert T.check_specials(g)[0] == []
    out, _ = T.check_specials(g, evaluator=lambda h, x: (
        lambda r: (r[0], 0x90 | 0x1) if x == top else r)(ml.evaluate(h, x)))
    assert len(out) == 1 and "2^1024 and the largest finite" in out[0] \
        and "1 of 4 lanes differ" in out[0] and "flag word" in out[0]
    out, _ = T.check_specials(g, evaluator=lambda h, x: (
        lambda r: (r[0], r[1] & 0x7F) if x == top else r)(ml.evaluate(h, x)))
    assert len(out) == 1 and "flag word" in out[0]
    # the "decided" row: the predecessor of 2^R marked
    out, _ = T.check_specials(g, evaluator=lambda h, x: (
        lambda r: (r[0], r[1] | 0x80) if x == top - 1 else r)(
            ml.evaluate(h, x)))
    assert len(out) == 1 and "the predecessor of 2^1024" in out[0] \
        and "1 of 2 lanes differ" in out[0]


def test_each_leg_of_audit_can_fail_alone():
    b = build_of("sin", FP64, RNE)
    assert T.check_audit(b, list(T.pool_slice(FP64))[:20])[0] == []
    # no claim recorded: the reduction's plant claims_lost
    lost = ml.build("sin", FP64, RNE, plant="claims_lost")
    out, _ = T.check_audit(lost, list(T.pool_slice(FP64))[:20])
    assert len(out) == 1 and "records no claim of exactness" in out[0] \
        and out[0].startswith("audit: ")
    # a claim that fails on a lane: exact_add (test above) - here a claim on
    # an opcode that cannot be audited is reported too
    odd = ml.build("sin", FP64, RNE)
    odd.meta["exact"] = set(odd.meta["exact"]) | {
        ("v", next(i for i, ins in enumerate(odd.body)
                   if ins[0] == sf.OP_SELECT))}
    out, _ = T.check_audit(odd, [T.pool_slice(FP64)[100]])
    assert len(out) == 1 and "have a claim that fails" in out[0]


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
    lines, findings = ml.check_trig_constants(
        builder=lambda n, f, r: b, formats=(fmt,), attrs=(b.rnd,),
        names=(b.meta["fn"],))
    return [f"constants: {s}" for s in findings]


def test_each_leg_of_constants_can_fail_alone():
    """The build with one word changed, one role at a time: the difference is
    named by fragment and word. Every kind of word: the reduction's, the
    Taylor coefficients (first, middle and last of each series, tail and
    head), the after-V section's, the integers."""
    clean = ml.build("sin", FP64, RNE)
    assert _constants_of(clean) == []
    roles = ["MAGIC", "MQ", "INVB", "FLOOROFF", "PIO2H", "PIO2L", "PIO4D",
             "CHUNK0", "CHUNK14", "S_Y12", "S_Y8", "S_Y10", "S_CH0", "S_CH3",
             "S_CH7", "S_CL1", "S_CL7", "C_Y13", "C_Y8", "C_Y11", "C_CH1",
             "C_CH7", "C_CL2", "C_CL7", "GATE", "BREL", "U1", "L1",
             "TINY_EPS", "MINN", "ZERO", "ONE", "SIGN", "INF", "QNAN", "ABSM",
             "QBIT", "INT1", "INT2", "SHIFT_W2", "FL_INVALID", "FL_INEXACT",
             "FL_INEXACT_MARK", "FL_UNDER_INEXACT"]
    for role in roles:
        bad = _fresh_with("sin", FP64, RNE, role)
        found = _constants_of(bad)
        assert found and all(s.startswith("constants: ") for s in found), role
        assert any(f"sin fp64 rne {role}:" in s for s in found), (role, found)
    # cos's and tan's own words
    for fn, role in (("cos", "COSTINY"), ("cos", "U1"), ("tan", "TINY_EPS"),
                     ("tan", "SHIFT_W1"), ("tan", "MINN")):
        found = _constants_of(_fresh_with(fn, FP64, RTZ, role))
        assert any(f"{fn} fp64 rtz {role}:" in s for s in found), (fn, role)
    # the range word (fp128), and the three formats' own: INF, QNAN
    found = _constants_of(_fresh_with("cos", FP128, RUP, "RANGE"))
    assert any("cos fp128 rup RANGE:" in s for s in found)
    found = _constants_of(_fresh_with("tan", FP256, RDN, "QNAN"))
    assert any("tan fp256 rdn QNAN:" in s for s in found)
    # a role no derivation asks, a low word where one word is exact, a
    # difference of the plan, the plan undecidable
    found = _constants_of(_fresh_with("sin", FP64, RNE,
                                      extra_role=("EXTRA", 0x1234)))
    assert len(found) == 1 and "derived but not checked: ['EXTRA']" in found[0]
    found = _constants_of(_fresh_with(
        "sin", FP64, RNE, extra_role=("S_CL0", 0x3c90000000000000)))
    assert len(found) == 1 and "S_CL0 is held, but the coefficient is exact " \
        "in one word" in found[0]


def test_the_plan_legs_of_constants(monkeypatch):
    real = ml.plan_trig
    monkeypatch.setattr(ml, "plan_trig", lambda fmt, G, rho: (
        lambda p: (p[0], (p[1][0], p[1][1] + 1)))(real(fmt, G, rho)))
    bad = ml.build("sin", FP64, RNE)
    monkeypatch.undo()
    found = _constants_of(bad)
    assert any("the plan ((8, 12), (8, 14)) is not the re-derived "
               "((8, 12), (8, 13))" in s for s in found), found
    # the enclosure of pi too wide to decide the plan
    monkeypatch.setattr(ml, "_check_pi", lambda bits: (Fraction(3),
                                                       Fraction(4)))
    found = _constants_of(ml.build("sin", FP64, RNE))
    assert any("undecidable: the enclosure of pi gives two plans" in s
               for s in found), found


def test_check_exits_1_on_a_difference_and_names_it(monkeypatch, capsys):
    real = ml.build

    def altered(name, fmt, rnd, **kw):
        b = real(name, fmt, rnd, **kw)
        if name == "cos" and fmt is FP64 and rnd == RTZ:
            b.words[b.roles["U1"][1]] += 1
        return b
    monkeypatch.setattr(ml, "build", altered)
    assert ml.main(["--check", "--only", "trig"]) == 1
    shown = capsys.readouterr().out
    assert "DIFFERENCE: cos fp64 rtz U1:" in shown
    # the word is shared by COSTINY (both 1 - 2^-p under rtz): two roles
    assert "DIFFERENCE: cos fp64 rtz COSTINY:" in shown
    n = shown.count("DIFFERENCE:")
    assert shown.splitlines()[-1] == (
        f"mathlib --check (trig): 3 routines, 3 formats, {n} differences")


# ---- the shape's legs ----------------------------------------------------------

def test_each_leg_of_shape_can_fail_alone():
    builds = {(fn, r): build_of(fn, FP64, r) for fn in FUNCS for r in RND}
    assert T.check_shape(FP64, builds) == []

    def legs(text, tables, n):
        out = T.check_shape(FP64, builds, tables=tables)
        assert len(out) == n and all(text in s and s.startswith("shape: ")
                                     for s in out), (text, out)
    shape = dict(T.SHAPE)
    shape[("sin", "fp64")] = [(407, 107, 26)] + T.SHAPE[("sin", "fp64")][1:]
    legs("pinned 407, 107, 26", T.Tables(shape=shape), 1)
    legs("instructions by phase differ from the model's",
         T.Tables(phases=lambda fn, name: dict(T.port_phases(fn, name), z=5)
                  if fn == "sin" else T.port_phases(fn, name)), 5)
    legs("the flag word takes", T.Tables(flag_words=dict(
        T.FLAG_WORDS, sin=T.FLAG_WORDS["sin"] | {0x2})), 5)
    legs("MIN and", T.Tables(min_max=dict(T.MIN_MAX, cos=(1, 2))), 5)
    legs("the cap is 27", T.Tables(caps={
        **ml.TRIG_LIVE_CAP, "sin": {**ml.TRIG_LIVE_CAP["sin"], "fp64": 27}}),
         1)
    legs("bank words over the three functions", T.Tables(
        union=dict(T.UNION_WORDS, fp64=110)), 1)
    legs("of one argument are", T.Tables(shared=dict(T.SHARED, fp64=476)), 5)
    # a cap one under fails by name; the cap itself holds: the leg compares
    # the fragments' live with the cap, and with one less
    f = ml.fragment("cos", FP64, RNE)
    assert ml.invariants(f, live_cap=26) == []
    assert ml.invariants(f, live_cap=25) == ["26 values live at once, past 25"]
    # and the cap a doctored table names under the maximum: the maximal
    # fragment fails its own cap
    out = T.check_shape(FP64, builds, tables=T.Tables(caps={
        **ml.TRIG_LIVE_CAP, "tan": {**ml.TRIG_LIVE_CAP["tan"], "fp64": 25}}))
    assert any("the cap is 25, the most values live under any attribute is "
               "26" in s for s in out)
    assert any("invariants: 26 values live at once, past 25" in s
               for s in out)


def test_the_reorder_leg_of_shape_fails_alone_on_a_doctored_fragment():
    builds = {(fn, r): build_of(fn, FP64, r) for fn in FUNCS for r in RND}
    frags = {k: b.fragment() for k, b in builds.items()}
    key = ("sin", RNE)
    g = frags[key]
    # still a topological order, one value changed (renumbered operand)
    out = T.check_shape(FP64, builds,
                        fragments={**frags, key: ml._misnumbered(g)})
    assert [s for s in out if "the dataflow graph is not the design's" in s]
    assert all(s.startswith("shape: ") for s in out)
    # an instruction before an operand it reads
    out = T.check_shape(FP64, builds, fragments={**frags, key: ml._forward(g)})
    assert [s for s in out if "not a topological order" in s]
    assert all(s.startswith("shape: ") for s in out)


def test_the_sharing_leg_of_shape_fails_alone_on_a_doctored_prefix():
    """cos's instruction in the prefix with its operands exchanged (ADD is
    commutative: the same value, a different instruction), in all five
    attributes: the three are no longer alike before `select`, which the leg
    says by instruction and function; the count the doctored fragments make in
    a compiled step is the doctored table's, so the count leg is quiet."""
    import copy
    builds = {(fn, r): build_of(fn, FP64, r) for fn in FUNCS for r in RND}
    for r in RND:
        c = copy.copy(builds[("cos", r)])
        c.body = list(c.body)
        live = set(c.live_indices())
        i = next(i for i, (op, rr, srcs) in enumerate(c.body)
                 if op == sf.OP_ADD and c.phase_of[i] == "red-mid"
                 and i in live and srcs[0] != srcs[1])
        op, rr, srcs = c.body[i]
        c.body[i] = (op, rr, srcs[::-1])
        builds[("cos", r)] = c
    counts = {T.shared_count([builds[(fn, r)].fragment() for fn in FUNCS])
              for r in RND}
    assert len(counts) == 1 and counts != {475}
    out = T.check_shape(FP64, builds,
                        tables=T.Tables(shared={"fp64": counts.pop(),
                                                "fp128": 455, "fp256": 464}))
    assert len(out) == 5 and all("are not alike before `select`" in s
                                 and "cos not sin's" in s for s in out), out


def test_phase_order_has_the_trig_phases_in_place():
    order = ml.PHASE_ORDER
    new = ("z", "S-tail", "S-head", "C-tail", "C-head", "sincos", "select",
           "quotient")
    i = order.index("fixed-grid")
    assert order[i + 1:i + 1 + len(new)] == new
    assert order[i + 1 + len(new):i + 3 + len(new)] == ("final", "classify")
    assert order[-2:] == ("range", "special")
    used = {ph for fn in FUNCS for fmt in FORMATS
            for ph in build_of(fn, fmt, RNE).phase_of}
    assert used <= set(order) and "setup" not in used


# =====================================================================
# the shared sections: what parcel M2F calls
# =====================================================================

def test_the_after_v_section_accepts_three_words_without_building_fp32(
        monkeypatch):
    """trig_after() takes V as a list of words: three, whose low words round
    through round-to-odd as M1's fp32 finals do. The double word's own
    builder is run with a third word of +0 appended to sin(r) and to cos(r)
    (and to tan's quotient), so that the three-word section runs on real
    values at fp64 without building fp32: every unmarked lane of the slice
    equal to transcend.py's, the fragments in C4's shape, the round-to-odd
    adds (RTZ) present and the probes V0, V1, V2 and Vh kept."""
    real = ml.trig_after
    seen = []

    def three(b, fn, x, q, sin_words, cos_words, **kw):
        zero = b.const("ZERO", 0)
        quotient = kw.get("quotient")
        if quotient is not None:
            kw["quotient"] = lambda bb, N, D: list(quotient(
                bb, N[:2], D[:2])) + [zero]
        seen.append(fn)
        return real(b, fn, x, q, list(sin_words) + [zero],
                    list(cos_words) + [zero], **kw)
    monkeypatch.setattr(ml, "trig_after", three)
    xs = list(T.pool_slice(FP64))[::3]
    for rnd in (RNE, RDN):
        for fn in FUNCS:
            b = ml.build(fn, FP64, rnd)
            f = b.fragment()
            assert {"V0", "V1", "V2", "Vh"} <= set(b.probes)
            assert "Vl" not in b.probes
            assert ml.invariants(f, live_cap=None) == []
            rtz_adds = [1 for op, r, _s in f.body
                        if op == sf.OP_ADD and r == RTZ]
            assert len(rtz_adds) >= 3, (fn, rnd)
            out, t = T.check_pools(f, xs=xs, marks={})
            assert out == [], out[:2]
            assert not t.wrong and not t.guess_wrong
    assert seen == [fn for _r in (RNE, RDN) for fn in FUNCS]
    monkeypatch.undo()
    # the two-word section's refusals
    b = ml.Build(FP64, RNE, "x")
    one = b.word(sf.one_bits(FP64), "ONE")
    for sin_w, cos_w in (([one], [one]), ([one] * 4, [one] * 4),
                         ([one] * 2, [one] * 3)):
        with pytest.raises(ValueError, match="two words or of three"):
            ml.trig_after(b, "sin", ("in", "a"), one, sin_w, cos_w, G=44)
    with pytest.raises(ValueError, match="quotient"):
        ml.trig_after(b, "tan", ("in", "a"), one, [one] * 2, [one] * 2, G=44)
    with pytest.raises(ValueError, match="sinh"):
        ml.trig_after(b, "sinh", ("in", "a"), one, [one] * 2, [one] * 2, G=44)


def test_the_polynomial_plan_is_for_a_given_rho():
    """fp32's reduction proved |r| <= pi/4 (1 + 2^-11) at G = 18, and the
    triple word is planned at its own rho: plan_trig() takes any."""
    rho11 = ml.trig_rho(11)
    k, d = zip(*ml.plan_trig(FP32, 18, rho11))
    assert all(1 <= x <= 30 for x in k + d) and k[0] <= d[0] and k[1] <= d[1]
    # fp32 at M2X's G = 40 and rho 2^-18.91 over: (K, D) of the triple word's
    # polynomials need not be this plan, but the function is the same one
    assert ml.plan_trig(FP64, 44, ml.trig_rho(30)) == ((8, 12), (8, 13))
    # a larger rho needs no fewer terms, a smaller G no more
    big = ml.plan_trig(FP64, 44, Fraction(11, 10))
    assert big[0][1] >= 12 and big[1][1] >= 13 and big != ml.plan_trig(
        FP64, 44, ml.trig_rho(30))
    assert ml.plan_trig(FP64, 30, ml.trig_rho(30))[0][0] <= 8


def test_the_cushion_proof_refuses_a_build_by_name():
    """The reduction's own computed cushion past pi/4 is within the
    polynomials' rho at every build, a static proof that fails by name: not at
    fp32's G = 18 (2^-11.66), not for a mid sum that rounds (2^10.96 at fp64),
    not for a rho that leaves less room than the reduction's 2^-33.04."""
    rho = ml.trig_rho()
    for fmt, want in ((FP64, -33.04), (FP128, -64.0), (FP256, -62.0)):
        b = ml.build_reduction(fmt)
        ml._check_trig_cushion(b, rho)
        assert round(math.log2(ml._trig_slack(b)), 2) == want
    b32 = ml.build_reduction(FP32, G=18)
    with pytest.raises(ValueError, match=r"2\^-11\.66 at fp32 \(G = 18\), is "
                       r"past the polynomials' rho = pi/4 \(1 \+ 2\^-30"):
        ml._check_trig_cushion(b32, rho)
    ml._check_trig_cushion(b32, ml.trig_rho(10))      # a rho of its own
    b = ml.build_reduction(FP64)
    with pytest.raises(ValueError, match="computed cushion"):
        ml._check_trig_cushion(b, ml.trig_rho(40))
    # the lanes alone: a doctored bound of the lower pieces
    b = ml.build_reduction(FP64)
    b.meta["reduction_mid"]["lows"] = -20.0
    with pytest.raises(ValueError, match="computed cushion"):
        ml._check_trig_cushion(b, rho)


# =====================================================================
# the box's commands
# =====================================================================

def _runs(*args):
    return subprocess.run([sys.executable, "-B", str(pathlib.Path(__file__)
                                                      .parent /
                                                      "mathlib_runs.py"),
                           *args], capture_output=True, text=True)


def test_the_trig_commands_run_at_small_sizes_and_refuse_an_existing_out(
        tmp_path):
    done = _runs("trig-pools", "--quick", "--seq", "--fn", "cos", "--formats",
                 "fp128", "--attrs", "rtz,rup")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RESULT: ok" in done.stdout
    assert done.stdout.count("trig-pools cos fp128") == 2
    assert "past the range marked" in done.stdout and "peak memory" in \
        done.stdout
    out = tmp_path / "pools.txt"
    done = _runs("trig-bound", "--quick", "--fn", "sin", "--attrs", "rne",
                 "--n", "4", "--out", str(out))
    assert done.returncode == 0, done.stdout + done.stderr
    assert "RESULT: ok" in done.stdout
    text = out.read_text()
    assert text.count("trig-bound sin fp128 rne") == 5 and \
        "a sampled lower bound" in text and "RESULT: ok" in text
    # a path that exists is refused, before any work, and left as it was
    done = _runs("trig-bound", "--quick", "--n", "4", "--out", str(out))
    assert done.returncode != 0 and "refusing to overwrite" in (
        done.stdout + done.stderr)
    assert out.read_text() == text
    done = _runs("trig-pools", "--quick", "--out", str(out))
    assert done.returncode != 0 and "the file exists" in (
        done.stdout + done.stderr)
    assert _runs("trig-pools", "--formats", "fp32").returncode != 0
    assert _runs("trig-bound", "--fn", "exp").returncode != 0
