# M3 model: the driver of parcel M3XN, one mode a run (scratch). pown, rootn and
# compound at fp32 as a triple word (pw32n.py), measured. Each run's output is
# kept as pw32n_<mode>[-<detail>].out.txt, its command and time in the parcel's
# ledger.
#
#   python pw32n_run.py costs
#   python pw32n_run.py live
#   python pw32n_run.py bound FN N_OPERAND [LANES] [B1exp B2exp] [region,...]
#   python pw32n_run.py control
#   python pw32n_run.py pools {model|seq|regions} [FN] [N] [LANES]
#   python pw32n_run.py rate {wide|lists} ...
#   python pw32n_run.py plants
#   python pw32n_run.py slice
#
# Run from docs/studies/m3: m3core.py puts python/ on the path.

import math
import random
import re
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
import mpmath
import pw32
import pw32n
import pw32_budget as PB
import pw32n_budget as NB
import pw32_run as PR

MARK = ml.MARK
FNS = pw32n.FNS
fmt = FP32

# the brief's list of n: the sweeps' seven, the zone (1000), the words'
# boundaries (2^24 + 1, 2^40, 2^48 + 1), the small fragments (0, 1), and one
# n of three words (2^62 + 2^37 + 1) so that a third word of n exists
SWEEP_N = (2, -2, 3, -3, 17, 2 ** 31 - 1, -2 ** 63)
N_LIST = SWEEP_N + (1000, 2 ** 24 + 1, 2 ** 40, 2 ** 48 + 1,
                    2 ** 62 + 2 ** 37 + 1)
SMALL_N = (0, 1)


def _b(fn, rnd, n, **kw):
    return pw32n.build(fn, rnd, n, **kw)


def max_register(f):
    return PR.max_register(f)


def nstr(n):
    for k in (31, 48, 62, 63):
        if n == 2 ** k - 1:
            return f"2^{k}-1"
        if n == 2 ** k + 1:
            return f"2^{k}+1"
        if n == -2 ** k:
            return f"-2^{k}"
        if n == 2 ** k:
            return f"2^{k}"
    if n == 2 ** 62 + 2 ** 37 + 1:
        return "2^62+2^37+1"
    return str(n)



# ---- regions ----------------------------------------------------------------
# regions.py's own names (int, int-neg, int17, int31, int63, int1000, zone,
# zone<N>, int<N>), and one of ours: cint<N>, compound at a large n, where x
# must be about t ln 2 / n for t to be in range and regions.py's int (x
# log-uniform over the exponent range, kept when |n log2(1 + x)| < T_f) finds
# almost none: x = 2^(t / n) - 1 for t uniform in the main path's range, so
# 1 + x is formed exactly by TwoSum and x is far below 2^-24 for n past 2^24.

def _check_region(name):
    """regions.py's region() takes any name of an n-keyed function for its
    int branch; a name no region has is refused here, by name, so that a
    misspelt job fails."""
    if name not in RG.INT_NS and name != "zone" and             not re.fullmatch(r"(?:int|zone|cint)-?\d+", name):
        raise ValueError(f"no region named {name!r}")


def rg_n(fn, name):
    _check_region(name)
    m = re.fullmatch(r"cint(-?\d+)", name)
    if m:
        return int(m.group(1))
    return RG.region_n(fn, name)


def rg_region(fn, name, count, seed=1):
    _check_region(name)
    m = re.fullmatch(r"cint(-?\d+)", name)
    if not m:
        return RG.region(fmt, fn, name, count, seed)
    n = int(m.group(1))
    rng = random.Random(seed * 1000003 + 4242)
    Tf = RG._tf(fmt)
    out = []
    while len(out) < count:
        t = rng.uniform(-Tf, Tf)
        with mpmath.workprec(fmt.prec + 80):
            xv = mpmath.expm1(mpmath.mpf(t) * mpmath.log(2) / n)
            x = enc(fmt, M.ml._frac(xv))
        ax = x & ~fmt.sign_mask
        if not ax or ax >= sf.inf_bits(fmt):
            continue
        if RG.main_lane(fmt, "compound", (x, n)):
            out.append((x, n))
    return out


def lanes_n(fn, name):
    """the n a region's lanes carry"""
    return rg_n(fn, name)


def _bound_regions(fn):
    base = ["int", "int-neg", "int17", "int31", "int63", "int1000",
            "int16777217", "int1099511627776", "int281474976710657",
            "zone", "zone1000", "zone-3", "zone17"]
    if fn == "compound":
        base += ["cint2147483647", "cint-9223372036854775808",
                 "cint16777217", "cint4611686018427388929"]
    return base


# ---- costs ------------------------------------------------------------------

def mode_costs():
    for fn in FNS:
        for n in N_LIST:
            for rnd in ATTRS:
                try:
                    b = _b(fn, rnd, n)
                except Exception as exc:
                    print(f"fp32 {fn} n={nstr(n)} {AN[rnd]}: REFUSED "
                          f"{type(exc).__name__}: {exc}")
                    continue
                keep = b.live_indices()
                f = b.fragment()
                parts = Counter(pw32n.PARTS[b.label_of[i]] for i in keep)
                bad = ml.invariants(f, live_cap=None)
                fw = routines.flag_words(f)
                print(f"fp32 {fn} n={nstr(n)} {AN[rnd]}: instructions "
                      f"{len(f.body)}, bank words {len(f.words)}, Y words "
                      f"{b.meta['ywords']}, TwoSum {b.meta['two_sum']}, "
                      f"Fast2Sum {b.meta['fast_two_sum']} (built, before "
                      f"pruning)")
                print("    by part: " + ", ".join(
                    f"{k} {parts[k]}" for k in ("logarithm", "product",
                                                 "exponential", "test",
                                                 "specials")))
                if rnd == RNE:
                    m = b.meta
                    print(f"    plan: G {m['G']}, GL {m['GL']} (logarithm "
                          f"K3,K2,D = {m['KL']}), exponential K3,K2,D = "
                          f"{m['KE']}, B1 2^{lg(m['B1']):.0f}, B2 "
                          f"2^{lg(m['B2']):.0f}")
                    print(f"    static proofs held: "
                          f"{', '.join(m['proofs'])}")
                print(f"    invariants (live_cap None): "
                      f"{'; '.join(bad) if bad else 'none failing'}")
                fwt = "unknown" if fw is None else \
                    "{" + ", ".join(f"{v:#x}" for v in sorted(fw)) + "}"
                print(f"    flag words: {fwt}")
    for fn in FNS:
        for n in SMALL_N:
            for rnd in ATTRS:
                try:
                    b = _b(fn, rnd, n)
                except M.Refused as exc:
                    print(f"fp32 {fn} n={n} {AN[rnd]}: REFUSED by name: "
                          f"{exc}")
                    continue
                f = b.fragment()
                print(f"fp32 {fn} n={n} {AN[rnd]} (build_small): "
                      f"instructions {len(f.body)}, bank words "
                      f"{len(f.words)}")


# ---- live -------------------------------------------------------------------

