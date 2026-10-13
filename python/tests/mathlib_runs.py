# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The larger runs of parcel E1: the checks of test_mathlib.py at sizes the
golden stage does not run, as a script.

    python python/tests/mathlib_runs.py pools   [--formats fp64,fp128] [--seq]
    python python/tests/mathlib_runs.py lanes   --format fp64 --n 5000 --seed 3
    python python/tests/mathlib_runs.py bound   --format fp64
        --random 2000 --weighted 2000
    python python/tests/mathlib_runs.py budget  --format fp64
        --unit 300 --weighted 300
    python python/tests/mathlib_runs.py rate    --format fp64 --n 20000
        --attrs rne,rtz
    python python/tests/mathlib_runs.py family  [--format fp64] [--centres 0]
    python python/tests/mathlib_runs.py family  --write | --check
    python python/tests/mathlib_runs.py live
    python python/tests/mathlib_runs.py all     [--scale 1]

Each command prints what it ran and what it measured, then a line
"RESULT: ok" or "RESULT: N findings" and exits 0 or 1. Pure Python, one
process, one core: the lanes are softfloat.compute one instruction at a time
(about 1 ms a lane at fp64 and 2 ms at fp256), the references mpmath and
transcend.py. Every sample is a function of --seed, so a run can be repeated.

  pools    the transcend pools through each fragment, and with --seq through
           seq.py as a stand-alone program
  lanes    random arguments with every bit random, and the weighted
           sampler's, through each fragment against transcend.exp
  bound    |V - mpmath| / Bv over random arguments with every bit random,
           over the places each path's reduced argument is largest, and over
           the weighted sampler: the largest ratio found, a lower bound on
           the true worst
  budget   verifier-VM1b's first-order budget over the same regions: the
           bound it states, which the true worst cannot pass
           (mathlib_budget); fp64, fp128 and fp256 only
  rate     the mark-rate law with the bound inflated to G' = 6
  family   the committed windows (mathlib_family): every centre, its
           neighbours inside and outside, the census arguments that are
           not centres and, at fp128 and fp256, the deep arguments below
           the census
  live     the live-value count of each fragment, and what emitting every
           special's condition just before its use does to it
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


# ---- the commands -----------------------------------------------------------

def cmd_pools(a):
    for fmt in formats_of(a.formats, [f.name for f in H.FORMATS]):
        for rnd in attrs_of(a.attrs):
            f = ml.fragment("exp", fmt, rnd)
            out, t = H.check_pools(f)
            note(out)
            line = (f"pools {fmt.name} {sf.RND_NAMES[rnd]}: {t.n} lanes, "
                    f"{len(t.marked)} marked (guess right "
                    f"{t.marked_right}), {len(t.wrong)} wrong unmarked; "
                    f"{len(f)} instructions, {f.live_max()} live")
            if a.seq and fmt.name != "fp32":
                out, ts = H.check_seq(f)
                note(out)
                line += f"; seq.py {ts.n} lanes, {len(ts.wrong)} wrong"
            say(line)


def cmd_lanes(a):
    for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
        for rnd in attrs_of(a.attrs):
            f = ml.fragment("exp", fmt, rnd)
            out, t = H.check_random_lanes(f, a.n, a.seed)
            note(out)
            say(f"lanes {fmt.name} {sf.RND_NAMES[rnd]}: {t.n} random and "
                f"weighted lanes, {len(t.marked)} marked, {len(t.wrong)} "
                f"wrong unmarked, {len(t.guess_wrong)} wrong guesses")


def cmd_bound(a):
    for fmt in formats_of(a.format, ["fp64"]):
        b = ml.build_exp(fmt, sf.RND_RNE, guard=a.guard)
        for label, xs in (("random", H.random_main(fmt, a.random, a.seed)),
                          ("placed", H.placed_exp(fmt)),
                          ("weighted", H.weighted_exp(fmt, a.weighted,
                                                      a.seed))):
            out, (worst, n) = H.check_bound(b, xs, label)
            note(out)
            say(f"bound {fmt.name} {label}: {n} lanes, largest |V - exp| / "
                f"Bv = 2^{worst:+.2f}")


