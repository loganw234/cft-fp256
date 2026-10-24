# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Retention (parcel S4a), run by the scheduler at the end of every window job: Logan's answer 11, "twice as thorough" as the study suggested - clones 14 days, passing logs 360,
every record kept, and the disk floor (config.json's floors) untouched: it is READ for the record and nothing here acts on it or on any other configuration.

WHAT IT MAY REMOVE, and nothing else: (1) a clone the scheduler made, `clones/<full SHA>` in the state root, that no job has used for `clone_days` (its age is counted from the newest
record of a job that names it, else its directory's own time: a clone the nightly reuses is in use), is not named by a queued or running job, is a real directory (no link) with a
.git, and whose real path is that very name under the real `clones/`; its `verify/state` (a gate run in it leaves the stage logs there) is first COPIED to
`archive/clones/<SHA>.<time>/verify-state` and the copy counted, and a clone whose archive cannot be made is kept, with the reason; (2) the step log `NN-STEP.log` of a leg that PASSED, in the
directory of a job that ended `passing_log_days` ago: the log is replaced by `NN-STEP.log.removed` (its sha256 and size, when and why), and the job's sums are written again, so the
job still checks. A failed step's log is kept, and so is every record: `record_days` is read and reported, and a number there is NOT acted on. Anything else in the state root, and
anything outside it, is never a candidate: the exact paths are chosen from the names above and each removal is by its exact path.
THE RECORD is `run()`'s return: what it would remove, what it removed, what it kept and why. A dry job's retention (`apply=False`) removes nothing and says so.
"""
from __future__ import annotations

import json
import os
import re
import shutil

import sched_code as CODE
import sched_state as STATE

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
LOG_RE = re.compile(r"\d\d-[A-Za-z0-9._-]+\.log\Z")
DAY = 86400.0
CAP = 40                                   # entries of a list the record names one by one; the counts are whole


def tree_facts(d: str) -> tuple:
    """(files, bytes) under d, links not followed."""
    n = b = 0
    for dp, _dn, fn in os.walk(d):
        for f in fn:
            n += 1
            b += os.lstat(os.path.join(dp, f)).st_size
    return n, b


def named(root: str) -> tuple:
    """({sha: epoch of the newest record of a job that used clones/sha}, {sha named by a queued or running job's spec})."""
    use, busy = {}, set()
    for where in ("jobs", "running", "queue"):
        base = os.path.join(root, where)
        for jid in os.listdir(base) if os.path.isdir(base) else []:
            if not STATE.ID_RE.match(jid):
                continue
            for r in STATE.read_records(os.path.join(base, jid, "job.jsonl")):
                if r.get("type") == "code" and isinstance(r.get("clone"), str):
                    sha = r["clone"].rsplit("/", 1)[-1]
                    use[sha] = max(use.get(sha, 0.0), float(r.get("t") or 0))
            if where != "jobs":
                try:
                    with open(os.path.join(base, jid, "spec.json"), "rb") as fh:
                        busy.add(((json.loads(fh.read().decode()).get("code") or {}).get("commit")))
                except (OSError, ValueError):
                    pass
    return use, busy


def plan_clones(root: str, days: float, now: float) -> tuple:
    """([clones to remove], [{path, why} kept]) for clones/."""
    base = os.path.join(root, "clones")
    real_base, use, busy = os.path.realpath(base), *named(root)
    go, keep = [], []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        p, why = os.path.join(base, name), None
        if not SHA_RE.match(name):
            why = "not a clone the scheduler made: its name is not a full SHA"
        elif os.path.islink(p) or not os.path.isdir(os.path.join(p, ".git")) or os.path.dirname(os.path.realpath(p)) != real_base:
            why = "not a clone the scheduler made: a link, or no .git, or its real path is not clones/" + name
        elif name in busy:
            why = "named by a queued or running job"
        else:
            last = use.get(name) or os.path.getmtime(p)
            if (now - last) / DAY < days:
                why = f"used {(now - last) / DAY:.1f} days ago, under the {days:g}-day retention"
        if why:
            keep.append({"path": f"clones/{name}", "why": why})
        else:
            go.append({"path": f"clones/{name}", "sha": name, "age_days": round((now - (use.get(name) or os.path.getmtime(p))) / DAY, 1)})
    return go, keep


def remove_clone(root: str, c: dict, now: float, by: str) -> dict:
    """Archive the clone's verify/state, count the copy, then remove the clone by its exact path. {"removed": True, ...} or {"removed": False, "why": ...} (kept)."""
    src = os.path.join(root, "clones", c["sha"])
    dest = os.path.join(root, "archive", "clones", f"{c['sha']}.{int(now)}")           # one directory a removal: a clone made again and removed again is archived again
    vs = os.path.join(src, "verify", "state")
    facts = {"sha": c["sha"], "age_days": c["age_days"], "removed_t": round(now, 3), "by": by, "verify_state": os.path.isdir(vs)}
    if os.path.exists(dest):
        return {"removed": False, "path": c["path"], "why": f"kept: archive/clones/{os.path.basename(dest)} exists already (not written over)"}
    try:
        os.makedirs(dest)
        if facts["verify_state"]:
            shutil.copytree(vs, os.path.join(dest, "verify-state"), symlinks=True)
            if tree_facts(vs) != tree_facts(os.path.join(dest, "verify-state")):
                raise OSError("the copy does not hold the files and bytes of the original")
            facts["files"], facts["bytes"] = tree_facts(vs)
        with open(os.path.join(dest, "facts.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(facts, fh, indent=1)
            fh.write("\n")
    except OSError as e:
        if os.path.isdir(dest):
            CODE.remove_tree(dest)                                                  # the partial archive this call made, by its exact path
        return {"removed": False, "path": c["path"], "why": f"kept: its verify/state could not be archived ({e})"}
    try:
        CODE.remove_tree(src)
    except OSError as e:                                                            # the archive stays: it holds what the clone held
        return {"removed": False, "path": c["path"], "why": f"kept: it could not be removed ({e})"}
    return {"removed": True, "path": c["path"], "archive": f"archive/clones/{os.path.basename(dest)}", "verify_state": facts["verify_state"], "age_days": c["age_days"]}


def plan_logs(root: str, days: float, now: float) -> tuple:
    """([(job directory, [log names], end time)] to remove, {why: number of logs kept})."""
    base, go, kept = os.path.join(root, "jobs"), [], {}
    bump = lambda w, n=1: kept.__setitem__(w, kept.get(w, 0) + n)
    for jid in sorted((n for n in os.listdir(base) if STATE.ID_RE.match(n)), key=STATE.id_key) if os.path.isdir(base) else []:
        d = os.path.join(base, jid)
        rs = STATE.read_records(os.path.join(d, "job.jsonl"))
        logs = [n for n in os.listdir(d) if LOG_RE.match(n) and os.path.isfile(os.path.join(d, n))]
        if not rs or rs[-1].get("type") != "ended":
            bump("no end record: the job is not sealed", len(logs))
            continue
        passing = {r["log"] for r in rs if r.get("type") == "leg" and r.get("status") == "pass" and r.get("log_kept") == "whole" and isinstance(r.get("log"), str)}
        old = (now - float(rs[-1].get("t") or now)) / DAY >= days
        bump("a step that did not pass: its log is kept", len([n for n in logs if n not in passing]))
        go_here = [n for n in logs if n in passing and old]
        bump(f"a passing log under {days:g} days old", len([n for n in logs if n in passing and not old]))
        if go_here:
            go.append((d, go_here, float(rs[-1]["t"])))
    return go, kept


def remove_logs(d: str, names: list, now: float, by: str, days: float) -> list:
    """Replace each log with its `.removed` note and write the job's sums again. Returns [{name, sha256, bytes}]."""
    out = []
    for n in names:
        p = os.path.join(d, n)
        note = {"v": 1, "log": n, "sha256": STATE.sha256_file(p), "bytes": os.path.getsize(p), "removed_t": round(now, 3), "by": by, "why": f"a passing step's log, kept {days:g} days"}
        with open(p + ".removed", "w", encoding="utf-8", newline="\n") as fh:
            json.dump(note, fh, indent=1)
            fh.write("\n")
        os.unlink(p)
        out.append({k: note[k] for k in ("log", "sha256", "bytes")})
    STATE.write_sums(d)
    return out


def run(root: str, cfg: dict, now: float, by: str, apply: bool = True) -> dict:
    """The retention, planned and (apply) done: the record of what it would remove, what it removed, what it kept and why."""
    pol, floor = cfg["retention"], cfg["floors"]["disk_free_gb"]
    go, keep = plan_clones(root, pol["clone_days"], now)
    logs, kept_logs = plan_logs(root, pol["passing_log_days"], now)
    res = [remove_clone(root, c, now, by) for c in go] if apply else []
    done_logs = []
    for d, names, _t in logs if apply else []:
        done_logs += [dict(job=os.path.basename(d), **x) for x in remove_logs(d, names, now, by, pol["passing_log_days"])]
    n_would = sum(len(names) for _d, names, _t in logs)
    jobs = len([n for n in os.listdir(os.path.join(root, "jobs")) if STATE.ID_RE.match(n)]) if os.path.isdir(os.path.join(root, "jobs")) else 0
    return {"mode": "applied" if apply else "PLAN ONLY: the job is a dry run, and nothing was removed",
            "policy": {"clone_days": pol["clone_days"], "passing_log_days": pol["passing_log_days"], "record_days": pol["record_days"]},
            "clones": {"would_remove": [c["path"] for c in go][:CAP], "would_remove_n": len(go), "removed": [r for r in res if r["removed"]][:CAP],
                       "removed_n": sum(r["removed"] for r in res), "kept": (keep + [{"path": r["path"], "why": r["why"]} for r in res if not r["removed"]])[:CAP]},
            "logs": {"would_remove_n": n_would, "removed_n": len(done_logs), "removed": done_logs[:CAP], "kept": kept_logs},
            "records": {"kept": jobs, "why": "every record is kept" + (f"; record_days is {pol['record_days']} in config.json and is NOT acted on: this retention never removes a record" if pol["record_days"] is not None else "")},
            "disk_floor_gb": floor, "disk_floor": "read and reported; nothing here acts on it or changes it"}
