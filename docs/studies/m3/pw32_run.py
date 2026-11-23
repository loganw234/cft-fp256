# M3 model: the driver of parcel M3X, one mode a run (scratch). pow and powr at
# fp32 as a triple word (pw32.py), measured. Each run's output is kept as
# pw32_<mode>[-<detail>].out.txt, its command and time in the parcel's ledger.
#
#   python pw32_run.py costs
#   python pw32_run.py live
#   python pw32_run.py bound FN [N] [B1exp B2exp] [region,region,...]
#   python pw32_run.py control
#   python pw32_run.py pools {model|seq|regions|fallback} [FN] [N]
#   python pw32_run.py rate {wide|lists} [FN] [N] [set]
#   python pw32_run.py plants
#   python pw32_run.py slice
#
# Run from docs/studies/m3: m3core.py puts python/ on the path.

import math
import random
import sys
import time
from collections import Counter
from fractions import Fraction

from m3core import (ml, sf, routines, FP32, FP64, ATTRS, AN, RNE, RTZ, RDN,
                    RUP, RMM, dec, golden, lg, enc)
import m3pow as M
import m3harness as H
import regions as RG
import census as CE
import pw32
import pw32_budget as PB

MARK = ml.MARK
FNS = ("pow", "powr")
fmt = FP32


def _b(fn, rnd, **kw):
    return pw32.build(fn, rnd, **kw)


_FRAG = {}


def frag(b, key):
    if key not in _FRAG:
        _FRAG[key] = b.fragment()
    return _FRAG[key]


def max_register(f):
    """The highest register routines.program gives (its allocation, restated:
    inputs in r0 and r1, values by first free from r2 up, a source's register
    free for the instruction that last reads it)."""
    last = {}
    for i, (_op, _r, srcs) in enumerate(f.body):
        for s in srcs:
            if s[0] in ("v", "in"):
                last[s] = i
    last[f.result] = last[f.flags] = len(f.body)
    reg = {("in", n): k for k, n in enumerate(f.inputs)}
    free = list(range(len(f.inputs), routines.seq.NREG))
    top = len(f.inputs) - 1
    for i, (_op, _rnd, srcs) in enumerate(f.body):
        for s in set(srcs):
            if s[0] in ("v", "in") and last.get(s) == i:
                free.append(reg[s])
        free.sort()
        if not free:
            return None
        reg[("v", i)] = free.pop(0)
        top = max(top, reg[("v", i)])
    return top


# ---- costs ------------------------------------------------------------------

def mode_costs():
    for fn in FNS:
        for rnd in ATTRS:
            b = _b(fn, rnd)
            keep = b.live_indices()
            f = b.fragment()
            f0 = b.fragment(schedule=False)
            parts = Counter(pw32.PARTS[b.label_of[i]] for i in keep)
            labels = Counter(b.label_of[i] for i in keep)
            bad = ml.invariants(f, live_cap=None)
            fw = routines.flag_words(f)
            print(f"fp32 {fn} {AN[rnd]}: instructions {len(f.body)}, bank "
                  f"words {len(f.words)}, live {f.live_max()} scheduled / "
                  f"{f0.live_max()} design order, TwoSum {b.meta['two_sum']}"
                  f", Fast2Sum {b.meta['fast_two_sum']} (built, before "
                  f"pruning)")
            print(f"    by part: " + ", ".join(
                f"{k} {parts[k]}" for k in ("logarithm", "product",
                                             "exponential", "test",
                                             "specials")))
            if rnd == RNE:
                print("    by label: " + ", ".join(
                    f"{k} {v}" for k, v in sorted(labels.items(),
                                                  key=lambda kv: -kv[1])))
                m = b.meta
                print(f"    plan: G {m['G']}, GL {m['GL']} (logarithm "
                      f"K3,K2,D = {m['KL']}), exponential K3,K2,D = "
                      f"{m['KE']}, B1 2^{lg(m['B1']):.0f}, B2 "
                      f"2^{lg(m['B2']):.0f}")
                print(f"    static proofs held: {', '.join(m['proofs'])}")
            print(f"    invariants (live_cap None): "
                  f"{'; '.join(bad) if bad else 'none failing'}")
            fwt = "unknown" if fw is None else \
                "{" + ", ".join(f"{v:#x}" for v in sorted(fw)) + "}"
            print(f"    flag words: {fwt}")


# ---- live -------------------------------------------------------------------

def _live_orders(b):
    f0 = b.fragment(schedule=False)
    keep = b.live_indices()
    phases = [b.phase_of[i] for i in keep]
    ranked = ml.permuted(f0, ml._ranked_order(f0, phases)).live_max()
    dfs = ml.permuted(f0, ml._dfs_order(f0)).live_max()
    return f0, ranked, dfs, f0.live_max()


