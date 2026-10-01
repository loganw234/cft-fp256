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
                  from-first-principles derivation of SHA-256's round
                  constants the tool calls (host/src/sha256.c, since
                  c0effe9).
 6. Determinism.  Batch-size independence, program-versus-loop bit
                  identity, and interrupt/resume equivalence - all as
                  byte comparisons of checkpoints and records.
 6b. Segments.    --engine segments against the host loop on both
                  problems, both schemes and all four formats, at the
                  segment lengths real runs use (1,024 steps, 1 + 99,999,
                  intervals split at the loader's limit) as well as
                  short ones; stop points; its own batch independence; a
                  run resumed ALTERNATELY by the two engines; where its
                  checkpoints fall, against the host loop's under a
                  steady clock, and a real interruption; a killed run's
                  records, resumed by either engine, against the
                  uninterrupted run's, and a run ended the instant a
                  checkpoint appears; records files and paths a resume
                  must refuse, pipes and locked files included, in
                  bounded time, and --records and --checkpoint as one
                  file; a fresh run into a file that says it holds 0
                  bytes, and into one the system will not cut; the
                  image cache's key; the checkpoint's rename held open,
                  and how long it is retried; a second writer; the
                  census it reports, derived here from the program's
                  structure; the golden model's executor and assembler
                  on the image it writes. Most legs carry a control that
                  must fail, run every time; check_segments names the
                  eleven that do not.
 7. Refusals.     What the two program engines must refuse, and the
                  precise reason each is refused.
 8. Certificates. Certified runs of the Newton route (docs/ORBITS.md,
                  "Certified runs"): each sample interval one segment of
                  the stride's image, the certificate held to the golden
                  reader and writer, to the records and to both auditors;
                  the same bytes however the run was cut, batched,
                  relayed or killed; the controls, each refused by name
                  by both auditors; and every refusal it can make, by
                  name and code, with what each leaves - all but
                  build-width, which no build whose tool and library
                  share one configuration reaches.
"""

import argparse
import hashlib
import os
import re
import shutil
from fractions import Fraction
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    from mpmath import mp, mpf, sqrt as mp_sqrt, sin as mp_sin, cos as mp_cos, \
        pi as mp_pi, floor as mp_floor, log as mp_log
except ImportError:                                   # pragma: no cover
    raise SystemExit(
        "orbits_check needs mpmath, and it is the ONLY dependency it has.\n"
        "  pip install mpmath\n"
        "or point the target at an interpreter that already carries it:\n"
        "  make -C host orbitstest PYTHON=/path/to/python\n"
        "On Windows a bare `python` inside a make recipe is often not the\n"
        "one on your shell's PATH - verify/run.sh resolves it once and\n"
        "passes it in for exactly this reason.")

mp.dps = 300

ROOT = Path(__file__).resolve().parents[2]
# The golden model: its sequencer executor and its assembler are the
# definition the segments engine's image is held to in [6b]. Standard
# library only, so this adds no dependency beside mpmath.
sys.path.insert(0, str(ROOT / "python"))
from cft_golden import FORMATS, asm, seq                 # noqa: E402

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

    def run(self, *args, expect_ok=True, env=None):
        proc = subprocess.run([self.exe] + [str(a) for a in args],
                              capture_output=True, text=True, env=env)
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


def ratio(a, b):
    """a/b, with a zero or NaN denominator answered rather than raised.

    A broken tool can report an exactly zero drift - negative control
    B does - and a check that died on that would be reporting a
    traceback where it should be reporting a failure. A NaN stays a
    NaN, so that every comparison against it is false and the check
    FAILS rather than passing on an infinity."""
    if a != a or b != b:
        return mpf("nan")
    if b == 0:
        return mpf("inf")
    return a / b


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


def _values(data, fmt):
    esz = fmt.width // 8
    return [int.from_bytes(data[i:i + esz], "little")
            for i in range(0, len(data), esz)]


def _at_of(path):
    for line in Path(path).read_text().splitlines():
        if line.startswith("at "):
            return [int(x) for x in line.split()[1:]]
    return [0, 0]


def _relay(tool, argv, ckpt, recs, engines, stop, total, env_for=None):
    """Run in pieces of `stop` steps, resuming each time with the next
    engine of `engines` in turn, until the checkpoint reaches `total`
    steps. Returns (rounds, rounds that stopped mid sample interval).
    `env_for` maps an engine to the environment its legs run under."""
    rounds, midway, stride = 0, 0, None
    while True:
        eng = engines[rounds % len(engines)]
        extra = ["--resume"] if rounds else []
        tool.run(*argv, "--engine", eng, "--stop-after-steps", stop,
                 "--checkpoint", ckpt, "--records", recs, *extra,
                 env=(env_for or {}).get(eng))
        rounds += 1
        st, _sm = _at_of(ckpt)
        if stride is None:
            for line in Path(ckpt).read_text().splitlines():
                if line.startswith("stride "):
                    stride = int(line.split()[1])
        if stride and st % stride:
            midway += 1
        if st >= total or rounds > 400:
            return rounds, midway


def _csv_row(stdout):
    lines = stdout.strip().splitlines()
    return dict(zip(lines[0].split(","), lines[-1].split(",")))


def _field_of(path, key):
    """The integer after `key` on a checkpoint line, or None."""
    for line in Path(path).read_text().splitlines():
        if line.startswith(key + " "):
            return int(line.split()[1])
    return None


def _run_until(tool, argv, ck, env=None, bound=60.0, wait=None,
               records=None, grown=0):
    """Start a run writing checkpoint `ck`, and kill it at the first of:
    `bound` seconds; `wait` seconds (when given); or - when `wait` is
    None - once `ck` exists and, when `records` is given, that file has
    grown by more than `grown` bytes since `ck` first appeared. Only the
    files' existence and size are read while the tool runs, never their
    contents: the tool renames each checkpoint over the last one.
    Returns (seconds until the kill, whether it was still running, the
    step the checkpoint holds or None if there is none)."""
    ck = Path(ck)
    for p in (ck, records):
        if p is not None and Path(p).exists():
            Path(p).unlink()
    t0 = time.monotonic()
    proc = subprocess.Popen([tool.exe] + [str(a) for a in argv] +
                            ["--checkpoint", str(ck)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, env=env)
    base = None
    while proc.poll() is None:
        t = time.monotonic() - t0
        if t >= bound or (wait is not None and t >= wait):
            break
        if wait is None and ck.exists():
            if records is None:
                break
            size = Path(records).stat().st_size
            if base is None:
                base = size
            elif size > base + grown:
                break
        time.sleep(0.01)
    elapsed = time.monotonic() - t0
    alive = proc.poll() is None
    proc.kill()
    proc.wait()
    return elapsed, alive, (_at_of(ck)[0] if ck.exists() else None)


_CKPT_LOG = re.compile(r"cft-orbits: checkpoint at step (\d+), sample (\d+)")


def _clock_log(stderr):
    """The (step, sample) of every checkpoint a run under
    CFT_ORBITS_VIRTUAL_CLOCK logged, in order."""
    return [(int(a), int(b)) for a, b in _CKPT_LOG.findall(stderr)]


def env_with(**kv):
    return dict(os.environ, **kv)


def check_segments(tool, tmp):
    """[6b] --engine segments. The engine comparisons, the long
    segments, the stop points, the relays, where checkpoints fall, the
    interruption, a killed run's records, the records file laid out by
    hand, the order of a checkpoint and its records, the loader's limit
    and the golden comparison each carry a control that must make them
    fail, run every time, and its failure is asserted - a comparison
    that has never been seen to fail is not a gate. Eleven carry none
    of their own - the census, the batch-size comparison, the
    comparisons at the three narrower formats, the relay without
    --records, the run with no instrument set, the image cache's key,
    the rename under a stat() poll, the rename held open, the second
    writer, the fresh run into a pipe, and the fresh run into a file
    that says it holds 0 bytes - and were watched failing only under
    one-off planted defects; the refusals are their own kind, a case
    each that must be refused by name. docs/ORBITS.md says what holds
    each."""
    print("\n[6b] --engine segments: the ensemble state through the "
          "scratch block")
    env_nc = env_with(CFT_ORBITS_NEGATIVE_CONTROL="transpose")

    # --- the two engines, on both problems and both schemes ----------
    # Each is also run with the loader's limit lowered to 13 steps
    # (CFT_ORBITS_SEGMENT_LIMIT, a test instrument): the real limit is
    # 2^32-1 steps or 2^40 instructions - hours - so the split it makes
    # is otherwise never reached. 13 divides neither interval (96, 36),
    # so every interval ends on a short piece; the run count shows the
    # split happened.
    cases = (("kepler", "leapfrog", ["--periods", 2,
                                     "--steps-per-period", 96]),
             ("kepler", "yoshida4", ["--periods", 2,
                                     "--steps-per-period", 96]),
             ("outer", "leapfrog", ["--years", 4, "--days", 10]),
             ("outer", "yoshida4", ["--years", 4, "--days", 10]))
    limit = 13
    env_lim = env_with(CFT_ORBITS_SEGMENT_LIMIT=str(limit))
    for problem, scheme, extra in cases:
        argv = ["--problem", problem, "--scheme", scheme, "--format",
                "fp256", "--members", 5, "--rsqrt", "newton", "--quiet",
                *extra]
        got = {}
        for eng, batch in (("loop", 5), ("segments", 3)):
            ck = Path(tmp) / ("s-%s-%s-%s.ckpt" % (problem, scheme, eng))
            rc = Path(tmp) / ("s-%s-%s-%s.txt" % (problem, scheme, eng))
            tool.run(*argv, "--engine", eng, "--batch", batch,
                     "--checkpoint", ck, "--records", rc)
            got[eng] = (ck.read_bytes(), rc.read_bytes())
        nrec = got["loop"][1].count(b"\n")
        check(got["loop"] == got["segments"] and nrec > 0,
              "%s, %s: segments (batch 3 of 5) and the host loop end on "
              "byte-identical checkpoints and %d byte-identical records"
              % (problem, scheme, nrec),
              "%s, %s: --engine segments and the host loop disagree"
              % (problem, scheme))
        # the loader's limit, lowered: no --checkpoint, so nothing but
        # the sample boundary and the limit sizes a segment
        rs = Path(tmp) / ("s-%s-%s-split.txt" % (problem, scheme))
        proc = tool.run(*argv, "--engine", "segments", "--batch", 3,
                        "--records", rs, "--csv", env=env_lim,
                        expect_ok=False)
        row = _csv_row(proc.stdout) if proc.returncode == 0 else {}
        st = tool.setup(*argv)
        want_runs = 2 * st["samples"] * -(-st["stride"] // limit)
        check(proc.returncode == 0 and
              "TEST INSTRUMENT ACTIVE" in proc.stderr and
              rs.exists() and rs.read_bytes() == got["loop"][1] and
              int(row.get("seg_runs", -1)) == want_runs,
              "%s, %s: split at a loader limit of %d steps - %d runs, "
              "every %d-step interval in %d pieces - and the records are "
              "the host loop's, byte for byte"
              % (problem, scheme, limit, want_runs, st["stride"],
                 -(-st["stride"] // limit)),
              "%s, %s: split at a loader limit of %d steps, segments "
              "disagree with the host loop or did not split (exit %d, %s "
              "runs where the split makes %d) %s"
              % (problem, scheme, limit, proc.returncode,
                 row.get("seg_runs"), want_runs, proc.stderr.strip()[-160:]))
        if (problem, scheme) == ("outer", "yoshida4"):
            # the same split, transposed: the comparison must see it
            proc = tool.run(*argv, "--engine", "segments", "--batch", 3,
                            "--records", rs,
                            env=env_with(CFT_ORBITS_SEGMENT_LIMIT=str(limit),
                                         CFT_ORBITS_NEGATIVE_CONTROL=
                                         "transpose"), expect_ok=False)
            check(proc.returncode == 0 and rs.exists() and
                  rs.read_bytes() != got["loop"][1],
                  "%s, %s: NEGATIVE CONTROL: split and transposed "
                  "(=transpose), the same comparison FAILS" % (problem, scheme),
                  "%s, %s: NEGATIVE CONTROL FAILED TO FAIL: a transposed "
                  "split run matched the host loop (exit %d)"
                  % (problem, scheme, proc.returncode))

    # --- the other three formats ---------------------------------------
    # The Newton pass count is the format's, so a segment built with
    # binary256's passes at every format matches the loop engine at
    # binary256 and nowhere else - one configuration of each other
    # format runs here. The arithmetic count the census implies is held
    # to the loop engine's own count at each, a second statement of the
    # census that shares none of its derivation.
    for fmtname, problem, scheme, extra in (
            ("fp32", "kepler", "yoshida4", ["--periods", 2,
                                            "--steps-per-period", 96]),
            ("fp64", "outer", "leapfrog", ["--years", 2, "--days", 10]),
            ("fp128", "outer", "yoshida4", ["--years", 2, "--days", 10])):
        argv = ["--problem", problem, "--scheme", scheme, "--format",
                fmtname, "--members", 5, "--rsqrt", "newton", "--quiet",
                *extra]
        got, ops = {}, {}
        for eng, batch in (("loop", 5), ("segments", 3)):
            ck = Path(tmp) / ("f-%s-%s.ckpt" % (fmtname, eng))
            rc = Path(tmp) / ("f-%s-%s.txt" % (fmtname, eng))
            proc = tool.run(*argv, "--engine", eng, "--batch", batch,
                            "--checkpoint", ck, "--records", rc, "--csv")
            got[eng] = (ck.read_bytes(), rc.read_bytes())
            ops[eng] = int(_csv_row(proc.stdout)["elemops"])
        nrec = got["loop"][1].count(b"\n")
        check(got["loop"] == got["segments"] and nrec > 0 and
              ops["loop"] == ops["segments"] > 0,
              "%s, %s, %s: segments and the host loop end on byte-identical "
              "checkpoints and %d records, and issue the same %d operations"
              % (fmtname, problem, scheme, nrec, ops["loop"]),
              "%s, %s, %s: segments and the host loop disagree (operations "
              "%d against %d)" % (fmtname, problem, scheme, ops["segments"],
                                  ops["loop"]))

    # --- where a stopped run stops --------------------------------------
    # A relay converges on the same end state however its legs split, so
    # it cannot see a leg that stopped one step late. A single stopped
    # run's checkpoint can: it records the step it stopped at. Stride 96,
    # so 95, 96 and 97 sit either side of a sample boundary.
    sargv = ["--problem", "kepler", "--scheme", "leapfrog", "--format",
             "fp256", "--members", 5, "--rsqrt", "newton", "--quiet",
             "--periods", 2, "--steps-per-period", 96, "--batch", 3]
    stops, blob = (1, 13, 95, 96, 97), {}
    env_late = env_with(CFT_ORBITS_NEGATIVE_CONTROL="late-stop")

    def stops_held(eng_env):
        held = []
        for stop in stops:
            ck = Path(tmp) / ("stop-%d-seg.ckpt" % stop)
            if ck.exists():
                ck.unlink()
            proc = tool.run(*sargv, "--engine", "segments",
                            "--stop-after-steps", stop, "--checkpoint", ck,
                            env=eng_env, expect_ok=False)
            if (proc.returncode == 0 and ck.exists() and
                    ck.read_bytes() == blob[stop] and _at_of(ck)[0] == stop):
                held.append(stop)
        return held

    for stop in stops:
        ck = Path(tmp) / ("stop-%d-loop.ckpt" % stop)
        tool.run(*sargv, "--engine", "loop", "--stop-after-steps", stop,
                 "--checkpoint", ck)
        blob[stop] = ck.read_bytes()
    held = stops_held(None)
    check(held == list(stops),
          "stopped after %s steps, segments stop where the host loop does, "
          "on byte-identical checkpoints at the step asked for"
          % ", ".join(map(str, stops)),
          "a stopped segments run is not where the host loop's is (held at "
          "%s of %s)" % (held, list(stops)))
    # The control: segments that run one step past the stop. A run at 1
    # stops on time anyway - with a checkpoint named, a run's first
    # segment is one step, which times the rate - and so does one at 96,
    # the sample boundary, which ends a segment of its own accord; at 13,
    # 95 and 97 a segment runs past the stop, and the checkpoint's step
    # clause and its bytes must both see it.
    late = stops_held(env_late)
    check(late == [1, 96],
          "NEGATIVE CONTROL: with segments running a step past the stop "
          "(=late-stop), the comparison FAILS at 13, 95 and 97 - where a "
          "segment, not the first step or a sample boundary, ends the run",
          "NEGATIVE CONTROL: with segments running a step past the stop, "
          "the comparison held at %s, not only at [1, 96]" % late)
    for problem, scheme, extra in (cases[0], cases[3]):
        common = ["--problem", problem, "--scheme", scheme, "--format",
                  "fp256", "--members", 5, "--rsqrt", "newton", *extra]
        st = tool.setup(*common)
        row = tool.csv(*common, "--engine", "segments", "--batch", 3)
        nw, nb, nd, nsub = st["newton"], st["bodies"], st["dims"], st["nsub"]
        ncomp, inv = nb * nd, 1 + 4 * nw + 3      # seed, passes, y^3 * K
        if problem == "kepler":
            alu = nsub * (2 * ncomp + 2 + inv + 2)
            ctl = nsub * (2 * ncomp + 2 * 2)
        else:
            pairs = nb * (nb - 1) // 2
            per_pair = nd + 1 + (nd - 2) + 1 + inv + 1 + nd + 1 + nd
            alu = nsub * (2 * ncomp + pairs * per_pair)
            ctl = nsub * (2 * ncomp + pairs * 4 * nd)
        runs = st["samples"] * 2                  # 5 members, batch 3
        good = (int(row["seg_alu_step"]) == alu and
                int(row["seg_ctl_step"]) == ctl and
                int(row["seg_slots"]) == 2 * ncomp and
                int(row["seg_runs"]) == runs)
        check(good,
              "%s, %s: the census is the structure's - %d ALU and %d control "
              "codes a lane-step, %d scratch slots, %d runs (%d samples x 2 "
              "chunks), derived here from %d Newton passes"
              % (problem, scheme, alu, ctl, 2 * ncomp, runs, st["samples"],
                 nw),
              "%s, %s: the tool reports %s ALU / %s control / %s slots / %s "
              "runs; the structure says %d / %d / %d / %d"
              % (problem, scheme, row["seg_alu_step"], row["seg_ctl_step"],
                 row["seg_slots"], row["seg_runs"], alu, ctl, 2 * ncomp, runs))

    # --- its own batch independence ------------------------------------
    base = ["--problem", "kepler", "--format", "fp256", "--members", 8,
            "--periods", 2, "--steps-per-period", 96, "--rsqrt", "newton",
            "--engine", "segments", "--quiet"]
    # A --batch far past --members is legal and means one chunk of all of
    # them; buffers sized by the batch rather than the chunk asked for
    # ~128 TB at 10^12 and died "out of memory" where the loop ran.
    blobs, died = [], []
    for batch in (8, 3, 1, 10 ** 12):
        path = Path(tmp) / ("s-bs-%d.ckpt" % batch)
        proc = tool.run(*base, "--batch", batch, "--checkpoint", path,
                        expect_ok=False)
        if proc.returncode:
            died.append("batch %d: exit %d, %s" % (
                batch, proc.returncode, proc.stderr.strip()[-120:]))
            blobs.append(None)
        else:
            blobs.append(path.read_bytes())
    check(not died and blobs[0] == blobs[1] == blobs[2] == blobs[3],
          "segments at batch 8, 3, 1 and 10^12 (past the 8 members) end on "
          "byte-identical checkpoints",
          "the segments engine's checkpoints differ across batch sizes%s"
          % ("" if not died else " - " + "; ".join(died)))

    # --- resumed in pieces, alternating engines, the outer system -----
    # The case the old program engine could not run at all: thirty
    # values a lane, entered from a checkpoint either engine wrote. 37
    # does not divide the 36-step sample interval, so most pieces stop
    # part way through one.
    rargv = ["--problem", "outer", "--format", "fp256", "--members", 4,
             "--years", 4, "--days", 10, "--rsqrt", "newton", "--quiet",
             "--batch", 3]
    whole_ck, whole_rc = Path(tmp) / "s-whole.ckpt", Path(tmp) / "s-whole.txt"
    tool.run(*rargv, "--engine", "loop", "--checkpoint", whole_ck,
             "--records", whole_rc)
    total = _at_of(whole_ck)[0]
    for label, engines in (("segments alone", ("segments",)),
                           ("loop and segments in turn",
                            ("segments", "loop"))):
        ck = Path(tmp) / ("s-piece-%d.ckpt" % len(engines))
        rc = Path(tmp) / ("s-piece-%d.txt" % len(engines))
        rounds, midway = _relay(tool, rargv, ck, rc, engines, 37, total)
        check(midway > 0 and rounds > 1 and
              ck.read_bytes() == whole_ck.read_bytes() and
              rc.read_bytes() == whole_rc.read_bytes(),
              "outer solar system, %s: stopped and resumed %d times (%d of "
              "them mid interval) and ends on the uninterrupted loop "
              "engine's checkpoint and records, byte for byte"
              % (label, rounds, midway),
              "outer solar system, %s: the resumed run differs from the "
              "uninterrupted one (%d rounds, %d mid interval)"
              % (label, rounds, midway))

    # --- the negative control: the comparisons above can fail ----------
    argv = ["--problem", "kepler", "--scheme", "leapfrog", "--format",
            "fp256", "--members", 5, "--rsqrt", "newton", "--quiet",
            "--periods", 2, "--steps-per-period", 96]
    lp, lr = Path(tmp) / "nc-loop.ckpt", Path(tmp) / "nc-loop.txt"
    sp, sr = Path(tmp) / "nc-seg.ckpt", Path(tmp) / "nc-seg.txt"
    tool.run(*argv, "--engine", "loop", "--checkpoint", lp, "--records", lr)
    proc = tool.run(*argv, "--engine", "segments", "--batch", 3,
                    "--checkpoint", sp, "--records", sr, env=env_nc)
    check("NEGATIVE CONTROL ACTIVE" in proc.stderr,
          "the control announces itself on stderr",
          "the negative control ran silently")
    check(lp.read_bytes() != sp.read_bytes() and
          lr.read_bytes() != sr.read_bytes(),
          "NEGATIVE CONTROL: with v_0 and v_1 packed into each other's "
          "scratch slots the engine comparison FAILS, so it can see a "
          "layout bug",
          "NEGATIVE CONTROL FAILED TO FAIL: a transposed scratch layout "
          "still matched the host loop")
    ck, rc = Path(tmp) / "nc-relay.ckpt", Path(tmp) / "nc-relay.txt"
    _relay(tool, rargv, ck, rc, ("segments", "loop"), 37, total,
           env_for={"segments": env_nc})
    check(ck.read_bytes() != whole_ck.read_bytes(),
          "NEGATIVE CONTROL: the alternating relay under the same control "
          "FAILS its comparison too",
          "NEGATIVE CONTROL FAILED TO FAIL: the relay matched with a "
          "transposed segment")

    # --- long segments ---------------------------------------------------
    # Every comparison above runs segments of at most 96 steps. Real runs
    # do not: the tool's DEFAULT kepler run is a segment a period, 1,024
    # steps, and a long sample interval that no checkpoint cuts is one
    # segment of all of it. Two of those against the host loop, byte for
    # byte - the second past 2^16 steps in ONE segment, which a trip
    # count kept to 16 bits would wrap - and each with the transpose
    # control, which must fail. With a checkpoint named, a run's first
    # segment is one step, which times the rate, so the run counts are
    # (samples + 1) and 2 a chunk: they show the segments were that long.
    for label, argv, batch, chunks, runs in (
            ("the default kepler run (fp256, a sample a period): "
             "1,024-step segments",
             ["--problem", "kepler", "--members", 4, "--periods", 2,
              "--rsqrt", "newton", "--quiet"], 3, 2, 3),
            ("fp64, one 100,000-step sample interval: a 99,999-step "
             "segment after the first",
             ["--problem", "kepler", "--format", "fp64", "--members", 2,
              "--steps", 100000, "--sample-every", 100000, "--rsqrt",
              "newton", "--quiet", "--checkpoint-interval", 1000000000],
             1, 2, 2)):
        got, rows, errs = {}, {}, []
        for key, eng, env in (("loop", "loop", None),
                              ("segments", "segments", None),
                              ("control", "segments", env_nc)):
            ck = Path(tmp) / ("long-%s.ckpt" % key)
            rc = Path(tmp) / ("long-%s.txt" % key)
            extra = [] if eng == "loop" else ["--batch", batch]
            proc = tool.run(*argv, "--engine", eng, *extra, "--checkpoint",
                            ck, "--records", rc, "--csv", env=env,
                            expect_ok=False)
            if proc.returncode:
                errs.append("%s: exit %d, %s" % (key, proc.returncode,
                                                  proc.stderr.strip()[-120:]))
                got[key], rows[key] = None, {}
            else:
                got[key] = (ck.read_bytes(), rc.read_bytes())
                rows[key] = _csv_row(proc.stdout)
        nrec = got["loop"][1].count(b"\n") if got["loop"] else 0
        want = chunks * runs
        check(not errs and got["loop"] == got["segments"] and nrec > 0 and
              int(rows["segments"].get("seg_runs", -1)) == want,
              "%s: %d runs, and the host loop's checkpoint and %d records, "
              "byte for byte" % (label, want, nrec),
              "%s: segments and the host loop disagree, or the segments "
              "were not that long (%s runs, %d expected) %s"
              % (label, rows["segments"].get("seg_runs"), want,
                 "; ".join(errs)))
        check(got["control"] is not None and got["control"] != got["loop"],
              "%s: NEGATIVE CONTROL: transposed (=transpose), the same "
              "comparison FAILS" % label.split(":")[0],
              "%s: NEGATIVE CONTROL FAILED TO FAIL: a transposed segments "
              "run matched the host loop" % label.split(":")[0])

    # --- the image cache, keyed by the whole length ----------------------
    # seg_run keeps the last eight images by segment length. A key that
    # kept only some bits of the length would hand one length another's
    # image: cut to 8 bits, a run's 257-step segment ran the 1-step image
    # and ended on the wrong checkpoint and records - with the whole gate
    # green (verifier-V6's V6G). So a run whose two segment lengths share
    # their low sixteen bits, and so collide in any key cut to 16 bits or
    # fewer: 65,538 steps in one sample interval, a checkpoint named (the
    # first segment is one step, which times the rate) and an interval too
    # long to cut the rest - segments of 1 and 65,537 steps, two images.
    cargv = ["--problem", "kepler", "--format", "fp64", "--members", 1,
             "--steps", 65538, "--sample-every", 65538, "--rsqrt", "newton",
             "--quiet", "--checkpoint-interval", 1000000000]
    got, row = {}, {}
    for eng in ("loop", "segments"):
        ck = Path(tmp) / ("key-%s.ckpt" % eng)
        rc = Path(tmp) / ("key-%s.txt" % eng)
        proc = tool.run(*cargv, "--engine", eng, "--checkpoint", ck,
                        "--records", rc, "--csv", expect_ok=False)
        got[eng] = ((ck.read_bytes(), rc.read_bytes())
                    if proc.returncode == 0 else None)
        if eng == "segments" and proc.returncode == 0:
            row = _csv_row(proc.stdout)
    check(got["loop"] is not None and got["segments"] == got["loop"] and
          row.get("seg_runs") == "2" and row.get("seg_loads") == "2",
          "segments of 1 and 65,537 steps - one length in any key cut to 16 "
          "bits - run two images, and end on the host loop's checkpoint and "
          "records, byte for byte",
          "segments of 1 and 65,537 steps: %s runs of %s images (2 of 2 "
          "wanted), and %s the host loop's bytes"
          % (row.get("seg_runs"), row.get("seg_loads"),
             "equal to" if got["segments"] == got["loop"] else "NOT"))

    # --- where checkpoints fall -----------------------------------------
    # An interruption costs about one --checkpoint-interval only if a
    # checkpoint is written about one interval after the last. The loop
    # engine reads the clock after every step, so it writes one at the
    # step an interval has passed. A segment is sized to END when the
    # next checkpoint is due, so at a steady rate segments must write
    # theirs at the SAME steps. A real clock cannot show that - it
    # measures this machine's load - so these run under
    # CFT_ORBITS_VIRTUAL_CLOCK (2^-10 s a step, an interval of exactly
    # 100 steps, every checkpoint logged), in three regimes: a sample
    # interval of many checkpoint intervals, sample intervals a little
    # longer than one (127 steps), and much shorter ones (10). Segments
    # sized to a whole interval rather than to the time left wrote theirs
    # about two intervals apart (verifier-V1, 2026-09-25). The run count
    # bounds the pieces: a binary decomposition of each interval, eight
    # at most for 100 steps, and one more a sample boundary. The pieces
    # recur from one interval to the next, and each length's image is
    # built and loaded once (seg_run keeps eight): with no sample
    # boundary to cut them, the lengths are 1 (the first step, which
    # times the rate) and the binary decompositions of the first
    # interval's other 99 steps and of 100 - five, so five loads. The
    # 127-step regime needs more images than the eight slots (17 loads
    # for 43 runs), so it evicts, and each regime's last checkpoint is
    # also held to the host loop's byte for byte: an image run for the
    # wrong length ends elsewhere, whether or not a checkpoint falls
    # where it shows (verifier-V6's V6E, a slot keeping its old key over
    # a new image, was caught before only where a real-clock run happened
    # to meet it).
    vargv = ["--problem", "kepler", "--format", "fp64", "--members", 2,
             "--rsqrt", "newton", "--csv", "--quiet",
             "--checkpoint-interval", "0.09765625"]
    env_vc = env_with(CFT_ORBITS_VIRTUAL_CLOCK="0.0009765625")
    env_vcu = env_with(CFT_ORBITS_VIRTUAL_CLOCK="0.0009765625",
                       CFT_ORBITS_NEGATIVE_CONTROL="uncapped")
    regimes = (("a 1,000-step sample interval", 1000, 1000),
               ("127-step sample intervals", 1016, 127),
               ("10-step sample intervals", 1000, 10))

    def pieces(n):
        return {1 << b for b in range(n.bit_length()) if n >> b & 1}

    for label, nsteps, every in regimes:
        logs, ends, runs, loads, bad = {}, {}, None, None, []
        for key, eng, env in (("loop", "loop", env_vc),
                              ("segments", "segments", env_vc),
                              ("control", "segments", env_vcu)):
            if key == "control" and every < 100:
                continue            # sample-bounded already: nothing to cut
            ck = Path(tmp) / ("vc-%s.ckpt" % key)
            if ck.exists():
                ck.unlink()
            proc = tool.run(*vargv, "--steps", nsteps, "--sample-every",
                            every, "--engine", eng, "--checkpoint", ck,
                            env=env, expect_ok=False)
            if proc.returncode or "TEST INSTRUMENT ACTIVE" not in proc.stderr:
                bad.append("%s: exit %d, %s" % (key, proc.returncode,
                                                 proc.stderr.strip()[-120:]))
            logs[key] = _clock_log(proc.stderr)
            ends[key] = ck.read_bytes() if ck.exists() else None
            if key == "segments" and not proc.returncode:
                row = _csv_row(proc.stdout)
                runs, loads = int(row["seg_runs"]), int(row["seg_loads"])
        L = logs["loop"]
        steps = [s for s, _ in L[:-1]]       # the last is the end of run
        bound = 8 * (nsteps // 100) + nsteps // every + 1
        want_loads = (len({1} | pieces(99) | pieces(100))
                      if every == nsteps else None)
        same_end = ends["loop"] is not None and ends["segments"] == ends["loop"]
        check(not bad and L and logs["segments"] == L and same_end and
              steps == list(range(100, nsteps + 1, 100)) and
              runs is not None and runs <= bound and
              loads < runs and (want_loads is None or loads == want_loads),
              "%s, under a steady clock: segments checkpoint at exactly the "
              "host loop's steps - every 100, one interval - and end on its "
              "checkpoint byte for byte, in %d runs (at most %d) of %d "
              "images%s"
              % (label, runs or 0, bound, loads or 0,
                 "" if want_loads is None else
                 ", one a length (%d lengths)" % want_loads),
              "%s, under a steady clock: segments checkpoint at %s, the host "
              "loop at %s, in %s runs (at most %d) of %s images (%s wanted); "
              "the last checkpoint %s the host loop's %s" % (
                  label, [s for s, _ in logs["segments"]][:8], steps[:8],
                  runs, bound, loads,
                  want_loads if want_loads else "fewer than the runs",
                  "IS" if same_end else "is NOT", "; ".join(bad)))
        if "control" in logs:
            check(logs["control"] != L,
                  "%s: NEGATIVE CONTROL: uncapped, segments checkpoint at "
                  "%s instead - the comparison FAILS"
                  % (label, [s for s, _ in logs["control"]][:4]),
                  "%s: NEGATIVE CONTROL FAILED TO FAIL: uncapped segments "
                  "checkpointed where the host loop does" % label)

    # --- an interruption, on the real clock -----------------------------
    # A sample interval of 30,000 steps - minutes of work - and a
    # one-second checkpoint interval: the run is watched until its first
    # checkpoint appears (60 s at most, however busy the machine) and
    # then killed. It must hold a step part way through the interval, as
    # the host loop's would. The control (uncapped: the first segment is
    # the whole interval) is given three times as long, and at least 3 s,
    # and must have written none.
    iargv = ["--problem", "outer", "--scheme", "yoshida4", "--format",
             "fp256", "--members", 32, "--rsqrt", "newton", "--quiet",
             "--years", 1000, "--days", 10, "--sample-every", 30000,
             "--checkpoint-interval", 1, "--engine", "segments"]
    t_ck, alive, at = _run_until(tool, iargv, Path(tmp) / "kill.ckpt")
    check(alive and at is not None and 0 < at < 30000,
          "with --checkpoint-interval 1 and a 30,000-step sample interval, "
          "segments had written a checkpoint %.1f s in, at step %s - part "
          "way through the interval, as the host loop does" % (t_ck, at),
          "a segments run in a 30,000-step interval had %s after %.1f s "
          "(still running: %s)" % ("no checkpoint" if at is None else
                                   "a checkpoint at step %d" % at, t_ck,
                                   alive))
    env_unc = env_with(CFT_ORBITS_NEGATIVE_CONTROL="uncapped")
    t_nc, alive, at = _run_until(tool, iargv, Path(tmp) / "kill-nc.ckpt",
                                 env=env_unc, wait=max(3.0, 3 * t_ck))
    check(alive and at is None,
          "NEGATIVE CONTROL: uncapped, the same run had written no "
          "checkpoint %.1f s in - the whole interval would be lost, so the "
          "check above can see it" % t_nc,
          "NEGATIVE CONTROL FAILED TO FAIL: uncapped segments had a "
          "checkpoint at step %s after %.1f s (still running: %s)"
          % (at, t_nc, alive))

    # --- a killed run's records -----------------------------------------
    # Records go through stdio and a checkpoint is written between
    # samples, so a kill leaves the records file out of step with the
    # checkpoint on disk. Two ways, each on both engines, each resumed by
    # the other engine and required to finish on the uninterrupted run's
    # checkpoint and records:
    #  - killed the moment the first checkpoint appears, with the next
    #    sample far off (1,500-step intervals, 0.1 s checkpoints): the
    #    tail of sample 0's records is still in the stdio buffer then,
    #    so unless it was handed over before the checkpoint was written
    #    the file is BEHIND the checkpoint and cannot be resumed. The
    #    kill must find the file exactly at the checkpoint - landing
    #    before the next sample is what makes that window the one tested
    #    - and is repeated until it does, five times at most;
    #  - killed once the file has grown 8 KB past the first checkpoint
    #    (150-step intervals, 0.2 s checkpoints): the file is AHEAD of
    #    the checkpoint, usually ending in half a line, and --resume must
    #    cut it back. The killed state, copied, is resumed again under
    #    =append (the resume before 2026-09-25), which must FAIL. A kill
    #    that left the file exactly at the checkpoint cannot show that,
    #    so that kill is repeated until one does not - five at most.
    env_app = env_with(CFT_ORBITS_NEGATIVE_CONTROL="append")
    kstyles = (
        ("at its first checkpoint", None, False,
         ["--problem", "kepler", "--format", "fp256", "--members", 20,
          "--rsqrt", "newton", "--steps", 3000, "--sample-every", 1500,
          "--checkpoint-interval", 0.1, "--quiet"]),
        ("8 KB past its first checkpoint", 8192, True,
         ["--problem", "kepler", "--format", "fp256", "--members", 20,
          "--rsqrt", "newton", "--steps", 3000, "--sample-every", 150,
          "--checkpoint-interval", 0.2, "--quiet"]))
    for style, grown, wants_ahead, kargv in kstyles:
        kw_ck, kw_rc = Path(tmp) / "k-whole.ckpt", Path(tmp) / "k-whole.txt"
        tool.run(*kargv, "--engine", "loop", "--checkpoint", kw_ck,
                 "--records", kw_rc)
        whole = (kw_ck.read_bytes(), kw_rc.read_bytes())
        for kill_eng, res_eng in (("loop", "segments"),
                                  ("segments", "loop")):
            ck = Path(tmp) / ("k-%s.ckpt" % kill_eng)
            rc = Path(tmp) / ("k-%s.txt" % kill_eng)
            cck, crc = Path(tmp) / "k-ctl.ckpt", Path(tmp) / "k-ctl.txt"
            seen, resumed, control, landed = [], [], None, False
            for _attempt in range(5):
                _t, alive, at = _run_until(
                    tool, kargv + ["--engine", kill_eng, "--records", rc],
                    ck, records=rc if grown else None, grown=grown or 0)
                n_ck = _field_of(ck, "recbytes") if at is not None else None
                killed = rc.read_bytes()
                seen.append("%d/%s" % (len(killed), n_ck))
                if not alive or n_ck is None:
                    resumed.append(False)
                    break
                shutil.copyfile(ck, cck)
                shutil.copyfile(rc, crc)
                proc = tool.run(*kargv, "--engine", res_eng, "--checkpoint",
                                ck, "--records", rc, "--resume",
                                expect_ok=False)
                resumed.append(proc.returncode == 0 and
                               (ck.read_bytes(), rc.read_bytes()) == whole)
                if not resumed[-1]:
                    seen[-1] += " (%s)" % proc.stderr.strip()[-100:]
                if not wants_ahead and len(killed) == n_ck:
                    landed = True
                    break
                if wants_ahead and len(killed) > n_ck:
                    landed = True
                    proc = tool.run(*kargv, "--engine", res_eng,
                                    "--checkpoint", cck, "--records", crc,
                                    "--resume", env=env_app,
                                    expect_ok=False)
                    control = (proc.returncode == 0 and
                               "NEGATIVE CONTROL ACTIVE" in proc.stderr and
                               crc.read_bytes() != whole[1])
                    break
            check(resumed and all(resumed) and landed,
                  "killed on %s %s (file/checkpoint bytes %s), resumed by "
                  "%s: the checkpoint and all %d records are the "
                  "uninterrupted run's, byte for byte"
                  % (kill_eng, style, ", ".join(seen), res_eng,
                     whole[1].count(b"\n")),
                  "killed on %s %s (file/checkpoint bytes %s), resumed by "
                  "%s: not the uninterrupted run's checkpoint and records, "
                  "or no kill landed %s"
                  % (kill_eng, style, ", ".join(seen), res_eng,
                     "ahead of the checkpoint" if wants_ahead else
                     "with the file at the checkpoint"))
            if not wants_ahead:
                continue
            check(control is True,
                  "killed on %s: NEGATIVE CONTROL: the same killed state "
                  "resumed without cutting the file back (=append) FAILS - "
                  "its records are not the run's" % kill_eng,
                  "killed on %s: NEGATIVE CONTROL %s (file/checkpoint bytes "
                  "%s)" % (kill_eng, "FAILED TO FAIL: an appending resume "
                           "matched the uninterrupted records"
                           if control is False else "not judged: no kill "
                           "left the file ahead of its checkpoint",
                           ", ".join(seen)))

    # --- the records file a resume is handed ----------------------------
    # The same, laid out exactly rather than by a kill: a run stopped at
    # step 37 closes its records at the checkpoint's length, and the
    # files are then given what a kill leaves - the next sample's records
    # and half a line - or what no kill can: a file cut short, one byte
    # changed, none at all, a checkpoint of the old version or without its
    # recbytes line. The first must resume to the uninterrupted run (and
    # fail under =append); every other must be refused by name with both
    # files left as they were.
    rargv5 = ["--problem", "kepler", "--scheme", "leapfrog", "--format",
              "fp256", "--members", 5, "--rsqrt", "newton", "--quiet",
              "--periods", 2, "--steps-per-period", 96]
    full = (Path(tmp) / "s-kepler-leapfrog-loop.ckpt").read_bytes(), \
        (Path(tmp) / "s-kepler-leapfrog-loop.txt").read_bytes()
    sck, src = Path(tmp) / "r-stop.ckpt", Path(tmp) / "r-stop.txt"
    tool.run(*rargv5, "--engine", "loop", "--stop-after-steps", 37,
             "--checkpoint", sck, "--records", src)
    stop_ck, stop_rc = sck.read_bytes(), src.read_bytes()
    nb = _field_of(sck, "recbytes")
    check(nb == len(stop_rc) and full[1].startswith(stop_rc) and
          _field_of(sck, "at") == 37,
          "a run stopped at step 37 leaves its records exactly as long as "
          "its checkpoint's recbytes (%d bytes), and they begin the "
          "uninterrupted run's" % len(stop_rc),
          "a run stopped at step 37: recbytes %s, records %d bytes, a prefix "
          "of the whole run's: %s" % (nb, len(stop_rc),
                                      full[1].startswith(stop_rc)))
    nxt = full[1][len(stop_rc):]
    cut = nxt.index(b"\n") + 1
    torn = stop_rc + nxt[:cut] + nxt[cut:cut + (nxt[cut:].index(b"\n") // 2)]

    def resume_with(records_bytes, ckpt_bytes=stop_ck, env=None):
        ck, rc = Path(tmp) / "r-case.ckpt", Path(tmp) / "r-case.txt"
        ck.write_bytes(ckpt_bytes)
        if rc.exists():
            rc.unlink()
        if records_bytes is not None:
            rc.write_bytes(records_bytes)
        proc = tool.run(*rargv5, "--engine", "segments", "--batch", 3,
                        "--checkpoint", ck, "--records", rc, "--resume",
                        env=env, expect_ok=False)
        return (proc, ck.read_bytes(),
                rc.read_bytes() if rc.exists() else None)

    proc, got_ck, got_rc = resume_with(torn)
    check(proc.returncode == 0 and (got_ck, got_rc) == full,
          "handed %d bytes more than its checkpoint accounts for, ending in "
          "half a line, --resume cuts the file back and finishes on the "
          "uninterrupted run's checkpoint and records" % (len(torn) - nb),
          "handed a records file ahead of its checkpoint, --resume ended "
          "elsewhere (exit %d) %s" % (proc.returncode,
                                      proc.stderr.strip()[-160:]))
    proc, _, got_rc = resume_with(torn, env=env_app)
    check(proc.returncode == 0 and got_rc != full[1],
          "NEGATIVE CONTROL: the same resume without the cut (=append) "
          "FAILS - its records are not the run's",
          "NEGATIVE CONTROL FAILED TO FAIL: an appending resume matched the "
          "uninterrupted records (exit %d)" % proc.returncode)
    def flipped(data, at):
        out = bytearray(data)
        out[at] = ord("7") if out[at] != ord("7") else ord("3")
        return bytes(out)

    old = stop_ck.replace(b"cft-orbits-checkpoint 2\n",
                          b"cft-orbits-checkpoint 1\n", 1)
    norec = b"".join(l for l in stop_ck.splitlines(True)
                     if not l.startswith(b"recbytes "))
    # another run of the same shape - its checkpoint would be accepted -
    # whose ensemble differs (a ladder of 2 ulps), so even its sample 0
    # is not this run's
    tool.run(*rargv5, "--engine", "loop", "--spread", 2, "--records",
             Path(tmp) / "r-other.txt")
    other = (Path(tmp) / "r-other.txt").read_bytes()
    hash_msg = "do not hash to the checkpoint's chain"
    refused, why = [], []
    # Files LONGER than the checkpoint's records whose first recbytes
    # bytes are wrong must be refused as surely as ones exactly that
    # long: the prefix is what is checked, whatever follows it.
    for what, rec, ckb, needle in (
            ("the file cut one byte short", stop_rc[:-1], stop_ck,
             "holds %d bytes and the checkpoint's records run to %d"
             % (nb - 1, nb)),
            ("one byte of the file changed", flipped(stop_rc, nb // 2),
             stop_ck, hash_msg),
            ("the whole run's records with a byte changed before recbytes",
             flipped(full[1], nb // 2), stop_ck, hash_msg),
            ("the whole run's records with CRLF line ends",
             full[1].replace(b"\n", b"\r\n"), stop_ck, hash_msg),
            ("another run's longer records (--spread 2, %d bytes)"
             % len(other), other, stop_ck, hash_msg),
            ("no records file at all", None, stop_ck,
             "there is no records file"),
            ("a version-1 checkpoint", stop_rc, old,
             "not a cft-orbits checkpoint of this version"),
            ("a checkpoint without its recbytes line", stop_rc, norec,
             "does not say how long its records are")):
        if rec is not None and rec is not stop_rc and len(rec) > nb and \
                rec[:nb] == stop_rc:
            why.append("%s: the case is not what it says" % what)
            continue
        proc, got_ck, got_rc = resume_with(rec, ckb)
        if (proc.returncode == 2 and needle in proc.stderr and
                got_ck == ckb and got_rc == rec):
            refused.append(what)
        else:
            why.append("%s: exit %d, %s" % (what, proc.returncode,
                                           proc.stderr.strip()[-120:]))
    check(not why,
          "--resume refuses, by name and touching neither file: %s"
          % "; ".join(refused),
          "--resume did not refuse by name, or touched a file: %s"
          % "; ".join(why))

    # --- the right records, which this process may not read -------------
    # A records file another process holds open with no sharing (Windows)
    # or that this user may not read (POSIX: its permissions taken away)
    # is not short and not another run's - c8a7d97 and 589cbc1 called it
    # "0 bytes ... cut short" all the same (verifier-V6). The refusal must
    # name what is wrong, touch neither file, and the resume must go
    # through once the file can be read again.
    lk_ck, lk_rc = Path(tmp) / "lk.ckpt", Path(tmp) / "lk.txt"
    lk_ck.write_bytes(stop_ck)
    lk_rc.write_bytes(stop_rc)
    blocked, release = None, None
    if os.name == "nt":
        import _winapi
        lk_h = _winapi.CreateFile(str(lk_rc), 0x80000000, 0, _winapi.NULL,
                                  _winapi.OPEN_EXISTING, 0, _winapi.NULL)
        blocked = "held open by another process with no sharing"
        release = lambda: _winapi.CloseHandle(lk_h)
    elif os.geteuid() != 0:
        os.chmod(lk_rc, 0)
        blocked = "with its read permission taken away"
        release = lambda: os.chmod(lk_rc, 0o644)
    if blocked is None:
        print("SKIP  --resume on a records file it may not read: this check "
              "runs as root, which no permission stops from reading a file")
    else:
        proc = tool.run(*rargv5, "--engine", "segments", "--batch", 3,
                        "--checkpoint", lk_ck, "--records", lk_rc,
                        "--resume", expect_ok=False)
        release()
        untouched = (lk_ck.read_bytes() == stop_ck and
                     lk_rc.read_bytes() == stop_rc)
        again = tool.run(*rargv5, "--engine", "segments", "--batch", 3,
                         "--checkpoint", lk_ck, "--records", lk_rc,
                         "--resume", expect_ok=False)
        check(proc.returncode == 2 and "could not be opened to be read back"
              in proc.stderr and "holds 0 bytes" not in proc.stderr and
              untouched and again.returncode == 0 and
              (lk_ck.read_bytes(), lk_rc.read_bytes()) == full,
              "the right records %s: --resume refused by name (\"could not "
              "be opened to be read back\"), both files untouched, and once "
              "it could be read the resume ended on the uninterrupted run"
              % blocked,
              "the right records %s: exit %d, %s; files untouched %s; the "
              "resume after, exit %d" % (blocked, proc.returncode,
                                         proc.stderr.strip()[-160:],
                                         untouched, again.returncode))

    # --- --records and --checkpoint naming one file ------------------------
    # The checkpoint is written beside its path and renamed over it at
    # every interval: on POSIX the records then went on into an unlinked
    # file and were lost, with exit 0; on Windows the run died 1.7 s in
    # blaming "another process" (verifier-V6, pre-existing). Refused by
    # name, before a byte of either file is cut. The same path, and the
    # checkpoint's .tmp as written, are told from the strings, before
    # anything is opened - so nothing may be created there. Two spellings
    # of one file are told by the file itself, on a fresh run from the
    # records file opened but not yet cut - so a checkpoint already there
    # must be left as it was (d56ecbe emptied it, and a leg that began
    # with no checkpoint could not see that: verifier-V6) - and that
    # holds for the .tmp under another spelling as for the checkpoint.
    same = Path(tmp) / "same.ckpt"
    stmp = Path(str(same) + ".tmp")
    dot = str(Path(tmp)) + os.sep + "." + os.sep  # not through pathlib,
    # which would fold the "." away
    why, refused = [], []
    for what, rcp, there, resume, says in (
            ("the same path, fresh", same, False, False, "same path"),
            ("the same path, fresh, a checkpoint there", same, True, False,
             "same path"),
            ("the .tmp, fresh", stmp, False, False, "same path"),
            ("one file under two names, fresh, a checkpoint there",
             dot + "same.ckpt", True, False, "two names"),
            ("the .tmp under another name, fresh, a checkpoint there",
             dot + "same.ckpt.tmp", True, False, "two names"),
            ("one file under two names, on --resume", dot + "same.ckpt",
             True, True, "two names")):
        for p in (same, stmp):
            if p.exists():
                p.unlink()
        if there:
            same.write_bytes(stop_ck)
        proc = tool.run(*rargv5, "--engine", "segments", "--checkpoint",
                        same, "--records", rcp,
                        *(["--resume"] if resume else []), expect_ok=False)
        if there:
            left = same.read_bytes() == stop_ck
            said_left = "the checkpoint %s" % ("untouched" if left else
                                               "CHANGED")
        else:
            left = not same.exists() and not stmp.exists()
            said_left = "nothing created" if left else "a file CREATED"
        if (proc.returncode == 2 and "--checkpoint" in proc.stderr and
                ("are the " + says if says == "same path" else
                 "one file under " + says) in proc.stderr and left):
            refused.append("%s (%s)" % (what, said_left))
        else:
            why.append("%s: exit %d, %s; %s" % (
                what, proc.returncode, proc.stderr.strip()[-110:], said_left))
    check(not why,
          "refused by name, --records and --checkpoint as one file: %s"
          % "; ".join(refused),
          "--records and --checkpoint as one file not refused by name, or "
          "a file changed: %s" % "; ".join(why))

    # --- records that are not a file -------------------------------------
    # A resume reads the records back and cuts them, which only a regular
    # file allows. Handed a pipe, a FIFO or a device, c8a7d97 read it -
    # and waited for ever on a pipe that nothing wrote, with no message
    # (verifier-V6). Each must be refused by name at once, the checkpoint
    # untouched. Every run here has 60 s, so a regression is a FAIL and
    # not a gate that never ends. A FRESH run into a pipe was never the
    # problem, and must still stream the run's records.
    def bounded(argv, **kw):
        try:
            return subprocess.run([tool.exe] + [str(a) for a in argv],
                                  capture_output=True, text=True,
                                  timeout=60, **kw)
        except subprocess.TimeoutExpired:
            return None

    pipes = []                  # (what, path) to refuse
    pipe_close = []
    if os.name == "nt":
        import _winapi
        pname = r"\\.\pipe\cft-orbits-check-%d" % os.getpid()
        ph = _winapi.CreateNamedPipe(pname, _winapi.PIPE_ACCESS_DUPLEX, 0,
                                     _winapi.PIPE_UNLIMITED_INSTANCES,
                                     65536, 65536, 0, _winapi.NULL)
        pipe_close.append(lambda: _winapi.CloseHandle(ph))
        pipes += [("a named pipe nothing writes (%s)" % pname, pname),
                  ("the NUL device", "NUL")]
    else:
        fifo = Path(tmp) / "records.fifo"
        os.mkfifo(fifo)
        pipes += [("a FIFO nothing writes", str(fifo)),
                  ("/dev/stdout, a pipe to this check", "/dev/stdout"),
                  ("/dev/null", "/dev/null")]
    refused, why = [], []
    for what, path in pipes:
        ck = Path(tmp) / "p-case.ckpt"
        ck.write_bytes(stop_ck)
        t0 = time.monotonic()
        proc = bounded(rargv5 + ["--engine", "segments", "--batch", 3,
                                 "--checkpoint", ck, "--records", path,
                                 "--resume"])
        if proc is None:
            why.append("%s: still running after 60 s - HUNG, killed" % what)
        elif (proc.returncode == 2 and "is not a regular file" in
              proc.stderr and ck.read_bytes() == stop_ck):
            refused.append("%s (%.2f s)" % (what, time.monotonic() - t0))
        else:
            why.append("%s: exit %d, %s" % (what, proc.returncode,
                                           proc.stderr.strip()[-120:]))
    for close in pipe_close:
        close()
    check(not why,
          "--resume --records refuses, by name, at once and with the "
          "checkpoint untouched: %s" % "; ".join(refused),
          "--resume --records into a pipe or a device: %s" % "; ".join(why))
    # the same kind of path on a fresh run: the records stream through it
    got, rdr = [], None
    if os.name == "nt":
        pname = r"\\.\pipe\cft-orbits-check-in-%d" % os.getpid()
        ph = _winapi.CreateNamedPipe(pname, _winapi.PIPE_ACCESS_INBOUND, 0,
                                     1, 65536, 65536, 0, _winapi.NULL)

        def drain():
            try:
                _winapi.ConnectNamedPipe(ph, False)
            except OSError:
                pass
            while True:
                try:
                    data, _err = _winapi.ReadFile(ph, 65536)
                except OSError:
                    break
                if not data:
                    break
                got.append(data)
        ppath = pname
    else:
        ppath = str(Path(tmp) / "records-in.fifo")
        os.mkfifo(ppath)

        def drain():
            with open(ppath, "rb") as f:
                got.append(f.read())
    rdr = threading.Thread(target=drain, daemon=True)
    rdr.start()
    proc = bounded(rargv5 + ["--engine", "segments", "--batch", 3,
                             "--checkpoint", Path(tmp) / "p-fresh.ckpt",
                             "--checkpoint-interval", 0, "--records", ppath])
    rdr.join(30)
    if os.name == "nt":
        _winapi.CloseHandle(ph)
    streamed = b"".join(got)
    check(proc is not None and proc.returncode == 0 and
          streamed == full[1],
          "a fresh run with --records %s and a checkpoint every step "
          "streams the run's %d bytes of records through it, as before"
          % ("a named pipe" if os.name == "nt" else "a FIFO", len(streamed)),
          "a fresh run into a pipe: %s, %d bytes through it where the run "
          "has %d" % ("HUNG" if proc is None else "exit %d" % proc.returncode,
                      len(streamed), len(full[1])))

    # --- a pipe the system calls an empty file ---------------------------
    # From Windows, the WSL share presents a Linux FIFO as a regular file
    # that says it holds 0 bytes, whatever is written to it, and refuses
    # to be cut ("the parameter is incorrect", measured 2026-09-27).
    # bc00d8d cut a fresh run's records file before writing to it, and so
    # refused a run into such a FIFO that had streamed until then
    # (verifier-V6, 2026-09-26). The gate does not open FIFOs through the
    # share - an open that finds no peer leaves a thread of the distro's
    # 9P server blocked, and enough of them hung the share on 2026-09-25 -
    # so CFT_ORBITS_SHARE_FIFO makes the records file what the share
    # makes of one. Without --checkpoint the run must write its records
    # as into any file; with a checkpoint every step, the length check
    # cannot tell such a file from one something else cut, and must stop
    # the run by name at its first checkpoint saying both and claiming
    # neither ("something else wrote to it", what c8a7d97 to bc00d8d
    # said, is a guess there), with no checkpoint written.
    env_sf = env_with(CFT_ORBITS_SHARE_FIFO="1")
    sfr, sfc = Path(tmp) / "sf.txt", Path(tmp) / "sf.ckpt"
    for p in (sfr, sfc):
        if p.exists():
            p.unlink()
    said = "TEST INSTRUMENT ACTIVE (CFT_ORBITS_SHARE_FIFO=1)"
    proc = tool.run(*rargv5, "--engine", "loop", "--records", sfr,
                    env=env_sf, expect_ok=False)
    lines = proc.stderr.strip().splitlines()
    check(proc.returncode == 0 and len(lines) == 1 and said in lines[0] and
          sfr.exists() and sfr.read_bytes() == full[1],
          "a fresh run into a file that says it holds 0 bytes and refuses a "
          "cut (CFT_ORBITS_SHARE_FIFO, what the WSL share makes of a Linux "
          "FIFO), no --checkpoint: exit 0 and the run's %d bytes of records, "
          "the file not cut" % len(full[1]),
          "a fresh run into a file that says it holds 0 bytes and refuses a "
          "cut: exit %d, %r; the records %s" % (
              proc.returncode, proc.stderr.strip()[-200:],
              "right" if sfr.exists() and sfr.read_bytes() == full[1]
              else "WRONG or none"))
    sfr.unlink()
    proc = tool.run(*rargv5, "--engine", "segments", "--records", sfr,
                    "--checkpoint", sfc, "--checkpoint-interval", 0,
                    env=env_sf, expect_ok=False)
    wrote = sfr.read_bytes() if sfr.exists() else b""
    check(proc.returncode == 2 and said in proc.stderr and
          "says it holds 0 bytes" in proc.stderr and
          "something else cut it, or it is a pipe the system presents as an "
          "empty file" in proc.stderr and
          "something else wrote to it" not in proc.stderr and
          not sfc.exists() and wrote and full[1].startswith(wrote),
          "the same with a checkpoint every step: stopped by name at the "
          "first, after %d bytes of records - \"%s\" - and no checkpoint "
          "written" % (len(wrote), (proc.stderr.strip().splitlines() or
                                    [""])[-1].replace("cft-orbits: ", "")),
          "a file that says it holds 0 bytes, with a checkpoint every step: "
          "exit %d, %r; %d bytes written; a checkpoint %s" % (
              proc.returncode, proc.stderr.strip()[-240:], len(wrote),
              "WRITTEN" if sfc.exists() else "not written"))

    # --- a records file the system will not cut -------------------------
    # A fresh run cuts its records file to nothing before writing; when
    # the system refuses, the refusal must name the step, the file and
    # the system's own reason, and leave the file as it was - bc00d8d
    # said only "cannot write the records file" (verifier-V6). Windows
    # will not cut a file another process has mapped (the gate maps it);
    # Linux will not shrink a memfd sealed against shrinking (the gate
    # makes one and hands it down, named /proc/self/fd/N).
    body = b"another file's bytes, which must be left as they are\n" * 64
    cut_proc, cut_left, cut_how = None, None, None
    if os.name == "nt":
        import mmap
        mf = Path(tmp) / "mapped.txt"
        mf.write_bytes(body)
        with open(mf, "r+b") as fh:
            mm = mmap.mmap(fh.fileno(), 0)
            try:
                cut_proc = tool.run(*rargv5, "--engine", "loop",
                                    "--records", mf, expect_ok=False)
            finally:
                mm.close()
        cut_left = mf.read_bytes() == body
        cut_how, cut_why = "another process has mapped", "Windows error 1224"
    else:
        try:
            import fcntl
        except ImportError:                             # pragma: no cover
            fcntl = None
        if (fcntl is not None and hasattr(os, "memfd_create") and
                hasattr(fcntl, "F_SEAL_SHRINK")):
            mfd = os.memfd_create("orbits-check-sealed", os.MFD_ALLOW_SEALING)
            try:
                os.write(mfd, body)
                fcntl.fcntl(mfd, fcntl.F_ADD_SEALS, fcntl.F_SEAL_SHRINK)
                cut_proc = subprocess.run(
                    [tool.exe] + [str(a) for a in rargv5] +
                    ["--engine", "loop", "--records",
                     "/proc/self/fd/%d" % mfd],
                    capture_output=True, text=True, pass_fds=(mfd,))
                cut_left = os.pread(mfd, len(body) + 4096, 0) == body
            finally:
                os.close(mfd)
            cut_how = "that is a memfd sealed against shrinking"
            cut_why = "Operation not permitted"
    if cut_proc is None:
        print("SKIP  a records file the system will not cut: neither a "
              "Windows mapping nor a Linux sealed memfd is to be had here")
    else:
        check(cut_proc.returncode == 2 and
              "could not empty the records file" in cut_proc.stderr and
              cut_why in cut_proc.stderr and cut_left,
              "a records file %s, which the system will not cut: refused by "
              "name - \"%s\" - and left as it was" % (
                  cut_how, (cut_proc.stderr.strip().splitlines() or
                            [""])[-1].replace("cft-orbits: ", "")),
              "a records file %s: exit %d, %r; the file %s" % (
                  cut_how, cut_proc.returncode,
                  cut_proc.stderr.strip()[-200:],
                  "left as it was" if cut_left else "CHANGED"))

    # --- the records beside a checkpoint, at the instant it appears ------
    # A checkpoint promises the records file holds at least recbytes
    # bytes, so the records must reach the system BEFORE the checkpoint
    # is renamed into place. A kill lands between the two by chance once
    # in thousands of tries, so the gate places one there:
    # CFT_ORBITS_DIE_AFTER_CHECKPOINT=N ends the process, as a kill
    # would, the moment its N-th checkpoint is in place. With a sample a
    # step and a checkpoint after every step, records are waiting in the
    # stdio buffer at checkpoints 1 and 4 (sample 0's, sample 2's). The
    # file must then be exactly as long as the checkpoint says, and the
    # other engine must resume it to the uninterrupted run. The control,
    # =flush-late, hands the records over just after the rename: the
    # file is then behind the checkpoint and the resume must refuse it.
    dargv = ["--problem", "kepler", "--format", "fp64", "--members", 2,
             "--rsqrt", "newton", "--steps", 12, "--sample-every", 1,
             "--checkpoint-interval", 0, "--quiet"]
    dw_ck, dw_rc = Path(tmp) / "d-whole.ckpt", Path(tmp) / "d-whole.txt"
    tool.run(*dargv, "--engine", "loop", "--checkpoint", dw_ck,
             "--records", dw_rc)
    dwhole = (dw_ck.read_bytes(), dw_rc.read_bytes())
    for kill_eng, res_eng in (("loop", "segments"), ("segments", "loop")):
        seen, ctl, bad = [], [], []
        ck, rc = Path(tmp) / "d-case.ckpt", Path(tmp) / "d-case.txt"
        for n in (1, 4):
            for label, extra_env in (("ordered", {}),
                                     ("control", {"CFT_ORBITS_NEGATIVE_"
                                                  "CONTROL": "flush-late"})):
                for p in (ck, rc):
                    if p.exists():
                        p.unlink()
                proc = tool.run(*dargv, "--engine", kill_eng, "--checkpoint",
                                ck, "--records", rc, expect_ok=False,
                                env=env_with(
                                    CFT_ORBITS_DIE_AFTER_CHECKPOINT=str(n),
                                    **extra_env))
                k = len(rc.read_bytes()) if rc.exists() else -1
                nck = _field_of(ck, "recbytes") if ck.exists() else None
                if proc.returncode != 9 or nck is None or \
                        "TEST INSTRUMENT ACTIVE" not in proc.stderr:
                    bad.append("%s after %d: exit %d, %s" % (
                        label, n, proc.returncode,
                        proc.stderr.strip()[-100:]))
                    continue
                res = tool.run(*dargv, "--engine", res_eng, "--checkpoint",
                               ck, "--records", rc, "--resume",
                               expect_ok=False)
                if label == "ordered":
                    seen.append("%d/%d" % (k, nck))
                    if not (k == nck and res.returncode == 0 and
                            (ck.read_bytes(), rc.read_bytes()) == dwhole):
                        bad.append("after checkpoint %d the file held %d "
                                   "of %d bytes; the resume: exit %d"
                                   % (n, k, nck, res.returncode))
                else:
                    ctl.append("%d/%d" % (k, nck))
                    if not (k < nck and res.returncode == 2 and
                            "holds %d bytes and the checkpoint's records "
                            "run to %d" % (k, nck) in res.stderr):
                        bad.append("NEGATIVE CONTROL FAILED TO FAIL after "
                                   "checkpoint %d: the file held %d of %d "
                                   "bytes, the resume exit %d"
                                   % (n, k, nck, res.returncode))
        check(not bad,
              "%s ended as a kill would the moment checkpoints 1 and 4 were "
              "in place: the records file exactly as long as each said "
              "(%s bytes), and %s resumed each to the uninterrupted run; "
              "NEGATIVE CONTROL: with the records handed over after the "
              "rename (=flush-late) the file was BEHIND (%s) and the resume "
              "refused it" % (kill_eng, ", ".join(seen), res_eng,
                              ", ".join(ctl)),
              "%s ended at a checkpoint's rename: %s" % (kill_eng,
                                                        "; ".join(bad)))

    # --- a resume without --records ---------------------------------------
    # The checkpoint counts the records whether or not --records writes
    # them, so a run stopped and resumed WITHOUT --records ends on the
    # same checkpoint as one that wrote them all: a relay of 37-step legs,
    # the engines in turn, none with --records, against the loop engine's
    # uninterrupted run with them.
    nck = Path(tmp) / "nr.ckpt"
    rounds = 0
    while rounds < 20:
        tool.run(*rargv5, "--engine", ("segments", "loop")[rounds % 2],
                 "--stop-after-steps", 37, "--checkpoint", nck,
                 *(["--resume"] if rounds else []))
        rounds += 1
        if _at_of(nck)[0] >= 192:
            break
    check(nck.read_bytes() == full[0],
          "stopped and resumed %d times by the two engines in turn, none "
          "with --records, the run ends on the checkpoint of the "
          "uninterrupted run that wrote them (recbytes %s)"
          % (rounds, _field_of(nck, "recbytes")),
          "a relay without --records ends on recbytes %s where the run with "
          "them says %s" % (_field_of(nck, "recbytes"),
                            _field_of(Path(tmp) /
                                      "s-kepler-leapfrog-loop.ckpt",
                                      "recbytes")))

    # --- a run with no instrument set -------------------------------------
    # The instruments must be off unless named: a run with none set says
    # nothing on stderr (no announcement, no checkpoint log), and its
    # clock is the wall's. A clock that counts steps - the test clock left
    # on, logging or not - reports the same time for the same steps
    # whatever each step costs; the wall does not. So the same 1,024 steps
    # at 1 member and at 16 must report times at least 4 apart (measured
    # about 15), each within its own process's lifetime. That lifetime is
    # taken with perf_counter, the clock the tool itself reads: Python's
    # monotonic() is GetTickCount64 on Windows, 15.6 ms a tick, and the
    # 1-member run is about that long - measured with it, the check failed
    # 12 of 280 times on a correct tool (verifier-V6, 2026-09-25). The
    # 1-member time is the least of three runs: a busy moment only makes a
    # run longer, and one 1-member run of 0.175 s against about 0.015 s
    # failed the ratio once in about 340 (verifier-V6). (The real loader
    # limit by default is held above: the 100,000-step interval runs as
    # 1 + 99,999, and =overlong is refused at the real ceiling.)
    targv = ["--problem", "kepler", "--format", "fp256", "--rsqrt",
             "newton", "--steps", 1024, "--sample-every", 256, "--quiet"]
    for eng in ("loop", "segments"):
        runs, said = [], []
        for m in (16, 1, 1, 1):
            t0 = time.perf_counter()
            proc = tool.run(*targv, "--members", m, "--engine", eng, "--csv",
                            "--checkpoint", Path(tmp) / "t.ckpt", "--records",
                            Path(tmp) / "t.txt")
            wall = time.perf_counter() - t0
            runs.append((m, float(_csv_row(proc.stdout)["seconds"]), wall))
            if proc.stderr:
                said.append(proc.stderr[:100])
        s16 = runs[0][1]
        s1 = min(s for m, s, _ in runs if m == 1)
        check(not said and s16 >= 4 * s1 and
              all(0 < s <= w for _, s, w in runs),
              "with no instrument set, %s says nothing on stderr and its "
              "clock is the wall's: the same 1,024 steps took %.3f s at 16 "
              "members and %.3f s at 1 (the least of %s), each run inside "
              "its process's lifetime" % (
                  eng, s16, s1,
                  ", ".join("%.3f" % s for m, s, _ in runs if m == 1)),
              "with no instrument set, %s wrote %r on stderr, or reported "
              "%.3f s at 16 members and %.3f s at 1 (runs of %s)" % (
                  eng, said, s16, s1,
                  ", ".join("%d members %.3f s in a %.3f s process" % r
                            for r in runs)))

    # --- a checkpoint renamed while something else looks at it ----------
    # On Windows another process that holds the checkpoint open for a
    # moment - a scanner, a sync agent, anything that stat()s it - makes
    # the rename over it fail; c8a7d97 died of it (verifier-V6: 8 runs
    # of 8 under a tight os.stat poll). The rename is now retried. A run
    # checkpointing after every step, polled by os.stat() as fast as this
    # process can, must finish on the unpolled run's checkpoint. (POSIX
    # renames over an open file, so there it holds by construction.)
    pargv = ["--problem", "kepler", "--format", "fp64", "--members", 2,
             "--rsqrt", "newton", "--steps", 400, "--sample-every", 50,
             "--checkpoint-interval", 0, "--quiet"]
    pref = Path(tmp) / "poll-ref.ckpt"
    tool.run(*pargv, "--engine", "loop", "--checkpoint", pref)
    for eng in ("loop", "segments"):
        pck = Path(tmp) / ("poll-%s.ckpt" % eng)
        halt, polls = [False], [0]

        def poll():
            while not halt[0]:
                try:
                    os.stat(pck)
                except OSError:
                    pass
                polls[0] += 1

        th = threading.Thread(target=poll, daemon=True)
        th.start()
        proc = bounded(pargv + ["--engine", eng, "--checkpoint", pck])
        halt[0] = True
        th.join(10)
        check(proc is not None and proc.returncode == 0 and
              pck.read_bytes() == pref.read_bytes(),
              "%s, a checkpoint every step, os.stat() on it %d times as it "
              "ran (%s): exit 0, on the unpolled run's checkpoint"
              % (eng, polls[0], "Windows, where that can refuse a rename"
                 if os.name == "nt" else "a POSIX rename is not refused so"),
              "%s under an os.stat() poll: %s" % (
                  eng, "HUNG" if proc is None else "exit %d, %s" % (
                      proc.returncode, proc.stderr.strip()[-120:])))

    # --- how long the rename is retried --------------------------------
    # The poll above shows a retry happens; not how long it lasts, and a
    # retry of about 60 ms passed it (verifier-V6's V6K). So the
    # checkpoint is held open, as a reader holds it, while a run renames
    # it after every step: for 0.5 s, which the run must outlast and end
    # on the unheld run's bytes; and for 5 s, longer than the retry (until
    # 1.5 s on the clock after the rename first fails), which on Windows
    # must end the run BY NAME between 1 and 5 s after the hold began -
    # and the run so ended must resume, on the other engine, to the unheld
    # run's checkpoint and records. The retry is bounded by the clock, not
    # by a count of sleeps, so a busy scheduler adds one sleep to it -
    # stretched as that sleep may be - not sixty (d56ecbe's count gave up
    # as late as 4.88 s, and once not within the 5 s, with a game holding
    # the CPU: verifier-V6). The 0.5 s hold asks of this process, too, that
    # it let go within about 1 s of the tool's first refused rename; that
    # is stated, not measured - the machine is not loaded to try it. A
    # POSIX rename over an open file is not refused, so there both holds
    # must leave the run as if nothing held it.
    hargv = ["--problem", "kepler", "--format", "fp64", "--members", 2,
             "--rsqrt", "newton", "--steps", 1000, "--sample-every", 50,
             "--checkpoint-interval", 0, "--quiet"]
    href_ck, href_rc = Path(tmp) / "h-ref.ckpt", Path(tmp) / "h-ref.txt"
    tool.run(*hargv, "--engine", "loop", "--checkpoint", href_ck,
             "--records", href_rc)
    href = (href_ck.read_bytes(), href_rc.read_bytes())

    def held_run(eng, seconds, ck, rc):
        """A run holding its checkpoint open for `seconds` once the first
        exists, or until the run ends if that is sooner. Returns (exit
        code or None if it outlived 60 s, stderr, seconds from the hold's
        start to the run's end or None if it was still running at the
        release, whether the hold was taken)."""
        for p in (ck, rc, Path(str(ck) + ".tmp")):
            if p.exists():
                p.unlink()
        pr = subprocess.Popen([tool.exe] + [str(a) for a in hargv] +
                              ["--engine", eng, "--checkpoint", str(ck),
                               "--records", str(rc)],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.PIPE, text=True)
        limit = time.monotonic() + 60
        while not ck.exists() and pr.poll() is None and \
                time.monotonic() < limit:
            time.sleep(0.002)
        fh = None
        for _ in range(500):            # it may be mid-rename
            try:
                fh = open(ck, "rb")
                break
            except OSError:
                time.sleep(0.002)
        t_hold, ended = time.perf_counter(), None
        while time.perf_counter() - t_hold < seconds:
            if pr.poll() is not None:
                ended = time.perf_counter() - t_hold
                break
            time.sleep(0.005)
        if fh:
            fh.close()
        try:
            _out, err = pr.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            pr.kill()
            pr.communicate()
            return None, "", ended, fh is not None
        return pr.returncode, err, ended, fh is not None

    for eng, other in (("loop", "segments"), ("segments", "loop")):
        ck, rc = Path(tmp) / "h.ckpt", Path(tmp) / "h.txt"
        code, err, ended, took = held_run(eng, 0.5, ck, rc)
        # On Windows the run is held in its retry through the whole 0.5 s,
        # so it is still running at the release - which is what shows the
        # hold met a rename and the retry outlasted it.
        short_ok = (took and code == 0 and
                    (ended is None or os.name != "nt") and
                    (ck.read_bytes(), rc.read_bytes()) == href)
        code2, err2, ended2, took2 = held_run(eng, 5.0, ck, rc)
        if os.name == "nt":
            gave_up = (took2 and code2 == 2 and ended2 is not None and
                       1.0 <= ended2 <= 5.0 and
                       "could not be renamed into place" in err2)
            res = tool.run(*hargv, "--engine", other, "--checkpoint", ck,
                           "--records", rc, "--resume", expect_ok=False)
            long_ok = (gave_up and res.returncode == 0 and
                       (ck.read_bytes(), rc.read_bytes()) == href)
            long_says = ("ended BY NAME %.2f s into it, and %s resumed it "
                         "to the unheld run's checkpoint and records"
                         % (ended2 or -1, other))
        else:
            long_ok = (took2 and code2 == 0 and
                       (ck.read_bytes(), rc.read_bytes()) == href)
            long_says = "went on untroubled (a POSIX rename is not refused)"
        check(short_ok and long_ok,
              "%s, renaming its checkpoint after every step while it was "
              "held open: 0.5 s - outlasted, ending on the unheld run's "
              "bytes; 5 s - %s" % (eng, long_says),
              "%s under a held checkpoint: 0.5 s hold taken %s, still "
              "running at the release %s, exit %s, bytes %s; 5 s hold: exit "
              "%s after %s s, %s" % (
                  eng, took, ended is None, code,
                  "right" if short_ok else "WRONG", code2,
                  "%.2f" % ended2 if ended2 is not None else "-",
                  err2.strip()[-100:]))

    # --- a second writer ------------------------------------------------
    # The length check before each checkpoint: another process that
    # writes to the records while the run does - here 1 MiB appended as
    # the first checkpoint appears - leaves the file longer than the
    # records the run has counted, and the run must stop BY NAME at its
    # next checkpoint, leaving the one before; the other engine resumes
    # that to the unheld run's checkpoint and records, cutting the
    # stranger's bytes away. With the check removed the run finished, exit
    # 0, on a file that was not its records (verifier-V6's R7, 3 of 3).
    wck, wrc = Path(tmp) / "w2.ckpt", Path(tmp) / "w2.txt"
    for p in (wck, wrc, Path(str(wck) + ".tmp")):
        if p.exists():
            p.unlink()
    pr = subprocess.Popen([tool.exe] + [str(a) for a in hargv] +
                          ["--engine", "segments", "--checkpoint", str(wck),
                           "--records", str(wrc)],
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          text=True)
    limit = time.monotonic() + 60
    while not wck.exists() and pr.poll() is None and \
            time.monotonic() < limit:
        time.sleep(0.002)
    appended = pr.poll() is None and wck.exists()
    if appended:
        with open(wrc, "ab") as fh:
            fh.write(b"another writer's line\n" * 47663)     # 1 MiB and more
    try:
        _out, werr = pr.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        pr.kill()
        _out, werr = pr.communicate()
    wres = tool.run(*hargv, "--engine", "loop", "--checkpoint", wck,
                    "--records", wrc, "--resume", expect_ok=False)
    wend = tuple(p.read_bytes() if p.exists() else None for p in (wck, wrc))
    check(appended and pr.returncode == 2 and
          "something else wrote to it or cut it" in werr and
          wres.returncode == 0 and wend == href,
          "a second writer: 1 MiB appended to the records as the run's first "
          "checkpoint appeared stopped the run BY NAME at its next (\"%s\"), "
          "and loop resumed the checkpoint left to the unheld run's "
          "checkpoint and records"
          % (werr.strip().splitlines() or [""])[-1].replace("cft-orbits: ", ""),
          "a second writer appending 1 MiB (%s): exit %s, %s; the resume "
          "after: exit %d, bytes %s" % (
              "appended" if appended else "NOT appended - the run had ended",
              pr.returncode, werr.strip()[-240:], wres.returncode,
              "right" if wend == href else "WRONG"))

    # --- a sample interval longer than one segment may run -------------
    # The loader refuses an image that could execute more than 2^40
    # instructions, and a trip count is 32 bits; a longer interval runs
    # as several segments. Each run's FIRST segment is exactly the
    # longest the tool computes it may be - outer/yoshida4 at the
    # instruction ceiling, kepler/leapfrog at the 2^32-1 trip count - so
    # one step more is refused at once (by the loader for the first, by
    # this tool's own trip-count check for the second), and a limit
    # computed right loads and runs until it is killed. The control
    # (=overlong) takes each limit one step too long, and both runs must
    # then be refused. (Until 2026-09-25 the first was refused, unnamed,
    # and the second by name.)
    long_runs = (
        ("outer, yoshida4, a segment at the 2^40-instruction ceiling",
         ["--problem", "outer", "--scheme", "yoshida4",
          "--steps", 700000000, "--sample-every", 700000000],
         "cft_program_load (a segment)"),
        ("kepler, leapfrog, a segment at the 2^32-1 trip count",
         ["--problem", "kepler", "--scheme", "leapfrog",
          "--steps", 5000000000, "--sample-every", 5000000000],
         "a segment's trip count must be 1..2^32-1"))
    env_ovl = env_with(CFT_ORBITS_NEGATIVE_CONTROL="overlong")
    procs = []
    for label, extra, needle in long_runs:
        argv = ["--format", "fp256", "--members", 2, "--rsqrt", "newton",
                "--quiet", "--engine", "segments", *extra]
        for env in (None, env_ovl):
            procs.append((label, needle, env, subprocess.Popen(
                [tool.exe] + [str(a) for a in argv],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                env=env)))
    time.sleep(2.0)
    for label, needle, env, p in procs:
        if env is None:
            alive = p.poll() is None
            p.kill()
            _, err = p.communicate()
            check(alive,
                  "%s: an interval longer than one segment may run is "
                  "split, not refused - the first segment, at exactly that "
                  "limit, loaded and ran until killed" % label,
                  "%s: refused or died at once: exit %s, %s"
                  % (label, p.returncode, err.strip()[-200:]))
        else:
            try:
                _, err = p.communicate(timeout=60)
            except subprocess.TimeoutExpired:
                p.kill()
                _, err = p.communicate()
            check(p.returncode == 2 and needle in err,
                  "%s: NEGATIVE CONTROL: one step longer (=overlong), the "
                  "first segment is refused - \"%s\"" % (label, needle),
                  "%s: NEGATIVE CONTROL FAILED TO FAIL: a segment one step "
                  "past the limit gave exit %s, %s"
                  % (label, p.returncode, err.strip()[-200:]))

    # --- a segment's flags reach the certificate -----------------------
    # A fault only the flag certificate can see: with every r^2 in the
    # image zeroed, the reciprocal square root meets a zero and the step
    # goes to NaN. The run must end on the certificate - exit 3, naming
    # the segment - so a segments engine that dropped its flags_out
    # (and would finish with exit 0 and a NaN energy) cannot pass.
    env_z = dict(os.environ, CFT_ORBITS_NEGATIVE_CONTROL="zero-r2")
    proc = tool.run("--problem", "kepler", "--scheme", "leapfrog",
                    "--format", "fp64", "--members", 3, "--rsqrt", "newton",
                    "--periods", 1, "--steps-per-period", 64, "--quiet",
                    "--engine", "segments", expect_ok=False, env=env_z)
    check(proc.returncode == 3 and
          "a sequencer-program segment raised" in proc.stderr and
          "NEGATIVE CONTROL ACTIVE" in proc.stderr,
          "PLANTED FAULT: with every r^2 in the segment zeroed the run stops "
          "on the flag certificate - exit 3, naming the segment",
          "PLANTED FAULT MISSED: a zeroed r^2 gave exit %d - %s"
          % (proc.returncode, proc.stderr.strip()[-200:]))

    # --- the golden model on the image this engine writes -------------
    for problem, scheme, fmtname, extra in (
            ("kepler", "leapfrog", "fp64", ["--periods", 1,
                                            "--steps-per-period", 64]),
            ("outer", "yoshida4", "fp256", ["--years", 1, "--days", 10])):
        d = Path(tmp) / ("dump-%s-%s" % (problem, fmtname))
        d.mkdir()
        tool.run("--problem", problem, "--scheme", scheme, "--format",
                 fmtname, "--members", 3, "--rsqrt", "newton", "--engine",
                 "segments", "--sample-every", 2, "--quiet", *extra,
                 "--segment-dump", d)
        fmt = FORMATS[fmtname]
        image = (d / "segment.cftp").read_bytes()
        a_in = _values((d / "segment.a.bin").read_bytes(), fmt)
        s_in = _values((d / "segment.in.bin").read_bytes(), fmt)
        s_out = _values((d / "segment.out.bin").read_bytes(), fmt)
        n = len(a_in)
        prog = seq.Program.from_bytes(image)
        res = seq.run(prog, a_in, [0] * n, None, scratch_in=s_in)
        label = "%s, %s, %s" % (problem, scheme, fmtname)
        check(len(s_out) == len(s_in) == n * prog.n_scratch_out and
              s_out != s_in,
              "%s: the dumped segment moved the state (%d lanes x %d slots) - "
              "the comparison below is not of a no-op" % (label, n,
                                                          prog.n_scratch_out),
              "%s: the dump is empty, mis-sized or unchanged by the run"
              % label)
        check(res.scratch_out == s_out and res.status == 0,
              "%s: python/cft_golden's executor, on the image this tool "
              "built and the scratch block it sent, returns the library's "
              "scratch-out exactly (%d instructions)" % (label,
                                                         len(prog.insns)),
              "%s: the golden model and the library disagree on the "
              "segment" % label)
        # The control is a different PROGRAM, not a different answer: a
        # flipped bit in s_out could never have matched once the check
        # above passed, so it proved nothing. Constant 2 is the first
        # drift's scale - h/2 under leapfrog, w1 h/2 under yoshida4 (the
        # bank's order is -1, -1/2, then the drift scales) - and one bit
        # of it must move the golden executor off the library: the bit
        # in the MIDDLE of the significand, a change of about 2^(p/2)
        # ulps. Not bit 0: the step map is many-to-one at the ulp scale,
        # and a one-ulp change can merge back bit for bit within a
        # segment (F0b, 2026-09-25), which would fail this control on a
        # program that did differ.
        esz = fmt.width // 8
        mid = fmt.man_w // 2                 # a significand bit, not the
        other = bytearray(image)             # exponent's, in any format
        other[32 + 2 * esz + mid // 8] ^= 1 << (mid % 8)
        res_k = seq.run(seq.Program.from_bytes(bytes(other)), a_in,
                        [0] * n, None, scratch_in=s_in)
        check(res_k.scratch_out != s_out,
              "%s: NEGATIVE CONTROL: the same image with one bit of one "
              "constant changed gives the golden executor a different "
              "scratch-out, so agreement means the library ran THIS "
              "program" % label,
              "%s: NEGATIVE CONTROL FAILED TO FAIL: an altered constant "
              "left the golden scratch-out unchanged" % label)
        # The round trip reproduces any legal encoding, a kx the
        # assembler would not have chosen included - the disassembler
        # writes that one as `.kx` and the assembler honours it - so the
        # CHOICE is held by requiring no `.kx` in the text: the tool
        # must pick the indexed form exactly where the assembler's own
        # rule does (docs/PROGRAMS.md), and only the outer yoshida4
        # image, whose bank runs past 16, needs it at all.
        text = asm.disassemble(image)
        again = asm.assemble(text, "segment")
        forced = [ln.strip() for ln in text.splitlines() if ".kx " in ln]
        check(again == image and not forced,
              "%s: the reference assembler reads the image back to the same "
              "%d bytes, and no instruction is marked .kx - the tool's "
              "encoder, its choice of the indexed form included, is the "
              "assembler's" % (label, len(image)),
              "%s: disassemble/re-assemble does not return the tool's image, "
              "or the tool chose kx where the assembler would not (%d "
              "marked, e.g. %s)" % (label, len(forced),
                                    forced[0] if forced else "-"))
        bad = bytearray(image)
        bad[-1] |= 0x80          # imm[31] of the last word: HALT's, reserved
        refused = 0
        try:
            seq.Program.from_bytes(bytes(bad))
        except seq.ProgramError:
            refused += 1
        try:
            asm.disassemble(bytes(bad))
        except asm.AsmError:
            refused += 1
        check(refused == 2,
              "%s: NEGATIVE CONTROL: the same image with one reserved bit "
              "set is refused by both the golden loader and the "
              "disassembler, so their acceptance of the real one means "
              "something" % label,
              "%s: NEGATIVE CONTROL FAILED TO FAIL: a reserved bit was "
              "accepted (%d of 2 refused)" % (label, refused))


# ---------------------------------------------------------------------
# [8] Certified runs (docs/ORBITS.md, "Certified runs")
#
# A certified run's certificate is held three ways: to the golden model
# (its reader, strictly; its writer, which runs every interval WHOLE with
# seq.run and must make the same bytes; its chain, which every boundary
# file must be), to the tool's own records (every boundary file is its
# sample's exact decimals), and to both auditors (cert.audit and
# cft-audit, the same verdict, line for line or refusal for refusal).
# Then the same bytes however the engine cut its intervals, whatever the
# batch, and however the run was interrupted and resumed; the controls,
# each refused by name by both auditors; and every refusal the certified
# path can make, by name and exit code, with what each leaves behind: all
# but `build-width`, which no build whose tool and library share one
# configuration reaches (a mixed build does, verifier-W3b) - a bigint that
# narrow needs CFT_NO_TRANSCEND, and cft-orbits calls cft_acos and
# cft_rootn (docs/ORBITS.md, "Certified runs").
# ---------------------------------------------------------------------
_AUDIT_REFUSED = re.compile(r"^cft-audit: refused ([a-z-]+): ", re.M)
_AUDIT_LOCATION = re.compile(r"^cft-audit: location line=(\S+) run=(\S+) "
                             r"segment=(\S+) entry=(\S+)$", re.M)
_ORBITS_REFUSED = re.compile(r"^cft-orbits: refused ([a-z-]+): ", re.M)


def _golden_verdict(fn, *a, **k):
    """-> ("refused", (name, code, location)) or ("accepted", lines)."""
    from cft_golden import cert
    try:
        v = fn(*a, **k)
    except cert.Refusal as e:
        loc = tuple("-" if x is None else str(x)
                    for x in (e.line, e.run, e.segment, e.entry))
        return "refused", (e.name, e.exit_code, loc)
    return "accepted", v.lines()


def _tool_verdict(proc):
    if proc.returncode == 0:
        return "accepted", proc.stdout.split("\n")[:-1]
    m = _AUDIT_REFUSED.search(proc.stderr)
    loc = _AUDIT_LOCATION.search(proc.stderr)
    if m and loc:
        return "refused", (m.group(1), proc.returncode, tuple(loc.groups()))
    return "error", "exit %d: %s" % (proc.returncode, proc.stderr[-200:])


def check_certificates(tool, tmp, audit_exe):
    """[8] certified runs of the Newton route: --cert on --engine
    segments. Controls: the certificate's end state, flag word and an
    interval each changed, the transpose control's own certificate, and a
    resume that drops the interval's flags so far (=drop-flags) - each
    refused by name by both auditors."""
    from cft_golden import cert, chars
    print("\n[8] certified runs: each sample interval one segment of the "
          "stride's image, audited by both auditors")
    tmp = Path(tmp)
    work = tmp / "cert"
    work.mkdir()
    salt_file = work / "example.salt"
    salt_file.write_bytes(bytes(range(32)))    # the page's example salt
    other_salt = work / "other.salt"
    other_salt.write_bytes(bytes(range(1, 33)))
    K = ["--problem", "kepler", "--scheme", "leapfrog", "--format", "fp64",
         "--members", 4, "--periods", 2, "--steps-per-period", 64,
         "--sample-every", 16, "--rsqrt", "newton", "--engine", "segments",
         "--quiet"]
    O = ["--problem", "outer", "--scheme", "yoshida4", "--format", "fp256",
         "--members", 3, "--years", 1, "--days", 10, "--sample-every", 9,
         "--rsqrt", "newton", "--engine", "segments", "--quiet"]
    MODE = {"keyed": ["--cert-salt", salt_file], "open": ["--cert-open"]}
    SALT = {"keyed": salt_file.read_bytes(), "open": None}
    ACC = ["--cert-accuracy", "angular-momentum-drift"]
    seed = bytes(range(100, 132))
    serial = [0]

    def paths(tag):
        return work / (tag + ".cert"), work / (tag + ".states")

    def certify(tag, argv, mode, *extra, env=None, entries=True):
        """A certified run, with the angular momentum's drift entries
        unless `entries` is False; -> (proc, certificate, states dir)."""
        c, d = paths(tag)
        proc = tool.run(*argv, "--cert", c, "--cert-states", d, *MODE[mode],
                        *(ACC if entries else []), *extra, expect_ok=False,
                        env=env)
        return proc, c, d

    def audits(c, d, mode, states="all", choose=None):
        """Both auditors on one certificate: -> (golden, tool)."""
        image = (d / "run-0.cftp").read_bytes()
        data = c.read_bytes()
        sdir = d
        if states == "initial":
            serial[0] += 1
            sdir = work / ("initial-%d" % serial[0])
            sdir.mkdir()
            shutil.copyfile(d / "run-0-boundary-0.bin",
                            sdir / "run-0-boundary-0.bin")
        st = {0: {int(p.name[len("run-0-boundary-"):-4]): p.read_bytes()
                  for p in sdir.glob("run-0-boundary-*.bin")}}
        kw = {"states": st}
        args = [audit_exe, "--cert", c, "--states", sdir, "--run", 0,
                "--image", d / "run-0.cftp"]
        if choose:
            kw.update(choose={0: ("sample", choose)}, seed=seed)
            args += ["--choose", "sample:%d" % choose, "--seed", seed.hex()]
        if SALT[mode] is not None:
            args += ["--salt", salt_file]
        g = _golden_verdict(cert.audit, data, SALT[mode],
                            {0: (image, None)}, **kw)
        t = _tool_verdict(subprocess.run([str(a) for a in args],
                                         capture_output=True, text=True))
        return g, t

    def refusal(proc):
        m = _ORBITS_REFUSED.search(proc.stderr)
        return (m.group(1) if m else None), proc.returncode

    # --- the two runs, keyed and open ------------------------------------
    made = {}
    for label, argv, fmtname, stride in (("kepler fp64 leapfrog", K, "fp64",
                                          16),
                                         ("outer fp256 yoshida4", O, "fp256",
                                          9)):
        fmt = FORMATS[fmtname]
        for mode in ("keyed", "open"):
            tag = "%s-%s" % (argv[1], mode)
            rec = work / (tag + ".txt")
            proc, c, d = certify(tag, argv, mode, "--records", rec)
            if not check(proc.returncode == 0 and c.exists(),
                         "%s, %s: certified, exit 0" % (label, mode),
                         "%s, %s: the certified run failed (exit %d) %s"
                         % (label, mode, proc.returncode,
                            proc.stderr[-300:])):
                continue
            made[(argv[1], mode)] = (c, d, rec)
            data = c.read_bytes()
            try:
                parsed = cert.parse(data, SALT[mode])
                why = None
            except cert.Refusal as e:
                parsed, why = None, "%s: %s" % (e.name, e)
            check(parsed is not None,
                  "%s, %s: the golden reader accepts it strictly" % (label,
                                                                     mode),
                  "%s, %s: the golden reader refuses it - %s" % (label, mode,
                                                                  why))
            if parsed is None:
                continue
            run = parsed.runs[0]
            image = (d / "run-0.cftp").read_bytes()
            init = cert.state_values(fmt,
                                     (d / "run-0-boundary-0.bin").read_bytes())
            states, results = cert.run_chain(image, None, init,
                                             len(run.chain))
            grun = cert.certify_run("main", image, None, SALT[mode], states,
                                    results, steps=run.steps)
            # the entries, made again here: each component's terms from
            # the problem's structure, each mass from --dump-setup's exact
            # decimal, each value by cert.derive from the golden chain
            st_ = tool.setup(*argv)
            nb, nd = st_["bodies"], st_["dims"]
            nslots = 2 * nb * nd
            entries, sizes = [], []
            for elabel, terms in _angmom_terms(argv[1], st_["mass"], nb, nd):
                probe = cert.Entry("drift", "measurement", 0, None,
                                   cert.Value("exact", exact=Fraction(0)),
                                   elabel, terms)
                q = cert.derive(probe, (grun,), [(run.fmt, nslots)],
                                {(0, 0): states[0],
                                 (0, len(states) - 1): states[-1]})
                sizes.append((elabel, _widest(terms, fmt, states[0],
                                              states[-1], nslots, run.lanes),
                              q))
                entries.append(cert.Entry("drift", "measurement", 0, None,
                                          cert.make_value(q, "exact"), elabel,
                                          terms))
            gold = cert.encode(cert.Certificate(
                parsed.mode, parsed.salt_commitment, parsed.identity,
                (grun,), tuple(entries)))
            files = [(d / ("run-0-boundary-%d.bin" % b)).read_bytes()
                     for b in range(len(states))]
            check(gold == data and all(files[b] == cert.state_bytes(fmt, s)
                                       for b, s in enumerate(states)) and
                  run.steps == stride and
                  all((s.flags, s.status) == (16, 0) for s in run.chain),
                  "%s, %s: the golden writer, running each of the %d "
                  "intervals WHOLE with seq.run from boundary 0 and deriving "
                  "the %d angular-momentum drift entr%s itself, writes the "
                  "same bytes; every boundary file is its chain's state; "
                  "every segment says flags 16 status 0, as the library "
                  "reported" % (label, mode, len(run.chain), len(entries),
                                "y" if len(entries) == 1 else "ies"),
                  "%s, %s: the golden writer's certificate or chain is not "
                  "the tool's" % (label, mode))
            if mode == "keyed":
                # the width rule, COMPUTED on this configuration: the most
                # bits any value reaches on the way, in cert.derive's order
                most = max(max(w) for _, w, _ in sizes)
                kinds = ([e.kind for e in parsed.accuracy] ==
                         ["measurement"] * len(entries))
                labels = ([e.label for e in parsed.accuracy] ==
                          [s[0] for s in sizes])
                check(most <= 1023 and kinds and labels,
                      "%s: each entry's kind a measurement and its label the "
                      "component; every value within the width rule, "
                      "computed - %s; the widest %d bits of 1,023"
                      % (label, "; ".join(
                          "%s %s, numerator %d and denominator %d bits, %d "
                          "and %d the most on the way"
                          % (n, "0" if q == 0 else "%.3e" % float(q),
                             abs(q.numerator).bit_length(),
                             q.denominator.bit_length(), w[0], w[1])
                          for n, w, q in sizes), most),
                      "%s: an entry past the width rule (%d bits), or not a "
                      "measurement labelled by its component" % (label,
                                                                  most))
            # every boundary file is the records' exact decimals
            recs = parse_records(rec)
            good = True
            for b in range(len(states)):
                vals = []
                for row in [r for r in recs if r[0] == b]:
                    vals += [chars.from_decimal(fmt, x)[0]
                             for x in row[3] + row[4]]
                good &= cert.state_bytes(fmt, vals) == files[b]
            check(good, "%s, %s: every boundary file holds its sample's "
                        "records, exact decimal for exact decimal (the "
                        "state lane-major, slot c q_c, slot ncomp + c v_c)"
                  % (label, mode),
                  "%s, %s: a boundary file is not its sample's records"
                  % (label, mode))
            for how, kw in (("in full from the states directory",
                             {"states": "all"}),
                            ("in full from boundary 0 alone, every later "
                             "state re-run into", {"states": "initial"}),
                            ("sampled, 2 segments under a fixed seed",
                             {"states": "all", "choose": 2})):
                g, t = audits(c, d, mode, **kw)
                check(g[0] == "accepted" and t == g,
                      "%s, %s: both auditors accept it %s, the same verdict "
                      "line for line" % (label, mode, how),
                      "%s, %s, audited %s: golden %s, cft-audit %s"
                      % (label, mode, how, g, t))

    # --- the same bytes however the intervals were cut --------------------
    base = made.get(("kepler", "open"))
    if base:
        whole = base[0].read_bytes()
        ck = work / "cut.ckpt"
        for label, extra, env in (
                ("its intervals cut at a loader limit lowered to 5 steps "
                 "(CFT_ORBITS_SEGMENT_LIMIT)", ["--batch", 3],
                 env_with(CFT_ORBITS_SEGMENT_LIMIT="5")),
                ("its intervals cut by checkpoints under a steady clock "
                 "(CFT_ORBITS_VIRTUAL_CLOCK)",
                 ["--checkpoint", ck, "--checkpoint-interval", "0.05"],
                 env_with(CFT_ORBITS_VIRTUAL_CLOCK="0.01")),
                ("at batch 1, one lane a run", ["--batch", 1], None),
                ("at batch 3, chunks of 3 and 1", ["--batch", 3], None)):
            serial[0] += 1
            tag = "cut-%d" % serial[0]
            proc, c, d = certify(tag, K, "open", *extra, env=env)
            same = (proc.returncode == 0 and c.read_bytes() == whole and
                    all((d / p.name).read_bytes() == p.read_bytes()
                        for p in base[1].iterdir()))
            check(same, "kepler, open: %s - the same certificate and states, "
                        "byte for byte" % label,
                  "kepler, open: %s - the certificate or a state differs "
                  "(exit %d) %s" % (label, proc.returncode,
                                    proc.stderr[-200:]))
    ob = made.get(("outer", "keyed"))
    if ob:
        proc, c, d = certify("outer-cut", O, "keyed", "--batch", 2,
                             env=env_with(CFT_ORBITS_SEGMENT_LIMIT="4"))
        check(proc.returncode == 0 and c.read_bytes() == ob[0].read_bytes(),
              "outer, keyed: its intervals cut at 4 steps and in chunks of 2 "
              "and 1 - the same certificate, byte for byte",
              "outer, keyed: the cut run's certificate differs (exit %d)"
              % proc.returncode)
    # stream a: a certified run hands +0, an ordinary one q_0
    for argv, key in ((K, "kepler"), (O, "outer")):
        m = made.get((key, "open"))
        if not m:
            continue
        rec = work / ("plain-%s.txt" % key)
        tool.run(*argv, "--records", rec)
        check(rec.read_bytes() == m[2].read_bytes(),
              "%s: the certified run's records, stream a +0, are an "
              "ordinary run's, stream a q_0, byte for byte - no stream "
              "reaches a result" % key,
              "%s: the certified run's records differ from an ordinary "
              "run's" % key)

    # --- resumed: the uninterrupted run's bytes ---------------------------
    def relay(tag, argv, mode, stop, batch, env=None):
        c, d = paths(tag)
        ck = work / (tag + ".ckpt")
        rounds, mid, closed_late = 0, 0, 0
        while rounds < 60:
            proc, c, d = certify(tag, argv, mode, "--stop-after-steps", stop,
                                 "--checkpoint", ck, "--batch", batch,
                                 *(["--resume"] if rounds else []),
                                 env=env)
            rounds += 1
            if proc.returncode:
                return rounds, mid, closed_late, proc
            st, sm = _at_of(ck)
            stride = _field_of(ck, "stride")
            if st % stride:
                mid += 1
            elif st != sm * stride:
                closed_late += 1
            if c.exists():
                break
        return rounds, mid, closed_late, proc

    if base:
        whole = base[0].read_bytes()
        for tag, stop, batch in (("relay-37", 37, 3), ("relay-16", 16, 1)):
            rounds, mid, late, proc = relay(tag, K, "open", stop, batch)
            c, _ = paths(tag)
            check(proc.returncode == 0 and c.exists() and
                  c.read_bytes() == whole and (mid or late),
                  "kepler, open: stopped every %d steps and resumed %d times "
                  "at batch %d (%d stops mid interval, %d at an interval's "
                  "last step, unclosed) - the uninterrupted certificate, "
                  "byte for byte" % (stop, rounds - 1, batch, mid, late),
                  "kepler, open: the relay every %d steps did not end on the "
                  "uninterrupted certificate (exit %d) %s"
                  % (stop, proc.returncode, proc.stderr[-200:]))
        # killed the instant its third checkpoint is in place, resumed
        ck = work / "killed.ckpt"
        proc, c, d = certify("killed", K, "open", "--checkpoint", ck,
                             "--checkpoint-interval", "0.05",
                             env=env_with(CFT_ORBITS_VIRTUAL_CLOCK="0.01",
                                          CFT_ORBITS_DIE_AFTER_CHECKPOINT=
                                          "3"))
        at = _at_of(ck) if ck.exists() else None
        p2, c, d = certify("killed", K, "open", "--checkpoint", ck,
                           "--resume")
        check(proc.returncode == 9 and not c.with_suffix(".cert.tmp").exists()
              and p2.returncode == 0 and c.read_bytes() == whole,
              "kepler, open: killed as its third checkpoint appeared (at "
              "%s), then resumed - the uninterrupted certificate" % at,
              "kepler, open: the killed and resumed run's certificate "
              "differs (exits %d, %d) %s" % (proc.returncode, p2.returncode,
                                             p2.stderr[-200:]))
        # resumed from its final checkpoint, the certificate removed
        c, d = paths("killed")
        c.unlink()
        p3, c, d = certify("killed", K, "open", "--checkpoint", ck,
                           "--resume")
        check(p3.returncode == 0 and c.read_bytes() == whole,
              "kepler, open: resumed from its final checkpoint with the "
              "certificate gone, it writes the same certificate again",
              "kepler, open: resumed from its final checkpoint, exit %d %s"
              % (p3.returncode, p3.stderr[-200:]))
        # a stop at the run's last step leaves its last interval unclosed and
        # writes no certificate; a stop at its last sample is the run
        # completed, and writes it
        for label, stop, writes in (
                ("--stop-after-steps 128, the run's last step",
                 ["--stop-after-steps", 128], False),
                ("--stop-after-samples 8, the run's last sample",
                 ["--stop-after-samples", 8], True)):
            serial[0] += 1
            tag = "stop-end-%d" % serial[0]
            ck = work / (tag + ".ckpt")
            proc, c, d = certify(tag, K, "open", *stop, "--checkpoint", ck)
            at = _at_of(ck) if ck.exists() else None
            check(proc.returncode == 0 and
                  (c.exists() and c.read_bytes() == whole and at == [128, 8]
                   if writes else not c.exists() and at == [128, 7]),
                  "kepler, open: %s - %s" % (label, "the run completed, and "
                  "its certificate is the uninterrupted one" if writes else
                  "its last interval unclosed (at 128 7), and no certificate"),
                  "kepler, open: %s - exit %d, at %s, certificate %s"
                  % (label, proc.returncode, at,
                     "written" if c.exists() else "not written"))
        # CERT.tmp is the tool's own name, as a checkpoint's .tmp is: a file
        # of that name there already is cut, and the certificate written
        serial[0] += 1
        tag = "tmp-there-%d" % serial[0]
        c, d = paths(tag)
        tmpf = Path(str(c) + ".tmp")
        tmpf.write_bytes(b"a file of the user's, by the tool's own name\n")
        proc, c, d = certify(tag, K, "open")
        check(proc.returncode == 0 and c.exists() and
              c.read_bytes() == whole and not tmpf.exists(),
              "kepler, open: a file named CERT.tmp there already is cut, and "
              "the run writes the uninterrupted certificate",
              "kepler, open: with a CERT.tmp there already - exit %d, %s, "
              "CERT.tmp %s" % (proc.returncode, proc.stderr[-200:],
                               "there" if tmpf.exists() else "gone"))
    if ob:
        rounds, mid, late, proc = relay("relay-outer", O, "keyed", 13, 2)
        c, _ = paths("relay-outer")
        check(proc.returncode == 0 and c.exists() and
              c.read_bytes() == ob[0].read_bytes(),
              "outer, keyed: stopped every 13 steps and resumed %d times - "
              "the uninterrupted certificate" % (rounds - 1),
              "outer, keyed: the relay's certificate differs (exit %d) %s"
              % (proc.returncode, proc.stderr[-200:]))

    # --- the controls: each refused by name by both auditors -------------
    def edited(src, tag, fn):
        """A copy of certificate `src` with its body edited by fn and a
        valid hash line over it, beside its own states."""
        body = cert.body_of(src.read_bytes()).decode("ascii")
        new = fn(body.split("\n")[:-1])
        text = "\n".join(new) + "\n"
        c = work / (tag + ".cert")
        c.write_bytes(cert.rehash(text.encode("ascii")))
        return c

    def both_refuse(c, d, mode, states, name, seg, label):
        g, t = audits(c, d, mode, states=states)
        want = ("refused", (name, cert.REFUSALS[name],
                            ("-", "0", str(seg), "-")))
        check(g == want and t == g,
              "CONTROL: %s - both auditors refuse %s at run 0 segment %d"
              % (label, name, seg),
              "CONTROL FAILED: %s - golden %s, cft-audit %s"
              % (label, g, t))

    if base:
        c0, d0 = base[0], base[1]

        def end_changed(lines):
            seg = {int(l.split()[1]): i for i, l in enumerate(lines)
                   if l.startswith("segment ")}
            other = lines[seg[5]].split()[5]          # boundary 6's hash
            a = lines[seg[2]].split()
            a[5] = other
            b = lines[seg[3]].split()
            b[3] = other
            lines[seg[2]], lines[seg[3]] = " ".join(a), " ".join(b)
            return lines

        both_refuse(edited(c0, "ctl-end", end_changed), d0, "open",
                    "initial", "segment-end", 2,
                    "segment 2's end state changed (its end and segment 3's "
                    "start moved to boundary 6's hash, the hash line made "
                    "again), audited from boundary 0")

        def flags_changed(lines):
            i = next(i for i, l in enumerate(lines)
                     if l.startswith("segment 1 "))
            lines[i] = lines[i].replace(" flags 16 ", " flags 17 ")
            return lines

        both_refuse(edited(c0, "ctl-flags", flags_changed), d0, "open",
                    "all", "segment-flags", 1,
                    "segment 1's flag word changed from 16 to 17")

        def dropped(lines):
            out, k = [], 0
            for l in lines:
                if l.startswith("segments "):
                    l = "segments %d" % (int(l.split()[1]) - 1)
                elif l.startswith("segment "):
                    if l.startswith("segment 3 "):
                        continue
                    f = l.split()
                    f[1] = str(k)
                    k += 1
                    l = " ".join(f)
                out.append(l)
            return out

        both_refuse(edited(c0, "ctl-dropped", dropped), d0, "open", "all",
                    "continuity", 3,
                    "interval 3 dropped (its line removed, the count and the "
                    "later indices made to agree)")
        proc, c, d = certify("ctl-transpose", K, "open",
                             env=env_with(CFT_ORBITS_NEGATIVE_CONTROL=
                                          "transpose"))
        if check(proc.returncode == 0 and c.exists(),
                 "CONTROL: under =transpose the run certifies what it "
                 "computed",
                 "CONTROL: under =transpose the run failed (exit %d)"
                 % proc.returncode):
            both_refuse(c, d, "open", "all", "segment-end", 0,
                        "=transpose's own certificate (v_0 and v_1 packed "
                        "into each other's slots, the state certified in the "
                        "layout the image reads)")
        # a resume that drops the interval's flags so far
        ck = work / "ctl-drop.ckpt"
        certify("ctl-drop", K, "open", "--stop-after-steps", 16,
                "--checkpoint", ck)
        at = _at_of(ck)
        proc, c, d = certify("ctl-drop", K, "open", "--checkpoint", ck,
                             "--resume",
                             env=env_with(CFT_ORBITS_NEGATIVE_CONTROL=
                                          "drop-flags"))
        check(at == [16, 0] and proc.returncode == 0 and
              "NEGATIVE CONTROL ACTIVE" in proc.stderr and
              c.read_bytes() != c0.read_bytes(),
              "CONTROL: stopped at interval 0's last step (at 16 0, "
              "unclosed) and resumed under =drop-flags, the certificate is "
              "NOT the uninterrupted one",
              "CONTROL FAILED: at %s, exit %d, the resumed certificate %s the "
              "uninterrupted one" % (at, proc.returncode,
                                     "equals" if c.exists() and
                                     c.read_bytes() == c0.read_bytes()
                                     else "vs"))
        both_refuse(c, d, "open", "all", "segment-flags", 0,
                    "a resume that dropped the interval's flags so far "
                    "(=drop-flags)")

    # --- no entries asked: `accuracy 0`; and the width rule, by name -----
    proc, c, d = certify("no-entries", K, "open", entries=False)
    if proc.returncode == 0 and c.exists():
        data = c.read_bytes()
        parsed = cert.parse(data)
        run = parsed.runs[0]
        image = (d / "run-0.cftp").read_bytes()
        init = cert.state_values(FORMATS["fp64"],
                                 (d / "run-0-boundary-0.bin").read_bytes())
        states, results = cert.run_chain(image, None, init, len(run.chain))
        gold = cert.encode(cert.Certificate(
            "open", None, parsed.identity,
            (cert.certify_run("main", image, None, None, states, results,
                              steps=run.steps),), ()))
        g, t = audits(c, d, "open")
        check(gold == data and b"\naccuracy 0\n" in data and
              g[0] == "accepted" and t == g,
              "kepler, open, no --cert-accuracy: `accuracy 0`, the golden "
              "writer's bytes, and both auditors accept it",
              "kepler, open, no --cert-accuracy: not the golden writer's "
              "bytes, or not accepted (golden %s, cft-audit %s)" % (g, t))
    else:
        check(False, "", "kepler, open, no --cert-accuracy: the run failed "
                         "(exit %d) %s" % (proc.returncode, proc.stderr[-200:]))
    # the width plant: the first term's coefficient taken times 2^-1000, so
    # that its first product is past the rule. The golden writer refuses
    # the same entry `width`, and so must the tool, by name, with no
    # certificate.
    proc, c, d = certify("width-plant", K, "open",
                         env=env_with(CFT_ORBITS_CERT_PLANT="width"))
    st_ = tool.setup(*K)
    (elabel, terms), = _angmom_terms("kepler", st_["mass"], 1, 2)
    planted = ((terms[0][0] * Fraction(1, 2 ** 1000), terms[0][1]),) + \
        terms[1:]
    try:
        run = cert.parse((work / "no-entries.cert").read_bytes()).runs[0]
        gs = cert.state_values(FORMATS["fp64"],
                               (d / "run-0-boundary-0.bin").read_bytes())
        gstates, gres = cert.run_chain((d / "run-0.cftp").read_bytes(), None,
                                       gs, len(run.chain))
        cert.derive(cert.Entry("drift", "measurement", 0, None,
                               cert.Value("exact", exact=Fraction(0)), elabel,
                               planted),
                    (run,), [("fp64", 4)],
                    {(0, 0): gstates[0], (0, len(gstates) - 1): gstates[-1]})
        golden_says = "accepted"
    except cert.Refusal as e:
        golden_says = e.name + ": " + str(e)
    # refused at the run's end: DIR is left whole, the image and every
    # boundary, and there is no certificate and no CERT.tmp
    left = sorted(p.name for p in d.iterdir()) if d.exists() else None
    whole_dir = sorted(["run-0.cftp"] + ["run-0-boundary-%d.bin" % b
                                         for b in range(9)])
    check(refusal(proc) == ("width", 3) and "term 0's product" in
          proc.stderr and golden_says.startswith("width") and
          "term 0's product" in golden_says and not c.exists() and
          not Path(str(c) + ".tmp").exists() and left == whole_dir,
          "refused width (exit 3) at the run's end: no certificate and no "
          "CERT.tmp, DIR left whole (the image and all 9 boundaries); the "
          "first term's coefficient taken times 2^-1000 "
          "(CFT_ORBITS_CERT_PLANT=width), its first product past the rule - "
          "where the golden writer refuses the same entry, `%s`"
          % golden_says[:90],
          "the width plant: the tool %s (exit %d), the golden writer %s; "
          "DIR left %s, CERT.tmp %s"
          % (refusal(proc)[0], proc.returncode, golden_says[:120], left,
             "there" if Path(str(c) + ".tmp").exists() else "gone"))

    # --- what the certified path refuses, by name and exit code ----------
    # the page's table, every name and its code; build-width (78) is in it
    # and not here: no build whose tool and library share one
    # configuration reaches it
    NAMES = {"engine": 64, "rsqrt-exact": 64, "step-halving": 64,
             "wider": 64, "energy-drift": 64, "usage": 64,
             "salt-length": 4, "program-image": 4, "device": 69,
             "malformed": 2, "width": 3, "accuracy-finite": 7,
             "memory": 71, "output": 73, "salt-missing": 4,
             "salt-unexpected": 4, "salt-commitment": 4, "identity": 78,
             "image-digest": 4, "program-digest": 4, "state-missing": 4,
             "state-hash": 4, "state-shape": 4}
    short = ["--problem", "kepler", "--format", "fp64", "--members", 2,
             "--periods", 1, "--steps-per-period", 32, "--sample-every", 8,
             "--quiet"]
    seg = ["--rsqrt", "newton", "--engine", "segments"]
    salt31 = work / "short.salt"
    salt31.write_bytes(bytes(31))
    there = work / "there.cert"
    there.write_bytes(b"not mine\n")
    there_dir = work / "there.states"
    there_dir.mkdir()
    fresh_refusals = (
        ("--engine loop, the default", [], ["--cert-open"], None, "engine"),
        ("--engine program", ["--rsqrt", "newton", "--engine", "program"],
         ["--cert-open"], None, "engine"),
        ("--rsqrt exact, the default", ["--engine", "segments"],
         ["--cert-open"], None, "rsqrt-exact"),
        ("--cert-accuracy step-halving", seg,
         ["--cert-open", "--cert-accuracy", "step-halving"], None,
         "step-halving"),
        ("--cert-accuracy wider", seg,
         ["--cert-open", "--cert-accuracy", "wider"], None, "wider"),
        ("--cert-accuracy energy-drift", seg,
         ["--cert-open", "--cert-accuracy", "energy-drift"], None,
         "energy-drift"),
        ("--cert-accuracy of no method", seg,
         ["--cert-open", "--cert-accuracy", "drift"], None, "usage"),
        ("--cert-salt and --cert-open both", seg,
         ["--cert-open", "--cert-salt", salt_file], None, "usage"),
        ("neither --cert-salt nor --cert-open", seg, [], None, "usage"),
        ("--cert-open given twice", seg, ["--cert-open", "--cert-open"],
         None, "usage"),
        ("--stop-after-steps without --checkpoint", seg,
         ["--cert-open", "--stop-after-steps", 3], None, "usage"),
        ("a salt of 31 bytes", seg, ["--cert-salt", salt31], None,
         "salt-length"),
        ("a salt file that is not there", seg,
         ["--cert-salt", work / "no.salt"], None, "usage"),
        ("the device taken to read no flags (CFT_ORBITS_CERT_PLANT)", seg,
         ["--cert-open"], {"CFT_ORBITS_CERT_PLANT": "flags-unreadable"},
         "device"),
        ("a stride of 2^32 steps, past a trip count", ["--steps",
         4294967296, "--sample-every", 4294967296] + seg, ["--cert-open"],
         None, "program-image"),
    )
    for label, extra, cflags, env, name in fresh_refusals:
        serial[0] += 1
        c, d = paths("refused-%d" % serial[0])
        proc = tool.run(*short, *extra, "--cert", c, "--cert-states", d,
                        *cflags, expect_ok=False,
                        env=env_with(**env) if env else None)
        got = refusal(proc)
        check(got == (name, NAMES[name]) and not c.exists() and
              not d.exists() and not Path(str(c) + ".tmp").exists(),
              "refused %s (exit %d), nothing made: %s"
              % (name, NAMES[name], label),
              "not refused %s (exit %d) with nothing made: %s - %s, exit "
              "%d, %s" % (name, NAMES[name], label, got[0], proc.returncode,
                          proc.stderr.strip()[-200:]))
    # the loader's own ceiling: 2^40 instructions (outer yoshida4)
    serial[0] += 1
    c, d = paths("refused-%d" % serial[0])
    proc = tool.run("--problem", "outer", "--scheme", "yoshida4", "--members",
                    1, "--steps", 700000000, "--sample-every", 700000000,
                    *seg, "--quiet", "--cert", c, "--cert-states", d,
                    "--cert-open", expect_ok=False)
    check(refusal(proc) == ("program-image", 4) and "cft_program_load" in
          proc.stderr and not d.exists() and not c.exists() and
          not Path(str(c) + ".tmp").exists(),
          "refused program-image (exit 4), nothing made: a stride of 7e8 "
          "outer yoshida4 steps, past the loader's 2^40 instructions, with "
          "the library's sentence",
          "not refused program-image for a stride past 2^40 instructions: "
          "%s" % proc.stderr.strip()[-200:])
    # memory: what the certificate needs, sized by the run and taken before
    # anything is made - an interval count no size_t addresses hashes for,
    # and one whose hashes no process can hold: 2^52 intervals are 293 PB
    # of hashes, past an x86-64 process's address space (128 TiB, or 64
    # PiB with five-level paging), so no allocator gives them, whatever the
    # system's overcommit. 10^12 (65 TB) fits 47 bits, and Linux's
    # always-overcommit would grant it and run the 10^12 steps.
    for label, steps, sentence in (
            ("2^62 one-step intervals, more than a size_t counts the "
             "certificate's hashes for", 2 ** 62,
             "%d intervals of 2 members cannot be addressed" % 2 ** 62),
            ("2^52 one-step intervals, 293 PB of hashes, past an x86-64 "
             "process's address space", 2 ** 52, "the certificate's hashes "
             "and words for %d intervals, and a state of 64 bytes, could "
             "not be allocated" % 2 ** 52)):
        serial[0] += 1
        c, d = paths("refused-%d" % serial[0])
        proc = tool.run(*short, "--steps", steps, "--sample-every", 1, *seg,
                        "--cert", c, "--cert-states", d, "--cert-open",
                        expect_ok=False)
        check(refusal(proc) == ("memory", NAMES["memory"]) and
              sentence in proc.stderr and not c.exists() and
              not d.exists() and not Path(str(c) + ".tmp").exists(),
              "refused memory (exit 71), nothing made: %s" % label,
              "not refused memory (exit 71) with nothing made: %s - %s, "
              "exit %d, %s" % (label, refusal(proc)[0], proc.returncode,
                               proc.stderr.strip()[-200:]))
    for label, cpath, dpath, name in (
            ("--cert already there", there, work / "new-1.states", "output"),
            ("--cert-states already there", work / "new-2.cert", there_dir,
             "output"),
            ("--cert inside a --cert-states not made yet",
             work / "new-3.states" / "c.cert", work / "new-3.states",
             "output")):
        before = there.read_bytes()
        proc = tool.run(*short, *seg, "--cert", cpath, "--cert-states", dpath,
                        "--cert-open", expect_ok=False)
        check(refusal(proc) == (name, NAMES[name]) and
              there.read_bytes() == before and not list(there_dir.iterdir())
              and not (work / "new-1.states").exists() and
              not (work / "new-3.states").exists() and
              (cpath == there or not cpath.exists()) and
              not Path(str(cpath) + ".tmp").exists(),
              "refused %s (exit %d), nothing made or changed: %s"
              % (name, NAMES[name], label),
              "not refused %s: %s - %s" % (name, label,
                                           proc.stderr.strip()[-200:]))
    for plant, name in (("flags-unwritten", "device"),
                        ("flags-wide", "malformed")):
        serial[0] += 1
        c, d = paths("refused-%d" % serial[0])
        proc = tool.run(*short, *seg, "--cert", c, "--cert-states", d,
                        "--cert-open", expect_ok=False,
                        env=env_with(CFT_ORBITS_CERT_PLANT=plant))
        # refused during the run: DIR is left as far as it got - its image
        # and boundary 0 - with no certificate and no CERT.tmp
        left = sorted(p.name for p in d.iterdir()) if d.exists() else None
        check(refusal(proc) == (name, NAMES[name]) and not c.exists() and
              not Path(str(c) + ".tmp").exists() and
              left == ["run-0-boundary-0.bin", "run-0.cftp"] and
              "planted" in proc.stderr,
              "refused %s (exit %d) at the first segment: no certificate and "
              "no CERT.tmp, DIR left holding its image and boundary 0; the "
              "library's flag word taken as %s (CFT_ORBITS_CERT_PLANT)"
              % (name, NAMES[name], plant),
              "not refused %s under %s, or not with DIR left as far as the "
              "run got (%s, CERT.tmp %s): %s"
              % (name, plant, left,
                 "there" if Path(str(c) + ".tmp").exists() else "gone",
                 proc.stderr.strip()[-200:]))

    # --- what a resume refuses, with nothing changed ---------------------
    def stopped(tag, mode):
        """A certified run stopped at step 37: its checkpoint and states."""
        ck = work / (tag + ".ckpt")
        certify(tag, K, mode, "--stop-after-steps", 37, "--checkpoint", ck)
        return ck

    def snapshot(ck, d):
        return (ck.read_bytes(), sorted((p.name, p.read_bytes())
                                        for p in d.iterdir()))

    def resume_refused(label, tag, ck, mode_args, name, sentence=None,
                       env=None, exit_code=None, acc=ACC):
        c, d = paths(tag)
        before = snapshot(ck, d)
        proc = tool.run(*K, "--cert", c, "--cert-states", d, *mode_args, *acc,
                        "--checkpoint", ck, "--resume", expect_ok=False,
                        env=env)
        got = refusal(proc)
        if name:
            ok_ = got == (name, NAMES[name]) and (sentence is None or
                                                  sentence in proc.stderr)
        else:
            ok_ = proc.returncode == exit_code and sentence in proc.stderr
        check(ok_ and snapshot(ck, d) == before and not c.exists() and
              not Path(str(c) + ".tmp").exists(),
              "resume refused %s, nothing changed: %s"
              % (name or "(exit %d)" % exit_code, label),
              "resume not refused as it should be: %s - exit %d, %s"
              % (label, proc.returncode, proc.stderr.strip()[-240:]))

    ckk = stopped("rs-keyed", "keyed")
    cko = stopped("rs-open", "open")
    resume_refused("a keyed run resumed with --cert-open", "rs-keyed", ckk,
                   ["--cert-open"], "salt-missing")
    resume_refused("an open run resumed with --cert-salt", "rs-open", cko,
                   ["--cert-salt", salt_file], "salt-unexpected")
    resume_refused("a keyed run resumed with another salt", "rs-keyed", ckk,
                   ["--cert-salt", other_salt], "salt-commitment")
    # the build-id line edited, the sum made again: another build
    def another_build(body):
        lines = body.split("\n")
        i = next(i for i, l in enumerate(lines)
                 if l.startswith("cert build-id "))
        lines[i] = ("cert build-id commit=" + "0" * 40 +
                    " tracked=clean untracked=none")
        return "\n".join(lines)

    ck_id = work / "rs-identity.ckpt"
    ck_id.write_text(_resum(cko.read_text(), another_build), newline="\n")
    c_o, d_o = paths("rs-open")
    shutil.copytree(d_o, work / "rs-identity.states")
    resume_refused("a checkpoint whose run was certified on another build "
                   "(its build-id line changed, its sum made again)",
                   "rs-identity", ck_id, ["--cert-open"], "identity")
    # the states directory, each way wrong
    for label, name, fn in (
            ("a bit of a constant in the states directory's image flipped",
             "image-digest",
             lambda d: (d / "run-0.cftp").write_bytes(
                 _flip((d / "run-0.cftp").read_bytes(), 40))),
            ("boundary 1 removed", "state-missing",
             lambda d: (d / "run-0-boundary-1.bin").unlink()),
            ("boundary 1 changed", "state-hash",
             lambda d: (d / "run-0-boundary-1.bin").write_bytes(
                 bytes(len((d / "run-0-boundary-1.bin").read_bytes())))),
            ("boundary 1 a byte short", "state-shape",
             lambda d: (d / "run-0-boundary-1.bin").write_bytes(
                 (d / "run-0-boundary-1.bin").read_bytes()[:-1]))):
        serial[0] += 1
        tag = "rs-dir-%d" % serial[0]
        shutil.copytree(d_o, work / (tag + ".states"))
        ck = work / (tag + ".ckpt")
        shutil.copyfile(cko, ck)
        fn(work / (tag + ".states"))
        resume_refused(label, tag, ck, ["--cert-open"], name)
    # the checkpoint's `cert program-digest` line not this process's, its
    # sum made again: program-image (image-digest's) is the same digest,
    # so only a file written to pass the sum makes the two disagree
    serial[0] += 1
    tag = "rs-digest-%d" % serial[0]
    shutil.copytree(d_o, work / (tag + ".states"))
    ck = work / (tag + ".ckpt")
    ck.write_text(_resum(cko.read_text(), lambda b: re.sub(
        r"(?m)^cert program-digest [0-9a-f]{64}$",
        "cert program-digest " + "0" * 64, b)), newline="\n")
    resume_refused("a checkpoint whose `cert program-digest` is not this "
                   "process's (the line changed, its sum made again)", tag,
                   ck, ["--cert-open"], "program-digest")
    # accuracy-finite: an entry reads every state value it needs exactly,
    # and a NaN has no exact value. No run of this tool's makes one unless a
    # fault does ("Flags": the Newton route carries a NaN without a flag),
    # so the resume is handed one: a completed run's final checkpoint, its
    # certificate removed, boundary 0 given fp64's quiet NaN at lane 1 slot
    # 0, and the checkpoint's two hashes of it (`cert boundary 0`, segment
    # 0's start) and its sum made again. With no step left, the resume holds
    # boundary 0 to that hash, writes its final checkpoint again, the same
    # bytes, and refuses the entry: nothing is changed.
    serial[0] += 1
    tag = "rs-nan-%d" % serial[0]
    ck_nan = work / (tag + ".ckpt")
    proc, c, d = certify(tag, K, "open", "--checkpoint", ck_nan)
    if check(proc.returncode == 0 and c.exists(),
             "a run certified with its entries and a final checkpoint, for "
             "accuracy-finite",
             "the run for accuracy-finite failed (exit %d) %s"
             % (proc.returncode, proc.stderr[-200:])):
        c.unlink()
        b0 = d / "run-0-boundary-0.bin"
        state0 = b0.read_bytes()
        off = (1 * 4 + 0) * 8               # lane 1 slot 0, 4 slots of 8 bytes
        nan0 = state0[:off] + (0x7ff8 << 48).to_bytes(8, "little") + \
            state0[off + 8:]
        h_old, h_new = cert.state_hash(None, state0), cert.state_hash(None,
                                                                      nan0)
        text = ck_nan.read_text()
        b0.write_bytes(nan0)
        ck_nan.write_text(_resum(text, lambda b: b.replace(h_old, h_new)),
                          newline="\n")
        check(text.count(h_old) == 2, "boundary 0's hash is the checkpoint's "
              "twice, `cert boundary 0` and segment 0's start: both changed",
              "boundary 0's hash is in the checkpoint %d times, not 2"
              % text.count(h_old))
        resume_refused("a completed run's final checkpoint resumed with a NaN "
                       "at boundary 0, lane 1 slot 0 (its two hashes and its "
                       "sum made again) - the entry cannot take it exactly",
                       tag, ck_nan, ["--cert-open"], "accuracy-finite",
                       "lane 1 slot 0 of the initial state is nan")
    serial[0] += 1
    tag = "rs-nodir-%d" % serial[0]
    ck = work / (tag + ".ckpt")
    shutil.copyfile(cko, ck)
    c, d = paths(tag)
    proc = tool.run(*K, "--cert", c, "--cert-states", d, "--cert-open",
                    *ACC, "--checkpoint", ck, "--resume", expect_ok=False)
    check(refusal(proc) == ("output", 73) and not d.exists() and
          ck.read_bytes() == cko.read_bytes() and not c.exists() and
          not Path(str(c) + ".tmp").exists(),
          "resume refused output (exit 73), nothing changed or made: its "
          "states directory is not there",
          "resume without its states directory: %s"
          % proc.stderr.strip()[-200:])
    # a certificate states one set of entries: a resume asks for the same
    serial[0] += 1
    tag = "rs-entries-%d" % serial[0]
    shutil.copytree(d_o, work / (tag + ".states"))
    ck = work / (tag + ".ckpt")
    shutil.copyfile(cko, ck)
    resume_refused("a run certified with the angular-momentum entries, "
                   "resumed without --cert-accuracy", tag, ck,
                   ["--cert-open"], None, "the run was certified with "
                   "--cert-accuracy angular-momentum-drift, and this resume "
                   "asks for none", exit_code=2, acc=[])
    ck_plain = work / "rs-noentries.ckpt"
    certify("rs-noentries", K, "open", "--stop-after-steps", 37,
            "--checkpoint", ck_plain, entries=False)
    resume_refused("a run certified without entries, resumed with "
                   "--cert-accuracy angular-momentum-drift", "rs-noentries",
                   ck_plain, ["--cert-open"], None, "the run was certified "
                   "without accuracy entries", exit_code=2)
    # the checkpoint's own refusals: a sentence, and exit 2
    plain = work / "rs-plain.ckpt"
    tool.run(*K, "--stop-after-steps", 37, "--checkpoint", plain)
    serial[0] += 1
    tag = "rs-v2-%d" % serial[0]
    shutil.copytree(d_o, work / (tag + ".states"))
    resume_refused("an uncertified run's checkpoint (version 2) with --cert",
                   tag, plain, ["--cert-open"], None,
                   "the checkpoint is version 2, a run that was not "
                   "certified", exit_code=2)
    before = cko.read_bytes()
    proc = tool.run(*K, "--checkpoint", cko, "--resume", expect_ok=False)
    check(proc.returncode == 2 and "the checkpoint is version 3, a certified "
          "run's" in proc.stderr and cko.read_bytes() == before,
          "resume refused (exit 2), nothing changed: a certified run's "
          "checkpoint (version 3) without --cert",
          "a version-3 checkpoint resumed without --cert: exit %d, %s"
          % (proc.returncode, proc.stderr.strip()[-200:]))
    for label, fn, sentence in (
            ("a byte changed in its state lines",
             lambda t: t.replace("state 1 ", "state 1 1", 1),
             "is not the SHA-256 of what it follows"),
            ("cut a line short", lambda t: t[:-30] + "\n",
             "last line is not `sum`"),
            ("a line repeated, its sum made again",
             lambda t: _resum(t, lambda b: b.replace(
                 "cert lanes 4\n", "cert lanes 4\ncert lanes 4\n", 1)),
             "where this run's certificate has `steps 16`"),
            ("the last closed segment's flag word 16 made 99, its sum made "
             "again",
             lambda t: _resum(t, lambda b: b.replace(
                 " flags 16 status 0\ncert interval",
                 " flags 99 status 0\ncert interval", 1)),
             "flag word (0 to 31)"),
            ("the last closed segment's flag word 16 made 17, invalid "
             "raised, which this tool would have stopped at, its sum made "
             "again",
             lambda t: _resum(t, lambda b: b.replace(
                 " flags 16 status 0\ncert interval",
                 " flags 17 status 0\ncert interval", 1)),
             "stops a run at any flag but inexact"),
            ("the interval in progress's STATUS 0 made 1, its sum made "
             "again",
             lambda t: _resum(t, lambda b: b.replace(
                 "cert interval flags 16 status 0\n",
                 "cert interval flags 16 status 1\n", 1)),
             "stops a run at any STATUS bit"),
            # each value in its one spelling: the same value spelt another
            # way, which cft_from_decimal_char reads (verifier-W3)
            ("its step size h respelt with a leading 0, the same value, its "
             "sum made again",
             lambda t: _resum(t, lambda b: _respelt(b, "h ", 1, "zero")),
             "is this run's step size, not in its one spelling"),
            ("member 1's first state value respelt with an uppercase E, the "
             "same value, its sum made again",
             lambda t: _resum(t, lambda b: _respelt(b, "state 1 ", 2, "E")),
             "member 1's state value"),
            ("member 0's energy respelt with an uppercase E, the same value, "
             "its sum made again",
             lambda t: _resum(t, lambda b: _respelt(b, "inv 0 ", 2, "E")),
             "member 0's invariant")):
        serial[0] += 1
        tag = "rs-ck-%d" % serial[0]
        shutil.copytree(d_o, work / (tag + ".states"))
        ck = work / (tag + ".ckpt")
        ck.write_text(fn(cko.read_text()), newline="\n")
        resume_refused("a version-3 checkpoint " + label, tag, ck,
                       ["--cert-open"], None, sentence, exit_code=2)


def _flip(data, i):
    """`data` with bit 0 of byte i flipped."""
    return data[:i] + bytes([data[i] ^ 1]) + data[i + 1:]


def _angmom_terms(problem, masses, nb, nd):
    """The angular momentum's drift entries' terms, from the problem's
    structure alone: for each component k (z alone in the plane), body by
    body, m_b q_(k+1) v_(k+2) then -m_b q_(k+2) v_(k+1), indices mod 3, a
    state's slot c q_c and slot ncomp + c v_c; m_b the exact value of the
    mass --dump-setup states, and 1 for Kepler's test particle.
    -> [(label, ((coefficient, (slot, slot)), ...)), ...]"""
    ncomp = nb * nd
    out = []
    for k in ((2,) if nd == 2 else (0, 1, 2)):
        k1, k2 = (k + 1) % 3, (k + 2) % 3
        terms = []
        for b in range(nb):
            m = Fraction(1) if problem == "kepler" else Fraction(masses[b])
            terms.append((m, (b * nd + k1, ncomp + b * nd + k2)))
            terms.append((-m, (b * nd + k2, ncomp + b * nd + k1)))
        out.append(("angular-momentum-" + "xyz"[k], tuple(terms)))
    return out


def _widest(terms, fmt, first, last, nslots, lanes):
    """The most bits a numerator and a denominator reach on the way to a
    drift entry's value, every value cert.derive computes, in its order:
    each element's, each product, each partial sum, each lane's drift.
    -> [numerator bits, denominator bits]"""
    from cft_golden import cert
    most = [0, 0]

    def note(q):
        most[0] = max(most[0], abs(q.numerator).bit_length())
        most[1] = max(most[1], q.denominator.bit_length())
        return q

    def q_of(state, i):
        q = Fraction(0)
        for c, slots in terms:
            p = note(c)
            for s in slots:
                v = note(cert.element_fraction(fmt, state[i * nslots + s])[1])
                p = note(p * v)
            q = note(q + p)
        return q
    for i in range(lanes):
        note(q_of(last, i) - q_of(first, i))
    return most


def _resum(text, fn):
    """A version-3 checkpoint's body edited by fn, its sum made again."""
    body = fn(text[:text.rindex("sum ")])
    return body + "sum " + hashlib.sha256(body.encode()).hexdigest() + "\n"


def _respelt(body, prefix, index, how):
    """`body` with token `index` of its first line that begins `prefix`
    spelt another way, the same value: a 0 put before its first digit
    ("zero"), or its exponent's e made E ("E")."""
    lines = body.split("\n")
    i = next(i for i, l in enumerate(lines) if l.startswith(prefix))
    tok = lines[i].split(" ")
    v = tok[index]
    if how == "zero":
        v = v[:1] + "0" + v[1:] if v[:1] == "-" else "0" + v
    else:
        assert "e" in v, v
        v = v.replace("e", "E", 1)
    tok[index] = v
    lines[i] = " ".join(tok)
    return "\n".join(lines)


def main():
    global CHECKS
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None)
    ap.add_argument("--audit", default=None,
                    help="cft-audit, for [8]; host/cft-audit by default")
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
    audit = args.audit
    if audit is None:
        for cand in ("cft-audit.exe", "cft-audit"):
            path = ROOT / "host" / cand
            if path.exists():
                audit = path
                break
    if audit is None or not Path(audit).exists():
        raise SystemExit("cft-audit not found, and [8] audits every "
                         "certificate with it - `make -C host orbitstest` "
                         "builds it")
    audit = Path(audit).resolve()
    tool = Tool(Path(exe).resolve())
    tmp = tempfile.mkdtemp(prefix="orbits-check-")

    periods = 2 if args.quick else 4
    sps = 256 if args.quick else 512

    # Every leg runs the tool as a user would unless it names a control
    # or an instrument itself, so none may leak in from the caller's
    # environment - [6b] holds that a run with none set behaves normally.
    stray = sorted(k for k in os.environ if k.startswith("CFT_ORBITS_"))
    for k in stray:
        del os.environ[k]

    try:
        print("cft-orbits cross-check, tool: %s" % exe)
        if stray:
            print("(removed from this check's environment: %s)"
                  % ", ".join(stray))
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
        rr = ratio(floors["fp64"], floors["fp256"])
        want_ratio = mpf(2) ** (237 - 53)
        check(want_ratio / 4096 < rr < want_ratio * 4096,
              "fp64's roundoff is %.3e times fp256's; 2^(237-53) is %.3e, "
              "so the two floors are the formats' own ratio and nothing "
              "else" % (float(rr), float(want_ratio)),
              "fp64/fp256 roundoff ratio %.3e is nowhere near 2^184 = %.3e"
              % (float(rr), float(want_ratio)))

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
            r = ratio(errs[0], errs[1])
            check(lo < r < hi,
                  "%s: halving h cut the error from the closed form by "
                  "%.2f, and order %d wants %d - %.3e at %d steps a period, "
                  "%.3e at %d"
                  % (scheme, float(r), order, 2 ** order,
                     float(errs[0]), sps_o, float(errs[1]), 2 * sps_o),
                  "%s: halving h changed the error by %.2f, which is not "
                  "order %d" % (scheme, float(r), order))
            # and the roundoff floor must be far below it
            gap = ratio(errs[1], floors["fp256"])
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
        lr = ratio(dl64, dl256)
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
              % (float(dev64), float(ratio(dev64, dev))),
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
        # Angular momentum is conserved EXACTLY by both schemes for
        # both problems: the drift moves q along v, which adds
        # m (v x v) = 0, and the kick's pair term m_i g_ij (q_i x q_j)
        # cancels against m_j g_ji (q_j x q_i) because m_i g_ij is
        # symmetric - which is Newton's third law. So the drift the
        # tool reports has NO truncation component at all and is a
        # bound on the ARITHMETIC alone. That makes it a certificate
        # rather than a diagnostic, and this is its gate.
        print("\n[4b] the angular-momentum certificate")
        for problem, extra, label in (
                ("kepler", ["--periods", 4, "--steps-per-period", 256],
                 "kepler, 1024 steps"),
                ("outer", ["--years", 20, "--days", 10],
                 "outer solar system, 730 steps")):
            for scheme in ("leapfrog", "yoshida4"):
                r = tool.csv("--problem", problem, "--scheme", scheme,
                             "--format", "fp256", "--members", 2, *extra)
                nst = int(r["steps"])
                bound = mpf(nst) ** 2 * mpf(2) ** -237 * 10 ** 6
                got = mpf(r["angmom_drift"])
                check(got < bound,
                      "%s, %s: |L-L0|/|L0| is %s, under the %.2e bound - "
                      "both schemes conserve L exactly, so this is the "
                      "arithmetic and nothing else"
                      % (label, scheme, r["angmom_drift"], float(bound)),
                      "%s, %s: the angular-momentum drift is %s, above the "
                      "%.2e bound - something other than rounding is moving "
                      "L" % (label, scheme, r["angmom_drift"], float(bound)))

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
        # The checkpoint's recbytes counts the record stream whether or
        # not --records writes it, so the file is the same either way -
        # an option is not a result - and it is the file's length.
        check(whole.read_bytes() == blobs[0] and
              _field_of(whole, "recbytes") == len(wrec.read_bytes()),
              "a run with --records ends on the same checkpoint as one "
              "without, and its recbytes (%s) is the records file's length"
              % _field_of(whole, "recbytes"),
              "with --records the checkpoint says recbytes %s and the file "
              "is %d bytes; without, recbytes %s - the checkpoints %s"
              % (_field_of(whole, "recbytes"), len(wrec.read_bytes()),
                 _field_of(Path(tmp) / "bs-8.ckpt", "recbytes"),
                 "match" if whole.read_bytes() == blobs[0] else "differ"))
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
        check_segments(tool, tmp)

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
                  % (why, (proc.stderr.strip().splitlines() or
                           [""])[0]),
                  "not refused: %s" % why)

        print("\n[7b] what --engine segments must refuse")
        env_nc = dict(os.environ, CFT_ORBITS_NEGATIVE_CONTROL="transpose")
        for why, argv, env, needle in (
            ("--rsqrt exact (whole-program divide and square root, no "
             "inliner to splice them)",
             ["--engine", "segments", "--rsqrt", "exact", "--periods", 1],
             None, "fragment inliner"),
            ("--segment-dump without --engine segments",
             ["--engine", "loop", "--periods", 1, "--segment-dump", tmp],
             None, "needs --engine segments"),
            ("the negative control on an engine it does not sabotage",
             ["--engine", "loop", "--periods", 1], env_nc,
             "sabotages --engine segments"),
            ("a negative control the tool does not have - a misspelt one "
             "must not run clean",
             ["--engine", "segments", "--periods", 1],
             dict(os.environ, CFT_ORBITS_NEGATIVE_CONTROL="transposed"),
             "takes transpose, zero-r2, uncapped, late-stop, overlong, "
             "append, flush-late or drop-flags"),
            ("=flush-late on --engine program, which cannot resume",
             ["--engine", "program", "--rsqrt", "newton", "--periods", 1],
             dict(os.environ, CFT_ORBITS_NEGATIVE_CONTROL="flush-late"),
             "--engine program cannot resume"),
            ("CFT_ORBITS_DIE_AFTER_CHECKPOINT on --engine program, which "
             "cannot resume",
             ["--engine", "program", "--rsqrt", "newton", "--periods", 1],
             dict(os.environ, CFT_ORBITS_DIE_AFTER_CHECKPOINT="1"),
             "--engine program cannot resume"),
            ("=append on --engine program, which cannot resume",
             ["--engine", "program", "--rsqrt", "newton", "--periods", 1],
             dict(os.environ, CFT_ORBITS_NEGATIVE_CONTROL="append"),
             "--engine program cannot resume"),
            ("CFT_ORBITS_SEGMENT_LIMIT on an engine it does not instrument",
             ["--engine", "loop", "--periods", 1],
             dict(os.environ, CFT_ORBITS_SEGMENT_LIMIT="7"),
             "instruments --engine segments and nothing else"),
            ("CFT_ORBITS_VIRTUAL_CLOCK on --engine program, which writes "
             "one checkpoint",
             ["--engine", "program", "--rsqrt", "newton", "--periods", 1],
             dict(os.environ, CFT_ORBITS_VIRTUAL_CLOCK="0.5"),
             "writes one, at the end"),
            ("CFT_ORBITS_SHARE_FIFO on a run with no records file",
             ["--engine", "loop", "--periods", 1],
             dict(os.environ, CFT_ORBITS_SHARE_FIFO="1"),
             "instruments the records file, and there is no --records"),
            ("CFT_ORBITS_CERT_PLANT on a run that is not certified",
             ["--engine", "segments", "--rsqrt", "newton", "--periods", 1],
             dict(os.environ, CFT_ORBITS_CERT_PLANT="flags-wide"),
             "instruments a certified run, and there is no --cert"),
            ("CFT_ORBITS_CERT_PLANT=width on a certified run with no entry",
             ["--engine", "segments", "--rsqrt", "newton", "--periods", 1,
              "--cert", Path(tmp) / "never.cert", "--cert-states",
              Path(tmp) / "never.states", "--cert-open"],
             dict(os.environ, CFT_ORBITS_CERT_PLANT="width"),
             "instruments an accuracy entry, and there is no "
             "--cert-accuracy"),
            ("CFT_ORBITS_NEGATIVE_CONTROL=drop-flags on a run that is not "
             "certified",
             ["--engine", "segments", "--rsqrt", "newton", "--periods", 1],
             dict(os.environ, CFT_ORBITS_NEGATIVE_CONTROL="drop-flags"),
             "sabotages a certified run's resume, and there is no --cert"),
            ("--records in a directory that is not there - the step, the "
             "file and the system's reason named",
             ["--engine", "loop", "--periods", 1, "--records",
              Path(tmp) / "no-such-directory" / "r.txt"],
             os.environ, "could not open the records file"),
        ):
            proc = tool.run(*argv, expect_ok=False, env=env)
            check(proc.returncode != 0 and needle in proc.stderr,
                  "refused: %s\n         (%s)"
                  % (why, (proc.stderr.strip().splitlines() or
                           [""])[-1]),
                  "not refused, or refused for another reason: %s (%s)"
                  % (why, proc.stderr.strip()[-160:]))
        # The test instruments take a number (CFT_ORBITS_SHARE_FIFO takes
        # 1 and nothing else), and anything else must be refused by name
        # rather than read as some number or as unset.
        for var, bad, needle in (
                ("CFT_ORBITS_SEGMENT_LIMIT",
                 ("0", "-7", "7x", " 7", "7.0", "0x10", "4294967296",
                  "99999999999999999999999"),
                 "takes a whole number of steps, 1 to 4294967295"),
                ("CFT_ORBITS_VIRTUAL_CLOCK",
                 ("0", "-0.5", "abc", " 0.5", "0.5s", "nan", "inf", "1e7"),
                 "takes a positive number of seconds a step"),
                ("CFT_ORBITS_DIE_AFTER_CHECKPOINT",
                 ("0", "-1", "1x", " 1", "1.0", "4294967296"),
                 "takes a whole number of checkpoints, 1 to 4294967295"),
                ("CFT_ORBITS_SHARE_FIFO",
                 ("0", "2", "01", " 1", "1 ", "yes", "true"),
                 "CFT_ORBITS_SHARE_FIFO takes 1"),
                ("CFT_ORBITS_CERT_PLANT",
                 ("flags", "Flags-wide", " width", "width ", "widths", "1"),
                 "CFT_ORBITS_CERT_PLANT takes flags-unreadable, "
                 "flags-unwritten, flags-wide or width")):
            ran = []
            for val in bad:
                proc = tool.run("--engine", "segments", "--rsqrt", "newton",
                                "--periods", 1, "--quiet", expect_ok=False,
                                env=dict(os.environ, **{var: val}))
                if not (proc.returncode == 2 and needle in proc.stderr):
                    ran.append("%r: exit %d" % (val, proc.returncode))
            check(not ran,
                  "refused: %s set to any of %d malformed values (%s)"
                  % (var, len(bad), ", ".join(repr(v) for v in bad)),
                  "%s: a malformed value was not refused by name - %s"
                  % (var, "; ".join(ran)))
        # --checkpoint-interval is a number of seconds, 0 or more. strtod
        # alone read "nan" as a clock that never came due (every segment
        # one step, no checkpoint until the end, on both engines), "abc"
        # as 0 and "1s" as 1 (verifier-V6, pre-existing).
        bad = ("nan", "inf", "-1", "-0.5", "abc", "1s", "", " 1", "+1",
               "1e999")
        ran = []
        for val in bad:
            for eng in ("loop", "segments"):
                proc = tool.run("--engine", eng, "--rsqrt", "newton",
                                "--periods", 1, "--quiet",
                                "--checkpoint-interval", val,
                                expect_ok=False)
                if not (proc.returncode == 2 and "--checkpoint-interval "
                        "takes a number of seconds, 0 or more" in
                        proc.stderr):
                    ran.append("%r on %s: exit %d" % (val, eng,
                                                     proc.returncode))
        check(not ran,
              "refused, on both engines: --checkpoint-interval %s"
              % ", ".join(repr(v) for v in bad),
              "--checkpoint-interval accepted a value that is not a number "
              "of seconds: %s" % "; ".join(ran))

        # -------------------------------------------------------------
        check_certificates(tool, tmp, audit)

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
