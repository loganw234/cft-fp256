# M3 model: the driver of parcel M3XN2, one mode a run (scratch). compound at
# fp32 as a triple word: the unfixed model (pw32n.build, `--model n`, the
# control) and the follow-up's (pw32c.build, `--model c`, the default, with
# `--variant NAME`), measured. Each run's output is kept as
# pw32c_<mode>[-<detail>].out.txt, its command and time in the parcel's ledger.
# It imports pw32n_run's helpers (regions, n names, the pools' x list) and
# changes none of them.
#
#   python pw32c_run.py [--model n|c] [--variant V] MODE args
#
#   same                              pw32c.build(None) against pw32n.build:
#                                     instruction lists and dag_digest
#   attribute REGION [LANES] [SEED]   item 2: the instructions carrying the
#                                     log-sum and log-lowword capacities
#   cell N REGION [LANES] [SEED]      one cell of the n-scan: a report and one
#                                     `CELL ...` line
#   table FILE...                     the `CELL` lines of FILEs, sorted by n
#   worst FILE... [K]                 the K n whose total is largest (default 6)
#   bound [LANES] [B1exp B2exp] [region,...]   compound's regions (as pw32n_run)
#   costs, live, pools, rate, plants  as pw32n_run, compound only
#
# Run from docs/studies/m3.

import math
import random
import re
import sys
import time
from collections import Counter
from fractions import Fraction

from m3core import (ml, sf, routines, FP32, ATTRS, AN, RNE, RTZ, RDN, RUP,
                    RMM, dec, golden, lg, enc)
import m3pow as M
import regions as RG
import census as CE
import pw32
import pw32n
import pw32n_run as NR
import pw32n_budget as NB
import pw32_run as PR
import pw32c
import pw32c_budget as CB

MARK = ml.MARK
fmt = FP32
N_LIST = NR.N_LIST
SMALL_N = NR.SMALL_N
nstr = NR.nstr
rg_n, rg_region = NR.rg_n, NR.rg_region
max_register = NR.max_register

MODEL = "c"
VARIANT = None


def _b(fn, rnd, n, **kw):
    """the build: pw32c's (with --variant) or, under --model n, pw32n's"""
    if MODEL == "n":
        if VARIANT is not None:
            raise SystemExit("--variant needs --model c (pw32n.build has none)")
        return pw32n.build(fn, rnd, n, **kw)
    return pw32c.build(fn, rnd, n, variant=VARIANT, **kw)


def model_tag():
    return (f"model {'pw32n.build (the unfixed control)' if MODEL == 'n' else 'pw32c.build'}"
            + (f", variant {VARIANT}" if MODEL == "c" else ""))


# ---- the n-scan's list -------------------------------------------------------
# positive n at factors of about 2 to 3 from 4 to 2^24 + 1 (19), and negative n
# at every other one and at -1000 (7): M3XN's box list has none between 17 and
# 2^24 + 1 but 1000
SCAN_POS = (4, 5, 8, 30, 60, 100, 200, 300, 500, 1000, 2000, 3000, 5000,
            10 ** 4, 3 * 10 ** 4, 10 ** 5, 3 * 10 ** 5, 10 ** 6,
            2 ** 22 + 1)
SCAN_NEG = (-5, -30, -300, -1000, -3000, -10 ** 5, -10 ** 6)
SCAN_N = tuple(sorted(SCAN_NEG + SCAN_POS))


def scan_cells():
    """[(n, region)]: int<N> and zone<N> at every n, cint<N> from |N| = 10^4"""
    cells = []
    for n in SCAN_N:
        cells.append((n, f"int{n}"))
        cells.append((n, f"zone{n}"))
        if abs(n) >= 10 ** 4:
            cells.append((n, f"cint{n}"))
    return cells


def mode_cells(args):
    """cells: the scan's (n, region) cells, one `N REGION` a line, for the
    box script"""
    for n, name in scan_cells():
        print(n, name)


# ---- same --------------------------------------------------------------------

