# M2 model: the first-order error budget of a region (scratch; the
# study's 3.2). verifier-VM1b's method for M1 (docs/studies/m1/vm1b/
# adlib.py and p5_budget.py), ported to this model, with two extensions:
#   * an IXOR whose other operand is the sign word or zero is a NEGATION
#     (V's sign, -r_h, -z_h), continuous, not data;
#   * the roundings the reduction tags as data (m2red.data: a modular
#     quotient, a quadrant count, a split's high part, the bucket) are
#     frozen, as M1's integer-feeding values were: their rounding is the
#     operation's purpose.
#
# For one lane x: the ORIGINAL run (softfloat), a TWIN run in exact
# arithmetic (every continuous instruction exact on the twin's operands,
# data frozen to the original's), each rounding's error
# delta_i = (rounded) - (the exact operation on the original's operands),
# and s_i = dV/dv_i at the twin's point by a reverse sweep from
# V = V_h + V_l. Then V - T = M(x) + sum_i delta_i s_i + (second order),
# M(x) = V_twin - T the method error (truncations, the constants'
# representation, 2/pi's dropped tail). Over a region's arguments the
# budget's bound is M's largest value plus each rounding's largest
# CAPACITY, |s_i| ulp(v_i)/2: what it adds rounding the worst way.
#
#   python m2budget.py FMT FN MODE N [seed] [top]
# MODE as m2measure.py's (random, edge, near, small, worst).

import sys
import time
import math

import mpmath

from m2core import FORMATS, sf, dec, run_body, RNE, asm, A as FA, B as FB, C as FC
from m2trig import build
from m2measure import sample, in_main, true_value

CONT = (sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL, sf.OP_NEG, sf.OP_ABS)
AFTER_V = ("final", "range", "special", "classify")
# The reduction's error-free phases: every instruction in them is exact
# (the audit of m2red.audit checks each claim lane by lane) or a rounding
# whose error an exact instruction captures (a TwoProd's product, a TwoSum's
# sum) or a selection (data). They carry no rounding error, so the twin
# takes their values as computed: freezing them keeps the twin's modular
# bookkeeping (quotients chosen by the original's roundings) consistent,
# where recomputing a TwoProd's product exactly would move its error term
# to zero under a frozen quotient. The lower sum and everything after it
# are budgeted.
EXACT_PHASES = ("red-setup", "red-window", "red-products", "red-coarse",
                "red-mid")


def M(q):
    return mpmath.mpf(q.numerator) / q.denominator


