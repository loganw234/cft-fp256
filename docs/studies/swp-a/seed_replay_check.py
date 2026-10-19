# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""seed_replay_check.py - what a second stress run covers, read from the real
driver's own records.

Parcel SC's question: the card's stress driver (hw/card_stress.py) numbers the
slices of a random sweep item n = 0, 1, 2, ... and seeds slice n with
`base_seed + 7919 * n` (hw/card_stress_lib.py, Item.seed_for); it rebuilds n
from the run's own metrics.jsonl (Driver.load_state). Claim under test: a run
in a NEW --out starts at n = 0 again, so it repeats the last run's random
operands and re-serves the exhaustive items from encoding 0; only `--resume`
on the same directory continues.

The measurement is hw/card_stress.py --dry-run --quick, three times (seed_replay.sh):
  A  a fresh --out
  B  another fresh --out
  C  A resumed (--resume --out A)
Its stand-in tools run nothing on a card; the seed and slice logic being
measured is the driver's own. This script reads the three metrics.jsonl files
(A's holds A's first invocation and then C's) and checks:

  1. B's sweep legs equal A's first invocation's: same items, same seed_n, same
     seed, same [lo, hi) - a new directory replays;
  2. C's legs continue A's: every random item's seed_n is one more than before,
     every exhaustive item's lo is where A's slices ended - a resume continues;
  3. the seeds the driver recorded are base + 7919 n, the formula READ in the
     code (the base is taken from the first record, so the test is on the step);
  4. CONTROL: the same comparison on a copy of B whose div32-rne seed is moved
     by one must say "not a replay" - a check that cannot fail proves nothing.

usage: python seed_replay_check.py A_metrics.jsonl B_metrics.jsonl
Exit status 0 only if every check held.
"""
import json
import sys


def sweep_legs(path):
    """[(invocation, image, item, seed_n, seed, count, lo, hi)] in file order;
    the invocation number counts the run_start records."""
    out, inv = [], 0
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            r = json.loads(ln)
            if r.get("type") == "run_start":
                inv += 1
            elif r.get("type") == "leg" and r.get("kind") == "sweep" \
                    and r.get("status") in ("pass", "fail"):
                sw = r.get("sweep") or {}
                out.append((inv, r.get("image"), sw.get("item"), sw.get("seed_n"),
                            sw.get("seed"), sw.get("count"), sw.get("lo"), sw.get("hi")))
    return out


def key(leg):
    """What identifies the slice's CONTENT: the item and its seed or range
    (not the image or the tile it happened to run on)."""
    inv, image, item, seed_n, seed, count, lo, hi = leg
    return (item, seed_n, seed, lo, hi)


def main(argv):
    try:
        sys.stdout.reconfigure(newline="\n")          # the same bytes on Windows and Linux
    except (AttributeError, ValueError):
        pass
    if len(argv) != 3:
        print(__doc__)
        return 2
    A = sweep_legs(argv[1])
    B = sweep_legs(argv[2])
    A1 = [l for l in A if l[0] == 1]
    A2 = [l for l in A if l[0] == 2]
    bad = 0

    def check(label, ok, detail=""):
        nonlocal bad
        print(f"CHECK {label:<66} {'ok' if ok else 'FAILED'} {detail}")
        if not ok:
            bad += 1

    print("sweep legs read:  A first invocation %d, A resumed %d, B %d" % (len(A1), len(A2), len(B)))
    print()
    print("  invocation  image   item          seed_n  seed         lo       hi")
    for tag, legs in (("A.1", A1), ("B  ", B), ("A.2", A2)):
        for inv, image, item, seed_n, seed, count, lo, hi in legs:
            print("  %-10s  %-6s  %-12s  %-6s  %-11s  %-7s  %-7s" % (
                tag, image, item, "-" if seed_n is None else seed_n,
                "-" if seed is None else seed, "-" if lo is None else lo,
                "-" if hi is None else hi))
    print()

    check("both fresh runs served the same number of sweep legs", len(A1) == len(B) and len(B) > 0,
          "(%d, %d)" % (len(A1), len(B)))
    check("B (a new --out) served exactly A's first invocation's slices",
          [key(l) for l in A1] == [key(l) for l in B])
    randoms = [l for l in B if l[3] is not None]
    check("there is at least one random item in the runs", len(randoms) > 0,
          "(%s)" % ", ".join(sorted({l[2] for l in randoms})))
    check("every random item in B started at seed_n = 0", all(l[3] == 0 for l in randoms))
    check("every exhaustive item in B started at lo = 0 (its first slice)",
          all(min(x[6] for x in B if x[2] == l[2]) == 0 for l in B if l[6] is not None))

    # 2. a resume continues
    for l in randoms:
        item, n0, s0 = l[2], l[3], l[4]
        nxt = [x for x in A2 if x[2] == item]
        if not nxt:
            continue
        check(f"A resumed: {item} seed_n {n0} -> {nxt[0][3]}", nxt[0][3] == n0 + 1)
        check(f"A resumed: {item} seed = first seed + 7919 x seed_n", nxt[0][4] == s0 + 7919 * (nxt[0][3] - n0),
              "(%s)" % nxt[0][4])
    for item in sorted({l[2] for l in A1 if l[6] is not None}):
        ends = [l[7] for l in A1 if l[2] == item]
        starts = [l[6] for l in A2 if l[2] == item]
        if starts:
            check(f"A resumed: {item} starts where A's slices ended ({max(ends)})", min(starts) == max(ends))

    # 4. control: the replay check must be able to say no
    tampered = [list(l) for l in B]
    for l in tampered:
        if l[2] == "div32-rne":
            l[4] = (l[4] or 0) + 1
    ctl = [key(tuple(l)) for l in tampered] == [key(l) for l in A1]
    check("CONTROL: B with div32-rne's seed moved by one is NOT a replay of A", not ctl)

    print()
    if bad:
        print("seed_replay_check: %d CHECK(s) FAILED" % bad)
        return 1
    print("seed_replay_check: every CHECK held")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
