#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Reduce a long run's metrics.jsonl to the one small JSON file the nightly progress page reads.

    python3 hw/card_stress_progress.py RUN_DIR [--out FILE] [--commit SHA|none]
    python3 hw/card_stress_progress.py --check FILE RUN_DIR

EVERY FIGURE IS summarize()'s (hw/card_stress_report.py); this adds no second coverage computation. It calls summarize()
(1) over the records up to each night's end: the cumulative state after that night; (2) over each night alone: its header;
(3) over the records of the nights that ran under one tree class: the class's first uncovered index, which the report
states for the whole run only, so mixing classes. The rest is arithmetic on those results: differences between
consecutive nights, a sum and a ratio, the night an item first completed, and one estimate. A class's covered figure
from (3) is held to the report's own, and the file is not made if they differ. hw/test_card_stress_progress.py holds
every shared figure to `card_stress_report.py RUN --json` on real copies.

NIGHTS. A night is a run_start and the records up to the next run_start (a resumed run appends one each night). It is
CLOSED if it holds a run_end; with none, it is "no run_end recorded" (interrupted if a later run_start follows, running or
dead if last) and its end is its last record's. Its date is the date it STARTED, on the box's clock as the records give
it. A run_end's `cycles` is the run's cumulative number, so a night's cycles are its cycle_start records.

CLASSES, as the report keys and labels them, for the labels are the report's: a tile item per RTL tree, a host item per host
tree and compiler, a tree with uncommitted changes its own class, a run that recorded no tree read from git where its commit
says (the label names the commit: "read from git at commit X") and else kept apart by its commit, with the report's reason.
Nothing is summed across classes. The CURRENT class of each kind is the newest night's. It is listed even with no slice yet, and
the campaign's items (the newest run_start's --sweep-items) are listed in it at zero, which the report cannot do. A class the
report says it read from git (`derived_from_git`) is carried with that note. summarize() names a class only where a slice fell in
it, so a class nothing was swept under (today's current host class) is the report's public tree_class(kind, run_start): its own
rule and label, no fallback, an error from it a failure.

THE ESTIMATE (COMPUTED; the rule is in the file). For an open item of a current class: gain = covered now minus covered
after the night before the window, the window being the class's last 3 nights (fewer if it has fewer); nights_left =
ceil(remaining x window nights / gain); the date is the newest night's date plus that many days. No gain: no estimate.

GROUPS (parcel HXd). Within a class the items are in two groups, the report's: "base", and "wide" (the wide-format items, Item.mpfr). Each row
carries its `format` (the catalog's: what it computes in, a conversion's both ends) and its `group`; each class carries `groups`, its totals by
group (only the groups it has rows of) beside `total`, which stays over every row; and a night's `after.groups` (class -> group -> covered and
complete) is written only once the class has a wide row served, so that the nights before it are the nights they were. Fields are added, none
changed: SCHEMA stays 1, and a data file without them is read as the page has always read it.

RATES (parcel TP, 2026-10-28). The file gains ONE top-level field, `rates`: for each night, from that night's own records and the report's `rates`
(card_stress_report._rates), the card's throughput by op and format - cases a second on one tile, a row for each (image, op, format, level), its tiles,
their pool and their sum - and, for a night with probe legs, the card-only rates beside them. It is NOT a field of `nights[i]`: the scheduler's
publish step compares every field of the nights the published file holds (hw/sched/sched_publish.py, first_diff, which is symmetric on keys), so a
field added to an earlier night would be refused as `earlier-night-changed`; a top-level field leaves every night the night it was, and the nights
before these tools get their rows too, derived from the slices their records hold. A file made without it is read as it always was.

NOTHING PRIVATE. Only counts, item names, short tree hashes, the compiler's version line, a run_end reason that is a plain
snake_case word, and the images' names, tile counts and short sha256 are passed through. Every string of the result is then
held against the private text the records themselves carry (host, directory, image paths, the user names in them) and
against the shapes of a path and an IP address: a hit refuses the file (status 3). A dry-run night is refused (status 2):
its slices ran against stand-ins. So is a damaged file (an unparsable line in the middle): the report goes on with the
lines that parse, and says so loudly, and a public page must not.

--check FILE RUN_DIR re-derives FILE from RUN_DIR and compares every field but `made`. `made.commit` is the commit the TOOLS were at
when the file was made: git's HEAD of the checkout that ran them, which is normally the commit before the data file's own, since the
routine makes the file before committing it; `--commit SHA` records another, which may be the file's own. It cannot be re-derived. A
difference names the first fields that differ. It is the morning check.