def mode_live():
    print("phase map (label -> PHASE_ORDER name):")
    for k, v in pw32n.PHASE_MAP.items():
        print(f"    {k:12s} {v}")
    worst = {}
    for fn in FNS:
        for n in N_LIST:
            for rnd in ATTRS:
                b = _b(fn, rnd, n)
                f0, ranked, dfs, design = PR._live_orders(b)
                f = b.fragment()
                same = ml.dag_digest(f0) == ml.dag_digest(f)
                top = max_register(f)
                try:
                    prog, bank = routines.program(f)
                    acc = (f"accepted ({len(prog.insns)} program words, "
                           f"{len(bank)} bank words)")
                except AssertionError as exc:
                    acc = f"REFUSED: {exc}"
                live = f.live_max()
                key = fn
                cur = worst.get(key)
                if cur is None or live > cur[0] or \
                        (live == cur[0] and (top or 0) > cur[3]):
                    worst[key] = (live, n, rnd, top or 0)
                print(f"fp32 {fn} n={nstr(n)} {AN[rnd]}: live scheduled "
                      f"{live} (by phase {ranked}, depth first {dfs}, "
                      f"design order {design}); dag_digest equal to the "
                      f"design order's: {same}; routines.program {acc}; "
                      f"highest register r{top}", flush=True)
    for fn in FNS:
        for n in SMALL_N:
            for rnd in ATTRS:
                try:
                    f = _b(fn, rnd, n).fragment()
                except M.Refused:
                    continue
                try:
                    routines.program(f)
                    acc = "accepted"
                except AssertionError as exc:
                    acc = f"REFUSED: {exc}"
                print(f"fp32 {fn} n={n} {AN[rnd]} (build_small): live "
                      f"{f.live_max()}; routines.program {acc}; highest "
                      f"register r{max_register(f)}")
    print("\nCAPS: a function's cap is its largest scheduled live count over "
          "every n of the list (the 12 n of the core, "
          + ", ".join(nstr(n) for n in N_LIST) + ") under all five "
          "attributes")
    for fn in FNS:
        live, n, rnd, top = worst[fn]
        # every (n, attribute) reaching the cap
        sets = []
        for n2 in N_LIST:
            for r2 in ATTRS:
                if _b(fn, r2, n2).fragment().live_max() == live:
                    sets.append(f"n={nstr(n2)} {AN[r2]}")
        print(f"  {fn}: cap {live}; set by {len(sets)} of "
              f"{len(N_LIST) * len(ATTRS)} (n, attribute) cells: "
              + "; ".join(sets[:12]) + (" ..." if len(sets) > 12 else "")
              + f"; the first reaching it: n={nstr(n)} {AN[rnd]}, highest "
              f"register there r{top}; the allocator beside a call: 30 less "
              f"the cap = {30 - live} other values")


# ---- bound ------------------------------------------------------------------

def mode_bound(args):
    """bound FN [LANES] [B1exp B2exp] [region,region,...]"""
    fn = args[0]
    nl = int(args[1]) if len(args) > 1 else 300
    e1 = int(args[2]) if len(args) > 2 and args[2] != "-" else None
    e2 = int(args[3]) if len(args) > 3 and args[3] != "-" else None
    names = args[4].split(",") if len(args) > 4 else _bound_regions(fn)
    t0 = time.time()
    rows = []
    for name in names:
        n = rg_n(fn, name)
        b = _b(fn, RNE, n, B1=None if e1 is None else Fraction(1, 2 ** e1),
               B2=None if e2 is None else Fraction(1, 2 ** e2))
        lanes = rg_region(fn, name, nl, 1)
        s = NB.report(b, lanes, name, time.time())
        rows.append((name, n, s, len(lanes)))
    print(f"\nSUMMARY fp32 {fn}, {nl} lanes a region, seed 1, rne, B1 "
          f"{'2^' + str(e1) if e1 is not None else '2^-66 (first)'}, B2 "
          f"{'2^' + str(e2) if e2 is not None else '2^-67 (first)'}:")
    worst = 0.0
    nmeas = 0
    for name, n, s, got in rows:
        tot = s["bound"] + s["resid"]
        if s["lanes"] == 0:
            print(f"  {name:20s} n={nstr(n):12s} NOT MEASURED (0 measured "
                  f"lanes of {got} generated; outside the pass count)")
            continue
        nmeas += 1
        worst = max(worst, tot)
        ok = "under 1" if tot < 1 else "OVER 1"
        print(f"  {name:20s} n={nstr(n):12s} lanes {s['lanes']:4d} of {got:4d} "
              f"bound {s['bound']:.6f} + residual {s['resid']:.2e} = "
              f"{tot:.6f} Bv ({ok}); margin "
              f"{-math.log2(tot) if tot > 0 else float('inf'):.2f} bits; "
              f"measured worst {s['Emax']:.6f}")
    if nmeas == 0:
        print(f"  NOT MEASURED: no region had a measured lane; "
              f"{time.time() - t0:.0f} s")
        return
    print(f"  worst region bound {worst:.6f} Bv, margin "
          f"{-math.log2(worst):.2f} bits, over the {nmeas} of {len(rows)} "
          f"regions measured; {time.time() - t0:.0f} s")


def mode_control():
    """Two controls of pw32n_budget.NBudget: (1) the model's fp64 pown,
    region int, 120 lanes, seed 1, against budget.fp64-pown-int.out.txt (the
    model's own tool's) to its printed digits; (2) M3X's fp32 pow, region
    edge, 300 lanes, seed 1, against pw32_bound-pow.out.txt (M3X's tool's)."""
    t0 = time.time()
    ok_all = True
    # (1)
    lanes = RG.region(FP64, "pown", "int", 120, 1)
    b = M.build("pown", FP64, RNE, n=3)
    print("control 1: NBudget on the model's fp64 pown, region int, 120 "
          "lanes, seed 1; reference budget.fp64-pown-int.out.txt")
    s = NB.report(b, lanes, "int", t0)
    ref = open("budget.fp64-pown-int.out.txt").read().splitlines()
    want = [ln for ln in ref if "M max" in ln][0].strip()
    wact = [ln for ln in ref if "rounding instructions" in ln][0].strip()
    got = (f"M max {s['Mmax']:.6f} Bv; capacities {s['S_cap']:.6f} Bv; "
           f"BOUND {s['bound']:.6f} Bv (2^{lg(s['bound']):.2f})")
    gact = f"rounding instructions active {s['rounding']}"
    ok1 = got == want and gact == wact
    print(f"  reference: {want} / {wact}")
    print(f"  this tool: {got} / {gact}")
    print("CONTROL 1 " + ("REPRODUCES the bound to its printed digits"
                          if ok1 else "DOES NOT reproduce"))
    # (2)
    lanes = RG.region(FP32, "pow", "edge", 300, 1)
    b = pw32.build("pow", RNE)
    print("control 2: NBudget on pw32.build's fp32 pow, region edge, 300 "
          "lanes, seed 1; reference pw32_bound-pow.out.txt (region edge)")
    s = NB.report(b, lanes, "edge", time.time())
    ref = open("pw32_bound-pow.out.txt").read().splitlines()
    i = [k for k, ln in enumerate(ref)
         if ln.startswith("fp32 pow region edge:")][0]
    want = [ln for ln in ref[i:i + 6] if "M max" in ln][0].strip()
    wact = [ln for ln in ref[i:i + 6] if "rounding instructions" in ln][0]         .strip()
    got = (f"M max {s['Mmax']:.6f} Bv; capacities {s['S_cap']:.6f} Bv; "
           f"BOUND {s['bound']:.6f} Bv (2^{lg(s['bound']):.2f})")
    gact = f"rounding instructions active {s['rounding']}"
    ok2 = got == want and gact == wact
    print(f"  reference: {want} / {wact}")
    print(f"  this tool: {got} / {gact}")
    print("CONTROL 2 " + ("REPRODUCES the bound to its printed digits"
                          if ok2 else "DOES NOT reproduce"))
    print(f"{time.time() - t0:.0f} s")
    return ok1 and ok2


