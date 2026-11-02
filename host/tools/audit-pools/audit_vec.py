"""For every unary function: the operands vectors.py directs at it that the
oracle's pool does not hold, grouped by the line of vectors.py that builds
them.

Usage, from the repository's root:

    python -B host/tools/audit-pools/audit_vec.py DUMP [FORMATS [FUNCTIONS]]

DUMP is a case dump (CFT_MPFR_DUMP_CASES=1 ./mpfr-check 24 7, run in host/);
FORMATS and FUNCTIONS are comma lists (all by default).
"""
import collections
import sys
import time

import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_lib import *   # noqa

dump = sys.argv[1]
only_fmt = sys.argv[2].split(",") if len(sys.argv) > 2 else list(FMTS)
only_fn = sys.argv[3].split(",") if len(sys.argv) > 3 else None

cases = parse_dump(dump)

TAG = collections.defaultdict(set)


def tagged_extend(out, *values):
    ln = sys._getframe(1).f_lineno
    for v in values:
        if v is not None:
            out.append(v)
            TAG[v].add(ln)


V._extend = tagged_extend

POOLS = {}
for fn in ("exp", "expm1", "exp2", "log", "log1p", "log2", "log10"):
    POOLS[fn] = V.transcend_unary_pool
for fn in ("sinpi", "cospi", "tanpi", "asin", "acos", "atan", "asinpi",
           "acospi", "atanpi"):
    POOLS[fn] = V.trig_unary_pool
for fn in ("sin", "cos", "tan"):
    POOLS[fn] = V.radian_unary_pool
for fn in ("sinh", "cosh", "tanh", "asinh", "acosh", "atanh"):
    POOLS[fn] = V.hyperbolic_unary_pool
for fn in ("exp2m1", "exp10", "exp10m1", "log2p1", "log10p1", "rsqrt"):
    POOLS[fn] = V.table91_unary_pool

IO_LINES = set()
for fmt_name in only_fmt:
    fmt = FMTS[fmt_name]
    t0 = time.time()
    io = set(V.interesting_operands(fmt))
    built = {}
    for pb in set(POOLS.values()):
        TAG.clear()
        t1 = time.time()
        vec = pb(fmt, 0)
        built[pb] = (vec, {k: set(v) for k, v in TAG.items()})
    print("== %s (vectors built in %.1fs)" % (fmt_name, time.time() - t0))
    for fn in FNS:
        if fn not in POOLS or (only_fn and fn not in only_fn):
            continue
        vec, tags = built[POOLS[fn]]
        pool = first_operands(cases, fmt_name, fn)
        miss = [v for v in vec if v not in pool]
        bysrc = collections.defaultdict(list)
        for v in miss:
            key = tuple(sorted(tags.get(v, {"IO" if v in io else "?"})))
            bysrc[key].append(v)
        print("  %-8s vec=%4d pool=%3d missing=%4d" % (fn, len(vec),
                                                       len(pool), len(miss)))
        for key in sorted(bysrc, key=lambda k: (-len(bysrc[k]), tuple(map(str, k)))):
            ex = bysrc[key]
            print("      lines %-14s %3d  e.g. %s" % (
                ",".join(map(str, key)), len(ex),
                "; ".join(describe(fmt, v) for v in ex[:3])))
