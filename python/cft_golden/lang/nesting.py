# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""How deep the canonical form nests, line by line, without writing it.

render.py's canonical form writes each labelled node of a section as a
let, each output as an equation, and every unlabelled node in place, at
its one use. The parser reads nesting 100 deep (syntax.MAX_NESTING: each
( and [ one level), so a canonical form nested deeper would not read back.
lines() measures every expression line the canonical form writes, as the
lexer counts it, from the step graph alone - one pass over each section's
nodes, which are in post-order, so nothing recurses however deep a line
is - and the checker refuses a source whose canonical form would nest past
the limit (`too-deep`, check.py's canonical_nesting).

A canonical line can nest deeper than its source: the canonical form
writes its own parentheses - around every operation nested in another but
a left operand of its kind, around a compound constant used as an operand,
x * (1/3), and around a negation used as an operand of a binary operation,
(-a) * b - and writes out what a source need not, the expansion block and
the tangent's lines. For example, -(-(...) * y) * y nests two levels a
level there, and the tangent of an unnamed product of n terms n - 1 deep
from a source 0 deep (D2's probe and verifier-VD2 found such sources, each
a cftc exit 70 until this rule). lines() keeps no list of the ways: it
measures what the canonical form would write.

Each rule below is render._Canon's, one for one, and uses its operator
tables; python/tests/test_lang_readback.py holds the measure equal to the
lexer's own count on render_canonical's text, line by line.
"""

from . import constants as C
from .graph import PRIMAL_OF
from .render import _CANON_BIN, _KIND


def _name_depth(name):
    """A name as the canonical form writes it - x, x[3], k1.x[3], v.r -
    nests one level when it carries an index."""
    return 1 if "[" in name else 0


class _Section:
    """One section's nodes measured: depth[i] is how deep the text
    _Canon.node writes for node i nests, and kind[i] its kind - bin, neg
    or call, as _Canon.node returns them. `primal` is the section a
    tangent section differentiates (its nN are that section's labelled
    nodes), or None."""

    def __init__(self, sec, primal, compound, comps):
        self.sec = sec
        self.primal = primal
        self.own = "n" if primal is None else "d"
        self.compound = compound
        self.comps = comps
        nodes = sec.nodes
        self.depth = depth = [0] * len(nodes)
        self.kind = kind = [None] * len(nodes)
        for i, (op, args, _label) in enumerate(nodes):
            if op in _CANON_BIN:
                # the left spine: a left operand of the same kind is written
                # flat (a + b - c), every other nesting in parentheses
                j = self._inline(args[0], _CANON_BIN)
                if j is None:
                    left = self.ref(args[0], "bin")
                else:
                    flat = _KIND[nodes[j][0]] == _KIND[op] != "cmp"
                    left = depth[j] + (0 if flat else 1)
                depth[i] = max(left, self.ref(args[1], "bin"))
                kind[i] = "bin"
            elif op == "neg":
                # a run of minuses is written flat, - - -x, its first
                # operand that is not one in place after it
                j = self._inline(args[0], ("neg",))
                depth[i] = depth[j] if j is not None else \
                    self.ref(args[0], "neg")
                kind[i] = "neg"
            else:
                # a call: select(c, a, b), fma(a, b, c), abs(a), ...
                depth[i] = 1 + max(self.ref(a, "arg") for a in args)
                kind[i] = "call"

    def _inline(self, ref, ops):
        """The unlabelled node of this section a ref names, when its
        operation is one of `ops` (_Canon._inline)."""
        if ref[0] != self.own:
            return None
        i = int(ref[1:])
        op, _args, label = self.sec.nodes[i]
        return i if label is None and op in ops else None

    def ref(self, ref, parent):
        """How deep a ref nests where `parent` - top, arg, bin or neg -
        uses it (_Canon.ref)."""
        kind, i = ref[0], int(ref[1:])
        if kind == "t":                   # a tangent's component, v.x[3]
            return _name_depth(self.comps[i])
        if kind == "n" and self.primal is not None:
            return _name_depth(self.primal.nodes[i][2])
        if kind == self.own:
            label = self.sec.nodes[i][2]
            if label is not None:         # written by its name
                return _name_depth(label)
            wrap = self.kind[i] != "call" and parent in ("bin", "neg")
            return self.depth[i] + (1 if wrap else 0)
        if kind == "s":
            return _name_depth(self.comps[i])
        if kind == "c":                   # (h/2), (-3), (8/3) as an operand
            return 1 if parent in ("bin", "neg") and self.compound[i] else 0
        return 0                          # a param or a lane param: a name


def lines(g, every_vector=False):
    """[(code, depth, section, what, vector)]: one for each expression line
    render_canonical writes of the step graph `g` - each labelled node's
    let, each output's equation, for every section - with `code` the
    line's left side as written (`let k1.x`, `next v.x`), `depth` how deep
    the line nests as the lexer counts it, `section` the graph's section,
    `what` ("label", label) or ("out", component index), and `vector` the
    tangent vector a tangent section's line is written for (None for a
    primal line). A tangent section is the same text for every vector but
    its names; it is given for the first vector alone unless
    `every_vector`."""
    comps = g.components()
    compound = [C.is_compound(C.literal(v) if fa is None else C.h_form(fa))
                for v, fa, _b, _f in g.const]
    out = []
    vectors = list(g.tangent) if every_vector else list(g.tangent[:1])

    def section(key, word, vecs):
        sec = g.section(key)
        primal = g.section(PRIMAL_OF[key]) if key in PRIMAL_OF else None
        m = _Section(sec, primal, compound, comps)
        for vec in vecs:
            pre = "" if vec is None else f"{vec}."
            for i, (_op, _args, label) in enumerate(sec.nodes):
                if label is not None:
                    out.append((f"let {pre}{label}",
                                max(_name_depth(label), m.depth[i]), key,
                                ("label", label), vec))
            for c, o in enumerate(sec.out):
                out.append((f"{word} {pre}{comps[c]}",
                            max(_name_depth(comps[c]), m.ref(o, "top")), key,
                            ("out", c), vec))

    word = "d/dt" if g.is_flow else "next"
    section("field" if g.is_flow else "step", word, [None])
    if g.tangent:
        section("tangent_field" if g.is_flow else "tangent_step", word,
                vectors)
    if g.is_flow:                         # the expansion block
        section("step", "next", [None])
        if g.tangent:
            section("tangent_step", "next", vectors)
    return out