def cmd_budget(a):
    for fmt in formats_of(a.format, ["fp64", "fp128", "fp256"]):
        G = ml.GUARD[fmt.name] if a.guard is None else a.guard
        b = ml.build_exp(fmt, sf.RND_RNE, guard=G)
        bud = B.Budget(b)
        regions = (
            ("x in [-1, 1]", H.uniform_unit(fmt, a.unit, a.seed)),
            ("weighted to the reduction's ends",
             H.weighted_exp(fmt, a.weighted, a.seed)),
            ("placed at each path's largest |r|", H.placed_exp(fmt)))
        for label, xs in regions:
            t = time.perf_counter()
            reg = B.Budget(b).add(xs).summary()
            bud.add(xs)
            ms = (time.perf_counter() - t) / max(1, reg['lanes']) * 1000
            say(f"budget {fmt.name} G = {G} {label}: {reg['lanes']} lanes, "
                f"bound {reg['bound']:.4f} Bv "
                f"(2^{-B.bits_log2(reg['bound']):+.2f}) "
                f"= M {reg['Mmax']:.4f} + capacities {reg['S_cap']:.4f}; "
                f"largest error found {reg['Emax']:.4f}; "
                f"{ms:.0f} ms a lane")
        s = bud.summary()
        say(f"budget {fmt.name} G = {G} ALL REGIONS: {s['lanes']} lanes, "
            f"{s['rounding']} instructions ever round: the budget's bound "
            f"{s['bound']:.4f} Bv (2^{-B.bits_log2(s['bound']):+.2f}), "
            f"margin {B.bits_log2(s['bound']):.2f} bits; M {s['Mmax']:.4f}, "
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
            note([f"budget: {fmt.name} G = {G}: the budget's bound is "
                  f"{s['bound']:.3f} Bv (not under 1), or a lane's error "
                  f"{s['Emax']:.3f} is past it"])


def cmd_rate(a):
    for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
        for rnd in attrs_of(a.attrs):
            out, st = H.check_rate(fmt, rnd, a.n, a.seed, sigmas=a.sigmas)
            note(out)
            dev = (st['marked'] - st['expected']) / st['sigma']
            say(f"rate {fmt.name} {sf.RND_NAMES[rnd]}: {st['marked']} of "
                f"{st['n']} marked, {st['expected']:.1f} expected (sigma "
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
        say(f"family --check: {sum(len(v) for v in F.FAMILY.values())} "
            f"lists, {len(found)} differ from the theory's")
        return
    for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
        census = F.census(fmt)
        for rnd in attrs_of(a.attrs):
            cen = F.FAMILY[fmt.name][sf.RND_NAMES[rnd]]
            if a.centres:
                cen = cen[::max(1, len(cen) // a.centres)][:a.centres]
            listed = F.FAMILY[fmt.name][sf.RND_NAMES[rnd]]
            have = {F.argument(fmt, c) for c in listed}
            extra = [x for x in census if x not in have]
            f = ml.fragment("exp", fmt, rnd)
            out, st = H.check_family(f, cen, extra=extra, deep=True)
            note(out)
            say(f"family {fmt.name} {sf.RND_NAMES[rnd]}: {len(cen)} centres, "
                f"{st['lanes']} lanes: theory says mark {st['mark']} (marked "
                f"{st['marked_mark']}), clear {st['clear']} (marked "
                f"{st['marked_clear']}), either {st['either']} (marked "
                f"{st['marked_either']}), gated {st['gated']}; wrong "
                f"unmarked {st['wrong']}, wrong guesses {st['guess_wrong']}")


def late_order(f):
    """f's instructions in an order that emits each value just before its
    first use: a depth-first walk from the flag word and the result, the
    larger subtree first, so that the main path is walked before the
    conditions of the specials (each of which needs only x and words), which
    then come last and are not kept live across it."""
    n = len(f.body)
    anc = [0] * n
    for i, (_op, _r, srcs) in enumerate(f.body):
        m = 1 << i
        for s in srcs:
            if s[0] == "v":
                m |= anc[s[1]]
        anc[i] = m
    size = [bin(m).count("1") for m in anc]
    order, seen = [], set()

    def visit(i):
        if i in seen:
            return
        seen.add(i)
        deps = sorted({s[1] for s in f.body[i][2] if s[0] == "v"},
                      key=lambda j: -size[j])
        for j in deps:
            visit(j)
        order.append(i)
    sys.setrecursionlimit(10000)
    for ref in (f.flags, f.result):
        visit(ref[1])
    return order


def reordered(f):
    """The fragment with its body permuted by late_order: the same
    instructions, the same words, the same result and flag word."""
    order = late_order(f)
    new = {old: k for k, old in enumerate(order)}
    body = []
    for old in order:
        op, r, srcs = f.body[old]
        body.append((op, r, tuple(("v", new[s[1]]) if s[0] == "v" else s
                                  for s in srcs)))
    return routines.Fragment(f.op, f.fmt, f.rnd, f.inputs, body,
                             ("v", new[f.result[1]]), ("v", new[f.flags[1]]),
                             f.words, f.stage)


def cmd_live(a):
    say("live values, the fragment as built, and with each special's "
        "condition emitted at its use (the same instructions, permuted)")
    for fmt in formats_of(a.format, [f.name for f in H.FORMATS]):
        for rnd in attrs_of(a.attrs):
            f = ml.fragment("exp", fmt, rnd)
            g = reordered(f)
            line = (f"live {fmt.name} {sf.RND_NAMES[rnd]}: built "
                    f"{f.live_max()} (cap {ml.LIVE_CAP[fmt.name]}), "
                    f"reordered {g.live_max()}")
            xs = list(H.pools(fmt))[::max(1, len(H.pools(fmt)) // a.lanes)]
            same = all(ml.evaluate(f, x) == ml.evaluate(g, x) for x in xs)
            line += f"; {len(xs)} lanes equal: {same}"
            if not same:
                note([f"live: {fmt.name} {sf.RND_NAMES[rnd]}: the reordered "
                      f"fragment differs from the built one"])
            try:
                outs, words = routines.run(g, xs)
                got = list(zip(outs, words))
                line += (f"; on seq.py (routines.program): equal to "
                         f"evaluate: {got == [ml.evaluate(f, x) for x in xs]}")
                if got != [ml.evaluate(f, x) for x in xs]:
                    note([f"live: {fmt.name}: the reordered fragment on "
                          f"seq.py differs"])
            except AssertionError as e:
                line += f"; routines.program refuses it: {e}"
            say(line)


def cmd_all(a):
    s = a.scale
    for fmt in H.FORMATS:
        for rnd in sf.RND_MODES:
            f = ml.fragment("exp", fmt, rnd)
            out, t = H.check_pools(f)
            note(out)
        say(f"pools {fmt.name}: all five attributes, {t.n} lanes each")
    ns = argparse.Namespace
    cmd_lanes(ns(format=None, attrs=None, n=int(300 * s), seed=1))
    cmd_bound(ns(format="fp32,fp64,fp128,fp256", random=int(400 * s),
                 weighted=int(400 * s), seed=1, guard=None))
    cmd_budget(ns(format=None, unit=int(60 * s), weighted=int(60 * s),
                  seed=1, guard=None))
    cmd_rate(ns(format=None, attrs="rne,rtz", n=int(1500 * s), seed=11,
                sigmas=3.0))
    cmd_family(ns(write=False, check=True, format=None, attrs=None,
                  centres=0))
    cmd_family(ns(write=False, check=False, format="fp64,fp128,fp256",
                  attrs="rne,rtz", centres=int(4 * s)))
    cmd_live(ns(format=None, attrs="rne", lanes=60))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pools")
    p.add_argument("--formats")
    p.add_argument("--attrs")
    p.add_argument("--seq", action="store_true")
    p.set_defaults(fn=cmd_pools)
    p = sub.add_parser("lanes")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--n", type=int, default=1000)
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(fn=cmd_lanes)
    p = sub.add_parser("bound")
    p.add_argument("--format")
    p.add_argument("--random", type=int, default=400)
    p.add_argument("--weighted", type=int, default=400)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--guard", type=int,
                   help="G, instead of the decided one (fp32's at 46 fails)")
    p.set_defaults(fn=cmd_bound)
    p = sub.add_parser("budget")
    p.add_argument("--format")
    p.add_argument("--unit", type=int, default=60)
    p.add_argument("--weighted", type=int, default=60)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--guard", type=int)
    p.set_defaults(fn=cmd_budget)
    p = sub.add_parser("rate")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--n", type=int, default=2000)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--sigmas", type=float, default=3.0)
    p.set_defaults(fn=cmd_rate)
    p = sub.add_parser("family")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--centres", type=int, default=0,
                   help="at most this many centres a cell, spread over the "
                        "list (0: all)")
    p.add_argument("--write", action="store_true")
    p.add_argument("--check", action="store_true")
    p.set_defaults(fn=cmd_family)
    p = sub.add_parser("live")
    p.add_argument("--format")
    p.add_argument("--attrs")
    p.add_argument("--lanes", type=int, default=200)
    p.set_defaults(fn=cmd_live)
    p = sub.add_parser("all")
    p.add_argument("--scale", type=float, default=1.0)
    p.set_defaults(fn=cmd_all)
    a = ap.parse_args(argv)
    a.fn(a)
    verdict = "ok" if not FINDINGS else f"{len(FINDINGS)} findings"
    say(f"RESULT: {verdict}")
    return 1 if FINDINGS else 0


if __name__ == "__main__":
    sys.exit(main())
