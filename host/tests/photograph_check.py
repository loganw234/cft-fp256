# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""A GPU's record of a real workload, reproduced bit for bit.

    python host/tests/photograph_check.py [--case DIR] [--device sw|IMAGE]
                                          [--runner PATH] [--jobs N]

The case (host/tests/photograph/hopf, and its README) is atlas-engine's
deterministic camera around a plate, lowered to a sequencer program: the
sample index in, five 32-bit words a sample out, one constant bank a
pass. The expected SHA-256 of each pass's deposit buffer was written by
an NVIDIA GPU rendering the same frame from pinned GLSL - so nothing
this project computed is on the expected side of the comparison.

Every pass goes through `positive-run --iota N --bank ... --out ...`,
side by side, and three things must hold for each: the runner exits
clean, the hash it PRINTS is the GPU's, and the hash of the buffer it
WROTE is the GPU's. Two hashes because they fail differently - a runner
that printed the right word over the wrong bytes is a defect a single
comparison cannot see. STATUS must be zero; the IEEE flags are reported
and not judged (the GPU has none to compare).

The fixture is checked against its own record first, so a damaged
fixture is named as that and not as a library that disagrees.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = HERE.parent


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def default_runner():
    name = "positive-run.exe" if os.name == "nt" else "positive-run"
    return HOST / name


def load_case(case):
    """The passes of a case, each with its bank and the GPU's hash, after
    holding the fixture to its own record."""
    rec = json.loads((case / "camera.json").read_text(encoding="utf-8"))
    problems = []
    image = case / rec["image"]["file"]
    if sha256_file(image) != rec["image"]["sha256"]:
        problems.append("%s is not the image camera.json records" % image.name)
    listed = {}
    for line in (case / "deposits.SHA256").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([0-9a-f]{64})\s+\*?records\.(p\d+)\.bin\s*$", line)
        if m:
            listed[m.group(2)] = m.group(1)
    passes = []
    for p in rec["passes"]:
        tag = "p%04d" % p["pass"]
        bank = case / p["bank"]["file"]
        if sha256_file(bank) != p["bank"]["sha256"]:
            problems.append("%s is not the bank camera.json records" % bank.name)
        want = p["expect"]["sha256"]
        if listed.get(tag) != want:
            problems.append("deposits.SHA256 and camera.json disagree about "
                            "pass %s" % tag)
        passes.append((tag, bank, want))
    if len(listed) != len(passes):
        problems.append("deposits.SHA256 lists %d passes and camera.json %d"
                        % (len(listed), len(passes)))
    return rec, image, passes, problems


def run_pass(runner, image, lanes, bank, device, out):
    t0 = time.time()
    proc = subprocess.run([str(runner), str(image), "--iota", str(lanes),
                           "--bank", str(bank), "--out", str(out),
                           "--device", device],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          universal_newlines=True)
    seconds = time.time() - t0
    text = proc.stdout or ""

    def field(name):
        m = re.search(r"^%s\s+(\S+)" % name, text, re.M)
        return m.group(1) if m else None

    wrote = sha256_file(out) if os.path.exists(out) else None
    return {"rc": proc.returncode, "seconds": seconds, "said": field("sha256"),
            "wrote": wrote, "status": field("status"), "flags": field("flags"),
            "tail": text.strip().splitlines()[-3:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", default=str(HERE / "photograph" / "hopf"))
    ap.add_argument("--device", default="sw",
                    help="sw, or an artifact positive-run can open")
    ap.add_argument("--runner", default=str(default_runner()))
    ap.add_argument("--jobs", type=int, default=0,
                    help="passes side by side (default: every pass, up to "
                         "the machine's cores; 1 on a device)")
    args = ap.parse_args()

    case = Path(args.case)
    runner = Path(args.runner)
    if not runner.is_file():
        print("photograph_check: %s is not built - make -C host positive-run"
              % runner)
        return 2
    rec, image, passes, problems = load_case(case)
    if problems:
        for p in problems:
            print("photograph_check: FIXTURE: " + p)
        return 2

    lanes = int(rec["frame"]["samples_a_pass"])
    gpu = rec.get("device", {})
    print("%s: %d passes of %d samples, %d instructions; expected = %s, %s"
          % (rec.get("plate", case.name), len(passes), lanes,
             rec.get("words", 0), gpu.get("renderer", "a GPU"),
             gpu.get("gl_version", "")))
    jobs = args.jobs or (1 if args.device != "sw"
                         else max(1, min(len(passes), os.cpu_count() or 1)))

    tmp = Path(tempfile.mkdtemp(prefix="cft-photograph-"))
    failed = 0
    try:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            futures = [(tag, want, pool.submit(run_pass, runner, image, lanes,
                                               bank, args.device,
                                               tmp / ("deposits.%s.bin" % tag)))
                       for tag, bank, want in passes]
            for tag, want, fut in futures:
                r = fut.result()
                bad = []
                if r["rc"] != 0:
                    bad.append("the runner exited %d" % r["rc"])
                if r["wrote"] != want:
                    bad.append("the buffer it wrote hashes to %s"
                               % (r["wrote"] or "nothing - no file"))
                if r["said"] != want:
                    bad.append("the hash it printed is %s" % r["said"])
                if r["status"] is not None and int(r["status"], 16) != 0:
                    bad.append("STATUS %s" % r["status"])
                if bad:
                    failed += 1
                    print("  pass %s  DIFFER   %.0f s   the GPU recorded %s; %s"
                          % (tag, r["seconds"], want, "; ".join(bad)))
                    for line in r["tail"]:
                        print("      | " + line)
                else:
                    print("  pass %s  MATCH    %.0f s   %s   flags %s"
                          % (tag, r["seconds"], want, r["flags"]))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)

    if failed:
        print("photograph_check: %d of %d passes are not the GPU's bytes"
              % (failed, len(passes)))
        return 1
    print("photograph_check: every pass is the GPU's record, bit for bit "
          "(%s, %d at a time)" % (args.device, jobs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
