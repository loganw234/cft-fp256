# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Figures of the whole project, made by script from the project's own data.

python/readme_charts.py draws the two charts the README shows, about one
question (when does the card pay). This draws the rest: the project's history,
its verification, its hardware, its performance, its math, and the card's
long stress run - one figure at a time, each saying something a reader of the
project would ask, each read off the record and not drawn for it.

    python python/project_figures.py --write    # remake every figure, sidecar and the gallery
    python python/project_figures.py --check    # remake them in memory; fail by name on any difference
    python python/project_figures.py --list     # each figure, the data it reads, where it is filed
    python python/project_figures.py --only perf-speedup --write

WHAT A FIGURE IS HERE. A pair of SVGs, light and dark (docs/img/figures/NAME-
{light,dark}.svg, for a <picture>); a sidecar (NAME.json) holding every number
drawn, the SHA-256 of every file it was read from, the extracts it read and the
commit those were read at, and the cross-checks it ran; and a place in the
gallery, docs/FIGURES.md, which is WRITTEN BY THIS SCRIPT from the same data, so
that a number in a caption is the number in the figure.

WHAT --check DOES, AND WHAT IT NEVER TOUCHES. It reads no git history, no
network, no card and no other machine: CI's checkout is shallow, and a figure
that needed any of those would pass or fail by where it was run. History comes
through the committed extracts (python/figure_extracts.py: each records the
commit it was read at and the command that remakes it); everything else is a
file in the tree. It regenerates every figure in memory and compares, byte for
byte, with the committed files, and fails by name on:
  - an SVG, a sidecar or the gallery that differs from a fresh generation;
  - an output that is missing, or one in docs/img/figures/ that no figure makes;
  - an extract whose data no longer matches its own recorded digest, or whose
    recorded source digest no longer matches the source, where the source is
    present, or that no figure reads;
  - a number the record states that a figure disagrees with, or a statement that
    has quietly stopped being there - see CLAIMS below;
  - a personal path in anything it writes.
Then it plants each of those faults in a scratch copy and requires the check to
name it: a check that cannot fail is a defect (HonestFramework, METHOD 3), so
every run watches its own check fail first. One more control goes the other way:
a file that a figure reads only in part (verify/run.sh, which changes with most
rounds: the figure reads its stage names and its two budget lists) is held by
what was read, not by the file's bytes, so an edit elsewhere in it must move
nothing - a check that failed for that would fail for nothing, every round.

CLAIMS. Where the record states a figure's number in words - the README's "4.5x
and 5.5x", docs/DETERMINISM.md's table of formats - the figure's number is held
to it, at the precision the record gives. Agreement is recorded in the sidecar.
A disagreement fails the check unless it is in KNOWN with its reason, in which
case it is carried to the sidecar and the gallery, said, and not hidden.

Standard library only (plus the sibling modules), so it runs wherever CI's host
job does: Python 3.10 to 3.13, Linux, macOS and Windows.
"""
import argparse
import csv
import importlib.util
import json
import math
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import figure_extracts as X                                      # noqa: E402
import figure_kit as K                                           # noqa: E402
import readme_charts as rc                                       # noqa: E402

FIG_DIR = "docs/img/figures"
GALLERY = "docs/FIGURES.md"
FORMATS = ["fp32", "fp64", "fp128", "fp256"]
FORMAT_LABEL = rc.FORMAT_LABEL
SELF = "python/project_figures.py"

NUMWORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10}

# A disagreement between a figure and the record that is known, reported and
# not fixed here: "figure/claim-id" -> the reason, in words. Empty is the good state.
KNOWN = {}


# ------------------------------------------------------------------- sources
class Src:
    """Every file a figure reads goes through here, so that what its sidecar says it read is what
    it read, and so that the scratch copy the controls mutate is made of exactly those files."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.files = {}          # rel -> {"sha256", "bytes"}: read, digested, named in the sidecar
        self.docs = set()        # rel: read only to check a claim; named in no sidecar (see doc())
        self.extracts = {}       # name -> envelope

    def _read(self, rel):
        p = self.root / rel
        if not p.is_file():
            raise X.ExtractError("%s is not in the tree" % rel)
        return p.read_bytes()

    def bytes(self, rel):
        b = self._read(rel)
        self.files[rel] = {"sha256": X.sha256_bytes(b), "bytes": len(b)}
        return b

    def text(self, rel):
        return self.bytes(rel).decode("utf-8")

    def path(self, rel):
        """The absolute path of a file, for a reader that wants a path; it is digested."""
        self.bytes(rel)
        return str(self.root / rel)

    def csv_rows(self, rel):
        return list(csv.DictReader(self.text(rel).splitlines()))

    def json(self, rel):
        return json.loads(self.text(rel))

    def doc(self, rel):
        """A document read only to check a claim against it. It is NOT digested into the sidecar:
        the README changes with every round, and a sidecar that moved with it would be regenerated
        for nothing. What the claim found there is recorded, and the claim is checked on every run."""
        self.docs.add(rel)
        return self._read(rel).decode("utf-8")

    def module(self, rel, name):
        """A python file of the tree, loaded by path, its digest recorded."""
        path = self.path(rel)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.modules.pop(name, None)
        return mod

    def extract(self, name):
        ex = X.load(self.root, name)
        self.extracts[name] = ex
        p = X.extract_path(self.root, name)
        self.files[X.EXTRACT_DIR + "/" + name + ".json"] = {"sha256": X.sha256_file(p), "bytes": p.stat().st_size}
        return ex["data"]

    def prefix(self, rel, nbytes):
        """The first nbytes of a file that only grows; the digest is of exactly those bytes."""
        b = self._read(rel)
        self.files[rel] = {"sha256": X.sha256_bytes(b[:nbytes]), "bytes": nbytes}
        return b[:nbytes]

    def derived(self, rel, reads, fn):
        """A figure that reads only part of a file that changes with most rounds reads it through here.
        `fn(text)` returns the JSON-able value the figure uses, and the sidecar records the digest of THAT
        value, with what was read, in place of the file's own digest: an edit elsewhere in the file (a
        stage's description, a comment) does not move the figure, and a change in what was read does.
        verify/run.sh is the case: its digest would have failed this check for nothing on each of them."""
        value = fn(self._read(rel).decode("utf-8"))
        blob = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
        self.files[rel] = {"sha256": X.sha256_bytes(blob), "bytes": len(blob), "reads": reads}
        return value

    def sources(self):
        """The tree files read, as a sidecar lists them: not the extracts' own files, which it
        lists with what they were read from."""
        skip = {X.EXTRACT_DIR + "/" + n + ".json" for n in self.extracts}
        return [dict(path=p, **self.files[p]) for p in sorted(self.files) if p not in skip]

    def extract_records(self):
        out = []
        for name in sorted(self.extracts):
            ex = self.extracts[name]
            rel = X.EXTRACT_DIR + "/" + name + ".json"
            out.append({"name": name, "path": rel, "sha256": self.files[rel]["sha256"], "read_at": ex["read_at"],
                        "label": ex["read_at_label"], "what": ex["what"], "body_sha256": ex["body_sha256"],
                        "remake": ex["remake"], "sources": ex["sources"]})
        return out

    def needed(self):
        """Every tree file this figure's build read, for the scratch copy."""
        return sorted(set(self.files) | self.docs)


class Claims:
    """The numbers the record states that a figure is held to."""

    def __init__(self, src, fig):
        self.src, self.fig, self.rows = src, fig, []

    def add(self, cid, claim, doc, drawn, stated, ok, note=None):
        row = {"id": cid, "claim": claim, "document": doc, "drawn": drawn, "stated": stated,
               "verdict": "not found" if stated is None else ("agrees" if ok else "disagrees")}
        if note:
            row["note"] = note
        if row["verdict"] == "disagrees" and ("%s/%s" % (self.fig, cid)) in KNOWN:
            row["verdict"] = "disagrees (reported)"
            row["reported"] = KNOWN["%s/%s" % (self.fig, cid)]
        self.rows.append(row)
        return row

    def check(self, cid, claim, doc, pattern, drawn, fmt="%.1f", group=1, within=None, note=None):
        """`pattern` finds the stated number in `doc`; `drawn` is the figure's value. They agree if
        the drawn value printed with `fmt` is the stated text - the record's own precision - or,
        only where `within` is given, for a record that quotes a different run of the same thing,
        if they are that close (relative)."""
        m = re.search(pattern, self.src.doc(doc))
        if not m:
            return self.add(cid, claim, doc, fmt % drawn, None, False, note)
        stated = m.group(group)
        if within is None:
            ok = (fmt % drawn) == stated.replace(",", "")
        else:
            sv = float(NUMWORDS.get(stated.lower(), stated.replace(",", "")))
            ok = abs(drawn - sv) <= within * abs(sv)
            note = (note or "") + (" (held to %g%%)" % (within * 100))
        return self.add(cid, claim, doc, fmt % drawn, stated, ok, note)


# ------------------------------------------------------------------ registry
class Fig:
    def __init__(self, name, group, title, alt, build):
        self.name, self.group, self.title, self.alt, self.build = name, group, title, alt, build
        self.draw = None
        self.caption = None

    def alt_text(self, data):
        """The picture's description for a reader who cannot see it: a string, or a function of the
        data when it states numbers (so it cannot say what the data no longer does)."""
        return self.alt(data) if callable(self.alt) else self.alt

    def drawer(self, fn):
        self.draw = fn
        return fn

    def captioner(self, fn):
        self.caption = fn
        return fn


FIGS = []
GROUPS = [("history", "History"), ("verification", "Verification"), ("hardware", "Hardware"),
          ("performance", "Performance"), ("math", "The math library"), ("reliability", "Reliability")]


def figure(name, group, title, alt):
    """Register a figure. The function it decorates is build(src, claims) -> data; then
    @fig.drawer gives draw(theme, data, meta) -> svg text and @fig.captioner gives
    caption(data) -> {"shows", "not", "notes"} for the gallery."""
    def deco(build):
        f = Fig(name, group, title, alt, build)
        FIGS.append(f)
        return f
    return deco


