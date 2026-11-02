"""proto_worst.py: part of the pool audit; see docs/TRANSCENDENTALS.md.

Needs mpmath.  Usage, from the repository's root, no arguments:

    python -B host/tools/audit-pools/proto_worst.py

Prototype of the search for the arguments whose reduction modulo pi cancels
most (continued fractions of frac(2^(v - p + 2) / pi)), checked against
host/tools/pi_worstcase.py.
"""
import sys, time
import os  # noqa: E402
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "python"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from cft_golden import formats as F
import pi_worstcase as PW
import mpmath

def my_worst(fmt, v):
    p = fmt.prec
    Fb = 2 * p + 128
    N0, N1 = 1 << (p - 1), 1 << p
    mpmath.mp.prec = max(v - p + 2, 0) + 2 * p + 192
    alpha = mpmath.mpf(2) ** (v - p + 2) / mpmath.pi
    f = alpha - mpmath.floor(alpha)
    num = int(mpmath.floor(f * (mpmath.mpf(2) ** Fb)))
    den = 1 << Fb
    r0, r1 = den, num
    qm1, q0 = 0, 1
    best = None
    def consider(m):
        nonlocal best
        if not (N0 <= m < N1):
            return
        r = (m * num) % den
        d = min(r, den - r)
        if best is None or d < best[0]:
            best = (d, m)
    while r1:
        a = r0 // r1
        # multiples of the previous convergent
        if q0 >= 1:
            t = -(-N0 // q0)
            consider(t * q0)
        # intermediate fractions qm1 + s*q0
        if q0:
            s_lo = max(1, -(-(N0 - qm1) // q0))
            s_hi = min(a, (N1 - 1 - qm1) // q0)
            for s in {s_lo, s_lo + 1, s_hi, s_hi - 1}:
                if 1 <= s <= a:
                    consider(qm1 + s * q0)
        q = a * q0 + qm1
        r0, r1 = r1, r0 - a * r1
        qm1, q0 = q0, q
        if qm1 >= N1:
            break
    return best

for name in ("fp32", "fp64"):
    fmt = F.FORMATS[name] if hasattr(F, "FORMATS") else None
    emax = fmt.emax
    bad = 0
    t0 = time.time()
    for v in range(0, emax + 1):
        m, e, lost, mag, N = PW.worst_in_binade(fmt, v)
        mine = my_worst(fmt, v)
        if mine is None or mine[1] != m:
            bad += 1
            if bad <= 8:
                print(name, "v=%d ref m=%d mine=%s" % (v, m, mine))
    print(name, "binades", emax + 1, "disagree", bad, "%.1fs" % (time.time() - t0))

for name, stride in (("fp128", 2048), ("fp256", 32768)):
    fmt = F.FORMATS[name]
    bad = 0
    t0 = time.time()
    for v in range(0, fmt.emax + 1, stride):
        m, e, lost, mag, N = PW.worst_in_binade(fmt, v)
        mine = my_worst(fmt, v)
        if mine is None or mine[1] != m:
            bad += 1
            print(name, "v=%d ref m=%d mine=%s" % (v, m, mine))
    print(name, "sampled binades", len(range(0, fmt.emax + 1, stride)), "disagree", bad, "%.1fs" % (time.time() - t0))
