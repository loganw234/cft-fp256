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

A CERTIFIED cft-orbits run (docs/ORBITS.md, "Certified runs",
2026-09-30) writes checkpoint version 3: version 2's lines, the
certificate so far, and a `sum` line over the file. Two entries seed
from one - `orbits-cert` open and `orbits-cert-keyed` keyed - made fresh
each session in the work directory with the states directory beside
it, since both name this build and the states' hashes (never cached in
corpus/ckpt). Their refusals are named two ways, both the contract's:
a checkpoint that does not describe the run, the reader's sentence and
exit 2; and the certified path's `cft-orbits: refused <name>: <why>`,
with that name's code (salt-missing, identity, state-hash, ...). The
classifier holds each name to the code the page gives it (NAME_CODES):
a named refusal with another exit is WRONG-CODE, and a name the page
does not give is UNKNOWN-NAME, both findings (since 2026-09-30's
send-back; before it, any exit but 1 and 70 passed). A run
the flag certificate stops (exit 3, "raised 0x..") is refused by name
too: the arithmetic left the domain. The mutator knows the version-3
block, and makes the sum again over three mutations in four, so that
the strict reader behind the sum is what it reaches. And an accepted
certified resume runs to the end and writes its certificate, which
must be the uninterrupted run's, byte for byte: one that differs is
held to the golden audit (python/cft_golden/cert.py), and is a finding
- a SILENT WRONG RESUME - unless the audit refuses it by name.
"""

import argparse
import hashlib
import os
import random
import re
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

# A certified cft-orbits run: Kepler, fp64, 8 intervals of 16 steps,
# stopped at 37 - part way through interval 2, two intervals closed - so
# the seed's `cert` block carries segment lines and flags so far. The
# resume runs to the end and writes the certificate; `cert` names the
# mode, and one_tool adds --cert, --cert-states and the salt choice. The
# keyed one also writes the angular momentum's drift entry, so its seed
# says `cert entries angular-momentum-drift` and its resumes derive it.
_ORBITS_CERT = ["--problem", "kepler", "--format", "fp64", "--members", "4",
                "--periods", "2", "--steps-per-period", "64",
                "--sample-every", "16", "--rsqrt", "newton", "--engine",
                "segments", "--batch", "3", "--quiet"]
for _name, _mode, _acc in (
        ("orbits-cert", "open", []),
        ("orbits-cert-keyed", "keyed",
         ["--cert-accuracy", "angular-momentum-drift"])):
    TOOLS[_name] = {"exe": "cft-orbits",
                    "seed": _ORBITS_CERT + _acc + ["--stop-after-steps", "37"],
                    "resume": _ORBITS_CERT + _acc, "cert": _mode}

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


WORDS = ["0", "1", "15", "16", "17", "31", "32", "99", "016", "-1", "",
         "4294967295", "4294967296", "18446744073709551616"]


def mutate_cert(text, rng):
    """One mutation that knows a certified cft-orbits checkpoint's block
    (version 3; docs/ORBITS.md, "Certified runs"): its flag words and
    STATUS, its hashes, its mode, its segment lines, the `at` line it is
    held to, the certificate lines a resume holds to its own, and the
    state values it cannot hold to anything but the sum."""
    lines = text.split("\n")
    cert = [i for i, l in enumerate(lines) if l.startswith("cert ")]
    segs = [i for i in cert if lines[i].startswith("cert segment ")]
    what = rng.randrange(8)
    if what == 0:                        # a flag word or a STATUS
        cand = [i for i in cert if " flags " in lines[i]]
        if cand:
            i = rng.choice(cand)
            tok = lines[i].split(" ")
            key = "flags" if rng.randrange(2) else "status"
            tok[tok.index(key) + 1] = rng.choice(WORDS)
            lines[i] = " ".join(tok)
    elif what == 1:                      # a hash: another, or respelt
        hashes = [t for i in cert for t in lines[i].split(" ")
                  if len(t) == 64]
        cand = [i for i in cert
                if any(len(t) == 64 for t in lines[i].split(" "))]
        if cand:
            i = rng.choice(cand)
            tok = lines[i].split(" ")
            j = rng.choice([j for j, t in enumerate(tok) if len(t) == 64])
            tok[j] = rng.choice(hashes + [tok[j][1:], tok[j] + "0",
                                          tok[j].upper(), "0" * 64])
            lines[i] = " ".join(tok)
    elif what == 2:                      # the mode, the other way
        for i in cert:
            if lines[i].startswith("cert mode "):
                lines[i] = ("cert mode open" if lines[i].endswith("keyed")
                            else "cert mode keyed")
    elif what == 3 and segs:             # a segment line dropped, repeated,
        i = rng.choice(segs)             # or two exchanged
        how = rng.randrange(3)
        if how == 0:
            del lines[i]
        elif how == 1:
            lines.insert(i, lines[i])
        elif len(segs) > 1:
            j = rng.choice([s for s in segs if s != i])
            lines[i], lines[j] = lines[j], lines[i]
    elif what == 4:                      # the at line, a step or a sample
        for i, l in enumerate(lines):
            if l.startswith("at "):
                tok = l.split(" ")
                k = rng.choice([1, 2])
                if tok[k].isdigit():
                    tok[k] = str(max(0, int(tok[k]) +
                                     rng.choice([-16, -1, 1, 16])))
                lines[i] = " ".join(tok)
    elif what == 5 and cert:             # a certificate line's value
        i = rng.choice(cert)
        tok = lines[i].split(" ")
        if len(tok) > 2:
            tok[rng.randrange(2, len(tok))] = rng.choice(WORDS + INTERESTING)
            lines[i] = " ".join(tok)
    elif what == 6:                      # a state value: another one
        st = [i for i, l in enumerate(lines) if l.startswith("state ")]
        if st:
            i, j = rng.choice(st), rng.choice(st)
            a, b = lines[i].split(" "), lines[j].split(" ")
            if len(a) > 2 and len(b) > 2:
                a[rng.randrange(2, len(a))] = b[rng.randrange(2, len(b))]
                lines[i] = " ".join(a)
    elif cert:                           # a block line dropped or moved
        i = rng.choice(cert)
        line = lines.pop(i)
        if rng.randrange(2):
            lines.insert(rng.randrange(len(lines)), line)
    return "\n".join(lines)


def ckpt_bytes(text):
    """The bytes a mutated checkpoint is, one for each character. A
    checkpoint is ASCII, and a bit flipped makes a byte of 0x80 or more
    (mutate), which latin-1 alone keeps as that one byte. The file
    resumed, the sum made again over it (resum) and a finding kept are all
    these bytes, so a sum made again is the sum of the file the tool reads,
    whatever the platform's default encoding. Until 2026-09-30's send-back
    resum hashed these bytes and the file was written in the default one:
    UTF-8 in cft-sim, where a character of 0x80 or more is two bytes, so a
    resume whose file held one stopped at a sum that was not its file's -
    about one in 200, verifier-W3 reckoned from the mutator's odds."""
    return text.encode("latin-1", "replace")


