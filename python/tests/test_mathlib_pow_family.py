# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The structured families of pow, powr, pown, rootn and compound and the
exact-case rule (parcel M3G3): python/tests/mathlib_pow_family.py.

  the list      the committed list is a fresh generation from the theory, and
                a list edited by hand, a family's centre dropped, its range
                cut, the dominant threshold off by one, or B too small is not
  the classes   the theory's exact classes (integer arithmetic) agree with
                golden's own (transcend._pow_dyadic and the others)
  the census    the study's census at its seed and sizes (fp64, 8 families)
                reproduced by the port, counts pinned, 0 wrong unmarked
  the legs      the exact-case rule's four legs and "a mark off the list"
                each shown failing alone on a doctored input of its own
  the runs      every family's lanes through the fragments: every lane the
                theory demands marked is, no other is, every unmarked lane is
                right; the harness's structured rows and the pools' marks
                held to the theory
"""

import copy
import contextlib
import functools
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from cft_golden import FP64, FP128, FP256  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import transcend as tr  # noqa: E402

import mathlib_pow_family as PF  # noqa: E402
import mathlib_pow_harness as P  # noqa: E402

RNE, RTZ, RMM = sf.RND_RNE, sf.RND_RTZ, sf.RND_RMM
MARK = ml.MARK
FNS = ml.POW_NAMES


@contextlib.contextmanager
def patched(**kw):
    """Set module attributes of mathlib_pow_family for a block, with the
    generators' cache cleared on the way in and out."""
    old = {k: getattr(PF, k) for k in kw}
    for k, v in kw.items():
        setattr(PF, k, v)
    PF.family_lanes.cache_clear()
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(PF, k, v)
        PF.family_lanes.cache_clear()


# =====================================================================
# the committed list
# =====================================================================

def test_the_committed_list_is_a_fresh_generation_from_the_theory():
    assert PF.check_family_list(PF._FAMILY_CLASSES) == []
    fresh = PF.generate()
    assert PF._FAMILY_CLASSES == {fn: {f: {c: [tuple(e) for e in es]
                                           for c, es in cs.items()}
                                       for f, cs in fm.items()}
                                  for fn, fm in fresh.items()}
    assert set(PF._FAMILY_CLASSES) == set(FNS)
    for fn in FNS:
        assert set(PF._FAMILY_CLASSES[fn]) == {"fp64", "fp128", "fp256"}
        for fmt_name, cs in PF._FAMILY_CLASSES[fn].items():
            assert set(cs) == {"nearest", "directed"} and cs["nearest"]
            for fam, *counts in cs["nearest"] + cs["directed"]:
                assert fam in PF.FAMILIES and len(counts) == 6
                assert sum(counts[1:]) == counts[0]       # every lane a status
    # POW_FAMILY[fn][fmt][attribute]: rtz, rdn and rup one class, rne and rmm
    # the other
    for fn in FNS:
        for fm, by in PF.POW_FAMILY[fn].items():
            assert set(by) == {"rne", "rtz", "rdn", "rup", "rmm"}
            assert by["rtz"] == by["rdn"] == by["rup"]
            assert by["rne"] == by["rmm"]
    # the size of the literal: under 450 lines (the brief's line)
    text = pathlib.Path(PF.__file__).read_text(encoding="utf-8")
    lit = text[text.index(PF._MARKER):].count("\n")
    assert 100 < lit < 450, lit


def test_a_committed_list_edited_by_hand_is_refused_and_named():
    fresh = PF.generate()
    ent = copy.deepcopy(PF._FAMILY_CLASSES)
    ent["pown"]["fp64"]["directed"][0] = (
        ent["pown"]["fp64"]["directed"][0][:2] + (1,)
        + ent["pown"]["fp64"]["directed"][0][3:])
    out = PF.check_family_list(ent, fresh)
    assert len(out) == 1 and "pown fp64 directed" in out[0] \
        and "intpow" in out[0]
    ent = copy.deepcopy(PF._FAMILY_CLASSES)
    del ent["rootn"]["fp256"]["nearest"][1]
    out = PF.check_family_list(ent, fresh)
    assert len(out) == 1 and "rootn fp256 nearest" in out[0]
    ent = copy.deepcopy(PF._FAMILY_CLASSES)
    ent["pow"].pop("fp128")
    assert "pow fp128 nearest" in PF.check_family_list(ent, fresh)[0]


def _entries(fn="compound", fmt=FP64, cls="nearest"):
    return PF.entries(fmt, cls, fn)


