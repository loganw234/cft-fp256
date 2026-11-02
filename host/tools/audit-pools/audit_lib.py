"""Audit helpers: parse the case dump of
mpfr-check (CFT_MPFR_DUMP_CASES=1) and give the operand sets per function.

Imported by the other scripts of this directory; run on its own it only
checks that the golden model imports.  The functions: parse_dump(path) reads
a case dump of mpfr-check (CFT_MPFR_DUMP_CASES=1) into cases[format][function],
operands / first_operands / pairs give the operand sets of a function, and
describe(fmt, bits) writes an operand in words.
"""
import collections
import os
import re
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "python"))
sys.path.insert(0, os.path.join(REPO, "host", "tools"))

from cft_golden import formats as F          # noqa: E402
from cft_golden import softfloat as sf       # noqa: E402
from cft_golden import vectors as V          # noqa: E402
from cft_golden import transcend as T        # noqa: E402

FMTS = {"fp32": F.FP32, "fp64": F.FP64, "fp128": F.FP128, "fp256": F.FP256}
FNS = T.TRANSCEND_FNS
ARITY = T.TRANSCEND_ARITY
INTARG = T.TRANSCEND_INTARG


def parse_dump(path):
    """cases[fmt][fn] = list of (a, b, n, directed, pass_letter, i, j)"""
    cases = collections.defaultdict(lambda: collections.defaultdict(list))
    with open(path) as fh:
        for line in fh:
            if not line.startswith("C "):
                continue
            _, fmt, fn, ps, i, j, d, a, b, n = line.split()[:10]
            cases[fmt][fn].append((
                int(a, 16), None if b == "-" else int(b, 16),
                None if n == "-" else int(n), d == "1", ps, int(i), int(j)))
    return cases


def operands(cases, fmt, fn, directed_only=True):
    """The set of floating operands (first and second) a function is asked
    at, directed ones only by default."""
    s = set()
    for a, b, n, d, ps, i, j in cases[fmt][fn]:
        if directed_only and not d:
            continue
        s.add(a)
        if b is not None:
            s.add(b)
    return s


def first_operands(cases, fmt, fn, directed_only=True):
    return {a for a, b, n, d, ps, i, j in cases[fmt][fn]
            if d or not directed_only}


def pairs(cases, fmt, fn, directed_only=True):
    return {(a, b if b is not None else n) for a, b, n, d, ps, i, j
            in cases[fmt][fn] if d or not directed_only}


def describe(fmt, bits):
    """A readable value: sign, special class or m*2^e (m odd), and the
    floor(log2|x|)."""
    u = sf.unpack(fmt, bits)
    if u.kind == sf.NAN:
        return ("sNaN" if u.signaling else "qNaN") + ("-" if u.sign else "+") + \
            "(%x)" % bits
    if u.kind == sf.INF:
        return ("-" if u.sign else "+") + "inf"
    if u.kind == sf.ZERO:
        return ("-" if u.sign else "+") + "0"
    m, e = u.m, u.e
    while m % 2 == 0:
        m //= 2
        e += 1
    vexp = u.e + u.m.bit_length() - 1
    return "%s%d*2^%d [e=%d]" % ("-" if u.sign else "+", m, e, vexp) \
        if m < (1 << 20) else "%s0x%x*2^%d [e=%d]" % ("-" if u.sign else "+",
                                                       m, e, vexp)