def resum(text):
    """A version-3 checkpoint's `sum` made again over what it follows, so
    that a mutation reaches the strict reader behind it."""
    i = text.rfind("\nsum ")
    if i < 0:
        return text
    body = text[:i + 1]
    return (body + "sum " + hashlib.sha256(ckpt_bytes(body)).hexdigest() +
            "\n")


# A certified cft-orbits run's refusals name themselves, each with its
# name's own exit code: the page's table (docs/ORBITS.md, "Certified
# runs", "Refused by name"), held here as orbits_check.py's [8] holds it.
# build-width and the three accuracy-* checks of an entry's definition are
# in it although no run reaches them. And cft-orbits' flag certificate
# stops a run whose arithmetic left the domain, exit 3, naming what raised
# what (docs/ORBITS.md, "Flags"). Both are named refusals.
NAME_CODES = {"cft-orbits": {
    "engine": 64, "rsqrt-exact": 64, "step-halving": 64, "wider": 64,
    "energy-drift": 64, "usage": 64, "salt-length": 4, "program-image": 4,
    "device": 69, "malformed": 2, "width": 3, "accuracy-finite": 7,
    "accuracy-run": 7, "accuracy-scope": 7, "accuracy-slot": 7,
    "build-width": 78, "memory": 71, "output": 73, "salt-missing": 4,
    "salt-unexpected": 4, "salt-commitment": 4, "identity": 78,
    "image-digest": 4, "program-digest": 4, "state-missing": 4,
    "state-shape": 4, "state-hash": 4}}
