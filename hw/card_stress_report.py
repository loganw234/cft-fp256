#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Read a long run's metrics.jsonl and print an account of it: the header, the totals, a row
per (image, leg), the telemetry, every failure, the sweep's coverage and every disagreement,
and the run's uptime and gaps.

    python3 hw/card_stress_report.py RUN_DIR [--json FILE] [--no-write] [--gap-seconds N] [--also DIR]... [--no-git]

It runs at any time, during a run or after. A last line that does not parse is the driver
caught mid-append: noted, skipped, not an error. A line in the middle that does not parse is
named FIRST and loudly, and left out. The text goes to stdout and to RUN_DIR/report.txt,
replaced whole each time (the report is derived; metrics.jsonl is the record). --json writes
the same figures as data: render() builds the text from that summary alone, so the two cannot
disagree. The driver runs this after every cycle (hw/card_stress.py, refresh_report), with a
two-minute limit and its output discarded - hence report.txt is the output that matters, and a
failure of the report itself rewrites it to say so instead of leaving a stale account that
looks current.

Exit status: 0 a report was made (lines that do not parse do not change it); 2 there is
nothing to report (RUN_DIR or metrics.jsonl missing, unreadable, or without one record, or a
usage error); 1 the report was printed but a file could not be written; 3 the report itself
failed (a bug; the traceback is on stderr).

