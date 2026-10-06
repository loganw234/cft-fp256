# M1 model: random arguments in each main path; the actual error of V
# against the in-lane bound, with mpmath at 4p + 200 bits the reference.
import math, sys, time, random
from fractions import Fraction
import mpmath
from m1core import sf, evaluate, dec, enc, RDN, RUP
from m1const import mpf_to_frac
from m1exp import build_exp, LN2 as LN2_MP
from m1log import build_log
from m1harness import domain_sample, FORMATS, tr

def true_scaled(fmt, fn, xa, k):
    x = mpmath.mpf(dec(fmt, xa).numerator) / dec(fmt, xa).denominator
    if fn == "exp":
        v = mpmath.exp(x)
    elif fn == "exp2":
        v = mpmath.power(2, x)
    elif fn == "expm1":
        v = mpmath.expm1(x)
    elif fn == "log":
        v = mpmath.log(x)
    elif fn == "log2":
        v = mpmath.log(x) / mpmath.log(2)
    else:
        v = mpmath.log1p(x)
    return v * mpmath.mpf(2) ** (-k)

_SCREENS = {}


def screens(fmt):
    """The model's own screen constants (m1exp.build_exp's XOVF, XUNF and
    XM1, the same expressions), as values: the main path's exact ends."""
    if fmt.name not in _SCREENS:
        p, l2 = fmt.prec, mpf_to_frac(LN2_MP)
        _SCREENS[fmt.name] = (
            dec(fmt, enc(fmt, (fmt.emax + 1) * l2 + Fraction(1, 2 ** 3000), RUP)),
            dec(fmt, enc(fmt, (fmt.emin - p) * l2, RDN)),
            dec(fmt, enc(fmt, -(p + 2) * l2, RDN)))
    return _SCREENS[fmt.name]


def in_main(fmt, fn, xa):
    """Whether the main path answers x (no special, screen, tiny or exact
    path does), by the model's own thresholds. (Until the send-back of
    2026-10-05 this kept a margin of 1 inside each end of the exp
    family's range, so the last unit at each end went unmeasured:
    verifier-VM1's note.)"""
    u = sf.unpack(fmt, xa)
    if u.kind in (sf.NAN, sf.INF, sf.ZERO):
        return False
    x = dec(fmt, xa)
    p = fmt.prec
    ax = abs(x)
    xovf, xunf, xm1 = screens(fmt)
    if fn == "exp":
        return xunf < x < xovf and ax >= Fraction(1, 2 ** (p + 3))
    if fn == "exp2":
        return (fmt.emin - p < x < fmt.emax + 1 and ax >= Fraction(1, 2 ** (p + 3))
                and x.denominator != 1)
    if fn == "expm1":
        return xm1 < x < xovf and ax >= Fraction(1, 2 ** (p + 2))
    if fn in ("log", "log2"):
        if x <= 0 or x == 1:
            return False
        if fn == "log2" and x.numerator & (x.numerator - 1) == 0 and x.denominator & (x.denominator - 1) == 0:
            return False
        return True
    return x > -1 and ax >= Fraction(1, 2 ** (p + 2))


def run(fn, fmtname, rnd, n, seed=1, inflate=0):
    fmt = FORMATS[fmtname]
    p = fmt.prec
    mpmath.mp.prec = 4 * p + 200
    G = 46
    if fn in ("exp", "exp2", "expm1"):
        brel = None if not inflate else sf.round_pack(fmt, 0, 1, -(p + G) + inflate, 0)[0]
        f = build_exp(fmt, rnd, fn, brel=brel, brel_z=brel)
    else:
        brel = None if not inflate else sf.round_pack(fmt, 0, 1, -(p + G) + inflate, 0)[0]
        f = build_log(fmt, rnd, fn, brel=brel)
    xs = domain_sample(fmt, fn, n, seed)
    wrong = marked = right = main = 0
    worst = -1e9
    hist = {}
    for xa in xs:
        bits, fw, pr = evaluate(f, xa, want=["Vh", "Vl", "Bv", "Ek", "R", "mk"], full=True)
        gb, gf = tr.compute(fmt, fn, xa, 0, rnd)
        if fw & 0x80:
            marked += 1
            if bits == gb and (fw & 0x1F) == gf:
                right += 1
        elif (bits, fw) != (gb, gf):
            wrong += 1
            if wrong <= 5:
                print("   WRONG", fn, fmtname, sf.RND_NAMES[rnd], hex(xa), hex(bits), fw, hex(gb), gf)
        # error of V where the main path is the answer
        try:
            vh, vl, bv = dec(fmt, pr["Vh"]), dec(fmt, pr["Vl"]), dec(fmt, pr["Bv"])
        except Exception:
            continue
        if bv == 0:
            continue
        if fn in ("exp", "exp2", "expm1"):
            k = pr["Ek"] - fmt.bias - f.meta["OFF"]
        else:
            k = 0
        # only lanes whose answer comes from the main path
        u = sf.unpack(fmt, xa)
        if u.kind in (sf.NAN, sf.INF, sf.ZERO):
            continue
        tv = true_scaled(fmt, fn, xa, k)
        if not mpmath.isfinite(tv):
            continue
        err = abs(mpmath.mpf(vh.numerator) / vh.denominator + mpmath.mpf(vl.numerator) / vl.denominator - tv)
        ratio = err / (mpmath.mpf(bv.numerator) / bv.denominator)
        if ratio == 0:
            continue
        lr = float(mpmath.log(ratio, 2))
        # skip lanes the specials or screens answer: their V is garbage
        if (bits, fw & 0x1F) != (pr["R"], fw & 0x1F) and fn not in ("exp", "exp2", "expm1"):
            pass
        if not in_main(fmt, fn, xa):
            continue     # a screened or special lane: V is not the answer
        main += 1
        worst = max(worst, lr)
        b = math.floor(lr)
        hist[b] = hist.get(b, 0) + 1
    return {"n": len(xs), "wrong": wrong, "marked": marked, "marked_right": right,
            "main": main, "worst_log2_err_over_bound": worst, "hist": dict(sorted(hist.items())),
            "insns": len(f.body)}

if __name__ == "__main__":
    fns = sys.argv[1].split(",")
    fmtname = sys.argv[2]
    n = int(sys.argv[3])
    rnds = [int(c) for c in sys.argv[4].split(",")] if len(sys.argv) > 4 else list(sf.RND_MODES)
    inflate = int(sys.argv[5]) if len(sys.argv) > 5 else 0
    t0 = time.perf_counter()
    for fn in fns:
        for rnd in rnds:
            st = run(fn, fmtname, rnd, n, inflate=inflate)
            print(fn, fmtname, sf.RND_NAMES[rnd], "inflate", inflate, st, f"{time.perf_counter()-t0:.0f}s", flush=True)
