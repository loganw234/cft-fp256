# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The structured families and the mark-rate law of atan, asin, acos and atan2
(parcel M4G4: python/tests/mathlib_inv_family.py and mathlib_inv_rate.py),
held to the study's 3.4 and 3.5: the committed list against a fresh
generation; the study's census counts at fp64 reproduced on the fragments; the
committed STRUCT lanes of waves 1 and 2 held to the predicate; a mark off the
list failing; every leg of every check failing alone on a doctored input; the
tool plants' matrix (each row listing every check); the fragment plants of
M4G1 red in the checks that read a fragment; the rate law with the crowding
split and its constants; the three box commands at --quick.

The theory shares nothing with the fragment: it is mpmath at 4p + 200 bits and
exact rationals. Nothing here imports docs/studies/m4.
"""

import functools
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

pytest.importorskip("mpmath")

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_inv_family as F  # noqa: E402
import mathlib_inv_harness as I  # noqa: E402
import mathlib_inv_rate as R  # noqa: E402
import mathlib_runs as RUNS  # noqa: E402

FORMATS = I.FORMATS
FUNCS = F.FUNCTIONS
RND = list(sf.RND_MODES)
MARK = ml.MARK
CHECKS = F.CHECKS


@functools.lru_cache(maxsize=None)
def frag(fn, fmt_name, rnd, plant=None):
    return ml.build(fn, I.BY_NAME[fmt_name], rnd, plant=plant).fragment()


@functools.lru_cache(maxsize=None)
def fresh():
    return F.generate()


def names(findings):
    """The set of checks the findings belong to (each begins with its name and
    a colon)."""
    return {f.split(":")[0] for f in findings}


# ---- the committed list -------------------------------------------------------

def test_the_committed_list_is_a_fresh_generation_from_the_theory():
    assert F.check_family_list(F.INV_FAMILY, fresh()) == []
    assert F.INV_FAMILY == fresh()
    # and the file's generated tail is the rendering of it, byte for byte: the
    # list is not edited by hand
    text = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    assert text[text.index(F._MARKER):] == F.render(fresh())
    assert "\r" not in text


def test_write_regenerates_the_tail_into_a_copy_of_the_module(tmp_path):
    src = pathlib.Path(F.__file__).read_text(encoding="utf-8")
    copy = tmp_path / "copy.py"
    cut = src.index(F._MARKER)
    copy.write_text(src[:cut], encoding="utf-8")
    F.write(copy, fresh())
    assert copy.read_text(encoding="utf-8") == src


def _doctored(edit):
    data = {fn: {f: {r: list(l) for r, l in per.items()}
                 for f, per in pf.items()} for fn, pf in fresh().items()}
    edit(data)
    return data


def test_the_generated_list_has_the_studys_shape():
    g = fresh()
    # fp64: atan 3 2^-26 under the nearest two, asin 3 2^-25 under the
    # directed three, atan2 3 2^-26; no tiny centre of acos
    assert ("tiny", 3, 26, 26) in g["atan"]["fp64"]["rne"]
    assert ("tiny", 3, 25, 25) in g["asin"]["fp64"]["rtz"]
    assert g["atan"]["fp64"]["rtz"] == g["atan"]["fp64"]["rdn"] == \
        g["atan"]["fp64"]["rup"]
    assert g["atan"]["fp64"]["rne"] == g["atan"]["fp64"]["rmm"]
    assert not any(e[0] == "tiny" for e in g["acos"]["fp64"]["rne"])
    # acos: positive windows only, and the claim of zero near 1
    for rnd, kind in (("rne", "mid"), ("rtz", "grid")):
        wins = [e for e in g["acos"]["fp64"][rnd] if e[0] == "win"]
        assert wins and all(e[2] == kind for e in wins)
    # the ratio family's threshold: j < 2^((p - G - 2)/2) = 11.3 at fp64 (11
    # measured), and 2^32.5 and 2^94.5 at the others
    for fmt in FORMATS:
        (en,) = [e for e in g["atan2"][fmt.name]["rtz"] if e[0] == "ratio"]
        assert en[1] == "deep"
        top = 2 ** ((fmt.prec - ml.GUARD[fmt.name] - 2) / 2)
        assert en[2] <= top < 1.6 * en[2], (fmt.name, en, top)
    assert [e for e in g["atan2"]["fp64"]["rtz"]
            if e[0] == "ratio"] == [("ratio", "deep", 11)]
    assert not [e for e in g["atan2"]["fp64"]["rne"] if e[0] == "ratio"]
    for fn in ("asin", "acos"):
        assert ("zero", "near1", 64) in g[fn]["fp128"]["rne"]
    assert ("zero", "diag", 40, 4) in g["atan2"]["fp256"]["rtz"]


def test_the_tool_plants_of_the_list_are_red_in_family_list():
    base = fresh()
    # a hand-edited list: a centre added that the theory does not generate
    bad = _doctored(lambda d: d["atan"]["fp64"]["rtz"].append(
        ("tiny", 5, 26, 26)))
    found = F.check_family_list(bad, base)
    assert len(found) == 1 and "extra" in found[0]
    # a centre dropped
    bad = _doctored(lambda d: d["atan"]["fp128"]["rtz"].remove(
        ("tiny", 3, 41, 55)))
    found = F.check_family_list(bad, base)
    assert len(found) == 1 and "missing" in found[0]
    # the ratio family's threshold one too high
    bad = _doctored(lambda d: d["atan2"]["fp64"]["rtz"].__setitem__(
        d["atan2"]["fp64"]["rtz"].index(("ratio", "deep", 11)),
        ("ratio", "deep", 12)))
    assert len(F.check_family_list(bad, base)) == 1
    # a whole cell missing, and a cell added
    bad = _doctored(lambda d: d["acos"]["fp64"].pop("rne"))
    assert len(F.check_family_list(bad, base)) == 1
    bad = _doctored(lambda d: d["acos"].__setitem__("fp32", {"rne": []}))
    assert len(F.check_family_list(bad, base)) == 1


# ---- the predicate -------------------------------------------------------------

def test_the_predicate_shares_nothing_with_the_fragment():
    # d is mpmath's: atan(2^-30) = x - x^3/3 + ... sits x^5/5 from the grid
    # point of its cell
    fmt = I.FP64
    x = ml._enc(fmt, F.Fraction(3, 2 ** 26))
    d = F.distance(fmt, I.RNE, "atan", x)
    assert 0 < d < 0.7
    assert F.classify(fmt, I.RNE, "atan", x) == "mark"
    assert F.classify(fmt, I.RTZ, "atan", x) == "clear"
    # a lane under the tiny gate and a zero are gated
    assert F.classify(fmt, I.RNE, "atan", ml._enc(
        fmt, F.Fraction(1, 2 ** 40))) == "gated"
    assert F.classify(fmt, I.RNE, "atan", 0) == "gated"
    assert F.classify(fmt, I.RNE, "asin", sf.one_bits(fmt)) == "gated"
    assert F.classify(fmt, I.RNE, "atan2", (sf.inf_bits(fmt), 1)) == "gated"
    # atan2's range
    assert F.classify(fmt, I.RNE, "atan2", (
        1, sf.one_bits(fmt))) == "mark"
    # the thresholds are 1 -+ B, B the cell's, and print as such
    assert F.thresholds(fmt, "asin") == (0.927, 1.073)
    assert F.thresholds(I.FP256, "atan") == (0.977, 1.023)


def test_the_ratio_threshold_is_exact_and_monotone():
    for fmt in FORMATS:
        for cls in ("directed",):
            j = F._ratio_threshold(fmt, cls, "deep")
            rep = F.rep_of(cls)
            lane = lambda jj: F.ratio_lane(fmt, F.ratio_k(fmt, "deep"), jj)
            assert F.classify(fmt, rep, "atan2", lane(j)) == "mark"
            assert F.classify(fmt, rep, "atan2", lane(j + 1)) != "mark"
            assert F.classify(fmt, rep, "atan2", lane(1)) == "mark"
        assert F._ratio_threshold(fmt, "nearest", "deep") == 0
        assert F._ratio_threshold(fmt, "directed", -10) == 0
        assert F._ratio_threshold(fmt, "directed", -40) == 0


def test_the_deep_family_closes_where_tiny_top_says():
    # the odd multiples of 3 of b bits (the smallest, the middle, the
    # largest) that have a window under rne or rtz: some up to tiny_top(fmt),
    # none one or two past it (the study's c of about 2^12 at fp128 and 2^33
    # at fp256)
    def windows(fmt, fn, b):
        lo, hi = 1 << (b - 1), (1 << b) - 1
        first = lo + (3 - lo) % 6
        last = hi - (hi - 3) % 6
        mid = first + ((last - first) // 2) // 6 * 6
        return sum(any(F.classify(fmt, r, fn, F.tiny_lane(fn, fmt, c, e))
                       == "mark" for r in (I.RNE, I.RTZ)
                       for e in F._exponents(fmt, fn, b))
                   for c in {first, mid, last})
    assert F.tiny_top(I.FP128) == 12 and F.tiny_top(I.FP256) == 33
    for fmt in FORMATS[1:]:
        top = F.tiny_top(fmt)
        at_top = 0
        for fn in ("atan", "asin", "atan2"):
            assert windows(fmt, fn, top - 1) == 3
            at_top += windows(fmt, fn, top)
            assert windows(fmt, fn, top + 1) == windows(fmt, fn, top + 2) == 0
        assert at_top >= 1                # the window is closing at top
    # and the deep arguments are lanes of those lengths only
    deep = F.deep_arguments(I.FP128, "atan")
    assert deep and all(F.classify(I.FP128, I.RNE, "atan", x) != "gated"
                        for x, _l in deep)


# ---- STRUCT: waves 1 and 2's committed lanes held to the predicate -----------------

# the three committed lanes whose d is past M2's fixed 0.7 (the lead's ruling of
# 2026-11-10): lane, attribute, d (MEASURED by check_struct)
PAST_07 = [("asin", 0x3e78000000000000, 0.7594),
           ("asin", 0x3e78000000000001, 0.8531),
           ("atan2", (0x3c00000000000000, 0x3ff000000000000b), 0.9453)]


@pytest.mark.parametrize("fmt", FORMATS, ids=lambda f: f.name)
def test_every_struct_lane_is_under_the_must_mark_threshold(fmt):
    n = 0
    for fn in FUNCS:
        for rnd in RND:
            out, rep = F.check_struct(fmt, rnd, fn)
            assert out == [], out
            n += len(rep)
    assert n > 0


def test_the_three_lanes_past_a_fixed_07_are_named_and_pinned():
    fmt = I.FP64
    for fn, lane, d in PAST_07:
        for rnd in (I.RTZ, I.RDN, I.RUP):
            got = F.distance(fmt, rnd, fn, lane)
            assert abs(got - d) < 5e-4 and got > 0.7, (fn, lane, got)
            assert got < F.thresholds(fmt, fn)[0]
    # every other STRUCT lane is under 0.7
    past = {(fn, lane) for fn, lane, _d in PAST_07}
    for fn in FUNCS:
        for rnd in RND:
            _out, rep = F.check_struct(fmt, rnd, fn)
            for x, d in rep:
                key = (fn, x & ~fmt.sign_mask if not isinstance(x, tuple)
                       else (x[0] & ~fmt.sign_mask, x[1]))
                assert d < 0.7 or key in past, (fn, x, d)


def test_the_struct_check_fails_on_a_doctored_lane():
    fmt = I.FP64
    # a lane whose d is past MUST_MARK: atan(3 2^-25) is nowhere near a
    # boundary under rne
    x = ml._enc(fmt, F.Fraction(3, 2 ** 25))
    table = {"atan": {"fp64": [((I.RNE,), [x])]}}
    out, rep = F.check_struct(fmt, I.RNE, "atan", table)
    assert names(out) == {"struct"} and len(out) == 2     # both signs
    assert all(d > F.thresholds(fmt, "atan")[0] for _x, d in rep)
    # and the committed table, untouched, is green
    assert F.check_struct(fmt, I.RNE, "atan")[0] == []


def test_between_07_and_must_mark_the_listed_lanes_are_counted():
    # the number of listed centres whose d is from 0.7 up to 1 - B, per
    # function and format (the directed three; the nearest two have none)
    want = {("asin", "fp64"): (1, 1), ("atan", "fp128"): (115, 1),
            ("asin", "fp128"): (115, 1), ("atan2", "fp128"): (115, 1),
            ("atan", "fp256"): (456, 1), ("asin", "fp256"): (456, 1),
            ("atan2", "fp256"): (456, 1)}
    for fmt in FORMATS:
        for fn in FUNCS:
            got = F.listed_between(fmt, I.RTZ, fn)
            assert got == want.get((fn, fmt.name),
                                   (got[0], 0)), (fn, fmt.name, got)
            assert F.listed_between(fmt, I.RNE, fn)[1] == 0


# ---- the fragments against the theory --------------------------------------------

@functools.lru_cache(maxsize=None)
def _family(fn, fmt_name, rnd, plant=None):
    fmt = I.BY_NAME[fmt_name]
    f = frag(fn, fmt_name, rnd, plant)
    return F.check_family(f, F.entries(fmt, rnd, fn), deep=plant is None)


def test_the_control_family_is_green_in_every_cell_at_fp64():
    for fn in FUNCS:
        for rnd in RND:
            out, st = _family(fn, "fp64", rnd)
            assert out == [], out
            assert st["marked_clear"] == st["marked_gated"] == 0
            assert st["marked_mark"] == st["mark"] > 0 or fn == "asin" \
                or st["mark"] == 0
            assert st["wrong"] == 0


def test_the_family_at_fp128_and_fp256_under_a_directed_and_a_nearest_attribute():
    for fmt in FORMATS[1:]:
        for fn in ("atan", "acos"):
            for rnd in (I.RNE, I.RTZ):
                f = frag(fn, fmt.name, rnd)
                ents = F.entries(fmt, rnd, fn)
                cen = F.expand(ents)
                small = [e for e in ents if e[0] not in ("tiny",)] + [
                    ("tiny", c[1], c[2], c[2]) for c in cen[:4]
                    if c[0] == "tiny"]
                out, st = F.check_family(f, small)
                assert out == [], out


def test_census_counts_at_fp64_are_the_studys():
    fmt = I.FP64
    got = {}
    for fn in FUNCS:
        for fam, lanes in F.census_lanes(fmt, fn).items():
            for rnd in RND:
                out, marked = F.check_census_counts(frag(fn, "fp64", rnd),
                                                    fam, lanes)
                assert out == [], out
                got[(fn, fam, sf.RND_NAMES[rnd])] = len(marked)
    # the study's 3.5 table: per attribute, tiny atan 6 / 0, asin 0 / 6,
    # atan2 18 / 0 (rne, rmm / each directed); the windows 258 under every
    # attribute (each kind's, 129 about each of two boundaries); the ratio's
    # 11 under the directed three; near 1 and the diagonals none
    for rn in ("rne", "rmm"):
        assert (got[("atan", "tiny", rn)], got[("asin", "tiny", rn)],
                got[("atan2", "tiny", rn)]) == (6, 0, 18)
        assert got[("atan2", "ratio", rn)] == 0
    for rn in ("rtz", "rdn", "rup"):
        assert (got[("atan", "tiny", rn)], got[("asin", "tiny", rn)],
                got[("atan2", "tiny", rn)]) == (0, 6, 0)
        assert got[("atan2", "ratio", rn)] == 11
    assert all(v == 258 for k, v in got.items() if k[1] == "near")
    assert all(v == 0 for k, v in got.items() if k[1] in ("near1", "diag"))
    assert len(F.census_lanes(fmt, "atan")["tiny"]) == 14 * 16 * 2
    assert len(F.census_lanes(fmt, "atan2")["diag"]) == 1440


def test_census_counts_at_fp128_tiny_are_the_studys():
    fmt = I.FP128
    for fn in ("atan", "asin"):
        lanes = F.census_lanes(fmt, fn)["tiny"]
        want = {"atan": (10, 136), "asin": (0, 140)}[fn]
        for rnd in (I.RNE, I.RTZ):
            out, marked = F.check_census_counts(frag(fn, "fp128", rnd),
                                                "tiny", lanes)
            assert out == []
            assert len(marked) == want[0 if rnd == I.RNE else 1]


def test_the_census_tables_hold_the_studys_numbers():
    assert F.TINY_COUNTS == {
        "fp64": {"atan": (6, 0), "asin": (0, 6), "atan2": (18, 0)},
        "fp128": {"atan": (10, 136), "asin": (0, 140), "atan2": (30, 408)},
        "fp256": {"atan": (10, 446), "asin": (0, 450), "atan2": (30, 1338)}}
    assert F.RATIO_COUNTS == {"fp64": 11, "fp128": 40, "fp256": 40}
    assert F.NEAR_COUNT == 258


# ---- every leg of every check fails alone on a doctored input ------------------------

def _evaluator_with(f, lane, mark=None, bits=None):
    """ml.evaluate with one lane's answer doctored: the mark set or cleared,
    or the bits changed."""
    def ev(g, x):
        b, fw = ml.evaluate(g, x)
        if x == lane:
            if mark is True:
                fw |= MARK
            if mark is False:
                fw &= ~MARK
            if bits is not None:
                b = bits
        return b, fw
    return ev


def test_family_fails_on_an_unmarked_lane_the_theory_demands():
    fmt = I.FP64
    f = frag("atan", "fp64", I.RNE)
    ents = F.entries(fmt, I.RNE, "atan")
    lane = F.centre_lane("atan", fmt, ("tiny", 3, 26))
    out, st = F.check_family(f, ents, evaluator=_evaluator_with(f, lane,
                                                                mark=False))
    assert out and names(out) == {"family"}
    assert "inside a window" in out[0] or "unmarked and wrong" in out[0]


def test_family_fails_on_an_unmarked_lane_that_is_wrong():
    fmt = I.FP64
    f = frag("atan", "fp64", I.RTZ)
    ents = F.entries(fmt, I.RTZ, "atan")
    # a lane the theory calls clear and the fragment answers: doctor its bits
    lane = F.negated("atan", fmt, F.centre_lane("atan", fmt,
                                                ("win", "pio2", "grid", 0)))
    ev = _evaluator_with(f, lane, mark=False, bits=1)
    out, st = F.check_family(f, ents, evaluator=ev)
    assert names(out) == {"family"} and st["wrong"] >= 1


def test_off_list_fails_on_a_mark_past_must_not():
    fmt = I.FP64
    f = frag("atan", "fp64", I.RNE)
    ents = F.entries(fmt, I.RNE, "atan")
    # a lane the theory calls clear (the neighbour 2W of a window), doctored
    # to be marked
    cen = ("win", "pio2", "mid", 0)
    far = [lane for lane, lab in F.neighbours(fmt, "atan", cen)
           if lab == "+2W"][0]
    assert F.classify(fmt, I.RNE, "atan", far) == "clear"
    out, st = F.check_family(f, ents, evaluator=_evaluator_with(
        f, far, mark=True))
    assert names(out) == {"off_list"} and "a mark off the list" in out[0]
    # check_off_list on its own, with results handed in
    lanes = [far]
    res = [(0, MARK)]
    out2, marks = F.check_off_list(f, lanes, res)
    assert names(out2) == {"off_list"} and marks == lanes
    # and a mark the theory predicts passes it
    lane = F.centre_lane("atan", fmt, ("tiny", 3, 26))
    out3, marks = F.check_off_list(f, [lane], [(0, MARK)])
    assert out3 == [] and marks == [lane]
    # a mark just past MUST_NOT but under 1.3 still fails: no second set of
    # thresholds at 1.3
    d_far = F.distance(fmt, I.RNE, "atan", far)
    assert d_far > F.thresholds(fmt, "atan")[1]


def test_off_list_is_not_fooled_by_the_tiny_quotient_range():
    fmt = I.FP64
    f = frag("atan2", "fp64", I.RNE)
    lane = (1, sf.one_bits(fmt))                  # minSub / 1: in the range
    out, marks = F.check_off_list(f, [lane], [(0, MARK)])
    assert out == [] and F.classify(fmt, I.RNE, "atan2", lane) == "mark"
    # the same mark on a lane outside it, with a clear d, fails
    lane = (sf.one_bits(fmt), sf.one_bits(fmt) + 5)
    assert F.classify(fmt, I.RNE, "atan2", lane) == "clear"
    out, _m = F.check_off_list(f, [lane], [(0, MARK)])
    assert names(out) == {"off_list"}


def test_a_listed_lane_the_theory_does_not_demand_fails_family():
    fmt = I.FP64
    f = frag("atan", "fp64", I.RTZ)
    ents = F.entries(fmt, I.RTZ, "atan") + [("tiny", 5, 26, 26)]
    out, st = F.check_family(f, ents)
    assert names(out) == {"family"} and "LISTED" in out[0]
    # the ratio threshold one too high lists a lane the theory does not
    f2 = frag("atan2", "fp64", I.RTZ)
    ents = [("ratio", "deep", 12)]
    out, st = F.check_family(f2, ents)
    assert names(out) == {"family"} and "the listed threshold" in out[0]


def test_a_claim_of_zero_the_theory_contradicts_fails_family(monkeypatch):
    fmt = I.FP64
    f = frag("acos", "fp64", I.RNE)
    ents = [("zero", "near1", 64)]
    out, st = F.check_family(f, ents)
    assert out == [] and st["lanes"] == 128 and st["mark"] == 0
    real = F.classify
    monkeypatch.setattr(F, "classify", lambda *a, **k: "mark"
                        if a[3] == F.one(fmt) - 3 else real(*a, **k))
    out, st = F.check_family(f, ents)
    assert names(out) == {"family"} and "claimed to mark nothing" in out[0]


def test_windows_fails_on_a_half_width_halved_and_on_doctored_lanes(monkeypatch):
    fmt = I.FP64
    f = frag("atan", "fp64", I.RTZ)
    cen = [("win", "pio2", "grid", 0)]
    out, n = F.check_windows(f, cen)
    assert out == [] and n == 8
    # a window's half-width halved
    real = F.half_width
    monkeypatch.setattr(F, "half_width", lambda *a, **k: real(*a, **k) / 2)
    out, n = F.check_windows(f, cen)
    assert names(out) == {"windows"} and "half-width" in out[0]
    monkeypatch.undo()
    # the window's inner edge not marked
    x0 = F.centre_lane("atan", fmt, cen[0])
    edges = F.window_edges(fmt, I.RTZ, "atan", cen[0])
    lane = x0 + edges[1][0]
    out, n = F.check_windows(f, cen, evaluator=_evaluator_with(
        f, lane, mark=False))
    assert names(out) == {"windows"} and "not marked" in out[0]
    # the outer edge marked
    lane = x0 + edges[1][1]
    out, n = F.check_windows(f, cen, evaluator=_evaluator_with(
        f, lane, mark=True))
    assert names(out) == {"windows"} and "outside the window and marked" in \
        out[0]
    # an unmarked lane wrong
    lane = x0 - edges[-1][1]
    out, n = F.check_windows(f, cen, evaluator=_evaluator_with(
        f, lane, mark=False, bits=1))
    assert names(out) == {"windows"} and "is wrong" in out[0]


def test_census_counts_fails_on_each_of_its_legs():
    fmt = I.FP64
    f = frag("atan", "fp64", I.RNE)
    lanes = F.census_lanes(fmt, "atan")["tiny"]
    marked_lane = F.tiny_lane("atan", fmt, 3, 26)
    ok, marked = F.check_census_counts(f, "tiny", lanes)
    assert ok == [] and len(marked) == 6
    # the count
    out, _m = F.check_census_counts(f, "tiny", lanes, want=7)
    assert names(out) == {"census_counts"} and "study's count" in out[0]
    # a lane the theory demands marked, not marked: also a wrong count
    out, _m = F.check_census_counts(f, "tiny", lanes,
                                    evaluator=_evaluator_with(
                                        f, marked_lane, mark=False))
    assert names(out) == {"census_counts"}
    assert any("demands marked" in o for o in out)
    # an unmarked lane wrong
    other = F.tiny_lane("atan", fmt, 1, 22)
    out, _m = F.check_census_counts(f, "tiny", lanes,
                                    evaluator=_evaluator_with(
                                        f, other, mark=False, bits=1))
    assert any("wrong unmarked" in o for o in out)
    # a mark the theory calls clear is a mark off the list
    out, _m = F.check_census_counts(f, "tiny", lanes, want=7,
                                    evaluator=_evaluator_with(
                                        f, other, mark=True))
    assert any(o.startswith("off_list") for o in out)


def test_pool_marks_fail_on_a_mark_the_theory_does_not_predict():
    out, n = F.check_pool_marks()
    assert out == [] and n == len(I.INV_POOL_MARKS) == 265
    fmt = I.FP64
    bad = tuple(I.INV_POOL_MARKS) + (
        ("atan2", "fp64", "rne", (sf.one_bits(fmt), sf.one_bits(fmt) + 5),
         "doctored"),)
    out, n = F.check_pool_marks(bad)
    assert names(out) == {"pool_marks"} and len(out) == 1
    # the pools' own check (M4G1's) still refuses a mark off its list
    assert I.pool_marks("atan2", "fp64", "rne")


# ---- the tool plants and the fragment plants: the matrix ------------------------------

# (plant, the checks it is red in, the checks it is green in): every row lists
# every check of F.CHECKS. The first four are faults of this tool (the list, the
# theory's width), the last three are M4G1's fragment plants, measured at fp64
# on atan (and the others where the plant acts).
PLANTED = [
    ("list_edited", ("family_list", "family"),
     ("off_list", "windows", "census_counts", "struct", "pool_marks")),
    ("centre_dropped", ("family_list",),
     ("family", "off_list", "windows", "census_counts", "struct",
      "pool_marks")),
    ("halfwidth_halved", ("windows",),
     ("family_list", "family", "off_list", "census_counts", "struct",
      "pool_marks")),
    ("ratio_off_by_one", ("family_list", "family"),
     ("off_list", "windows", "census_counts", "struct", "pool_marks")),
    ("mark_silenced", ("family", "windows", "census_counts"),
     ("family_list", "off_list", "struct", "pool_marks")),
    ("bound_loose", ("family", "windows", "census_counts"),
     ("family_list", "off_list", "struct", "pool_marks")),
    ("pio2_low", ("family", "windows", "census_counts"),
     ("family_list", "off_list", "struct", "pool_marks")),
]


def _check_row(row):
    plant, red, green = row
    assert set(red) | set(green) == set(CHECKS), (plant, set(CHECKS)
                                                  - set(red) - set(green))
    assert not set(red) & set(green), plant
    assert len(red) + len(green) == len(CHECKS), plant
    assert red, plant


def test_every_row_lists_every_check_and_a_bad_row_is_refused():
    assert [r[0] for r in PLANTED][:4] == list(F.TOOL_PLANTS)
    for row in PLANTED:
        _check_row(row)
    rest = tuple(c for c in CHECKS if c not in ("family", "windows"))
    for bad in (("p", ("family",), ("windows",)),
                ("p", ("family", "windows"), ("windows",) + rest),
                ("p", (), tuple(CHECKS))):
        with pytest.raises(AssertionError):
            _check_row(bad)
    _check_row(("p", ("family",), ("windows",) + rest))


def _red_checks(plant):
    """The checks a plant turns red, measured."""
    fmt = I.FP64
    red = set()
    if plant in F.TOOL_PLANTS:
        base = fresh()
        if plant == "list_edited":
            d = _doctored(lambda d: d["atan"]["fp64"]["rtz"].append(
                ("tiny", 5, 26, 26)))
            if F.check_family_list(d, base):
                red.add("family_list")
            ents = d["atan"]["fp64"]["rtz"]
            out, _st = F.check_family(frag("atan", "fp64", I.RTZ), ents)
        elif plant == "centre_dropped":
            d = _doctored(lambda d: d["atan"]["fp128"]["rtz"].remove(
                ("tiny", 3, 41, 55)))
            if F.check_family_list(d, base):
                red.add("family_list")
            ents = d["atan"]["fp128"]["rtz"]
            out, _st = F.check_family(frag("atan", "fp128", I.RTZ), ents)
        elif plant == "ratio_off_by_one":
            d = _doctored(lambda d: d["atan2"]["fp64"]["rtz"].__setitem__(
                d["atan2"]["fp64"]["rtz"].index(("ratio", "deep", 11)),
                ("ratio", "deep", 12)))
            if F.check_family_list(d, base):
                red.add("family_list")
            out, _st = F.check_family(frag("atan2", "fp64", I.RTZ),
                                      d["atan2"]["fp64"]["rtz"])
        else:                                      # halfwidth_halved
            real = F.half_width
            F.half_width = lambda *a, **k: real(*a, **k) / 2
            try:
                out, _n = F.check_windows(frag("atan", "fp64", I.RTZ),
                                          [("win", "pio2", "grid", 0)])
            finally:
                F.half_width = real
            return names(out)
        red |= names(out)
        return red
    # M4G1's fragment plants, on atan at fp64 (the plant acts there)
    for fn, rnd in (("atan", I.RNE), ("atan", I.RTZ)):
        f = frag(fn, "fp64", rnd, plant)
        ents = F.entries(fmt, rnd, fn)
        out, _st = F.check_family(f, ents)
        red |= names(out)
        out, _n = F.check_windows(f, F.expand(ents))
        red |= names(out)
        for fam, lanes in F.census_lanes(fmt, fn).items():
            out, _m = F.check_census_counts(f, fam, lanes)
            red |= names(out)
    return red


@pytest.mark.parametrize("row", PLANTED, ids=lambda r: r[0])
def test_each_plant_is_red_in_its_checks_and_green_in_the_others(row):
    plant, red, green = row
    got = _red_checks(plant)
    assert got == set(red), (plant, got)
    assert not got & set(green)


def test_every_check_is_red_somewhere():
    # off_list, struct and pool_marks are red on doctored inputs (above): no
    # plant of the fragment adds a mark the theory forbids, none edits STRUCT
    # or the pools' list. The rest are red under a plant of the matrix.
    red = {c for row in PLANTED for c in row[1]}
    assert red == set(CHECKS) - {"off_list", "struct", "pool_marks"}


# ---- the rate law and the crowding split -------------------------------------------------

def test_the_crowding_constants_are_exact_rationals_held_to_the_study():
    assert R.crowd_distances().keys() == R.CROWD_DISTANCES.keys()
    for fmt, per in R.crowd_distances().items():
        for name, (g, m) in per.items():
            cg, cm = R.CROWD_DISTANCES[fmt][name]
            assert f"{g:.4g}" == f"{cg:.4g}" and f"{m:.4g}" == f"{cm:.4g}"
            sg, sm = R.STUDY_DISTANCES[fmt][name]
            assert abs(g / sg - 1) < 0.03 and abs(m / sm - 1) < 0.03, \
                (fmt, name, g, sg, m, sm)
    # the least distance in inflated bounds is fp256's midpoint beside pi/2:
    # 4.0 (the open cell's constant)
    least = min(R.inflated_bounds(I.BY_NAME[f], d)
                for f, per in R.CROWD_DISTANCES.items()
                for pair in per.values() for d in pair)
    assert 4.0 < least < 4.02


def test_the_constants_are_pi_over_four_times_one_to_four():
    cs = R.crowd_constants()
    import mpmath
    with mpmath.workprec(600):
        for k, c in enumerate(cs, 1):
            assert abs(F._mp(c) - mpmath.pi * k / 4) < mpmath.mpf(2) ** -590


def test_crowded_lanes_are_those_within_an_ulp_of_a_constant():
    fmt = I.FP64
    huge = ml._enc(fmt, F.Fraction(2 ** 70))
    assert R.crowded(fmt, "atan", huge)             # atan(2^70) is pi/2
    assert not R.crowded(fmt, "atan", ml._enc(fmt, F.Fraction(3, 10)))
    assert R.crowded(fmt, "acos", ml._enc(fmt, F.Fraction(1, 2 ** 60)))


def test_the_rate_law_holds_on_the_rest_and_the_split_is_stated():
    fmt = I.FP64
    out, st = R.check_rate(fmt, I.RNE, "acos", "random", 600, 3)
    assert out == [], out
    assert st["rest_n"] + st["crowd_n"] == st["distinct"]
    assert st["crowd_n"] > 0 and st["rest_n"] > 0
    assert st["crowd_marked"] <= st["crowd_expected"] + 5
    assert st["wrong"] == 0
    # the edge region repeats its arguments and says so
    out, st = R.check_rate(fmt, I.RTZ, "atan", "edge", 600, 3)
    assert out == [], out
    assert st["distinct"] < st["n"] and st["inflation"] > 1.0
    assert st["crowd_n"] == 0                     # atan's edge has none


def test_the_rate_check_fails_on_each_of_its_legs():
    fmt = I.FP64
    # the count: a build whose bound is 2^40 too small marks nothing
    out, st = R.check_rate(fmt, I.RNE, "asin", "random", 600, 3,
                           plant="bound_loose")
    assert out and names(out) == {"rate"} and st["marked"] == 0
    # and mark_silenced
    out, _st = R.check_rate(fmt, I.RTZ, "asin", "random", 600, 3,
                            plant="mark_silenced")
    assert out and names(out) == {"rate"}
    # the tool plant: the expectation taken from the build under test cannot
    # see the faulted bound
    out, _st = R.check_rate(fmt, I.RNE, "asin", "random", 600, 3,
                            plant="bound_loose",
                            tool_plant="expectation_follows_build")
    assert out == []
    with pytest.raises(ValueError, match="unknown tool plant"):
        R.check_rate(fmt, I.RNE, "asin", "random", 60, 3, tool_plant="x")
    # an unmarked lane wrong
    calls = []

    def ev(g, x):
        b, fw = ml.evaluate(g, x)
        if not calls:
            calls.append(x)
            return b ^ 1, fw & ~MARK & 0x1F
        return b, fw
    out, st = R.check_rate(fmt, I.RNE, "asin", "random", 60, 3, evaluator=ev)
    assert st["wrong"] == 1 and any("unmarked lanes are wrong" in o
                                    for o in out)


def test_crowded_lanes_that_mark_more_than_the_law_allows_are_a_finding():
    fmt = I.FP64
    smp = R.rate_sample(fmt, "acos", "random", 600, 3)
    crowd = set(smp.crowd)
    assert crowd

    def ev(g, x):
        b, fw = ml.evaluate(g, x)
        return (b, fw | MARK) if x in crowd else (b, fw)
    out, st = R.check_rate(fmt, I.RNE, "acos", "random", 600, 3,
                           evaluator=ev)
    assert any("crowded" in o for o in out), out


def test_the_rate_sample_matches_the_models_counts_at_seed_3():
    # the study's 3.4 first table at fp64, 2,000 lanes, seed 3, rne / rtz (the
    # model's rate.py run apart): atan 5 / 7, asin 35 / 30, acos 41 / 36,
    # atan2 23 / 23, each lane's own prediction 49.1, 47.1, 49.0, 40.3
    fmt = I.FP64
    want = {"atan": (5, 7, 49.1), "asin": (35, 30, 47.1),
            "acos": (41, 36, 49.0), "atan2": (23, 23, 40.3)}
    for fn, (a, b, e) in want.items():
        for rnd, w in ((I.RNE, a), (I.RTZ, b)):
            out, st = R.check_rate(fmt, rnd, fn, "random", 2000, 3,
                                   sigmas=6)
            assert st["marked"] == w, (fn, rnd, st["marked"])
            assert abs(st["all_expected"] - e) < 0.06, (fn, st)


# ---- the box's commands -------------------------------------------------------------------

def _run(argv, tmp_path=None):
    RUNS.FINDINGS.clear()
    rc = RUNS.main(argv)
    return rc, list(RUNS.FINDINGS)


@pytest.mark.parametrize("cmd,extra", [
    ("inv-budget", ["--fn", "atan2", "--regions", "edge,small"]),
    ("inv-rate", ["--fn", "acos", "--attrs", "rne"]),
    ("inv-family", ["--fn", "atan", "--attrs", "rtz"]),
])
def test_each_command_runs_at_quick_and_out_refuses_an_existing_path(
        cmd, extra, tmp_path, capsys):
    out = tmp_path / f"{cmd}.txt"
    rc, found = _run([cmd, "--quick"] + extra + ["--out", str(out)])
    assert rc == 0 and found == []
    text = out.read_text(encoding="utf-8")
    assert text.count(cmd) >= 2 and text.rstrip().endswith("RESULT: ok")
    # a path that exists is refused, before any work
    with pytest.raises(SystemExit, match="exists"):
        _run([cmd, "--quick"] + extra + ["--out", str(out)])
    RUNS.OUT = None


def test_inv_family_check_holds_the_list_to_a_fresh_generation(capsys):
    rc, found = _run(["inv-family", "--check"])
    assert rc == 0 and found == []
    assert "differ from the theory's" in capsys.readouterr().out


def test_the_commands_name_a_bad_function_format_or_region():
    for argv in (["inv-budget", "--fn", "exp"],
                 ["inv-budget", "--formats", "fp32"],
                 ["inv-budget", "--fn", "atan", "--regions", "tinyn"],
                 ["inv-rate", "--regions", "diag"]):
        with pytest.raises(SystemExit):
            _run(argv)
    RUNS.OUT = None
