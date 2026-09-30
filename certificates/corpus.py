# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The golden certificates: a committed corpus of programs and their
certificates. The certificate plan's step 7 (docs/ROADMAP.md);
docs/CERTIFICATES.md, "Golden certificates", is its manual.

    python certificates/corpus.py check --tool host/cft-segrun[.exe]
                                        [--seed HEX] [--keep DIR]
    python certificates/corpus.py make  --tool host/cft-segrun[.exe]

`make -C host corpustest` runs `check` with the tree's cft-segrun.

WHY IT EXISTS. host/tests/segrun_check.py holds cft-segrun and the golden
writer to EACH OTHER, from states made fresh, so a change that moves both
at once passes it: a change to the model, to a hash or to an encoding. A
committed certificate does not move. So every such change either keeps
the corpus's bytes or changes them in a commit that says so, by running
`make` and committing what it writes.

WHAT `check` HOLDS, for every case certificates/MANIFEST lists:
  1. every file the manifest names against its SHA-256, and no file under
     certificates/ that it does not name, so an edited or added file
     fails by its name;
  2. every committed image against its source assembled again, byte for
     byte, and a library image against programs/MANIFEST's digest too;
  3. the golden writer - cert.run_chain and certify_run at the case's
     depth, each accuracy entry's value derived again (derive,
     make_value) under the definition the committed certificate states,
     and encode, handed the committed certificate's identity lines -
     writes the committed bytes, byte for byte;
  4. every boundary of the golden chain is the committed state file;
  5. cft-segrun, on the software backend at the case's depth, writes the
     committed certificate NORMALIZED in two places and in nothing else:
     its build-id line is the one the binary's own --build-id prints,
     and its hash line is computed again over that body; an accuracy
     case has its accuracy block replaced by `accuracy 0`, the block the
     tool writes before the plan's step 5. Every other line is a function
     of what the manifest fixes - the image, bank, initial state,
     segments, steps, parameters, mode and salt, depth - and of the
     backend, which the gate fixes to software. build-id names the
     library build, which changes with every commit by design, and the
     hash line covers it. Its boundary files are the committed ones;
  6. the golden audit gives each case its expected verdict, in full from
     the initial states alone, and sampled from the committed states
     directory (the seed printed; --seed draws the same sample again);
  7. the case named `example` is docs/CERTIFICATES.md's example
     certificate, byte for byte.

`make` writes the corpus again from the recipes below: every image, bank,
state and certificate, and the manifest. A certificate is the one
cft-segrun writes, with the golden writer's accuracy block where the case
has one; `example` is the golden writer's, as the page prints it. It
refuses to run unless the tool's build id is clean, so that each
certificate names a commit anyone can check out.

