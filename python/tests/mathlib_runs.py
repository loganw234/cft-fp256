# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The larger runs of parcels E1, MB1 and MB2: the checks of test_mathlib.py at
sizes the golden stage does not run, as a script, for exp, exp2, expm1, log,
log2 and log1p.

    python python/tests/mathlib_runs.py pools   [--fn exp2] [--formats fp64]
        [--seq] [--edges]
    python python/tests/mathlib_runs.py lanes   --fn expm1 --format fp64
        --n 5000 --seed 3
    python python/tests/mathlib_runs.py bound   --fn exp2 --format fp64
        --random 2000 --weighted 2000
    python python/tests/mathlib_runs.py budget  --fn expm1 --format fp64
        --unit 300 --weighted 300
    python python/tests/mathlib_runs.py rate    --fn exp2 --format fp64
        --n 20000 --attrs rne,rtz [--statistics 18] [--alpha 0.001]
    python python/tests/mathlib_runs.py rategeom --fn log --format fp64
        --n 20000 --seeds 101-160
    python python/tests/mathlib_runs.py family  [--fn expm1] [--format fp64]
        [--centres 0]
    python python/tests/mathlib_runs.py sweep   --fn expm1 --format fp32
        --lo -0.3 --hi 0.3 --stride 1 --shard 0/36
    python python/tests/mathlib_runs.py family  --write | --check
    python python/tests/mathlib_runs.py live
    python python/tests/mathlib_runs.py reduction [--formats fp64,fp128,fp256]
        [--n 100000] [--seed 1] [--edge-width 8] [--halves-step 1] [--quick]
    python python/tests/mathlib_runs.py reduction-tw [--n 1000] [--seed 7]
        [--no-halves] [--quick]
    python python/tests/mathlib_runs.py trig-pools [--fn sin,cos,tan]
        [--formats fp64,fp128,fp256] [--attrs rne,rtz,rdn,rup,rmm] [--seq]
        [--step N] [--quick] [--out PATH]
    python python/tests/mathlib_runs.py trig-bound [--fn sin,cos,tan]
        [--formats fp64,fp128,fp256] [--attrs rne] [--n N] [--seed 121]
        [--guard G] [--quick] [--out PATH]
    python python/tests/mathlib_runs.py trig-budget [--fn sin,cos,tan]
        [--formats fp64,fp128,fp256] [--regions edge,near,zero,small,random]
        [--n N] [--seed 121] [--attrs-step K | --no-attrs] [--guard G]
        [--quick] [--out PATH]
    python python/tests/mathlib_runs.py trig-rate [--fn sin,cos,tan]
        [--formats fp64,fp128,fp256] [--attrs rne,rtz] [--n N] [--seed 7]
        [--statistics K] [--alpha A] [--sigmas S] [--quick] [--out PATH]
    python python/tests/mathlib_runs.py trig-family [--fn sin,cos,tan]
        [--formats fp64,fp128,fp256] [--attrs rne,rtz,rdn,rup,rmm]
        [--centres N] [--jmax J] [--quick] [--out PATH] | --write | --check
    python python/tests/mathlib_runs.py all     [--scale 1]

