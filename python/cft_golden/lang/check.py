# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The checker: from statements to the step graph, or a refusal by name.

It resolves every name, evaluates every constant exactly (a Fraction,
with the power of h it carries), builds one node per operator written,
expands the integrator's template (templates.py) into the step, holds
a written-out `expansion` block to that expansion byte for byte, and
refuses - by a name in refusals.CATALOGUE, with the source line - every
source the language does not take. docs/LANGUAGE.md is the definition
this implements.

Evaluation modes, and what each may read:

  field    a flow's right-hand sides and their lets: the state (a
           stage's inputs), params, lane params, consts that do not
           depend on h, lets, literals. Never h (`h-scope`).
  map      a map's equations and their lets: the same, and h.
  block    an expansion block: the state, params, lane params, consts,
           h, and the block's own labels - not the equations' lets.
  const    a const's value or the step's h: literals, consts, h.
  default  a param's or lane param's default: literals, consts that do
           not depend on h.
"""

from sys import _getframe

from .. import softfloat as sf
from ..formats import FORMATS
from ..seq import SCRATCH_D_MAX
from . import constants as C
from .graph import PRIMAL_OF, Node, StepGraph, canonical
from .refusals import Refusal, too_deep
from .syntax import (KEYWORDS, MAX_NESTING, Bin, Call, Cmp, Index, Name,
                     Neg, Num, Target, parse)
from .tangent import Derivation
from .templates import (FLOW_INTEGRATORS, INTEGRATORS, LABEL_PREFIXES,
                        TEMPLATES)

# The built-ins and the number of arguments each takes. sqrt joined them
# with the run-time square root (L4, 2026-10-02): of a constant it folds
# where the root is exact and is `irrational-constant` where it is not.
BUILTINS = {"fma": 3, "abs": 1, "copysign": 2, "min": 2, "max": 2,
            "minnum": 2, "maxnum": 2, "select": 3, "sqrt": 1}

# Refused by name in v1 (`transcendental`, `irrational-constant`), and so
# reserved: a value cannot be named after one.
TRANSCENDENTAL = frozenset({
    "exp", "expm1", "exp2", "exp10", "log", "log1p", "log2", "log10",
    "pow", "pown", "powr", "rootn", "hypot", "sin", "cos", "tan", "sinpi",
    "cospi", "tanpi", "asin", "acos", "atan", "atan2", "asinpi", "acospi",
    "atanpi", "atan2pi", "sinh", "cosh", "tanh", "asinh", "acosh",
    "atanh", "cbrt", "rsqrt",
})
SPECIAL_WORDS = frozenset({"inf", "infinity", "nan", "snan"})
RESERVED = (KEYWORDS | frozenset(BUILTINS) | frozenset({"h"})
            | TRANSCENDENTAL | SPECIAL_WORDS)

# The bank addresses 512 constants on every device (seq.py KADDR_KX,
# rtl/cft_seq.sv's KMEM_D): params and constants share it.
BANK_SLOTS = 512

# A lane's state and lane params live in its scratch, and no tile can
# publish a deeper scratch than this (seq.py SCRATCH_D_MAX: CAPS2[3:0]
# is a four-bit log2). So it bounds an array, a range, and a lane.
LANE_SLOTS = SCRATCH_D_MAX

_STEP_OPTIONS = {"rk4": ("h",), "euler": ("h",),
                 "stormer-verlet": ("h", "q", "p"), "map": ("h",)}

# ---- definitions read by name, at any depth (D2, 2026-10-01) ------------
#
# A let, a label, a written tangent let or label, or a const is evaluated
# where it is first read, and memoized. A chain of them read by name used to
# recurse a definition a level, so it was held to Python's own recursion
# limit - and the verdict hung on the Python version and the caller's stack:
# a chain of 150 lets through a call was accepted on 3.12 and refused on
# 3.10, a 230-let map accepted from the command line and refused 100 frames
# down, and rk4 with 81 lets accepted while its canonical form, whose
# expansion block chains the stages through labels, did not read back
# (verifier-VD2; cftc's exit 70). Now a definition met where the stack is
# BUDGET frames above the top-level evaluation - an equation's output, a
# block's next line, a default, h - is set aside (_Deep) with the
# definitions on the path to it, and `evaluate` evaluates them again from
# the top, innermost first, the rest of the path kept busy, and then the
# expression itself. Each repeats only its own prefix, which had been done
# without fault and whose effects are idempotent (completed definitions are
# memoized, labels set on completion, constants a cache), so every effect
# first happens in the recursion's order, the prefix's second time adding
# none: the same graph, the same first refusal, a cycle named at the same
# reference.
# python/tests/test_lang_readback.py holds it to the unlimited recursion.
# Nothing bounds a chain: Logan, 2026-10-01, "No limit (Recommended)".
# The budget changes no verdict, only where the stack is cut: at 200 the
# checker's deepest point - a definition entered just under it whose own
# expression is 99 calls deep - was 405 frames on 3.12 and 504 on 3.10,
# under the parser's 506 for that text (D2, measured), so checking never
# needs more stack than parsing the same source.
BUDGET = 200


class _Pending:
    """A definition set aside: a let, label or written tangent let or label
    (its context's `busy` set and its `key`) or a const (`d`), and `again`,
    which evaluates it from the top."""
    __slots__ = ("busy", "key", "d", "again")

    def __init__(self, busy, key, d, again):
        self.busy, self.key, self.d, self.again = busy, key, d, again


class _Deep(Exception):
    """A definition met too deep: `path` holds it and then each definition
    in progress above it, innermost first."""

    def __init__(self, pending):
        super().__init__()
        self.path = [pending]


def _depth():
    """The frames on the stack, the caller's own included."""
    f, n = _getframe(1), 0
    while f is not None:
        n, f = n + 1, f.f_back
    return n


def _past(limit):
    """Whether the caller is more than `limit` frames above the stack's
    bottom (sys._getframe walks down that many, or raises)."""
    try:
        _getframe(limit)
    except ValueError:
        return False
    return True


def _no_root(value):
    """irrational-constant's sentence for sqrt of a constant whose root no
    rational carries."""
    shown = C.brief(value)
    if value < 0:
        return (f"sqrt({shown}) is not a real number: the square root of a "
                f"negative constant has no value, and a constant is an exact "
                f"rational (at run time such a root is a NaN, with invalid)")
    # the constant exactly, not as shown: a long one is shown to five
    # digits, and 4 + 1e-30 shows as 4.0000e+0, a square (verifier-VL4)
    return (f"sqrt({shown}) has no exact rational value - the constant, "
            f"exactly, is no rational's square, and a constant is an exact "
            f"rational: write the root's value as a decimal or a/b, or take "
            f"the root at run time, as the square root of a param")


def _reserved_why(name):
    if name in KEYWORDS:
        return "a keyword"
    if name in BUILTINS:
        return "a built-in"
    if name == "h":
        return "the step's own name"
    if name in SPECIAL_WORDS:
        return "a value v1 refuses as a constant"
    return "a function v1 refuses"


class K:
    """A constant: coef x h^deg, exactly. deg is 0 for a plain rational
    and 1 for an h-scaled one; any other power refuses where it would
    become a leaf (`h-nonlinear`). coef is a Fraction and never a float:
    C.exact refuses one, so no binary64 can reach a constant.

    hsrc is None for a constant that never read h, and otherwise (the
    outermost constant expression that read it, its index environment):
    where the constant meets the step, one of degree 0 is a use of h that
    folded away, which the `unused` check names (Checker.unused)."""
    __slots__ = ("coef", "deg", "hsrc")

    def __init__(self, coef, deg=0, hsrc=None):
        self.coef = C.exact(coef)
        if not isinstance(deg, int) or isinstance(deg, bool):
            raise AssertionError(f"a constant's power of h is an integer, "
                                 f"not {deg!r}")
        self.deg = deg if self.coef != 0 else 0
        self.hsrc = hsrc

    def read_h(self, e, env):
        """This constant as the expression `e` makes it, having read h: a
        new K, since a fold may hand back an operand's own (0 + c is c),
        and a const's value is shared by every use."""
        return K(self.coef, self.deg, (e, env))


def _hread(*vals):
    return any(isinstance(v, K) and v.hsrc is not None for v in vals)


def _pieces(e):
    """An expression's text as a sentence names it, in pieces, in order:
    its own names, literals and operators, each nested operation
    parenthesised but a left operand with its parent's operator (a - b - c).
    A chain and a run of minuses are walked in loops, and nesting recurses
    as deep as the parser allowed it (MAX_NESTING). The pieces come lazily,
    so spell() stops at its limit: writing a long folded constant whole was
    quadratic (verifier-VD2: 2.5 s at 128,000 terms)."""
    if isinstance(e, Num):
        yield e.text
    elif isinstance(e, Name):
        yield e.name
    elif isinstance(e, Index):
        yield f"{e.name}["
        yield from _pieces(e.index)
        yield "]"
    elif isinstance(e, Neg):
        n = 0
        while isinstance(e, Neg):
            n, e = n + 1, e.arg
        yield "- " * (n - 1) + "-"
        yield from _operand(e, isinstance(e, (Bin, Cmp)))
    elif isinstance(e, Bin):
        chain = []
        while isinstance(e, Bin):
            chain.append(e)
            e = e.left
        # a left operand of another operator is parenthesised: open them all
        # first, each closed after its own right operand
        yield "(" * sum(1 for k in range(1, len(chain))
                        if chain[k - 1].op != chain[k].op)
        yield from _operand(e, isinstance(e, (Cmp, Neg)))
        for k in range(len(chain) - 1, -1, -1):
            b = chain[k]
            yield f" {b.op} "
            yield from _operand(b.right, isinstance(b.right, (Bin, Cmp, Neg)))
            if k and chain[k - 1].op != b.op:
                yield ")"
    elif isinstance(e, Cmp):
        yield from _operand(e.left, isinstance(e.left, (Bin, Cmp, Neg)))
        yield f" {e.op} "
        yield from _operand(e.right, isinstance(e.right, (Bin, Cmp, Neg)))
    elif isinstance(e, Call):
        yield f"{e.name}("
        for k, a in enumerate(e.args):
            if k:
                yield ", "
            yield from _pieces(a)
        yield ")"
    else:
        raise AssertionError(f"unknown expression {e!r}")


def _operand(x, wrap):
    if wrap:
        yield "("
    yield from _pieces(x)
    if wrap:
        yield ")"


def spell(e, env=None, limit=40):
    """(text, where): a constant expression as a refusal's sentence names
    it - its text, cut to `limit` characters - and, where an equation's
    range binds index variables it reads, their values (" where i = 3")."""
    out, size = [], 0
    for piece in _pieces(e):
        out.append(piece)
        size += len(piece)
        if size > limit:
            break
    text = "".join(out)
    if len(text) > limit:
        text = text[:limit - 3] + "..."
    where = ""
    if env:
        names = set()
        stack = [e]
        while stack:
            x = stack.pop()
            if isinstance(x, Name):
                names.add(x.name)
            elif isinstance(x, Index):
                stack.append(x.index)
            elif isinstance(x, Neg):
                stack.append(x.arg)
            elif isinstance(x, (Bin, Cmp)):
                stack += [x.left, x.right]
            elif isinstance(x, Call):
                stack += list(x.args)
        bound = [f"{v} = {C.shown(env[v])}" for v in sorted(env) if v in names]
        if bound:
            where = f" where {', '.join(bound)}"
    return text, where


class Decl:
    """A declared name."""
    __slots__ = ("kind", "name", "line", "expr", "index", "length",
                 "cyclic", "base", "value", "busy", "used", "defs",
                 "used_comps", "indexed", "lname")

    def __init__(self, kind, name, line):
        self.kind = kind              # state, const, param, lane, let,
        self.name = name              # label, tangent, or a written
        self.line = line              # tangent let or label (tlet)
        self.lname = None             # a tlet's label in the generic
        #                               tangent section: r for v.r
        self.expr = None
        self.index = None             # a param's or lane param's position
        self.length = None            # an array's length
        self.cyclic = False
        self.base = None              # a state's first flat component
        self.value = None             # a const's K once evaluated
        self.busy = False
        self.used = False
        self.defs = {}                # a let's {comp: (expr, line, env)}
        self.used_comps = set()
        self.indexed = None


class Ctx:
    """Where an expression is evaluated. A TANGENT context - one written
    tangent equation, tangent let or expansion line of the vector `tvec`
    - has the mode of the primal it differentiates (field, map, block),
    reads that vector's components as tangent inputs and its written
    tangent lets or labels from `tlabels`, and reads the primal's lets
    through `primal`, the context that built them, so that a let named
    in a tangent equation is the primal's own node."""
    __slots__ = ("mode", "inputs", "memo", "busy", "prefix", "env", "line",
                 "labels", "tvec", "tlabels", "primal")

    def __init__(self, mode, inputs=None, prefix=None, labels=None):
        self.mode = mode
        self.inputs = inputs
        self.memo = {}
        self.busy = set()
        self.prefix = prefix
        self.env = {}
        self.line = None
        self.labels = labels
        self.tvec = None
        self.tlabels = None
        self.primal = None

    def at(self, env, line):
        c = Ctx.__new__(Ctx)
        c.mode, c.inputs, c.memo, c.busy = (self.mode, self.inputs,
                                            self.memo, self.busy)
        c.prefix, c.labels = self.prefix, self.labels
        c.tvec, c.tlabels, c.primal = self.tvec, self.tlabels, self.primal
        c.env, c.line = env, line
        return c


class Checker:
    def __init__(self, stmts):
        self.stmts = stmts
        self.names = {}
        self.rounded = {}
        self.const_stack = []
        self.h_value = None
        self.h_busy = False
        self.h_used = False             # h is read
        self.h_line = None
        # h is USED where a constant of the step scales with it: an
        # h-scaled leaf made (every flow's template makes some), and the
        # uses of h that folded to a constant that does not scale -
        # {id(expression): (expression, index environment, value)}
        self.h_scaled = False
        self.h_folded = {}
        # the stack depth past which a definition is set aside: BUDGET above
        # the first top-level evaluation, taken once a check (evaluate)
        self._limit = None
        self._comp_at = None        # a component's flat index, by name
        # the tangent vectors, in declaration order, and what a source
        # writes of their equations: {vector: [Stmt]}, {vector: {name:
        # Decl}} for its written tangent lets
        self.tangent_items = []
        self.tangents = []
        self.tangent_set = set()
        self.tan_eq_stmts = {}
        self.tan_eq_lines = {}          # {vector: each component's line}
        self.tan_let_stmts = {}
        self.tan_lets = {}
        self.field_ctx = None
        self.map_ctx = None
        # the source lines at which a run-time division or square root is
        # built, whatever the statement - the graph's routine_lines (L4)
        self.routine_lines = set()

    # ==== declarations ================================================

    def collect(self):
        once = {"system": None, "format": None, "round": None,
                "step": None, "expansion": None}
        self.state_items, self.const_items = [], []
        self.param_items, self.lane_items = [], []
        self.let_stmts, self.eq_stmts = [], []
        for st in self.stmts:
            k = st.kind
            if k in once:
                if once[k] is not None:
                    raise Refusal(
                        "duplicate-declaration",
                        f"{'an expansion block' if k == 'expansion' else k}"
                        f" is already declared, at line {once[k].line}",
                        st.line)
                once[k] = st
            elif k == "state":
                self.state_items.extend(st.items)
            elif k == "tangent":
                self.tangent_items.extend(st.items)
            elif k == "const":
                self.const_items.extend(st.items)
            elif k == "param":
                self.param_items.extend(st.items)
            elif k == "lane":
                self.lane_items.extend(st.items)
            elif k == "let":
                self.let_stmts.append(st)
            else:
                self.eq_stmts.append(st)
        if once["system"] is None:
            raise Refusal("missing-system",
                          "a system file names its system: system NAME")
        if once["format"] is None:
            raise Refusal("missing-format", "a system declares its format: "
                          "format fp32, fp64, fp128 or fp256")
        if not self.state_items:
            raise Refusal("missing-state", "a system has state: "
                          "state x, y")
        if once["step"] is None:
            raise Refusal("missing-step", "a system says how it steps: "
                          "step rk4, h = ..., or step map")
        self.sys_st = once["system"]
        if "." in self.sys_st.word:
            raise Refusal("syntax", f"{self.sys_st.word}: a system's name "
                          f"has no dot", self.sys_st.line)
        fst = once["format"]
        if fst.word not in FORMATS:
            raise Refusal("unknown-format", f"{fst.word} is not a format "
                          f"here: fp32, fp64, fp128 or fp256", fst.line)
        self.fmt = FORMATS[fst.word]
        rst = once["round"]
        if rst is None:
            self.rnd = sf.RND_RNE
        elif rst.word not in C.RND_BY_NAME:
            raise Refusal("unknown-rounding", f"{rst.word} is not a "
                          f"rounding attribute: rne, rtz, rdn, rup or rmm",
                          rst.line)
        else:
            self.rnd = C.RND_BY_NAME[rst.word]
        self.step_st = once["step"]
        if self.step_st.word not in INTEGRATORS:
            raise Refusal("unknown-integrator",
                          f"{self.step_st.word} is not an integrator in "
                          f"v1: rk4, stormer-verlet, euler or map",
                          self.step_st.line)
        self.integ = self.step_st.word
        self.exp_st = once["expansion"]

    def declare(self):
        items = []
        for name, length, cyclic, line in self.state_items:
            items.append((line, 0, "state", name, (length, cyclic)))
        for name, expr, line in self.const_items:
            items.append((line, 1, "const", name, expr))
        for name, expr, line in self.param_items:
            items.append((line, 2, "param", name, expr))
        for name, expr, line in self.lane_items:
            items.append((line, 3, "lane", name, expr))
        for st in self.let_stmts:
            items.append((st.line, 4, "let", st.target.name, st))
        for name, line in self.tangent_items:
            items.append((line, 5, "tangent", name, None))
        items.sort(key=lambda t: (t[0], t[1]))
        tangent_names = {name for name, _line in self.tangent_items}
        n_param = n_lane = 0
        for line, _o, kind, name, payload in items:
            if "." in name:
                vec = name.split(".", 1)[0]
                if kind == "let" and vec in tangent_names:
                    # a written tangent let, v.r: held to the derivation
                    # once the equations' lets are known (tangent_lets)
                    self.tan_let_stmts.setdefault(vec, []).append(payload)
                    continue
                if kind == "tangent":
                    raise Refusal("syntax", f"{name}: a tangent vector's "
                                  f"name has no dot", line)
                raise Refusal("syntax", f"{name} is a label: a dotted name "
                              f"is defined only in an expansion block, or "
                              f"names a tangent's let (v.r)", line)
            if name in RESERVED:
                raise Refusal("reserved-name", f"{name} is "
                              f"{_reserved_why(name)} and cannot name a "
                              f"value", line)
            if kind == "tangent" and name in LABEL_PREFIXES:
                raise Refusal("reserved-name", f"{name} names a label of an "
                              f"expanded step ({name}.x), and a tangent "
                              f"vector named so would read as one", line)
            prev = self.names.get(name)
            if prev is not None:
                if kind == "let" and prev.kind == "let":
                    prev.defs.setdefault("_stmts", []).append(payload)
                    continue
                raise Refusal("duplicate-name", f"{name} is already "
                              f"declared, at line {prev.line}", line)
            d = Decl(kind, name, line)
            if kind == "tangent":
                self.names[name] = d
                continue
            if kind == "state":
                length, cyclic = payload
                if length is not None:
                    v = length.value
                    if not length.text.isdigit() or v < 1:
                        raise Refusal("array-length", f"{name}[{length.text}]"
                                      f": an array's length is written as a "
                                      f"whole number, at least 1", line)
                    if v > LANE_SLOTS:
                        raise Refusal(
                            "array-length", f"{name}[{length.text}]: an "
                            f"array has at most {LANE_SLOTS:,} components, "
                            f"the deepest scratch any tile publishes", line)
                    d.length = int(v)
                d.cyclic = cyclic
            elif kind == "const":
                d.expr = payload
            elif kind == "param":
                d.expr = payload
                d.index = n_param
                n_param += 1
            elif kind == "lane":
                d.expr = payload
                d.index = n_lane
                n_lane += 1
            else:
                d.defs["_stmts"] = [payload]
            self.names[name] = d
        # the flat layout
        self.state_decls = [self.names[name] for name, *_ in
                            self.state_items]
        self.tangents = [name for name, _line in self.tangent_items]
        self.tangent_set = set(self.tangents)
        n_comp = sum(1 if d.length is None else d.length
                     for d in self.state_decls)
        total = n_comp * (1 + len(self.tangents)) + n_lane
        if total > LANE_SLOTS:
            held = ("its state and its lane params" if not self.tangents
                    else f"its state, its {len(self.tangents)} tangent "
                         f"vector{'s' if len(self.tangents) > 1 else ''} "
                         f"and its lane params")
            raise Refusal("lane-capacity", f"a lane holds {total:,} values "
                          f"({held}), and the deepest scratch any tile "
                          f"publishes holds {LANE_SLOTS:,}",
                          self.state_decls[0].line)
        base = 0
        self.comp_names = []
        for d in self.state_decls:
            d.base = base
            if d.length is None:
                self.comp_names.append(d.name)
                base += 1
            else:
                self.comp_names.extend(f"{d.name}[{k}]"
                                       for k in range(d.length))
                base += d.length
        self.n = base
        self.params = [self.names[n] for n, *_ in self.param_items]
        self.lanes = [self.names[n] for n, *_ in self.lane_items]

    # ==== the step ===================================================

    def step_setup(self):
        st = self.step_st
        allowed = _STEP_OPTIONS[self.integ]
        opts = {}
        for key, value, line in st.items:
            if key in opts:
                raise Refusal("step-option", f"{key} is given twice", line)
            if key not in allowed:
                raise Refusal(
                    "step-option",
                    f"{self.integ} takes {' and '.join(allowed)}; "
                    f"{key} is not one of its options"
                    + ("; q and p are stormer-verlet's" if key in ("q", "p")
                       else ""), line)
            opts[key] = (value, line)
        self.opts = opts
        if self.integ in FLOW_INTEGRATORS and "h" not in opts:
            raise Refusal("missing-step-size", f"{self.integ} needs its "
                          f"step: step {self.integ}, h = ...", st.line)
        if "h" in opts:
            expr, line = opts["h"]
            self.h_line = line
            self.h_busy = True
            v = self.evaluate(expr, self.const_ctx(line))
            self.h_busy = False
            if v.deg != 0:
                raise Refusal("cycle", "h depends on itself", line)
            if v.coef == 0:
                raise Refusal("step-size-zero", "h is exactly zero, and a "
                              "step that does not move is not a step", line)
            self.h_value = v.coef

    def partition(self):
        """stormer-verlet's positions and momenta, as flat components."""
        if self.integ != "stormer-verlet":
            self.options = None
            return
        if "q" not in self.opts or "p" not in self.opts:
            raise Refusal("verlet-partition", "stormer-verlet splits the "
                          "state into positions and momenta: give q = "
                          "(...) and p = (...)", self.step_st.line)
        seen = {}
        lists = {}
        for key in ("q", "p"):
            names, _line = self.opts[key]
            decls = []
            for nm, ln in names:
                d = self.names.get(nm)
                if d is None or d.kind != "state":
                    raise Refusal("not-state", f"{nm} is not a state "
                                  f"component", ln)
                if nm in seen:
                    raise Refusal("verlet-partition", f"{nm} is in "
                                  f"{seen[nm]} already; each component is "
                                  f"in exactly one of q and p", ln)
                seen[nm] = key
                decls.append(d)
            decls.sort(key=lambda d: d.base)
            lists[key] = decls
        for d in self.state_decls:
            if d.name not in seen:
                raise Refusal("verlet-partition", f"q and p split the "
                              f"state, each component in exactly one: "
                              f"{d.name} is in neither", self.step_st.line)
        self.q_comps = [c for d in lists["q"] for c in self._comps(d)]
        self.p_comps = [c for d in lists["p"] for c in self._comps(d)]
        self.options = {"q": [d.name for d in lists["q"]],
                        "p": [d.name for d in lists["p"]]}

    @staticmethod
    def _comps(d):
        if d.length is None:
            return [d.base]
        return list(range(d.base, d.base + d.length))

    # ==== equations ===================================================

    def equations(self):
        # a written tangent equation (d/dt v.x, next v.x) is set aside:
        # it is held to the derivation once the step is built
        self.tangent_set = set(self.tangents)
        primal = []
        for st in self.eq_stmts:
            name = st.target.name
            vec = name.split(".", 1)[0] if "." in name else None
            if vec in self.tangent_set:
                self.tan_eq_stmts.setdefault(vec, []).append(st)
            else:
                primal.append(st)
        self.eq_stmts = primal
        if not self.eq_stmts:
            raise Refusal("missing-equation", f"{self.comp_names[0]} has "
                          f"no equation", self.state_decls[0].line)
        first = self.eq_stmts[0].kind
        for st in self.eq_stmts:
            if st.kind != first:
                raise Refusal("mixed-equations", "a system is a flow (d/dt) "
                              "or a map (next), not both", st.line)
        for sts in self.tan_eq_stmts.values():
            for st in sts:
                if st.kind != first:
                    raise Refusal(
                        "mixed-equations", f"a flow's tangent equations are "
                        f"d/dt {st.target.name} = ..., a map's next "
                        f"{st.target.name} = ...: the system's own kind",
                        st.line)
        self.is_flow = first == "d/dt"
        if self.is_flow and self.integ == "map":
            raise Refusal("integrator-mismatch", "map steps a map (next); "
                          "a flow steps with rk4, euler or stormer-verlet",
                          self.step_st.line)
        if not self.is_flow and self.integ != "map":
            raise Refusal("integrator-mismatch", f"{self.integ} steps a "
                          f"flow (d/dt); a map steps with step map",
                          self.step_st.line)
        if self.exp_st is not None and not self.is_flow:
            raise Refusal("integrator-mismatch", "an expansion block writes "
                          "out a flow's step; a map's equations are its "
                          "step", self.exp_st.line)
        self.eqs = {}
        for st in self.eq_stmts:
            for comp, env in self.targets(st, st.target, st.range):
                if comp in self.eqs:
                    raise Refusal(
                        "duplicate-equation",
                        f"{self.comp_names[comp]} already has an equation,"
                        f" at line {self.eqs[comp][2]}", st.line)
                self.eqs[comp] = (st.kind, st.expr, st.line, env)
        for comp in range(self.n):
            if comp not in self.eqs:
                d = next(d for d in self.state_decls
                         if d.base <= comp < d.base + (d.length or 1))
                raise Refusal("missing-equation", f"{self.comp_names[comp]}"
                              f" has no equation", d.line)

    def targets(self, st, target, rng):
        """[(flat component, index environment)] an equation covers."""
        name = target.name
        d = self.names.get(name)
        if d is None or d.kind != "state":
            what = "not declared" if d is None else f"a {d.kind}"
            raise Refusal("not-state", f"{name} is {what}, not a state "
                          f"component", st.line)
        if d.length is None:
            if target.index is not None:
                raise Refusal("array-index", f"{name} is a scalar; it "
                              f"takes no index", st.line)
            envs = [{}] if rng is None else self.range_envs(rng)
            return [(d.base, env) for env in envs]
        if target.index is None:
            raise Refusal("array-index", f"{name} is an array of "
                          f"{d.length}: an equation names a component, "
                          f"{name}[i]", st.line)
        if rng is not None:
            envs = self.range_envs(rng)
        elif (isinstance(target.index, Name)
              and target.index.name not in self.names
              and target.index.name not in RESERVED
              and "." not in target.index.name):
            var = target.index.name
            envs = [{var: k} for k in range(d.length)]
        else:
            envs = [{}]
        out = []
        for env in envs:
            k = self.index_value(target.index, env, st.line)
            out.append((d.base + self.wrap(d, k, st.line), env))
        return out

    def range_envs(self, rng):
        var = rng.var
        if var in RESERVED:
            raise Refusal("reserved-name", f"{var} is "
                          f"{_reserved_why(var)} and cannot be an index "
                          f"variable", rng.line)
        if var in self.names:
            raise Refusal("duplicate-name", f"{var} is already declared, "
                          f"at line {self.names[var].line}; an index "
                          f"variable is a new name", rng.line)
        lo = self.index_value(rng.lo, {}, rng.line)
        hi = self.index_value(rng.hi, {}, rng.line)
        span = f"{C.shown(lo)}..{C.shown(hi)}"
        if lo > hi:
            raise Refusal("index-range", f"{span} is empty: a range "
                          f"includes both its ends and runs upward",
                          rng.line)
        if hi - lo + 1 > LANE_SLOTS:
            raise Refusal("index-range", f"{span} covers "
                          f"{C.shown(hi - lo + 1, group=True)} "
                          f"indices; a range covers at most {LANE_SLOTS:,}, "
                          f"the deepest scratch any tile publishes",
                          rng.line)
        return [{var: k} for k in range(lo, hi + 1)]

    def wrap(self, d, k, line):
        if d.cyclic:
            return k % d.length
        if not 0 <= k < d.length:
            raise Refusal("index-range", f"{d.name} has {d.length} "
                          f"components and is not cyclic: "
                          f"{d.name}[{C.shown(k)}] "
                          f"is outside 0..{d.length - 1}", line)
        return k

    def index_value(self, e, env, line):
        """An index: integer arithmetic on literals and index variables."""
        if isinstance(e, Num):
            if e.value.denominator != 1:
                raise Refusal("index-not-integer", f"an index is an "
                              f"integer; {e.text} is not one", line)
            return int(e.value)
        if isinstance(e, Name):
            if e.name in env:
                return env[e.name]
            if e.name in self.names or e.name in RESERVED:
                what = (self.names[e.name].kind if e.name in self.names
                        else _reserved_why(e.name))
                raise Refusal("index-not-integer", f"{e.name} is {what}, "
                              f"and an index is integer arithmetic on "
                              f"literals and the statement's index "
                              f"variable", line)
            raise Refusal("unbound-index", f"{e.name} is bound by nothing: "
                          f"write the equation for every component "
                          f"(d/dt x[i] = ...) or give a range (... for "
                          f"{e.name} in 0..9)", line)
        if isinstance(e, Neg):
            sign = 1
            while isinstance(e, Neg):              # a run, in a loop
                sign, e = -sign, e.arg
            return sign * self.index_value(e, env, line)
        if isinstance(e, Bin) and e.op in ("+", "-", "*"):
            chain = []
            while isinstance(e, Bin) and e.op in ("+", "-", "*"):
                chain.append(e)                    # a chain, in a loop
                e = e.left
            v = self.index_value(e, env, line)
            for b in reversed(chain):
                r = self.index_value(b.right, env, line)
                v = v + r if b.op == "+" else v - r if b.op == "-" else v * r
            return v
        raise Refusal("index-not-integer", "an index is integer "
                      "arithmetic (+, - and *) on literals and the "
                      "statement's index variable", line)

    def tangent_targets(self, st, vec):
        """[(flat component, index environment)] a tangent equation of
        `vec` covers: its target v.x or v.x[i] is the state's x or x[i]."""
        name = st.target.name
        rest = name[len(vec) + 1:]
        d = self.names.get(rest)
        if d is None or d.kind != "state":
            raise Refusal("not-state", f"{name} is not a tangent component: "
                          f"{rest} is not a state component", st.line)
        return self.targets(st, Target(rest, st.target.index,
                                       st.target.line), st.range)

    def lets(self):
        for d in list(self.names.values()):
            if d.kind != "let":
                continue
            stmts = d.defs.pop("_stmts")
            for st in stmts:
                self.let_defs(d, st.target, st.expr, st.range, st.line)
        # a written tangent let, v.r: the tangent of the let r, a family
        # of its own whose nodes carry r's label in the tangent section
        for vec, stmts in self.tan_let_stmts.items():
            fams = self.tan_lets.setdefault(vec, {})
            for st in stmts:
                name = st.target.name
                rest = name[len(vec) + 1:]
                prim = self.names.get(rest)
                if prim is None or prim.kind != "let":
                    raise Refusal("undefined-name", f"{name} names no "
                                  f"tangent let: {rest} is not a let of the "
                                  f"equations", st.line)
                fam = fams.get(name)
                if fam is None:
                    fam = fams[name] = Decl("tlet", name, st.line)
                    fam.lname = rest
                self.let_defs(fam, st.target, st.expr, st.range, st.line)
                if fam.indexed != prim.indexed:
                    raise Refusal("array-index", f"{name} is the tangent of "
                                  f"{rest}, which is "
                                  f"{'indexed' if prim.indexed else 'a scalar'}"
                                  f": write it so", st.line)
            if vec not in self.tan_eq_stmts:
                raise Refusal("missing-equation", f"{vec}'s tangent lets are "
                              f"written and its equations are not: a source "
                              f"writes all of {vec}'s equations, with its "
                              f"lets, or none", stmts[0].line)

    def let_defs(self, d, target, expr, rng, line):
        indexed = target.index is not None
        if d.indexed is None:
            d.indexed = indexed
        elif d.indexed != indexed:
            raise Refusal("duplicate-name", f"{d.name} is already declared "
                          f"as {'an indexed' if d.indexed else 'a scalar'} "
                          f"let, at line {d.line}", line)
        envs = [{}] if rng is None else self.range_envs(rng)
        for env in envs:
            if indexed:
                comp = self.index_value(target.index, env, line)
                if comp < 0:
                    raise Refusal("index-range", f"{d.name}[{comp}]: a let "
                                  f"array's components are numbered from 0",
                                  line)
            else:
                comp = None
            if comp in d.defs:
                label = d.name if comp is None else f"{d.name}[{comp}]"
                raise Refusal("duplicate-name", f"{label} is already "
                              f"defined, at line {d.defs[comp][1]}", line)
            d.defs[comp] = (expr, line, env)

    # ==== evaluation =================================================

    def const_ctx(self, line):
        c = Ctx("const")
        c.line = line
        return c

    def eval(self, e, ctx):
        # A constant that read h carries the outermost expression that read
        # it (K.hsrc): each operator below whose result is a constant made
        # from one marks it as its own, so that where the constant meets
        # the step the expression named is the whole constant written.
        if isinstance(e, Num):
            return K(e.value)
        if isinstance(e, Name):
            v = self.name_value(e.name, None, ctx, e.line)
            if e.name == "h" and isinstance(v, K):
                v = v.read_h(e, ctx.env)
            return v
        if isinstance(e, Index):
            return self.name_value(e.name, e.index, ctx, e.line)
        if isinstance(e, Neg):
            # a run of minuses, walked in a loop rather than a frame each
            negs = []
            while isinstance(e, Neg):
                negs.append(e)
                e = e.arg
            if isinstance(e, Num) and e.value == 0:
                # a minus written on a zero literal asks for -0, a sign
                # the rational cannot keep; any other constant whose
                # exact value is zero is +0, negated or not
                raise Refusal(
                    "constant-negative-zero",
                    f"-{e.text} is not a rational: a constant has no sign "
                    f"of zero, and v1 refuses a minus written on a zero "
                    f"(a constant whose exact value is 0 is +0 under every "
                    f"attribute)", negs[-1].line)
            inner = v = self.eval(e, ctx)
            for n in reversed(negs):
                v = self.negate(v, n.line)
            if isinstance(v, K) and _hread(inner):
                v = v.read_h(negs[0], ctx.env)
            return v
        if isinstance(e, Bin):
            # a left-deep chain (a + b + c ...), walked in a loop: each
            # operator still one operation, left operand first
            chain = []
            while isinstance(e, Bin):
                chain.append(e)
                e = e.left
            v = self.eval(e, ctx)
            for b in reversed(chain):
                r = self.eval(b.right, ctx)
                out = self.binary(b, v, r)
                if isinstance(out, K) and _hread(v, r):
                    out = out.read_h(b, ctx.env)
                v = out
            return v
        if isinstance(e, Cmp):
            a = self.eval(e.left, ctx)
            b = self.eval(e.right, ctx)
            op, args = {"<": ("cmplt", (a, b)), "<=": ("cmple", (a, b)),
                        ">": ("cmplt", (b, a)), ">=": ("cmple", (b, a)),
                        "==": ("cmpeq", (a, b))}[e.op]
            v = self.apply(op, list(args), e.line)
            if isinstance(v, K) and _hread(a, b):
                v = v.read_h(e, ctx.env)
            return v
        if isinstance(e, Call):
            return self.call(e, ctx)
        raise AssertionError(f"unknown expression {e!r}")

    def negate(self, v, line):
        if isinstance(v, K):
            return K(-v.coef, v.deg)          # exact; a zero stays +0
        return self.apply("neg", [v], line)

    def binary(self, e, a, b):
        # A division of constants folds exactly (8/3 is the rational); one
        # with a run-time operand is the node div, one correctly rounded
        # division - by a constant c too, RN(a / RN(c)), never a product by
        # a rounded reciprocal: x * (1/3) is that, and is another value for
        # about a third of all x (L4, 2026-10-02; it was runtime-division).
        op = {"+": "add", "-": "sub", "*": "mul", "/": "div"}[e.op]
        return self.apply(op, [a, b], e.line)

    def call(self, e, ctx):
        name = e.name
        if name in BUILTINS:
            want = BUILTINS[name]
            if len(e.args) != want:
                raise Refusal("arity", f"{name} takes {want} argument"
                              f"{'s' if want > 1 else ''}, and "
                              f"{len(e.args)} {'is' if len(e.args) == 1 else 'are'}"
                              f" given", e.line)
            vals = [self.eval(a, ctx) for a in e.args]
            if name == "select":
                c, a, b = vals
                v = self.apply("select", [a, b, c], e.line)
            else:
                v = self.apply(name, vals, e.line)
            if isinstance(v, K) and _hread(*vals):
                v = v.read_h(e, ctx.env)
            return v
        if name in TRANSCENDENTAL:
            vals = [self.eval(a, ctx) for a in e.args]
            if vals and all(isinstance(v, K) for v in vals):
                raise Refusal(
                    "irrational-constant",
                    f"{name} of a constant has no exact rational value in "
                    f"general, and v1 constants are rationals written as "
                    f"such: write the value as a decimal or a/b", e.line)
            raise Refusal("transcendental", f"{name} is not computed by a "
                          f"program in v1", e.line)
        d = self.names.get(name)
        if d is not None:
            raise Refusal("unknown-function", f"{name} is a {d.kind}, not a "
                          f"function", e.line)
        raise Refusal("unknown-function", f"{name} is not a built-in: fma, "
                      f"abs, copysign, min, max, minnum, maxnum, select and "
                      f"sqrt are", e.line)

    def name_value(self, name, index, ctx, line):
        if index is None and name in ctx.env:
            return K(ctx.env[name])
        if "." in name:
            vec = name.split(".", 1)[0]
            if vec in self.tangent_set:
                return self.tangent_value(name, vec, index, ctx, line)
            if ctx.mode == "block":
                fam = ctx.labels.get(name)
                if fam is None:
                    raise Refusal("undefined-name", f"{name} is not defined "
                                  f"in this expansion block", line)
                if ctx.tvec is not None:
                    # the block's own label, as its primal lines built it
                    return self.family_value(fam, index,
                                             ctx.primal.at(ctx.env, line),
                                             line)
                return self.family_value(fam, index, ctx, line)
            raise Refusal("undefined-name", f"{name} is a label of a "
                          f"written-out step, and names nothing here", line)
        d = self.names.get(name)
        if d is None:
            return self.undeclared(name, ctx, line)
        kind = d.kind
        if kind == "tangent":
            raise Refusal("tangent-scope", f"{name} is a tangent vector: a "
                          f"tangent equation reads its components ({name}.x),"
                          f" and nothing reads the vector whole", line)
        if kind == "state":
            if ctx.mode in ("const", "default"):
                raise self.not_constant(ctx, f"{name} is the state", line)
            if d.length is None:
                if index is not None:
                    raise Refusal("array-index", f"{name} is a scalar; it "
                                  f"takes no index", line)
                return ctx.inputs[d.base]
            if index is None:
                raise Refusal("array-index", f"{name} is an array of "
                              f"{d.length}: name a component, {name}[i]",
                              line)
            k = self.index_value(index, ctx.env, line)
            return ctx.inputs[d.base + self.wrap(d, k, line)]
        if index is not None and kind in ("param", "lane", "const"):
            raise Refusal("array-index", f"{name} is a {kind}, not an "
                          f"array", line)
        if kind in ("param", "lane"):
            if ctx.mode in ("const", "default"):
                raise self.not_constant(
                    ctx, f"{name} is a {'param' if kind == 'param' else 'lane param'}"
                    f", which belongs to the run", line)
            d.used = True
            return ("p" if kind == "param" else "l", d.index)
        if kind == "const":
            v = self.const_value(d, line)
            if v.deg != 0 and ctx.mode in ("field", "default"):
                # what h-scope keeps out is a value that moves when a
                # step-halving run halves h; a const whose value does
                # not (h/h, abs(1/(3*h))*h) is a plain rational
                raise self.h_scope(ctx, f"the const {name}'s value "
                                   f"depends on h", line, const=name)
            return v
        # a let
        if ctx.mode in ("const", "default"):
            raise self.not_constant(ctx, f"{name} is a let, which belongs to "
                                    f"the step", line)
        if ctx.mode == "block":
            raise Refusal("undefined-name", f"{name} is a let of the "
                          f"equations; an expansion block names it by its "
                          f"label in the step (k1.{name}, ...)", line)
        if ctx.tvec is not None:
            # a tangent equation reads the let's value: the primal's own
            # node, as the equations built it
            return self.family_value(d, index, ctx.primal.at(ctx.env, line),
                                     line)
        return self.family_value(d, index, ctx, line)

    def tangent_value(self, name, vec, index, ctx, line):
        """A dotted name whose prefix is a tangent vector: in that vector's
        own tangent context, a component (the tangent input) or a written
        tangent let or label; anywhere else, `tangent-scope`."""
        if ctx.tvec is None:
            where = {"const": "a constant", "default": "a default",
                     "block": "an expansion block's primal line"}.get(
                ctx.mode, "the state's equations")
            raise Refusal("tangent-scope", f"{name} is read from the "
                          f"tangent vector {vec}, and {where} cannot read a "
                          f"tangent: the state never depends on its "
                          f"tangents", line)
        if vec != ctx.tvec:
            raise Refusal("tangent-scope", f"{name} is read from {vec}, "
                          f"and these are {ctx.tvec}'s equations: one tangent "
                          f"vector never reads another", line)
        rest = name[len(vec) + 1:]
        d = self.names.get(rest)
        if d is not None and d.kind == "state":
            if d.length is None:
                if index is not None:
                    raise Refusal("array-index", f"{rest} is a scalar; "
                                  f"{name} takes no index", line)
                return ("t", d.base)
            if index is None:
                raise Refusal("array-index", f"{rest} is an array of "
                              f"{d.length}: name a component, {name}[i]",
                              line)
            k = self.index_value(index, ctx.env, line)
            return ("t", d.base + self.wrap(d, k, line))
        fam = ctx.tlabels.get(name) if ctx.tlabels else None
        if fam is not None:
            return self.family_value(fam, index, ctx, line)
        if ctx.mode == "block":
            raise Refusal("undefined-name", f"{name} is not defined in this "
                          f"expansion block", line)
        if d is not None and d.kind == "let":
            raise Refusal("undefined-name", f"{name}, the tangent of the let "
                          f"{rest}, is not written: a source that writes "
                          f"{vec}'s equations writes its tangent lets too "
                          f"(let {name} = ...)", line)
        raise Refusal("undefined-name", f"{name} names no component of {vec} "
                      f"and no tangent let: {rest} is not declared", line)

    def undeclared(self, name, ctx, line):
        if name == "h":
            if self.h_value is None and not self.h_busy:
                raise Refusal("undefined-name", "h is not declared: a map "
                              "names its step with step map, h = ...", line)
            if ctx.mode in ("field", "default"):
                raise self.h_scope(ctx, "h", line)
            if self.h_busy:
                raise Refusal("cycle", "h depends on itself", line)
            self.h_used = True
            return K(1, 1)
        if name in ("inf", "infinity"):
            raise Refusal("constant-infinity", f"{name} is not a rational, "
                          f"and v1 refuses it as a constant (an infinity "
                          f"can still arise at run time)", line)
        if name in ("nan", "snan"):
            raise Refusal("constant-nan", f"{name} is not a rational, and "
                          f"v1 refuses it as a constant (a NaN can still "
                          f"arise at run time)", line)
        if name == "t" and ctx.mode in ("field", "map", "block"):
            raise Refusal("time-dependence", "t is not declared, and v1 has "
                          "no explicit time: carry it in the state (state t,"
                          " d/dt t = 1)", line)
        if name in BUILTINS or name in TRANSCENDENTAL:
            raise Refusal("syntax", f"{name} is a function; call it with its "
                          f"arguments", line)
        raise Refusal("undefined-name", f"{name} is not declared", line)

    @staticmethod
    def not_constant(ctx, why, line):
        what = {"const": "a constant", "default": "a default"}[ctx.mode]
        return Refusal("not-constant", f"{what} is fixed when the program "
                       f"is compiled, and {why}", line)

    @staticmethod
    def h_scope(ctx, what, line, const=None):
        # A flow's sentence says the rule and its reason, never that this
        # right-hand side would move: h read directly is refused whatever
        # it folds to, and (h/h) * x would not move (D2; it said "the
        # right-hand side would move with it" until 2026-10-01).
        if ctx.mode == "field" and const is None:
            return Refusal("h-scope", "a flow's equations cannot read h, "
                           "whatever it folds to: a step-halving run halves "
                           "h, and a right-hand side must not move with it "
                           "(a const whose value does not change with h's "
                           "size, such as const c = h/h, is a plain rational "
                           "they may read)", line)
        if ctx.mode == "field":
            return Refusal("h-scope", f"a flow's equations cannot read the "
                           f"const {const}, whose value changes with h's "
                           f"size: a step-halving run halves h, and a "
                           f"right-hand side must not move with it", line)
        return Refusal("h-scope", f"a default cannot read h ({what}): a "
                       f"step-halving run halves h, and the default would "
                       f"not follow it", line)

    # ---- evaluation from the top, and definitions set aside ------------

    def evaluate(self, e, ctx):
        """eval, at the top: an equation's output, a block's next line, a
        default, h. A definition met too deep (_Deep) is set aside with the
        definitions on the path to it; each is evaluated again from here,
        innermost first, those below it on the path kept busy as they would
        be on the recursion's stack, and then the expression itself."""
        if self._limit is None:
            self._limit = _depth() + BUDGET
        pending = []              # every entry but the last is kept busy
        while True:
            try:
                if not pending:
                    return self.eval(e, ctx)
                pending[-1].again()
            except _Deep as deep:
                new = deep.path[::-1]                 # outermost first
                if pending:
                    # the outermost is the definition being evaluated
                    # again: it stays where it is, now on the path
                    del new[0]
                    self._keep(pending[-1])
                for p in new[:-1]:
                    self._keep(p)
                pending.extend(new)
                continue
            pending.pop()
            if pending:
                self._release(pending[-1])

    def _keep(self, p):
        """A definition set aside, on the path: busy, as on the stack."""
        if p.d is None:
            p.busy.add(p.key)
        else:
            p.d.busy = True
            self.const_stack.append(p.d.name)

    def _release(self, p):
        if p.d is None:
            p.busy.discard(p.key)
        else:
            p.d.busy = False
            self.const_stack.pop()

    def const_value(self, d, line, again=False):
        """A const's value, once: set aside where the stack is too deep,
        unless `evaluate` is evaluating it again (`again`)."""
        if d.value is not None:
            d.used = True
            return d.value
        if d.busy:
            path = self.const_stack[self.const_stack.index(d.name):]
            raise Refusal("cycle", f"{d.name} depends on itself: "
                          f"{', '.join(path + [d.name])}", line)
        if not again and _past(self._limit):
            raise _Deep(_Pending(None, None, d,
                                 lambda: self.const_value(d, line, True)))
        d.busy = True
        self.const_stack.append(d.name)
        try:
            v = self.eval(d.expr, self.const_ctx(d.line))
        except _Deep as deep:
            deep.path.append(_Pending(None, None, d,
                                      lambda: self.const_value(d, line, True)))
            raise
        finally:
            self.const_stack.pop()
            d.busy = False
        d.value = v
        d.used = True
        return v

    def family_value(self, d, index, ctx, line):
        if d.indexed and index is None:
            raise Refusal("array-index", f"{d.name} is an indexed let: name "
                          f"a component, {d.name}[k]", line)
        if not d.indexed and index is not None:
            raise Refusal("array-index", f"{d.name} is a scalar; it takes no "
                          f"index", line)
        comp = None if index is None else self.index_value(index, ctx.env,
                                                           line)
        if comp not in d.defs:
            have = sorted(c for c in d.defs)
            raise Refusal("index-range", f"{d.name} has no component "
                          f"{comp}: it defines {have[0]}..{have[-1]}"
                          if have else f"{d.name} defines no component",
                          line)
        return self.define(d, comp, ctx, line)

    def define(self, d, comp, ctx, line, again=False):
        """A let, label or written tangent let or label, component `comp`,
        evaluated once in a context: set aside where the stack is too deep,
        unless `evaluate` is evaluating it again (`again`)."""
        key = (d.name, comp)
        if key in ctx.memo:
            d.used_comps.add(comp)
            return ctx.memo[key]
        label = d.name if comp is None else f"{d.name}[{comp}]"
        if key in ctx.busy:
            raise Refusal("cycle", f"{label} depends on itself", line)
        if not again and _past(self._limit):
            raise _Deep(_Pending(ctx.busy, key, None,
                                 lambda: self.define(d, comp, ctx, line, True)))
        # No bound on a chain (Logan: "No limit"); were one stated, the
        # longest chain of lets would be counted here, on completion, from
        # the chains of the lets this one reads.
        ctx.busy.add(key)
        expr, sline, env = d.defs[comp]
        try:
            v = self.eval(expr, ctx.at(env, sline))
        except _Deep as deep:
            deep.path.append(_Pending(ctx.busy, key, None,
                                      lambda: self.define(d, comp, ctx, line,
                                                          True)))
            raise
        finally:
            ctx.busy.discard(key)
        if d.lname is not None:
            # a written tangent let or label: in the generic tangent
            # section it carries the label of what it is the tangent of
            label = d.lname if comp is None else f"{d.lname}[{comp}]"
        if isinstance(v, Node) and v.label is None:
            v.label = label if ctx.prefix is None else f"{ctx.prefix}.{label}"
        d.used_comps.add(comp)
        ctx.memo[key] = v
        return v

    # ==== nodes and constants =========================================

    def apply(self, op, args, line):
        if all(isinstance(a, K) for a in args):
            return self.fold(op, args, line)
        if op in ("div", "sqrt") and line is not None:
            # every statement the source writes is evaluated here - a
            # written tangent and an expansion block too, to be held to
            # what the language derives - so this meets each run-time
            # division and root at the line that holds it
            self.routine_lines.add(line)
        return Node(op, [self.leaf(a, line) if isinstance(a, K) else a
                         for a in args], line)

    def leaf(self, k, line):
        """A constant meeting a run-time operation or a step output:
        its one rounding, refused by name if it overflows or vanishes."""
        if k.deg not in (0, 1):
            raise Refusal("h-nonlinear", f"a constant here is a multiple of "
                          f"h^{k.deg}, which does not halve with h: a "
                          f"constant is a rational, or a rational multiple "
                          f"of h", line)
        self.h_meets(k)
        if k.deg == 0:
            key = (k.coef, None)
        else:
            key = (k.coef * self.h_value, k.coef)
        if key not in self.rounded:
            value = key[0]
            bits, flags = C.round_once(self.fmt, self.rnd, value)
            over = C.overflowed(flags)
            vanished = C.rounded_to_zero(self.fmt, value, bits)
            if over or vanished:
                # the test first, the sentence after: a sentence names a
                # constant briefly, whatever its size
                spell = C.brief(value) if key[1] is None else \
                    f"{C.h_form(key[1])} = {C.brief(value)}"
                where = (f"{C.FORMAT_754[self.fmt.name]} under "
                         f"{sf.RND_NAMES[self.rnd]}")
                if over:
                    raise Refusal("constant-overflow", f"{spell} overflows "
                                  f"{where}", line)
                raise Refusal("constant-rounds-to-zero", f"{spell} is not "
                              f"zero and rounds to zero in {where}", line)
            self.rounded[key] = (bits, flags)
        return ("c", key)

    def h_meets(self, k):
        """A constant of degree 0 or 1 meeting the step - a leaf, or a
        map's constant output: one that scales with h uses h; one that read
        h and does not scale is a use of h that folded away."""
        if k.deg == 1:
            self.h_scaled = True
        elif k.deg == 0 and k.hsrc is not None:
            e, env = k.hsrc
            self.h_folded.setdefault(id(e), (e, env, k.coef))

    def sign_h(self):
        return 1 if self.h_value is None or self.h_value > 0 else -1

    def fold(self, op, a, line):
        """An operation whose operands are all constants: exact."""
        def add(x, y):
            if x.coef == 0:
                return y
            if y.coef == 0:
                return x
            if x.deg != y.deg:
                # not "does not halve with h": 2 + h*h at h = 2 is 6, and 3
                # at h = 1 (D2). What is true of every such sum is the rule.
                raise Refusal("h-nonlinear", "a sum of h and a constant, or "
                              "of different powers of h, is neither a "
                              "rational nor a rational multiple of h, which "
                              "a constant is", line)
            return K(x.coef + y.coef, x.deg)

        def mul(x, y):
            return K(x.coef * y.coef, x.deg + y.deg)

        def mag(x):
            # |c h^d| as a multiple of h^d is |c| (sign h)^d. The sign is
            # +1 or -1, so (sign h)^d needs d's parity alone - for a
            # negative d too, where 1 ** -1 would be the float 1.0.
            flip = self.sign_h() < 0 and x.deg % 2 == 1
            return K(-abs(x.coef) if flip else abs(x.coef), x.deg)

        def value(x):
            # Fraction ** int is exact, a negative power included
            return x.coef * (self.h_value ** x.deg if x.deg else 1)

        if op == "add":
            r = add(a[0], a[1])
        elif op == "sub":
            r = add(a[0], K(-a[1].coef, a[1].deg))
        elif op == "mul":
            r = mul(a[0], a[1])
        elif op == "fma":
            r = add(mul(a[0], a[1]), a[2])
        elif op == "div":
            if a[1].coef == 0:
                raise Refusal("constant-division-by-zero", "this divides a "
                              "constant by a constant zero", line)
            r = K(a[0].coef / a[1].coef, a[0].deg - a[1].deg)
        elif op == "neg":
            r = K(-a[0].coef, a[0].deg)
        elif op == "abs":
            r = mag(a[0])
        elif op == "copysign":
            m = mag(a[0])
            r = K(-m.coef, m.deg) if value(a[1]) < 0 else m
        else:
            if any(x.deg != 0 for x in a):
                # The rule, true of every input that reaches it. It said
                # "is not a fixed multiple of h, and would not halve with
                # it", untrue of min(h, 2*h), which is h at h > 0, and of
                # h < 0, fixed by h's sign (the challenge suite's finding 2).
                what = "a comparison" if op in ("cmplt", "cmple", "cmpeq") \
                    else op
                raise Refusal("h-nonlinear", f"{what} of a constant that "
                              f"changes with h's size is refused, even where, "
                              f"at h's sign, the result would be fixed or a "
                              f"multiple of h: a constant is a rational or a "
                              f"rational multiple of h, and h's sign enters "
                              f"one only through copysign and abs", line)
            v = [x.coef for x in a]
            if op in ("min", "minnum"):
                r = K(min(v[0], v[1]))
            elif op in ("max", "maxnum"):
                r = K(max(v[0], v[1]))
            elif op == "cmplt":
                r = K(1 if v[0] < v[1] else 0)
            elif op == "cmple":
                r = K(1 if v[0] <= v[1] else 0)
            elif op == "cmpeq":
                r = K(1 if v[0] == v[1] else 0)
            elif op == "select":
                r = a[0] if v[2] != 0 else a[1]
            elif op == "sqrt":
                # folded where the root is exact (sqrt(9/4) is 3/2), refused
                # where no rational carries it - a constant is an exact
                # rational, and a node would round it twice (L4)
                root = C.rational_sqrt(v[0])
                if root is None:
                    raise Refusal("irrational-constant", _no_root(v[0]), line)
                r = K(root)
            else:
                raise AssertionError(op)
        if not C.in_range(r.coef):
            raise Refusal("constant-range", f"this constant's exact value "
                          f"lies beyond 2^+-{C.LIMIT_LOG2}, outside every "
                          f"format by far", line)
        return r

    # ==== the sections =================================================

    def field_call(self, comps, inputs, prefix, ctx=None):
        if ctx is None:
            ctx = Ctx("field", inputs=inputs, prefix=prefix)
        out = {}
        for comp in comps:
            _kind, expr, line, env = self.eqs[comp]
            out[comp] = self.evaluate(expr, ctx.at(env, line))
        return out

    def build_map(self):
        ctx = self.map_ctx = Ctx("map", inputs=[("s", i)
                                               for i in range(self.n)])
        outs = []
        for comp in range(self.n):
            _kind, expr, line, env = self.eqs[comp]
            outs.append(self.evaluate(expr, ctx.at(env, line)))
        return outs

    @staticmethod
    def depends(v, memo):
        """The state components a value reads, through its nodes - an
        explicit stack, so a deep graph costs no frames."""
        def leaf(a):
            if isinstance(a, tuple) and a[0] == "s":
                return frozenset((a[1],))
            return frozenset()
        if not isinstance(v, Node):
            return leaf(v)
        stack = [v]
        while stack:
            node = stack[-1]
            if id(node) in memo:
                stack.pop()
                continue
            pending = [a for a in node.args
                       if isinstance(a, Node) and id(a) not in memo]
            if pending:
                stack.extend(pending)
                continue
            stack.pop()
            got = frozenset()
            for a in node.args:
                got = got | (memo[id(a)] if isinstance(a, Node) else leaf(a))
            memo[id(node)] = got
        return memo[id(v)]

    def separable(self, field):
        memo = {}
        qs, ps = set(self.q_comps), set(self.p_comps)
        for comps, other, what, reads in (
                (self.q_comps, ps, "position", "momenta"),
                (self.p_comps, qs, "momentum", "positions")):
            for comp in comps:
                deps = self.depends(field[comp], memo)
                stray = sorted(deps - other)
                if stray:
                    names = ", ".join(self.comp_names[c] for c in stray)
                    raise Refusal(
                        "verlet-not-separable",
                        f"stormer-verlet needs a {what}'s right-hand side "
                        f"to read {reads} only: d/dt "
                        f"{self.comp_names[comp]} reads {names}",
                        self.eqs[comp][2])

    def expand(self):
        """The integrator's template, evaluated component by component
        over the field: one step, as nodes."""
        line = self.step_st.line
        leaves = [("s", i) for i in range(self.n)]
        allc = list(range(self.n))
        vectors = {"Y": {c: leaves[c] for c in allc}}
        if self.integ == "stormer-verlet":
            vectors["Q"] = {c: leaves[c] for c in self.q_comps}
            vectors["P"] = {c: leaves[c] for c in self.p_comps}
        calls = {"f": 0, "v": 0, "a": 0}
        env = dict(vectors)
        outs = {}

        def tval(e, bind=None):
            if isinstance(e, Num):
                return K(e.value)
            if isinstance(e, Name):
                if e.name == "h":
                    self.h_used = True
                    return K(1, 1)
                return env[e.name]
            if isinstance(e, Bin):
                a, b = tval(e.left), tval(e.right)
                if e.op == "/":
                    return self.fold("div", [a, b], line)
                return vop({"+": "add", "-": "sub", "*": "mul"}[e.op], [a, b])
            if isinstance(e, Call) and e.name == "fma":
                return vop("fma", [tval(x) for x in e.args])
            if isinstance(e, Call):
                arg = tval(e.args[0])
                calls[e.name] += 1
                prefix = bind or f"{e.name}{calls[e.name]}"
                inputs = list(leaves)
                for c, v in arg.items():
                    inputs[c] = v
                comps = {"f": allc, "v": getattr(self, "q_comps", None),
                         "a": getattr(self, "p_comps", None)}[e.name]
                return self.field_call(comps, inputs, prefix)
            raise AssertionError(f"template expression {e!r}")

        def vop(op, args):
            keys = None
            for x in args:
                if isinstance(x, dict):
                    if keys is not None and list(x) != keys:
                        raise AssertionError("template vectors disagree")
                    keys = list(x)
            if keys is None:
                return self.fold(op, args, line)
            return {c: self.apply(op, [x[c] if isinstance(x, dict) else x
                                       for x in args], line)
                    for c in keys}

        for st in TEMPLATES[self.integ]:
            name = st.target.name
            if st.kind == "let":
                bind = name if (isinstance(st.expr, Call)
                                and st.expr.name in ("f", "v", "a")) else None
                val = tval(st.expr, bind)
                for c, v in val.items():
                    if isinstance(v, Node) and v.label is None:
                        v.label = f"{name}.{self.comp_names[c]}"
                env[name] = val
            else:
                for c, v in tval(st.expr).items():
                    outs[c] = v
        return [outs[c] for c in allc]

    def block_build(self):
        """Evaluate a written-out expansion block: its outputs, and its
        `next` lines - before the unused check, so that what the block
        reads counts as read."""
        blk = self.exp_st
        labels = {}
        nexts = {}
        tlabels = {}            # vector -> {v.k1.x: Decl}
        tnexts = {}             # vector -> {component: (expr, line)}
        for st in blk.body:
            name = st.target.name
            vec = name.split(".", 1)[0] if "." in name else None
            if vec not in self.tangent_set:
                vec = None
            if st.range is not None:
                raise Refusal("syntax", "an expansion block writes every "
                              "component out; it takes no for", st.line)
            if st.kind == "let":
                if "." not in name:
                    raise Refusal("syntax", f"{name}: an expansion block's "
                                  f"lets are labels of the step, such as "
                                  f"k1.x", st.line)
                if vec is not None:
                    fams = tlabels.setdefault(vec, {})
                    fam = fams.get(name)
                    if fam is None:
                        fam = fams[name] = Decl("tlet", name, st.line)
                        fam.lname = name[len(vec) + 1:]
                else:
                    fam = labels.get(name)
                    if fam is None:
                        fam = labels[name] = Decl("label", name, st.line)
                self.let_defs(fam, st.target, st.expr, None, st.line)
                continue
            where = nexts if vec is None else tnexts.setdefault(vec, {})
            comps = (self.targets(st, st.target, None) if vec is None
                     else self.tangent_targets(st, vec))
            for comp, _env in comps:
                if comp in where:
                    shown = self.comp_names[comp] if vec is None else \
                        f"{vec}.{self.comp_names[comp]}"
                    raise Refusal("duplicate-equation", f"{shown} already "
                                  f"has a next in this block, at line "
                                  f"{where[comp][1]}", st.line)
                where[comp] = (st.expr, st.line)
        for comp in range(self.n):
            if comp not in nexts:
                raise Refusal("missing-equation", f"the expansion block "
                              f"gives {self.comp_names[comp]} no next",
                              blk.line)
        for vec in self.tangents:
            if vec not in tnexts and vec not in tlabels:
                continue
            for comp in range(self.n):
                if comp not in tnexts.get(vec, {}):
                    raise Refusal("missing-equation", f"the expansion block "
                                  f"gives {vec}.{self.comp_names[comp]} no "
                                  f"next: a block writes all of {vec}'s "
                                  f"lines or none", blk.line)
        ctx = self.block_ctx = Ctx("block", inputs=[("s", i)
                                                   for i in range(self.n)],
                                   labels=labels)
        outs = []
        for comp in range(self.n):
            expr, line = nexts[comp]
            outs.append(self.evaluate(expr, ctx.at({}, line)))
        touts = {}
        for vec in self.tangents:
            if vec not in tnexts:
                continue
            tctx = Ctx("block", inputs=[("s", i) for i in range(self.n)],
                       labels=labels)
            tctx.tvec, tctx.tlabels, tctx.primal = vec, tlabels.get(vec, {}), \
                ctx
            touts[vec] = ([self.evaluate(tnexts[vec][c][0],
                                         tctx.at({}, tnexts[vec][c][1]))
                           for c in range(self.n)],
                          [tnexts[vec][c][1] for c in range(self.n)],
                          tctx.tlabels)
        fams = list(labels.values()) + [f for vec in tlabels
                                        for f in tlabels[vec].values()]
        for fam in sorted(fams, key=lambda d: d.line):
            for comp in sorted(fam.defs, key=lambda c: -1 if c is None else c):
                if comp not in fam.used_comps:
                    label = fam.name if comp is None else f"{fam.name}[{comp}]"
                    raise Refusal("unused", f"{label} (line "
                                  f"{fam.defs[comp][1]}) is never used, and "
                                  f"every operation written is performed",
                                  fam.defs[comp][1])
        return outs, nexts, labels, touts

    def block_compare(self, field_outs, expansion_outs, built, tangent):
        """Hold a written-out expansion block to the template's
        expansion, byte for byte; a difference is named at the first
        label, in the order the canonical form writes them, whose
        definition differs. Then each vector whose tangent lines the
        block writes, to the derivation of the step (`tangent-mismatch`)."""
        outs, nexts, labels, touts = built
        self.block_primal_compare(field_outs, expansion_outs,
                                  (outs, nexts, labels))
        step_lines = [nexts[c][1] for c in range(self.n)]
        for vec, (vals, lines, fams) in touts.items():
            self.tangent_compare(
                "tangent_step", vec,
                self.assemble(field_outs, expansion_outs, tangent=tangent),
                self.assemble(field_outs, outs, step_lines,
                              tangent=(tangent[0], vals),
                              tangent_lines=(None, lines)),
                lines, fams, self.exp_st.line)

    def block_primal_compare(self, field_outs, expansion_outs, built):
        from .render import definitions
        outs, nexts, labels = built
        blk = self.exp_st
        want = self.assemble(field_outs, expansion_outs)
        got = self.assemble(field_outs, outs,
                            [nexts[c][1] for c in range(self.n)])
        if want.to_bytes() == got.to_bytes():
            return
        line, why = blk.line, "the bytes differ"
        lines = {}
        for fam in labels.values():
            for comp, (_e, ln, _v) in fam.defs.items():
                lines[fam.name if comp is None else f"{fam.name}[{comp}]"] = ln
        a, b = definitions(want), definitions(got)
        for label, text in a.items():
            if b.get(label) != text:
                if label in b:
                    why = (f"{label} is {b[label]} here, and {text} in the "
                           f"expansion")
                else:
                    why = f"{label} = {text} is missing"
                line = lines.get(label, blk.line)
                break
        else:
            extra = [lb for lb in b if lb not in a]
            if extra:
                why = f"{extra[0]} is not in the expansion"
                line = lines.get(extra[0], blk.line)
            elif want.const != got.const:
                why = "its constants differ from the expansion's"
            else:
                for c, (x, y) in enumerate(zip(want.step.out, got.step.out)):
                    if x != y:
                        why = f"the next of {self.comp_names[c]} differs"
                        line = nexts[c][1]
                        break
        raise Refusal("expansion-mismatch", f"the written-out step is not "
                      f"{self.integ}'s expansion: {why}", line)

    # ==== the tangent ===================================================

    def tangent_build(self, field_outs, step_outs):
        """The derivation of the field and the step (tangent.py), and
        each vector's written tangent equations held to it. -> (tangent
        field outputs or None, tangent step outputs), or None without
        tangent vectors."""
        if not self.tangents:
            return None
        line = self.tangent_items[0][1]
        zero = self.leaf(K(0), line)
        one = self.leaf(K(1), line)
        two = self.leaf(K(2), line)             # the root's rule, da / (2 * r)

        def fold(op, leaves):
            # a rule on constants alone is a constant expression: folded
            # exactly, as the language folds any, and rounded once
            ks = [K(key[0]) if key[1] is None else K(key[1], 1)
                  for _c, key in leaves]
            return self.leaf(self.fold(op, ks, line), line)

        def derived(outs):
            ts = Derivation(zero, one, fold, two).derive(outs)
            return [K(0) if t is None else t for t in ts]
        tf = derived(field_outs) if self.is_flow else None
        ts = derived(step_outs)
        written = {vec: self.tangent_equations(vec) for vec in self.tangents
                   if vec in self.tan_eq_stmts}
        if written:
            # a param or lane param a written tangent equation reads, and
            # the equations do not, has its default rounded now - so that
            # the difference is refused as one, by name
            self.defaults()
        for vec, (vals, lines) in written.items():
            self.tan_eq_lines[vec] = lines
            fams = self.tan_lets.get(vec, {})
            want = self.assemble(field_outs, step_outs, tangent=(tf, ts))
            if self.is_flow:
                got = self.assemble(field_outs, step_outs, tangent=(vals, ts),
                                    tangent_lines=(lines, None))
                self.tangent_compare("tangent_field", vec, want, got, lines,
                                     fams, self.tan_eq_stmts[vec][0].line)
            else:
                got = self.assemble(field_outs, step_outs, tangent=(tf, vals),
                                    tangent_lines=(None, lines))
                self.tangent_compare("tangent_step", vec, want, got, lines,
                                     fams, self.tan_eq_stmts[vec][0].line)
        return tf, ts

    def tangent_equations(self, vec):
        """A vector's written tangent equations, evaluated in its tangent
        context: (the outputs in component order, each one's line)."""
        sts = self.tan_eq_stmts[vec]
        eqs = {}
        for st in sts:
            for comp, env in self.tangent_targets(st, vec):
                if comp in eqs:
                    raise Refusal("duplicate-equation", f"{vec}."
                                  f"{self.comp_names[comp]} already has an "
                                  f"equation, at line {eqs[comp][1]}",
                                  st.line)
                eqs[comp] = (st.expr, st.line, env)
        for comp in range(self.n):
            if comp not in eqs:
                raise Refusal("missing-equation", f"{vec}."
                              f"{self.comp_names[comp]} has no equation: a "
                              f"source writes all of {vec}'s tangent "
                              f"equations or none", sts[0].line)
        ctx = Ctx("field" if self.is_flow else "map",
                  inputs=[("s", i) for i in range(self.n)])
        ctx.tvec = vec
        ctx.tlabels = self.tan_lets.get(vec, {})
        ctx.primal = self.field_ctx if self.is_flow else self.map_ctx
        vals = [self.evaluate(eqs[c][0], ctx.at(eqs[c][2], eqs[c][1]))
                for c in range(self.n)]
        return vals, [eqs[c][1] for c in range(self.n)]

    def tangent_compare(self, section, vec, want, got, out_lines, fams,
                        line):
        """A written tangent part against the derivation, byte for byte;
        a difference is named at the first label or component, in the
        order the canonical form writes them, whose definition differs."""
        if want.to_bytes() == got.to_bytes():
            return
        from .render import tangent_definitions
        a = tangent_definitions(want, section, vec)
        b = tangent_definitions(got, section, vec)
        lines = {}
        for fam in fams.values():
            for comp, (_e, ln, _v) in fam.defs.items():
                lines[fam.name if comp is None else f"{fam.name}[{comp}]"] = ln
        for c, comp in enumerate(self.comp_names):
            lines.setdefault(f"{vec}.{comp}", out_lines[c])
        why = "the bytes differ"
        for name, text in a.items():
            if b.get(name) != text:
                why = (f"{name} is {b[name]} here, and {text} in the "
                       f"derivation" if name in b else
                       f"{name} = {text} is missing")
                line = lines.get(name, line)
                break
        else:
            extra = [n for n in b if n not in a]
            if extra:
                why = f"{extra[0]} is not in the derivation"
                line = lines.get(extra[0], line)
        raise Refusal("tangent-mismatch", f"the tangent written for {vec} is "
                      f"not the derivation's: {why}", line)

    # ==== the graph ====================================================

    def defaults(self):
        for d in self.params + self.lanes:
            if d.expr is None:
                d.value = None
                continue
            if not d.used:
                continue
            ctx = Ctx("default")
            ctx.line = d.line
            v = self.evaluate(d.expr, ctx)
            if v.hsrc is not None:
                # a default reading a const that read h: h-scope refuses one
                # that scales, so this is a use of h that folded, outside the
                # step (verifier-VD2: once named nowhere in `unused`)
                self.h_meets(v)
            value = v.coef
            bits, flags = C.round_once(self.fmt, self.rnd, value)
            over = C.overflowed(flags)
            if over or C.rounded_to_zero(self.fmt, value, bits):
                where = (f"{C.FORMAT_754[self.fmt.name]} under "
                         f"{sf.RND_NAMES[self.rnd]}")
                if over:
                    raise Refusal("constant-overflow", f"{d.name}'s default "
                                  f"{C.brief(value)} overflows {where}",
                                  d.line)
                raise Refusal("constant-rounds-to-zero", f"{d.name}'s "
                              f"default {C.brief(value)} is not zero and "
                              f"rounds to zero in {where}", d.line)
            d.value = (value, bits, flags)

    def unused(self, outs):
        """Every declared name, let and h used, or `unused` at the first
        line that is not. `outs` are the primal equations' outputs: a map's
        constant output meets the step there, after this check."""
        tail = ", and every operation written is performed"
        found = []
        for d in self.names.values():
            if d.kind in ("const", "param", "lane") and not d.used:
                kind = "lane param" if d.kind == "lane" else d.kind
                found.append((d.line, f"the {kind} {d.name} is never "
                                      f"used{tail}"))
            elif d.kind == "let":
                for comp, (_e, ln, _env) in d.defs.items():
                    if comp not in d.used_comps:
                        label = d.name if comp is None else f"{d.name}[{comp}]"
                        found.append((ln, f"the let {label} is never "
                                          f"used{tail}"))
        if self.h_line is not None and not self.h_used:
            found.append((self.h_line, f"h is declared and never used{tail}"))
        elif self.h_line is not None and not self.h_scales(outs):
            found.append((self.h_line, self.h_folded_sentence()))
        for fams in self.tan_lets.values():
            for d in fams.values():
                for comp, (_e, ln, _env) in d.defs.items():
                    if comp not in d.used_comps:
                        label = d.name if comp is None else f"{d.name}[{comp}]"
                        found.append((ln, f"the tangent let {label} is "
                                          f"never used{tail}"))
        if found:
            line, sentence = min(found, key=lambda t: t[0])
            raise Refusal("unused", sentence, line)

    def h_scales(self, outs):
        """Whether h is used: whether a constant of the step scales with it
        (docs/LANGUAGE.md, "The step's constants"). Every leaf has met the
        step by now (h_meets); a map's constant output meets it here. A
        constant output of another power is refused `h-nonlinear` when the
        graph is assembled, as it always was, so it counts as no fold."""
        if self.h_scaled:
            return True
        other_power = False
        for v in outs:
            if isinstance(v, K):
                if v.deg in (0, 1):
                    self.h_meets(v)
                else:
                    other_power = True
        return self.h_scaled or other_power

    def h_folded_sentence(self):
        """`unused`'s sentence for an h read only where it folds away: each
        such use by line, with its value (D2, 2026-10-01: before it, the
        source was accepted and its canonical form, declaring h and reading
        it nowhere, did not read back - cftc's exit 70)."""
        uses = sorted(self.h_folded.values(), key=lambda u: u[0].line)
        shown = []
        for e, env, value in uses[:3]:
            text, where = spell(e, env)
            shown.append(f"{text} at line {e.line} is {C.brief(value)}{where}")
        if len(uses) > 3:
            shown.append(f"{len(uses) - 3:,} more")
        listed = "" if not shown else f" ({shown[0]})" if len(shown) == 1 \
            else " (" + ", ".join(shown[:-1]) + ", and " + shown[-1] + ")"
        which = "the constant" if len(uses) == 1 else "the constants"
        return (f"no constant of the step scales with h, so h is never used: "
                f"it is read only where it folds to a constant that does "
                f"not{listed}; write {which}, or leave h out of the step line")

    def assemble(self, field_outs, step_outs, step_lines=None, tangent=None,
                 tangent_lines=(None, None)):
        """The step graph of these outputs. A constant output is rounded
        here, refused at its equation's line (a flow's step at the step
        line, or the block's `next` line). With `tangent`, (the tangent
        field's outputs or None, the tangent step's), the graph is
        version 2: the primal sections as without it, then the tangent's."""
        eq_lines = [self.eqs[c][2] for c in range(self.n)]

        def leafy(vals, lines):
            if vals is None:
                return None
            return [self.leaf(v, ln) if isinstance(v, K) else v
                    for v, ln in zip(vals, lines)]
        if step_lines is None:
            step_lines = ([self.step_st.line] * self.n if self.is_flow
                          else eq_lines)
        sections = {"field": leafy(field_outs, eq_lines),
                    "step": leafy(step_outs, step_lines)}
        cross = None
        if tangent is not None:
            tf, ts = tangent
            tf_lines, ts_lines = tangent_lines
            sections["tangent_field"] = leafy(tf, tf_lines or eq_lines)
            sections["tangent_step"] = leafy(ts, ts_lines or step_lines)
            cross = PRIMAL_OF
        sections, keys = canonical(sections, cross)
        const = [(v, fa) + self.rounded[(v, fa)] for v, fa in keys]
        param = []
        for d in self.params:
            value, bits, flags = d.value
            param.append((d.name, value, bits, flags))
        lane = []
        for d in self.lanes:
            if d.value is None:
                lane.append((d.name, None, None))
            else:
                lane.append((d.name, d.value[0], d.value[1]))
        state = [(d.name, d.length) for d in self.state_decls]
        return StepGraph(self.sys_st.word, self.fmt, self.rnd, state, lane,
                         param, (self.integ, self.h_value, self.options),
                         const, sections["field"], sections["step"],
                         self.tangents if tangent is not None else (),
                         sections.get("tangent_field"),
                         sections.get("tangent_step"))

    def run(self):
        self.collect()
        self.declare()
        self.step_setup()
        self.partition()
        self.equations()
        self.lets()
        if self.is_flow:
            leaves = [("s", i) for i in range(self.n)]
            self.field_ctx = Ctx("field", inputs=leaves)
            field = self.field_call(range(self.n), leaves, None,
                                    ctx=self.field_ctx)
            field_outs = [field[c] for c in range(self.n)]
            if self.integ == "stormer-verlet":
                self.separable(field)
            step_outs = self.expand()
        else:
            field_outs = None
            step_outs = self.build_map()
        self.defaults()
        tangent = self.tangent_build(field_outs, step_outs)
        built = self.block_build() if self.exp_st is not None else None
        self.unused(field_outs if self.is_flow else step_outs)
        graph = self.assemble(field_outs, step_outs, tangent=tangent)
        slots = len(graph.param) + len(graph.const)
        if slots > BANK_SLOTS:
            raise Refusal("bank-capacity", f"{len(graph.param)} params and "
                          f"{len(graph.const)} constants: the bank holds "
                          f"{BANK_SLOTS} on every device")
        if built is not None:
            self.block_compare(field_outs, step_outs, built, tangent)
        self.canonical_nesting(graph)
        graph.routine_lines = tuple(sorted(self.routine_lines))
        return graph

    # ==== the canonical form's nesting (D2) ============================

    def canonical_nesting(self, graph):
        """A source whose canonical form would nest past what the parser
        reads is `too-deep`, at the source line of the equation or let
        whose rendered line is too deep - so that every source accepted has
        a canonical form that reads back (docs/LANGUAGE.md, "The text").
        The depth is the renderer's own, measured by nesting.py without
        writing the text; this is a rule of the language, not a read-back."""
        from .nesting import lines
        worst = None
        for _code, depth, section, what, vec in lines(graph):
            if depth <= MAX_NESTING:
                continue
            line, desc = self.nesting_source(section, what, vec)
            key = (line, -depth)
            if worst is None or key < worst[0]:
                worst = (key, desc, depth, line)
        if worst is None:
            return
        _key, desc, depth, line = worst
        raise Refusal("too-deep", f"the canonical form would write {desc} "
                      f"{C.shown(depth, group=True)} deep, and the language "
                      f"reads nesting {MAX_NESTING} deep at most: name parts "
                      f"of this line's expression with lets, which the "
                      f"canonical form keeps as names, so that its depth is "
                      f"bounded", line)

    def nesting_source(self, section, what, vec):
        """(source line, the line as the sentence names it) for a line the
        canonical form writes: `what` is ("out", component) or ("label",
        label) of `section`, written for the tangent vector `vec` in a
        tangent section. The line is the equation's or the let's - a
        written tangent equation's or tangent let's where the source writes
        one - and, for a line of the expansion block, the equation or let
        the stage evaluates."""
        tangent = section in PRIMAL_OF
        primal = PRIMAL_OF.get(section, section)
        word = "d/dt" if self.is_flow else "next"
        kind, x = what
        in_block = self.is_flow and primal == "step"
        if kind == "out":
            name = self.comp_names[x]
            line = self.eqs[x][2]
            if in_block:
                code = f"next {vec}.{name}" if tangent else f"next {name}"
                return line, f"{code}, in its expansion block,"
            if not tangent:
                return line, f"{word} {name}"
            written = self.tan_eq_lines.get(vec)
            return (written[x] if written else line,
                    f"{word} {vec}.{name}, the tangent of {word} {name},")
        label = x
        rest = label.partition(".")[2] if in_block else label
        base, _b, idx = rest.partition("[")
        comp = int(idx[:-1]) if idx else None
        d = self.names.get(base)
        if d is not None and d.kind == "let":
            line = d.defs[comp][1]
            if tangent and not in_block:
                fam = self.tan_lets.get(vec, {}).get(f"{vec}.{base}")
                if fam is not None and comp in fam.defs:
                    line = fam.defs[comp][1]
        else:                       # a stage's component: k1.x, Y2.x[3]
            # a dict, made once: list.index for each line past 100 was
            # quadratic (verifier-VD2: 1.5 s at 8,000 such components)
            if self._comp_at is None:
                self._comp_at = {c: k for k, c in enumerate(self.comp_names)}
            line = self.eqs[self._comp_at[rest]][2]
        code = f"let {vec}.{label}" if tangent else f"let {label}"
        if in_block:
            return line, f"{code}, in its expansion block,"
        if tangent:
            return line, f"{code}, the tangent of let {label},"
        return line, code


def constant_of(text):
    """The exact value of a constant written as text, by the language's
    own rules - its literals (decimal, hexadecimal significand, a/b),
    exact arithmetic, a minus written on a zero refused - or a Refusal.
    It reads no name: a run value is a number, not a program."""
    from .syntax import Parser, lex
    try:
        p = Parser(lex(text))
        e = p.expr()
        t = p.peek()
        if t.kind not in ("nl", "eof"):
            raise Refusal("syntax", f"{text!r} is one constant, and "
                          f"{t.text!r} follows it")
        if p.peek().kind == "nl":
            p.take()
            if p.peek().kind != "eof":
                raise Refusal("syntax", f"{text!r} is one constant, on one "
                              f"line")
        checker = Checker([])
        v = checker.evaluate(e, checker.const_ctx(None))
    except RecursionError:
        raise too_deep("this constant") from None
    return v.coef


def check(text, source="<text>"):
    """The step graph of a source, or a Refusal naming the source."""
    try:
        try:
            return Checker(parse(text)).run()
        except RecursionError:
            raise too_deep("this system") from None
    except Refusal as r:
        r.with_source(source)
        raise
