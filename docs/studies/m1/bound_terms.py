# The bound's terms, computed from the design's parameters (no lanes).
import math
from m1exp import exp_plan
from m1log import log_plan, RHO
from m1harness import FORMATS
G = 46
lg = lambda v: math.log2(v)
fact = lambda n: math.factorial(n)
print("exp/exp2 (relative to V), log family (relative to V); each term as log2")
for name in ("fp64", "fp128", "fp256"):
    fmt = FORMATS[name]; p = fmt.prec; u = 2.0 ** -p
    K, D, rho = exp_plan(fmt, 8, G)
    t_tail = 2 * u * rho ** (K + 1) / fact(K + 1)
    t_trunc = rho ** (D + 2) / fact(D + 2) * (1 + rho)
    t_round = 10 * u * u
    t_red = 2 * u * 2.0 ** -(p + 4.5)
    tot = t_tail + t_trunc + t_round + t_red
    Km, Dm, _ = exp_plan(fmt, 8, G, rel_z=True)
    tz_tail = 2 * u * rho ** Km / fact(Km + 1)
    tz_trunc = rho ** (Dm + 1) / fact(Dm + 2) * (1 + rho)
    totz = tz_tail + tz_trunc + 10 * u * u
    Kl, Dl = log_plan(fmt, G)
    rl = RHO
    l_tail = 2 * u * rl ** Kl / (Kl + 1)
    l_trunc = rl ** (Dl + 1) / (Dl + 2) / (1 - rl)
    l_round = 12 * u * u
    totl = l_tail + l_trunc + l_round
    print(f"{name}: bound 2^{-(p+G)} | exp K={K} D={D}: tail {lg(t_tail):.1f} trunc {lg(t_trunc):.1f} rounding {lg(t_round):.1f} reduction {lg(t_red):.1f} -> total {lg(tot):.1f} | expm1 n=0 (rel. Z) K={Km}: total {lg(totz):.1f} | log K={Kl} D={Dl}: tail {lg(l_tail):.1f} trunc {lg(l_trunc):.1f} rounding {lg(l_round):.1f} -> total {lg(totl):.1f}")
