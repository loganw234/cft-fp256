# M3 model: the first-order budget of pown, rootn and compound at fp32's triple
# word (parcel M3XN). pw32_budget.TWBudget (M3X's, imported and never edited:
# TrigAnalyzer cannot run a one-input n-keyed build seeded from V0, V1, V2 and
# InvAnalyzer cannot seed three words, so M3X subclassed the second) runs the
# n-keyed builds unchanged: their lane is x alone (m3pow.lane_of) and
# true_value is keyed by n. What this file adds, and why:
#
#   NBudget.in_main  also leaves out the lanes the in-lane test does not
#   answer: |t0| below 2^-(p+3) (the build's `tinyt`, which clears the mark
#   and lets the rule beside 1 answer). TWBudget keeps them, and a lane that
#   small makes instructions round that no larger lane rounds (a word of the
#   logarithm in the subnormals), whose capacities, taken at the worst over
#   the other lanes (the sum of the capacities of every instruction that
#   rounds in any lane), made compound's bound 7468 Bv at n = 3 with every
#   lane's own worst 0.0065 Bv (pw32n_budget's own measurement, the ledger).
#   The lanes left out are COUNTED and printed (skipped_tiny).
#
#   python pw32n_budget.py FN REGION N [seed] [B1 exp] [B2 exp] [plant] [rnd]

import sys
import time
from fractions import Fraction

from m3core import RNE, sf, dec, lg, FP32
import m3pow as M
import regions as RG
import pw32_budget as PB
import pw32n


class NBudget(PB.TWBudget):
    def __init__(self, build):
        super().__init__(build)
        self.skipped_tiny = 0

    def in_main(self, lane):
        if not super().in_main(lane):
            return False
        fmt, fn = self.b.fmt, self.b.meta["fn"]
        _b, _f, pr = M.run(self.b, fn, lane, ("tinyt",))
        if pr["tinyt"] & ~fmt.sign_mask:
            self.skipped_tiny += 1
            return False
        return True


def report(bld, lanes, label, t0):
    """pw32_budget.report over NBudget; returns the summary with the lanes
    counted: summary()['lanes'] measured, ['skipped'] all left out,
    ['tiny'] of those the tinyt gate's."""
    fn = bld.meta["fn"]
    bud = NBudget(bld).add(lanes)
    s = bud.summary()
    s["tiny"] = bud.skipped_tiny
    print(f"{bld.fmt.name} {fn} n={bld.meta.get('n')} region {label}: "
          f"{s['lanes']} measured lanes of {len(lanes)} (left out: "
          f"{s['skipped']}, of them {bud.skipped_tiny} by the tinyt gate), "
          f"Y words {bld.meta.get('ywords', 'n/a')}, G {bld.meta['G']}, GL "
          f"{bld.meta['GL']}, B1 "
          f"2^{lg(bld.meta['B1']) if bld.meta['B1'] else '-inf'}, B2 "
          f"2^{lg(bld.meta['B2']) if bld.meta['B2'] else '-inf'}")
    if s["lanes"] == 0:
        print("  NOT MEASURED (0 measured lanes in this region: no bound, "
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
    fn, region, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    seed = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    e1 = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5] != "-" else None
    e2 = int(sys.argv[6]) if len(sys.argv) > 6 and sys.argv[6] != "-" else None
    plant = sys.argv[7] if len(sys.argv) > 7 and sys.argv[7] != "-" else None
    t0 = time.time()
    nn = RG.region_n(fn, region)
    lanes = RG.region(FP32, fn, region, n, seed)
    bld = pw32n.build(fn, RNE, nn, plant=plant,
                      B1=None if e1 is None else Fraction(1, 2 ** e1),
                      B2=None if e2 is None else Fraction(1, 2 ** e2))
    report(bld, lanes, region, t0)


if __name__ == "__main__":
    main()