# ---- pools ------------------------------------------------------------------

def _xs(fn):
    """The x operands of a pool: m3harness.pool's x (distinct, in order) and
    structured extras (zeros, infinities, NaNs, +-1, powers of two, x next to
    1 and to -1, the compound's 2^E - 1 and the SMALL edge)."""
    one = sf.one_bits(fmt)
    xs = [ln[0] for ln in H.pool(fmt, fn)]
    ex = [0, fmt.sign_mask, sf.inf_bits(fmt), sf.inf_bits(fmt, 1),
          0x7FC00000, 0x7F800001, 0x7FC00001, one, one | fmt.sign_mask]
    for k in range(-20, 21):
        v = Fraction(2) ** k
        ex += [enc(fmt, v), enc(fmt, -v), enc(fmt, v - 1), enc(fmt, 1 - v)]
    for k in (1, 2, 3, 5, 8, 100):
        ex += [one + k, one - k, (one + k) | fmt.sign_mask,
               (one - k) | fmt.sign_mask]
    ex += [enc(fmt, Fraction(15, 256)), enc(fmt, -Fraction(15, 256)),
           enc(fmt, Fraction(241, 256))]
    seen, out = set(), []
    for v in xs + ex:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _cmp(fn, n, xs, rnd, via_seq=False, plant=None, stop=40, **kw):
    """The model (or the scheduled fragment on seq.py) at (fn, n) against
    transcend.py (golden): {lanes, marked, wrong, guess_wrong, diff, marks,
    wrong_ex}; {'refused': name} for rootn at n = 0."""
    try:
        b = _b(fn, rnd, n, plant=plant, **kw)
    except M.Refused as exc:
        return {"refused": str(exc)}
    out = {"lanes": 0, "marked": 0, "wrong": 0, "guess_wrong": 0, "diff": 0,
           "marks": [], "wrong_ex": []}
    if via_seq:
        f = b.fragment()
        outs, words = routines.run(f, list(xs))
        res = list(zip(outs, words))
    for k, x in enumerate(xs):
        mb, mf, _ = b.run(x)
        if via_seq:
            bits, fl = res[k]
            if (bits, fl) != (mb, mf):
                out["diff"] += 1
        else:
            bits, fl = mb, mf
        lane = (x, n)
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


def _print_n(tag, fn, n, rnd, r, show_marks=True):
    if "refused" in r:
        print(f"{tag} fp32 {fn} n={nstr(n)} {AN[rnd]}: REFUSED by name: "
              f"{r['refused']}", flush=True)
        return
    cls = Counter(m[4] for m in r["marks"])
    print(f"{tag} fp32 {fn:8s} n={nstr(n):12s} {AN[rnd]}: lanes "
          f"{r['lanes']}, marked {r['marked']}, wrong guesses "
          f"{r['guess_wrong']}, differing from the model {r['diff']}, WRONG "
          f"UNMARKED {r['wrong']}"
          + (f"; marks by class {dict(sorted(cls.items()))}"
             if r["marks"] else ""), flush=True)
    for lane, bits, fl, want, c in (r["marks"] if show_marks else []):
        ok = (bits, fl & ~MARK) == want
        print(f"    mark [{c}] x={lane[0]:#010x} n={lane[1]}: guess "
              f"({bits:#x}, {fl:#x}) want ({want[0]:#x}, {want[1]:#x}) "
              f"{'guess right' if ok else 'guess WRONG'}")
    for lane, bits, fl, want in r["wrong_ex"]:
        print(f"    WRONG x={lane[0]:#010x} n={lane[1]}: got "
              f"({bits:#x}, {fl:#x}) want ({want[0]:#x}, {want[1]:#x})")


def mode_pools(args):
    """pools {model|seq} [FN|-] [n,n,...]; pools regions [FN|-] [LANES];
    pools agree [FN|-]"""
    which = args[0]
    fns = [args[1]] if len(args) > 1 and args[1] != "-" else list(FNS)
    t0 = time.time()
    total = 0
    if which in ("model", "seq"):
        ns = list(N_LIST) + list(SMALL_N)
        if len(args) > 2:
            ns = [int(v) for v in args[2].split(",")]
        for fn in fns:
            xs = _xs(fn)
            print(f"pool of {fn}: {len(xs)} x operands (m3harness.pool's x "
                  f"and structured extras), at each of {len(ns)} n")
            for n in ns:
                for rnd in ATTRS:
                    r = _cmp(fn, n, xs, rnd, via_seq=(which == "seq"))
                    total += r.get("wrong", 0)
                    _print_n(which, fn, n, rnd, r, show_marks=False)
    elif which == "regions":
        nl = int(args[2]) if len(args) > 2 else 100
        for fn in fns:
            for name in _bound_regions(fn):
                n = rg_n(fn, name)
                lanes = rg_region(fn, name, nl, 1)
                if not lanes:
                    print(f"seq fp32 {fn:8s} region {name}: NOT MEASURED "
                          f"(0 lanes generated)")
                    continue
                xs = [ln[0] for ln in lanes]
                cells = [_cmp(fn, n, xs, rnd, via_seq=True) for rnd in ATTRS]
                total += sum(r["wrong"] for r in cells)
                print(f"seq fp32 {fn:8s} region {name:20s} n={nstr(n):12s}: "
                      f"{len(xs)} lanes x 5 attributes, marked "
                      + "/".join(str(r["marked"]) for r in cells)
                      + " (rne/rtz/rdn/rup/rmm), differing from the model "
                      + "/".join(str(r["diff"]) for r in cells)
                      + f", WRONG UNMARKED {sum(r['wrong'] for r in cells)}",
                      flush=True)
                for r, rnd in zip(cells, ATTRS):
                    for lane, bits, fl, want in r["wrong_ex"][:3]:
                        print(f"    {AN[rnd]} WRONG x={lane[0]:#010x} "
                              f"n={lane[1]} got ({bits:#x},{fl:#x}) want "
                              f"({want[0]:#x},{want[1]:#x})")
    elif which == "agree":
        nd = _agree(fns)
        print(f"agree: {nd} differing lanes in all (each listed above), "
              f"{time.time() - t0:.0f} s")
        return
    print(f"{which}: {total} wrong unmarked lanes in all; "
          f"{time.time() - t0:.0f} s")


