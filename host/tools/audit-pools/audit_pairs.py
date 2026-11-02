"""Pair-level coverage: the (a, b) pairs and (a, n) pairs vectors.py directs
at the binary and integer-exponent functions, against the pairs the oracle
asks (directed only).

Usage, from the repository's root:

    python -B host/tools/audit-pools/audit_pairs.py DUMP [FORMATS]

DUMP is a case dump; FORMATS a comma list (all by default).
"""
import collections
import sys

import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_lib import *   # noqa

dump = sys.argv[1]
fmts = sys.argv[2].split(",") if len(sys.argv) > 2 else list(FMTS)
cases = parse_dump(dump)
# the generator's random operands are not directed: replace them by 1.0 so the set is unchanged
V._rand_bits = lambda rng, fmt: sf.one_bits(fmt)


def cls(fmt, bits):
    u = sf.unpack(fmt, bits)
    if u.kind == sf.NAN:
        return "sNaN" if u.signaling else "qNaN"
    if u.kind == sf.INF:
        return "-inf" if u.sign else "+inf"
    if u.kind == sf.ZERO:
        return "-0" if u.sign else "+0"
    return "-fin" if u.sign else "+fin"


for fname in fmts:
    fmt = FMTS[fname]
    print("== %s" % fname)
    vc = collections.defaultdict(set)
    for (fn, a, b, k) in V.transcend_cases(fmt, 0):
        if ARITY[fn] == 2 or INTARG[fn]:
            vc[fn].add((a, b if ARITY[fn] == 2 else k))
    for fn in ("pow", "hypot", "atan2", "atan2pi", "powr", "pown",
               "compound", "rootn"):
        op = pairs(cases, fname, fn)
        pool_ops = operands(cases, fname, fn)
        vp = vc[fn]
        miss = vp - op
        # marginal membership
        va = {p[0] for p in vp}
        vb = {p[1] for p in vp} if not INTARG[fn] else set()
        print("  %-8s vector pairs %5d  oracle directed pairs %5d  vector pairs NOT asked %5d  | a-operands missing %3d/%3d  b-operands missing %3d/%3d" % (
            fn, len(vp), len(op), len(miss), len(va - pool_ops), len(va),
            len(vb - pool_ops), len(vb)))
        # by class of the pair (specials crossing)
        byc = collections.Counter()
        for (a, b) in miss:
            if INTARG[fn]:
                byc[(cls(fmt, a), "n")] += 1
            else:
                byc[(cls(fmt, a), cls(fmt, b))] += 1
        top = byc.most_common(8)
        print("            missing by class:", ", ".join("%s/%s:%d" % (k[0], k[1], v) for k, v in top))