def mode_live():
    print("phase map (label -> PHASE_ORDER name):")
    for k, v in pw32.PHASE_MAP.items():
        print(f"    {k:12s} {v}")
    for fn in FNS:
        for rnd in ATTRS:
            b = _b(fn, rnd)
            f0, ranked, dfs, design = _live_orders(b)
            f = b.fragment()
            same = ml.dag_digest(f0) == ml.dag_digest(f)
            top = max_register(f)
            try:
                prog, bank = routines.program(f)
                acc = f"accepted ({len(prog.insns)} words of program, " \
                      f"{len(bank)} bank words)"
            except AssertionError as exc:
                acc = f"REFUSED: {exc}"
            print(f"fp32 {fn} {AN[rnd]}: live scheduled {f.live_max()} "
                  f"(by phase {ranked}, depth first {dfs}, design order "
                  f"{design}); dag_digest equal to the design order's: "
                  f"{same}; routines.program {acc}; highest register r{top}; "
                  f"the allocator beside a call: 30 less the cap = "
                  f"{30 - f.live_max()} other values")


# ---- bound ------------------------------------------------------------------

def mode_bound(args):
    fn = args[0]
    n = int(args[1]) if len(args) > 1 else 300
    e1 = int(args[2]) if len(args) > 2 and args[2] != "-" else None
    e2 = int(args[3]) if len(args) > 3 and args[3] != "-" else None
    names = args[4].split(",") if len(args) > 4 else list(RG.NAMES)
    t0 = time.time()
    b = _b(fn, RNE, B1=None if e1 is None else Fraction(1, 2 ** e1),
           B2=None if e2 is None else Fraction(1, 2 ** e2))
    rows = []
    for name in names:
        lanes = RG.region(fmt, fn, name, n, 1)
        s = PB.report(b, lanes, name, time.time())
        rows.append((name, s))
    print(f"\nSUMMARY fp32 {fn}, {n} lanes a region, seed 1, rne, B1 "
          f"{'2^' + str(e1) if e1 is not None else '2^-66 (first)'}, B2 "
          f"{'2^' + str(e2) if e2 is not None else '2^-67 (first)'}:")
    worst = 0.0
    nmeas = sum(1 for _n, s_ in rows if s_["lanes"])
    for name, s in rows:
        tot = s["bound"] + s["resid"]
        worst = max(worst, tot)
        if s["lanes"] == 0:
            print(f"  {name:8s} NOT MEASURED (0 lanes: no main-path lane in "
                  f"the region for {fn})")
            continue
        ok = "under 1" if tot < 1 else "OVER 1"
        print(f"  {name:8s} lanes {s['lanes']:4d}  bound {s['bound']:.6f} + "
              f"residual {s['resid']:.2e} = {tot:.6f} Bv ({ok}); margin "
              f"{-math.log2(tot) if tot > 0 else float('inf'):.2f} bits; "
              f"measured worst {s['Emax']:.6f}")
    print(f"  worst region bound {worst:.6f} Bv, margin "
          f"{-math.log2(worst):.2f} bits, over the {nmeas} of {len(rows)} "
          f"regions measured; {time.time() - t0:.0f} s")


def mode_control():
    t0 = time.time()
    lanes = RG.region(FP64, "pow", "edge", 120, 1)
    b = M.build("pow", FP64, RNE)
    print("control: this tool (pw32_budget.TWBudget, V as Vh and Vl) on the "
          "model's fp64 pow, region edge, 120 lanes, seed 1; the reference "
          "is budget.fp64-pow-edge.out.txt (the model's own tool)")
    s = PB.report(b, lanes, "edge", t0)
    ref = open("budget.fp64-pow-edge.out.txt").read().splitlines()
    want = {"M": [ln for ln in ref if "M max" in ln][0].strip(),
            "worst": [ln for ln in ref if "measured worst" in ln][0].strip(),
            "resid": [ln for ln in ref if "residual" in ln][0].strip(),
            "active": [ln for ln in ref if "rounding instructions"
                       in ln][0].strip()}
    got = {"M": f"M max {s['Mmax']:.6f} Bv; capacities {s['S_cap']:.6f} Bv; "
                f"BOUND {s['bound']:.6f} Bv (2^{lg(s['bound']):.2f})",
           "worst": None, "resid": None,
           "active": f"rounding instructions active {s['rounding']}"}
    ok = got["M"] == want["M"] and got["active"] == want["active"]
    print(f"control: bound line equal to the reference's: {got['M'] == want['M']}"
          f"; active roundings equal: {got['active'] == want['active']}")
    print(f"  reference: {want['M']}")
    print(f"  this tool: {got['M']}")
    print("CONTROL " + ("REPRODUCES the bound to its printed digits"
                        if ok else "DOES NOT reproduce"))
    return ok


