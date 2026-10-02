# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The variational equations: the tangent of a section of the step graph,
node by node (docs/LANGUAGE.md, "The variational equations").

A system that declares `tangent v` carries, beside its step, the step's
tangent-linear model: the derivative of every operation of the step,
along a tangent vector over the whole state. This is construction B of
L3's design - the step map's own derivative, not the integrator applied
to a differentiated right-hand side - so a map has one too, every
template gets its tangent from the same rules, and what is differentiated
is what the program computes.

Each operation's tangent is a rule written in the language
(docs/LANGUAGE.md's rule table), applied here to the checker's nodes:

  a + b           da + db
  a - b           da - db
  -a              -da
  a * b           fma(da, b, a * db)
  fma(a, b, c)    fma(da, b, fma(a, db, dc))
  a / b           fma(-r, db, da) / b, r the quotient (L4)
  sqrt(a)         da / (2 * r), r the root (L4)
  abs(a)          copysign(1, a) * da
  copysign(a, b)  copysign(1, b) * (copysign(1, a) * da)
  min, max, minnum, maxnum (a, b) with result r
                  select(r == a, da, db)
  select(c, a, b) select(c, da, db)
  comparisons     zero

A value's tangent is IDENTICALLY ZERO when it reads no state component -
a constant, h, a param, a lane param - or reads one only through a
comparison or a select's condition. An identically-zero tangent is never
an operand: each term it would make is left out, exactly (fma's rule with
dc absent is the product rule; the product rule with da absent is
`a * db`; the quotient's with db absent is `da / b`, and with da absent
`(-r) * db / b`), and where a select needs an arm it is the constant 0.
So no tangent ever rounds an exact zero, and `x + 0 is not x` never
arises.

The quotient's and the root's rules read r, the operation's own result,
as min's and max's do: (da - r db) / b, one fma and one division, two
roundings, the fma's -r a primal value the compiler shares across
vectors; and da / (2 r), whose doubling is exact, one rounding. Each
whose tangent is not zero - one that reads the state - costs a tangent
vector ONE run-time division - the quotient or root written again where
it has no name is the primal's own operation, shared - and the root's
tangent takes no root; one that reads no state (a quotient of params,
the root of a param) has an identically-zero tangent and costs a vector
nothing (docs/LANGUAGE.md, "The quotient and the root").

A rule reads a primal value BY NAME where it has one - a leaf, or a
labelled node (a let, a template label such as k1.x), which the tangent
section refers to across sections - and otherwise WRITES IT AGAIN: a copy
of the unlabelled subtree down to names. A copy is an operation of the
tangent, performed again: the same operation on the same values, so the
same bits and the same flags, and FLAGS is an OR; the compiler shares it
with the primal's own. That keeps the language's promise for the
tangent's text - every operation written is performed, once, in the order
the canonical form writes it - at a known price: a long chain of unnamed
operations whose rules read an operand or their own result (products,
fma, quotients, roots, abs, copysign, the min family) makes each one's
tangent write its unnamed operands again, so the tangent grows with the
square of the chain (measured: 5,049 nodes for a 100-term product chain,
198 without copies; 5,247 for a chain of 99 quotients, 297 named by
lets; 5,148 for 99 nested roots; 8,099 for a min chain of 90 terms). A
select's condition takes no tangent, so a chain through it stays linear.
Naming parts with lets keeps it linear.

The walk is iterative, from the outputs, and makes the tangent of a node
only when some output's tangent reads it, so a comparison's operands and
a select's condition get none.
"""

from .graph import Node

CMP = frozenset({"cmplt", "cmple", "cmpeq"})
MINMAX = frozenset({"min", "max", "minnum", "maxnum"})


def relevant(node):
    """The operand positions whose tangents the node's rule reads."""
    op = node.op
    if op in CMP:
        return ()
    if op == "select":          # golden order (a, b, c): c is the condition
        return (0, 1)
    if op == "copysign":        # b's sign only: its tangent is never read
        return (0,)
    return tuple(range(len(node.args)))


class Derivation:
    """The tangent of one section's outputs, for a generic tangent vector
    whose component i is the leaf ('t', i). A tangent is a Node, a leaf
    ('t', i), or None: identically zero.

    `zero`, `one` and `two` are the leaves of the exact constants 0, 1
    and 2, as the checker rounds them (each once, under the program's
    attribute; all exact in every format). `fold(op, leaves)` is the
    checker's own
    exact folding of an operation on constant leaves, as a leaf: a rule
    whose operands are all constants - copysign(1, b) for a constant b -
    is a constant expression, folded as the language folds any, so the
    rule written out reads back as what was derived (`copysign(1, 2)` is
    the constant 1, and `copysign(1, -2)` the constant -1)."""

    def __init__(self, zero, one, fold, two):
        self.zero = zero
        self.one = one
        self.two = two
        self.fold = fold
        self.memo = {}

    def of(self, v):
        """The tangent of a primal value whose node, if any, is derived."""
        if isinstance(v, Node):
            return self.memo[id(v)]
        if isinstance(v, tuple) and v[0] == "s":
            return ("t", v[1])
        return None             # a constant, a param, a lane param, a K

    def derive(self, outs):
        """The tangents of a section's outputs - None where identically
        zero. Every node a rule needs is derived first, in a post-order
        walk over the operands whose tangents the rules read."""
        order, seen = [], set()
        for root in outs:
            if not isinstance(root, Node) or id(root) in self.memo \
                    or id(root) in seen:
                continue
            seen.add(id(root))
            stack = [[root, 0, relevant(root)]]
            while stack:
                frame = stack[-1]
                node, i, rel = frame
                if i < len(rel):
                    frame[1] = i + 1
                    a = node.args[rel[i]]
                    if isinstance(a, Node) and id(a) not in self.memo \
                            and id(a) not in seen:
                        seen.add(id(a))
                        stack.append([a, 0, relevant(a)])
                    continue
                stack.pop()
                order.append(node)
        for node in order:
            t = self.rule(node)
            # the tangent of a named value is named after it, so that it
            # may be read as often as the value is (k1.x's is v.k1.x)
            if node.label is not None and isinstance(t, Node) \
                    and t.label is None:
                t.label = node.label
            self.memo[id(node)] = t
        return [self.of(o) for o in outs]

    def read(self, v):
        """A primal value as a rule reads it: itself where it has a name -
        a leaf, a constant, a labelled node - and otherwise written again,
        a copy of its unlabelled subtree down to names, walked in a loop."""
        if not isinstance(v, Node) or v.label is not None:
            return v
        made = {}
        stack = [[v, 0]]
        while stack:
            frame = stack[-1]
            node, i = frame
            if i < len(node.args):
                frame[1] = i + 1
                x = node.args[i]
                if isinstance(x, Node) and x.label is None \
                        and id(x) not in made:
                    stack.append([x, 0])
                continue
            stack.pop()
            args = [made[id(x)] if isinstance(x, Node) and x.label is None
                    else x for x in node.args]
            made[id(node)] = Node(node.op, args, node.line)
        return made[id(v)]

    def rule(self, node):
        """The node's tangent, by its operation's rule (the module
        docstring), with every identically-zero term left out."""
        op, a, line = node.op, node.args, node.line
        rel = relevant(node)
        t = [self.of(a[k]) if k in rel else None for k in range(len(a))]
        R = self.read

        def N(o, *args):
            if all(isinstance(x, tuple) and x[0] == "c" for x in args):
                return self.fold(o, args)
            return Node(o, args, line)

        def arm(x):
            return self.zero if x is None else x
        if op in CMP:
            return None
        if op == "add":
            da, db = t
            if da is None:
                return db
            if db is None:
                return da
            return N("add", da, db)
        if op == "sub":
            da, db = t
            if da is None and db is None:
                return None
            if db is None:
                return da
            if da is None:
                return N("neg", db)
            return N("sub", da, db)
        if op == "neg":
            return None if t[0] is None else N("neg", t[0])
        if op == "mul":
            da, db = t
            if da is None and db is None:
                return None
            if db is None:
                return N("mul", da, R(a[1]))
            if da is None:
                return N("mul", R(a[0]), db)
            return N("fma", da, R(a[1]), N("mul", R(a[0]), db))
        if op == "fma":
            da, db, dc = t
            if db is not None and dc is not None:
                inner = N("fma", R(a[0]), db, dc)
            elif db is not None:
                inner = N("mul", R(a[0]), db)
            else:
                inner = dc
            if da is None:
                return inner
            if inner is None:
                return N("mul", da, R(a[1]))
            return N("fma", da, R(a[1]), inner)
        if op == "div":
            # r = a / b: (da - r db) / b. One fma rounds the numerator, its
            # -r a negated primal value; a zero term is left out.
            da, db = t
            if da is None and db is None:
                return None
            if db is None:
                return N("div", da, R(a[1]))
            minus_r = N("neg", R(node))
            if da is None:
                return N("div", N("mul", minus_r, db), R(a[1]))
            return N("div", N("fma", minus_r, db, da), R(a[1]))
        if op == "sqrt":
            # r = sqrt(a): da / (2 r), the doubling exact
            if t[0] is None:
                return None
            return N("div", t[0], N("mul", self.two, R(node)))
        if op == "abs":
            if t[0] is None:
                return None
            return N("mul", N("copysign", self.one, R(a[0])), t[0])
        if op == "copysign":
            if t[0] is None:
                return None
            inner = N("mul", N("copysign", self.one, R(a[0])), t[0])
            return N("mul", N("copysign", self.one, R(a[1])), inner)
        if op in MINMAX:
            da, db = t
            if da is None and db is None:
                return None
            return N("select", arm(da), arm(db), N("cmpeq", R(node), R(a[0])))
        if op == "select":
            da, db = t[0], t[1]
            if da is None and db is None:
                return None
            return N("select", arm(da), arm(db), R(a[2]))
        raise AssertionError(f"no tangent rule for {op}")
