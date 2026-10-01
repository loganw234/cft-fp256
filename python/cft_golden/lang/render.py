# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The intention-out: a step graph written back out, two ways.

  render_canonical  the program in the language itself (ASCII): every
                    operation written once and its order explicit, every
                    labelled node a let, the integrator's step written
                    out in an `expansion` block the parser holds to the
                    template's expansion, and each constant's exact
                    value, rounding and relative error and the step's
                    operation counts as comments. Parsed again it gives
                    the same step graph, byte for byte.

  render_math       the equations in conventional notation (UTF-8 plain
                    text): each fma as the a*b + c it computes, each
                    constant as its exact value, the step as the
                    template's own scheme. Evaluated exactly at random
                    rational points it gives what the step graph gives
                    evaluated exactly (python/tests/lang_mathform.py).

Both read the step graph - and, for a flow's step, the template the
graph names - and never the source text.

A name that spells a Greek letter prints as the letter in the
mathematical form (sigma as σ, Delta as Δ). The mapping is cosmetic:
the exact-evaluation check binds every value by its position in the
graph's own declarations, never by the glyph.
"""

from fractions import Fraction

from .. import chars
from . import constants as C
from .refusals import too_deep
from .syntax import Bin, Call, Name, Num
from .templates import TEMPLATES, TITLE

_GREEK = ("alpha α Α", "beta β Β", "gamma γ Γ", "delta δ Δ",
          "epsilon ε Ε", "zeta ζ Ζ", "eta η Η", "theta θ Θ", "iota ι Ι",
          "kappa κ Κ", "lambda λ Λ", "mu μ Μ", "nu ν Ν", "xi ξ Ξ",
          "omicron ο Ο", "pi π Π", "rho ρ Ρ", "sigma σ Σ", "tau τ Τ",
          "upsilon υ Υ", "phi φ Φ", "chi χ Χ", "psi ψ Ψ", "omega ω Ω")
GREEK = {}
for _row in _GREEK:
    _name, _lower, _upper = _row.split()
    GREEK[_name] = _lower
    GREEK[_name.capitalize()] = _upper

MINUS = "−"
DOT = "·"
MAPSTO = "↦"
LE = "≤"
NE = "≠"


def greek(name):
    """A name as the mathematical form prints it: x, or x[3], with a
    Greek letter for a name that spells one."""
    base, bracket, rest = name.partition("[")
    return GREEK.get(base, base) + (bracket + rest if bracket else "")


# ---- the canonical form -----------------------------------------------

def _leaf_text(g, ref, comps):
    kind, i = ref[0], int(ref[1:])
    if kind == "s":
        return comps[i]
    if kind == "l":
        return g.lane[i][0]
    if kind == "p":
        return g.param[i][0]
    value, factor, _b, _f = g.const[i]
    return C.literal(value) if factor is None else C.h_form(factor)


_CANON_BIN = {"add": "+", "sub": "-", "mul": "*", "cmplt": "<",
              "cmple": "<=", "cmpeq": "=="}
_KIND = {"add": "sum", "sub": "sum", "mul": "product", "cmplt": "cmp",
         "cmple": "cmp", "cmpeq": "cmp"}


class _Canon:
    def __init__(self, g, sec):
        self.g = g
        self.sec = sec
        self.comps = g.components()

    def ref(self, ref, parent):
        """A ref written where `parent` (top, arg, bin or neg) uses it."""
        if ref[0] != "n":
            text = _leaf_text(self.g, ref, self.comps)
            if (ref[0] == "c" and parent in ("bin", "neg")
                    and C.is_compound(text)):
                return f"({text})"
            return text
        op, args, label = self.sec.nodes[int(ref[1:])]
        if label is not None:
            return label
        text, kind = self.node(op, args)
        if kind in ("bin", "neg") and parent in ("bin", "neg"):
            return f"({text})"
        return text

    def _inline(self, ref, ops):
        """The unlabelled node a ref names when its op is one of `ops`."""
        if ref[0] != "n":
            return None
        op, args, label = self.sec.nodes[int(ref[1:])]
        if label is not None or op not in ops:
            return None
        return op, args

    def node(self, op, args):
        """(text, kind) of an operation; kind is bin, neg or call. A
        left-deep chain of binary operations and a run of minuses are
        walked in loops, so their length costs no frames."""
        if op in _CANON_BIN:
            spine = [(op, args)]
            left = args[0]
            while True:
                nxt = self._inline(left, _CANON_BIN)
                if nxt is None:
                    break
                spine.append(nxt)
                left = nxt[1][0]
            text = self.ref(left, "bin")
            inner_out = list(reversed(spine))
            for k, (o, a) in enumerate(inner_out):
                text = f"{text} {_CANON_BIN[o]} {self.ref(a[1], 'bin')}"
                if k < len(inner_out) - 1:
                    outer = inner_out[k + 1][0]
                    # a + b - c is (a + b) - c by the language's own
                    # rule that binary operators associate left, so a
                    # left operand of the same kind needs no parentheses
                    # - and a long sum written out stays one level deep.
                    # Every other nesting is parenthesised.
                    if not (_KIND[o] == _KIND[outer] != "cmp"):
                        text = f"({text})"
            return text, "bin"
        if op == "neg":
            # a run of minuses is written flat, `- - -x`, one minus a
            # neg: the parser reads a run in a loop, so the canonical
            # form of any run reads back, however long
            count, inner = 1, args[0]
            while True:
                nxt = self._inline(inner, ("neg",))
                if nxt is None:
                    break
                count += 1
                inner = nxt[1][0]
            return "- " * (count - 1) + "-" + self.ref(inner, "neg"), "neg"
        if op == "select":
            a, b, c = (self.ref(x, "arg") for x in args)
            return f"select({c}, {a}, {b})", "call"
        return f"{op}({', '.join(self.ref(x, 'arg') for x in args)})", "call"

    def definition(self, i):
        op, args, _label = self.sec.nodes[i]
        return self.node(op, args)[0]


def _refs_labels(sec, i, seen):
    """The labelled nodes node i's written expression names."""
    out = []
    stack = list(sec.nodes[i][1])
    while stack:
        r = stack.pop()
        if r[0] != "n":
            continue
        k = int(r[1:])
        if sec.nodes[k][2] is not None:
            out.append(k)
        else:
            stack.extend(sec.nodes[k][1])
    return out


