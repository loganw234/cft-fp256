# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The revision-8 set's routine entries, held without a card, a library or
a compile (parcel MA, M1's build, item 6; programs/acceptance.py, whose
docstring is the definition):

  set         REV8, the ten workloads, is what it was, name for name; the
              routine entries follow them, six, each on the quad the rule
              puts it on; the acceptance set's references build the lanes
              they built before the routine entries' parameters existed
              (their init digests are programs/acceptance.json's)
  recipe      one structured lane a tile, past the spot check's ordinary
              lanes and clear of the special ones; each function is one the
              entry's committed image holds; each centre is a centre of
              python/tests/mathlib_family.py's FAMILY at rne, the theory
              demands it marked, and centre_bits() builds its encoding
              without mpmath as mathlib_family.argument() does with it; the
              control's off-centre argument is none (mpmath)
  checks      the mark checks' pure functions - mark_problems,
              block_problems, probe_run_problems, probe_device_problems and
              outcome_problems on the marks - green on a block the recipe
              describes, and a planted fault in a copy of it red in the
              check it is for, by name: a structured lane's byte with bit 7
              cleared, STATUS[6] cleared, a lane marked that the recipe does
              not mark, STATUS[6] in a segment with no marked lane, a flag
              word the lanes do not OR to, a probe whose end state or STATUS
              is not the certificate's, a probe on another backend, tile
              count, image or depth, and a record whose marks or block
              hashes were edited
  record      (KL-345, parcel P4) the committed record
              programs/acceptance-rev8.json carries `marked` and
              `lane_flags_sha256` for each of the six routine entries and
              neither for the ten workloads; a record that lacks one of the
              two keys for a routine entry fails outcome_problems, naming
              the entry and the key, for each key in turn and for both; the
              verdict line names only the comparisons that were made

The driver's own run (python programs/acceptance.py --set rev8 --only
<routine entries>) is the end-to-end check, with its own controls.
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "tests"))
sys.path.insert(0, str(ROOT / "programs"))

import acceptance as A  # noqa: E402
from cft_golden import FORMATS, cert2, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden.cert import Identity  # noqa: E402

TEN = ("gray_scott_hard_fp64", "gray_scott_wide_fp256",
       "lorenz_tangent_hard_fp64", "lorenz_tangent_wide_fp256",
       "gray_scott_extended_fp64", "fput_extended_fp64",
       "phi4_extended_fp64", "kuramoto_sivashinsky_extended_fp64",
       "reservoir_extended_fp64", "riccati_extended_fp64")
ROUTINES = tuple(n for n, _s, _t in A.REV8_ROUTINES)
SYSTEMS = ROOT / "programs" / "systems"


def fmt_of(name):
    return FORMATS["fp256" if name.endswith("fp256") else "fp64"]


# ---- the set ----------------------------------------------------------------

def test_the_ten_workloads_are_what_they_were():
    assert tuple(w for w, _t in A.REV8) == TEN
    assert [e["name"] for e in A.entries("rev8")] == list(TEN) + \
        list(ROUTINES)


def test_each_routine_entry_is_on_the_quad_by_the_rule_and_has_no_compile():
    for e in A.entries("rev8"):
        if e["kind"] == "workload":
            continue
        image = (ROOT / e["image"]).read_bytes()
        assert A.rule_target(image) == e["target"] == "u50-rev8-quad"
        assert A.rule_problems(e["target"], image) == []
        assert e["tiles"] == 4 and e["depth"] == 4096
        assert (ROOT / e["bank"]).is_file() and (ROOT / e["source"]).is_file()


def test_the_acceptance_sets_references_build_the_same_lanes():
    """reference_lanes gained a `tiles` parameter whose default is the
    quad's four: every reference of the acceptance set is its record."""
    doc = json.loads((ROOT / "programs" / "acceptance.json").read_bytes())
    want = {e["name"]: e for e in doc["entries"]}
    n = 0
    for e in A.entries():
        if e["kind"] == "workload":
            continue
        _image, _bank, _init, rec, _f3, _s, _h = A.prepare(e)
        for key in ("init_sha256", "image_sha256", "bank_sha256", "lanes",
                    "slots", "steps", "special", "spot", "format"):
            assert rec[key] == want[e["name"]][key], (e["name"], key)
        assert "structured" not in rec
        n += 1
    assert n == 10


