# M3 model: what each fragment costs (scratch; the study's section 5):
# instructions in all and by part, bank words, values live at once (the
# design's order and scheduled), the error-free sums, and C4's invariants as
# routines.invariants() states them under the math library's contract.
#
#   python costs.py FMT

import sys
from collections import Counter

from m3core import FORMATS, ATTRS, AN, routines
import m3pow as M

SHOW = (("pow", None), ("powr", None), ("pown", 3), ("pown", -3),
        ("pown", 2), ("rootn", 3), ("rootn", 2), ("compound", 3),
        ("compound", -1), ("pown", 0), ("pown", 1), ("compound", 1))


def cost(fn, fmt, rnd, n):
    b = M.build_any(fn, fmt, rnd, n=n)
    keep = b.live_indices()
    labels = Counter(b.label_of[i] for i in keep)
    f = b.fragment()
    f0 = b.fragment(schedule=False)
    bad = routines.invariants(f, live_cap=None,
                              contract=routines.MATH_CONTRACT)
    return {"ins": len(f.body), "words": len(f.words), "live": f.live_max(),
            "live0": f0.live_max(), "labels": labels, "bad": bad,
            "fast": b.meta.get("fast_two_sum", 0),
            "two": b.meta.get("two_sum", 0), "meta": b.meta}


def main():
    fmt = FORMATS[sys.argv[1]]
    allw = set()
    for fn, n in SHOW:
        rows = []
        for rnd in ATTRS:
            c = cost(fn, fmt, rnd, n)
            rows.append((rnd, c))
            bld = M.build_any(fn, fmt, rnd, n=n)
            allw |= set(bld.words.values())
        c0 = rows[0][1]
        tag = fn if n is None else f"{fn}(x, {n})"
        ins = "/".join(str(c["ins"]) for _r, c in rows)
        live = "/".join(str(c["live"]) for _r, c in rows)
        print(f"{fmt.name} {tag:16s} instructions {ins} (rne/rtz/rdn/rup/"
              f"rmm); words {c0['words']}; live {live} scheduled, "
              f"{c0['live0']} in the design's order; Fast2Sum {c0['fast']}, "
              f"TwoSum {c0['two']}")
        if c0["meta"].get("family") == "double word":
            m = c0["meta"]
            print(f"    plan: G {m['G']}, GL {m['GL']} (K {m['KL']}, D "
                  f"{m['DL']}), GE {m['GE']} (K {m['KE']}, D {m['DE']})")
        parts = ", ".join(f"{k} {v}" for k, v in sorted(
            c0["labels"].items(), key=lambda kv: -kv[1]))
        print(f"    rne by part: {parts}")
        for rnd, c in rows:
            if c["bad"]:
                print(f"    {AN[rnd]} invariants: {'; '.join(c['bad'])}")
    print(f"{fmt.name}: distinct bank words over these fragments and the "
          f"five attributes: {len(allw)}")


if __name__ == "__main__":
    main()
