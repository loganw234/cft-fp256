# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Certificates, version 2: the golden implementation.

docs/CERTIFICATES.md, "Version 2", is the specification; this file is its
executable form, beside cert.py, which is version 1's and stays so. A
version-2 certificate says what a run MEANS where version 1 says what the
machine did (the lead's decision and Logan's, 2026-10-02):

  * each segment's per-lane flags (R23), as a hash a segment;
  * a lane the machine marked (R24's raise with bit 7: its routine could
    not decide its last bit) REPLAYED by the definition - the source's
    reference interpreter, lang.run, at the run's format - with the raw
    segment on a replay line and the corrected one certified, so that a
    version-2 chain is the definition's wherever it stands;
  * the source a run was compiled from or is defined by, checked by
    recompiling with cftc or by the language, and `wider-source`, the
    same source compiled one format wider;
  * the definition it is claimed under - the conformance profile, now
    versioning the program model too, and the language's version - so
    that a failure under an auditor whose definition does not cover the
    certificate's is `definition-differs`, the auditor's own limit;
  * provenance - the issuer and its key, the times, the host's OS and
    architecture, the writer and its runtime, the compiler's build, the
    device's platform, XRT and clock and serial, the environment, how
    the initial state was made, the certificate it supersedes - each
    REPORTED, with the issuer and the device serial written only on
    request;
  * a detached Ed25519 signature over the body hash, for either version.

What is here, beside version 1's names in cert.py:
  * read_body()     a version-2 body's lines -> a Certificate, STRICT;
                    cert.parse dispatches here on the magic line
  * encode()        a Certificate -> the bytes, read back before they are
                    returned
  * run_chain(), certify_run()   the golden writer: segments by seq.run,
                    each block of per-lane flags, each marked lane
                    replayed by a Definition
  * source_graph(), Definition, source_lines()   the source: its step
                    graph at a format (the format override), its replays
  * signature_file(), check_signature_file()   the detached signature
  * audit()         every check, in the specification's order; cert.audit
                    dispatches here on the magic line

