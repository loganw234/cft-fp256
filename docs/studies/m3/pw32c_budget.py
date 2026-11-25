# M3 model: the budget tools of parcel M3XN2 (compound at fp32, the follow-up to
# pw32n.py). pw32n_budget.NBudget (M3XN's, imported and never edited) is the
# budget; what this file adds, and nothing else:
#
#   CBudget      NBudget with ONE addition: for each instruction, the lane that
#                set its capacity (the largest |s_i| half-ulp(v_i) / Bv over the
#                lanes run), kept beside the capacity itself. `add` below is
#                pw32_budget.TWBudget.add's loop, character for character in
#                what it computes (the lines marked [NEW] are the only ones
#                that are not), so CBudget's `summary()` is NBudget's to the
#                last digit (pw32c_run.py `attribute` checks that, by printing
#                the summary of the unchanged class beside it)
#   attribute()  item 2 of the brief: the instructions that carry each logarithm
#                term's capacity (log-sum and log-lowword), index, op,
#                label, operands, capacity in Bv, observed Bv, and the lane
#                that sets the capacity, sorted, the sum shown beside the
#                part's figure
#
# THE BUDGET'S RULE, read in pw32_budget.TWBudget.summary and
# mathlib_budget.contributions (CONFIRMED in the code, not from a docstring):
# BOUND = Mmax + sum over the instructions that round in at least one lane
# (`active`) of that instruction's capacity, and an instruction's capacity is
# the largest over ALL the lanes of |s_i| 2^(e_i - p) / Bv, where s_i is the
# instruction's sensitivity (the adjoint of V), e_i the exponent of its value,
# 2^(e_i - p) half an ulp of it. A part's figure is the sum of its active
# instructions' capacities (`by`), and `observed` is the sum of each one's
# largest |delta_i s_i| / Bv. So the capacity is a sum of per-instruction
# worsts over lanes (a first-order over-count unless one lane is the worst of
# all of them), and the observed is a sum of per-instruction worsts, also over
# different lanes: neither is the error of any one lane.

import mpmath

from m3core import ml, sf, true_value
import m3pow as M
import pw32n_budget as NB
import regions as RG


class CBudget(NB.NBudget):
    def __init__(self, build):
        super().__init__(build)
        n = len(self.an.body)
        self.cap_lane = [None] * n                         # [NEW]
        self.obs_lane = [None] * n                         # [NEW]

    def add(self, lanes):
        an, fmt, fn = self.an, self.b.fmt, self.b.meta["fn"]
        for lane in lanes:
            if not self.in_main(lane):
                self.skipped += 1
                continue
            L = an.analyze(M.lane_of(fn, lane))
            k = (L.vals[self.b.probes["Ek"][1]] - fmt.bias
                 - self.b.meta["OFF"])
            self.tmax = max(self.tmax, abs(k))
            with mpmath.workprec(an.prec):
                T = true_value(fmt, fn, lane, an.prec) * mpmath.mpf(2) ** (-k)
                Bv = L.Bv
                E = float(abs((L.V - T) / Bv))
                self.Mmax = max(self.Mmax, float(abs((L.Vex - T) / Bv)))
                if E > self.Emax:
                    self.Emax, self.worst = E, lane
                first = L.Vex - T
                for i, contrib, capi, d in an.contributions(L):
                    if d != 0:
                        self.active[i] = True
                    first += contrib
                    o = abs(float(contrib / Bv))
                    if o > self.obs[i]:                    # [NEW] lane kept
                        self.obs_lane[i] = lane
                    self.obs[i] = max(self.obs[i], o)
                    c = float(capi / Bv)
                    if c > self.cap[i]:                    # [NEW] lane kept
                        self.cap_lane[i] = lane
                    self.cap[i] = max(self.cap[i], c)
                self.resid = max(self.resid,
                                 abs(float((L.V - T - first) / Bv)))
            self.lanes += 1
        return self


def src_str(s):
    """an operand as the builder holds it: ('v', j) an earlier instruction,
    ('w', j) a bank word, ('in', 0) the input"""
    if s[0] == "v":
        return f"v{s[1]}"
    if s[0] == "w":
        return f"w{s[1]}"
    return "x"


def attribute(bld, lanes, label, out=print, terms=("log-sum", "log-lowword"),
              top=12):
    """Run CBudget on `lanes`; for each term in `terms` print the active
    instructions carrying its capacity, sorted by capacity, and the sums
    against the part's figure. Returns (summary, {term: (cap sum, obs sum)})."""
    bud = CBudget(bld).add(lanes)
    s = bud.summary()
    fn = bld.meta["fn"]
    body = bud.an.body
    out(f"{bld.fmt.name} {fn} n={bld.meta.get('n')} region {label}: "
        f"{s['lanes']} measured lanes of {len(lanes)} (left out {s['skipped']}, "
        f"of them {bud.skipped_tiny} by the tinyt gate); instructions "
        f"{len(body)}, active (rounding in some lane) {s['rounding']}; "
        f"BOUND {s['bound']:.6f} + residual {s['resid']:.2e} = "
        f"{s['bound'] + s['resid']:.6f} Bv; measured worst {s['Emax']:.6f} Bv")
    sums = {}
    for term in terms:
        act = [i for i in range(len(body)) if bud.active[i]
               and bld.label_of[i] == term]
        act.sort(key=lambda i: -bud.cap[i])
        sc = sum(bud.cap[i] for i in act)
        so = sum(bud.obs[i] for i in act)
        want = s["by"].get(term, (0.0, 0.0))
        ok = abs(sc - want[1]) < 1e-9 and abs(so - want[0]) < 1e-9
        sums[term] = (sc, so)
        out(f"  {term}: {len(act)} active instructions; capacity sum "
            f"{sc:.6f}, observed sum {so:.6f}; the part's figure in the "
            f"summary: capacity {want[1]:.6f}, observed {want[0]:.6f} "
            f"({'EQUAL' if ok else 'NOT EQUAL'})")
        run, shown = 0.0, 0
        for i in act[:top]:
            op, _r, srcs = body[i]
            ln = bud.cap_lane[i]
            run += bud.cap[i]
            shown += 1
            out(f"    v{i:<4d} {sf.OP_NAMES[op]:6s} "
                f"({', '.join(src_str(x) for x in srcs):16s}) capacity "
                f"{bud.cap[i]:.6f} observed {bud.obs[i]:.6f} cap from "
                f"{RG.show(ln, fn) if ln else '-'} (running {run:.6f})")
        rest = act[top:]
        if rest:
            out(f"    ... {len(rest)} more, capacity {sum(bud.cap[i] for i in rest):.6f}"
                f", observed {sum(bud.obs[i] for i in rest):.6f}; the "
                f"largest of them {bud.cap[rest[0]]:.6f}")
        # the instructions whose capacity is far above what was observed
        over = [i for i in act if bud.cap[i] > 0 and
                bud.cap[i] > 4 * bud.obs[i] and bud.cap[i] > 0.01]
        if over:
            out(f"    capacity over 4 times observed (and over 0.01 Bv): "
                + ", ".join(f"v{i} ({bud.cap[i]:.4f} / {bud.obs[i]:.4f})"
                            for i in over[:8]))
    return s, sums, bud
