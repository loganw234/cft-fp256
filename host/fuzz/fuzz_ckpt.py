# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The five workload tools' --resume readers, over malformed checkpoints.

    python3 host/fuzz/fuzz_ckpt.py --bin DIR [--seconds 300] [--tool collatz]

A checkpoint is a file the tool wrote, and on a shared machine that is
still a file some other process can rewrite, truncate or corrupt. Each
tool's ckpt_read is static inside its own main file and a resume is a
whole-process act, so this drives the tools as PROCESSES rather than in
process - which also means there is no coverage feedback here, unlike
the three in-process harnesses. The mutation is structure-aware
instead: the format is one key per line with counted blocks after
`batchrecords` and `inflight`, and the mutator works on keys, tokens
and counts rather than on bytes.

What counts as a finding, in the words of the contract these tools
keep: a malformed checkpoint must produce a NAMED REFUSAL - the tool's
own die() message and exit 2 - never a crash, never a hang, and never
a silent resume from a state the file did not describe.

    exit 2 + a message   refusal, as intended
    exit 0               accepted (reported, not a finding by itself)
    a signal, or a sanitiser report on stderr    CRASH
    no exit inside the timeout                   HANG
"""

import argparse
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

# One entry per tool: the arguments that WRITE a seed checkpoint, and
# the arguments a resume needs. Both are the shapes host/tests uses,
# and both stop early so a seed carries work in flight - the state a
# resume that only ever restarted on a batch boundary never reaches.
TOOLS = {
    "collatz": {
        "exe": "cft-collatz",
        "seed": ["--from", "1", "--to", "400", "--batch", "64",
                 "--steps-per-call", "7", "--stop-after-passes", "3",
                 "--quiet"],
        "resume": ["--batch", "64", "--steps-per-call", "7",
                   "--stop-after-passes", "3", "--quiet"],
    },
    "enclose": {
        "exe": "cft-enclose",
        "seed": ["--format", "fp64", "--points", "64", "--batch", "23",
                 "--stop-after-passes", "4", "--quiet"],
        "resume": ["--format", "fp64", "--points", "64", "--batch", "23",
                   "--stop-after-passes", "4", "--quiet"],
    },
    "mersenne": {
        "exe": "cft-mersenne",
        "seed": ["--exponents", "521", "--batch", "9",
                 "--stop-after-squarings", "137", "--quiet"],
        "resume": ["--exponents", "521", "--batch", "9",
                   "--stop-after-squarings", "137", "--quiet"],
    },
    "orbits": {
        "exe": "cft-orbits",
        "seed": ["--problem", "kepler", "--format", "fp256", "--members", "8",
                 "--periods", "2", "--steps-per-period", "96", "--batch", "5",
                 "--stop-after-steps", "37", "--quiet"],
        "resume": ["--problem", "kepler", "--format", "fp256", "--members",
                   "8", "--periods", "2", "--steps-per-period", "96",
                   "--batch", "5", "--stop-after-steps", "37", "--quiet"],
    },
    "zoom": {
        "exe": "cft-zoom",
        "seed": ["--ref-iters", "2000", "--no-pixels", "--steps-per-call",
                 "37", "--stop-after-passes", "5", "--quiet"],
        "resume": ["--ref-iters", "2000", "--no-pixels", "--steps-per-call",
                   "37", "--stop-after-passes", "5", "--quiet"],
    },
}

INTERESTING = ["0", "1", "-1", "2", "7", "8", "63", "64", "65", "255",
               "256", "4294967295", "4294967296", "2147483647",
               "-2147483648", "9223372036854775807", "18446744073709551615",
               "99999999999999999999999999", "-", "", "nan", "inf",
               "0x10", "1e309", "A" * 600, "A" * 8, "0" * 600]


def mutate(text, rng):
    """One mutation of a checkpoint's text, on its own terms."""
    lines = text.split("\n")
    what = rng.randrange(9)

    if what == 0 and len(lines) > 1:                 # drop a line
        del lines[rng.randrange(len(lines))]
    elif what == 1 and len(lines) > 1:               # duplicate a line
        i = rng.randrange(len(lines))
        lines.insert(i, lines[i])
    elif what == 2 and len(lines) > 2:               # swap two lines
        i, j = rng.randrange(len(lines)), rng.randrange(len(lines))
        lines[i], lines[j] = lines[j], lines[i]
    elif what == 3 and len(lines) > 1:               # truncate the file
        lines = lines[:rng.randrange(1, len(lines))]
    elif what == 4:                                  # a token, replaced
        i = rng.randrange(len(lines))
        tok = lines[i].split(" ")
        if len(tok) > 1:
            tok[rng.randrange(1, len(tok))] = rng.choice(INTERESTING)
            lines[i] = " ".join(tok)
    elif what == 5:                                  # a token, dropped
        i = rng.randrange(len(lines))
        tok = lines[i].split(" ")
        if len(tok) > 1:
            del tok[rng.randrange(1, len(tok))]
            lines[i] = " ".join(tok)
    elif what == 6:                                  # a token, added
        i = rng.randrange(len(lines))
        if lines[i]:
            lines[i] = lines[i] + " " + rng.choice(INTERESTING)
    elif what == 7:                                  # a count, perturbed
        for i, ln in enumerate(lines):
            key = ln.split(" ")[0] if ln else ""
            if key in ("batchrecords", "inflight", "nrec", "live", "n",
                       "count", "items", "pending"):
                tok = ln.split(" ")
                if len(tok) > 1:
                    tok[1] = rng.choice(INTERESTING)
                    lines[i] = " ".join(tok)
                    break
    else:                                            # a byte, flipped
        if text:
            i = rng.randrange(len(text))
            b = bytearray(text.encode("latin-1", "replace"))
            b[i] ^= 1 << rng.randrange(8)
            return b.decode("latin-1")
    return "\n".join(lines)


