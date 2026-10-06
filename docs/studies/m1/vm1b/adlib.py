# VM1b: first-order error attribution for the model's fragments, by instruction.
#
# For one lane x: the ORIGINAL run (softfloat, every instruction's bits), a TWIN run in exact arithmetic
# (mpmath at a high precision; instructions whose bits feed an integer op, a compare or a SELECT's
# condition are FROZEN to the original run's value, since they are data - tc, n, uh, k ... - not errors),
# the rounding error delta_i of every continuous instruction (rounded value minus the exact operation on
# the original's own operands), and s_i = dV/dv_i at the twin's point by a reverse sweep from V = Vh + Vl.
#     V_original - T  =  M(x) + sum_i delta_i s_i   (+ second order)
# M(x) = V_twin - T is the method error (truncation, constants' representation, the tail's coefficients).
# usage: from adlib import *
import math
from vm1blib import *      # noqa
from m1core import A as FA, B as FB, C as FC, asm
from m1measure import true_scaled

CONT = (sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL, sf.OP_NEG, sf.OP_ABS)


class Lane:
    pass


class Analyzer:
    def __init__(self, f, fn):
        self.f, self.fn, self.fmt = f, fn, f.fmt
        self.body, self.phases, self.probes = f.all_body
        self.p = self.fmt.prec
        n = len(self.body)
        dfeed = set()
        for i, (op, r, srcs) in enumerate(self.body):
            if op in CONT:
                continue
            if self.phases[i] in ("final", "fixed-grid", "special"):
                continue     # decisions taken after V is formed do not define data that V depends on
            ss = [srcs[2]] if op == sf.OP_SELECT else list(srcs)
            for s in ss:
                if s[0] == "v":
                    dfeed.add(s[1])
        self.dfeed = dfeed
        self.prec = 6 * self.p + 300

    def _bits(self, s, vals, xa):
        if s[0] == "v":
            return vals[s[1]]
        if s[0] == "in":
            return xa
        return self.f.allwords[s[1]]

    def original(self, xa):
        fmt = self.fmt
        vals = []
        for op, r, srcs in self.body:
            ops = {FA: 0, FB: 0, FC: 0}
            for s, fld in zip(srcs, asm.OP_FIELDS[op]):
                ops[fld] = self._bits(s, vals, xa)
            res, _fl = sf.compute(fmt, op, ops[FA], ops[FB], ops[FC], RNE if r is None else r)
            vals.append(res)
        return vals

    def analyze(self, xa):
        fmt, body, p = self.fmt, self.body, self.p
        mpmath.mp.prec = self.prec
        vals = self.original(xa)

        def num(bits):
            try:
                return M(dec(fmt, bits))
            except ValueError:
                return None

        n = len(body)
        ex = [None] * n
        delta = [None] * n
        cond_orig = {}

        def exv(s):
            if s[0] == "v":
                return ex[s[1]]
            return num(self._bits(s, vals, xa))

        def ov(s):       # the original run's numeric value of an operand
            return num(self._bits(s, vals, xa))

        for i, (op, r, srcs) in enumerate(body):
            if op in CONT:
                if i in self.dfeed:
                    ex[i] = num(vals[i])
                    continue
                a = [exv(s) for s in srcs]
                oa = [ov(s) for s in srcs]
                if op == sf.OP_ADD:
                    e_exact = a[0] + a[1]
                    o_exact = oa[0] + oa[1]
                elif op == sf.OP_SUB:
                    e_exact = a[0] - a[1]
                    o_exact = oa[0] - oa[1]
                elif op == sf.OP_MUL:
                    e_exact = a[0] * a[1]
                    o_exact = oa[0] * oa[1]
                elif op == sf.OP_FMA:
                    e_exact = a[0] * a[1] + a[2]
                    o_exact = oa[0] * oa[1] + oa[2]
                elif op == sf.OP_NEG:
                    e_exact, o_exact = -a[0], -oa[0]
                else:
                    e_exact, o_exact = abs(a[0]), abs(oa[0])
                ex[i] = e_exact
                vi = num(vals[i])
                delta[i] = vi - o_exact
            elif op == sf.OP_SELECT:
                cbits = self._bits(srcs[2], vals, xa)
                take_a = (cbits & ~fmt.sign_mask) != 0
                cond_orig[i] = take_a
                if i in self.dfeed:
                    ex[i] = num(vals[i])
                else:
                    ex[i] = exv(srcs[0] if take_a else srcs[1])
            else:
                ex[i] = num(vals[i])
        # reverse sweep from V = Vh + Vl
        adj = [mpmath.mpf(0)] * n
        for nm in ("Vh", "Vl"):
            ref = self.probes[nm]
            adj[ref[1]] += 1
        for i in range(n - 1, -1, -1):
            g = adj[i]
            if g == 0:
                continue
            op, r, srcs = body[i]
            if i in self.dfeed:
                continue
            if op in CONT:
                if op == sf.OP_ADD:
                    self._acc(adj, srcs[0], g)
                    self._acc(adj, srcs[1], g)
                elif op == sf.OP_SUB:
                    self._acc(adj, srcs[0], g)
                    self._acc(adj, srcs[1], -g)
                elif op == sf.OP_MUL:
                    self._acc(adj, srcs[0], g * exv(srcs[1]))
                    self._acc(adj, srcs[1], g * exv(srcs[0]))
                elif op == sf.OP_FMA:
                    self._acc(adj, srcs[0], g * exv(srcs[1]))
                    self._acc(adj, srcs[1], g * exv(srcs[0]))
                    self._acc(adj, srcs[2], g)
                elif op == sf.OP_NEG:
                    self._acc(adj, srcs[0], -g)
                else:
                    v = exv(srcs[0])
                    self._acc(adj, srcs[0], g if v >= 0 else -g)
            elif op == sf.OP_SELECT:
                self._acc(adj, srcs[0] if cond_orig[i] else srcs[1], g)
        L = Lane()
        L.xa, L.vals, L.ex, L.delta, L.adj = xa, vals, ex, delta, adj
        vh, vl = num(vals[self.probes["Vh"][1]]), num(vals[self.probes["Vl"][1]])
        L.V = vh + vl
        L.Vex = ex[self.probes["Vh"][1]] + ex[self.probes["Vl"][1]]
        L.Bv = num(vals[self.probes["Bv"][1]])
        k = 0
        if self.fn.startswith("exp"):
            L.k = dec(fmt, vals[self.probes["Ek"][1]]) if False else None
        L.T = None
        return L

    @staticmethod
    def _acc(adj, s, g):
        if s[0] == "v":
            adj[s[1]] += g

    def contributions(self, L):
        """[(i, delta_i * s_i, |s_i| * ulp_i/2)] for the instructions with a rounding error possible"""
        out = []
        for i, d in enumerate(L.delta):
            if d is None:
                continue
            s = L.adj[i]
            v = L.ex[i]
            cap = mpmath.mpf(0)
            vo = M(dec(self.fmt, L.vals[i])) if L.vals[i] else mpmath.mpf(0)
            if vo != 0:
                e = mpmath.mag(vo) - 1
                cap = abs(s) * mpmath.mpf(2) ** (e - (self.p - 1) - 1)
            out.append((i, d * s, cap, d))
        return out