def test_a_centre_dropped_a_range_cut_a_threshold_moved_or_b_too_small():
    """Each fault of the THEORY'S INPUTS makes the generated list differ from
    the committed one (the list is held to a fresh generation)."""
    want = PF._FAMILY_CLASSES["compound"]["fp64"]["nearest"]
    assert _entries() == want
    # a centre dropped: the first lane of the dominant family
    orig = PF.GENERATORS["dominant"]
    with patched(GENERATORS=dict(PF.GENERATORS, dominant=lambda f, fn:
                                 list(orig(f, fn))[1:])):
        assert _entries() != want
    # a family's range cut: intpow's exponents shortened by 1
    with patched(_ymax=lambda p, M: (p + 1) // M.bit_length()):
        assert PF.entries(FP64, "nearest", "pown") != \
            PF._FAMILY_CLASSES["pown"]["fp64"]["nearest"]
    # the dominant threshold off by one: x doubled (e + 1)
    shifted = lambda f, fn: [(x + (1 << f.man_w), n)       # noqa: E731
                             for x, n in orig(f, fn)]
    with patched(GENERATORS=dict(PF.GENERATORS, dominant=shifted)):
        assert _entries() != want
    # the committed B too small (0.38 -> 0.0): lanes the budget leaves
    # between 1 - B and 1 + B are called must or clear
    tb = dict(PF.THRESHOLD_B, **{("compound", "fp64"): 0.0})
    with patched(THRESHOLD_B=tb):
        assert _entries() != want
    assert _entries() == want                     # restored


# =====================================================================
# the theory against golden's classes
# =====================================================================

def test_the_theorys_exact_classes_equal_golden_s_own():
    n = 0
    for fn in FNS:
        for fam in ("intpow", "pow2", "smallint", "root2k"):
            lanes = PF.family_lanes(FP64, fn, fam)
            assert PF.check_classes(FP64, fn, fam, lanes) == [], (fn, fam)
            n += sum(PF.theory_class(FP64, fn, fam, ln) is not None
                     for ln in lanes)
    assert n > 300
    # the leg is red on a theory that is wrong: M^y of one bit too few
    lanes = PF.family_lanes(FP64, "pow", "intpow")
    real = PF.theory_class

    def off_by_one(fmt, fn, family, lane):
        got = real(fmt, fn, family, lane)
        return {"rep": "mid", "mid": "rep"}.get(got, got)
    with patched(theory_class=off_by_one):
        out = PF.check_classes(FP64, "pow", "intpow", lanes)
    assert out and "the theory says" in out[0]


def test_power_of_two_result_iff_decided_by_golden_s_function():
    """From golden's function applied to the lane, not a hand list: over every
    exact lane of every family at fp64, the lane is decided (never marked) iff
    golden's exact result has odd part 1 (a power of two)."""
    def odd_part(fn, ln):
        ux = sf.unpack(FP64, ln[0])
        if fn in ("pow", "powr"):
            m, _e = tr._pow_dyadic(FP64, ux, sf.unpack(FP64, ln[1]))
        elif fn == "pown":
            m, _e = tr._pown_dyadic(FP64, ux.m, ux.e, ln[1])
        elif fn == "rootn":
            m, _e = tr._rootn_dyadic(FP64, ux, ln[1])
        else:
            sm, se = tr._exact_one_plus(ux)
            m, _e = tr._pown_dyadic(FP64, sm, se, ln[1])
        return m >> ((m & -m).bit_length() - 1)
    n = 0
    for fn in FNS:
        for _fam, ln in PF.rule_lanes(FP64, fn):
            if PF.gated_why(FP64, fn, ln):
                continue
            n += 1
            assert (odd_part(fn, ln) == 1) == \
                (PF.status(FP64, RNE, fn, ln) == "decided"), (fn, ln)
    assert n > 400


# =====================================================================
# the study's census, ported
# =====================================================================

def test_the_census_port_reproduces_the_studys_counts_at_fp64():
    """docs/studies/m3/census.fp64-*.out.txt (seed 1, 300 lanes a family, hard3p
    400): the port draws with random.Random(seed * 7919 + width), the same
    calls in the same order, so the study's lanes are the port's: every class
    count and every (class, attribute) count of marked lanes, guesses that
    differ and wrong unmarked lanes equal the study's (rne, rtz and rmm; rdn
    and rup are rtz's), 0 wrong unmarked, 0 marks off the list. The study's
    off_rule of hard3p (60 = 12 lanes x 5 attributes) is the y = +1 lanes,
    which the rule's other domain decides (x itself): the port's off_rule is 0
    there."""
    for name in PF.CENSUS_FAMILIES:
        counts, res = PF.census_run(FP64, name, PF.CENSUS_COUNT[name],
                                    rnds=(RNE, RTZ, RMM))
        want_counts, want_res = PF.CENSUS_FP64[name]
        assert counts == want_counts, name
        for rnd_name, by in want_res.items():
            rnd = sf.RND_NAMES.index(rnd_name) if False else \
                {v: k for k, v in sf.RND_NAMES.items()}[rnd_name]
            if rnd not in res:
                continue
            for cls, pin in by.items():
                assert res[rnd][cls][:4] == pin, (name, rnd_name, cls)
        for rnd, row in res.items():
            for cls, v in row.items():
                assert v[3] == 0 and v[4] == 0 and v[5] == 0, (name, rnd, cls)


# =====================================================================
# the exact-case rule's legs, each failing alone
# =====================================================================

def _two(fmt, x, y):
    return (P._enc(fmt, x), P._enc(fmt, y))


def test_each_leg_of_the_exact_case_rule_fails_alone_on_a_doctored_input():
    from fractions import Fraction
    fmt = FP64
    real = PF.runner(fmt, "pow", RNE)
    pow2 = _two(fmt, 4, 3)                      # 4^3 = 64: base 2^2: decided
    nine = _two(fmt, 3, 2)                      # 3^2 = 9: exact, base 3: marked
    mid = (P._enc(fmt, 3), P._val if False else P._enc(fmt, 34))   # 3^34
    assert PF.status(fmt, RNE, "pow", pow2) == "decided"
    assert PF.status(fmt, RNE, "pow", nine) == "must"
    lanes = [pow2, nine]
    out, st = PF.check_exact_rule(fmt, RNE, "pow", run=real, lanes=lanes)
    assert out == [] and (st["decided"], st["marked"], st["replay"]) == \
        (1, 1, 1) and st["off_rule"] == 0

    def doctor(lane, fn):
        def run(ln):
            bits, fw = real(ln)
            return fn(bits, fw) if ln == lane else (bits, fw)
        return run
    # decided: the power of two marked
    out, _ = PF.check_exact_rule(fmt, RNE, "pow", lanes=lanes,
                                 run=doctor(pow2, lambda b, f: (b, f | MARK)))
    assert [o.split(":")[0] for o in out] == ["decided"]
    # marked: the 9 unmarked and WRONG
    out, _ = PF.check_exact_rule(fmt, RNE, "pow", lanes=lanes,
                                 run=doctor(nine, lambda b, f: (b ^ 1, 0)))
    assert [o.split(":")[0] for o in out] == ["marked"]
    # off_rule: the 9 decided unmarked and RIGHT (an exact representable lane
    # whose base is not a power of two)
    gb, gf = P.golden(fmt, RNE, nine, "pow")
    out, st = PF.check_exact_rule(fmt, RNE, "pow", lanes=lanes,
                                  run=doctor(nine, lambda b, f: (gb, gf)))
    assert [o.split(":")[0] for o in out] == ["off_rule"] and st["off_rule"] == 1
    # replay: the 9 marked with a guess that is not the exact value
    out, _ = PF.check_exact_rule(
        fmt, RNE, "pow", lanes=lanes,
        run=doctor(nine, lambda b, f: (b ^ 2, f | MARK)))
    assert [o.split(":")[0] for o in out] == ["replay"]
    # and the same input through the real run is green in every leg
    out, _ = PF.check_exact_rule(fmt, RNE, "pow", lanes=lanes, run=real)
    assert out == []
    del Fraction, mid


def test_a_mark_off_the_list_fails_and_names_the_lane():
    fmt = FP64
    real = PF.runner(fmt, "pow", RNE)
    clear = _two(fmt, 5, Fraction_half()) if False else _two(fmt, 5, 7)
    # 5^7 = 78125 is exact (rep): marked is right; take an irrational lane
    irr = _two(fmt, 3, __import__("fractions").Fraction(1, 3))
    assert PF.status(fmt, RNE, "pow", irr) == "clear"
    out, n = PF.check_off_list(fmt, RNE, "pow", [irr, clear])
    assert n == 2 and len(out) == 1 and "off_list" in out[0]
    assert hex(irr[0]) in out[0]
    # the same lane marked by a fault in the run, through check_lanes
    def marks_all(ln):
        bits, fw = real(ln)
        return bits, fw | MARK
    out, st = PF.check_lanes(fmt, RNE, "pow", [irr], marks_all)
    assert out and out[0].startswith("off_list:") and st["marked_clear"] == 1
    # a gated lane (a special row) marked: also off the list
    gated = (sf.one_bits(fmt), P._enc(fmt, 3))
    assert PF.status(fmt, RNE, "pow", gated) == "gated"
    out, _ = PF.check_lanes(fmt, RNE, "pow", [gated], marks_all)
    assert out and "gated" in out[0]
    # a must lane left unmarked fails the other way
    nine = _two(fmt, 3, 2)
    out, _ = PF.check_lanes(fmt, RNE, "pow", [nine],
                            lambda ln: P.golden(fmt, RNE, ln, "pow"))
    assert out and out[0].startswith("family:") and "must be marked" in out[0]


def Fraction_half():          # (kept for the doctored lane's readability)
    from fractions import Fraction
    return Fraction(1, 2)


# =====================================================================
# the families through the fragments
# =====================================================================

def _sums(fmt, fn, cls):
    return {s: sum(e[2 + i] for e in PF._FAMILY_CLASSES[fn][fmt.name][cls])
            for i, s in enumerate(PF.STAT)}


@pytest.mark.parametrize("fn", FNS)
def test_every_family_lane_is_what_the_theory_says_at_fp64(fn):
    """rne and rtz, every lane of every family of fn: the lanes the theory
    demands marked are marked, none it calls clear, decided or gated is (a mark
    off the list), every unmarked lane is equal to transcend.py, and the
    status counts are the committed list's."""
    for rnd, cls in ((RNE, "nearest"), (RTZ, "directed")):
        out, st = PF.check_family(FP64, rnd, fn)
        assert out == [], out
        want = _sums(FP64, fn, cls)
        for s in PF.STAT:
            assert st[s] == want[s], (fn, cls, s)
        assert st["marked_must"] == st["must"] and st["wrong"] == 0
        assert st["marked_clear"] == st["marked_decided"] == \
            st["marked_gated"] == 0
        o, rs = PF.check_exact_rule(FP64, rnd, fn)
        assert o == [] and rs["off_rule"] == 0
        assert rs["decided"] > 0 and rs["marked"] > 0


@pytest.mark.parametrize("fmt", [FP128, FP256], ids=lambda f: f.name)
def test_the_families_at_fp128_and_fp256_sampled(fmt):
    for fn in ("pow", "compound"):
        out, st = PF.check_family(fmt, RNE, fn, step=8)
        assert out == [] and st["wrong"] == 0, out


def test_the_claims_of_zero_are_the_families_that_mark_nothing():
    """pow2, near1, edges and the tie: the families the list says mark
    nothing (no must, no either lane under the class) have no mark, under the
    nearest and the directed attribute."""
    claims = [(fn, fmt, fam) for fn in FNS for fmt in (FP64,)
              for fam in ("pow2", "tie", "near1", "edges")
              if PF.family_lanes(fmt, fn, fam)]
    assert len(claims) >= 8
    for fn, fmt, fam in claims:
        for rnd, cls in ((RNE, "nearest"), (RTZ, "directed")):
            ent = {e[0]: e for e in PF._FAMILY_CLASSES[fn][fmt.name][cls]}[fam]
            out, st = PF.check_family(fmt, rnd, fn, families=(fam,))
            assert out == [], out
            if ent[2] == 0 and ent[4] == 0:                 # no must, either
                assert st["per"][fam][1] == 0, (fn, fam, cls)


def test_the_harness_s_structured_rows_are_held_to_the_theory():
    """Every lane of structured_rows (pow, powr) and structured_rows_n (the n
    list's, at each n) under the five attributes: each row's expectation
    agrees with the theory. (If one did not, the brief says stop: a committed
    lane of a merged parcel.)"""
    total = 0
    for fmt in (FP64, FP128, FP256):
        for fn in FNS:
            ns = P.check_ns(fn, fmt) if fn in ml.POW_INT_NAMES else ()
            out, n = PF.check_structured_rows(fmt, fn, ns=ns)
            assert out == [], out
            total += n
    assert total > 5000
    # a doctored row: a lane the theory demands marked in a "decided" row
    nine = _two(FP64, 3, 2)
    old = P.STRUCT_ROWS["pow"]
    P.STRUCT_ROWS["pow"] = lambda fmt: [("doctored", [nine], "decided")]
    try:
        out, _ = PF.check_structured_rows(FP64, "pow")
    finally:
        P.STRUCT_ROWS["pow"] = old
    assert len(out) == 5 and "doctored" in out[0] and "must by the theory" in \
        out[0]


def test_the_marks_of_the_pools_are_all_on_the_list():
    """check_pools' Tally.marked, held to the theory: pow and powr at fp64
    (every third lane of the pool, rne and rtz) and the n-keyed pools at
    n = 3 (pool_n's lanes): a mark off the list is a finding."""
    for fn in ("pow", "powr"):
        xs = list(P.pool(fn, FP64))[::3]
        for rnd in (RNE, RTZ):
            f = P.fragment_of(fn, FP64, rnd)
            out, t = P.check_pools(f, xs)
            assert out == [] and t.marked
            o, n = PF.check_off_list(FP64, rnd, fn, t.marked)
            assert o == [] and n == len(t.marked), o
    for fn in ml.POW_INT_NAMES:
        for rnd in (RNE, RTZ):
            out, t = P.check_pools_n(fn, FP64, rnd, 3)
            f_marked = [(x, 3) for x, _n in t.marked]
            o, n = PF.check_off_list(FP64, rnd, fn, f_marked)
            assert o == [], o
