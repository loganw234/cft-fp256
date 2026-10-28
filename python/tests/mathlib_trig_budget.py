# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The first-order error budget of sin, cos and tan (parcel M2G2b): the study's
3.2 (docs/studies/M2-trig.md), the model's m2budget.py (docs/studies/m2/, which
nothing in the tree imports) ported onto parcel M2G2a's Build, extending
mathlib_budget's Analyzer and Budget (the six's tool, imported and never edited)
by subclass.

What the six's tool does is in mathlib_budget's docstring: the original run in
softfloat, a twin run in exact arithmetic that freezes the values that are data,
each rounding's error delta_i, the reverse sweep s_i = dV/dv_i from V, and over
a sample of arguments M's largest value plus the sum of each instruction's
largest CAPACITY |s_i| ulp(v_i)/2, in units of Bv, which must be under 1. What
sin, cos and tan add (the study's 3.2, items 6 and 7 of 3.6), each a defect the
model found in its own tool:

  * an IXOR with the sign word, or with a value of integer instructions that
    carries it (V's sign by the quadrant), is a NEGATION: continuous, not data
    (TrigAnalyzer.negs). Taken as data it cuts the sweep at V's own sign;
  * the reduction's error-free phases (EXACT_PHASES: red-setup, red-window,
    red-products, red-coarse, red-mid) are frozen WHOLE in the twin: their
    instructions are exact or capture their rounding exactly (the audit checks
    each claim lane by lane), and recomputing a TwoProd's product exactly under
    a frozen modular quotient moved the model's method error to 2^+822 Bv;
  * a RECIP_SEED's output is data and its source is not: tan's denominator D_h
    feeds the seed, and freezing D_h at its rounded value while the twin
    recomputes D's low word lost that word (2^+46.7 Bv against a measured
    0.048).

The regions are the study's five (mathlib_trig_harness.REGIONS: edge, near,
zero, small, random), the lanes m2measure.py's sample() draws for a seed
(mathlib_trig_harness.sample, ported by parcel M2G2a), the decided G (44, 46,
46), rne: V is the same under every attribute (check_attributes), so the rne
budget is every attribute's.

Room for fp32 (parcel M2F). TrigAnalyzer takes V as the words of the build's
probes: Vh and Vl, or V0, V1 and V2 (a triple word, as parcel M2X's
tw32_budget.py seeds them), and the frozen phases as an argument
(`exact_phases`: M2X froze red-products-low too). A build whose probes lack
the words named is refused by name.

THE CHECK `budget` (check_budget) has legs, each a finding that begins with
"budget:":

  bound      the budget's bound M_max + capacities under 1
  lane       no sampled lane's measured error past its bound (the tool's own
             soundness check: a fault of the fragment moves M and the
             capacities with it, a fault of the tool does not)
  residual   what first order leaves out, |V - f - (M + sum delta_i s_i)| / Bv,
             is MEASURED and stated beside the bound and is not bounded; the
             bound with it added is held under 1 as the study holds it (3.2:
             "0.106 with its residual")
  reach      the sweep reached the roundings: some instruction rounds and its
             observed contribution is not zero
  reference  the model's own figures at the model's own lanes, when the caller
             has them (`expect`): the rounding instructions, M, the
             capacities and the bound equal to the model's digits
  attributes V bit-identical across the five attributes on every budgeted lane
             (check_attributes)