def mode_same(args):
    """pw32c.build(variant None) against pw32n.build: body, bank words and
    dag_digest equal, at the 12 n and 0, 1 and the five attributes"""
    t0 = time.time()
    bad = cells = 0
    for n in list(N_LIST) + list(SMALL_N):
        for rnd in ATTRS:
            a = pw32n.build("compound", rnd, n).fragment()
            c = pw32c.build("compound", rnd, n).fragment()
            same = (a.body == c.body and a.words == c.words
                    and ml.dag_digest(a) == ml.dag_digest(c))
            cells += 1
            if not same:
                bad += 1
                print(f"DIFFERENT: compound n={nstr(n)} {AN[rnd]}")
    print(f"pw32c.build (variant None) against pw32n.build, compound: "
          f"{cells} cells (n in {', '.join(nstr(n) for n in list(N_LIST) + list(SMALL_N))}; "
          f"five attributes), instruction lists, bank words and dag_digest "
          f"compared: {bad} different; {time.time() - t0:.0f} s")
    if bad:
        raise SystemExit(1)


# ---- attribute ---------------------------------------------------------------

def mode_attribute(args):
    name = args[0]
    nl = int(args[1]) if len(args) > 1 else 2000
    seed = int(args[2]) if len(args) > 2 else 1
    t0 = time.time()
    n = rg_n("compound", name)
    lanes = rg_region("compound", name, nl, seed)
    b = _b("compound", RNE, n)
    print(f"ATTRIBUTION, {model_tag()}, region {name} n={nstr(n)}, {nl} lanes "
          f"requested, seed {seed}, rne, B1 2^{lg(b.meta['B1']):.0f}, B2 "
          f"2^{lg(b.meta['B2']):.0f}")
    CB.attribute(b, lanes, name)
    print(f"{time.time() - t0:.0f} s")


# ---- the cell and the table -------------------------------------------------

CELL = re.compile(r"^CELL (.*)$")


def mode_cell(args):
    n = int(args[0])
    name = args[1]
    nl = int(args[2]) if len(args) > 2 else 2000
    seed = int(args[3]) if len(args) > 3 else 1
    t0 = time.time()
    if rg_n("compound", name) != n:
        raise SystemExit(f"region {name!r} is at n = {rg_n('compound', name)}"
                         f", not {n}")
    lanes = rg_region("compound", name, nl, seed)
    b = _b("compound", RNE, n)
    print(f"{model_tag()}; seed {seed}; {nl} lanes requested")
    s = NB.report(b, lanes, name, time.time())
    ls, lw = s["by"].get("log-sum", (0.0, 0.0)), s["by"].get("log-lowword",
                                                           (0.0, 0.0))
    head = (f"model={MODEL} variant={VARIANT or '-'} n={n} region={name} "
            f"seed={seed} gen={len(lanes)} measured={s['lanes']} "
            f"left={s['skipped']} tinyt={s['tiny']}")
    if s["lanes"] == 0:
        print(f"CELL {head} NOT_MEASURED")
        return
    tot = s["bound"] + s["resid"]
    print(f"CELL {head} bound={s['bound']:.6f} resid={s['resid']:.2e} "
          f"total={tot:.6f} margin={-math.log2(tot):.2f} "
          f"worst={s['Emax']:.6f} logsum_cap={ls[1]:.6f} "
          f"logsum_obs={ls[0]:.6f} lowword_cap={lw[1]:.6f} "
          f"lowword_obs={lw[0]:.6f} s={time.time() - t0:.0f}")


def parse_cells(files):
    rows = []
    for fn in files:
        for ln in open(fn).read().splitlines():
            m = CELL.match(ln)
            if not m:
                continue
            kv = dict(p.split("=", 1) for p in m.group(1).split() if "=" in p)
            kv["NOT_MEASURED"] = "NOT_MEASURED" in m.group(1).split()
            kv["file"] = fn
            rows.append(kv)
    return rows


