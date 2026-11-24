# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The mark-rate law of pow, powr, pown, rootn and compound (parcel M3G3): the
study's 3.4 (docs/studies/M3-pow.md), the model's rate.py (docs/studies/m3/,
which nothing in the tree imports) in the form of mathlib_inv_rate (M4G4's),
with each lane's OWN probability and the BERNOULLI statistic.

THE LAW. With the bound inflated (bound_shift = shift: Bv is 2^shift times its
own, every term of it) a lane is marked when [V - Bv, V + Bv] holds a boundary
of the attribute's rounding, with probability p = 2 Bv / s, s the boundaries'
spacing at R: ulp(R) under rtz, rdn and rup (the grid points), ulp(R)/2 under
rne and rmm (the midpoints, and the grid points the "may be exact" test adds).
At fp64 Bv is not 2^-(p+G) |V|: it carries the |t| and |Y k| terms (the plan's
B1 and B2), which `shift` multiplies too, so p is each lane's OWN, taken from
the build's probes R and Bv, not from a nominal 2^-G sig(V) (the tool plant
nominal_bound). The expectation is of the UNPLANTED build's bound: a planted
bound (bound_loose, bound_tight) or a silenced mark changes the count and not
the centre.

THE STATISTIC IS BERNOULLI. Marks are independent Bernoulli(p_i) trials: the
count's variance is sum p (1 - p), its exact two-sided tail the Poisson-
binomial dynamic programme of mathlib_harness (poisson_binomial_pmf, pmf_top,
RateSample's tails). The study's z values are the POISSON form, (obs - exp) /
sqrt(exp) with p capped at 1 (rate.py:56): right where p is small, wrong where
it is not, and the study's cells are not rare: 436 of 600 lanes marked at
fp64's G' = 8, a mean p of 0.73 (M3X's pow at fp32 was -12.1 where the Poisson
form said -3.6, with 1,191 of 2,000 lanes at p = 1). z here is (marks - sum p)
/ sqrt(sum p (1 - p)); the Poisson form is the tool plant poisson_variance.
rtz, rdn and rup mark the same lanes, rne and rmm the same: a cell's two
attributes are two independent statistics, not five.

THE REGIME. A lane whose interval is as long as the boundaries' spacing (2 Bv
/ s at least 1) holds a boundary and marks, whatever the law says of it: it is
AT THE CAP. A cell is judged only where no lane is at the cap: the inflation is
chosen by a rule (choose_shift): the largest shift at which the largest p is
under 1/2, and the expected marks at least MIN_MARKS (30) over the cell's
lanes; a cell that cannot reach 30 expected marks that way is NOT MEASURED and
says so. A cell run at a shift that puts lanes at the cap is printed as CAPPED,
its lanes at the cap counted apart and not part of any pass count; the cap leg
holds each of them to mark (INFERRED from the in-lane test, 3.1), unless ex or
tinyt (decided in the lane: they never mark) or a rule of the subnormal grid
clears it. Lanes with ex or tinyt set are out of the count, and counted.

THE LEGS of the check `rate`, each a finding that begins with "rate:":

  law          the exact two-sided tail of the count of marks under the
               lanes' own p, under alpha / statistics
  variance     the statistic's variance is sum p (1 - p) (to 1e-9)
  probability  every p in [0, 1]
  cap          every lane at the cap is marked
  wrong        every unmarked lane equals transcend.py in bits and flags
