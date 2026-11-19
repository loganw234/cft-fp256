# M3 model: the special rows, row by row, each against transcend.py at every
# attribute (scratch; the study's section 4).
#
#   python specials.py FMT [fn ...]
#
# Each row names the 9.2.1 entry (or transcend.py's rule) it holds and the
# lanes it is tried on; a row passes when every lane equals transcend.py in
# bits and flags UNMARKED, or is marked (the replay answers it: counted and
# printed, a special row should never mark).

import sys
import time

from m3core import FORMATS, ATTRS, AN, sf, val
import m3harness as H


def rows(fmt, fn):
    p, mw = fmt.prec, fmt.man_w
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    z, mz = sf.zero_bits(fmt), sf.zero_bits(fmt, 1)
    inf, minf = sf.inf_bits(fmt), sf.inf_bits(fmt, 1)
    qn, sn = sf.qnan_bits(fmt), sf.snan_bits(fmt)
    mx, mn = sf.max_normal_bits(fmt), sf.min_subnormal_bits(fmt)
    S = fmt.sign_mask
    v = lambda s, m, e: val(fmt, s, m, e)                   # noqa: E731
    fin = [v(0, 3, 0), v(1, 3, 0), v(0, 3, -2), v(1, 5, -3), mx, mx | S, mn,
           mn | S, v(0, 1, fmt.emin)]
    ally = [z, mz, inf, minf, qn, one, mone, v(0, 3, -1), v(1, 3, -1),
            v(0, 3, 0), v(1, 3, 0), mx, mx | S, mn, mn | S]
    # y's integrality and parity across MAGIC's band (below 2^(p-2)), the
    # band of halves (2^(p-2) to 2^(p-1)), the band of integers (to 2^p) and
    # past 2^p (the study's 2.5 and 3.6, item 5)
    oddy = [v(0, 3, 0), v(1, 3, 0), one, mone, v(0, (1 << p) - 1, 0),
            v(1, (1 << p) - 1, 0), v(0, (1 << (p - 2)) - 1, 0),
            v(0, (1 << (p - 2)) + 1, 0), v(1, (1 << (p - 2)) + 3, 0),
            v(0, (1 << (p - 1)) - 1, 0), v(1, (1 << (p - 1)) + 1, 0)]
    eveny = [v(0, 2, 0), v(1, 2, 0), v(0, 1, p), v(1, 1, p + 5), mx, mx | S,
             v(0, 1, p - 2), v(0, (1 << (p - 2)) + 2, 0),
             v(1, (1 << (p - 1)) - 2, 0), v(0, (1 << (p - 1)) + 2, 0)]
    noninty = [v(0, 1, -1), v(1, 3, -1), mn, v(0, (1 << p) - 1, -1),
               v(1, 1, -p), v(0, (1 << (p - 1)) + 1, -1),
               v(1, (1 << p) - 1, -1)]
    R = []
    if fn in ("pow", "powr"):
        R += [("y = +-0 (pow: 1, even x = NaN; powr: finite x > 0)",
               [(a, b) for a in fin + [z, mz, inf, minf, qn, one, mone]
                for b in (z, mz)]),
              ("x = +1 (pow: 1, even y = NaN; powr: finite y)",
               [(one, b) for b in ally]),
              ("x = -1 and y = +-inf", [(mone, inf), (mone, minf)]),
              ("a sNaN in either operand", [(sn, b) for b in (z, one, qn)] +
               [(a, sn) for a in (one, z, qn, mone)]),
              ("a qNaN in either, no row above", [(qn, b) for b in
                                                   (one, mone, inf, v(0, 3, 0))]
               + [(a, qn) for a in (mone, z, inf, v(0, 3, 0), v(1, 3, 0))]),
              ("x = +-0, y < 0 (odd, even, non-integer, -inf)",
               [(a, b) for a in (z, mz) for b in
                (mone, v(1, 3, 0), v(1, 2, 0), v(1, 3, -1), mx | S, minf)]),
              ("x = +-0, y > 0", [(a, b) for a in (z, mz) for b in
                                  (one, v(0, 3, 0), v(0, 2, 0), v(0, 3, -1),
                                   mx, inf, mn)]),
              ("x = +-inf", [(a, b) for a in (inf, minf) for b in
                             (one, mone, v(0, 3, 0), v(1, 3, 0), v(0, 2, 0),
                              v(1, 2, 0), v(0, 3, -1), v(1, 3, -1), inf,
                              minf, mn, mx)]),
              ("y = +-inf, |x| < 1 and > 1",
               [(a, b) for a in (v(0, 1, -1), v(1, 1, -1), v(0, 3, 0),
                                 v(1, 3, 0), mn, mx, one - 1, one + 1)
                for b in (inf, minf)]),
              ("x < 0 finite, y not an integer",
               [(a, b) for a in (mone, v(1, 3, 0), mx | S, mn | S)
                for b in noninty]),
              ("x < 0, y odd integer (sign kept), across y's bands",
               [(a, b) for a in (v(1, 3, 0), v(1, 5, -3), v(1, 1, -3),
                                 mone + 1, mone - 1)
                for b in oddy]),
              ("x < 0, y even integer, y past 2^p",
               [(a, b) for a in (v(1, 3, 0), v(1, 5, -3), mone + 1)
                for b in eveny]),
              ("y = 1: x itself (exact)", [(a, one) for a in fin]),
              ("subnormal operands",
               [(mn, v(0, 1, -1)), (mn, one + 1), (v(0, 3, fmt.emin - p), v(0, 1, -1)),
                (v(0, 1, -2), v(0, 1, 1)), (mn, mone), (v(0, 3, -p), v(0, 3, 0))]),
              ("overflowing and underflowing results",
               [(v(0, 1, 1), v(0, fmt.emax, 0)), (v(0, 1, 1), v(0, fmt.emax + 1, 0)),
                (v(0, 1, 1), v(1, -(fmt.emin - mw - 1), 0)),
                (v(0, 1, 1), v(1, -(fmt.emin - mw), 0)),
                (v(0, 1, 1), v(1, -(fmt.emin - mw - 2), 0)),
                (v(0, 10, 0), v(0, 400, 0)), (v(0, 10, 0), v(1, 400, 0)),
                (v(0, 3, 0), mx), (v(0, 3, -2), mx), (mx, v(0, 3, -1)),
                (mx, v(0, 2, 0)), (mn, v(0, 2, 0)), (mn, v(1, 1, -1))])]
        if fn == "powr":
            R += [("powr: x < 0 (every y, qNaN included)",
                   [(a, b) for a in (mone, v(1, 3, 0), minf, mn | S)
                    for b in (z, one, qn, inf, v(0, 3, -1))]),
                  ("powr: +-0 to +-0, +inf to +-0, +1 to +-inf",
                   [(a, b) for a in (z, mz) for b in (z, mz)] +
                   [(inf, z), (inf, mz), (one, inf), (one, minf)])]
        return R
    ns = [0, 1, -1, 2, -2, 3, -3, 4, 17, -17, (1 << 63) - 1, -(1 << 63),
          (1 << 62), -(1 << 62) - 1]
    xs = [z, mz, inf, minf, qn, sn, one, mone, one + 1, one - 1, mone + 1,
          mone - 1, mn, mn | S, mx, mx | S, v(0, 3, 0), v(1, 3, 0),
          v(0, 1, -1), v(1, 1, -1), v(0, 1, -p - 3), v(1, 1, -p - 3)]
    R.append((f"{fn}: x specials and neighbours of +-1, 0 and the range "
              f"against n at 0, +-1, +-2, +-3, 4, +-17 and int64's extremes",
              [(a, n) for a in xs for n in ns]))
    return R