# ---- pools ------------------------------------------------------------------

def _compare(builder, fn, lanes, rnd, via_seq=False, stop=100):
    """The model (or the scheduled fragment on seq.py) against transcend.py:
    {lanes, marked, wrong, guess_wrong, diff (the fragment's against the
    model's own), marks [(lane, bits, fl, want, class)], wrong_ex}."""
    b = builder(fn, rnd)
    out = {"lanes": 0, "marked": 0, "wrong": 0, "guess_wrong": 0, "diff": 0,
           "marks": [], "wrong_ex": []}
    if via_seq:
        f = b.fragment()
        outs, words = routines.run(f, [ln[0] for ln in lanes],
                                   [ln[1] for ln in lanes])
        res = list(zip(outs, words))
    for k, lane in enumerate(lanes):
        mb, mf, _ = M.run(b, fn, lane)
        if via_seq:
            bits, fl = res[k]
            if (bits, fl) != (mb, mf):
                out["diff"] += 1
        else:
            bits, fl = mb, mf
        want = golden(fmt, fn, lane, rnd)
        out["lanes"] += 1
        same = (bits, fl & ~MARK) == want
        if fl & MARK:
            out["marked"] += 1
            if not same:
                out["guess_wrong"] += 1
            if len(out["marks"]) < stop:
                out["marks"].append((lane, bits, fl, want,
                                     CE.classify(fmt, fn, lane)))
        elif not same:
            out["wrong"] += 1
            if len(out["wrong_ex"]) < 20:
                out["wrong_ex"].append((lane, bits, fl, want))
    return out


def _print_cfg(tag, fn, rnd, r, show_marks=True):
    cls = Counter(m[4] for m in r["marks"])
    print(f"{tag} fp32 {fn:5s} {AN[rnd]}: lanes {r['lanes']}, marked "
          f"{r['marked']}, wrong guesses {r['guess_wrong']}, differing from "
          f"the model {r['diff']}, WRONG UNMARKED {r['wrong']}"
          + (f"; marks by class {dict(sorted(cls.items()))}"
             if r["marks"] else ""), flush=True)
    for lane, bits, fl, want, c in (r["marks"] if show_marks else []):
        ok = (bits, fl & ~MARK) == want
        print(f"    mark [{c}] x={lane[0]:#010x} y={lane[1]:#010x}: guess "
              f"({bits:#x}, {fl:#x}) want ({want[0]:#x}, {want[1]:#x}) "
              f"{'guess right' if ok else 'guess WRONG'}")
    for lane, bits, fl, want in r["wrong_ex"]:
        print(f"    WRONG x={lane[0]:#010x} y={lane[1]:#010x}: got "
              f"({bits:#x}, {fl:#x}) want ({want[0]:#x}, {want[1]:#x})")


def mode_pools(args):
    which = args[0]
    fns = [args[1]] if len(args) > 1 else list(FNS)
    t0 = time.time()
    total = 0
    if which in ("model", "seq"):
        for fn in fns:
            lanes = H.pool(fmt, fn)
            print(f"pool of {fn}: {len(lanes)} lanes (m3harness.pool, fp32)")
            for rnd in ATTRS:
                r = _compare(_b, fn, lanes, rnd, via_seq=(which == "seq"))
                total += r["wrong"]
                _print_cfg(which, fn, rnd, r)
    elif which == "regions":
        n = int(args[2]) if len(args) > 2 else 100
        for fn in fns:
            for name in RG.NAMES:
                lanes = RG.region(fmt, fn, name, n, 1)
                cells = []
                for rnd in ATTRS:
                    r = _compare(_b, fn, lanes, rnd, via_seq=True)
                    total += r["wrong"]
                    cells.append(r)
                print(f"seq fp32 {fn:5s} region {name:8s}: {len(lanes)} "
                      f"lanes x 5 attributes, marked "
                      + "/".join(str(r["marked"]) for r in cells)
                      + f" (rne/rtz/rdn/rup/rmm), differing from the model "
                      + "/".join(str(r["diff"]) for r in cells)
                      + f", WRONG UNMARKED {sum(r['wrong'] for r in cells)}",
                      flush=True)
                for r, rnd in zip(cells, ATTRS):
                    for lane, bits, fl, want in r["wrong_ex"][:3]:
                        print(f"    {AN[rnd]} WRONG x={lane[0]:#010x} "
                              f"y={lane[1]:#010x} got ({bits:#x},{fl:#x}) "
                              f"want ({want[0]:#x},{want[1]:#x})")
    elif which == "fallback":
        total = _fallback(fns)
    print(f"{which}: {total} wrong unmarked lanes in all; "
          f"{time.time() - t0:.0f} s")


