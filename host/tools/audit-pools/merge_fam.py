"""merge_fam.py: part of the pool audit; see docs/TRANSCENDENTALS.md.

Usage, from the repository's root:

    python -B host/tools/audit-pools/merge_fam.py PREFIX [plain]

PREFIX_fp32.txt ... PREFIX_fp256.txt are the outputs of
CFT_MPFR_PHASES=extras CFT_MPFR_FORMATS=<format> ./mpfr-check 24 7, one per
format.  Merges the four family tables into one.
"""
import re, sys, collections
pref = sys.argv[1]
FM = ["fp32", "fp64", "fp128", "fp256"]
rows = collections.OrderedDict()
tot = {f: 0 for f in FM}
for k, f in enumerate(FM):
    for line in open("%s_%s.txt" % (pref, f)):
        m = re.match(r"^  (\S+)\s+(.*)$", line)
        g = re.findall(r"(\d+)-\s*(\d+)=\s*(\d+)/(\d+)", line)
        if m and len(g) == 4:
            name = m.group(1)
            rows.setdefault(name, {})[f] = tuple(int(x) for x in g[k])
        mt = re.match(r"^  extras total: (\d+) cases", line)
        if mt:
            tot[f] = int(mt.group(1))
mode = sys.argv[2] if len(sys.argv) > 2 else "plain"
print("%-22s %s" % ("family", " ".join("%-26s" % ("%s intended-held=added/cases" % f) for f in FM)) if mode == "plain" else "")
for name, d in rows.items():
    cells = []
    for f in FM:
        i, h, a, c = d.get(f, (0, 0, 0, 0))
        cells.append("%4d-%3d=%4d/%-7d" % (i, h, a, c))
    print("%-22s %s" % (name, "  ".join(cells)))
print("totals:", tot, "sum", sum(tot.values()))
