# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Routines inlined (C4): a division's and a square root's nodes replaced
by their fragments (cft_golden/routines.py).

A tile has no divide or square-root instruction. The compiler carries
the language's `div` and `sqrt` nodes as ROUTINES: the schedulers order
the lowered step with each routine node one node, and then, for each
candidate order, expand() replaces each routine node at its place by its
fragment - divfull's or sqrtfull's instructions, specialised at the
program's attribute - bound to the node's operands, followed by a RAISE
of the fragment's flag word. The allocator takes the result as the
straight-line step it always takes, so a routine's registers come from
it like any value's, and Belady's rule spills around a routine what the
step keeps live across it.

* A routine instance is one BLOCK of the order: no language node and no
  other routine's instruction stands inside it. The allocator opens a
  quiet region (QUIET) before a block's first instruction and closes it
  (ENDQUIET) after its last; the raise follows, outside, so the only
  flags a routine raises are its flag word's: exactly its operation's
  (docs/SEQUENCER.md, R24). Loads, stores and copies the allocator puts
  inside a region raise nothing either way.
* SHARING: a routine's instructions are hash-consed across instances by
  opcode, attribute and operands - two divisions by one divisor share
  its classification, seed and Newton steps, every division of 1 its
  dividend's - after routines.simplify, which binding a fragment's inputs
  can make apply where they coincide (x / x). The value kept is the
  first instance's, so a later block reads an earlier block's value: a
  value like any, live or spilled between them. Every routine's
  instruction reads one of its words or another of its values, so none
  can be a language node's, and the language's nodes are not keyed here.
* A word is the bank slot holding its bits: ("w", bits) in slot_of.

What the step computes is the lowered step's, node for node: each
routine's result is the fragment's result value (the language's nodes
that read the routine read it), and its flags are raised once. The
internal check holds that of the image without reading any of this: it
instantiates each routine's fragment from the golden model itself
(check.py).
"""

from cft_golden import routines as R
from cft_golden import softfloat as sf

from .ir import ROUTINES
from .lower import LNode
from .refusals import InternalError


class XNode(LNode):
    """A node of the expanded step: a language node (kind "lang"), a
    routine's instruction ("quiet") or a routine's raise ("raise")."""
    __slots__ = ("rnd", "kind", "block", "routine", "at")

    def __init__(self, op, args, labels, origin, rnd=None, kind="lang",
                 block=None, routine=None, at=None):
        super().__init__(op, args, labels, origin)
        self.rnd = rnd          # a routine instruction's own attribute
        self.kind = kind
        self.block = block      # the routine instance, for quiet and raise
        self.routine = routine  # the lowered routine node it comes from
        self.at = at            # (its index in the fragment, the body's size)


class Expanded:
    """The lowered step expanded in one order: the allocator's input, the
    lowering's bank and graph, and each routine instance's block."""

    def __init__(self, low, nodes, outs, blocks):
        self.low = low
        self.graph = low.graph
        self.nodes = nodes
        self.outs = outs
        self.slots = low.slots
        self.slot_of = low.slot_of
        self.h_slots = low.h_slots
        self.routines = low.routines
        # [(lowered routine node, op, its first expanded node, its raise)]
        self.blocks = blocks

    @property
    def fmt(self):
        return self.graph.fmt


def expand(low, order):
    """-> Expanded: `order`'s nodes, each routine node replaced at its
    place by its fragment bound to its operands, then a raise of its
    flag word (the module docstring)."""
    g = low.graph
    fmt, rnd = g.fmt, g.rnd
    nodes, keyed, map_low, blocks = [], {}, {}, []

    def word_bits(r):
        return r[1] if r[0] == "w" else None
    for j in order:
        nd = low.nodes[j]
        args = tuple(map_low[a[1]] if a[0] == "n" else a for a in nd.args)
        if nd.op not in ROUTINES:
            nodes.append(XNode(nd.op, args, nd.labels, nd.origin))
            map_low[j] = ("n", len(nodes) - 1)
            continue
        f = R.fragment(nd.op, fmt, rnd)
        inputs = dict(zip(f.inputs, args))
        vals = {}
        first = len(nodes)
        for i, (opc, r, srcs) in enumerate(f.body):
            ss = tuple(inputs[s[1]] if s[0] == "in" else vals[s]
                       if s[0] == "v" else ("w", f.words[s[1]])
                       for s in srcs)
            same = R.simplify(opc, ss, word_bits, fmt.sign_mask)
            if same is not None:
                vals[("v", i)] = same
                continue
            name = sf.OP_NAMES[opc]
            key = (name, r, ss)
            hit = keyed.get(key)
            if hit is not None:
                vals[("v", i)] = hit
                continue
            nodes.append(XNode(name, ss, [], [], rnd=r, kind="quiet",
                               block=len(blocks), routine=j,
                               at=(i + 1, len(f.body))))
            vals[("v", i)] = keyed[key] = ("n", len(nodes) - 1)
        res, flags = vals[f.result], vals[f.flags]
        if res[0] != "n" or flags[0] != "n":
            raise InternalError(f"{nd.op} node {j}: its result or flag word "
                                f"is not one of its values")
        nodes.append(XNode("raise", (flags,), [], [], kind="raise",
                           block=len(blocks), routine=j))
        blocks.append((j, nd.op, first, len(nodes) - 1))
        map_low[j] = res
    outs = [map_low[r[1]] if r[0] == "n" else r for r in low.outs]
    return Expanded(low, nodes, outs, blocks)
