# M4 model: the specials and the flags, row by row against transcend.py
# (scratch; the study's section 4). Each named row's arguments through the
# model and through transcend.py under all five attributes: equal in bits
# and flag word, or marked (allowed only where the design marks: atan2's
# tiny-quotient range). One line a row: the model's result and flag word
# under rne, and the count of attributes equal, marked and wrong.
#
#   python specials.py FMT

import sys
from fractions import Fraction

from m4core import FORMATS, sf, enc, dec, evaluate2, ATTRS, RNE
from m4inv import build, gates, FNS
from m4harness import golden


def V(fmt, s, m, e):
    b, fl = sf.round_pack(fmt, s, m, e, RNE)
    assert fl == 0, (m, e)
    return b


def rows(fmt, fn):
    p = fmt.prec
    one, mone = sf.one_bits(fmt), sf.one_bits(fmt, 1)
    msub, mxsub, mnn = (sf.min_subnormal_bits(fmt), sf.max_subnormal_bits(fmt),
                        sf.min_normal_bits(fmt))
    mxn = sf.max_normal_bits(fmt)
    inf, qn, sn = sf.inf_bits(fmt), sf.qnan_bits(fmt), sf.snan_bits(fmt)
    S = fmt.sign_mask
    ga, gs = gates(fmt)
    if fn == "atan2":
        r = []
        two = V(fmt, 0, 1, 1)
        ys = {"+0": 0, "-0": S, "+1": one, "-1": mone, "+inf": inf,
              "-inf": inf | S, "+minSub": msub}
        xs = {"+0": 0, "-0": S, "+1": one, "-1": mone, "+inf": inf,
              "-inf": inf | S, "+maxN": mxn}
        for yn, y in ys.items():
            for xn, x in xs.items():
                r.append((f"9.2.1 y {yn}, x {xn}", (y, x)))
        r += [("NaN y", (qn, one)), ("NaN x", (one, qn)), ("sNaN y", (sn, one)),
              ("sNaN x", (one, sn)), ("NaN, sNaN", (qn, sn)),
              ("diagonal +1, +1", (one, one)), ("diagonal +1, -1", (one, mone)),
              ("diagonal -1, -1", (mone, mone)),
              ("diagonal minSub, -minSub", (msub, msub | S)),
              ("diagonal maxN, maxN", (mxn, mxn)),
              ("diagonal one off: 1+ulp, 1", (one + 1, one)),
              ("exact quotient minSub/2 (a subnormal midpoint)", (msub, two)),
              ("exact quotient -minSub/2", (msub | S, two)),
              ("exact quotient minSub/1", (msub, one)),
              ("exact quotient 2^(emin)/2^p", (mnn, V(fmt, 0, 1, p))),
              ("exact quotient 2^-60 / 1", (V(fmt, 0, 1, -60), one)),
              ("exact quotient 3 2^-60 / 3", (V(fmt, 0, 9, -60), V(fmt, 0, 3, 0))),
              ("exact quotient -2^-40 / 2", (V(fmt, 1, 1, -40), two)),
              (f"exact quotient at the gate 2^{ga - 1}", (V(fmt, 0, 1, ga - 1), one)),
              (f"exact quotient past the gate 2^{ga}", (V(fmt, 0, 1, ga), one)),
              ("exact quotient 2^-60 against x < 0", (V(fmt, 0, 1, -60), mone)),
              ("one ulp off exact 2^-60 / 1", (V(fmt, 0, 1, -60) + 1, one)),
              ("one ulp off, divisor 1 + ulp", (V(fmt, 0, 1, -60), one + 1)),
              ("|y| dominant, 1 / 2^-60", (one, V(fmt, 0, 1, -60))),
              ("subnormal both, 3 minSub / minSub", (3 * msub, msub)),
              ("subnormal both, minSub / 3 minSub", (msub, 3 * msub)),
              ("maxN / (0.9 maxN), d + c n past maxN unscaled",
               (mxn, enc(fmt, Fraction(9, 10) * dec(fmt, mxn))))]
        return r
    r = [("+0", 0), ("-0", S), ("+inf", inf), ("-inf", inf | S), ("qNaN", qn),
         ("sNaN", sn), ("+minSub", msub), ("-minSub", msub | S),
         ("+maxSub", mxsub), ("+minNormal", mnn), ("-minNormal", mnn | S)]
    if fn == "atan":
        r += [(f"gate - ulp (2^{ga} - ulp)", V(fmt, 0, 1, ga) - 1),
              (f"gate 2^{ga}", V(fmt, 0, 1, ga)),
              ("+1", one), ("-1", mone), ("+maxN", mxn), ("-maxN", mxn | S),
              (f"2^{p}", V(fmt, 0, 1, p)), (f"2^{p + 2}", V(fmt, 0, 1, p + 2))]
    else:
        r += [(f"gate - ulp (2^{gs} - ulp)", V(fmt, 0, 1, gs) - 1),
              (f"gate 2^{gs}", V(fmt, 0, 1, gs)),
              ("+1", one), ("-1", mone), ("1 - ulp", one - 1),
              ("-(1 - ulp)", mone - 1), ("1 + ulp", one + 1),
              ("-(1 + ulp)", mone + 1), ("+maxN", mxn), ("+1/2", V(fmt, 0, 1, -1)),
              ("-1/2", V(fmt, 1, 1, -1)),
              ("nearest 1/sqrt2", enc(fmt, Fraction(7071067811865475244, 10 ** 19)))]
    return r


def main():
    name = sys.argv[1]
    fmt = FORMATS[name]
    for fn in FNS:
        frags = {rnd: build(fmt, rnd, fn) for rnd in ATTRS}
        tot = [0, 0, 0]
        for label, args in rows(fmt, fn):
            eq = mk = bad = 0
            for rnd in ATTRS:
                b, fw, _ = evaluate2(frags[rnd], args)
                gb, gf = golden(fmt, fn, args, rnd)
                if fw & 0x80:
                    mk += 1
                elif (b, fw) == (gb, gf):
                    eq += 1
                else:
                    bad += 1
            b, fw, _ = evaluate2(frags[RNE], args)
            tot = [tot[0] + eq, tot[1] + mk, tot[2] + bad]
            print(f"{name} {fn} {label}: rne {hex(b)} flags {hex(fw)}; "
                  f"equal {eq}, marked {mk}, wrong {bad}", flush=True)
        print(f"{name} {fn}: all rows, attributes equal {tot[0]}, marked "
              f"{tot[1]}, wrong {tot[2]}", flush=True)


if __name__ == "__main__":
    main()
