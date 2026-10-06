# M1 design study, phase 1: the model's core (scratch; not the tree's code).
#
# A routine is built as straight-line SSA in C4's Fragment shape
# (cft_golden/routines.py): instruction i defines value i, each
# (opcode, rnd, srcs), a src ("in", name), ("v", i) or ("w", name).
# Words are raw bank encodings. The builder hash-conses instructions by
# (opcode, attribute, operands) as cftc's inliner shares them, and applies
# routines.simplify's rules. The evaluator runs a body through
# softfloat.compute exactly as seq.py's ALU does, one lane at a time.

import sys
from fractions import Fraction

import pathlib                                  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "python"))

from cft_golden import softfloat as sf          # noqa: E402
from cft_golden import asm, routines            # noqa: E402
from cft_golden.formats import FpFormat         # noqa: E402

A, B, C = "ra", "rb", "rc"
RNE, RTZ, RDN, RUP, RMM = (sf.RND_RNE, sf.RND_RTZ, sf.RND_RDN, sf.RND_RUP,
                           sf.RND_RMM)
ROUNDED = (sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL)


class Frag:
    """A routine under construction: body, words, probes, phases."""

    def __init__(self, fmt: FpFormat, rnd: int, name: str):
        self.fmt = fmt
        self.rnd = rnd
        self.name = name
        self.body = []          # (op, rnd, srcs)
        self.phase_of = []      # the phase each instruction was emitted in
        self.words = {}         # name -> bits (pruned to the used ones)
        self.word_of = {}       # bits -> name
        self.allwords = {}      # every word ever made, for evaluation
        self.keyed = {}
        self.probes = {}        # name -> ref, for the analysis
        self.phase = "setup"
        self.inputs = ("a",)
        self.result = None
        self.flags = None

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

    # the opcodes, operands in OP_FIELDS order
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
        """Drop values neither the result nor the flags reach (the
        specialisation's last rule); renumber; keep the probes that
        survive."""
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
        self.dropped_probes = {k: v for k, v in self.probes.items()
                               if v[0] == "v" and v not in ren}
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
        return routines.Fragment("m1:" + self.name, self.fmt, self.rnd,
                                 self.inputs, self.body, self.result,
                                 self.flags, self.words, "specialised")


def evaluate(f: Frag, xa, want=None, full=False):
    """Run the body on one lane, x = xa. -> (result, flag word, {probe:
    bits}). full=True runs the unpruned body (every probe), whose result
    and flags are the same values."""
    fmt = f.fmt
    if full and hasattr(f, "all_body"):
        body, _ph, probes = f.all_body
        res_ref, fl_ref = f.all_result, f.all_flags
    else:
        body, probes = f.body, f.probes
        res_ref, fl_ref = f.result, f.flags
    vals = []
    words = f.allwords

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
    out = {}
    if want:
        for k in want:
            if k in probes:
                out[k] = get(probes[k])
    return get(res_ref), get(fl_ref), out


# ---- encodings -----------------------------------------------------------

def enc(fmt, value, rnd=RNE):
    """bits of a Fraction/int value rounded once under rnd (0 is +0)."""
    v = Fraction(value)
    if v == 0:
        return 0
    sign = 1 if v < 0 else 0
    v = abs(v)
    n, d = v.numerator, v.denominator
    # m * 2^e with enough guard bits, sticky folded in
    e = n.bit_length() - d.bit_length() - fmt.prec - 8
    if e >= 0:
        q, r = divmod(n, d << e)
    else:
        q, r = divmod(n << -e, d)
    m = (q << 1) | (1 if r else 0)
    bits, _fl = sf.round_pack(fmt, sign, m, e - 1, rnd)
    return bits


def enc_exact(fmt, value):
    v = Fraction(value)
    bits = enc(fmt, v)
    assert dec(fmt, bits) == v, (fmt.name, v)
    return bits


def dec(fmt, bits):
    """The exact value of a finite encoding, as a Fraction."""
    u = sf.unpack(fmt, bits)
    if u.kind == sf.ZERO:
        return Fraction(0)
    if u.kind in (sf.INF, sf.NAN):
        raise ValueError("not finite")
    v = Fraction(u.m) * (Fraction(2) ** u.e)
    return -v if u.sign else v


def pow2_bits(fmt, k):
    return enc_exact(fmt, Fraction(2) ** k)
