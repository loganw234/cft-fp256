# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""How well a certificate's two estimates indicate the errors they
estimate: every number of docs/studies/ACC-A-estimates.md, made again.

    python programs/estimates.py certified [--cases A,B] [--tau T]
    python programs/estimates.py sweep --tool host/cft-segrun[.exe]
                                       [--cases A,B] [--keep DIR]
    python programs/estimates.py all --tool host/cft-segrun[.exe]

A certificate (docs/CERTIFICATES.md, "Accuracy entries") can carry two
ESTIMATES: `step-halving`, the largest absolute difference over the
state's slots between the main run's final state and a half-step run's
(the bank's h-slots exactly halved, twice the segments), and `wider`,
the same against a run one format wider (constants, streams and start
exactly widened). The page says an estimate "indicates an error without
bounding it". This measures how well each one indicates, on every ODE
case of the golden corpus (certificates/MANIFEST), whose runs are also
the ones host/tests/segrun_check.py certifies.

THE THREE REFERENCES.
  R_k   programs/check.py's 300-digit arm (check.scheme_run: ode_step
        through _MpOps, the program's scheme with its roundings taken
        out) run from the certified start's exact values with the bank's
        h-slots exactly halved k times and 2^k times the steps, keeping
        the state at every boundary of the certified run. R_0 is the
        arm over the whole run: the ROUNDING REFERENCE of the main run,
        R_1 the half-step run's.
  R_K   the CONVERGED REFERENCE: the first K >= 3 at which, in every lane
        at every boundary, |R_K - R_(K-1)| <= TAU |R_0 - R_K| (maxima over
        the slots) and the last ratio of successive differences is
        within RATIO_BAND of 2^p. Its error is stated as u = |R_K -
        R_(K-1)| / (2^p - 1), and 2u is the bound every ratio's
        uncertainty is computed from. A case that reaches its cap
        (KCAP) first is named NOT CONVERGED and not scored.
  odefun  mpmath's own Taylor-series integrator, from the same exact
        start with the bank's parameter values, at 30 and 40 digits. It
        shares no code with the program, gen_odes.py or ode_step (the
        vector fields below are written again, in their textbook form).
        It is a cross-check of R_K, and the reference for the sweep's
        deepest levels only where the sweep shows it is the scheme's
        own limit (below).

THE LIMIT, AND THE TIME SHIFT. RK4's bank carries H6 = h/6 ROUNDED to the
format, and halving the bank halves that rounding exactly, so the scheme
at h/2^k converges to the solution of y' = (1 + delta) f(y), delta =
6 H6/H - 1: y((1 + delta) t), the ODE's solution at a SHIFTED time. That
limit is what the step-halving estimate estimates the distance to, and
R_K converges to it. odefun evaluates y at both times; the difference is
the shift, an error of the certified run that neither estimate can see:
the half-step run halves H6 exactly and the wider run widens it exactly.
Stormer-Verlet's bank has no rounded derived constant (delta = 0).