def _agree(fns):
    """The independent agreement. pown(x, n) against pw32's pow(x, n as an
    fp32 value) where n is one word; rootn(x, n) against pow(x, 1/n) only
    where 1/n is an fp32 value (n a power of two), and there they are NOT an
    identity: rootn(x < 0, even n) is invalid and pow(x < 0, 1/n) is invalid
    too, but rootn(-inf, even n) is invalid where pow(-inf, 1/n) is +inf, and
    rootn(-0, 2) is +0 where pow(-0, 0.5) is +0 and the odd n of pown carry
    x's sign. Lanes unmarked in both are compared, bits and flags; the
    differing ones are printed with their class. compound has no pow twin.
    Returns the number of differing lanes."""
    nd = 0
    for fn in fns:
        if fn == "compound":
            print("compound: no pow twin (1 + x is not an operand of pow); "
                  "not compared")
            continue
        xs = _xs(fn)
        for n in (2, -2, 3, -3, 17, 1000, 2 ** 24, -2 ** 24, 2 ** 40,
                  -2 ** 40):
            yv = Fraction(n) if fn == "pown" else Fraction(1, n)
            yb = enc(fmt, yv)
            if dec(fmt, yb) != yv:
                print(f"{fn} n={nstr(n)}: {'n' if fn == 'pown' else '1/n'} "
                      f"is not an fp32 value; not compared")
                continue
            for rnd in (RNE, RTZ):
                b = _b(fn, rnd, n)
                bp = pw32.build("pow", rnd)
                both = same = 0
                diffs = []
                for x in xs:
                    bits, fl, _ = b.run(x)
                    pb, pf, _ = pw32.run(bp, "pow", (x, yb))
                    if fl & MARK or pf & MARK:
                        continue
                    both += 1
                    if (bits, fl) == (pb, pf):
                        same += 1
                    else:
                        diffs.append((x, bits, fl, pb, pf))
                nd += len(diffs)
                print(f"{fn} n={nstr(n)} {AN[rnd]}: {both} lanes unmarked "
                      f"in both, equal {same}, different {len(diffs)}",
                      flush=True)
                for x, bits, fl, pb, pf in diffs[:6]:
                    print(f"    x={x:#010x}: {fn} ({bits:#x},{fl:#x}) pow "
                          f"({pb:#x},{pf:#x})")
    return nd


# ---- the mark-rate law ------------------------------------------------------

X_N2 = {"pown": (3, 17), "rootn": (3, 17), "compound": (3, 1000)}


def mode_rate_wide(args):
    """rate wide [LANES] [FN]: the law at bound_shift = G - 6, two n per
    function, the main region (regions.py int at that n), rne and rtz. A lane
    whose p = min(1, 2 Bv / s) is 1 is AT THE CAP: it is marked for sure and
    says nothing about the law, so it is counted and left out of the judged
    cell: the cell is the lanes with p < 1, observed marks against the sum of
    p, variance the Bernoulli's, the sum of p (1 - p)."""
    nl = int(args[0]) if args else 2000
    fns = [args[1]] if len(args) > 1 else list(FNS)
    G = pw32n.GUARD
    shift = G - 6
    t0 = time.time()
    for fn in fns:
        for n in X_N2[fn]:
            rname = {3: "int", 17: "int17", 1000: "int1000"}[n]
            lanes = rg_region(fn, rname, nl, 3)
            print(f"fp32 {fn} n={n} region {rname}: {len(lanes)} lanes, "
                  f"seed 3, G' = 6 (the bound 2^{shift} times its own, B1 "
                  f"and B2 with it)")
            for rnd in (RNE, RTZ):
                b = _b(fn, rnd, n, bound_shift=shift)
                used = capped = cap_marked = wrong = gw = nov = 0
                obs_u = 0
                exp_u = var_u = 0.0
                for lane in lanes:
                    bits, fl, pr = b.run(lane[0], ("R", "Bv", "ex", "tinyt"))
                    if pr["ex"] & ~fmt.sign_mask or                             pr["tinyt"] & ~fmt.sign_mask:
                        continue
                    if not RG.main_lane(fmt, fn, lane):
                        continue
                    inf = sf.inf_bits(fmt)
                    if (pr["R"] & ~fmt.sign_mask) >= inf or                             not (pr["R"] & ~fmt.sign_mask):
                        continue
                    Rq = abs(float(dec(fmt, pr["R"])))
                    Bvq = float(dec(fmt, pr["Bv"]))
                    if not Bvq:
                        continue
                    e = math.floor(math.log2(Rq))
                    ulp = 2.0 ** (e - fmt.prec + 1)
                    s = ulp / 2 if rnd in (RNE, RMM) else ulp
                    pm = min(1.0, 2 * Bvq / s)
                    mk = bool(fl & MARK)
                    if fl & sf.FLAG_OVERFLOW:
                        # an overflowed answer is decided by the final
                        # scaling's screen and carries no mark (rate capped
                        # shows it): it is outside the law's population
                        nov += 1
                        continue
                    used += 1
                    if pm >= 1.0:
                        capped += 1
                        cap_marked += mk
                    else:
                        exp_u += pm
                        var_u += pm * (1 - pm)
                        obs_u += mk
                    want = golden(fmt, fn, lane, rnd)
                    same = (bits, fl & ~MARK) == want
                    if mk and not same:
                        gw += 1
                    if not mk and not same:
                        wrong += 1
                zb = (obs_u - exp_u) / math.sqrt(var_u) if var_u > 0                     else float("nan")
                print(f"  {AN[rnd]}: {used} main-path lanes (and {nov} "
                      f"whose answer overflows, left out: never marked); "
                      f"{capped} at "
                      f"the cap (p = 1; {cap_marked} of them marked; left "
                      f"out of the judgement); judged cell: {used - capped} "
                      f"lanes with p < 1, marked {obs_u}, the law predicts "
                      f"{exp_u:.1f}, observed / predicted "
                      f"{obs_u / exp_u if exp_u else float('nan'):.3f}, "
                      f"Bernoulli z = {zb:+.2f} (variance sum p(1-p) = "
                      f"{var_u:.1f}); wrong guesses {gw}, WRONG UNMARKED "
                      f"{wrong}", flush=True)
    print(f"{time.time() - t0:.0f} s")


def mode_rate_capped(args):
    """rate capped [LANES]: where the lanes at the cap that are NOT marked
    come from. The lanes of mode_rate_wide's cell, split by (at the cap or
    not, marked or not, the answer's kind): an unmarked lane at the cap whose
    answer is an overflow (+-inf under rne) was decided by the overflow
    screen of the final scaling and carries no mark by design; the law's
    population (regions.main_lane) includes it."""
    nl = int(args[0]) if args else 2000
    shift = pw32n.GUARD - 6
    t0 = time.time()
    for fn, n in (("pown", 3), ("rootn", 3), ("compound", 3)):
        lanes = rg_region(fn, "int", nl, 3)
        for rnd in (RNE, RTZ):
            b = _b(fn, rnd, n, bound_shift=shift)
            c = Counter()
            for ln in lanes:
                bits, fl, pr = b.run(ln[0], ("R", "Bv", "ex", "tinyt"))
                if pr["ex"] & ~fmt.sign_mask or pr["tinyt"] & ~fmt.sign_mask:
                    continue
                if not RG.main_lane(fmt, fn, ln):
                    continue
                if (pr["R"] & ~fmt.sign_mask) >= sf.inf_bits(fmt) or \
                        not (pr["R"] & ~fmt.sign_mask):
                    continue
                Rq = abs(float(dec(fmt, pr["R"])))
                Bvq = float(dec(fmt, pr["Bv"]))
                s = 2.0 ** (math.floor(math.log2(Rq)) - 23) * \
                    (0.5 if rnd == RNE else 1)
                capped = 2 * Bvq >= s
                ab = bits & ~fmt.sign_mask
                kind = ("overflow flag set" if fl & sf.FLAG_OVERFLOW else
                        "+-inf" if ab == sf.inf_bits(fmt) else
                        "zero or subnormal" if ab < (1 << 23) else "normal")
                c[("at the cap" if capped else "p < 1",
                   "marked" if fl & MARK else "unmarked", kind)] += 1
            print(f"fp32 {fn} n={n} region int, {len(lanes)} lanes, seed 3, "
                  f"G' = 6, {AN[rnd]}: "
                  + "; ".join(f"{'/'.join(k)} {v}"
                              for k, v in sorted(c.items())), flush=True)
    print(f"{time.time() - t0:.0f} s")




