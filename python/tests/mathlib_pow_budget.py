# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The first-order error budget of pow, powr, pown, rootn and compound (parcel
M3G3): the study's 3.2 (docs/studies/M3-pow.md), the model's budget.py (docs/
studies/m3/, which nothing in the tree imports) ported onto parcel M3G1's and
M3G2's Build, extending mathlib_inv_budget's InvAnalyzer and InvBudget (M4G4's
port of the inverse functions' tool, imported and never edited) by subclass.

What the inverse functions' tool does is in mathlib_inv_budget's docstring: the
original run, a twin run in exact arithmetic freezing the data, each rounding's
error delta_i, the reverse sweep s_i = dV/dv_i from V, and over a sample of
lanes M's largest value plus the sum of each instruction's largest CAPACITY
|s_i| ulp(v_i)/2, in units of each lane's Bv, which must be under 1. What the
pow family adds:

  * TWO INPUTS and the INTEGER OPERAND. A lane is the harness's: the pair
    (x, y) for pow and powr, (x, n) for pown, rootn and compound; the build
    runs on lane_args(fn, lane) (the pair, or (x,)), and the true value is the
    harness's true_value(fn, fmt, lane);
  * V LIVES IN THE SCALED DOMAIN: V = f 2^-k, k = floor(nf / 8), nf the probe
    (bound_log2's convention); the true value is taken at 6p + 300 bits and
    scaled;
  * THE FIXED GRID IS AFTER V. It reads V_l with a CMPEQ (its round-to-odd);
    the inverse functions have no fixed grid, so their tool counts the phase
    "fixed-grid" as before V and freezes V_l as data, which stops the sweep at
    V_l: the first run's tell, a method error of 10^12 Bv on lanes whose
    measured error was 0.05 Bv (the study's 3.6, item 4). Here the phase is
    read as "final" (the model's remap) by a light PROXY of the build: its
    fmt, body, words, probes, inputs, a copy of its meta with the fn the base
    class's check accepts and the remapped phase_of. THE MODEL SET meta["fn"]
    ON THE MEMOISED BUILD FOR THE LENGTH OF __init__; the harness says "A Build
    is never mutated by a check" (build_of), so the build is never touched
    here and snapshot() shows it equal before and after;
  * the data frozen are the sources of integer instructions, compares and
    SELECT conditions before V; the pow family sets no meta["data"]: the
    exponential's magic-number sum feeds integer instructions (the table's
    index, k), which freezes it (the model measured exactly this);
  * the tree's pow Build has no instruction labels (the model's "log-sum",
    "product", ... are m3pow.py's own); labels_of() finds the logarithm's sum
    as the instructions of the phase "recon" that V's logarithm words Lh and
    Ll read, which is the model's "log-sum" (16 instructions at every format).

THE LEGS of the check `budget` (check_budget_pow), each a finding that begins
with "budget:" (mathlib_inv_budget's, over pow-family builds):

  bound       the budget's bound M_max + capacities under 1
  lane        no sampled lane's error past its bound by more than 0.1%
  residual    what first order leaves out is MEASURED and stated beside the
              bound, and the bound with it is held under 1; and a residual of
              exactly 0 on a region of main-path lanes is a finding (the tell
              of 3.6, item 4: a sweep that stopped short has none)
  reach       some instruction rounds and its observed contribution is not 0
  head        inv's head leg, which asks the sign carrier's phase: the pow
              family has no sign carrier at the head (V is signed by a SELECT
              between 0 and SIGN before the final rounding, in "final"), so
              the leg is asked on `edge`, where the head phase's capacity and
              the residual are not both zero on a sweep that reached it
  reference   the model's own digits at the model's own lanes
  attributes  V bit-identical across the five attributes on every lane
  analytic    (zone cells) the sum's measured capacity at most the analytic
              bound of the study's 3.2 (zonebound.py), computed from the
              build's own B1 and B2, and that bound plus the sampled rest
              under 1: a bound with no sample in it, which makes
              zone_bound_off red at any lane count

Each cell's FIGURE (cell_figure): the largest of the budget's bound, the bound
with its residual and the sampled worst of check_bound's lanes at the same
region, called which of them it is. A budget bounds its own sample (3.3) and a
sampled worst is a lower bound on the true worst: the figure is neither a
proof. A region with no main-path lane (hugey, int63) is NOT MEASURED, with its
lane count, and is outside every pass count.
"""

import functools
import math
import sys
import types
from fractions import Fraction
from pathlib import Path

import mpmath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_budget as B  # noqa: E402
import mathlib_inv_budget as IB  # noqa: E402
import mathlib_pow_harness as P  # noqa: E402

RND_NAMES = sf.RND_NAMES
INT_FUNCS = ml.POW_INT_NAMES
# the base class's fn check names the inverse functions: the proxy carries one
_BASE_FN = "atan2"

# Faults of the TOOL, for the tests (a table of this module's: never
# POW_PLANTS, which are the fragment's, nor InvAnalyzer's TOOL_PLANTS). A plant
# that could not act is refused by name.
POW_TOOL_PLANTS = {
    "fixed_grid_as_before_v": "the phase \"fixed-grid\" not remapped: the "
                              "fixed grid, which reads V_l with a CMPEQ, is "
                              "before V and V_l is frozen as data, so the "
                              "sweep stops at V_l (the study's 3.6, item 4)",
    "scale_unscaled": "the true value taken without 2^-k, so that V (in the "
                      "scaled domain) is compared with f: red where k is not "
                      "0",
    "inputs_swapped": "pow's and powr's two inputs read in each other's place "
                      "by the analysis, original run and twin alike, the true "
                      "value of (x, y) unchanged",
    "negation_as_data": "an IXOR with a sign carrier taken as integer data, "
                        "not as a negation: the sweep stops at V's sign",
    "capacities_dropped": "the capacities left out of the bound, which is M "
                          "alone, so the lanes' rounding errors pass it",
}
_INHERITED = ("inputs_swapped", "negation_as_data")     # InvAnalyzer's own


def _refuse(plant, build, why):
    return ValueError(f"tool plant {plant!r} does not apply to "
                      f"{build.meta['fn']} at {build.fmt.name}: {why}")


def snapshot(b):
    """What a check must leave of a Build as it found it: body, words,
    phase_of, meta, inputs and probes, as comparable values (meta's values by
    repr: Fractions, ints and names)."""
    return (tuple(b.body), tuple(b.words), tuple(b.phase_of),
            tuple(sorted((k, repr(v)) for k, v in b.meta.items())),
            tuple(b.inputs), tuple(sorted(b.probes.items())))


def _view(build, remap=True):
    """A light proxy of the build for InvAnalyzer: its fmt, body, words,
    probes and inputs, a COPY of its meta with the fn the base class's check
    accepts, and phase_of with "fixed-grid" read as "final" (unless remap is
    off, the plant). The build itself is not touched."""
    phases = [("final" if ph == "fixed-grid" else ph) if remap else ph
              for ph in build.phase_of]
    return types.SimpleNamespace(
        fmt=build.fmt, body=build.body, words=build.words,
        probes=build.probes, inputs=build.inputs,
        meta=dict(build.meta, fn=_BASE_FN), phase_of=phases)


class PowAnalyzer(IB.InvAnalyzer):
    """InvAnalyzer over a pow-family Build (the module docstring): built on a
    proxy of it, so that the memoised Build is not touched. `plant` is a key
    of POW_TOOL_PLANTS (the ones that are the base class's are passed to it)."""

    def __init__(self, build, plant=None):
        if plant is not None and plant not in POW_TOOL_PLANTS:
            raise ValueError(f"unknown tool plant {plant!r}: "
                             f"{', '.join(POW_TOOL_PLANTS)}")
        fn = build.meta.get("fn")
        if fn not in ml.POW_NAMES:
            raise ValueError(f"{fn!r} is not one of {', '.join(ml.POW_NAMES)}: "
                             f"this is the pow family's budget")
        if plant == "inputs_swapped" and len(build.inputs) < 2:
            raise _refuse(plant, build, "it has one input")
        if plant == "negation_as_data" and not any(
                op == sf.OP_IXOR for op, _r, _s in build.body):
            raise _refuse(plant, build, "it has no IXOR")
        super().__init__(_view(build, remap=plant != "fixed_grid_as_before_v"),
                         plant if plant in _INHERITED else None)
        self.plant = plant
        self.b = build                   # not the proxy
        self.phases = build.phase_of     # the build's own labels (by phase)


def labels_of(build):
    """{instruction index: label} for the instructions the report names: the
    logarithm's SUM ("log-sum": the instructions of the phase "recon" that the
    probes Lh and Ll read, the model's own label) and the bound's coefficient
    ("test": the instructions of the phase "head2" that the probe Bv reads and
    the product's words th0 and th do not)."""
    body, phases, pr = build.body, build.phase_of, build.probes

    def ancestors(roots):
        seen, stack = set(), [pr[r][1] for r in roots]
        while stack:
            i = stack.pop()
            if i in seen:
                continue
            seen.add(i)
            stack.extend(s[1] for s in body[i][2] if s[0] == "v")
        return seen
    out = {i: "log-sum" for i in ancestors(("Lh", "Ll"))
           if phases[i] == "recon"}
    return out


def log_sum_index(build):
    return sorted(labels_of(build))


# ---- the budget --------------------------------------------------------------------

class PowBudget(IB.InvBudget):
    """InvBudget over the pow family's lanes: for each instruction that ever
    rounds its largest observed contribution (`obs`) and capacity (`cap`), in
    Bv, the largest method error M and total error E, and the residual (what
    first order leaves out), on the lanes the main path answers: the
    harness's in_main (in_main_n), not taken by the screens, and with the
    probe `ex` clear (a lane the in-lane rule decides has no rounding to
    bound). `plant` names a fault of the tool (POW_TOOL_PLANTS)."""

    def __init__(self, build, plant=None):
        # not InvBudget.__init__: it makes the inverse functions' analyzer
        self.plant = plant
        self.an = PowAnalyzer(build, plant)
        n = len(self.an.body)
        self.obs, self.cap = [0.0] * n, [0.0] * n
        self.active = [False] * n
        self.Mmax = self.Emax = self.resid = 0.0
        self.lanes = self.skipped = 0
        self.worst_x = None
        self.ymax = 0.0
        self.worst_k = 0

    def in_main(self, lane):
        b = self.an.b
        fn, fmt = b.meta["fn"], b.fmt
        ok = (P.in_main_n if fn in INT_FUNCS else P.in_main)(fn, fmt, lane)
        if not ok:
            return False
        _r, _f, pr = b.run(P.lane_args(fn, lane), ("th0", "ex"))
        if P._screened(fmt, pr):
            return False
        return not pr["ex"] & ~fmt.sign_mask

    def add(self, lanes):
        an, fmt = self.an, self.an.fmt
        b = an.b
        fn = b.meta["fn"]
        for lane in lanes:
            if not self.in_main(lane):
                self.skipped += 1
                continue
            L = an.analyze(P.lane_args(fn, lane))
            k = int(ml._dec(fmt, L.vals[b.probes["nf"][1]])) // 8
            self.worst_k = max(self.worst_k, abs(k))
            with mpmath.workprec(an.prec):
                T = P.true_value(fn, fmt, lane)
                if self.plant != "scale_unscaled":
                    T = T * mpmath.mpf(2) ** (-k)
                Bv = L.Bv
                E = float(abs((L.V - T) / Bv))
                self.Mmax = max(self.Mmax, float(abs((L.Vex - T) / Bv)))
                if E > self.Emax:
                    self.Emax, self.worst_x = E, lane
                first = L.Vex - T
                for i, contrib, capi, d in an.contributions(L):
                    if d != 0:
                        self.active[i] = True
                    first += contrib
                    self.obs[i] = max(self.obs[i], abs(float(contrib / Bv)))
                    if self.plant != "capacities_dropped":
                        self.cap[i] = max(self.cap[i], float(capi / Bv))
                self.resid = max(self.resid,
                                 abs(float((L.V - T - first) / Bv)))
            self.ymax = max(self.ymax, lane_y(fmt, fn, lane))
            self.lanes += 1
        return self

    def summary(self):
        """InvBudget.summary() and, by label, the capacity of the logarithm's
        sum ("log-sum_cap") and the rest of the bound ("rest" = bound less
        it)."""
        s = super().summary()
        idx = set(log_sum_index(self.an.b))
        s["log_sum_cap"] = sum(self.cap[i] for i, a in enumerate(self.active)
                               if a and i in idx)
        s["rest"] = s["bound"] - s["log_sum_cap"]
        s["ymax"], s["kmax"] = self.ymax, self.worst_k
        return s


def lane_y(fmt, fn, lane):
    """|Y| of the lane, the logarithm's multiplier: |y| for pow and powr, |n|
    for pown and compound, 1/|n| for rootn."""
    if fn in ("pow", "powr"):
        return abs(float(ml._dec(fmt, lane[1])))
    n = abs(lane[1])
    return 1.0 / n if fn == "rootn" else float(n)


def budget_of(build, lanes, plant=None):
    """The summary of PowBudget(build).add(lanes), and the budget."""
    bud = PowBudget(build, plant).add(lanes)
    return bud.summary(), bud


# ---- the attributes ----------------------------------------------------------------

def v_words(build, lane):
    """The bits of V's words (Vh and Vl) on one lane."""
    _res, _fl, pr = build.run(P.lane_args(build.meta["fn"], lane),
                              ("Vh", "Vl"))
    return pr["Vh"], pr["Vl"]


def check_attributes(builds, lanes, label="random"):
    """[finding], (lanes, differing): attributes. `builds` {attribute: Build}
    of one function, format and n; V (its probes' words) bit-identical across
    them on every main-path lane of `lanes`, so that a budget under one
    attribute is every attribute's (the in-lane test and the final sum come
    after V). The first attribute's build is the reference."""
    rnds = sorted(builds)
    ref = builds[rnds[0]]
    fmt, fn = ref.fmt, ref.meta["fn"]
    probe = PowBudget.__new__(PowBudget)        # in_main only
    probe.an = types.SimpleNamespace(b=ref)
    n, bad = 0, []
    for lane in lanes:
        if not probe.in_main(lane):
            continue
        n += 1
        want = v_words(ref, lane)
        for r in rnds[1:]:
            if v_words(builds[r], lane) != want:
                bad.append((lane, r))
                break
    where = f"budget: {fn} {fmt.name} {label}"
    out = []
    if bad:
        lane, r = bad[0]
        out.append(f"{where}: V differs across the attributes on {len(bad)} "
                   f"of {n} lanes, first {P._hexes([lane])} ({RND_NAMES[r]} "
                   f"against {RND_NAMES[rnds[0]]}): a rounding comes before "
                   f"V, so the rne budget is not every attribute's")
    return out, (n, len(bad))


# ---- the analytic bound of the zone (the study's 3.2, zonebound.py) ---------------
#
# Where |x| (1 + x for compound) is in [1/2, X_b), M1's reduction takes k = -1
# and m' = 2|x|, so L = k + log2 m' cancels: X_b, the reduction's own boundary
# (241/256), is found by bisection on the probe kf, and so are the cells,
# C = 9 to 16 (c = C/16), by bisection on the probe cc. The logarithm's sum
# (the 16 instructions labels_of names) has five roundings, whose capacities
# are |dV/dv_i| ulp(v_i)/2 with dV/dL = V ln 2 Y and dL/dv = 1/ln 2 for the
# first two and 1 for the last three (natural-log units); compound's 1 + x low
# word adds four of the same scale. Bv/|V| = 2^-(p+G+shift) + |Y| (|L| B1 + B2)
# 2^shift, so the capacity is at most
#
#       ln 2 U / (BREL / |Y| + |L|_min B1' + B2')           (B' = B 2^shift)
#
# in Bv, whatever the lane's |L| above L_min, and at most ln 2 U / B2' whatever
# |Y|. U = sum c_i ulp(v_i)/2 is the sum of the rounding bounds in L, with each
# |v| at its largest on the zone. The arithmetic is zonebound.py's, taken at
# the format's p; the model's figures are COMPUTED at fp64 (0.171 Bv for the
# five, 0.231 Bv for compound's nine, 0.898 Bv at n = 1000 with B2 = 0).

def _half_ulp(p, vmax):
    """ulp(v)/2 for |v| <= vmax at p bits (0 for v = 0)."""
    if vmax <= 0:
        return 0.0
    return 2.0 ** (math.floor(math.log2(vmax)) - p)


def _il2h(p):
    with mpmath.workprec(200):
        return float(1 / mpmath.log(2))


def zone_rows(p, Fmax, Lj, rmin, rmax, c, ghmin, compound):
    """The sum's roundings (name, |v| max, dL/dv) for one cell, or for the
    zone with each magnitude at its largest (zonebound.py's rows_for)."""
    il2h, il2l = _il2h(p), 2.0 ** -p
    rabs = max(abs(rmin), abs(rmax))
    fe = _half_ulp(p, Fmax) if Lj else 0.0     # F = lph exactly where L_j = 0
    Ll = _half_ulp(p, Lj)
    nlpl = _half_ulp(p, rabs * 1.01) + 2.0 ** -p * rabs
    Fl1 = fe + Ll
    yv = 1 / (1 + min(rmin, 0.0))
    rl = 2.0 ** -(p + 1) * 2 * c if compound else 0.0
    corr = rl * yv
    Fl = Fl1 + nlpl + corr
    nge = _half_ulp(p, Fmax * il2h)
    ngl1 = Fmax * il2l + nge
    ngl = il2h * Fl + ngl1
    e = _half_ulp(p, 1 - ghmin) if ghmin < 0.5 else 0.0
    lo = e + ngl
    rows = [("a Fl1", Fl1, il2h), ("b Fl", Fl, il2h), ("c ngl1", ngl1, 1.0),
            ("d ngl", ngl, 1.0), ("e lo", lo, 1.0)]
    if compound:
        rows += [("p nlpl-corr", nlpl + corr, il2h),
                 ("w rl", rl, il2h * yv), ("w corr", corr, il2h),
                 ("w Newton", yv, 3 * il2h * rl)]
    return rows


def zone_U(p, rows):
    """U = sum c_i ulp(v_i)/2, in L."""
    return sum(c * _half_ulp(p, v) for _n, v, c in rows)


def _probe_of(b, lane_x, name):
    _r, _f, pr = b.run((lane_x,), (name,)) if b.meta["fn"] in INT_FUNCS \
        else b.run(lane_x, (name,))
    return float(ml._dec(b.fmt, pr[name]))


@functools.lru_cache(maxsize=None)
def zone_cells(fmt_name):
    """(X_b, [(C, X_a, X_z)]): the zone's top and the cells of the reduction
    over [1/2, X_b), by bisection on the probes kf and cc of pown's build at
    n = 1000 (zonebound.py's boundary() and cells(), with 200 points a scan
    where the model took 800: the narrowest cell, C = 16, is 0.0166 wide of
    0.44)."""
    fmt = P.BY_NAME[fmt_name]
    b = ml.build("pown", fmt, sf.RND_RNE, n=1000)

    def probe(X, name):
        return _probe_of(b, ml._enc(fmt, Fraction(X)), name)
    a, c = 0.9, 0.99
    assert probe(a, "kf") == -1 and probe(c, "kf") == 0
    for _ in range(60):
        m = (a + c) / 2
        if probe(m, "kf") == -1:
            a = m
        else:
            c = m
    Xb = a
    pts = [0.5 + (Xb - 0.5) * i / 200 for i in range(200)] + [Xb]
    cs = [round(16 * probe(X, "cc")) for X in pts]
    out, start = [], 0.5
    for i in range(1, len(pts)):
        if cs[i] != cs[i - 1]:
            lo, hi = pts[i - 1], pts[i]
            for _ in range(55):
                m = (lo + hi) / 2
                if round(16 * probe(m, "cc")) == cs[i - 1]:
                    lo = m
                else:
                    hi = m
            out.append((cs[i - 1], start, hi))
            start = hi
    out.append((cs[-1], start, Xb))
    return Xb, tuple(out)


def _bound_terms(meta, fmt, Y=None):
    """(BREL / |Y|, B1', B2') of the build, as floats: BREL = 2^-(p+G+shift)
    and B1', B2' the plan's coefficients times 2^shift, from the BUILD's meta
    (so that a plant or a doctored meta moves the bound). Y None is |Y| ->
    infinity (the BREL term gone)."""
    p, shift = fmt.prec, meta["shift"]
    brel = 2.0 ** (-(p + meta["G"]) + shift)
    b1 = float(meta["B1"] * Fraction(2) ** shift)
    b2 = float(meta["B2"] * Fraction(2) ** shift)
    return (0.0 if Y is None else brel / Y), b1, b2


def zone_analytic(meta, fmt, fn, Y=None):
    """The analytic bound, in Bv, of the logarithm's sum's capacity on the
    cancelling zone for a build with this meta (B1, B2, G, shift) and |Y| <=
    Y: ln 2 U / (BREL/Y + |L|_min B1' + B2'), over the whole zone for pow,
    pown and rootn (the five roundings) and the largest cell for compound (its
    nine). inf where the denominator is 0 (B1 = B2 = 0 and Y None)."""
    p = fmt.prec
    Xb, cells = zone_cells(fmt.name)
    compound = fn == "compound"
    by, b1, b2 = _bound_terms(meta, fmt, Y)
    ln2 = math.log(2)
    if not compound:
        rows = zone_rows(p, 0.64, math.log(16 / 9), -0.0625, 0.0625, 0.0, 0.0,
                         False)
        den = by + -math.log2(Xb) * b1 + b2
        return ln2 * zone_U(p, rows) / den if den > 0 else math.inf
    worst = 0.0
    for C, Xa, Xz in cells:
        Fmax = math.log(2 * Xz)
        Lj = math.log(16 / C)
        rmin, rmax = 2 * Xa * C / 16 - 1, 2 * Xz * C / 16 - 1
        ghmin = math.log(2 * Xa) * _il2h(p)
        rows = zone_rows(p, Fmax, Lj, rmin, rmax, C / 16, ghmin, True)
        den = by + -math.log2(Xz) * b1 + b2
        worst = max(worst, ln2 * zone_U(p, rows) / den if den > 0
                    else math.inf)
    return worst


def judge_analytic(s, meta, fmt, fn, where, Y):
    """[finding]: the analytic leg on a summary (budget_of's, with
    log_sum_cap and rest): the sum's measured capacity at most the analytic
    bound of the zone for this build's B1 and B2, and the analytic bound plus
    the sampled rest under 1. Split from the running so that a test can
    doctor B2 (the meta) and show it fail alone."""
    a = zone_analytic(meta, fmt, fn, Y)
    out = []
    if s["log_sum_cap"] > a * 1.000001:
        out.append(f"{where}: the logarithm's sum's measured capacity "
                   f"{s['log_sum_cap']:.4g} Bv is past the analytic bound "
                   f"{a:.4g}")
    if a + s["rest"] >= 1:
        out.append(f"{where}: the analytic bound of the logarithm's sum "
                   f"{a:.4g} Bv (for |Y| up to {Y:.5g}, B1 {meta['B1']}, "
                   f"B2 {meta['B2']}) and the sampled rest {s['rest']:.4g} "
                   f"come to {a + s['rest']:.4g}, not under 1")
    return out


# ---- the legs, as findings ----------------------------------------------------------

LEGS = IB.LEGS + ("analytic",)
_LEG_TEXT = IB._LEG_TEXT + (("analytic", "the analytic bound of the logarithm"),)


def leg_of(finding):
    """The leg of check `budget` a finding belongs to (LEGS), or None: told
    apart by their text (inv's, and the analytic leg's). A residual of exactly
    0 is the residual leg's."""
    if finding.startswith("budget:") and "residual is exactly 0" in finding:
        return "residual"
    for leg, text in _LEG_TEXT:
        if finding.startswith("budget:") and text in finding:
            return leg
    return None


def exact_v(s):
    """V is exactly f on every sampled lane: the measured error and the method
    error are 0 (a region whose lanes the near-one gate or an exact V
    answers)."""
    return bool(s["lanes"]) and s["Emax"] == 0 and s["Mmax"] == 0


def judge(s, where, expect=None, head=False, zero_resid=True):
    """[finding]: inv's judge() and the residual's second leg: a residual of
    exactly 0 with main-path lanes, rounding instructions and a bound above 0
    (the tell of 3.6, item 4: a sweep that stopped short has none)."""
    out = IB.judge(s, where, expect, head=head)
    if exact_v(s):
        # V is exactly f on every sampled lane (tinyy at fp256: |t| under
        # the gate, V = 1): the measured error is 0 and there is nothing for
        # a sweep to bound. A sweep that stopped short is not this: its lanes'
        # error is not 0 (the lane leg)
        out = [f for f in out if "reverse sweep reached no rounding" not in f]
        return out
    if zero_resid and s["lanes"] and s["resid"] == 0 and s["rounding"]:
        out.append(f"{where}: the residual is exactly 0 over {s['lanes']} "
                   f"lanes with {s['rounding']} rounding instructions: a "
                   f"sweep that stopped short (the study's 3.6, item 4)")
    return out


def check_budget_pow(b, lanes, label="random", plant=None, expect=None,
                     attrs=None, attr_lanes=None, head=None, zone=None):
    """[finding], summary: budget. The first-order budget of the build over
    the lanes (the main path's), judge()'s legs (the head leg on `edge`);
    `expect` the model's figures (reference); `attrs` {attribute: Build} for
    the attributes' leg, over every lane of `attr_lanes` or `lanes`; `zone`
    True (default: the region's name starts with "zone") the analytic leg.
    The summary is budget_of()'s, every figure in units of Bv."""
    before = snapshot(b)
    s, bud = budget_of(b, lanes, plant)
    assert snapshot(b) == before, "a check mutated a Build"
    fn, fmt = b.meta["fn"], b.fmt
    where = f"budget: {fn} {fmt.name} {RND_NAMES[b.rnd]} {label}"
    out = judge(s, where, expect,
                head=(label == "edge") if head is None else head)
    zone = label.startswith("zone") if zone is None else zone
    if zone and s["lanes"]:
        out += judge_analytic(s, b.meta, fmt, fn, where, s["ymax"])
    if attrs is not None:
        found, (n, bad) = check_attributes(
            attrs, lanes if attr_lanes is None else attr_lanes, label)
        out += found
        s["attr_lanes"], s["attr_differ"] = n, bad
    return out, s


# ---- the cells ------------------------------------------------------------------------

def cell_lanes(fmt, fn, region, count, seed=1):
    """The lanes of a cell: the harness's region (region_n for the n-keyed
    three), `count` of them."""
    if fn in INT_FUNCS:
        return P.region_n(fmt, fn, region, count, seed)
    return P.region(fmt, fn, region, count, seed)


def build_for(fn, fmt, rnd, n, plant=None):
    """The memoised Build of fn at fmt under rnd (and n)."""
    return P.build_n(fn, fmt, rnd, n, plant) if fn in INT_FUNCS \
        else P.build_of(fn, fmt, rnd, plant)


def by_n(fn, lanes):
    """[(n, lanes)] in order: the n-keyed functions' lanes grouped by their
    integer operand (one Build each), pow and powr's as one group (n None)."""
    if fn not in INT_FUNCS:
        return [(None, list(lanes))]
    return list(P._by_n(lanes).items())


def sampled_worst(build, lanes):
    """The largest |V - f| / Bv over the main-path lanes of `lanes` by the
    harness's bound_log2 (check_bound's): a LOWER BOUND on the true worst. 0.0
    where every lane is exact or none is on the main path."""
    fn, fmt = build.meta["fn"], build.fmt
    ok = P.in_main_n if fn in INT_FUNCS else P.in_main
    w = None
    for lane in lanes:
        if not ok(fn, fmt, lane):
            continue
        _r, _f, pr = build.run(P.lane_args(fn, lane), ("th0",))
        if P._screened(fmt, pr):
            continue
        r = P.bound_log2(build, lane)
        if r is not None and (w is None or r > w):
            w = r
    return 0.0 if w is None else 2.0 ** w


def cell_figure(s, worst):
    """(figure, which): the largest of the budget's bound, the bound with its
    residual and the sampled worst, and which of the three it is. Each is a
    figure about the lanes it was taken on."""
    return IB.cell_figure(s, worst)


def run_cell(fmt, fn, region, count, seed=1, rnd=sf.RND_RNE, plant=None,
             tool_plant=None, expect=None, worst=False, attrs=0):
    """One cell of the study's 3.2 table: (findings, record). The record is
    {"status": "measured" | "NOT MEASURED", "lanes": the region's lanes,
    "main": main-path lanes (over the cell's groups), "groups": [(n, summary)],
    "bound", "resid", "worst" (the sampled worst, when asked), "figure",
    "which"}. A cell with no main-path lane is NOT MEASURED and has no finding
    here: its caller names it and keeps it out of its pass count. `attrs` is
    the number of lanes (the first of each group) the attributes' leg runs
    under all five attributes (0: not run). The groups are the n of the
    lanes (pown, rootn and compound: nlow and m1edge carry several), the cell's
    figure the largest group's."""
    lanes = cell_lanes(fmt, fn, region, count, seed)
    found, groups = [], []
    for n, ls in by_n(fn, lanes):
        b = build_for(fn, fmt, rnd, n, plant)
        eb = None
        if attrs:
            eb = {r: build_for(fn, fmt, r, n, plant)
                  for r in sf.RND_MODES if r != rnd}
            eb[rnd] = b
        label = region if n is None or len(by_n(fn, lanes)) == 1 \
            else f"{region} n = {n}"
        f, s = check_budget_pow(b, ls, label, tool_plant, expect, eb,
                                attr_lanes=ls[:attrs] if attrs else None)
        s["n"] = n
        if worst:
            s["worst_sampled"] = sampled_worst(b, ls)
        if s["lanes"]:
            found += f
        groups.append((n, s))
    main = sum(s["lanes"] for _n, s in groups)
    rec = {"lanes": len(lanes), "main": main, "groups": groups,
           "status": "measured" if main else "NOT MEASURED"}
    if main:
        top = max((g for g in groups if g[1]["lanes"]),
                  key=lambda g: g[1]["bound"])[1]
        rec["bound"], rec["resid"] = top["bound"], top["resid"]
        w = max((g[1].get("worst_sampled", 0.0) for g in groups), default=0.0)
        rec["worst"] = w if worst else None
        rec["figure"], rec["which"] = cell_figure(top, w)
    return found, rec


# ---- the model's own figures --------------------------------------------------------
#
# docs/studies/m3/budget.py (the model, which nothing in the tree imports) run
# APART, imported and unedited, at the tree's base 6eec2e3e (its builds are the
# tree's own: m3pow.py builds on mathlib's Build), on the model's own lanes
# (regions.py's region and region_n at seed 1 and the sizes of the study's
# desktop set: 120 lanes at fp64 and 40 above), rne, at the cells below, and
# its figures copied here to four significant digits:
#   (fmt, fn, region, plant): (lanes asked, main-path lanes, a digest of the
#   lane list, rounding instructions, M_max, capacities summed, bound,
#   residual), in units of Bv.
# The reference leg holds this tool to them. The digest is sha256 of the
# repr of the model's lane list, first 16 hex digits: the harness's region
# and region_n (ported, not copied) give the model's lanes at the same seed
# at every one of these cells (a scratch run, 19 of 19 digests equal), so the
# leg takes the tree's lanes and holds their digest to the model's: a change of
# the generator's order is a finding by name and not a silent move of the
# reference. The model's compound m1edge is not here: its budget builds ONE n
# (region_n's) and runs lanes of six, which is not a figure of any build.
MODEL_SEED = 1
MODEL_FIGURES = {
    ('fp64', 'pow', 'edge', None): (120, 120, '33e4efc49c760bc3', 147, 0.0009876, 0.01364, 0.01463, 2.096e-07),
    ('fp64', 'pow', 'zone', None): (120, 116, '22c1a7f77be9b9f0', 146, 0.005969, 0.1119, 0.1178, 1.806e-06),
    ('fp64', 'pow', 'edge', 'bound_tight'): (120, 120, '33e4efc49c760bc3', 143, 0.1691, 2.609, 2.778, 4.25e-05),
    ('fp64', 'powr', 'near1', None): (120, 117, '746b20afe07f90a5', 139, 0.0006463, 0.05666, 0.05731, 1.924e-06),
    ('fp64', 'powr', 'rhoedge', None): (120, 113, '706b04ee296ebeb6', 143, 0.005748, 0.11, 0.1158, 1.22e-05),
    ('fp64', 'pown', 'zone12000', None): (120, 119, '34eae7e74367f912', 143, 0.00597, 0.09081, 0.09678, 2.472e-07),
    ('fp64', 'rootn', 'int', None): (120, 120, '54a6a31540519f44', 147, 0.001784, 0.02741, 0.0292, 1.409e-05),
    ('fp64', 'compound', 'int1000', None): (120, 120, '13286f4abb40d13f', 174, 0.003505, 0.04257, 0.04607, 1.233e-05),
    ('fp64', 'compound', 'zone1000', None): (120, 120, '1a47300db749be17', 155, 0.01029, 0.1838, 0.194, 3.95e-06),
    ('fp64', 'compound', 'zone1000', 'zone_bound_off'): (120, 120, '1a47300db749be17', 154, 0.06436, 0.9504, 1.015, 4.655e-06),
    ('fp128', 'pow', 'rhoedge', None): (40, 40, '29f427f4c435840f', 181, 0.000939, 0.0004057, 0.001345, 1.649e-22),
    ('fp128', 'pow', 'rhoedge', 'log_short'): (40, 40, '29f427f4c435840f', 162, 64.92, 59.17, 124.1, 1.649e-22),
    ('fp128', 'powr', 'wide', None): (40, 40, '69c856759280b1ed', 187, 0.0005527, 7e-05, 0.0006227, 1.258e-22),
    ('fp128', 'compound', 'zone188000', None): (40, 40, '23c4966906ea49e5', 192, 0.002731, 0.0006391, 0.00337, 8.223e-23),
    ('fp128', 'rootn', 'int17', None): (40, 40, '4a5619eb79108d64', 186, 0.0001295, 3.921e-05, 0.0001687, 1.137e-22),
    ('fp256', 'pow', 'zone', None): (40, 40, '0f44ba5f58accc7f', 234, 0.003518, 0.0005305, 0.004048, 7.432e-60),
    ('fp256', 'powr', 'edge', None): (40, 40, '3e5cb46bbaa8de99', 235, 0.001705, 6.169e-05, 0.001767, 5.022e-60),
    ('fp256', 'pown', 'int', None): (40, 40, '7a062267cc246307', 235, 0.001183, 5.628e-05, 0.001239, 4.965e-60),
    ('fp256', 'compound', 'int', None): (40, 40, '388f604bf9121ff5', 245, 4.81e-06, 7.379e-06, 1.219e-05, 2.61e-60),
}


def model_cell(fmt_name, fn, region, plant=None):
    """(lanes asked, main-path lanes, digest, expect) of one reference cell:
    expect is the dict judge()'s reference leg takes."""
    n, main, digest, rounding, M, cap, bound, resid = MODEL_FIGURES[
        (fmt_name, fn, region, plant)]
    return n, main, digest, {"rounding": rounding, "Mmax": M, "S_cap": cap,
                             "bound": bound, "resid": resid}


def lanes_digest(lanes):
    """The digest MODEL_FIGURES holds of a lane list."""
    import hashlib
    return hashlib.sha256(repr(list(lanes)).encode()).hexdigest()[:16]


def check_reference(fmt, fn, region, plant=None, rnd=sf.RND_RNE):
    """[finding], summary: reference. The cell of MODEL_FIGURES at the tree's
    lanes: their digest equal to the model's, the main-path lane count and the
    figures (the rounding instructions, M, the capacities, the bound and the
    residual to four figures) equal to the model's."""
    n, main, digest, expect = model_cell(fmt.name, fn, region, plant)
    lanes = cell_lanes(fmt, fn, region, n, MODEL_SEED)
    where = f"budget: {fn} {fmt.name} {RND_NAMES[rnd]} {region}"
    out = []
    if lanes_digest(lanes) != digest:
        out.append(f"{where}: the reference lanes differ from the model's "
                   f"(digest {lanes_digest(lanes)}, the model's {digest}): "
                   f"differs from the model's figures at the model's lanes "
                   f"cannot be held")
    n_, = {g for g, _ in by_n(fn, lanes)} or {None}
    b = build_for(fn, fmt, rnd, n_, plant)
    s, _bud = budget_of(b, lanes)
    if s["lanes"] != main:
        out.append(f"{where}: {s['lanes']} main-path lanes, the model's "
                   f"{main}: differs from the model's figures at the "
                   f"model's lanes")
    out += IB.judge(s, where, expect, head=False)
    return [f for f in out if "differs from the model" in f], s