def classify(proc, timed_out):
    if timed_out:
        return "HANG"
    err = proc.stderr or ""
    if "AddressSanitizer" in err or "runtime error:" in err or \
       "LeakSanitizer" in err:
        return "SANITIZER"
    if proc.returncode < 0:
        return "SIGNAL%d" % (-proc.returncode)
    if proc.returncode == 0:
        return "ACCEPT"
    if proc.returncode == 2 and err.strip():
        return "REFUSE"
    return "EXIT%d" % proc.returncode


def one_tool(name, bindir, outdir, seconds, seed, timeout):
    spec = TOOLS[name]
    exe = Path(bindir) / spec["exe"]
    if not exe.exists():
        exe = Path(bindir) / (spec["exe"] + ".exe")
    if not exe.exists():
        print(f"{name}: SKIP (no {spec['exe']} in {bindir})")
        return {}

    work = Path(outdir) / name
    work.mkdir(parents=True, exist_ok=True)
    corpus_dir = HERE / "corpus" / "ckpt"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    seed_path = corpus_dir / f"{name}.ckpt"

    if not seed_path.exists():
        tmp = work / "seed.ckpt"
        r = subprocess.run([str(exe)] + spec["seed"] +
                           ["--checkpoint", str(tmp)],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not tmp.exists():
            print(f"{name}: SKIP (the seed run failed: {r.stderr[:200]})")
            return {}
        shutil.copyfile(tmp, seed_path)

    corpus = [p.read_text(errors="replace") for p in sorted(corpus_dir.glob(f"{name}*"))]
    rng = random.Random(seed ^ (hash(name) & 0xFFFF))
    counts = {}
    t0 = time.time()
    n = 0
    cur = work / "cur.ckpt"
    findings = 0

    while time.time() - t0 < seconds:
        text = mutate(rng.choice(corpus), rng)
        for _ in range(rng.randrange(3)):
            text = mutate(text, rng)
        cur.write_text(text, errors="replace")
        timed_out = False
        try:
            proc = subprocess.run(
                [str(exe), "--resume", "--checkpoint", str(cur)] +
                spec["resume"], capture_output=True, text=True,
                timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True

            class P:
                returncode = 0
                stderr = ""
            proc = P()
        verdict = classify(proc, timed_out)
        counts[verdict] = counts.get(verdict, 0) + 1
        n += 1
        if verdict in ("HANG", "SANITIZER") or verdict.startswith("SIGNAL") \
                or verdict.startswith("EXIT"):
            findings += 1
            keep = HERE / "crashes" / "ckpt"
            keep.mkdir(parents=True, exist_ok=True)
            dst = keep / f"{name}-{verdict}-{findings:04d}.ckpt"
            if not dst.exists():
                dst.write_text(text, errors="replace")
                (keep / f"{name}-{verdict}-{findings:04d}.log").write_text(
                    (proc.stderr or "")[:8000], errors="replace")
                print(f"  {name}: {verdict} -> {dst.name}")
    el = time.time() - t0
    summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"{name}: {n} resumes in {el:.0f}s ({n / el:.1f}/s)  {summary}")
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bin", default=str(HERE / "bin"),
                    help="directory holding the sanitised tools")
    ap.add_argument("--out", default=str(HERE / "work"))
    ap.add_argument("--seconds", type=float, default=300.0)
    # Ninety seconds, not twenty. cft-zoom derives its fp256 centre
    # BEFORE it reads the checkpoint, so even a resume it refuses
    # outright takes 11 to 25 seconds under the sanitisers - and a
    # timeout inside that window reports the tool's setup as a hang.
    # It did, on 2026-09-07, and the file it saved turned out to be
    # refused correctly (`bad checkpoint orbit line`, exit 2) 24
    # seconds in. A fuzzer whose hang budget is shorter than its
    # target's start-up is a fuzzer that reports start-up.
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--tool", nargs="*", default=list(TOOLS))
    args = ap.parse_args()

    os.environ.setdefault("ASAN_OPTIONS",
                          "detect_leaks=0:allocator_may_return_null=1")
    os.environ.setdefault("UBSAN_OPTIONS", "print_stacktrace=1")

    total = {}
    for name in args.tool:
        if name not in TOOLS:
            print(f"no such tool: {name}")
            return 2
        for k, v in one_tool(name, args.bin, args.out,
                             args.seconds / len(args.tool), args.seed,
                             args.timeout).items():
            total[k] = total.get(k, 0) + v
    print("\ntotal: " + " ".join(f"{k}={v}" for k, v in sorted(total.items())))
    bad = sum(v for k, v in total.items()
              if k in ("HANG", "SANITIZER") or k.startswith("SIGNAL")
              or k.startswith("EXIT"))
    if bad:
        print(f"{bad} checkpoint(s) did something other than refuse cleanly "
              f"- see host/fuzz/crashes/ckpt")
    return 0


if __name__ == "__main__":
    sys.exit(main())
