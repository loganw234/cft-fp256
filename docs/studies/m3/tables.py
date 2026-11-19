# M3 model: the study's tables, read from the captured outputs (scratch;
# COMPUTED from the *.out.txt beside this file, so that no figure of 3.2 and
# 3.3 is copied by hand).
#
#   python tables.py budget|pools|regions|onseq|specials|costs|share

import glob
import re
import sys


def budget():
    print("| format | function | region (n) | main-path lanes | M max | "
          "capacities | bound (bits of margin) | measured worst | residual |")
    print("|---|---|---|---|---|---|---|---|---|")
    order = {"fp64": 0, "fp128": 1, "fp256": 2}
    rows = []
    for f in glob.glob("budget.fp*-*.out.txt"):
        t = open(f, encoding="utf-8").read()
        m = re.search(r"^(fp\d+) (\w+) region (\S+): (\d+) main-path lanes of "
                      r"(\d+) \(n = ([^)]*)\)", t, re.M)
        if not m or "PLANT" in t:
            continue
        b = re.search(r"BOUND ([\d.]+) Bv \(2\^([-\d.inf]+)\)", t)
        mm = re.search(r"M max ([\d.]+) Bv; capacities ([\d.]+) Bv", t)
        w = re.search(r"measured worst ([\d.]+) Bv", t)
        r = re.search(r"residual \(second order, measured\) ([\d.e+-]+) Bv", t)
        fmt, fn, reg, lanes, of, n = m.groups()
        bound = float(b.group(1))
        bits = "-" if bound == 0 else f"{-float(b.group(2)):.2f}"
        rows.append(((order[fmt], fn, reg), f"| {fmt} | {fn} | {reg}"
                     + ("" if n == "None" else f" ({n})")
                     + f" | {lanes} of {of} | {float(mm.group(1)):.4f} | "
                     f"{float(mm.group(2)):.4f} | {bound:.4f} ({bits}) | "
                     f"{float(w.group(1)):.4f} | {float(r.group(1)):.1e} |"))
    for _k, line in sorted(rows):
        print(line)


FNORD = {"pow": 0, "powr": 1, "pown": 2, "rootn": 3, "compound": 4}
FMORD = {"fp64": 0, "fp128": 1, "fp256": 2}


def pools():
    print("| format | function | lanes | marked (rne / rtz / rdn / rup / rmm)"
          " | refused | wrong unmarked |")
    print("|---|---|---|---|---|---|")
    cells = {}
    for f in ["pools_run.fp64.out.txt"] + sorted(
            glob.glob("pools_run.fp128-*.out.txt")) + sorted(
            glob.glob("pools_run.fp256-*.out.txt")):
        try:
            t = open(f, encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"^(fp\d+) (\w+)\s+(\w+): lanes (\d+), marked "
                             r"(\d+), wrong guesses \d+, refused (\d+), WRONG "
                             r"UNMARKED (\d+)", t, re.M):
            fmt, fn, rn, lanes, mk, ref, wr = m.groups()
            c = cells.setdefault((fmt, fn), {"lanes": lanes, "mk": [],
                                             "ref": ref, "wr": 0})
            c["mk"].append(mk)
            c["wr"] += int(wr)
    for (fmt, fn), c in sorted(cells.items(), key=lambda kv: (
            FMORD[kv[0][0]], FNORD[kv[0][1]])):
        print(f"| {fmt} | {fn} | {c['lanes']} | {' / '.join(c['mk'])} | "
              f"{c['ref']} | {c['wr']} |")


def regions():
    print("| format | function | region | lanes | marked (rne / rtz / rdn / "
          "rup / rmm) | wrong unmarked |")
    print("|---|---|---|---|---|---|")
    rows = []
    for f in sorted(glob.glob("regions_run.fp*-*.out.txt")):
        if "first" in f or "second" in f:
            continue                # the first designs' runs, kept apart
        t = open(f, encoding="utf-8").read()
        for k, m in enumerate(re.finditer(
                r"^(fp\d+) (\w+) region (\S+): (\d+) lanes x 5 "
                r"attributes, marked ([\d/]+) \(rne/rtz/rdn/rup/"
                r"rmm\), WRONG UNMARKED (\d+)", t, re.M)):
            fmt, fn, reg, lanes, mk, wr = m.groups()
            if lanes == "0":
                continue            # a region that does not apply (powr's
                                    # negative bases)
            rows.append(((FMORD[fmt], FNORD[fn], k),
                         f"| {fmt} | {fn} | {reg} | {lanes} | "
                         f"{mk.replace('/', ' / ')} | {wr} |"))
    for _k, line in sorted(rows):
        print(line)


