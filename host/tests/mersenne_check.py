# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Score host/tools/mersenne.c against a Python big-integer oracle.

    python3 host/tests/mersenne_check.py [--exe PATH] [--quick] [--full]

The division of authority is the repository's usual one. The LIBRARY is
the authority on arithmetic: what `cft_reduce(CFT_DOT)` returns and
which flags it raises is settled by docs/DETERMINISM.md and by
python/cft_golden, not by anything here. PYTHON is the authority on
Lucas-Lehmer, because its integers are exact and unbounded, so an
oracle written in them cannot be wrong about a residue.

What that leaves for this file is the join, and it is a stricter join
than the Collatz check's, because a Lucas-Lehmer verdict is one bit and
one bit is easy to get right by accident. So the oracle does not only
compare verdicts:

  * it recomputes s_k for EVERY k the tool dumps and compares the whole
    residue - a SHA-256 over the canonical limbs, not a window of it -
    so a wrong carry shows at the first squaring that breaks it rather
    than 1,275 squarings later;
  * it compares res64, the low 64 bits of the canonical residue, which
    is what every other Lucas-Lehmer implementation in the world
    reports, so the composite controls are checked against a number
    that was never derived from this tool;
  * and it checks the verdicts in BOTH directions - 1277 and 1619 are
    prime exponents whose Mersenne numbers are composite, so a tool
    that always said "prime" would fail here even though it would pass
    a test set of Mersenne primes alone.

Seven properties, and four of them are about the machine rather than
about Mersenne numbers:

1. Results.       Every verdict, squaring count and res64 against the
                  oracle, at fp256 and fp64.
2. Residues.      Every intermediate residue, whole, at every dump
                  point.
3. Engines.       The sequencer-program route and the host cft_run loop
                  must produce identical chains and identical residues.
4. Formats.       fp32, fp64, fp128 and fp256 must produce the same
                  chain - the record is deliberately format-independent,
                  so this is the ladder's one contract seen from
                  outside.
5. Batch size.    Different --batch values over the same work must end
                  on byte-identical checkpoints.
6. Interruption.  A run stopped mid-exponent and resumed, at a
                  different batch size, must end on the same checkpoint
                  as one that was never stopped.
7. The bound.     An accumulation built to cross 2^p must raise
                  inexact; a limb width the bound forbids must be
                  refused; and forcing one past the refusal must be
                  stopped by the LIBRARY's flag rather than by the
                  tool's arithmetic.

And the hash chain is recomputed here with hashlib, which is what
proves the tool's from-first-principles derivation of SHA-256's round
constants right.
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FAILURES = []
CHECKS = 0


def fail(what):
    FAILURES.append(what)
    print("  FAIL: " + what)


def ok(what):
    print("  ok   " + what)


# ---------------------------------------------------------------------
# The oracle
# ---------------------------------------------------------------------
def lucas_lehmer(P, upto=None):
    """Yield (k, s_k) for the Lucas-Lehmer sequence mod 2^P - 1.

    s_0 = 4, s_{k+1} = s_k^2 - 2 mod (2^P - 1), and 2^P - 1 is prime
    exactly when s_{P-2} == 0. Python's integers are exact, so this is
    the definition of the answer.
    """
    m = (1 << P) - 1
    s = 4 % m
    yield 0, s
    n = P - 2 if upto is None else min(upto, P - 2)
    for k in range(1, n + 1):
        s = (s * s - 2) % m
        yield k, s


def final_residue(P):
    s = 0
    for _k, s in lucas_lehmer(P):
        pass
    return s


def canonical_limbs(R, b, L):
    """The tool's canonical representation of the residue R.

    The residue is carried in L limbs of b bits with L*b >= P; the
    canonical representative is the one below 2^P, so every limb is
    just a window of R.
    """
    mask = (1 << b) - 1
    return [(R >> (k * b)) & mask for k in range(L)]


def residue_digest(R, b, L):
    h = hashlib.sha256()
    for x in canonical_limbs(R, b, L):
        h.update(("%d\n" % x).encode("ascii"))
    return h.hexdigest()


def res64(R):
    return R & ((1 << 64) - 1)


def oracle_record(P):
    s = final_residue(P)
    return "%d %s %d %016x" % (P, "prime" if s == 0 else "composite",
                               P - 2, res64(s))


