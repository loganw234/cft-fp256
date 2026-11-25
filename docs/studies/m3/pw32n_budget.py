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
    """TWBudget with one predicate added to in_main. THE PREDICATE, exactly:
    a lane is left out when the build's probe `tinyt` is nonzero, `tinyt`
    being b.icmplt(|t0|, TINYT) with t0 the first word of t = Y L and TINYT
    the encoding of 2^-(p+3) = 2^-27: an integer compare of |t0|'s encoding
    against 2^-27's, so |t0| < 2^-27 (t0 = 0 included). Those lanes are
    answered by the rule beside 1 (mark cleared, the side of 1 from the
    operands' signs), not by the in-lane test, so Bv plays no part in their
    answer. WHY the first-order model does not hold there: t is that small
    only where L or Y is, and then the logarithm's words (a word of L is
    2^-24 of the one above it, F's lowest 2^-72 of F) fall into the
    subnormals, 2^-126 to 2^-149, where a rounding is an ABSOLUTE error
    (at most 2^-150) and not a relative one, so the capacity the tool takes
    for an instruction (a half ulp of its value) is not that error, and the
    tool's sum over every instruction that rounds in any lane, each at its
    worst capacity over all lanes, is dominated by instructions that round
    only in these lanes. This is a LIMIT of the budget, not coverage: the
    budget says nothing about the left-out lanes. What is printed for them
    instead is each one's DIRECT error (V against the true value, in Bv; the
    measured worst of the set, a sample, not a bound), and what covers them
    is the pools and regions on seq.py (their answers are the rule's) and
    the card's sweeps to come."""

    def __init__(self, build):
        super().__init__(build)
        self.skipped_tiny = 0
        self.tiny_E = []                 # direct error of each, in Bv
        self.tiny_worst = None

    def in_main(self, lane):
        if not super().in_main(lane):
            return False
        fmt, fn = self.b.fmt, self.b.meta["fn"]
        _b, _f, pr = M.run(self.b, fn, lane, ("tinyt",))
        if pr["tinyt"] & ~fmt.sign_mask:
            self.skipped_tiny += 1
            self._direct(lane)
            return False
        return True

    def _direct(self, lane):
        """The left-out lane's own error: |V - T| / Bv, V the model's three
        words summed, T the true value scaled by 2^-k, as add() has it."""
        import mpmath
        from m3core import true_value
        an, fmt, fn = self.an, self.b.fmt, self.b.meta["fn"]
        L = an.analyze(M.lane_of(fn, lane))
        k = (L.vals[self.b.probes["Ek"][1]] - fmt.bias - self.b.meta["OFF"])
        with mpmath.workprec(an.prec):
            T = true_value(fmt, fn, lane, an.prec) * mpmath.mpf(2) ** (-k)
            E = float(abs((L.V - T) / L.Bv)) if L.Bv else float("inf")
        self.tiny_E.append(E)
        if self.tiny_worst is None or E >= max(self.tiny_E):
            self.tiny_worst = lane


def report(bld, lanes, label, t0):
    """pw32_budget.report over NBudget; returns the summary with the lanes
    counted: summary()['lanes'] measured, ['skipped'] all left out,
    ['tiny'] of those the tinyt gate's."""
    fn = bld.meta["fn"]
    bud = NBudget(bld).add(lanes)
    s = bud.summary()
    s["tiny"] = bud.skipped_tiny
    s["tiny_E"] = max(bud.tiny_E) if bud.tiny_E else None
    print(f"{bld.fmt.name} {fn} n={bld.meta.get('n')} region {label}: "
          f"{s['lanes']} measured lanes of {len(lanes)} (left out: "
          f"{s['skipped']}, of them {bud.skipped_tiny} by the tinyt gate), "
          f"Y words {bld.meta.get('ywords', 'n/a')}, G {bld.meta['G']}, GL "
          f"{bld.meta['GL']}, B1 "
          f"2^{lg(bld.meta['B1']) if bld.meta['B1'] else '-inf'}, B2 "
          f"2^{lg(bld.meta['B2']) if bld.meta['B2'] else '-inf'}")
    if bud.tiny_E:
        print(f"  left out by the tinyt gate: {bud.skipped_tiny} lanes "
              f"(|t0| < 2^-27; NOT bounded by this budget); their DIRECT "
              f"error, V against the true value in Bv: largest "
              f"{max(bud.tiny_E):.3e} at "
              f"{RG.show(bud.tiny_worst, fn)}; measured, a sample, not a "
              f"bound")
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
