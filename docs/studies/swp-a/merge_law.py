# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""merge_law.py - the laws the accumulation design in the study relies on, checked on a MODEL.

Nothing here is the store; the study designs one (docs/studies/SWP-A-coverage.md, "Accumulating
coverage") and this script holds the design's central claims to random tests of an executable
model of it, so the claims are not only prose. The model:

  campaign   a canonical description (operation, attribute, stratum, enumeration) whose SHA-256 is
             its id, and a space of N cases numbered 0 .. N-1 (the enumeration is a keyed
             permutation, perm_check.c: the cases of an index interval are distinct); the
             description is stored as a record of its own, so a slice can be replayed
  record     an immutable fact: campaign, subject class, index interval [lo, hi), the case
             counts it reports, the mismatches it found, and a digest; its identity is the
             hash of its canonical bytes
  store      a SET of records. Merging two stores is the union of the sets
  coverage   a pure function of the set: for each (campaign, subject class) the union of the
             intervals of the records that are CONSISTENT (cases == hi - lo + the tool's extra
             cases) and CLEAN (no mismatch); a record that finds a mismatch is never coverage

Laws checked, each over the same 3,000 random scenarios (three stores of forty records over two
campaigns and two subject classes, 80% good, 10% with a wrong case count, 10% with mismatches):
  L1  merge order and grouping do not matter                      L2  duplicates (the same slice from a second device) do not matter
  L3  coverage equals an independent bitmap of the same records   L4  adding a record never loses coverage
  L5  an inconsistent or failing record is not coverage           L6  subject classes do not mix
  L7  total cases RUN may exceed the space, coverage never does
  L8  Merkle localization: two devices' slice digests differ iff some batch's outputs differ, and the
      first differing batch is found in about 2 log2(n) hash comparisons, not n
  L9  a slice is replayable from the store: its record, the campaign record its cid hashes, and the
      tool; without the campaign record, or with one that does not hash to the cid, replay refuses by name

Every law is run twice: on the right fold, where it must report 0 violations, and on a PLANTED wrong
version of the fold (or of the descent), where the SAME test must report violations. A law whose test
cannot be made to fail would prove nothing.
usage: python merge_law.py
"""
import hashlib
import json
import random
import sys

fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-96s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


# ---------------------------------------------------------------- the model
def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def make_record(cid, subject, lo, hi, cases=None, vm=0, fm=0, digest="d", extra=0, device="dev"):
    body = {"kind": "slice", "cid": cid, "subject": subject, "lo": lo, "hi": hi,
            "cases": (hi - lo + extra) if cases is None else cases, "vm": vm, "fm": fm, "digest": digest,
            "extra": extra, "device": device}
    rid = hashlib.sha256(canon(body).encode()).hexdigest()
    return rid, body


def merge_intervals(iv):
    out = []
    for lo, hi in sorted(iv):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def merge_intervals_bad(iv):
    """PLANTED: a nested interval ends the merged one early (the later end, not the larger)."""
    out = []
    for lo, hi in sorted(iv):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], hi)
        else:
            out.append((lo, hi))
    return out


def counts_as_coverage(rec):
    return rec["cases"] == rec["hi"] - rec["lo"] + rec["extra"] and rec["vm"] == 0 and rec["fm"] == 0 and rec["hi"] > rec["lo"]


def fold(store, mode="good"):
    """store: dict id -> record. Returns {(cid, subject): merged intervals}. `mode` is "good" or the name of a
    PLANTED wrong version, each breaking one law:
      first     the first record of a group wins (breaks L1: the answer depends on the order)
      naive     the lengths are SUMMED, not unioned (breaks L2, L3, L7: duplicates count again, coverage can exceed the space)
      badmerge  a nested interval ends the merged one early (breaks L3: the union is not the bitmap's)
      overwrite a later record with the same lo replaces the earlier (breaks L4: adding a record can lose coverage)
      nocount   the case-count rule is not applied (breaks L5)
      novm      a record that found a mismatch counts (breaks L5)
      blind     the subject class is ignored (breaks L6)"""
    groups = {}
    for rid, rec in store.items():
        if rec.get("kind") != "slice":                         # a campaign record is not coverage
            continue
        ok = counts_as_coverage(rec)
        if mode == "nocount":
            ok = rec["vm"] == 0 and rec["fm"] == 0 and rec["hi"] > rec["lo"]
        elif mode == "novm":
            ok = rec["cases"] == rec["hi"] - rec["lo"] + rec["extra"] and rec["hi"] > rec["lo"]
        if not ok:
            continue
        key = (rec["cid"], "*" if mode == "blind" else rec["subject"])
        if mode == "first":
            groups.setdefault(key, [(rec["lo"], rec["hi"])])
        elif mode == "overwrite":
            groups.setdefault(key, {})[rec["lo"]] = rec["hi"]
        else:
            groups.setdefault(key, []).append((rec["lo"], rec["hi"]))
    if mode == "naive":
        return {k: [(0, sum(h - l for l, h in v))] for k, v in groups.items()}
    if mode == "overwrite":
        return {k: merge_intervals(list(d.items())) for k, d in groups.items()}
    merge = merge_intervals_bad if mode == "badmerge" else merge_intervals
    return {k: merge(v) for k, v in groups.items()}


def covered(cov, key):
    return sum(h - l for l, h in cov.get(key, []))


def random_record(rng, N, cids, subjects, device=None):
    cid, subj = rng.choice(cids), rng.choice(subjects)
    lo = rng.randrange(0, N)
    hi = min(N, lo + rng.randrange(1, N // 4 + 2))
    kind = rng.random()
    dev = device or rng.choice(("d1", "d2", "d3"))
    if kind < 0.8:
        return make_record(cid, subj, lo, hi, device=dev)
    if kind < 0.9:
        return make_record(cid, subj, lo, hi, cases=hi - lo - 1)                # inconsistent count
    return make_record(cid, subj, lo, hi, vm=rng.randrange(1, 5))               # found a mismatch


CIDS, SUBJECTS = ("c1", "c2"), ("rtl-A", "rtl-B")


def random_store(rng, N, n=40):
    store = {}
    for _ in range(n):
        rid, rec = random_record(rng, N, CIDS, SUBJECTS)
        store[rid] = rec
    return store


def bitmap_cover(store, N, cid, subj):
    bm = bytearray(N)
    for rec in store.values():
        if rec["cid"] == cid and rec["subject"] == subj and counts_as_coverage(rec):
            for i in range(rec["lo"], rec["hi"]):
                bm[i] = 1
    return sum(bm)


def scenarios(rng, N, t):
    """The same t scenarios for the right fold and every planted one."""
    out = []
    for _ in range(t):
        S1, S2, S3 = random_store(rng, N), random_store(rng, N), random_store(rng, N)
        # a second device repeating each record of S1: distinct records (their device differs), the same slice
        dups = {}
        for rec in S1.values():
            rid, cp = make_record(rec["cid"], rec["subject"], rec["lo"], rec["hi"], cases=rec["cases"], vm=rec["vm"], fm=rec["fm"],
                                  extra=rec["extra"], device="d9")
            dups[rid] = cp
        xrid, xrec = random_record(rng, N, CIDS, SUBJECTS)                      # the record L4 adds
        if rng.random() < 0.5:
            # half the time a SHORTER TWIN of a good record of S1: the same campaign, subject class and lo, a smaller hi (a legitimate record)
            good = [r for r in S1.values() if counts_as_coverage(r) and r["hi"] - r["lo"] > 1]
            if good:
                r0 = rng.choice(good)
                xrid, xrec = make_record(r0["cid"], r0["subject"], r0["lo"], r0["lo"] + 1 + rng.randrange(r0["hi"] - r0["lo"] - 1), device="d8")
        out.append((S1, S2, S3, dups, (xrid, xrec)))
    return out


def laws(scen, N, mode):
    """The violations of L1 to L7 over the scenarios, with the fold `mode`."""
    f = lambda s: fold(s, mode)
    bad = dict.fromkeys(("L1", "L2", "L3", "L4", "L5", "L6", "L7"), 0)
    for S1, S2, S3, dups, (xrid, xrec) in scen:
        u12 = dict(S1); u12.update(S2)
        u21 = dict(S2); u21.update(S1)
        l = dict(u12); l.update(S3)
        r23 = dict(S2); r23.update(S3)
        r = dict(S1); r.update(r23)
        if f(u12) != f(u21) or f(l) != f(r):                                    # L1 order and grouping
            bad["L1"] += 1
        both = dict(S1); both.update(dups)
        if f(both) != f(S1):                                                    # L2 the same slice from a second device
            bad["L2"] += 1
        if any(covered(f(l), (cid, subj)) != bitmap_cover(l, N, cid, subj) for cid in CIDS for subj in SUBJECTS):   # L3 against a bitmap
            bad["L3"] += 1
        before = f(S1)                                                          # L4 adding any record never loses coverage
        after = f({**S1, xrid: xrec})
        if any(covered(after, k) < covered(before, k) for k in before):
            bad["L4"] += 1
        rid1, r1 = make_record("c9", "rtl-A", 0, 10, cases=9)                   # L5 inconsistent or failing records are not coverage
        rid2, r2 = make_record("c9", "rtl-A", 0, 10, vm=1)
        rid3, r3 = make_record("c9", "rtl-A", 0, 10, fm=2)
        if f({rid1: r1, rid2: r2, rid3: r3}) != {}:
            bad["L5"] += 1
        c = f(l)                                                                # L6 subject classes do not mix
        a_only = f({k: v for k, v in l.items() if v["subject"] == "rtl-A"})
        if any(c.get(k) != a_only.get(k) for k in a_only):
            bad["L6"] += 1
        if any(covered(c, k) > N for k in c):                                   # L7 coverage never exceeds the space
            bad["L7"] += 1
    return bad


# ---------------------------------------------------------------- Merkle localization
def h(b):
    return hashlib.sha256(b).digest()


def merkle(leaves):
    """All levels of a binary Merkle tree (an odd node is promoted), leaves = list of bytes hashes."""
    levels = [leaves]
    while len(levels[-1]) > 1:
        cur, nxt = levels[-1], []
        for i in range(0, len(cur), 2):
            nxt.append(h(b"\x01" + cur[i] + cur[i + 1]) if i + 1 < len(cur) else cur[i])
        levels.append(nxt)
    return levels


def first_difference(A, B, buggy=False):
    """Find the first differing leaf by descending from the roots; returns (leaf index or None, comparisons).
    buggy=True is the PLANTED descent that always goes left."""
    if A[-1][0] == B[-1][0]:
        return None, 1
    comps, idx = 1, 0
    for lvl in range(len(A) - 2, -1, -1):
        left = idx * 2
        comps += 1
        if buggy or (left < len(A[lvl]) and A[lvl][left] != B[lvl][left]):
            idx = left
        else:
            idx = left + 1
    return idx, comps


# ---------------------------------------------------------------- replay from the store (L9)
def campaign_id(desc):
    return hashlib.sha256(canon(desc).encode()).hexdigest()


def toy_outputs(desc, lo, hi, batch=4):
    """The per-batch hashes of the outputs of slice [lo, hi) of a campaign: a stand-in for the tool run from the
    description (the operand of index i is a function of the description and i alone, as the keyed permutation makes it)."""
    leaves = []
    for b0 in range(lo, hi, batch):
        leaves.append(h(("%s|%d|%d" % (canon(desc), b0, min(hi, b0 + batch))).encode()))
    return merkle(leaves)


def replay(store, rec, verify_cid=True):
    """Re-run a slice from the store alone. Returns a verdict string: 'ok', 'differs at batch j', or a refusal by name."""
    camp = store.get(rec["cid"])
    if camp is None:
        return "refused: no campaign record for cid"
    camp = {k: v for k, v in camp.items() if k != "kind"}
    if verify_cid and campaign_id(camp) != rec["cid"]:
        return "refused: campaign record does not hash to its cid"
    mine = toy_outputs(camp, rec["lo"], rec["hi"])
    theirs = rec["digest_levels"]
    if mine[-1][0] == theirs[-1][0]:
        return "ok"
    j, _ = first_difference(mine, theirs)
    return "differs at batch %d" % j


def main():
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    rng = random.Random(20261019)
    N = 256
    print("merge_law.py: the accumulation design's laws, on an executable model")
    print()
    t = 3000
    scen = scenarios(rng, N, t)
    good = laws(scen, N, "good")
    check("L1 merge order and grouping do not change coverage (commutative, associative)", good["L1"] == 0, "(%d scenarios, %d violations)" % (t, good["L1"]))
    check("L2 a second device's copy of every record (distinct records, the same slices) does not change coverage", good["L2"] == 0, "(%d violations)" % good["L2"])
    check("L3 coverage from interval union equals an independent bitmap of the same records", good["L3"] == 0, "(%d violations)" % good["L3"])
    check("L4 adding a record never reduces coverage (monotone)", good["L4"] == 0, "(%d violations)" % good["L4"])
    check("L5 a record whose case count is wrong, or that found a mismatch, is not coverage", good["L5"] == 0, "(%d violations)" % good["L5"])
    check("L6 records of one subject class (RTL build) never count for another", good["L6"] == 0, "(%d violations)" % good["L6"])
    check("L7 coverage never exceeds the space although the cases RUN may", good["L7"] == 0, "(%d violations)" % good["L7"])

    # the cases-run total can exceed the space: ten devices, the same slice
    many = {}
    for d in range(10):
        rid, rec = make_record("c1", "rtl-A", 0, N, device="dev%d" % d)
        many[rid] = rec
    check("L7' ten devices on one slice: cases run = 10 N, coverage = N",
          sum(v["cases"] for v in many.values()) == 10 * N and covered(fold(many), ("c1", "rtl-A")) == N)
    rid_b, rec_b = make_record("c1", "rtl-B", 0, N // 2)                        # only build B ran; build A has run nothing
    check("the correct fold credits build A with nothing when only build B ran", covered(fold({rid_b: rec_b}), ("c1", "rtl-A")) == 0)

    # ---- the plants: each wrong fold is run through the SAME tests and must break the law written for it
    print()
    plants = (("first", "L1"), ("naive", "L2"), ("badmerge", "L3"), ("overwrite", "L4"), ("nocount", "L5"), ("novm", "L5"),
              ("blind", "L6"), ("naive", "L7"))
    results = {}
    for mode, law in plants:
        if mode not in results:
            results[mode] = laws(scen, N, mode)
        v = results[mode]
        check("PLANT %-9s breaks %s: the same test reports violations" % (mode, law), v[law] > 0,
              "(%d of %d scenarios; also broken: %s)" % (v[law], t, ", ".join("%s %d" % (k, n) for k, n in v.items() if n and k != law) or "none"))
    over = any(covered(fold(many, "naive"), k) > N for k in fold(many, "naive"))
    check("PLANT naive on the ten devices of L7': coverage above the space", over)
    check("PLANT blind on build B's half-space slice credits half the space to a build that never ran a case",
          covered(fold({rid_b: rec_b}, "blind"), ("c1", "*")) == N // 2)

    # ---- L8 Merkle localization
    print()
    nb = 4096                                  # batches in a slice: a 2^24-case slice of 4096-case batches
    outs = [h(b"batch %d" % i) for i in range(nb)]
    A = merkle(outs)
    ok_equal = merkle(list(outs))[-1][0] == A[-1][0]
    check("L8 two devices with identical outputs have identical roots", ok_equal)
    trials = []
    for trial in range(300):
        j = rng.randrange(nb)
        mod = list(outs)
        mod[j] = h(b"flipped %d" % j)
        trials.append((j, merkle(mod)))

    def localize(buggy):
        wrong = worst = 0
        for j, B in trials:
            idx, comps = first_difference(A, B, buggy)
            worst = max(worst, comps)
            if idx != j or A[-1][0] == B[-1][0]:
                wrong += 1
        return wrong, worst
    wrong, worst = localize(False)
    check("L8 one differing batch changes the root and is found by descent (300 trials, 4,096 batches)", wrong == 0, "(%d wrong)" % wrong)
    check("L8 the descent used at most 2 log2(n) + 2 = 26 comparisons, against 4,096 for a scan", worst <= 26, "(worst %d)" % worst)
    two = list(outs)
    two[7] = h(b"x"); two[3000] = h(b"y")
    idx, comps = first_difference(A, merkle(two))
    check("with two differing batches the descent finds the FIRST (batch 7), and the rest by repeating on the remainder", idx == 7)
    bw, _ = localize(True)
    check("PLANT a descent that always goes left breaks L8: the same trials find the wrong batch", bw > 250, "(%d of 300 wrong)" % bw)
    check("PLANT a root comparison alone says 'differs' but not where (the descent is what localizes)", A[-1][0] != merkle(two)[-1][0])

    # ---- L9 a slice is replayable from the store: record + campaign record + tool
    print()
    desc = {"operation": "div32", "attribute": "rne", "stratum": "core", "enumeration": {"kind": "feistel", "width": 23, "rounds": 6, "key": "0x5eed"}}
    cid = campaign_id(desc)
    store = {cid: dict(desc, kind="campaign")}
    levels = toy_outputs(desc, 0, 64)
    rec9 = {"cid": cid, "lo": 0, "hi": 64, "digest_levels": levels}
    check("L9 an honest slice replays from its record and its campaign record alone", replay(store, rec9) == "ok")
    bad_levels = [list(lv) for lv in levels]
    bad_levels[0][5] = h(b"a flipped batch")                                   # a tampered leaf: the roots differ, the descent says where
    tampered = merkle(bad_levels[0])
    rec9b = dict(rec9, digest_levels=tampered)
    check("L9 a tampered slice is found by replay and its batch named", replay(store, rec9b) == "differs at batch 5", "(%s)" % replay(store, rec9b))
    check("L9 without the campaign record replay refuses by name (the cid is a hash, its preimage is not in the slice record)",
          replay({}, rec9) == "refused: no campaign record for cid")
    swapped = {cid: dict(desc, attribute="rtz", kind="campaign")}               # a campaign record that is not the one the cid hashes
    check("L9 a campaign record that does not hash to the cid is refused by name", replay(swapped, rec9) == "refused: campaign record does not hash to its cid")
    check("PLANT a replay that does not check the campaign record against the cid calls an honest slice tampered, not a bad campaign record",
          replay(swapped, rec9, verify_cid=False).startswith("differs"), "(%s)" % replay(swapped, rec9, verify_cid=False))
    check("a campaign record is not coverage: a store holding only it covers nothing", fold(store) == {})

    # ---- R. the size of the record of section 5.3, its fields filled to the lengths the design gives them
    print()
    rec = {"v": 1, "cid": "a" * 64, "stratum": "core", "lo": 0, "hi": 268435456, "cases": 268435456, "vm": 0, "fm": 0, "skipped": 0,
           "digest": {"alg": "sha256-merkle-4096", "root": "b" * 64, "batches": 65536},
           "subject": {"rtl": "c" * 40, "xclbin": "d" * 64, "tile": 2, "abi": "0.18"},
           "tool": {"build_id": "e" * 40, "commit": "f" * 40, "cc": "gcc 11.4", "flags": "1" * 64},
           "oracle": {"kind": "host-fpu+glibc", "libm": "glibc 2.39", "cpu": "12th Gen Intel(R) Core(TM) i5-12400F",
                      "probes": {"scalbn": "RELIABLE", "castflags": "RELIABLE", "cvtfrom": "RELIABLE"}},
           "control": {"sabotage_detected": True},
           "run": {"id": "card-stress-1016", "device": "d1", "start": "2026-10-16 18:58:23", "end": "2026-10-16 19:03:11", "rate": 1.99e6},
           "sig": {"alg": "ed25519", "key": "9" * 64, "sig": "8" * 128}}
    size = len(canon(rec))
    camp_rec = {"v": 1, "kind": "campaign", "operation": "div32", "attribute": "rne", "stratum": {"name": "core", "version": 1, "index": "4^23 significand pairs"},
                "enumeration": {"kind": "feistel", "width": 23, "rounds": 6, "key": "0x" + "5" * 16}, "oracle": "host-fpu+glibc",
                "count_unit": "pairs", "expected_cases": "hi-lo"}
    csize = len(canon(camp_rec))
    slices, weekends = 3287, 520
    print("R. a record as section 5.3 writes it, canonical JSON: %d bytes; a weekend of %d slices %.1f MB; a decade of %d weekends %.2f GB"
          % (size, slices, size * slices / 1e6, weekends, size * slices * weekends / 1e9))
    print("   a campaign record (once for every slice that names it): %d bytes" % csize)
    check("a decade of weekly weekends from one device is under 5 GB of records (the study's 'not a size problem')",
          size * slices * weekends < 5e9, "(%d bytes a record, %.2f GB)" % (size, size * slices * weekends / 1e9))
    print()
    print("merge_law: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