NAMED = re.compile(r"^(cft-[a-z]+): refused ([a-z][a-z0-9-]*): ", re.M)
FLAGSTOP = re.compile(r"raised 0x[0-9a-f]+ - this workload can only ever "
                      r"raise inexact")
# What is a finding: a crash, a hang, a sanitiser report, an exit that is
# not the contract's named refusal, a named refusal off its page, and a
# certified resume accepted wrongly (accepted_certificate).
FINDINGS = ("HANG", "SANITIZER", "SILENT-WRONG", "ACCEPT-NO-CERTIFICATE",
            "WRONG-CODE", "UNKNOWN-NAME")


def is_finding(verdict):
    return verdict in FINDINGS or verdict.startswith("SIGNAL") or \
        verdict.startswith("EXIT")


def refusal_name(proc):
    """What refused: the name a certified refusal gives, `flags` for the
    flag certificate, `sentence` for a die() message and exit 2."""
    m = NAMED.search(proc.stderr or "")
    if m:
        return m.group(2)
    if proc.returncode == 3:
        return "flags"
    return "sentence"


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
    m = NAMED.search(err)
    if m:
        # a named refusal, held to its name's code: first, so that a name
        # whose code is not 2 cannot pass as a sentence at exit 2
        want = NAME_CODES.get(m.group(1), {}).get(m.group(2))
        if want is None:
            return "UNKNOWN-NAME"
        return "REFUSE" if proc.returncode == want else "WRONG-CODE"
    if proc.returncode == 2 and err.strip():
        return "REFUSE"
    if proc.returncode == 3 and FLAGSTOP.search(err):
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
    mode = spec.get("cert")
    cert_args = []
    if mode:
        # A certified run's seed names this build and its states' hashes,
        # so it is made fresh in the work directory, never cached; and so
        # is the uninterrupted run's certificate every accepted resume's
        # must equal.
        salt = work / "fuzz.salt"
        salt.write_bytes(bytes(range(7, 39)))
        mode_args = (["--cert-salt", str(salt)] if mode == "keyed"
                     else ["--cert-open"])
        for p in ("seed.cert", "seed.ckpt", "ref.cert"):
            if (work / p).exists():
                (work / p).unlink()
        for d in ("seed.states", "ref.states"):
            shutil.rmtree(work / d, ignore_errors=True)
        r = subprocess.run([str(exe)] + spec["seed"] +
                           ["--checkpoint", str(work / "seed.ckpt"),
                            "--cert", str(work / "seed.cert"),
                            "--cert-states", str(work / "seed.states")] +
                           mode_args, capture_output=True, text=True,
                           timeout=600)
        ref = subprocess.run([str(exe)] + spec["resume"] +
                             ["--cert", str(work / "ref.cert"),
                              "--cert-states", str(work / "ref.states")] +
                             mode_args, capture_output=True, text=True,
                             timeout=600)
        if r.returncode or ref.returncode or \
                not (work / "seed.ckpt").exists():
            print(f"{name}: SKIP (the certified seed run failed: "
                  f"{(r.stderr + ref.stderr)[-200:]})")
            return {}
        reference = (work / "ref.cert").read_bytes()
        corpus = [(work / "seed.ckpt").read_bytes().decode("latin-1")]
        cert_args = ["--cert", str(work / "cur.cert"), "--cert-states",
                     str(work / "cur.states")] + mode_args
    else:
        if not seed_path.exists():
            tmp = work / "seed.ckpt"
            r = subprocess.run([str(exe)] + spec["seed"] +
                               ["--checkpoint", str(tmp)],
                               capture_output=True, text=True, timeout=600)
            if r.returncode != 0 or not tmp.exists():
                print(f"{name}: SKIP (the seed run failed: {r.stderr[:200]})")
                return {}
            shutil.copyfile(tmp, seed_path)
        corpus = [p.read_bytes().decode("latin-1")
                  for p in sorted(corpus_dir.glob(f"{name}*"))
                  if p.name == f"{name}.ckpt" or
                  not p.name.startswith(f"{name}-cert")]
    rng = random.Random(seed ^ (hash(name) & 0xFFFF))
    counts, names = {}, {}
    t0 = time.time()
    n = 0
    cur = work / "cur.ckpt"
    findings = 0

    while time.time() - t0 < seconds:
        if mode:
            text = rng.choice(corpus)
            for _ in range(1 + rng.randrange(3)):
                text = (mutate_cert(text, rng) if rng.randrange(4)
                        else mutate(text, rng))
            if rng.randrange(4):
                text = resum(text)
            shutil.rmtree(work / "cur.states", ignore_errors=True)
            shutil.copytree(work / "seed.states", work / "cur.states")
            for p in ("cur.cert", "cur.cert.tmp"):
                if (work / p).exists():
                    (work / p).unlink()
        else:
            text = mutate(rng.choice(corpus), rng)
            for _ in range(rng.randrange(3)):
                text = mutate(text, rng)
        # as mutated, byte for byte and LF and all: text mode on Windows
        # would make every LF a CRLF, which a version-3 reader refuses at
        # its first byte, and a default encoding other than latin-1 would
        # make another file than the one resum summed (ckpt_bytes)
        cur.write_bytes(ckpt_bytes(text))
        timed_out = False
        try:
            proc = subprocess.run(
                [str(exe), "--resume", "--checkpoint", str(cur)] +
                spec["resume"] + cert_args, capture_output=True, text=True,
                timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True

            class P:
                returncode = 0
                stderr = ""
            proc = P()
        verdict = classify(proc, timed_out)
        if verdict == "REFUSE":
            nm = refusal_name(proc)
            names[nm] = names.get(nm, 0) + 1
        if mode and verdict == "ACCEPT":
            verdict = accepted_certificate(work, mode, salt, reference)
        counts[verdict] = counts.get(verdict, 0) + 1
        n += 1
        if is_finding(verdict):
            findings += 1
            keep = HERE / "crashes" / "ckpt"
            keep.mkdir(parents=True, exist_ok=True)
            dst = keep / f"{name}-{verdict}-{findings:04d}.ckpt"
            if not dst.exists():
                # the bytes that were resumed, so that it replays on any
                # platform (in text mode Windows would write CRLF)
                dst.write_bytes(ckpt_bytes(text))
                (keep / f"{name}-{verdict}-{findings:04d}.log").write_text(
                    (proc.stderr or "")[:8000], errors="replace")
                print(f"  {name}: {verdict} -> {dst.name}")
    el = time.time() - t0
    summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"{name}: {n} resumes in {el:.0f}s ({n / el:.1f}/s)  {summary}")
    if names:
        print(f"  {name}: refused by " +
              ", ".join(f"{k} {v}" for k, v in sorted(names.items())))
    return counts