def main():
    fmt = FORMATS[sys.argv[1]]
    fns = sys.argv[2:] or ("pow", "powr", "pown", "rootn", "compound")
    t0 = time.time()
    bad = 0
    for fn in fns:
        for name, lanes in rows(fmt, fn):
            lanes = [ln for ln in lanes if ln[0] is not None
                     and ln[1] is not None]
            res = [H.compare(fmt, fn, lanes, rnd) for rnd in ATTRS]
            wrong = sum(r["wrong"] for r in res)
            marked = sum(r["marked"] for r in res)
            refused = sum(r["refused"] for r in res)
            bad += wrong
            print(f"{fmt.name} {fn:8s} {len(lanes):3d} lanes x 5: wrong "
                  f"{wrong}, marked {marked}, refused {refused}  | {name}",
                  flush=True)
            for r, rnd in zip(res, ATTRS):
                for lane, bits, fl, want in r["wrong_ex"][:3]:
                    print(f"     {AN[rnd]} WRONG {H.show(fmt, lane, fn)} got "
                          f"({bits:#x}, {fl:#x}) want ({want[0]:#x}, "
                          f"{want[1]:#x})")
                for lane, bits, fl, want in r["marked_ex"][:2]:
                    print(f"     {AN[rnd]} marked {H.show(fmt, lane, fn)}")
    print(f"{fmt.name}: {bad} wrong unmarked special lanes; "
          f"{time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
