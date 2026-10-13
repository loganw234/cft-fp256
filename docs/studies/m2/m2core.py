# M2 design study: the model's core (scratch; not the tree's code, and
# nothing in the tree imports it).
#
# A routine is built as straight-line SSA in C4's Fragment shape
# (cft_golden/routines.py): instruction i defines value i, each
# (opcode, rnd, srcs), a src ("in", name), ("v", i) or ("w", name). Words
# are raw bank encodings. The builder hash-conses instructions by
# (opcode, attribute, operands), as cftc's inliner shares them across a
# step, and applies routines.simplify's rules. The evaluator runs a body
# through softfloat.compute exactly as seq.py's ALU does, one lane at a
# time. It is M1's m1core.py, extended: the opcodes M1 did not use (MIN,
# MAX, COPYSIGN), the error-free transformations as builder methods that
# count themselves, and values read from mpmath through the raw _mpf_
# tuple (mpmath's to_man_exp is not called: its unsigned default is
# deprecated in mpmath 1.4).

import sys
import pathlib
from fractions import Fraction

sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import softfloat as sf          # noqa: E402
from cft_golden import asm, routines            # noqa: E402
from cft_golden.formats import FORMATS, FpFormat  # noqa: E402,F401

A, B, C = "ra", "rb", "rc"
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
ATTRS = (RNE, RTZ, RDN, RUP, RMM)
ROUNDED = (sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL)


def frac(v):
    """An mpmath mpf as the exact Fraction it is, read from its raw tuple
    (sign, mantissa, exponent, bitcount): no rounding happens here."""
    sign, man, ex, _bc = v._mpf_
    if not man and ex:
        raise ValueError(f"{v} is not a finite number")
    q = Fraction(int(man)) * (Fraction(2) ** int(ex))
    return -q if sign else q


