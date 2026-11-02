#!/usr/bin/env python3
"""Print the pin table of host/tools/mpfr_check.c from runs of the tool.

mpfr_check.c pins the cases its `extras` phase asks, per family and per
format, under `mpfr-check 24 7`.  Whoever changes a pool, a family or the
extras' dedupe changes those counts and updates the pins in the same
commit; this is how to read the new ones off a run.

Run from the repository's root.  Give it the output of one run of the
extras at every format, or of one run per format; it sums the table that
each run ends with, so both work:

    cd host
    CFT_MPFR_PHASES=extras ./mpfr-check 24 7 > /tmp/extras.txt
    cd ..
    python host/tools/audit-pools/pins.py /tmp/extras.txt

and prints the lines to paste between the braces of XPIN in
mpfr_check.c, then the four per-format totals for XPIN_FORMAT.  With
--check it compares the table of the runs with the pins that
mpfr_check.c holds now and says which differ (exit 1), so that a change
to the pins can be reviewed without a build.

Python 3.8 or later; no library beyond the standard one.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE = os.path.join(HERE, "..", "mpfr_check.c")
FORMATS = ("fp32", "fp64", "fp128", "fp256")
CELL = re.compile(r"(\d+)-\s*(\d+)=\s*(\d+)/(\d+)")


def read_tables(paths):
    """{family: [cases at fp32, fp64, fp128, fp256]}, in first-seen order,
    summed over the files."""
    fam = {}
    for path in paths:
        in_table = False
        with open(path, errors="replace") as fh:
            for line in fh:
                if line.startswith("extras (audit of"):
                    in_table = True
                    continue
                if not in_table:
                    continue
                if line.startswith("  extras total"):
                    in_table = False
                    continue
                m = re.match(r"^  (\S+)\s", line)
                cells = CELL.findall(line)
                if not m or len(cells) != 4 or m.group(1) == "family":
                    continue
                row = fam.setdefault(m.group(1), [0, 0, 0, 0])
                for k in range(4):
                    row[k] += int(cells[k][3])
    return fam


def read_pins(source):
    """The pins mpfr_check.c holds: ({family: [4 counts]}, [4 totals])."""
    with open(source, errors="replace") as fh:
        text = fh.read()
    a = text.index("XPIN[] = {")
    b = text.index("\n};", a)
    fam = {}
    for m in re.finditer(r'\{\s*"([^"]+)",\s*\{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)\s*\}\s*\}',
                         text[a:b]):
        fam[m.group(1)] = [int(x) for x in m.groups()[1:]]
    t = re.search(r"XPIN_FORMAT\[4\] = \{\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)", text)
    return fam, [int(x) for x in t.groups()]


def main(argv):
    check = "--check" in argv
    paths = [a for a in argv[1:] if not a.startswith("--")]
    if not paths:
        sys.stderr.write(__doc__)
        return 2
    fam = read_tables(paths)
    if not fam:
        sys.stderr.write("pins.py: no extras table in %s\n" % ", ".join(paths))
        return 2
    totals = [sum(r[k] for r in fam.values()) for k in range(4)]
    if not check:
        for name, r in fam.items():
            print('    { %-26s { %s } },' % ('"%s",' % name,
                                             ", ".join("%d" % x for x in r)))
        print("")
        print("XPIN_FORMAT: %s   (%d in all)" % (
            ", ".join("%d" % x for x in totals), sum(totals)))
        return 0
    held, held_tot = read_pins(SOURCE)
    bad = 0
    for name in sorted(set(fam) | set(held)):
        a, b = fam.get(name, [0] * 4), held.get(name, [0] * 4)
        for k in range(4):
            if a[k] != b[k]:
                bad += 1
                print("%s %s: the run has %d, the pin %d" % (FORMATS[k], name, a[k], b[k]))
    for k in range(4):
        if totals[k] != held_tot[k]:
            bad += 1
            print("%s total: the run has %d, the pin %d" % (FORMATS[k], totals[k], held_tot[k]))
    print("pins.py: %d difference(s)" % bad)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
