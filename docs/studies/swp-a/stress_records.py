# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""stress_records.py - the card's 60-hour stress run, read from its own record.

The run (hw/card-stress.sh, 2026-10-16 18:58 to 2026-10-19 08:01, run id card-stress-1016, on
amd-arc-box) wrote metrics.jsonl, one JSON object a line, the record the driver's report is
derived from. This script reads that file (8 MB, so it is NOT in the repository; the lead's
scratchpad holds it with its SHA-256) and does five things for parcel SC's study:

  1. SUMMARY   the run's totals: records by type, sweep slices by kind and image, the end;
  2. RATES     the per-item, per-image median per-job rate, in the format of the lead's
               stress-item-rates.txt, written with --write-rates (the study's primary input;
               the lead's own file is the cross-check, see sweep_cost.py);
  3. SEEDS     every random slice's seed against the formula hw/card_stress_lib.py gives
               (base_seed + 7919 n), n against the run's own count, and the streams that
               share a starting state because both tools set rng_state = seed | 1;
  4. EXHAUSTIVE which image served how much of each exhaustive item (coverage is per ITEM
               in the driver, not per image) and that the intervals tile [0, 2^32);
  5. TILES     the quad's per-tile median rates, to see whether the four tiles differ.

usage: python stress_records.py METRICS_JSONL [--report REPORT_TXT] [--write-rates OUT]
                                [--sha256 HEX] [--controls]
  --report    the final report (hw/card_stress_report.py's text); every item's slices and
              cases must equal its table's exactly
  --controls  tampered copies of the record (a dropped slice, a moved seed, a shortened
              slice), each of which must turn a named CHECK red
Exit status 0 only if every CHECK held.
"""
import collections
import hashlib
import importlib.util
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))

fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-80s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


def load_lib():
    """hw/card_stress_lib.py, read (not changed): the driver's item catalog and seed rule."""
    path = os.path.join(ROOT, "hw", "card_stress_lib.py")
    spec = importlib.util.spec_from_file_location("card_stress_lib", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["card_stress_lib"] = mod
    spec.loader.exec_module(mod)
    return mod


def read_records(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def sweep_legs(recs):
    """The sweep slices that finished with a verdict, in file order."""
    out = []
    for r in recs:
        if r.get("type") != "leg" or r.get("kind") != "sweep" or r.get("status") not in ("pass", "fail"):
            continue
        sw = r.get("sweep") or {}
        out.append(dict(
            item=sw["item"], op=sw.get("op"), tool=sw.get("tool"), mode=sw.get("mode"), image=r["image"],
            tile=sw.get("tile"), jobs=sw.get("jobs", 1), dur=float(r["duration_s"]),
            cases=int((r.get("counts") or {}).get("cases", 0)),
            count=sw.get("count"), seed=sw.get("seed"), seed_n=sw.get("seed_n"),
            lo=sw.get("lo"), hi=sw.get("hi"), status=r["status"],
            vm=int((r.get("counts") or {}).get("value_mismatches", 0)),
            fm=int((r.get("counts") or {}).get("flag_mismatches", 0))))
    return out


def units(s):
    return s["count"] if s["count"] is not None else s["hi"] - s["lo"]


def rates_table(legs):
    """(item, image) -> the lead's columns, from the slices (the median is over slices of
    count-or-cases per second of the slice's own job time)."""
    by = collections.defaultdict(list)
    for s in legs:
        by[(s["item"], s["image"])].append(s)
    rows = {}
    for key, ss in by.items():
        exhaustive = ss[0]["seed_n"] is None
        count_rates = [0 if exhaustive else s["count"] / s["dur"] for s in ss]
        cases_rates = [s["cases"] / s["dur"] for s in ss]
        rows[key] = dict(
            slices=len(ss), count_sum=0 if exhaustive else sum(s["count"] for s in ss),
            cases_sum=sum(s["cases"] for s in ss), jobsec=int(round(sum(s["dur"] for s in ss))),
            count_rate=int(round(statistics.median(count_rates))),
            cases_rate=int(round(statistics.median(cases_rates))),
            jobs=sorted({s["jobs"] for s in ss}))
    return rows


def write_rates(path, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("item image slices count_sum cases_sum jobsec_sum median_count_rate median_cases_rate jobs_seen\n")
        for (item, image) in sorted(rows):
            r = rows[(item, image)]
            fh.write("%s %s %d %d %d %d %d %d [%s]\n" % (
                item, image, r["slices"], r["count_sum"], r["cases_sum"], r["jobsec"],
                r["count_rate"], r["cases_rate"], ",".join(str(j) for j in r["jobs"])))


def read_report_tables(path):
    """item -> (slices, cases) from the report's random and exhaustive tables."""
    out, mode = {}, None
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith("exhaustive items"):
                mode = "exh"
                continue
            if ln.startswith("random items"):
                mode = "rand"
                continue
            if ln.startswith("slices:") or ln.startswith("  total:"):
                mode = None
                continue
            if mode == "exh":
                m = re.match(r"^  (\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+[\d.]+%", ln)
            elif mode == "rand":
                m = re.match(r"^  (\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$", ln)
            else:
                m = None
            if m:
                out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return out


def merge(iv):
    out = []
    for lo, hi in sorted(iv):
        if out and lo <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def analyse(recs, lib, report_path, label, write=None, quiet=False):
    """Everything the script checks, on one record. Returns the legs."""
    global fails
    out = (lambda *a: None) if quiet else print
    legs = sweep_legs(recs)
    types = collections.Counter(r.get("type") for r in recs)
    run_end = [r for r in recs if r.get("type") == "run_end"]
    starts = [r for r in recs if r.get("type") == "run_start"]

    out("== 1. SUMMARY (%s)" % label)
    out("   records %d: %s" % (len(recs), ", ".join("%s %d" % kv for kv in sorted(types.items()))))
    if starts:
        out("   run_start: run id %s on %s, first record %s, resumed=%s" % (
            starts[0].get("run_id"), starts[0].get("host"), starts[0].get("ts"), starts[0].get("resumed")))
    if run_end:
        out("   run_end: reason %s, exit %s, %s cycles, at %s" % (
            run_end[-1].get("reason"), run_end[-1].get("exit"), run_end[-1].get("cycles"), run_end[-1].get("ts")))
    rand = [s for s in legs if s["seed_n"] is not None]
    exh = [s for s in legs if s["seed_n"] is None]
    out("   sweep slices with a verdict: %d (%d random, %d exhaustive); by image: %s" % (
        len(legs), len(rand), len(exh), ", ".join("%s %d" % kv for kv in sorted(collections.Counter(s["image"] for s in legs).items()))))
    out("   value mismatches %d, flag mismatches %d, slices with status fail %d" % (
        sum(s["vm"] for s in legs), sum(s["fm"] for s in legs), sum(1 for s in legs if s["status"] != "pass")))
    out("   cases: %s random, %s exhaustive" % ("{:,}".format(sum(s["cases"] for s in rand)),
                                               "{:,}".format(sum(s["cases"] for s in exh))))
    out("   random slices' size: %d at the 2^20 probe, %d at the 2^28 cap, %d other" % (
        sum(1 for s in rand if s["count"] == 1 << 20), sum(1 for s in rand if s["count"] == 1 << 28),
        sum(1 for s in rand if s["count"] not in (1 << 20, 1 << 28))))
    tot_count = sum(s["count"] for s in rand)
    fixed = sum(s["count"] for s in rand if s["count"] in (1 << 20, 1 << 28))
    out("   share of the random COUNT in slices of the probe or cap size (a rerun's slice n has the same length): %.1f%%" %
        (100.0 * fixed / tot_count))
    check("(%s) a run_end record exists and says exit 0" % label,
          bool(run_end) and run_end[-1].get("exit") == 0 and run_end[-1].get("reason") == "deadline",
          "(%s)" % (run_end[-1].get("reason") if run_end else "none"))
    check("(%s) every sweep slice with a verdict passed: no disagreement in the record" % label,
          all(s["status"] == "pass" and s["vm"] == 0 and s["fm"] == 0 for s in legs))
    check("(%s) 68 items: 54 random and 14 exhaustive" % label,
          len({s["item"] for s in rand}) == 54 and len({s["item"] for s in exh}) == 14,
          "(%d, %d)" % (len({s["item"] for s in rand}), len({s["item"] for s in exh})))
    out()

    # ---- 2. rates -------------------------------------------------------------------
    rows = rates_table(legs)
    out("== 2. RATES: %d (item, image) rows derived; the median is over slices of count (cases for the" % len(rows))
    out("   exhaustive items) per second of the slice's own job time, as the lead's file defines it")
    if write:
        write_rates(write, rows)
        out("   written to the file named by --write-rates (%d rows + header)" % len(rows))
    if report_path:
        rep = read_report_tables(report_path)
        got = {}
        for (item, image), r in rows.items():
            sl, ca = got.get(item, (0, 0))
            got[item] = (sl + r["slices"], ca + r["cases_sum"])
        bad = [(i, got.get(i), rep[i]) for i in rep if got.get(i) != rep[i]]
        check("(%s) all %d items' slices and cases equal the report's tables exactly" % (label, len(rep)),
              len(rep) == 68 and not bad, str(bad[:2]))
    out()

    # ---- 3. seeds ---------------------------------------------------------------------
    out("== 3. SEEDS: the formula, the counter, and the streams that start in the same place")
    items = {it.name: it for it in lib.sweep_items()}
    bad = [(s["item"], s["seed_n"]) for s in rand if s["seed"] != items[s["item"]].seed_for(s["seed_n"])]
    check("(%s) every random slice's seed is hw/card_stress_lib.py's base_seed + 7919 n" % label, not bad,
          "(%d slices; %s)" % (len(rand), str(bad[:2])))
    per_item = collections.defaultdict(list)
    for s in rand:
        per_item[s["item"]].append(s["seed_n"])
    gaps = [i for i, ns in per_item.items() if sorted(ns) != list(range(len(ns)))]
    check("(%s) each random item's slices are n = 0, 1, 2, ... with no gap and no repeat" % label, not gaps, str(gaps[:3]))
    check("(%s) all 54 random items have slices; the highest seed_n of any is shown" % label, len(per_item) == 54,
          "(max seed_n %d)" % max(max(ns) for ns in per_item.values()))
    # the state each stream starts in: both tools set rng_state = seed | 1
    groups = collections.defaultdict(list)
    for s in rand:
        groups[s["seed"] | 1].append(s)
    multi = {st: g for st, g in groups.items() if len({x["item"] for x in g}) > 1}
    within = [st for st, g in groups.items() if len(g) > len({x["item"] for x in g})]
    check("(%s) no item repeats a starting state within itself" % label, not within)
    same_op, diff_op = [], []
    for st, g in multi.items():
        ops = {x["op"] for x in g}
        (same_op if len(ops) == 1 else diff_op).append(g)
    in_multi = sum(len(g) for g in multi.values())
    out("   slices %d, distinct starting states %d; states shared by two or more items: %d" % (
        len(rand), len(groups), len(multi)))
    out("   slices whose starting state another item's slice also started from: %d of %d (%.1f%%)" % (
        in_multi, len(rand), 100.0 * in_multi / len(rand)))
    out("   of those, %d share one OPERATION (the same operands go to different rounding modes) and %d mix operations" % (
        len(same_op), len(diff_op)))
    per_op = collections.defaultdict(lambda: [0, 0, 0, 0])      # slices, colliding slices, dup units, total units
    for s in rand:
        per_op[s["op"]][0] += 1
        per_op[s["op"]][3] += s["count"]
    dup_total = 0
    for g in same_op:
        # the stream is the same; the shorter slice is a prefix of the longer, so the operands
        # a second item sees again are the shorter's, once per extra item in the group
        cs = sorted(x["count"] for x in g)
        extra = sum(cs[:-1])
        per_op[g[0]["op"]][1] += len(g)
        per_op[g[0]["op"]][2] += extra
        dup_total += extra
    out("   %-11s %7s %12s %22s %24s" % ("operation", "slices", "in a shared", "operand count seen again", "share of the op's count"))
    for op in sorted(per_op):
        sl, col, dup, tot = per_op[op]
        if col:
            out("   %-11s %7d %12d %22s %23.1f%%" % (op, sl, col, "{:,}".format(dup), 100.0 * dup / tot))
    out("   total operand count seen again by a second rounding mode of the same operation: %s" % "{:,}".format(dup_total))
    # which (s, s+1) pairs and which parities, as the formula predicts
    pairs = collections.Counter()
    for g in multi.values():
        pairs[tuple(sorted(x["item"] for x in g))] += 1
    out("   the item pairs that shared a state, by number of slices (n) they shared it on:")
    for pr, k in sorted(pairs.items()):
        out("      %-34s %2d slices" % (" + ".join(pr), k))
    # the prediction, from the formula alone (no record): adjacent s at the same n with s + n even
    pred = collections.Counter()
    ns = {name: max(per_item[name]) + 1 for name in per_item}
    by_family = collections.defaultdict(list)
    for name, it in items.items():
        if it.kind == "random":
            by_family[it.base_seed & ~0xFFFF].append(it)
    for fam, its in by_family.items():
        for a in its:
            for b in its:
                if a.name >= b.name:
                    continue
                for n in range(min(ns[a.name], ns[b.name])):
                    if (a.seed_for(n) | 1) == (b.seed_for(n) | 1):
                        pred[tuple(sorted((a.name, b.name)))] += 1
    check("(%s) the formula alone (seed | 1, same n) predicts exactly the pairs and slice counts in the record" % label,
          pred == pairs, "(%d pairs predicted, %d seen)" % (len(pred), len(pairs)))
    out()

    # ---- 4. exhaustive coverage by image -------------------------------------------------
    out("== 4. EXHAUSTIVE items: which image served the slices (the driver keys coverage by ITEM)")
    by = collections.defaultdict(lambda: collections.defaultdict(list))
    for s in exh:
        by[s["item"]][s["image"]].append((s["lo"], s["hi"]))
    out("   %-12s %12s %12s %12s   %s" % ("item", "quad", "single", "deep", "union"))
    tiling_bad = []
    for item in sorted(by):
        share = {im: sum(hi - lo for lo, hi in by[item].get(im, [])) for im in ("quad", "single", "deep")}
        allv = [iv for im in by[item] for iv in by[item][im]]
        un = merge(allv)
        total = sum(hi - lo for lo, hi in allv)
        if un != [(0, 1 << 32)] or total != 1 << 32:
            tiling_bad.append(item)
        out("   %-12s %11.2f%% %11.2f%% %11.2f%%   %s" % (item, 100.0 * share["quad"] / (1 << 32), 100.0 * share["single"] / (1 << 32),
                                                   100.0 * share["deep"] / (1 << 32), "[0, 2^32), no overlap" if item not in tiling_bad else "NOT A TILING"))
    check("(%s) every exhaustive item's slices tile [0, 2^32) exactly, with no overlap" % label, not tiling_bad, str(tiling_bad))
    out()

    # ---- 5. tiles ---------------------------------------------------------------------
    out("== 5. TILES: per-tile median rates on the quad (count, or cases for the exhaustive items), M/s")
    tile_rows = collections.defaultdict(lambda: collections.defaultdict(list))
    for s in legs:
        if s["image"] == "quad" and s["tile"] and s["dur"] > 20:
            u = s["cases"] if s["seed_n"] is None else s["count"]
            tile_rows[s["item"]][s["tile"]].append(u / s["dur"])
    spread = []
    out("   %-16s %8s %8s %8s %8s   %s" % ("item", "tile 1", "tile 2", "tile 3", "tile 4", "max/min"))
    for item in sorted(tile_rows):
        med = {t: statistics.median(v) / 1e6 for t, v in tile_rows[item].items() if len(v) >= 2}
        if len(med) == 4:
            ratio = max(med.values()) / min(med.values())
            spread.append((ratio, item))
    for ratio, item in sorted(spread, reverse=True)[:6]:
        med = {t: statistics.median(v) / 1e6 for t, v in tile_rows[item].items()}
        out("   %-16s %8.3f %8.3f %8.3f %8.3f   %.3f" % (item, med.get(1, 0), med.get(2, 0), med.get(3, 0), med.get(4, 0), ratio))
    out("   (the six widest of the %d items that have a median on each of the four tiles, slices over 20 s)" % len(spread))
    out("   max/min across the four tiles: median %.3f, widest %.3f" % (statistics.median(r for r, _ in spread), max(r for r, _ in spread)))
    out()
    return legs, rows


def controls(metrics, report):
    """Tampered copies of the record, each of which must turn a named CHECK red."""
    import subprocess
    import tempfile
    recs = read_records(metrics)
    tmp = tempfile.mkdtemp(prefix="swp_a_stress_")
    bad = 0

    def run(label, mutated, expect):
        nonlocal bad
        path = os.path.join(tmp, "m.jsonl")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            for r in mutated:
                fh.write(json.dumps(r) + "\n")
        p = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), path, "--report", report],
                           capture_output=True, text=True)
        failed = [l for l in p.stdout.splitlines() if l.startswith("CHECK") and "FAILED" in l]
        hit = [l for l in failed if expect in l]
        ok = p.returncode == 1 and bool(hit)
        print("CONTROL %-62s %s" % (label, "red at the check written for it" if ok else "NOT CAUGHT  FAILED"))
        for l in (hit or failed)[:1]:
            print("        " + l[:170])
        if not ok:
            bad += 1

    def tweak(pred, fn):
        out, done = [], False
        for r in recs:
            r2 = json.loads(json.dumps(r))
            if not done and pred(r2):
                fn(r2)
                done = True
            out.append(r2)
        assert done, "no record matched the mutation"
        return out

    is_sweep = lambda r: r.get("type") == "leg" and r.get("kind") == "sweep"
    # T1: one slice of div64-rne dropped (a lost record)
    run("T1 a div64-rne slice dropped from the record",
        [r for i, r in enumerate(recs) if not (is_sweep(r) and r["sweep"]["item"] == "div64-rne" and r["sweep"].get("seed_n") == 3)],
        "equal the report's tables")
    # T2: a seed moved off the formula
    run("T2 one random slice's seed moved by one",
        tweak(lambda r: is_sweep(r) and r["sweep"]["item"] == "sqrt64-rtz" and r["sweep"].get("seed_n") == 5,
              lambda r: r["sweep"].__setitem__("seed", r["sweep"]["seed"] + 1)),
        "base_seed + 7919 n")
    # T3: an exhaustive slice shortened by one encoding (a hole in the tiling)
    run("T3 an exhaustive slice shortened by one encoding",
        tweak(lambda r: is_sweep(r) and r["sweep"]["item"] == "class32" and r["sweep"].get("lo") == 0 and r["image"] == "quad",
              lambda r: r["sweep"].__setitem__("hi", r["sweep"]["hi"] - 1)),
        "tile [0, 2^32) exactly")
    # T4: a disagreement planted
    run("T4 one slice reports a value mismatch",
        tweak(lambda r: is_sweep(r), lambda r: r["counts"].__setitem__("value_mismatches", 1)),
        "no disagreement in the record")
    # T5: the run_end exit changed
    run("T5 the run ended with exit 3",
        tweak(lambda r: r.get("type") == "run_end", lambda r: r.__setitem__("exit", 3)),
        "a run_end record exists and says exit 0")
    # T6: a collision planted: sqrt64-rne's slice n = 7 given sqrt64-rtz's n = 7 seed (the formula
    #     predicts the pairs; the record then holds one the formula does not predict)
    other = {}
    for r in recs:
        if is_sweep(r) and r["sweep"]["item"] == "sqrt64-rtz" and r["sweep"].get("seed_n") == 7:
            other["seed"] = r["sweep"]["seed"]
    run("T6 a starting state shared that the seed | 1 formula does not predict",
        tweak(lambda r: is_sweep(r) and r["sweep"]["item"] == "sqrt64-rup" and r["sweep"].get("seed_n") == 7,
              lambda r: r["sweep"].__setitem__("seed", other["seed"])),
        "the formula alone")
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if bad:
        print("stress_records controls: %d control(s) NOT CAUGHT" % bad)
        return 1
    print("stress_records controls: all six tampered records were caught at their checks")
    return 0


def main(argv):
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    args = list(argv[1:])
    if not args:
        print(__doc__)
        return 2
    metrics, report, write, sha, do_controls = None, None, None, None, False
    while args:
        a = args.pop(0)
        if a == "--report":
            report = args.pop(0)
        elif a == "--write-rates":
            write = args.pop(0)
        elif a == "--sha256":
            sha = args.pop(0)
        elif a == "--controls":
            do_controls = True
        else:
            metrics = a
    if metrics is None:
        print(__doc__)
        return 2
    if do_controls:
        return controls(metrics, report)
    h = hashlib.sha256()
    with open(metrics, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    print("stress_records.py: the record is metrics.jsonl, %d bytes, sha256 %s" % (os.path.getsize(metrics), h.hexdigest()))
    if sha:
        check("the record's SHA-256 is the one given", h.hexdigest() == sha)
    print()
    lib = load_lib()
    recs = read_records(metrics)
    analyse(recs, lib, report, "final", write=write)
    print("stress_records: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
