# M3 model: the first-order budget of pow and powr at fp32's TRIPLE word
# (parcel M3X). The tree's tools, imported and never edited:
#
#   mathlib_trig_budget.TrigAnalyzer  takes V as V0, V1, V2 but runs one
#                                     input (ml._values without the inputs)
#   mathlib_inv_budget.InvAnalyzer    runs the inputs of a two-input build
#                                     (pow's x and y) but seeds V as Vh, Vl
#                                     and refuses a family that is not the
#                                     double word
#
# so neither runs pow at fp32 by itself, and this subclasses InvAnalyzer the
# way budget.PowAnalyzer does for the double word (its fn and family set for
# the length of __init__, the fixed grid's phase read as "final") and
# re-states its `analyze` with V's words taken from `self.seeds` as
# TrigAnalyzer takes them. The sweep, the data and the negations are
# InvAnalyzer's, unchanged: the body of analyze below is InvAnalyzer's with
# the three seeds.
#
# The control, `control`: the model's own tool (budget.PowBudget) on the
# model's fp64 pow, region edge, 120 lanes, seed 1, printing the digits of
# budget.fp64-pow-edge.out.txt; it is a run of that tool, not of this one.
#
#   python pw32_budget.py FN REGION N [seed] [B1 exponent] [B2 exponent]
#                         [plant]   (rne)

import sys
import time

import mpmath

from m3core import RNE, true_value, dec, lg, FP32, ml, sf
import m3pow as M
import regions as RG
import mathlib_budget as B
import mathlib_inv_budget as IB
import pw32


