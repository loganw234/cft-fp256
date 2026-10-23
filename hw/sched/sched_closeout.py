# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The close-out of a nightly window (parcel S4a): the lead's morning routine (docs/CARDDAY.md, "The morning after"; box_day_1023.sh's second step), done by the window job.

Logan, 2026-10-23: "Build it into the scheduler", and "Box prepares, lead pushes". When the driver of a window job has ended, WHATEVER the outcome and as long as the job started it
and its run directory is there, the job does five things, each its own PART with a `closeout_part` record (done, refused by name, skipped with its reason, or error), none hiding
another, and then the job ends with the driver's outcome, which no part changes:
  report     the clone's own report tool (`python3 -B <clone>/hw/card_stress_report.py RUN`, the clone that ran the night, so a fallback night is read by the fallback's tool): its text
             kept as `report-final.txt` and the run's report.txt written again by it, as the routine did;
  summary    the same run's `--json`, kept as `window-summary.json` (the study's "window summary from report --json");
  sums       the lead's copy list: the run's five files (metrics.jsonl, driver.log, status.txt, settings.json, report.txt, as the night ended) and the smoke's five, with the job's own
             records and logs, in the job's ONE SHA256SUMS (written when the job is sealed, from `sums-extra.json`, which this part writes: sched_state.write_sums);
  publish    the page's data commit prepared on a branch of the scheduler's own clone (sched_publish.py): never pushed, a dry job's never made;
  retention  sched_retention.py: what it would remove, what it removed, what it kept and why.
`status` shows each (window_info, format_window), and the end record carries `closeout`.
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback

import sched_publish as PUB
import sched_retention as RET
import sched_state as STATE
from sched_names import Refusal

RUN_FILES = ("metrics.jsonl", "driver.log", "status.txt", "settings.json", "report.txt")           # a driver directory's five files, the run's and the smoke's
REPORT, SUMMARY, SMOKE_RE = "report-final.txt", "window-summary.json", re.compile(r"\d\d-driver-quick\Z")
PARTS = ("report", "summary", "sums", "publish", "retention")


class Skip(Exception):
    """A part that does not apply, and why."""


def do_report(clone, python, run, jobdir, rec):
    tool = os.path.join(clone, "hw", "card_stress_report.py")
    if not os.path.isfile(tool):
        raise Refusal("report-failed", "hw/card_stress_report.py is not in the clone that ran the night")
    rc, out, err = PUB.run([python, "-B", tool, run, "--json", os.path.join(jobdir, SUMMARY)], clone, 900)
    rec.update(rc=rc, lines=len(out.splitlines()), tool="hw/card_stress_report.py of the clone that ran the night", clone=os.path.basename(os.path.normpath(clone)))
    if out:
        with open(os.path.join(jobdir, REPORT), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
        rec["file"] = REPORT
    if rc != 0:
        raise Refusal("report-failed", ("the report tool did not finish" if rc is None else f"the report tool exited with status {rc}") + f": {PUB.lines(err)}")


def epoch(ts) -> float:
    """A driver timestamp ('YYYY-MM-DD HH:MM:SS', the box's clock) as an epoch; infinity where it cannot be read, so that such a disagreement counts for the night rather than escapes it."""
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except (TypeError, ValueError, OverflowError):
        return float("inf")


def do_summary(jobdir, t0, rec):
    """The summary kept, and the driver's FINDINGS read out of it (S3a left the outcome as the driver's `run_end` and said this close-out reads them): the sweep's disagreements, this night's
    (those of legs that started no more than 60 s before the driver did, or after: the driver's stamps are to the second, and a leg of this night never starts before it) and the run's,
    and the run's failed legs. The outcome is not changed by them."""
    try:
        with open(os.path.join(jobdir, SUMMARY), "rb") as fh:
            data = fh.read()
        s = json.loads(data.decode("utf-8"))
        version = s["report_version"]
        if not isinstance(version, int):
            raise TypeError("report_version is not a number")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Refusal("summary-unreadable", f"{SUMMARY} is not a summary: {type(e).__name__}: {e}")
    dis = (s.get("sweep") or {}).get("disagreements") or []
    rec.update(file=SUMMARY, bytes=len(data), report_version=version, records=(s.get("input") or {}).get("records"), disagreements_this_night=len([d for d in dis if epoch(d.get("start")) >= t0 - 60]),
               disagreements_in_run=len(dis), failed_legs_in_run=(((s.get("totals") or {}).get("legs") or {}).get("by_status") or {}).get("fail"))


def do_sums(run, jobdir, share, rec):
    """The list of files the lead's copy is checked against: written as `sums-extra.json`, which sched_state.write_sums turns into lines of the job's SHA256SUMS when the job is sealed."""
    rows, missing = [], []

    def add(name, path):
        try:
            rows.append({"name": name, "sha256": STATE.sha256_file(path), "bytes": os.path.getsize(path)})
            return True
        except OSError:
            return False
    for n in RUN_FILES:
        if not add(os.path.join(run, n), os.path.join(run, n)):
            missing.append(n)
    smoke = [d for d in sorted(os.listdir(jobdir)) if SMOKE_RE.match(d) and os.path.isdir(os.path.join(jobdir, d))]
    smoke_files = [d + "/" + n for d in smoke for n in RUN_FILES if add(d + "/" + n, os.path.join(jobdir, d, n))]
    lost = [d + "/" + n for d in smoke for n in RUN_FILES if d + "/" + n not in smoke_files]                # a smoke the job ran that left one of its five unreadable or missing
    with open(os.path.join(jobdir, STATE.EXTRA), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"v": 1, "files": rows}, fh, indent=1)
        fh.write("\n")
    share["metrics_sha256"] = next((r["sha256"] for r in rows if r["name"] == os.path.join(run, "metrics.jsonl")), None)
    rec.update(file="SHA256SUMS", extra=STATE.EXTRA, run_dir=run, run_files=[r["name"] for r in rows if os.path.isabs(r["name"])], smoke_files=smoke_files, listed=len(rows),
               metrics_sha256=share["metrics_sha256"], note="the lines naming the run's files hold for the lead's copy of this night: the next night resumes that directory, and `check_sums` leaves them be")
    if missing or lost:
        what = [f"{', '.join(missing)} of the run in {run}"] * bool(missing) + [f"{', '.join(lost)} of the smoke in the job's directory"] * bool(lost)
        raise Refusal("sums-incomplete", f"cannot be read: {'; '.join(what)}: the list is written without {'it' if len(missing) + len(lost) == 1 else 'them'}")


