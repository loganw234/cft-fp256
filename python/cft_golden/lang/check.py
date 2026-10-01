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

from .. import softfloat as sf
from ..formats import FORMATS
from ..seq import SCRATCH_D_MAX
from . import constants as C
from .graph import Node, StepGraph, canonical
from .refusals import Refusal, too_deep
from .syntax import (KEYWORDS, Bin, Call, Cmp, Index, Name, Neg, Num,
                     parse)
from .templates import FLOW_INTEGRATORS, INTEGRATORS, TEMPLATES

# The built-ins and the number of arguments each takes.
BUILTINS = {"fma": 3, "abs": 1, "copysign": 2, "min": 2, "max": 2,
            "minnum": 2, "maxnum": 2, "select": 3}

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
RESERVED = (KEYWORDS | frozenset(BUILTINS) | frozenset({"sqrt", "h"})
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
    C.exact refuses one, so no binary64 can reach a constant."""
    __slots__ = ("coef", "deg")

    def __init__(self, coef, deg=0):
        self.coef = C.exact(coef)
        if not isinstance(deg, int) or isinstance(deg, bool):
            raise AssertionError(f"a constant's power of h is an integer, "
                                 f"not {deg!r}")
        self.deg = deg if self.coef != 0 else 0


class Decl:
    """A declared name."""
    __slots__ = ("kind", "name", "line", "expr", "index", "length",
                 "cyclic", "base", "value", "busy", "used", "defs",
                 "used_comps", "indexed")

    def __init__(self, kind, name, line):
        self.kind = kind              # state, const, param, lane, let, label
        self.name = name
        self.line = line
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
    __slots__ = ("mode", "inputs", "memo", "busy", "prefix", "env", "line",
                 "labels")

    def __init__(self, mode, inputs=None, prefix=None, labels=None):
        self.mode = mode
        self.inputs = inputs
        self.memo = {}
        self.busy = set()
        self.prefix = prefix
        self.env = {}
        self.line = None
        self.labels = labels

    def at(self, env, line):
        c = Ctx.__new__(Ctx)
        c.mode, c.inputs, c.memo, c.busy = (self.mode, self.inputs,
                                            self.memo, self.busy)
        c.prefix, c.labels = self.prefix, self.labels
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
        self.h_used = False
        self.h_line = None

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
        items.sort(key=lambda t: (t[0], t[1]))
        n_param = n_lane = 0
        for line, _o, kind, name, payload in items:
            if "." in name:
                raise Refusal("syntax", f"{name} is a label: a dotted name "
                              f"is defined only in an expansion block",
                              line)
            if name in RESERVED:
                raise Refusal("reserved-name", f"{name} is "
                              f"{_reserved_why(name)} and cannot name a "
                              f"value", line)
            prev = self.names.get(name)
            if prev is not None:
                if kind == "let" and prev.kind == "let":
                    prev.defs.setdefault("_stmts", []).append(payload)
                    continue
                raise Refusal("duplicate-name", f"{name} is already "
                              f"declared, at line {prev.line}", line)
            d = Decl(kind, name, line)
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
        total = sum(1 if d.length is None else d.length
                    for d in self.state_decls) + n_lane
        if total > LANE_SLOTS:
            raise Refusal("lane-capacity", f"a lane holds {total:,} values "
                          f"(its state and its lane params), and the deepest "
                          f"scratch any tile publishes holds {LANE_SLOTS:,}",
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
            v = self.eval(expr, self.const_ctx(line))
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
        if not self.eq_stmts:
            raise Refusal("missing-equation", f"{self.comp_names[0]} has "
                          f"no equation", self.state_decls[0].line)
        first = self.eq_stmts[0].kind
        for st in self.eq_stmts:
            if st.kind != first:
                raise Refusal("mixed-equations", "a system is a flow (d/dt) "
                              "or a map (next), not both", st.line)
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

    def lets(self):
        for d in list(self.names.values()):
            if d.kind != "let":
                continue
            stmts = d.defs.pop("_stmts")
            for st in stmts:
                self.let_defs(d, st.target, st.expr, st.range, st.line)

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
        if isinstance(e, Num):
            return K(e.value)
        if isinstance(e, Name):
            return self.name_value(e.name, None, ctx, e.line)
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
            v = self.eval(e, ctx)
            for n in reversed(negs):
                v = self.negate(v, n.line)
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
                v = self.binary(b, v, self.eval(b.right, ctx))
            return v
        if isinstance(e, Cmp):
            a = self.eval(e.left, ctx)
            b = self.eval(e.right, ctx)
            op, args = {"<": ("cmplt", (a, b)), "<=": ("cmple", (a, b)),
                        ">": ("cmplt", (b, a)), ">=": ("cmple", (b, a)),
                        "==": ("cmpeq", (a, b))}[e.op]
            return self.apply(op, list(args), e.line)
        if isinstance(e, Call):
            return self.call(e, ctx)
        raise AssertionError(f"unknown expression {e!r}")

    def negate(self, v, line):
        if isinstance(v, K):
            return K(-v.coef, v.deg)          # exact; a zero stays +0
        return self.apply("neg", [v], line)

    def binary(self, e, a, b):
        if e.op == "/":
            if isinstance(a, K) and isinstance(b, K):
                return self.fold("div", [a, b], e.line)
            raise Refusal(
                "runtime-division",
                "this divides at run time, which v1 does not; for a "
                "constant divisor multiply by its reciprocal, x * (1/3)"
                " - one rounding of 1/3, then one of the product", e.line)
        op = {"+": "add", "-": "sub", "*": "mul"}[e.op]
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
                return self.apply("select", [a, b, c], e.line)
            return self.apply(name, vals, e.line)
        if name == "sqrt" or name in TRANSCENDENTAL:
            vals = [self.eval(a, ctx) for a in e.args]
            if vals and all(isinstance(v, K) for v in vals):
                raise Refusal(
                    "irrational-constant",
                    f"{name} of a constant has no exact rational value in "
                    f"general, and v1 constants are rationals written as "
                    f"such: write the value as a decimal or a/b", e.line)
            if name == "sqrt":
                raise Refusal("runtime-sqrt", "v1 has no square root at run "
                              "time", e.line)
            raise Refusal("transcendental", f"{name} is not computed by a "
                          f"program in v1", e.line)
        d = self.names.get(name)
        if d is not None:
            raise Refusal("unknown-function", f"{name} is a {d.kind}, not a "
                          f"function", e.line)
        raise Refusal("unknown-function", f"{name} is not a built-in: fma, "
                      f"abs, copysign, min, max, minnum, maxnum and select "
                      f"are", e.line)

    def name_value(self, name, index, ctx, line):
        if index is None and name in ctx.env:
            return K(ctx.env[name])
        if "." in name:
            if ctx.mode == "block":
                fam = ctx.labels.get(name)
                if fam is None:
                    raise Refusal("undefined-name", f"{name} is not defined "
                                  f"in this expansion block", line)
                return self.family_value(fam, index, ctx, line)
            raise Refusal("undefined-name", f"{name} is a label of a "
                          f"written-out step, and names nothing here", line)
        d = self.names.get(name)
        if d is None:
            return self.undeclared(name, ctx, line)
        kind = d.kind
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
                                   f"depends on h", line)
            return v
        # a let
        if ctx.mode in ("const", "default"):
            raise self.not_constant(ctx, f"{name} is a let, which belongs to "
                                    f"the step", line)
        if ctx.mode == "block":
            raise Refusal("undefined-name", f"{name} is a let of the "
                          f"equations; an expansion block names it by its "
                          f"label in the step (k1.{name}, ...)", line)
        return self.family_value(d, index, ctx, line)

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
        if name in BUILTINS or name == "sqrt" or name in TRANSCENDENTAL:
            raise Refusal("syntax", f"{name} is a function; call it with its "
                          f"arguments", line)
        raise Refusal("undefined-name", f"{name} is not declared", line)

    @staticmethod
    def not_constant(ctx, why, line):
        what = {"const": "a constant", "default": "a default"}[ctx.mode]
        return Refusal("not-constant", f"{what} is fixed when the program "
                       f"is compiled, and {why}", line)

    @staticmethod
    def h_scope(ctx, what, line):
        if ctx.mode == "field":
            return Refusal("h-scope", f"a flow's equations cannot read h "
                           f"({what}): a step-halving run halves h, and the "
                           f"right-hand side would move with it", line)
        return Refusal("h-scope", f"a default cannot read h ({what}): a "
                       f"step-halving run halves h, and the default would "
                       f"not follow it", line)

    def const_value(self, d, line):
        if d.value is not None:
            d.used = True
            return d.value
        if d.busy:
            path = self.const_stack[self.const_stack.index(d.name):]
            raise Refusal("cycle", f"{d.name} depends on itself: "
                          f"{', '.join(path + [d.name])}", line)
        d.busy = True
        self.const_stack.append(d.name)
        v = self.eval(d.expr, self.const_ctx(d.line))
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
        key = (d.name, comp)
        if key in ctx.memo:
            d.used_comps.add(comp)
            return ctx.memo[key]
        label = d.name if comp is None else f"{d.name}[{comp}]"
        if key in ctx.busy:
            raise Refusal("cycle", f"{label} depends on itself", line)
        ctx.busy.add(key)
        expr, sline, env = d.defs[comp]
        v = self.eval(expr, ctx.at(env, sline))
        ctx.busy.discard(key)
        if isinstance(v, Node) and v.label is None:
            v.label = label if ctx.prefix is None else f"{ctx.prefix}.{label}"
        d.used_comps.add(comp)
        ctx.memo[key] = v
        return v

    # ==== nodes and constants =========================================

    def apply(self, op, args, line):
        if all(isinstance(a, K) for a in args):
            return self.fold(op, args, line)
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
                raise Refusal("h-nonlinear", "a sum of h and a constant, or "
                              "of different powers of h, does not halve "
                              "with h: a constant is a rational, or a "
                              "rational multiple of h", line)
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
                raise Refusal("h-nonlinear", f"{op} of a constant that "
                              f"depends on h is not a fixed multiple of h, "
                              f"and would not halve with it", line)
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
            else:
                raise AssertionError(op)
        if not C.in_range(r.coef):
            raise Refusal("constant-range", f"this constant's exact value "
                          f"lies beyond 2^+-{C.LIMIT_LOG2}, outside every "
                          f"format by far", line)
        return r

    # ==== the sections =================================================

    def field_call(self, comps, inputs, prefix):
        ctx = Ctx("field", inputs=inputs, prefix=prefix)
        out = {}
        for comp in comps:
            _kind, expr, line, env = self.eqs[comp]
            out[comp] = self.eval(expr, ctx.at(env, line))
        return out

    def build_map(self):
        ctx = Ctx("map", inputs=[("s", i) for i in range(self.n)])
        outs = []
        for comp in range(self.n):
            _kind, expr, line, env = self.eqs[comp]
            outs.append(self.eval(expr, ctx.at(env, line)))
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
        for st in blk.body:
            if st.kind == "let":
                name = st.target.name
                if "." not in name:
                    raise Refusal("syntax", f"{name}: an expansion block's "
                                  f"lets are labels of the step, such as "
                                  f"k1.x", st.line)
                if st.range is not None:
                    raise Refusal("syntax", "an expansion block writes "
                                  "every component out; it takes no for",
                                  st.line)
                fam = labels.get(name)
                if fam is None:
                    fam = labels[name] = Decl("label", name, st.line)
                self.let_defs(fam, st.target, st.expr, None, st.line)
            else:
                if st.range is not None:
                    raise Refusal("syntax", "an expansion block writes "
                                  "every component out; it takes no for",
                                  st.line)
                for comp, _env in self.targets(st, st.target, None):
                    if comp in nexts:
                        raise Refusal(
                            "duplicate-equation",
                            f"{self.comp_names[comp]} already has a next "
                            f"in this block, at line {nexts[comp][1]}",
                            st.line)
                    nexts[comp] = (st.expr, st.line)
        for comp in range(self.n):
            if comp not in nexts:
                raise Refusal("missing-equation", f"the expansion block "
                              f"gives {self.comp_names[comp]} no next",
                              blk.line)
        ctx = Ctx("block", inputs=[("s", i) for i in range(self.n)],
                  labels=labels)
        outs = []
        for comp in range(self.n):
            expr, line = nexts[comp]
            outs.append(self.eval(expr, ctx.at({}, line)))
        for fam in sorted(labels.values(), key=lambda d: d.line):
            for comp in sorted(fam.defs, key=lambda c: -1 if c is None else c):
                if comp not in fam.used_comps:
                    label = fam.name if comp is None else f"{fam.name}[{comp}]"
                    raise Refusal("unused", f"{label} (line "
                                  f"{fam.defs[comp][1]}) is never used, and "
                                  f"every operation written is performed",
                                  fam.defs[comp][1])
        return outs, nexts, labels

    def block_compare(self, field_outs, expansion_outs, built):
        """Hold a written-out expansion block to the template's
        expansion, byte for byte; a difference is named at the first
        label, in the order the canonical form writes them, whose
        definition differs."""
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
            v = self.eval(d.expr, ctx)
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

    def unused(self):
        found = []
        for d in self.names.values():
            if d.kind in ("const", "param", "lane") and not d.used:
                kind = "lane param" if d.kind == "lane" else d.kind
                found.append((d.line, f"the {kind} {d.name} is never used"))
            elif d.kind == "let":
                for comp, (_e, ln, _env) in d.defs.items():
                    if comp not in d.used_comps:
                        label = d.name if comp is None else f"{d.name}[{comp}]"
                        found.append((ln, f"the let {label} is never used"))
        if self.h_line is not None and not self.h_used:
            found.append((self.h_line, "h is declared and never used"))
        if found:
            line, what = min(found, key=lambda t: t[0])
            raise Refusal("unused", f"{what}, and every operation written "
                          f"is performed", line)

    def assemble(self, field_outs, step_outs, step_lines=None):
        """The step graph of these outputs. A constant output is rounded
        here, refused at its equation's line (a flow's step at the step
        line, or the block's `next` line)."""
        eq_lines = [self.eqs[c][2] for c in range(self.n)]

        def leafy(vals, lines):
            if vals is None:
                return None
            return [self.leaf(v, ln) if isinstance(v, K) else v
                    for v, ln in zip(vals, lines)]
        if step_lines is None:
            step_lines = ([self.step_st.line] * self.n if self.is_flow
                          else eq_lines)
        sections, keys = canonical({"field": leafy(field_outs, eq_lines),
                                    "step": leafy(step_outs, step_lines)})
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
                         const, sections["field"], sections["step"])

    def run(self):
        self.collect()
        self.declare()
        self.step_setup()
        self.partition()
        self.equations()
        self.lets()
        if self.is_flow:
            leaves = [("s", i) for i in range(self.n)]
            field = self.field_call(range(self.n), leaves, None)
            field_outs = [field[c] for c in range(self.n)]
            if self.integ == "stormer-verlet":
                self.separable(field)
            step_outs = self.expand()
        else:
            field_outs = None
            step_outs = self.build_map()
        self.defaults()
        built = self.block_build() if self.exp_st is not None else None
        self.unused()
        graph = self.assemble(field_outs, step_outs)
        slots = len(graph.param) + len(graph.const)
        if slots > BANK_SLOTS:
            raise Refusal("bank-capacity", f"{len(graph.param)} params and "
                          f"{len(graph.const)} constants: the bank holds "
                          f"{BANK_SLOTS} on every device")
        if built is not None:
            self.block_compare(field_outs, step_outs, built)
        return graph


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
        v = checker.eval(e, checker.const_ctx(None))
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
