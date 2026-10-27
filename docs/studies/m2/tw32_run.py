# M2X: the measurements of fp32's triple word at G = 40 (scratch; the
# study's section 2.7 and question 3). One driver, a mode each; every run's
# output is kept beside it as tw32_<mode>[-<detail>].out.txt. Run from this
# directory, where m2core.py puts the repository's python/ on the path.
#
#   python tw32_run.py costs                    instructions, words, parts
#   python tw32_run.py live                     values live, design and scheduled
#   python tw32_run.py live-search [N]          the phase map, searched
#   python tw32_run.py reduce [PLANT]           the reduction against exact rationals
#   python tw32_run.py pools model|seq|census   the pools on the model, on seq.py; census.py's families
#   python tw32_run.py budget FN MODE [N] [seed] [PLANT]   tw32_budget.py, one region
#   python tw32_run.py rate [PLANT]             the mark-rate law with the bound inflated
#   python tw32_run.py plant NAME               a plant, red in its named mode, beside the control

import sys
import time
import math
import random
from fractions import Fraction

import mpmath

import tw32
import tw32_budget
from m2core import (Frag, FORMATS, sf, dec, enc_exact, evaluate, ATTRS, RNE,
                    RTZ)
from m2const import pi_frac
from m2harness import pools, compare, tr
from m2measure import sample, in_main
from m2red import audit
from m2edges import edges
import redcheck
import census
from cft_golden import mathlib, routines

FMT = FORMATS["fp32"]
FNS = ("sin", "cos", "tan")
P_BITS = FMT.prec
G = tw32.G_TW

# The map of this file's phases onto mathlib.PHASE_ORDER's names, for
# mathlib.schedule_order (the scheduler ranks the instructions ready to emit
# by their phase's place in PHASE_ORDER). The reduction first and whole, S
# before C, the quotient and the final rounding after them: the design's own
# order, by the names the tree's scheduler knows. live-search below looks for
# a better one among 4,000 monotone maps and does not find one under 23.
PHASE_MAP = {
    "red-setup": "setup", "red-window": "setup", "red-products": "reduce",
    "red-coarse": "lowword", "red-mid": "lowword",
    "red-products-low": "lowword", "red-lower": "lowword",
    "red-triple": "lowword", "red-scale": "lowword", "red-small": "lowword",
    "z": "tail", "S-tail": "tail", "S-head2": "head", "S-head3": "head2",
    "C-tail": "head3", "C-head2": "Z", "C-head3": "lookup",
    "sincos": "recon", "select": "scale", "quotient": "scale",
    "final": "final", "classify": "classify", "special": "special",
}


def scheduled(f, phase_map=None):
    """(design-order Fragment, scheduled Fragment) of a built fragment."""
    pm = phase_map or PHASE_MAP
    frag = f.to_fragment()
    order = mathlib.schedule_order(frag, [pm[p] for p in f.phase_of])
    return frag, mathlib.permuted(frag, order)


def say(*a, **k):
    print(*a, **k, flush=True)


# ---- costs ---------------------------------------------------------------

PARTS = [
    ("setup", ("red-setup",)), ("window", ("red-window",)),
    ("products", ("red-products", "red-products-low")),
    ("coarse", ("red-coarse",)), ("mid", ("red-mid",)),
    ("lows", ("red-lower",)), ("triple word", ("red-triple",)),
    ("scale", ("red-scale",)), ("small", ("red-small",)),
]
HEADS = ("z", "S-tail", "S-head2", "S-head3", "C-tail", "C-head2", "C-head3")
REST = ("sincos", "select", "quotient", "final", "classify", "special")