"""

import functools
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import mathlib as ml  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

import mathlib_harness as H  # noqa: E402
import mathlib_pow_budget as PB  # noqa: E402
import mathlib_pow_harness as P  # noqa: E402

INT_FUNCS = ml.POW_INT_NAMES
RATE_ALPHA = H.RATE_ALPHA
MAX_P = 0.5               # the rule: the largest p under 1/2
MIN_MARKS = 30            # the rule: about 30 expected marks at least
LEGS = ("law", "variance", "probability", "cap", "wrong")

# Faults of the TOOL, for the tests: check_rate(tool_plant=...).
RATE_TOOL_PLANTS = {
    "nominal_bound": "p taken from the nominal 2^-(p+G) |R| (the |t| and |Y k| "
                     "terms of Bv ignored): red at fp64, where they are most "
                     "of Bv",
    "poisson_variance": "the statistic's variance the Poisson form's (the "
                        "mean, the model's rate.py): red in the variance leg "
                        "wherever sum p^2 is not negligible; the z it gives "
                        "is off by sqrt(1 - mean p), -0.95 for -1.67 at the "
                        "study's fp64 cell",
    "cap_dropped": "p not capped at 1: red where 2 Bv / s is over 1",
}


class Law(H.RateSample):
    """H.RateSample's law (mean, sigma, pmf, tails, p_value) for lanes given
    by their probabilities."""

    def __init__(self, ps):
        self.p = list(ps)
        self.n = len(self.p)
        self.mean = math.fsum(self.p)
        self.var = math.fsum(q * (1.0 - q) for q in self.p)
        self.sigma = math.sqrt(self.var)
        self._pmf = None


@functools.lru_cache(maxsize=None)
def _build(fn, fmt, rnd, n, shift, plant=None):
    """The Build of fn at fmt under rnd with the bound inflated 2^shift
    (memoised: a Build is never mutated by a check)."""
    return ml.build(fn, fmt, rnd, n=n, bound_shift=shift, plant=plant)


def cell_n(fn, region):
    """The integer operand of a region of pown, rootn or compound (None for
    pow and powr)."""
    return P.region_n_of(region) if fn in INT_FUNCS else None


def main_lanes(fmt, fn, region, count, seed):
    """[lane]: the harness's lanes of the region that the main path answers
    (in_main, in_main_n) and the screens do not take, in order."""
    lanes = (P.region_n if fn in INT_FUNCS else P.region)(fmt, fn, region,
                                                          count, seed)
    ok = P.in_main_n if fn in INT_FUNCS else P.in_main
    b = _build(fn, fmt, sf.RND_RNE, cell_n(fn, region), 0)
    out = []
    for lane in lanes:
        if not ok(fn, fmt, lane):
            continue
        _r, _f, pr = b.run(P.lane_args(fn, lane), ("th0",))
        if not P._screened(fmt, pr):
            out.append(lane)
    return out


def lane_p(fmt, rnd, pr, nominal=False, meta=None, shift=0):
    """2 Bv / s of one lane from its probes (R, Bv): s = ulp(R) under rtz,
    rdn and rup and ulp(R)/2 under rne and rmm; None where R is not finite or
    is 0 or Bv is 0. `nominal` (the tool plant) takes Bv = 2^-(p+G+shift)
    |R| instead of the build's."""
    p = fmt.prec
    try:
        Rq = abs(float(ml._dec(fmt, pr["R"])))
        Bvq = float(ml._dec(fmt, pr["Bv"]))
    except ValueError:
        return None
    if not Rq or not Bvq:
        return None
    if nominal:
        Bvq = Rq * 2.0 ** (-(p + meta["G"]) + shift)
    ulp = 2.0 ** (math.floor(math.log2(Rq)) - p + 1)
    s = ulp / 2 if rnd in H.RATE_NEAREST else ulp
    return 2 * Bvq / s


def probabilities(fmt, fn, lanes, rnd, n, shift):
    """[(lane, p_raw or None, excluded, result, flag word)] from the UNPLANTED
    build at `shift`: p_raw = 2 Bv / s uncapped; excluded is "ex", "tinyt"
    (decided in the lane: never marks) or None."""
    b = _build(fn, fmt, rnd, n, shift)
    sm = fmt.sign_mask
    out = []
    for lane in lanes:
        res, fl, pr = b.run(P.lane_args(fn, lane),
                            ("R", "Bv", "ex", "tinyt"))
        why = "ex" if pr["ex"] & ~sm else "tinyt" if pr["tinyt"] & ~sm             else None
        out.append((lane, lane_p(fmt, rnd, pr), why, res, fl))
    return out


def choose_shift(fmt, fn, lanes, rnd, n, max_p=MAX_P, min_marks=MIN_MARKS):
    """(shift, expected, ok): the rule. p scales as 2^shift (every term of Bv
    does), so from the build at shift 0: the largest shift at which the
    largest p of the cell's usable lanes is under `max_p`, and the expected
    marks (sum of p) there; ok is False where they are under `min_marks`
    (the cell is NOT MEASURED at this lane count). Lanes with ex or tinyt set
    are not usable."""
    ps = [p for _l, p, why, _r, _f in probabilities(fmt, fn, lanes, rnd, n, 0)
          if p is not None and why is None]
    if not ps:
        return 0, 0.0, False
    shift = math.floor(math.log2(max_p / max(ps)))
    while max(ps) * 2.0 ** shift >= max_p:
        shift -= 1
    exp = sum(ps) * 2.0 ** shift
    return shift, exp, exp >= min_marks


