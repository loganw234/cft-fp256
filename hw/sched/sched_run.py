# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The service loop, the fake runner, and the views `status` and `list` print.

The real runners are parcels S2 (staged steps: sched_staged.py) and S3a (windows: sched_window.py, which also runs staged jobs); S1's loop was written against the FAKE runner, which
touches no card and says so in every record it writes. A real runner's end record may say otherwise (`card_touched`). The loop's one rule about the card is the order of
three things: the service holds the root's lock for its life; for each card it takes the card's lock BEFORE it
claims a job and drops it AFTER the job's record is sealed and moved, so the lock is held for exactly a job's run;
and a hold is looked at before and again under that lock.
"""
from __future__ import annotations

import json
import os
import socket
import time

import sched_closeout as CO
import sched_window as WD
from sched_names import Refusal
from sched_state import (HAVE_FLOCK, ID_RE, Lock, Log, card_log, claim_next, finish, hold_info, id_key, lock_held, queue_entries,
                         read_records, recover, stop_info)

VERSION = "1"
FAKE_REGISTRY = {"sleep": {"seconds": "number"}, "ignore-stop": {"seconds": "number"},
                 "fail": {"reason": "str"}, "find": {"count": "pos"}}


class StopWatch:
    """Looks for running/ID/STOP at a safe point, and records the first sighting, once."""

    def __init__(self, root: str, jid: str, log: Log):
        self.root, self.jid, self.log, self.seen = root, jid, log, False

    def requested(self) -> bool:
        info = stop_info(self.root, self.jid)
        if info is None:
            return False
        if not self.seen:
            self.seen = True
            self.log.append("stop_requested", by=info.get("by"), requested_t=info.get("t"))
        return True


class FakeRunner:
    """S1's stand-in for the real runners. A step is atomic: it runs to its end, and a stop is looked at only at a safe
    point, the start of the job and the end of each step but one, as the driver looks between legs and never in the middle
    of one. `sleep` sleeps; `fail` fails (the steps after it are recorded `skipped`); `find` passes and reports a finding;
    `ignore-stop` sleeps and its end is NOT a safe point: no stop is looked at there, and the next step's end is the next one (the
    legs of one wave have none between them)."""
    name = "fake"
    registry = FAKE_REGISTRY

    def run(self, spec: dict, log: Log, stop: StopWatch, sleep=time.sleep) -> tuple:
        failed = stopped = False
        findings = ran = 0
        skip, at_safe_point = None, True                   # the start of a job is a safe point
        for i, st in enumerate(spec["steps"]):
            kind = st["type"]
            if not skip and at_safe_point and stop.requested():
                skip = "a stop was requested"
            if skip:
                log.append("step", index=i, step=kind, status="skipped", reason=skip)
                stopped = stopped or skip == "a stop was requested"
                continue
            t0 = time.monotonic()
            status, n = "pass", 0
            if kind in ("sleep", "ignore-stop"):
                sleep(st.get("seconds", 0))
            elif kind == "fail":
                status = "failed"
            elif kind == "find":
                n = st.get("count", 1)
                findings += n
            ran += 1
            at_safe_point = kind != "ignore-stop"
            log.append("step", index=i, step=kind, status=status, elapsed_s=round(time.monotonic() - t0, 3), findings=n,
                       safe_point=at_safe_point, **({"reason": st["reason"]} if "reason" in st else {}))
            if status == "failed":
                failed, skip = True, "an earlier step failed"
        outcome = "failed" if failed else "cancelled" if stopped else "done-with-findings" if findings else "done"
        return outcome, {"findings": findings, "steps_ran": ran, "steps_total": len(spec["steps"])}


def run_claimed(root: str, jid: str, spec: dict, log: Log, runner) -> str:
    log.append("started", runner=runner.name, card_touched=False, name=spec["name"], kind=spec["kind"])
    stop = StopWatch(root, jid, log)
    outcome, fields = runner.run(spec, log, stop)
    stop.requested()                              # a stop that came after the last safe point is still recorded
    finish(root, jid, log, outcome, **{"runner": runner.name, "card_touched": False, **fields})      # a real runner says whether it touched the card
    return outcome


def serve(root: str, cfg: dict, runner, poll: float = 1.0, drain: bool = False, max_jobs: int | None = None,
          skip_locks: bool = False, out=None) -> int:
    """The loop. One service per root (the root's lock); one job at a time per card (the card's lock)."""
    out = out or (lambda s: print(s, flush=True))
    if skip_locks and HAVE_FLOCK:
        raise Refusal("locks-required", "this platform has flock(2): run with the locks")
    svc = Lock(os.path.join(root, "lock"), skip=skip_locks)
    if not svc.acquire(tries=3, delay=0.1):
        raise Refusal("lock-held", f"another service holds {os.path.join(root, 'lock')}")
    try:
        svc.write_info(pid=os.getpid(), host=socket.gethostname(), since=round(time.time(), 3), runner=runner.name)
        locks = "skipped" if skip_locks else "flock"
        out(f"serve: runner {runner.name}, locks {locks.upper() if skip_locks else locks}, cards {', '.join(c['id'] for c in cfg['cards'])}")
        for c in cfg["cards"]:
            card_log(root, c["id"]).append("service_start", pid=os.getpid(), runner=runner.name, locks=locks, version=VERSION,
                                           card_kind=c["kind"], card_touched=False)
        recover(root, out)
        n = 0
        while True:
            worked = False
            for c in cfg["cards"]:
                cid = c["id"]
                if hold_info(root, cid) is not None:
                    continue
                lk = Lock(os.path.join(root, "cards", cid, "CARDLOCK"), skip=skip_locks)
                if not lk.acquire():
                    continue                      # something holds the card: a probe, or a user we do not own
                try:
                    if hold_info(root, cid) is not None:
                        continue                  # a hold made since the look above
                    got = claim_next(root, cfg, cid, time.time(), runner.registry)
                    if got:
                        jid, spec, log = got
                        out(f"serve: {jid} claimed on {cid}: {spec['name']}")
                        out(f"serve: {jid} ended: {run_claimed(root, jid, spec, log, runner)}")
                        n += 1
                        worked = True
                finally:
                    lk.release()
            if max_jobs is not None and n >= max_jobs:
                break
            if not worked:
                if drain:
                    break
                time.sleep(poll)
        return n
    finally:
        svc.release()


# ---------------------------------------------------------------------------------------- the views

def _ids(root: str, where: str) -> list:
    return sorted((n for n in os.listdir(os.path.join(root, where)) if ID_RE.match(n)), key=id_key)


def job_view(root: str, where: str, jid: str) -> dict:
    recs = read_records(os.path.join(root, where, jid, "job.jsonl"))
    sub = next((r for r in recs if r.get("type") == "submitted"), {})
    end = recs[-1] if recs and recs[-1].get("type") == "ended" else None
    return {"id": jid, "where": where, "name": sub.get("name"), "kind": sub.get("kind"), "priority": sub.get("priority"),
            "card": recs[-1].get("card") if recs else None, "outcome": end.get("outcome") if end else None,
            "refusal": end.get("refusal") if end else None, "t": (end or (recs[-1] if recs else {})).get("t"),
            "records": len(recs), "stop": stop_info(root, jid) if where == "running" else None}


def list_jobs(root: str, everything: bool = False) -> dict:
    queued =[job_view(root, "queue", j) for j, _ in queue_entries(root)]
    done = _ids(root, "jobs")
    return {"queued": queued, "running": [job_view(root, "running", j) for j in _ids(root, "running")],
            "finished": [job_view(root, "jobs", j) for j in (done if everything else done[-10:])]}


def gather_status(root: str, cfg: dict) -> dict:
    held = lock_held(os.path.join(root, "lock"))
    info = None
    if held:
        try:
            with open(os.path.join(root, "lock"), "rb") as fh:
                info = json.loads(fh.read().decode() or "null")
        except (OSError, ValueError):
            info = None
    jobs = list_jobs(root)
    cards = []
    for c in cfg["cards"]:
        cid = c["id"]
        mine = [j for j in jobs["running"] if j["card"] == cid]
        h = hold_info(root, cid)
        lh = lock_held(os.path.join(root, "cards", cid, "CARDLOCK"))     # True: held; False: free; None: cannot tell
        # orphaned: a job sits in running/ and nobody holds the lock; locked: somebody holds it and no job of ours is there
        cards.append({"id": cid, "kind": c["kind"], "state": "orphaned" if mine and lh is False else "held" if h else "busy" if mine else "locked" if lh else "ready",
                      "running": mine[0] if mine else None, "hold": h,
                      "queued": sum(1 for j in jobs["queued"] if j["card"] in (cid, "any"))})
    recent = [job_view(root, "jobs", j) for j in _ids(root, "jobs")[-20:]]
    last = max(recent, key=lambda j: j["t"] or 0, default=None)
    ref = read_records(os.path.join(root, "refusals.jsonl"))
    wins = [dict(WD.window_info(root, w, j["id"], cfg), id=j["id"], where=w) for w, js in (("running", jobs["running"]), ("queue", jobs["queued"])) for j in js if j["kind"] == "window"]
    lw = next((j for j in reversed(recent) if j["kind"] == "window"), None)             # the newest window job that ended: its close-out is what the morning reads (parcel S4a)
    return {"root": root, "service": {"running": held, "info": info}, "locks": "flock" if held is not None else "unavailable",
            "cards": cards, "queue": jobs["queued"], "windows": wins, "last": last, "last_refusal": ref[-1] if ref else None,
            "last_window": lw and {"id": lw["id"], "outcome": lw["outcome"], "closeout": CO.info(read_records(os.path.join(root, "jobs", lw["id"], "job.jsonl")))}}


def _when(t) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if isinstance(t, (int, float)) else "?"


def format_status(st: dict) -> str:
    s = st["service"]
    lines = [f"cft-sched status, root {st['root']}",
             "service : " + ("running, pid %s since %s" % ((s["info"] or {}).get("pid"), _when((s["info"] or {}).get("since")))
                             if s["running"] else "not running" if s["running"] is False else "unknown (no flock on this platform)"),
             f"locks   : {st['locks']}"]
    for c in st["cards"]:
        r = c["running"]
        lines.append(f"card {c['id']} ({c['kind']}): {c['state']}"
                     + (f", running {r['id']} {r['name']!r} (priority {r['priority']})" + (f", stop requested by {r['stop'].get('by')}" if r["stop"] else "")
                        if r else "") + f", {c['queued']} queued")
        if c["hold"]:
            lines.append(f"    held by {c['hold'].get('by')} since {_when(c['hold'].get('t'))}: {c['hold'].get('why')}")
    lines.append(f"queue   : {len(st['queue'])} queued")
    lines += [f"    {j['id']}  priority {j['priority']}  {j['card']}  {j['name']!r}" for j in st["queue"]]
    for w in st.get("windows", []):
        lines += [f"window  : {w['id']} ({w['where']})"] + WD.format_window(w)
    lw = st.get("last_window")
    if lw and lw["closeout"]:
        lines += [f"window  : {lw['id']} (ended {lw['outcome']})"] + CO.lines(lw["closeout"])
    la = st["last"]
    lines.append("last    : " + (f"{la['id']} {la['outcome']}" + (f" ({la['refusal']})" if la["refusal"] else "") + f" on {la['card']} at {_when(la['t'])}"
                                 if la else "no job has ended"))
    lr = st["last_refusal"]
    if lr:
        lines.append(f"refusal : last {lr.get('name')} at {_when(lr.get('t'))}: {lr.get('why')}")
    return "\n".join(lines)


def format_list(v: dict) -> str:
    dash = lambda x: "-" if x is None else x
    rows = [f"{j['id']}  {w:8}  priority {dash(j['priority'])}  {dash(j['card'])}  {dash(j['name'])!r}"
            + (f"  {j['outcome']}" if j["outcome"] else "") + (f" ({j['refusal']})" if j["refusal"] else "")
            for w in ("queued", "running", "finished") for j in v[w]]
    return "\n".join(rows) or "no jobs"
