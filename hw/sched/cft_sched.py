#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft-sched: the card scheduler's command (docs/studies/SCHED-A-card-scheduler.md; this is its first parcel, S1).

    cft-sched [--root DIR] init                  write config.json (the defaults) and the layout; the only verb that makes a root
    cft-sched [--root DIR] submit FILE|-         a job spec (JSON): queued, or refused by name; either way it has an id and a record
    cft-sched [--root DIR] list [--all] [--json] the queue, what runs, and the last ten that ended (all of them with --all)
    cft-sched [--root DIR] status [ID] [--json]  each card's state, the running job, the queue, the last outcome; one job with ID
    cft-sched [--root DIR] cancel ID             a queued job leaves the queue; a running one stops at its next safe point
    cft-sched [--root DIR] hold CARD [--why T]   no new claims on the card; what runs is not touched
    cft-sched [--root DIR] release CARD
    cft-sched [--root DIR] serve [--drain] [--poll S] [--max-jobs N] [--no-locks]

The root is --root or $CFT_SCHED_ROOT, outside every git checkout (on the box: /data/cft-sched). In this parcel `serve`
runs the FAKE runner, which touches no card. A refusal prints `refused: NAME: why` on stderr and exits 2; docs/studies
and hw/sched/sched_names.py hold the table. Only the box user submits, over ssh: there is no listener and no socket.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sched_config as C          # noqa: E402
import sched_run as R             # noqa: E402
import sched_state as S           # noqa: E402
from sched_names import Refusal   # noqa: E402


def cmd_init(a, root):
    path = os.path.join(root, "config.json")
    try:
        with open(path, "xb") as fh:
            fh.write(C.default_config_text().encode())
    except FileExistsError:
        raise Refusal("config-exists", f"{path} exists: edit it, `init` does not overwrite")
    C.ensure_layout(root, C.load_config(root))
    print(f"initialized {root}: config.json holds the defaults and one card, u50-0 (xrt); edit it for this machine")
    return 0


def cmd_submit(a, root):
    cfg = C.load_config(root)
    try:
        if a.file == "-":
            raw = sys.stdin.buffer.read()
        else:
            with open(a.file, "rb") as fh:
                raw = fh.read()
    except OSError as e:
        raise SystemExit(f"cft-sched: cannot read {a.file}: {e}")
    jid, refusal = S.submit(root, cfg, raw, R.FAKE_REGISTRY)
    if refusal:
        print(f"refused {jid}: {refusal.name}: {refusal.why}", file=sys.stderr)
        return 2
    print(f"submitted {jid}")
    return 0


def cmd_list(a, root):
    C.load_config(root)
    v = R.list_jobs(root, a.all)
    print(json.dumps(v, sort_keys=True) if a.json else R.format_list(v))
    return 0


def cmd_status(a, root):
    cfg = C.load_config(root)
    if a.id:
        jid = S.parse_job_id(a.id)
        for where in ("queue", "running", "jobs"):
            if os.path.isdir(os.path.join(root, where, jid)):
                v = R.job_view(root, where, jid)
                v["sums_problems"] = S.check_sums(os.path.join(root, where, jid)) if where == "jobs" else None
                print(json.dumps(v, sort_keys=True) if a.json else
                      f"{jid}: {where}, {v['name']!r} on {v['card']}, {v['records']} records, outcome {v['outcome']}"
                      + (f" ({v['refusal']})" if v["refusal"] else "") + (f", stop requested by {v['stop'].get('by')}" if v["stop"] else ""))
                return 0
        raise Refusal("job-unknown", f"no job {jid}")
    st = R.gather_status(root, cfg)
    print(json.dumps(st, sort_keys=True) if a.json else R.format_status(st))
    return 0


def cmd_cancel(a, root):
    C.load_config(root)
    how = S.cancel(root, a.id, S.user())
    print({"dequeued": f"{a.id}: removed from the queue; outcome cancelled",
           "stop-requested": f"{a.id}: stop requested; it ends at its next safe point",
           "stop-already-requested": f"{a.id}: a stop was already requested"}[how])
    return 0


def cmd_hold(a, root):
    S.hold(root, C.load_config(root), a.card, S.user(), a.why)
    print(f"{a.card}: held; no new claims, what runs is not touched")
    return 0


def cmd_release(a, root):
    S.release(root, C.load_config(root), a.card, S.user())
    print(f"{a.card}: released")
    return 0


def cmd_serve(a, root):
    cfg = C.load_config(root)
    C.ensure_layout(root, cfg)
    R.serve(root, cfg, R.FakeRunner(), poll=a.poll, drain=a.drain, max_jobs=a.max_jobs, skip_locks=a.no_locks)
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cft-sched", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", help=f"the state root (default ${C.ENV_ROOT})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("init", cmd_init), ("submit", cmd_submit), ("list", cmd_list), ("status", cmd_status), ("cancel", cmd_cancel),
                     ("hold", cmd_hold), ("release", cmd_release), ("serve", cmd_serve)):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        if name == "submit":
            p.add_argument("file", help="a spec file, or - for standard input")
        if name in ("list", "status"):
            p.add_argument("--json", action="store_true")
        if name == "list":
            p.add_argument("--all", action="store_true", help="every job that ended, not the last ten")
        if name == "status":
            p.add_argument("id", nargs="?")
        if name == "cancel":
            p.add_argument("id")
        if name in ("hold", "release"):
            p.add_argument("card")
        if name == "hold":
            p.add_argument("--why", default="", help="what the hold is for, shown by status")
        if name == "serve":
            p.add_argument("--drain", action="store_true", help="run what is eligible, then exit")
            p.add_argument("--poll", type=float, default=1.0, help="seconds between looks at the queue (default 1)")
            p.add_argument("--max-jobs", type=int, default=None)
            p.add_argument("--no-locks", action="store_true", help="take no locks, and say so in the records (for a platform without flock)")
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    root = None
    try:
        root = C.check_root(C.resolve_root(a.root), create=a.cmd == "init")
        return a.fn(a, root)
    except Refusal as r:
        print(f"refused: {r.name}: {r.why}", file=sys.stderr)
        if root:
            S.note_refusal(root, r, a.cmd, getattr(a, "card", None))
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
