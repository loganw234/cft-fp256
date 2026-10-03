# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft-audit held to the golden auditor: the equality gate of the plan of
record's step 4 (docs/ROADMAP.md, "Steps 4 and 7"; docs/CERTIFICATES.md,
"The audit tool").

    python host/tests/audit_check.py --tool host/cft-audit[.exe]
                                     --segrun host/cft-segrun[.exe]
                                     [--cc CC --lib-src "SRC ..."]
                                     [--keep DIR] [--record DIR]

`make -C host audittest` runs it, and verify/run.sh's `audit` stage, in
the gate budget, runs that. Every input is handed to both auditors -
cft-audit as files and options, cert.audit (or cert.parse) as the
arguments it takes - and they must give the SAME verdict: the refusal's
name, its exit code and its location (line, run, segment, entry), or
both ACCEPTED with the same verdict, line for line.

  1. the tool's own: every usage refusal a command line or a file can
     cause, a state file that is a directory among them, refused before
     step 1; `--sample` against the page's test vector and against
     cert.sample over a grid, with the choice refusals, and a K past
     what a map can be sized for refused `memory` (71), promptly; the
     instrument set empty, which is the instrument unset; a seed drawn
     by the operating system, printed, different each audit, and the
     same verdict again under it; git ignoring the binary in both its
     forms;
  2. test_cert.py and test_cert2.py, run in this process with cert.parse
     and cert.audit SHADOWED: every top-level call a test makes is also
     handed to the tool, so "every control test_cert.py makes" is every
     call its tests make, and stays so as controls are added. The golden
     call's own result goes back to the test unchanged, and pytest must
     pass. A call whose arguments no file or option can carry faithfully
     (a list where a mapping goes, a str or bool key, an integer past the
     format, a salt that is not bytes) is counted and named by reason,
     never compared. A seed the golden audit draws is caught and handed
     to the tool; an executor test_cert.py makes refuse (a monkeypatched
     seq.run) is the tool's instrument, CFT_AUDIT_PLANT=executor-refuses.
     cft-audit takes no source and regenerates no initial state, so a
     version-2 audit call handed either is held to the golden auditor
     handed neither (no_source_kwargs), where a replay, a wider-source
     relation and a definition re-run refuse source-missing in both;
  3. the certificates segrun_check makes: cft-segrun on its programs,
     keyed and open, with the accuracy entries segrun_check gives them
     (every method, scope, form and direction), each audited in full from
     every boundary, in full from the initial states alone, and sampled
     under a fixed seed;
  4. the golden corpus (certificates/MANIFEST), where the tree has one:
     each case in full and sampled, both auditors against each other and
     against the manifest's verdict; each version-2 case and control as
     corpus.py hands the golden auditor its blocks, signature, keyring,
     superseded certificate and definition re-run, without the source and
     the regeneration (section_corpus2);
  5. two narrow builds: libcft and cft-audit compiled at CFT_MAX_FORMAT=2
     (formats to fp128), at its own 576-bit cft_bn and at CFT_BN_LIMBS=64
     (NARROW_BUILDS). The first must refuse `build-width` (78) at an
     `accuracy` line counting at least 1; the second must audit exact
     values within the ceiling in full, lor's four entries and the page's
     example, with the golden's verdict. Both must refuse `build-format`
     (78) wherever a format above the ceiling would reach the library: a
     run's `program-format` line (an fp256 certificate the golden auditor
     and the default tool accept: verifier-A1's first case), an accuracy
     value's line (lor with entry 1 in fp256, rounded or enclosed: A1's
     second), and at a run whose image's header is fp256 under a stated
     fp128, which the golden refuses program-format;
  6. the tool's numerics, through a probe build of tools/audit.c
     (-DCFT_AUDIT_PROBE, never the tool itself): its own division, gcd
     and exact arithmetic held to Python's integers up to 2,047 bits, its
     rounding of a rational to cert.round_rational in every format and
     direction, an element's exact value and width to
     cert.element_fraction, and the library's widening (cft_convert) and
     exact decimal (cft_to_decimal_char) to cert.widen and
     chars.to_decimal - measured before they are trusted, on a fixed
     seed's random cases and each operation's edges;
  7. Ed25519 verification and SHA-512 in C (tools/ed25519.h and
     tools/sha512.h, version 2's detached signature), through the same
     probe build: every vector python/tests/test_ed25519.py carries, each
     answer the golden model's, and SHA-512's published examples and every
     length across its padding against hashlib.

Section 1 also holds cft.h's CFT_PROFILE_* and CFT_LANGUAGE_* to
python/cft_golden/profile.py and lang/version.py, and the tool's writer's
list of variables and its generators to cert2.py's.

With --record DIR, every tool run is kept as a case - its files, its
command line and the golden verdict it must give - for
host/tests/audit_plants.py, the census of plants, to replay.

Exit 0 only if every check passed; the last line says so.
"""

import argparse
import dataclasses
import hashlib
import json
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
sys.path.insert(0, str(ROOT / "python" / "tests"))
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(HERE))

from cft_golden import FORMATS, cert, seq  # noqa: E402

# The tool's own refusals, beside the page's table: the codes the checks
# below want of them.
TOOL_OWN = {"usage": 64, "memory": 71, "build-width": 78,
            "build-format": 78}
TOOL_TIMEOUT = 120
SEED0 = bytes(32)
FIXED_SEED = hashlib.sha256(b"audit_check: the fixed sampling seed").digest()

CHECKS = 0
FAILED = []
SKIPS = []


def ok(what, quiet=False):
    global CHECKS
    CHECKS += 1
    if not quiet:
        print(f"  ok    {what}", flush=True)


def bad(what):
    global CHECKS
    CHECKS += 1
    FAILED.append(what)
    print(f"  FAIL  {what}", flush=True)


def check(cond, what, why="", quiet=False):
    if cond:
        ok(what, quiet)
    else:
        bad(what + (f" - {why}" if why else ""))
    return cond


def skip(what, why):
    SKIPS.append(what)
    print(f"SKIP  {what}: {why}", flush=True)


# ---- verdicts ---------------------------------------------------------------

def loc_of(e):
    return tuple("-" if v is None else str(v)
                 for v in (e.line, e.run, e.segment, e.entry))


def golden(fn, *a, **k):
    """-> (kind, detail): ("refused", (name, code, loc)), ("accepted",
    lines or None), or ("error", type name) for what is not a verdict."""
    try:
        v = fn(*a, **k)
    except cert.Refusal as e:
        return "refused", (e.name, e.exit_code, loc_of(e))
    except Exception as e:      # noqa: BLE001 - reported, never raised
        return "error", type(e).__name__
    # a verdict of either version: cert.Verdict, or cert2.Verdict
    return "accepted", (v.lines() if callable(getattr(v, "lines", None))
                        else None)


REFUSED = re.compile(r"^cft-audit: refused ([a-z-]+): ", re.M)
LOCATION = re.compile(r"^cft-audit: location line=(\S+) run=(\S+) "
                      r"segment=(\S+) entry=(\S+)$", re.M)

TOOL = SEGRUN = None
RECORD = None
RECORDED = [0]


def run_tool(args, env=None, cwd=None):
    e = dict(os.environ)
    e.pop("CFT_AUDIT_PLANT", None)
    if env:
        e.update(env)
    try:
        r = subprocess.run([str(TOOL)] + [str(a) for a in args],
                           capture_output=True, text=True, env=e,
                           timeout=TOOL_TIMEOUT, cwd=cwd)
    except subprocess.TimeoutExpired:
        return -1, "", f"audit_check: the tool ran past {TOOL_TIMEOUT} s"
    return r.returncode, r.stdout, r.stderr


def tool_verdict(rc, out, err):
    """The tool's answer in golden()'s shape. An accepted version-2 verdict
    keeps the tool's two header lines (its identity and the audit's time,
    cert2.Verdict.header()'s place); same() holds them to their shape and
    compares the lines after them."""
    if rc == 0:
        return "accepted", out.split("\n")[:-1] if out.endswith("\n") \
            else out.split("\n")
    m, l = REFUSED.search(err), LOCATION.search(err)
    if m and l:
        return "refused", (m.group(1), rc, tuple(l.groups()))
    return "error", f"exit {rc}: {err.strip()[-300:]}"


V2_HEADER = (re.compile(r"auditor cft-audit (?:unknown|commit=[0-9a-f]{40}"
                        r"(?:[0-9a-f]{24})? tracked=(?:clean|modified) "
                        r"untracked=(?:none|present))"),
             re.compile(r"audited [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:"
                        r"[0-9]{2}:[0-9]{2}Z"))


def verdict_lines(t_lines, g_lines):
    """The tool's verdict lines to compare with the golden's: after the two
    header lines where the golden verdict is version 2's, which the tool
    must print (its identity and the audit's time, as cert2.Verdict.header()
    holds them for the golden auditor). -> (lines, why or "")"""
    if g_lines and g_lines[0].startswith("cft-certificate 2:"):
        if len(t_lines) < 2 or not V2_HEADER[0].fullmatch(t_lines[0]) or \
                not V2_HEADER[1].fullmatch(t_lines[1]):
            return t_lines, (f"a version-2 verdict without the tool's header "
                             f"(auditor, audited): {t_lines[:2]}")
        return t_lines[2:], ""
    return t_lines, ""


def same(g, t, read_only=False):
    """Do the golden verdict g and the tool's t agree? -> (bool, why)"""
    if g[0] == "refused":
        if t[0] != "refused":
            return False, (f"golden refused {g[1][0]} at {g[1][2]}; the tool "
                           f"{'ACCEPTED' if t[0] == 'accepted' else t[1]}")
        if t[1] != g[1]:
            return False, (f"golden refused {g[1][0]} (exit {g[1][1]}) at "
                           f"{g[1][2]}; the tool refused {t[1][0]} (exit "
                           f"{t[1][1]}) at {t[1][2]}")
        return True, ""
    if g[0] == "accepted":
        if t[0] != "accepted":
            said = (f"refused {t[1][0]} at {t[1][2]}" if t[0] == "refused"
                    else t[1])
            return False, f"golden ACCEPTED; the tool {said}"
        if read_only:
            ok_read = bool(t[1]) and (
                t[1][0].startswith("cft-certificate 1: READ") or
                t[1][0].startswith("cft-certificate 2: READ"))
            return ok_read, "" if ok_read else f"the tool printed {t[1][:2]}"
        lines, why = verdict_lines(t[1], g[1])
        if why:
            return False, why
        t = (t[0], lines)
        if t[1] != list(g[1]):
            diff = next((f"line {i + 1}: golden {x!r}, tool {y!r}"
                         for i, (x, y) in enumerate(zip(g[1], t[1]))
                         if x != y), f"{len(g[1])} lines against {len(t[1])}")
            return False, f"both ACCEPTED, the verdicts differ: {diff}"
        return True, ""
    return False, f"golden gave no verdict ({g[1]})"


def record(workdir, args, env, want, label, read_only=False, binary="tool"):
    """Keep this tool run as a case for audit_plants.py: its files, its
    arguments relative to its directory, and the verdict it must give -
    of the tool, or of a narrow build (binary "narrow" or "narrow64",
    NARROW_BUILDS)."""
    if RECORD is None:
        return
    RECORDED[0] += 1
    d = RECORD / f"{RECORDED[0]:06d}"
    if workdir is not None:
        shutil.copytree(workdir, d)
    else:
        d.mkdir(parents=True)
    rel = []
    for a in args:
        s = str(a)
        rel.append(os.path.relpath(s, workdir) if workdir is not None and
                   os.path.isabs(s) and s.startswith(str(workdir)) else s)
    (d / "case.json").write_text(json.dumps(
        {"args": rel, "env": env or {}, "want": want, "label": label,
         "read_only": read_only, "binary": binary}), encoding="utf-8")


def hold(args, env, g, label, workdir, read_only=False, quiet=True):
    """Run the tool on `args`, compare with the golden verdict g."""
    rc, out, err = run_tool(args, env, cwd=workdir)
    t = tool_verdict(rc, out, err)
    agree, why = same(g, t, read_only)
    record(workdir, args, env, list(g), label, read_only)
    return check(agree, label, why, quiet=quiet)


# ---- translating a golden call into files and options -----------------------

class Untranslatable(Exception):
    """These arguments have no faithful spelling as files and options."""


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _bytes_of(fmt, s, what):
    """A state or stream as the bytes the library stores, or refused."""
    if isinstance(s, (bytes, bytearray)):
        return bytes(s)
    if not isinstance(s, (list, tuple)) or not all(_is_int(v) for v in s):
        raise Untranslatable(f"{what} is a {type(s).__name__}, not bytes or "
                             f"integers")
    w = FORMATS[fmt].width
    if not all(0 <= v < (1 << w) for v in s):
        raise Untranslatable(f"{what} holds an integer past {fmt}")
    return cert.state_bytes(fmt, list(s))


def _formats(data):
    """Each run's format, read from the certificate - which is the image's
    wherever step 7 is reached - or fp64 where it does not read."""
    try:
        c = cert.parse(data) if ORIG_PARSE is None else ORIG_PARSE(data)
        return [r.fmt for r in c.runs]
    except Exception:           # noqa: BLE001
        return []


def _choice_spec(c):
    """A choice of segments as the tool spells it (--choose, --define)."""
    if c == "all":
        return "all"
    if isinstance(c, tuple) and len(c) == 2 and c[0] == "sample":
        if not _is_int(c[1]):
            raise Untranslatable("a sample size that is not an integer")
        return f"sample:{c[1]}"
    if isinstance(c, (list, tuple)):
        if not all(_is_int(k) for k in c):
            raise Untranslatable("a segment that is not an integer")
        return ",".join(str(k) for k in c)
    if isinstance(c, str) and re.fullmatch(r"[a-z]+", c) and c != "all":
        return c
    raise Untranslatable(f"a choice {c!r} with no spelling")


V2_INPUTS = ("sources", "lane_flags", "signature", "keyring", "superseded",
             "define", "regenerate")


def translate(workdir, data, salt, programs=None, states=None, streams=None,
              choose=None, seed=None, read_only=False, sources=None,
              lane_flags=None, signature=None, keyring=None, superseded=None,
              define=None, regenerate=False):
    """-> the tool's arguments, with the files written into workdir.

    Version 2's inputs (cert2.audit's keywords): the blocks go into the
    states directory as run-<r>-segment-<k>.flags, the signature, keyring
    and superseded certificate into files of their own, and `define` into
    each run's --define. `sources` is not carried: cft-audit takes no
    source, so the caller compares it with the golden auditor handed none
    (no_source_kwargs). `regenerate=True` has no spelling: the tool
    regenerates no initial state."""
    if not isinstance(data, (bytes, bytearray)):
        raise Untranslatable("the certificate is not bytes")
    v2 = bytes(data[:18]) == b"cft-certificate 2\n"
    if not v2 and (any(x is not None for x in (
            sources, lane_flags, signature, keyring, superseded, define))
            or regenerate is not False):
        raise Untranslatable("version 2's inputs beside a version-1 "
                             "certificate, which cert.audit refuses with a "
                             "TypeError")
    if regenerate is True:
        raise Untranslatable("regenerate=True: cft-audit regenerates no "
                             "initial state (no_source_kwargs drops it)")
    if regenerate is not False:
        raise Untranslatable(f"regenerate={regenerate!r:.20}: a choice that "
                             f"is not a bool has no spelling")
    (workdir / "c.cert").write_bytes(bytes(data))
    args = ["--cert", workdir / "c.cert"]
    if read_only:
        args = ["--read"] + args
    if salt is not None:
        if not isinstance(salt, (bytes, bytearray)):
            raise Untranslatable("the salt is not bytes")
        (workdir / "salt").write_bytes(bytes(salt))
        args += ["--salt", workdir / "salt"]
    if read_only:
        return args
    fmts = _formats(data)

    def fmt_of(r):
        return fmts[r] if _is_int(r) and 0 <= r < len(fmts) else "fp64"
    if seed is not None:
        if not isinstance(seed, (bytes, bytearray)):
            raise Untranslatable("the seed is not bytes")
        args += ["--seed", bytes(seed).hex()]
    blocks = {}

    def block(r):
        if not _is_int(r):
            raise Untranslatable(f"a run key {r!r} that is not an integer")
        return blocks.setdefault(r, [])
    if programs is not None:
        if not isinstance(programs, dict):
            raise Untranslatable("programs is not a mapping")
        for r, pair in programs.items():
            b = block(r)
            if not (isinstance(pair, (tuple, list)) and len(pair) == 2 and
                    isinstance(pair[0], (bytes, bytearray)) and
                    (pair[1] is None or isinstance(pair[1],
                                                   (bytes, bytearray)))):
                raise Untranslatable("a program that is not (image, bank)")
            f = workdir / f"image-{len(blocks)}-{len(b)}"
            f.write_bytes(bytes(pair[0]))
            b += ["--image", f]
            if pair[1]:
                g = workdir / f"bank-{len(blocks)}-{len(b)}"
                g.write_bytes(bytes(pair[1]))
                b += ["--bank", g]
    if streams is not None:
        if not isinstance(streams, dict):
            raise Untranslatable("streams is not a mapping")
        for r, abc in streams.items():
            if abc is None:
                if not (_is_int(r) and 0 <= r < len(fmts)):
                    raise Untranslatable("no stream for a key that is no run")
                continue
            if not isinstance(abc, (tuple, list)) or len(abc) != 3:
                raise Untranslatable("streams that are not (a, b, c)")
            if all(s is None for s in abc) and not (_is_int(r) and
                                                     0 <= r < len(fmts)):
                raise Untranslatable("no stream for a key that is no run")
            b = block(r)
            for x, s in zip("abc", abc):
                if s is None:
                    continue
                f = workdir / f"stream-{r}-{x}"
                f.write_bytes(_bytes_of(fmt_of(r), s, f"stream {x}"))
                b += ["--stream", x, f]
    if choose is not None:
        if not isinstance(choose, dict):
            raise Untranslatable("choose is not a mapping")
        for r, c in choose.items():
            b = block(r)
            b += ["--choose", _choice_spec(c)]
    if define is not None:
        if not isinstance(define, dict):
            raise Untranslatable("define is not a mapping")
        for r, c in define.items():
            if isinstance(c, tuple) and len(c) == 2 and c[0] == "sample":
                raise Untranslatable("a definition re-run of a sample, which "
                                     "has no spelling")
            b = block(r)
            b += ["--define", _choice_spec(c)]
    for r, b in blocks.items():
        if b:
            args += ["--run", str(r)] + b
    sd = workdir / "states"
    if states is not None:
        if not isinstance(states, dict):
            raise Untranslatable("states is not a mapping")
        sd.mkdir(exist_ok=True)
        for r, per in states.items():
            if not _is_int(r) or r < 0:
                raise Untranslatable(f"a states key {r!r} no file name holds")
            if not isinstance(per, dict):
                raise Untranslatable("a run's states that are not a mapping")
            for b_, s in per.items():
                if not _is_int(b_) or b_ < 0:
                    raise Untranslatable(f"a boundary {b_!r} no file name "
                                         f"holds")
                (sd / f"run-{r}-boundary-{b_}.bin").write_bytes(
                    _bytes_of(fmt_of(r), s, "a state"))
    if lane_flags is not None:
        if not isinstance(lane_flags, dict):
            raise Untranslatable("lane_flags is not a mapping")
        sd.mkdir(exist_ok=True)
        for r, per in lane_flags.items():
            if not _is_int(r) or r < 0:
                raise Untranslatable(f"a lane_flags key {r!r} no file name "
                                     f"holds")
            if not isinstance(per, dict):
                raise Untranslatable("a run's blocks that are not a mapping")
            for k, blk in per.items():
                if not _is_int(k) or k < 0:
                    raise Untranslatable(f"a block's segment {k!r} no file "
                                         f"name holds")
                if not isinstance(blk, (bytes, bytearray)):
                    raise Untranslatable("a block that is not bytes")
                (sd / f"run-{r}-segment-{k}.flags").write_bytes(bytes(blk))
    if states is not None or lane_flags is not None:
        args += ["--states", sd]
    for value, fname, opt in ((signature, "c.sig", "--signature"),
                              (keyring, "ring", "--keyring"),
                              (superseded, "old.cert", "--superseded")):
        if value is None:
            continue
        if not isinstance(value, (bytes, bytearray)):
            raise Untranslatable(f"{opt[2:]} that is not bytes")
        (workdir / fname).write_bytes(bytes(value))
        args += [opt, workdir / fname]
    return args


def no_source_kwargs(kw):
    """A version-2 golden audit's keywords for the same audit as cft-audit
    can be handed it: no source - so that a replay in a re-run segment, a
    wider-source relation and a definition re-run refuse `source-missing`
    in both (docs/CERTIFICATES.md, "Version 2's C half") - and not
    asked to regenerate the initial state, which the tool does not do, so
    that both report a generator as not regenerated. A regenerate that is
    not a bool is kept, and is untranslatable. -> (kwargs, what was
    dropped: a tuple of "source" and "regenerate")."""
    out, dropped = dict(kw), []
    if out.get("sources") is not None:
        out.pop("sources")
        dropped.append("source")
    if out.get("regenerate") is True:
        out.pop("regenerate")
        dropped.append("regenerate")
    return (out, tuple(dropped)) if dropped else (kw, ())


# ---- section 2: test_cert.py, shadowed --------------------------------------

ORIG_PARSE = ORIG_AUDIT = ORIG_SEQ_RUN = None


class _Os:
    """cert.py's `os`, with every urandom it draws kept, so that a seed
    the golden audit draws can be handed to the tool."""

    def __init__(self, real):
        self._real = real
        self.drawn = []

    def urandom(self, n):
        b = self._real.urandom(n)
        self.drawn.append(b)
        return b

    def __getattr__(self, name):
        return getattr(self._real, name)


class Shadow:
    def __init__(self, work):
        self.work = work
        self.depth = 0
        self.calls = {"parse": 0, "audit": 0}
        self.mirrored = {"parse": 0, "audit": 0}
        self.untranslatable = {}
        self.fails = []
        self.n = 0
        self.t_tool = 0.0          # seconds in the tool's runs
        self.t_files = 0.0         # seconds writing their files
        self.slowest = []          # (seconds, label)
        self.no_source = 0         # version-2 calls held to the golden
                                   # auditor handed no source
        self.no_regen = 0          # ... and not asked to regenerate
        self.versions = {1: 0, 2: 0}   # mirrored calls by the version

    def _dir(self, read_only):
        """A parse call writes its certificate (and salt) over the last
        one's; an audit call gets a directory of its own, fresh."""
        self.n += 1
        d = self.work / "shadow" / ("read" if read_only else "case")
        if not read_only and d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _test(self):
        t = os.environ.get("PYTEST_CURRENT_TEST", "?")
        return t.split(" ")[0].split("::")[-1]

    def mirror(self, kind, g, a, k, env=None, read_only=False):
        self.calls[kind] += 1
        test = self._test()
        t0 = time.perf_counter()
        d = self._dir(read_only)
        try:
            if kind == "parse":
                data = a[0] if a else k.get("data")
                args = translate(d, data,
                                 a[1] if len(a) > 1 else k.get("salt"),
                                 read_only=True)
            else:
                names = ("data", "salt", "programs", "states", "streams",
                         "choose", "seed")
                kw = dict(zip(names, a))
                kw.update(k)
                data = kw.get("data")
                args = translate(d, **kw)
        except Untranslatable as e:
            key = f"{test}: {e}"
            self.untranslatable[key] = self.untranslatable.get(key, 0) + 1
            return
        if g[0] == "error":
            key = f"{test}: golden raised {g[1]}, not a verdict"
            self.untranslatable[key] = self.untranslatable.get(key, 0) + 1
            return
        self.mirrored[kind] += 1
        self.versions[2 if isinstance(data, (bytes, bytearray)) and
                      bytes(data[:18]) == b"cft-certificate 2\n" else 1] += 1
        t1 = time.perf_counter()
        rc, out, err = run_tool(args, env, cwd=d)
        t2 = time.perf_counter()
        self.t_files += t1 - t0
        self.t_tool += t2 - t1
        self.slowest = sorted(self.slowest + [(t2 - t1, f"{test} {kind} "
                                               f"#{self.calls[kind]}")])[-5:]
        t = tool_verdict(rc, out, err)
        agree, why = same(g, t, read_only)
        record(d, args, env, list(g), f"{test} ({kind} #{self.calls[kind]})",
               read_only)
        global CHECKS
        CHECKS += 1
        if not agree:
            self.fails.append(f"{test}, {kind} call {self.calls[kind]}: {why}")
            FAILED.append(self.fails[-1])
            print(f"  FAIL  {self.fails[-1]}", flush=True)

    def parse(self, *a, **k):
        top = self.depth == 0
        self.depth += 1
        try:
            try:
                res = ORIG_PARSE(*a, **k)
                g = ("accepted", None)
            except cert.Refusal as e:
                res, g = e, ("refused", (e.name, e.exit_code, loc_of(e)))
            except Exception as e:      # noqa: BLE001
                res, g = e, ("error", type(e).__name__)
        finally:
            self.depth -= 1
        if top:
            self.mirror("parse", g, a, k, read_only=True)
        if isinstance(res, BaseException):
            raise res
        return res

    def audit(self, *a, **k):
        top = self.depth == 0
        self.depth += 1
        cert.os.drawn.clear()
        kw = None
        try:
            try:
                res = ORIG_AUDIT(*a, **k)
                g = ("accepted", res.lines())
            except cert.Refusal as e:
                res, g = e, ("refused", (e.name, e.exit_code, loc_of(e)))
            except Exception as e:      # noqa: BLE001
                res, g = e, ("error", type(e).__name__)
            if top:
                names = ("data", "salt", "programs", "states", "streams",
                         "choose", "seed")
                kw = dict(zip(names, a))
                kw.update(k)
                if kw.get("seed") is None and cert.os.drawn:
                    kw["seed"] = cert.os.drawn[0]
                data = kw.get("data")
                if isinstance(data, (bytes, bytearray)) and \
                        bytes(data[:18]) == b"cft-certificate 2\n":
                    # cft-audit takes no source and regenerates nothing: it
                    # is held to the golden auditor handed no source and
                    # not asked to regenerate, where a replay, a
                    # wider-source relation and a definition re-run refuse
                    # source-missing in both (the golden call's own result
                    # still goes back to the test)
                    kw, dropped = no_source_kwargs(kw)
                    if dropped:
                        g = golden(ORIG_AUDIT, **kw)
                        self.no_source += "source" in dropped
                        self.no_regen += "regenerate" in dropped
        finally:
            self.depth -= 1
        if top:
            env = None
            if cert.seq.run is not ORIG_SEQ_RUN:
                env = {"CFT_AUDIT_PLANT": "executor-refuses"}
            self.mirror("audit", g, (), kw, env=env)
        if isinstance(res, BaseException):
            raise res
        return res


def section_shadow(work, files=("test_cert.py", "test_cert2.py")):
    """Section 2: each test file run in this process with cert.parse and
    cert.audit shadowed - test_cert.py's version-1 calls, and since version
    2's C half (parcel CV2CA) test_cert2.py's, whose audit calls are held
    to the golden auditor handed no source."""
    global ORIG_PARSE, ORIG_AUDIT, ORIG_SEQ_RUN
    import pytest
    print("== 2. test_cert.py and test_cert2.py shadowed: every parse call, "
          "and every audit call files and options can carry, through the "
          "tool too", flush=True)
    ORIG_PARSE, ORIG_AUDIT, ORIG_SEQ_RUN = cert.parse, cert.audit, seq.run
    out = []
    for fname in files:
        sh = Shadow(work)
        real_os = cert.os
        cert.os = _Os(real_os)
        cert.parse, cert.audit = sh.parse, sh.audit
        t0 = time.perf_counter()
        try:
            rc = pytest.main([str(ROOT / "python" / "tests" / fname),
                              "-q", "-p", "no:cacheprovider"])
        finally:
            cert.parse, cert.audit = ORIG_PARSE, ORIG_AUDIT
            cert.os = real_os
        dt = time.perf_counter() - t0
        check(rc == 0, f"{fname} passes with the shadow on ({dt:.0f} s: "
              f"{sh.t_tool:.0f} s in the tool's {sum(sh.mirrored.values())} "
              f"runs, {sh.t_files:.0f} s writing their files, the rest the "
              f"golden model)", f"pytest exit {rc}")
        print(f"  NOTE  {fname}'s slowest tool runs: " + "; ".join(
            f"{lab} {s:.2f} s" for s, lab in reversed(sh.slowest)),
            flush=True)
        for kind in ("parse", "audit"):
            n, m = sh.calls[kind], sh.mirrored[kind]
            check(m > 0, f"{fname} {kind}: {m} of {n} top-level calls handed "
                  f"to the tool too, each the same verdict"
                  + (f" ({len([f for f in sh.fails if f', {kind} call' in f])}"
                     f" differ)" if sh.fails else ""))
        print(f"  NOTE  {fname}: {sh.versions[1]} calls of version 1 and "
              f"{sh.versions[2]} of version 2 compared; {sh.no_source} "
              f"version-2 audits held to the golden auditor handed no "
              f"source, as cft-audit takes none, and {sh.no_regen} to it not "
              f"asked to regenerate the initial state, which cft-audit does "
              f"not do", flush=True)
        if sh.untranslatable:
            n = sum(sh.untranslatable.values())
            print(f"  NOTE  {fname}: {n} calls with arguments no file or "
                  f"option carries faithfully, not compared:", flush=True)
            for key, c in sorted(sh.untranslatable.items()):
                print(f"          {c:4d}  {key}", flush=True)
        out.append(sh)
    return out


# ---- section 1: the tool's own ----------------------------------------------

def section_tool(work):
    print("== 1. the tool's own: usage, --sample, a drawn seed, git",
          flush=True)
    d = work / "own"
    d.mkdir(parents=True, exist_ok=True)
    # the page's test vector, and cert.sample over a grid
    text = DOC.read_text(encoding="utf-8")
    at = text.index("<!-- the test vectors -->")
    block = re.search(r"```[a-z]*\n(.*?)```", text[at:], re.S).group(1)
    rows = dict(ln.split(None, 1) for ln in block.strip().split("\n"))
    args = ["--sample", rows["sample-seed"], rows["sample-run"],
            rows["sample-of"], rows["sample-k"]]
    rc, out, err = run_tool(args)
    check(rc == 0 and out.strip() == rows["sample"],
          f"--sample: the page's vector, {rows['sample']}",
          f"exit {rc}: {out.strip() or err.strip()}")
    record(None, args, None, ["accepted", [rows["sample"]]],
           "--sample, the page's vector")
    grid = 0
    for seed in (bytes(32), bytes(range(32)),
                 hashlib.sha256(b"auditor").digest()):
        for r, S, k in ((0, 10, 3), (1, 8, 8), (2, 1000, 17), (7, 5, 1),
                        ((1 << 32) - 1, 4, 2), (3, 1, 1), (0, 64, 63)):
            args = ["--sample", seed.hex(), str(r), str(S), str(k)]
            rc, out, _ = run_tool(args)
            want = " ".join(str(x) for x in cert.sample(seed, r, S, k))
            grid += check(rc == 0 and out.strip() == want,
                          f"--sample {seed.hex()[:8]}.. {r} {S} {k}",
                          f"{out.strip()!r}, golden {want!r}", quiet=True)
            record(None, args, None, ["accepted", [want]],
                   f"--sample {r} {S} {k}")
    print(f"  ok    --sample equals cert.sample on {grid} points of the grid",
          flush=True)
    for label, a, b in (
            ("a 31-byte seed", [bytes(31).hex(), "0", "4", "2"],
             (bytes(31), 0, 4, 2)),
            ("k 0", [bytes(32).hex(), "0", "4", "0"], (bytes(32), 0, 4, 0)),
            ("k past S", [bytes(32).hex(), "0", "4", "5"],
             (bytes(32), 0, 4, 5)),
            ("run -1", [bytes(32).hex(), "-1", "4", "2"],
             (bytes(32), -1, 4, 2)),
            ("run 2^32", [bytes(32).hex(), str(1 << 32), "4", "2"],
             (bytes(32), 1 << 32, 4, 2))):
        g = golden(cert.sample, *b)
        rc, out, err = run_tool(["--sample"] + a)
        agree, why = same(g, tool_verdict(rc, out, err))
        check(agree, f"--sample, {label}: refused choice as cert.sample is",
              why)
        record(None, ["--sample"] + a, None, list(g), f"--sample, {label}")
    # usage: every refusal a command line or a file can cause
    # --sample past what a map can be sized for: the tool's own `memory`,
    # promptly (at K = 2^62, 4K wrapped to 0 and the map probed forever;
    # verifier-A1). cert.sample has no verdict there (it builds range(S)).
    big = (1 << 63) - 1
    for S_, k_ in ((1 << 62, 1 << 62), (big, 1 << 62), (big, big)):
        args = ["--sample", bytes(32).hex(), "0", str(S_), str(k_)]
        rc, out, err = run_tool(args)
        t = tool_verdict(rc, out, err)
        want = ("refused", ("memory", TOOL_OWN["memory"],
                            ("-", "-", "-", "-")))
        check(t == want and out == "", f"--sample of {k_} from {S_}: "
              f"refused memory (71), promptly", f"{t}")
        record(None, args, None, [want[0], list(want[1])],
               f"--sample of {k_} from {S_}")
    # the instrument set to the empty string is the instrument unset, as
    # CFT_SEGRUN_PLANT's is (cmd and Windows PowerShell remove a variable
    # set empty, so an empty one means the same everywhere)
    args = ["--sample", rows["sample-seed"], rows["sample-run"],
            rows["sample-of"], rows["sample-k"]]
    env = {"CFT_AUDIT_PLANT": ""}
    rc, out, err = run_tool(args, env)
    check(rc == 0 and out.strip() == rows["sample"], "CFT_AUDIT_PLANT set "
          "empty is the instrument unset: --sample still prints the page's "
          "vector", f"exit {rc}: {out.strip() or err.strip()}")
    record(None, args, env, ["accepted", [rows["sample"]]],
           "CFT_AUDIT_PLANT empty")
    lor = work / "own" / "l.cert"
    lor.write_bytes(b"cft-certificate 1\n")
    # a file version 2's dispatch takes (its first 18 bytes), for the
    # usage refusals of version 2's inputs, which come before step 1
    lor2 = work / "own" / "l2.cert"
    lor2.write_bytes(b"cft-certificate 2\n")
    (d / "states-bad").mkdir(exist_ok=True)
    (d / "states-bad" / "run-01-boundary-0.bin").write_bytes(b"")
    (d / "blocks-bad").mkdir(exist_ok=True)
    (d / "blocks-bad" / "run-0-segment-01.flags").write_bytes(b"")
    # a directory by a boundary file's name: `usage` BEFORE step 1, which
    # this certificate (no hash line) would fail - so a tool that found it
    # only at step 7 says hash-line here (verifier-A1)
    (d / "states-dir" / "run-0-boundary-0.bin").mkdir(parents=True,
                                                      exist_ok=True)
    (d / "blocks-dir" / "run-0-segment-0.flags").mkdir(parents=True,
                                                       exist_ok=True)
    for label, args, env in (
            ("no argument at all", [], None),
            ("an unknown option", ["--cert", lor, "--lanes", "3"], None),
            ("no --cert", ["--salt", lor], None),
            ("--cert twice", ["--cert", lor, "--cert", lor], None),
            ("--run R twice", ["--cert", lor, "--run", "0", "--choose", "all",
                               "--run", "0", "--choose", "all"], None),
            ("--image before any --run", ["--cert", lor, "--image", lor],
             None),
            ("--image twice in a block", ["--cert", lor, "--run", "0",
                                          "--image", lor, "--image", lor],
             None),
            ("--stream x", ["--cert", lor, "--run", "0", "--stream", "x",
                            lor], None),
            ("--bank with no --image", ["--cert", lor, "--run", "0",
                                        "--bank", lor], None),
            ("--run R giving nothing", ["--cert", lor, "--run", "0"], None),
            ("--read with --states", ["--read", "--cert", lor, "--states",
                                      d], None),
            ("--sample with a fifth argument", ["--sample", "00" * 32, "0",
                                                "4", "2", "--cert", lor],
             None),
            ("--sample with three", ["--sample", "00" * 32, "0", "4"], None),
            ("a certificate that is not there", ["--cert", d / "absent"],
             None),
            ("an image that is not there", ["--cert", lor, "--run", "0",
                                            "--image", d / "absent"], None),
            ("a --states that is not a directory", ["--cert", lor,
                                                    "--states", lor], None),
            ("a boundary file misspelt", ["--cert", lor, "--states",
                                          d / "states-bad"], None),
            ("a directory named as a boundary file, found before step 1",
             ["--cert", lor, "--states", d / "states-dir"], None),
            ("CFT_AUDIT_PLANT=bogus", ["--cert", lor],
             {"CFT_AUDIT_PLANT": "bogus"}),
            # the census's (audit_plants.py): each of these reaches a check
            # no case above does, or a site whose own cases another check
            # would decide the same way
            ("--read twice", ["--read", "--read", "--cert", lor], None),
            ("--sample twice", ["--sample", "00" * 32, "0", "4", "2",
                                "--sample", "00" * 32, "0", "4", "2"], None),
            ("--stream before any --run", ["--cert", lor, "--stream", "a",
                                           lor], None),
            ("--seed with no value, last", ["--read", "--cert", lor,
                                            "--seed"], None),
            ("--stream ab", ["--cert", lor, "--run", "0", "--stream", "ab",
                             lor], None),
            # version 2's inputs (parcel CV2CA): beside a version-1
            # certificate, as cert.audit raises a TypeError for them; in
            # their places; and a block file's name, before step 1
            ("--signature beside a version-1 certificate",
             ["--cert", lor, "--signature", lor], None),
            ("--keyring beside a version-1 certificate",
             ["--cert", lor, "--keyring", lor], None),
            ("--superseded beside a version-1 certificate",
             ["--cert", lor, "--superseded", lor], None),
            ("--define beside a version-1 certificate",
             ["--cert", lor, "--run", "0", "--define", "all"], None),
            ("--define before any --run", ["--cert", lor2, "--define",
                                           "all"], None),
            ("--define twice in a block", ["--cert", lor2, "--run", "0",
                                           "--define", "all", "--define",
                                           "0"], None),
            ("--signature twice", ["--cert", lor2, "--signature", lor,
                                   "--signature", lor], None),
            ("--read with --keyring", ["--read", "--cert", lor2,
                                       "--keyring", lor], None),
            ("a signature file that is not there",
             ["--cert", lor2, "--signature", d / "absent"], None),
            ("a block file misspelt, for a version-2 certificate",
             ["--cert", lor2, "--states", d / "blocks-bad"], None),
            ("a directory named as a block file, found before step 1",
             ["--cert", lor2, "--states", d / "blocks-dir"], None)):
        rc, out, err = run_tool(args, env, cwd=d)
        t = tool_verdict(rc, out, err)
        code = TOOL_OWN["usage"]
        check(t[0] == "refused" and t[1][0] == "usage" and rc == code and
              t[1][2] == ("-", "-", "-", "-") and out == "",
              f"refused usage (exit {code}), nothing on stdout: {label}",
              f"{t}")
        record(d, args, env, ["refused", ["usage", code, ["-"] * 4]],
               f"usage: {label}")
    # version 1 reads no block file, as before version 2: the same
    # misspelt block file beside a version-1 certificate is not read, and
    # the certificate (no hash line) is refused at step 1
    args = ["--cert", lor, "--states", d / "blocks-bad"]
    rc, out, err = run_tool(args, cwd=d)
    t = tool_verdict(rc, out, err)
    want = ("refused", ("hash-line", 1, ("-", "-", "-", "-")))
    check(t == want, "a misspelt block file beside a version-1 certificate "
          "is not read: hash-line at step 1, as before version 2", f"{t}")
    record(d, args, None, [want[0], list(want[1])], "version 1 reads no "
           "block file")
    definition_checks()
    census_controls(work)
    v2_census_controls(work)


def v2_census_controls(work):
    """Golden against tool on version-2 inputs no test_cert2.py call hands
    the tool as it is handed them (no source): `definition-differs` raised
    inside each region cert2._Through covers that step 4 does not reach -
    a re-run's segment line (segment-flags, segment-lane-flags), a replay
    line's own checks (replay-raw, replay-missing) and the wider-source
    relation (aux-format) - under a certificate whose profile this
    library's does not cover; and an audit ACCEPTED under a definition
    that does not cover the certificate's (the verdict's "do not cover
    them" line), by the profile's minor and by the language where a run
    names a source. Without these, every definition-differs the gate
    compared was step 4's."""
    import test_cert2 as T2
    print("== 1d. version 2's controls: definition-differs in each re-derivation "
          "a source-free audit reaches, and a verdict under a definition "
          "that does not cover the certificate's", flush=True)
    fl = fixture_function(T2.fl)()
    mk = T2.make_markstep()
    lz = fixture_function(T2.lz)()
    n = 0

    def one(label, data, salt, programs, want=None, **kw):
        nonlocal n
        n += 1
        d = work / "census2" / f"c{n}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        kw, dropped = no_source_kwargs(kw)
        g = golden(cert.audit, data, salt, programs, **kw)
        args = translate(d, data, salt, programs=programs, **kw)
        hold(args, None, g, f"{label}: {describe(g)}", d, quiet=False)
        if want is not None:
            check(g[0] == want[0] and (g[0] != "refused" or
                                       (g[1][0], g[1][2]) == want[1:]),
                  f"  and the golden verdict is the control's: {want}",
                  describe(g))

    def seg(data, k, field, value):
        L = T2.lines_of(data)
        i = T2.find(L, f"segment {k} ")
        t = L[i].split(" ")
        t[field] = value
        return T2.rebuilt(L[:i] + [" ".join(t)] + L[i + 1:])

    def prof(data, value="profile 3"):
        return T2.edit(data, value.split(" ")[0] + " ", value)
    fl_states = {0: {0: fl.init}}
    one("flagstep, profile 3, segment 1's flags wrong",
        prof(seg(fl.data, 1, 7, "21")), None, {0: (fl.img, None)},
        ("refused", "definition-differs", ("-", "0", "1", "-")),
        states=fl_states)
    blk = fl.chain.blocks[0]
    other = bytes([blk[0] & ~0x10]) + blk[1:]
    one("flagstep, profile 3, segment 0's block another",
        prof(T2._block_line(fl, 0, other)), None, {0: (fl.img, None)},
        ("refused", "definition-differs", ("-", "0", "0", "-")),
        states=fl_states)
    L = T2.lines_of(mk.data)
    r = T2.find(L, "replay ")
    t = L[r].split(" ")
    t[7] = cert.parse(mk.data).runs[0].chain[1].end
    raw = T2.rebuilt(L[:r] + [" ".join(t)] + L[r + 1:])
    mk_args = dict(states={0: {0: mk.init}}, sources={0: mk.src})
    one("markstep, profile 3, its replay line's raw end the segment's",
        prof(raw), None, {0: (mk.img, mk.bank)},
        ("refused", "definition-differs", ("-", "0", "1", "-")), **mk_args)
    i = T2.find(L, "replay-methods ")
    m = T2.find(L, "replays ")
    gone = L[:i] + ["replay-methods 0"] + L[i + 2:m] + ["replays 0"] + \
        L[r + 1:]
    one("markstep, profile 3, its replay lines gone",
        prof(T2.rebuilt(gone)), None, {0: (mk.img, mk.bank)},
        ("refused", "definition-differs", ("-", "0", "1", "-")), **mk_args)
    r0, r1, _r2, r3 = lz.runs
    same = dataclasses.replace(r0, kind="wider-source")
    one("lorenz-63, profile 3, its wider-source run the main run's format",
        prof(T2.with_runs(lz, (r0, r1, same, r3))), None,
        {**lz.progs, 2: lz.progs[0]},
        ("refused", "definition-differs", ("-", "2", "-", "-")),
        states={**lz.states, 2: {0: lz.init}},
        sources={0: lz.src, 1: lz.src, 2: lz.src})
    one("flagstep, profile 2.1: accepted, under a definition that does not "
        "cover it", prof(fl.data, "profile 2.1"), None, {0: (fl.img, None)},
        ("accepted",), states=fl_states)
    every = {0: dict(enumerate(mk.chain.states))}
    one("markstep, language 2, its unreplayed segments: accepted, under a "
        "definition that does not cover it", prof(mk.data, "language 2"),
        None, {0: (mk.img, mk.bank)}, ("accepted",), states=every,
        choose={0: [0, 2]}, sources={0: mk.src})
    # paths only the C tool has code of its own for: a signature file whose
    # key encodes no point (cert2 refuses no such key there: its signature
    # does not verify), the wider-source relation's lanes and steps, and
    # blocks past segment 9, which cert2._check_blocks reads in their
    # decimal spelling's order (10 before 9) and the verdict lists so
    full = fixture_function(T2.full)(fl)
    S = full.sig.decode("ascii").split("\n")[:-1]
    nopoint = "\n".join(S[:2] + ["key 02" + "00" * 31] + S[3:]) + "\n"
    one("the signed certificate, a signature file whose key encodes no "
        "point", full.data, T2.SALT, {0: (full.img, None)},
        ("refused", "signature", ("-", "-", "-", "-")),
        states={0: {0: full.init}}, signature=nopoint.encode("ascii"))
    # its certificate line another body's, its signature this one's: only
    # the certificate line's own check refuses it (the signature verifies)
    from cft_golden import cert2 as C2
    named = "\n".join(S[:3] + [f"certificate {C2.body_hash_of(fl.data)}"]
                      + S[4:]) + "\n"
    one("the signed certificate, a signature file naming another "
        "certificate, its signature this one's", full.data, T2.SALT,
        {0: (full.img, None)}, ("refused", "signature", ("-", "-", "-", "-")),
        states={0: {0: full.init}}, signature=named.encode("ascii"))
    wide = dataclasses.replace(lz.runs[2], lanes=4)
    one("lorenz-63, its wider-source run of 4 lanes (its state not handed)",
        T2.with_runs(lz, (r0, r1, wide, r3)), None, lz.progs,
        ("refused", "aux-lanes", ("-", "2", "-", "-")),
        states={0: {0: lz.init}, 1: {0: lz.init}, 3: {0: lz.init_w}})
    slow = dataclasses.replace(lz.runs[2], steps=99)
    one("lorenz-63, its wider-source run of 99 steps a segment",
        T2.with_runs(lz, (r0, r1, slow, r3)), None, lz.progs,
        ("refused", "aux-image", ("-", "2", "-", "-")), states=lz.states)
    from cft_golden import cert2
    img = T2.flagstep_image()
    init = [T2.d64(v) for v in ("3", "1", "3", "5")]
    ch = cert2.run_chain(img, b"", init, 12, lane_flags=True)
    run12 = cert2.certify_run("main", img, b"", None, ch, steps=1)
    data12 = cert2.encode(cert2.Certificate(
        "open", None, T2.IDN, T2.prov(language="none"), (run12,), ()))
    blocks = dict(enumerate(ch.blocks))
    one("flagstep of 12 segments, every block handed: accepted, the blocks "
        "listed in their spelling's order", data12, None, {0: (img, None)},
        ("accepted",), states={0: {0: init}}, lane_flags={0: blocks})
    bad = dict(blocks)
    for k in (9, 10):
        b = bytearray(bad[k])
        b[0] ^= 0x01
        bad[k] = bytes(b)
    one("flagstep of 12 segments, blocks 9 and 10 not the certified ones: "
        "10 is read first", data12, None, {0: (img, None)},
        ("refused", "lane-flags-hash", ("-", "0", "10", "-")),
        states={0: {0: init}}, lane_flags={0: bad})


def definition_checks():
    """What cft-audit holds as version 2's definition and lists, against the
    golden model's: cft.h's CFT_PROFILE_* and CFT_LANGUAGE_* (the lead's
    names, 2026-10-02) against python/cft_golden/profile.py and
    lang/version.py, which decide `definition-differs` in both auditors;
    audit.c's writer's list of variables against cert2.ENVIRONMENT_NAMES;
    and its generators against cert2.GENERATORS."""
    from cft_golden import cert2, profile
    from cft_golden.lang import version as lang_version
    text = (HOST / "include" / "cft.h").read_text(encoding="utf-8")
    got = {n: int(v) for n, v in re.findall(
        r"^#define (CFT_(?:PROFILE|LANGUAGE)_(?:MAJOR|MINOR))\s+(\d+)\s*$",
        text, re.M)}
    want = {"CFT_PROFILE_MAJOR": profile.VERSION[0],
            "CFT_PROFILE_MINOR": profile.VERSION[1],
            "CFT_LANGUAGE_MAJOR": lang_version.VERSION[0],
            "CFT_LANGUAGE_MINOR": lang_version.VERSION[1]}
    check(got == want, f"cft.h's profile and language macros are "
          f"profile.py's {profile.VERSION} and lang/version.py's "
          f"{lang_version.VERSION}: {got}", f"want {want}")
    src = (HOST / "tools" / "audit.c").read_text(encoding="utf-8")
    try:
        block = src[src.index("BEGIN ENVIRONMENT_NAMES"):
                    src.index("END ENVIRONMENT_NAMES")]
        names = tuple(re.findall(r'"([A-Z0-9_]+)"', block))
    except ValueError:
        names = ()
    check(names == tuple(cert2.ENVIRONMENT_NAMES), f"cft-audit's list of the "
          f"variables an env line may name is cert2.ENVIRONMENT_NAMES, "
          f"{len(names)} of them", f"{names}")
    m = re.search(r"GENERATORS\[\] = \{([^}]*)\}", src)
    gens = tuple(re.findall(r'"([a-z0-9-]+)"', m.group(1))) if m else ()
    check(set(gens) == set(cert2.GENERATORS), f"cft-audit's generators, "
          f"which it reports and does not regenerate, are cert2.GENERATORS: "
          f"{', '.join(gens)}", f"{gens}")


def census_controls(work):
    """Golden against tool on inputs no test_cert.py call hands the audit,
    each for a check the plant census (audit_plants.py) found no case to
    reach, or found another check to decide the same way for the cases
    that reach it:
      - a stream one byte past whole elements whose whole ones are the
        run's lanes, and a state one byte past its size: only the
        whole-element check refuses these, where 23 and 71 bytes are
        refused by the length checks too;
      - a stream for a run the certificate does not have, handed;
      - a program whose scratch block goes in as 2 and out as 1, and a
        segment-shaped one that deposits, AUDITED: test_cert.py holds these
        two reasons through the writer (run_chain) only."""
    import test_cert as T
    from cft_golden import asm
    print("== 1c. controls the plant census asked for", flush=True)
    data, progs, states = T.example_certificate()
    fmt, lanes = "fp64", 2
    n = 0

    def one(label, dat=data, salt=T.SALT, prg=progs, **kw):
        nonlocal n
        n += 1
        d = work / "census" / f"c{n}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        kw.setdefault("states", states)
        g = golden(cert.audit, dat, salt, prg, **kw)
        args = translate(d, dat, salt, programs=prg, **kw)
        hold(args, None, g, f"{label}: {describe(g)}", d, quiet=False)
    whole = cert.state_bytes(fmt, [0] * lanes)
    one("a stream of whole elements and one byte, the lanes long",
        streams={0: (whole + b"\x00", None, None)})
    s0 = cert.state_bytes(fmt, states[0][0])
    one("a state of one byte past its size",
        states={0: {**states[0], 0: s0 + b"\x00"}, 1: states[1]})
    one("a stream handed for a run the certificate does not have",
        streams={5: (whole, None, None)})
    # two programs that are not segments, audited
    for label, src in (
            ("scratch in 2, out 1", ".format   fp64\n.deposits 0\n"
             ".scratch  in 2\n.scratch  out 1\nldl  r3, 0\nstl  r3, 0\n"
             "halt\n"),
            ("a segment's scratch that deposits", ".format   fp64\n"
             ".deposits 1\n.scratch  in 1\n.scratch  out 1\nldl  r3, 0\n"
             "deposit r3\nstl  r3, 0\nhalt\n")):
        img = asm.assemble(src, "shape")
        h = hashlib.sha256(b"a start").hexdigest()
        e = hashlib.sha256(b"an end").hexdigest()
        zero = cert.stream_hash(None, "a", bytes(8))
        run = cert.Run("main", fmt, cert.sha256(img), cert.sha256(img), 1, 1,
                       (zero, cert.stream_hash(None, "b", bytes(8)),
                        cert.stream_hash(None, "c", bytes(8))), (),
                       (cert.Segment(h, e, 0, 0),), e)
        c = cert.encode(cert.Certificate("open", None, T.IDENTITY, (run,),
                                         ()))
        one(f"{label}, audited", dat=c, salt=None, prg={0: (img, None)},
            states=None)


def drawn_seed_checks(work, case):
    """case: (args without a seed, golden audit kwargs) of an accepted
    certificate with a sampled run."""
    args, kw = case
    seeds = []
    for i in range(2):
        rc, out, err = run_tool(args)
        m = re.search(r"the auditor's seed ([0-9a-f]{64})", out)
        if not check(rc == 0 and m, f"a sample with no seed handed: "
                     f"accepted, the seed drawn and printed (#{i + 1})",
                     err.strip()[-200:]):
            return
        seeds.append((m.group(1), out))
    check(seeds[0][0] != seeds[1][0], "two audits draw two seeds: the "
          "auditor's own, never the certificate's")
    s = bytes.fromhex(seeds[0][0])
    g = golden(ORIG_AUDIT or cert.audit, **dict(kw, seed=s))
    t = tool_verdict(*run_tool(args + ["--seed", seeds[0][0]]))
    agree, why = same(g, t)

    def timeless(lines):
        # a version-2 verdict's header carries the audit's time
        return [ln for ln in lines if not ln.startswith("audited ")]
    check(agree and timeless(t[1]) ==
          timeless(seeds[0][1].split("\n")[:-1]),
          "the drawn seed handed back gives the same verdict, and the "
          "golden audit's under it", why)


def hold_ignored():
    try:
        r = subprocess.run(["git", "-C", str(ROOT), "rev-parse",
                            "--is-inside-work-tree"], capture_output=True,
                           text=True)
    except OSError:
        r = None
    if r is None or r.returncode != 0 or r.stdout.strip() != "true":
        skip("git ignores host/cft-audit", "this tree is in no git "
             "repository")
        return
    for p in ("host/cft-audit", "host/cft-audit.exe"):
        r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", p])
        check(r.returncode == 0, f"git ignores {p}, so a build of it leaves "
              f"the next build id clean", f"git check-ignore exits "
              f"{r.returncode}")


# ---- section 3: segrun_check's certificates ---------------------------------

def audits_of(work, label, data, salt, progs, states, fmt_of, want=None):
    """Hold both auditors equal on one certificate: in full from every
    state handed, in full from the initial states alone, and sampled
    under a fixed seed. -> the golden's full verdict."""
    runs = cert.parse(data).runs
    initial = {r: {0: s[0]} for r, s in states.items() if 0 in s}
    sample = {r: ("sample", max(1, len(run.chain) // 2))
              for r, run in enumerate(runs)}
    results = []
    for how, st, ch, seed in (("in full", states, None, None),
                              ("in full from the initial states", initial,
                               None, None),
                              ("sampled", states, sample, FIXED_SEED)):
        d = work / "cases" / f"{label}-{how.replace(' ', '-')}"
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)
        g = golden(cert.audit, data, salt, progs, states=st, choose=ch,
                   seed=seed)
        args = translate(d, data, salt, programs=progs, states=st, choose=ch,
                         seed=seed)
        hold(args, None, g, f"{label}, {how}: {describe(g)}", d, quiet=False)
        if want is not None:
            check(g[0] == want[0] and (g[0] != "refused" or
                                       g[1][0] == want[1]),
                  f"{label}, {how}: the golden audit's verdict is the "
                  f"expected one ({want[0]}"
                  f"{' ' + want[1] if want[0] == 'refused' else ''})",
                  describe(g))
        results.append(g)
    return results


def describe(g):
    if g[0] == "refused":
        return f"both refuse {g[1][0]} at {g[1][2]}"
    if g[0] == "accepted":
        return "both ACCEPTED, the same verdict"
    return f"golden: {g[1]}"


def section_segrun(work):
    print("== 3. cft-segrun's certificates of segrun_check's programs, each "
          "audited in full, from the initial states, and sampled", flush=True)
    import segrun_check as sc
    sc.TOOL = SEGRUN
    sc.SALT = hashlib.sha256(b"audit_check: the keyed salt").digest()
    sc.DEPTH = seq.SCRATCH_D
    man = sc.manifest()
    n0 = sc.CHECKS
    programs = [sc.ode_program(b, f, man) for b in sc.SIZES
                for f in ("fp64", "fp256")]
    flag = sc.flagstep_program()
    programs.append(flag)
    programs.append(sc.half_init_program(
        next(p for p in programs if p.name == "lorenz63-rk4-fp64")))
    check(sc.CHECKS - n0 == 6 and not sc.FAILED,
          "segrun_check's programs: the six ODE images are programs/"
          "MANIFEST's", f"{sc.FAILED}")
    # with the accuracy entries segrun_check certifies them with (the plan's
    # step 5): both auditors re-derive each, and their verdicts' lines hold
    # the values
    sc.attach_entries(programs)
    check(sum(len(p.entries) for p in programs) > 0,
          f"segrun_check's programs carry their accuracy entries: "
          f"{sum(len(p.entries) for p in programs)} of them")
    salt_path = work / "segrun" / "salt.bin"
    salt_path.parent.mkdir(parents=True, exist_ok=True)
    salt_path.write_bytes(sc.SALT)
    sampled_case = None
    for prog in programs:
        paths = sc.write_inputs(work / "segrun", prog)
        for mode in ("keyed", "open"):
            stem = work / "segrun" / "out" / f"{prog.name}-{mode}"
            stem.parent.mkdir(parents=True, exist_ok=True)
            out = Path(str(stem) + ".cert")
            sdir = Path(str(stem) + ".states")
            for p in (out,):
                if p.exists():
                    p.unlink()
            if sdir.exists():
                shutil.rmtree(sdir)
            salt = sc.SALT if mode == "keyed" else None
            r = subprocess.run([str(SEGRUN)] + [str(a) for a in sc.tool_args(
                prog, paths, out, sdir, salt_path if salt else None)],
                capture_output=True, text=True, timeout=TOOL_TIMEOUT)
            if not check(r.returncode == 0, f"{prog.name} {mode}: cft-segrun "
                         f"writes it", r.stderr.strip()[-300:]):
                continue
            data = out.read_bytes()
            progs = {i: (s.image, s.bank) for i, s in enumerate(prog.runs)}
            states = {i: {b: (sdir / f"run-{i}-boundary-{b}.bin")
                          .read_bytes() for b in range(s.segments + 1)}
                      for i, s in enumerate(prog.runs)}
            want = ("refused", prog.audit_refuses) if prog.audit_refuses \
                else ("accepted", None)
            audits_of(work, f"{prog.name} {mode}", data, salt, progs, states,
                      None, want)
            if sampled_case is None and mode == "open" and \
                    not prog.audit_refuses:
                d = work / "cases" / "drawn"
                if d.exists():
                    shutil.rmtree(d)
                d.mkdir(parents=True)
                ch = {i: ("sample", 1) for i in range(len(prog.runs))}
                sampled_case = (translate(d, data, None, programs=progs,
                                          states=states, choose=ch),
                                dict(data=data, salt=None, programs=progs,
                                     states=states, choose=ch))
    return sampled_case


# ---- section 4: the golden corpus -------------------------------------------

def read_manifest(path):
    """certificates/MANIFEST (P2's format, the audit round's ledger P2.md
    19:53:22): the cases, each with its certificate, runs (image, bank),
    states, salt and verdict. Only what this gate needs is read."""
    cases, cur, run = [], None, None
    for raw in path.read_text(encoding="ascii").split("\n"):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        t = line.split(" ")
        if t[0] == "case":
            cur = {"name": t[1], "runs": [], "salt": None}
            cases.append(cur)
        elif cur is None:
            continue
        elif t[0] == "certificate":
            cur["certificate"] = t[1]
        elif t[0] == "salt":
            cur["salt"] = t[1]
        elif t[0] == "states":
            cur["states"] = t[1]
        elif t[0] == "verdict":
            cur["verdict"] = ("accepted", None) if t[1] == "accepted" \
                else ("refused", t[2])
        elif t[0] == "run":
            run = {"image": None, "bank": None}
            cur["runs"].append(run)
        elif t[0] == "image" and run is not None and len(t) == 2:
            run["image"] = t[1]
        elif t[0] == "bank" and run is not None:
            run["bank"] = None if t[1] == "none" else t[1]
    return cases


def section_corpus(work, root):
    print("== 4. the golden corpus, every case in full and sampled",
          flush=True)
    man = root / "certificates" / "MANIFEST"
    if not man.is_file():
        skip("the golden corpus", f"{root} has no certificates/MANIFEST")
        return
    cases = read_manifest(man)
    check(len(cases) > 0, f"{man} names {len(cases)} cases")
    version_2 = []
    for c in cases:
        data = (root / c["certificate"]).read_bytes()
        if data[:18] == b"cft-certificate 2\n":
            version_2.append(c["name"])
            continue
        salt = (root / c["salt"]).read_bytes() if c["salt"] else None
        progs = {i: ((root / r["image"]).read_bytes(),
                     (root / r["bank"]).read_bytes() if r["bank"] else None)
                 for i, r in enumerate(c["runs"])}
        sdir = root / c["states"]
        states = {}
        for f in sorted(os.listdir(sdir)):
            m = re.fullmatch(r"run-(\d+)-boundary-(\d+)\.bin", f)
            if m:
                states.setdefault(int(m.group(1)), {})[int(m.group(2))] = \
                    (sdir / f).read_bytes()
        audits_of(work, f"corpus {c['name']}", data, salt, progs, states,
                  None, c.get("verdict"))
    if version_2:
        section_corpus2(work, root, version_2)


def section_corpus2(work, root, names):
    """Section 4's version-2 cases (since version 2's C half): each case and
    control handed to both auditors as corpus.py's audit_inputs2 hands the
    golden one - its blocks, signature, keyring, superseded certificate and
    definition re-run - but no source and no regeneration, which cft-audit
    does not take (no_source_kwargs); the golden auditor handed the same is
    the verdict both must give. A case a writer makes is audited in full as
    the manifest hands it, sampled under the fixed seed, in full from every
    committed state, and from every state choosing the segments that carry
    no replay line, with no definition re-run - which is where cft-audit
    can accept a certificate whose replays it cannot make; a control, in
    full and from every state. How many keep the manifest's verdict handed
    no source is printed, and each that does not by the verdict both
    auditors give it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "corpus_for_audit_check", root / "certificates" / "corpus.py")
    CP = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(CP)
    corpus = CP.read_manifest()         # its own tree's, as CP.rp reads
    by = {c.name: c for c in corpus.cases}
    kept, moved = 0, {}
    for name in names:
        case = by[name]
        data = CP.rp(case.certificate[0]).read_bytes()
        try:
            parsed = cert.parse(data)
        except cert.Refusal:
            parsed = None           # a control the reader refuses
        modes = [("in full as the manifest hands it", False, None)]
        if case.writers != "golden":
            modes.append(("sampled", True, None))
        modes.append(("in full from every committed state", False, "every"))
        if parsed is not None and case.writers != "golden" and \
                any(r.replays for r in parsed.runs):
            modes.append(("from every state, the segments with no replay "
                          "line and no definition re-run", False,
                          "unreplayed"))
        for how, sampled, states_mode in modes:
            salt, progs, kw = CP.audit_inputs2(case, corpus, sampled,
                                               FIXED_SEED)
            if states_mode:
                try:
                    kw["states"] = {
                        r.index: {b: CP.rp(r.state_path(case, b)).read_bytes()
                                  for b in range(r.segments + 1)}
                        for r in case.runs}
                except OSError as e:
                    print(f"  NOTE  corpus {name}, {how}: not every state is "
                          f"committed ({e}); not made", flush=True)
                    continue
                kw.pop("choose", None)
                kw.pop("seed", None)
            if states_mode == "unreplayed":
                ch = {}
                for i, run in enumerate(parsed.runs):
                    reps = {x.segment for x in run.replays}
                    keep = [k for k in range(len(run.chain)) if k not in reps]
                    if reps and keep:
                        ch[i] = keep
                kw["choose"] = ch
                # the definition re-run is the auditor's own choice too,
                # and one this tool always refuses: this audit makes none
                kw.pop("define", None)
            kw, dropped = no_source_kwargs(kw)
            d = work / "corpus2" / f"{name}-{len(how)}-{int(sampled)}"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            g = golden(cert.audit, data, salt, progs, **kw)
            args = translate(d, data, salt, programs=progs, **kw)
            label = (f"corpus {name} (version 2), {how}"
                     + (f", without the {' and the '.join(dropped)}"
                        if dropped else "") + f": {describe(g)}")
            hold(args, None, g, label, d, quiet=False)
            if states_mode is None and not sampled:
                want = ("accepted", None) if case.verdict == "accepted" \
                    else ("refused", case.verdict)
                same_verdict = g[0] == want[0] and (
                    g[0] != "refused" or g[1][0] == want[1])
                if same_verdict:
                    kept += 1
                else:
                    got = "ACCEPTED" if g[0] == "accepted" else \
                        g[1][0] if g[0] == "refused" else str(g[1])
                    moved.setdefault(got, []).append(name)
    print(f"  NOTE  {len(names)} version-2 cases and controls handed to both "
          f"auditors as the manifest hands them but the source and the "
          f"regeneration: {kept} keep their manifest verdict, and "
          f"{sum(len(c) for c in moved.values())} do not, each given one "
          f"verdict by both auditors, as measured: "
          + "; ".join(f"{v} {len(c)} ({', '.join(c)})"
                      for v, c in sorted(moved.items())), flush=True)


# ---- section 5: the narrow builds -------------------------------------------

# The two narrow builds section 5 compiles, and audit_plants.py again:
# -> (optimization, defines). "narrow" is CFT_MAX_FORMAT=2 at the bigint
# that ceiling gives by default, 18 limbs (576 bits), which cft_config.h
# allows only with CFT_NO_TRANSCEND; CFT_NO_CONFORMANCE too, since the
# conformance replay calls the transcendentals and a tool must link
# (profiles-check compiles each profile, never links). "narrow64" is the
# same ceiling with CFT_BN_LIMBS=64, the combination cft_config.h
# documents as building: the full bigint under a lower ceiling (where
# verifier-A1 found its second narrow-build finding). It is compiled at
# -O1, which is enough for the few runs it makes: 5.8 s where -O2 took
# 9.2 s on the desktop (2026-09-29).
NARROW_BUILDS = {
    "narrow": ("-O2", ["-DCFT_MAX_FORMAT=2", "-DCFT_NO_TRANSCEND",
                       "-DCFT_NO_CONFORMANCE"]),
    "narrow64": ("-O1", ["-DCFT_MAX_FORMAT=2", "-DCFT_BN_LIMBS=64"]),
}


def fixture_function(fx):
    """The function under a pytest fixture. A fixture refuses to be
    called directly, and pytest has kept the function under a different
    name in different versions."""
    got = getattr(fx, "_get_wrapped_function", None)
    if got is not None:
        return got()
    got = getattr(fx, "__pytest_wrapped__", None)
    if got is not None:
        return got.obj
    return getattr(fx, "__wrapped__", fx)


def line_of(data, prefix, nth=0):
    """The body's line number of the nth line that starts with prefix."""
    return [i + 1 for i, ln in enumerate(cert.body_of(data).decode().split(
        "\n")) if ln.startswith(prefix)][nth]


def held_refused(exe_label, binary, workdir, args, name, loc, what,
                 read_args=None):
    """The build at TOOL must refuse `name` (the tool's own) at loc, in
    the audit and, given read_args, in --read too."""
    want = ("refused", (name, TOOL_OWN[name], loc))
    pairs = [("its audit", args)]
    if read_args is not None:
        pairs.append(("its --read", read_args))
    for how, a in pairs:
        rc, out, err = run_tool(a, cwd=workdir)
        t = tool_verdict(rc, out, err)
        where = ("line " + loc[0]) if loc[0] != "-" else ("run " + loc[1])
        check(t == want and out == "", f"  and {exe_label} refuses {how} "
              f"{name}, exit {TOOL_OWN[name]}, at {where}: {what}", f"{t}")
        record(workdir, a, None, [want[0], list(want[1])],
               f"{binary}: {what}, {how}, {name}", binary=binary)


def image_above(fp256):
    """The fp256 certificate's runs restated as fp128, the images left
    fp256: the golden refuses program-format at run 0, since a certificate
    that states one format for an image of another is not the one the
    image ran under; a narrow build cannot load the image to know that."""
    data, progs, states = fp256
    c = cert.parse(data)
    lie = cert.encode(dataclasses.replace(c, runs=tuple(
        dataclasses.replace(r, fmt="fp128") for r in c.runs)))
    return lie, progs, states


def section_narrow(work, cc, lib_src):
    print("== 5. two narrow builds at CFT_MAX_FORMAT=2, its own 576-bit "
          "bigint and CFT_BN_LIMBS=64: build-width, build-format at a run, "
          "a value or an image above fp128, and what each audits in full",
          flush=True)
    if not cc or not lib_src:
        skip("the narrow builds", "no --cc and --lib-src given (make -C host "
             "audittest gives both)")
        return
    d = work / "narrow"
    d.mkdir(parents=True, exist_ok=True)
    ext = ".exe" if os.name == "nt" else ""
    exe = d / ("cft-audit-narrow" + ext)
    t0 = time.perf_counter()
    opt, defs = NARROW_BUILDS["narrow"]
    built, err = compile_with(cc, lib_src, exe, defs, work, opt)
    if not check(built, f"cft-audit and libcft built at CFT_MAX_FORMAT=2 "
                 f"({time.perf_counter() - t0:.0f} s)", err.strip()[-400:]):
        return
    global TOOL
    wide, TOOL = TOOL, exe
    try:
        import test_cert as T
        data, progs, states = T.example_certificate()
        e = d / "example"
        e.mkdir(exist_ok=True)
        args = translate(e, data, T.SALT, programs=progs, states=states)
        rc, out, err = run_tool(args, cwd=e)
        t = tool_verdict(rc, out, err)
        acc = next(i + 1 for i, ln in enumerate(
            cert.body_of(data).decode().split("\n")) if
            ln.startswith("accuracy "))
        want = ("refused", ("build-width", TOOL_OWN["build-width"],
                            (str(acc), "-", "-", "-")))
        check(t == want, f"the page's example (accuracy 2): refused "
              f"build-width, exit 78, at its accuracy line {acc}", f"{t}")
        record(e, args, None, [want[0], list(want[1])], "narrow: the page's "
               "example refused build-width", binary="narrow")
        args = ["--read"] + args[:2] + ["--salt", e / "salt"]
        rc, out, err = run_tool(args, cwd=e)
        t = tool_verdict(rc, out, err)
        check(t == want, "its --read, the same", f"{t}")
        record(e, args, None, [want[0], list(want[1])], "narrow: --read of "
               "the page's example refused build-width", binary="narrow")
        # the same runs with accuracy 0: audited in full
        c = cert.parse(data)
        data0 = cert.encode(dataclasses.replace(c, accuracy=()))
        e0 = d / "example0"
        e0.mkdir(exist_ok=True)
        g = golden(cert.audit, data0, T.SALT, progs, states=states)
        args = translate(e0, data0, T.SALT, programs=progs, states=states)
        rc, out, err = run_tool(args, cwd=e0)
        agree, why = same(g, tool_verdict(rc, out, err))
        check(agree, "the same runs with accuracy 0: the narrow build audits "
              "them in full, the golden verdict", why)
        record(e0, args, None, list(g), "narrow: accuracy 0, audited in full",
               binary="narrow")
        # a run above the build's ceiling (verifier-A1's case): cft-segrun's
        # open lorenz63-rk4-fp256 certificate, two runs, accuracy 0, every
        # state handed. The golden auditor and the default tool ACCEPT it;
        # the narrow build refuses build-format at run 0's program-format
        # line, never program-image, a name for an input not the one
        # certified where the cause is the build
        data2, progs2, states2 = fp256_certificate(d / "fp256")
        g = golden(cert.audit, data2, None, progs2, states=states2)
        check(g[0] == "accepted", "an open fp256 certificate of two runs "
              "and accuracy 0: the golden audit accepts it", describe(g))
        e2 = d / "fp256-audit"
        e2.mkdir(exist_ok=True)
        args = translate(e2, data2, None, programs=progs2, states=states2)
        TOOL = wide
        hold(args, None, g, "  and the default tool accepts it, the same "
             "verdict", e2, quiet=False)
        TOOL = exe
        pf = str(line_of(data2, "program-format "))
        held_refused("the narrow build", "narrow", e2, args, "build-format",
                     (pf, "-", "-", "-"), "the fp256 certificate at run 0's "
                     "program-format line", ["--read"] + args[:2])
        # the same images under runs that state fp128: the reader passes
        # them, and step 4 would hand the library an fp256 image. The
        # golden and the default tool refuse program-format; a narrow
        # build refuses build-format at the run, never program-image
        lie, progs3, states3 = image_above((data2, progs2, states2))
        g = golden(cert.audit, lie, None, progs3, states=states3)
        check(g == ("refused", ("program-format", 4, ("-", "0", "-", "-"))),
              "the fp256 images under runs stated fp128: the golden refuses "
              "program-format at run 0", describe(g))
        e3 = d / "fp256-stated-fp128"
        e3.mkdir(exist_ok=True)
        args3 = translate(e3, lie, None, programs=progs3, states=states3)
        TOOL = wide
        hold(args3, None, g, "  and the default tool, the same verdict", e3,
             quiet=False)
        TOOL = exe
        held_refused("the narrow build", "narrow", e3, args3, "build-format",
                     ("-", "0", "-", "-"), "the fp256 images under runs "
                     "stated fp128")
        # verifier-A1's second case, lor with entry 1's value in fp256:
        # here the accuracy line comes first, build-width at it
        L = fixture_function(T.lor)()
        lor_cases = lor_above(L)
        acc = str(line_of(L.data, "accuracy "))
        e4 = d / "lor-rounded-fp256"
        e4.mkdir(exist_ok=True)
        data4 = lor_cases[0][1]
        args4 = translate(e4, data4, T.SALT, programs=L.progs,
                          states=L.states, choose=LOR_CHOOSE)
        held_refused("the narrow build", "narrow", e4, args4, "build-width",
                     (acc, "-", "-", "-"), "lor with entry 1 rounded fp256, "
                     "at its accuracy line, before any value")
    finally:
        TOOL = wide
    section_narrow64(work, cc, lib_src, d, T, L, lor_cases,
                     (data2, progs2, states2), (lie, progs3, states3))


# lor's segments a case above the ceiling is audited on: one a run
# (verifier-A1's choice), so that the golden's re-runs stay few
LOR_CHOOSE = {0: [0], 1: [0], 2: [0]}


def lor_above(L):
    """lor (test_cert.py) with entry 1's value re-made in fp256, rounded
    to nearest and enclosed by its two neighbours: formats above a
    CFT_MAX_FORMAT=2 build's, which cert.audit and the default tool
    accept. -> [(label, bytes), ...]"""
    q1 = L.values[1]
    vals = (("rounded fp256 rne", cert.Value(
                "rounded", fmt="fp256", rnd="rne",
                bits=cert.round_rational("fp256", q1, "rne"))),
            ("enclosed fp256", cert.Value(
                "enclosed", fmt="fp256",
                lo=cert.round_rational("fp256", q1, "rdn"),
                hi=cert.round_rational("fp256", q1, "rup"))))
    out = []
    for label, v in vals:
        es = list(L.entries)
        es[1] = dataclasses.replace(es[1], value=v)
        out.append((label, cert.encode(dataclasses.replace(
            L.cert, accuracy=tuple(es)))))
    return out


def section_narrow64(work, cc, lib_src, d, T, L, lor_cases, fp256, image):
    """The same ceiling at CFT_BN_LIMBS=64: exact values within the
    ceiling audited in full, and build-format wherever a format above it
    would reach the library - a value's line (verifier-A1's second case),
    a run's program-format line, and an image's header."""
    global TOOL
    exe = d / ("cft-audit-narrow64" + (".exe" if os.name == "nt" else ""))
    t0 = time.perf_counter()
    opt, defs = NARROW_BUILDS["narrow64"]
    built, err = compile_with(cc, lib_src, exe, defs, work, opt)
    if not check(built, f"cft-audit and libcft built at CFT_MAX_FORMAT=2 "
                 f"with CFT_BN_LIMBS=64, {opt} "
                 f"({time.perf_counter() - t0:.0f} s)", err.strip()[-400:]):
        return
    wide, TOOL = TOOL, exe
    try:
        # exact values within the ceiling: audited in full, the golden's
        # verdict - lor's four entries (every method, form and scope), and
        # the page's example, which the other narrow build refuses
        # build-width
        ex_data, ex_progs, ex_states = T.example_certificate()
        for name, label, data, progs, states in (
                ("lor", "lor, its four entries", L.data, L.progs, L.states),
                ("example", "the page's example (accuracy 2)", ex_data,
                 ex_progs, ex_states)):
            salt = T.SALT
            e = d / ("n64-" + name)
            e.mkdir(exist_ok=True)
            g = golden(cert.audit, data, salt, progs, states=states)
            args = translate(e, data, salt, programs=progs, states=states)
            rc, out, err = run_tool(args, cwd=e)
            agree, why = same(g, tool_verdict(rc, out, err))
            check(agree and g[0] == "accepted", f"{label}: the wide-bigint "
                  f"build audits it in full, the golden's verdict", why)
            record(e, args, None, list(g), f"narrow64: {label}, in full",
                   binary="narrow64")
        # a value above the ceiling: build-format at its line
        vline = str(line_of(L.data, "value ", 1))
        for label, data in lor_cases:
            e = d / ("n64-lor-" + label.split()[0])
            e.mkdir(exist_ok=True)
            g = golden(cert.audit, data, T.SALT, L.progs, states=L.states,
                       choose=LOR_CHOOSE)
            check(g[0] == "accepted", f"lor with entry 1 {label}: the golden "
                  f"audit accepts it", describe(g))
            args = translate(e, data, T.SALT, programs=L.progs,
                             states=L.states, choose=LOR_CHOOSE)
            TOOL = wide
            hold(args, None, g, "  and the default tool, the same verdict", e,
                 quiet=False)
            TOOL = exe
            held_refused("the wide-bigint build", "narrow64", e, args,
                         "build-format", (vline, "-", "-", "-"),
                         f"lor with entry 1 {label}, at the value's line",
                         ["--read"] + args[:4])
        # a run above the ceiling, and an image above it
        data2, progs2, states2 = fp256
        e = d / "n64-fp256"
        e.mkdir(exist_ok=True)
        args = translate(e, data2, None, programs=progs2, states=states2)
        held_refused("the wide-bigint build", "narrow64", e, args,
                     "build-format", (str(line_of(data2, "program-format ")),
                                      "-", "-", "-"),
                     "the fp256 certificate at run 0's program-format line",
                     ["--read"] + args[:2])
        lie, progs3, states3 = image
        e = d / "n64-fp256-stated-fp128"
        e.mkdir(exist_ok=True)
        args = translate(e, lie, None, programs=progs3, states=states3)
        held_refused("the wide-bigint build", "narrow64", e, args,
                     "build-format", ("-", "0", "-", "-"),
                     "the fp256 images under runs stated fp128")
    finally:
        TOOL = wide


def fp256_certificate(d):
    """cft-segrun's open certificate of lorenz63-rk4 at fp256: one lane,
    a main run of 1 segment and its half-step run of 2 (segrun_check's
    program, cut short), with every boundary state. -> (bytes, programs,
    states)"""
    import segrun_check as sc
    sc.TOOL = SEGRUN
    prog = sc.ode_program("lorenz63-rk4", "fp256", sc.manifest())
    main, half = prog.runs[0], prog.runs[1]
    lane = main.init[:3]
    runs = [dataclasses.replace(main, init=lane, segments=1,
                                params=(("members", 1),)),
            dataclasses.replace(half, init=lane, segments=2,
                                params=(("members", 1),))]
    prog = dataclasses.replace(prog, runs=runs)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    paths = sc.write_inputs(d, prog)
    out, sdir = d / "c.cert", d / "states"
    r = subprocess.run([str(SEGRUN)] + [str(a) for a in sc.tool_args(
        prog, paths, out, sdir, None)], capture_output=True, text=True,
        timeout=TOOL_TIMEOUT)
    if r.returncode != 0:
        raise RuntimeError(f"cft-segrun: {r.stderr.strip()[-300:]}")
    progs = {i: (s.image, s.bank) for i, s in enumerate(runs)}
    states = {i: {b: (sdir / f"run-{i}-boundary-{b}.bin").read_bytes()
                  for b in range(s.segments + 1)}
              for i, s in enumerate(runs)}
    return out.read_bytes(), progs, states


# ---- section 6: the numerics against Python's integers and the golden -------

def compile_with(cc, lib_src, out, defs, work, opt="-O2"):
    """cc on the library's sources and tools/audit.c, from host/. A
    compiler named by its path finds its own programs (cc1, as, ld) and
    their DLLs beside it: its directory goes on PATH for the compiler's
    process alone, never for this one. -> (ok, stderr)"""
    env = dict(os.environ)
    first = cc.split()[0]
    if os.path.dirname(first):
        env["PATH"] = os.path.dirname(first) + os.pathsep + env.get("PATH",
                                                                    "")
    cmd = cc.split() + ["-std=c99", opt] + defs + ["-Iinclude"] + \
        lib_src.split() + ["tools/audit.c", "-o", str(out)]
    r = subprocess.run(cmd, cwd=str(HOST), capture_output=True, text=True,
                       env=env)
    return r.returncode == 0 and out.is_file(), r.stderr


def _hexelem(fmt, bits):
    return f"{bits:0{FORMATS[fmt].width // 4}x}"


def _rattext(q):
    return cert.rational_text(q)


def numeric_cases(rng):
    """(probe line, the answer Python's integers or the golden model give)
    for every operation the probe has, random under a fixed seed and at
    the edges each one has."""
    import math
    from fractions import Fraction
    from cft_golden import chars
    from cft_golden import softfloat as sf
    out = []

    def nat(bits):
        return (1 << (bits - 1)) | rng.getrandbits(bits - 1) if bits > 1 \
            else 1

    # gcd and divmod, up to 2,047 bits: the widest an in-rule step makes
    fib = [0, 1]
    while fib[-1].bit_length() < 2040:
        fib.append(fib[-1] + fib[-2])
    pairs = [(0, nat(100)), (nat(100), 0), (0, 1), (1, 1), (6, 4),
             (1 << 2046, 1 << 1000), ((1 << 2047) - 1, (1 << 2047) - 1),
             (fib[-1], fib[-2]), (nat(2047), 1), (nat(2047), nat(2047)),
             (nat(2017), nat(2020)), (nat(33), nat(2047))]
    for _ in range(150):
        pairs.append((nat(rng.randint(1, 2047)), nat(rng.randint(1, 2047))))
    for _ in range(60):
        g = nat(rng.randint(2, 1000))
        x, y = nat(rng.randint(1, 1000)), nat(rng.randint(1, 1000))
        if (g * x).bit_length() <= 2047 and (g * y).bit_length() <= 2047:
            pairs.append((g * x, g * y))
    for a, b in pairs:
        out.append((f"gcd {a:x} {b:x}", f"{math.gcd(a, b):x}"))
        if b:
            q, r = divmod(a, b)
            out.append((f"divmod {a:x} {b:x}", f"{q:x} {r:x}"))

    # exact arithmetic: in-rule operands, reduced results of any width the
    # bigint holds (a product up to 2,046 bits, a sum up to 2,047)
    def rat():
        k = rng.random()
        if k < 0.1:
            return Fraction(0)
        if k < 0.3:     # dyadic, as an element's value is
            q = Fraction(nat(rng.randint(1, 900)),
                         1 << rng.randint(0, 1000))
        else:
            q = Fraction(nat(rng.randint(1, 1023)),
                         nat(rng.randint(1, 1023)))
        while abs(q.numerator).bit_length() > 1023 or \
                q.denominator.bit_length() > 1023:
            q = Fraction(q.numerator >> 1 or 1, q.denominator)
        return -q if rng.random() < 0.5 else q
    ca, cb = (1 << 600) + 1, (1 << 601) - 1
    rats = [(Fraction(1, ca), Fraction(1, cb)), (Fraction(1, cb),
                                                 Fraction(-1, cb)),
            (Fraction(0), Fraction(0)), (Fraction(-1, 3), Fraction(1, 3)),
            (Fraction((1 << 1023) - 1), Fraction((1 << 1023) - 1)),
            (Fraction(1, (1 << 1023) - 1), Fraction(-1, (1 << 1023) - 3))]
    rats += [(rat(), rat()) for _ in range(250)]
    for x, y in rats:
        out.append((f"add {_rattext(x)} {_rattext(y)}", _rattext(x + y)))
        out.append((f"sub {_rattext(x)} {_rattext(y)}", _rattext(x - y)))
        out.append((f"mul {_rattext(x)} {_rattext(y)}", _rattext(x * y)))
        out.append((f"cmp {_rattext(x)} {_rattext(y)}",
                    str((x > y) - (x < y))))
        out.append((f"cmp {_rattext(x)} {_rattext(x)}", "0"))

    # rounding an in-rule rational into each format, each direction
    names = ("fp32", "fp64", "fp128", "fp256")
    rnds = ("rne", "rtz", "rdn", "rup", "rmm")

    def value(fmt, bits):
        return cert.element_fraction(fmt, bits)[1]
    for fi, fmt in enumerate(names):
        f = FORMATS[fmt]
        qs = [rat() for _ in range(40)]
        # at and between the format's own values: exact, a tie, a third
        for _ in range(12):
            e = rng.randint(-120, 120) if fmt == "fp32" else \
                rng.randint(-1000, 1000)
            ulp = Fraction(2) ** (e - f.prec)
            q0 = nat(f.prec) * ulp
            qs += [q0, q0 + ulp / 2, -q0 - ulp / 2, q0 + ulp / 3]
        qs += [Fraction(1 << 200), Fraction(1, 1 << 300),
               Fraction(1, 1 << 150), Fraction(3, 1 << 151),
               Fraction(-1, 1 << 150), Fraction(1, 1 << 1022),
               Fraction(1, (1 << 1022) + 1), Fraction((1 << 1023) - 1),
               Fraction(1, 3 << 900), Fraction(1, (1 << 900) - 1)]
        for q in qs:
            if abs(q.numerator).bit_length() > 1023 or \
                    q.denominator.bit_length() > 1023:
                continue
            for ri, rn in enumerate(rnds):
                if rng.random() < 0.5 and q not in qs[40:]:
                    continue
                out.append((f"round {fi} {ri} {_rattext(q)}",
                            _hexelem(fmt, cert.round_rational(fmt, q, rn))))

    # elements: exact values, widening, decimals, halves
    def specials(fmt):
        """+0, -0, +inf, -inf, a quiet NaN, two signaling ones, the
        smallest and largest subnormal, the smallest normal, the largest
        finite, minus the smallest subnormal, and one"""
        f = FORMATS[fmt]
        w, mw = f.width, f.man_w
        ew = w - 1 - mw
        emask = ((1 << ew) - 1) << mw
        top = 1 << (w - 1)
        one = ((1 << (ew - 1)) - 1) << mw
        return [0, top, emask, top | emask, emask | (1 << (mw - 1)),
                emask | 1, top | emask | 5, 1, (1 << mw) - 1, 1 << mw,
                emask - 1, top | 1, one]
    for fi, fmt in enumerate(names):
        w = FORMATS[fmt].width
        bits = specials(fmt) + [rng.getrandbits(w) for _ in range(30)]
        # values near one, whose exact values are in the rule
        bits += [(((1 << (w - 2)) - (1 << FORMATS[fmt].man_w)) |
                  rng.getrandbits(FORMATS[fmt].man_w)) for _ in range(10)]
        for b in bits:
            kind, v = cert.element_fraction(fmt, b)
            if kind != "finite":
                want = "nonfinite"
            elif abs(v.numerator).bit_length() > 1023 or \
                    v.denominator.bit_length() > 1023:
                want = (f"width {abs(v.numerator).bit_length()} "
                        f"{v.denominator.bit_length()}")
            else:
                want = _rattext(v)
            out.append((f"exact {fi} {_hexelem(fmt, b)}", want))
            if fi < 3:
                out.append((f"widen {fi} {_hexelem(fmt, b)}",
                            _hexelem(names[fi + 1], cert.widen(fmt, b))))
            out.append((f"decimal {fi} {_hexelem(fmt, b)}",
                        chars.to_decimal(FORMATS[fmt], b, 0)[0]))
            if kind == "finite" and v != 0:
                half = sf.mul(FORMATS[fmt], b, chars.from_decimal(
                    FORMATS[fmt], "0.5", sf.RND_RNE)[0])[0]
                for x in (half, half + 1, half - 1 if half else 0, b):
                    x &= (1 << w) - 1
                    kx, vx = cert.element_fraction(fmt, x)
                    out.append((f"half {fi} {_hexelem(fmt, x)} "
                                f"{_hexelem(fmt, b)}",
                                "1" if kx == "finite" and vx == v / 2
                                else "0"))
    return out


PROBE = {}


def build_probe(work, cc, lib_src):
    """The probe build of tools/audit.c (-DCFT_AUDIT_PROBE), once for the
    sections that run it. -> its path, or None where it did not build."""
    if "exe" in PROBE:
        return PROBE["exe"]
    d = work / "probe"
    d.mkdir(parents=True, exist_ok=True)
    exe = d / ("cft-audit-probe" + (".exe" if os.name == "nt" else ""))
    t0 = time.perf_counter()
    built, err = compile_with(cc, lib_src, exe, ["-DCFT_AUDIT_PROBE"], work)
    check(built, f"the probe, tools/audit.c with -DCFT_AUDIT_PROBE, built "
          f"({time.perf_counter() - t0:.0f} s)", err[-400:])
    PROBE["exe"] = exe if built else None
    return PROBE["exe"]


def section_numerics(work, cc, lib_src):
    print("== 6. the tool's numerics - its division, gcd, exact arithmetic "
          "and rounding, an element's exact value, and the library's "
          "widening and exact decimal - against Python's integers and the "
          "golden model", flush=True)
    if not cc or not lib_src:
        skip("the tool's numerics", "no --cc and --lib-src given (make -C "
             "host audittest gives both)")
        return
    import random
    exe = build_probe(work, cc, lib_src)
    if exe is None:
        return
    cases = numeric_cases(random.Random(20260929))
    t0 = time.perf_counter()
    r = subprocess.run([str(exe)], input="".join(c + "\n" for c, _ in cases),
                       capture_output=True, text=True, timeout=600)
    got = r.stdout.split("\n")
    tally = {}
    wrong = []
    for i, (line, want) in enumerate(cases):
        op = line.split(" ")[0]
        t = tally.setdefault(op, [0, 0])
        t[0] += 1
        if i < len(got) and got[i] == want:
            t[1] += 1
        else:
            wrong.append(f"{line[:120]}: the probe says "
                         f"{(got[i] if i < len(got) else '(nothing)')[:80]!r}"
                         f", Python {want[:80]!r}")
    check(r.returncode == 0, f"the probe ran {len(cases)} operations "
          f"({time.perf_counter() - t0:.1f} s)", r.stderr.strip()[-300:])
    for op, (n, good) in sorted(tally.items()):
        check(n == good, f"{op}: {good} of {n} as Python's integers and the "
              f"golden model give them",
              "; ".join(w for w in wrong if w.startswith(op))[:600])


# ---- section 7: Ed25519 and SHA-512 against their vectors -------------------

# FIPS 180-4's SHA-512 examples, as NIST publishes them (the examples with
# intermediate values, and FIPS 180-2's appendix C for the million 'a's),
# and the empty message: (what, the message or (byte, count), the digest).
# Each is held to Python's hashlib as well, which would show a digest typed
# wrong here.
SHA512_PUBLISHED = (
    ("the empty message", b"",
     "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce"
     "47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"),
    ('"abc"', b"abc",
     "ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a"
     "2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f"),
    ("the 448-bit message",
     b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
     "204a8fc6dda82f0a0ced7beb8e08a41657c16ef468b228a8279be331a703c335"
     "96fd15c13b1b07f9aa1d3bea57789ca031ad85c7a71dd70354ec631238ca3445"),
    ("the 896-bit message",
     b"abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmn"
     b"hijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu",
     "8e959b75dae313da8cf4f72814fc143f8f7779c6eb9f7fa17299aeadb6889018"
     "501d289e4900f7e4331b99dec4b5433ac7d329eeb6dd26545e96e55b874be909"),
    ("a million 'a's", (0x61, 1000000),
     "e718483d0ce769644e2e42c7bc15b4638e1f98b13b2044285632a803afa973eb"
     "de0ff244877ea60a4cb0432ce577c31beb009c5c2c49aa2e4eadb217ad8cc09b"),
)


def ed25519_cases(rng):
    """(probe line, the answer, the group it counts in): every vector
    python/tests/test_ed25519.py carries, each answer the golden model's
    (python/cft_golden/ed25519.py) and the test's own - the RFC's five,
    every bit of each signature, the message's and the key's edges,
    another key's signature, the eight keys of small order with verifier
    VCV2B's forgery, the six encodings of no point as key and as R, the
    three S at or above L, signatures under a key with a small-order part
    (the cofactored equation, odd k among them), the mixed keys, the
    page's version-2 test vector - and random keys the golden model signs;
    then SHA-512's published examples and every length across a block's
    padding edge against hashlib."""
    import hashlib as H
    import test_ed25519 as TE
    from cft_golden import ed25519 as E
    out = []

    def h(b):
        return b.hex() if b else "-"

    def verify(pk, m, s, group):
        want = "1" if E.verify(pk, m, s) else "0"
        out.append((f"ed-verify {pk.hex()} {h(m)} {s.hex()}", want, group))
        return want

    for v in TE.VECTORS:
        sk, pk, msg, sig = TE._v(v[0])
        assert verify(pk, msg, sig, "the RFC's five verified") == "1"
        for i in range(8 * len(sig)):
            bad = bytearray(sig)
            bad[i // 8] ^= 1 << (i % 8)
            verify(pk, msg, bytes(bad), "every bit of their signatures")
        edits = [msg + b"\x00"]
        for i in ((0, len(msg) - 1) if msg else ()):
            bad = bytearray(msg)
            bad[i] ^= 1
            edits.append(bytes(bad))
        for m in edits:
            assert verify(pk, m, sig, "their messages edited") == "0"
        for i in (0, 31):
            bad = bytearray(pk)
            bad[i] ^= 1
            assert verify(bytes(bad), msg, sig, "their keys edited") == "0"
        out.append((f"ed-key {pk.hex()}", "0", "their keys: a prime-order "
                    "part"))
    _sk1, _pk1, msg, sig1 = TE._v("TEST 2")
    _sk2, pk2, _m, _s = TE._v("TEST 3")
    assert verify(pk2, msg, sig1, "another key's signature") == "0"
    _sk, pk, msg, good = TE._v("TEST 1")
    for _what, s in TE.S_EDGES:
        assert verify(pk, msg, bytes.fromhex(s), "S at or above L") == "0"
    for _what, _n, enc in TE.UNDECODABLE:
        out.append((f"ed-key {enc}", "1", "encodings of no point"))
        out.append((f"ed-decode {enc}", "0", "encodings of no point"))
        out.append((f"ed-small {enc}", "0", "encodings of no point"))
        b = bytes.fromhex(enc)
        assert verify(b, msg, good, "no point, as key or as R") == "0"
        assert verify(pk, msg, b + good[32:], "no point, as key or as R") \
            == "0"
    r = 1234567
    forged = E.encode_point(E._mul(r, E.B)) + r.to_bytes(32, "little")
    for _what, key in TE.SMALL_ORDER:
        out.append((f"ed-key {key}", "2", "the eight keys of small order"))
        out.append((f"ed-small {key}", "1", "the eight keys of small order"))
        for m in (b"", b"any message", b"cft-signature 1\x00" + bytes(32)):
            assert verify(bytes.fromhex(key), m, forged, "VCV2B's forgery "
                          "under each") == "0"
    t2 = (0, E.P - 1, 1, 0)
    s, prefix = E._expand(bytes(range(32, 64)))
    pub2 = E.encode_point(E._add(E._mul(s, E.B), t2))
    odd = 0
    for i in range(64):
        m = b"cofactor " + bytes([i])
        rr = E._sha512_int(prefix, m) % E.L
        r_enc = E.encode_point(E._mul(rr, E.B))
        k = E._sha512_int(r_enc, pub2, m) % E.L
        odd += k % 2
        assert verify(pub2, m, r_enc + ((rr + k * s) % E.L).to_bytes(
            32, "little"), "the cofactored equation (A + T, T of order "
            "2)") == "1"
    assert odd, "no odd k: the cofactorless equation would not part"
    a = E._mul(s, E.B)
    for _w, hx in TE.SMALL_ORDER:
        mixed = E.encode_point(E._add(a, E.decode_point(bytes.fromhex(hx))))
        out.append((f"ed-key {mixed.hex()}", "0", "keys with a small-order "
                    "part"))
    rows = dict(ln.split(None, 1) for ln in re.search(
        r"```[a-z]*\n(.*?)```", DOC.read_text(encoding="utf-8")[
            DOC.read_text(encoding="utf-8").index(
                "<!-- the version-2 test vectors -->"):], re.S).group(1)
        .strip().split("\n"))
    assert verify(bytes.fromhex(rows["test-key"]),
                  bytes.fromhex(rows["signed-message"]),
                  bytes.fromhex(rows["signature"]),
                  "the page's version-2 test vector") == "1"
    for _ in range(40):
        sk = bytes(rng.getrandbits(8) for _ in range(32))
        m = bytes(rng.getrandbits(8) for _ in range(rng.randint(0, 300)))
        pk = E.public_key(sk)
        sg = E.sign(sk, m)
        verify(pk, m, sg, "random keys the golden model signs")
        bad = bytearray(sg)
        bad[rng.randrange(64)] ^= 1 << rng.randrange(8)
        verify(pk, m, bytes(bad), "random keys the golden model signs")
    for what, m, digest in SHA512_PUBLISHED:
        if isinstance(m, tuple):
            data = bytes([m[0]]) * m[1]
            line = f"sha512rep {m[0]:02x} {m[1]}"
        else:
            data, line = m, f"sha512 {h(m)}"
        assert H.sha512(data).hexdigest() == digest, what
        out.append((line, digest, "SHA-512's published examples"))
    for n in list(range(0, 300)) + [1000, 1023, 1024, 4095]:
        m = bytes(rng.getrandbits(8) for _ in range(n))
        out.append((f"sha512 {h(m)}", H.sha512(m).hexdigest(),
                    "SHA-512 at every length across its padding"))
    return out


def section_ed25519(work, cc, lib_src):
    print("== 7. Ed25519 verification and SHA-512 in C (tools/ed25519.h, "
          "tools/sha512.h) against every vector test_ed25519.py carries, "
          "FIPS 180-4's examples and hashlib, through the probe build",
          flush=True)
    if not cc or not lib_src:
        skip("Ed25519 and SHA-512", "no --cc and --lib-src given (make -C "
             "host audittest gives both)")
        return
    import random
    exe = build_probe(work, cc, lib_src)
    if exe is None:
        return
    t0 = time.perf_counter()
    cases = ed25519_cases(random.Random(20261002))
    t1 = time.perf_counter()
    r = subprocess.run([str(exe)], input="".join(c + "\n" for c, _w, _g in
                                                 cases),
                       capture_output=True, text=True, timeout=600)
    got = r.stdout.split("\n")
    check(r.returncode == 0, f"the probe ran {len(cases)} operations "
          f"({time.perf_counter() - t1:.1f} s; the golden model's answers "
          f"{t1 - t0:.1f} s)", r.stderr.strip()[-300:])
    tally = {}
    for i, (line, want, group) in enumerate(cases):
        t = tally.setdefault(group, [0, 0, []])
        t[0] += 1
        if i < len(got) and got[i] == want:
            t[1] += 1
        else:
            t[2].append(f"{line[:100]}: the probe says "
                        f"{(got[i] if i < len(got) else '(nothing)')[:40]!r}, "
                        f"the golden {want[:40]!r}")
    for group, (n, good, wrong) in tally.items():
        check(n == good, f"{group}: {good} of {n}", "; ".join(wrong)[:600])


# ---- main -------------------------------------------------------------------

def main():
    global TOOL, SEGRUN, RECORD
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tool", required=True, help="the cft-audit binary")
    ap.add_argument("--segrun", required=True, help="the cft-segrun binary")
    ap.add_argument("--cc", help="the C compiler, for the narrow build")
    ap.add_argument("--lib-src", help="libcft's sources, relative to host/ "
                    "(make print-src), for the narrow build")
    ap.add_argument("--keep", help="write everything here and keep it")
    ap.add_argument("--record", help="keep every tool run as a case here, "
                    "for audit_plants.py")
    ap.add_argument("--sections", default="1,2,3,4,5,6,7",
                    help="which sections to run (default all)")
    ap.add_argument("--corpus-root", help="the tree whose certificates/ "
                    "holds the golden corpus (default this one)")
    args = ap.parse_args()
    TOOL = Path(args.tool).resolve()
    SEGRUN = Path(args.segrun).resolve()
    for p, what in ((TOOL, "cft-audit"), (SEGRUN, "cft-segrun")):
        if not p.is_file():
            sys.exit(f"audit_check: {p} is not built (make -C host {what})")
    if args.record:
        RECORD = Path(args.record).resolve()
        RECORD.mkdir(parents=True, exist_ok=True)
    work = Path(args.keep).resolve() if args.keep else \
        Path(tempfile.mkdtemp(prefix="audit-check-"))
    work.mkdir(parents=True, exist_ok=True)
    sections = set(args.sections.split(","))
    t_all = time.perf_counter()
    print(f"audit_check: {TOOL}", flush=True)
    print(f"  work in {work}", flush=True)
    if "1" in sections:
        section_tool(work)
        print("== the binary, ignored by git", flush=True)
        hold_ignored()
    if "2" in sections:
        section_shadow(work)
    drawn = None
    if "3" in sections:
        drawn = section_segrun(work)
    if "1" in sections and drawn is not None:
        print("== 1b. a seed the operating system draws", flush=True)
        drawn_seed_checks(work, drawn)
    if "4" in sections:
        section_corpus(work, Path(args.corpus_root).resolve()
                       if args.corpus_root else ROOT)
    if "5" in sections:
        section_narrow(work, args.cc, args.lib_src)
    if "6" in sections:
        section_numerics(work, args.cc, args.lib_src)
    if "7" in sections:
        section_ed25519(work, args.cc, args.lib_src)
    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print(f"audit_check: {CHECKS} checks, {len(FAILED)} failed, "
          f"{len(SKIPS)} skipped, {time.perf_counter() - t_all:.0f} s"
          + (f", {RECORDED[0]} cases recorded" if RECORD else ""),
          flush=True)
    if FAILED:
        for w in FAILED[:60]:
            print(f"  FAILED: {w}")
        if len(FAILED) > 60:
            print(f"  ... and {len(FAILED) - 60} more")
        return 1
    print("AUDIT CHECK OK" if not SKIPS else
          "AUDIT CHECK OK, with the skips above named")
    return 0


if __name__ == "__main__":
    sys.exit(main())
