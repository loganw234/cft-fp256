# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The revision-8 set's inverse-trigonometric case, held without a card, a
library or a compile (parcel M4A, M4's build, wave 5; programs/acceptance.py,
whose docstring is the definition). It is NOT test_acceptance_trig.py's
"four" (the pendulum's and the attitude's entries): these are the two entries
of the phase follower, the committed reference whose step holds atan2 of two
state components and atan, asin and acos each of one.

  set       the follower's two entries are the last two of REV8_ROUTINES,
            fp64 then fp256, on the quad the rule puts them on; the box the
            set draws their lanes in is programs/tangent_check.py's MATH_BOX
  attribute the entries are compiled round rdn, from their own source; the
            study's own case, atan(3 2^-26) under rne at fp64, is a centre of
            the rne list and of NO rdn list, and is not among the recipe's
            centres
  recipe    four structured lanes a tile; the pair for atan2 is (y's
            component, x's component) with (y's centre, x's centre), y
            first; the refusals by name; the literal window centres equal
            python/tests/mathlib_inv_family.py's own
  centres   (mpmath) each centre is a centre of INV_FAMILY at rdn, classify
            says "mark" for the call the tile is built for, and the answer
            for every other call that reads the lane's components is pinned;
            an off-centre control argument is "clear"
  record    the committed record's marks by segment, STATUS and flags for
            the two entries, and that no lane is declared a range lane
  no mpmath the entries are built in a process where mpmath cannot import

Needs mpmath where it calls the theory (classify, INV_FAMILY); the rest does
not.
"""

import json
import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "tests"))
sys.path.insert(0, str(ROOT / "programs"))

import acceptance as A  # noqa: E402
from cft_golden import FORMATS, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

NAMES = ("phasefollower-rk4-tangent-fp64", "phasefollower-rk4-tangent-fp256")
SYSTEMS = ROOT / "programs" / "systems"
# the follower's state: c, s, phi, q, v; its calls read atan2(s, c),
# asin(q * 0.5), atan(q) and acos(v * 0.5)
C, S, PHI, Q, V = 0, 1, 2, 3, 4


def fmt_of(name):
    return FORMATS["fp256" if name.endswith("fp256") else "fp64"]


def attribute_of(name):
    """The entry's rounding attribute, from its own source."""
    text = (SYSTEMS / f"{name}.cftl").read_text()
    return re.search(r"^round\s+(\w+)", text, re.M).group(1)


def entry(name):
    return {e["name"]: e for e in A.entries("rev8")}[name]


def half(fmt, bits):
    """bits * 0.5, exact for a normal number: one exponent step down."""
    return bits - (1 << fmt.man_w)


def state_of(name, tile):
    """The recipe's components of tile `tile`: {component: bits}."""
    fmt = fmt_of(name)
    fn, comp, centre = A.STRUCTURED[name][tile]
    if isinstance(comp, tuple):
        return {c: A.centre_bits(fmt, ce) for c, ce in zip(comp, centre)}
    return {comp: A.centre_bits(fmt, centre)}


def calls_of(name, tile):
    """{call: (function, lane)}: every call of the follower's step that
    reads a component the tile's recipe sets, as the theory takes the lane."""
    fmt = fmt_of(name)
    st = state_of(name, tile)
    out = {}
    if C in st or S in st:
        out["atan2(s, c)"] = ("atan2", (st[S], st[C]))
    if Q in st:
        out["asin(q * 0.5)"] = ("asin", half(fmt, st[Q]))
        out["atan(q)"] = ("atan", st[Q])
    if V in st:
        out["acos(v * 0.5)"] = ("acos", half(fmt, st[V]))
    return out


# classify's answer at rdn, for every call that reads the lane's components,
# per tile (MEASURED 2026-11-11 by this file's own test); the tile's own call
# is first and "mark". "gated" is what the theory calls an argument the
# routine's test never decides (asin outside [-1, 1])
CALLS = {
    "phasefollower-rk4-tangent-fp64": (
        {"atan2(s, c)": "mark"},
        {"asin(q * 0.5)": "mark", "atan(q)": "clear"},
        {"acos(v * 0.5)": "mark"},
        {"asin(q * 0.5)": "gated", "atan(q)": "mark"}),
    "phasefollower-rk4-tangent-fp256": (
        {"atan2(s, c)": "mark"},
        {"asin(q * 0.5)": "mark", "atan(q)": "mark"},
        {"asin(q * 0.5)": "mark", "atan(q)": "clear"},
        {"acos(v * 0.5)": "mark"})}
OWN = {"phasefollower-rk4-tangent-fp64": ("atan2(s, c)", "asin(q * 0.5)",
                                          "acos(v * 0.5)", "atan(q)"),
       "phasefollower-rk4-tangent-fp256": ("atan2(s, c)", "atan(q)",
                                           "asin(q * 0.5)", "acos(v * 0.5)")}


def family():
    pytest.importorskip("mpmath")
    import mathlib_inv_family as IF
    return IF


# ---- the set ----------------------------------------------------------------

def test_the_follower_entries_are_the_last_two_fp64_then_fp256_on_the_quad():
    names = [n for n, _s, _t in A.REV8_ROUTINES]
    assert len(names) == 12 and tuple(names[10:]) == NAMES
    by = {e["name"]: e for e in A.entries("rev8")}
    for n in NAMES:
        e = by[n]
        assert e["system"] == "phasefollower-rk4"
        image = (ROOT / e["image"]).read_bytes()
        assert A.rule_target(image) == e["target"] == "u50-rev8-quad"
        assert A.rule_problems(e["target"], image) == []


def test_the_follower_images_stream_past_a_tiles_store():
    """7,997 and 8,605 instructions (their manifests'), against the 4,096 a
    revision-8 tile holds: the claim of the docstring, read from the images."""
    from cft_golden import asm
    for n, want in zip(NAMES, (7997, 8605)):
        m = json.loads((SYSTEMS / "compiled-tangent"
                        / f"{n}.manifest.json").read_bytes())
        img = asm.Image.from_bytes((ROOT / entry(n)["image"]).read_bytes())
        assert m["uses"]["instructions"] == len(img.insns) == want > 4096


def test_the_follower_box_is_the_tangent_checks_math_box():
    import tangent_check as TC
    assert A.BOX["phasefollower-rk4"] == TC.MATH_BOX["phasefollower-rk4"]


def test_the_attribute_is_rdn_from_the_source():
    assert {n: attribute_of(n) for n in NAMES} == {n: "rdn" for n in NAMES}


def test_the_manifest_holds_the_four_functions_and_each_tile_one_of_them():
    for n in NAMES:
        m = json.loads((SYSTEMS / "compiled-tangent"
                        / f"{n}.manifest.json").read_bytes())
        calls = set(m["routines"]["calls"])
        assert {"atan", "asin", "acos", "atan2"} <= calls
        assert A.held_functions(entry(n)) == calls - {"div", "sqrt"}
        assert [fn for fn, _c, _x in A.STRUCTURED[n]] == \
            [x.split("(")[0] for x in OWN[n]]


# ---- the recipe -------------------------------------------------------------

def test_the_pair_is_y_then_x_and_sets_s_and_c():
    for n in NAMES:
        fn, comp, centre = A.STRUCTURED[n][0]
        assert fn == "atan2" and comp == (S, C)
        assert len(centre) == 2


def test_the_pair_builds_s_from_the_first_centre_and_c_from_the_second():
    n = NAMES[0]
    fmt = fmt_of(n)
    e = entry(n)
    slots = 10
    block = [0] * (256 * slots)
    out = A.structured_lanes(e, fmt, block, slots, 4)
    d = out[0]
    assert d["components"] == [S, C] and d["function"] == "atan2"
    assert "component" not in d and "centre" not in d
    lane = d["lane"]
    assert block[lane * slots + S] == A.centre_bits(fmt, (1, 63))
    assert block[lane * slots + C] == sf.one_bits(fmt) + 11
    assert d["arguments"] == ["0x3c00000000000000", "0x3ff000000000000b"]
    # the single-component descriptor keeps its five keys
    assert sorted(out[1]) == ["argument", "centre", "component",
                              "function", "lane", "segment", "tile"]


def test_the_pairs_refusals_are_by_name():
    n = NAMES[0]
    fmt = fmt_of(n)

    def run(item):
        e = dict(entry(n), structured=(item,) + A.STRUCTURED[n][1:])
        A.structured_lanes(e, fmt, [0] * 4096, 10, 4)
    with pytest.raises(ValueError, match="names component 1 twice"):
        run(("atan2", (1, 1), ((1, 63), ("u", 11))))
    with pytest.raises(ValueError, match="a pair of components for asin"):
        run(("asin", (1, 0), ((1, 63), ("u", 11))))
    with pytest.raises(ValueError, match="atan2 reads two operands"):
        run(("atan2", 1, (1, 63)))
    with pytest.raises(ValueError, match="two components and two centres"):
        run(("atan2", (1, 0), ((1, 63),)))
    with pytest.raises(ValueError, match="not one the image calls"):
        run(("sin", 3, (3, 24)))
    with pytest.raises(ValueError, match="is not a centre"):
        run(("atan2", (1, 0), ((1, 63), ("n", 11))))
    with pytest.raises(ValueError, match="not a fp64 encoding"):
        run(("atan2", (1, 0), ((1, 63), ("bits", "0x3ff0"))))


def test_the_other_entries_keep_their_single_component_descriptors():
    """The record's descriptor of a single lane is what it was: the six's
    and the radian four's entries hold their five keys and no pair's."""
    doc = json.loads((ROOT / "programs" / "acceptance-rev8.json").read_bytes())
    for r in doc["entries"]:
        if r["name"] in NAMES or not r.get("structured"):
            continue
        for s in r["structured"]:
            assert sorted(s) == ["argument", "centre", "component",
                                 "function", "lane", "segment", "tile"]


def test_one_structured_lane_a_tile_and_the_rest_of_the_lane_is_the_recipes():
    for n in NAMES:
        fmt = fmt_of(n)
        blk = A.BLOCK[fmt.name]
        rec = A.prepare(entry(n))[3]
        assert [s["lane"] for s in rec["structured"]] == \
            [t * blk + A.STRUCTURED_LANE for t in range(4)]
        assert not {s["lane"] for s in rec["structured"]} & \
            set(rec["special"])
        want = (["atan2", "asin", "acos", "atan"] if n.endswith("64")
                else ["atan2", "atan", "asin", "acos"])
        assert [s["function"] for s in rec["structured"]] == want


def test_the_entries_build_where_mpmath_cannot_import():
    """The acceptance run needs no mpmath: the follower's lanes, window
    centres included, are built by softfloat alone."""
    code = (
        "import sys; sys.modules['mpmath'] = None\n"
        f"sys.path[:0] = [{str(ROOT / 'python')!r}, "
        f"{str(ROOT / 'programs')!r}]\n"
        "import acceptance as A\n"
        f"for e in A.entries('rev8'):\n"
        f"    if e['name'] in {NAMES!r}:\n"
        "        rec = A.prepare(e)[3]\n"
        "        assert len(rec['structured']) == 4, e['name']\n"
        "print('built')\n")
    r = subprocess.run([sys.executable, "-B", "-I", "-c", code],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0 and r.stdout.strip() == "built", r.stderr[-400:]


# ---- the centres ------------------------------------------------------------

def test_each_tiles_own_centre_is_in_inv_family_at_rdn_and_marks():
    IF = family()
    for n in NAMES:
        fmt = fmt_of(n)
        for t, (fn, comp, centre) in enumerate(A.STRUCTURED[n]):
            own_fn, lane = calls_of(n, t)[OWN[n][t]]
            assert own_fn == fn
            ents = IF.entries(fmt, sf.RND_RDN, fn)
            listed = IF.centres(fmt, sf.RND_RDN, fn)
            if fn == "atan2" and n.endswith("64"):
                # ("ratio", "deep", 11): atan2(2^-63, 1 + j ulp), j = 1 to
                # 11; the recipe takes the largest j
                assert ("ratio", "deep", 11) in ents
                assert lane == IF.ratio_lane(fmt, -(fmt.prec + 10), 11)
            elif fn == "atan2":
                assert ("tiny", 3, 72) in listed
                assert lane == IF.tiny_lane("atan2", fmt, 3, 72)
            elif centre[0] == "bits":
                cen = ("win", "pio2", "grid", 0)
                assert cen in listed
                assert lane == IF.window_centre(fmt, fn, *cen[1:])
            else:
                assert any(IF.tiny_argument(fmt, c, e) == lane
                           for (k, c, e) in listed if k == "tiny"),                     (n, fn, centre)


def test_classify_says_mark_for_the_tile_and_the_others_are_pinned():
    IF = family()
    for n in NAMES:
        fmt = fmt_of(n)
        got = []
        for t in range(4):
            got.append({k: IF.classify(fmt, sf.RND_RDN, fn, lane)
                        for k, (fn, lane) in calls_of(n, t).items()})
        assert got == list(CALLS[n]), n
        for t in range(4):
            assert got[t][OWN[n][t]] == "mark"


def test_the_window_literals_are_the_familys_own():
    IF = family()
    fmt = FORMATS["fp64"]
    assert A.STRUCTURED[NAMES[0]][2][2] == \
        ("bits", f"{IF.window_centre(fmt, 'acos', 'pio2', 'grid', 0) + (1 << 52):#018x}")
    assert A.STRUCTURED[NAMES[0]][3][2] == \
        ("bits", f"{IF.window_centre(fmt, 'atan', 'pio2', 'grid', 0):#018x}")
    fmt = FORMATS["fp256"]
    assert A.STRUCTURED[NAMES[1]][3][2] == \
        ("bits", f"{IF.window_centre(fmt, 'acos', 'pio2', 'grid', 0) + (1 << 236):#066x}")


def test_the_off_centre_argument_is_clear_by_the_theory():
    """The control's lane (inv_controls): the tile's first component moved by
    off_centre_dense. Its own call must be "clear" by the theory, not merely
    unmarked on seq.py. The pair's first component is y's (s)."""
    IF = family()
    for n in NAMES:
        fmt = fmt_of(n)
        for t, (fn, comp, _c) in enumerate(A.STRUCTURED[n]):
            st = state_of(n, t)
            first = comp[0] if isinstance(comp, tuple) else comp
            st[first] = A.off_centre_dense(fmt, st[first])
            if fn == "atan2":
                lane = (st[S], st[C])
            elif fn == "asin":
                lane = half(fmt, st[Q])
            elif fn == "acos":
                lane = half(fmt, st[V])
            else:
                lane = st[Q]
            assert IF.classify(fmt, sf.RND_RDN, fn, lane) == "clear", \
                (n, t, fn)


def test_the_study_case_under_rne_is_not_among_the_followers_centres():
    """atan(3 2^-26) under rne at fp64 is a centre of INV_FAMILY at rne and
    of no rdn list; the follower is compiled rdn, and no tile's atan argument
    is that one."""
    IF = family()
    f64 = FORMATS["fp64"]
    case = ("tiny", 3, 26)
    assert case in IF.centres(f64, sf.RND_RNE, "atan")
    assert case not in IF.centres(f64, sf.RND_RDN, "atan")
    arg = IF.tiny_argument(f64, 3, 26)
    n = NAMES[0]
    for t in range(4):
        for k, (fn, lane) in calls_of(n, t).items():
            assert not (fn == "atan" and lane == arg), (t, k)
    # the entries' own attribute is rdn, and acceptance.py says by name
    # that the case is not reached
    assert attribute_of(n) == "rdn"
    src = (ROOT / "programs" / "acceptance.py").read_text()
    assert "atan(3 2^-26)" in src and "is NOT reached" in src


# ---- the record -------------------------------------------------------------

def committed():
    doc = json.loads((ROOT / "programs" / "acceptance-rev8.json").read_bytes())
    return {r["name"]: r for r in doc["entries"]}


def test_the_committed_record_holds_the_recipe_and_the_marks_by_segment():
    rec = committed()
    for n in NAMES:
        r = rec[n]
        fmt = fmt_of(n)
        blk = A.BLOCK[fmt.name]
        lanes = [t * blk + A.STRUCTURED_LANE for t in range(4)]
        want = A.prepare(entry(n))[3]["structured"]
        assert r["structured"] == want
        assert "range" not in r and "no_structured" not in r
        # marks: the four lanes in segment 0, none in segments 1 to 3
        assert [sorted(l for l, _b in seg) for seg in r["marked"]] == \
            [lanes, [], [], []]
        assert all(b & seq.LANE_MARKED for _l, b in r["marked"][0])
        assert r["status"] == [seq.STATUS_MARKED, 0, 0, 0]
        assert r["flags"][0] & 0x1f == 0x1f and len(r["flags"]) == 4


def test_no_follower_lane_is_declared_a_range_lane():
    for n in NAMES:
        assert n not in A.RANGE_LANES and "range_segments" not in entry(n)


def test_mark_problems_names_a_lane_that_marks_undeclared():
    """The plant: the recipe's block with one more lane marked is named by
    lane and segment, for the follower's pair descriptor as for a single."""
    n = NAMES[0]
    rec = A.prepare(entry(n))[3]
    blocks = [bytearray([0x10] * 256) for _ in range(4)]
    for s in rec["structured"]:
        blocks[0][s["lane"]] = 0x90
    status = [seq.STATUS_MARKED, 0, 0, 0]
    assert A.mark_problems(rec["structured"],
                           [bytes(b) for b in blocks], status) == []
    blocks[2][100] |= seq.LANE_MARKED
    probs = A.mark_problems(rec["structured"], [bytes(b) for b in blocks],
                            status)
    assert any("segment 2: lanes [100] carry bit 7" in p for p in probs)
    blocks[2][100] &= 0x7f
    blocks[0][3] = 0x10
    probs = A.mark_problems(rec["structured"], [bytes(b) for b in blocks],
                            status)
    assert any("lane 3 " in p and "components [1, 0]" in p
               and "without bit 7" in p for p in probs)
