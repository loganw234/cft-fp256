# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The step graph, lowered: shared, folded once, and given its bank.

Three things happen here and nothing else, because the language allows
nothing else (docs/ROADMAP.md, step 3: literal evaluation):

1. SHARING. The step is hash-consed in the graph's node order. A node's
   key is its op and its operands' keys, the two operands of add and
   mul and fma's two multiplicands in a fixed order - the plan allows
   commuting + and *, and verifier-P1 measured both, and fma's
   multiplicands swapped, bit for bit with NaN payloads. Two nodes with
   one key give the same bits and raise the same flags, and FLAGS is an
   OR, so one evaluation is the run's value and FLAGS. The node kept is
   the first, with its own operand order.

2. ONE FOLD. A neg whose every use is a multiplicand of an fma or a mul
   whose OTHER multiplicand is a const entry c is removed: each use
   reads the neg's operand t instead, and a bank slot holding flip(c) -
   c's encoding with its sign bit inverted, which is -RN(c) and not
   RN(-c). Bit for bit and flag for flag under every attribute:
   * c is a constant, so never a NaN; neg(t) is a NaN exactly when t
     is, signalling exactly when t is (neg flips the sign bit and
     nothing else, 754 5.5.1), and raises nothing;
   * with a NaN operand fma and mul return the one canonical quiet NaN
     (softfloat.py: "any NaN in -> the one canonical qNaN out") and
     raise invalid exactly when an operand signals, in both forms;
   * otherwise c x (-t) and (-c) x t have one magnitude and one sign,
     zero products included, and inf x 0 and inf - inf fall alike: one
     exact value meets one rounding, so the result, 754 6.3's sign of an
     exact zero sum and every flag agree;
   * the slot holds the FLIP because RN(-c) is not -RN(c) under rdn and
     rup when c is inexact; an h-scaled c's flip halves exactly with it.
   python/tests/test_cftc.py holds the identity over specials, all five
   attributes and all four formats. It is done only while the bank has
   room for the flips (512 slots); past that the neg is emitted.