def mode_rate_lists(args):
    """rate lists [FN] [COUNT]: the 21 list slices as samples: for each of
    the seven n of each function, COUNT (4,096) uniformly random 32-bit
    patterns of x under rne and rtz: marks, wrong unmarked, and the marks
    that are exact cases (golden's _pown_dyadic and _rootn_dyadic: a value;
    compound's by _pown_dyadic of 1 + x) against the others; extrapolated
    to 2^32 as a COMPUTED figure (a sample is a lower bound's worth of
    evidence, not a count)."""
    fns = [args[0]] if args and args[0] != "-" else list(FNS)
    cnt = int(args[1]) if len(args) > 1 else 4096
    t0 = time.time()
    for fn in fns:
        for n in SWEEP_N:
            rng = random.Random(20261124 + n % 1000003 + len(fn))
            xs = [rng.getrandbits(32) for _ in range(cnt)]
            cells = []
            for rnd in (RNE, RTZ):
                r = _cmp(fn, n, xs, rnd, stop=10 ** 9)
                ex = sum(1 for m in r["marks"] if m[4] != "irr")
                cells.append((rnd, r, ex))
            line = ", ".join(
                f"{AN[rnd]}: marked {r['marked']} (exact cases {ex}, others "
                f"{r['marked'] - ex}), WRONG UNMARKED {r['wrong']}"
                for rnd, r, ex in cells)
            ext = ", ".join(
                f"{AN[rnd]} {(r['marked'] - ex) / cnt * 2 ** 32:.3g}"
                for rnd, r, ex in cells)
            ub = ", ".join(
                f"{AN[rnd]} <= {max(3.0, 1.0 * (r['marked'] - ex)) / cnt:.2e}"
                for rnd, r, ex in cells)
            print(f"fp32 {fn:8s} slice n={nstr(n):12s} x random, {cnt} "
                  f"lanes: {line}; non-exact marks extrapolated to 2^32 "
                  f"lanes (COMPUTED, a sample): {ext}; 95 % upper bound a "
                  f"lane by the rule of three: {ub}", flush=True)
    print(f"{time.time() - t0:.0f} s")


def mode_rate(args):
    if args[0] == "wide":
        mode_rate_wide(args[1:])
    elif args[0] == "capped":
        mode_rate_capped(args[1:])
    else:
        mode_rate_lists(args[1:])


# ---- the plants ---------------------------------------------------------------

def _bound_tot(fn, n, region, count, plant=None, rnd=RNE, **kw):
    """(bound + residual, measured lanes, measured worst) of the build at n
    over `count` lanes of `region` (seed 1), by NBudget."""
    b = _b(fn, rnd, n, plant=plant, **kw)
    lanes = rg_region(fn, region, count, 1)
    bud = NB.NBudget(b).add(lanes)
    s = bud.summary()
    return s["bound"] + s["resid"], s["lanes"], s["Emax"]


def _verdict(red, why_red, why_green="green"):
    return f"RED ({why_red})" if red else why_green


def _rate_marks(fn, n, plant, nl=600):
    """Marks under bound_shift G - 6 on the first `nl` lanes of region int
    (seed 3), rne: (lanes used, marked, wrong unmarked, expected, variance)."""
    shift = pw32n.GUARD - 6
    lanes = rg_region(fn, "int" if n == 3 else f"int{n}", nl, 3)
    b = _b(fn, RNE, n, bound_shift=shift, plant=plant)
    used = marked = wrong = 0
    exp = var = 0.0
    for lane in lanes:
        bits, fl, pr = b.run(lane[0], ("R", "Bv", "ex", "tinyt"))
        if pr["ex"] & ~fmt.sign_mask or pr["tinyt"] & ~fmt.sign_mask:
            continue
        if not RG.main_lane(fmt, fn, lane):
            continue
        if (pr["R"] & ~fmt.sign_mask) >= sf.inf_bits(fmt) or \
                not (pr["R"] & ~fmt.sign_mask):
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
    print("PLANTS of pw32n.build; each shown red in a named mode beside the "
          "control (plant None) green. A plant's threshold says its "
          "sensitivity.\n")
    # 1 l3_dropped: bound
    print("plant l3_dropped (M3X's, red in `bound`): " +
          pw32n.PLANTS["l3_dropped"])
    for fn in FNS:
        for plant in (None, "l3_dropped"):
            tot, ln, em = _bound_tot(fn, 3, "int", 100, plant)
            print(f"  bound mode, fp32 {fn} n=3 region int, 100 lanes, seed "
                  f"1, rne, plant {plant}: bound + residual {tot:.6g} Bv "
                  f"over {ln} lanes, measured worst {em:.6g} Bv -> "
                  f"{_verdict(tot >= 1, 'over 1 Bv', 'green (under 1)')}",
                  flush=True)
    # 2 b1_dropped: regions other than edge
    print("plant b1_dropped (red in a region other than `edge`): " +
          pw32n.PLANTS["b1_dropped"])
    for fn, regs in (("pown", ("int1000", "zone1000", "int17", "int")),
                     ("rootn", ("int", "int17")),
                     ("compound", ("int1000", "zone1000", "int", "int17",
                                   "cint16777217"))):
        for region in regs:
            n = rg_n(fn, region)
            for plant in (None, "b1_dropped"):
                tot, ln, em = _bound_tot(fn, n, region, 100, plant)
                print(f"  bound mode, fp32 {fn} n={nstr(n)} region {region}, "
                      f"100 lanes, seed 1, rne, plant {plant}: bound + "
                      f"residual {tot:.6g} Bv over {ln} lanes, measured worst "
                      f"{em:.6g} Bv -> "
                      f"{_verdict(tot >= 1, 'over 1 Bv', 'green (under 1)')}",
                      flush=True)
    # 3 mark_silenced: rate (threshold: under half the control's marks) and
    # pools (wrong unmarked)
    print("plant mark_silenced (red in `rate` and `pools`): " +
          pw32n.PLANTS["mark_silenced"] + "; the rate cell is RED when the "
          "plant's marks are under half the control's, so a silencing of "
          "under half is NOT seen by it (sensitivity); the pools cell is "
          "red at any wrong unmarked lane")
    for fn in FNS:
        base = None
        for plant in (None, "mark_silenced"):
            used, marked, wrong, exp, var = _rate_marks(fn, 3, plant)
            if plant is None:
                base = marked
            print(f"  rate mode, fp32 {fn} n=3 region int, 600 lanes, seed "
                  f"3, G' = 6, rne, plant {plant}: {used} main-path lanes, "
                  f"marked {marked}, the law predicts {exp:.1f}, WRONG "
                  f"UNMARKED {wrong} -> "
                  f"{_verdict(marked < base / 2, 'under half the control marks', 'green (the control)')}",
                  flush=True)
        xs = _xs(fn)
        for plant in (None, "mark_silenced"):
            tot = 0
            for n in (3, 2, -3):
                for rnd in (RNE, RTZ, RDN):
                    tot += _cmp(fn, n, xs, rnd, plant=plant)["wrong"]
            print(f"  pools mode (model), fp32 {fn} n in 3, 2, -3 x rne, "
                  f"rtz, rdn, {len(xs)} x operands, plant {plant}: WRONG "
                  f"UNMARKED {tot} -> "
                  f"{_verdict(tot > 0, 'wrong unmarked lanes', 'green')}",
                  flush=True)
    # 4 the n-word plants and the rows, in pools
    cases = (
        ("n_word_ulp", (("pown", 3), ("rootn", 3), ("compound", 3))),
        ("n_low_dropped", (("pown", 2 ** 24 + 1), ("compound", 2 ** 24 + 1))),
        ("n_word3_dropped", (("rootn", 3), ("rootn", 17),
                             ("compound", 2 ** 62 + 2 ** 37 + 1),
                             ("pown", 2 ** 62 + 2 ** 37 + 1))),
        ("n_row_loud", (("pown", 3), ("rootn", 3), ("compound", 3))),
        ("rootn_m0_neg", (("rootn", 2), ("rootn", -2))),
        ("compound_onep_rounded", (("compound", 3), ("compound", 17))),
        ("exact_rule_no_tl", (("pown", 3), ("pown", 17), ("pown", 2 ** 24 + 1),
                              ("compound", 3), ("compound", 1000))),
    )
    for plant, lst in cases:
        print(f"plant {plant}: {pw32n.PLANTS[plant]}")
        for fn, n in lst:
            xs = _xs(fn)
            if fn == "compound" and n > 2 ** 20:
                xs = xs + [ln[0] for ln in rg_region(
                    fn, f"cint{n}", 200, 1)]
            for p_ in (None, plant):
                try:
                    tot = sum(_cmp(fn, n, xs, rnd, plant=p_)["wrong"]
                              for rnd in (RNE, RTZ))
                except ValueError as exc:
                    print(f"  pools mode, fp32 {fn} n={nstr(n)}, plant "
                          f"{p_}: REFUSED by name: {exc}", flush=True)
                    continue
                print(f"  pools mode (model), fp32 {fn} n={nstr(n)}, "
                      f"{len(xs)} x operands, rne + rtz, plant {p_}: WRONG "
                      f"UNMARKED {tot} -> "
                      f"{_verdict(tot > 0, 'wrong unmarked lanes', 'green')}",
                      flush=True)
    # the bound mode for the two that act on the value
    for plant, fn, n, region in (("n_word3_dropped", "rootn", 3, "int"),
                                 ("compound_onep_rounded", "compound", 3,
                                  "int"),
                                 ("n_word_ulp", "pown", 3, "int"),
                                 ("exact_rule_no_tl", "pown", 3, "int")):
        for p_ in (None, plant):
            tot, ln, em = _bound_tot(fn, n, region, 100, p_)
            print(f"  bound mode, fp32 {fn} n={n} region {region}, 100 "
                  f"lanes, seed 1, rne, plant {p_}: bound + residual "
                  f"{tot:.6g} Bv over {ln} lanes, measured worst {em:.6g} Bv "
                  f"-> {_verdict(tot >= 1, 'over 1 Bv', 'green (under 1)')}",
                  flush=True)
    # rootn at TWO words, then THREE: the brief's demonstration
    print("rootn's 1/n at two words (words=2) against three (the default): "
          "bound mode, region int, 100 lanes, seed 1")
    for n in (3, 17, -3):
        for w in (2, 3):
            tot, ln, em = _bound_tot("rootn", n, "int" if n == 3 else
                                     rg_region_name(n), 100, None, words=w)
            print(f"  rootn n={n} words={w}: bound + residual {tot:.6g} Bv "
                  f"over {ln} lanes, measured worst {em:.6g} Bv -> "
                  f"{_verdict(tot >= 1, 'over 1 Bv', 'green (under 1)')}",
                  flush=True)
    print(f"{time.time() - t0:.0f} s")