def _groups(integ):
    """The order in which an expansion's labels are written: the
    template's statements in order, each one's calls' field lets before
    its own components - the order the expansion evaluates them in."""
    calls = {"f": 0, "v": 0, "a": 0}
    order = []

    def walk(e, bind=None):
        if isinstance(e, Call) and e.name in calls:
            walk(e.args[0])
            calls[e.name] += 1
            order.append(bind or f"{e.name}{calls[e.name]}")
        elif isinstance(e, Call):
            for x in e.args:
                walk(x)
        elif isinstance(e, Bin):
            walk(e.left)
            walk(e.right)
    for st in TEMPLATES[integ]:
        bind = None
        if (st.kind == "let" and isinstance(st.expr, Call)
                and st.expr.name in calls):
            bind = st.target.name
        walk(st.expr, bind)
        if st.kind == "let" and bind is None:
            order.append(st.target.name)
    seen, out = set(), []
    for name in order:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def _let_order(g, sec, integ):
    """The labelled nodes of a section in the order they are written,
    each after every label its definition names (asserted)."""
    labelled = [k for k, (_o, _a, lb) in enumerate(sec.nodes)
                if lb is not None]
    if integ is None:
        order = labelled
    else:
        comps = set(g.components())
        groups = {}
        for k in labelled:
            prefix, _dot, rest = sec.nodes[k][2].partition(".")
            groups.setdefault(prefix, []).append((rest, k))
        order = []
        comp_index = {c: n for n, c in enumerate(g.components())}
        for prefix in _groups(integ):
            members = groups.pop(prefix, [])
            lets = [k for rest, k in members if rest not in comps]
            outs = sorted((comp_index[rest], k) for rest, k in members
                          if rest in comps)
            order.extend(lets + [k for _c, k in outs])
        for prefix in groups:
            order.extend(k for _rest, k in groups[prefix])
    done = set()
    for k in order:
        for dep in _refs_labels(sec, k, done):
            if dep not in done:
                raise AssertionError(f"label {sec.nodes[k][2]} is written "
                                     f"before {sec.nodes[dep][2]}")
        done.add(k)
    return order


