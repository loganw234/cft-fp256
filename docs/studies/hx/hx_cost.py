#!/usr/bin/env python3
"""hx_cost.py - parcel HX: the card's rates at fp64, fp128 and fp256 as the probe measured them, and every candidate
item's card time and the campaign's nights (scratch beside docs/studies/HX-wide-sweeps.md, sections 5 and 7; nothing
in the tree imports it). Standard library only; reads box-out/ beside it.

  C1  the probe's rates (box-out/probe-tile1.txt: tile 1 alone; probe-quad-t1..t4.txt: four tiles at once), MEASURED
      on amd-arc-box by the lead on 2026-10-26 with docs/studies/hx/hx_probe.c (box-out/hx-probe-summary.txt)
  C2  a two-term model of a divide and a square root, t = h + L T64 (L = 1, 2, 4 for fp64, fp128, fp256: the beat's
      lanes 4, 2, 1), fitted on fp64 and fp128 and held to fp256
  C3  what one night gives the sweep, from nightly-1024's record (COMPUTED by the study from metrics.jsonl, which is
      outside the tree; the constants are below with their source)
  C4  every candidate item's tile-hours (space x cases an index / rate, each attribute), and its class: L1 over a
      stated space, hard, or L2 class
  C5  phase 1 (the study's section 7) in tile-hours and in nights; the checks fail the exit status

usage: python hx_cost.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "box-out")
FAILS = []


def check(name, ok, detail=""):
    print("CHECK %-84s %s%s" % (name, "ok" if ok else "FAILED", (": " + detail) if detail else ""))
    if not ok:
        FAILS.append(name)


LINE = re.compile(r"^hx-probe (fp\d+) (\w+): N 4096, calls (\d+), ([0-9.]+) ns an element, ([0-9.]+) M/s, "
                  r"check (\d+) of 4096 equal, flags device 0x([0-9a-f]+) software 0x([0-9a-f]+)$", re.M)


def rates(path):
    text = open(path, encoding="utf-8").read()
    out = {}
    for m in LINE.finditer(text):
        if int(m.group(6)) != 4096 or m.group(7) != m.group(8):
            raise SystemExit("%s: a row whose check was not equal: %s" % (path, m.group(0)))
        out[(m.group(1), m.group(2))] = float(m.group(5)) * 1e6
    if len(out) != 21 or "every check equal" not in text:
        raise SystemExit("%s: %d rows, or no 'every check equal' line" % (path, len(out)))
    return out


# C3's constants: COMPUTED on 2026-10-26 from Data/runs/2026-10-12-math-round/box/nightly-1024/run/metrics.jsonl (the lead's
# copy, 12,138,283 bytes): passing legs' duration_s summed by kind and image, and the six run_start/run_end pairs
ON_CARD_S = 401752               # report.txt, "on the card"
SWEEP_JOB_S = {"quad": 699441, "single": 20763, "deep": 18874}   # sweep legs' job-seconds (cpu 16,321: the host pool)
RUN_HOURS = (12.40, 12.09, 13.33, 13.25, 13.20, 47.44)           # the six runs: five weekday nights, then 2026-10-24's weekend
EXH_WEIGHT = 0.75                # docs/CARDDAY.md: "exhaustive items outweigh random ones 3 to 1 (--sweep-weights)"
EXH = 1 << 32


def main():
    t1 = rates(os.path.join(OUT, "probe-tile1.txt"))
    quad = [rates(os.path.join(OUT, "probe-quad-t%d.txt" % t)) for t in (1, 2, 3, 4)]
    fmts, ops = ("fp64", "fp128", "fp256"), ("div", "sqrt", "rint", "scaleb", "fma", "mul", "add")
    print("== C1. the card's rates, M elements a second a tile (one call of 4,096, RNE; MEASURED by the probe)")
    print("  %-7s %-6s %10s %22s %12s" % ("op", "format", "tile alone", "four at once (min-max)", "quad, sum"))
    lo_r, hi_r = 9.0, 0.0
    for op in ops:
        for f in fmts:
            q = [r[(f, op)] for r in quad]
            print("  %-7s %-6s %10.3f %12.3f - %-7.3f %12.3f" % (op, f, t1[(f, op)] / 1e6, min(q) / 1e6, max(q) / 1e6,
                                                                sum(q) / 1e6))
            lo_r, hi_r = min(lo_r, min(q) / t1[(f, op)]), max(hi_r, max(q) / t1[(f, op)])
    print("  four tiles at once: each tile at %.2f to %.2f times tile 1 alone's rate" % (lo_r, hi_r))
    check("C1: no tile of the four-at-once run is below 85% of tile 1 alone (the quad scales by four)",
          all(r[k] >= 0.85 * t1[k] for r in quad for k in t1))

    print("\n== C2. t = h + L T64 (ns an element), fitted on fp64 and fp128, held to fp256")
    for op in ("div", "sqrt", "rint"):
        t64, t128, t256 = (1e9 / t1[(f, op)] for f in fmts)
        T = t128 - t64
        h = t64 - T
        pred = h + 4 * T
        print("  %-5s fp64 %7.1f  fp128 %7.1f  fp256 %7.1f  ->  h %6.1f, T64 %6.1f; fp256 predicted %7.1f (%+.1f%%)"
              % (op, t64, t128, t256, h, T, pred, 100 * (pred / t256 - 1)))
        if op in ("div", "sqrt"):
            check("C2: %s's fp256 time within 5%% of h + 4 T64 (the tile part scales with the beat's lanes)" % op,
                  abs(pred / t256 - 1) < 0.05)

    print("\n== C3. a night's sweep (COMPUTED from nightly-1024's record; constants in this file)")
    per = sum(SWEEP_JOB_S.values()) / ON_CARD_S
    week = sum(RUN_HOURS[:5]) / 5
    wkd = week * per
    wke = (62.0 - 0.6) * per
    two = 8 * wkd + 2 * wke
    print("  sweep tile-seconds a card-second: %.3f (quad %d, single %d, deep %d job-seconds over %d s on the card)"
          % (per, SWEEP_JOB_S["quad"], SWEEP_JOB_S["single"], SWEEP_JOB_S["deep"], ON_CARD_S))
    print("  a weekday night: %.2f h on the card (the mean of five) = %.1f sweep tile-hours" % (week, wkd))
    print("  a weekend (Friday 18:00 to Monday 08:00, 61.4 h on the card, ESTIMATE): %.1f sweep tile-hours" % wke)
    print("  two weeks (8 weekday nights and 2 weekends): %.0f sweep tile-hours; at the exhaustive weight %.2f: %.0f"
          % (two, EXH_WEIGHT, two * EXH_WEIGHT))

    print("\n== C4. the candidate items: tile-hours a run of every attribute listed (rates from C1, tile 1 alone)")
    r = lambda f, op: t1[(f, op)]
    # the hard-case spaces (hardcases.py's families; hx_spaces.py S2 prints them): indices, cases an index from
    # HARD_WHOLE at fp64 (div 812,489,184 / 289,685,696; sqrt 1,745,752 / 4,456,448), and the fp64 mode's efficiency
    # against the bare call (div64-hard@quad 440,237 indices/s x 2.805 against the probe's fp64 div: COMPUTED below)
    div_ci, sqrt_ci = 812489184 / 289685696, 1745752 / 4456448
    eff_div = 440237 * div_ci / r("fp64", "div")
    eff_sqrt = 895453 * sqrt_ci / r("fp64", "sqrt")
    print("  the fp64 hard modes against the bare call (nightly-1024 status.txt rates): div %.2f, sqrt %.2f" % (eff_div, eff_sqrt))

    def div_space(bias, nk):
        return 4 * 24 + 4 * (4 * bias - 1) + (4 << 16) + (4 << 20) + 2 * (4 << 21) + 4 * nk
    hard_idx = {"fp128": div_space(16383, 1 << 26) - 4 * 24 + 4 * 113, "fp256": div_space(262143, 1 << 26) - 4 * 24 + 4 * 237}
    # class-level items: hx_spaces.py S1's indices (the tree's enumerators at the wide formats); the rate a CASE is the
    # fp64 class modes' (nightly-1024: rint64-class 240 indices/s x 4 lanes, scaleb64-class 2,852 x 4): one call a case,
    # so the per-call cost, not the format, sets it (ESTIMATE)
    cls = {"rint128-class": (137344, 2, 240 * 4), "rint256-class": (537600, 1, 240 * 4),
           "scaleb128-class": (None, 2, 2852 * 4), "scaleb256-class": (None, 1, 2852 * 4)}
    items = []

    def add(name, level, space, per_index, rate, attrs, note):
        hours = space * per_index / rate / 3600 * attrs
        items.append((name, level, space, per_index, rate, attrs, hours, note))

    for f in fmts:
        add("sqrt%s-f32" % f[2:], "L1", EXH, 1, r(f, "sqrt"), 5, "every fp32 input, widened")
        add("recip%s-f32" % f[2:], "L1", EXH, 1, r(f, "div"), 5, "1/x, every fp32 x")
    for f in ("fp128", "fp256"):
        add("rint%s-f32" % f[2:], "L1", EXH, 2, r(f, "rint"), 5, "both variants; exact identity")
    for f in ("fp128", "fp256"):
        add("div%s-hard" % f[2:], "hard", hard_idx[f], div_ci, r(f, "div") * eff_div, 5, "F3a..F0K as div64-hard")
        add("sqrt%s-hard" % f[2:], "hard", 4456448, sqrt_ci, r(f, "sqrt") * eff_sqrt, 5, "S1, S0 as sqrt64-hard")
    add("div64-hard-w128", "hard", 289685696, div_ci, r("fp128", "div") * eff_div, 5, "div64-hard's operands at fp128")
    add("div64-hard-w256", "hard", 289685696, div_ci, r("fp256", "div") * eff_div, 5, "div64-hard's operands at fp256")
    sizes = {}
    if os.path.isfile(os.path.join(HERE, "hx_spaces.out")):
        txt = open(os.path.join(HERE, "hx_spaces.out"), encoding="utf-8").read()
        for key, label in (("scaleb128-class", "scaleb, fp128"), ("scaleb256-class", "scaleb, fp256"),
                           ("rint128-class", "rint, fp128"), ("rint256-class", "rint, fp256")):
            m = re.search(r"^  %s\s+tile\s+(\d+)" % re.escape(label), txt, re.M)
            if m:
                sizes[key] = int(m.group(1))
    for key, (n, k, rate) in cls.items():
        n = sizes.get(key, n)
        if n is None:
            print("  %s: no size (run hx_spaces.py first)" % key)
            continue
        add(key, "L2", n, k, rate, 5 if key.startswith("rint") else 4, "one call a case (ESTIMATE rate)")
    for f in ("fp128", "fp256"):
        add("sqrt%s-win" % f[2:], "L1", EXH, 1, r(f, "sqrt"), 2, "one low-32-bit window, rne and rup")
        add("recip%s-win" % f[2:], "L1", EXH, 1, r(f, "div"), 2, "one low-32-bit window, rne and rup")
        add("sqrt%s-f64top" % f[2:], "L1", EXH, 1, r(f, "sqrt"), 5, "fp64 inputs, low 32 fraction bits zero")
    print("  %-17s %-5s %13s %6s %10s %5s %10s  %s" % ("item", "level", "indices", "k", "M/s", "attrs", "tile-h", "what"))
    for name, level, space, k, rate, attrs, hours, note in items:
        print("  %-17s %-5s %13d %6.3f %10.3f %5d %10.2f  %s" % (name, level, space, k, rate / 1e6, attrs, hours, note))
    byname = {it[0]: it for it in items}

    print("\n== C5. phase 1 (section 7): the items, their tile-hours, and nights")
    phase1 = ["div128-hard", "div256-hard", "sqrt128-hard", "sqrt256-hard", "div64-hard-w128", "div64-hard-w256",
              "rint128-class", "rint256-class", "scaleb128-class", "scaleb256-class",
              "sqrt64-f32", "sqrt128-f32", "sqrt256-f32", "recip64-f32", "recip128-f32", "recip256-f32",
              "rint128-f32", "rint256-f32"]
    windows = [("sqrt128-win", 4), ("sqrt256-win", 4), ("recip128-win", 4), ("recip256-win", 4)]
    total = 0.0
    for name in phase1:
        if name in byname:
            total += byname[name][6]
    win = sum(byname[n][6] * c for n, c in windows)
    oracle = 0.10                    # ESTIMATE: MPFR in line, serial with the card's call (section 4.2)
    grand = (total + win) * (1 + oracle)
    print("  hard, class and the fp32 slice (%d items): %.1f tile-h; four windows of each of four modes: %.1f tile-h"
          % (len(phase1), total, win))
    print("  with the oracle in line (+%.0f%%, ESTIMATE): %.1f tile-hours" % (100 * oracle, grand))
    print("  = %.1f weekday nights of the whole sweep, %.1f at the exhaustive weight (%.2f); two weeks hold %.0f"
          % (grand / wkd, grand / (wkd * EXH_WEIGHT), EXH_WEIGHT, two * EXH_WEIGHT))
    check("C5: phase 1 fits in two weeks of nights at the exhaustive weight", grand < two * EXH_WEIGHT)
    print("\nhx_cost: %d check(s) failed" % len(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