class TWAnalyzer(IB.InvAnalyzer):
    def __init__(self, build):
        fn, phases = build.meta["fn"], build.phase_of
        fam = build.meta["family"]
        triple = "V0" in build.probes
        had_vl = "Vl" in build.probes
        build.meta["fn"] = "atan2"
        build.meta["family"] = "double word"
        build.phase_of = ["final" if ph == "fixed-grid" else ph
                          for ph in phases]
        if triple and not had_vl:
            build.probes["Vl"] = build.probes["V1"]
        try:
            super().__init__(build)
        finally:
            build.meta["fn"], build.meta["family"] = fn, fam
            build.phase_of = phases
            if triple and not had_vl:
                del build.probes["Vl"]
        self.phases = phases
        # V's words: V0, V1, V2 (pw32's), or Vh and Vl (the model's double
        # word, which the control runs this tool on)
        self.seeds = ("V0", "V1", "V2") if triple else ("Vh", "Vl")
        self.probes = build.probes

    def analyze(self, xa):
        """InvAnalyzer.analyze with V = V0 + V1 + V2."""
        fmt, body = self.fmt, self.body
        vals = ml._values(fmt, body, self.words, xa, None, self.inputs)
        sm = fmt.sign_mask
        with mpmath.workprec(self.prec):
            def num(bits):
                try:
                    return B.to_mp(ml._dec(fmt, bits))
                except ValueError:
                    return None
            n = len(body)
            ex, delta = [None] * n, [None] * n
            sel_take, negsign = {}, {}

            def exv(s):
                return ex[s[1]] if s[0] == "v" else \
                    num(self._bits(s, vals, xa))

            def ov(s):
                return num(self._bits(s, vals, xa))
            for i, (op, _r, srcs) in enumerate(body):
                if i in self.negs and i not in self.dfeed:
                    c, s = self.negs[i]
                    flag = self._bits(s, vals, xa) == sm
                    negsign[i] = (c, flag)
                    e = exv(c)
                    ex[i] = None if e is None else (-e if flag else e)
                    continue
                if op in IB.CONT and i not in self.dfeed:
                    a = [exv(s) for s in srcs]
                    oa = [ov(s) for s in srcs]
                    if any(v is None for v in a) or any(v is None for v in oa):
                        ex[i] = num(vals[i])
                        continue
                    if op == sf.OP_ADD:
                        e_x, o_x = a[0] + a[1], oa[0] + oa[1]
                    elif op == sf.OP_SUB:
                        e_x, o_x = a[0] - a[1], oa[0] - oa[1]
                    elif op == sf.OP_MUL:
                        e_x, o_x = a[0] * a[1], oa[0] * oa[1]
                    elif op == sf.OP_FMA:
                        e_x, o_x = (a[0] * a[1] + a[2],
                                    oa[0] * oa[1] + oa[2])
                    elif op == sf.OP_NEG:
                        e_x, o_x = -a[0], -oa[0]
                    else:
                        e_x, o_x = abs(a[0]), abs(oa[0])
                    ex[i] = e_x
                    vi = num(vals[i])
                    delta[i] = None if vi is None else vi - o_x
                elif op == sf.OP_SELECT and i not in self.dfeed:
                    take = (self._bits(srcs[2], vals, xa) & ~sm) != 0
                    sel_take[i] = take
                    ex[i] = exv(srcs[0] if take else srcs[1])
                else:
                    ex[i] = num(vals[i])
            adj = [mpmath.mpf(0)] * n
            for nm in self.seeds:                       # V's three words
                adj[self.probes[nm][1]] += 1
            for i in range(n - 1, -1, -1):
                g = adj[i]
                if g == 0:
                    continue
                op, _r, srcs = body[i]
                if i in negsign:
                    other, neg = negsign[i]
                    self._acc(adj, other, -g if neg else g)
                    continue
                if i in self.dfeed:
                    continue
                if op in IB.CONT:
                    if op == sf.OP_ADD:
                        self._acc(adj, srcs[0], g)
                        self._acc(adj, srcs[1], g)
                    elif op == sf.OP_SUB:
                        self._acc(adj, srcs[0], g)
                        self._acc(adj, srcs[1], -g)
                    elif op == sf.OP_MUL:
                        self._acc(adj, srcs[0], g * (exv(srcs[1]) or 0))
                        self._acc(adj, srcs[1], g * (exv(srcs[0]) or 0))
                    elif op == sf.OP_FMA:
                        self._acc(adj, srcs[0], g * (exv(srcs[1]) or 0))
                        self._acc(adj, srcs[1], g * (exv(srcs[0]) or 0))
                        self._acc(adj, srcs[2], g)
                    elif op == sf.OP_NEG:
                        self._acc(adj, srcs[0], -g)
                    else:
                        v = exv(srcs[0]) or 0
                        self._acc(adj, srcs[0], g if v >= 0 else -g)
                elif op == sf.OP_SELECT and i in sel_take:
                    self._acc(adj, srcs[0] if sel_take[i] else srcs[1], g)
            L = B.Lane()
            L.xa, L.vals, L.ex, L.delta, L.adj = xa, vals, ex, delta, adj
            L.V = sum(num(vals[self.probes[nm][1]]) for nm in self.seeds)
            L.Vex = sum(ex[self.probes[nm][1]] for nm in self.seeds)
            L.Bv = abs(num(vals[self.probes["Bv"][1]]))
            return L


