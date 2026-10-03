# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Section 14 of host/tests/segrun_check.py: cft-segrun's certificate format
version 2 (docs/CERTIFICATES.md, "Version 2"; "The segment runner"), held
to the golden writer, python/cft_golden/cert2.py, which is the authority.

segrun_check.py calls hold_v2(); every other section of that gate holds
version 1, each command line asking for it (`--format-version 1`). This
one gives none, or `--format-version 2`, and holds:

  a. programs certified at version 2 on the software backend, keyed and
     open, each byte for byte the golden writer's - cert2.run_chain (each
     block, each marked lane replayed by the source's definition) and
     certify_run, and encode handed the tool's own header lines, which are
     measurements and statements - with every boundary, block and raw file
     the golden chain's, and the golden audit accepting it, handed the
     sources and blocks, in full and sampled:
       - flagstep with --lane-flags, three lanes whose counters differ, so
         each block is its own; a drift;
       - replaystep, written here with its source: an image that computes
         the source's map and beside it a routine's test, run quiet, which
         marks lane 1 in segment 0 (its value right) and lane 0 in segment
         1 (its last bit wrong); replayed by cftc's compile of the source
         (--replay-image, --replay-bank), `--compiler none`; the golden
         writer replays by the definition, and the bytes must agree;
       - Lorenz-63 compiled by cftc from programs/systems with rho = 29
         and beta = 21/8 (source params, canonical literals "29" and
         "2.625"), a half-step run on the compile's half bank and h-slots,
         a wider-source run (the source at fp128), a wider-source estimate
         and a step-halving one;
       - every header statement given, in the certificate's own spelling
         (signed-fp64's certificate-id with its non-ASCII among them), the
         initial state the shake-box generator's, both privacy defaults
         published, and the run deeper than 256 (--scratch-depth);
  b. what the tool measures, against the golden writer's own functions on
     this host: host-os with and without its version, host-arch; the
     profile and language lines against profile.py and lang/version.py;
     `writer cft-segrun <build-id>`, `writer-runtime none`; the software
     backend's four device lines `none`; the times in their spelling and
     order; the environment exactly the writer's list's variables that are
     set, one set empty left out; and segrun.c's table of names held to
     cert2.ENVIRONMENT_NAMES, so a variable joins it with the code;
  c. one run's version-1 and version-2 certificates carrying the same
     state and stream hashes (the contract's sentence);
  d. a source param's literal: manifests whose param_overrides carry
     values chosen at every edge of lang.constants.literal - short
     decimals positional and with exponents at 10^-6 and 10^20, 24
     significant digits and 25, dyadic values long enough for a
     hexadecimal significand, p/q - each line the golden writer's
     canonical_literal of the value;
  e. the issuer-key's decoding: the published test key and RFC 8032's
     keys accepted, the eight keys of small order `signer` and the six
     encodings of no point `malformed` (python/tests/test_ed25519.py's
     vectors), each as the golden writer's read-back names it;
  f. every refusal version 2 adds, by its name and exit code, a refusal
     before anything runs leaving nothing behind and one at a segment
     leaving the files it wrote and saying so, beside a control that is
     written; the golden writer's name for the same defect where it has
     one;
  g. with --serve: flagstep with its blocks and replaystep with its
     replays through a loopback cft-serve - the device lines `unknown`,
     every run block the software backend's;
  h. on a card (--device): a version-2 certificate made on the tile, its
     device lines filled from the card (not `none`), its serial withheld
     until published, its run blocks the software backend's; and the
     per-lane block refused by name, which no revision-7 tile publishes.
"""

import dataclasses
import hashlib
import os
import re
import shutil
import subprocess
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

from cft_golden import FORMATS, asm, cert, cert2, ed25519, seq  # noqa: E402
from cft_golden.profile import VERSION as PROFILE  # noqa: E402
from cft_golden.lang.version import VERSION as LANGUAGE  # noqa: E402
import cftc  # noqa: E402

SC = None           # segrun_check, the gate this is a section of
WORK = None

# The replay program: written here, sharing nothing with the corpus's
# markstep. The source defines k <- k + 1 and x <- x a + b, a = 3/4
# (exact) and b = 1/3 (rounded once); the image computes the same and,
# quiet, marks a lane where k is 5 (and writes its x's last bit wrong
# there) or 22 (its x right), then raises the mark with invalid.
REPLAYSTEP_SRC = b"""; replaystep - segrun_check's replay program (section 14)
system replaystep
format fp64
round  rne
state  k, x
param  a = 3/4, b = 1/3
next   k = k + 1
next   x = x * a + b
step   map
"""
REPLAYSTEP = """.format   fp64
.deposits 0
.bank     external
.scratch  in 2
.scratch  out 2
.const    A
.const    B
.const    ONE
.const    K5
.const    K22
.const    IONE
.const    MARK
.const    ZERO
.reg      k   = r3
.reg      x   = r4
.reg      ax  = r5
.reg      at5 = r6
.reg      at2 = r7
.reg      bad = r8
.reg      mk  = r9
ldl    k, 0
ldl    x, 1
repeat 4
  mul    ax, x, A
  add    x, ax, B
  quiet
    cmpeq  at5, k, K5
    cmpeq  at2, k, K22
    ixor   bad, x, IONE
    select x, bad, x, at5
    select mk, MARK, ZERO, at5
    select mk, MARK, mk, at2
  endquiet
  raise  mk
  add    k, k, ONE
endrep
stl    k, 0
stl    x, 1
halt
"""
LORENZ_SRC = ROOT / "programs" / "systems" / "lorenz63-rk4-fp64.cftl"
LZ_PARAMS = {"rho": "29", "beta": "21/8"}
# docs/CERTIFICATES.md prints the published test key's secret, 20 .. 3f
TEST_SEED = bytes(range(32, 64))


def fbits(fmt, text):
    return SC.dec(fmt, text)


@dataclasses.dataclass
class Run2:
    """A version-2 run as both writers take it."""
    kind: str
    image: bytes
    bank: bytes
    init: list
    fmt: str
    segments: int
    steps: int
    params: tuple = ()
    h_slots: tuple = ()
    lane_flags: bool = False        # --lane-flags
    source: Path = None             # the .cftl, or None
    manifest: bytes = None          # cftc's manifest for the tool
    compiled: str = None            # the target where compiled from
    sparams: dict = dataclasses.field(default_factory=dict)
    replay: tuple = None            # (image bytes, bank bytes)


@dataclasses.dataclass
class Prog2:
    name: str
    runs: list
    entries: tuple = ()             # segrun_check EntrySpecs
    opts: tuple = ()                # global options (statements, ...)
    env: dict = None                # the environment's variables to set


def compile_source(src_bytes, steps, fmt=None, params=None, name="system"):
    c = cftc.compile_text(src_bytes, steps, "sw", source=name, fmt=fmt,
                          params=params or None)
    return c


def write_run_inputs(d, i, r):
    d.mkdir(parents=True, exist_ok=True)
    img = d / f"run{i}.cftp"
    img.write_bytes(r.image)
    bank = None
    if r.bank:
        bank = d / f"run{i}.bank"
        bank.write_bytes(r.bank)
    init = d / f"run{i}.init"
    init.write_bytes(cert.state_bytes(r.fmt, r.init))
    a = ["--run", r.kind]
    if r.kind == "half-step":
        a += ["--h-slots", ",".join(str(s) for s in r.h_slots)]
    a += ["--image", img]
    if bank:
        a += ["--bank", bank]
    a += ["--init", init, "--segments", r.segments, "--steps", r.steps]
    for n, v in r.params:
        if n != SC.DEPTH_PARAM:         # --scratch-depth's, not the run's
            a += ["--param", f"{n}={v}"]
    if r.lane_flags:
        a += ["--lane-flags"]
    if r.source is not None:
        man = d / f"run{i}.manifest.json"
        man.write_bytes(r.manifest)
        a += ["--source", r.source, "--manifest", man]
        if not r.compiled:
            a += ["--compiler", "none"]
    if r.replay is not None:
        rimg = d / f"run{i}.replay.cftp"
        rimg.write_bytes(r.replay[0])
        a += ["--replay-image", rimg]
        if r.replay[1]:
            rb = d / f"run{i}.replay.bank"
            rb.write_bytes(r.replay[1])
            a += ["--replay-bank", rb]
    return a


def tool_args(prog, d, out, sdir, salt_path, device="sw", extra=()):
    a = ["--out", out, "--states", sdir]
    a += ["--salt", salt_path] if salt_path else ["--open"]
    a += ["--device", device]
    a += list(prog.opts) + list(extra)
    for i, r in enumerate(prog.runs):
        a += write_run_inputs(d, i, r)
    return a + SC.entry_options(prog.entries)


def run_tool(args, env=None):
    """The tool on a version-2 command line: no --format-version added,
    and the writer's list's variables cleared from the environment but for
    those `env` sets."""
    e = {n: "" for n in cert2.ENVIRONMENT_NAMES}
    e.update(env or {})
    return SC.run_tool(args, env=e, v2=True)


# ---- the golden writer ------------------------------------------------------

def golden_runs(prog, salt):
    runs, chains, shapes = [], [], []
    for r in prog.runs:
        definition = src = None
        if r.source is not None:
            sb = Path(r.source).read_bytes()
            g = cert2.source_graph(sb, r.fmt)
            definition = cert2.Definition(g, r.sparams,
                                          half=r.kind == "half-step")
            src = cert2.source_lines(
                sb, r.fmt, name=Path(r.source).name, params=r.sparams,
                compiler=("cftc", cftc.VERSION, r.compiled) if r.compiled
                else None)
        ch = cert2.run_chain(r.image, r.bank, r.init, r.segments,
                             scratch_depth=SC.DEPTH_V2,
                             lane_flags=True if r.lane_flags else None,
                             definition=definition, steps=r.steps)
        runs.append(cert2.certify_run(
            r.kind, r.image, r.bank, salt, ch, steps=r.steps,
            parameters=r.params, h_slots=r.h_slots,
            scratch_depth=SC.DEPTH_V2, source=src,
            main_image=prog.runs[0].image))
        chains.append(ch)
        shapes.append((FORMATS[r.fmt],
                       seq.Program.from_bytes(
                           r.image, scratch_depth=SC.DEPTH_V2).n_scratch_in))
    return runs, chains, shapes


def golden_entries(prog, runs, chains, shapes):
    ends = {}
    for i, ch in enumerate(chains):
        ends[(i, 0)] = ch.states[0]
        ends[(i, len(ch.states) - 1)] = ch.states[-1]
    out = []
    for e in prog.entries:
        probe = cert.Entry(e.method, cert2.METHOD_KIND[e.method], e.uses,
                           e.lane, cert.Value("exact", exact=Fraction(0)),
                           e.label, tuple(e.terms))
        q = cert.derive(probe, runs, shapes, ends,
                        method_run=cert2.METHOD_RUN)
        out.append(dataclasses.replace(probe, value=cert.make_value(
            q, e.form, e.fmt, e.rnd)))
    return tuple(out)


def golden_certificate(prog, salt, parsed):
    runs, chains, shapes = golden_runs(prog, salt)
    entries = golden_entries(prog, runs, chains, shapes)
    data = cert2.encode(cert2.Certificate(
        parsed.mode, parsed.salt_commitment, parsed.identity,
        parsed.provenance, tuple(runs), entries))
    return data, chains


def side_files(chains, fmts):
    """{name: bytes} of every file the golden chain puts in DIR."""
    out = {}
    for i, (ch, fmt) in enumerate(zip(chains, fmts)):
        for b, st in enumerate(ch.states):
            out[f"run-{i}-boundary-{b}.bin"] = cert.state_bytes(fmt, st)
        out.update(cert2.side_files(i, ch))
    return out


def audit_args(prog, chains, sdir, sampled, seed):
    progs = {i: (r.image, r.bank or None) for i, r in enumerate(prog.runs)}
    kw = {"sources": {i: Path(r.source).read_bytes()
                      for i, r in enumerate(prog.runs) if r.source}}
    if not kw["sources"]:
        del kw["sources"]
    states = {}
    for i, ch in enumerate(chains):
        bs = range(len(ch.states)) if sampled else (0,)
        states[i] = {b: (sdir / f"run-{i}-boundary-{b}.bin").read_bytes()
                     for b in bs}
    kw["states"] = states
    blocks = {i: {k: (sdir / f"run-{i}-segment-{k}.flags").read_bytes()
                  for k in range(len(ch.blocks))}
              for i, ch in enumerate(chains) if ch.lane_flags}
    if blocks:
        kw["lane_flags"] = blocks
    if sampled:
        kw["choose"] = {i: ("sample", max(1, r.segments // 2))
                        for i, r in enumerate(prog.runs)}
        kw["seed"] = seed
    return progs, kw


def certify(prog, mode, tag="", device="sw", extra=(), env=None,
            hold_golden=True):
    """cft-segrun on a version-2 program, held to the golden writer, its
    files to the golden chain's, and the golden audit. -> (bytes, sdir,
    parsed) or None."""
    salt = SC.SALT if mode == "keyed" else None
    what = f"v2 {prog.name} {mode}{tag}"
    stem = WORK / "v2" / re.sub(r"[^A-Za-z0-9.-]+", "-", what)
    d = Path(str(stem) + ".in")
    out, sdir = Path(str(stem) + ".cert"), Path(str(stem) + ".states")
    salt_path = WORK / "salt.bin" if salt is not None else None
    t0 = time.perf_counter()
    rc, so, se = run_tool(tool_args(prog, d, out, sdir, salt_path, device,
                                    extra), env if env is not None
                          else prog.env)
    if not SC.check(rc == 0, f"{what}: cft-segrun writes it "
                    f"({time.perf_counter() - t0:.1f} s)",
                    f"rc {rc}: {se.strip()[-500:]}"):
        return None
    data = out.read_bytes()
    try:
        parsed = cert.parse(data, salt=salt)
        SC.ok(f"{what}: the golden reader accepts it ({len(data):,} bytes, "
              f"version {parsed.version})")
    except cert.Refusal as e:
        SC.bad(f"{what}: the golden reader refuses it: {e}")
        return None
    if not SC.check(getattr(parsed, "version", 1) == 2,
                    f"{what}: it is version 2 (cft-certificate 2)"):
        return None
    if not hold_golden:
        return data, sdir, parsed
    t0 = time.perf_counter()
    gold, chains = golden_certificate(prog, salt, parsed)
    SC.check(gold == data, f"{what}: the golden writer, running and "
             f"replaying every segment itself, handed the tool's header "
             f"lines, writes the same bytes "
             f"({time.perf_counter() - t0:.1f} s)",
             SC.first_difference(data, gold))
    want = side_files(chains, [r.fmt for r in prog.runs])
    have = sorted(os.listdir(sdir)) if sdir.is_dir() else []
    SC.check(have == sorted(want), f"{what}: DIR holds exactly the golden "
             f"chain's {len(want)} files (boundaries, blocks, raw files)",
             f"it holds {have[:8]}")
    wrong = [n for n in want if n in have and
             (sdir / n).read_bytes() != want[n]]
    SC.check(not wrong, f"{what}: each is the golden chain's, byte for byte",
             f"{wrong[:6]}")
    for sampled in (False, True):
        progs, kw = audit_args(prog, chains, sdir, sampled, bytes(32))
        how = "sampled" if sampled else "in full from the initial states"
        try:
            t0 = time.perf_counter()
            cert.audit(data, salt, progs, **kw)
            SC.ok(f"{what}: the golden audit ACCEPTS it {how}, handed the "
                  f"sources and blocks ({time.perf_counter() - t0:.1f} s)")
        except cert.Refusal as e:
            SC.bad(f"{what}: the golden audit refuses it {how}: {e.name}: "
                   f"{e.message}")
    return data, sdir, parsed


# ---- the programs ------------------------------------------------------------

def flagstep2():
    img = asm.assemble(SC.FLAGSTEP, "flagstep")
    init = [fbits("fp64", t) for t in ("3", "1", "2", "5", "1", "7")]
    return Prog2("flagstep-lanes",
                 [Run2("main", img, b"", init, "fp64", 5, 1,
                       lane_flags=True)],
                 entries=(SC.EntrySpec("drift", 0, None, "exact",
                                       label="c", terms=SC.FLAG_C),))


def replaystep(work):
    src = work / "replaystep.cftl"
    src.write_bytes(REPLAYSTEP_SRC)
    g = cert2.source_graph(REPLAYSTEP_SRC)
    pa = {p[0]: p[2] for p in g.param}
    bank = cert.state_bytes("fp64", [pa["a"], pa["b"], fbits("fp64", "1"),
                                     fbits("fp64", "5"), fbits("fp64", "22"),
                                     1, 0x81, 0])
    img = asm.assemble(REPLAYSTEP, "replaystep")
    c = compile_source(REPLAYSTEP_SRC, 4, name="replaystep.cftl")
    init = [fbits("fp64", t) for t in ("0", "0.25", "20", "0.5", "10",
                                       "0.75")]
    return Prog2("replaystep",
                 [Run2("main", img, bank, init, "fp64", 3, 4, source=src,
                       manifest=c.manifest_bytes,
                       replay=(c.image, c.bank))],
                 entries=(SC.EntrySpec("drift", 0, None, "exact",
                                       label="k", terms=SC.FLAG_C),)), c


def lorenz2():
    sb = LORENZ_SRC.read_bytes()
    c64 = compile_source(sb, 100, params=LZ_PARAMS,
                         name="lorenz63-rk4-fp64.cftl")
    c128 = compile_source(sb, 100, fmt="fp128", params=LZ_PARAMS,
                          name="lorenz63-rk4-fp64.cftl")
    init = []
    for i in range(3):
        init += [fbits("fp64", repr(1 + i / 64)), fbits("fp64", "1"),
                 fbits("fp64", "1")]
    wide = [cert.widen("fp64", x) for x in init]
    hs = tuple(c64.manifest["h_slots"])
    kw = dict(source=LORENZ_SRC, compiled="sw", sparams=LZ_PARAMS)
    return Prog2("lorenz63-sourced", [
        Run2("main", c64.image, c64.bank, init, "fp64", 2, 100,
             params=(("members", 3),), manifest=c64.manifest_bytes, **kw),
        Run2("half-step", c64.image, c64.half_bank, init, "fp64", 4, 100,
             h_slots=hs, manifest=c64.manifest_bytes, **kw),
        Run2("wider-source", c128.image, c128.bank, wide, "fp128", 2, 100,
             manifest=c128.manifest_bytes, **kw)],
        entries=(SC.EntrySpec("wider-source", 2, None, "enclosed", "fp64"),
                 SC.EntrySpec("step-halving", 1, 0, "rounded", "fp64",
                              "rne")))


# signed-fp64's certificate-id (certificates/corpus.py), spelt as a text
SIGNED_ID = cert2.text_token("cert 0001 / " + chr(0x141) + chr(0xF3) + "d" +
                             chr(0x17A))
ISSUER = "cft%20test%20issuer%20(published%20key)"
BOX = ("gen%20case", "2", "4", "-1", "1")


def statements2(supersedes):
    """flagstep with every statement given, its initial state the
    shake-box generator's, both privacy defaults published."""
    p = flagstep2()
    vals = cert2.generate_initial(("generator", "shake-box",
                                   ("gen case", "2", "4", "-1", "1")),
                                  "fp64", 2, 2)
    p.name = "flagstep-statements"
    p.runs = [dataclasses.replace(p.runs[0], init=vals, segments=3)]
    key = ed25519.public_key(TEST_SEED).hex()
    p.opts = ("--certificate-id", SIGNED_ID, "--issuer", ISSUER,
              "--issuer-key", key, "--supersedes", supersedes,
              "--initial", "generator shake-box " + " ".join(BOX),
              "--publish", "device-serial", "--publish", "host-os-version")
    p.env = {"CFT_TIMEOUT_MS": "60000", "XCL_EMULATION_MODE": "hw_emu",
             "CFT_XRT_TILES": ""}
    return p


# ---- the legs -----------------------------------------------------------------

def lines_of(data):
    return cert.body_of(data).decode("ascii").split("\n")[:-1]


def line(data, key):
    for ln in lines_of(data):
        if ln.split(" ")[0] == key:
            return ln[len(key) + 1:]
    return None


def hold_measured(what, data, publish_os=False, env=None, device="none"):
    """b. what the tool measures, against the golden writer's functions."""
    want_os = cert2.host_os(with_version=publish_os)
    tok = cert2.text_token(want_os) if want_os != "unknown" else "unknown"
    SC.check(line(data, "host-os") == tok, f"{what}: host-os is the golden "
             f"writer's host_os({publish_os}) on this host: {tok}",
             f"{line(data, 'host-os')!r}")
    arch = cert2.host_arch()
    SC.check(line(data, "host-arch") == (cert2.text_token(arch) if arch !=
                                         "unknown" else arch),
             f"{what}: host-arch is the golden writer's host_arch(): {arch}",
             f"{line(data, 'host-arch')!r}")
    SC.check(line(data, "profile") == cert2.version_text(PROFILE),
             f"{what}: profile {cert2.version_text(PROFILE)}, profile.py's")
    rc, out, _ = SC.run_tool(["--build-id"])
    SC.check(line(data, "writer") == f"cft-segrun {out.strip()}" and
             line(data, "writer-runtime") == "none",
             f"{what}: writer cft-segrun and its build-id, writer-runtime "
             f"none", f"{line(data, 'writer')!r}")
    if device == "none":
        SC.check(all(line(data, k) == "none" for k in
                     ("device-platform", "device-xrt", "device-clock",
                      "device-serial")),
                 f"{what}: the software backend's four device lines none")
    times = [line(data, k) for k in ("started", "finished", "issued")]
    parsed = [cert2.read_time(t) for t in times]
    SC.check(all(p is not None for p in parsed) and parsed == sorted(parsed),
             f"{what}: started, finished and issued are times, in order "
             f"({times[0]} .. {times[2]})", f"{times}")
    want_env = [(n, cert2.text_token(v)) for n, v in
                sorted((env or {}).items()) if v]
    have_env = [tuple(ln.split(" ")[1:]) for ln in lines_of(data)
                if ln.startswith("env ")]
    SC.check(line(data, "environment") == str(len(want_env)) and
             have_env == want_env,
             f"{what}: the environment is the writer's list's variables "
             f"set, {[n for n, _ in want_env] or 'none'}", f"{have_env}")


def hold_env_table():
    src = (ROOT / "host" / "tools" / "segrun.c").read_text(encoding="utf-8")
    m = re.search(r"ENV_NAMES\[\] = \{(.*?)\};", src, re.S)
    names = tuple(re.findall(r'"([A-Z0-9_]+)"', m.group(1))) if m else ()
    SC.check(names == cert2.ENVIRONMENT_NAMES,
             f"segrun.c's environment table is cert2.ENVIRONMENT_NAMES, "
             f"{len(names)} names in byte order",
             f"{names} against {cert2.ENVIRONMENT_NAMES}")


def hold_same_hashes(flag):
    """c. one run's version-1 and version-2 certificates carry the same
    state and stream hashes."""
    d = WORK / "v2" / "v1v2"
    a = tool_args(flag, d, d / "v2.cert", d / "v2.states",
                  WORK / "salt.bin")
    rc2, _, se2 = run_tool(a)
    a1 = ["--format-version", "1"] + [x for x in a if str(x) !=
                                      "--lane-flags"]
    a1[a1.index("--out") + 1] = d / "v1.cert"
    a1[a1.index("--states") + 1] = d / "v1.states"
    rc1, _, se1 = run_tool(a1)
    if not SC.check(rc1 == 0 and rc2 == 0, "flagstep keyed, version 1 and "
                    "version 2 of one run: both written",
                    f"{se1.strip()[-200:]} {se2.strip()[-200:]}"):
        return
    v1, v2 = cert.parse((d / "v1.cert").read_bytes(), salt=SC.SALT), \
        cert.parse((d / "v2.cert").read_bytes(), salt=SC.SALT)
    r1, r2 = v1.runs[0], v2.runs[0]
    SC.check(r1.streams == r2.streams and
             [(s.start, s.end) for s in r1.chain] ==
             [(s.start, s.end) for s in r2.chain] and r1.output == r2.output,
             "one run's version-1 and version-2 certificates carry the same "
             "state and stream hashes, keyed under one salt")


def hold_literals(work, rs):
    """d. a source param's canonical literal, from manifests whose
    param_overrides carry chosen values."""
    values = ["29", "0", "-7", "1/2", "-3/4", "1/3", "21/2",
              "100000000000000000000", "1000000000000000000000",
              "1/1000000", "1/10000000", "123456789012345678901234",
              "1234567890123456789012345", "-1234567890123456789012345",
              "1/1237940039285380274899124224",       # 2^-90
              "3/1208925819614629174706176",          # 3 * 2^-80
              "1152921504606846977/2305843009213693952",  # (2^60+1)/2^61
              "-5/18014398509481984",                 # -5 * 2^-54
              "1/931322574615478515625",              # 5^-30
              "7/100", "123/1000000000", "123456789/1000"]
    src = rs.runs[0].source
    flag_img = asm.assemble(SC.FLAGSTEP, "flagstep")
    base = cftc.compile_text(REPLAYSTEP_SRC, 4, "sw",
                             source="replaystep.cftl").manifest
    import json
    names = [f"p{i:02d}" for i in range(len(values))]
    m = dict(base)
    m["param_overrides"] = [{"name": n, "value": v, "encoding": "0",
                             "default": "0"} for n, v in zip(names, values)]
    d = work / "v2" / "literals"
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_bytes(
        (json.dumps(m, indent=1, ensure_ascii=True) + "\n").encode("ascii"))
    (d / "flag.cftp").write_bytes(flag_img)
    (d / "flag.init").write_bytes(cert.state_bytes(
        "fp64", [fbits("fp64", "3"), fbits("fp64", "1")]))
    rc, _, se = run_tool(["--out", d / "c.cert", "--states", d / "s",
                          "--open", "--run", "main", "--image",
                          d / "flag.cftp", "--init", d / "flag.init",
                          "--segments", "1", "--steps", "1", "--source", src,
                          "--manifest", d / "manifest.json", "--compiler",
                          "none"])
    if not SC.check(rc == 0, f"d. a manifest of {len(values)} param "
                    f"overrides: written", f"rc {rc}: {se.strip()[-300:]}"):
        return
    got = {ln.split(" ")[1]: ln.split(" ")[2]
           for ln in lines_of((d / "c.cert").read_bytes())
           if ln.startswith("source-param ")}
    order = [ln.split(" ")[1] for ln in lines_of((d / "c.cert").read_bytes())
             if ln.startswith("source-param ")]
    SC.check(order == sorted(names), "d. the source-param lines are in byte "
             "order of their names")
    for n, v in zip(names, values):
        want = cert2.canonical_literal(Fraction(v)) if "/" in v else \
            cert2.canonical_literal(int(v))
        SC.check(got.get(n) == want, f"d. {v} spelt {want}, the language's "
                 f"canonical literal", f"the tool wrote {got.get(n)!r}")


ED_RFC_KEYS = (
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
    "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
    "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025")


def hold_keys(work, flag):
    """e. the issuer-key's decoding, against test_ed25519.py's vectors."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "test_ed25519", ROOT / "python" / "tests" / "test_ed25519.py")
    tv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tv)
    keys = [("the published test key", ed25519.public_key(TEST_SEED).hex(),
             None)]
    keys += [(f"RFC 8032's key {i + 1}", k, None)
             for i, k in enumerate(ED_RFC_KEYS)]
    keys += [(f"small order: {w}", h, "signer") for w, h in tv.SMALL_ORDER]
    keys += [(f"no point: {w}", h, "malformed") for w, _n, h in
             tv.UNDECODABLE]
    d = work / "v2" / "keys"
    for i, (what, key, want) in enumerate(keys):
        gold = cert2.key_problem(key)
        SC.check((gold[0] if gold else None) == want,
                 f"e. the golden reader's key_problem says "
                 f"{want or 'none'} for {what}")
        out, sdir = d / f"k{i}.cert", d / f"k{i}.states"
        rc, _, se = run_tool(tool_args(flag, d / f"k{i}.in", out, sdir, None,
                                       extra=("--issuer-key", key)))
        m = SC.REFUSED.search(se)
        if want is None:
            SC.check(rc == 0 and line(out.read_bytes(), "issuer-key") == key,
                     f"e. cft-segrun takes {what} as the issuer-key",
                     f"rc {rc}: {se.strip()[-200:]}")
        else:
            SC.check(rc == cert.REFUSALS[want] and m and m.group(1) == want
                     and not out.exists() and not sdir.exists(),
                     f"e. cft-segrun refuses {what} {want}, nothing made",
                     f"rc {rc}: {se.strip()[-200:]}")


# the tool's own limits, cft-audit's names (exit 78)
TOOL_LIMITS = {"build-width": 78, "build-format": 78}


def refused(label, name, args, env=None, after=False, twin=None):
    """f. one refusal: its name and code; nothing left behind before the
    run, or the files written so far left and said so after it; the golden
    writer's twin by the same name where it has one."""
    out = Path(args[args.index("--out") + 1]) if "--out" in args else None
    sdir = Path(args[args.index("--states") + 1]) if "--states" in args \
        else None
    rc, _, se = run_tool(args, env)
    m = SC.REFUSED.search(se)
    got = m.group(1) if m else None
    code = cert.REFUSALS.get(name, SC.TOOL_OWN.get(name, TOOL_LIMITS.get(
        name)))
    SC.check(rc == code and got == name, f"f. refused {name} (exit {code}): "
             f"{label}", f"exit {rc}, {got or 'no refusal named'}: "
             f"{se.strip()[-260:]}")
    if out is not None:
        if after:
            SC.check(not out.exists() and sdir is not None and sdir.is_dir()
                     and "written so far" in se and "left in" in se,
                     f"   and no certificate, the files written before the "
                     f"refusal left and said so: {label}")
        else:
            left = [p.name for p in (out, sdir) if p is not None and
                    p.exists()]
            SC.check(not left, f"   and nothing left behind: {label}",
                     f"left {left}")
    if twin is not None:
        try:
            twin()
            SC.bad(f"   the golden writer ACCEPTS {label}, which the tool "
                   f"refuses {name}")
        except cert.Refusal as e:
            SC.check(e.name == name, f"   the golden writer refuses {label} "
                     f"by the same name", f"it says {e.name}: {e.message}")


def hold_refusals(work, flag, rs, rs_c, lz):
    """f. every refusal version 2 adds, each beside a written control."""
    d = work / "v2" / "refusals"
    d.mkdir(parents=True, exist_ok=True)
    n = [0]

    def args(prog, extra=(), salt=False, runs_extra=None):
        n[0] += 1
        a = tool_args(prog, d / f"c{n[0]}.in", d / f"c{n[0]}.cert",
                      d / f"c{n[0]}.states",
                      WORK / "salt.bin" if salt else None, extra=extra)
        if runs_extra:
            a = runs_extra(a)
        return [str(x) for x in a]

    def with_run(prog, i, **kw):
        p = dataclasses.replace(prog, runs=list(prog.runs))
        p.runs[i] = dataclasses.replace(prog.runs[i], **kw)
        return p

    def control(label, a, env=None):
        rc, _, se = run_tool(a, env)
        SC.check(rc == 0, f"f. control, written: {label}",
                 f"rc {rc}: {se.strip()[-260:]}")

    key = ed25519.public_key(TEST_SEED).hex()
    # flagstep with no version-2 option of its own, and Lorenz-63 with no
    # source: each version-2 option is added to one alone
    plain = with_run(flag, 0, lane_flags=False)
    lz_nosrc = dataclasses.replace(lz, runs=[dataclasses.replace(
        r, source=None, manifest=None, compiled=None, sparams={})
        for r in lz.runs], entries=())
    # the command line's own (usage)
    control("flagstep at version 2, given --format-version 2",
            args(flag, ("--format-version", "2")))
    control("flagstep with no version-2 option, at --format-version 1",
            args(plain, ("--format-version", "1")))
    refused("--format-version 3", "usage", args(flag, ("--format-version",
                                                       "3")))
    refused("--lane-flags beside --format-version 1", "usage",
            args(flag, ("--format-version", "1")))
    for opt in (("--certificate-id", "x"), ("--issuer", "x"),
                ("--issuer-key", key), ("--initial", "given"),
                ("--supersedes", "none"), ("--publish", "device-serial")):
        refused(f"{opt[0]} beside --format-version 1", "usage",
                args(plain, ("--format-version", "1") + opt))
    refused("--compiler-build beside --format-version 1", "usage",
            args(lz, ("--format-version", "1", "--compiler-build",
                      "unknown")))
    refused("--source and --manifest beside --format-version 1", "usage",
            args(rs, ("--format-version", "1"),
                 runs_extra=lambda a: _drop(a, "--replay-image")))
    refused("--run wider-source beside --format-version 1", "usage",
            args(lz_nosrc, ("--format-version", "1")))
    refused("--publish a word it does not take", "usage",
            args(flag, ("--publish", "issuer")))
    refused("--publish device-serial twice", "usage",
            args(flag, ("--publish", "device-serial", "--publish",
                        "device-serial")))
    refused("--compiler with a value other than none", "usage",
            args(rs, runs_extra=lambda a: _set(a, "--compiler", "cftc")))
    refused("--compiler none on a run that names no source", "usage",
            args(plain, runs_extra=lambda a: _in_run(a, ["--compiler",
                                                         "none"])))
    refused("--source without --manifest", "usage",
            args(rs, runs_extra=lambda a: _drop(a, "--manifest")))
    refused("--replay-bank without --replay-image", "usage",
            args(rs, runs_extra=lambda a: _drop(a, "--replay-image")))
    refused("--compiler-build where no run names a compiler", "usage",
            args(rs, ("--compiler-build", "unknown")))
    refused("--compiler-build none where a run names one", "usage",
            args(lz, ("--compiler-build", "none")))
    control("--compiler-build stated where a run names a compiler",
            args(lz, ("--compiler-build", "commit=" + "c" * 40 +
                      " tracked=clean untracked=none")))
    bad_man = d / "bad.manifest.json"
    bad_man.write_bytes(b"{not json\n")
    refused("a manifest that is not JSON", "usage",
            args(rs, runs_extra=lambda a: _set(a, "--manifest", bad_man)))
    v9 = d / "v9.manifest.json"
    v9.write_bytes(rs.runs[0].manifest.replace(b'"cftc_manifest": 1',
                                               b'"cftc_manifest": 9'))
    refused("a manifest of a version this tool does not read", "usage",
            args(rs, runs_extra=lambda a: _set(a, "--manifest", v9)))
    # the statements' spellings (malformed), the golden writer's too
    for label, opt, val in (
            ("a certificate-id with a space unencoded", "--certificate-id",
             "a b"),
            ("a certificate-id with %41", "--certificate-id", "%41b"),
            ("a certificate-id in lowercase hex", "--certificate-id", "%c5%81"),
            ("a certificate-id of 256 characters", "--certificate-id",
             "x" * 256),
            ("a certificate-id that is a word", "--certificate-id", "unknown"),
            ("an issuer that is a word it does not take", "--issuer",
             "unknown"),
            ("an issuer-key of 63 hex digits", "--issuer-key", key[:63]),
            ("an issuer-key in upper case", "--issuer-key", key.upper()),
            ("a supersedes that is no body hash", "--supersedes", "abc"),
            ("a compiler-build out of grammar", "--compiler-build",
             "commit=abc tracked=clean untracked=none"),
            ("an initial with no generator name", "--initial", "generator"),
            ("an initial whose generator is a word", "--initial",
             "generator unknown x"),
            ("an initial of 17 arguments", "--initial",
             "generator shake-box " + " ".join(["1"] * 17)),
            ("an initial argument not a text", "--initial",
             "generator shake-box a%20b c%2"),
            ("an initial with two spaces", "--initial",
             "generator  shake-box")):
        prog = lz if opt == "--compiler-build" else flag
        refused(label, "malformed", args(prog, (opt, val)))
    control("a certificate-id of 255 characters",
            args(flag, ("--certificate-id", "x" * 255)))
    control("an initial of 16 arguments",
            args(flag, ("--initial", "generator shake-box " +
                        " ".join(["1"] * 16))))
    refused("an environment variable of the writer's list set to a word",
            "malformed", args(flag), env={"CFT_TIMEOUT_MS": "none"},
            twin=lambda: cert2.text_token("none"))
    def golden_with_key(k):
        """the golden writer handed a flagstep certificate's lines with
        this issuer-key: its read-back names the key's problem"""
        p = flag
        runs, chains, shapes = golden_runs(p, None)
        prov = cert2.Provenance(profile="2", language="none",
                                issuer_key=k)
        return cert2.encode(cert2.Certificate(
            "open", None, cert.Identity(), prov, tuple(runs),
            golden_entries(p, runs, chains, shapes)))
    refused("an issuer-key of small order", "signer",
            args(flag, ("--issuer-key", "01" + "00" * 31)),
            twin=lambda: golden_with_key("01" + "00" * 31))
    refused("an issuer-key that encodes no point (y = 2)", "malformed",
            args(flag, ("--issuer-key", "02" + "00" * 31)),
            twin=lambda: golden_with_key("02" + "00" * 31))
    # the source and its manifest, each beside its control
    lzm = lz.runs[0]
    other = d / "other.cftl"
    other.write_bytes(LORENZ_SRC.read_bytes() + b"; another source\n")
    refused("a source that is not the manifest's", "source-digest",
            args(lz, runs_extra=lambda a: _set(a, "--source", other, 0)))
    nul = d / "null.manifest.json"
    nul.write_bytes(re.sub(rb'("source": \{\s*"path": "[^"]*",\s*"sha256": )'
                           rb'"[0-9a-f]{64}"', rb'\1null', lzm.manifest))
    refused("a manifest that names no source file's digest",
            "source-digest",
            args(lz, runs_extra=lambda a: _set(a, "--manifest", nul, 0)))
    m128 = lz.runs[2].manifest
    w = d / "fp128.manifest.json"
    w.write_bytes(m128)
    refused("an fp64 run handed the fp128 compile's manifest",
            "source-graph",
            args(lz, runs_extra=lambda a: _set(a, "--manifest", w, 0)))
    lz128_main = dataclasses.replace(
        lz, runs=[dataclasses.replace(lz.runs[2], kind="main",
                                      params=())], entries=())
    refused("a main run compiled one rung up from its source (a format "
            "override)", "source-format", args(lz128_main))
    refused("a source whose lane is not the image's", "source-shape",
            args(dataclasses.replace(
                flag, runs=[dataclasses.replace(
                    flag.runs[0], source=LORENZ_SRC,
                    manifest=lzm.manifest)])))
    c50 = cftc.compile_text(LORENZ_SRC.read_bytes(), 50, "sw",
                            source="lorenz63-rk4-fp64.cftl",
                            params=LZ_PARAMS)
    refused("a compiled run whose image is another compile's (50 steps "
            "where the manifest says 100)", "source-image",
            args(with_run(lz, 0, manifest=c50.manifest_bytes)))
    refused("a compiled main run on the half bank", "source-image",
            args(with_run(lz, 0, bank=lz.runs[1].bank)))
    control("the same main run defined by its source on the half bank "
            "(--compiler none)",
            args(dataclasses.replace(lz, runs=[dataclasses.replace(
                lzm, bank=lz.runs[1].bank, compiled=None)], entries=())))
    # the replay image, beside the program
    img128 = asm.assemble(REPLAYSTEP.replace(".format   fp64",
                                             ".format   fp128"),
                          "replay128")
    refused("a replay image of another format", "program-format",
            args(with_run(rs, 0, replay=(img128, b""))))
    noio = asm.assemble((ROOT / "programs" / "div-fp64.cfta").read_text(
        encoding="utf-8"), "div-fp64")
    refused("a replay image that is not a segment", "program-shape",
            args(with_run(rs, 0, replay=(noio, b""))))
    refused("a replay image cut short", "program-image",
            args(with_run(rs, 0, replay=(rs_c.image[:-8], rs_c.bank))))
    refused("a replay bank one element short", "program-image",
            args(with_run(rs, 0, replay=(rs_c.image, rs_c.bank[:-8]))))
    flag_img = asm.assemble(SC.FLAGSTEP, "flagstep")
    refused("a replay bank beside a replay image with its own constants",
            "program-image",
            args(with_run(rs, 0, replay=(flag_img, bytes(8)))))
    one = asm.assemble(".format   fp64\n.deposits 0\n.scratch  in 1\n"
                       ".scratch  out 1\nldl  r3, 0\nstl  r3, 0\nhalt\n",
                       "one-slot")
    refused("a replay image whose lane is another width", "source-shape",
            args(with_run(rs, 0, replay=(one, b""))))
    refused("--replay-image on a run that names no source", "replay-source",
            args(with_run(flag, 0, replay=(rs_c.image, rs_c.bank))))
    # a segment that marks a lane, at the segment
    plain = dataclasses.replace(rs, entries=())
    refused("a run that marks a lane and names no source", "replay-source",
            args(with_run(plain, 0, source=None, manifest=None,
                          replay=None)), after=True,
            twin=lambda: cert2.run_chain(rs.runs[0].image, rs.runs[0].bank,
                                         rs.runs[0].init, 3, steps=4))
    refused("a run that marks a lane, names its source and has no replay "
            "image", "replay-missing", args(with_run(plain, 0, replay=None)),
            after=True)
    refused("a replay image that marks the lane too (the marking image "
            "itself)", "replay-undecided",
            args(with_run(plain, 0, replay=(rs.runs[0].image,
                                            rs.runs[0].bank))), after=True)
    # C4's rule at version 2: a wider run of a routine image (QUIET,
    # ENDQUIET or RAISE in the main image) refused aux-image before
    # anything runs, as at version 1; lanes whose k never meets 5 or 22,
    # so that the golden writer's chain reaches its check
    rimg, rbank = rs.runs[0].image, rs.runs[0].bank
    quiet = [fbits("fp64", t) for t in ("100", "0.25", "200", "0.5")]
    wimg = asm.assemble(REPLAYSTEP.replace(".format   fp64",
                                           ".format   fp128"), "replay128")
    wbank = cert.state_bytes("fp128", [cert.widen("fp64", x) for x in
                                       cert.state_values("fp64", rbank)])
    wide = [cert.widen("fp64", x) for x in quiet]
    rw = Prog2("replaystep-wider", [
        Run2("main", rimg, rbank, quiet, "fp64", 1, 4),
        Run2("wider", wimg, wbank, wide, "fp128", 1, 4)])

    def golden_routine_wider():
        ch = cert2.run_chain(wimg, wbank, wide, 1)
        cert2.certify_run("wider", wimg, wbank, None, ch, steps=4,
                          main_image=rimg)
    refused("a version-2 wider run of a routine image", "aux-image",
            args(rw), twin=golden_routine_wider)
    rc, _, se = run_tool(args(rw), {"CFT_SEGRUN_PLANT": "wider-routine"})
    SC.check(rc == 0, "f. control: CFT_SEGRUN_PLANT=wider-routine writes "
             "that version-2 certificate as stated, for an audit to refuse",
             f"rc {rc}: {se.strip()[-200:]}")
    lzw = dataclasses.replace(lz_nosrc, runs=[
        lz_nosrc.runs[0], dataclasses.replace(lz_nosrc.runs[2],
                                              kind="wider")])
    control("a version-2 wider run beside a main image with no routine "
            "(Lorenz-63; the writer checks no relation)", args(lzw))
    # what memory a version-2 run needs, tried before anything is made
    refused("10^12 segments asking for the per-lane block", "memory",
            args(with_run(flag, 0, segments=10 ** 12), ()))
    # a source param past the bigint: the tool's own limit, beside a
    # manifest whose value is not frac_text's spelling (usage)
    import json
    big = json.loads(lzm.manifest)
    big["param_overrides"] = [{"name": "rho", "value": "1/" + "3" * 700,
                               "encoding": "0", "default": "28"}]
    bm = d / "big.manifest.json"
    bm.write_bytes((json.dumps(big, indent=1) + "\n").encode("ascii"))
    one_run = dataclasses.replace(lz, runs=[dataclasses.replace(
        lzm, compiled=None)], entries=())
    refused("a source param's value past the bigint", "build-width",
            args(one_run, runs_extra=lambda a: _set(a, "--manifest", bm)))
    big["param_overrides"][0]["value"] = "2/4"
    bm2 = d / "half.manifest.json"
    bm2.write_bytes((json.dumps(big, indent=1) + "\n").encode("ascii"))
    refused("a manifest's param value not in lowest terms", "usage",
            args(one_run, runs_extra=lambda a: _set(a, "--manifest", bm2)))


def _drop(a, opt):
    a = list(a)
    i = a.index(opt)
    return a[:i] + a[i + 2:]


def _in_run(a, extra):
    """`extra` inserted at the end of the last run block: before the first
    --entry, or at the end."""
    a = list(a)
    i = a.index("--entry") if "--entry" in a else len(a)
    return a[:i] + [str(x) for x in extra] + a[i:]


def _set(a, opt, value, nth=0):
    a = list(a)
    idx = [i for i, x in enumerate(a) if x == opt][nth]
    a[idx + 1] = str(value)
    return a


def hold_remote(serve, flag, rs, sw):
    """g. flagstep's blocks and replaystep's replays through a loopback
    cft-serve: the device lines unknown, the run blocks the software
    backend's."""
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    log = open(WORK / "v2" / "serve.log", "w")
    p = subprocess.Popen([str(serve), "--port", str(port)], stdout=log,
                         stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        for prog in (flag, rs):
            res = certify(prog, "keyed", " remote",
                          device=f"cft://127.0.0.1:{port}", hold_golden=False)
            if not res or prog.name not in sw:
                continue
            data = res[0]
            SC.check(all(line(data, k) == "unknown" for k in
                         ("device-platform", "device-xrt", "device-clock",
                          "device-serial")) and line(data, "backend") ==
                     "remote", f"g. {prog.name} through cft-serve: backend "
                     f"remote, its four device lines unknown")
            SC.check(SC.runs_part(data) == SC.runs_part(sw[prog.name]),
                     f"g. {prog.name} through cft-serve: every run block the "
                     f"software backend's, byte for byte")
    finally:
        p.terminate()
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
        log.close()
        print(f"  cft-serve pid {p.pid} stopped", flush=True)


def hold_card(device, l63_sw):
    """h. on a card: the device lines from the tile, the serial withheld
    until published, the run blocks the software backend's; the per-lane
    block refused by name."""
    prog = dataclasses.replace(l63_sw, name="lorenz63-plain")
    res = certify(prog, "keyed", " card", device=device, hold_golden=False)
    if res:
        data = res[0]
        SC.check(line(data, "backend") == "xrt" and
                 all(line(data, k) not in (None, "none") for k in
                     ("device-platform", "device-xrt", "device-clock")),
                 f"h. on the card: backend xrt, platform "
                 f"{line(data, 'device-platform')!r}, XRT "
                 f"{line(data, 'device-xrt')!r}, clock "
                 f"{line(data, 'device-clock')!r}, none of them none")
        SC.check(line(data, "device-serial") in ("withheld", "unknown"),
                 f"h. on the card: the serial {line(data, 'device-serial')}, "
                 f"withheld by default (unknown where XRT gives none)")
    pub = certify(prog, "keyed", " card published", device=device,
                  extra=("--publish", "device-serial"), hold_golden=False)
    if pub:
        print(f"  NOTE  the card's serial, published: "
              f"{line(pub[0], 'device-serial')}", flush=True)
    sw = certify(prog, "keyed", " sw", hold_golden=False)
    if res and sw:
        SC.check(SC.runs_part(res[0]) == SC.runs_part(sw[0]),
                 "h. on the card: every run block the software backend's")
    asks = dataclasses.replace(prog, runs=[dataclasses.replace(
        prog.runs[0], lane_flags=True)])
    refused("the per-lane block asked of a revision-7 tile (CAPS2[13] "
            "clear)", "device", [str(x) for x in tool_args(
                asks, WORK / "v2" / "card-lf.in",
                WORK / "v2" / "card-lf.cert", WORK / "v2" / "card-lf.states",
                None, device)], after=True)


def hold_v2(sc, work, card=False, device="sw", serve=None):
    global SC, WORK
    SC, WORK = sc, work
    print("== 14. certificate format version 2: the golden writer's bytes, "
          "every measured line, every statement, every refusal by name",
          flush=True)
    (work / "v2").mkdir(parents=True, exist_ok=True)
    hold_env_table()
    flag = flagstep2()
    rs, rs_c = replaystep(work / "v2")
    lz = lorenz2()
    if card:
        lz_plain = Prog2("lorenz63-plain", [dataclasses.replace(
            r, source=None, manifest=None, compiled=None, sparams={})
            for r in lz.runs[:2]])
        hold_card(device, lz_plain)
        return
    sw = {}
    for prog in (flag, rs, lz):
        for mode in ("keyed", "open"):
            print(f"== v2 {prog.name}, {mode}", flush=True)
            res = certify(prog, mode)
            if res and mode == "keyed":
                sw[prog.name] = res[0]
                hold_measured(f"v2 {prog.name} keyed", res[0])
    if rs.name in sw:
        reps = [ln for ln in lines_of(sw[rs.name]) if ln.startswith("replay ")]
        SC.check(len(reps) == 2 and reps[0].startswith("replay 0 marked 1 "
                                                       "changed 0 ") and
                 reps[1].startswith("replay 1 marked 1 changed 1 "),
                 "replaystep: segment 0 marks lane 1 (changed 0) and segment "
                 "1 marks lane 0, whose last bit was wrong (changed 1)",
                 f"{reps}")
        SC.check(line(sw[rs.name], "language") ==
                 cert2.version_text(LANGUAGE),
                 f"a run that names a source: language "
                 f"{cert2.version_text(LANGUAGE)}, lang/version.py's")
    if flag.name in sw:
        SC.check(line(sw[flag.name], "language") == "none",
                 "no run names a source: language none")
    sup = cert2.body_hash_of(sw[flag.name]) if flag.name in sw else "0" * 64
    st = statements2(sup)
    print(f"== v2 {st.name}, keyed", flush=True)
    res = certify(st, "keyed")
    if res:
        data = res[0]
        hold_measured(f"v2 {st.name}", data, publish_os=True, env=st.env)
        SC.check(line(data, "certificate-id") == SIGNED_ID and
                 line(data, "issuer") == ISSUER and
                 line(data, "supersedes") == sup and
                 line(data, "initial") == "generator shake-box " +
                 " ".join(BOX),
                 "every statement written as given, in its own spelling")
        SC.check(SIGNED_ID == "cert%200001%20/%20%C5%81%C3%B3d%C5%BA" and
                 cert.parse(data).provenance.certificate_id.endswith(
                     chr(0xF3) + "d" + chr(0x17A)),
                 "signed-fp64's certificate-id reaches the tool whole, "
                 "non-ASCII and all, through its percent-encoded spelling")
    deep = dataclasses.replace(flag, name="flagstep-deep", runs=[
        dataclasses.replace(r, params=tuple(sorted(
            r.params + ((SC.DEPTH_PARAM, 2048),)))) for r in flag.runs])
    print("== v2 flagstep at --scratch-depth 2048, open", flush=True)
    SC.DEPTH_V2 = 2048
    try:
        res = certify(deep, "open", extra=("--scratch-depth", "2048"))
        if res:
            SC.check(line(res[0], "parameter") == "scratch-depth 2048",
                     "at --scratch-depth 2048 the run block states it")
    finally:
        SC.DEPTH_V2 = SC.DEPTH
    hold_same_hashes(flag)
    hold_literals(work, rs)
    hold_keys(work, flag)
    hold_refusals(work, flag, rs, rs_c, lz)
    if serve is not None:
        hold_remote(serve, flag, rs, sw)