def mode_costs():
    union_all = set()
    unions = {}
    for fn in FNS:
        words_fn = set()
        for rnd in ATTRS:
            f = tw32.build(FMT, rnd, fn)
            frag = f.to_fragment()
            inv = mathlib.invariants(frag, live_cap=None)
            fw = routines.flag_words(frag)
            words_fn |= set(f.words.values())
            union_all |= set(f.words.values())
            say(f"fp32 {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, "
                f"{len(f.words)} words, live {f.live_max()} (design order); "
                f"TwoSum {f.meta['two_sum']}, Fast2Sum {f.meta['fast_two_sum']}, "
                f"TwoProd {f.meta['two_prod']}; invariants (live_cap=None) "
                f"{inv if inv else 'hold'}; flag words (C4's walk) "
                f"{sorted(hex(w) for w in fw) if fw is not None else None}")
            if rnd == RNE:
                ph = f.by_phase()
                say(f"   by phase {ph}")
                say(f"   by opcode {dict(sorted(f.counts().items(), key=lambda kv: -kv[1]))}")
                m = f.meta
                say(f"   plan: b {m['b']} L {m['L']} bottom {m['bottom']} "
                    f"budget {m['budget']} (t known to 2^{m['budget']} absolute) "
                    f"bmid {m['bmid']}; words of 2/pi {m['K_words']} "
                    f"(Z {m['Z']} zero); pieces {m['pieces']}; "
                    f"S K3/K2/D {m['poly']['S']}, C {m['poly']['C']}; G {m['G']}")
                say(f"   static proofs held at build time: {len(m['proofs'])}")
                for nm in m["proofs"]:
                    say(f"      {nm}")
        unions[fn] = words_fn
    say(f"fp32 bank words, union over the five attributes: sin {len(unions['sin'])}, "
        f"cos {len(unions['cos'])}, tan {len(unions['tan'])}; all three {len(union_all)}")
    # the study's 2.2 table by part, and 2.7's three parts
    for fn in FNS:
        f = tw32.build(FMT, RNE, fn)
        ph = f.by_phase()
        say(f"\nfp32 {fn} rne by part (the study's 2.2 table, this build):")
        red = 0
        for nm, phs in PARTS:
            n = sum(ph.get(p_, 0) for p_ in phs)
            red += n
            say(f"   {nm:12s} {n:5d}")
        heads = sum(ph.get(p_, 0) for p_ in HEADS)
        rest = sum(ph.get(p_, 0) for p_ in REST)
        say(f"   the reduction {red}; z, tails and heads {heads} "
            f"(S: {sum(ph.get(p_, 0) for p_ in HEADS if p_.startswith('S'))}, "
            f"C: {sum(ph.get(p_, 0) for p_ in HEADS if p_.startswith('C'))}); "
            f"sin(r)/cos(r), select, quotient, final, classify, special {rest}; "
            f"total {red + heads + rest} = {len(f.body)}")
        say(f"   against 2.7's ESTIMATE (reduction about 320, heads about 490, "
            f"the rest about 120, sin about 930): reduction {red} ({red - 320:+d}), "
            f"heads {heads} ({heads - 490:+d}), rest {rest} ({rest - 120:+d}), "
            f"total {len(f.body)} ({len(f.body) - 930:+d} for sin; "
            f"{len(f.body) / 930:.3f} of the estimate; the decision's cap is 1,395)")
        detail = {p_: n for p_, n in ph.items()}
        say(f"   every phase: {detail}")


# ---- live ------------------------------------------------------------------

