# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The golden certificates: a committed corpus of programs and their
certificates. The certificate plan's step 7 (docs/ROADMAP.md);
docs/CERTIFICATES.md, "Golden certificates", is its manual.

    python certificates/corpus.py check --tool host/cft-segrun[.exe]
                                        [--seed HEX] [--keep DIR]
    python certificates/corpus.py make  --tool host/cft-segrun[.exe]
                                        [--rewrite-all]
    python certificates/corpus.py make  --keep-version-1

`make -C host corpustest` runs `check` with the tree's cft-segrun, and
verify/run.sh's `programs` stage runs that, beside segruntest.

WHY IT EXISTS. host/tests/segrun_check.py holds cft-segrun and the golden
writer to EACH OTHER, from states made fresh, so a change that moves both
at once passes it: a change to the model, to a hash or to an encoding. A
committed certificate does not move. So every such change either keeps
the corpus's bytes or changes them in a commit that says so, by running
`make` and committing what it writes.

TWO VERSIONS. Version 1's cases are cft-segrun's certificates, held to the
golden writer. Version 2's (docs/CERTIFICATES.md, "Version 2") are the
golden writer's, and since version 2's C half (parcel CV2CW) cft-segrun's
too: each version-2 case says whether a C writer must reproduce it
(`writers both`) or whether it is a control no writer makes, made here
from a case by one named edit and refused by every auditor by one name
(`writers golden`).

WHAT `check` HOLDS, for every case certificates/MANIFEST lists:
  1. every file the manifest names against its SHA-256, and no file under
     certificates/ that it does not name, so an edited or added file
     fails by its name;
  2. every committed image against its source assembled or compiled again,
     byte for byte, and a library image against programs/MANIFEST's digest
     too;
  3. the golden writer - version 1's cert.run_chain and certify_run, or
     version 2's cert2.run_chain (its blocks and replays) and certify_run,
     at the case's depth, each accuracy entry's value derived again under
     the definition the committed certificate states, and encode, handed
     the committed certificate's header lines - writes the committed
     bytes, byte for byte; a control is its case's certificate with its
     edit made again;
  4. every boundary of the golden chain is the committed state file, and
     for version 2 every block and every replay's raw end and raw block;
  5. cft-segrun, on the software backend at the case's depth, handed the
     case's accuracy entries as the committed certificate defines them
     (each one's method, run, scope, quantity and terms, and its value's
     form - never its value), writes the committed certificate
     NORMALIZED in two places and in nothing else: its build-id line is
     the one the binary's own --build-id prints, and its hash line is
     computed again over that body. So the tool makes the three accuracy
     cases WHOLE, their values included (the plan's step 5, 2026-09-30;
     until then their accuracy block was replaced by `accuracy 0`, the
     block the tool wrote). Every other line is a function of what the
     manifest fixes - the image, bank, initial state, segments, steps,
     parameters, mode and salt, depth, and the entries' definitions -
     and of the backend, which the gate fixes to software. build-id names
     the library build, which changes with every commit by design, and
     the hash line covers it. Its boundary files are the committed ones.
     Version 2's cases marked `writers both` are the C writer's too: each
     case's hold has cft-segrun remake it, and section 5b checks that all
     seven were;
  6. the golden audit gives each case its expected verdict, in full from
     the initial states alone (from nothing but the sources and the
     generator where the case regenerates), and, for a case a writer
     makes, sampled from the committed states directory (the seed printed;
     --seed draws the same sample again);
  7. the case named `example` is docs/CERTIFICATES.md's example
     certificate, and `markstep-fp64` its version-2 example, byte for
     byte.

`make` writes the corpus again from the recipes below: every image, bank,
state and certificate, and the manifest. A version-1 certificate is the
one cft-segrun writes, its accuracy entries included; `make` refuses a case
whose entries are not, value for value, the ones the golden writer makes
from the same runs. `example` is the golden writer's, as the page prints
it (build-id unknown), and cft-segrun's entries must be its entries. It
refuses to run unless the tool's build id is clean, so that each
certificate names a commit anyone can check out. `--keep-version-1` keeps
every version-1 case as committed, its files untouched, needing no tool,
and writes version 2's again.

It KEEPS a case's committed certificate, byte for byte, where the one it
makes equals it but for build-id and the hash line and every boundary
file has the committed manifest's digest: a case's bytes, and the commit
its build-id names, move only when what it certifies does (the fixes
round, 2026-09-30). `--rewrite-all` writes every certificate the tool
makes, as `make` did before.

The manifest's grammar is read strictly by read_manifest(), which another
gate may import (programs/estimates.py does): printable ASCII and LF, one
record a line, its key first, single spaces; '#' begins a comment line
and blank lines separate cases. Paths are from the repository's root.

Exit 0 only if every check passed; the last line says so.
"""

import argparse
import dataclasses
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
MANIFEST = HERE / "MANIFEST"
DOC = ROOT / "docs" / "CERTIFICATES.md"
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "programs"))

from cft_golden import FORMATS, asm, cert, cert2, chars  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

MAGIC = "cft-golden-corpus 2"
LADDER = ("fp32", "fp64", "fp128", "fp256")
DEPTH_PARAM = "scratch-depth"
DEPTH_MAX = 1 << 15
TOOL_TIMEOUT = 120
# the files under certificates/ that are the corpus's machinery, not data
MACHINERY = ("MANIFEST", "corpus.py")
# where version 2's controls keep their certificates and their own files
CONTROLS = "certificates/v2-controls"
# docs/CERTIFICATES.md prints both: the example salt, and the published
# test key's secret, 20 21 .. 3f. Each is a test value only, never an
# owner's.
EXAMPLE_SALT = bytes(range(32))
TEST_SEED = bytes(range(32, 64))
# the issuer the test key is bound to in signed-fp64's keyring: evidently
# a test, since anyone holding the published seed can sign as it
TEST_ISSUER = "cft test issuer (published key)"
# RFC 8032 section 7.1 TEST 1's secret: a key that is not the test key
OTHER_SEED = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc4"
                           "4449c5697b326919703bac031cae7f60")

_HEX64 = re.compile(r"[0-9a-f]{64}")
_DEC = re.compile(r"0|[1-9][0-9]{0,18}")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")
_LANG = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFINE = re.compile(r"none|(0|[1-9][0-9]{0,18}):(all|(0|[1-9][0-9]{0,18})"
                     r"(,(0|[1-9][0-9]{0,18}))*)")


def sha256(data):
    return hashlib.sha256(bytes(data)).hexdigest()


def rp(path):
    """A manifest path, from the repository's root."""
    return ROOT / path


# ---- the manifest -----------------------------------------------------------

class ManifestError(ValueError):
    def __init__(self, line, message):
        super().__init__(f"certificates/MANIFEST line {line}: {message}")
        self.line = line


@dataclasses.dataclass
class Image:
    path: str               # certificates/images/<name>.cftp
    sha: str
    how: str                # library, source or compiled
    name: str               # a programs/MANIFEST name, or a source's path
    fmt: str = None         # source and compiled: the format it is made at
    steps: int = None       # compiled: cftc's --steps
    target: str = None      # compiled: cftc's --target
    params: tuple = ()      # compiled: cftc's --param, ((name, literal), ...)


@dataclasses.dataclass
class Run:
    index: int
    kind: str               # main, half-step, wider or wider-source
    h_slots: tuple
    image: str              # the path of one of Corpus.images
    bank: tuple             # (path, sha), or None for `bank none`
    segments: int
    steps: int
    parameters: tuple       # ((name, value), ...), names in byte order
    boundaries: list        # the SHA-256 of boundary 0..S's file
    source: tuple = None    # version 2: (path, sha) of the source handed
    blocks: list = dataclasses.field(default_factory=list)
    raws: list = dataclasses.field(default_factory=list)  # (k, sha, sha)

    def state_path(self, case, b):
        return f"{case.states}/run-{self.index}-boundary-{b}.bin"

    def block_path(self, case, k):
        return f"{case.blocks}/run-{self.index}-segment-{k}.flags"

    def raw_paths(self, case, k):
        base = f"{case.states}/run-{self.index}-segment-{k}-raw"
        return f"{base}.bin", f"{base}.flags"

    def depth_param(self):
        for n, v in self.parameters:
            if n == DEPTH_PARAM:
                return v
        return None


@dataclasses.dataclass
class Case:
    name: str
    what: str
    certificate: tuple      # (path, sha)
    mode: str               # open or keyed
    salt: tuple             # (path, sha) for a keyed case, else None
    depth: int
    backends: str           # any or software
    accuracy: int
    # none, or both: the golden writer and cft-segrun each make the
    # entries, held to the committed bytes (golden, only the golden
    # writer's, until the plan's step 5, 2026-09-30)
    accuracy_by: str
    verdict: str            # accepted, or the name of a refusal
    states: str             # the directory of every boundary's file
    runs: list
    line: int = 0
    version: int = 1        # the certificate's format version
    # both: the golden writer and a C writer each make it (version 2's C
    # writer from its C half on); golden: a control, made here by an edit
    writers: str = "both"
    blocks: str = None      # the directory of the blocks handed
    signature: tuple = None     # (path, sha) of a .sig handed, or None
    keyring: tuple = None       # (path, sha) of a keyring handed, or None
    superseded: str = None      # the case whose certificate is handed
    define: str = "none"        # the definition re-run: none or r:all|k,k
    regenerate: bool = False    # the audit regenerates the initial state

    def files(self):
        """(path, sha) of every file of this case's own."""
        out = [self.certificate]
        for f in (self.salt, self.signature, self.keyring):
            if f:
                out.append(f)
        for r in self.runs:
            if r.bank:
                out.append(r.bank)
            if r.source:
                out.append(r.source)
            out += [(r.state_path(self, b), h)
                    for b, h in enumerate(r.boundaries)]
            out += [(r.block_path(self, k), h)
                    for k, h in enumerate(r.blocks)]
            for k, hb, hf in r.raws:
                pb, pf = r.raw_paths(self, k)
                out += [(pb, hb), (pf, hf)]
        return out


@dataclasses.dataclass
class Corpus:
    sources: dict           # path -> sha: the corpus's own programs
    images: dict            # path -> Image
    cases: list


class _Lines:
    def __init__(self, text):
        self.rows = []
        for n, raw in enumerate(text.split("\n"), 1):
            if raw.startswith("#") or raw == "":
                continue
            self.rows.append((n, raw))
        self.i = 0
        self.last = 0

    def peek(self):
        return self.rows[self.i][1].split(" ")[0] if self.i < len(self.rows) \
            else None

    def take(self, key, ntok=None, rest=False):
        if self.i >= len(self.rows):
            raise ManifestError(self.last, f"the manifest ends where "
                                           f"`{key}` is expected")
        n, raw = self.rows[self.i]
        self.last = n
        if raw.startswith(" ") or raw.endswith(" ") or "  " in raw or \
                any(not 0x20 <= ord(c) <= 0x7E for c in raw):
            raise ManifestError(n, "not printable ASCII tokens separated by "
                                   "single spaces")
        tok = raw.split(" ")
        if tok[0] != key:
            raise ManifestError(n, f"`{key}` is expected here, and this line "
                                   f"is `{tok[0]}`")
        if rest:
            if len(tok) < 2:
                raise ManifestError(n, f"`{key}` needs its text")
            self.i += 1
            return n, raw[len(key) + 1:]
        if ntok is not None and len(tok) not in (
                ntok if isinstance(ntok, tuple) else (ntok,)):
            raise ManifestError(n, f"`{key}` takes {ntok} tokens; this line "
                                   f"has {len(tok)}")
        self.i += 1
        return n, tok


def _dec(n, tok, what, lo=0, hi=(1 << 63) - 1):
    if not _DEC.fullmatch(tok) or not lo <= int(tok) <= hi:
        raise ManifestError(n, f"{what} {tok!r} is not a decimal integer in "
                               f"{lo}..{hi} in its one spelling")
    return int(tok)


def _sha(n, tok):
    if not _HEX64.fullmatch(tok):
        raise ManifestError(n, f"{tok!r} is not a SHA-256: 64 lowercase hex "
                               f"digits")
    return tok


def _path(n, tok):
    if not _PATH.fullmatch(tok) or ".." in tok.split("/"):
        raise ManifestError(n, f"{tok!r} is not a path from the repository's "
                               f"root")
    return tok


def _file_or_none(L, key):
    n, tok = L.take(key, (2, 3))
    if tok[1:] == ["none"]:
        return None
    if len(tok) == 3:
        return (_path(n, tok[1]), _sha(n, tok[2]))
    raise ManifestError(n, f"{key} is `none` or `<path> <sha256>`")


def _image_line(n, tok):
    p, h, how = _path(n, tok[1]), _sha(n, tok[2]), tok[3]
    if how == "library" and len(tok) == 5:
        return Image(p, h, how, tok[4])
    if how == "source" and len(tok) in (5, 7):
        fmt = None
        if len(tok) == 7:
            if tok[5] != "format" or tok[6] not in LADDER:
                raise ManifestError(n, "a source image's last two tokens "
                                       "are `format <fp32|fp64|fp128|fp256>`")
            fmt = tok[6]
        return Image(p, h, how, _path(n, tok[4]), fmt)
    # image <path> <sha> compiled <source> format <fmt> steps <K>
    #       target <t> params <n> [<name> <literal>] ...
    if how == "compiled" and len(tok) >= 13:
        if (tok[5], tok[7], tok[9], tok[11]) != ("format", "steps", "target",
                                                 "params") or \
                tok[6] not in LADDER or \
                not re.fullmatch(r"[a-z0-9:-]{1,40}", tok[10]):
            raise ManifestError(n, "a compiled image is `compiled <source> "
                                   "format <fmt> steps <K> target <t> params "
                                   "<n> [<name> <literal>] ...`")
        k = _dec(n, tok[12], "params")
        if len(tok) != 13 + 2 * k:
            raise ManifestError(n, f"params says {k}, and the line does not "
                                   f"hold {k} pairs")
        params = []
        for j in range(k):
            name, lit = tok[13 + 2 * j], tok[14 + 2 * j]
            if not _LANG.fullmatch(name) or (params and
                                             name <= params[-1][0]):
                raise ManifestError(n, f"param {name!r}: a name of the "
                                       f"language, names increasing")
            params.append((name, lit))
        return Image(p, h, how, _path(n, tok[4]), tok[6],
                     _dec(n, tok[8], "steps", 1), tok[10], tuple(params))
    raise ManifestError(n, "an image is `library <name>`, `source <path> "
                           "[format <fmt>]` or `compiled <path> format <fmt> "
                           "steps <K> target <t> params <n> ...`")