class TWBudget:
    """budget.PowBudget over TWAnalyzer."""

    def __init__(self, build):
        self.b = build
        self.an = TWAnalyzer(build)
        n = len(self.an.body)
        self.obs, self.cap = [0.0] * n, [0.0] * n
        self.active = [False] * n
        self.Mmax = self.Emax = self.resid = 0.0
        self.lanes = self.skipped = 0
        self.worst = None
        self.tmax = 0.0

    def in_main(self, lane):
        fn, fmt = self.b.meta["fn"], self.b.fmt
        _bits, _fl, pr = M.run(self.b, fn, lane, ("th0", "ex"))
        th0 = pr["th0"]
        if (th0 & ~fmt.sign_mask) >= sf.inf_bits(fmt):
            return False
        t = dec(fmt, th0)
        if not (fmt.emin - fmt.prec - 2 < t < fmt.emax + 2):
            return False
        if pr["ex"] & ~fmt.sign_mask:
            return False
        return RG.main_lane(fmt, fn, lane)

    def add(self, lanes):
        an, fmt, fn = self.an, self.b.fmt, self.b.meta["fn"]
        for lane in lanes:
            if not self.in_main(lane):
                self.skipped += 1
                continue
            L = an.analyze(M.lane_of(fn, lane))
            k = (L.vals[self.b.probes["Ek"][1]] - fmt.bias
                 - self.b.meta["OFF"])
            self.tmax = max(self.tmax, abs(k))
            with mpmath.workprec(an.prec):
                T = true_value(fmt, fn, lane, an.prec) * mpmath.mpf(2) ** (-k)
                Bv = L.Bv
                E = float(abs((L.V - T) / Bv))
                self.Mmax = max(self.Mmax, float(abs((L.Vex - T) / Bv)))
                if E > self.Emax:
                    self.Emax, self.worst = E, lane
                first = L.Vex - T
                for i, contrib, capi, d in an.contributions(L):
                    if d != 0:
                        self.active[i] = True
                    first += contrib
                    self.obs[i] = max(self.obs[i], abs(float(contrib / Bv)))
                    self.cap[i] = max(self.cap[i], float(capi / Bv))
                self.resid = max(self.resid,
                                 abs(float((L.V - T - first) / Bv)))
            self.lanes += 1
        return self

    def summary(self):
        act = [i for i, a in enumerate(self.active) if a]
        s_cap = sum(self.cap[i] for i in act)
        by = {}
        for i in act:
            lab = self.b.label_of[i]
            a, c = by.get(lab, (0.0, 0.0))
            by[lab] = (a + self.obs[i], c + self.cap[i])
        return {"lanes": self.lanes, "skipped": self.skipped,
                "rounding": len(act), "Emax": self.Emax, "Mmax": self.Mmax,
                "S_cap": s_cap, "bound": self.Mmax + s_cap,
                "resid": self.resid, "by": by}


def report(bld, lanes, label, t0):
    """Print one region's budget; return its summary."""
    from fractions import Fraction  # noqa: F401
    fn = bld.meta["fn"]
    bud = TWBudget(bld).add(lanes)
    s = bud.summary()
    print(f"{bld.fmt.name} {fn} region {label}: {s['lanes']} main-path lanes "
          f"of {len(lanes)}, G {bld.meta['G']}, GL {bld.meta['GL']}, B1 "
          f"2^{lg(bld.meta['B1']) if bld.meta['B1'] else '-inf'}, B2 "
          f"2^{lg(bld.meta['B2']) if bld.meta['B2'] else '-inf'}")
    if s["lanes"] == 0:
        print("  NOT MEASURED (0 main-path lanes in this region: no bound, "
              "no margin)")
        print(f"  {time.time() - t0:.0f} s", flush=True)
        return s
    print(f"  rounding instructions active {s['rounding']}")
    print(f"  M max {s['Mmax']:.6f} Bv; capacities {s['S_cap']:.6f} Bv; "
          f"BOUND {s['bound']:.6f} Bv (2^{lg(s['bound']):.2f})")
    print(f"  measured worst {s['Emax']:.6f} Bv at "
          f"{RG.show(bud.worst, fn) if bud.worst else '-'}")
    print(f"  residual (second order, measured) {s['resid']:.3e} Bv; "
          f"bound + residual {s['bound'] + s['resid']:.6f} Bv")
    for lab, (o, c) in sorted(s["by"].items(), key=lambda kv: -kv[1][1])[:8]:
        print(f"    {lab:12s} capacity {c:.6f}  observed {o:.6f}")
    print(f"  {time.time() - t0:.0f} s", flush=True)
    return s


def main():
    from fractions import Fraction
    fn, region, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    e1 = int(sys.argv[5]) if len(sys.argv) > 5 else None
    e2 = int(sys.argv[6]) if len(sys.argv) > 6 else None
    plant = sys.argv[7] if len(sys.argv) > 7 else None
    t0 = time.time()
    lanes = RG.region(FP32, fn, region, n, seed)
    bld = pw32.build(fn, RNE, plant=plant,
                     B1=None if e1 is None else Fraction(1, 2 ** e1),
                     B2=None if e2 is None else Fraction(1, 2 ** e2))
    if plant:
        print(f"PLANT {plant}: {pw32.PLANTS[plant]}")
    report(bld, lanes, region, t0)


if __name__ == "__main__":
    main()