def mode_live():
    say("fp32 triple word, values live at once, design order and scheduled "
        "(mathlib.schedule_order with the PHASE_MAP of tw32_run.py, mathlib.permuted); "
        "dag_digest of the scheduled fragment against the design order's; "
        "routines.program on each (seq.py's 32 registers; 'no register for the harness' "
        "would refuse); mathlib.invariants at the tree's cap for fp32 "
        f"(LIVE_CAP {mathlib.LIVE_CAP['fp32']}) beside")
    worst = 0
    worst_d = 0
    ok_all = True
    for fn in FNS:
        for rnd in ATTRS:
            f = tw32.build(FMT, rnd, fn)
            frag, g = scheduled(f)
            same = mathlib.dag_digest(frag) == mathlib.dag_digest(g)
            res = []
            for nm, fr in (("design", frag), ("scheduled", g)):
                try:
                    prog, bank = routines.program(fr)
                    res.append(f"{nm}: program accepted ({len(bank)} bank words)")
                except AssertionError as e:
                    res.append(f"{nm}: program REFUSED ({e})")
                    ok_all = False
            inv = mathlib.invariants(g)
            say(f"fp32 {fn} {sf.RND_NAMES[rnd]}: design {frag.live_max()}, scheduled "
                f"{g.live_max()}; dag_digest equal {same}; {'; '.join(res)}; "
                f"invariants at the tree's default cap: {inv if inv else 'hold'}")
            ok_all = ok_all and same
            worst = max(worst, g.live_max())
            worst_d = max(worst_d, frag.live_max())
    say(f"most live over the 15: design order {worst_d}, scheduled {worst}; "
        f"all 15 accepted by routines.program with identical digests: {ok_all}")


def mode_live_search(n=4000, seed=1):
    seq = list(PHASE_MAP)
    names = list(mathlib.PHASE_ORDER)
    rng = random.Random(seed)
    frs = {}
    for fn in FNS:
        f = tw32.build(FMT, RNE, fn)
        frs[fn] = (f, f.to_fragment())
    base = 0
    for fn, (f, frag) in frs.items():
        order = mathlib.schedule_order(frag, [PHASE_MAP[p_] for p_ in f.phase_of])
        base = max(base, mathlib.permuted(frag, order).live_max())
    say(f"live-search: the script's PHASE_MAP keeps {base} live at most (sin, cos, tan, rne); "
        f"{n} monotone maps of the {len(seq)} phases onto the {len(names)} names, seed {seed}")
    best, hist = (99, None), {}
    t0 = time.perf_counter()
    for it in range(n):
        cuts = sorted(rng.randint(0, len(names) - 1) for _ in seq)
        m = {ph: names[c] for ph, c in zip(seq, cuts)}
        worst = 0
        for fn, (f, frag) in frs.items():
            order = mathlib.schedule_order(frag, [m[p_] for p_ in f.phase_of])
            worst = max(worst, mathlib.permuted(frag, order).live_max())
        hist[worst] = hist.get(worst, 0) + 1
        if worst < best[0]:
            best = (worst, m)
    say(f"most live by map, how many maps: {dict(sorted(hist.items()))}; the best "
        f"{best[0]} (the first map to reach it: {best[1]}); {time.perf_counter() - t0:.0f}s")


# ---- reduce ----------------------------------------------------------------

def build_red(P, plant=None):
    f = Frag(FMT, RNE, "red-tw")
    mref = f.wx(Fraction(3, 2) * 2 ** (P_BITS - 1), "MAGIC")
    out = tw32.reduce_tw(f, ("in", "a"), P, mref, plant)
    f.result, f.flags = out["r0"], out["q"]
    f.out = out
    return f