def mode_table(args):
    rows = parse_cells(args)
    rows.sort(key=lambda r: (int(r["n"]), r["region"], r["model"]))
    print(f"{len(rows)} CELL lines from {len(args)} files, sorted by n; total "
          f"= bound + residual in Bv, margin in bits, the two logarithm terms' "
          f"capacity / observed in Bv")
    print(f"{'n':>9} {'region':>12} {'model':>8} {'gen':>5} {'meas':>5} "
          f"{'left':>5} {'tinyt':>5} {'bound':>9} {'resid':>8} {'total':>9} "
          f"{'margin':>6} {'worst':>8} {'logsum cap/obs':>16} "
          f"{'lowword cap/obs':>16} larger-cap term")
    for r in rows:
        tag = r["model"] + ("" if r["variant"] == "-" else ":" + r["variant"])
        if r["NOT_MEASURED"]:
            print(f"{r['n']:>9} {r['region']:>12} {tag:>8} {r['gen']:>5} "
                  f"{r['measured']:>5} {r['left']:>5} {r['tinyt']:>5}  "
                  f"NOT MEASURED (no lane: outside the pass count)")
            continue
        lc, wc = float(r["logsum_cap"]), float(r["lowword_cap"])
        print(f"{r['n']:>9} {r['region']:>12} {tag:>8} {r['gen']:>5} "
              f"{r['measured']:>5} {r['left']:>5} {r['tinyt']:>5} "
              f"{r['bound']:>9} {r['resid']:>8} {r['total']:>9} "
              f"{r['margin']:>6} {r['worst']:>8} "
              f"{r['logsum_cap'] + '/' + r['logsum_obs']:>16} "
              f"{r['lowword_cap'] + '/' + r['lowword_obs']:>16} "
              f"{'log-sum' if lc >= wc else 'log-lowword'}")
    # the peak, per model: the cell with the largest total, and each n's own
    for tag in sorted({(r["model"], r["variant"]) for r in rows}):
        sub = [r for r in rows if (r["model"], r["variant"]) == tag
               and not r["NOT_MEASURED"]]
        if not sub:
            continue
        top = max(sub, key=lambda r: float(r["total"]))
        print(f"model {tag[0]} variant {tag[1]}: the largest total over its "
              f"{len(sub)} measured cells is {top['total']} Bv at n="
              f"{top['n']} region {top['region']} (margin {top['margin']} "
              f"bits); there log-sum capacity {top['logsum_cap']} (observed "
              f"{top['logsum_obs']}), log-lowword capacity "
              f"{top['lowword_cap']} (observed {top['lowword_obs']})")


def mode_worst(args):
    k = 6
    files = list(args)
    if files and files[-1].isdigit():
        k = int(files.pop())
    rows = [r for r in parse_cells(files) if not r["NOT_MEASURED"]]
    best = {}
    for r in rows:
        key = int(r["n"])
        if key not in best or float(r["total"]) > float(best[key]["total"]):
            best[key] = r
    order = sorted(best.values(), key=lambda r: -float(r["total"]))[:k]
    for r in order:
        print(f"WORST {r['n']} {r['region']} {r['total']}")
    if not order:
        print("NOT MEASURED: no cell with a measured lane in the files")
        raise SystemExit(1)


# ---- bound (compound's regions) -------------------------------------------------

