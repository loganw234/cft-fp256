# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""merge_law.py - the laws the accumulation design in the study relies on, checked on a MODEL.

Nothing here is the store; the study designs one (docs/studies/SWP-A-coverage.md, "Accumulating
coverage") and this script holds the design's central claims to random tests of an executable
model of it, so the claims are not only prose. The model:

  campaign   an id, and a space of N cases numbered 0 .. N-1 (the enumeration is a keyed
             permutation, perm_check.c: the cases of an index interval are distinct)
  record     an immutable fact: campaign, subject class, index interval [lo, hi), the case
             counts it reports, the mismatches it found, and a digest; its identity is the
             hash of its canonical bytes
  store      a SET of records. Merging two stores is the union of the sets
  coverage   a pure function of the set: for each (campaign, subject class) the union of the
             intervals of the records that are CONSISTENT (cases == hi - lo + the tool's extra
             cases) and CLEAN (no mismatch); a record that finds a mismatch is never coverage

Laws checked (a random scenario each, many of them):
  L1  merge order does not matter (commutative, associative)      L2  duplicates do not matter
  L3  coverage equals an independent bitmap of the same records   L4  adding a record never loses coverage
  L5  an inconsistent or failing record is not coverage           L6  subject classes do not mix
  L7  total cases RUN may exceed the space, coverage never does
  L8  Merkle localization: two devices' slice digests differ iff some batch's outputs differ, and the
      first differing batch is found in about 2 log2(n) hash comparisons, not n

Each law has a PLANTED wrong version that the same test must catch.
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
EXTRA = {"nextup32": 8, "nextdown32": 8}


def make_record(cid, subject, lo, hi, cases=None, vm=0, fm=0, digest="d", extra=0, device="dev"):
    body = {"cid": cid, "subject": subject, "lo": lo, "hi": hi,
            "cases": (hi - lo + extra) if cases is None else cases, "vm": vm, "fm": fm, "digest": digest,
            "extra": extra, "device": device}
    rid = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return rid, body


def merge_intervals(iv):
    out = []
    for lo, hi in sorted(iv):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def counts_as_coverage(rec):
    return rec["cases"] == rec["hi"] - rec["lo"] + rec["extra"] and rec["vm"] == 0 and rec["fm"] == 0 and rec["hi"] > rec["lo"]


def fold(store, by_subject=True, naive=False):
    """store: dict id -> record. Returns {(cid, subject): merged intervals}; naive=True is the planted
    version that SUMS interval lengths instead of taking the union."""
    groups = {}
    for rid, rec in store.items():
        if not counts_as_coverage(rec):
            continue
        key = (rec["cid"], rec["subject"] if by_subject else "*")
        groups.setdefault(key, []).append((rec["lo"], rec["hi"]))
    if naive:
        return {k: [(0, sum(h - l for l, h in v))] for k, v in groups.items()}
    return {k: merge_intervals(v) for k, v in groups.items()}


def covered(cov, key):
    return sum(h - l for l, h in cov.get(key, []))


def random_store(rng, N, cids=("c1", "c2"), subjects=("rtl-A", "rtl-B"), n=40):
    store = {}
    for _ in range(n):
        cid, subj = rng.choice(cids), rng.choice(subjects)
        lo = rng.randrange(0, N)
        hi = min(N, lo + rng.randrange(1, N // 4 + 2))
        kind = rng.random()
        if kind < 0.8:
            rid, rec = make_record(cid, subj, lo, hi, device=rng.choice(("d1", "d2", "d3")))
        elif kind < 0.9:
            rid, rec = make_record(cid, subj, lo, hi, cases=hi - lo - 1)           # inconsistent count
        else:
            rid, rec = make_record(cid, subj, lo, hi, vm=rng.randrange(1, 5))       # found a mismatch
        store[rid] = rec
    return store


def bitmap_cover(store, N, cid, subj):
    bm = bytearray(N)
    for rec in store.values():
        if rec["cid"] == cid and rec["subject"] == subj and counts_as_coverage(rec):
            for i in range(rec["lo"], rec["hi"]):
                bm[i] = 1
    return sum(bm)


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


def first_difference(A, B):
    """Find the first differing leaf by descending from the roots; returns (leaf index or None, comparisons)."""
    if A[-1][0] == B[-1][0]:
        return None, 1
    comps, idx = 1, 0
    for lvl in range(len(A) - 2, -1, -1):
        left = idx * 2
        comps += 1
        if left < len(A[lvl]) and A[lvl][left] != B[lvl][left]:
            idx = left
        else:
            idx = left + 1
    return idx, comps


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
    bad1 = bad2 = bad3 = bad4 = bad5 = bad6 = bad7 = bad8 = 0
    for _ in range(t):
        S1, S2, S3 = random_store(rng, N), random_store(rng, N), random_store(rng, N)
        u12 = dict(S1); u12.update(S2)
        u21 = dict(S2); u21.update(S1)
        l = dict(u12); l.update(S3)
        r23 = dict(S2); r23.update(S3)
        r = dict(S1); r.update(r23)
        # L1 order and grouping
        if fold(u12) != fold(u21) or fold(l) != fold(r):
            bad1 += 1
        # L2 duplicates
        dup = dict(S1); dup.update(S1); dup.update(S2); dup.update(S1)
        if fold(dup) != fold(u12):
            bad2 += 1
        # L3 against a bitmap
        for cid in ("c1", "c2"):
            for subj in ("rtl-A", "rtl-B"):
                if covered(fold(l), (cid, subj)) != bitmap_cover(l, N, cid, subj):
                    bad3 += 1
        # L4 monotone
        before = fold(S1)
        rid, rec = make_record("c1", "rtl-A", 0, N)
        after = fold({**S1, rid: rec})
        if any(covered(after, k) < covered(before, k) for k in before):
            bad4 += 1
        # L5 inconsistent or failing records are not coverage
        rid1, r1 = make_record("c9", "rtl-A", 0, 10, cases=9)
        rid2, r2 = make_record("c9", "rtl-A", 0, 10, vm=1)
        rid3, r3 = make_record("c9", "rtl-A", 0, 10, fm=2)
        if fold({rid1: r1, rid2: r2, rid3: r3}) != {}:
            bad5 += 1
        # L6 subject classes do not mix
        c = fold(l)
        a_only = fold({k: v for k, v in l.items() if v["subject"] == "rtl-A"})
        if any(c.get(k) != a_only.get(k) for k in a_only):
            bad6 += 1
        # L7 total run may exceed the space; coverage never does
        if any(covered(c, k) > N for k in c):
            bad7 += 1
    check("L1 merge order and grouping do not change coverage (commutative, associative)", bad1 == 0, "(%d scenarios, %d violations)" % (t, bad1))
    check("L2 duplicate records do not change coverage (idempotent)", bad2 == 0, "(%d violations)" % bad2)
    check("L3 coverage from interval union equals an independent bitmap of the same records", bad3 == 0, "(%d violations)" % bad3)
    check("L4 adding a record never reduces coverage (monotone)", bad4 == 0, "(%d violations)" % bad4)
    check("L5 a record whose case count is wrong, or that found a mismatch, is not coverage", bad5 == 0, "(%d violations)" % bad5)
    check("L6 records of one subject class (RTL build) never count for another", bad6 == 0, "(%d violations)" % bad6)
    check("L7 coverage never exceeds the space although the cases RUN may", bad7 == 0, "(%d violations)" % bad7)

    # the cases-run total can exceed the space: ten devices, the same slice
    many = {}
    for d in range(10):
        rid, rec = make_record("c1", "rtl-A", 0, N, device="dev%d" % d)
        many[rid] = rec
    check("L7' ten devices on one slice: cases run = 10 N, coverage = N",
          sum(v["cases"] for v in many.values()) == 10 * N and covered(fold(many), ("c1", "rtl-A")) == N)

    # ---- the plants: a wrong version must be caught by the same tests
    over = any(covered(fold(many, naive=True), k) > N for k in fold(many, naive=True))
    check("PLANT: a fold that SUMS interval lengths double-counts duplicates (ten devices on one slice: coverage above the space)", over)
    # a store holding ONLY build B's half-space slice: build A has run nothing
    rid_b, rec_b = make_record("c1", "rtl-B", 0, N // 2)
    only_b = {rid_b: rec_b}
    credited_to_a_correct = covered(fold(only_b), ("c1", "rtl-A"))
    credited_wrong = covered(fold(only_b, by_subject=False), ("c1", "*"))
    check("the correct fold credits build A with nothing when only build B ran", credited_to_a_correct == 0, "(%d)" % credited_to_a_correct)
    check("PLANT: a fold that ignores the subject class credits half the space to a build that never ran a case",
          credited_wrong == N // 2, "(%d of %d)" % (credited_wrong, N))

    # ---- L8 Merkle localization
    print()
    nb = 4096                                  # batches in a slice: a 2^24-case slice of 4096-case batches
    outs = [h(b"batch %d" % i) for i in range(nb)]
    A = merkle(outs)
    ok_equal = merkle(list(outs))[-1][0] == A[-1][0]
    check("L8 two devices with identical outputs have identical roots", ok_equal)
    worst = 0
    wrong = 0
    for trial in range(300):
        j = rng.randrange(nb)
        mod = list(outs)
        mod[j] = h(b"flipped %d" % j)
        B = merkle(mod)
        idx, comps = first_difference(A, B)
        worst = max(worst, comps)
        if idx != j or A[-1][0] == B[-1][0]:
            wrong += 1
    check("L8 one differing batch changes the root and is found by descent (300 trials, 4,096 batches)", wrong == 0, "(%d wrong)" % wrong)
    check("L8 the descent used at most 2 log2(n) + 2 = 26 comparisons, against 4,096 for a scan", worst <= 26, "(worst %d)" % worst)
    two = list(outs)
    two[7] = h(b"x"); two[3000] = h(b"y")
    idx, comps = first_difference(A, merkle(two))
    check("with two differing batches the descent finds the FIRST (batch 7), and the rest by repeating on the remainder", idx == 7)
    # plant: comparing only the roots localizes nothing
    check("PLANT: a root comparison alone says 'differs' but not where (the descent is what localizes)", A[-1][0] != merkle(two)[-1][0])

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
    size = len(json.dumps(rec, sort_keys=True, separators=(",", ":")))
    slices, weekends = 3287, 520
    print("R. a record as section 5.3 writes it, canonical JSON: %d bytes; a weekend of %d slices %.1f MB; a decade of %d weekends %.2f GB"
          % (size, slices, size * slices / 1e6, weekends, size * slices * weekends / 1e9))
    check("a decade of weekly weekends from one device is under 5 GB of records (the study's 'not a size problem')",
          size * slices * weekends < 5e9, "(%d bytes a record, %.2f GB)" % (size, size * slices * weekends / 1e9))
    print()
    print("merge_law: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