# --------------------------------------------------------------- the helpers
def lum(hexcol):
    def ch(v):
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexcol[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def ink_on(hexcol, T):
    """Whichever of the theme's two text colours reads better on this fill."""
    lc = lum(hexcol)
    best, bestc = None, -1.0
    for col in (T["fg"], T["bg"]):
        lt = lum(col)
        c = (max(lt, lc) + 0.05) / (min(lt, lc) + 0.05)
        if c > bestc:
            best, bestc = col, c
    return best


def r4(v):
    """A float as it goes into a sidecar: six significant digits, the same on every platform."""
    return float("%.6g" % v)


def source_line(meta, collapse=3):
    """The footer's text: where the numbers came from. Many files of one directory fold into one
    mention; the sidecar has them all."""
    files = meta["files"]
    by_dir = {}
    for f in files:
        d, _, base = f["path"].rpartition("/")
        by_dir.setdefault(d, []).append(f)
    bits = []
    for d in sorted(by_dir):
        fs = by_dir[d]
        if len(fs) > collapse:
            bits.append("%s/ (%d files)" % (d, len(fs)))
        else:
            bits.extend("%s (%s%s)" % (f["path"], f["reads"] + "; " if "reads" in f else "", f["sha256"][:8])
                        for f in fs)
    for e in meta["extracts"]:
        bits.append("%s (extract; %s)" % (e["path"], e["label"]))
    return "source: " + "; ".join(bits)


# ======================================================================
#                              THE FIGURES
# ======================================================================

# ---------------------------------------------------------------- formats
@figure("formats", "hardware", "One 256-bit beat, and the four formats it carries",
        "The four binary formats drawn to scale across one 256-bit beat: one binary256 lane, two "
        "binary128, four binary64 or eight binary32.")
def build_formats(src, claims):
    fm = src.module("python/cft_golden/formats.py", "fg_formats")
    rows = []
    for name in ("fp256", "fp128", "fp64", "fp32"):
        f = fm.FORMATS[name]
        rows.append({"format": name, "width": f.width, "exp": f.exp_w, "man": f.man_w, "p": f.prec,
                     "emax": f.emax, "bias": f.bias, "lanes": 256 // f.width,
                     "digits": r4(f.prec * 0.3010299956639812)})
    # held to docs/DETERMINISM.md's table (w, t, p, emax, bias), and to the README's "Fifteen ... 8x fp32,
    # 4x fp64, 2x fp128, 1x fp256"
    det = src.doc("docs/DETERMINISM.md")
    for r in rows:
        m = re.search(r"(?m)^\| %-5s \| (\d+)\s*\| (\d+)\s*\| (\d+)\s*\| (\d+)\s*\| (\d+)\s*\|" % r["format"], det)
        for label, idx, val in (("exponent bits", 1, r["exp"]), ("trailing significand bits", 2, r["man"]),
                                ("precision p", 3, r["p"]), ("emax", 4, r["emax"]), ("bias", 5, r["bias"])):
            claims.add("%s-%s" % (r["format"], label.split()[0]), "%s, %s" % (FORMAT_LABEL[r["format"]], label),
                       "docs/DETERMINISM.md", str(val), m.group(idx) if m else None,
                       bool(m) and int(m.group(idx)) == val)
    total = sum(r["lanes"] for r in rows)
    m = re.search(r"Fifteen 16-stage pipelined fused-multiply-add cores in four banks - 8x fp32, 4x fp64, "
                  r"2x fp128, 1x fp256", src.doc("README.md"))
    claims.add("fifteen-cores", "FMA cores in four banks, 8 + 4 + 2 + 1", "README.md",
               "%d (8x fp32, 4x fp64, 2x fp128, 1x fp256)" % total, "Fifteen, 8x fp32, 4x fp64, 2x fp128, 1x fp256"
               if m else None, total == 15)
    return {"rows": rows, "beat": 256}


@build_formats.drawer
def draw_formats(theme, d, meta):
    W, H = 900, 470
    p = K.Plot(theme, W, H, meta["title"],
               "The tile moves one 256-bit beat at a time. Each row is that beat cut into the lanes of one format, "
               "every field to scale: sign, exponent, trailing significand. The widths are the golden model's own.",
               meta["alt"])
    T = p.T
    x0, x1 = 150.0, 705.0
    sx = K.Lin(0, 256, x0, x1)
    csign, cexp, cman = T["cats"][4], T["cats"][1], T["cats"][0]
    top0 = 122.0
    for i, r in enumerate(d["rows"]):
        top = top0 + i * 72
        p.text(24, top + 14, FORMAT_LABEL[r["format"]], size=13, weight="600")
        p.text(24, top + 29, "%d bits a lane" % r["width"], size=10.5, fill=T["muted"])
        for k in range(r["lanes"]):
            b0 = k * r["width"]
            for bits, col, lab in ((1, csign, ""), (r["exp"], cexp, str(r["exp"])), (r["man"], cman, str(r["man"]))):
                xa, xb = sx(b0), sx(b0 + bits)
                p.rect(xa, top, xb - xa, 34, col)
                if k == 0 and lab:
                    p.text((xa + xb) / 2, top - 5, lab, size=10, fill=T["muted"], anchor="middle", mono=True)
                b0 += bits
            if k:
                p.rect(sx(k * r["width"]) - 1, top, 2, 34, T["bg"])      # the cut between lanes, in the page colour
        p.text(x1 + 14, top + 13, "%d lane%s a beat" % (r["lanes"], "" if r["lanes"] == 1 else "s"),
               size=12, weight="600")
        p.text(x1 + 14, top + 28, "p = %d, emax %s" % (r["p"], K.with_commas(r["emax"])), size=10.5, fill=T["muted"])
        p.text(x1 + 14, top + 42, "about %.1f decimal digits" % r["digits"], size=10.5, fill=T["muted"])
    ry = top0 + 4 * 72 - 18
    p.line(x0, ry, x1, ry, T["axis"], 1)
    for b in range(0, 257, 32):
        p.line(sx(b), ry, sx(b), ry + 5, T["axis"], 1)
        p.text(sx(b), ry + 17, str(b), size=10, fill=T["muted"], anchor="middle", mono=True)
    p.text((x0 + x1) / 2, ry + 33, "bit position in the beat", size=10.5, fill=T["muted"], anchor="middle")
    p.legend([(csign, "sign"), (cexp, "exponent field"), (cman, "trailing significand")], x0, ry + 56, 600, size=11)
    p.footer([source_line(meta)])
    return p.render()


@build_formats.captioner
def caption_formats(d):
    return {"shows": "The four interchange formats the tile computes, drawn to scale across the 256-bit beat it "
                     "moves at a time: one binary256 lane, two binary128, four binary64 or eight binary32, so "
                     "fifteen FMA cores in four banks. Field widths, precision and the largest exponent are the "
                     "golden model's.",
            "not": "How the lanes are built (the banks are separate pipes, not one lane split four ways) or what "
                   "they cost; hw-area has the areas."}


# ----------------------------------------------------------- perf-speedup
def _speedup_cells(src):
    """Every (op, arch, tiles, format) cell: resident tiles against the fastest real software, each at
    the largest element count both measured and at least 65,536 - the README chart's own rule."""
    sweep = rc.load_sweep(src.path("docs/bench/sweep-x86_64.csv"))
    peers = {"x86-64": rc.load_peers(src.path("docs/bench/peers-x86_64.csv")),
             "arm64": rc.load_peers(src.path("docs/bench/peers-arm64.csv"))}
    cells = []
    for op in ("mul", "fma", "add"):
        for tiles in ("1", "4"):
            for arch in ("x86-64", "arm64"):
                for fmt in FORMATS:
                    sw, who = rc.best_software(peers[arch], fmt, op)
                    dev = sweep.get(("device", "resident", tiles, fmt, op))
                    if not sw or not dev:
                        continue
                    shared = [n for n in sorted(set(sw) & set(dev)) if n >= 65536]
                    if not shared:
                        continue
                    n = shared[-1]
                    cells.append({"op": op, "tiles": int(tiles), "arch": arch, "format": fmt,
                                  "ratio": r4(sw[n] / dev[n]), "n": n, "best": who[n]})
    sweep_ops = sorted({k[4] for k in sweep if k[0] == "device"})
    peer_ops = sorted({k[2] for arch in peers for k in peers[arch]})
    return cells, sweep_ops, peer_ops


@figure("perf-speedup", "performance", "Where the card wins, for every operation",
        lambda d: "A grid of speed-ups of the resident tiles over the fastest real software, for multiply, fused "
                  "multiply-add and add, at four formats, on two machines: the tile is ahead in %d of %d cells, "
                  "by up to %.0f times, and behind in %d, by up to %.1f times." % (
                      d["wins"], d["n_cells"], d["best"], d["losses"], 1.0 / d["worst"]))
def build_perf_speedup(src, claims):
    cells, sweep_ops, peer_ops = _speedup_cells(src)

    def get(op, arch, tiles, fmt):
        for c in cells:
            if (c["op"], c["arch"], c["tiles"], c["format"]) == (op, arch, tiles, fmt):
                return c["ratio"]
        raise KeyError((op, arch, tiles, fmt))

    R = "README.md"
    two = r"(\d+\.\d)x"
    claims.check("mul-1t-f128", "multiply, one tile, x86-64: binary128", R,
                 r"\*\*binary128 " + two + r"\*\*, \*\*binary256 \d+\.\dx\*\*", get("mul", "x86-64", 1, "fp128"))
    claims.check("mul-1t-f256", "multiply, one tile, x86-64: binary256", R,
                 r"\*\*binary128 \d+\.\dx\*\*, \*\*binary256 " + two + r"\*\*", get("mul", "x86-64", 1, "fp256"))
    claims.check("mul-4t-f128", "multiply, four tiles, x86-64: binary128", R,
                 r"Four tiles reach " + two + r" and \d+\.\dx", get("mul", "x86-64", 4, "fp128"))
    claims.check("mul-4t-f256", "multiply, four tiles, x86-64: binary256", R,
                 r"Four tiles reach \d+\.\dx and " + two, get("mul", "x86-64", 4, "fp256"))
    behind = (r"(\d+\.\d)x and (\d+\.\d)x\s+behind an x86-64 workstation, and (\d+\.\d)x\s+behind an M2 Pro")
    claims.check("mul-1t-f32-behind", "multiply, one tile, x86-64, binary32: times behind", R, behind,
                 1.0 / get("mul", "x86-64", 1, "fp32"), group=1)
    claims.check("mul-1t-f64-behind", "multiply, one tile, x86-64, binary64: times behind", R, behind,
                 1.0 / get("mul", "x86-64", 1, "fp64"), group=2)
    claims.check("mul-1t-f32-m2", "multiply, one tile, M2 Pro, binary32: times behind", R, behind,
                 1.0 / get("mul", "arm64", 1, "fp32"), group=3)
    fma_b128 = r"binary128 one tile is\s+(\d+\.\d)x and four tiles (\d+\.\d)x"
    claims.check("fma-1t-f128", "fused multiply-add, one tile, x86-64: binary128", R, fma_b128,
                 get("fma", "x86-64", 1, "fp128"), group=1)
    claims.check("fma-4t-f128", "fused multiply-add, four tiles, x86-64: binary128", R, fma_b128,
                 get("fma", "x86-64", 4, "fp128"), group=2)
    ahead = r"one tile is (\d+\.\d\d)x and (\d+\.\d\d)x \*ahead\*"
    claims.check("fma-1t-f32", "fused multiply-add, one tile, x86-64: binary32, ahead by", R, ahead,
                 get("fma", "x86-64", 1, "fp32"), fmt="%.2f", group=1)
    claims.check("fma-1t-f64", "fused multiply-add, one tile, x86-64: binary64, ahead by", R, ahead,
                 get("fma", "x86-64", 1, "fp64"), fmt="%.2f", group=2)
    reaches = r"one tile reaches (\d+\.\d\d)x and (\d+\.\d\d)x of it"
    claims.check("fma-1t-f32-m2", "fused multiply-add, one tile, M2 Pro: binary32 reaches", R, reaches,
                 get("fma", "arm64", 1, "fp32"), fmt="%.2f", group=1)
    claims.check("fma-1t-f64-m2", "fused multiply-add, one tile, M2 Pro: binary64 reaches", R, reaches,
                 get("fma", "arm64", 1, "fp64"), fmt="%.2f", group=2)
    # why fma flatters the tile, as the README gives it: checked to be there, in its words
    text = src.doc(R)
    for cid, claim, pat in (("glibc-fma", "the README's reason fused multiply-add flatters the tile on a CPU",
                             r"glibc's\s+`fma` is a function call"),
                            ("fmaq-soft", "the README's reason binary128 fused multiply-add flatters it", r"`fmaq` is a soft routine")):
        m = re.search(pat, text)
        claims.add(cid, claim, R, "stated in the caption", m.group(0) if m else None, bool(m))
    wins = [c for c in cells if c["ratio"] >= 1]
    return {"cells": cells, "n_cells": len(cells), "wins": len(wins), "losses": len(cells) - len(wins),
            "best": max(c["ratio"] for c in cells), "worst": min(c["ratio"] for c in cells),
            "peer_only_ops": sorted(set(peer_ops) - set(sweep_ops))}


@build_perf_speedup.drawer
def draw_perf_speedup(theme, d, meta):
    W, H = 900, 468
    p = K.Plot(theme, W, H, meta["title"],
               "Resident tiles against the fastest real software on the same machine, each at the largest element "
               "count both sides measured (at least 65,536). Green: the tile is ahead. Red: it is behind. The small "
               "word is who the software was.", meta["alt"])
    T = p.T
    cw, rh = 80.0, 38.0
    lx = 130.0
    blocks = [("x86-64", "an x86-64 workstation", lx), ("arm64", "an M2 Pro laptop", lx + 4 * cw + 38)]
    rows = [(op, t) for op in ("mul", "fma", "add") for t in (1, 4)]
    top = 150.0
    names = {"mul": "multiply", "fma": "fused multiply-add", "add": "add"}
    idx = {(c["op"], c["tiles"], c["arch"], c["format"]): c for c in d["cells"]}
    for arch, label, bx in blocks:
        p.text(bx, top - 38, label, size=12.5, weight="600")
        for j, fmt in enumerate(FORMATS):
            p.text(bx + j * cw + cw / 2, top - 12, FORMAT_LABEL[fmt], size=11, anchor="middle", fill=T["muted"])
        for i, (op, t) in enumerate(rows):
            for j, fmt in enumerate(FORMATS):
                c = idx.get((op, t, arch, fmt))
                if not c:
                    continue
                r = c["ratio"]
                if r >= 1:
                    col = K.mix(T["panel"], T["win"], 0.14 + 0.86 * min(1.0, math.log10(r) / 1.75))
                    txt = ("%.2fx" % r) if r < 10 else ("%.1fx" % r) if r < 100 else "%.0fx" % r
                else:
                    col = K.mix(T["panel"], T["lose"], 0.14 + 0.86 * min(1.0, math.log10(1.0 / r)))
                    txt = ("/%.2f" % (1.0 / r)) if 1.0 / r < 10 else "/%.1f" % (1.0 / r)
                x, y = bx + j * cw, top + i * rh
                p.rect(x + 1, y + 1, cw - 2, rh - 2, col)
                ink = ink_on(col, T)
                p.text(x + cw / 2, y + 17, txt, size=12.5, weight="600", anchor="middle", mono=True, fill=ink)
                p.text(x + cw / 2, y + 31, c["best"], size=9, anchor="middle", fill=ink, opacity=0.9)
    for i, (op, t) in enumerate(rows):
        y = top + i * rh
        if t == 1:
            p.text(24, y + 16, names[op], size=12, weight="600")
            p.text(24, y + 31, "1 tile", size=10.5, fill=T["muted"])
        else:
            p.text(24, y + 16, "4 tiles", size=10.5, fill=T["muted"])
    by = top + len(rows) * rh + 24
    for k, line in enumerate(K.wrap("A loss is written as a divisor: /7.2 means the tile takes 7.2 times as long. "
                                    "Fused multiply-add flatters the tile because glibc's fma is a function call and "
                                    "__float128's is a soft routine; add and multiply are one instruction on a CPU "
                                    "that has the format.", W - 48, 10.5)):
        p.text(24, by + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_perf_speedup.captioner
def caption_perf_speedup(d):
    return {"shows": "The README's multiply chart for every operation the sweep and the peer runs share "
                     "(multiply, fused multiply-add, add): %d cells, the tile ahead in %d and behind in %d. "
                     "The extremes are %.1fx ahead and %.1fx behind." % (
                         d["n_cells"], d["wins"], d["losses"], d["best"], 1.0 / d["worst"]),
            "not": "%s (the peer runs measure them, the device sweep does not), the non-arithmetic operations, or "
                   "anything at a size below 65,536 elements, where a device call is mostly fixed cost; the "
                   "README's cost-by-size chart has that." % " and ".join(d["peer_only_ops"]).capitalize().replace(
                       "Div", "Divide").replace("sqrt", "square root")}


# ------------------------------------------------------------- perf-lanes
def _rates(src):
    """{(backend, path, tiles, format, op): {n: elements per second}} from the committed sweep."""
    out = {}
    for r in src.csv_rows("docs/bench/sweep-x86_64.csv"):
        try:
            n, eps = int(r["n"]), float(r["elems_per_s"])
        except (KeyError, ValueError):
            continue
        out.setdefault((r["backend"], r["path"], r["tiles"], r["format"], r["op"]), {})[n] = eps
    return out


@figure("perf-lanes", "performance", "The tile is beat-limited: throughput follows the lanes in a beat",
        "Elements per second against problem size for the four formats on one resident tile, and the same "
        "rates relative to binary256: they climb towards eight, four and two, the number of lanes in a beat.")
def build_perf_lanes(src, claims):
    rates = _rates(src)
    f256 = rates[("device", "resident", "1", "fp256", "mul")]
    nmax256 = max(f256)
    best256 = f256[nmax256]
    series, ratio, ext, top = {}, {}, {}, {}
    for fmt in FORMATS:
        s = rates[("device", "resident", "1", fmt, "mul")]
        series[fmt] = [[n, r4(s[n] / 1e6)] for n in sorted(s) if n >= 4096]
        nmax = max(s)
        top[fmt] = {"n": nmax, "rate_m": r4(s[nmax] / 1e6)}
        if fmt != "fp256":
            ratio[fmt] = [[n, r4(s[n] / f256[n])] for n in sorted(f256) if n in s and n >= 4096]
            # past binary256's largest measured size there is nothing to divide by at the same size: the ratio is
            # taken against binary256's rate at its own largest, which the figure draws dotted
            ext[fmt] = [[n, r4(s[n] / best256)] for n in sorted(s) if n > nmax256]
    sat = {fmt: ext[fmt][-1][1] for fmt in ("fp32", "fp64", "fp128")}
    at_1m = {fmt: r4(rates[("device", "resident", "1", fmt, "mul")][1048576] / 1e6) for fmt in FORMATS}
    # does the operation matter? the resident rate of add and of fused multiply-add against multiply's, at each
    # format's largest size
    spread = 0.0
    for fmt in FORMATS:
        vals = [rates[("device", "resident", "1", fmt, op)][top[fmt]["n"]] for op in ("mul", "fma", "add")]
        spread = max(spread, (max(vals) - min(vals)) / (sum(vals) / 3.0))
    R = "README.md"
    note = ("the README quotes docs/BENCHMARKS.md's cft-resident run of 2026-09-16; the sweep is a different "
            "run, through cft-bench")
    claims.check("readme-fp32-1m", "binary32, one tile, resident, million elements/s at 1M", R,
                 r"\((\d+) against \d+ million elements a second,\s+resident, one tile", at_1m["fp32"],
                 fmt="%.0f", within=0.05, note=note)
    claims.check("readme-fp256-1m", "binary256, one tile, resident, million elements/s at 1M", R,
                 r"\(\d+ against (\d+) million elements a second,\s+resident, one tile", at_1m["fp256"],
                 fmt="%.0f", within=0.05, note=note)
    settle = r"ratios\s+settle on (\d), (\d) and (\d)\."
    for k, fmt_ in enumerate(("fp32", "fp64", "fp128")):
        claims.check("readme-settle-" + fmt_, "the README's figure caption: the %s ratio settles on" % FORMAT_LABEL[fmt_],
                     R, settle, sat[fmt_], fmt="%.0f", group=k + 1)
    return {"series": series, "top": top, "ratio": ratio, "ratio_ext": ext, "saturated_ratio": sat, "at_1m_m": at_1m,
            "n_min": 4096, "best256_n": nmax256, "op_spread": r4(spread)}


@build_perf_lanes.drawer
def draw_perf_lanes(theme, d, meta):
    W, H = 900, 548
    p = K.Plot(theme, W, H, meta["title"],
               "One resident tile, multiply. Left: elements per second against problem size. Right: the same rates "
               "relative to binary256 at the same size. A beat carries 8, 4, 2 or 1 elements, so the ratios should "
               "settle at 8, 4 and 2 - and they climb to them as the call gets big enough to hide its fixed cost.",
               meta["alt"])
    T = p.T
    cols = {"fp32": T["cats"][4], "fp64": T["cats"][1], "fp128": T["cats"][2], "fp256": T["cats"][0]}
    allx = [n for s in d["series"].values() for n, _ in s]
    ally = [v for s in d["series"].values() for _, v in s]
    # left panel
    lx0, lx1, ly0, ly1 = 84.0, 424.0, 142.0, 400.0
    X1 = rc.Log(min(allx), max(allx), lx0, lx1)
    lo, hi = 10 ** math.floor(math.log10(min(ally))), 10 ** math.ceil(math.log10(max(ally)))
    Y1 = rc.Log(lo, hi, ly1, ly0)
    p.panel(lx0, ly0, lx1, ly1)
    K.axis_y_log(p, Y1, lx0, lx1, lo, hi, lambda v: ("%gG" % (v / 1000.0)) if v >= 1000 else "%gM" % v)
    for g in K.decades(min(allx), max(allx)):
        p.line(X1(g), ly0, X1(g), ly1, T["grid"], 1)
        p.text(X1(g), ly1 + 14, K.human(g), size=10.5, fill=T["muted"], anchor="middle", mono=True)
    for fmt in reversed(FORMATS):
        p.path([(X1(n), Y1(v)) for n, v in d["series"][fmt]], cols[fmt], 2.4)
        n, v = d["series"][fmt][-1]
        p.text(X1(n) - 4, Y1(v) - 7, "%.0fM" % v, size=10, fill=cols[fmt], anchor="end", mono=True)
    p.text((lx0 + lx1) / 2, ly1 + 32, "elements per call", size=10.5, fill=T["muted"], anchor="middle")
    p.text(lx0, ly0 - 10, "million elements per second", size=10.5, fill=T["muted"])
    # right panel
    rx0, rx1, ry0, ry1 = 536.0, 876.0, 142.0, 400.0
    X2 = rc.Log(min(allx), max(allx), rx0, rx1)
    Y2 = K.Lin(0, 9, ry1, ry0)
    p.panel(rx0, ry0, rx1, ry1)
    for v in (0, 2, 4, 6, 8):
        p.line(rx0, Y2(v), rx1, Y2(v), T["grid"], 1)
        p.text(rx0 - 7, Y2(v) + 3.5, "%dx" % v, size=10.5, fill=T["muted"], anchor="end", mono=True)
    for g in K.decades(min(allx), max(allx)):
        p.line(X2(g), ry0, X2(g), ry1, T["grid"], 1)
        p.text(X2(g), ry1 + 14, K.human(g), size=10.5, fill=T["muted"], anchor="middle", mono=True)
    for fmt, target in (("fp32", 8), ("fp64", 4), ("fp128", 2)):
        p.line(rx0, Y2(target), rx1, Y2(target), cols[fmt], 1.2, dash="5 4", opacity=0.9)
        pts = [(X2(n), Y2(v)) for n, v in d["ratio"][fmt]]
        p.path(pts, cols[fmt], 2.4)
        ex = d["ratio_ext"][fmt]
        p.path([pts[-1]] + [(X2(n), Y2(v)) for n, v in ex], cols[fmt], 2.4, dash="2 3")
        n, v = (ex or d["ratio"][fmt])[-1]
        p.circle(X2(n), Y2(v), 3.4, cols[fmt])
        p.text(X2(n) - 6, Y2(v) + (15 if fmt == "fp32" else -8), "%.2fx" % v, size=10, fill=cols[fmt],
               anchor="end", mono=True)
    p.text((rx0 + rx1) / 2, ry1 + 32, "elements per call", size=10.5, fill=T["muted"], anchor="middle")
    p.text(rx0, ry0 - 10, "rate over binary256's (dashed: lanes in a beat)", size=10.5, fill=T["muted"])
    y = p.legend([(cols[f], FORMAT_LABEL[f]) for f in FORMATS], 24, 452, 850, line=True)
    t = d["top"]
    for k, line in enumerate(K.wrap(
            "Solid: the ratio at the same size, up to binary256's largest (%s elements). Dotted: past it, each format's "
            "rate at its own largest size (binary32 %s elements, binary64 %s, binary128 %s) over binary256's rate at "
            "its largest: %.2fx, %.2fx and %.2fx, the lanes in a beat to within %.1f%%."
            % (K.with_commas(d["best256_n"]), K.with_commas(t["fp32"]["n"]), K.with_commas(t["fp64"]["n"]),
               K.with_commas(t["fp128"]["n"]), d["saturated_ratio"]["fp32"], d["saturated_ratio"]["fp64"],
               d["saturated_ratio"]["fp128"],
               100.0 * max(abs(d["saturated_ratio"]["fp32"] / 8.0 - 1), abs(d["saturated_ratio"]["fp64"] / 4.0 - 1),
                           abs(d["saturated_ratio"]["fp128"] / 2.0 - 1))), W - 48, 10.5)):
        p.text(24, y + 10 + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_perf_lanes.captioner
def caption_perf_lanes(d):
    return {"shows": "That the tile's rate is set by the beat. At a million elements one tile moves %.0f, %.0f, %.0f "
                     "and %.0f million binary32, 64, 128 and 256 elements a second, which is %.1fx, %.1fx and %.1fx "
                     "binary256's rate against the 8, 4 and 2 the lane counts say; the ratios settle on those numbers "
                     "at the largest sizes (%.2f, %.2f, %.2f)." % (
                         d["at_1m_m"]["fp32"], d["at_1m_m"]["fp64"], d["at_1m_m"]["fp128"], d["at_1m_m"]["fp256"],
                         d["at_1m_m"]["fp32"] / d["at_1m_m"]["fp256"], d["at_1m_m"]["fp64"] / d["at_1m_m"]["fp256"],
                         d["at_1m_m"]["fp128"] / d["at_1m_m"]["fp256"], d["saturated_ratio"]["fp32"],
                         d["saturated_ratio"]["fp64"], d["saturated_ratio"]["fp128"]),
            "not": "A different operation (add and fused multiply-add are within %.2f%% of multiply's rate at each "
                   "format's largest size), the PCIe path, or four tiles: this is the resident path of one tile. The "
                   "ratios at the top rest on binary256 having been measured only up to %s elements." % (
                       100.0 * d["op_spread"], K.with_commas(d["best256_n"]))}


# ------------------------------------------------------------ history-commits
SHORT_AREA = {"rtl": "RTL and proofs", "golden": "golden model", "host": "host and bindings",
              "programs": "programs, certificates", "hw": "FPGA builds, card", "gates": "gates, plumbing",
              "docs": "documents"}
HEAT_BINS = ((1, "1"), (2, "2-4"), (5, "5-9"), (10, "10-19"), (20, "20+"))


def heat_level(c):
    lvl = -1
    for i, (lo, _lab) in enumerate(HEAT_BINS):
        if c >= lo:
            lvl = i
    return lvl


@figure("history-commits", "history", "What was worked on, day by day",
        lambda d: "Commits per day over %d days, with merges apart, and under them a grid of the repository's %d areas "
                  "showing how many commits touched each one on each day, with the ABI steps and %d milestones marked."
                  % (len(d["days"]), len(d["areas"]), len(d["milestones"])))
def build_history_commits(src, claims):
    h = src.extract("history")
    led = src.extract("ledger")
    compat = src.doc("docs/COMPATIBILITY.md")
    bad = [a["abi"] for a in h["abi"]
           if not re.search(r"(?m)^(?:\*\*|### )ABI %s \(%s" % (re.escape(a["abi"]), a["day"]), compat)]
    claims.add("abi-dates", "each ABI step and the day the record dates it", "docs/COMPATIBILITY.md",
               "%d steps, ABI %s to %s" % (len(h["abi"]), h["abi"][0]["abi"], h["abi"][-1]["abi"]),
               "all found, with the same dates" if not bad else "not found as dated: " + ", ".join(bad), not bad)
    totals = h["totals"]
    ok = sum(h["commits"]) == totals["non_merge"] and sum(h["merges"]) == totals["merges"] \
        and totals["non_merge"] + totals["merges"] == totals["commits"]
    claims.add("commit-counts", "the days' commits add up to the walk's totals", X.EXTRACT_DIR + "/history.json",
               "%d + %d = %d" % (sum(h["commits"]), sum(h["merges"]), sum(h["commits"]) + sum(h["merges"])),
               "%d + %d = %d" % (totals["non_merge"], totals["merges"], totals["commits"]), ok)
    days = h["days"]
    by_day = {}
    for a in h["abi"]:
        by_day.setdefault(a["day"], []).append(a["abi"])
    abi_marks = [[days.index(dy), v[0] if len(v) == 1 else "%s-%s" % (v[0], v[-1])] for dy, v in sorted(by_day.items())]
    mil = sorted(([days.index(m["date"]), m["label"], m["date"]] for m in led["milestones"] if m["date"] in days))
    tot = [c + m for c, m in zip(h["commits"], h["merges"])]
    peak = max(range(len(days)), key=lambda i: (tot[i], -i))
    area_totals = {a["id"]: sum(h["touched"][a["id"]]) for a in h["areas"]}
    # each area's busiest week: the Monday that starts the seven days with most commits touching it
    busiest = {}
    for a in h["areas"]:
        wk = {}
        for i, dy in enumerate(days):
            num = K.day_number(dy)
            monday = num - ((num - 1) % 7)
            wk[monday] = wk.get(monday, 0) + h["touched"][a["id"]][i]
        best = max(sorted(wk), key=lambda m: wk[m])
        busiest[a["id"]] = [K.day_iso(best), wk[best]]
    return {"days": days, "commits": h["commits"], "merges": h["merges"], "areas": [a["id"] for a in h["areas"]],
            "area_names": {a["id"]: a["name"] for a in h["areas"]}, "touched": h["touched"],
            "area_totals": area_totals, "abi": abi_marks, "milestones": mil, "totals": totals,
            "peak": {"day": days[peak], "commits": h["commits"][peak], "merges": h["merges"][peak]},
            "busiest_week": busiest, "author_offsets": h["author_offsets"], "abi_steps": h["abi"],
            "as_of": h["as_of"]}


@build_history_commits.drawer
def draw_history_commits(theme, d, meta):
    W, H = 900, 716
    p = K.Plot(theme, W, H, meta["title"],
               "Every commit to the repository from %s to %s %s, by the day it was written. Above: commits per day, "
               "with the merges that joined parcels to main apart. Below: for each area of the tree, the commits "
               "that touched it that day." % (K.day_short(d["days"][0]), K.day_short(d["days"][-1]),
                                              d["days"][-1][:4]), meta["alt"])
    T = p.T
    days, n = d["days"], len(d["days"])
    x0, x1 = 168.0, 838.0
    cw = (x1 - x0) / n
    d0, d1 = K.day_number(days[0]), K.day_number(days[-1])
    X1 = lambda i: x0 + i * cw                                    # noqa: E731
    # panel A
    ay0, ay1 = 150.0, 276.0
    tot = [c + m for c, m in zip(d["commits"], d["merges"])]
    top = 110.0
    Y = K.Lin(0, top, ay1, ay0)
    p.panel(x0, ay0, x1, ay1)
    for v in (0, 50, 100):
        p.line(x0, Y(v), x1, Y(v), T["grid"], 1)
        p.text(x0 - 7, Y(v) + 3.5, str(v), size=10.5, fill=T["muted"], anchor="end", mono=True)
    p.text(24, ay0 + 13, "commits a day", size=12, weight="600")
    for k, (idx, label, date) in enumerate(d["milestones"], 1):
        xm = X1(idx) + cw / 2
        p.line(xm, ay0 - 6, xm, ay1, T["axis"], 1, dash="2 3")
    for i in range(n):
        c, m = d["commits"][i], d["merges"][i]
        bx = X1(i) + cw * 0.12
        if c:
            p.rect(bx, Y(c), cw * 0.76, Y(0) - Y(c), T["cats"][0])
        if m:
            p.rect(bx, Y(c + m), cw * 0.76, Y(c) - Y(c + m), K.mix(T["cats"][0], T["bg"], 0.6))
    for k, (idx, label, date) in enumerate(d["milestones"], 1):
        xm = X1(idx) + cw / 2
        p.circle(xm, ay0 - 14, 8, T["fg"])
        p.text(xm, ay0 - 10.2, str(k), size=10.5, weight="600", anchor="middle", fill=T["bg"], mono=True)
    pk = d["days"].index(d["peak"]["day"])
    p.text(X1(pk) + cw + 6, Y(tot[pk]) + 4, "%d on %s" % (d["commits"][pk] + d["peak"]["merges"], K.day_short(d["peak"]["day"])),
           size=10.5, fill=T["muted"])
    ly = p.legend([(T["cats"][0], "commits that are not merges"),
                   (K.mix(T["cats"][0], T["bg"], 0.6), "merges (%d)" % d["totals"]["merges"])],
                  x1 - 330, ay0 + 16, 320, size=10.5)
    # ABI steps
    p.text(24, ay1 + 25, "ABI steps", size=11, weight="600")
    for k, (idx, label) in enumerate(d["abi"]):
        xm = X1(idx) + cw / 2
        p.line(xm, ay1 + 2, xm, ay1 + 8, T["axis"], 1)
        p.text(xm, ay1 + 20 + 11 * (k % 3), label, size=9.5, fill=T["muted"], anchor="middle", mono=True)
    # panel B: the heat grid
    by, rh = ay1 + 62, 25.0
    for r, aid in enumerate(d["areas"]):
        y = by + r * rh
        p.text(24, y + 16, SHORT_AREA.get(aid, aid), size=11)
        p.text(x1 + 8, y + 16, K.with_commas(d["area_totals"][aid]), size=10.5, fill=T["muted"], mono=True)
        for i in range(n):
            c = d["touched"][aid][i]
            lvl = heat_level(c)
            col = T["pale"] if lvl < 0 else K.mix(T["panel"], T["cats"][0], (0.2, 0.4, 0.6, 0.8, 1.0)[lvl])
            p.rect(X1(i) + 0.5, y + 1, cw - 1, rh - 3, col)
    gy = by + len(d["areas"]) * rh
    for dd in K.week_ticks(d0, d1):
        xm = x0 + (dd - d0) * cw + cw / 2
        p.line(xm, gy, xm, gy + 4, T["axis"], 1)
        p.text(xm, gy + 16, K.day_short(K.day_iso(dd)), size=10, fill=T["muted"], anchor="middle", mono=True)
    p.text(x1 + 8, by - 6, "commits", size=10, fill=T["muted"])
    leg = [(K.mix(T["panel"], T["cats"][0], (0.2, 0.4, 0.6, 0.8, 1.0)[i]), lab) for i, (_lo, lab) in enumerate(HEAT_BINS)]
    p.text(24, gy + 44, "commits touching the area that day:", size=10.5, fill=T["muted"])
    p.legend(leg, 250, gy + 44, 600, size=10.5)
    yy = gy + 68
    for line in K.wrap("A commit that touches several areas is counted in each, so a column of the grid can add up to more "
                       "than its bar. The merges join parcels' branches to main and carry no files of their own, so "
                       "they are counted apart: %d of the %d commits are merges and %d are the work."
                       % (d["totals"]["merges"], d["totals"]["commits"], d["totals"]["non_merge"]), W - 48, 10.5):
        p.text(24, yy, line, size=10.5, fill=T["muted"])
        yy += 15
    yy += 8
    p.text(24, yy, "Milestones, each the date of the ledger entry that records it:", size=10.5, weight="600")
    yy += 17
    half = (len(d["milestones"]) + 1) // 2
    for k, (idx, label, date) in enumerate(d["milestones"], 1):
        col, row = divmod(k - 1, half)
        xx, y2 = 24 + col * 430, yy + row * 16
        p.circle(xx + 8, y2 - 3.5, 7, T["fg"])
        p.text(xx + 8, y2 - 0.3, str(k), size=9.5, weight="600", anchor="middle", fill=T["bg"], mono=True)
        p.text(xx + 22, y2, "%s  %s" % (K.day_short(date), label), size=10.5)
    p.footer([source_line(meta)])
    return p.render()


@build_history_commits.captioner
def caption_history_commits(d):
    t = d["totals"]
    pk = d["peak"]
    weeks = sorted(d["areas"], key=lambda a: (d["busiest_week"][a][0], a))
    offs = d["author_offsets"]
    tz = ("every commit is dated at UTC%s%s" % (list(offs)[0][0], int(list(offs)[0][1:3]))) if len(offs) == 1 \
        else "the commits carry %d different UTC offsets" % len(offs)
    return {"shows": "%s commits in %d days, %s of them merges; the busiest day was %s, with %d. Each area's busiest "
                     "week, by commits touching it: %s. The ABI steps, %s to %s, are on the days "
                     "docs/COMPATIBILITY.md dates them." % (
                         K.with_commas(t["commits"]), len(d["days"]), K.with_commas(t["merges"]),
                         K.day_short(pk["day"]), pk["commits"] + pk["merges"],
                         "; ".join("%s the week of %s (%d)" % (SHORT_AREA[a], K.day_short(d["busiest_week"][a][0]),
                                                                d["busiest_week"][a][1]) for a in weeks),
                         d["abi_steps"][0]["abi"], d["abi_steps"][-1]["abi"]),
            "not": "How big the commits were, or who wrote what: a commit counts once whatever it changed. A day is the "
                   "author's local day (%s), not UTC's. History is read at %s and ends there; commits made after it "
                   "are in the next remake." % (tz, d["as_of"][:7]),
            "notes": []}


# ------------------------------------------------------------- history-size
AREA_COLOR_ORDER = ("rtl", "golden", "host", "programs", "hw", "gates", "docs", "pack", "vendored")


@figure("history-size", "history", "What the repository is made of, and the record it keeps",
        lambda d: "Text lines in the repository by area at the end of each day, and the validation ledger's size, "
                  "with the lines ever deleted from it: %d of %s, %d of them in the newest entry." % (
                      d["ledger"]["deleted"], K.with_commas(d["ledger"]["added"]),
                      d["ledger"]["edits"]["by_distance"].get("0", 0)))
def build_history_size(src, claims):
    t = src.extract("tree")
    led = src.extract("ledger")
    areas = [a["id"] for a in t["line_areas"]]
    names = {a["id"]: a["name"] for a in t["line_areas"]}
    L = t["ledger"]
    ok = L["lines"][-1] == led["prefix_lines"] and L["entries"][-1] == led["entries"]
    claims.add("ledger-size", "the ledger's lines and entries at the as-of commit (git) and in the pinned prefix of "
               "the file", "docs/VALIDATION.md", "%s lines, %d entries (git)" % (K.with_commas(L["lines"][-1]), L["entries"][-1]),
               "%s lines, %d entries (the file's prefix)" % (K.with_commas(led["prefix_lines"]), led["entries"]), ok)
    for cid, claim, doc, pat in (
            ("pack-delivered", "the hard-workload pack is kept as delivered, by another model", "programs/workloads/README.md",
             r"written by an OpenAI model"),
            ("pack-kept", "... and says so in its title", "programs/workloads/README.md", r"programs written elsewhere, kept as delivered"),
            ("arduino-copy", "the Arduino library holds a vendored copy of host/", "bindings/arduino/sync.py",
             r"Vendor libcft into the Arduino library")):
        m = re.search(pat, src.doc(doc))
        claims.add(cid, claim, doc, "stated in the subtitle", m.group(0) if m else None, bool(m))
    ed = L["edits"]
    ok2 = ed["deleted"] == sum(L["deleted"]) and sum(ed["by_distance"].values()) == ed["deleted"]
    claims.add("ledger-deleted", "the lines deleted, counted by commit and by position", X.EXTRACT_DIR + "/tree.json",
               str(sum(L["deleted"])), str(ed["deleted"]), ok2)
    final = {a: t["lines"][a][-1] for a in areas}
    return {"days": t["days"], "areas": areas, "names": names, "lines": t["lines"], "final": final,
            "total": sum(final.values()), "files": t["files"][-1],
            "ledger": {"lines": L["lines"], "entries": L["entries"], "added": sum(L["added"]),
                       "deleted": sum(L["deleted"]), "edits": ed},
            "as_of": t["as_of"]}


@build_history_size.drawer
def draw_history_size(theme, d, meta):
    W, H = 900, 800
    p = K.Plot(theme, W, H, meta["title"],
               "Top: the text lines of every tracked file, by area, at the end of each day on main's own line. Two "
               "slices are kept apart because neither is the project's own authorship: the hard-workload pack, "
               "written by another model and kept as delivered, and the Arduino library's copy of host/. Bottom: "
               "the ledger, and what was ever taken out of it.", meta["alt"])
    T = p.T
    days, n = d["days"], len(d["days"])
    cols = {a: T["cats"][i] for i, a in enumerate(d["areas"][:7])}
    cols["pack"] = K.mix(T["muted"], T["bg"], 0.35)
    cols["vendored"] = K.mix(T["muted"], T["bg"], 0.65)
    short = dict(SHORT_AREA, pack="delivered pack", vendored="Arduino copy of host/")
    x0, x1 = 90.0, 830.0
    ay0, ay1 = 160.0, 400.0
    d0, d1 = K.day_number(days[0]), K.day_number(days[-1])
    X1 = K.Lin(d0, d1, x0, x1)
    top = 900000.0
    Y = K.Lin(0, top, ay1, ay0)
    p.panel(x0, ay0, x1, ay1)
    for v in (0, 200000, 400000, 600000, 800000):
        p.line(x0, Y(v), x1, Y(v), T["grid"], 1)
        p.text(x0 - 7, Y(v) + 3.5, K.kmg(v), size=10.5, fill=T["muted"], anchor="end", mono=True)
    stack = [0.0] * n
    order = [a for a in AREA_COLOR_ORDER if a in d["areas"]]
    for a in order:
        lo = list(stack)
        for i in range(n):
            stack[i] += d["lines"][a][i]
        pts_top = [(X1(d0 + i), Y(stack[i])) for i in range(n)]
        pts_bot = [(X1(d0 + i), Y(lo[i])) for i in reversed(range(n))]
        p.path(pts_top + pts_bot, "none", fill=cols[a], close=True)
    for dd in K.week_ticks(d0, d1):
        p.text(X1(dd), ay1 + 14, K.day_short(K.day_iso(dd)), size=10, fill=T["muted"], anchor="middle", mono=True)
    p.text(x0, ay0 - 9, "text lines", size=10.5, fill=T["muted"])
    p.text(x1 + 6, Y(stack[-1]) + 4, K.with_commas(stack[-1]), size=10.5, weight="600", mono=True)
    p.legend([(cols[a], short[a]) for a in order], 24, ay1 + 40, W - 48, size=10.5)
    # bottom left: the ledger over time
    bx0, bx1, by0, by1 = 90.0, 440.0, 520.0, 700.0
    Lk = d["ledger"]
    Y2 = K.Lin(0, 22000, by1, by0)
    X2 = K.Lin(d0, d1, bx0, bx1)
    p.text(24, by0 - 22, "The ledger, docs/VALIDATION.md: lines, by day", size=12, weight="600")
    p.panel(bx0, by0, bx1, by1)
    for v in (0, 10000, 20000):
        p.line(bx0, Y2(v), bx1, Y2(v), T["grid"], 1)
        p.text(bx0 - 7, Y2(v) + 3.5, K.kmg(v), size=10.5, fill=T["muted"], anchor="end", mono=True)
    pts = [(X2(d0 + i), Y2(Lk["lines"][i])) for i in range(n)]
    p.path(pts + [(X2(d1), Y2(0)), (X2(d0), Y2(0))], "none", fill=K.mix(T["cats"][3], T["bg"], 0.55), close=True)
    p.path(pts, T["cats"][3], 2.2)
    for dd in K.week_ticks(d0, d1)[::2]:
        p.text(X2(dd), by1 + 14, K.day_short(K.day_iso(dd)), size=10, fill=T["muted"], anchor="middle", mono=True)
    p.text(bx1 - 4, Y2(Lk["lines"][-1]) - 8, "%s lines, %d entries" % (K.with_commas(Lk["lines"][-1]), Lk["entries"][-1]),
           size=10.5, anchor="end", weight="600")
    # bottom right: what was deleted
    rx0 = 500.0
    p.text(rx0, by0 - 22, "Where the lines taken out of it were", size=12, weight="600")
    ed = Lk["edits"]
    p.text(rx0, by0 + 6, "%s lines were added to the ledger over its life; %d were later deleted (%.1f%%)."
           % (K.with_commas(Lk["added"]), Lk["deleted"], 100.0 * Lk["deleted"] / Lk["added"]), size=10.5, fill=T["muted"])
    p.text(rx0, by0 + 21, "Distance from the newest entry, in entries, when the line was deleted:", size=10.5, fill=T["muted"])
    rows = []
    for k, v in sorted(ed["by_distance"].items(), key=lambda kv: int(kv[0])):
        lab = "the newest entry" if k == "0" else "%s entr%s back" % (k, "y" if k == "1" else "ies")
        rows.append((lab, v))
    mx = max(v for _l, v in rows)
    for i, (lab, v) in enumerate(rows):
        y = by0 + 54 + i * 34
        p.text(rx0, y + 12, lab, size=11)
        bw = max(3.0, 150.0 * v / mx)
        p.rect(rx0 + 130, y, bw, 18, T["cats"][3])
        p.text(rx0 + 130 + bw + 6, y + 13, "%d  (%.1f%%)" % (v, 100.0 * v / ed["deleted"]), size=10.5, mono=True)
    for k, line in enumerate(K.wrap("The ledger's own rule is that an entry never edits history. %d of the %d lines taken out "
                                    "were in the newest entry when they went, the one being written; %d were in older ones. "
                                    "%d commits took lines out, and the subjects of %d of them say restated, corrected, fixed "
                                    "or a verifier's finding." % (
                                        ed["by_distance"].get("0", 0), ed["deleted"],
                                        sum(v for kk, v in ed["by_distance"].items() if kk != "0"),
                                        ed["commits_deleting"], ed["subjects_restating"]),
                                    W - rx0 - 24, 10.5)):
        p.text(rx0, by0 + 54 + len(rows) * 34 + 12 + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_history_size.captioner
def caption_history_size(d):
    ed = d["ledger"]["edits"]
    off = sum(v for k, v in ed["by_distance"].items() if k != "0")
    elsewhere = "; ".join("%d line%s %d entr%s back, in %s on %s" % (
        e["lines"], "" if e["lines"] == 1 else "s", e["entries_from_end"], "y" if e["entries_from_end"] == 1 else "ies",
        e["commit"], K.day_short(e["day"])) for e in ed["not_the_newest"])
    return {"shows": "%s text lines in %s tracked text files at %s: the largest slice is the hard-workload pack (%s lines, "
                     "written by another model and kept as delivered), then the host library and bindings, documents "
                     "and the golden model. Beside it, the ledger (%s lines in %d entries) and a measurement of its "
                     "rule that it is append-only: %d of the %s lines ever added to it were later deleted, %d of those "
                     "in the newest entry at the time." % (
                         K.with_commas(d["total"]), K.with_commas(d["files"]), d["as_of"][:7],
                         K.with_commas(d["final"]["pack"]), K.with_commas(d["ledger"]["lines"][-1]),
                         d["ledger"]["entries"][-1], ed["deleted"], K.with_commas(d["ledger"]["added"]),
                         ed["by_distance"].get("0", 0)),
            "not": "Lines of working code: data files, captured outputs and compiled programs are lines too, and a "
                   "line is a line however long. Nor the ledger's content: it counts lines, not whether a sentence "
                   "that was changed in place mattered.",
            "notes": ["**Data and prose.** docs/VALIDATION.md says it is append-only and that \"an entry never edits "
                      "history\". Git says %d of the %s lines ever added to it were later deleted, by %d commits (%d "
                      "of whose subjects say restated, corrected, fixed or a verifier's finding: a count of those "
                      "words, not a reading of each): %d (%.1f%%) from the newest entry at the time, an edit of the "
                      "entry being written, and %d from older entries (%s). Only those %d lines of the %d belonged "
                      "to an entry that was no longer the newest, which is the case the rule rules out; the rest "
                      "restate the entry being written. This is reported as measured, and nothing here corrects it." % (
                          ed["deleted"], K.with_commas(d["ledger"]["added"]), ed["commits_deleting"],
                          ed["subjects_restating"], ed["by_distance"].get("0", 0),
                          100.0 * ed["by_distance"].get("0", 0) / ed["deleted"], off, elsewhere, off,
                          ed["deleted"])]}


# ------------------------------------------------------------ verify-growth
def _live_gate(src):
    """What the tree's own files derive for the gate's size now, by the extract's own rules."""
    run_sh = src.doc("verify/run.sh")
    tb = src.doc("tb/Makefile")
    formal = src.doc("formal/run.sh")
    return {"stages": len(re.findall(r'^stage [a-z0-9-]+ "', run_sh, re.M)),
            "quick": len(X._budget_members(run_sh, "BUDGET_QUICK") or []),
            "gate": len(X._budget_members(run_sh, "BUDGET_GATE") or []),
            "benches": X._bench_count(tb), "proofs": len(re.findall(r"^run_proof ", formal, re.M))}


def _fresh_verify_growth(src, d):
    """A note, never a failure: the figure ends at its extract's commit, and says so; this says when the
    tree has moved on from it."""
    live, tip = _live_gate(src), d["tip"]
    moved = ["%s is %s here and %s in the tree" % (k, tip[k], live[k]) for k in live if live[k] != tip.get(k)]
    if moved:
        return ["verify-growth ends at %s; the tree has moved since: %s. Remake with: python "
                "python/figure_extracts.py tree (needs the full history)" % (d["as_of"][:7], "; ".join(moved))]
    return []


@figure("verify-growth", "verification", "How the gate grew",
        lambda d: "Four small charts over time: the verification runner's stages (%d, of which %d in the gate budget "
                  "and %d in the quick one), the RTL benches (%d), the formal proofs (%d) and the golden-model test "
                  "functions (%s)." % (d["tip"]["stages"], d["tip"]["gate"], d["tip"]["quick"], d["tip"]["benches"],
                                       d["tip"]["proofs"], K.with_commas(d["tip"]["tests"])))
def build_verify_growth(src, claims):
    t = src.extract("tree")
    g = t["gates"]
    tip = {k: [v for v in g[k] if v is not None][-1] for k in g}
    first = {k: t["days"][[i for i, v in enumerate(g[k]) if v is not None][0]] for k in g}
    # The figure ends at its extract's commit. What the tree says now is compared in the freshness note, which
    # --check prints and which is never part of any output: a stage added later must not turn CI red for a
    # figure of the past.
    return {"days": t["days"], "series": {k: g[k] for k in g}, "tip": tip, "first": first, "as_of": t["as_of"]}


build_verify_growth.fresh = _fresh_verify_growth


@build_verify_growth.drawer
def draw_verify_growth(theme, d, meta):
    W, H = 900, 604
    p = K.Plot(theme, W, H, meta["title"],
               "The size of the gate at the end of each day on main's own line: the runner's stages and budgets, the "
               "cocotb RTL benches, the formal proofs, and the test functions defined for the golden model. "
               "A count a file did not yet give is a gap, not a zero.", meta["alt"])
    T = p.T
    days, n = d["days"], len(d["days"])
    d0, d1 = K.day_number(days[0]), K.day_number(days[-1])
    panels = [("Runner stages", [("stages", "all stages", T["cats"][0]), ("gate", "in the gate budget", T["cats"][1]),
                                 ("quick", "in the quick budget", T["cats"][2])]),
              ("RTL benches, make sim", [("benches", "cocotb benches", T["cats"][3])]),
              ("Formal proofs", [("proofs", "proof tasks", T["cats"][4])]),
              ("Test functions in python/tests", [("tests", "defined", T["cats"][6])])]
    pw, ph = 380.0, 150.0
    for k, (title, items) in enumerate(panels):
        cx, cy = 60 + (k % 2) * 410.0, 132 + (k // 2) * 218.0
        px0, py0, px1, py1 = cx + 32, cy + 20, cx + pw, cy + 20 + ph
        vals = [v for key, _l, _c in items for v in d["series"][key] if v is not None]
        top = K.nice_ticks(0, max(vals) * 1.08, 4)
        ymax = top[-1] if top[-1] >= max(vals) else top[-1] + (top[-1] - top[-2])
        Y = K.Lin(0, ymax, py1, py0)
        X1 = K.Lin(d0, d1, px0, px1)
        p.text(cx - 36, cy + 10, title, size=12, weight="600")
        p.panel(px0, py0, px1, py1)
        for v in top:
            p.line(px0, Y(v), px1, Y(v), T["grid"], 1)
            p.text(px0 - 6, Y(v) + 3.5, K.with_commas(v), size=10, fill=T["muted"], anchor="end", mono=True)
        for dd in K.week_ticks(d0, d1)[::2]:
            p.text(X1(dd), py1 + 13, K.day_short(K.day_iso(dd)), size=9.5, fill=T["muted"], anchor="middle", mono=True)
        for key, lab, col in items:
            pts = [(X1(d0 + i), Y(v)) for i, v in enumerate(d["series"][key]) if v is not None]
            p.path(pts, col, 2.2)
            lastv = [v for v in d["series"][key] if v is not None][-1]
            p.text(px1 - 3, Y(lastv) - 6, K.with_commas(lastv), size=10.5, fill=col, anchor="end", weight="600", mono=True)
        if len(items) > 1:
            p.legend([(c, l) for _k, l, c in items], px0 + 8, py0 + 16, pw - 20, size=10, line=True)
    p.text(24, 562, "Test functions are the lines that define one (def test_...); pytest collects several times as many "
           "because a function is run for each case it is given.", size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_verify_growth.captioner
def caption_verify_growth(d):
    t = d["tip"]
    return {"shows": "How much the project asks of itself before it believes a change: at %s the runner has %d stages "
                     "(%d in the quick budget, %d in the gate budget), %d RTL benches run under `make sim`, %d formal "
                     "proofs run, and python/tests defines %s test functions. On the first day each was counted there "
                     "were %d stages, %d benches, %d proofs and %d test functions." % (
                         d["as_of"][:7], t["stages"], t["quick"], t["gate"], t["benches"], t["proofs"],
                         K.with_commas(t["tests"]), [v for v in d["series"]["stages"] if v is not None][0],
                         [v for v in d["series"]["benches"] if v is not None][0],
                         [v for v in d["series"]["proofs"] if v is not None][0],
                         [v for v in d["series"]["tests"] if v is not None][0]),
            "not": "How long any of it takes, or whether it passes: these are sizes, counted from the files at each "
                   "day's last commit on main (the runner's stage lines and its two budget lists; tb/Makefile's bench "
                   "list in each of the three forms it has had; formal/run.sh's run_proof lines; the def test_ lines). "
                   "The figure ends at %s; `--check` prints a note, and does not fail, when the tree has moved on." % d["as_of"][:7]}


# ------------------------------------------------------------ verify-stages
STAGE_GROUPS = (
    ("keeping the tree honest", ("docs", "generated", "buildargs", "sweepjudge", "innerskips", "ensurevectors")),
    ("the golden model and its vectors", ("golden", "vectors")),
    ("the RTL", ("sim", "simmc", "lint", "formal")),
    ("the host library against the model", ("libcft", "selfcheck", "divsqrt", "clause5", "character", "transcend",
                                              "augmented", "status96", "formatof", "diff", "seq", "reduce", "mpfr")),
    ("programs, language, certificates", ("programs", "lang", "lang-routines", "tangent", "acceptance",
                                           "acceptance-far", "acceptance-rev8", "audit", "estimates", "estimates-full")),
    ("languages and surfaces", ("bindings", "cpp", "lang-cpp", "lang-rust", "lang-julia", "lang-go", "lang-csharp",
                                 "lang-r", "lang-fortran", "node", "wasm")),
    ("real workloads", ("photograph", "workloads", "demos")),
    ("hardware and remote", ("soak-quick", "images", "remote")),
)


@figure("verify-stages", "verification", "The runner's stages, and which budget runs each",
        lambda d: "The %d stages of the verification runner in eight groups, each shaded by the smallest budget that "
                  "runs it: %d in quick, %d more in gate, %d only in the full census." % (
                      d["total"], d["n_quick"], d["n_gate_only"], d["n_full_only"]))
def build_verify_stages(src, claims):
    def read(text):
        return {"names": re.findall(r'^stage ([a-z0-9-]+) "', text, re.M),
                "quick": X._budget_members(text, "BUDGET_QUICK") or [],
                "gate": X._budget_members(text, "BUDGET_GATE") or []}
    got = src.derived("verify/run.sh", "the stage names and the two budget lists", read)
    names, quick, gate = got["names"], got["quick"], got["gate"]
    known = [s for _g, ss in STAGE_GROUPS for s in ss]
    other = [s for s in names if s not in known]
    groups = [{"name": g, "stages": [s for s in ss if s in names]} for g, ss in STAGE_GROUPS]
    if other:
        groups.append({"name": "not yet placed in a group (%s)" % SELF, "stages": other})
    tier = {s: ("quick" if s in quick else "gate" if s in gate else "full") for s in names}
    claims.check("quick-of-total", "the quick budget's size, of the stages", "CLAUDE.md",
                 r"make verify-quick\s+# ~20 min, (\d+) of \d+ stages", len(quick), fmt="%d")
    claims.check("total-of-quick", "the stage count the quick line is of", "CLAUDE.md",
                 r"make verify-quick\s+# ~20 min, \d+ of (\d+) stages", len(names), fmt="%d")
    claims.check("gate-of-total", "the gate budget's size, of the stages", "CLAUDE.md",
                 r"make verify-gate\s+# ~2 h quiet, (\d+) of \d+", len(gate), fmt="%d")
    claims.check("readme-quick", "README: the quick budget's size", "README.md",
                 r"make verify-quick\s+# ~20 min, (\d+) of \d+ stages", len(quick), fmt="%d")
    claims.check("readme-gate", "README: the gate budget's size", "README.md",
                 r"make verify-gate\s+# ~2 h, (\d+) of \d+:", len(gate), fmt="%d")
    return {"groups": groups, "tier": tier, "total": len(names), "n_quick": len(quick),
            "n_gate_only": len([s for s in names if tier[s] == "gate"]),
            "n_full_only": len([s for s in names if tier[s] == "full"]), "budget_gate": len(gate),
            "full_only": [s for s in names if tier[s] == "full"]}


@build_verify_stages.drawer
def draw_verify_stages(theme, d, meta):
    W = 900
    cw, ch, gap = 112.0, 26.0, 6.0
    per_row = 5
    rows = sum((len(g["stages"]) + per_row - 1) // per_row for g in d["groups"])
    H = int(132 + rows * (ch + gap) + len(d["groups"]) * 12 + 110)
    p = K.Plot(theme, W, H, meta["title"],
               "Every stage of verify/run.sh, by what it checks. The shade is the smallest budget that runs it: "
               "make verify-quick, make verify-gate, or only the full census, make verify. Quick is part of "
               "gate, and gate of full.", meta["alt"])
    T = p.T
    shade = {"quick": T["cats"][0], "gate": K.mix(T["cats"][0], T["bg"], 0.55), "full": T["pale"]}
    y = 128.0
    for g in d["groups"]:
        p.text(24, y + 17, g["name"], size=11.5, weight="600")
        p.text(24, y + 32, "%d stage%s" % (len(g["stages"]), "" if len(g["stages"]) == 1 else "s"), size=10.5,
               fill=T["muted"])
        for k, s in enumerate(g["stages"]):
            col, row = k % per_row, k // per_row
            x, yy = 246 + col * (cw + gap), y + row * (ch + gap)
            fill = shade[d["tier"][s]]
            p.rect(x, yy, cw, ch, fill, stroke=T["axis"] if d["tier"][s] == "full" else None)
            p.text(x + cw / 2, yy + 17.5, s, size=10.5, anchor="middle", mono=True, fill=ink_on(fill, T))
        y += ((len(g["stages"]) + per_row - 1) // per_row) * (ch + gap) + 12
    ly = y + 8
    p.legend([(shade["quick"], "quick, %d stages (about 20 minutes)" % d["n_quick"]),
              (shade["gate"], "added by gate, %d (about 2 hours quiet)" % d["n_gate_only"]),
              (shade["full"], "only in the full census, %d" % d["n_full_only"])], 24, ly + 8, W - 48, size=10.5)
    p.text(24, ly + 32, "%d stages in all; the gate budget runs %d." % (d["total"], d["budget_gate"]), size=10.5,
           fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_verify_stages.captioner
def caption_verify_stages(d):
    return {"shows": "What the gate is made of: %d stages in %d groups, %d in the quick budget, %d more in the gate "
                     "budget and %d only in the full census (%s)." % (
                         d["total"], len(d["groups"]), d["n_quick"], d["n_gate_only"], d["n_full_only"],
                         ", ".join(d["full_only"])),
            "not": "What each stage proves or how long it takes: docs/VERIFICATION.md is the map of that. The grouping "
                   "is this script's (%s), not the runner's: a stage it does not place is drawn in a group of its own, "
                   "named, so a new stage shows up instead of vanishing." % SELF}


# ----------------------------------------------------------------- hw-area
@figure("hw-area", "hardware", "Where a tile's area goes, and what the U50 could carry",
        lambda d: "One tile's logic cells by bank, and the %d layouts the layout generator derives for the U50, each as "
                  "a share of the part: four full tiles fit at %.1f%%." % (len(d["layouts"]), d["quad_pct"]))
def build_hw_area(src, claims):
    gl = src.module("hw/gen_layouts.py", "fg_gen_layouts")
    tile = {"full": gl.LUT_FULL_TILE, "banks": dict(gl.BANK_LUT),
            "shared": gl.LUT_FULL_TILE - sum(gl.BANK_LUT.values())}
    layouts = []
    family = gl.family()
    # whether a layout is built is the generator's own word, in the last cell of its table's row
    status = {m.group(1): m.group(2).strip() for m in re.finditer(r"(?m)^\| `([\w-]+)` \|.*\| ([^|]+) \|$",
                                                                  gl.render_table(family))}
    for name, mix, note in family:
        n = sum(c for _v, c in mix)
        layouts.append({
            "name": name, "tiles": n, "shell": gl.shell_lut(n), "total": gl.total_lut(mix),
            "pct": r4(gl.pct(gl.total_lut(mix))),
            "mix": [[gl.SHORT[v], c, gl.tile_lut(v)] for v, c in mix],
            "mhz": [gl.VARIANTS[v]["mhz"] for v, _c in mix],
            "measured": all(gl.VARIANTS[v]["clock"].startswith("measured") for v, _c in mix),
            "status": status[name], "built": status[name] == "built"})
    quad = next(l for l in layouts if l["name"] == "u50-4xfp256")
    # held to docs/LAYOUTS.md's calibration sentence and to the generator's own comment of it
    claims.check("quad-model", "the model's LUTs for four full tiles", "docs/LAYOUTS.md",
                 r"puts the routed quad at ([\d,]+) against the\s+[\d,]+ it actually placed", quad["total"],
                 fmt="%d")
    return {"tile": tile, "layouts": layouts, "device": gl.LUT_DEVICE, "fits": gl.FITS_PCT, "limit": gl.LIMIT_PCT,
            "max_tiles": gl.MAX_TILES, "quad_pct": quad["pct"], "quad_total": quad["total"],
            "shell_1cu": gl.SHELL_1CU, "shell_per_extra": gl.SHELL_PER_EXTRA_CU}


@build_hw_area.drawer
def draw_hw_area(theme, d, meta):
    W = 900
    n = len(d["layouts"])
    H = int(236 + n * 27 + 96)
    p = K.Plot(theme, W, H, meta["title"],
               "Top: the logic cells one tile costs, out of context, split by the four banks of FMA lanes and the shared "
               "machinery. Below: every tile mix the layout generator catalogues for the U50, as a share of the part's "
               "%s LUTs: the shell, then the tiles. The two built layouts are marked." % K.with_commas(d["device"]),
               meta["alt"])
    T = p.T
    t = d["tile"]
    parts = [(FORMAT_LABEL[f], t["banks"][f], T["cats"][i]) for i, f in enumerate(FORMATS)] + [
        ("shared machinery", t["shared"], T["cats"][5])]
    x0, x1 = 24.0, 876.0
    sx = K.Lin(0, t["full"], x0, x1)
    xx, y = 0, 130.0
    for lab, v, col in parts:
        a, b = sx(xx), sx(xx + v)
        p.rect(a, y, b - a, 30, col)
        p.text((a + b) / 2, y + 19.5, K.with_commas(v), size=11, anchor="middle", mono=True, fill=ink_on(col, T))
        p.text((a + b) / 2, y + 46, lab, size=10.5, anchor="middle", fill=T["muted"])
        xx += v
    p.text(x0, y - 8, "one tile, out of context: %s LUTs" % K.with_commas(t["full"]), size=11.5, weight="600")
    # the catalogue
    cy0 = y + 78
    lx0, lx1 = 250.0, 730.0
    sc = K.Lin(0, 100, lx0, lx1)
    p.text(24, cy0 - 12, "layouts, as a share of the U50's logic cells", size=11.5, weight="600")
    for v in (0, 20, 40, 60, 80, 100):
        p.line(sc(v), cy0, sc(v), cy0 + n * 27, T["grid"], 1)
        p.text(sc(v), cy0 + n * 27 + 13, "%d%%" % v, size=10, fill=T["muted"], anchor="middle", mono=True)
    for k, lay in enumerate(d["layouts"]):
        yy = cy0 + k * 27
        p.text(24, yy + 15, lay["name"][4:], size=10.5, mono=True, weight="600" if lay["built"] else None)
        a = sc(0)
        w = sc(100.0 * lay["shell"] / d["device"]) - sc(0)
        p.rect(a, yy + 3, w, 17, T["muted"], opacity=0.5)
        a += w
        for j, (short, cnt, each) in enumerate(lay["mix"]):
            w = sc(100.0 * each * cnt / d["device"]) - sc(0)
            col = {"fp256": T["cats"][3], "fp128": T["cats"][2], "fp64": T["cats"][1], "fp32": T["cats"][0],
                   "fp64fp128": T["cats"][6]}.get(short, T["cats"][5])
            p.rect(a, yy + 3, w, 17, col)
            if w > 34:
                p.text(a + w / 2, yy + 15.5, "%dx %s" % (cnt, short.replace("fp", "")), size=9.5, anchor="middle",
                       fill=ink_on(col, T), mono=True)
            a += w
        p.text(lx1 + 10, yy + 15.5, "%.1f%%" % lay["pct"], size=10, fill=T["fg"], mono=True)
        p.text(lx1 + 66, yy + 15.5, "/".join(str(m) for m in lay["mhz"]) + " MHz" + ("" if lay["measured"] else "*"),
               size=10, fill=T["muted"], mono=True)
    for pct_, lab, col, anch, dx in ((d["fits"], "fits", T["win"], "end", -4),
                                     (d["limit"], "routing limit", T["lose"], "start", 4)):
        p.line(sc(pct_), cy0 - 2, sc(pct_), cy0 + n * 27, col, 1.4, dash="5 4")
        p.text(sc(pct_) + dx, cy0 - 5, "%.0f%% %s" % (pct_, lab), size=9.5, fill=col, anchor=anch)
    p.text(lx1 + 10, cy0 - 5, "of the part", size=9.5, fill=T["muted"])
    p.text(lx1 + 66, cy0 - 5, "clocks, MHz", size=9.5, fill=T["muted"])
    for k, line in enumerate(K.wrap(
            "Grey: the shell and crossbar. Bold names are the two layouts built so far; the others are placeholders until "
            "narrow variants are packaged. * a clock target, not a measurement. The model is about 2%% optimistic: it "
            "puts four full tiles at %s LUTs, where the routed quad placed higher." % K.with_commas(d["quad_total"]),
            W - 48, 10.5)):
        p.text(24, cy0 + n * 27 + 34 + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_hw_area.captioner
def caption_hw_area(d):
    t = d["tile"]
    big = max(FORMATS, key=lambda f: t["banks"][f])
    return {"shows": "A full tile costs %s LUTs out of context: the four banks cost %s, %s, %s and %s (binary32 to "
                     "binary256, each about the same because lanes halve as precision doubles, until binary256 cannot "
                     "halve) and the shared machinery %s. Four of them and the shell come to %.1f%% of the U50 in the "
                     "model; narrower tiles let more fit." % (
                         K.with_commas(t["full"]), K.with_commas(t["banks"]["fp32"]), K.with_commas(t["banks"]["fp64"]),
                         K.with_commas(t["banks"]["fp128"]), K.with_commas(t["banks"]["fp256"]),
                         K.with_commas(t["shared"]), d["quad_pct"]),
            "not": "Placed results: this is hw/gen_layouts.py's model, from tile costs measured out of context, and it "
                   "is about 2% optimistic against the routed quad (docs/LAYOUTS.md). Only the two layouts marked "
                   "bold have been built."}


# ---------------------------------------------------------------- hw-clock
@figure("hw-clock", "hardware", "How far the clock was pushed, and what it left in slack",
        lambda d: "Kernel slack against the clock for every timing attempt the ledger records for the U50 "
                  "(%d attempts), and the slack of the images built at 135 MHz over time. One tile closes %d MHz; "
                  "four tiles close %d." % (len(d["attempts"]), d["max_single"], d["max_quad"]))
def build_hw_clock(src, claims):
    led = src.extract("ledger")
    att = led["attempts"]
    closed = [a for a in att if a["closed"]]
    max_single = max(a["mhz"] for a in closed if a["tiles"] == 1 and a["mhz"] < 200)
    max_quad = max(a["mhz"] for a in closed if a["tiles"] == 4)
    proven = [a for a in closed if a["card"] and a["card"].endswith("pass")]
    top = max(proven, key=lambda a: a["mhz"])
    m = re.search(r"one tile closes (\d+) MHz,\s+proven on the card, (\d{4}-\d{2}-\d{2})", src.doc("README.md"))
    claims.add("175-proven", "the highest clock a single tile closed and passed on the card, and its day",
               "README.md", "%d MHz, %s" % (top["mhz"], top["date"]),
               ("%s MHz, %s" % (m.group(1), m.group(2))) if m else None,
               bool(m) and (int(m.group(1)), m.group(2)) == (top["mhz"], top["date"]))
    return {"attempts": att, "max_single": max_single, "max_quad": max_quad, "n_missed": len(att) - len(closed),
            "proven": top["mhz"], "quote": led["quotes"][0]}


@build_hw_clock.drawer
def draw_hw_clock(theme, d, meta):
    W, H = 900, 640
    p = K.Plot(theme, W, H, meta["title"],
               "Every kernel worst-negative-slack the ledger states for a build on the U50, read out of docs/VALIDATION.md. "
               "A build closes timing when its slack is not negative. Left: slack against the clock it was built at. "
               "Right: the images built at 130 and 135 MHz, in the order they were built.", meta["alt"])
    T = p.T
    att = [a for a in d["attempts"] if a["mhz"] < 200]
    off = [a for a in d["attempts"] if a["mhz"] >= 200]
    ylo, yhi = -0.45, 0.65
    ay0, ay1 = 150.0, 470.0
    Y = K.Lin(ylo, yhi, ay1, ay0)
    colr = {1: T["cats"][0], 4: T["cats"][1]}

    def marker(x, y, tiles, closed, size=5.5):
        col = colr[tiles]
        if tiles == 1:
            if closed:
                p.circle(x, y, size, col)
            else:
                p.circle(x, y, size, T["bg"], stroke=T["lose"], sw=2)
        else:
            if closed:
                p.rect(x - size, y - size, 2 * size, 2 * size, col)
            else:
                p.rect(x - size, y - size, 2 * size, 2 * size, T["bg"], stroke=T["lose"], sw=2)
    # left panel: slack against clock
    lx0, lx1 = 84.0, 470.0
    X1 = K.Lin(125, 180, lx0, lx1)
    p.text(lx0, ay0 - 14, "slack (ns) against the clock built for (MHz)", size=11.5, weight="600")
    p.panel(lx0, ay0, lx1, ay1)
    for v in (-0.4, -0.2, 0, 0.2, 0.4, 0.6):
        p.line(lx0, Y(v), lx1, Y(v), T["axis"] if v == 0 else T["grid"], 1.5 if v == 0 else 1)
        p.text(lx0 - 6, Y(v) + 3.5, "%+.1f" % v if v else "0", size=10, fill=T["muted"], anchor="end", mono=True)
    for v in range(130, 181, 10):
        p.line(X1(v), ay0, X1(v), ay1, T["grid"], 1)
        p.text(X1(v), ay1 + 14, str(v), size=10, fill=T["muted"], anchor="middle", mono=True)
    groups = {}
    for a in att:
        groups.setdefault((a["mhz"], a["tiles"]), []).append(a)
    for (mhz, tiles), lst in sorted(groups.items()):
        for j, a in enumerate(sorted(lst, key=lambda a: a["date"] + a["id"])):
            x = X1(mhz) + (j - (len(lst) - 1) / 2.0) * 6 + (-5 if tiles == 1 else 5)
            marker(x, Y(a["wns"]), tiles, a["closed"])
            if mhz > 135 and (tiles == 1) and a["recipe"] == "standard" and not a["id"].startswith("bracket"):
                p.text(x, Y(a["wns"]) - 11, "%+.3f" % a["wns"], size=8.5, fill=T["muted"], anchor="middle", mono=True)
    for a in att:
        if a["id"] == "sweep-175-extra":
            p.line(X1(175), Y(a["wns"]) + 7, X1(175), Y(-0.2), T["axis"], 1, dash="2 3")
            p.text(X1(175) + 8, Y(-0.2) + 4, "175 MHz: %+.3f with the second recipe" % a["wns"], size=9.5, anchor="end",
                   fill=T["fg"])
            p.text(X1(175) + 8, Y(-0.2) + 17, "(%+.3f with the standard one)" % [b for b in att if b["id"] == "sweep-175-std"][0]["wns"],
                   size=9.5, anchor="end", fill=T["muted"])
    for a in off:
        p.text(lx1 - 4, ay1 - 8, "%d MHz: %.3f ns (off the chart)" % (a["mhz"], a["wns"]), size=9.5, fill=T["lose"],
               anchor="end")
    p.text((lx0 + lx1) / 2, ay1 + 30, "target clock, MHz", size=10.5, fill=T["muted"], anchor="middle")
    # right panel: one row a build, a dot an image, in the order they were built
    by_id = {a["id"]: a for a in d["attempts"]}
    lineage = (("bac9f550, 130 MHz", ("bac9f550-single", "bac9f550-quad")),
               ("b1a014c, 130 MHz", ("ms-single", "ms-quad")),
               ("39fc2c0", ("135-single", "135-quad")),
               ("ed752dd", ("ed752dd-single", "ed752dd-quad")),
               ("revision 2", ("rev2-single", "rev2-quad")),
               ("revision 3", ("rev3-single", "rev3-quad")),
               ("read-ahead", ("ra-single", "ra-quad")),
               ("revision 4", ("rev4-single", "rev4-quad")),
               ("round 2", ("round2-single", "round2-quad-first", "round2-quad")),
               ("revision 7", ("rev7b-single", "q135b-quad")),
               ("revision 8", ("rev8a-single", "rev8q-quad", "rev8d-deep")))
    rx0, rx1 = 610.0, 872.0
    X2 = K.Lin(-0.45, 0.5, rx0, rx1)
    p.text(520, ay0 - 14, "slack of every 130 and 135 MHz image, in build order", size=11.5, weight="600")
    rowh = (ay1 - ay0) / float(len(lineage))
    p.panel(rx0, ay0, rx1, ay1)
    for v in (-0.4, -0.2, 0, 0.2, 0.4):
        p.line(X2(v), ay0, X2(v), ay1, T["axis"] if v == 0 else T["grid"], 1.5 if v == 0 else 1)
        p.text(X2(v), ay1 + 14, "%+.1f" % v if v else "0", size=10, fill=T["muted"], anchor="middle", mono=True)
    for r, (label, ids) in enumerate(lineage):
        yc = ay0 + r * rowh + rowh / 2.0
        xs = [X2(by_id[i]["wns"]) for i in ids]
        p.line(min(xs), yc, max(xs), yc, T["axis"], 1.2)
        p.text(rx0 - 8, yc + 3.5, "%s  %s" % (K.day_short(by_id[ids[0]]["date"]), label), size=10, anchor="end")
        for i in ids:
            a = by_id[i]
            x = X2(a["wns"])
            if a["id"] == "rev8d-deep":
                col = T["cats"][3]
                p.polygon([(x, yc - 5.5), (x + 5.5, yc), (x, yc + 5.5), (x - 5.5, yc)], col)
            else:
                marker(x, yc, a["tiles"], a["closed"], size=4.8)
    p.text((rx0 + rx1) / 2, ay1 + 30, "kernel slack, ns", size=10.5, fill=T["muted"], anchor="middle")
    ly = p.legend([(colr[1], "one tile (circle)"), (colr[4], "four tiles (square)"), (T["cats"][3], "deep single (diamond)"),
                   (T["lose"], "missed: red outline")],
                  24, 530, W - 48, size=10.5)
    missed = [a for a in d["attempts"] if not a["closed"]]
    sw = [a for a in d["attempts"] if a["id"].startswith("sweep-") and a["closed"]]
    swp = [a for a in sw if a["card"] and a["card"].endswith("pass")]
    q135 = [a["wns"] for a in d["attempts"] if a["tiles"] == 4 and a["closed"] and a["mhz"] == 135]
    text = ("Missed, of %d attempts: %s. Every other one closed. The sweep's closed points (%s MHz) passed the conformance "
            "set on the card at %d of %d; the quad closed 135 MHz %d times with slack from %+.3f to %+.3f ns."
            % (len(d["attempts"]),
               "; ".join("%s at %d MHz, %+.3f (%s)" % ("one tile" if a["tiles"] == 1 else "four tiles", a["mhz"], a["wns"],
                                                      K.day_short(a["date"])) for a in missed),
               ", ".join(str(a["mhz"]) for a in sw), len(swp), len(sw), len(q135), min(q135), max(q135)))
    for k, line in enumerate(K.wrap(text, W - 48, 10.5)):
        p.text(24, ly + 12 + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_hw_clock.captioner
def caption_hw_clock(d):
    att = d["attempts"]
    closed = [a for a in att if a["closed"]]
    q135 = [a for a in att if a["tiles"] == 4 and a["mhz"] == 135]
    q135c = [a for a in q135 if a["closed"]]
    q135m = [a for a in q135 if not a["closed"]]
    first = min(a["date"] for a in q135c)
    best = [a for a in att if a["id"] == "sweep-175-extra"][0]
    q = d["quote"]
    return {"shows": "%d timing attempts the ledger records on the U50, %d of them missed. One tile closed %d MHz (by "
                     "%+.3f ns, with the second recipe) and passed on the card. Four tiles closed 135 MHz %d times from "
                     "%s, with slack from %+.3f to %+.3f ns, and missed it %s (%s; closed on a rebuild); at 145 they "
                     "missed by %.3f. The long-shot build for 260 MHz missed by %.3f ns and is off the chart." % (
                         len(att), d["n_missed"], d["max_single"], best["wns"], len(q135c), K.day_short(first),
                         min(a["wns"] for a in q135c), max(a["wns"] for a in q135c),
                         {1: "once", 2: "twice"}.get(len(q135m), "%d times" % len(q135m)),
                         "; ".join("%s, %+.3f" % (a["label"], a["wns"]) for a in q135m),
                         [a for a in att if a["id"] == "bracket-quad-145"][0]["wns"],
                         [a for a in att if a["id"] == "long-shot-260"][0]["wns"]),
            "not": "How many builds were made: only builds for which the ledger states a kernel slack are here. A small "
                   "positive slack is not a margin to build on: the ledger's own lesson (%s, line %d) is that %s." % (
                       q["entry"][:10], q["line"], q["text"])}


# ----------------------------------------------------------------- math-cost
M1_LINE = re.compile(r"^(fp\d+) (\w+)\s+K(\d+) D(\d+): instructions (\d+)-(\d+) \[([\d, ]+)\], words (\d+)-(\d+), "
                     r"live (\d+)-(\d+)\s*$", re.M)
M2_LINE = re.compile(r"^(fp\d+) (sin|cos|tan) rne: (\d+) instructions, (\d+) words, live (\d+);")
PHASE_GROUP = (("range reduction", lambda k: k.startswith("red-")),
               ("the series", lambda k: k in ("z", "S-head", "S-tail", "C-head", "C-tail")),
               ("choosing and finishing", lambda k: True))
FN_ORDER = ("exp", "exp2", "expm1", "log", "log2", "log1p", "sin", "cos", "tan")


def _parse_m2_costs(src):
    import ast
    out = {}
    for fmt in FORMATS:
        lines = src.text("docs/studies/m2/costs.%s.out.txt" % fmt).splitlines()
        for i, ln in enumerate(lines):
            m = M2_LINE.match(ln)
            if not m:
                continue
            ph = lines[i + 1].strip()
            if not ph.startswith("by phase"):
                raise X.ExtractError("costs.%s.out.txt: no 'by phase' line after %r" % (fmt, ln[:30]))
            phases = ast.literal_eval(ph[len("by phase"):].strip())
            out[(fmt, m.group(2))] = {"instructions": int(m.group(3)), "words": int(m.group(4)), "live": int(m.group(5)),
                                      "phases": phases}
    return out


@figure("math-cost", "math", "What a correctly rounded function costs the tile",
        lambda d: "Tile instructions per call for the nine correctly rounded functions at the formats they are built for "
                  "(%d to %d), and where the trigonometric three spend theirs: range reduction takes %d to %d of each "
                  "sin, cos and tan." % (d["min"], d["max"], d["red_min"], d["red_max"]))
def build_math_cost(src, claims):
    m1 = {}
    for m in M1_LINE.finditer(src.text("docs/studies/m1/final_counts.out.txt")):
        fmt, fn = m.group(1), m.group(2)
        per = [int(x) for x in m.group(7).split(",")]
        m1[(fmt, fn)] = {"instructions": max(per), "min": min(per), "per_attribute": per, "words": int(m.group(9)),
                         "live": int(m.group(11))}
    if len(m1) != 18:
        raise X.ExtractError("final_counts.out.txt gave %d routines, want 18" % len(m1))
    m2 = _parse_m2_costs(src)
    if len(m2) != 12:
        raise X.ExtractError("costs.*.out.txt gave %d routines, want 12" % len(m2))
    rows = []
    for fn in FN_ORDER:
        for fmt in FORMATS:
            if fn in ("sin", "cos", "tan"):
                v = m2[(fmt, fn)]
                rows.append({"fn": fn, "format": fmt, "instructions": v["instructions"], "min": v["instructions"],
                             "from": "M2", "words": v["words"], "live": v["live"]})
            elif (fmt, fn) in m1:
                v = m1[(fmt, fn)]
                rows.append({"fn": fn, "format": fmt, "instructions": v["instructions"], "min": v["min"], "from": "M1",
                             "words": v["words"], "live": v["live"]})
    phases = []
    sums_ok = True
    for fmt in FORMATS:
        for fn in ("sin", "cos", "tan"):
            v = m2[(fmt, fn)]
            tot = sum(v["phases"].values())
            sums_ok = sums_ok and tot == v["instructions"]
            groups = {}
            for k, c in v["phases"].items():
                for gname, test in PHASE_GROUP:
                    if test(k):
                        groups[gname] = groups.get(gname, 0) + c
                        break
            phases.append({"fn": fn, "format": fmt, "total": v["instructions"], "phase_sum": tot,
                           "groups": {g: groups.get(g, 0) for g, _t in PHASE_GROUP}})
    # held to docs/studies/M2-trig.md: "sin 406, 382 and 389 instructions at fp64, fp128 and fp256; cos 4 fewer;
    # tan 13 to 17 more"
    doc = "docs/studies/M2-trig.md"
    sin = {f: m2[(f, "sin")]["instructions"] for f in FORMATS}
    stated = re.search(r"sin (\d+), (\d+) and (\d+) instructions at\s+fp64, fp128 and fp256; cos (\d+) fewer; "
                       r"tan (\d+) to (\d+) more", src.doc(doc))
    for k, fmt in enumerate(("fp64", "fp128", "fp256")):
        claims.add("sin-" + fmt, "sin's instructions at %s" % FORMAT_LABEL[fmt], doc, str(sin[fmt]),
                   stated.group(k + 1) if stated else None, bool(stated) and int(stated.group(k + 1)) == sin[fmt])
    diffs = sorted({sin[f] - m2[(f, "cos")]["instructions"] for f in FORMATS})
    claims.add("cos-fewer", "how many fewer instructions cos takes than sin, at every format", doc,
               "%s" % ", ".join(str(x) for x in diffs), stated.group(4) if stated else None,
               bool(stated) and diffs == [int(stated.group(4))])
    tan_more = [m2[(f, "tan")]["instructions"] - sin[f] for f in ("fp64", "fp128", "fp256")]
    claims.add("tan-more", "how many more instructions tan takes than sin, fp64 to fp256", doc,
               "%d to %d" % (min(tan_more), max(tan_more)),
               ("%s to %s" % (stated.group(5), stated.group(6))) if stated else None,
               bool(stated) and (min(tan_more), max(tan_more)) == (int(stated.group(5)), int(stated.group(6))))
    claims.add("phases-add-up", "each routine's phases add up to its instructions", "docs/studies/m2/costs.*.out.txt",
               "12 of 12" if sums_ok else "some do not", "12 of 12", sums_ok)
    red = [g["groups"]["range reduction"] for g in phases]
    return {"rows": rows, "phases": phases, "min": min(r["instructions"] for r in rows),
            "max": max(r["instructions"] for r in rows), "red_min": min(red), "red_max": max(red)}


@build_math_cost.drawer
def draw_math_cost(theme, d, meta):
    W = 900
    H = 780
    p = K.Plot(theme, W, H, meta["title"],
               "Instructions in the tile's own program for one correctly rounded result, per format. Exp and log "
               "families (M1): the most any rounding attribute needs. Sin, cos and tan (M2): the same at every attribute. "
               "Below: the three trigonometric functions split into range reduction, the series and the finish.", meta["alt"])
    T = p.T
    cols = {"fp32": T["cats"][4], "fp64": T["cats"][1], "fp128": T["cats"][2], "fp256": T["cats"][0]}
    x0, x1 = 120.0, 800.0
    top = 450.0
    sx = K.Lin(0, top, x0, x1)
    y0 = 140.0
    pitch = 36.0
    for v in (0, 100, 200, 300, 400):
        p.line(sx(v), y0 - 6, sx(v), y0 + len(FN_ORDER) * pitch, T["grid"], 1)
        p.text(sx(v), y0 + len(FN_ORDER) * pitch + 12, str(v), size=10, fill=T["muted"], anchor="middle", mono=True)
    p.text(x0, y0 - 14, "tile instructions per call", size=10.5, fill=T["muted"])
    for k, fn in enumerate(FN_ORDER):
        yy = y0 + k * pitch
        p.text(24, yy + 18, fn, size=12, weight="600", mono=True)
        rows = [r for r in d["rows"] if r["fn"] == fn]
        for j, r in enumerate(rows):
            by = yy + 2 + j * 7.5
            p.rect(x0, by, sx(r["instructions"]) - x0, 6.5, cols[r["format"]])
            lab = str(r["instructions"]) if r["min"] == r["instructions"] else "%d-%d" % (r["min"], r["instructions"])
            p.text(sx(r["instructions"]) + 5, by + 6, lab, size=9, fill=T["muted"], mono=True)
    ly = y0 + len(FN_ORDER) * pitch + 28
    p.legend([(cols[f], FORMAT_LABEL[f]) for f in FORMATS], x0, ly, 700, size=10.5)
    # phases
    py0 = ly + 52
    p.text(24, py0 - 14, "where sin, cos and tan spend their instructions", size=12, weight="600")
    gcol = {"range reduction": T["cats"][3], "the series": T["cats"][5], "choosing and finishing": T["cats"][8]}
    sx2 = K.Lin(0, 450, x0 + 50, x1)
    rows = d["phases"]
    for i, r in enumerate(rows):
        yy = py0 + i * 17 + (i // 3) * 5
        p.text(24, yy + 11, "%s, %s" % (r["fn"], FORMAT_LABEL[r["format"]]), size=10, mono=True)
        a = x0 + 50
        for gname in ("range reduction", "the series", "choosing and finishing"):
            v = r["groups"][gname]
            wd = sx2(v) - sx2(0)
            p.rect(a, yy, wd, 13, gcol[gname])
            if v >= 26:
                p.text(a + wd / 2, yy + 10.5, str(v), size=9.5, anchor="middle", fill=ink_on(gcol[gname], T), mono=True)
            a += wd
        p.text(a + 6, yy + 10.5, str(r["total"]), size=9.5, fill=T["muted"], mono=True)
    ly2 = py0 + len(rows) * 17 + 4 * 5 + 10
    p.legend([(gcol[g], g) for g in ("range reduction", "the series", "choosing and finishing")], x0 + 50, ly2, 700, size=10.5)
    p.footer([source_line(meta)])
    return p.render()


@build_math_cost.captioner
def caption_math_cost(d):
    by = {(r["fn"], r["format"]): r for r in d["rows"]}
    wide = [100.0 * by[(fn, "fp256")]["instructions"] / by[(fn, "fp64")]["instructions"] for fn in FN_ORDER]
    return {"shows": "Each correctly rounded routine is a program of %d to %d tile instructions at its format: "
                     "exp and expm1 about %d, the log family %d to %d, sin %d, %d, %d and %d (binary32 to binary256). "
                     "Binary256 costs %.0f%% to %.0f%% of what the same routine costs at binary64. Of sin, cos and tan, "
                     "range reduction takes %d to %d instructions."
                     % (d["min"], d["max"], by[("exp", "fp64")]["instructions"],
                        min(by[(g, f)]["instructions"] for g in ("log", "log2", "log1p") for f in ("fp64", "fp128", "fp256")),
                        max(by[(g, f)]["instructions"] for g in ("log", "log2", "log1p") for f in ("fp64", "fp128", "fp256")),
                        by[("sin", "fp32")]["instructions"], by[("sin", "fp64")]["instructions"],
                        by[("sin", "fp128")]["instructions"], by[("sin", "fp256")]["instructions"],
                        min(wide), max(wide), d["red_min"], d["red_max"]),
            "not": "Time: an instruction is a pass of the sequencer over the lanes, not a clock cycle, and the M1 and "
                   "M2 numbers are counts of the compiled routines (the study's own scripts, captured in "
                   "docs/studies/m1/ and m2/), not measurements on the card. %s" % (
                       "M1's exp and log family has no binary32 row." if not any(
                           r["from"] == "M1" and r["format"] == "fp32" for r in d["rows"]) else "")}


# --------------------------------------------------------------- math-marks
M1_RATE = re.compile(r"^(\w+)\s+(fp\d+) (\w+) bound [^:]+: marked (\d+)/(\d+) = ([\d.]+) \(guess right (\d+)\), "
                     r"predicted ([\d.]+), wrong unmarked (\d+)", re.M)
M2_RATE = re.compile(r"^(fp\d+) (\w+) (\w+) G'=(\d+) seed (\d+): (\d+) lanes, marked (\d+) = ([\d.]+)%; M1's law "
                     r"([\d.]+)% \(([+-][\d.]+) sigma\); each lane's own 2\^-G' sig\(V\) sums to ([\d.]+) = ([\d.]+)% "
                     r"\(([+-][\d.]+) sigma\); guesses right (\d+) of (\d+); wrong unmarked (\d+)", re.M)


@figure("math-marks", "math", "How often a correctly rounded routine has to say 'undecided'",
        lambda d: "Observed rates of marked (undecided) lanes for the six exp and log routines and for sin, cos and tan, "
                  "against the law that predicts them: %d runs, %s lanes, and not one lane that was wrong went "
                  "unmarked." % (d["runs"], K.with_commas(d["lanes"])))
def build_math_marks(src, claims):
    rows = []
    for m in M1_RATE.finditer(src.text("docs/studies/m1/m1rate.fp64.out.txt")):
        n, k = int(m.group(5)), int(m.group(4))
        rows.append({"from": "M1", "fn": m.group(1), "format": m.group(2), "rounding": m.group(3), "lanes": n, "marked": k,
                     "law": r4(float(m.group(8)) * 100), "lane_law": None, "wrong_unmarked": int(m.group(9)),
                     "guess_right": int(m.group(7)), "sigma_first": None, "sigma_lane": None})
    for fmt in ("fp64", "fp128", "fp256"):
        for m in M2_RATE.finditer(src.text("docs/studies/m2/box-out/rate-%s.out.txt" % fmt)):
            n, k = int(m.group(6)), int(m.group(7))
            rows.append({"from": "M2", "fn": m.group(2), "format": m.group(1), "rounding": m.group(3), "lanes": n,
                         "marked": k, "law": r4(float(m.group(9))), "lane_law": r4(float(m.group(12))),
                         "wrong_unmarked": int(m.group(16)), "guess_right": int(m.group(14)),
                         "sigma_first": float(m.group(10)), "sigma_lane": float(m.group(13))})
    if len(rows) != 30:
        raise X.ExtractError("the rate outputs gave %d runs, want 30 (12 of M1 and 18 of M2)" % len(rows))
    for r in rows:
        pr = 100.0 * r["marked"] / r["lanes"]
        se = 100.0 * math.sqrt((pr / 100.0) * (1 - pr / 100.0) / r["lanes"])
        r["rate"] = r4(pr)
        r["ci95"] = r4(1.96 * se)
    wrong = sum(r["wrong_unmarked"] for r in rows)
    right_all = all(r["guess_right"] == r["marked"] for r in rows)
    mt = re.search(r"0 wrong unmarked lanes", src.doc("docs/studies/M2-trig.md"))
    claims.add("wrong-unmarked", "lanes that were wrong without being marked, over every captured rate run",
               "docs/studies/M2-trig.md", str(wrong), "0 wrong unmarked lanes" if mt else None, wrong == 0 and bool(mt))
    claims.add("guesses-right", "marked lanes whose guessed rounding turned out right, in every run",
               "docs/studies/m2/box-out/rate-*.out.txt", "%d of %d runs all right" % (sum(1 for r in rows if r["guess_right"] == r["marked"]), len(rows)),
               "all", right_all)
    sc64 = [r["sigma_first"] for r in rows if r["from"] == "M2" and r["format"] == "fp64" and r["fn"] in ("sin", "cos")]
    lane = [abs(r["sigma_lane"]) for r in rows if r["from"] == "M2"]
    return {"rows": rows, "runs": len(rows), "lanes": sum(r["lanes"] for r in rows), "marked": sum(r["marked"] for r in rows),
            "wrong_unmarked": wrong, "first_law_sigma_sincos64": [min(sc64), max(sc64)], "lane_law_max_sigma": max(lane)}


@build_math_marks.drawer
def draw_math_marks(theme, d, meta):
    W = 900
    H = 846
    p = K.Plot(theme, W, H, meta["title"],
               "A lane is marked when the routine cannot decide its rounding within the bound, and the host then "
               "decides it. Each dot is a captured run: its marked share of lanes with a 95% binomial interval. The "
               "diamond is the rate the first law predicts; the hollow one, for sin, cos and tan, the rate the lane's own "
               "bound predicts. Filled is round to nearest even, hollow is toward zero.", meta["alt"])
    T = p.T
    x0, x1 = 230.0, 760.0
    sx = K.Lin(1.0, 3.6, x0, x1)
    rows = d["rows"]
    keys = []
    for r in rows:
        k = (r["from"], r["fn"], r["format"])
        if k not in keys:
            keys.append(k)
    y0, pitch = 168.0, 33.0
    for v in (1.0, 1.5, 2.0, 2.5, 3.0, 3.5):
        p.line(sx(v), y0 - 8, sx(v), y0 + len(keys) * pitch + 22, T["grid"], 1)
        p.text(sx(v), y0 + len(keys) * pitch + 35, "%.1f%%" % v, size=10, fill=T["muted"], anchor="middle", mono=True)
    p.text(x0, y0 - 14, "marked lanes, share of the run", size=10.5, fill=T["muted"])
    ctx = {"fp64": T["cats"][1], "fp128": T["cats"][2], "fp256": T["cats"][0]}
    prev = None
    for i, k in enumerate(keys):
        yy = y0 + i * pitch + (22 if k[0] == "M2" else 0)
        if k[0] != prev:
            if k[0] == "M1":
                ln = sorted({r["lanes"] for r in rows if r["from"] == "M1"})
                hdr = "M1, the exp and log family at binary64: %s lanes a run" % " and ".join(K.with_commas(x) for x in ln)
            else:
                per = []
                for f in ("fp64", "fp128", "fp256"):
                    ln = sorted({r["lanes"] for r in rows if r["from"] == "M2" and r["format"] == f})
                    per.append("%s at %s" % (" and ".join(K.with_commas(x) for x in ln), FORMAT_LABEL[f]))
                hdr = "M2, sin, cos and tan: " + ", ".join(per) + " lanes a run"
            p.text(24, yy - 10 if k[0] == "M2" else y0 - 36, hdr, size=11, weight="600")
            prev = k[0]
        p.text(24, yy + 18, "%s, %s" % (k[1], FORMAT_LABEL[k[2]]), size=10.5, mono=True)
        mine = [r for r in rows if (r["from"], r["fn"], r["format"]) == k]
        law = mine[0]["law"]
        p.polygon([(sx(law), yy + 3), (sx(law) + 6, yy + 12), (sx(law), yy + 21), (sx(law) - 6, yy + 12)], T["fg"])
        if mine[0]["lane_law"] is not None:
            q = mine[0]["lane_law"]
            p.path([(sx(q), yy + 4), (sx(q) + 5, yy + 12), (sx(q), yy + 20), (sx(q) - 5, yy + 12)], T["fg"], 1.6, close=True)
        for r in mine:
            yc = yy + (8 if r["rounding"] == "rne" else 16)
            col = ctx[r["format"]]
            p.line(sx(r["rate"] - r["ci95"]), yc, sx(r["rate"] + r["ci95"]), yc, col, 1.6)
            if r["rounding"] == "rne":
                p.circle(sx(r["rate"]), yc, 3.8, col)
            else:
                p.circle(sx(r["rate"]), yc, 3.8, T["bg"], stroke=col, sw=1.8)
        p.text(x1 + 16, yy + 16, "0 wrong unmarked" if all(r["wrong_unmarked"] == 0 for r in mine) else "WRONG UNMARKED",
               size=9.5, fill=T["muted"], mono=True)
    ly = y0 + len(keys) * pitch + 62
    p.legend([(ctx["fp64"], "binary64"), (ctx["fp128"], "binary128"), (ctx["fp256"], "binary256")], 24, ly, 400, size=10.5)
    lo_s, hi_s = d["first_law_sigma_sincos64"]
    for k, line in enumerate(K.wrap(
            "%d runs, %s lanes: %s marked, and none of the lanes whose rounding was wrong was left unmarked. For sin and cos "
            "at binary64 the first law reads low by %.1f to %.1f standard deviations; the lane's own bound (hollow diamond) "
            "is within %.1f of every run."
            % (d["runs"], K.with_commas(d["lanes"]), K.with_commas(d["marked"]), lo_s, hi_s, d["lane_law_max_sigma"]),
            W - 48, 10.5)):
        p.text(24, ly + 24 + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_math_marks.captioner
def caption_math_marks(d):
    return {"shows": "How often the exp, log, sin, cos and tan routines mark a lane undecided: %s lanes in %d captured "
                     "runs, %s marked (%.2f%%), and in every run every marked lane's guessed rounding was right and no "
                     "wrong lane was unmarked. At binary64 the first law reads low for sin and cos by %.1f to %.1f "
                     "standard deviations; the study's second, per-lane law is within %.1f of every run." % (
                         K.with_commas(d["lanes"]), d["runs"], K.with_commas(d["marked"]), 100.0 * d["marked"] / d["lanes"],
                         d["first_law_sigma_sincos64"][0], d["first_law_sigma_sincos64"][1], d["lane_law_max_sigma"]),
            "not": "That the routines are correctly rounded: the marked lanes are decided by the host, and the proof "
                   "of the bound is docs/studies/M1-exp-log.md and M2-trig.md. These runs only count how often the "
                   "tile does not decide, and that it never decided wrongly in the lanes sampled. The 95% intervals "
                   "are binomial, from the lane count alone."}


# ----------------------------------------------------------- perf-crossings
def _crossing(sw, dev):
    """The element count from which `dev` stays at or below the software's ns, interpolated between the two
    measured sizes on a log-log line; (n, None) where it wins from the smallest shared size, (None, ratio) where
    it never wins (ratio is software over device at the largest shared size)."""
    ns = sorted(set(sw) & set(dev))
    ratio = [(n, sw[n] / dev[n]) for n in ns]
    k = None
    for i in range(len(ratio) - 1, -1, -1):
        if ratio[i][1] >= 1:
            k = i
        else:
            break
    if k is None:
        return None, ratio[-1][1]
    if k == 0:
        return float(ratio[0][0]), None
    (n0, r0), (n1, r1) = ratio[k - 1], ratio[k]
    t = (0 - math.log(r0)) / (math.log(r1) - math.log(r0))
    return math.exp(math.log(n0) + t * (math.log(n1) - math.log(n0))), None


CONFIGS = (("resident", "1", "1 tile, resident"), ("resident", "4", "4 tiles, resident"),
           ("host", "1", "1 tile, over PCIe"), ("host", "4", "4 tiles, over PCIe"))


@figure("perf-crossings", "performance", "How many elements a call needs before the card pays",
        lambda d: "For each format and way of calling the card, the number of elements a call needs before the tile beats "
                  "the fastest real software, for multiply, fused multiply-add and add on two machines: from %s elements "
                  "to never." % K.with_commas(d["lowest"]))
def build_perf_crossings(src, claims):
    sweep = rc.load_sweep(src.path("docs/bench/sweep-x86_64.csv"))
    peers = {"x86-64": rc.load_peers(src.path("docs/bench/peers-x86_64.csv")),
             "arm64": rc.load_peers(src.path("docs/bench/peers-arm64.csv"))}
    cells = []
    for arch in ("x86-64", "arm64"):
        for op in ("mul", "fma", "add"):
            for fmt in FORMATS:
                sw, _who = rc.best_software(peers[arch], fmt, op)
                for path, tiles, label in CONFIGS:
                    dev = sweep.get(("device", path, tiles, fmt, op))
                    if not dev or not sw:
                        continue
                    n, loss = _crossing(sw, dev)
                    cells.append({"arch": arch, "op": op, "format": fmt, "config": label,
                                  "n": None if n is None else int(round(n)),
                                  "never_ratio": None if loss is None else r4(loss)})
    R = "README.md"

    def find(arch, op, fmt, config):
        return next(c for c in cells if (c["arch"], c["op"], c["format"], c["config"]) == (arch, op, fmt, config))
    c256 = find("x86-64", "mul", "fp256", "1 tile, resident")["n"]
    c128 = find("x86-64", "mul", "fp128", "1 tile, resident")["n"]
    pat = r"at about \*\*([\d,]+) elements\*\* for binary256 and \*\*([\d,]+)\*\* for binary128"
    claims.check("fp256-mul-crossing", "one tile resident passes the best software at about this many elements, binary256",
                 R, pat, c256, fmt="%d", group=1, within=0.10)
    claims.check("fp128-mul-crossing", "... and binary128", R, pat, c128, fmt="%d", group=2, within=0.02)
    ratios = []
    for fmt in FORMATS:
        h = sweep[("device", "host", "1", fmt, "mul")]
        r = sweep[("device", "resident", "1", fmt, "mul")]
        ratios.append(h[1048576] / r[1048576])
    ratios.sort()
    med = (ratios[1] + ratios[2]) / 2.0
    claims.check("pcie-over-resident", "staging operands across PCIe costs roughly this many times resident, at a million "
                 "elements (median over the four formats)", R, r"costs roughly (five) times running them", med,
                 fmt="%.2f", within=0.10, note="the README writes the word; five is 5")
    wins = [c["n"] for c in cells if c["n"] is not None]
    return {"cells": cells, "lowest": min(wins), "pcie_ratio": r4(med), "ratios": [r4(x) for x in ratios]}


@build_perf_crossings.drawer
def draw_perf_crossings(theme, d, meta):
    W, H = 900, 612
    p = K.Plot(theme, W, H, meta["title"],
               "Each mark is the size of call, in elements, from which the tile's time per element stays under the fastest "
               "real software's, found between the two measured sizes on a log-log line. Rows are the format and how the "
               "card is called; the cross at the right is a tile that never wins in the measured range.", meta["alt"])
    T = p.T
    opcol = {"mul": T["cats"][0], "fma": T["cats"][1], "add": T["cats"][2]}
    opmark = {"mul": "o", "fma": "d", "add": "s"}
    lo, hi = 100, 1e7
    panels = (("x86-64", "an x86-64 workstation", 24.0), ("arm64", "an M2 Pro laptop", 466.0))
    pw = 410.0
    top = 150.0
    rh = 17.0

    def mark(x, y, kind, col):
        if kind == "o":
            p.circle(x, y, 4.2, col)
        elif kind == "d":
            p.polygon([(x, y - 5.2), (x + 5.2, y), (x, y + 5.2), (x - 5.2, y)], col)
        else:
            p.rect(x - 3.8, y - 3.8, 7.6, 7.6, col)
    for arch, label, px in panels:
        lx0, lx1 = px + 112, px + pw - 40
        X1 = rc.Log(lo, hi, lx0, lx1)
        p.text(px, top - 36, label, size=12, weight="600")
        n_rows = len(FORMATS) * len(CONFIGS)
        span = n_rows * rh + len(FORMATS) * 22
        for dec in K.decades(lo, hi):
            p.line(X1(dec), top - 6, X1(dec), top + span, T["grid"], 1)
            p.text(X1(dec), top + span + 13, K.human(dec), size=10, fill=T["muted"], anchor="middle", mono=True)
        yy = top
        for f in FORMATS:
            p.text(px, yy + 11, FORMAT_LABEL[f], size=11, weight="600")
            yy += 16
            for path, tiles, cfg in CONFIGS:
                p.text(px + 104, yy + 12, cfg, size=9.5, fill=T["muted"], anchor="end")
                for op in ("mul", "fma", "add"):
                    c = next((c for c in d["cells"] if (c["arch"], c["op"], c["format"], c["config"]) == (arch, op, f, cfg)), None)
                    if c is None:
                        continue
                    if c["n"] is None:
                        p.text(lx1 + 4 + {"mul": 0, "fma": 8, "add": 16}[op], yy + 12, "x", size=10, fill=opcol[op],
                               mono=True, weight="600")
                    else:
                        mark(X1(max(c["n"], lo)), yy + 8, opmark[op], opcol[op])
                yy += rh
            yy += 6
        p.text((lx0 + lx1) / 2, yy + 38, "elements per call", size=10.5, fill=T["muted"], anchor="middle")
    ly = p.legend([(opcol["mul"], "multiply (circle)"), (opcol["fma"], "fused multiply-add (diamond)"),
                   (opcol["add"], "add (square)")], 24, 572, 840, size=10.5)
    p.footer([source_line(meta)])
    return p.render()


@build_perf_crossings.captioner
def caption_perf_crossings(d):
    def get(arch, op, fmt, cfg):
        return next(c for c in d["cells"] if (c["arch"], c["op"], c["format"], c["config"]) == (arch, op, fmt, cfg))
    a = get("x86-64", "mul", "fp256", "1 tile, resident")["n"]
    b = get("x86-64", "mul", "fp128", "1 tile, resident")["n"]
    never = sum(1 for c in d["cells"] if c["n"] is None)
    return {"shows": "How big a call has to be. On the workstation one resident tile passes the best software at %s elements "
                     "for binary256 multiply and %s for binary128; staged over PCIe it needs far more or never gets there, "
                     "because the bus costs about %.1fx resident at a million elements (median of the four formats). "
                     "%d of the %d cells never cross in the measured range." % (
                         K.with_commas(a), K.with_commas(b), d["pcie_ratio"], never, len(d["cells"])),
            "not": "The size at which any call breaks even in practice: the sizes are interpolated between measured "
                   "points on two machines, with the baseline the fastest real software at each size, never the "
                   "library's own softfloat; and a crossing near the smallest measured size is a floor."}


# ------------------------------------------------------- the stress run
IMG_COLOR = {"quad": 0, "single": 1, "deep": 2}
LEG_ORDER = ("api-test", "dt-i", "dt-q8", "dt-full", "dt-r", "dt-b", "card-segrun", "seq-check", "acceptance",
             "acceptance-rev8", "resident", "selftest")
# the command each leg runs, as docs/CARDDAY.md's table of legs gives it (checked there by name)
LEG_CMD = {"api-test": "api-test", "dt-i": "device-test -i", "dt-q8": "device-test -q -n 8",
           "dt-full": "device-test -q -n 4096", "dt-r": "device-test -r", "dt-b": "device-test -b -n 4096",
           "card-segrun": "hw/card-segrun.sh", "seq-check": "seq_check.py --trials 250",
           "acceptance": "programs/acceptance.py", "acceptance-rev8": "acceptance.py --set rev8",
           "resident": "cft-resident", "selftest": "cft-selftest vectors/out (every 3rd visit)"}


def clock_ticks(started, total_s):
    """[(seconds from the start, label, major)] at each midnight and noon of the box's clock, from the run's own
    start string; plain integer arithmetic on the strings, so nothing here knows the machine's time zone."""
    h, m, s = (int(x) for x in started[11:19].split(":"))
    sod = h * 3600 + m * 60 + s
    day = K.day_number(started[:10])
    first = 86400 - sod
    out = []
    for j in range(-1, int(total_s // 43200) + 3):
        t = first + j * 43200
        if 0 <= t <= total_s:
            if j % 2 == 0:
                out.append((t, K.day_short(K.day_iso(day + 1 + j // 2)), True))
            else:
                out.append((t, "12:00", False))
    return out


def fmt_seconds(v):
    if v < 10:
        return "%.1f s" % v
    if v < 600:
        return "%.0f s" % v
    return "%.1f min" % (v / 60.0)


def _verdict_sentence(st):
    bad = st["fail"] + st["timeout"] + st["no_device"] + st["parse_error"] + st["error"]
    return "No leg failed." if bad == 0 else "%d legs did not pass." % bad


# --------------------------------------------------------- stress-timeline
@figure("stress-timeline", "reliability", "The card's long run: what ran, and what passed",
        lambda d: "A timeline of the %d cycles of the card's stress run on three images, and a table of the legs run "
                  "on each: %s legs, %s passed, %d skipped by design, none failed." % (
                      d["cycles_n"], K.with_commas(d["legs"]["total"]), K.with_commas(d["legs"]["by_status"]["pass"]),
                      d["legs"]["by_status"]["skipped"]))
def build_stress_timeline(src, claims):
    s = src.extract("stress")
    run, legs = s["run"], s["legs"]
    cardday = src.doc("docs/CARDDAY.md")
    missing = [n for n in LEG_ORDER if ("`%s`" % n) not in cardday and ("`%s`," % n) not in cardday]
    claims.add("legs-named", "each of the run's twelve battery legs is a row of docs/CARDDAY.md's table of legs",
               "docs/CARDDAY.md", "%d of %d" % (len(LEG_ORDER) - len(missing), len(LEG_ORDER)), "all found" if not missing else
               "not named: " + ", ".join(missing), not missing)
    m = re.search(r"default weights quad (\d+), single (\d+),\s+deep (\d+)", cardday)
    w = run["weights"]
    claims.add("weights", "the images' visit weights the run was started with", "docs/CARDDAY.md",
               "quad %d, single %d, deep %d" % (w["quad"], w["single"], w["deep"]),
               ("quad %s, single %s, deep %s" % m.groups()) if m else None,
               bool(m) and (int(m.group(1)), int(m.group(2)), int(m.group(3))) == (w["quad"], w["single"], w["deep"]))
    sweep_by_img = {}
    for it in s["sweep"]["items"]:
        for img, k in it["on"].items():
            sweep_by_img[img] = sweep_by_img.get(img, 0) + k
    ok = sum(sweep_by_img.values()) == legs["sweep"]
    claims.add("sweep-slices", "the sweep slices by image add up to the sweep legs", X.EXTRACT_DIR + "/stress.json",
               str(sum(sweep_by_img.values())), str(legs["sweep"]), ok)
    cs = s["sweep"]["cases"]
    tile_c = cs["tile_exhaustive"] + cs["tile_random"]
    host_c = cs["host_exhaustive"] + cs["host_random"]
    return {"run": run, "legs": legs, "cycles": s["cycles"], "cycles_n": len(s["cycles"]), "matrix": s["matrix"],
            "sweep_slices": sweep_by_img, "images": s["images"], "visits": run["visits"],
            "hours": r4(run["seconds"] / 3600.0), "host_case_share": r4(host_c / float(tile_c + host_c))}


@build_stress_timeline.drawer
def draw_stress_timeline(theme, d, meta):
    W, H = 900, 760
    run = d["run"]
    p = K.Plot(theme, W, H, meta["title"],
               "The card's long run (%s), %s to %s on the box's clock: it cycled through its three images (%s), "
               "weighted %d to %d to %d, and on each visit ran a battery of the card's own tests and then a slice of the "
               "native-oracle sweeps. %s" % (run["id"], run["started"][:16], run["ended"][:16],
                                            ", ".join(d["images"][k]["target"] for k in ("quad", "single", "deep")),
                                            run["weights"]["quad"], run["weights"]["single"], run["weights"]["deep"],
                                            _verdict_sentence(d["legs"]["by_status"])), meta["alt"])
    T = p.T
    st = d["legs"]["by_status"]
    kpis = [(K.with_commas(d["legs"]["total"]), "legs"), (K.with_commas(st["pass"]), "passed"),
            (str(st["skipped"]), "skipped by design"), (str(st["fail"] + st["timeout"] + st["no_device"] + st["parse_error"]
                                                           + st["error"]), "failed, timed out or lost"),
            (str(d["cycles_n"]), "cycles"), ("%.1f" % d["hours"], "hours")]
    kx = 24.0
    for val, lab in kpis:
        p.text(kx, 124, val, size=22, weight="600", mono=True)
        p.text(kx, 141, lab, size=10.5, fill=T["muted"])
        kx += 146
    # the timeline
    x0, x1 = 90.0, 870.0
    total = run["seconds"]
    sx = K.Lin(0, total, x0, x1)
    ty = 172.0
    lane = 24.0
    p.text(24, ty - 8, "cycles, by image: the battery (dark) then the sweep slices (light)", size=11.5, weight="600")
    for (t, lab, major) in clock_ticks(run["started"], total):
        p.line(sx(t), ty, sx(t), ty + 3 * lane + 2, T["grid"] if major else T["pale"], 1)
        p.text(sx(t), ty + 3 * lane + 16, lab, size=9.5, fill=T["muted"], anchor="middle", mono=True)
    for j, img in enumerate(("quad", "single", "deep")):
        y = ty + j * lane
        col = T["cats"][IMG_COLOR[img]]
        p.text(x0 - 8, y + 16, img, size=11, anchor="end", weight="600")
        for c in d["cycles"]:
            if c["image"] != img:
                continue
            p.rect(sx(c["start_s"]), y + 3, max(1.0, sx(c["battery_end_s"]) - sx(c["start_s"])), lane - 7, col)
            p.rect(sx(c["battery_end_s"]), y + 3, max(1.0, sx(c["end_s"]) - sx(c["battery_end_s"])), lane - 7,
                   K.mix(col, T["bg"], 0.55))
    # the table of legs
    cy = ty + 3 * lane + 52
    p.text(24, cy - 10, "legs by image: passed (skipped by design), and the median time of a passing run", size=11.5,
           weight="600")
    cols = {"quad": 262.0, "single": 408.0, "deep": 554.0}
    cwid = 140.0
    for img, cx in cols.items():
        p.text(cx + cwid / 2, cy + 8, "%s (%d visits)" % (img, d["visits"][img]), size=11, weight="600", anchor="middle",
               fill=T["cats"][IMG_COLOR[img]])
    rows = list(LEG_ORDER) + ["sweep"]
    idx = {(m["image"], m["leg"]): m for m in d["matrix"]}
    rh = 22.0
    for r, leg in enumerate(rows):
        y = cy + 16 + r * rh
        p.text(24, y + 15, leg, size=10.5, mono=True, weight="600")
        p.text(704, y + 15, LEG_CMD.get(leg, "slices of the divsqrt and clause-5 soaks"), size=9.5, fill=T["muted"])
        for img, cx in cols.items():
            if leg == "sweep":
                n = d["sweep_slices"].get(img, 0)
                fill = K.mix(T["panel"], T["win"], 0.30)
                p.rect(cx, y + 1, cwid, rh - 3, fill)
                p.text(cx + 8, y + 15, K.with_commas(n), size=10.5, mono=True, weight="600", fill=ink_on(fill, T))
                p.text(cx + cwid - 8, y + 15, "slices", size=9.5, anchor="end", fill=ink_on(fill, T), opacity=0.8)
                continue
            m = idx.get((img, leg))
            if not m:
                continue
            if m["pass"] == 0:
                p.rect(cx, y + 1, cwid, rh - 3, T["pale"])
                p.text(cx + 8, y + 15, "%d skipped" % m["skipped"], size=10, fill=T["muted"], mono=True)
            else:
                fill = K.mix(T["panel"], T["win"], 0.30)
                p.rect(cx, y + 1, cwid, rh - 3, fill)
                p.text(cx + 8, y + 15, str(m["pass"]), size=10.5, mono=True, weight="600", fill=ink_on(fill, T))
                if m["skipped"]:
                    p.text(cx + 44, y + 15, "(+%d)" % m["skipped"], size=9.5, fill=ink_on(fill, T), mono=True, opacity=0.8)
                if m["seconds_median"] is not None:
                    p.text(cx + cwid - 8, y + 15, fmt_seconds(m["seconds_median"]), size=9.5, anchor="end",
                           fill=ink_on(fill, T), mono=True, opacity=0.85)
    ny = cy + 16 + len(rows) * rh + 20
    reasons = {}
    for m in d["matrix"]:
        if m["skipped"]:
            why = re.sub(r"; this is visit \d+$", "", m["skip_reason"] or "no reason recorded")
            reasons.setdefault((m["leg"], why), []).append(m["image"])
    parts = ["%s on %s: %s" % (leg, " and ".join(imgs), why) for (leg, why), imgs in sorted(reasons.items())]
    for k, line in enumerate(K.wrap(
            "The %d skips are by design and each carries its reason in the record - %s. Every other leg ran on every visit "
            "and passed." % (d["legs"]["by_status"]["skipped"], "; ".join(parts)), W - 48, 10.5)):
        p.text(24, ny + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_stress_timeline.captioner
def caption_stress_timeline(d):
    run, st = d["run"], d["legs"]["by_status"]
    return {"shows": "The card's long run, %s: %s legs in %d cycles over %.1f hours, %s passed, %d skipped by design, "
                     "and none failed, timed out, lost the device or failed to parse. It visited the quad %d times, the "
                     "single %d and the deep single %d, against weights of %d, %d and %d. It ended at %s on the box's "
                     "clock; the reason it recorded is %s." % (
                         run["id"], K.with_commas(d["legs"]["total"]), d["cycles_n"], d["hours"],
                         K.with_commas(st["pass"]), st["skipped"], run["visits"]["quad"], run["visits"]["single"],
                         run["visits"]["deep"], run["weights"]["quad"], run["weights"]["single"], run["weights"]["deep"],
                         run["ended"][:16], run["end_reason"]),
            "not": "How hard the card was driven: the legs are short tests and soak slices, and %.0f%% of the sweep's cases "
                   "ran in host code, where the tile does no work (see stress-sweep). Nor that the same card would last longer. "
                   "The times are the box's own clock; the run's commit and the images' digests are in the sidecar." % (
                       100.0 * d["host_case_share"])}


# --------------------------------------------------------- stress-telemetry
@figure("stress-telemetry", "reliability", "What the card drew and how warm it ran",
        lambda d: "Board power and four temperatures at %d samples over %.1f hours: %.1f W on the quad image, %.1f W on "
                  "the single and %.1f W on the deep one at the median, with one sample at %.1f W." % (
                      d["n"], d["hours"], d["by_image"]["quad"]["median"], d["by_image"]["single"]["median"],
                      d["by_image"]["deep"]["median"], d["peak"]["watts"]))
def build_stress_telemetry(src, claims):
    s = src.extract("stress")
    t = s["telemetry"]
    n = len(t["t_s"])
    peak = t["peak"]
    pmin = min(t["power_w"])
    R, B = "README.md", "docs/BENCHMARKS.md"
    claims.check("readme-35w", "the README's power with four tiles streaming", R, r"at about (\d+) watts", peak["watts"],
                 fmt="%.0f", within=0.05, note="'about': the run's highest sample, one in %d, within 5%%" % n)
    claims.check("benchmarks-34-8w", "BENCHMARKS.md: power with four tiles streaming", B, r"(\d+\.\d) W with four",
                 peak["watts"], fmt="%.1f", within=0.05)
    claims.check("benchmarks-idle", "BENCHMARKS.md: power with an image loaded and the tiles idle", B,
                 r"(\d+\.\d) W with an image loaded and the tiles idle", pmin, fmt="%.1f", within=0.05,
                 note="the run's lowest sample, on the single image")
    pat = r"about (\d+) W\s+on\s+the\s+quad,\s+(\d+) W\s+on\s+the\s+single"
    claims.check("readme-quad-22w", "the README's sentence under the throughput table: power on the quad image", R, pat,
                 t["power_by_image"]["quad"]["median"], fmt="%.0f", group=1, within=0.03,
                 note="'about': the median of %d samples" % t["power_by_image"]["quad"]["n"])
    claims.check("readme-single-16w", "... and on the single image", R, pat, t["power_by_image"]["single"]["median"],
                 fmt="%.0f", group=2, within=0.03, note="the median of %d samples" % t["power_by_image"]["single"]["n"])
    return {"t_s": t["t_s"], "image": t["image"], "power_w": t["power_w"], "fpga_c": t["fpga_c"],
            "intvcc_c": t["intvcc_c"], "pcb_front_c": t["pcb_front_c"], "pcb_rear_c": t["pcb_rear_c"],
            "by_image": t["power_by_image"], "by_activity": t["power_by_activity"], "peak": peak,
            "resident_s": [m for m in s["matrix"] if m["image"] == "quad" and m["leg"] == "resident"][0]["seconds_median"],
            "hbm_zero": t["hbm_zero_samples"], "n": n, "run": s["run"], "cycles": s["cycles"],
            "hours": r4(s["run"]["seconds"] / 3600.0)}


@build_stress_telemetry.drawer
def draw_stress_telemetry(theme, d, meta):
    W, H = 900, 760
    run = d["run"]
    p = K.Plot(theme, W, H, meta["title"],
               "The card's own sensors, read by the stress driver every five minutes and between legs: board power above, "
               "and below four temperature sensors, named as the card names them (FPGA, Int Vcc, PCB Top Front, PCB Top "
               "Rear). Shading and colour are the image loaded.", meta["alt"])
    T = p.T
    x0, x1 = 90.0, 818.0
    total = run["seconds"]
    sx = K.Lin(0, total, x0, x1)
    img_col = {k: T["cats"][v] for k, v in IMG_COLOR.items()}
    ay0, ay1 = 146.0, 336.0
    by0, by1 = 398.0, 560.0
    for (y0, y1, label) in ((ay0, ay1, "board power, W"), (by0, by1, "temperature, degrees C")):
        p.text(24, y0 - 10, label, size=11.5, weight="600")
        p.panel(x0, y0, x1, y1)
        for c in d["cycles"]:
            p.rect(sx(c["start_s"]), y0, max(0.8, sx(c["end_s"]) - sx(c["start_s"])), y1 - y0,
                   K.mix(img_col[c["image"]], T["panel"], 0.94))
        for (t, lab, major) in clock_ticks(run["started"], total):
            p.line(sx(t), y0, sx(t), y1, T["grid"] if major else T["pale"], 1)
    YA = K.Lin(10, 40, ay1, ay0)
    for v in (10, 15, 20, 25, 30, 35, 40):
        p.line(x0, YA(v), x1, YA(v), T["grid"], 1)
        p.text(x0 - 7, YA(v) + 3.5, str(v), size=10, fill=T["muted"], anchor="end", mono=True)
    for i, tt in enumerate(d["t_s"]):
        p.circle(sx(tt), YA(d["power_w"][i]), 1.7, img_col[d["image"][i]] if d["image"][i] else T["muted"])
    pk = d["peak"]
    p.line(sx(pk["t_s"]), YA(pk["watts"]) + 4, sx(pk["t_s"]) - 40, YA(pk["watts"]) + 4, T["axis"], 1)
    p.text(sx(pk["t_s"]) - 46, YA(pk["watts"]) + 8, "%.1f W: one sample, during %s on the %s image" % (
        pk["watts"], pk["battery_leg_running"], pk["image"]), size=10, anchor="end", fill=T["fg"])
    for img, y in (("quad", d["by_image"]["quad"]["median"]), ("single", d["by_image"]["single"]["median"]),
                   ("deep", d["by_image"]["deep"]["median"])):
        p.text(x1 + 6, YA(y) + 4 + (-8 if img == "deep" else 8 if img == "single" else 0),
               "%s %.1f" % (img, y), size=9.5, fill=img_col[img], mono=True)
    YB = K.Lin(25, 50, by1, by0)
    for v in (25, 30, 35, 40, 45, 50):
        p.line(x0, YB(v), x1, YB(v), T["grid"], 1)
        p.text(x0 - 7, YB(v) + 3.5, str(v), size=10, fill=T["muted"], anchor="end", mono=True)
    series = (("intvcc_c", "Int Vcc", T["cats"][1]), ("pcb_rear_c", "PCB Top Rear", T["cats"][5]),
              ("pcb_front_c", "PCB Top Front", T["cats"][6]), ("fpga_c", "FPGA", T["cats"][4]))
    for key, lab, col in series:
        p.path([(sx(tt), YB(v)) for tt, v in zip(d["t_s"], d[key]) if v is not None], col, 1.3)
    for (t, lab, major) in clock_ticks(run["started"], total):
        p.text(sx(t), by1 + 15, lab, size=9.5, fill=T["muted"], anchor="middle", mono=True)
    ly = p.legend([(img_col["quad"], "quad image"), (img_col["single"], "single image"), (img_col["deep"], "deep image")],
                  24, ay1 + 34, 500, size=10.5)
    p.legend([(c, l) for _k, l, c in series], 24, by1 + 38, 840, size=10.5, line=True)
    # the median power by what was running
    ty = by1 + 66
    acts = ("between legs", "other battery leg", "sweep, host items only", "sweep, with tile items", "cft-resident leg")
    p.text(24, ty - 8, "median board power (W) by what was running when the sample was taken, and how many samples", size=11.5,
           weight="600")
    colx = [150.0 + k * 150.0 for k in range(len(acts))]
    for a, cx in zip(acts, colx):
        p.text(cx, ty + 10, a, size=9.5, fill=T["muted"], anchor="middle")
    for r, img in enumerate(("quad", "single", "deep")):
        yy = ty + 16 + r * 19
        p.text(24, yy + 12, img, size=10.5, weight="600", fill=img_col[img])
        for a, cx in zip(acts, colx):
            v = d["by_activity"][img].get(a)
            if v:
                p.text(cx, yy + 12, "%.1f  (%d)" % (v["median"], v["n"]), size=10.5, anchor="middle", mono=True)
            else:
                p.text(cx, yy + 12, "-", size=10.5, anchor="middle", mono=True, fill=T["muted"])
    q = d["by_activity"]["quad"]
    ny = ty + 16 + 3 * 19 + 14
    for k, line in enumerate(K.wrap(
            "The image loaded sets the board's power, not the work: on the quad, a sweep slice with tile items running "
            "drew %.1f W at the median against %.1f W with only host items running and %.1f W between legs. Only "
            "cft-resident's streaming leg, about %.0f s a visit, took it to %.1f W (one sample of %s). The card's HBM "
            "temperature sensor read 0 in %s of the %s samples, so it is left out."
            % (q["sweep, with tile items"]["median"], q["sweep, host items only"]["median"], q["between legs"]["median"],
               d["resident_s"], d["peak"]["watts"], K.with_commas(d["n"]), K.with_commas(d["hbm_zero"]),
               K.with_commas(d["n"])),
            W - 48, 10.5)):
        p.text(24, ny + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_stress_telemetry.captioner
def caption_stress_telemetry(d):
    b = d["by_image"]
    ts = [d[k] for k in ("fpga_c", "intvcc_c", "pcb_front_c", "pcb_rear_c")]
    lo = min(min(v for v in s if v is not None) for s in ts)
    hi = max(max(v for v in s if v is not None) for s in ts)
    q = d["by_activity"]["quad"]
    return {"shows": "%d sensor samples over %.1f hours. Board power sits at %.1f W (median) with the quad image loaded, "
                     "%.1f W with the single and %.1f W with the deep one; on the quad it was %.1f W with tile items "
                     "running and %.1f with only host items. The highest sample, %.1f W, is the one taken during "
                     "cft-resident's streaming leg. The four temperatures stay between %.0f and %.0f degrees C." % (
                         d["n"], d["hours"], b["quad"]["median"], b["single"]["median"], b["deep"]["median"],
                         q["sweep, with tile items"]["median"], q["sweep, host items only"]["median"],
                         d["peak"]["watts"], lo, hi),
            "not": "Power at full rate: the README's \"about 35 watts\" is four tiles streaming, which this run sampled "
                   "once, in a leg of about %.0f s; the sweep slices' tile work drew %.1f W. Nor the card's HBM "
                   "temperature (the sensor reads 0 in %d of %d samples)." % (
                       d["resident_s"], q["sweep, with tile items"]["median"], d["hbm_zero"], d["n"])}


# ------------------------------------------------------------ stress-sweep
HOST_FAMILY = {"nextup": "cft_next_", "nextdown": "cft_next_", "logb": "cft_logb", "class": "cft_class",
               "conv": "cft_convert", "cvtfrom": "the integer conversions", "cvtto": "the integer conversions",
               "rem": "cft_rem"}


@figure("stress-sweep", "reliability", "What the sweep covered, and what of it ran on the tile",
        lambda d: "The native-oracle sweep of the stress run: all %d exhaustive items complete, and %s cases in all, of which "
                  "%.1f%% exercised the tile and the rest ran in libcft's host code on the box's CPU; no case disagreed." % (
                      d["exh_complete"], K.with_commas(d["cases_total"]), 100.0 * d["tile_share"]))
def build_stress_sweep(src, claims):
    s = src.extract("stress")
    sw = s["sweep"]
    clause5 = src.doc("host/src/clause5.c")
    divsqrt = src.doc("host/tools/divsqrt_soak.c")
    # the classification is read from the code, not believed: see figure_extracts.STRESS_TILE_OPS. The header
    # comment is read with its leading asterisks and line breaks taken out.
    flat = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*\*", " ", clause5))
    comp = re.search(r"COMPOSED - cft_rint, cft_scaleb, cft_cmp_sig\.", flat)
    host = re.search(r"HOST - cft_convert, the integer conversions, cft_logb, cft_next_\*, cft_class, "
                     r"cft_total_order\*, cft_rem\.", flat)
    runs = len(re.findall(r"\bcft_run\(dev", clause5))
    claims.add("composed-ops", "host/src/clause5.c: the composed (on the tile) clause-5 operations are rint and scaleb",
               "host/src/clause5.c", "rint, scaleb", "COMPOSED - cft_rint, cft_scaleb, cft_cmp_sig" if comp else None,
               bool(comp))
    bad = [op for op in sw["host_ops"] if HOST_FAMILY.get(re.match(r"[a-z]+", op).group(0)) is None
           or HOST_FAMILY[re.match(r"[a-z]+", op).group(0)] not in (host.group(0) if host else "")]
    claims.add("host-ops", "host/src/clause5.c: every other swept operation is HOST - no floating-point pass, the device "
               "is context", "host/src/clause5.c", "%d host ops" % len(sw["host_ops"]),
               "HOST - cft_convert, the integer conversions, cft_logb, cft_next_*, cft_class, cft_total_order*, cft_rem"
               if host else None, bool(host) and not bad)
    claims.add("two-passes", "host/src/clause5.c issues cft_run() from exactly two places (rint and scaleb)",
               "host/src/clause5.c", "2", str(runs), runs == 2)
    div = ("cft_div(dev" in divsqrt) and ("cft_sqrt(dev" in divsqrt)
    claims.add("divsqrt-tile", "host/tools/divsqrt_soak.c calls cft_div and cft_sqrt, which compose from the tile's opcodes",
               "host/tools/divsqrt_soak.c", "div32, div64, sqrt32, sqrt64", "cft_div(dev ... cft_sqrt(dev" if div else None, div)
    sq = sum(c for it in sw["items"] if it["op"] == "sqrt32" for c in [it["cases"]])
    claims.check("readme-sqrt32", "exhaustive binary32 square root under every attribute, billions of cases (the "
                 "README states the same sum for the earlier soaks)", "README.md",
                 r"exhaustive binary32 square root\s+under every attribute is (\d+\.\d+) billion", sq / 1e9, fmt="%.2f")
    # the items
    exh = [it for it in sw["items"] if it["kind"] == "exhaustive"]
    complete = [it["item"] for it in exh if sw["coverage"][it["item"]][-1][1] == sw["encodings_per_item"]]
    cases = sw["cases"]
    tile = cases["tile_exhaustive"] + cases["tile_random"]
    host_c = cases["host_exhaustive"] + cases["host_random"]
    return {"items": sw["items"], "coverage": sw["coverage"], "enc": sw["encodings_per_item"],
            "hours": sw["cumulative_hours"], "cum": sw["cumulative_cases"], "rates": sw["rates"],
            "tile_ops": sw["tile_ops"], "host_ops": sw["host_ops"], "cases": cases, "cases_total": tile + host_c,
            "tile_cases": tile, "host_cases": host_c, "tile_share": r4(tile / float(tile + host_c)),
            "exh_complete": len(complete), "exh_total": len(exh), "mismatches": sw["mismatches"],
            "run": s["run"], "tile_exh_items": len([i for i in exh if i["unit"] == "tile"]),
            "host_exh_items": len([i for i in exh if i["unit"] == "host"]),
            "tile_random_items": len([i for i in sw["items"] if i["kind"] == "random" and i["unit"] == "tile"]),
            "host_random_items": len([i for i in sw["items"] if i["kind"] == "random" and i["unit"] == "host"])}


@build_stress_sweep.drawer
def draw_stress_sweep(theme, d, meta):
    W, H = 900, 1030
    run = d["run"]
    p = K.Plot(theme, W, H, meta["title"],
               "Only some sweep operations exercise the card's tile: divide and square root, roundToIntegral and scaleB, which "
               "libcft composes from the tile's opcodes. The rest - nextUp, nextDown, logB, class, the conversions, remainder - "
               "run in libcft's host code on the box's CPU, and the tile does no work for them. Every figure below keeps the two apart.",
               meta["alt"])
    T = p.T
    total = run["seconds"]
    tile_col, host_col = T["cats"][0], T["cats"][1]
    # panel A: coverage of the exhaustive items
    ax0, ax1, ay0, ay1 = 74.0, 440.0, 176.0, 380.0
    last_s = max(pts[-1][0] for pts in d["coverage"].values())
    span = int(math.ceil(last_s / 3600.0 * 1.08))
    sx = K.Lin(0, span * 3600.0, ax0, ax1)
    sy = K.Lin(0, 100, ay1, ay0)
    p.text(24, ay0 - 14, "the %d exhaustive items, each all 2^32 encodings: share covered, by hour" % len(d["coverage"]),
           size=11.5, weight="600")
    p.panel(ax0, ay0, ax1, ay1)
    for v in (0, 25, 50, 75, 100):
        p.line(ax0, sy(v), ax1, sy(v), T["grid"], 1)
        p.text(ax0 - 6, sy(v) + 3.5, "%d%%" % v, size=10, fill=T["muted"], anchor="end", mono=True)
    for h in range(0, span + 1, 2):
        p.line(sx(h * 3600.0), ay0, sx(h * 3600.0), ay1, T["pale"], 1)
        p.text(sx(h * 3600.0), ay1 + 14, "%dh" % h, size=9.5, fill=T["muted"], anchor="middle", mono=True)
    p.text(ax1 - 8, sy(6), "all complete by %.1f h" % (last_s / 3600.0), size=10, anchor="end", fill=T["fg"],
           weight="600")
    fam = {}
    for it in d["items"]:
        if it["kind"] == "exhaustive":
            fam.setdefault(it["op"], []).append(it["item"])
    famcol = {"sqrt32": T["cats"][0], "rint32": T["cats"][3]}
    for op, names in sorted(fam.items()):
        for k, nm in enumerate(names):
            unit = "tile" if op in d["tile_ops"] else "host"
            col = famcol.get(op, host_col if unit == "host" else tile_col)
            if unit == "host":
                col = T["cats"][1] if k % 2 == 0 else T["cats"][5]
            pts = [(0.0, 0.0)] + [(sx(t), sy(100.0 * cv / d["enc"])) for t, cv in d["coverage"][nm]]
            pts[0] = (sx(0), sy(0))
            p.path(pts, K.mix(col, T["bg"], 0.0 if unit == "tile" else 0.0), 1.5 if unit == "tile" else 1.8,
                   dash=None if unit == "tile" else "5 3", opacity=0.85)
    p.legend([(T["cats"][0], "sqrt32, five attributes (tile)"), (T["cats"][3], "rint32, five attributes (tile)"),
              (T["cats"][1], "nextup32, logb32 (host)", "dash"), (T["cats"][5], "nextdown32, class32 (host)", "dash")],
             24, ay1 + 36, 440, size=10, line=True)
    # panel B: cumulative cases
    bx0, bx1 = 524.0, 850.0
    sx2 = K.Lin(0, d["hours"][-1], bx0, bx1)
    top = max(d["cum"]["tile"][-1], d["cum"]["host"][-1]) * 1.12
    ticks = K.nice_ticks(0, top, 5)
    sy2 = K.Lin(0, ticks[-1], ay1, ay0)
    p.text(480, ay0 - 14, "cases checked against the CPU's own answers, cumulative", size=11.5, weight="600")
    p.panel(bx0, ay0, bx1, ay1)
    for v in ticks:
        p.line(bx0, sy2(v), bx1, sy2(v), T["grid"], 1)
        p.text(bx0 - 6, sy2(v) + 3.5, K.kmg(v), size=10, fill=T["muted"], anchor="end", mono=True)
    for h in range(0, int(d["hours"][-1]) + 1, 12):
        p.line(sx2(h), ay0, sx2(h), ay1, T["pale"], 1)
        p.text(sx2(h), ay1 + 14, "%dh" % h, size=9.5, fill=T["muted"], anchor="middle", mono=True)
    p.path([(sx2(h), sy2(v)) for h, v in zip(d["hours"], d["cum"]["host"])], host_col, 2.2, dash="5 3")
    p.path([(sx2(h), sy2(v)) for h, v in zip(d["hours"], d["cum"]["tile"])], tile_col, 2.6)
    p.text(bx1 - 4, sy2(d["cum"]["tile"][-1]) - 8, "tile items %s (%.1f%%)" % (
        K.kmg(d["tile_cases"]), 100 * d["tile_share"]), size=10.5, anchor="end", fill=tile_col, weight="600")
    p.text(bx1 - 4, sy2(d["cum"]["host"][-1]) - 8, "host items %s (%.1f%%)" % (
        K.kmg(d["host_cases"]), 100 * (1 - d["tile_share"])), size=10.5, anchor="end", fill=host_col, weight="600")
    p.text(bx0, ay1 + 34, "hours into the run", size=10, fill=T["muted"])
    # panel C: rates by op
    cy0 = 470.0
    ops = [op for op in ("sqrt32", "div32", "div64", "sqrt64", "rint32", "rint64", "scaleb32", "scaleb64")
           if any(r["op"] == op for r in d["rates"])] + sorted(op for op in d["host_ops"])
    rx0, rx1 = 150.0, 720.0
    rates = [r["median"] for r in d["rates"]]
    rlo, rhi = 10 ** math.floor(math.log10(min(rates))), 10 ** math.ceil(math.log10(max(rates)))
    X1 = rc.Log(rlo * 3, rhi / 3.0, rx0, rx1)
    p.text(24, cy0 - 14, "slice rate by operation: cases per second a job, median, by image", size=11.5, weight="600")
    rh = 15.0
    nrows = len(ops)
    for dec in K.decades(rlo * 3, rhi / 3.0):
        p.line(X1(dec), cy0, X1(dec), cy0 + nrows * rh + 8, T["grid"], 1)
        p.text(X1(dec), cy0 + nrows * rh + 22, K.human(dec), size=10, fill=T["muted"], anchor="middle", mono=True)
    icol = {"quad": T["cats"][0], "single": T["cats"][1], "deep": T["cats"][2]}
    for i, op in enumerate(ops):
        y = cy0 + i * rh + (8 if op in d["host_ops"] else 0)
        unit_col = tile_col if op in d["tile_ops"] else host_col
        p.text(24, y + 11, op, size=10, mono=True, fill=unit_col, weight="600")
        for r in d["rates"]:
            if r["op"] == op:
                p.circle(X1(r["median"]), y + 7, 3.6, icol[r["image"]])
    p.text(24, cy0 + 8 * rh + 3, "", size=1)
    p.text(rx1 + 20, cy0 + 12, "tile items", size=10, fill=tile_col, weight="600")
    p.text(rx1 + 20, cy0 + 8 * rh + 8 + 12, "host items", size=10, fill=host_col, weight="600")
    p.legend([(icol["quad"], "quad (a job a tile, four at once)"), (icol["single"], "single"), (icol["deep"], "deep")],
             rx0, cy0 + nrows * rh + 40, 700, size=10)
    ny = cy0 + nrows * rh + 72
    for k, line in enumerate(K.wrap(
            "%s of the %s exhaustive items finished: %s encodings, %d x 2^32 through the tile (sqrt32 and rint32, five "
            "attributes each) and %d x 2^32 in host code (nextup32, nextdown32, logb32, class32). The random items split the "
            "same way, %d on the tile and %d in host code. %d cases disagreed, tile or host. A 'case' is what each tool's "
            "verdict counts, so one input can be several cases (the conversions)."
            % (d["exh_complete"], d["exh_total"], K.with_commas(d["exh_total"] * d["enc"]), d["tile_exh_items"],
               d["host_exh_items"], d["tile_random_items"], d["host_random_items"], d["mismatches"]), W - 48, 10.5)):
        p.text(24, ny + 15 * k, line, size=10.5, fill=T["muted"])
    p.footer([source_line(meta)])
    return p.render()


@build_stress_sweep.captioner
def caption_stress_sweep(d):
    c = d["cases"]
    return {"shows": "The stress run's sweep: %s cases in all, %s (%.1f%%) from items that exercise the tile (divide, square "
                     "root, roundToIntegral, scaleB: %s exhaustive and %s random) and %s from items that run in libcft's host "
                     "code on the box's CPU. All %d exhaustive items covered every one of their 2^32 "
                     "encodings, %d through the tile and %d in host code; %d cases disagreed with the oracle." % (
                         K.with_commas(d["cases_total"]), K.with_commas(d["tile_cases"]), 100.0 * d["tile_share"],
                         K.with_commas(c["tile_exhaustive"]), K.with_commas(c["tile_random"]), K.with_commas(d["host_cases"]),
                         d["exh_total"], d["tile_exh_items"], d["host_exh_items"], d["mismatches"]),
            "not": "A total of cases \"on the card\". The sweep's total is the sum of two kinds of item and only the "
                   "tile items exercise the card, so the figure gives both numbers and never calls the sum \"on the "
                   "card\". The host items test libcft's host code against the CPU's own answers, and the tile does no "
                   "work for them. The split is read from host/src/clause5.c and host/tools/divsqrt_soak.c on every "
                   "check.",
            "notes": []}


# ======================================================================
#                   assembly, outputs, the check and its controls
# ======================================================================
LEAK = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]|/home/[A-Za-z]|/Users/[A-Za-z]|\\Users\\")


class Result:
    def __init__(self, fig, data, meta, claims, src):
        self.fig, self.data, self.meta, self.claims, self.src = fig, data, meta, claims, src
        self.svgs = {t: fig.draw(t, data, meta) for t in K.THEME_NAMES}

    def sidecar(self):
        return {"figure": self.fig.name, "title": self.fig.title, "group": self.fig.group,
                "alt": self.meta["alt"],
                "files": ["%s/%s-%s.svg" % (FIG_DIR, self.fig.name, t) for t in K.THEME_NAMES],
                "maker": "%s: build_%s, draw_%s" % (SELF, self.fig.name.replace("-", "_"),
                                                    self.fig.name.replace("-", "_")),
                "commit": X.BASE_COMMIT,
                "commit_means": "the commit the extracts below were read at; a file read from the tree is "
                                "identified by its SHA-256 instead",
                "sources": self.meta["files"], "extracts": self.meta["extracts"],
                "checks": self.claims.rows, "data": self.data}


def build_all(root, only=None):
    results = []
    for fig in FIGS:
        if only and fig.name not in only:
            continue
        src, claims = Src(root), None
        claims = Claims(src, fig.name)
        data = fig.build(src, claims)
        meta = {"title": fig.title, "alt": fig.alt_text(data), "files": src.sources(),
                "extracts": src.extract_records()}
        results.append(Result(fig, data, meta, claims, src))
    return results


def md_wrap(text, width=100):
    """Prose wrapped for the repository's hard-wrapped Markdown; words are never split."""
    import textwrap
    return textwrap.fill(" ".join(text.split()), width=width, break_long_words=False, break_on_hyphens=False)


GALLERY_INTRO = (
    "Every figure here is drawn by `python/project_figures.py` from committed data: files already in the tree, or a "
    "small extract (`docs/figures/`) that records the commit it was read at, the SHA-256 of what it was made from and the "
    "command that remakes it. Beside each figure is a sidecar (`docs/img/figures/<name>.json`) holding every number drawn, "
    "the digest of every source and the cross-checks that were run. **This page is written by the same script**, so a "
    "number in a caption is the number in the figure.",
    "`python python/project_figures.py --check`, which is the `generated` stage's seventh generator in `verify/run.sh`, "
    "remakes everything in memory and fails by name on a figure, sidecar or caption that differs from a fresh generation, "
    "on an extract whose digests no longer hold, and on a number that the README or another document states and a "
    "figure disagrees with. It reads no git history, no network and no card, and then plants each of those faults in a "
    "scratch copy to show that it would catch it.",
    "Each figure is a `<picture>`, so GitHub shows the reader's theme. The rules are `python/readme_charts.py`'s: literal "
    "geometry and colour only, no fonts, scripts or CSS variables. The README's own two charts (`docs/img/bench/`) are not "
    "repeated here.")


GALLERY_LIMITS = (
    "A figure of the current state (the benchmark sweeps, the layout generator, the formats, the design studies' captured "
    "runs, the runner's stage list) is read from the tree every time, so it fails the check the moment the tree moves.",
    "A figure of history reads an extract pinned to a commit and says so on its face; it lags the project until someone "
    "with the full history remakes it (`python python/figure_extracts.py history`, `tree`, `ledger`), and `--check` prints "
    "a note, and does not fail, when the gate's own files have moved past it.",
    "`python python/figure_extracts.py --verify` remakes every extract from its source and compares the bytes: it needs "
    "the full git history, and for the stress run the raw `metrics.jsonl`, which is 8 MB and is never committed.",
    "A number the record states in words is held to the figure by a pattern; reword the sentence and the check says "
    "that the statement is gone, by name, rather than passing.")


def gallery_text(results):
    out = ["# Figures of the project, made by script from its own data", ""]
    for para in GALLERY_INTRO:
        out += [md_wrap(para), ""]
    by = {}
    for r in results:
        by.setdefault(r.fig.group, []).append(r)
    out.append("| figure | what it answers |")
    out.append("|---|---|")
    for gid, gname in GROUPS:
        for r in by.get(gid, []):
            out.append("| [%s](#%s) | %s |" % (r.fig.name, r.fig.name, r.fig.title))
    out.append("")
    extracts = {}
    for gid, gname in GROUPS:
        if gid not in by:
            continue
        out += ["## %s" % gname, ""]
        for r in by[gid]:
            cap = r.fig.caption(r.data)
            out += ['<a id="%s"></a>' % r.fig.name, "### %s" % r.fig.title, "", "<picture>",
                    '  <source media="(prefers-color-scheme: dark)" srcset="img/figures/%s-dark.svg">' % r.fig.name,
                    '  <img alt="%s" src="img/figures/%s-light.svg">' % (K.esc(r.meta["alt"]), r.fig.name),
                    "</picture>", ""]
            out += [md_wrap("**Shows.** %s" % cap["shows"]), ""]
            out += [md_wrap("**Does not show.** %s" % cap["not"]), ""]
            srcs = ["`%s`%s" % (f["path"], " (%s)" % f["reads"] if "reads" in f else "") for f in r.meta["files"]]
            for e in r.meta["extracts"]:
                srcs.append("`%s` (%s)" % (e["path"], e["label"]))
                extracts[e["name"]] = e
            if len(srcs) > 6:
                srcs = srcs[:5] + ["and %d more, all listed in the sidecar" % (len(srcs) - 5)]
            out += [md_wrap("**Source.** %s. Remade by `python python/project_figures.py --only %s --write`; the "
                            "numbers and digests are in `docs/img/figures/%s.json`." % (", ".join(srcs), r.fig.name, r.fig.name)),
                    ""]
            if r.claims.rows:
                agree = [c for c in r.claims.rows if c["verdict"] == "agrees"]
                bad = [c for c in r.claims.rows if c["verdict"] != "agrees"]
                per = {}
                for c in r.claims.rows:
                    per[c["document"]] = per.get(c["document"], 0) + 1
                where = ", ".join("`%s` (%d)" % (k, per[k]) for k in sorted(per))
                line = ("**Held to the record.** %d statement%s checked against this figure on every run, %d agree: %s." % (
                    len(r.claims.rows), " is" if len(r.claims.rows) == 1 else "s are", len(agree), where))
                if bad:
                    line += " **%d do not**, and are reported: %s." % (len(bad), "; ".join(
                        "%s says %s where the data gives %s (%s)" % (c["document"], c["stated"], c["drawn"],
                                                                      c.get("reported", "not found")) for c in bad))
                out += [md_wrap(line), ""]
            for note in cap.get("notes", []):
                out += [md_wrap(note), ""]
    out += ["## Where the extracts come from", "",
            "| extract | what it is | read at | remake |", "|---|---|---|---|"]
    for name in sorted(extracts):
        e = extracts[name]
        out.append("| `%s` | %s | %s | `%s` |" % (e["path"], e["what"], e["label"], e["remake"]))
    out += ["", "## What the check does and does not do", ""]
    for para in GALLERY_LIMITS:
        out += ["- " + md_wrap(para, 96).replace("\n", "\n  "), ""]
    return "\n".join(out).rstrip("\n") + "\n"



def outputs(results):
    """{relative path: text}: every file this script owns."""
    out = {}
    for r in results:
        for t in K.THEME_NAMES:
            out["%s/%s-%s.svg" % (FIG_DIR, r.fig.name, t)] = r.svgs[t]
        out["%s/%s.json" % (FIG_DIR, r.fig.name)] = X.dumps(r.sidecar())
    out[GALLERY] = gallery_text(results)
    return out


def owned_on_disk(root):
    """The figure files present under docs/img/figures/."""
    d = pathlib.Path(root) / FIG_DIR
    if not d.is_dir():
        return []
    return sorted("%s/%s" % (FIG_DIR, p.name) for p in d.iterdir()
                  if p.is_file() and (p.name.endswith("-light.svg") or p.name.endswith("-dark.svg")
                                      or p.name.endswith(".json")))


# What GitHub's SVG handling lets through, as python/readme_charts.py's header states it: literal geometry and
# colour, no fonts, scripts or CSS variables. Held to the generated text of every figure, not to a reviewer's eye.
SVG_ELEMENTS = {"svg", "title", "rect", "line", "path", "polygon", "circle", "text"}
SVG_ATTRS = {"xmlns", "width", "height", "viewBox", "role", "aria-label", "x", "y", "x1", "y1", "x2", "y2", "cx", "cy", "r",
             "rx", "d", "points", "fill", "stroke", "stroke-width", "stroke-dasharray", "stroke-linejoin", "opacity",
             "font-family", "font-size", "font-weight", "text-anchor", "transform"}


def svg_lint(text):
    """The reasons an SVG would not survive GitHub's sanitising, or []: an element or attribute outside the
    small set above, a colour that is not a literal hex or none, a font that is not one of the two stacks
    python/readme_charts.py uses, a transform that is not a rotation, any style, class, link or event handler."""
    out = []
    for m in re.finditer(r"<(/?)([A-Za-z][\w:-]*)([^>]*?)/?>", text):
        closing, name, attrs = m.group(1), m.group(2), m.group(3)
        if closing:
            continue
        if name not in SVG_ELEMENTS:
            out.append("element <%s>" % name)
            continue
        for a in re.finditer(r'([A-Za-z_:][\w:.-]*)="([^"]*)"', attrs):
            k, v = a.group(1), a.group(2)
            if k not in SVG_ATTRS:
                out.append("attribute %s on <%s>" % (k, name))
            elif k in ("fill", "stroke") and not re.fullmatch(r"#[0-9a-f]{6}|none", v):
                out.append("%s=%r is not a literal colour" % (k, v))
            elif k == "font-family" and v not in (K.FONT, K.MONO):
                out.append("font-family %r is not one of the two stacks" % v)
            elif k == "transform" and not re.fullmatch(r"rotate\(-?[\d.]+ -?[\d.]+ -?[\d.]+\)", v):
                out.append("transform %r is not a rotation" % v)
            elif k == "xmlns" and v != "http://www.w3.org/2000/svg":
                out.append("xmlns %r" % v)
    if re.search(r"(?i)javascript:|url\(|var\(|@import|<!\[CDATA|&#x?[0-9a-f]+;[^<]{0,0}<script", text):
        out.append("a script, url() or var() reference")
    return sorted(set(out))


def check_tree(root, only=None):
    """(problems, notes, results) for the tree at `root`. Reads no git."""
    root = pathlib.Path(root)
    problems, notes = [], []
    # 1. the extracts: each parses, holds to its own digest and, where its source is here, to that
    names = sorted(p.stem for p in (root / X.EXTRACT_DIR).glob("*.json")) if (root / X.EXTRACT_DIR).is_dir() else []
    for name in names:
        try:
            ex = X.load(root, name)
        except X.ExtractError as e:
            problems.append(str(e))
            continue
        pr, nt = X.source_problems(root, ex)
        problems += pr
        notes += nt
    # 2. the figures
    try:
        results = build_all(root, only)
    except (X.ExtractError, KeyError) as e:
        problems.append("a figure could not be built: %s" % e)
        return problems, notes, []
    read = set()
    for r in results:
        read.update(r.src.extracts)
    if not only:
        for name in names:
            if name not in read:
                problems.append("extract %s is read by no figure (remove it, or draw it)" % name)
    for r in results:
        if getattr(r.fig, "fresh", None):
            notes += r.fig.fresh(r.src, r.data)
    outs = outputs(results)
    for rel in sorted(outs):
        if only and not any(rel.startswith("%s/%s" % (FIG_DIR, n)) for n in only):
            continue
        fig = rel.rsplit("/", 1)[-1]
        p = root / rel
        who = fig.rsplit("-", 1)[0] if rel.endswith(".svg") else fig[:-5] if rel.endswith(".json") else "gallery"
        if rel == GALLERY:
            who = "gallery"
        if not p.is_file():
            problems.append("figure %s: %s is missing; remake with: python python/project_figures.py --write"
                            % (who, rel))
        elif p.read_bytes() != outs[rel].encode("utf-8"):
            problems.append("STALE figure %s: %s differs from a fresh generation; remake with: "
                            "python python/project_figures.py --write" % (who, rel))
        if rel.endswith(".svg") and svg_lint(outs[rel]):
            problems.append("figure %s: %s would not survive GitHub's SVG handling: %s" % (
                who, rel, "; ".join(svg_lint(outs[rel])[:4])))
        if LEAK.search(outs[rel]):
            problems.append("figure %s: %s would carry a personal path (%s)" % (who, rel, LEAK.search(outs[rel]).group(0)))
    if not only:
        made = set(outs)
        for rel in owned_on_disk(root):
            if rel not in made:
                problems.append("%s is made by no figure of %s (remove it, or add the figure)" % (rel, SELF))
    for r in results:
        for c in r.claims.rows:
            if c["verdict"] in ("disagrees", "not found"):
                what = ("states %s" % c["stated"]) if c["stated"] is not None else "no longer states it"
                problems.append("figure %s: the record disagrees with it, claim %s: %s %s where the data gives %s"
                                % (r.fig.name, c["id"], c["document"], what, c["drawn"]))
    return problems, notes, results


# ------------------------------------------------------------------ controls
def _flip(text, find, repl):
    assert find in text, find
    return text.replace(find, repl, 1)


def controls(root, results):
    """Plant each fault in a scratch copy and require the check to name it.

    Returns (failures, report): a failure is a plant the check did not catch, or a scratch copy that does not
    reproduce the real tree's own clean verdict; the report is one line a plant, with the problem that named it."""
    root = pathlib.Path(root)
    failures, report = [], []
    need = set()
    for r in results:
        need.update(r.src.needed())
    outs = outputs(results)
    need.update(outs)
    for p in (root / X.EXTRACT_DIR).glob("*.json"):
        need.add(X.EXTRACT_DIR + "/" + p.name)
        for s_ in json.loads(p.read_text(encoding="utf-8"))["sources"]:       # a source that is a file here
            if s_.get("kind") in ("file", "file-prefix"):
                need.add(s_["path"])
    with tempfile.TemporaryDirectory(prefix="project_figures-") as tmp:
        t = pathlib.Path(tmp)
        for rel in sorted(need):
            if (root / rel).is_file():
                (t / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / rel, t / rel)
        base, _, _ = check_tree(t)
        if base:
            return (["the scratch copy does not reproduce the tree's own verdict, so no control below proves "
                     "anything: %s" % base[0]], report)
        first = results[0].fig.name
        side = next((r for r in results if r.claims.rows), results[0])

        def mutated(mutate, only):
            """The check's problems on the scratch copy with `mutate`'s change in it, the copy then restored."""
            saved = {}
            try:
                for rel, new in mutate(t).items():
                    p = t / rel
                    saved[rel] = p.read_bytes() if p.exists() else None
                    if new is None:
                        if p.exists():
                            p.unlink()
                    else:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(new if isinstance(new, bytes) else new.encode("utf-8"))
                got, _, _ = check_tree(t, only)
            finally:
                for rel, old in saved.items():
                    p = t / rel
                    if old is None:
                        if p.exists():
                            p.unlink()
                    else:
                        p.write_bytes(old)
            return got

        def plant(label, mutate, pattern, only=None):
            got = mutated(mutate, only)
            hit = next((g for g in got if re.search(pattern, g)), None)
            if hit is None:
                failures.append("NEGATIVE CONTROL FAILED TO FAIL: %s; wanted /%s/, got %s" % (
                    label, pattern, got or "no problem at all"))
            else:
                report.append("%s -> %s" % (label, hit[:150]))

        def stay(label, mutate, only=None):
            """The converse of a plant: a change to a file that the figure reads only in part, outside the part
            it reads, must move nothing - a check that failed on it would fail for nothing, on every round."""
            got = mutated(mutate, only)
            if got:
                failures.append("CONTROL FAILED: %s moved a figure that does not read it: %s" % (label, got[0][:150]))
            else:
                report.append("%s -> no problem, as it should be (not counted as a fault)" % label)

        svg_rel = "%s/%s-light.svg" % (FIG_DIR, first)
        side_rel = "%s/%s.json" % (FIG_DIR, side.fig.name)
        # the brief's four, in its order
        plant("a committed SVG changed by one byte",
              lambda t: {svg_rel: _one_byte((t / svg_rel).read_bytes())},
              r"^STALE figure %s: %s differs from a fresh generation" % (re.escape(first), re.escape(svg_rel)),
              only=[first])
        names = sorted(read_extract_names(results))
        for name in names[:1]:
            rel = "%s/%s.json" % (X.EXTRACT_DIR, name)
            plant("an extract's data edited by hand",
                  lambda t, rel=rel: {rel: _edit_extract_data(t / rel)},
                  r"^extract %s: its data no longer matches its recorded body_sha256" % re.escape(name))
        plant("a sidecar changed",
              lambda t: {side_rel: _flip((t / side_rel).read_text(encoding="utf-8"), '"drawn": "', '"drawn": "9')},
              r"^STALE figure %s: %s differs from a fresh generation" % (re.escape(side.fig.name), re.escape(side_rel)),
              only=[side.fig.name])
        for name in names:
            ex = X.load(t, name)
            srcs = [s for s in ex["sources"] if s.get("kind") in ("file", "file-prefix")]
            if srcs:
                s = srcs[0]
                rel = "%s/%s.json" % (X.EXTRACT_DIR, name)
                plant("an extract's source, which is present, edited: its recorded digest no longer matches",
                      lambda t, s=s: {s["path"]: _bump_digit(
                          (t / s["path"]).read_bytes(), min(s.get("bytes", 10 ** 9), 10 ** 9) // 2)},
                      r"^extract %s: its recorded source digest no longer matches" % re.escape(name))
                plant("an extract's recorded source digest edited, its own digest made to agree",
                      lambda t, rel=rel: {rel: _edit_extract_source_digest(t / rel)},
                      r"^extract %s: its recorded source digest no longer matches" % re.escape(name))
                break
        # and the rest of what the check claims to catch
        plant("a committed SVG deleted", lambda t: {svg_rel: None},
              r"^figure %s: %s is missing" % (re.escape(first), re.escape(svg_rel)), only=[first])
        plant("an SVG no figure makes", lambda t: {FIG_DIR + "/ghost-light.svg": "<svg/>\n"},
              r"^%s/ghost-light\.svg is made by no figure" % re.escape(FIG_DIR))
        plant("the gallery changed", lambda t: {GALLERY: (t / GALLERY).read_text(encoding="utf-8") + "\nedited\n"},
              r"^STALE figure gallery: %s differs from a fresh generation" % re.escape(GALLERY))
        plant("an extract no figure reads",
              lambda t: {X.EXTRACT_DIR + "/ghost.json": _ghost_extract(t)},
              r"^extract ghost is read by no figure")
        for r in results:
            files = [f["path"] for f in r.meta["files"] if f["path"].startswith("docs/bench/")]
            if files:
                plant("a file a figure reads, edited by one digit",
                      lambda t, f=files[0]: {f: _bump_digit((t / f).read_bytes(), len((t / f).read_bytes()) // 2)},
                      r"^STALE figure %s: " % re.escape(r.fig.name), only=[r.fig.name])
                break
        for r in results:
            ok = [c for c in r.claims.rows if c["verdict"] == "agrees" and c["document"] == "README.md"
                  and re.fullmatch(r"\d+\.\d", c["stated"] or "")]
            if ok:
                c = ok[0]
                plant("a number the record states, changed",
                      lambda t, c=c: {c["document"]: _change_stated(t / c["document"], c)},
                      r"^figure %s: the record disagrees with it, claim %s:" % (re.escape(r.fig.name), re.escape(c["id"])),
                      only=[r.fig.name])
                plant("a statement the record made, removed",
                      lambda t, c=c: {c["document"]: _remove_stated(t / c["document"], c)},
                      r"^figure %s: the record disagrees with it, claim %s: .* no longer states it"
                      % (re.escape(r.fig.name), re.escape(c["id"])), only=[r.fig.name])
                break
        # a figure that reads only part of a file that changes with most rounds: what it reads is held, the rest is not
        run_rel = "verify/run.sh"
        if any(r.fig.name == "verify-stages" for r in results):
            plant("a stage added to the runner's list",
                  lambda t: {run_rel: (t / run_rel).read_text(encoding="utf-8")
                             + '\nstage zz-control "a stage that is not there" -- do_zz\n'},
                  r"^STALE figure verify-stages: ", only=["verify-stages"])
            stay("a comment added to the runner, outside what the stage figure reads",
                 lambda t: {run_rel: (t / run_rel).read_text(encoding="utf-8") + "\n# a comment, which no figure reads\n"},
                 only=["verify-stages"])
        # the lint can fail: an SVG that carries a script, a style, a CSS variable, an external font or an image
        for label, bad_svg, want in (
                ("an SVG with a script", '<svg xmlns="http://www.w3.org/2000/svg"><script>x()</script></svg>', "element <script>"),
                ("an SVG with a style attribute", '<svg xmlns="http://www.w3.org/2000/svg"><rect style="fill:red"/></svg>',
                 "attribute style"),
                ("an SVG with a CSS variable for a colour", '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="var(--c)"/></svg>',
                 "not a literal colour"),
                ("an SVG with an external font", '<svg xmlns="http://www.w3.org/2000/svg"><text font-family="Inter">a</text></svg>',
                 "font-family"),
                ("an SVG with an embedded image", '<svg xmlns="http://www.w3.org/2000/svg"><image href="x.png"/></svg>',
                 "element <image>")):
            hit = [x for x in svg_lint(bad_svg) if want in x]
            if hit:
                report.append("%s -> %s" % (label, hit[0]))
            else:
                failures.append("NEGATIVE CONTROL FAILED TO FAIL: the SVG lint passed %s" % label)
        try:
            with tripwire():
                subprocess.run(["git", "--version"], capture_output=True)
            failures.append("NEGATIVE CONTROL FAILED TO FAIL: the tripwire that keeps --check from starting a "
                            "process did not trip on a call to git")
        except RuntimeError as e:
            report.append("a check that asks git -> %s" % e)
        try:
            with tripwire():
                socket.socket().connect(("127.0.0.1", 9))
            failures.append("NEGATIVE CONTROL FAILED TO FAIL: the tripwire did not trip on a connection")
        except RuntimeError as e:
            report.append("a check that opens a connection -> %s" % e)
        plant("a personal path that a figure would write",
              lambda t: {X.EXTRACT_DIR + "/ledger.json": _plant_path_in_extract(t / (X.EXTRACT_DIR + "/ledger.json"))},
              r"would carry a personal path")
    return failures, report


def _ghost_extract(t):
    ex = json.loads((t / X.EXTRACT_DIR / "history.json").read_text(encoding="utf-8"))
    ex["extract"] = "ghost"
    return X.dumps(ex)


def _plant_path_in_extract(path):
    """A valid extract (its own digest recomputed) whose data carries a personal path, which a figure would then
    copy into its sidecar: the leak check must name it before anything is written."""
    ex = json.loads(path.read_text(encoding="utf-8"))
    fake = "C:" + "/" + "Users" + "/someone/x "       # assembled, so that this file itself carries no such path
    ex["data"]["milestones"][0]["label"] = fake + ex["data"]["milestones"][0]["label"]
    ex["body_sha256"] = X.body_digest(ex["data"])
    return X.dumps(ex)


def _bump_digit(b, start):
    """The same bytes with the first ASCII digit at or after `start` increased by one (9 becomes 0)."""
    out = bytearray(b)
    for i in range(min(start, len(out) - 1), len(out)):
        if 48 <= out[i] <= 57:
            out[i] = 48 + (out[i] - 48 + 1) % 10
            return bytes(out)
    raise AssertionError("no digit to bump")


def read_extract_names(results):
    names = set()
    for r in results:
        names.update(r.src.extracts)
    return names


def _one_byte(b):
    """The same bytes with the first hex digit of the first fill colour changed: one byte of the file."""
    i = b.index(b'fill="#') + len(b'fill="#')
    out = bytearray(b)
    out[i] = ord("1") if out[i] == ord("0") else ord("0")
    return bytes(out)


def _flip_byte(b, i):
    b = bytearray(b)
    b[i] = (b[i] + 1) % 256 if b[i] != 10 else 32
    return bytes(b)


def _edit_extract_data(path):
    ex = json.loads(path.read_text(encoding="utf-8"))

    def bump(o):
        if isinstance(o, dict):
            for k in sorted(o):
                if bump(o[k]) if isinstance(o[k], (dict, list)) else False:
                    return True
                if isinstance(o[k], int) and not isinstance(o[k], bool):
                    o[k] += 1
                    return True
        elif isinstance(o, list):
            for i, v in enumerate(o):
                if isinstance(v, (dict, list)):
                    if bump(v):
                        return True
                elif isinstance(v, int) and not isinstance(v, bool):
                    o[i] += 1
                    return True
        return False
    assert bump(ex["data"])
    return X.dumps(ex)


def _edit_extract_source_digest(path):
    ex = json.loads(path.read_text(encoding="utf-8"))
    for s in ex["sources"]:
        if "sha256" in s:
            s["sha256"] = ("0" if s["sha256"][0] != "0" else "1") + s["sha256"][1:]
            break
    ex["body_sha256"] = X.body_digest(ex["data"])
    return X.dumps(ex)


def _change_stated(path, c):
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"\b%s(x)" % re.escape(c["stated"]), "9.9\\1", text, count=1)
    assert new != text
    return new


def _remove_stated(path, c):
    text = path.read_text(encoding="utf-8")
    new = re.sub(r"\b%s(x)" % re.escape(c["stated"]), "some\\1", text, count=1)
    assert new != text
    return new


# ----------------------------------------------------------------------- CLI
def cmd_write(root, only):
    results = build_all(root, only)
    outs = outputs(results)
    n = 0
    for rel in sorted(outs):
        if only and not any(rel.startswith("%s/%s" % (FIG_DIR, nm)) for nm in only):
            continue
        K.write_text(pathlib.Path(root) / rel, outs[rel])
        n += 1
    if not only:
        for rel in owned_on_disk(root):
            if rel not in outs:
                (pathlib.Path(root) / rel).unlink()
                print("removed %s (made by no figure)" % rel)
    bad = [(r.fig.name, c["id"]) for r in results for c in r.claims.rows if c["verdict"] != "agrees"]
    print("project_figures: wrote %d files for %d figures%s" % (n, len(results), "; " if bad else ""))
    for name, cid in bad:
        print("  claim %s/%s does not agree with the record (see the sidecar)" % (name, cid))
    return 0


def cmd_list(root):
    results = build_all(root)
    for r in results:
        print("%-16s %-12s %2d files, %d extract(s), %d claim(s)  %s" % (
            r.fig.name, r.fig.group, len(r.meta["files"]), len(r.meta["extracts"]), len(r.claims.rows), r.fig.title))
    return 0


class tripwire:
    """For the length of a with-block, starting a process or opening a connection raises RuntimeError.

    --check must read no git history, network, card or other machine (the brief's FG2, and CI's shallow
    checkout makes it a necessity). Saying so is not enough, so the check runs under this: a change that
    made it call git, or open a socket, would fail by name instead of passing where history happens to be."""

    def __enter__(self):
        self._popen, self._connect = subprocess.Popen.__init__, socket.socket.connect

        def no_process(*a, **k):
            raise RuntimeError("the check tried to start a process (git? a tool?); it must read the tree only")

        def no_connection(*a, **k):
            raise RuntimeError("the check tried to open a connection; it must read the tree only")
        subprocess.Popen.__init__ = no_process
        socket.socket.connect = no_connection
        return self

    def __exit__(self, *exc):
        subprocess.Popen.__init__, socket.socket.connect = self._popen, self._connect
        return False


def cmd_check(root, only, run_controls=True):
    with tripwire():
        return _cmd_check(root, only, run_controls)


def _cmd_check(root, only, run_controls=True):
    problems, notes, results = check_tree(root, only)
    for n_ in notes:
        print("note: %s" % n_)
    if not problems:
        for r in results:
            print("  ok    %-16s %d files, %d extract%s, %d claim%s agree" % (
                r.fig.name, len(r.meta["files"]), len(r.meta["extracts"]), "" if len(r.meta["extracts"]) == 1 else "s",
                len(r.claims.rows), "" if len(r.claims.rows) == 1 else "s"))
    failures, report = [], []
    if run_controls and not problems and not only:
        failures, report = controls(root, results)
        for line in report:
            print("  control: %s" % line)
    problems += failures
    if problems:
        for p in problems:
            print("  %s" % p)
        names = []
        for p in problems:
            m = re.search(r"figure ([\w-]+)|extract ([\w-]+)", p)
            if m and (m.group(1) or m.group(2)) not in names:
                names.append(m.group(1) or m.group(2))
        print("project_figures: %d problem(s): %s - STALE ones differ from a fresh generation, remake with "
              "python python/project_figures.py --write" % (len(problems), ", ".join(names[:8]) or "see above"))
        return 1
    n_stay = sum(1 for line in report if "not counted as a fault" in line)
    print("project_figures: %d figures, %d files, every number the record states agrees%s"
          % (len(results), 3 * len(results) + 1,
             "; %d faults planted, each caught by name, and %d edit%s that must move nothing, which moved nothing" % (
                 len(report) - n_stay, n_stay, "" if n_stay == 1 else "s") if run_controls and not only else ""))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true", help="remake every figure, sidecar and the gallery")
    g.add_argument("--check", action="store_true", help="remake them in memory and fail by name on a difference")
    g.add_argument("--list", action="store_true", help="list the figures")
    ap.add_argument("--only", action="append", default=[], metavar="NAME", help="restrict to one figure (repeatable)")
    ap.add_argument("--root", default=str(ROOT), help="the tree to read and write (default: this one)")
    ap.add_argument("--no-controls", action="store_true", help="--check without planting faults (for a quick look)")
    a = ap.parse_args(argv)
    if a.write:
        return cmd_write(a.root, a.only)
    if a.list:
        return cmd_list(a.root)
    return cmd_check(a.root, a.only, not a.no_controls)


if __name__ == "__main__":
    sys.exit(main())
