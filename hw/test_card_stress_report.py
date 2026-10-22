#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Test of hw/card_stress_report.py:   python hw/test_card_stress_report.py

HOW IT KNOWS. A synthetic run is built with known truth (three images; battery legs with
passes, a failure, a timeout, a no_device, a parse_error and skips; exhaustive and random sweep
slices, contiguous and not, with failing ones; telemetry on straight lines; host samples;
events; gaps between legs) in a zone nobody here lives in (UTC-03:30), so a report that read
the box's times in this machine's zone would be wrong and say so. Every figure then has three
values: the ORACLE's (plain loops, sets of blocks and of half-seconds, Fraction arithmetic;
it calls nothing in the report), the one summarize() returns, and the one read back out of the
rendered text. They must agree, figure by figure; and a few dozen are also pinned to numbers
counted by hand.

HOW IT KNOWS IT CAN FAIL. Each family of figures (header, totals, rows, telemetry, failures,
sweep, uptime) is shown to move when the data moves: a mutation catalogue flips a status, drops
a slice, moves a telemetry value, shifts a deadline, moves an event out of a gap, and so on, and
for each the report's figures must become exactly the oracle's new truth, with the named ones
changed and nothing else. A second control tampers the finished summary and requires both the
summary check and the text check to name the figure. Files are truncated mid-line, corrupted
in the middle, emptied and removed; the command is run as a subprocess.

THE TREES READ FROM GIT (group git-trees, parcel RG, 2026-10-22). A scratch git repository of three real commits stands in for the
checkout, and runs are built whose first run_start recorded its tree and whose second did not. The report must give the second the
class of a run that recorded that tree (and say "read from git", and list what it read in derived_from_git), and keep it apart, with
the reason, where git cannot say: a commit the repository lacks, a run not recorded clean, a recorded tree git does not give for its
commit, --no-git, no repository, git too slow or not there. Each check family is then run again on a summary made with the defect it
guards against put in (git ignored, a git that finds every commit, a dirty tree taken for clean, ...) and must fail at the check named for
it. The report's coverage in the classes of a resuming run is held to what card_stress_lib.count_slices - the driver's resume - counts
from the same records with the same git, on the synthetic runs and, when CARD_STRESS_RESUME_RUN names a copy of the lead's run, on it.