def definitions(g):
    """{label: its definition as the canonical form writes it}, for the
    step section, in the order the canonical form writes them - what an
    expansion block is compared by, label by label."""
    sec = g.step
    can = _Canon(g, sec)
    try:
        order = _let_order(g, sec, g.integrator[0] if g.is_flow else None)
    except AssertionError:
        order = [k for k, (_o, _a, lb) in enumerate(sec.nodes)
                 if lb is not None]
    return {sec.nodes[k][2]: can.definition(k) for k in order}


def _const_rows(g):
    fmt, rnd = g.fmt, g.rnd
    rows = []
    for value, factor, bits, flags in g.const:
        name = C.literal(value) if factor is None else C.h_form(factor)
        rows.append((name, C.literal(value), C.bits_hex(fmt, bits),
                     chars.to_hex(fmt, bits),
                     C.describe(fmt, rnd, value, bits, flags)))
    return rows


def _table(rows, indent):
    widths = [max(len(r[c]) for r in rows) for c in range(len(rows[0]) - 1)]
    out = []
    for r in rows:
        cells = [r[c].ljust(widths[c]) for c in range(len(widths))]
        out.append(indent + "  ".join(cells) + "  " + r[-1])
    return out


def render_canonical(g):
    """The canonical form of a step graph (the module docstring)."""
    try:
        return _render_canonical(g)
    except RecursionError:
        raise too_deep("this step graph's expression") from None


def render_math(g):
    """The mathematical form of a step graph (the module docstring)."""
    try:
        return _render_math(g)
    except RecursionError:
        raise too_deep("this step graph's expression") from None


