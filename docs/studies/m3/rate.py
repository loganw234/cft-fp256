# M3 model: the mark-rate law (scratch; the study's 3.4). The bound is
# inflated 2^shift times (G' = G - shift) so that marks are common, and the
# marks on N placed main-path lanes are counted against the law's
# prediction, lane by lane: the interval [V - Bv, V + Bv] holds a rounding
# boundary with probability 2 Bv / s, s the boundaries' spacing at R: ulp(R)
# under rtz, rdn and rup (the grid points); ulp(R)/2 under rne and rmm (the
# midpoints, and the grid points the "may be exact" test adds). At the true
# G that is a rate of about 2^-(G-1) sig(V) a call under the directed
# attributes and twice that under rne and rmm, sig(V) the significand of V
# in [1, 2); at fp64 G is G(t) of 2.2.
#
#   python rate.py FMT FN REGION N [Gprime] [seed]

import sys
import math
import time

from m3core import FORMATS, ATTRS, AN, dec, sf
import m3pow as M
import regions as RG


def main():
    fmt = FORMATS[sys.argv[1]]
    fn, region, n = sys.argv[2], sys.argv[3], int(sys.argv[4])
    Gp = int(sys.argv[5]) if len(sys.argv) > 5 else 8
    seed = int(sys.argv[6]) if len(sys.argv) > 6 else 3
    t0 = time.time()
    G = M.GUARD[fmt.name]
    shift = G - Gp
    lanes = RG.region(fmt, fn, region, n, seed)
    nint = RG.region_n(fn, region, seed)
    print(f"{fmt.name} {fn} region {region}: {len(lanes)} lanes, seed {seed},"
          f" G' = {Gp} (the bound 2^{shift} times its own)")
    for rnd in ATTRS:
        b = M.build(fn, fmt, rnd, n=nint, shift=shift)
        obs = 0
        exp = 0.0
        used = 0
        for lane in lanes:
            bits, fl, pr = M.run(b, fn, lane, ("R", "Bv", "ex", "tinyt",
                                               "th0"))
            if pr["ex"] & ~fmt.sign_mask or pr["tinyt"] & ~fmt.sign_mask:
                continue
            Rq = abs(float(dec(fmt, pr["R"]))) if (pr["R"] & ~fmt.sign_mask) \
                < sf.inf_bits(fmt) else None
            Bvq = float(dec(fmt, pr["Bv"]))
            if not Rq or not Bvq:
                continue
            e = math.floor(math.log2(Rq))
            ulp = 2.0 ** (e - fmt.prec + 1)
            s = ulp / 2 if rnd in (M.RNE, M.RMM) else ulp
            exp += min(1.0, 2 * Bvq / s)
            obs += bool(fl & M.ml.MARK)
            used += 1
        z = (obs - exp) / math.sqrt(exp) if exp > 0 else float("nan")
        print(f"  {AN[rnd]}: {used} lanes, marked {obs}, the law predicts "
              f"{exp:.1f}, z = {z:+.2f}", flush=True)
    print(f"  {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
