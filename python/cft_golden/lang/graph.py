# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The step graph: the checked form of one step.

The checker builds it, the interpreter runs its `step` section, the two
renderers write the intention-out from it, and the compiler (L2)
compiles it. Its bytes - canonical JSON, version 1, laid out below - are
a function of the system's meaning and never of how the source spelt
it, which is what makes "the canonical form parses back to the same
step graph, byte for byte" a check rather than a hope.

Layout (docs/LANGUAGE.md, "The step graph"), keys in this order:

  cftl_graph   1
  system       the system's name
  format       fp32, fp64, fp128 or fp256
  round        rne, rtz, rdn, rup or rmm - the one attribute
  state        [[name, length or null]], declaration order; the flat
               component order s0, s1, ... is this order with an
               array's components by index - the lane layout
  lane         [[name, default exact or null, bits or null]]
  param        [[name, default exact, bits, flags]]
  integrator   [name, h exact or null, options or null]
  const        [[exact, h-factor or null, bits, flags]], one entry per
               distinct (exact value, h-factor): the h-scaled first by
               factor descending, then the rest by value ascending
  field        a flow's right-hand sides once, over the state inputs:
               {"out": [ref], "nodes": [node]}; null for a map
  step         one step, the template expanded: {"out", "nodes"}

A node is [op, [ref], label or null]; a ref is sN (a state input), lN
(a lane param), pN (a param), cN (a const) or nN (a node of the same
section, always an earlier one). Exact values are Fractions written as
p/q or p; bits are 0x and the format's width in hex digits.

