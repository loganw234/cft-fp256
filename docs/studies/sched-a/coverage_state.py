#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Where a nightly window has not reached yet, computed from finished runs' metrics.jsonl by the driver's own functions.

    python -B -I coverage_state.py LABEL=METRICS.jsonl[@N] [LABEL=METRICS.jsonl[@N] ...] [--controls]

Read-only. For each run: the driver's `sweep_coverage` (hw/card_stress_lib.py) gives each exhaustive item's
finished intervals, `covered` and `first_gap` its coverage and its first hole, and the item's slices give its
rate in encodings a second a job. Then, across the runs:

  * which of the catalog's 36 exhaustive items a file never served (so a resume of that directory without
    --sweep-items would start them at encoding 0: `Driver.load_state` reads only its own file);
  * the TREE each run's commit stands for, derived with `git rev-parse <commit>:rtl` and `:host` on this
    repository (a run before 2026-10-20 recorded no tree: hw/card_stress_report.py keeps such a run apart
    by its commit; the derivation is the repair SWEEP-RECORDS.md says it would take; a run that did record
    its tree is held to what git derives for its commit), and the union of
    the intervals of every run of one tile class (the rtl/ tree) and the coverage of each host class
    (the host/ tree) apart, as the report keys them;
  * the pace of the unfinished tile items from the card slot-seconds of the newest run, per RUN hour, and
    the nights at that pace; and, when the file's earlier run is also given, what that earlier run's model said
    against what the newer run did;
  * what covering the tile items again on a new rtl/ tree would cost, in nights of the window, at each run's use of the slots;
  * what re-covering the host items on a new host/ tree costs in CPU time at the rates the runs show.