def chain_of(lines):
    h = bytes(32)
    for line in lines:
        h = hashlib.sha256(h + (line + "\n").encode("ascii")).digest()
    return h.hex()


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
            raise RuntimeError("cft-mersenne %s failed (%d)\n%s\n%s"
                               % (" ".join(str(a) for a in args),
                                  proc.returncode, proc.stdout, proc.stderr))
        return proc

    def csv(self, *args):
        out = self.run(*args, "--csv").stdout.strip().splitlines()
        if len(out) < 2:
            raise RuntimeError("the tool printed no csv row")
        head = out[0].split(",")
        row = dict(zip(head, out[1].split(",")))
        rows = []
        for line in out[2:]:
            f = line.split(",")
            if f[0] == "exponent":
                rows.append("%s %s %s %s" % (f[1], f[2], f[3], f[4]))
        return row, rows


def read_field(path, key):
    for line in Path(path).read_text().splitlines():
        if line.startswith(key + " "):
            return line[len(key) + 1:]
    return None


# ---------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------
def check_results(tool, exps, fmt, engine, batch, label):
    global CHECKS
    try:
        row, rows = tool.csv("--exponents", ",".join(str(e) for e in exps),
                             "--format", fmt, "--engine", engine,
                             "--batch", batch)
    except RuntimeError as exc:
        CHECKS += 1
        fail("%s: the tool refused to finish - %s"
             % (label, str(exc).strip().splitlines()[-1]))
        return None, []
    want = [oracle_record(e) for e in exps]
    CHECKS += len(want)
    if rows != want:
        for a, b in zip(rows, want):
            if a != b:
                fail("%s: got '%s', oracle says '%s'" % (label, a, b))
                return row, rows
        fail("%s: %d records, oracle has %d" % (label, len(rows), len(want)))
        return row, rows
    prime = sum(1 for w in want if " prime " in w)
    ok("%s: %d exponents match the big-integer oracle - %d prime, %d "
       "composite, res64 included"
       % (label, len(want), prime, len(want) - prime))
    return row, rows


def check_residues(tool, tmp, P, fmt, engine, every, upto, label):
    """Every intermediate residue, whole, against Python's."""
    global CHECKS
    path = Path(tmp) / ("dump-%d-%s-%s.txt" % (P, fmt, engine))
    try:
        tool.run("--exponents", P, "--format", fmt, "--engine", engine,
                 "--dump-residues", path, "--dump-every", every,
                 "--max-squarings", upto, "--quiet")
    except RuntimeError as exc:
        CHECKS += 1
        fail("%s: the tool refused to finish - %s"
             % (label, str(exc).strip().splitlines()[-1]))
        return
    got = {}
    geom = None
    for line in path.read_text().splitlines():
        f = line.split()
        if len(f) != 6:
            continue
        got[int(f[1])] = (int(f[2]), int(f[3]), f[4], f[5])
        geom = (int(f[2]), int(f[3]))
    if not got:
        CHECKS += 1
        fail("%s: the tool dumped no residues" % label)
        return
    b, L = geom
    bad = 0
    seen = 0
    for k, s in lucas_lehmer(P, upto=upto):
        if k not in got:
            continue
        seen += 1
        CHECKS += 1
        wb, wL, wr64, wdg = got[k]
        want_r64 = "%016x" % res64(s)
        want_dg = residue_digest(s, wb, wL)
        if (wr64, wdg) != (want_r64, want_dg):
            bad += 1
            if bad == 1:
                fail("%s: residue after squaring %d differs - tool "
                     "res64 %s digest %s, oracle res64 %s digest %s"
                     % (label, k, wr64, wdg[:16], want_r64, want_dg[:16]))
    if seen != len(got):
        CHECKS += 1
        fail("%s: the dump has %d residues the oracle never reached"
             % (label, len(got) - seen))
    elif not bad:
        ok("%s: %d intermediate residues match whole, at b = %d, L = %d "
           "(res64 and a SHA-256 over every limb)" % (label, seen, b, L))


