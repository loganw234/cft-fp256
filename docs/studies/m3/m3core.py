# M3 design study: the model's core (scratch; not the tree's code, and
# nothing in the tree imports it).
#
# Unlike M1's, M2's and M4's models this one builds its fragments on the
# TREE's builder, python/cft_golden/mathlib.py's Build, and on M1's built
# helpers there (_log_reduce, _table, _scale, the constants), imported and
# never edited: M1's exp2 and log2 are built and verified, so the pow core
# reuses their code rather than a model's copy of it. What is new is in
# m3pow.py. This file holds the paths, the encodings and the golden calls.

import sys
import pathlib
from fractions import Fraction

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "python" / "tests"))

import mpmath                                            # noqa: E402

from cft_golden import mathlib as ml                     # noqa: E402
from cft_golden import routines, seq, transcend as tr    # noqa: E402,F401
from cft_golden import softfloat as sf                   # noqa: E402
from cft_golden.formats import FP32, FP64, FP128, FP256  # noqa: E402

FORMATS = {"fp32": FP32, "fp64": FP64, "fp128": FP128, "fp256": FP256}
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
ATTRS = (RNE, RTZ, RDN, RUP, RMM)
AN = sf.RND_NAMES
FNS = ("pow", "powr", "pown", "rootn", "compound")
INTARG = ("pown", "rootn", "compound")


def dec(fmt, bits):
    """The exact Fraction of a finite encoding."""
    return ml._dec(fmt, bits)


def enc(fmt, q, rnd=RNE):
    """The encoding of the rational q rounded once under rnd."""
    return ml._enc(fmt, q, rnd)


def val(fmt, sign, m, e):
    """The encoding of (-1)^sign m 2^e, exactly, or None."""
    bits, flags = sf.round_pack(fmt, sign, m, e, RNE)
    return None if flags else bits


def golden(fmt, fn, lane, rnd):
    """transcend.py's (bits, flags) for one lane: (x, y) for pow and powr,
    (x, n) for the three of an integer operand."""
    x, b = lane
    if fn in INTARG:
        return tr.compute(fmt, fn, x, 0, rnd, b)
    return tr.compute(fmt, fn, x, b, rnd)


def frac_mp(v):
    """An mpf as the exact Fraction it is, read from the raw _mpf_ tuple
    (mpmath's to_man_exp is not called: the brief)."""
    sign, man, ex, _bc = v._mpf_
    q = Fraction(int(man)) * (Fraction(2) ** int(ex))
    return -q if sign else q


def to_mp(q):
    return mpmath.mpf(q.numerator) / q.denominator


def true_value(fmt, fn, lane, prec=None):
    """The function's value on a main-path lane as an mpf at 4p + 200 bits
    (the brief's precision): pow and powr |x|^y with pow's sign, pown x^n,
    rootn x^(1/n) with x's sign for odd n, compound (1 + x)^n."""
    p = fmt.prec
    prec = prec or 4 * p + 200
    x, b = lane
    with mpmath.workprec(prec):
        X = to_mp(dec(fmt, x))
        if fn in ("pow", "powr"):
            Y = to_mp(dec(fmt, b))
            mag = mpmath.power(abs(X), Y)
            q = dec(fmt, b)
            odd = q.denominator == 1 and q.numerator % 2 != 0
            return -mag if (X < 0 and odd) else +mag
        n = b
        if fn == "pown":
            mag = mpmath.power(abs(X), n)
            return -mag if (X < 0 and n % 2) else +mag
        if fn == "rootn":
            mag = mpmath.power(abs(X), mpmath.mpf(1) / n)
            return -mag if X < 0 else +mag
        u = dec(fmt, x) + 1                      # compound: 1 + x exactly
        return mpmath.power(to_mp(u), n)


def lg(v):
    v = abs(float(v))
    return float("-inf") if v == 0 else __import__("math").log2(v)
