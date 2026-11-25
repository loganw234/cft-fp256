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


# the gap scan (the lead's finding on the unfixed model's scan: log-lowword's
# capacity is 0.5275 at n = 1000 and exactly 0 from n = 2000, and -1000 against
# -3000): the block "log-lowword" is selected to zero where |x| < SMALL =
# 15/256 (pw32c.py's `sm`). The main path is the SCREENS': the build's rounded
# product th0 is tested against TOVF (emax + 2 = 129) and TUNF (emin - p - 2 =
# -152), so it is -152 < t < 129 (pw32n.py :373 to :375; send-back 1's
# correction: the first version of this comment used 149, regions.py's `_tf`,
# which is the int sampler's cap and not the main path). The four edges of the
# block (|x| >= SMALL, t = n log2(1 + x)) are COMPUTED in mode_gapedge below
# from the build's own words TOVF, TUNF and SMALL.
GAP_POS = (1100, 1200, 1300, 1500, 1700, 1800, 1900)
GAP_NEG = (-1100, -1200, -1300, -1500, -1700, -1800, -1900, -2000, -2500)
GAP_N = tuple(sorted(GAP_NEG + GAP_POS))


def gap_cells():
    return [(n, f"{k}{n}") for n in GAP_N for k in ("int", "zone")]


def mode_gapedge(args):
    """gapedge: the four edges of the log-lowword block's lanes in n,
    COMPUTED from the build's own words TOVF, TUNF and SMALL (read from the
    built fragment's bank), for |x| >= SMALL and -152 < t < 129"""
    import pw32n
    G, GL, plog, pexp = pw32n.plan()
    cl, _ce = pw32n._consts("compound", G, GL, plog, pexp)
    small = float(dec(fmt, cl["SMALL"]))
    b = pw32c.build("compound", RNE, 1000)
    tovf = float(dec(fmt, b.words["TOVF"]))
    tunf = float(dec(fmt, b.words["TUNF"]))
    lp = math.log2(1 + small)
    ln = abs(math.log2(1 - small))
    print(f"SMALL = {small} (= 15/256: {small == 15 / 256}); the screens' "
          f"words of the build: TOVF = {tovf:g}, TUNF = {tunf:g}, so the "
          f"main path is {tunf:g} < t < {tovf:g} (t = n log2(1 + x)); "
          f"log2(1 + SMALL) = {lp:.6f}, |log2(1 - SMALL)| = {ln:.6f}")
    print(f"the block (|x| >= SMALL) has lanes, COMPUTED as the screen / "
          f"the log:")
    print(f"  x > 0, n > 0: n < {tovf / lp:.1f}   (t up to {tovf:g})")
    print(f"  x < 0, n > 0: n < {-tunf / ln:.1f}   (t down to {tunf:g})")
    print(f"  x > 0, n < 0: |n| < {-tunf / lp:.1f}   (t down to {tunf:g})")
    print(f"  x < 0, n < 0: |n| < {tovf / ln:.1f}   (t up to {tovf:g})")
    # the coverage, COUNTED: for every cell of the scan and of the gap scan
    # (2,000 lanes, seed 1, the lists' own regions), the lanes whose
    # t = n log2(1 + x) is in the band (TUNF, -_tf) = (-152, -149), by cell
    # type, and of those the block's (|x| >= SMALL) by the signs of x and n
    import mpmath
    band_hi = -RG._tf(fmt)
    print(f"coverage: lanes of each cell (the scan's {len(scan_cells())} and "
          f"the gap scan's {len(gap_cells())} cells, 2,000 lanes, seed 1) "
          f"with t in ({tunf:g}, {band_hi}); regions.py's int sampler keeps "
          f"|t| < {RG._tf(fmt)} (its `_tf`, t_reach - 3)", flush=True)
    tot = Counter()
    gen = Counter()
    sign = Counter()
    for n, name in scan_cells() + gap_cells():
        typ = re.match(r"[a-z]+", name).group(0)
        lanes = rg_region("compound", name, 2000, 1)
        gen[typ] += len(lanes)
        k = kb = 0
        for x, nn in lanes:
            xv = dec(fmt, x)
            with mpmath.workprec(80):
                t = nn * mpmath.log(1 + mpmath.mpf(xv.numerator)
                                    / xv.denominator, 2)
            if tunf < t < band_hi:
                k += 1
                tot[typ] += 1
                if abs(float(xv)) >= small:
                    kb += 1
                    sign[(typ, "x>0" if xv > 0 else "x<0",
                          "n>0" if nn > 0 else "n<0")] += 1
        if k:
            print(f"  {name:12s} n={n:>6d}: {k} lanes with t in the band, "
                  f"{kb} of them block lanes (|x| >= SMALL)", flush=True)
    for typ in ("int", "zone", "cint"):
        print(f"{typ}<N> cells: {gen[typ]} lanes generated, {tot[typ]} with "
              f"t in ({tunf:g}, {band_hi}), of them block lanes by sign: "
              + (", ".join(f"{sx} {sn} {c}" for (t2, sx, sn), c in
                           sorted(sign.items()) if t2 == typ) or "none"))
    # t < 0 needs x < 0 with n > 0 or x > 0 with n < 0: only those two sign
    # cases can have block lanes in the band
    cover = {(sx, sn) for (_t, sx, sn) in sign}
    cases = [("x<0", "n>0"), ("x>0", "n<0")]
    miss = [c for c in cases if c not in cover]
    print("COVERAGE (this tool's count): of the two sign cases whose t is "
          "negative, block lanes with t in the band are sampled in "
          + (", ".join(f"{sx} {sn}" for sx, sn in sorted(cover)) or "neither")
          + " (in zone cells only: no int<N> or cint<N> cell has one); "
          "sampled in NO cell: "
          + (", ".join(f"{sx} {sn}" for sx, sn in miss) or "none")
          + " (a case with no lane here is not measured)")


