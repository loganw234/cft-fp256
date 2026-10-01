# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The step graph as the compiler reads it: L1's canonical bytes.

The compiler's one input is the step graph's bytes - canonical JSON,
version 1 (cft_golden/lang/graph.py and docs/LANGUAGE.md, "The step
graph") - read here into plain tuples. Reading the bytes rather than
L1's objects keeps the compiler to the published form: what it compiles
is exactly what the manifest's graph SHA-256 is the digest of.

A ref is a pair: ("s", i) a state input, ("l", i) a lane param,
("p", i) a param, ("c", i) a const entry, ("n", i) a node of the step.
The lowering adds ("f", i), a slot holding const i's encoding with its
sign bit inverted (lower.py).
"""

import hashlib
import json
from fractions import Fraction

from cft_golden import FORMATS
from cft_golden import softfloat as sf

from .refusals import InternalError

ARITY = {"fma": 3, "add": 2, "sub": 2, "mul": 2, "neg": 1, "abs": 1,
         "copysign": 2, "min": 2, "max": 2, "minnum": 2, "maxnum": 2,
         "cmplt": 2, "cmple": 2, "cmpeq": 2, "select": 3}
ROUNDED = frozenset({"fma", "add", "sub", "mul"})
RND_BY_NAME = {name: code for code, name in sf.RND_NAMES.items()}


def parse_ref(text):
    kind, digits = text[:1], text[1:]
    if kind not in "slpcn" or not digits.isdigit():
        raise InternalError(f"{text!r} is not a step-graph reference")
    return kind, int(digits)


def ref_text(ref):
    return f"{ref[0]}{ref[1]}"


class Graph:
    """One step graph, read: its header, its constants and its step."""

    def __init__(self, data):
        self.bytes = bytes(data)
        self.sha256 = hashlib.sha256(self.bytes).hexdigest()
        try:
            obj = json.loads(self.bytes.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise InternalError(f"the step graph is not ASCII JSON: "
                                f"{exc}") from None
        if obj.get("cftl_graph") != 1:
            raise InternalError("the step graph is not version 1")
        self.system = obj["system"]
        self.fmt_name = obj["format"]
        self.fmt = FORMATS[self.fmt_name]
        self.rnd_name = obj["round"]
        self.rnd = RND_BY_NAME[self.rnd_name]
        self.state = [(n, ln) for n, ln in obj["state"]]
        self.components = []
        for name, length in self.state:
            if length is None:
                self.components.append(name)
            else:
                self.components.extend(f"{name}[{k}]" for k in range(length))
        self.n_state = len(self.components)

        def ex(t):
            return None if t is None else Fraction(t)

        def bits(t):
            return None if t is None else int(t, 16)
        self.lane = [(n, ex(d), bits(b)) for n, d, b in obj["lane"]]
        self.param = [(n, Fraction(d), int(b, 16), int(f))
                      for n, d, b, f in obj["param"]]
        name, h, options = obj["integrator"]
        self.integrator = (name, ex(h), options)
        self.const = [(Fraction(v), ex(fa), int(b, 16), int(f))
                      for v, fa, b, f in obj["const"]]
        step = obj["step"]
        self.nodes = []
        for k, (op, args, label) in enumerate(step["nodes"]):
            if op not in ARITY or len(args) != ARITY[op]:
                raise InternalError(f"step node {k}: {op} with {len(args)} "
                                    f"operands")
            refs = tuple(parse_ref(a) for a in args)
            for r in refs:
                self._check_ref(r, k)
            self.nodes.append((op, refs, label))
        self.outs = [parse_ref(o) for o in step["out"]]
        if len(self.outs) != self.n_state:
            raise InternalError(f"{len(self.outs)} outputs for "
                                f"{self.n_state} state components")
        for r in self.outs:
            self._check_ref(r, len(self.nodes))
        self.field_counts = None
        if obj.get("field") is not None:
            counts = {}
            for op, _a, _l in obj["field"]["nodes"]:
                counts[op] = counts.get(op, 0) + 1
            self.field_counts = counts

    def _check_ref(self, ref, before):
        kind, i = ref
        limit = {"s": self.n_state, "l": len(self.lane),
                 "p": len(self.param), "c": len(self.const),
                 "n": before}[kind]
        if not 0 <= i < limit:
            raise InternalError(f"reference {ref_text(ref)} is outside its "
                                f"table")

    @property
    def m(self):
        """Values a lane carries in its scratch block: state, lane params."""
        return self.n_state + len(self.lane)

    def op_counts(self):
        counts = {}
        for op, _a, _l in self.nodes:
            counts[op] = counts.get(op, 0) + 1
        return {op: counts[op] for op in ARITY if op in counts}

    def ref_name(self, ref):
        """A readable name for a leaf: x, x[3], sigma, lane param mass."""
        kind, i = ref
        if kind == "s":
            return self.components[i]
        if kind == "l":
            return self.lane[i][0]
        if kind == "p":
            return self.param[i][0]
        raise InternalError(f"{ref_text(ref)} has no name of its own")
