# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The integrators, written in the language.

Each is a template the checker expands into one step: its rounding
orders are the language's, because its text is the language's, read by
the same parser (syntax.parse(..., templates=True)). docs/LANGUAGE.md
quotes TEXT, and python/tests/test_lang.py holds the two copies equal.

In a template, Y is the whole state; Q and P are stormer-verlet's
positions and momenta; f is the whole right-hand side, v the
positions' right-hand sides (a function of P) and a the momenta's (a
function of Q); h is the step. Every operation acts component by
component, a constant broadcasts, and a let's components are labelled
<let>.<component> in the expanded step.

The orders are programs/gen_odes.py's, line by line (docs/LANGUAGE.md,
"The integrators"): rk4's stage inputs fma(H2, k, Y) and fma(H, k3, Y),
its sum fma(TWO, k2, k1) then fma(TWO, k3, .) then + k4, its update
fma(H6, sum, Y); stormer-verlet's drift fma(H2, p, q) and kick
fma(h, a(q), p) - the image's fma(MH, t0, px) with the force's sign
kept by the force, which is the same bits (docs/LANGUAGE.md, "The
kick"); euler is rk4's update with one stage.
"""

from .syntax import parse

TEXT = """\
integrator euler
  next Y = fma(h, f(Y), Y)
end

integrator rk4
  let k1 = f(Y)
  let Y2 = fma(h/2, k1, Y)
  let k2 = f(Y2)
  let Y3 = fma(h/2, k2, Y)
  let k3 = f(Y3)
  let Y4 = fma(h, k3, Y)
  let k4 = f(Y4)
  let S2 = fma(2, k2, k1)
  let S3 = fma(2, k3, S2)
  let S4 = S3 + k4
  next Y = fma(h/6, S4, Y)
end

integrator stormer-verlet
  let Q1 = fma(h/2, v(P), Q)
  let P1 = fma(h, a(Q1), P)
  next Q = fma(h/2, v(P1), Q1)
  next P = P1
end
"""

# What each integrator is called in the intention-out.
TITLE = {
    "euler": "the forward Euler method (euler)",
    "rk4": "the classical Runge-Kutta method (rk4)",
    "stormer-verlet": "Stormer-Verlet, drift-kick-drift (stormer-verlet)",
    "map": "the map (map)",
}

FLOW_INTEGRATORS = ("euler", "rk4", "stormer-verlet")
INTEGRATORS = FLOW_INTEGRATORS + ("map",)

# The template's own names. Not reserved in a system: a template has
# its own scope.
VECTORS = {"euler": ("Y",), "rk4": ("Y",), "stormer-verlet": ("Q", "P")}
FUNCTIONS = {"euler": ("f",), "rk4": ("f",), "stormer-verlet": ("v", "a")}


def _load():
    out = {}
    for st in parse(TEXT, templates=True):
        out[st.word] = st.body
    return out


# {integrator: [Stmt]} - each a `let` or `next` over the names above.
TEMPLATES = _load()
assert tuple(TEMPLATES) == FLOW_INTEGRATORS


def _label_prefixes():
    """Every prefix a label of an expanded step can carry: each
    template's lets (k1, Y2, Q1 ...) and its inline calls' names (f1, v1,
    a1, v2), counted as the checker's expansion counts them. A tangent
    vector may not be named after one: `Y2.x` would be both rk4's stage
    and the tangent of x (docs/LANGUAGE.md, "The variational equations")."""
    from .syntax import Bin, Call
    out = set()
    for body in TEMPLATES.values():
        calls = {}

        def walk(e, bind=None):
            if isinstance(e, Call) and e.name in ("f", "v", "a"):
                walk(e.args[0])
                calls[e.name] = calls.get(e.name, 0) + 1
                out.add(bind or f"{e.name}{calls[e.name]}")
            elif isinstance(e, Call):
                for x in e.args:
                    walk(x)
            elif isinstance(e, Bin):
                walk(e.left)
                walk(e.right)
        for st in body:
            bind = None
            if (st.kind == "let" and isinstance(st.expr, Call)
                    and st.expr.name in ("f", "v", "a")):
                bind = st.target.name
            walk(st.expr, bind)
            if st.kind == "let":
                out.add(st.target.name)
    return frozenset(out)


LABEL_PREFIXES = _label_prefixes()