Exit status, the report's: 0 made (or --check: equal); 2 nothing to reduce or check (RUN_DIR or metrics.jsonl missing, unreadable,
empty or damaged, no run_start, a record before the first, a dry run, a --check FILE missing, not JSON or not a data file (no
`made.commit` of 40 lowercase hex digits or null), a usage error); 1 made but not written, or --check found a difference; 3 the
reducer failed or refused its own check (a bug, or private text in a published field; the message is on stderr).
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import traceback
from typing import Any, Dict, List, Optional, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)            # python -I does not put the script's directory there
import card_stress_report as R           # noqa: E402  (summarize() is the authority)
from card_stress_lib import EXH, HOST, TILE, read_records, sweep_items   # noqa: E402

SCHEMA = 1
WINDOW = 3                               # nights the estimate looks back over
JS_SAFE = (1 << 53) - 1                  # the page reads numbers as doubles: nothing past this is exact there
KINDS = (TILE, HOST)
CLASS_PREFIX = {TILE: "t", HOST: "h"}
RULES = {
    "night": "A night is one run_start and the records after it up to the next one; the run resumes each night. Its date is the "
             "date it started, on the clock of the card's host.",
    "classes": "Coverage is evidence about the thing that ran. A slice swept on one RTL tree says nothing about another, so a tile "
               "item is counted per RTL tree, and a host item per host tree and compiler, because no tile computes it. A changed "
               "tree starts a new class from nothing, and nothing is summed across classes. How a run that did not record its tree "
               "is placed is the report's rule, and the class's label says which.",
    "groups": "Within a class the items are in two groups, each counted over its own items and spaces so that a group joining a class does not "
              "move the other's figures: the base items, and the wide-format items (fp64, fp128 and fp256), which exist only in a tool built "
              "against the pinned MPFR. A class's total is over both. Each item names the format it computes in; a conversion names both ends.",
    "estimate": "ESTIMATE, not a measurement. For an item not yet fully covered in a current class: its gain over the class's last "
                "3 nights (fewer if the class is younger), divided by the nights in that window, is its rate a night; the nights "
                "left are the remaining indices over that rate, rounded up; the date counts that many days after the newest night, "
                "assuming a night every day. It does not know of a skipped night, or that items finishing free time for the rest.",
    "card_time": "Time on the card is the report's: the union of the battery and sweep legs' intervals on the card images, skipped "
                 "legs and the host pool's legs left out. The wall span runs from the first record to the last and includes the "
                 "days between nights.",
}
_CAT = {it.name: it for it in sweep_items(mpfr=True)}      # with the wide items (parcel HXc), so a night that names one does not call it unknown
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_PATHY = re.compile(r"(?:^|[\s\"'(=:,;\[])(?:[A-Za-z]:[\\/]|\\\\|~/|/[A-Za-z0-9._~-]+/[A-Za-z0-9._~-])")
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_USER = re.compile(r"(?:/hom[e]/|/Users/|[A-Za-z]:[\\/]Users[\\/])([A-Za-z0-9._-]+)")     # the user in a home directory: Linux, macOS, Windows


class Refused(Exception):
    """Nothing honest can be reduced from this input (status 2)."""


class Failed(Exception):
    """The reducer failed its own check (status 3)."""


def _num(x: Any) -> Optional[float]:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or (isinstance(x, float) and not math.isfinite(x)):
        return None
    return x


def _last_epoch(recs: List[Dict[str, Any]]) -> float:
    es = [e for r in recs if (e := _num(r.get("epoch"))) is not None]
    return float(max(es)) if es else 0.0


def _sub(a: Any, b: Any) -> Any:
    """a - b, None if either is unknown (never 0), rounded to the milliseconds the records carry."""
    return None if a is None or b is None else (round(a - b, 3) if isinstance(a, float) or isinstance(b, float) else a - b)


def _r3(x: Any) -> Any:
    return None if x is None else round(x, 3)