def fallback_G():
    """The largest G at which the model's double word builds pow and powr at
    fp32, by its own refusal (the plan raises past the floor)."""
    for G in range(40, 0, -1):
        try:
            for fn in FNS:
                M.build(fn, fmt, RNE, G=G)
            return G
        except ValueError as exc:
            last = str(exc)
    raise AssertionError("no G builds: " + last)


def _fallback(fns):
    G0 = fallback_G()
    print(f"the double word at fp32: the largest G the model's m3pow.build "
          f"accepts is {G0}")
    for G in (G0 + 1, G0 + 2):
        try:
            M.build("pow", fmt, RNE, G=G)
        except ValueError as exc:
            print(f"  G = {G}: refused: {exc}")
    total = 0
    for fn in fns:
        for rnd in ATTRS:
            b = M.build(fn, fmt, rnd, G=G0)
            f = b.fragment()
            print(f"double word fp32 {fn} {AN[rnd]} G={G0}: instructions "
                  f"{len(f.body)}, words {len(f.words)}, live {f.live_max()}"
                  f", highest register r{max_register(f)}; meta GL "
                  f"{b.meta['GL']}, B1 2^{lg(b.meta['B1']) if b.meta['B1'] else '-inf'}")
    lanes_of = {fn: H.pool(fmt, fn) for fn in fns}

    def builder(fn, rnd):
        return M.build(fn, fmt, rnd, G=G0)
    for fn in fns:
        lanes = lanes_of[fn]
        for rnd in ATTRS:
            r = _compare(builder, fn, lanes, rnd, via_seq=False)
            total += r["wrong"]
            _print_cfg(f"double word G={G0}", fn, rnd, r, show_marks=False)
    return total


# ---- the mark-rate law ------------------------------------------------------

def _sig(fmt_, bits):
    q = abs(float(dec(fmt_, bits)))
    e = math.floor(math.log2(q))
    return q / 2.0 ** e


def _wide_lanes(fn, n, seed):
    return RG.region(fmt, fn, "wide", n, seed)


def mode_rate_wide(args):
    n = int(args[0]) if args else 2000
    fns = [args[1]] if len(args) > 1 else list(FNS)
    G = pw32.GUARD
    shift = G - 6
    t0 = time.time()
    for fn in fns:
        lanes = _wide_lanes(fn, n, 3)
        print(f"fp32 {fn} region wide: {len(lanes)} lanes, seed 3, G' = 6 (the "
              f"bound 2^{shift} times its own, B1 and B2 with it)")
        for rnd in (RNE, RTZ):
            b = _b(fn, rnd, bound_shift=shift)
            used = obs = wrong = gw = 0
            exp = 0.0
            var = 0.0
            capped = 0
            sigs = []
            ex_true = 0.0
            for lane in lanes:
                bits, fl, pr = M.run(b, fn, lane, ("R", "Bv", "ex", "tinyt",
                                                   "th0", "Vh"))
                if pr["ex"] & ~fmt.sign_mask or pr["tinyt"] & ~fmt.sign_mask:
                    continue
                if not RG.main_lane(fmt, fn, lane):
                    continue
                inf = sf.inf_bits(fmt)
                if (pr["R"] & ~fmt.sign_mask) >= inf or \
                        not (pr["R"] & ~fmt.sign_mask):
                    continue
                Rq = abs(float(dec(fmt, pr["R"])))
                Bvq = float(dec(fmt, pr["Bv"]))
                if not Bvq:
                    continue
                e = math.floor(math.log2(Rq))
                ulp = 2.0 ** (e - fmt.prec + 1)
                s = ulp / 2 if rnd in (RNE, RMM) else ulp
                pm = min(1.0, 2 * Bvq / s)
                exp += pm
                var += pm * (1 - pm)
                capped += pm == 1.0
                ex_true += 2 * Bvq / s / 2 ** shift
                sigs.append(_sig(fmt, pr["Vh"]))
                mk = bool(fl & MARK)
                obs += mk
                used += 1
                want = golden(fmt, fn, lane, rnd)
                same = (bits, fl & ~MARK) == want
                if mk and not same:
                    gw += 1
                if not mk and not same:
                    wrong += 1
            z = (obs - exp) / math.sqrt(exp) if exp > 0 else float("nan")
            zb = (obs - exp) / math.sqrt(var) if var > 0 else float("nan")
            msig = sum(sigs) / len(sigs)
            nominal = 2.0 ** -(G - 1) * msig * (2 if rnd == RNE else 1)
            actual = ex_true / used
            print(f"  {AN[rnd]}: {used} lanes, marked {obs}, the law predicts "
                  f"{exp:.1f}, z = {z:+.2f} (rate.py's Poisson form), "
                  f"Bernoulli z = {zb:+.2f} (variance sum p(1-p) = "
                  f"{var:.1f}; {capped} of {used} lanes have p = 1); "
                  f"wrong guesses {gw}, WRONG "
                  f"UNMARKED {wrong}; mean sig(V) {msig:.4f}")
            print(f"    rate at G = 40, COMPUTED: nominal 2^-(G-1) mean "
                  f"sig(V){' x 2' if rnd == RNE else ''} = {nominal:.3e} "
                  f"(2^{math.log2(nominal):.2f}) a main-path call; with this "
                  f"region's own bounds (B1, B2 terms) the mean of 2 Bv / s "
                  f"= {actual:.3e} (2^{math.log2(actual):.2f})", flush=True)
    print(f"{time.time() - t0:.0f} s")