The last line is "report test: N checks, F failed"; the exit status is 0 only if F is 0.
"""
import sys
sys.dont_write_bytecode = True

import calendar
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from fractions import Fraction

HW = os.path.dirname(os.path.abspath(__file__))
if HW not in sys.path:
    sys.path.insert(0, HW)
import card_stress_lib as LIB       # noqa: E402  (what the driver's resume counts by)
import card_stress_report as R      # noqa: E402  (the unit under test)

SCRIPT = os.path.join(HW, "card_stress_report.py")

# ---------------------------------------------------------------------------
# checks, a line a group
# ---------------------------------------------------------------------------
_st = {"n": 0, "failed": 0, "g": None, "gn": 0, "gf": 0}


def _short(x, n=240):
    s = repr(x)
    return s if len(s) <= n else s[:n] + "..."


def _close_group():
    if _st["g"] is not None:
        print(f"{_st['g']}: {_st['gn']} checks, {_st['gf']} failed")
        sys.stdout.flush()


def group(name):
    _close_group()
    _st.update(g=name, gn=0, gf=0)


def check(ok, what, detail=None):
    _st["n"] += 1
    _st["gn"] += 1
    if not ok:
        _st["failed"] += 1
        _st["gf"] += 1
        print(f"  FAIL [{_st['g']}] {what}" + (f": {_short(detail)}" if detail is not None else ""))
    return bool(ok)


def eq(got, want, what):
    return check(got == want, what, f"got {_short(got)}, want {_short(want)}")


# ---------------------------------------------------------------------------
# the fixture: one synthetic run with known truth
# ---------------------------------------------------------------------------
STATUSES = ("pass", "fail", "timeout", "no_device", "parse_error", "skipped", "error")
T0 = 1_700_000_000                       # 2023-11-14 22:13:20 UTC
BOX_OFF = -(3 * 3600 + 1800)             # the fixture box's zone, UTC-03:30
A = 1 << 20                              # the sweep's slice unit
EXH = 1 << 32
FMT = "%Y-%m-%d %H:%M:%S"
SHA = {"quad": "4f" * 32, "single": "06" * 32, "deep": "bb" * 32}
TILES = {"quad": 4, "single": 1, "deep": 1}
DEFAULT_RC = {"pass": 0, "fail": 1, "timeout": 124, "no_device": 1, "parse_error": 0,
              "skipped": None, "error": None}
ITEMS = {
    "sqrt32-rne": dict(tool="divsqrt", op="sqrt32", mode="rne", reach="tile"),
    "rint32-rne": dict(tool="clause5", op="rint32", mode="rne", reach="tile"),
    "logb32": dict(tool="clause5", op="logb32", mode=None, reach="host"),
    "nextup32": dict(tool="clause5", op="nextup32", mode=None, reach="host"),
    # a record from before the driver wrote `reach`: the report reads it off the op, from the catalog's table
    "div64-rne": dict(tool="divsqrt", op="div64", mode="rne", base=0x50AC0000 + 5),
    "sqrt64-rne": dict(tool="divsqrt", op="sqrt64", mode="rne", base=0x50AC0000 + 9, reach="tile"),
}
# the operations whose reach the ORACLE knows by itself (independent of the report and of the lib's table), for
# a record that does not say
ORACLE_REACH = {"sqrt32": "tile", "sqrt64": "tile", "div64": "tile", "rint32": "tile", "logb32": "host",
                "nextup32": "host", "rem32": "host", "conv32to64": "host", "conv32to64-all": "host",
                "cvtfrom32-all": "host", "scaleb32-wide": "tile"}
# items only the reach group's run uses: the exhaustive conversion and scaleB items of parcel EX (their records say what
# they covered: `encodings` and `skipped` in counts, `expected_encodings` in the sweep), and records whose `reach` is
# missing, invalid, or contradicts the table
ITEMS.update({
    "conv32to64-all": dict(tool="clause5", op="conv32to64-all", mode=None, reach="host", per=1),
    "scaleb32-wide-rne": dict(tool="clause5", op="scaleb32-wide", mode="rne", reach="tile", per=568),
    "cvtfrom32-all-rne": dict(tool="clause5", op="cvtfrom32-all", mode="rne", reach="fast", per=2),
    "rem32": dict(tool="clause5", op="rem32", mode=None, base=0xC5000000 + 9),
    "futureop-x": dict(tool="clause5", op="futureop", mode=None, base=7),
    "conv32to64": dict(tool="clause5", op="conv32to64", mode=None, base=0xC5000000 + 8, reach="tile"),
})
SKIP_A = ("the revision-8 set has no entry for u50-rev8: its rule puts a workload on the single only "
          "where R21 alone keeps it off the quad, which none does")
SKIP_B = "every u50-rev8-deep entry is a 40-minute-or-longer compile with no cached image"
SKIP_C = "every 3 visits of an image; this is visit 2"
SKIP_D = "the soak binary is not built"
SQRT_FAIL_LINES = ["MISMATCH sqrt32 rne in=0x7f800001 got=0x7fc00000 want=0x7fc00001",
                   "FLAGS sqrt32 rne in=0x00000001 got=0x01 want=0x00"]
DIV_FAIL_LINES = ["FLAGS div64 rne a=0x3ff0000000000000 b=0x7ff0000000000000 got=0x00 want=0x01"]
TMO = "no answer within 180 s"
NODEV = "no_device: opening device 0: no such device"
ORDER = ["quad", "quad", "single", "quad", "deep", "quad", "quad", "single", "quad", "deep",
         "quad", "quad", "single", "deep", "deep"]
Q_DUR_I = [20, 20, 21, 19, 20, 20, 22, 20]
Q_RATE_I = [3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, None]
Q_DUR_Q8 = [58, 60, 61, 59, 62, 60, 63, 57]
Q_RATE_Q8 = [50.0, 52.0, 51.0, 53.0, 49.0, 47.0, 46.0, 44.0]
S_DUR_Q8, S_RATE_Q8 = [70, 71, 69], [30.0, 31.0, 32.0]
D_DUR_Q8, D_RATE_Q8 = [80, 82, 81, 79], [10.0, 11.0, 12.0, 13.0]


def box_ts(e):
    return time.strftime(FMT, time.gmtime(math.floor(e) + BOX_OFF))


def cps(v):
    return None if v is None else {"value": v, "unit": "checks/s"}


def job_ex(item, lo, hi, status="pass", vm=0, fm=0, lines=None, reason=None):
    return dict(item=item, lo=lo * A, hi=hi * A, status=status, vm=vm, fm=fm, lines=lines, reason=reason)


def job_rd(item, n, count, status="pass", vm=0, fm=0, lines=None, reason=None):
    return dict(item=item, seed_n=n, count=count, status=status, vm=vm, fm=fm, lines=lines, reason=reason)


QUAD_WAVES = [
    [job_ex("sqrt32-rne", 0, 1), job_rd("div64-rne", 0, 1_000_000)],
    [job_ex("sqrt32-rne", 1, 2), job_rd("div64-rne", 1, 1_000_000)],
    [job_ex("sqrt32-rne", 2, 3), job_rd("div64-rne", 2, 1_000_000, "fail", fm=1, lines=DIV_FAIL_LINES)],
    [job_ex("sqrt32-rne", 3, 4), job_rd("div64-rne", 3, 1_000_000)],
    [job_ex("sqrt32-rne", 4, 5, "timeout", reason=TMO), job_rd("div64-rne", 4, 1_000_000, "no_device", reason=NODEV)],
    [job_ex("sqrt32-rne", 3, 4)],                                  # the same slice again
    [job_ex("sqrt32-rne", 10, 12)],
    [job_ex("sqrt32-rne", 12, 13)],                                # touches [10, 12)
    [job_ex("sqrt32-rne", 20, 21)],
    [job_ex("sqrt32-rne", 30, 31, "fail", vm=2, lines=SQRT_FAIL_LINES)],
]
SINGLE_WAVES = [
    [job_ex("rint32-rne", 0, 1), job_rd("sqrt64-rne", 0, 500_000)],
    [job_ex("rint32-rne", 1, 2, "parse_error", reason="soak: 0 cases - the tool ran nothing (exit status 0)"),
     job_rd("sqrt64-rne", 1, 500_000)],
    [job_ex("logb32", 0, 1, "timeout", reason=TMO), job_ex("nextup32", 0, 1, "skipped", reason=SKIP_D)],
]


class Fx:
    """Records of one run. add() takes the record's own time; records() sorts by it, the way a
    file written as things happen is sorted (a leg is written when it ends)."""

    def __init__(self):
        self.items, self.seq, self.cycle, self.cur = [], 0, 0, None
        self.rate_n = Counter()

    def add(self, typ, epoch, **kw):
        rec = {"v": 1, "type": typ, "ts": box_ts(epoch), "epoch": float(epoch)}
        rec.update(kw)
        self.items.append((epoch, self.seq, rec))
        self.seq += 1
        return rec

    def records(self):
        return [r for _, _, r in sorted(self.items, key=lambda x: (x[0], x[1]))]

    def event(self, epoch, name, detail="", **kw):
        return self.add("event", epoch, event=name, detail=detail, **kw)

    def leg(self, image, name, start, dur, status="pass", kind="battery", attempt=1, counts=None,
            rate=None, sweep=None, disagreements=None, reason=None, tile=None, extra=None, notes=None):
        end = start + dur
        to = status == "timeout"
        rec = self.add("leg", end, cycle=self.cycle, image=image, image_sha256=SHA[image], leg=name,
                       kind=kind, attempt=attempt, start=box_ts(start), end=box_ts(end),
                       start_epoch=float(start), end_epoch=float(end), duration_s=float(dur),
                       rc=DEFAULT_RC[status], status=status, timed_out=to, killed="TERM" if to else None,
                       counts=counts, rate=rate, sweep=sweep, disagreements=disagreements,
                       log=None if status == "skipped" else f"logs/{self.seq:04d}-{name}.log",
                       log_kept="none" if status == "skipped" else ("gz" if status == "pass" else "whole"),
                       reason=reason, tile=tile, extra=extra)
        if notes:
            rec["notes"] = notes
        return rec

    def battery(self, t, image, specs):
        """Legs one after another, two seconds apart (a skip is a point one second on)."""
        for sp in specs:
            sp = dict(sp)
            name, dur = sp.pop("name"), sp.pop("dur", 0)
            if sp.get("status") == "skipped":
                t += 1
                self.leg(image, name, t, 0, **sp)
            else:
                self.leg(image, name, t + 2, dur, **sp)
                t = t + 2 + dur
        return t

    def wave(self, t, image, jobs):
        """Sweep jobs started together a second apart, so they overlap."""
        s0, end = t + 2, t
        for j, job in enumerate(jobs):
            it, st = job["item"], job["status"]
            s, dur = s0 + j, (0 if st == "skipped" else 30 + 2 * j)
            info = ITEMS[it]
            sw = {"item": it, "tool": info["tool"], "op": info["op"], "mode": info["mode"]}
            if info.get("reach") is not None:
                sw["reach"] = info["reach"]
            per = info.get("per")             # an item whose verdict line says what it covered (the -all / -wide modes)
            if "lo" in job:
                sw.update(lo=job["lo"], hi=job["hi"], tile=j + 1, jobs=len(jobs),
                          expected_cases=(job["hi"] - job["lo"]) * (per or 1))
                cases = (job["hi"] - job["lo"]) * (per or 1)
                if per:
                    sw["expected_encodings"] = job["hi"] - job["lo"]
            else:
                sw.update(count=job["count"], seed=info["base"] + 7919 * job["seed_n"], seed_n=job["seed_n"],
                          tile=j + 1, jobs=len(jobs))
                cases = job["count"]
            counts = rate = None
            if st in ("pass", "fail"):
                counts = {"cases": cases, "value_mismatches": job["vm"], "flag_mismatches": job["fm"]}
                if per:
                    counts.update(encodings=job["hi"] - job["lo"], skipped=0)
                rate = {"value": {"quad": 1000.0, "single": 5000.0}[image] + 10.0 * self.rate_n[image],
                        "unit": "cases/s"}
                self.rate_n[image] += 1
            self.leg(image, "sweep-" + it, s, dur, status=st, kind="sweep", counts=counts, rate=rate,
                     sweep=sw, disagreements=job["lines"], reason=job["reason"], tile=j + 1)
            end = max(end, s + dur)
        return end

    def begin_cycle(self, t, image, visit, pause):
        self.cycle += 1
        start0 = t + pause
        self.add("cycle_start", start0 - 1, cycle=self.cycle, image=image, image_sha256=SHA[image],
                 visit=visit, battery=["api-test", "dt-i", "dt-q8"], sweep_minutes=1.0, quick=False)
        self.cur = (self.cycle, image, start0 - 1)
        return start0 - 2                    # the first leg starts two seconds after this

    def end_cycle(self, t):
        c, image, t0 = self.cur
        legs = [r for _, _, r in self.items if r["type"] == "leg" and r["cycle"] == c
                and r["kind"] == "battery" and r["status"] != "skipped"]
        self.add("cycle_end", t + 1, cycle=c, image=image, legs=len(legs),
                 failed=sum(1 for r in legs if r["status"] != "pass"), seconds=float(t + 1 - t0))


def quad_specs(k):
    s = [dict(name="api-test", dur=10, counts={"failed": 0}),
         dict(name="dt-i", dur=Q_DUR_I[k], counts={"checks": 66, "failed": 0}, rate=cps(Q_RATE_I[k])),
         dict(name="dt-q8", dur=Q_DUR_Q8[k], counts={"checks": 2733, "failed": 0}, rate=cps(Q_RATE_Q8[k]))]
    if k in (0, 4):
        s.append(dict(name="card-segrun", dur=90, counts={"checks": 6, "failed": 0}))
    if k == 0:
        s.append(dict(name="acceptance", dur=380, rate=cps(0.458),
                      counts={"entries": 20, "entries_passed": 20, "checks": 174, "failed": 0,
                              "reported_seconds": 371}))
    if k == 2:
        s.append(dict(name="resident", dur=15, counts={"failed": 0}))
    return s


def small_specs(n, durs, rates):
    return [dict(name="api-test", dur=10, counts={"failed": 0}),
            dict(name="dt-i", dur=20, counts={"checks": 66, "failed": 0}),
            dict(name="dt-q8", dur=durs[n], counts={"checks": 2733, "failed": 0}, rate=cps(rates[n]))]


def add_telemetry(fx):
    fail = {3: "xbutil: timed out after 20 s", 7: "--format JSON: no values (rc 1) device not found",
            9: "xbutil: timed out after 20 s"}
    when = {0: "before-cycle", 5: "after-battery", 11: "end"}
    for k in range(12):
        e = T0 + 100 + 400 * k
        host = {"load1": 0.5 + 0.25 * k, "load5": 0.75, "load15": 1.0 - 0.0625 * k,
                "mem_avail_mb": 40000 - 100 * k, "mem_total_mb": 47000,
                "disk_free_gb": {"/data/stress": 500.0 - 0.25 * k}}
        if k in fail:
            fx.add("telemetry", e, cycle=None, image=None, when=when.get(k, "timer"), ok=False, values=None,
                   host=host, raw="[xrt] no values here", error=fail[k])
        else:
            vals = {"xbutil.temp": 40.0 + 1.5 * k, "xbutil.power": 25.0 - 0.5 * k, "xbutil.fan": 3000}
            if k < 2:
                vals["xbutil.rare"] = 7.0 + 0.25 * k
            fx.add("telemetry", e, cycle=None, image=None, when=when.get(k, "timer"), ok=True, values=vals,
                   host=host, raw=None, error=None)


def run_start_rec(fx, epoch, resumed=False, deadline=None):
    dl = box_ts(deadline if deadline is not None else T0 + 86400)
    return fx.add("run_start", epoch, run_id="stress-20231114-abc1234", out="/data/stress/run1",
                  host="amd-arc-box", argv=["--until", dl],
                  settings={"until": dl, "quick": False, "dry_run": False, "legs": ["api-test", "dt-i", "dt-q8"]},
                  tree={"commit": "abc1234def5678", "dirty": False},
                  images={n: {"sha256": SHA[n], "bytes": 1000 + i, "tiles": TILES[n], "path": f"/x/{n}.xclbin",
                             "target": f"u50-rev8-{n}"} for i, n in enumerate(("quad", "single", "deep"))},
                  deadline=dl, resumed=resumed)


def build_main():
    """The run: 15 cycles (8 quad, 3 single, 4 deep), 85 legs. Returns (records, marks)."""
    fx, marks = Fx(), {}
    run_start_rec(fx, T0)
    fx.add("build", T0 + 5, ok=True, steps=[{"name": "host tools", "ok": True, "detail": "built"},
                                           {"name": "image quad", "ok": True, "detail": "sha256 ok"},
                                           {"name": "probes", "ok": True, "detail": "modes rne"}])
    t = T0 + 97
    visits, qi, si, di = Counter(), 0, 0, 0
    for pos, image in enumerate(ORDER):
        pause = {5: 200, 8: 900}.get(pos, 3)
        if pos == 5:
            marks["small_gap"] = (t, t + 200)
            fx.event(t + 50, "retry", "leg dt-i again after a 20 s pause")
        if pos == 8:
            marks["big_gap"] = (t, t + 900)
            fx.event(t - 5, "tree_moved", "HEAD moved to 1a2b3c4 (noted, not acted on)")
            fx.event(t + 30, "guard_refused", "card in use by pid 4242 (xbutil)")
            fx.event(t + 60.5, "guard_wait", "card busy; waited 30 s")
            fx.event(t + 600, "guard_wait", "card busy; waited 570 s")
            fx.event(t + 890, "guard_clear", "the card is free")
            fx.event(t + 905, "disk_floor", "9.8 GB free of a 10 GB floor (warning)")
        visits[image] += 1
        t = fx.begin_cycle(t, image, visits[image], pause)
        if image == "quad":
            t = fx.battery(t, "quad", quad_specs(qi))
            if qi < 5:
                for w in (2 * qi, 2 * qi + 1):
                    t = fx.wave(t, "quad", QUAD_WAVES[w])
            qi += 1
        elif image == "single":
            specs = small_specs(si, S_DUR_Q8, S_RATE_Q8)
            if si == 0:
                t = fx.battery(t, "single", specs + [dict(name="acceptance-rev8", status="skipped", reason=SKIP_A)])
            elif si == 1:
                t = fx.battery(t, "single", specs + [dict(name="dt-full", dur=300, status="timeout",
                                                          reason="no answer within 300 s")])
                fx.event(t + 1, "pause", "card not answering (consecutive failure 1); waiting 30 s", streak=1)
                t = fx.battery(t + 29, "single", [
                    dict(name="dt-full", dur=100, attempt=2, counts={"checks": 5000, "failed": 0}, rate=cps(50.0)),
                    dict(name="acceptance-rev8", status="skipped", reason=SKIP_A)])
            else:
                t = fx.battery(t, "single", specs + [dict(name="dt-r", dur=12, status="no_device", reason=NODEV)])
                fx.event(t + 1, "pause", "card not answering (consecutive failure 1); waiting 30 s", streak=1)
                fx.event(t + 32, "recover_start", "open quad, then single again", streak=1)
                fx.event(t + 32, "image_switch", "single -> quad -> single")
                fx.leg("quad", "dt-i", t + 33, 25, kind="recovery", counts={"checks": 66, "failed": 0},
                       rate=cps(2.64), extra={"image_sha256": SHA["quad"], "tiles": 4})
                fx.leg("single", "dt-i", t + 60, 24, kind="recovery", counts={"checks": 66, "failed": 0},
                       rate=cps(2.75), extra={"image_sha256": SHA["single"], "tiles": 1})
                fx.event(t + 85, "recover_end", "single answers again (dt-i passed)", ok=True)
                t = fx.battery(t + 85, "single", [
                    dict(name="dt-r", dur=40, attempt=2, counts={"checks": 300, "failed": 0}),
                    dict(name="seq-check", dur=200, status="parse_error",
                         reason="seq_check: neither the device's pass line nor a recognised failure line (exit status 0)"),
                    dict(name="acceptance-rev8", status="skipped", reason=SKIP_A),
                    dict(name="selftest", status="skipped", reason=SKIP_C)])
            t = fx.wave(t, "single", SINGLE_WAVES[si])
            si += 1
        else:
            specs = small_specs(di, D_DUR_Q8, D_RATE_Q8)
            if di == 2:
                specs[2] = dict(specs[2], status="fail", counts={"checks": 2733, "failed": 3},
                                notes=["device-test: 3 checks failed"])
            t = fx.battery(t, "deep", specs + [dict(name="acceptance-rev8", status="skipped", reason=SKIP_B)])
            di += 1
        fx.end_cycle(t)
    add_telemetry(fx)
    end = max(t, T0 + 4500) + 50
    fx.add("run_end", end, reason="deadline", exit=0, cycles=len(ORDER))
    marks.update(first_leg_start=T0 + 100, run_end=end, last_leg_end=t)
    return fx.records(), marks


# ---------------------------------------------------------------------------
# the oracle: expected figures from the records, by plain loops (nothing from the report)
# ---------------------------------------------------------------------------

def med(xs):
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def ls_slope_per_hour(pts):
    """Least-squares slope of value against epoch, per hour, in exact arithmetic (a Fraction)."""
    n = len(pts)
    if n < 3:
        return None
    xs = [Fraction(p[0]) for p in pts]
    ys = [Fraction(p[1]) for p in pts]
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx * 3600


def pieces_of(intervals):
    """Pieces of the union of closed intervals with whole-second ends, on a grid of half
    seconds: two intervals that touch share a grid point, two that do not are apart."""
    grid = set()
    for s, e in intervals:
        grid.update(range(int(2 * s), int(2 * e) + 1))
    out = []
    for p in sorted(grid):
        if out and p == out[-1][1] + 1:
            out[-1][1] = p
        else:
            out.append([p, p])
    return [(a / 2, b / 2) for a, b in out]


def stat_block(pts):
    pts = sorted(pts, key=lambda p: p[0])
    vs = [Fraction(p[1]) for p in pts]
    return {"n": len(vs), "min": min(vs), "max": max(vs), "mean": sum(vs) / len(vs), "first": vs[0],
            "last": vs[-1], "slope": ls_slope_per_hour(pts), "range": max(vs) - min(vs)}


def oracle(recs, now=None, gap_s=300):
    F = {}
    idx = list(enumerate(recs))

    def typ(t):
        return [(i, r) for i, r in idx if r["type"] == t]

    legs = typ("leg")
    # ---- header
    rs, rn = typ("run_start"), typ("run_end")
    F["header.run_id"] = ", ".join(dict.fromkeys(r["run_id"] for _, r in rs)) or None
    F["header.host"] = ", ".join(dict.fromkeys(r["host"] for _, r in rs)) or None
    F["header.commit"] = rs[0][1]["tree"]["commit"] if rs else None
    F["header.dirty"] = rs[0][1]["tree"]["dirty"] if rs else None
    F["header.started"] = rs[0][1]["ts"] if rs else None
    F["header.run_starts"] = len(rs)
    F["header.resumed"] = sum(1 for _, r in rs if r["resumed"] is True)
    ended = bool(rn) and (not rs or rn[-1][0] > rs[-1][0])
    F["header.running"] = not ended
    F["header.ended"] = rn[-1][1]["ts"] if ended else None
    F["header.end_reason"] = rn[-1][1]["reason"] if ended else None
    last_epoch = max(r["epoch"] for r in recs)
    F["header.age_s"] = None if ended else now - last_epoch
    cur = rs[-1][1] if rs else None
    F["header.deadline"] = cur["deadline"] if cur and cur.get("deadline") else None
    if F["header.deadline"]:
        dl = calendar.timegm(time.strptime(F["header.deadline"], FMT)) - BOX_OFF
        F["header.remaining_s"] = dl - (rn[-1][1]["epoch"] if ended else now)
    else:
        F["header.remaining_s"] = None
    F["header.quick"] = cur["settings"]["quick"] if cur else None
    F["header.dry_run"] = cur["settings"]["dry_run"] if cur else None
    # ---- totals
    F["totals.legs"] = len(legs)
    for s in STATUSES:
        F[f"totals.status.{s}"] = sum(1 for _, r in legs if r["status"] == s)
    cs, ce = typ("cycle_start"), typ("cycle_end")
    F["totals.cycles_started"], F["totals.cycles_ended"] = len(cs), len(ce)
    done = {r["cycle"] for _, r in ce}
    F["totals.unfinished"] = sorted(r["cycle"] for _, r in cs if r["cycle"] not in done)
    F["totals.by_image"] = sorted(Counter(r["image"] for _, r in cs).items())
    F["totals.cycle_end_failed"] = sum(1 for _, r in ce if r["failed"] > 0)
    F["totals.cycle_end_reporting"] = sum(1 for _, r in ce if "failed" in r)
    F["totals.builds"] = ["ok" if r["ok"] else "FAILED" for _, r in typ("build")]
    F["totals.records"] = sorted(Counter(r["type"] for r in recs).items())
    # ---- rows
    order, rows = [], {}
    for pos, (_, r) in enumerate(legs):
        if r["image"] not in order:
            order.append(r["image"])
        label = ("sweep (all items)" if r["kind"] == "sweep" else
                 r["leg"] if r["kind"] == "battery" else f'{r["leg"]} [{r["kind"]}]')
        row = rows.setdefault((r["image"], label), {"pos": pos, "runs": 0, "st": Counter(), "checks": None,
                                                    "cases": None, "dur": [], "rates": []})
        row["runs"] += 1
        row["st"][r["status"]] += 1
        for fld in ("checks", "cases"):
            if r.get("counts") and fld in r["counts"]:
                row[fld] = (row[fld] or 0) + r["counts"][fld]
        if r["status"] not in ("skipped", "error"):
            row["dur"].append(r["duration_s"])
        if r.get("rate"):
            row["rates"].append((r["start_epoch"], pos, r["rate"]["value"], r["rate"]["unit"]))
    listed = sorted(rows.items(), key=lambda kv: (order.index(kv[0][0]), kv[0][1] == "sweep (all items)", kv[1]["pos"]))
    F["rows"] = [f"{k[0]}/{k[1]}" for k, _ in listed]
    for (img, label), row in listed:
        p = f"row[{img}/{label}]."
        F[p + "runs"] = row["runs"]
        for s in STATUSES:
            F[p + s] = row["st"].get(s, 0)
        F[p + "checks"], F[p + "cases"] = row["checks"], row["cases"]
        d = row["dur"]
        F[p + "dur_med"], F[p + "dur_min"], F[p + "dur_max"] = (med(d), min(d), max(d)) if d else (None, None, None)
        rates = sorted(row["rates"], key=lambda x: (x[0], x[1]))
        vals = [x[2] for x in rates]
        n = len(vals)
        F[p + "rate_unit"] = rates[0][3] if rates else None
        F[p + "rate_n"] = n
        F[p + "rate_med"], F[p + "rate_min"], F[p + "rate_max"] = (med(vals), min(vals), max(vals)) if n else (None, None, None)
        F[p + "trend"], F[p + "trend_note"] = None, ("too few" if 0 < n < 4 else None)
        if n >= 4:
            q = n // 4
            m1, m2 = med(vals[:q]), med(vals[n - q:])
            F[p + "trend"] = (m2 - m1) / m1 * 100
        F[p + "series"] = vals if n <= 12 else [vals[round(j * (n - 1) / 11)] for j in range(12)]
    # ---- telemetry
    tel = [r for _, r in typ("telemetry")]
    F["tele.samples"] = len(tel)
    F["tele.with_values"] = sum(1 for r in tel if r.get("values"))
    F["tele.failed"] = sum(1 for r in tel if r["ok"] is False)
    errs = Counter(r["error"] or "(no error text)" for r in tel if r["ok"] is False)
    F["tele.errors"] = sorted(errs.items(), key=lambda kv: (-kv[1], kv[0]))
    F["tele.by_when"] = sorted(Counter(r["when"] for r in tel).items())
    dev, host = defaultdict(list), defaultdict(list)
    for r in tel:
        for label, v in (r.get("values") or {}).items():
            dev[label].append((r["epoch"], v))
        for k, v in (r.get("host") or {}).items():
            if isinstance(v, dict):
                for path, g in v.items():
                    host[f"host.{k}[{path}]"].append((r["epoch"], g))
            else:
                host[f"host.{k}"].append((r["epoch"], v))
    blocks = {label: stat_block(pts) for label, pts in dev.items()}
    ordered = sorted(blocks, key=lambda l: (-blocks[l]["range"], l))
    F["tele.labels_total"] = len(ordered)
    F["tele.left_out"] = max(0, len(ordered) - 40)
    F["tele.labels"] = ordered[:40]
    for label in ordered[:40]:
        for fld, v in blocks[label].items():
            if fld != "range":
                F[f"tele.label[{label}].{fld}"] = v
    first = ["host.load1", "host.load5", "host.load15", "host.mem_avail_mb", "host.mem_total_mb"]
    hl = sorted(host, key=lambda l: (0, first.index(l)) if l in first else ((2, l) if "[" in l else (1, l)))
    F["tele.hostlabels"] = hl
    for label in hl:
        for fld, v in stat_block(host[label]).items():
            if fld != "range":
                F[f"tele.host[{label}].{fld}"] = v
    raws = [r["raw"] for r in tel if r.get("raw")]
    F["tele.first_raw"] = raws[0][:600] if raws and not F["tele.with_values"] else None
    # ---- failures
    bad = sorted(((r["start_epoch"], i, r) for i, r in legs if r["status"] not in ("pass", "skipped")),
                 key=lambda x: (x[0], x[1]))
    F["fail.count"] = len(bad)
    F["fail.list"] = [(r["start"], r["image"], r["leg"], r["attempt"], r["status"], r["rc"], r["timed_out"],
                       r["killed"], r["reason"],
                       [(k, str(v)) for k, v in r["counts"].items()] if r["counts"] else None,
                       (r["disagreements"] or [])[:3] or None, len(r["disagreements"] or []),
                       "; ".join(r["notes"]) if r.get("notes") else None, r["log"]) for _, _, r in bad]
    groups = {}
    for _, _, r in sorted(((r["start_epoch"], i, r) for i, r in legs if r["status"] == "skipped"),
                          key=lambda x: (x[0], x[1])):
        g = groups.setdefault((r["leg"], r["reason"]), [0, []])
        g[0] += 1
        if r["image"] not in g[1]:
            g[1].append(r["image"])
    F["skip.count"] = sum(g[0] for g in groups.values())
    F["skip.groups"] = [(k[0], k[1], g[0], sorted(g[1])) for k, g in groups.items()]
    # ---- sweep (slice boundaries are whole blocks of 2**20, so a block set is the oracle)
    items = {}
    for _, r in legs:
        sw = r.get("sweep")
        if r["kind"] != "sweep" or not sw or r["status"] == "skipped":
            continue
        it = items.setdefault(sw["item"], {"exh": "lo" in sw, "slices": 0, "cases": 0, "blocks": set(),
                                           "inc": 0, "seed": None,
                                           "reach": (sw["reach"] if sw.get("reach") in ("tile", "host")
                                                     else ORACLE_REACH.get(sw.get("op")))})
        if r["status"] in ("pass", "fail"):
            it["slices"] += 1
            it["cases"] += r["counts"]["cases"]
            if "lo" in sw:
                assert sw["lo"] % A == 0 and sw["hi"] % A == 0, "oracle: a slice off the block grid"
                it["blocks"].update(range(sw["lo"] // A, sw["hi"] // A))
            else:
                it["seed"] = sw["seed_n"] if it["seed"] is None else max(it["seed"], sw["seed_n"])
        else:
            it["inc"] += 1
    exh = sorted(k for k, v in items.items() if v["exh"])
    F["sweep.exh"] = exh
    tot_cov = 0
    for k in exh:
        v, p = items[k], f"sweep.exh[{k}]."
        b = sorted(v["blocks"])
        F[p + "slices"], F[p + "cases"], F[p + "incomplete"] = v["slices"], v["cases"], v["inc"]
        F[p + "reach"] = v["reach"] or "unknown"
        F[p + "covered"] = len(b) * A
        F[p + "pct"] = len(b) * A / EXH * 100
        F[p + "intervals"] = sum(1 for j, x in enumerate(b) if j == 0 or x != b[j - 1] + 1)
        gap = 0
        while gap in v["blocks"]:
            gap += 1
        nxt = gap + 1
        while nxt < EXH // A and nxt not in v["blocks"]:
            nxt += 1
        F[p + "first_gap"] = None if gap >= EXH // A else [gap * A, nxt * A]
        tot_cov += len(b) * A
    F["sweep.total.items"], F["sweep.total.covered"] = len(exh), tot_cov
    F["sweep.total.total"] = len(exh) * EXH
    F["sweep.total.pct"] = tot_cov / (len(exh) * EXH) * 100 if exh else None
    F["sweep.total.complete"] = sum(1 for k in exh if len(items[k]["blocks"]) == EXH // A)
    tr = []
    for key in ("tile", "host", "unknown"):
        mine = [k for k in exh if (items[k]["reach"] or "unknown") == key]
        if mine:
            cov = sum(len(items[k]["blocks"]) * A for k in mine)
            tr.append((key, len(mine), cov, len(mine) * EXH, cov / (len(mine) * EXH) * 100,
                       sum(1 for k in mine if len(items[k]["blocks"]) == EXH // A)))
    F["sweep.total.reach"] = tr
    rnd = sorted(k for k, v in items.items() if not v["exh"])
    F["sweep.rand"] = rnd
    for k in rnd:
        v, p = items[k], f"sweep.rand[{k}]."
        F[p + "slices"], F[p + "cases"], F[p + "incomplete"], F[p + "max_seed_n"] = v["slices"], v["cases"], v["inc"], v["seed"]
        F[p + "reach"] = v["reach"] or "unknown"
    F["sweep.rand.reach"] = [(key, sum(1 for k in rnd if (items[k]["reach"] or "unknown") == key))
                             for key in ("tile", "host", "unknown") if any((items[k]["reach"] or "unknown") == key for k in rnd)]
    sl = [r for _, r in legs if r["kind"] == "sweep"]
    F["sweep.completed"] = sum(1 for r in sl if r["status"] in ("pass", "fail"))
    F["sweep.failed"] = sum(1 for r in sl if r["status"] == "fail")
    for s in ("timeout", "no_device", "parse_error"):
        F[f"sweep.nc.{s}"] = sum(1 for r in sl if r["status"] == s)
    F["sweep.skipped"] = sum(1 for r in sl if r["status"] == "skipped")
    dis = []
    for r in sl:
        if r["status"] == "fail" and r.get("sweep"):
            sw = r["sweep"]
            where = ("range", sw["lo"], sw["hi"]) if "lo" in sw else ("seed", sw["seed"], sw["seed_n"], sw["count"])
            dis.append((sw["item"], r["image"], r["start"], where,
                        [(k, str(v)) for k, v in (r["counts"] or {}).items()] or None,
                        list(r["disagreements"] or []), r["log"]))
    F["sweep.disagreements"] = dis
    F["sweep.none_phrase"] = F["sweep.completed"] if not dis else None
    # ---- uptime
    used = [(r["start_epoch"], r["end_epoch"]) for _, r in legs]
    card = [(r["start_epoch"], r["end_epoch"]) for _, r in legs
            if r["kind"] in ("battery", "sweep") and r["status"] != "skipped"]
    first_epoch = min(r["epoch"] for r in recs)
    end_epoch = last_epoch if ended else max(now, last_epoch)
    wall = end_epoch - first_epoch
    pc = pieces_of(used)
    F["up.wall_s"] = wall
    F["up.legs_s"] = sum(b - a for a, b in pc)
    F["up.legs_pct"] = F["up.legs_s"] / wall * 100 if wall > 0 else None
    F["up.card_s"] = sum(b - a for a, b in pieces_of(card))
    F["up.card_pct"] = F["up.card_s"] / wall * 100 if wall > 0 else None
    F["up.before_first"] = pc[0][0] - first_epoch if pc else None
    F["up.after_last"] = end_epoch - pc[-1][1] if pc else None
    allgaps = [(a[1], b[0]) for a, b in zip(pc, pc[1:])]
    F["up.longest_gap_s"] = max(g1 - g0 for g0, g1 in allgaps) if allgaps else None
    over = [(g0, g1) for g0, g1 in allgaps if g1 - g0 > gap_s]
    F["up.gaps_over"] = len(over)
    evs = [r for _, r in typ("event")]
    marks = [r for _, r in idx if r["type"] in ("run_start", "run_end", "build")]
    F["up.gaps"] = [(box_ts(g0), box_ts(g1), g1 - g0,
                     [(r["ts"], r["event"], r["detail"]) for r in sorted(evs, key=lambda r: r["epoch"])
                      if g0 <= r["epoch"] <= g1],
                     [(r["ts"], r["type"]) for r in sorted(marks, key=lambda r: r["epoch"]) if g0 <= r["epoch"] <= g1])
                    for g0, g1 in over]
    F["up.events"] = sorted(Counter(r["event"] for r in evs).items(), key=lambda kv: (-kv[1], kv[0]))
    F["up.run_ends"] = [(r["ts"], r["reason"], r["exit"], r["cycles"]) for _, r in rn]
    return F


# ---------------------------------------------------------------------------
# the same figures, read out of summarize()'s data and out of render()'s text
# ---------------------------------------------------------------------------

class Txt:
    """A number read from the text: its value and the half unit of its last printed digit."""

    def __init__(self, s):
        self.s = s
        self.v = float(s)
        dec = len(s.split(".")[1]) if "." in s else 0
        self.tol = 0.5 * 10 ** (-dec) * (1 + 1e-9) + 1e-12

    def __repr__(self):
        return f"Txt({self.s})"


def num(s):
    s = s.strip()
    return None if s in ("", "-") else Txt(s)


def match(exp, got):
    if isinstance(got, Txt):
        return (exp is not None and not isinstance(exp, (str, list, tuple, bool))
                and abs(got.v - float(exp)) <= got.tol)
    if exp is None or got is None:
        return exp is None and got is None
    if isinstance(exp, (list, tuple)):
        return isinstance(got, (list, tuple)) and len(exp) == len(got) and all(match(a, b) for a, b in zip(exp, got))
    if isinstance(exp, (float, Fraction)) or isinstance(got, (float, Fraction)):
        a, b = float(exp), float(got)
        return abs(a - b) <= 1e-9 * max(1.0, abs(a))
    return exp == got


def norm(x):
    if isinstance(x, Txt):
        return x.s
    if isinstance(x, (list, tuple)):
        return [norm(v) for v in x]
    if isinstance(x, Fraction):
        return float(x)
    return x


def summary_figs(S):
    F = {}
    h = S["header"]
    F["header.run_id"] = ", ".join(h["run_ids"]) or None
    F["header.host"] = ", ".join(h["hosts"]) or None
    t0 = h["trees"][0] if h["trees"] else None
    F["header.commit"], F["header.dirty"] = (t0["commit"], t0["dirty"]) if t0 else (None, None)
    F["header.started"] = h["started"]["ts"] if h["started"] else None
    F["header.run_starts"], F["header.resumed"] = h["run_starts"], h["resumed_marked"]
    F["header.running"] = h["running"]
    last = h["run_ends"][-1] if h["run_ends"] else None
    F["header.ended"] = None if h["running"] else last["ts"]
    F["header.end_reason"] = None if h["running"] else last["reason"]
    F["header.age_s"] = h["age_s"]
    d = h["deadline"]
    F["header.deadline"] = d["text"] if d else None
    F["header.remaining_s"] = d["remaining_s"] if d else None
    f = h["flags"]
    F["header.quick"], F["header.dry_run"] = (f["quick"], f["dry_run"]) if f else (None, None)
    t = S["totals"]
    F["totals.legs"] = t["legs"]["total"]
    for s in STATUSES:
        F[f"totals.status.{s}"] = t["legs"]["by_status"][s]
    c = t["cycles"]
    F["totals.cycles_started"], F["totals.cycles_ended"] = c["started"], c["ended"]
    F["totals.unfinished"] = c["unfinished"]
    F["totals.by_image"] = sorted(c["by_image"].items())
    F["totals.cycle_end_failed"], F["totals.cycle_end_reporting"] = c["ended_with_failed"], c["ended_reporting_failed"]
    F["totals.builds"] = ["ok" if b["ok"] else "FAILED" for b in t["builds"]]
    F["totals.records"] = sorted(t["records"].items())
    F["rows"] = [f'{r["image"]}/{r["leg"]}' for r in S["rows"]]
    for r in S["rows"]:
        p = f'row[{r["image"]}/{r["leg"]}].'
        F[p + "runs"] = r["runs"]
        for s in STATUSES:
            F[p + s] = r["statuses"][s]
        F[p + "checks"], F[p + "cases"] = r["checks"], r["cases"]
        F[p + "dur_med"], F[p + "dur_min"], F[p + "dur_max"] = r["duration"]["median"], r["duration"]["min"], r["duration"]["max"]
        ra = r["rate"]
        F[p + "rate_unit"] = ra["unit"] if ra else None
        F[p + "rate_n"] = ra["n"] if ra else 0
        F[p + "rate_med"], F[p + "rate_min"], F[p + "rate_max"] = (ra["median"], ra["min"], ra["max"]) if ra else (None, None, None)
        F[p + "trend"] = ra["trend_pct"] if ra else None
        F[p + "trend_note"] = ra["trend_note"] if ra else None
        F[p + "series"] = ra["series"] if ra else []
    T = S["telemetry"]
    F["tele.samples"], F["tele.with_values"], F["tele.failed"] = T["samples"], T["with_values"], T["failed"]
    F["tele.errors"] = [(e["message"], e["count"]) for e in T["errors"]]
    F["tele.by_when"] = sorted(T["by_when"].items())
    F["tele.labels_total"] = T["labels_total"]
    F["tele.left_out"] = max(0, T["labels_total"] - 40)
    F["tele.labels"] = [x["label"] for x in T["labels"][:40]]
    for x in T["labels"][:40]:
        for fld, key in (("n", "n"), ("min", "min"), ("max", "max"), ("mean", "mean"), ("first", "first"),
                         ("last", "last"), ("slope", "slope_per_hour")):
            F[f'tele.label[{x["label"]}].{fld}'] = x[key]
    F["tele.hostlabels"] = [x["label"] for x in T["host"]]
    for x in T["host"]:
        for fld, key in (("n", "n"), ("min", "min"), ("max", "max"), ("mean", "mean"), ("first", "first"),
                         ("last", "last"), ("slope", "slope_per_hour")):
            F[f'tele.host[{x["label"]}].{fld}'] = x[key]
    F["tele.first_raw"] = T["first_raw"] if T["with_values"] == 0 else None
    Fl = S["failures"]
    F["fail.count"] = Fl["count"]
    F["fail.list"] = [(b["start"], b["image"], b["leg"], b["attempt"], b["status"], b["rc"], b["timed_out"],
                       b["killed"], b["reason"],
                       [(k, str(v)) for k, v in b["counts"].items()] if b["counts"] else None,
                       (b["disagreements"] or [])[:3] or None, len(b["disagreements"] or []),
                       "; ".join(b["notes"]) if b["notes"] else None, b["log"]) for b in Fl["legs"]]
    F["skip.count"] = Fl["skipped"]["count"]
    F["skip.groups"] = [(g["leg"], g["reason"], g["count"], sorted(g["images"])) for g in Fl["skipped"]["groups"]]
    W = S["sweep"]
    F["sweep.exh"] = [e["item"] for e in W["exhaustive"]]
    for e in W["exhaustive"]:
        p = f'sweep.exh[{e["item"]}].'
        for fld, key in (("slices", "slices"), ("cases", "cases"), ("covered", "covered"), ("pct", "pct"),
                         ("intervals", "intervals"), ("first_gap", "first_gap"), ("incomplete", "incomplete")):
            F[p + fld] = e[key]
        F[p + "reach"] = e["reach"] or "unknown"
    tt = W["total_exhaustive"]
    F["sweep.total.items"], F["sweep.total.covered"], F["sweep.total.total"] = tt["items"], tt["covered"], tt["total"]
    F["sweep.total.pct"], F["sweep.total.complete"] = tt["pct"], tt["complete_items"]
    F["sweep.total.reach"] = [(r["reach"] or "unknown", r["items"], r["covered"], r["total"], r["pct"], r["complete_items"])
                              for r in tt["by_reach"]]
    F["sweep.rand"] = [e["item"] for e in W["random"]]
    for e in W["random"]:
        p = f'sweep.rand[{e["item"]}].'
        F[p + "slices"], F[p + "cases"], F[p + "incomplete"], F[p + "max_seed_n"] = e["slices"], e["cases"], e["incomplete"], e["max_seed_n"]
        F[p + "reach"] = e["reach"] or "unknown"
    F["sweep.rand.reach"] = [(r["reach"] or "unknown", r["items"]) for r in W["random_by_reach"]]
    F["sweep.completed"], F["sweep.failed"], F["sweep.skipped"] = W["completed"], W["failed"], W["skipped"]
    for s in ("timeout", "no_device", "parse_error"):
        F[f"sweep.nc.{s}"] = W["not_completed"][s]
    dis = []
    for d in W["disagreements"]:
        sw = d["sweep"]
        where = ("range", sw["lo"], sw["hi"]) if "lo" in sw else ("seed", sw["seed"], sw["seed_n"], sw["count"])
        dis.append((d["item"], d["image"], d["start"], where,
                    [(k, str(v)) for k, v in d["counts"].items()] if d["counts"] else None, list(d["lines"]), d["log"]))
    F["sweep.disagreements"] = dis
    F["sweep.none_phrase"] = W["completed"] if not dis else None
    U = S["uptime"]
    F["up.wall_s"], F["up.legs_s"], F["up.card_s"] = U["wall_s"], U["legs_union_s"], U["card_union_s"]
    F["up.legs_pct"] = None if U["legs_fraction"] is None else U["legs_fraction"] * 100
    F["up.card_pct"] = None if U["card_fraction"] is None else U["card_fraction"] * 100
    F["up.before_first"], F["up.after_last"] = U["before_first_leg_s"], U["after_last_leg_s"]
    F["up.longest_gap_s"] = U["longest_gap"]["seconds"] if U["longest_gap"] else None
    F["up.gaps_over"] = U["gaps_over"]
    F["up.gaps"] = [(g["start"], g["end"], g["seconds"], [(e["ts"], e["event"], e["detail"]) for e in g["events"]],
                     [(m["ts"], m["type"]) for m in g["records"]]) for g in U["gaps"]]
    F["up.events"] = list(U["events_by_name"].items())
    F["up.run_ends"] = [(e["ts"], e["reason"], e["exit"], e["cycles"]) for e in h["run_ends"]]
    return F


def sections(text):
    top, secs, cur = [], {}, None
    for ln in text.split("\n"):
        m = re.match(r"^== (.+) ==$", ln)
        if m:
            cur = m.group(1)
            secs[cur] = []
        elif cur is None:
            top.append(ln)
        else:
            secs[cur].append(ln)
    return top, secs


def kvs(lines):
    d = {}
    for ln in lines:
        if not ln or ln.startswith(" "):
            continue
        key, sep, val = ln.partition(": ")
        if sep:
            d.setdefault(key.strip(), []).append(val)
    return d


def first_of(d, key):
    v = d.get(key)
    return v[0] if v else None


def dash(s):
    return None if s in (None, "-") else s


def parse_table(lines, header, stop=None):
    """The rows of the table whose header line has exactly these words, each cell sliced at the
    header words' columns; a table ends at a blank line or at a line matching `stop`."""
    for i, ln in enumerate(lines):
        if ln.split() == header:
            offs = [m.start() for m in re.finditer(r"\S+", ln)]
            rows = []
            for ln2 in lines[i + 1:]:
                if not ln2.strip() or (stop and re.match(stop, ln2)):
                    break
                cells = [ln2[o:(offs[j + 1] if j + 1 < len(offs) else None)].strip() for j, o in enumerate(offs)]
                rows.append(dict(zip(header, cells)))
            return rows
    return None


