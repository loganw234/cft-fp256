# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""pown, rootn and compound of python/cft_golden/mathlib.py (parcel M3G2, M3's
build, wave 2) at fp64, fp128 and fp256, on the pow family's one core, held to
the study's section 8 (docs/studies/M3-pow.md): quick enough for the golden
stage; the larger runs are `python python/tests/mathlib_runs.py pow-pools` and
`pow-bound` with `--fn pown,rootn,compound`.

The integer operand n is a constant of the fragment (mathlib.pow_n checks it),
so every fragment is keyed by (name, fmt, rnd, n) and every check runs at an n:
python/tests/mathlib_pow_harness.py's `*_n` checks, which return findings that
begin with the check's name and an "n = N:". The n list is mathlib.POW_CHECK_NS
(fp64, 13 n) and its 6 shortest (0, 1, 3, -3, 17, -2^63) at fp128 and
fp256; all five attributes at n = 0, 1, 3, -3 and one large n, rne and rtz at
the others. n = 0 and n = 1 are the small
fragments.

  pools  regions  specials  structured  seq  bound  shape  core  constants

and for each a planted fault shown red in it (mathlib.POW_PLANTS: 28, five of
them this parcel's), the control green in all, every leg of each check shown
failing alone on a doctored input, the interface, the refusals and the
`--check --only pow-n` output. Nothing here imports docs/studies/m3: the pinned
data (the harness's PINS_N, EFT_N, FLAG_WORDS_N, POOL_MARKS_N, SPECIAL_MARKS_N)
is the model's, taken once, by the parcel's scratch script.
"""

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

import mathlib_pow_harness as P  # noqa: E402
import mathlib_runs as R  # noqa: E402

PYTHON_DIR = pathlib.Path(__file__).resolve().parents[1]
FORMATS = (FP64, FP128, FP256)
INT_FUNCS = ("pown", "rootn", "compound")
RND = list(sf.RND_MODES)
RNE, RTZ, RDN, RUP, RMM = P.RNE, P.RTZ, P.RDN, P.RUP, P.RMM


def fid(f):
    return f.name


def rid(r):
    return sf.RND_NAMES[r]


def configs():
    """[(fn, fmt, n)] of the golden stage: every function at every format at
    its n list."""
    return [(fn, f, n) for fn in INT_FUNCS for f in FORMATS
            for n in ml.pow_check_ns(fn, f)]


CONFIGS = configs()


def cid(c):
    return f"{c[0]}-{c[1].name}-{c[2]}"


# =====================================================================
# the interface and the refusals
# =====================================================================

def test_the_key_and_the_tables():
    assert ml.POW_INT_NAMES == ("pown", "rootn", "compound")
    assert tuple(ml._POW_N_BUILDERS) == ml.POW_INT_NAMES
    # pow and powr stay in their own table, and FUNCS stays two names
    assert tuple(ml._POW_BUILDERS) == ("pow", "powr") == P.FUNCS
    assert "pown" not in ml.__all__ and "pow_n" not in ml.__all__
    assert ml._POW_PARCEL["pown"] == "M3G2"      # the record of who builds it
    assert ml.POW_CHECK_NS == (0, 1, 2, -2, 3, -3, 8, 17, 1000, 2 ** 31 - 1,
                               2 ** 63 - 1, -2 ** 63, 2 ** 53 + 1)
    assert ml.pow_check_ns("rootn", FP64) == tuple(
        n for n in ml.POW_CHECK_NS if n)
    assert ml.pow_check_ns("pown", FP128) == (0, 1, 3, -3, 17, -2 ** 63)
    # every function of the table has a pool, a true value, regions and rows
    for fn in INT_FUNCS:
        assert fn in P.POOL_FNS and fn in P.TRUE_FNS and fn in P.REGION_NAMES


@pytest.mark.parametrize("bad,match", [
    (2 ** 63, "pown: n = 9223372036854775808 is outside int64"),
    (-2 ** 63 - 1, "is outside int64"),
    (2.5, "n = 2.5 is not an integer"),
    (True, "n = True is not an integer"),
    ("3", "is not an integer")])
def test_pow_n_refuses_by_name(bad, match):
    with pytest.raises(ValueError, match=match):
        ml.pow_n("pown", bad)
    with pytest.raises(ValueError, match=match):
        ml.build("pown", FP64, RNE, n=bad)
    with pytest.raises(ValueError, match=match.replace("pown", "compound")):
        ml.fragment("compound", FP128, RNE, n=bad)


def test_pow_n_takes_the_int64_range_and_rootn_refuses_zero():
    for n in (-2 ** 63, 2 ** 63 - 1, 0, 1, -1):
        for name in ("pown", "compound"):
            assert ml.pow_n(name, n) == n
    with pytest.raises(ValueError, match="rootn.x, 0. is invalid for every x"):
        ml.pow_n("rootn", 0)
    for call in (ml.build, ml.fragment):
        with pytest.raises(ValueError, match="rootn.x, 0. is invalid"):
            call("rootn", FP64, RNE, n=0)


def test_n_is_required_and_refused_where_it_is_not_taken():
    for name in INT_FUNCS:
        for call in (ml.build, ml.fragment):
            with pytest.raises(ValueError, match=f"{name} needs its integer "
                               f"operand n: a constant of the fragment"):
                call(name, FP64, RNE)
    for name in ("pow", "powr"):
        for call in (ml.build, ml.fragment):
            with pytest.raises(ValueError, match=f"{name} takes no integer "
                               f"operand"):
                call(name, FP64, RNE, n=3)
    for name in INT_FUNCS:
        with pytest.raises(ValueError, match="triple word, parcel M3F1's"):
            ml.build(name, FP32, RNE, n=3)
    # the names the library knows, listed in the refusal: the built ones after
    # pow and powr
    with pytest.raises(ValueError) as e:
        ml.fragment("sinh", FP64, RNE)
    assert "pow, powr, pown, rootn, compound" in str(e.value)


def test_two_n_are_two_fragments_with_one_op():
    a, b = (ml.fragment("pown", FP64, RNE, n) for n in (3, 5))
    assert a is not b and a.op == b.op == "pown"
    assert a is ml.fragment("pown", FP64, RNE, 3)
    assert ml.dag_digest(a) != ml.dag_digest(b)
    # n is a constant: one input
    assert a.inputs == ("a",)
    assert ml.build("pown", FP64, RNE, n=3).inputs == ("a",)
    assert ml.build("pow", FP64, RNE).inputs == ("a", "b")


@pytest.mark.parametrize("fn", INT_FUNCS)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
def test_the_small_fragments_are_routed_and_take_no_plant(fn, fmt):
    for n in (0, 1):
        if fn == "rootn" and n == 0:
            continue
        b = ml.build(fn, fmt, RNE, n=n)
        assert b.meta["family"] == "small" and b.inputs == ("a",)
        f = ml.fragment(fn, fmt, RNE, n)
        # the study's 5.1: 6 instructions (25 to 26 for compound(x, 1))
        want = {("compound", 1): range(25, 27),
                ("compound", 0): range(9, 10)}.get((fn, n), range(6, 7))
        assert len(f) in want, (fn, n, len(f))
        for plant in ("exact_unmarked", "n_word_ulp", "compound_onep_rounded",
                      "log_short"):
            with pytest.raises(ValueError, match="does not apply"):
                ml.build(fn, fmt, RNE, n=n, plant=plant)
    # n = 2 is a core fragment
    assert ml.build(fn, fmt, RNE, n=2).meta["family"] == "double word"


def test_the_small_fragments_answer_the_rule():
    """The small rows, by the rule and not by transcend.py: pown(x, 0) is 1
    for a quiet NaN, an infinity and a zero too, a signalling NaN invalid;
    pown and rootn at 1 are x itself (a NaN quiet); compound(x, 1) is 1 + x
    rounded once, -1 answered +0 under every attribute (rdn too), the sum's
    overflow under rup at x = max."""
    fmt = FP64
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    inf, qn, sn = sf.inf_bits(fmt), sf.qnan_bits(fmt), sf.snan_bits(fmt)
    for rnd in RND:
        f0 = ml.fragment("pown", fmt, rnd, 0)
        for x in (qn, inf, sf.zero_bits(fmt, 1), mone):
            assert ml.evaluate(f0, x) == (one, 0)
        assert ml.evaluate(f0, sn) == (qn, sf.FLAG_INVALID)
        f1 = ml.fragment("rootn", fmt, rnd, 1)
        assert ml.evaluate(f1, sf.inf_bits(fmt, 1)) == (sf.inf_bits(fmt, 1), 0)
        assert ml.evaluate(f1, sn) == (qn, sf.FLAG_INVALID)
        c1 = ml.fragment("compound", fmt, rnd, 1)
        assert ml.evaluate(c1, mone) == (0, 0)             # +0, not -0 (rdn)
        mx = sf.max_normal_bits(fmt)
        bits, fl = ml.evaluate(c1, mx)
        want = sf.inf_bits(fmt) if rnd == RUP else mx
        assert (bits, fl & 0x1F) == (want, 0x14 if rnd == RUP else 0x10)
        c0 = ml.fragment("compound", fmt, rnd, 0)
        assert ml.evaluate(c0, _enc(-2)) == (qn, sf.FLAG_INVALID)
        assert ml.evaluate(c0, qn) == (one, 0)


def _enc(q):
    return P._enc(FP64, Fraction(q))


# =====================================================================
# the port against the model: the shape, the digests, the pins
# =====================================================================

def test_the_pins_cover_exactly_the_golden_stage():
    keys = {(fn, f.name, sf.RND_NAMES[r], n) for fn, f, n in CONFIGS
            for r in P.check_attrs(f, n)}
    assert keys == set(P.PINS_N)
    assert {(fn, f.name, n) for fn, f, n in CONFIGS} == set(P.EFT_N)
    # the study's 5.1 (MEASURED by the model's costs.py): n = 3, rne
    study = {("pown", "fp64"): range(380, 387), ("pown", "fp128"):
             range(436, 443), ("pown", "fp256"): range(487, 494),
             ("rootn", "fp64"): range(381, 388), ("rootn", "fp128"):
             range(437, 444), ("rootn", "fp256"): range(488, 495),
             ("compound", "fp64"): range(404, 411), ("compound", "fp128"):
             range(463, 470), ("compound", "fp256"): range(514, 521)}
    for (fn, fm), rng in study.items():
        assert P.PINS_N[(fn, fm, "rne", 3)][0] in rng, (fn, fm)
    live = {fn: {P.PINS_N[(fn, f.name, "rne", 3)][2] for f in FORMATS}
            for fn in INT_FUNCS}
    assert live == {"pown": {20, 21}, "rootn": {19}, "compound": {22}}  # 5.1


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", INT_FUNCS)
def test_shape_digests_phases_and_eft_are_the_models(fn, fmt):
    for n in ml.pow_check_ns(fn, fmt):
        assert P.check_shape_n(fn, fmt, n) == [], (fn, n)
        # the design's order and the scheduled fragment are one graph
        b = P.build_n(fn, fmt, RNE, n)
        assert ml.dag_digest(b.fragment(schedule=False)) == \
            ml.dag_digest(b.fragment())


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", INT_FUNCS)
def test_the_caps_are_the_measured_maximum_and_a_cap_under_fails(fn, fmt):
    assert P.check_caps_n(fn, fmt) == []


# =====================================================================
# the checks, clean
# =====================================================================

@pytest.mark.parametrize("cfg", CONFIGS, ids=cid)
def test_pools(cfg):
    fn, fmt, n = cfg
    xs = P.pool_n(fn, fmt, n)
    for rnd in P.check_attrs(fmt, n):
        out, t = P.check_pools_n(fn, fmt, rnd, n)
        assert out == [] and t.wrong == [] and t.stray == []
        assert t.n == len(xs)
        want = P.POOL_MARKS_N.get((fn, fmt.name, n))
        assert (want is None) == (not xs)
        if want is not None:
            assert len(t.marked) == want[sf.RND_NAMES[rnd]]


def test_the_pools_are_the_stages_over_31_n():
    for fmt, size in ((FP64, 4260), (FP128, 4131), (FP256, 3204)):
        for fn in INT_FUNCS:
            pl = P.pool(fn, fmt)
            assert len(pl) == size and len({ln[1] for ln in pl}) == 31


@pytest.mark.parametrize("cfg", CONFIGS, ids=cid)
def test_specials(cfg):
    fn, fmt, n = cfg
    out, cnt = P.check_specials_n(fn, fmt, n, P.check_attrs(fmt, n))
    assert out == [] and cnt > 20
    if n in (0, 1, 3, -3):
        out, cnt = P.check_specials_n(fn, fmt, n)          # all five
        assert out == []


@pytest.mark.parametrize("cfg", CONFIGS, ids=cid)
def test_structured(cfg):
    fn, fmt, n = cfg
    for rnd in P.check_attrs(fmt, n):
        out, cnt = P.check_structured_n(fn, fmt, rnd, n)
        assert out == [] and (cnt > 0 or abs(n) > 17)


def test_the_named_special_rows():
    """The study's section 4 rows by the rule: rootn(+-0, n) by parity at 2,
    3, -2, -3; pown(-1, 2^63 - 1) = -1 and pown(-1, -2^63) = +1."""
    for fmt in FORMATS:
        names = {(fn, n): [lab for lab, _l, _w in
                           P._named_special_lanes(fn, fmt, n)]
                 for fn, n in (("rootn", 2), ("rootn", -3), ("pown", 2 ** 63
                                                              - 1),
                               ("pown", -2 ** 63), ("compound", 3))}
        assert names[("rootn", 2)] == ["rootn(+0, 2)", "rootn(-0, 2)"]
        assert names[("pown", 2 ** 63 - 1)] == [f"pown(-1, {2 ** 63 - 1})"]
        assert len(names[("compound", 3)]) == 5
    rows = {fn: P.check_specials_n(fn, FP64, n)
            for fn, n in (("rootn", 2), ("rootn", 3), ("rootn", -2),
                          ("rootn", -3), ("pown", 2 ** 63 - 1),
                          ("pown", -2 ** 63))}
    assert all(out == [] for out, _c in rows.values())


# regions: the study's 3.3, 20 lanes a region at fp64 and 6 above (the box command's default is REGION_LANES: 400 and 80)
@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", INT_FUNCS)
def test_regions(fn, fmt):
    results = {}
    cnt = 20 if fmt.name == "fp64" else 6
    for name in P.region_names_n(fn, fmt):
        lanes = P.region_n_cached(fmt, fn, name, cnt, 1)
        assert lanes, name
        found = []
        main = marked = 0
        for rnd in ((RNE, RUP) if fmt.name == "fp64" else (RNE,)):
            out, (nl, mk, mn) = P.check_regions_n(fn, fmt, rnd, name, cnt)
            found += out
            main = max(main, mn)
            marked += mk
        results[name] = (main, len(lanes), found)
        assert found == [], (name, found[:1])
    passed, nm, lines, res = P.region_summary_n(results)
    assert "RESULT: ok" in res and passed + len(nm) == len(results)
    for name in nm:
        assert f"{name}: NOT MEASURED" in " ".join(lines)
    # the only region expected to measure nothing is int63 at fp64 for pown
    # (the study's 3.3: it finds no main-path lane)
    assert set(nm) <= ({"int63"} if (fn, fmt.name) == ("pown", "fp64")
                       else set()), nm
    # zone, nlow and the others reach the main path
    assert results["int"][0] > 0 and results["zone"][0] > 0
    if fmt.name == "fp64" and fn in ("pown", "compound"):
        assert results["nlow"][0] > 20


def test_int63_at_fp64_is_not_measured_and_says_so():
    fn, fmt = "pown", FP64
    out, (lanes, marked, main) = P.check_regions_n(fn, fmt, RNE, "int63")
    assert out == [] and main == 0 and lanes == 40      # REGION_LANES // 10
    line = P.region_line_n("int63", main, lanes)
    assert line == ("int63: NOT MEASURED (40 lanes, none reaches the main "
                    "path)")
    assert "measured (" not in line
    res = {"int63": (0, 40, []), "int": (39, 40, [])}
    passed, nm, lines, text = P.region_summary_n(res)
    assert (passed, nm) == (1, ["int63"])
    assert "1 NOT MEASURED (int63)" in text and "RESULT: ok" in text
    # and the bound's check does not crash on it (rc 0, a printed count)
    out, (worst, main_b, total) = P.check_bound_n(fn, fmt, RNE, "int63")
    assert out == [] and main_b == 0 and total == 8
    R.OUT = None
    R.FINDINGS.clear()
    rc = R.main(["pow-bound", "--fn", "pown", "--formats", "fp64", "--ns",
                 "-9223372036854775808", "--n", "6"])
    assert rc == 0 and not R.FINDINGS


def test_nlow_reaches_the_main_path_and_has_both_signs_of_n_l():
    for fn in ("pown", "compound"):
        lanes = P.region_n_cached(FP64, fn, "nlow", 40, 1)
        ns = {ln[1] for ln in lanes}
        assert ns == set(P.NLOW_NS)
        signs = {ml._pow_int_words(FP64, n)[1] is not None and
                 P.value(FP64, ml._pow_int_words(FP64, n)[1]) < 0
                 for n in ns}
        assert signs == {True, False}
        main, total = P.reach_n(fn, FP64, lanes)
        assert main > 40 and total == len(lanes)


@pytest.mark.parametrize("cfg", [(fn, f, n) for fn in INT_FUNCS
                                 for f in FORMATS for n in (3, -3)], ids=cid)
def test_seq(cfg):
    fn, fmt, n = cfg
    out, lanes = P.check_seq_n(fn, fmt, RNE, n)
    assert out == [] and len(lanes) > 20


def test_seq_of_the_small_fragments_and_a_large_n():
    for fn, fmt, n in (("pown", FP64, 0), ("compound", FP64, 1),
                       ("rootn", FP64, 1), ("pown", FP64, 2 ** 53 + 1),
                       ("rootn", FP128, -2 ** 63)):
        out, lanes = P.check_seq_n(fn, fmt, RTZ, n)
        assert out == [], (fn, n)


@pytest.mark.parametrize("fmt", FORMATS, ids=fid)
@pytest.mark.parametrize("fn", INT_FUNCS)
def test_bound(fn, fmt):
    sets = {}
    for name in P.region_names_n(fn, fmt):
        out, (worst, main, total) = P.check_bound_n(fn, fmt, RNE, name)
        assert out == [], (name, out)
        sets[name] = (worst, main, total)
        if main:
            assert worst < 0
    assert sets["int"][1] > 0 and sets["zone"][1] > 0
    # the zone's and int1000's direct errors are a sample of 8 points a region:
    # the budget at 10,000 lanes is parcel M3G3's, on the box


@pytest.mark.parametrize("fn", INT_FUNCS)
def test_core(fn):
    out, (worst, n_main, signs) = P.check_core_n(fn, FP64)
    assert out == []
    if fn != "rootn":
        assert n_main > 50 and signs == [False, True] and worst < 0
    # the Fraction ybound's Bv is the exact bound at fp64 and absent at fp128
    for fmt in (FP128, FP256):
        assert ml.plan_pow(fmt).B2 == 0
        assert "YB2" not in P.build_n(fn, fmt, RNE, 3).roles
    assert "YB2" in P.build_n(fn, FP64, RNE, 3).roles
    assert "B2" not in P.build_n(fn, FP64, RNE, 3).roles


def test_n_l_is_nonzero_exactly_above_2_53_at_fp64():
    for n in (2 ** 53, -2 ** 53, 2 ** 53 + 1, 2 ** 54 + 3, -(2 ** 54 + 3),
              2 ** 63 - 1, 3):
        hi, lo = ml._pow_int_words(FP64, n)
        assert (lo is None) == (abs(n) <= 2 ** 53 or abs(n) == 2 ** 62
                                or n == -2 ** 63), n
        got = P.value(FP64, hi) + (0 if lo is None else P.value(FP64, lo))
        assert got == n
    for fmt in (FP128, FP256):
        assert ml._pow_int_words(fmt, 2 ** 63 - 1)[1] is None


# =====================================================================
# the constants
# =====================================================================

def test_constants_in_process_a_part():
    out, lines = P.check_constants_n(formats=(FP64, FP128),
                                     ns=(0, 1, 3, -3, 2 ** 53 + 1))
    assert out == [] and len(lines) == 6
    for fn in INT_FUNCS:
        assert any(ln.startswith(f"{fn} fp64:") for ln in lines)


def test_constants_as_a_program():
    out, lines = P.check_constants_n_cli()
    assert out == []
    assert lines[-1] == ("mathlib --check (pow, integer operand): 3 routines, "
                         "3 formats, 0 differences")


def test_only_pow_is_unchanged_and_pow_n_is_a_word():
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--only", "pow-n"], capture_output=True, text=True,
                       cwd=PYTHON_DIR)
    assert r.returncode == 0
    rows = r.stdout.splitlines()
    assert rows[0].split()[:4] == ["routine", "format", "rnd", "n"]
    got = {(ln.split()[0], ln.split()[1], int(ln.split()[3]))
           for ln in rows[1:]}
    assert got == {(fn, f.name, n) for fn, f, n in CONFIGS}
    assert len(rows) == 1 + sum(len(P.check_attrs(f, n))
                                for _fn, f, n in CONFIGS)
    r = subprocess.run([sys.executable, "-B", "-m", "cft_golden.mathlib",
                        "--only", "pown"], capture_output=True, text=True,
                       cwd=PYTHON_DIR)
    assert r.returncode != 0 and "pow-n" in r.stderr


# =====================================================================
# the plants: every check on every plant, the control green
# =====================================================================

# PLANT_RED[plant][(fn, n)] = the checks RED at (fn, n) at fp64 (the others green), MEASURED by the
# parcel's scratch run of harness.red_checks_n over the whole PLANT_N matrix at its tip; a row lists every
# check of CHECKS, in CHECKS order (pools, regions, specials, structured, seq, bound, shape, core, constants),# True where red: a row with fewer than nine entries is a finding of the test
_RED = {
    None: {
        ('pown', 3): (False, False, False, False, False, False, False, False, False),
        ('rootn', 3): (False, False, False, False, False, False, False, False, False),
        ('compound', 3): (False, False, False, False, False, False, False, False, False),
        ('pown', 9007199254740993): (False, False, False, False, False, False, False, False, False),
    },
    'rootn_m0_neg': {
        ('rootn', 2): (True, False, True, True, True, False, True, False, False),
    },
    'compound_onep_rounded': {
        ('compound', 3): (True, False, True, True, True, False, True, False, False),
    },
    'n_low_dropped': {
        ('pown', 9007199254740993): (False, True, True, False, False, True, True, True, True),
        ('compound', 9007199254740993): (False, True, True, False, False, True, True, True, True),
    },
    'n_word_ulp': {
        ('pown', 3): (True, True, True, True, True, True, True, False, True),
        ('rootn', 3): (True, True, True, True, True, True, True, False, True),
        ('compound', 3): (True, False, True, True, True, True, True, False, True),
    },
    'n_row_loud': {
        ('pown', 3): (False, False, True, False, True, False, True, False, False),
        ('rootn', 3): (False, False, True, False, True, False, True, False, False),
        ('compound', 3): (False, False, True, False, True, False, True, False, False),
    },
    'exact_unmarked': {
        ('pown', 2): (True, False, True, True, True, False, True, False, False),
        ('compound', 2): (True, False, True, True, True, False, True, False, False),
        ('rootn', 2): (True, False, False, True, True, False, True, False, False),
    },
    'exact_rule_off': {
        ('pown', 2): (True, False, True, True, True, False, True, False, False),
        ('rootn', 2): (True, False, True, True, True, False, True, False, False),
        ('compound', 2): (True, False, False, True, False, False, True, False, False),
    },
    'exact_rule_no_tl': {
        ('pown', 3): (False, False, False, False, False, False, True, False, False),
        ('compound', 3): (False, False, False, False, False, False, True, False, False),
    },
    'midpoint_unmarked': {
        ('pown', 2): (False, False, False, False, False, False, True, False, False),
    },
    'near_one_gate_off': {
        ('compound', 3): (True, False, False, False, False, False, True, False, True),
        ('rootn', 1000): (False, False, False, False, False, False, True, False, True),
    },
    'side_rule_off': {
        ('compound', 3): (False, False, False, False, False, False, True, False, True),
        ('rootn', 1000): (False, False, False, False, False, False, True, False, True),
    },
    'screen_low': {
        ('pown', 3): (False, False, False, False, False, False, True, False, True),
        ('rootn', 3): (False, False, False, False, False, False, True, False, True),
        ('compound', 3): (False, False, False, False, False, False, True, False, True),
    },
    'mark_silenced': {
        ('pown', 3): (True, False, True, True, True, False, True, False, False),
        ('rootn', 3): (True, False, False, True, True, False, True, False, False),
        ('compound', 3): (True, False, True, True, True, False, True, False, False),
    },
    'bound_loose': {
        ('pown', 2): (True, False, True, True, True, True, True, False, True),
        ('rootn', 3): (True, False, False, True, True, True, True, False, True),
        ('compound', 3): (True, False, True, True, True, True, True, False, True),
    },
    'zero_sign_lost': {
        ('pown', 3): (False, False, False, True, True, False, True, False, False),
    },
    'log_table_entry': {
        ('pown', 3): (True, False, True, True, True, False, True, False, True),
        ('rootn', 3): (False, False, False, True, True, True, True, False, True),
        ('compound', 3): (True, False, True, True, True, False, True, False, True),
    },
    'il2h_ulp': {
        ('pown', 3): (True, True, True, True, True, True, True, False, True),
        ('rootn', 3): (True, True, False, True, True, True, True, False, True),
        ('compound', 3): (True, False, True, True, True, True, True, False, True),
    },
    'screen_ulp': {
        ('pown', 3): (False, False, False, False, False, False, True, False, True),
        ('rootn', 3): (False, False, False, False, False, False, True, False, True),
        ('compound', 3): (False, False, False, False, False, False, True, False, True),
    },
    'two_sum_all': {
        ('pown', 3): (False, False, False, False, False, False, True, False, False),
        ('rootn', 3): (False, False, False, False, False, False, True, False, False),
        ('compound', 3): (False, False, False, False, False, False, True, False, False),
    },
    'log_short': {
        ('pown', 3): (False, False, False, False, False, False, True, False, True),
        ('rootn', 3): (False, False, False, False, False, False, True, False, True),
        ('compound', 3): (False, False, False, False, False, False, True, False, True),
    },
}
PLANT_RED = {pl: {key: dict(zip(P.CHECKS, row)) for key, row in cases.items()}
             for pl, cases in _RED.items()}


def _row_ok(row):
    """The row assertion: nine booleans, one for each check of CHECKS."""
    assert len(row) == len(P.CHECKS), row
    assert all(isinstance(v, bool) for v in row)


def test_the_plant_rows_list_every_check_and_every_plant():
    assert set(PLANT_RED) == set(P.PLANT_N) | {None}
    assert set(ml.POW_PLANTS) == set(P.PLANT_N) | P.POW_FRONT_ONLY
    assert len(ml.POW_PLANTS) == 28 and len(P.POW_FRONT_ONLY) == 8
    for plant, cases in _RED.items():
        assert {k for k in cases} == (set(P.PLANT_N[plant]) if plant else
                                      set(PLANT_RED[None]))
        for key, row in cases.items():
            _row_ok(row)
            assert tuple(PLANT_RED[plant][key]) == P.CHECKS
    # the row assertion refuses a row that omits a check or is not a bool
    good = _RED["n_word_ulp"][("pown", 3)]
    _row_ok(good)
    for bad in (good[:-1], good[1:], good + (True,), good[:-1] + (1,)):
        with pytest.raises(AssertionError):
            _row_ok(bad)


def _plant_cases():
    out = [(None, fn, n) for fn, n in ((fn, 3) for fn in INT_FUNCS)]
    out.append((None, "pown", 2 ** 53 + 1))
    # one case a plant by default (the second and third of a plant are the
    # full matrix, CFT_POW_N_FULL=1)
    import os
    full = os.environ.get("CFT_POW_N_FULL") == "1"
    for plant, cases in P.PLANT_N.items():
        for fn, n in (cases if full else cases[:1]):
            out.append((plant, fn, n))
    return out


@pytest.mark.parametrize("case", _plant_cases(),
                         ids=lambda c: f"{c[0]}-{c[1]}-{c[2]}")
def test_plants_are_red_where_the_table_says_and_the_control_green(case):
    plant, fn, n = case
    red = P.red_checks_n(plant, fn, n)
    got = {c: bool(red.get(c)) for c in P.CHECKS}
    assert got == PLANT_RED[plant][(fn, n)], \
        {c: v for c, v in red.items()}
    if plant is None:
        assert not red
    else:
        assert any(got.values()), "a plant red in no check"
        # a finding names its check
        for check, found in red.items():
            assert all(s.startswith(f"{check}:") for s in found), check


def test_plants_the_pow_front_owns_are_refused_on_the_three_by_name():
    for plant in sorted(P.POW_FRONT_ONLY):
        for fn in INT_FUNCS:
            with pytest.raises(ValueError, match="does not apply"):
                ml.build(fn, FP64, RNE, n=3, plant=plant)
    for plant in ("bound_tight", "zone_bound_off"):
        with pytest.raises(ValueError, match="unknown plant"):
            ml.build("pown", FP64, RNE, n=3, plant=plant)       # M3G3's
    # rootn's plant at an odd n, and the core plants of the others
    with pytest.raises(ValueError, match="does not apply"):
        ml.build("rootn", FP64, RNE, n=3, plant="rootn_m0_neg")
    with pytest.raises(ValueError, match="does not apply"):
        ml.build("pown", FP64, RNE, n=2, plant="rootn_m0_neg")
    with pytest.raises(ValueError, match="does not apply"):
        ml.build("pown", FP64, RNE, n=3, plant="compound_onep_rounded")
    with pytest.raises(ValueError, match="does not apply"):
        ml.build("rootn", FP64, RNE, n=3, plant="n_low_dropped")


def test_n_low_dropped_is_red_in_nlow_and_green_where_n_l_is_zero():
    # red: the nlow region and the core check, named
    out, _c = P.check_regions_n("pown", FP64, RNE, "nlow", 40,
                                plant="n_low_dropped")
    assert out and all(s.startswith("regions:") for s in out)
    core, _ = P.check_core_n("pown", FP64, RNE, plant="n_low_dropped")
    assert core and all(s.startswith("core:") for s in core)
    # green: the same fragment where n_l = 0 (n = 3, 2^62, -2^63; and at
    # fp128, where n is one word)
    for fmt, n in ((FP64, 3), (FP64, 2 ** 62), (FP64, -2 ** 63),
                   (FP128, 2 ** 63 - 1)):
        a = P.build_n("pown", fmt, RNE, n, "n_low_dropped")
        b = P.build_n("pown", fmt, RNE, n)
        assert ml.dag_digest(a.fragment()) == ml.dag_digest(b.fragment()), n


def test_a_doctored_row_that_omits_a_check_is_refused():
    row = dict(PLANT_RED["n_word_ulp"][("pown", 3)])
    del row["core"]
    assert set(row) != set(P.CHECKS)
    with pytest.raises(AssertionError):
        assert set(row) == set(P.CHECKS)


# =====================================================================
# every leg of three checks (and more) shown failing alone
# =====================================================================

def test_leg_pools_the_marks_the_size_and_a_wrong_lane():
    fn, fmt, n = "pown", FP64, 3
    f = P.fragment_n(fn, fmt, RNE, n)
    xs = list(P.pool_n(fn, fmt, n))
    marks = P.POOL_MARKS_N[(fn, "fp64", n)]["rne"]
    assert P.check_pools(f, xs, marks=marks)[0] == []
    out, _ = P.check_pools(f, xs, marks=marks + 1)               # the pin
    assert out and "lanes marked, the model's count" in out[0]
    out, _ = P.check_pools(f, xs, marks=marks, size=len(xs) + 1)  # the size
    assert out and "the model's pool has" in out[0]
    # an evaluator-less doctoring: results with one unmarked bit flipped
    results = [ml.evaluate(f, (x[0],)) for x in xs]
    i = next(i for i, (b_, fw) in enumerate(results) if not fw & ml.MARK)
    results[i] = (results[i][0] ^ 1, results[i][1])
    out, t = P.check_pools(f, xs, results=results, marks=marks)
    assert t.wrong and "unmarked lanes differ" in out[0]
    results[i] = (results[i][0] ^ 1, results[i][1] | 0x20)       # stray bit
    out, t = P.check_pools(f, xs, results=results, marks=marks)
    assert t.stray and "flag words carry bits" in " ".join(out)


def test_leg_regions_an_evaluator_that_is_wrong():
    fn, fmt, n = "compound", FP64, 3
    f = P.fragment_n(fn, fmt, RNE, n)
    lanes = list(P.region_n_cached(fmt, fn, "int", 12, 1))

    def bad(f_, lane):
        bits, fw = ml.evaluate(f_, (lane[0],))
        return bits ^ 1, fw & ~ml.MARK
    out, _ = P.check_regions(f, {"int": lanes}, first=[], evaluator=bad)
    assert out and out[0].startswith("regions:")
    assert P.check_regions(f, {"int": lanes}, first=[],
                           evaluator=P.EV_N)[0] == []


def test_leg_specials_the_marks_the_rows_and_a_named_row():
    fn, fmt, n = "pown", FP64, 3
    frags = {r: P.fragment_n(fn, fmt, r, n) for r in RND}
    rows = P.special_rows_n(fn, fmt, n)
    label = rows[0][0]
    good = sum(P.SPECIAL_MARKS_N[(fn, "fp64", n)])
    assert P.check_specials(fmt, fn, frags, evaluator=P.EV_N, rows=rows,
                            marks={label: good})[0] == []
    out, _ = P.check_specials(fmt, fn, frags, evaluator=P.EV_N, rows=rows,
                              marks={label: good + 1})
    assert out and "marks over the five attributes" in out[0]

    def bad(f, lane):
        bits, fw = ml.evaluate(f, (lane[0],))
        return (bits ^ 1, fw) if lane[0] == sf.inf_bits(fmt) else (bits, fw)
    out, _ = P.check_specials(fmt, fn, frags, evaluator=bad, rows=rows,
                              marks={label: good})
    assert out and "unmarked lanes differ" in out[0]
    # a named row: rootn(-0, 2) is +0; the plant answers -0 and fails it alone
    out, _ = P.check_specials_n("rootn", FP64, 2, (RNE,),
                                plant="rootn_m0_neg")
    assert any("named row rootn(-0, 2)" in s for s in out)


def test_leg_structured_decided_marked_and_midpoint():
    fn, fmt, n = "pown", FP64, 2
    f = P.fragment_n(fn, fmt, RNE, n)
    rows = P.structured_rows_n(fn, fmt, n)
    labels = {lab.split(" (")[0] for lab, _l, _e in rows}
    assert any(e == "marked" for _l, _ls, e in rows)
    assert any(e == "midpoint" for _l, _ls, e in rows)
    assert P.check_structured(f, evaluator=P.EV_N, rows=rows)[0] == []

    def marks_all(f_, lane):
        bits, fw = ml.evaluate(f_, (lane[0],))
        return bits, fw | ml.MARK | 0x10

    def marks_none(f_, lane):
        bits, fw = ml.evaluate(f_, (lane[0],))
        return bits, fw & ~ml.MARK
    out, _ = P.check_structured(f, evaluator=marks_all, rows=rows)
    assert any("is marked, the design decides it" in s for s in out)
    out, _ = P.check_structured(f, evaluator=marks_none, rows=rows)
    assert any("is not marked, the in-lane test cannot decide it" in s
               for s in out)


def test_leg_seq_the_flag_byte_and_status():
    fn, fmt, n = "rootn", FP64, 3
    f = P.fragment_n(fn, fmt, RNE, n)
    xs = P.seq_lanes_n(fn, fmt, n)
    assert P.check_seq(f, xs=xs, rows=P.structured_rows_n(fn, fmt, n))[0] == []
    out, _ = P.check_seq(f, xs=xs, rows=P.structured_rows_n(fn, fmt, n),
                         evaluator=lambda f_, lane: (0, 0))
    assert out and "seq.py and evaluate() differ" in out[0]


def test_leg_shape_every_pinned_field_and_the_caps():
    fn, fmt, n = "pown", FP64, 3
    key = (fn, "fp64", "rne", n)
    pins = dict(P.PINS_N)
    for i, name in enumerate(("instructions", "bank words", "values live",
                              "dag digest", "instructions-by-phase")):
        doctored = list(pins[key])
        doctored[i] = doctored[i] + 1 if isinstance(doctored[i], int) \
            else "0" * len(doctored[i])
        out = P.check_shape_n(fn, fmt, n, (RNE,), pins={**pins, key:
                                                        tuple(doctored)})
        assert len(out) == 1 and name in out[0], (name, out)
    eft = dict(P.EFT_N)
    eft[(fn, "fp64", n)] = (0, 0)
    out = P.check_shape_n(fn, fmt, n, (RNE,), eft=eft)
    assert len(out) == 1 and "Fast2Sums" in out[0]
    # the cap: one more and one less, each failing alone
    caps = {k: dict(v) for k, v in ml.POW_LIVE_CAP.items()}
    caps[fn]["fp64"] = 22
    out = P.check_caps_n(fn, fmt, ns=(3,), caps=caps)
    assert len(out) == 1 and "the cap is 22, the most values live" in out[0]
    caps[fn]["fp64"] = 20
    out = P.check_caps_n(fn, fmt, ns=(3,), caps=caps)
    assert len(out) == 1 and "the cap is 20, the most values live" in out[0]
    # the flag word's values
    out = P.check_shape_n("compound", fmt, 1, (RNE,),
                          pins=P.PINS_N)
    assert out == []


def test_leg_core_one_sign_of_n_l_and_a_wrong_ybound():
    lanes = [ln for ln in P.region_n_cached(FP64, "pown", "nlow", 40, 5)
             if ln[1] == 2 ** 53 + 1]
    out, (_w, _n, signs) = P.check_core_n("pown", FP64, lanes=lanes)
    assert signs == [False] and any("one sign" in s for s in out)
    # the pinned Bv: a build with the YB2 word one ulp off fails the exact-bound leg
    out, _ = P.check_core_n("pown", FP64, plant=None)
    assert out == []
    b = P.build_n("pown", FP64, RNE, 3, "n_word_ulp")
    assert b.roles["NH"]                         # (constants: the other leg)


def test_leg_constants_each_role_alone():
    fmt = FP64
    base = lambda name, f_, r_, n_: P.build_n(name, f_, r_, n_)    # noqa: E731
    assert P.check_constants_n(builder=base, formats=(fmt,), attrs=(RNE,),
                               names=("pown",), ns=(3,))[0] == []

    def doctored(role, delta):
        def builder(name, f_, r_, n_):
            b = P.build_n(name, f_, r_, n_)
            import copy
            b2 = copy.copy(b)
            b2.words = dict(b.words)
            nm = b.roles[role][1]
            b2.words[nm] = b.words[nm] + delta
            return b2
        return builder
    for fn, role in (("pown", "NH"), ("pown", "YB2"), ("rootn", "RNH"),
                     ("rootn", "RNL"), ("compound", "SMALL"),
                     ("compound", "K_CLAMP"), ("compound", "NH"),
                     ("pown", "SIGN"), ("pown", "TOVF")):
        n = 3 if role != "RNL" else 3
        out, _ = P.check_constants_n(builder=doctored(role, 1),
                                     formats=(fmt,), attrs=(RNE,),
                                     names=(fn,), ns=(n,))
        assert any(f" {role}:" in s for s in out), (fn, role, out[:2])
    # a word with no role, and a role not asked: the small fragments' check
    b = P.build_n("compound", FP64, RNE, 1)
    findings = []
    ml._check_pow_small(b, findings)
    assert findings == []


def test_leg_constants_n_words_by_integer_arithmetic_at_a_tie():
    """n = 2^53 + 1 is a tie between 2^53 and 2^53 + 2: n_h = 2^53 (even), n_l
    = 1; the check asks the exact integer, and a doctored n_h of 2^53 + 2 (n_l
    = -1 would be the sum) fails it."""
    hi, lo = ml._pow_int_words(FP64, 2 ** 53 + 1)
    assert (P.value(FP64, hi), P.value(FP64, lo)) == (2 ** 53, 1)
    out, _ = P.check_constants_n(formats=(FP64,), attrs=(RNE,),
                                 names=("pown", "compound"),
                                 ns=(2 ** 53 + 1,))
    assert out == []


# =====================================================================
# nothing moved
# =====================================================================

def test_pow_and_powr_are_untouched_by_the_integer_operand():
    # the 30 digests of test_mathlib_pow.py's DIGESTS, by the one table that
    # holds them
    import test_mathlib_pow as T
    for fn in ("pow", "powr"):
        for fmt in FORMATS:
            for rnd in RND:
                got = ml.dag_digest(P.fragment_of(fn, fmt, rnd))[:32]
                assert got == T.DIGESTS[f"{fn}/{fmt.name}/{rid(rnd)}"]