def rg_region_name(n):
    return {3: "int", -3: "int-neg", 17: "int17"}[n]


# ---- the slice rate ----------------------------------------------------------

LANES = 2 ** 32
TILE_NS = 0.98                       # the plan's figure per instruction (READ)
ORACLE_ROW = re.compile(r"^(\w+) n=(-?\d+) rand N=(-?\d+): raw_tfn ([\d.]+) "
                        r"us, oracle x1 ([\d.]+) us, oracle x5 ([\d.]+) us")


def _ins_all(fn, n):
    """(instructions + 5 under rne, over the five attributes) at (fn, n)."""
    cnt = [len(_b(fn, rnd, n).fragment().body) + 5 for rnd in ATTRS]
    return cnt[0], sum(cnt)


def mode_slice():
    rows = {}
    for ln in open("pw32n_slice-oracle.out.txt").read().splitlines():
        m = ORACLE_ROW.match(ln)
        if m:
            rows[(m.group(1), int(m.group(2)))] = (
                float(m.group(4)), float(m.group(5)), float(m.group(6)))
    print(f"oracle rows read from pw32n_slice-oracle.out.txt: {len(rows)} "
          "(function, n) pairs (raw_tfn us, oracle x1 us, oracle x5 us a "
          "lane; MEASURED by the C timer in the parcel's scratch folder, "
          "not committed; n a C long, 32 bits here: -2^63 does not fit and "
          "is not timed)")
    dev = {}                         # (fn, n) -> instructions, five attrs
    print("\nper (function, n): instructions + 5 (rne) and over the five "
          "attributes (COMPUTED from pw32n.build at this tree); device `all` "
          "us a lane = five-attribute instructions x 0.98 ns")
    slices = []                      # (fn, n, ins_all, O1, O5, source)
    for fn in FNS:
        have = [rows[(fn, n)] for n in SWEEP_N if (fn, n) in rows]
        mean1 = sum(r[1] for r in have) / len(have)
        mean5 = sum(r[2] for r in have) / len(have)
        for n in SWEEP_N:
            i1, ia = _ins_all(fn, n)
            if (fn, n) in rows:
                o1, o5, src = rows[(fn, n)][1], rows[(fn, n)][2], "MEASURED"
            else:
                o1, o5, src = mean1, mean5, "ESTIMATE (the mean of the " \
                    f"function's {len(have)} timed n: this n does not fit " \
                    "a long)"
            print(f"  {fn:8s} n={nstr(n):12s}: {i1} instructions + 5 rne, "
                  f"five attributes {ia}; device `all` "
                  f"{ia * TILE_NS / 1000:.3f} us; oracle x1 {o1:.3f} us, x5 "
                  f"{o5:.3f} us [{src}]")
            slices.append((fn, n, ia, o1, o5))
    # M3X's 36: pow and powr, 18 list slices each, their own oracle rows
    m3x = []
    for ln in open("pw32_slice-oracle.out.txt").read().splitlines():
        m = PR.LINE.match(ln)
        if m and m.group(3) != "rand" and m.group(1) in ("pow", "powr"):
            m3x.append((m.group(1), float(m.group(7)), float(m.group(8))))
    ins36 = {fn: sum(len(pw32.build(fn, r).fragment().body) + 5
                     for r in ATTRS) for fn in ("pow", "powr")}
    print(f"\nM3X's 36 slices: {len(m3x)} oracle rows of pw32_slice-oracle."
          f"out.txt (pow, powr, 18 each); five-attribute instructions at "
          f"this tree: pow {ins36['pow']}, powr {ins36['powr']} "
          f"(COMPUTED from pw32.build)")
    print("\nTOTALS (COMPUTED; formulas shown). A slice on one tile = "
          "2^32 x (device `all` + O) us, O the oracle's us a lane in that "
          "process; the quad's four tiles run one process each, so a set of "
          "slices takes (sum of slices) / 4")
    res = {}
    for lab, k in (("one oracle call (x1)", 0), ("five oracle calls (x5)", 1)):
        h21 = sum(LANES * (s[2] * TILE_NS / 1000 + s[3 + k]) * 1e-6 / 3600
                  for s in slices)
        h36 = sum(LANES * (ins36[r[0]] * TILE_NS / 1000 + r[1 + k]) * 1e-6
                  / 3600 for r in m3x)
        res[k] = (h21, h36)
        print(f"  {lab}: 21 n-keyed slices: sum over (function, n) of 2^32 x "
              f"(device + O) = {h21:.1f} tile-hours, on the quad "
              f"{h21 / 4:.1f} h; 36 pow and powr slices (M3X's figures) "
              f"{h36:.1f} tile-hours, {h36 / 4:.1f} h; the 57 together "
              f"({h21:.1f} + {h36:.1f}) / 4 = {(h21 + h36) / 4:.1f} h")
    dev21 = sum(LANES * s[2] * TILE_NS / 1000 * 1e-6 / 3600 for s in slices)
    print(f"  the device alone, 21 slices: {dev21:.1f} tile-hours "
          f"({dev21 / 4:.1f} h on the quad); instructions per slice "
          f"(five attributes) from {min(s[2] for s in slices)} to "
          f"{max(s[2] for s in slices)}")
    print("  against: the plan's 200 and 440 h (57 slices), M3X's 133 to "
          "337 h (pow's counts for all 57; M3X's report); the 57 above use "
          "each slice's own counts and oracle rows")




