# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""sweep_cost.py - what a full sweep of each space costs, from the stress run's
measured rates; and what a weekend of the card adds to it.

Inputs, all in this directory:
  stress-final-item-rates.txt  per item and image: slices, count_sum, cases_sum,
                          jobsec_sum, the median per-job rate in `count` and in
                          `cases` a second, the number of jobs at once. DERIVED by
                          stress_records.py from the run's own metrics.jsonl at the
                          run's end (2026-10-19 08:01:13, SHA-256 e7989f88...), in the
                          format of the lead's file. The primary input.
  stress-final-report.txt the report derived from the same record at the end; its tables
                          must equal the derived file's sums exactly
  stress-item-rates.txt   the lead's own per-item rates (written about 07:17, before the
                          run ended) and
  stress-report-0655.txt  the report as of 06:55: both copied unchanged from the lead's
                          scratchpad (parcel SC's brief); the CROSS-CHECK that the lead's
                          derivation and this one agree

Every rate here is in the unit of the driver's `sweep.count`, and that unit is NOT
the same for every operation. It was READ from host/tools/clause5_soak.c and
divsqrt_soak.c and MEASURED on the tools by tool_probe.sh (tool_probe.out):

  one count is ...                      operations
  an operand (or a pair)                class, logb, next, rint, sqrt, div, rem, conv
  an operand, checked against FOUR      cvtto32, cvtto64  (cases = the in-range pairs)
    integer targets
  a lane, converted FOUR times          cvtfrom32, cvtfrom64  (a fresh random i32, u32,
    (i32, u32, i64, u64 sources)        i64 and u64 value each)
  one operand x one exponent: a CHECK   scaleb32, scaleb64  (count -= n * listn)
  an exhaustive slice's `cases`         the 14 exhaustive items, count rate 0 in the
                                        file, so cases/s is used (nextup32/nextdown32
                                        carry 8 extra cases a slice, negligible)

The space of an item is counted in the SAME unit, so time = space / rate holds. A
"worker" is one soak process running at the measured median per-job rate: a TILE for
the items that run on the tile (div, sqrt, rint, scaleb: host/src/clause5.c, divsqrt.c)
and a CPU CORE for the items that do not (clause5.c's HOST operations: conversions, logb,
next, class and rem, where "the device argument is context", cft.h). On the quad the
jobs ran four at once, one a tile; that is the lead's convention, kept here: one quad
= four workers for a tile item.

Every figure printed is COMPUTED from the file's numbers, a stated constant or a count.
The script exits nonzero if any CHECK fails.

usage: python sweep_cost.py                  (reads the files beside it)
       python sweep_cost.py --controls       (seven mutated copies of the rates file; each must go red)
       python sweep_cost.py --rates F --report G   (other copies of the primary inputs)
"""
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RATES = os.path.join(HERE, "stress-final-item-rates.txt")
REPORT = os.path.join(HERE, "stress-final-report.txt")
LEAD_RATES = os.path.join(HERE, "stress-item-rates.txt")
LEAD_REPORT = os.path.join(HERE, "stress-report-0655.txt")

YEAR = 365.25 * 86400.0          # a Julian year, in seconds
S32, S64, S128 = 2 ** 32, 2 ** 64, 2 ** 128
WEEKEND = 0.0                    # the run's seconds on the card, read from the final report in main()

MODES4 = ("rne", "rtz", "rdn", "rup")
MODES5 = MODES4 + ("rmm",)

fails = 0


def check(label, ok, detail=""):
    global fails
    print("CHECK %-76s %s %s" % (label, "ok" if ok else "FAILED", detail))
    if not ok:
        fails += 1


# --------------------------------------------------------------------------
# scaleb's wide exponent range, derived (EX derives the same for fp32: 556)
# --------------------------------------------------------------------------
def scaleb_wide(emax, emin_sub):
    """Exponents n for which scaleb(x, n) can differ from its value at the edge.
    For n >= hi every nonzero finite x overflows (the smallest, 2^emin_sub, reaches
    2^(emin_sub + hi) > max_normal), and the delivered value depends only on sign
    and attribute; for n <= lo every x lands strictly below half the smallest
    subnormal (the largest, below 2^(emax+1), reaches below 2^(emax+1+lo)), and the
    value again depends only on sign and attribute. Zero, infinity and NaN lanes do
    not depend on n at all."""
    hi = emax - emin_sub + 1
    lo = -(emax + 2 - emin_sub)
    return lo, hi, hi - lo + 1


_lo32, _hi32, _n32 = scaleb_wide(127, -149)
_lo64, _hi64, _n64 = scaleb_wide(1023, -1074)

# --------------------------------------------------------------------------
# the families: kind, modes, the rate's unit, and the spaces (in the rate's unit)
# --------------------------------------------------------------------------
# kind: "tile" runs passes on the device; "host" is bit surgery in libcft's host code
# rate: which column of the file is the rate ("count" for random items, "cases" for
#       the exhaustive ones, whose count column is 0)
FAMILIES = {
    # exhaustive items: all 2^32 encodings, rate in encodings a second
    "sqrt32":     dict(kind="tile", modes=MODES5, rate="cases", unit="encodings", spaces=[("2^32 encodings", S32)]),
    "rint32":     dict(kind="tile", modes=MODES5, rate="cases", unit="encodings", spaces=[("2^32 encodings", S32)]),
    "nextup32":   dict(kind="host", modes=(None,), rate="cases", unit="encodings", spaces=[("2^32 encodings", S32)]),
    "nextdown32": dict(kind="host", modes=(None,), rate="cases", unit="encodings", spaces=[("2^32 encodings", S32)]),
    "logb32":     dict(kind="host", modes=(None,), rate="cases", unit="encodings", spaces=[("2^32 encodings", S32)]),
    "class32":    dict(kind="host", modes=(None,), rate="cases", unit="encodings", spaces=[("2^32 encodings", S32)]),
    # random items over 32-bit operand spaces (EX's exhaustive modes)
    "conv32to64": dict(kind="host", modes=(None,), rate="count", unit="operands", spaces=[("fp32 operands, 2^32", S32)]),
    "cvtto32":    dict(kind="host", modes=MODES5, rate="count", unit="operands (x4 targets)",
                       spaces=[("fp32 operands, 2^32", S32)]),
    # random items whose spaces are 2^64 or larger
    "class64":    dict(kind="host", modes=(None,), rate="count", unit="operands", spaces=[("fp64 operands, 2^64", S64)]),
    "logb64":     dict(kind="host", modes=(None,), rate="count", unit="operands", spaces=[("fp64 operands, 2^64", S64)]),
    "nextup64":   dict(kind="host", modes=(None,), rate="count", unit="operands", spaces=[("fp64 operands, 2^64", S64)]),
    "nextdown64": dict(kind="host", modes=(None,), rate="count", unit="operands", spaces=[("fp64 operands, 2^64", S64)]),
    "rint64":     dict(kind="tile", modes=MODES5, rate="count", unit="operands (x2 variants)",
                       spaces=[("fp64 operands, 2^64", S64)]),
    "sqrt64":     dict(kind="tile", modes=MODES4, rate="count", unit="operands", spaces=[("fp64 operands, 2^64", S64)]),
    "conv64to32": dict(kind="host", modes=MODES4, rate="count", unit="operands", spaces=[("fp64 operands, 2^64", S64)]),
    "cvtto64":    dict(kind="host", modes=MODES5, rate="count", unit="operands (x4 targets)",
                       spaces=[("fp64 operands, 2^64", S64)]),
    "cvtfrom32":  dict(kind="host", modes=MODES4, rate="count", unit="lanes (x4 sources)",
                       spaces=[("i32/u32 sources, 2^32", S32), ("i64/u64 sources, 2^64", S64)]),
    "cvtfrom64":  dict(kind="host", modes=MODES4, rate="count", unit="lanes (x4 sources)",
                       spaces=[("i32/u32 sources, 2^32", S32), ("i64/u64 sources, 2^64", S64)]),
    "div32":      dict(kind="tile", modes=MODES4, rate="count", unit="pairs", spaces=[("fp32 pairs, 2^64", S64)]),
    "rem32":      dict(kind="host", modes=(None,), rate="count", unit="pairs", spaces=[("fp32 pairs, 2^64", S64)]),
    "div64":      dict(kind="tile", modes=MODES4, rate="count", unit="pairs", spaces=[("fp64 pairs, 2^128", S128)]),
    "rem64":      dict(kind="host", modes=(None,), rate="count", unit="pairs", spaces=[("fp64 pairs, 2^128", S128)]),
}
# scaleb: the space is operands x exponents, and the rate is in checks (operand x exponent)
FAMILIES["scaleb32"] = dict(kind="tile", modes=MODES4, rate="count", unit="checks (operand x exponent)",
                            spaces=[("fp32 x 17 directed exponents", S32 * 17),
                                    ("fp32 x %d wide exponents" % _n32, S32 * _n32)])
FAMILIES["scaleb64"] = dict(kind="tile", modes=MODES4, rate="count", unit="checks (operand x exponent)",
                            spaces=[("fp64 x 27 directed exponents", S64 * 27),
                                    ("fp64 x %d wide exponents" % _n64, S64 * _n64)])

EXHAUSTIVE = ("sqrt32", "rint32", "nextup32", "nextdown32", "logb32", "class32")


def family_of(item):
    m = re.match(r"^(.*)-(rne|rtz|rdn|rup|rmm)$", item)
    if m and m.group(1) in FAMILIES:
        return m.group(1), m.group(2)
    if item in FAMILIES:
        return item, None
    return None, None


def item_names(fam):
    return [fam if m is None else "%s-%s" % (fam, m) for m in FAMILIES[fam]["modes"]]


# --------------------------------------------------------------------------
# reading the two files
# --------------------------------------------------------------------------
def read_rates(path, what):
    rows = {}
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    head = lines[0].split()
    want = ["item", "image", "slices", "count_sum", "cases_sum", "jobsec_sum",
            "median_count_rate", "median_cases_rate", "jobs_seen"]
    check("the %s has the nine columns this script reads" % what, head == want, "(%d columns)" % len(head))
    for ln in lines[1:]:
        f = ln.split()
        if len(f) != 9:
            check("every data row has nine fields", False, repr(ln))
            continue
        rows[(f[0], f[1])] = dict(
            slices=int(f[2]), count_sum=int(f[3]), cases_sum=int(f[4]), jobsec=int(f[5]),
            count_rate=int(f[6]), cases_rate=int(f[7]), jobs=f[8])
    return rows, len(lines) - 1


def read_report(path, start, stop, pattern):
    out, sect = {}, False
    with open(path, encoding="utf-8") as fh:
        for ln in fh:
            if ln.startswith(start):
                sect = True
                continue
            if sect and ln.startswith(stop):
                break
            m = re.match(pattern, ln)
            if sect and m:
                out[m.group(1)] = tuple(int(x) for x in m.groups()[1:4])
    return out


def span(seconds):
    """A duration the way a reader wants it."""
    if seconds < 120:
        return "%.0f s" % seconds
    if seconds < 7200:
        return "%.1f min" % (seconds / 60.0)
    if seconds < 2 * 86400:
        return "%.1f h" % (seconds / 3600.0)
    if seconds < 400 * 86400:
        return "%.1f d" % (seconds / 86400.0)
    y = seconds / YEAR
    return ("%.4g y" % y) if y < 1e4 else ("%.3g y" % y)


def workers_for(wsec, years):
    return max(1, int(math.ceil(wsec / (years * YEAR))))


def big(x):
    return "{:,}".format(x) if x < 1e7 else "%.2e" % x


def controls():
    """Negative controls: mutated copies of the inputs, each of which must turn a named
    CHECK red. A script that cannot fail proves nothing."""
    import shutil
    import subprocess
    import tempfile
    with open(RATES, encoding="utf-8") as fh:
        rates = fh.read().splitlines()
    tmp = tempfile.mkdtemp(prefix="swp_a_controls_")
    bad = 0

    def run(label, mutated, expect):
        nonlocal bad
        path = os.path.join(tmp, "rates.txt")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(mutated) + "\n")
        p = subprocess.run([sys.executable, "-B", os.path.abspath(__file__), "--rates", path, "--report", REPORT],
                           capture_output=True, text=True)
        failed = [l for l in p.stdout.splitlines() if l.startswith("CHECK") and "FAILED" in l]
        hit = [l for l in failed if expect in l]
        ok = p.returncode == 1 and bool(hit)
        print("CONTROL %-58s %s" % (label, "red at the check written for it" if ok else "NOT CAUGHT  FAILED"))
        for l in (hit or failed)[:2]:
            print("        " + l[:150])
        if not ok:
            bad += 1

    def field_edit(prefix_item, prefix_image, col, fn):
        out = []
        for ln in rates:
            f = ln.split()
            if len(f) == 9 and f[0] == prefix_item and f[1] == prefix_image:
                f[col] = str(fn(int(f[col])))
                ln = " ".join(f)
            out.append(ln)
        return out

    # C1: every rate doubled -> the lead's quoted extremes no longer hold
    doubled = []
    for ln in rates:
        f = ln.split()
        if len(f) == 9 and f[0] != "item":
            f[6], f[7] = str(2 * int(f[6])), str(2 * int(f[7]))
            ln = " ".join(f)
        doubled.append(ln)
    run("C1 all rates doubled", doubled, "class64 over 2^64")
    # C2: a quad row removed
    run("C2 the rem32 quad row removed", [l for l in rates if not l.startswith("rem32 quad ")],
        "every item has a quad row")
    # C3: an item's cases one short of the final report's
    run("C3 class32 quad cases_sum one short", field_edit("class32", "quad", 4, lambda v: v - 1),
        "equal the final report's tables")
    # C4: cvtfrom32's cases no longer 4 x its count
    run("C4 cvtfrom32-rne quad cases_sum +1", field_edit("cvtfrom32-rne", "quad", 4, lambda v: v + 1),
        "cvtfrom32: cases_sum is 4 x")
    # C5: an item the script has no family for
    run("C5 an unknown item added", rates + ["frobnicate64-rne quad 1 1 1 1 1 1 [1]"], "every item belongs to a family")
    # C6: scaleb counted as operands in the data (cases 17 x count): the unit check must see it
    run("C6 scaleb32-rne quad cases_sum 17 x count_sum", field_edit("scaleb32-rne", "quad", 4, lambda v: v * 17),
        "scaleb32: cases_sum is within 0.1%")
    # C7: one random slice's cases one short: the per-family totals (Table 6) no longer add to the record's
    run("C7 div32-rne quad cases_sum one short", field_edit("div32-rne", "quad", 4, lambda v: v - 1),
        "the families' cases add to the record's totals")
    shutil.rmtree(tmp, ignore_errors=True)
    print()
    if bad:
        print("sweep_cost controls: %d control(s) NOT CAUGHT" % bad)
        return 1
    print("sweep_cost controls: all seven mutations were caught at their checks")
    return 0


def sums_by_item(rows):
    out = {}
    for (item, image), r in rows.items():
        sl, ca = out.get(item, (0, 0))
        out[item] = (sl + r["slices"], ca + r["cases_sum"])
    return out


def main():
    global WEEKEND
    weekend = None
    with open(REPORT, encoding="utf-8") as fh:
        for ln in fh:
            m = re.match(r"^on the card\s*:\s*(\d+) s", ln)
            if m:
                weekend = float(m.group(1))
    WEEKEND = weekend or 0.0
    print("sweep_cost.py: full-sweep cost from the stress run's measured rates")
    print("   rates  : stress-final-item-rates.txt (derived by stress_records.py from the final metrics.jsonl)")
    print("   report : stress-final-report.txt      cross-checks: the lead's stress-item-rates.txt, stress-report-0655.txt")
    print("   year   : %.0f s (Julian); month = year / 12; one weekend of the card = %d s (the final report's 'on the card')"
          % (YEAR, WEEKEND))
    print()
    check("the final report states the run's seconds on the card", weekend is not None, "(%d s)" % WEEKEND)
    rows, nrows = read_rates(RATES, "final derived file")
    rep_rand = read_report(REPORT, "random items", "slices:", r"^  (\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")
    rep_exh = read_report(REPORT, "exhaustive items", "  total:", r"^  (\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+[\d.]+%")

    # ---- integrity of the inputs ----------------------------------------
    check("the rates file has 182 data rows (183 lines with its header)", nrows == 182, "(%d)" % nrows)
    items = sorted({i for i, _ in rows})
    check("68 distinct items in the rates file (14 exhaustive + 54 random)", len(items) == 68, "(%d)" % len(items))
    unmapped = [i for i in items if family_of(i)[0] is None]
    check("every item belongs to a family with a stated unit and space", not unmapped, str(unmapped))
    check("the final report lists 54 random and 14 exhaustive items", len(rep_rand) == 54 and len(rep_exh) == 14,
          "(%d random, %d exhaustive)" % (len(rep_rand), len(rep_exh)))
    noquad = [i for i in items if (i, "quad") not in rows]
    check("every item has a quad row (the lead's per-tile convention)", not noquad, str(noquad))
    # primary file against the final report: the same record at the same instant, so EXACT
    mine = sums_by_item(rows)
    bad = [(i, mine.get(i), (sl, ca)) for i, (sl, ca, _x) in list(rep_rand.items()) + list(rep_exh.items())
           if mine.get(i) != (sl, ca)]
    check("all 68 items' slices and cases equal the final report's tables exactly, summed over images", not bad, str(bad[:2]))
    # the lead's earlier files: snapshots of the same run taken before it ended; never AHEAD of the final
    lead_rows, _n = read_rates(LEAD_RATES, "lead's earlier rates file")
    lead_sums = sums_by_item(lead_rows)
    ahead = [i for i in lead_sums if lead_sums[i][0] > mine[i][0] or lead_sums[i][1] > mine[i][1]]
    check("the lead's earlier rates file is never ahead of the final record on any item", not ahead, str(ahead[:3]))
    old_rand = read_report(LEAD_REPORT, "random items", "slices:", r"^  (\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$")
    old_exh = read_report(LEAD_REPORT, "exhaustive items", "  total:", r"^  (\S+)\s+(\d+)\s+(\d+)\s+(\d+)\s+[\d.]+%")
    ahead = [i for i, (sl, ca, _x) in list(old_rand.items()) + list(old_exh.items()) if sl > mine[i][0] or ca > mine[i][1]]
    check("the 06:55 report is never ahead of the final record on any item", not ahead, str(ahead[:3]))
    worst = (0.0, None)
    n_cmp = 0
    for key, lr in lead_rows.items():
        r = rows.get(key)
        if r is None or lr["slices"] < 5:
            continue
        for col in ("count_rate", "cases_rate"):
            if lr[col] > 0:
                dev = abs(r[col] - lr[col]) / lr[col]
                n_cmp += 1
                if dev > worst[0]:
                    worst = (dev, (key, col, lr[col], r[col]))
    check("the lead's medians (07:17, rows with >= 5 slices) agree with the final derivation within 3%", worst[0] <= 0.03,
          "(%d medians compared; the widest %.2f%% at %s)" % (n_cmp, 100.0 * worst[0], worst[1][0] if worst[1] else "-"))
    check("the exhaustive items' count column is 0 everywhere (so cases/s is their rate)",
          all(r["count_sum"] == 0 and r["count_rate"] == 0 for (i, im), r in rows.items() if family_of(i)[0] in EXHAUSTIVE))
    check("the random items' count rates are all positive",
          all(r["count_rate"] > 0 for (i, im), r in rows.items() if family_of(i)[0] not in EXHAUSTIVE))
    sc = rows[("scaleb32-rne", "quad")]
    check("scaleb32: cases_sum is within 0.1% of count_sum (count IS checks, not operands)",
          abs(sc["cases_sum"] - sc["count_sum"]) < 0.001 * sc["count_sum"], "(%d vs %d)" % (sc["cases_sum"], sc["count_sum"]))
    cf = rows[("cvtfrom32-rne", "quad")]
    check("cvtfrom32: cases_sum is 4 x count_sum (4 source types a lane)", cf["cases_sum"] == 4 * cf["count_sum"],
          "(%d vs %d)" % (cf["cases_sum"], cf["count_sum"]))
    ct = rows[("cvtto32-rne", "quad")]
    check("cvtto32: cases_sum is between 1 x and 4 x count_sum (in-range pairs only)",
          ct["count_sum"] < ct["cases_sum"] < 4 * ct["count_sum"], "(ratio %.2f)" % (ct["cases_sum"] / ct["count_sum"]))
    check("scaleb32 wide range derived as [-278, +277] = 556 exponents (EX's BELIEVED figure)",
          (_lo32, _hi32, _n32) == (-278, 277, 556), "(%d, %d, %d)" % (_lo32, _hi32, _n32))
    print("   scaleb64 wide range derived as [%d, %+d] = %d exponents (same argument: emax 1023, smallest subnormal 2^-1074)"
          % (_lo64, _hi64, _n64))
    print()

    def rate(item, image="quad"):
        r = rows[(item, image)]
        return float(r["cases_rate"] if FAMILIES[family_of(item)[0]]["rate"] == "cases" else r["count_rate"])

    # ---- the lead's quoted extremes, reproduced ----------------------------
    quad_y = lambda space, item: space / (4.0 * rate(item)) / YEAR
    c64, r32 = quad_y(S64, "class64"), quad_y(S64, "rem32")
    check("class64 over 2^64 on one quad is about 6,600 years (the lead's COMPUTED)", 6400 < c64 < 6800, "(%.0f y)" % c64)
    check("rem32 over 2^64 pairs on one quad is about 320,000 years (the lead's COMPUTED)", 310000 < r32 < 330000,
          "(%.0f y)" % r32)
    d64, r64 = quad_y(S128, "div64-rne"), quad_y(S128, "rem64")
    check("div64 and rem64 over 2^128 pairs: 10^24 .. 10^26 years on one quad (the lead's COMPUTED)",
          1e24 <= d64 <= 1e26 and 1e24 <= r64 <= 1e26, "(%.2e, %.2e y)" % (d64, r64))
    ntile = sum(1 for i in items if FAMILIES[family_of(i)[0]]["kind"] == "tile")
    nhost = sum(1 for i in items if FAMILIES[family_of(i)[0]]["kind"] == "host")
    check("35 items run on the tile and 33 are host code", (ntile, nhost) == (35, 33), "(%d, %d)" % (ntile, nhost))
    print()

    # ---- table 1 -------------------------------------------------------------
    print("== TABLE 1. families, where each runs, what its rate counts, and the quad's per-job median rates")
    print("   'tile' = passes on the device; 'host' = libcft host code, so its rate here is one CPU core of the box")
    print("   %-11s %-5s %-26s %5s %10s %10s   %s" % ("family", "runs", "one count is", "items", "min M/s", "max M/s", "spaces"))
    for fam, spec in FAMILIES.items():
        rs = [rate(n) for n in item_names(fam)]
        print("   %-11s %-5s %-26s %5d %10.3f %10.3f   %s" % (
            fam, spec["kind"], spec["unit"], len(rs), min(rs) / 1e6, max(rs) / 1e6, "; ".join(s[0] for s in spec["spaces"])))
    print()

    # ---- table 2 -------------------------------------------------------------
    print("== TABLE 2. a full sweep of each space at the measured rates (COMPUTED)")
    print("   worker-seconds = sum over the family's attributes of space / per-job median rate")
    print("   one quad = 4 workers; 'workers' are tiles for tile items and CPU cores for host items")
    print("   %-11s %-5s %-30s %2s %12s %14s %14s %14s %14s" % (
        "family", "runs", "space", "n", "one quad", "workers 10 y", "workers 1 y", "workers 1 mo", "worker-y"))
    for fam, spec in FAMILIES.items():
        names = item_names(fam)
        for label, space in spec["spaces"]:
            wsec = sum(space / rate(n) for n in names)
            print("   %-11s %-5s %-30s %2d %12s %14s %14s %14s %14s" % (
                fam, spec["kind"], label, len(names), span(wsec / 4.0),
                big(workers_for(wsec, 10.0)), big(workers_for(wsec, 1.0)), big(workers_for(wsec, 1.0 / 12.0)),
                ("%.3g" % (wsec / YEAR))))
    print()

    # ---- table 3 -------------------------------------------------------------
    print("== TABLE 3. what the 2026-10-16..19 run covered of each large space, and the defect share it could see")
    print("   count = the run's total in the item's own unit (all images), from the rates file; fraction = count / space.")
    print("   floor95 = 3 / count: the smallest share of the SAMPLED distribution a defect can occupy and still be hit")
    print("   with probability 0.95 by that many independent draws (1 - exp(-3) = 0.95). 'W weekends' means W runs of")
    print("   this size with INDEPENDENT samples; with today's seeds a rerun repeats the first (see seed_audit.py).")
    print("   For the two 2^32 spaces the run drew MORE than the space; the share of distinct points a uniform")
    print("   sampler would have hit is 1 - exp(-fraction) (the banded sampler is not uniform, so this is an upper bound).")
    print("   %-16s %-5s %20s %11s %11s %11s %11s %11s" % ("item (rne or only)", "runs", "count, one run", "fraction", "distinct if uniform", "floor95 1w", "floor95 13w", "floor95 52w"))
    for fam, spec in FAMILIES.items():
        if fam in EXHAUSTIVE:
            continue
        item = item_names(fam)[0]
        total = sum(r["count_sum"] for (i, im), r in rows.items() if i == item)
        space = max(s[1] for s in spec["spaces"])
        frac = total / space
        print("   %-16s %-5s %20s %11.2e %11s %11.2e %11.2e %11.2e" % (
            item, spec["kind"], "{:,}".format(total), frac,
            ("%.1f%%" % (100.0 * (1.0 - math.exp(-frac)))) if frac > 1e-3 else "-",
            3.0 / total, 3.0 / (13 * total), 3.0 / (52 * total)))
    print()

    # ---- table 4 -------------------------------------------------------------
    print("== TABLE 4. the whole weekend (%d s, four workers) on ONE item: the most one weekend could add" % WEEKEND)
    print("   %-16s %-5s %22s %12s %16s" % ("item", "runs", "cases in a weekend", "fraction", "weekends to 1.0"))
    for item in ("class64", "rem32", "div32-rne", "sqrt64-rne", "rint64-rne", "conv64to32-rne", "cvtto64-rne", "div64-rne", "rem64"):
        spec = FAMILIES[family_of(item)[0]]
        space = max(s[1] for s in spec["spaces"])
        n = 4.0 * rate(item) * WEEKEND
        print("   %-16s %-5s %22s %12.2e %16.3g" % (item, spec["kind"], "{:,}".format(int(n)), n / space, space / n))
    print()

    # ---- the share of the run's sweep job-seconds that went to host items ------
    tile_s = sum(r["jobsec"] for (i, im), r in rows.items() if FAMILIES[family_of(i)[0]]["kind"] == "tile")
    host_s = sum(r["jobsec"] for (i, im), r in rows.items() if FAMILIES[family_of(i)[0]]["kind"] == "host")
    tile_c = sum(r["cases_sum"] for (i, im), r in rows.items() if FAMILIES[family_of(i)[0]]["kind"] == "tile")
    host_c = sum(r["cases_sum"] for (i, im), r in rows.items() if FAMILIES[family_of(i)[0]]["kind"] == "host")
    print("== TABLE 5. where the run's sweep job-seconds went (jobsec_sum, all images)")
    print("   tile items: %s job-s (%.1f%%), %s cases;  host items: %s job-s (%.1f%%), %s cases" % (
        "{:,}".format(tile_s), 100.0 * tile_s / (tile_s + host_s), "{:,}".format(tile_c),
        "{:,}".format(host_s), 100.0 * host_s / (tile_s + host_s), "{:,}".format(host_c)))
    for image in ("quad", "single", "deep"):
        t = sum(r["jobsec"] for (i, im), r in rows.items() if im == image and FAMILIES[family_of(i)[0]]["kind"] == "tile")
        h = sum(r["jobsec"] for (i, im), r in rows.items() if im == image and FAMILIES[family_of(i)[0]]["kind"] == "host")
        print("   %-7s tile %8d job-s, host %8d job-s (host share %.1f%%)" % (image, t, h, 100.0 * h / (t + h)))
    print()

    # ---- what the run did, per family, summed over its attributes and images ---------
    print("== TABLE 6. what the run did, per family, summed over the family's attributes and the three images (as run)")
    print("   'cases' is the verdict's own case count; 'count' is the soak's argument, in the unit of 2.2 (0 for the exhaustive items)")
    print("   %-11s %-5s %5s %20s %20s" % ("family", "runs", "items", "cases", "count"))
    grand_r = grand_e = 0
    for fam, spec in FAMILIES.items():
        names = item_names(fam)
        cs = sum(r["cases_sum"] for (i, im), r in rows.items() if i in names)
        ns = sum(r["count_sum"] for (i, im), r in rows.items() if i in names)
        if fam in EXHAUSTIVE:
            grand_e += cs
        else:
            grand_r += cs
        print("   %-11s %-5s %5d %20s %20s" % (fam, spec["kind"], len(names), "{:,}".format(cs), "{:,}".format(ns)))
    print("   random %s cases, exhaustive %s cases" % ("{:,}".format(grand_r), "{:,}".format(grand_e)))
    check("the families' cases add to the record's totals (1,296,186,685,863 random, 60,129,542,440 exhaustive)",
          (grand_r, grand_e) == (1296186685863, 60129542440), "(%d, %d)" % (grand_r, grand_e))
    print()

    # ---- which bit patterns uniform draws cover: the coupon-collector union bound -------------------
    print("== TABLE 7. the union bound: draws needed so that EVERY pattern of t bits on EVERY set of t of an operand's 64 positions")
    print("   is seen, with probability at least 1 - e^-3 = 0.95, by uniform draws: N >= 2^t (t ln 2 + ln C(64, t) + 3)")
    n_item = sum(r["count_sum"] for (i, im), r in rows.items() if i == "div32-rne")
    print("   one weekend item (div32-rne, as run): %s draws" % "{:,}".format(n_item))
    need = {}
    for t in (20, 24, 26, 27, 28, 29):
        ln_c = math.lgamma(65) - math.lgamma(t + 1) - math.lgamma(65 - t)
        need[t] = (2 ** t) * (t * math.log(2.0) + ln_c + 3.0)
        print("   t = %2d  needs %.3e draws  (%s by a weekend item)" % (t, need[t], "covered" if need[t] <= n_item else "not covered"))
    check("a weekend item covers every 27-bit pattern and not every 28-bit pattern (the quoted 'up to about 27')",
          need[27] <= n_item < need[28], "(%.2e <= %.2e < %.2e)" % (need[27], n_item, need[28]))
    print()

    print("sweep_cost: %s" % ("every CHECK held" if fails == 0 else "%d CHECK(s) FAILED" % fails))
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    try:                                  # the same bytes on Windows and Linux
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    args = sys.argv[1:]
    while args:
        a = args.pop(0)
        if a == "--rates":
            RATES = args.pop(0)
        elif a == "--report":
            REPORT = args.pop(0)
        elif a == "--controls":
            sys.exit(controls())
        else:
            print(__doc__)
            sys.exit(2)
    sys.exit(main())