def main():
    global CHECKS
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--full", action="store_true",
                    help="add the larger exponents; minutes, not seconds")
    args = ap.parse_args()

    exe = args.exe
    if exe is None:
        for cand in ("cft-mersenne.exe", "cft-mersenne"):
            path = ROOT / "host" / cand
            if path.exists():
                exe = path
                break
    if exe is None or not Path(exe).exists():
        raise SystemExit("cft-mersenne not found - run `make -C host mersenne`")
    tool = Tool(exe)

    # 521 and 607 are Mersenne prime exponents; 1277 and 1619 are prime
    # exponents whose Mersenne numbers are NOT prime, and they are here
    # so the verdict is scored in both directions; 1279 is the next
    # Mersenne prime up.
    exps = [521, 607, 1277, 1279, 1619]
    if args.quick:
        exps = [521, 607, 1277]
    if args.full:
        exps = exps + [2203, 2281, 3217]

    tmp = tempfile.mkdtemp(prefix="mersenne-check-")
    try:
        print("cft-mersenne cross-check, tool: %s" % exe)

        # 1. verdicts, squaring counts and res64
        print("\n[1] results against the big-integer oracle")
        row_p, rows_p = check_results(tool, exps, "fp256", "program", 4096,
                                      "fp256, sequencer program")
        row_l, rows_l = check_results(tool, exps, "fp256", "loop", 97,
                                      "fp256, host cft_run loop")
        row_64, rows_64 = check_results(tool, exps, "fp64", "program", 251,
                                        "fp64, sequencer program")

        # 2. every intermediate residue, whole
        print("\n[2] the residues, not only the verdicts")
        check_residues(tool, tmp, 1277, "fp256", "program", 1, 250,
                       "fp256 program, 2^1277 - 1, every squaring to 250")
        check_residues(tool, tmp, 1277, "fp256", "loop", 7, 250,
                       "fp256 loop, 2^1277 - 1, every 7th squaring to 250")
        check_residues(tool, tmp, 607, "fp64", "program", 5, 300,
                       "fp64 program, 2^607 - 1, every 5th squaring to 300")
        check_residues(tool, tmp, 521, "fp32", "program", 11, 120,
                       "fp32 program, 2^521 - 1, every 11th squaring to 120")

        # 3. the two engines
        print("\n[3] the two engines, and the format ladder")
        CHECKS += 1
        if row_p and row_l and row_p["chain"] == row_l["chain"]:
            ok("the sequencer program and the host cft_run loop return the "
               "same chain over %d exponents (%s)"
               % (len(exps), row_p["chain"][:16]))
        else:
            fail("the two engines disagree")

        # 4. the ladder. The record is the exponent, the verdict, the
        #    squaring count and res64 - none of which mentions a format
        #    - so every rung must agree even though the limb geometry is
        #    completely different on each.
        ladders = [("fp128", 1279), ("fp64", 1279), ("fp32", 521)]
        for fmt, P in ladders:
            CHECKS += 1
            try:
                r256, _ = tool.csv("--exponents", P, "--format", "fp256")
                rX, _ = tool.csv("--exponents", P, "--format", fmt)
            except (RuntimeError, IndexError) as exc:
                fail("%s at P = %d refused to run - %s"
                     % (fmt, P, str(exc).strip().splitlines()[-1]))
                continue
            if r256["chain"] == rX["chain"]:
                ok("%s and fp256 return the same chain for 2^%d - 1, from "
                   "%s and %s limb products" % (fmt, P, rX["limb_products"],
                                                r256["limb_products"]))
            else:
                fail("%s and fp256 disagree at P = %d" % (fmt, P))
        CHECKS += 1
        if row_p and row_64 and row_p["chain"] == row_64["chain"]:
            ok("fp64 and fp256 return the same chain over all %d exponents"
               % len(exps))
        else:
            fail("fp64 and fp256 disagree over the exponent set")

        # 5. the hash chain, recomputed with hashlib
        print("\n[4] the hash chain")
        CHECKS += 1
        want_chain = chain_of([oracle_record(e) for e in exps])
        if row_p and row_p["chain"] == want_chain:
            ok("the tool's chain over %d records matches hashlib's - so its "
               "derivation of SHA-256's constants from the cube roots of "
               "the primes is right" % len(exps))
        else:
            fail("chain mismatch: tool %s, hashlib %s"
                 % (row_p["chain"] if row_p else "-", want_chain))
        CHECKS += 1
        if row_p and row_p["flags"] == "0x00" and row_p["status"] == "0x00":
            ok("not one operation of %s squarings raised a flag, and the "
               "754-2019 status word agrees with the union"
               % row_p["squarings"])
        else:
            fail("flags were raised during a run that must be exact: %r"
                 % (row_p,))

        # 6. batch-size independence
        print("\n[5] the same work, three batch sizes, one checkpoint")
        small = exps[:3]
        argset = ["--exponents", ",".join(str(e) for e in small)]
        paths = []
        for batch, engine in ((3, "program"), (4096, "program"),
                              (11, "loop")):
            path = Path(tmp) / ("bs-%d-%s.ckpt" % (batch, engine))
            try:
                tool.run(*argset, "--batch", batch, "--engine", engine,
                         "--checkpoint", path, "--quiet")
            except RuntimeError as exc:
                fail("batch %d, engine %s refused to run - %s"
                     % (batch, engine, str(exc).strip().splitlines()[-1]))
                continue
            paths.append(path)
        CHECKS += 1
        blobs = [p.read_bytes() for p in paths]
        if len(blobs) == 3 and blobs[0] == blobs[1] == blobs[2]:
            ok("batch 3, batch 4096 and the host loop at batch 11 end on "
               "byte-identical checkpoints (%s)"
               % read_field(paths[0], "chain")[:16])
        else:
            fail("the checkpoints differ across batch sizes or engines")

        # 7. interrupt and resume
        #
        # --stop-after-squarings is deliberately not a multiple of any
        # exponent's length, so a stop lands in the MIDDLE of a
        # Lucas-Lehmer sequence with a partial residue on disk. A resume
        # that only ever restarted between exponents would be testing
        # the cursor and nothing else.
        print("\n[6] interrupting and resuming")
        piece = Path(tmp) / "piece.ckpt"
        step = 137 if not args.quick else 211
        common = argset + ["--batch", 9, "--stop-after-squarings", step,
                           "--checkpoint", piece, "--quiet"]
        started = True
        try:
            tool.run(*common)
        except RuntimeError as exc:
            CHECKS += 1
            fail("the interrupt leg could not start - %s"
                 % str(exc).strip().splitlines()[-1])
            started = False
        rounds = 0
        mid = 0
        while started:
            rounds += 1
            if rounds > 10000:
                fail("the resumed run did not finish")
                break
            if read_field(piece, "current") != "- -":
                mid += 1
            try:
                tool.run("--resume",
                         *(argset + ["--batch", 23,
                                     "--stop-after-squarings", step,
                                     "--checkpoint", piece, "--quiet"]))
            except RuntimeError as exc:
                fail("a resume refused to run - %s"
                     % str(exc).strip().splitlines()[-1])
                started = False
                break
            if read_field(piece, "done") == str(len(small)):
                break
        CHECKS += 2
        if started and mid:
            ok("%d of the %d interruptions caught a partial residue "
               "mid-exponent" % (mid, rounds))
        else:
            fail("no interruption landed inside an exponent, so the "
                 "in-flight residue was never exercised")
        if started and blobs and piece.read_bytes() == blobs[0]:
            ok("a run stopped and resumed %d times, at a different batch "
               "size, ends on the same checkpoint - byte for byte - as one "
               "that was never stopped" % rounds)
        else:
            fail("the resumed run's checkpoint differs from the "
                 "uninterrupted one")

        # 8. the exactness bound
        print("\n[7] the exactness bound, probed rather than asserted")
        st = tool.run("--selftest")
        CHECKS += 1
        if "MERSENNE SELFTEST OK" in st.stdout:
            n_ok = st.stdout.count("  ok   ")
            ok("the selftest's %d probes pass: an accumulation reaching "
               "2^p - 1 raises nothing, one crossing 2^p raises inexact, "
               "and every derived geometry's worst-case coefficient is "
               "exact" % n_ok)
        else:
            fail("the selftest failed:\n%s" % st.stdout)

        # A limb width the bound forbids must be refused BEFORE any
        # arithmetic; forcing it past the refusal must be stopped by the
        # library's flag. Two different mechanisms, and the tool must
        # not confuse them.
        CHECKS += 1
        wide = tool.run("--exponents", 1279, "--limb", 118, expect_ok=False)
        if wide.returncode == 2 and "limb width" in wide.stderr:
            ok("a limb width the exactness bound forbids is refused before "
               "any arithmetic (--limb 118 at fp256: 11 limbs of 118 bits "
               "would need 2^239 of significand)")
        else:
            fail("--limb 118 was not refused: rc=%d %r"
                 % (wide.returncode, wide.stderr[:200]))
        CHECKS += 1
        forced = tool.run("--exponents", 1279, "--limb", 118,
                          "--unsafe-limb", expect_ok=False)
        if forced.returncode == 3 and "inexact" in forced.stderr:
            ok("forcing it past the refusal is stopped by the LIBRARY: "
               "the dot raises inexact and the residue is refused, not "
               "reported")
        else:
            fail("--unsafe-limb did not end in a refused certificate: "
                 "rc=%d %r" % (forced.returncode, forced.stderr[:200]))
        CHECKS += 1
        huge = tool.run("--exponents", 1279, "--limb", 200, expect_ok=False)
        if huge.returncode != 0:
            ok("a limb wider than half the significand is refused too "
               "(--limb 200 at p = 237)")
        else:
            fail("--limb 200 was accepted at fp256")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d comparisons, %d failures" % (CHECKS, len(FAILURES)))
    if FAILURES:
        print("MERSENNE CHECK FAILED")
        return 1
    print("MERSENNE CHECK OK - the tool, the library and the big-integer "
          "oracle agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
