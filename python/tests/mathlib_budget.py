# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The first-order error budget of a math-library fragment: verifier-VM1b's
tool (docs/studies/m1/vm1b/: adlib.py, p5_budget.py, p5c_budget_end.py),
ported into the tree for parcel E1 and held, since parcel MB1, to the
instrumented forms of exp, exp2 and expm1 and, since parcel MB2, of log, log2
and log1p (cft_golden/mathlib.py's Build), which keep what it reads: the
unpruned body, each instruction's phase and the probes Vh, Vl, Bv and, for the
scaled exp family, Ek. The true value it compares with is f(x) 2^-k for the
build's own f (true_scaled); the log family is not scaled (k = 0).

What it is. The in-lane test (the study's 3.1) is sound only if the true
value lies within Bv = 2^-(p+G) |V_h| of V = V_h + V_l, so that bound must
HOLD, and a sampled worst error is only a lower bound on the true worst
(the study's lesson, three passes running). The budget states the bound
from the instructions instead, to first order:

  * the ORIGINAL run: softfloat, every instruction's bits;
  * a TWIN run in exact arithmetic (mpmath at 6p + 300 bits): what the
    method alone computes. An instruction whose bits feed an integer
    operation, a compare or a SELECT's condition before V is formed is
    FROZEN to the original's value - it is data (the magic-number sum t,
    the table's index, the scale), not an error;
  * delta_i, the rounding error of every continuous instruction: its
    rounded value minus the exact operation on the original's own operands;
  * s_i = dV/dv_i at the twin's point, by a reverse sweep from
    V = V_h + V_l.
  Then V - true = M(x) + sum_i delta_i s_i  (+ second order), where
  M(x) = V_twin - true is the METHOD's error: the truncation of Y(r), the
  constants' representation, the tail's coefficients.

Over a sample of arguments the budget keeps, for each instruction that ever
rounds, its largest CAPACITY: |s_i| times half an ulp of its value, what it
adds if it rounds the worst way. The BUDGET'S BOUND of a region is M's
largest value plus the sum of the capacities, in units of Bv; it bounds the
first-order error of every lane sampled whatever the roundings' alignment,
and is the region's bound as far as the sample reaches the region's
extremes. It must be under 1.

Verifier-VM1d measured what first order leaves out (6e-5 Bv for exp at
G = 44: the study's 3.2), so a bound under 1 with the room the study
recorded (0.164 Bv at fp64, G = 44) is a bound with margin. exp2's is exp's
(the same polynomial and reconstruction: 0.1643, 0.0148 and 0.0193 Bv at
fp64, fp128 and fp256 over all regions, parcel MB1's entry; the placed
region alone gives 0.1642 at fp64); expm1's is mostly the method's
error at its first clamped k, where 2^-k is taken as 0 (about 1/8 Bv, M in
the summary), with the double word's floor amplified at n = +-1 on top at
fp64.

fp32 has no budget: its V is three words and the probes are V0, V1, V2; its
bound is measured (mathlib_harness.check_bound).
"""

import math
import sys
from pathlib import Path

import mpmath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

CONT = (sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL, sf.OP_NEG, sf.OP_ABS)
_PHASES_AFTER_V = ("final", "fixed-grid", "special")


def to_mp(q):
    """A Fraction as an mpf, at the current working precision."""
    return mpmath.mpf(q.numerator) / q.denominator


def true_scaled(fmt, x, k, fn="exp"):
    """f(x) 2^-k at 4p + 200 bits, f exp, exp2 or expm1: the true value in
    the scaled domain V lives in (independent of transcend.py's decision
    procedure). The log family's V is not scaled (k = 0): f is log, log2 or
    log1p."""
    with mpmath.workprec(4 * fmt.prec + 200):
        xv = to_mp(ml._dec(fmt, x))
        if fn == "exp2":
            v = mpmath.power(2, xv)
        elif fn == "expm1":
            v = mpmath.expm1(xv)
        elif fn == "log":
            v = mpmath.log(xv)
        elif fn == "log2":
            v = mpmath.log(xv) / mpmath.log(2)
        elif fn == "log1p":
            v = mpmath.log1p(xv)
        else:
            v = mpmath.exp(xv)
        return v * mpmath.mpf(2) ** (-k)


class Lane:
    """One analysed lane: xa; vals, every instruction's bits; ex, the
    twin's values; delta, each rounding's error; adj, dV/dv_i; V, the
    original's V_h + V_l; Vex, the twin's; Bv."""


class Analyzer:
    """adlib.Analyzer, over a mathlib.Build."""

    def __init__(self, build):
        if "Vh" not in build.probes or "Vl" not in build.probes or \
                build.meta.get("family") == "triple word":
            raise ValueError(f"{build.fmt.name} has no budget: its V is "
                             f"not a double word; its bound is measured")
        self.b = build
        self.fmt = build.fmt
        self.body, self.phases = build.body, build.phase_of
        self.probes, self.words = build.probes, build.words
        self.p = self.fmt.prec
        self.prec = 6 * self.p + 300
        dfeed = set()
        for i, (op, _r, srcs) in enumerate(self.body):
            if op in CONT or self.phases[i] in _PHASES_AFTER_V:
                continue
            for s in ([srcs[2]] if op == sf.OP_SELECT else list(srcs)):
                if s[0] == "v":
                    dfeed.add(s[1])
        self.dfeed = dfeed          # values that are data, not errors

    def _bits(self, s, vals, xa):
        if s[0] == "v":
            return vals[s[1]]
        return xa if s[0] == "in" else self.words[s[1]]

    def analyze(self, xa):
        fmt, body = self.fmt, self.body
        vals = ml._values(fmt, body, self.words, xa)
        with mpmath.workprec(self.prec):
            def num(bits):
                try:
                    return to_mp(ml._dec(fmt, bits))
                except ValueError:
                    return None
            n = len(body)
            ex, delta, cond = [None] * n, [None] * n, {}

            def exv(s):
                return ex[s[1]] if s[0] == "v" else \
                    num(self._bits(s, vals, xa))

            def ov(s):
                return num(self._bits(s, vals, xa))
            for i, (op, _r, srcs) in enumerate(body):
                if op in CONT:
                    if i in self.dfeed:
                        ex[i] = num(vals[i])
                        continue
                    a = [exv(s) for s in srcs]
                    o = [ov(s) for s in srcs]
                    if op == sf.OP_ADD:
                        ex[i], exact = a[0] + a[1], o[0] + o[1]
                    elif op == sf.OP_SUB:
                        ex[i], exact = a[0] - a[1], o[0] - o[1]
                    elif op == sf.OP_MUL:
                        ex[i], exact = a[0] * a[1], o[0] * o[1]
                    elif op == sf.OP_FMA:
                        ex[i], exact = (a[0] * a[1] + a[2],
                                        o[0] * o[1] + o[2])
                    elif op == sf.OP_NEG:
                        ex[i], exact = -a[0], -o[0]
                    else:
                        ex[i], exact = abs(a[0]), abs(o[0])
                    # an instruction whose value is not finite sits on an arm
                    # the lane's SELECT discards (the log family's x 2^p for a
                    # large x): it has no rounding error to count
                    nv = num(vals[i])
                    delta[i] = None if nv is None else nv - exact
                elif op == sf.OP_SELECT:
                    take_a = (self._bits(srcs[2], vals, xa)
                              & ~fmt.sign_mask) != 0
                    cond[i] = take_a
                    ex[i] = num(vals[i]) if i in self.dfeed else \
                        exv(srcs[0] if take_a else srcs[1])
                else:
                    ex[i] = num(vals[i])
            adj = [mpmath.mpf(0)] * n
            for nm in ("Vh", "Vl"):
                adj[self.probes[nm][1]] += 1
            for i in range(n - 1, -1, -1):
                g = adj[i]
                if g == 0 or i in self.dfeed:
                    continue
                op, _r, srcs = body[i]
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
                        self._acc(adj, srcs[0],
                                  g if exv(srcs[0]) >= 0 else -g)
                elif op == sf.OP_SELECT:
                    self._acc(adj, srcs[0] if cond[i] else srcs[1], g)
            L = Lane()
            L.xa, L.vals, L.ex, L.delta, L.adj = xa, vals, ex, delta, adj
            ih, il = self.probes["Vh"][1], self.probes["Vl"][1]
            L.V = num(vals[ih]) + num(vals[il])
            L.Vex = ex[ih] + ex[il]
            L.Bv = num(vals[self.probes["Bv"][1]])
            L.k = (vals[self.probes["Ek"][1]] - self.fmt.bias
                   - self.b.meta["OFF"]) if self.b.meta.get("scaled", True) \
                else 0
            return L

    @staticmethod
    def _acc(adj, s, g):
        if s[0] == "v":
            adj[s[1]] += g

    def contributions(self, L):
        """[(i, delta_i s_i, capacity_i, delta_i)] for the instructions
        that can round: the capacity is |s_i| times half an ulp of the
        original's value."""
        out = []
        with mpmath.workprec(self.prec):
            for i, d in enumerate(L.delta):
                if d is None:
                    continue
                s = L.adj[i]
                vo = to_mp(ml._dec(self.fmt, L.vals[i])) if L.vals[i] \
                    else mpmath.mpf(0)
                cap = mpmath.mpf(0)
                if vo != 0:
                    e = mpmath.mag(vo) - 1
                    cap = abs(s) * mpmath.mpf(2) ** (e - (self.p - 1) - 1)
                out.append((i, d * s, cap, d))
        return out


# Faults of the tool itself, for the tests. mathlib_harness.check_budget's
# last branch, "a lane's error is past the budget's bound", is the tool's own
# soundness check: a fault of the fragment moves the method's error M and the
# capacities with it (the twin shares the fragment's method and every
# rounding is counted). MEASURED on the plants table's lanes at fp64 and
# fp128: no plant of mathlib.PLANTS fires that branch, only the first (a
# bound not under 1) or none; a fault in the tool does.
PLANTS = {
    "capacities_dropped": "the capacities left out of the bound, which is "
                          "M alone, so the lanes' rounding errors pass it",
}


class Budget:
    """p5_budget.py's sums, kept across regions: for each instruction the
    largest |delta_i s_i| seen (`obs`) and the largest capacity (`cap`),
    in Bv; the largest method error M and total error E. `plant` names a
    fault of the tool (PLANTS), for the tests."""

    def __init__(self, build, plant=None):
        if plant is not None and plant not in PLANTS:
            raise ValueError(f"unknown budget plant {plant!r}: "
                             f"{', '.join(PLANTS)}")
        self.plant = plant
        self.an = Analyzer(build)
        n = len(self.an.body)
        self.obs, self.cap = [0.0] * n, [0.0] * n
        self.active = [False] * n
        self.Mmax = self.Emax = 0.0
        self.lanes = 0
        self.worst_x = None

    def add(self, xs):
        an, fmt = self.an, self.an.fmt
        fn = an.b.meta["fn"]
        for xa in xs:
            L = an.analyze(xa)
            T = true_scaled(fmt, xa, L.k, fn)
            with mpmath.workprec(an.prec):
                E = (L.V - T) / L.Bv
                Mx = (L.Vex - T) / L.Bv
                e_abs = abs(float(E))
                self.Mmax = max(self.Mmax, abs(float(Mx)))
                if e_abs > self.Emax:
                    self.Emax, self.worst_x = e_abs, xa
                for i, contrib, capi, d in an.contributions(L):
                    if d != 0:
                        self.active[i] = True
                    self.obs[i] = max(self.obs[i], abs(float(contrib / L.Bv)))
                    if self.plant != "capacities_dropped":
                        self.cap[i] = max(self.cap[i], float(capi / L.Bv))
            self.lanes += 1
        return self

    def summary(self):
        """{Emax, Mmax, S_obs, S_cap, bound = Mmax + S_cap, lanes, rounding
        instructions, by_phase}: every figure in units of Bv."""
        act = [i for i, a in enumerate(self.active) if a]
        s_obs = sum(self.obs[i] for i in act)
        s_cap = sum(self.cap[i] for i in act)
        by_phase = {}
        for i in act:
            a, c = by_phase.get(self.an.phases[i], (0.0, 0.0))
            by_phase[self.an.phases[i]] = (a + self.obs[i], c + self.cap[i])
        return {"lanes": self.lanes, "rounding": len(act),
                "Emax": self.Emax, "Mmax": self.Mmax, "S_obs": s_obs,
                "S_cap": s_cap, "bound": self.Mmax + s_cap,
                "by_phase": by_phase}

    def largest(self, top=8):
        """[(instruction, opcode name, phase, capacity, observed max)]."""
        order = sorted((i for i, a in enumerate(self.active) if a),
                       key=lambda i: -self.cap[i])[:top]
        return [(i, sf.OP_NAMES[self.an.body[i][0]], self.an.phases[i],
                 self.cap[i], self.obs[i]) for i in order]


def bits_log2(bound):
    """-log2(bound): the bits of margin a bound of `bound` Bv leaves."""
    return -math.log2(bound) if bound > 0 else float("inf")