# the study's lists (plan.md, "Questions for Logan", 2): nine x, nine y
X_LIST = (("0.5", 0x3F000000), ("1-2^-24", 0x3F7FFFFF),
          ("1+2^-23", 0x3F800001), ("1.5", 0x3FC00000), ("2", 0x40000000),
          ("3", 0x40400000), ("10", 0x41200000), ("2^-126", 0x00800000),
          ("maxN", 0x7F7FFFFF))
Y_LIST = (("-2", 0xC0000000), ("-1", 0xBF800000), ("-0.5", 0xBF000000),
          ("0.5", 0x3F000000), ("1.5", 0x3FC00000), ("2", 0x40000000),
          ("3", 0x40400000), ("2^-20", 0x35800000), ("2^20", 0x49800000))


def mode_rate_lists(args):
    """The study's lists as samples: 4,096 uniformly random 32-bit patterns
    for the free operand of each slice, rne and rtz."""
    fns = [args[0]] if args else list(FNS)
    n = int(args[1]) if len(args) > 1 else 4096
    which = args[2] if len(args) > 2 else "both"
    t0 = time.time()
    for fn in fns:
        for kind, lst in (("x", X_LIST), ("y", Y_LIST)):
            if which not in ("both", kind):
                continue
            for label, fixed in lst:
                rng = random.Random(hash((fn, kind, label)) & 0xFFFF
                                    if False else 20261123 + fixed)
                free = [rng.getrandbits(32) for _ in range(n)]
                lanes = [(fixed, v) if kind == "x" else (v, fixed)
                         for v in free]
                cells = []
                for rnd in (RNE, RTZ):
                    r = _compare(_b, fn, lanes, rnd, stop=10 ** 9)
                    ex = sum(1 for m in r["marks"] if m[4] != "irr")
                    cells.append((rnd, r, ex))
                line = ", ".join(
                    f"{AN[rnd]}: marked {r['marked']} (exact cases {ex}, "
                    f"others {r['marked'] - ex}), WRONG UNMARKED {r['wrong']}"
                    for rnd, r, ex in cells)
                rate = ", ".join(
                    f"{AN[rnd]} {(r['marked'] - ex) / len(lanes):.2e}"
                    for rnd, r, ex in cells)
                print(f"fp32 {fn:5s} slice {kind}-fixed {label:8s} "
                      f"({fixed:#010x}), {len(lanes)} lanes: {line}; "
                      f"sample mark rate of the non-exact marks {rate} "
                      + "; as a 95 % upper bound on the rate, the rule of "
                      + "three, " + ", ".join(
                          f"{AN[rnd]} <= {max(3.0, 1.0 * (r['marked'] - ex)) / len(lanes):.2e} a lane"
                          for rnd, r, ex in cells)
                      + " (a bound on the sample, not an extrapolation)",
                      flush=True)
    print(f"{time.time() - t0:.0f} s")


def main():
    mode, args = sys.argv[1], sys.argv[2:]
    if mode == "costs":
        mode_costs()
    elif mode == "live":
        mode_live()
    elif mode == "bound":
        mode_bound(args)
    elif mode == "control":
        mode_control()
    elif mode == "slice":
        mode_slice()
    elif mode == "plants":
        mode_plants()
    elif mode == "pools":
        mode_pools(args)
    elif mode == "rate":
        if args[0] == "wide":
            mode_rate_wide(args[1:])
        elif args[0] == "exact":
            mode_rate_exact(args[1:])
        else:
            mode_rate_lists(args[1:])
    else:
        raise SystemExit(f"unknown mode {mode!r}")




# ---- the plants ---------------------------------------------------------------