def _render_canonical(g):
    fmt = g.fmt
    attr = g.round_name
    integ, h, options = g.integrator
    lines = [f"; {g.system} - the canonical form, regenerated from the "
             f"step graph",
             f"; sha256 {g.digest()}",
             ";",
             "; Read back, this text gives the same step graph, byte for "
             "byte. Every",
             "; operation is written once, in the order it is performed; "
             "each one",
             f"; that rounds rounds once, under {attr} "
             f"({C.RND_754[g.rnd]}), in {C.FORMAT_754[fmt.name]}.",
             ";"]
    if g.is_flow:
        lines.append(f"; operations: the equations {g.count_text('field')};")
        lines.append(f";             a step {g.count_text('step')}")
    else:
        lines.append(f"; operations: a step {g.count_text('step')}")
    lines.append(";")
    if g.const:
        lines.append(f"; constants, exact value -> {C.FORMAT_754[fmt.name]} "
                     f"under {attr}:")
        lines.extend(_table(_const_rows(g), ";   "))
        scaled = [C.h_form(fa) for _v, fa, _b, _f in g.const
                  if fa is not None]
        if scaled:
            lines.append(f"; h-scaled, halved by a step-halving bank: "
                         f"{', '.join(scaled)}")
    else:
        lines.append("; constants: none")
    lines.append("")
    lines.append(f"system {g.system}")
    lines.append(f"format {fmt.name}")
    lines.append(f"round  {attr}")
    lines.append("state  " + ", ".join(
        n if ln is None else f"{n}[{ln}]" for n, ln in g.state))
    decl = []
    for name, value, bits, flags in g.param:
        decl.append((f"param  {name} = {C.literal(value)}",
                     f"{C.bits_hex(fmt, bits)}  {chars.to_hex(fmt, bits)}  "
                     f"{C.describe(fmt, g.rnd, value, bits, flags)}"))
    for name, value, bits in g.lane:
        if value is None:
            decl.append((f"lane param {name}", "no default: each lane "
                         "gives it"))
        else:
            _b, flags = C.round_once(fmt, g.rnd, value)
            decl.append((f"lane param {name} = {C.literal(value)}",
                         f"{C.bits_hex(fmt, bits)}  "
                         f"{chars.to_hex(fmt, bits)}  "
                         f"{C.describe(fmt, g.rnd, value, bits, flags)}"))
    if decl:
        w = max(len(code) for code, _c in decl)
        for code, comment in decl:
            lines.append(f"{code.ljust(w)}   ; {comment}")
    comps = g.components()
    lines.append("")
    eq_sec = g.field if g.is_flow else g.step
    can = _Canon(g, eq_sec)
    for k in _let_order(g, eq_sec, None):
        lines.append(f"let {eq_sec.nodes[k][2]} = {can.definition(k)}")
    word = "d/dt" if g.is_flow else "next"
    for c, out in enumerate(eq_sec.out):
        lines.append(f"{word} {comps[c]} = {can.ref(out, 'top')}")
    lines.append("")
    step = f"step {integ}"
    if h is not None:
        step += f", h = {C.literal(h)}"
    if options:
        step += f", q = ({', '.join(options['q'])})"
        step += f", p = ({', '.join(options['p'])})"
    lines.append(step)
    if g.is_flow:
        lines.append("expansion")
        can = _Canon(g, g.step)
        for k in _let_order(g, g.step, integ):
            lines.append(f"  let {g.step.nodes[k][2]} = {can.definition(k)}")
        for c, out in enumerate(g.step.out):
            lines.append(f"  next {comps[c]} = {can.ref(out, 'top')}")
        lines.append("end")
    return "\n".join(lines) + "\n"


# ---- the mathematical form ---------------------------------------------

class M:
    """A rendered value: text, precedence (0 a sum, 1 a product or a
    quotient, 2 a negation, 3 an atom), the value it negates if it is a
    negation, and whether it is a quotient."""
    __slots__ = ("text", "prec", "neg", "div")

    def __init__(self, text, prec, neg=None, div=False):
        self.text, self.prec, self.neg, self.div = text, prec, neg, div


def _par(m, min_prec):
    return m.text if m.prec >= min_prec else f"({m.text})"


def _factor(m):
    """An operand of a product: a sum, a quotient or a negation is
    parenthesised; a product or an atom is not."""
    if m.prec < 1 or m.div or m.text.startswith(MINUS):
        return f"({m.text})"
    return m.text


def m_sum(left, right, sub=False):
    if not sub and right.neg is not None:
        sub, right = True, right.neg
    if sub:
        if right.prec < 1 or right.text.startswith(MINUS):
            rtext = f"({right.text})"
        else:
            rtext = right.text
        return M(f"{left.text} {MINUS} {rtext}", 0)
    rtext = right.text
    if rtext.startswith(MINUS):
        rtext = f"({rtext})"
    return M(f"{left.text} + {rtext}", 0)


def m_prod(a, b):
    return M(f"{_factor(a)}{DOT}{_factor(b)}", 1)


def m_neg(a):
    inner = a.text if a.prec >= 1 and not a.text.startswith(MINUS) \
        else f"({a.text})"
    return M(f"{MINUS}{inner}", 2, neg=a)


def m_const(value, factor=None):
    if factor is None:
        text = C.math_literal(value)
        if text.startswith("-"):
            pos = m_const(-value)
            return M(MINUS + pos.text, 2, neg=pos)
        return M(text, 1 if "/" in text else 3, div="/" in text)
    f = Fraction(factor)
    if f < 0:
        pos = m_const(None, -f)
        return M(MINUS + pos.text, 2, neg=pos)
    p, q = f.numerator, f.denominator
    if f == 1:
        return M("h", 3)
    if q == 1:
        return M(f"{p}{DOT}h", 1)
    if p == 1:
        return M(f"h/{q}", 1, div=True)
    return M(f"{p}{DOT}h/{q}", 1, div=True)


