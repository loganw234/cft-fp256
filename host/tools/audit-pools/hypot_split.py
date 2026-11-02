#!/usr/bin/env python3
"""Split the pairs the extras ask of hypot, by what they are.

docs/TRANSCENDENTALS.md counts the family `hypot:triples` by the line of
the vector generator that builds each pair (40 "both signs", 20 "one ulp
off", 40 "scaled": 100 pairs).  This script counts the same pairs by what
each one is, from a dump of the cases: an exact Pythagorean triple (the
hypot is exactly representable in value: a^2 + b^2 is the square of a
dyadic rational), a pair one ulp from an exact triple (one operand stepped
by one unit in the last place), or neither.  The two splits are of the
same pairs: the generator's list holds ten pairs, eight of them triples and
two of them, (1, 1) and (2, 2), not.

Run from the repository's root, on the dump of the extras at one format:

    cd host
    CFT_MPFR_DUMP_CASES=1 CFT_MPFR_PHASES=extras CFT_MPFR_FORMATS=fp32 \
        ./mpfr-check 24 7 > /tmp/extras-fp32.txt
    cd ..
    python host/tools/audit-pools/hypot_split.py /tmp/extras-fp32.txt fp32

It prints the counts for every hypot family in the dump.  The dump holds
the pairs the extras ADD, not the ones a pool already held, so the split
of the 100 of `hypot:triples` is read from 92 lines at fp32 (the pools hold
8, all of the "neither" kind).  Python 3.8 or later.
"""
import collections
import math
import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "python"))

from cft_golden import formats as F          # noqa: E402
from cft_golden import softfloat as sf       # noqa: E402

FMTS = {"fp32": F.FP32, "fp64": F.FP64, "fp128": F.FP128, "fp256": F.FP256}


def value(fmt, bits):
    """|x| as a Fraction, or None for a zero, infinity or NaN."""
    u = sf.unpack(fmt, bits)
    if u.kind in (sf.NAN, sf.INF, sf.ZERO):
        return None
    return Fraction(u.m) * (Fraction(2) ** u.e)


def is_square(q):
    return (math.isqrt(q.numerator) ** 2 == q.numerator and
            math.isqrt(q.denominator) ** 2 == q.denominator)


def exact_triple(x, y):
    return x is not None and y is not None and is_square(x * x + y * y)


def neighbours(fmt, bits):
    """The encodings one ulp either side of the magnitude, sign kept."""
    sign = bits & (1 << (fmt.width - 1))
    mag = bits ^ sign
    return [(mag + d) | sign for d in (-1, 1) if mag + d >= 0]


def classify(fmt, a, b):
    if exact_triple(value(fmt, a), value(fmt, b)):
        return "exact triple"
    for na in neighbours(fmt, a):
        if exact_triple(value(fmt, na), value(fmt, b)):
            return "one ulp from an exact triple"
    for nb in neighbours(fmt, b):
        if exact_triple(value(fmt, a), value(fmt, nb)):
            return "one ulp from an exact triple"
    return "neither"


def main(argv):
    if len(argv) != 3 or argv[2] not in FMTS:
        sys.stderr.write(__doc__)
        return 2
    fmt = FMTS[argv[2]]
    count = collections.defaultdict(collections.Counter)
    with open(argv[1], errors="replace") as fh:
        for line in fh:
            p = line.split()
            # C <format> <function> e <i> 0 1 <a> <b> <n> <family>
            if len(p) < 11 or p[0] != "C" or p[1] != argv[2] or p[2] != "hypot" or p[3] != "e":
                continue
            fam = p[10]
            count[fam][classify(fmt, int(p[7], 16), int(p[8], 16))] += 1
    if not count:
        sys.stderr.write("hypot_split.py: no hypot line of the extras at %s in %s\n" % (argv[2], argv[1]))
        return 2
    for fam in sorted(count):
        c = count[fam]
        print("%-22s %4d pairs: %d exact triples, %d one ulp from an exact triple, %d neither" % (
            fam, sum(c.values()), c["exact triple"], c["one ulp from an exact triple"], c["neither"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
