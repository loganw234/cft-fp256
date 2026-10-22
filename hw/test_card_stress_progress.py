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

The last line is "progress test: N checks, F failed, K skipped"; the exit status is 0 only if F is 0.
"""
import sys
sys.dont_write_bytecode = True

import calendar
import datetime
import hashlib
import inspect
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
st = {"n": 0, "f": 0, "skips": 0}
DERIVED = []
_SUMMARIZE = R.summarize
_HAS_REV = "rev" in inspect.signature(R.summarize).parameters      # the report derives an unrecorded tree from git when it takes `rev`


def record_only(on):
    """The fixture's commits are made up, so its groups need no git: where summarize() takes `rev` they pass rev=None (the record-only view,
    the CLI's --no-git). The real copies use the defaults, which are what `card_stress_report.py --json` shows."""
    R.summarize = (lambda *a, **k: _SUMMARIZE(*a, **dict(k, rev=k.get("rev")))) if (on and _HAS_REV) else _SUMMARIZE


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
ITEMS = {                                              # tool, op, mode, reach, space, cases an index
    "conv32to64-all": ("clause5", "conv32to64-all", None, "host", EXH, 1),
    "scaleb32-all-rne": ("clause5", "scaleb32-all", "rne", "tile", EXH, 17),
    "scaleb32-wide-rne": ("clause5", "scaleb32-wide", "rne", "tile", EXH, 568),
    "rint64-class-rne": ("clause5", "rint64-class", "rne", "tile", 35840, 4),
    "div32-hard-rne": ("divsqrt", "div32-hard", "rne", "tile", 21235788, 4),
}
CAMPAIGN = list(ITEMS)
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


def local(e):
    return time.strftime(FMT, time.gmtime(e + OFF))


def build(spec=SPEC):
    """The records of the spec's nights, a night a day, in the order and with the fields the driver writes (the ones read)."""
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
            argv=(["--resume"] if k else []) + ["--out", "/data/fixture-run", "--rev8-images", "/Users/fixtureuser/images", "--sweep-items", ",".join(CAMPAIGN)],
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
                tool, op, mode, reach, _space, per = ITEMS[item]
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
        night = {"legs": Counter(), "slices": 0, "cases": 0, "card": 0, "dis": 0, "ids": {}, "state": {}}
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
            status, (_t, _o, _m, reach, _sp, per) = (s[0] if s else "pass"), ITEMS[item]
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


def against_oracle(out, spec, recs):
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
        names = sorted(set(o["iv"]) | (set(i for i in CAMPAIGN if ITEMS[i][3] == o["kind"]) if cur else set()))
        eq([r["item"] for r in c["items"]], names, f"class {c['id']}: its items (a current class lists the campaign's at zero)")
        for r in c["items"]:
            i, iv = r["item"], o["iv"].get(r["item"], [])
            cov = sum(h - lo for lo, h in union(iv))
            want = {"space": ITEMS[i][4], "covered": cov, "slices": o["n"].get(i, 0), "cases": o["cases"].get(i, 0), "complete": cov == ITEMS[i][4],
                    "complete_night": o["done"].get(i), "first_gap": first_gap(iv, ITEMS[i][4]), "estimate": estimate(o, i, n, date) if cur and cov < ITEMS[i][4] else None}
            eq({k: r[k] for k in want}, want, f"class {c['id']} {i}: space, covered, slices, cases, complete, night, first gap, estimate")
        eq(c["total"], {"items": len(names), "complete": sum(r["complete"] for r in c["items"]), "covered": sum(r["covered"] for r in c["items"]),
                        "space": sum(ITEMS[i][4] for i in names), "pct": 100.0 * sum(r["covered"] for r in c["items"]) / sum(ITEMS[i][4] for i in names)},
           f"class {c['id']}: total")


