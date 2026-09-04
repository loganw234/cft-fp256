# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Score host/tools/enclose.c against an exact oracle.

    python3 host/tests/enclose_check.py [--exe PATH] [--quick]

The division of authority is the repository's usual one. The LIBRARY is
the authority on arithmetic: what `fma(x, y, c)` returns under
roundTowardNegative, and which flags it raises, is settled by
docs/DETERMINISM.md and by python/cft_golden, not by anything here.
PYTHON is the authority on the DOMAIN, and it can be, because every
quantity this workload encloses is one Python computes without
rounding:

  * a dot product of dyadic rationals is a rational, and `fractions`
    computes it exactly - which is why the tool's vectors are built out
    of small odd integers times powers of two rather than out of
    anything that merely looks random;
  * a polynomial with coefficients 1/k! at a dyadic point is a
    rational, so interval Horner's target is exact too;
  * exp(x) is not a rational, so THAT one gets mpmath at 300 digits -
    about 228 decimal digits more than a binary256 enclosure can carry,
    so the comparison is never close.

What that leaves for this file is the only question that matters for a
verified computation:

    IS THE TRUE VALUE INSIDE THE INTERVAL THE TOOL PRINTED?

An enclosure can be wrong in a way no internal check can see. The tool
asserts lo <= hi, and it asserts that a clean flag word implies a
zero width, and both are theorems - but a bound computed with the
attribute pointing the wrong way on BOTH sides satisfies every one of
them and is still not a bound. Only an independent computation of the
true value catches that, which is what the negative control in
docs/ENCLOSE.md demonstrates.

Nine properties are checked, and four of them are about the machine
rather than about the mathematics:

1. Containment.   Every enclosure at fp256, fp64 and fp32 against the
                  exact oracle, including the ill-conditioned dot
                  products where fp64 has nothing left.
2. Coefficients.  The interval coefficients the Horner kernel builds
                  must contain 1/k! - a prerequisite for its
                  containment claim, checked separately so a failure
                  says which of the two broke.
3. Tightness.     An enclosure that is valid but useless is a
                  regression, so every width is held below a few
                  thousand ulps of its own value.
4. Engines.       The sequencer-program route and the host cft_run loop
                  must produce byte-identical records for the Horner
                  kernel.
5. Batch size.    Three batch sizes over the same work must end on
                  byte-identical checkpoints AND byte-identical records.
6. Interruption.  A run stopped every few passes and resumed, at a
                  different batch size, must end on the same checkpoint
                  as one that was never stopped - and the stops must
                  land mid-item, inside the series recurrence, or the
                  in-flight state was never exercised.
7. The chain.     Recomputed with hashlib, which is what proves the
                  tool's from-first-principles derivation of SHA-256's
                  round constants right.
8. Formats.       fp256 against fp64 on the same data: the numbers that
                  say what fp64 loses.
9. Refusals.      A degree the sixteen-constant bank cannot hold, a
                  point count that is not a power of two, and a format
                  whose exponent range cannot carry the condition
                  ladder are all refused rather than approximated.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from math import factorial
from pathlib import Path

import mpmath

ROOT = Path(__file__).resolve().parents[2]

FAILURES = []
CHECKS = 0


def fail(what):
    FAILURES.append(what)
    print("  FAIL: " + what)


def ok(what):
    print("  ok   " + what)


# ---------------------------------------------------------------------
# Exact parsing of what the tool writes
#
# cft_to_hex_char produces the shortest sequence that represents the
# value EXACTLY (754-2019 5.12.3), so reading it back into a Fraction
# loses nothing - which is the only reason this file can claim to check
# containment rather than approximate it.
# ---------------------------------------------------------------------
def hex_to_fraction(s):
    t = s.strip()
    neg = False
    if t[0] in "+-":
        neg = t[0] == "-"
        t = t[1:]
    if not t.lower().startswith("0x"):
        raise ValueError("not a hexadecimal sequence: %r" % s)
    t = t[2:]
    if "p" in t:
        mant, _, ex = t.partition("p")
    elif "P" in t:
        mant, _, ex = t.partition("P")
    else:
        raise ValueError("no binary exponent: %r" % s)
    exp = int(ex)
    ip, _, fp = mant.partition(".")
    digits = ip + fp
    v = Fraction(int(digits, 16) if digits else 0, 1)
    v /= Fraction(16) ** len(fp)
    v *= Fraction(2) ** exp
    return -v if neg else v