3. THE BANK. h-scaled entries and their flips by factor descending (a
   flip's factor is -f; an entry before a flip of equal factor), then
   the other const entries and their flips by exact value ascending (an
   entry before a flip of equal value), then every param in declaration
   order. That is gen_odes.py's classic order for the three references.
   Only slots an instruction addresses are in it. The halved bank halves
   every h-scaled slot exactly and leaves every other one alone.
   Then, where the step divides or takes a root (C4), the WORDS its
   routines read (cft_golden/routines.py): one slot for each distinct
   bit pattern, the division's words first in divfull's own order, then
   the root's that are new - raw encodings at the format, an infinity,
   -0, NaNs and integers among them, which no constant of the language
   can be. A word is never h-scaled, never halved, never a param and
   never shared with a const slot (a const slot may be h-scaled or a run
   value; a word may not). They come after the params, so a step's const,
   flip and param slots are where they would be without routines. A step
   with call loops (callloop.py) adds the loop's words the same way: its
   step, the word 1, here, and each loop's record base once the
   allocation is chosen (callloop.finish).
   The bank holds 512 on every device: params, addressed constants and
   words past it are refused `bank-capacity`, the language's own name for
   the limit, here for the cause the checker cannot see; and the fold
   adds a flip only while there is room with the words counted.

Nothing here reads an encoding to decide anything - only exact values
and structure - so a system's instruction words are the same at every
format, unless it divides or takes a root: a routine's words are its
format's (its Newton passes, its masks and biases), so are its bank
words, and the image with them. Encodings decide only the bank's bytes
and halving-underflow.
"""

from fractions import Fraction

from cft_golden import chars
from cft_golden import softfloat as sf

from .refusals import InternalError, refuse

BANK_MAX = 512           # a constant index is nine bits (KADDR_KX)


class LNode:
    __slots__ = ("op", "args", "labels", "origin")

    def __init__(self, op, args, labels, origin):
        self.op = op
        self.args = tuple(args)
        self.labels = list(labels)      # the graph's labels it carries
        self.origin = list(origin)      # the graph nodes it stands for

    @property
    def label(self):
        return self.labels[0] if self.labels else None


class Slot:
    """One bank slot: a const entry, a const entry's flip, a param, or a
    routine's word."""
    __slots__ = ("kind", "index", "exact", "factor", "bits", "flags",
                 "default", "names")

    def __init__(self, kind, index, exact, factor, bits, flags,
                 default=True, names=None):
        self.kind = kind            # "const", "flip", "param" or "word"
        self.index = index          # the const's or the param's index
        self.exact = exact          # the exact value the slot stands for
        self.factor = factor        # h-factor, or None
        self.bits = bits
        self.flags = flags          # the one rounding's flags
        self.default = default      # a param at its default
        self.names = names          # a word's [(routine, word name)]


class Lowered:
    """The lowered step: nodes in the graph's order, the outputs, the
    bank and its map from refs to slots."""

    def __init__(self, graph, nodes, outs, slots, shared, folds):
        self.graph = graph
        self.nodes = nodes
        self.outs = outs
        self.slots = slots
        self.shared = shared
        self.folds = folds
        self.slot_of = {}
        for k, s in enumerate(slots):
            if s.kind == "word":
                self.slot_of[("w", s.bits)] = k
                continue
            key = {"const": "c", "flip": "f", "param": "p"}[s.kind]
            self.slot_of[(key, s.index)] = k
        self.h_slots = [k for k, s in enumerate(slots)
                        if s.factor is not None and s.factor != 0]
        self.half_bits = None           # set by halve()
        self.routines = []              # set by lower(): div, sqrt present

    @property
    def fmt(self):
        return self.graph.fmt

    def bank_values(self):
        return [s.bits for s in self.slots]

    def bank_bytes(self, values=None):
        esz = self.fmt.width // 8
        vals = self.bank_values() if values is None else values
        return b"".join(v.to_bytes(esz, "little") for v in vals)

    def half_bank_bytes(self):
        return None if self.half_bits is None else \
            self.bank_bytes(self.half_bits)

    def op_counts(self):
        counts = {}
        for nd in self.nodes:
            counts[nd.op] = counts.get(nd.op, 0) + 1
        return counts


def _canon(op, args):
    if op in ("add", "mul"):
        return tuple(sorted(args))
    if op == "fma":
        return tuple(sorted(args[:2])) + args[2:]
    return args


def share(graph):
    """-> (nodes, outs, merged): the step hash-consed (module docstring)."""
    nodes, keyed, remap = [], {}, {}
    merged = 0
    for k, (op, args, label) in enumerate(graph.nodes):
        a = tuple(remap[r[1]] if r[0] == "n" else r for r in args)
        key = (op, _canon(op, a))
        j = keyed.get(key)
        if j is None:
            j = len(nodes)
            keyed[key] = j
            nodes.append(LNode(op, a, [label] if label else [], [k]))
        else:
            merged += 1
            nodes[j].origin.append(k)
            if label:
                nodes[j].labels.append(label)
        remap[k] = ("n", j)
    outs = [remap[r[1]] if r[0] == "n" else r for r in graph.outs]
    return nodes, outs, merged


def fold(graph, nodes, outs, n_words=0):
    """-> (nodes, outs, folds): the one fold, applied in the graph's node
    order while the bank has room, the routines' n_words counted (module
    docstring)."""
    users = [[] for _ in nodes]
    for j, nd in enumerate(nodes):
        for pos, r in enumerate(nd.args):
            if r[0] == "n":
                users[r[1]].append((j, pos))
    is_out = {r[1] for r in outs if r[0] == "n"}
    cuse = [0] * len(graph.const)
    fuse = [0] * len(graph.const)
    for nd in nodes:
        for r in nd.args:
            if r[0] == "c":
                cuse[r[1]] += 1
    for r in outs:
        if r[0] == "c":
            cuse[r[1]] += 1
    n_param = len(graph.param)

    def bank_size():
        return n_param + n_words + sum(1 for u in cuse if u) + \
            sum(1 for u in fuse if u)

    dead, folds = set(), []
    for j, nd in enumerate(nodes):
        if nd.op != "neg" or j in is_out or not users[j]:
            continue
        sites = []
        for c, pos in users[j]:
            cn = nodes[c]
            if cn.op not in ("fma", "mul") or pos not in (0, 1):
                break
            other = cn.args[1 - pos]
            if other[0] != "c":
                break
            sites.append((c, pos, other[1]))
        else:
            for _c, _p, i in sites:
                cuse[i] -= 1
                fuse[i] += 1
            if bank_size() > BANK_MAX:
                for _c, _p, i in sites:
                    cuse[i] += 1
                    fuse[i] -= 1
                continue
            t = nd.args[0]
            for c, pos, i in sites:
                args = list(nodes[c].args)
                args[pos] = t
                args[1 - pos] = ("f", i)
                nodes[c].args = tuple(args)
            dead.add(j)
            folds.append({"neg": j, "consts": sorted({i for _c, _p, i
                                                      in sites}),
                          "uses": len(sites), "labels": list(nd.labels)})
    if not dead:
        return nodes, outs, folds
    renum, kept = {}, []
    for j, nd in enumerate(nodes):
        if j in dead:
            continue
        renum[j] = len(kept)
        kept.append(nd)
    for nd in kept:
        nd.args = tuple(("n", renum[r[1]]) if r[0] == "n" else r
                        for r in nd.args)
    outs = [("n", renum[r[1]]) if r[0] == "n" else r for r in outs]
    for f in folds:
        f["neg_origin"] = nodes[f["neg"]].origin[0]
        del f["neg"]
    return kept, outs, folds


def layout(graph, nodes, outs, param_bits=None, words=()):
    """-> [Slot]: the bank (module docstring). `param_bits` maps a param's
    index to (bits, flags, exact) for a run value given in its place;
    `words` are the routines' word slots, which go last."""
    used_c, used_f = set(), set()
    for nd in nodes:
        for r in nd.args:
            if r[0] == "c":
                used_c.add(r[1])
            elif r[0] == "f":
                used_f.add(r[1])
    for r in outs:
        if r[0] == "c":
            used_c.add(r[1])
    sign = graph.fmt.sign_mask
    entries = []
    for i in sorted(used_c):
        exact, factor, bits, flags = graph.const[i]
        entries.append(Slot("const", i, exact, factor, bits, flags))
    for i in sorted(used_f):
        exact, factor, bits, flags = graph.const[i]
        entries.append(Slot("flip", i, -exact,
                            None if factor is None else -factor,
                            bits ^ sign, flags))

    def h_scaled(s):
        return s.factor is not None and s.factor != 0
    rank = {"const": 0, "flip": 1}
    hs = sorted((s for s in entries if h_scaled(s)),
                key=lambda s: (-s.factor, rank[s.kind], s.index))
    plain = sorted((s for s in entries if not h_scaled(s)),
                   key=lambda s: (s.exact, rank[s.kind], s.index))
    params = []
    for i, (_name, exact, bits, flags) in enumerate(graph.param):
        if param_bits and i in param_bits:
            b, fl, ex = param_bits[i]
            params.append(Slot("param", i, ex, None, b, fl, default=False))
        else:
            params.append(Slot("param", i, exact, None, bits, flags))
    slots = hs + plain + params + list(words)
    if len(slots) > BANK_MAX:
        raise InternalError(f"{len(slots)} bank slots: the fold adds a flip "
                            f"only while there is room, L1 refuses more "
                            f"than {BANK_MAX} params and constants, and "
                            f"lower() refuses the routines' words past it")
    return slots


def routine_words(graph, nodes, loop_words=()):
    """[Slot]: the words the step's routines read, one slot a bit pattern
    - the division's words in divfull's order, then the root's that are
    new, then the call loop's that are new (module docstring) - each
    naming every (routine, word) it is; a call loop's as ("loop", name)."""
    from cft_golden import routines as R
    slots, at = [], {}

    def add(op, name, bits):
        if bits not in at:
            at[bits] = len(slots)
            slots.append(Slot("word", None, None, None, bits, 0, names=[]))
        slots[at[bits]].names.append((op, name))
    for op in ("div", "sqrt"):
        if not any(nd.op == op for nd in nodes):
            continue
        f = R.fragment(op, graph.fmt, graph.rnd)
        for name, bits in f.words.items():
            add(op, name, bits)
    for name, bits in loop_words:
        add("loop", name, bits)
    return slots


def halve(low, source=None):
    """The halved bank: each h-scaled slot exactly halved, or
    halving-underflow. Exactness is the multiply's own flags - zero means
    the product needed no rounding at all."""
    fmt = low.fmt
    half, _ = chars._round_rational(fmt, 0, 1, 2, sf.RND_RNE)
    out = list(low.bank_values())
    for k in low.h_slots:
        res, fl = sf.mul(fmt, out[k], half, sf.RND_RNE)
        if fl:
            s = low.slots[k]
            refuse("halving-underflow",
                   f"bank slot {k} ({_slot_words(low, s)}) is "
                   f"0x{out[k]:0{fmt.width // 4}x} in {fmt.name}, and its "
                   f"half is not exact there, so no step-halving bank can "
                   f"hold it", source=source)
        out[k] = res
    low.half_bits = out
    return out


def _slot_words(low, s):
    from cft_golden.lang import constants as K
    if s.kind == "param":
        return f"param {low.graph.param[s.index][0]}"
    exact, factor = low.graph.const[s.index][:2]
    name = (f"{K.h_form(factor)} = {K.literal(exact)}" if factor is not None
            else K.literal(exact))
    return f"the flip of {name}" if s.kind == "flip" else name


def lower(graph, param_bits=None, source=None, loop_words=()):
    """-> Lowered: shared, folded once, and given its bank - the routines'
    words in it, and a call loop's step word (`loop_words`,
    callloop.WORDS), or `bank-capacity` where they do not fit."""
    nodes, outs, merged = share(graph)
    words = routine_words(graph, nodes, loop_words)
    if words:
        used = {r[1] for nd in nodes for r in nd.args if r[0] == "c"} | \
            {r[1] for r in outs if r[0] == "c"}
        need = len(graph.param) + len(used) + len(words)
        if need > BANK_MAX:
            ops = [op for op in ("div", "sqrt")
                   if any(nd.op == op for nd in nodes)]
            loop = " and the call loop it runs some of them in" \
                if loop_words else ""
            refuse("bank-capacity",
                   f"{len(graph.param)} params, {len(used)} constants and "
                   f"{len(words)} words of the routine"
                   f"{'s' if len(ops) > 1 else ''} the compiler inlines for "
                   f"{' and '.join(ops)}{loop} come to {need}: the bank "
                   f"holds {BANK_MAX} on every device", source=source)
    nodes, outs, folds = fold(graph, nodes, outs, len(words))
    slots = layout(graph, nodes, outs, param_bits, words)
    low = Lowered(graph, nodes, outs, slots, merged, folds)
    low.routines = [op for op in ("div", "sqrt")
                    if any(nd.op == op for nd in nodes)]
    for f in folds:
        f["slots"] = [low.slot_of[("f", i)] for i in f["consts"]]
    return low


def exact_value(fmt, bits):
    """The exact value of a finite encoding, as a Fraction."""
    u = sf.unpack(fmt, bits)
    if u.kind in (sf.INF, sf.NAN):
        raise InternalError("not a finite encoding")
    if u.kind == sf.ZERO:
        return Fraction(0)
    v = Fraction(u.m) * (Fraction(2) ** u.e)
    return -v if u.sign else v
