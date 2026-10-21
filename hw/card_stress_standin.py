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
          short       (soak, the -all and -wide modes) a slice one ENCODING short: the tool ran
                      [lo, hi - 1) and says so, its counts consistent, exit 0
          shortcase   (soak, the same modes) the right encodings and ONE CASE too few, exit 0
          badenc      (soak, the same modes) the right cases, and an encodings clause ONE TOO FEW: the tool's own account of
                      what it covered contradicts the job, though its case count is the job's, exit 0
          skipoff     (soak, the hard-case and class-level modes) one skipped slot more and one case fewer than the mode's
                      whole-space counts spread over the slice: the cover rule (cases + skipped = k x E) still holds, so
                      only the sum over a covered item's slices can tell, exit 0
          nochunk     (soak, a chunked tool) the pass-size stderr line left out
          wrongchunk  (soak) a pass-size line saying twice the pass size the tool's name carries
          defchunk    (soak) a pass-size line, from a tool whose name carries no pass size (the default build prints none)
          slow:N      N seconds, then the normal verdict
    CFT_STANDIN_STATE=<dir>            where the counts are kept (required with a scenario)
    CFT_STANDIN_SOAK_RATE=<cases/s>    a soak takes cases / rate seconds (default 0: at once)
    CFT_STANDIN_TILES=<n>              tiles the identity says (default: 4 for a path with "quad")
  Every soak job also prints "standin: env CFT_SOAK_ARTIFACT=... CFT_XRT_TILES=..." (the two variables as the job was handed
  them, "<unset>" for none): the tests hold a host-pool job to neither, and a card job to its image and tile.

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

# The checks a slice of each exhaustive conversion/scaleB mode makes for every encoding of its operand:
# host/tools/clause5_soak.c's "Exhaustive modes" section, and hw/card_stress_lib.py's PER_ENCODING (the
# driver's tests hold this copy to the real tool's logs). cvtto32-all skips the pairs whose rounded value
# leaves the target's range; the stand-in does not know the operands, so it skips a third, which is
# only a count that adds up.
EXH_PER = {"conv32to64-all": 1, "cvtto32-all": 4, "cvtfrom32-all": 2, "cvtfrom64-all": 2,
           "scaleb32-all": 17, "scaleb32-wide": 568}

# The coverage wave's index-based modes (parcels HC and CL): op -> (the mode's indices, k checks an index, the skipped slots
# over its whole space). The stand-in cannot build the operands, so it SPREADS the whole space's skips evenly over the indices:
# a slice [lo, hi) skips g x (F(hi) - F(lo)) slots with F(x) = x x (whole skips / g) // indices (g = k where a skipped index
# skips all its k slots - the hard-case modes - and 1 for cvtto64-class, whose unit is a pair), so ANY partition of the space
# into slices gives the whole space's totals exactly, which is what the driver's whole-space check holds a covered item to.
# The suite holds this table equal to the library's, item for item. cvtto64-class's skips depend on the attribute.
IDX = {"div32-hard": (21235788, 4, 20596560), "div64-hard": (289685696, 4, 346253600), "sqrt64-hard": (4456448, 1, 2710696),
       "conv64to32-class": (136192, 1, 0), "rint64-class": (35840, 4, 0), "cvtto64-class": (40768, 4, None),
       "cvtfrom64-class": (50923, 1, 0), "scaleb64-class": (72648, 4, 0)}
CVTTO64_SKIPPED = {"rne": 72067, "rtz": 71588, "rdn": 77931, "rup": 71594, "rmm": 72086}
SCALEB_LIST = {"scaleb32": 17, "scaleb64": 27}       # the exponent lists random scaleB runs a batch against (clause5_soak.c)