def mode_bound(args):
    """bound [LANES] [B1exp B2exp] [region,region,...]"""
    nl = int(args[0]) if args else 300
    e1 = int(args[1]) if len(args) > 1 and args[1] != "-" else None
    e2 = int(args[2]) if len(args) > 2 and args[2] != "-" else None
    names = args[3].split(",") if len(args) > 3 else \
        NR._bound_regions("compound")
    t0 = time.time()
    rows = []
    print(f"BOUND, {model_tag()}")
    for name in names:
        n = rg_n("compound", name)
        b = _b("compound", RNE, n,
               B1=None if e1 is None else Fraction(1, 2 ** e1),
               B2=None if e2 is None else Fraction(1, 2 ** e2))
        lanes = rg_region("compound", name, nl, 1)
        s = NB.report(b, lanes, name, time.time())
        rows.append((name, n, s, len(lanes)))
    print(f"\nSUMMARY fp32 compound, {nl} lanes a region, seed 1, rne, B1 "
          f"{'2^' + str(e1) if e1 is not None else '2^-66 (first)'}, B2 "
          f"{'2^' + str(e2) if e2 is not None else '2^-67 (first)'}:")
    worst, nmeas = 0.0, 0
    for name, n, s, got in rows:
        tot = s["bound"] + s["resid"]
        if s["lanes"] == 0:
            print(f"  {name:20s} n={nstr(n):12s} NOT MEASURED (0 measured "
                  f"lanes of {got} generated; outside the pass count)")
            continue
        nmeas += 1
        worst = max(worst, tot)
        ls = s["by"].get("log-sum", (0.0, 0.0))
        lw = s["by"].get("log-lowword", (0.0, 0.0))
        print(f"  {name:20s} n={nstr(n):12s} lanes {s['lanes']:5d} of "
              f"{got:5d} (tinyt-gated {s['tiny']}) bound {s['bound']:.6f} + "
              f"residual {s['resid']:.2e} = {tot:.6f} Bv "
              f"({'under 1' if tot < 1 else 'OVER 1'}); margin "
              f"{-math.log2(tot) if tot > 0 else float('inf'):.2f} bits; "
              f"measured worst {s['Emax']:.6f}; log-sum cap {ls[1]:.6f} (obs "
              f"{ls[0]:.6f}), log-lowword cap {lw[1]:.6f} (obs {lw[0]:.6f})")
    if nmeas == 0:
        print(f"  NOT MEASURED: no region had a measured lane; "
              f"{time.time() - t0:.0f} s")
        return
    print(f"  worst region bound {worst:.6f} Bv, margin "
          f"{-math.log2(worst):.2f} bits, over the {nmeas} of {len(rows)} "
          f"regions measured; {time.time() - t0:.0f} s")


# ---- the modes pw32n_run.py has, run for compound through THIS driver's build --
# pw32n_run's mode functions look their build up in their own module (`_b`,
# `FNS`); this driver sets both in THIS process (never in a file) and calls
# them, so that costs, live, pools and rate are the same code as M3XN's, on
# pw32c.build (or, under --model n, on pw32n.build), restricted to compound.

