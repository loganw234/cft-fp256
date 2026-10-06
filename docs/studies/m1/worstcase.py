# Arguments placed where each path leaves its reduced argument largest -
# the bound's worst point for the truncation and the tail - and the error
# there, path by path (each path's own largest |r|, not the seed cells'
# alone):
#   exp, expm1: x next to (n +- 1/2) ln2/8;  exp2: x next to (n +- 1/2)/8
#   log, log2: m at the ends of the first and last C = 9 seed cells
#     (rmax.py), x = m 2^k
#   log1p: the reduction path the same way (x = m 2^k - 1, and the same x
#     with the low word of 1 + x at its largest), and the r = x path at its
#     end, |x| just under SMALL, and the reduction path's own lower end
# (Until the send-back of 2026-10-05 the exp family's points were each
# placed twice - an unused sign loop: 33 distinct of "66" - and no log1p
# point lay on the r = x path: verifier-VM1's notes.)
import sys, time, math
from fractions import Fraction
import mpmath
from m1core import sf, evaluate, dec, enc
from m1exp import build_exp
from m1log import build_log, SMALL
from m1harness import FORMATS, tr
from m1measure import true_scaled, in_main

fmtname = sys.argv[1]
fmt = FORMATS[fmtname]; p = fmt.prec
mpmath.mp.prec = 4 * p + 200
LN2 = mpmath.log(2)
t0 = time.perf_counter()
args = {"exp": [], "exp2": [], "expm1": [], "log": [], "log2": [], "log1p": []}
for n in (-41, -17, -9, -1, 0, 1, 3, 9, 33, 77, 401):
    for s in (-1, 1):                       # both ends of n's interval
        mid = (mpmath.mpf(n) + mpmath.mpf(s) / 2) * LN2 / 8
        b = enc(fmt, Fraction(int(mpmath.floor(mid * 2 ** (p + 60))), 2 ** (p + 60)))
        args["exp"] += [b, b + 1, b - 1]
        args["expm1"] += [b, b + 1, b - 1]
        b2 = enc(fmt, Fraction(2 * n + s, 16))
        args["exp2"] += [b2 + 1, b2 - 1, b2 + 2, b2 - 2]


def ulp(v):
    u = sf.unpack(fmt, enc(fmt, v))
    return Fraction(2) ** u.e


# the seed cells of C = 9, and their ends
cells = []
for i in range(512):
    lo = 1 + Fraction(i, 512)
    xb = sf.round_pack(fmt, 0, int(lo * 2 ** (p - 1)), -(p - 1), 0)[0]
    seed = sf.unpack(fmt, sf.recip_seed(fmt, xb)[0])
    t = 16 * Fraction(seed.m) * Fraction(2) ** seed.e
    C = math.floor(t + Fraction(1, 2))
    if C == 9:
        cells.append(i)
for i in cells[:1] + cells[-1:]:
    for end in (Fraction(i, 512), Fraction(i + 1, 512)):
        m = 1 + end
        for k in (0, 1, -1, 7, -300):
            b = sf.round_pack(fmt, 0, int(m * 2 ** (p - 1)), -(p - 1) + k, 0)[0]
            for d in (-2, -1, 0, 1, 2):
                args["log"].append(b + d)
                args["log2"].append(b + d)
                if k in (-1, 0, 1, 7):
                    u = dec(fmt, b + d)
                    x = u - 1                       # 1 + x = u exactly
                    args["log1p"].append(enc(fmt, x))
                    if x and abs(x) < 1:            # and the low word at its largest
                        uu, ux = ulp(u), ulp(x)
                        for dd in {uu / 2, uu / 2 - ux}:
                            if dd > 0:
                                args["log1p"] += [enc(fmt, x + dd), enc(fmt, x - dd)]
# log1p's r = x path at its end, and the reduction path's lower end
U5 = Fraction(1, 2 ** (p + 4))                      # the ulp on [2^-5, 2^-4)
for s in (1, -1):
    args["log1p"] += [enc(fmt, s * (SMALL - j * U5)) for j in (1, 2, 3, 16, 17)]
    args["log1p"] += [enc(fmt, s * (SMALL + j * U5)) for j in (0, 1, 16, 17)]
    args["log1p"] += [enc(fmt, s * (Fraction(1, 16) - j * U5)) for j in (1, 2)]
    args["log1p"] += [enc(fmt, s * (Fraction(1, 16) + 2 * j * U5)) for j in (0, 1)]
for fn in args:
    args[fn] = sorted(set(args[fn]))
for fn, xs in args.items():
    for rnd in (sf.RND_RNE, sf.RND_RTZ):
        f = build_exp(fmt, rnd, fn) if fn.startswith("exp") else build_log(fmt, rnd, fn)
        worst, wx, wrong, marked, nmain = -1e9, None, 0, 0, 0
        for xa in xs:
            bits, fw, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv", "Ek"], full=True)
            gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
            if fw & 0x80:
                marked += 1
            elif (bits, fw) != (gb, gf):
                wrong += 1
            if not in_main(fmt, fn, xa):
                continue
            k = pr["Ek"] - fmt.bias - f.meta["OFF"] if fn.startswith("exp") else 0
            vh, vl, bv = dec(fmt, pr["Vh"]), dec(fmt, pr["Vl"]), dec(fmt, pr["Bv"])
            tv = true_scaled(fmt, fn, xa, k)
            err = abs(mpmath.mpf(vh.numerator) / vh.denominator + mpmath.mpf(vl.numerator) / vl.denominator - tv)
            if err:
                lr = float(mpmath.log(err / (mpmath.mpf(bv.numerator) / bv.denominator), 2))
                if lr > worst:
                    worst, wx = lr, xa
            nmain += 1
        print(f"{fmtname} {fn:5s} {sf.RND_NAMES[rnd]}: {len(xs)} placed arguments ({nmain} on the main path), wrong {wrong}, marked {marked}, worst log2(err/bound) {worst:.2f} at x = {float(dec(fmt, wx)) if wx is not None else float('nan'):+.12g}  {time.perf_counter()-t0:.0f}s", flush=True)
