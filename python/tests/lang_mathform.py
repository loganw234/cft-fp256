# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The mathematical form, read back and evaluated exactly - the test's
own reader, sharing no code with the renderer (cft_golden/lang/render.py)
or the language's parser.

The intention-out's mathematical form is a promise that the equations a
writer reads are the equations the step graph holds. This module holds
it: it parses the form's notation (σ·(y − x), [a < b], |x|, Y ↦ ...,
k2 = f(Y + (h/2)·k1)) and evaluates it in Fractions, and
python/tests/test_lang.py compares the result with the step graph's own
exact evaluation at random rational points - the right-hand sides, and
the whole step through the template's scheme.

Values are bound by POSITION, never by glyph: the state by the order of
the form's own `Y = (...)` line, the params and lane params by the order
of their sections. So a renderer that printed a Greek letter wrong would
still be read correctly here - while one that wrote a wrong operation
or a wrong constant would not. The glyphs, and every other line the
form prints, are held by test_lang.py's check_comments.

A number is read at any length: Python's int() stops at 4,300 digits,
and a constant may have more (verifier-VL1), so a long one is read with
the limit lifted for that one conversion, as the golden model's
chars._int_from_digits does.

A system with tangent vectors (L3) prints, for each vector, its
variational equations (d(v.x)/dt = ...) or a map's tangent lines
(v.x ↦ ...), and a flow's tangent step: the same method on δY, where
Df(Z)·W is the variational right-hand sides at the state Z along the
tangent W. They are read here too, and evaluated exactly: a vector is
bound by the ORDER its sections appear in, its components by the order
of its δY line or of its equations - never by the glyph.
"""

import re
import sys
from fractions import Fraction

MINUS, DOT, MAPSTO, LE, NE = "−", "·", "↦", "≤", "≠"


class MathFormError(ValueError):
    pass


def _int(digits):
    """A string of decimal digits as an int, at any length."""
    try:
        return int(digits)
    except ValueError:
        if not digits.isdigit():
            raise
        old = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(0)
        try:
            return int(digits)
        finally:
            sys.set_int_max_str_digits(old)


def _number(text):
    """d[.d][e[+-]d], exactly, at any length."""
    mant, _e, exp = text.partition("e")
    whole, _dot, frac = mant.partition(".")
    if not (whole + frac).isdigit():
        raise MathFormError(f"{text!r} is not a number")
    value = Fraction(_int(whole + frac))
    k = (int(exp) if exp else 0) - len(frac)
    return value * 10 ** k if k >= 0 else value / 10 ** -k


def _tokens(text):
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == " ":
            i += 1
            continue
        if c.isdigit():
            j = i
            while i < n and (text[i].isdigit() or text[i] == "."):
                i += 1
            if i < n and text[i] == "e":
                i += 1
                if i < n and text[i] in "+-":
                    i += 1
                while i < n and text[i].isdigit():
                    i += 1
            out.append(("num", _number(text[j:i])))
            continue
        if c.isalpha() or c == "_":
            j = i
            while True:
                while i < n and (text[i].isalnum() or text[i] == "_"):
                    i += 1
                if i < n and text[i] == "[" and text[i + 1:i + 2].isdigit():
                    k = text.index("]", i)
                    i = k + 1
                # a dotted name - a tangent's v.x, v.r - is one name
                if i + 1 < n and text[i] == "." and \
                        (text[i + 1].isalpha() or text[i + 1] == "_"):
                    i += 1
                    continue
                break
            out.append(("name", text[j:i]))
            continue
        out.append(("op", c))
        i += 1
    out.append(("end", None))
    return out


class _Expr:
    """A parsed expression: a tree of tuples."""

    def __init__(self, text):
        self.toks = _tokens(text)
        self.i = 0
        self.tree = self.sum()
        if self.toks[self.i][0] != "end":
            raise MathFormError(f"trailing {self.toks[self.i]} in {text!r}")

    def peek(self):
        return self.toks[self.i]

    def take(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, op):
        t = self.take()
        if t != ("op", op):
            raise MathFormError(f"expected {op!r}, found {t}")

    def sum(self):
        left = self.term()
        while self.peek() in (("op", "+"), ("op", MINUS)):
            op = self.take()[1]
            left = ("add" if op == "+" else "sub", left, self.term())
        return left

    def term(self):
        left = self.unary()
        while self.peek() in (("op", DOT), ("op", "/")):
            op = self.take()[1]
            left = ("mul" if op == DOT else "div", left, self.unary())
        return left

    def unary(self):
        count = 0
        while self.peek() == ("op", MINUS):      # a run, in a loop
            self.take()
            count += 1
        tree = self.atom()
        for _ in range(count):
            tree = ("neg", tree)
        return tree

    def atom(self):
        t = self.take()
        if t[0] == "num":
            return ("num", t[1])
        if t[0] == "name":
            if self.peek() == ("op", "("):
                self.take()
                args = [self.sum()]
                while self.peek() == ("op", ","):
                    self.take()
                    args.append(self.sum())
                self.expect(")")
                return ("call", t[1], args)
            return ("name", t[1])
        if t == ("op", "("):
            inner = self.sum()
            if self.peek() == ("name", "if"):
                self.take()
                cond = self.sum()
                self.expect(NE)
                zero = self.take()
                if zero != ("num", 0):
                    raise MathFormError("a selection compares with 0")
                if self.take() != ("name", "else"):
                    raise MathFormError("expected else")
                other = self.sum()
                self.expect(")")
                return ("select", cond, inner, other)
            self.expect(")")
            return inner
        if t == ("op", "|"):
            inner = self.sum()
            self.expect("|")
            return ("abs", inner)
        if t == ("op", "["):
            left = self.sum()
            op = self.take()
            if op not in (("op", "<"), ("op", LE), ("op", "=")):
                raise MathFormError(f"expected a comparison, found {op}")
            right = self.sum()
            self.expect("]")
            return ("cmp", op[1], left, right)
        raise MathFormError(f"unexpected {t}")


class Vec:
    """A vector of the step: component name -> value, in order."""

    def __init__(self, names, values):
        self.names = list(names)
        self.v = dict(zip(self.names, values))

    def map2(self, other, fn):
        if isinstance(other, Vec):
            if other.names != self.names:
                raise MathFormError("vectors over different components")
            return Vec(self.names, [fn(self.v[k], other.v[k])
                                    for k in self.names])
        return Vec(self.names, [fn(self.v[k], other) for k in self.names])


class Op:
    """Df(Z), Dv(Z) or Da(Z): the variational right-hand sides of one
    tangent vector at the state Z, a linear map waiting for its tangent;
    `scale` is a constant it has been multiplied by (h·Df(Y)·δY)."""

    def __init__(self, form, fn, z, env, scale=Fraction(1)):
        self.form, self.fn, self.z, self.env = form, fn, z, env
        self.scale = scale

    def scaled(self, s):
        return Op(self.form, self.fn, self.z, self.env, self.scale * s)

    def apply(self, w):
        out = self.form._tangent_call(self.fn, self.z, w, self.env)
        return out.map2(self.scale, lambda x, s: x * s)


def _arith(op, a, b):
    fn = {"add": lambda x, y: x + y, "sub": lambda x, y: x - y,
          "mul": lambda x, y: x * y, "div": lambda x, y: x / y}[op]
    if isinstance(a, Op) or isinstance(b, Op):
        if op != "mul":
            raise MathFormError(f"{op} of a tangent's map")
        if isinstance(a, Op) and isinstance(b, Vec):
            return a.apply(b)
        if isinstance(b, Op) and not isinstance(a, (Op, Vec)):
            return b.scaled(a)
        if isinstance(a, Op) and not isinstance(b, (Op, Vec)):
            return a.scaled(b)
        raise MathFormError("a tangent's map applied to no tangent")
    if isinstance(a, Vec):
        return a.map2(b, fn)
    if isinstance(b, Vec):
        if op not in ("mul", "add"):
            raise MathFormError(f"scalar {op} vector")
        return b.map2(a, lambda x, y: fn(y, x))
    return fn(a, b)


_TFIELD = "the variational equations of the tangent vector "
_TMAP = "the tangent of the map, along the tangent vector "
_TSTEP = re.compile(r"the tangent (\S+)'s step: ")


class MathForm:
    def __init__(self, text):
        self.params, self.lanes = [], []
        self.where = {}             # name -> tree (tangent lets: v.r)
        self.equations = {}         # component -> tree
        self.step_lines = []        # ("def", name, tree) or ("map", name, tree)
        self.vectors = {}           # Y, Q, P -> [component]
        self.h = None
        self.kind = None
        # each tangent vector, in the order its sections appear
        self.tvectors = []
        self.tangent_eqs = {}       # vector -> {component: tree}
        self.tangent_map = {}       # vector -> [(component, tree)]
        self.tangent_steps = {}     # vector -> [("def"|"map", name, tree)]
        self.tangent_vecs = {}      # vector -> {δY, δQ, δP: [component]}
        section = None
        for raw in text.splitlines():
            if not raw.strip():
                continue
            if not raw.startswith("  "):
                m = _TSTEP.match(raw)
                if raw.startswith(_TFIELD) or raw.startswith(_TMAP):
                    vec = raw.split(" ")[-1]
                    section = ("tfield" if raw.startswith(_TFIELD)
                               else "tmap", vec)
                    self._vector(vec)
                    continue
                if m:
                    section = ("tstep", m.group(1))
                    self._vector(m.group(1))
                    continue
                head = raw.split(",")[0].split(":")[0]
                section = {"parameters": "params",
                           "lane parameters": "lanes", "where": "where",
                           "the equations": "eqs",
                           "one step": "step"}.get(head)
                continue
            line = raw.strip()
            if isinstance(section, tuple):
                self._tangent_line(section, line)
                continue
            if section == "params" or section == "lanes":
                name = line.split(" = ")[0]
                (self.params if section == "params" else self.lanes).append(
                    name)
            elif section == "where":
                name, rhs = line.split(" = ", 1)
                self.where[name] = _Expr(rhs).tree
            elif section == "eqs":
                lhs, rhs = line.split(" = ", 1)
                if not (lhs.startswith("d") and lhs.endswith("/dt")):
                    raise MathFormError(f"not an equation: {line!r}")
                self.equations[lhs[1:-3]] = _Expr(rhs).tree
                self.kind = "flow"
            elif section == "step":
                if f" {MAPSTO} " in line:
                    name, rhs = line.split(f" {MAPSTO} ", 1)
                    self.step_lines.append(("map", name, _Expr(rhs).tree))
                    continue
                name, rhs = line.split(" = ", 1)
                if name == "h":
                    self.h = _Expr(rhs).tree
                elif rhs.startswith("(") and name in ("Y", "Q", "P"):
                    self.vectors[name] = [c.strip() for c in
                                          rhs[1:-1].split(",")]
                else:
                    self.step_lines.append(("def", name, _Expr(rhs).tree))
        if self.kind is None:
            self.kind = "map"

    def _vector(self, vec):
        if vec not in self.tvectors:
            self.tvectors.append(vec)
            self.tangent_eqs[vec] = {}
            self.tangent_map[vec] = []
            self.tangent_steps[vec] = []
            self.tangent_vecs[vec] = {}

    def _plain(self, vec, name):
        """v.x -> x: a tangent component as the state's component."""
        if not name.startswith(vec + "."):
            raise MathFormError(f"{name} is not a component of {vec}")
        return name[len(vec) + 1:]

    def _tangent_line(self, section, line):
        kind, vec = section
        if kind == "tstep":
            if f" {MAPSTO} " in line:
                name, rhs = line.split(f" {MAPSTO} ", 1)
                self.tangent_steps[vec].append(("map", name, _Expr(rhs).tree))
                return
            name, rhs = line.split(" = ", 1)
            if name in ("δY", "δQ", "δP") and rhs.startswith("("):
                self.tangent_vecs[vec][name] = [
                    self._plain(vec, c.strip()) for c in rhs[1:-1].split(",")]
            else:
                self.tangent_steps[vec].append(("def", name, _Expr(rhs).tree))
            return
        if kind == "tmap" and f" {MAPSTO} " in line:
            name, rhs = line.split(f" {MAPSTO} ", 1)
            self.tangent_map[vec].append((self._plain(vec, name),
                                          _Expr(rhs).tree))
            return
        lhs, rhs = line.split(" = ", 1)
        if kind == "tfield" and lhs.startswith("d(") and lhs.endswith(")/dt"):
            self.tangent_eqs[vec][self._plain(vec, lhs[2:-4])] = \
                _Expr(rhs).tree
            return
        self._plain(vec, lhs)               # a tangent let: v.r
        self.where[lhs] = _Expr(rhs).tree

    # -- evaluation -----------------------------------------------------

    def _eval(self, t, env):
        kind = t[0]
        if kind == "num":
            return t[1]
        if kind == "name":
            return env.lookup(t[1])
        if kind in ("add", "sub", "mul", "div"):
            # a left-deep chain, in a loop
            spine = []
            while t[0] in ("add", "sub", "mul", "div"):
                spine.append(t)
                t = t[1]
            v = self._eval(t, env)
            for node in reversed(spine):
                v = _arith(node[0], v, self._eval(node[2], env))
            return v
        if kind == "neg":
            count = 0
            while t[0] == "neg":                    # a run, in a loop
                count += 1
                t = t[1]
            v = self._eval(t, env)
            if count % 2:
                v = v.map2(0, lambda x, _y: -x) if isinstance(v, Vec) else -v
            return v
        if kind == "abs":
            return abs(self._eval(t[1], env))
        if kind == "cmp":
            a, b = self._eval(t[2], env), self._eval(t[3], env)
            truth = {"<": a < b, LE: a <= b, "=": a == b}[t[1]]
            return Fraction(1 if truth else 0)
        if kind == "select":
            c = self._eval(t[1], env)
            return self._eval(t[2], env) if c != 0 else self._eval(t[3], env)
        if kind == "call":
            name, args = t[1], t[2]
            if name in ("f", "v", "a"):
                return self._field_call(name, self._eval(args[0], env), env)
            if name in ("Df", "Dv", "Da"):
                return Op(self, name[1:], self._eval(args[0], env), env)
            vals = [self._eval(a, env) for a in args]
            if name in ("min", "minNum"):
                return min(vals)
            if name in ("max", "maxNum"):
                return max(vals)
            if name == "copysign":
                return -abs(vals[0]) if vals[1] < 0 else abs(vals[0])
            raise MathFormError(f"unknown function {name}")
        raise MathFormError(f"unknown node {kind}")

    def _field_call(self, fn, arg, env):
        comps = self.vectors["Y"]
        if fn == "f":
            outs = comps
        elif fn == "v":
            outs = self.vectors["Q"]
        else:
            outs = self.vectors["P"]
        bound = dict(zip(arg.names, (arg.v[k] for k in arg.names)))
        inner = _Env(self, bound, env.globals)
        return Vec(outs, [self._eval(self.equations[c], inner)
                          for c in outs])

    def _tangent_call(self, fn, z, w, env):
        """Df(Z)·W: the variational equations of the vector being read,
        at the state Z (its components bound by name) along the tangent
        W (bound as v.x ...), for the components fn has: all for f, the
        positions for v, the momenta for a."""
        vec = env.vec
        outs = {"f": self.vectors["Y"], "v": self.vectors.get("Q"),
                "a": self.vectors.get("P")}[fn]
        bound = dict(zip(z.names, (z.v[k] for k in z.names)))
        for c in w.names:
            bound[f"{vec}.{c}"] = w.v[c]
        inner = _Env(self, bound, env.globals)
        inner.vec = vec
        return Vec(outs, [self._eval(self.tangent_eqs[vec][c], inner)
                          for c in outs])

    def _tangent_env(self, k, state, tangent, params, lanes):
        vec = self.tvectors[k]
        comps = self.vectors["Y"]
        bound = dict(zip(comps, state))
        bound.update((f"{vec}.{c}", t) for c, t in zip(comps, tangent))
        env = _Env(self, bound, self._globals(list(params), list(lanes)))
        env.vec = vec
        return vec, comps, env

    def tangent_field(self, k, state, tangent, params=(), lanes=()):
        """The k-th vector's variational equations at (state, tangent)."""
        vec, comps, env = self._tangent_env(k, state, tangent, params, lanes)
        return [self._eval(self.tangent_eqs[vec][c], env) for c in comps]

    def tangent_step(self, k, state, tangent, params=(), lanes=()):
        """The k-th vector's tangent after one step: a map's tangent
        lines, or a flow's tangent step - the primal scheme run first,
        for its stages, then the tangent's."""
        vec, comps, env = self._tangent_env(k, state, tangent, params, lanes)
        if self.kind == "map":
            got = {c: self._eval(t, env) for c, t in self.tangent_map[vec]}
            return [got[c] for c in comps]
        for name, names in self.vectors.items():
            env.locals[name] = Vec(names, [env.locals[c] for c in names])
        for kind, name, tree in self.step_lines:
            if kind == "def":
                env.locals[name] = self._eval(tree, env)
        tb = dict(zip(comps, tangent))
        for name, names in self.tangent_vecs[vec].items():
            env.locals[name] = Vec(names, [tb[c] for c in names])
        nxt = {}
        for kind, name, tree in self.tangent_steps[vec]:
            value = self._eval(tree, env)
            if kind == "def":
                env.locals[name] = value
            elif isinstance(value, Vec):
                for c in self.tangent_vecs[vec][name]:
                    nxt[c] = value.v[c]
            else:
                raise MathFormError(f"{name} maps to no vector")
        return [nxt[c] for c in comps]

    def _globals(self, params, lanes):
        if len(params) != len(self.params) or len(lanes) != len(self.lanes):
            raise MathFormError("the values do not match the form's "
                                "parameters")
        g = dict(zip(self.params, params))
        g.update(zip(self.lanes, lanes))
        if self.h is not None:
            g["h"] = self._eval(self.h, _Env(self, {}, {}))
        return g

    def field(self, state, params=(), lanes=()):
        """The right-hand sides at `state` (in the form's Y order)."""
        if self.kind != "flow":
            return None
        g = self._globals(list(params), list(lanes))
        out = self._field_call("f", Vec(self.vectors["Y"], state),
                               _Env(self, {}, g))
        return [out.v[c] for c in self.vectors["Y"]]

    def step(self, state, params=(), lanes=()):
        """One step from `state`, in the form's Y order."""
        g = self._globals(list(params), list(lanes))
        comps = self.vectors["Y"]
        bound = dict(zip(comps, state))
        env = _Env(self, bound, g)
        for name, names in self.vectors.items():
            env.locals[name] = Vec(names, [bound[c] for c in names])
        nxt = {}
        for kind, name, tree in self.step_lines:
            value = self._eval(tree, env)
            if kind == "def":
                env.locals[name] = value
            elif isinstance(value, Vec):
                for c in self.vectors[name]:
                    nxt[c] = value.v[c]
            else:
                nxt[name] = value
        return [nxt[c] for c in comps]


def constant(text):
    """A value the form prints alone - a default, h - read exactly:
    8/3, −0.5, 1e5000."""
    form = MathForm("")
    return form._eval(_Expr(text).tree, _Env(form, {}, {}))


class _Env:
    """A binding: the state's values (as plain names), the step's own
    names, the form's where-definitions (evaluated lazily, once a
    binding), and the parameters."""

    def __init__(self, form, bound, globals_):
        self.form = form
        self.locals = dict(bound)
        self.globals = globals_
        self.memo = {}
        self.vec = None             # the tangent vector being read

    def lookup(self, name):
        if name in self.locals:
            return self.locals[name]
        if name in self.form.where:
            if name not in self.memo:
                self.memo[name] = self.form._eval(self.form.where[name], self)
            return self.memo[name]
        if name in self.globals:
            return self.globals[name]
        raise MathFormError(f"{name} is bound by nothing")
