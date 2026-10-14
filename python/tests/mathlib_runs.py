# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The larger runs of parcels E1 and MB1: the checks of test_mathlib.py at
sizes the golden stage does not run, as a script, for exp, exp2 and expm1.

    python python/tests/mathlib_runs.py pools   [--fn exp2] [--formats fp64]
        [--seq] [--edges]
    python python/tests/mathlib_runs.py lanes   --fn expm1 --format fp64
        --n 5000 --seed 3
    python python/tests/mathlib_runs.py bound   --fn exp2 --format fp64
        --random 2000 --weighted 2000
    python python/tests/mathlib_runs.py budget  --fn expm1 --format fp64
        --unit 300 --weighted 300
    python python/tests/mathlib_runs.py rate    --fn exp2 --format fp64
        --n 20000 --attrs rne,rtz
    python python/tests/mathlib_runs.py family  [--fn expm1] [--format fp64]
        [--centres 0]
    python python/tests/mathlib_runs.py sweep   --fn expm1 --format fp32
        --lo -0.3 --hi 0.3 --stride 1 --shard 0/36
    python python/tests/mathlib_runs.py family  --write | --check
    python python/tests/mathlib_runs.py live
    python python/tests/mathlib_runs.py all     [--scale 1]

--fn is a list of exp, exp2 and expm1 (all three by default). Each command
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
  rate     the mark-rate law with the bound inflated to G' = 6
  sweep    the bound over EVERY float of a range (--lo, --hi, decimal
           numbers, exact), every --stride-th of them, shard i of n of
           those (--shard i/n, so n processes cover the range): the largest
           ratio found and where, for the lead's box. A range of 2^23 floats
           (one binade) costs about 2 ms a lane at fp32 and fp64
  family   the committed windows (mathlib_family): every centre, its
           neighbours inside and outside, the census arguments that are
           not centres and, at fp128 and fp256, the deep arguments below
           the census (exp, expm1); exp2's lack of a family
  live     the live-value count of each fragment in the design's order and
           scheduled, that the reorder is a permutation (the digest of the
           dataflow graph), the lanes equal, and each fragment on seq.py
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


def say(msg):
    print(f"[{time.perf_counter() - T0:7.1f}s] {msg}", flush=True)


def note(findings):
    for s in findings:
        FINDINGS.append(s)
        print("   FINDING:", s, flush=True)


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
            for idx, x in enumerate(H.range_encodings(fmt, Fraction(a.lo),
                                                      Fraction(a.hi))):
                if idx % a.stride or (idx // a.stride) % n != i:
                    continue
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
                ("x in [-1, 1]", H.uniform_unit(fmt, a.unit, a.seed, fn)),
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
    for fn in fns_of(a.fn):
        for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
            for rnd in attrs_of(a.attrs):
                out, st = H.check_rate(fmt, rnd, a.n, a.seed,
                                       sigmas=a.sigmas, fn=fn)
                note(out)
                dev = (st['marked'] - st['expected']) / st['sigma']
                say(f"rate {fn} {fmt.name} {sf.RND_NAMES[rnd]}: "
                    f"{st['marked']} of {st['n']} marked, "
                    f"{st['expected']:.1f} expected (sigma "
                    f"{st['sigma']:.1f}, {dev:+.2f}), {st['wrong']} wrong "
                    f"unmarked, {st['guess_wrong']} wrong guesses")


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
            census = F.census(fmt)
            for rnd in attrs_of(a.attrs):
                f = ml.fragment(fn, fmt, rnd)
                if fn == "exp2":
                    out, t = H.check_nofamily(f)
                    note(out)
                    say(f"family {fn} {fmt.name} {sf.RND_NAMES[rnd]}: no "
                        f"family; {t.n} lanes (the census, the deep "
                        f"arguments, the floats next to integers), "
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
                seed=11, sigmas=3.0))
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
    p.add_argument("--sigmas", type=float, default=3.0)
    p.set_defaults(fn_=cmd_rate)
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
