#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""A long-run stress driver for the U50: cycles of the card's own checks on revision 8's
three images, weighted toward the four-tile quad, with the native-oracle soaks worked
through slice by slice in the time between, and metrics kept as it goes.

    bash hw/card-stress.sh --until "2026-10-19 08:00" [--out DIR]     the long run
    bash hw/card-stress.sh --quick                                    the smoke
    bash hw/card-stress.sh --dry-run ...                              no XRT, no card
    touch $OUT/STOP                                                   stop after the leg running
    python3 hw/card_stress_report.py $OUT                             read a run, any time

docs/CARDDAY.md, "The long run", is the operator's page: how to start, stop and read it,
and what it guarantees and does not. This file's text is the design.

WHAT A CYCLE IS. The driver picks an image by a smooth weighted rotation (default quad 4,
single 1, deep 1), runs the battery of legs on it - each an existing tool, below - and then
fills the rest of the cycle with sweep slices of the soaks. Opening an image IS switching to
it: libcft's cft_open loads the xclbin bytes through XRT (host/src/backend_xrt.cpp, the
`D->dev.load_xclbin(*xb)` of cftx_open), so there is no separate programming step to script.
XRT treats loading the xclbin already on the card as a no-op, which is why a tile left
running by an abandoned run is cured by loading ANOTHER image and then this one
(docs/HOSTAPI.md, "A tile a run was abandoned on") and why the failure policy below does
exactly that.

THE LEGS (each a command the 2026-10-06 and 2026-10-12 card runs used; docs/VALIDATION.md):
  api-test         host/api-test: "all contract checks passed"
  dt-i             hw/run-device-test.sh IMAGE -i: the image's identity (SHA-256 and tiles
                   held to the driver's own check of the file)
  dt-q8, dt-full,  device-test against the software backend: -q -n 8, -n 4096, -r, -b -n 4096
  dt-r, dt-b       ("the device and the software backend agree on every case that RAN")
  card-segrun      hw/card-segrun.sh IMAGE: the segment runner's card leg, certificates audited
  seq-check        host/tests/seq_check.py --device IMAGE: the eight corpora on the card
  acceptance       programs/acceptance.py --device IMAGE: the card's admission test
  acceptance-rev8  the revision-8 set, --target the image, only the entries the rule gives that
                   image: the quad's nine workloads and six routine entries (the routine
                   entries read committed files and --lib host/libcft.so), the deep's one
  resident, selftest  (beyond the brief) cft-resident IMAGE; cft-selftest vectors/out IMAGE,
                   every third visit