class Frag:
    """A routine under construction: body, words, probes, phases, counts
    of the error-free transformations."""

    def __init__(self, fmt: FpFormat, rnd: int, name: str):
        self.fmt = fmt
        self.rnd = rnd
        self.name = name
        self.body = []          # (op, rnd, srcs)
        self.phase_of = []
        self.words = {}         # name -> bits (pruned to the used ones)
        self.word_of = {}       # bits -> name
        self.allwords = {}
        self.keyed = {}
        self.probes = {}
        self.phase = "setup"
        self.inputs = ("a",)
        self.result = None
        self.flags = None
        self.meta = {"two_sum": 0, "fast_two_sum": 0, "two_prod": 0}

    # ---- words -------------------------------------------------------
    def w(self, bits, name=None):
        bits &= (1 << self.fmt.width) - 1
        if bits in self.word_of:
            return ("w", self.word_of[bits])
        nm = name or f"K{len(self.words)}"
        while nm in self.words:
            nm += "'"
        self.words[nm] = bits
        self.word_of[bits] = nm
        self.allwords[nm] = bits
        return ("w", nm)

    def wv(self, value, rnd=RNE, name=None):
        """A word holding the exact rational `value` rounded once."""
        return self.w(enc(self.fmt, value, rnd), name)

    def wx(self, value, name=None):
        """A word holding `value` exactly (refused if the format cannot)."""
        return self.w(enc_exact(self.fmt, value), name)

    def wi(self, v, name=None):
        """An integer word, two's complement on the W-bit encoding."""
        return self.w(v & ((1 << self.fmt.width) - 1), name)

    def bits_of(self, s):
        return self.allwords[s[1]] if s[0] == "w" else None

    # ---- instructions ------------------------------------------------
    def ins(self, op, srcs, rnd=None):
        if op in ROUNDED and rnd is None:
            rnd = RNE
        if op not in ROUNDED:
            rnd = None
        srcs = tuple(srcs)
        same = routines.simplify(op, srcs, self.bits_of, self.fmt.sign_mask)
        if same is not None:
            return same
        key = (op, rnd, srcs)
        if key in self.keyed:
            return self.keyed[key]
        self.body.append(key)
        self.phase_of.append(self.phase)
        ref = ("v", len(self.body) - 1)
        self.keyed[key] = ref
        return ref

    def fma(self, a, b, c, rnd=RNE):
        return self.ins(sf.OP_FMA, (a, b, c), rnd)

    def add(self, a, c, rnd=RNE):
        return self.ins(sf.OP_ADD, (a, c), rnd)

    def sub(self, a, c, rnd=RNE):
        return self.ins(sf.OP_SUB, (a, c), rnd)

    def mul(self, a, b, rnd=RNE):
        return self.ins(sf.OP_MUL, (a, b), rnd)

    def neg(self, a):
        return self.ins(sf.OP_NEG, (a,))

    def fabs(self, a):
        return self.ins(sf.OP_ABS, (a,))

    def copysign(self, a, b):
        return self.ins(sf.OP_COPYSIGN, (a, b))

    def fmin(self, a, b):
        return self.ins(sf.OP_MIN, (a, b))

    def fmax(self, a, b):
        return self.ins(sf.OP_MAX, (a, b))

    def sel(self, a, b, c):
        """c ? a : b (softfloat.select: c's magnitude not zero)."""
        return self.ins(sf.OP_SELECT, (a, b, c))

    def cmplt(self, a, b):
        return self.ins(sf.OP_CMPLT, (a, b))

    def cmple(self, a, b):
        return self.ins(sf.OP_CMPLE, (a, b))

    def cmpeq(self, a, b):
        return self.ins(sf.OP_CMPEQ, (a, b))

    def iand(self, a, b):
        return self.ins(sf.OP_IAND, (a, b))

    def ior(self, a, b):
        return self.ins(sf.OP_IOR, (a, b))

    def ixor(self, a, b):
        return self.ins(sf.OP_IXOR, (a, b))

    def iadd(self, a, b):
        return self.ins(sf.OP_IADD, (a, b))

    def isub(self, a, b):
        return self.ins(sf.OP_ISUB, (a, b))

    def ishl(self, a, b):
        return self.ins(sf.OP_ISHL, (a, b))

    def ishr(self, a, b):
        return self.ins(sf.OP_ISHR, (a, b))

    def icmplt(self, a, b):
        return self.ins(sf.OP_ICMPLT, (a, b))

    def recip_seed(self, a):
        return self.ins(sf.OP_RECIP_SEED, (a,))

    # ---- the error-free transformations, counted -----------------------
    def two_sum(self, a, b):
        """(s, e), s + e = a + b exactly, any order: Knuth's TwoSum, 6."""
        self.meta["two_sum"] += 1
        s = self.add(a, b)
        a1 = self.sub(s, b)
        b1 = self.sub(s, a1)
        da = self.sub(a, a1)
        db = self.sub(b, b1)
        return s, self.add(da, db)

    def fast_two_sum(self, a, b):
        """(s, e), s + e = a + b exactly when a's exponent is at least b's
        (or a is zero... the caller's claim, checked by the model's exact
        audit): Dekker's Fast2Sum, 3."""
        self.meta["fast_two_sum"] += 1
        s = self.add(a, b)
        z = self.sub(s, a)
        return s, self.sub(b, z)

    def two_prod(self, a, b, na=None):
        """(p, -e) with p + e = a * b exactly: MUL and one FMA. The low
        word comes back NEGATED, -e = p - a*b = fma(-a, b, p), so that one
        FMA suffices; `na` is -a where the caller has it."""
        self.meta["two_prod"] += 1
        p = self.mul(a, b)
        if na is None:
            na = self.neg(a)
        return p, self.fma(na, b, p)

    # ---- what is counted ---------------------------------------------
    def live_max(self):
        last = {}
        for i, (_op, _r, srcs) in enumerate(self.body):
            for s in srcs:
                if s[0] in ("v", "in"):
                    last[s] = i
        end = len(self.body)
        last[self.result] = end
        last[self.flags] = end
        live = {("in", n) for n in self.inputs if ("in", n) in last}
        best = len(live)
        for i, (_op, _r, srcs) in enumerate(self.body):
            for s in srcs:
                if s[0] in ("v", "in") and last.get(s) == i:
                    live.discard(s)
            if ("v", i) in last:
                live.add(("v", i))
            best = max(best, len(live))
        return best

    def prune(self):
        """Drop values neither the result nor the flags reach; renumber;
        keep the unpruned body for the analyses (full=True)."""
        need, stack = set(), [s for s in (self.result, self.flags)
                              if s[0] == "v"]
        while stack:
            v = stack.pop()
            if v not in need:
                need.add(v)
                stack.extend(s for s in self.body[v[1]][2] if s[0] == "v")
        keep = [i for i in range(len(self.body)) if ("v", i) in need]
        ren = {("v", i): ("v", k) for k, i in enumerate(keep)}
        body, phases = [], []
        for i in keep:
            op, r, srcs = self.body[i]
            body.append((op, r, tuple(ren.get(s, s) for s in srcs)))
            phases.append(self.phase_of[i])
        used = {s[1] for _op, _r, srcs in body for s in srcs if s[0] == "w"}
        self.all_body = (self.body, self.phase_of, dict(self.probes))
        self.all_result, self.all_flags = self.result, self.flags
        self.body, self.phase_of = body, phases
        self.result = ren.get(self.result, self.result)
        self.flags = ren.get(self.flags, self.flags)
        self.probes = {k: ren.get(v, v) for k, v in self.probes.items()
                       if v[0] != "v" or v in ren}
        self.words = {k: v for k, v in self.words.items() if k in used}
        self.word_of = {v: k for k, v in self.words.items()}
        return self

    def counts(self):
        out = {}
        for op, _r, _s in self.body:
            nm = sf.OP_NAMES[op]
            out[nm] = out.get(nm, 0) + 1
        return out

    def by_phase(self):
        out = {}
        for ph in self.phase_of:
            out[ph] = out.get(ph, 0) + 1
        return out

    def to_fragment(self):
        """The routine as routines.Fragment, for routines.program/run."""
        return routines.Fragment("m2:" + self.name, self.fmt, self.rnd,
                                 self.inputs, self.body, self.result,
                                 self.flags, self.words, "specialised")


