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

A graph with tangent vectors (version 2: docs/LANGUAGE.md, "The
variational equations") is read here into the same shape, over an
EXTENDED state: the state's n components, then each vector's n, in
declaration order - which is the lane block's layout, [state | v | w
| lane params]. Its step is the primal step's nodes, then, a vector at a
time, the generic tangent step's, each tangent input tN of vector k
read as the state input n(k + 1) + N, each dN as that copy's node, each
nN as the primal node it names. From here on the compiler treats a
tangent component as one more component of the state - homed or pinned,
loaded and stored like any - and its sharing merges what the copies
compute alike: the primal values a tangent writes again, and the
primal-only nodes of the rules (copysign(1, a), r == a) across vectors.
"""

import hashlib
import json
from cft_golden import FORMATS
from cft_golden import softfloat as sf
from cft_golden.lang import constants as K

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
        self.version = obj.get("cftl_graph")
        if self.version not in (1, 2) or isinstance(self.version, bool):
            raise InternalError("the step graph is not version 1 or 2")
        self.system = obj["system"]
        self.fmt_name = obj["format"]
        self.fmt = FORMATS[self.fmt_name]
        self.rnd_name = obj["round"]
        self.rnd = RND_BY_NAME[self.rnd_name]
        self.state = [(n, ln) for n, ln in obj["state"]]
        primal = []
        for name, length in self.state:
            if length is None:
                primal.append(name)
            else:
                primal.extend(f"{name}[{k}]" for k in range(length))
        self.tangent = list(obj["tangent"]) if self.version == 2 else []
        self.T = len(self.tangent)
        if self.version == 2 and not self.T:
            raise InternalError("a version-2 step graph names no tangent "
                                "vector")
        self.n_primal = len(primal)
        self.primal_components = primal
        # the extended state: the state, then each vector's components
        self.components = primal + [f"{vec}.{c}" for vec in self.tangent
                                    for c in primal]
        self.n_state = len(self.components)

        # Exact values are read as the graph writes them, p or p/q, at any
        # size: Fraction's own parser stops at Python's 4,300-digit limit,
        # and the language holds constants to 2^+-1048576, so a const of
        # 1e-5000 at fp256 is the language's and has 5,001 digits.
        def ex(t):
            return None if t is None else K.parse_frac(t)

        def bits(t):
            return None if t is None else int(t, 16)
        self.lane = [(n, ex(d), bits(b)) for n, d, b in obj["lane"]]
        self.param = [(n, K.parse_frac(d), int(b, 16), int(f))
                      for n, d, b, f in obj["param"]]
        name, h, options = obj["integrator"]
        self.integrator = (name, ex(h), options)
        self.const = [(K.parse_frac(v), ex(fa), int(b, 16), int(f))
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
        if len(self.outs) != self.n_primal:
            raise InternalError(f"{len(self.outs)} outputs for "
                                f"{self.n_primal} state components")
        for r in self.outs:
            self._check_ref(r, len(self.nodes))
        self.primal_step_nodes = len(self.nodes)
        self.primal_counts = self.op_counts()
        self.tangent_step_nodes = 0
        self.tangent_counts = {}
        if self.T:
            self._tangent(obj["tangent_step"])
        self.field_counts = None
        if obj.get("field") is not None:
            counts = {}
            for op, _a, _l in obj["field"]["nodes"]:
                counts[op] = counts.get(op, 0) + 1
            self.field_counts = counts

    def _tangent(self, tstep):
        """The tangent step, a copy a vector, after the primal step's
        nodes; its outputs after the step's (the module docstring)."""
        P, n = self.primal_step_nodes, self.n_primal
        nodes = tstep["nodes"]
        self.tangent_step_nodes = len(nodes)
        counts = {}
        for op, _a, _l in nodes:
            counts[op] = counts.get(op, 0) + 1
        self.tangent_counts = {op: counts[op] for op in ARITY if op in counts}
        for k in range(self.T):
            base = len(self.nodes)

            def ref(text, before):
                kind, digits = text[:1], text[1:]
                if kind not in "slpcntd" or not digits.isdigit():
                    raise InternalError(f"{text!r} is not a tangent "
                                        f"section's reference")
                i = int(digits)
                if kind == "t":
                    if i >= n:
                        raise InternalError(f"{text} is past the state")
                    return ("s", n * (k + 1) + i)
                if kind == "d":
                    if i >= before:
                        raise InternalError(f"{text} is not an earlier node")
                    return ("n", base + i)
                if kind == "n":
                    if i >= P:
                        raise InternalError(f"{text} is past the step")
                    return ("n", i)
                r = (kind, i)
                self._check_ref(r, 0)
                return r
            for j, (op, args, label) in enumerate(nodes):
                if op not in ARITY or len(args) != ARITY[op]:
                    raise InternalError(f"tangent step node {j}: {op} with "
                                        f"{len(args)} operands")
                self.nodes.append((op, tuple(ref(a, j) for a in args),
                                   None if label is None
                                   else f"{self.tangent[k]}.{label}"))
            outs = [ref(o, len(nodes)) for o in tstep["out"]]
            if len(outs) != n:
                raise InternalError(f"{len(outs)} tangent outputs for {n} "
                                    f"state components")
            self.outs += outs

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
