# The 16/C reduction's |r| bound, exactly, over all 512 RECIP_SEED cells
# (the seed is constant on a cell, so C is; |r| is largest at its ends).
import math
from fractions import Fraction
import m1core
from m1core import sf
from m1harness import FORMATS
for name in ('fp32', 'fp64', 'fp256'):
    fmt = FORMATS[name]; p = fmt.prec
    worst = Fraction(0); worstC = None; Cs = set()
    for i in range(512):
        lo = 1 + Fraction(i, 512); hi = 1 + Fraction(i + 1, 512) - Fraction(1, 2 ** (p - 1))
        xb = sf.round_pack(fmt, 0, int(lo * 2 ** (p - 1)), -(p - 1), 0)[0]
        seed = sf.unpack(fmt, sf.recip_seed(fmt, xb)[0])
        sv = Fraction(seed.m) * Fraction(2) ** seed.e
        t = 16 * sv
        C = math.floor(t + Fraction(1, 2))
        if t + Fraction(1, 2) == C and C % 2:       # a tie: RNE takes the even
            C -= 1
        if C == 8:
            c = Fraction(1); ends = (lo / 2, hi / 2)
        else:
            c = Fraction(C, 16); ends = (lo, hi)
        Cs.add(C)
        for m in ends:
            r = abs(m * c - 1)
            if r > worst:
                worst, worstC = r, C
    print(name, 'max|r| =', float(worst), '= 2^%.3f' % math.log2(worst), 'at C =', worstC, 'C in', sorted(Cs))