def idx_skipped(op: str, mode: str, lo: int, hi: int) -> int:
    space, k, whole = IDX[op]
    if whole is None:
        whole = CVTTO64_SKIPPED[mode]
    g = k if op.endswith("-hard") else 1
    per = whole // g
    return g * ((hi * per) // space - (lo * per) // space)


def scaleb_cases(count: int, batch: int, ln: int) -> int:
    """Random scaleB's cases at a BATCH (clause5_soak.c drv_scaleb): a batch of n = min(left, BATCH) operands makes n x ln cases
    and takes that many off the count."""
    total, left = 0, count
    while left > 0:
        n = min(left, batch)
        total += n * ln
        left = left - n * ln if left > n * ln else 0
    return total


def chunk_of(argv0: str) -> int:
    """The pass size a chunked tool's name carries (divsqrt-soak-c16384, .exe or not), 0 for the default tool."""
    m = re.search(r"-c(\d+)(?:\.exe)?$", os.path.basename(argv0))
    return int(m.group(1)) if m else 0


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
    if leg == "soak":
        # what the driver's environment handed this job: the tests hold a host-pool job to "<unset>" for both
        # (a host job must not be able to name the card), and a card job to its image and its tile
        out(f"standin: env CFT_SOAK_ARTIFACT={os.environ.get('CFT_SOAK_ARTIFACT', '<unset>')} "
            f"CFT_XRT_TILES={os.environ.get('CFT_XRT_TILES', '<unset>')}")
    do = rule_for("soak" if leg == "soak" else leg, image) or ""
    fail = do == "fail"
    if do and do not in ("fail", "mismatch", "wrongsha", "wrongtiles", "software", "short", "shortcase", "badenc", "skipoff",
                         "nochunk", "wrongchunk", "defchunk"):
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
        tail = ""                 # the exhaustive modes' ", E encodings, S skipped" clause
        refuse = None             # a range the tool refuses by name, after its backend line, exit 2
        chunk = chunk_of(real[0])
        if op in IDX:
            lo, hi = int(real[2], 0), int(real[3], 0)
            space, k, _w = IDX[op]
            mode = real[4]
            if not 0 <= lo < hi <= space:
                refuse = f"need 0 <= lo < hi <= {space} (the indices of {op}), got [{real[2]}, {real[3]})"
                cases = 0
            else:
                enc = hi - lo - (1 if do == "short" else 0)
                skipped = idx_skipped(op, mode, lo, lo + enc) + (1 if do == "skipoff" else 0)
                cases = enc * k - skipped - (1 if do == "shortcase" else 0)       # skipoff: skipped one slot more, cases one fewer, the sum k x E
                if skipped and op == "cvtto64-class":
                    out(f"  skipped {skipped} lane-target pairs outside the target range (invalid table is model-pinned)")
                tail = f", {enc - (1 if do == 'badenc' else 0)} encodings, {skipped} skipped"
        elif op in ("sqrt32", "rint32", "nextup32", "nextdown32", "logb32", "class32") or op in EXH_PER:
            lo, hi = int(real[2], 0), int(real[3], 0)
            cases = hi - lo + (8 if op in ("nextup32", "nextdown32") else 0)
            mode = real[4] if len(real) > 4 else ("rne" if op == "conv32to64-all" else "-")
            if op in EXH_PER:
                enc = hi - lo - (1 if do == "short" else 0)
                skipped = (enc * EXH_PER[op]) // 3 if op == "cvtto32-all" else 0
                cases = enc * EXH_PER[op] - skipped - (1 if do == "shortcase" else 0)
                if skipped:
                    out(f"  skipped {skipped} lane-target pairs outside the target range "
                        f"(invalid table is model-pinned)")
                tail = f", {enc - (1 if do == 'badenc' else 0)} encodings, {skipped} skipped"
        else:
            cases = int(real[2], 0)
            if op in SCALEB_LIST and chunk:
                cases = scaleb_cases(cases, chunk, SCALEB_LIST[op])      # the chunked tools' BATCH, which sets the rounding
            mode = real[4] if len(real) > 4 else ("rne" if op == "conv32to64" else "-")
        art = os.environ.get("CFT_SOAK_ARTIFACT")
        if do == "software":
            art = None            # a soak that fell back to the software backend
        err(f"soaking the {'DEVICE' if art else 'software'} backend{': ' + art if art else ''}")
        if do == "wrongchunk":
            n = (chunk or 4096) * 2
            err(f"soaking with BATCH {n} and CFT_CHUNK {n} (the defaults are 4096)")
        elif do == "defchunk" and not chunk:
            err("soaking with BATCH 16384 and CFT_CHUNK 16384 (the defaults are 4096)")
        elif chunk and chunk != 4096 and do != "nochunk":
            err(f"soaking with BATCH {chunk} and CFT_CHUNK {chunk} (the defaults are 4096)")
        if refuse:
            err(refuse)
            return 2
        rate = float(os.environ.get("CFT_STANDIN_SOAK_RATE") or 0)
        if rate > 0:
            time.sleep(cases / rate)
        if do == "mismatch":
            out(f"  MISMATCH {mode if mode != '-' else op} a=0x3f800001 lib=0x3f800000 cpu=0x3f800001")
            out(f"  FLAGS {mode if mode != '-' else op} a=0x3f800002 lib=0x01 cpu=0x00")
            out(f"{op} {mode}: {cases} cases, 1 value mismatches, 1 flag mismatches{tail}")
            return 1
        out(f"{op} {mode}: {cases} cases, 0 value mismatches, 0 flag mismatches{tail}")
        return 0

    print(f"card_stress_standin: no stand-in for leg {leg!r}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
