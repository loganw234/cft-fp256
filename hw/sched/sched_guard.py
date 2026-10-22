# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The guard: who else uses the card (parcel S2).

What a card user IS belongs to the driver (hw/card_stress.py card_user and find_card_users, imported by sched_driver, not
copied): a program handed an image, acceptance.py or seq_check.py on a device that is not software, a soak with
CFT_SOAK_ARTIFACT in its environment, xbutil or xrt-smi running a subcommand that touches the card, an idle `cft-serve
--artifact IMAGE`. The process that asks, everything it started and its ancestors are excluded by ancestry, so a job's own
steps and the shell that launched the service are never "foreign". Used BEHIND the card's lock (sched_run.serve takes it before
a job is claimed): the lock keeps the scheduler's own jobs apart, and this finds the users that never took it. It detects and
never kills.

A card has a `kind`, and what a card user is differs by kind: KIND_SCANS has one entry per kind the configuration admits
(a test holds the two equal), and `xrt` is the only one so far. A job at its start asks with wait_max_s 0 and is refused at
once, as the driver's start is; between steps it waits, as the driver's guard does between legs, recording `guard_wait` once
and `guard_clear` when the card is free, and refuses `card-busy-foreign` after the limit. It never stops or signals what it finds.
"""
from __future__ import annotations

import time

from sched_driver import CS
from sched_names import Refusal


class Stopped(Exception):
    """A stop was requested while the guard waited for the card: the job ends cancelled, not refused."""


def _scan_xrt(exclude_pids) -> tuple:
    return CS.find_card_users(exclude_pids=set(exclude_pids))


KIND_SCANS = {"xrt": _scan_xrt}


def scan(kind: str, exclude_pids=()) -> tuple:
    """(foreign card users, verify/run.sh runs beside) for a card of this kind."""
    return KIND_SCANS[kind](exclude_pids)


def hold_until_clear(log, kind: str, wait_max_s: float, poll_s: float, stop=None, sleep=time.sleep, clock=time.monotonic) -> None:
    """Return when no foreign process uses the card; else wait up to wait_max_s (0: do not wait) and refuse `card-busy-foreign`."""
    t0, announced, seen = clock(), False, set()
    while True:
        users, beside = scan(kind)
        fresh = [b for b in beside if b["pid"] not in seen]
        if fresh:
            seen.update(b["pid"] for b in fresh)
            log.append("beside", note="verify/run.sh uses no card: allowed, and recorded", runs=fresh)
        if not users:
            if announced:
                log.append("guard_clear", waited_s=round(clock() - t0, 1))
            return
        desc = "; ".join(f"pid {u['pid']} {u['why']}" for u in users)
        if clock() - t0 >= wait_max_s:
            log.append("guard_refused", users=users, waited_s=round(clock() - t0, 1))
            raise Refusal("card-busy-foreign", f"{desc}" + (f" (still in use after {wait_max_s:.0f} s)" if wait_max_s else ""))
        if not announced:
            log.append("guard_wait", users=users)
            announced = True
        if stop is not None and stop():
            raise Stopped()
        sleep(poll_s)
