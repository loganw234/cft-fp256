# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Score host/tools/orbits.c against a 300-digit oracle.

    python3 host/tests/orbits_check.py [--exe PATH] [--quick]

The division of authority is the repository's usual one. The LIBRARY
is the authority on arithmetic: what fma(a, b, c) returns and which
flags it raises is settled by docs/DETERMINISM.md and by
python/cft_golden, not by anything here. MPMATH AT 300 DIGITS is the
authority on the domain, in two different ways, and keeping them
apart is the whole design of this file:

  THE SAME DISCRETE SCHEME, at 300 digits, from the tool's own
  starting ENCODINGS and the tool's own derived CONSTANTS (which is
  what `--dump-setup` exists to hand over). The difference between
  that and the tool's run is the format's ROUNDOFF and nothing else -
  not truncation, not a different step size, not a differently
  rounded 2*pi.

  THE CLOSED FORM, through Kepler's equation, which the discrete
  scheme is approximating. The difference between the 300-digit
  discrete run and that is the method's TRUNCATION error, and it is
  the same number in every format.

Those two are the reason the workload exists, so they are measured
rather than asserted, and the ratio between binary64's roundoff and
binary256's is checked against 2^(237-53) - the formats' own ratio,
which is the sharpest statement of what fp64 loses here.

Seven groups of checks:

 1. Roundoff.     Each format's Kepler run against its own 300-digit
                  twin, and the fp64/fp256 ratio against 2^184.
 2. Truncation.   The tool's fp256 run against the closed form, at two
                  step sizes, for both schemes - which recovers the
                  schemes' orders (2 and 4) from the tool's output.
 3. Invariants.   The energy and angular momentum the tool reports at
                  sample 0, against the same quantities computed at
                  300 digits from the same starting bits.
 4. Outer.        The outer solar system against its 300-digit twin,
                  and - because that table is TRANSCRIBED and every
                  other constant in the tool is derived - a physical
                  validation of the table itself: each planet's
                  osculating semi-major axis and period recovered from
                  its own (r, v) and compared with the published
                  sidereal periods. A mistyped digit moves a period by
                  percent.
 5. The chain.    Recomputed with hashlib, which is what proves the
                  tool's from-first-principles derivation of SHA-256's
                  round constants.
 6. Determinism.  Batch-size independence, program-versus-loop bit
                  identity, and interrupt/resume equivalence - all as
                  byte comparisons of checkpoints and records.
 7. Refusals.     The three things --engine program must refuse, and
                  the precise reason each is refused.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from mpmath import mp, mpf, sqrt as mp_sqrt, sin as mp_sin, cos as mp_cos, \
        pi as mp_pi, floor as mp_floor, log as mp_log
except ImportError:                                   # pragma: no cover
    raise SystemExit("orbits_check needs mpmath: pip install mpmath")

mp.dps = 300

ROOT = Path(__file__).resolve().parents[2]
FAILURES = []
CHECKS = 0


def fail(what):
    FAILURES.append(what)
    print("  FAIL: " + what)


def ok(what):
    print("  ok   " + what)


def check(cond, good, bad):
    global CHECKS
    CHECKS += 1
    if cond:
        ok(good)
    else:
        fail(bad)
    return cond


# ---------------------------------------------------------------------
# Driving the tool
# ---------------------------------------------------------------------
class Tool:
    def __init__(self, exe):
        self.exe = str(exe)

    def run(self, *args, expect_ok=True):
        proc = subprocess.run([self.exe] + [str(a) for a in args],
                              capture_output=True, text=True)
        if expect_ok and proc.returncode != 0:
            raise RuntimeError("cft-orbits %s failed (%d)\n%s\n%s"
                               % (" ".join(str(a) for a in args),
                                  proc.returncode, proc.stdout, proc.stderr))
        return proc

    def setup(self, *args):
        """The derived constants, as exact decimals."""
        out = self.run(*args, "--dump-setup").stdout
        s = {"hd": {}, "mg": {}, "hm": {}, "mhm": {}, "mass": {},
             "halfm": {}, "gmm": {}}
        for line in out.splitlines():
            f = line.split()
            if not f or f[0] != "setup":
                continue
            k = f[1]
            if k in ("hd", "mg"):
                s[k][int(f[2])] = f[3]
            elif k in ("hm", "mhm"):
                s[k][(int(f[2]), int(f[3]))] = f[4]
            elif k in ("mass", "halfm"):
                s[k][int(f[2])] = f[3]
            elif k == "gmm":
                s[k][(int(f[2]), int(f[3]))] = f[4]
            elif k == "end":
                pass
            else:
                s[k] = f[2] if len(f) > 2 else ""
        for k in ("precision", "newton", "bodies", "dims", "nsub",
                  "members", "steps", "stride", "samples"):
            s[k] = int(s[k])
        return s

    def records(self, tmp, *args, name="rec.txt"):
        path = Path(tmp) / name
        self.run(*args, "--records", path, "--quiet")
        return parse_records(path), path

    def csv(self, *args):
        out = self.run(*args, "--csv", "--quiet").stdout.strip().splitlines()
        head = out[0].split(",")
        row = out[-1].split(",")
        return dict(zip(head, row))