class Analyzer:
    def __init__(self, f):
        self.f, self.fmt = f, f.fmt
        self.body, self.phases, self.probes = f.all_body
        self.p = self.fmt.prec
        frozen = set(i for (_k, i) in f.meta.get("data", set()))
        sm = self.fmt.sign_mask
        # which values are CONTINUOUS (arithmetic, a SELECT, the input, a
        # negation) and which are integer data; an IXOR of a continuous
        # value with a SIGN CARRIER (the sign word, or a value of integer
        # instructions, whose bits are 0 or the sign: V's sign by the
        # quadrant) is a negation: self.negs[i] = (continuous, carrier)
        cont = set()
        self.negs = {}
        for i, (op, r, srcs) in enumerate(self.body):
            if op in CONT or op == sf.OP_SELECT:
                cont.add(i)
            elif op == sf.OP_IXOR:
                kinds = []
                for s in srcs:
                    if s[0] == "in" or (s[0] == "v" and s[1] in cont):
                        kinds.append("c")
                    elif s[0] == "w" and f.allwords[s[1]] in (0, sm):
                        kinds.append("s")
                    elif s[0] == "v" and s[1] not in cont:
                        kinds.append("s")
                    else:
                        kinds.append("?")
                if sorted(kinds) == ["c", "s"]:
                    k = kinds.index("c")
                    self.negs[i] = (srcs[k], srcs[1 - k])
                    cont.add(i)
        dfeed = set()
        for i, (op, r, srcs) in enumerate(self.body):
            if op in CONT:
                continue
            if self.phases[i] in AFTER_V:
                continue
            if op in (sf.OP_RECIP_SEED, sf.OP_RSQRT_SEED):
                # a seed is data (its output, frozen as any non-arithmetic
                # value is), but what it reads is not: tan's denominator
                # D_h feeds RECIP_SEED, and freezing D_h at its rounded
                # value while the twin recomputes D's low word as zero
                # loses that word (the first version's 2^+45 Bv for tan)
                continue
            if i in self.negs:
                c, s = self.negs[i]
                if s[0] == "v":
                    dfeed.add(s[1])
                continue
            ss = [srcs[2]] if op == sf.OP_SELECT else list(srcs)
            for s in ss:
                if s[0] == "v":
                    dfeed.add(s[1])
        exact_ph = {i for i in range(len(self.body))
                    if self.phases[i] in EXACT_PHASES}
        self.dfeed = dfeed | frozen | exact_ph
        self.prec = 6 * self.p + 300

    def _bits(self, s, vals, xa):
        if s[0] == "v":
            return vals[s[1]]
        if s[0] == "in":
            return xa
        return self.f.allwords[s[1]]

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
        for i, (op, r, srcs) in enumerate(body):
            if i in self.negs and i not in self.dfeed:
                c, s = self.negs[i]
                flag = self._bits(s, vals, xa) == sm
                negsign[i] = (c, flag)
                e = exv(c)
                ex[i] = None if e is None else (-e if flag else e)
                continue
            if op in CONT and i not in self.dfeed:
                a = [exv(s) for s in srcs]
                oa = [ov(s) for s in srcs]
                if any(v is None for v in a) or any(v is None for v in oa):
                    ex[i] = num(vals[i])
                    continue
                if op == sf.OP_ADD:
                    e_x, o_x = a[0] + a[1], oa[0] + oa[1]
                elif op == sf.OP_SUB:
                    e_x, o_x = a[0] - a[1], oa[0] - oa[1]
                elif op == sf.OP_MUL:
                    e_x, o_x = a[0] * a[1], oa[0] * oa[1]
                elif op == sf.OP_FMA:
                    e_x, o_x = a[0] * a[1] + a[2], oa[0] * oa[1] + oa[2]
                elif op == sf.OP_NEG:
                    e_x, o_x = -a[0], -oa[0]
                else:
                    e_x, o_x = abs(a[0]), abs(oa[0])
                ex[i] = e_x
                vi = num(vals[i])
                delta[i] = None if vi is None else vi - o_x
            elif op == sf.OP_SELECT and i not in self.dfeed:
                c = self._bits(srcs[2], vals, xa)
                take = (c & ~sm) != 0
                sel_take[i] = take
                ex[i] = exv(srcs[0] if take else srcs[1])
            else:
                ex[i] = num(vals[i])
        adj = [mpmath.mpf(0)] * n
        for nm in ("Vh", "Vl"):
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
            if op in CONT:
                if op == sf.OP_ADD:
                    self._acc(adj, srcs[0], g)
                    self._acc(adj, srcs[1], g)
                elif op == sf.OP_SUB:
                    self._acc(adj, srcs[0], g)
                    self._acc(adj, srcs[1], -g)
                elif op == sf.OP_MUL:
                    self._acc(adj, srcs[0], g * (exv(srcs[1]) or 0))
                    self._acc(adj, srcs[1], g * (exv(srcs[0]) or 0))
                elif op == sf.OP_FMA:
                    self._acc(adj, srcs[0], g * (exv(srcs[1]) or 0))
                    self._acc(adj, srcs[1], g * (exv(srcs[0]) or 0))
                    self._acc(adj, srcs[2], g)
                elif op == sf.OP_NEG:
                    self._acc(adj, srcs[0], -g)
                else:
                    v = exv(srcs[0]) or 0
                    self._acc(adj, srcs[0], g if v >= 0 else -g)
            elif op == sf.OP_SELECT and i in sel_take:
                self._acc(adj, srcs[0] if sel_take[i] else srcs[1], g)

        class Lane:
            pass
        Lx = Lane()
        Lx.vals, Lx.ex, Lx.delta, Lx.adj = vals, ex, delta, adj
        vh, vl = num(vals[self.probes["Vh"][1]]), num(vals[self.probes["Vl"][1]])
        Lx.V = vh + vl
        Lx.Vex = ex[self.probes["Vh"][1]] + ex[self.probes["Vl"][1]]
        Lx.Bv = abs(num(vals[self.probes["Bv"][1]]))
        return Lx

    @staticmethod
    def _acc(adj, s, g):
        if s[0] == "v":
            adj[s[1]] += g

    def contributions(self, Lx):
        out = []
        for i, d in enumerate(Lx.delta):
            if d is None:
                continue
            s = Lx.adj[i]
            vo = M(dec(self.fmt, Lx.vals[i])) if Lx.vals[i] & ~self.fmt.sign_mask else mpmath.mpf(0)
            cap = mpmath.mpf(0)
            if vo != 0:
                e = mpmath.mag(vo) - 1
                cap = abs(s) * mpmath.mpf(2) ** (e - (self.p - 1) - 1)
            out.append((i, d * s, cap, d))
        return out


def budget(fmt, fn, xs, rnd=RNE, top=10, G=None):
    f = build(fmt, rnd, fn, G=G)
    an = Analyzer(f)
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


def lg(v):
    return math.log2(v) if v > 0 else -999.0


def main():
    name, fn, mode, N = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
    seed = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    top = int(sys.argv[6]) if len(sys.argv) > 6 else 8
    G = int(sys.argv[7]) if len(sys.argv) > 7 else None
    fmt = FORMATS[name]
    t0 = time.perf_counter()
    xs = sample(fmt, mode, N, seed)
    b = budget(fmt, fn, xs, top=top, G=G)
    print(f"{name} {fn} {mode} seed {seed} G {G or 'default'}: {b['lanes']} main lanes of "
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