# ---- the n-scan --------------------------------------------------------------

def _scan_xs(fn, count=3000):
    """x operands that could reach the main path at a large n: the 1 +- k
    ulp neighbours either side of +-1 (k to 300), +-2^E, +-(2^E - 1) and
    the tiny x of compound (1.m 2^-e for e from 20 to 149), and `count`
    uniformly random patterns."""
    one = sf.one_bits(fmt)
    rng = random.Random(20261124)
    xs = []
    for k in range(1, 301):
        for s in (0, fmt.sign_mask):
            xs += [(one + k) | s, (one - k) | s]
    for e in range(-149, 128):
        v = Fraction(2) ** e
        xs += [enc(fmt, v), enc(fmt, -v)]
    if fn == "compound":
        for e in range(20, 150):
            for f in (1, Fraction(3, 2), Fraction(199, 100)):
                v = Fraction(f) * Fraction(2) ** -e
                xs += [enc(fmt, v), enc(fmt, -v)]
    xs += [rng.getrandbits(32) for _ in range(count)]
    seen, out = set(), []
    for v in xs:
        if v not in seen and (v & ~fmt.sign_mask) < sf.inf_bits(fmt) and \
                (v & ~fmt.sign_mask):
            seen.add(v)
            out.append(v)
    return out


def mode_nscan():
    """For each function and n of the list: of the probe set, how many x are
    decided by the screens (the rounded product th0 at or past the overflow
    or underflow thresholds), by the exact rule (ex), by the rule beside 1
    (tinyt), or reach the in-lane test (the main path); the build's own
    probes, rne. Also, in exact arithmetic, the least |log2|x|| of an fp32
    x other than 1 and the largest |n| that leaves a lane unscreened."""
    p = fmt.prec
    one = sf.one_bits(fmt)
    lmin = min(abs(math.log2(float(dec(fmt, one + 1)))),
               abs(math.log2(float(dec(fmt, one - 1)))))
    tpos, tneg = fmt.emax + 2, p - fmt.emin + 2 + 0
    print(f"least |log2 |x|| over fp32 x other than +-1: {lmin:.4e} "
          f"(= 2^{math.log2(lmin):.2f}), at x = 1 - 2^-24 and 1 + 2^-23; "
          f"the screens answer t >= {tpos} (overflow) and t <= "
          f"{fmt.emin - p - 2} (underflow), so pown has an unscreened "
          f"lane with x != +-1 only for |n| below about "
          f"{min(tpos, -(fmt.emin - p - 2)) / lmin:.3e} "
          f"(2^{math.log2(min(tpos, -(fmt.emin - p - 2)) / lmin):.2f}); "
          f"COMPUTED")
    for fn in FNS:
        xs = _scan_xs(fn)
        print(f"\n{fn}: probe set of {len(xs)} x (neighbours of +-1 to 300 "
              f"ulp, +-2^E{', tiny x of compound' if fn == 'compound' else ''}"
              f", 3000 random patterns)")
        for n in N_LIST:
            b = _b(fn, RNE, n)
            c = Counter()
            for x in xs:
                bits, fl, pr = b.run(x, ("th0", "ex", "tinyt"))
                th0 = dec(fmt, pr["th0"]) if (pr["th0"] & ~fmt.sign_mask) \
                    < sf.inf_bits(fmt) else None
                if not RG.main_lane(fmt, fn, (x, n)):
                    c["special row"] += 1
                elif th0 is None or th0 >= tpos or th0 <= fmt.emin - p - 2:
                    c["screened"] += 1
                elif pr["ex"] & ~fmt.sign_mask:
                    c["exact rule"] += 1
                elif pr["tinyt"] & ~fmt.sign_mask:
                    c["beside 1 (tinyt)"] += 1
                else:
                    c["MAIN PATH"] += 1
            print(f"  n={nstr(n):12s} Y words {b.meta['ywords']}: "
                  + ", ".join(f"{k} {v}" for k, v in sorted(c.items())),
                  flush=True)




# ---- the tool's finding and the same question of pow and powr ----------------

def mode_finding():
    """TWBudget's (M3X's tool's) bound on compound n = 3, region int, 30
    lanes, seed 1, rne: 7468 Bv, from ONE lane; the terms that made it."""
    t0 = time.time()
    n = 3
    lanes = RG.region(fmt, "compound", "int", 30, 1)
    b = _b("compound", RNE, n)
    tw = PB.TWBudget(b).add(lanes)
    s = tw.summary()
    print(f"TWBudget (pw32_budget.py, M3X's tool, unchanged) on fp32 "
          f"compound n={n} region int, {len(lanes)} lanes, seed 1, rne: "
          f"{s['lanes']} lanes, M max {s['Mmax']:.6f} Bv, capacities "
          f"{s['S_cap']:.6f} Bv, BOUND {s['bound']:.6f} Bv")
    nb = NB.NBudget(b).add(lanes)
    sn = nb.summary()
    print(f"NBudget (pw32n_budget.py) on the same lanes: {sn['lanes']} "
          f"lanes measured, {nb.skipped_tiny} left out by the tinyt gate, "
          f"M max {sn['Mmax']:.6f}, capacities {sn['S_cap']:.6f}, BOUND "
          f"{sn['bound']:.6f} Bv")
    act = [i for i in range(len(tw.cap)) if tw.active[i]]
    top = sorted(act, key=lambda i: -tw.cap[i])[:4]
    body = tw.an.body
    print("the active instructions with the largest capacity (index, "
          "label, op, the capacity the tool sums, the largest observed "
          "contribution):")
    for i in top:
        best = None
        rounds_in = []
        for ln in lanes:
            if not tw.in_main(ln):
                continue
            one = PB.TWBudget(b).add([ln])
            if best is None or one.cap[i] > best[0]:
                best = (one.cap[i], ln)
            if one.active[i]:
                rounds_in.append(ln)
        print(f"  instruction {i}: label {b.label_of[i]}, op {body[i][0]}, "
              f"sources {body[i][2]}, capacity {tw.cap[i]:.6g} Bv, "
              f"observed {tw.obs[i]:.3g} Bv; the capacity comes from "
              f"x={best[1][0]:#010x} n={best[1][1]} (largest over the "
              f"lanes, {best[0]:.6g} Bv); the instruction rounds (is "
              f"active) in {len(rounds_in)} lane(s): "
              + ", ".join(f"x={ln[0]:#010x}" for ln in rounds_in[:4]))
    tl = [ln for ln in lanes if tw.in_main(ln) and
          M.run(b, "compound", ln, ("tinyt",))[2]["tinyt"] & ~fmt.sign_mask]
    for ln in tl:
        nbu = NB.NBudget(b)
        nbu._direct(ln)
        print(f"  the lane x={ln[0]:#010x} (x = {float(dec(fmt, ln[0])):.4e}"
              f"), n={n}, rne: |t0| < 2^-27 (tinyt set); its DIRECT error "
              f"(V against the true value) is {nbu.tiny_E[0]:.3e} Bv; "
              f"alone, TWBudget's own bound on it is "
              f"{PB.TWBudget(b).add([ln]).summary()['bound']:.3e} Bv")
    print(f"{time.time() - t0:.0f} s")


