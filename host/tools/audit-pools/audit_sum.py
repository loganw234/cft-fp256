"""Per group and format: what the vector generator directs (distinct operands or pairs),
and how many of them the oracle's pools held before and hold after.

Usage, from the repository's root:

    python -B host/tools/audit-pools/audit_sum.py BEFORE AFTER > summary.md

BEFORE and AFTER as for audit_table.py.  Writes the summary table of
docs/TRANSCENDENTALS.md.
"""
import sys
import os  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_lib import *   # noqa
V._rand_bits = lambda rng, fmt: sf.one_bits(fmt)
LONG = 2147483647
before = parse_dump(sys.argv[1]); after = parse_dump(sys.argv[2])
G = [("exp family (7)", "transcend_unary_pool", "exp", "u"),
     ("trig family (9)", "trig_unary_pool", "sinpi", "u"),
     ("sin cos tan (3)", "radian_unary_pool", "sin", "u"),
     ("hyperbolics (6)", "hyperbolic_unary_pool", "sinh", "u"),
     ("table 9.1 unary (6)", "table91_unary_pool", "exp2m1", "u"),
     ("pow", "transcend_pow_pairs", "pow", "p"),
     ("hypot", "transcend_hypot_pairs", "hypot", "p"),
     ("atan2, atan2pi", "trig_atan2_pairs", "atan2", "p"),
     ("powr", "transcend_powr_pairs", "powr", "p"),
     ("pown compound rootn", "transcend_int_pow_cases", "pown", "i")]
print("| functions | what the vectors direct | held before | held after |")
print("|---|---|---|---|")
for title, bname, fn, kind in G:
    row = []
    for fname in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FMTS[fname]
        if kind == "u":
            vec = set(getattr(V, bname)(fmt, 0))
            hb = len(vec & first_operands(before, fname, fn)); ha = len(vec & first_operands(after, fname, fn))
        elif kind == "p":
            vec = set(getattr(V, bname)(fmt, 0))
            hb = len(vec & pairs(before, fname, fn)); ha = len(vec & pairs(after, fname, fn))
        else:
            vec = {(a, k) for (a, k) in getattr(V, bname)(fmt, 0) if -LONG <= k <= LONG}
            hb = len(vec & pairs(before, fname, fn)); ha = len(vec & pairs(after, fname, fn))
        row.append((len(vec), hb, ha))
    print("| %s | %s | %s | %s |" % (title, "/".join(str(r[0]) for r in row), "/".join(str(r[1]) for r in row), "/".join(str(r[2]) for r in row)))
