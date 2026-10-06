from fractions import Fraction
import mpmath
from m1core import sf, enc, dec, RUP, RDN
from m1exp import exp_plan
from m1log import log_plan
from m1harness import FORMATS
from m1const import mpf_to_frac
LN2 = mpf_to_frac(mpmath.log(2))
for name in ("fp32", "fp64", "fp128", "fp256"):
    fmt = FORMATS[name]; p = fmt.prec
    xovf = enc(fmt, (fmt.emax + 1) * LN2, RUP)
    xunf = enc(fmt, (fmt.emin - p) * LN2, RDN)
    xm1 = enc(fmt, -(p + 2) * LN2, RDN)
    nmax = 8 * (max(fmt.emax + 1, -(fmt.emin - p)) + 4)
    kmax = max(fmt.emax + 1, -(fmt.emin - p)) + 2
    line = f"{name}: X_OVF(exp) {float(dec(fmt, xovf)):.12g}  X_UNF(exp) {float(dec(fmt, xunf)):.12g}  X_M1(expm1) {float(dec(fmt, xm1)):.6g}  exp2 screens >= {fmt.emax+1}, <= {fmt.emin - p}  |n| < 2^{nmax.bit_length()} |k| < 2^{kmax.bit_length()}"
    if p > 24:
        K, D, rho = exp_plan(fmt); Km, Dm, _ = exp_plan(fmt, rel_z=True); Kl, Dl = log_plan(fmt)
        line += f"  | exp/exp2 K{K} D{D}, expm1 K{Km} D{Dm}, log family K{Kl} D{Dl}"
    print(line)