FILE@N reads the N-th run of a file that holds several (a resumed run writes its own `run_start`; the lead resumes
one directory each night). Its COVERAGE is the file's up to the end of that run, which is what the driver's resume
would have read; its slot-seconds, rates, waves and pace are the run's own; and only its own slices are folded by
tree class (a slice belongs to the tree of the run that ran it, which the driver's coverage does not know). A pace
is per RUN hour: each run's own span from its `run_start` to its last record, the idle hours between two runs of a
file left out (divided by the file's whole span, a two-night file's pace came out a third too low). FILE alone is the
whole file: all its runs, and its coverage at its end. The output is written with LF line ends on every platform
(Windows Python would write CRLF to a redirected stdout), so the captures beside this script are LF and compare
equal as they stand.

The union is held to an independent merge written here (CHECK), and each check is shown able to fail
(--controls: a slice removed must change the unfinished list; a wrong merge must be caught; a run-hours sum that
counts the idle hours, an item with no rate, a recorded tree that is not git's and a run the file does not have must
each be caught or refused by name). Prints no path.

Python 3.10 or later; standard library only; `git` for the tree derivation (read-only).
"""
import datetime
import math
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
TONIGHT = "0b7c959"     # the commit of the lead's resume of 2026-10-20 and of the second night's window: main after the coverage wave


def git_tree(commit, rel):
    try:
        p = subprocess.run(["git", "-C", ROOT, "rev-parse", "%s:%s" % (commit, rel)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = p.stdout.strip()
    return out if p.returncode == 0 and len(out) == 40 else None


def tree_status(commit, rec_rtl, rec_host):
    """None when the run recorded no tree; 'skip' when git cannot derive one for its commit; else 'ok' or 'FAIL'."""
    if not (rec_rtl or rec_host):
        return None
    d_rtl = git_tree(commit, "rtl") if commit else None
    d_host = git_tree(commit, "host") if commit else None
    if d_rtl is None or d_host is None:
        return "skip"
    return "ok" if (rec_rtl in (None, d_rtl)) and (rec_host in (None, d_host)) else "FAIL"


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


def parse_arg(a):
    """LABEL=PATH or LABEL=PATH@N -> (label, path, N or None); an `@` not followed by digits only is part of the path."""
    label, _, path = a.partition("=")
    head, sep, tail = path.rpartition("@")
    if sep and head and tail.isdigit():
        return label, head, int(tail)
    return label, path, None


def run_bounds(recs, part):
    """(lo, hi, number of runs) of the part-th run's records in recs (0-based, hi exclusive); the whole of recs for part None.
    None when the file has no such run."""
    starts = [i for i, r in enumerate(recs) if r.get("type") == "run_start"]
    if part is None:
        return 0, len(recs), len(starts)
    if not 1 <= part <= len(starts):
        return None
    return starts[part - 1], (starts[part] if part < len(starts) else len(recs)), len(starts)


def run_seconds(recs):
    """The seconds the driver ran: each run's own span (its run_start to its last record), the idle hours between runs left out."""
    starts = [i for i, r in enumerate(recs) if r.get("type") == "run_start"] or [0]
    tot = 0.0
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(recs)
        ep = [r["epoch"] for r in recs[s:e] if isinstance(r.get("epoch"), (int, float))]
        if ep:
            tot += max(ep) - min(ep)
    return tot


class Run:
    def __init__(self, label, path, part=None):
        self.label = label
        self.path_id = path                     # never printed: only to tell which runs came from one file
        recs_all, partial, bad = L.read_records(path)
        if bad:
            raise SystemExit("%s: lines %s do not parse" % (label, bad[:5]))
        b = run_bounds(recs_all, part)
        if b is None:
            raise SystemExit("%s: the file has no run %d" % (label, part))
        lo, hi, self.nruns = b
        self.part = part
        self.recs = recs_all[:hi]               # what the driver's resume would have read at the end of this run
        self.mine = recs_all[lo:hi]             # this run's own records
        self.before = recs_all[:lo]             # what the file held before it
        self.iv, self.served, self.cases, self.seeds, self.dis = L.sweep_coverage(self.recs)
        self.iv_mine = L.sweep_coverage(self.mine)[0]
        self.iv_before = L.sweep_coverage(self.before)[0] if self.before else {}
        rs = [r for r in self.mine if r.get("type") == "run_start"]
        t = (rs[0].get("tree") or {}) if rs else {}
        self.commit = t.get("commit")
        self.rtl_recorded = t.get("rtl")
        self.host_recorded = t.get("host_src")
        self.rtl = self.rtl_recorded or (git_tree(self.commit, "rtl") if self.commit else None)
        self.host = self.host_recorded or (git_tree(self.commit, "host") if self.commit else None)
        self.derived = not self.rtl_recorded
        self.tree_check = tree_status(self.commit, self.rtl_recorded, self.host_recorded)
        self.legs = [r for r in self.mine if r.get("type") == "leg" and r.get("kind") == "sweep" and r.get("status") in ("pass", "fail")]
        ep = [r["epoch"] for r in self.mine if isinstance(r.get("epoch"), (int, float))]
        self.t0, self.t1 = min(ep), max(ep)
        self.run_s = run_seconds(self.mine)
        self.last_ts = next((r.get("ts") for r in reversed(self.mine) if r.get("ts")), None)

    def item_rate(self, name):
        enc = sum(int(r["sweep"]["hi"]) - int(r["sweep"]["lo"]) for r in self.legs if r["sweep"].get("item") == name and "lo" in r["sweep"])
        sec = sum(float(r.get("duration_s") or 0) for r in self.legs if r["sweep"].get("item") == name and "lo" in r["sweep"])
        return (enc / sec) if sec > 0 else None

    def enc_mine(self, name):
        return sum(int(r["sweep"]["hi"]) - int(r["sweep"]["lo"]) for r in self.legs if r["sweep"].get("item") == name and "lo" in r["sweep"])


def catalog_exhaustive():
    return [it for it in L.sweep_items() if it.kind == "exhaustive"]


def waves_of(r):
    """[(start, end, jobs)] of the run's sweep waves: the sweep legs of a cycle whose intervals overlap, each with the size it records."""
    waves = []
    by_cycle = {}
    for x in r.legs:
        by_cycle.setdefault(x.get("cycle"), []).append(x)
    for cyc, ls in by_cycle.items():
        ls.sort(key=lambda x: x["start_epoch"])
        cur = [ls[0]]
        for x in ls[1:]:
            if x["start_epoch"] < max(y["end_epoch"] for y in cur):
                cur.append(x)
            else:
                waves.append((min(y["start_epoch"] for y in cur), max(y["end_epoch"] for y in cur), int(cur[0]["sweep"].get("jobs") or 1)))
                cur = [x]
        waves.append((min(y["start_epoch"] for y in cur), max(y["end_epoch"] for y in cur), int(cur[0]["sweep"].get("jobs") or 1)))
    return waves


def pace_model(r, tile):
    """The slot-second model of one run, per RUN hour; None when it has no finished sweep slice.
    Each unfinished tile item (unfinished at the end of the run, by the coverage through its end) gets
    low = the slots this run kept busy, shared by the unfinished items alone;
    high = every slot of every wave busy to its end, shared the same way."""
    if not r.legs:
        return None
    span = r.run_s
    slot_s = sum(float(x.get("duration_s") or 0) for x in r.legs)
    waves = waves_of(r)
    t_wave = {}
    for s, e, j in waves:
        t_wave[j] = t_wave.get(j, 0.0) + (e - s)
    full_slots = sum(t * j for j, t in t_wave.items())
    by_jobs = sum(1.0 / max(1, int(x["sweep"].get("jobs") or 1)) for x in r.legs)
    first_last = {}
    for x in r.legs:
        n = x["sweep"]["item"]
        a, b = first_last.get(n, (1e18, 0.0))
        first_last[n] = (min(a, x["start_epoch"]), max(b, x["end_epoch"]))
    unfinished = [it for it in tile if r.iv.get(it.name) and L.first_gap(r.iv[it.name]) is not None]
    unf_names = {u.name for u in unfinished}
    done_end = max((first_last[n][1] for n in first_last if n not in unf_names), default=r.t0)
    n_unf = len(unfinished)
    items = {}
    for it in unfinished:
        rate = r.item_rate(it.name)
        pct = 100.0 * L.covered(r.iv[it.name]) / EXH
        if rate is None or n_unf == 0:
            items[it.name] = (pct, None, None, None)
            continue
        lo = rate * (slot_s / span) / n_unf * 3600.0 / EXH * 100.0
        hi = rate * sum(t * min(j, n_unf) for j, t in t_wave.items()) / n_unf / span * 3600.0 / EXH * 100.0
        items[it.name] = (pct, rate, lo, hi)
    return {"span": span, "slot_s": slot_s, "busy": slot_s / span, "waves": waves, "t_wave": t_wave, "full_slots": full_slots,
            "by_jobs": by_jobs, "alone_h": (r.t1 - done_end) / 3600.0, "unfinished": unfinished, "items": items}


def cost_over(items, runs):
    """(items with a rate, total seconds of one job each, longest (name, seconds), names with no rate in any run):
    each item at the median of the rates the runs show for it; an item no run has a rate for is named and left out."""
    tot = 0.0
    longest = ("", 0.0)
    skipped = []
    have = 0
    parts = []
    for it in items:
        rates = [x for x in (r.item_rate(it.name) for r in runs) if x]
        if not rates:
            skipped.append(it.name)
            continue
        rate = sorted(rates)[len(rates) // 2]
        sec = EXH / rate
        have += 1
        tot += sec
        parts.append((it.name, sec))
        if sec > longest[1]:
            longest = (it.name, sec)
    return have, tot, longest, skipped, parts


def date_after(ts, nights):
    """The date `nights` nights after the date of a run's last record (`ts`, the local time the run wrote), or None."""
    try:
        return datetime.date.fromisoformat(ts[:10]) + datetime.timedelta(days=int(math.ceil(nights)))
    except (TypeError, ValueError):
        return None


def main(argv):
    try:
        sys.stdout.reconfigure(newline="\n")      # LF on every platform, so a capture is the same bytes everywhere
    except (AttributeError, ValueError):
        pass
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 64
    runs = []
    for a in args:
        label, path, part = parse_arg(a)
        runs.append(Run(label, path, part))
    cat = catalog_exhaustive()
    tile = [it for it in cat if it.reach == L.TILE]
    host = [it for it in cat if it.reach == L.HOST]
    print("catalog: %d exhaustive items (%d tile, %d host), each over 2^32 = %s encodings" % (len(cat), len(tile), len(host), format(EXH, ",")))
    ok = True
    # the trees at the commits of the runs and at the commit the lead's resume and the second night's window use (0b7c959)
    print()
    print("== the trees at the commits of the runs (git rev-parse COMMIT:DIR)")
    rows = []
    for r in runs:
        if r.commit and r.commit not in [c for _, c in rows]:
            rows.append((r.label, r.commit))
    if not any(c.startswith(TONIGHT) for _, c in rows):
        rows.append(("the second night's window", TONIGHT))
    trees = {}
    for who, c in rows:
        t = {rel: git_tree(c, rel) for rel in ("rtl", "host", "host/src", "host/include")}
        trees[c] = t
        print("%-40s %-12s rtl %s host %s host/src %s host/include %s" %
              (who, c[:12], (t["rtl"] or "?")[:8], (t["host"] or "?")[:8], (t["host/src"] or "?")[:8], (t["host/include"] or "?")[:8]))
    others = [c for _, c in rows if not c.startswith(TONIGHT)]
    if others:
        a = others[-1]
        b = next(c for _, c in rows if c.startswith(TONIGHT))
        n_all = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b)], capture_output=True, text=True).stdout.strip()
        n_host = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b), "--", "host"], capture_output=True, text=True).stdout.strip()
        n_rtl = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b), "--", "rtl"], capture_output=True, text=True).stdout.strip()
        n_lib = subprocess.run(["git", "-C", ROOT, "rev-list", "--count", "%s..%s" % (a, b), "--", "host/src", "host/include"], capture_output=True, text=True).stdout.strip()
        print("commits from %s to %s: %s in all, %s touched host/, %s touched host/src or host/include, %s touched rtl/" % (a[:7], b[:7], n_all, n_host, n_lib, n_rtl))
        same_lib = trees[a]["host/src"] == trees[b]["host/src"] and trees[a]["host/include"] == trees[b]["host/include"]
        good = same_lib and n_lib == "0" and trees[a]["host/src"] is not None
        print("CHECK %-4s the library's own source (host/src and host/include) is byte-identical at the two commits, and no commit between them touched it" % ("ok" if good else "FAIL"))
        ok = ok and good
    for r in runs:
        if r.tree_check is None:
            print("tree     : %s recorded none (its run_start has no rtl or host_src): derived with git from its commit" % r.label)
        else:
            print("CHECK %-4s %s: the rtl/ and host/ trees its run_start recorded are what git derives for its commit" % (
                {"ok": "ok", "FAIL": "FAIL", "skip": "skip"}[r.tree_check], r.label))
            ok = ok and r.tree_check != "FAIL"
    for r in runs:
        print()
        part = "" if r.part is None else " (run %d of %d in its file; the coverage below is the file's through the end of this run, as the driver's resume would read it)" % (r.part, r.nruns)
        print("== %s%s: commit %s, rtl %s%s, host/ %s%s; %d finished sweep slices in this run, %.2f run hours%s" % (
            r.label, part, (r.commit or "?")[:12], (r.rtl or "?")[:8],
            " (derived with git: the run recorded none)" if r.derived else " (recorded)", (r.host or "?")[:8],
            " (recorded)" if r.host_recorded else " (derived)", len(r.legs), r.run_s / 3600.0,
            "" if r.part is not None or r.nruns <= 1 else "; %d runs, the idle hours between them left out of the run hours (the file spans %.2f h)" % (r.nruns, (r.t1 - r.t0) / 3600.0)))
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
        # what this run gained, against the coverage the file held before it
        if r.part and r.part > 1:
            gained = []
            bad_gain = []
            for it in cat:
                b0 = L.covered(r.iv_before.get(it.name, []))
                b1 = L.covered(r.iv.get(it.name, []))
                if b1 != b0:
                    gained.append((it.name, b0, b1))
                    if b1 - b0 != L.covered(r.iv_mine.get(it.name, [])) or L.covered(r.iv_mine.get(it.name, [])) != r.enc_mine(it.name):
                        bad_gain.append(it.name)
            print("gained in this run, against the file's coverage before it (points of 2^32; %.2f run hours):" % (r.run_s / 3600.0))
            for n, b0, b1 in gained:
                print("  %-18s %7.3f%% -> %7.3f%%: +%.3f points, %.3f points an hour" % (n, 100.0 * b0 / EXH, 100.0 * b1 / EXH, 100.0 * (b1 - b0) / EXH, 100.0 * (b1 - b0) / EXH / (r.run_s / 3600.0)))
            print("CHECK %-4s %s: each item's gain is the encodings this run's own slices cover, and its slices repeat nothing the file held (the resume starts at the first gap)" %
                  ("ok" if not bad_gain else "FAIL", r.label))
            ok = ok and not bad_gain
        # check: the library's union equals an independent merge, for every item of this file
        bad = [n for n, iv in r.iv.items() if L.covered(iv) != naive_union(iv)]
        print("CHECK %-4s %s: hw/card_stress_lib.covered equals an independent merge on all %d items served" % ("ok" if not bad else "FAIL", r.label, len(r.iv)))
        ok = ok and not bad

    # ---- across the runs, by derived tree class: each run's own slices, folded by the tree of the run that ran them
    print()
    print("== the runs folded by tree class (the report's keys: a tile item by rtl/, a host item by host/ and the compiler; each run's own slices)")
    tile_cls = {}
    host_cls = {}
    for r in runs:
        for it in cat:
            iv = r.iv_mine.get(it.name, [])
            if not iv:
                continue
            if it.reach == L.TILE:
                tile_cls.setdefault(r.rtl, {}).setdefault(it.name, []).extend(iv)
            else:
                host_cls.setdefault((r.host, r.label), {}).setdefault(it.name, []).extend(iv)
    for key, items in tile_cls.items():
        done = [n for n, iv in items.items() if L.covered(iv) == EXH]
        partial = {n: L.covered(iv) / EXH for n, iv in items.items() if L.covered(iv) != EXH}
        print("tile class rtl %s: %d of %d tile exhaustive items complete across %s; unfinished: %s" % (
            (key or "?")[:8], len(done), len(tile), ", ".join(r.label for r in runs if r.rtl == key),
            ", ".join("%s %.3f%%" % (n, 100 * p) for n, p in sorted(partial.items())) or "none"))
        miss = [it.name for it in tile if it.name not in items]
        print("                   served by no run: %s" % (", ".join(miss) or "none"))
        ok = ok and all(L.covered(iv) <= EXH for iv in items.values())
    for (h, lab), items in host_cls.items():
        done = [n for n, iv in items.items() if L.covered(iv) == EXH]
        print("host class host/ %s (run %s): %d of %d host exhaustive items complete" % ((h or "?")[:8], lab, len(done), len(host)))
    served_host = {r.label for r in runs for it in host if r.iv_mine.get(it.name)}
    for r in runs:
        if r.label not in served_host:
            print("host class host/ %s (run %s): no host slice among this run's own records, 0 of %d complete (MEASURED: the run's records, not the code)" % ((r.host or "?")[:8], r.label, len(host)))
    print("a commit whose host/ tree is in no class has 0 of %d: the driver, resuming, counts the whole file's coverage and does not re-run them" % len(host))
    print("CHECK %-4s no folded item exceeds 2^32 encodings" % ("ok" if ok else "FAIL"))

    # ---- the pace of the unfinished tile items, from the card's slot-seconds in the newest run, per RUN hour
    print()
    last = max(runs, key=lambda r: r.t1)
    model = pace_model(last, tile)
    if model is None:
        print("== pace: %s has no finished sweep slice, so no pace is read from it" % last.label)
    else:
        good_w = abs(model["by_jobs"] - len(model["waves"])) < 1e-6
        span = model["span"]
        print("== pace of the unfinished tile items in %s, from its card slot-seconds, per run hour (%.2f run hours)" % (last.label, span / 3600.0))
        print("CHECK %-4s %s: the %d waves found equal the sum of 1/jobs over the sweep legs (%.3f), the size each leg records" % ("ok" if good_w else "FAIL", last.label, len(model["waves"]), model["by_jobs"]))
        ok = ok and good_w
        print("waves: %s; the slot-seconds the legs ran are %.0f of the %.0f the waves held (%.0f%%: a wave waits for its slowest job, and the fast items' slots then idle); %.2f slots busy over the run" %
              (", ".join("%d of %d jobs (%.2f h, %.1f%% of the run)" % (sum(1 for w in model["waves"] if w[2] == j), j, t / 3600.0, 100.0 * t / span) for j, t in sorted(model["t_wave"].items(), reverse=True)),
               model["slot_s"], model["full_slots"], 100.0 * model["slot_s"] / model["full_slots"], model["busy"]))
        print("the unfinished items shared the card with the others until %.2f hours before the run's last record: %s" %
              (model["alone_h"], "no clean period to read a pace from" if model["alone_h"] < 1.0 else "the last %.2f hours are theirs alone" % model["alone_h"]))
        prev = next((p for p in runs if p is not last and last.part and p.path_id == last.path_id and p.part == last.part - 1), None)
        pmodel = pace_model(prev, tile) if prev else None
        run_h = [x.run_s / 3600.0 for x in runs if x.path_id == last.path_id and x.part] or [span / 3600.0]
        night_h = sum(run_h) / len(run_h)
        print("%-18s %8s %9s %12s %15s %17s %s" % ("item", "done", "enc/s", "gained here", "this run's model", "earlier run's model", "nights to finish (observed pace; 14 h, %.1f run hours)" % night_h))
        finish = []
        for it in model["unfinished"]:
            pct, rate, lo, hi = model["items"][it.name]
            if rate is None:
                print("%-18s %7.3f%%   no slice of it in this run: no pace read from it" % (it.name, pct))
                continue
            gain = None
            if last.part and last.part > 1:
                gain = 100.0 * (L.covered(last.iv.get(it.name, [])) - L.covered(last.iv_before.get(it.name, []))) / EXH / (span / 3600.0)
            pm = (pmodel["items"].get(it.name) if pmodel else None) or (None, None, None, None)
            obs = gain if gain is not None else lo
            n14 = (100.0 - pct) / (obs * WINDOW_H) if obs else float("nan")
            nrun = (100.0 - pct) / (obs * night_h) if obs else float("nan")
            d = date_after(last.last_ts, nrun)
            finish.append((nrun, d))
            print("%-18s %7.3f%% %9.0f %12s %15s %17s %.1f nights at 14 h, %.1f at %.1f run hours: morning of %s" % (
                it.name, pct, rate, ("%.3f/h" % gain) if gain is not None else "-", "%.2f to %.2f/h" % (lo, hi),
                ("%.2f to %.2f/h" % (pm[2], pm[3])) if pm[2] is not None else "-", n14, nrun, night_h, d if d else "?"))
        if finish and all(d for _, d in finish):
            d_lo, d_hi = min(d for _, d in finish), max(d for _, d in finish)
            print("the %d unfinished items complete %s (COMPUTED from %s's end, BELIEVED steady: the nights being the %.1f run hours the file's runs gave)" %
                  (len(finish), ("on the morning of %s" % d_lo) if d_lo == d_hi else "between the mornings of %s and %s" % (d_lo, d_hi), last.label, night_h))
        if pmodel and last.part and last.part > 1:
            inside = []
            for it in model["unfinished"]:
                gain = 100.0 * (L.covered(last.iv.get(it.name, [])) - L.covered(last.iv_before.get(it.name, []))) / EXH / (span / 3600.0)
                pm = pmodel["items"].get(it.name)
                if pm and pm[2] is not None:
                    inside.append((it.name, gain, pm[2], pm[3], pm[2] <= gain <= pm[3]))
            print("%s's model against what %s did: %s" % (prev.label, last.label, "; ".join(
                "%s %.2f an hour against %.2f to %.2f (%s)" % (n, g, lo, hi, "inside" if ins else "OUTSIDE") for n, g, lo, hi, ins in inside) or "no item in both"))
        # the check: the identity the pace rests on - the slot-seconds the unfinished items got, times their rates, are their encodings
        bad_id = []
        for it in model["unfinished"]:
            enc = last.enc_mine(it.name)
            sec = sum(float(x.get("duration_s") or 0) for x in last.legs if x["sweep"].get("item") == it.name and "lo" in x["sweep"])
            rate = last.item_rate(it.name)
            if rate is None:
                continue
            if abs(rate * sec - enc) > 1e-6 * max(enc, 1) or enc != L.covered(last.iv_mine.get(it.name, [])):
                bad_id.append(it.name)
        print("CHECK %-4s %s: each unfinished item's rate times its slot-seconds is the encodings its slices ran in this run, and equals their merged coverage (no overlap, no gap between slices counted)" %
              ("ok" if not bad_id else "FAIL", last.label))
        ok = ok and not bad_id

    # ---- the cost of covering the tile items again on a new RTL tree, at each run's use of the slots
    print()
    print("== what the %d tile exhaustive items cost to cover again on one more rtl/ tree, at the rates these runs show" % len(tile))
    have, jobsec, longest_t, skipped_t, parts = cost_over(tile, runs)
    if skipped_t:
        print("%d tile items have no rate in any run and are left out of the sum: %s" % (len(skipped_t), ", ".join(skipped_t)))
    if have:
        wide = sum(s for n, s in parts if n.startswith("scaleb32-wide"))
        part_h = [x.run_s / 3600.0 for x in runs if x.part]
        nh = (sum(part_h) / len(part_h)) if part_h else WINDOW_H
        print("%.0f slot-hours in all for the %d tile items with a rate (scaleb32-wide %.0f of them, %.1f%%); a night of %.0f hours, or of %.1f run hours (the mean of the nights read), holds, by the run's use of the slots:" %
              (jobsec / 3600.0, have, wide / 3600.0, 100.0 * wide / jobsec, WINDOW_H, nh))
        for r in runs:
            m = pace_model(r, tile) if r.legs else None
            if m is None:
                continue
            night_lo = m["busy"] * WINDOW_H * 3600.0
            night_hi = m["full_slots"] / m["span"] * WINDOW_H * 3600.0
            print("  %-16s %.1f slot-hours at its use of the slots (%.2f busy) and %.1f with every slot busy: %.1f to %.1f nights of %.0f hours, %.1f to %.1f of %.1f run hours (COMPUTED, BELIEVED steady)" %
                  (r.label, night_lo / 3600.0, m["busy"], night_hi / 3600.0, jobsec / night_hi, jobsec / night_lo, WINDOW_H,
                   jobsec / night_hi * WINDOW_H / nh, jobsec / night_lo * WINDOW_H / nh, nh))
    else:
        print("no tile item has a rate in these runs: no cost to give")

    # ---- the cost of covering the host items again on a new host/ tree
    print()
    print("== what the host items cost to cover again on one more host/ tree, at the rates these runs show")
    nrates, tot, longest, skipped_h, _parts = cost_over(host, runs)
    if skipped_h:
        print("%d host items have no rate in any run and are left out of the sum: %s" % (len(skipped_h), ", ".join(skipped_h)))
    print("%d host exhaustive items have a rate in these runs; one core covering all of them once: %.1f hours; the longest alone: %s %.2f hours" %
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
        # 4. the run hours of two runs ten hours apart are their two spans, not the span between the first record and the last
        syn = [{"type": "run_start", "epoch": 0.0}, {"type": "leg", "epoch": 7200.0}, {"type": "run_end", "epoch": 7200.0},
               {"type": "run_start", "epoch": 43200.0}, {"type": "run_end", "epoch": 46800.0}]
        rs_ok = run_seconds(syn) == 10800.0 and (46800.0 - 0.0) != 10800.0
        print("CONTROL %-4s two runs of 2 h and 1 h with ten idle hours between are %.0f run seconds, not the %.0f the file spans" % ("ok" if rs_ok else "FAIL", run_seconds(syn), 46800.0))
        ok = ok and rs_ok
        # 5. an item no run has a rate for is named and left out, and the sum does not raise
        h0, t0, lg, sk, _p = cost_over(tile, [])
        no_rate = h0 == 0 and t0 == 0.0 and len(sk) == len(tile)
        print("CONTROL %-4s with no run at all, all %d tile items are named as having no rate and the cost sum is empty, not a crash" % ("ok" if no_rate else "FAIL", len(sk)))
        ok = ok and no_rate
        # 6. a recorded tree that is not git's must be caught; an unknown commit is a skip, not a pass
        flipped = tree_status(TONIGHT, "0" * 40, None)
        unknown = tree_status("0" * 40, "1" * 40, None)
        tr_ok = flipped == "FAIL" and unknown == "skip" and tree_status(TONIGHT, None, None) is None
        print("CONTROL %-4s a recorded rtl/ hash that git does not derive is %s, an unknown commit is %s, a run that recorded none is %s" % (
            "ok" if tr_ok else "FAIL", flipped, unknown, tree_status(TONIGHT, None, None)))
        ok = ok and tr_ok
        # 7. a run the file does not have is refused
        n_runs = run_bounds(runs[-1].recs, None)[2]
        refused = run_bounds(runs[-1].recs, n_runs + 1) is None and run_bounds(runs[-1].recs, 0) is None
        print("CONTROL %-4s a run the file does not have (%d and 0) is refused, not read as another" % ("ok" if refused else "FAIL", n_runs + 1))
        ok = ok and refused
    print("coverage_state: %s" % ("every check held" if ok else "A CHECK FAILED"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