def mode_reduce(plant=None, n=1000, seed=7):
    P = tw32.tw_plan(FMT)
    f = build_red(P, plant)
    say(f"fp32 triple word, the reduction alone{' PLANT ' + plant if plant else ''}: "
        f"b {P.b} L {P.L} bottom {P.bottom} budget {P.budget} bmid {P.bmid} "
        f"Z {P.Z} K {P.K} (words of 2/pi) Egate {P.Egate} Emax {P.Emax}; "
        f"{len(f.body)} instructions by phase {f.by_phase()}; "
        f"{len(f.meta.get('exact', ()))} instructions claimed exact; "
        f"{len(f.meta['proofs'])} static proofs held at build time")
    mpmath.mp.prec = 4 * P_BITS + 200
    B = Fraction(1, 2 ** (P_BITS + G))
    rho = pi_frac() / 4 * (1 + tw32.CUSHION)
    magic = enc_exact(FMT, Fraction(3, 2) * 2 ** (P_BITS - 1))
    totals = {"quadrant off": 0, "audit failures": 0, "arguments": 0}
    for label, xs in (("random, bucket edges, powers of two, the pools "
                       "(redcheck.args)", redcheck.args(FMT, P, n, seed)),
                      ("the products' binade edges (m2edges.edges)", edges(FMT, P)),
                      ("x within 3 ulps of (k + 1/2) pi/2, where |r| is next to pi/4 "
                       "and the cushion acts (m2measure.sample edge, seed 31, 2,000)",
                       [x for x in sample(FMT, "edge", 2000, 31) if in_main(FMT, "sin", x)])):
        t0 = time.perf_counter()
        worst, wx, bad_q, bad_audit, cnt, maxex = -1e9, None, 0, 0, 0, -1.0
        firsts = []
        for xa in xs:
            _r, _q, pr = evaluate(f, xa, want=["r0", "r1", "r2", "q"])
            rm = dec(FMT, pr["r0"]) + dec(FMT, pr["r1"]) + dec(FMT, pr["r2"])
            nq = (pr["q"] - magic) % 4
            rt = redcheck.exact_ref(FMT, xa, nq)
            if abs(rt) > rho:
                bad_q += 1
                if bad_q <= 5:
                    firsts.append(f"QUADRANT off: {hex(xa)} n {nq} |r| {float(abs(rt)):.9f}")
                continue
            maxex = max(maxex, float(abs(rt) / (pi_frac() / 4) - 1))
            err = abs(rm - rt) / abs(rt) / B
            lg = float(mpmath.log(mpmath.mpf(err.numerator) / err.denominator, 2)) if err else -999
            if lg > worst:
                worst, wx = lg, xa
            a = audit(f, xa)
            if a:
                bad_audit += 1
                if bad_audit <= 5:
                    firsts.append(f"AUDIT failed: {hex(xa)} {a[:3]}")
            cnt += 1
        for line in firsts:
            say("  " + line)
        say(f"  {label}: {cnt} arguments (of {len(xs)}): r's largest relative error "
            f"2^{worst:.2f} of 2^-(p+G) = 2^-{P_BITS + G} at {hex(wx) if wx else None}; "
            f"quadrant off (|r| past pi/4 (1 + 2^-16) in the model's own quadrant) {bad_q}; "
            f"audit failures {bad_audit}; largest |r|/(pi/4) - 1 seen {maxex:.3e}; "
            f"{time.perf_counter() - t0:.0f}s")
        totals["quadrant off"] += bad_q
        totals["audit failures"] += bad_audit
        totals["arguments"] += cnt
    say(f"TOTAL {totals['arguments']} arguments: quadrant off {totals['quadrant off']}, "
        f"audit failures {totals['audit failures']}")
    return totals


# ---- pools -----------------------------------------------------------------

def marks_listing(f, fn, xs, rnd):
    out = []
    for xa in xs:
        bits, fw, _ = evaluate(f, xa)
        if fw & 0x80:
            gb, gf = tr.compute(FMT, fn, xa, 0, rnd)
            out.append((hex(xa), hex(bits), fw, bits == gb and (fw & 0x1F) == gf))
    return out