def closeout(runner, spec, log, S, dry) -> dict:
    """Run the parts; returns what the end record carries: {"parts": {name: status or "refused:NAME"}, "data_commit": SHA or None}. Never raises for a part."""
    root, cfg, jobdir, run, share, parts, recs = runner.root, runner.cfg, os.path.dirname(log.path), spec["driver"]["out"], {}, {}, {}
    python, clone = cfg["runner"]["python"], S.ctx.clone if S.ctx else None
    t0 = next((r["t"] for r in STATE.read_records(log.path) if r.get("type") == "driver_started"), None)
    started = t0 is not None
    why_not = None if started and clone and os.path.isdir(run) else ("no driver was started this night (the job ended before it): there is no night to close out" if not started
                                                                      else "the run directory is not there")

    def part(name, fn, needs_night=True):
        rec = {}
        try:
            if needs_night and why_not:
                raise Skip(why_not)
            fn(rec)
            status = "done"
        except Skip as s:
            status, rec["why"] = "skipped", str(s)
        except Refusal as r:
            status, rec["refusal"], rec["why"] = "refused", r.name, r.why
        except Exception as e:                                           # a defect here, or a tool's surprise, ends THIS part, recorded: never the job or the service
            status, rec["error"], rec["traceback"] = "error", f"{type(e).__name__}: {e}", traceback.format_exc()[-1500:]
        log.append("closeout_part", part=name, status=status, **rec)
        parts[name], recs[name] = (f"refused:{rec['refusal']}" if status == "refused" else status), rec

    def publish(rec):
        if dry:
            raise Skip("the job is a dry run: its slices ran against stand-ins and the page shows the card's nights; nothing is fetched or prepared")
        PUB.prepare(root, cfg, run, share.get("metrics_sha256"), python, rec)
    part("report", lambda rec: do_report(clone, python, run, jobdir, rec))
    part("summary", lambda rec: do_summary(jobdir, t0, rec))
    part("sums", lambda rec: do_sums(run, jobdir, share, rec))
    part("publish", publish)
    part("retention", lambda rec: rec.update(RET.run(root, cfg, time.time(), log.job, apply=not dry)), needs_night=False)
    return {"parts": parts, "data_commit": recs["publish"].get("commit")}


def info(records: list) -> dict:
    """{part: its newest `closeout_part` record} out of a job's records, for `status`."""
    return {r["part"]: r for r in records if r.get("type") == "closeout_part"}


def lines(parts: dict) -> list:
    """`status`'s lines for a job's close-out: one a part, the data commit's fetch command under it."""
    if not parts:
        return []
    out = ["  close-out:"]
    for name in PARTS:
        r = parts.get(name)
        if r is None:
            continue
        what = {"report": lambda: f"{r.get('file')}, {r.get('lines')} lines, rc {r.get('rc')}, by the tool of clone {str(r.get('clone'))[:12]}", "summary": lambda: f"{r.get('file')}, report_version {r.get('report_version')}, DISAGREEMENTS {r.get('disagreements_this_night')} this night ({r.get('disagreements_in_run')} in the run)",
                "sums": lambda: f"{r.get('listed')} files of the run and the smoke listed (the job's own are listed when it is sealed), metrics.jsonl {str(r.get('metrics_sha256'))[:12]}",
                "publish": lambda: f"night {r.get('night')} ({r.get('date')}), commit {str(r.get('commit'))[:12]} on {r.get('branch')}, parent {str(r.get('parent'))[:12]}",
                "retention": lambda: f"{r.get('clones', {}).get('removed_n')} clone(s) and {r.get('logs', {}).get('removed_n')} log(s) removed, would remove {r.get('clones', {}).get('would_remove_n')} and "
                                     f"{r.get('logs', {}).get('would_remove_n')}, kept {len(r.get('clones', {}).get('kept', []))} clone(s) ({r.get('mode')})"}[name]
        st = r["status"]
        out.append(f"    {name}: " + (f"REFUSED {r['refusal']}: {r.get('why')}" if st == "refused" else f"ERROR {r.get('error')}" if st == "error" else f"skipped: {r.get('why')}" if st == "skipped" else f"done: {what()}"))
    pub = parts.get("publish")
    if pub and pub["status"] == "done":
        out.append(f"    for the lead, from the desktop: {pub.get('fetch')}" + (f"   ({pub['fetch_note']})" if pub.get("fetch_note") else ""))
    return out