# ---- the recipe -------------------------------------------------------------

def test_one_structured_lane_a_tile_clear_of_the_special_lanes():
    for e in A.entries("rev8"):
        if e["kind"] == "workload":
            continue
        fmt = fmt_of(e["name"])
        blk = A.BLOCK[fmt.name]
        _i, _b, _init, rec, _f3, _s, _h = A.prepare(e)
        lanes = [s["lane"] for s in rec["structured"]]
        assert lanes == [t * blk + A.STRUCTURED_LANE for t in range(4)]
        assert not set(lanes) & set(rec["special"])
        assert not set(lanes) & {0, 1, 2}
        assert set(lanes) <= set(rec["spot"])
        assert all(s["segment"] == 0 for s in rec["structured"])
        assert [s["tile"] for s in rec["structured"]] == [0, 1, 2, 3]


def test_each_function_is_one_the_images_manifest_holds_and_none_never_marks():
    for name in ROUTINES:
        m = json.loads((SYSTEMS / "compiled-tangent"
                        / f"{name}.manifest.json").read_bytes())
        held = set(m["routines"]["calls"])
        for fn, comp, _c in A.STRUCTURED[name]:
            assert fn in held, (name, fn, held)
            assert fn not in ("exp2", "log2")      # no family (parcel VMP)
            assert comp in (0, 1)


def test_centre_bits_known_values():
    f64, f256 = FORMATS["fp64"], FORMATS["fp256"]
    assert A.centre_bits(f64, (1, 53)) == 0x3ca0000000000000
    assert A.centre_bits(f64, (-1, 54)) == 0xbc90000000000000
    assert A.centre_bits(f64, ("u", 6)) == 0x3ff0000000000006
    assert A.centre_bits(f64, ("d", 2)) == 0x3feffffffffffffe
    assert A.centre_bits(f256, (1, 237)) == int("3ff12" + "0" * 59, 16)
    assert A.centre_bits(f256, ("d", 12)) == \
        int("3fffe" + "f" * 58 + "4", 16)
    with pytest.raises(ValueError):
        A.centre_bits(f64, ("n", 54))      # needs ln 2


def test_the_centres_are_the_family_at_rne_and_the_theory_marks_them():
    pytest.importorskip("mpmath")
    import mathlib_family as F
    for name in ROUTINES:
        fmt = fmt_of(name)
        for fn, _comp, centre in A.STRUCTURED[name]:
            assert centre in F.FAMILY[fn][fmt.name]["rne"], (name, centre)
            bits = F.argument(fmt, centre)
            assert A.centre_bits(fmt, centre) == bits
            assert F.classify(fmt, sf.RND_RNE, bits, None, fn) == "mark"


def test_the_off_centre_argument_is_clear_by_the_theory():
    """The control's lane, moved off its centre by a relative 2^-20, is
    outside every window: the theory classifies it clear, not merely 'not
    marked'."""
    pytest.importorskip("mpmath")
    import mathlib_family as F
    for name in ROUTINES:
        fmt = fmt_of(name)
        for fn, _comp, centre in A.STRUCTURED[name]:
            bits = A.off_centre(fmt, A.centre_bits(fmt, centre))
            assert F.classify(fmt, sf.RND_RNE, bits, None, fn) == "clear", \
                (name, centre)


# ---- the checks, on a block the recipe describes ---------------------------

LANES = 256
ORD, MARK = 0x10, 0x90         # INEXACT; INEXACT and the mark


def structured():
    return [{"lane": 3 + 64 * t, "tile": t, "segment": 0, "function": "exp",
             "component": 1, "centre": [1, 53], "argument": "0x3ca0"}
            for t in range(4)]


def blocks():
    out = [bytearray([ORD] * LANES) for _ in range(4)]
    for s in structured():
        out[0][s["lane"]] = MARK
    return [bytes(b) for b in out]


FLAGS = [ORD, ORD, ORD, ORD]
STATUS = [seq.STATUS_MARKED, 0, 0, 0]


def cleared(bl, seg, lane, mask):
    out = [bytearray(b) for b in bl]
    out[seg][lane] &= 0xFF & ~mask
    return [bytes(b) for b in out]


def test_the_checks_are_green_on_the_recipes_block():
    assert A.mark_problems(structured(), blocks(), STATUS) == []
    assert A.block_problems(blocks(), FLAGS, STATUS) == []


