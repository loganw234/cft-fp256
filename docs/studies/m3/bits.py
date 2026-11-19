# M3 model: how many bits the logarithm needs past p + G, per format (the
# study's 2.2), and what M1's double word holds (COMPUTED, exact rationals).
#
# The main path answers t in (emin - p - 2, emax + 2): the screens take the
# rest. An absolute error d in t moves 2^t by a relative ln2 d, and t = Y L,
# so L's relative error eps gives ln2 |t| eps. For the bound 2^-(p+G) the
# logarithm therefore needs about p + G + log2(T_f) bits, T_f the largest |t|.
#
#   python bits.py

import math

from m3core import FORMATS
import m3pow as M
from m3core import ml


def main():
    for name, fmt in FORMATS.items():
        p = fmt.prec
        G = M.GUARD[name]
        Tf = M.t_reach(fmt)
        need = p + G + math.log2(Tf)
        if name == "fp32":
            print(f"{name}: p {p}, G {G}, T_f {Tf} (log2 {math.log2(Tf):.2f}),"
                  f" extra {M.extra_bits(fmt)}; the logarithm needs p + G + "
                  f"log2 T_f = {need:.2f} bits; the double word holds "
                  f"{2 * p}, the triple word {3 * p}: the triple word, with "
                  f"no room for its own roundings (not modelled here)")
            continue
        dw = 2 * p
        G_, GL, GE, B1 = M.plan(fmt)
        K, D = ml.plan_log(fmt, GL)
        # the largest GL M1's plan_log accepts (its double-word floor 12 u^2),
        # searched up to G + 120
        gmax = G
        while gmax < G + 120:
            try:
                ml.plan_log(fmt, gmax + 1)
                gmax += 1
            except ValueError:
                break
        reach = (f"{gmax}" if gmax < G + 120 else f"past {gmax} (the search's "
                 f"end)")
        print(f"{name}: p {p}, G {G}, T_f {Tf} (log2 {math.log2(Tf):.2f}), "
              f"extra {M.extra_bits(fmt)}; the logarithm needs p + G + "
              f"log2 T_f = {need:.2f} bits; the double word holds {dw}, "
              f"M1's plan_log reaches GL {reach}; "
              f"planned GL {GL} (K {K}, D {D}), GE {GE}, B1 "
              f"{'0' if not B1 else '2^%.0f' % math.log2(B1)}")
        if B1:
            for t in (1, 8, 64, 1024, Tf):
                w = 2.0 ** -(p + G) + t * float(B1)
                print(f"    |t| = {t}: Bv/|V| = 2^{math.log2(w):.2f}, "
                      f"G at that |t| {-(math.log2(w)) - p:.2f}")


if __name__ == "__main__":
    main()