def onseq():
    print("| format | function | programs | lanes on seq.py (each attribute)"
          " | differing from the model | wrong unmarked | most live |")
    print("|---|---|---|---|---|---|---|")
    cells = {}
    for f in sorted(glob.glob("onseq.fp*.out.txt")):
        t = open(f, encoding="utf-8").read()
        for m in re.finditer(r"^(fp\d+) (\w+)\s+(\w+): (\d+) programs, (\d+) "
                             r"lanes on seq.py, (\d+) differing from the model,"
                             r" marked (\d+), WRONG UNMARKED (\d+), most live "
                             r"(\d+)", t, re.M):
            fmt, fn, rn, pr, lanes, diff, mk, wr, live = m.groups()
            c = cells.setdefault((fmt, fn), [pr, lanes, 0, 0, 0])
            c[2] += int(diff)
            c[3] += int(wr)
            c[4] = max(c[4], int(live))
    for (fmt, fn), c in sorted(cells.items(), key=lambda kv: (
            FMORD[kv[0][0]], FNORD[kv[0][1]])):
        print(f"| {fmt} | {fn} | {c[0]} | {c[1]} | {c[2]} | {c[3]} | "
              f"{c[4]} |")


def specials():
    cols = ("fp64", "fp128", "fp256")
    rows, order = {}, []
    for fmt in cols:
        try:
            t = open(f"specials.{fmt}.out.txt", encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"^(fp\d+) (\w+)\s+(\d+) lanes x 5: wrong (\d+), "
                             r"marked (\d+), refused (\d+)\s+\| (.*)$", t, re.M):
            f, fn, lanes, wr, mk, ref, name = m.groups()
            key = (fn, name)
            if key not in rows:
                rows[key] = {"lanes": lanes}
                order.append(key)
            rows[key][f] = f"{wr}, {mk}" + (f", {ref} refused" if ref != "0"
                                             else "")
    print("| function | row (specials.py's name) | lanes | " +
          " | ".join(f"{c}: wrong, marked" for c in cols) + " |")
    print("|---|---|---|" + "---|" * len(cols))
    for key in order:
        r = rows[key]
        print(f"| {key[0]} | {key[1]} | {r['lanes']} | " +
              " | ".join(r.get(c, "-") for c in cols) + " |")


def costs():
    cols = ("fp64", "fp128", "fp256")
    rows, order = {}, []
    for fmt in cols:
        try:
            t = open(f"costs.{fmt}.out.txt", encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"^(fp\d+) (\S+(?:, -?\d+\))?)\s+instructions "
                             r"([\d/]+) \(rne/rtz/rdn/rup/rmm\); words (\d+); "
                             r"live ([\d/]+) scheduled, (\d+) in the design's "
                             r"order", t, re.M):
            f, tag, ins, words, live, live0 = m.groups()
            if tag not in rows:
                rows[tag] = {}
                order.append(tag)
            i = ins.split("/")
            lv = live.split("/")
            lo, hi = min(i, key=int), max(i, key=int)
            rows[tag][f] = (f"{lo} to {hi}" if lo != hi else lo,
                            words, max(lv, key=int), live0)
    print("| fragment | fp64 | fp128 | fp256 | words (fp64 / fp128 / fp256) "
          "| most live, scheduled (design's order) |")
    # instructions: the least and the most over the five attributes
    print("|---|---|---|---|---|---|")
    for tag in order:
        r = rows[tag]
        ins = " | ".join(r[c][0] if c in r else "-" for c in cols)
        words = " / ".join(r[c][1] if c in r else "-" for c in cols)
        lives = sorted({(r[c][2], r[c][3]) for c in cols if c in r})
        live = ", ".join(f"{a} ({b})" for a, b in lives)
        print(f"| {tag} | {ins} | {words} | {live} |")


def share():
    cols = ("fp64", "fp128", "fp256")
    rows, order = {}, []
    for fmt in cols:
        try:
            t = open(f"share.{fmt}.out.txt", encoding="utf-8").read()
        except OSError:
            continue
        for m in re.finditer(r"^  with (.*): (\d+) shared; together (\d+) "
                             r"against (\d+) apart", t, re.M):
            name, sh, tog, apart = m.groups()
            if name not in rows:
                rows[name] = {}
                order.append(name)
            rows[name][fmt] = f"{sh}, {tog} ({apart})"
        for m in re.finditer(r"^  (pown\(x, 5\) against pown\(x, 3\)): (\d+) "
                             r"shared of \d+; together (\d+) against (\d+) "
                             r"apart", t, re.M):
            name, sh, tog, apart = m.groups()
            if name not in rows:
                rows[name] = {}
                order.append(name)
            rows[name][fmt] = f"{sh}, {tog} ({apart})"
    print("| pow(x, y) with ... | " + " | ".join(
        f"{c}: shared, together (apart)" for c in cols) + " |")
    print("|---|" + "---|" * len(cols))
    for name in order:
        print(f"| {name} | " + " | ".join(rows[name].get(c, "-")
                                          for c in cols) + " |")


if __name__ == "__main__":
    {"budget": budget, "pools": pools, "regions": regions,
     "onseq": onseq, "specials": specials, "costs": costs,
     "share": share}[sys.argv[1]]()