def test_plant_a_structured_lanes_byte_without_bit_7():
    probs = A.mark_problems(structured(), cleared(blocks(), 0, 67,
                                                  seq.LANE_MARKED), STATUS)
    assert any("lane 67 " in p and "without bit 7" in p for p in probs)
    assert len(probs) == 1


def test_plant_status_without_status_6():
    bad = [0, 0, 0, 0]
    assert any("lacks STATUS[6]" in p
               for p in A.mark_problems(structured(), blocks(), bad))
    assert any("lacks STATUS[6]" in p
               for p in A.block_problems(blocks(), FLAGS, bad))


def test_plant_a_lane_marked_that_the_recipe_does_not_mark():
    bl = [bytearray(b) for b in blocks()]
    bl[2][100] |= seq.LANE_MARKED
    probs = A.mark_problems(structured(), [bytes(b) for b in bl], STATUS)
    assert any("segment 2: lanes [100] carry bit 7" in p for p in probs)


def test_plant_status_6_in_a_segment_with_no_marked_lane():
    probs = A.mark_problems(structured(), blocks(),
                            [STATUS[0], seq.STATUS_MARKED, 0, 0])
    assert any("segment 1's STATUS" in p and "marks no lane in it" in p
               for p in probs)


def test_plant_a_flag_word_the_lanes_do_not_or_to():
    assert any("OR to" in p for p in
               A.block_problems(blocks(), [ORD ^ sf.FLAG_INEXACT, ORD, ORD,
                                           ORD], STATUS))
    assert any("[6:5]" in p for p in
               A.block_problems(blocks(), FLAGS, [STATUS[0] | 0x10, 0, 0, 0]))


def test_plant_a_probe_that_is_not_the_certificates_run():
    files = {k: bytes([k]) * 8 for k in range(5)}
    good = [(files[k + 1], FLAGS[k], STATUS[k], b"") for k in range(4)]
    assert A.probe_run_problems(good, files, FLAGS, STATUS) == []
    bent = [(b"\x02" + files[1][1:], FLAGS[0], STATUS[0], b"")] + good[1:]
    assert any("end state" in p for p in
               A.probe_run_problems(bent, files, FLAGS, STATUS))
    other = [(files[1], FLAGS[0], 0, b"")] + good[1:]
    assert any("probe's STATUS" in p for p in
               A.probe_run_problems(other, files, FLAGS, STATUS))
    other = [(files[1], 0, STATUS[0], b"")] + good[1:]
    assert any("flag word" in p for p in
               A.probe_run_problems(other, files, FLAGS, STATUS))


def test_plant_a_probe_on_another_device():
    ident = Identity(backend="xrt", device_xclbin="ab" * 32, device_tiles=4)
    got = {"backend": "xrt", "tiles": 4, "depth": 4096, "xclbin": "ab" * 32}
    assert A.probe_device_problems(got, ident, 4096) == []
    assert any("backend" in p for p in A.probe_device_problems(
        dict(got, backend="software"), ident, 4096))
    assert any("tiles" in p for p in A.probe_device_problems(
        dict(got, tiles=1), ident, 4096))
    assert any("image" in p for p in A.probe_device_problems(
        dict(got, xclbin="cd" * 32), ident, 4096))
    assert any("scratch slots" in p for p in A.probe_device_problems(
        dict(got, depth=8192), ident, 4096))
    sw = Identity(backend="software", device_xclbin="none", device_tiles=1)
    assert A.probe_device_problems(
        {"backend": "software", "tiles": 1, "depth": 4096, "xclbin": None},
        sw, 4096) == []


def test_the_record_keeps_the_marks_and_holds_them():
    marked, hashes = A.marked_record(blocks())
    assert marked[0] == [[s["lane"], MARK] for s in structured()]
    assert marked[1:] == [[], [], []]
    assert hashes == [cert2.lane_flags_hash(None, b) for b in blocks()]
    rec = {"boundaries": ["a"], "flags": [0], "status": [0],
           "marked": marked, "lane_flags_sha256": hashes}
    assert A.outcome_problems(rec, dict(rec)) == []
    bad = dict(rec, marked=[[[3, ORD]] + marked[0][1:]] + marked[1:])
    assert any("segment 0 marks" in p
               for p in A.outcome_problems(bad, dict(rec)))
    bad = dict(rec, lane_flags_sha256=hashes[:1] + ["0" * 64] + hashes[2:])
    assert any("segment 1's lane block" in p
               for p in A.outcome_problems(bad, dict(rec)))
    bad = {k: v for k, v in rec.items() if k != "marked"}
    assert any("were not read" in p
               for p in A.outcome_problems(bad, dict(rec)))