What makes the bytes canonical: one node per operator written (no
sharing - so an unlabelled node has exactly one use, asserted here);
constant subexpressions already folded; nodes ordered by an iterative
post-order walk from the outputs in state order, operands in order; no
set or hash order anywhere; ASCII, the key order above, no spaces, one
node a line, a final newline.
"""

import hashlib
import json
from fractions import Fraction

from .. import softfloat as sf
from ..formats import FORMATS
from . import constants as K_
from .refusals import Refusal

VERSION = 1

# The operations a node may be, in the order counts are written, with
# each one's operand count. The names are softfloat.OP_NAMES' spellings
# and the operand order is the golden function's (asm.py's OP_FIELDS).
OPS = {"fma": 3, "add": 2, "sub": 2, "mul": 2, "neg": 1, "abs": 1,
       "copysign": 2, "min": 2, "max": 2, "minnum": 2, "maxnum": 2,
       "cmplt": 2, "cmple": 2, "cmpeq": 2, "select": 3}
ROUNDED = frozenset({"fma", "add", "sub", "mul"})


class Node:
    """A node while the checker builds: an operation on values, each a
    Node or a leaf tuple ('s'|'l'|'p', index) or ('c', (exact, factor))."""
    __slots__ = ("op", "args", "label", "line")

    def __init__(self, op, args, line):
        self.op = op
        self.args = tuple(args)
        self.label = None
        self.line = line


class Section:
    __slots__ = ("out", "nodes")

    def __init__(self, out, nodes):
        self.out = list(out)            # [ref]
        self.nodes = list(nodes)        # [(op, (ref, ...), label or None)]


def _ref_kind(ref):
    return ref[0], int(ref[1:])


def _frac(text):
    return Fraction(text)


def _key_sort(entry):
    value, factor = entry
    if factor is not None:
        return (0, -factor, value)
    return (1, value, 0)


def canonical(sections):
    """{name: Section} and the const keys, from {name: [output value]}.

    The walk is iterative and visits each section's outputs in state
    order, operands in order; a node gets its index when it is left
    (post-order), so every ref is to an earlier node."""
    keys = {}
    walked = {}
    for name, outs in sections.items():
        if outs is None:
            walked[name] = None
            continue
        order = []
        index = {}
        for root in outs:
            if not isinstance(root, Node) or id(root) in index:
                continue
            stack = [[root, 0]]
            while stack:
                frame = stack[-1]
                node, i = frame
                if i < len(node.args):
                    frame[1] = i + 1
                    a = node.args[i]
                    if isinstance(a, Node) and id(a) not in index:
                        stack.append([a, 0])
                    continue
                stack.pop()
                if id(node) not in index:
                    index[id(node)] = len(order)
                    order.append(node)
        for node in order:
            for a in node.args:
                if not isinstance(a, Node) and a[0] == "c":
                    keys[a[1]] = True
        for o in outs:
            if not isinstance(o, Node) and o[0] == "c":
                keys[o[1]] = True
        walked[name] = (outs, order, index)
    ckeys = sorted(keys, key=_key_sort)
    cindex = {k: i for i, k in enumerate(ckeys)}

    def ref(v, index):
        if isinstance(v, Node):
            return f"n{index[id(v)]}"
        kind, x = v
        if kind == "c":
            return f"c{cindex[x]}"
        return f"{kind}{x}"

    out = {}
    for name, w in walked.items():
        if w is None:
            out[name] = None
            continue
        outs, order, index = w
        uses = [0] * len(order)
        for node in order:
            for a in node.args:
                if isinstance(a, Node):
                    uses[index[id(a)]] += 1
        for o in outs:
            if isinstance(o, Node):
                uses[index[id(o)]] += 1
        for k, node in enumerate(order):
            if node.label is None and uses[k] != 1:
                raise AssertionError(
                    f"an unlabelled {node.op} node has {uses[k]} uses; "
                    f"the builder shares only through labels")
        nodes = [(n.op, tuple(ref(a, index) for a in n.args), n.label)
                 for n in order]
        out[name] = Section([ref(o, index) for o in outs], nodes)
    return out, ckeys


class StepGraph:
    """The checked form of one step (the module docstring)."""

    def __init__(self, system, fmt, rnd, state, lane, param, integrator,
                 const, field, step):
        self.system = system
        self.fmt = fmt
        self.rnd = rnd
        self.state = list(state)            # [(name, length or None)]
        self.lane = list(lane)              # [(name, default, bits)]
        self.param = list(param)            # [(name, exact, bits, flags)]
        self.integrator = integrator        # (name, h or None, options)
        self.const = list(const)            # [(exact, factor, bits, flags)]
        self.field = field                  # Section or None
        self.step = step                    # Section

    # -- what it holds --------------------------------------------------

    @property
    def round_name(self):
        return sf.RND_NAMES[self.rnd]

    def components(self):
        """The flat component names: x, or x[0] .. x[N-1]."""
        out = []
        for name, length in self.state:
            if length is None:
                out.append(name)
            else:
                out.extend(f"{name}[{k}]" for k in range(length))
        return out

    @property
    def n_state(self):
        return sum(1 if ln is None else ln for _, ln in self.state)

    @property
    def is_flow(self):
        return self.field is not None

    def copy(self, **changes):
        g = StepGraph(self.system, self.fmt, self.rnd, self.state,
                      self.lane, self.param, self.integrator, self.const,
                      self.field, self.step)
        for k, v in changes.items():
            setattr(g, k, v)
        return g

    def op_counts(self, section="step"):
        sec = self.field if section == "field" else self.step
        counts = {op: 0 for op in OPS}
        for op, _a, _l in sec.nodes:
            counts[op] += 1
        return {op: n for op, n in counts.items() if n}

    def constant_report(self):
        """Every constant the step reads, as the compiler's manifest wants
        it: [{kind, name, exact, h_factor, bits, flags, relative_error}],
        the consts in the graph's order (named by their spelling: h/6,
        8/3), then the params' and lane params' defaults. The relative
        error is exact, a Fraction: (rounded - exact) / exact."""
        fmt = self.fmt
        out = []
        for value, factor, bits, flags in self.const:
            out.append({"kind": "const",
                        "name": (K_.literal(value) if factor is None
                                 else K_.h_form(factor)),
                        "exact": value, "h_factor": factor, "bits": bits,
                        "flags": flags,
                        "relative_error": K_.relative_error(fmt, bits,
                                                            value)})
        for name, value, bits, flags in self.param:
            out.append({"kind": "param", "name": name, "exact": value,
                        "h_factor": None, "bits": bits, "flags": flags,
                        "relative_error": K_.relative_error(fmt, bits,
                                                            value)})
        for name, value, bits in self.lane:
            if value is None:
                continue
            _b, flags = K_.round_once(fmt, self.rnd, value)
            out.append({"kind": "lane param", "name": name, "exact": value,
                        "h_factor": None, "bits": bits, "flags": flags,
                        "relative_error": K_.relative_error(fmt, bits,
                                                            value)})
        return out

    def count_text(self, section="step"):
        counts = self.op_counts(section)
        total = sum(counts.values())
        if not counts:
            return "0"
        parts = ", ".join(f"{n} {op}" for op, n in counts.items())
        return f"{total} ({parts})"

    # -- the bytes --------------------------------------------------------

    def to_bytes(self):
        fmt = self.fmt
        dump = lambda o: json.dumps(o, separators=(",", ":"),  # noqa: E731
                                    ensure_ascii=True)

        def ex(v):
            return None if v is None else str(Fraction(v))

        def bx(b):
            return None if b is None else K_.bits_hex(fmt, b)

        name, h, options = self.integrator
        lines = [
            '{"cftl_graph":%d,' % VERSION,
            '"system":%s,' % dump(self.system),
            '"format":%s,' % dump(fmt.name),
            '"round":%s,' % dump(self.round_name),
            '"state":%s,' % dump([[n, ln] for n, ln in self.state]),
            '"lane":%s,' % dump([[n, ex(d), bx(b)]
                                 for n, d, b in self.lane]),
            '"param":%s,' % dump([[n, ex(d), bx(b), f]
                                  for n, d, b, f in self.param]),
            '"integrator":%s,' % dump([name, ex(h), options]),
            '"const":%s,' % dump([[ex(v), ex(fa), bx(b), f]
                                  for v, fa, b, f in self.const]),
        ]
        for key, sec, last in (("field", self.field, False),
                               ("step", self.step, True)):
            tail = "}" if last else ","
            if sec is None:
                lines.append('"%s":null%s' % (key, tail))
                continue
            head = '"%s":{"out":%s,"nodes":[' % (key, dump(sec.out))
            if not sec.nodes:
                lines.append(head + "]}" + tail)
                continue
            lines.append(head)
            body = [dump([op, list(args), label])
                    for op, args, label in sec.nodes]
            for k, text in enumerate(body):
                lines.append(text + ("," if k + 1 < len(body)
                                     else "]}" + tail))
        return ("\n".join(lines) + "\n").encode("ascii")

    def digest(self):
        return hashlib.sha256(self.to_bytes()).hexdigest()

    @classmethod
    def from_bytes(cls, data):
        """The graph these bytes are, or `graph-format`. The bytes must
        be canonical (re-serialised, they come back the same), every
        ref must point at an earlier node or an existing leaf, and every
        encoding must be its exact value rounded once."""
        def bad(why):
            return Refusal("graph-format",
                           f"these bytes are not a version-1 step graph: "
                           f"{why}")
        try:
            obj = json.loads(bytes(data).decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise bad(f"not ASCII JSON ({exc})") from None
        try:
            g = cls._from_obj(obj)
        except Refusal:
            raise
        except (KeyError, TypeError, ValueError, IndexError,
                ZeroDivisionError, AttributeError) as exc:
            raise bad(f"{type(exc).__name__}: {exc}") from None
        problem = g.problem()
        if problem:
            raise bad(problem)
        if g.to_bytes() != bytes(data):
            raise bad("not canonical: re-serialised it differs")
        return g

    @classmethod
    def _from_obj(cls, obj):
        if obj.get("cftl_graph") != VERSION:
            raise ValueError("cftl_graph is not 1")
        fmt = FORMATS[obj["format"]]
        rnd = K_.RND_BY_NAME[obj["round"]]

        def bits(t):
            return None if t is None else int(t, 16)

        def ex(t):
            return None if t is None else _frac(t)

        state = [(str(n), None if ln is None else int(ln))
                 for n, ln in obj["state"]]
        lane = [(str(n), ex(d), bits(b)) for n, d, b in obj["lane"]]
        param = [(str(n), _frac(d), bits(b), int(f))
                 for n, d, b, f in obj["param"]]
        name, h, options = obj["integrator"]
        const = [(_frac(v), ex(fa), bits(b), int(f))
                 for v, fa, b, f in obj["const"]]

        def section(o):
            if o is None:
                return None
            return Section([str(r) for r in o["out"]],
                           [(str(op), tuple(str(a) for a in args),
                             None if lb is None else str(lb))
                            for op, args, lb in o["nodes"]])
        return cls(str(obj["system"]), fmt, rnd, state, lane, param,
                   (str(name), ex(h), options), const,
                   section(obj["field"]), section(obj["step"]))

    def problem(self):
        """A sentence naming what is wrong with this graph, or None."""
        fmt, rnd = self.fmt, self.rnd
        n = self.n_state
        limits = {"s": n, "l": len(self.lane), "p": len(self.param),
                  "c": len(self.const)}
        for value, factor, bits, flags in self.const:
            if factor is not None and self.integrator[1] is not None:
                if value != factor * self.integrator[1]:
                    return f"const {value} is not {factor} h"
            want = K_.round_once(fmt, rnd, value)
            if want != (bits, flags):
                return f"const {value} is not its exact value rounded once"
        for name, value, bits, flags in self.param:
            if K_.round_once(fmt, rnd, value) != (bits, flags):
                return f"param {name}'s default is not rounded once"
        for name, value, bits in self.lane:
            if value is not None and K_.round_once(fmt, rnd, value)[0] != bits:
                return f"lane param {name}'s default is not rounded once"
        for key, sec in (("field", self.field), ("step", self.step)):
            if sec is None:
                if key == "step":
                    return "no step section"
                continue
            if len(sec.out) != n:
                return f"{key} has {len(sec.out)} outputs for {n} components"
            for k, (op, args, label) in enumerate(sec.nodes):
                if op not in OPS:
                    return f"{key} node {k}: {op!r} is not an operation"
                if len(args) != OPS[op]:
                    return f"{key} node {k}: {op} takes {OPS[op]} operands"
                for a in args:
                    why = _ref_problem(a, limits, k)
                    if why:
                        return f"{key} node {k}: {why}"
            for o in sec.out:
                why = _ref_problem(o, limits, len(sec.nodes))
                if why:
                    return f"{key} output: {why}"
        return None

    # -- exact evaluation --------------------------------------------------

    def exact_eval(self, section, state, params=None, lanes=None):
        """The section's outputs evaluated exactly, in Fractions: every
        node's operation without rounding (fma is a*b + c, a comparison
        is 1 or 0, copysign takes the sign of a zero as +), constants
        at their exact values. `params` and `lanes` default to the
        declared defaults."""
        sec = self.field if section == "field" else self.step
        values = {"s": [Fraction(v) for v in state],
                  "l": ([Fraction(v) for v in lanes] if lanes is not None
                        else [d for _n, d, _b in self.lane]),
                  "p": ([Fraction(v) for v in params] if params is not None
                        else [d for _n, d, _b, _f in self.param]),
                  "c": [v for v, _fa, _b, _f in self.const]}
        nodes = []

        def get(ref):
            kind, i = _ref_kind(ref)
            if kind == "n":
                return nodes[i]
            return values[kind][i]
        for op, args, _label in sec.nodes:
            nodes.append(_exact(op, [get(a) for a in args]))
        return [get(o) for o in sec.out]


def _ref_problem(ref, limits, before):
    if not ref or ref[0] not in "slpcn" or not ref[1:].isdigit():
        return f"{ref!r} is not a reference"
    kind, i = ref[0], int(ref[1:])
    if kind == "n":
        return None if i < before else f"{ref} is not an earlier node"
    return None if i < limits[kind] else f"{ref} is past the table"


def _exact(op, a):
    if op == "fma":
        return a[0] * a[1] + a[2]
    if op == "add":
        return a[0] + a[1]
    if op == "sub":
        return a[0] - a[1]
    if op == "mul":
        return a[0] * a[1]
    if op == "neg":
        return -a[0]
    if op == "abs":
        return abs(a[0])
    if op == "copysign":
        return -abs(a[0]) if a[1] < 0 else abs(a[0])
    if op in ("min", "minnum"):
        return min(a[0], a[1])
    if op in ("max", "maxnum"):
        return max(a[0], a[1])
    if op == "cmplt":
        return Fraction(1 if a[0] < a[1] else 0)
    if op == "cmple":
        return Fraction(1 if a[0] <= a[1] else 0)
    if op == "cmpeq":
        return Fraction(1 if a[0] == a[1] else 0)
    if op == "select":
        return a[0] if a[2] != 0 else a[1]
    raise ValueError(op)