The manifest's grammar is read strictly by read_manifest(), which another
gate may import (P1's cft-audit gate does): printable ASCII and LF, one
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

from cft_golden import FORMATS, asm, cert, chars  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

MAGIC = "cft-golden-corpus 1"
LADDER = ("fp32", "fp64", "fp128", "fp256")
DEPTH_PARAM = "scratch-depth"
DEPTH_MAX = 1 << 15
TOOL_TIMEOUT = 120
# the files under certificates/ that are the corpus's machinery, not data
MACHINERY = ("MANIFEST", "corpus.py")

_HEX64 = re.compile(r"[0-9a-f]{64}")
_DEC = re.compile(r"0|[1-9][0-9]{0,18}")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_PATH = re.compile(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*")


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
    how: str                # library or source
    name: str               # a programs/MANIFEST name, or a source's path
    fmt: str = None         # source: the format its .format line is set to


@dataclasses.dataclass
class Run:
    index: int
    kind: str               # main, half-step or wider
    h_slots: tuple
    image: str              # the path of one of Corpus.images
    bank: tuple             # (path, sha), or None for `bank none`
    segments: int
    steps: int
    parameters: tuple       # ((name, value), ...), names in byte order
    boundaries: list        # the SHA-256 of boundary 0..S's file

    def state_path(self, case, b):
        return f"{case.states}/run-{self.index}-boundary-{b}.bin"

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
    accuracy_by: str        # none, or golden: only the golden writer, before step 5
    verdict: str            # accepted, or the name of a refusal
    states: str             # the directory of every boundary's file
    runs: list
    line: int = 0

    def files(self):
        """(path, sha) of every file of this case's own."""
        out = [self.certificate]
        if self.salt:
            out.append(self.salt)
        for r in self.runs:
            if r.bank:
                out.append(r.bank)
            out += [(r.state_path(self, b), h)
                    for b, h in enumerate(r.boundaries)]
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
        n, tok = L.take("image", (5, 6, 7))
        p, h, how = _path(n, tok[1]), _sha(n, tok[2]), tok[3]
        if how == "library" and len(tok) == 5:
            images[p] = Image(p, h, how, tok[4])
        elif how == "source" and len(tok) in (5, 7):
            fmt = None
            if len(tok) == 7:
                if tok[5] != "format" or tok[6] not in LADDER:
                    raise ManifestError(n, "a source image's last two tokens "
                                           "are `format <fp32|fp64|fp128|"
                                           "fp256>`")
                fmt = tok[6]
            images[p] = Image(p, h, how, _path(n, tok[4]), fmt)
        else:
            raise ManifestError(n, "an image is `library <name>` or `source "
                                   "<path> [format <fmt>]`")
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
        n, tok = L.take("accuracy", 3)
        acc = _dec(n, tok[1], "accuracy")
        if tok[2] not in ("none", "golden") or (acc == 0) != (tok[2] == "none"):
            raise ManifestError(n, "accuracy is `0 none` or `<A> golden` with "
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
            elif kind not in ("main", "wider") or len(tok) != 3:
                raise ManifestError(n, "a run is main, half-step or wider")
            if (kind == "main") != (i == 0):
                raise ManifestError(n, "run 0, and only run 0, is main")
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
            runs.append(Run(i, kind, h_slots, img, bank, S, K, tuple(params),
                            bounds))
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
                          acc_by, verdict, states, runs, n0))
    if not cases:
        raise ManifestError(L.last, "no case")
    return Corpus(sources, images, cases)


def write_manifest(corpus):
    """The manifest's text, from a Corpus: the inverse of read_manifest."""
    out = [
        "# certificates/MANIFEST - the golden certificates: every case, and",
        "# every file's SHA-256 (docs/CERTIFICATES.md, \"Golden "
        "certificates\").",
        "#",
        "# Written by `python certificates/corpus.py make`; held by its",
        "# `check` (make -C host corpustest). Paths are from the repository's",
        "# root. An implementation that uses the corpus as a conformance",
        "# test makes each case's runs from the images, banks and initial",
        "# states named here, at the case's depth, and must reproduce every",
        "# run block and accuracy value of the certificate. The identity",
        "# lines name the implementation that made it.",
        "#",
        "# The one salt here, certificates/example.salt, is the bytes 00 01",
        "# .. 1f: docs/CERTIFICATES.md prints it, so it is a TEST salt only,",
        "# and never an owner's.",
        MAGIC,
        ""]
    for p, h in sorted(corpus.sources.items()):
        out.append(f"source {p} {h}")
    for p, im in sorted(corpus.images.items()):
        how = f"library {im.name}" if im.how == "library" else \
            f"source {im.name}" + (f" format {im.fmt}" if im.fmt else "")
        out.append(f"image {p} {im.sha} {how}")
    for c in corpus.cases:
        out += ["", f"case {c.name}", f"what {c.what}",
                f"certificate {c.certificate[0]} {c.certificate[1]}",
                f"mode {c.mode}"]
        if c.salt:
            out.append(f"salt {c.salt[0]} {c.salt[1]}")
        out += [f"depth {c.depth}", f"backends {c.backends}",
                f"accuracy {c.accuracy} {c.accuracy_by}",
                "verdict accepted" if c.verdict == "accepted" else
                f"verdict refused {c.verdict}",
                f"states {c.states}", f"runs {len(c.runs)}"]
        for r in c.runs:
            head = f"run {r.index} {r.kind}"
            if r.kind == "half-step":
                head += f" h-slots {len(r.h_slots)} " + \
                        " ".join(str(s) for s in r.h_slots)
            out += [head, f"image {r.image}",
                    f"bank {r.bank[0]} {r.bank[1]}" if r.bank else "bank none",
                    f"segments {r.segments}", f"steps {r.steps}",
                    f"parameters {len(r.parameters)}"]
            out += [f"parameter {n} {v}" for n, v in r.parameters]
            out += [f"boundary {b} {h}" for b, h in enumerate(r.boundaries)]
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
    `.format` line set to the named rung when one is named."""
    if im.how == "library":
        stem = im.name[:-len(".cftp")] if im.name.endswith(".cftp") \
            else im.name
        src = (ROOT / "programs" / f"{stem}.cfta").read_text(encoding="utf-8")
        return asm.assemble(src, stem)
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
    """Every case of the corpus, as `make` writes it (the lead's decision,
    2026-09-29: eleven cases and the twelfth, half-init)."""
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
    C.append(CaseRecipe(
        "augsum-fp64",
        "augsum, the corpus's own: revision 8's augadd and augerr in a "
        "compensated sum, and a stepped STX and LDX; 2 lanes, 3 segments; "
        "the software backend only",
        [RunRecipe("main", au, b"", None, cert.state_bytes(
            "fp64", [dec("fp64", t) for t in
                     ("1", "0", "0.1", "0", "1e16", "0", "1", "0")]), 3, 4)],
        backends="software"))
    dw = _src_image("deepwrap-fp64", "certificates/programs/deepwrap-fp64.cfta")
    dwi = cert.state_bytes("fp64", [dec("fp64", t) for t in
                                    ("1", "0.25", "3", "2", "0.5", "7")])
    for depth in (256, 2048):
        C.append(CaseRecipe(
            f"deepwrap-fp64-{depth}",
            f"deepwrap, the corpus's own, at {depth:,} scratch slots: a "
            f"non-strict ldx at index 256 and stx at 258, which "
            + ("wrap into the carried block" if depth == 256 else
               "do not wrap") + "; 2 lanes, 3 segments",
            [RunRecipe("main", dw, b"", None, dwi, 3, 1,
                       params=((DEPTH_PARAM, depth),))],
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


def tool_args(case, runs_io, out, sdir):
    """cft-segrun's command line for `case`: runs_io is each run's
    (image path, bank path or None, init path)."""
    a = ["--out", out, "--states", sdir]
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
    return a


def normalized(data, build_id, strip_accuracy):
    """The committed certificate as cft-segrun must write it: its build-id
    line the tool's, its accuracy block `accuracy 0` where the tool writes
    none yet (before step 5), and the hash line computed again."""
    lines = cert.body_of(data).decode("ascii").split("\n")[:-1]
    lines = [f"build-id {build_id}" if ln.startswith("build-id ") else ln
             for ln in lines]
    if strip_accuracy:
        k = next(i for i, ln in enumerate(lines) if ln.startswith("accuracy "))
        lines = lines[:k] + ["accuracy 0", "end"]
    return cert.rehash("\n".join(lines) + "\n")


# ---- the golden writer ------------------------------------------------------

def golden_runs(case, images, salt):
    """Every run of `case` by the golden writer at the case's depth, from
    its committed inputs -> (runs, chains, progs, shapes)."""
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
                                     scratch_depth=case.depth))
        chains.append((st, rs))
        progs[r.index] = (img, bank or None)
        shapes.append((prog.fmt, prog.n_scratch_in))
    return runs, chains, progs, shapes


def golden_entries(entries, runs, shapes, chains):
    """Each entry's value derived again from the golden chains, under the
    definition the entry states (method, kind, uses, scope, quantity,
    form): what an implementation must reproduce is the value."""
    ends = {}
    for r, (st, _) in enumerate(chains):
        ends[(r, 0)] = st[0]
        ends[(r, len(st) - 1)] = st[-1]
    out = []
    for e in entries:
        q = cert.derive(e, runs, shapes, ends)
        v = e.value
        out.append(dataclasses.replace(
            e, value=cert.make_value(q, v.form, v.fmt, v.rnd)))
    return tuple(out)


def entries_from(recipe_entries):
    """The Entry objects a recipe names, their values placeholders."""
    return tuple(cert.Entry(e.method, cert.METHOD_KIND[e.method], e.uses,
                            e.lane, cert.Value(e.form, exact=Fraction(0),
                                               fmt=e.fmt, rnd=e.rnd),
                            e.label, e.terms) for e in recipe_entries)


def page_example():
    text = DOC.read_text(encoding="utf-8")
    at = text.index("<!-- the example certificate -->")
    m = re.search(r"```[a-z]*\n(.*?)```", text[at:], re.S)
    return m.group(1).encode("ascii")


# ---- make -----------------------------------------------------------------

def tool_build_id():
    rc, out, err = run_tool(["--build-id"])
    if rc != 0:
        sys.exit(f"corpus: {TOOL} --build-id failed: {err.strip()}")
    return out.strip()


def make(force_dirty=False):
    bid = tool_build_id()
    print(f"corpus make: {TOOL}\n  build-id {bid}", flush=True)
    if not force_dirty and not bid.endswith("tracked=clean untracked=none"):
        sys.exit("corpus make: the tool's build is not clean, so its "
                 "certificates would name no commit anyone can check out; "
                 "build it in a clean worktree (or --force-dirty for a "
                 "trial that will not be committed)")
    C = recipes()
    # the data this script writes, and nothing else, is cleared first
    for d in ["images"] + [c.name for c in C]:
        shutil.rmtree(HERE / d, ignore_errors=True)
    for stale in HERE.iterdir():
        if stale.is_dir() and stale.name not in ("programs", "__pycache__"):
            shutil.rmtree(stale)
    (HERE / "images").mkdir()
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
    salt = bytes(range(32))
    rp(salt_path).write_bytes(salt)
    work = Path(tempfile.mkdtemp(prefix="corpus-make-"))
    cases = []
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
                        "golden" if c.entries else "none", c.verdict,
                        f"certificates/{c.name}/states", runs)
            out = work / f"{c.name}.cert"
            rc, _, se = run_tool(tool_args(case, io, out, rp(case.states)))
            if rc != 0:
                sys.exit(f"corpus make: {c.name}: cft-segrun refused it: "
                         f"{se.strip()}")
            data = out.read_bytes()
            parsed = cert.parse(data, salt=salt if c.mode == "keyed" else None)
            if c.entries or c.name == "example":
                imgs = {p: rp(p).read_bytes() for p in images}
                g_runs, chains, _, shapes = golden_runs(
                    case, imgs, salt if c.mode == "keyed" else None)
                ents = golden_entries(entries_from(c.entries), g_runs,
                                      shapes, chains)
                idn = PAGE_IDENTITY if c.name == "example" else \
                    parsed.identity
                data = cert.encode(cert.Certificate(
                    parsed.mode, parsed.salt_commitment, idn, parsed.runs,
                    ents))
            if c.name == "example" and data != page_example():
                sys.exit("corpus make: the example case is not "
                         "docs/CERTIFICATES.md's example certificate")
            rp(case.certificate[0]).write_bytes(data)
            case.certificate = (case.certificate[0], sha256(data))
            for r in case.runs:
                r.boundaries = [sha256(rp(r.state_path(case, b)).read_bytes())
                                for b in range(r.segments + 1)]
            cases.append(case)
            print(f"  {c.name}: {len(data):,} bytes, "
                  f"{time.perf_counter() - t0:.1f} s", flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    MANIFEST.write_bytes(write_manifest(Corpus(sources, images, cases))
                         .encode("ascii"))
    total = sum(p.stat().st_size for p in HERE.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts)
    print(f"corpus make: {len(cases)} cases, {total:,} bytes under "
          f"certificates/ (this script and the sources included)")
    return 0


# ---- check ----------------------------------------------------------------

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
    """2. Each committed image, against its source assembled again."""
    print("== 2. every image, against its source assembled again", flush=True)
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
               im.name + (f" at {im.fmt}" if im.fmt else ""))
        check_that(made == data, f"{p} is {how} assembled, byte for byte")
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
        rc, _, se = run_tool(tool_args(case, io, out, sdir))
        if check_that(rc == 0, f"{case.name}: cft-segrun makes it on the "
                      f"software backend ({time.perf_counter() - t1:.1f} s)",
                      f"rc {rc}: {se.strip()[-300:]}"):
            mine = out.read_bytes()
            got = cert.parse(mine).identity.build_id
            check_that(got == build_id, f"{case.name}: its build-id line is "
                       f"what the binary's --build-id prints",
                       f"{got!r} against {build_id!r}")
            want = normalized(data, build_id, case.accuracy > 0)
            what = ("the committed bytes but for build-id, the accuracy block "
                    "(accuracy 0, before step 5) and the hash line" if
                    case.accuracy else "the committed bytes but for build-id "
                    "and the hash line")
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
    try:
        for case in corpus.cases:
            hold_case(case, images, build_id, seed, work)
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    print("== 7. the page's example certificate", flush=True)
    ex = [c for c in corpus.cases if c.name == "example"]
    if check_that(len(ex) == 1, "the corpus has the case `example`"):
        check_that(rp(ex[0].certificate[0]).read_bytes() == page_example(),
                   "docs/CERTIFICATES.md's example certificate is the "
                   "`example` case's, byte for byte")
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
    args = ap.parse_args()
    if args.tool:
        TOOL = Path(args.tool).resolve()
        if not TOOL.is_file():
            sys.exit(f"corpus: {TOOL} is not built (make -C host cft-segrun)")
    if args.what == "make":
        if TOOL is None:
            sys.exit("corpus make: --tool is required")
        return make(args.force_dirty)
    seed = bytes.fromhex(args.seed) if args.seed else os.urandom(32)
    if len(seed) != 32:
        sys.exit("corpus: --seed is 64 hex digits")
    return check(seed, args.keep)


if __name__ == "__main__":
    sys.exit(main())
