# M2X: the first-order error budget of a region for the TRIPLE-word fp32
# routines (scratch; the study's 3.2 method, ported once more). m2budget.py
# (verifier-VM1b's method) seeds its reverse sweep at V_h and V_l and takes
# V = V_h + V_l (m2budget.py:179 to 180, 218 to 220), so it cannot budget a
# triple word as it is. This file subclasses its Analyzer, copies its
# `analyze` with ONE change, the seeds: V0, V1 and V2, V their sum; for a
# fragment with V_h and V_l probes (m2trig's) it seeds those, so the same
# tool is its own control (fp64 sin, edge, 1,500 lanes, seed 21: 0.07031 Bv,
# budget.fp64-sin-edge.out.txt). Nothing of m2budget.py is edited.
#
# The reduction's error-free phases are frozen as m2budget.EXACT_PHASES
# freezes the double word's, by name: red-setup, red-window, red-products,
# red-coarse and red-mid, and red-products-low, which holds the same
# products of the low positions (emitted late, to keep fewer values live).
# The lows' sum, the triple word's VecSum and everything after are budgeted.
#
#   python tw32_budget.py FMT FN MODE N [seed] [top] [G] [plant]
# FMT fp32: tw32.build (G = 40, a `plant` of tw32.PLANTS); any other format:
# m2trig.build (the control). MODE as m2measure.py's.

import sys
import time

import mpmath

import m2budget
from m2budget import Analyzer, M, lg
from m2core import FORMATS, sf, dec, run_body, RNE
from m2measure import sample, in_main, true_value
import m2trig
import tw32

# the process-local extension of the frozen phases (m2budget.py:46 itself is
# not edited): the low positions' products, error-free as red-products are
m2budget.EXACT_PHASES = m2budget.EXACT_PHASES + ("red-products-low",)


class TWAnalyzer(Analyzer):
    """m2budget.Analyzer with the seeds of V's words: V0, V1, V2 for a triple
    word, V_h and V_l for a double word."""

    def __init__(self, f):
        super().__init__(f)
        self.seeds = (("V0", "V1", "V2") if "V0" in self.probes
                      else ("Vh", "Vl"))

    def analyze(self, xa):
        fmt, body = self.fmt, self.body
        mpmath.mp.prec = self.prec
        vals, _get = run_body(fmt, body, self.f.allwords, xa)

        def num(bits):
            try:
                return M(dec(fmt, bits))
            except ValueError:
                return None
        n = len(body)
        ex = [None] * n
        delta = [None] * n
        sel_take = {}
        negsign = {}
        sm = fmt.sign_mask

        def exv(s):
            return ex[s[1]] if s[0] == "v" else num(self._bits(s, vals, xa))

        def ov(s):
            return num(self._bits(s, vals, xa))
        sf_ = sf
        for i, (op, r, srcs) in enumerate(body):
            if i in self.negs and i not in self.dfeed:
                c, s = self.negs[i]
                flag = self._bits(s, vals, xa) == sm
                negsign[i] = (c, flag)
                e = exv(c)
                ex[i] = None if e is None else (-e if flag else e)
                continue
            if op in m2budget.CONT and i not in self.dfeed:
                a = [exv(s) for s in srcs]
                oa = [ov(s) for s in srcs]
                if any(v is None for v in a) or any(v is None for v in oa):
                    ex[i] = num(vals[i])
                    continue
                if op == sf_.OP_ADD:
                    e_x, o_x = a[0] + a[1], oa[0] + oa[1]
                elif op == sf_.OP_SUB:
                    e_x, o_x = a[0] - a[1], oa[0] - oa[1]
                elif op == sf_.OP_MUL:
                    e_x, o_x = a[0] * a[1], oa[0] * oa[1]
                elif op == sf_.OP_FMA:
                    e_x, o_x = a[0] * a[1] + a[2], oa[0] * oa[1] + oa[2]
                elif op == sf_.OP_NEG:
                    e_x, o_x = -a[0], -oa[0]
                else:
                    e_x, o_x = abs(a[0]), abs(oa[0])
                ex[i] = e_x
                vi = num(vals[i])
                delta[i] = None if vi is None else vi - o_x
            elif op == sf_.OP_SELECT and i not in self.dfeed:
                c = self._bits(srcs[2], vals, xa)
                take = (c & ~sm) != 0
                sel_take[i] = take
                ex[i] = exv(srcs[0] if take else srcs[1])
            else:
                ex[i] = num(vals[i])
        adj = [mpmath.mpf(0)] * n
        for nm in self.seeds:                       # THE CHANGE: V's words
            adj[self.probes[nm][1]] += 1
        for i in range(n - 1, -1, -1):
            g = adj[i]
            if g == 0:
                continue
            op, r, srcs = body[i]
            if i in negsign:
                other, neg = negsign[i]
                self._acc(adj, other, -g if neg else g)
                continue
            if i in self.dfeed:
                continue
            if op in m2budget.CONT:
                if op == sf_.OP_ADD:
                    self._acc(adj, srcs[0], g)
                    self._acc(adj, srcs[1], g)
                elif op == sf_.OP_SUB:
                    self._acc(adj, srcs[0], g)
                    self._acc(adj, srcs[1], -g)
                elif op == sf_.OP_MUL:
                    self._acc(adj, srcs[0], g * (exv(srcs[1]) or 0))
                    self._acc(adj, srcs[1], g * (exv(srcs[0]) or 0))
                elif op == sf_.OP_FMA:
                    self._acc(adj, srcs[0], g * (exv(srcs[1]) or 0))
                    self._acc(adj, srcs[1], g * (exv(srcs[0]) or 0))
                    self._acc(adj, srcs[2], g)
                elif op == sf_.OP_NEG:
                    self._acc(adj, srcs[0], -g)
                else:
                    v = exv(srcs[0]) or 0
                    self._acc(adj, srcs[0], g if v >= 0 else -g)
            elif op == sf_.OP_SELECT and i in sel_take:
                self._acc(adj, srcs[0] if sel_take[i] else srcs[1], g)

        class Lane:
            pass
        Lx = Lane()
        Lx.vals, Lx.ex, Lx.delta, Lx.adj = vals, ex, delta, adj
        Lx.V = sum(num(vals[self.probes[nm][1]]) for nm in self.seeds)
        Lx.Vex = sum(ex[self.probes[nm][1]] for nm in self.seeds)
        Lx.Bv = abs(num(vals[self.probes["Bv"][1]]))
        return Lx


