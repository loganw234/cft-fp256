# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Score host/tools/collatz.c against a Python big-integer oracle.

    python3 host/tests/collatz_check.py [--exe PATH] [--quick]

The division of authority is the repository's usual one, applied to a
new question. The LIBRARY is the authority on arithmetic: what
`fma(n, 3, 1)` returns and which flags it raises is settled by
docs/DETERMINISM.md and by python/cft_golden, not by anything here.
PYTHON is the authority on Collatz, because its integers are exact and
unbounded, so an oracle written in them cannot be wrong about a
stopping time.

What that leaves for this file is the join: does the tool's
floating-point trajectory agree, step for step, with the integer one -
and does it stop in exactly the same place when the format runs out?
The second half is the interesting one. The oracle models the tool's
stopping rule exactly rather than approximately:

  * a value at or above 2^p has no units bit and is therefore even;
  * an odd step is taken only when 3n+1 fits p significant bits, and
    the element stops - unverified - at the first one that does not.

So the oracle predicts not just the answer but the abandonment, and a
tool that gave up one step early or one step late would fail here.

Five properties are checked, and three of them are about the machine
rather than about Collatz:

1. Results.       Every record against the oracle, at fp256 and fp64,
                  over small starts and over starts chosen to sit on
                  the exactness boundary.
2. Engines.       The sequencer-program route and the host cft_run
                  loop must produce byte-identical records.
3. Formats.       Where a trajectory stays inside binary64's exact
                  range, fp64 and fp256 must produce identical records
                  - the same contract at two rungs of the ladder.
4. Batch size.    Three different batch sizes over the same range must
                  end on byte-identical checkpoints.
5. Interruption.  A run stopped and resumed repeatedly must end on the
                  same checkpoint as one that was never stopped.

