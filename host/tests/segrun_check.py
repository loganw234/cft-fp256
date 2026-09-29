# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft-segrun held to the golden writer: the differential gate of the plan
of record's step 3 (docs/ROADMAP.md, "Segments, certificates and the
audit tool"; docs/CERTIFICATES.md, "The segment runner").

    python host/tests/segrun_check.py --tool host/cft-segrun[.exe]
                                      [--serve host/cft-serve[.exe]]
                                      [--keep DIR] [--salt-hex HEX]
    python host/tests/segrun_check.py --tool host/cft-segrun
                                      --device <image.xclbin>
                                      --expect-xclbin HEX --expect-version HEX
                                      --expect-caps "HEX [HEX]"
                                      --expect-tiles N [--no-wider]

`make -C host segruntest` runs the first with the tree's build id in
CFT_EXPECT_BUILD_ID, and verify/run.sh's `programs` stage runs that. The
second is the card leg, which hw/card-segrun.sh runs on the box with the
card, the identity it expects measured apart from the tool (sha256sum of
the image, device-test -i): each certificate is made on the card, held to
everything below, and made again on the software backend, its run blocks
compared byte for byte.

First, git ignores the binary in both its forms, so a build of it leaves
the next build id clean. Then, for each program below, keyed and then
open, on the software backend:
  1. cft-segrun runs it as consecutive segments and writes the
     certificate and every boundary state;
  2. the golden reader (cert.parse) accepts the certificate - with the
     salt, its commitment too;
  3. the golden writer - cert.run_chain, certify_run and encode, handed
     the certificate's identity lines, the salt and the INITIAL states -
     runs every segment itself and writes the same bytes, which holds the
     arithmetic and the carrying of state as well as the encoding;
  4. the states directory holds exactly the boundary files, each the
     golden chain's state at that boundary, lane-major;
  5. cert.audit accepts the certificate from the states the tool wrote:
     every segment of every run, and then a sample the auditor draws
     (its seed printed, so a red sample can be drawn again) - or, for
     the one program certified with a relation broken on purpose, refuses
     it by the name the relation's check has (aux-start);
  6. the identity lines are the library's: build-id is what the binary's
     own `--build-id` prints and what the tree builds (CFT_EXPECT_BUILD_ID);
     the software backend's device lines are `none` and its tiles 1.
Then:
  7. the page's test vectors through `cft-segrun --hash`, and every tag,
     keyed and open, against an HMAC written here from RFC 2104;
  8. every refusal an input or the instrument can cause, by its name and
     exit code (the page lists those only a failure can reach), a refusal
     before the run leaving nothing behind; for each of the page's names,
     the golden writer refusing the same defect by the same name; and each
     refusal whose command line has an --out of its own again with a file
     already there, which must come through it byte for byte - the tool
     removes only what it created;
  9. with --serve: lorenz63 and flagstep certified through a loopback
     cft-serve, stopped by its PID - backend remote, the device lines the
     page's remote rule gives, and every run block byte for byte the
     software backend's, flagstep's flag words and STATUS among them;
 10. memory. What a run beside the main run costs: flagstep on 65,535
     lanes, a main run and two half-step runs, against the main run alone
     - no more than the two runs' inputs and one state to spare, where
     4eed552 held every run's working set at once (verifier-C7's
     regression); peak commit on Windows, on Linux the least address
     space the run writes its certificate in (ulimit -v), found by
     bisection. And what the trial costs the runs, to the page: the least
     address space with the trial and with its allocations skipped
     (CFT_SEGRUN_PLANT=trial-skipped), in two small shapes where eb2d1ae's
     trial cost them up to 40 KiB (verifier-C7) - on Linux; on Windows,
     where identical runs' peak commit differs by several pages, NOT
     TESTED, by name. A host whose hard address-space limit stops a
     measurement says NOT TESTED too, and the gate goes on.

The programs: lorenz63-rk4, lorenz96-rk4 and henonheiles-lf at fp64 and
fp256, each image held to programs/MANIFEST, with its classic bank, a
half-step run beside it (the bank slots that carry h exactly halved,
twice the segments), and at fp64 a wider run - the same source assembled
at fp128 (gen_odes builds none), the bank and the initial state exactly
widened. And `flagstep`, written here: its segments raise flags 20, 0,
1, 0, 20 and STATUS 48, 48, 0, 48, 48. Every ODE segment raises 16 and 0,
so the ODE programs alone cannot tell a writer that drops STATUS, or
writes one segment's flags against another, from one that does not.
And lorenz63 at fp64 once more, its half-step run entered from an
initial state of its OWN, unlike the main run's: every other half-step
run shares run 0's, so a writer that entered a half-step run from run
0's --init would pass them all (verifier-C6's plant). The tool must
still write the golden writer's bytes for what it was handed; the audit
refuses the certificate `aux-start`.

Exit 0 only if every check passed; the last line says so.
"""

import argparse
import dataclasses
import hashlib
import hmac
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOST = HERE.parent
ROOT = HOST.parent
PROGRAMS = ROOT / "programs"
DOC = ROOT / "docs" / "CERTIFICATES.md"
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(PROGRAMS))

from cft_golden import FORMATS, asm, cert, chars, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
import gen_odes  # noqa: E402

# The tool's own refusals, beside the page's table (docs/CERTIFICATES.md,
# "The segment runner"): a command line, a device, memory, an output.
TOOL_OWN = {"usage": 64, "device": 69, "memory": 71, "output": 73}

# How long one run of the tool may take here before it is stopped and
# failed by name: every run the gate asks for takes well under a second,
# and a refusal that did not come - a run of 10^12 segments started -
# must end the check, not the afternoon.
TOOL_TIMEOUT = 120

# lanes and segments a main run, chosen for time: lorenz96 carries forty
# slots a lane and costs the golden executor about 0.24 s a lane-segment
# at either format (measured 2026-09-28), lorenz63 0.06 s, henonheiles
# 0.015 s.
SIZES = {"lorenz63-rk4": (3, 3), "lorenz96-rk4": (2, 2),
         "henonheiles-lf": (4, 4)}
# the bank slots that carry the step h, by their names in gen_odes
H_NAMES = ("H", "H2", "H6", "MH")

FLAGSTEP = """.format   fp64
.deposits 0
.scratch  in 2
.scratch  out 2
.scratch  strict
.const    ONE   = 0x3ff0000000000000
.const    THIRD = 0x3fd5555555555555
.const    HUGE  = 0x7fe0000000000000
.const    INF   = 0x7ff0000000000000
; slot 0 is a counter c, slot 1 a value x. Each segment: c <- c - 1;
; c/3 is inexact where c is not a power of two, c * 2^1023 overflows
; where |c| >= 2, c * inf is invalid where c = 0; x <- x c.
ldl    r3, 0
ldl    r4, 1
sub    r3, r3, ONE
mul    r5, r3, THIRD
mul    r6, r3, HUGE
mul    r7, r3, INF
mul    r4, r4, r3
stl    r3, 0
stl    r4, 1
; STATUS: an indexed load at c's bit pattern is past the scratch in a
; strict image unless c = +0 (bit 5); setact leaves active every lane
; whose c is not 0, and each deposits past max_deposits 0 (bit 4)
ldx    r8, r3
setact r3
deposit r4
actall
halt
"""
FLAGSTEP_FLAGS = [20, 0, 1, 0, 20]
FLAGSTEP_STATUS = [48, 48, 0, 48, 48]

CHECKS = 0
FAILED = []
SKIPS = []


def ok(what):
    global CHECKS
    CHECKS += 1
    print(f"  ok    {what}", flush=True)


def bad(what):
    global CHECKS
    CHECKS += 1
    FAILED.append(what)
    print(f"  FAIL  {what}", flush=True)


def check(cond, what, why=""):
    if cond:
        ok(what)
    else:
        bad(what + (f" - {why}" if why else ""))
    return cond


def skip(what, why):
    SKIPS.append(what)
    print(f"SKIP  {what}: {why}", flush=True)


def dec(fmt, text):
    return chars.from_decimal(FORMATS[fmt], text, sf.RND_RNE)[0]


# ---- the programs -------------------------------------------------------

@dataclasses.dataclass
class RunSpec:
    kind: str           # main, half-step or wider
    image: bytes
    bank: bytes
    init: list          # the initial state's values, lane-major
    fmt: str
    segments: int
    steps: int
    params: tuple = ()
    h_slots: tuple = ()


@dataclasses.dataclass
class Program:
    name: str
    runs: list
    # None: the golden audit must accept the certificate. A refusal's
    # name: the certificate carries a relation broken on purpose, and the
    # audit must refuse it by that name, full and sampled alike.
    audit_refuses: str = None


def halved(fmt, bank, slots):
    """The bank with each named slot exactly halved (test_cert's
    `halved`): the half-step bank of the plan."""
    vals = cert.state_values(fmt, bank)
    for s in slots:
        vals[s], fl = sf.mul(FORMATS[fmt], vals[s], dec(fmt, "0.5"))
        assert fl == 0, "halving is exact for these banks"
    return cert.state_bytes(fmt, vals)


def ensemble(base, fmt, lanes):
    """Each lane displaced from the first by an exact dyadic amount, as
    programs/check.py's ensembles are - written again here, not imported."""
    out = []
    for i in range(lanes):
        if base == "lorenz63-rk4":
            out += [dec(fmt, repr(1 + i / 64)), dec(fmt, "1"), dec(fmt, "1")]
        elif base == "lorenz96-rk4":
            out += [dec(fmt, repr(8 + (i + 1) / 1024))] + \
                   [dec(fmt, "8")] * (gen_odes.L96_N - 1)
        else:
            out += [dec(fmt, "0"), dec(fmt, repr(0.1 + i / 1024)),
                    dec(fmt, "0.5"), dec(fmt, "0")]
    return out