def run_family(label, xs, fns=FNS):
    t0 = time.perf_counter()
    say(f"fp32 triple word {label}: {len(xs)} arguments")
    tot = {"lanes": 0, "marked": 0, "right": 0, "wrong": 0}
    for fn in fns:
        for rnd in ATTRS:
            f = tw32.build(FMT, rnd, fn)
            st = compare(f, fn, xs, rnd)
            say(f"  {fn} {sf.RND_NAMES[rnd]}: {len(f.body)} instructions, {len(f.words)} words, "
                f"live {f.live_max()}: {st['n']} lanes, marked {st['marked']} "
                f"(guess right {st['marked_right']}), wrong {len(st['wrong'])}, flag words "
                f"{sorted(hex(w) for w in st['words'])}; {time.perf_counter() - t0:.0f}s")
            for wr in st["wrong"][:6]:
                say("     WRONG", wr)
            for (a, b_, fw, ok) in marks_listing(f, fn, xs, rnd):
                say(f"     mark: argument {a}, its guess {b_} flags {fw:#04x}, guess "
                    f"{'right' if ok else 'WRONG'}")
            tot["lanes"] += st["n"]
            tot["marked"] += st["marked"]
            tot["right"] += st["marked_right"]
            tot["wrong"] += len(st["wrong"])
    say(f"TOTAL {label}: {tot['lanes']} lanes, marked {tot['marked']} "
        f"(guess right {tot['right']}), wrong unmarked {tot['wrong']}")
    return tot


def mode_pools(part):
    if part == "model":
        xs = pools(FMT)
        run_family("pools on the model (m2harness.pools)", xs)
    elif part == "seq":
        xs = pools(FMT)
        t0 = time.perf_counter()
        say(f"fp32 triple word, the pools as the SCHEDULED fragment on seq.py "
            f"(routines.run, as onseq.py): {len(xs)} arguments")
        tot = {"lanes": 0, "diff_model": 0, "mism": 0, "marked": 0, "right": 0}
        for fn in FNS:
            for rnd in ATTRS:
                f = tw32.build(FMT, rnd, fn)
                frag, g = scheduled(f)
                outs, words = routines.run(g, xs)
                diff_model = mism = marked = right = 0
                lst = []
                for xa, ob, ow in zip(xs, outs, words):
                    mb, mw, _ = evaluate(f, xa)
                    if (ob, ow) != (mb, mw):
                        diff_model += 1
                    gb, gf = tr.compute(FMT, fn, xa, 0, rnd)
                    if ow & 0x80:
                        marked += 1
                        ok = ob == gb and (ow & 0x1F) == gf
                        right += ok
                        lst.append((hex(xa), hex(ob), ow, ok))
                    elif (ob, ow) != (gb, gf):
                        mism += 1
                say(f"  {fn} {sf.RND_NAMES[rnd]}: {len(xs)} lanes on seq.py, {len(g.body)} "
                    f"instructions, scheduled live {g.live_max()}: differ from the model "
                    f"{diff_model}, from transcend.py (unmarked) {mism}, marked {marked} "
                    f"(guess right {right}); {time.perf_counter() - t0:.0f}s")
                for (a, b_, fw, ok) in lst:
                    say(f"     mark: argument {a}, its guess {b_} flags {fw:#04x}, guess "
                        f"{'right' if ok else 'WRONG'}")
                tot["lanes"] += len(xs)
                tot["diff_model"] += diff_model
                tot["mism"] += mism
                tot["marked"] += marked
                tot["right"] += right
        say(f"TOTAL on seq.py: {tot['lanes']} lanes, differ from the model {tot['diff_model']}, "
            f"wrong unmarked {tot['mism']}, marked {tot['marked']} (guess right {tot['right']})")
    elif part == "census":
        p = FMT.prec
        # the study's own tiny family at fp32 (E0 from its G = 18 design, so
        # the arguments are census.fp32-tiny.out.txt's 144), and the near family
        e0 = (p + 18) // 4 - 4
        run_family(f"census tiny family (census.tiny_family, E0 = {e0}, as the double "
                   f"word's run)", census.tiny_family(FMT, e0))
        run_family("census near family (census.near_family)", census.near_family(FMT))
        e1 = (p + G) // 4 - 4
        run_family(f"census tiny family at this design's own start (E0 = (p+G)//4 - 4 = {e1})",
                   census.tiny_family(FMT, e1))
    else:
        raise SystemExit("pools model|seq|census")


# ---- rate ------------------------------------------------------------------