def mode_cells(args):
    """cells [gap]: the scan's (n, region) cells, one `N REGION` a line, for
    the box script (`gap`: the gap list's)"""
    for n, name in (gap_cells() if args and args[0] == "gap"
                    else scan_cells()):
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


def mode_ladder(args):
    """ladder LANES REGIONS VARIANTS: each variant (`;`-joined list, `none`
    the control through pw32c.build) at each region (`,`-joined), seed 1,
    rne: instructions, live cap and highest register over the 12 n and five
    attributes, and per region the bound with the two logarithm terms"""
    nl = int(args[0])
    regs = args[1].split(",")
    t0 = time.time()
    lanes = {r: rg_region("compound", r, nl, 1) for r in regs}
    for v in args[2].split(";"):
        v = None if v == "none" else v
        ins, live, top = [], 0, 0
        for n in N_LIST:
            for rnd in ATTRS:
                f = pw32c.build("compound", rnd, n, variant=v).fragment()
                ins.append(len(f.body))
                live = max(live, f.live_max())
                top = max(top, max_register(f) or 0)
                routines.program(f)       # an AssertionError would stop here
        print(f"VARIANT {v}: instructions {min(ins)} to {max(ins)} (12 n, "
              f"five attributes), cap {live}, highest register r{top}, "
              f"routines.program accepts every fragment; values beside a "
              f"call 30 - cap = {30 - live}", flush=True)
        for r in regs:
            n = rg_n("compound", r)
            b = pw32c.build("compound", RNE, n, variant=v)
            s = NB.NBudget(b).add(lanes[r]).summary()
            if s["lanes"] == 0:
                print(f"  {r}: NOT MEASURED (0 measured lanes)")
                continue
            tot = s["bound"] + s["resid"]
            ls = s["by"].get("log-sum", (0.0, 0.0))
            lw = s["by"].get("log-lowword", (0.0, 0.0))
            print(f"  {r}: {s['lanes']} measured of {len(lanes[r])}: bound "
                  f"{s['bound']:.6f} + residual {s['resid']:.2e} = {tot:.6f} "
                  f"Bv, margin {-math.log2(tot):.2f} bits, measured worst "
                  f"{s['Emax']:.6f}; log-sum capacity {ls[1]:.6f} (observed "
                  f"{ls[0]:.6f}), log-lowword capacity {lw[1]:.6f} (observed "
                  f"{lw[0]:.6f})", flush=True)
    print(f"{time.time() - t0:.0f} s")


def mode_capexp(args):
    """capexp: the experiments of the ladder's text, as an output: `early`
    (the block built before the table's lookups) against the same variant
    without it, and every phase label for the block, fixB: instructions,
    cap and highest register over the 12 n and five attributes"""
    def stats(v):
        """(min, max instructions, live cap, highest register or None,
        the set of routines.program's refusals); the register is read only
        where routines.program accepts the fragment"""
        ins, live, top, refused = [], 0, 0, Counter()
        for n in N_LIST:
            for rnd in ATTRS:
                f = pw32c.build("compound", rnd, n, variant=v).fragment()
                ins.append(len(f.body))
                live = max(live, f.live_max())
                try:
                    routines.program(f)
                except AssertionError as exc:
                    refused[str(exc)] += 1
                    continue
                top = max(top, max_register(f))
        return min(ins), max(ins), live, top, refused

    def show(lo, hi, live, top, refused):
        if refused:
            why = "; ".join(f"{k!r} in {c} of {len(N_LIST) * len(ATTRS)} "
                            f"cells" for k, c in refused.items())
            return (f"REFUSED by routines.program: {why}; instructions "
                    f"{lo} to {hi}, live {live} (no register is allocated: "
                    f"no highest register)")
        return (f"instructions {lo} to {hi}, cap {live}, highest register "
                f"r{top}")
    for v in ("fixB", "early+" + pw32c.ALIASES["fixB"]):
        print(f"variant {v}: {show(*stats(v))} (12 n, five attributes)",
              flush=True)
    for ph in ("lowword", "reduce", "table", "Z", "recon", "setup", "head2",
               "final"):
        pw32c.LW_PHASE = ph
        try:
            print(f"variant fixB, the block's phase label {ph!r}: "
                  f"{show(*stats('fixB'))}", flush=True)
        except Exception as exc:
            print(f"variant fixB, phase label {ph!r}: REFUSED "
                  f"{type(exc).__name__}: {str(exc)[:100]}")
    pw32c.LW_PHASE = "lowword"


EXTRA = {"ladder": mode_ladder, "capexp": mode_capexp, "costs": _wrap("costs"), "live": _wrap("live"),
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
             "bound": mode_bound, "cells": mode_cells, "gapedge": mode_gapedge}
    modes.update(EXTRA)
    if mode not in modes:
        raise SystemExit(f"unknown mode {mode!r}: {', '.join(sorted(modes))}")
    modes[mode](args)


if __name__ == "__main__":
    main()