def parse_records(path):
    """[(sample, step, member, q[], v[], H, L[])], values as strings."""
    out = []
    for line in Path(path).read_text().splitlines():
        f = line.split()
        if not f:
            continue
        sample, step, member = int(f[0]), int(f[1]), int(f[2])
        rest = f[3:]
        # ncomp is (len(rest) - 1 - nL) / 2, and nL is 1 or 3; the
        # record's own shape settles it, since ncomp is 2 or 15
        n = len(rest)
        for ncomp, nL in ((2, 1), (15, 3)):
            if 2 * ncomp + 1 + nL == n:
                break
        else:
            raise RuntimeError("unrecognised record shape: %d fields" % n)
        q = rest[0:ncomp]
        v = rest[ncomp:2 * ncomp]
        H = rest[2 * ncomp]
        L = rest[2 * ncomp + 1:]
        out.append((sample, step, member, q, v, H, L))
    return out


def last_sample(recs, member=0):
    rows = [r for r in recs if r[2] == member]
    return rows[-1]


def first_sample(recs, member=0):
    rows = [r for r in recs if r[2] == member]
    return rows[0]


# ---------------------------------------------------------------------
# The oracle: the same discrete scheme, at 300 digits
#
# Every constant comes from --dump-setup, so this integrates the same
# map the tool integrated - the same h, the same fl(w*h/2), the same
# G. What is left over is the format's roundoff.
# ---------------------------------------------------------------------
class Scheme:
    def __init__(self, setup):
        s = setup
        self.problem = s["problem"]
        self.nb = s["bodies"]
        self.nd = s["dims"]
        self.nsub = s["nsub"]
        self.ncomp = self.nb * self.nd
        self.hd = [mpf(s["hd"][i]) for i in range(self.nsub)]
        if self.problem == "kepler":
            self.mg = [mpf(s["mg"][i]) for i in range(self.nsub)]
            self.mu = mpf(s["mu"])
        else:
            self.G = mpf(s["G"])
            self.hm = [[mpf(s["hm"][(i, b)]) for b in range(self.nb)]
                       for i in range(self.nsub)]
            self.mhm = [[mpf(s["mhm"][(i, b)]) for b in range(self.nb)]
                        for i in range(self.nsub)]
            self.mass = [mpf(s["mass"][b]) for b in range(self.nb)]
            self.halfm = [mpf(s["halfm"][b]) for b in range(self.nb)]
            self.gmm = {k: mpf(val) for k, val in s["gmm"].items()}

    def _drift(self, q, v, sub):
        for c in range(self.ncomp):
            q[c] = self.hd[sub] * v[c] + q[c]

    def _kick(self, q, v, sub):
        if self.problem == "kepler":
            r2 = q[0] * q[0] + q[1] * q[1]
            g = self.mg[sub] / (r2 * mp_sqrt(r2))
            v[0] = g * q[0] + v[0]
            v[1] = g * q[1] + v[1]
            return
        nd = self.nd
        for i in range(self.nb):
            for j in range(i + 1, self.nb):
                d = [q[j * nd + k] - q[i * nd + k] for k in range(nd)]
                r2 = sum(x * x for x in d)
                u = self.G / (r2 * mp_sqrt(r2))
                gi = u * self.hm[sub][j]
                for k in range(nd):
                    v[i * nd + k] = gi * d[k] + v[i * nd + k]
                gj = u * self.mhm[sub][i]
                for k in range(nd):
                    v[j * nd + k] = gj * d[k] + v[j * nd + k]

    def step(self, q, v):
        for s in range(self.nsub):
            self._drift(q, v, s)
            self._kick(q, v, s)
            self._drift(q, v, s)

    def run(self, q0, v0, nsteps):
        q = list(q0)
        v = list(v0)
        for _ in range(nsteps):
            self.step(q, v)
        return q, v

    def energy(self, q, v):
        if self.problem == "kepler":
            r = mp_sqrt(q[0] * q[0] + q[1] * q[1])
            return (v[0] * v[0] + v[1] * v[1]) / 2 - self.mu / r
        nd = self.nd
        H = mpf(0)
        for i in range(self.nb):
            H += self.halfm[i] * sum(v[i * nd + k] ** 2 for k in range(nd))
        for i in range(self.nb):
            for j in range(i + 1, self.nb):
                r = mp_sqrt(sum((q[j * nd + k] - q[i * nd + k]) ** 2
                                for k in range(nd)))
                H -= self.gmm[(i, j)] / r
        return H

    def angmom(self, q, v):
        if self.problem == "kepler":
            return [q[0] * v[1] - q[1] * v[0]]
        nd = self.nd
        out = []
        for k in range(3):
            k1, k2 = (k + 1) % 3, (k + 2) % 3
            acc = mpf(0)
            for i in range(self.nb):
                acc += self.mass[i] * (q[i * nd + k1] * v[i * nd + k2] -
                                       q[i * nd + k2] * v[i * nd + k1])
            out.append(acc)
        return out