and the SWEEP: hw/run-soak.sh's and hw/run-c5-soak.sh's own campaigns (their job lines,
hw/card_stress_lib.py's sweep_items), run slice by slice, resumed across cycles from
metrics.jsonl alone. The scripts themselves cannot be sliced or resumed (each wipes its own
output directory and runs everything), so this driver runs the same binaries on the same job
lines. Each item is marked TILE or HOST (hw/card_stress_lib.py, OP_REACH, from the library's own
composed/host classification), and the two kinds run in different places (since 2026-10-20):
  - the card's sweep, between the battery legs of each cycle, takes TILE items only, with
    CFT_SOAK_ARTIFACT naming the image (one job a tile on the quad);
  - a HOST item - the conversions, next, logB, class, remainder - is libcft's host code, which
    "contains NO floating-point arithmetic at all" and is "bit-identical on every backend by
    construction" (host/src/clause5.c, 11-35): a test of the library in which the tile computes
    nothing. It runs on the HOST POOL, --host-workers CPU-only jobs (default 8) from the run's
    start to its end, beside the battery and the card's sweep, niced like every leg, with no
    CFT_SOAK_ARTIFACT and no CFT_XRT_TILES - the software backend, no card opened - and their
    slices are recorded like the card's, under the image name `cpu`.
The records (sweep.reach), status.txt and the report say which an item is. The exhaustive
conversion and scaleB modes (the -all and -wide items) also say what they covered on their
verdict line, and a slice's encodings are held to it exactly. A random slice's seed is
(item index << 40) | (n << 1) | 1 and n continues across runs (--earlier-runs); the run records
the RTL tree it runs from, and the report counts coverage per tree.
Since 2026-10-21 (parcel DR3, the coverage wave) the catalog has 35 more items, the hard-case and class-level modes
(hw/card_stress_lib.py: Item.space, HARD_SPACE, CLASS_SPACE): each exhaustive over a space of its own, held to cases + S = k x E
and, once wholly covered, to its whole-space figures. --records writes the finished sweep slices as canonical records through
hw/sweep_record.py (RecordSink; --sign-key signs them) and --sweep-chunk N runs the sweep's slices with the tools built at
pass size N, recording the batch and chunk each said. docs/CARDDAY.md, "The coverage wave in the driver", is the operator's page.

RECORDS. $OUT/metrics.jsonl is append-only: one `leg` record a leg, one `telemetry` record a
sample, with `run_start`, `build`, `cycle_start`, `cycle_end`, `event` and `run_end` between
(fields: hw/card_stress_lib.py and docs/CARDDAY.md). $OUT/status.txt is rewritten after every
leg. A count in a record is a captured group of a line a pattern matched, or it is absent; a log
a pattern cannot read is a `parse_error` leg, kept whole. Nothing is defaulted to 0.

FAILURE POLICY. A failing leg keeps its whole log and the run goes on. The card not answering
(a no-device open, a tile left poisoned, or a hang past the leg's timeout) is retried after a
pause; the second consecutive time the driver opens another image and comes back; after
--max-card-failures in a row it stops, writes $OUT/STOPPED.txt and leaves the card idle. A stop
(the stop file, SIGINT or SIGTERM, the deadline) comes after the leg running, never in the
middle of one: an abandoned card run poisons its tile until an image reload. An unexpected
exception in the driver itself is recorded (event driver_error, with its traceback) and the next
cycle begins - the fifth in a row stops the run; a sweep item whose slices keep giving logs no
parser can read is disabled for the rest of the run, recorded, rather than starving the others;
a metrics file torn by a killed run is repaired on --resume.

PROCESSES. Every leg runs under `nice -n 10` and GNU `timeout --kill-after`; the driver
signals only the process groups it started, by PID, and never by a pattern. A guard refuses to
start, and waits between legs, while another process uses the card (it detects, never kills);
verify/run.sh runs, which use none, are allowed and recorded.

THE DRY RUN. --dry-run replaces every command by hw/card_stress_standin.py (which prints
the tools' real verdict lines, and fails, hangs or loses the device on a scripted schedule);
everything else - the scheduler, rotation, deadline, stop file, failure policy, disk floor,
guard, metrics and the parsers - is this code. hw/test_card_stress.py drives it.

Python 3.10 or later; standard library only.
"""
from __future__ import annotations

import argparse
import datetime
import glob
import gzip
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import card_stress_lib as L  # noqa: E402

ROOT = os.path.dirname(HERE)
POSIX = os.name == "posix"

# ---------------------------------------------------------------------------
# the images, and what each is (docs/VALIDATION.md, step 6's closing records, 2026-10-06)
# ---------------------------------------------------------------------------
IMAGES = {
    # name: (default path, tiles, programs/acceptance.py's --target, SHA-256 read from
    #        docs/VALIDATION.md at 582953c; also checked against the SHA256SUMS beside it)
    "quad": ("$HOME/cardday-rev8q/cft_hw_quad.xclbin", 4, "u50-rev8-quad",
             "4f9921a25af65444abc5c267fff1117a8e14abbc16a75de643e43c9dbf6ef53b"),
    "single": ("$HOME/cardday-rev8a/cft_hw_single.xclbin", 1, "u50-rev8",
               "0639248e9c66f779e7c126f4449062af646d3d7e8abd0173926812790bc80450"),
    "deep": ("$HOME/cardday-rev8d/cft_hw_deep.xclbin", 1, "u50-rev8-deep",
             "bbf08fb3feb60940bcbdfcf0eebef12de8fd55c7d302b2f896534c49447316fa"),
}

# programs/acceptance.py, REV8 and REV8_ROUTINES: the revision-8 set's entries and the image the
# rule picks for each - the ten workloads, then the six routine entries (parcel MA, 2026-10-19),
# all six on the quad. hw/test_card_stress.py reads that source and fails if this table is not
# both tuples, entry for entry, or if acceptance.py has a REV8 name the test has not been shown.
# The six were missing from here from 2026-10-19 to 2026-10-20: the test read REV8 alone and
# counted its ten, so a second tuple in the same file went by unseen.
# A routine entry's image and bank are committed files (programs/systems/compiled-tangent/): no
# compile, nothing to cache in --rev8-images, which acceptance.py ignores for them.
REV8_ROUTINE_ENTRIES = ("lotkavolterra-rk4-tangent-fp64", "lotkavolterra-rk4-tangent-fp256",
                        "diode-rk4-tangent-fp64", "diode-rk4-tangent-fp256",
                        "culture-rk4-tangent-fp64", "culture-rk4-tangent-fp256")
REV8_ENTRIES = {
    "u50-rev8-quad": ["gray_scott_hard_fp64", "gray_scott_wide_fp256",
                      "lorenz_tangent_hard_fp64", "lorenz_tangent_wide_fp256",
                      "fput_extended_fp64", "phi4_extended_fp64",
                      "kuramoto_sivashinsky_extended_fp64", "reservoir_extended_fp64",
                      "riccati_extended_fp64"] + list(REV8_ROUTINE_ENTRIES),
    "u50-rev8": [],
    "u50-rev8-deep": ["gray_scott_extended_fp64"],
}
# Compiles of 40 minutes (Gray-Scott extended) and 2.2 hours (Riccati extended) on the box
# (programs/acceptance.py, the note above REV8): left out unless their image and bank are
# already cached.
REV8_LONG_COMPILES = ("gray_scott_extended_fp64", "riccati_extended_fp64")
# Short entries for --quick: a revision-7 set entry or two, the revision-8 entry that compiles
# in 51 s (phi4_extended_fp64, the same note) and, on the quad, one routine entry: it has no
# compile, so the smoke takes the routine path (the --lib probe, the structured lanes) on the
# card instead of the long run's first cycle finding out.
QUICK_ACCEPT_ONLY = "lorenz63-rk4-fp64,lorenz96-rk4-fp64"
QUICK_REV8_ONLY = {"u50-rev8-quad": "phi4_extended_fp64",
                   "u50-rev8-deep": "gray_scott_extended_fp64"}
QUICK_REV8_ROUTINE = {"u50-rev8-quad": "lotkavolterra-rk4-tangent-fp64"}
# --quick's sweep. The card's: TILE items only (a host item is the pool's), so each soak tool is still shown once on
# the quad - divsqrt by sqrt32-rne and div32-rne, clause5 by rint32-rne and rint64-rne (the fourth was nextup32,
# a host item, until 2026-10-20). The pool's: one slice of each of these, a plain exhaustive item with edge cases,
# one that says what it covered, and a random one, all of 2^18 (--quick-slice-cases), seconds on a CPU.
QUICK_QUAD_ITEMS = ("sqrt32-rne", "rint32-rne", "div32-rne", "rint64-rne")
QUICK_SINGLE_ITEMS = ("sqrt32-rne", "rint32-rne")
QUICK_HOST_ITEMS = ("nextup32", "conv32to64-all", "rem32")
# What a host job must not see, whatever the environment the driver was started in: it names the card (and a tile of it)
HOST_JOB_DROPS = ("CFT_SOAK_ARTIFACT", "CFT_XRT_TILES")

BATTERY = ["api-test", "dt-i", "dt-q8", "dt-full", "dt-r", "dt-b", "card-segrun",
           "seq-check", "acceptance", "acceptance-rev8", "resident", "selftest"]
QUICK_BATTERY = ["api-test", "dt-i", "dt-q8", "dt-full", "dt-r", "dt-b", "card-segrun",
                 "seq-check", "acceptance", "acceptance-rev8"]
# Seconds. Sized from the card runs of 2026-10-06 (docs/VALIDATION.md): device-test's three
# matrices took about 2, 11-14 and 2 s; card-segrun 169-185 s; the acceptance set 371-384 s;
# the revision-8 set 353 s on the quad (images cached) and 77 s on the deep, and 57 s for the six
# routine entries (docs/CARDDAY.md, 2026-10-19), so 410 s for the quad's fifteen: 2400 s is 5.9
# times that (COMPUTED). A timeout is a
# several-times margin on those, with a floor, because a hang costs only its timeout and a
# false timeout costs a run (an abandoned run poisons the tile). api-test, dt-i, dt-b,
# seq-check, resident and selftest have no card figure in the records: BELIEVED, from their
# software times (seq-check 50-79 s) and VERIFICATION.md's card rows (selftest about 10 min
# an image, resident 20-40 s).
DEFAULT_TIMEOUTS = {"api-test": 300, "dt-i": 300, "dt-q8": 600, "dt-full": 900, "dt-r": 600,
                    "dt-b": 600, "card-segrun": 1500, "seq-check": 2400,
                    "acceptance": 2400, "acceptance-rev8": 2400, "resident": 600,
                    "selftest": 3600}
REV8_FIRST_COMPILE_ALLOWANCE = 4 * 3600   # added when a workload's cached image is missing (never for a routine entry)
DEFAULT_EVERY = {"selftest": 3}
# api-test opens no image (it may open device 0 for an instant and passes without a card), so
# its result neither ends nor extends the run of consecutive card failures.
NO_CARD_LEGS = ("api-test",)


class Skip:
    def __init__(self, reason: str):
        self.reason = reason


class Cmd:
    def __init__(self, argv: List[str], timeout: float, parser: Callable[[str, Optional[int]], L.Verdict],
                 env: Optional[Dict[str, str]] = None, tmpdir: bool = False,
                 post: Optional[Callable[[L.Verdict], None]] = None, card: bool = True):
        self.argv = argv
        self.timeout = timeout
        self.parser = parser
        self.env = env or {}
        self.tmpdir = tmpdir
        self.post = post
        self.card = card          # False for a host job: no card, so no log of it is "the card did not answer"


class WrongAnswer(Exception):
    """A leg that ran and parsed, whose content is wrong (a different image, tile count...)."""


class Stop(Exception):
    def __init__(self, reason: str, exit_code: int = 0, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.exit_code = exit_code
        self.detail = detail


class Image:
    def __init__(self, name: str, path: str, tiles: int, target: str, want_sha: Optional[str]):
        self.name = name
        self.path = path
        self.tiles = tiles
        self.target = target
        self.want_sha = want_sha
        self.sha = ""
        self.bytes = 0


class ProcResult:
    def __init__(self):
        self.rc: Optional[int] = None
        self.start = 0.0
        self.end = 0.0
        self.timed_out = False
        self.killed: Optional[str] = None
        self.error: Optional[str] = None


def sha256_file(path: str) -> Tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def kv_ints(text: str, what: str, names: Optional[List[str]] = None) -> Dict[str, int]:
    """'quad=4,single=1' -> {'quad': 4, ...}; refuses anything else by name."""
    out: Dict[str, int] = {}
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)=(\d+(?:\.\d+)?)", part)
        if not m:
            raise SystemExit(f"{what}: {part!r} is not NAME=NUMBER")
        if names is not None and m.group(1) not in names:
            raise SystemExit(f"{what}: {m.group(1)!r} is not one of {', '.join(names)}")
        v = float(m.group(2))
        out[m.group(1)] = int(v) if v == int(v) else v  # type: ignore[assignment]
    return out


def expand(path: str) -> str:
    return os.path.expandvars(os.path.expanduser(path))


# ---------------------------------------------------------------------------
# processes on this host, for the guard (never to signal: the guard only reads)
# ---------------------------------------------------------------------------

def list_processes() -> List[Dict[str, Any]]:
    """[{pid, ppid, args(list)}] from /proc, or ps, or (Windows) CIM. Best effort: a process
    that vanishes while it is read is skipped."""
    procs: List[Dict[str, Any]] = []
    if os.path.isdir("/proc/self"):
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open(f"/proc/{d}/cmdline", "rb") as fh:
                    args = [a.decode("utf-8", "replace") for a in fh.read().split(b"\0") if a]
                with open(f"/proc/{d}/stat", "r", errors="replace") as fh:
                    stat = fh.read()
                ppid = int(stat[stat.rindex(")") + 2:].split()[1])
            except (OSError, ValueError):
                continue
            if args:
                procs.append({"pid": int(d), "ppid": ppid, "args": args})
        return procs
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | ForEach-Object { '{0}|{1}|{2}' -f "
                 "$_.ProcessId, $_.ParentProcessId, $_.CommandLine }"],
                capture_output=True, text=True, timeout=60).stdout
        except (OSError, subprocess.TimeoutExpired):
            return procs
        for ln in out.splitlines():
            parts = ln.split("|", 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[2].strip():
                try:
                    args = shlex.split(parts[2], posix=False)
                except ValueError:
                    args = parts[2].split()
                procs.append({"pid": int(parts[0]), "ppid": int(parts[1] or 0), "args": args})
        return procs
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid=,args="], capture_output=True,
                             text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return procs
    for ln in out.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(.*)$", ln)
        if m:
            procs.append({"pid": int(m.group(1)), "ppid": int(m.group(2)),
                          "args": m.group(3).split()})
    return procs


def proc_environ(pid: int) -> Dict[str, str]:
    try:
        with open(f"/proc/{pid}/environ", "rb") as fh:
            parts = fh.read().split(b"\0")
    except OSError:
        return {}
    env: Dict[str, str] = {}
    for p in parts:
        if b"=" in p:
            k, v = p.split(b"=", 1)
            env[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
    return env


SOAK_TOOLS = ("divsqrt-soak", "clause5-soak", "divsqrt_soak", "clause5_soak")
DEVICE_FLAG_TOOLS = ("cft-segrun", "acceptance.py", "seq_check.py", "cft-audit")
# Programs that open an xclbin they are handed: an argument ending .xclbin makes the process
# a card user only when one of these is on its command line (a `cp`, `sha256sum` or editor
# naming an image does not hold the card).
# (hw/verify-image.sh is NOT here: it reads an xclbin with xclbinutil and never opens the card, and the
# gate's `images` stage runs it.)
XCLBIN_TOOLS = ("device-test", "run-device-test.sh", "card-segrun.sh", "card-identity.sh",
                "seq_check.py", "acceptance.py", "run-soak.sh",
                "run-c5-soak.sh") + SOAK_TOOLS
# The vendor tools' subcommands that touch the card (examine, which this driver itself
# uses for telemetry, does not).
XRT_TOOLS = ("xbutil", "xrt-smi", "xbmgmt")
XRT_ACTIVE = ("program", "reset", "validate", "advanced", "configure", "dump")


def card_user(p: Dict[str, Any]) -> Optional[str]:
    """Why this process uses the card, or None. A process uses it when an argument is an
    xclbin and it is one of the tools that open one (device-test, run-device-test.sh,
    card-segrun.sh, any cft-* tool, ...); when it is acceptance.py, seq_check.py or cft-segrun
    given a --device that is not sw, sw:N or a cft:// URL; when it is a soak with
    CFT_SOAK_ARTIFACT set; or when it is xbutil, xrt-smi or xbmgmt running a subcommand that
    programs, resets or tests the card."""
    args = p["args"]
    base = [os.path.basename(a) for a in args]
    names = [b[:-4] if b.endswith(".exe") else b for b in base]
    for a in args:
        if a.lower().endswith(".xclbin") and any(
                n in XCLBIN_TOOLS or n.startswith("cft-") for n in names):
            return f"an xclbin argument ({os.path.basename(a)})"
    if names and names[0] in XRT_TOOLS and any(x in XRT_ACTIVE for x in args[1:3]):
        return f"{names[0]} {' '.join(args[1:3])}"
    if any(b in DEVICE_FLAG_TOOLS or b.startswith("cft-segrun") for b in base):
        for i, a in enumerate(args):
            if a == "--device" and i + 1 < len(args):
                v = args[i + 1]
                if v != "sw" and not v.startswith("sw:") and not v.startswith("cft://"):
                    return f"--device {v}"
            elif a.startswith("--device=") and not a[9:].startswith(("sw", "cft://")):
                return a
    if any(b in SOAK_TOOLS or b.startswith(("divsqrt-soak", "clause5-soak")) for b in base):
        art = proc_environ(p["pid"]).get("CFT_SOAK_ARTIFACT")
        if art:
            return f"CFT_SOAK_ARTIFACT={os.path.basename(art)}"
    return None


def is_verify_run(p: Dict[str, Any]) -> bool:
    return any(a.replace("\\", "/").endswith("verify/run.sh") for a in p["args"])


def descendants_of(pid: int, procs: List[Dict[str, Any]]) -> set:
    kids: Dict[int, List[int]] = {}
    for p in procs:
        kids.setdefault(p["ppid"], []).append(p["pid"])
    seen = {pid}
    stack = [pid]
    while stack:
        for c in kids.get(stack.pop(), []):
            if c not in seen:
                seen.add(c)
                stack.append(c)
    return seen


def find_card_users(exclude_pids: Optional[set] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(foreign card users, verify/run.sh runs beside us). Our own process and everything we
    started are excluded by ancestry."""
    procs = list_processes()
    mine = descendants_of(os.getpid(), procs) | (exclude_pids or set())
    # our ancestors (a shell, the launcher) are not "another process" either
    anc = set()
    by_pid = {p["pid"]: p for p in procs}
    cur = os.getpid()
    while cur in by_pid and cur not in anc:
        anc.add(cur)
        cur = by_pid[cur]["ppid"]
    users, beside = [], []
    for p in procs:
        if p["pid"] in mine or p["pid"] in anc:
            continue
        if is_verify_run(p):
            beside.append({"pid": p["pid"], "args": " ".join(p["args"])[:200]})
            continue
        why = card_user(p)
        if why:
            users.append({"pid": p["pid"], "why": why, "args": " ".join(p["args"])[:200]})
    return users, beside


# ---------------------------------------------------------------------------
# --records: the canonical records of hw/sweep_record.py, written as the legs finish
# ---------------------------------------------------------------------------

RECORDS_FILE = "sweep-records.jsonl"       # in --out, beside metrics.jsonl
RECORD_EVENTS_MAX = 50                     # refusals named one by one; the rest are counted


class RecordsError(Exception):
    """--records cannot start: the message names why (a key refused by name, a file that is not this run's)."""


def records_device_key(text: str) -> bytes:
    """--device-key: a public key, 64 lowercase hex, a point of the curve not of small order - the form `sweep_record.py export
    --device-key` takes. Refused by name here, before anything starts."""
    import sweep_record as SR
    if not re.fullmatch(r"[0-9a-f]{64}", text or "") or SR.cert2.key_problem(text):
        raise RecordsError("--device-key is a public key: 64 lowercase hex, a point of the curve not of small order")
    return bytes.fromhex(text)


class RecordSink:
    """The driver's records, written the way `sweep_record.py export` writes them, a leg at a time. Every record the driver
    appends to metrics.jsonl is fed to it AFTER that append (Driver.rec); run_start, build and leg go to hw/sweep_record.py's
    Exporter (docs/SWEEP-RECORDS.md, "From the driver"), and the lines it returns - the campaign's, the first time an item is
    met, then the slice's - are appended to $OUT/sweep-records.jsonl in one write.

    A leg the exporter REFUSES (a Refusal, by name: it cannot be a version-1 record) is an `event` named record_refused in
    metrics.jsonl and driver.log, with the refusal's name and reason, and the run goes on: a record error never stops a long run.
    A run_start it refuses (a run id with no version-1 spelling) disables the sink with one event, `records_disabled`, and every
    leg after it is counted as not exported. A host-pool slice (image cpu) is not offered to it: version 1's subject is an image and
    the SHA-256 of its xclbin, which a CPU job has none of (the exporter would refuse each by name); they are counted, and said
    once, as `records_host_slices` - a limit of the format, which a later version can lift.
    With --sign-key the exporter signs; with --device-key it names the device and leaves the signing to `sweep_record.py sign`.
    The secret is held in the Signer for the run and is in no record, no setting and no log."""

    def __init__(self, path: str, key_path: Optional[str] = None, device_key: Optional[str] = None,
                 emit: Optional[Callable[..., None]] = None):
        import sweep_record as SR
        self.SR = SR
        self.path = path
        self.emit = emit or (lambda name, detail, **kw: None)
        self.lock = threading.Lock()
        if key_path:
            try:
                self.ex = SR.Exporter(signer=SR.Signer(SR.load_seed(key_path)))
            except SR.Refusal as e:
                raise RecordsError(f"--sign-key {key_path}: refused {e.name}: {e.why}")
        elif device_key:
            self.ex = SR.Exporter(public=records_device_key(device_key))
        else:
            raise RecordsError("--records needs a device: --sign-key KEYFILE (signs the records) or --device-key HEX "
                               "(unsigned, for `sweep_record.py sign` later): version 1 puts the device in every record")
        self.signed = key_path is not None
        self.written = 0                   # slice and stream records
        self.campaigns = 0
        self.refused: Dict[str, int] = {}
        self.host_slices = 0
        self.disabled: Optional[str] = None
        self.n_events = 0

    def adopt(self, resumed_run_id: Optional[str]) -> List[str]:
        """On --resume: the file left by the run's earlier part must be this run's and this device's, and its campaigns are
        known (so none is written twice); a torn last line (a write cut short) is cut back to the last whole line. Returns notes
        for the driver to say. A file that is not this run's, or this key's, is refused by name: appending to it would make a file
        `verify` refuses as a splice."""
        notes: List[str] = []
        if not os.path.exists(self.path):
            return notes
        with open(self.path, "rb") as fh:
            data = fh.read()
        if data and not data.endswith(b"\n"):
            cut = data.rfind(b"\n") + 1
            with open(self.path, "r+b") as fh:
                fh.truncate(cut)
            notes.append(f"the last line of {os.path.basename(self.path)} was torn ({len(data) - cut} bytes): cut back to its last whole record")
            data = data[:cut]
        if not data:
            return notes
        try:
            recs = self.SR.parse_file(data)
        except self.SR.Refusal as e:
            raise RecordsError(f"{self.path} cannot be continued: refused {e.name}: {e.why}")
        for _n, r in recs:
            if r["kind"] == "campaign":
                self.ex.seen.add(r["id"])
                self.campaigns += 1
            else:
                self.written += 1
                if r["run"]["device"] != self.ex.device:
                    raise RecordsError(f"{self.path} holds records of device {r['run']['device']}; this run's key makes device "
                                       f"{self.ex.device} - a resumed run takes the key it started with")
                if resumed_run_id is not None and r["run"]["id"] != resumed_run_id:
                    raise RecordsError(f"{self.path} holds records of run {r['run']['id']}, not {resumed_run_id}")
        notes.append(f"continuing {os.path.basename(self.path)}: {self.written} record(s) and {self.campaigns} campaign(s) already in it")
        return notes

    def feed(self, rec: Dict[str, Any]) -> None:
        typ = rec.get("type")
        if typ not in ("run_start", "build", "leg"):
            return
        events: List[Tuple[str, str]] = []
        with self.lock:
            try:
                if typ == "run_start":
                    self.disabled = None
                    self.ex.run_start(rec)
                elif typ == "build":
                    self.ex.build(rec)
                elif rec.get("kind") == "sweep":
                    if rec.get("image") == L.CPU:
                        if rec.get("status") in ("pass", "fail"):
                            self.host_slices += 1
                            if self.host_slices == 1:
                                events.append(("records_host_slices", "a host-pool slice (image cpu) finished: version 1's record has "
                                               "an image and its xclbin's SHA-256, which a CPU job has none of, so the host items' "
                                               "slices are not in sweep-records.jsonl (metrics.jsonl has them); counted, said once"))
                    elif self.disabled is not None:
                        if rec.get("status") in ("pass", "fail"):
                            self.refused["disabled"] = self.refused.get("disabled", 0) + 1
                    else:
                        lines = self.ex.leg(rec)
                        if lines:
                            fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
                            try:
                                os.write(fd, b"".join(lines))
                                os.fsync(fd)
                            finally:
                                os.close(fd)
                            self.written += 1
                            self.campaigns += len(lines) - 1
            except self.SR.Refusal as e:
                if typ == "run_start":
                    self.disabled = f"{e.name}: {e.why}"[:300]
                    events.append(("records_disabled", f"the exporter refused this run ({self.disabled}): no sweep slice of it "
                                   f"is exported; the run goes on"))
                else:
                    self.refused[e.name] = self.refused.get(e.name, 0) + 1
                    self.n_events += 1
                    if self.n_events <= RECORD_EVENTS_MAX:
                        events.append(("record_refused", f"{e.name}: {e.why}"[:600]))
                    elif self.n_events == RECORD_EVENTS_MAX + 1:
                        events.append(("record_refused", f"more than {RECORD_EVENTS_MAX} legs refused: the rest are counted, not "
                                       f"named one by one (the summary at the end has the counts)"))
        for name, detail in events:           # after the lock: an event is a record, and comes back through feed()
            self.emit(name, detail)

    def summary(self) -> str:
        left = dict(self.ex.left)
        return (f"{self.written} record(s) and {self.campaigns} campaign(s) in {os.path.basename(self.path)} "
                f"({'signed by key ' + self.ex.public.hex() if self.signed else 'UNSIGNED, for key ' + self.ex.public.hex()}, "
                f"device {self.ex.device}); {self.ex.findings} finding(s); refused: {self.refused or 'none'}; "
                f"slices not finished: {left or 'none'}; host-pool slices not in it: {self.host_slices}")


# ---------------------------------------------------------------------------
# the driver
# ---------------------------------------------------------------------------

class Driver:
    def __init__(self, a: argparse.Namespace):
        self.a = a
        self.root = os.path.abspath(a.root)
        self.dry = a.dry_run
        self.tree_check = (not a.dry_run) or bool(getattr(a, "check_tree_in_dry_run", False))   # the tree test of should_stop
        self.tree_stop: Optional[Stop] = None      # a moved tree, once anyone (the main loop or a pool worker) has seen it
        self.quick = a.quick
        self.out = os.path.abspath(a.out)
        self.metrics = os.path.join(self.out, "metrics.jsonl")
        self.status_path = os.path.join(self.out, "status.txt")
        self.stop_path = os.path.join(self.out, "STOP")
        self.logs = os.path.join(self.out, "logs")
        self.tmp = os.path.join(self.out, "tmp")
        self.lock = threading.Lock()
        self.children: Dict[int, subprocess.Popen] = {}
        self.sig: Optional[str] = None
        self.hard = False
        self.seq = 0                       # leg counter, names the logs
        self.cycle = 0
        self.t0 = time.time()
        self.deadline = L.parse_when(a.until) if a.until else None
        self.images: Dict[str, Image] = {}
        self.streak = 0                    # consecutive card failures (the policy's N)
        self.counts: Dict[str, int] = {}   # leg statuses, for status.txt
        self.by_image: Dict[str, Dict[str, int]] = {}
        self.last_tel: Optional[Dict[str, Any]] = None
        self.tel_json: Dict[str, bool] = {}   # per report: False once JSON gave nothing and text did
        self.tel_worked: Dict[str, str] = {}  # per report: the tool that last gave values
        self.tel_stop = threading.Event()
        self.tel_lock = threading.Lock()      # one sample at a time, from the examine calls to the append
        self.tel_thread: Optional[threading.Thread] = None
        self.state = "STARTING"
        self.current = ""
        self.beside: List[Dict[str, Any]] = []
        self.beside_seen: set = set()
        self.internal_errors = 0
        # A sweep item whose slices keep failing to give a readable verdict (parse_error, error) is not the
        # card's fault and would otherwise starve every other item: it never counts as served, so it stays
        # the least served and is picked again at once, every wave. After more than --quarantine-after in a
        # row it is disabled for the rest of the run (and, rebuilt from the records, after a resume).
        self.item_bad: Dict[str, int] = {}
        self.disabled_items: Dict[str, str] = {}
        self.torn_note = ""
        self.disabled_legs: Dict[str, str] = {}   # a leg its tool's build check ruled out, and why
        self.head = ""
        self.started = False               # run_start written: only then does metrics.jsonl exist
        self.tree: Dict[str, Any] = {}
        self.python = a.python
        self.items: List[L.Item] = []
        self.intervals: Dict[str, List[Tuple[int, int]]] = {}
        self.served: Dict[str, int] = {}
        self.seed_n: Dict[str, int] = {}
        self.seed_states: Dict[Any, Tuple[str, int]] = {}   # stream (L.stream_key: the tool state seed | 1, plus the batch for a cvtfrom item) -> (item, n), this file and --earlier-runs
        self.seed_floor: Dict[str, int] = {}                # the first n --earlier-runs leaves each item
        # --sweep-chunk N: the sweep's slices (the card's and the pool's) run the tools built at pass size N; the battery's legs
        # keep the default tools. None: the default tools, and nothing below changes.
        self.chunk: Optional[int] = getattr(a, "sweep_chunk", None) or None
        self.batch = self.chunk or L.DEFAULT_BATCH          # the BATCH a sweep slice's tool will say it ran at
        # cases and skipped slots of each item's completed slices, to hold a wholly covered item to its whole-space figures
        self.sums: Dict[str, List[int]] = {}
        self.whole_done: set = set()
        self.sink: Optional["RecordSink"] = None            # --records: the canonical records, written as the legs finish
        self.earlier_notes: List[Dict[str, Any]] = []
        self.prev_rtl: Optional[str] = None                 # the RTL tree the last run_start of a resumed file recorded
        self.build_id: Optional[str] = None                 # the tools' build id, once the build step has asserted it
        self.quarantine: Dict[str, List[Tuple[int, int]]] = {}
        self.fail_slices: Dict[Tuple[str, int, int], int] = {}
        # The host pool (below): threads of this process, one soak process each, on the `cpu` pseudo-image. The sweep's
        # state above (served, intervals, seed_n, item_bad, disabled_items, fail_slices, quarantine, rate) is shared by
        # the card's sweep, which only touches TILE items, and the pool, which only touches HOST ones; pool_lock (re-entrant)
        # guards every change to it. NEVER call say(), event() or write_status() while holding pool_lock: write_status
        # holds `lock` and takes pool_lock inside it, so the other order would deadlock.
        self.cpu = Image(L.CPU, "", 0, "", None)
        self.pool_lock = threading.RLock()
        self.tally_lock = threading.Lock()
        self.pool_stop = threading.Event()
        self.pool_threads: List[threading.Thread] = []
        self.pool_busy: Dict[str, Dict[str, Any]] = {}      # item name -> {"job", "proc", "abandon"}: slices in flight
        self.pool_queue: Optional[List[str]] = None         # --quick: the host items still owed their one slice
        self.pool_note = "not started"
        self.pool_served = 0
        self.rate: Dict[str, float] = {}   # units per second, by "op@image"
        self.visits: Dict[str, int] = {}
        self.picked = 0
        self.disagreements = 0
        self.last_record_cycle = 0
        self.timeouts = dict(DEFAULT_TIMEOUTS)
        self.timeouts.update(kv_ints(a.timeout, "--timeout"))
        self.every = dict(DEFAULT_EVERY)
        self.every.update(kv_ints(a.every, "--every"))
        self.weights = kv_ints(a.weights, "--weights", list(IMAGES))
        self.sweep_minutes = kv_ints(a.sweep_minutes, "--sweep-minutes", list(IMAGES))
        self.sweep_weights = kv_ints(a.sweep_weights, "--sweep-weights", ["exhaustive", "random"])
        self.battery = [x for x in (a.legs.split(",") if a.legs else
                                    (QUICK_BATTERY if self.quick else BATTERY)) if x]
        for leg in self.battery:
            if leg not in BATTERY:
                raise SystemExit(f"--legs: {leg!r} is not one of {', '.join(BATTERY)}")
        self.sweep_only = [x for x in a.sweep_items.split(",") if x]
        self.rev8_images = expand(a.rev8_images) if a.rev8_images else os.path.join(self.out, "rev8-images")

    # -- small things -------------------------------------------------------
    def say(self, msg: str) -> None:
        line = f"[{L.iso(time.time())}] {msg}"
        with self.lock:
            try:
                print(line, flush=True)
            except (OSError, ValueError):
                pass                       # a closed terminal must not end a 60-hour run
            try:
                with open(os.path.join(self.out, "driver.log"), "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                pass

    def rec(self, rec: Dict[str, Any]) -> None:
        L.append_record(self.metrics, rec)
        if self.sink is not None:
            self.sink.feed(rec)       # AFTER the append: a record the exporter refuses is in metrics.jsonl all the same

    def event(self, name: str, detail: str = "", **kw: Any) -> None:
        self.say(f"event {name}: {detail}")
        if self.started:
            self.rec({"type": "event", "event": name, "detail": detail, **kw})

    def card_paths(self) -> List[str]:
        paths = [self.out]
        if self.a.disk_extra and os.path.isdir(self.a.disk_extra):
            paths.append(self.a.disk_extra)
        return paths

    # -- the rotation of images --------------------------------------------
    def next_image(self) -> Image:
        if self.quick:
            order = [n for n in ("quad", "single", "deep") if n in self.images]
            return self.images[order[self.picked % len(order)]]
        name = L.smooth_wrr({k: self.weights.get(k, 1) for k in self.images}, self.picked + 1)[-1]
        return self.images[name]

    # -- stop conditions: all checked BETWEEN legs ----------------------------
    def should_stop(self, git: bool = True) -> Optional[Stop]:
        """Why the run is to end, or None: the STOP file, a signal, the deadline, the disk floor and, with git, HEAD against
        the commit the tools were built from (a real run; a --dry-run only with --check-tree-in-dry-run). The main loop asks
        between legs, waves and cycles, and every host-pool worker asks, tree test included, before it plans each slice: one
        `git rev-parse HEAD` a slice (20 ms, MEASURED on Windows; a slice lasts from a fraction of a second, the first probe
        of an op, to --sweep-slice-seconds). A moved tree is LATCHED: once anyone has seen it every later call says so without
        asking git, so no worker plans another slice, and the main loop ends the run as `tree_moved` at its next check, as it
        always did. A slice a worker had planned in the same few milliseconds still starts, and a slice in flight runs on,
        as a card leg in flight does. git=False skips the tree test: the pool's workers asked that way until the second pass
        of 2026-10-20 (verifier-VDR2), and a plant of the suite puts it back."""
        if os.path.exists(self.stop_path):
            return Stop("stop_file", 0, f"{self.stop_path} exists")
        if self.sig:
            return Stop("signal", 0, f"{self.sig} received")
        if self.deadline is not None and time.time() >= self.deadline:
            return Stop("deadline", 0, f"{L.iso(self.deadline)} reached")
        low = []
        for p in self.card_paths():
            try:
                free = shutil.disk_usage(p).free / 1e9
            except OSError:
                continue
            if free < self.a.disk_floor_gb:
                low.append(f"{p}: {free:.2f} GB free, floor {self.a.disk_floor_gb} GB")
        if low:
            return Stop("disk_floor", 3, "; ".join(low))
        if git and self.head and self.tree_check:
            if self.tree_stop is None:
                now = self.git_head()
                if now and now != self.head:
                    self.tree_stop = Stop("tree_moved", 3, f"HEAD was {self.head[:12]} at the start and is "
                                          f"{now[:12]} now: the tools were built from the first")
            if self.tree_stop is not None:
                return self.tree_stop
        return None

    def git_head(self) -> str:
        try:
            return subprocess.run(["git", "-C", self.root, "rev-parse", "HEAD"], capture_output=True,
                                  text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            return ""

    def estimate(self, leg: str) -> float:
        return float(self.timeouts.get(leg, 600)) / 3.0

    # -- the guard ---------------------------------------------------------
    def guard(self, waiting_ok: bool) -> None:
        """Refuse (at the start) or wait (between legs) while another process uses the card.
        Detects, never kills."""
        t_start = time.time()
        announced = False
        while True:
            users, beside = find_card_users()
            self.beside = beside
            self.note_beside()
            if not users:
                if announced:
                    self.event("guard_clear", f"the card is free after {time.time() - t_start:.0f} s")
                return
            desc = "; ".join(f"pid {u['pid']} {u['why']}" for u in users)
            if not waiting_ok:
                self.event("guard_refused", desc, users=users)
                raise Stop("guard_refused", 2, desc)
            if not announced:
                self.event("guard_wait", desc, users=users)
                announced = True
            if time.time() - t_start > self.a.guard_wait_max:
                raise Stop("guard_timeout", 3, f"still in use after {self.a.guard_wait_max:.0f} s: {desc}")
            if os.path.exists(self.stop_path) or self.sig:
                raise Stop("stop_file" if not self.sig else "signal", 0, "stopped while waiting for the card")
            time.sleep(min(self.a.guard_poll, 30))

    def note_beside(self) -> None:
        """verify/run.sh uses no card: allowed, and recorded once a run. (A run seen at the start
        is recorded as soon as run_start is written, since nothing is before it.)"""
        if not self.started:
            return
        fresh = [b for b in self.beside if b["pid"] not in self.beside_seen]
        if fresh:
            self.beside_seen.update(b["pid"] for b in fresh)
            self.event("beside", "verify/run.sh running beside this run (it uses no card): "
                       + "; ".join(f"pid {b['pid']} {b['args'][:80]}" for b in fresh), runs=fresh)

    # -- running one process --------------------------------------------------
    def wrap(self, argv: List[str], timeout_s: float) -> List[str]:
        cmd = list(argv)
        if POSIX:
            if shutil.which("timeout"):
                cmd = ["timeout", "--signal=TERM", "-k", str(int(self.a.kill_after)),
                       str(int(max(1, round(timeout_s)))) + "s"] + cmd
            if self.a.nice and shutil.which("nice"):
                cmd = ["nice", "-n", str(self.a.nice)] + cmd
        return cmd

    def spawn(self, argv: List[str], env_extra: Dict[str, str], logpath: str, cwd: str,
              timeout_s: float, drop: Tuple[str, ...] = ()) -> "Tuple[subprocess.Popen, Any, List[str]]":
        """drop: variables REMOVED from the child's environment, after the driver's own are copied in - a host
        job is started with HOST_JOB_DROPS, so a CFT_SOAK_ARTIFACT in the environment the driver itself was started
        in cannot reach it and open the card."""
        env = dict(os.environ)
        for k in drop:
            env.pop(k, None)
        env.update(env_extra)
        env.setdefault("PYTHONUNBUFFERED", "1")
        cmd = self.wrap(argv, timeout_s)
        logf = open(logpath, "wb")
        kw: Dict[str, Any] = {}
        if POSIX:
            kw["start_new_session"] = True
        elif hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                env=env, cwd=cwd, **kw)
        self.children[proc.pid] = proc
        return proc, logf, cmd

    def kill_group(self, proc: subprocess.Popen, sig: str) -> None:
        """Signal the process group WE started (its leader is our child), by PID."""
        try:
            if POSIX:
                os.killpg(proc.pid, signal.SIGTERM if sig == "TERM" else signal.SIGKILL)
            elif sig == "TERM":
                proc.terminate()
            else:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                               capture_output=True, timeout=30)
                proc.kill()
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def await_proc(self, proc: subprocess.Popen, timeout_s: float, res: ProcResult) -> None:
        """Wait for the process; at the timeout, TERM then (after --kill-after) KILL. On POSIX
        the `timeout` wrapper does this itself and the Python-side deadline is only a backstop
        a little later, for a wrapper that has died."""
        limit = timeout_s + (self.a.kill_after + 30 if (POSIX and shutil.which("timeout")) else 0)
        deadline = time.time() + limit
        termed_at: Optional[float] = None
        while True:
            try:
                res.rc = proc.wait(timeout=2)
                break
            except subprocess.TimeoutExpired:
                pass
            now = time.time()
            if self.hard and termed_at is None:
                self.kill_group(proc, "TERM")
                termed_at = now
                res.killed = "TERM"
                res.timed_out = True
            if now >= deadline and termed_at is None:
                res.timed_out = True
                res.killed = "TERM"
                self.kill_group(proc, "TERM")
                termed_at = now
            elif termed_at is not None and now - termed_at >= self.a.kill_after:
                self.kill_group(proc, "KILL")
                res.killed = "KILL"
                termed_at = now + 3600       # once
            self.heartbeat()
        if POSIX and res.rc == 124:
            res.timed_out = True
            res.killed = res.killed or "TERM"
        elif POSIX and res.rc in (137, -9) and res.timed_out is False:
            # killed by SIGKILL: -9 to Popen (137 to a shell) - by `timeout --kill-after`, whose
            # own process goes with the group when a leg ignored SIGTERM, measured in WSL
            # (coreutils 8.32); or from outside. Either way the leg did not finish.
            res.timed_out = True
            res.killed = "KILL"
        self.children.pop(proc.pid, None)

    def heartbeat(self) -> None:
        now = time.time()
        if now - getattr(self, "_hb", 0) >= 60:
            self._hb = now
            self.write_status()

    # -- one leg ------------------------------------------------------------
    def log_name(self, leg: str) -> Tuple[str, str]:
        with self.tally_lock:                 # the pool's workers name logs too
            self.seq += 1
            seq = self.seq
        base = f"c{self.cycle:04d}-{seq:05d}-{leg}"
        return base, os.path.join(self.logs, base + ".log")

    def run_leg(self, leg: str, img: Image, cmd: Cmd, kind: str = "battery", attempt: int = 1,
                sweep: Optional[Dict[str, Any]] = None, tile: Optional[int] = None,
                expected_cases: Optional[int] = None) -> Dict[str, Any]:
        """Run one command to its end, parse it, record it, return the record."""
        base, logpath = self.log_name(leg)
        tmpdir = None
        env = dict(cmd.env)
        if cmd.tmpdir:
            tmpdir = os.path.join(self.tmp, base)
            os.makedirs(tmpdir, exist_ok=True)
            env["TMPDIR"] = tmpdir
        self.current = f"{leg} on {img.name} (cycle {self.cycle}, attempt {attempt})"
        self.say(f"leg {leg} on {img.name} starts: {shlex.join(cmd.argv)[:300]}")
        res = ProcResult()
        res.start = time.time()
        try:
            proc, logf, full = self.spawn(cmd.argv, env, logpath, self.root, cmd.timeout)
        except OSError as e:
            res.end = time.time()
            res.error = f"could not start {cmd.argv[0]}: {e}"
            return self.finish_leg(leg, img, kind, attempt, sweep, tile, res, None, base, logpath,
                                   tmpdir, cmd, expected_cases)
        try:
            self.await_proc(proc, cmd.timeout, res)
        finally:
            logf.close()
            res.end = time.time()
        return self.finish_leg(leg, img, kind, attempt, sweep, tile, res, None, base, logpath,
                               tmpdir, cmd, expected_cases)

    def classify(self, res: ProcResult, text: str, cmd: Cmd) -> Tuple[str, Optional[L.Verdict], str]:
        """(status, verdict, reason)."""
        if res.error:
            return "error", None, res.error
        if res.timed_out:
            return ("timeout", None, f"no verdict within {cmd.timeout:.0f} s; "
                    f"signalled {res.killed or 'TERM'}")
        try:
            v = cmd.parser(text, res.rc)
            if cmd.post:
                cmd.post(v)
        except WrongAnswer as e:
            return "fail", None, str(e)
        except L.VerdictError as e:
            # a log that is not a verdict is "the card did not answer" only for a job that uses the card
            infra = L.classify_infra(text) if cmd.card else None
            if infra:
                return "no_device", None, f"{infra}: {e}"
            return "parse_error", None, f"{e} (exit status {res.rc})"
        return ("pass" if v.ok else "fail"), v, ""

    def finish_leg(self, leg, img, kind, attempt, sweep, tile, res, _unused, base, logpath, tmpdir,
                   cmd, expected_cases) -> Dict[str, Any]:
        try:
            with open(logpath, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            text = ""
        status, v, reason = self.classify(res, text, cmd)
        dur = max(0.0, res.end - res.start)
        counts = dict(v.counts) if v else None
        extra = dict(v.extra) if v else {}
        disagreements = extra.pop("disagreements", None) if v else None
        if sweep is not None and v is not None:
            # the pass size the tool said it ran at, read from its own stderr line and held to the request by the parser
            # (L.parse_soak, chunk=): the slice's record carries it, the batch its flags were compared over (CK's finding iii)
            for k in ("batch", "chunk"):
                if k in extra:
                    sweep[k] = extra.pop(k)
        if v is None and sweep is not None:
            # a slice that did not finish still shows what the tool printed, if anything
            disagreements = None
        rate = None
        if counts:
            for key, unit in (("cases", "cases/s"), ("checks", "checks/s")):
                if key in counts and dur > 0:
                    rate = {"value": round(counts[key] / dur, 3), "unit": unit}
                    break
        kept = self.keep_log(logpath, status, tmpdir, extra)
        rec: Dict[str, Any] = {
            "type": "leg", "cycle": self.cycle, "image": img.name, "image_sha256": img.sha or None,
            "leg": leg, "kind": kind, "attempt": attempt,
            "start": L.iso(res.start), "end": L.iso(res.end),
            "start_epoch": round(res.start, 3), "end_epoch": round(res.end, 3),
            "duration_s": round(dur, 3), "rc": res.rc, "status": status,
            "timed_out": bool(res.timed_out), "killed": res.killed, "counts": counts,
            "rate": rate, "sweep": sweep, "disagreements": disagreements,
            "log": os.path.relpath(kept[0], self.out).replace("\\", "/") if kept[0] else None,
            "log_kept": kept[1], "reason": reason or None, "tile": tile,
            "extra": extra or None, "argv": cmd.argv[:12] if status != "pass" else None,
        }
        if v and v.notes:
            rec["notes"] = v.notes
        self.rec(rec)
        self.tally(img.name, status)
        self.say(f"leg {leg} on {img.name}: {status} in {dur:.1f} s"
                 + (f" ({reason})" if reason else "") + (f" {counts}" if counts else ""))
        if cmd.card:
            self.current = ""             # what the card is doing now; a host job ending says nothing of it
        self.write_status()
        return rec

    def keep_log(self, logpath: str, status: str, tmpdir: Optional[str],
                 extra: Dict[str, Any]) -> Tuple[Optional[str], str]:
        """A passing leg's log is gzipped (--keep-pass-logs gz), or cut to its last lines
        (verdict) or dropped (none); anything else's is kept whole."""
        kept: Tuple[Optional[str], str] = (logpath, "whole")
        try:
            if status == "pass":
                mode = self.a.keep_pass_logs
                if mode == "gz":
                    gz = logpath + ".gz"
                    with open(logpath, "rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                        shutil.copyfileobj(src, dst)
                    os.remove(logpath)
                    kept = (gz, "gz")
                elif mode == "verdict":
                    with open(logpath, "r", encoding="utf-8", errors="replace") as fh:
                        lines = fh.read().splitlines()
                    with open(logpath, "w", encoding="utf-8") as fh:
                        fh.write("\n".join(lines[:5] + ["..."] + lines[-25:]) + "\n")
                    kept = (logpath, "whole")
                elif mode == "none":
                    os.remove(logpath)
                    kept = (None, "none")
            kd = extra.get("kept_dir")
            if kd and os.path.isdir(kd):
                dest = logpath[:-4] + "-kept"
                shutil.move(kd, dest)
                extra["kept_dir"] = os.path.relpath(dest, self.out).replace("\\", "/")
        except OSError as e:
            self.say(f"could not tidy {logpath}: {e}")
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)
        return kept

    def tally(self, image: str, status: str) -> None:
        with self.tally_lock:                 # the card's thread and the pool's workers all count
            self.counts[status] = self.counts.get(status, 0) + 1
            d = self.by_image.setdefault(image, {})
            d[status] = d.get(status, 0) + 1

    def skipped(self, leg: str, img: Image, reason: str, kind: str = "battery") -> None:
        now = time.time()
        self.rec({"type": "leg", "cycle": self.cycle, "image": img.name, "image_sha256": img.sha,
                  "leg": leg, "kind": kind, "attempt": 1, "start": L.iso(now), "end": L.iso(now),
                  "start_epoch": round(now, 3), "end_epoch": round(now, 3), "duration_s": 0.0,
                  "rc": None, "status": "skipped", "timed_out": False, "killed": None,
                  "counts": None, "rate": None, "sweep": None, "disagreements": None,
                  "log": None, "log_kept": "none", "reason": reason, "tile": None, "extra": None})
        self.tally(img.name, "skipped")
        self.say(f"leg {leg} on {img.name}: SKIPPED ({reason})")

    # -- the legs' commands ---------------------------------------------------
    def standin(self, leg: str, real: List[str]) -> List[str]:
        return [sys.executable, os.path.join(HERE, "card_stress_standin.py"), leg, "--"] + real

    def leg_cmd(self, leg: str, img: Image, visit: int) -> "Cmd | Skip":
        R = self.root
        x = img.path
        T = float(self.timeouts[leg])
        if leg in self.disabled_legs:
            return Skip(self.disabled_legs[leg])
        every = int(self.every.get(leg, 1))
        if every > 1 and (visit - 1) % every != 0:
            return Skip(f"every {every} visits of an image; this is visit {visit}")
        py = self.python
        dt = ["bash", os.path.join(R, "hw", "run-device-test.sh"), x]

        def wrap(real: List[str]) -> List[str]:
            return self.standin(leg, real) if self.dry else real

        def dtp(mode: str):
            return lambda t, rc: L.parse_device_test(t, rc, mode)

        if leg == "api-test":
            return Cmd(wrap([os.path.join(R, "host", "api-test")]), T, L.parse_api_test)
        if leg == "dt-i":
            def post(v: L.Verdict, img=img) -> None:
                e = v.extra
                if e.get("image_sha256") != img.sha:
                    raise WrongAnswer(f"device-test -i read the image as sha256 {e.get('image_sha256')}"
                                      f"; the file hashes to {img.sha}")
                if e.get("tiles") != img.tiles:
                    raise WrongAnswer(f"device-test -i read {e.get('tiles')} tiles; {img.name} has {img.tiles}")
                if e.get("backend") != "xrt":
                    raise WrongAnswer(f"device-test -i opened backend {e.get('backend')!r}, not xrt")
            return Cmd(wrap(dt + ["-i"]), T, dtp("i"), post=post)
        if leg == "dt-q8":
            return Cmd(wrap(dt + ["-q", "-n", "8"]), T, dtp("q8"))
        if leg == "dt-full":
            return Cmd(wrap(dt + ["-n", "4096"]), T, dtp("full"))
        if leg == "dt-r":
            return Cmd(wrap(dt + ["-r"]), T, dtp("r"))
        if leg == "dt-b":
            return Cmd(wrap(dt + ["-b", "-n", "4096"]), T, dtp("b"))
        if leg == "card-segrun":
            return Cmd(wrap(["bash", os.path.join(R, "hw", "card-segrun.sh"), x]), T,
                       L.parse_card_segrun, tmpdir=True)
        if leg == "seq-check":
            argv = [py, os.path.join(R, "host", "tests", "seq_check.py"), "--trials", str(self.a.seq_trials),
                    "--formats", "fp32", "fp64", "fp128", "fp256", "--device", x]
            return Cmd(wrap(argv), T, lambda t, rc: L.parse_seq_check(t, rc, x))
        if leg == "acceptance":
            argv = [py, os.path.join(R, "programs", "acceptance.py"), "--device", x]
            if self.quick:
                argv += ["--only", QUICK_ACCEPT_ONLY]
            return Cmd(wrap(argv), T, lambda t, rc: L.parse_acceptance(t, rc, device=x), tmpdir=True)
        if leg == "acceptance-rev8":
            entries = REV8_ENTRIES.get(img.target, [])
            if not entries:
                return Skip(f"the revision-8 set has no entry for {img.target}: its rule puts a workload "
                            f"on the single only where R21 alone keeps it off the quad, which none does "
                            f"(programs/acceptance.py, REV8)")
            chosen, left_out = [], []
            for e in entries:
                cached = all(os.path.isfile(os.path.join(self.rev8_images, e + ext)) for ext in (".cftp", ".bank"))
                if e in REV8_LONG_COMPILES and not cached:
                    left_out.append(e)
                else:
                    chosen.append(e)
            if self.quick:
                q = QUICK_REV8_ONLY.get(img.target)
                if q is None or q not in chosen:
                    return Skip(f"--quick: {q} compiles in 40 minutes or more and no cached image is in "
                                f"{self.rev8_images}; seed it (--rev8-images) to run it")
                chosen = [q] + [r for r in [QUICK_REV8_ROUTINE.get(img.target)] if r in chosen]
            if not chosen:
                return Skip(f"every {img.target} entry is a 40-minute-or-longer compile with no cached image "
                            f"in {self.rev8_images}: {', '.join(left_out)}")
            os.makedirs(self.rev8_images, exist_ok=True)
            # a routine entry reads committed files and has nothing to compile or to cache: never "missing"
            # (counted so, it would add the 4-hour compile allowance to every quad leg for ever)
            missing = [e for e in chosen if e not in REV8_ROUTINE_ENTRIES
                       and not all(os.path.isfile(os.path.join(self.rev8_images, e + ext)) for ext in (".cftp", ".bank"))]
            t = T + (REV8_FIRST_COMPILE_ALLOWANCE if missing else 0)
            argv = [py, os.path.join(R, "programs", "acceptance.py"), "--set", "rev8", "--legs", "set",
                    "--device", x, "--target", img.target, "--images", self.rev8_images,
                    "--only", ",".join(chosen)]
            if any(e in REV8_ROUTINE_ENTRIES for e in chosen):
                # the routine entries read each segment's per-lane block through libcft by ctypes (acceptance.py
                # --lib, whose default is $CFT_LIB first): this tree's library, the XRT-linked one build_tools
                # checked with ldd, not whatever the environment names
                argv += ["--lib", os.path.join(R, "host", "libcft.so")]
            return Cmd(wrap(argv), t, lambda tx, rc: L.parse_acceptance(tx, rc, device=x, rev8=True,
                                                                         target=img.target), tmpdir=True)
        if leg == "resident":
            return Cmd(wrap([os.path.join(R, "host", "cft-resident"), x]), T, L.parse_resident)
        if leg == "selftest":
            return Cmd(wrap([os.path.join(R, "host", "cft-selftest"), os.path.join(R, "vectors", "out"), x]),
                       T, L.parse_selftest)
        raise SystemExit(f"internal: no command for leg {leg}")

    # -- the failure policy ----------------------------------------------------
    def other_image(self, img: Image) -> Optional[Image]:
        """Another image, of another xclbin, for the reload: the one the rotation visits most
        after this one (the quad when this is not it)."""
        order = sorted((i for i in self.images.values() if i.sha != img.sha),
                       key=lambda i: -self.weights.get(i.name, 1))
        return order[0] if order else None

    def recover(self, img: Image, streak: int) -> None:
        """Pause; from the second consecutive failure, load another image and come back."""
        pause = self.a.retry_pause * (1 if streak <= 1 else streak)
        self.event("pause", f"card not answering (consecutive failure {streak}); waiting {pause:.0f} s",
                   streak=streak)
        self.sleep_interruptible(pause)
        if streak >= 2:
            other = self.other_image(img)
            if other is None:
                self.event("recover_start", "no other image to open; retrying this one only")
                return
            self.event("recover_start", f"open {other.name}, then {img.name} again", streak=streak)
            self.event("image_switch", f"{img.name} -> {other.name} -> {img.name}")
            for step in (other, img):
                cmd = self.leg_cmd("dt-i", step, 1)
                assert isinstance(cmd, Cmd)
                r = self.run_leg("dt-i", step, cmd, kind="recovery")
                if r["status"] in ("timeout", "no_device"):
                    self.streak += 1
                    self.event("recover_end", f"{step.name} dt-i: {r['status']}", ok=False)
                    return
            self.event("recover_end", f"{img.name} answers again (dt-i passed)", ok=True)

    def sleep_interruptible(self, secs: float) -> None:
        end = time.time() + secs
        while time.time() < end:
            if self.hard:
                return
            time.sleep(min(1.0, max(0.0, end - time.time())))

    def after_result(self, rec: Dict[str, Any]) -> None:
        """The streak of consecutive card failures: a leg that ran to a verdict on the card ends
        it; a timeout or a no-device open adds one; the Nth stops the run."""
        st = rec["status"]
        if rec["leg"] in NO_CARD_LEGS:
            return
        if st in ("pass", "fail"):
            self.streak = 0
        elif st in ("timeout", "no_device"):
            self.streak += 1
            if self.streak >= self.a.max_card_failures:
                raise Stop("card_lost", 3, f"{self.streak} consecutive failures of the card to answer; "
                           f"the last: {rec['leg']} on {rec['image']}: {rec.get('reason')}")

    def run_battery_leg(self, leg: str, img: Image, visit: int) -> Optional[Dict[str, Any]]:
        attempt = 1
        while True:
            cmd = self.leg_cmd(leg, img, visit)
            if isinstance(cmd, Skip):
                if attempt == 1:
                    self.skipped(leg, img, cmd.reason)
                return None
            rec = self.run_leg(leg, img, cmd, attempt=attempt)
            self.after_result(rec)
            if rec["status"] in ("timeout", "no_device") and attempt <= self.a.leg_retries:
                self.recover(img, self.streak)
                if self.hard or self.should_stop():
                    return rec
                attempt += 1
                continue
            if rec["status"] in ("timeout", "no_device"):
                self.recover(img, self.streak)
            return rec

    # -- the sweep ----------------------------------------------------------
    def load_state(self) -> None:
        """Rebuild the cycle counter, the rotation, the visits, the sweep's coverage, the seeds,
        the rates and the quarantine from metrics.jsonl alone."""
        if not os.path.exists(self.metrics):
            return
        self.repair_tail()
        recs, _partial, bad = L.read_records(self.metrics)
        if bad:
            raise SystemExit(f"{self.metrics}: lines {bad[:10]} do not parse; will not resume over them")
        iv, served, _cases, seeds, dis = L.sweep_coverage(recs)
        self.intervals = {k: list(v) for k, v in iv.items()}
        self.served = dict(served)
        self.seed_n = {k: v + 1 for k, v in seeds.items()}
        self.seed_states.update(L.seed_states(recs))
        self.disagreements = len(dis)
        for r in recs:
            t = r.get("type")
            if t == "run_start" and isinstance(r.get("tree"), dict):
                self.prev_rtl = r["tree"].get("rtl") or None
            if t == "cycle_start":
                self.cycle = max(self.cycle, int(r["cycle"]))
                self.visits[r["image"]] = max(self.visits.get(r["image"], 0), int(r.get("visit", 0)))
                if not r.get("quick"):
                    self.picked += 1
            elif t == "leg":
                self.seq = max(self.seq, 0)
                if r.get("kind") == "sweep":
                    sw = r.get("sweep") or {}
                    st_, nm_ = r.get("status"), sw.get("item")
                    if nm_ and st_ in ("parse_error", "error"):
                        self.item_bad[nm_] = self.item_bad.get(nm_, 0) + 1
                    elif nm_ and st_ in ("pass", "fail"):
                        self.item_bad[nm_] = 0
                        if "lo" in sw:
                            sm = self.sums.setdefault(nm_, [0, 0])
                            sm[0] += int((r.get("counts") or {}).get("cases", 0))
                            sm[1] += int((r.get("counts") or {}).get("skipped", 0))
                    if r.get("status") in ("timeout", "no_device", "parse_error") and "lo" in sw:
                        k = (sw["item"], int(sw["lo"]), int(sw["hi"]))
                        self.fail_slices[k] = self.fail_slices.get(k, 0) + 1
                    self.note_rate(r)
        for nm_, n_ in self.item_bad.items():
            if n_ > self.a.quarantine_after:
                self.disabled_items[nm_] = f"{n_} slices in a row gave no readable verdict (from the records)"
        for (item, lo, hi), n in self.fail_slices.items():
            if n >= self.a.quarantine_after:
                self.quarantine.setdefault(item, []).append((lo, hi))
        self.seq = len(glob.glob(os.path.join(self.logs, "*"))) + 1000

    def load_earlier(self) -> None:
        """--earlier-runs: each random item's first n here is above the highest n any named run used (and above this
        file's own, when it is resumed), so a new --out draws new operands and not the last run's again. The
        directories are named, never searched for; parse_args has refused a name that is no run, and a directory
        that changed since is refused again here, by name."""
        if not self.a.earlier_runs:
            return
        try:
            floor, states, notes = L.earlier_runs(self.a.earlier_runs, self.batch)   # a cvtfrom item's floor: this batch's slices
        except L.EarlierRunError as e:
            raise SystemExit(str(e))
        self.seed_floor, self.earlier_notes = floor, notes
        for state, who in states.items():
            self.seed_states.setdefault(state, who)
        for item, n in floor.items():
            self.seed_n[item] = max(self.seed_n.get(item, 0), n)

    def repair_tail(self) -> None:
        """A metrics file whose last line has no newline was caught mid-append (the driver or the host died in
        the write). Appending to it would fuse the next record to that line and make a line no later resume
        could read. A last line that is a whole record just gets its newline; a torn one is kept beside the
        file (metrics.torn-<time>.txt) and the file is cut back to its last whole record."""
        with open(self.metrics, "rb") as fh:
            data = fh.read()
        if not data or data.endswith(b"\n"):
            return
        cut = data.rfind(b"\n") + 1
        tail = data[cut:]
        try:
            json.loads(tail.decode("utf-8"))
            whole = True
        except (ValueError, UnicodeDecodeError):
            whole = False
        if whole:
            with open(self.metrics, "ab") as fh:
                fh.write(b"\n")
            self.torn_note = "the last record of metrics.jsonl was whole but had no newline: one was added"
            return
        side = os.path.join(self.out, f"metrics.torn-{int(time.time())}.txt")
        with open(side, "wb") as fh:
            fh.write(tail)
        with open(self.metrics, "r+b") as fh:
            fh.truncate(cut)
        self.torn_note = (f"the last line of metrics.jsonl was torn ({len(tail)} bytes, a write cut short): kept in "
                          f"{os.path.basename(side)}, the file cut back to its last whole record")

    def note_rate(self, r: Dict[str, Any]) -> None:
        if r.get("status") not in ("pass", "fail"):
            return
        sw = r.get("sweep") or {}
        dur = float(r.get("duration_s") or 0)
        if dur <= 0:
            return
        units = (int(sw["hi"]) - int(sw["lo"])) if "lo" in sw else int(sw.get("count") or 0)
        if units <= 0:
            return
        key = f"{sw.get('op')}@{r.get('image')}"
        j = max(1, int(sw.get("jobs", 1)))
        # a slice's own rate, for ONE job; the longest slice seen is the least start-up-skewed
        new = units / dur
        if dur >= 20 or key not in self.rate:
            self.rate[key] = new

    def pick_item(self, reserved: Dict[str, List[Tuple[int, int]]], avoid: set,
                  only: Optional[str] = None, reach: Optional[str] = None
                  ) -> Optional[Tuple[L.Item, Optional[Tuple[int, int]]]]:
        """The next item by weighted rotation (fewest slices served per unit of weight), with
        its next gap (exhaustive) or None (random). Exhaustive items already covered, and items
        in `avoid` (served this wave), are not eligible. `reach` limits the choice to the items
        of one kind: the card's sweep asks for TILE, the host pool for HOST (under pool_lock, so
        that its pick and its reservation are one step; the two kinds touch different items)."""
        best, best_key = None, None
        for idx, it in enumerate(self.items):
            if it.name in avoid or (only is not None and it.name != only):
                continue
            if reach is not None and it.reach != reach:
                continue
            if self.sweep_only and it.name not in self.sweep_only:
                continue
            if it.name in self.disabled_items:
                continue
            gap = None
            if it.kind == "exhaustive":
                have = self.intervals.get(it.name, []) + self.quarantine.get(it.name, []) + reserved.get(it.name, [])
                gap = L.first_gap(have, it.space)         # the item's own space: 2^32 encodings, or a mode's indices
                if gap is None:
                    continue
            w = self.sweep_weights.get(it.kind, 1) or 1
            key = (self.served.get(it.name, 0) / w, idx)
            if best_key is None or key < best_key:
                best, best_key, best_gap = it, key, gap
        if best is None:
            return None
        return best, best_gap  # type: ignore[possibly-undefined]

    def slice_units(self, it: L.Item, img: Image, secs: float) -> int:
        """Cases (or encodings) in a slice: the probe size until this op has a rate measured on
        this image, then what the measured rate fills `secs` with, in whole ATOMs. --quick uses
        its own small size: its slices measure the rate, they do not fill time. The card's slices
        are held at 2^28; a host job's at L.HOST_SLICE_CAP (see there)."""
        if self.quick:
            return self.a.quick_slice_cases
        rate = self.rate.get(f"{it.op}@{img.name}")
        if rate is None:
            return self.a.probe_cases
        units = int(rate * secs)
        units = max(L.ATOM, min(units, L.HOST_SLICE_CAP if img.name == L.CPU else 1 << 28))
        return units - units % L.ATOM

    def soak_binary(self, it: L.Item) -> str:
        """The tool of a sweep slice: the default build, or with --sweep-chunk N the one `make soak-chunk` made at pass size N
        (host/Makefile: divsqrt-soak-cN, clause5-soak-cN, each against a library of its own)."""
        name = "divsqrt-soak" if it.tool == "divsqrt" else "clause5-soak"
        return os.path.join(self.root, "host", f"{name}-c{self.chunk}" if self.chunk else name)

    def plan_wave(self, img: Image, remaining: float, jobs: int,
                  forced: Optional[List[str]] = None, reach: str = L.TILE,
                  busy: Optional[set] = None) -> List[Dict[str, Any]]:
        """The jobs of one wave. `reach` is the kind of item they may be: the card's sweep plans TILE items
        and never a host item (the host pool plans those, with img = the cpu pseudo-image and reach HOST);
        `busy` is the items already running, which this wave does not take again."""
        wave: List[Dict[str, Any]] = []
        reserved: Dict[str, List[Tuple[int, int]]] = {}
        avoid: set = set(busy or ())
        slice_secs = min(self.a.sweep_slice_seconds, max(5.0, remaining - 15))
        for k in range(jobs):
            pick = self.pick_item(reserved, avoid, forced[k] if forced and k < len(forced) else None, reach)
            if pick is None:
                if forced and k < len(forced):
                    continue         # that item cannot run (disabled, covered): the rest of the wave still can
                break
            it, gap = pick
            avoid.add(it.name)
            units = self.slice_units(it, img, slice_secs)
            job: Dict[str, Any] = {"item": it, "units": units, "slice_secs": slice_secs, "tile": None}
            if it.kind == "exhaustive":
                lo = gap[0]
                hi = min(gap[1], lo + units)
                job.update(lo=lo, hi=hi)
                reserved.setdefault(it.name, []).append((lo, hi))
                job["expected"] = it.expected_cases(lo, hi)
                job["cover"] = it.cover_spec(lo, hi)
                job["argv"] = it.argv(self.soak_binary(it), lo=lo, hi=hi)
                job["sweep"] = {"item": it.name, "tool": it.tool, "op": it.op, "mode": it.mode,
                                "reach": it.reach, "lo": lo, "hi": hi, "tile": None}
            else:
                n = self.seed_n.get(it.name, 0)
                seed = it.seed_for(n)
                # the tool starts from seed | 1: refuse, by name, a state a slice of ANOTHER (item, n) in this file or in
                # an --earlier-runs directory already started from (the same item and n is a slice served again). A cvtfrom
                # item's stream is the state AND the batch (L.stream_key): its draws go to other source types at another BATCH
                prior = self.seed_states.get(L.stream_key(it.op, seed, self.batch))
                if prior is not None and prior != (it.name, n):
                    raise RuntimeError(f"seed collision: {it.name} slice {n} would start from tool state {seed | 1:#x}"
                                       f"{f' at batch {self.batch}' if it.layout_dependent else ''}, which "
                                       f"{prior[0]} slice {prior[1]} already started from; its draws would repeat")
                job.update(count=units, seed=seed, seed_n=n)
                # a chunked run holds a random scaleB slice to the cases its BATCH gives (CK's finding i: the count rounded up by
                # whole batches); the default run has never held a random slice to a count, and does not now
                job["expected"] = it.random_cases(units, self.batch) if self.chunk else None
                job["cover"] = None
                job["argv"] = it.argv(self.soak_binary(it), count=units, seed=seed)
                job["sweep"] = {"item": it.name, "tool": it.tool, "op": it.op, "mode": it.mode,
                                "reach": it.reach, "count": units, "seed": seed, "seed_n": n,
                                "seed_scheme": L.SEED_SCHEME, "tile": None}
            if jobs > 1 and img.tiles > 1:
                job["tile"] = k + 1
                job["sweep"]["tile"] = k + 1
            job["timeout"] = max(180.0, 3.0 * slice_secs + 120.0)
            wave.append(job)
        return wave

    def soak_jobs_for(self, img: Image) -> int:
        if self.a.soak_jobs == "auto":
            return img.tiles
        return max(1, min(int(self.a.soak_jobs), img.tiles))

    def run_wave(self, img: Image, wave: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Start the wave's jobs together (one process a tile on the quad), wait for all, parse
        and record each. The jobs are the soak binaries on the job lines run-soak.sh and
        run-c5-soak.sh print, with CFT_SOAK_ARTIFACT naming the image."""
        procs = []
        for job in wave:
            it: L.Item = job["item"]
            base, logpath = self.log_name(f"sweep-{it.name}")
            env = {"CFT_SOAK_ARTIFACT": img.path}
            if job["tile"]:
                env["CFT_XRT_TILES"] = str(job["tile"])
            argv = self.standin("soak", job["argv"]) if self.dry else job["argv"]
            res = ProcResult()
            res.start = time.time()
            try:
                proc, logf, full = self.spawn(argv, env, logpath, self.root, job["timeout"])
            except OSError as e:
                res.end = time.time()
                res.error = f"could not start {argv[0]}: {e}"
                proc = logf = None
            procs.append((job, base, logpath, proc, logf, res))
            self.say(f"sweep job {it.name} [{job['sweep'].get('lo', job['sweep'].get('count'))}"
                     f"{'-' + str(job['sweep']['hi']) if 'hi' in job['sweep'] else ' cases'}]"
                     f" on {img.name}{' tile ' + str(job['tile']) if job['tile'] else ''}")
        self.current = f"{len(procs)} sweep job(s) on {img.name}"
        threads = []
        for job, base, logpath, proc, logf, res in procs:
            if proc is None:
                continue
            t = threading.Thread(target=self._wait_job, args=(proc, job["timeout"], res, logf), daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            while t.is_alive():
                t.join(timeout=5)
                self.heartbeat()
        recs = []
        for job, base, logpath, proc, logf, res in procs:
            it = job["item"]
            exp = job["expected"]
            cover = job["cover"]
            cmd = Cmd(job["argv"], job["timeout"],
                      (lambda t, rc, it=it, exp=exp, cover=cover, img=img: L.parse_soak(
                          t, rc, it.op, it.verdict_mode, img.path, exp, cover, chunk=self.chunk)))
            sweep = dict(job["sweep"])
            sweep["jobs"] = len(wave)
            if exp is not None:
                sweep["expected_cases"] = exp
            if cover is not None:
                sweep["expected_encodings"] = cover["encodings"]
            rec = self.finish_leg(f"sweep-{it.name}", img, "sweep", 1, sweep, job["tile"], res, None,
                                  base, logpath, None, cmd, exp)
            recs.append(rec)
            for name, detail, kw in self.account_slice(rec, job):
                self.event(name, detail, **kw)
        return recs

    def account_slice(self, rec: Dict[str, Any], job: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
        """Fold one finished sweep slice into what the driver knows - the item's good and bad streak, the slices
        served, the coverage, the next seed number, the rate, the quarantine - for the card's wave and the host
        pool alike. Returns the events to emit, which the caller emits AFTER this has let go of pool_lock."""
        it: L.Item = job["item"]
        st = rec["status"]
        ev: List[Tuple[str, str, Dict[str, Any]]] = []
        with self.pool_lock:
            if it.kind == "random":
                # started from this seed, whatever came of it: the guard in plan_wave refuses another (item, n) on it
                self.seed_states[L.stream_key(it.op, job["seed"], self.batch)] = (it.name, job["seed_n"])
            if st in ("parse_error", "error"):
                self.item_bad[it.name] = self.item_bad.get(it.name, 0) + 1
                if self.item_bad[it.name] > self.a.quarantine_after:
                    self.disabled_items[it.name] = (f"{self.item_bad[it.name]} slices in a row gave no readable verdict; "
                                                    f"the last: {(rec.get('reason') or '')[:120]}")
                    ev.append(("item_disabled", f"{it.name}: {self.disabled_items[it.name]}; the sweep goes on "
                               f"without it", {"item": it.name}))
            elif st in ("pass", "fail"):
                self.item_bad[it.name] = 0
            if st in ("pass", "fail"):
                self.served[it.name] = self.served.get(it.name, 0) + 1
                if it.kind == "exhaustive":
                    self.intervals.setdefault(it.name, []).append((job["lo"], job["hi"]))
                    sm = self.sums.setdefault(it.name, [0, 0])
                    sm[0] += int((rec.get("counts") or {}).get("cases", 0))
                    sm[1] += int((rec.get("counts") or {}).get("skipped", 0))
                    ev += self.whole_space_events(it)
                else:
                    self.seed_n[it.name] = job["seed_n"] + 1
                self.note_rate(rec)
                if st == "fail":
                    self.disagreements += 1
            elif it.kind == "exhaustive":
                k = (it.name, job["lo"], job["hi"])
                self.fail_slices[k] = self.fail_slices.get(k, 0) + 1
                if self.fail_slices[k] >= self.a.quarantine_after:
                    self.quarantine.setdefault(it.name, []).append((job["lo"], job["hi"]))
                    ev.append(("quarantine", f"{it.name} [{job['lo']}, {job['hi']}) failed to finish "
                               f"{self.fail_slices[k]} times; the sweep moves past it", {"item": it.name}))
        return ev

    def whole_space_events(self, it: L.Item) -> List[Tuple[str, str, Dict[str, Any]]]:
        """When an item with a whole-space figure (Item.whole: HC's `hard-count` totals, CL's cvtto64-class counts, k x E for the
        other class modes) has just become wholly covered, hold the cases and skipped slots of its slices to it, once: the cover
        rule of each slice (cases + skipped = k x E) cannot see a tool that skips the wrong indices, and the sum can. Called under
        pool_lock; returns the event to emit, `whole_space_ok` or `whole_space_mismatch`, which the caller emits after it lets go."""
        if it.whole is None or it.name in self.whole_done or L.first_gap(self.intervals.get(it.name, []), it.space) is not None:
            return []
        self.whole_done.add(it.name)
        cases, skipped = self.sums.get(it.name, [0, 0])
        wc, ws = it.whole
        ok = (cases, skipped) == (wc, ws)
        what = (f"{it.name}: its {self.served.get(it.name, 0)} slice(s) cover [0, {it.space:,}); their cases {cases:,} and skipped "
                f"{skipped:,} " + ("equal the whole space's" if ok else f"are NOT the whole space's {wc:,} and {ws:,}")
                + (" (hard-count's totals)" if it.level == "hard" else " (the mode's own whole-space counts)"))
        return [("whole_space_ok" if ok else "whole_space_mismatch", what, {"item": it.name, "cases": cases, "skipped": skipped,
                                                                        "want_cases": wc, "want_skipped": ws})]

    def _wait_job(self, proc, timeout_s, res, logf) -> None:
        try:
            self.await_proc(proc, timeout_s, res)
        finally:
            try:
                logf.close()
            except OSError:
                pass
            res.end = time.time()

    def sweep_phase(self, img: Image, minutes: float) -> None:
        if self.a.no_sweep or minutes <= 0:
            return
        budget_end = time.time() + (self.a.quick_sweep_seconds if self.quick else minutes * 60.0)
        if self.deadline is not None:
            budget_end = min(budget_end, self.deadline)
        jobs = self.soak_jobs_for(img)
        waves = 0
        while True:
            stop = self.should_stop()
            if stop:
                raise stop
            remaining = budget_end - time.time()
            if remaining < self.a.min_slice_seconds and not (self.quick and waves == 0):
                break
            if self.quick and waves >= self.quick_waves(img):
                break
            self.guard(True)
            forced = self.quick_items(img, waves) if self.quick else None
            wave = self.plan_wave(img, remaining, jobs, forced)
            if not wave:
                why, cause = self.why_no_wave(forced)
                self.event("sweep_empty", why, image=img.name, cause=cause)
                if self.quick and not self.sweep_only and waves + 1 < self.quick_waves(img):
                    waves += 1       # quick's own list: the next wave has another item (a single's rint32-rne after a covered sqrt32-rne)
                    continue
                break
            recs = self.run_wave(img, wave)
            waves += 1
            bad = [r for r in recs if r["status"] in ("timeout", "no_device")]
            for r in recs:
                if r["status"] in ("pass", "fail"):
                    self.streak = 0
            if bad:
                self.streak += len(bad)
                if self.streak >= self.a.max_card_failures:
                    raise Stop("card_lost", 3, f"{self.streak} consecutive failures of the card to answer; "
                               f"the last: {bad[-1]['leg']} on {img.name}: {bad[-1].get('reason')}")
                self.recover(img, self.streak)

    def quick_waves(self, img: Image) -> int:
        return 1 if img.tiles > 1 else 2

    def quick_items(self, img: Image, wave_no: int) -> List[str]:
        """--quick's sweep, fixed so the smoke shows each soak tool once on each image: on the quad
        one wave of four jobs, one a tile (QUICK_QUAD_ITEMS: both soak tools, an exhaustive and a random
        item of the clause-5 tool); on a single, two waves of one job. TILE items only: a host item is
        the pool's (QUICK_HOST_ITEMS), and the card is not asked to run it.

        With --sweep-items the named tile items replace that list (2026-10-20; before, every wave was
        empty whenever none of the four was named, and the log said the campaign was finished). They
        are taken in the order named, the least served first, and an item that cannot run is passed
        over: the first four distinct ones on the quad, and on a single image one a wave, so a
        second image's waves are the next items and not the same ones again (with --resume, a
        second smoke goes on again)."""
        if self.sweep_only:
            names = [n for n in dict.fromkeys(self.sweep_only) if self.pick_item({}, set(), n, L.TILE)]
            names.sort(key=lambda n: self.served.get(n, 0))     # stable: a tie stays in the order named
            return names[:img.tiles if img.tiles > 1 else 1]
        if img.tiles > 1:
            return list(QUICK_QUAD_ITEMS)
        return [[QUICK_SINGLE_ITEMS[0]], [QUICK_SINGLE_ITEMS[1]]][min(wave_no, 1)]

    def why_no_wave(self, forced: Optional[List[str]]) -> Tuple[str, str]:
        """(a sentence, its cause - "finished" or "blocked") for a wave that plan_wave could not fill with one job.
        The campaign is the catalog, or the items named by --sweep-items. It is finished only when every item of it is
        an exhaustive item already covered, and only then does the sentence say `nothing left to run`: decided over the
        CAMPAIGN, never over the wave's own list (verifier-VDR1: a single image whose sqrt32-rne was covered planned no
        job from its list while sqrt32-rtz was still to run, and the sentence called the campaign finished). The wave's
        list gives the causes, and when it is blocked and the campaign is not, the sentence says what remains.
        2026-10-19's smoke printed the finished words on each image when --sweep-items named none of --quick's own items."""
        have = {it.name: it for it in self.items}
        named = list(dict.fromkeys(self.sweep_only))
        campaign = named or [it.name for it in self.items]
        scope = "named by --sweep-items" if named else "in the campaign"

        def stopped_by(n: str) -> Tuple[str, str]:
            """(what stops the item, how it is listed); "" for an item that can run."""
            it = have.get(n)
            iv = self.intervals.get(n, [])
            if it is None:
                return "not in this run's catalog (a probe at the build ruled it out)", n
            if self.sweep_only and n not in self.sweep_only:
                return "outside --sweep-items", n
            if n in self.disabled_items:
                return "disabled", f"{n} ({self.disabled_items[n][:90]})"
            if it.kind == "exhaustive" and L.first_gap(iv, it.space) is None:
                return "covered", n
            if it.kind == "exhaustive" and L.first_gap(iv + self.quarantine.get(n, []), it.space) is None:
                return "moved past by the quarantine", n
            if it.reach == L.HOST:
                return "a host item the CPU pool runs, not the card", n
            return "", n

        def causes(names: List[str]) -> str:
            by: Dict[str, List[str]] = {}
            for n in names:
                c, tag = stopped_by(n)
                by.setdefault(c or "able to run, but no job was planned (a defect in this driver)", []).append(tag)
            return "; ".join(f"{len(v)} {k}: {', '.join(v[:6])}{', ...' if len(v) > 6 else ''}" for k, v in by.items())

        can_run = [n for n in campaign if not stopped_by(n)[0]]
        if all(stopped_by(n)[0] == "covered" for n in campaign):
            return (f"nothing left to run {'for the items named by --sweep-items' if named else 'in this campaign'}: all "
                    f"{len(campaign)} {'are' if named else 'items are'} exhaustive and covered", "finished")
        left = f"{len(can_run)} of the {len(campaign)} items {scope} can still run ({', '.join(can_run[:6])}{', ...' if len(can_run) > 6 else ''})"
        if can_run and forced:
            return (f"no job from this wave's list could start ({causes(list(forced))}), but the campaign is NOT finished: "
                    f"{left}", "blocked")
        if can_run:
            return f"no sweep job was planned although {left}: a defect in this driver", "blocked"
        return (f"no sweep job could start, and the campaign is NOT finished - of the {len(campaign)} items {scope}, "
                + causes(campaign), "blocked")

    # -- the host pool --------------------------------------------------------
    # The HOST items (hw/card_stress_lib.py, OP_REACH) are libcft's host code: no floating-point arithmetic, "bit-identical
    # on every backend by construction", the device argument "context ... not a participant" (host/src/clause5.c, 11-35,
    # read again for this parcel against the code of that section and of the soaks). A card soak of one tested the library
    # on the box's CPU and spent a tile's sweep time on it: 52.5 per cent of the final stress run's sweep job-seconds
    # (docs/studies/SWP-A-coverage.md, 2.3). So they run here instead: --host-workers threads, each starting one soak process
    # at a time, from the start of the run to its end, beside the battery and the card's sweep. A host job is the same soak
    # binary on the same job line, niced and under `timeout` like every leg, with CFT_SOAK_ARTIFACT and CFT_XRT_TILES removed
    # from its environment: it soaks the software backend and cannot open the card. Its slices are recorded as sweep legs
    # of the image `cpu`. A host job's failure is its item's, never the card's: nothing here touches the streak, recover()
    # or the card_lost stop.
    def node(self) -> str:
        return os.uname().nodename if hasattr(os, "uname") else os.environ.get("COMPUTERNAME", "?")

    def pool_start(self) -> None:
        a = self.a
        if a.no_sweep or a.host_workers <= 0:
            self.pool_note = f"off ({'--no-sweep' if a.no_sweep else '--host-workers 0'}): the host items do not run"
            self.say(f"host pool: {self.pool_note}")
            return
        host = self.host_items()
        if self.quick:
            names = list(dict.fromkeys(self.sweep_only)) if self.sweep_only else list(QUICK_HOST_ITEMS)
            have = {it.name for it in host}
            self.pool_queue = [n for n in names if n in have]
            host = [it for it in host if it.name in self.pool_queue]
        if not host or (not self.quick and self.pick_item({}, set(), None, L.HOST) is None):
            self.pool_note = "off: no host item to run (none in this run's campaign, or all covered)"
            self.say(f"host pool: {self.pool_note}")
            return
        n = min(a.host_workers, len(host))
        self.pool_note = f"{n} worker(s) over {len(host)} host item(s)"
        self.event("host_pool", f"{self.pool_note}: CPU-only jobs, niced {a.nice}, no CFT_SOAK_ARTIFACT, no CFT_XRT_TILES"
                   + (f"; --quick: one slice of each of {', '.join(self.pool_queue or [])}" if self.quick else ""),
                   workers=n, items=len(host))
        for k in range(1, n + 1):
            t = threading.Thread(target=self.pool_worker, args=(k,), name=f"host-pool-{k}", daemon=True)
            t.start()
            self.pool_threads.append(t)

    def host_items(self) -> List[L.Item]:
        return [it for it in self.items if it.reach == L.HOST and (not self.sweep_only or it.name in self.sweep_only)]

    def pool_plan(self) -> Optional[Dict[str, Any]]:
        """The next host slice for a free worker, or None: the pick and the reservation (the item is busy from here) are one
        step under pool_lock, so two workers never take one item, and a slice is sized to the time left before the deadline."""
        with self.pool_lock:
            remaining = (self.deadline - time.time()) if self.deadline is not None else 1e12
            if remaining < self.a.min_slice_seconds and not self.quick:
                return None                    # as the card's sweep: no slice starts with less time than this
            forced = None
            if self.pool_queue is not None:    # --quick: each host item once
                while self.pool_queue and forced is None:
                    name = self.pool_queue.pop(0)
                    if self.pick_item({}, set(self.pool_busy), name, L.HOST):
                        forced = [name]        # an item that is disabled, covered or outside --sweep-items is passed over
                if forced is None:
                    return None
            wave = self.plan_wave(self.cpu, remaining, 1, forced, L.HOST, set(self.pool_busy))
            if not wave:
                return None
            self.pool_busy[wave[0]["item"].name] = {"job": wave[0], "proc": None, "abandon": False}
            return wave[0]

    def pool_done(self) -> bool:
        """Nothing a worker could ever run again: --quick's list is served, or every host item is covered, disabled or
        outside --sweep-items (an item another worker has in flight is not 'nothing')."""
        with self.pool_lock:
            if self.pool_queue is not None:
                return not self.pool_queue
            return self.pick_item({}, set(), None, L.HOST) is None

    def pool_worker(self, k: int) -> None:
        errors = 0
        while not self.pool_stop.is_set():
            job = None
            try:
                stop = self.should_stop()
                if stop is not None:           # a stop (STOP, a signal, the deadline, the disk floor, a moved tree): no slice starts
                    self.say(f"host pool worker {k}: no more slices ({stop.reason}: {stop.detail})")
                    return
                job = self.pool_plan()
                if job is None:
                    if self.pool_done():
                        return
                    self.pool_stop.wait(3.0)
                    continue
                self.run_host_slice(k, job)
                errors = 0
            except Exception as e:             # a worker must never take the run down, nor stop silently
                errors += 1
                self.event("driver_error", f"host pool worker {k}: {type(e).__name__}: {e}", n=errors,
                           traceback=traceback.format_exc()[-1800:])
                if errors >= 5:
                    self.event("host_pool_worker_gone", f"worker {k} stopped after {errors} errors in a row", worker=k)
                    return
                self.pool_stop.wait(min(30.0, self.a.retry_pause))
            finally:
                if job is not None:
                    with self.pool_lock:
                        self.pool_busy.pop(job["item"].name, None)

    def run_host_slice(self, k: int, job: Dict[str, Any]) -> None:
        """One host slice: start the soak, wait for it, and record it like a card slice - unless the run's end killed it."""
        it: L.Item = job["item"]
        if self.pool_stop.is_set():
            return                             # the run is ending: pool_end has already looked for what is running
        base, logpath = self.log_name(f"sweep-{it.name}")
        argv = self.standin("soak", job["argv"]) if self.dry else job["argv"]
        slot = self.pool_busy[it.name]
        res = ProcResult()
        res.start = time.time()
        logf = None
        try:
            proc, logf, full = self.spawn(argv, {}, logpath, self.root, job["timeout"], drop=HOST_JOB_DROPS)
            slot["proc"] = proc
        except OSError as e:
            res.end = time.time()
            res.error = f"could not start {argv[0]}: {e}"
            proc = None
        what = job["sweep"].get("lo", job["sweep"].get("count"))
        self.say(f"host job {it.name} [{what}{'-' + str(job['sweep']['hi']) if 'hi' in job['sweep'] else ' cases'}] "
                 f"on {L.CPU} (worker {k})")
        if proc is not None:
            try:
                self.await_proc(proc, job["timeout"], res)
            finally:
                if logf is not None:
                    logf.close()
                res.end = time.time()
        if slot["abandon"] or (self.hard and res.killed):
            # The run ended with this job in flight, and the job was terminated for it (pool_end, or a second signal).
            # Nothing of that is the item's failure, so it is NOT a leg - as a parse_error or a timeout it would count
            # toward disabling the item or quarantining its range - and the slice is not covered, so a resume serves it
            # again. The event says so.
            self.event("host_job_abandoned", f"{it.name} [{what}{'-' + str(job['sweep']['hi']) if 'hi' in job['sweep'] else ' cases'}]"
                       f" was terminated because the run ended; it is not recorded as a slice, and a resumed run serves it again",
                       item=it.name)
            return
        exp, cover = job["expected"], job["cover"]
        cmd = Cmd(job["argv"], job["timeout"],
                  (lambda t, rc, it=it, exp=exp, cover=cover: L.parse_soak(t, rc, it.op, it.verdict_mode, None, exp, cover,
                                                                           cpu=True, chunk=self.chunk)), card=False)
        sweep = dict(job["sweep"])
        sweep["jobs"] = 1
        sweep["pool"] = {"worker": k, "host": self.node(), "build_id": self.build_id}
        if exp is not None:
            sweep["expected_cases"] = exp
        if cover is not None:
            sweep["expected_encodings"] = cover["encodings"]
        rec = self.finish_leg(f"sweep-{it.name}", self.cpu, "sweep", 1, sweep, None, res, None, base, logpath, None, cmd, exp)
        for name, detail, kw in self.account_slice(rec, job):
            self.event(name, detail, **kw)
        with self.pool_lock:
            self.pool_served += 1
        if rec["status"] == "parse_error" and (rec.get("reason") or "").startswith(L.CPU_OPENED_CARD):
            self.event("host_pool_stopped", "a host job opened the card, which the pool's jobs are started without any way "
                       "to do; the pool stops here and no further host job starts", item=it.name)
            self.pool_stop.set()

    def pool_end(self, drain: bool) -> None:
        """End the pool. A --quick run that finished lets the host items it still owes their one slice finish (seconds)
        first. Then no slice starts, and a slice still running gets --kill-after seconds from now - the run's last card
        leg has just ended - before it is marked abandoned for terminate_children() to end (nothing of a host job
        needs protecting from a stop, as a card leg does: a CPU job poisons nothing)."""
        if not self.pool_threads:
            return
        grace = max(1.0, float(self.a.kill_after))
        if drain and not self.hard:
            t_end = time.time() + max(60.0, grace)
            for t in self.pool_threads:
                t.join(timeout=max(0.0, t_end - time.time()))
        self.pool_stop.set()
        t_end = time.time() + grace
        for t in self.pool_threads:
            t.join(timeout=max(0.0, t_end - time.time()))
        with self.pool_lock:
            live = [s for s in self.pool_busy.values() if s["proc"] is not None and s["proc"].poll() is None]
            for s in live:
                s["abandon"] = True

    def pool_join(self) -> None:
        for t in self.pool_threads:
            t.join(timeout=10.0)

    # -- telemetry ------------------------------------------------------------
    def examine(self, tool: str, rep: str, mode: str) -> Tuple[Dict[str, float], str, Optional[str]]:
        """One `xbutil|xrt-smi examine -d CARD -r REP`, as JSON in a file (`--format JSON --output`)
        or as the as-is text on stdout: (values read, the text, an error or None)."""
        a = self.a
        base = [tool, "examine", "-d", a.card, "-r", rep]
        argv = self.standin("telemetry", base) if self.dry else base
        try:
            if mode == "json":
                os.makedirs(self.tmp, exist_ok=True)
                path = os.path.join(self.tmp, f"tel-{os.getpid()}-{threading.get_ident()}-{rep}.json")
                try:
                    os.remove(path)
                except OSError:
                    pass
                p = subprocess.run(argv + ["--format", "JSON", "--output", path], capture_output=True,
                                   text=True, timeout=a.telemetry_timeout)
                text = ""
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                    os.remove(path)
                got = L.parse_telemetry(text) if text else {}
                err = None if got else f"--format JSON: no values (rc {p.returncode}) {p.stderr.strip()[:120]}"
                return got, text, err
            p = subprocess.run(argv, capture_output=True, text=True, timeout=a.telemetry_timeout)
            got = L.parse_telemetry(p.stdout)
            err = None if got else f"as-is text: no values (rc {p.returncode}) {p.stderr.strip()[:120]}"
            return got, p.stdout, err
        except (OSError, subprocess.TimeoutExpired) as e:
            return {}, "", f"{mode}: {e}"

    def telemetry(self, when: str, img: Optional[Image] = None) -> None:
        """One sample, its record appended in the order the sample was taken. The timer's thread
        and the run's own calls (before-cycle, after-battery, end) can overlap, and unserialised
        two overlapping samples took their readings in one order and appended their records in the
        other: hw/test_card_stress.py's telemetry check saw one pair swapped on a busy desktop
        (docs/VALIDATION.md, parcel EX). So a sample holds tel_lock from its first examine call to
        its append, and a call waits for the sample in flight: no longer than that sample's own
        examine calls, each killed at --telemetry-timeout (3 reports, 2 tools, JSON and text: 12
        calls, 720 s at the default 60 s, only if every call hangs). A timer sample the run's stop
        reaches is dropped at its next examine call, so the "end" sample never waits behind a whole
        new one. It also asks the vendor tool one question at a time of a card that a leg may be
        using."""
        with self.tel_lock:
            self.take_sample(when, img)

    def take_sample(self, when: str, img: Optional[Image] = None) -> None:
        """One sample: each report asked for as JSON, falling back to the as-is text (and
        remembering, per report, that JSON gave nothing where the text did), then the host's
        load, memory and free disk. A sample with no values is recorded as such - ok false, the
        raw text beside it - and never as a reading."""
        values: Dict[str, float] = {}
        errors: List[str] = []
        raws: List[str] = []
        for rep in [r for r in self.a.telemetry_reports.split(",") if r]:
            modes = ["json", "text"] if self.tel_json.get(rep, True) else ["text"]
            got: Dict[str, float] = {}
            text = ""
            err = None
            # the tool that worked for this report first, then the other one that is on PATH: the
            # brief names xrt-smi and calls xbutil the old name, and which one answers `examine -r
            # electrical` on this card was not known when this was written
            tools = self.tel_tools(rep)
            for tool in tools:
                for mode in modes:
                    if when == "timer" and self.tel_stop.is_set():
                        return          # the run is ending and its own "end" sample is next: not behind this one
                    got, text, err = self.examine(tool, rep, mode)
                    if got:
                        if mode == "text" and "json" in modes:
                            self.tel_json[rep] = False
                        self.tel_worked[rep] = tool
                        break
                if got:
                    break
            if got:
                for k, v in got.items():
                    values[f"{rep}.{k}"] = v
            else:
                errors.append(f"{rep}: {err}")
                raws.append(f"[{rep}] {text[:400]}")
        host = L.host_sample(self.card_paths())
        rec = {"type": "telemetry", "cycle": self.cycle or None, "image": img.name if img else None,
               "when": when, "ok": bool(values), "values": values or None, "host": host or None,
               "raw": (" | ".join(raws)[:1200] if not values else None),
               "error": ("; ".join(errors)[:500] if errors else None)}
        self.rec(rec)
        self.last_tel = rec

    def tel_tool(self) -> str:
        t = self.a.telemetry_tool
        if t != "auto":
            return t
        if self.dry:
            return "xbutil"
        for cand in ("xrt-smi", "xbutil"):
            if shutil.which(cand):
                return cand
        return "xbutil"

    def tel_tools(self, rep: str) -> List[str]:
        """Tools to try for a report, the one that worked before first. Naming a tool with
        --telemetry-tool uses that one alone."""
        if self.a.telemetry_tool != "auto" or self.dry:
            return [self.tel_tool()]
        have = [t for t in ("xrt-smi", "xbutil") if shutil.which(t)] or ["xbutil"]
        w = self.tel_worked.get(rep)
        return ([w] + [t for t in have if t != w]) if w in have else have

    def tel_loop(self) -> None:
        while not self.tel_stop.wait(self.a.telemetry_seconds):
            try:
                self.telemetry("timer")
            except Exception as e:  # a sampler must never take the run down
                self.say(f"telemetry sampler: {e!r}")

    # -- the status file ---------------------------------------------------------
    def write_status(self) -> None:
        with self.lock:
            now = time.time()
            # a copy of what the card's thread and the host pool's workers change, taken under their locks (lock order:
            # `lock`, then these; no code that holds one of these calls say(), event() or this)
            with self.tally_lock:
                counts = dict(self.counts)
                by_image = {k: dict(v) for k, v in self.by_image.items()}
            with self.pool_lock:
                intervals = {k: list(v) for k, v in self.intervals.items()}
                served, rate, disabled = dict(self.served), dict(self.rate), dict(self.disabled_items)
                disagreements, pool_served = self.disagreements, self.pool_served
                in_flight = sorted(f"{n} [{s['job']['sweep'].get('lo', s['job']['sweep'].get('count'))}"
                                   f"{'-' + str(s['job']['sweep']['hi']) if 'hi' in s['job']['sweep'] else ' cases'}]"
                                   for n, s in self.pool_busy.items())
            lines = [f"card-stress status   {L.iso(now)}", ""]
            lines.append(f"run        {self.run_id}   out {self.out}"
                         + ("   [QUICK]" if self.quick else "") + ("   [DRY RUN]" if self.dry else ""))
            lines.append(f"state      {self.state}" + (f"   now: {self.current}" if self.current else ""))
            lines.append(f"cycle      {self.cycle}   image {getattr(self, 'cur_image', '-')}"
                         f"   visits {dict(sorted(self.visits.items()))}")
            if self.deadline:
                lines.append(f"deadline   {L.iso(self.deadline)}   remaining {self.deadline - now:.0f} s")
            else:
                lines.append("deadline   none (quick or open-ended)")
            lines.append(f"running    since {L.iso(self.t0)}   {now - self.t0:.0f} s")
            tot = sum(counts.values())
            lines.append(f"legs       {tot}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
            for im, d in sorted(by_image.items()):
                lines.append(f"  {im:<8} " + ", ".join(f"{k} {v}" for k, v in sorted(d.items())))
            lines.append(f"card       consecutive failures {self.streak} of {self.a.max_card_failures}")
            if self.beside:
                lines.append("beside     " + "; ".join(f"verify/run.sh pid {b['pid']}" for b in self.beside))
            if self.last_tel:
                v = self.last_tel.get("values") or {}
                key = [f"{k}={x}" for k, x in list(v.items())[:6]]
                lines.append(f"telemetry  {self.last_tel.get('ts')}: " + ("; ".join(key) if key else
                             "no values parsed" + (f" ({self.last_tel.get('error')})" if self.last_tel.get("error") else "")))
                h = self.last_tel.get("host") or {}
                if h:
                    lines.append(f"host       {h}")
            # the sweep
            ex_total = ex_cov = 0
            by_reach = {L.TILE: [0, 0, 0, 0], L.HOST: [0, 0, 0, 0]}   # exhaustive items, covered, total; random begun
            for it in self.items:
                if it.kind == "exhaustive":
                    cov_it = L.covered(intervals.get(it.name, []) or []) if intervals.get(it.name) else 0
                    ex_total += it.space
                    ex_cov += cov_it
                    by_reach[it.reach][0] += 1
                    by_reach[it.reach][1] += cov_it
                    by_reach[it.reach][2] += it.space
                elif served.get(it.name):
                    by_reach[it.reach][3] += 1
            rnd = sum(1 for it in self.items if it.kind == "random" and served.get(it.name))
            lines.append(f"sweep      exhaustive {ex_cov:,} of {ex_total:,} encodings"
                         f" ({(100.0 * ex_cov / ex_total) if ex_total else 0:.3f} %); "
                         f"slices served {sum(served.values())}; random items begun {rnd};"
                         f" disagreements {disagreements}; rates {{{', '.join(f'{k}: {v:,.0f}/s' for k, v in sorted(rate.items()))}}}")
            # which items reach the tile at all (hw/card_stress_lib.py, OP_REACH): a HOST item is libcft's host
            # code, which the host pool runs on CPUs beside the card, the tile computing nothing for it
            lines.append("reach      " + "; ".join(
                f"{k} items: exhaustive {v[1]:,} of {v[2]:,} encodings ({(100.0 * v[1] / v[2]) if v[2] else 0:.3f} %)"
                f" over {v[0]} item(s), random begun {v[3]}" for k, v in by_reach.items())
                         + "; the tile computes nothing for a host item")
            lines.append(f"hostpool   {self.pool_note}; {pool_served} slice(s) recorded; in flight: "
                         + ("; ".join(in_flight) if in_flight else "none"))
            if self.sink is not None:
                lines.append(f"records    {self.sink.summary()}")
            if disabled:
                lines.append("disabled   sweep items: " + "; ".join(f"{k} ({v[:60]})" for k, v in disabled.items()))
            tmp = self.status_path + ".tmp"
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    fh.write("\n".join(lines) + "\n")
                os.replace(tmp, self.status_path)
            except OSError:
                pass

    # -- the start: tree, build, images ---------------------------------------
    def pre_check(self) -> None:
        """What run_start records: the commit and whether the tree is clean, and each image's
        SHA-256 (read here; build_and_check holds it to SHA256SUMS and to the hash it was given)."""
        self.head = self.git_head()
        dirty = ""
        try:
            dirty = subprocess.run(["git", "-C", self.root, "status", "--porcelain", "--untracked-files=no"],
                                   capture_output=True, text=True, timeout=60).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        self.tree = {"commit": self.head or None, "dirty": bool(dirty), "dirty_files": len(dirty.splitlines())}
        self.tree.update(self.tree_facts())
        for im in self.images.values():
            try:
                im.sha, im.bytes = sha256_file(im.path)
            except OSError as e:
                self.say(f"image {im.name}: cannot read {im.path}: {e}")

    def tree_facts(self) -> Dict[str, Any]:
        """What the report keys a slice's coverage by, recorded in run_start (docs/CARDDAY.md, "The long run"):
        rtl, the git tree hash of rtl/ at HEAD (`git rev-parse HEAD:rtl`), which is what a tile item is evidence about; host_src,
        the same for host/, and cc, the C compiler's first version line, which is what a host item is about; each with a
        `_dirty` flag, true when git status of that directory shows a change, untracked files included (an untracked
        .sv is compiled into a bitstream all the same: hw/rebuild-2022.sh). None where git cannot say, never a guess.
        This is the tree the driver RUNS FROM. It is the tree the images were built from only if they were; the images'
        own identity is their SHA-256, recorded beside it."""
        out: Dict[str, Any] = {}
        for key, rel in (("rtl", "rtl"), ("host_src", "host")):
            h = d = None
            try:
                p = subprocess.run(["git", "-C", self.root, "rev-parse", f"HEAD:{rel}"], capture_output=True, text=True, timeout=30)
                h = p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None
                if h:
                    s = subprocess.run(["git", "-C", self.root, "status", "--porcelain", "--untracked-files=all", "--", rel],
                                       capture_output=True, text=True, timeout=60)
                    d = bool(s.stdout.strip()) if s.returncode == 0 else None
            except (OSError, subprocess.TimeoutExpired):
                pass
            out[key], out[key + "_dirty"] = h, d
        cc = None
        try:
            p = subprocess.run([os.environ.get("CC", "cc"), "--version"], capture_output=True, text=True, timeout=30)
            cc = (p.stdout or p.stderr).strip().splitlines()[0].strip() if p.returncode == 0 and (p.stdout or p.stderr).strip() else None
        except (OSError, subprocess.TimeoutExpired):
            pass
        out["cc"] = cc
        return out

    def build_and_check(self) -> None:
        steps: List[Dict[str, Any]] = []
        ok = True

        def step(name: str, good: bool, detail: str) -> None:
            nonlocal ok
            steps.append({"name": name, "ok": good, "detail": detail[:600]})
            ok = ok and good
            self.say(f"build step {name}: {'ok' if good else 'FAILED'} - {detail[:200]}")

        # 1. the tree: the SHA and, separately, the content (CLAUDE.md, "Before believing a remote build")
        dirty = self.tree.get("dirty_files", 0)
        step("tree", bool(self.head) or self.dry,
             f"HEAD {self.head[:12] or 'unknown'}{', DIRTY (' + str(dirty) + ' files)' if self.tree.get('dirty') else ', clean'}")
        markers = [("host/tests/seq_check.py", "THE ROUTINE CORPUS DID NOT REACH EVERY FORM"),
                   ("programs/acceptance.py", "REV8_ORDER"),
                   ("hw/card-segrun.sh", "== card-segrun:"),
                   ("hw/card_stress.py", "THE LEGS")]
        for rel, text in markers:
            p = os.path.join(self.root, rel)
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as fh:
                    found = text in fh.read()
            except OSError:
                found = False
            step(f"content {rel}", found, f"contains {text!r}" if found else f"does not contain {text!r} (a stale tree?)")
        if self.dry:
            step("tools", True, "dry run: no make, no ldd, no XRT (the stand-ins replace every command)")
        else:
            self.build_tools(step)
        # 5. the images, held to SHA256SUMS beside each and to the hash this driver was given
        for im in self.images.values():
            if not im.sha:
                step(f"image {im.name}", False, f"cannot read {im.path}")
                continue
            good, why = True, f"sha256 {im.sha[:16]}..., {im.bytes:,} bytes"
            sums = os.path.join(os.path.dirname(im.path), "SHA256SUMS")
            if os.path.exists(sums):
                found = None
                with open(sums, "r", encoding="utf-8", errors="replace") as fh:
                    for ln in fh:
                        m = re.match(r"([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", ln)
                        if m and os.path.basename(m.group(2)) == os.path.basename(im.path):
                            found = m.group(1).lower()
                if found is None:
                    good, why = False, f"{sums} has no line for {os.path.basename(im.path)}"
                elif found != im.sha:
                    good, why = False, f"{sums} says {found[:16]}..., the file hashes to {im.sha[:16]}..."
                else:
                    why += ", equal to SHA256SUMS"
            else:
                good, why = False, f"no SHA256SUMS beside {im.path}"
            if good and im.want_sha and im.want_sha != im.sha:
                good, why = False, f"the file hashes to {im.sha[:16]}..., this driver was given {im.want_sha[:16]}..."
            elif good and im.want_sha:
                why += ", equal to the hash given"
            step(f"image {im.name}", good, why)
        self.rec({"type": "build", "ok": ok, "steps": steps})
        if not ok:
            raise Stop("build_failed", 3, "; ".join(f"{s['name']}: {s['detail']}" for s in steps if not s["ok"]))

    def run_quiet(self, argv: List[str], timeout: float, cwd: Optional[str] = None,
                  env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
        e = dict(os.environ)
        e.update(env or {})
        try:
            p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=cwd or self.root, env=e)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as ex:
            return 127, f"{ex}"

    def build_tools(self, step: Callable[[str, bool, str], None]) -> None:
        a = self.a
        host = os.path.join(self.root, "host")
        c5defs = ""
        probe_c = os.path.join(self.tmp, "re-probe.c")
        os.makedirs(self.tmp, exist_ok=True)
        with open(probe_c, "w") as fh:
            fh.write("#define _GNU_SOURCE\n#include <math.h>\nint main(void){return (int)(roundeven(1.5)"
                     "+roundevenf(2.5f));}\n")
        rc, _ = self.run_quiet([os.environ.get("CC", "cc"), probe_c, "-lm", "-o", probe_c + ".out"], 120)
        if rc == 0:
            c5defs = "-DCFT_SOAK_HAVE_ROUNDEVEN=1"
        for f in (probe_c, probe_c + ".out"):
            try:
                os.remove(f)
            except OSError:
                pass
        step("roundeven probe", True, "present" if c5defs else "absent: the rne oracle is rint under FE_TONEAREST")
        targets = ["all", "device-test", "api-test", "remote-test", "divsqrt-soak", "clause5-soak"]
        xrt_flags = a.make_xrt_flags.split() if a.make_xrt_flags else ["XRT=1", f"XRT_ROOT={a.xrt_root}"]
        argv = ["make", "-C", host, f"-j{a.build_jobs}"] + xrt_flags
        if c5defs:
            argv.append(f"C5DEFS={c5defs}")
        argv += targets
        if self.a.nice and shutil.which("nice"):
            argv = ["nice", "-n", str(a.nice)] + argv
        log = os.path.join(self.logs, "build.log")
        t0 = time.time()
        try:
            with open(log, "wb") as lf:
                p = subprocess.run(argv, stdout=lf, stderr=subprocess.STDOUT, timeout=a.build_timeout)
            rc = p.returncode
        except (OSError, subprocess.TimeoutExpired) as e:
            rc = 127
            self.say(f"build: {e}")
        warns = []
        try:
            with open(log, "r", encoding="utf-8", errors="replace") as fh:
                warns = [ln.strip() for ln in fh if "warning:" in ln]
        except OSError:
            pass
        step("make", rc == 0, f"make -C host {' '.join(xrt_flags)} {' '.join(targets)}: rc {rc} in "
             f"{time.time() - t0:.0f} s, {len(warns)} warning line(s) (the known two: "
             f"tools/cft_resident.cpp:264 and :265, deprecated read_register); log {os.path.relpath(log, self.out)}")
        if rc != 0:
            return
        if len(warns) != 2:
            self.say("NOTE: CLAUDE.md says the XRT=1 host build carries exactly two known warnings; "
                     f"this one has {len(warns)}: " + " | ".join(w[:120] for w in warns[:4]))
        if self.chunk:
            # --sweep-chunk N: the sweep's slices run the tools built at pass size N (host/Makefile, `soak-chunk`: divsqrt-soak-cN
            # and clause5-soak-cN against a library of their own). Built with the flags the default build took - the XRT ones and
            # C5DEFS - so that an artifact can be opened, and by a make of its own: it is not a prerequisite of `all`, and the
            # default tools are not touched.
            cargv = ["make", "-C", host, f"-j{a.build_jobs}"] + xrt_flags
            if c5defs:
                cargv.append(f"C5DEFS={c5defs}")
            cargv += [f"SOAK_CHUNK={self.chunk}", "soak-chunk"]
            if a.nice and shutil.which("nice"):
                cargv = ["nice", "-n", str(a.nice)] + cargv
            clog = os.path.join(self.logs, "build-chunk.log")
            t1 = time.time()
            try:
                with open(clog, "wb") as lf:
                    cp = subprocess.run(cargv, stdout=lf, stderr=subprocess.STDOUT, timeout=a.build_timeout)
                crc = cp.returncode
            except (OSError, subprocess.TimeoutExpired) as e:
                crc = 127
                self.say(f"build (soak-chunk): {e}")
            step("make soak-chunk", crc == 0, f"make -C host {' '.join(xrt_flags)}{' C5DEFS=' + c5defs if c5defs else ''} "
                 f"SOAK_CHUNK={self.chunk} soak-chunk: rc {crc} in {time.time() - t1:.0f} s; log {os.path.relpath(clog, self.out)}")
            if crc != 0:
                return
        exes = ["device-test", "api-test", "remote-test", "cft-segrun", "cft-audit", "divsqrt-soak",
                "clause5-soak", "cft-resident", "cft-selftest", "libcft.so"]
        if self.chunk:
            exes += [f"divsqrt-soak-c{self.chunk}", f"clause5-soak-c{self.chunk}"]
        if "XRT=1" not in xrt_flags:
            exes.remove("cft-resident")      # only an XRT=1 build makes it (the test's XRT=0 build has none)
        # cft-resident and cft-selftest serve optional legs: a missing or unlinked one disables its leg
        # by name (a skipped leg, with this reason) instead of refusing the whole run
        optional = {"cft-resident": "resident", "cft-selftest": "selftest"}
        for exe in exes:
            path = os.path.join(host, exe)
            if not os.path.exists(path):
                if exe in optional:
                    self.disabled_legs[optional[exe]] = f"{exe} was not built"
                    step(f"xrt {exe}", True, f"not built: the {optional[exe]} leg is skipped, by name")
                else:
                    step(f"xrt {exe}", False, f"{path} was not built")
                continue
            rc, out = self.run_quiet(["ldd", path], 60)
            if exe in optional and not (rc == 0 and "xrt_coreutil" in out):
                self.disabled_legs[optional[exe]] = f"{exe} does not link XRT (ldd)"
                step(f"xrt {exe}", True, f"NOT XRT-linked (an optional tool): the {optional[exe]} leg is skipped, by name")
                continue
            step(f"xrt {exe}", rc == 0 and "xrt_coreutil" in out,
                 "links libxrt_coreutil" if "xrt_coreutil" in out else
                 "does NOT link XRT: built without XRT=1 it answers every xclbin with 'no such device' (CLAUDE.md)")
        rc, tid = self.run_quiet(["make", "-s", "-C", host, "print-build-id"], 120)
        rc2, bid = self.run_quiet([os.path.join(host, "cft-segrun"), "--build-id"], 60)
        step("build id", rc == 0 and rc2 == 0 and tid.strip() == bid.strip() and bool(bid.strip()),
             f"the tree's {tid.strip()!r}, cft-segrun's {bid.strip()!r}")
        if rc == 0 and rc2 == 0 and tid.strip() == bid.strip() and bid.strip():
            self.build_id = bid.strip()          # what a host slice's record says was run
        for mod in ("mpmath", "pytest"):
            rc, _ = self.run_quiet([self.python, "-c", f"import {mod}"], 60)
            if rc != 0:
                self.say(f"NOTE: {self.python} cannot import {mod}: seq-check's eighth corpus will print a SKIP "
                         f"line, counted in its record as an inner skip")
        # the clause-5 soak's environment probes decide which directed-mode jobs exist, as in
        # hw/run-c5-soak.sh (host only: probes return before the device is opened)
        c5 = os.path.join(host, "clause5-soak")
        sc = L.MODES4 if self.run_quiet([c5, "probe", "scalbn"], 120)[0] == 0 else ("rne",)
        cf = L.MODES4 if self.run_quiet([c5, "probe", "cvtfrom"], 120)[0] == 0 else ("rne",)
        # scaleb32-wide's exponent range, measured on this libm (host only): if it does not hold the wide items
        # do not exist, as run-c5-soak.sh drops their jobs
        wd = sc if self.run_quiet([c5, "probe", "scalebrange"], 120)[0] == 0 else ()
        self.items = L.sweep_items(sc, cf, wd)
        step("probes", True, f"scaleb modes {','.join(sc)}; cvtfrom modes {','.join(cf)}; scaleb32-wide modes "
             f"{','.join(wd) if wd else 'none (probe scalebrange: the derived exponent range does not hold on this libm)'}")
        # the card is there, as far as XRT can say (telemetry, and a cheap look)
        tool = self.tel_tool()
        if shutil.which(tool):
            rc, out = self.run_quiet([tool, "examine", "-d", a.card], 60)
            # advisory, never a reason to stop: xrt-smi 2.19's device-info parser has died on this card
            # before ("Mac address exceed IP4 maximum value", docs/VALIDATION.md 2026-09-08), and the legs
            # say whether the card answers
            step("card visible", True, f"{tool} examine -d {a.card}: rc {rc} (advisory: the legs say whether "
                 f"the card answers)")
        else:
            self.say(f"NOTE: {tool} is not on PATH: telemetry will record errors, and the run goes on")

    # -- a cycle ---------------------------------------------------------------------
    def run_cycle(self, img: Image) -> None:
        self.cycle += 1
        self.cur_image = img.name
        self.visits[img.name] = self.visits.get(img.name, 0) + 1
        visit = self.visits[img.name]
        self.picked += 1
        # the image on disk is still the one that was checked
        if not self.dry or os.path.exists(img.path):
            try:
                sha, _ = sha256_file(img.path)
            except OSError as e:
                raise Stop("image_missing", 3, f"{img.path}: {e}")
            if sha != img.sha:
                raise Stop("image_changed", 3, f"{img.path} hashes to {sha[:16]}..., was {img.sha[:16]}...")
        battery = [leg for leg in self.battery]
        sweep_min = float(self.sweep_minutes.get(img.name, 0))
        self.rec({"type": "cycle_start", "cycle": self.cycle, "image": img.name, "image_sha256": img.sha,
                  "visit": visit, "battery": battery, "sweep_minutes": sweep_min, "quick": self.quick})
        sweep_txt = f"{self.a.quick_sweep_seconds:.0f} s (quick)" if self.quick else f"{sweep_min:g} min"
        self.say(f"cycle {self.cycle}: {img.name} (visit {visit}), battery {battery}, sweep {sweep_txt}")
        t_cycle = time.time()
        self.guard(True)
        self.telemetry("before-cycle", img)
        n_legs = n_failed = 0
        try:
            for leg in battery:
                stop = self.should_stop()
                if stop:
                    raise stop
                if self.deadline is not None and time.time() + self.estimate(leg) > self.deadline + self.a.deadline_grace:
                    self.skipped(leg, img, f"its estimate ({self.estimate(leg):.0f} s) would end past the "
                                 f"deadline by more than the {self.a.deadline_grace:.0f} s grace")
                    continue
                self.guard(True)
                rec = self.run_battery_leg(leg, img, visit)
                if rec is not None:
                    n_legs += 1
                    n_failed += rec["status"] != "pass"
            self.telemetry("after-battery", img)
            stop = self.should_stop()
            if stop:
                raise stop
            self.sweep_phase(img, sweep_min)
        finally:
            self.rec({"type": "cycle_end", "cycle": self.cycle, "image": img.name, "legs": n_legs,
                      "failed": n_failed, "seconds": round(time.time() - t_cycle, 1)})
            self.refresh_report()

    def refresh_report(self) -> None:
        rp = os.path.join(HERE, "card_stress_report.py")
        if not os.path.exists(rp):
            return
        try:
            r = subprocess.run([sys.executable, rp, self.out], capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                self.say(f"the report script exited {r.returncode} (report.txt is as it was): {(r.stderr or r.stdout)[-200:]}")
        except (OSError, subprocess.TimeoutExpired) as e:
            self.say(f"the report script did not run: {e}")

    # -- the whole run --------------------------------------------------------------
    def run(self) -> int:
        a = self.a
        os.makedirs(self.logs, exist_ok=True)
        os.makedirs(self.tmp, exist_ok=True)
        self.run_id = os.path.basename(self.out.rstrip("/\\"))
        if os.path.exists(self.stop_path):
            print(f"{self.stop_path} exists: remove it to start (a stale stop file would end the run "
                  f"after its first leg)", file=sys.stderr)
            return 2
        problem = self.out_in_tree()
        if problem:
            print(problem, file=sys.stderr)
            return 2
        resumed = os.path.exists(self.metrics)
        if resumed and not a.resume:
            print(f"{self.metrics} exists: give --resume {self.out} to continue that run, or a new --out",
                  file=sys.stderr)
            return 2
        for name, (dflt, tiles, target, sha) in IMAGES.items():
            path = a.image.get(name) if a.image else None
            self.images[name] = Image(name, expand(path or dflt), tiles, target,
                                      (a.sha or {}).get(name, sha if not self.dry else None))
        if getattr(a, "records", False):
            rpath = os.path.join(self.out, RECORDS_FILE)
            if not resumed and os.path.exists(rpath):
                print(f"{rpath} exists in a new run's directory: it would be spliced into this run's records; give a new --out",
                      file=sys.stderr)
                return 2
            try:
                self.sink = RecordSink(rpath, a.sign_key, a.device_key, emit=self.event)
                for note in (self.sink.adopt(self.run_id) if resumed else []):
                    self.say(f"records: {note}")
            except RecordsError as e:
                print(f"--records: {e}", file=sys.stderr)
                return 2
        self.items = L.sweep_items()
        exit_code = 0
        reason = "finished"
        try:
            self.load_state()
            self.load_earlier()
            # settings.json is every argument; the three of the coverage wave's flags are left out while they are unset, so that
            # a run without them writes the file it always wrote (a key's PATH is a setting; its secret is never read into one)
            unset = {"sweep_chunk", "records", "sign_key", "device_key"}
            with open(os.path.join(self.out, "settings.json"), "w", encoding="utf-8") as fh:
                json.dump({k: v for k, v in vars(a).items() if not (k in unset and v in (None, False))}, fh, indent=1, default=str)
            self.say(f"card-stress: out {self.out}{' (resumed)' if resumed else ''}; "
                     f"{'QUICK ' if self.quick else ''}{'DRY RUN ' if self.dry else ''}"
                     f"until {L.iso(self.deadline) if self.deadline else 'no deadline'}")
            if self.quick:
                self.say("--quick: every leg once on each image, short slices. ESTIMATED at 24 to 28 minutes on "
                         "the card (docs/CARDDAY.md, \"The long run\"): from the 2026-10-06 card times where there "
                         "are some, guesses for seq-check, the sweep slices and the image loads; not measured")
            self.say(f"stop it: touch {self.stop_path}   (it ends after the leg running)")
            self.say(f"read it: cat {self.status_path}   or   python3 {os.path.join(HERE, 'card_stress_report.py')} {self.out}")
            self.state = "GUARD"
            self.guard(False)
            self.pre_check()
            settings = {"until": L.iso(self.deadline) if self.deadline else None,
                        "quick": self.quick, "dry_run": self.dry, "weights": self.weights,
                        "sweep_minutes": self.sweep_minutes, "legs": self.battery,
                        "timeouts": self.timeouts, "every": self.every, "nice": a.nice,
                        "soak_jobs": a.soak_jobs, "max_card_failures": a.max_card_failures,
                        "disk_floor_gb": a.disk_floor_gb, "host_workers": a.host_workers,
                        "seed_scheme": L.SEED_SCHEME}
            if self.chunk:
                settings["sweep_chunk"] = self.chunk       # the pass size of the sweep's tools; absent for the default tools
            if self.sink is not None:
                settings["records"] = {"file": RECORDS_FILE, "signed": self.sink.signed}
            self.rec({"type": "run_start", "run_id": self.run_id, "out": self.out,
                      "host": self.node(),
                      "argv": sys.argv[1:], "settings": settings,
                      "tree": getattr(self, "tree", None),
                      "earlier_runs": ({"dirs": self.earlier_notes, "first_n": self.seed_floor}
                                       if self.earlier_notes else None),
                      "images": {n: {"sha256": i.sha, "bytes": i.bytes, "tiles": i.tiles, "path": i.path,
                                     "target": i.target} for n, i in self.images.items()},
                      "deadline": L.iso(self.deadline) if self.deadline else None, "resumed": resumed})
            self.started = True
            if self.torn_note:
                self.event("torn_tail", self.torn_note)
            if self.sink is not None and resumed and self.sink.written == 0 and sum(self.served.values()):
                self.event("records_partial", f"resumed with --records on a run whose metrics.jsonl already holds "
                           f"{sum(self.served.values())} finished sweep slice(s) and whose {RECORDS_FILE} holds none: the file "
                           f"starts here, and `sweep_record.py export` of the whole run makes the complete one")
            if resumed and self.prev_rtl and self.tree.get("rtl") and self.prev_rtl != self.tree["rtl"]:
                self.event("tree_changed", f"resumed on RTL tree {self.tree['rtl'][:12]}; the file's earlier run_start recorded "
                           f"{self.prev_rtl[:12]}. The report counts the slices before and after as different trees; this driver "
                           f"goes on from the whole file's coverage, so it does not redo the earlier tree's tile slices. Use a new "
                           f"--out to cover the new tree from the start", before=self.prev_rtl, now=self.tree["rtl"])
            self.note_beside()
            self.state = "BUILD"
            self.build_and_check()
            if not self.items:
                self.items = L.sweep_items()
            self.install_signals()
            if a.telemetry_seconds > 0:
                self.tel_thread = threading.Thread(target=self.tel_loop, daemon=True)
                self.tel_thread.start()
            self.pool_start()
            self.state = "RUNNING"
            self.write_status()
            n_cycles = 0
            while True:
                stop = self.should_stop()
                if stop:
                    raise stop
                img = self.next_image()
                t_c = time.time()
                try:
                    self.run_cycle(img)
                    self.internal_errors = 0
                except Stop:
                    raise
                except Exception as e:
                    # An unexpected exception (a defect in this driver, not a failing leg) must not end a
                    # 60-hour run: record it with its traceback, make sure nothing of ours is left running,
                    # and go on to the next cycle; the fifth in a row stops the run, by name.
                    self.internal_errors += 1
                    self.event("driver_error", f"{type(e).__name__}: {e}", n=self.internal_errors,
                               traceback=traceback.format_exc()[-1800:])
                    self.terminate_children(card_only=True)
                    if self.internal_errors >= 5:
                        raise Stop("driver_error", 3, f"{self.internal_errors} unexpected exceptions in a row; "
                                   f"the last: {type(e).__name__}: {e}")
                    self.sleep_interruptible(min(30.0, self.a.retry_pause))
                n_cycles += 1
                if time.time() - t_c < 1.0:
                    time.sleep(1.0)       # a cycle that ran nothing must not spin
                if self.quick and n_cycles >= len([n for n in ("quad", "single", "deep") if n in self.images]):
                    raise Stop("quick_done", 0, "every image visited once")
        except Stop as s:
            reason, exit_code = s.reason, s.exit_code
            self.event(s.reason if s.reason in ("deadline", "stop_file", "disk_floor", "tree_moved", "card_lost",
                                                "guard_timeout", "driver_error") else "stop_requested",
                       s.detail or s.reason, reason=s.reason)
            if s.exit_code != 0:
                self.write_stopped(s)
        except SystemExit:
            raise
        except KeyboardInterrupt:
            reason, exit_code = "interrupted", 3
        finally:
            self.tel_stop.set()
            if self.tel_thread:
                self.tel_thread.join(timeout=5)
            self.pool_end(drain=reason == "quick_done")      # no host slice starts; the ones in flight get --kill-after
            self.terminate_children()
            self.pool_join()
            if self.sink is not None and self.started:
                self.event("records_summary", self.sink.summary(), records=self.sink.written)
                self.say(f"verify them: python -B hw/sweep_record.py verify {self.sink.path}"
                         + ("" if self.sink.signed else " --allow-unsigned") + "   (add --keyring RING to name whose key it is)")
            try:
                if self.started:
                    self.telemetry("end")
            except Exception:
                pass
            if self.started:
                self.rec({"type": "run_end", "reason": reason, "exit": exit_code, "cycles": self.cycle})
            self.state = f"{'STOPPED' if exit_code else 'FINISHED'}: {reason}"
            self.write_status()
            if self.started:
                self.refresh_report()
        if self.quick and exit_code == 0:
            # the smoke is a check: every leg must have passed (a skip is named, not a failure)
            bad = {k: v for k, v in self.counts.items() if k not in ("pass", "skipped")}
            if bad:
                exit_code = 1
                self.say(f"quick: not every leg passed: {bad}")
        self.say(f"card-stress ends: {reason} (exit {exit_code}); the card is left idle "
                 f"(no process of this run is alive)")
        return exit_code

    def out_in_tree(self) -> Optional[str]:
        """--out inside the checkout would make the tree untracked and change the build id
        hw/card-segrun.sh asserts on every run (the id the tools were built with names a tree
        with no untracked files). Inside is allowed only where git ignores it."""
        rel = os.path.relpath(self.out, self.root)
        if rel.startswith("..") or os.path.isabs(rel):
            return None
        try:
            r = subprocess.run(["git", "-C", self.root, "check-ignore", "-q", self.out], capture_output=True,
                               timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if r.returncode == 0:
            return None
        return (f"--out {self.out} is inside the checkout and git does not ignore it: its files would make the "
                f"tree untracked, and hw/card-segrun.sh would then refuse the tools' build id. Give an --out "
                f"outside {self.root}.")

    def write_stopped(self, s: Stop) -> None:
        try:
            with open(os.path.join(self.out, "STOPPED.txt"), "w", encoding="utf-8") as fh:
                fh.write(f"{L.iso(time.time())}  the driver stopped: {s.reason}\n{s.detail}\n"
                         f"The card was left idle: no process this run started is alive. "
                         f"Read {os.path.join(self.out, 'status.txt')} and the report.\n")
        except OSError:
            pass

    def install_signals(self) -> None:
        def handler(signum, _frame):
            name = signal.Signals(signum).name
            if self.sig is None:
                self.sig = name
                self.event("signal", f"{name}: the run ends after the leg running (send it again to "
                           f"terminate the leg)")
            else:
                self.hard = True
        for s in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(s, handler)
            except (ValueError, OSError):
                pass
        if hasattr(signal, "SIGHUP"):
            try:
                signal.signal(signal.SIGHUP, signal.SIG_IGN)     # a closed terminal must not end the run
            except (ValueError, OSError):
                pass

    def terminate_children(self, card_only: bool = False) -> None:
        """Whatever this run started and is still alive, by PID. Never by a pattern. card_only leaves the host pool's
        jobs alone: a failure in the card's cycle (driver_error) must not kill CPU jobs that are running beside it, and
        have them recorded as failures of their items."""
        keep = set()
        if card_only:
            with self.pool_lock:
                keep = {s["proc"].pid for s in self.pool_busy.values() if s["proc"] is not None}
        for pid, proc in list(self.children.items()):
            if pid in keep:
                continue
            if proc.poll() is None:
                self.say(f"terminating pid {pid} (started by this run)")
                self.kill_group(proc, "TERM")
                t_end = time.time() + self.a.kill_after
                while time.time() < t_end and proc.poll() is None:
                    time.sleep(0.5)
                if proc.poll() is None:
                    self.kill_group(proc, "KILL")
            self.children.pop(pid, None)


# ---------------------------------------------------------------------------
# the command line
# ---------------------------------------------------------------------------

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="card-stress.sh", formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__.split("THE LEGS")[0],
        epilog="Every default is stated in docs/CARDDAY.md, \"The long run\".")
    g = ap.add_argument_group("the run")
    g.add_argument("--until", help='deadline, the box\'s local time: "2026-10-19 08:00". Required for a long run.')
    g.add_argument("--quick", action="store_true", help="the smoke: every leg once on each image, short slices")
    g.add_argument("--dry-run", action="store_true", help="stand-ins for every command; no XRT, no card")
    g.add_argument("--check-tree-in-dry-run", action="store_true",
                   help="in a --dry-run too, compare HEAD with the commit the run started from before every leg, wave, cycle and host "
                        "slice, and stop (tree_moved) when it moved. A dry run does not by default: its --root may be a checkout somebody "
                        "is committing to. The suite's test of the moved tree uses it, on a scratch repository.")
    g.add_argument("--out", help="run directory (default: ~/card-stress-out/<stamp>-<commit>). Keep it OUTSIDE the "
                   "checkout: files there make the tree untracked, and hw/card-segrun.sh asserts the tree's build id")
    g.add_argument("--resume", action="store_true", help="continue the run in --out (sweep state is replayed)")
    g.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)
    g.add_argument("--python", default=os.environ.get("PYTHON", "python3"),
                   help="the python that runs seq_check.py and acceptance.py (default $PYTHON or python3)")
    g = ap.add_argument_group("the images")
    g.add_argument("--image", action="append", default=[], metavar="NAME=PATH",
                   help="override an image's path (quad, single, deep); defaults are $HOME/cardday-rev8{q,a,d}/...")
    g.add_argument("--sha", action="append", default=[], metavar="NAME=HEX",
                   help="override the SHA-256 an image must have (defaults: VALIDATION.md's, 2026-10-06)")
    g.add_argument("--weights", default="quad=4,single=1,deep=1", help="rotation weights (default %(default)s)")
    g = ap.add_argument_group("the legs")
    g.add_argument("--legs", default="", help="the battery, comma-separated, in order (default: all; --quick: the brief's)")
    g.add_argument("--every", default="", help="LEG=N: run LEG on every Nth visit of an image (default selftest=3)")
    g.add_argument("--timeout", default="", help="LEG=SECONDS overrides of the per-leg timeouts")
    g.add_argument("--seq-trials", type=int, default=250, help="seq_check --trials (default %(default)s)")
    g.add_argument("--rev8-images", help="acceptance.py --images for the revision-8 set (default OUT/rev8-images); "
                   "seed it to include the two 40-minute-plus compiles")
    g.add_argument("--keep-pass-logs", choices=("gz", "verdict", "none"), default="gz")
    g = ap.add_argument_group("the sweep")
    g.add_argument("--sweep-minutes", default="quad=45,single=20,deep=20", help="sweep time per cycle by image (default %(default)s)")
    g.add_argument("--sweep-slice-seconds", type=float, default=600, help="target seconds a sweep job runs (default %(default)s)")
    g.add_argument("--probe-cases", type=int, default=1 << 20, help="size of the first slice, which measures the rate (default %(default)s)")
    g.add_argument("--quick-slice-cases", type=int, default=1 << 18, help="slice size in --quick (default %(default)s)")
    g.add_argument("--min-slice-seconds", type=float, default=120, help="no sweep job starts with less cycle time than this")
    g.add_argument("--quick-sweep-seconds", type=float, default=180, help="time budget of --quick's sweep on an image")
    g.add_argument("--soak-jobs", default="auto", help="soak processes at once: auto = one a tile (4 on the quad, pinned by "
                   "CFT_XRT_TILES), or a number")
    g.add_argument("--sweep-weights", default="exhaustive=3,random=1", help="share of sweep slices by campaign kind")
    g.add_argument("--quarantine-after", type=int, default=2, help="a slice that fails to finish this often is moved past")
    g.add_argument("--no-sweep", action="store_true", help="the battery only (no host pool either)")
    g.add_argument("--host-workers", type=int, default=8, help="the host pool: this many CPU-only soak processes at once, "
                   "from the run's start to its end, for the HOST items (the conversions, next, logB, class, remainder: "
                   "libcft's host code, which no tile computes), niced like every leg, with no CFT_SOAK_ARTIFACT, so "
                   "no card is opened; the card's sweep then takes tile items only. 0: the host items do not run at "
                   "all (default %(default)s: a quarter of the box's 36 threads, beside the card's four and the "
                   "battery; docs/CARDDAY.md says why)")
    g.add_argument("--earlier-runs", action="append", default=[], metavar="DIR[,DIR...]",
                   help="earlier runs' output directories, named: each random item's first slice number n here is above "
                   "the highest any of them used, so this run's draws are new (docs/CARDDAY.md, \"The long run\"). A "
                   "directory without a metrics.jsonl, or whose lines do not parse, is refused by name")
    g.add_argument("--sweep-chunk", type=int, default=None, metavar="N",
                   help="the sweep's pass size: the build step also runs `make -C host SOAK_CHUNK=N soak-chunk` (with the XRT "
                   "flags and C5DEFS of the default build), and every sweep slice - the card's and the pool's - runs "
                   "divsqrt-soak-cN or clause5-soak-cN (BATCH and CFT_CHUNK both N); the battery's legs keep the default tools. "
                   "N is a positive multiple of 4096 up to 65536 (the Makefile's rule). Each sweep record then carries the "
                   "`batch` and `chunk` its tool said (docs/CARDDAY.md, \"The soak at a larger pass size\" and \"The driver at "
                   "a larger pass size\": flags are compared per batch, so a larger one compares them over more operands). "
                   "Default: the default tools, and nothing changes")
    g.add_argument("--sweep-items", default="", help="comma-separated campaign items to sweep, e.g. sqrt32-rne,rint32-rne "
                   "(default: all; names are hw/card_stress_lib.py's sweep_items). A wave runs one job a distinct item, so "
                   "name four tile items to use the quad's four tiles; a host item named here is the host pool's, not "
                   "the card's. With --quick the smoke's waves are these tile items, in the order named, the least "
                   "served first (instead of its own four): the first four on the quad, one a wave on a single image; "
                   "and the pool serves each host item named once")
    g = ap.add_argument_group("signed records (hw/sweep_record.py; docs/SWEEP-RECORDS.md, \"From the driver\")")
    g.add_argument("--records", action="store_true",
                   help="write the finished sweep slices as canonical records, version 1, to OUT/sweep-records.jsonl as the legs "
                   "finish, through hw/sweep_record.py's Exporter; needs --sign-key or --device-key; refused with --dry-run (the "
                   "exporter refuses a run whose legs came from stand-ins). A leg the exporter refuses is an event, named, and the "
                   "run goes on. A host-pool slice (image cpu) has no xclbin to name and is not in the file. Default: no file")
    g.add_argument("--sign-key", default=None, metavar="KEYFILE",
                   help="sign the records with this Ed25519 key (python/cft_sign.py's key file; made once with `cft_sign.py keygen`, "
                   "outside every git working tree: a key inside one is refused by name, key-in-tree)")
    g.add_argument("--device-key", default=None, metavar="HEX",
                   help="instead of --sign-key: the public key (64 hex) whose device the records name, unsigned, for "
                   "`sweep_record.py sign` to sign later, as `sweep_record.py export --device-key` does")
    g = ap.add_argument_group("policy")
    g.add_argument("--retry-pause", type=float, default=120, help="seconds to wait after the card fails to answer")
    g.add_argument("--max-card-failures", type=int, default=6, help="consecutive failures after which the run stops")
    g.add_argument("--leg-retries", type=int, default=1, help="times a leg that lost the card is run again")
    g.add_argument("--kill-after", type=float, default=60, help="seconds between TERM and KILL")
    g.add_argument("--nice", type=int, default=10, help="nice -n for every leg (0: none)")
    g.add_argument("--disk-floor-gb", type=float, default=5, help="stop cleanly below this much free space (default %(default)s)")
    g.add_argument("--disk-extra", default="/data", help="a second filesystem held to the floor (default %(default)s, if present)")
    g.add_argument("--guard-wait-max", type=float, default=4 * 3600, help="seconds to wait for another card user")
    g.add_argument("--guard-poll", type=float, default=30)
    g.add_argument("--deadline-grace", type=float, default=900, help="a leg whose estimate ends this far past the deadline is not started")
    g = ap.add_argument_group("telemetry and the build")
    g.add_argument("--card", default="0000:02:00.1", help="the user function's address (default %(default)s)")
    g.add_argument("--telemetry-seconds", type=float, default=300, help="sample every N seconds (0: between legs only)")
    g.add_argument("--telemetry-tool", default="auto", help="xrt-smi or xbutil (default: whichever is on PATH)")
    g.add_argument("--telemetry-reports", default="electrical,thermal,mechanical")
    g.add_argument("--telemetry-timeout", type=float, default=60)
    g.add_argument("--xrt-root", default="/opt/xilinx/xrt")
    g.add_argument("--build-jobs", type=int, default=4)
    g.add_argument("--make-xrt-flags", default="", help=argparse.SUPPRESS)   # the test's: replaces XRT=1 XRT_ROOT=...
    g.add_argument("--build-timeout", type=float, default=2400)
    a = ap.parse_args(argv)
    a.image = dict(kv.split("=", 1) for kv in a.image) if a.image else {}
    for k in a.image:
        if k not in IMAGES:
            ap.error(f"--image {k}: not one of {', '.join(IMAGES)}")
    a.sha = dict(kv.split("=", 1) for kv in a.sha) if a.sha else {}
    if not a.quick and not a.until and not a.dry_run:
        ap.error('a long run needs --until "YYYY-MM-DD HH:MM" (or --quick for the smoke)')
    if a.until:
        try:
            L.parse_when(a.until)
        except ValueError as e:
            ap.error(str(e))
    if a.sweep_items:
        known = {it.name for it in L.sweep_items()}
        for n in a.sweep_items.split(","):
            if n and n not in known:
                ap.error(f"--sweep-items {n!r}: not an item ({', '.join(sorted(known)[:6])}, ...)")
    if a.soak_jobs != "auto" and not a.soak_jobs.isdigit():
        ap.error("--soak-jobs is auto or a number")
    if a.host_workers < 0:
        ap.error("--host-workers is 0 (the host items do not run) or a number of CPU-only soak processes")
    if a.sweep_chunk is not None and not (4096 <= a.sweep_chunk <= 65536 and a.sweep_chunk % 4096 == 0):
        ap.error(f"--sweep-chunk {a.sweep_chunk}: refused. The pass size is a positive multiple of 4096 up to 65536 "
                 f"(host/Makefile's SOAK_CHUNK rule: a larger or odd one would build nothing)")
    if (a.sign_key or a.device_key) and not a.records:
        ap.error("--sign-key and --device-key name the key of the records --records writes: give --records too")
    if a.records:
        if a.dry_run:
            ap.error("--records: refused with --dry-run. hw/sweep_record.py refuses a dry run (its legs come from stand-ins, "
                     "not from the card, and are never exported: docs/SWEEP-RECORDS.md, \"From the driver\")")
        if a.sign_key and a.device_key:
            ap.error("--sign-key and --device-key are alternatives: the key that signs names the device")
        if not (a.sign_key or a.device_key):
            ap.error("--records needs a device: --sign-key KEYFILE (signs the records) or --device-key HEX (unsigned, for "
                     "`sweep_record.py sign` later). Version 1 puts the device in every record")
        try:
            # refused by name, before anything starts: a key inside a git working tree (key-in-tree), a key file that cannot
            # be read or that others may read (key-file), a public key that is no key. The secret is read to be checked and let go
            import sweep_record as SR
            if a.sign_key:
                try:
                    SR.load_seed(a.sign_key)
                except SR.Refusal as e:
                    ap.error(f"--sign-key {a.sign_key}: refused {e.name}: {e.why}")
            else:
                records_device_key(a.device_key)
        except RecordsError as e:
            ap.error(str(e))
    a.earlier_runs = [expand(x.strip()) for v in a.earlier_runs for x in v.split(",") if x.strip()]
    if a.earlier_runs:
        try:
            L.earlier_runs(a.earlier_runs)            # refuse a name that is no run's directory now, not after hours
        except L.EarlierRunError as e:
            ap.error(str(e))
    if not a.out:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        sha = ""
        try:
            sha = subprocess.run(["git", "-C", a.root, "rev-parse", "--short", "HEAD"], capture_output=True,
                                 text=True, timeout=30).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
        a.out = os.path.join(os.path.expanduser("~"), "card-stress-out",
                             f"{stamp}-{sha or 'nogit'}{'-quick' if a.quick else ''}")
    return a


def main(argv: Optional[List[str]] = None) -> int:
    a = parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    return Driver(a).run()


if __name__ == "__main__":
    sys.exit(main())