def frac_to_mpf(v):
    """Exact, for a dyadic v: mpmath at 300 digits holds far more bits
    than any of these formats carries."""
    return mpmath.mpf(v.numerator) / mpmath.mpf(v.denominator)


PREC = {"fp32": 24, "fp64": 53, "fp128": 113, "fp256": 237}


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
            raise RuntimeError("cft-enclose %s failed (%d)\n%s\n%s"
                               % (" ".join(str(a) for a in args),
                                  proc.returncode, proc.stdout, proc.stderr))
        return proc


def read_records(path):
    out = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        f = line.split()
        out.append({
            "raw": line,
            "kernel": f[0],
            "item": int(f[1]),
            "lo": hex_to_fraction(f[2]),
            "hi": hex_to_fraction(f[3]),
            "w": hex_to_fraction(f[4]),
            "exact": f[5] == "exact",
        })
    return out


def read_vectors(path):
    cases = {}
    which = None
    for line in Path(path).read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split()
        if f[0] == "vec":
            which = int(f[1])
            cases[which] = {"name": f[2], "x": [], "y": []}
        elif f[0] == "xy":
            cases[which]["x"].append(hex_to_fraction(f[1]))
            cases[which]["y"].append(hex_to_fraction(f[2]))
    return cases


def read_coeffs(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        f = line.split()
        if f[0] == "coef":
            out[int(f[1])] = (hex_to_fraction(f[2]), hex_to_fraction(f[3]))
    return out


def ckpt_field(path, key):
    for line in Path(path).read_text().splitlines():
        if line.startswith(key + " "):
            return line[len(key) + 1:]
    return None


def chain_of(lines):
    h = bytes(32)
    for line in lines:
        h = hashlib.sha256(h + (line + "\n").encode("ascii")).digest()
    return h.hex()


# ---------------------------------------------------------------------
# The oracle
# ---------------------------------------------------------------------
def series_point(j, points):
    return Fraction(j, points)


def horner_point(j, points):
    return Fraction(2 * j, points) - 1


def taylor_exact(x, degree):
    """T_d(x) = sum x^k / k!, an exact rational at a dyadic x."""
    s = Fraction(0)
    xp = Fraction(1)
    for k in range(degree + 1):
        s += xp / factorial(k)
        xp *= x
    return s


def dot_exact(xs, ys):
    return sum((a * b for a, b in zip(xs, ys)), Fraction(0))


# ---------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------
def check_containment(tool, tmp, fmt, kernels, points, degree, engine,
                      batch, tag):
    """Every enclosure of one run against the exact oracle."""
    global CHECKS
    p = PREC[fmt]
    base = Path(tmp) / ("%s-%s" % (fmt, tag))
    recs_path = str(base) + ".rec"
    vec_path = str(base) + ".vec"
    coef_path = str(base) + ".coef"
    args = ["--format", fmt, "--kernels", ",".join(kernels),
            "--points", points, "--degree", degree, "--engine", engine,
            "--batch", batch, "--records", recs_path, "--quiet"]
    if "dot" in kernels:
        args += ["--dump-vectors", vec_path]
    if "horner" in kernels:
        args += ["--dump-coeffs", coef_path]
    tool.run(*args)
    recs = read_records(recs_path)
    vecs = read_vectors(vec_path) if "dot" in kernels else {}
    coefs = read_coeffs(coef_path) if "horner" in kernels else {}

    # 2. the interval coefficients must contain 1/k! before the Horner
    #    enclosures can be believed
    if coefs:
        bad = []
        for k, (clo, chi) in sorted(coefs.items()):
            CHECKS += 1
            true = Fraction(1, factorial(k))
            if not (clo <= true <= chi):
                bad.append(k)
        if bad:
            fail("%s %s: the coefficient enclosure misses 1/k! at k = %s"
                 % (fmt, tag, bad[:4]))
        else:
            ok("%s %s: all %d interval coefficients contain 1/k! exactly"
               % (fmt, tag, len(coefs)))

    mpmath.mp.dps = 300
    counts = {}
    worst = {}          # kernel -> (worst ratio of width to its budget)
    for r in recs:
        CHECKS += 1
        k = r["kernel"]
        counts[k] = counts.get(k, 0) + 1
        if r["lo"] > r["hi"]:
            fail("%s %s: %s item %d has its ends the wrong way round"
                 % (fmt, tag, k, r["item"]))
            continue
        if r["exact"] != (r["lo"] == r["hi"]):
            fail("%s %s: %s item %d is labelled %s but lo %s hi"
                 % (fmt, tag, k, r["item"],
                    "exact" if r["exact"] else "strict",
                    "==" if r["lo"] == r["hi"] else "!="))
        if r["w"] < r["hi"] - r["lo"]:
            fail("%s %s: %s item %d reports a width below the real one"
                 % (fmt, tag, k, r["item"]))

        # The tightness budget is per kernel, because the scale a width
        # should be measured against is not always the answer's own. A
        # dot product with heavy cancellation has an answer far smaller
        # than any of its terms, and the honest budget there is a few
        # ulps per addition of the LARGEST partial magnitude - which is
        # exactly what the fp64 column of this workload is about.
        if k == "series":
            x = series_point(r["item"], int(points))
            v = mpmath.exp(frac_to_mpf(Fraction(x)))
            inside = frac_to_mpf(r["lo"]) <= v <= frac_to_mpf(r["hi"])
            budget = abs(v) * 4096.0 * 2.0 ** (1 - p)
        elif k == "horner":
            x = horner_point(r["item"], int(points))
            v = taylor_exact(x, int(degree))
            inside = r["lo"] <= v <= r["hi"]
            budget = abs(frac_to_mpf(v)) * 4096.0 * 2.0 ** (1 - p)
        else:
            case = vecs[r["item"]]
            v = dot_exact(case["x"], case["y"])
            inside = r["lo"] <= v <= r["hi"]
            scale = sum((abs(a * b) for a, b in zip(case["x"], case["y"])),
                        Fraction(0))
            budget = (frac_to_mpf(scale) * 8.0 * len(case["x"]) *
                      2.0 ** (1 - p))
        if not inside:
            fail("%s %s: %s item %d does not contain the true value "
                 "(lo %s, hi %s)" % (fmt, tag, k, r["item"],
                                     float(r["lo"]), float(r["hi"])))
            continue
        if budget > 0:
            ratio = float(frac_to_mpf(r["hi"] - r["lo"]) / budget)
            worst[k] = max(worst.get(k, 0.0), ratio)

    if vecs:
        CHECKS += 1
        zero = [r for r in recs if r["kernel"] == "dot" and r["item"] == 0]
        if zero and zero[0]["exact"] and zero[0]["lo"] ==                 dot_exact(vecs[0]["x"], vecs[0]["y"]):
            ok("%s %s: the exact-by-construction dot product came back "
               "with width zero, so both bounds ARE the rational value"
               % (fmt, tag))
        else:
            fail("%s %s: the exact-by-construction dot product did not "
                 "come back exact" % (fmt, tag))

    for k in sorted(counts):
        CHECKS += 1
        if worst.get(k, 0.0) > 1.0:
            fail("%s %s: the %s kernel's widest enclosure is %.1fx its "
                 "rounding budget - valid, but wider than the arithmetic "
                 "can explain" % (fmt, tag, k, worst[k]))
        else:
            ok("%s %s: %d %s enclosures all contain the true value, "
               "widest %.2f%% of its rounding budget"
               % (fmt, tag, counts[k], k, 100.0 * worst.get(k, 0.0)))
    return recs


def check_engines(tool, tmp, fmt, points, degree):
    global CHECKS
    got = {}
    for engine, batch in (("program", 64), ("loop", 37)):
        path = Path(tmp) / ("eng-%s.rec" % engine)
        tool.run("--format", fmt, "--kernels", "horner", "--points", points,
                 "--degree", degree, "--engine", engine, "--batch", batch,
                 "--records", path, "--quiet")
        got[engine] = path.read_bytes()
    CHECKS += 1
    if got["program"] == got["loop"]:
        ok("%s: the sequencer program and the host cft_run loop produce "
           "byte-identical Horner records, at different batch sizes"
           % fmt)
    else:
        fail("%s: the two Horner engines disagree" % fmt)


def check_batch_independence(tool, tmp, fmt, points, batches):
    global CHECKS
    blobs, recs = [], []
    for b in batches:
        cp = Path(tmp) / ("bs-%d.ckpt" % b)
        rp = Path(tmp) / ("bs-%d.rec" % b)
        tool.run("--format", fmt, "--points", points, "--batch", b,
                 "--checkpoint", cp, "--records", rp, "--quiet")
        blobs.append(cp.read_bytes())
        recs.append(rp.read_bytes())
    CHECKS += 2
    if len(set(blobs)) == 1:
        ok("%s: batches %s end on byte-identical checkpoints (%s)"
           % (fmt, ", ".join(str(b) for b in batches),
              ckpt_field(Path(tmp) / ("bs-%d.ckpt" % batches[0]),
                         "chain")[:16]))
    else:
        fail("%s: the checkpoints differ across batch sizes" % fmt)
    if len(set(recs)) == 1:
        ok("%s: and byte-identical record streams" % fmt)
    else:
        fail("%s: the records differ across batch sizes" % fmt)
    return blobs[0]


def check_resume(tool, tmp, fmt, points, whole_blob):
    """A stop every few passes lands INSIDE the series recurrence, with
    partly-summed terms in flight - which is the state a resume that
    only ever restarted on a batch boundary would never exercise."""
    global CHECKS
    piece = Path(tmp) / "piece.ckpt"
    common = ["--format", fmt, "--points", points, "--batch", 23,
              "--stop-after-passes", 4, "--checkpoint", piece, "--quiet"]
    tool.run(*common)
    rounds = 0
    saw_inflight = 0
    total = ckpt_field(piece, "items")
    while True:
        rounds += 1
        if rounds > 5000:
            fail("%s: the resumed run did not finish" % fmt)
            return
        if int(ckpt_field(piece, "inflight").split()[0]) > 0:
            saw_inflight += 1
        tool.run("--resume", *common)
        if ckpt_field(piece, "cursor") == total:
            break
    CHECKS += 2
    if saw_inflight:
        ok("%s: %d of %d interruptions caught a series item part way "
           "through its recurrence" % (fmt, saw_inflight, rounds))
    else:
        fail("%s: no interruption landed mid-item, so the in-flight state "
             "was never exercised" % fmt)
    if piece.read_bytes() == whole_blob:
        ok("%s: a run stopped and resumed %d times, at a different batch "
           "size, ends on the same checkpoint - byte for byte - as one "
           "that was never stopped" % (fmt, rounds))
    else:
        fail("%s: the resumed run's checkpoint differs from the "
             "uninterrupted one" % fmt)


def check_chain(tool, tmp, fmt, points, recs):
    global CHECKS
    rp = Path(tmp) / "chain.rec"
    cp = Path(tmp) / "chain.ckpt"
    tool.run("--format", fmt, "--points", points, "--batch", 91,
             "--records", rp, "--checkpoint", cp, "--quiet")
    lines = [ln for ln in rp.read_text().splitlines() if ln.strip()]
    CHECKS += 1
    if ckpt_field(cp, "chain") == chain_of(lines):
        ok("%s: the tool's chain over %d records matches hashlib's - so "
           "its derivation of SHA-256's constants from the cube roots of "
           "the primes is right" % (fmt, len(lines)))
    else:
        fail("%s: chain mismatch: tool %s, hashlib %s"
             % (fmt, ckpt_field(cp, "chain"), chain_of(lines)))


def check_formats(tool, tmp, points, degree):
    """The number the whole workload exists to produce: what fp64 has
    left on a kernel fp256 still resolves."""
    global CHECKS
    out = {}
    for fmt in ("fp64", "fp256"):
        rp = Path(tmp) / ("fmt-%s.rec" % fmt)
        vp = Path(tmp) / ("fmt-%s.vec" % fmt)
        tool.run("--format", fmt, "--points", points, "--degree", degree,
                 "--batch", 64, "--records", rp, "--dump-vectors", vp,
                 "--quiet")
        out[fmt] = (read_records(rp), read_vectors(vp))

    # the two runs must have been given the same numbers, or the
    # comparison is between two different problems
    CHECKS += 1
    same = all(out["fp64"][1][i]["x"] == out["fp256"][1][i]["x"] and
               out["fp64"][1][i]["y"] == out["fp256"][1][i]["y"]
               for i in out["fp64"][1])
    if same:
        ok("fp64 and fp256 were handed the same dot vectors, exactly")
    else:
        fail("the two formats were handed different vectors")
        return

    for kernel in ("series", "dot", "horner"):
        a = [r for r in out["fp64"][0] if r["kernel"] == kernel]
        b = [r for r in out["fp256"][0] if r["kernel"] == kernel]
        wa = max(r["w"] for r in a)
        wb = max(r["w"] for r in b)
        CHECKS += 1
        if wb < wa:
            ok("%-6s widest width  fp64 %-12.4g  fp256 %-12.4g  "
               "ratio 2^%.0f" % (kernel, float(wa), float(wb),
                                 (mpmath.log(frac_to_mpf(wa) /
                                             frac_to_mpf(wb), 2)
                                  if wb else 0)))
        else:
            fail("%s: fp256's widest enclosure is not narrower than "
                 "fp64's" % kernel)

    # the ill-conditioned rows, where fp64 has nothing left at all
    n64 = sum(1 for r in out["fp64"][0]
              if r["kernel"] == "dot" and r["lo"] <= 0 <= r["hi"])
    n256 = sum(1 for r in out["fp256"][0]
               if r["kernel"] == "dot" and r["lo"] <= 0 <= r["hi"])
    CHECKS += 1
    if n64 > 0 and n256 == 0:
        ok("%d of the dot enclosures straddle zero at fp64 - the sign of "
           "the answer is not determined - and none of them do at fp256"
           % n64)
    else:
        fail("the ill-conditioned dot ladder did not separate the two "
             "formats: fp64 straddles %d, fp256 straddles %d"
             % (n64, n256))
    return out


def check_refusals(tool):
    global CHECKS
    cases = [
        (["--degree", 12],
         "a degree the sixteen-constant bank cannot hold"),
        (["--points", 100],
         "a point count that is not a power of two"),
        (["--format", "fp32"],
         "a format whose exponent range cannot carry the condition "
         "ladder"),
        (["--kernels", "nonsense"],
         "an unknown kernel name"),
    ]
    for args, what in cases:
        CHECKS += 1
        proc = tool.run("--points", 8, "--quiet", *args, expect_ok=False)
        if proc.returncode != 0:
            ok("%s is refused, not approximated" % what)
        else:
            fail("%s was accepted" % what)


def main():
    global CHECKS
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    exe = args.exe
    if exe is None:
        for cand in ("cft-enclose.exe", "cft-enclose"):
            path = ROOT / "host" / cand
            if path.exists():
                exe = path
                break
    if exe is None or not Path(exe).exists():
        raise SystemExit("cft-enclose not found - run `make -C host enclose`")
    tool = Tool(exe)

    points = 32 if args.quick else 64
    degree = 23
    tmp = tempfile.mkdtemp(prefix="enclose-check-")
    try:
        print("cft-enclose cross-check, tool: %s" % exe)
        print("mpmath %s at 300 digits; exact rationals elsewhere"
              % mpmath.__version__)

        print("\n[1] containment against the exact oracle")
        check_containment(tool, tmp, "fp256", ("series", "dot", "horner"),
                          points, degree, "program", 64, "all")
        check_containment(tool, tmp, "fp64", ("series", "dot", "horner"),
                          points, degree, "program", 17, "all")
        check_containment(tool, tmp, "fp256", ("horner",), points, degree,
                          "loop", 9, "loop")
        # binary32 cannot carry the dot ladder's exponent spread, which
        # is checked as a refusal below; its two point kernels are the
        # end of the ladder where precision runs out first.
        check_containment(tool, tmp, "fp32", ("series", "horner"), points,
                          degree, "program", 32, "narrow")

        print("\n[2] the two Horner engines")
        check_engines(tool, tmp, "fp256", points, degree)
        check_engines(tool, tmp, "fp64", points, degree)

        print("\n[3] batch-size independence")
        whole = check_batch_independence(tool, tmp, "fp256", points,
                                         (7, 64, 1024))

        print("\n[4] interrupting and resuming")
        check_resume(tool, tmp, "fp256", points, whole)

        print("\n[5] the hash chain")
        check_chain(tool, tmp, "fp64", points, None)

        print("\n[6] what fp64 loses")
        check_formats(tool, tmp, points, degree)

        print("\n[7] refusals")
        check_refusals(tool)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d comparisons, %d failures" % (CHECKS, len(FAILURES)))
    if FAILURES:
        print("ENCLOSE CHECK FAILED")
        return 1
    print("ENCLOSE CHECK OK - every enclosure contains the value the "
          "oracle computed, and the same bits come out at every batch "
          "size, from either engine, interrupted or not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