def hex_pair(s):
    m = re.match(r"^\[0x([0-9a-f]+), 0x([0-9a-f]+)\)$", s)
    return [int(m.group(1), 16), int(m.group(2), 16)] if m else None


def pairs_of(s):
    if s in (None, "none"):
        return None
    return [tuple(p.split("=", 1)) for p in s.split(", ")]


def count_pairs(s):
    return sorted((p.rsplit(" ", 1)[0], int(p.rsplit(" ", 1)[1])) for p in s.split(", "))


STAT_HDR = ["label", "samples", "min", "max", "mean", "first", "last", "slope_per_h"]
YN = {"yes": True, "no": False, "-": None}
STAMP = r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d"


def text_figs(T):
    top, secs = sections(T)
    F = {}
    # ---- header
    h = kvs(secs["HEADER"])
    F["header.run_id"], F["header.host"] = dash(first_of(h, "run id")), dash(first_of(h, "host"))
    m = re.match(r"^commit (\S+) \((clean|DIRTY|dirty unknown)\)", first_of(h, "tree") or "")
    F["header.commit"] = dash(m.group(1)) if m else None
    F["header.dirty"] = {"clean": False, "DIRTY": True}.get(m.group(2)) if m else None
    F["header.started"] = dash(first_of(h, "started"))
    m = re.match(r"^(\d+) record\(s\), (\d+) marked resumed$", first_of(h, "run_start"))
    F["header.run_starts"], F["header.resumed"] = int(m.group(1)), int(m.group(2))
    e = first_of(h, "ended")
    m = re.match(rf"^RUNNING: last record ({STAMP}), (\d+) s ago", e)
    if m:
        F["header.running"], F["header.ended"], F["header.end_reason"], F["header.age_s"] = True, None, None, Txt(m.group(2))
    else:
        m = re.match(r"^(\S+ \S+) \(reason (.*?), exit (\S+), cycles (\S+)\)$", e)
        F["header.running"], F["header.ended"], F["header.end_reason"], F["header.age_s"] = False, m.group(1), dash(m.group(2)), None
    dtxt = first_of(h, "deadline")
    if dtxt == "none set":
        F["header.deadline"], F["header.remaining_s"] = None, None
    else:
        text, _, phrase = dtxt.partition("; ")
        F["header.deadline"] = re.sub(r" \(from settings\.until\)$", "", text)
        m = re.search(r"(\d+) s \(", phrase)
        F["header.remaining_s"] = Txt(("-" if phrase.startswith("OVERSHOOT") else "") + m.group(1)) if m else None
    m = re.match(r"^quick (\S+), dry_run (\S+)", first_of(h, "flags"))
    F["header.quick"], F["header.dry_run"] = (YN[m.group(1)], YN[m.group(2)]) if m else (None, None)
    # ---- totals
    t = kvs(secs["TOTALS"])
    m = re.match(r"^(\d+) recorded; (.*)$", first_of(t, "legs"))
    F["totals.legs"] = int(m.group(1))
    for part in m.group(2).split(", "):
        name, n = part.rsplit(" ", 1)
        F[f"totals.status.{name}"] = int(n)
    m = re.match(r"^(\d+) started, (\d+) ended; started and not ended: (.*)$", first_of(t, "cycles"))
    F["totals.cycles_started"], F["totals.cycles_ended"] = int(m.group(1)), int(m.group(2))
    F["totals.unfinished"] = [] if m.group(3) == "none" else [int(x) for x in m.group(3).split(", ")]
    bi = first_of(t, "by image")
    F["totals.by_image"] = [] if bi == "-" else count_pairs(bi)
    m = re.match(r"^(\d+) of (\d+) records", first_of(t, "cycle_end"))
    F["totals.cycle_end_failed"], F["totals.cycle_end_reporting"] = int(m.group(1)), int(m.group(2))
    F["totals.builds"] = [("ok" if b.startswith("ok") else "FAILED") for b in t.get("build", []) if b != "no build record"]
    rec = first_of(t, "records")
    F["totals.records"] = [] if rec == "none" else count_pairs(rec)
    # ---- rows
    rl = secs["PER IMAGE AND LEG"]
    F["rows"] = []
    if rl and not rl[0].startswith("no leg records"):
        hdr_a = ["image", "leg", "runs"] + list(STATUSES) + ["checks", "cases"]
        ta = parse_table(rl, hdr_a) or parse_table(rl, hdr_a[:10] + ["other"] + hdr_a[10:])
        tb = parse_table(rl, ["image", "leg", "dur_med_s", "dur_min_s", "dur_max_s", "rate_unit", "n_rates",
                              "rate_med", "rate_min", "rate_max", "trend"])
        series = {}
        for ln in rl:
            m = re.match(r"^  (\S+) / (.+) \[([^\[\],]+), (\d+) rates?(?:, (\d+) picked)?\]: (.*)$", ln)
            if m:
                series[f"{m.group(1)}/{m.group(2)}"] = [num(x) for x in m.group(6).split()]
        for a, b in zip(ta, tb):
            key = f'{a["image"]}/{a["leg"]}'
            F["rows"].append(key)
            p = f"row[{key}]."
            F[p + "runs"] = int(a["runs"])
            for s in STATUSES:
                F[p + s] = int(a[s])
            F[p + "checks"] = int(a["checks"]) if a["checks"] else None
            F[p + "cases"] = int(a["cases"]) if a["cases"] else None
            F[p + "dur_med"], F[p + "dur_min"], F[p + "dur_max"] = num(b["dur_med_s"]), num(b["dur_min_s"]), num(b["dur_max_s"])
            F[p + "rate_unit"] = dash(b["rate_unit"])
            F[p + "rate_n"] = int(b["n_rates"])
            F[p + "rate_med"], F[p + "rate_min"], F[p + "rate_max"] = num(b["rate_med"]), num(b["rate_min"]), num(b["rate_max"])
            tr = b["trend"]
            F[p + "trend"] = Txt(tr.rstrip("%")) if re.match(r"^[+-]\d", tr) else None
            F[p + "trend_note"] = tr if tr in ("too few", "n/a") else None
            F[p + "series"] = series.get(key, [])
    # ---- telemetry
    tl = secs["TELEMETRY"]
    F.update({"tele.samples": 0, "tele.with_values": 0, "tele.failed": 0, "tele.errors": [], "tele.by_when": [],
              "tele.labels_total": 0, "tele.left_out": 0, "tele.labels": [], "tele.hostlabels": [], "tele.first_raw": None})
    m = re.match(r"^telemetry: (\d+) samples, none parsed$", tl[0])
    m2 = re.match(r"^telemetry: (\d+) samples, (\d+) with values, (\d+) without, (\d+) marked ok=false$", tl[0])
    if m:
        F["tele.samples"] = int(m.group(1))
    elif m2:
        F["tele.samples"], F["tele.with_values"], F["tele.failed"] = int(m2.group(1)), int(m2.group(2)), int(m2.group(4))
    errs, in_err, raw, in_raw = [], False, [], False
    for i, ln in enumerate(tl):
        mw = re.match(r"^  by when: (.*)$", ln)
        if mw:
            F["tele.by_when"] = count_pairs(mw.group(1))
        mf = re.match(r"^  samples with ok=false: (\d+); errors:$", ln)
        if mf:
            F["tele.failed"] = int(mf.group(1))
            in_err = True
            continue
        me = re.match(r"^    (\d+) x (.*)$", ln)
        if in_err and me:
            errs.append((me.group(2), int(me.group(1))))
        elif in_err:
            in_err = False
        if re.match(r"^  first raw text \(\d+ of \d+ chars\):$", ln):
            in_raw = True
            continue
        if in_raw:
            if ln.startswith("    "):
                raw.append(ln[4:])
            else:
                in_raw = False
        md = re.match(r"^  device labels: (\d+)", ln)
        if md:
            F["tele.labels_total"] = int(md.group(1))
            rows = parse_table(tl[i + 1:], STAT_HDR) or []
            F["tele.labels"] = [r["label"] for r in rows]
            for r in rows:
                p = f'tele.label[{r["label"]}].'
                F[p + "n"] = int(r["samples"])
                for fld in ("min", "max", "mean", "first", "last"):
                    F[p + fld] = num(r[fld])
                F[p + "slope"] = num(r["slope_per_h"])
            ml = re.search(r"(\d+) left out", ln)
            F["tele.left_out"] = int(ml.group(1)) if ml else 0
        if ln == "  host fields:":
            rows = parse_table(tl[i + 1:], STAT_HDR) or []
            F["tele.hostlabels"] = [r["label"] for r in rows]
            for r in rows:
                p = f'tele.host[{r["label"]}].'
                F[p + "n"] = int(r["samples"])
                for fld in ("min", "max", "mean", "first", "last"):
                    F[p + fld] = num(r[fld])
                F[p + "slope"] = num(r["slope_per_h"])
    F["tele.errors"] = errs
    F["tele.first_raw"] = "\n".join(raw) if raw else None
    # ---- failures
    fl = secs["FAILURES"]
    F["fail.count"], F["skip.count"], F["skip.groups"] = 0, 0, []
    legs_, cur = [], None
    for ln in fl:
        mc = re.match(r"^legs not passed \(.*\): (\d+); ", ln)
        if mc:
            F["fail.count"] = int(mc.group(1))
            continue
        mh = re.match(r"^  (.+?)  (\S+)  (\S+)  attempt (\S+)  status (\S+)  rc (\S+)  timed_out (\S+)  killed (\S+)$", ln)
        if mh:
            g = mh.groups()
            cur = {"start": dash(g[0]), "image": dash(g[1]), "leg": g[2], "attempt": None if g[3] == "-" else int(g[3]),
                   "status": g[4], "rc": None if g[5] == "-" else int(g[5]), "timed_out": YN[g[6]], "killed": dash(g[7]),
                   "reason": None, "counts": None, "dis": [], "dis_n": 0, "notes": None, "log": None}
            legs_.append(cur)
            continue
        if cur is not None and ln.startswith("      "):
            body = ln[6:]
            if body.startswith("reason: "):
                cur["reason"] = None if body[8:] == "none" else body[8:]
            elif body.startswith("counts: "):
                cur["counts"] = pairs_of(body[8:])
            elif body.startswith("notes: "):
                cur["notes"] = body[7:]
            elif body.startswith("log: "):
                cur["log"] = None if body[5:] == "none" else body[5:]
            else:
                md = re.match(r"^disagreements \(first \d+ of (\d+)\):$", body)
                if md:
                    cur["dis_n"] = int(md.group(1))
                elif ln.startswith("        "):
                    cur["dis"].append(ln[8:])
        ms = re.match(r"^skipped legs: (\d+) in ", ln)
        if ms:
            F["skip.count"] = int(ms.group(1))
            cur = None
        mg = re.match(r'^  (\S+): (\d+) x "(.*)" \(images: (.*)\)$', ln)
        if mg:
            F["skip.groups"].append((mg.group(1), None if mg.group(3) == "(no reason recorded)" else mg.group(3),
                                     int(mg.group(2)), sorted(mg.group(4).split(", "))))
    F["fail.list"] = [(c["start"], c["image"], c["leg"], c["attempt"], c["status"], c["rc"], c["timed_out"], c["killed"],
                       c["reason"], c["counts"], c["dis"] or None, c["dis_n"], c["notes"], c["log"]) for c in legs_]
    # ---- sweep
    sl = secs["SWEEP COVERAGE"]
    exh = parse_table(sl, ["item", "slices", "cases", "covered", "pct", "intervals", "first_uncovered", "incomplete", "reach"],
                      stop=r"^  total:") or []
    F["sweep.exh"] = [r["item"] for r in exh]
    for r in exh:
        p = f'sweep.exh[{r["item"]}].'
        F[p + "slices"], F[p + "cases"], F[p + "covered"] = int(r["slices"]), int(r["cases"]), int(r["covered"])
        F[p + "pct"] = Txt(r["pct"].rstrip("%"))
        F[p + "intervals"], F[p + "incomplete"] = int(r["intervals"]), int(r["incomplete"])
        F[p + "first_gap"] = hex_pair(r["first_uncovered"])
        F[p + "reach"] = r["reach"]
    F.update({"sweep.total.items": 0, "sweep.total.covered": 0, "sweep.total.total": 0, "sweep.total.pct": None,
              "sweep.total.complete": 0, "sweep.none_phrase": None})
    F["sweep.total.reach"] = []
    rnd = parse_table(sl, ["item", "slices", "cases", "highest_seed_n", "incomplete", "reach"],
                      stop=r"^  random reach:") or []
    F["sweep.rand"] = [r["item"] for r in rnd]
    for r in rnd:
        p = f'sweep.rand[{r["item"]}].'
        F[p + "slices"], F[p + "cases"], F[p + "incomplete"] = int(r["slices"]), int(r["cases"]), int(r["incomplete"])
        F[p + "max_seed_n"] = None if r["highest_seed_n"] == "-" else int(r["highest_seed_n"])
        F[p + "reach"] = r["reach"]
    F["sweep.rand.reach"] = []
    dis, cur = [], None
    for ln in sl:
        mt = re.match(r"^  total: (\d+) exhaustive item\(s\) seen; covered (\d+) of (\d+) encodings \((\S+)%\); "
                      r"fully covered (\d+) of (\d+)$", ln)
        if mt:
            F["sweep.total.items"], F["sweep.total.covered"], F["sweep.total.total"] = int(mt.group(1)), int(mt.group(2)), int(mt.group(3))
            F["sweep.total.pct"], F["sweep.total.complete"] = Txt(mt.group(4)), int(mt.group(5))
        mr = re.match(r"^  reach (tile|host|unknown): (\d+) exhaustive item\(s\) seen; covered (\d+) of (\d+) encodings "
                      r"\((\S+)%\); fully covered (\d+) of (\d+)$", ln)
        if mr:
            F["sweep.total.reach"].append((mr.group(1), int(mr.group(2)), int(mr.group(3)), int(mr.group(4)),
                                           Txt(mr.group(5)), int(mr.group(6))))
        mq = re.match(r"^  random reach: (.*)$", ln)
        if mq:
            F["sweep.rand.reach"] = [(m2.group(1), int(m2.group(2))) for m2 in
                                     re.finditer(r"(tile|host|unknown) (\d+) item\(s\)", mq.group(1))]
        ms = re.match(r"^slices: (\d+) completed \(pass (\d+), fail (\d+)\); did not complete: timeout (\d+), "
                      r"no_device (\d+), parse_error (\d+)(?:, [^;]*)?; skipped (\d+)$", ln)
        if ms:
            F["sweep.completed"], F["sweep.failed"] = int(ms.group(1)), int(ms.group(3))
            F["sweep.nc.timeout"], F["sweep.nc.no_device"], F["sweep.nc.parse_error"] = int(ms.group(4)), int(ms.group(5)), int(ms.group(6))
            F["sweep.skipped"] = int(ms.group(7))
        mn = re.match(r"^no disagreement recorded in (\d+) completed slices$", ln)
        if mn:
            F["sweep.none_phrase"] = int(mn.group(1))
        md = re.match(r"^  \[(\d+)\] item (\S+), image (\S+), start (.+?), (?:range \[0x([0-9a-f]+), 0x([0-9a-f]+)\)|"
                      r"seed (\d+) \(seed_n (\d+), count (\d+)\))$", ln)
        if md:
            g = md.groups()
            where = ("range", int(g[4], 16), int(g[5], 16)) if g[4] else ("seed", int(g[6]), int(g[7]), int(g[8]))
            cur = {"item": g[1], "image": dash(g[2]), "start": dash(g[3]), "where": where, "counts": None, "lines": [], "log": None}
            dis.append(cur)
            continue
        if cur is not None and ln.startswith("      "):
            body = ln[6:]
            if body.startswith("counts: "):
                cur["counts"] = pairs_of(body[8:])
            elif body.startswith("log: "):
                cur["log"] = None if body[5:] == "none" else body[5:]
            else:
                cur["lines"].append(body)
    F["sweep.disagreements"] = [(d["item"], d["image"], d["start"], d["where"], d["counts"], d["lines"], d["log"]) for d in dis]
    # ---- uptime
    ul = secs["UPTIME AND GAPS"]
    u = kvs(ul)

    def secs_of(key):
        m = re.match(r"^(\S+) s \(", first_of(u, key) or "")
        return Txt(m.group(1)) if m else None

    def pct_of(key):
        m = re.search(r"\), ([\d.]+)%", first_of(u, key) or "")
        return Txt(m.group(1)) if m else None

    F["up.wall_s"], F["up.legs_s"], F["up.card_s"] = secs_of("wall span"), secs_of("in legs"), secs_of("on the card")
    F["up.legs_pct"], F["up.card_pct"] = pct_of("in legs"), pct_of("on the card")
    for key, fld in (("before 1st leg", "up.before_first"), ("after last leg", "up.after_last")):
        v = first_of(u, key)
        F[fld] = Txt(v[:-2]) if v and v != "-" else None
    lg = first_of(u, "longest gap")
    F["up.longest_gap_s"] = Txt(re.match(r"^(\S+) s \(", lg).group(1)) if lg and not lg.startswith("n/a") else None
    gk = [k for k in u if k.startswith("gaps >")]
    F["up.gaps_over"] = int(u[gk[0]][0]) if gk else 0
    gaps, curg = [], None
    for ln in ul:
        mg = re.match(r"^  gap (\d+): (.*?) to (.*?), (\S+) s \(.*?\), (\d+) event\(s\) inside$", ln)
        if mg:
            curg = {"start": mg.group(2), "end": mg.group(3), "seconds": Txt(mg.group(4)), "events": [], "records": []}
            gaps.append(curg)
            continue
        if curg is not None and ln.startswith("      "):
            mm = re.match(rf"^      ({STAMP})  \[(\w+), .*\]$", ln)
            if mm:
                curg["records"].append((mm.group(1), mm.group(2)))
                continue
            me = re.match(rf"^      ({STAMP})  ([^\s:]+): (.*)$", ln)
            if me:
                curg["events"].append((me.group(1), me.group(2), me.group(3)))
        elif not ln.startswith("  "):
            curg = None
    F["up.gaps"] = [(g["start"], g["end"], g["seconds"], g["events"], g["records"]) for g in gaps]
    ev = first_of(u, "events")
    F["up.events"] = [] if ev in (None, "none") else [(p.rsplit(" ", 1)[0], int(p.rsplit(" ", 1)[1])) for p in ev.split(", ")]
    ends = []
    for v in u.get("run_end", []):
        m = re.match(r"^(\S+ \S+), reason (.*?), exit (\S+), cycles (\S+)$", v)
        if m:
            ends.append((m.group(1), dash(m.group(2)), None if m.group(3) == "-" else int(m.group(3)),
                         None if m.group(4) == "-" else int(m.group(4))))
    F["up.run_ends"] = ends
    return F