--fn is a list of exp, exp2, expm1, log, log2 and log1p (all six by default).
Each command
prints what it ran and what it measured, then a line "RESULT: ok" or
"RESULT: N findings" and exits 0 or 1. Pure Python, one process, one core:
the lanes are softfloat.compute one instruction at a time (about 1 ms a lane
at fp64 and 2 ms at fp256), the references mpmath and transcend.py. Every
sample is a function of --seed, so a run can be repeated.

  pools    the transcend pools through each fragment, with --edges the
           routine's edge pool as well, and with --seq through seq.py as a
           stand-alone program (every format, fp32 included: the scheduled
           fragments fit its 32 registers)
  lanes    random arguments with every bit random, and the weighted
           sampler's, through each fragment against transcend
  bound    |V - mpmath| / Bv over random arguments with every bit random,
           over the places each path's reduced argument is largest (expm1's
           first clamped k among them), over the weighted sampler and over x
           uniform on [-1, 1] (expm1's cancelling cells n = +-1 are there):
           the largest ratio found, a lower bound on the true worst
  budget   verifier-VM1b's first-order budget over the same regions: the
           bound it states, which the true worst cannot pass
           (mathlib_budget); fp64, fp128 and fp256 only
  rate     the mark-rate law with the bound inflated to G' = 6: each cell's
           count of marks against the SAMPLE'S OWN expectation (the sum of
           2^-G' m_V over its lanes, m_V the significand of the lane's true
           value), judged by its exact two-sided tail, and the cells of the
           run judged together: a cell is flagged when its tail is under
           alpha / K, K the independent statistics of the run (two a routine
           and format: rtz, rdn and rup mark the same lanes, rne and rmm the
           same), so that a run with nothing wrong is flagged with probability
           at most alpha (--alpha, 0.1%). --statistics K names the run's K
           when the run is several processes (the default is this process's
           own); --sigmas N is the plain N-sigma line, no multiplicity. A
           last line gives the run's smallest tail
  rategeom the same law without the fragment: for each seed of --seeds
           (a-b, inclusive) and each routine and format, the counts of marks
           the true-value geometry gives each class (directed, nearest), their
           z and exact tails, and how many of the seeds' runs the rule would
           have flagged against how many the law says it flags: the rule's
           false-alarm rate, measured; and per statistic the mean and
           variance of z over the seeds, which the law says are 0 and 1
  sweep    the bound over EVERY float of a range (--lo, --hi, decimal
           numbers, exact), every --stride-th of them, shard i of n of
           those (--shard i/n, so n processes cover the range): the largest
           ratio found and where, for the lead's box. A range of 2^23 floats
           (one binade) costs about 2 ms a lane at fp32 and fp64. The walk
           is of the lanes the stride and shard take (the arithmetic
           progression H.sweep_keys), not of every float of the range as it
           was before parcel MB2: one fp64 binade (2^52 floats) at stride
           2^30 is 2^22 lanes and begins at once, where the walk of every
           float would not have ended in years
  family   the committed windows (mathlib_family): every centre, its
           neighbours inside and outside, the census arguments that are
           not centres and, at fp128 and fp256, the deep arguments below
           the census (exp, expm1); exp2's lack of a family
  live     the live-value count of each fragment in the design's order and
           scheduled, that the reorder is a permutation (the digest of the
           dataflow graph), the lanes equal, and each fragment on seq.py
  reduction  the trigonometric reduction of parcel M2G1
           (mathlib.build_reduction, python/tests/test_mathlib_reduction.py's
           checks) at fp64, fp128 and fp256 by default: --n random arguments a
           format (exponent uniform over the range, every significand bit
           random, both signs), every power of two of the range, the products'
           binade edges widened to --edge-width significands either side, the
           floats next to the odd multiples of pi/4 in every --halves-step-th
           binade, the pools and the deepest cancellations; each lane against
           |x| 2/pi in exact rationals from host/src/mp_2opi.h (r's relative
           error under 2^-(p+G+3), the quadrant, the cushion past pi/4) and
           every claim of the build audited. Prints, a format, the lanes, r's
           largest error in units of 2^-(p+G), the largest overshoot past
           pi/4 against the computed bound, and the audit's tally. --quick
           takes every 16th power of two and leaves out the study's own
           families (the golden stage's smoke run). Not part of `all`
  reduction-tw  fp32's triple-word reduction of parcel M2F1
           (mathlib.build_reduction(FP32), G = 40; python/tests/
           test_mathlib_reduction_tw.py's checks) over the model's reduce mode's
           five families (docs/studies/m2/tw32_run.py, 14,021 arguments):
           --n random, bucket-edge, power-of-two and pool arguments (the
           study's redcheck, seed --seed), the products' binade edges, 2,000
           floats within 3 ulps of odd multiples of pi/4 of random size, the
           quadrant boundaries from k = 0, and the floats next to the odd
           multiples of pi/4 in every binade, which needs numpy (without it
           that family is skipped and said so). Per family and in total: r's
           largest relative error in units of 2^-(p+G), quadrants off, the
           audit's failures, the largest overshoot past pi/4 against the
           computed bound. --quick: --n 100 and every 20th lane. Not part of
           `all`
  trig-pools  sin, cos and tan (parcel M2G2a; mathlib.fragment at fp64, fp128
           and fp256, python/tests/mathlib_trig_harness.py's checks): the whole
           radian pools (4,408, 620 and 614 arguments) through every
           configuration, every unmarked lane equal to transcend.py in bits
           and flag word, every past-range lane marked, every other mark on
           the committed list; with --seq each fragment as a stand-alone
           program on seq.py and as the compiled shape (QUIET, the body,
           ENDQUIET, RAISE) over the same lanes. --step N: every Nth lane of the
           pools (1: all). --quick: --step 8, and fp128 under rne and rtz where
           --formats and --attrs are not given (the golden stage's smoke
           run). Not part of `all`
  trig-bound  sin, cos and tan: |V - f(x)| / Bv under 1, mpmath at 4p + 200
           bits, at --n placed points of each of the study's five regions
           (edge, near, zero, small, random; a seed each from --seed on) of
           each format (12,000 at fp64 and 3,000 at fp128 and fp256 by
           default, the study's box sizes), under --attrs (rne by default,
           the study's budgets), each lane also against transcend.py. The
           largest is a sampled lower bound. --quick: 12 points a region and
           fp128 only. Not part of `all`
  trig-budget  the first-order budget of sin, cos and tan (parcel M2G2b;
           python/tests/mathlib_trig_budget.py, the study's 3.2): the bound it
           states, M's largest value plus the rounding instructions' largest
           capacities in units of Bv, which the true worst cannot pass and which
           must be under 1, at --n lanes of each of the study's five regions
           (edge, near, zero, small, random; seeds --seed + 0, 1, 4, 2, 3: the
           study's 21, 22, 25, 23, 24, and its box runs' 121 to 125) of each
           format (12,000 at fp64 and 3,000 at fp128 and fp256 by default),
           rne; no sampled lane's error past
           its bound; the residual stated beside it; and V bit-identical across
           the five attributes on every --attrs-step-th lane (1: every one),
           so that the rne budget is every attribute's. --quick: 12 lanes a
           region and fp128 only. Not part of `all`
  trig-rate  the mark-rate law of sin, cos and tan (parcel M2G2b): the bound
           inflated to G' = 6, --n lanes of the random region (50,000 at fp64
           and 20,000 at fp128 and fp256 by default, seed --seed), each cell's
           count of marks against the sample's own expectation, judged by its
           exact two-sided tail, the cells of the run as the independent
           statistics they hold (--statistics K names the run's K when the run
           is several processes), every unmarked lane right and every marked
           guess right; under --attrs (rne and rtz by default). These cells are
           a family of their own, never added to test_mathlib.py's 90. --quick:
           400 lanes and fp128 only. Not part of `all`
  trig-family  the structured families of sin, cos and tan (parcel M2G2b;
           python/tests/mathlib_trig_family.py, the study's 3.5), wider than the
           golden stage's: for each format, function and attribute (all five
           by default) the census counts (the tiny family and the minimisers'
           neighbours equal the study's tables), every committed centre with
           its neighbours inside and outside its window and the deep arguments
           beyond the committed sample (--centres N: at most this many centres
           a cell, spread over the list; 0: all), the windows' exact edges
           (up to 40 centres a cell) and the study's three measured windows
           at fp64, and with --jmax J the minimisers' neighbours out to |j| = J
           (the study's 3.5: "the window beyond |j| = 4 is not measured"),
           each classified by the theory. --write regenerates the committed list
           (mathlib_trig_family.TRIG_FAMILY), --check holds it to the theory.
           --quick: --centres 6, fp128 only. Not part of `all`
  The trig commands take --out PATH, which writes the output there and
  REFUSES a path that exists, and end with their peak memory.
  all      a standard run of each, at modest sizes (--scale multiplies them)
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import mathlib_budget as B  # noqa: E402
import mathlib_family as F  # noqa: E402
import mathlib_harness as H  # noqa: E402
from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import routines  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

BY_NAME = {f.name: f for f in H.FORMATS}
RND_BY_NAME = {v: k for k, v in sf.RND_NAMES.items()}
T0 = time.perf_counter()
FINDINGS = []


OUT = None                              # --out's file, where a command opens one


def say(msg):
    line = f"[{time.perf_counter() - T0:7.1f}s] {msg}"
    print(line, flush=True)
    if OUT is not None:
        OUT.write(line + "\n")
        OUT.flush()


def note(findings):
    for s in findings:
        FINDINGS.append(s)
        print("   FINDING:", s, flush=True)
        if OUT is not None:
            OUT.write(f"   FINDING: {s}\n")
            OUT.flush()


def open_out(path):
    """--out: the file every line is written to as well, created EXCLUSIVELY:
    a path that exists is refused, before any work, so that a run never
    overwrites an earlier one's record."""
    global OUT
    if path is None:
        return
    try:
        OUT = open(path, "x", encoding="utf-8", newline="\n")
    except FileExistsError:
        raise SystemExit(f"--out {path}: the file exists; refusing to "
                         f"overwrite it")


def peak_memory_mb():
    """This process's peak resident memory in MB (resource on Linux, the
    peak working set through ctypes on Windows), or None."""
    try:
        import resource
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return kb / 1024 if sys.platform != "darwin" else kb / 1048576
    except ImportError:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        c = Counters()
        c.cb = ctypes.sizeof(c)
        kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),
                                          ctypes.byref(c), c.cb):
            return None
        return c.PeakWorkingSetSize / 1048576
    except (AttributeError, OSError, ImportError):
        return None


def formats_of(arg, default):
    return [BY_NAME[n] for n in (arg.split(",") if arg else default)]


def attrs_of(arg):
    return [RND_BY_NAME[n] for n in arg.split(",")] if arg else \
        list(sf.RND_MODES)


def fns_of(arg):
    names = arg.split(",") if arg else list(ml.NAMES)
    for n in names:
        if n not in ml.NAMES:
            raise SystemExit(f"--fn {n!r}: one of {', '.join(ml.NAMES)}")
    return names


# ---- the commands -----------------------------------------------------------

def cmd_pools(a):
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.formats, [f.name for f in H.FORMATS]):
            for rnd in attrs_of(a.attrs):
                f = ml.fragment(fn, fmt, rnd)
                out, t = H.check_pools(f)
                note(out)
                line = (f"pools {fn} {fmt.name} {sf.RND_NAMES[rnd]}: {t.n} "
                        f"lanes, {len(t.marked)} marked (guess right "
                        f"{t.marked_right}), {len(t.wrong)} wrong unmarked; "
                        f"{len(f)} instructions, {f.live_max()} live")
                if a.edges:
                    out, te = H.check_edges(f)
                    note(out)
                    line += (f"; edge pool {te.n} lanes, {len(te.marked)} "
                             f"marked (guess right {te.marked_right}), "
                             f"{len(te.wrong)} wrong")
                if a.seq:
                    xs = sorted(set(H.pools(fmt)) | (set(H.edge_pool(fmt, fn))
                                                     if a.edges else set()))
                    out, ts = H.check_seq(f, xs)
                    note(out)
                    line += f"; seq.py {ts.n} lanes, {len(ts.wrong)} wrong"
                say(line)


def cmd_lanes(a):
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
            for rnd in attrs_of(a.attrs):
                f = ml.fragment(fn, fmt, rnd)
                out, t = H.check_random_lanes(f, a.n, a.seed)
                note(out)
                say(f"lanes {fn} {fmt.name} {sf.RND_NAMES[rnd]}: {t.n} random "
                    f"and weighted lanes, {len(t.marked)} marked, "
                    f"{len(t.wrong)} wrong unmarked, {len(t.guess_wrong)} "
                    f"wrong guesses")


def cmd_bound(a):
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.format, ["fp64"]):
            b = ml.build(fn, fmt, sf.RND_RNE, guard=a.guard)
            for label, xs in (("random", H.random_main(fmt, a.random, a.seed,
                                                       fn)),
                              ("placed", H.placed(fmt, fn)),
                              ("weighted", H.weighted(fmt, a.weighted, a.seed,
                                                      fn)),
                              ("unit", H.uniform_unit(fmt, a.weighted,
                                                      a.seed, fn))):
                out, (worst, n) = H.check_bound(b, xs, label)
                note(out)
                say(f"bound {fn} {fmt.name} {label}: {n} lanes, largest "
                    f"|V - {fn}| / Bv = 2^{worst:+.2f}")


def cmd_sweep(a):
    from fractions import Fraction
    i, n = (int(v) for v in a.shard.split("/"))
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.format, ["fp32"]):
            b = ml.build(fn, fmt, sf.RND_RNE, guard=a.guard)
            worst, where, lanes, main = -1e9, None, 0, 0
            for key in H.sweep_keys(fmt, Fraction(a.lo), Fraction(a.hi),
                                    a.stride, (i, n)):
                x = H.key_encoding(fmt, key)
                lanes += 1
                if not H.in_main(fmt, x, fn):
                    continue
                main += 1
                r = H.bound_log2(b, x)
                if r is not None and r > worst:
                    worst, where = r, x
                if r is not None and r >= 0:
                    note([f"bound: {fn} {fmt.name} {hex(x)} is past the "
                          f"bound at 2^{r:+.2f} of Bv"])
            say(f"sweep {fn} {fmt.name} [{a.lo}, {a.hi}] stride {a.stride} "
                f"shard {a.shard}: {lanes} floats, {main} on the main path, "
                f"largest |V - {fn}| / Bv = 2^{worst:+.2f}"
                + (f" at {hex(where)} = "
                   f"{float(ml._dec(fmt, where))!r}" if where is not None
                   else ""))


def cmd_budget(a):
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.format, ["fp64", "fp128", "fp256"]):
            G = ml.GUARD[fmt.name] if a.guard is None else a.guard
            b = ml.build(fn, fmt, sf.RND_RNE, guard=G)
            bud = B.Budget(b)
            regions = (
                ("x in [-1, 1]" if fn in H.EXP_FUNCS else
                 "the cancelling cells",
                 H.uniform_unit(fmt, a.unit, a.seed, fn)),
                ("weighted to the reduction's ends",
                 H.weighted(fmt, a.weighted, a.seed, fn)),
                ("placed at each path's largest |r|", H.placed(fmt, fn)))
            for label, xs in regions:
                t = time.perf_counter()
                reg = B.Budget(b).add(xs).summary()
                bud.add(xs)
                ms = (time.perf_counter() - t) / max(1, reg['lanes']) * 1000
                say(f"budget {fn} {fmt.name} G = {G} {label}: {reg['lanes']} "
                    f"lanes, bound {reg['bound']:.4f} Bv "
                    f"(2^{-B.bits_log2(reg['bound']):+.2f}) "
                    f"= M {reg['Mmax']:.4f} + capacities {reg['S_cap']:.4f}; "
                    f"largest error found {reg['Emax']:.4f}; "
                    f"{ms:.0f} ms a lane")
            s = bud.summary()
            say(f"budget {fn} {fmt.name} G = {G} ALL REGIONS: {s['lanes']} "
                f"lanes, {s['rounding']} instructions ever round: the "
                f"budget's bound {s['bound']:.4f} Bv "
                f"(2^{-B.bits_log2(s['bound']):+.2f}), margin "
                f"{B.bits_log2(s['bound']):.2f} bits; M {s['Mmax']:.4f}, "
                f"capacities {s['S_cap']:.4f}, largest error found "
                f"{s['Emax']:.4f}")
            say("   by phase (observed maxima, capacities), in Bv: " +
                "; ".join(f"{k} {v[0]:.4f}, {v[1]:.4f}"
                          for k, v in sorted(s["by_phase"].items(),
                                             key=lambda kv: -kv[1][1])))
            say("   the largest capacities: " + "; ".join(
                f"#{i} {nm} {ph} {cap:.4f}" for i, nm, ph, cap, _o in
                bud.largest(4)))
            if s["bound"] >= 1 or s["Emax"] > s["bound"] * 1.001:
                note([f"budget: {fn} {fmt.name} G = {G}: the budget's bound "
                      f"is {s['bound']:.3f} Bv (not under 1), or a lane's "
                      f"error {s['Emax']:.3f} is past it"])


def cmd_rate(a):
    fns = fns_of(a.fn)
    fmts = formats_of(a.format, [f.name for f in H.FORMATS])
    rnds = attrs_of(a.attrs)
    k = a.statistics or H.rate_statistics(fns, fmts, rnds)
    say(f"rate: {len(fns) * len(fmts) * len(rnds)} cells, {k} statistics, "
        f"alpha {a.alpha:g}: a cell is flagged when its exact two-sided tail "
        f"is under {H.rate_level(k, a.alpha):.3g}"
        + (f" (or past {a.sigmas:g} sigma, the plain line)"
           if a.sigmas is not None else ""))
    smallest = None
    for fn in fns:
        for fmt in fmts:
            for rnd in rnds:
                out, st = H.check_rate(fmt, rnd, a.n, a.seed, sigmas=a.sigmas,
                                       fn=fn, statistics=k, alpha=a.alpha)
                note(out)
                cell = f"{fn} {fmt.name} {sf.RND_NAMES[rnd]}"
                say(f"rate {cell}: {st['marked']} of {st['n']} marked, "
                    f"{st['expected']:.1f} expected (sigma "
                    f"{st['sigma']:.1f}, {st['z']:+.2f}), two-sided tail "
                    f"{st['p']:.3g}, {st['wrong']} wrong unmarked, "
                    f"{st['guess_wrong']} wrong guesses")
                if smallest is None or st["p"] < smallest[0]:
                    smallest = (st["p"], cell)
    say(f"rate: the run's smallest two-sided tail is {smallest[0]:.3g} "
        f"({smallest[1]}); a tail that small somewhere among {k} statistics "
        f"has probability at most {min(1.0, k * smallest[0]):.3g}")


def parse_seeds(arg):
    """'101-160' or '7': the seeds, inclusive."""
    lo, _, hi = arg.partition("-")
    return range(int(lo), int(hi or lo) + 1)


def cmd_rategeom(a):
    fns = fns_of(a.fn)
    fmts = formats_of(a.format, ["fp64", "fp128", "fp256"])
    seeds = parse_seeds(a.seeds)
    k = a.statistics or 2 * len(fns) * len(fmts)
    level = H.rate_level(k, a.alpha)
    say(f"rategeom: {len(seeds)} runs of {len(fns) * len(fmts)} routines and "
        f"formats, {k} statistics, alpha {a.alpha:g}: flagged when a "
        f"two-sided tail is under {level:.3g}; n = {a.n}")
    zs = {}
    flagged, expected = 0, 0.0
    for seed in seeds:
        smallest, clean = (2.0, ""), 1.0
        for fn in fns:
            for fmt in fmts:
                smp = H.RateSample(fmt, fn, a.n, seed)     # not cached: memory
                counts = (("directed",
                           sum(smp.geometric_marks(sf.RND_RTZ))),
                          ("nearest", sum(smp.geometric_marks(sf.RND_RNE))))
                for cls, c in counts:
                    zs.setdefault((fn, fmt.name, cls), []).append(
                        (c - smp.mean) / smp.sigma)
                    p = smp.p_value(c)
                    if p < smallest[0]:
                        smallest = (p, f"{fn} {fmt.name} {cls}: {c} marked, "
                                    f"{smp.mean:.1f} expected")
                clean *= (1.0 - smp.rejection(level)) ** 2
        expected += 1.0 - clean
        hit = smallest[0] < level
        flagged += hit
        say(f"rategeom seed {seed}: smallest two-sided tail {smallest[0]:.3g}"
            f" ({smallest[1]})" + ("  FLAGGED" if hit else ""))
    say(f"rategeom: {flagged} of {len(seeds)} runs flagged at alpha "
        f"{a.alpha:g}; the law says {expected:.2f} (at most "
        f"{a.alpha * len(seeds):.2f})")
    for (fn, fmt_name, cls), z in sorted(zs.items()):
        m = sum(z) / len(z)
        v = sum((x - m) ** 2 for x in z) / max(1, len(z) - 1)
        bad = len(z) >= 30 and (abs(m) > 4.5 / len(z) ** 0.5 or
                                abs(v - 1) > 4.5 * (2 / (len(z) - 1)) ** 0.5)
        sd_v = (2 / max(1, len(z) - 1)) ** 0.5
        say(f"   {fn} {fmt_name} {cls}: mean z {m:+.3f} (sd "
            f"{len(z) ** -0.5:.3f}), variance of z {v:.3f} (sd {sd_v:.3f})"
            + ("  OFF THE LAW" if bad else ""))
        if bad:
            note([f"rategeom: {fn} {fmt_name} {cls}: over {len(z)} seeds the "
                  f"z of the count has mean {m:+.3f} and variance {v:.3f}, "
                  f"which is not the law's 0 and 1 (4.5 standard errors "
                  f"allowed)"])


def cmd_family(a):
    if a.write:
        F.write()
        say("FAMILY regenerated into python/tests/mathlib_family.py")
        return
    if a.check:
        found = H.check_family_list(F.FAMILY)
        note(found)
        n = sum(len(v) for per in F.FAMILY.values() for v in per.values())
        say(f"family --check: {n} lists, {len(found)} differ from the "
            f"theory's")
        return
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
            census = F.census_log(fmt) if fn in ("log", "log2") \
                else F.census(fmt)
            for rnd in attrs_of(a.attrs):
                f = ml.fragment(fn, fmt, rnd)
                if fn in H.NOFAMILY:
                    out, t = H.check_nofamily(f)
                    note(out)
                    say(f"family {fn} {fmt.name} {sf.RND_NAMES[rnd]}: no "
                        f"family; {t.n} lanes (the census, the deep "
                        f"arguments, the floats next to the exact cases), "
                        f"{len(t.marked)} marked, {len(t.wrong)} wrong "
                        f"unmarked")
                    continue
                listed = F.FAMILY[fn][fmt.name][sf.RND_NAMES[rnd]]
                cen = listed
                if a.centres:
                    cen = cen[::max(1, len(cen) // a.centres)][:a.centres]
                have = {F.argument(fmt, c) for c in listed}
                extra = [x for x in census if x not in have]
                out, st = H.check_family(f, cen, extra=extra, deep=True)
                note(out)
                say(f"family {fn} {fmt.name} {sf.RND_NAMES[rnd]}: "
                    f"{len(cen)} centres, {st['lanes']} lanes: theory says "
                    f"mark {st['mark']} (marked {st['marked_mark']}), clear "
                    f"{st['clear']} (marked {st['marked_clear']}), either "
                    f"{st['either']} (marked {st['marked_either']}), gated "
                    f"{st['gated']}; wrong unmarked {st['wrong']}, wrong "
                    f"guesses {st['guess_wrong']}")


def cmd_live(a):
    say("live values and the reorder: each fragment as the design emits it "
        "(schedule=False) and as scheduled; the reorder a permutation (the "
        "digest of the dataflow graph); the lanes equal; the scheduled "
        "fragment on seq.py through routines.program")
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
            for rnd in attrs_of(a.attrs):
                b = ml.build(fn, fmt, rnd)
                g = b.fragment(schedule=False)
                f = ml.fragment(fn, fmt, rnd)
                same = ml.dag_digest(f) == ml.dag_digest(g)
                line = (f"live {fn} {fmt.name} {sf.RND_NAMES[rnd]}: designed "
                        f"{g.live_max()}, scheduled {f.live_max()} (cap "
                        f"{ml.LIVE_CAP[fmt.name]}); same dataflow graph: "
                        f"{same}")
                if not same:
                    note([f"live: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: the "
                          f"scheduled fragment is not the design's"])
                xs = list(H.pools(fmt))[::max(1, len(H.pools(fmt)) //
                                              a.lanes)]
                eq = all(ml.evaluate(f, x) == ml.evaluate(g, x) for x in xs)
                line += f"; {len(xs)} lanes equal to the design's order: {eq}"
                if not eq:
                    note([f"live: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: the "
                          f"scheduled fragment differs from the design's "
                          f"order"])
                try:
                    outs, words = routines.run(f, xs)
                    ok = list(zip(outs, words)) == [ml.evaluate(f, x)
                                                    for x in xs]
                    line += f"; on seq.py equal to evaluate: {ok}"
                    if not ok:
                        note([f"live: {fn} {fmt.name}: seq.py differs"])
                except AssertionError as e:
                    line += f"; routines.program refuses it: {e}"
                    note([f"live: {fn} {fmt.name} {sf.RND_NAMES[rnd]}: "
                          f"routines.program refuses the fragment: {e}"])
                try:
                    routines.program(g)
                    line += "; the design's order fits"
                except AssertionError as e:
                    line += f"; the design's order: {e}"
                say(line)


def cmd_reduction(a):
    import math
    import random
    import test_mathlib_reduction as R
    batch = 4000
    for name in (a.formats.split(",") if a.formats else
                 ["fp64", "fp128", "fp256"]):
        if name not in ("fp64", "fp128", "fp256", "fp32"):
            raise SystemExit(f"--formats {name!r}: fp64, fp128, fp256 or fp32")
        fmt, G = R.BY_NAME[name], R.G_OF[name]
        b = R.build_of(name)
        P = b.meta["reduction"]
        fam = R.families(name)
        rng = random.Random(a.seed * 1000 + fmt.width)
        rand = []
        for _ in range(a.n):
            E = rng.randint(P.Egate, P.Emax)
            m = rng.getrandbits(fmt.prec - 1) | (1 << (fmt.prec - 1))
            rand.append(R._enc(fmt, rng.getrandbits(1), m, E - fmt.prec + 1))
        pows = [R._enc(fmt, 0, 1 << (fmt.prec - 1), E - fmt.prec + 1)
                for E in range(P.Egate, P.Emax + 1, 16 if a.quick else 1)]
        sets = [("random", rand), ("every power of two", pows),
                ("binade edges", R.edge_args(
                    fmt, P, ms_around=tuple(range(-a.edge_width,
                                                  a.edge_width + 1)))),
                ("odd multiples of pi/4", R.half_args(fmt, P, a.halves_step)),
                ("the study's families", [] if a.quick else
                 list(R.main_args(name)) + list(fam["edges"])
                 + list(fam["deep"]) + list(fam["pio4"]))]
        stats, tally, lanes = {}, {}, 0
        for label, xs in sets:
            before = len(FINDINGS)
            for i in range(0, len(xs), batch):
                run = R.run_lanes(b, xs[i:i + batch])
                note(R.check_reference(run, stats))
                note(R.check_audit(run, pin=R.CLAIMS[name]))
                note(R.check_cushion(run))
                for k, v in run.tally.items():
                    tally[k] = tally.get(k, 0) + v
                lanes += len(run.rows)
            say(f"reduction {name} {label}: {len(xs)} lanes, "
                f"{len(FINDINGS) - before} findings")
        bound = R.quadrant_slack(b)
        over = stats["over"]
        say(f"reduction {name}: G = {G}, b = {P.b}: {lanes} lanes; r's "
            f"largest relative error 2^{stats['worst']:.2f} of 2^-(p+G); "
            f"largest overshoot past pi/4 "
            f"{'none' if over <= 0 else '2^%.2f' % R._log2(over)} against the "
            f"computed bound 2^{bound:.2f}; audit: {tally['claims']} claims "
            f"examined, {tally['nonfinite']} non-finite, {tally['skipped']} "
            f"skipped")


def cmd_reduction_tw(a):
    import math
    from fractions import Fraction
    import test_mathlib_reduction as RT
    import test_mathlib_reduction_tw as W
    b = W.build_tw()
    P = b.meta["reduction"]
    fmt = W.FMT
    pos = lambda xs: [x for x in xs if not x & fmt.sign_mask]
    step = 20 if a.quick else 1
    sets = [("random, bucket edges, powers of two, pools (the study's "
             "redcheck arguments)",
             [x for fam in RT.redcheck_args(fmt, P, 100 if a.quick else a.n,
                                            a.seed) for x in fam]),
            ("the products' binade edges", RT.edge_args(fmt, P)),
            ("x within 3 ulps of odd multiples of pi/4, random size, both "
             "signs (2,000)", W.edge_sample()),
            ("the quadrant boundaries from k = 0 (0x3f490fdb) and 128 random "
             "k, positive", pos(W.quad_args()))]
    if a.no_halves:
        say("the odd multiples of pi/4 in every binade: skipped (--no-halves)")
    else:
        try:
            sets.append(("the floats next to the odd multiples of pi/4 in "
                         "every binade, positive (numpy)", W.half_family()))
        except ImportError as e:
            say(f"the odd multiples of pi/4 in every binade: skipped, numpy "
                f"is not importable ({e})")
    tally, total = {}, 0
    tot = {"worst": -math.inf, "worst_x": None, "over": Fraction(0),
           "quadrant off": 0, "bad": 0}
    over_bound = b.meta["overshoot"]
    say(f"reduction fp32 (triple word): G = {W.G}, b = {P.b}, L = {P.L}, "
        f"{len(b.body)} instructions; the computed bound on |r| past pi/4 "
        f"{float(over_bound):.4e} (2^{RT._log2(over_bound):.2f}), "
        f"{len(b.meta['exact'])} claims audited")
    for label, xs in sets:
        xs = xs[::step]
        before = len(FINDINGS)
        st, bad = {}, 0
        for i in range(0, len(xs), 4000):
            run = W.run_lanes_tw(b, xs[i:i + 4000])
            note(W.check_reference(run, st))
            note(W.check_audit(run))
            note(W.check_cushion(run))
            bad += len(run.bad)
            for k, v in run.tally.items():
                tally[k] = tally.get(k, 0) + v
        total += len(xs)
        if st["worst"] > tot["worst"]:
            tot["worst"], tot["worst_x"] = st["worst"], st["worst_x"]
        tot["over"] = max(tot["over"], st["over"])
        tot["quadrant off"] += st["quadrant off"]
        tot["bad"] += bad
        say(f"  {label}: {len(xs)} arguments: r's largest relative error "
            f"2^{st['worst']:.2f} of 2^-(p+G) at {st['worst_x']:#x}; quadrant "
            f"off {st['quadrant off']}; audit failures {bad}; largest "
            f"2|t| - 1 (|r| past pi/4) {float(st['over']):.3e}; "
            f"{len(FINDINGS) - before} findings")
    ov = tot["over"]
    say(f"TOTAL {total} arguments: r's largest relative error "
        f"2^{tot['worst']:.2f} of 2^-(p+G) at {tot['worst_x']:#x} (the "
        f"model's: 2^-5.51); quadrant off {tot['quadrant off']}; audit "
        f"failures {tot['bad']}; largest overshoot MEASURED {float(ov):.3e} "
        f"(2^{RT._log2(ov):.2f}) against the COMPUTED bound "
        f"{float(over_bound):.3e} (2^{RT._log2(over_bound):.2f}), "
        f"{float(over_bound / ov):.2f} times it (the model's: 1.1); claims "
        f"examined {tally['claims']}, non-finite {tally['nonfinite']}, "
        f"skipped {tally['skipped']}")


def _trig_fns(arg):
    import mathlib_trig_harness as T
    names = arg.split(",") if arg else list(T.FUNCS)
    for n in names:
        if n not in T.FUNCS:
            raise SystemExit(f"--fn {n!r}: one of {', '.join(T.FUNCS)}")
    return names


def _trig_formats(arg, default):
    import mathlib_trig_harness as T
    names = arg.split(",") if arg else default
    for n in names:
        if n not in T.BY_NAME:
            raise SystemExit(f"--formats {n!r}: fp64, fp128 or fp256 (fp32 is "
                             f"not built: parcel M2F's)")
    return [T.BY_NAME[n] for n in names]


def _memory_line():
    mb = peak_memory_mb()
    return ("peak memory not available here" if mb is None
            else f"peak memory {mb:.0f} MB")


def cmd_trig_pools(a):
    """The whole radian pools through every configuration of sin, cos and tan
    (parcel M2G2a), with --seq the fragment as a program on seq.py and as the
    compiled shape over the same lanes."""
    import mathlib_trig_harness as T
    open_out(a.out)
    step = a.step if a.step else (8 if a.quick else 1)
    fmts = _trig_formats(a.formats, ["fp128"] if a.quick else
                         [f.name for f in T.FORMATS])
    rnds = attrs_of(a.attrs) if a.attrs else (
        [T.RNE, T.RTZ] if a.quick else list(sf.RND_MODES))
    for fmt in fmts:
        xs = list(T.radian_pools(fmt))[::step]
        for fn in _trig_fns(a.fn):
            for rnd in rnds:
                f = ml.fragment(fn, fmt, rnd)
                out, t = T.check_pools(f, xs)
                note(out)
                line = (f"trig-pools {fn} {fmt.name} {sf.RND_NAMES[rnd]}: "
                        f"{t.n} lanes, {len(t.marked)} marked (guess right "
                        f"{t.marked_right}), {len(t.range_marked)} past the "
                        f"range marked ({len(t.range_unmarked)} not), "
                        f"{len(t.off)} marks off the list, {len(t.wrong)} "
                        f"wrong unmarked; {len(f)} instructions, "
                        f"{f.live_max()} live")
                if a.seq:
                    out, lanes = T.check_seq(f, xs=xs)
                    note(out)
                    line += (f"; seq.py and the compiled shape over "
                             f"{len(lanes)} lanes: {len(out)} findings")
                say(line)
    say(f"trig-pools: {_memory_line()}")


def cmd_trig_bound(a):
    """|V - f(x)| / Bv at placed points of the study's five regions, sin, cos
    and tan (parcel M2G2a), each lane also against transcend.py."""
    import mathlib_trig_harness as T
    open_out(a.out)
    sizes = {"fp64": 12000, "fp128": 3000, "fp256": 3000}
    fmts = _trig_formats(a.formats, ["fp128"] if a.quick else
                         [f.name for f in T.FORMATS])
    rnds = attrs_of(a.attrs) if a.attrs else [T.RNE]
    for fmt in fmts:
        n = a.n if a.n else (12 if a.quick else sizes[fmt.name])
        for fn in _trig_fns(a.fn):
            for rnd in rnds:
                b = ml.build(fn, fmt, rnd, guard=a.guard)
                for k, region in enumerate(T.REGIONS):
                    xs = T.sample(fmt, region, n, a.seed + k)
                    out, (worst, main, lanes) = T.check_bound(
                        b, xs, f"{region} seed {a.seed + k}")
                    note(out)
                    say(f"trig-bound {fn} {fmt.name} {sf.RND_NAMES[rnd]} "
                        f"{region} seed {a.seed + k}: {lanes} lanes, "
                        f"{main} main-path, largest |V - {fn}| / Bv = "
                        f"2^{worst:+.2f} (a sampled lower bound), "
                        f"{len(out)} findings")
    say(f"trig-bound: {_memory_line()}")


# trig-budget's seed of each region, from --seed: the study's order and its
# seeds 21 to 25 (edge, near, small, random, zero; the zero region was added
# after the first runs), 121 to 125 on its box
BUDGET_SEED_OFFSET = {"edge": 0, "near": 1, "small": 2, "random": 3, "zero": 4}


def cmd_trig_budget(a):
    """The first-order budget at the study's regions and sizes, sin, cos and
    tan (parcel M2G2b): the bound under 1, no lane past it, the residual, V the
    same under the five attributes."""
    import mathlib_trig_budget as TB
    import mathlib_trig_harness as T
    open_out(a.out)
    sizes = {"fp64": 12000, "fp128": 3000, "fp256": 3000}
    fmts = _trig_formats(a.formats, ["fp128"] if a.quick else
                         [f.name for f in T.FORMATS])
    regions = a.regions.split(",") if a.regions else list(T.REGIONS)
    for r in regions:
        if r not in T.REGIONS:
            raise SystemExit(f"--regions {r!r}: one of {', '.join(T.REGIONS)}")
    for fmt in fmts:
        n = a.n if a.n else (12 if a.quick else sizes[fmt.name])
        for fn in _trig_fns(a.fn):
            def build(r, fn=fn, fmt=fmt):
                return (T.build_of(fn, fmt, r) if a.guard is None
                        else ml.build(fn, fmt, r, guard=a.guard))
            b = build(T.RNE)
            attrs = None if a.no_attrs else {r: build(r)
                                             for r in sf.RND_MODES}
            G = b.meta["G"]
            worst = 0.0
            for region in regions:
                seed = a.seed + BUDGET_SEED_OFFSET[region]
                xs = T.sample(fmt, region, n, seed)
                t = time.perf_counter()
                out, s = TB.check_budget(
                    b, xs, f"{region} seed {seed}", attrs=attrs,
                    attr_xs=xs[::max(1, a.attrs_step)])
                note(out)
                worst = max(worst, s["bound"])
                ms = (time.perf_counter() - t) / max(1, s["lanes"]) * 1000
                margin = -TB.bits_log2(s["bound"])
                say(f"trig-budget {fn} {fmt.name} G = {G} rne {region} seed "
                    f"{seed}: {s['lanes']} lanes ({s['skipped']} not on the "
                    f"main path), {s['rounding']} instructions ever round, "
                    f"bound {s['bound']:.4f} Bv (2^{margin:+.2f}) = M "
                    f"{s['Mmax']:.4f} + capacities {s['S_cap']:.4f}"
                    f"; largest error found {s['Emax']:.4f}; residual "
                    f"{s['resid']:.3g} (measured, not bounded)"
                    + (f"; V the same under the five attributes on "
                       f"{s['attr_lanes']} lanes: {s['attr_differ']} differ"
                       if attrs is not None else "")
                    + f"; {ms:.0f} ms a lane, {len(out)} findings")
            say(f"trig-budget {fn} {fmt.name} G = {G} ALL REGIONS: the bound "
                f"is at most {worst:.4f} Bv (stated as far as the sample "
                f"reaches the regions' extremes)")
    say(f"trig-budget: {_memory_line()}")


def cmd_trig_rate(a):
    """The mark-rate law at the study's box sizes, sin, cos and tan (parcel
    M2G2b): each cell's count against the sample's own expectation."""
    import mathlib_trig_harness as T
    open_out(a.out)
    sizes = {"fp64": 50000, "fp128": 20000, "fp256": 20000}
    fns = _trig_fns(a.fn)
    fmts = _trig_formats(a.formats, ["fp128"] if a.quick else
                         [f.name for f in T.FORMATS])
    rnds = attrs_of(a.attrs) if a.attrs else [T.RNE, T.RTZ]
    k = a.statistics or H.rate_statistics(fns, fmts, rnds)
    say(f"trig-rate: {len(fns) * len(fmts) * len(rnds)} cells, {k} "
        f"statistics, alpha {a.alpha:g}: a cell is flagged when its exact "
        f"two-sided tail is under {H.rate_level(k, a.alpha):.3g}"
        + (f" (or past {a.sigmas:g} sigma, the plain line)"
           if a.sigmas is not None else ""))
    smallest = None
    for fmt in fmts:
        n = a.n if a.n else (400 if a.quick else sizes[fmt.name])
        for fn in fns:
            for rnd in rnds:
                out, st = T.check_rate(fmt, rnd, fn, n, a.seed,
                                       sigmas=a.sigmas, statistics=k,
                                       alpha=a.alpha)
                note(out)
                cell = f"{fn} {fmt.name} {sf.RND_NAMES[rnd]}"
                say(f"trig-rate {cell}: {st['marked']} of {st['n']} marked, "
                    f"{st['expected']:.1f} expected (sigma {st['sigma']:.1f}, "
                    f"{st['z']:+.2f}), two-sided tail {st['p']:.3g}, "
                    f"{st['wrong']} wrong unmarked, {st['guess_wrong']} wrong "
                    f"guesses")
                if smallest is None or st["p"] < smallest[0]:
                    smallest = (st["p"], cell)
    say(f"trig-rate: the run's smallest two-sided tail is {smallest[0]:.3g} "
        f"({smallest[1]}); a tail that small somewhere among {k} statistics "
        f"has probability at most {min(1.0, k * smallest[0]):.3g}")
    say(f"trig-rate: {_memory_line()}")


def cmd_trig_family(a):
    """The structured families, wider than the golden stage's (parcel M2G2b):
    census counts, every centre and its window, the deep arguments, the
    windows' scans, the minimisers' neighbours out to --jmax."""
    import mathlib_trig_family as TF
    import mathlib_trig_harness as T
    if a.write:
        TF.write()
        say("TRIG_FAMILY regenerated into python/tests/mathlib_trig_family.py")
        return
    if a.check:
        found = T.check_family_list(TF.TRIG_FAMILY)
        note(found)
        n = sum(len(TF.expand(v)) for per in TF.TRIG_FAMILY.values()
                for p in per.values() for v in p.values())
        say(f"trig-family --check: {n} centres in the lists, {len(found)} "
            f"cells differ from the theory's")
        return
    open_out(a.out)
    fmts = _trig_formats(a.formats, ["fp128"] if a.quick else
                         [f.name for f in T.FORMATS])
    rnds = attrs_of(a.attrs) if a.attrs else (
        [T.RNE, T.RTZ] if a.quick else list(sf.RND_MODES))
    cap = a.centres if a.centres else (6 if a.quick else 0)
    for fmt in fmts:
        for fn in _trig_fns(a.fn):
            for rnd in rnds:
                f = ml.fragment(fn, fmt, rnd)
                cell = f"{fn} {fmt.name} {sf.RND_NAMES[rnd]}"
                for kind in ("tiny", "minnbr"):
                    out, t = T.check_census_counts(f, kind)
                    note(out)
                    table = T.TINY_COUNTS if kind == "tiny" else T.MINNBR_COUNTS
                    want = table[fmt.name][fn][0 if rnd in T.NEAREST_ATTRS
                                               else 1]
                    say(f"trig-family {cell} census {kind}: {t.n} arguments, "
                        f"{len(t.marked)} marked (the study's {want}), "
                        f"{len(t.wrong)} wrong unmarked, {len(t.guess_wrong)} "
                        f"wrong guesses")
                every = TF.centres(fmt, rnd, fn)
                cen = every
                if cap and len(cen) > cap:
                    cen = cen[::max(1, len(cen) // cap)][:cap]
                extra = []
                if a.jmax and a.jmax > TF.MINNBR_J:
                    extra = TF.minnbr_arguments(fmt, J=a.jmax)
                out, st = T.check_family(f, cen, extra=extra, deep=True)
                note(out)
                say(f"trig-family {cell} family: {len(cen)} of {len(every)} "
                    f"centres, {st['lanes']} lanes: theory says mark "
                    f"{st['mark']} (marked {st['marked_mark']}), clear "
                    f"{st['clear']} (marked {st['marked_clear']}), either "
                    f"{st['either']} (marked {st['marked_either']}), gated "
                    f"{st['gated']}; wrong unmarked {st['wrong']}, wrong "
                    f"guesses {st['guess_wrong']}")
                tiny = [c for c in cen if c[0] != "m"]
                tiny = tiny[::max(1, len(tiny) // 40)][:40]
                out, n = T.check_windows(f, tiny)
                note(out)
                say(f"trig-family {cell} windows: {len(tiny)} centres, {n} "
                    f"lanes at the windows' exact edges (inner, half way, "
                    f"outer, twice as far, either side), {len(out)} findings")
                for (fn_, rn_, c, e, J), want in T.WINDOW_SCANS.items():
                    if (fn_, rn_) == (fn, sf.RND_NAMES[rnd]) and \
                            fmt.name == "fp64":
                        out, (cnt, lo, hi) = T.check_scan(f, c, e, J, want)
                        note(out)
                        say(f"trig-family {cell} scan {c} 2^-{e} j = -{J}.."
                            f"{J}: {cnt} marked, j = {lo} .. {hi} (the "
                            f"study's {want[0]}, {want[1]} .. {want[2]})")
    say(f"trig-family: {_memory_line()}")


def cmd_all(a):
    s = a.scale
    ns = argparse.Namespace
    cmd_pools(ns(fn=None, formats=None, attrs=None, seq=False, edges=True))
    cmd_lanes(ns(fn=None, format=None, attrs=None, n=int(300 * s), seed=1))
    cmd_bound(ns(fn=None, format="fp32,fp64,fp128,fp256",
                 random=int(400 * s), weighted=int(400 * s), seed=1,
                 guard=None))
    cmd_budget(ns(fn=None, format=None, unit=int(60 * s),
                  weighted=int(60 * s), seed=1, guard=None))
    cmd_rate(ns(fn=None, format=None, attrs="rne,rtz", n=int(1500 * s),
                seed=11, sigmas=None, statistics=None, alpha=H.RATE_ALPHA))
    cmd_family(ns(write=False, check=True, fn=None, format=None, attrs=None,
                  centres=0))
    cmd_family(ns(write=False, check=False, fn=None,
                  format="fp64,fp128,fp256", attrs="rne,rtz",
                  centres=int(4 * s)))
    cmd_live(ns(fn=None, format=None, attrs="rne", lanes=60))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pools")
    p.add_argument("--fn")
    p.add_argument("--formats")
    p.add_argument("--attrs")
    p.add_argument("--seq", action="store_true")
    p.add_argument("--edges", action="store_true")
    p.set_defaults(fn_=cmd_pools)
    p = sub.add_parser("lanes")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(fn_=cmd_lanes)
    p = sub.add_parser("bound")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--random", type=int, default=400)
    p.add_argument("--weighted", type=int, default=400)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--guard", type=int,
                   help="G, instead of the decided one (fp32's at 46 fails)")
    p.set_defaults(fn_=cmd_bound)
    p = sub.add_parser("sweep")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--lo", required=True)
    p.add_argument("--hi", required=True)
    p.add_argument("--stride", type=int, default=1)
    p.add_argument("--shard", default="0/1")
    p.add_argument("--guard", type=int)
    p.set_defaults(fn_=cmd_sweep)
    p = sub.add_parser("budget")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--unit", type=int, default=60)
    p.add_argument("--weighted", type=int, default=60)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--guard", type=int)
    p.set_defaults(fn_=cmd_budget)
    p = sub.add_parser("rate")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--sigmas", type=float, default=None,
                   help="the plain line at this many sigma, no multiplicity "
                        "(default: the exact-tail rule)")
    p.add_argument("--statistics", type=int, default=None,
                   help="the independent statistics of the whole run, when "
                        "the run is several processes (default: this "
                        "process's own, two a routine and format)")
    p.add_argument("--alpha", type=float, default=H.RATE_ALPHA,
                   help="the run's false-alarm rate")
    p.set_defaults(fn_=cmd_rate)
    p = sub.add_parser("rategeom")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--seeds", default="1-20", help="a-b, inclusive")
    p.add_argument("--statistics", type=int, default=None)
    p.add_argument("--alpha", type=float, default=H.RATE_ALPHA)
    p.set_defaults(fn_=cmd_rategeom)
    p = sub.add_parser("family")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--centres", type=int, default=0,
                   help="at most this many centres a cell, spread over the "
                        "list (0: all)")
    p.add_argument("--write", action="store_true")
    p.add_argument("--check", action="store_true")
    p.set_defaults(fn_=cmd_family)
    p = sub.add_parser("live")
    p.add_argument("--fn")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--lanes", type=int, default=200)
    p.set_defaults(fn_=cmd_live)
    p = sub.add_parser("reduction")
    p.add_argument("--formats", help="fp64,fp128,fp256 (default); fp32 is "
                                     "the double word at G = 18")
    p.add_argument("--n", type=int, default=100000,
                   help="random arguments a format")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--edge-width", type=int, default=8,
                   help="significands either side of each binade edge "
                        "(the golden stage uses 2 below and 1 above)")
    p.add_argument("--halves-step", type=int, default=1,
                   help="every this many binades for the odd multiples of "
                        "pi/4")
    p.add_argument("--quick", action="store_true",
                   help="every 16th power of two, and not the study's own "
                        "families")
    p.set_defaults(fn_=cmd_reduction)
    p = sub.add_parser("reduction-tw")
    p.add_argument("--n", type=int, default=1000,
                   help="random arguments (the model's reduce mode: 1000)")
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--no-halves", action="store_true",
                   help="leave out the odd multiples of pi/4 in every binade "
                        "(numpy)")
    p.add_argument("--quick", action="store_true",
                   help="--n 100 and every 20th argument")
    p.set_defaults(fn_=cmd_reduction_tw)
    p = sub.add_parser("trig-pools")
    p.add_argument("--fn", help="sin,cos,tan (all by default)")
    p.add_argument("--formats", help="fp64,fp128,fp256 (all by default)")
    p.add_argument("--attrs", help="rne,rtz,rdn,rup,rmm (all by default)")
    p.add_argument("--seq", action="store_true")
    p.add_argument("--step", type=int, default=0,
                   help="every this many lanes of the pools (default 1)")
    p.add_argument("--quick", action="store_true",
                   help="--step 8, fp128 under rne and rtz by default")
    p.add_argument("--out", help="write the output here too; a path that "
                                 "exists is refused")
    p.set_defaults(fn_=cmd_trig_pools)
    p = sub.add_parser("trig-bound")
    p.add_argument("--fn", help="sin,cos,tan (all by default)")
    p.add_argument("--formats", help="fp64,fp128,fp256 (all by default)")
    p.add_argument("--attrs", help="rne (by default; the study's budgets)")
    p.add_argument("--n", type=int, default=0,
                   help="points a region (default 12,000 at fp64, 3,000 at "
                        "fp128 and fp256)")
    p.add_argument("--seed", type=int, default=121,
                   help="the first region's seed, one more each (the "
                        "study's box runs: 121 to 125)")
    p.add_argument("--guard", type=int,
                   help="G, instead of the decided one")
    p.add_argument("--quick", action="store_true",
                   help="12 points a region, fp128 only by default")
    p.add_argument("--out", help="write the output here too; a path that "
                                 "exists is refused")
    p.set_defaults(fn_=cmd_trig_bound)
    p = sub.add_parser("trig-budget")
    p.add_argument("--fn", help="sin,cos,tan (all by default)")
    p.add_argument("--formats", help="fp64,fp128,fp256 (all by default)")
    p.add_argument("--regions", help="edge,near,zero,small,random (all by "
                                     "default)")
    p.add_argument("--n", type=int, default=0,
                   help="lanes a region (default 12,000 at fp64, 3,000 at "
                        "fp128 and fp256)")
    p.add_argument("--seed", type=int, default=121,
                   help="edge's seed; near, small, random and zero take one "
                        "more each, in the study's order (its box runs: 121 "
                        "to 125; its own runs 21 to 25)")
    p.add_argument("--attrs-step", type=int, default=1,
                   help="V under the five attributes on every this many "
                        "lanes (default 1: every lane)")
    p.add_argument("--no-attrs", action="store_true",
                   help="leave the attributes' leg out")
    p.add_argument("--guard", type=int, help="G, instead of the decided one")
    p.add_argument("--quick", action="store_true",
                   help="12 lanes a region, fp128 only by default")
    p.add_argument("--out", help="write the output here too; a path that "
                                 "exists is refused")
    p.set_defaults(fn_=cmd_trig_budget)
    p = sub.add_parser("trig-rate")
    p.add_argument("--fn", help="sin,cos,tan (all by default)")
    p.add_argument("--formats", help="fp64,fp128,fp256 (all by default)")
    p.add_argument("--attrs", help="rne,rtz (by default)")
    p.add_argument("--n", type=int, default=0,
                   help="lanes a cell (default 50,000 at fp64, 20,000 at "
                        "fp128 and fp256)")
    p.add_argument("--seed", type=int, default=7,
                   help="the sample's seed (the study's box run: 7)")
    p.add_argument("--statistics", type=int, default=None,
                   help="the independent statistics of the whole run, when "
                        "the run is several processes (default: this "
                        "process's own, two a function and format)")
    p.add_argument("--alpha", type=float, default=H.RATE_ALPHA,
                   help="the run's false-alarm rate")
    p.add_argument("--sigmas", type=float, default=None,
                   help="the plain line at this many sigma, no multiplicity")
    p.add_argument("--quick", action="store_true",
                   help="400 lanes a cell, fp128 only by default")
    p.add_argument("--out", help="write the output here too; a path that "
                                 "exists is refused")
    p.set_defaults(fn_=cmd_trig_rate)
    p = sub.add_parser("trig-family")
    p.add_argument("--fn", help="sin,cos,tan (all by default)")
    p.add_argument("--formats", help="fp64,fp128,fp256 (all by default)")
    p.add_argument("--attrs", help="rne,rtz,rdn,rup,rmm (all by default)")
    p.add_argument("--centres", type=int, default=0,
                   help="at most this many centres a cell, spread over the "
                        "list (0: all)")
    p.add_argument("--jmax", type=int, default=0,
                   help="the minimisers' neighbours out to |j| = this "
                        "(the study's 4), classified by the theory")
    p.add_argument("--quick", action="store_true",
                   help="--centres 6, fp128 under rne and rtz by default")
    p.add_argument("--out", help="write the output here too; a path that "
                                 "exists is refused")
    p.add_argument("--write", action="store_true")
    p.add_argument("--check", action="store_true")
    p.set_defaults(fn_=cmd_trig_family)
    p = sub.add_parser("all")
    p.add_argument("--scale", type=float, default=1.0)
    p.set_defaults(fn_=cmd_all)
    a = ap.parse_args(argv)
    a.fn_(a)
    verdict = "ok" if not FINDINGS else f"{len(FINDINGS)} findings"
    say(f"RESULT: {verdict}")
    return 1 if FINDINGS else 0


if __name__ == "__main__":
    sys.exit(main())