def rate_cells(plant=None, N=2000, seed=3, Gp=6, fns=FNS, rnds=(RNE, RTZ), quiet=False):
    xs = sample(FMT, "random", N, seed)
    t0 = time.perf_counter()
    cells = []
    for fn in fns:
        main_xs = [x for x in xs if in_main(FMT, fn, x)]
        for rnd in rnds:
            f = tw32.build(FMT, rnd, fn, bound_shift=G - Gp, plant=plant)
            k = right = wrong = 0
            exp_sum = var_sum = 0.0
            for xa in main_xs:
                bits, fw, pr = evaluate(f, xa, want=["Vh"])
                v = abs(dec(FMT, pr["Vh"]))
                sig = 2 * math.frexp(float(v))[0]
                pi_ = min(1.0, 2.0 ** -Gp * sig)
                exp_sum += pi_
                var_sum += pi_ * (1 - pi_)
                gb, gf = tr.compute(FMT, fn, xa, 0, rnd)
                if fw & 0x80:
                    k += 1
                    if bits == gb and (fw & 0x1F) == gf:
                        right += 1
                elif (bits, fw) != (gb, gf):
                    wrong += 1
            n = len(main_xs)
            z = (k - exp_sum) / math.sqrt(var_sum)
            cells.append(dict(fn=fn, rnd=rnd, n=n, k=k, right=right, wrong=wrong,
                              exp=exp_sum, z=z, meansig=exp_sum * 2 ** Gp / n))
            if not quiet:
                say(f"fp32 {fn} {sf.RND_NAMES[rnd]} G'={Gp} seed {seed}: {n} lanes, marked {k} "
                    f"= {100 * k / n:.2f}%; each lane's own 2^-G' sig(V) sums to {exp_sum:.1f} = "
                    f"{100 * exp_sum / n:.2f}% ({z:+.1f} sigma); guesses right {right} of {k}; "
                    f"wrong unmarked {wrong}; mean sig(V) {exp_sum * 2 ** Gp / n:.4f}; "
                    f"{time.perf_counter() - t0:.0f}s")
    return cells


def mode_rate(plant=None):
    say(f"fp32 triple word, the mark-rate law (rate.py's, bound_shift = G - 6 = {G - 6}): 2,000 "
        f"random arguments, seed 3, rne and rtz{', PLANT ' + plant if plant else ''}")
    cells = rate_cells(plant)
    bad = [c for c in cells if abs(c["z"]) > 4 or c["wrong"] or c["right"] != c["k"]]
    say(f"CELLS: {len(cells)}; red (past 4 sigma of its own prediction, a wrong unmarked lane, "
        f"or a wrong guess): {len(bad)} {[(c['fn'], sf.RND_NAMES[c['rnd']], round(c['z'], 1)) for c in bad]}")
    say(f"the largest |z| {max(abs(c['z']) for c in cells):.2f} sigma; marked in all "
        f"{sum(c['k'] for c in cells)}, guesses right {sum(c['right'] for c in cells)}, "
        f"wrong unmarked {sum(c['wrong'] for c in cells)}")
    if not plant:
        for fn in FNS:
            cs = [c for c in cells if c["fn"] == fn]
            ms = sum(c["exp"] for c in cs) * 2 ** 6 / sum(c["n"] for c in cs)
            say(f"{fn}: mean sig(V) over its {sum(c['n'] for c in cs)} lanes {ms:.4f}; "
                f"COMPUTED rate at G = {G}: mean sig(V) x 2^-{G} = {ms * 2.0 ** -G:.3e} a call "
                f"= 2^{math.log2(ms) - G:.2f}, about one in {2.0 ** G / ms:.3e}")
    return cells


# ---- plants ----------------------------------------------------------------

