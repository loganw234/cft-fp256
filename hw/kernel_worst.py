#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The kernel clock's worst setup path in a Vivado timing summary, cell by cell.

    python3 hw/kernel_worst.py <timing_summary.rpt | .rpt.gz> [...]

The kernel clock is found BY NAME - clk_out1_ulp_clk_wiz_0 on the U50
shell, or KERNEL_CLK, as for hw/rebuild-2022.sh - because the first "Max
Delay Paths" block in these reports belongs to whichever clock Vivado
prints first, and on this shell that is a PCIe or HBM clock with nothing
to do with the kernel (docs/VALIDATION.md, 2026-09-15).

For each report: the clock's setup WNS and failing endpoints, then its
worst path - slack, source, destination, data path delay, logic levels -
and each RAM, DSP, LUT, CARRY, MUX and flop along it. hw/sweep_freq.sh
runs it on every point, so a sweep says where the wall is as well as
whether the clock closed. Exit 1 if any report lacks the clock's section.
"""
import gzip
import os
import re
import sys

K = os.environ.get("KERNEL_CLK", "clk_out1_ulp_clk_wiz_0")
CELL = re.compile(r"^\s+\S+\s+(RAMB\w+|DSP_\w+|DSP48\w*|LUT\d|CARRY\d|MUXF\d|FD\w+)"
                  r"\s+\((?:Prop|Setup)_[^)]*\).*?(\S+)\s*$")


def read(path):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", errors="replace") as f:
        return f.read().splitlines()


def section(lines):
    """The clock's own From/To block: its summary lines and worst paths."""
    for i in range(len(lines) - 1):
        if lines[i].strip() == "From Clock:  " + K and lines[i + 1].strip() == "To Clock:  " + K:
            out = []
            for line in lines[i + 2:]:
                if line.startswith("From Clock:"):
                    break
                out.append(line)
            return "\n".join(out)
    return None


def field(pat, text):
    m = re.search(pat, text, re.S)
    return m.group(1).strip() if m else "?"


def main(paths):
    missing = 0
    for path in paths:
        sec = section(read(path))
        print("== " + path)
        if sec is None:
            print("   no section for %s" % K)
            missing += 1
            continue
        head = re.search(r"Setup :\s+(\d+)\s+Failing Endpoints,\s+Worst Slack\s+(-?[\d.]+)ns", sec)
        if head:
            print("   %s setup WNS %s ns, failing endpoints %s" % (K, head.group(2), head.group(1)))
        else:
            print("   %s: no setup summary line" % K)
        a = sec.find("Slack (")
        if a < 0:
            print("   no path listed")
            continue
        b = sec.find("Slack (", a + 10)
        p = sec[a:b if b > 0 else None]
        print("   slack %s  %s -> %s" % (field(r"Slack \(\w+\)\s*:\s*(\S+)", p),
                                        field(r"Source:\s+(\S+)", p), field(r"Destination:\s+(\S+)", p)))
        print("   data path " + field(r"Data Path Delay:\s+([^\n]+)", p))
        print("   levels    " + field(r"Logic Levels:\s+([^\n]+)", p))
        for line in p.splitlines():
            m = CELL.match(line)
            if m:
                print("      %-18s %s" % (m.group(1), m.group(2)[-90:]))
    return 1 if missing else 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__.strip().splitlines()[2].strip())
    sys.exit(main(sys.argv[1:]))
