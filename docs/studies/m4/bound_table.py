# M4 model: the bound cell by cell, from every output kept (scratch; the
# study's 3.2 and 3.3, after send-back 1): for each format, function and
# region, the desktop's budget (budget.*.out.txt, 1,000 or 300 lanes, seed
# 2), the box's (box-out/, 12,000 or 3,000 lanes, seeds 121 to 125; for
# atan2, whose fragment send-back 1 changed, box-out2/'s runs of both
# sizes), each with its second-order residual, and the largest measured
# |V - f| / Bv (measure.*.out.txt, seed 1; box-out2/'s for atan2). The cell's
# bound is the largest of them all, budgets with their residuals; its bits
# are log2 of 1 over it. Reads files only.
#
#   python bound_table.py [md]       (md: the study's table of bits)

import math
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
FMTS = (("fp64", "fp64"), ("fp128", "fp128"), ("fp256", "fp256"),
        ("fp32-dw18", "fp32 double word"))
FNS = ("atan", "asin", "acos", "atan2")
REGIONS = ("random", "edge", "big", "small", "diag")
BOUND = re.compile(r"THE BUDGET'S BOUND: M_max \+ capacities = ([0-9.e+-]+) Bv")
RESID = re.compile(r"second-order residual at most ([0-9.e+-]+) Bv")
WORST = re.compile(r"^(\S+) (\S+) rne (\S+) seed \d+: .*largest \|V - f\|/Bv 2\^(-?[0-9.]+)")


def budget(path):
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    b, r = BOUND.search(text), RESID.search(text)
    if not b:
        return None
    return float(b.group(1)), float(r.group(1)) if r else 0.0


def worsts(path):
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = WORST.match(line)
            if m:
                out[m.group(2)] = 2.0 ** float(m.group(4))
    return out


def main():
    import sys
    md = "md" in sys.argv[1:]
    bits = {}
    b2 = HERE / "box-out2"
    print("cell: desktop budget (+residual); box budget (+residual); worst "
          "measured; the cell's bound = the largest, budgets with residuals")
    for fmt, label in FMTS:
        for reg in REGIONS:
            wd = worsts(b2 / f"measure.{fmt}-{reg}.out.txt") or {}
            wd0 = worsts(HERE / f"measure.{fmt}-{reg}.out.txt")
            for fn in FNS:
                if fn == "atan" and reg == "diag":
                    continue
                if fn == "atan2" and b2.is_dir():
                    d = budget(b2 / f"budget.{fmt}-atan2-{reg}.out.txt")
                    x = budget(b2 / f"budget-box-{fmt}-atan2-{reg}.out.txt")
                    w = wd.get(fn)
                else:
                    d = budget(HERE / f"budget.{fmt}-{fn}-{reg}.out.txt")
                    x = budget(HERE / "box-out" / f"budget-{fmt}-{fn}-{reg}.out.txt")
                    w = wd0.get(fn)
                cands = [v for v in ((d[0] + d[1]) if d else None,
                                     (x[0] + x[1]) if x else None, w) if v]
                top = max(cands) if cands else None

                bits[(label, fn, reg)] = math.log2(1 / top) if top else None
                if md:
                    continue

                def show(t):
                    return f"{t[0]:.4g} (+{t[1]:.2g})" if t else "-"
                print(f"{label} {fn} {reg}: {show(d)}; {show(x)}; "
                      f"{w:.3g}" if w else f"{label} {fn} {reg}: {show(d)}; {show(x)}; -",
                      end="")
                print(f"; bound {top:.4g} Bv, {math.log2(1 / top):.2f} bits"
                      if top else "; bound -")
    if md:
        print("| bits kept (the cell's figure) | random | edge | big | small | diag |")
        print("|---|---|---|---|---|---|")
        for _fmt, label in FMTS:
            for fn in FNS:
                row = []
                for reg in REGIONS:
                    v = bits.get((label, fn, reg))
                    row.append("-" if v is None else
                               (f"{v:.2f}" if v < 20 else f"{v:.0f}"))
                print(f"| {label} {fn} | " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