# ---------------------------------------------------------------------------
# the reducer against the report: every figure both state
# ---------------------------------------------------------------------------
def report_of(d, git_free):
    j = os.path.join(TMP, "report-%s.json" % hashlib.sha256(d.encode()).hexdigest()[:8])
    nogit = ["--no-git"] if git_free and "--no-git" in cli("--help", script=REPORT)[1] else []
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
        f.append((f"class {rc['label'][:40]}: covered", c["total"]["covered"], rc["total"]["covered"]))
        rows = {r["item"]: r for r in c["items"]}
        for e in rc["exhaustive"]:
            r = rows.get(e["item"], {})
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
const [html, mode, dataPath] = process.argv.slice(2);
const m = /<script>([\s\S]*?)<\/script>/.exec(fs.readFileSync(html, "utf8"));
class T { constructor(t) { this.text = t; } get textContent() { return this.text; } }
class N {
  constructor(tag) { this.tag = tag; this.kids = []; this.attrs = {}; this.style = {}; this.hidden = false; this.className = ""; }
  appendChild(c) { if (c.frag) { this.kids.push(...c.kids); c.kids = []; } else this.kids.push(c); return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  get textContent() { return this.kids.map(k => k.textContent).join(" "); }
  set textContent(v) { this.kids = v === "" ? [] : [new T(String(v))]; }
}
const els = { status: new N("div"), app: new N("div") };
const document = { createElement: t => new N(t), createElementNS: (ns, t) => new N(t), createTextNode: s => new T(s),
  createDocumentFragment: () => Object.assign(new N("#frag"), { frag: true }), getElementById: id => els[id], documentElement: { clientWidth: 900 } };
const resp = (ok, status, text) => ({ ok, status, statusText: ok ? "OK" : "Not Found", text: () => Promise.resolve(text) });
const fetch = () => mode === "reject" ? Promise.reject(new TypeError("Failed to fetch")) :
  Promise.resolve(mode === "404" ? resp(false, 404, "") : resp(true, 200, fs.readFileSync(dataPath, "utf8")));
vm.runInNewContext(m[1], { document, window: { addEventListener() {} }, fetch, Date, setTimeout, clearTimeout, console });
setTimeout(() => console.log(JSON.stringify({ status: { hidden: els.status.hidden, text: els.status.textContent },
  app: { hidden: els.app.hidden, text: els.app.textContent } })), 300);
'''


def page(mode, data=None):
    h = os.path.join(TMP, "harness.js")
    if not os.path.exists(h):
        with open(h, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(HARNESS)
    p = subprocess.run([NODE, h, PAGE, mode, data or ""], capture_output=True, text=True, encoding="utf-8", timeout=60)
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
    miss = [w for w in want if w not in text]
    check(not miss, f"page: shows {len(want)} figures of the data file, each as the report's _pct3 and thousands separators write it", miss[:4])
    near = json.loads(json.dumps(out))
    row = next(r for c in near["now"]["classes"] for r in c["items"] if not r["complete"])
    row["covered"] = row["space"] - 1
    json.dump(near, open(dj, "w", encoding="utf-8"))
    json.dump(DERIVED[0], open(dj, "w", encoding="utf-8"))
    tn = page("ok", dj)["app"]["text"]
    check("Read from git, not recorded by the run: rtl tree f7f7f7f7f7f7 of commit a1a1a1a1a1a1." in tn and "Read from git" not in text,
          "page: a class the report read from git gets a note under it, and a data file without the field none")
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
    eq(out["totals"]["disagreements"], 0, "fixture: no disagreement in 18 completed slices")
    eq([c["label"] for c in out["now"]["classes"] if c["kind"] == "tile"], ["commit a1a1a1a, tree not recorded in the run", "RTL tree c3c3c3c3c3c3"], "fixture: an unrecorded tree is said plainly, by its commit")
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
    pb = reduce_dir(write_run(rb, "nohost"))
    against_oracle(pb, bare, rb)
    h2 = next(c for c in pb["now"]["classes"] if c["id"] == "h2")
    eq((h2["current"], h2["served"], h2["nights"], h2["total"]["covered"], h2["label"]), (True, False, [2, 3], 0, "host/ tree d4d4d4d4d4d4, compiler cc (Fixture) 1.0"),
       "fixture: a current class nothing was swept under is still listed, as its night's tree names it (the report has no entry for it)")
    one = [N1 | {"tree": dict(TREE_B, commit="a1" * 20, host_src="e6" * 20)}, N2, N3]       # one RTL tree on every night, the host tree changing at night 2
    r1 = build(one)
    d1 = write_run(r1, "one-rtl")
    p1 = reduce_dir(d1)
    against_oracle(p1, one, r1)
    against_report(p1, d1, "one RTL tree over three nights")
    eq(([(c["id"], c["nights"]) for c in p1["now"]["classes"] if c["kind"] == "tile"], p1["now"]["classes"][0]["total"]["complete"]), ([("t1", [1, 2, 3])], 3),
       "fixture: a class that spans nights is one class, and an item complete on its first night is complete in it")
    base_summarize = R.summarize

    def derived(*a, **k):                              # a stand-in for the report after parcel RG: night 1's tile class says it was read from git
        S = base_summarize(*a, **k)
        for c in S["sweep"]["trees"]["classes"]:
            if c["kind"] == "tile" and c["key"].startswith("unrecorded:"):
                c["derived_from_git"] = [{"commit": c["key"][11:], "dir": "rtl", "tree": "f7" * 20}]
        return S
    R.summarize = derived
    try:
        pd = reduce_dir(d)
    finally:
        R.summarize = base_summarize
    eq({c["id"]: c.get("derived_from_git") for c in pd["now"]["classes"]}, {"t1": [{"commit": "a1a1a1a1a1a1", "dir": "rtl", "tree": "f7f7f7f7f7f7"}], "h1": None, "t2": None, "h2": None},
       "fixture: a class the report read from git carries its commits and trees, and the others carry no such field")
    eq(sum("derived_from_git" in c for c in out["now"]["classes"]), 0, "fixture: with a report that has no such field the data file has none")
    DERIVED.append(pd)
    two = reduce_dir(write_run(build(SPEC[:2]), "two"))
    eq(two["nights"], out["nights"][:2], "fixture: the reduction of the first two nights is the first two nights of the reduction (nights only append)")
    return recs, out, d, text


def group_check(d, text, out):
    f = os.path.join(TMP, "data.json")
    open(f, "w", encoding="utf-8", newline="\n").write(text)
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