# ---------------------------------------------------------------------------
# scenarios and comparisons
# ---------------------------------------------------------------------------
FAMILIES = {"header": ("header.",), "totals": ("totals.",), "rows": ("rows", "row["),
            "telemetry": ("tele.",), "failures": ("fail.", "skip."), "sweep": ("sweep.",), "uptime": ("up.",)}


class Scn:
    def __init__(self, recs, now=None, gap_s=300, **kw):
        self.recs, self.now, self.gap_s = recs, now, gap_s
        self.S = R.summarize(recs, now=now, gap_seconds=gap_s, **kw)
        self.T = R.render(self.S)
        self.O = oracle(recs, now, gap_s)
        self.FS = summary_figs(self.S)
        self.FT = text_figs(self.T)


def in_family(key, fam):
    return any(key == p or key.startswith(p) for p in FAMILIES[fam])


def compare(scn, fam, label=""):
    """Every oracle figure of a family against the summary's and the text's; and neither may
    carry a figure the oracle does not."""
    keys = [k for k in scn.O if in_family(k, fam)]
    for k in keys:
        for view, figs in (("summary", scn.FS), ("text", scn.FT)):
            if k not in figs:
                check(False, f"{label}{view} has no {k}")
            else:
                check(match(scn.O[k], figs[k]), f"{label}{view} {k}", f"oracle {_short(scn.O[k])}, got {_short(figs[k])}")
    for view, figs in (("summary", scn.FS), ("text", scn.FT)):
        extra = sorted(k for k in figs if in_family(k, fam) and k not in scn.O)
        check(not extra, f"{label}{view} carries figures the oracle does not", extra[:6])
    return len(keys)


def compare_all(scn, label=""):
    for fam in FAMILIES:
        compare(scn, fam, label)


def mismatches(O, figs):
    return sorted(k for k in O if k not in figs or not match(O[k], figs[k]))


