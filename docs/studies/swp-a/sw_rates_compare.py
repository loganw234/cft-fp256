# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""sw_rates_compare.py - the soak jobs' rate on the software backend (sw_rates.out, this
desktop's CPU) against the stress run's per-job rate on the card (the quad's median,
stress-final-item-rates.txt), job by job.

What it tests (parcel SC, "what bounds each item's rate"):

  HOST items are libcft host code (host/src/clause5.c: "the device argument is context"),
  so a soak of them on the card does the same work as a soak on the software backend, and
  the two rates should differ by the CPU, the run's load and noise alone. Expectation: the
  software/card ratio of every host job lies in [0.5, 2.5]. (HONESTY: this band was set after
  the raw software rates in sw_rates.out had been seen, and before their ratios to the card's
  were computed; it is wide on purpose, and a band fitted to the data would prove nothing.)

  TILE items (div, sqrt, rint, scaleb) run composed passes on the device; the software
  backend runs the same passes in C softfloat, a different computation. If the tile does the
  work, the card is faster: the software/card ratio of every tile job is below 0.5.

The two machines differ (this desktop: a 12th-gen Core i5; the box: not recorded in the
stress record), each ratio rests on one short run, and nothing here separates a CPU's speed
from noise, so the bands are wide. The script prints every ratio and exits nonzero if a band
fails. usage: python sw_rates_compare.py [--sw FILE] [--rates FILE] [--controls]
"""
import os
import re
import statistics
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SW = os.path.join(HERE, "sw_rates.out")
RATES = os.path.join(HERE, "stress-final-item-rates.txt")

TILE = ("div32", "div64", "sqrt64", "sqrt32", "rint64", "rint32", "scaleb32", "scaleb64")
HOST_BAND = (0.5, 2.5)
TILE_MAX = 0.5

fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-82s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


def read_sw(path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            m = re.match(r"^RATE (\S+)\s+.*rate=(\d+) rc=(\d+)$", ln.strip())
            if m:
                out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return out


def read_card(path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        next(fh)
        for ln in fh:
            f = ln.split()
            if f[1] == "quad":
                out[f[0]] = (int(f[6]), int(f[7]))     # count rate, cases rate
    return out


def family(job):
    return re.sub(r"-(rne|rtz|rdn|rup|rmm)$", "", job)


def main(sw_path, rates_path):
    sw = read_sw(sw_path)
    card = read_card(rates_path)
    print("sw_rates_compare.py: the software backend (one core of this desktop) against the card run's per-job medians")
    print()
    check("24 jobs were measured on the software backend (18 random, 6 exhaustive)", len(sw) == 24, "(%d)" % len(sw))
    check("every job exited 0", all(rc == 0 for _, rc in sw.values()))
    exhaustive = ("sqrt32-rne", "rint32-rne", "nextup32", "nextdown32", "logb32", "class32")
    rows = []
    for job, (rate, rc) in sorted(sw.items()):
        c = card.get(job)
        if c is None:
            check("job %s has a card rate" % job, False)
            continue
        card_rate = c[1] if job in exhaustive else c[0]
        kind = "tile" if family(job) in TILE else "host"
        rows.append((kind, job, rate, card_rate, rate / card_rate))
    print("   %-5s %-15s %12s %12s %9s" % ("kind", "job", "sw M/s", "card M/s", "sw/card"))
    for kind, job, rate, card_rate, ratio in sorted(rows):
        print("   %-5s %-15s %12.3f %12.3f %9.3f" % (kind, job, rate / 1e6, card_rate / 1e6, ratio))
    host = [r for r in rows if r[0] == "host"]
    tile = [r for r in rows if r[0] == "tile"]
    print()
    print("   host jobs: median ratio %.2f, min %.2f, max %.2f (%d jobs)" % (
        statistics.median(r[4] for r in host), min(r[4] for r in host), max(r[4] for r in host), len(host)))
    print("   tile jobs: median ratio %.2f, min %.2f, max %.2f (%d jobs); the card is %.1f to %.1f times faster" % (
        statistics.median(r[4] for r in tile), min(r[4] for r in tile), max(r[4] for r in tile), len(tile),
        1 / max(r[4] for r in tile), 1 / min(r[4] for r in tile)))
    print()
    bad = [(r[1], round(r[4], 2)) for r in host if not (HOST_BAND[0] <= r[4] <= HOST_BAND[1])]
    check("every host job's software/card ratio lies in [%.1f, %.1f]" % HOST_BAND, not bad, str(bad))
    bad = [(r[1], round(r[4], 2)) for r in tile if r[4] >= TILE_MAX]
    check("every tile job's software/card ratio is below %.1f (the card is at least 2x faster)" % TILE_MAX, not bad, str(bad))
    check("the 24 jobs split into 16 host jobs and 8 tile jobs (6 random + sqrt32-rne, rint32-rne)",
          (len(host), len(tile)) == (16, 8), "(%d host, %d tile)" % (len(host), len(tile)))
    print()
    print("sw_rates_compare: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


def controls():
    """Tampered copies of the software rates, each of which must turn the right band red."""
    with open(SW, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    tmp = tempfile.mkdtemp(prefix="swp_a_sw_")
    bad = 0

    def run(label, mutated, expect):
        nonlocal bad
        path = os.path.join(tmp, "sw.out")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(mutated) + "\n")
        p = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), "--sw", path], capture_output=True, text=True)
        failed = [l for l in p.stdout.splitlines() if l.startswith("CHECK") and "FAILED" in l]
        hit = [l for l in failed if expect in l]
        ok = p.returncode == 1 and bool(hit)
        print("CONTROL %-62s %s" % (label, "red at the check written for it" if ok else "NOT CAUGHT  FAILED"))
        for l in (hit or failed)[:1]:
            print("        " + l[:160])
        if not ok:
            bad += 1

    def edit(job, fn):
        out = []
        for ln in lines:
            m = re.match(r"^(RATE %s\s+.*rate=)(\d+)( rc=\d+)$" % re.escape(job), ln)
            if m:
                ln = m.group(1) + str(fn(int(m.group(2)))) + m.group(3)
            out.append(ln)
        return out

    run("D1 class64's software rate cut to 1% (a host job 100x off)", edit("class64", lambda v: v // 100), "host job's software/card ratio")
    run("D2 div32's software rate raised 20x (a tile job no slower than the card)", edit("div32-rne", lambda v: v * 20), "tile job's software/card ratio")
    run("D3 a job missing", [l for l in lines if not l.startswith("RATE rem64 ")], "24 jobs were measured")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if bad:
        print("sw_rates_compare controls: %d NOT CAUGHT" % bad)
        return 1
    print("sw_rates_compare controls: all three tampered inputs were caught at their checks")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    sw_path, rates_path = SW, RATES
    do_controls = False
    while args:
        a = args.pop(0)
        if a == "--sw":
            sw_path = args.pop(0)
        elif a == "--rates":
            rates_path = args.pop(0)
        elif a == "--controls":
            do_controls = True
        else:
            print(__doc__)
            sys.exit(2)
    sys.exit(controls() if do_controls else main(sw_path, rates_path))