# ---------------------------------------------------------------------
# The Kepler closed form
#
# The initial state is at an apse (q.v == 0), so the eccentric anomaly
# starts at 0 and the perifocal frame is the tool's own frame. a, e
# and n come from the state the tool ACTUALLY holds - the initial
# speed is a rounded square root, so they are not exactly 1, 3/4 and 1.
# ---------------------------------------------------------------------
def kepler_elements(q0, v0, mu):
    r0 = mp_sqrt(q0[0] ** 2 + q0[1] ** 2)
    v2 = v0[0] ** 2 + v0[1] ** 2
    energy = v2 / 2 - mu / r0
    a = -mu / (2 * energy)
    ell = q0[0] * v0[1] - q0[1] * v0[0]
    ecc = mp_sqrt(1 - ell * ell / (mu * a))
    n = mp_sqrt(mu / a ** 3)
    return a, ecc, n, ell


def kepler_at(q0, v0, mu, t):
    """Position and velocity at time t, exactly, from Kepler's equation."""
    a, ecc, n, _ = kepler_elements(q0, v0, mu)
    M = n * t
    # wrap into [-pi, pi] so Newton starts near the root whatever t is
    M = M - 2 * mp_pi * mp_floor(M / (2 * mp_pi) + mpf(1) / 2)
    E = M + ecc * mp_sin(M)
    for _ in range(200):
        f = E - ecc * mp_sin(E) - M
        fp = 1 - ecc * mp_cos(E)
        dE = f / fp
        E = E - dE
        if abs(dE) < mpf(10) ** (-(mp.dps - 20)):
            break
    else:                                             # pragma: no cover
        raise RuntimeError("Kepler's equation did not converge")
    se, ce = mp_sin(E), mp_cos(E)
    b = a * mp_sqrt(1 - ecc * ecc)
    x = a * (ce - ecc)
    y = b * se
    denom = 1 - ecc * ce
    vx = -a * n * se / denom
    vy = b * n * ce / denom
    return [x, y], [vx, vy]


# ---------------------------------------------------------------------
# Norms and ulps
# ---------------------------------------------------------------------
def norm(vec):
    return mp_sqrt(sum(x * x for x in vec))


def state_of(row):
    """(q, v) of a record row, exactly."""
    return [mpf(s) for s in row[3]], [mpf(s) for s in row[4]]


def rel_diff(a, b):
    """||a - b|| / ||b||, over a concatenated state."""
    d = norm([x - y for x, y in zip(a, b)])
    s = norm(b)
    return d / s if s else d


def ulps_of(diff, ref, p):
    """|diff| in ulps of `ref` at binary-p - the ulp of the REFERENCE,
    which is the only scale a difference means anything against."""
    if diff == 0:
        return mpf(0)
    if ref == 0:
        return mpf("inf")
    e = int(mp_floor(mp_log(abs(ref), 2)))
    return abs(diff) / mpf(2) ** (e - p + 1)