def _bound_of(fn, region, n, plant):
    b = _b(fn, RNE, plant=plant)
    lanes = RG.region(fmt, fn, region, n, 1)
    bud = PB.TWBudget(b).add(lanes)
    s = bud.summary()
    return s["bound"] + s["resid"], s["lanes"], s["Emax"]


def _marks_under_shift(fn, n, plant):
    shift = pw32.GUARD - 6
    lanes = _wide_lanes(fn, n, 3)
    b = _b(fn, RNE, bound_shift=shift, plant=plant)
    marked = wrong = used = 0
    exp = 0.0
    var = 0.0
    for lane in lanes:
        bits, fl, pr = M.run(b, fn, lane, ("ex", "tinyt", "R", "Bv"))
        if pr["ex"] & ~fmt.sign_mask or pr["tinyt"] & ~fmt.sign_mask:
            continue
        if not RG.main_lane(fmt, fn, lane):
            continue
        if (pr["R"] & ~fmt.sign_mask) >= sf.inf_bits(fmt) or                 not (pr["R"] & ~fmt.sign_mask):
            continue
        used += 1
        e = math.floor(math.log2(abs(float(dec(fmt, pr["R"])))))
        pm = min(1.0, 2 * float(dec(fmt, pr["Bv"])) /
                 (2.0 ** (e - fmt.prec + 1) / 2))
        exp += pm
        var += pm * (1 - pm)
        marked += bool(fl & MARK)
        if not fl & MARK and (bits, fl & ~MARK) != golden(fmt, fn, lane, RNE):
            wrong += 1
    return used, marked, wrong, exp, var


def mode_plants():
    t0 = time.time()
    print("plant 1, l3_dropped: " + pw32.PLANTS["l3_dropped"])
    for plant in (None, "l3_dropped"):
        tot, lanes, em = _bound_of("pow", "wide", 100, plant)
        print(f"  bound mode, fp32 pow region wide, 100 lanes, seed 1, rne, "
              f"plant {plant}: bound + residual {tot:.6g} Bv over {lanes} "
              f"lanes, measured worst {em:.6g} Bv -> "
              f"{'RED (over 1)' if tot >= 1 else 'green (under 1)'}",
              flush=True)
    print("plant 2, b1_dropped: " + pw32.PLANTS["b1_dropped"])
    for region in ("edge", "near1"):
        for plant in (None, "b1_dropped"):
            tot, lanes, em = _bound_of("pow", region, 100, plant)
            print(f"  bound mode, fp32 pow region {region}, 100 lanes, seed "
                  f"1, rne, plant {plant}: bound + residual {tot:.6g} Bv "
                  f"over {lanes} lanes, measured worst {em:.6g} Bv -> "
                  f"{'RED (over 1)' if tot >= 1 else 'green (under 1)'}",
                  flush=True)
    print("plant 3, mark_silenced: " + pw32.PLANTS["mark_silenced"])
    base = None
    for plant in (None, "mark_silenced"):
        used, marked, wrong, exp, var = _marks_under_shift("pow", 600, plant)
        if plant is None:
            base = marked
        z = (marked - exp) / math.sqrt(var)
        print(f"  rate mode, fp32 pow region wide, 600 lanes, seed 3, G' = 6,"
              f" rne, plant {plant}: {used} main-path lanes, marked "
              f"{marked}, the law predicts {exp:.1f}, Bernoulli z = {z:+.2f}, WRONG "
              f"UNMARKED {wrong} -> "
              f"{'RED (under half the control' + chr(39) + 's marks)' if marked < base / 2 else 'green (the control: the law over-predicts, see the rate mode)'}",
              flush=True)
    lanes = H.pool(fmt, "pow")
    for plant in (None, "mark_silenced"):
        r = _compare(lambda f_, rnd_: _b(f_, rnd_, plant=plant), "pow",
                     lanes, RNE)
        print(f"  pools mode (model), fp32 pow, rne, {len(lanes)} lanes, "
              f"plant {plant}: marked {r['marked']}, WRONG UNMARKED "
              f"{r['wrong']} -> "
              f"{'RED (wrong unmarked lanes)' if r['wrong'] else 'green'}",
              flush=True)
    print(f"{time.time() - t0:.0f} s")


# ---- the slice rate on software -------------------------------------------------
#
# The oracle's microseconds are MEASURED by a C timer in the parcel's scratch
# folder (not committed: oracle_timer.c, built with the desktop's mingw64 and
# MPFR 4.2.2 against host/tools/mpfr_tfn.h, calling ieee_tfn_oracle and raw_tfn);
# its output lines are kept in pw32_slice-oracle.out.txt, which this mode reads.

import re