def run_body(fmt, body, words, xa):
    vals = []

    def get(s):
        if s[0] == "v":
            return vals[s[1]]
        if s[0] == "in":
            return xa
        return words[s[1]]
    for op, r, srcs in body:
        ops = {A: 0, B: 0, C: 0}
        for s, fld in zip(srcs, asm.OP_FIELDS[op]):
            ops[fld] = get(s)
        res, _fl = sf.compute(fmt, op, ops[A], ops[B], ops[C],
                              RNE if r is None else r)
        vals.append(res)
    return vals, get


def evaluate(f: Frag, xa, want=None, full=False):
    """Run the body on one lane, x = xa. -> (result, flag word, {probe:
    bits}). full=True runs the unpruned body (every probe), whose result
    and flags are the same values."""
    if full and hasattr(f, "all_body"):
        body, _ph, probes = f.all_body
        res_ref, fl_ref = f.all_result, f.all_flags
    else:
        body, probes = f.body, f.probes
        res_ref, fl_ref = f.result, f.flags
    _vals, get = run_body(f.fmt, body, f.allwords, xa)
    out = {}
    if want:
        for k in want:
            if k in probes:
                out[k] = get(probes[k])
    return get(res_ref), get(fl_ref), out


# ---- encodings -----------------------------------------------------------

def enc(fmt, value, rnd=RNE):
    """The bits of the exact rational `value` rounded ONCE under rnd (zero
    is +0): eight guard bits and a sticky bit, then round_pack."""
    v = Fraction(value)
    if v == 0:
        return 0
    sign = 1 if v < 0 else 0
    n, d = abs(v).numerator, abs(v).denominator
    e = n.bit_length() - d.bit_length() - fmt.prec - 8
    q, r = divmod(n, d << e) if e >= 0 else divmod(n << -e, d)
    return sf.round_pack(fmt, sign, (q << 1) | (1 if r else 0), e - 1, rnd)[0]


def enc_exact(fmt, value):
    bits = enc(fmt, value)
    if dec(fmt, bits) != Fraction(value):
        raise ValueError(f"{value} is not exact at {fmt.name}")
    return bits


def dec(fmt, bits):
    """The exact value of a finite encoding, as a Fraction."""
    u = sf.unpack(fmt, bits)
    if u.kind == sf.ZERO:
        return Fraction(0)
    if u.kind in (sf.INF, sf.NAN):
        raise ValueError(f"{bits:#x} is not finite at {fmt.name}")
    v = Fraction(u.m) * (Fraction(2) ** u.e)
    return -v if u.sign else v


def pow2_bits(fmt, k):
    return enc_exact(fmt, Fraction(2) ** k)


def words_of(fmt, value, n):
    """`value` as n words, each the nearest to what is left."""
    v = Fraction(value)
    out = []
    for _ in range(n):
        b = enc(fmt, v)
        out.append(b)
        v -= dec(fmt, b)
    return out