def budget(build_fn, fmt, fn, xs, rnd=RNE, top=10):
    """m2budget.budget, with the analyzer above."""
    f = build_fn(fmt, rnd, fn)
    an = TWAnalyzer(f)
    n = len(an.body)
    obs = [0.0] * n
    cap = [0.0] * n
    active = [False] * n
    Mmax, Emax, cnt = 0.0, 0.0, 0
    resid = 0.0
    for xa in xs:
        if not in_main(fmt, fn, xa):
            continue
        Lx = an.analyze(xa)
        T = true_value(fn, dec(fmt, xa))
        Bv = Lx.Bv
        E = abs((Lx.V - T) / Bv)
        Mx = abs((Lx.Vex - T) / Bv)
        Mmax = max(Mmax, float(Mx))
        Emax = max(Emax, float(E))
        first = Lx.Vex - T
        for i, contrib, capi, d in an.contributions(Lx):
            if d != 0:
                active[i] = True
            first += contrib
            obs[i] = max(obs[i], abs(float(contrib / Bv)))
            cap[i] = max(cap[i], float(capi / Bv))
        resid = max(resid, abs(float((Lx.V - T - first) / Bv)))
        cnt += 1
    S_obs = sum(obs[i] for i in range(n) if active[i])
    S_cap = sum(cap[i] for i in range(n) if active[i])
    byphase = {}
    for i in range(n):
        if active[i]:
            ph = an.phases[i]
            a, b = byphase.get(ph, (0.0, 0.0))
            byphase[ph] = (a + obs[i], b + cap[i])
    order = sorted((i for i in range(n) if active[i]), key=lambda i: -cap[i])[:top]
    return {"lanes": cnt, "instructions": n, "rounding": sum(active),
            "Emax": Emax, "Mmax": Mmax, "S_obs": S_obs, "S_cap": S_cap,
            "bound": Mmax + S_cap, "resid": resid, "byphase": byphase,
            "top": [(i, sf.OP_NAMES[an.body[i][0]], an.phases[i], cap[i], obs[i])
                    for i in order]}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    name, fn, mode, N = argv[0], argv[1], argv[2], int(argv[3])
    seed = int(argv[4]) if len(argv) > 4 else 1
    top = int(argv[5]) if len(argv) > 5 else 8
    G = int(argv[6]) if len(argv) > 6 and argv[6] != "-" else None
    plant = argv[7] if len(argv) > 7 and argv[7] != "-" else None
    fmt = FORMATS[name]
    t0 = time.perf_counter()
    xs = sample(fmt, mode, N, seed)
    if name == "fp32":
        def build_fn(fm, rnd, fnn):
            return tw32.build(fm, rnd, fnn, G=G or tw32.G_TW, plant=plant)
    else:
        def build_fn(fm, rnd, fnn):
            return m2trig.build(fm, rnd, fnn, G=G)
    b = budget(build_fn, fmt, fn, xs, top=top)
    print(f"{name} {fn} {mode} seed {seed} G {G or 'default'}"
          f"{' plant ' + plant if plant else ''}: {b['lanes']} main lanes of "
          f"{len(xs)}; {b['instructions']} instructions (unpruned), "
          f"{b['rounding']} ever round; {time.perf_counter() - t0:.0f}s")
    print(f"  max |E|/Bv {b['Emax']:.4g} (2^{lg(b['Emax']):+.2f}); "
          f"max |M|/Bv {b['Mmax']:.4g} (2^{lg(b['Mmax']):+.2f}); "
          f"second-order residual at most {b['resid']:.3g} Bv")
    print(f"  observed maxima summed {b['S_obs']:.4g} (2^{lg(b['S_obs']):+.2f}); "
          f"capacities summed {b['S_cap']:.4g} (2^{lg(b['S_cap']):+.2f})")
    print(f"  THE BUDGET'S BOUND: M_max + capacities = {b['bound']:.4g} Bv "
          f"(2^{lg(b['bound']):+.2f})")
    print("  by phase (observed, capacity), in Bv:")
    for ph, (a, c) in sorted(b["byphase"].items(), key=lambda kv: -kv[1][1]):
        print(f"     {ph:14s} {a:.3e}  {c:.3e}")
    print(f"  the {top} largest capacities:")
    for i, nm, ph, c, o in b["top"]:
        print(f"     #{i:4d} {nm:5s} {ph:14s} capacity {c:.3e}  observed {o:.3e}")


if __name__ == "__main__":
    main()