def run_cell(fmt, fn, region, count, seed, rnd, shift=None, plant=None,
             statistics=1, alpha=RATE_ALPHA, tool_plant=None, lanes=None,
             min_marks=MIN_MARKS):
    """[finding], stats: rate, one cell. `lanes` default the harness's main
    lanes of the region (`count` asked at `seed`); `shift` None is the rule's
    (choose_shift, per attribute class); `plant` is a fault of the fragment
    (POW_PLANTS, which acts on the count and not on the centre);
    `tool_plant` one of RATE_TOOL_PLANTS. stats: {status: "judged" | "CAPPED"
    | "NOT MEASURED", lanes, used, excluded, capped, capped_unmarked, pmax,
    expected, marks, var, sigma, z, z_poisson, p_value, level, wrong,
    guess_wrong, shift, statistics}."""
    if tool_plant is not None and tool_plant not in RATE_TOOL_PLANTS:
        raise ValueError(f"unknown tool plant {tool_plant!r}: "
                         f"{', '.join(RATE_TOOL_PLANTS)}")
    n = cell_n(fn, region)
    if lanes is None:
        lanes = main_lanes(fmt, fn, region, count, seed)
    st = {"lanes": len(lanes), "shift": shift, "statistics": statistics,
          "rnd": rnd}
    if shift is None:
        shift, exp0, ok = choose_shift(fmt, fn, lanes, rnd, n,
                                       min_marks=min_marks)
        st.update(shift=shift, rule=True)
        if not ok:
            st.update(status="NOT MEASURED", expected=exp0)
            return [], st
    probs = probabilities(fmt, fn, lanes, rnd, n, shift)
    b = _build(fn, fmt, rnd, n, shift, plant)
    meta = _build(fn, fmt, rnd, n, shift).meta
    used, excluded, capped, ps, mk = [], [], [], [], []
    marks_of = {}
    wrong, gwrong = [], []
    sm = fmt.sign_mask
    for (lane, praw, why, res, fl) in probs:
        if plant is not None:       # the count is the planted build's
            res, fl, _pr = b.run(P.lane_args(fn, lane), ())
        marked = bool(fl & ml.MARK)
        marks_of[lane] = marked
        gb, gf = P.golden(fmt, rnd, lane, fn)
        if marked:
            if (res, fl & 0x1F) != (gb, gf):
                gwrong.append(lane)
        elif (res, fl) != (gb, gf):
            wrong.append(lane)
        if why is not None or praw is None:
            excluded.append((lane, why or "R"))
            continue
        if tool_plant == "nominal_bound":
            _r, _f, pr = _build(fn, fmt, rnd, n, shift).run(
                P.lane_args(fn, lane), ("R", "Bv"))
            praw = lane_p(fmt, rnd, pr, nominal=True, meta=meta, shift=shift)
        if praw >= 1.0 and tool_plant != "cap_dropped":
            capped.append(lane)
            continue
        used.append(lane)
        ps.append(praw if tool_plant == "cap_dropped" else min(1.0, praw))
        mk.append(marked)
    return judge_cell(fmt, fn, rnd, region, st, ps, mk, capped, marks_of,
                      excluded, wrong, gwrong, probs, statistics, alpha,
                      tool_plant)


def judge_cell(fmt, fn, rnd, region, st, ps, mk, capped, marks_of, excluded,
               wrong, gwrong, probs, statistics, alpha, tool_plant=None):
    """[finding], stats: the legs on the cell's measured lists. Split from
    the running so that a test can doctor one list (a count, a lane's mark, a
    probability, the variance) and show its leg fail alone."""
    where = (f"rate: {fn} {fmt.name} {sf.RND_NAMES[rnd]} {region} "
             f"(shift {st['shift']})")
    law = Law([min(1.0, q) for q in ps])
    marks = sum(mk)
    mean = math.fsum(ps)
    var = math.fsum(min(1.0, q) * (1.0 - min(1.0, q)) for q in ps)
    var_used = mean if tool_plant == "poisson_variance" else var
    sigma = math.sqrt(var_used) if var_used > 0 else 0.0
    z = (marks - mean) / sigma if sigma > 0 else 0.0
    z_poisson = (marks - mean) / math.sqrt(mean) if mean > 0 else 0.0
    level = H.rate_level(statistics, alpha)
    lo, hi = law.tails(marks) if law.n else (1.0, 1.0)
    pval = min(1.0, 2.0 * min(lo, hi))
    capped_unmarked = [lane for lane in capped if not marks_of[lane]]
    st.update(used=len(ps), excluded=len(excluded), capped=len(capped),
              capped_unmarked=capped_unmarked, pmax=max(ps) if ps else 0.0,
              expected=mean, marks=marks, var=var_used, sigma=sigma, z=z,
              z_poisson=z_poisson, p_value=pval, level=level,
              wrong=len(wrong), guess_wrong=len(gwrong),
              status="CAPPED" if capped else "judged",
              ex_n=sum(1 for _l, w in excluded if w == "ex"),
              tinyt_n=sum(1 for _l, w in excluded if w == "tinyt"))
    out = []
    if any(q > 1.0 for q in ps) or any(q < 0.0 for q in ps):
        out.append(f"{where}: {sum(1 for q in ps if q > 1.0)} lane "
                   f"probabilities are over 1 (the largest "
                   f"{max(ps):.3g}): p is capped at 1")
    if abs(var_used - var) > 1e-9 * max(1.0, var):
        out.append(f"{where}: the statistic's variance is {var_used:.6g}, not "
                   f"sum p (1 - p) = {var:.6g}: marks are Bernoulli, and the "
                   f"Poisson form (the mean) is wrong where p is not small")
    if capped_unmarked:
        out.append(f"{where}: {len(capped_unmarked)} of {len(capped)} lanes "
                   f"at the cap (2 Bv / s at least 1, so the interval holds a "
                   f"boundary) are not marked, first "
                   f"{P._hexes([capped_unmarked[0]])}")
    if wrong:
        out.append(f"{where}: {len(wrong)} unmarked lanes differ from "
                   f"transcend.{fn}, first {P._hexes([wrong[0]])}")
    if not capped and law.n and pval < level:
        out.append(f"{where}: {marks} of {len(ps)} lanes marked, "
                   f"{mean:.1f} expected (sigma {sigma:.2f}): {z:+.2f} sigma, "
                   f"an exact two-sided tail of {pval:.2g}, under the "
                   f"{level:.2g} of this run (alpha {alpha:g} over "
                   f"{statistics} statistics)")
    return out, st


