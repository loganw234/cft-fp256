#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Where a nightly window has not reached yet, computed from finished runs' metrics.jsonl by the driver's own functions.

    python -B -I coverage_state.py LABEL=METRICS.jsonl [LABEL=METRICS.jsonl ...] [--controls]

Read-only. For each run file: the driver's `sweep_coverage` (hw/card_stress_lib.py) gives each exhaustive item's
finished intervals, `covered` and `first_gap` its coverage and its first hole, and the item's slices give its
rate in encodings a second a job. Then, across the files:

  * which of the catalog's 36 exhaustive items a file never served (so a resume of that directory without
    --sweep-items would start them at encoding 0: `Driver.load_state` reads only its own file);
  * the TREE each run's commit stands for, derived with `git rev-parse <commit>:rtl` and `:host` on this
    repository (a run before 2026-10-20 recorded no tree: hw/card_stress_report.py keeps such a run apart
    by its commit; the derivation is the repair SWEEP-RECORDS.md says it would take), and the union of
    the intervals of every run of one tile class (the rtl/ tree) and the coverage of each host class
    (the host/ tree) apart, as the report keys them;
  * the pace of the unfinished tile items from the card slot-seconds of the newest file, and the nights at that pace;
  * what covering the tile items again on a new rtl/ tree would cost, in nights of the window;
  * what re-covering the host items on a new host/ tree costs in CPU time at the rates the files show.

The union is held to an independent merge written here (CHECK), and each check is shown able to fail
(--controls: a slice removed must change the unfinished list; a wrong merge must be caught). Prints no path.

Python 3.10 or later; standard library only; `git` for the tree derivation (read-only).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
HW = os.path.join(ROOT, "hw")
sys.dont_write_bytecode = True
sys.path.insert(0, HW)
import card_stress_lib as L  # noqa: E402

EXH = L.EXH
WINDOW_H = 14.0
TONIGHT = "0b7c959"     # the commit of the lead's resume of 2026-10-20 and of tonight's window: main after the coverage wave



