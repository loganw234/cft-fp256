#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The stand-in for every command of hw/card_stress.py's dry run: no XRT, no card.

    card_stress_standin.py LEG -- <the real argv the driver would have run>

It prints the verdict lines the real tool prints - the text of each printf is the one in the
tool's source (hw/card_stress_lib.py cites file and line for each), and the numbers are those
quoted in docs/VALIDATION.md's 2026-10-06 and 2026-10-12 card runs - so the driver's parsers
read real shapes, not shapes invented for them. And it misbehaves when told to, so the driver's
failure policy meets each kind of failure:

    CFT_STANDIN_SCENARIO=<file.json>   a list of rules
        {"leg": "dt-full", "nth": [2, 3], "do": "fail"}          the 2nd and 3rd dt-full
        {"leg": "soak", "image": "quad", "from": 4, "do": "slow:2"}
      leg: the leg's name, or "soak" for every sweep job, or "telemetry"; image: quad, single or
      deep (from the xclbin's file name; optional); nth: a list, or from/to: a range, of the
      1-based count of invocations of that leg (and image, when given).
      do: fail        the tool's own failure verdict (a wrong answer), exit 1
          nodevice    "no such device", exit 2 (a no-device open)
          poison      a tile left running by an abandoned run: refused at open, exit 2
          hang        sleeps forever, ignoring nothing
          hangdeaf    sleeps forever and ignores SIGTERM (the driver must escalate to KILL)
          garbage     exits 0 and prints nothing a parser can read
          crash       exits 139 with no verdict
          mismatch    (soak) a disagreement with its operands, exit 1
          slow:N      N seconds, then the normal verdict
    CFT_STANDIN_STATE=<dir>            where the counts are kept (required with a scenario)
    CFT_STANDIN_SOAK_RATE=<cases/s>    a soak takes cases / rate seconds (default 0: at once)
    CFT_STANDIN_TILES=<n>              tiles the identity says (default: 4 for a path with "quad")

Python 3.10 or later; standard library only. The text below that is NOT a tool's own is marked.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import sys
import tempfile
import time


def count(state: str, key: str) -> int:
    """The 1-based invocation number for `key`, kept in a file under a lock (soak jobs of one
    wave run at once)."""
    os.makedirs(state, exist_ok=True)
    lock = os.path.join(state, "lock")
    for _ in range(2000):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            time.sleep(0.005)
    try:
        p = os.path.join(state, "n-" + re.sub(r"[^A-Za-z0-9_.-]", "_", key))
        n = 0
        if os.path.exists(p):
            n = int(open(p).read() or 0)
        n += 1
        with open(p, "w") as fh:
            fh.write(str(n))
        return n
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


OP = ""      # a soak job's op (argv[1] after the binary), for rules that name one


def image_name(args) -> str:
    for a in args:
        low = os.path.basename(a).lower()
        if low.endswith(".xclbin"):
            for n in ("quad", "single", "deep"):
                if n in low:
                    return n
    art = os.environ.get("CFT_SOAK_ARTIFACT", "")
    for n in ("quad", "single", "deep"):
        if n in os.path.basename(art).lower():
            return n
    return ""


def rule_for(leg: str, image: str):
    sc = os.environ.get("CFT_STANDIN_SCENARIO")
    if not sc:
        return None
    state = os.environ.get("CFT_STANDIN_STATE") or os.path.dirname(sc)
    rules = json.load(open(sc))
    hit = None
    cache = {}
    for r in rules:
        if r.get("leg") != leg:
            continue
        if r.get("image") and r["image"] != image:
            continue
        if r.get("op") and r["op"] != OP:
            continue
        key = f"{leg}-{r.get('image') or 'any'}-{r.get('op') or 'any'}"
        if key not in cache:
            cache[key] = count(state, key)
        n = cache[key]
        if "nth" in r and n in r["nth"]:
            hit = r["do"]
        elif "from" in r and n >= r["from"] and n <= r.get("to", 10 ** 9):
            hit = r["do"]
    return hit


def sha_of(path: str):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def find_xclbin(args):
    for a in args:
        if a.lower().endswith(".xclbin"):
            return a
    return None


def out(s: str = "") -> None:
    sys.stdout.write(s + "\n")
    sys.stdout.flush()


def err(s: str) -> None:
    sys.stderr.write(s + "\n")
    sys.stderr.flush()


def apply_misbehaviour(do: str, leg: str, xb) -> bool:
    """True when the behaviour ended the run; False for 'slow' (carry on afterwards)."""
    if do == "hang" or do == "hangdeaf":
        if do == "hangdeaf" and hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        state = os.environ.get("CFT_STANDIN_STATE")
        if state:
            with open(os.path.join(state, f"hang-{leg}-{os.getpid()}.pid"), "w") as fh:
                fh.write(str(os.getpid()))
        out("standin: hanging")
        time.sleep(10 ** 6)
        sys.exit(0)
    if do == "nodevice":
        err(f"device {xb}: no such device\n  opening device 0: (stand-in) xclbin not loadable")
        if leg == "soak":
            err(f"cft_open({xb}) failed: no such device")
        sys.exit(2)
    if do == "poison":
        err("device " + str(xb) + ": internal error\n  tile 2 (cft_krnl:{cft_krnl_2}) is already running "
            "when this handle opens it (stand-in)")
        sys.exit(2)
    if do == "garbage":
        out("(stand-in) a log with no verdict line")
        sys.exit(0)
    if do == "crash":
        err("(stand-in) segmentation fault")
        sys.exit(139)
    if do.startswith("slow:"):
        time.sleep(float(do[5:]))
        return False
    return False


def main() -> int:
    argv = sys.argv[1:]
    if "--" not in argv:
        print("usage: card_stress_standin.py LEG -- <real argv>", file=sys.stderr)
        return 2
    leg = argv[0]
    real = argv[argv.index("--") + 1:]
    global OP
    OP = real[1] if leg == "soak" and len(real) > 1 else ""
    xb = find_xclbin(real)
    image = image_name(real)
    # the header goes to stderr for telemetry, whose stdout is parsed as the tool's own
    (err if leg == "telemetry" else out)("standin: would run: " + " ".join(real))
    if hasattr(os, "nice") and leg != "telemetry":
        # how the driver started this process: its niceness, and its parent's command line
        # (on Linux, the `timeout` wrapper), for the tests to hold to the stated policy
        out(f"standin: nice {os.nice(0)}")
        try:
            with open(f"/proc/{os.getppid()}/cmdline", "rb") as fh:
                out("standin: parent: " + fh.read().replace(bytes([0]), b" ").decode("utf-8", "replace").strip())
        except OSError:
            pass
    do = rule_for("soak" if leg == "soak" else leg, image) or ""
    fail = do == "fail"
    if do and do not in ("fail", "mismatch", "wrongsha", "wrongtiles", "software"):
        apply_misbehaviour(do, leg, xb)

    tiles = int(os.environ.get("CFT_STANDIN_TILES") or (4 if "quad" in (xb or "") else 1))

    if leg == "telemetry":
        # NOT a tool's own text: the shape xbutil's JSON is BELIEVED to have, with values moving
        # a little each call so a trend exists. The driver reads numbers wherever they are.
        n = count(os.environ.get("CFT_STANDIN_STATE") or os.path.join(tempfile.gettempdir(), "card-stress-standin"),
                  "telemetry-values")
        rep = real[real.index("-r") + 1] if "-r" in real else "electrical"
        if rep == "thermal":
            doc = {"thermals": [{"location_id": "fpga0", "description": "FPGA Temperature", "temp_C": str(30 + n * 0.5)},
                                {"location_id": "hbm", "description": "HBM Temperature", "temp_C": str(32 + n * 0.25)}]}
        elif rep == "electrical":
            doc = {"power_consumption_watts": str(15.0 + 0.5 * (n % 7)),
                   "power_rails": [{"id": "12v_pex", "description": "12 Volts PCI Express",
                                    "voltage": {"volts": "12.1"}, "current": {"amps": str(1.2 + 0.1 * (n % 5))}}]}
        else:
            print("ERROR: unknown report " + rep, file=sys.stderr)
            return 1
        if "--output" in real:
            with open(real[real.index("--output") + 1], "w") as fh:
                json.dump(doc, fh)
            out("Successfully wrote the JSON file")
        else:
            out(json.dumps(doc))
        return 0

    if leg == "api-test":
        if fail:
            out("api-test: 3 FAILED")
            return 1
        out("api-test: all contract checks passed")
        return 0

    if leg.startswith("dt-"):
        sha, size = sha_of(xb)
        if do == "wrongsha":
            sha = "0" * 64
        if do == "wrongtiles":
            tiles = tiles + 1
        mode = "i" if "-i" in real else leg
        out("libcft build commit=0123456789abcdef tracked=clean untracked=none")
        out(f"device: backend xrt, {tiles} tile{'s' if tiles != 1 else ''}, contract 0x00000b00, "
            f"formats fp32 fp64 fp128 fp256")
        out(f"image: sha256 {sha}, {size} bytes, VERSION 0x00000b00, CAPS 0x19faffff, CAPS2 0x00187ffc")
        if mode == "i":
            if fail:
                out("\n23 checks, 1 failed")
                return 1
            out("\n23 checks, 0 failed")
            out("the device image's identity holds")
            return 0
        checks = {"dt-q8": 2733, "dt-full": 10373, "dt-r": 2416, "dt-b": 180}.get(leg, 100)
        if fail:
            out(f"\n{checks} checks, 2 failed")
            return 1
        out(f"\n{checks} checks, 0 failed")
        out("not on this device, each named above: NOT COMPARED 0 formats, 0 buffers legs, 0 opcodes "
            "and 0 other legs; NOT TESTED 5; NOT RUN 0")
        out("the device and the software backend agree on every case that RAN, bits and flags")
        return 0

    if leg == "card-segrun":
        if fail:
            out("  FAIL  the certificates made on this card: ...")
            out("== card-segrun: 6 checks, 1 failed")
            out("   logs kept in /nonexistent/stand-in")
            return 1
        out("  ok    the certificates made on this card: 695 checks, 0 failed, 0 skipped")
        out("== card-segrun: 6 checks, 0 failed")
        return 0

    if leg == "seq-check":
        dev = real[real.index("--device") + 1]
        out(f"device {dev}: backend xrt, {tiles} tiles, contract 0x00000b00, seq_features 0x7ff1f, "
            f"max_scratch 4096; the model runs at 4096 scratch slots a lane")
        out("\n1234 programs run through both implementations, 321 refused by both")
        if fail:
            out("3 DISAGREEMENTS")
            return 1
        out(f"the device ({dev}) and the golden model agree on every program it ran: deposits, counts, flags "
            f"and status, and every lane byte where asked; it refused by name every program needing a bit "
            f"it does not publish")
        return 0

    if leg in ("acceptance", "acceptance-rev8"):
        dev = real[real.index("--device") + 1]
        rev8 = leg == "acceptance-rev8"
        only = real[real.index("--only") + 1].split(",") if "--only" in real else None
        tgt = real[real.index("--target") + 1] if "--target" in real else None
        n = len(only) if only else (9 if rev8 else 20)
        slow = int(os.environ.get("CFT_STANDIN_ACCEPT_SECONDS") or 0)
        on = dev + (f" as {tgt}" if tgt else "")
        name = "acceptance rev8" if rev8 else "acceptance"
        if fail:
            out(f"\n== verdicts\nFAIL (stand-in)\n{name}: {n - 1} of {n} PASS on {on} (set); 100 checks ok, "
                f"2 failed, {slow} s")
            return 1
        out("\n== verdicts")
        out(f"{name}: {n} of {n} PASS on {on} (set); {n * 9 + 9} checks ok, 0 failed, {slow or 371} s")
        return 0

    if leg == "resident":
        if fail:
            out("2 row(s) FAILED a check")
            return 1
        out("every row: status clean, the same bytes on every unit, on repeat, and in software")
        return 0

    if leg == "selftest":
        if fail:
            out("CONFORMANCE FAILED: a case differs (stand-in)")
            return 1
        out("1224915 cases checked")
        return 0

    if leg == "soak":
        op = real[1]
        if op in ("sqrt32", "rint32", "nextup32", "nextdown32", "logb32", "class32"):
            lo, hi = int(real[2], 0), int(real[3], 0)
            cases = hi - lo + (8 if op in ("nextup32", "nextdown32") else 0)
            mode = real[4] if len(real) > 4 else "-"
        else:
            cases = int(real[2], 0)
            mode = real[4] if len(real) > 4 else ("rne" if op == "conv32to64" else "-")
        art = os.environ.get("CFT_SOAK_ARTIFACT")
        if do == "software":
            art = None            # a soak that fell back to the software backend
        err(f"soaking the {'DEVICE' if art else 'software'} backend{': ' + art if art else ''}")
        rate = float(os.environ.get("CFT_STANDIN_SOAK_RATE") or 0)
        if rate > 0:
            time.sleep(cases / rate)
        if do == "mismatch":
            out(f"  MISMATCH {mode if mode != '-' else op} a=0x3f800001 lib=0x3f800000 cpu=0x3f800001")
            out(f"  FLAGS {mode if mode != '-' else op} a=0x3f800002 lib=0x01 cpu=0x00")
            out(f"{op} {mode}: {cases} cases, 1 value mismatches, 1 flag mismatches")
            return 1
        out(f"{op} {mode}: {cases} cases, 0 value mismatches, 0 flag mismatches")
        return 0

    print(f"card_stress_standin: no stand-in for leg {leg!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