class _Math:
    def __init__(self, g, sec):
        self.g = g
        self.sec = sec
        self.comps = g.components()

    def ref(self, ref):
        kind, i = ref[0], int(ref[1:])
        if kind == "s":
            return M(greek(self.comps[i]), 3)
        if kind == "l":
            return M(greek(self.g.lane[i][0]), 3)
        if kind == "p":
            return M(greek(self.g.param[i][0]), 3)
        if kind == "c":
            value, factor, _b, _f = self.g.const[i]
            return m_const(value, factor)
        op, args, label = self.sec.nodes[i]
        if label is not None:
            return M(greek(label), 3)
        return self.node(op, args)

    def _inline(self, ref, ops):
        if ref[0] != "n":
            return None
        op, args, label = self.sec.nodes[int(ref[1:])]
        if label is not None or op not in ops:
            return None
        return op, args

    def node(self, op, args):
        if op in ("add", "sub", "mul"):
            # a left-deep chain, walked in a loop
            spine = [(op, args)]
            left = args[0]
            while True:
                nxt = self._inline(left, ("add", "sub", "mul"))
                if nxt is None:
                    break
                spine.append(nxt)
                left = nxt[1][0]
            m = self.ref(left)
            for o, a in reversed(spine):
                r = self.ref(a[1])
                m = m_prod(m, r) if o == "mul" else m_sum(m, r,
                                                          sub=o == "sub")
            return m
        if op == "neg":
            count, inner = 1, args[0]
            while True:
                nxt = self._inline(inner, ("neg",))
                if nxt is None:
                    break
                count += 1
                inner = nxt[1][0]
            m = self.ref(inner)
            if count == 1:
                return m_neg(m)
            # a run of negations, flat: --x, one minus a negation
            inner_text = m.text if m.prec >= 1 and \
                not m.text.startswith(MINUS) else f"({m.text})"
            rest = M(MINUS * (count - 1) + inner_text, 2)
            return M(MINUS + rest.text, 2, neg=rest)
        a = [self.ref(x) for x in args]
        if op == "fma":
            prod = m_prod(a[0], a[1])
            if args[0][0] == "c":
                return m_sum(a[2], prod)
            return m_sum(prod, a[2])
        if op == "abs":
            return M(f"|{a[0].text}|", 3)
        if op in ("copysign", "min", "max", "minnum", "maxnum"):
            name = {"minnum": "minNum", "maxnum": "maxNum"}.get(op, op)
            return M(f"{name}({a[0].text}, {a[1].text})", 3)
        if op in ("cmplt", "cmple", "cmpeq"):
            sym = {"cmplt": "<", "cmple": LE, "cmpeq": "="}[op]
            return M(f"[{a[0].text} {sym} {a[1].text}]", 3)
        if op == "select":
            return M(f"({a[0].text} if {a[2].text} {NE} 0 else "
                     f"{a[1].text})", 3)
        raise AssertionError(op)

    def definition(self, i):
        op, args, _label = self.sec.nodes[i]
        return self.node(op, args).text


