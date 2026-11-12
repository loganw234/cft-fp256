# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The revision-8 set's radian case, held without a card, a library or a
compile (parcel M2A, M2's build, wave 4; programs/acceptance.py, whose
docstring is the definition; the six routine entries of parcel MA are
test_acceptance_marks.py's):

  set       the pendulum and the attitude, each at fp64 and fp256, follow the
            six routine entries, on the quad the rule puts them on
  centres   each structured lane's centre is in python/tests/
            mathlib_trig_family.py's TRIG_FAMILY at the entry's OWN attribute
            (read from its source: the pendulum's rne, the attitude's rdn),
            the trig theory (classify) demands it marked, centre_bits() builds
            its value, and the off-centre control's argument is clear by the
            theory - which the six's off_centre step is not, for a trig
            centre (a few-bit step leaves the square on the result's grid)
  range     the fp256 entries declare the recipe's overflow lane (lane 31) an
            expected mark; its argument is past the stated range by
            mathlib_trig_harness.past_range, at fp256 and not at fp64; the
            mark check names it undeclared, and names it missing
  empty     the pendulum at fp64 has an empty recipe, accepted by name with
            its reason; an empty recipe for any other entry is refused, and so
            is a reason beside structured lanes
  record    the committed record holds each of these by name

Needs mpmath where it calls the theory (classify); the rest does not.
"""

import json
import pathlib
import re
import sys
from fractions import Fraction

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "tests"))
sys.path.insert(0, str(ROOT / "programs"))

import acceptance as A  # noqa: E402
from cft_golden import FORMATS, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

NAMES = ("pendulum-rk4-tangent-fp64", "pendulum-rk4-tangent-fp256",
         "attitude-rk4-tangent-fp64", "attitude-rk4-tangent-fp256")
RANGED = ("pendulum-rk4-tangent-fp256", "attitude-rk4-tangent-fp256")
LANES = tuple(n for n in NAMES if A.STRUCTURED[n])
RND = {"rne": sf.RND_RNE, "rtz": sf.RND_RTZ, "rdn": sf.RND_RDN,
       "rup": sf.RND_RUP, "rmm": sf.RND_RMM}


def fmt_of(name):
    return FORMATS["fp256" if name.endswith("fp256") else "fp64"]


def attribute_of(name):
    """The entry's rounding attribute, from its own source."""
    text = (ROOT / "programs" / "systems" / f"{name}.cftl").read_text()
    return re.search(r"^round\s+(\w+)", text, re.M).group(1)


def value(fmt, bits):
    u = sf.unpack(fmt, bits)
    return (-1) ** u.sign * u.m * Fraction(2) ** u.e


def mpmath_modules():
    pytest.importorskip("mpmath")
    import mathlib_trig_family as TF
    return TF


# ---- the set ----------------------------------------------------------------

def test_the_four_follow_the_six_on_the_quad_by_the_rule():
    names = [n for n, _s, _t in A.REV8_ROUTINES]
    assert len(names) == 12 and tuple(names[6:10]) == NAMES
    by = {e["name"]: e for e in A.entries("rev8")}
    for n in NAMES:
        e = by[n]
        image = (ROOT / e["image"]).read_bytes()
        assert A.rule_target(image) == e["target"] == "u50-rev8-quad"
        assert A.rule_problems(e["target"], image) == []


def test_the_attributes_are_the_sources():
    assert {n: attribute_of(n) for n in NAMES} == {
        "pendulum-rk4-tangent-fp64": "rne",
        "pendulum-rk4-tangent-fp256": "rne",
        "attitude-rk4-tangent-fp64": "rdn",
        "attitude-rk4-tangent-fp256": "rdn"}


def test_each_function_is_one_the_images_manifest_holds():
    for n in LANES:
        m = json.loads((ROOT / "programs" / "systems" / "compiled-tangent"
                        / f"{n}.manifest.json").read_bytes())
        held = set(m["routines"]["calls"])
        for fn, comp, _c in A.STRUCTURED[n]:
            assert fn in A.TRIG_FUNCTIONS and fn in held, (n, fn, held)
            assert comp in (0, 1)


def test_one_structured_lane_a_tile_for_the_three_with_lanes():
    assert LANES == NAMES[1:]
    for n in LANES:
        e = {x["name"]: x for x in A.entries("rev8")}[n]
        rec = A.prepare(e)[3]
        blk = A.BLOCK[fmt_of(n).name]
        assert [s["lane"] for s in rec["structured"]] == \
            [t * blk + A.STRUCTURED_LANE for t in range(4)]
        assert all(s["segment"] == 0 for s in rec["structured"])


# ---- the centres ------------------------------------------------------------

def test_the_centres_are_trig_family_at_the_entrys_attribute_and_mark():
    TF = mpmath_modules()
    for n in LANES:
        fmt, rnd = fmt_of(n), attribute_of(n)
        for fn, _comp, centre in A.STRUCTURED[n]:
            listed = TF.expand(TF.TRIG_FAMILY[fn][fmt.name][rnd])
            assert tuple(centre) in listed, (n, fn, centre, rnd)
            bits = A.centre_bits(fmt, centre)
            c, e = centre
            assert value(fmt, bits) == Fraction(c, 2 ** e)
            assert TF.classify(fmt, RND[rnd], bits, None, fn) == "mark", \
                (n, fn, centre)


def test_a_centre_at_the_wrong_attribute_is_not_listed():
    """The attitude's centres held at rne, as a plant: none is in
    TRIG_FAMILY at rne (a cos centre at fp64 has none under rne, and tan's
    fp256 rne list is another list), so the check above is red for it."""
    TF = mpmath_modules()
    for n in ("attitude-rk4-tangent-fp64", "attitude-rk4-tangent-fp256"):
        fmt = fmt_of(n)
        wrong = [c for fn, _comp, c in A.STRUCTURED[n]
                 if tuple(c) not in TF.expand(TF.TRIG_FAMILY[fn][fmt.name]
                                              ["rne"])]
        assert wrong, n


def test_the_off_centre_argument_is_clear_by_the_theory():
    TF = mpmath_modules()
    for n in LANES:
        fmt, rnd = fmt_of(n), attribute_of(n)
        for fn, _comp, centre in A.STRUCTURED[n]:
            bits = A.off_centre_dense(fmt, A.centre_bits(fmt, centre))
            assert TF.classify(fmt, RND[rnd], bits, None, fn) == "clear", \
                (n, fn, centre)


def test_the_six_off_centre_step_alone_is_not_clear_for_a_trig_centre():
    """Why off_centre_dense exists: cos at 2^-70 (1 + 2^-20), fp256, rdn, is
    still demanded marked (measured 2026-11-04: the attitude's lane 3 kept
    byte 0x90)."""
    TF = mpmath_modules()
    fmt = FORMATS["fp256"]
    bits = A.off_centre(fmt, A.centre_bits(fmt, (1, 70)))
    assert TF.classify(fmt, sf.RND_RDN, bits, None, "cos") == "mark"


# ---- the range lane ---------------------------------------------------------

def committed():
    doc = json.loads((ROOT / "programs" / "acceptance-rev8.json")
                     .read_bytes())
    return {e["name"]: e for e in doc["entries"]}


def test_the_range_lane_is_past_the_range_at_fp256_and_not_at_fp64():
    import mathlib_trig_harness as H
    for n in NAMES:
        fmt = fmt_of(n)
        e = {x["name"]: x for x in A.entries("rev8")}[n]
        rec = A.prepare(e)[3]
        lane = 2 * A.BLOCK[fmt.name] - 1          # tile 1's last lane
        huge = sf.round_pack(fmt, 0, 1, fmt.emax // 2 + 10)[0]
        assert H.past_range(fmt, huge) == (n in RANGED)
        if n in RANGED:
            r = rec["range"][0]
            assert r["lane"] == lane == 31 and r["tile"] == 1
            assert int(r["argument"], 16) == huge
            assert lane in rec["special"] and lane in rec["spot"]
            assert H.past_range(fmt, int(r["argument"], 16))
        else:
            assert "range" not in rec


def test_the_committed_record_declares_the_range_lane_by_name():
    rec = committed()
    for n in NAMES:
        if n in RANGED:
            r = rec[n]["range"]
            assert len(r) == 1 and r[0]["lane"] == 31
            assert r[0]["segments"] == list(A.RANGE_LANES[n])
            for k in r[0]["segments"]:
                assert [31, 0x90] in rec[n]["marked"][k]
        else:
            assert "range" not in rec[n]
    for n, _s, _t in A.REV8_ROUTINES[:6]:
        assert "range" not in rec[n]


def synthetic(ranged_segments=(0, 1, 2, 3)):
    """A block the fp256 recipe describes: the structured lanes in segment 0,
    lane 31 in `ranged_segments`."""
    st = [{"lane": 3 + 16 * t, "tile": t, "segment": 0, "function": "sin",
           "component": 0, "centre": [21, 116], "argument": "0x0"}
          for t in range(4)]
    rng = [{"lane": 31, "tile": 1, "segments": list(ranged_segments),
            "function": "range", "components": [0, 1], "argument": "0x1"}]
    bl = [bytearray([0x10] * 64) for _ in range(4)]
    for s in st:
        bl[0][s["lane"]] = 0x90
    for k in ranged_segments:
        bl[k][31] = 0x90
    status = [0x40 if any(b & 0x80 for b in blk) else 0 for blk in bl]
    return st, rng, [bytes(b) for b in bl], status


def test_the_mark_check_is_green_with_the_range_lane_declared():
    st, rng, bl, status = synthetic()
    assert A.mark_problems(st, bl, status, rng) == []


def test_plant_the_range_lane_undeclared_is_named_by_lane():
    st, _rng, bl, status = synthetic()
    probs = A.mark_problems(st, bl, status)
    assert any("lanes [31] carry bit 7" in p for p in probs), probs
    assert any(p.startswith("segment 1:") for p in probs)


def test_plant_an_expected_range_mark_missing():
    st, rng, bl, status = synthetic()
    cut = [bytearray(b) for b in bl]
    cut[2][31] = 0x10
    probs = A.mark_problems(st, [bytes(b) for b in cut], status, rng)
    assert any("range lane 31" in p and "segment 2" in p
               and "without bit 7" in p for p in probs), probs
    # and STATUS[6] cleared in segment 2, where only the range lane marks
    cs = list(status)
    cs[2] = 0
    probs = A.mark_problems(st, bl, cs, rng)
    assert any("segment 2's STATUS" in p and "lacks STATUS[6]" in p
               for p in probs), probs


def test_plant_a_range_lane_that_marks_in_a_segment_not_declared():
    st, rng, bl, status = synthetic(ranged_segments=(0, 1, 2))
    # the block marks in segment 3 as well
    bl = [bytearray(b) for b in bl]
    bl[3][31] = 0x90
    probs = A.mark_problems(st, [bytes(b) for b in bl], status, rng)
    assert any("segment 3: lanes [31] carry bit 7" in p for p in probs)


# ---- the empty recipe -------------------------------------------------------

def test_the_pendulum_at_fp64_has_an_empty_recipe_with_its_reason():
    TF = mpmath_modules()
    n = "pendulum-rk4-tangent-fp64"
    assert A.STRUCTURED[n] == ()
    why = A.NO_STRUCTURED[n]
    assert "fp64" in why and "rne" in why
    # the reason is true of the committed lists: no sin or cos centre at fp64
    # under rne
    for fn in ("sin", "cos"):
        assert TF.expand(TF.TRIG_FAMILY[fn]["fp64"]["rne"]) == []
    e = {x["name"]: x for x in A.entries("rev8")}[n]
    assert e["structured"] == () and e["no_structured"] == why
    rec = A.prepare(e)[3]
    assert rec["structured"] == [] and rec["no_structured"] == why
    assert "range" not in rec


def test_structured_lanes_accepts_an_empty_recipe_only_by_name():
    n = "pendulum-rk4-tangent-fp64"
    e = {x["name"]: x for x in A.entries("rev8")}[n]
    fmt = FORMATS["fp64"]
    block = [0] * (256 * 4)
    assert A.structured_lanes(e, fmt, block, 4, 4) == []
    assert block == [0] * 1024              # nothing set
    with pytest.raises(ValueError, match="no reason"):
        A.structured_lanes(dict(e, no_structured=None), fmt, block, 4, 4)
    other = {x["name"]: x for x in A.entries("rev8")}[
        "lotkavolterra-rk4-tangent-fp64"]
    with pytest.raises(ValueError, match="no reason"):
        A.structured_lanes(dict(other, structured=()), fmt, block, 4, 4)
    with pytest.raises(ValueError, match="for having none"):
        A.structured_lanes(dict(other, no_structured="x"), fmt, block, 4, 4)


def test_the_committed_record_holds_the_empty_recipe_by_name():
    rec = committed()["pendulum-rk4-tangent-fp64"]
    assert rec["structured"] == []
    assert rec["no_structured"] == A.NO_STRUCTURED[rec["name"]]
    assert rec["marked"] == [[], [], [], []]
    assert rec["status"] == [0, 0, 0, 0]


def test_the_committed_records_marks_and_status_for_the_four():
    rec = committed()
    for n in LANES:
        e = rec[n]
        want = [[s["lane"], 0x90] for s in e["structured"]]
        if n in RANGED:
            assert e["status"] == [seq.STATUS_MARKED] * 4
            assert e["marked"][0] == sorted(want + [[31, 0x90]])
            assert all(e["marked"][k] == [[31, 0x90]] for k in (1, 2, 3))
        else:
            assert e["status"] == [seq.STATUS_MARKED, 0, 0, 0]
            assert e["marked"] == [want, [], [], []]
