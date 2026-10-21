#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""What the lead's box scripts each do, counted: the skeleton a scheduler would hold once.

    python -B -I script_census.py DIR [--controls]

DIR is a directory of the lead's scripts for amd-arc-box (box_*.sh and copy_wave9.sh); they are the lead's, read
here and never changed or run, and the output names each by its file name only. For every script it asks, by
a pattern, whether the script does each thing a run on the box needs done and recorded (a summary file
ending "=== done", a refusal when its output exists, a guard against other card users, a clone from a bundle,
the assertions of HEAD, a clean status, the rtl/ tree and a string from each change, a build with XRT=1 and
the ldd check, XRT's environment, nice, the sha256 of what it ran). The totals are the number of scripts
that each have it; the guard line lists the guard's pattern of every script that has a `pgrep` guard, since
a guard written eleven times is eleven guards.

Every feature's pattern is tried on a line that must match and a line that must not (the CONTROL lines),
and the totals are held to the rows (a CHECK). A pattern that matched a comment is counted: a script that
merely mentions a thing in a comment is not told apart from one that does it, and the count says "mentions
or does" for that reason (BELIEVED small: the scripts' comments are headers of a few lines).

The output is written with LF line ends on every platform (Windows Python would write CRLF to a redirected stdout), so the
capture beside this script is LF and compares equal as it stands.

Python 3.10 or later; standard library only. Prints no path.
"""
import glob
import os
import re
import sys

FEATURES = [
    # (column, what it asks, pattern, a line that must match, a line that must not)
    ("say", "defines say() and writes a dated summary", r"^say\(\)", 'say() { echo "$(date) x: $*" >> $S; }', "# say it"),
    ("done", 'ends the summary with "=== done"', r"=== done", 'done_() { echo "=== done" >> $S; }', "done_ 1"),
    ("refuse", "refuses when its output already exists", r"REFUSED, .*exists|refused: .* exists", 'say "REFUSED, $p exists"', "say REFUSED nothing"),
    ("pgrep", "guards with pgrep -f on a pattern", r"pgrep -[a-z]*f[a-z]* ", "n=$(pgrep -fc 'a|b')", "pkill nothing"),
    ("status", "guards on the run's status.txt and a PID", r'grep -q "\^state', 'grep -q "^state *RUNNING" status.txt', "grep -q ready"),
    ("clone", "clones from a bundle", r"git clone -q \$W/bundles/", "git clone -q $W/bundles/$BUNDLE $D", "git clone -q https://x"),
    ("head", "asserts HEAD", r"rev-parse HEAD(?!:)", "h=$(git -C $D rev-parse HEAD)", "rev-parse HEAD:rtl is another"),
    ("clean", "asserts a clean status", r"status --porcelain", "git -C $D status --porcelain | wc -l", "git status"),
    ("rtl", "asserts the rtl/ tree hash", r"rev-parse HEAD:rtl", "r=$(git -C $D rev-parse HEAD:rtl)", "rev-parse HEAD"),
    ("content", "greps the clone for a string of each change", r"grep -c ['\"]", "n1=$(grep -c 'check_tree' $D/hw/x.py)", "grep -q x"),
    ("xrt1", "builds with XRT=1", r"XRT=1", "make -C host XRT=1 XRT_ROOT=/opt/xilinx/xrt", "make -C host all"),
    ("ldd", "checks the tools' ldd for xrt", r"ldd ", "x=$(ldd $D/host/clause5-soak | grep -c xrt)", "# the old ldd"),
    ("xrtenv", "sources XRT's environment", r"source /opt/xilinx/xrt/setup\.sh", "source /opt/xilinx/xrt/setup.sh > /dev/null", "source ~/.bashrc"),
    ("nice", "runs its work niced", r"nice -n 10", "nice -n 10 make vectors", "nice make"),
    ("sums", "records a sha256", r"sha256sum", "sha256sum $M/metrics.jsonl", "# sha256"),
    ("sleep", "waits for a start time", r"sleep \$\(\(", "sleep $(( ts - now ))", "sleep 5"),
]
PGREP_ARG = re.compile(r"pgrep -[a-z]*f[a-z]* '([^']*)'")


def read_scripts(directory):
    names = sorted(glob.glob(os.path.join(directory, "box_*.sh")) + glob.glob(os.path.join(directory, "copy_*.sh")))
    out = []
    for p in names:
        with open(p, "r", encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read()
        out.append((os.path.basename(p), text))
    return out


def census(scripts):
    rows = []
    for name, text in scripts:
        lines = text.split("\n")
        feats = {}
        for col, _, pat, _, _ in FEATURES:
            feats[col] = len(re.findall(pat, text, re.M)) > 0
        guards = PGREP_ARG.findall(text)
        rows.append({"name": name, "lines": len([ln for ln in lines if ln.strip() != ""]), "feats": feats, "guards": guards})
    return rows


def main(argv):
    try:
        sys.stdout.reconfigure(newline="\n")      # LF on every platform, so a capture is the same bytes everywhere
    except (AttributeError, ValueError):
        pass
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        return 64
    scripts = read_scripts(args[0])
    rows = census(scripts)
    ok = True
    cols = [f[0] for f in FEATURES]
    print(("%-24s %5s  %s" % ("script", "lines", " ".join("%-7s" % c for c in cols))).rstrip())
    for r in rows:
        print(("%-24s %5d  %s" % (r["name"], r["lines"], " ".join("%-7s" % ("x" if r["feats"][c] else ".") for c in cols))).rstrip())
    totals = {c: sum(1 for r in rows if r["feats"][c]) for c in cols}
    print(("%-24s %5d  %s" % ("scripts with it (of %d)" % len(rows), sum(r["lines"] for r in rows), " ".join("%-7d" % totals[c] for c in cols))).rstrip())
    print()
    for col, what, _, _, _ in FEATURES:
        print("  %-8s %2d of %d  %s (mentions or does)" % (col, totals[col], len(rows), what))
    print()
    gset = {}
    for r in rows:
        for g in r["guards"]:
            gset.setdefault(g, []).append(r["name"])
    print("pgrep guards: %d scripts have one, with %d distinct patterns:" % (sum(1 for r in rows if r["guards"]), len(gset)))
    for g, names in sorted(gset.items(), key=lambda kv: -len(kv[1])):
        print("  %d script(s): %s" % (len(names), g))
        print("      %s" % ", ".join(names))
    allpats = set()
    for g in gset:
        allpats.update(g.split("|"))
    print("the patterns' words together: %d; each guard lacks, of them: %s" % (
        len(allpats), "; ".join("%d" % len(allpats - set(g.split("|"))) for g in sorted(gset))))
    guards_none = [r["name"] for r in rows if not r["guards"] and not r["feats"]["status"]]
    print("no guard of either kind: %d scripts: %s" % (len(guards_none), ", ".join(guards_none)))
    print()
    # the checks
    good = len(rows) > 0 and all(r["lines"] > 0 for r in rows)
    print("CHECK %-4s %d scripts were read, none empty" % ("ok" if good else "FAIL", len(rows)))
    ok = ok and good
    good = all(totals[c] == sum(1 for r in rows if r["feats"][c]) for c in cols)
    print("CHECK %-4s every total equals the number of rows that have the feature" % ("ok" if good else "FAIL"))
    ok = ok and good
    good = all(len(re.findall(p, m, re.M)) > 0 and len(re.findall(p, n, re.M)) == 0 for _, _, p, m, n in FEATURES)
    print("CHECK %-4s every feature's pattern matches its own positive line and not its negative line (%d patterns)" % ("ok" if good else "FAIL", len(FEATURES)))
    ok = ok and good
    if "--controls" in argv:
        # a broken pattern must be seen: replace the clone pattern by one that can never match and the control line must fail
        broken = [(c, w, r"never-matches-anything-\d\d\d", m, n) for c, w, p, m, n in FEATURES]
        red = not all(len(re.findall(p, m, re.M)) > 0 and len(re.findall(p, n, re.M)) == 0 for _, _, p, m, n in broken)
        print("CONTROL %-4s a pattern that cannot match makes the positive-line check go red, as it must" % ("ok" if red else "FAIL"))
        ok = ok and red
        mangled = [(n, t.replace("pgrep", "pg_rep")) for n, t in scripts]
        t2 = {c: sum(1 for r in census(mangled) if r["feats"][c]) for c in cols}
        red2 = t2["pgrep"] == 0 and totals["pgrep"] > 0
        print("CONTROL %-4s with every `pgrep` renamed the census finds none (it found %d): the count follows the text" % ("ok" if red2 else "FAIL", totals["pgrep"]))
        ok = ok and red2
    print("script_census: %s" % ("every check held" if ok else "A CHECK FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