def manifest():
    m = {}
    text = (PROGRAMS / "MANIFEST").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            h, name = line.split()
            m[name] = h
    return m


def ode_program(base, fmt, man):
    name = f"{base}-{fmt}"
    src = (PROGRAMS / f"{name}.cfta").read_text(encoding="utf-8")
    img = asm.assemble(src, name)
    check(cert.sha256(img) == man.get(name + ".cftp"),
          f"{name}: the image assembled here is programs/MANIFEST's "
          f"({cert.sha256(img)[:16]}...)")
    bank = (PROGRAMS / f"{name}.classic.bank").read_bytes()
    names = [n for n, _ in gen_odes.bank_values(base, FORMATS[fmt])]
    h_slots = tuple(i for i, n in enumerate(names) if n in H_NAMES)
    lanes, S = SIZES[base]
    init = ensemble(base, fmt, lanes)
    steps = gen_odes.STEPS[base]
    runs = [RunSpec("main", img, bank, init, fmt, S, steps,
                    params=(("ensemble-spread", 64), ("members", lanes))),
            RunSpec("half-step", img, halved(fmt, bank, h_slots), init, fmt,
                    2 * S, steps, params=(("members", lanes),),
                    h_slots=h_slots)]
    if fmt == "fp64":
        # one format wider, as test_cert.py builds it: the source's format
        # line changed, the bank and the start exactly widened
        line = ".format   fp64"
        assert src.count(line) == 1, f"{name}: no single '{line}' line"
        img128 = asm.assemble(src.replace(line, ".format   fp128"),
                              f"{base}-fp128")
        bank_w = cert.state_bytes("fp128", [cert.widen("fp64", x) for x in
                                            cert.state_values("fp64", bank)])
        runs.append(RunSpec("wider", img128, bank_w,
                            [cert.widen("fp64", x) for x in init], "fp128", S,
                            steps))
    return Program(name, runs)


def flagstep_program():
    img = asm.assemble(FLAGSTEP, "flagstep")
    init = [dec("fp64", "3"), dec("fp64", "1"), dec("fp64", "3"),
            dec("fp64", "5")]
    return Program("flagstep-fp64",
                   [RunSpec("main", img, b"", init, "fp64", 5, 1)])


def half_init_program(l63):
    """lorenz63 at fp64 (`l63`, the gate's own) with its half-step run
    entered from an initial state of its own: every lane's x a further
    1/128 along, exactly. Every other half-step run in the gate shares run
    0's initial state, so a writer that entered a half-step run from run
    0's --init would pass them all (verifier-C6, 2026-09-28). The
    certificate states a relation that does not hold, and the audit
    refuses it aux-start; the tool is still held to the golden writer's
    bytes for what it was handed."""
    main, half = l63.runs[0], l63.runs[1]
    assert (main.kind, half.kind) == ("main", "half-step")
    lanes = len(main.init) // 3
    other = []
    for i in range(lanes):
        other += [dec("fp64", repr(1 + i / 64 + 1 / 128)), dec("fp64", "1"),
                  dec("fp64", "1")]
    assert other != main.init and len(other) == len(main.init)
    return Program("lorenz63-rk4-fp64-half-init",
                   [main, dataclasses.replace(half, init=other)],
                   audit_refuses="aux-start")


# ---- the tool -------------------------------------------------------------

TOOL = SERVE = None
SALT = None
EXPECT_ID = None