Every refusal is a cert.Refusal whose name is in cert.REFUSALS, version 2's
names among them.
"""

import hashlib
import hmac
import os
import platform
import re
import time
from dataclasses import dataclass, field, replace
from fractions import Fraction

from . import cert as V1
from . import ed25519
from . import seq
from .cert import (DEC_MAX, LADDER, MODES, Entry, Identity, Refusal,
                   Value, sha256, state_bytes, state_hash, state_values)
from .formats import FORMATS
from .profile import VERSION as PROFILE

MAGIC = "cft-certificate"
VERSION = 2

# The tags. Version 1's are kept (cert.py): a state, its salt commitment
# and the three streams hash as they do there, so one run's version-1 and
# version-2 certificates carry the same state and stream hashes, and a
# replay line's raw end is a state like any other. New objects take new
# tags, each ending in a NUL as version 1's do.
TAG_LANE_FLAGS = b"cft-certificate 2 lane-flags\x00"
TAG_SIGNATURE = b"cft-signature 1\x00"

LANE_MARK = 0x80            # R23's byte: [7] the mark
LANE_IEEE = 0x1F            #             [4:0] the five IEEE flags
LANE_STATUS = 0x60          #             [6:5] STATUS[5:4], one place up
STATUS_MARK = 1 << 6        # STATUS[6], CFT_STATUS_MARKED

# The words that stand for an absent value (rule 2 of the study): a field
# not recorded, not existing for this backend, held back by the producer,
# or (for `initial`) handed as data. A text is never one of them.
WORDS = ("none", "unknown", "withheld", "given")

# Every variable libcft and cft-segrun read (getenv in host/src and
# host/tools/segrun.c, and libcft's instrument seeds): the writer's list
# for the `environment` lines. test_cert2.py holds it to the code's
# calls, so that a new variable cannot be missed.
ENVIRONMENT_NAMES = (
    "CFT_DIVSQRT_FULL", "CFT_DIVSQRT_SEQ", "CFT_SEGRUN_PLANT",
    "CFT_TIMEOUT_MS", "CFT_TRANSCEND_MINPREC", "CFT_XRT_BIND",
    "CFT_XRT_CAPS", "CFT_XRT_MASK_ADDR_OVERRIDE", "CFT_XRT_PROGRAM_CUTS",
    "CFT_XRT_REDUCE_BC", "CFT_XRT_TILES", "CFT_XRT_TILE_ORDER",
    "CFT_XRT_TRACE", "CFT_XRT_WITNESS", "XCL_EMULATION_MODE")

MAX_GENERATOR_ARGS = 16
MAX_TEXT = 255

# The methods: version 1's three and `wider-source`, an estimate on a
# wider-source run.
METHOD_KIND = dict(V1.METHOD_KIND, **{"wider-source": "estimate"})
METHOD_RUN = dict(V1.METHOD_RUN, **{"wider-source": "wider-source"})
RUN_KINDS = ("main", "half-step", "wider", "wider-source")


# ---- encodings ---------------------------------------------------------------

_HEX = {n: re.compile(r"[0-9a-f]{%d}" % n) for n in (8, 64, 128)}
_DEC = re.compile(r"0|[1-9][0-9]*")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_ENV = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_LANG_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_TEXT = re.compile(r"(?:[!-$&-~]|%[0-9A-F]{2})+")
_TIME = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2})"
                   r":([0-9]{2})Z")
_VERSION = re.compile(r"([1-9][0-9]{0,18})(?:\.([1-9][0-9]{0,18}))?")
_BUILD_COMMIT = re.compile(r"commit=(?:[0-9a-f]{40}|[0-9a-f]{64})")


def text_token(value):
    """A text's one spelling: its UTF-8 bytes, each from 0x21 to 0x7E but
    `%` standing as itself and every other byte `%` and two uppercase hex
    digits - so a space is %20 and `Logan W.` is `Logan%20W.` - 1 to 255
    characters once encoded. A text equal to one of the words is refused
    (`malformed`), so that a word is never a value."""
    if not isinstance(value, str):
        raise Refusal("malformed", f"a text is a string, not a "
                                   f"{type(value).__name__}")
    if value in WORDS:
        raise Refusal("malformed", f"the text {value!r} is one of the words "
                                   f"{', '.join(WORDS)}, which stand for an "
                                   f"absent value; a text is never one")
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError:
        raise Refusal("malformed", "a text is UTF-8, and this string has no "
                                   "UTF-8 spelling") from None
    tok = "".join(chr(b) if 0x21 <= b <= 0x7E and b != 0x25 else f"%{b:02X}"
                  for b in raw)
    if not 1 <= len(tok) <= MAX_TEXT:
        raise Refusal("malformed", f"a text is 1 to {MAX_TEXT} characters "
                                   f"once encoded; this one is {len(tok)}")
    return tok


def read_text(tok):
    """The string a token spells as a text, or None where it is not a
    text's one spelling: a byte that may stand as itself encoded, a
    lowercase hex digit, a lone `%`, bytes that are not UTF-8, or more
    than 255 characters."""
    if not 1 <= len(tok) <= MAX_TEXT or not _TEXT.fullmatch(tok):
        return None
    out = bytearray()
    i = 0
    while i < len(tok):
        if tok[i] == "%":
            b = int(tok[i + 1:i + 3], 16)
            if 0x21 <= b <= 0x7E and b != 0x25:
                return None             # a byte that may stand as itself
            out.append(b)
            i += 3
        else:
            out.append(ord(tok[i]))
            i += 1
    try:
        value = bytes(out).decode("utf-8")
    except UnicodeDecodeError:
        return None
    return None if value in WORDS else value


def _days(year, month):
    if month == 2:
        leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
        return 29 if leap else 28
    return 30 if month in (4, 6, 9, 11) else 31


def read_time(tok):
    """A time's fields (year, month, day, hour, minute, second) - one
    spelling of RFC 3339's date-time: UTC, `T` and `Z` in upper case, no
    fraction, a real Gregorian date, seconds 00 to 59 - or None."""
    m = _TIME.fullmatch(tok)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(g) for g in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= _days(y, mo) and h <= 23
            and mi <= 59 and s <= 59):
        return None
    return (y, mo, d, h, mi, s)


def time_text(fields):
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % tuple(fields)


def version_text(v):
    """A version's one spelling: the major, then `.` and the minor where
    the minor is not 0 - `1`, `1.2`."""
    major, minor = v
    return f"{major}" if minor == 0 else f"{major}.{minor}"


def read_version(tok):
    """(major, minor) of a version token, or None."""
    m = _VERSION.fullmatch(tok)
    if not m:
        return None
    major = int(m.group(1))
    minor = int(m.group(2)) if m.group(2) else 0
    if major > DEC_MAX or minor > DEC_MAX:
        return None
    return (major, minor)


def covers(auditor, certified):
    """Does a definition at version `auditor` cover a certificate's
    `certified` (a version's text, `none` or `unknown`)? `none` - no run
    names a source, so no check reads the language - is covered by every
    version, and `unknown` by none. Otherwise the majors are equal and the
    auditor's minor is at least the certificate's."""
    if certified == "none":
        return True
    v = read_version(certified) if isinstance(certified, str) else None
    if v is None:
        return False
    return auditor[0] == v[0] and auditor[1] >= v[1]


def _language_version():
    from .lang.version import VERSION as LANG
    return LANG


# ---- the structure -------------------------------------------------------------

@dataclass(frozen=True)
class Provenance:
    """The header's new lines, in their order. A text is held as its
    string, a word as the word itself (a text is never one), a time as
    its token. The defaults are the privacy defaults: the issuer and the
    device serial are withheld until the owner asks for them, and the
    rest is unknown until a writer measures it."""
    profile: str = "unknown"            # a version, or unknown
    language: str = "unknown"           # a version, none or unknown
    device_platform: str = "unknown"    # a text, none or unknown
    device_xrt: str = "unknown"         # a text, none or unknown
    device_clock: object = "unknown"    # Hz, an integer >= 1; none; unknown
    device_serial: str = "withheld"     # a text, none, unknown or withheld
    writer: object = "unknown"          # (name, build-id or "unknown"), or
                                        # "unknown"
    writer_runtime: str = "unknown"     # a text, none or unknown
    compiler_build: str = "unknown"     # a build-id, none or unknown
    replay_methods: tuple = ()          # ((run, "golden"), (run, "image",
                                        # digest), ...), runs increasing
    certificate_id: str = "none"        # a text, or none
    issuer: str = "withheld"            # a text, none or withheld
    issuer_key: str = "none"            # 64 hex digits, or none
    host_os: str = "unknown"            # a text, unknown or withheld
    host_arch: str = "unknown"          # a text, unknown or withheld
    started: str = "unknown"            # a time, or unknown
    finished: str = "unknown"
    issued: str = "unknown"
    supersedes: str = "none"            # a body hash, or none
    environment: tuple = ()             # ((NAME, value), ...), increasing
    initial: tuple = ("given",)         # ("given",) or ("generator", name,
                                        # (text, ...))


@dataclass(frozen=True)
class Source:
    """What a run says of its source: its SHA-256, its file name, its step
    graph's SHA-256 at the run's format, the compiler that made the image
    (None where the image is not claimed to be its compile), and the run
    values of its params, by name, each a literal in the language's
    canonical spelling."""
    digest: str
    name: str                   # a text, or none
    graph: str
    compiler: object            # None, or (name, output version, target)
    params: tuple = ()          # ((name, literal), ...), names increasing


@dataclass(frozen=True)
class Segment:
    start: str
    end: str
    flags: int
    status: int
    lanes: str = None           # the block's hash; None in a `no` run


@dataclass(frozen=True)
class Replay:
    """One segment in which the machine marked a lane: how many it marked,
    how many the replay changed, and the hashes of its raw end state and
    raw block, before the replay."""
    segment: int
    marked: int
    changed: int
    raw_end: str
    raw_lanes: str


@dataclass(frozen=True)
class Run:
    kind: str                   # main, half-step, wider or wider-source
    fmt: str
    image: str
    digest: str
    source: object              # a Source, or None for `source none`
    lanes: int
    steps: int
    streams: tuple
    parameters: tuple
    lane_flags: bool
    chain: tuple                # (Segment, ...)
    replays: tuple              # (Replay, ...), segments increasing
    output: str
    h_slots: tuple = ()


@dataclass(frozen=True)
class Certificate:
    mode: str
    salt_commitment: str
    identity: Identity
    provenance: Provenance
    runs: tuple
    accuracy: tuple
    version: int = VERSION


# ---- the hashes ----------------------------------------------------------------

def lane_flags_hash(salt, block):
    """The hash of a segment's per-lane flags: n bytes, lane i's at byte i,
    behind TAG_LANE_FLAGS - an HMAC under the salt in a keyed certificate,
    plain SHA-256 in an open one, as version 1 hashes a state."""
    return V1._mac(salt, TAG_LANE_FLAGS + bytes(block))


def signature_message(body_hash):
    """What a signature signs: `cft-signature 1`, a NUL, then the 32 bytes
    of the body hash - so a signature over a certificate is a signature
    over nothing else."""
    return TAG_SIGNATURE + bytes.fromhex(body_hash)


# ---- the writer: the lines -------------------------------------------------

def _spell(value, words, what):
    """A field that holds a text or one of `words`."""
    if value in words:
        return value
    if value in WORDS:
        raise Refusal("malformed", f"{what}: the word {value!r} does not "
                                   f"stand on this line, which takes "
                                   f"{', '.join(words)} or a text")
    return text_token(value)


def _header_lines(p):
    L = [f"profile {p.profile}", f"language {p.language}",
         f"device-platform {_spell(p.device_platform, ('none', 'unknown'), 'device-platform')}",
         f"device-xrt {_spell(p.device_xrt, ('none', 'unknown'), 'device-xrt')}",
         f"device-clock {p.device_clock}",
         f"device-serial {_spell(p.device_serial, ('none', 'unknown', 'withheld'), 'device-serial')}"]
    if p.writer == "unknown":
        L.append("writer unknown")
    else:
        name, build = p.writer
        if not isinstance(name, str) or name in WORDS:
            raise Refusal("malformed", f"a writer's name is a name, and not "
                                       f"one of the words: {name!r}")
        L.append(f"writer {name} {build}")
    L += [f"writer-runtime {_spell(p.writer_runtime, ('none', 'unknown'), 'writer-runtime')}",
          f"compiler-build {p.compiler_build}",
          f"replay-methods {len(p.replay_methods)}"]
    for m in p.replay_methods:
        if m[1:] == ("golden",):
            L.append(f"replay-method {m[0]} golden")
        else:
            L.append(f"replay-method {m[0]} image {m[2]}")
    L += [f"certificate-id {_spell(p.certificate_id, ('none',), 'certificate-id')}",
          f"issuer {_spell(p.issuer, ('none', 'withheld'), 'issuer')}",
          f"issuer-key {p.issuer_key}",
          f"host-os {_spell(p.host_os, ('unknown', 'withheld'), 'host-os')}",
          f"host-arch {_spell(p.host_arch, ('unknown', 'withheld'), 'host-arch')}",
          f"started {p.started}", f"finished {p.finished}",
          f"issued {p.issued}", f"supersedes {p.supersedes}",
          f"environment {len(p.environment)}"]
    for name, value in p.environment:
        L.append(f"env {name} {text_token(value)}")
    if p.initial == ("given",):
        L.append("initial given")
    else:
        _g, name, args = p.initial
        L.append(" ".join(["initial", "generator", name]
                          + [text_token(a) for a in args]))
    return L


def _run_lines(i, run):
    if run.kind == "half-step":
        L = [f"run {i} half-step h-slots {len(run.h_slots)} "
             + " ".join(str(s) for s in run.h_slots)]
    else:
        L = [f"run {i} {run.kind}"]
    L += [f"program-format {run.fmt}", f"program-image {run.image}",
          f"program-digest {run.digest}"]
    s = run.source
    if s is None:
        L.append("source none")
    else:
        L += [f"source {s.digest}",
              f"source-name {_spell(s.name, ('none',), 'source-name')}",
              f"graph {s.graph}"]
        if s.compiler is None:
            L.append("compiler none")
        else:
            name, ver, target = s.compiler
            L.append(f"compiler {name} {ver} {text_token(target)}")
        L.append(f"source-params {len(s.params)}")
        L += [f"source-param {n} {lit}" for n, lit in s.params]
    L += [f"lanes {run.lanes}", f"steps {run.steps}",
          f"stream-a {run.streams[0]}", f"stream-b {run.streams[1]}",
          f"stream-c {run.streams[2]}",
          f"parameters {len(run.parameters)}"]
    L += [f"parameter {n} {v}" for n, v in run.parameters]
    L.append(f"lane-flags {'yes' if run.lane_flags else 'no'}")
    L.append(f"segments {len(run.chain)}")
    for k, sg in enumerate(run.chain):
        line = (f"segment {k} start {sg.start} end {sg.end} flags {sg.flags} "
                f"status {sg.status}")
        if sg.lanes is not None:
            line += f" lanes {sg.lanes}"
        L.append(line)
    L.append(f"replays {len(run.replays)}")
    L += [f"replay {r.segment} marked {r.marked} changed {r.changed} "
          f"raw-end {r.raw_end} raw-lanes {r.raw_lanes}"
          for r in run.replays]
    L.append(f"output {run.output}")
    return L


def _body_lines(cert):
    idn = cert.identity
    caps = (" ".join(idn.device_caps) if isinstance(idn.device_caps, tuple)
            else idn.device_caps)
    L = [f"{MAGIC} {VERSION}", f"mode {cert.mode}"]
    if cert.mode == "keyed":
        L.append(f"salt-commitment {cert.salt_commitment}")
    L += [f"build-id {idn.build_id}", f"backend {idn.backend}",
          f"device-xclbin {idn.device_xclbin}",
          f"device-version {idn.device_version}", f"device-caps {caps}",
          f"device-tiles {idn.device_tiles}"]
    L += _header_lines(cert.provenance)
    L.append(f"runs {len(cert.runs)}")
    for i, run in enumerate(cert.runs):
        L += _run_lines(i, run)
    L.append(f"accuracy {len(cert.accuracy)}")
    for j, e in enumerate(cert.accuracy):
        L += [f"entry {j} {e.method}", f"kind {e.kind}", f"uses {e.uses}",
              "scope max-lanes" if e.lane is None else f"scope lane {e.lane}"]
        if e.method == "drift":
            L.append(f"quantity {e.label} terms {len(e.terms)}")
            for c, slots in e.terms:
                L.append(" ".join(["term", V1.rational_text(c)]
                                  + [f"s{s}" for s in slots]))
        L.append(V1._value_text(e.value))
    L.append("end")
    return L


def _normalized(cert):
    """The same certificate with every sequence a tuple, as read_body
    returns it."""
    p = cert.provenance
    p = replace(p, replay_methods=tuple(tuple(m) for m in p.replay_methods),
                environment=tuple(tuple(e) for e in p.environment),
                initial=(("given",) if tuple(p.initial) == ("given",) else
                         (p.initial[0], p.initial[1], tuple(p.initial[2]))),
                writer=(p.writer if p.writer == "unknown" else
                        tuple(p.writer)))
    runs = []
    for r in cert.runs:
        src = r.source
        if src is not None:
            src = replace(src, compiler=(None if src.compiler is None else
                                         tuple(src.compiler)),
                          params=tuple(tuple(x) for x in src.params))
        runs.append(replace(
            r, source=src, streams=tuple(r.streams),
            parameters=tuple((n, v) for n, v in r.parameters),
            chain=tuple(s if isinstance(s, Segment) else Segment(*s)
                        for s in r.chain),
            replays=tuple(x if isinstance(x, Replay) else Replay(*x)
                          for x in r.replays),
            h_slots=tuple(r.h_slots)))
    acc = tuple(Entry(e.method, e.kind, e.uses, e.lane, e.value, e.label,
                      tuple((c, tuple(sl)) for c, sl in e.terms))
                for e in cert.accuracy)
    idn = cert.identity
    if isinstance(idn.device_caps, list):
        idn = replace(idn, device_caps=tuple(idn.device_caps))
    return Certificate(cert.mode, cert.salt_commitment, idn, p, tuple(runs),
                       acc)


def encode(cert):
    """The certificate's bytes, hash line included. As version 1's writer
    does, it reads its text back with the strict reader before returning
    it, and the read-back must equal the object: a value it cannot spell,
    a word where a text belongs, a form rule broken (a mark in a STATUS,
    a replay in a `no` run) is refused by the name the reader gives it."""
    try:
        cert = _normalized(cert)
        body = ("\n".join(_body_lines(cert)) + "\n").encode("ascii")
    except Refusal:
        raise
    except (AttributeError, IndexError, KeyError, TypeError,
            UnicodeEncodeError, ValueError) as e:
        raise Refusal("malformed",
                      f"the writer was handed a certificate object it cannot "
                      f"spell ({type(e).__name__}: {e})") from None
    data = body + f"hash {sha256(body)}\n".encode("ascii")
    back = V1.parse(data)
    if back != cert:
        where = V1._first_difference(cert, back) or "the certificate"
        raise Refusal("malformed",
                      f"the writer was handed {where}, which reads back as "
                      f"something else: a value of the wrong type or "
                      f"spelling")
    return data


# ---- the strict reader ---------------------------------------------------------

_ORDER = ("cft-certificate", "mode", "salt-commitment", "build-id", "backend",
          "device-xclbin", "device-version", "device-caps", "device-tiles",
          "profile", "language", "device-platform", "device-xrt",
          "device-clock", "device-serial", "writer", "writer-runtime",
          "compiler-build", "replay-methods", "replay-method",
          "certificate-id", "issuer", "issuer-key", "host-os", "host-arch",
          "started", "finished", "issued", "supersedes", "environment",
          "env", "initial", "runs",
          "run", "program-format", "program-image", "program-digest",
          "source", "source-name", "graph", "compiler", "source-params",
          "source-param", "lanes", "steps", "stream-a", "stream-b",
          "stream-c", "parameters", "parameter", "lane-flags", "segments",
          "segment", "replays", "replay", "output",
          "accuracy", "entry", "kind", "uses", "scope", "quantity", "term",
          "value", "end", "hash")
RANK = {k: i for i, k in enumerate(_ORDER)}
STARTERS = ("run", "accuracy", "entry", "end")
BLOCK_OF = {"run": 1, "accuracy": 2, "entry": 3, "end": 4}
REPEATING = ("run", "entry")
BLOCK_TYPE = {k: (0 if RANK[k] < RANK["run"] else
                  1 if RANK[k] < RANK["accuracy"] else
                  2 if k == "accuracy" else
                  3 if RANK[k] < RANK["end"] else
                  4 if k == "end" else 5) for k in RANK}


class _Reader(V1._Reader):
    """Version 1's reader, its token readers and its rules for a line that
    is not the one expected, over version 2's order."""

    def _block_rest(self):
        out = []
        for i in range(self.pos, len(self.lines)):
            k = self.lines[i][0]
            if i > self.pos and k in STARTERS:
                break
            out.append(k)
        return out

    def classify(self, expected):
        k = self.key()
        if k is None:
            return Refusal("line-missing",
                           f"'{expected}' is missing: the body ends first",
                           line=self.ln())
        t = BLOCK_TYPE[k]
        if k in STARTERS:
            if t > self.block or (t == self.block and k in REPEATING):
                return self.fail("line-missing",
                                 f"'{expected}' is missing: '{k}' begins a "
                                 f"later block here")
            return self.fail("line-unexpected",
                             f"'{k}' has no place here: its block is "
                             f"already read, and '{expected}' belongs here")
        if t < self.block or (t == self.block and (
                expected in STARTERS or RANK[k] < RANK[expected])):
            return self.fail("line-unexpected",
                             f"'{k}' has no place here: its place is "
                             f"earlier, and '{expected}' belongs here")
        if expected in self._block_rest():
            return self.fail("line-order",
                             f"'{k}' comes before '{expected}', which "
                             f"belongs first")
        return self.fail("line-missing", f"'{expected}' is missing; "
                                         f"'{k}' is here instead")

    # -- the certificate ------------------------------------------------

    def certificate(self):
        # the dispatcher sent this body here because its first line is
        # exactly `cft-certificate 2`
        for i, toks in enumerate(self.lines):
            if toks[0] not in RANK:
                raise self.fail("unknown-line",
                                f"'{toks[0][:80]}' is not a line of "
                                f"version 2", i)
        self.pos = 1
        mode = self.expect("mode", 2)[1]
        if mode not in MODES:
            raise self.fail("mode-unknown",
                            f"mode {mode[:40]!r}: this reader knows 'keyed' "
                            f"and 'open'", self.pos - 1)
        at = [i for i, t in enumerate(self.lines) if t[0] == "salt-commitment"]
        if mode == "open" and at:
            raise self.fail("commitment-unexpected",
                            "an open certificate has no salt and so no "
                            "salt commitment", at[0])
        if mode == "keyed" and not at:
            raise self.fail("commitment-missing",
                            "a keyed certificate commits to its salt on the "
                            "line after its mode, and this one has no "
                            "salt-commitment line")
        sc = None
        if mode == "keyed":
            sc = self.hexn(self.expect("salt-commitment", 2)[1], 64,
                           "the salt commitment", self.pos - 1)
        idn = self.identity()
        prov = self.provenance()
        self._replays_at = {}
        R = self.count_line("runs", "run", 1, False, stop=("accuracy", "end"))
        runs = tuple(self.run(i) for i in range(R))
        self.replay_methods_hold(prov, runs)
        A = self.count_line("accuracy", "entry", 0, False, stop=("end",))
        self.block = BLOCK_OF["accuracy"]
        acc = tuple(self.entry(j) for j in range(A))
        self.expect("end", 1)
        self.block = BLOCK_OF["end"]
        if self.pos != len(self.lines):
            raise self.fail("line-unexpected",
                            f"'{self.key()}' after 'end'; the body ends at "
                            f"'end'")
        return Certificate(mode, sc, idn, prov, runs, acc)

    # -- the header's new lines -------------------------------------------

    def one(self, key):
        """The one value of a two-token line."""
        return self.expect(key, 2)[1]

    def text_or(self, key, words):
        """A line holding a text or one of `words`."""
        tok = self.one(key)
        at = self.pos - 1
        if tok in words:
            return tok
        if tok in WORDS:
            raise self.malformed(f"'{key}' takes {', '.join(words)} or a "
                                 f"text; the word {tok!r} does not stand "
                                 f"here", at)
        v = read_text(tok)
        if v is None:
            raise self.malformed(f"'{key}' {tok[:80]!r} is not a text in its "
                                 f"one spelling: 1 to {MAX_TEXT} characters, "
                                 f"each byte from 0x21 to 0x7E but '%' as "
                                 f"itself and every other '%' and two "
                                 f"uppercase hex digits, UTF-8", at)
        return v

    def version_or(self, key, words):
        tok = self.one(key)
        if tok in words or read_version(tok) is not None:
            return tok
        raise self.malformed(f"'{key}' {tok[:80]!r} is not a version - a "
                             f"major, then '.' and a minor where the minor "
                             f"is not 0, no leading zeros - nor "
                             f"{' or '.join(words)}", self.pos - 1)

    def build_or(self, key, words):
        toks = self.expect(key)
        at = self.pos - 1
        if len(toks) == 2 and toks[1] in words:
            return toks[1]
        if (len(toks) == 4 and _BUILD_COMMIT.fullmatch(toks[1])
                and toks[2] in ("tracked=clean", "tracked=modified")
                and toks[3] in ("untracked=none", "untracked=present")):
            return " ".join(toks[1:])
        raise self.malformed(f"'{key}' is a build in cft_build_id()'s "
                             f"grammar - 'commit=<40 or 64 lowercase hex> "
                             f"tracked=<clean|modified> "
                             f"untracked=<none|present>' - or "
                             f"{' or '.join(words)}", at)

    def time_or_unknown(self, key):
        tok = self.one(key)
        if tok == "unknown" or read_time(tok) is not None:
            return tok
        raise self.malformed(f"'{key}' {tok[:80]!r} is not a time - "
                             f"YYYY-MM-DDTHH:MM:SSZ, UTC, a real date, "
                             f"seconds 00 to 59 - nor 'unknown'",
                             self.pos - 1)

    def provenance(self):
        profile = self.version_or("profile", ("unknown",))
        language = self.version_or("language", ("none", "unknown"))
        platform_ = self.text_or("device-platform", ("none", "unknown"))
        xrt = self.text_or("device-xrt", ("none", "unknown"))
        tok = self.one("device-clock")
        if tok in ("none", "unknown"):
            clock = tok
        else:
            clock = self.dec(tok, "the device clock in Hz", lo=1,
                             i=self.pos - 1)
        serial = self.text_or("device-serial", ("none", "unknown",
                                                "withheld"))
        toks = self.expect("writer")
        at = self.pos - 1
        if toks == ["writer", "unknown"]:
            writer = "unknown"
        elif len(toks) in (3, 5) and _NAME.fullmatch(toks[1]) and \
                toks[1] not in WORDS:
            rest = toks[2:]
            if rest == ["unknown"]:
                writer = (toks[1], "unknown")
            elif (len(rest) == 3 and _BUILD_COMMIT.fullmatch(rest[0])
                  and rest[1] in ("tracked=clean", "tracked=modified")
                  and rest[2] in ("untracked=none", "untracked=present")):
                writer = (toks[1], " ".join(rest))
            else:
                raise self.malformed("'writer <name> <build>': the build in "
                                     "cft_build_id()'s grammar, or "
                                     "'unknown'", at)
        else:
            raise self.malformed("'writer unknown', or 'writer <name> "
                                 "<build>' with a name of [a-z][a-z0-9-]*, "
                                 "at most 64, that is not one of the words",
                                 at)
        runtime = self.text_or("writer-runtime", ("none", "unknown"))
        cbuild = self.build_or("compiler-build", ("none", "unknown"))
        methods = self.methods()
        cid = self.text_or("certificate-id", ("none",))
        issuer = self.text_or("issuer", ("none", "withheld"))
        tok = self.one("issuer-key")
        if tok != "none" and not _HEX[64].fullmatch(tok):
            raise self.malformed(f"'issuer-key' {tok[:80]!r} is not an "
                                 f"Ed25519 public key - 64 lowercase hex "
                                 f"digits - nor 'none'", self.pos - 1)
        key = tok
        hos = self.text_or("host-os", ("unknown", "withheld"))
        harch = self.text_or("host-arch", ("unknown", "withheld"))
        t_at = self.pos
        started = self.time_or_unknown("started")
        finished = self.time_or_unknown("finished")
        issued = self.time_or_unknown("issued")
        self.provenance_order(t_at, started, finished, issued)
        tok = self.one("supersedes")
        if tok != "none" and not _HEX[64].fullmatch(tok):
            raise self.malformed(f"'supersedes' {tok[:80]!r} is not a body "
                                 f"hash - 64 lowercase hex digits - nor "
                                 f"'none'", self.pos - 1)
        sup = tok
        env = self.environment()
        initial = self.initial()
        return Provenance(profile, language, platform_, xrt, clock, serial,
                          writer, runtime, cbuild, methods, cid, issuer, key,
                          hos, harch, started, finished, issued, sup, env,
                          initial)

    def provenance_order(self, at, started, finished, issued):
        """Where the times are known, started <= finished <= issued: each
        pair of known times in order, refused at the later line."""
        t = [read_time(x) if x != "unknown" else None
             for x in (started, finished, issued)]
        names = ("started", "finished", "issued")
        for a, b in ((0, 1), (1, 2), (0, 2)):
            if t[a] is not None and t[b] is not None and t[a] > t[b]:
                raise self.fail("provenance-order",
                                f"'{names[a]}' is after '{names[b]}': a run "
                                f"starts before it finishes, and a "
                                f"certificate is issued after its runs",
                                at + b)

    def methods(self):
        n = self.count_line("replay-methods", "replay-method", 0, True)
        out = []
        self._method_at = {}
        for _ in range(n):
            toks = self.expect("replay-method")
            at = self.pos - 1
            if len(toks) == 3 and toks[2] == "golden":
                how = ("golden",)
            elif len(toks) == 4 and toks[2] == "image":
                how = ("image", self.hexn(toks[3], 64, "a replay image's "
                                          "digest", at))
            else:
                raise self.malformed("'replay-method <run> golden' or "
                                     "'replay-method <run> image <digest>'",
                                     at)
            r = self.dec(toks[1], "a replay method's run", i=at)
            if out and r <= out[-1][0]:
                if r == out[-1][0]:
                    raise self.fail("line-unexpected",
                                    f"a replay method for run {r} again", at)
                raise self.fail("line-order",
                                f"the replay method for run {r} comes after "
                                f"run {out[-1][0]}'s; runs are in increasing "
                                f"order", at)
            out.append((r,) + how)
            self._method_at[r] = at
        return tuple(out)

    def environment(self):
        n = self.count_line("environment", "env", 0, True)
        out = []
        for _ in range(n):
            toks = self.expect("env", 3)
            at = self.pos - 1
            if not _ENV.fullmatch(toks[1]):
                raise self.malformed(f"variable name {toks[1][:80]!r} is not "
                                     f"[A-Z][A-Z0-9_]*, at most 64", at)
            if out and toks[1] <= out[-1][0]:
                if toks[1] == out[-1][0]:
                    raise self.fail("line-unexpected",
                                    f"variable {toks[1]} again", at)
                raise self.fail("line-order",
                                f"variable {toks[1]} comes after "
                                f"{out[-1][0]}; names are in increasing "
                                f"order", at)
            v = read_text(toks[2])
            if v is None:
                raise self.malformed(f"variable {toks[1]}'s value is not a "
                                     f"text in its one spelling", at)
            out.append((toks[1], v))
        return tuple(out)

    def initial(self):
        toks = self.expect("initial")
        at = self.pos - 1
        if toks == ["initial", "given"]:
            return ("given",)
        if len(toks) >= 3 and toks[1] == "generator":
            if not _NAME.fullmatch(toks[2]):
                raise self.malformed(f"generator name {toks[2][:80]!r} is "
                                     f"not [a-z][a-z0-9-]*, at most 64", at)
            args = toks[3:]
            if len(args) > MAX_GENERATOR_ARGS:
                raise self.malformed(f"a generator takes at most "
                                     f"{MAX_GENERATOR_ARGS} arguments", at)
            vals = []
            for a in args:
                v = read_text(a)
                if v is None:
                    raise self.malformed(f"generator argument {a[:80]!r} is "
                                         f"not a text in its one spelling",
                                         at)
                vals.append(v)
            return ("generator", toks[2], tuple(vals))
        raise self.malformed("'initial given', or 'initial generator <name> "
                             "<text> ...'", at)

    # -- a run ----------------------------------------------------------

    def run(self, i):
        self.member_index("run", i, stop=("accuracy", "end"),
                          consecutive=False)
        toks = self.expect("run")
        self.block = BLOCK_OF["run"]
        at = self.pos - 1
        h_slots = ()
        if len(toks) < 3:
            raise self.malformed("'run' is 'run <index> main', 'run <index> "
                                 "half-step h-slots <n> ...', 'run <index> "
                                 "wider' or 'run <index> wider-source'", at)
        kind = toks[2]
        if kind == "main":
            if i != 0 or len(toks) != 3:
                raise self.malformed("run 0, and only run 0, is 'run 0 "
                                     "main'", at)
        elif kind in ("wider", "wider-source"):
            if i == 0 or len(toks) != 3:
                raise self.malformed(f"'run <index> {kind}' is an auxiliary "
                                     f"run, never run 0, and takes nothing "
                                     f"more", at)
        elif kind == "half-step":
            if i == 0:
                raise self.malformed("run 0 is the main run; a half-step "
                                     "run is auxiliary", at)
            if len(toks) < 5 or toks[3] != "h-slots":
                raise self.malformed("'run <index> half-step h-slots <n> "
                                     "<slot> ...'", at)
            n = self.dec(toks[4], "the h-slot count", lo=1,
                         hi=seq.KADDR_KX, i=at)
            have = len(toks) - 5
            if have != n:
                raise self.fail("count", f"'h-slots {n}' and {have} slot "
                                         f"index{'es' if have != 1 else ''} "
                                         f"follow", at)
            h = [self.dec(t, "an h-slot", hi=seq.KADDR_KX - 1, i=at)
                 for t in toks[5:]]
            for a, b in zip(h, h[1:]):
                if b <= a:
                    raise self.malformed("h-slot indices are strictly "
                                         "increasing", at)
            h_slots = tuple(h)
        else:
            raise self.malformed(f"run kind {kind[:40]!r} is not main, "
                                 f"half-step, wider or wider-source", at)
        fmt = self.word(self.expect("program-format", 2)[1], LADDER,
                        "the program format")
        image = self.hexn(self.expect("program-image", 2)[1], 64,
                          "the image digest", self.pos - 1)
        digest = self.hexn(self.expect("program-digest", 2)[1], 64,
                           "the program digest", self.pos - 1)
        source = self.source()
        lanes = self.dec(self.expect("lanes", 2)[1], "lanes", lo=1,
                         i=self.pos - 1)
        steps = self.dec(self.expect("steps", 2)[1], "steps", lo=1,
                         i=self.pos - 1)
        streams = tuple(self.hexn(self.expect(f"stream-{s}", 2)[1], 64,
                                  f"stream {s}'s hash", self.pos - 1)
                        for s in "abc")
        params = self.parameters()
        lf = self.word(self.expect("lane-flags", 2)[1], ("yes", "no"),
                       "lane-flags") == "yes"
        S = self.count_line("segments", "segment", 1, True)
        chain = []
        for k in range(S):
            self.member_index("segment", k)
            toks = self.expect("segment")
            at = self.pos - 1
            want = 12 if lf else 10
            if len(toks) != want:
                raise self.malformed(
                    "'segment <k> start <hash> end <hash> flags <n> status "
                    "<n>" + (" lanes <hash>' in a run that says lane-flags "
                             "yes" if lf else "' in a run that says "
                             "lane-flags no, with no lanes pair"), at)
            names = (toks[2], toks[4], toks[6], toks[8]) + \
                ((toks[10],) if lf else ())
            if names != ("start", "end", "flags", "status") + \
                    (("lanes",) if lf else ()):
                raise self.malformed("'segment <k> start <hash> end <hash> "
                                     "flags <n> status <n>"
                                     + (" lanes <hash>'" if lf else "'"), at)
            status = self.dec(toks[9], "status", hi=(1 << 32) - 1, i=at)
            seg = Segment(self.hexn(toks[3], 64, "a start hash", at),
                          self.hexn(toks[5], 64, "an end hash", at),
                          self.dec(toks[7], "flags", hi=31, i=at), status,
                          self.hexn(toks[11], 64, "a lane-flags hash", at)
                          if lf else None)
            if status & STATUS_MARK:
                raise self.fail("marked",
                                f"segment {k}'s STATUS carries STATUS[6], "
                                f"the mark: a version-2 segment is the "
                                f"definition's, so every mark in it is "
                                f"resolved by a replay; the machine's own "
                                f"values, mark and all, are version 1's", at)
            chain.append(seg)
        replays = self.replays(i, S, lanes, lf, source)
        output = self.hexn(self.expect("output", 2)[1], 64, "the output hash",
                           self.pos - 1)
        return Run(kind, fmt, image, digest, source, lanes, steps, streams,
                   params, lf, tuple(chain), replays, output, h_slots)

    def source(self):
        tok = self.one("source")
        at = self.pos - 1
        if tok == "none":
            return None
        digest = self.hexn(tok, 64, "the source's SHA-256", at)
        name = self.text_or("source-name", ("none",))
        graph = self.hexn(self.one("graph"), 64, "the step graph's SHA-256",
                          self.pos - 1)
        toks = self.expect("compiler")
        at = self.pos - 1
        if toks == ["compiler", "none"]:
            compiler = None
        elif len(toks) == 4 and _NAME.fullmatch(toks[1]) and \
                toks[1] not in WORDS:
            ver = self.dec(toks[2], "the compiler's output version", i=at)
            target = read_text(toks[3])
            if target is None:
                raise self.malformed(f"the compiler's target {toks[3][:80]!r}"
                                     f" is not a text in its one spelling",
                                     at)
            compiler = (toks[1], ver, target)
        else:
            raise self.malformed("'compiler none', or 'compiler <name> "
                                 "<output version> <target>'", at)
        P = self.count_line("source-params", "source-param", 0, True)
        params = []
        for _ in range(P):
            toks = self.expect("source-param", 3)
            at = self.pos - 1
            if not _LANG_NAME.fullmatch(toks[1]):
                raise self.malformed(f"source param {toks[1][:80]!r} is not "
                                     f"a name of the language: a letter or "
                                     f"'_', then letters, digits and '_'", at)
            if params and toks[1] <= params[-1][0]:
                if toks[1] == params[-1][0]:
                    raise self.fail("line-unexpected",
                                    f"source param {toks[1]} again", at)
                raise self.fail("line-order",
                                f"source param {toks[1]} comes after "
                                f"{params[-1][0]}; names are in increasing "
                                f"byte order", at)
            params.append((toks[1], toks[2]))
        return Source(digest, name, graph, compiler, tuple(params))

    def parameters(self):
        P = self.count_line("parameters", "parameter", 0, True)
        params = []
        for _ in range(P):
            toks = self.expect("parameter", 3)
            at = self.pos - 1
            if not _NAME.fullmatch(toks[1]):
                raise self.malformed(f"parameter name {toks[1][:80]!r} is "
                                     f"not [a-z][a-z0-9-]*, at most 64", at)
            if params and toks[1] <= params[-1][0]:
                if toks[1] == params[-1][0]:
                    raise self.fail("line-unexpected",
                                    f"parameter {toks[1]!r} again", at)
                raise self.fail("line-order",
                                f"parameter {toks[1]!r} comes after "
                                f"{params[-1][0]!r}; names are in "
                                f"increasing order", at)
            v = self.dec(toks[2], "a parameter", i=at)
            if toks[1] == V1.DEPTH_PARAMETER and not V1._is_depth(v):
                raise self.malformed(f"parameter {V1.DEPTH_PARAMETER} {v}: a "
                                     f"run's scratch depth is a power of two "
                                     f"in 1..{seq.SCRATCH_D_MAX}", at)
            params.append((toks[1], v))
        return tuple(params)

    def replays(self, run_index, S, lanes, lf, source):
        at0 = self.pos
        m = self.count_line("replays", "replay", 0, True)
        self._replays_at[run_index] = at0
        if m and not lf:
            raise self.fail("replay-lane-flags",
                            f"run {run_index} has replay lines and says "
                            f"lane-flags no: a run whose image can mark asks "
                            f"for the block, since a mark alone does not "
                            f"say which lane", at0)
        if m and source is None:
            raise self.fail("replay-source",
                            f"run {run_index} has replay lines and names no "
                            f"source: a replay is by the definition the "
                            f"source gives", at0)
        out = []
        for _ in range(m):
            toks = self.expect("replay", 10)
            at = self.pos - 1
            if (toks[2], toks[4], toks[6], toks[8]) != \
                    ("marked", "changed", "raw-end", "raw-lanes"):
                raise self.malformed("'replay <k> marked <n> changed <c> "
                                     "raw-end <hash> raw-lanes <hash>'", at)
            k = self.dec(toks[1], "a replay's segment", hi=S - 1, i=at)
            if out and k <= out[-1].segment:
                if k == out[-1].segment:
                    raise self.fail("line-unexpected",
                                    f"a replay line for segment {k} again",
                                    at)
                raise self.fail("line-order",
                                f"the replay line for segment {k} comes "
                                f"after segment {out[-1].segment}'s; "
                                f"segments are in increasing order", at)
            marked = self.dec(toks[3], "the lanes marked", lo=1, hi=lanes,
                              i=at)
            changed = self.dec(toks[5], "the lanes changed", hi=lanes, i=at)
            if changed > marked:
                raise self.malformed(f"changed {changed} is more than marked "
                                     f"{marked}: a replay changes only lanes "
                                     f"the machine marked", at)
            out.append(Replay(k, marked, changed,
                              self.hexn(toks[7], 64, "a raw end hash", at),
                              self.hexn(toks[9], 64, "a raw lane-flags hash",
                                        at)))
        return tuple(out)

    def replay_methods_hold(self, prov, runs):
        """The runs with replay lines are exactly the runs the header's
        replay-method lines name."""
        with_replays = {i for i, r in enumerate(runs) if r.replays}
        for m in prov.replay_methods:
            if m[0] not in with_replays:
                raise self.fail(
                    "replay-method",
                    f"the header names how run {m[0]}'s replays were made, "
                    f"and " + (f"run {m[0]} has no replay line" if
                               m[0] < len(runs) else
                               f"there is no run {m[0]}"),
                    self._method_at[m[0]])
        named = {m[0] for m in prov.replay_methods}
        for i in sorted(with_replays - named):
            raise self.fail("replay-method",
                            f"run {i} has replay lines and the header names "
                            f"no replay-method for it", self._replays_at[i])

    def entry(self, j):
        self.member_index("entry", j, stop=("end",), consecutive=False)
        toks = self.expect("entry", 3)
        self.block = BLOCK_OF["entry"]
        method = self.word(toks[2], tuple(METHOD_KIND), "the method")
        kind = self.word(self.expect("kind", 2)[1], V1.KINDS, "the kind")
        if kind != METHOD_KIND[method]:
            raise self.fail(
                "accuracy-kind",
                f"entry {j}: the kind of {method} is "
                f"{METHOD_KIND[method]}, not {kind}"
                + ("; a bound needs a rigorous remainder, and no version-2 "
                   "method has one" if kind == "bound" else ""),
                self.pos - 1)
        uses = self.dec(self.expect("uses", 2)[1], "the run used",
                        i=self.pos - 1)
        toks = self.expect("scope")
        if toks == ["scope", "max-lanes"]:
            lane = None
        elif len(toks) == 3 and toks[1] == "lane":
            lane = self.dec(toks[2], "the lane", i=self.pos - 1)
        else:
            raise self.malformed("'scope lane <i>' or 'scope max-lanes'",
                                 self.pos - 1)
        label, terms = None, ()
        if method == "drift":
            i = self.pos
            toks = self.expect("quantity")
            if len(toks) != 4 or toks[2] != "terms":
                raise self.malformed("'quantity <label> terms <n>'", i)
            if not _NAME.fullmatch(toks[1]):
                raise self.malformed(f"label {toks[1][:80]!r} is not "
                                     f"[a-z][a-z0-9-]*, at most 64", i)
            label = toks[1]
            t = self.dec(toks[3], "the term count", lo=1, hi=V1.MAX_TERMS,
                         i=i)
            have = 0
            for q in range(self.pos, len(self.lines)):
                if self.lines[q][0] != "term":
                    break
                have += 1
            if have != t:
                raise self.fail("count", f"'terms {t}' and {have} 'term' "
                                         f"line{'s' if have != 1 else ''} "
                                         f"follow", i)
            out = []
            for _ in range(t):
                toks = self.expect("term")
                at = self.pos - 1
                if len(toks) < 2:
                    raise self.malformed("'term <coefficient> [s<slot> ...]'",
                                         at)
                c = self.rational(toks[1], "a coefficient", at)
                slots = []
                for f in toks[2:]:
                    m = V1._SLOT.fullmatch(f)
                    if not m:
                        raise self.malformed(f"factor {f[:40]!r} is not "
                                             f"s<slot>", at)
                    slots.append(self.dec(m.group(1), "a slot", hi=0xFFFF,
                                          i=at))
                if len(slots) > V1.MAX_FACTORS:
                    raise self.malformed(f"a term has at most "
                                         f"{V1.MAX_FACTORS} factors", at)
                if slots != sorted(slots):
                    raise self.malformed("a term's factors are in "
                                         "non-decreasing slot order", at)
                out.append((c, tuple(slots)))
            terms = tuple(out)
        value = self.value()
        return Entry(method, kind, uses, lane, value, label, terms)


def read_body(lines):
    """A version-2 body, split into lines of tokens (cert.parse's
    _split_lines), -> a Certificate, or the first Refusal."""
    return _Reader(lines).certificate()


def parse(data, salt=None):
    """cert.parse, for a caller that holds version 2: the dispatching
    reader, which refuses a version-1 body here only by its own rules."""
    return V1.parse(data, salt)


# ---- the source and its definition ---------------------------------------------

def source_graph(source_bytes, fmt=None, name="<source>"):
    """The source's step graph, checked by the language: at its own format,
    or at `fmt` - the format override (docs/LANGUAGE.md, "Statements"; cftc's
    `--format`), the source with its format statement's value replaced. A
    language Refusal names the source."""
    from . import lang
    return lang.compile_text(bytes(source_bytes), name, fmt=fmt).graph


def own_format(source_bytes):
    """The format the source declares, whatever it is checked at: the
    graph's source_format, which is never in its bytes."""
    return source_graph(source_bytes).source_format


def canonical_literal(value):
    """The language's canonical spelling of a constant (LANGUAGE.md, "The
    intention-out"): an int, a Fraction, or text the language reads as a
    constant."""
    from .lang import constants as C
    from .lang.check import constant_of
    if isinstance(value, str):
        value = constant_of(value)
    return C.literal(Fraction(value))


class Definition:
    """What a run's source defines it to compute: the step graph at the
    run's format, the run values of its params (literal text, read by the
    language as a default is), and h - the source's own, or h/2 for a
    half-step run. A lane of the image's scratch block is the graph's
    lane: its state, then each tangent vector's components, then its lane
    params (cftc's layout, and the interpreter's)."""

    def __init__(self, graph, params=(), half=False):
        self.graph = graph
        self.params = dict(params)
        self.h = None
        if half:
            h0 = graph.integrator[1]
            if h0 is None:
                from .lang.refusals import Refusal as LangRefusal
                raise LangRefusal("unknown-param",
                                  f"{graph.system} declares no h, so a "
                                  f"half-step run has none to halve")
            self.h = Fraction(h0) / 2
        self.n = graph.n_state
        self.T = len(graph.tangent)
        self.m = len(graph.lane)
        self.width = self.n * (1 + self.T) + self.m

    def needs_mpmath(self):
        """Does evaluating the graph reach a golden function decided
        through mpmath's enclosures? Only a node in TRANSCEND_OPS does, and
        the language has none today: it refuses `exp` (`transcendental`),
        and its division and root are softfloat's (L4). M1's routines will
        be the first."""
        for name in ("step", "tangent_step"):
            sec = self.graph.section(name)
            if sec is not None and any(op in TRANSCEND_OPS
                                       for op, _a, _l in sec.nodes):
                return True
        return False

    def lane(self, values, steps):
        """One lane's values after `steps` steps of the definition, and the
        five IEEE flags it raised: lang.run on that lane alone, which is
        the lane as it is in the lockstep run (LANGUAGE.md)."""
        from .lang import run as lang_run
        n, T = self.n, self.T
        state = list(values[:n])
        tans = [list(values[n * (1 + t):n * (2 + t)]) for t in range(T)]
        lp = list(values[n * (1 + T):])
        r = lang_run(self.graph, [state], steps, lane_params=[lp],
                     params=self.params or None, h=self.h,
                     tangents=[tans] if T else None)
        out = list(r.states[0])
        if T:
            for t in r.tangents[0]:
                out += list(t)
        return out + lp, r.flags & LANE_IEEE


# The language's node operations whose golden function is decided through
# mpmath (transcend.py): none yet. M1's exp and log will join it.
TRANSCEND_OPS = frozenset()


def _mpmath_version():
    try:
        import mpmath
    except ImportError:
        return None
    return mpmath.__version__


def runtime_text(evaluated):
    """`writer-runtime` for the golden writer: its Python, and mpmath's
    version wherever it evaluated the definition (a replay)."""
    text = f"python-{platform.python_version()}"
    if evaluated:
        text += f",mpmath-{_mpmath_version() or 'none'}"
    return text


class _Undecided(Exception):
    """The definition could not be evaluated here: mpmath is missing for a
    node that needs it, or an enclosure reached its precision cap."""


def _evaluate(definition, values, steps):
    from .transcend import ZivEscalation
    if definition.needs_mpmath() and _mpmath_version() is None:
        raise _Undecided("the definition reaches a transcendental golden "
                         "function, decided through mpmath's enclosures, "
                         "and mpmath is not installed")
    try:
        return definition.lane(values, steps)
    except ZivEscalation as e:
        raise _Undecided(f"a golden function's enclosure reached its "
                         f"precision cap: {e}") from None


def replay_segment(definition, start, raw_end, raw_block, nslots, steps):
    """Replay every lane the raw block marks, from the segment's start
    state, by the definition. -> (the corrected end, the corrected block,
    the marked lanes, how many of them the replay changed). A marked
    lane's end values are the definition's, and its byte the definition's
    five flags with the raw [6:5] and [7] clear."""
    end = list(raw_end)
    block = bytearray(raw_block)
    marked = [i for i, b in enumerate(raw_block) if b & LANE_MARK]
    changed = 0
    for i in marked:
        lo, hi = i * nslots, (i + 1) * nslots
        vals, fl = _evaluate(definition, start[lo:hi], steps)
        if vals != end[lo:hi]:
            changed += 1
        end[lo:hi] = vals
        block[i] = fl | (raw_block[i] & LANE_STATUS)
    return end, bytes(block), marked, changed


def _flags_of(block):
    out = 0
    for b in block:
        out |= b & LANE_IEEE
    return out


# ---- the golden writer -----------------------------------------------------------

@dataclass
class Chain:
    """A run as the golden writer made it: S + 1 boundary states (each the
    definition's, a marked lane replayed), each segment's flag word and
    STATUS, its block (None in a `no` run), and for each segment with a
    replay its raw end state, raw block, marked count and changed count."""
    states: list
    results: list
    blocks: list
    raws: dict
    lane_flags: bool
    fmt: str = None
    nslots: int = 0


def needs_flag_control(image, scratch_depth=seq.SCRATCH_D):
    prog = seq.Program.from_bytes(bytes(image), scratch_depth=scratch_depth)
    return bool(seq.features_rev8(prog.insns) & seq.FEAT_FLAG_CONTROL)


def run_chain(image, bank, initial, segments, *, streams=None,
              scratch_depth=seq.SCRATCH_D, lane_flags=None, definition=None,
              steps=None):
    """Run `image` as `segments` segments from `initial`, by seq.run, each
    with its block of per-lane flags (R23). A run asks for the block when
    `lane_flags` says so, and by default whenever its image needs flag
    control (CAPS2[14]), since a mark alone does not say which lane. A
    segment that marks a lane is replayed lane by lane by `definition` (a
    Definition, at the run's format and h) over `steps` steps, and the
    chain carries the corrected segment: refused `replay-lane-flags` in a
    run that does not ask for the block, `replay-source` with no
    definition, and `replay-undecided` where the definition cannot be
    evaluated here."""
    if definition is not None and (not V1._is_int(steps) or steps < 1):
        raise TypeError("a replay runs the run's steps a segment: hand "
                        "run_chain `steps` with a definition")
    prog = seq.Program.from_bytes(bytes(image), scratch_depth=scratch_depth)
    why = V1._segment_shape(prog)
    if why:
        raise Refusal("program-shape", f"this program is not a segment: "
                                       f"{why}")
    bankv = V1._bank_values(prog, bank)
    nslots = prog.n_scratch_in
    if len(initial) % nslots:
        raise Refusal("state-shape", f"{len(initial)} values is not a whole "
                                     f"number of lanes of {nslots} slots")
    n = len(initial) // nslots
    a, b, c = V1._streams_or_zero(prog.fmt, n, streams)
    fc = bool(seq.features_rev8(prog.insns) & seq.FEAT_FLAG_CONTROL)
    lf = fc if lane_flags is None else bool(lane_flags)
    if definition is not None and definition.width != nslots:
        raise Refusal("source-shape",
                      f"the image's lane is {nslots} slots and its source's "
                      f"is {definition.width}: {definition.n} state, "
                      f"{definition.T * definition.n} tangent, "
                      f"{definition.m} lane params")
    states, results, blocks, raws = [list(initial)], [], [], {}
    for k in range(segments):
        res = seq.run(prog, a, b, c, bank=bankv, scratch_in=states[-1],
                      scratch_depth=scratch_depth)
        out = list(res.scratch_out)
        block = bytes(res.lane_flags)
        fl, st = res.flags, res.status
        if any(x & LANE_MARK for x in block):
            if not lf:
                raise Refusal("replay-lane-flags",
                              f"segment {k} marks a lane, and the run does "
                              f"not ask for the per-lane block that says "
                              f"which")
            if definition is None:
                raise Refusal("replay-source",
                              f"segment {k} marks a lane, and the run names "
                              f"no source whose definition could replay it")
            try:
                end, nb, marked, changed = replay_segment(
                    definition, states[-1], out, block, nslots, steps)
            except _Undecided as e:
                raise Refusal("replay-undecided",
                              f"segment {k}: a marked lane cannot be "
                              f"replayed here: {e}") from None
            raws[k] = (out, block, len(marked), changed)
            out, block = end, nb
            fl, st = _flags_of(block), st & ~STATUS_MARK
        states.append(out)
        results.append((fl, st))
        blocks.append(block if lf else None)
    return Chain(states, results, blocks, raws, lf, prog.fmt.name, nslots)


def certify_run(kind, image, bank, salt, chain, *, steps, streams=None,
                parameters=(), h_slots=(), scratch_depth=seq.SCRATCH_D,
                source=None):
    """A Run from a Chain (run_chain's): the hashes of every boundary and
    block, each replay's raw end and raw block, the image and program
    digests, the streams' hashes - keyed under `salt`, or open when it is
    None - and `source`, a Source or None."""
    base = V1.certify_run(kind, image, bank, salt, chain.states,
                          chain.results, steps=steps, streams=streams,
                          parameters=parameters, h_slots=h_slots,
                          scratch_depth=scratch_depth)
    segs = []
    for k, s in enumerate(base.chain):
        lanes = (lane_flags_hash(salt, chain.blocks[k]) if chain.lane_flags
                 else None)
        segs.append(Segment(s.start, s.end, s.flags, s.status, lanes))
    fmt = base.fmt
    reps = tuple(Replay(k, marked, changed,
                        state_hash(salt, state_bytes(fmt, raw_end)),
                        lane_flags_hash(salt, raw_block))
                 for k, (raw_end, raw_block, marked, changed)
                 in sorted(chain.raws.items()))
    return Run(kind, fmt, base.image, base.digest, source, base.lanes,
               base.steps, base.streams, base.parameters, chain.lane_flags,
               tuple(segs), reps, base.output, base.h_slots)


def source_lines(source_bytes, fmt, *, name="none", params=None,
                 compiler=None):
    """The Source a run names: the file's SHA-256, its name, the SHA-256
    of its step graph at `fmt` (the run's format), the compiler that made
    the image or None, and the run values of its params in the language's
    canonical spelling, names in increasing byte order."""
    graph = source_graph(source_bytes, fmt)
    lits = tuple(sorted((n, canonical_literal(v))
                        for n, v in (params or {}).items()))
    return Source(sha256(source_bytes), name, sha256(graph.to_bytes()),
                  None if compiler is None else tuple(compiler), lits)


def compile_source(source_bytes, fmt, steps, target, params=()):
    """cftc's compile of the source at `fmt`, the run's format (the format
    override above), with the run's steps, target and source params. One
    image serves every target that accepts it, so the target decides only
    acceptance (python/cftc)."""
    import cftc
    graph = source_graph(source_bytes, fmt)
    return cftc.compile_graph(graph, steps, target, stem="system",
                              params=dict(params) or None)


def side_files(run_index, chain):
    """The files a writer puts beside the boundary states: each segment's
    block, `run-<r>-segment-<k>.flags`, and each replayed segment's raw end
    and raw block, `run-<r>-segment-<k>-raw.bin` and `-raw.flags`."""
    out = {}
    if chain.lane_flags:
        for k, blk in enumerate(chain.blocks):
            out[f"run-{run_index}-segment-{k}.flags"] = bytes(blk)
    for k, (raw_end, raw_block, _m, _c) in sorted(chain.raws.items()):
        out[f"run-{run_index}-segment-{k}-raw.bin"] = state_bytes(
            chain.fmt, raw_end)
        out[f"run-{run_index}-segment-{k}-raw.flags"] = bytes(raw_block)
    return out


# ---- what a writer measures ----------------------------------------------------

def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def host_os(with_version=False):
    """The OS's name, `linux` or `windows` (or another system's own name,
    lower case); with its version only on request - for Linux the
    kernel's."""
    name = platform.system().lower() or "unknown"
    if with_version and name != "unknown":
        rel = platform.release() if name == "linux" else platform.version()
        if rel:
            name = f"{name}-{rel}"
    return name


def host_arch():
    m = platform.machine().lower()
    return {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "aarch64",
            "aarch64": "aarch64"}.get(m, m or "unknown")


def environment(environ=None):
    """The writer's list's variables that are set, by name: a variable set
    to the empty string counts as unset (libcft's rule, since cmd and
    PowerShell remove a variable set empty)."""
    environ = os.environ if environ is None else environ
    return tuple((n, environ[n]) for n in ENVIRONMENT_NAMES
                 if environ.get(n))


# ---- the detached signature ---------------------------------------------------

SIG_LINES = ("cft-signature 1", "scheme ed25519")


def body_hash_of(data):
    """A certificate's name: the SHA-256 of its body, which its hash line
    carries - held to the body first (`hash-line`, `body-hash`)."""
    body, digest = V1._split_hash(data)
    if sha256(body) != digest:
        raise Refusal("body-hash", "the hash line is not the SHA-256 of the "
                                   "body: the bytes are not the ones it was "
                                   "written over")
    return digest


def signature_file(secret, data):
    """The detached signature of a certificate of either version, as the
    five lines of `<certificate>.sig`: Ed25519 (RFC 8032) by the 32-byte
    `secret` over `cft-signature 1`, a NUL and the 32 bytes of the body
    hash."""
    digest = body_hash_of(data)
    key = ed25519.public_key(secret)
    sig = ed25519.sign(secret, signature_message(digest))
    return (f"{SIG_LINES[0]}\n{SIG_LINES[1]}\nkey {key.hex()}\n"
            f"certificate {digest}\nsignature {sig.hex()}\n").encode("ascii")


def read_signature_file(sig):
    """(key, certificate, signature), each hex, from a signature file's
    bytes, read strictly: exactly its five lines, printable ASCII and LF,
    or `signature-format`."""
    if not isinstance(sig, (bytes, bytearray)):
        raise Refusal("signature-format", "a signature file is bytes")
    sig = bytes(sig)
    if not sig.endswith(b"\n") or any(not (0x20 <= b <= 0x7E or b == 0x0A)
                                      for b in sig):
        raise Refusal("signature-format", "a signature file is printable "
                                          "ASCII lines, each ending in LF")
    lines = sig[:-1].decode("ascii").split("\n")
    pat = (SIG_LINES[0], SIG_LINES[1], r"key [0-9a-f]{64}",
           r"certificate [0-9a-f]{64}", r"signature [0-9a-f]{128}")
    if len(lines) != 5 or not all(re.fullmatch(p, ln)
                                  for p, ln in zip(pat, lines)):
        raise Refusal("signature-format",
                      "a signature file is five lines: 'cft-signature 1', "
                      "'scheme ed25519', 'key <64 hex>', 'certificate <64 "
                      "hex>' and 'signature <128 hex>', lowercase, each "
                      "ending in LF")
    return (lines[2].split(" ")[1], lines[3].split(" ")[1],
            lines[4].split(" ")[1])


def check_signature_file(data, sig):
    """Does `sig` sign the certificate `data`? -> the signing key's hex,
    or `signature-format` (the file's form) or `signature` (another
    certificate's, or a signature that does not verify)."""
    key, digest, s = read_signature_file(sig)
    mine = body_hash_of(data)
    if digest != mine:
        raise Refusal("signature", f"the signature names the certificate "
                                   f"{digest[:16]}..., and this one is "
                                   f"{mine[:16]}...")
    if not ed25519.verify(bytes.fromhex(key), signature_message(digest),
                          bytes.fromhex(s)):
        raise Refusal("signature", f"the signature does not verify under "
                                   f"key {key}")
    return key


def read_keyring(data):
    """A keyring: lines `key <64 hex> <text>`, each key once -> {key:
    holder}. A keyring that breaks its form is refused `signer`, step 2a's
    name for it."""
    if not isinstance(data, (bytes, bytearray)):
        raise Refusal("signer", "a keyring is bytes")
    data = bytes(data)
    if not data:
        return {}
    if not data.endswith(b"\n") or any(not (0x20 <= b <= 0x7E or b == 0x0A)
                                       for b in data):
        raise Refusal("signer", "a keyring is printable ASCII lines, each "
                                "ending in LF")
    out = {}
    for n, line in enumerate(data[:-1].decode("ascii").split("\n"), 1):
        toks = line.split(" ")
        if len(toks) != 3 or toks[0] != "key" or \
                not _HEX[64].fullmatch(toks[1]):
            raise Refusal("signer", f"keyring line {n}: 'key <64 lowercase "
                                    f"hex> <text>'")
        holder = read_text(toks[2])
        if holder is None:
            raise Refusal("signer", f"keyring line {n}: the holder is not a "
                                    f"text in its one spelling")
        if toks[1] in out:
            raise Refusal("signer", f"keyring line {n}: key {toks[1][:16]}... "
                                    f"again")
        out[toks[1]] = holder
    return out


# ---- the initial-state generators ------------------------------------------------

def _shake_box(fmt, lanes, nslots, args):
    """`shake-box <tag> <lo> <hi> ...`: lane k's slot j a value in [lo_j,
    hi_j] at twice the format's precision, drawn from SHAKE-256 of `<tag>
    lane <k> state <j>`, rounded once to nearest - A1's rule for its
    reference lanes (programs/acceptance.py, full_value), without its
    special lanes. Each bound is a constant in the language's canonical
    spelling, and there is one pair for each slot of a lane."""
    if len(args) != 1 + 2 * nslots:
        raise ValueError(f"shake-box takes a tag and a (lo, hi) pair for "
                         f"each of a lane's {nslots} slots: {1 + 2 * nslots} "
                         f"arguments, not {len(args)}")
    tag, bounds = args[0], args[1:]
    box = []
    for t in bounds:
        if canonical_literal(t) != t:
            raise ValueError(f"the bound {t!r} is not a constant in the "
                             f"language's canonical spelling")
        from .lang.check import constant_of
        box.append(Fraction(constant_of(t)))
    f = FORMATS[fmt]
    out = []
    for k in range(lanes):
        for j in range(nslots):
            lo, hi = box[2 * j], box[2 * j + 1]
            if lo > hi:
                raise ValueError(f"slot {j}'s box has lo above hi")
            nbits = 2 * f.prec
            nbytes = (nbits + 7) // 8
            num = int.from_bytes(hashlib.shake_256(
                f"{tag} lane {k} state {j}".encode("utf-8")).digest(nbytes),
                "big") >> (8 * nbytes - nbits)
            v = lo + (hi - lo) * Fraction(num, 1 << nbits)
            out.append(V1.round_rational(fmt, v, "rne"))
    return out


GENERATORS = {"shake-box": _shake_box}


def generate_initial(initial, fmt, lanes, nslots):
    """The initial state a named generator makes, lane-major, or a
    ValueError naming why it cannot."""
    _g, name, args = initial
    fn = GENERATORS[name]
    return fn(fmt, lanes, nslots, args)


# ---- the audit -------------------------------------------------------------------

@dataclass
class Verdict:
    """What a version-2 audit found. lines() is the verdict, which two
    auditors must agree on line for line; header() is the auditor's own
    identity and the audit's time, which the comparison leaves out."""
    name: str
    mode: str
    lines_: list
    auditor: list
    exit_code: int = 0

    def lines(self):
        return list(self.lines_)

    def header(self):
        return list(self.auditor)


def _words_report(key, value):
    if value == "unknown":
        return f"{key}: unknown - the producer did not record it"
    if value == "none":
        return f"{key}: none - it does not exist for this producer"
    if value == "withheld":
        return f"{key}: withheld - the producer has it and chose not to " \
               f"publish it"
    return f"{key}: {value} - stated, not checked"


def provenance_report(p):
    """Each header statement: stated and not checked, unknown, none or
    withheld. Texts are shown in their spelling, so the verdict stays one
    ASCII byte string."""
    def t(v):
        return v if v in WORDS else text_token(v)
    rows = [("device-platform", t(p.device_platform)),
            ("device-xrt", t(p.device_xrt)),
            ("device-clock", str(p.device_clock)),
            ("device-serial", t(p.device_serial)),
            ("writer", p.writer if p.writer == "unknown" else
             f"{p.writer[0]} {p.writer[1]}"),
            ("writer-runtime", t(p.writer_runtime)),
            ("compiler-build", p.compiler_build),
            ("certificate-id", t(p.certificate_id)),
            ("issuer", t(p.issuer)),
            ("issuer-key", p.issuer_key),
            ("host-os", t(p.host_os)), ("host-arch", t(p.host_arch)),
            ("started", p.started), ("finished", p.finished),
            ("issued", p.issued)]
    out = [_words_report(k, v) for k, v in rows]
    for r, *how in p.replay_methods:
        out.append(f"replay-method {r}: "
                   + ("golden" if how == ["golden"] else
                      f"image {how[1]}")
                   + " - stated, not checked: every replay is checked "
                     "against the definition")
    out.append("environment: " + (", ".join(
        f"{n}={text_token(v)}" for n, v in p.environment)
        if p.environment else "none set") + " - stated, not checked")
    return out


class _Cover:
    """The auditor's definition against the certificate's, and the rule
    for a re-derivation that fails: its own name where the auditor's
    covers the certificate's, else `definition-differs`, naming both."""

    def __init__(self, cert):
        p = cert.provenance
        self.profile = version_text(PROFILE)
        self.language = version_text(_language_version())
        self.covered = covers(PROFILE, p.profile) and \
            covers(_language_version(), p.language)
        self.cert_profile, self.cert_language = p.profile, p.language

    def describe(self):
        return (f"definition: the certificate's profile {self.cert_profile} "
                f"and language {self.cert_language}; the auditor's profile "
                f"{self.profile} and language {self.language}, which "
                + ("cover them" if self.covered else
                   "do not cover them, and every re-derivation passed under "
                   "the auditor's"))

    def judge(self, r):
        if self.covered:
            return r
        return Refusal("definition-differs",
                       f"{r.name} under the auditor's definition (profile "
                       f"{self.profile}, language {self.language}), which "
                       f"does not cover the certificate's (profile "
                       f"{self.cert_profile}, language {self.cert_language})"
                       f": the auditor's own limit, not a verdict on the "
                       f"certificate - hand the audit the named definition "
                       f"to decide ({r.message})",
                       line=r.line, run=r.run, segment=r.segment,
                       entry=r.entry)


class _Through:
    """with _Through(cover): a re-derivation through the definition."""

    def __init__(self, cover):
        self.cover = cover

    def __enter__(self):
        return self

    def __exit__(self, et, e, tb):
        if et is not None and issubclass(et, Refusal) and \
                e.name not in ("definition-unavailable", "source-missing",
                               "state-missing", "definition-differs"):
            raise self.cover.judge(e) from None
        return False


def audit(data, salt, programs, states=None, streams=None, choose=None,
          seed=None, *, sources=None, lane_flags=None, signature=None,
          keyring=None, superseded=None, define=None, regenerate=False):
    """Audit a version-2 certificate. Returns a Verdict, or raises the
    first Refusal in the specification's order:

      1  integrity    the hash line, the body's hash
      2  form         the strict reader, its form rules among it
         choice       the auditor's own choices: segments to re-run, and
                      segments to run by the definition (`define`)
      2a signature    when one is handed: its form, that it signs this
                      certificate, its key, a keyring's holder
      3  salt
      3a supersedes   when the superseded certificate is handed
      4  programs     version 1's; the loader's verdicts through the
                      definition
      4a sources      each run's source handed: digest, the language,
                      format, graph, params, lane shape, the recompile
      5  streams, 6 continuity, 7 states (and blocks handed, and the
         initial state regenerated), 8 relations (wider-source, the
         source lines), 9 re-runs (the block, the replays), 9a the
         definition re-run, 10 accuracy

    Version 2's inputs, beside version 1's:
      sources     {run: the source's bytes}
      lane_flags  {run: {segment: the block's bytes}}
      signature   the `.sig` file's bytes
      keyring     a keyring's bytes
      superseded  the certificate this one names in `supersedes`
      define      {run: "all" | [segment, ...]}: segments the auditor
                  chooses to run by the source's interpreter too
      regenerate  True: regenerate run 0's initial state by its named
                  generator, where the auditor knows it - the auditor's
                  choice, since it costs the certificate's lanes - and hold
                  it to the certified one (`initial-state`); then it need
                  not be handed
    """
    cert = V1.parse(data)                                         # 1, 2
    if not isinstance(cert, Certificate):
        raise TypeError("cert2.audit audits version 2; cert.audit "
                        "dispatches by the magic line")
    plan = V1._plan(cert, choose, seed)                          # choice
    dplan = _define_plan(cert, define)
    if not isinstance(regenerate, bool):
        raise Refusal("choice", f"regenerate is True or False, not "
                                f"{regenerate!r}")
    sig_line = _check_signature(cert, data, signature, keyring)  # 2a
    V1.check_salt(cert, salt)                                    # 3
    sup_line = _check_superseded(cert, superseded)               # 3a
    cover = _Cover(cert)
    progs = _check_programs(cert, programs, cover)               # 4
    srcs = _check_sources(cert, sources, progs, cover)           # 4a
    regen, why, initial_line = _regenerate(cert, progs, regenerate)
    handed = states
    states = _with_initial(states, regen)
    strm = V1._check_streams(cert, salt, progs, streams, states)  # 5
    V1._check_continuity(cert)                                   # 6
    if why is not None:                                          # 7
        raise Refusal("initial-state", why, run=0, segment=0)
    if regen is not None and state_hash(
            salt, state_bytes(progs[0]["prog"].fmt, regen)) \
            != cert.runs[0].chain[0].start:
        raise Refusal("initial-state", f"generator "
                                       f"{cert.provenance.initial[1]} does "
                                       f"not regenerate run 0's initial "
                                       f"state", run=0, segment=0)
    known = V1._check_states(cert, salt, progs, states)
    blocks_seen = _check_blocks(cert, salt, lane_flags)
    _check_relations(cert, salt, progs, strm, known, srcs, cover)  # 8
    notes = _rerun(cert, salt, progs, strm, known, plan, srcs, cover)  # 9
    dnotes = _define_rerun(cert, salt, progs, strm, known, dplan, srcs,
                           cover)                                 # 9a
    shapes = [(p["prog"].fmt, p["nslots"]) for p in progs]
    values = []
    for j, e in enumerate(cert.accuracy):                         # 10
        try:
            q = V1.derive(e, cert.runs, shapes, known, method_run=METHOD_RUN)
        except Refusal as r:
            raise Refusal(r.name, f"entry {j}: {r.message}", run=r.run,
                          segment=r.segment, entry=j)
        if not V1.value_holds(e.value, q):
            raise Refusal("accuracy-value",
                          f"entry {j}: the value recorded is not the "
                          f"{e.method} of the certified runs, which is "
                          f"{V1.rational_text(q)}", entry=j)
        values.append(q)
    name = V1._split_hash(data)[1]
    return _verdict(cert, name, plan, dplan, values, sig_line, sup_line,
                    cover, srcs, notes, dnotes, blocks_seen, initial_line,
                    handed)


def _define_plan(cert, define):
    """The auditor's choice of segments to run by the definition, held to
    the certificate like its choice of re-runs (`choice`)."""
    define = V1._run_mapping(cert, define, "the definition re-run", "choice")
    out = {}
    for r, c in define.items():
        S = len(cert.runs[r].chain)
        if c == "all":
            out[r] = list(range(S))
        elif isinstance(c, (list, tuple)):
            segs = list(c)
            if not segs or any(not V1._is_int(k) or not 0 <= k < S
                               for k in segs) or len(set(segs)) != len(segs):
                raise Refusal("choice", f"run {r}: segments {segs!r} to run "
                                        f"by the definition are not distinct "
                                        f"indices in 0..{S - 1}, at least "
                                        f"one", run=r)
            out[r] = sorted(segs)
        else:
            raise Refusal("choice", f"run {r}: the definition re-run takes "
                                    f"'all' or a list of segments, not "
                                    f"{c!r}", run=r)
    return out


def _check_signature(cert, data, signature, keyring):
    """Step 2a: the signature file's form, that it signs this certificate
    and verifies, its key against `issuer-key`, and a keyring's holder
    against `issuer`."""
    p = cert.provenance
    if signature is None:
        if keyring is not None:
            read_keyring(keyring)
        return "signature: none handed"
    key = check_signature_file(data, signature)
    if p.issuer_key != "none" and key != p.issuer_key:
        raise Refusal("signature-key",
                      f"the signature is by key {key}, and the certificate "
                      f"names {p.issuer_key} as the key it is to be signed "
                      f"with")
    if keyring is None:
        return f"signature: by key {key}, verified, which no keyring handed " \
               f"names"
    ring = read_keyring(keyring)
    holder = ring.get(key)
    if holder is None:
        return f"signature: by key {key}, verified, which the keyring " \
               f"handed does not name"
    if p.issuer not in WORDS and holder != p.issuer:
        raise Refusal("signer",
                      f"the keyring names key {key[:16]}... as "
                      f"{text_token(holder)}, and the certificate's issuer "
                      f"is {text_token(p.issuer)}")
    return f"signature: by key {key}, verified, held by " \
           f"{text_token(holder)} by the keyring handed"


def _check_superseded(cert, superseded):
    sup = cert.provenance.supersedes
    if superseded is None:
        return ("supersedes: none" if sup == "none" else
                f"supersedes {sup}: named, not handed - stated, not checked")
    if not isinstance(superseded, (bytes, bytearray)):
        raise Refusal("supersedes", "the superseded certificate is handed as "
                                    "its bytes")
    try:
        got = body_hash_of(superseded)
    except Refusal as r:
        raise Refusal("supersedes", f"the certificate handed as the one this "
                                    f"supersedes is not whole: {r.name}")
    if sup == "none" or got != sup:
        raise Refusal("supersedes",
                      f"the certificate handed as the one this supersedes is "
                      f"{got[:16]}..., and this one names "
                      + ("none" if sup == "none" else f"{sup[:16]}..."))
    return f"supersedes {sup}: the certificate handed is that one"


def _check_programs(cert, programs, cover):
    """Step 4, as version 1's, with the loader's verdicts - the image
    loads, its format, its shape - re-derived through the definition."""
    programs = V1._run_mapping(cert, programs, "programs", "program-image")
    out = []
    for r, run in enumerate(cert.runs):
        depth = V1.scratch_depth_of(cert.identity, run)
        if r not in programs:
            raise Refusal("program-image", f"run {r}: no program image was "
                                           f"handed to the audit", run=r)
        pair = programs[r]
        if not (isinstance(pair, (tuple, list)) and len(pair) == 2
                and V1._is_bytes(pair[0])
                and (pair[1] is None or V1._is_bytes(pair[1]))):
            raise Refusal("program-image",
                          f"run {r}: a program is handed as (image, bank), "
                          f"the image bytes and the bank bytes or None; this "
                          f"is a {type(pair).__name__}", run=r)
        image, bank = bytes(pair[0]), bytes(pair[1] or b"")
        if sha256(image) != run.image:
            raise Refusal("image-digest",
                          f"run {r}: the image handed is not the one "
                          f"certified (its SHA-256 differs)", run=r)
        if sha256(image + bank) != run.digest:
            raise Refusal("program-digest",
                          f"run {r}: the image and bank handed are not the "
                          f"ones certified (SHA-256 of image then bank "
                          f"differs)", run=r)
        with _Through(cover):
            try:
                prog = seq.Program.from_bytes(image, scratch_depth=depth)
            except seq.ProgramError as e:
                raise Refusal("program-image", f"run {r}: the image does "
                                               f"not load: {e}", run=r)
            if prog.fmt.name != run.fmt:
                raise Refusal("program-format",
                              f"run {r}: the image is {prog.fmt.name} and "
                              f"the certificate says {run.fmt}", run=r)
            why = V1._segment_shape(prog)
            if why:
                raise Refusal("program-shape",
                              f"run {r}: this program is not a segment: "
                              f"{why}", run=r)
        try:
            bankv = V1._bank_values(prog, bank)
        except Refusal as e:
            raise Refusal(e.name, f"run {r}: {e.message}", run=r)
        out.append({"prog": prog, "bank": bank, "bankv": bankv,
                    "nslots": prog.n_scratch_in, "depth": depth,
                    "image": image})
    return out


def _check_sources(cert, sources, progs, cover):
    """Step 4a: each run that names a source the audit was handed. ->
    {run: {"bytes", "graph", "definition", "compiled", "note"}} for the
    runs whose source was handed and checked."""
    from .lang.refusals import Refusal as LangRefusal
    sources = V1._run_mapping(cert, sources, "sources", "source-digest")
    out = {}
    for r in sorted(sources):
        run = cert.runs[r]
        b = sources[r]
        if not V1._is_bytes(b):
            raise Refusal("source-digest", f"run {r}: a source is handed as "
                                           f"its file's bytes, not a "
                                           f"{type(b).__name__}", run=r)
        if run.source is None:
            raise Refusal("source-digest", f"run {r}: a source was handed, "
                                           f"and the run names none", run=r)
    for r, run in enumerate(cert.runs):
        s = run.source
        if s is None or r not in sources:
            continue
        b = bytes(sources[r])
        if sha256(b) != s.digest:                                 # 1
            raise Refusal("source-digest",
                          f"run {r}: the source handed is not the one its run "
                          f"names (its SHA-256 differs)", run=r)
        with _Through(cover):
            try:                                                  # 2
                graph = source_graph(b, run.fmt)
            except LangRefusal as e:
                raise Refusal("source-refused",
                              f"run {r}: the language refuses the source at "
                              f"{run.fmt}: {e.name}: {e.sentence}",
                              run=r) from None
        if run.kind == "main":                                    # 3
            own = graph.source_format
            if own != run.fmt:
                raise Refusal("source-format",
                              f"run {r}: the main run is {run.fmt}, and its "
                              f"source's own format is {own}", run=r)
        with _Through(cover):
            if sha256(graph.to_bytes()) != s.graph:               # 4
                raise Refusal("source-graph",
                              f"run {r}: the source's step graph at "
                              f"{run.fmt} is not the one the run names",
                              run=r)
            _check_source_params(r, graph, s.params)              # 5
            n, T, m = graph.n_state, len(graph.tangent), len(graph.lane)
            if progs[r]["nslots"] != n * (1 + T) + m:             # shape
                raise Refusal("source-shape",
                              f"run {r}: the image's lane is "
                              f"{progs[r]['nslots']} slots, and its source's "
                              f"is {n * (1 + T) + m}: {n} state, {T * n} "
                              f"tangent, {m} lane params", run=r)
            compiled = None
            if s.compiler is not None:                            # 6
                compiled = _recompile(r, run, b, s, progs[r])
        try:
            definition = Definition(graph, s.params,
                                    half=run.kind == "half-step")
        except LangRefusal:
            definition = None       # no h to halve: a replay refuses below
        how = (f"recompiled by {s.compiler[0]} {s.compiler[1]} for "
               f"{text_token(s.compiler[2])}" if compiled is not None else
               "no compiler named")
        out[r] = {"bytes": b, "graph": graph, "definition": definition,
                  "compiled": compiled,
                  "note": f"run {r} source {s.digest}: checked - the "
                          f"language at {run.fmt}, {how}"}
    return out


def _check_source_params(r, graph, params):
    from .lang import constants as C
    from .lang import interp
    from .lang.refusals import Refusal as LangRefusal
    names = [p[0] for p in graph.param]
    for name, lit in params:
        if name not in names:
            raise Refusal("source-param", f"run {r}: source param {name} is "
                                          f"not a param of {graph.system}",
                          run=r)
        try:
            v = interp._exact_run_value(name, lit)
            interp._round_run(graph, name, v)
        except LangRefusal as e:
            raise Refusal("source-param", f"run {r}: source param {name}'s "
                                          f"value {lit[:40]!r}: {e.name}: "
                                          f"{e.sentence}", run=r) from None
        if C.literal(v) != lit:
            raise Refusal("source-param",
                          f"run {r}: source param {name}'s value {lit[:40]!r} "
                          f"is not the language's canonical spelling of its "
                          f"value, {C.literal(v)[:40]!r}", run=r)


def _recompile(r, run, source_bytes, s, prog):
    """Check 6 of step 4a: the auditor's cftc compiles the source with the
    run's steps, source params, format and target, and the image and bank
    must be the run's - for a half-step run the image, its bank being step
    8's. A difference is `source-image` where the auditor's compiler is the
    named name and output version, else `compiler-differs`."""
    import cftc
    from .lang.refusals import Refusal as LangRefusal
    name, ver, target = s.compiler
    same = (name, ver) == ("cftc", cftc.VERSION)
    mine = f"cftc {cftc.VERSION}"

    def differs(why):
        if same:
            return Refusal("source-image",
                           f"run {r}: {why}, so the image is not "
                           f"{name} {ver}'s compile of the source", run=r)
        return Refusal("compiler-differs",
                       f"run {r}: {why}; the certificate names {name} {ver} "
                       f"and the auditor's compiler is {mine}: the auditor's "
                       f"own limit - hand it the named compiler to decide",
                       run=r)
    try:
        c = compile_source(source_bytes, run.fmt, run.steps, target,
                           s.params)
    except LangRefusal as e:        # a ValueError too: caught first
        raise differs(f"the source does not compile for {target}: {e.name}: "
                      f"{e.sentence}") from None
    except cftc.InternalError as e:
        raise Refusal("compiler-differs",
                      f"run {r}: the auditor's compiler failed (a defect in "
                      f"it, exit 70): {e}", run=r) from None
    except ValueError as e:
        raise differs(f"the auditor's compiler has no target "
                      f"{target!r} ({e})") from None
    if sha256(c.image) != run.image:
        raise differs("the recompile's image is not the run's")
    # A half-step run's bank is its relation's to check - the main bank
    # halved in exactly its h-slots (`aux-bank`), which must be the slots
    # the recompile names (`aux-h-slots`) - so its image alone is held
    # here; every other run's image and bank are the recompile's.
    if run.kind != "half-step" and sha256(c.image + c.bank) != run.digest:
        raise differs("the recompile's bank is not the run's")
    return c


def _check_blocks(cert, salt, lane_flags):
    """Step 7's blocks: each block handed, its size the run's lanes
    (`lane-flags-shape`), its hash the segment's (`lane-flags-hash`), and
    R23's identities against the segment line (`lane-flags-identity`): the
    OR of its bytes' [4:0] is the flag word, of their [6:5] STATUS[5:4],
    and no byte carries [7], since a certified block's marks are
    resolved. -> {run: [segment, ...]} handed."""
    lane_flags = V1._run_mapping(cert, lane_flags, "lane_flags",
                                 "lane-flags-shape")
    seen = {}
    for r in sorted(lane_flags):
        run = cert.runs[r]
        per = lane_flags[r]
        if not isinstance(per, dict):
            raise Refusal("lane-flags-shape",
                          f"run {r}: its blocks are handed as a mapping from "
                          f"segment to bytes, not a {type(per).__name__}",
                          run=r)
        for k in sorted(per, key=lambda x: (not V1._is_int(x), str(x))):
            blk = per[k]
            if not V1._is_int(k) or not 0 <= k < len(run.chain):
                raise Refusal("lane-flags-shape",
                              f"run {r} has segments 0..{len(run.chain) - 1}; "
                              f"a block was handed for {k!r}", run=r)
            if not run.lane_flags:
                raise Refusal("lane-flags-shape",
                              f"run {r} segment {k}: a block was handed, and "
                              f"the run says lane-flags no", run=r, segment=k)
            if not V1._is_bytes(blk) or len(blk) != run.lanes:
                raise Refusal("lane-flags-shape",
                              f"run {r} segment {k}: a block is the run's "
                              f"{run.lanes} lanes, a byte each; this is "
                              + (f"{len(blk)} bytes" if V1._is_bytes(blk)
                                 else f"a {type(blk).__name__}"),
                              run=r, segment=k)
            seg = run.chain[k]
            if lane_flags_hash(salt, blk) != seg.lanes:
                raise Refusal("lane-flags-hash",
                              f"run {r} segment {k}: the block handed is not "
                              f"the one certified", run=r, segment=k)
            ieee = st = mark = 0
            for b in bytes(blk):
                ieee |= b & LANE_IEEE
                st |= (b & LANE_STATUS) >> 1
                mark |= b & LANE_MARK
            if ieee != seg.flags or st != (seg.status & 0x30) or mark:
                raise Refusal("lane-flags-identity",
                              f"run {r} segment {k}: the block's OR is flags "
                              f"{ieee} and STATUS[5:4] {st >> 4}"
                              + (", with a byte carrying [7]" if mark else "")
                              + f"; the segment line says flags {seg.flags} "
                                f"and STATUS[5:4] {(seg.status >> 4) & 3}",
                              run=r, segment=k)
            seen.setdefault(r, []).append(k)
    return seen


def _regenerate(cert, progs, regenerate):
    """The initial state a named generator makes, where the auditor knows
    the generator and chose to regenerate (`regenerate`): -> (values or
    None, why it could not, or None, the verdict's line). It costs the
    certificate's `lanes`, which is why it is the auditor's choice - an
    audit spends what it is handed, its own choices among them - and
    without it a generator is reported, not run."""
    init = cert.provenance.initial
    if init == ("given",):
        return None, None, "initial state: given"
    _g, name, args = init
    if name not in GENERATORS:
        return None, None, (f"initial state: generator {name}, which this "
                            f"auditor does not know - stated, not checked")
    if not regenerate:
        return None, None, (f"initial state: generator {name} - stated, not "
                            f"checked: the auditor did not choose to "
                            f"regenerate it")
    run = cert.runs[0]
    fmt = progs[0]["prog"].fmt.name
    try:
        vals = generate_initial(init, fmt, run.lanes, progs[0]["nslots"])
    except (ValueError, KeyError, ZeroDivisionError) as e:
        return None, (f"generator {name} cannot make run 0's initial state "
                      f"from these arguments: {e}"), None
    line = f"initial state: regenerated by {name}, run 0's boundary 0"
    if cert.mode == "keyed":
        line += (" - which a generator publishes, though the certificate "
                 "is keyed")
    return vals, None, line


def _with_initial(states, vals):
    """`states`, with the regenerated initial state as run 0's boundary 0
    where none was handed - and as it was where its shape is not version
    1's, so that step 7 refuses it by its own name."""
    if vals is None:
        return states
    if states is None:
        return {0: {0: vals}}
    if not isinstance(states, dict):
        return states
    per = states.get(0)
    if per is not None and not isinstance(per, dict):
        return states
    out = dict(states)
    out[0] = dict(per or {})
    out[0].setdefault(0, vals)
    return out


def _check_relations(cert, salt, progs, strm, known, srcs, cover):
    """Step 8: version 1's relations for half-step and wider runs, version
    2's for a wider-source run, and every auxiliary run's source lines
    against its relation's (`aux-source`), run by run in the table's
    order."""
    main, P0 = cert.runs[0], progs[0]
    for r in range(1, len(cert.runs)):
        A, PA = cert.runs[r], progs[r]
        where = f"run {r} ({A.kind})"
        if A.kind == "wider-source":
            with _Through(cover):
                _wider_source(cert, salt, r, A, PA, main, P0, strm, known,
                              srcs, where)
            continue
        half = A.kind == "half-step"
        if half and A.fmt != main.fmt:
            raise Refusal("aux-format", f"{where} is {A.fmt}; a half-step run "
                                        f"is at the main run's {main.fmt}",
                          run=r)
        if not half:
            _next_rung(where, r, A, main)
        if A.lanes != main.lanes:
            raise Refusal("aux-lanes", f"{where} has {A.lanes} lanes and the "
                                       f"main run {main.lanes}", run=r)
        if half and A.source != main.source:
            raise Refusal("aux-source", f"{where}: its source lines are not "
                                        f"the main run's - a half-step run "
                                        f"is the main run's source at h/2",
                          run=r)
        if not half and A.source is not None:
            raise Refusal("aux-source", f"{where} names a source: a wider "
                                        f"run's relation is to the main "
                                        f"image, not to a source "
                                        f"(wider-source is the source's)",
                          run=r)
        if A.steps != main.steps:
            raise Refusal("aux-image", f"{where} states {A.steps} steps a "
                                       f"segment and the main run "
                                       f"{main.steps}; the same instructions "
                                       f"take the same steps", run=r)
        if half:
            if A.image != main.image:
                raise Refusal("aux-image", f"{where}: its image digest is not "
                                           f"the main run's - a half-step run "
                                           f"is the same image", run=r)
        else:
            why = V1.routine_words(P0["prog"])
            if why:
                raise Refusal("aux-image", f"{where}: {why}", run=r)
            why = V1._wider_image(P0["prog"], PA["prog"])
            if why:
                raise Refusal("aux-image", f"{where} is not the main image "
                                           f"one format wider: {why}", run=r)
        if PA["depth"] != P0["depth"]:
            raise Refusal("aux-image", f"{where} is re-run at a scratch depth "
                                       f"of {PA['depth']} and the main run at "
                                       f"{P0['depth']}: the same instructions "
                                       f"on another machine", run=r)
        want = 2 * len(main.chain) if half else len(main.chain)
        if len(A.chain) != want:
            raise Refusal("aux-segments",
                          f"{where} has {len(A.chain)} segments; "
                          + (f"a half-step run has twice the main run's "
                             f"{len(main.chain)}" if half else
                             f"a wider run has the main run's "
                             f"{len(main.chain)}"), run=r)
        b0, bA = P0["bankv"], PA["bankv"]
        fmt0 = P0["prog"].fmt
        if half:
            if b0 is None:
                raise Refusal("aux-h-slots", f"{where}: the main image "
                                             f"carries its constants, so no "
                                             f"bank slot can be halved",
                              run=r)
            for s in A.h_slots:
                if s >= len(b0):
                    raise Refusal("aux-h-slots", f"{where}: h-slot {s} is "
                                                 f"past the {len(b0)}-slot "
                                                 f"bank", run=r)
                kind, v = V1.element_fraction(fmt0, b0[s])
                if kind != "finite" or v == 0:
                    raise Refusal("aux-h-slots",
                                  f"{where}: h-slot {s} holds "
                                  f"{'zero' if kind == 'finite' else kind} "
                                  f"in the main bank, which halving leaves "
                                  f"unchanged or undefined", run=r)
            c0 = srcs.get(0, {}).get("compiled")
            if c0 is not None:
                want_h = tuple(c0.manifest["h_slots"])
                if tuple(A.h_slots) != want_h:
                    raise Refusal("aux-h-slots",
                                  f"{where}: its h-slots are "
                                  f"{list(A.h_slots)}, and the main run's "
                                  f"compile names {list(want_h)} as the "
                                  f"slots that carry the step", run=r)
            for s in range(len(b0)):
                if s in A.h_slots:
                    if V1.element_fraction(fmt0, bA[s])[1] != \
                            V1.element_fraction(fmt0, b0[s])[1] / 2:
                        raise Refusal("aux-bank",
                                      f"{where}: bank slot {s} is not the "
                                      f"main bank's exactly halved", run=r)
                elif bA[s] != b0[s]:
                    raise Refusal("aux-bank",
                                  f"{where}: bank slot {s} differs from the "
                                  f"main bank's, and it is not a named "
                                  f"h-slot", run=r)
        else:
            if b0 is not None and any(V1.widen(main.fmt, x) != y
                                      for x, y in zip(b0, bA)):
                raise Refusal("aux-bank", f"{where}: the bank is not the main "
                                          f"bank exactly widened", run=r)
        _streams_and_start(salt, r, A, PA, main, half, strm, known, where)


def _next_rung(where, r, A, main):
    if main.fmt == LADDER[-1]:
        raise Refusal("aux-format",
                      f"{where}: the main run is {main.fmt}, the top of the "
                      f"ladder - a program image is at most fp256, so no "
                      f"wider run exists and a rounding estimate by one is "
                      f"refused", run=r)
    nxt = LADDER[LADDER.index(main.fmt) + 1]
    if A.fmt != nxt:
        raise Refusal("aux-format", f"{where} is {A.fmt}; one format wider "
                                    f"than {main.fmt} is {nxt}", run=r)


def _streams_and_start(salt, r, A, PA, main, half, strm, known, where):
    if half:
        if A.streams != main.streams:
            raise Refusal("aux-streams", f"{where}: its streams are not the "
                                         f"main run's", run=r)
        if A.chain[0].start != main.chain[0].start:
            raise Refusal("aux-start", f"{where} does not start on the main "
                                       f"run's initial state", run=r)
        return
    if strm[0] is not None:
        fmtA = PA["prog"].fmt
        for i, nm in enumerate("abc"):
            w = [V1.widen(main.fmt, x) for x in strm[0][i]]
            if V1.stream_hash(salt, nm, state_bytes(fmtA, w)) \
                    != A.streams[i]:
                raise Refusal("aux-streams", f"{where}: stream {nm} is not "
                                             f"the main run's exactly "
                                             f"widened", run=r)
    s0 = known.get((0, 0))
    if s0 is None:
        raise Refusal("state-missing",
                      f"{where}: holding a wider run to the main run's "
                      f"initial state exactly widened needs that state (run "
                      f"0 boundary 0), and it was not handed", run=0,
                      segment=0)
    w = [V1.widen(main.fmt, x) for x in s0]
    if state_hash(salt, state_bytes(PA["prog"].fmt, w)) != A.chain[0].start:
        raise Refusal("aux-start", f"{where} does not start on the main "
                                   f"run's initial state exactly widened",
                      run=r)


def _wider_source(cert, salt, r, A, PA, main, P0, strm, known, srcs, where):
    """The wider-source relation: the main run's source compiled at the
    next rung, with the same steps, source params and target."""
    _next_rung(where, r, A, main)
    if A.lanes != main.lanes:
        raise Refusal("aux-lanes", f"{where} has {A.lanes} lanes and the "
                                   f"main run {main.lanes}", run=r)
    s, s0 = A.source, main.source
    if s is None or s0 is None or s.compiler is None or s0.compiler is None:
        raise Refusal("aux-source",
                      f"{where}: a wider-source run and its main run each "
                      f"name the source and a compiler", run=r)
    if (s.digest, s.params, s.compiler) != (s0.digest, s0.params,
                                            s0.compiler):
        raise Refusal("aux-source",
                      f"{where}: its source, source params and compiler "
                      f"(name, output version, target) are not the main "
                      f"run's", run=r)
    if A.steps != main.steps:
        raise Refusal("aux-image", f"{where} states {A.steps} steps a "
                                   f"segment and the main run {main.steps}",
                      run=r)
    if r not in srcs or srcs[r]["compiled"] is None:
        raise Refusal("source-missing",
                      f"{where}: holding a wider-source run to the main "
                      f"run's source compiled one format wider needs the "
                      f"source, and it was not handed", run=r)
    if PA["depth"] != P0["depth"]:
        raise Refusal("aux-image", f"{where} is re-run at a scratch depth of "
                                   f"{PA['depth']} and the main run at "
                                   f"{P0['depth']}", run=r)
    if len(A.chain) != len(main.chain):
        raise Refusal("aux-segments", f"{where} has {len(A.chain)} segments; "
                                      f"a wider-source run has the main "
                                      f"run's {len(main.chain)}", run=r)
    _streams_and_start(salt, r, A, PA, main, False, strm, known, where)


def run_segment(prog, a, b, c, start, *, bank=None,
                scratch_depth=seq.SCRATCH_D):
    """cert.run_segment with each block's per-lane flags: -> (end state,
    flags, status, the block of a byte a lane)."""
    n = len(a)
    per = prog.n_scratch_in
    out, flags, status, block = [], 0, 0, bytearray()
    for lo in range(0, n, V1.BLOCK_LANES):
        hi = min(n, lo + V1.BLOCK_LANES)
        res = seq.run(prog, a[lo:hi], b[lo:hi], c[lo:hi], bank=bank,
                      scratch_depth=scratch_depth,
                      scratch_in=start[lo * per:hi * per])
        out += res.scratch_out
        flags |= res.flags
        status |= res.status
        block += bytes(res.lane_flags)
        del res
    return out, flags, status, bytes(block)


def _definition_for(srcs, r, run, where, k):
    if r not in srcs:
        raise Refusal("source-missing",
                      f"{where}: the definition is the run's source, and "
                      f"it was not handed", run=r, segment=k)
    d = srcs[r]["definition"]
    if d is None:
        raise Refusal("source-refused",
                      f"{where}: the run is a half-step run and its source "
                      f"declares no h to halve", run=r, segment=k)
    return d


def _rerun(cert, salt, progs, strm, known, plan, srcs, cover):
    """Step 9: each chosen segment re-run, its block with it; a replay line
    held to the raw segment, each marked lane replayed by the definition,
    and the corrected segment held to the segment line."""
    from .lang.refusals import Refusal as LangRefusal
    notes = {}
    for r, run in enumerate(cert.runs):
        p = progs[r]
        fmt = p["prog"].fmt
        reps = {x.segment: x for x in run.replays}
        n_rep_lanes = n_rep_segs = blocks = 0
        for k in plan[r]["rerun"]:
            s = known.get((r, k))
            if s is None:
                raise Refusal("state-missing",
                              f"run {r} segment {k}: its start state "
                              f"(boundary {k}) was not handed"
                              + (", and it is the initial state" if k == 0
                                 else f", and segment {k - 1} was not re-run "
                                      f"to give it"), run=r, segment=k)
            a, b, c = strm[r]
            where = f"run {r} segment {k}"
            with _Through(cover):
                try:
                    out, fl, st, block = run_segment(
                        p["prog"], a, b, c, s, bank=p["bankv"],
                        scratch_depth=p["depth"])
                except seq.ProgramError as e:
                    raise Refusal("program-image", f"{where}: the executor "
                                                   f"refuses it: {e}", run=r,
                                  segment=k)
                marked = [i for i, x in enumerate(block) if x & LANE_MARK]
                rep = reps.get(k)
                if marked and rep is None:
                    raise Refusal("replay-missing",
                                  f"{where}: the re-run marks lane"
                                  f"{'s' if len(marked) > 1 else ''} "
                                  f"{marked[:8]}, and no replay line names "
                                  f"the segment", run=r, segment=k)
                if rep is not None and not marked:
                    raise Refusal("replay-unmarked",
                                  f"{where}: a replay line names it, and its "
                                  f"re-run marks no lane", run=r, segment=k)
                if rep is not None:
                    if rep.raw_end != state_hash(salt, state_bytes(fmt, out)) \
                            or rep.raw_lanes != lane_flags_hash(salt, block) \
                            or rep.marked != len(marked):
                        raise Refusal("replay-raw",
                                      f"{where}: the replay line's raw end, "
                                      f"raw block or marked count is not the "
                                      f"re-run's ({len(marked)} marked)",
                                      run=r, segment=k)
            if rep is not None:
                d = _definition_for(srcs, r, run, where, k)
                try:
                    end, nb, _m, changed = replay_segment(
                        d, s, out, block, p["nslots"], run.steps)
                except _Undecided as e:
                    raise Refusal("definition-unavailable",
                                  f"{where}: the auditor cannot evaluate the "
                                  f"definition: {e}", run=r,
                                  segment=k) from None
                except LangRefusal as e:
                    raise Refusal("source-refused",
                                  f"{where}: the language refuses to run the "
                                  f"source on these inputs: {e.name}: "
                                  f"{e.sentence}", run=r,
                                  segment=k) from None
                with _Through(cover):
                    if changed != rep.changed:
                        raise Refusal("replay-changed",
                                      f"{where}: the replay changes {changed} "
                                      f"of the {len(marked)} marked lanes, "
                                      f"and the line says {rep.changed}",
                                      run=r, segment=k)
                out, block = end, nb
                fl, st = _flags_of(block), st & ~STATUS_MARK
                n_rep_lanes += len(marked)
                n_rep_segs += 1
            seg = run.chain[k]
            with _Through(cover):
                if state_hash(salt, state_bytes(fmt, out)) != seg.end:
                    raise Refusal("segment-end",
                                  f"{where}: re-run from its certified start "
                                  f"state" + (" and replayed" if rep else "")
                                  + ", it does not end on its certified end "
                                    "state", run=r, segment=k)
                if run.lane_flags and lane_flags_hash(salt, block) \
                        != seg.lanes:
                    raise Refusal("segment-lane-flags",
                                  f"{where}: the re-run's block is not the "
                                  f"certified one", run=r, segment=k)
                if fl != seg.flags:
                    raise Refusal("segment-flags",
                                  f"{where}: the re-run raises flags {fl} and "
                                  f"the certificate says {seg.flags}", run=r,
                                  segment=k)
                if st != seg.status:
                    raise Refusal("segment-status",
                                  f"{where}: the re-run's STATUS is {st} and "
                                  f"the certificate says {seg.status}",
                                  run=r, segment=k)
            if run.lane_flags:
                blocks += 1
            known.setdefault((r, k + 1), out)
        notes[r] = (n_rep_lanes, n_rep_segs, blocks)
    return notes


def _define_rerun(cert, salt, progs, strm, known, dplan, srcs, cover):
    """Step 9a, the auditor's choice: each chosen segment run by the
    source's interpreter from its certified start, lane by lane, must end
    on the certified state (`definition-end`) and raise the certified flag
    word and block (`definition-flags`)."""
    from .lang.refusals import Refusal as LangRefusal
    done = {}
    for r in sorted(dplan):
        run, p = cert.runs[r], progs[r]
        fmt = p["prog"].fmt
        for k in dplan[r]:
            where = f"run {r} segment {k}"
            s = known.get((r, k))
            if s is None:
                raise Refusal("state-missing",
                              f"{where}: the definition re-run starts from "
                              f"boundary {k}, which was neither handed nor "
                              f"re-run into", run=r, segment=k)
            d = _definition_for(srcs, r, run, where, k)
            n = p["nslots"]
            end, block = [], bytearray()
            for i in range(run.lanes):
                try:
                    vals, fl = _evaluate(d, s[i * n:(i + 1) * n], run.steps)
                except _Undecided as e:
                    raise Refusal("definition-unavailable",
                                  f"{where}: the auditor cannot evaluate the "
                                  f"definition: {e}", run=r,
                                  segment=k) from None
                except LangRefusal as e:
                    raise Refusal("source-refused",
                                  f"{where}: the language refuses to run the "
                                  f"source on these inputs: {e.name}: "
                                  f"{e.sentence}", run=r,
                                  segment=k) from None
                end += vals
                block.append(fl)
            seg = run.chain[k]
            with _Through(cover):
                if state_hash(salt, state_bytes(fmt, end)) != seg.end:
                    raise Refusal("definition-end",
                                  f"{where}: the source's interpreter, from "
                                  f"the certified start, does not end on the "
                                  f"certified end state", run=r, segment=k)
                if _flags_of(block) != seg.flags or (
                        run.lane_flags and
                        lane_flags_hash(salt, block) != seg.lanes):
                    raise Refusal("definition-flags",
                                  f"{where}: the source's interpreter does "
                                  f"not raise the certified flags"
                                  + (" or block" if run.lane_flags else ""),
                                  run=r, segment=k)
        done[r] = list(dplan[r])
    return done


def _verdict(cert, name, plan, dplan, values, sig_line, sup_line, cover,
             srcs, notes, dnotes, blocks_seen, initial_line, states):
    out = ["cft-certificate 2: ACCEPTED - every check passed",
           f"certificate {name}: its name, the SHA-256 of its body",
           "keyed: the salt handed is the one committed to"
           if cert.mode == "keyed" else
           "open: no salt - its hashes are plain SHA-256, and anyone "
           "holding the states can audit it",
           sig_line, sup_line, cover.describe()]
    for r in plan:
        i = r["run"]
        run = cert.runs[i]
        head = (f"run {i} {r['kind']} {r['format']}, {r['lanes']} lanes, "
                f"{r['segments']} segments: re-ran {len(r['rerun'])} of "
                f"{r['segments']}")
        if r["how"] == "sample":
            S, k = r["segments"], len(r["rerun"])
            p1 = V1.escape_probability(S, k, 1)
            head += (f", a sample drawn with the auditor's seed {r['seed']}: "
                     f"a producer who made f of these {S} segments wrong "
                     f"escapes it with probability C({S}-f,{k})/C({S},{k}); "
                     f"for f = 1 that is {p1.numerator}/{p1.denominator}; "
                     f"the segments sampled: {V1._segment_list(r['rerun'])}")
        elif r["how"] == "named":
            head += f", the segments named: {V1._segment_list(r['rerun'])}"
        else:
            head += ", every segment"
        out.append(head)
        if run.source is None:
            out.append(f"run {i} source: none")
        elif i in srcs:
            out.append(srcs[i]["note"])
        else:
            out.append(f"run {i} source {run.source.digest}: named, not "
                       f"handed - stated, not checked")
        if run.lane_flags:
            seen = blocks_seen.get(i, [])
            out.append(f"run {i} lane flags: {notes[i][2]} blocks re-run and "
                       f"matched" + (f", segments {V1._segment_list(seen)} "
                                     f"handed and consistent" if seen else ""))
        else:
            out.append(f"run {i} lane flags: none - the run did not ask for "
                       f"them")
        nl, ns, _b = notes[i]
        out.append(f"run {i} replays: {nl} lane{'s' if nl != 1 else ''} in "
                   f"{ns} segment{'s' if ns != 1 else ''} replayed by the "
                   f"definition, each matched" if ns else
                   f"run {i} replays: none in the segments re-run")
        if i in dnotes:
            out.append(f"run {i} definition re-run: segments "
                       f"{V1._segment_list(dnotes[i])} run by the source's "
                       f"interpreter, each ending on its certified state "
                       f"with its certified flags")
    for j, q in enumerate(values):
        out.append(f"accuracy entry {j}: re-derived as {V1.rational_text(q)}"
                   f" - the value is the stated function of the certified "
                   f"runs; that an estimate estimates well is not shown")
    out.append(initial_line)
    out.append("handed: " + _handed(cert, srcs, states, initial_line))
    out += V1.identity_report(cert)
    out += provenance_report(cert.provenance)
    auditor = [f"auditor golden {runtime_text(True)}",
               f"audited {utc_now()}"]
    return Verdict(name, cert.mode, out, auditor)


def _handed(cert, srcs, states, initial_line):
    """What the audit was handed, as three levels after ACM's and NISO's
    vocabulary: rebuilt (every image and bank the auditor's own recompile,
    the initial state regenerated, no other state handed), re-run from
    the start (states at boundary 0 alone), or re-run."""
    states = states or {}
    beyond = any(b != 0 for per in states.values() if isinstance(per, dict)
                 for b in per)
    rebuilt = (all(i in srcs and srcs[i]["compiled"] is not None
                   for i in range(len(cert.runs)))
               and initial_line.startswith("initial state: regenerated")
               and not any(per for r, per in states.items()
                           if isinstance(per, dict) and r != 0)
               and set(states.get(0, {}) or {}) <= {0})
    if rebuilt:
        return ("rebuilt - from the sources, the initial generator and the "
                "auditor's own compiles; no state of the producer's but the "
                "regenerated initial one")
    if not beyond:
        return "re-run from the start - from the initial states alone"
    return "re-run - from states handed"
