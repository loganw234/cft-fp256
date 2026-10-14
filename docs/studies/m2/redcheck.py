# M2 model: the reduction alone, against an exact reference (scratch).
#
#   python redcheck.py FMT [N] [variant]
#
# For each argument x: the model's (r_h + r_l, n mod 4) against the exact
# x 2/pi (2/pi to e + 2p + 400 bits, rationals), with r's relative error
# in units of 2^-(p+G); and every instruction the reduction calls exact,
# audited on the lane. Arguments: random over the range (exponent uniform,
# significand random, both signs), every bucket's two edge exponents,
# every power of two the range holds (sampled at fp128 and fp256), the
# deepest cancellations host/tools/pi_worstcase.py finds (the pools' own,
# through transcend_check.radian_pool and vectors.radian_unary_pool), and
# the products' binade edges (m2edges.py: every bucket and position, the
# significands that bring T_j next to a power of two).

import sys
import time
import random
import importlib.util
from fractions import Fraction

import mpmath

from m2core import (Frag, FORMATS, sf, enc, enc_exact, dec, evaluate, ROOT,
                    RNE)
from m2const import two_over_pi_int, pi_frac
from m2plan import plan, LOST
from m2red import reduce_ph, audit
from m2edges import edges
from cft_golden import vectors

_spec = importlib.util.spec_from_file_location(
    "transcend_check", str(ROOT / "host" / "tests" / "transcend_check.py"))
tc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tc)

GUARD = {"fp64": 44, "fp128": 46, "fp256": 46}
RANGE = {"fp64": 1023, "fp128": 1023, "fp256": 1023}
GATE = {"fp64": -28, "fp128": -58, "fp256": -120}


def build(fmt, P, variant):
    f = Frag(fmt, RNE, f"red-{fmt.name}-{variant}")
    MAGIC = Fraction(3, 2) * 2 ** (fmt.prec - 1)
    mref = f.wx(MAGIC, "MAGIC")
    out = reduce_ph(f, ("in", "a"), P, mref, variant)
    f.result, f.flags = out["rh"], out["q"]
    f.out = out
    return f


def exact_ref(fmt, xa, n_mod4):
    """t = |x| 2/pi - n with n = n_mod4 (mod 4), centred; exact enough
    (the reduction is of |x|; the routine applies the sign)."""
    X = abs(dec(fmt, xa))
    e = max(0, X.numerator.bit_length() - X.denominator.bit_length())
    N = e + 2 * fmt.prec + 400
    T = Fraction(two_over_pi_int(N), 1 << N)
    Pv = X * T
    k = Pv.numerator // Pv.denominator           # floor
    fr = Pv - k
    t = fr + ((k - n_mod4) % 4)
    if t > 2:
        t -= 4
    return t * pi_frac() / 2                      # r


def args(fmt, P, n, seed):
    rng = random.Random(seed)
    p = fmt.prec
    out = []
    for _ in range(n):
        E = rng.randint(P.Egate, P.Emax)
        m = rng.getrandbits(p - 1) | (1 << (p - 1))
        out.append(sf.round_pack(fmt, rng.getrandbits(1), m, E - p + 1, RNE)[0])
    for gm1 in range(P.gm1_min, P.gm1_max + 1):
        for G0 in (gm1 * P.b, gm1 * P.b + P.b - 1):
            E = G0 + p + 1
            if P.Egate <= E <= P.Emax:
                for m in ((1 << (p - 1)), (1 << p) - 1,
                          rng.getrandbits(p - 1) | (1 << (p - 1))):
                    out.append(sf.round_pack(fmt, 0, m, E - p + 1, RNE)[0])
    step = 1 if fmt.width <= 64 else 7
    for E in range(P.Egate, P.Emax + 1, step):
        out.append(sf.round_pack(fmt, 0, 1 << (p - 1), E - p + 1, RNE)[0])
    t = 64 if fmt.width <= 64 else 16
    pool = set(tc.radian_pool(fmt, t, 5)) | set(vectors.radian_unary_pool(fmt, 24, 14))
    lim = enc(fmt, Fraction(2) ** (P.Emax + 1))
    for b in pool:
        ax = b & ~fmt.sign_mask
        u = sf.unpack(fmt, b)
        if u.kind not in (sf.ZERO, sf.INF, sf.NAN) and \
                enc(fmt, Fraction(2) ** P.Egate) <= ax < lim:
            out.append(b)
    return out


def main():
    name = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 300
    variant = sys.argv[3] if len(sys.argv) > 3 else "A"
    fmt = FORMATS[name]
    p, G = fmt.prec, GUARD[name]
    P = plan(fmt, G, LOST[name], RANGE[name], GATE[name])
    f = build(fmt, P, variant)
    print(f"{name} variant {variant}: b {P.b} L {P.L} Z {P.Z} K {P.K} "
          f"bottom {P.bottom} budget {P.budget}; {len(f.body)} instructions "
          f"by phase {f.by_phase()}; {f.meta}", flush=True)
    mpmath.mp.prec = 4 * p + 200
    B = Fraction(1, 2 ** (p + G))
    for label, xs in (("random, bucket edges, powers of two, the pools",
                       args(fmt, P, n, 7)),
                      ("the products' binade edges (m2edges)", edges(fmt, P))):
        t0 = time.perf_counter()
        worst, wx, bad_q, bad_audit, cnt = -1e9, None, 0, 0, 0
        for xa in xs:
            _r, _q, pr = evaluate(f, xa, want=["rh", "rl", "q"])
            rm = dec(fmt, pr["rh"]) + dec(fmt, pr["rl"])
            nq = (pr["q"] - enc_exact(fmt, Fraction(3, 2) * 2 ** (p - 1))) % 4
            rt = exact_ref(fmt, xa, nq)
            if abs(rt) > pi_frac() / 4 * (1 + Fraction(1, 2 ** 20)):
                bad_q += 1
                if bad_q <= 5:
                    print("  QUADRANT off:", hex(xa), nq, float(rt))
                continue
            err = abs(rm - rt) / abs(rt) / B
            lg = float(mpmath.log(mpmath.mpf(err.numerator) / err.denominator, 2)) if err else -999
            if lg > worst:
                worst, wx = lg, xa
            a = audit(f, xa)
            if a:
                bad_audit += 1
                if bad_audit <= 5:
                    print("  AUDIT failed:", hex(xa), a[:4])
            cnt += 1
        print(f"  {label}: {cnt} arguments (of {len(xs)}): r's relative error "
              f"at most 2^{worst:.2f} of 2^-(p+G) at {hex(wx) if wx else None}; "
              f"quadrant off {bad_q}; audit failures {bad_audit}; "
              f"{time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