def leg_of(finding):
    """The leg of check `rate` a finding belongs to (LEGS), or None."""
    for leg, text in (("probability", "probabilities are over 1"),
                      ("variance", "the statistic's variance"),
                      ("cap", "at the cap"),
                      ("wrong", "unmarked lanes differ"),
                      ("law", "exact two-sided tail")):
        if finding.startswith("rate:") and text in finding:
            return leg
    return None


def lanes_to_see(silenced, mean_p, level=RATE_ALPHA, lo=10, hi=1500):
    """The least number of lanes at which a build that silences the fraction
    `silenced` of its marks (the fragment mark_silenced is 1.0) is red to the
    law: lanes of probability `mean_p` each, the silenced count's EXPECTED
    value ((1 - silenced) N mean_p, rounded down) judged by the exact two-sided
    tail under the clean law (Binomial(N, mean_p)) and under `level`. A
    typical run: the sample's own count varies by its sigma, which this
    ignores."""
    def red(n):
        law = Law([mean_p] * n)
        c = int(math.floor((1.0 - silenced) * n * mean_p))
        lo_, hi_ = law.tails(c)
        return min(1.0, 2.0 * min(lo_, hi_)) < level
    if not red(hi):
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if red(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


# ---- the study's own cell, in both statistics -----------------------------------------

def model_cell(fmt, fn, region, count, seed, rnd, shift):
    """The model's rate.py on the harness's lanes of the region, as it counts:
    every lane (no main-path filter) with ex and tinyt clear and R and Bv
    nonzero and finite, p = min(1, 2 Bv / s), the count of marks of the
    build at `shift`. Returns {used, marks, expected, capped (lanes whose
    uncapped p is at least 1), p_one (lanes whose capped p is 1), pmax,
    z_poisson (the model's: (obs - exp) / sqrt(exp)), z_bernoulli ((obs - exp)
    / sqrt(sum p (1 - p)))}: the study's 3.4 figures, and the same cell under
    the statistic the marks obey."""
    n = cell_n(fn, region)
    lanes = (P.region_n if fn in INT_FUNCS else P.region)(fmt, fn, region,
                                                          count, seed)
    b = _build(fn, fmt, rnd, n, shift)
    sm = fmt.sign_mask
    ps, marks, capped = [], 0, 0
    for lane in lanes:
        _r, fl, pr = b.run(P.lane_args(fn, lane),
                           ("R", "Bv", "ex", "tinyt"))
        if pr["ex"] & ~sm or pr["tinyt"] & ~sm:
            continue
        praw = lane_p(fmt, rnd, pr)
        if praw is None:
            continue
        capped += praw >= 1.0
        ps.append(min(1.0, praw))
        marks += bool(fl & ml.MARK)
    exp = math.fsum(ps)
    var = math.fsum(q * (1.0 - q) for q in ps)
    return {"used": len(ps), "marks": marks, "expected": exp,
            "capped": capped, "p_one": sum(q == 1.0 for q in ps),
            "pmax": max(ps) if ps else 0.0,
            "z_poisson": (marks - exp) / math.sqrt(exp) if exp else 0.0,
            "z_bernoulli": (marks - exp) / math.sqrt(var) if var else 0.0}
