#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""How long a request to stop waits for a card stress run to reach a safe point.

    python -B -I latency.py LABEL=METRICS.jsonl[@N] [LABEL=METRICS.jsonl[@N] ...] [--controls]

FILE@N is the N-th run of a file that holds several (a resumed run writes its own `run_start`): the records from that
`run_start` to the next one's, analysed as a file of their own, so that a night is measured alone and not with the idle
hours between two nights (a request is taken as arriving uniformly over the run's span, so idle hours would dilute it).
The output is written with LF line ends on every platform (Windows Python would write CRLF to a redirected stdout), so
the captures beside this script are LF and compare equal as they stand.

hw/card_stress.py stops "after the leg running, never in the middle of one" (its docstring): a STOP file,
a signal or the deadline is looked at between legs and between sweep waves, and a card leg in flight runs
on. A scheduler that preempts a window for a staged run therefore waits for the leg or the wave running.
This reads a run's metrics.jsonl and computes, from the legs' own start and end epochs, how long that wait
would have been for a request arriving at an instant chosen uniformly over the run's span:

  activity   a battery or recovery leg, or a sweep wave (the sweep legs of one cycle whose intervals overlap:
             run_wave starts a wave's jobs in one loop and waits for all of them, so a wave ends with its last
             job and the next wave starts after that; each sweep leg also records the size of its wave, `jobs`,
             which gives the number of waves independently: the sum of 1/jobs over the sweep legs)
  wait       the time from the instant to the end of the activity it falls in, or 0 in a gap between
             activities (the driver looks for a stop there)

For one activity of length d the wait is uniform on [0, d], so over the span S the mean wait is
sum(d^2) / (2 S) and P(wait > x) = sum(max(0, d - x)) / S, both exact. A Monte Carlo of the same
definition, with a fixed seed, is run beside them as a check, and with --controls a wrong formula must be
caught by it. Nothing here measures the host pool (no slice of it is in these runs): it adds at most the
--kill-after grace (60 s by default, READ in pool_end) after the last card leg. A leg on the image `cpu` is a host
slice, which runs beside the card's legs and holds no card, so it is counted and left out of the activities (none
of the runs read so far has one).