Everything is computed from the records; nothing is read from the box. One thing besides the records is read, by the
coverage-by-tree section alone (since 2026-10-22, parcel RG): git of the checkout this file is in. A run_start that recorded
no tree has it read from its commit (`git rev-parse COMMIT:rtl`, and `COMMIT:host`) when that commit is in the checkout and
the run recorded its own checkout clean - card_stress_lib.resolve_tree, the rule the driver's --resume counts by - and the
class says "read from git". `--no-git` (summarize(rev=None)) reads the records alone. A figure that cannot
be computed is "-" or "n/a", never 0. Choices a reader could otherwise take another way:
  - Times are shown as the records give them (ts, start, end: the box's local clock). The
    deadline's epoch is found with the box's UTC offset read off the records' own ts/epoch
    pairs, so a copy read in another time zone still gets the remaining time right.
  - A row is (image, leg name, kind): a recovery leg reuses the battery's name (dt-i), so it
    gets a row of its own, labelled "dt-i [recovery]"; a battery leg is labelled by its name.
    Every sweep leg of an image is one row, "sweep (all items)"; its rates mix items whose
    rates differ, so its trend reflects the mix as well as the card (the text says so).
  - Duration statistics skip legs that did not run (status skipped or error). Rate statistics
    use every leg that carries a rate, in start order; the trend compares the median of the
    first n//4 rates with the last n//4 (n >= 4 needed), as a percentage of the first.
  - The union of leg intervals counts every leg record with a start and an end, including a
    skipped leg, which is a zero-length point. (lib.merge_intervals refuses an empty
    interval, so the time axis has its own union; the sweep's coverage uses the lib's.) A
    gap is the space between two pieces of the union longer than --gap-seconds; "longest gap"
    is the longest of all. Events and run_start/run_end/build records at a gap's ends count
    as inside it.
  - A sweep slice is completed when its status is pass or fail; the coverage, the slice
    counts and the highest seed_n are lib.sweep_coverage's. A sweep leg whose fields it
    could not take (a range outside [0, 2**32), a non-integer seed_n) is named and left out.
  - Every sweep item has a REACH: "tile" if its work runs on the card's tile, "host" if it is
    libcft's host code run against the CPU (the conversions, next, logB, class, remainder: a
    full-space test of the library in which the tile computes nothing). It is what the item's
    first record says (`sweep.reach`, written by the driver from card_stress_lib.OP_REACH), or,
    for a record from before the driver wrote it, what that table says of the record's op;
    "unknown" when neither does. It is the LAST column of the sweep tables, so the tables read as
    they did and a reader that takes columns by position still does. The coverage is totalled by
    reach, so the report says how much of the exhaustive space the tile itself has seen.
  - COVERAGE BY TREE (the section after the sweep's; since 2026-10-20). What a slice is evidence
    about depends on what it ran: a TILE item, on the RTL it ran on; a HOST item, on the library's
    source and the compiler. So that section counts a tile item's coverage per RTL tree - the git
    tree hash of rtl/ of the checkout the run started from, which the driver records in run_start
    as tree.rtl - with the images (quad, single, deep) reported separately beneath it, each by what
    it covered alone; and a host item's per library source: tree.host_src, the tree hash of host/,
    with tree.cc, the C compiler's version line. A tree with uncommitted changes is a class of its
    own (tree.rtl_dirty, tree.host_src_dirty); a run that recorded none of it (every run before
    2026-10-20) has it READ FROM GIT where git can say (above): the class of the tree a run that recorded
    it would be in, its label saying "read from git" at commits it names sorted and its `derived_from_git`
    (in --json) listing {commit, dir, tree} for each run whose tree in that class was read, sorted by
    commit, dir and tree whatever the order of the runs, [] when none was. (A `rev` that is
    not git - a function a caller gave to summarize() - is used as given and not called git: the label says
    "taken from the given rev, not git", `sweep.trees.git.read` is false and `source` is "given rev", and
    `derived_from_git` lists what the function answered.) What git cannot
    say - a commit the checkout lacks, a run not recorded clean, a recorded tree that git does not give
    for its commit, no git - is kept apart by its commit, as "not recorded" or "unknown" ("not recorded or
    unknown" for a class that gathers both, whatever their order), with resolve_tree's reason in the
    label. A compiler line is never read: such a run's host class says "compiler not recorded".
    `sweep.trees.git` ({read, source, problem}) says whether git was read, where the trees came from and
    what stopped git (git is asked at most 10 s a lookup and 40 s in all, once for a commit and directory).
    A slice belongs to the LAST run_start
    before it in its file, so a run resumed from another checkout counts what follows under that
    checkout's tree. `--also DIR` adds other runs' directories to that section (and only to it):
    coverage accumulated over runs, each slice under its own run's tree, so two trees are never
    summed. The first sections are of RUN_DIR alone, as they were.
  - SPACE (since 2026-10-21, parcel DR3). An exhaustive item's coverage is counted over ITS space, which the catalog gives
    (`Item.space`): 2**32 encodings for every item the scripts' campaign has, the mode's indices for the coverage wave's hard-case
    and class-level items (21,235,788 for div32-hard, 35,840 for rint64-class, ...). An item whose space is not 2**32 says so in the
    tables ("rint64-class-rne [35,840 indices]") and its 100% is of its own indices; a class-level pass is a claim at the class level
    (L2, PLAUSIBLE and not proved) and a hard-case pass a space of constructed operands, and the report says both under its table.
    A record of an item the catalog does not name is counted over 2**32, as every item was.
  - NO READING (since 2026-10-22, KL-32). The U50's FPGA HBM temperature reads 0 in most samples of a long run (670 of 865 on 2026-10-19,
    between runs of readings from 27 to 35). A 0 from an HBM temperature is taken as no reading (card_stress_lib.no_reading), counted by
    name in the telemetry section ("NO READING: ... read 0 in N of M samples") and left out of that label's samples and range; every other
    label, a rail that reads a flat 0 included, is reported as it always was. The summary's `telemetry.no_reading` has the counts.
  - THE IMAGES' MANIFESTS (since 2026-10-22, KL-42). The header's images line says, for a run_start that recorded it, what each image's
    manifest gave: the commit it was built at and that commit's rtl tree when it is this checkout's, that it was NOT CHECKED (no
    manifest, a commit the checkout lacks), or that the driver REFUSED it (run_start is written before the build step that refuses, so a
    run that stopped there has its reason in this line). A run_start from before records none, and its line is what it was.
  - PASS SIZE (with `--sweep-chunk`). A sweep slice carries `sweep.batch`, the BATCH its tool ran at (a slice with none ran the default
    tools' 4096); an item with a slice at another batch gets a line saying how many ran at each, since the tools compare flags per batch,
    and random coverage by tree is a row per (item, batch): a chunked item's slices are never summed with the default tools'. A run with
    no chunked slice is reported as it always was.
"""
from __future__ import annotations

import argparse
import bisect
import calendar
import datetime
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
import traceback
from collections import Counter
from typing import Any, Callable, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)            # python -I does not put the script's directory there
from card_stress_lib import (CPU, DEFAULT_BATCH, EXH, GIT_HASH, HOST, TILE, covered, first_gap, is_hbm_temperature, iso,  # noqa: E402
                             manifest_brief, merge_intervals, no_reading, read_records, reach_of, record_batch, resolve_tree,
                             run_classes, slice_reach, sweep_coverage, sweep_items, tree_key)

# What the catalog says of each item: the space its coverage is counted over (2^32 encodings for the fp32-operand items, the
# indices of a mode's own space for the hard-case and class-level items) and what a pass claims ("exhaustive", "hard", "class",
# "random"). An item the catalog does not name (a record of another tree's) is counted over 2**32, as every item was before.
# The catalog with its wide-format items (parcel HXc: sweep_items(mpfr=True), which a run has only with --mpfr-prefix), so that a run that
# served them has them counted over their own spaces; a run that did not is reported as it was. ITEM_CLAIM: what a pass over a wide item's
# whole space claims, named by space and level (Item.claim), said under the sweep table for each wide mode the run served.
_CATALOG = {it.name: it for it in sweep_items(mpfr=True)}
ITEM_SPACE = {n: it.space for n, it in _CATALOG.items()}
ITEM_LEVEL = {n: it.level for n, it in _CATALOG.items()}
ITEM_CLAIM = {n: it.claim for n, it in _CATALOG.items() if it.claim}

KNOWN = ("pass", "fail", "timeout", "no_device", "parse_error", "skipped", "error")
SWEEP_ROW = "sweep (all items)"
SERIES_MAX = 12                  # rates shown per row, evenly picked
LABELS_SHOWN = 40                # telemetry labels shown, widest range first
RAW_CHARS = 600                  # raw telemetry text shown when nothing parsed
DISAGREE_SHOWN = 3               # disagreement lines shown per failing leg (section 5)
GAP_EVENTS_SHOWN = 40            # event lines shown per gap in the text (the JSON has all)
BAD_LINES_SHOWN = 100
HOST_FIRST = ("host.load1", "host.load5", "host.load15", "host.mem_avail_mb", "host.mem_total_mb")
TS_FMT = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _num(x: Any) -> Optional[Any]:
    """A finite number, or None: a bool, a string, NaN and infinity are not numbers here."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    if isinstance(x, float) and not math.isfinite(x):
        return None
    return x


def _int(x: Any) -> Optional[int]:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and math.isfinite(x) and x == int(x):
        return int(x)
    return None


def _str(x: Any) -> Optional[str]:
    return x if isinstance(x, str) else None


def _bool(x: Any) -> Optional[bool]:
    return x if isinstance(x, bool) else None


_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _line(x: Any, limit: Optional[int] = None) -> str:
    """One line: control characters and runs of white space become one space. A record's
    text can then never forge a section heading or break a table."""
    s = " ".join(_CTRL.sub(" ", str(x)).split())
    if limit is not None and len(s) > limit:
        s = s[:max(0, limit - 3)] + "..."
    return s


_CTRL_KEEP_NL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f]")


def _scrub(x: Any, keep_newlines: bool = False) -> Any:
    """The summary with every control character in its strings and keys made a space, so that
    whatever a record says (a leg's name, an event's detail) can never forge a heading or break
    a table. Telemetry's raw text keeps its line breaks, and is shown indented."""
    if isinstance(x, str):
        return (_CTRL_KEEP_NL if keep_newlines else _CTRL).sub(" ", x)
    if isinstance(x, dict):
        return {_scrub(k): _scrub(v, k == "first_raw") for k, v in x.items()}
    if isinstance(x, list):
        return [_scrub(v, keep_newlines) for v in x]
    return x


def _when(text: Any, epoch: Any) -> Optional[str]:
    """The record's own local-time string (the box's clock) where it has one, else the epoch
    formatted by the lib's iso() (this machine's zone)."""
    if isinstance(text, str) and text.strip():
        return text.strip()
    e = _num(epoch)
    return iso(e) if e is not None else None


def _clean(x: Any, depth: int = 0) -> Any:
    """JSON-safe and round-trip stable: string keys, lists for tuples, None for NaN/inf."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if x is None or isinstance(x, (str, int, bool)):
        return x
    if depth > 40:
        return None
    if isinstance(x, dict):
        return {str(k): _clean(v, depth + 1) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v, depth + 1) for v in x]
    return str(x)


def _box_offset(recs: List[Dict[str, Any]]) -> Optional[int]:
    """The box's offset from UTC in seconds, read off the last few records' own ts and epoch.
    ts is the epoch's whole second in local time, so ts-as-UTC minus epoch is the offset to
    within a second (and a rounded epoch can add one more); real offsets are whole quarter
    hours, so rounding to 900 s recovers it exactly. A DST change between the last record and
    the deadline is not seen: the remaining time is then an hour out, which the text cannot tell."""
    xs: List[float] = []
    for r in reversed(recs):
        ts, ep = r.get("ts"), _num(r.get("epoch"))
        if isinstance(ts, str) and ep is not None:
            try:
                xs.append(calendar.timegm(time.strptime(ts.strip(), TS_FMT)) - ep)
            except (ValueError, OverflowError):
                continue
            if len(xs) >= 9:
                break
    if not xs:
        return None
    return 900 * int(round(statistics.median(xs) / 900.0))


def _clock_epoch(text: str, offset: Optional[int]) -> Optional[float]:
    """A deadline string ('YYYY-MM-DD HH:MM[:SS]', a 'T' for the space, or an ISO time with a
    zone) as an epoch, in the box's zone when `offset` is known, else this machine's."""
    t = text.strip()
    for fmt in (TS_FMT, "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            st = time.strptime(t, fmt)
        except ValueError:
            continue
        try:
            return float(calendar.timegm(st) - offset) if offset is not None else float(time.mktime(st))
        except (OverflowError, ValueError):
            return None
    try:
        dt = datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None
    try:
        if dt.tzinfo is not None:
            return dt.timestamp()
        frac = dt.microsecond / 1e6
        if offset is not None:
            return calendar.timegm(dt.timetuple()) + frac - offset
        return time.mktime(dt.timetuple()) + frac
    except (OverflowError, ValueError, OSError):
        return None


def _time_union(items: List[Tuple[float, float, Optional[str], Optional[str]]]) -> List[list]:
    """Pieces [start, end, start_text, end_text] of the union of intervals; touching
    intervals join, and a zero-length one is a piece of its own unless something covers it."""
    out: List[list] = []
    for s, e, st, et in sorted(items, key=lambda x: (x[0], x[1])):
        if out and s <= out[-1][1]:
            if e > out[-1][1]:
                out[-1][1], out[-1][3] = e, et
        else:
            out.append([s, e, st, et])
    return out


def _pick_series(vals: List[Any], k: int = SERIES_MAX) -> List[Any]:
    """At most k values, evenly picked, first and last always in."""
    n = len(vals)
    if n <= k:
        return list(vals)
    return [vals[(2 * j * (n - 1) + (k - 1)) // (2 * (k - 1))] for j in range(k)]


# ---------------------------------------------------------------------------
# summarize: the figures, as plain data
# ---------------------------------------------------------------------------

def _leg_views(by_type: Dict[str, List[Tuple[int, Dict[str, Any]]]]) -> List[Dict[str, Any]]:
    views = []
    for i, r in by_type.get("leg", []):
        se, ee = _num(r.get("start_epoch")), _num(r.get("end_epoch"))
        t = se if se is not None else (ee if ee is not None else _num(r.get("epoch")))
        views.append({
            "i": i, "r": r, "image": _str(r.get("image")), "name": _str(r.get("leg")),
            "kind": _str(r.get("kind")), "status": _str(r.get("status")), "se": se, "ee": ee,
            "order": (0, t, i) if t is not None else (1, 0.0, i),
            "counts": r.get("counts") if isinstance(r.get("counts"), dict) else None,
        })
    return views


def _header(objs: List[Dict[str, Any]], by_type: Dict[str, List[Tuple[int, Dict[str, Any]]]],
            now: float, offset: Optional[int]) -> Dict[str, Any]:
    starts: List[Dict[str, Any]] = []
    for i, r in by_type.get("run_start", []):
        st = r.get("settings") if isinstance(r.get("settings"), dict) else {}
        tr = r.get("tree") if isinstance(r.get("tree"), dict) else {}
        starts.append({
            "i": i, "ts": _when(r.get("ts"), r.get("epoch")), "epoch": _num(r.get("epoch")),
            "run_id": _str(r.get("run_id")), "host": _str(r.get("host")), "out": _str(r.get("out")),
            "commit": _str(tr.get("commit")), "dirty": _bool(tr.get("dirty")),
            "rtl": _str(tr.get("rtl")), "rtl_dirty": _bool(tr.get("rtl_dirty")), "host_src": _str(tr.get("host_src")),
            "host_src_dirty": _bool(tr.get("host_src_dirty")), "cc": _str(tr.get("cc")),
            "deadline": _str(r.get("deadline")) or None, "until": _str(st.get("until")) or None,
            "quick": _bool(st.get("quick")), "dry_run": _bool(st.get("dry_run")),
            "resumed": _bool(r.get("resumed")),
            "images": r.get("images") if isinstance(r.get("images"), dict) else None,
        })

    def distinct(key: str) -> List[str]:
        out: List[str] = []
        for s in starts:
            if s[key] is not None and s[key] not in out:
                out.append(s[key])
        return out

    trees: List[Dict[str, Any]] = []
    for s in starts:
        t = {"commit": s["commit"], "dirty": s["dirty"]}
        t.update({k: s[k] for k in ("rtl", "rtl_dirty", "host_src", "host_src_dirty", "cc") if s[k] is not None})
        if (t["commit"] is not None or t["dirty"] is not None) and t not in trees:
            trees.append(t)

    run_ends = []
    for i, r in by_type.get("run_end", []):
        run_ends.append({"i": i, "ts": _when(r.get("ts"), r.get("epoch")), "epoch": _num(r.get("epoch")),
                         "reason": _str(r.get("reason")), "exit": _int(r.get("exit")),
                         "cycles": _int(r.get("cycles"))})
    # ended: the last run_end comes after the last run_start (a resume appends a run_start
    # and the run is then running again, whatever ended before)
    ended = bool(run_ends) and run_ends[-1]["i"] > (starts[-1]["i"] if starts else -1)

    stamped = [(e, i) for i, r in enumerate(objs) if (e := _num(r.get("epoch"))) is not None]
    last = None
    if stamped:
        le, li = max(stamped)
        last = {"ts": _when(objs[li].get("ts"), le), "epoch": le}
    age = (now - last["epoch"]) if (last is not None and not ended) else None

    cur = starts[-1] if starts else None
    dl = None
    if cur is not None and (cur["deadline"] or cur["until"]):
        text = cur["deadline"] or cur["until"]
        ep = _clock_epoch(text, offset)
        ref = run_ends[-1]["epoch"] if ended else now
        dl = {"text": text, "source": "deadline" if cur["deadline"] else "settings.until",
              "epoch": ep, "measured_at": "run_end" if ended else "now",
              "remaining_s": (ep - ref) if (ep is not None and ref is not None) else None}

    flags = None
    if cur is not None:
        differs = any((s["quick"], s["dry_run"]) != (cur["quick"], cur["dry_run"]) for s in starts)
        flags = {"quick": cur["quick"], "dry_run": cur["dry_run"], "differs": differs}

    images = None
    for s in reversed(starts):
        if s["images"]:
            images = {}
            for name, d in s["images"].items():
                d = d if isinstance(d, dict) else {}
                mf = d.get("manifest") if isinstance(d.get("manifest"), dict) else None
                images[str(name)] = {"sha256": _str(d.get("sha256")), "bytes": _int(d.get("bytes")),
                                     "tiles": _int(d.get("tiles")),
                                     "manifest": ({"state": _str(mf.get("state")), "commit": _str(mf.get("commit")),
                                                   "rtl": _str(mf.get("rtl")), "file": _str(mf.get("file"))} if mf else None)}
            break

    return {
        "run_ids": distinct("run_id"), "hosts": distinct("host"), "outs": distinct("out"),
        "trees": trees,
        "started": ({"ts": starts[0]["ts"], "epoch": starts[0]["epoch"]} if starts else None),
        "run_starts": len(starts), "resumed_marked": sum(1 for s in starts if s["resumed"] is True),
        "running": not ended, "last_record": last, "age_s": age,
        "run_ends": [{k: v for k, v in e.items() if k != "i"} for e in run_ends],
        "deadline": dl, "flags": flags, "images": images,
    }


def _totals(by_type: Dict[str, List[Tuple[int, Dict[str, Any]]]], views: List[Dict[str, Any]]) -> Dict[str, Any]:
    status = Counter(v["status"] if v["status"] is not None else "(missing)" for v in views)
    statuses = {k: status.get(k, 0) for k in KNOWN}
    for k, n in status.items():
        if k not in statuses:
            statuses[k] = n
    cs, ce = by_type.get("cycle_start", []), by_type.get("cycle_end", [])
    started = Counter(c for _, r in cs if (c := _int(r.get("cycle"))) is not None)
    ended = Counter(c for _, r in ce if (c := _int(r.get("cycle"))) is not None)
    failed = [f for _, r in ce if (f := _int(r.get("failed"))) is not None]
    builds = []
    for _, r in by_type.get("build", []):
        steps = r.get("steps") if isinstance(r.get("steps"), list) else []
        builds.append({
            "ts": _when(r.get("ts"), r.get("epoch")), "ok": _bool(r.get("ok")), "steps": len(steps),
            "failed_steps": [{"name": _str(s.get("name")) or "?", "detail": _str(s.get("detail"))}
                             for s in steps if isinstance(s, dict) and s.get("ok") is False]})
    return {
        "records": {t: len(v) for t, v in by_type.items()},
        "legs": {"total": len(views), "by_status": statuses},
        "cycles": {
            "started": len(cs), "ended": len(ce),
            "unfinished": sorted(c for c, n in started.items() if n > ended.get(c, 0)),
            "by_image": dict(Counter(_str(r.get("image")) or "-" for _, r in cs)),
            "ended_reporting_failed": len(failed), "ended_with_failed": sum(1 for f in failed if f > 0),
        },
        "builds": builds,
    }


def _rate_stats(rates: List[Tuple[Any, Any, str]]) -> Optional[Dict[str, Any]]:
    if not rates:
        return None
    rates = sorted(rates, key=lambda x: x[0])
    units = Counter(u for _, _, u in rates)
    unit = units.most_common(1)[0][0]            # the most common; a tie goes to the first seen
    vals = [v for _, v, u in rates if u == unit]
    n = len(vals)
    d: Dict[str, Any] = {
        "unit": unit, "n": n, "median": statistics.median(vals), "min": min(vals), "max": max(vals),
        "trend_pct": None, "trend_note": None, "first_quarter_median": None,
        "last_quarter_median": None, "series": _pick_series(vals),
        "other_units": {u: c for u, c in units.items() if u != unit},
    }
    if n < 4:
        d["trend_note"] = "too few"
    else:
        q = n // 4
        m1, m2 = statistics.median(vals[:q]), statistics.median(vals[-q:])
        d["first_quarter_median"], d["last_quarter_median"] = m1, m2
        if m1 == 0:
            d["trend_note"] = "n/a"
        else:
            d["trend_pct"] = (m2 - m1) / m1 * 100.0
    return d


def _rows(views: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    acc: Dict[tuple, Dict[str, Any]] = {}
    img_order: Dict[Optional[str], int] = {}
    for v in views:
        img = v["image"]
        img_order.setdefault(img, len(img_order))
        if v["kind"] == "sweep":
            key, label = (img, SWEEP_ROW, "sweep"), SWEEP_ROW
        else:
            # a battery leg is listed by its name; any other kind is named beside it, because a
            # recovery leg reuses the battery's name (dt-i) and must not be summed into it
            key = (img, v["name"], v["kind"])
            nm = v["name"] if v["name"] is not None else "(unnamed)"
            label = nm if v["kind"] == "battery" else f"{nm} [{v['kind'] if v['kind'] is not None else '?'}]"
        a = acc.get(key)
        if a is None:
            a = acc[key] = {"image": img, "leg": label, "kind": key[2], "runs": 0, "status": Counter(),
                            "checks": None, "cases": None, "durations": [], "rates": [],
                            "items": set(), "first": v["i"]}
        r, st = v["r"], v["status"]
        a["runs"] += 1
        a["status"][st if st is not None else "(missing)"] += 1
        c = v["counts"]
        if c:
            for fld in ("checks", "cases"):
                n = _int(c.get(fld))
                if n is not None:
                    a[fld] = (a[fld] or 0) + n
        dur = _num(r.get("duration_s"))
        if dur is not None and dur >= 0 and st not in ("skipped", "error"):
            a["durations"].append(dur)
        rate = r.get("rate")
        if isinstance(rate, dict):
            val = _num(rate.get("value"))
            if val is not None:
                a["rates"].append((v["order"], val, _str(rate.get("unit")) or "?"))
        if v["kind"] == "sweep":
            sw = r.get("sweep")
            if isinstance(sw, dict) and isinstance(sw.get("item"), str):
                a["items"].add(sw["item"])
    rows = []
    for key, a in sorted(acc.items(), key=lambda kv: (img_order[kv[0][0]], kv[0][2] == "sweep", kv[1]["first"])):
        durs = a["durations"]
        known = sum(a["status"].get(k, 0) for k in KNOWN)
        rows.append({
            "image": a["image"], "leg": a["leg"], "kind": a["kind"], "runs": a["runs"],
            "statuses": {k: a["status"].get(k, 0) for k in KNOWN}, "other": a["runs"] - known,
            "checks": a["checks"], "cases": a["cases"],
            "duration": {"n": len(durs),
                         "median": statistics.median(durs) if durs else None,
                         "min": min(durs) if durs else None, "max": max(durs) if durs else None},
            "rate": _rate_stats(a["rates"]),
            "items": len(a["items"]) if a["kind"] == "sweep" else None,
        })
    return rows


def _label_stats(label: str, pts: List[Tuple[Any, int, Any]]) -> Dict[str, Any]:
    """pts: (epoch, file index, value). The slope is the least-squares line of value against
    epoch, per hour; it needs three samples and two different times."""
    pts = sorted(pts, key=lambda p: (p[0], p[1]))
    vs = [p[2] for p in pts]
    n = len(vs)
    lo, hi = min(vs), max(vs)
    slope = None
    if n >= 3:
        x0 = pts[0][0]
        xs = [p[0] - x0 for p in pts]
        mx = math.fsum(xs) / n
        sxx = math.fsum((x - mx) ** 2 for x in xs)
        if sxx > 0:
            y0 = vs[0]            # centred on the first value, so a constant series is exactly flat
            slope = math.fsum((x - mx) * (v - y0) for x, v in zip(xs, vs)) / sxx * 3600.0
    return {"label": label, "n": n, "min": lo, "max": hi, "mean": math.fsum(vs) / n,
            "first": vs[0], "last": vs[-1], "range": hi - lo, "slope_per_hour": slope}


def _telemetry(by_type: Dict[str, List[Tuple[int, Dict[str, Any]]]]) -> Dict[str, Any]:
    tel = by_type.get("telemetry", [])
    dev: Dict[str, List[Tuple[Any, int, Any]]] = {}
    host: Dict[str, List[Tuple[Any, int, Any]]] = {}
    zeros: Dict[str, List[int]] = {}       # an HBM temperature's label -> [samples that read 0, samples that read at all]
    with_values = 0
    errors: Counter = Counter()
    failed = 0
    first_raw = None
    for i, r in tel:
        ep = _num(r.get("epoch"))
        vals = r.get("values") if isinstance(r.get("values"), dict) else {}
        got = False
        for label, x in vals.items():
            n = _num(x)
            if n is not None:
                got = True
                if is_hbm_temperature(label):
                    # KL-32: this sensor reads 0 for no reading (card_stress_lib.no_reading): counted by name, and left out of the
                    # label's statistics, whose range was that artifact (0 to 35 over a run whose readings were 27 to 35)
                    zc = zeros.setdefault(str(label), [0, 0])
                    zc[1] += 1
                    if no_reading(label, n):
                        zc[0] += 1
                        continue
                if ep is not None:
                    dev.setdefault(str(label), []).append((ep, i, n))
        with_values += got
        if r.get("ok") is False:
            failed += 1
            errors[_str(r.get("error")) or "(no error text)"] += 1
        if first_raw is None and isinstance(r.get("raw"), str) and r["raw"].strip():
            first_raw = r["raw"]
        h = r.get("host") if isinstance(r.get("host"), dict) else {}
        if ep is None:
            continue
        for k, x in h.items():
            if k == "disk_free_gb" and isinstance(x, dict):
                for path, g in x.items():
                    n = _num(g)
                    if n is not None:
                        host.setdefault(f"host.disk_free_gb[{path}]", []).append((ep, i, n))
            else:
                n = _num(x)
                if n is not None:
                    host.setdefault(f"host.{k}", []).append((ep, i, n))

    def host_key(label: str) -> Tuple[int, Any]:
        if label in HOST_FIRST:
            return (0, HOST_FIRST.index(label))
        return (2, label) if label.startswith("host.disk_free_gb[") else (1, label)

    labels = sorted((_label_stats(k, v) for k, v in dev.items()), key=lambda d: (-d["range"], d["label"]))
    return {
        "samples": len(tel), "with_values": with_values, "without_values": len(tel) - with_values,
        "failed": failed,
        "by_when": dict(Counter(_str(r.get("when")) or "-" for _, r in tel)),
        "errors": [{"message": m, "count": c} for m, c in sorted(errors.items(), key=lambda kv: (-kv[1], kv[0]))],
        "labels": labels, "labels_total": len(labels),
        "no_reading": [{"label": k, "zero": z, "of": t, "kept": t - z} for k, (z, t) in sorted(zeros.items()) if z],
        "host": [_label_stats(k, host[k]) for k in sorted(host, key=host_key)],
        "first_raw": first_raw[:RAW_CHARS] if first_raw is not None else None,
        "first_raw_chars": len(first_raw) if first_raw is not None else None,
    }


def _failures(views: List[Dict[str, Any]]) -> Dict[str, Any]:
    bad: List[Dict[str, Any]] = []
    groups: Dict[tuple, Dict[str, Any]] = {}
    for v in sorted(views, key=lambda v: v["order"]):
        r, st = v["r"], v["status"]
        reason = _str(r.get("reason")) or None
        if st == "skipped":
            g = groups.setdefault((v["name"], reason), {"leg": v["name"], "reason": reason,
                                                        "count": 0, "images": []})
            g["count"] += 1
            if (v["image"] or "-") not in g["images"]:
                g["images"].append(v["image"] or "-")
        elif st != "pass":
            dis = r.get("disagreements")
            notes = r.get("notes")
            bad.append({
                "start": _when(r.get("start"), v["se"]), "start_epoch": v["se"], "image": v["image"],
                "leg": v["name"], "kind": v["kind"], "attempt": _int(r.get("attempt")),
                "status": st if st is not None else "(missing)", "rc": _int(r.get("rc")),
                "timed_out": _bool(r.get("timed_out")), "killed": _str(r.get("killed")),
                "reason": reason, "counts": v["counts"],
                "disagreements": [str(x) for x in dis] if isinstance(dis, list) else None,
                "notes": [str(x) for x in notes] if isinstance(notes, list) and notes else None,
                "log": _str(r.get("log")), "tile": _int(r.get("tile")),
            })
    return {
        "count": len(bad), "by_status": dict(Counter(b["status"] for b in bad)), "legs": bad,
        "skipped": {"count": sum(g["count"] for g in groups.values()), "groups": list(groups.values())},
    }


def _sweep_defect(r: Dict[str, Any]) -> Optional[str]:
    """Why lib.sweep_coverage could not take this completed sweep leg, or None."""
    sw = r.get("sweep")
    if sw is None:
        return None                       # no item: the lib passes over it
    if not isinstance(sw, dict):
        return "sweep is not an object"
    item = sw.get("item")
    if item is None or item == "":
        return None
    if not isinstance(item, str):
        return "item is not a string"
    if "lo" in sw or "hi" in sw:
        lo, hi = _int(sw.get("lo")), _int(sw.get("hi"))
        if lo is None or hi is None:
            return "lo and hi are not both integers"
        if not 0 <= lo < hi <= EXH:
            return f"range [{lo}, {hi}) is not inside [0, 2**32)"
    if "seed_n" in sw and _int(sw.get("seed_n")) is None:
        return "seed_n is not an integer"
    c = r.get("counts")
    if c is not None and not isinstance(c, dict):
        return "counts is not an object"
    if isinstance(c, dict) and "cases" in c and _int(c.get("cases")) is None:
        return "counts.cases is not an integer"
    return None


def _sweep(objs: List[Dict[str, Any]], views: List[Dict[str, Any]]) -> Dict[str, Any]:
    sviews = [v for v in views if v["kind"] == "sweep"]
    malformed, bad_ids = [], set()
    for v in sviews:
        if v["status"] in ("pass", "fail"):
            why = _sweep_defect(v["r"])
            if why:
                sw = v["r"].get("sweep")
                malformed.append({"item": sw.get("item") if isinstance(sw, dict) else None,
                                  "status": v["status"], "start": _when(v["r"].get("start"), v["se"]),
                                  "why": why})
                bad_ids.add(id(v["r"]))
    intervals, served, cases, seeds, dis = sweep_coverage([r for r in objs if id(r) not in bad_ids])

    completed = failed_slices = skipped = 0
    not_completed: Counter = Counter()
    incomplete: Counter = Counter()
    seen_kind: Dict[str, str] = {}
    seen_reach: Dict[str, Optional[str]] = {}
    for v in sviews:
        st, sw = v["status"], v["r"].get("sweep")
        sw = sw if isinstance(sw, dict) else {}
        item = sw.get("item") if isinstance(sw.get("item"), str) and sw.get("item") else None
        if st in ("pass", "fail"):
            completed += 1
            failed_slices += st == "fail"
        elif st == "skipped":
            skipped += 1
        else:
            not_completed[st if st is not None else "(missing)"] += 1
            if item:
                incomplete[item] += 1
        if st != "skipped" and item and item not in seen_kind:
            seen_kind[item] = ("exhaustive" if ("lo" in sw or "hi" in sw) else
                               "random" if ("seed_n" in sw or "seed" in sw or "count" in sw) else "other")
            # whether the item's work reaches the tile: what its first record says, else what the
            # catalog's table says of its op (a record from before the driver wrote `reach`); None when
            # neither knows - never a guess
            rch = sw.get("reach")
            seen_reach[item] = rch if rch in (TILE, HOST) else reach_of(sw.get("op"))
    nc = {k: not_completed.get(k, 0) for k in ("timeout", "no_device", "parse_error")}
    for k, n in not_completed.items():
        if k not in nc:
            nc[k] = n

    items = sorted(set(served) | set(seen_kind))
    exh, rnd, other = [], [], []
    for it in items:
        base = {"item": it, "reach": seen_reach.get(it), "slices": served.get(it, 0), "cases": cases.get(it, 0),
                "incomplete": incomplete.get(it, 0)}
        if it in intervals or (it not in seeds and seen_kind.get(it) == "exhaustive"):
            iv = intervals.get(it, [])
            space = ITEM_SPACE.get(it, EXH)
            gap = first_gap(iv, space)
            cov = covered(iv)
            base.update(covered=cov, total=space, pct=100.0 * cov / space, intervals=len(merge_intervals(iv)),
                        first_gap=list(gap) if gap else None, level=ITEM_LEVEL.get(it))
            exh.append(base)
        elif it in seeds or seen_kind.get(it) == "random":
            base["max_seed_n"] = seeds.get(it)
            rnd.append(base)
        else:
            other.append(base)
    n_exh = len(exh)
    tot_cov = sum(e["covered"] for e in exh)
    # by reach: which of the items exercise the tile at all (tile first, then host, then the ones
    # nothing says anything of); only the kinds present are listed
    by_reach = []
    for key in (TILE, HOST, None):
        mine = [e for e in exh if e["reach"] == key]
        if mine:
            cov = sum(e["covered"] for e in mine)
            tot = sum(e["total"] for e in mine)
            by_reach.append({"reach": key, "items": len(mine), "covered": cov, "total": tot,
                             "pct": 100.0 * cov / tot,
                             "complete_items": sum(1 for e in mine if e["covered"] == e["total"])})
    rnd_reach = [{"reach": key, "items": sum(1 for e in rnd if e["reach"] == key)}
                 for key in (TILE, HOST, None) if any(e["reach"] == key for e in rnd)]
    tot_all = sum(e["total"] for e in exh)
    # the pass size each item's completed slices ran at, where any ran at one the records name (the chunked tools): per item,
    # {batch: slices}; a slice with no `batch` ran the default tools' 4096. Empty - and the report unchanged - for a run that
    # used no chunked tool
    by_batch: Dict[str, Counter] = {}
    for v in sviews:
        sw = v["r"].get("sweep")
        if v["status"] in ("pass", "fail") and isinstance(sw, dict) and isinstance(sw.get("item"), str) and sw["item"] \
                and id(v["r"]) not in bad_ids:
            by_batch.setdefault(sw["item"], Counter())[record_batch(sw)] += 1
    batches = [{"item": it, "by_batch": {str(b): n for b, n in sorted(c.items())}}
               for it, c in sorted(by_batch.items()) if any(b != DEFAULT_BATCH for b in c)]
    return {
        "exhaustive": exh, "random": rnd, "other": other, "batches": batches,
        "total_exhaustive": {"items": n_exh, "covered": tot_cov, "total": tot_all,
                             "pct": (100.0 * tot_cov / tot_all) if n_exh else None,
                             "complete_items": sum(1 for e in exh if e["covered"] == e["total"]),
                             "by_reach": by_reach},
        "random_by_reach": rnd_reach,
        "completed": completed, "failed": failed_slices, "not_completed": nc, "skipped": skipped,
        "outside_coverage": completed - sum(served.values()), "malformed": malformed,
        "disagreements": [{"item": d["item"], "image": d["image"], "start": d["start"], "sweep": d["sweep"],
                           "counts": d["counts"], "lines": [str(x) for x in d["lines"]], "log": d["log"]}
                          for d in dis],
    }


IMAGE_ORDER = ("quad", "single", "deep", CPU)
TREE_KINDS = (TILE, HOST, "unknown")

# git, for a run_start that recorded no tree (parcel RG, 2026-10-22). The driver refreshes this report after every cycle with a two-minute
# limit, so git is bounded: a lookup waits GIT_TIMEOUT_S at most and all of one reader's lookups GIT_BUDGET_S (the driver's own git_tree allows
# itself 30 s a lookup and no total).
GIT_TIMEOUT_S = 10.0
GIT_BUDGET_S = 40.0
LABEL_COMMITS = 3                        # the commits a class's label names where trees were read from git (derived_from_git lists them all)
_CHECKOUT = os.path.dirname(_HERE)      # the repository that holds this file's hw/: the checkout the report reads git of
_REPO_GIT = object()                     # summarize()'s default `rev`: git of that checkout (None is "read none", a callable is used as given)
_checkout_git: Optional["GitTrees"] = None


class GitTrees:
    """`git rev-parse COMMIT:REL` in one checkout - the `rev` card_stress_lib.resolve_tree takes, and what the driver's git_tree does - bounded and
    kept. Called (commit, rel), rel being 'rtl' or 'host', it gives the tree hash of that directory at a whole 40-hex commit, or None where git
    cannot say (the commit is not in the checkout, or has no such directory, or is not a whole hash). BOUNDED: a lookup waits `timeout` seconds
    at most and all of them together `budget`; the first lookup that git does not answer in time, that cannot be run, or that finds no
    repository sets `problem` (a string with no path in it) and git is not asked again, so what it could not read is said to be unread and
    not to be absent. KEPT: one process for each (commit, rel) however many run_starts name the commit, for the life of the object."""

    def __init__(self, root: str, timeout: float = GIT_TIMEOUT_S, budget: float = GIT_BUDGET_S) -> None:
        self.root, self.timeout, self.budget = root, timeout, budget
        self.spent = 0.0
        self.problem: Optional[str] = None
        self.seen: Dict[Tuple[str, str], Optional[str]] = {}
        self.probed = False

    def _git(self, *args: str) -> Optional[Tuple[int, str]]:
        """(return code, stdout) of `git -C root ARGS`, or None when git was not run or did not answer in its time (`problem` says why)."""
        limit = min(self.timeout, self.budget - self.spent)
        if self.problem is None and limit <= 0:
            self.problem = f"git has been asked for {self.budget:g} s in all"
        if self.problem is not None:
            return None
        t0, got = time.monotonic(), None
        try:
            p = subprocess.run(["git", "-C", self.root] + list(args), capture_output=True, text=True, errors="replace", timeout=limit)
            got = (p.returncode, p.stdout.strip())
        except subprocess.TimeoutExpired:
            self.problem = f"git did not answer within {limit:g} s"
        except OSError as e:
            self.problem = f"git could not be run ({type(e).__name__})"
        self.spent += time.monotonic() - t0
        return got

    def __call__(self, commit: str, rel: str) -> Optional[str]:
        k = (commit, rel)
        if k not in self.seen:
            h = None
            if GIT_HASH.fullmatch(commit or ""):
                got = self._git("rev-parse", f"{commit}:{rel}")
                if got is not None and got[0] == 0 and GIT_HASH.fullmatch(got[1]):
                    h = got[1]
                elif got is not None and not self.probed:       # git answered no: to a commit it lacks, or to a place that is no repository?
                    self.probed = True
                    top = self._git("rev-parse", "--git-dir")
                    if top is not None and top[0] != 0:
                        self.problem = "the checkout this report is in is not a git repository (or git refused to read it)"
            self.seen[k] = h
        return self.seen[k]


def checkout_git() -> GitTrees:
    """The GitTrees on the repository that holds this file's hw/, made on first use and shared by every summarize() of the process: a reducer
    that calls it many times asks git once for each commit and directory."""
    global _checkout_git
    if _checkout_git is None:
        _checkout_git = GitTrees(_CHECKOUT)
    return _checkout_git


def _run_trees(rs: Optional[Dict[str, Any]], rev: Optional[Callable[[str, str], Optional[str]]]) -> Dict[str, Any]:
    """What a run_start's `tree` comes to by the driver's own rule, card_stress_lib's resolve_tree and run_classes (the ones its --resume counts
    by; no second rule here): `use`, the tree with what the run did not record taken from its commit through `rev` where git can say; `classes`,
    {TILE: (key, reason), HOST: (key, reason)}, the reason None when every part of the key is known; `derived`, {'rtl'|'host': tree} for each
    directory whose tree the run did not record and git gave. `rs` None: a slice before any run_start, which recorded nothing."""
    tr = rs.get("tree") if isinstance(rs, dict) and isinstance(rs.get("tree"), dict) else {}
    use, _why = resolve_tree(tr, rev)
    derived = {rel: use[k] for k, rel in (("rtl", "rtl"), ("host_src", "host"))
               if isinstance(use.get(k), str) and use[k] and not (isinstance(tr.get(k), str) and tr[k])}
    return {"tr": tr, "use": use, "classes": run_classes(tr, rev), "derived": derived, "cl": {}}


def _tree_class(kind: str, info: Dict[str, Any], git_read: bool = True) -> Dict[str, Any]:
    """The class a slice of this reach falls in, under the run_start whose _run_trees is `info`: its `key`, the `head` and `tail` of its label
    (_tree_label puts them round what the class gathers), `why` (the reason this run's tree is not known, resolve_tree's own, or None) and
    `derived` (the {commit, dir, tree} that rev gave this run, or None). A TILE item is keyed by the RTL tree; a HOST item by the library's
    source (host/'s tree hash) and the compiler's version line; a tree with uncommitted changes is its own key ('+modified'); a tree that
    is not known is kept apart by its commit, and its head is not made here: the entry has `said` ('unknown': the run recorded one, which
    git contradicts; 'not recorded'), the `prefix` and the commit, and _tree_label chooses the word from every run the class gathers, so
    that no run's order decides it. Two runs share a class only when every part of the key is equal. The KEY is card_stress_lib.
    tree_key's, through run_classes, the one the driver's --resume counts by (parcel DR4); the label is this report's."""
    tr, use = info["tr"], info["use"]
    if kind not in (TILE, HOST):
        return {"key": tree_key(kind, tr)[0], "tail": "", "why": None, "derived": None, "said": None,
                "head": "reach unknown (no key: neither the records nor the catalog's table say whether the tile is involved)"}
    key, why = info["classes"][kind]
    k, dk, rel, name = ("rtl", "rtl_dirty", "rtl", "RTL tree") if kind == TILE else ("host_src", "host_src_dirty", "host", "host/ tree")
    h, mod, cc = _str(use.get(k)), _bool(use.get(dk)), _str(use.get("cc"))
    commit = _str(tr.get("commit"))
    if not h:
        said = "unknown" if _str(tr.get(k)) else "not recorded"          # unknown: it recorded one, which git contradicts
        return {"key": key, "tail": "", "derived": None, "head": None, "said": said,
                "prefix": "RTL tree " if kind == TILE else "library source and compiler ", "commit12": commit[:12] if commit else "unknown",
                "why": (why or "") + ("" if git_read else "; git was not read (--no-git)")}
    return {"key": key, "why": None, "said": None,
            "head": f"{name} {h[:12]}" + (f" MODIFIED (uncommitted changes under {rel}/)" if mod else ""),
            "tail": (f", compiler {_line(cc, 80) if cc else 'not recorded'}" if kind == HOST
                     else "" if mod is not None else " (whether it was modified is not recorded)"),
            "derived": {"commit": commit, "dir": rel, "tree": h} if rel in info["derived"] else None}


def _tree_label(c: Dict[str, Any], problem: Optional[str], via: str = "git") -> str:
    """A class's label, the same whatever the order of the runs it gathers: its head - for a class whose tree is not known the word is the
    runs' common one ('unknown', 'not recorded'), and 'not recorded or unknown' where they differ -, '(read from git at commit ...)' where a
    run's tree in it was read from git, the commits sorted ('(taken from the given rev, not git, at commit ...)' where `via` says a
    function the caller gave answered), its tail, and, for a class kept apart, why (the reasons sorted) - with what stopped git where
    something did, since a commit git was not asked about is "not in this checkout" to resolve_tree and the reader must be able to tell
    that from an absent one."""
    cms = sorted({d["commit"][:12] for d in c["derived"]})
    how = "read from git" if via == "git" else "taken from the given rev, not git,"
    read = (f" ({how} at commit{'s' if len(cms) > 1 else ''} {', '.join(cms[:LABEL_COMMITS])}"
            + (f" and {len(cms) - LABEL_COMMITS} more" if len(cms) > LABEL_COMMITS else "") + ")") if cms else ""
    why = "; ".join(sorted(c["why"])) + (f" [git: {problem}]" if problem else "") if c["why"] else ""
    word = c["said"][0] if len(c["said"]) == 1 else "not recorded or unknown"
    head = f"{c['prefix']}{word} (commit {c['commit12']})" if c["said"] else c["head"]
    return head + read + c["tail"] + (f": {why}" if why else "")


def _via(rev: Any) -> str:
    """Where a rev's trees come from, for the label and for sweep.trees.git: 'git' only for a GitTrees, 'given rev' for any other function, 'records'."""
    return "git" if isinstance(rev, GitTrees) else "given rev" if rev is not None else "records"


def _gather(classes: Dict[Tuple[str, str], Dict[str, Any]], kind: str, cl: Dict[str, Any]) -> Dict[str, Any]:
    """The entry for the class (kind, cl['key']) in `classes`, opened if need be and with what the slice's _tree_class `cl` says added to it. _trees
    gathers every slice of a run through this, and tree_class gathers one: the label of a class a run fills alone is the same by construction."""
    c = classes.setdefault((kind, cl["key"]), {"kind": kind, "key": cl["key"], "head": cl["head"], "tail": cl["tail"], "why": [], "said": [],
                                               "prefix": cl.get("prefix"), "commit12": cl.get("commit12"),
                                               "derived": [], "runs": [], "commits": [], "iv": {}, "rnd": {}})
    if cl["tail"] and not c["tail"]:
        c["tail"] = cl["tail"]                  # a note (a tile tree's 'whether it was modified is not recorded') is the class's if any run's is
    if cl["said"] and cl["said"] not in c["said"]:
        c["said"].append(cl["said"])
    if cl["why"] and cl["why"] not in c["why"]:
        c["why"].append(cl["why"])
    if cl["derived"] and cl["derived"] not in c["derived"]:
        c["derived"].append(cl["derived"])
    return c


def tree_class(kind: str, run_start: Optional[Dict[str, Any]], rev: Any = _REPO_GIT) -> Tuple[str, str]:
    """(key, label) of the class a slice of reach `kind` ('tile', 'host', else 'unknown') falls in under `run_start` (None: a slice before any run_start), by
    this report's own rule and with the label --json gives a class that this run alone fills - the same pieces _trees uses: _run_trees, _tree_class,
    _gather and _tree_label, with the problem and `via` read as _trees reads them. `rev` is summarize()'s: the default reads git through checkout_git(),
    None reads the records alone, a callable is used as given. Public because a reducer needs the class of a run nothing was swept under: the nightly
    page's (hw/card_stress_progress.py, _empty_class) is its caller."""
    if rev is _REPO_GIT:
        rev = checkout_git()
    cl = _tree_class(kind, _run_trees(run_start, rev), rev is not None)
    return cl["key"], _tree_label(_gather({}, kind, cl), _str(getattr(rev, "problem", None)), _via(rev))


def _trees(sources: List[Dict[str, Any]], rev: Optional[Callable[[str, str], Optional[str]]] = None) -> Dict[str, Any]:
    """Coverage by tree: every completed sweep slice of every source (a run's records, in file order), attributed to the
    last run_start before it, and counted in the class its reach and that run's tree give (_tree_class). The coverage
    of an exhaustive item in a class is the union of its slices' intervals over every image; each image's own is
    beside it. Nothing here is summed across classes. A run_start's tree is what it recorded with what it did not taken from its commit
    through `rev` (resolve_tree: git of the checkout; None reads the records alone; a function the caller gave is used as given). A class
    entry has `label` (which says "read from git" where a run's tree in it was, and "taken from the given rev, not git" where a function the
    caller gave supplied it) and `derived_from_git`: [{commit, dir ('rtl'|'host'), tree}], sorted by those three, for each run whose tree in
    the class `rev` supplied - what git gave when rev is a GitTrees, what the function answered when it is not -, [] when none was; the
    label names the commits sorted too, so that nothing a class says depends on the order of its runs; the result has `git`: {read,
    source, problem}: whether git was read (only a GitTrees reads it), where the trees came from ('git', 'given rev', 'records') and what,
    if anything, stopped git."""
    classes: Dict[Tuple[str, str], Dict[str, Any]] = {}
    via = _via(rev)
    for src in sources:
        rs: Optional[Dict[str, Any]] = None
        info = _run_trees(None, rev)
        for r in src["objs"]:
            typ = r.get("type")
            if typ == "run_start":
                rs = r
                info = _run_trees(r, rev)
                continue
            if typ != "leg" or r.get("kind") != "sweep" or r.get("status") not in ("pass", "fail") or _sweep_defect(r):
                continue
            sw = r.get("sweep")
            item = sw.get("item") if isinstance(sw, dict) else None
            if not isinstance(item, str) or not item:
                continue
            kind = slice_reach(sw) or "unknown"
            if kind not in info["cl"]:
                info["cl"][kind] = _tree_class(kind, info, rev is not None)
            c = _gather(classes, kind, info["cl"][kind])
            rid = _str(rs.get("run_id")) if isinstance(rs, dict) else None
            cm = _str((rs.get("tree") or {}).get("commit")) if isinstance(rs, dict) and isinstance(rs.get("tree"), dict) else None
            if rid and rid not in c["runs"]:
                c["runs"].append(rid)
            if cm and cm not in c["commits"]:
                c["commits"].append(cm)
            image = _str(r.get("image")) or "-"
            cases = _int((r.get("counts") or {}).get("cases")) if isinstance(r.get("counts"), dict) else None
            if "lo" in sw or "hi" in sw:
                d = c["iv"].setdefault(item, {})
                d.setdefault(image, {"iv": [], "slices": 0, "cases": 0})
                d[image]["iv"].append((int(sw["lo"]), int(sw["hi"])))
                d[image]["slices"] += 1
                d[image]["cases"] += cases or 0
            else:
                # a random item's coverage is keyed by the BATCH its slices ran at (the chunked tools: --sweep-chunk): the flags
                # of a slice were compared over that many operands, a scaleB slice's cases follow it, and a cvtfrom slice's operand
                # stream does too, so a chunked item's slices are a row of their own and never summed with the default tools'
                bt = record_batch(sw)
                rk = item if bt == DEFAULT_BATCH else f"{item} @batch {bt}"
                d = c["rnd"].setdefault(rk, {})
                d.setdefault(image, {"slices": 0, "cases": 0, "max_seed_n": None})
                d[image]["slices"] += 1
                d[image]["cases"] += cases or 0
                sn = _int(sw.get("seed_n"))
                if sn is not None:
                    d[image]["max_seed_n"] = sn if d[image]["max_seed_n"] is None else max(d[image]["max_seed_n"], sn)

    def img_key(i: str) -> Tuple[int, str]:
        return (IMAGE_ORDER.index(i), i) if i in IMAGE_ORDER else (len(IMAGE_ORDER), i)

    problem = _str(getattr(rev, "problem", None))          # what stopped git, read after the last lookup
    out = []
    for kind in TREE_KINDS:
        for (k2, key), c in classes.items():
            if k2 != kind:
                continue
            imgs = sorted({i for d in list(c["iv"].values()) + list(c["rnd"].values()) for i in d}, key=img_key)
            exh = []
            for item in sorted(c["iv"]):
                per = c["iv"][item]
                cov = covered([iv for v in per.values() for iv in v["iv"]])
                sp = ITEM_SPACE.get(item, EXH)
                exh.append({"item": item, "slices": sum(v["slices"] for v in per.values()),
                            "cases": sum(v["cases"] for v in per.values()), "covered": cov, "total": sp,
                            "pct": 100.0 * cov / sp, "complete": cov == sp,
                            "by_image": {i: covered(per[i]["iv"]) for i in sorted(per, key=img_key)}})
            rnd = []
            for item in sorted(c["rnd"]):
                per = c["rnd"][item]
                seeds = [v["max_seed_n"] for v in per.values() if v["max_seed_n"] is not None]
                rnd.append({"item": item, "slices": sum(v["slices"] for v in per.values()),
                            "cases": sum(v["cases"] for v in per.values()), "max_seed_n": max(seeds) if seeds else None,
                            "by_image": {i: per[i]["cases"] for i in sorted(per, key=img_key)}})
            tot_cov = sum(e["covered"] for e in exh)
            tot_sp = sum(e["total"] for e in exh)
            out.append({
                "kind": kind, "key": key, "label": _tree_label(c, problem, via),
                "derived_from_git": sorted(c["derived"], key=lambda d: (d["commit"], d["dir"], d["tree"])), "runs": c["runs"],
                "commits": c["commits"], "images": imgs, "exhaustive": exh, "random": rnd,
                "total": {"items": len(exh), "covered": tot_cov, "total": tot_sp,
                          "pct": (100.0 * tot_cov / tot_sp) if exh else None,
                          "complete_items": sum(1 for e in exh if e["complete"]),
                          "by_image": {i: sum(e["by_image"].get(i, 0) for e in exh) for i in imgs if any(i in e["by_image"] for e in exh)}},
            })
    return {"classes": out, "git": {"read": via == "git", "source": via, "problem": problem},
            "sources": [{"source": s["source"], "records": len(s["objs"]), "bad_lines": sorted(s.get("bad_lines") or []),
                         "partial_tail": bool(s.get("partial_tail"))} for s in sources]}


def _uptime(objs: List[Dict[str, Any]], by_type: Dict[str, List[Tuple[int, Dict[str, Any]]]],
            views: List[Dict[str, Any]], now: float, ended: bool, gap_seconds: float) -> Dict[str, Any]:
    stamped = [(e, i) for i, r in enumerate(objs) if (e := _num(r.get("epoch"))) is not None]
    events = Counter(_str(r.get("event")) or "(unnamed)" for _, r in by_type.get("event", []))
    out: Dict[str, Any] = {
        "gap_seconds": gap_seconds, "events_by_name": dict(sorted(events.items(), key=lambda kv: (-kv[1], kv[0]))),
        "wall_s": None, "first_epoch": None, "end_epoch": None, "legs_union_s": None, "legs_fraction": None,
        "card_union_s": None, "card_fraction": None, "legs_used": 0, "legs_unusable": 0,
        "before_first_leg_s": None, "after_last_leg_s": None, "pieces": 0,
        "gaps": [], "gaps_over": 0, "longest_gap": None,
    }
    if not stamped:
        return out
    first_e, last_e = min(stamped)[0], max(stamped)[0]
    end_e = last_e if ended else max(now, last_e)
    wall = end_e - first_e
    out.update(wall_s=wall, first_epoch=first_e, end_epoch=end_e)

    used, card, unusable = [], [], 0
    for v in views:
        se, ee = v["se"], v["ee"]
        if se is None or ee is None or ee < se:
            unusable += 1
            continue
        it = (se, ee, _when(v["r"].get("start"), se), _when(v["r"].get("end"), ee))
        used.append(it)
        if v["kind"] in ("battery", "sweep") and v["status"] != "skipped" and v["image"] != CPU:
            card.append(it)                  # a host pool slice (image cpu) runs beside the card, and is not time on it
    pieces = _time_union(used)
    union = math.fsum(p[1] - p[0] for p in pieces)
    cunion = math.fsum(p[1] - p[0] for p in _time_union(card))
    out.update(legs_union_s=union, card_union_s=cunion, legs_used=len(used), legs_unusable=unusable,
               pieces=len(pieces), legs_fraction=(union / wall) if wall > 0 else None,
               card_fraction=(cunion / wall) if wall > 0 else None)
    if pieces:
        out["before_first_leg_s"] = pieces[0][0] - first_e
        out["after_last_leg_s"] = end_e - pieces[-1][1]

    evs = sorted(((e, i, r) for i, r in by_type.get("event", []) if (e := _num(r.get("epoch"))) is not None),
                 key=lambda x: (x[0], x[1]))
    ev_keys = [x[0] for x in evs]
    marks = []
    for typ in ("run_start", "run_end", "build"):
        for i, r in by_type.get(typ, []):
            e = _num(r.get("epoch"))
            if e is not None:
                if typ == "run_start":
                    text = f"run_start, run_id {_str(r.get('run_id')) or '-'}, resumed {r.get('resumed')}"
                elif typ == "run_end":
                    text = f"run_end, reason {_str(r.get('reason')) or '-'}, exit {_int(r.get('exit'))}"
                else:
                    text = f"build, ok {_bool(r.get('ok'))}"
                marks.append((e, i, {"ts": _when(r.get("ts"), e), "type": typ, "text": text}))
    marks.sort(key=lambda x: (x[0], x[1]))
    mk_keys = [x[0] for x in marks]

    gaps_all = []
    for p, q in zip(pieces, pieces[1:]):
        g0, g1 = p[1], q[0]
        lo, hi = bisect.bisect_left(ev_keys, g0), bisect.bisect_right(ev_keys, g1)
        mlo, mhi = bisect.bisect_left(mk_keys, g0), bisect.bisect_right(mk_keys, g1)
        gaps_all.append({
            "start": p[3], "end": q[2], "start_epoch": g0, "end_epoch": g1, "seconds": g1 - g0,
            "events": [{"ts": _when(r.get("ts"), e), "event": _str(r.get("event")) or "(unnamed)",
                        "detail": _str(r.get("detail")) or ""} for e, _, r in evs[lo:hi]],
            "records": [m[2] for m in marks[mlo:mhi]],
        })
    over = [g for g in gaps_all if g["seconds"] > gap_seconds]
    out["gaps"], out["gaps_over"] = over, len(over)
    if gaps_all:
        g = max(gaps_all, key=lambda x: x["seconds"])
        out["longest_gap"] = {"seconds": g["seconds"], "start": g["start"], "end": g["end"],
                              "over_threshold": g["seconds"] > gap_seconds}
    return out


def summarize(records: List[Any], now: Optional[float] = None, gap_seconds: float = 300, *,
              partial_tail: bool = False, bad_lines: Optional[List[int]] = None,
              also: Optional[List[Dict[str, Any]]] = None, run_label: str = "this run", rev: Any = _REPO_GIT) -> Dict[str, Any]:
    """The run's figures as plain, JSON-safe data. `records` is read_records()'s list;
    `now` (epoch seconds, default time.time()) is used only while the run has no run_end;
    partial_tail and bad_lines carry what read_records() reported, for the text to say first.
    `also`: other runs' records for the coverage-by-tree section alone, each {"source": name, "objs": the
    records that are objects, "bad_lines": [...], "partial_tail": bool} (main() reads them from --also).
    `rev` (parcel RG): how a run_start's tree that the run did not record is read from its commit, for that section alone - the `rev`
    of card_stress_lib.resolve_tree, `rev(commit, rel) -> tree hash or None`. The default is git of the repository that holds this
    file's hw/ (checkout_git(): bounded, and shared by every call in the process), so every caller that passes nothing gets what the
    command line shows; None reads the records alone (`--no-git`); a callable is used as given, and then only a GitTrees is called git:
    for any other the labels say "taken from the given rev, not git", `sweep.trees.git` is {read: false, source: "given rev"}, and
    each `derived_from_git` entry is what the callable answered."""
    if rev is _REPO_GIT:
        rev = checkout_git()
    records = list(records)
    now = time.time() if now is None else float(now)
    gap_seconds = float(gap_seconds)
    objs = [r for r in records if isinstance(r, dict)]
    non_obj = [r for r in records if not isinstance(r, dict)]
    by_type: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    for i, r in enumerate(objs):
        t = r.get("type")
        by_type.setdefault(t if isinstance(t, str) else "(none)", []).append((i, r))
    views = _leg_views(by_type)
    offset = _box_offset(objs)
    header = _header(objs, by_type, now, offset)
    versions = Counter(str(r.get("v")) if "v" in r else "(absent)" for r in objs if _int(r.get("v")) != 1)
    sweep = _sweep(objs, views)
    sweep["trees"] = _trees([{"source": run_label, "objs": objs, "bad_lines": bad_lines, "partial_tail": partial_tail}]
                            + list(also or []), rev)
    summary = {
        "report_version": 1,
        "input": {
            "records": len(objs), "bad_lines": sorted(bad_lines or []), "partial_tail": bool(partial_tail),
            "non_object": len(non_obj), "non_object_examples": [_line(repr(x), 60) for x in non_obj[:3]],
            "no_epoch": sum(1 for r in objs if _num(r.get("epoch")) is None),
            "unknown_versions": dict(versions),
        },
        "header": header,
        "totals": _totals(by_type, views),
        "rows": _rows(views),
        "telemetry": _telemetry(by_type),
        "failures": _failures(views),
        "sweep": sweep,
        "uptime": _uptime(objs, by_type, views, now, not header["running"], gap_seconds),
    }
    return _clean(summary)


# ---------------------------------------------------------------------------
# render: the text, from the summary alone
# ---------------------------------------------------------------------------

def _g(x: Any) -> str:
    """A number to four significant digits, never in exponent form; '-' for None; anything
    that is not a number is shown as the one line of text it is."""
    if x is None:
        return "-"
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return _line(x, 40)
    if isinstance(x, int):
        return str(x)
    if x == 0:
        return "0"
    a = abs(x)
    if a >= 1000:
        nd = 0
    elif a >= 100:
        nd = 1
    elif a >= 10:
        nd = 2
    elif a >= 1:
        nd = 3
    else:
        nd = min(12, 3 + int(-math.floor(math.log10(a))))
    return "%.*f" % (nd, x)


def _gs(x: Optional[float]) -> str:
    """_g with an explicit sign, for slopes."""
    if x is None:
        return "-"
    return ("+" if x > 0 else "-" if x < 0 else "") + _g(abs(x))


def _dur(s: Optional[float]) -> str:
    if s is None:
        return "-"
    neg, t = s < 0, abs(int(round(s)))
    d, r = divmod(t, 86400)
    h, r = divmod(r, 3600)
    m, sec = divmod(r, 60)
    if d:
        txt = f"{d} d {h:02d} h {m:02d} m {sec:02d} s"
    elif h:
        txt = f"{h} h {m:02d} m {sec:02d} s"
    elif m:
        txt = f"{m} m {sec:02d} s"
    else:
        txt = f"{sec} s"
    return ("-" if neg else "") + txt


def _pct3(part: int, whole: int) -> str:
    """A percentage to three decimals that never rounds an incomplete figure up to 100."""
    if not whole:
        return "-"
    s = "%.3f" % (100.0 * part / whole)
    if part < whole and s == "100.000":
        s = "99.999"
    return s + "%"


def _hex_range(lo: int, hi: int) -> str:
    return f"[0x{lo:08x}, 0x{hi:08x})"


KV_WIDTH = 15


def _kv(key: str, val: Any) -> str:
    return f"{key:<{KV_WIDTH}}: {val}"


def _table(headers: List[str], rows: List[List[str]]) -> List[str]:
    widths = [len(h) for h in headers]
    for r in rows:
        for j, c in enumerate(r):
            widths[j] = max(widths[j], len(c))

    def fmt(cells: List[str]) -> str:
        return ("  " + "  ".join(c.ljust(w) for c, w in zip(cells, widths))).rstrip()

    return [fmt(headers)] + [fmt(r) for r in rows]


def _yn(x: Optional[bool]) -> str:
    return "-" if x is None else ("yes" if x else "no")


def _counts_text(c: Optional[Dict[str, Any]]) -> str:
    return ", ".join(f"{k}={_line(v, 60)}" for k, v in c.items()) if c else "none"


def _r_top(S: Dict[str, Any]) -> List[str]:
    inp, out = S["input"], []
    bad = inp["bad_lines"]
    if bad:
        more = f", ... and {len(bad) - BAD_LINES_SHOWN} more" if len(bad) > BAD_LINES_SHOWN else ""
        out.append(f"!!! {len(bad)} UNPARSABLE LINE(S) in metrics.jsonl, line number(s): "
                   f"{', '.join(str(n) for n in bad[:BAD_LINES_SHOWN])}{more}")
        out.append("!!! those records are NOT in this report: the file is damaged or was edited, "
                   "and every figure below is of the lines that do parse")
    if inp["partial_tail"]:
        out.append("note: the last line of metrics.jsonl is a partial record (the driver was caught "
                   "mid-append, or died mid-write); it is left out, which is not an error")
    if inp["non_object"]:
        out.append(f"note: {inp['non_object']} line(s) parse as JSON but are not records (objects), "
                   f"left out; first: {'; '.join(inp['non_object_examples'])}")
    if inp["unknown_versions"]:
        seen = ", ".join(f"v={k} x{n}" for k, n in inp["unknown_versions"].items())
        out.append(f"note: records of a version other than 1 ({seen}); this report reads version 1")
    if inp["no_epoch"]:
        out.append(f"note: {inp['no_epoch']} record(s) carry no numeric epoch and are left out of "
                   f"every time-based figure")
    return out


def _r_header(S: Dict[str, Any]) -> List[str]:
    h = S["header"]
    L = ["== HEADER =="]
    L.append(_kv("run id", ", ".join(h["run_ids"]) or "-"))
    L.append(_kv("host", ", ".join(h["hosts"]) or "-"))
    L.append(_kv("out", ", ".join(h["outs"]) or "-"))
    trees = [f"commit {t['commit'] or '-'} ({'DIRTY' if t['dirty'] else 'clean' if t['dirty'] is False else 'dirty unknown'})"
             + (f", rtl {t['rtl'][:12]}{' MODIFIED' if t.get('rtl_dirty') else ''}" if t.get("rtl") else ", rtl not recorded")
             + (f", host/ {t['host_src'][:12]}{' MODIFIED' if t.get('host_src_dirty') else ''}" if t.get("host_src") else "")
             + (f", cc {_line(t['cc'], 60)}" if t.get("cc") else "")
             for t in h["trees"]]
    L.append(_kv("tree", "; ".join(trees) or "-"))
    L.append(_kv("started", h["started"]["ts"] if h["started"] else "-"))
    L.append(_kv("run_start", f"{h['run_starts']} record(s), {h['resumed_marked']} marked resumed"))
    ends = h["run_ends"]
    if h["running"]:
        lr = h["last_record"]
        if lr is None:
            txt = "RUNNING: no record carries a time"
        else:
            age = h["age_s"]
            txt = f"RUNNING: last record {lr['ts']}, {max(0, int(round(age)))} s ago"
            if age < -5:
                txt += f" (this machine's clock is {int(round(-age))} s behind the record's)"
        L.append(_kv("ended", txt))
    else:
        e = ends[-1]
        L.append(_kv("ended", f"{e['ts']} (reason {e['reason'] or '-'}, exit {_g(e['exit'])}, "
                              f"cycles {_g(e['cycles'])})"))
    for e in (ends[:-1] if not h["running"] else ends):
        L.append(_kv("earlier end", f"{e['ts']} (reason {e['reason'] or '-'}, exit {_g(e['exit'])}, "
                                    f"cycles {_g(e['cycles'])})"))
    d = h["deadline"]
    if d is None:
        L.append(_kv("deadline", "none set"))
    else:
        rem = d["remaining_s"]
        if rem is None:
            phrase = "remaining time n/a" + (" (deadline not understood)" if d["epoch"] is None else "")
        else:
            n, hum = int(round(abs(rem))), _dur(abs(rem))
            if d["measured_at"] == "run_end":
                phrase = (f"ended {n} s ({hum}) before the deadline" if rem >= 0
                          else f"OVERSHOOT: ended {n} s ({hum}) after the deadline")
            else:
                phrase = (f"{n} s ({hum}) remaining" if rem >= 0
                          else f"OVERSHOOT: {n} s ({hum}) past the deadline and still running")
        src = "" if d["source"] == "deadline" else " (from settings.until)"
        L.append(_kv("deadline", f"{d['text']}{src}; {phrase}"))
    f = h["flags"]
    if f is None:
        L.append(_kv("flags", "-"))
    else:
        L.append(_kv("flags", f"quick {_yn(f['quick'])}, dry_run {_yn(f['dry_run'])}"
                              + (" (differs between run_start records)" if f["differs"] else "")))
    if h["images"]:
        L.append(_kv("images", "; ".join(
            f"{n} {_g(i['tiles'])} tiles sha256 {(i['sha256'] or '-')[:12]}"
            + (f", {manifest_brief(i['manifest'])}" if i.get("manifest") else "") for n, i in h["images"].items())))
    return L


def _r_totals(S: Dict[str, Any]) -> List[str]:
    t = S["totals"]
    L = ["== TOTALS =="]
    by = t["legs"]["by_status"]
    known = ", ".join(f"{k} {by[k]}" for k in KNOWN)
    extra = "".join(f", {k} {n}" for k, n in by.items() if k not in KNOWN)
    L.append(_kv("legs", f"{t['legs']['total']} recorded; {known}{extra}"))
    c = t["cycles"]
    unf = ", ".join(str(x) for x in c["unfinished"]) or "none"
    L.append(_kv("cycles", f"{c['started']} started, {c['ended']} ended; started and not ended: {unf}"))
    L.append(_kv("by image", ", ".join(f"{k} {n}" for k, n in c["by_image"].items()) or "-"))
    L.append(_kv("cycle_end", f"{c['ended_with_failed']} of {c['ended_reporting_failed']} records "
                              f"that report it show failed legs"))
    if not t["builds"]:
        L.append(_kv("build", "no build record"))
    for b in t["builds"]:
        if b["ok"] is True:
            L.append(_kv("build", f"ok ({b['steps']} steps)"))
        else:
            what = ("FAILED" if b["ok"] is False else "ok not recorded")
            L.append(_kv("build", f"{what} ({b['steps']} steps; {len(b['failed_steps'])} failed)"))
            for s in b["failed_steps"]:
                L.append(" " * (KV_WIDTH + 2) + f"{_line(s['name'], 60)}: {_line(s['detail'] or '-', 200)}")
    L.append(_kv("records", ", ".join(f"{k} {n}" for k, n in t["records"].items()) or "none"))
    return L


def _r_rows(S: Dict[str, Any]) -> List[str]:
    rows = S["rows"]
    L = ["== PER IMAGE AND LEG =="]
    if not rows:
        L.append("no leg records")
        return L
    other = any(r["other"] for r in rows)
    L += _table(["image", "leg", "runs"] + list(KNOWN) + (["other"] if other else []) + ["checks", "cases"],
                [[r["image"] or "-", r["leg"], str(r["runs"])] + [str(r["statuses"][k]) for k in KNOWN]
                 + ([str(r["other"])] if other else [])
                 + ["" if r["checks"] is None else str(r["checks"]), "" if r["cases"] is None else str(r["cases"])]
                 for r in rows])
    L.append("")
    body = []
    for r in rows:
        d, ra = r["duration"], r["rate"]
        if ra is None:
            rate = ["-", "0", "-", "-", "-", "-"]
        else:
            trend = ("%+.1f%%" % ra["trend_pct"]) if ra["trend_pct"] is not None else ra["trend_note"]
            rate = [ra["unit"], str(ra["n"]), _g(ra["median"]), _g(ra["min"]), _g(ra["max"]), trend]
        body.append([r["image"] or "-", r["leg"], _g(d["median"]), _g(d["min"]), _g(d["max"])] + rate)
    L += _table(["image", "leg", "dur_med_s", "dur_min_s", "dur_max_s", "rate_unit", "n_rates", "rate_med",
                 "rate_min", "rate_max", "trend"], body)
    series = [r for r in rows if r["rate"] is not None]
    if series:
        L.append("")
        L.append("  rates over time (evenly picked, at most 12 a row), oldest first:")
        for r in series:
            ra = r["rate"]
            picked = f", {len(ra['series'])} picked" if len(ra["series"]) < ra["n"] else ""
            L.append(f"  {r['image'] or '-'} / {r['leg']} [{ra['unit']}, {ra['n']} rate"
                     f"{'' if ra['n'] == 1 else 's'}{picked}]: {' '.join(_g(v) for v in ra['series'])}")
            if ra["other_units"]:
                L.append("      also in other units, not in the figures above: "
                         + ", ".join(f"{u} x{n}" for u, n in ra["other_units"].items()))
    mixed = [r for r in rows if r["kind"] == "sweep" and (r["items"] or 0) > 1 and r["rate"] is not None]
    if mixed:
        L.append("")
        L.append("  note: a sweep row mixes items whose rates differ, so its trend reflects the mix of "
                 "items as well as the card")
    return L


def _stats_table(stats: List[Dict[str, Any]]) -> List[str]:
    return _table(["label", "samples", "min", "max", "mean", "first", "last", "slope_per_h"],
                  [[_line(s["label"], 70), str(s["n"]), _g(s["min"]), _g(s["max"]), _g(s["mean"]),
                    _g(s["first"]), _g(s["last"]),
                    _gs(s["slope_per_hour"])] for s in stats])


def _r_telemetry(S: Dict[str, Any]) -> List[str]:
    T = S["telemetry"]
    L = ["== TELEMETRY =="]
    n = T["samples"]
    if n == 0:
        L.append("telemetry: no samples recorded")
        return L
    if T["with_values"] == 0:
        L.append(f"telemetry: {n} samples, none parsed")
    else:
        L.append(f"telemetry: {n} samples, {T['with_values']} with values, {T['without_values']} without, "
                 f"{T['failed']} marked ok=false")
    L.append("  by when: " + ", ".join(f"{k} {c}" for k, c in T["by_when"].items()))
    for nr in T.get("no_reading", []):
        L.append(f"  NO READING: {nr['label']} read 0 in {nr['zero']} of {nr['of']} samples. A 0 from this sensor is taken as no "
                 f"reading, not 0 degrees (BELIEVED: a powered card's HBM is not at 0, and the zeros come in runs between runs of "
                 f"readings), so the zeros are left out of its range below, "
                 + (f"which is of the other {nr['kept']} sample(s)" if nr["kept"] else "and it has no range: every sample read 0"))
    if T["failed"]:
        L.append(f"  samples with ok=false: {T['failed']}; errors:")
        for e in T["errors"]:
            L.append(f"    {e['count']} x {_line(e['message'], 300)}")
    if T["with_values"] == 0:
        if T["first_raw"] is not None:
            L.append(f"  first raw text ({len(T['first_raw'])} of {T['first_raw_chars']} chars):")
            for ln in T["first_raw"].split("\n"):
                L.append("    " + ln.rstrip())
        else:
            L.append("  no sample carries raw text either")
    else:
        shown = T["labels"][:LABELS_SHOWN]
        left = T["labels_total"] - len(shown)
        L.append("")
        L.append(f"  device labels: {T['labels_total']}"
                 + (f"; the {len(shown)} with the widest range (max - min) are shown, {left} left out" if left else ""))
        L += _stats_table(shown)
    if T["host"]:
        L.append("")
        L.append("  host fields:")
        L += _stats_table(T["host"])
    return L


def _r_failures(S: Dict[str, Any]) -> List[str]:
    F = S["failures"]
    L = ["== FAILURES =="]
    if F["count"] == 0:
        L.append("no leg has a status other than pass or skipped")
    else:
        L.append(f"legs not passed (status other than pass or skipped): {F['count']}; "
                 + ", ".join(f"{k} {n}" for k, n in F["by_status"].items()))
        for b in F["legs"]:
            to = _yn(b["timed_out"])
            L.append(f"  {b['start'] or '-'}  {b['image'] or '-'}  {b['leg'] or '(unnamed)'}  "
                     f"attempt {_g(b['attempt'])}  status {b['status']}  rc {_g(b['rc'])}  "
                     f"timed_out {to}  killed {b['killed'] or '-'}")
            L.append(f"      reason: {_line(b['reason'], 400) if b['reason'] else 'none'}")
            L.append(f"      counts: {_counts_text(b['counts'])}")
            if b["notes"]:
                L.append(f"      notes: {_line('; '.join(b['notes']), 400)}")
            if b["disagreements"]:
                d = b["disagreements"]
                L.append(f"      disagreements (first {min(len(d), DISAGREE_SHOWN)} of {len(d)}):")
                for x in d[:DISAGREE_SHOWN]:
                    L.append(f"        {_line(x)}")
            L.append(f"      log: {b['log'] or 'none'}")
    sk = F["skipped"]
    L.append("")
    if sk["count"] == 0:
        L.append("skipped legs: none")
    else:
        L.append(f"skipped legs: {sk['count']} in {len(sk['groups'])} group(s), by (leg, reason):")
        for g in sk["groups"]:
            L.append(f"  {g['leg'] or '(unnamed)'}: {g['count']} x "
                     f"\"{_line(g['reason'], 200) if g['reason'] else '(no reason recorded)'}\" "
                     f"(images: {', '.join(sorted(g['images']))})")
    return L


def _reach_text(r: Optional[str]) -> str:
    """'tile', 'host', or 'unknown' for an item whose records and the catalog's table both say nothing."""
    return r if r in (TILE, HOST) else "unknown"


def _reach_note(rows: List[Dict[str, Any]]) -> List[str]:
    """One sentence, when any item is a host item, on what that means (hw/card_stress_lib.py, OP_REACH)."""
    L: List[str] = []
    if any(r["reach"] == HOST for r in rows):
        L.append("  a host item is libcft's host code run against the CPU: a full-space test of the library in "
                 "which the tile computes nothing")
    if any(r["reach"] not in (TILE, HOST) for r in rows):
        L.append("  an unknown item has no `reach` in its records and an op the catalog's table does not name")
    return L


def _r_sweep(S: Dict[str, Any]) -> List[str]:
    W = S["sweep"]
    L = ["== SWEEP COVERAGE =="]
    if W["exhaustive"]:
        own = [e for e in W["exhaustive"] if e["total"] != EXH]
        L.append(f"exhaustive items (encodings of 2**32 = {EXH}"
                 + ("; an item marked [N indices] counts the indices of its own space, the hard-case and class-level modes'" if own else "")
                 + "):")
        # `reach` is the last column: the table is the one it was, plus one column at its end
        L += _table(["item", "slices", "cases", "covered", "pct", "intervals", "first_uncovered", "incomplete", "reach"],
                    [[e["item"] + (f" [{e['total']:,} indices]" if e["total"] != EXH else ""), str(e["slices"]), str(e["cases"]),
                      str(e["covered"]), _pct3(e["covered"], e["total"]), str(e["intervals"]),
                      _hex_range(*e["first_gap"]) if e["first_gap"] else "none", str(e["incomplete"]),
                      _reach_text(e["reach"])]
                     for e in W["exhaustive"]])
        t = W["total_exhaustive"]
        L.append(f"  total: {t['items']} exhaustive item(s) seen; covered {t['covered']} of {t['total']} "
                 f"encodings ({_pct3(t['covered'], t['total'])}); fully covered {t['complete_items']} of {t['items']}")
        for r in t["by_reach"]:
            L.append(f"  reach {_reach_text(r['reach'])}: {r['items']} exhaustive item(s) seen; covered {r['covered']} "
                     f"of {r['total']} encodings ({_pct3(r['covered'], r['total'])}); fully covered "
                     f"{r['complete_items']} of {r['items']}")
        L += _reach_note(t["by_reach"])
        if any(e.get("level") == "class" for e in W["exhaustive"]):
            L.append("  a class-level item (an op ending -class) is a claim at the class level (L2), PLAUSIBLE and not proved: a "
                     "representative of every class of operand, not a sweep of the operand space (docs/CARDDAY.md)")
        if any(e.get("level") == "hard" for e in W["exhaustive"]):
            L.append("  a hard-case item (an op ending -hard) is a deterministic space of constructed operands, the closest "
                     "approaches to a rounding boundary and the exact and edge quotients a sampler cannot reach, not the operand space")
        wide: Dict[str, Any] = {}
        for e in W["exhaustive"]:
            claim = ITEM_CLAIM.get(e["item"])
            if claim and ", under " in claim:
                what, attr = claim.rsplit(", under ", 1)
                wide.setdefault(_CATALOG[e["item"]].op, (what, []))[1].append(attr)
        if wide:
            L.append("  a wide item (parcel HXc: fp64, fp128 and fp256, checked against MPFR at fp128 and fp256 and the CPU's double at "
                     "fp64) claims, over its whole space and under its attribute:")
            L += [f"    {op} ({', '.join(attrs)}): {what}" for op, (what, attrs) in wide.items()]
    else:
        L.append("exhaustive items: none seen")
    L.append("")
    if W["random"]:
        L.append("random items (highest seed_n among completed slices):")
        L += _table(["item", "slices", "cases", "highest_seed_n", "incomplete", "reach"],
                    [[e["item"], str(e["slices"]), str(e["cases"]), _g(e["max_seed_n"]),
                      str(e["incomplete"]), _reach_text(e["reach"])] for e in W["random"]])
        L.append("  random reach: " + ", ".join(f"{_reach_text(r['reach'])} {r['items']} item(s)"
                                                for r in W["random_by_reach"]))
        L += _reach_note(W["random_by_reach"])
    else:
        L.append("random items: none seen")
    if W["other"]:
        L.append("")
        L.append("items with neither a range nor a seed in their records:")
        L += _table(["item", "slices", "cases", "incomplete"],
                    [[e["item"], str(e["slices"]), str(e["cases"]), str(e["incomplete"])] for e in W["other"]])
    L.append("")
    nc = ", ".join(f"{k} {n}" for k, n in W["not_completed"].items())
    L.append(f"slices: {W['completed']} completed (pass {W['completed'] - W['failed']}, fail {W['failed']}); "
             f"did not complete: {nc}; skipped {W['skipped']}")
    if W.get("batches"):
        # only when the run used the chunked tools (--sweep-chunk): the BATCH each slice's tool ran at, which is the number of
        # operands a flag word was compared over (the tools compare flags per batch: docs/CARDDAY.md, "The soak at a larger pass size")
        L.append("pass size, items with a slice that ran at another than the default 4096 (the BATCH its tool said; a slice with "
                 "none ran the default tools; flags are compared over a batch's operands, so a larger one hides a flag defect "
                 "among more of them; a class-level item compares flags per operand call whatever the batch is):")
        L += _table(["item", "slices by batch"],
                    [[b["item"], ", ".join(f"{n} at {bt}" for bt, n in b["by_batch"].items())] for b in W["batches"]])
    if W["outside_coverage"]:
        L.append(f"note: {W['outside_coverage']} completed sweep leg(s) carry no item or have fields "
                 f"the coverage cannot take, and are not in it")
    for m in W["malformed"]:
        L.append(f"  malformed sweep leg left out of the coverage: item {m['item']}, status {m['status']}, "
                 f"start {m['start']}: {m['why']}")
    dis = W["disagreements"]
    if not dis:
        L.append(f"no disagreement recorded in {W['completed']} completed slices")
    else:
        L.append(f"disagreements: {len(dis)}")
        for k, d in enumerate(dis, 1):
            sw = d["sweep"] if isinstance(d["sweep"], dict) else {}
            if "lo" in sw and "hi" in sw:
                what = f"range {_hex_range(int(sw['lo']), int(sw['hi']))}"
            else:
                what = (f"seed {_g(sw.get('seed'))} (seed_n {_g(sw.get('seed_n'))}, count {_g(sw.get('count'))})")
            if isinstance(sw.get("batch"), int):
                what += f", batch {sw['batch']}"
            L.append(f"  [{k}] item {d['item']}, image {d['image'] or '-'}, start {d['start'] or '-'}, {what}")
            L.append(f"      counts: {_counts_text(d['counts'])}")
            for x in d["lines"]:
                L.append(f"      {_line(x)}")
            L.append(f"      log: {d['log'] or 'none'}")
    return L


def _r_trees(S: Dict[str, Any]) -> List[str]:
    T = S["sweep"]["trees"]
    L = ["== SWEEP COVERAGE BY TREE =="]
    L.append("the key: a TILE item's slices are counted per RTL tree (`git rev-parse HEAD:rtl` of the checkout the run started from,")
    L.append("recorded in run_start), the images beneath each by what it covered alone; a HOST item's per library source (the tree hash of")
    L.append("host/) and compiler, since no tile computes it. A modified tree is its own class. A tree the run did not record is read from")
    L.append("its commit by git (`git rev-parse COMMIT:rtl`, the driver's own rule) where the checkout holds the commit and the run was recorded")
    L.append("clean, and its class says \"read from git\"; otherwise it is kept apart by its commit, with the reason. A slice is counted under")
    L.append("the last run_start before it in its file. Nothing is summed across classes.")
    for s in T["sources"]:
        extra = ""
        if s["bad_lines"]:
            extra += f"; !!! {len(s['bad_lines'])} UNPARSABLE LINE(S) left out (line number(s) {', '.join(str(n) for n in s['bad_lines'][:20])})"
        if s["partial_tail"]:
            extra += "; a partial last line left out"
        L.append(f"read: {_line(s['source'], 120)} ({s['records']} records{extra})")
    g = T.get("git")
    if isinstance(g, dict):
        src = g.get("source") or ("git" if g.get("read") else "records")          # a summary from before `source` has only `read`
        L.append("git: " + {"git": "read for each run_start that recorded no tree",
                            "given rev": "NOT read: a function the caller gave supplied the trees a run_start did not record"}.get(
                                src, "not read (--no-git): a run that recorded no tree is kept apart by its commit")
                 + (f"; !!! {_line(g['problem'], 200)}: what git was not asked is unread, not absent" if g.get("problem") else ""))
    if not T["classes"]:
        L.append("no completed sweep slice in the runs read")
        return L
    for c in T["classes"]:
        L.append("")
        runs = ", ".join(_line(r, 60) for r in c["runs"]) or "no run id"
        cms = ", ".join(x[:12] for x in c["commits"]) or "none recorded"
        L.append(f"{c['kind']} items - {c['label']}")
        L.append(f"  runs: {runs}; commits: {cms}; images that served it: {', '.join(c['images']) or 'none'}")
        imgs = c["images"]
        if c["exhaustive"]:
            L.append("  exhaustive items (encodings of 2**32"
                     + ("; an item marked [N indices] counts the indices of its own space" if any(e["total"] != EXH for e in c["exhaustive"]) else "")
                     + "; an image's column is what that image covered alone):")
            L += _table(["item", "covered", "pct", "slices"] + imgs,
                        [[e["item"] + (f" [{e['total']:,} indices]" if e["total"] != EXH else ""), str(e["covered"]),
                          _pct3(e["covered"], e["total"]), str(e["slices"])]
                         + [str(e["by_image"][i]) if i in e["by_image"] else "-" for i in imgs] for e in c["exhaustive"]])
            t = c["total"]
            L.append(f"  total: {t['items']} exhaustive item(s) seen; covers {t['covered']} of {t['total']} encodings "
                     f"({_pct3(t['covered'], t['total'])}); fully covered {t['complete_items']} of {t['items']}; by image: "
                     + (", ".join(f"{i} {n}" for i, n in t["by_image"].items()) or "none"))
        else:
            L.append("  exhaustive items: none seen")
        if c["random"]:
            L.append("  random items (cases by image; highest seed_n among completed slices):")
            L += _table(["item", "slices", "cases", "highest_seed_n"] + [f"cases_{i}" for i in imgs],
                        [[e["item"], str(e["slices"]), str(e["cases"]), _g(e["max_seed_n"])]
                         + [str(e["by_image"][i]) if i in e["by_image"] else "-" for i in imgs] for e in c["random"]])
        else:
            L.append("  random items: none seen")
    return L


def _r_uptime(S: Dict[str, Any]) -> List[str]:
    U, h = S["uptime"], S["header"]
    L = ["== UPTIME AND GAPS =="]
    if U["wall_s"] is None:
        L.append("no record carries an epoch: no time figure can be computed")
    else:
        end = "now" if h["running"] else f"the last record ({h['last_record']['ts']})"
        L.append(_kv("wall span", f"{_g(U['wall_s'])} s ({_dur(U['wall_s'])}), the first record "
                                  f"({h['started']['ts'] if h['started'] else '-'}) to {end}"))

        def frac(x: Optional[float]) -> str:
            return "n/a" if x is None else "%.1f%%" % (100.0 * x)

        L.append(_kv("in legs", f"{_g(U['legs_union_s'])} s ({_dur(U['legs_union_s'])}), {frac(U['legs_fraction'])} "
                                f"of the wall span; the union of {U['legs_used']} leg interval(s), sweep legs overlap"))
        L.append(_kv("on the card", f"{_g(U['card_union_s'])} s ({_dur(U['card_union_s'])}), "
                                    f"{frac(U['card_fraction'])}; battery and sweep legs, not skipped"))
        if U["legs_unusable"]:
            L.append(f"  note: {U['legs_unusable']} leg record(s) without a usable start and end are in no union")
        for key, fld in (("before 1st leg", "before_first_leg_s"), ("after last leg", "after_last_leg_s")):
            L.append(_kv(key, "-" if U[fld] is None else f"{_g(U[fld])} s"))
        lg = U["longest_gap"]
        if lg is None:
            L.append(_kv("longest gap", "n/a (the legs form one piece, or there is none)"))
        else:
            L.append(_kv("longest gap", f"{_g(lg['seconds'])} s ({_dur(lg['seconds'])}), from {lg['start']} to {lg['end']}"))
        L.append(_kv("gaps > %g s" % U["gap_seconds"], str(U["gaps_over"])))
        for k, g in enumerate(U["gaps"], 1):
            L.append(f"  gap {k}: {g['start']} to {g['end']}, {_g(g['seconds'])} s ({_dur(g['seconds'])}), "
                     f"{len(g['events'])} event(s) inside")
            for e in g["events"][:GAP_EVENTS_SHOWN]:
                L.append(f"      {e['ts']}  {e['event']}: {_line(e['detail'], 200)}")
            if len(g["events"]) > GAP_EVENTS_SHOWN:
                L.append(f"      ... {len(g['events']) - GAP_EVENTS_SHOWN} more, all in the --json file")
            for m in g["records"]:
                L.append(f"      {m['ts']}  [{_line(m['text'], 200)}]")
    ev = U["events_by_name"]
    L.append(_kv("events", ", ".join(f"{k} {n}" for k, n in ev.items()) if ev else "none"))
    ends = h["run_ends"]
    if ends:
        for e in ends:
            L.append(_kv("run_end", f"{e['ts']}, reason {e['reason'] or '-'}, exit {_g(e['exit'])}, cycles {_g(e['cycles'])}"))
    else:
        L.append(_kv("run_end", "none recorded"))
    return L


def render(summary: Dict[str, Any]) -> str:
    """The report's text, built from the summary alone (so from its JSON as well)."""
    summary = _scrub(summary)
    out = _r_top(summary)
    if out:
        out.append("")
    out.append("card stress report: derived from metrics.jsonl, which is the record; this text is "
               "rewritten whole at each run of the report")
    out.append("")
    for part in (_r_header, _r_totals, _r_rows, _r_telemetry, _r_failures, _r_sweep, _r_trees, _r_uptime):
        out += part(summary)
        out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# the command line
# ---------------------------------------------------------------------------

def _write_atomic(path: str, text: str) -> None:
    tmp = f"{path}.tmp{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="card_stress_report.py",
        description="Read a card stress run's metrics.jsonl and print an account of it (any time, "
                    "during the run or after). See this file's docstring for what each part means.")
    ap.add_argument("run_dir", metavar="RUN_DIR", help="the run's directory: it holds metrics.jsonl")
    ap.add_argument("--json", metavar="FILE", default=None,
                    help="also write the same figures as JSON to FILE (sweep.trees.classes[]: key, label - which says \"read from git\" "
                         "where a run's tree was - and derived_from_git, the {commit, dir, tree} of each run whose tree in the class was "
                         "read from git, sorted by commit, dir and tree, [] when none was; for a rev that is not git, which only a caller of summarize() can give, the label "
                         "says \"taken from the given rev, not git\" and derived_from_git is what that function answered; "
                         "sweep.trees.git: {read, source, problem}, whether git was read, where the trees came from and what stopped it)")
    ap.add_argument("--no-git", action="store_true",
                    help="read the records alone: a run_start that recorded no tree stays kept apart by its commit (the default reads "
                         "that tree from git, `git rev-parse COMMIT:rtl`, in the checkout this report is in)")
    ap.add_argument("--no-write", action="store_true",
                    help="do not write RUN_DIR/report.txt (the text still goes to stdout)")
    ap.add_argument("--gap-seconds", type=float, default=300.0, metavar="N",
                    help="list the gaps between legs longer than N seconds (default 300)")
    ap.add_argument("--also", action="append", default=[], metavar="DIR",
                    help="another run's directory, whose sweep slices are added to the coverage-by-tree section ALONE "
                         "(coverage accumulated over runs; each slice stays under its own run's tree); repeatable")
    a = ap.parse_args(argv)
    if not math.isfinite(a.gap_seconds) or a.gap_seconds < 0:
        ap.error("--gap-seconds must be a number of seconds, 0 or more")
    me = "card_stress_report"
    metrics = os.path.join(a.run_dir, "metrics.jsonl")
    if not os.path.isdir(a.run_dir):
        print(f"{me}: {a.run_dir} is not a directory (RUN_DIR is the run's output directory, "
              f"the one that holds metrics.jsonl)", file=sys.stderr)
        return 2
    if not os.path.isfile(metrics):
        print(f"{me}: {metrics} does not exist: RUN_DIR is not a run's output directory, or the "
              f"driver has not started writing there", file=sys.stderr)
        return 2
    try:
        size = os.path.getsize(metrics)
        records, partial, bad = read_records(metrics)
    except OSError as e:
        print(f"{me}: cannot read {metrics}: {e}", file=sys.stderr)
        return 2
    if not any(isinstance(r, dict) for r in records):
        if size == 0:
            print(f"{me}: {metrics} is empty (0 bytes): the driver has not written its first record "
                  f"yet, or this is not its run directory", file=sys.stderr)
        else:
            print(f"{me}: {metrics} holds no record that can be read ({size} bytes; "
                  f"unparsable line(s): {', '.join(str(n) for n in bad) or 'none'}; "
                  f"a partial last line: {'yes' if partial else 'no'})", file=sys.stderr)
        return 2
    also = []
    for d in a.also:
        mp = os.path.join(d, "metrics.jsonl")
        if not os.path.isfile(mp):
            print(f"{me}: --also {d}: no metrics.jsonl there: name a run's output directory", file=sys.stderr)
            return 2
        try:
            recs2, partial2, bad2 = read_records(mp)
        except OSError as e:
            print(f"{me}: --also {d}: cannot read {mp}: {e}", file=sys.stderr)
            return 2
        also.append({"source": d, "objs": [r for r in recs2 if isinstance(r, dict)], "bad_lines": bad2,
                     "partial_tail": partial2})
    try:
        summary = summarize(records, gap_seconds=a.gap_seconds, partial_tail=partial, bad_lines=bad, also=also,
                            **({"rev": None} if a.no_git else {}))
        text = render(summary)
    except Exception as e:          # a bug here must not leave a stale report that looks current
        msg = f"the report itself failed: {type(e).__name__}: {e}"
        print(f"{me}: {msg}", file=sys.stderr)
        traceback.print_exc()
        if not a.no_write:
            try:
                _write_atomic(os.path.join(a.run_dir, "report.txt"),
                              f"{msg}\n(see the report's stderr; metrics.jsonl is intact)\n")
            except OSError:
                pass
        return 3
    sys.stdout.write(text)
    sys.stdout.flush()
    status = 0
    if not a.no_write:
        try:
            _write_atomic(os.path.join(a.run_dir, "report.txt"), text)
        except OSError as e:
            print(f"{me}: could not write report.txt: {e}", file=sys.stderr)
            status = 1
    if a.json:
        try:
            _write_atomic(a.json, json.dumps(summary, indent=1, allow_nan=False) + "\n")
        except (OSError, ValueError) as e:
            print(f"{me}: could not write {a.json}: {e}", file=sys.stderr)
            status = 1
    return status


def _utf8_streams() -> None:
    """A record's text may not be ASCII, and a pipe's default encoding may not hold it."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


if __name__ == "__main__":
    _utf8_streams()
    sys.exit(main())
