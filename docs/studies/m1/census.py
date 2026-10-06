# The structured families: arguments with few significant bits next to
# the exact cases, where the true value sits within 2^-(2p) of a rounding
# boundary and no double word decides it. Counted at one format, every
# attribute: x = +-c 2^-e (exp, exp2, expm1, log1p) and 1 +- c ulp (log,
# log2), c = 1..cmax, e over a window around p.
import sys, time
from fractions import Fraction
from m1core import sf, evaluate, enc_exact, dec
from m1exp import build_exp
from m1log import build_log
from m1harness import FORMATS, tr

fmtname = sys.argv[1]
cmax = int(sys.argv[2]) if len(sys.argv) > 2 else 64
fmt = FORMATS[fmtname]
p = fmt.prec
t0 = time.perf_counter()
for fn in ("exp", "exp2", "expm1", "log", "log2", "log1p"):
    xs = set()
    if fn in ("log", "log2"):
        one = sf.one_bits(fmt)
        for c in range(1, cmax + 1):
            xs.add(one + c)                     # 1 + c ulp(1)
            xs.add(one - c)                     # 1 - c ulp below 1
    else:
        for e in range(p - 10, p + 4):
            for c in range(1, cmax + 1):
                for s in (0, 1):
                    v = Fraction(c, 2 ** e) * (-1 if s else 1)
                    b = sf.round_pack(fmt, s, c, -e, sf.RND_RNE)
                    if b[1] == 0:
                        xs.add(b[0])
    xs = sorted(xs)
    for rnd in sf.RND_MODES:
        f = build_exp(fmt, rnd, fn) if fn.startswith("exp") else build_log(fmt, rnd, fn)
        marked = wrongguess = wrong = 0
        ms = []
        for xa in xs:
            bits, fw, _ = evaluate(f, xa)
            gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
            if fw & 0x80:
                marked += 1
                ms.append(float(dec(fmt, xa)))
                if (bits, fw & 0x1F) != (gb, gf):
                    wrongguess += 1
            elif (bits, fw) != (gb, gf):
                wrong += 1
        print(f"{fmtname} {fn:5s} {sf.RND_NAMES[rnd]}: {len(xs)} structured arguments, marked {marked} (guess wrong {wrongguess}), wrong unmarked {wrong}; e.g. {['%.3g' % v for v in ms[:4]]}", flush=True)
print(f"{time.perf_counter()-t0:.0f}s")
