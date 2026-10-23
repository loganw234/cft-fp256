# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The calendar (parcel S3a): a window is a start and an end of the day in the box's zone, every night or on stated dates.

config.json's `windows` holds the zone (`local`, the machine's own, or a name such as America/Phoenix) and a list of
{name, start, end[, dates]}: start and end are HH:MM or HH:MM:SS; an end that is not after the start is the next morning's; `dates`,
when present, are the dates a window STARTS on (YYYY-MM-DD) and it has no other. An occurrence's two ends are each read as a wall-clock
time of its own date in the zone and turned into an epoch there, so the length is the difference of the epochs, not of the clock
faces: the night the clocks go back is one hour longer than the window's face (15 hours for 18:00 to 08:00) and the night they go
forward one hour shorter (13). A start or end that falls in the hour the clocks skip, or repeat, is read by PEP 495's first-fold rule
(zoneinfo's, and the C library's mktime for `local`): a limit, stated, not handled. `state` answers for one instant: the occurrence
open (`open`), else the next to open (`waiting`), else the last there was (`closed`: no occurrence is left, which only a window with
`dates` can come to). An unknown window is None; naming it is `window-bad`'s to say (sched_spec.validate).
"""
from __future__ import annotations

import datetime as dt
import time


def zone_of(name: str):
    """The zone's tzinfo, or None for `local` (the C library's, through time.mktime)."""
    if name == "local":
        return None
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def zone_problem(name: str):
    """None when the zone can be used here, else why not (config.json is refused `config-form` with it)."""
    try:
        zone_of(name)
    except Exception as e:                          # ZoneInfoNotFoundError (a KeyError), ValueError, ImportError: no database on this platform
        return f"{name!r} is not a zone this machine's time zone database holds ({type(e).__name__})"
    return None


def hms(text: str) -> tuple:
    p = [int(x) for x in text.split(":")]
    return p[0], p[1], p[2] if len(p) > 2 else 0


def wall(zone, day: dt.date, t: tuple) -> float:
    """The epoch of a wall-clock time on a date in the zone."""
    if zone is None:
        return time.mktime((day.year, day.month, day.day, t[0], t[1], t[2], 0, 0, -1))
    return dt.datetime(day.year, day.month, day.day, t[0], t[1], t[2], tzinfo=zone).timestamp()


def occurrence(win: dict, zone, day: dt.date) -> tuple:
    """(opens, closes) as epochs of the occurrence that starts on `day`."""
    a, b = hms(win["start"]), hms(win["end"])
    return wall(zone, day, a), wall(zone, day if b > a else day + dt.timedelta(days=1), b)


def state(cfg: dict, name: str, now: float):
    """None (no such window), or {name, zone, state: open|waiting|closed, opens, closes, length_s} for the occurrence that is open at
    `now`, else the next to open, else the last."""
    win = next((w for w in cfg["windows"]["list"] if w["name"] == name), None)
    if win is None:
        return None
    zname = cfg["windows"]["zone"]
    zone = zone_of(zname)
    today = dt.datetime.fromtimestamp(now, zone).date() if zone else dt.date.fromtimestamp(now)
    days = [dt.date.fromisoformat(d) for d in sorted(win["dates"])] if win.get("dates") else [today + dt.timedelta(days=i) for i in (-1, 0, 1)]
    occ = [occurrence(win, zone, d) for d in days]
    pick = next(((o, c, "open") for o, c in occ if o <= now < c), None)
    if pick is None:
        later = [(o, c) for o, c in occ if o > now]
        pick = (*min(later), "waiting") if later else (*occ[-1], "closed")
    return {"name": name, "zone": zname, "state": pick[2], "opens": pick[0], "closes": pick[1], "length_s": pick[1] - pick[0]}


def fmt(epoch: float) -> str:
    """An epoch as the machine's local 'YYYY-MM-DD HH:MM:SS', the form the driver's --until reads (hw/card_stress_lib.py parse_when)."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))