WHAT IS SCORED. `certified`, every lane of every ODE case with an
auxiliary run, at every boundary (a certificate states the last):
  - step-halving E (the page's function, cert.derive) against the method
    error M = |R_0 - R_K|, as E / M, beside Richardson's 1 - 2^-p;
  - E against the certified run's total error |F0 - R_K|;
  - wider W against the rounding error |F0 - R_0|, beside the wider run's
    own rounding |F2 - R_0|, which bounds |W - rounding|;
  - at fp256, the wider run's refusal: the golden audit handed an fp256
    certificate with a wider run attached must refuse it `aux-format`.
`sweep` follows lane 0 of each system as h shrinks: at level j,
cft-segrun certifies in a scratch directory a one-lane main run on the
bank halved j times, its half-step run and, at fp64, its wider run; the
golden audit accepts a sample of each; level 0 is checked bit for bit
against the corpus's lane 0, and each level's half-step run against the
next level's main run. The rounding reference at level j is R_j. The
method error at level j is measured against R_L, lane 0's deepest level
computed, where 2u_L is at most RESOLVE_REF of it (R_L's own error
biases the ratio by no more), and otherwise against odefun where its
stated agreement with the scheme's limit is at most RESOLVE_OD of it;
otherwise it is printed unresolved. Every row names its reference. The
agreement is shown on lane 0, level by level: |R_k - odefun| / u_k is
within MATCH_BAND at every level k >= 3, |R_L - odefun| <= MATCH u_L,
and the stated agreement is the largest of three: |R_L+ - odefun|,
where R_L+ = R_L + (R_L - R_(L-1)) / (2^p - 1) is the deepest level
extrapolated; how far R_L+ moved from R_(L-1)+; and odefun's own 30-
against 40-digit difference.

Every value is computed at 300 digits (check.SCHEME_DPS), or exactly;
lines beginning `time` are the only ones a re-run should change.

Exit 0 only if every check passed and every case converged; the last
line says so.
"""

import argparse
import dataclasses
import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "certificates"))
sys.path.insert(0, str(HERE))

try:
    import mpmath
except ImportError:                     # pragma: no cover
    mpmath = None

import check                            # noqa: E402  scheme_exact, scheme_run
import corpus                           # noqa: E402  read_manifest
import gen_odes                         # noqa: E402  the banks' slot names
from cft_golden import FORMATS, cert   # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

TAU = "1e-6"                # the converged reference's tolerance (the lead)
RATIO_BAND = 0.10           # successive differences within 10% of 2^p
KCAP = {4: 10, 2: 13}       # the deepest level a case may need
ORDER = {"lorenz63-rk4": 4, "lorenz96-rk4": 4, "henonheiles-lf": 2}
SCHEME = {4: "classic Runge-Kutta", 2: "Stormer-Verlet"}
H_NAMES = ("H", "H2", "H6", "MH")        # the bank slots that carry h
ODEFUN_DPS = (30, 40)
ODEFUN_SELF = "1e-25"       # odefun's 30- and 40-digit answers must agree
MATCH = 2                   # |odefun - R_K| <= MATCH u at every boundary
MATCH_BAND = (0.5, 2.0)     # |R_k - odefun| / u_k, level by level
RESOLVE_REF = "0.001"       # R_L scores a level its 2u_L is <= 0.1% of
RESOLVE_OD = "0.01"         # odefun one its stated agreement is <= 1% of
# the sweep, lane 0: (system, format) -> (J, the deepest level scored;
# L, the deepest level of the scheme computed, at least J + 1)
SWEEP = {("lorenz63-rk4", "fp64"): (9, 10),
         ("lorenz96-rk4", "fp64"): (7, 8),
         ("henonheiles-lf", "fp64"): (10, 11),
         ("lorenz63-rk4", "fp256"): (4, 8)}
TOOL_TIMEOUT = 900

CHECKS = 0
FAILED = []
NOT_CONVERGED = []
T_ALL = time.perf_counter()


def ok(what):
    global CHECKS
    CHECKS += 1
    print(f"  ok    {what}", flush=True)


def bad(what):
    global CHECKS
    CHECKS += 1
    FAILED.append(what)
    print(f"  FAIL  {what}", flush=True)


def check_that(cond, what, why=""):
    if cond:
        ok(what)
    else:
        bad(what + (f" - {why}" if why else ""))
    return cond


def say(line=""):
    print(line, flush=True)


def timed(what, t0):
    print(f"time  {what}: {time.perf_counter() - t0:.1f} s", flush=True)


# ---- numbers -------------------------------------------------------------

def mpq(q):
    """An exact rational as an mpf at the context's precision."""
    return mpmath.mpf(q.numerator) / q.denominator


def n(x, d=6):
    """A number for a table: d significant digits."""
    if isinstance(x, (Fraction, int)):
        x = mpq(Fraction(x))
    return mpmath.nstr(x, d)


def pm(x, u, d=7):
    """x with its uncertainty u: `x +- u`."""
    return f"{n(x, d)} +- {n(u, 2)}"


def maxabs(a, b):
    """The largest absolute difference over the slots."""
    return max(abs(x - y) for x, y in zip(a, b))


def lanes_of(values, nstate):
    return [values[i:i + nstate] for i in range(0, len(values), nstate)]


def mp_state(fmt, bits):
    f = FORMATS[fmt]
    return [check.scheme_exact(f, b) for b in bits]


def exact_state(fmt, bits):
    return [cert.element_fraction(fmt, b)[1] for b in bits]


# ---- the corpus's ODE cases -----------------------------------------------

def image_base(img):
    """(system, format) of a corpus image, or (None, None): a library
    image by its programs/MANIFEST name, a source by its path's stem and
    the format the corpus assembled it at."""
    if img.how == "library":
        return check._ode_base(Path(img.name).stem)
    base, fmt = check._ode_base(Path(img.name).stem)
    return (base, img.fmt) if base else (None, None)


@dataclasses.dataclass
class Case:
    name: str
    base: str
    fmt: str                # the main run's format
    p: int
    salt: object            # bytes for a keyed case, else None
    data: bytes             # the certificate
    parsed: object          # cert.Certificate
    images: dict            # run -> image bytes
    banks: dict             # run -> bank bytes
    states: dict            # run -> [bits of boundary b]
    names: list             # the bank's slot names, in order
    nstate: int
    lanes: int
    S: int                  # the main run's segments
    steps: int
    half: int               # the half-step run's index
    wider: object           # the wider run's index, or None
    h_slots: tuple


def load_cases(only=None):
    """The corpus's cases: (scored, [(name, why not scored)]). Every file
    read is held to its manifest SHA-256 and every state to its
    certificate's hash before it is used."""
    man = corpus.read_manifest()
    scored, skipped = [], []
    for c in man.cases:
        if only and c.name not in only:
            continue
        bases = {image_base(man.images[r.image]) for r in c.runs}
        kinds = [r.kind for r in c.runs]
        if c.verdict != "accepted":
            skipped.append((c.name, f"its certificate states a relation "
                            f"that does not hold, on purpose, and the audit "
                            f"refuses it {c.verdict}: its half-step run starts "
                            f"from another state, so its difference is not an "
                            f"estimate of anything"))
            continue
        if any(b[0] is None for b in bases):
            skipped.append((c.name, "not an ODE program, and no auxiliary "
                            "run: nothing to estimate" if kinds == ["main"]
                            else "not an ODE program: its half-step run "
                            "halves a bank slot that steps no differential "
                            "equation, so there is no method error to "
                            "estimate"))
            continue
        if kinds == ["main"]:
            skipped.append((c.name, "no auxiliary run, so no estimate"))
            continue
        scored.append(load_case(c, man))
    return scored, skipped


def load_case(c, man):
    what = f"{c.name}"
    salt = corpus.rp(c.salt[0]).read_bytes() if c.salt else None
    data = corpus.rp(c.certificate[0]).read_bytes()
    check_that(corpus.sha256(data) == c.certificate[1],
               f"{what}: the certificate is the manifest's")
    parsed = cert.parse(data, salt=salt)
    images, banks, states = {}, {}, {}
    main = c.runs[0]
    base, fmt = image_base(man.images[main.image])
    for r, (rr, cr) in enumerate(zip(c.runs, parsed.runs)):
        img = corpus.rp(rr.image).read_bytes()
        bank = corpus.rp(rr.bank[0]).read_bytes() if rr.bank else b""
        good = (corpus.sha256(img) == man.images[rr.image].sha and
                cert.sha256(img) == cr.image and
                (not rr.bank or corpus.sha256(bank) == rr.bank[1]) and
                cert.sha256(img + bank) == cr.digest)
        held = []
        for b in range(rr.segments + 1):
            blob = corpus.rp(rr.state_path(c, b)).read_bytes()
            want = cr.chain[0].start if b == 0 else cr.chain[b - 1].end
            good = good and corpus.sha256(blob) == rr.boundaries[b] and \
                cert.state_hash(salt, blob) == want
            held.append(cert.state_values(cr.fmt, blob))
        check_that(good, f"{what}: run {r} ({cr.kind}, {cr.fmt}) - its "
                   f"image, bank and {rr.segments + 1} boundary states are "
                   f"the manifest's files and the certificate's hashes")
        images[r], banks[r], states[r] = img, bank, held
    names = [nm for nm, _v in gen_odes.bank_values(base, FORMATS[fmt])]
    check_that(banks[0] == gen_odes.bank_bytes(base, FORMATS[fmt]),
               f"{what}: run 0's bank is gen_odes.py's classic bank, so its "
               f"slots are {', '.join(names)}")
    half = next(r for r, cr in enumerate(parsed.runs)
                if cr.kind == "half-step")
    wider = next((r for r, cr in enumerate(parsed.runs)
                  if cr.kind == "wider"), None)
    h_slots = tuple(parsed.runs[half].h_slots)
    want = tuple(i for i, nm in enumerate(names) if nm in H_NAMES)
    check_that(h_slots == want, f"{what}: the half-step run's h-slots "
               f"{list(h_slots)} are the slots named "
               f"{', '.join(names[i] for i in want)}")
    nstate = len(states[0][0]) // parsed.runs[0].lanes
    return Case(c.name, base, fmt, ORDER[base], salt, data, parsed, images,
                banks, states, names, nstate, parsed.runs[0].lanes,
                len(parsed.runs[0].chain), parsed.runs[0].steps, half,
                wider, h_slots)


# ---- the references --------------------------------------------------------

class References:
    """The scheme at h/2^k, one lane at a time, kept once computed: (system,
    format, bank, h-slots, the lane's start, steps a segment) -> {k: the
    states at boundaries 0..S}. A shorter horizon from the same start
    (the `example` case, half of henonheiles-lf-fp64's) is a prefix."""

    def __init__(self):
        self.memo = {}

    def level(self, base, fmt, bank_bits, h_slots, init_bits, steps, S, k):
        key = (base, fmt, tuple(bank_bits), tuple(h_slots),
               tuple(init_bits), steps)
        levels = self.memo.setdefault(key, {})
        have = levels.get(k)
        if have is not None and len(have) > S:
            return have[:S + 1]
        F = FORMATS[fmt]
        Km = [check.scheme_exact(F, b) for b in bank_bits]
        # exact: a power of two at SCHEME_DPS digits, as the certificate's
        # half-step bank halves each named slot exactly
        Kk = [v / 2 ** k if i in h_slots else v for i, v in enumerate(Km)]
        s = [check.scheme_exact(F, b) for b in init_bits]
        out = [s]
        for _b in range(S):
            s = check.scheme_run(base, Kk, [s], steps * 2 ** k)[0]
            out.append(s)
        levels[k] = out
        return out


REFS = References()


def bank_bits(case):
    return cert.state_values(case.fmt, case.banks[0])


def lane_levels(case, lane, upto):
    """[R_0 .. R_upto] for one lane: each the states at boundaries 0..S."""
    bank = bank_bits(case)
    init = lanes_of(case.states[0][0], case.nstate)[lane]
    return [REFS.level(case.base, case.fmt, bank, case.h_slots, init,
                       case.steps, case.S, k) for k in range(upto + 1)]


def converge(case, tau):
    """Raise k until the converged reference's two conditions hold in every
    lane at every boundary. -> (K, levels[lane][k][b]) or (None, levels)."""
    p = case.p
    levels = [[] for _ in range(case.lanes)]
    bank = bank_bits(case)
    inits = lanes_of(case.states[0][0], case.nstate)
    say(f"  the scheme at h/2^k, {check.SCHEME_DPS} digits, every lane; "
        f"at the last boundary, the maxima over the lanes:")
    say(f"    {'k':>2}  {'|R_k - R_(k-1)|':>14}  {'ratio':>9}  "
        f"{'|R_0 - R_k|':>14}")
    for k in range(KCAP[p] + 1):
        t0 = time.perf_counter()
        for i in range(case.lanes):
            levels[i].append(REFS.level(case.base, case.fmt, bank,
                                        case.h_slots, inits[i], case.steps,
                                        case.S, k))
        dt = time.perf_counter() - t0
        if k == 0:
            say(f"    {k:>2}  (R_0: check.py's arm over the whole run, the "
                f"main run's rounding reference)")
            print(f"time  {case.name} level {k}: {dt:.1f} s", flush=True)
            continue
        d = [maxabs(levels[i][k][case.S], levels[i][k - 1][case.S])
             for i in range(case.lanes)]
        e = [maxabs(levels[i][0][case.S], levels[i][k][case.S])
             for i in range(case.lanes)]
        ratio = ""
        if k >= 2:
            dp = [maxabs(levels[i][k - 1][case.S], levels[i][k - 2][case.S])
                  for i in range(case.lanes)]
            ratio = n(max(dp) / max(d), 6)
        say(f"    {k:>2}  {n(max(d)):>14}  {ratio:>9}  {n(max(e), 8):>14}")
        print(f"time  {case.name} level {k}: {dt:.1f} s", flush=True)
        if k < 3:
            continue
        good = True
        for i in range(case.lanes):
            for b in range(1, case.S + 1):
                dk = maxabs(levels[i][k][b], levels[i][k - 1][b])
                dk1 = maxabs(levels[i][k - 1][b], levels[i][k - 2][b])
                ek = maxabs(levels[i][0][b], levels[i][k][b])
                if not (dk <= tau * ek and
                        abs(dk1 / dk / 2 ** p - 1) <= RATIO_BAND):
                    good = False
        if good:
            return k, levels
    return None, levels


def field(base, P):
    """The vector field in its textbook form, for mpmath.odefun - written
    here, not taken from gen_odes.py or ode_step. P: the bank's values by
    their names."""
    if base == "lorenz63-rk4":
        s, r, b = P["SIGMA"], P["RHO"], P["BETA"]
        return lambda t, Y: [s * (Y[1] - Y[0]), Y[0] * (r - Y[2]) - Y[1],
                             Y[0] * Y[1] - b * Y[2]]
    if base == "lorenz96-rk4":
        F = P["F"]

        def f(t, X):
            N = len(X)
            return [(X[(i + 1) % N] - X[(i - 2) % N]) * X[(i - 1) % N]
                    - X[i] + F for i in range(N)]
        return f
    if base == "henonheiles-lf":
        # H = (px^2 + py^2)/2 + (x^2 + y^2)/2 + x^2 y - y^3/3
        return lambda t, Y: [Y[2], Y[3], -Y[0] * (1 + 2 * Y[1]),
                             Y[1] * Y[1] - Y[1] - Y[0] * Y[0]]
    raise KeyError(base)


def shift_of(case):
    """(H, delta) as exact rationals: delta = 6 H6/H - 1 where the bank
    has H6, else 0."""
    F = FORMATS[case.fmt]
    vals = dict(zip(case.names, bank_bits(case)))
    H = check._frac(F, vals["H"])
    if "H6" in vals:
        return H, 6 * check._frac(F, vals["H6"]) / H - 1
    return H, Fraction(0)


class Odefun:
    """mpmath.odefun for one lane at each of ODEFUN_DPS digits, created
    and evaluated under its own precision, compared at SCHEME_DPS."""

    def __init__(self, case, lane):
        F = FORMATS[case.fmt]
        vals = dict(zip(case.names, bank_bits(case)))
        P = {nm: check.scheme_exact(F, b) for nm, b in vals.items()}
        y0 = mp_state(case.fmt, lanes_of(case.states[0][0],
                                         case.nstate)[lane])
        self.sol = {}
        for dps in ODEFUN_DPS:
            with mpmath.workdps(dps):
                self.sol[dps] = mpmath.odefun(field(case.base, P), 0, y0)

    def at(self, t, dps=ODEFUN_DPS[-1]):
        with mpmath.workdps(dps):
            y = self.sol[dps](t)
        return [+v for v in y]


# ---- certified: every lane of the corpus's runs ----------------------------

def entry(method, uses, lane):
    return cert.Entry(method, cert.METHOD_KIND[method], uses, lane, None)


def score_certified(case, tau):
    t_case = time.perf_counter()
    p = case.p
    rich = 1 - Fraction(1, 2 ** p)
    H, delta = shift_of(case)
    say()
    say(f"-- {case.name}: {SCHEME[p]} (p = {p}), {case.lanes} lanes of "
        f"{case.nstate} slots, {case.S} segments of {case.steps} steps; "
        f"Richardson's 1 - 2^-p = {n(rich)}")
    say(f"  T = {case.S * case.steps} H, H = the bank's h = {n(H, 30)} "
        f"= 0.01 + ({n(H - Fraction(1, 100), 4)})")
    say(f"  delta = 6 H6/H - 1 = "
        f"{n(delta) if delta else '0 exactly' if 'H6' in case.names else '0: the bank has no rounded derived constant'}")
    K, levels = converge(case, mpmath.mpf(tau))
    if K is None:
        NOT_CONVERGED.append(case.name)
        say(f"  NOT CONVERGED: {case.name} reached level {KCAP[p]} without "
            f"both conditions in every lane at every boundary; not scored")
        return None
    u = [[maxabs(levels[i][K][b], levels[i][K - 1][b]) / (2 ** p - 1)
          for b in range(case.S + 1)] for i in range(case.lanes)]
    say(f"  converged at K = {K}: in every lane at every boundary "
        f"|R_K - R_(K-1)| <= {tau} |R_0 - R_K| and the last ratio is within "
        f"{int(RATIO_BAND * 100)}% of {2 ** p}; the reference's stated error "
        f"u = |R_K - R_(K-1)|/{2 ** p - 1} is at most "
        f"{n(max(max(x[1:]) for x in u), 3)} (at h/2^{K}, "
        f"{case.S * case.steps * 2 ** K} steps)")
    # the 300-digit arm against itself at 400 digits, level 0
    F = FORMATS[case.fmt]
    worst = mpmath.mpf(0)
    with mpmath.workdps(400):
        Km = [check.scheme_exact(F, b) for b in bank_bits(case)]
        for i, init in enumerate(lanes_of(case.states[0][0], case.nstate)):
            s = [check.scheme_exact(F, b) for b in init]
            for b in range(1, case.S + 1):
                s = check.ode_step(case.base, check._MpOps, Km, s,
                                   case.steps)
                worst = max(worst, maxabs(s, levels[i][0][b]))
    say(f"  the 300-digit arm (level 0) against the same at 400 digits: "
        f"largest difference {n(worst, 3)}")
    # odefun: the cross-check, and the shift
    t0 = time.perf_counter()
    od = [Odefun(case, i) for i in range(case.lanes)]
    say(f"  odefun at {ODEFUN_DPS[0]} and {ODEFUN_DPS[1]} digits, lane by "
        f"lane, at t_b (1 + delta), t_b = b x {case.steps} H:")
    say(f"    {'lane':>4}  {'b':>2}  {'|od30 - od40|':>13}  "
        f"{'|R_K - od|':>12}  {'/ u':>7}  {'shift |y((1+d)t) - y(t)|':>24}")
    shifts = []
    for i in range(case.lanes):
        sh_i = []
        for b in range(1, case.S + 1):
            t = mpq(Fraction(b * case.steps) * H)
            ts = mpq(Fraction(b * case.steps) * H * (1 + delta))
            a30, a40 = od[i].at(ts, ODEFUN_DPS[0]), od[i].at(ts)
            selfd = maxabs(a30, a40)
            match = maxabs(levels[i][K][b], a40)
            shift = maxabs(a40, od[i].at(t)) if delta else mpmath.mpf(0)
            sh_i.append(shift)
            say(f"    {i:>4}  {b:>2}  {n(selfd, 3):>13}  {n(match, 5):>12}  "
                f"{n(match / u[i][b], 4):>7}  {n(shift, 6):>24}")
            check_that(selfd <= mpmath.mpf(ODEFUN_SELF) and
                       match <= MATCH * u[i][b],
                       f"{case.name} lane {i} boundary {b}: odefun agrees with "
                       f"itself to {ODEFUN_SELF} and with R_K within {MATCH}u",
                       f"{n(selfd, 3)}, {n(match / u[i][b], 3)} u")
        shifts.append(sh_i)
    timed(f"{case.name} odefun", t0)
    # step-halving
    runs = case.parsed.runs
    shapes = [(cr.fmt, case.nstate) for cr in runs]
    known = {(r, b): st for r, sts in case.states.items()
             for b, st in enumerate(sts)}
    say(f"  step-halving at every boundary: E = max |F0(b) - F1(2b)|, the "
        f"method error M = max |R_0 - R_K|, the total error "
        f"|F0 - R_K|; E/M against {n(rich)} (the uncertainty from 2u, "
        f"the same for the exact column's)")
    say(f"    {'lane':>4}  {'b':>2}  {'E':>13}  {'M':>13}  "
        f"{'E/M':>22}  {'E/M - (1-2^-p)':>14}  {'p_eff':>7}  "
        f"{'exact (R_0-R_1)/M':>17}  {'E/total':>10}")
    for b in range(1, case.S + 1):
        Es, Ms, Us = [], [], []
        for i in range(case.lanes):
            f0 = lanes_of(case.states[0][b], case.nstate)[i]
            f1 = lanes_of(case.states[case.half][2 * b], case.nstate)[i]
            E = max(abs(x - y) for x, y in zip(exact_state(case.fmt, f0),
                                                exact_state(case.fmt, f1)))
            R0, R1, RK = levels[i][0][b], levels[i][1][b], levels[i][K][b]
            F0 = mp_state(case.fmt, f0)
            M = maxabs(R0, RK)
            tot = maxabs(F0, RK)
            Em = mpq(E)
            ratio = Em / M
            unc = ratio * 2 * u[i][b] / M
            peff = mpmath.log(M / maxabs(R1, RK), 2)
            exact = maxabs(R0, R1) / M
            Es.append(E)
            Ms.append(M)
            Us.append(u[i][b])
            say(f"    {i:>4}  {b:>2}  {n(Em):>13}  {n(M):>13}  "
                f"{pm(ratio, unc):>22}  {n(ratio - mpq(rich), 3):>14}  "
                f"{n(peff, 4):>7}  {n(exact, 7):>17}  {n(Em / tot, 7):>10}")
            if b == case.S:
                q = cert.derive(entry("step-halving", case.half, i), runs,
                                shapes, known)
                check_that(q == E, f"{case.name} lane {i}: the estimate is "
                           f"cert.derive's, the page's function")
        Emax, Mmax = max(Es), max(Ms)
        ratio = mpq(Emax) / Mmax
        unc = ratio * 2 * max(Us) / Mmax
        say(f"    {'max':>4}  {b:>2}  {n(Emax):>13}  {n(Mmax):>13}  "
            f"{pm(ratio, unc):>22}  {n(ratio - mpq(rich), 3):>14}")
        if b == case.S:
            q = cert.derive(entry("step-halving", case.half, None), runs,
                            shapes, known)
            check_that(q == Emax, f"{case.name}: the max-lanes estimate is "
                       f"cert.derive's, {n(q, 10)}")
    for j, e in enumerate(case.parsed.accuracy):
        if e.method not in cert.METHOD_RUN:
            continue
        q = cert.derive(e, runs, shapes, known)
        check_that(cert.value_holds(e.value, q),
                   f"{case.name}: the certificate's entry {j} ({e.method}, "
                   f"{'lane ' + str(e.lane) if e.lane is not None else 'max-lanes'}"
                   f", {e.value.form}) holds its derived value {n(q, 10)}")
    # wider
    if case.wider is None:
        if case.fmt == cert.LADDER[-1]:
            refuse_wider(case)
    else:
        say(f"  wider at the last boundary: W = max |F0 - F2| against the "
            f"rounding error rho = max |F0 - R_0|; the wider run's own "
            f"rounding |F2 - R_0| bounds |W - rho|; the time shift beside")
        say(f"    {'lane':>4}  {'W':>13}  {'rho':>13}  {'W/rho - 1':>11}  "
            f"{'|F2 - R_0|':>11}  {'shift':>12}  {'shift/rho':>9}")
        Ws, rhos = [], []
        wfmt = runs[case.wider].fmt
        for i in range(case.lanes):
            f0 = lanes_of(case.states[0][case.S], case.nstate)[i]
            f2 = lanes_of(case.states[case.wider][case.S], case.nstate)[i]
            q = cert.derive(entry("wider", case.wider, i), runs, shapes,
                            known)
            W = mpq(q)
            R0 = levels[i][0][case.S]
            rho = maxabs(mp_state(case.fmt, f0), R0)
            rho2 = maxabs(mp_state(wfmt, f2), R0)
            sh = shifts[i][case.S - 1]
            Ws.append(W)
            rhos.append(rho)
            say(f"    {i:>4}  {n(W):>13}  {n(rho):>13}  {n(W / rho - 1, 3):>11}"
                f"  {n(rho2, 3):>11}  {n(sh, 6):>12}  {n(sh / rho, 4):>9}")
        say(f"    {'max':>4}  {n(max(Ws)):>13}  {n(max(rhos)):>13}  "
            f"{n(max(Ws) / max(rhos) - 1, 3):>11}")
    timed(f"{case.name} in all", t_case)
    return K


def refuse_wider(case):
    """At fp256 no wider run exists: the golden audit, handed this case's
    own certificate with run 0 attached again as a wider run (an fp256
    run beside an fp256 main run), must refuse it aux-format - in its
    relation check, before any segment is re-run."""
    runs = case.parsed.runs
    extra = dataclasses.replace(runs[0], kind="wider")
    c2 = cert.Certificate(case.parsed.mode, case.parsed.salt_commitment,
                          case.parsed.identity, runs + (extra,), ())
    data = cert.encode(c2)
    r = len(runs)
    progs = {k: (case.images[k], case.banks[k]) for k in range(r)}
    progs[r] = progs[0]
    states = {k: dict(enumerate(case.states[k])) for k in range(r)}
    states[r] = states[0]
    try:
        cert.audit(data, case.salt, progs, states=states)
        bad(f"{case.name}: the golden audit ACCEPTS a wider run at fp256")
    except cert.Refusal as e:
        check_that(e.name == "aux-format",
                   f"{case.name}: wider - none. The golden audit, handed this "
                   f"certificate with an fp256 run attached as its wider run, "
                   f"refuses it {e.name} (exit {e.exit_code}): {e.message}",
                   f"it says {e.name}")


# ---- sweep: lane 0 as h shrinks ---------------------------------------------

def halve(fmt, bits, slots):
    """A bank with each named slot exactly halved (corpus.halved's rule)."""
    F = FORMATS[fmt]
    half = corpus.dec(fmt, "0.5")
    out = list(bits)
    for s in slots:
        out[s], fl = sf.mul(F, out[s], half)
        assert fl == 0, "halving these banks is exact"
    return out


def segrun(tool, work, tag, runs):
    """cft-segrun, one certificate, open, software backend. `runs`:
    [(kind, h_slots, image bytes, fmt, bank bits, init bits, segments,
    steps)]. -> (certificate bytes, {run: [boundary bits]}, programs), or
    None having failed."""
    d = work / tag
    d.mkdir(parents=True)
    args = ["--out", d / "c.cert", "--states", d / "states", "--open",
            "--device", "sw"]
    progs = {}
    for r, (kind, hs, img, fmt, bank, init, segs, steps) in enumerate(runs):
        (d / f"run{r}.cftp").write_bytes(img)
        (d / f"run{r}.bank").write_bytes(cert.state_bytes(fmt, bank))
        (d / f"run{r}.init").write_bytes(cert.state_bytes(fmt, init))
        args += ["--run", kind]
        if kind == "half-step":
            args += ["--h-slots", ",".join(str(s) for s in hs)]
        args += ["--image", d / f"run{r}.cftp", "--bank", d / f"run{r}.bank",
                 "--init", d / f"run{r}.init", "--segments", segs,
                 "--steps", steps]
        progs[r] = (img, cert.state_bytes(fmt, bank))
    try:
        p = subprocess.run([str(tool)] + [str(a) for a in args],
                           capture_output=True, text=True,
                           timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        bad(f"{tag}: cft-segrun ran past {TOOL_TIMEOUT} s")
        return None
    if p.returncode != 0:
        bad(f"{tag}: cft-segrun exits {p.returncode}: "
            f"{p.stderr.strip()[-300:]}")
        return None
    data = (d / "c.cert").read_bytes()
    states = {}
    for r, (_k, _h, _i, fmt, _b, _n, segs, _s) in enumerate(runs):
        states[r] = [cert.state_values(fmt, (d / "states" /
                     f"run-{r}-boundary-{b}.bin").read_bytes())
                     for b in range(segs + 1)]
    return data, states, progs


def sweep_system(case, J, L, tool, work):
    t_sys = time.perf_counter()
    p = case.p
    rich = 1 - Fraction(1, 2 ** p)
    H, delta = shift_of(case)
    say()
    say(f"-- {case.base} at {case.fmt}, lane 0, as h shrinks: levels j = 0.."
        f"{J}, h = H/2^j, {case.S} x 2^j segments of {case.steps} steps; the "
        f"scheme at 300 digits to level L = {L}; Richardson's 1 - 2^-p = "
        f"{n(rich)}")
    img = case.images[0]
    bank0 = bank_bits(case)
    init0 = lanes_of(case.states[0][0], case.nstate)[0]
    wider = case.wider is not None
    wimg = case.images[case.wider] if wider else None
    wfmt = case.parsed.runs[case.wider].fmt if wider else None
    # the rounding references and the method's reference, lane 0
    t0 = time.perf_counter()
    lv = lane_levels(case, 0, L)
    S = case.S
    d = [None] + [maxabs(lv[k][S], lv[k - 1][S]) for k in range(1, L + 1)]
    uL = d[L] / (2 ** p - 1)
    timed(f"{case.base} {case.fmt} lane 0, levels 0..{L}", t0)
    t0 = time.perf_counter()
    od = Odefun(case, 0)
    T = Fraction(S * case.steps) * H
    y_od = od.at(mpq(T * (1 + delta)))
    selfd = maxabs(od.at(mpq(T * (1 + delta)), ODEFUN_DPS[0]), y_od)
    timed(f"{case.base} {case.fmt} lane 0, odefun", t0)
    say(f"  lane 0's levels k = 1..{L} against odefun at T (1 + delta), "
        f"level by level: the scheme's levels approach odefun as each "
        f"level's own stated error u_k = |R_k - R_(k-1)|/{2 ** p - 1} says")
    say(f"    {'k':>2}  {'|R_k - od|':>12}  {'u_k':>12}  {'ratio':>8}")
    band = True
    for k in range(1, L + 1):
        dist = maxabs(lv[k][S], y_od)
        uk = d[k] / (2 ** p - 1)
        say(f"    {k:>2}  {n(dist, 5):>12}  {n(uk, 5):>12}  "
            f"{n(dist / uk, 5):>8}")
        if k >= 3 and not MATCH_BAND[0] <= dist / uk <= MATCH_BAND[1]:
            band = False
    ext = [None, None] + [
        [a + (a - b) / (2 ** p - 1) for a, b in zip(lv[k][S], lv[k - 1][S])]
        for k in range(2, L + 1)]
    a_plus = maxabs(ext[L], y_od)
    d_plus = maxabs(ext[L], ext[L - 1])
    t_od = max(a_plus, d_plus, selfd)
    usable = band and maxabs(lv[L][S], y_od) <= MATCH * uL
    say(f"  the deepest level L = {L}: |R_L - od| = "
        f"{n(maxabs(lv[L][S], y_od), 4)}, 2 u_L = {n(2 * uL, 4)}; its "
        f"Richardson extrapolation R_L + (R_L - R_(L-1))/{2 ** p - 1} is "
        f"{n(a_plus, 3)} from odefun and moved {n(d_plus, 3)} from level "
        f"L - 1's; odefun's 30 and 40 digits differ by {n(selfd, 3)}")
    check_that(usable, f"{case.base} {case.fmt}: odefun sits at the scheme's "
               f"own limit - at every level k >= 3 |R_k - od|/u_k is in "
               f"{list(MATCH_BAND)}, and |R_L - od| <= {MATCH} u_L - so it "
               f"may score a level, within its stated agreement "
               f"max(those three) = {n(t_od, 3)}")
    # the certified runs, level by level
    rows = []
    prev_half = None
    t0 = time.perf_counter()
    bj = bank0
    for j in range(J + 1):
        bj1 = halve(case.fmt, bj, case.h_slots)
        runs = [("main", (), img, case.fmt, bj, init0, S * 2 ** j,
                 case.steps),
                ("half-step", case.h_slots, img, case.fmt, bj1, init0,
                 S * 2 ** (j + 1), case.steps)]
        if wider:
            runs.append(("wider", (), wimg, wfmt,
                         [cert.widen(case.fmt, x) for x in bj],
                         [cert.widen(case.fmt, x) for x in init0],
                         S * 2 ** j, case.steps))
        tag = f"{case.base}-{case.fmt}-j{j}"
        got = segrun(tool, work, tag, runs)
        if got is None:
            return None
        data, states, progs = got
        seed = hashlib.sha256(f"ACC-A sweep {tag}".encode()).digest()
        try:
            v = cert.audit(data, None, progs,
                           states={r: dict(enumerate(s))
                                   for r, s in states.items()},
                           choose={r: ("sample", 1) for r in states},
                           seed=seed)
            ok(f"{tag}: the golden audit accepts cft-segrun's certificate, "
               f"re-running {[len(x['rerun']) for x in v.runs]} sampled "
               f"segments, seed {seed.hex()[:16]}...")
        except cert.Refusal as e:
            bad(f"{tag}: the golden audit refuses it: {e.name}: {e.message}")
        F0, F1 = states[0][-1], states[1][-1]
        if j == 0:
            check_that(F0 == lanes_of(case.states[0][S], case.nstate)[0]
                       and F1 == lanes_of(case.states[case.half][2 * S],
                                          case.nstate)[0]
                       and (not wider or states[2][-1] == lanes_of(
                           case.states[case.wider][S], case.nstate)[0]),
                       f"{tag}: lane 0 of the corpus's runs, bit for bit")
        if prev_half is not None:
            check_that(F0 == prev_half, f"{tag}: its main run's final state "
                       f"is level {j - 1}'s half-step run's, bit for bit")
        prev_half = F1
        rows.append((j, F0, F1, states[2][-1] if wider else None))
        bj = bj1
    timed(f"{case.base} {case.fmt} cft-segrun and the audits", t0)
    # the scores
    say(f"  step-halving at level j: E = max |F_j - F_(j+1)| (the half-step "
        f"run's), the method error M = max |R_j - ref|, the total error "
        f"|F_j - ref|, rho = |F_j - R_j| the run's rounding; ref is R_{L} "
        f"where 2u_L <= {RESOLVE_REF} M, else odefun where its stated "
        f"agreement <= {RESOLVE_OD} M; the uncertainty is the "
        f"reference's")
    say(f"    {'j':>2}  {'E':>11}  {'ref':>6}  {'M':>11}  {'E/M':>20}  "
        f"{'exact |R_j - R_(j+1)|/M':>23}  {'total':>11}  {'E/total':>18}  "
        f"{'rho':>10}")
    res_ref, res_od = mpmath.mpf(RESOLVE_REF), mpmath.mpf(RESOLVE_OD)
    out = []
    for j, F0, F1, F2 in rows:
        Rj, Rj1 = lv[j][S], lv[j + 1][S]
        f0 = mp_state(case.fmt, F0)
        E = mpq(max(abs(x - y) for x, y in zip(exact_state(case.fmt, F0),
                                                exact_state(case.fmt, F1))))
        rho = maxabs(f0, Rj)
        if j < L and 2 * uL <= res_ref * maxabs(Rj, lv[L][S]):
            ref, name, unc = lv[L][S], f"R_{L}", 2 * uL
        elif usable and t_od <= res_od * maxabs(Rj, y_od):
            ref, name, unc = y_od, "odefun", t_od
        else:
            ref, name, unc = None, "none", None
        exact_ratio = None
        if ref is None:
            M = tot = None
            say(f"    {j:>2}  {n(E, 5):>11}  {name:>6}  {'unresolved':>11}  "
                f"{'':>20}  {'':>23}  {'':>11}  {'':>18}  {n(rho, 3):>10}")
        else:
            M = maxabs(Rj, ref)
            tot = maxabs(f0, ref)
            r1, r2 = E / M, E / tot
            exact_ratio = maxabs(Rj, Rj1) / M
            say(f"    {j:>2}  {n(E, 5):>11}  {name:>6}  {n(M, 5):>11}  "
                f"{pm(r1, r1 * unc / M, 6):>20}  "
                f"{pm(exact_ratio, exact_ratio * unc / M, 6):>23}  "
                f"{n(tot, 5):>11}  {pm(r2, r2 * unc / tot, 6):>18}  "
                f"{n(rho, 3):>10}")
        out.append({"j": j, "E": E, "ref": name, "M": M, "tot": tot,
                    "unc": unc, "rho": rho, "exact": exact_ratio})
    if wider:
        say(f"  wider at level j: W = max |F_j - F_j(wider)| against rho = "
            f"|F_j - R_j|; the wider run's own rounding |F2 - R_j| beside")
        say(f"    {'j':>2}  {'W':>11}  {'rho':>11}  {'W/rho - 1':>11}  "
            f"{'|F2 - R_j|':>11}")
        for (j, F0, _F1, F2), o in zip(rows, out):
            W = mpq(max(abs(x - y) for x, y in zip(
                exact_state(case.fmt, F0), exact_state(wfmt, F2))))
            rho2 = maxabs(mp_state(wfmt, F2), lv[j][S])
            o["W"], o["rho2"] = W, rho2
            say(f"    {j:>2}  {n(W, 6):>11}  {n(o['rho'], 6):>11}  "
                f"{n(W / o['rho'] - 1, 3):>11}  {n(rho2, 3):>11}")
    timed(f"{case.base} {case.fmt} sweep in all", t_sys)
    return out


# ---- main ----------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", choices=("certified", "sweep", "all"))
    ap.add_argument("--tool", help="cft-segrun, for the sweep")
    ap.add_argument("--cases", help="only these corpus cases, comma-separated")
    ap.add_argument("--tau", default=TAU,
                    help=f"the converged reference's tolerance ({TAU})")
    ap.add_argument("--keep", help="keep the sweep's runs in this directory")
    args = ap.parse_args()
    # LF on every platform, so that a re-run redirected to a file diffs
    # against the committed run line for line (Windows would write CRLF)
    try:
        sys.stdout.reconfigure(newline="\n")
    except (AttributeError, ValueError):
        pass
    if mpmath is None:
        sys.exit("estimates: needs mpmath - check.py's 300-digit arm is "
                 "written in it, and odefun is its")
    if args.mode in ("sweep", "all") and not args.tool:
        sys.exit("estimates: the sweep needs --tool, cft-segrun")
    mpmath.mp.dps = check.SCHEME_DPS
    only = set(args.cases.split(",")) if args.cases else None
    say(f"== ACC-A: a certificate's two estimates, scored "
        f"(programs/estimates.py {args.mode})")
    say(f"mpmath {mpmath.__version__} on {mpmath.libmp.BACKEND}; the scheme "
        f"at {check.SCHEME_DPS} digits (check.SCHEME_DPS); TAU {args.tau}; "
        f"levels to at most {KCAP[4]} (RK4) and {KCAP[2]} (Stormer-Verlet)")
    say()
    say("== the cases: certificates/MANIFEST")
    t0 = time.perf_counter()
    cases, skipped = load_cases(only)
    for name, why in skipped:
        say(f"  not scored: {name} - {why}")
    timed("loading and holding the corpus", t0)
    results = {}
    if args.mode in ("certified", "all"):
        say()
        say("== certified: every lane of the corpus's runs")
        for case in cases:
            results[case.name] = score_certified(case, args.tau)
    if args.mode in ("sweep", "all"):
        say()
        say("== sweep: lane 0 as h shrinks, each level a certificate "
            "cft-segrun makes here")
        tool = Path(args.tool).resolve()
        work = Path(args.keep) if args.keep else \
            Path(tempfile.mkdtemp(prefix="acc-a-"))
        work.mkdir(parents=True, exist_ok=True)
        by = {(c.base, c.fmt): c for c in cases if c.name != "example"}
        for key, (J, L) in SWEEP.items():
            if key in by:
                sweep_system(by[key], J, L, tool, work)
        if not args.keep:
            shutil.rmtree(work, ignore_errors=True)
    say()
    for name in NOT_CONVERGED:
        say(f"NOT CONVERGED: {name}")
    for f in FAILED:
        say(f"FAILED: {f}")
    timed("total", T_ALL)
    good = not FAILED and not NOT_CONVERGED
    say(f"estimates: {CHECKS} checks, {len(FAILED)} failed, "
        f"{len(NOT_CONVERGED)} not converged - "
        f"{'every check passed' if good else 'NOT every check passed'}")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
