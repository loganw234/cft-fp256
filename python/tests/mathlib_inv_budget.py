# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The first-order error budget of atan, asin, acos and atan2 (parcel M4G4):
the study's 3.2 (docs/studies/M4-invtrig.md), the model's m4budget.py (docs/
studies/m4/, which nothing in the tree imports) ported onto parcel M4G1's
Build, extending mathlib_budget's Analyzer and Budget (the six's tool,
imported and never edited) by subclass, as mathlib_trig_budget does.

What the six's tool does is in mathlib_budget's docstring: the original run in
softfloat, a twin run in exact arithmetic that freezes the values that are
data, each rounding's error delta_i, the reverse sweep s_i = dV/dv_i from V,
and over a sample of lanes M's largest value plus the sum of each
instruction's largest CAPACITY |s_i| ulp(v_i)/2, in units of Bv, which must be
under 1. What the inverse functions add:

  * a lane is the build's inputs in Build.inputs' order: one encoding, or the
    pair (y, x) of atan2 (the build's ("a", "b")); every ("in", name) source
    is read by its NAME;
  * a SELECT between the words 0 and SIGN is a SIGN CARRIER, not a value
    (inv_recon's sigma, sg = sel(SIGN, ZERO, sigc)). The tree's trig tool
    (mathlib_trig_budget) adds every SELECT to the continuous values, which is
    right for sin, cos and tan and WRONG here: the IXOR that applies sigma
    then looks like integer data, its operands are frozen, and every rounding
    before the reconstruction moves into M (the study's 3.6, item 3: the
    tell was a residual of exactly 0 and zero capacity in every phase but the
    reconstruction). An IXOR of a continuous value with the sign word or with
    a value of integer instructions is a negation, as in the trig tool;
  * the data frozen in the twin: the index's magic-number FMA
    (meta["data"]), the sources of integer instructions, compares and SELECT
    conditions before V is formed, MIN's and MAX's operands; a seed's
    OUTPUT (RECIP_SEED, RSQRT_SEED) is data and its source is not;
  * V = Vh + Vl, Bv from the probe, the phases after V ("final", "special",
    "classify"); the lanes are those the harness's in_main answers, the true
    value the harness's true_value.

THE CHECK `budget` (check_budget) has legs, each a finding that begins with
"budget:":

  bound      the budget's bound M_max + capacities under 1
  lane       no sampled lane's measured error past its bound by more than
             0.1% (`Emax > bound * 1.001`, the six's tolerance, copied so that
             the tools judge alike; it is for float noise in the sums, not
             derived). The tool's own soundness check: a fault of the
             fragment moves M and the capacities with it, a fault of the tool
             does not
  residual   what first order leaves out, |V - f - (M + sum delta_i s_i)| /
             Bv, is MEASURED and stated beside the bound and is not bounded;
             the bound with it added is held under 1
  reach      some instruction rounds and its observed contribution is not
             zero
  head       (the study's test of 3.6, item 3) on the edge region the head
             phase's capacity is not zero and the residual is not exactly 0:
             the two tells of a sweep that stopped at the reconstruction
  reference  the model's own digits at the model's own lanes, when the caller
             has them (`expect`): the rounding instructions, M, the
             capacities, the bound
  attributes V bit-identical across the five attributes on every budgeted
             lane (check_attributes)

Each cell's FIGURE (cell_figure): the largest of the budget's bound, the
bound with its residual and the sampled worst of the inv-bound lanes of the
cell, called which of them it is. A budget bounds its own sample (3.3), and a
sampled worst is a lower bound on the true worst: the figure is neither a
proof.
"""

import copy
import sys
from pathlib import Path

import mpmath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_budget as B  # noqa: E402
import mathlib_inv_harness as I  # noqa: E402

CONT = B.CONT
# the phases after V: the rounding, the specials, the classification
AFTER_V = ("final", "special", "classify")
SEED_OPS = (sf.OP_RECIP_SEED, sf.OP_RSQRT_SEED)
RND_NAMES = sf.RND_NAMES

# Faults of the TOOL, for the tests (never mathlib_budget.PLANTS, which the
# six's tests hold to their table, nor INV_PLANTS, which are the fragment's).
# A plant that could not act is refused by name.
TOOL_PLANTS = {
    "sign_select_as_value": "a SELECT between the words 0 and SIGN taken as a "
                            "continuous value (the trig tool's rule), so the "
                            "IXOR applying sigma is integer data (the study's "
                            "3.6, item 3: every rounding before the "
                            "reconstruction moves into M)",
    "seed_source_frozen": "a RECIP_SEED's or RSQRT_SEED's source frozen as "
                          "data with every other non-arithmetic "
                          "instruction's",
    "negation_as_data": "an IXOR with a sign carrier taken as integer data, "
                        "not as a negation: the sweep stops at V's sign",
    "capacities_dropped": "the capacities left out of the bound, which is M "
                          "alone, so the lanes' rounding errors pass it",
    "inputs_swapped": "atan2's two inputs read in each other's place by the "
                      "analysis, original run and twin alike (Build.inputs' "
                      "order taken as (x, y)), the true value of (y, x) "
                      "unchanged",
}


def _refuse(plant, build, why):
    return ValueError(f"tool plant {plant!r} does not apply to "
                      f"{build.meta['fn']} at {build.fmt.name}: {why}")


class InvAnalyzer(B.Analyzer):
    """mathlib_budget.Analyzer with the inverse functions' extensions (the
    module docstring). `plant` names a fault of the tool (TOOL_PLANTS)."""

    def __init__(self, build, plant=None):
        # not Analyzer.__init__: its check names the six's double word
        if plant is not None and plant not in TOOL_PLANTS:
            raise ValueError(f"unknown tool plant {plant!r}: "
                             f"{', '.join(TOOL_PLANTS)}")
        fn = build.meta.get("fn")
        if fn not in ml.INV_NAMES:
            raise ValueError(f"{fn!r} is not one of {', '.join(ml.INV_NAMES)}: "
                             f"this is the inverse functions' budget")
        probes = build.probes
        lost = [k for k in ("Vh", "Vl", "Bv") if k not in probes]
        if lost or build.meta.get("family") != "double word":
            raise ValueError(f"{build.fmt.name} {fn} has no budget: its V is "
                             f"not a double word (probes missing: {lost})")
        self.plant = plant
        self.b = build
        self.fmt = build.fmt
        self.body, self.phases = build.body, build.phase_of
        self.probes, self.words = probes, build.words
        self.inputs = tuple(build.inputs)
        self.p = self.fmt.prec
        self.prec = 6 * self.p + 300
        body, sm = self.body, self.fmt.sign_mask

        def signword(s):
            return s[0] == "w" and self.words[s[1]] in (0, sm)
        # CONTINUOUS values and the negations: an IXOR of a continuous value
        # with a SIGN CARRIER (the sign word, or a value of integer
        # instructions, or a SELECT between the words 0 and SIGN) is a
        # negation; self.negs[i] = (the continuous operand, the carrier)
        cont, self.negs, self.carriers = set(), {}, set()
        for i, (op, _r, srcs) in enumerate(body):
            if op == sf.OP_SELECT and signword(srcs[0]) and signword(srcs[1]):
                self.carriers.add(i)
                if plant != "sign_select_as_value":
                    continue
            if op in CONT or op == sf.OP_SELECT:
                cont.add(i)
            elif op == sf.OP_IXOR and plant != "negation_as_data":
                kinds = []
                for s in srcs:
                    if s[0] == "in" or (s[0] == "v" and s[1] in cont):
                        kinds.append("c")
                    elif signword(s):
                        kinds.append("s")
                    elif s[0] == "v" and s[1] not in cont:
                        kinds.append("s")
                    else:
                        kinds.append("?")
                if sorted(kinds) == ["c", "s"]:
                    k = kinds.index("c")
                    self.negs[i] = (srcs[k], srcs[1 - k])
                    cont.add(i)
        if plant == "sign_select_as_value" and not self.carriers:
            raise _refuse(plant, build, "it has no SELECT between 0 and SIGN")
        if plant == "negation_as_data" and not any(
                op == sf.OP_IXOR for op, _r, _s in body):
            raise _refuse(plant, build, "it has no IXOR")
        if plant == "seed_source_frozen" and not any(
                op in SEED_OPS for op, _r, _s in body):
            raise _refuse(plant, build, "it has no seed")
        if plant == "inputs_swapped" and len(self.inputs) < 2:
            raise _refuse(plant, build, "it has one input")
        # the values that are DATA, not errors: the sources of the integer
        # operations and compares and of a SELECT's condition before V is
        # formed (MIN's and MAX's operands among them), but not a seed's
        # source, nor a negation's operand
        dfeed = set()
        for i, (op, _r, srcs) in enumerate(body):
            if op in CONT or self.phases[i] in AFTER_V:
                continue
            if op in SEED_OPS and plant != "seed_source_frozen":
                continue                # a seed's source is not data
            if i in self.negs:
                s = self.negs[i][1]
                if s[0] == "v":
                    dfeed.add(s[1])
                continue
            for s in ([srcs[2]] if op == sf.OP_SELECT else list(srcs)):
                if s[0] == "v":
                    dfeed.add(s[1])
        frozen = {ref[1] for ref in build.meta.get("data", ())}
        self.dfeed = dfeed | frozen

    def _bits(self, s, vals, xa):
        """The bits of a source on the lane xa (an encoding, or the tuple of
        encodings in Build.inputs' order): an input by its name."""
        if s[0] == "v":
            return vals[s[1]]
        if s[0] == "in":
            names = self.inputs
            if isinstance(xa, tuple):
                return dict(zip(names, xa))[s[1]]
            return xa
        return self.words[s[1]]

    def analyze(self, xa):
        """The model's analyze(): one lane's Lane (xa, vals, ex, delta, adj,
        V, Vex, Bv)."""
        fmt, body = self.fmt, self.body
        xa_true = xa
        if self.plant == "inputs_swapped":
            xa = xa[::-1]               # the fault: x read as y and y as x
        vals = ml._values(fmt, body, self.words, xa, None, self.inputs)
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
            for nm in ("Vh", "Vl"):                     # V's words
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
            L.xa, L.vals, L.ex, L.delta, L.adj = xa_true, vals, ex, delta, adj
            ih, il = self.probes["Vh"][1], self.probes["Vl"][1]
            L.V = num(vals[ih]) + num(vals[il])
            L.Vex = ex[ih] + ex[il]
            L.Bv = abs(num(vals[self.probes["Bv"][1]]))
            return L


class InvBudget(B.Budget):
    """mathlib_budget.Budget over the inverse routines: for each instruction
    that ever rounds its largest observed contribution (`obs`) and capacity
    (`cap`), in Bv, the largest method error M and total error E, and the
    RESIDUAL (`resid`): what first order leaves out, |V - f - (M + sum delta_i
    s_i)| / Bv, measured on the same lanes and not bounded (the model's
    `resid`). Only the lanes the main path answers are analysed
    (harness.in_main). `plant` names a fault of the tool (TOOL_PLANTS)."""

    def __init__(self, build, plant=None):
        # not Budget.__init__: its plant table is the six's
        self.plant = plant
        self.an = InvAnalyzer(build, plant)
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
            if not I.in_main(fn, fmt, xa):
                self.skipped += 1
                continue
            L = an.analyze(xa)
            with mpmath.workprec(an.prec):
                Tv = I.true_value(fn, fmt, xa)
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


def budget_of(build, xs, plant=None):
    """The summary of InvBudget(build).add(xs), and the budget."""
    bud = InvBudget(build, plant).add(xs)
    return bud.summary(), bud


# ---- the attributes ------------------------------------------------------------

def v_words(build, x):
    """The bits of V's words (Vh and Vl) on one lane."""
    _res, _fl, pr = build.run(x, ("Vh", "Vl"))
    return pr["Vh"], pr["Vl"]


def with_directed_before_v(build, which=None):
    """A copy of the build in which one rounding instruction BEFORE V carries
    the program's own attribute (the last ADD of the reconstruction, or `which`, an
    instruction index): the fault the attributes' leg exists for. Refused by
    name under rne, where the attribute is the default and the fault changes
    nothing."""
    if build.rnd == sf.RND_RNE:
        raise ValueError("the plant 'directed_before_v' does not apply under "
                         "rne: the program's attribute is the default's")
    if which is None:
        which = [i for i, (op, _r, _s) in enumerate(build.body)
                 if op == sf.OP_ADD and build.phase_of[i] == "recon"][-1]
    op, _r, srcs = build.body[which]
    c = copy.copy(build)
    c.body = list(build.body)
    c.body[which] = (op, build.rnd, srcs)
    return c


def check_attributes(builds, xs, label="random"):
    """[finding], (lanes, differing): attributes. `builds` {attribute: Build}
    of one function and format; V (its probes' words) bit-identical across
    them on every main-path lane of xs, so that a budget under one attribute
    is every attribute's (no directed rounding comes before V: the in-lane
    test and the final sum come after). The first attribute's build is the
    reference."""
    rnds = sorted(builds)
    ref = builds[rnds[0]]
    fmt, fn = ref.fmt, ref.meta["fn"]
    n, bad = 0, []
    for x in xs:
        if not I.in_main(fn, fmt, x):
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
                   f"of {n} lanes, first {I._hexes([x])} ({RND_NAMES[r]} "
                   f"against {RND_NAMES[rnds[0]]}): a rounding comes before "
                   f"V, so the rne budget is not every attribute's")
    return out, (n, len(bad))


# ---- the check -----------------------------------------------------------------

def _digits(v):
    return f"{v:.4g}"


def judge(s, where, expect=None, head=False):
    """[finding]: the legs of the check `budget` on a summary (budget_of's):
    bound, lane, residual, reach, with `head` the head leg and with `expect`
    (the model's figures: {"rounding", "Mmax", "S_cap", "bound", "resid"} at
    its lanes) reference. Split from the running so that a test can doctor
    one figure and show its leg fail alone."""
    out = []
    bound, resid = s["bound"], s["resid"]
    if s["lanes"] == 0:
        out.append(f"{where}: no lane of the sample is on the main path")
        return out
    if bound >= 1:
        out.append(f"{where}: the budget's bound is {bound:.3g} Bv (M "
                   f"{s['Mmax']:.3g} + capacities {s['S_cap']:.3g}), not "
                   f"under 1")
    if s["Emax"] > bound * 1.001:           # the six's 0.1% (module docstring)
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
    if head:
        cap = s["by_phase"].get("head", (0.0, 0.0))[1]
        if cap == 0 or resid == 0:
            out.append(f"{where}: the head phase's capacity is {cap:.3g} Bv "
                       f"and the residual {resid:.3g} Bv: on this region "
                       f"neither may be exactly 0 (the sweep stopped short "
                       f"of the head: the study's 3.6, item 3, a sign "
                       f"carrier taken as a value)")
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


def check_budget(b, xs, label="random", plant=None, expect=None, attrs=None,
                 attr_xs=None, head=None):
    """[finding], summary: budget. The first-order budget of the build over
    the lanes xs (the main path's), judge()'s legs (the head leg on the
    region `edge`, or where `head` says); with `attrs` ({attribute: Build} of
    the same function and format, the five) the attributes' leg as well, on
    every lane of xs or of `attr_xs`. The summary is budget_of()'s (Emax,
    Mmax, S_obs, S_cap, bound, resid, lanes, rounding, by_phase), every
    figure in units of Bv."""
    s, _bud = budget_of(b, xs, plant)
    where = (f"budget: {b.meta['fn']} {b.fmt.name} {RND_NAMES[b.rnd]} "
             f"{label}")
    out = judge(s, where, expect, head=(label == "edge") if head is None
                else head)
    if attrs is not None:
        found, (n, bad) = check_attributes(attrs, xs if attr_xs is None
                                           else attr_xs, label)
        out += found
        s["attr_lanes"], s["attr_differ"] = n, bad
    return out, s


LEGS = ("bound", "lane", "residual", "reach", "head", "reference",
        "attributes")
_LEG_TEXT = (("head", "the head phase's capacity"),
             ("bound", "the budget's bound is"),
             ("lane", "a lane's error"),
             ("residual", "the residual"),
             ("reach", "reverse sweep reached no rounding"),
             ("reference", "differs from the model's figures"),
             ("attributes", "V differs across the attributes"))


def leg_of(finding):
    """The leg of check `budget` a finding belongs to (LEGS), or None: the
    legs' messages are told apart by their text."""
    for leg, text in _LEG_TEXT:
        if finding.startswith("budget:") and text in finding:
            return leg
    return None


# ---- the model's own figures ------------------------------------------------------
#
# docs/studies/m4/m4budget.py (the model, which nothing in the tree imports)
# run APART on the model's own lanes (m4measure.sample, the seed MODEL_SEED,
# MODEL_N lanes a cell, rne) for each of the 57 cells of the study's 3.2 at
# fp64, fp128 and fp256, and its figures copied here to four significant
# digits: (main lanes, rounding instructions, M_max, capacities summed, bound,
# residual), in units of Bv. The `reference` leg holds this tool to them. The
# lanes are the tree's sampler's (mathlib_inv_harness.sample), which equals
# the model's on every one of these cells (a scratch run, the lanes compared
# one list to the other).
MODEL_N = {'fp64': 16, 'fp128': 6, 'fp256': 5}
MODEL_SEED = 2
MODEL_FIGURES = {
    ("fp64", "atan", "random"): (16, 65, 0.0001511, 0.00212, 0.002271, 3.604e-10),
    ("fp64", "atan", "edge"): (16, 72, 0.003248, 0.01233, 0.01558, 0.0004076),
    ("fp64", "atan", "big"): (16, 63, 0.0001511, 0.001243, 0.001394, 1.22e-19),
    ("fp64", "atan", "small"): (16, 52, 5.839e-08, 0.002336, 0.002336, 3.375e-08),
    ("fp64", "asin", "random"): (16, 90, 0.0005179, 0.02732, 0.02784, 0.002809),
    ("fp64", "asin", "edge"): (16, 95, 0.003124, 0.02556, 0.02868, 0.002489),
    ("fp64", "asin", "big"): (16, 87, 0.0001734, 0.00344, 0.003614, 0.0004279),
    ("fp64", "asin", "small"): (16, 79, 0.0006592, 0.02002, 0.02068, 0.003341),
    ("fp64", "asin", "diag"): (16, 88, 0.0004057, 0.009082, 0.009487, 0.0008365),
    ("fp64", "acos", "random"): (16, 89, 0.0001801, 0.004217, 0.004398, 0.0001487),
    ("fp64", "acos", "edge"): (16, 95, 0.003229, 0.01995, 0.02318, 0.000895),
    ("fp64", "acos", "big"): (16, 85, 0.002752, 0.02114, 0.02389, 0.003093),
    ("fp64", "acos", "small"): (16, 81, 0.0001573, 0.002657, 0.002814, 1.172e-05),
    ("fp64", "acos", "diag"): (16, 89, 0.0005298, 0.009714, 0.01024, 0.0008365),
    ("fp64", "atan2", "random"): (14, 65, 0.0001515, 0.002494, 0.002646, 4.464e-07),
    ("fp64", "atan2", "edge"): (16, 73, 0.001234, 0.008833, 0.01007, 0.0006997),
    ("fp64", "atan2", "big"): (12, 64, 0.0001511, 0.001243, 0.001394, 3.776e-13),
    ("fp64", "atan2", "small"): (2, 58, 1.605e-12, 0.003492, 0.003492, 0.0005531),
    ("fp64", "atan2", "diag"): (16, 72, 0.0004083, 0.007376, 0.007784, 0.0003866),
    ("fp128", "atan", "random"): (6, 44, 6.637e-22, 0.0, 6.637e-22, 0.0),
    ("fp128", "atan", "edge"): (6, 78, 0.01123, 0.01841, 0.02964, 4.545e-21),
    ("fp128", "atan", "big"): (6, 45, 6.637e-22, 1.078e-21, 1.742e-21, 7.657e-256),
    ("fp128", "atan", "small"): (6, 60, 7.761e-21, 1.929e-20, 2.705e-20, 1.692e-27),
    ("fp128", "asin", "random"): (6, 90, 4.574e-21, 8.106e-20, 8.563e-20, 3.308e-21),
    ("fp128", "asin", "edge"): (6, 101, 0.01123, 0.01841, 0.02964, 1.031e-20),
    ("fp128", "asin", "big"): (6, 91, 5.247e-10, 8.54e-10, 1.379e-09, 4.209e-23),
    ("fp128", "asin", "small"): (6, 90, 4.574e-21, 8.106e-20, 8.563e-20, 3.308e-21),
    ("fp128", "asin", "diag"): (6, 98, 0.00183, 0.002927, 0.004757, 2.394e-21),
    ("fp128", "acos", "random"): (6, 93, 4.99e-08, 8.14e-08, 1.313e-07, 3.752e-24),
    ("fp128", "acos", "edge"): (6, 103, 0.0004706, 0.0007715, 0.001242, 1.713e-21),
    ("fp128", "acos", "big"): (6, 90, 3.677e-08, 5.985e-08, 9.662e-08, 5.86e-21),
    ("fp128", "acos", "small"): (6, 93, 4.99e-08, 8.14e-08, 1.313e-07, 3.752e-24),
    ("fp128", "acos", "diag"): (6, 98, 0.00183, 0.002927, 0.004757, 2.394e-21),
    ("fp128", "atan2", "random"): (6, 74, 0.000115, 0.0001879, 0.000303, 2.55e-21),
    ("fp128", "atan2", "edge"): (6, 80, 0.001757, 0.002872, 0.004629, 2.043e-22),
    ("fp128", "atan2", "big"): (3, 74, 6.637e-22, 4.314e-21, 4.978e-21, 1.051e-54),
    ("fp128", "atan2", "small"): (2, 70, 4.156e-37, 1.333e-20, 1.333e-20, 3.924e-21),
    ("fp128", "atan2", "diag"): (6, 77, 0.00183, 0.002927, 0.004757, 1.204e-21),
    ("fp256", "atan", "random"): (5, 46, 8.511e-59, 0.0, 8.511e-59, 0.0),
    ("fp256", "atan", "edge"): (5, 96, 0.001727, 0.01097, 0.0127, 1.406e-58),
    ("fp256", "atan", "big"): (5, 46, 8.511e-59, 0.0, 8.511e-59, 0.0),
    ("fp256", "atan", "small"): (5, 74, 4.872e-20, 3.167e-19, 3.654e-19, 8.524e-65),
    ("fp256", "asin", "random"): (5, 111, 4.873e-20, 3.167e-19, 3.655e-19, 2.918e-58),
    ("fp256", "asin", "edge"): (5, 122, 0.001727, 0.01097, 0.0127, 1.069e-58),
    ("fp256", "asin", "big"): (5, 113, 8.511e-59, 4.057e-58, 4.908e-58, 1.48e-65),
    ("fp256", "asin", "small"): (5, 111, 4.873e-20, 3.167e-19, 3.655e-19, 2.918e-58),
    ("fp256", "asin", "diag"): (5, 116, 0.004213, 0.002927, 0.00714, 1.15e-58),
    ("fp256", "acos", "random"): (5, 113, 8.511e-59, 4.057e-58, 4.908e-58, 3.304e-67),
    ("fp256", "acos", "edge"): (5, 120, 0.0004248, 0.002618, 0.003043, 1.742e-58),
    ("fp256", "acos", "big"): (5, 112, 8.511e-59, 9.476e-58, 1.033e-57, 3.581e-59),
    ("fp256", "acos", "small"): (5, 112, 8.511e-59, 4.057e-58, 4.908e-58, 1.592e-69),
    ("fp256", "acos", "diag"): (5, 117, 0.004213, 0.002927, 0.00714, 1.15e-58),
    ("fp256", "atan2", "random"): (4, 92, 1.083e-45, 7.042e-45, 8.126e-45, 3.865e-59),
    ("fp256", "atan2", "edge"): (5, 97, 0.0004269, 0.002628, 0.003055, 1.276e-59),
    ("fp256", "atan2", "big"): (3, 91, 8.511e-59, 4.057e-58, 4.908e-58, 2.431e-123),
    ("fp256", "atan2", "small"): (3, 89, 1.752e-92, 4.819e-58, 4.819e-58, 6.746e-59),
    ("fp256", "atan2", "diag"): (5, 98, 0.004213, 0.002927, 0.00714, 2.792e-59),
}


def model_expect(fmt_name, fn, region):
    """(lanes, expect) of one cell: the model's lane count and the figures
    check_budget's `expect` takes, from MODEL_FIGURES."""
    lanes, rounding, M, cap, bound, resid = MODEL_FIGURES[
        (fmt_name, fn, region)]
    return lanes, {"rounding": rounding, "Mmax": M, "S_cap": cap,
                   "bound": bound, "resid": resid}


def model_lanes(fmt, fn, region):
    """The model's lanes of a cell: MODEL_N of them at MODEL_SEED."""
    return I.sample(fn, fmt, region, MODEL_N[fmt.name], MODEL_SEED)


# ---- each cell's figure ----------------------------------------------------------

def sampled_worst(build, xs):
    """The largest |V - f| / Bv over the main-path lanes of xs, by
    mathlib_inv_harness.bound_log2 (inv-bound's): a LOWER BOUND on the true
    worst. 0.0 where every lane is exact or none is on the main path."""
    fn, fmt = build.meta["fn"], build.fmt
    w = None
    for x in xs:
        if not I.in_main(fn, fmt, x):
            continue
        r = I.bound_log2(build, x)
        if r is not None and (w is None or r > w):
            w = r
    return 0.0 if w is None else 2.0 ** w


def cell_figure(s, worst):
    """(figure, which): the largest of the budget's bound, the bound with its
    residual and the sampled worst `worst` (bound_table.py's rule: the study's
    3.3), and which of the three it is. Each is a figure about the lanes it
    was taken on."""
    cands = (("the budget's bound", s["bound"]),
             ("the budget's bound with its residual", s["bound"] + s["resid"]),
             ("the sampled worst", worst))
    which, top = max(cands, key=lambda kv: kv[1])
    return top, which


def bits_log2(bound):
    """-log2(bound): the bits of margin a bound of `bound` Bv leaves."""
    return B.bits_log2(bound)
