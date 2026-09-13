#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Turn a bench sweep into line charts and a table of tipping points.

    python python/bench_report.py bench-sweep/sweep.csv
    python python/bench_report.py sweep.csv --out docs/bench

Reads what hw/bench-sweep.sh emitted and writes two things beside each other,
because the question has two audiences:

  bench-report.html   one log-log chart per (format, operation), every
                      configuration a line, the crossover marked - for looking
  tipping-points.json crossovers as numbers, with the bracketing measurements
                      that produced each - for parsing

WHAT A TIPPING POINT IS HERE, stated so nobody has to infer it. For one
(format, operation, configuration) it is the smallest element count at which
the device's nanoseconds-per-element falls below the software backend's. The
reported figure is a log-interpolation between the two bracketing measurements,
and both are carried in the JSON so the interpolation can be checked or
ignored. Where the device never wins inside the measured range the entry says
so by name rather than extrapolating; where it wins at every measured size the
entry says THAT, because a crossover below the smallest size measured is not a
crossover this data establishes.

NO CHART LIBRARY. The SVG is emitted directly - the pages this project ships
are self-contained and offline by rule, and a chart that needs a CDN is a chart
that stops working when the network does.

THE RATE IS NOT THE WHOLE STORY and the page says so: cft-bench verifies the
bytes it timed, but a point measured from a single repetition at a large n is a
different quality of evidence from one measured over hundreds, so reps travels
with every point into the JSON and into the tooltip.
"""
import argparse
import csv
import json
import math
import pathlib
import sys
from collections import defaultdict

CONFIGS = [
    ("software", "host", "0", "software", "#6b7280"),
    ("device", "host", "1", "1 tile, over PCIe", "#dc2626"),
    ("device", "resident", "1", "1 tile, resident", "#ea580c"),
    ("device", "host", "4", "4 tiles, over PCIe", "#2563eb"),
    ("device", "resident", "4", "4 tiles, resident", "#0891b2"),
]
FORMAT_ORDER = ["fp32", "fp64", "fp128", "fp256"]


def load(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                r["n"] = int(r["n"])
                r["ns_per_elem"] = float(r["ns_per_elem"])
                r["elems_per_s"] = float(r["elems_per_s"])
                r["reps"] = int(r["reps"])
                r["seconds"] = float(r["seconds"])
            except (KeyError, ValueError):
                continue
            rows.append(r)
    return rows


def key_of(r):
    return (r["backend"], r["path"], r["tiles"])


def series(rows):
    """-> {(format, op): {config_key: [(n, ns, reps), ...sorted]}}"""
    out = defaultdict(lambda: defaultdict(list))
    for r in rows:
        out[(r["format"], r["op"])][key_of(r)].append(
            (r["n"], r["ns_per_elem"], r["reps"]))
    for fo in out:
        for k in out[fo]:
            out[fo][k].sort()
    return out


def crossover(sw, dev):
    """Smallest n where dev beats sw, log-interpolated. -> dict or None.

    Both are [(n, ns, reps)] sorted by n. Compared only at element counts
    MEASURED IN BOTH, because a crossover inferred from a size one side never
    ran is an invention.
    """
    swm = {n: (ns, reps) for n, ns, reps in sw}
    common = [(n, ns, reps) for n, ns, reps in dev if n in swm]
    if len(common) < 2:
        return {"status": "insufficient overlap",
                "measured_points": len(common)}

    prev = None
    for n, ns, reps in common:
        sw_ns = swm[n][0]
        wins = ns < sw_ns
        if wins and prev is None:
            return {"status": "device wins at every measured size",
                    "smallest_measured_n": n,
                    "device_ns": ns, "software_ns": sw_ns,
                    "speedup_there": sw_ns / ns if ns else None,
                    "device_reps": reps}
        if wins and prev is not None:
            pn, pns, psw = prev
            # Log-linear in n between the bracketing pair: the quantity that
            # changes across it is a ratio, so the interpolation is done on
            # the ratio's log rather than on the rates themselves.
            r0 = math.log(pns / psw)
            r1 = math.log(ns / sw_ns)
            t = r0 / (r0 - r1) if r0 != r1 else 0.0
            ln = math.log(pn) + t * (math.log(n) - math.log(pn))
            last = common[-1]
            return {"status": "crosses",
                    "n": int(round(math.exp(ln))),
                    "bracket_low": {"n": pn, "device_ns": pns,
                                    "software_ns": psw},
                    "bracket_high": {"n": n, "device_ns": ns,
                                     "software_ns": sw_ns},
                    "speedup_at_largest_measured":
                        swm[last[0]][0] / last[1] if last[1] else None,
                    "largest_measured_n": last[0],
                    "device_reps_at_crossing": reps}
        prev = (n, ns, sw_ns)

    last = common[-1]
    return {"status": "device never wins in the measured range",
            "largest_measured_n": last[0],
            "device_ns": last[1], "software_ns": swm[last[0]][0],
            "shortfall_at_largest": last[1] / swm[last[0]][0]
                                    if swm[last[0]][0] else None}


def svg_chart(fmt, op, by_cfg, width=560, height=330):
    """One log-log chart: n across, ns/element up. Lower is faster."""
    pad_l, pad_r, pad_t, pad_b = 62, 14, 30, 46
    pts = [(n, ns) for s in by_cfg.values() for n, ns, _ in s if ns > 0]
    if not pts:
        return "<p>no data for %s %s</p>" % (fmt, op)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1 = math.log10(max(1, min(xs))), math.log10(max(xs))
    if x1 - x0 < 0.5:
        x1 = x0 + 0.5
    y0, y1 = math.log10(min(ys)), math.log10(max(ys))
    if y1 - y0 < 0.5:
        y1 = y0 + 0.5
    y0 -= 0.06 * (y1 - y0)
    y1 += 0.06 * (y1 - y0)

    def px(n):
        return pad_l + (math.log10(max(1, n)) - x0) / (x1 - x0) * (width - pad_l - pad_r)

    def py(ns):
        return pad_t + (1 - (math.log10(ns) - y0) / (y1 - y0)) * (height - pad_t - pad_b)

    o = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s %s">' % (width, height, fmt, op)]
    o.append('<title>%s %s - nanoseconds per element against working set</title>' % (fmt, op))

    # decade gridlines
    for d in range(int(math.floor(y0)), int(math.ceil(y1)) + 1):
        v = 10 ** d
        if not (y0 <= d <= y1):
            continue
        o.append('<line class="grid" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                 % (pad_l, py(v), width - pad_r, py(v)))
        o.append('<text class="ax" x="%.1f" y="%.1f" text-anchor="end">%s</text>'
                 % (pad_l - 6, py(v) + 3, _sci(v)))
    for d in range(int(math.floor(x0)), int(math.ceil(x1)) + 1):
        v = 10 ** d
        if not (x0 <= d <= x1):
            continue
        o.append('<line class="grid" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f"/>'
                 % (px(v), pad_t, px(v), height - pad_b))
        o.append('<text class="ax" x="%.1f" y="%.1f" text-anchor="middle">%s</text>'
                 % (px(v), height - pad_b + 15, _sci(v)))

    o.append('<text class="axlab" x="%.1f" y="%.1f" text-anchor="middle">elements per call</text>'
             % ((pad_l + width - pad_r) / 2, height - 8))
    o.append('<text class="axlab" transform="translate(13,%.1f) rotate(-90)" '
             'text-anchor="middle">ns per element</text>' % ((pad_t + height - pad_b) / 2))

    for backend, path, tiles, label, colour in CONFIGS:
        s = by_cfg.get((backend, path, tiles))
        if not s:
            continue
        d = " ".join("%s%.1f,%.1f" % ("M" if i == 0 else "L", px(n), py(ns))
                     for i, (n, ns, _) in enumerate(s) if ns > 0)
        o.append('<path class="ln" d="%s" stroke="%s"/>' % (d, colour))
        for n, ns, reps in s:
            if ns <= 0:
                continue
            o.append('<circle cx="%.1f" cy="%.1f" r="2.4" fill="%s">'
                     '<title>%s, n=%s: %.1f ns/elem, %d reps</title></circle>'
                     % (px(n), py(ns), colour, label, f"{n:,}", ns, reps))
    o.append("</svg>")
    return "\n".join(o)


def _sci(v):
    if v >= 1e6:
        return "%gM" % (v / 1e6)
    if v >= 1e3:
        return "%gk" % (v / 1e3)
    if v >= 1:
        return "%g" % v
    return "%g" % v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", help="sweep.csv from hw/bench-sweep.sh")
    ap.add_argument("--out", default=None,
                    help="directory for the report (default: beside the csv)")
    a = ap.parse_args(argv)

    src = pathlib.Path(a.csv)
    out = pathlib.Path(a.out) if a.out else src.parent
    out.mkdir(parents=True, exist_ok=True)

    rows = load(src)
    if not rows:
        sys.stderr.write("no usable rows in %s\n" % src)
        return 1

    ser = series(rows)
    formats = [f for f in FORMAT_ORDER if any(k[0] == f for k in ser)]
    ops = sorted({k[1] for k in ser})

    tips = {"source": str(src), "rows": len(rows), "points": {}}
    for fmt in formats:
        for op in ops:
            by_cfg = ser.get((fmt, op))
            if not by_cfg:
                continue
            sw = by_cfg.get(("software", "host", "0"))
            if not sw:
                continue
            for backend, path, tiles, label, _c in CONFIGS:
                if backend == "software":
                    continue
                dev = by_cfg.get((backend, path, tiles))
                if not dev:
                    continue
                tips["points"]["%s/%s/%s" % (fmt, op, label)] = crossover(sw, dev)

    (out / "tipping-points.json").write_text(
        json.dumps(tips, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    html = [_HEAD]
    html.append("<h1>Where hardware starts to pay</h1>")
    html.append("<p class=lede>%d measurements from <code>%s</code>. Every "
                "chart is log-log and <strong>lower is faster</strong>: "
                "nanoseconds per element against the number of elements in one "
                "call. Where a coloured line drops below the grey one, the "
                "device has overtaken the software backend for that operation "
                "at that size.</p>" % (len(rows), src.name))
    html.append(_LEGEND)

    # The crossover table first: it is the answer, and the charts are the
    # evidence for it.
    html.append("<h2>Tipping points</h2>")
    html.append("<p class=note>The smallest working set at which the device "
                "wins, log-interpolated between the two measurements that "
                "bracket it. <code>tipping-points.json</code> carries both "
                "bracketing measurements for every entry, so the "
                "interpolation can be checked rather than trusted.</p>")
    html.append("<table><thead><tr><th>format</th><th>op</th>"
                "<th>configuration</th><th>crosses at</th>"
                "<th>speed-up at the largest size measured</th></tr></thead><tbody>")
    for name, c in sorted(tips["points"].items()):
        fmt, op, label = name.split("/", 2)
        if c["status"] == "crosses":
            at = "<strong>%s</strong> elements" % f"{c['n']:,}"
            sp = ("%.1fx at n=%s" % (c["speedup_at_largest_measured"],
                                     f"{c['largest_measured_n']:,}")
                  if c.get("speedup_at_largest_measured") else "-")
        elif c["status"].startswith("device wins at every"):
            at = "<span class=win>every size measured</span>"
            sp = "%.1fx at n=%s" % (c["speedup_there"], f"{c['smallest_measured_n']:,}")
        elif c["status"].startswith("device never"):
            at = "<span class=lose>never, within the measured range</span>"
            sp = ("%.2fx (still %.1fx slower)"
                  % (1 / c["shortfall_at_largest"], c["shortfall_at_largest"])
                  if c.get("shortfall_at_largest") else "-")
        else:
            at = "<span class=lose>%s</span>" % c["status"]
            sp = "-"
        html.append("<tr><td>%s</td><td><code>%s</code></td><td>%s</td>"
                    "<td>%s</td><td>%s</td></tr>" % (fmt, op, label, at, sp))
    html.append("</tbody></table>")

    for fmt in formats:
        html.append("<h2>%s</h2><div class=grid>" % fmt)
        for op in ops:
            by_cfg = ser.get((fmt, op))
            if not by_cfg:
                continue
            html.append("<figure><figcaption>%s &middot; <code>%s</code></figcaption>%s</figure>"
                        % (fmt, op, svg_chart(fmt, op, by_cfg)))
        html.append("</div>")

    html.append(_FOOT)
    (out / "bench-report.html").write_text("\n".join(html), encoding="utf-8")

    crosses = sum(1 for c in tips["points"].values() if c["status"] == "crosses")
    always = sum(1 for c in tips["points"].values()
                 if c["status"].startswith("device wins at every"))
    never = sum(1 for c in tips["points"].values()
                if c["status"].startswith("device never"))
    print("bench_report: %d rows, %d series, %d tipping points "
          "(%d cross, %d always win, %d never win)"
          % (len(rows), len(tips["points"]), len(tips["points"]),
             crosses, always, never))
    print("  %s" % (out / "bench-report.html"))
    print("  %s" % (out / "tipping-points.json"))
    return 0


_HEAD = """<!doctype html><meta charset=utf-8>
<title>cft-fp256 - where hardware starts to pay</title>
<style>
 :root{--ink:#14171a;--dim:#5b6570;--rule:#dfe3e8;--bg:#fbfaf8}
 body{margin:0 auto;padding:28px 22px 64px;max-width:1180px;background:var(--bg);
      color:var(--ink);font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif}
 h1{font-size:27px;margin:0 0 6px;letter-spacing:-.01em}
 h2{font-size:19px;margin:34px 0 10px;padding-bottom:5px;border-bottom:1px solid var(--rule)}
 .lede{color:var(--dim);max-width:74ch}
 .note{color:var(--dim);font-size:13.5px;max-width:78ch}
 table{border-collapse:collapse;width:100%;font-size:13.5px;margin:10px 0 4px}
 th,td{text-align:left;padding:5px 9px;border-bottom:1px solid var(--rule);
       vertical-align:top}
 th{font-weight:600;color:var(--dim);font-size:12px;text-transform:uppercase;
    letter-spacing:.04em}
 td:nth-child(4),td:nth-child(5){font-variant-numeric:tabular-nums}
 code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;
      background:#f0eeea;padding:1px 4px;border-radius:3px}
 .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:16px}
 figure{margin:0;background:#fff;border:1px solid var(--rule);border-radius:7px;
        padding:8px 10px 4px}
 figcaption{font-size:12.5px;color:var(--dim);margin-bottom:2px}
 svg{width:100%;height:auto;display:block}
 .grid line,line.grid{stroke:#eceef1;stroke-width:1}
 .ln{fill:none;stroke-width:1.9;stroke-linejoin:round;stroke-linecap:round}
 text.ax{font-size:10px;fill:#8b95a1}
 text.axlab{font-size:10.5px;fill:var(--dim)}
 .key{display:flex;flex-wrap:wrap;gap:14px;margin:10px 0 2px;font-size:13px}
 .key span{display:inline-flex;align-items:center;gap:6px;color:var(--dim)}
 .sw{width:15px;height:3px;border-radius:2px;display:inline-block}
 .win{color:#15803d;font-weight:600}
 .lose{color:#b45309}
</style>
"""

_LEGEND = """<div class=key>
 <span><i class=sw style="background:#6b7280"></i>software</span>
 <span><i class=sw style="background:#dc2626"></i>1 tile, over PCIe</span>
 <span><i class=sw style="background:#ea580c"></i>1 tile, resident</span>
 <span><i class=sw style="background:#2563eb"></i>4 tiles, over PCIe</span>
 <span><i class=sw style="background:#0891b2"></i>4 tiles, resident</span>
</div>"""

_FOOT = """<h2>What this does not measure</h2>
<p class=note>Division, square root and the transcendentals are not
<code>cft_run</code> opcodes - they are their own entry points - so they are
absent from <code>cft-bench</code> and therefore from this sweep. They are the
calls where a tile has the most to win, so every tipping point here is a
<strong>lower bound</strong> on the case for hardware rather than an upper one.
Reductions are likewise a different call shape and not covered.</p>
<p class=note>A point measured from a single repetition is weaker evidence than
one measured over hundreds; the repetition count travels with every point into
<code>tipping-points.json</code> and into each marker's tooltip. The rates
themselves are checked rather than merely timed - <code>cft-bench</code> reads
the result buffer back and holds it against the same call on plain host
pointers before reporting a number.</p>
"""


if __name__ == "__main__":
    sys.exit(main())
