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
     (its seed printed, so a red sample can be drawn again);
  6. the identity lines are the library's: build-id is what the binary's
     own `--build-id` prints and what the tree builds (CFT_EXPECT_BUILD_ID);
     the software backend's device lines are `none` and its tiles 1.
Then:
  7. the page's test vectors through `cft-segrun --hash`, and every tag,
     keyed and open, against an HMAC written here from RFC 2104;
  8. every refusal the tool makes, by its name and exit code, a refusal
     before the run leaving nothing behind; and for each of the page's
     names, the golden writer refusing the same defect by the same name;
  9. with --serve: one certificate through a loopback cft-serve, stopped
     by its PID - backend remote, the device lines the page's remote rule
     gives, and every run block byte for byte the software backend's.

The programs: lorenz63-rk4, lorenz96-rk4 and henonheiles-lf at fp64 and
fp256, each image held to programs/MANIFEST, with its classic bank, a
half-step run beside it (the bank slots that carry h exactly halved,
twice the segments), and at fp64 a wider run - the same source assembled
at fp128 (gen_odes builds none), the bank and the initial state exactly
widened. And `flagstep`, written here: its segments raise flags 20, 0,
1, 0, 20 and STATUS 48, 48, 0, 48, 48. Every ODE segment raises 16 and 0,
so the ODE programs alone cannot tell a writer that drops STATUS, or
writes one segment's flags against another, from one that does not.

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
# "The segment runner"): a command line, a device, an output.
TOOL_OWN = {"usage": 64, "device": 69, "output": 73}

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
; strict image unless c = +0 (bit 5), and every lane still active after
; c = 0 is dropped deposits into none (max_deposits 0, bit 4)
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
    for line in (PROGRAMS / "MANIFEST").read_text(encoding="utf-8").splitlines():
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


# ---- the tool -------------------------------------------------------------

TOOL = SERVE = None
SALT = None
EXPECT_ID = None


def run_tool(args, env=None):
    e = dict(os.environ)
    e.pop("CFT_SEGRUN_PLANT", None)
    if env:
        e.update(env)
    r = subprocess.run([str(TOOL)] + [str(a) for a in args],
                       capture_output=True, text=True, env=e)
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
                                  h_slots=spec.h_slots)
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
                  for b in range(len(st)) if boundary_file(sdir, r, b).is_file()}
              for r, (st, _) in enumerate(chains)}
    progs = {r: (spec.image, spec.bank) for r, spec in enumerate(prog.runs)}
    try:
        t0 = time.perf_counter()
        v = cert.audit(data, salt, progs, states=states)
        check([len(x["rerun"]) for x in v.runs] ==
              [spec.segments for spec in prog.runs],
              f"{what}: the golden audit ACCEPTS it, every segment of every "
              f"run re-run from the states the tool wrote "
              f"({time.perf_counter() - t0:.1f} s)")
    except cert.Refusal as e:
        bad(f"{what}: the golden audit refuses it: {e.name}: {e.message}")
    try:
        choose = {r: ("sample", max(1, spec.segments // 2))
                  for r, spec in enumerate(prog.runs)}
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
                                spec.segments)
        runs.append(cert.certify_run(spec.kind, spec.image, spec.bank, salt,
                                     st, rs, steps=spec.steps,
                                     parameters=spec.params,
                                     h_slots=spec.h_slots))
    return cert.encode(cert.Certificate(
        "keyed" if salt is not None else "open",
        cert.salt_commitment(salt) if salt is not None else None,
        cert.Identity(), tuple(runs), ()))


def golden_flags(spec, flags):
    """The golden writer handed one segment whose flag word is `flags`,
    as a producer's own results (certify_run takes them)."""
    st, rs = cert.run_chain(spec.image, spec.bank, spec.init, 1)
    run = cert.certify_run("main", spec.image, spec.bank, None, st,
                           [(flags, rs[0][1])], steps=spec.steps)
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
    ]
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


# ---- the remote leg ---------------------------------------------------------

def hold_remote(work, prog, chains, sw_data):
    print("== 9. through a loopback cft-serve: the page's remote rule, and "
          "the same chain", flush=True)
    rd = work / "remote"
    rd.mkdir(parents=True, exist_ok=True)
    port_file, pid_file = rd / "port", rd / "pid"
    log = open(rd / "serve.log", "w")
    proc = subprocess.Popen([str(SERVE), "--port", "0", "--port-file",
                             str(port_file), "--pid-file", str(pid_file),
                             "--max-conns", "1"],
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
        res = certify_and_hold(prog, chains, "keyed", work,
                               device=f"cft://127.0.0.1:{port}",
                               tag=" remote")
        if res is None:
            return
        data = res[0]
        check(runs_part(data) == runs_part(sw_data),
              f"{prog.name} keyed remote: every run block, byte for byte, "
              f"the software backend's")
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


def main():
    global TOOL, SERVE, SALT, EXPECT_ID, EXPECT_XRT
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
    chains = {}
    for prog in programs:
        PATHS[prog.name] = write_inputs(work, prog)
        t0 = time.perf_counter()
        chains[prog.name] = [cert.run_chain(s.image, s.bank, s.init,
                                            s.segments) for s in prog.runs]
        shape = ", ".join(
            f"{s.kind} {s.fmt} {len(st[0]) // seq.Program.from_bytes(s.image).n_scratch_in}"
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
            print(f"== {prog.name}, {mode}{' on ' + args.device if card else ''}",
                  flush=True)
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
    elif l63.name in sw_keyed:
        hold_remote(work, l63, chains[l63.name], sw_keyed[l63.name])
    else:
        bad("the remote leg: the software certificate it compares with was "
            "not made")

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