def _short(h: Any, n: int = 12) -> Optional[str]:
    return h[:n] if isinstance(h, str) and h else None


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def load(run_dir: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    metrics = os.path.join(run_dir, "metrics.jsonl")
    if not os.path.isdir(run_dir):
        raise Refused(f"{run_dir} is not a directory (RUN_DIR is the run's output directory, the one that holds metrics.jsonl)")
    if not os.path.isfile(metrics):
        raise Refused(f"{metrics} does not exist: RUN_DIR is not a run's output directory")
    try:
        with open(metrics, "rb") as fh:
            data = fh.read()
        records, partial, bad = read_records(metrics)
    except OSError as e:
        raise Refused(f"cannot read {metrics}: {e}")
    objs = [r for r in records if isinstance(r, dict)]
    if not objs:
        raise Refused(f"{metrics} holds no record that can be read ({len(data)} bytes)")
    if bad:
        raise Refused(f"{len(bad)} unparsable line(s) in metrics.jsonl, line number(s) {', '.join(map(str, bad[:20]))}: the report "
                      f"goes on with the lines that parse and says so, and a page that states figures must not")
    if len(objs) != len(records):
        raise Refused(f"{len(records) - len(objs)} line(s) of metrics.jsonl parse as JSON but are not records (objects)")
    starts = [i for i, r in enumerate(objs) if r.get("type") == "run_start"]
    if not starts:
        raise Refused("no run_start record: this is not a run's record, and there is no night to date")
    if starts[0] != 0:
        raise Refused(f"{starts[0]} record(s) come before the first run_start: a night with no start cannot be dated")
    for n, i in enumerate(starts, 1):
        st = objs[i].get("settings")
        if isinstance(st, dict) and st.get("dry_run") is True:
            raise Refused(f"night {n} is a dry run (settings.dry_run): its slices ran against stand-ins, not the card")
    return objs, {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "partial_tail": bool(partial)}


def spans_of(objs: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
    starts = [i for i, r in enumerate(objs) if r.get("type") == "run_start"] + [len(objs)]
    return list(zip(starts, starts[1:]))


def campaign_items(objs: List[Dict[str, Any]], last_start: int) -> Optional[List[str]]:
    argv = objs[last_start].get("argv")
    if not isinstance(argv, list):
        return None
    for i, a in enumerate(argv):
        if a == "--sweep-items" and i + 1 < len(argv) and isinstance(argv[i + 1], str):
            return [x for x in argv[i + 1].split(",") if x]
        if isinstance(a, str) and a.startswith("--sweep-items="):
            return [x for x in a.split("=", 1)[1].split(",") if x]
    return None


def _entry(summary: Dict[str, Any], kind: str, key: str) -> Optional[Dict[str, Any]]:
    for c in summary["sweep"]["trees"]["classes"]:
        if c["kind"] == kind and c["key"] == key:
            return c
    return None


# ---------------------------------------------------------------------------
# the reduction
# ---------------------------------------------------------------------------

def reduce_records(objs: List[Dict[str, Any]], info: Dict[str, Any], commit: Any = None) -> Dict[str, Any]:
    spans = spans_of(objs)
    n_nights = len(spans)
    cums = [R.summarize(objs[:b], now=_last_epoch(objs[:b])) for _a, b in spans]
    owns = [R.summarize(objs[a:b], now=_last_epoch(objs[a:b])) for a, b in spans]
    final = cums[-1]
    if final["report_version"] != 1:
        raise Failed(f"the report's summary is version {final['report_version']}; this reducer reads version 1")

    # -- classes, as the report gives them: a night's own summary says which class its slices of each kind fell in, so a rule the report
    #    changes (reading an unrecorded tree from git) is followed here, not copied; a kind with no slice that night is read off the
    #    night's tree, so that a current class with nothing swept is still listed
    reg: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def register(kind: str, key: str, label: str, night: Optional[int]) -> Dict[str, Any]:
        c = reg.get((kind, key))
        if c is None:
            n = 1 + sum(1 for k, _ in reg if k == kind)
            c = reg[(kind, key)] = {"id": f"{CLASS_PREFIX.get(kind, 'u')}{n}", "kind": kind, "key": key, "label": label, "nights": []}
        if night is not None:
            c["nights"].append(night)
        return c

    labels = {(e["kind"], e["key"]): e["label"] for e in final["sweep"]["trees"]["classes"]}       # the whole run's label of a class, as --json shows it
    night_class: List[Dict[str, str]] = []
    for k, ((a, _b), own) in enumerate(zip(spans, owns), 1):
        ids = {}
        for kind in KINDS:
            got = [e for e in own["sweep"]["trees"]["classes"] if e["kind"] == kind]
            if len(got) > 1:
                raise Failed(f"night {k}: the report put its {kind} slices in {len(got)} classes, and a night has one tree")
            key, label = (got[0]["key"], got[0]["label"]) if got else R.tree_class(kind, objs[a])       # no fallback: an error from the report is a failure
            ids[kind] = register(kind, key, labels.get((kind, key), label), k)["id"]
        night_class.append(ids)
    for cum in cums:                                     # a class no night's tree names (slices of unknown reach)
        for e in cum["sweep"]["trees"]["classes"]:
            register(e["kind"], e["key"], e["label"], None)
    classes = list(reg.values())

    # -- the campaign: the items the newest run_start asked for
    named = campaign_items(objs, spans[-1][0])
    unplaced = [n for n in (named or []) if n not in _CAT]

    # -- per class: the first gap of each item (the report's, over the nights that ran under the class), and the check
    firsts: Dict[str, Dict[str, Any]] = {}
    for c in classes:
        firsts[c["id"]] = {}
        if c["kind"] not in KINDS or not c["nights"]:
            continue
        recs = [r for k in c["nights"] for r in objs[spans[k - 1][0]:spans[k - 1][1]]]
        own = R.summarize(recs, now=_last_epoch(recs))
        for e in own["sweep"]["exhaustive"]:
            firsts[c["id"]][e["item"]] = e
        ent = _entry(final, c["kind"], c["key"])
        for e in (ent["exhaustive"] if ent else []):
            got = firsts[c["id"]].get(e["item"])
            if got is None or got["covered"] != e["covered"]:
                raise Failed(f"class {c['id']} item {e['item']}: covered {e['covered']} by the report's coverage by tree, "
                             f"{None if got is None else got['covered']} over the nights that ran under it")

    # -- nights
    nights: List[Dict[str, Any]] = []
    prev: Optional[Dict[str, Any]] = None
    first_complete: Dict[Tuple[str, str], int] = {}
    for k, ((a, b), cum, own) in enumerate(zip(spans, cums, owns), 1):
        h = own["header"]
        closed = not h["running"]
        end = h["run_ends"][-1] if closed else (h["last_record"] or {"ts": None, "epoch": None})
        st = h["started"] or {"ts": None, "epoch": None}
        reason = end.get("reason") if closed else None
        tr = h["trees"][0] if h["trees"] else {}
        legs_now, legs_prev = cum["totals"]["legs"]["by_status"], (prev["totals"]["legs"]["by_status"] if prev else {})
        cases_now = sum(e["cases"] for g in ("exhaustive", "random", "other") for e in cum["sweep"][g])
        cases_prev = sum(e["cases"] for g in ("exhaustive", "random", "other") for e in prev["sweep"][g]) if prev else 0
        after_classes: Dict[str, Any] = {}
        after_groups: Dict[str, Any] = {}
        for c in classes:
            if not c["nights"] or c["nights"][0] > k:
                continue
            ent = _entry(cum, c["kind"], c["key"])
            seen = ent["exhaustive"] if ent else []
            for e in seen:
                if e["complete"]:
                    first_complete.setdefault((c["id"], e["item"]), k)
            after_classes[c["id"]] = {"covered": sum(e["covered"] for e in seen), "complete": sum(1 for e in seen if e["complete"])}
            if any(e["group"] == "wide" for e in seen):
                after_groups[c["id"]] = {g: {"covered": sum(e["covered"] for e in mine), "complete": sum(1 for e in mine if e["complete"])}
                                         for g in R.GROUPS if (mine := [e for e in seen if e["group"] == g])}
        nights.append({
            "n": k, "date": st["ts"][:10] if isinstance(st.get("ts"), str) and re.match(r"\d{4}-\d\d-\d\d", st["ts"]) else None,
            "start": st["ts"], "start_epoch": st["epoch"], "end": end.get("ts"), "end_epoch": end.get("epoch"),
            "closed": closed, "reason": reason if isinstance(reason, str) and _REASON.match(reason) else None,
            "reason_withheld": bool(closed and reason is not None and not (isinstance(reason, str) and _REASON.match(reason))),
            "exit": end.get("exit") if closed else None,
            "span_s": _sub(end.get("epoch"), st["epoch"]), "card_s": _sub(cum["uptime"]["card_union_s"], prev["uptime"]["card_union_s"] if prev else 0.0),
            "cycles": own["totals"]["cycles"]["started"],
            "legs": {s: legs_now.get(s, 0) - legs_prev.get(s, 0) for s in legs_now},
            "slices": cum["sweep"]["completed"] - (prev["sweep"]["completed"] if prev else 0), "cases": cases_now - cases_prev,
            "disagreements": len(cum["sweep"]["disagreements"]) - (len(prev["sweep"]["disagreements"]) if prev else 0),
            "quick": (h["flags"] or {}).get("quick"), "dry_run": (h["flags"] or {}).get("dry_run"),
            "tree": {"commit": _short(tr.get("commit")), "dirty": tr.get("dirty"), "rtl": _short(tr.get("rtl")),
                     "rtl_dirty": tr.get("rtl_dirty"), "host_src": _short(tr.get("host_src")),
                     "host_src_dirty": tr.get("host_src_dirty"), "cc": tr.get("cc")},
            "images": [{"name": nm, "tiles": i["tiles"], "sha256": _short(i["sha256"])} for nm, i in (cum["header"]["images"] or {}).items()],
            "classes": night_class[k - 1],
            "after": dict({"card_s": _r3(cum["uptime"]["card_union_s"]), "slices": cum["sweep"]["completed"], "cases": cases_now, "classes": after_classes},
                          **({"groups": after_groups} if after_groups else {})),
        })
        prev = cum

    # -- now: each class and its rows, with each open row's estimate
    date_new = nights[-1]["date"]
    now_classes: List[Dict[str, Any]] = []
    for c in classes:
        current = bool(c["nights"]) and c["nights"][-1] == n_nights and c["kind"] in KINDS
        ent = _entry(final, c["kind"], c["key"])
        rows: Dict[str, Dict[str, Any]] = {}
        for e in (ent["exhaustive"] if ent else []):
            rows[e["item"]] = {"item": e["item"], "space": e["total"], "covered": e["covered"], "pct": e["pct"], "slices": e["slices"],
                               "cases": e["cases"], "complete": e["complete"], "format": e["format"], "group": e["group"]}
        for name in (named or []):
            it = _CAT.get(name)
            if current and name not in rows and it is not None and it.kind == "exhaustive" and it.reach == c["kind"]:
                rows[name] = {"item": name, "space": R.ITEM_SPACE.get(name, EXH), "covered": 0, "pct": 0.0, "slices": 0, "cases": 0,
                              "complete": False, "format": R.ITEM_FORMAT.get(name), "group": R.ITEM_GROUP.get(name, "base")}
        window = c["nights"][-WINDOW:] if current else []
        for name, row in sorted(rows.items()):
            row.update(level=R.ITEM_LEVEL.get(name), in_campaign=bool(named is None or name in named),
                       complete_night=first_complete.get((c["id"], name)), first_gap=None, estimate=None, estimate_note=None)
            if row["complete"]:
                continue
            fg = firsts[c["id"]].get(name)
            # the report's first gap over the nights that ran under this class; an item nothing was swept for has none to
            # state, and its first open index is 0
            row["first_gap"] = (fg or {}).get("first_gap") or ([0, row["space"]] if row["covered"] == 0 else None)
            if not current:
                continue
            base = 0                          # the class's coverage of the item after the night before the window
            if window[0] >= 2:
                be = _entry(cums[window[0] - 2], c["kind"], c["key"])
                base = next((e["covered"] for e in (be["exhaustive"] if be else []) if e["item"] == name), 0)
            gain = row["covered"] - base
            if gain <= 0:
                row["estimate_note"] = f"no gain in the last {len(window)} night(s) of this class"
                continue
            left = -(-(row["space"] - row["covered"]) * len(window) // gain)       # ceil, in integers
            row["estimate"] = {"window_nights": len(window), "per_night": gain // len(window), "nights_left": left,
                               "date": ((datetime.date.fromisoformat(date_new) + datetime.timedelta(days=left)).isoformat()
                                        if date_new else None)}
        items = [rows[n] for n in sorted(rows)]
        cov, space = sum(r["covered"] for r in items), sum(r["space"] for r in items)
        by_group = []
        for g in R.GROUPS:
            mine = [r for r in items if r["group"] == g]
            if mine:
                gc, gs = sum(r["covered"] for r in mine), sum(r["space"] for r in mine)
                by_group.append({"group": g, "items": len(mine), "complete": sum(1 for r in mine if r["complete"]), "covered": gc, "space": gs,
                                 "pct": (100.0 * gc / gs) if gs else None})
        now_classes.append({
            "id": c["id"], "kind": c["kind"], "key": c["key"], "label": c["label"], "current": current, "served": ent is not None,
            "nights": c["nights"],
            "total": {"items": len(items), "complete": sum(1 for r in items if r["complete"]), "covered": cov, "space": space,
                      "pct": (100.0 * cov / space) if space else None},
            "groups": by_group,
            "items": items,
        })
        # the report says a class holds a run whose tree it read from git (`derived_from_git`, a list of {commit, dir, tree}); carried as it
        # comes, and absent when the report has none, which is the report before that field
        dg = [{"commit": _short(x.get("commit")), "dir": x.get("dir"), "tree": _short(x.get("tree"))}
              for x in ((ent or {}).get("derived_from_git") or []) if isinstance(x, dict)]
        if dg:
            now_classes[-1]["derived_from_git"] = dg

    complete_list = sorted(({"class": cid, "item": it, "night": k, "date": nights[k - 1]["date"]} for (cid, it), k in first_complete.items()),
                           key=lambda d: (d["night"], d["class"], d["item"]))
    up, sw = final["uptime"], final["sweep"]
    out = {
        "schema": SCHEMA,
        "made": {"by": "hw/card_stress_progress.py", "report_version": final["report_version"], "commit": commit},
        "source": {"run_ids": final["header"]["run_ids"], "records": len(objs), "metrics_sha256": info["sha256"],
                   "metrics_bytes": info["bytes"], "partial_tail": info["partial_tail"]},
        "newest": {"night": n_nights, "date": date_new, "start": nights[-1]["start"], "end": nights[-1]["end"],
                   "end_epoch": nights[-1]["end_epoch"], "closed": nights[-1]["closed"]},
        "rules": RULES,
        "nights": nights,
        "now": {"campaign": {"items": named, "named_by": ("the newest run_start's --sweep-items" if named is not None else
                                                          "nothing: the newest run_start named no items, so the whole catalog"),
                             "unknown_to_the_catalog": unplaced},
                "classes": now_classes},
        "totals": {
            "nights": n_nights, "closed_nights": sum(1 for n in nights if n["closed"]), "wall_s": _r3(up["wall_s"]), "card_s": _r3(up["card_union_s"]),
            "first": final["header"]["started"]["ts"] if final["header"]["started"] else None, "slices": sw["completed"],
            "cases": nights[-1]["after"]["cases"], "disagreements": len(sw["disagreements"]), "completed_slices": sw["completed"],
            "disagreement_list": [{"item": d["item"], "image": d["image"], "start": d["start"]} for d in sw["disagreements"]],
            "legs": {"total": final["totals"]["legs"]["total"], "by_status": final["totals"]["legs"]["by_status"]},
            "cycles": final["totals"]["cycles"]["started"], "fully_covered": complete_list,
        },
        "rates": rates_of(owns, nights),          # parcel TP: LAST, a field of its own (see RATES in the docstring): no night's entry has changed
    }
    guard(out, objs)
    return out


# ---------------------------------------------------------------------------
# the rates (parcel TP)
# ---------------------------------------------------------------------------

class OneLine(dict):
    """A dict the file writes on one line whatever its length (a rate row, which holds a tile's figures for each of four tiles): _inline says so.
    json.dumps treats it as the dict it is, and --check reads the file back as plain dicts."""


RATES_COLUMNS = ["slices", "cases", "median", "min", "max"]
RATES_SUM_COLUMNS = ["tiles", "median", "min", "max"]
PROBE_COLUMNS = ["rows", "median", "min", "max"]
RATES_RULE = ("Per night, from that night's own records: the card's throughput by op and format, in cases a second on one tile. A row is an (image, op, "
              "format, level); it is made of the night's sweep slices that ran on a tile of the card (reach tile, level exhaustive or hard, status pass) "
              "and of nothing else: the class level (one case a call), the host reach (the CPU) and the random items are left out, and `left_out` counts "
              "them and every other leg that is not in a row, by reason. A rate is the slice's own, its cases over its whole duration with the soak "
              "process's start and the host's oracle in it, so it is the pipeline's pace and not the tile's alone. A case is one element through the op; a "
              "hard item's cases are the ones its tool compared, its skipped slots left out. `all` is the image's slices pooled and `tiles` each tile's "
              "([slices, cases, median, least, most], cases a second); `sum` adds the tiles' medians, least and most (bounds, not measured quad rates). "
              "`card` is the night's probe rate with the oracle off for the same op and format, per tile, and its ratio to `all`'s median; null where "
              "no probe ran that night, never a zero. `from` names the catalog ops pooled in a row.")


def rate_row(e: Dict[str, Any]) -> "OneLine":
    """The report's rate row as the file keeps it: a figure list for each of `all` and the tiles (RATES_COLUMNS), so that a night of the whole catalog is a
    line a row and not a hundred."""
    return OneLine({
        "image": e["image"], "op": e["op"], "format": e["format"], "level": e["level"], "from": e["from"],
        "all": [e["all"][c] for c in RATES_COLUMNS],
        "tiles": {("only" if t["tile"] is None else str(t["tile"])): [t[c] for c in RATES_COLUMNS] for t in e["tiles"]},
        "sum": ([e["sum"][c] for c in RATES_SUM_COLUMNS] if e["sum"] else None),
        "card": e["card"]})


def rates_of(owns: List[Dict[str, Any]], nights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The file's `rates`: one entry a night, from that night's own summary (owns[k]["rates"], the report's _rates over the night's records)."""
    out = []
    for k, own in enumerate(owns, 1):
        X = own["rates"]
        P = X["probe"]
        probe = None
        if P is not None:
            probe = {"images": P["images"],
                     "table": [OneLine({"image": t["image"], "op": t["op"], "format": t["format"],
                                        "alone": [t["alone"][c] for c in PROBE_COLUMNS] if t["alone"] else None,
                                        "together": [t["together"][c] for c in PROBE_COLUMNS] if t["together"] else None}) for t in P["table"]],
                     "refused": [OneLine({"image": r["image"], "op": r["op"], "format": r["format"], "refused": r["refused"]}) for r in P["refused"]],
                     "red": len(P["red"])}
        out.append({"n": k, "date": nights[k - 1]["date"], "seen": X["seen"], "used": X["used"], "left_out": X["left_out"],
                    "rows": [rate_row(e) for e in X["rows"]], "probe": probe})
    return {"unit": R.RATE_UNIT, "columns": RATES_COLUMNS, "sum_columns": RATES_SUM_COLUMNS, "probe_columns": PROBE_COLUMNS, "rule": RATES_RULE, "nights": out}


# ---------------------------------------------------------------------------
# the guards: nothing private, nothing a double cannot hold
# ---------------------------------------------------------------------------

def _strings(x: Any):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _strings(k)
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)


def _private(objs: List[Dict[str, Any]]) -> List[str]:
    """The text the records themselves carry that the output must not: the host name, the run's directory, every image path,
    and the user names in those paths."""
    found: List[str] = []
    for r in objs:
        if r.get("type") != "run_start":
            continue
        pool = [r.get("host"), r.get("out"), r.get("root")] + [d.get("path") for d in (r.get("images") or {}).values() if isinstance(d, dict)]
        pool += [a for a in (r.get("argv") or []) if isinstance(a, str) and ("/" in a or "\\" in a)]
        for s in pool:
            if isinstance(s, str) and len(s) >= 3:
                found.append(s)
        for s in _strings(r):
            found += [u for u in _USER.findall(s) if len(u) >= 3]
    return sorted(set(found))


def guard(out: Dict[str, Any], objs: List[Dict[str, Any]]) -> None:
    private = _private(objs)
    for s in _strings(out):
        for p in private:
            if p in s:
                raise Failed(f"private text in a published string: {s[:60]!r} holds {p[:40]!r}, which the records carry as a host, directory, path or user")
        if _PATHY.search(s) or _IPV4.search(s):
            raise Failed(f"a published string has the shape of a path or an IP address: {s[:80]!r}")
    stack = [out]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            stack += list(x.values())
        elif isinstance(x, list):
            stack += x
        elif isinstance(x, int) and not isinstance(x, bool) and abs(x) > JS_SAFE:
            raise Failed(f"the number {x} is past 2**53: the page reads numbers as doubles and would show another")
        elif isinstance(x, float) and not math.isfinite(x):
            raise Failed("a figure is not finite")


# ---------------------------------------------------------------------------
# the command line
# ---------------------------------------------------------------------------

def _inline(x: Any) -> bool:
    """Whether a dict or list goes on one line: it holds only scalars (and no long text), or it is short. A night's item map is
    one line, so a night adds tens of lines to the file, not hundreds."""
    if isinstance(x, OneLine):
        return True
    vals = list(x.values()) if isinstance(x, dict) else x
    if all(not isinstance(v, (dict, list)) for v in vals):
        return not any(isinstance(v, str) and len(v) > 100 for v in vals)
    return len(json.dumps(x, separators=(", ", ": "))) <= 420


def _emit(x: Any, ind: int = 0) -> str:
    if not isinstance(x, (dict, list)) or not x or _inline(x):
        return json.dumps(x, allow_nan=False, separators=(", ", ": "))
    pad = " " * (ind + 1)
    if isinstance(x, dict):
        return "{\n" + ",\n".join(f"{pad}{json.dumps(k)}: {_emit(v, ind + 1)}" for k, v in x.items()) + "\n" + " " * ind + "}"
    return "[\n" + ",\n".join(pad + _emit(v, ind + 1) for v in x) + "\n" + " " * ind + "]"


def dump(obj: Dict[str, Any]) -> str:
    return _emit(obj) + "\n"


def differences(a: Any, b: Any, path: str = "", out: Optional[List[str]] = None, limit: int = 60) -> List[str]:
    # the first `limit` differences, in the file's order (60 since parcel HXd: the groups of each class are fields a night moves, and a fourth night
    # made 43 differences, `totals.nights` the 33rd, where it had been inside the first 30)
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in list(a) + [k for k in b if k not in a]:
            if k not in a or k not in b:
                out.append(f"{path}.{k}: {'missing from the file' if k not in a else 'not derived'}")
            else:
                differences(a[k], b[k], f"{path}.{k}", out, limit)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            differences(x, y, f"{path}[{i}]", out, limit)
    elif a != b or type(a) is not type(b):
        out.append(f"{path or '.'}: file {json.dumps(a)[:60]}, derived {json.dumps(b)[:60]}"
                   if not isinstance(a, (list, dict)) and not isinstance(b, (list, dict)) else f"{path or '.'}: shape differs")
    return out


def repo_commit() -> Optional[str]:
    """git's HEAD in this file's repository, or None where git cannot say (the file then records null, not a guess)."""
    try:
        p = subprocess.run(["git", "-C", os.path.dirname(_HERE), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = p.stdout.strip()
    return sha if p.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="card_stress_progress.py", description="Reduce a long run's metrics.jsonl to the nightly progress page's data "
                                 "file (see this file's docstring for what each part means and the exit statuses).")
    ap.add_argument("run_dir", metavar="RUN_DIR", help="the run's directory: it holds metrics.jsonl")
    ap.add_argument("--out", metavar="FILE", default=None, help="write the data file here (default: standard output)")
    ap.add_argument("--check", metavar="FILE", default=None, help="re-derive FILE from RUN_DIR and compare, writing nothing")
    ap.add_argument("--commit", metavar="SHA|none", default=None, help="the commit to record as the one the file was made at "
                    "(default: git's HEAD in this file's repository, or null if git cannot say)")
    a = ap.parse_args(argv)
    me = "card_stress_progress"
    if a.check and a.out:
        ap.error("--check writes nothing: it does not take --out")
    try:
        objs, info = load(a.run_dir)
        if a.check:
            try:
                with open(a.check, "rb") as fh:
                    have = json.loads(fh.read().decode("utf-8"))
            except (OSError, ValueError) as e:
                raise Refused(f"{a.check} cannot be read as a data file: {type(e).__name__}: {e}")
            got = json.loads(dump(reduce_records(objs, info, None)))
            if not isinstance(have, dict):
                raise Refused(f"{a.check} is JSON but not an object")
            made = have.get("made")
            if not (isinstance(made, dict) and (made.get("commit") is None or re.fullmatch(r"[0-9a-f]{40}", str(made.get("commit"))))):
                raise Refused(f"{a.check} is not a data file: its made.commit is not 40 lowercase hex digits or null")
            have["made"] = got["made"] = None
            diff = differences(have, got)
            if diff:
                print(f"{me}: {a.check} is NOT what {a.run_dir} reduces to; first differences:", file=sys.stderr)
                for d in diff:
                    print(f"  {d}", file=sys.stderr)
                return 1
            print(f"{me}: {a.check} is what {a.run_dir} reduces to: {len(got['nights'])} nights, {info['sha256'][:12]} metrics.jsonl "
                  f"({got['source']['records']:,} records); the commit it was made at ({made.get('commit')}) is not compared")
            return 0
        commit = repo_commit() if a.commit is None else (None if a.commit == "none" else a.commit)
        if commit is not None and not re.fullmatch(r"[0-9a-f]{40}", commit):
            ap.error("--commit is 40 lowercase hex digits or none")
        text = dump(reduce_records(objs, info, commit))
    except Refused as e:
        print(f"{me}: {e}", file=sys.stderr)
        return 2
    except Exception as e:           # a bug, or the reducer's own check: nothing is written
        print(f"{me}: the reducer failed or refused its own check: {type(e).__name__}: {e}", file=sys.stderr)
        if not isinstance(e, Failed):
            traceback.print_exc()
        return 3
    if a.out is None:
        sys.stdout.write(text)
        return 0
    try:
        tmp = f"{a.out}.tmp{os.getpid()}"
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, a.out)
    except OSError as e:
        print(f"{me}: could not write {a.out}: {e}", file=sys.stderr)
        return 1
    d = json.loads(text)
    print(f"{me}: wrote {a.out}: {d['totals']['nights']} nights, {d['source']['records']:,} records, metrics sha256 {info['sha256']}; "
          f"newest night {d['newest']['date']}")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass
    sys.exit(main())