SLICES = 57
LANES = 2 ** 32
TILE_NS = 0.98                       # the plan's figure per instruction (READ)
SOFT_US = (0.23, 0.32)               # M4X's software backend per instruction (READ)
ATAN2_INS, ATAN2_SLICE_H = 518, 31.0 / 9      # plan.md: 31 h for nine slices (READ)
THREADS = 36                         # amd-arc-box (CLAUDE.md, READ)
LINE = re.compile(r"^(\w+) n=(\d+) (\w+) fixed=(\S+) N=(-?\d+): raw_tfn "
                  r"([\d.]+) us, oracle x1 ([\d.]+) us, oracle x5 ([\d.]+) us")


def mode_slice():
    rows = []
    for ln in open("pw32_slice-oracle.out.txt").read().splitlines():
        m = LINE.match(ln)
        if m:
            rows.append((m.group(1), m.group(3), m.group(4), int(m.group(5)),
                         float(m.group(6)), float(m.group(7)),
                         float(m.group(8))))
    print("oracle rows read from pw32_slice-oracle.out.txt: "
          f"{len(rows)} (name, mode, fixed, n, raw_tfn us, oracle x1 us, "
          "oracle x5 us a lane; MEASURED)")
    for fn in FNS:
        cnt = []
        for rnd in ATTRS:
            f = _b(fn, rnd).fragment()
            cnt.append(len(f.body) + 5)
        tot5 = sum(cnt)
        print(f"{fn}: instructions + 5 (the compiled shape) under rne/rtz/"
              f"rdn/rup/rmm {'/'.join(map(str, cnt))}; five attributes a "
              f"lane {tot5} (COMPUTED from pw32.build at this tree)")
        print(f"  device, per lane per attribute (rne): {cnt[0]} x "
              f"{TILE_NS} ns = {cnt[0] * TILE_NS / 1000:.3f} us on a tile "
              f"(COMPUTED); `all` (five runs): {tot5 * TILE_NS / 1000:.3f} us")
        print(f"  software, per lane per attribute (rne): {cnt[0]} x "
              f"{SOFT_US[0]}..{SOFT_US[1]} us = "
              f"{cnt[0] * SOFT_US[0]:.0f} to {cnt[0] * SOFT_US[1]:.0f} us "
              f"(COMPUTED from M4X's per-instruction figures); `all`: "
              f"{tot5 * SOFT_US[0]:.0f} to {tot5 * SOFT_US[1]:.0f} us")
    # the oracle's side, by function
    for fn in ("pow", "powr", "pown", "rootn", "compound"):
        sel = [r for r in rows if r[0] == fn]
        if not sel:
            continue
        for key in sorted({(r[1] == "rand", r[3]) for r in sel}):
            grp = [r for r in sel if (r[1] == "rand", r[3]) == key]
            lab = "both operands random" if key[0] else                 "an operand fixed (the lists' slices)"
            x1 = [r[5] for r in grp]
            x5 = [r[6] for r in grp]
            print(f"oracle {fn} n={key[1]}, {lab}: {len(grp)} runs, oracle x1 "
                  f"{min(x1):.3f} to {max(x1):.3f} us a lane, x5 "
                  f"{min(x5):.3f} to {max(x5):.3f} us a lane (MEASURED)")
    # the totals
    pw = [r for r in rows if r[0] == "pow" and r[1] != "rand"]
    prw = [r for r in rows if r[0] == "powr" and r[1] != "rand"]
    pick = {}
    for fn, grp in (("pow", pw), ("powr", prw)):
        if grp:
            pick[fn] = (sum(r[6] for r in grp) / len(grp),
                        max(r[6] for r in grp))
    ins_pow = len(_b("pow", RNE).fragment().body) + 5
    ins_all = sum(len(_b("pow", r).fragment().body) + 5 for r in ATTRS)
    print("\nTOTALS for 57 slices of 2^32 lanes (COMPUTED; formulas shown)")
    # the device
    dev1 = SLICES * LANES * ins_all * TILE_NS * 1e-9 / 3600
    print(f"  device on tiles, instruction-bound: slices x 2^32 x (five "
          f"attributes' instructions {ins_all}) x {TILE_NS} ns = "
          f"{dev1:.0f} tile-hours; over T tiles, {dev1:.0f} / T hours "
          f"(T is the card's tiles in use, not measured here)")
    plan_pace = SLICES * ATAN2_SLICE_H * ins_pow / ATAN2_INS
    print(f"  the plan's other basis, atan2's pace scaled by instructions: "
          f"{SLICES} x {ATAN2_SLICE_H:.2f} h x {ins_pow} / {ATAN2_INS} = "
          f"{plan_pace:.0f} h (the plan's 200 h is {SLICES} x "
          f"{ATAN2_SLICE_H:.2f}; its 440 h scales by 1,150 / {ATAN2_INS})")
    soft = [SLICES * LANES * ins_all * u * 1e-6 / 3600 for u in SOFT_US]
    print(f"  software backend (the device's own function on software), "
          f"single thread: slices x 2^32 x {ins_all} x "
          f"{SOFT_US[0]}..{SOFT_US[1]} us = {soft[0]:.3g} to {soft[1]:.3g} "
          f"hours; over {THREADS} threads {soft[0] / THREADS:.3g} to "
          f"{soft[1] / THREADS:.3g} h")
    for fn, (mean5, mx5) in pick.items():
        h1 = SLICES * LANES * mean5 * 1e-6 / 3600
        print(f"  oracle `all` path, {fn}'s list slices, five oracle calls a "
              f"lane (an upper bound: the sweep tool derives four from one "
              f"evaluation): mean {mean5:.3f} us a lane (max {mx5:.3f}): "
              f"{SLICES} x 2^32 x {mean5:.3f} us = {h1:.3g} hours single "
              f"thread; {h1 / THREADS:.3g} h over {THREADS} threads")
    print("\nTHE PACE, one process a tile, device and oracle in sequence "
          "(the lead's formula, notes-W1.md item 10): a slice costs "
          "2^32 x (device `all` + O), O the oracle seconds a lane in that "
          "process; the quad's four tiles run one process each, so 57 "
          "slices take 57 x 2^32 x (device + O) / 4")
    dev_all = ins_all * TILE_NS / 1000          # us a lane, five attributes
    for fn, grp in (("pow", pw), ("powr", prw)):
        if not grp:
            continue
        o1 = sum(r[5] for r in grp) / len(grp)
        o5 = sum(r[6] for r in grp) / len(grp)
        for lab, o in (("one call", o1), ("five calls", o5)):
            slice_h = LANES * (dev_all + o) * 1e-6 / 3600
            quad_h = SLICES * slice_h / 4
            print(f"  {fn}, O = {o:.3f} us ({lab}, mean of the 18 list "
                  f"slices; MEASURED): a slice {LANES} x ({dev_all:.3f} + "
                  f"{o:.3f}) us = {slice_h:.1f} h on one tile; 57 slices on "
                  f"the quad {quad_h:.0f} h (COMPUTED); oracle share "
                  f"{o / (dev_all + o) * 100:.0f} %")
    print("  a threaded oracle (36 threads beside the call) is a later "
          "step and not the tool as it is; what it would give is the "
          "oracle's 28.8 h above spread, with the device alone then "
          f"{SLICES * LANES * dev_all * 1e-6 / 3600 / 4:.0f} h on four tiles")
    print("  units: the 309 above is tile-hours, instruction-bound, one "
          "process a tile without an oracle; the 352 is card hours at "
          "atan2's measured pace (plan.md:96, 31 h for nine slices = "
          "3.44 h a slice), which includes atan2's own oracle and its 70 % "
          "marked lanes; they are not one range")