def mode_plants(args):
    """compound's plants (item 6 of the brief), each shown red in a named mode
    beside the control (plant None) green, on this driver's model"""
    NR._b = _b
    NR.FNS = ("compound",)
    t0 = time.time()
    print(f"PLANTS of compound, {model_tag()}; each shown red in a named mode "
          f"beside the control (plant None) green. A plant's threshold says "
          f"its sensitivity.")
    print()
    V = NR._verdict
    n3 = 2 ** 62 + 2 ** 37 + 1
    bound_cases = (("l3_dropped", 3, "int"), ("l3_dropped", 1000, "int1000"),
                   ("b1_dropped", 1000, "int1000"),
                   ("b1_dropped", 1000, "zone1000"),
                   ("b1_dropped", 16777217, "cint16777217"),
                   ("b1_dropped", 3, "int"), ("b1_dropped", 17, "int17"),
                   ("n_word3_dropped", n3, f"cint{n3}"),
                   ("compound_onep_rounded", 3, "int"),
                   ("n_word_ulp", 3, "int"), ("exact_rule_no_tl", 3, "int"))
    for plant, n, region in bound_cases:
        print(f"plant {plant}: {pw32n.PLANTS[plant]}")
        for p_ in (None, plant):
            tot, ln, em = NR._bound_tot("compound", n, region, 100, p_)
            print(f"  bound mode, fp32 compound n={nstr(n)} region {region}, "
                  f"100 lanes, seed 1, rne, plant {p_}: bound + residual "
                  f"{tot:.6g} Bv over {ln} lanes, measured worst {em:.6g} Bv "
                  f"-> {V(ln and tot >= 1, 'over 1 Bv', 'green (under 1)') if ln else 'NOT MEASURED (no lane)'}",
                  flush=True)
    print("plant mark_silenced: " + pw32n.PLANTS["mark_silenced"] + "; the "
          "rate cell is RED when the plant's marks are under half the "
          "control's (a silencing of under half is NOT seen by it), the "
          "pools cell at any wrong unmarked lane")
    xs = NR._xs("compound")
    base = None
    for plant in (None, "mark_silenced"):
        used, marked, wrong, exp, var = NR._rate_marks("compound", 3, plant)
        if plant is None:
            base = marked
        print(f"  rate mode, fp32 compound n=3 region int, 600 lanes, seed "
              f"3, G' = 6, rne, plant {plant}: {used} main-path lanes, marked "
              f"{marked}, the law predicts {exp:.1f}, WRONG UNMARKED {wrong} "
              f"-> {V(marked < base / 2, 'under half the control marks', 'green (the control)')}",
              flush=True)
    for plant in (None, "mark_silenced"):
        tot = sum(NR._cmp("compound", n, xs, rnd, plant=plant)["wrong"]
                  for n in (3, 2, -3) for rnd in (RNE, RTZ, RDN))
        print(f"  pools mode (model), fp32 compound n in 3, 2, -3 x rne, rtz, "
              f"rdn, {len(xs)} x operands, plant {plant}: WRONG UNMARKED "
              f"{tot} -> {V(tot > 0, 'wrong unmarked lanes', 'green')}",
              flush=True)
    for plant, lst in (("n_word_ulp", (3,)), ("n_low_dropped", (2 ** 24 + 1,)),
                       ("n_word3_dropped", (n3,)), ("n_row_loud", (3,)),
                       ("compound_onep_rounded", (3, 17)),
                       ("exact_rule_no_tl", (3, 1000))):
        print(f"plant {plant}: {pw32n.PLANTS[plant]}")
        for n in lst:
            xs_n = xs
            if n > 2 ** 20:
                xs_n = xs + [ln[0] for ln in rg_region(
                    "compound", f"cint{n}", 200, 1)]
            for p_ in (None, plant):
                try:
                    tot = sum(NR._cmp("compound", n, xs_n, rnd, plant=p_)
                              ["wrong"] for rnd in (RNE, RTZ))
                except ValueError as exc:
                    print(f"  pools mode, compound n={nstr(n)}, plant {p_}: "
                          f"REFUSED by name: {exc}", flush=True)
                    continue
                print(f"  pools mode (model), fp32 compound n={nstr(n)}, "
                      f"{len(xs_n)} x operands, rne + rtz, plant {p_}: WRONG "
                      f"UNMARKED {tot} -> "
                      f"{V(tot > 0, 'wrong unmarked lanes', 'green')}",
                      flush=True)
    print(f"{time.time() - t0:.0f} s")


def _wrap(name):
    def run(args):
        NR._b = _b
        NR.FNS = ("compound",)
        print(f"{name}: {model_tag()}")
        getattr(NR, "mode_" + name)(*([args] if name in ("pools", "rate") else []))
    return run


EXTRA = {"costs": _wrap("costs"), "live": _wrap("live"),
         "pools": _wrap("pools"), "rate": _wrap("rate"),
         "plants": mode_plants}


def main():
    global MODEL, VARIANT
    argv = sys.argv[1:]
    while argv and argv[0].startswith("--"):
        if argv[0] == "--model":
            MODEL = argv[1]
            if MODEL not in ("n", "c"):
                raise SystemExit(f"--model n or c, not {MODEL!r}")
        elif argv[0] == "--variant":
            VARIANT = None if argv[1] in ("none", "-") else argv[1]
        else:
            raise SystemExit(f"unknown option {argv[0]!r}")
        argv = argv[2:]
    if not argv:
        raise SystemExit(__doc__)
    mode, args = argv[0], argv[1:]
    modes = {"same": mode_same, "attribute": mode_attribute,
             "cell": mode_cell, "table": mode_table, "worst": mode_worst,
             "bound": mode_bound, "cells": mode_cells}
    modes.update(EXTRA)
    if mode not in modes:
        raise SystemExit(f"unknown mode {mode!r}: {', '.join(sorted(modes))}")
    modes[mode](args)


if __name__ == "__main__":
    main()