def same(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def changed(a, b):
    """Keys whose value differs between two figure dicts (as the text prints them, to a float's noise)."""
    return sorted(k for k in set(a) | set(b) if not same(norm(a.get(k, "<absent>")), norm(b.get(k, "<absent>"))))


def hand(scn, pins, label=""):
    """Figures pinned to numbers counted by hand: the oracle, the summary and the text each."""
    for k, want in pins.items():
        for view, figs in (("oracle", scn.O), ("summary", scn.FS), ("text", scn.FT)):
            check(k in figs and match(want, figs[k]), f"{label}{view} {k} is {_short(want)}",
                  f"got {_short(figs.get(k, '<absent>'))}")


def line_re(text, pattern):
    return re.search(pattern, text, re.M) is not None


# ---------------------------------------------------------------------------
# helpers for file-level tests
# ---------------------------------------------------------------------------

def write_metrics(path, recs):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def write_bytes(path, data):
    with open(path, "wb") as fh:
        fh.write(data)


def read_text(path):
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def run_cli(args):
    p = subprocess.run([sys.executable, "-B", "-I", SCRIPT] + args, capture_output=True, timeout=180)
    return (p.returncode, p.stdout.decode("utf-8", "replace").replace("\r\n", "\n"),
            p.stderr.decode("utf-8", "replace").replace("\r\n", "\n"))


def run_main(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = R.main(args)
        except SystemExit as e:
            rc = e.code
    return rc, out.getvalue(), err.getvalue()


def mutate(recs, fn):
    out = copy.deepcopy(recs)
    fn(out)
    return out


def find_all(recs, **kw):
    return [r for r in recs if all(r.get(k) == v for k, v in kw.items())]


def find(recs, **kw):
    return find_all(recs, **kw)[0]


# ---------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------

def group_pins(base, marks):
    group("fixture")
    recs = base.recs
    eq(recs, sorted(recs, key=lambda r: r["epoch"]), "the file is in time order")
    hand(base, {
        "totals.records": [("build", 1), ("cycle_end", 15), ("cycle_start", 15), ("event", 12), ("leg", 85),
                           ("run_end", 1), ("run_start", 1), ("telemetry", 12)],
        "totals.legs": 85, "totals.status.pass": 66, "totals.status.fail": 3, "totals.status.timeout": 3,
        "totals.status.no_device": 2, "totals.status.parse_error": 2, "totals.status.skipped": 9,
        "totals.status.error": 0, "totals.cycles_started": 15, "totals.cycles_ended": 15, "totals.unfinished": [],
        "totals.cycle_end_failed": 3, "totals.cycle_end_reporting": 15,
        "totals.by_image": [("deep", 4), ("quad", 8), ("single", 3)], "totals.builds": ["ok"],
        "header.run_starts": 1, "header.resumed": 0, "header.running": False, "header.end_reason": "deadline",
        "header.commit": "abc1234def5678", "header.dirty": False, "header.run_id": "stress-20231114-abc1234",
        "header.host": "amd-arc-box", "header.started": box_ts(T0), "header.ended": box_ts(marks["run_end"]),
        "header.deadline": box_ts(T0 + 86400), "header.remaining_s": T0 + 86400 - marks["run_end"],
        "header.quick": False, "header.dry_run": False, "header.age_s": None,
    })
    hand(base, {
        "row[quad/dt-q8].runs": 8, "row[quad/dt-q8].checks": 21864, "row[quad/dt-q8].dur_med": 60.0,
        "row[quad/dt-q8].dur_min": 57, "row[quad/dt-q8].dur_max": 63, "row[quad/dt-q8].rate_n": 8,
        "row[quad/dt-q8].rate_med": 49.5, "row[quad/dt-q8].rate_min": 44.0, "row[quad/dt-q8].rate_max": 53.0,
        "row[quad/dt-q8].trend": -600 / 51, "row[quad/dt-q8].series": Q_RATE_Q8, "row[quad/dt-q8].rate_unit": "checks/s",
        "row[quad/dt-i].runs": 8, "row[quad/dt-i].rate_n": 7, "row[quad/dt-i].trend": (3.7 - 3.1) / 3.1 * 100,
        "row[quad/dt-i].checks": 528, "row[quad/api-test].checks": None, "row[quad/api-test].rate_unit": None,
        "row[quad/api-test].rate_n": 0, "row[quad/api-test].trend": None, "row[quad/api-test].trend_note": None,
        "row[quad/dt-i [recovery]].runs": 1, "row[quad/dt-i [recovery]].rate_n": 1,
        "row[single/dt-i [recovery]].runs": 1, "row[single/dt-q8].trend": None,
        "row[single/dt-q8].trend_note": "too few", "row[deep/dt-q8].trend": 30.0, "row[deep/dt-q8].fail": 1,
        "row[deep/dt-q8].pass": 3, "row[single/dt-full].timeout": 1, "row[single/dt-full].pass": 1,
        "row[single/dt-full].dur_max": 300.0, "row[single/dt-r].no_device": 1, "row[single/seq-check].parse_error": 1,
        "row[single/acceptance-rev8].skipped": 3, "row[single/acceptance-rev8].dur_med": None,
        "row[deep/acceptance-rev8].skipped": 4, "row[quad/sweep (all items)].runs": 15,
        "row[quad/sweep (all items)].rate_n": 13, "row[quad/sweep (all items)].cases": 10 * A + 4_000_000,
        "row[quad/sweep (all items)].series": [1000.0 + 10 * j for j in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12)],
        "row[quad/sweep (all items)].timeout": 1, "row[quad/sweep (all items)].no_device": 1,
        "row[single/sweep (all items)].runs": 6, "row[single/sweep (all items)].skipped": 1,
        "row[single/sweep (all items)].rate_n": 3, "row[single/sweep (all items)].trend_note": "too few",
        "row[quad/card-segrun].runs": 2, "row[quad/card-segrun].checks": 12, "row[quad/acceptance].checks": 174,
    })
    hand(base, {
        "tele.samples": 12, "tele.with_values": 9, "tele.failed": 3,
        "tele.errors": [("xbutil: timed out after 20 s", 2), ("--format JSON: no values (rc 1) device not found", 1)],
        "tele.by_when": [("after-battery", 1), ("before-cycle", 1), ("end", 1), ("timer", 9)],
        "tele.labels": ["xbutil.temp", "xbutil.power", "xbutil.rare", "xbutil.fan"],
        "tele.label[xbutil.temp].n": 9, "tele.label[xbutil.temp].min": 40.0, "tele.label[xbutil.temp].max": 56.5,
        "tele.label[xbutil.temp].first": 40.0, "tele.label[xbutil.temp].last": 56.5,
        "tele.label[xbutil.temp].mean": 40 + 1.5 * 47 / 9, "tele.label[xbutil.temp].slope": 13.5,
        "tele.label[xbutil.power].slope": -4.5, "tele.label[xbutil.fan].slope": 0.0,
        "tele.label[xbutil.rare].n": 2, "tele.label[xbutil.rare].slope": None,
        "tele.host[host.load1].n": 12, "tele.host[host.load1].slope": 2.25,
        "tele.host[host.load5].slope": 0.0, "tele.host[host.load15].slope": -0.5625,
        "tele.host[host.mem_avail_mb].slope": -900.0, "tele.host[host.disk_free_gb[/data/stress]].slope": -2.25,
        "tele.hostlabels": ["host.load1", "host.load5", "host.load15", "host.mem_avail_mb", "host.mem_total_mb",
                            "host.disk_free_gb[/data/stress]"],
    })
    failing = [("sweep-div64-rne", "fail"), ("sweep-sqrt32-rne", "timeout"), ("sweep-div64-rne", "no_device"),
               ("sweep-sqrt32-rne", "fail"), ("dt-full", "timeout"), ("sweep-rint32-rne", "parse_error"),
               ("dt-r", "no_device"), ("seq-check", "parse_error"), ("sweep-logb32", "timeout"), ("dt-q8", "fail")]
    for view, figs in (("oracle", base.O), ("summary", base.FS), ("text", base.FT)):
        eq([(e[2], e[4]) for e in figs["fail.list"]], failing, f"{view}: the ten failing legs, in time order")
    hand(base, {
        "fail.count": 10, "skip.count": 9,
        "skip.groups": [("acceptance-rev8", SKIP_A, 3, ["single"]), ("acceptance-rev8", SKIP_B, 4, ["deep"]),
                        ("selftest", SKIP_C, 1, ["single"]), ("sweep-nextup32", SKIP_D, 1, ["single"])],
    })
    hand(base, {
        "sweep.exh": ["logb32", "rint32-rne", "sqrt32-rne"],
        "sweep.exh[sqrt32-rne].slices": 9, "sweep.exh[sqrt32-rne].cases": 10 * A,
        "sweep.exh[sqrt32-rne].covered": 9 * A, "sweep.exh[sqrt32-rne].pct": 9 / 4096 * 100,
        "sweep.exh[sqrt32-rne].intervals": 4, "sweep.exh[sqrt32-rne].first_gap": [4 * A, 10 * A],
        "sweep.exh[sqrt32-rne].incomplete": 1,
        "sweep.exh[rint32-rne].slices": 1, "sweep.exh[rint32-rne].covered": A, "sweep.exh[rint32-rne].intervals": 1,
        "sweep.exh[rint32-rne].first_gap": [A, EXH], "sweep.exh[rint32-rne].incomplete": 1,
        "sweep.exh[logb32].slices": 0, "sweep.exh[logb32].covered": 0, "sweep.exh[logb32].intervals": 0,
        "sweep.exh[logb32].first_gap": [0, EXH], "sweep.exh[logb32].incomplete": 1,
        "sweep.total.items": 3, "sweep.total.covered": 10 * A, "sweep.total.total": 3 * EXH,
        "sweep.total.pct": 10 * A / (3 * EXH) * 100, "sweep.total.complete": 0,
        "sweep.rand": ["div64-rne", "sqrt64-rne"], "sweep.rand[div64-rne].slices": 4,
        "sweep.rand[div64-rne].cases": 4_000_000, "sweep.rand[div64-rne].max_seed_n": 3,
        "sweep.rand[div64-rne].incomplete": 1, "sweep.rand[sqrt64-rne].slices": 2,
        "sweep.rand[sqrt64-rne].cases": 1_000_000, "sweep.rand[sqrt64-rne].max_seed_n": 1,
        "sweep.rand[sqrt64-rne].incomplete": 0,
        "sweep.completed": 16, "sweep.failed": 2, "sweep.nc.timeout": 2, "sweep.nc.no_device": 1,
        "sweep.nc.parse_error": 1, "sweep.skipped": 1, "sweep.none_phrase": None,
        # which items reach the tile: from the record where it says (sqrt32-rne, rint32-rne, logb32, sqrt64-rne), from
        # the op where it does not (div64-rne's records are from before the driver wrote `reach`)
        "sweep.exh[sqrt32-rne].reach": "tile", "sweep.exh[rint32-rne].reach": "tile", "sweep.exh[logb32].reach": "host",
        "sweep.total.reach": [("tile", 2, 10 * A, 2 * EXH, 10 * A / (2 * EXH) * 100, 0), ("host", 1, 0, EXH, 0.0, 0)],
        "sweep.rand[div64-rne].reach": "tile", "sweep.rand[sqrt64-rne].reach": "tile",
        "sweep.rand.reach": [("tile", 2)],
    })
    g0, g1 = marks["big_gap"]
    hand(base, {
        "up.wall_s": marks["run_end"] - T0, "up.before_first": 100.0,
        "up.after_last": marks["run_end"] - marks["last_leg_end"], "up.gaps_over": 1, "up.longest_gap_s": 900.0,
        "up.run_ends": [(box_ts(marks["run_end"]), "deadline", 0, 15)],
        "up.events": [("guard_wait", 2), ("pause", 2), ("disk_floor", 1), ("guard_clear", 1), ("guard_refused", 1),
                      ("image_switch", 1), ("recover_end", 1), ("recover_start", 1), ("retry", 1), ("tree_moved", 1)],
        "up.gaps": [(box_ts(g0), box_ts(g1), 900.0,
                     [(box_ts(g0 + 30), "guard_refused", "card in use by pid 4242 (xbutil)"),
                      (box_ts(g0 + 60.5), "guard_wait", "card busy; waited 30 s"),
                      (box_ts(g0 + 600), "guard_wait", "card busy; waited 570 s"),
                      (box_ts(g0 + 890), "guard_clear", "the card is free")], [])],
    })
    s0, s1 = marks["small_gap"]
    eq(s1 - s0, 200, "the small gap is 200 s")
    # the oracle's own arithmetic against hand-made cases
    eq(pieces_of([(0, 10), (10, 20), (30, 30), (31, 40), (40, 40), (100, 100)]), [(0, 20), (30, 30), (31, 40), (100, 100)],
       "pieces_of: touching joins, a lone point stays, a point at an end is absorbed")
    eq(ls_slope_per_hour([(0, 1), (1800, 2), (3600, 3)]), 2, "ls_slope_per_hour on a line of 2 per hour")
    eq(ls_slope_per_hour([(0, 1), (1, 2)]), None, "ls_slope_per_hour needs three samples")
    eq((med([3, 1, 2]), med([4, 1, 3, 2]), med([2, 2])), (2, 2.5, 2.0), "med")


def group_families(base):
    for fam in ("header", "totals", "rows", "telemetry", "failures", "sweep", "uptime"):
        group(fam)
        n = compare(base, fam)
        check(n > 0, f"{fam}: the oracle has figures to compare", n)
    group("text")
    top, secs = sections(base.T)
    eq(list(secs), ["HEADER", "TOTALS", "PER IMAGE AND LEG", "TELEMETRY", "FAILURES", "SWEEP COVERAGE",
                    "SWEEP COVERAGE BY TREE", "UPTIME AND GAPS"],
       "the eight sections, in the spec's order (the coverage by tree, parcel DR2, follows the sweep's)")
    check(base.T.endswith("\n") and not base.T.endswith("\n\n"), "the text ends with one newline")
    check(all(ord(c) < 128 for c in base.T), "the report's own text is ASCII")
    check("RUNNING" not in base.T, "an ended run does not say RUNNING")
    check(not top[0].startswith("!!!") and not any("partial" in ln for ln in top), "a clean file raises no warning or note")
    rl = secs["PER IMAGE AND LEG"]
    check(any(ln.startswith("  quad / sweep (all items) [cases/s, 13 rates, 12 picked]:") for ln in rl),
          "the 13 sweep rates are shown as 12 picked")
    check(any("note: a sweep row mixes items" in ln for ln in rl), "the sweep row carries its mixed-items note")
    check(any(ln.startswith("  quad / dt-i [recovery] [checks/s, 1 rate]:") for ln in rl), "a recovery row is labelled, singular")
    check(any(ln.startswith("  single") and "sweep (all items)" in ln for ln in rl), "the sweep row is one per image")
    check(not any(ln.startswith("  deep") and "sweep (all items)" in ln for ln in rl), "no sweep row for an image that ran none")
    check("quad/dt-i" in base.FT["rows"] and "quad/dt-i [recovery]" in base.FT["rows"], "dt-i and dt-i [recovery] are two rows on the quad")
    fl = secs["FAILURES"]
    check(sum(1 for ln in fl if "disagreements (first 1 of 1)" in ln or "disagreements (first 2 of 2)" in ln) == 2,
          "the two failing sweep legs show their disagreement lines in the failures section")
    check(any("      notes: device-test: 3 checks failed" in ln for ln in fl), "a leg's notes are shown")
    sl = secs["SWEEP COVERAGE"]
    check("      MISMATCH sqrt32 rne in=0x7f800001 got=0x7fc00000 want=0x7fc00001" in sl,
          "every operand line of a disagreement is in the sweep section")
    check(not any("no disagreement recorded" in ln for ln in sl), "no 'no disagreement' line when there are some")
    check(not any("first raw text" in ln for ln in secs["TELEMETRY"]), "no raw text when samples have values")
    hd = secs["HEADER"]
    check(any(ln.startswith("images") and "quad 4 tiles sha256 4f4f4f4f4f4f" in ln for ln in hd), "the images' ids are in the header")


def group_running_and_deadline(base, marks):
    group("running")
    recs = base.recs
    run = [r for r in recs if r["type"] != "run_end"]
    last = max(r["epoch"] for r in run)
    sc = Scn(run, now=last + 42)
    compare_all(sc, "running: ")
    hand(sc, {"header.running": True, "header.age_s": 42, "header.remaining_s": T0 + 86400 - (last + 42),
              "header.ended": None, "up.wall_s": last + 42 - T0, "up.run_ends": []}, "running: ")
    check(f"RUNNING: last record {box_ts(last)}, 42 s ago" in sc.T, "RUNNING: last record <ts>, 42 s ago")
    over = Scn(run, now=T0 + 86400 + 90)
    check("OVERSHOOT: " in over.T and over.FS["header.remaining_s"] == -90, "past the deadline while running: OVERSHOOT, -90 s")
    late = mutate(recs, lambda rr: [r.update(deadline=box_ts(marks["run_end"] - 1000)) for r in rr if r["type"] == "run_start"])
    sl = Scn(late)
    check("OVERSHOOT: ended 1000 s (16 m 40 s) after the deadline" in sl.T and sl.FS["header.remaining_s"] == -1000,
          "an ended run past its deadline: OVERSHOOT, 1000 s")
    group("zone")
    shifted = copy.deepcopy(recs)
    delta = 5 * 3600 + 45 * 60
    for r in shifted:
        for k in ("ts", "start", "end", "deadline"):
            if isinstance(r.get(k), str) and re.match(rf"^{STAMP}$", r[k]):
                r[k] = time.strftime(FMT, time.gmtime(calendar.timegm(time.strptime(r[k], FMT)) + delta))
    z = R.summarize(shifted)
    eq(z["header"]["deadline"]["remaining_s"], base.S["header"]["deadline"]["remaining_s"],
       "the same run in another zone: the same remaining time")
    check(z["header"]["deadline"]["text"] != base.S["header"]["deadline"]["text"], "though the recorded strings differ")


def group_gaps(base, marks):
    group("gaps")
    for gs, lens in ((1000, []), (300, [900.0]), (30, [200.0, 31.0, 900.0, 33.0]), (1, None), (0, None)):
        sc = Scn(base.recs, gap_s=gs)
        compare(sc, "uptime", f"gap_seconds {gs}: ")
        if lens is not None:
            eq([g[2] for g in sc.O["up.gaps"]], lens, f"gap_seconds {gs}: gap lengths in time order")
        eq(sc.FS["up.longest_gap_s"], 900.0, f"gap_seconds {gs}: the longest gap is still 900 s")
    fx = Fx()
    run_start_rec(fx, T0)
    fx.leg("quad", "api-test", T0 + 10, 10, counts={"failed": 0})
    fx.leg("quad", "acceptance-rev8", T0 + 100, 0, status="skipped", reason="x")      # a zero-length leg
    fx.leg("quad", "api-test", T0 + 200, 10, counts={"failed": 0})
    fx.add("run_end", T0 + 210, reason="deadline", exit=0, cycles=0)
    z = Scn(fx.records(), gap_s=30)
    compare(z, "uptime", "point: ")
    eq([g[2] for g in z.O["up.gaps"]], [80.0, 100.0], "a skipped leg (a point) splits one 180 s gap into 80 s and 100 s")
    fx = Fx()
    run_start_rec(fx, T0)
    fx.leg("quad", "api-test", T0 + 10, 10, counts={"failed": 0})
    fx.leg("quad", "dt-i", T0 + 30, 10, kind="recovery", counts={"checks": 1, "failed": 0})
    fx.add("run_end", T0 + 50, reason="deadline", exit=0, cycles=0)
    hand(Scn(fx.records()), {"up.legs_s": 20.0, "up.card_s": 10.0}, "recovery: ")


def group_telemetry_edges():
    group("telemetry-edges")
    raw = "[xrt] " + "0123456789" * 70
    fx = Fx()
    run_start_rec(fx, T0)
    for k in range(3):
        fx.add("telemetry", T0 + 100 + 60 * k, cycle=None, image=None, when="timer", ok=False, values=None,
               host={"load1": 0.5}, raw=raw if k == 0 else "later raw " + str(k), error="xbutil: no values (rc 1)")
    sn = Scn(fx.records(), now=T0 + 500)
    compare_all(sn, "none parsed: ")
    check("telemetry: 3 samples, none parsed" in sn.T, "'telemetry: 3 samples, none parsed'")
    check(raw[:600] in sn.T and raw[:601] not in sn.T and "later raw" not in sn.T,
          "the first 600 characters of the first raw text are shown, and not a 601st")
    check("device labels" not in sn.T, "no empty device-label table when nothing parsed")
    fx = Fx()
    run_start_rec(fx, T0)
    for k in range(4):
        fx.add("telemetry", T0 + 600 * k, cycle=None, image=None, when="timer", ok=True,
               values={f"L{j:02d}": j * k for j in range(45)}, host=None, raw=None, error=None)
    sb = Scn(fx.records(), now=T0 + 5000)
    compare(sb, "telemetry", "45 labels: ")
    eq((sb.FS["tele.labels_total"], sb.FT["tele.left_out"], len(sb.S["telemetry"]["labels"])), (45, 5, 45),
       "45 labels: all 45 in the data, 5 left out of the text")
    eq(sb.FT["tele.labels"], [f"L{j:02d}" for j in range(44, 4, -1)], "45 labels: the 40 widest range are shown, widest first")


def group_json(base):
    group("json")
    S = base.S
    text = json.dumps(S, allow_nan=False)
    eq(json.loads(text), S, "summarize() equals its own JSON round trip")
    eq(R.render(json.loads(text)), base.T, "render() of the loaded JSON is the same text")

    def walk(x, path="S"):
        bad = []
        if isinstance(x, dict):
            for k, v in x.items():
                bad += ([f"{path} key {k!r}"] if not isinstance(k, str) else []) + walk(v, f"{path}.{k}")
        elif isinstance(x, (list, tuple)):
            bad += ([f"{path} is a tuple"] if isinstance(x, tuple) else [])
            for i, v in enumerate(x):
                bad += walk(v, f"{path}[{i}]")
        elif isinstance(x, float) and not math.isfinite(x):
            bad.append(f"{path} is {x}")
        return bad
    eq(walk(S), [], "no tuple, non-string key or NaN anywhere in the summary")
    check(all(k in S for k in ("input", "header", "totals", "rows", "telemetry", "failures", "sweep", "uptime")), "the summary has every section")


def mutation_catalogue(marks):
    """(name, fn(records), figures that must change). The oracle says what else must."""
    def flip_status(rr):
        find_all(rr, type="leg", image="quad", leg="dt-q8")[2].update(status="fail", rc=1, counts={"checks": 2733, "failed": 3})

    def drop_slice(rr):
        for i, r in enumerate(rr):
            if r["type"] == "leg" and r.get("sweep") and r["sweep"].get("item") == "sqrt32-rne" and r["sweep"].get("lo") == A:
                del rr[i]
                return

    def move_telemetry(rr):
        [x for x in rr if x["type"] == "telemetry" and x.get("values")][5]["values"]["xbutil.temp"] = 100.0

    def shift_deadline(rr):
        for r in rr:
            if r["type"] == "run_start":
                r["deadline"] = box_ts(T0 + 86400 + 3600)

    def move_event(rr):
        r = find(rr, type="event", event="guard_wait", detail="card busy; waited 30 s")
        r["epoch"] -= 500
        r["ts"] = box_ts(r["epoch"])

    def tamper_rate(rr):
        find_all(rr, type="leg", image="quad", leg="dt-q8")[0]["rate"]["value"] = 80.0

    def telemetry_fail(rr):
        [x for x in rr if x["type"] == "telemetry" and x.get("values")][4].update(
            ok=False, values=None, raw="[xrt] nothing", error="xbutil: new failure")

    def unfinished(rr):
        rr.remove([r for r in rr if r["type"] == "cycle_end"][-1])

    def timeout_to_pass(rr):
        r = [x for x in rr if x["type"] == "leg" and x["status"] == "timeout" and x.get("sweep")
             and x["sweep"].get("item") == "sqrt32-rne"][0]
        r.update(status="pass", rc=0, timed_out=False, killed=None, reason=None, rate={"value": 999.0, "unit": "cases/s"},
                 counts={"cases": r["sweep"]["hi"] - r["sweep"]["lo"], "value_mismatches": 0, "flag_mismatches": 0})

    def widen_gap(rr):
        # everything from the cycle after the big gap on starts 100 s later: the gap is 1000 s
        g1 = [r for r in rr if r["type"] == "cycle_start" and r["cycle"] == 9][0]["epoch"]
        for r in rr:
            if r["epoch"] >= g1 and r["type"] in ("leg", "cycle_start", "cycle_end", "run_end"):
                r["epoch"] += 100.0
                r["ts"] = box_ts(r["epoch"])
                if r["type"] == "leg":
                    s, e = r["start_epoch"] + 100.0, r["end_epoch"] + 100.0
                    r.update(start_epoch=s, end_epoch=e, start=box_ts(s), end=box_ts(e))
        rr.sort(key=lambda x: x["epoch"])

    def flip_reach(rr):
        for r in rr:
            if r["type"] == "leg" and r.get("sweep") and r["sweep"].get("item") == "logb32":
                r["sweep"]["reach"] = "tile"

    return [
        ("flip a status (quad dt-q8 #3 pass -> fail)", flip_status,
         ["totals.status.pass", "totals.status.fail", "row[quad/dt-q8].pass", "row[quad/dt-q8].fail", "fail.count", "fail.list"]),
        ("an item's records say it reaches the tile (logb32: host -> tile)", flip_reach,
         ["sweep.exh[logb32].reach", "sweep.total.reach"]),
        ("drop a sweep slice ([1,2) of sqrt32-rne)", drop_slice,
         ["sweep.exh[sqrt32-rne].slices", "sweep.exh[sqrt32-rne].covered", "sweep.exh[sqrt32-rne].intervals",
          "sweep.exh[sqrt32-rne].first_gap", "sweep.completed", "totals.legs", "row[quad/sweep (all items)].runs"]),
        ("move a telemetry value (a temp sample to 100.0)", move_telemetry,
         ["tele.label[xbutil.temp].max", "tele.label[xbutil.temp].mean", "tele.label[xbutil.temp].slope"]),
        ("shift the deadline by an hour", shift_deadline, ["header.deadline", "header.remaining_s"]),
        ("move an event out of the big gap", move_event, ["up.gaps"]),
        ("change one rate (quad dt-q8 #1 to 80.0)", tamper_rate,
         ["row[quad/dt-q8].rate_med", "row[quad/dt-q8].rate_max", "row[quad/dt-q8].trend", "row[quad/dt-q8].series"]),
        ("mark a good telemetry sample ok=false", telemetry_fail,
         ["tele.failed", "tele.with_values", "tele.errors", "tele.label[xbutil.temp].n"]),
        ("a cycle that never ended", unfinished, ["totals.cycles_ended", "totals.unfinished"]),
        ("a timed-out slice completes", timeout_to_pass,
         ["sweep.nc.timeout", "sweep.exh[sqrt32-rne].first_gap", "sweep.exh[sqrt32-rne].covered", "sweep.completed"]),
        ("the big gap grows by 100 s", widen_gap, ["up.gaps", "up.longest_gap_s", "up.wall_s"]),
    ]


def group_controls(base, marks):
    group("controls")
    seen = set()
    for name, fn, expect in mutation_catalogue(marks):
        m = Scn(mutate(base.recs, fn))
        om = changed(base.O, m.O)
        check(set(expect) <= set(om), f"[{name}] the oracle itself moves the figures expected", sorted(set(expect) - set(om)))
        seen |= set(om)
        bad_s, bad_t = mismatches(m.O, m.FS), mismatches(m.O, m.FT)
        check(not bad_s, f"[{name}] summarize() equals the new truth, every figure", bad_s[:6])
        check(not bad_t, f"[{name}] the text equals the new truth, every figure", bad_t[:6])
        check(not (set(m.FS) - set(m.O)) and not (set(m.FT) - set(m.O)), f"[{name}] and carries no figure the truth lacks")
        cs, ct = changed(base.FS, m.FS), changed(base.FT, m.FT)
        check(set(expect) <= set(cs), f"[{name}] summarize() moved the expected figures", sorted(set(expect) - set(cs)))
        check(set(expect) <= set(ct), f"[{name}] the text moved the expected figures", sorted(set(expect) - set(ct)))
        check(set(cs) <= set(om), f"[{name}] summarize() moved nothing the truth did not", sorted(set(cs) - set(om))[:6])
        check(set(ct) <= set(om), f"[{name}] the text moved nothing the truth did not", sorted(set(ct) - set(om))[:6])
    for fam in FAMILIES:
        check(any(in_family(k, fam) for k in seen), f"the catalogue moves at least one {fam} figure")
    a, b = Scn(base.recs, gap_s=300), Scn(base.recs, gap_s=1000)
    eq(changed(a.FS, b.FS), ["up.gaps", "up.gaps_over"], "the gap threshold moves the gap figures in the summary, and only those")
    eq(changed(a.FT, b.FT), ["up.gaps", "up.gaps_over"], "and in the text")


def pick(node, sel):
    if isinstance(sel, tuple):
        kind, want = sel
        if kind == "row":
            return next(x for x in node if f'{x["image"]}/{x["leg"]}' == want)
        return next(x for x in node if x["label" if kind == "label" else "item"] == want)
    return node[sel]


def group_sabotage(base):
    group("sabotage")
    tampers = [
        ("a status count", ["totals", "legs", "by_status", "pass"], lambda v: v + 1, "totals.status.pass"),
        ("the run id", ["header", "run_ids"], lambda v: ["x"], "header.run_id"),
        ("the remaining time", ["header", "deadline", "remaining_s"], lambda v: v + 10, "header.remaining_s"),
        ("a row's runs", ["rows", ("row", "quad/api-test"), "runs"], lambda v: v + 1, "row[quad/api-test].runs"),
        ("a duration median", ["rows", ("row", "quad/dt-q8"), "duration", "median"], lambda v: v + 5, "row[quad/dt-q8].dur_med"),
        ("a rate trend", ["rows", ("row", "quad/dt-q8"), "rate", "trend_pct"], lambda v: v + 3.0, "row[quad/dt-q8].trend"),
        ("a rate series value", ["rows", ("row", "quad/dt-q8"), "rate", "series", 7], lambda v: v + 1, "row[quad/dt-q8].series"),
        ("a telemetry slope", ["telemetry", "labels", ("label", "xbutil.temp"), "slope_per_hour"], lambda v: v * 2,
         "tele.label[xbutil.temp].slope"),
        ("a host mean", ["telemetry", "host", ("label", "host.load1"), "mean"], lambda v: v + 1, "tele.host[host.load1].mean"),
        ("a failure's status", ["failures", "legs", 0, "status"], lambda v: "weird", "fail.list"),
        ("a skipped group's count", ["failures", "skipped", "groups", 0, "count"], lambda v: v + 1, "skip.groups"),
        ("an item's coverage", ["sweep", "exhaustive", ("item", "sqrt32-rne"), "covered"], lambda v: v - A, "sweep.exh[sqrt32-rne].covered"),
        ("an item's first gap", ["sweep", "exhaustive", ("item", "sqrt32-rne"), "first_gap"], lambda v: [0, 5], "sweep.exh[sqrt32-rne].first_gap"),
        ("a disagreement's operand line", ["sweep", "disagreements", 0, "lines"], lambda v: v + ["extra"], "sweep.disagreements"),
        ("the legs union", ["uptime", "legs_union_s"], lambda v: v + 100, "up.legs_s"),
        ("a gap's length", ["uptime", "gaps", 0, "seconds"], lambda v: v + 7, "up.gaps"),
        ("an event count", ["uptime", "events_by_name", "guard_wait"], lambda v: v + 1, "up.events"),
    ]
    for name, path, fn, key in tampers:
        S = copy.deepcopy(base.S)
        node = S
        for step in path[:-1]:
            node = pick(node, step)
        node[path[-1]] = fn(node[path[-1]])
        ms, mt = mismatches(base.O, summary_figs(S)), mismatches(base.O, text_figs(R.render(S)))
        check(key in ms, f"tampered {name}: the summary check names {key}", ms[:4])
        check(key in mt, f"tampered {name}: the text check names {key}", mt[:4])
    check(not mismatches(base.O, summary_figs(base.S)) and not mismatches(base.O, text_figs(base.T)),
          "an untouched summary names nothing")


def group_files(base, marks, tmp):
    group("partial-and-corrupt")
    recs = base.recs
    lines = [json.dumps(r) + "\n" for r in recs]
    full = "".join(lines).encode()
    d = os.path.join(tmp, "partial")
    os.makedirs(d)
    cut = full[:-(len(lines[-1]) // 2)]
    check(not cut.endswith(b"\n"), "the cut file ends mid-line")
    write_bytes(os.path.join(d, "metrics.jsonl"), cut)
    rc, out, err = run_main([d, "--no-write"])
    eq(rc, 0, "partial last line: exit status 0")
    top = out.split("\n")
    check(top[0].startswith("note:") and "partial record" in top[0], "partial last line: noted at the very top", top[:2])
    check("UNPARSABLE" not in out, "partial last line: not called unparsable")
    check("RUNNING: last record" in out, "partial last line: the run_end was the cut line, so the run reads as running")
    f = text_figs(out)
    eq(f["totals.legs"], 85, "partial last line: every complete record is still counted (85 legs)")
    eq((f["totals.cycles_started"], f["totals.cycles_ended"]), (15, 15), "partial last line: and the cycles")
    eq(f["up.run_ends"], [], "partial last line: the cut run_end is not in the data")
    write_bytes(os.path.join(d, "metrics.jsonl"), full)
    rc, out, err = run_main([d, "--no-write"])
    check("partial record" not in out and rc == 0, "a whole file has no partial note")
    # a corrupt line in the middle: named first and loudly, the rest still read
    d2 = os.path.join(tmp, "corrupt")
    os.makedirs(d2)
    k_leg = next(i for i, r in enumerate(recs) if r["type"] == "leg" and r["image"] == "quad" and r["leg"] == "dt-q8")
    k_tel = next(i for i, r in enumerate(recs) if r["type"] == "telemetry")
    bad = list(lines)
    bad[k_leg] = '{"v":1,"type":"leg","image":"quad","leg":"dt-q8","status":\n'
    bad[k_tel] = "this is not json at all\n"
    write_bytes(os.path.join(d2, "metrics.jsonl"), "".join(bad).encode())
    rc, out, err = run_main([d2, "--no-write"])
    eq(rc, 0, "corrupt lines: the report is still made, exit status 0")
    first = out.split("\n")[0]
    check(first.startswith("!!!") and "UNPARSABLE" in first, "corrupt lines: the first line is the warning", first)
    eq(sorted(int(x) for x in re.findall(r"\d+", first.split("number(s):")[1])), sorted([k_leg + 1, k_tel + 1]),
       "corrupt lines: exactly the two line numbers are named")
    check("2 UNPARSABLE" in first, "corrupt lines: and counted")
    f = text_figs(out)
    eq(f["totals.legs"], 84, "corrupt lines: the corrupt leg is not counted (84 legs)")
    eq(f["row[quad/dt-q8].runs"], 7, "corrupt lines: the dt-q8 row has 7 runs")
    eq(f["tele.samples"], 11, "corrupt lines: nor the corrupt telemetry line (11 samples)")
    # corrupt, partial and a blank line, together
    d3 = os.path.join(tmp, "both")
    os.makedirs(d3)
    write_bytes(os.path.join(d3, "metrics.jsonl"), ("".join(bad[:50]) + "\n" + "".join(bad[50:])).encode() + b'{"v":1,"type":"ev')
    rc, out, err = run_main([d3, "--no-write"])
    first = out.split("\n")[0]
    check(rc == 0 and "UNPARSABLE" in first and "partial record" in out, "corrupt and partial together: both said", first)
    nums = sorted(int(x) for x in re.findall(r"\d+", first.split("number(s):")[1]))
    eq(nums, sorted([k_leg + 1 + (1 if k_leg >= 50 else 0), k_tel + 1 + (1 if k_tel >= 50 else 0)]),
       "corrupt and partial together: a blank line moves the numbers, and is not itself corruption")
    S = R.summarize(recs, bad_lines=[7, 99], partial_tail=True)
    t = R.render(S)
    check(t.split("\n")[0].startswith("!!!") and "7, 99" in t.split("\n")[0], "summarize(bad_lines=...) puts them first in the text")
    check("partial record" in t, "summarize(partial_tail=True) notes it")
    eq(S["input"]["bad_lines"], [7, 99], "and in the data")
    S = R.summarize(recs, bad_lines=list(range(1, 251)))
    check("... and 150 more" in R.render(S).split("\n")[0], "250 bad lines: the first 100 are named and the rest counted")
    eq(len(S["input"]["bad_lines"]), 250, "and all 250 are in the data")


def build_reach_run():
    """A one-cycle run of the sweep items whose `reach` is the question: the new exhaustive conversion and scaleB items
    (records that say what they covered), a record with no `reach` and an op the table names, a record with no `reach`
    and an op it does not, an invalid `reach`, and a `reach` that contradicts the table."""
    fx = Fx()
    run_start_rec(fx, T0)
    t = fx.begin_cycle(T0 + 5, "quad", 1, 3)
    t = fx.battery(t, "quad", [dict(name="api-test", dur=10, counts={"failed": 0})])
    t = fx.wave(t, "quad", [job_ex("conv32to64-all", 0, 2), job_ex("scaleb32-wide-rne", 0, 1),
                            job_rd("rem32", 0, 100000), job_rd("futureop-x", 0, 100)])
    t = fx.wave(t, "quad", [job_ex("cvtfrom32-all-rne", 0, 1), job_rd("conv32to64", 0, 50000),
                            job_ex("conv32to64-all", 2, 3)])
    fx.end_cycle(t)
    fx.add("run_end", t + 10, reason="deadline", exit=0, cycles=1)
    return fx.records()


def group_reach():
    group("reach")
    recs = build_reach_run()
    scn = Scn(recs)
    compare_all(scn)
    hand(scn, {
        "sweep.exh": ["conv32to64-all", "cvtfrom32-all-rne", "scaleb32-wide-rne"],
        # the record says host / tile; "fast" is not a reach, so the table's host for the op
        "sweep.exh[conv32to64-all].reach": "host", "sweep.exh[scaleb32-wide-rne].reach": "tile",
        "sweep.exh[cvtfrom32-all-rne].reach": "host",
        "sweep.exh[conv32to64-all].covered": 3 * A, "sweep.exh[conv32to64-all].intervals": 1,
        "sweep.exh[conv32to64-all].cases": 3 * A, "sweep.exh[scaleb32-wide-rne].cases": 568 * A,
        "sweep.exh[cvtfrom32-all-rne].cases": 2 * A,
        "sweep.total.reach": [("tile", 1, A, EXH, A / EXH * 100, 0), ("host", 2, 4 * A, 2 * EXH, 4 * A / (2 * EXH) * 100, 0)],
        # no `reach` and an op the table names (rem32: host), no `reach` and an op it does not (unknown), and a record
        # that says tile of an op the table says host (conv32to64: the record wins)
        "sweep.rand": ["conv32to64", "futureop-x", "rem32"],
        "sweep.rand[rem32].reach": "host", "sweep.rand[futureop-x].reach": "unknown",
        "sweep.rand[conv32to64].reach": "tile",
        "sweep.rand.reach": [("tile", 1), ("host", 1), ("unknown", 1)],
    })
    # the records the new driver writes: what the items covered rides in counts and in the sweep
    wide = [r for r in recs if r.get("type") == "leg" and (r.get("sweep") or {}).get("item") == "scaleb32-wide-rne"][0]
    eq((wide["counts"]["encodings"], wide["counts"]["skipped"], wide["sweep"]["expected_encodings"],
        wide["sweep"]["expected_cases"], wide["sweep"]["reach"]), (A, 0, A, 568 * A, "tile"),
       "the synthetic wide-item record has the shape the driver writes")
    t = scn.T
    check("  reach tile: 1 exhaustive item(s) seen; covered " + str(A) + " of " + str(EXH) in t, "the text has a tile line")
    check("  reach host: 2 exhaustive item(s) seen; covered " + str(4 * A) + " of " + str(2 * EXH) in t, "the text has a host line")
    check("  random reach: tile 1 item(s), host 1 item(s), unknown 1 item(s)" in t, "the text has the random items' reach")
    check("  a host item is libcft's host code run against the CPU: a full-space test of the library in which the tile "
          "computes nothing" in t, "the text says what a host item is")
    check("  an unknown item has no `reach` in its records and an op the catalog's table does not name" in t,
          "the text says what an unknown item is")
    check(not any(ln.startswith("  reach unknown:") for ln in t.split("\n")),
          "no 'reach unknown' line for exhaustive items when none is unknown")
    # a run of the whole old kind: no record says anything, every op is in the table
    old = mutate(recs, lambda rr: [r["sweep"].pop("reach", None) for r in rr if r.get("type") == "leg" and r.get("sweep")])
    so = Scn(old)
    compare_all(so)
    eq(so.FS["sweep.exh[scaleb32-wide-rne].reach"], "tile", "records from before the driver wrote `reach` are read off the op: scaleb32-wide is tile")
    eq(so.FS["sweep.rand[conv32to64].reach"], "host", "... and with the record's contradiction gone the table's host stands")
    eq(changed(scn.FS, so.FS), ["sweep.rand.reach", "sweep.rand[conv32to64].reach"],
       "only the one item whose record contradicted the table moves when the records' `reach` is removed")


def group_weird(base):
    group("weird")
    fx = Fx()
    run_start_rec(fx, T0, deadline=T0 + 5000)
    fx.leg("quad", "api-test", T0 + 10, 5, counts={"failed": 0})
    recs = fx.records()
    recs[0]["deadline"] = "next tuesday"
    nan = float("nan")

    def rec(typ, e, **kw):
        return dict({"v": 1, "type": typ, "ts": box_ts(T0 + e), "epoch": float(T0 + e)}, **kw)
    extra = [
        rec("leg", 30, image="quad", leg="dt-q8", kind="battery"),
        rec("leg", 31, image="quad", leg="dt-i", kind="battery", status="pass", start_epoch=None, end_epoch=None,
            duration_s=nan, counts="oops", rate={"value": "fast", "unit": "x"}),
        rec("leg", 33, image="quad", leg="sweep-x", kind="sweep", status="pass", start_epoch=float(T0 + 26),
            end_epoch=float(T0 + 27), duration_s=1.0, counts={"cases": 5}, sweep={"item": "bad-range", "lo": 5, "hi": 3}),
        rec("leg", 36, image="quad", leg="a" * 80 + "\nHEADING", kind="battery", status="fail", start_epoch=float(T0 + 36),
            end_epoch=float(T0 + 37), reason="line one\n== FAILURES ==\nline three " + "z" * 600, counts={"failed": 3}),
        rec("telemetry", 40, when="timer", ok=True, values={"a": "x", "b": nan, "c": True, "d": 5}, host="weird"),
        rec("event", 42), rec("mystery", 43), {"v": 1, "ts": box_ts(T0 + 45), "epoch": float(T0 + 45)},
    ]
    try:
        S = R.summarize(recs + extra + [7, "text", [1, 2]], now=T0 + 100)
        t = R.render(S)
        json.dumps(S, allow_nan=False)
    except Exception as e:                      # the point: odd records must never crash the report
        check(False, "odd records crash the report", repr(e))
        return
    check(True, "odd records do not crash summarize() or render(), and the summary is valid JSON")
    eq(S["input"]["non_object"], 3, "three non-object lines counted")
    check(S["header"]["deadline"]["remaining_s"] is None and "remaining time n/a (deadline not understood)" in t,
          "an unparseable deadline: no remaining time, and said so")
    eq(S["totals"]["legs"]["by_status"].get("(missing)"), 1, "a leg with no status is counted as (missing)")
    eq(S["uptime"]["legs_unusable"], 2, "legs without a usable start and end are in no union")
    eq([m["item"] for m in S["sweep"]["malformed"]], ["bad-range"], "a completed sweep leg with an impossible range is named and left out")
    eq(S["telemetry"]["labels_total"], 1, "only a numeric telemetry value is a label")
    check(sum(1 for ln in t.split("\n") if ln == "== FAILURES ==") == 1, "a reason with a section heading in it cannot forge one")
    check(not any(ln.startswith("HEADING") for ln in t.split("\n")), "a newline in a leg name cannot start a line")
    eq(S["totals"]["records"].get("mystery"), 1, "a record of an unknown type is counted")


def group_cli(base, marks, tmp):
    group("cli")
    recs = base.recs
    d = os.path.join(tmp, "good")
    os.makedirs(d)
    mpath = os.path.join(d, "metrics.jsonl")
    write_metrics(mpath, recs)
    before = read_text(mpath)
    jpath = os.path.join(tmp, "out.json")
    rc, out, err = run_cli([d, "--json", jpath])
    eq((rc, err), (0, ""), "the script, run isolated (-I) as a subprocess, exits 0 and writes nothing to stderr")
    rpt = os.path.join(d, "report.txt")
    eq(read_text(rpt), out, "report.txt holds exactly what stdout got")
    eq(out, base.T, "the subprocess's text is render(summarize(records)) for an ended run")
    eq(read_text(mpath), before, "metrics.jsonl is untouched")
    with open(jpath, "r", encoding="utf-8") as fh:
        loaded = json.load(fh)
    eq(loaded, base.S, "--json holds the summary: the same figures as data")
    eq(R.render(loaded), out, "and the text can be rebuilt from the file")
    eq(sorted(os.listdir(d)), ["metrics.jsonl", "report.txt"], "the run directory holds only those two files")
    write_bytes(rpt, b"OLD REPORT\n")
    rc, out2, _ = run_cli([d])
    check(rc == 0 and read_text(rpt) == out2, "report.txt is overwritten each time")
    os.remove(rpt)
    rc, out3, _ = run_cli([d, "--no-write"])
    check(rc == 0 and not os.path.exists(rpt) and out3 == out, "--no-write: no report.txt, the same text on stdout")
    rc, out4, _ = run_cli([d, "--no-write", "--gap-seconds", "1000"])
    check(rc == 0 and line_re(out4, r"^gaps > 1000 s\s*: 0$"), "--gap-seconds 1000: no gap listed")
    check(run_cli([d, "--gap-seconds", "-1"])[0] == 2, "--gap-seconds -1 is a usage error, status 2")
    d4 = os.path.join(tmp, "running")
    os.makedirs(d4)
    write_metrics(os.path.join(d4, "metrics.jsonl"), [r for r in recs if r["type"] != "run_end"])
    rc, out6, _ = run_cli([d4, "--no-write"])
    m = re.search(r"RUNNING: last record (\S+ \S+), (\d+) s ago", out6)
    check(rc == 0 and m is not None and int(m.group(2)) > 10 ** 7, "a run with no run_end says RUNNING and its age")
    de = os.path.join(tmp, "empty")
    os.makedirs(de)
    write_bytes(os.path.join(de, "metrics.jsonl"), b"")
    rc, out7, err = run_cli([de])
    check(rc == 2 and out7 == "" and "empty" in err and "metrics.jsonl" in err, "an empty metrics.jsonl: status 2, 'empty' on stderr", (rc, err))
    check(not os.path.exists(os.path.join(de, "report.txt")), "and no report.txt is written")
    dm = os.path.join(tmp, "nofile")
    os.makedirs(dm)
    rc, out8, err = run_cli([dm])
    check(rc == 2 and out8 == "" and "metrics.jsonl" in err and "does not exist" in err, "no metrics.jsonl: status 2, 'does not exist'", (rc, err))
    rc, _, err = run_cli([os.path.join(tmp, "nodir")])
    check(rc == 2 and "not a directory" in err, "no such directory: status 2, 'not a directory'", (rc, err))
    dg = os.path.join(tmp, "guard")
    os.makedirs(dg)
    write_metrics(os.path.join(dg, "metrics.jsonl"), recs)
    write_bytes(os.path.join(dg, "report.txt"), b"STALE\n")
    real = R.render

    def boom(summary):
        raise RuntimeError("synthetic failure")
    R.render = boom
    try:
        rc, _, err = run_main([dg])
    finally:
        R.render = real
    check(rc == 3 and "the report itself failed: RuntimeError: synthetic failure" in err, "a bug in the report: status 3, the message on stderr", (rc, err[-200:]))
    t = read_text(os.path.join(dg, "report.txt"))
    check("STALE" not in t and "the report itself failed" in t, "and report.txt no longer shows a stale account")


# ---------------------------------------------------------------------------
# parcel RG (2026-10-22): a tree the run did not record, read from its commit
# ---------------------------------------------------------------------------

GM = 1 << 20
TI, HI = "scaleb32-all-rne", "conv32to64-all"          # a tile item and a host item of the catalog
REAL_THREE_NIGHT = "de4ee37900917762e4ba071d434eb28204f92fed6c5056e88a70ccce6516e986"       # the lead's three nights (1,910 records), by sha256


def skip(what, why):
    print(f"  SKIP  [{_st['g']}] {what} - {why}")
    sys.stdout.flush()


def rmtree_force(path):
    """shutil.rmtree that also removes read-only files: a git repository's objects are, and ignore_errors=True leaves them on Windows."""
    def fix(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    try:
        shutil.rmtree(path, **({"onexc": fix} if sys.version_info >= (3, 12) else {"onerror": fix}))
    except OSError:
        pass


class Ck:
    """Checks collected, not yet counted: a family runs on the real summary (hold) and again on one made with a defect put in (plant),
    where the check named for the defect must fail - a check that cannot fail is worth nothing."""

    def __init__(self):
        self.res = []

    def __call__(self, ok, what, detail=None):
        self.res.append((bool(ok), what, detail))

    def eq(self, got, want, what):
        self(got == want, what, f"got {_short(got)}, want {_short(want)}")


def hold(fn, *a):
    ck = Ck()
    fn(ck, *a)
    for ok, what, detail in ck.res:
        check(ok, what, detail)


def plant(fn, defect, named, *a):
    """fn(ck, *a), `a` made with `defect` put in: the check that begins `named` must fail."""
    ck = Ck()
    fn(ck, *a)
    red = [w for ok, w, _ in ck.res if not ok]
    check(any(w.startswith(named) for w in red), f"plant, {defect}: the check '{named}...' fails", red[:2])


@contextlib.contextmanager
def patched(**kw):
    old = {k: getattr(R, k) for k in kw}
    for k, v in kw.items():
        setattr(R, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            setattr(R, k, v)


def g_start(tree):
    return {"type": "run_start", "v": 1, "epoch": T0, "ts": box_ts(T0), "run_id": "git-run", "tree": tree}


def g_leg(item, lo, hi, reach, image):
    return {"type": "leg", "v": 1, "epoch": T0, "kind": "sweep", "status": "pass", "image": image, "leg": "sweep-" + item,
            "counts": {"cases": hi - lo}, "sweep": {"item": item, "op": item.split("-")[0], "reach": reach, "lo": lo, "hi": hi}}


class GitFx:
    """A scratch git repository of three real commits: c1 and c2 share rtl/ and differ in host/ (as 881bbcb and 0b7c959 do), c3 changes rtl/."""

    def __init__(self, tmp):
        self.repo = os.path.join(tmp, "git-repo")
        os.makedirs(self.repo)
        self.git("init", "-q")
        self.c = []
        for k, (rtl, host) in enumerate((("v1", "h1"), ("v1", "h2"), ("v2", "h2"))):
            for rel, txt in (("rtl/a.sv", rtl), ("host/h.c", host)):
                os.makedirs(os.path.join(self.repo, os.path.dirname(rel)), exist_ok=True)
                write_bytes(os.path.join(self.repo, rel), (txt + "\n").encode())
            self.git("add", "-A")
            self.git("commit", "-qm", f"c{k + 1}")
            self.c.append(self.git("rev-parse", "HEAD"))
        self.t = {(c, d): self.git("rev-parse", f"{c}:{d}") for c in self.c for d in ("rtl", "host")}
        self.A, self.B, self.H1, self.H2 = self.t[(self.c[0], "rtl")], self.t[(self.c[2], "rtl")], self.t[(self.c[0], "host")], self.t[(self.c[1], "host")]
        # a run that recorded all of its tree, at c2; and one from before 2026-10-20, at c1, that recorded none
        self.rec = {"commit": self.c[1], "dirty": False, "dirty_files": 0, "rtl": self.A, "rtl_dirty": False, "host_src": self.H2,
                    "host_src_dirty": False, "cc": "gcc 11.4"}
        self.old = {"commit": self.c[0], "dirty": False, "dirty_files": 0}

    def git(self, *a):
        p = subprocess.run(["git", "-c", "user.name=report-test", "-c", "user.email=report-test@example.invalid", "-c", "commit.gpgsign=false",
                            "-C", self.repo] + list(a), capture_output=True, text=True, timeout=60)
        if p.returncode != 0:
            raise RuntimeError(f"git {' '.join(a)}: {p.stderr.strip()[:200]}")
        return p.stdout.strip()

    def runs(self, second):
        """The first run recorded its tree, the second is `second`; each did one slice of a tile item and one of a host item, side by side."""
        return [g_start(self.rec), g_leg(TI, 0, GM, "tile", "quad"), g_leg(HI, 0, GM, "host", "cpu"),
                g_start(second), g_leg(TI, GM, 2 * GM, "tile", "single"), g_leg(HI, GM, 2 * GM, "host", "cpu")]


NO_CLASS = {"exhaustive": [{}], "derived_from_git": None, "label": ""}


def kclasses(S, kind):
    return [c for c in S["sweep"]["trees"]["classes"] if c["kind"] == kind]


def kkey(cs, key):
    return next((c for c in cs if c["key"] == key), None)


def ck_derived(ck, S, fx, twin):
    """The second run recorded no tree and its clean commit is in the checkout: it is in the class of the tree, and says so."""
    A, c1 = fx.A, fx.c[0]
    tc, hc = kclasses(S, "tile"), kclasses(S, "host")
    ck.eq([c["key"] for c in tc], [A], "derived: one tile class, the tree the first run recorded and the second did not")
    ta = kkey(tc, A) or NO_CLASS
    e = ta["exhaustive"][0]
    ck((e.get("covered"), e.get("slices"), e.get("by_image")) == (2 * GM, 2, {"quad": GM, "single": GM}),
       "derived: the second run's slice is counted in it, beside the first run's", e)

    def strip(c):
        return {k: v for k, v in (c or {}).items() if k not in ("label", "derived_from_git")}
    ck(strip(kkey(kclasses(twin, "tile"), A)) == strip(kkey(tc, A)) != {},
       "derived: it is the very class a run that RECORDED that tree is in (every field but label and derived_from_git)")
    ck.eq(ta["derived_from_git"], [{"commit": c1, "dir": "rtl", "tree": A}], "derived: derived_from_git gives the commit, the directory and the tree read")
    ck("read from git" in ta["label"] and c1[:12] in ta["label"] and A[:12] in ta["label"],
       "derived: the label says 'read from git', at which commit, for which tree", ta["label"])
    hk = f"{fx.H1}|compiler not recorded"
    ck.eq(sorted(c["key"] for c in hc), sorted([f"{fx.H2}|gcc 11.4", hk]),
          "derived: the host items are two classes: the second run's host/ tree is read from git, its compiler never")
    hb = kkey(hc, hk) or NO_CLASS
    ck.eq(hb["derived_from_git"], [{"commit": c1, "dir": "host", "tree": fx.H1}], "derived: the host class's derived_from_git gives its commit and tree")
    ck("read from git" in hb["label"] and "compiler not recorded" in hb["label"], "derived: and its label says both", hb["label"])
    ck.eq((kkey(hc, f"{fx.H2}|gcc 11.4") or NO_CLASS)["derived_from_git"], [], "derived: a class of a run that recorded its tree has an empty derived_from_git")


def ck_many(ck, S, fx, rev, many):
    """A resumed run (a second run_start at one commit) is ONE entry of derived_from_git, a run at another commit a second."""
    ta = kkey(kclasses(S, "tile"), fx.A) or NO_CLASS
    c1, c2 = fx.c[0][:12], fx.c[1][:12]
    ck.eq([(d["commit"][:12], d["dir"]) for d in ta["derived_from_git"]], [(c1, "rtl"), (c2, "rtl")],
          "many: two run_starts at one commit and one at another give two derived_from_git entries, in the order first used")
    ck("commits" in ta["label"] and c1 in ta["label"] and c2 in ta["label"], "many: and the label names both commits", ta["label"])
    with patched(LABEL_COMMITS=1):
        lab = R.summarize(many, rev=rev)["sweep"]["trees"]["classes"][0]["label"]
    ck(c1 in lab and "and 1 more" in lab and c2 not in lab, "many: and names at most LABEL_COMMITS of them, the rest as a count", lab)


def ck_apart(ck, S, fx, commit, why, what):
    """The second run's tree cannot be had from git: its slice is a class of its own, by its commit, and the label says why."""
    tc = kclasses(S, "tile")
    ka = kkey(tc, "unrecorded:" + commit)
    ck(ka is not None, f"{what}: the second run is a class of its own, kept apart by its commit", [c["key"][:20] for c in tc])
    ka = ka or NO_CLASS
    ck(why in ka["label"] and commit[:12] in ka["label"], f"{what}: its label gives the reason ({why})", ka["label"])
    ck("read from git" not in ka["label"] and ka["derived_from_git"] == [], f"{what}: and nothing is read from git for it", ka["derived_from_git"])
    ta = kkey(tc, fx.A) or NO_CLASS
    ck(ta["exhaustive"][0].get("covered") == GM, f"{what}: the first run's class holds the first run's slice alone", ta["exhaustive"][0])


class FakeProc:
    """Stands in for the subprocess module inside the report: counts what it is asked, and answers, fails or is slow as told."""
    TimeoutExpired = subprocess.TimeoutExpired

    def __init__(self, out="a" * 40, rc=0, exc=None, delay=0.0):
        self.out, self.rc, self.exc, self.delay, self.calls = out, rc, exc, delay, []

    def run(self, argv, **kw):
        self.calls.append((list(argv), kw))
        if self.delay:
            time.sleep(self.delay)
        if self.exc:
            raise self.exc
        return type("P", (), {"returncode": self.rc, "stdout": self.out + "\n", "stderr": ""})()


class Uncached(R.GitTrees):
    def __call__(self, commit, rel):
        self.seen.clear()
        return super().__call__(commit, rel)


class Persistent(R.GitTrees):
    def _git(self, *args):
        self.problem = None
        return super()._git(*args)


def ck_kept(ck, cls):
    """git is asked once for each (commit, directory), by the driver's own command, with a timeout."""
    b, fake = "b" * 40, FakeProc()
    with patched(subprocess=fake):
        g = cls("/x")
        got = [g(b, "rtl"), g(b, "rtl"), g(b, "host"), g(b, "rtl"), g("c" * 40, "rtl"), g("abc", "rtl")]
    ck.eq(got, ["a" * 40] * 5 + [None], "git: the answer is the tree git printed; a commit that is not a whole hash is None")
    ck.eq(len(fake.calls), 3, "git: kept per (commit, directory): six asks for three pairs run git three times, a non-hash never")
    ck.eq(fake.calls[0][0], ["git", "-C", "/x", "rev-parse", f"{b}:rtl"], "git: the command is `git -C ROOT rev-parse COMMIT:REL`, the driver's own")
    ck(all(0 < kw.get("timeout", 0) <= R.GIT_TIMEOUT_S for _, kw in fake.calls), "git: every lookup carries a timeout of at most GIT_TIMEOUT_S",
       [kw.get("timeout") for _, kw in fake.calls])


def ck_stops(ck, cls):
    """A git that does not answer in time stops them: it is asked once, and the label and the summary say it was not asked, not that the commit is absent."""
    b, fake = "b" * 40, FakeProc(exc=subprocess.TimeoutExpired("git", 10))
    recs = [g_start({"commit": b, "dirty": False, "dirty_files": 0}), g_leg(TI, 0, GM, "tile", "quad")]
    with patched(subprocess=fake):
        g = cls("/x")
        S = R.summarize(recs, rev=g)
        again = g("e" * 40, "host")
    ck(len(fake.calls) == 1 and again is None, "git stops: the lookup git does not answer in time is the only one run; the next is not", len(fake.calls))
    ck("did not answer within" in (g.problem or ""), "git stops: and `problem` says so by name", g.problem)
    lab = (kclasses(S, "tile") or [NO_CLASS])[0]["label"]
    ck(g.problem and g.problem in lab and S["sweep"]["trees"]["git"] == {"read": True, "problem": g.problem},
       "git stops: the class's label and the summary carry it (unread, not absent)", lab)


def ck_agree(ck, recs, tree_now, rev, S, what):
    """The report's coverage in the classes a resuming run at `tree_now` is in equals what card_stress_lib.count_slices - the driver's resume -
    counts from the same records with the same rev: per item, the slices, the cases, and the covered encodings (exhaustive) or highest seed_n."""
    now = LIB.run_classes(tree_now)
    counted, tally = LIB.count_slices(recs, now, rev)
    iv, served, cases, seeds, _dis = LIB.sweep_coverage(counted)
    bad = []
    for reach in (LIB.TILE, LIB.HOST):
        key, unknown = now[reach]
        want = {r["sweep"]["item"]: (served[r["sweep"]["item"]], cases[r["sweep"]["item"]],
                                     LIB.covered(iv[r["sweep"]["item"]]) if r["sweep"]["item"] in iv else seeds.get(r["sweep"]["item"]))
                for r in counted if LIB.slice_reach(r["sweep"]) == reach}
        c = kkey(kclasses(S, reach), key) or {}
        got = {e["item"]: (e["slices"], e["cases"], e["covered"]) for e in c.get("exhaustive", [])}
        got.update({e["item"]: (e["slices"], e["cases"], e["max_seed_n"]) for e in c.get("random", [])})
        if unknown is not None or got != want:
            bad.append(f"{reach} {key[:24]}: unknown {unknown}; the report has {sorted(got.items())[:2]}, the resume counts {sorted(want.items())[:2]}")
    ck(not bad, f"{what}: the report's coverage in the resuming run's classes equals what the resume counts, item by item", bad[:2])
    ck(tally["counted"][LIB.TILE] > 0, f"{what}: and the resume counted tile slices there (the comparison is not empty)", tally["counted"])
    return tally


def cli_checks(fx, tmp):
    """The command line, from a copy of the report placed in hw/ of the scratch repository (its own checkout) and in a directory that is none."""
    run = os.path.join(tmp, "git-cli-run")
    os.makedirs(run)
    write_metrics(os.path.join(run, "metrics.jsonl"), fx.runs(fx.old))
    jp = os.path.join(tmp, "git-cli.json")

    def go(root, *extra):
        os.makedirs(os.path.join(root, "hw"), exist_ok=True)
        for f in ("card_stress_report.py", "card_stress_lib.py"):
            shutil.copyfile(os.path.join(HW, f), os.path.join(root, "hw", f))
        p = subprocess.run([sys.executable, "-B", "-I", os.path.join(root, "hw", "card_stress_report.py"), run, "--no-write", "--json", jp]
                           + list(extra), capture_output=True, text=True, timeout=120, cwd=tmp)
        try:
            with open(jp, encoding="utf-8") as fh:
                js = json.load(fh)
            os.remove(jp)
        except (OSError, ValueError):
            js = {"sweep": {"trees": {"classes": [], "git": {}}}}
        return p, js["sweep"]["trees"]

    def reads(ck, pj):
        p, T = pj
        tk = [c for c in T["classes"] if c["kind"] == "tile"]
        ck(p.returncode == 0 and [c["key"] for c in tk] == [fx.A] and tk[0]["derived_from_git"] == [{"commit": fx.c[0], "dir": "rtl", "tree": fx.A}],
           "cli: by default the report reads git of the repository that holds ITS hw/ (a scratch one, run from elsewhere): the tree is derived",
           (p.returncode, [c["key"][:12] for c in tk], p.stderr[-120:]))
        ck(f"(read from git at commit {fx.c[0][:12]})" in p.stdout and T["git"] == {"read": True, "problem": None},
           "cli: and the text says 'read from git' at that commit, and sweep.trees.git says git was read and nothing stopped it")

    def apart(ck, pj):
        ck(f"unrecorded:{fx.c[0]}" in [c["key"] for c in pj[1]["classes"] if c["kind"] == "tile"], "cli: --no-git keeps it apart")

    here = go(fx.repo)
    hold(reads, here)
    plain = os.path.join(tmp, "git-plain")
    os.makedirs(plain)
    if subprocess.run(["git", "-C", plain, "rev-parse", "--git-dir"], capture_output=True, text=True, timeout=60).returncode == 0:
        skip("cli: the report in a directory that is no repository", "the temporary directory is inside a repository")
    else:
        outside = go(plain)
        tk = [c for c in outside[1]["classes"] if c["kind"] == "tile"]
        check(f"unrecorded:{fx.c[0]}" in [c["key"] for c in tk] and all(c["derived_from_git"] == [] for c in tk)
              and "not a git repository" in (outside[1]["git"].get("problem") or "") and "not a git repository" in outside[0].stdout,
              "cli: a copy in a directory that is no repository derives nothing, and says so by name (sweep.trees.git.problem and the text)",
              [c["key"][:12] for c in tk])
        plant(reads, "the report reading no checkout", "cli: by default the report reads git", outside)
    nog = go(fx.repo, "--no-git")
    hold(apart, nog)
    check(nog[0].returncode == 0 and "git was not read (--no-git)" in nog[0].stdout and nog[1]["git"] == {"read": False, "problem": None}
          and all(c["derived_from_git"] == [] for c in nog[1]["classes"]), "cli: --no-git is today's record-only view; the text and the summary say git was not read")
    plant(apart, "the flag ignored", "cli: --no-git keeps it apart", here)


def real_copy_checks():
    """The agreement on a real file: CARD_STRESS_RESUME_RUN names a directory holding a copy of the lead's stress run (metrics.jsonl)."""
    run = os.environ.get("CARD_STRESS_RESUME_RUN")
    mp = os.path.join(run or "", "metrics.jsonl")
    what = "the report against the resume's count on a real file"
    if not run or not os.path.isfile(mp):
        skip(what, "CARD_STRESS_RESUME_RUN does not name a run directory holding a metrics.jsonl (the lead's box/nightly-1021/run)")
        return
    recs = LIB.read_records(mp)[0]
    checkout = os.path.dirname(HW)
    head = subprocess.run(["git", "-C", checkout, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=60).stdout.strip()
    if not LIB.GIT_HASH.fullmatch(head):
        skip(what, "this checkout is not a git repository")
        return
    rev = R.GitTrees(checkout)
    S = R.summarize(recs, rev=rev)
    starts = [r["tree"] for r in recs if r.get("type") == "run_start" and isinstance(r.get("tree"), dict)]
    here = {"commit": head, "dirty": False, "rtl": rev(head, "rtl"), "rtl_dirty": False, "host_src": rev(head, "host"), "host_src_dirty": False,
            "cc": starts[-1].get("cc")}
    hold(lambda ck: (ck_agree(ck, recs, starts[-1], rev, S, "real file, at the file's last run_start"),
                     ck_agree(ck, recs, here, rev, S, "real file, at this checkout's HEAD")))
    plant(lambda ck, s: ck_agree(ck, recs, starts[-1], rev, s, "real file, at the file's last run_start"), "the report not reading git while the resume does",
          "real file, at the file's last run_start: the report's coverage", R.summarize(recs, rev=None))
    first = starts[0].get("commit")
    with open(mp, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    if sha != REAL_THREE_NIGHT or not rev(first, "rtl"):
        skip("the lead's three nights: night 1's slices in the current trees' classes", "the file is not the lead's three-night copy (sha256), or "
             "this checkout does not hold night 1's commit")
        return
    cur = rev(first, "rtl")

    def done(summary):
        return sorted(e["item"] for e in (kkey(kclasses(summary, "tile"), cur) or {}).get("exhaustive", []) if e["item"].startswith("scaleb32-all-") and e["complete"])
    eq(done(S), ["scaleb32-all-" + m for m in ("rdn", "rne", "rtz", "rup")], "real file: the four scaleb32-all items are complete in the current RTL tree's class")
    eq(done(R.summarize(recs, rev=None)), [], "real file: and without git they are not (night 1's slices are in a class of their own)")
    hk = [c for c in kclasses(S, "host") if c["key"].startswith(rev(first, "host"))]
    check(len(hk) == 1 and "read from git" in hk[0]["label"] and rev(head, "host") != rev(first, "host"),
          "real file: night 1's host slices are in the class of ITS host/ tree, which is not this checkout's", [c["label"][:60] for c in hk])


def group_git(tmp):
    group("git-trees")
    try:
        fx = GitFx(tmp)
    except (OSError, RuntimeError) as e:
        skip("the trees read from git", f"no scratch git repository can be made here ({e})")
        return
    c1, c2, c3, A = fx.c[0], fx.c[1], fx.c[2], fx.A
    check(fx.t[(c2, "rtl")] == A != fx.B == fx.t[(c3, "rtl")] and fx.H1 != fx.H2 == fx.t[(c3, "host")],
          "the scratch repository has the shape the tests assume: c1 and c2 share rtl/, host/ differs between them, c3 changes rtl/")
    rev = R.GitTrees(fx.repo)
    # 1. no tree recorded, a clean commit that is in the checkout: the class of a run that recorded that tree
    twin = R.summarize(fx.runs(dict(fx.old, rtl=A, rtl_dirty=False)), rev=rev)
    S = R.summarize(fx.runs(fx.old), rev=rev)
    hold(ck_derived, S, fx, twin)
    plant(ck_derived, "git not read (the report before parcel RG)", "derived: one tile class", R.summarize(fx.runs(fx.old), rev=None), fx, twin)
    # every caller that passes nothing gets what the command line shows; a callable is used as given
    check(R.checkout_git() is R.checkout_git() and R.checkout_git().root == os.path.dirname(HW),
          "default: the rev summarize() takes when given none is ONE GitTrees on the repository that holds hw/, shared by every call")
    with patched(_checkout_git=rev):
        dflt = R.summarize(fx.runs(fx.old))
    fn = R.summarize(fx.runs(fx.old), rev=lambda c, r: fx.t.get((c, r)))
    check(kclasses(dflt, "tile") == kclasses(S, "tile") == kclasses(fn, "tile") and kclasses(dflt, "host") == kclasses(S, "host") == kclasses(fn, "host"),
          "default and callable: summarize() with no rev, and with a function that answers as git does, give the classes an explicit GitTrees gives")
    many = fx.runs(fx.old) + [g_start(fx.old), g_leg(TI, 2 * GM, 3 * GM, "tile", "quad"), g_start(dict(fx.old, commit=c2)), g_leg(TI, 3 * GM, 4 * GM, "tile", "quad")]
    Sm = R.summarize(many, rev=rev)
    hold(ck_many, Sm, fx, rev, many)
    twice = copy.deepcopy(Sm)
    for cl in kclasses(twice, "tile"):
        if cl["key"] == A:
            cl["derived_from_git"].append({"commit": c1, "dir": "rtl", "tree": A})
    plant(ck_many, "a run's tree listed twice", "many: two run_starts", twice, fx, rev, many)
    # 2. what git cannot say is kept apart, by commit, with the reason

    def dirty_blind(t):               # a report that takes every checkout for a clean one
        res, cls = R.resolve_tree, R.run_classes
        with patched(resolve_tree=lambda tr, rv=None: res(dict(tr or {}, dirty=False), rv),
                     run_classes=lambda tr, rv=None: cls(dict(tr or {}, dirty=False), rv)):
            return R.summarize(fx.runs(t), rev=rev)
    absent, contra = "d" * 40, dict(fx.old, rtl="e" * 40, rtl_dirty=False, host_src=fx.H1, host_src_dirty=False, cc="gcc 11.4")
    for what, tree, commit, why, defect, bad in (
            ("absent", dict(fx.old, commit=absent), absent, "is not in this checkout", "a git that finds every commit",
             lambda t: R.summarize(fx.runs(t), rev=lambda c, r: fx.t[(c1, r)])),
            ("dirty", dict(fx.old, dirty=True, dirty_files=3), c1, "was not recorded clean", "a dirty checkout taken for clean", dirty_blind),
            ("contradicted", contra, c1, "which git does not give for its commit", "a git that never answers, so the recorded tree is trusted",
             lambda t: R.summarize(fx.runs(t), rev=lambda c, r: None))):
        Sx = R.summarize(fx.runs(tree), rev=rev)
        hold(ck_apart, Sx, fx, commit, why, what)
        plant(ck_apart, defect, f"{what}: the second run is a class of its own", bad(tree), fx, commit, why, what)
        check(Sx["sweep"]["trees"]["git"] == {"read": True, "problem": None}, f"{what}: git itself had no problem (an absent commit or a refusal is an answer)")
    Sc = R.summarize(fx.runs(contra), rev=rev)
    check("RTL tree unknown" in (kkey(kclasses(Sc, "tile"), "unrecorded:" + c1) or NO_CLASS)["label"]
          and (kkey(kclasses(Sc, "host"), f"{fx.H1}|gcc 11.4") or NO_CLASS)["derived_from_git"] == [],
          "contradicted: a recorded tree git contradicts is 'unknown', not 'not recorded'; the directory git agrees on keeps its recorded tree")
    # --no-git (rev=None): today's record-only view
    Sn = R.summarize(fx.runs(fx.old), rev=None)
    why = "git was not read (--no-git)"
    hold(ck_apart, Sn, fx, c1, why, "no-git")
    plant(ck_apart, "git read although told not to", "no-git: the second run is a class of its own", S, fx, c1, why, "no-git")
    check(Sn["sweep"]["trees"]["git"] == {"read": False, "problem": None} and "not read (--no-git)" in R.render(Sn), "no-git: the summary and the text say git was not read")
    # 3. git is bounded and kept
    hold(ck_kept, R.GitTrees)
    plant(ck_kept, "no cache", "git: kept per (commit, directory)", Uncached)
    hold(ck_stops, R.GitTrees)
    plant(ck_stops, "git asked again after it failed", "git stops: the lookup", Persistent)
    with patched(subprocess=FakeProc(exc=FileNotFoundError())):
        g = R.GitTrees("/x")
        check(g("b" * 40, "rtl") is None and "could not be run" in (g.problem or ""), "git missing: no tree, and `problem` says git could not be run", g.problem)
    fake = FakeProc(delay=0.2)               # four times the budget (a Windows clock ticks in 16 ms)
    with patched(subprocess=fake):
        g = R.GitTrees("/x", budget=0.05)
        first, second = g("b" * 40, "rtl"), g("b" * 40, "host")
    check(first == "a" * 40 and second is None and len(fake.calls) == 1 and "asked for" in (g.problem or ""),
          "git budget: when all the lookups together have taken the budget, the answer is kept and git is not asked again, by name", (first, second, g.problem))
    fake = FakeProc(rc=128, out="")
    with patched(subprocess=fake):
        g = R.GitTrees("/x")
        none, more = g("b" * 40, "rtl"), g("b" * 40, "host")
    check(none is None and more is None and len(fake.calls) == 2 and "not a git repository" in (g.problem or ""),
          "no repository: a refusal followed by a refused `rev-parse --git-dir` is named, and git is not asked again", (len(fake.calls), g.problem))
    drv = os.path.join(HW, "card_stress.py")
    lim = re.search(r"def refresh_report.*?timeout=(\d+)", open(drv, encoding="utf-8").read(), re.S) if os.path.exists(drv) else None
    if lim:
        check(R.GIT_BUDGET_S < int(lim.group(1)) / 2, f"git bound: all of git's time ({R.GIT_BUDGET_S:g} s) is under half the driver's refresh limit ({lim.group(1)} s)")
    else:
        skip("git bound against the driver's refresh limit", "hw/card_stress.py is not beside the test")
    # 4. the command line, and the agreement with the resume's count
    cli_checks(fx, tmp)
    recs = fx.runs(fx.old) + [{"type": "leg", "v": 1, "epoch": T0, "kind": "sweep", "status": "pass", "image": "quad", "leg": "sweep-div32-rne",
                               "counts": {"cases": 1000}, "sweep": {"item": "div32-rne", "op": "div32", "reach": "tile", "count": 1000, "seed": 3, "seed_n": 1}}]

    def synthetic(ck, s):
        t = ck_agree(ck, recs, fx.rec, rev, s, "synthetic")
        ck.eq(t["counted"], {"tile": 3, "host": 1}, "synthetic: the resume counts the derived run's tile slice as the report does (3 tile and 1 host slice counted)")
    hold(synthetic, R.summarize(recs, rev=rev))
    plant(synthetic, "the report not reading git while the resume does", "synthetic: the report's coverage", R.summarize(recs, rev=None))
    real_copy_checks()


def main():
    tmp = tempfile.mkdtemp(prefix="cft-report-test-")
    try:
        recs, marks = build_main()
        base = Scn(recs)
        group_pins(base, marks)
        group_families(base)
        group_running_and_deadline(base, marks)
        group_gaps(base, marks)
        group_telemetry_edges()
        group_json(base)
        group_reach()
        group_controls(base, marks)
        group_sabotage(base)
        group_files(base, marks, tmp)
        group_weird(base)
        group_cli(base, marks, tmp)
        group_git(tmp)
    finally:
        _close_group()
        rmtree_force(tmp)
    print(f"report test: {_st['n']} checks, {_st['failed']} failed")
    return 0 if _st["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