def read_manifest(path=MANIFEST):
    """certificates/MANIFEST -> Corpus, read strictly: a departure from the
    grammar is a ManifestError naming its line. It holds the manifest to
    itself (counts, indices, names, every image a run names declared);
    what the files hold is `check`'s."""
    L = _Lines(Path(path).read_text(encoding="ascii"))
    n, tok = L.take("cft-golden-corpus", 2)
    if " ".join(tok) != MAGIC:
        raise ManifestError(n, f"the first line is `{MAGIC}`")
    sources, images, cases = {}, {}, []
    while L.peek() == "source":
        n, tok = L.take("source", 3)
        sources[_path(n, tok[1])] = _sha(n, tok[2])
    while L.peek() == "image":
        n, tok = L.take("image")
        if len(tok) < 5:
            raise ManifestError(n, "an image line is `image <path> <sha256> "
                                   "<how> ...`")
        im = _image_line(n, tok)
        images[im.path] = im
    if not images:
        raise ManifestError(L.last, "no image is declared")
    names = set()
    while L.i < len(L.rows):
        n0, tok = L.take("case", 2)
        name = tok[1]
        if not _NAME.fullmatch(name) or name in names:
            raise ManifestError(n0, f"case {name!r}: a name, and each once")
        names.add(name)
        _, what = L.take("what", rest=True)
        n, tok = L.take("certificate", 3)
        crt = (_path(n, tok[1]), _sha(n, tok[2]))
        n, tok = L.take("version", 2)
        version = _dec(n, tok[1], "version", 1, 2)
        n, tok = L.take("mode", 2)
        if tok[1] not in ("open", "keyed"):
            raise ManifestError(n, "mode is open or keyed")
        mode, salt = tok[1], None
        if mode == "keyed":
            n, tok = L.take("salt", 3)
            salt = (_path(n, tok[1]), _sha(n, tok[2]))
        n, tok = L.take("depth", 2)
        depth = _dec(n, tok[1], "depth", 1, DEPTH_MAX)
        if depth & (depth - 1):
            raise ManifestError(n, "depth is a power of two")
        n, tok = L.take("backends", 2)
        if tok[1] not in ("any", "software"):
            raise ManifestError(n, "backends is any or software")
        backends = tok[1]
        n, tok = L.take("writers", 2)
        if tok[1] not in ("both", "golden"):
            raise ManifestError(n, "writers is both or golden")
        writers = tok[1]
        n, tok = L.take("accuracy", 3)
        acc = _dec(n, tok[1], "accuracy")
        if tok[2] not in ("none", "both") or (acc == 0) != (tok[2] == "none"):
            raise ManifestError(n, "accuracy is `0 none` or `<A> both` with "
                                   "A at least 1")
        acc_by = tok[2]
        n, tok = L.take("verdict", (2, 3))
        if tok[1:] == ["accepted"]:
            verdict = "accepted"
        elif len(tok) == 3 and tok[1] == "refused" and \
                tok[2] in cert.REFUSALS:
            verdict = tok[2]
        else:
            raise ManifestError(n, "verdict is `accepted` or `refused "
                                   "<a refusal's name>`")
        n, tok = L.take("states", 2)
        states = _path(n, tok[1])
        n, tok = L.take("blocks", 2)
        blocks = _path(n, tok[1])
        signature = _file_or_none(L, "signature")
        keyring = _file_or_none(L, "keyring")
        n, tok = L.take("superseded", 2)
        superseded = None if tok[1] == "none" else tok[1]
        if superseded is not None and not _NAME.fullmatch(superseded):
            raise ManifestError(n, "superseded is `none` or a case's name")
        n, tok = L.take("define", 2)
        if not _DEFINE.fullmatch(tok[1]):
            raise ManifestError(n, "define is `none`, `<run>:all` or "
                                   "`<run>:<k>,<k>...`")
        define = tok[1]
        n, tok = L.take("regenerate", 2)
        if tok[1] not in ("no", "yes"):
            raise ManifestError(n, "regenerate is no or yes")
        regenerate = tok[1] == "yes"
        if version == 1 and (writers != "both" or blocks != states or
                             signature or keyring or superseded or
                             define != "none" or regenerate):
            raise ManifestError(n0, f"case {name}: a version-1 case is "
                                    f"cft-segrun's, handed nothing of "
                                    f"version 2's")
        n, tok = L.take("runs", 2)
        R = _dec(n, tok[1], "runs", 1)
        runs = []
        for i in range(R):
            n, tok = L.take("run")
            if len(tok) < 3 or tok[1] != str(i):
                raise ManifestError(n, f"run {i} is expected here")
            kind, h_slots = tok[2], ()
            if kind == "half-step":
                if len(tok) < 6 or tok[3] != "h-slots":
                    raise ManifestError(n, "a half-step run is `run <i> "
                                           "half-step h-slots <n> <slot> ...`")
                k = _dec(n, tok[4], "h-slots", 1, 512)
                if len(tok) != 5 + k:
                    raise ManifestError(n, f"h-slots says {k} and gives "
                                           f"{len(tok) - 5}")
                h_slots = tuple(_dec(n, t, "an h-slot", 0, 511)
                                for t in tok[5:])
            elif kind not in ("main", "wider", "wider-source") or \
                    len(tok) != 3:
                raise ManifestError(n, "a run is main, half-step, wider or "
                                       "wider-source")
            if (kind == "main") != (i == 0):
                raise ManifestError(n, "run 0, and only run 0, is main")
            if kind == "wider-source" and version == 1:
                raise ManifestError(n, "a wider-source run is version 2's")
            n, tok = L.take("image", 2)
            if tok[1] not in images:
                raise ManifestError(n, f"image {tok[1]} is not one the "
                                       f"manifest declares")
            img = tok[1]
            n, tok = L.take("bank", (2, 3))
            if tok[1:] == ["none"]:
                bank = None
            elif len(tok) == 3:
                bank = (_path(n, tok[1]), _sha(n, tok[2]))
            else:
                raise ManifestError(n, "bank is `none` or `<path> <sha256>`")
            src = _file_or_none(L, "source")
            if src and version == 1:
                raise ManifestError(n, "a version-1 run names no source")
            n, tok = L.take("segments", 2)
            S = _dec(n, tok[1], "segments", 1)
            n, tok = L.take("steps", 2)
            K = _dec(n, tok[1], "steps", 1)
            n, tok = L.take("parameters", 2)
            P = _dec(n, tok[1], "parameters")
            params = []
            for _ in range(P):
                n, tok = L.take("parameter", 3)
                if not _NAME.fullmatch(tok[1]):
                    raise ManifestError(n, f"{tok[1]!r} is not a name")
                params.append((tok[1], _dec(n, tok[2], "a parameter")))
            bounds = []
            for b in range(S + 1):
                n, tok = L.take("boundary", 3)
                if tok[1] != str(b):
                    raise ManifestError(n, f"boundary {b} is expected here")
                bounds.append(_sha(n, tok[2]))
            blks = []
            while L.peek() == "block":
                n, tok = L.take("block", 3)
                if tok[1] != str(len(blks)):
                    raise ManifestError(n, f"block {len(blks)} is expected "
                                           f"here")
                blks.append(_sha(n, tok[2]))
            if blks and len(blks) != S:
                raise ManifestError(n, f"a run's blocks are one a segment: "
                                       f"{S}, not {len(blks)}")
            raws = []
            while L.peek() == "raw":
                n, tok = L.take("raw", 4)
                k = _dec(n, tok[1], "a raw segment", 0, S - 1)
                if raws and k <= raws[-1][0]:
                    raise ManifestError(n, "raw segments are increasing")
                raws.append((k, _sha(n, tok[2]), _sha(n, tok[3])))
            if (blks or raws) and version == 1:
                raise ManifestError(n, "blocks and raw files are version 2's")
            runs.append(Run(i, kind, h_slots, img, bank, S, K, tuple(params),
                            bounds, src, blks, raws))
        depths = {r.depth_param() for r in runs}
        if len(depths) != 1:
            raise ManifestError(n0, f"case {name}: every run states the same "
                                    f"{DEPTH_PARAM}, or none does - one "
                                    f"handle made them")
        stated = depths.pop()
        if stated is not None and stated != depth:
            raise ManifestError(n0, f"case {name}: its runs state "
                                    f"{DEPTH_PARAM} {stated} and its depth "
                                    f"is {depth}")
        cases.append(Case(name, what, crt, mode, salt, depth, backends, acc,
                          acc_by, verdict, states, runs, n0, version, writers,
                          blocks, signature, keyring, superseded, define,
                          regenerate))
    if not cases:
        raise ManifestError(L.last, "no case")
    known = {c.name for c in cases}
    for c in cases:
        if c.superseded is not None and c.superseded not in known:
            raise ManifestError(c.line, f"case {c.name}: superseded names "
                                        f"{c.superseded}, which is no case")
    return Corpus(sources, images, cases)


HEAD = [
    "# certificates/MANIFEST - the golden certificates: every case, and",
    "# every file's SHA-256 (docs/CERTIFICATES.md, \"Golden certificates\").",
    "#",
    "# Written by `python certificates/corpus.py make`; held by its",
    "# `check` (make -C host corpustest). Paths are from the repository's",
    "# root. An implementation that uses the corpus as a conformance",
    "# test makes each case's runs from the images, banks and initial",
    "# states named here, at the case's depth, and must reproduce every",
    "# run block and accuracy value of the certificate. The identity",
    "# lines name the implementation that made it.",
    "#",
    "# A case of version 2 says whether a C writer must reproduce it",
    "# (`writers both`), or whether it is a control that no writer makes",
    "# and every auditor refuses by its verdict's name (`writers golden`),",
    "# and what its audit is handed: the sources, the blocks, a signature",
    "# and a keyring, the certificate it supersedes, the definition re-run",
    "# and the regenerated initial state.",
    "#",
    "# The one salt here, certificates/example.salt, is the bytes 00 01",
    "# .. 1f, and the one signing key the test key, whose secret is 20 21",
    "# .. 3f: docs/CERTIFICATES.md prints both, so each is a TEST value",
    "# only, and never an owner's.",
]


def write_manifest(corpus):
    """The manifest's text, from a Corpus: the inverse of read_manifest."""
    out = HEAD + [MAGIC, ""]
    for p, h in sorted(corpus.sources.items()):
        out.append(f"source {p} {h}")
    for p, im in sorted(corpus.images.items()):
        if im.how == "library":
            how = f"library {im.name}"
        elif im.how == "source":
            how = f"source {im.name}" + (f" format {im.fmt}" if im.fmt else "")
        else:
            how = (f"compiled {im.name} format {im.fmt} steps {im.steps} "
                   f"target {im.target} params {len(im.params)}"
                   + "".join(f" {n} {v}" for n, v in im.params))
        out.append(f"image {p} {im.sha} {how}")
    for c in corpus.cases:
        out += ["", f"case {c.name}", f"what {c.what}",
                f"certificate {c.certificate[0]} {c.certificate[1]}",
                f"version {c.version}", f"mode {c.mode}"]
        if c.salt:
            out.append(f"salt {c.salt[0]} {c.salt[1]}")
        out += [f"depth {c.depth}", f"backends {c.backends}",
                f"writers {c.writers}",
                f"accuracy {c.accuracy} {c.accuracy_by}",
                "verdict accepted" if c.verdict == "accepted" else
                f"verdict refused {c.verdict}",
                f"states {c.states}", f"blocks {c.blocks}"]
        for key, f in (("signature", c.signature), ("keyring", c.keyring)):
            out.append(f"{key} {f[0]} {f[1]}" if f else f"{key} none")
        out += [f"superseded {c.superseded or 'none'}",
                f"define {c.define}",
                f"regenerate {'yes' if c.regenerate else 'no'}",
                f"runs {len(c.runs)}"]
        for r in c.runs:
            head = f"run {r.index} {r.kind}"
            if r.kind == "half-step":
                head += f" h-slots {len(r.h_slots)} " + \
                        " ".join(str(s) for s in r.h_slots)
            out += [head, f"image {r.image}",
                    f"bank {r.bank[0]} {r.bank[1]}" if r.bank else "bank none",
                    f"source {r.source[0]} {r.source[1]}" if r.source
                    else "source none",
                    f"segments {r.segments}", f"steps {r.steps}",
                    f"parameters {len(r.parameters)}"]
            out += [f"parameter {n} {v}" for n, v in r.parameters]
            out += [f"boundary {b} {h}" for b, h in enumerate(r.boundaries)]
            out += [f"block {k} {h}" for k, h in enumerate(r.blocks)]
            out += [f"raw {k} {hb} {hf}" for k, hb, hf in r.raws]
    return "\n".join(out) + "\n"


# ---- images -----------------------------------------------------------------

