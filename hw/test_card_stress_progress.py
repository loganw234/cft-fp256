#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Test of hw/card_stress_progress.py and of site/nightly.html:   python hw/test_card_stress_progress.py [--write-fixture]

HOW IT KNOWS. A synthetic run with known truth: three nights in a zone nobody here lives in (UTC-03:30, so a night's date is
not its UTC date); a first night that recorded no tree and two that did; host slices beside the card's; a failed battery
leg and a skipped one; the hard-case and class-level spaces; and a range swept only under the older tree, so a class's first
gap is not the whole run's. Every figure has three values: the ORACLE's (plain loops and integer arithmetic over the spec; it
calls nothing in the reducer or the report), the reducer's, and the report's own (`card_stress_report.py RUN --json`). The page
is run in node against a stub DOM, and its text held to the same numbers.
HOW IT KNOWS IT CAN FAIL. Plants - a disagreement, a fourth night, a tree change, a malformed line, a night with no run_end, a
dry run, a leaked host name, path and user, a number past 2**53, an edited data file - must each change the output or be refused
by name, and --check must name the field; every one is paired with a control that must not trip. The lead's real copies are read
when CARD_STRESS_PROGRESS_RUNS names their directories (separated as PATH is), and skipped by name without it.

THE WIDE ITEMS (parcel HXd, 2026-10-27). A second synthetic run (BSPEC, four nights, and WSPEC: the same four nights with the wide items served from the third,
the tile class's second night) serves wide items of the three kinds the driver serves - hard cases, the fp32 slice at fp64, a low-bit window - beside the base items.
Its truth is the oracle's, from the spec alone (the format and group of every item written in this file's own table, the spaces from the documents), and the
reducer's data, the report's and the page's are held to it: each row's format and group, each class's totals by group, a night's state by group (written only once a
class has a wide row, so the nights before it are the nights they were), the base group's figures unmoved by the wide group joining, the page's card, item list and
chart in node (the older group's line point for point as it was), every format passing the guard against a path-shaped string, and, over a data file WITHOUT the new
fields, the page drawing the very tree that 3ec0081c's page drew (a digest of the whole stub DOM, from running that page through this harness).

The last line is "progress test: N checks, F failed, K skipped"; the exit status is 0 only if F is 0.
"""
import sys
sys.dont_write_bytecode = True

import calendar
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter

HW = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HW)
if HW not in sys.path:
    sys.path.insert(0, HW)
import card_stress_progress as P      # noqa: E402  (the unit under test)
import card_stress_report as R        # noqa: E402

SCRIPT, REPORT = os.path.join(HW, "card_stress_progress.py"), os.path.join(HW, "card_stress_report.py")
PAGE, DATA = os.path.join(ROOT, "site", "nightly.html"), os.path.join(ROOT, "site", "nightly.json")
FIXTURE = os.path.join(HW, "card_stress_fixtures", "progress-synthetic.jsonl")
FIXTURE_WIDE = os.path.join(HW, "card_stress_fixtures", "progress-synthetic-wide.jsonl")
# What the page of 3ec0081c drew over a data file of the shape its reducer made (the run without wide items, the new fields taken off), as the digest of
# the whole tree it builds in the stub DOM, with the clock at LEGACY_CLOCK (the page says how long ago the newest night ended). Made once by running that
# page (git show 3ec0081c:site/nightly.html) through this very harness; the page now must draw the same tree over such a file.
LEGACY_CLOCK = 1792650000000
LEGACY_DOM = "c8aa1396ddcc7be0457d479cb6de09be623ad34752cad269f96c5c570636e2e4"
# The same, for the file the nightly page was committed with at 3ec0081c (night 7, the data file's sha256 below): the digest of the tree that page drew
# over it with the clock at NIGHT7_CLOCK, from running that page through this harness.
NIGHT7_SHA256 = "72960b0c33ce267b0627e7feec3b74483875fff1e7977f1f597e5ca17971d650"
NIGHT7_CLOCK = 1793200000000
NIGHT7_DOM = "0884be6ecce7fb52f062a5983a51afa2e1850131790567bb1dada4869fea69b8"
st = {"n": 0, "f": 0, "skips": 0}
DERIVED = []
_SUMMARIZE, _TREE_CLASS = R.summarize, R.tree_class


def with_rev(rev):
    """The reducer's calls to summarize() and to tree_class() with `rev` given: None is the record-only view (the CLI's --no-git), a function the
    report's "given rev" view. The fixture's commits are made up, so its groups use None and need no git; the real copies use the defaults (git of
    the checkout), which are what `card_stress_report.py --json` shows."""
    R.summarize = lambda *a, **k: _SUMMARIZE(*a, **dict(k, rev=k.get("rev", rev)))
    R.tree_class = lambda kind, rs, rev=rev: _TREE_CLASS(kind, rs, rev)


def record_only(on):
    if on:
        with_rev(None)
    else:
        R.summarize, R.tree_class = _SUMMARIZE, _TREE_CLASS


def check(ok, what, detail=None):
    st["n"] += 1
    if not ok:
        st["f"] += 1
        print(f"  FAIL {what}" + (f": {detail!r}"[:400] if detail is not None else ""))
    return bool(ok)


def eq(got, want, what):
    return check(got == want, what, f"got {got!r}, want {want!r}")


def skip(name, why):
    st["skips"] += 1
    print(f"  SKIP  {name} - {why}")


# ---------------------------------------------------------------------------
# the fixture: a run with known truth, written as the driver writes one
# ---------------------------------------------------------------------------
FMT, OFF = "%Y-%m-%d %H:%M:%S", -(3 * 3600 + 1800)
T0 = calendar.timegm((2026, 10, 20, 2, 0, 0))        # night 1 starts at 22:30 on the 19th by the fixture box's clock
A, EXH = 1 << 30, 1 << 32
ITEMS = {                                              # tool, op, mode, reach, space, cases an index, format, group (the format and group written here by hand)
    "conv32to64-all": ("clause5", "conv32to64-all", None, "host", EXH, 1, "fp32 -> fp64", "base"),
    "scaleb32-all-rne": ("clause5", "scaleb32-all", "rne", "tile", EXH, 17, "fp32", "base"),
    "scaleb32-wide-rne": ("clause5", "scaleb32-wide", "rne", "tile", EXH, 568, "fp32", "base"),
    "rint64-class-rne": ("clause5", "rint64-class", "rne", "tile", 35840, 4, "fp64", "base"),
    "div32-hard-rne": ("divsqrt", "div32-hard", "rne", "tile", 21235788, 4, "fp32", "base"),
}
CAMPAIGN = list(ITEMS)
# The wide-format items (parcel HXc's), one of each kind the driver serves, their spaces and k from the documents (docs/CARDDAY.md, "The wide items in
# the driver"; docs/studies/HX-wide-sweeps.md), not from the library, and their formats from the C tools' headers: a hard case (div128-hard: p = 113),
# the fp64 hard cases widened (sqrt256-f64hard), the fp32 slice at fp64 (sqrt64-f32) and a low-bit window (recip128-win-key: a keyed draw). They are
# all tile items. sqrt128-hard-rne is named by the wide campaign and never served: a wide row at zero.
WIDE = {
    "div128-hard-rne": ("divsqrt", "div128-hard", "rne", "tile", 289_931_696, 4, "fp128", "wide"),
    "sqrt256-f64hard-rne": ("divsqrt", "sqrt256-f64hard", "rne", "tile", 4_456_448, 1, "fp256", "wide"),
    "sqrt64-f32-rup": ("divsqrt", "sqrt64-f32", "rup", "tile", EXH, 1, "fp64", "wide"),
    "recip128-win-key-rne": ("divsqrt", "recip128-win-key", "rne", "tile", EXH, 1, "fp128", "wide"),
    "sqrt128-hard-rne": ("divsqrt", "sqrt128-hard", "rne", "tile", 4_456_448, 1, "fp128", "wide"),
}
ITEMS.update(WIDE)
WCAMPAIGN = list(ITEMS)
TREE_A = {"commit": "a1" * 20, "dirty": False, "dirty_files": 0}              # a run that recorded no tree
TREE_B = {"commit": "b2" * 20, "dirty": False, "dirty_files": 0, "rtl": "c3" * 20, "rtl_dirty": False, "host_src": "d4" * 20,
          "host_src_dirty": False, "cc": "cc (Fixture) 1.0"}
TREE_C = dict(TREE_B, commit="b3" * 20, rtl="c4" * 20, host_src="d5" * 20)
N1 = {"tree": TREE_A, "battery": [("api-test", "pass"), ("dt-i", "pass")], "slices": [
    ("scaleb32-all-rne", 0, A), ("scaleb32-all-rne", A, 2 * A), ("scaleb32-all-rne", 2 * A, 3 * A), ("scaleb32-all-rne", 3 * A, 4 * A),
    ("scaleb32-wide-rne", 0, A), ("conv32to64-all", 0, A), ("conv32to64-all", A, 2 * A), ("conv32to64-all", 2 * A, 3 * A),
    ("conv32to64-all", 3 * A, 4 * A)]}
N2 = {"tree": TREE_B, "battery": [("api-test", "pass"), ("dt-i", "fail"), ("selftest", "skipped")], "slices": [
    ("scaleb32-wide-rne", A, 2 * A), ("scaleb32-wide-rne", 2 * A, 3 * A), ("rint64-class-rne", 0, 35840),
    ("div32-hard-rne", 0, 10_000_000), ("conv32to64-all", 0, A), ("conv32to64-all", A, 2 * A)]}
N3 = {"tree": TREE_B, "battery": [("api-test", "pass"), ("selftest", "skipped")], "slices": [
    ("div32-hard-rne", 12_000_000, 21_235_788), ("scaleb32-wide-rne", 3 * A, 4 * A), ("conv32to64-all", 2 * A, 3 * A)]}
SPEC = [N1, N2, N3]
# A fourth night, the base items' (BSPEC): the run goes on under the same tree, filling the gap in div32-hard-rne, a quarter of scaleb32-all-rne, and the last
# quarter of conv32to64-all, so that the base group moves on the night the wide group is first served.
N4 = {"tree": TREE_B, "battery": [("api-test", "pass"), ("selftest", "skipped")], "slices": [
    ("div32-hard-rne", 10_000_000, 12_000_000), ("scaleb32-all-rne", 0, A), ("conv32to64-all", 3 * A, 4 * A)]}
BSPEC = [N1, N2, N3, N4]
# The same four nights with the wide items served from the third, the class's second night (the tile class of nights 2 to 4 has its first night without them):
# div128-hard partly on night 3 and to the end of its space on night 4 (4 checks an index), sqrt256-f64hard whole in one slice, sqrt64-f32 a quarter and then
# three quarters, recip128-win-key two quarters and then the rest. Its campaign (WCAMPAIGN) names sqrt128-hard-rne too, never served.
WN3 = N3 | {"slices": N3["slices"] + [("div128-hard-rne", 0, 4_000_000), ("sqrt64-f32-rup", 0, A), ("recip128-win-key-rne", 0, 2 * A)]}
WN4 = N4 | {"slices": N4["slices"] + [("div128-hard-rne", 4_000_000, 289_931_696), ("sqrt256-f64hard-rne", 0, 4_456_448), ("sqrt64-f32-rup", A, 3 * A),
                                      ("recip128-win-key-rne", 2 * A, EXH)]}
WSPEC = [N1, N2, WN3, WN4]


def local(e):
    return time.strftime(FMT, time.gmtime(e + OFF))


def build(spec=SPEC, campaign=None):
    """The records of the spec's nights, a night a day, in the order and with the fields the driver writes (the ones read). `campaign` is the
    items every run_start's --sweep-items names (CAMPAIGN, the base items, unless given)."""
    campaign = CAMPAIGN if campaign is None else campaign
    recs, clk, cycle = [], [0.0], 0

    def put(typ, e, **kw):
        clk[0] = max(clk[0] + 0.001, e)
        recs.append({"type": typ, **kw, "v": 1, "ts": local(clk[0]), "epoch": round(clk[0], 3)})

    def leg(t, dur, name, kind, status, image, **kw):
        put("leg", t + dur, cycle=cycle, image=image, leg=name, kind=kind, attempt=1, start=local(t), end=local(t + dur), start_epoch=t,
            end_epoch=t + dur, duration_s=float(dur), rc=None if status == "skipped" else int(status == "fail"), status=status,
            timed_out=False, killed=None, rate=None, **kw)

    for k, nt in enumerate(spec):
        e = T0 + k * 86400
        put("run_start", e, run_id="fixture-run", out="/data/fixture-run", host="fixture-box",
            argv=(["--resume"] if k else []) + ["--out", "/data/fixture-run", "--rev8-images", "/Users/fixtureuser/images", "--sweep-items", ",".join(campaign)],
            settings={"until": "2026-10-20 08:00:00", "quick": False, "dry_run": nt.get("dry", False)}, tree=nt["tree"], deadline="2026-10-20 08:00:00",
            images={"quad": {"sha256": "4f" * 32, "bytes": 5, "tiles": 4, "path": "/Users/fixtureuser/images/quad.xclbin", "target": "u50-quad"},
                    "single": {"sha256": "06" * 32, "bytes": 4, "tiles": 1, "path": "/Users/fixtureuser/images/single.xclbin", "target": "u50"}},
            resumed=bool(k))
        put("build", e + 1, ok=True, steps=[{"name": "tree", "ok": True, "detail": "HEAD, clean"}])
        cycle += 1
        put("cycle_start", e + 2, cycle=cycle, image="quad", visit=1, quick=False)
        t = e + 10
        for name, status in nt["battery"]:
            dur = 0 if status == "skipped" else 30
            leg(t, dur, name, "battery", status, "quad", counts=None if status == "skipped" else {"failed": int(status == "fail")}, sweep=None,
                disagreements=None, log=None, reason="every 3 visits of an image" if status == "skipped" else None, tile=None)
            t += dur + 5
        put("cycle_end", t, cycle=cycle, image="quad", legs=len(nt["battery"]), failed=sum(s == "fail" for _, s in nt["battery"]), seconds=t - e)
        cycle += 1
        put("cycle_start", t + 1, cycle=cycle, image="quad", visit=2, quick=False)
        t += 5
        starts = []
        for host_pass in (False, True):                # the card's slices one after another, then the host pool's beside them
            for j, (item, lo, hi, *s) in enumerate(x for x in nt["slices"] if (ITEMS[x[0]][3] == "host") == host_pass):
                tool, op, mode, reach, _space, per, *_ = ITEMS[item]
                status, t0 = (s[0] if s else "pass"), (starts[j % len(starts)] if host_pass else t)
                if not host_pass:
                    starts.append(t0)
                leg(t0, 600, "sweep-" + item, "sweep", status, "cpu" if host_pass else "quad",
                    counts={"cases": (hi - lo) * per, "value_mismatches": int(status == "fail"), "flag_mismatches": 0, "encodings": hi - lo, "skipped": 0},
                    sweep={"item": item, "tool": tool, "op": op, "mode": mode, "reach": reach, "lo": lo, "hi": hi, "tile": 1, "jobs": 1},
                    disagreements=["MISMATCH fixture"] if status == "fail" else [], log="logs/x.log.gz", reason=None, tile=1)
                t += 0 if host_pass else 605
        put("cycle_end", t, cycle=cycle, image="quad", legs=len(nt["slices"]), failed=0, seconds=t - e)
        put("event", t + 1, event="deadline", detail="reached", reason="deadline")
        if not nt.get("no_end"):
            put("run_end", t + 2, reason=nt.get("reason", "deadline"), exit=0, cycles=cycle)
    return recs