# =====================================================================
# The checks
# =====================================================================
def check_roundoff(tool, tmp, fmt, p, periods, sps, scheme="leapfrog"):
    """One format's run against its own 300-digit twin. Returns the
    relative deviation, which IS that format's accumulated roundoff."""
    args = ["--problem", "kepler", "--scheme", scheme, "--format", fmt,
            "--members", 1, "--periods", periods, "--steps-per-period", sps]
    setup = tool.setup(*args)
    recs, _ = tool.records(tmp, *args, name="ro-%s-%s.txt" % (fmt, scheme))
    q0, v0 = state_of(first_sample(recs))
    qT, vT = state_of(last_sample(recs))
    sch = Scheme(setup)
    qo, vo = sch.run(q0, v0, setup["steps"])
    return rel_diff(qT + vT, qo + vo), (qT + vT), (qo + vo), setup


def main():
    global CHECKS
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    exe = args.exe
    if exe is None:
        for cand in ("cft-orbits.exe", "cft-orbits"):
            path = ROOT / "host" / cand
            if path.exists():
                exe = path
                break
    if exe is None or not Path(exe).exists():
        raise SystemExit("cft-orbits not found - run `make -C host orbits`")
    tool = Tool(exe)
    tmp = tempfile.mkdtemp(prefix="orbits-check-")

    periods = 2 if args.quick else 4
    sps = 256 if args.quick else 512

    try:
        print("cft-orbits cross-check, tool: %s" % exe)
        print("mpmath at %d digits is the oracle; the library is the "
              "authority on arithmetic" % mp.dps)

        # -------------------------------------------------------------
        print("\n[1] the roundoff floor: each format against its own "
              "300-digit twin")
        floors = {}
        for fmt, p in (("fp256", 237), ("fp64", 53)):
            dev, got, want, setup = check_roundoff(tool, tmp, fmt, p,
                                                   periods, sps)
            floors[fmt] = dev
            nsteps = setup["steps"]
            # A step's roundoff is at most a few ulps and they add up
            # no faster than the phase error does; n^2 ulps is a
            # generous ceiling and a real one - it fails the moment an
            # operation is wrong rather than merely rounded.
            ceiling = mpf(nsteps) ** 2 * mpf(2) ** (-p) * 1000
            check(dev < ceiling,
                  "%s over %d steps deviates from the 300-digit run of the "
                  "SAME scheme by %.3e relative - the format's roundoff, "
                  "under the %.1e ceiling"
                  % (fmt, nsteps, float(dev), float(ceiling)),
                  "%s deviates by %.3e, above the %.3e ceiling: that is not "
                  "roundoff" % (fmt, float(dev), float(ceiling)))
        ratio = floors["fp64"] / floors["fp256"]
        want_ratio = mpf(2) ** (237 - 53)
        check(want_ratio / 4096 < ratio < want_ratio * 4096,
              "fp64's roundoff is %.3e times fp256's; 2^(237-53) is %.3e, "
              "so the two floors are the formats' own ratio and nothing "
              "else" % (float(ratio), float(want_ratio)),
              "fp64/fp256 roundoff ratio %.3e is nowhere near 2^184 = %.3e"
              % (float(ratio), float(want_ratio)))

        # -------------------------------------------------------------
        print("\n[2] the truncation error, and the two schemes' orders")
        # ONE period, and a step small enough that the asymptotic
        # regime has been reached: at e = 3/4 a coarse step puts the
        # error at O(1), where no order is visible in it.
        sps_o = 512 if args.quick else 1024
        for scheme, order, lo, hi in (("leapfrog", 2, 3.5, 4.6),
                                      ("yoshida4", 4, 13.0, 18.5)):
            errs = []
            for s in (sps_o, 2 * sps_o):
                a = ["--problem", "kepler", "--scheme", scheme,
                     "--format", "fp256", "--members", 1,
                     "--periods", 1, "--steps-per-period", s]
                setup = tool.setup(*a)
                recs, _ = tool.records(tmp, *a,
                                       name="tr-%s-%d.txt" % (scheme, s))
                q0, v0 = state_of(first_sample(recs))
                qT, vT = state_of(last_sample(recs))
                t = mpf(setup["h"]) * setup["steps"]
                qe, ve = kepler_at(q0, v0, mpf(setup["mu"]), t)
                errs.append(rel_diff(qT + vT, qe + ve))
            r = errs[0] / errs[1]
            check(lo < r < hi,
                  "%s: halving h cut the error from the closed form by "
                  "%.2f, and order %d wants %d - %.3e at %d steps a period, "
                  "%.3e at %d"
                  % (scheme, float(r), order, 2 ** order,
                     float(errs[0]), sps_o, float(errs[1]), 2 * sps_o),
                  "%s: halving h changed the error by %.2f, which is not "
                  "order %d" % (scheme, float(r), order))
            # and the roundoff floor must be far below it
            gap = errs[1] / floors["fp256"]
            check(gap > 10 ** 6,
                  "%s: its truncation error is %.2e times fp256's roundoff, "
                  "so the method's error is the ONLY error - which is the "
                  "condition a step-size study needs and binary64 loses"
                  % (scheme, float(gap)),
                  "%s: fp256's roundoff is not negligible against the "
                  "truncation error" % scheme)

        # -------------------------------------------------------------
        print("\n[3] the invariants the tool reports")
        a = ["--problem", "kepler", "--format", "fp256", "--members", 1,
             "--periods", 1, "--steps-per-period", 64]
        setup = tool.setup(*a)
        recs, _ = tool.records(tmp, *a, name="inv.txt")
        sch = Scheme(setup)
        row0 = first_sample(recs)
        q0, v0 = state_of(row0)
        H_want = sch.energy(q0, v0)
        L_want = sch.angmom(q0, v0)
        H_got = mpf(row0[5])
        L_got = [mpf(x) for x in row0[6]]
        dH = ulps_of(H_got - H_want, H_want, 237)
        dL = ulps_of(L_got[0] - L_want[0], L_want[0], 237)
        check(dH < 8 and dL < 8,
              "the tool's H0 and L0 match the 300-digit values from the same "
              "starting bits to %.1f and %.1f ulps of binary256"
              % (float(dH), float(dL)),
              "H0 is %.1f ulps out and L0 is %.1f ulps out"
              % (float(dH), float(dL)))
        # a = 1 and e = 3/4 to the accuracy of the rounded initial speed
        aa, ee, _, _ = kepler_elements(q0, v0, mpf(setup["mu"]))
        check(abs(aa - 1) < mpf(10) ** -60 and abs(ee - mpf(3) / 4) <
              mpf(10) ** -60,
              "the initial condition is the semi-major axis 1, eccentricity "
              "3/4 orbit it claims to be (a-1 = %.2e, e-3/4 = %.2e)"
              % (float(abs(aa - 1)), float(abs(ee - mpf(3) / 4))),
              "the initial condition is not a = 1, e = 3/4: a = %s, e = %s"
              % (mp.nstr(aa, 12), mp.nstr(ee, 12)))
        # angular momentum drift is roundoff ALONE: both schemes conserve
        # L exactly for a central force in exact arithmetic
        row = tool.csv("--problem", "kepler", "--format", "fp256",
                       "--members", 1, "--periods", periods,
                       "--steps-per-period", sps)
        row64 = tool.csv("--problem", "kepler", "--format", "fp64",
                         "--members", 1, "--periods", periods,
                         "--steps-per-period", sps)
        dl256, dl64 = mpf(row["angmom_drift"]), mpf(row64["angmom_drift"])
        dh256, dh64 = mpf(row["energy_drift"]), mpf(row64["energy_drift"])
        check(dh256 == dh64,
              "the ENERGY drift is identical at fp64 and fp256 (%s): it is "
              "the method's error and the arithmetic cannot reach it"
              % row["energy_drift"],
              "the energy drift differs between the formats: %s vs %s"
              % (row["energy_drift"], row64["energy_drift"]))
        lr = dl64 / dl256
        check(want_ratio / 4096 < lr < want_ratio * 4096,
              "the ANGULAR-MOMENTUM drift is %s at fp256 and %s at fp64, a "
              "factor of %.3e: it is roundoff alone, because both schemes "
              "conserve L exactly for a central force"
              % (row["angmom_drift"], row64["angmom_drift"], float(lr)),
              "the angular-momentum drift ratio %.3e is not the formats' "
              "ratio" % float(lr))

        # -------------------------------------------------------------
        print("\n[4] the outer solar system")
        years = 4 if args.quick else 10
        a = ["--problem", "outer", "--format", "fp256", "--members", 1,
             "--years", years, "--days", 10]
        setup = tool.setup(*a)
        recs, _ = tool.records(tmp, *a, name="outer.txt")
        q0, v0 = state_of(first_sample(recs))
        qT, vT = state_of(last_sample(recs))
        sch = Scheme(setup)
        qo, vo = sch.run(q0, v0, setup["steps"])
        dev = rel_diff(qT + vT, qo + vo)
        ceiling = mpf(setup["steps"]) ** 2 * mpf(2) ** -237 * 10 ** 6
        check(dev < ceiling,
              "fp256 over %d steps (%d years) reproduces the 300-digit "
              "discrete solution to %.3e relative"
              % (setup["steps"], years, float(dev)),
              "fp256's outer-system run deviates by %.3e, above the %.3e "
              "ceiling" % (float(dev), float(ceiling)))
        a64 = ["--problem", "outer", "--format", "fp64", "--members", 1,
               "--years", years, "--days", 10]
        setup64 = tool.setup(*a64)
        recs64, _ = tool.records(tmp, *a64, name="outer64.txt")
        q064, v064 = state_of(first_sample(recs64))
        qT64, vT64 = state_of(last_sample(recs64))
        sch64 = Scheme(setup64)
        qo64, vo64 = sch64.run(q064, v064, setup64["steps"])
        dev64 = rel_diff(qT64 + vT64, qo64 + vo64)
        check(dev64 > dev * 10 ** 40,
              "fp64's deviation from ITS 300-digit twin is %.3e, %.2e times "
              "fp256's - the same integration, the same step, only the "
              "arithmetic differs"
              % (float(dev64), float(dev64 / dev)),
              "fp64's outer-system deviation %.3e is not far above fp256's "
              "%.3e" % (float(dev64), float(dev)))

        # the transcribed table, validated physically
        print("      the published table, checked against the sky:")
        # Sidereal periods in Julian years, IAU / JPL planetary fact
        # sheets. An OSCULATING period from one instantaneous (r, v)
        # differs from the mean by under a percent for these four.
        want_T = {1: ("Jupiter", 11.862), 2: ("Saturn", 29.457),
                  3: ("Uranus", 84.021), 4: ("Neptune", 164.79)}
        G = mpf(setup["G"])
        masses = [mpf(setup["mass"][b]) for b in range(setup["bodies"])]
        good = True
        for b, (nm, T_pub) in want_T.items():
            qi = [q0[b * 3 + k] - q0[k] for k in range(3)]
            vi = [v0[b * 3 + k] - v0[k] for k in range(3)]
            r = norm(qi)
            v2 = sum(x * x for x in vi)
            gm = G * (masses[0] + masses[b])
            sma = 1 / (2 / r - v2 / gm)
            T = 2 * mp_pi * mp_sqrt(sma ** 3 / gm) / mpf("365.25")
            err = abs(T - T_pub) / T_pub
            print("        %-8s a = %8.5f AU, osculating period %8.3f yr "
                  "(published %7.3f, %.2f%%)"
                  % (nm, float(sma), float(T), T_pub, float(err) * 100))
            if err > mpf("0.03"):
                good = False
        check(good,
              "every planet's osculating semi-major axis and period, "
              "recovered from its own position and velocity, agrees with "
              "the published sidereal period to under 3% - so the "
              "transcribed table is the table it claims to be",
              "a planet's recovered period is more than 3% from the "
              "published one: suspect a digit in the table")

        # -------------------------------------------------------------
        print("\n[5] the hash chain")
        a = ["--problem", "kepler", "--format", "fp256", "--members", 4,
             "--periods", 2, "--steps-per-period", 64]
        row = tool.csv(*a, "--records", Path(tmp) / "chain.txt")
        lines = (Path(tmp) / "chain.txt").read_text().splitlines()
        h = bytes(32)
        for line in lines:
            if line.strip():
                h = hashlib.sha256(h + (line + "\n").encode("ascii")).digest()
        check(row["chain"] == h.hex(),
              "the tool's chain over %d records matches hashlib's - so its "
              "derivation of SHA-256's constants from the cube roots of the "
              "primes is right" % len(lines),
              "chain mismatch: tool %s, hashlib %s" % (row["chain"], h.hex()))

        # -------------------------------------------------------------
        print("\n[6] determinism")
        base = ["--problem", "kepler", "--format", "fp256", "--members", 8,
                "--periods", 2, "--steps-per-period", 96, "--quiet"]
        blobs = []
        for batch in (8, 3, 1):
            path = Path(tmp) / ("bs-%d.ckpt" % batch)
            tool.run(*base, "--batch", batch, "--checkpoint", path)
            blobs.append(path.read_bytes())
        check(blobs[0] == blobs[1] == blobs[2],
              "batch 8, 3 and 1 over the same ensemble end on byte-identical "
              "checkpoints - --batch is a library-call boundary and cannot "
              "reach a result",
              "the checkpoints differ across batch sizes")

        # the sequencer program against the host loop
        pbase = ["--problem", "kepler", "--format", "fp256", "--members", 6,
                 "--periods", 2, "--steps-per-period", 96,
                 "--rsqrt", "newton", "--quiet"]
        lp = Path(tmp) / "eng-loop.ckpt"
        pg = Path(tmp) / "eng-prog.ckpt"
        lr = Path(tmp) / "eng-loop.txt"
        pr = Path(tmp) / "eng-prog.txt"
        tool.run(*pbase, "--engine", "loop", "--checkpoint", lp,
                 "--records", lr)
        tool.run(*pbase, "--engine", "program", "--batch", 4,
                 "--checkpoint", pg, "--records", pr)
        check(lp.read_bytes() == pg.read_bytes() and
              lr.read_bytes() == pr.read_bytes(),
              "the whole integration as ONE sequencer program and the host "
              "cft_run loop produce byte-identical records and checkpoints",
              "the sequencer program and the host loop disagree")

        # Interrupt and resume. --stop-after-steps is deliberately a
        # number that does not divide the 96-step sample interval, so
        # most stops land part way THROUGH one: a resume that only
        # ever restarted on a sample boundary would be testing the
        # sample counter and nothing else.
        whole = Path(tmp) / "whole.ckpt"
        wrec = Path(tmp) / "whole.txt"
        tool.run(*base, "--checkpoint", whole, "--records", wrec)
        piece = Path(tmp) / "piece.ckpt"
        prec = Path(tmp) / "piece.txt"
        common = ["--problem", "kepler", "--format", "fp256", "--members", 8,
                  "--periods", 2, "--steps-per-period", 96, "--quiet",
                  "--batch", 5, "--stop-after-steps", 37,
                  "--checkpoint", piece, "--records", prec]
        tool.run(*common)
        rounds, midway = 0, 0

        def at_of(path):
            for line in Path(path).read_text().splitlines():
                if line.startswith("at "):
                    return [int(x) for x in line.split()[1:]]
            return [0, 0]

        while True:
            rounds += 1
            if rounds > 400:
                fail("the resumed run did not finish")
                break
            st, sm = at_of(piece)
            if st % 96:
                midway += 1
            if st >= 192:
                break
            tool.run(*common, "--resume")
        check(midway > 0,
              "%d of the %d interruptions landed part way through a sample "
              "interval, with the ensemble mid-flight" % (midway, rounds),
              "no interruption landed mid-interval, so the step-granular "
              "state was never exercised")
        check(piece.read_bytes() == whole.read_bytes() and
              prec.read_bytes() == wrec.read_bytes(),
              "a run stopped and resumed %d times, at a different batch "
              "size and mid sample interval, ends on the same checkpoint "
              "and the same records - byte for byte - as one that was never "
              "stopped" % rounds,
              "the resumed run's checkpoint or records differ from the "
              "uninterrupted one")

        # -------------------------------------------------------------
        print("\n[7] what --engine program must refuse")
        for why, argv in (
            ("the outer solar system (30 state values, 3 input streams)",
             ["--engine", "program", "--problem", "outer", "--rsqrt",
              "newton", "--years", 1]),
            ("--rsqrt exact (host prep, program core, host finish)",
             ["--engine", "program", "--rsqrt", "exact", "--periods", 1]),
            ("--resume (a restart state has four non-zero components)",
             ["--engine", "program", "--rsqrt", "newton", "--periods", 1,
              "--checkpoint", Path(tmp) / "never.ckpt", "--resume"]),
        ):
            proc = tool.run(*argv, expect_ok=False)
            check(proc.returncode != 0 and "cft-orbits:" in proc.stderr,
                  "refused: %s\n         (%s)"
                  % (why, proc.stderr.strip().splitlines()[0][:110]),
                  "not refused: %s" % why)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d checks, %d failures" % (CHECKS, len(FAILURES)))
    if FAILURES:
        print("ORBITS CHECK FAILED")
        return 1
    print("ORBITS CHECK OK - the tool, the library and the 300-digit oracle "
          "agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
