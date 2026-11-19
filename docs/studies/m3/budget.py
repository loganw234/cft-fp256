# M3 model: the first-order error budget of a region (scratch; the study's
# 3.2). Verifier-VM1b's method as the tree ports it: python/tests/
# mathlib_inv_budget.py's InvAnalyzer (M4G4's port of M4's model), imported
# and never edited, on this model's Build. Its fn check names the four
# inverse functions, so the analyzer is made with the build's fn set to
# atan2 for the length of its __init__ and set back; nothing else of it is
# inverse-specific (a lane is the build's inputs in Build.inputs' order; a
# SELECT between the words 0 and SIGN is a sign carrier; an IXOR of a value
# with one is a negation; the sources of integer instructions, compares and
# SELECT conditions before V are data; V = Vh + Vl, Bv from the probe).
#
# For one lane: the original run, a twin in exact arithmetic with the data
# frozen, each rounding's error delta_i and s_i = dV/dv_i by the reverse
# sweep from V. Over a region: M's largest value (the method's own error:
# the polynomials' truncation, the constants, the seeds' cells) plus each
# rounding's largest capacity |s_i| ulp(v_i)/2, in units of each lane's Bv.
# The RESIDUAL, what first order leaves out, is measured beside it.
#
#   python budget.py FMT FN REGION N [seed]

import sys
import time

import mpmath

from m3core import FORMATS, RNE, true_value, to_mp, dec, lg
import m3pow as M
import regions as RG
import mathlib_budget as B
import mathlib_inv_budget as IB


class PowAnalyzer(IB.InvAnalyzer):
    """The fixed grid reads V_l with a CMPEQ (its round-to-odd); the
    inverse functions have no fixed grid, so their tool counts the phase
    "fixed-grid" as before V and freezes V_l as data, which stops the sweep
    at V_l (the first run's tell: a method error of 10^12 Bv while the
    measured error was 0.05 Bv; the study's 3.6). The fixed grid is after
    V, as the six's tool has it: its phase is read as "final" here."""

    def __init__(self, build):
        fn, phases = build.meta["fn"], build.phase_of
        build.meta["fn"] = "atan2"
        build.phase_of = ["final" if ph == "fixed-grid" else ph
                          for ph in phases]
        try:
            super().__init__(build)
        finally:
            build.meta["fn"] = fn
            build.phase_of = phases
        self.phases = phases


class PowBudget:
    def __init__(self, build):
        self.b = build
        self.an = PowAnalyzer(build)
        n = len(self.an.body)
        self.obs, self.cap = [0.0] * n, [0.0] * n
        self.active = [False] * n
        self.Mmax = self.Emax = self.resid = 0.0
        self.lanes = self.skipped = 0
        self.worst = None
        self.tmax = 0.0

    def in_main(self, lane):
        fn, fmt = self.b.meta["fn"], self.b.fmt
        _bits, _fl, pr = M.run(self.b, fn, lane, ("th0", "ex", "Vh"))
        th0 = pr["th0"]
        if (th0 & ~fmt.sign_mask) >= sf_inf(fmt):
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
            # V lives in the scaled domain: f 2^-k, k from the probe Ek
            k = (L.vals[self.b.probes["Ek"][1]] - fmt.bias
                 - self.b.meta["OFF"])
            self.tmax = max(self.tmax, abs(k))
            with mpmath.workprec(an.prec):
                T = true_value(fmt, fn, lane, an.prec) * \
                    mpmath.mpf(2) ** (-k)
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


def sf_inf(fmt):
    return M.sf.inf_bits(fmt)


def main():
    fmt = FORMATS[sys.argv[1]]
    fn, region, n = sys.argv[2], sys.argv[3], int(sys.argv[4])
    seed = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    plant = sys.argv[6] if len(sys.argv) > 6 else None
    t0 = time.time()
    lanes = RG.region(fmt, fn, region, n, seed)
    nint = RG.region_n(fn, region, seed)
    bld = M.build(fn, fmt, RNE, n=nint, plant=plant)
    if plant:
        print(f"PLANT {plant}: {M.PLANTS[plant]}")
    bud = PowBudget(bld).add(lanes)
    s = bud.summary()
    print(f"{fmt.name} {fn} region {region}: {s['lanes']} main-path lanes "
          f"of {len(lanes)} (n = {nint}), seed {seed}, G {bld.meta['G']}, "
          f"GL {bld.meta['GL']}, GE {bld.meta['GE']}, B1 "
          f"2^{lg(bld.meta['B1']) if bld.meta['B1'] else '-inf'}")
    print(f"  rounding instructions active {s['rounding']}")
    print(f"  M max {s['Mmax']:.6f} Bv; capacities {s['S_cap']:.6f} Bv; "
          f"BOUND {s['bound']:.6f} Bv (2^{lg(s['bound']):.2f})")
    print(f"  measured worst {s['Emax']:.6f} Bv at "
          f"{RG.show(bud.worst, fn) if bud.worst else '-'}")
    print(f"  residual (second order, measured) {s['resid']:.3e} Bv; "
          f"bound + residual {s['bound'] + s['resid']:.6f} Bv")
    for lab, (o, c) in sorted(s["by"].items(), key=lambda kv: -kv[1][1]):
        print(f"    {lab:12s} capacity {c:.6f}  observed {o:.6f}")
    print(f"  {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