def run_tool(args, env=None):
    e = dict(os.environ)
    e.pop("CFT_SEGRUN_PLANT", None)
    if env:
        e.update(env)
    try:
        r = subprocess.run([str(TOOL)] + [str(a) for a in args],
                           capture_output=True, text=True, env=e,
                           timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return (-1, "", f"segrun_check: the tool ran past {TOOL_TIMEOUT} s "
                        f"and was stopped")
    return r.returncode, r.stdout, r.stderr


def write_inputs(work, prog):
    d = work / "inputs" / prog.name
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for r, spec in enumerate(prog.runs):
        img = d / f"run{r}.cftp"
        img.write_bytes(spec.image)
        bank = None
        if spec.bank:
            bank = d / f"run{r}.bank"
            bank.write_bytes(spec.bank)
        init = d / f"run{r}.init"
        init.write_bytes(cert.state_bytes(spec.fmt, spec.init))
        out.append((img, bank, init))
    return out


def tool_args(prog, paths, out, states, salt_path, device="sw"):
    args = ["--out", out, "--states", states]
    args += ["--salt", salt_path] if salt_path else ["--open"]
    args += ["--device", device]
    for spec, (img, bank, init) in zip(prog.runs, paths):
        args += ["--run", spec.kind]
        if spec.kind == "half-step":
            args += ["--h-slots", ",".join(str(s) for s in spec.h_slots)]
        args += ["--image", img]
        if bank:
            args += ["--bank", bank]
        args += ["--init", init, "--segments", spec.segments,
                 "--steps", spec.steps]
        for n, v in spec.params:
            args += ["--param", f"{n}={v}"]
    return args


# ---- the golden writer -------------------------------------------------

def golden_certificate(prog, chains, salt, identity):
    runs = tuple(cert.certify_run(spec.kind, spec.image, spec.bank, salt, st,
                                  rs, steps=spec.steps,
                                  parameters=spec.params,
                                  h_slots=spec.h_slots,
                                  scratch_depth=DEPTH)
                 for spec, (st, rs) in zip(prog.runs, chains))
    return cert.encode(cert.Certificate(
        "keyed" if salt is not None else "open",
        cert.salt_commitment(salt) if salt is not None else None,
        identity, runs, ()))


def first_difference(a, b):
    la = a.decode("ascii", "replace").split("\n")
    lb = b.decode("ascii", "replace").split("\n")
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"line {i + 1}: the tool's {x[:110]!r}, golden {y[:110]!r}"
    return f"{len(la)} lines against {len(lb)}"


def boundary_file(sdir, r, b):
    return sdir / f"run-{r}-boundary-{b}.bin"


def hold_identity(what, idn, backend):
    rc, out, _ = run_tool(["--build-id"])
    own = out.strip()
    check(rc == 0 and idn.build_id == own,
          f"{what}: build-id is cft_build_id() as the binary prints it",
          f"the certificate says {idn.build_id!r}, --build-id {own!r}")
    if EXPECT_ID is not None:
        check(idn.build_id == EXPECT_ID,
              f"{what}: build-id is the tree's ({EXPECT_ID[:22]}...)",
              f"the certificate says {idn.build_id!r}: a stale binary, or an "
              f"id from somewhere other than the library")
    want = {"software": ("software", "none", "none", "none", 1),
            "remote": ("remote", "unknown", "unknown", "unknown", 1),
            "xrt": EXPECT_XRT}[backend]
    got = (idn.backend, idn.device_xclbin, idn.device_version,
           idn.device_caps, idn.device_tiles)
    check(got == want, f"{what}: backend and device lines are the library's "
          f"answers for a {backend} handle {want}", f"got {got}")


def certify_and_hold(prog, chains, mode, work, device="sw", tag="",
                     may_refuse_load=False):
    """Steps 1 to 6 for one program in one mode. -> (bytes, states dir),
    or None. With may_refuse_load, a device that refuses to load the
    image (program-image) is a NOTE, not a failure: the card leg's
    `flagstep`, which needs features the brief's six programs do not."""
    salt = SALT if mode == "keyed" else None
    what = f"{prog.name} {mode}{tag}"
    stem = work / "out" / f"{prog.name}-{mode}{tag.replace(' ', '-')}"
    stem.parent.mkdir(parents=True, exist_ok=True)
    out, sdir = Path(str(stem) + ".cert"), Path(str(stem) + ".states")
    salt_path = work / "salt.bin" if salt is not None else None
    t0 = time.perf_counter()
    rc, so, se = run_tool(tool_args(prog, PATHS[prog.name], out, sdir,
                                    salt_path, device))
    if may_refuse_load and rc == cert.REFUSALS["program-image"] and \
            "refused program-image: " in se and "cft_program_load" in se:
        print(f"  NOTE  {what}: NOT TESTED - this device refuses the image: "
              f"{se.strip()[-300:]}", flush=True)
        return None
    if not check(rc == 0, f"{what}: cft-segrun exits 0 "
                 f"({time.perf_counter() - t0:.1f} s)",
                 f"rc {rc}: {se.strip()[-400:]}"):
        return None
    data = out.read_bytes()
    try:
        parsed = cert.parse(data, salt=salt)
        ok(f"{what}: the golden reader accepts it ({len(data)} bytes"
           f"{', the salt its commitment' if salt is not None else ''})")
    except cert.Refusal as e:
        bad(f"{what}: the golden reader refuses it: {e}")
        return None
    gold = golden_certificate(prog, chains, salt, parsed.identity)
    check(gold == data, f"{what}: the golden writer, running every segment "
          f"itself from the initial states, writes the same bytes",
          first_difference(data, gold))
    want = sorted(boundary_file(sdir, r, b).name
                  for r, (st, _) in enumerate(chains) for b in range(len(st)))
    have = sorted(os.listdir(sdir)) if sdir.is_dir() else []
    check(have == want, f"{what}: the states directory holds exactly the "
          f"{len(want)} boundary files", f"it holds {have[:6]}...")
    wrong = [(r, b) for r, (st, _) in enumerate(chains)
             for b in range(len(st))
             if not boundary_file(sdir, r, b).is_file()
             or boundary_file(sdir, r, b).read_bytes()
             != cert.state_bytes(prog.runs[r].fmt, st[b])]
    check(not wrong, f"{what}: every boundary file is the golden chain's "
          f"state there, lane-major", f"(run, boundary) {wrong[:4]} differ")
    states = {r: {b: boundary_file(sdir, r, b).read_bytes()
                  for b in range(len(st))
                  if boundary_file(sdir, r, b).is_file()}
              for r, (st, _) in enumerate(chains)}
    progs = {r: (spec.image, spec.bank) for r, spec in enumerate(prog.runs)}
    choose = {r: ("sample", max(1, spec.segments // 2))
              for r, spec in enumerate(prog.runs)}
    if prog.audit_refuses:
        # a relation broken on purpose: the audit must refuse it by its
        # check's name, full and sampled alike (relations come before any
        # re-run)
        for how, kw in (("in full", {}), ("sampled", {"choose": choose})):
            try:
                cert.audit(data, salt, progs, states=states, **kw)
                bad(f"{what}: the golden audit ACCEPTS it {how}, and its "
                    f"relation is broken on purpose")
            except cert.Refusal as e:
                check(e.name == prog.audit_refuses,
                      f"{what}: the golden audit refuses it {how}, "
                      f"{prog.audit_refuses}, as its broken relation must be",
                      f"it says {e.name}: {e.message}")
    else:
        try:
            t0 = time.perf_counter()
            v = cert.audit(data, salt, progs, states=states)
            check([len(x["rerun"]) for x in v.runs] ==
                  [spec.segments for spec in prog.runs],
                  f"{what}: the golden audit ACCEPTS it, every segment of "
                  f"every run re-run from the states the tool wrote "
                  f"({time.perf_counter() - t0:.1f} s)")
        except cert.Refusal as e:
            bad(f"{what}: the golden audit refuses it: {e.name}: "
                f"{e.message}")
        try:
            v = cert.audit(data, salt, progs, states=states, choose=choose)
            ok(f"{what}: the golden audit ACCEPTS a sample of "
               f"{[len(x['rerun']) for x in v.runs]} segments, seed "
               f"{v.runs[0]['seed']}")
        except cert.Refusal as e:
            bad(f"{what}: the golden audit refuses a sample: {e.name}: "
                f"{e.message}")
    hold_identity(what, parsed.identity,
                  "remote" if device.startswith("cft://") else
                  "software" if device == "sw" else "xrt")
    return data, sdir


def runs_part(data):
    """A certificate's body from its `runs` line to `end`: every run
    block, without the identity lines."""
    L = cert.body_of(data).decode("ascii").split("\n")
    return L[next(i for i, x in enumerate(L) if x.startswith("runs ")):]


# ---- the hashes against the page and RFC 2104 ----------------------------

def rfc2104(key, msg):
    """HMAC-SHA-256 written out from RFC 2104 with hashlib alone."""
    if len(key) > 64:
        key = hashlib.sha256(key).digest()
    key = key.ljust(64, b"\x00")
    inner = hashlib.sha256(bytes(x ^ 0x36 for x in key) + msg).digest()
    return hashlib.sha256(bytes(x ^ 0x5C for x in key) + inner).hexdigest()


def hold_ignored():
    """The binary, in both its forms, is ignored by git, so building it
    never makes the next build id untracked=present. .gitignore says
    adding a tool needs a line there as well as in host/Makefile; this
    tool went without it until its own Linux build showed `?? host/
    cft-segrun` (2026-09-28)."""
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse",
                            "--is-inside-work-tree"], capture_output=True,
                           text=True)
    except OSError:
        r = None
    if r is None or r.returncode != 0 or r.stdout.strip() != "true":
        skip("git ignores host/cft-segrun", "this tree is in no git "
             "repository")
        return
    for p in ("host/cft-segrun", "host/cft-segrun.exe"):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", p])
        check(r.returncode == 0, f"git ignores {p}, so a build of it leaves "
              f"the next build id clean", f"git check-ignore exits "
              f"{r.returncode}")


def hold_hashes(work):
    print("== 7. the hashes: the page's test vectors, and every tag against "
          "RFC 2104", flush=True)
    text = DOC.read_text(encoding="utf-8")
    at = text.index("<!-- the test vectors -->")
    block = re.search(r"```[a-z]*\n(.*?)```", text[at:], re.S).group(1)
    rows = dict(ln.split(None, 1) for ln in block.strip().split("\n"))
    d = work / "vectors"
    d.mkdir(parents=True, exist_ok=True)
    (d / "salt").write_bytes(bytes.fromhex(rows["salt"]))
    (d / "state").write_bytes(bytes.fromhex(rows["state-bytes"]))
    (d / "stream").write_bytes(bytes.fromhex(rows["stream-a-bytes"]))
    for row, args in (
            ("salt-commitment", ["--hash", "commitment", "--salt", d / "salt"]),
            ("state-hash", ["--hash", "state", d / "state", "--salt",
                            d / "salt"]),
            ("open-state-hash", ["--hash", "state", d / "state", "--open"]),
            ("stream-a-hash", ["--hash", "stream-a", d / "stream", "--salt",
                               d / "salt"])):
        rc, out, err = run_tool(args)
        check(rc == 0 and out.strip() == rows[row],
              f"the page's {row}: {rows[row][:16]}...",
              f"cft-segrun --hash says {out.strip() or err.strip()!r}")
    # every tag, keyed and open, on bytes the page does not print
    salt = hashlib.sha256(b"segrun_check: a salt for the tag check").digest()
    body = bytes(range(256)) * 3 + b"\x00\x01"
    (d / "salt2").write_bytes(salt)
    (d / "body").write_bytes(body)
    tags = {"state": b"cft-certificate 1 state\x00",
            "stream-a": b"cft-certificate 1 stream a\x00",
            "stream-b": b"cft-certificate 1 stream b\x00",
            "stream-c": b"cft-certificate 1 stream c\x00"}
    seen = set()
    for kind, tag in tags.items():
        rc, out, _ = run_tool(["--hash", kind, d / "body", "--salt",
                               d / "salt2"])
        check(rc == 0 and out.strip() == rfc2104(salt, tag + body),
              f"{kind}, keyed: HMAC-SHA-256 of its tag, the NUL and the bytes")
        rc2, out2, _ = run_tool(["--hash", kind, d / "body", "--open"])
        check(rc2 == 0 and out2.strip()
              == hashlib.sha256(tag + body).hexdigest(),
              f"{kind}, open: SHA-256 of its tag, the NUL and the bytes")
        seen |= {out.strip(), out2.strip()}
    rc, out, _ = run_tool(["--hash", "commitment", "--salt", d / "salt2"])
    check(rc == 0 and out.strip()
          == rfc2104(salt, b"cft-certificate 1 salt"),
          "the salt commitment: HMAC of the tag alone, no NUL")
    check(len(seen) == 8, "eight tags and modes, eight different hashes")


# ---- the refusals -----------------------------------------------------------

REFUSED = re.compile(r"cft-segrun: refused ([a-z-]+):")


def golden_write(runs_specs, salt=None):
    """The golden writer on RunSpecs: run_chain, certify_run, encode."""
    runs = []
    for spec in runs_specs:
        st, rs = cert.run_chain(spec.image, spec.bank, spec.init,
                                spec.segments, scratch_depth=DEPTH)
        runs.append(cert.certify_run(spec.kind, spec.image, spec.bank, salt,
                                     st, rs, steps=spec.steps,
                                     parameters=spec.params,
                                     h_slots=spec.h_slots,
                                     scratch_depth=DEPTH))
    return cert.encode(cert.Certificate(
        "keyed" if salt is not None else "open",
        cert.salt_commitment(salt) if salt is not None else None,
        cert.Identity(), tuple(runs), ()))


def golden_flags(spec, flags):
    """The golden writer handed one segment whose flag word is `flags`,
    as a producer's own results (certify_run takes them)."""
    st, rs = cert.run_chain(spec.image, spec.bank, spec.init, 1,
                            scratch_depth=DEPTH)
    run = cert.certify_run("main", spec.image, spec.bank, None, st,
                           [(flags, rs[0][1])], steps=spec.steps,
                           scratch_depth=DEPTH)
    return cert.encode(cert.Certificate("open", None, cert.Identity(),
                                        (run,), ()))


def hold_refusals(work, l63, flag):
    print("== 8. the refusals: each by its name and exit code; the page's "
          "names, the golden writer's for the same defect", flush=True)
    d = work / "refusals"
    d.mkdir(parents=True, exist_ok=True)
    main = l63.runs[0]
    fmt = main.fmt
    img, bank = main.image, main.bank
    init = cert.state_bytes(fmt, main.init)
    fimg, finit = flag.runs[0].image, cert.state_bytes(
        "fp64", flag.runs[0].init)

    def f(name, data):
        p = d / name
        p.write_bytes(data)
        return p

    P = {"img": f("l63.cftp", img), "bank": f("l63.bank", bank),
         "init": f("l63.init", init), "fimg": f("flag.cftp", fimg),
         "finit": f("flag.init", finit),
         "salt": f("salt.bin", bytes(range(32)))}
    P["salt31"] = f("salt31.bin", bytes(31))
    P["salt33"] = f("salt33.bin", bytes(33))
    P["bank-short"] = f("bank-short", bank[:-8])
    P["eight"] = f("eight", bytes(8))
    P["img-trunc"] = f("trunc.cftp", img[:-8])
    # the flagstep image with its last word, HALT, made an unknown control
    # code: the header describes the bytes, and the loader refuses them
    bad_ctl = bytearray(fimg)
    assert bad_ctl[-8:-4] == (1 << 31).to_bytes(4, "little"), "HALT last"
    bad_ctl[-8:-4] = ((1 << 31) | 0x7F).to_bytes(4, "little")
    P["img-ctl"] = f("ctl.cftp", bytes(bad_ctl))
    try:
        seq.Program.from_bytes(bytes(bad_ctl))
        bad("the planted control code: the golden loader accepts it, so it "
            "tests nothing")
    except seq.ProgramError:
        pass
    div = asm.assemble((PROGRAMS / "div-fp64.cfta").read_text(
        encoding="utf-8"), "div-fp64")
    P["img-noio"] = f("div.cftp", div)
    inout = asm.assemble(".format   fp64\n.deposits 0\n.scratch  in 2\n"
                         ".scratch  out 1\nldl  r3, 0\nstl  r3, 0\nhalt\n",
                         "in2out1")
    P["img-inout"] = f("inout.cftp", inout)
    depo = asm.assemble(".format   fp64\n.deposits 1\n.scratch  in 1\n"
                        ".scratch  out 1\nldl  r3, 0\ndeposit r3\n"
                        "stl  r3, 0\nhalt\n", "deposits")
    P["img-dep"] = f("dep.cftp", depo)
    P["init-part"] = f("init-part", init[:-8])
    P["init-ragged"] = f("init-ragged", init[:-1])
    P["init-empty"] = f("init-empty", b"")
    half_bank = f("l63.half", l63.runs[1].bank)
    exists = d / "exists"
    exists.mkdir(exist_ok=True)
    # a file already at --out: every refusal must leave it byte for byte
    kept = b"a file that was at --out before the run\n" + bytes(range(256))
    P["existing"] = f("existing.cert", kept)

    def base(out, sdir, image="img", bnk="bank", ini="init", seg="1",
             steps="100", mode=("--salt", P["salt"]), extra=(), runs=None):
        a = ["--out", out, "--states", sdir, *mode]
        if runs is not None:
            return a + list(runs) + list(extra)
        a += ["--run", "main", "--image", P[image]]
        if bnk:
            a += ["--bank", P[bnk]]
        a += ["--init", P[ini], "--segments", seg, "--steps", steps]
        return a + list(extra)

    def spec(**kw):
        s = dict(kind="main", image=img, bank=bank, init=main.init, fmt=fmt,
                 segments=1, steps=100)
        s.update(kw)
        return RunSpec(**s)

    half_run = ["--run", "half-step", "--h-slots", "0,1,2", "--image",
                P["img"], "--bank", half_bank, "--init", P["init"],
                "--segments", "2", "--steps", "100"]
    main_run = ["--run", "main", "--image", P["img"], "--bank", P["bank"],
                "--init", P["init"], "--segments", "1", "--steps", "100"]
    half_spec = spec(kind="half-step", bank=l63.runs[1].bank, segments=2,
                     h_slots=(0, 1, 2))

    # (label, name, the tool's arguments, env, the golden writer's twin)
    cases = [
        ("a 31-byte salt", "salt-length",
         lambda o, s: base(o, s, mode=("--salt", P["salt31"])), None,
         lambda: cert.salt_commitment(bytes(31))),
        ("a 33-byte salt", "salt-length",
         lambda o, s: base(o, s, mode=("--salt", P["salt33"])), None,
         lambda: cert.salt_commitment(bytes(33))),
        ("an image cut short", "program-image",
         lambda o, s: base(o, s, image="img-trunc"), None, None),
        ("an image the loader refuses (an unknown control code)",
         "program-image",
         lambda o, s: base(o, s, image="img-ctl", bnk=None, ini="finit"),
         None, None),
        ("a bank one element short", "program-image",
         lambda o, s: base(o, s, bnk="bank-short"), None,
         lambda: golden_write([spec(bank=bank[:-8])])),
        ("no bank for a BANK_EXT image", "program-image",
         lambda o, s: base(o, s, bnk=None), None,
         lambda: golden_write([spec(bank=b"")])),
        ("a bank for an image that carries its constants", "program-image",
         lambda o, s: base(o, s, image="fimg", bnk="eight", ini="finit"),
         None,
         lambda: golden_write([spec(image=fimg, bank=bytes(8),
                                    init=flag.runs[0].init)])),
        ("no scratch block (div-fp64)", "program-shape",
         lambda o, s: base(o, s, image="img-noio", bnk=None), None,
         lambda: golden_write([spec(image=div, bank=b"", init=[])])),
        ("scratch in 2, out 1", "program-shape",
         lambda o, s: base(o, s, image="img-inout", bnk=None), None,
         lambda: golden_write([spec(image=inout, bank=b"")])),
        ("a program that deposits", "program-shape",
         lambda o, s: base(o, s, image="img-dep", bnk=None), None,
         lambda: golden_write([spec(image=depo, bank=b"")])),
        ("an initial state a lane short of whole", "state-shape",
         lambda o, s: base(o, s, ini="init-part"), None,
         lambda: golden_write([spec(init=main.init[:-1])])),
        ("an initial state that is not whole elements", "state-shape",
         lambda o, s: base(o, s, ini="init-ragged"), None, None),
        # no twin: the golden writer has no name for an empty initial
        # state - cert.run_chain hands seq.run an empty block, and it
        # raises seq.ProgramError (found 2026-09-28; for P1c)
        ("an empty initial state", "state-shape",
         lambda o, s: base(o, s, ini="init-empty"), None, None),
        ("0 segments", "malformed", lambda o, s: base(o, s, seg="0"), None,
         lambda: golden_write([spec(segments=0)])),
        ("0 steps", "malformed", lambda o, s: base(o, s, steps="0"), None,
         lambda: golden_write([spec(steps=0)])),
        ("segments '03'", "malformed", lambda o, s: base(o, s, seg="03"),
         None, None),
        ("segments 2^63", "malformed",
         lambda o, s: base(o, s, seg=str(1 << 63)), None, None),
        ("a half-step run with no h-slots", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             x for x in half_run if x not in ("--h-slots", "0,1,2")]),
         None, lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=())])),
        ("h-slot 512", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             "512" if x == "0,1,2" else x for x in half_run]), None,
         lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=(512,))])),
        ("h-slots 2,1", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             "2,1" if x == "0,1,2" else x for x in half_run]), None,
         lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=(2, 1))])),
        ("h-slots 1,1", "malformed",
         lambda o, s: base(o, s, runs=main_run + [
             "1,1" if x == "0,1,2" else x for x in half_run]), None,
         lambda: golden_write([spec(), dataclasses.replace(
             half_spec, h_slots=(1, 1))])),
        ("a parameter name with a capital", "malformed",
         lambda o, s: base(o, s, extra=["--param", "Spread=1"]), None,
         lambda: golden_write([spec(params=(("Spread", 1),))])),
        ("a parameter value of 2^63", "malformed",
         lambda o, s: base(o, s, extra=["--param", f"n={1 << 63}"]), None,
         lambda: golden_write([spec(params=(("n", 1 << 63),))])),
        ("a parameter named twice", "line-unexpected",
         lambda o, s: base(o, s, extra=["--param", "a=1", "--param", "a=2"]),
         None, lambda: golden_write([spec(params=(("a", 1), ("a", 2)))])),
        ("parameters out of byte order", "line-order",
         lambda o, s: base(o, s, extra=["--param", "a0=1", "--param",
                                        "a-b=2"]),
         None, lambda: golden_write([spec(params=(("a0", 1), ("a-b", 2)))])),
        ("run 0 a half-step run", "malformed",
         lambda o, s: base(o, s, runs=half_run), None,
         lambda: golden_write([half_spec])),
        ("two main runs", "malformed",
         lambda o, s: base(o, s, runs=main_run + main_run), None,
         lambda: golden_write([spec(), spec()])),
        ("no run at all", "malformed", lambda o, s: base(o, s, runs=[]),
         None, lambda: cert.encode(cert.Certificate(
             "open", None, cert.Identity(), (), ()))),
        ("an unknown option", "usage",
         lambda o, s: base(o, s, extra=["--lanes", "3"]), None, None),
        ("no --out", "usage",
         lambda o, s: base(o, s)[2:], None, None),
        ("--salt and --open", "usage",
         lambda o, s: base(o, s, extra=["--open"]), None, None),
        ("neither --salt nor --open", "usage",
         lambda o, s: base(o, s, mode=()), None, None),
        ("a run option before any --run", "usage",
         lambda o, s: ["--image", P["img"]] + base(o, s), None, None),
        ("--run sideways", "usage",
         lambda o, s: base(o, s, runs=["--run", "sideways"]), None, None),
        ("an image file that is not there", "usage",
         lambda o, s: base(o, s, runs=["--run", "main", "--image",
                                       d / "absent.cftp", "--init",
                                       P["init"], "--segments", "1",
                                       "--steps", "1"]), None, None),
        ("--h-slots on the main run", "usage",
         lambda o, s: base(o, s, extra=["--h-slots", "0"]), None, None),
        ("CFT_SEGRUN_PLANT=bogus", "usage", lambda o, s: base(o, s),
         {"CFT_SEGRUN_PLANT": "bogus"}, None),
        # the two small modes' own
        ("--hash with a kind there is not", "usage",
         lambda o, s: ["--hash", "sideways", P["init"], "--open"], None,
         None),
        ("--hash state with neither --salt nor --open", "usage",
         lambda o, s: ["--hash", "state", P["init"]], None, None),
        ("--hash commitment with no salt", "usage",
         lambda o, s: ["--hash", "commitment", "--open"], None, None),
        ("--build-id with anything else", "usage",
         lambda o, s: ["--build-id", "--open"], None, None),
        ("a device that does not open", "device",
         lambda o, s: base(o, s, extra=["--device", d / "absent.xclbin"]),
         None, None),
        ("a device that cannot read its flags (planted)", "device",
         lambda o, s: base(o, s), {"CFT_SEGRUN_PLANT": "flags-unreadable"},
         None),
        # these two are refused at the first segment, after boundary 0 was
        # written: no certificate, and the one boundary file left, said so
        ("a flag word the library left unwritten (planted)", "device",
         lambda o, s: base(o, s), {"CFT_SEGRUN_PLANT": "flags-unwritten"},
         None),
        ("a flag word past the five sticky flags (planted)", "malformed",
         lambda o, s: base(o, s), {"CFT_SEGRUN_PLANT": "flags-wide"},
         lambda: golden_flags(spec(), 16 | 0x20)),
        ("a states directory that already exists", "output",
         lambda o, s: base(o, exists), None, None),
        ("a certificate in a directory that is not there", "output",
         lambda o, s: base(d / "absent" / "c.cert", s), None, None),
        # P3b (verifier-C6's findings): no run overwrites a file it did not
        # make; the certificate can never be a boundary file; and a run the
        # process cannot hold is refused by name before anything runs
        ("an --out that is there already", "output",
         lambda o, s: base(P["existing"], s), None, None),
        ("an --out inside --states, named as boundary 0", "output",
         lambda o, s: base(s / "run-0-boundary-0.bin", s), None, None),
        ("run 1 asking 2^63 - 1 segments, run 0 one", "memory",
         lambda o, s: base(o, s, runs=main_run + [
             str((1 << 63) - 1) if x == "2" else x for x in half_run]),
         None, None),
        ("10^12 segments", "memory",
         lambda o, s: base(o, s, seg=str(10 ** 12)), None, None),
        # verifier-C7's Windows findings: an existing directory at --out
        # was refused as "Permission denied", and the null device accepted
        ("an --out that is a directory there already", "output",
         lambda o, s: base(exists, s), None, None),
        ("the null device as --out", "output",
         lambda o, s: base(os.devnull, s), None, None),
    ]
    # refused by a check the tool makes only after the outputs are made:
    # the library's loader, which needs the device, opened after them
    AFTER_OUTPUTS = {"an image the loader refuses (an unknown control code)"}

    def survive(i, label, name, argf, env):
        """The same refusal with a file already at --out, which it must
        leave byte for byte. A defect found only after the outputs are
        made - the device, the library's loader, the flag words, the states
        directory - is met first by the --out that is there, refused
        `output`. A case whose command line has no --out of its own to give
        it (none at all, the two small modes, or an --out the case fixes)
        has nothing to keep, and is not counted."""
        keep, sdir2 = d / f"case{i}.kept", d / f"case{i}.states2"
        args2 = [str(a) for a in argf(keep, sdir2)]
        if "--out" not in args2 or \
                args2[args2.index("--out") + 1] != str(keep):
            return
        keep.write_bytes(kept)
        rc2, _, se2 = run_tool(args2, env)
        m2 = REFUSED.search(se2)
        got2 = m2.group(1) if m2 else None
        late = (name in ("device", "output") or label in AFTER_OUTPUTS
                or (env or {}).get("CFT_SEGRUN_PLANT", "").startswith(
                    "flags-"))
        want2 = "output" if late else name
        code2 = cert.REFUSALS.get(want2, TOOL_OWN.get(want2))
        same = keep.is_file() and keep.read_bytes() == kept
        check(rc2 == code2 and got2 == want2 and same and not sdir2.exists(),
              f"  and a file already at --out comes through it byte for "
              f"byte, refused {want2}: {label}",
              f"exit {rc2}, {got2 or 'no refusal named'}, the file "
              f"{'kept' if same else 'CHANGED or gone'}, states "
              f"{'left' if sdir2.exists() else 'none'}: "
              f"{se2.strip()[-200:]}")

    # what a refusal's words must begin with (a regular expression), where
    # the name alone would not show the check it was made by: an --out
    # inside --states must be refused as the --out it is, not later as a
    # boundary file that collides with it; a run too long to hold, by what
    # is held before any segment runs - run 1 by its own size, before run
    # 0 has run. 10^12 segments are refused by the boundary hashes'
    # allocation where memory is not overcommitted (the Windows desktop),
    # and by the certificate's text, 200 TB, past what a process can
    # address, where it is (WSL cft2204, vm.overcommit_memory 1).
    says = {"an --out that is there already": r"--out .+ is there already",
            "an --out inside --states, named as boundary 0":
                r"--out .+ cannot be created",
            "run 1 asking 2^63 - 1 segments, run 0 one":
                r"run 1: \d+ segments need more memory than this process "
                r"can address",
            "10^12 segments":
                r"(run 0: \d+ x 65 bytes for the boundary hashes|\d+ x 1 "
                r"bytes for the certificate's text) could not be had; .*"
                r"before anything is made",
            "an --out that is a directory there already":
                r"--out .+ is there already",
            "the null device as --out":
                r"--out .+ (is not a file|is there already)"}
    for i, (label, name, argf, env, twin) in enumerate(cases):
        out, sdir = d / f"case{i}.cert", d / f"case{i}.states"
        args = argf(out, sdir)
        rc, so, se = run_tool(args, env)
        m = REFUSED.search(se)
        got = m.group(1) if m else None
        code = cert.REFUSALS.get(name, TOOL_OWN.get(name))
        check(rc == code and got == name,
              f"refused {name} (exit {code}): {label}",
              f"exit {rc}, {got or 'no refusal named'}: {se.strip()[-240:]}")
        if label in says:
            words = se[m.end():].lstrip() if m else ""
            check(re.match(says[label], words) is not None,
                  f"  and its words begin {says[label]!r}: {label}",
                  f"they are {words.strip()[:200]!r}")
        if env and env["CFT_SEGRUN_PLANT"] in ("flags-unwritten",
                                                "flags-wide"):
            files = sorted(os.listdir(sdir)) if sdir.is_dir() else None
            check(not out.exists() and files == ["run-0-boundary-0.bin"]
                  and "the 1 boundary state file written so far is left" in se,
                  f"  and no certificate; boundary 0, written before the "
                  f"refusal, left and said so: {label}",
                  f"certificate {out.exists()}, states {files}")
        else:
            left = [p.name for p in (out, sdir) if p.exists()]
            if name == "output" and label.startswith("a states directory"):
                left = [p.name for p in (out,) if p.exists()]
            check(not left, f"  and nothing left behind: {label}",
                  f"left {left}")
        survive(i, label, name, argf, env)
        if twin is not None:
            try:
                twin()
                bad(f"  the golden writer ACCEPTS {label}, which the tool "
                    f"refuses as {name}")
            except cert.Refusal as e:
                check(e.name == name, f"  the golden writer refuses {label} "
                      f"by the same name", f"it says {e.name}: {e.message}")
            except Exception as e:      # noqa: BLE001 - reported, not raised
                bad(f"  the golden writer has no name for {label}: "
                    f"{type(e).__name__}: {e}")
    check(not (d / "absent").exists(), "a refused --out made no directory")
    # read only if it is there: a tool that removed it fails here by name,
    # and the gate goes on to the remote leg and removes its work directory
    # (verifier-C7's plant F crashed this line at 4eed552)
    check(P["existing"].is_file() and P["existing"].read_bytes() == kept,
          "the file at --out in 'an --out that is there already' is as it "
          "was, byte for byte",
          "it is CHANGED" if P["existing"].is_file() else "it is GONE")