# ---- the record's two keys, required of every routine entry (KL-345) -------

# the two keys, spelled out here and not read from acceptance.py, so that the
# plants below are the same plants against a tree that lacks the fix
KEYS = ("marked", "lane_flags_sha256")


def committed_entries():
    doc = json.loads((ROOT / "programs" / "acceptance-rev8.json")
                     .read_bytes())
    return {e["name"]: e for e in doc["entries"]}


def test_the_committed_record_carries_both_keys_of_each_routine_entry():
    """The record itself, read here: a routine entry without one of the two
    keys is the damage KL-345 named, and the acceptance-rev8 stage (hours)
    is not the only place to see it."""
    entries = committed_entries()
    assert set(ROUTINES) <= set(entries)
    for name in ROUTINES:
        for key in KEYS:
            assert key in entries[name], (name, key)
            assert len(entries[name][key]) == entries[name]["segments"]
    for name in TEN:
        for key in KEYS:
            assert key not in entries[name], (name, key)


def test_plant_a_routine_entrys_record_without_one_of_its_keys():
    """Until KL-345 the comparison was skipped when the record lacked the
    key, and every one of these passed."""
    entries = committed_entries()
    for name in ROUTINES:
        rec = entries[name]
        assert A.outcome_problems(rec, json.loads(json.dumps(rec))) == []
        for key in KEYS:
            want = {k: v for k, v in rec.items() if k != key}
            probs = A.outcome_problems(rec, want)
            assert len(probs) == 1, (name, key, probs)
            assert name in probs[0] and f"`{key}`" in probs[0], probs
        want = {k: v for k, v in rec.items() if k not in KEYS}
        probs = A.outcome_problems(rec, want)
        assert len(probs) == 2, (name, probs)
        assert all(name in p for p in probs)
        assert {k for k in KEYS if any(f"`{k}`" in p for p in probs)} \
            == set(KEYS)


def test_the_other_entries_are_not_asked_for_the_keys():
    """The ten workloads carry neither key and are held to neither."""
    entries = committed_entries()
    for name in TEN:
        rec = entries[name]
        assert A.outcome_problems(rec, json.loads(json.dumps(rec))) == []
    # nor the acceptance set's (revision 7's record, whose entries never
    # carried them): none of its names is a routine's
    assert not {e["name"] for e in A.entries()} & A.ROUTINE_NAMES


def test_the_requirement_is_the_entrys_by_name_not_the_records_shape():
    """A record entry that has lost a key is refused for a routine's name
    only: a synthetic record with no name (the test above) and a workload's
    are not asked for the keys."""
    entries = committed_entries()
    rec = entries[ROUTINES[0]]
    want = {k: v for k, v in rec.items() if k != "marked"}
    assert A.outcome_problems(dict(rec, name=TEN[0]),
                              dict(want, name=TEN[0])) == []
    nameless = {k: v for k, v in want.items() if k != "name"}
    assert A.outcome_problems({k: v for k, v in rec.items() if k != "name"},
                              nameless) == []


def test_the_verdict_line_names_only_what_was_compared():
    rec = committed_entries()[ROUTINES[0]]
    both = A.marks_compared(rec, rec)
    assert "marked lanes" in both and "per-lane blocks" in both
    assert f"the {rec['segments']} per-lane blocks' hashes" in both
    no_marks = {k: v for k, v in rec.items() if k != "marked"}
    only = A.marks_compared(rec, no_marks)
    assert "marked lanes" not in only and "per-lane blocks" in only
    no_hashes = {k: v for k, v in rec.items() if k != "lane_flags_sha256"}
    only = A.marks_compared(rec, no_hashes)
    assert "marked lanes" in only and "per-lane blocks" not in only
    neither = {k: v for k, v in rec.items() if k not in KEYS}
    assert A.marks_compared(rec, neither) == ""
    assert tuple(k for k, _w in A.ROUTINE_KEYS) == KEYS
    assert A.ROUTINE_NAMES == set(ROUTINES)