def mode_plant(name):
    assert name in tw32.PLANTS, name
    if name == "carry-dropped":
        say("PLANT carry-dropped, named mode: reduce (the audit of every instruction "
            "the reduction calls exact). Control first.")
        c = mode_reduce(None, n=300)
        say("--- the plant ---")
        p = mode_reduce("carry-dropped", n=300)
        red = p["audit failures"] > 0
        say(f"RESULT: control audit failures {c['audit failures']} (green: {c['audit failures'] == 0}); "
            f"plant audit failures {p['audit failures']} -> {'RED' if red else 'NOT RED'}")
    elif name == "r2-dropped":
        say("PLANT r2-dropped, named mode: budget (sin, edge, 300 lanes, seed 21) and, "
            "beside it, pools (sin rne). Control first.")
        xs = sample(FMT, "edge", 300, 21)
        res = {}
        for label, pl in (("control", None), ("plant", "r2-dropped")):
            def bf(fm, rnd, fnn, pl=pl):
                return tw32.build(fm, rnd, fnn, plant=pl)
            b = tw32_budget.budget(bf, FMT, "sin", xs, top=3)
            res[label] = b
            say(f"  {label}: {b['lanes']} lanes; max |E|/Bv {b['Emax']:.4g}; max |M|/Bv "
                f"{b['Mmax']:.4g}; THE BUDGET'S BOUND {b['bound']:.4g} Bv")
        pxs = pools(FMT)
        for label, pl in (("control", None), ("plant", "r2-dropped")):
            f = tw32.build(FMT, RNE, "sin", plant=pl)
            st = compare(f, "sin", pxs, RNE)
            say(f"  pools sin rne, {label}: {st['n']} lanes, marked {st['marked']}, "
                f"wrong unmarked {len(st['wrong'])}")
        red = res["plant"]["bound"] > 1.0 or res["plant"]["Emax"] > 1.0
        say(f"RESULT: control bound {res['control']['bound']:.4g} Bv (green: "
            f"{res['control']['bound'] < 1.0}); plant bound {res['plant']['bound']:.4g} Bv, "
            f"largest error {res['plant']['Emax']:.4g} Bv -> {'RED' if red else 'NOT RED'} in budget")
    else:
        say("PLANT mark-silenced, named mode: rate (cos, rne and rtz, 2,000 arguments, seed 3). "
            "Control first.")
        c = rate_cells(None, fns=("cos",))
        say("--- the plant ---")
        p = rate_cells("mark-silenced", fns=("cos",))
        red = any(abs(x["z"]) > 4 for x in p)
        say(f"RESULT: control |z| {[round(abs(x['z']), 1) for x in c]} (green: "
            f"{all(abs(x['z']) <= 4 for x in c)}); plant marked {[x['k'] for x in p]} against "
            f"predicted {[round(x['exp'], 1) for x in p]}, |z| {[round(abs(x['z']), 1) for x in p]} "
            f"-> {'RED' if red else 'NOT RED'} in rate")


# ---- main --------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__ if __doc__ else "modes")
    mode = sys.argv[1]
    arg = sys.argv[2:]
    t0 = time.perf_counter()
    if mode == "costs":
        mode_costs()
    elif mode == "live":
        mode_live()
    elif mode == "live-search":
        mode_live_search(int(arg[0]) if arg else 4000)
    elif mode == "reduce":
        mode_reduce(arg[0] if arg else None)
    elif mode == "pools":
        mode_pools(arg[0] if arg else "model")
    elif mode == "budget":
        fn, region = arg[0], arg[1]
        N = arg[2] if len(arg) > 2 else "1500"
        seed = arg[3] if len(arg) > 3 else str({"edge": 21, "near": 22, "small": 23,
                                               "random": 24, "zero": 25}[region])
        plant = arg[4] if len(arg) > 4 else "-"
        tw32_budget.main(["fp32", fn, region, N, seed, "10", "-", plant])
    elif mode == "rate":
        mode_rate(arg[0] if arg else None)
    elif mode == "plant":
        mode_plant(arg[0])
    else:
        raise SystemExit(f"unknown mode {mode}")
    say(f"-- {mode} {' '.join(arg)}: {time.perf_counter() - t0:.0f}s")


if __name__ == "__main__":
    main()