# ---- memory: what a run costs, and what the trial costs --------------------

# flagstep at fp64: 16 bytes a lane, so 1,048,560 bytes of state - 16
# short of 1 MiB, so that the tool reads each initial state into a buffer
# of exactly 1 MiB
PEAK_LANES = 65535


def read_buffer(n):
    """What cft-segrun's read_file holds an n-byte file in: 64 KiB,
    doubled until the file's bytes and its end both fit."""
    cap = 1 << 16
    while cap <= n:
        cap *= 2
    return cap


class Unmeasured(Exception):
    """This host cannot take the measurement: named NOT TESTED, never a
    failure of the tool and never a crash of the gate."""


class Unwritten(Exception):
    """The run did not write its certificate under all the memory the
    measurement may give it: the tool's failure, by name."""


def tool_env(env):
    e = dict(os.environ)
    e.pop("CFT_SEGRUN_PLANT", None)
    if env:
        e.update(env)
    return e


def peak_commit(args, env=None):
    """Windows: the run's peak commit (PeakPagefileUsage), read from its
    process handle once it has exited. -> (rc, stderr, bytes)"""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.K32GetProcessMemoryInfo.argtypes = [
            wt.HANDLE, ctypes.POINTER(Counters), wt.DWORD]
        k32.K32GetProcessMemoryInfo.restype = wt.BOOL
        p = subprocess.Popen([str(TOOL)] + [str(a) for a in args],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, env=tool_env(env))
    except (ImportError, AttributeError, OSError, ValueError) as e:
        raise Unmeasured(f"the peak commit cannot be read here: "
                         f"{type(e).__name__}: {e}")
    try:
        _, se = p.communicate(timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        p.kill()
        p.communicate()
        return -1, f"stopped after {TOOL_TIMEOUT} s", 0
    c = Counters()
    c.cb = ctypes.sizeof(c)
    if not k32.K32GetProcessMemoryInfo(int(p._handle), ctypes.byref(c),
                                       c.cb):
        raise Unmeasured(f"GetProcessMemoryInfo failed "
                         f"({ctypes.get_last_error()})")
    return p.returncode, se, c.PeakPagefileUsage


def least_address_space(argf, d, tag, env=None, step=4096):
    """Linux: the least address space - RLIMIT_AS, verifier-C7's `ulimit
    -v` - under which the run writes its certificate, to `step` bytes:
    doubled from 16 MiB until it writes, then bisected. Only the soft
    limit is set, and never past the hard limit this process has, which
    an unprivileged process may not raise (verifier-C7 ran the gate as
    `nobody` under a hard limit of about 8 GB: the 16 GiB this asked for
    at eb2d1ae stopped it with a traceback). -> bytes; Unmeasured when
    the hard limit stops the measurement, Unwritten when 16 GiB does not
    let the run write."""
    try:
        import resource
        hard = resource.getrlimit(resource.RLIMIT_AS)[1]
    except (ImportError, OSError, ValueError) as e:
        raise Unmeasured(f"RLIMIT_AS cannot be read here: {e}")
    cap = 1 << 34
    if hard != resource.RLIM_INFINITY and hard < cap:
        cap = hard
    n = [0]
    last = [""]

    def ok(limit):
        n[0] += 1
        out, sdir = d / f"{tag}{n[0]}.cert", d / f"{tag}{n[0]}.states"

        def lim():
            resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
        try:
            r = subprocess.run([str(TOOL)] + [str(a) for a in
                                              argf(out, sdir)],
                               capture_output=True, text=True,
                               preexec_fn=lim, env=tool_env(env),
                               timeout=TOOL_TIMEOUT)
            good, last[0] = r.returncode == 0, r.stderr
        except subprocess.TimeoutExpired:
            good, last[0] = False, f"stopped after {TOOL_TIMEOUT} s"
        except (subprocess.SubprocessError, OSError, ValueError) as e:
            raise Unmeasured(f"the tool cannot be started under an address-"
                             f"space limit here: {type(e).__name__}: {e}")
        finally:
            if out.exists():
                out.unlink()
            shutil.rmtree(sdir, ignore_errors=True)
        return good

    lo, hi = 0, min(1 << 24, cap)
    while not ok(hi):
        if hi >= cap and cap < 1 << 34:
            raise Unmeasured(f"the run does not write its certificate under "
                             f"{hi} bytes, this process's hard address-"
                             f"space limit: {last[0].strip()[-200:]}")
        if hi >= cap:
            raise Unwritten(f"not even under {hi} bytes: "
                            f"{last[0].strip()[-240:]}")
        lo, hi = hi, min(hi * 2, cap)
    while hi - lo > step:
        mid = (lo + hi) // 2 // step * step
        if mid <= lo:
            break
        if ok(mid):
            hi = mid
        else:
            lo = mid
    return hi


def kib(n):
    return f"{n / 1024:,.0f} KiB"


def hold_peak(work, flag):
    """verifier-C7's regressions, held.
    4eed552 held every run's two states and streams at once, where
    99f1b43 held one run's: a main run and two half-step runs must cost
    what the main run alone does, and no more than the two further runs'
    inputs beside it and one state to spare. Measured as the platform
    measures a process: its peak commit on Windows, and on Linux the least
    address space it writes its certificate in.
    eb2d1ae's trial took its pieces under 64 KiB from the C library's heap
    and left the heap bigger, so the runs needed up to 40 KiB more than
    99f1b43's: the trial must cost the runs nothing, to the page. Held on
    Linux, where the least address space is the same run after run; on
    Windows, identical runs' peak commit differs by several pages, so
    there it is NOT TESTED."""
    print("== 10. memory: a run beside the main run costs its own inputs, "
          "and the trial costs the runs nothing", flush=True)
    d = work / "peak"
    d.mkdir(parents=True, exist_ok=True)
    img = flag.runs[0].image
    lane = list(flag.runs[0].init[:2])
    pi = d / "flag.cftp"
    pi.write_bytes(img)
    inits = {}
    for lanes in (PEAK_LANES, 1, 16):
        inits[lanes] = d / f"flag-{lanes}.init"
        inits[lanes].write_bytes(cert.state_bytes("fp64", lane * lanes))
    salt = d / "salt.bin"
    salt.write_bytes(bytes(range(32)))

    def argf(lanes, segments, n_half, keyed=False):
        pn = inits[lanes]

        def f(out, sdir):
            a = ["--out", out, "--states", sdir,
                 *(("--salt", salt) if keyed else ("--open",)),
                 "--run", "main", "--image", pi, "--init", pn,
                 "--segments", str(segments), "--steps", "1"]
            for _ in range(n_half):
                a += ["--run", "half-step", "--h-slots", "0", "--image", pi,
                      "--init", pn, "--segments", str(2 * segments),
                      "--steps", "1"]
            return a
        return f

    linux = sys.platform.startswith("linux")
    what_run = "what a run beside the main run costs"
    try:
        # 1. a run's own working set: one run against three
        shapes = (("the main run alone", 0),
                  ("the main run and two half-step runs", 2))
        vals = []
        if os.name == "nt":
            how = "peak commit"
            for label, k in shapes:
                out, sdir = d / f"w{k}.cert", d / f"w{k}.states"
                rc, se, pk = peak_commit(argf(PEAK_LANES, 1, k)(out, sdir))
                if not check(rc == 0, f"{label}, {PEAK_LANES} lanes: "
                             f"written, and its peak commit read",
                             f"rc {rc}: {se.strip()[-240:]}"):
                    return
                vals.append(pk)
        elif linux:
            how = "least address space (ulimit -v)"
            for label, k in shapes:
                try:
                    vals.append(least_address_space(
                        argf(PEAK_LANES, 1, k), d, f"l{k}-", step=1 << 16))
                except Unwritten as e:
                    bad(f"{label}, {PEAK_LANES} lanes: written, under a "
                        f"limit found by bisection - {e}")
                    return
                ok(f"{label}, {PEAK_LANES} lanes: written, under a limit "
                   f"found by bisection")
        else:
            raise Unmeasured(f"no way to measure a process's peak here "
                             f"({sys.platform})")
        one, three = vals
        inputs = 2 * (read_buffer(PEAK_LANES * 16) + read_buffer(len(img)))
        state = PEAK_LANES * 16
        check(three - one <= inputs + state,
              f"{how}: the main run alone {kib(one)}, with two half-step "
              f"runs {kib(three)} - {kib(three - one)} more, within the two "
              f"runs' inputs ({kib(inputs)}) and one state ({kib(state)})",
              f"{kib(three - one)} more, past {kib(inputs + state)}: a run "
              f"holds a working set of its own beside the others' (4eed552 "
              f"held every run's states at once; verifier-C7)")
    except Unmeasured as e:
        skip(what_run, f"NOT TESTED here - {e}")

    # 2. the trial's cost to the runs, to the page: the least address
    # space with the trial and with its allocations skipped (the
    # instrument), in two small shapes verifier-C7 found it in
    trial_shapes = (
        ("1 lane, open, a main run of 100 segments and a half-step run "
         "of 200", argf(1, 100, 1)),
        ("16 lanes, keyed, a main run of 30 segments and two half-step "
         "runs of 60", argf(16, 30, 2, keyed=True)))
    what_trial = "what the trial costs the runs, to the page"
    if not linux:
        skip(what_trial, "NOT TESTED here - " + (
             "identical runs' peak commit differs by several pages on "
             "Windows, so a page is below what it can see; held on Linux"
             if os.name == "nt" else
             f"no way to measure a process's address space here "
             f"({sys.platform})"))
        return
    try:
        for i, (label, f) in enumerate(trial_shapes):
            try:
                with_trial = least_address_space(f, d, f"t{i}-")
                without = least_address_space(
                    f, d, f"s{i}-", env={"CFT_SEGRUN_PLANT": "trial-skipped"})
            except Unwritten as e:
                bad(f"what the trial costs the runs ({label}): the run "
                    f"written under a limit found by bisection - {e}")
                continue
            check(with_trial <= without,
                  f"least address space with the trial {kib(with_trial)}, "
                  f"with its allocations skipped {kib(without)}: the trial "
                  f"costs the runs nothing ({label})",
                  f"the trial costs the runs {kib(with_trial - without)} - "
                  f"it has left the heap bigger (eb2d1ae's pieces under "
                  f"64 KiB from calloc; verifier-C7)")
    except Unmeasured as e:
        skip(what_trial, f"NOT TESTED here - {e}")


# ---- the remote leg ---------------------------------------------------------

def hold_remote(work, legs):
    """`legs`: (program, its golden chains, its keyed software certificate)
    for each program certified through the server - lorenz63, whose every
    segment is flags 16 and STATUS 0, and flagstep, whose are not, so that
    a flag word or STATUS lost on the way back from a server is seen."""
    print("== 9. through a loopback cft-serve: the page's remote rule, and "
          "the same chains", flush=True)
    rd = work / "remote"
    rd.mkdir(parents=True, exist_ok=True)
    port_file, pid_file = rd / "port", rd / "pid"
    log = open(rd / "serve.log", "w")
    proc = subprocess.Popen([str(SERVE), "--port", "0", "--port-file",
                             str(port_file), "--pid-file", str(pid_file),
                             "--max-conns", str(len(legs))],
                            stdout=log, stderr=subprocess.STDOUT)
    print(f"  cft-serve pid {proc.pid}", flush=True)
    try:
        port = None
        deadline = time.time() + 30
        while time.time() < deadline and proc.poll() is None:
            if port_file.is_file() and port_file.read_text().strip():
                port = int(port_file.read_text().split()[0])
                break
            time.sleep(0.1)
        if not check(port is not None, "cft-serve reports its port",
                     f"exit {proc.poll()}"):
            return
        for prog, chains, sw_data in legs:
            res = certify_and_hold(prog, chains, "keyed", work,
                                   device=f"cft://127.0.0.1:{port}",
                                   tag=" remote")
            if res is None:
                continue
            check(runs_part(res[0]) == runs_part(sw_data),
                  f"{prog.name} keyed remote: every run block, byte for "
                  f"byte, the software backend's")
    finally:
        if proc.poll() is None:
            proc.terminate()              # by PID: this child and no other
            try:
                proc.wait(10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(10)
        log.close()
        print(f"  cft-serve pid {proc.pid} stopped (exit {proc.returncode})",
              flush=True)


# ---- main -------------------------------------------------------------------

PATHS = {}
EXPECT_XRT = None
# The scratch depth the golden writer runs at (revision 7): the DEVICE's,
# read out of the CAPS2 its expected identity names (cert.scratch_depth_of,
# which is also what the audit re-runs at), or the software backend's 256.
# Every program below names only static slots under 256 - the ODE rows'
# highest is lorenz96's 200 - so their chains are the same bytes at any
# depth that holds them; the golden writer takes the device's anyway, so a
# program that indexed past 256 could not pass here by computing another
# machine's answer.
DEPTH = seq.SCRATCH_D


def main():
    global TOOL, SERVE, SALT, EXPECT_ID, EXPECT_XRT, DEPTH
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tool", required=True, help="the cft-segrun binary")
    ap.add_argument("--serve", help="cft-serve, for the remote leg")
    ap.add_argument("--keep", help="write everything here and keep it")
    ap.add_argument("--salt-hex", help="the keyed salt (default: drawn "
                    "from the operating system and printed)")
    ap.add_argument("--device", default="sw",
                    help="make the certificates on this xclbin (the card "
                    "leg, hw/card-segrun.sh); each is also made on the "
                    "software backend and its run blocks compared")
    ap.add_argument("--expect-xclbin", help="with --device: the image's "
                    "SHA-256, measured apart from the library (sha256sum)")
    ap.add_argument("--expect-version", help="with --device: VERSION, 8 hex")
    ap.add_argument("--expect-caps", help="with --device: CAPS [CAPS2], "
                    "8 hex each")
    ap.add_argument("--expect-tiles", type=int, help="with --device: tiles")
    ap.add_argument("--no-wider", action="store_true",
                    help="no wider runs: for a device without fp128")
    ap.add_argument("--programs", help="certify only these, by name, "
                    "comma-separated (the card leg's negative control)")
    args = ap.parse_args()
    TOOL = Path(args.tool).resolve()
    SERVE = Path(args.serve).resolve() if args.serve else None
    if not TOOL.is_file():
        sys.exit(f"segrun_check: {TOOL} is not built (make -C host "
                 f"cft-segrun)")
    SALT = bytes.fromhex(args.salt_hex) if args.salt_hex else os.urandom(32)
    EXPECT_ID = os.environ.get("CFT_EXPECT_BUILD_ID") or None
    card = args.device != "sw"
    if card:
        need = (args.expect_xclbin, args.expect_version, args.expect_caps,
                args.expect_tiles)
        if any(x is None for x in need):
            sys.exit("segrun_check: --device takes --expect-xclbin, "
                     "--expect-version, --expect-caps and --expect-tiles, "
                     "each measured apart from this tool")
        EXPECT_XRT = ("xrt", args.expect_xclbin, args.expect_version,
                      tuple(args.expect_caps.split()), args.expect_tiles)
        DEPTH = cert.scratch_depth_of(
            cert.Identity(device_caps=tuple(args.expect_caps.split())))
        print(f"  the golden writer at {DEPTH} scratch slots a lane, the "
              f"device's (CAPS2)", flush=True)
    work = Path(args.keep).resolve() if args.keep else \
        Path(tempfile.mkdtemp(prefix="segrun-check-"))
    work.mkdir(parents=True, exist_ok=True)
    (work / "salt.bin").write_bytes(SALT)
    t_all = time.perf_counter()
    print(f"segrun_check: {TOOL}", flush=True)
    print(f"  keyed salt {SALT.hex()} (reproduce with --salt-hex)", flush=True)
    print(f"  work in {work}", flush=True)
    if EXPECT_ID is None:
        skip("the build-id line held to the tree's id",
             "CFT_EXPECT_BUILD_ID is not set (make -C host segruntest sets "
             "it)")

    print("== the binary, ignored by git", flush=True)
    hold_ignored()
    print("== the programs", flush=True)
    man = manifest()
    programs = [ode_program(b, f, man) for b in SIZES for f in
                ("fp64", "fp256")]
    if args.no_wider:
        print("  NOTE  --no-wider: no fp128 run beside the fp64 programs",
              flush=True)
        for p in programs:
            p.runs = [r for r in p.runs if r.kind != "wider"]
    flag = flagstep_program()
    programs.append(flag)
    programs.append(half_init_program(
        next(p for p in programs if p.name == "lorenz63-rk4-fp64")))
    chains = {}
    for prog in programs:
        PATHS[prog.name] = write_inputs(work, prog)
        t0 = time.perf_counter()
        chains[prog.name] = [cert.run_chain(s.image, s.bank, s.init,
                                            s.segments, scratch_depth=DEPTH)
                             for s in prog.runs]
        shape = ", ".join(
            f"{s.kind} {s.fmt} "
            f"{len(st[0]) // seq.Program.from_bytes(s.image).n_scratch_in}"
            f" lanes x {s.segments}"
            for s, (st, _) in zip(prog.runs, chains[prog.name]))
        print(f"  {prog.name}: {shape}; the golden chains in "
              f"{time.perf_counter() - t0:.1f} s", flush=True)
    fl = [x[0] for x in chains[flag.name][0][1]]
    stt = [x[1] for x in chains[flag.name][0][1]]
    check(fl == FLAGSTEP_FLAGS and stt == FLAGSTEP_STATUS,
          f"flagstep's segments raise flags {FLAGSTEP_FLAGS} and STATUS "
          f"{FLAGSTEP_STATUS} in the golden model",
          f"flags {fl}, STATUS {stt}")

    sw_keyed = {}
    only = set(args.programs.split(",")) if args.programs else None
    if only and not only <= {p.name for p in programs}:
        sys.exit(f"segrun_check: --programs names "
                 f"{sorted(only - {p.name for p in programs})}, which are not "
                 f"programs here: {[p.name for p in programs]}")
    for prog in programs:
        if only and prog.name not in only:
            continue
        made = {}
        for mode in ("keyed", "open"):
            where = f" on {args.device}" if card else ""
            print(f"== {prog.name}, {mode}{where}", flush=True)
            res = certify_and_hold(prog, chains[prog.name], mode, work,
                                   device=args.device,
                                   tag=" card" if card else "",
                                   may_refuse_load=card and prog is flag)
            if res:
                made[mode] = res[0]
        if not card:
            if "keyed" in made:
                sw_keyed[prog.name] = made["keyed"]
            continue
        if "keyed" not in made:
            continue
        # the card's chain against the software backend's: the same
        # program, inputs and salt, made again on sw
        salt_path = work / "salt.bin"
        stem = work / "out" / f"{prog.name}-keyed-sw"
        rc, _, se = run_tool(tool_args(prog, PATHS[prog.name],
                                       Path(str(stem) + ".cert"),
                                       Path(str(stem) + ".states"),
                                       salt_path, "sw"))
        if check(rc == 0, f"{prog.name} keyed: made on the software backend "
                 f"too", f"rc {rc}: {se.strip()[-300:]}"):
            sw = Path(str(stem) + ".cert").read_bytes()
            sw_keyed[prog.name] = sw
            check(runs_part(made["keyed"]) == runs_part(sw),
                  f"{prog.name} keyed on the card: every run block, byte for "
                  f"byte, the software backend's")

    hold_hashes(work)
    l63 = next(p for p in programs if p.name == "lorenz63-rk4-fp64")
    hold_refusals(work, l63, flag)
    if SERVE is None:
        if card:
            print("  NOTE  the remote leg is not the card leg's: "
                  "hw/card-identity.sh holds a remote handle with a card "
                  "behind its server", flush=True)
        else:
            skip("the remote leg", "no --serve given")
    elif l63.name in sw_keyed and flag.name in sw_keyed:
        hold_remote(work, [(p, chains[p.name], sw_keyed[p.name])
                           for p in (l63, flag)])
    else:
        bad("the remote leg: a software certificate it compares with was "
            "not made")
    hold_peak(work, flag)

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print(f"segrun_check: {CHECKS} checks, {len(FAILED)} failed, "
          f"{len(SKIPS)} skipped, {time.perf_counter() - t_all:.0f} s",
          flush=True)
    if FAILED:
        for w in FAILED:
            print(f"  FAILED: {w}")
        return 1
    print("SEGRUN CHECK OK" if not SKIPS else
          "SEGRUN CHECK OK, with the skips above named")
    return 0


if __name__ == "__main__":
    sys.exit(main())