def git_tree(commit, rel):
    try:
        p = subprocess.run(["git", "-C", ROOT, "rev-parse", "%s:%s" % (commit, rel)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = p.stdout.strip()
    return out if p.returncode == 0 and len(out) == 40 else None


def naive_union(iv):
    """An independent merge: sort, then grow the current end; the sum of the lengths."""
    total, cur_lo, cur_hi = 0, None, None
    for lo, hi in sorted(iv):
        if cur_hi is None or lo > cur_hi:
            if cur_hi is not None:
                total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    if cur_hi is not None:
        total += cur_hi - cur_lo
    return total


class Run:
    def __init__(self, label, path):
        self.label = label
        recs, partial, bad = L.read_records(path)
        if bad:
            raise SystemExit("%s: lines %s do not parse" % (label, bad[:5]))
        self.recs = recs
        self.iv, self.served, self.cases, self.seeds, self.dis = L.sweep_coverage(recs)
        rs = [r for r in recs if r.get("type") == "run_start"]
        t = (rs[0].get("tree") or {}) if rs else {}
        self.commit = t.get("commit")
        self.rtl_recorded = t.get("rtl")
        self.rtl = self.rtl_recorded or (git_tree(self.commit, "rtl") if self.commit else None)
        self.host = t.get("host_src") or (git_tree(self.commit, "host") if self.commit else None)
        self.derived = not self.rtl_recorded
        legs = [r for r in recs if r.get("type") == "leg" and r.get("kind") == "sweep" and r.get("status") in ("pass", "fail")]
        self.legs = legs
        ep = [r["epoch"] for r in recs if isinstance(r.get("epoch"), (int, float))]
        self.t0, self.t1 = min(ep), max(ep)

    def item_rate(self, name):
        enc = sum(int(r["sweep"]["hi"]) - int(r["sweep"]["lo"]) for r in self.legs if r["sweep"].get("item") == name and "lo" in r["sweep"])
        sec = sum(float(r.get("duration_s") or 0) for r in self.legs if r["sweep"].get("item") == name and "lo" in r["sweep"])
        return (enc / sec) if sec > 0 else None


def catalog_exhaustive():
    return [it for it in L.sweep_items() if it.kind == "exhaustive"]


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 64
    runs = []
    for a in args:
        label, _, path = a.partition("=")
        runs.append(Run(label, path))
    cat = catalog_exhaustive()
    tile = [it for it in cat if it.reach == L.TILE]
    host = [it for it in cat if it.reach == L.HOST]
    print("catalog: %d exhaustive items (%d tile, %d host), each over 2^32 = %s encodings" % (len(cat), len(tile), len(host), format(EXH, ",")))
    ok = True
    # the trees at the commits of the runs and at the commit the lead's resume and tonight's window use (0b7c959)
    print()
    print("== the trees at three commits (git rev-parse COMMIT:DIR)")
    commits = [(r.label, r.commit) for r in runs if r.commit] + [("tonight's window and the second night", TONIGHT)]
    seen = {}
    for who, c in commits:
        t = {rel: git_tree(c, rel) for rel in ("rtl", "host", "host/src", "host/include")}
        seen[who] = t
        print("%-40s %-12s rtl %s host %s host/src %s host/include %s" %
              (who, c[:12], (t["rtl"] or "?")[:8], (t["host"] or "?")[:8], (t["host/src"] or "?")[:8], (t["host/include"] or "?")[:8]))
    if len(commits) >= 3:
        a, b = commits[-2][1], commits[-1][1]
        n_all = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b)], capture_output=True, text=True).stdout.strip()
        n_host = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b), "--", "host"], capture_output=True, text=True).stdout.strip()
        n_rtl = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b), "--", "rtl"], capture_output=True, text=True).stdout.strip()
        n_lib = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b), "--", "host/src", "host/include"], capture_output=True, text=True).stdout.strip()
        print("commits from %s to %s: %s in all, %s touched host/, %s touched host/src or host/include, %s touched rtl/" % (a[:7], b[:7], n_all, n_host, n_lib, n_rtl))
        same_lib = seen[commits[-2][0]]["host/src"] == seen[commits[-1][0]]["host/src"] and seen[commits[-2][0]]["host/include"] == seen[commits[-1][0]]["host/include"]
        good = same_lib and n_lib == "0" and seen[commits[-2][0]]["host/src"] is not None
        print("CHECK %-4s the library's own source (host/src and host/include) is byte-identical at the two commits, and no commit between them touched it" % ("ok" if good else "FAIL"))
        ok = ok and good
    for r in runs:
        print()
        print("== %s: commit %s, rtl %s%s, host/ %s; %d finished sweep slices" % (
            r.label, (r.commit or "?")[:12], (r.rtl or "?")[:8], " (derived with git: the run recorded none)" if r.derived else " (recorded)",
            (r.host or "?")[:8], len(r.legs)))
        print("%-18s %-5s %6s %9s %-26s %12s" % ("item", "reach", "slices", "covered", "first gap (lo, hi)", "enc/s a job"))
        unserved = 0
        for it in cat:
            iv = r.iv.get(it.name, [])
            if not iv:
                unserved += 1
                continue
            cov = L.covered(iv)
            gap = L.first_gap(iv)
            rate = r.item_rate(it.name)
            print("%-18s %-5s %6d %8.3f%% %-26s %12s" % (it.name, it.reach, r.served.get(it.name, 0), 100.0 * cov / EXH,
                  "complete" if gap is None else "(%d, %d)" % gap, "%.0f" % rate if rate else "-"))
        print("never served in this file: %d of %d exhaustive items (a --resume of this directory without --sweep-items would start each at encoding 0)" %
              (unserved, len(cat)))
        # check: the library's union equals an independent merge, for every item of this file
        bad = [n for n, iv in r.iv.items() if L.covered(iv) != naive_union(iv)]
        print("CHECK %-4s %s: hw/card_stress_lib.covered equals an independent merge on all %d items served" % ("ok" if not bad else "FAIL", r.label, len(r.iv)))
        ok = ok and not bad

    # ---- across the files, by derived tree class
    print()
    print("== the files folded by tree class (the report's keys: a tile item by rtl/, a host item by host/ and the compiler)")
    tile_cls = {}
    host_cls = {}
    for r in runs:
        for it in cat:
            iv = r.iv.get(it.name, [])
            if not iv:
                continue
            if it.reach == L.TILE:
                tile_cls.setdefault(r.rtl, {}).setdefault(it.name, []).extend(iv)
            else:
                host_cls.setdefault((r.host, r.label), {}).setdefault(it.name, []).extend(iv)
    for key, items in tile_cls.items():
        done = [n for n, iv in items.items() if L.covered(iv) == EXH]
        part = {n: L.covered(iv) / EXH for n, iv in items.items() if L.covered(iv) != EXH}
        print("tile class rtl %s: %d of %d tile exhaustive items complete across %s; unfinished: %s" % (
            (key or "?")[:8], len(done), len(tile), ", ".join(r.label for r in runs if r.rtl == key),
            ", ".join("%s %.3f%%" % (n, 100 * p) for n, p in sorted(part.items())) or "none"))
        miss = [it.name for it in tile if it.name not in items]
        print("                   served by no file: %s" % (", ".join(miss) or "none"))
        ok = ok and all(L.covered(iv) <= EXH for iv in items.values())
    for (h, lab), items in host_cls.items():
        done = [n for n, iv in items.items() if L.covered(iv) == EXH]
        print("host class host/ %s (file %s): %d of %d host exhaustive items complete" % ((h or "?")[:8], lab, len(done), len(host)))
    print("a commit whose host/ tree is in neither class has 0 of %d: the driver, resuming, counts the whole file's coverage and does not re-run them" % len(host))
    print("CHECK %-4s no folded item exceeds 2^32 encodings" % ("ok" if ok else "FAIL"))

    # ---- the pace of the unfinished tile items, from the card's slot-seconds in the newest file
    print()
    last = max(runs, key=lambda r: r.t1)
    span = last.t1 - last.t0
    slot_s = sum(float(r.get("duration_s") or 0) for r in last.legs)
    busy = slot_s / span
    # when each item of the file ran first and last: the items shared the card until the others finished
    first_last = {}
    for r in last.legs:
        n = r["sweep"]["item"]
        a, b = first_last.get(n, (1e18, 0.0))
        first_last[n] = (min(a, r["start_epoch"]), max(b, r["end_epoch"]))
    unfinished = [it for it in tile if last.iv.get(it.name) and L.first_gap(last.iv[it.name]) is not None]
    done_end = max((first_last[n][1] for n in first_last if n not in {u.name for u in unfinished}), default=last.t0)
    alone_h = (last.t1 - done_end) / 3600.0
    # the waves, as latency.py groups them (the sweep legs of a cycle whose intervals overlap), each with the size it records
    waves = []
    by_cycle = {}
    for r in last.legs:
        by_cycle.setdefault(r.get("cycle"), []).append(r)
    for cyc, ls in by_cycle.items():
        ls.sort(key=lambda r: r["start_epoch"])
        cur = [ls[0]]
        for r in ls[1:]:
            if r["start_epoch"] < max(x["end_epoch"] for x in cur):
                cur.append(r)
            else:
                waves.append((min(x["start_epoch"] for x in cur), max(x["end_epoch"] for x in cur), int(cur[0]["sweep"].get("jobs") or 1)))
                cur = [r]
        waves.append((min(x["start_epoch"] for x in cur), max(x["end_epoch"] for x in cur), int(cur[0]["sweep"].get("jobs") or 1)))
    t_wave = {}
    for s, e, j in waves:
        t_wave[j] = t_wave.get(j, 0.0) + (e - s)
    full_slots = sum(t * j for j, t in t_wave.items())           # slot-seconds if every slot of every wave had been busy to its end
    by_jobs = sum(1.0 / max(1, int(r["sweep"].get("jobs") or 1)) for r in last.legs)
    good_w = abs(by_jobs - len(waves)) < 1e-6
    print("CHECK %-4s %s: the %d waves found equal the sum of 1/jobs over the sweep legs (%.3f), the size each leg records" % ("ok" if good_w else "FAIL", last.label, len(waves), by_jobs))
    ok = ok and good_w
    print("== pace of the unfinished tile items in %s, from its card slot-seconds" % last.label)
    print("waves: %s; the slot-seconds the legs ran are %.0f of the %.0f the waves held (%.0f%%: a wave waits for its slowest job, and the fast items' slots then idle); %.2f slots busy over the span" %
          (", ".join("%d of %d jobs (%.2f h, %.1f%% of the span)" % (sum(1 for w in waves if w[2] == j), j, t / 3600.0, 100.0 * t / span) for j, t in sorted(t_wave.items(), reverse=True)),
           slot_s, full_slots, 100.0 * slot_s / full_slots, busy))
    print("the unfinished items shared the card with the others until %.2f hours before the file's last record: no clean period to read a pace from" % alone_h)
    n_unf = len(unfinished)
    for it in unfinished:
        iv = last.iv[it.name]
        pct = 100.0 * L.covered(iv) / EXH
        rate = last.item_rate(it.name)
        lo_pace = rate * busy / n_unf * 3600.0 / EXH * 100.0                  # the slots this file kept busy, shared by the unfinished items alone
        hi_pace = rate * sum(t * min(j, n_unf) for j, t in t_wave.items()) / n_unf / span * 3600.0 / EXH * 100.0   # every slot of every wave busy to its end
        print("%-18s %7.3f%% done, %.0f enc/s a job; %.2f to %.2f points an hour alone (%.1f to %.1f a %.0f-hour night): %.1f to %.1f more nights (COMPUTED, BELIEVED steady)" %
              (it.name, pct, rate, lo_pace, hi_pace, lo_pace * WINDOW_H, hi_pace * WINDOW_H, WINDOW_H,
               (100.0 - pct) / (hi_pace * WINDOW_H), (100.0 - pct) / (lo_pace * WINDOW_H)))
    # the check: the identity the pace rests on - the slot-seconds the unfinished items got, times their rates, are their encodings
    bad_id = []
    for it in unfinished:
        iv = last.iv[it.name]
        enc = sum(int(r["sweep"]["hi"]) - int(r["sweep"]["lo"]) for r in last.legs if r["sweep"].get("item") == it.name and "lo" in r["sweep"])
        sec = sum(float(r.get("duration_s") or 0) for r in last.legs if r["sweep"].get("item") == it.name and "lo" in r["sweep"])
        if abs(last.item_rate(it.name) * sec - enc) > 1e-6 * max(enc, 1) or enc != L.covered(iv):
            bad_id.append(it.name)
    print("CHECK %-4s %s: each unfinished item's rate times its slot-seconds is its covered encodings, and equals the merged coverage (no overlap, no gap between slices counted)" %
          ("ok" if not bad_id else "FAIL", last.label))
    ok = ok and not bad_id

    # ---- the cost of covering the tile items again on a new RTL tree
    print()
    print("== what the 18 tile exhaustive items cost to cover again on one more rtl/ tree, at the rates these files show")
    jobsec = 0.0
    parts = []
    for it in tile:
        rates = [r.item_rate(it.name) for r in runs if r.item_rate(it.name)]
        rate = sorted(rates)[len(rates) // 2]
        sec = EXH / rate
        jobsec += sec
        parts.append((it.name, sec))
    wide = sum(s for n, s in parts if n.startswith("scaleb32-wide"))
    night_lo = busy * WINDOW_H * 3600.0
    night_hi = full_slots / span * WINDOW_H * 3600.0
    print("%.0f slot-hours in all (scaleb32-wide %.0f of them, %.1f%%); a %.0f-hour night holds %.1f slot-hours at this file's use of the slots and %.1f with every slot busy: %.1f to %.1f nights (COMPUTED, BELIEVED steady)" %
          (jobsec / 3600.0, wide / 3600.0, 100.0 * wide / jobsec, WINDOW_H, night_lo / 3600.0, night_hi / 3600.0, jobsec / night_hi, jobsec / night_lo))

    # ---- the cost of covering the host items again on a new host/ tree
    print()
    print("== what the host items cost to cover again on one more host/ tree, at the rates these files show")
    tot = 0.0
    longest = ("", 0.0)
    nrates = 0
    for it in host:
        rates = [r.item_rate(it.name) for r in runs if r.item_rate(it.name)]
        if not rates:
            continue
        rate = sorted(rates)[len(rates) // 2]
        sec = EXH / rate
        nrates += 1
        tot += sec
        if sec > longest[1]:
            longest = (it.name, sec)
    print("%d host exhaustive items have a rate in these files; one core covering all of them once: %.1f hours; the longest alone: %s %.2f hours" %
          (nrates, tot / 3600.0, longest[0], longest[1] / 3600.0))
    for w in (8,):
        wall = max(tot / w, longest[1])
        print("on %d workers, one item a worker at a time (the pool's rule): about %.1f hours (COMPUTED; the rates are card-run rates of host code, the pool's own are unmeasured)" % (w, wall / 3600.0))

    if "--controls" in argv:
        print()
        print("== controls")
        # 1. a slice removed must change the unfinished list
        r = runs[-1]
        victim = next((n for n, iv in r.iv.items() if len(iv) > 1 and L.first_gap(iv) is None), None)
        if victim:
            iv = sorted(r.iv[victim])
            cut = iv[len(iv) // 2]
            damaged = [x for x in iv if x != cut]
            changed = L.first_gap(damaged) is not None and L.first_gap(iv) is None
            print("CONTROL %-4s removing one slice of %s (an item the file shows complete) makes it unfinished with a first gap at %s" % (
                "ok" if changed else "FAIL", victim, L.first_gap(damaged)))
            ok = ok and changed
        # 2. a wrong merge (adjacent intervals not joined, overlaps summed) must be caught by the independent check
        def wrong(iv):
            return sum(hi - lo for lo, hi in iv)
        iv = [(0, 100), (50, 150), (150, 200)]
        caught = wrong(iv) != naive_union(iv) and L.covered(iv) == naive_union(iv) == 200
        print("CONTROL %-4s a sum that counts an overlap twice (%d) differs from the merge (%d), which the check would catch" % ("ok" if caught else "FAIL", wrong(iv), naive_union(iv)))
        ok = ok and caught
        # 3. first_gap on a known hole
        g = L.first_gap([(0, 10), (20, EXH)])
        good = g == (10, 20)
        print("CONTROL %-4s first_gap finds the hole at %s in [(0, 10), (20, 2^32)]" % ("ok" if good else "FAIL", g))
        ok = ok and good
    print("coverage_state: %s" % ("every check held" if ok else "A CHECK FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