And the hash chain is recomputed here with hashlib, which is what
proves that the tool's from-first-principles derivation of SHA-256's
round constants is right.
"""

import argparse
import hashlib
import os
import re
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
def representable(v, p):
    """Is the non-negative integer v exactly a binary-p float?"""
    if v == 0:
        return True
    shift = v.bit_length() - p
    if shift <= 0:
        return True
    return (v >> shift) << shift == v


def trajectory(n0, p):
    """(steps, peak, final, escaped), modelling collatz.c exactly.

    Returns the number of steps every one of which was performed by an
    exact operation, the largest value provably held, the value the
    element stopped on, and whether it stopped because exactness ran
    out rather than because it reached 1.
    """
    n = n0
    steps = 0
    peak = n0
    while True:
        if n == 1:
            return steps, peak, n, False
        # A value at or above 2^p has ulp >= 2 and so is even; below
        # it, the parity is the units bit.
        odd = (n & 1) == 1 and n < (1 << p)
        if odd:
            y = 3 * n + 1
            if not representable(y, p):
                return steps, peak, n, True
            n = y
        else:
            assert n % 2 == 0, "an odd value above 2^p is not representable"
            n //= 2
        steps += 1
        if n > peak:
            peak = n


def oracle_record(n0, p):
    steps, peak, final, escaped = trajectory(n0, p)
    return "%d %d %d %d %s" % (n0, steps, peak, final,
                               "esc" if escaped else "ok")


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
            raise RuntimeError("cft-collatz %s failed (%d)\n%s\n%s"
                               % (" ".join(str(a) for a in args),
                                  proc.returncode, proc.stdout, proc.stderr))
        return proc

    def records(self, tmp, *args, name="rec.txt"):
        path = Path(tmp) / name
        self.run(*args, "--records", path, "--quiet")
        return [ln.rstrip("\n") for ln in
                path.read_text().splitlines() if ln.strip()]

    def csv(self, *args):
        out = self.run(*args, "--csv").stdout.strip().splitlines()
        head = out[0].split(",")
        row = out[-1].split(",")
        return dict(zip(head, row))


def read_ckpt_field(path, key):
    for line in Path(path).read_text().splitlines():
        if line.startswith(key + " "):
            return line[len(key) + 1:]
    return None


# ---------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------
def check_sweep(tool, tmp, fmt, p, lo, hi, engine, batch, label):
    global CHECKS
    got = tool.records(tmp, "--format", fmt, "--engine", engine,
                       "--from", lo, "--to", hi, "--batch", batch,
                       name="sweep-%s-%s-%s.txt" % (fmt, engine, batch))
    want = [oracle_record(n, p) for n in range(lo, hi)]
    CHECKS += len(want)
    if got != want:
        for a, b in zip(got, want):
            if a != b:
                fail("%s: got '%s', oracle says '%s'" % (label, a, b))
                return got
        fail("%s: %d records, oracle has %d" % (label, len(got), len(want)))
        return got
    ok("%s: %d starting values match the big-integer oracle" %
       (label, len(want)))
    return got


def check_values(tool, tmp, fmt, p, values, engine, label):
    global CHECKS
    got = tool.records(tmp, "--mode", "deep", "--format", fmt,
                       "--engine", engine, "--batch", max(8, len(values)),
                       "--values", ",".join(str(v) for v in values),
                       name="deep-%s-%s.txt" % (fmt, engine))
    want = [oracle_record(v, p) for v in values]
    CHECKS += len(want)
    bad = [(a, b) for a, b in zip(got, want) if a != b]
    if bad or len(got) != len(want):
        if bad:
            fail("%s: got '%s', oracle says '%s'" % (label, bad[0][0],
                                                     bad[0][1]))
        else:
            fail("%s: %d records, oracle has %d" % (label, len(got),
                                                    len(want)))
        return got
    esc = sum(1 for w in want if w.endswith("esc"))
    ok("%s: %d values match, %d of them left exact arithmetic where the "
       "oracle says they should" % (label, len(want), esc))
    return got


def boundary_values(p):
    """Starting values that sit on the exactness boundary.

    Deliberately a mix: odd values immediately below 2^p (whose very
    first 3n+1 may or may not be representable, depending on 3n+1 mod
    4), values just under the largest n for which 3n+1 is certainly
    representable, and values far enough below to be ordinary. A set
    that only contained the first kind would test one branch.
    """
    top = 1 << p
    vals = []
    for k in range(1, 12):
        vals.append(top - k)
    third = (top - 2) // 3
    for k in range(0, 6):
        vals.append(third - k)
    vals.append(top)
    vals.append(top // 2 + 1)
    vals.append((1 << (p // 2)) + 12345)
    vals.append(27)
    vals.append(703)
    vals.append(1)
    return [v for v in vals if v >= 1]


def main():
    global CHECKS
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=None)
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    exe = args.exe
    if exe is None:
        for cand in ("cft-collatz.exe", "cft-collatz"):
            path = ROOT / "host" / cand
            if path.exists():
                exe = path
                break
    if exe is None or not Path(exe).exists():
        raise SystemExit("cft-collatz not found - run `make -C host collatz`")
    tool = Tool(exe)

    tmp = tempfile.mkdtemp(prefix="collatz-check-")
    span = 2000 if args.quick else 5000
    ckpt_span = 4000 if args.quick else 12000
    try:
        print("cft-collatz cross-check, tool: %s" % exe)

        # 1. results, small starts, both engines, both formats
        print("\n[1] results against the big-integer oracle")
        prog = check_sweep(tool, tmp, "fp256", 237, 1, 1 + span,
                           "program", 128,
                           "fp256 sweep 1..%d, sequencer program" % span)
        loop = check_sweep(tool, tmp, "fp256", 237, 1, 1 + span,
                           "loop", 97,
                           "fp256 sweep 1..%d, host cft_run loop" % span)
        f64 = check_sweep(tool, tmp, "fp64", 53, 1, 1 + span,
                          "program", 251,
                          "fp64 sweep 1..%d, sequencer program" % span)

        print("\n[2] the two engines and the two formats agree")
        CHECKS += 2
        if prog == loop:
            ok("the sequencer program and the host loop produce identical "
               "records over %d starting values" % span)
        else:
            fail("the two engines disagree")
        if prog == f64:
            ok("fp64 and fp256 produce identical records where binary64 "
               "holds the whole trajectory exactly")
        else:
            diff = [(a, b) for a, b in zip(prog, f64) if a != b]
            fail("fp256 and fp64 disagree, first at %r vs %r" % diff[0])

        # 3. the exactness boundary
        print("\n[3] the exactness boundary, where INEXACT is the answer")
        b256 = boundary_values(237)
        got_p = check_values(tool, tmp, "fp256", 237, b256, "program",
                             "fp256 boundary set, sequencer program")
        got_l = check_values(tool, tmp, "fp256", 237, b256, "loop",
                             "fp256 boundary set, host cft_run loop")
        CHECKS += 1
        if got_p == got_l:
            ok("both engines agree on the boundary set")
        else:
            fail("the engines disagree on the boundary set")
        b64 = boundary_values(53)
        check_values(tool, tmp, "fp64", 53, b64, "program",
                     "fp64 boundary set, sequencer program")
        check_values(tool, tmp, "fp32", 24, boundary_values(24), "program",
                     "fp32 boundary set, sequencer program")
        # binary32 runs out of exactness inside an ORDINARY sweep, so
        # the sweep path's escape handling is covered too and not only
        # deep mode's. The window is chosen around the first starting
        # value that escapes at p = 24 (26623), which is later than it
        # looks: a trajectory routinely climbs past 2^24 and stays
        # exact, because 3n+1 is even for odd n and an even value one
        # bit above the format still fits.
        f32 = check_sweep(tool, tmp, "fp32", 24, 26000, 29000, "program",
                          512, "fp32 sweep 26000..28999, where binary32 "
                               "runs out")
        CHECKS += 1
        n_esc = sum(1 for r in f32 if r.endswith("esc"))
        if n_esc:
            ok("%d of those 3000 starting values left exact arithmetic at "
               "binary32, exactly where the oracle says they do" % n_esc)
        else:
            fail("no fp32 escapes: the sweep did not reach the boundary")

        # 4. the hash chain, recomputed with hashlib
        print("\n[4] the hash chain")
        row = tool.csv("--format", "fp256", "--from", 1, "--to", 1 + span,
                       "--batch", 333)
        CHECKS += 1
        if row["chain"] == chain_of(prog):
            ok("the tool's chain over %d records matches hashlib's - so its "
               "derivation of SHA-256's constants from the cube roots of "
               "the primes is right" % len(prog))
        else:
            fail("chain mismatch: tool %s, hashlib %s"
                 % (row["chain"], chain_of(prog)))
        CHECKS += 1
        if row["verified"] == str(span) and row["escaped"] == "0":
            ok("every starting value below %d is verified, none escaped"
               % (1 + span))
        else:
            fail("unexpected verified/escaped counts: %r" % row)

        # 5. batch-size independence
        print("\n[5] the same range, three batch sizes, one checkpoint")
        paths = []
        for batch in (64, 1000, 4096):
            path = Path(tmp) / ("bs-%d.ckpt" % batch)
            tool.run("--from", 1, "--to", 1 + ckpt_span, "--batch", batch,
                     "--checkpoint", path, "--quiet")
            paths.append(path)
        CHECKS += 1
        blobs = [p.read_bytes() for p in paths]
        if blobs[0] == blobs[1] == blobs[2]:
            ok("batch 64, 1000 and 4096 over 1..%d end on byte-identical "
               "checkpoints (%s)" % (ckpt_span,
                                     read_ckpt_field(paths[0], "chain")[:16]))
        else:
            fail("the checkpoints differ across batch sizes")

        # the engines must land on the same checkpoint too
        eng_path = Path(tmp) / "engine.ckpt"
        tool.run("--from", 1, "--to", 1 + ckpt_span, "--batch", 512,
                 "--engine", "loop", "--checkpoint", eng_path, "--quiet")
        CHECKS += 1
        if eng_path.read_bytes() == blobs[0]:
            ok("the host-loop engine lands on the same checkpoint as the "
               "sequencer program")
        else:
            fail("the two engines end on different checkpoints")

        # 6. interrupt and resume
        #
        # --steps-per-call is deliberately tiny here so that a stop
        # lands in the MIDDLE of a batch, with elements part way
        # through their trajectories. A resume that only ever restarted
        # on a batch boundary would be testing the cursor and nothing
        # else.
        print("\n[6] interrupting and resuming")
        whole = Path(tmp) / "whole.ckpt"
        tool.run("--from", 1, "--to", 1 + ckpt_span, "--batch", 512,
                 "--checkpoint", whole, "--quiet")
        piece = Path(tmp) / "piece.ckpt"
        common = ["--batch", 300, "--steps-per-call", 7,
                  "--stop-after-passes", 9, "--checkpoint", piece,
                  "--quiet"]
        tool.run("--from", 1, "--to", 1 + ckpt_span, *common)
        rounds = 0
        saw_inflight = 0
        while True:
            rounds += 1
            if rounds > 20000:
                fail("the resumed run did not finish")
                break
            if int(read_ckpt_field(piece, "inflight")) > 0:
                saw_inflight += 1
            tool.run("--resume", *common)
            cursor = read_ckpt_field(piece, "cursor")
            inflight = read_ckpt_field(piece, "inflight")
            pending = read_ckpt_field(piece, "batchrecords")
            if (cursor == str(1 + ckpt_span) and inflight == "0"
                    and pending == "0"):
                break
        CHECKS += 2
        if saw_inflight:
            ok("%d of the %d interruptions caught elements part way through "
               "a trajectory" % (saw_inflight, rounds))
        else:
            fail("no interruption landed mid-batch, so the in-flight state "
                 "was never exercised")
        if piece.read_bytes() == whole.read_bytes():
            ok("a run stopped and resumed %d times, at a different batch "
               "size and trip count, ends on the same checkpoint - byte for "
               "byte - as one that was never stopped" % rounds)
        else:
            fail("the resumed run's checkpoint differs from the "
                 "uninterrupted one")

        # 7. things that must be refused
        print("\n[7] refusals")
        CHECKS += 1
        bad = tool.run("--mode", "deep", "--values", str((1 << 237) + 1),
                       expect_ok=False)
        if bad.returncode != 0:
            ok("a starting value the format cannot hold exactly is refused, "
               "not rounded")
        else:
            fail("2^237 + 1 was accepted as a starting value")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d comparisons, %d failures" % (CHECKS, len(FAILURES)))
    if FAILURES:
        print("COLLATZ CHECK FAILED")
        return 1
    print("COLLATZ CHECK OK - the tool, the library and the big-integer "
          "oracle agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