def mode_tinyq(args):
    """The same question of M3X's pow and powr: do M3X's regions draw lanes
    with |t0| < 2^-27, and does TWBudget's bound differ from NBudget's
    there? pw32.build, rne, 300 lanes a region, seed 1."""
    t0 = time.time()
    nl = int(args[0]) if args else 300
    for fn in ("pow", "powr"):
        b = pw32.build(fn, RNE)
        for name in ("wide", "small", "tinyy", "near1", "sub"):
            lanes = RG.region(fmt, fn, name, nl, 1)
            tw = PB.TWBudget(b).add(lanes)
            nb = NB.NBudget(b).add(lanes)
            st, sn = tw.summary(), nb.summary()
            print(f"fp32 {fn} region {name}: {len(lanes)} lanes; TWBudget "
                  f"measures {st['lanes']} (bound {st['bound']:.6f} + "
                  f"residual {st['resid']:.2e} Bv); NBudget measures "
                  f"{sn['lanes']} and leaves out {nb.skipped_tiny} by the "
                  f"tinyt gate (bound {sn['bound']:.6f} + residual "
                  f"{sn['resid']:.2e} Bv)"
                  + (f"; the tinyt lanes' direct error, largest "
                     f"{max(nb.tiny_E):.3e} Bv" if nb.tiny_E else ""),
                  flush=True)
    print(f"{time.time() - t0:.0f} s")




# ---- plants the first run left for a second mode, and the control shown red ---

def mode_plants_extra():
    t0 = time.time()
    print("n_word3_dropped where the third word of n matters: compound at "
          "n = 2^62 + 2^37 + 1, whose x are tiny (cint region) so that "
          "t = n log2(1 + x) is in range; the pools of the first plants run "
          "(pw32n_plants.out.txt) did not see it, the budget does")
    n3 = 2 ** 62 + 2 ** 37 + 1
    for p_ in (None, "n_word3_dropped"):
        tot, ln, em = _bound_tot("compound", n3, f"cint{n3}", 100, p_)
        print(f"  bound mode, fp32 compound n={nstr(n3)} region cint{n3}, "
              f"100 lanes, seed 1, rne, plant {p_}: bound + residual "
              f"{tot:.6g} Bv over {ln} lanes, measured worst {em:.6g} Bv -> "
              f"{_verdict(tot >= 1, 'over 1 Bv', 'green (under 1)')}",
              flush=True)
    print("n_word3_dropped on pown at n = 2^62 + 2^37 + 1 (region "
          f"int{n3}): every lane but x = +-1 is screened, so there is "
          "nothing to measure")
    b = _b("pown", RNE, n3, plant="n_word3_dropped")
    lanes = rg_region("pown", f"int{n3}", 100, 1)
    bud = NB.NBudget(b).add(lanes)
    s = bud.summary()
    print(f"  bound mode, fp32 pown n={nstr(n3)} region int{n3}, plant "
          f"n_word3_dropped: {s['lanes']} measured lanes of {len(lanes)} -> "
          + ("NOT MEASURED (no lane: the plant is not red here, and says so)"
             if s["lanes"] == 0 else "measured"), flush=True)
    print("\ncontrol shown red before it is relied on green (the brief): "
          "the fp64 pown region int control with 119 lanes, not 120, against "
          "the same reference file")
    lanes = RG.region(FP64, "pown", "int", 119, 1)
    b = M.build("pown", FP64, RNE, n=3)
    s = NB.report(b, lanes, "int", time.time())
    ref = open("budget.fp64-pown-int.out.txt").read().splitlines()
    want = [ln for ln in ref if "M max" in ln][0].strip()
    got = (f"M max {s['Mmax']:.6f} Bv; capacities {s['S_cap']:.6f} Bv; "
           f"BOUND {s['bound']:.6f} Bv (2^{lg(s['bound']):.2f})")
    print(f"  reference: {want}\n  this tool: {got}\n  -> "
          + ("RED: the control does not reproduce a doctored lane count "
             "(it can fail)" if got != want else
             "GREEN on 119 lanes: the control cannot tell 119 from 120"))
    print(f"{time.time() - t0:.0f} s")




def mode_control_red():
    """The control shown red: the fp64 pown region int control on 120 lanes
    of seed 2 (not seed 1) against the same reference file; plants-extra's
    119-lane doctoring was GREEN (the 120th lane moves no figure), so the
    control's sensitivity is to which lanes, not to one lane."""
    lanes = RG.region(FP64, "pown", "int", 120, 2)
    b = M.build("pown", FP64, RNE, n=3)
    s = NB.report(b, lanes, "int", time.time())
    ref = open("budget.fp64-pown-int.out.txt").read().splitlines()
    want = [ln for ln in ref if "M max" in ln][0].strip()
    got = (f"M max {s['Mmax']:.6f} Bv; capacities {s['S_cap']:.6f} Bv; "
           f"BOUND {s['bound']:.6f} Bv (2^{lg(s['bound']):.2f})")
    print(f"  reference: {want}")
    print(f"  this tool: {got}")
    print("  -> " + ("RED: the control does not reproduce on other lanes "
                     "(seed 2)" if got != want else
                     "GREEN on seed 2: the control cannot fail"))


def main():
    mode, args = sys.argv[1], sys.argv[2:]
    if mode == "costs":
        mode_costs()
    elif mode == "live":
        mode_live()
    elif mode == "bound":
        mode_bound(args)
    elif mode == "pools":
        mode_pools(args)
    elif mode == "rate":
        mode_rate(args)
    elif mode == "plants":
        mode_plants()
    elif mode == "slice":
        mode_slice()
    elif mode == "nscan":
        mode_nscan()
    elif mode == "finding":
        mode_finding()
    elif mode == "tinyq":
        mode_tinyq(args)
    elif mode == "plants-extra":
        mode_plants_extra()
    elif mode == "control-red":
        mode_control_red()
    elif mode == "control":
        if not mode_control():
            raise SystemExit(1)
    else:
        raise SystemExit(f"unknown mode {mode!r}")


if __name__ == "__main__":
    main()