def write_run(recs, name, extra=None):
    d = os.path.join(TMP, name)
    os.makedirs(d, exist_ok=True)
    text = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in recs)
    with open(os.path.join(d, "metrics.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(extra(text) if extra else text)
    return d


def cli(*args, script=SCRIPT):
    p = subprocess.run([sys.executable, "-B", "-I", script, *args], capture_output=True, text=True, encoding="utf-8", timeout=300)
    return p.returncode, p.stdout, p.stderr


def reduce_dir(d, commit=None):
    objs, info = P.load(d)
    return json.loads(P.dump(P.reduce_records(objs, info, commit)))


# ---------------------------------------------------------------------------
# the oracle: the fixture's truth from the spec alone
# ---------------------------------------------------------------------------
def union(iv):
    out = []
    for lo, hi in sorted(iv):
        if out and lo <= out[-1][1]:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def first_gap(iv, space):
    pos = 0
    for lo, hi in union(iv):
        if lo > pos:
            return [pos, lo]
        pos = max(pos, hi)
    return [pos, space] if pos < space else None


def oracle(spec=SPEC):
    classes, nights = {}, []
    for k, nt in enumerate(spec, 1):
        night = {"legs": Counter(), "slices": 0, "cases": 0, "card": 0, "dis": 0, "ids": {}, "state": {}, "groups": {}}
        mine = {}
        for kind in ("tile", "host"):
            tr = nt["tree"]
            key = (tr.get("rtl") or "u" + tr["commit"]) if kind == "tile" else ((tr["host_src"], tr["cc"]) if tr.get("host_src") else "u" + tr["commit"])
            c = classes.setdefault((kind, key), {"id": kind[0] + str(1 + sum(1 for q, _ in classes if q == kind)) if (kind, key) not in classes else None,
                                                  "kind": kind, "nights": [], "iv": {}, "n": {}, "cases": {}, "done": {}, "hist": {}})
            c["nights"].append(k)
            mine[kind] = c
            night["ids"][kind] = c["id"]
        for name, status in nt["battery"]:
            night["legs"][status] += 1
            night["card"] += 0 if status == "skipped" else 30
        for item, lo, hi, *s in nt["slices"]:
            status, (_t, _o, _m, reach, _sp, per, *_) = (s[0] if s else "pass"), ITEMS[item]
            c = mine[reach]
            c["iv"].setdefault(item, []).append((lo, hi))
            c["n"][item] = c["n"].get(item, 0) + 1
            c["cases"][item] = c["cases"].get(item, 0) + (hi - lo) * per
            night["legs"][status] += 1
            night["slices"] += 1
            night["cases"] += (hi - lo) * per
            night["card"] += 600 if reach == "tile" else 0
            night["dis"] += status == "fail"
        for c in classes.values():
            if c["nights"][0] <= k:
                cov = {i: sum(h - lo for lo, h in union(iv)) for i, iv in c["iv"].items()}
                c["hist"][k] = cov
                for i, v in cov.items():
                    if v == ITEMS[i][4]:
                        c["done"].setdefault(i, k)
                night["state"][c["id"]] = {"covered": sum(cov.values()), "complete": sum(v == ITEMS[i][4] for i, v in cov.items())}
                if any(ITEMS[i][7] == "wide" for i in cov):          # a night's state by group is written only once the class has a wide row served
                    night["groups"][c["id"]] = {g: {"covered": sum(v for i, v in cov.items() if ITEMS[i][7] == g),
                                                    "complete": sum(v == ITEMS[i][4] for i, v in cov.items() if ITEMS[i][7] == g)}
                                                for g in ("base", "wide") if any(ITEMS[i][7] == g for i in cov)}
        nights.append(night)
    return nights, {c["id"]: c for c in classes.values()}


def estimate(c, item, newest, date):
    """The rule, in integers: the class's last 3 nights, gain over them, ceil of what remains over the rate."""
    win = c["nights"][-3:]
    cov = c["hist"][newest].get(item, 0)
    gain = cov - c["hist"].get(win[0] - 1, {}).get(item, 0)
    if gain <= 0:
        return None
    left = -(-(ITEMS[item][4] - cov) * len(win) // gain)
    return {"window_nights": len(win), "per_night": gain // len(win), "nights_left": left,
            "date": (datetime.date.fromisoformat(date) + datetime.timedelta(days=left)).isoformat()}


def against_oracle(out, spec, recs, campaign=None):
    campaign = CAMPAIGN if campaign is None else campaign
    nights, classes = oracle(spec)
    n = len(spec)
    eq(len(out["nights"]), n, "nights")
    dates = [time.strftime("%Y-%m-%d", time.gmtime(T0 + k * 86400 + OFF)) for k in range(n)]
    for k, (o, r) in enumerate(zip(nights, out["nights"])):
        eq((r["n"], r["date"], r["closed"], r["cycles"]), (k + 1, dates[k], not spec[k].get("no_end"), 2), f"night {k + 1}: number, date (the box's, not UTC), closed, cycles (not run_end's cumulative)")
        eq({s: r["legs"].get(s, 0) for s in set(o["legs"]) | set(r["legs"])}, {s: o["legs"].get(s, 0) for s in set(o["legs"]) | set(r["legs"])}, f"night {k + 1}: legs by status")
        eq((r["slices"], r["cases"], r["disagreements"]), (o["slices"], o["cases"], o["dis"]), f"night {k + 1}: slices, cases, disagreements")
        check(abs(r["card_s"] - o["card"]) < 1e-6, f"night {k + 1}: time on the card (the host pool's legs beside it are not on it)", (r["card_s"], o["card"]))
        eq(r["classes"], o["ids"], f"night {k + 1}: the classes it counted under")
        eq(r["after"]["classes"], o["state"], f"night {k + 1}: the state after it, per class")
        eq(r["after"].get("groups", {}), o["groups"], f"night {k + 1}: the state after it by group, written for a class only once it has a wide row served")
    T = out["totals"]
    eq((T["nights"], T["slices"], T["completed_slices"], T["cases"], T["disagreements"]),
       (n, sum(x["slices"] for x in nights), sum(x["slices"] for x in nights), sum(x["cases"] for x in nights), sum(x["dis"] for x in nights)), "totals: nights, slices, cases, disagreements")
    check(abs(T["card_s"] - sum(x["card"] for x in nights)) < 1e-6, "totals: time on the card")
    check(abs(T["wall_s"] - (max(r["epoch"] for r in recs) - min(r["epoch"] for r in recs))) < 1e-6, "totals: wall span, first record to last")
    eq(T["legs"]["by_status"]["pass"], sum(x["legs"]["pass"] for x in nights), "totals: legs passed")
    eq(T["cycles"], 2 * n, "totals: cycles")
    eq([(x["class"], x["item"], x["night"]) for x in T["fully_covered"]],
       sorted(((c["id"], i, k) for c in classes.values() for i, k in c["done"].items()), key=lambda x: (x[2], x[0], x[1])), "totals: the fully covered items, each with its night")
    eq({c["id"] for c in out["now"]["classes"]}, set(classes), "the classes")
    date = dates[-1]
    for c in out["now"]["classes"]:
        o = classes[c["id"]]
        cur = o["nights"][-1] == n
        eq((c["kind"], c["nights"], c["current"], c["served"]), (o["kind"], o["nights"], cur, bool(o["iv"])), f"class {c['id']}: kind, nights, current, served")
        names = sorted(set(o["iv"]) | (set(i for i in campaign if ITEMS[i][3] == o["kind"]) if cur else set()))
        eq([r["item"] for r in c["items"]], names, f"class {c['id']}: its items (a current class lists the campaign's at zero)")
        for r in c["items"]:
            i, iv = r["item"], o["iv"].get(r["item"], [])
            cov = sum(h - lo for lo, h in union(iv))
            want = {"space": ITEMS[i][4], "covered": cov, "slices": o["n"].get(i, 0), "cases": o["cases"].get(i, 0), "complete": cov == ITEMS[i][4],
                    "complete_night": o["done"].get(i), "first_gap": first_gap(iv, ITEMS[i][4]), "estimate": estimate(o, i, n, date) if cur and cov < ITEMS[i][4] else None}
            eq({k: r[k] for k in want}, want, f"class {c['id']} {i}: space, covered, slices, cases, complete, night, first gap, estimate")
            eq((r["format"], r["group"]), (ITEMS[i][6], ITEMS[i][7]), f"class {c['id']} {i}: its format and its group (the test's own table, not the catalog's)")
        eq(c["total"], {"items": len(names), "complete": sum(r["complete"] for r in c["items"]), "covered": sum(r["covered"] for r in c["items"]),
                        "space": sum(ITEMS[i][4] for i in names), "pct": 100.0 * sum(r["covered"] for r in c["items"]) / sum(ITEMS[i][4] for i in names)},
           f"class {c['id']}: total")
        want_groups, cov_of = [], lambda i: sum(h - lo for lo, h in union(o["iv"].get(i, [])))
        for g in ("base", "wide"):
            mine = [i for i in names if ITEMS[i][7] == g]
            if mine:
                gc, gs = sum(cov_of(i) for i in mine), sum(ITEMS[i][4] for i in mine)
                want_groups.append({"group": g, "items": len(mine), "complete": sum(cov_of(i) == ITEMS[i][4] for i in mine), "covered": gc, "space": gs,
                                    "pct": 100.0 * gc / gs})
        eq(c["groups"], want_groups, f"class {c['id']}: its totals by group, base then wide, only the groups it has rows of, each over its own items")


# ---------------------------------------------------------------------------
# the reducer against the report: every figure both state
# ---------------------------------------------------------------------------
def raw_slices(d):
    """Every completed sweep slice of a run's metrics.jsonl as (item, lo, hi, cases), by night (the run_start before it), read as plain JSON
    lines: for the checks that must not lean on summarize()."""
    nights, cur = [], None
    with open(os.path.join(d, "metrics.jsonl"), encoding="utf-8") as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            if r.get("type") == "run_start":
                cur = []
                nights.append(cur)
            elif cur is not None and r.get("type") == "leg" and r.get("kind") == "sweep" and r.get("status") in ("pass", "fail"):
                sw, c = r.get("sweep"), r.get("counts")
                if isinstance(sw, dict) and sw.get("item") and isinstance(sw.get("lo"), int) and isinstance(sw.get("hi"), int):
                    cur.append((sw["item"], sw["lo"], sw["hi"], c["cases"] if isinstance(c, dict) and isinstance(c.get("cases"), int) else 0))
    return nights


def against_raw(out, d):
    """Every (class, item) row of a data file - covered, slices, cases and the first uncovered index, the figures the page shows - recomputed
    from the raw records over the nights the file says the class ran under, with this file's own interval code: (rows compared, mismatches).
    The classes are the file's, which `shared` holds to the report's; what is held here is what is counted in them, whatever the classes are."""
    nights = raw_slices(d)
    rows, bad = 0, []
    for c in out["now"]["classes"]:
        for r in c["items"]:
            sl = [(lo, hi, cs) for k in c["nights"] for (it, lo, hi, cs) in nights[k - 1] if it == r["item"]]
            iv = [(lo, hi) for lo, hi, _ in sl]
            want = (sum(h - lo for lo, h in union(iv)), len(sl), sum(cs for _, _, cs in sl), first_gap(iv, r["space"]))
            rows += 1
            if (r["covered"], r["slices"], r["cases"], r["first_gap"]) != want:
                bad.append((c["id"], r["item"], (r["covered"], r["slices"], r["cases"], r["first_gap"]), want))
    return rows, bad


def raw_check(out, d, label, plants=True):
    """against_raw must find rows and no mismatch; and a first gap, a covered figure and a slice count each bent in a copy must be named,
    so that it is a check that can fail on this very data."""
    rows, bad = against_raw(out, d)
    check(rows > 0 and not bad, f"{label}: {rows} class-level rows (covered, slices, cases, first uncovered index) recomputed from the raw records agree with the data file", bad[:2])
    if plants:
        where = next(((ci, ri) for ci, c in enumerate(out["now"]["classes"]) for ri, r in enumerate(c["items"]) if r["first_gap"] and r["covered"] > 0), None)
        if where is None:        # a copy read with git (the classes it gives) can have every item whole or at zero: nothing to bend (it crashed here, 3ec0081c's test too)
            skip(f"{label}: raw-record plants", "no item of this copy is partly covered, so there is no first gap, covered figure or slice count to bend")
            return rows
        item = out["now"]["classes"][where[0]]["items"][where[1]]["item"]
        for what, edit in (("first uncovered index", lambda r: r.__setitem__("first_gap", [r["first_gap"][0] + 1, r["first_gap"][1]])),
                           ("covered figure", lambda r: r.__setitem__("covered", r["covered"] + 1)), ("slice count", lambda r: r.__setitem__("slices", r["slices"] + 1))):
            bent = json.loads(json.dumps(out))
            edit(bent["now"]["classes"][where[0]]["items"][where[1]])
            _, bad2 = against_raw(bent, d)
            check(len(bad2) == 1 and bad2[0][1] == item, f"{label}: a planted {what} of {item} is named by the raw-record check", bad2[:2])
    return rows


def report_of(d, git_free):
    j = os.path.join(TMP, "report-%s.json" % hashlib.sha256(d.encode()).hexdigest()[:8])
    nogit = ["--no-git"] if git_free else []
    rc, text, err = cli(d, "--no-write", "--json", j, *nogit, script=REPORT)
    with open(j, encoding="utf-8") as fh:
        return json.load(fh), text, rc


def shared(out, S, text):
    """(figure, the reducer's, the report's) for every figure the data file states that the report states too."""
    T, W, U, H = out["totals"], S["sweep"], S["uptime"], S["header"]
    f = [("nights", T["nights"], H["run_starts"]), ("closed nights", T["closed_nights"], len(H["run_ends"])), ("records", out["source"]["records"], S["input"]["records"]),
         ("slices completed", T["slices"], W["completed"]), ("legs, total", T["legs"]["total"], S["totals"]["legs"]["total"]),
         ("legs, by status", T["legs"]["by_status"], S["totals"]["legs"]["by_status"]), ("cycles", T["cycles"], S["totals"]["cycles"]["started"]),
         ("cases", T["cases"], sum(e["cases"] for g in ("exhaustive", "random", "other") for e in W[g])),
         ("time on the card, s", T["card_s"], round(U["card_union_s"], 3)), ("wall span, s", T["wall_s"], round(U["wall_s"], 3)),
         ("disagreements", T["disagreements"], len(W["disagreements"])), ("first record", T["first"], H["started"]["ts"])]
    m = re.search(r"^no disagreement recorded in (\d+) completed slices$", text, re.M)
    f.append(("the report's 'no disagreement recorded in N completed slices'", (T["disagreements"], T["completed_slices"]), (0, int(m.group(1))) if m else None))
    by = {(c["kind"], c["key"]): c for c in S["sweep"]["trees"]["classes"]}
    mine = {(c["kind"], c["key"]): c for c in out["now"]["classes"]}
    f.append(("the classes seen", sorted(k for k in mine if mine[k]["served"]), sorted(by)))
    seen = Counter(e["item"] for c in by.values() for e in c["exhaustive"])
    whole = {e["item"]: e for e in W["exhaustive"]}
    for key, rc in by.items():
        c = mine.get(key)
        if c is None:
            continue
        f.append((f"class {c['id']}: label", c["label"], rc["label"]))
        f.append((f"class {rc['label'][:40]}: covered", c["total"]["covered"], rc["total"]["covered"]))
        rows = {r["item"]: r for r in c["items"]}
        # the reducer's totals by group hold the campaign's rows at zero, which the report cannot list: what is compared is what both state, covered and
        # complete, for each group the report has
        seen_g = {g["group"]: (g["covered"], g["complete_items"]) for g in rc["total"]["by_group"]}
        f.append((f"class {c['id']}: totals by group (covered, items complete)", {g["group"]: (g["covered"], g["complete"]) for g in c["groups"] if g["group"] in seen_g}, seen_g))
        for e in rc["exhaustive"]:
            r = rows.get(e["item"], {})
            f.append((f"{e['item']} in {c['id']}: format, group", (r.get("format"), r.get("group")), (e["format"], e["group"])))
            f.append((f"{e['item']} in {c['id']}: space, covered, slices, cases, complete, pct", tuple(r.get(k) for k in ("space", "covered", "slices", "cases", "complete", "pct")),
                      (e["total"], e["covered"], e["slices"], e["cases"], e["complete"], e["pct"])))
            if seen[e["item"]] == 1 and not e["complete"]:
                f.append((f"{e['item']} (in one class): first uncovered index", r.get("first_gap"), whole[e["item"]]["first_gap"]))
    return f


def against_report(out, d, label, git_free=True):
    S, text, rc = report_of(d, git_free)
    eq(rc, 0, f"{label}: the report ran")
    rows = shared(out, S, text)
    bad = [(n, a, b) for n, a, b in rows if a != b]
    check(not bad, f"{label}: {len(rows)} shared figures equal the report's", bad[:3])
    return rows


# ---------------------------------------------------------------------------
# the page, in node against a stub DOM
# ---------------------------------------------------------------------------
HARNESS = r'''
const fs = require("fs"), vm = require("vm");
const [html, mode, dataPath, clock] = process.argv.slice(2);
const m = /<script>([\s\S]*?)<\/script>/.exec(fs.readFileSync(html, "utf8"));
class T { constructor(t) { this.text = t; } get textContent() { return this.text; } dump() { return { t: this.text }; } }
class N {
  constructor(tag) { this.tag = tag; this.kids = []; this.attrs = {}; this.style = {}; this.hidden = false; this.className = ""; }
  appendChild(c) { if (c.frag) { this.kids.push(...c.kids); c.kids = []; } else this.kids.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  get textContent() { return this.kids.map(k => k.textContent).join(" "); }
  set textContent(v) { this.kids = v === "" ? [] : [new T(String(v))]; }
  dump() { return { tag: this.tag, attrs: this.attrs, style: this.style, hidden: this.hidden, cls: this.className, kids: this.kids.map(k => k.dump()) }; }
}
// the chart: each polyline of the figure, with the titles of the circles drawn after it; the clock may be fixed (the page says how long ago a night ended)
function chart(n, out) {
  if (n.tag === "svg" && n.attrs.role === "img") {
    let cur = null;
    n.kids.forEach(k => { if (k.tag === "polyline") { cur = { points: k.attrs.points, style: k.attrs.style, titles: [] }; out.push(cur); }
                          else if (k.tag === "circle" && cur) cur.titles.push(k.kids.map(x => x.textContent).join("")); });
  }
  (n.kids || []).forEach(k => chart(k, out));
  return out;
}
class FDate extends Date { constructor(...a) { if (a.length) super(...a); else super(Number(clock)); } static now() { return Number(clock); } }
const els = { status: new N("div"), app: new N("div") };
const document = { createElement: t => new N(t), createElementNS: (ns, t) => new N(t), createTextNode: s => new T(s),
  createDocumentFragment: () => Object.assign(new N("#frag"), { frag: true }), getElementById: id => els[id], documentElement: { clientWidth: 900 } };
const resp = (ok, status, text) => ({ ok, status, statusText: ok ? "OK" : "Not Found", text: () => Promise.resolve(text) });
const fetch = () => mode === "reject" ? Promise.reject(new TypeError("Failed to fetch")) :
  Promise.resolve(mode === "404" ? resp(false, 404, "") : resp(true, 200, fs.readFileSync(dataPath, "utf8")));
vm.runInNewContext(m[1], { document, window: { addEventListener() {} }, fetch, Date: clock ? FDate : Date, setTimeout, clearTimeout, console });
setTimeout(() => console.log(JSON.stringify({ status: { hidden: els.status.hidden, text: els.status.textContent },
  app: { hidden: els.app.hidden, text: els.app.textContent }, chart: chart(els.app, []),
  dom: require("crypto").createHash("sha256").update(JSON.stringify(els.app.dump())).digest("hex") })), 300);
'''


def page(mode, data=None, html=None, clock=None):
    """The page `html` (default: site/nightly.html) in node over the data file `data`, with the clock at `clock` milliseconds if given."""
    h = os.path.join(TMP, "harness.js")
    if not os.path.exists(h):
        with open(h, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(HARNESS)
    p = subprocess.run([NODE, h, html or PAGE, mode, data or ""] + ([str(clock)] if clock else []), capture_output=True, text=True, encoding="utf-8", timeout=60)
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else {"error": p.stderr[-300:]}


def n(x):
    return f"{x:,}"


def group_page(out):
    html = open(PAGE, encoding="utf-8").read()
    check(not re.search(r"innerHTML|<script[^>]*\ssrc=|<link\b|@import|<img\b|<iframe", html), "page: no markup injection, no external script, stylesheet or image")
    urls = sorted(set(re.findall(r"https?://[^\s\"')<>]+", html)))
    check(urls == ["http://www.w3.org/2000/svg", "https://github.com/loganw234/cft-fp256/commit/"], "page: the only absolute URLs are the SVG namespace and the commit link", urls)
    check("prefers-color-scheme: dark" in html and 'name="viewport"' in html, "page: light and dark, and a viewport")
    eq(re.search(r"SCHEMA = (\d+)", html).group(1), str(P.SCHEMA), "page: reads the schema the reducer writes")
    eq(re.search(r'DATA = "([^"]+)"', html).group(1), os.path.basename(DATA), "page: fetches the data file's name")
    if not NODE:
        return skip("page in node", "node is not on PATH, so the page's script is not run against its states")
    dj = os.path.join(TMP, "page-data.json")
    with open(dj, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    r = page("ok", dj)
    app, text = r.get("app", {}), r.get("app", {}).get("text", "")
    check(r.get("status", {}).get("hidden") is True and app.get("hidden") is False and len(text) > 500, "page: with the real shape, the status is gone and the page is shown", r.get("error"))
    want = [n(x["cases"]) for x in out["nights"]] + [n(out["totals"]["cases"]), n(out["totals"]["slices"]), f"{out['totals']['disagreements']} in {n(out['totals']['completed_slices'])} completed slices"]
    for c in out["now"]["classes"]:
        want += [f"{c['total']['complete']} of {c['total']['items']}", c["label"]] + [R._pct3(r["covered"], r["space"]) for r in c["items"]]
        want += [e for r in c["items"] if r["estimate"] for e in (r["estimate"]["date"],)]
    check("Made with the tools at commit" in text and "Data made at" not in text and "own commit" not in text,
          "page: the commit line says the file was made with the tools at that commit, and claims nothing of whether it is the file's own")
    miss = [w for w in want if w not in text]
    check(not miss, f"page: shows {len(want)} figures of the data file, each as the report's _pct3 and thousands separators write it", miss[:4])
    near = json.loads(json.dumps(out))
    row = next(r for c in near["now"]["classes"] for r in c["items"] if not r["complete"])
    row["covered"] = row["space"] - 1
    json.dump(near, open(dj, "w", encoding="utf-8"))
    json.dump(DERIVED[0], open(dj, "w", encoding="utf-8"))
    tn = page("ok", dj)["app"]["text"]
    lab = next(c["label"] for c in DERIVED[0]["now"]["classes"] if c["id"] == "t1")
    plain = json.loads(json.dumps(DERIVED[0]))
    for c in plain["now"]["classes"]:
        c.pop("derived_from_git", None)
    json.dump(plain, open(dj, "w", encoding="utf-8"))
    check(tn == page("ok", dj)["app"]["text"] and lab in tn and "Read from git" not in tn,
          "page: a class the report read from git adds no text under its label: the page's text is the same with and without the data file's "
          "derived_from_git, the label is in it, and no note under the label repeats the commit and the tree")
    json.dump(near, open(dj, "w", encoding="utf-8"))
    t2 = page("ok", dj)["app"]["text"]
    bad = json.loads(json.dumps(out))
    bad["nights"][1]["legs"]["timeout"] = 2
    bad["totals"]["legs"]["by_status"]["timeout"] = 2
    json.dump(bad, open(dj, "w", encoding="utf-8"))
    tt = page("ok", dj)["app"]["text"]
    check("2 timeout" in tt and ", timeout 2)" in tt and "2 timeout" not in text, "page: a leg that timed out is shown on its night and in the totals, not hidden behind 'failed'")
    check(R._pct3(row["space"] - 1, row["space"]) == "99.999%" and "99.999%" in t2, "page: an item one index short of complete is never shown as 100%")
    for name, mode, body, say in [("a missing file", "404", None, ["could not be loaded", "HTTP 404"]), ("a refused request", "reject", None, ["could not be loaded", "Failed to fetch"]),
                                  ("truncated JSON", "ok", json.dumps(out)[:900], ["is not valid JSON"]), ("an empty file", "ok", "", ["is not valid JSON"]),
                                  ("another schema", "ok", json.dumps(dict(out, schema=P.SCHEMA + 1)), ["not the shape", "schema"]),
                                  ("a list", "ok", "[]", ["not the shape"]), ("no nights", "ok", json.dumps(dict(out, nights=[])), ["not the shape", "nights"]),
                                  ("a class with no items", "ok", json.dumps(dict(out, now=dict(out["now"], classes=[{"id": "x", "kind": "tile", "label": "y"}]))), ["not the shape"])]:
        if body is not None:
            open(dj, "w", encoding="utf-8").write(body)
        r = page(mode, dj)
        check(r.get("status", {}).get("hidden") is False and all(s in r["status"]["text"] for s in say) and r["app"]["text"] == "" and r["app"]["hidden"] is True,
              f"page: {name} is named, and no figure is shown", r)


# ---------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------
def group_fixture():
    recs = build()
    if "--write-fixture" in sys.argv:
        with open(FIXTURE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in recs))
    want = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in recs)
    check(os.path.exists(FIXTURE) and open(FIXTURE, encoding="utf-8", newline="").read() == want, "fixture: the committed file is what the builder writes (--write-fixture remakes it)")
    d = write_run(recs, "base")
    out = reduce_dir(d, "e5" * 20)
    against_oracle(out, SPEC, recs)
    against_report(out, d, "fixture")
    raw_check(out, d, "fixture")
    eq(out["totals"]["disagreements"], 0, "fixture: no disagreement in 18 completed slices")
    rs = [r for r in recs if r["type"] == "run_start"]
    lab = [c["label"] for c in out["now"]["classes"] if c["kind"] == "tile"]
    eq(lab, [R.tree_class("tile", rs[0], rev=None)[1], R.tree_class("tile", rs[1], rev=None)[1]], "fixture: a class's label is the report's own (tree_class, the label --json gives), not reworded")
    check("not recorded" in lab[0] and "a1a1a1a1a1a1" in lab[0] and "RTL tree c3c3c3c3c3c3" in lab[1], "fixture: an unrecorded tree's label names the commit, as the report writes it", lab)
    wide = next(r for c in out["now"]["classes"] if c["id"] == "t2" for r in c["items"] if r["item"] == "scaleb32-wide-rne")
    eq((wide["first_gap"], wide["covered"]), ([0, A], 3 * A), "fixture: the current class's first gap is its own ([0, A)), though the whole run has covered every index")
    zero = next(r for c in out["now"]["classes"] if c["id"] == "t2" for r in c["items"] if r["item"] == "scaleb32-all-rne")
    eq((zero["covered"], zero["slices"], zero["first_gap"], zero["estimate"], zero["in_campaign"]), (0, 0, [0, EXH], None, True), "fixture: a campaign item nothing was swept for under the tree is listed at zero")
    text = P.dump(out)
    eq(P.dump(reduce_dir(d, "e5" * 20)), text, "fixture: the same run reduces to the same bytes")
    leaks = [s for s in ("fixture-box", "/data/", "fixtureuser", "Users", "xclbin", "u50-quad", "\\\\") if s in text]
    check(not leaks, "fixture: no host name, path or user name in the output", leaks)
    bare = [N1] + [n | {"slices": [x for x in n["slices"] if ITEMS[x[0]][3] != "host"]} for n in (N2, N3)]      # nothing swept on the host under the current tree
    rb = build(bare)
    db = write_run(rb, "nohost")
    pb = reduce_dir(db)
    against_oracle(pb, bare, rb)
    raw_check(pb, db, "nothing swept on the host under the current tree", plants=False)
    h2 = next(c for c in pb["now"]["classes"] if c["id"] == "h2")
    eq((h2["current"], h2["served"], h2["nights"], h2["total"]["covered"], h2["label"]),
       (True, False, [2, 3], 0, R.tree_class("host", [r for r in rb if r["type"] == "run_start"][1], rev=None)[1]),
       "fixture: a current class nothing was swept under is still listed, with the label the report's tree_class gives its night's tree (the summary has no entry for it)")
    check("d4d4d4d4d4d4" in h2["label"] and "compiler cc (Fixture) 1.0" in h2["label"], "fixture: and that label names the host tree and its compiler", h2["label"])

    def broken(kind, rs, rev=None):
        raise RuntimeError("tree_class is broken")
    real_tc, R.tree_class = R.tree_class, broken
    try:
        try:
            reduce_dir(db)
            raised = False
        except RuntimeError as e:
            raised = "tree_class is broken" in str(e)
    finally:
        R.tree_class = real_tc
    check(raised, "plant: a report whose tree_class raises fails the reduction, and nothing falls back to another label")

    def rev_stopped(commit, rel):                      # a rev whose git stopped with a message that names a directory: the report puts it in the label of a class kept apart
        return None
    rev_stopped.problem = "fatal: not a git repository: '/srv/elsewhere/checkout'"
    with_rev(rev_stopped)
    try:
        try:
            reduce_dir(d)
            why = None
        except P.Failed as e:
            why = str(e)
    finally:
        record_only(True)
    check(why is not None and "path" in why, "plant: a git problem that carries a path, in a class's label, is refused by name and not published", why)
    one = [N1 | {"tree": dict(TREE_B, commit="a1" * 20, host_src="e6" * 20)}, N2, N3]       # one RTL tree on every night, the host tree changing at night 2
    r1 = build(one)
    d1 = write_run(r1, "one-rtl")
    p1 = reduce_dir(d1)
    against_oracle(p1, one, r1)
    against_report(p1, d1, "one RTL tree over three nights")
    raw_check(p1, d1, "one RTL tree over three nights", plants=False)
    eq(([(c["id"], c["nights"]) for c in p1["now"]["classes"] if c["kind"] == "tile"], p1["now"]["classes"][0]["total"]["complete"]), ([("t1", [1, 2, 3])], 3),
       "fixture: a class that spans nights is one class, and an item complete on its first night is complete in it")
    N1d = N1 | {"tree": {"commit": "a1" * 20, "dirty": False, "dirty_files": 0, "rtl": "c3" * 20, "rtl_dirty": False}}      # night 1 as the report then takes it

    def rev_a1(commit, rel):                           # a rev that knows night 1's commit: its RTL tree is the one nights 2 and 3 recorded
        return "c3" * 20 if (commit, rel) == ("a1" * 20, "rtl") else None
    with_rev(rev_a1)
    try:
        pd = reduce_dir(d)
    finally:
        record_only(True)
    against_oracle(pd, [N1d, N2, N3], recs)
    eq({c["id"]: c.get("derived_from_git") for c in pd["now"]["classes"]}, {"t1": [{"commit": "a1a1a1a1a1a1", "dir": "rtl", "tree": "c3c3c3c3c3c3"}], "h1": None, "h2": None},
       "fixture: with the real report reading night 1's tree (through a rev), the tile class spans the three nights and carries the commit and tree it was read at; the others carry no such field")
    check("taken from the given rev" in next(c["label"] for c in pd["now"]["classes"] if c["id"] == "t1"), "fixture: and its label says where the tree came from")
    eq(sum("derived_from_git" in c for c in out["now"]["classes"]), 0, "fixture: with the record-only view the data file has no such field")
    DERIVED.append(pd)
    two = reduce_dir(write_run(build(SPEC[:2]), "two"))
    eq(two["nights"], out["nights"][:2], "fixture: the reduction of the first two nights is the first two nights of the reduction (nights only append)")
    return recs, out, d, text


def legacy(out):
    """The data file as the tools of 3ec0081c made it: a copy of `out` without the fields parcel HXd added (the rule text of the groups, a class's
    totals by group, a row's format and group, a night's state by group)."""
    j = json.loads(json.dumps(out))
    j["rules"].pop("groups", None)
    for c in j["now"]["classes"]:
        c.pop("groups", None)
        for r in c["items"]:
            r.pop("format", None)
            r.pop("group", None)
    for nt in j["nights"]:
        nt["after"].pop("groups", None)
    return j


def js_pct1(cov, space):
    """The page's pct1: toFixed(1) rounds the double's exact value half up (Python's %.1f rounds an exact tie to even), and an incomplete
    figure is never shown as 100.0."""
    from decimal import Decimal, ROUND_HALF_UP
    s = str(Decimal(100 * cov / space).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return ("99.9" if cov < space and s == "100.0" else s) + "%"


def group_base4():
    """The base run's four nights (BSPEC), reduced: what the wide run's older group is held to. Its truth is the oracle's too."""
    recs = build(BSPEC)
    d = write_run(recs, "base4")
    out = reduce_dir(d, "e5" * 20)
    against_oracle(out, BSPEC, recs)
    against_report(out, d, "four nights without wide items")
    return out, d


def group_wide_fixture(base, base_dir):
    """Parcel HXd. The synthetic run served the wide items too (WSPEC: four nights, the same trees and base slices as BSPEC, and from night 3 slices of
    the wide items of three kinds: hard cases, the fp32 slice at fp64, a low-bit window). Its truth is the oracle's, from the spec alone; the reducer's
    data and the report's agree with it, the base group's figures are the base run's (`base`: BSPEC reduced), unmoved, and the nights before any wide
    row are the nights they were."""
    recs = build(WSPEC, WCAMPAIGN)
    check(len(WSPEC) == len(BSPEC) == 4 and WSPEC[:2] == BSPEC[:2], "wide fixture: the wide run is the base run's four nights, the first two as they are")
    if "--write-fixture" in sys.argv:
        with open(FIXTURE_WIDE, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in recs))
    want = "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in recs)
    check(os.path.exists(FIXTURE_WIDE) and open(FIXTURE_WIDE, encoding="utf-8", newline="").read() == want,
          "wide fixture: the committed file is what the builder writes (--write-fixture remakes it)")
    d = write_run(recs, "wide")
    out = reduce_dir(d, "e5" * 20)
    against_oracle(out, WSPEC, recs, WCAMPAIGN)
    against_report(out, d, "wide fixture")
    raw_check(out, d, "wide fixture")
    cls = {c["id"]: c for c in out["now"]["classes"]}
    bcls = {c["id"]: c for c in base["now"]["classes"]}
    eq(sorted(cls), sorted(bcls), "wide fixture: the same classes as the run without wide items (the wide items are tile items and the trees are the same)")
    grp = lambda c, g: next((x for x in c["groups"] if x["group"] == g), None)
    w = grp(cls["t2"], "wide")
    # counted by hand from the spec: div128-hard whole (289,931,696), sqrt256-f64hard whole (4,456,448), sqrt64-f32 three quarters of 2**32, recip128-win-key
    # whole (2**32), sqrt128-hard at zero: 5 rows, 3 complete
    eq((w["items"], w["complete"], w["covered"], w["space"]), (5, 3, 289_931_696 + 4_456_448 + 3 * A + EXH, 289_931_696 + 4_456_448 + EXH + EXH + 4_456_448),
       "wide fixture: the current tile class's wide group, counted by hand: 5 rows (one at zero), 3 complete, what they cover and the space of the five")
    check(w["pct"] == 100.0 * w["covered"] / w["space"] and 87.0 < w["pct"] < 88.0, "wide fixture: and its share, about 87.9 per cent", w["pct"])
    eq([g["group"] for g in cls["t1"]["groups"]] + [g["group"] for g in cls["h1"]["groups"]] + [g["group"] for g in cls["h2"]["groups"]], ["base"] * 3,
       "wide fixture: a class with no wide row has the base group alone, as do the host classes (every wide item is a tile item)")
    for cid, c in cls.items():
        b = grp(c, "base")
        eq({k: v for k, v in b.items() if k != "group"}, bcls[cid]["total"], f"wide fixture: class {cid}: the base group's figures are the run without wide items' class total, unmoved by the wide group joining")
    t2 = cls["t2"]
    eq((t2["total"]["items"], t2["total"]["complete"], t2["total"]["covered"], t2["total"]["space"]),
       tuple(grp(t2, "base")[k] + w[k] for k in ("items", "complete", "covered", "space")), "wide fixture: and the class's total stays over both groups")
    eq(out["nights"][:2], base["nights"][:2], "wide fixture: nights 1 and 2, before any wide slice, are the nights they were in the run without wide items (every field, the state by group absent)")
    eq([("groups" in x["after"], sorted(x["after"].get("groups", {}))) for x in out["nights"]], [(False, []), (False, []), (True, ["t2"]), (True, ["t2"])],
       "wide fixture: a night's state by group is written from the first night a class has a wide row served, and for that class alone")
    eq(sorted(out["nights"][3]["after"]["groups"]["t2"]["wide"].items()), [("complete", 3), ("covered", w["covered"])], "wide fixture: night 4's state: the wide group's covered figure and its three complete rows")
    eq(out["nights"][2]["after"]["groups"]["t2"]["wide"], {"covered": 4_000_000 + A + 2 * A, "complete": 0}, "wide fixture: night 3's, counted by hand: 4,000,000 of div128-hard, a quarter of sqrt64-f32 and two of recip128-win-key's quarters")
    eq([(x["item"], x["night"]) for x in out["totals"]["fully_covered"] if x["class"] == "t2" and ITEMS[x["item"]][7] == "wide"],
       [("div128-hard-rne", 4), ("recip128-win-key-rne", 4), ("sqrt256-f64hard-rne", 4)], "wide fixture: the wide items fully covered, each with its night (all on night 4)")
    # the report's own totals by group for the same class, from the same records: the wide group three ways (the oracle's, counted by hand above; the reducer's;
    # the report's, over the four wide items it saw: the fifth, at zero, is the reducer's campaign row), and the base group as the report gave it for the run
    # without wide items
    Sw, _t, _rc = report_of(d, True)
    Sb, _t, _rc = report_of(base_dir, True)
    rw = next(c for c in Sw["sweep"]["trees"]["classes"] if c["kind"] == "tile" and c["label"] == t2["label"])
    rb = next(c for c in Sb["sweep"]["trees"]["classes"] if c["kind"] == "tile" and c["label"] == t2["label"])
    gw = {g["group"]: g for g in rw["total"]["by_group"]}
    eq((gw["wide"]["items"], gw["wide"]["covered"], gw["wide"]["total"], gw["wide"]["complete_items"]), (4, w["covered"], 289_931_696 + 4_456_448 + EXH + EXH, 3),
       "wide fixture: the wide group three ways - the report's totals by group, over the four wide items it saw, are the oracle's and the reducer's: covered, space, items complete")
    eq(gw["base"], rb["total"]["by_group"][0], "wide fixture: and the report's base group, with wide items in the run, is the one it gave the run without them (every field, each image's figure too)")
    eq(sorted(gw), ["base", "wide"], "wide fixture: and the report's class has the two groups")
    eq(P.dump(reduce_dir(d, "e5" * 20)), P.dump(out), "wide fixture: the same run reduces to the same bytes")
    return recs, out, d


def group_format_guard(wide_dir):
    """The reducer holds every string it publishes against the shape of a path. Every format of the table passes it, a format that has one is refused
    by name, and the check is on the strings of the data, not on the table."""
    bad = sorted(f for f in set(R.OP_FORMAT.values()) if P._PATHY.search(f) or P._IPV4.search(f))
    eq(bad, [], "format guard: none of the table's formats, nor the groups' rule text, has the shape of a path or an IP address (the reducer's own screen, _PATHY and _IPV4)")
    check(not P._PATHY.search(P.RULES["groups"]) and not P._IPV4.search(P.RULES["groups"]), "format guard: the rule text of the groups passes it too")
    for f in ("fp32 /srv/data/x", "fp32 -> /usr/lib", "D:/data/fp64", "fp32 10.0.0.7"):
        check(bool(P._PATHY.search(f) or P._IPV4.search(f)), f"format guard: the screen sees {f!r} (a control: it can fail)")
    saved = R.ITEM_FORMAT["div128-hard-rne"]
    R.ITEM_FORMAT["div128-hard-rne"] = "fp128 /srv/data/x"
    try:
        try:
            reduce_dir(wide_dir)
            why = None
        except P.Failed as e:
            why = str(e)
    finally:
        R.ITEM_FORMAT["div128-hard-rne"] = saved
    check(why is not None and "path" in why and "fp128 /srv" in why, "plant: an item whose format has the shape of a path fails the reduction by name, and nothing is published", why)


def group_wide_page(base, wide, golden):
    """The page over the wide run, in node: the base block of the headline as it reads without wide items, the wide group beside it and listed as its
    own group, a format on every item row, and the chart with a line a class and group - the older group's lines unmoved. Over a data file without
    the new fields the page draws exactly what the page of 3ec0081c drew (`golden`: the digest of its tree)."""
    if not NODE:
        return skip("the page with wide items in node", "node is not on PATH")
    bj, wj, lj = (os.path.join(TMP, x) for x in ("pg-base.json", "pg-wide.json", "pg-legacy.json"))
    for path, j in ((bj, base), (wj, wide), (lj, legacy(base))):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(j, fh)
    rb, rw, rl = page("ok", bj), page("ok", wj), page("ok", lj, clock=golden["clock"])
    check(all(r.get("status", {}).get("hidden") is True and r.get("app", {}).get("hidden") is False for r in (rb, rw, rl)), "wide page: the run without wide items, the run with them and the legacy file are each shown", [r.get("error") for r in (rb, rw, rl)])
    eq(rl.get("dom"), golden["digest"], "wide page: over a data file without the new fields (the run without wide items as 3ec0081c's reducer made it) the tree the page draws is the page of 3ec0081c's, node for node")
    tb, tw = rb["app"]["text"], rw["app"]["text"]
    t2 = next(c for c in wide["now"]["classes"] if c["id"] == "t2")
    t2b = next(c for c in base["now"]["classes"] if c["id"] == "t2")
    bg, wg = (next(g for g in t2["groups"] if g["group"] == x) for x in ("base", "wide"))
    base_says = [f"{bg['complete']} of {bg['items']}", js_pct1(bg["covered"], bg["space"]), f"of the campaign's {n(bg['space'])} encodings or indices ({n(bg['covered'])} covered)"]
    check(all(s in tb for s in base_says) and all(s in tw for s in base_says) and base_says == [f"{t2b['total']['complete']} of {t2b['total']['items']}", js_pct1(t2b["total"]["covered"], t2b["total"]["space"]), f"of the campaign's {n(t2b['total']['space'])} encodings or indices ({n(t2b['total']['covered'])} covered)"],
          "wide page: the base group's block of the headline states, with wide items, what the class's card stated without them", base_says)
    wide_says = [f"{wg['complete']} of {wg['items']}", js_pct1(wg["covered"], wg["space"]), f"of the campaign's {n(wg['space'])} encodings or indices ({n(wg['covered'])} covered)"]
    check(all(s in tw for s in wide_says) and "wide-format items" in tw and "Wide-format items" not in tb and "wide-format items" not in tb,
          "wide page: the wide group's block is in the card beside it, with its own count, share and space, and there is none in the run without wide items", wide_says)
    sec = tw[tw.index("Item by item"):]
    start = sec.index(f"tile items - {t2['label']}")
    nxt = [sec.find(k, start + 10) for k in ("tile items - ", "host items - ", "Earlier trees, item by item")]
    block = sec[start:min([x for x in nxt if x > 0] or [len(sec)])]
    head = f"Wide-format items: {wg['complete']} of {wg['items']} fully covered"
    at = block.find(head)
    names_w = [r["item"] for r in t2["items"] if r["group"] == "wide"]
    names_b = [r["item"] for r in t2["items"] if r["group"] == "base"]
    check(at > 0 and f"Base items: {bg['complete']} of {bg['items']} fully covered" in block and all(block.find(x) > at for x in names_w) and all(0 < block.find(x) < at for x in names_b),
          "wide page: in the class's item list the base items come first and the wide items are listed after their own heading, as a group of their own", (at, names_w))
    miss = []
    for c in wide["now"]["classes"]:
        for r in c["items"]:
            lvl = {"hard": "hard-case ", "class": "class level "}.get(r["level"], "")
            if not re.search(re.escape(r["item"]) + r" " + re.escape(lvl) + re.escape(r["format"]) + r"( |$)", sec):
                miss.append((c["id"], r["item"], r["format"]))
    check(not miss, "wide page: every item row of every class shows the format it computes in, after its name and level tag (a conversion, both ends)", miss[:3])
    # the chart: one line a class, and for a class with wide items one a group; the older groups' lines are the run without wide items' lines, point for point
    cb, cw = rb["chart"], rw["chart"]
    is_wide = lambda ln: bool(ln["titles"]) and "(wide-format items)" in ln["titles"][0]
    rest = [ln for ln in cw if not is_wide(ln)]
    eq((len(cb), len(cw), len(rest)), (4, 5, 4), "wide page: the chart has a line for each of the four classes, and one more, the wide group's, with wide items")
    eq([len(ln["points"].split()) for ln in rest], [len(ln["points"].split()) for ln in cb], "wide page: and the base lines have the points they had, one a night of their class")
    eq([ln["points"] for ln in rest], [ln["points"] for ln in cb], "wide page: and every other line - the base group's of t2 among them - is the line of the run without wide items, point for point: an older group's history is not redrawn")
    wl = [ln for ln in cw if is_wide(ln)][0]
    cov_at = {k: wide["nights"][k - 1]["after"]["groups"]["t2"]["wide"]["covered"] for k in (3, 4)}
    want = [f"tile {t2['label']} (wide-format items): night {k}, {js_pct1(cov_at[k], wg['space'])} ({n(cov_at[k])} of {n(wg['space'])})" for k in (3, 4)]
    eq(wl["titles"], want, "wide page: the wide group's line starts on the first night it had anything covered (night 3, not the class's first, night 2) and each point is that night's covered figure over the group's own space")
    check(wl["style"] != rest[2]["style"] and "--s3" in wl["style"] and wl["style"].replace("--s3", "--s1") == rest[2]["style"], "wide page: in its own colour, the class's solid line (the current tree's) otherwise", (wl["style"], rest[2]["style"]))
    for name, edit, say in (("a groups field that is not a list", lambda j: j["now"]["classes"][2].__setitem__("groups", {}), "groups of class t2"),
                            ("a group without its space", lambda j: j["now"]["classes"][2]["groups"][0].pop("space"), "groups of class t2"),
                            ("a format that is a number", lambda j: j["now"]["classes"][2]["items"][0].__setitem__("format", 5), "format of an item of class t2")):
        j = json.loads(json.dumps(wide))
        edit(j)
        with open(wj, "w", encoding="utf-8") as fh:
            json.dump(j, fh)
        r = page("ok", wj)
        check(r.get("status", {}).get("hidden") is False and "not the shape" in r["status"]["text"] and say in r["status"]["text"] and r["app"]["text"] == "",
              f"wide page: {name} is named as not the shape this page reads, and no figure is shown", r.get("status"))
    # a tree that is no longer current but has wide items (the RTL tree changed after they ran): the list of earlier trees states both groups, not the class's total
    j = json.loads(json.dumps(wide))
    for c in j["now"]["classes"]:
        c["current"] = False
    with open(wj, "w", encoding="utf-8") as fh:
        json.dump(j, fh)
    te = page("ok", wj).get("app", {}).get("text", "")
    stated = (f"{t2['label']} : {bg['complete']} of {bg['items']} items fully covered, {js_pct1(bg['covered'], bg['space'])} ({n(bg['covered'])} of {n(bg['space'])}); "
              f"wide-format items: {wg['complete']} of {wg['items']} items fully covered, {js_pct1(wg['covered'], wg['space'])} ({n(wg['covered'])} of {n(wg['space'])}), nights 2, 3, 4")
    check(stated in te, "wide page: an earlier tree with wide items is listed with both groups' figures, not the class's total", stated)


def group_check(d, text, out):
    # the data file is made by the command itself, so that --check re-derives it in the view it was made in: the command's default reads git of the
    # checkout, whose reasons the labels of a class with a made-up commit carry (the in-process fixture groups read the records alone)
    f = os.path.join(TMP, "data.json")
    eq(cli(d, "--out", f, "--commit", "none")[0], 0, "check: the command makes the data file from the fixture run (control)")
    text = open(f, encoding="utf-8").read()
    rc, so, se = cli("--check", f, d)
    eq(rc, 0, f"check: the file made from the run is the run's reduction (control)")
    # plants in the run: each must change the reduction, and --check of the old file must name what changed
    plants = {
        "a disagreement": (build([N1, N2 | {"slices": N2["slices"][:2] + [("rint64-class-rne", 0, 35840, "fail")] + N2["slices"][3:]}, N3]), ["totals.disagreements", "nights[1]"]),
        "a fourth night": (build(SPEC + [{"tree": TREE_B, "battery": [("api-test", "pass")], "slices": [("div32-hard-rne", 10_000_000, 12_000_000)]}]), ["nights", "totals.nights"]),
        "a tree change": (build([N1, N2, N3 | {"tree": TREE_C}]), ["now.classes", "nights[2].classes"]),
        "a night with no run_end": (build([N1, N2, N3 | {"no_end": True}]), ["newest.closed", "nights[2].closed"]),
    }
    for name, (recs, names) in plants.items():
        pd = write_run(recs, name.replace(" ", "-"))
        rc, so, se = cli("--check", f, pd)
        eq(rc, 1, f"plant, {name}: --check of last night's file against the changed run fails")
        check(all(s in se for s in names), f"plant, {name}: and names the fields {names}", se[-300:])
    po = reduce_dir(write_run(plants["a disagreement"][0], "dis2"))
    eq((po["totals"]["disagreements"], po["totals"]["disagreement_list"][0]["item"], po["nights"][1]["legs"]["fail"]), (1, "rint64-class-rne", 2), "plant, a disagreement: counted once, by item, and a failed leg on its night")
    against_oracle(po, [N1, N2 | {"slices": N2["slices"][:2] + [("rint64-class-rne", 0, 35840, "fail")] + N2["slices"][3:]}, N3], plants["a disagreement"][0])
    p4 = reduce_dir(write_run(plants["a fourth night"][0], "four"))
    eq((p4["totals"]["nights"], p4["newest"]["night"], p4["nights"][:3] == out["nights"]), (4, 4, True), "plant, a fourth night: four nights, the first three as before")
    p3 = reduce_dir(write_run(plants["a tree change"][0], "tree"))
    eq((p3["nights"][2]["classes"], [c["id"] for c in p3["now"]["classes"] if c["current"]]), ({"tile": "t3", "host": "h3"}, ["t3", "h3"]), "plant, a tree change: the last night counts under new classes, which are current")
    against_oracle(p3, [N1, N2, N3 | {"tree": TREE_C}], plants["a tree change"][0])
    cur = {r["item"]: r["covered"] for c in p3["now"]["classes"] if c["id"] == "t3" for r in c["items"]}
    eq((cur["scaleb32-wide-rne"], cur["rint64-class-rne"]), (A, 0), "plant, a tree change: the new class holds only the night's own slices; what an earlier tree covered is not carried to it")
    p5 = reduce_dir(write_run(plants["a night with no run_end"][0], "open"))
    eq((p5["newest"]["closed"], p5["nights"][2]["reason"], p5["nights"][2]["end"] is not None), (False, None, True), "plant, no run_end: the night is open, has no reason, and ends at its last record")
    # plants in the data file
    for name, edit, names in [("a figure changed", lambda j: j["totals"].__setitem__("slices", j["totals"]["slices"] + 1), "totals.slices"),
                              ("a night's cases changed", lambda j: j["nights"][1].__setitem__("cases", 7), "nights[1].cases"),
                              ("an item's first gap changed", lambda j: j["now"]["classes"][2]["items"][0].__setitem__("first_gap", None), "first_gap"),
                              ("the run's hash changed", lambda j: j["source"].__setitem__("metrics_sha256", "0" * 64), "source.metrics_sha256"),
                              ("a key removed", lambda j: j.pop("rules"), "rules")]:
        j = json.loads(text)
        edit(j)
        open(f, "w", encoding="utf-8").write(P.dump(j))
        rc, so, se = cli("--check", f, d)
        check(rc == 1 and names in se, f"plant, the data file with {name}: --check fails and names {names}", (rc, se[-200:]))
    j = json.loads(text)
    j["made"]["commit"] = "9" * 40
    open(f, "w", encoding="utf-8").write(P.dump(j))
    eq(cli("--check", f, d)[0], 0, "control: a different commit in `made` is not a difference (it cannot be re-derived)")
    for name, edit in [("no made block", lambda j: j.pop("made")), ("a made.commit that is not a commit", lambda j: j["made"].__setitem__("commit", "xyz")),
                       ("an uppercase made.commit", lambda j: j["made"].__setitem__("commit", "A" * 40)), ("a short made.commit", lambda j: j["made"].__setitem__("commit", "a" * 39))]:
        j = json.loads(text)
        edit(j)
        open(f, "w", encoding="utf-8").write(P.dump(j))
        eq(cli("--check", f, d)[0], 2, f"check: a file with {name} is not a data file: status 2, as the exit table says, not 1")
    for name, body in [("missing", None), ("not JSON", "{"), ("a list", "[]")]:
        if body is None:
            os.remove(f)
        else:
            open(f, "w", encoding="utf-8").write(body)
        eq(cli("--check", f, d)[0], 2, f"check: a {name} data file is 2, nothing to check")


def group_refusals(recs):
    def run(name, rs=None, extra=None, want=2, say=None):
        d = write_run(rs if rs is not None else recs, name, extra)
        out = os.path.join(TMP, name + ".json")
        rc, so, se = cli(d, "--out", out, "--commit", "none")
        check(rc == want and (say is None or say in se) and (want == 0 or not os.path.exists(out)), f"{name}: status {want}{', ' + say if say else ''}, and a refusal writes nothing", (rc, se[-200:]))
        return d, out
    lines = lambda t: t.split("\n")
    run("malformed-middle", extra=lambda t: "\n".join(lines(t)[:10] + ["{not json"] + lines(t)[10:]), say="unparsable line")
    d, out = run("torn-tail", extra=lambda t: t + '{"type":"leg","sta', want=0)
    eq(json.load(open(out))["source"]["partial_tail"], True, "torn tail: a last line caught mid-append is noted, not refused")
    run("empty", extra=lambda t: "", say="holds no record")
    run("no-run-start", rs=[r for r in recs if r["type"] != "run_start"], say="no run_start")
    run("records-before-start", rs=recs[1:2] + recs, say="before the first run_start")
    run("dry-run", rs=build([N1, N2 | {"dry": True}, N3]), say="night 2 is a dry run")
    rc, so, se = cli(os.path.join(TMP, "nowhere"), "--commit", "none")
    check(rc == 2 and "not a directory" in se, "a directory that is not there: status 2")
    # the guard, by name: each leak must be refused (3) and the control beside it must not be
    leaks = {"a path in the compiler line": ("cc /usr/bin/cc 1.0", "path"), "the host's name": ("cc fixture-box 1.0", "private text"),
             "the user's name": ("cc fixtureuser 1.0", "private text"), "an IP address": ("cc 10.0.0.7 1.0", "IP")}
    for name, (cc, say) in leaks.items():
        run("leak-" + name.replace(" ", "-"), rs=build([N1, N2 | {"tree": dict(TREE_B, cc=cc)}, N3]), want=3, say=say)
    linux = [dict(r, images={k: dict(v, path="/ho" + "me/fixtureuser2/x.xclbin") for k, v in r["images"].items()}) if r["type"] == "run_start" else r for r in build([N1, N2 | {"tree": dict(TREE_B, cc="cc fixtureuser2 1.0")}, N3])]
    run("leak-a-user-name-from-a-linux-home-path", rs=linux, want=3, say="private text")
    run("no-leak-control", rs=build([N1, N2 | {"tree": dict(TREE_B, cc="cc (Fixture) 13.3.0-6ubuntu2~24.04.1")}, N3]), want=0)
    d, out = run("reason-withheld", rs=build([N1, N2, N3 | {"reason": "stopped by fixtureuser on fixture-box"}]), want=0)
    if os.path.exists(out):
        j = json.load(open(out))
        eq((j["nights"][2]["reason"], j["nights"][2]["reason_withheld"], "fixtureuser" in open(out).read()), (None, True, False), "a run_end reason that is not a plain word is withheld, and says so")
    big = [dict(r, counts=dict(r["counts"], cases=2 ** 60)) if r["type"] == "leg" and r.get("kind") == "sweep" else r for r in recs]
    run("past-2-53", rs=big, want=3, say="2**53")


def group_real(runs):
    done = []
    for d in runs:
        objs, info = P.load(d)
        out = json.loads(P.dump(P.reduce_records(objs, info, None)))
        tag = os.path.basename(os.path.dirname(os.path.normpath(d)))
        rows = against_report(out, d, tag, git_free=False)
        print(f"  {tag}: {out['totals']['nights']} nights, metrics sha256 {info['sha256'][:12]}, {len(rows)} figures compared with the report's")
        for name, a, b in rows[:13]:
            print(f"      {name:<62} reducer {a!s:<24.24} report {b!s:<24.24} {'=' if a == b else 'DIFFERS'}")
        eq(sum(x["slices"] for x in out["nights"]), out["totals"]["slices"], "real: the nights' slices add to the total")
        n_raw = raw_check(out, d, tag)
        print(f"  {tag}: {n_raw} class-level rows (covered, slices, cases, first uncovered index) recomputed from the raw records, independently of summarize(): all agree")
        if os.path.exists(DATA) and json.load(open(DATA, encoding="utf-8"))["source"]["metrics_sha256"] == info["sha256"]:
            n_file = raw_check(json.load(open(DATA, encoding="utf-8")), d, tag + ", the committed data file", plants=False)
            print(f"  {tag}: and the {n_file} rows of the committed data file (site/nightly.json), which is this copy's reduction")
        done.append((out, info))
    if len(done) == 2:
        (a, ia), (b, ib) = sorted(done, key=lambda x: x[0]["totals"]["nights"])
        if a["totals"]["nights"] < b["totals"]["nights"]:
            eq(b["nights"][:a["totals"]["nights"]], a["nights"], "real: the shorter copy's nights are the longer copy's first nights (what makes the file append night by night)")


def group_committed():
    if not os.path.exists(DATA):
        return skip("the committed data file", f"{os.path.relpath(DATA, ROOT)} is not there")
    text = open(DATA, encoding="utf-8").read()
    j = json.loads(text)
    eq(j["schema"], P.SCHEMA, "committed data: its schema is the reducer's")
    check(j["made"]["commit"] is None or re.fullmatch(r"[0-9a-f]{40}", j["made"]["commit"]), "committed data: made at a commit, or says none")
    check(not P._PATHY.search(text) and not P._IPV4.search(text) and not re.search(r"amd" r"-arc|logan|/data|/ho" r"me|Users", text), "committed data: no path, IP, host name or user name")
    eq(sum(x["slices"] for x in j["nights"]), j["totals"]["slices"], "committed data: the nights' slices add to the total")
    if NODE:
        r = page("ok", DATA)
        check(r.get("app", {}).get("hidden") is False and r["status"]["hidden"] is True, "committed data: the page shows it", r.get("error"))
        # parcel HXd: night 7's file, as 3ec0081c committed it (it has none of the new fields), is drawn as it was drawn. The check stands for as long as the
        # committed file is that one; the morning routine replaces it with a file made by these tools, and then the check is SKIPPED BY NAME (send-back 1,
        # N1: it used to vanish without a word), while the legacy check of the page's group covers a data file without the new fields
        have = hashlib.sha256(open(DATA, "rb").read()).hexdigest()
        if have == NIGHT7_SHA256:
            eq(page("ok", DATA, clock=NIGHT7_CLOCK).get("dom"), NIGHT7_DOM, "committed data: while the file is night 7's, as 3ec0081c committed it, the page draws the tree it drew then, node for node")
        else:
            skip("committed data: the page's tree over night 7's file",
                 f"{os.path.relpath(DATA, ROOT).replace(os.sep, '/')} is no longer the night-7 file 3ec0081c committed (its sha256 begins {have[:12]}, night 7's {NIGHT7_SHA256[:12]}), so "
                 "NIGHT7_DOM, the digest of the tree the old page drew over that file, does not apply to it; expected once the morning routine has replaced it (the check and the "
                 "three NIGHT7_ constants can then be retired)")
    else:
        skip("committed data in the page", "node is not on PATH")


def guarded(fn, *args):
    """A group that crashes is a failed check naming it, not the end of the run (the planted defects crash some of them)."""
    try:
        return fn(*args)
    except Exception as e:
        check(False, f"{fn.__name__} crashed", f"{type(e).__name__}: {e}")


def main():
    global TMP, NODE
    NODE = shutil.which("node")
    TMP = tempfile.mkdtemp(prefix="np-test-")
    record_only(True)
    try:
        print("== fixture: the oracle, the report, the bytes")
        got = guarded(group_fixture)
        if got:
            recs, out, d, text = got
            print("== --check, and the plants in the run and in the file")
            guarded(group_check, d, text, out)
            print("== refusals and the guard")
            guarded(group_refusals, recs)
            print("== the page")
            guarded(group_page, out)
            print("== the wide items: the same four nights, with the wide items served from the third (parcel HXd)")
            b4 = guarded(group_base4)
            wgot = guarded(group_wide_fixture, *b4) if b4 else None
            if wgot:
                _wrecs, wout, wd = wgot
                guarded(group_format_guard, wd)
                guarded(group_wide_page, b4[0], wout, {"clock": LEGACY_CLOCK, "digest": LEGACY_DOM})
        print("== the committed data file")
        guarded(group_committed)
        print("== the lead's real copies")
        runs = [x for x in os.environ.get("CARD_STRESS_PROGRESS_RUNS", "").split(os.pathsep) if x]
        record_only(False)
        if runs and all(os.path.isfile(os.path.join(x, "metrics.jsonl")) for x in runs):
            guarded(group_real, runs)
        else:
            skip("the real copies", "CARD_STRESS_PROGRESS_RUNS does not name run directories holding a metrics.jsonl (the lead's box/nightly-1021/run and box/resume-1020/run)")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"progress test: {st['n']} checks, {st['f']} failed, {st['skips']} skipped")
    return 1 if st["f"] else 0


if __name__ == "__main__":
    sys.exit(main())
