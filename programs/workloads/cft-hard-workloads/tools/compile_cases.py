#!/usr/bin/env python3
"""Run an actual compiler command against source cases, without a shell.

Example (substitute YOUR compiler's real flags):
  python tools/compile_cases.py --command 'YOUR_COMPILER {source} ... {out}'
Each case gets a separate output directory and per-case stdout/stderr files.
This tests acceptance/refusal only. It does not prove numerical correctness.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_mutually_exclusive_group(required=True)
    command.add_argument("--command", help="compiler argv in POSIX quoting syntax; use forward-slash paths on Windows, or prefer --command-json")
    command.add_argument("--command-json", help="JSON array of argv strings; preserves native Windows backslashes and spaces; {source}, {out}, {id}, {steps} substituted token by token")
    parser.add_argument("--include-stress", action="store_true")
    parser.add_argument("--only", help="regular expression selecting case IDs")
    parser.add_argument("--smoke", action="store_true", help="select the seven main workloads (same selection as the default)")
    parser.add_argument("--results", default="compiler-results.jsonl")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--cwd", help="compiler working directory; defaults to the current directory")
    parser.add_argument("--hash-seeds", default="", help="optional comma-separated PYTHONHASHSEEDs; reruns compilation, preserving each output")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        template = json.loads(args.command_json) if args.command_json is not None else shlex.split(args.command)
    except (ValueError, TypeError) as exc:
        parser.error("invalid compiler command: " + str(exc))
    if not isinstance(template, list) or not template or not all(isinstance(x,str) for x in template):
        parser.error("compiler command must be a nonempty array of strings")
    if not template or not any("{source}" in token for token in template):
        parser.error("--command must contain {source}")
    seeds = args.hash_seeds.split(",") if args.hash_seeds else [None]
    steps_provided = any("{steps}" in token for token in template)
    catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
    selected = catalog["cases"]
    if args.smoke:
        by_id = {c["id"]: c for c in selected}
        selected = [by_id[ident] for ident in catalog["smoke_order"]]
    results = Path(args.results).resolve()
    results.parent.mkdir(parents=True, exist_ok=True)
    work = results.parent / (results.stem + "-outputs-" + str(time.time_ns()))
    counts = collections.Counter()
    # Line-buffered output survives interruption; this is not a parallel runner.
    with results.open("w", buffering=1, encoding="utf-8", newline="\n") as log:
        for case in selected:
            if case["kind"] not in ("valid", "refusal", "compiler-refusal", "investigation"):
                continue
            if case.get("stress") and not args.include_stress:
                continue
            if args.only and not re.search(args.only, case["id"]):
                continue
            for seed in seeds:
                ident = case["id"] + ("-hash-" + seed if seed is not None else "")
                output = work / ident
                output.mkdir(parents=True, exist_ok=True)
                substitutions = {"source": str((ROOT / case["file"]).resolve()), "out": str(output), "id": case["id"], "steps": str(case.get("compile_steps", 1))}
                argv = [re.sub(r"\{(source|out|id|steps)\}", lambda match: substitutions[match[1]], token) for token in template]
                env = os.environ.copy()
                if seed is not None:
                    env["PYTHONHASHSEED"] = seed
                start = time.monotonic()
                row = {"id": case["id"], "hash_seed": seed, "kind": case["kind"], "argv": argv, "source_sha256": case["sha256"]}
                try:
                    done = subprocess.run(argv, cwd=args.cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=args.timeout)
                    stdout, stderr = done.stdout, done.stderr
                    row["returncode"] = done.returncode
                    message = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
                    names = sorted({n for n in catalog["refusal_names"] if re.search(r"(?<![a-z0-9_-])" + re.escape(n) + r"(?![a-z0-9_-])", message)})
                    row["observed_refusals"] = names
                    if done.returncode == 70 or "cftc: internal error" in message:
                        verdict = "INTERNAL-ERROR"
                    elif done.returncode < 0 or done.returncode >= 0xC0000000:
                        verdict = "CRASH"
                    elif case["kind"] == "investigation":
                        verdict = "OBSERVED"
                    elif case["kind"] == "compiler-refusal" and case.get("needs_steps_placeholder",True) and not steps_provided:
                        verdict = "UNTESTED-STEPS"
                    elif case["kind"] in ("refusal", "compiler-refusal"):
                        verdict = "PASS" if done.returncode != 0 and case["expected_refusal"] in names else "FAIL"
                    elif done.returncode == 0:
                        verdict = "PASS"
                    elif set(names) & set(case.get("allowed_target_refusals", [])):
                        verdict = "TARGET-LIMIT"
                    else:
                        verdict = "FAIL"
                except subprocess.TimeoutExpired as exc:
                    stdout, stderr = exc.stdout or b"", exc.stderr or b""
                    verdict = "TIMEOUT"
                except OSError as exc:
                    stdout, stderr = b"", str(exc).encode()
                    verdict = "ERROR"
                (output / "stdout.txt").write_bytes(stdout)
                (output / "stderr.txt").write_bytes(stderr)
                # Hashes are for comparing reruns; source path comments may cause
                # text differences. Compare graph/image/bank, not every text file.
                row["artifacts"] = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(output.rglob("*")) if p.is_file() and p.name not in ("stdout.txt", "stderr.txt")}
                row.update(verdict=verdict, elapsed_seconds=round(time.monotonic() - start, 6), output_dir=str(output))
                log.write(json.dumps(row, sort_keys=True) + "\n")
                counts[verdict] += 1
                print(f"{verdict:16} {ident}", flush=True)
    print(json.dumps(dict(counts), sort_keys=True))
    print("Results:", results)
    return int(any(counts[x] for x in ("FAIL", "TIMEOUT", "ERROR", "INTERNAL-ERROR", "CRASH")))


if __name__ == "__main__":
    raise SystemExit(main())