"""

import copy
import math
import sys
import time
from pathlib import Path

import mpmath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_budget as B  # noqa: E402
import mathlib_trig_harness as T  # noqa: E402

CONT = B.CONT
# the phases after V: the rounding, the test, the specials (the model's
# AFTER_V; mathlib_budget's own names the six's phases)
AFTER_V = ("final", "range", "special", "classify")
# the reduction's error-free phases, frozen whole in the twin (m2budget.py:46)
EXACT_PHASES = ("red-setup", "red-window", "red-products", "red-coarse",
                "red-mid")

# Faults of the TOOL, for the tests (never mathlib_budget.PLANTS, which the
# six's tests hold to their table). A plant that could not act is refused by
# name. The faults of the fragment are mathlib.TRIG_PLANTS'.
TOOL_PLANTS = {
    "seed_source_frozen": "a RECIP_SEED's source frozen as data with every "
                          "other non-arithmetic instruction's (3.6, item 7: "
                          "tan's bound 2^+46.7 Bv against a measured 0.048)",
    "phases_unfrozen": "the reduction's error-free phases recomputed exactly "
                       "in the twin (3.6, item 6: a method error of 2^+822 Bv "
                       "under a frozen modular quotient)",
    "negation_as_data": "an IXOR with the sign word taken as integer data, "
                        "not as a negation: the sweep stops at V's sign",
    "capacities_dropped": "the capacities left out of the bound, which is M "
                          "alone, so the lanes' rounding errors pass it (the "
                          "six's plant of the same name, for this tool)",
}


def _refuse(plant, build, why):
    return ValueError(f"tool plant {plant!r} does not apply to "
                      f"{build.meta['fn']} at {build.fmt.name}: {why}")


class TrigAnalyzer(B.Analyzer):
    """mathlib_budget.Analyzer with the model's trig extensions (the module
    docstring), V's words from the probes and the frozen phases an argument.
    `plant` names a fault of the tool (TOOL_PLANTS)."""

    def __init__(self, build, exact_phases=EXACT_PHASES, plant=None):
        # not Analyzer.__init__: its check names the double word
        if plant is not None and plant not in TOOL_PLANTS:
            raise ValueError(f"unknown tool plant {plant!r}: "
                             f"{', '.join(TOOL_PLANTS)}")
        self.plant = plant
        probes = build.probes
        self.seeds = ("V0", "V1", "V2") if "V0" in probes else ("Vh", "Vl")
        lost = [k for k in self.seeds + ("Bv",) if k not in probes]
        if lost:
            raise ValueError(f"{build.fmt.name} {build.meta.get('fn')} has no "
                             f"budget: its Build keeps no probe {lost}")
        self.b = build
        self.fmt = build.fmt
        self.body, self.phases = build.body, build.phase_of
        self.probes, self.words = probes, build.words
        self.p = self.fmt.prec
        self.prec = 6 * self.p + 300
        fmt, body, sm = self.fmt, self.body, self.fmt.sign_mask
        # CONTINUOUS values (arithmetic, a SELECT, the input, a negation) and
        # the negations: an IXOR of a continuous value with a SIGN CARRIER (the
        # sign word, or a value of integer instructions, whose bits are 0 or
        # the sign: V's sign by the quadrant) is a negation
        # self.negs[i] = (the continuous operand, the carrier)
        cont, self.negs = set(), {}
        for i, (op, _r, srcs) in enumerate(body):
            if op in CONT or op == sf.OP_SELECT:
                cont.add(i)
            elif op == sf.OP_IXOR and plant != "negation_as_data":
                kinds = []
                for s in srcs:
                    if s[0] == "in" or (s[0] == "v" and s[1] in cont):
                        kinds.append("c")
                    elif s[0] == "w" and self.words[s[1]] in (0, sm):
                        kinds.append("s")
                    elif s[0] == "v" and s[1] not in cont:
                        kinds.append("s")
                    else:
                        kinds.append("?")
                if sorted(kinds) == ["c", "s"]:
                    k = kinds.index("c")
                    self.negs[i] = (srcs[k], srcs[1 - k])
                    cont.add(i)
        if plant == "negation_as_data" and not any(
                op == sf.OP_IXOR for op, _r, _s in body):
            raise _refuse(plant, build, "it has no IXOR")
        # the values that are DATA, not errors: the sources of the integer
        # operations and compares and of a SELECT's condition before V is
        # formed, but not a seed's source, nor a negation's operand
        seed_ops = (sf.OP_RECIP_SEED, sf.OP_RSQRT_SEED)
        if plant == "seed_source_frozen" and not any(
                op in seed_ops for op, _r, _s in body):
            raise _refuse(plant, build, "it has no RECIP_SEED")
        dfeed = set()
        for i, (op, _r, srcs) in enumerate(body):
            if op in CONT or self.phases[i] in AFTER_V:
                continue
            if op in seed_ops and plant != "seed_source_frozen":
                # a seed's OUTPUT is data (frozen as any non-arithmetic value
                # is), but what it reads is not (3.6, item 7)
                continue
            if i in self.negs:
                s = self.negs[i][1]
                if s[0] == "v":
                    dfeed.add(s[1])
                continue
            for s in ([srcs[2]] if op == sf.OP_SELECT else list(srcs)):
                if s[0] == "v":
                    dfeed.add(s[1])
        frozen = {ref[1] for ref in build.meta.get("data", ())}
        self.exact_phases = () if plant == "phases_unfrozen" \
            else tuple(exact_phases)
        exact_ph = {i for i in range(len(body))
                    if self.phases[i] in self.exact_phases}
        if plant == "phases_unfrozen" and not any(
                ph in EXACT_PHASES for ph in self.phases):
            raise _refuse(plant, build, "it has no error-free phase")
        self.dfeed = dfeed | frozen | exact_ph

    def analyze(self, xa):
        """The model's analyze(): one lane's Lane (xa, vals, ex, delta, adj, V,
        Vex, Bv)."""
        fmt, body = self.fmt, self.body
        vals = ml._values(fmt, body, self.words, xa)
        sm = fmt.sign_mask
        with mpmath.workprec(self.prec):
            def num(bits):
                try:
                    return B.to_mp(ml._dec(fmt, bits))
                except ValueError:
                    return None
            n = len(body)
            ex, delta = [None] * n, [None] * n
            sel_take, negsign = {}, {}

            def exv(s):
                return ex[s[1]] if s[0] == "v" else \
                    num(self._bits(s, vals, xa))

            def ov(s):
                return num(self._bits(s, vals, xa))
            for i, (op, _r, srcs) in enumerate(body):
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
                        e_x, o_x = (a[0] * a[1] + a[2],
                                    oa[0] * oa[1] + oa[2])
                    elif op == sf.OP_NEG:
                        e_x, o_x = -a[0], -oa[0]
                    else:
                        e_x, o_x = abs(a[0]), abs(oa[0])
                    ex[i] = e_x
                    vi = num(vals[i])
                    delta[i] = None if vi is None else vi - o_x
                elif op == sf.OP_SELECT and i not in self.dfeed:
                    take = (self._bits(srcs[2], vals, xa) & ~sm) != 0
                    sel_take[i] = take
                    ex[i] = exv(srcs[0] if take else srcs[1])
                else:
                    ex[i] = num(vals[i])
            adj = [mpmath.mpf(0)] * n
            for nm in self.seeds:                       # V's words
                adj[self.probes[nm][1]] += 1
            for i in range(n - 1, -1, -1):
                g = adj[i]
                if g == 0:
                    continue
                op, _r, srcs = body[i]
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
            L = B.Lane()
            L.xa, L.vals, L.ex, L.delta, L.adj = xa, vals, ex, delta, adj
            L.V = sum(num(vals[self.probes[nm][1]]) for nm in self.seeds)
            L.Vex = sum(ex[self.probes[nm][1]] for nm in self.seeds)
            L.Bv = abs(num(vals[self.probes["Bv"][1]]))
            return L


def true_trig(fn, fmt, xa):
    """sin, cos or tan of the argument xa by mpmath at the caller's working
    precision (harness.true_value on the encoding's exact value)."""
    return T.true_value(fn, ml._dec(fmt, xa))


class TrigBudget(B.Budget):
    """mathlib_budget.Budget over the trig routines: for each instruction that
    ever rounds its largest observed contribution (`obs`) and capacity (`cap`),
    in Bv, the largest method error M and total error E, and the RESIDUAL
    (`resid`): what first order leaves out, |V - f - (M + sum delta_i s_i)| /
    Bv, measured on the same lanes and not bounded (the model's `resid`).
    Only the lanes the main path answers are analysed (harness.in_main).
    `plant` names a fault of the tool (TOOL_PLANTS)."""

    def __init__(self, build, exact_phases=EXACT_PHASES, plant=None):
        # not Budget.__init__: its plant table is the six's
        self.plant = plant
        self.an = TrigAnalyzer(build, exact_phases, plant)
        n = len(self.an.body)
        self.obs, self.cap = [0.0] * n, [0.0] * n
        self.active = [False] * n
        self.Mmax = self.Emax = self.resid = 0.0
        self.lanes = self.skipped = 0
        self.worst_x = None

    def add(self, xs):
        an, fmt = self.an, self.an.fmt
        fn = an.b.meta["fn"]
        for xa in xs:
            if not T.in_main(fmt, fn, xa):
                self.skipped += 1
                continue
            L = an.analyze(xa)
            with mpmath.workprec(an.prec):
                Tv = true_trig(fn, fmt, xa)
                Bv = L.Bv
                E = float(abs((L.V - Tv) / Bv))
                self.Mmax = max(self.Mmax, float(abs((L.Vex - Tv) / Bv)))
                if E > self.Emax:
                    self.Emax, self.worst_x = E, xa
                first = L.Vex - Tv
                for i, contrib, capi, d in an.contributions(L):
                    if d != 0:
                        self.active[i] = True
                    first += contrib
                    self.obs[i] = max(self.obs[i], abs(float(contrib / Bv)))
                    if self.plant != "capacities_dropped":
                        self.cap[i] = max(self.cap[i], float(capi / Bv))
                self.resid = max(self.resid,
                                 abs(float((L.V - Tv - first) / Bv)))
            self.lanes += 1
        return self

    def summary(self):
        """mathlib_budget.Budget.summary() and the residual: {Emax, Mmax,
        S_obs, S_cap, bound = Mmax + S_cap, resid, lanes, skipped (not on the
        main path), rounding instructions, by_phase}, in units of Bv."""
        s = super().summary()
        s["resid"], s["skipped"] = self.resid, self.skipped
        return s


def budget_of(build, xs, exact_phases=EXACT_PHASES, plant=None):
    """The summary of TrigBudget(build).add(xs), and the budget."""
    bud = TrigBudget(build, exact_phases, plant).add(xs)
    return bud.summary(), bud


# ---- the attributes ------------------------------------------------------------

def v_words(build, x):
    """The bits of V's words (Vh and Vl, or V0, V1 and V2) on one lane."""
    names = ("V0", "V1", "V2") if "V0" in build.probes else ("Vh", "Vl")
    _res, _fl, pr = build.run(x, names)
    return tuple(pr[nm] for nm in names)


def with_directed_before_v(build, which=None):
    """A copy of the build in which one rounding instruction BEFORE V carries
    the program's own attribute (a MUL of the polynomial, the first of the
    phase `sincos`, or `which`, an instruction index): the fault the
    attributes' leg exists for (M2X's `attrs` mode: a planted directed MUL
    turned it red). Refused by name under rne, where the attribute is the
    default and the fault changes nothing."""
    if build.rnd == sf.RND_RNE:
        raise ValueError("the plant 'directed_before_v' does not apply under "
                         "rne: the program's attribute is the default's")
    if which is None:
        which = next(i for i, (op, _r, _s) in enumerate(build.body)
                     if op == sf.OP_MUL and build.phase_of[i] == "sincos")
    op, r, srcs = build.body[which]
    c = copy.copy(build)
    c.body = list(build.body)
    c.body[which] = (op, build.rnd, srcs)
    return c


def check_attributes(builds, xs, label="random"):
    """[finding], (lanes, differing): attributes. `builds` {attribute: Build}
    of one function and format; V (its probes' words) bit-identical across them
    on every main-path lane of xs, so that a budget under one attribute is
    every attribute's (no directed rounding comes before V: the in-lane test and
    the final sum come after). The first attribute's build is the reference."""
    rnds = sorted(builds)
    ref = builds[rnds[0]]
    fmt, fn = ref.fmt, ref.meta["fn"]
    n, bad = 0, []
    for x in xs:
        if not T.in_main(fmt, fn, x):
            continue
        n += 1
        want = v_words(ref, x)
        for r in rnds[1:]:
            if v_words(builds[r], x) != want:
                bad.append((x, r))
                break
    where = f"budget: {fn} {fmt.name} {label}"
    out = []
    if bad:
        x, r = bad[0]
        out.append(f"{where}: V differs across the attributes on {len(bad)} "
                   f"of {n} lanes, first {hex(x)} ({sf.RND_NAMES[r]} against "
                   f"{sf.RND_NAMES[rnds[0]]}): a rounding comes before V, so "
                   f"the rne budget is not every attribute's")
    return out, (n, len(bad))


# ---- the check -----------------------------------------------------------------

def _digits(v):
    return f"{v:.4g}"


def judge(s, where, expect=None):
    """[finding]: the legs of the check `budget` on a summary (budget_of's):
    bound, lane, residual, reach and, with `expect` (the model's figures:
    {"rounding", "Mmax", "S_cap", "bound"} at its lanes), reference. Split from
    the running so that a test can doctor one figure and show its leg fail
    alone."""
    out = []
    bound, resid = s["bound"], s["resid"]
    if s["lanes"] == 0:
        out.append(f"{where}: no lane of the sample is on the main path")
        return out
    if bound >= 1:
        out.append(f"{where}: the budget's bound is {bound:.3g} Bv (M "
                   f"{s['Mmax']:.3g} + capacities {s['S_cap']:.3g}), not "
                   f"under 1")
    if s["Emax"] > bound * 1.001:
        out.append(f"{where}: a lane's error {s['Emax']:.3g} Bv is past the "
                   f"budget's bound {bound:.3g}")
    if bound < 1 <= bound + resid:
        out.append(f"{where}: the residual {resid:.3g} Bv (what first order "
                   f"leaves out, measured, not bounded) takes the bound "
                   f"{bound:.3g} to {bound + resid:.3g}, not under 1")
    if s["rounding"] == 0 or s["S_obs"] == 0:
        out.append(f"{where}: the reverse sweep reached no rounding "
                   f"instruction ({s['rounding']} round, observed "
                   f"contributions summing to {s['S_obs']:.3g} Bv): the bound "
                   f"is the method error alone")
    if expect is not None:
        diff = [f"{k} {_digits(s[k]) if k != 'rounding' else s[k]} against "
                f"the model's {_digits(v) if k != 'rounding' else v}"
                for k, v in expect.items()
                if (s[k] != v if k == "rounding"
                    else _digits(s[k]) != _digits(v))]
        if diff:
            out.append(f"{where}: differs from the model's figures at the "
                       f"model's lanes: {'; '.join(diff)}")
    return out


def check_budget(b, xs, label="random", plant=None, expect=None,
                 attrs=None, exact_phases=EXACT_PHASES, attr_xs=None):
    """[finding], summary: budget. The first-order budget of the build over the
    lanes xs (the main path's), judge()'s legs; with `attrs` ({attribute:
    Build} of the same function and format, the five) the attributes' leg as
    well, on every lane of xs or of `attr_xs`. The summary is budget_of()'s
    (Emax, Mmax, S_obs, S_cap, bound, resid, lanes, rounding, by_phase), every
    figure in units of Bv."""
    s, _bud = budget_of(b, xs, exact_phases, plant)
    where = (f"budget: {b.meta['fn']} {b.fmt.name} {sf.RND_NAMES[b.rnd]} "
             f"{label}")
    out = judge(s, where, expect)
    if attrs is not None:
        found, (n, bad) = check_attributes(attrs, xs if attr_xs is None
                                           else attr_xs, label)
        out += found
        s["attr_lanes"], s["attr_differ"] = n, bad
    return out, s


def bits_log2(bound):
    """-log2(bound): the bits of margin a bound of `bound` Bv leaves."""
    return B.bits_log2(bound)
