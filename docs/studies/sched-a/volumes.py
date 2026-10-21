#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""What a card stress run's metrics.jsonl holds, by record type, per hour, per nightly window and per year.

    python -B -I volumes.py LABEL=METRICS.jsonl[@N] [LABEL=METRICS.jsonl[@N] ...] [LABEL=DIRECTORY ...] [--controls]

Read-only. A LABEL=DIRECTORY argument lists the directory's files and bytes by name (the records the lead copied back from
a batch). A file that holds several runs (a resumed one: each resume writes its own `run_start`) can be read run by run:
FILE@N is the N-th run, from its `run_start` line to the next one's, and is analysed as a file of its own, so that a
night is measured alone and not with the idle hours between two nights. The output is written with LF line ends on
every platform (Windows Python would write CRLF to a redirected stdout), so the captures beside this script are LF
and compare equal as they stand. It reads each file once and prints: the size, line count and SHA-256 of what it
analyses (and, for a run of a file, which lines and the whole file's SHA-256); a table by
record type (count, bytes, share, mean bytes a record); the span the records cover; the rates a hour;
the same figures for a nightly window of 14 hours (18:00 to 08:00, the window Logan named on 2026-10-21)
and for 365 of them; and what the telemetry records say about the free disk. Nothing is printed of a
path: a record's `out`, an image's `path` and a file's directory are never shown, only the LABEL given.

Every figure is COMPUTED from the file. What it cannot give is the size of the run's `logs/`
directory: the records name each leg's log (`log`, `log_kept`) and not its size, and the logs are not
in any local copy. The checks at the end hold the table to the file (the sums, the parse, the newline
at the end) and, with --controls, show each check able to fail on a damaged copy.

Python 3.10 or later; standard library only.
"""
import collections
import hashlib
import json
import os
import sys
import time

WINDOW_H = 14.0          # 18:00 to 08:00
NIGHTS = 365


def iso_utc(epoch):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(epoch)) + "Z"


def analyse(raw):
    """(by_type, records, problems) from the file's bytes."""
    problems = []
    if not raw.endswith(b"\n"):
        problems.append("the file does not end with a newline")
    lines = raw.split(b"\n")
    tail = lines.pop()
    if tail:
        lines.append(tail)
    by = collections.OrderedDict()
    recs = []
    for i, ln in enumerate(lines, 1):
        if not ln.strip():
            problems.append("line %d is empty" % i)
            continue
        try:
            r = json.loads(ln.decode("utf-8"))
        except ValueError:
            problems.append("line %d does not parse" % i)
            continue
        t = r.get("type", "(no type)")
        by.setdefault(t, []).append(len(ln) + 1)
        recs.append(r)
    return by, recs, problems


def split_runs(raw):
    """[(first line, last line, bytes)] of each run of a file (1-based lines): from a `run_start` record's line to the line
    before the next one's (the last run goes to the end). Lines before the first `run_start` belong to no run."""
    parts = raw.split(b"\n")
    last = parts.pop()
    lines = [p + b"\n" for p in parts] + ([last] if last else [])
    starts = []
    for i, ln in enumerate(lines):
        try:
            if json.loads(ln.decode("utf-8")).get("type") == "run_start":
                starts.append(i)
        except ValueError:
            pass
    out = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(lines)
        out.append((s + 1, e, b"".join(lines[s:e])))
    return out


def report(label, raw, note=None):
    by, recs, problems = analyse(raw)
    total = len(raw)
    print("== %s" % label)
    if note:
        print("part     : %s" % note)
    print("file     : %s bytes, %d lines, sha256 %s" % (format(total, ","), raw.count(b"\n"), hashlib.sha256(raw).hexdigest()))
    print("%-12s %7s %10s %7s %9s" % ("type", "count", "bytes", "share", "B/record"))
    s_b = 0
    for t, v in by.items():
        s_b += sum(v)
        print("%-12s %7d %10s %6.1f%% %9.0f" % (t, len(v), format(sum(v), ","), 100.0 * sum(v) / total, sum(v) / len(v)))
    print("%-12s %7d %10s" % ("all", sum(len(v) for v in by.values()), format(s_b, ",")))
    ep = [r["epoch"] for r in recs if isinstance(r.get("epoch"), (int, float))]
    span = max(ep) - min(ep)
    hrs = span / 3600.0
    print("span     : %s to %s, %.3f hours (%d s)" % (iso_utc(min(ep)), iso_utc(max(ep)), hrs, round(span)))
    print("per hour : %.0f bytes, %.2f records" % (total / hrs, len(recs) / hrs))
    tel = by.get("telemetry", [])
    leg = by.get("leg", [])
    print("           telemetry %.0f B/h (%.1f samples/h), legs %.0f B/h (%.1f legs/h)" %
          (sum(tel) / hrs, len(tel) / hrs, sum(leg) / hrs, len(leg) / hrs))
    night = total / hrs * WINDOW_H
    print("per night: %.2f MB for a %.0f-hour window at this mix (COMPUTED: bytes/hour x %.0f)" % (night / 1e6, WINDOW_H, WINDOW_H))
    print("per year : %.0f MB for %d such nights (%.2f GB), of which telemetry %.0f MB" %
          (night * NIGHTS / 1e6, NIGHTS, night * NIGHTS / 1e9, sum(tel) / hrs * WINDOW_H * NIGHTS / 1e6))
    # what a compact telemetry record would hold: the six values the project's figures read
    # (python/figure_extracts.py STRESS_TEL), as keys and numbers, with the record's own header fields
    keys6 = ["electrical.devices[0].electrical.power_consumption_watts",
             "thermal.devices[0].thermals.FPGA.temp_C", "thermal.devices[0].thermals.Int Vcc.temp_C",
             "thermal.devices[0].thermals.PCB Top Front.temp_C", "thermal.devices[0].thermals.PCB Top Rear.temp_C",
             "thermal.devices[0].thermals.FPGA HBM.temp_C"]
    trecs = [r for r in recs if r.get("type") == "telemetry" and r.get("ok") and r.get("values")]
    have = sum(1 for r in trecs if all(k in r["values"] for k in keys6))
    if trecs:
        cmp_sizes = []
        for r in trecs:
            c = {"type": "telemetry", "epoch": r.get("epoch"), "when": r.get("when"), "ok": True,
                 "values": {k.split(".")[-2] if k.endswith("temp_C") else "power_w": r["values"].get(k) for k in keys6}}
            h = r.get("host") or {}
            if h:
                c["host"] = {k: h[k] for k in ("load1", "mem_avail_mb") if k in h}
            cmp_sizes.append(len(json.dumps(c, separators=(",", ":"))) + 1)
        print("telemetry: %d records with values; %d carry all six keys the figures read; a compact record of those six plus the host's load"
              " and memory is %.0f B on average against %.0f B (a %.1fx reduction, COMPUTED)" %
              (len(trecs), have, sum(cmp_sizes) / len(cmp_sizes), sum(by["telemetry"]) / len(by["telemetry"]),
               (sum(by["telemetry"]) / len(by["telemetry"])) / (sum(cmp_sizes) / len(cmp_sizes))))
    # the disk, as the telemetry sampled it
    series = collections.defaultdict(list)
    for r in recs:
        if r.get("type") == "telemetry":
            d = ((r.get("host") or {}).get("disk_free_gb")) or {}
            for k, v in d.items():
                series["the run directory" if k.startswith("/data/") else k].append((r["epoch"], v))
    for k, pts in series.items():
        pts.sort()
        vals = [v for _, v in pts]
        print("disk free: %-18s first %.2f GB, last %.2f GB, min %.2f, max %.2f GB over %d samples (net change %.2f GB; samples are rounded to 0.01 GB)" %
              (k, vals[0], vals[-1], min(vals), max(vals), len(vals), vals[-1] - vals[0]))
    hs = [(r.get("host") or {}) for r in recs if r.get("type") == "telemetry"]
    l1 = sorted(h["load1"] for h in hs if "load1" in h)
    ma = [h["mem_avail_mb"] for h in hs if "mem_avail_mb" in h]
    mt = sorted({h["mem_total_mb"] for h in hs if "mem_total_mb" in h})
    if l1 and ma and mt:
        print("host     : %d samples; load1 median %.2f, max %.2f; memory total %s MB, available at least %s MB (the host's own, as the driver sampled it)" %
              (len(l1), l1[len(l1) // 2], l1[-1], "/".join(format(x, ",") for x in mt), format(min(ma), ",")))
    kept = collections.Counter(r.get("log_kept") for r in recs if r.get("type") == "leg")
    named = sum(1 for r in recs if r.get("type") == "leg" and r.get("log"))
    print("logs     : %d legs name a log file (log_kept: %s); the records do not carry a log's size" %
          (named, ", ".join("%s %d" % (k, v) for k, v in sorted(kept.items(), key=lambda kv: str(kv[0])))))
    cpu = sum(1 for r in recs if r.get("type") == "leg" and r.get("image") == "cpu")
    print("host pool: %d legs ran on the image `cpu` (the host pool's slices)" % cpu)
    figs = {"label": label, "hours": hrs, "bytes": total, "per_h": total / hrs, "night_mb": night / 1e6,
            "year_mb": night * NIGHTS / 1e6, "tel_share": (sum(tel) / total) if total else 0.0,
            "tel_year_mb": sum(tel) / hrs * WINDOW_H * NIGHTS / 1e6, "load1_med": (l1[len(l1) // 2] if l1 else None),
            "records": len(recs)}
    return by, recs, problems, figs


def summary(figs):
    """The measured runs side by side, and the range they make."""
    print("== the measured runs side by side (a 14-hour window at each one's own mix; 365 such nights)")
    print("%-22s %8s %11s %10s %9s %9s %8s %7s" % ("run", "hours", "bytes", "bytes/h", "MB/night", "MB/year", "telem.", "load1"))
    for f in figs:
        print("%-22s %8.3f %11s %10.0f %9.2f %9.0f %7.1f%% %7s" % (
            f["label"], f["hours"], format(f["bytes"], ","), f["per_h"], f["night_mb"], f["year_mb"], 100.0 * f["tel_share"],
            ("%.2f" % f["load1_med"]) if f["load1_med"] is not None else "-"))
    nm = [f["night_mb"] for f in figs]
    ym = [f["year_mb"] for f in figs]
    ts = [100.0 * f["tel_share"] for f in figs]
    ld = [f["load1_med"] for f in figs if f["load1_med"] is not None]
    print("ranges   : %.2f to %.2f MB a night, %.0f to %.0f MB a year, telemetry %.1f to %.1f per cent of the bytes%s (COMPUTED over %d runs)" %
          (min(nm), max(nm), min(ym), max(ym), min(ts), max(ts),
           (", load1 median %.2f to %.2f" % (min(ld), max(ld))) if ld else "", len(figs)))
    ok = all(min(nm) <= x <= max(nm) for x in nm) and len(figs) >= 2
    print("CHECK %-4s the ranges are the least and the greatest of the rows above" % ("ok" if ok else "FAIL"))
    return ok


def checks(label, raw, by, recs, problems):
    ok = True

    def c(name, good, detail=""):
        nonlocal ok
        ok = ok and good
        print("CHECK %-4s %s: %s%s" % ("ok" if good else "FAIL", label, name, (" - " + detail) if detail and not good else ""))

    c("every line parses and the file ends with a newline", not problems, "; ".join(problems[:3]))
    c("the bytes by type add up to the file's size", sum(sum(v) for v in by.values()) == len(raw),
      "%d against %d" % (sum(sum(v) for v in by.values()), len(raw)))
    c("the records counted equal the file's newline count", len(recs) == raw.count(b"\n"))
    return ok


def controls(raw):
    """Each check must go red on a damaged copy of the file."""
    print("== controls")
    good = True
    cases = [
        ("a record torn in the middle", raw[: len(raw) // 2]),
        ("a garbage line appended", raw + b"not json\n"),
        ("the final newline cut", raw[:-1]),
    ]
    for name, dmg in cases:
        by, recs, problems = analyse(dmg)
        red = bool(problems) or sum(sum(v) for v in by.values()) != len(dmg) or len(recs) != dmg.count(b"\n")
        print("CONTROL %-4s %s: the checks %s" % ("ok" if red else "FAIL", name, "go red, as they must" if red else "STAY GREEN"))
        good = good and red
    return good


def report_dir(label, path):
    """A directory the lead copied back from a batch: its files and bytes, by name (no path is printed)."""
    sizes = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            sizes.append((os.path.getsize(os.path.join(root, f)), f))
    sizes.sort(reverse=True)
    total = sum(s for s, _ in sizes)
    print("== %s (a directory of records copied back from a batch)" % label)
    print("files    : %d files, %s bytes in all; the largest: %s" %
          (len(sizes), format(total, ","), ", ".join("%s %s B" % (n, format(s, ",")) for s, n in sizes[:3])))
    nm = sum(1 for _, n in sizes if n == "metrics.jsonl" or n.endswith(".jsonl"))
    print("           %d of them are jsonl records; a logs/ directory of a run: %s" %
          (nm, "present" if any(os.path.basename(r) == "logs" for r, _d, _f in os.walk(path)) else "none"))
    good = total == sum(s for s, _ in sizes)
    print("CHECK %-4s %s: the bytes by file add up to the directory's total" % ("ok" if good else "FAIL", label))
    return good


def parse_arg(a):
    """LABEL=PATH or LABEL=PATH@N -> (label, path, N or None); an `@` in a path that is not followed by digits only is part of it."""
    label, _, path = a.partition("=")
    head, sep, tail = path.rpartition("@")
    if sep and head and tail.isdigit():
        return label, head, int(tail)
    return label, path, None


def pick_run(whole, n):
    """(first line, last line, bytes) of the n-th run (1-based) of a file, or None when the file has no n-th run."""
    runs = split_runs(whole)
    if 1 <= n <= len(runs):
        return runs[n - 1]
    return None


def controls_runs(whole):
    """The run selection must refuse a run the file does not have, and the runs must add up to the file."""
    runs = split_runs(whole)
    a = pick_run(whole, len(runs) + 1) is None and pick_run(whole, 0) is None
    print("CONTROL %-4s a run the file does not have (%d and 0) is refused, not read as another" % ("ok" if a else "FAIL", len(runs) + 1))
    joined = b"".join(r[2] for r in runs)
    b = whole.endswith(joined)
    damaged = whole[:-1] if whole else whole
    c = not damaged.endswith(joined)
    print("CONTROL %-4s a file one byte short is not the runs it was split into (the partition check can fail)" % ("ok" if c else "FAIL"))
    return a and b and c


def main(argv):
    try:
        sys.stdout.reconfigure(newline="\n")      # LF on every platform, so a capture is the same bytes everywhere
    except (AttributeError, ValueError):
        pass
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 64
    allok = True
    first = None
    multi = None
    figs = []
    for a in args:
        label, path, part = parse_arg(a)
        if os.path.isdir(path):
            allok = report_dir(label, path) and allok
            print()
            continue
        with open(path, "rb") as fh:
            whole = fh.read()
        raw, note = whole, None
        if part is not None:
            runs = split_runs(whole)
            got = pick_run(whole, part)
            if got is None:
                print("== %s\nCHECK FAIL %s: the file has %d runs, so there is no run %d" % (label, label, len(runs), part))
                allok = False
                print()
                continue
            first_ln, last_ln, raw = got
            joined = b"".join(r[2] for r in runs)
            part_ok = whole.endswith(joined)
            note = "run %d of %d in its file: lines %d to %d of %d; the whole file is %s bytes, sha256 %s" % (
                part, len(runs), first_ln, last_ln, whole.count(b"\n"), format(len(whole), ","), hashlib.sha256(whole).hexdigest())
            multi = multi or whole
        first = first or raw
        by, recs, problems, f = report(label, raw, note)
        figs.append(f)
        allok = checks(label, raw, by, recs, problems) and allok
        if part is not None:
            print("CHECK %-4s %s: the file's runs, in order, are the file from its first run_start to its end" % ("ok" if part_ok else "FAIL", label))
            allok = allok and part_ok
        print()
    if len(figs) >= 2:
        allok = summary(figs) and allok
        print()
    if "--controls" in argv and first is not None:
        allok = controls(first) and allok
        if multi is not None:
            allok = controls_runs(multi) and allok
    print("volumes: %s" % ("every check held" if allok else "A CHECK FAILED"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