def accepted_certificate(work, mode, salt, reference):
    """A certified resume that was accepted runs to the end and writes
    its certificate. The same bytes as the uninterrupted run's: ACCEPT.
    Other bytes: the golden audit, in full from the states directory the
    resume left, must refuse it by name - ACCEPT-AUDIT-REFUSED-<name>, a
    checkpoint written to pass the sum whose certificate the audit
    catches - or it is a SILENT-WRONG resume. No certificate at all is
    ACCEPT-NO-CERTIFICATE. The last two are findings."""
    c = work / "cur.cert"
    if not c.exists():
        return "ACCEPT-NO-CERTIFICATE"
    data = c.read_bytes()
    if data == reference:
        return "ACCEPT"
    sys.path.insert(0, str(HERE.parents[1] / "python"))
    from cft_golden import cert            # the golden auditor
    d = work / "cur.states"
    states = {0: {int(p.name[len("run-0-boundary-"):-4]): p.read_bytes()
                  for p in d.glob("run-0-boundary-*.bin")}}
    try:
        cert.audit(data, salt.read_bytes() if mode == "keyed" else None,
                   {0: ((d / "run-0.cftp").read_bytes(), None)},
                   states=states)
    except cert.Refusal as e:
        return "ACCEPT-AUDIT-REFUSED-" + e.name
    return "SILENT-WRONG"


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
    bad = sum(v for k, v in total.items() if is_finding(k))
    if bad:
        print(f"{bad} checkpoint(s) did something other than refuse cleanly "
              f"- see host/fuzz/crashes/ckpt")
        # This used to `return 0` regardless, which made the driver report
        # success on exactly the outcomes its own docstring calls findings:
        # a crash, a hang, a sanitiser report, or an exit that is not the
        # contract's named refusal. run_ckpt.sh `exec`s this file, so that
        # zero was the whole chain's exit status and a fuzzing session that
        # found real defects looked clean to anything scripting it.
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