Read-only; prints no path. Python 3.10 or later; standard library only.
"""
import json
import random
import sys

def parse_arg(a):
    """LABEL=PATH or LABEL=PATH@N -> (label, path, N or None); an `@` not followed by digits only is part of the path."""
    label, _, path = a.partition("=")
    head, sep, tail = path.rpartition("@")
    if sep and head and tail.isdigit():
        return label, head, int(tail)
    return label, path, None


def load(path, part=None):
    """The records of the file; with part, only those of its part-th run (from a run_start to the next one's). None if there is no such run."""
    recs = []
    with open(path, "rb") as fh:
        for ln in fh.read().split(b"\n"):
            if ln.strip():
                recs.append(json.loads(ln.decode("utf-8")))
    if part is None:
        return recs
    starts = [i for i, r in enumerate(recs) if r.get("type") == "run_start"]
    if not 1 <= part <= len(starts):
        return None
    end = starts[part] if part < len(starts) else len(recs)
    return recs[starts[part - 1]:end]


def activities(recs, one_wave_a_cycle=False, keep_cpu=False):
    """[(start, end, name)] of battery legs, recoveries and sweep waves, sorted; legs that did not run, and legs on the image
    `cpu` (host slices, which hold no card), are left out. one_wave_a_cycle and keep_cpu are the planted slips of --controls:
    every sweep leg of a cycle called one wave; a host slice counted as a card activity."""
    acts = []
    sweeps = {}
    for r in recs:
        if r.get("type") != "leg" or r.get("status") == "skipped":
            continue
        if r.get("image") == "cpu" and not keep_cpu:
            continue
        s, e = r.get("start_epoch"), r.get("end_epoch")
        if s is None or e is None or e < s:
            continue
        if r.get("kind") == "sweep":
            sweeps.setdefault(r.get("cycle"), []).append((s, e))
        else:
            acts.append((s, e, "%s %s" % (r.get("leg"), r.get("image"))))
    for cyc, legs in sweeps.items():
        legs.sort()
        wave = [legs[0]]
        for s, e in legs[1:]:
            if one_wave_a_cycle or s < max(x[1] for x in wave):
                wave.append((s, e))
            else:
                acts.append((wave[0][0], max(x[1] for x in wave), "sweep wave"))
                wave = [(s, e)]
        acts.append((wave[0][0], max(x[1] for x in wave), "sweep wave"))
    acts.sort()
    return acts


def exact(acts, span):
    d = [e - s for s, e, _ in acts]
    mean = sum(x * x for x in d) / (2.0 * span)

    def tail(x):
        return sum(max(0.0, v - x) for v in d) / span

    def quantile(p):
        lo, hi = 0.0, max(d)
        for _ in range(80):
            mid = (lo + hi) / 2.0
            if tail(mid) > 1.0 - p:
                lo = mid
            else:
                hi = mid
        return hi
    return mean, tail, quantile


def wait_at(acts, t):
    for s, e, _ in acts:
        if s <= t < e:
            return e - t
        if s > t:
            break
    return 0.0


def monte_carlo(acts, t0, t1, n=200000, seed=20261021):
    rng = random.Random(seed)
    w = sorted(wait_at(acts, t0 + rng.random() * (t1 - t0)) for _ in range(n))
    return sum(w) / n, w


def fmt(sec):
    return "%.1f s (%.1f min)" % (sec, sec / 60.0)


def analyse(label, recs, wrong=False, one_wave_a_cycle=False, keep_cpu=False):
    """(every check held, the figures a summary table reads)."""
    acts = activities(recs, one_wave_a_cycle, keep_cpu)
    n_waves = sum(1 for a in acts if a[2] == "sweep wave")
    cpu_legs = sum(1 for r in recs if r.get("type") == "leg" and r.get("image") == "cpu" and r.get("status") != "skipped")
    by_jobs = sum(1.0 / max(1, int((r.get("sweep") or {}).get("jobs") or 1)) for r in recs
                  if r.get("type") == "leg" and r.get("kind") == "sweep" and r.get("status") != "skipped"
                  and r.get("start_epoch") is not None and r.get("end_epoch") is not None
                  and (keep_cpu or r.get("image") != "cpu"))
    t0 = min(a[0] for a in acts)
    t1 = max(a[1] for a in acts)
    span = t1 - t0
    # activities of one driver run are sequential: a card leg and a wave never overlap
    overlaps = sum(1 for a, b in zip(acts, acts[1:]) if b[0] < a[1] - 1e-6)
    inside = sum(e - s for s, e, _ in acts)
    mean, tail, q = exact(acts, span)
    if wrong:                          # the planted slip: d instead of d/2 in the mean
        mean *= 2.0
    print("== %s" % label)
    print("activities: %d (%d battery or recovery legs, %d sweep waves); %d overlap each other; %d host-slice legs (image cpu) left out" %
          (len(acts), sum(1 for a in acts if a[2] != "sweep wave"), sum(1 for a in acts if a[2] == "sweep wave"), overlaps, 0 if keep_cpu else cpu_legs))
    print("span      : %.0f s (%.3f h) from the first activity's start to the last one's end; %.2f%% of it is inside an activity" % (span, span / 3600.0, 100.0 * inside / span))
    rs_ep = next((r["epoch"] for r in recs if r.get("type") == "run_start" and isinstance(r.get("epoch"), (int, float))), None)
    startup = (t0 - rs_ep) if rs_ep is not None else None
    if startup is not None:
        print("start-up  : the first activity starts %.1f s after the run's `run_start` record, which the driver writes as it starts: its tree facts, build step, probes, image hashes and a first telemetry sample all fall in that time" % startup)
    wl = [e - s for s, e, n in acts if n == "sweep wave"]
    if wl:
        print("waves     : %d sweep waves, mean length %.1f s, longest %.1f s" % (len(wl), sum(wl) / len(wl), max(wl)))
    print("mean wait : %s" % fmt(mean))
    for p in (0.5, 0.9, 0.95, 0.99):
        print("p%-3d wait : %s" % (round(p * 100), fmt(q(p))))
    for x in (60, 300, 600, 1200):
        print("P(wait > %4d s) = %.4f" % (x, tail(x)))
    longest = sorted(acts, key=lambda a: a[1] - a[0], reverse=True)[:3]
    print("longest   : " + "; ".join("%s %s" % (a[2], fmt(a[1] - a[0])) for a in longest))
    # the longest battery leg against the same leg on the other visits: is it a first-visit cost?
    legs = [r for r in recs if r.get("type") == "leg" and r.get("kind") != "sweep" and r.get("status") != "skipped"]
    if legs:
        top = max(legs, key=lambda r: float(r.get("duration_s") or 0))
        same = sorted(float(r["duration_s"]) for r in legs
                      if r.get("leg") == top.get("leg") and r.get("image") == top.get("image") and r.get("cycle") != top.get("cycle"))
        if same:
            print("longest leg: %s on %s, cycle %s, %.1f s; the same leg in the other %d visits: median %.1f s, from %.1f to %.1f s" %
                  (top.get("leg"), top.get("image"), top.get("cycle"), float(top["duration_s"]), len(same), same[len(same) // 2], same[0], same[-1]))
    by = {}
    for s, e, n in acts:
        k = "sweep wave" if n == "sweep wave" else n.split(" ")[0]
        by.setdefault(k, []).append(e - s)
    print("by kind (activities, total s, share of the span, mean s, max s):")
    for k, v in sorted(by.items(), key=lambda kv: -sum(kv[1])):
        print("  %-16s %4d %9.0f %6.1f%% %8.1f %8.1f" % (k, len(v), sum(v), 100.0 * sum(v) / span, sum(v) / len(v), max(v)))
    mc_mean, w = monte_carlo(acts, t0, t1)
    mc_p95 = w[int(0.95 * len(w))]
    ok = abs(mc_mean - mean) <= 0.03 * max(mean, 1.0) and abs(mc_p95 - q(0.95)) <= 0.05 * max(q(0.95), 1.0) + 5.0
    print("CHECK %-4s %s: the exact mean %.1f s and p95 %.1f s agree with a seeded Monte Carlo of the same definition (%.1f s, %.1f s)" %
          ("ok" if ok else "FAIL", label, mean, q(0.95), mc_mean, mc_p95))
    ok2 = overlaps == 0
    print("CHECK %-4s %s: no two activities overlap" % ("ok" if ok2 else "FAIL", label))
    ok3 = abs(by_jobs - n_waves) < 1e-6
    print("CHECK %-4s %s: the %d sweep waves found equal the sum of 1/jobs over the sweep legs (%.3f), the wave size each leg records" %
          ("ok" if ok3 else "FAIL", label, n_waves, by_jobs))
    figs = {"label": label, "acts": len(acts), "waves": len(wl), "wave_mean": (sum(wl) / len(wl)) if wl else 0.0,
            "span_h": span / 3600.0, "mean": mean, "p50": q(0.5), "p95": q(0.95), "p99": q(0.99),
            "gt600": tail(600), "startup": startup}
    return (ok and ok2 and ok3), figs


def summary(figs):
    """The runs side by side and the range they make."""
    print("== the runs side by side (the wait of a stop request, a request arriving uniformly over each run's span)")
    print("%-18s %7s %6s %9s %11s %11s %11s %9s %10s" % ("run", "hours", "waves", "wave s", "mean wait s", "p95 wait s", "p99 wait s", "P(>600s)", "start-up s"))
    for f in figs:
        print("%-18s %7.3f %6d %9.1f %11.1f %11.1f %11.1f %9.4f %10s" % (
            f["label"], f["span_h"], f["waves"], f["wave_mean"], f["mean"], f["p95"], f["p99"], f["gt600"],
            ("%.1f" % f["startup"]) if f["startup"] is not None else "-"))
    m = [f["mean"] for f in figs]
    p = [f["p95"] for f in figs]
    w = [f["wave_mean"] for f in figs]
    print("ranges    : mean wait %.1f to %.1f s (%.1f to %.1f min), p95 %.1f to %.1f s (%.1f to %.1f min), a wave's mean length %.1f to %.1f s (COMPUTED over %d runs)" %
          (min(m), max(m), min(m) / 60.0, max(m) / 60.0, min(p), max(p), min(p) / 60.0, max(p) / 60.0, min(w), max(w), len(figs)))
    ok = len(figs) >= 2 and all(min(m) <= x <= max(m) for x in m)
    print("CHECK %-4s the ranges are the least and the greatest of the rows above" % ("ok" if ok else "FAIL"))
    return ok


def with_cpu_leg(recs):
    """recs plus one host-slice leg that overlaps the first card activity: the stand-in for a run with a host pool."""
    acts = activities(recs)
    s, e = acts[0][0], acts[0][1]
    ghost = {"type": "leg", "kind": "sweep", "image": "cpu", "status": "ok", "cycle": 1, "start_epoch": s + (e - s) / 4.0,
             "end_epoch": e + (e - s) / 4.0, "sweep": {"jobs": 1}, "leg": "sweep-slice"}
    return recs + [ghost]


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
    figs = []
    for a in args:
        label, path, part = parse_arg(a)
        recs = load(path, part)
        if recs is None:
            print("== %s\nCHECK FAIL %s: the file has no run %d" % (label, label, part))
            allok = False
            print()
            continue
        first = first or (label, recs)
        ok, f = analyse(label, recs)
        figs.append(f)
        allok = ok and allok
        print()
    if len(figs) >= 2:
        allok = summary(figs) and allok
        print()
    if "--controls" in argv and first is not None:
        import io
        import contextlib
        print("== control: the mean computed with d where d/2 belongs must be caught by the Monte Carlo check")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            caught = not analyse(first[0], first[1], wrong=True)[0]
        print("CONTROL %-4s a wrong formula %s" % ("ok" if caught else "FAIL", "is caught by the check, as it must be" if caught else "PASSES THE CHECK"))
        allok = caught and allok
        print("== control: every sweep leg of a cycle called one wave must be caught by the wave-count check")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            caught2 = not analyse(first[0], first[1], one_wave_a_cycle=True)[0]
        print("CONTROL %-4s a wrong grouping %s" % ("ok" if caught2 else "FAIL", "is caught by the check, as it must be" if caught2 else "PASSES THE CHECK"))
        allok = caught2 and allok
        print("== control: a host-slice leg (image cpu) beside a card leg is left out; counted as a card activity it must be caught")
        with contextlib.redirect_stdout(buf):
            left_out = analyse(first[0], with_cpu_leg(first[1]))[0]
            counted = not analyse(first[0], with_cpu_leg(first[1]), keep_cpu=True)[0]
        print("CONTROL %-4s a host slice is %s" % ("ok" if left_out else "FAIL", "left out and every check stays green" if left_out else "NOT LEFT OUT"))
        print("CONTROL %-4s a host slice counted as a card activity %s" % ("ok" if counted else "FAIL", "is caught by the no-overlap check, as it must be" if counted else "PASSES THE CHECKS"))
        allok = left_out and counted and allok
    print("latency: %s" % ("every check held" if allok else "A CHECK FAILED"))
    return 0 if allok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