def library_digests():
    """programs/MANIFEST: image name -> SHA-256."""
    m = {}
    for line in (ROOT / "programs" / "MANIFEST").read_text(
            encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            h, name = line.split()
            m[name] = h
    return m


def assemble(im):
    """An Image's bytes, made from its source: a library image from
    programs/<stem>.cfta, a source image from its path with its one
    `.format` line set to the named rung when one is named, and a compiled
    image by cftc from its .cftl at its format (the format override), with
    its steps, target and params."""
    if im.how == "library":
        stem = im.name[:-len(".cftp")] if im.name.endswith(".cftp") \
            else im.name
        src = (ROOT / "programs" / f"{stem}.cfta").read_text(encoding="utf-8")
        return asm.assemble(src, stem)
    if im.how == "compiled":
        return cert2.compile_source(rp(im.name).read_bytes(), im.fmt,
                                    im.steps, im.target,
                                    dict(im.params)).image
    src = rp(im.name).read_text(encoding="utf-8")
    if im.fmt:
        lines = [ln for ln in src.split("\n") if ln.startswith(".format")]
        if len(lines) != 1:
            raise ValueError(f"{im.name}: {len(lines)} `.format` lines, and "
                             f"a format is set on exactly one")
        src = src.replace(lines[0], f".format   {im.fmt}")
    return asm.assemble(src, Path(im.path).stem)


# ---- the recipes `make` writes the corpus from ----------------------------

def dec(fmt, text):
    return chars.from_decimal(FORMATS[fmt], text, sf.RND_RNE)[0]


def halved(fmt, bank, slots):
    """The bank with each named slot exactly halved: a half-step bank."""
    vals = cert.state_values(fmt, bank)
    half = dec(fmt, "0.5")
    for s in slots:
        vals[s], fl = sf.mul(FORMATS[fmt], vals[s], half)
        assert fl == 0, "halving is exact for these banks"
    return cert.state_bytes(fmt, vals)


def widened(fmt, data):
    """Bytes of fmt elements, each exactly widened a rung (convertFormat)."""
    up = LADDER[LADDER.index(fmt) + 1]
    return cert.state_bytes(up, [cert.widen(fmt, x)
                                 for x in cert.state_values(fmt, data)])


# Henon-Heiles' energy, the page's example's quantity: (px^2 + py^2)/2 +
# (x^2 + y^2)/2 + x^2 y - y^3/3, with slots (x, y, px, py) = (0, 1, 2, 3)
ENERGY = ((Fraction(1, 2), (2, 2)), (Fraction(1, 2), (3, 3)),
          (Fraction(1, 2), (0, 0)), (Fraction(1, 2), (1, 1)),
          (Fraction(1), (0, 0, 1)), (Fraction(-1, 3), (1, 1, 1)))
# the page's example: its identity, as test_cert.py's IDENTITY
PAGE_IDENTITY = cert.Identity(backend="software", device_xclbin="none",
                              device_version="none", device_caps="none",
                              device_tiles=1)


@dataclasses.dataclass
class RunRecipe:
    kind: str
    image: Image
    bank: bytes             # b"" for an image that carries its constants
    bank_path: str          # a library bank's path, or None: written here
    init: bytes
    segments: int
    steps: int
    params: tuple = ()
    h_slots: tuple = ()


@dataclasses.dataclass
class EntryRecipe:
    method: str
    uses: int
    lane: object            # a lane, or None for the maximum over lanes
    form: str
    fmt: str = None
    rnd: str = None
    label: str = None
    terms: tuple = ()


@dataclasses.dataclass
class CaseRecipe:
    name: str
    what: str
    runs: list
    mode: str = "open"
    depth: int = 256
    backends: str = "any"
    verdict: str = "accepted"
    entries: tuple = ()
    by_depth_option: bool = False   # made with --scratch-depth


def _lib_image(stem):
    return Image(f"certificates/images/{stem}.cftp", None, "library",
                 f"{stem}.cftp")


def _src_image(stem, src, fmt=None):
    return Image(f"certificates/images/{stem}.cftp", None, "source", src, fmt)


def ensemble(base, fmt, lanes):
    """Each lane displaced from the first by an exact dyadic amount, as
    programs/check.py's and segrun_check's ensembles are."""
    import gen_odes
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


def ode_runs(base, fmt, lanes, S, wider, init=None, half_init=None):
    import gen_odes
    name = f"{base}-{fmt}"
    bank_path = f"programs/{name}.classic.bank"
    bank = rp(bank_path).read_bytes()
    names = [n for n, _ in gen_odes.bank_values(base, FORMATS[fmt])]
    h_slots = tuple(i for i, n in enumerate(names)
                    if n in ("H", "H2", "H6", "MH"))
    init = init if init is not None else ensemble(base, fmt, lanes)
    steps = gen_odes.STEPS[base]
    img = _lib_image(name)
    runs = [RunRecipe("main", img, bank, bank_path,
                      cert.state_bytes(fmt, init), S, steps,
                      params=(("ensemble-spread", 64), ("members", lanes))),
            RunRecipe("half-step", img, halved(fmt, bank, h_slots), None,
                      cert.state_bytes(fmt, half_init if half_init is not None
                                       else init), 2 * S, steps,
                      params=(("members", lanes),), h_slots=h_slots)]
    if wider:
        up = LADDER[LADDER.index(fmt) + 1]
        runs.append(RunRecipe(
            "wider", _src_image(f"{base}-{up}", f"programs/{name}.cfta", up),
            widened(fmt, bank), None,
            widened(fmt, cert.state_bytes(fmt, init)), S, steps))
    return runs


def recipes():
    """Every version-1 case of the corpus, as `make` writes it (the lead's
    decision, 2026-09-29: eleven cases and the twelfth, half-init;
    deepwrap's depth ladder and half-step runs, and augsum's tie lanes, the
    fixes round, 2026-09-30)."""
    C = []
    C.append(CaseRecipe(
        "lorenz63-rk4-fp64",
        "Lorenz-63 by RK4 at fp64, 3 lanes: a main run of 3 segments, a "
        "half-step run of 6 and a wider fp128 run of 3; a wider estimate "
        "enclosed in fp64 and a step-halving estimate exact",
        ode_runs("lorenz63-rk4", "fp64", 3, 3, True),
        entries=(EntryRecipe("wider", 2, 0, "enclosed", "fp64"),
                 EntryRecipe("step-halving", 1, None, "exact"))))
    C.append(CaseRecipe(
        "lorenz63-rk4-fp256",
        "Lorenz-63 by RK4 at fp256, 3 lanes: a main run of 3 segments and "
        "a half-step run of 6",
        ode_runs("lorenz63-rk4", "fp256", 3, 3, False)))
    C.append(CaseRecipe(
        "lorenz96-rk4-fp64",
        "Lorenz-96 by RK4 at fp64, 2 lanes of 40 slots: a main run of 2 "
        "segments, a half-step run of 4 and a wider fp128 run of 2",
        ode_runs("lorenz96-rk4", "fp64", 2, 2, True)))
    C.append(CaseRecipe(
        "lorenz96-rk4-fp256",
        "Lorenz-96 by RK4 at fp256, 2 lanes of 40 slots: a main run of 2 "
        "segments and a half-step run of 4",
        ode_runs("lorenz96-rk4", "fp256", 2, 2, False)))
    C.append(CaseRecipe(
        "henonheiles-lf-fp64",
        "Henon-Heiles by Stormer-Verlet at fp64, 4 lanes: a main run of 4 "
        "segments, a half-step run of 8 and a wider fp128 run of 4",
        ode_runs("henonheiles-lf", "fp64", 4, 4, True)))
    C.append(CaseRecipe(
        "henonheiles-lf-fp256",
        "Henon-Heiles by Stormer-Verlet at fp256, 4 lanes: a main run of 4 "
        "segments and a half-step run of 8; the energy's drift over the "
        "lanes, exact, near the width rule",
        ode_runs("henonheiles-lf", "fp256", 4, 4, False),
        entries=(EntryRecipe("drift", 0, None, "exact", label="energy",
                             terms=ENERGY),)))
    ex = ode_runs("henonheiles-lf", "fp64", 2, 2, False)
    for r in ex:
        r.params = ()
    C.append(CaseRecipe(
        "example",
        "docs/CERTIFICATES.md's example certificate, byte for byte: "
        "Henon-Heiles at fp64, 2 lanes, a main run of 2 segments and a "
        "half-step run of 4, KEYED under the page's example salt, with the "
        "page's two entries",
        ex, mode="keyed",
        entries=(EntryRecipe("drift", 0, 1, "exact", label="energy",
                             terms=ENERGY),
                 EntryRecipe("step-halving", 1, None, "rounded", "fp64",
                             "rup"))))
    fl = _src_image("flagstep-fp64", "certificates/programs/flagstep-fp64.cfta")
    C.append(CaseRecipe(
        "flagstep-fp64",
        "flagstep, the corpus's own: 2 lanes, 5 segments raising flags 20, "
        "0, 1, 0, 20 and STATUS 48, 48, 0, 48, 48",
        [RunRecipe("main", fl, b"", None, cert.state_bytes(
            "fp64", [dec("fp64", t) for t in ("3", "1", "3", "5")]), 5, 1)]))
    au = _src_image("augsum-fp64", "certificates/programs/augsum-fp64.cfta")
    # lanes 2 and 3 (the fixes round, 2026-09-30): the first augadd of each
    # is +-(2^53 + 3), a tie between +-(2^53 + 2), whose significand is
    # odd, and +-(2^53 + 4), so roundTiesTowardZero and roundTiesToEven
    # part there. Lane 1's 1e16 + 1 is a tie at which they agree.
    tie = str(2 ** 53 + 2)
    C.append(CaseRecipe(
        "augsum-fp64",
        "augsum, the corpus's own: revision 8's augadd and augerr in a "
        "compensated sum, and a stepped STX and LDX; 4 lanes, 3 segments, "
        "lanes 2 and 3 meeting augadd ties, +-(2^53 + 3), at which "
        "roundTiesTowardZero and roundTiesToEven part; the software "
        "backend only",
        [RunRecipe("main", au, b"", None, cert.state_bytes(
            "fp64", [dec("fp64", t) for t in
                     ("1", "0", "0.1", "0", "1e16", "0", "1", "0",
                      tie, "0", "1", "0", "-" + tie, "0", "-1", "0")]),
            3, 4)],
        backends="software"))
    # deepwrap: its bank is H, 1.0, and the raw integers 32,768, 1 and 2
    # (the source's header); the half-step run halves H, slot 0
    dw = _src_image("deepwrap-fp64", "certificates/programs/deepwrap-fp64.cfta")
    dwb = cert.state_bytes("fp64", [dec("fp64", "0.25"), dec("fp64", "1"),
                                    1 << 15, 1, 2])
    dwi = cert.state_bytes("fp64", [dec("fp64", t) for t in
                                    ("1", "0.25", "0", "2", "0.5", "0")])
    for depth in (256, 2048):
        C.append(CaseRecipe(
            f"deepwrap-fp64-{depth}",
            f"deepwrap, the corpus's own, at {depth:,} scratch slots: a "
            f"non-strict ldx at p and stx at p + 2, for p = 16,384 down to "
            f"128, reach the carried block at every depth up to p, so every "
            f"depth from 128 to 32,768 has its own chain; a main run of 3 "
            f"segments and a half-step run of 6, each stating the depth; 2 "
            f"lanes",
            [RunRecipe("main", dw, dwb, None, dwi, 3, 1,
                       params=((DEPTH_PARAM, depth),)),
             RunRecipe("half-step", dw, halved("fp64", dwb, (0,)), None, dwi,
                       6, 1, params=((DEPTH_PARAM, depth),), h_slots=(0,))],
            depth=depth, by_depth_option=True))
    hi = ode_runs("lorenz63-rk4", "fp64", 2, 2, False, half_init=[
        v for i in range(2) for v in (dec("fp64", repr(1 + i / 64 + 1 / 128)),
                                      dec("fp64", "1"), dec("fp64", "1"))])
    C.append(CaseRecipe(
        "lorenz63-rk4-fp64-half-init",
        "Lorenz-63 at fp64, 2 lanes, a main run of 2 segments and a "
        "half-step run of 4 entered from an initial state of its OWN: a "
        "relation the certificate states and does not hold, refused "
        "aux-start",
        hi, verdict="aux-start"))
    return C


# ---- version 2's recipes ------------------------------------------------------

MARK_SRC = "certificates/programs/markstep-fp64.cftl"
LORENZ_SRC = "programs/systems/lorenz63-rk4-fp64.cftl"


@dataclasses.dataclass
class RunRecipe2:
    kind: str
    image: Image
    bank: bytes             # the bank's bytes; b"" for none
    init: bytes
    segments: int
    steps: int
    params: tuple = ()      # version 1's integer parameters
    h_slots: tuple = ()
    source: str = None      # the .cftl the run names, or None
    source_name: str = "none"
    source_params: tuple = ()
    target: str = None      # where the image is cftc's compile, its target
    lane_flags: object = None
    handed: bool = True     # the source is handed to the audit


@dataclasses.dataclass
class CaseRecipe2:
    name: str
    what: str
    runs: list
    provenance: object      # a cert2.Provenance; replay-methods are made
    mode: str = "open"
    entries: tuple = ()
    verdict: str = "accepted"
    writers: str = "both"
    sign: bool = False      # a .sig by the published test key, handed
    keyring: str = None     # a keyring's text, handed
    superseded: str = None  # the case it supersedes, handed
    define: str = "none"
    regenerate: bool = False
    depth: int = 256
    backends: str = "software"


# The profile the corpus's version-2 cases state: profile.py's VERSION, as
# the compiler lines state cftc's. It was the literal "2" until profile 3
# (2026-10-05), when the corpus was made again at 3.
PROFILE_TEXT = cert2.version_text(cert2.PROFILE)
# every measured header line unknown, as version 1's example's build-id
UNKNOWN = cert2.Provenance(profile=PROFILE_TEXT, language="1",
                           device_platform="none",
                           device_xrt="none", device_clock="none",
                           device_serial="none", writer=("golden", "unknown"),
                           writer_runtime="unknown", compiler_build="none",
                           issuer="withheld", issuer_key="none")
FULL_BOX = ("signed case", "2", "4", "-1", "1")
REBUILT_BOX = ("rebuilt case", "-1", "1", "-1", "1", "20", "30")
COUNTER = (EntryRecipe("drift", 0, None, "exact", label="counter",
                       terms=((Fraction(1), (0,)),)),)


def markstep_bank(b=None, zero=0):
    """markstep's bank: the source's a and b rounded once, 1, 7, 106, and
    the raw words 1, 0x81 (the mark with invalid) and `zero`."""
    g = cert2.source_graph(rp(MARK_SRC).read_bytes())
    pa = {p[0]: p[2] for p in g.param}
    return cert.state_bytes("fp64", [pa["a"], pa["b"] if b is None else b,
                                     dec("fp64", "1"), dec("fp64", "7"),
                                     dec("fp64", "106"), 1, 0x81, zero])


def _compiled(src, fmt, steps, target="sw", params=()):
    return Image(None, None, "compiled", src, fmt, steps, target,
                 tuple(params))


def recipes2():
    """Version 2's cases a writer makes (the golden writer now, a C writer
    from version 2's C half on where `writers both`)."""
    mk = _src_image("markstep-fp64", "certificates/programs/markstep-fp64.cfta")
    mark_init = cert.state_bytes("fp64", [dec("fp64", t) for t in
                                          ("0", "0.3333", "100", "0.5", "50",
                                           "0.2")])

    def markstep(name, what, bank, **kw):
        return CaseRecipe2(
            name, what,
            [RunRecipe2("main", mk, bank, mark_init, 3, 4, source=MARK_SRC,
                        source_name="markstep-fp64.cftl")],
            UNKNOWN, entries=COUNTER, **kw)

    C = [markstep(
        "markstep-fp64",
        "version 2's replay case and docs/CERTIFICATES.md's version-2 "
        "example, byte for byte: markstep, defined by its source, 3 lanes, "
        "3 segments of 4 steps; segment 1 marks lanes 0 and 1, lane 0's "
        "last bit wrong, and the golden writer replays both by the "
        "definition (replay 1 marked 2 changed 1); the counter's drift; "
        "audited with every segment run by the source's interpreter too",
        markstep_bank(), define="0:all")]
    lz_init = []
    for i in range(3):
        lz_init += [dec("fp64", repr(1 + i / 64)), dec("fp64", "1"),
                    dec("fp64", "1")]
    lz64 = cert.state_bytes("fp64", lz_init)
    c64 = _compiled(LORENZ_SRC, "fp64", 100)
    c64.path = "certificates/images/lorenz63-rk4-fp64-cftc.cftp"
    c128 = _compiled(LORENZ_SRC, "fp128", 100)
    c128.path = "certificates/images/lorenz63-rk4-fp128-cftc.cftp"
    src_kw = dict(source=LORENZ_SRC, source_name="lorenz63-rk4-fp64.cftl",
                  target="sw")
    C.append(CaseRecipe2(
        "lorenz63-rk4-fp64-sourced",
        "Lorenz-63 compiled from programs/systems/lorenz63-rk4-fp64.cftl by "
        "cftc for sw: 3 lanes, a main run of 3 segments, a half-step run of "
        "6 on the compile's half bank (its h-slots the compile's), and a "
        "wider-source run of 3 - the source compiled at fp128; the "
        "wider-source estimate, whose wider run has the source's constants "
        "rounded at fp128 where version 1's carries the fp64 bank's "
        "widened, and the step-halving estimate",
        [RunRecipe2("main", c64, None, lz64, 3, 100,
                    params=(("members", 3),), **src_kw),
         RunRecipe2("half-step", c64, "half", lz64, 6, 100, h_slots="h",
                    **src_kw),
         RunRecipe2("wider-source", c128, None, widened("fp64", lz64), 3, 100,
                    **src_kw)],
        dataclasses.replace(UNKNOWN, compiler_build="unknown"),
        entries=(EntryRecipe("wider-source", 2, None, "enclosed", "fp64"),
                 EntryRecipe("step-halving", 1, None, "exact"))))
    fl = _src_image("flagstep-fp64", "certificates/programs/flagstep-fp64.cfta")
    C.append(CaseRecipe2(
        "flagstep-fp64-lanes",
        "flagstep at version 2 with each segment's per-lane flags: 3 lanes "
        "whose counters start at 3, 2 and 1, so that in each of the 5 "
        "segments the lanes raise different flags; the counter's drift",
        [RunRecipe2("main", fl, b"", cert.state_bytes(
            "fp64", [dec("fp64", t) for t in ("3", "1", "2", "5", "1", "7")]),
            5, 1, lane_flags=True)],
        dataclasses.replace(UNKNOWN, language="none"), entries=COUNTER))
    signed_init = cert.state_bytes("fp64", cert2.generate_initial(
        ("generator", "shake-box", FULL_BOX), "fp64", 2, 2))
    C.append(CaseRecipe2(
        "signed-fp64",
        "every header line of version 2 spelt out - texts with spaces and "
        "non-ASCII, the device lines, the writer and compiler builds, the "
        "environment - keyed, its initial state made by the shake-box "
        "generator, superseding flagstep-fp64-lanes, and signed under the "
        "published test key; audited with its signature, the keyring naming "
        "the issuer, the superseded certificate and the initial state "
        "regenerated",
        [RunRecipe2("main", fl, b"", signed_init, 3, 1, lane_flags=True)],
        cert2.Provenance(
            profile=PROFILE_TEXT, language="none",
            device_platform="xilinx_u50_gen3x16_xdma_5_202210_1",
            device_xrt="2.19.194", device_clock=135000000,
            device_serial="SN 0001 (a test)",
            writer=("golden", "commit=" + "a" * 40 +
                    " tracked=clean untracked=none"),
            writer_runtime="python-3.12.9,mpmath-1.3.0",
            compiler_build="commit=" + "b" * 40 +
                           " tracked=modified untracked=present",
            certificate_id="cert 0001 / " + chr(0x141) + chr(0xF3) + "d"
                           + chr(0x17A),
            issuer=TEST_ISSUER,
            issuer_key=cert2.ed25519.public_key(TEST_SEED).hex(),
            host_os="linux-6.8.0", host_arch="x86_64",
            started="2026-10-02T12:00:00Z", finished="2026-10-02T12:00:05Z",
            issued="2026-10-02T12:00:06Z",
            environment=(("CFT_TIMEOUT_MS", "60000"),
                         ("XCL_EMULATION_MODE", "hw_emu")),
            initial=("generator", "shake-box", FULL_BOX)),
        mode="keyed", sign=True,
        keyring=f"key {cert2.ed25519.public_key(TEST_SEED).hex()} "
                f"{cert2.text_token(TEST_ISSUER)}\n",
        superseded="flagstep-fp64-lanes", regenerate=True))
    rb_init = cert.state_bytes("fp64", cert2.generate_initial(
        ("generator", "shake-box", REBUILT_BOX), "fp64", 2, 3))
    C.append(CaseRecipe2(
        "lorenz63-rk4-fp64-rebuilt",
        "Lorenz-63 compiled by cftc, 2 lanes, 2 segments, its initial state "
        "made by the shake-box generator: its audit is handed the source and "
        "no state, recompiles the image, regenerates the initial state and "
        "re-runs every segment - rebuilt",
        [RunRecipe2("main", c64, None, rb_init, 2, 100, **src_kw)],
        dataclasses.replace(UNKNOWN, compiler_build="unknown",
                            initial=("generator", "shake-box", REBUILT_BOX)),
        regenerate=True))
    C.append(markstep(
        "markstep-fp64-other-b",
        "markstep on a bank whose b is 1/4, not its source's 1/7: an honest "
        "certificate of another map, whose marked lanes the writer replays "
        "by the source; it holds together, and the definition re-run of "
        "segment 0 refuses it definition-end",
        markstep_bank(b=dec("fp64", "0.25")), define="0:0",
        verdict="definition-end"))
    C.append(markstep(
        "markstep-fp64-loud",
        "markstep on a bank whose no-mark word is 1, so that every lane "
        "raises invalid each step: the map's values with other flags; the "
        "definition re-run of segment 2 refuses it definition-flags",
        markstep_bank(zero=1), define="0:2", verdict="definition-flags"))
    return C


# ---- version 2's controls -----------------------------------------------------

@dataclasses.dataclass
class Control:
    """A version-2 case no writer makes: its base case's certificate with
    one named defect, by `edit` (on the body's lines, then the hash line
    remade) or `rebuild` (on the certificate object, then encoded), or its
    base's certificate with one of its audit's inputs other. Every auditor
    must refuse it by `verdict`."""
    name: str
    base: str
    what: str
    verdict: str
    edit: object = None         # (lines, ctx) -> lines
    rebuild: object = None      # (Certificate, ctx) -> Certificate
    runs_from: tuple = None     # the base's runs its runs are, in order
    signature: object = "base"  # "base", None, or (ctx) -> bytes
    keyring: object = "base"
    superseded: object = "base"
    sources: object = "base"    # "base", or {run: path} to hand instead
    files: object = None        # (ctx) -> {name: bytes}: its own files
    blocks: object = "base"     # "base", None, or (ctx) -> {(r, k): bytes}
    define: object = "base"
    regenerate: object = "base"


def _line(lines, prefix, nth=0):
    hits = [i for i, ln in enumerate(lines) if ln.startswith(prefix)]
    return hits[nth]


def _set(lines, prefix, new, nth=0):
    out = list(lines)
    out[_line(out, prefix, nth)] = new
    return out


def _put(lines, prefix, new, nth=0):
    """The line that starts with `prefix` replaced by the lines `new`."""
    i = _line(lines, prefix, nth)
    return list(lines[:i]) + list(new) + list(lines[i + 1:])


def _field(lines, prefix, i, value, nth=0):
    out = list(lines)
    j = _line(out, prefix, nth)
    t = out[j].split(" ")
    t[i] = value
    out[j] = " ".join(t)
    return out


def _drop(lines, *prefixes):
    return [ln for ln in lines if not ln.startswith(prefixes)]


def controls():
    """One committed control for each version-2 refusal a static case can
    carry, each from a case above. `definition-unavailable` and
    `replay-undecided` depend on the auditor's or the writer's environment,
    and are test_cert2.py's alone."""
    A, B, C, D = ("markstep-fp64", "lorenz63-rk4-fp64-sourced",
                  "flagstep-fp64-lanes", "signed-fp64")
    test_key = cert2.ed25519.public_key(TEST_SEED).hex()

    def refused_source(ctx):
        return rp(MARK_SRC).read_bytes().replace(b"step   map",
                                                 b"step   mapp")

    def edited_source(ctx):
        return rp(MARK_SRC).read_bytes().replace(b"; markstep - the",
                                                 b"; markstep: the")

    def no_lanes(lines, ctx):
        out = [ln if not ln.startswith("segment ") else
               " ".join(ln.split(" ")[:10]) for ln in lines]
        return _set(out, "lane-flags ", "lane-flags no")

    def no_source(lines, ctx):
        i, j = _line(lines, "source "), _line(lines, "lanes ")
        return lines[:i] + ["source none"] + lines[j:]

    def no_method(lines, ctx):
        i = _line(lines, "replay-methods ")
        return lines[:i] + ["replay-methods 0"] + lines[i + 2:]

    def no_replay(lines, ctx):
        out = no_method(lines, ctx)
        i = _line(out, "replays ")
        return out[:i] + ["replays 0"] + out[i + 2:]

    def unmarked(lines, ctx):
        i = _line(lines, "replays ")
        t = lines[i + 1].split(" ")
        t[1], t[3], t[5] = "0", "1", "0"
        return lines[:i] + ["replays 2", " ".join(t)] + lines[i + 1:]

    def seg1_end(lines, ctx):
        return _field(lines, "replay ", 7,
                      lines[_line(lines, "segment 1 ")].split(" ")[5])

    def other_block(ctx):
        blk = ctx.blocks[(0, 0)]
        return bytes([blk[0] & ~0x10]) + blk[1:]

    def identity_block(ctx):
        return bytes(b & ~0x10 for b in ctx.blocks[(0, 0)])

    def lanes_of(block_fn):
        def edit(lines, ctx):
            return _field(lines, "segment 0 ", 11,
                          cert2.lane_flags_hash(None, block_fn(ctx)))
        return edit

    def source_format(c, ctx):
        r2 = dataclasses.replace(c.runs[2], kind="main")
        return dataclasses.replace(c, runs=(r2,), accuracy=())

    def source_shape(c, ctx):
        r0 = dataclasses.replace(c.runs[0], source=cert2.source_lines(
            rp(MARK_SRC).read_bytes(), "fp64", name="markstep-fp64.cftl"))
        return dataclasses.replace(c, runs=(r0,), accuracy=())

    def initial_tag(c, ctx):
        _g, name, args = c.provenance.initial
        return dataclasses.replace(c, provenance=dataclasses.replace(
            c.provenance, initial=("generator", name,
                                   ("another tag",) + args[1:])))

    other = cftc_version() + 97
    X = [
        Control("v2-marked", A, "a segment line's STATUS with the mark, "
                "STATUS[6]", "marked",
                edit=lambda L, c: _field(L, "segment 1 ", 9, "64")),
        Control("v2-replay-lane-flags", A, "replay lines in a run that says "
                "lane-flags no", "replay-lane-flags", edit=no_lanes),
        Control("v2-replay-source", A, "replay lines in a run that names no "
                "source", "replay-source", edit=no_source),
        Control("v2-replay-method", A, "a run with replay lines and no "
                "replay-method line", "replay-method", edit=no_method),
        Control("v2-provenance-order", A, "started after finished",
                "provenance-order",
                edit=lambda L, c: _set(_set(L, "started ",
                                            "started 2026-10-02T12:00:06Z"),
                                       "finished ",
                                       "finished 2026-10-02T12:00:05Z")),
        Control("v2-signature-format", D, "a signature file of four lines",
                "signature-format",
                signature=lambda c: b"\n".join(
                    c.signature.split(b"\n")[:4]) + b"\n"),
        Control("v2-signature", D, "another certificate's signature file",
                "signature",
                signature=lambda c: cert2.signature_file(
                    TEST_SEED, c.others[C])),
        Control("v2-signature-key", D, "a signature by a key other than the "
                "certificate's issuer-key", "signature-key",
                signature=lambda c: cert2.signature_file(OTHER_SEED, c.data)),
        Control("v2-signer", D, "a keyring naming the signing key as another "
                "holder than the issuer", "signer",
                keyring=lambda c: f"key {test_key} Someone%20Else\n"
                .encode("ascii")),
        Control("v2-supersedes", D, "another certificate handed as the one "
                "it supersedes", "supersedes", superseded=A),
        Control("v2-source-digest", A, "a source handed with one byte "
                "changed", "source-digest",
                files=lambda c: {"markstep-fp64.cftl": edited_source(c)},
                sources={0: "markstep-fp64.cftl"}),
        Control("v2-source-refused", A, "a source the language refuses "
                "(step mapp), named and handed", "source-refused",
                edit=lambda L, c: _set(L, "source ",
                                       f"source {sha256(refused_source(c))}"),
                files=lambda c: {"markstep-fp64.cftl": refused_source(c)},
                sources={0: "markstep-fp64.cftl"}),
        Control("v2-source-format", B, "the fp128 compile certified as a "
                "main run of the fp64 source", "source-format",
                rebuild=source_format, runs_from=(2,)),
        Control("v2-source-graph", B, "another system's step graph named",
                "source-graph",
                edit=lambda L, c: _set(L, "graph ",
                                       f"graph {c.graphs[A]}")),
        Control("v2-source-param", B, "a source param in a spelling that is "
                "not the language's canonical one, rho 28.0", "source-param",
                edit=lambda L, c: _put(L, "source-params ",
                                       ["source-params 1",
                                        "source-param rho 28.0"])),
        Control("v2-source-shape", B, "the Lorenz-63 run naming markstep's "
                "source, whose lane is two slots to its three",
                "source-shape", rebuild=source_shape, runs_from=(0,),
                sources={0: MARK_SRC}),
        Control("v2-source-image", B, "the steps restated: the recompile's "
                "image is not the run's", "source-image",
                edit=lambda L, c: _set(L, "steps ", "steps 99")),
        Control("v2-compiler-differs", B, "another compiler named, whose "
                "recompile differs: the auditor's own limit",
                "compiler-differs",
                edit=lambda L, c: _set(_set(L, "steps ", "steps 99"),
                                       "compiler ",
                                       f"compiler cftc {other} sw")),
        Control("v2-source-missing", A, "the replay's source not handed",
                "source-missing", sources={}),
        Control("v2-lane-flags-shape", C, "a block handed one byte short",
                "lane-flags-shape",
                blocks=lambda c: {(0, 0): c.blocks[(0, 0)][:-1]}),
        Control("v2-lane-flags-hash", C, "a block handed with one byte "
                "changed", "lane-flags-hash",
                blocks=lambda c: {(0, 0): bytes([c.blocks[(0, 0)][0] ^ 0x10])
                                  + c.blocks[(0, 0)][1:]}),
        Control("v2-lane-flags-identity", C, "a block whose OR lacks the "
                "flag word's inexact, certified and handed",
                "lane-flags-identity", edit=lanes_of(identity_block),
                blocks=lambda c: {(0, 0): identity_block(c)}),
        Control("v2-initial-state", D, "the generator's tag changed: it does "
                "not regenerate the initial state", "initial-state",
                rebuild=initial_tag, signature=None),
        Control("v2-aux-source", B, "the wider-source run compiled for "
                "another target", "aux-source",
                edit=lambda L, c: _set(L, "compiler ", "compiler cftc "
                                       f"{cftc_version()} sw:2048", nth=2)),
        Control("v2-segment-lane-flags", C, "segment 0's block certified as "
                "another (one lane's inexact cleared), the blocks not handed",
                "segment-lane-flags", edit=lanes_of(other_block),
                blocks=None),
        Control("v2-replay-missing", A, "the replay line and its method "
                "dropped: the re-run still marks", "replay-missing",
                edit=no_replay),
        Control("v2-replay-unmarked", A, "a replay line for segment 0, "
                "which marks no lane", "replay-unmarked", edit=unmarked),
        Control("v2-replay-raw", A, "raw-end the hash of the corrected end",
                "replay-raw", edit=seg1_end),
        Control("v2-replay-changed", A, "changed one more than the replay "
                "changes", "replay-changed",
                edit=lambda L, c: _field(L, "replay ", 5, "2")),
        Control("v2-definition-differs", A, "changed one more, under a "
                "language the auditor's does not cover (2)",
                "definition-differs",
                edit=lambda L, c: _set(_field(L, "replay ", 5, "2"),
                                       "language ", "language 2")),
    ]
    return X


def cftc_version():
    import cftc
    return cftc.VERSION


# ---- the tool ---------------------------------------------------------------

TOOL = None


def run_tool(args):
    e = dict(os.environ)
    e.pop("CFT_SEGRUN_PLANT", None)
    try:
        r = subprocess.run([str(TOOL)] + [str(a) for a in args],
                           capture_output=True, text=True, env=e,
                           timeout=TOOL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return -1, "", f"corpus: the tool ran past {TOOL_TIMEOUT} s"
    return r.returncode, r.stdout, r.stderr


def entry_args(entries):
    """cft-segrun's options for accuracy entries (docs/CERTIFICATES.md,
    "The segment runner"), from cert.Entry objects: each one's method,
    run, scope, a drift's quantity and terms, and its value's form. Never
    its value: that is what the tool computes."""
    a = []
    for e in entries:
        a += ["--entry", e.method, "--uses", str(e.uses), "--scope",
              "max-lanes" if e.lane is None else f"lane:{e.lane}"]
        if e.method == "drift":
            a += ["--quantity", e.label]
            for c, slots in e.terms:
                a += ["--term", ",".join([cert.rational_text(Fraction(c))]
                                         + [f"s{s}" for s in slots])]
        v = e.value
        a += ["--value", "exact" if v.form == "exact" else
              f"rounded:{v.fmt}:{v.rnd}" if v.form == "rounded" else
              f"enclosed:{v.fmt}"]
    return a


def tool_args(case, runs_io, out, sdir, entries=()):
    """cft-segrun's command line for a version-1 `case`: runs_io is each
    run's (image path, bank path or None, init path); `entries` are the
    case's accuracy entries, as cert.Entry objects whose values are not
    read. cft-segrun writes version 2 by default since version 2's C half,
    so a version-1 case asks for version 1 (`--format-version 1`), which
    writes what the tool wrote before, byte for byte."""
    a = ["--format-version", "1", "--out", out, "--states", sdir]
    a += ["--salt", rp(case.salt[0])] if case.mode == "keyed" else ["--open"]
    depth = case.runs[0].depth_param()
    if depth is not None:
        a += ["--scratch-depth", str(depth)]
    for r, (img, bank, init) in zip(case.runs, runs_io):
        a += ["--run", r.kind]
        if r.kind == "half-step":
            a += ["--h-slots", ",".join(str(s) for s in r.h_slots)]
        a += ["--image", img]
        if bank:
            a += ["--bank", bank]
        a += ["--init", init, "--segments", str(r.segments),
              "--steps", str(r.steps)]
        for n, v in r.parameters:
            if n != DEPTH_PARAM:
                a += ["--param", f"{n}={v}"]
    return a + entry_args(entries)


def normalized(data, build_id):
    """The committed certificate as cft-segrun must write it: its build-id
    line the tool's, and the hash line computed again. Nothing else: since
    the plan's step 5 (2026-09-30) the tool writes the accuracy block
    too."""
    lines = cert.body_of(data).decode("ascii").split("\n")[:-1]
    lines = [f"build-id {build_id}" if ln.startswith("build-id ") else ln
             for ln in lines]
    return cert.rehash("\n".join(lines) + "\n")


# ---- the golden writer ------------------------------------------------------

def golden_runs(case, images, salt):
    """Every run of a version-1 `case` by the golden writer at the case's
    depth, from its committed inputs -> (runs, chains, progs, shapes)."""
    runs, chains, progs, shapes = [], [], {}, []
    for r in case.runs:
        img = images[r.image]
        bank = rp(r.bank[0]).read_bytes() if r.bank else b""
        prog = cert.seq.Program.from_bytes(img, scratch_depth=case.depth)
        fmt = prog.fmt.name
        init = cert.state_values(fmt, rp(r.state_path(case, 0)).read_bytes())
        st, rs = cert.run_chain(img, bank, init, r.segments,
                                scratch_depth=case.depth)
        runs.append(cert.certify_run(r.kind, img, bank, salt, st, rs,
                                     steps=r.steps, parameters=r.parameters,
                                     h_slots=r.h_slots,
                                     scratch_depth=case.depth,
                                     main_image=images[case.runs[0].image]))
        chains.append((st, rs))
        progs[r.index] = (img, bank or None)
        shapes.append((prog.fmt, prog.n_scratch_in))
    return runs, chains, progs, shapes


def golden_entries(entries, runs, shapes, chains, method_run=None):
    """Each entry's value derived again from the golden chains, under the
    definition the entry states (method, kind, uses, scope, quantity,
    form): what an implementation must reproduce is the value."""
    ends = {}
    for r, (st, _) in enumerate(chains):
        ends[(r, 0)] = st[0]
        ends[(r, len(st) - 1)] = st[-1]
    out = []
    for e in entries:
        q = cert.derive(e, runs, shapes, ends, method_run=method_run)
        v = e.value
        out.append(dataclasses.replace(
            e, value=cert.make_value(q, v.form, v.fmt, v.rnd)))
    return tuple(out)


def entries_from(recipe_entries, method_kind=None):
    """The Entry objects a recipe names, their values placeholders."""
    kinds = cert.METHOD_KIND if method_kind is None else method_kind
    return tuple(cert.Entry(e.method, kinds[e.method], e.uses,
                            e.lane, cert.Value(e.form, exact=Fraction(0),
                                               fmt=e.fmt, rnd=e.rnd),
                            e.label, e.terms) for e in recipe_entries)


def page_example(marker="<!-- the example certificate -->"):
    text = DOC.read_text(encoding="utf-8")
    at = text.index(marker)
    m = re.search(r"```[a-z]*\n(.*?)```", text[at:], re.S)
    return m.group(1).encode("ascii")


def page_example2():
    return page_example("<!-- the version-2 example certificate -->")


# ---- version 2: the golden writer's cases ---------------------------------------

# A C writer's certificate of a case marked `writers both` (from version
# 2's C half on) is held to the committed bytes with these lines left
# out of both: each is the writer's own measurement, or its own name for
# how it replayed (`replay-method <r> image <digest>` where the golden
# writer says `golden`). Every other line is held byte for byte. The
# header's statements - certificate-id, issuer, issuer-key, supersedes
# and initial - are handed to it, as the golden writer is handed them.
C_WRITER_MEASURED = ("build-id", "writer", "writer-runtime",
                     "compiler-build", "replay-method", "host-os",
                     "host-arch", "started", "finished", "issued",
                     "environment", "env")
# The four device lines are left out too only where the case carries a
# card's values (signed-fp64): `none`, which a software run measures and
# writes, is held byte for byte (verifier-VCV2B).
C_WRITER_DEVICE = ("device-platform", "device-xrt", "device-clock",
                   "device-serial")


def device_exempt(data):
    """Does a certificate carry a card's device lines, which a C writer
    on the software backend cannot write?"""
    lines = cert.body_of(data).decode("ascii").split(chr(10))
    return any(ln.startswith("device-platform ") and
               ln != "device-platform none" for ln in lines)

_COMPILES = {}


def compiled(src, fmt, steps, target, params):
    """cftc's compile, once a run: (image, bank, half bank, h-slots)."""
    key = (src, fmt, steps, target, tuple(params))
    if key not in _COMPILES:
        c = cert2.compile_source(rp(src).read_bytes(), fmt, steps, target,
                                 dict(params))
        _COMPILES[key] = (c.image, c.bank, c.half_bank,
                          tuple(c.manifest["h_slots"]))
    return _COMPILES[key]


@dataclasses.dataclass
class Made:
    """A version-2 certificate and everything beside it."""
    name: str
    data: bytes
    cert: object
    salt: object
    banks: dict             # run -> bank bytes
    chains: list            # cert2.Chain a run
    sources: dict           # run -> the source's path, handed
    signature: object       # the .sig's bytes, or None
    keyring: object         # the keyring's bytes, or None
    blocks: dict            # (run, segment) -> the block's bytes


def write_run2(r, img, bank, salt, depth, src_lines=None, source=None,
               source_params=(), main_image=None):
    """One version-2 run by the golden writer: its chain (each block, each
    marked lane replayed by the source's definition) and its Run."""
    prog = cert.seq.Program.from_bytes(img, scratch_depth=depth)
    fmt = prog.fmt.name
    definition = None
    if source is not None:
        g = cert2.source_graph(rp(source).read_bytes(), fmt)
        definition = cert2.Definition(g, source_params,
                                      half=r["kind"] == "half-step")
    init = cert.state_values(fmt, r["init"])
    ch = cert2.run_chain(img, bank, init, r["segments"], scratch_depth=depth,
                         lane_flags=r["lane_flags"], definition=definition,
                         steps=r["steps"])
    run = cert2.certify_run(r["kind"], img, bank, salt, ch, steps=r["steps"],
                            parameters=r["params"], h_slots=r["h_slots"],
                            scratch_depth=depth, source=src_lines,
                            main_image=main_image)
    return run, ch, (prog.fmt, prog.n_scratch_in)


def make2(rc, made, image_bytes):
    """A version-2 case from its recipe, by the golden writer."""
    salt = EXAMPLE_SALT if rc.mode == "keyed" else None
    runs, chains, shapes = [], [], []
    banks, sources = {}, {}
    for i, r in enumerate(rc.runs):
        img = image_bytes(r.image)
        bank, h_slots = r.bank, r.h_slots
        src_lines = None
        if r.target is not None:
            cimg, cbank, chalf, ch_slots = compiled(
                r.source, r.image.fmt, r.steps, r.target, r.source_params)
            assert cimg == img, f"{rc.name} run {i}: the image is the compile"
            bank = cbank if bank is None else chalf if bank == "half" \
                else bank
            h_slots = ch_slots if h_slots == "h" else h_slots
        if r.source is not None:
            fmt = cert.seq.Program.from_bytes(img).fmt.name
            src_lines = cert2.source_lines(
                rp(r.source).read_bytes(), fmt, name=r.source_name,
                params=dict(r.source_params),
                compiler=("cftc", cftc_version(), r.target)
                if r.target else None)
            if r.handed:
                sources[i] = r.source
        run, ch, shape = write_run2(
            dict(kind=r.kind, init=r.init, segments=r.segments,
                 steps=r.steps, params=r.params, h_slots=tuple(h_slots),
                 lane_flags=r.lane_flags), img, bank, salt, rc.depth,
            src_lines, r.source, r.source_params,
            image_bytes(rc.runs[0].image))
        runs.append(run)
        chains.append(ch)
        shapes.append(shape)
        banks[i] = bank
    ends = [(ch.states, ch.results) for ch in chains]
    entries = golden_entries(entries_from(rc.entries, cert2.METHOD_KIND),
                             runs, shapes, ends, method_run=cert2.METHOD_RUN)
    prov = dataclasses.replace(
        rc.provenance,
        replay_methods=tuple((i, "golden") for i, run in enumerate(runs)
                             if run.replays),
        supersedes=cert2.body_hash_of(made[rc.superseded].data)
        if rc.superseded else rc.provenance.supersedes)
    c = cert2.Certificate(rc.mode, cert.salt_commitment(salt) if salt
                          else None, PAGE_IDENTITY, prov, tuple(runs),
                          entries)
    data = cert2.encode(c)
    blocks = {(i, k): b for i, ch in enumerate(chains) if ch.lane_flags
              for k, b in enumerate(ch.blocks)}
    return Made(rc.name, data, cert.parse(data), salt, banks, chains,
                sources,
                cert2.signature_file(TEST_SEED, data) if rc.sign else None,
                rc.keyring.encode("ascii") if rc.keyring else None, blocks)


def remake2(case, data, images):
    """The golden writer's version-2 certificate from the manifest's inputs
    and the committed certificate's statements - its header lines, each
    run's source lines and lane-flags word - as version 1's check hands the
    golden writer the committed identity lines. -> Made."""
    c = cert.parse(data)
    salt = rp(case.salt[0]).read_bytes() if case.salt else None
    runs, chains, shapes = [], [], []
    banks, sources = {}, {}
    for r, cr in zip(case.runs, c.runs):
        img = images[r.image]
        bank = rp(r.bank[0]).read_bytes() if r.bank else b""
        init = rp(r.state_path(case, 0)).read_bytes()
        src = r.source[0] if r.source else None
        sl = None
        if cr.source is not None:
            fmt = cr.fmt
            sl = cert2.source_lines(rp(src).read_bytes(), fmt,
                                    name=cr.source.name,
                                    params=dict(cr.source.params),
                                    compiler=cr.source.compiler) \
                if src else cr.source
        run, ch, shape = write_run2(
            dict(kind=r.kind, init=init, segments=r.segments,
                 steps=r.steps, params=r.parameters, h_slots=r.h_slots,
                 lane_flags=cr.lane_flags),
            img, bank, salt, case.depth, sl, src,
            cr.source.params if cr.source else (),
            images[case.runs[0].image])
        runs.append(run)
        chains.append(ch)
        shapes.append(shape)
        banks[r.index] = bank
        if src:
            sources[r.index] = src
    ends = [(ch.states, ch.results) for ch in chains]
    entries = golden_entries(c.accuracy, runs, shapes, ends,
                             method_run=cert2.METHOD_RUN)
    made = cert2.encode(cert2.Certificate(
        c.mode, c.salt_commitment, c.identity, c.provenance, tuple(runs),
        entries))
    blocks = {(i, k): b for i, ch in enumerate(chains) if ch.lane_flags
              for k, b in enumerate(ch.blocks)}
    # the signature made again by the published test key (Ed25519 is
    # deterministic); the keyring is an input, as a state is
    sig = cert2.signature_file(TEST_SEED, made) if case.signature else None
    ring = rp(case.keyring[0]).read_bytes() if case.keyring else None
    return Made(case.name, made, cert.parse(made), salt, banks, chains,
                sources, sig, ring, blocks)


def files2(made, cdir):
    """{path: bytes} of every file a made case writes beside its
    certificate: its banks, boundaries, blocks and raw files, its
    signature and keyring."""
    out = {}
    for i, ch in enumerate(made.chains):
        fmt = ch.fmt
        if made.banks[i]:
            out[f"{cdir}/run-{i}.bank"] = made.banks[i]
        for b, st in enumerate(ch.states):
            out[f"{cdir}/states/run-{i}-boundary-{b}.bin"] = \
                cert.state_bytes(fmt, st)
        for name, blob in cert2.side_files(i, ch).items():
            out[f"{cdir}/states/{name}"] = blob
    if made.signature is not None:
        out[f"{cdir}/{made.name}.cert.sig"] = made.signature
    if made.keyring is not None:
        out[f"{cdir}/keyring"] = made.keyring
    return out


def case2_of(rc, made, image_paths):
    """The manifest's Case for a made version-2 case."""
    cdir = f"certificates/{rc.name}"
    states = f"{cdir}/states"
    files = files2(made, cdir)
    runs = []
    parsed = made.cert
    for i, cr in enumerate(parsed.runs):
        bank = (f"{cdir}/run-{i}.bank", sha256(made.banks[i])) \
            if made.banks[i] else None
        S = len(cr.chain)
        bounds = [sha256(files[f"{states}/run-{i}-boundary-{b}.bin"])
                  for b in range(S + 1)]
        blks = [sha256(files[f"{states}/run-{i}-segment-{k}.flags"])
                for k in range(S)] if cr.lane_flags else []
        raws = [(rep.segment,
                 sha256(files[f"{states}/run-{i}-segment-{rep.segment}"
                              f"-raw.bin"]),
                 sha256(files[f"{states}/run-{i}-segment-{rep.segment}"
                              f"-raw.flags"])) for rep in cr.replays]
        src = made.sources.get(i)
        runs.append(Run(i, cr.kind, cr.h_slots, image_paths[i], bank, S,
                        cr.steps, cr.parameters, bounds,
                        (src, sha256(rp(src).read_bytes())) if src else None,
                        blks, raws))
    sig = (f"{cdir}/{rc.name}.cert.sig", sha256(made.signature)) \
        if made.signature is not None else None
    ring = (f"{cdir}/keyring", sha256(made.keyring)) \
        if made.keyring is not None else None
    return Case(rc.name, rc.what, (f"{cdir}/{rc.name}.cert",
                                   sha256(made.data)), rc.mode,
                ("certificates/example.salt", sha256(EXAMPLE_SALT))
                if rc.mode == "keyed" else None, rc.depth, rc.backends,
                len(parsed.accuracy), "both" if parsed.accuracy else "none",
                rc.verdict, states, runs, 0, 2, rc.writers, states, sig,
                ring, rc.superseded, rc.define, rc.regenerate), files


class Ctx:
    """What a control's recipe reads of its base case."""

    def __init__(self, made, all_made):
        self.data = made.data
        self.signature = made.signature
        self.blocks = made.blocks
        self.others = {n: m.data for n, m in all_made.items()}
        self.graphs = {n: m.cert.runs[0].source.graph
                       for n, m in all_made.items()
                       if m.cert.runs[0].source is not None}


def control_of(ctl, base_case, ctx):
    """A control's certificate, its Case and its own files ({path: bytes}),
    from its base case's Case and certificate. The control is never read
    here: a reader may refuse it, and that refusal is its verdict."""
    cdir = f"{CONTROLS}/{ctl.name}"
    base = cert.parse(ctx.data)
    mode, accuracy, kinds = base.mode, base.accuracy, \
        [r.kind for r in base.runs]
    if ctl.rebuild is not None:
        c = ctl.rebuild(base, ctx)
        data = cert2.encode(c)
        mode, accuracy, kinds = c.mode, c.accuracy, [r.kind for r in c.runs]
    elif ctl.edit is not None:
        lines = cert.body_of(ctx.data).decode("ascii").split("\n")[:-1]
        data = cert.rehash("\n".join(ctl.edit(lines, ctx)) + "\n")
    else:
        data = ctx.data
    files = {f"{cdir}/{name}": blob
             for name, blob in (ctl.files(ctx) if ctl.files else {}).items()}
    order = ctl.runs_from or tuple(range(len(base_case.runs)))
    # a control whose runs are not its base's, in order, has states of its
    # own, since a boundary's file is named by its run
    states = f"{cdir}/states" if ctl.runs_from else base_case.states
    if ctl.blocks == "base":
        blocks_dir = base_case.blocks
    elif ctl.blocks is None:
        blocks_dir = states
    else:
        blocks_dir = f"{cdir}/blocks"
    variant = ctl.blocks(ctx) if callable(ctl.blocks) else {}
    runs = []
    for new, old in enumerate(order):
        br = base_case.runs[old]
        if ctl.runs_from:
            assert not br.blocks and not br.raws, \
                f"{ctl.name}: a run moved to another index keeps no blocks"
            for b in range(br.segments + 1):
                files[f"{states}/run-{new}-boundary-{b}.bin"] = \
                    rp(br.state_path(base_case, b)).read_bytes()
        blks = []
        if ctl.blocks == "base":
            blks = list(br.blocks)
        elif ctl.blocks is not None:
            for k in range(len(br.blocks)):
                blob = variant.get((new, k),
                                   rp(br.block_path(base_case, k))
                                   .read_bytes())
                files[f"{blocks_dir}/run-{new}-segment-{k}.flags"] = blob
                blks.append(sha256(blob))
        if ctl.sources == "base":
            src = br.source
        elif ctl.sources.get(new) is None:
            src = None
        else:
            p = ctl.sources[new]
            path = p if "/" in p else f"{cdir}/{p}"
            blob = files[path] if path in files else rp(path).read_bytes()
            src = (path, sha256(blob))
        runs.append(Run(new, kinds[new], br.h_slots, br.image, br.bank,
                        br.segments, br.steps, br.parameters,
                        list(br.boundaries), src, blks, list(br.raws)))

    def handed(attr, fname):
        v = getattr(ctl, attr)
        if v == "base":
            return getattr(base_case, attr)
        if v is None:
            return None
        blob = v(ctx)
        files[f"{cdir}/{fname}"] = blob
        return (f"{cdir}/{fname}", sha256(blob))

    def plain(attr):
        v = getattr(ctl, attr)
        return getattr(base_case, attr) if v == "base" else v
    case = Case(ctl.name, f"{ctl.what} (from {ctl.base}; refused "
                f"{ctl.verdict})", (f"{CONTROLS}/{ctl.name}.cert",
                                    sha256(data)),
                mode, base_case.salt, base_case.depth, base_case.backends,
                len(accuracy), "both" if accuracy else "none", ctl.verdict,
                states, runs, 0, 2, "golden", blocks_dir,
                handed("signature", f"{ctl.name}.cert.sig"),
                handed("keyring", "keyring"), plain("superseded"),
                plain("define"), plain("regenerate"))
    return data, case, files


# ---- make -----------------------------------------------------------------

def tool_build_id():
    rc, out, err = run_tool(["--build-id"])
    if rc != 0:
        sys.exit(f"corpus: {TOOL} --build-id failed: {err.strip()}")
    return out.strip()


def committed_certificates():
    """What `make` may keep: case name -> (its certificate's bytes, each
    run's boundary digests), for every case of the committed manifest
    whose certificate file has the manifest's SHA-256. Read before
    anything is cleared; empty where there is no manifest, or it does not
    read."""
    try:
        old = read_manifest()
    except (ManifestError, OSError, UnicodeDecodeError):
        return {}
    out = {}
    for c in old.cases:
        f = rp(c.certificate[0])
        data = f.read_bytes() if f.is_file() else None
        if data is not None and sha256(data) == c.certificate[1]:
            out[c.name] = (data, [r.boundaries for r in c.runs])
    return out


def make_version_1(C, committed):
    """Version 1's cases, each made by cft-segrun -> (cases, sources,
    images, kept)."""
    bid = tool_build_id()
    sources, images = {}, {}
    for c in C:
        for r in c.runs:
            im = r.image
            if im.path not in images:
                data = assemble(im)
                rp(im.path).write_bytes(data)
                images[im.path] = Image(im.path, sha256(data), im.how,
                                        im.name, im.fmt)
            if im.how == "source" and im.name.startswith("certificates/"):
                sources[im.name] = sha256(rp(im.name).read_bytes())
    lib = library_digests()
    for im in images.values():
        if im.how == "library" and lib.get(im.name) != im.sha:
            sys.exit(f"corpus make: {im.name} assembles to {im.sha[:16]}..., "
                     f"and programs/MANIFEST says {lib.get(im.name)}")
    salt_path = "certificates/example.salt"
    salt = EXAMPLE_SALT
    rp(salt_path).write_bytes(salt)
    work = Path(tempfile.mkdtemp(prefix="corpus-make-"))
    cases, kept = [], 0
    try:
        for c in C:
            t0 = time.perf_counter()
            cdir = HERE / c.name
            cdir.mkdir()
            runs = []
            io = []
            for i, r in enumerate(c.runs):
                if r.bank and r.bank_path is None:
                    bp = f"certificates/{c.name}/run-{i}.bank"
                    rp(bp).write_bytes(r.bank)
                    bank = (bp, sha256(r.bank))
                elif r.bank:
                    bank = (r.bank_path, sha256(r.bank))
                else:
                    bank = None
                init = work / f"{c.name}-run-{i}.init"
                init.write_bytes(r.init)
                io.append((rp(r.image.path), rp(bank[0]) if bank else None,
                           init))
                runs.append(Run(i, r.kind, r.h_slots, r.image.path, bank,
                                r.segments, r.steps, r.params, []))
            case = Case(c.name, c.what, (f"certificates/{c.name}/{c.name}"
                                         f".cert", None), c.mode,
                        (salt_path, sha256(salt)) if c.mode == "keyed"
                        else None, c.depth, c.backends, len(c.entries),
                        "both" if c.entries else "none", c.verdict,
                        f"certificates/{c.name}/states", runs)
            case.blocks = case.states
            out = work / f"{c.name}.cert"
            rc, _, se = run_tool(tool_args(case, io, out, rp(case.states),
                                           entries_from(c.entries)))
            if rc != 0:
                sys.exit(f"corpus make: {c.name}: cft-segrun refused it: "
                         f"{se.strip()}")
            data = out.read_bytes()
            parsed = cert.parse(data, salt=salt if c.mode == "keyed" else None)
            if c.entries or c.name == "example":
                # the tool's entries must be the golden writer's, value for
                # value, from the same runs (the plan's step 5)
                imgs = {p: rp(p).read_bytes() for p in images}
                g_runs, chains, _, shapes = golden_runs(
                    case, imgs, salt if c.mode == "keyed" else None)
                ents = golden_entries(entries_from(c.entries), g_runs,
                                      shapes, chains)
                if parsed.accuracy != tuple(ents):
                    sys.exit(f"corpus make: {c.name}: cft-segrun's accuracy "
                             f"entries are not the golden writer's from the "
                             f"same runs")
                if c.name == "example":
                    data = cert.encode(cert.Certificate(
                        parsed.mode, parsed.salt_commitment, PAGE_IDENTITY,
                        parsed.runs, ents))
            if c.name == "example" and data != page_example():
                sys.exit("corpus make: the example case is not "
                         "docs/CERTIFICATES.md's example certificate")
            for r in case.runs:
                r.boundaries = [sha256(rp(r.state_path(case, b)).read_bytes())
                                for b in range(r.segments + 1)]
            # the committed certificate is kept where this one equals it
            # but for build-id and the hash line, and so are its states
            old = committed.get(c.name)
            how = "made"
            if old is not None and \
                    old[1] == [r.boundaries for r in case.runs] and \
                    (old[0] == data or normalized(old[0], bid) == data):
                data, how = old[0], "kept"
                kept += 1
            rp(case.certificate[0]).write_bytes(data)
            case.certificate = (case.certificate[0], sha256(data))
            cases.append(case)
            print(f"  {c.name}: {len(data):,} bytes, {how}, "
                  f"{time.perf_counter() - t0:.1f} s", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return cases, sources, images, kept


def make_version_2():
    """Version 2's cases, by the golden writer, and its controls ->
    (cases, sources, images)."""
    sources, images = {}, {}

    def image_bytes(im):
        if im.path not in images:
            data = assemble(im)
            rp(im.path).write_bytes(data)
            images[im.path] = Image(im.path, sha256(data), im.how, im.name,
                                    im.fmt, im.steps, im.target, im.params)
        return rp(im.path).read_bytes()
    made, cases = {}, {}
    for rc in recipes2():
        t0 = time.perf_counter()
        m = make2(rc, made, image_bytes)
        made[rc.name] = m
        for r in rc.runs:
            for p in (r.image.name, r.source):
                if p and p.startswith("certificates/"):
                    sources[p] = sha256(rp(p).read_bytes())
        case, files = case2_of(rc, m, {i: r.image.path
                                       for i, r in enumerate(rc.runs)})
        cdir = HERE / rc.name
        (cdir / "states").mkdir(parents=True)
        for p, blob in files.items():
            rp(p).write_bytes(blob)
        rp(case.certificate[0]).write_bytes(m.data)
        if rc.name == "markstep-fp64" and m.data != page_example2():
            sys.exit("corpus make: markstep-fp64 is not docs/CERTIFICATES.md's"
                     " version-2 example certificate")
        cases[rc.name] = case
        print(f"  {rc.name}: {len(m.data):,} bytes, made by the golden "
              f"writer, {time.perf_counter() - t0:.1f} s", flush=True)
    (HERE / "v2-controls").mkdir()
    for ctl in controls():
        ctx = Ctx(made[ctl.base], made)
        data, case, files = control_of(ctl, cases[ctl.base], ctx)
        for p, blob in files.items():
            rp(p).parent.mkdir(parents=True, exist_ok=True)
            rp(p).write_bytes(blob)
        rp(case.certificate[0]).write_bytes(data)
        cases[ctl.name] = case
    print(f"  {len(controls())} controls, in {CONTROLS}", flush=True)
    return list(cases.values()), sources, images


def make(force_dirty=False, rewrite_all=False, keep_version_1=False):
    C = recipes()
    names2 = [rc.name for rc in recipes2()]
    if keep_version_1:
        old = read_manifest()
        v1 = [c for c in old.cases if c.version == 1]
        used = {r.image for c in v1 for r in c.runs}
        images = {p: im for p, im in old.images.items() if p in used}
        sources = {p: h for p, h in old.sources.items()
                   if any(im.name == p for im in images.values())}
        kept = len(v1)
        print("corpus make --keep-version-1: version 1's cases as committed",
              flush=True)
        for d in names2 + ["v2-controls"]:
            shutil.rmtree(HERE / d, ignore_errors=True)
        cases = v1
    else:
        bid = tool_build_id()
        print(f"corpus make: {TOOL}\n  build-id {bid}", flush=True)
        if not force_dirty and not bid.endswith("tracked=clean "
                                                "untracked=none"):
            sys.exit("corpus make: the tool's build is not clean, so its "
                     "certificates would name no commit anyone can check "
                     "out; build it in a clean worktree (or --force-dirty "
                     "for a trial that will not be committed)")
        # what may be kept, read before anything below is cleared
        committed = {} if rewrite_all else committed_certificates()
        if rewrite_all:
            print("  --rewrite-all: every certificate is the one made now",
                  flush=True)
        # clear what the script writes, and every other directory here but
        # programs/ and __pycache__/ (the second loop), so no stale case
        # stays
        for d in ["images"] + [c.name for c in C] + names2 + ["v2-controls"]:
            shutil.rmtree(HERE / d, ignore_errors=True)
        for stale in HERE.iterdir():
            if stale.is_dir() and stale.name not in ("programs",
                                                     "__pycache__"):
                shutil.rmtree(stale)
        (HERE / "images").mkdir()
        cases, sources, images, kept = make_version_1(C, committed)
    print("version 2, by the golden writer:", flush=True)
    cases2, sources2, images2 = make_version_2()
    sources.update(sources2)
    images.update(images2)
    MANIFEST.write_bytes(write_manifest(Corpus(sources, images,
                                               cases + cases2))
                         .encode("ascii"))
    total = sum(p.stat().st_size for p in HERE.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts)
    print(f"corpus make: {len(cases) + len(cases2)} cases ({len(cases)} of "
          f"version 1, {kept} kept; {len(cases2)} of version 2); {total:,} "
          f"bytes under certificates/ (this script and the sources "
          f"included)")
    return 0


# ---- check ----------------------------------------------------------------

CHECKS = 0
FAILED = []
SKIPS = []
NOTES = []


def ok(what):
    global CHECKS
    CHECKS += 1
    print(f"  ok    {what}", flush=True)


def bad(what):
    global CHECKS
    CHECKS += 1
    FAILED.append(what)
    print(f"  FAIL  {what}", flush=True)


def check_that(cond, what, why=""):
    if cond:
        ok(what)
    else:
        bad(what + (f" - {why}" if why else ""))
    return cond


def hold_files(corpus):
    """1. Every file the manifest names, against its digest; no file under
    certificates/ that it does not name."""
    print("== 1. every file against the manifest's SHA-256, and none unlisted",
          flush=True)
    named = dict(corpus.sources)
    named.update({p: im.sha for p, im in corpus.images.items()})
    for c in corpus.cases:
        for p, h in c.files():
            if named.get(p, h) != h:
                bad(f"{p}: named twice with two digests")
            named[p] = h
    wrong = []
    for p, h in sorted(named.items()):
        f = rp(p)
        got = sha256(f.read_bytes()) if f.is_file() else None
        if got != h:
            wrong.append(p)
            bad(f"{p}: " + ("is not there" if got is None else
                            f"its SHA-256 is {got[:16]}..., and the manifest "
                            f"says {h[:16]}..."))
    check_that(not wrong, f"the {len(named)} files the manifest names each "
               f"have its SHA-256")
    here = {p.relative_to(ROOT).as_posix() for p in HERE.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}
    unlisted = sorted(here - set(named) -
                      {f"certificates/{m}" for m in MACHINERY})
    check_that(not unlisted, "no file under certificates/ that the manifest "
               "does not name", f"unlisted: {unlisted[:8]}")


def hold_images(corpus):
    """2. Each committed image, against its source assembled or compiled
    again."""
    print("== 2. every image, against its source assembled or compiled "
          "again", flush=True)
    lib = library_digests()
    out = {}
    for p, im in sorted(corpus.images.items()):
        data = rp(p).read_bytes() if rp(p).is_file() else b""
        out[p] = data
        try:
            made = assemble(im)
        except Exception as e:      # noqa: BLE001 - reported, not raised
            bad(f"{p}: its source does not assemble: {type(e).__name__}: {e}")
            continue
        how = (f"programs/{im.name[:-5]}.cfta" if im.how == "library" else
               f"{im.name} compiled by cftc {cftc_version()} at {im.fmt}, "
               f"{im.steps} steps, for {im.target}" if im.how == "compiled"
               else im.name + (f" at {im.fmt}" if im.fmt else ""))
        check_that(made == data, f"{p} is {how}"
                   + ("" if im.how == "compiled" else " assembled")
                   + ", byte for byte")
        if im.how == "library":
            check_that(lib.get(im.name) == sha256(made),
                       f"{p} is programs/MANIFEST's {im.name}")
    return out


def hold_case(case, images, build_id, seed, work):
    print(f"== {case.name} ({case.mode}, depth {case.depth}, "
          f"{len(case.runs)} run{'s' if len(case.runs) > 1 else ''}, "
          f"verdict {case.verdict})", flush=True)
    t0 = time.perf_counter()
    salt = rp(case.salt[0]).read_bytes() if case.salt else None
    data = rp(case.certificate[0]).read_bytes()
    try:
        parsed = cert.parse(data, salt=salt)
        ok(f"{case.name}: the golden reader accepts it ({len(data):,} bytes"
           f"{', the salt its commitment' if salt else ''})")
    except cert.Refusal as e:
        bad(f"{case.name}: the golden reader refuses it: {e}")
        return
    check_that(len(parsed.accuracy) == case.accuracy,
               f"{case.name}: {case.accuracy} accuracy entries, as the "
               f"manifest says")
    try:
        depths = [cert.scratch_depth_of(parsed.identity, r)
                  for r in parsed.runs]
        why = f"it gives {depths}"
    except TypeError:
        depths = None
        why = ("cert.scratch_depth_of takes no run here: this tree's golden "
               "model does not read a run's scratch-depth parameter")
    check_that(depths == [case.depth] * len(parsed.runs),
               f"{case.name}: every run is re-run at the manifest's depth, "
               f"{case.depth}, by the page's rule (The chain)", why)
    # 3. the golden writer
    try:
        runs, chains, progs, shapes = golden_runs(case, images, salt)
        entries = golden_entries(parsed.accuracy, runs, shapes, chains)
        gold = cert.encode(cert.Certificate(
            parsed.mode, parsed.salt_commitment, parsed.identity, tuple(runs),
            entries))
    except cert.Refusal as e:
        bad(f"{case.name}: the golden writer refuses to make it again: "
            f"{e.name}: {e.message}")
        return
    check_that(gold == data, f"{case.name}: the golden writer, running every "
               f"segment itself at depth {case.depth}, handed its identity "
               f"lines, writes the committed bytes ({time.perf_counter() - t0:.1f}"
               f" s)", first_difference(data, gold))
    # 4. the golden chain's boundaries, against the committed files
    wrong = [(r.index, b) for r, (st, _) in zip(case.runs, chains)
             for b in range(len(st))
             if rp(r.state_path(case, b)).read_bytes()
             != cert.state_bytes(shapes[r.index][0], st[b])]
    check_that(not wrong, f"{case.name}: every boundary of the golden chain "
               f"is its committed state file", f"(run, boundary) {wrong[:4]}")
    # 5. cft-segrun
    if TOOL is None:
        SKIPS.append(f"{case.name}: cft-segrun")
        print(f"SKIP  {case.name}: cft-segrun's remake: no --tool given",
              flush=True)
    else:
        io = [(rp(r.image), rp(r.bank[0]) if r.bank else None,
               rp(r.state_path(case, 0))) for r in case.runs]
        out, sdir = work / f"{case.name}.cert", work / f"{case.name}.states"
        t1 = time.perf_counter()
        # the entries as the committed certificate defines them; their
        # values are what the tool must make again
        rc, _, se = run_tool(tool_args(case, io, out, sdir, parsed.accuracy))
        if check_that(rc == 0, f"{case.name}: cft-segrun makes it on the "
                      f"software backend ({time.perf_counter() - t1:.1f} s)",
                      f"rc {rc}: {se.strip()[-300:]}"):
            mine = out.read_bytes()
            got = cert.parse(mine).identity.build_id
            check_that(got == build_id, f"{case.name}: its build-id line is "
                       f"what the binary's --build-id prints",
                       f"{got!r} against {build_id!r}")
            want = normalized(data, build_id)
            what = ("the committed bytes, its accuracy entries' values made "
                    "from their definitions, but for build-id and the hash "
                    "line" if case.accuracy else "the committed bytes but for "
                    "build-id and the hash line")
            check_that(mine == want, f"{case.name}: cft-segrun writes {what}",
                       first_difference(want, mine))
            names = sorted(os.listdir(sdir)) if sdir.is_dir() else []
            want_names = sorted(Path(r.state_path(case, b)).name
                                for r in case.runs
                                for b in range(r.segments + 1))
            same = names == want_names and all(
                (sdir / nm).read_bytes() == rp(f"{case.states}/{nm}")
                .read_bytes() for nm in names)
            check_that(same, f"{case.name}: its {len(want_names)} boundary "
                       f"files are the committed ones, byte for byte",
                       f"it wrote {names[:6]}")
    # 6. the golden audit
    full = {r.index: {0: rp(r.state_path(case, 0)).read_bytes()}
            for r in case.runs}
    every = {r.index: {b: rp(r.state_path(case, b)).read_bytes()
                       for b in range(r.segments + 1)} for r in case.runs}
    choose = {r.index: ("sample", max(1, r.segments // 2))
              for r in case.runs}
    for how, kw in (("in full from the initial states alone",
                     {"states": full}),
                    ("sampled from the committed states",
                     {"states": every, "choose": choose, "seed": seed})):
        t1 = time.perf_counter()
        try:
            v = cert.audit(data, salt, progs, **kw)
            if case.verdict == "accepted":
                rer = [len(x["rerun"]) for x in v.runs]
                want = [r.segments if how.startswith("in full") else
                        max(1, r.segments // 2) for r in case.runs]
                check_that(rer == want, f"{case.name}: the golden audit "
                           f"ACCEPTS it {how}, re-running {rer} segments "
                           f"({time.perf_counter() - t1:.1f} s)")
            else:
                bad(f"{case.name}: the golden audit ACCEPTS it {how}, and "
                    f"the manifest expects it refused {case.verdict}")
        except cert.Refusal as e:
            check_that(e.name == case.verdict,
                       f"{case.name}: the golden audit refuses it {how}, "
                       f"{e.name}, its expected verdict",
                       f"expected {case.verdict}; it says {e.name}: "
                       f"{e.message}")


def audit_inputs2(case, corpus, sampled, seed):
    """The golden audit's arguments for a version-2 case, from the
    manifest: each run's image, bank and source, its states (boundary 0;
    every boundary when sampled; none of run 0's where the case
    regenerates), the blocks handed, and its signature, keyring,
    superseded certificate, definition re-run and regeneration."""
    salt = rp(case.salt[0]).read_bytes() if case.salt else None
    progs = {r.index: (rp(r.image).read_bytes(),
                       rp(r.bank[0]).read_bytes() if r.bank else None)
             for r in case.runs}
    kw = {}
    srcs = {r.index: rp(r.source[0]).read_bytes() for r in case.runs
            if r.source}
    if srcs:
        kw["sources"] = srcs
    states = {}
    for r in case.runs:
        if sampled:
            states[r.index] = {b: rp(r.state_path(case, b)).read_bytes()
                               for b in range(r.segments + 1)}
        elif not (case.regenerate and r.index == 0):
            states[r.index] = {0: rp(r.state_path(case, 0)).read_bytes()}
    kw["states"] = states
    blocks = {r.index: {k: rp(r.block_path(case, k)).read_bytes()
                        for k in range(len(r.blocks))}
              for r in case.runs if r.blocks}
    if blocks:
        kw["lane_flags"] = blocks
    if case.signature:
        kw["signature"] = rp(case.signature[0]).read_bytes()
    if case.keyring:
        kw["keyring"] = rp(case.keyring[0]).read_bytes()
    if case.superseded:
        other = next(c for c in corpus.cases if c.name == case.superseded)
        kw["superseded"] = rp(other.certificate[0]).read_bytes()
    if case.define != "none":
        r, segs = case.define.split(":")
        kw["define"] = {int(r): "all" if segs == "all" else
                        [int(k) for k in segs.split(",")]}
    if case.regenerate:
        kw["regenerate"] = True
    if sampled:
        kw["choose"] = {r.index: ("sample", max(1, r.segments // 2))
                        for r in case.runs}
        kw["seed"] = seed
    return salt, progs, kw


def hold_audits2(case, corpus, seed):
    """6. The golden audit gives the case its expected verdict: in full,
    and for a case a writer makes, sampled too."""
    data = rp(case.certificate[0]).read_bytes()
    modes = [False] if case.writers == "golden" else [False, True]
    for sampled in modes:
        how = ("sampled from the committed states" if sampled else
               "in full, run 0's initial state regenerated"
               if case.regenerate else
               "in full from the initial states alone")
        t1 = time.perf_counter()
        salt, progs, kw = audit_inputs2(case, corpus, sampled, seed)
        try:
            v = cert.audit(data, salt, progs, **kw)
            if case.verdict == "accepted":
                check_that(True, f"{case.name}: the golden audit ACCEPTS it "
                           f"{how} ({time.perf_counter() - t1:.1f} s): "
                           + "; ".join(ln for ln in v.lines()
                                       if ln.startswith("handed: ")))
            else:
                bad(f"{case.name}: the golden audit ACCEPTS it {how}, and "
                    f"the manifest expects it refused {case.verdict}")
        except cert.Refusal as e:
            check_that(e.name == case.verdict,
                       f"{case.name}: the golden audit refuses it {how}, "
                       f"{e.name}, its expected verdict",
                       f"expected {case.verdict}; it says {e.name}: "
                       f"{e.message}")


C_REMADE = []           # the writers-both cases cft-segrun remade, held


def c_writer_args(case, data, out, sdir, work):
    """cft-segrun's version-2 command line for a case marked `writers
    both`: the manifest's inputs (each run's image, bank, initial state,
    segments, steps and parameters), the committed certificate's header
    statements in their own spelling (certificate-id, issuer, issuer-key,
    supersedes, initial) and each run's lane-flags word, its accuracy
    entries' definitions (never their values), and for each run that names
    a source, cftc's compile of it made here at the run's format (the
    format override one rung up for a wider-source run), steps, target and
    source params: its manifest, from which the tool takes the run's source
    lines and to whose files it holds the run, and, where the run replays a
    marked lane, its image and bank as the replay image - this tool's route,
    which its replay-method line names where the golden writer's says
    golden."""
    import cftc
    c = cert.parse(data, salt=rp(case.salt[0]).read_bytes()
                   if case.salt else None)
    body = cert.body_of(data).decode("ascii").split("\n")[:-1]

    def val(key):
        return next(ln[len(key) + 1:] for ln in body
                    if ln.split(" ")[0] == key)
    a = ["--out", out, "--states", sdir]
    a += ["--salt", rp(case.salt[0])] if case.mode == "keyed" else ["--open"]
    depth = case.runs[0].depth_param()
    if depth is not None:
        a += ["--scratch-depth", str(depth)]
    for key in ("certificate-id", "issuer", "issuer-key", "supersedes",
                "initial"):
        a += [f"--{key}", val(key)]
    for r, cr in zip(case.runs, c.runs):
        a += ["--run", r.kind]
        if r.kind == "half-step":
            a += ["--h-slots", ",".join(str(s) for s in r.h_slots)]
        a += ["--image", rp(r.image)]
        if r.bank:
            a += ["--bank", rp(r.bank[0])]
        a += ["--init", rp(r.state_path(case, 0)), "--segments",
              str(r.segments), "--steps", str(r.steps)]
        for n, v in r.parameters:
            if n != DEPTH_PARAM:
                a += ["--param", f"{n}={v}"]
        if cr.lane_flags:
            a += ["--lane-flags"]
        if cr.source is None:
            continue
        if r.source is None:
            raise ValueError(f"run {r.index} names a source the manifest "
                             f"does not hand")
        src = rp(r.source[0]).read_bytes()
        own = cert2.own_format(src)
        target = cr.source.compiler[2] if cr.source.compiler else "sw"
        comp = cftc.compile_text(src, r.steps, target,
                                 source=Path(r.source[0]).name,
                                 fmt=None if cr.fmt == own else cr.fmt,
                                 params=dict(cr.source.params) or None)
        man = work / f"{case.name}-run-{r.index}.manifest.json"
        man.write_bytes(comp.manifest_bytes)
        a += ["--source", rp(r.source[0]), "--manifest", man]
        if cr.source.compiler is None:
            a += ["--compiler", "none"]
        if cr.replays:
            rimg = work / f"{case.name}-run-{r.index}.replay.cftp"
            rbank = work / f"{case.name}-run-{r.index}.replay.bank"
            rimg.write_bytes(comp.image)
            rbank.write_bytes(comp.half_bank if r.kind == "half-step"
                              else comp.bank)
            a += ["--replay-image", rimg, "--replay-bank", rbank]
    return a + entry_args(c.accuracy)


def held_lines(data, device):
    """A version-2 certificate's body lines a C writer is held to: every
    line but its own measurements (C_WRITER_MEASURED), and the four device
    lines too where the case carries a card's values (C_WRITER_DEVICE)."""
    skip = set(C_WRITER_MEASURED) | (set(C_WRITER_DEVICE) if device
                                     else set())
    return [ln for ln in cert.body_of(data).decode("ascii").split("\n")[:-1]
            if ln.split(" ")[0] not in skip]


def hold_case2_tool(case, data, work):
    """5. cft-segrun remakes a case marked `writers both` (version 2's C
    half): every line but its own measurements byte for byte, and its
    files - boundaries, blocks and raw files - the committed ones; a case
    with a signature is signed by cft_sign.py with the published test key,
    the tool writing its body, and verified with the committed keyring."""
    out, sdir = work / f"{case.name}.c.cert", work / f"{case.name}.c.states"
    t1 = time.perf_counter()
    try:
        args = c_writer_args(case, data, out, sdir, work)
    except Exception as e:      # noqa: BLE001 - reported, not raised
        bad(f"{case.name}: cft-segrun's command line could not be made: "
            f"{type(e).__name__}: {e}")
        return
    e = dict(os.environ)
    for n in cert2.ENVIRONMENT_NAMES:
        e.pop(n, None)
    try:
        r = subprocess.run([str(TOOL)] + [str(x) for x in args],
                           capture_output=True, text=True, env=e,
                           timeout=TOOL_TIMEOUT)
        rc, se = r.returncode, r.stderr
    except subprocess.TimeoutExpired:
        rc, se = -1, f"corpus: the tool ran past {TOOL_TIMEOUT} s"
    if not check_that(rc == 0, f"{case.name}: cft-segrun writes it at version "
                      f"2 on the software backend "
                      f"({time.perf_counter() - t1:.1f} s)",
                      f"rc {rc}: {se.strip()[-400:]}"):
        return
    mine = out.read_bytes()
    try:
        cert.parse(mine, salt=rp(case.salt[0]).read_bytes()
                   if case.salt else None)
    except cert.Refusal as x:
        bad(f"{case.name}: the golden reader refuses cft-segrun's: {x}")
        return
    device = device_exempt(data)
    want, got = held_lines(data, device), held_lines(mine, device)
    same = want == got
    check_that(same, f"{case.name}: cft-segrun writes every line but its own "
               f"measurements byte for byte ({len(want)} lines; the device "
               f"lines {'left out: a card' if device else 'held'}"
               f"{'; its replay-method names its replay image' if any(ln.startswith('replay-method ') for ln in cert.body_of(mine).decode('ascii').split(chr(10))) else ''})",
               first_difference("\n".join(want).encode("ascii"),
                                "\n".join(got).encode("ascii")))
    names = sorted(os.listdir(sdir)) if sdir.is_dir() else []
    want_names = sorted(Path(p).name for p, _h in case.files()
                        if p.startswith(case.states + "/"))
    files_same = names == want_names and all(
        (sdir / nm).read_bytes() == rp(f"{case.states}/{nm}").read_bytes()
        for nm in names)
    check_that(files_same, f"{case.name}: its {len(want_names)} boundary, "
               f"block and raw files are the committed ones, byte for byte",
               f"it wrote {names[:8]}")
    if case.signature:
        key = work / "test.key"
        if not key.exists():
            pub = cert2.ed25519.public_key(TEST_SEED).hex()
            # Mode 0600, as cft_sign.py writes a key: on POSIX it refuses
            # one its group or others can read (`usage`), and a file made
            # under the umask is 0644 or 0664 - the gate on amd-arc-box
            # failed here (2026-10-05); Windows has no such check.
            fd = os.open(str(key), os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_BINARY", 0), 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(f"cft-signing-key 1\nscheme ed25519\nseed "
                        f"{TEST_SEED.hex()}\nkey {pub}\n".encode("ascii"))
        sign = ROOT / "python" / "cft_sign.py"
        s = subprocess.run([sys.executable, str(sign), "sign", "--key",
                            str(key), "--cert", str(out)],
                           capture_output=True, text=True)
        v = subprocess.run([sys.executable, str(sign), "verify", "--cert",
                            str(out), "--keyring", str(rp(case.keyring[0]))],
                           capture_output=True, text=True)
        check_that(s.returncode == 0 and v.returncode == 0,
                   f"{case.name}: cft_sign.py signs cft-segrun's certificate "
                   f"with the published test key, and it verifies, the "
                   f"keyring naming its issuer",
                   f"sign rc {s.returncode}, verify rc {v.returncode}: "
                   f"{(s.stderr + v.stderr).strip()[-300:]}")
    if same and files_same:
        C_REMADE.append(case.name)


def hold_case2(case, corpus, images, seed, made, work=None):
    """A version-2 case a writer makes: steps 3, 4, 5 and 6."""
    print(f"== {case.name} (version 2, {case.mode}, {len(case.runs)} "
          f"run{'s' if len(case.runs) > 1 else ''}, writers {case.writers}, "
          f"verdict {case.verdict})", flush=True)
    t0 = time.perf_counter()
    data = rp(case.certificate[0]).read_bytes()
    try:
        cert.parse(data)
        ok(f"{case.name}: the golden reader accepts it ({len(data):,} "
           f"bytes)")
    except cert.Refusal as e:
        bad(f"{case.name}: the golden reader refuses it: {e}")
        return
    try:
        m = remake2(case, data, images)
    except cert.Refusal as e:
        bad(f"{case.name}: the golden writer refuses to make it again: "
            f"{e.name}: {e.message}")
        return
    made[case.name] = m
    check_that(m.data == data, f"{case.name}: the golden writer, running "
               f"every segment and replaying every marked lane itself, "
               f"handed its header lines, writes the committed bytes "
               f"({time.perf_counter() - t0:.1f} s)",
               first_difference(data, m.data))
    cdir = str(Path(case.certificate[0]).parent.as_posix())
    want = files2(m, cdir)
    wrong = [p for p, blob in want.items()
             if not p.endswith((".sig", "/keyring")) and
             (not rp(p).is_file() or rp(p).read_bytes() != blob)]
    check_that(not wrong, f"{case.name}: every boundary, block and raw "
               f"file of the golden chain is its committed file",
               f"{wrong[:4]}")
    if case.signature:
        sig = cert2.signature_file(TEST_SEED, data)
        check_that(rp(case.signature[0]).read_bytes() == sig,
                   f"{case.name}: its signature is the published test key's, "
                   f"made again byte for byte")
    if case.writers == "both":
        NOTES.append((case.name, device_exempt(data)))
        if TOOL is None:
            SKIPS.append(f"{case.name}: cft-segrun's version-2 remake")
            print(f"SKIP  {case.name}: cft-segrun's version-2 remake: no "
                  f"--tool given", flush=True)
        else:
            hold_case2_tool(case, data, work)
    hold_audits2(case, corpus, seed)


def hold_control(case, corpus, ctl, made):
    """A version-2 control: its certificate and its own files are its base
    case's with its edit made again; its audit refuses it by name."""
    print(f"== {case.name} (version 2's control, from {ctl.base}: refused "
          f"{case.verdict})", flush=True)
    base = next(c for c in corpus.cases if c.name == ctl.base)
    if ctl.base not in made:
        bad(f"{case.name}: its base {ctl.base} was not made again")
        return
    ctx = Ctx(made[ctl.base], made)
    data, want_case, files = control_of(ctl, base, ctx)
    committed = rp(case.certificate[0]).read_bytes()
    check_that(data == committed, f"{case.name}: its certificate is "
               f"{ctl.base}'s with its edit made again, byte for byte",
               first_difference(committed, data))
    wrong = [p for p, blob in files.items()
             if not rp(p).is_file() or rp(p).read_bytes() != blob]
    check_that(not wrong and want_case.files() == case.files(),
               f"{case.name}: its own files and its manifest entry are the "
               f"recipe's", f"{wrong[:4]}")
    hold_audits2(case, corpus, None)


def first_difference(a, b):
    la = a.decode("ascii", "replace").split("\n")
    lb = b.decode("ascii", "replace").split("\n")
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"line {i + 1}: {x[:100]!r} against {y[:100]!r}"
    return f"{len(la)} lines against {len(lb)}"


def check(seed, keep):
    t_all = time.perf_counter()
    print(f"corpus check: {TOOL}", flush=True)
    print(f"  the audits' sampling seed {seed.hex()} (again with --seed)",
          flush=True)
    try:
        corpus = read_manifest()
        ok(f"certificates/MANIFEST reads: {len(corpus.cases)} cases, "
           f"{len(corpus.images)} images, {len(corpus.sources)} sources")
    except (ManifestError, OSError, UnicodeDecodeError) as e:
        bad(f"certificates/MANIFEST does not read: {e}")
        return finish(t_all)
    hold_files(corpus)
    images = hold_images(corpus)
    build_id = None
    if TOOL is not None:
        rc, out, err = run_tool(["--build-id"])
        build_id = out.strip() if rc == 0 else None
        check_that(rc == 0, f"cft-segrun --build-id: {build_id}",
                   err.strip())
    work = Path(keep).resolve() if keep else \
        Path(tempfile.mkdtemp(prefix="corpus-check-"))
    work.mkdir(parents=True, exist_ok=True)
    ctls = {c.name: c for c in controls()}
    made = {}
    try:
        for case in corpus.cases:
            if case.version == 1:
                hold_case(case, images, build_id, seed, work)
            elif case.name in ctls:
                hold_control(case, corpus, ctls[case.name], made)
            elif case.writers == "golden":
                bad(f"{case.name}: a version-2 control this script has no "
                    f"recipe for")
            else:
                hold_case2(case, corpus, images, seed, made, work)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    have = {c.name for c in corpus.cases}
    missing = sorted((set(ctls) | {rc.name for rc in recipes2()}) - have)
    check_that(not missing, "the manifest holds every version-2 case and "
               "control this script's recipes make", f"missing {missing[:6]}")
    print("== 5b. the C writer's half of version 2", flush=True)
    # The NOTE that named the cases a C writer must reproduce, until
    # version 2's C half, is a check since it: cft-segrun remade each case
    # marked `writers both`, every line but its own measurements byte for
    # byte (C_WRITER_MEASURED; the four device lines too where a case
    # carries a card's values, C_WRITER_DEVICE), and its files the
    # committed ones. Without --tool each remake is a SKIP above, by name.
    both = [n for n, _d in NOTES]
    card = [n for n, d in NOTES if d]
    if TOOL is not None:
        check_that(both and sorted(C_REMADE) == sorted(both),
                   f"cft-segrun remade all {len(both)} version-2 cases marked "
                   f"writers both, every line but "
                   f"{', '.join(C_WRITER_MEASURED)} byte for byte, and the "
                   f"four device lines too where the case carries a card's "
                   f"values ({', '.join(card) or 'none'}), its files the "
                   f"committed ones: {', '.join(both)}",
                   f"remade {sorted(C_REMADE)} of {sorted(both)}")
    print("== 7. the page's example certificates", flush=True)
    ex = [c for c in corpus.cases if c.name == "example"]
    if check_that(len(ex) == 1, "the corpus has the case `example`"):
        check_that(rp(ex[0].certificate[0]).read_bytes() == page_example(),
                   "docs/CERTIFICATES.md's example certificate is the "
                   "`example` case's, byte for byte")
    ex2 = [c for c in corpus.cases if c.name == "markstep-fp64"]
    if check_that(len(ex2) == 1, "the corpus has the case `markstep-fp64`"):
        check_that(rp(ex2[0].certificate[0]).read_bytes() == page_example2(),
                   "docs/CERTIFICATES.md's version-2 example certificate is "
                   "the `markstep-fp64` case's, byte for byte")
    return finish(t_all)


def finish(t_all):
    print(f"corpus check: {CHECKS} checks, {len(FAILED)} failed, "
          f"{len(SKIPS)} skipped, {time.perf_counter() - t_all:.0f} s",
          flush=True)
    if FAILED:
        for w in FAILED:
            print(f"  FAILED: {w}")
        return 1
    print("CORPUS CHECK OK" if not SKIPS else
          "CORPUS CHECK OK, with the skips above named")
    return 0


def main():
    global TOOL
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=("check", "make"))
    ap.add_argument("--tool", help="the cft-segrun binary (check: without "
                    "it, the tool's remakes are named SKIP)")
    ap.add_argument("--seed", help="check: the sampled audits' seed, 64 hex "
                    "digits (default: drawn from the operating system and "
                    "printed)")
    ap.add_argument("--keep", help="check: keep the tool's outputs here")
    ap.add_argument("--force-dirty", action="store_true",
                    help="make: allow a tool whose build is not clean (a "
                    "trial, never committed)")
    ap.add_argument("--rewrite-all", action="store_true",
                    help="make: write every certificate the tool makes, "
                    "where by default a committed one that the new one "
                    "equals but for build-id and the hash line is kept")
    ap.add_argument("--keep-version-1", action="store_true",
                    help="make: keep every version-1 case as committed, its "
                    "files untouched, needing no tool, and write version 2's "
                    "again")
    args = ap.parse_args()
    if args.tool:
        TOOL = Path(args.tool).resolve()
        if not TOOL.is_file():
            sys.exit(f"corpus: {TOOL} is not built (make -C host cft-segrun)")
    if args.what == "make":
        if TOOL is None and not args.keep_version_1:
            sys.exit("corpus make: --tool is required (or --keep-version-1)")
        return make(args.force_dirty, args.rewrite_all, args.keep_version_1)
    seed = bytes.fromhex(args.seed) if args.seed else os.urandom(32)
    if len(seed) != 32:
        sys.exit("corpus: --seed is 64 hex digits")
    return check(seed, args.keep)


if __name__ == "__main__":
    sys.exit(main())
