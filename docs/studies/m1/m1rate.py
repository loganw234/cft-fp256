# The mark-rate law: with the bound inflated by 2^s, marks become common
# enough to count; the prediction is 2B/ulp averaged over the binade.
import sys, time, random, math
from fractions import Fraction
import mpmath
from m1core import sf, evaluate, dec, enc
from m1exp import build_exp
from m1log import build_log
from m1harness import FORMATS, tr

def uniform_sample(fmt, fn, n, seed=7):
    rng = random.Random(seed + fmt.width)
    p = fmt.prec
    out = []
    while len(out) < n:
        if fn in ("exp", "expm1"):
            v = rng.uniform((fmt.emin - p) * 0.693 + 1, (fmt.emax + 1) * 0.693 - 1)
            if fn == "expm1" and v < -(p + 2) * 0.693 + 1:
                continue
            b = enc(fmt, Fraction(v))
        elif fn == "exp2":
            b = enc(fmt, Fraction(rng.uniform(fmt.emin - p + 1, fmt.emax)))
        elif fn in ("log", "log2"):
            b = rng.getrandbits(fmt.width - 1)
            u = sf.unpack(fmt, b)
            if u.kind != sf.NORM:
                continue
        else:
            b = rng.getrandbits(fmt.width - 1) | (rng.getrandbits(1) << (fmt.width - 1))
            u = sf.unpack(fmt, b)
            if u.kind != sf.NORM:
                continue
            x = dec(fmt, b)
            if x <= -1 or abs(x) < Fraction(1, 2 ** (p + 2)):
                continue
        out.append(b)
    return out

def run(fn, fmtname, rnd, n, s):
    fmt = FORMATS[fmtname]; p = fmt.prec; G = 46
    brel = sf.round_pack(fmt, 0, 1, -(p + G) + s, 0)[0]
    f = build_exp(fmt, rnd, fn, brel=brel, brel_z=brel) if fn.startswith("exp") else build_log(fmt, rnd, fn, brel=brel)
    xs = uniform_sample(fmt, fn, n)
    marked = right = wrong = 0
    pred = 0.0
    for xa in xs:
        bits, fw, pr = evaluate(f, xa, want=["Vh", "Bv"], full=True)
        gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
        if fw & 0x80:
            marked += 1
            right += (bits == gb and (fw & 0x1F) == gf)
        elif (bits, fw) != (gb, gf):
            wrong += 1
        # prediction: 2 Bv / ulp(V_h) for this lane (one boundary per ulp)
        try:
            vh = sf.unpack(fmt, pr["Vh"]); bv = dec(fmt, pr["Bv"])
            if vh.kind == sf.NORM and bv > 0:
                ulp = Fraction(2) ** (vh.e)          # vh.m has p bits: e is ulp's exponent
                pred += float(2 * bv / ulp)
        except Exception:
            pass
    return marked, right, wrong, pred, len(xs)

if __name__ == "__main__":
    fns = sys.argv[1].split(","); fmtname = sys.argv[2]; n = int(sys.argv[3]); s = int(sys.argv[4])
    rnds = [int(c) for c in sys.argv[5].split(",")] if len(sys.argv) > 5 else [0, 1]
    t0 = time.perf_counter()
    for fn in fns:
        for rnd in rnds:
            m, r, wr, pred, nn = run(fn, fmtname, rnd, n, s)
            print(f"{fn:5s} {fmtname} {sf.RND_NAMES[rnd]} bound 2^-(p+{46-s}): marked {m}/{nn} = {m/nn:.4f} (guess right {r}), predicted {pred/nn:.4f}, wrong unmarked {wr}  {time.perf_counter()-t0:.0f}s", flush=True)