def _structured():
    """The free operand's structured candidates: integers to 256 and the
    halves, quarters and eighths to 32, either sign (where exact cases and
    the midpoints live; a sample of 4,096 uniform encodings meets almost
    none of them)."""
    vals = set()
    for k in range(1, 257):
        vals.add(Fraction(k))
    for q in (2, 4, 8):
        for k in range(1, 32 * q + 1):
            vals.add(Fraction(k, q))
    out = []
    for v in sorted(vals):
        out.append(enc(fmt, v))
        out.append(enc(fmt, -v))
    return out


def mode_rate_exact(args):
    fns = [args[0]] if args else list(FNS)
    t0 = time.time()
    free = _structured()
    for fn in fns:
        for kind, lst in (("x", X_LIST), ("y", Y_LIST)):
            for label, fixed in lst:
                lanes = [(fixed, v) if kind == "x" else (v, fixed)
                         for v in free]
                cells = []
                for rnd in (RNE, RTZ):
                    r = _compare(_b, fn, lanes, rnd, stop=10 ** 9)
                    ex = sum(1 for m in r["marks"] if m[4] != "irr")
                    cells.append((rnd, r, ex))
                line = ", ".join(
                    f"{AN[rnd]}: marked {r['marked']} (exact cases {ex}, "
                    f"others {r['marked'] - ex}), WRONG UNMARKED {r['wrong']}"
                    for rnd, r, ex in cells)
                print(f"fp32 {fn:5s} structured {kind}-fixed {label:8s} "
                      f"({fixed:#010x}), {len(lanes)} lanes: {line}",
                      flush=True)
    print(f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
