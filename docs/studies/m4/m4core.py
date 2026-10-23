# M4 design study: the model's core (scratch; not the tree's code, and
# nothing in the tree imports it).
#
# M2's core (docs/studies/m2/m2core.py) is imported, not copied: its SSA
# builder in C4's Fragment shape (hash-consing through routines.simplify),
# its counted error-free transformations, its encodings, and frac(), which
# reads an mpmath value through the raw _mpf_ tuple (to_man_exp is not
# called). This file adds what M4 needs and M2 did not:
#   * TWO inputs: atan2's y and x are the fragment's ("a", "b"), y first as
#     C and transcend.py have it, so a fragment runs on seq.py through
#     routines.program / routines.run with y in r0 and x in r1;
#   * an evaluator over those inputs (M2's passes one argument to every
#     "in" source);
#   * the constants: pi in words, atan(k/N) in words, the Taylor
#     coefficients of atan(s)/s.

import sys
import pathlib
from fractions import Fraction

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
# M2's directory goes LAST: it holds scripts named as this model's are
# (census.py, specials.py, rate.py, ...), and a script here that imports
# one of its neighbours must get this directory's (the first plants run
# imported M2's census and failed by name: the study's 3.6)
sys.path.append(str(HERE.parent / "m2"))

import mpmath                                            # noqa: E402

from m2core import (Frag, FORMATS, sf, asm, routines, enc, enc_exact,  # noqa: E402,F401
                    dec, pow2_bits, words_of, frac, RNE, RTZ, RDN, RUP,
                    RMM, ATTRS, A, B, C, ROOT)

CONST_BITS = 4000


class Frag2(Frag):
    """M2's Frag with named inputs: ("a",) for the unary functions and
    ("a", "b") = (y, x) for atan2."""

    def __init__(self, fmt, rnd, name, inputs=("a",)):
        super().__init__(fmt, rnd, name)
        self.inputs = tuple(inputs)

    def to_fragment(self):
        return routines.Fragment("m4:" + self.name, self.fmt, self.rnd,
                                 self.inputs, self.body, self.result,
                                 self.flags, self.words, "specialised")


def run_body2(fmt, body, words, inp):
    """Run a body on one lane; `inp` maps an input's name to its bits."""
    vals = []

    def get(s):
        if s[0] == "v":
            return vals[s[1]]
        if s[0] == "in":
            return inp[s[1]]
        return words[s[1]]
    for op, r, srcs in body:
        ops = {A: 0, B: 0, C: 0}
        for s, fld in zip(srcs, asm.OP_FIELDS[op]):
            ops[fld] = get(s)
        res, _fl = sf.compute(fmt, op, ops[A], ops[B], ops[C],
                              RNE if r is None else r)
        vals.append(res)
    return vals, get


def lane(f, args):
    """args: the input bits in f.inputs' order -> {name: bits}."""
    if not isinstance(args, (tuple, list)):
        args = (args,)
    return dict(zip(f.inputs, args))


def evaluate2(f, args, want=None, full=False):
    """(result, flag word, {probe: bits}) of one lane; `args` the input
    bits (one, or (y, x) for atan2). full=True runs the unpruned body."""
    if full and hasattr(f, "all_body"):
        body, _ph, probes = f.all_body
        res_ref, fl_ref = f.all_result, f.all_flags
    else:
        body, probes = f.body, f.probes
        res_ref, fl_ref = f.result, f.flags
    _vals, get = run_body2(f.fmt, body, f.allwords, lane(f, args))
    out = {}
    if want:
        for k in want:
            if k in probes:
                out[k] = get(probes[k])
    return get(res_ref), get(fl_ref), out


# ---- constants -----------------------------------------------------------

_PI = None


def pi_frac():
    global _PI
    if _PI is None:
        with mpmath.workprec(CONST_BITS):
            _PI = frac(+mpmath.pi)
    return _PI


_ATAN = {}


def atan_frac(q):
    """atan(q) for a rational q, to CONST_BITS bits, as a Fraction."""
    q = Fraction(q)
    if q not in _ATAN:
        with mpmath.workprec(CONST_BITS):
            _ATAN[q] = frac(mpmath.atan(mpmath.mpf(q.numerator) / q.denominator))
    return _ATAN[q]


def atan_coef(k):
    """The Taylor coefficient of atan(s)/s in z = s^2: (-1)^k / (2k+1)."""
    return Fraction(-1 if k % 2 else 1, 2 * k + 1)