def _template_math(integ):
    """The template's scheme in conventional notation: each let used
    once and not a call of the right-hand side is written in place."""
    body = TEMPLATES[integ]
    uses = {}

    def count(e):
        if isinstance(e, Name):
            uses[e.name] = uses.get(e.name, 0) + 1
        elif isinstance(e, Call):
            for x in e.args:
                count(x)
        elif isinstance(e, Bin):
            count(e.left)
            count(e.right)
    for st in body:
        count(st.expr)
    defs = {st.target.name: st.expr for st in body if st.kind == "let"}
    inline = {n for n, e in defs.items()
              if uses.get(n, 0) == 1
              and not (isinstance(e, Call) and e.name in ("f", "v", "a"))}

    def constant(e):
        return isinstance(e, Num) or (isinstance(e, Name) and e.name == "h") \
            or (isinstance(e, Bin) and e.op == "/")

    def tm(e):
        if isinstance(e, Num):
            return m_const(e.value)
        if isinstance(e, Name):
            if e.name in inline:
                return tm(defs[e.name])
            return M(e.name, 3)
        if isinstance(e, Bin):
            if e.op == "/":
                return M(f"{tm(e.left).text}/{tm(e.right).text}", 1,
                         div=True)
            if e.op == "+":
                return m_sum(tm(e.left), tm(e.right))
            if e.op == "-":
                return m_sum(tm(e.left), tm(e.right), sub=True)
            return m_prod(tm(e.left), tm(e.right))
        if isinstance(e, Call) and e.name == "fma":
            a, b, c = (tm(x) for x in e.args)
            prod = m_prod(a, b)
            return m_sum(c, prod) if constant(e.args[0]) else m_sum(prod, c)
        return M(f"{e.name}({tm(e.args[0]).text})", 3)

    out = []
    for st in body:
        name = st.target.name
        if st.kind == "let":
            if name not in inline:
                out.append(f"  {name} = {tm(st.expr).text}")
        else:
            out.append(f"  {name} {MAPSTO} {tm(st.expr).text}")
    return out


def _render_math(g):
    integ, h, options = g.integrator
    comps = g.components()
    lines = [f"{g.system} - the mathematical form, regenerated from the "
             f"step graph",
             f"{C.FORMAT_754[g.fmt.name]} ({g.fmt.name}), "
             f"{C.RND_754[g.rnd]}",
             "",
             "Each operation here is exact. The program performs the same",
             "operations, each rounded once, in the order the canonical "
             "form",
             "writes them.",
             ""]
    if g.param:
        lines.append("parameters, the run's (defaults)")
        for name, value, _b, _f in g.param:
            lines.append(f"  {greek(name)} = {m_const(value).text}")
        lines.append("")
    if g.lane:
        lines.append("lane parameters, each lane's (defaults)")
        for name, value, _b in g.lane:
            if value is None:
                lines.append(f"  {greek(name)}")
            else:
                lines.append(f"  {greek(name)} = {m_const(value).text}")
        lines.append("")
    sec = g.field if g.is_flow else g.step
    mm = _Math(g, sec)
    lets = [k for k, (_o, _a, lb) in enumerate(sec.nodes) if lb is not None]
    if lets:
        lines.append("where")
        for k in lets:
            lines.append(f"  {greek(sec.nodes[k][2])} = {mm.definition(k)}")
        lines.append("")
    if g.is_flow:
        lines.append("the equations")
        for c, out in enumerate(sec.out):
            lines.append(f"  d{greek(comps[c])}/dt = {mm.ref(out).text}")
        lines.append("")
        if integ == "stormer-verlet":
            lines.append(f"one step: {TITLE[integ]}, with v the right-hand "
                         f"sides of dQ/dt and a those of dP/dt")
        else:
            lines.append(f"one step: {TITLE[integ]}, with f the right-hand "
                         f"sides above")
        lines.append(f"  h = {m_const(h).text}")
        lines.append(f"  Y = ({', '.join(greek(c) for c in comps)})")
        if integ == "stormer-verlet":
            for key, vec in (("q", "Q"), ("p", "P")):
                names = []
                for d in options[key]:
                    names.extend(c for c in comps
                                 if c == d or c.startswith(d + "["))
                lines.append(f"  {vec} = ({', '.join(greek(c) for c in names)})")
        lines.extend(_template_math(integ))
    else:
        lines.append(f"one step: {TITLE['map']}")
        if h is not None:
            lines.append(f"  h = {m_const(h).text}")
        lines.append(f"  Y = ({', '.join(greek(c) for c in comps)})")
        for c, out in enumerate(sec.out):
            lines.append(f"  {greek(comps[c])} {MAPSTO} {mm.ref(out).text}")
    return "\n".join(lines) + "\n"
