# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""A dated archive of the project's figures and of where the project stands, for use outside the repository.

    python python/project_packager.py                   # exports/cft-fp256-status-<date>-<commit>.zip
    python python/project_packager.py --no-png          # the same, with no PNG renders (and so no converter)
    python python/project_packager.py --verify ARCHIVE  # re-hash an archive against its own manifest
    python python/project_packager.py --check           # the packager's own self-test (no converter needed)
    python python/project_packager.py --check --png     # and the legs that use the real converter

WHAT THE ARCHIVE HOLDS (docs/EXPORT.md has the long form)
  every figure - parcel FG's fifteen and the README's two bench charts - as the light and dark SVG that is
  committed, and as a PNG render of each; each figure's sidecar and its caption; STATUS.md, "where the project
  stands", made by script (python/packager_status.py), and STATUS.html, the same words for a browser
  (python/packager_html.py); the light documents as they stand; and MANIFEST.json: when (UTC), from which commit,
  whether the tree was clean, every file's size and SHA-256 and where it came from, the converter and its fonts,
  and the versions of this script and of Python.

DATED, AND REPRODUCIBLE BUT FOR ONE FIELD. The date is when the run began, in the file name and in the manifest.
Nothing else in the archive depends on the clock: the files copied from the tree are the tree's bytes; STATUS.md
carries the commit, not the date; the PNGs are what one converter makes of one SVG; the zip is written STORED
(not compressed, so no zlib build can change a byte), entries sorted by path, every entry stamped with the
commit's own committer time in UTC rounded down to an even second (a zip entry has no zone and two-second
resolution), unix mode 0644. So two runs at one commit with one converter differ in MANIFEST.json's created_utc
and date_utc, in the date in the file name and in the directory the entries sit in, and in nothing else. `--now`
fixes the clock, so two builds can be compared as a whole zip; the manifest then says, in archive.clock, that the
clock was given.

WHAT IT REFUSES, by name (exit 1, nothing written; independent refusals are reported together):
  no-git, not-a-git-tree   there is no git, or the root is not the top of a work tree with a commit.
  dirty-tree          the tree differs from HEAD. The archive names a commit, so it must be made from it; with
                      --allow-dirty the name ends -dirty and the manifest lists the paths that differ.
  output-not-ignored  the output directory is inside the tree and git does not ignore it.
  exists              the archive is already there (--force replaces it).
  no-converter, converter-unusable   there is no rsvg-convert, or the one named does not answer as one, and
                      --no-png was not given.
  missing-figure, missing-document   a figure's light or dark SVG or its sidecar is absent, or a README chart's SVG
                      is absent or has no aria-label; a figure's files have no place in docs/FIGURES.md; or a light
                      document is absent.
  gallery-unreadable, readme-unreadable   docs/FIGURES.md or the README no longer has the structure read from it.
  sidecar-mismatch    a sidecar that is not JSON, is not shaped like one, or does not describe its figure: another
                      name or files, an alt text that is not the SVG's or the gallery's, a title that is not the
                      gallery's, an SVG that declares no size, a source or an extract that is not in the tree or
                      whose digest is not the tree's file.
  figures-out-of-date python/project_figures.py --check fails or says nothing: a figure, sidecar or caption is not
                      what a fresh generation gives. It is run first, so that an out-of-date figure is never exported.
  readme-charts-out-of-date   the README's two bench charts are not what python/readme_charts.py makes from
                      docs/bench/.
  render-failed, png-size, png-blank, png-corrupt, png-unsupported   the converter failed, or its PNG is the wrong
                      size, blank, damaged or of a kind the reader does not hold (python/packager_png.py).
  status-source       a file STATUS.md is read from no longer says what its reader expects.
  html-text, html-malformed, html-link   STATUS.html does not say what STATUS.md says, its tags do not balance, or
                      it names a file the archive does not hold.
  personal-path       anything bound for the archive holds a path under a user's directory.
  self-verify         the archive just written did not verify (a defect in this script; nothing is left behind).
--verify names its own: hash-mismatch, size-mismatch, file-missing, file-unlisted, zip-metadata, manifest-missing,
manifest-unreadable, manifest-mismatch, archive-structure, archive-unreadable, png-missing, png-unexpected,
png-source, link-dead, html-mismatch, and the PNG, HTML, sidecar and personal-path names above.

THE CONVERTER. rsvg-convert (librsvg), chosen over ImageMagick, PyMuPDF and a headless browser by measurement
(docs/EXPORT.md): it follows the SVG's own font stack through the system's fonts, its PNG carries no date, and two
runs give the same bytes. The SVGs name system fonts, so a PNG's pixels depend on the fonts of the machine that
rendered it; the manifest records which fonts the render used.
"""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import zlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import packager_html as HTML                                         # noqa: E402
import packager_png as PNG                                           # noqa: E402
import packager_status as ST                                         # noqa: E402

FORMAT = 1
STEM = "cft-fp256-status"
DEFAULT_OUT = "exports"
FIG_DIR = "docs/img/figures"
BENCH_DIR = "docs/img/bench"
GALLERY = "docs/FIGURES.md"
THEMES = ("light", "dark")
README_CHARTS = ("when-hardware-pays", "cost-by-size")
README_CHARTS_ARGS = ["docs/bench/sweep-x86_64.csv", "--peers", "x86-64=docs/bench/peers-x86_64.csv",
                      "--peers", "arm64=docs/bench/peers-arm64.csv"]
README_CHARTS_DATA = ("docs/bench/sweep-x86_64.csv", "docs/bench/peers-x86_64.csv", "docs/bench/peers-arm64.csv")
SCALE_DEFAULT = 2
ZIP_MODE = 0o100644
# A path under a user's directory on Windows, Linux or macOS, exactly as python/project_figures.py's own scan has it,
# assembled from parts so that this file itself carries no such path.
_U, _H = "Us" + "ers", "ho" + "me"
LEAK = re.compile(r"[A-Za-z]:[\\/]+%s[\\/]|/%s/[A-Za-z]|/%s/[A-Za-z]|\\%s\\" % (_U, _H, _U, _U))
# The light documents, each with the reason it is there. Reasons are digit-free: STATUS.md prints them.
LIGHT_DOCS = (
    ("README.md", "the project's front page: what it is, how fast it is and how it is checked"),
    ("docs/FIGURES.md", "the gallery as published: each figure's caption, its sources and the notes that go with it"),
    ("CAPABILITIES.md", "what the tile can and cannot do, mark by mark, as that document states it (it dates its own "
                        "marks)"),
    ("docs/COMPLIANCE.md", "the standard's clauses one by one: what is implemented, what is refused, where each is "
                           "proven, as that document states it for the ABI it names"),
    ("LICENSE", "the licence terms the project, and so these figures, are distributed under"),
    ("NOTICE", "the attribution notice that the licence asks every redistribution to carry"),
)


class Refused(Exception):
    """One or more refusals: a list of (code, message)."""

    def __init__(self, items):
        Exception.__init__(self, "; ".join("%s: %s" % it for it in items))
        self.items = list(items)


def refuse(code, message):
    raise Refused([(code, message)])


def sha256(b):
    return hashlib.sha256(b).hexdigest()


TIMEOUT = 900          # seconds: the longest thing it runs, the figure check, takes about 15 on a loaded desktop


def run(args, cwd=None, env=None, timeout=TIMEOUT):
    """(exit code, stdout, stderr). A command that outlasts the timeout is a failure with exit code 124 and says so,
    so that a hung git or converter ends the run by name instead of hanging a gate."""
    try:
        p = subprocess.run(args, cwd=None if cwd is None else str(cwd), env=env, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", "timed out after %d s: %s" % (timeout, " ".join(str(a) for a in args[:3]))
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


# --------------------------------------------------------------------------------------------------- git
class GitError(Exception):
    pass


def git(root, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    rc, out, err = run(["git", "-c", "core.quotepath=off", "-C", str(root)] + list(args), env=env)
    if rc != 0:
        raise GitError("git %s: %s" % (" ".join(args[:2]), (err.strip() or out.strip())[:200]))
    return out


def porcelain(text):
    """`git status --porcelain=v1 -z` as a list of 'XY path' strings (a rename shows both paths)."""
    fields = text.split("\0")
    out, i = [], 0
    while i < len(fields):
        f = fields[i]
        i += 1
        if len(f) < 4:
            continue
        if f[0] in "RC":
            out.append("%s <- %s" % (f, fields[i] if i < len(fields) else "?"))
            i += 1
        else:
            out.append(f)
    return out


def git_state(root):
    """The commit the tree is, and whether it is clean. Refuses outside a git tree."""
    if shutil.which("git") is None:
        refuse("no-git", "git is not on PATH, and the archive names the commit it was made from")
    try:
        top = git(root, "rev-parse", "--show-toplevel").strip()
        sha = git(root, "rev-parse", "HEAD").strip()
        tree = git(root, "rev-parse", "HEAD^{tree}").strip()
        ct = int(git(root, "log", "-1", "--format=%ct", "HEAD").strip())
        status = git(root, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    except (GitError, ValueError) as e:
        refuse("not-a-git-tree", "%s is not a git work tree with a commit (%s)" % (root.name, e))
    if not os.path.samefile(top, str(root)):
        refuse("not-a-git-tree", "%s is inside a git tree but is not its top; give the top as --root" % root.name)
    dirty = porcelain(status)
    return {"sha": sha, "tree": tree, "committed": datetime.datetime.fromtimestamp(ct, datetime.timezone.utc),
            "clean": not dirty, "dirty": dirty}


def check_output_dir(root, out):
    """The output directory must be outside the tree or ignored by git: nothing the packager makes is committed."""
    try:
        rel = out.resolve().relative_to(root.resolve())
    except ValueError:
        return
    rc, _o, _e = run(["git", "-C", str(root), "check-ignore", "-q", "--", (rel / "probe.zip").as_posix()])
    if rc != 0:
        refuse("output-not-ignored", "%s is inside the tree and git does not ignore it, so an archive written there "
               "would be untracked content and the next run would find the tree dirty; add it to .gitignore, or give "
               "--out a directory outside the tree" % rel.as_posix())


# ----------------------------------------------------------------------------------------------- figures
def svg_size(text):
    m = re.search(r'<svg\b[^>]*?\bwidth="(\d+)"[^>]*?\bheight="(\d+)"', text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def svg_labels(text):
    """(title, aria-label) of an SVG as the figure kit writes them."""
    t = re.search(r"<title>(.*?)</title>", text, re.S)
    a = re.search(r'<svg\b[^>]*?\baria-label="([^"]*)"', text)
    unesc = ST.unescape_attr
    return (unesc(t.group(1)) if t else None), (unesc(a.group(1)) if a else None)


def collect_figures(root, rd):
    """The figures the archive holds, in the gallery's order and then the README's: (figures, problems).
    A figure is a dict (see packager_status.build's ctx); problems are (code, message) refusals."""
    problems = []
    try:
        gallery = ST.parse_gallery(rd.text(GALLERY))
    except ST.SourceError as e:
        return [], [("gallery-unreadable", str(e))]
    try:
        alts = ST.readme_picture_alts(rd.text(ST.README), README_CHARTS)
    except ST.SourceError as e:
        return [], [("readme-unreadable", str(e))]
    gsrc = rd.src(GALLERY, "the figure's block: title, alt text and caption paragraphs")
    rsrc = rd.src(ST.README, "the alt text of the chart's picture")
    figs = []
    listed = {g["name"] for g in gallery}
    on_disk = set()
    for p in (root / FIG_DIR).glob("*"):
        m = re.fullmatch(r"(.+?)(?:-light\.svg|-dark\.svg|\.json)", p.name)
        if m:
            on_disk.add(m.group(1))
    for extra in sorted(on_disk - listed):
        problems.append(("missing-figure", "%s/%s has files but no place in %s (an unlisted figure is not exported; "
                         "regenerate with python python/project_figures.py --write)" % (FIG_DIR, extra, GALLERY)))
    for g in gallery:
        n = g["name"]
        svgs = {t: "%s/%s-%s.svg" % (FIG_DIR, n, t) for t in THEMES}
        sidecar = "%s/%s.json" % (FIG_DIR, n)
        ok = True
        for rel in list(svgs.values()) + [sidecar]:
            if not (root / rel).is_file():
                problems.append(("missing-figure", "figure %s: %s is not in the tree" % (n, rel)))
                ok = False
        if not ok:
            continue
        problems += check_sidecar(rd, g, svgs, sidecar)
        figs.append({
            "name": n, "origin": "gallery", "group": g["group"], "group_source": gsrc, "title": g["title"],
            "alt": g["alt"], "caption_text": ST.caption_paragraph(g, "**Shows.**") + "\n\n"
            + ST.caption_paragraph(g, "**Does not show.**"),
            "caption_rule": "the figure's `**Shows.**` and `**Does not show.**` paragraphs in the gallery",
            "caption_source": gsrc, "svg_light": svgs["light"], "svg_dark": svgs["dark"],
            "png_light": "png/%s-light.png" % n, "png_dark": "png/%s-dark.png" % n,
            "sidecar": sidecar, "caption_file": "captions/%s.md" % n, "gallery": g})
    for n in README_CHARTS:
        svgs = {t: "%s/%s-%s.svg" % (BENCH_DIR, n, t) for t in THEMES}
        ok = True
        for rel in svgs.values():
            if not (root / rel).is_file():
                problems.append(("missing-figure", "README chart %s: %s is not in the tree" % (n, rel)))
                ok = False
        if not ok:
            continue
        _title, label = svg_labels(rd.text(svgs["light"]))
        title = label                   # the README's charts carry an aria-label and no <title>
        if title is None:
            problems.append(("missing-figure", "README chart %s: %s has no aria-label to name it by" % (n, svgs["light"])))
            continue
        figs.append({
            "name": n, "origin": "readme", "group": "From the README", "group_source": None, "title": title,
            "alt": alts[n], "caption_text": alts[n], "caption_rule": "the alt text of the chart's <img> in the README",
            "caption_source": rsrc, "svg_light": svgs["light"], "svg_dark": svgs["dark"],
            "png_light": "png/%s-light.png" % n, "png_dark": "png/%s-dark.png" % n,
            "sidecar": None, "caption_file": "captions/%s.md" % n, "gallery": None})
    return figs, problems


def check_sidecar(rd, g, svgs, sidecar):
    """Does the sidecar describe this figure? Its name, its files, its alt text (the SVG's, and the gallery's), its
    title (the gallery's), and the digest of every source it names that is a whole file in the tree."""
    n, out = g["name"], []

    def bad(msg):
        out.append(("sidecar-mismatch", "figure %s: %s" % (n, msg)))
    try:
        sc = rd.json(sidecar)
    except ST.SourceError as e:
        bad(str(e))
        return out
    try:
        if sc.get("figure") != n:
            bad("%s says it is figure %r" % (sidecar, sc.get("figure")))
        if sc.get("files") != [svgs["light"], svgs["dark"]]:
            bad("%s lists the files %r, not the figure's two SVGs" % (sidecar, sc.get("files")))
        if sc.get("title") != g["title"]:
            bad("%s has the title %r where the gallery has %r" % (sidecar, sc.get("title"), g["title"]))
        if sc.get("alt") != g["alt"]:
            bad("%s has an alt text that is not the gallery's" % sidecar)
        for t, rel in svgs.items():
            title, label = svg_labels(rd.text(rel))
            if label != sc.get("alt") or title != sc.get("alt"):
                bad("%s: the SVG's title and aria-label are not the sidecar's alt text" % rel)
            if svg_size(rd.text(rel)) is None:
                bad("%s declares no width and height" % rel)
        for s in sc.get("sources", []):
            if "reads" in s:
                continue                              # a digest of what was read from a changing file: project_figures'
            try:
                b = rd._bytes(s["path"])
            except ST.SourceError as e:
                bad("%s names a source it cannot find: %s" % (sidecar, e))
                continue
            if sha256(b) != s.get("sha256"):
                bad("%s records %s with digest %s..., and the tree's file is %s..." % (
                    sidecar, s["path"], str(s.get("sha256"))[:12], sha256(b)[:12]))
        for e in sc.get("extracts", []):
            try:
                b = rd._bytes(e["path"])
            except ST.SourceError as err:
                bad("%s names an extract it cannot find: %s" % (sidecar, err))
                continue
            if sha256(b) != e.get("sha256"):
                bad("%s records extract %s with digest %s..., and the tree's file is %s..." % (
                    sidecar, e["path"], str(e.get("sha256"))[:12], sha256(b)[:12]))
    except (AttributeError, KeyError, TypeError) as e:       # a sidecar that is JSON and is not shaped like one
        bad("%s is not shaped as a sidecar is (%s: %s)" % (sidecar, type(e).__name__, e))
    return out


def run_figure_check(root, extra=()):
    """python/project_figures.py --check, run first. Returns its summary line; refuses if it fails."""
    cmd = [sys.executable, "-B", str(root / "python" / "project_figures.py"), "--root", str(root), "--check"] + list(extra)
    rc, out, err = run(cmd, cwd=root)
    lines = [ln.strip() for ln in (out + err).splitlines() if ln.strip()]
    if rc != 0:
        refuse("figures-out-of-date", "python/project_figures.py --check failed (exit %d); %s" % (
            rc, "; ".join(ln for ln in lines if "STALE" in ln or "problem" in ln or "missing" in ln)[:600] or "see its output"))
    if not lines or not lines[-1].startswith("project_figures:"):
        refuse("figures-out-of-date", "python/project_figures.py --check passed but printed no summary line")
    return lines[-1]


def run_readme_charts_check(root):
    """The README's two bench charts regenerate, byte for byte, from the committed sweeps. Returns the data digests."""
    with tempfile.TemporaryDirectory(prefix="packager-rc-") as tmp:
        cmd = [sys.executable, "-B", str(root / "python" / "readme_charts.py")] + README_CHARTS_ARGS + ["--out", tmp]
        rc, out, err = run(cmd, cwd=root)
        if rc != 0:
            refuse("readme-charts-out-of-date", "python/readme_charts.py failed (exit %d): %s" % (rc, (err.strip() or out.strip())[:300]))
        for n in README_CHARTS:
            for t in THEMES:
                made = pathlib.Path(tmp) / ("%s-%s.svg" % (n, t))
                have = root / BENCH_DIR / ("%s-%s.svg" % (n, t))               # collect_figures has found it already
                if not made.is_file() or made.read_bytes() != have.read_bytes():
                    refuse("readme-charts-out-of-date", "%s/%s-%s.svg is not what python/readme_charts.py makes from "
                           "docs/bench/; remake with: python python/readme_charts.py %s --out %s" % (
                               BENCH_DIR, n, t, " ".join(README_CHARTS_ARGS), BENCH_DIR))
    data = []
    for rel in README_CHARTS_DATA:
        b = (root / rel).read_bytes()
        data.append({"path": rel, "sha256": sha256(b), "bytes": len(b)})
    return data


# ----------------------------------------------------------------------------------------------- converter
def find_converter(spec=None):
    """rsvg-convert, by name on PATH or by path. Its version is read from `--version`; anything that does not
    answer as rsvg-convert is refused, so a different tool cannot be mistaken for it (on Windows `convert` is a disk
    tool, not ImageMagick, and is never looked up)."""
    name = spec or "rsvg-convert"
    if os.sep in name or "/" in name:
        exe = name if os.path.isfile(name) else None
    else:
        exe = shutil.which(name)
    if not exe:
        refuse("no-converter", "no rsvg-convert was found (%s); install librsvg's rsvg-convert, name one with "
               "--converter, or pass --no-png to make an archive without PNG renders" % (
                   "looked for %r on PATH" % name if not spec else "--converter %r is not a file" % spec))
    try:
        rc, out, err = run([exe, "--version"])
    except OSError as e:
        refuse("converter-unusable", "%s could not be run (%s)" % (pathlib.Path(exe).name, e))
    m = re.search(r"rsvg-convert version (\d+(?:\.\d+)+)", out + err)
    if rc != 0 or not m:
        refuse("converter-unusable", "%s does not answer `--version` as rsvg-convert does (it said %r)" % (
            pathlib.Path(exe).name, (out + err).strip()[:80]))
    return {"exe": exe, "name": "rsvg-convert", "version": m.group(1), "library": "librsvg"}


def render_pngs(conv, svgs, scale, tmp):
    """{archive png path: bytes} and the fonts the renders used. `svgs` is [(png path, svg path, svg text)]."""
    out, fonts, stacks = {}, set(), set()
    for png_rel, svg_rel, text in svgs:
        size = svg_size(text)
        if size is None:
            refuse("render-failed", "%s declares no width and height, so the size of its PNG cannot be known" % svg_rel)
        src = pathlib.Path(tmp) / ("in-" + pathlib.PurePosixPath(svg_rel).name)
        src.write_bytes(text.encode("utf-8"))
        dst = pathlib.Path(tmp) / pathlib.PurePosixPath(png_rel).name
        rc, _o, err = run([conv["exe"], "--zoom", "%g" % scale, "-f", "png", "-o", str(dst), str(src)])
        if rc != 0 or not dst.is_file():
            refuse("render-failed", "rsvg-convert failed on %s (exit %d): %s" % (svg_rel, rc, err.strip()[:200]))
        data = dst.read_bytes()
        facts, problems = PNG.inspect(data, expect=(size[0] * scale, size[1] * scale))
        if problems:
            code, msg = problems[0]
            refuse(code, "%s, rendered from %s: %s" % (png_rel, svg_rel, msg))
        out[png_rel] = (data, facts, size)
        stacks.update(re.findall(r'font-family="([^"]*)"', text))
        pdf = pathlib.Path(tmp) / ("probe-" + pathlib.PurePosixPath(svg_rel).name + ".pdf")
        rc, _o, _e = run([conv["exe"], "-f", "pdf", "-o", str(pdf), str(src)])
        if rc == 0 and pdf.is_file():
            for raw in re.findall(rb"/BaseFont\s*/([A-Za-z0-9+_-]+)", pdf.read_bytes()):
                fonts.add(re.sub(r"^[A-Z]{6}\+", "", raw.decode("ascii")))
        else:
            fonts.add(None)
    probed = None not in fonts
    return out, {"stacks_named_by_the_svgs": sorted(stacks), "used": sorted(f for f in fonts if f) if probed else None,
                 "how": "the /BaseFont names read from a PDF that the same converter writes from each SVG, with cairo's "
                        "six-letter subset tag removed" if probed else
                        "not read: the converter could not write a PDF of every SVG"}


# ---------------------------------------------------------------------------------------------- the files
def caption_file(fg, rd):
    """captions/NAME.md: the figure's caption, as its source has it."""
    n = fg["name"]
    if fg["origin"] == "gallery":
        g = fg["gallery"]
        lines = ["# " + g["title"], "", g["body"], "", "---", "",
                 "This is the block of the figure `%s` in `docs/FIGURES.md`, without its picture, copied as it stands. "
                 "The figure is `%s` and `%s`, with its sidecar `%s`." % (n, fg["svg_light"], fg["svg_dark"], fg["sidecar"])]
    else:
        lines = ["# " + fg["title"], "", fg["alt"], "", "---", "",
                 "This is the alt text of the figure's picture in `README.md`: the chart has no sidecar and no block in "
                 "`docs/FIGURES.md`. It is drawn by `python/readme_charts.py` from the sweeps in `docs/bench/`, as "
                 "`%s` and `%s`." % (fg["svg_light"], fg["svg_dark"])]
    return ("\n".join(lines) + "\n").encode("utf-8")


def scan_leaks(entries):
    """Refuse if anything bound for the archive holds a path under a user's directory."""
    found = []
    for rel, data in entries:
        if rel.endswith(".png"):
            continue
        text = data.decode("utf-8", "replace")
        for i, line in enumerate(text.splitlines(), 1):
            m = LEAK.search(line)
            if m:
                found.append(("personal-path", "%s line %d holds a path under a user's directory (%s...)" % (
                    rel, i, m.group(0))))
                break
    if found:
        raise Refused(found)


def dumps(obj):
    return json.dumps(obj, indent=1, ensure_ascii=True) + "\n"


def entry_stamp(when):
    """A zip entry's time: the commit's, in UTC, to an even second, never before the zip epoch."""
    w = when.astimezone(datetime.timezone.utc)
    if w.year < 1980:
        return (1980, 1, 1, 0, 0, 0)
    return (w.year, w.month, w.day, w.hour, w.minute, w.second - w.second % 2)


def write_zip(path, root_dir, entries, when):
    """STORED, sorted by path, one stamp, mode 0644, created by 'unix': nothing in the bytes depends on the run."""
    stamp = entry_stamp(when)
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_STORED) as z:
        for rel, data in sorted(entries, key=lambda e: e[0]):
            zi = zipfile.ZipInfo(root_dir + "/" + rel, date_time=stamp)
            zi.compress_type = zipfile.ZIP_STORED
            zi.create_system = 3
            zi.external_attr = ZIP_MODE << 16
            z.writestr(zi, data)


def script_digests():
    out = []
    for name in ("project_packager.py", "packager_status.py", "packager_html.py", "packager_png.py", "packager_check.py"):
        p = HERE / name
        if p.is_file():
            out.append({"path": "python/" + name, "sha256": sha256(p.read_bytes())})
    return out


def parse_now(s):
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        raise SystemExit("project_packager: --now wants UTC like 2026-10-19T17:31:02Z, not %r" % s)


# -------------------------------------------------------------------------------------------------- build
def build(root, out_dir, no_png=False, converter=None, scale=SCALE_DEFAULT, allow_dirty=False, now=None, force=False,
          figure_check_args=(), say=print, memo=None):
    """Make the archive. Returns a dict of what was made. Raises Refused; writes nothing when it does.

    `memo` is for the self-test alone: a dict in which the two generator checks' verdicts are remembered by the
    commit's tree hash, so that building one clean commit several times runs them once. A dirty tree is never
    remembered. A real run passes none."""
    root = pathlib.Path(root).resolve()
    started = time.monotonic()
    clock = "given on the command line (--now)" if now else "the system clock, once, at the start of the run"
    created = now or datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    problems = []

    g = git_state(root)
    if not g["clean"] and not allow_dirty:
        problems.append(("dirty-tree", "the tree differs from commit %s in %d path(s) (%s); the archive names a commit, "
                         "so make it from a clean tree, or pass --allow-dirty to make one whose name ends -dirty and "
                         "whose manifest lists them" % (g["sha"][:7], len(g["dirty"]), "; ".join(g["dirty"][:5])
                                                         + ("; ..." if len(g["dirty"]) > 5 else ""))))
    stem = "%s-%s-%s%s" % (STEM, created.strftime("%Y-%m-%d"), g["sha"][:7], "" if g["clean"] else "-dirty")
    out = pathlib.Path(out_dir)
    out = out if out.is_absolute() else root / out
    try:
        check_output_dir(root, out)
    except Refused as r:
        problems += r.items
    target = out / (stem + ".zip")
    if target.exists() and not force:
        problems.append(("exists", "%s is already there; --force replaces it, or name another --out" % target.name))
    conv = None
    if not no_png:
        try:
            conv = find_converter(converter)
        except Refused as r:
            problems += r.items
    rd = ST.Reader(root)
    figs, fig_problems = collect_figures(root, rd)
    problems += fig_problems
    docs = []
    for rel, why in LIGHT_DOCS:
        try:
            docs.append((rel, why, rd._bytes(rel)))
        except ST.SourceError as e:
            problems.append(("missing-document", "the light document %s" % e))
    if problems:
        raise Refused(problems)

    say("project_packager: %s from commit %s (%s)" % (stem, g["sha"][:7], "clean" if g["clean"] else "DIRTY"))
    remember = memo is not None and g["clean"]
    fkey, ckey = ("figures", g["tree"], tuple(figure_check_args)), ("charts", g["tree"])
    if remember and fkey in memo:
        summary = memo[fkey]
    else:
        summary = run_figure_check(root, figure_check_args)
        if remember:
            memo[fkey] = summary
    say("  figures:  %s" % summary)
    if remember and ckey in memo:
        rc_data = memo[ckey]
    else:
        rc_data = run_readme_charts_check(root)
        if remember:
            memo[ckey] = rc_data
    say("  README charts: the four SVGs regenerate byte for byte from docs/bench/")

    entries, meta = [], {}

    def add(rel, data, **info):
        entries.append((rel, data))
        meta[rel] = dict(info, bytes=len(data), sha256=sha256(data))

    for fg in figs:
        for t in THEMES:
            rel = fg["svg_" + t]
            add(rel, rd._bytes(rel), kind="figure-svg", figure=fg["name"], theme=t, tree_path=rel,
                sidecar=fg["sidecar"], sidecar_sha256=rd.log[fg["sidecar"]]["sha256"] if fg["sidecar"] else None)
        if fg["sidecar"]:
            add(fg["sidecar"], rd._bytes(fg["sidecar"]), kind="sidecar", figure=fg["name"], tree_path=fg["sidecar"])
        add(fg["caption_file"], caption_file(fg, rd), kind="caption", figure=fg["name"],
            derived_from=ST.GALLERY if fg["origin"] == "gallery" else ST.README,
            derived_from_sha256=rd.log[ST.GALLERY if fg["origin"] == "gallery" else ST.README]["sha256"],
            rule="the figure's block in the gallery, without its picture" if fg["origin"] == "gallery" else
            "the alt text of the figure's picture in the README")
    for rel, why, data in docs:
        add(rel, data, kind="document", tree_path=rel, why=why)

    png_info = {"made": False, "reason": "--no-png was given: no converter was asked for, and the archive holds no PNG"}
    if not no_png:
        svgs = []
        for fg in figs:
            for t in THEMES:
                svgs.append((fg["png_" + t], fg["svg_" + t], rd.text(fg["svg_" + t])))
        with tempfile.TemporaryDirectory(prefix="packager-png-") as tmp:
            rendered, fonts = render_pngs(conv, svgs, scale, tmp)
        for fg in figs:
            for t in THEMES:
                rel = fg["png_" + t]
                data, facts, size = rendered[rel]
                add(rel, data, kind="figure-png", figure=fg["name"], theme=t, rendered_from=fg["svg_" + t],
                    rendered_from_sha256=meta[fg["svg_" + t]]["sha256"], scale=scale, width=facts["width"],
                    height=facts["height"], band_rows=facts["band_rows"], ink_pct=facts["ink_pct"],
                    colours=facts["colours"], converter="%s %s" % (conv["name"], conv["version"]))
        widths = sorted({size[0] for _data, _facts, size in rendered.values()})
        png_info = {
            "made": True, "scale": scale,
            "scale_rule": "a PNG is its SVG's declared size (the SVGs declare a width of %s px) times the scale; twice is "
                          "the usual export for a slide or a page that may be seen on a dense screen, and `--scale` "
                          "changes it" % " and ".join(str(w) for w in widths),
            "converter": {"name": conv["name"], "version": conv["version"], "library": conv["library"]},
            "command": [conv["name"], "--zoom", "%g" % scale, "-f", "png", "-o", "PNG", "SVG"],
            "background": "none is given: every figure draws its own opaque background rectangle, so no PNG is transparent",
            "fonts": fonts,
            "checks": {"size": "the PNG's width and height are the SVG's declared size times the scale",
                       "not_blank": "in the top %d rows at least %.1f%% of the pixels differ from the corner pixel and "
                                    "at least %d colours occur (python/packager_png.py gives the measurement behind "
                                    "both numbers)" % (PNG.BAND_ROWS, 100.0 * PNG.MIN_INK, PNG.MIN_COLOURS),
                       "each": "a PNG that fails either is refused and nothing is written"},
            "reproducibility": "the same converter on the same fonts gives the same bytes; a different machine may "
                               "draw the same SVG in other fonts (see fonts.used)"}

    all_paths = {rel for rel, _d in entries} | {"STATUS.md", "STATUS.html", "MANIFEST.json"}
    ctx = {"commit_sha": g["sha"], "commit_utc": g["committed"].strftime("%Y-%m-%d %H:%M:%S"),
           "tree_clean": g["clean"], "png": not no_png, "figures": figs, "light_docs": list(LIGHT_DOCS),
           "archive_paths": all_paths}
    try:
        text, facts, quotes, refs, reads, dropped = ST.build(rd, ctx)
    except (ST.SourceError, ST.DocError) as e:
        refuse("status-source", str(e))
    for rel in refs:
        if rel not in all_paths:
            refuse("status-source", "STATUS.md refers to %s, which the archive does not hold" % rel)
    add("STATUS.md", text.encode("utf-8"), kind="status", derived_from=sorted(reads),
        rule="python/packager_status.py reads the files listed under status_document.reads")
    page = HTML.render(text)
    found = HTML.check(text, page, all_paths)
    if found:
        raise Refused(found)
    add("STATUS.html", page.encode("utf-8"), kind="status-html", derived_from="STATUS.md",
        derived_from_sha256=meta["STATUS.md"]["sha256"],
        rule="python/packager_html.py renders STATUS.md, and --verify renders it again and compares the bytes; its text "
             "is checked word for word against the Markdown's")

    figures = []
    for fg in figs:
        rec = {"name": fg["name"], "origin": fg["origin"], "title": fg["title"], "svg": [fg["svg_light"], fg["svg_dark"]],
               "png": [fg["png_light"], fg["png_dark"]] if not no_png else None, "sidecar": fg["sidecar"],
               "sidecar_sha256": meta[fg["sidecar"]]["sha256"] if fg["sidecar"] else None,
               "caption": fg["caption_file"]}
        if fg["origin"] == "readme":
            rec["made_by"] = "python python/readme_charts.py " + " ".join(README_CHARTS_ARGS) + " --out docs/img/bench"
            rec["data"] = rc_data
            rec["fresh"] = "regenerated in a scratch directory by the command above: identical, byte for byte"
            rec["sidecar_note"] = "none exists for the README's charts"
        figures.append(rec)

    manifest = {
        "manifest_format": FORMAT,
        "what": "The manifest of a dated status archive of cft-fp256: every other file in the archive with its size, its "
                "SHA-256 and where it came from, and how the archive was made. It does not list itself.",
        "archive": {"name": stem, "file": stem + ".zip", "root_dir": stem, "created_utc": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "date_utc": created.strftime("%Y-%m-%d"), "clock": clock},
        "commit": {"sha": g["sha"], "short": g["sha"][:7], "tree": g["tree"],
                   "committed_utc": g["committed"].strftime("%Y-%m-%dT%H:%M:%SZ")},
        "tree": {"clean": g["clean"], "dirty_paths": g["dirty"],
                 "rule": "git status --porcelain=v1 --untracked-files=normal: empty means clean; ignored files are not listed"},
        "packager": {"scripts": script_digests(), "python": {"version": platform.python_version(),
                                                               "implementation": platform.python_implementation()},
                     "os": platform.system()},
        "checks": {"figures": {"command": "python python/project_figures.py --check" + (" " + " ".join(figure_check_args)
                                                                                        if figure_check_args else ""),
                               "result": "passed, before anything was read for the archive", "summary": summary},
                   "readme_charts": {"command": "python python/readme_charts.py " + " ".join(README_CHARTS_ARGS)
                                                + " --out SCRATCH",
                                     "result": "the four SVGs it writes equal the committed ones", "data": rc_data},
                   "sidecars": "each sidecar's figure, files, title, alt text and source digests agree with the figure, "
                               "the gallery and the tree",
                   "personal_paths": "no file bound for the archive, and not this manifest, holds a path under a "
                                     "user's directory (PNGs are binary and are not searched)"},
        "png": png_info,
        "zip": {"compression": "stored", "order": "sorted by path", "entry_time_utc": entry_stamp_text(g["committed"]),
                "entry_time_rule": "the commit's committer time in UTC, rounded down to an even second: a zip entry has "
                                   "no time zone and two-second resolution, so this wall-clock reading is UTC",
                "mode": "0644", "created_by_system": "unix", "root_dir": stem},
        "files": [],
        "figures": figures,
        "status_document": {"file": "STATUS.md", "facts": facts, "quotes": quotes, "refs": refs, "reads": reads,
                            "links_unlinked": sorted(set(dropped)),
                            "rule": "a number is printed only as a fact with a source and a rule, text only as a "
                                    "quotation from a named file; python/packager_status.py refuses a plain string with "
                                    "a digit in it"},
    }
    for rel, _d in sorted(entries, key=lambda e: e[0]):
        manifest["files"].append(dict(path=rel, **meta[rel]))
    mbytes = dumps(manifest).encode("utf-8")
    scan_leaks(entries + [("MANIFEST.json", mbytes)])
    entries.append(("MANIFEST.json", mbytes))

    out.mkdir(parents=True, exist_ok=True)
    part = out / (stem + ".zip.part")
    try:
        write_zip(part, stem, entries, g["committed"])
        bad = verify_archive(part)
        if bad:
            refuse("self-verify", "the archive just written does not verify: %s" % "; ".join("%s: %s" % b for b in bad[:3]))
        os.replace(str(part), str(target))
    finally:
        if part.exists():
            part.unlink()
    zbytes = target.read_bytes()
    return {"path": target, "bytes": len(zbytes), "sha256": sha256(zbytes), "manifest_sha256": sha256(mbytes),
            "files": len(entries), "pngs": 0 if no_png else 2 * len(figs), "dirty": not g["clean"],
            "seconds": time.monotonic() - started, "stem": stem}


def entry_stamp_text(when):
    s = entry_stamp(when)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % s


# ------------------------------------------------------------------------------------------------- verify
LINK = re.compile(r"(?<!\\)!?\[[^\]]*\]\(([^)\s]+)\)")


def sub(d, key):
    """d[key] if it is a dict, else an empty one: a manifest that is not what it should be answers 'no', not a traceback."""
    v = d.get(key) if isinstance(d, dict) else None
    return v if isinstance(v, dict) else {}


def verify_archive(path):
    """Re-hash an archive against its own manifest. Returns [] or a list of (code, message)."""
    problems = []

    def bad(code, msg):
        problems.append((code, msg))
    try:
        z = zipfile.ZipFile(str(path))
    except (zipfile.BadZipFile, OSError) as e:
        return [("archive-unreadable", "%s is not a zip archive (%s)" % (pathlib.Path(path).name, e))]
    with z:
        # an entry whose bytes fail their own CRC-32 is a damaged archive, said by name, and the check stops there:
        # nothing below can be read from it
        try:
            damaged = z.testzip()
        except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, OSError) as e:
            return [("archive-unreadable", "an entry of %s cannot be read from it (%s: %s)" % (
                pathlib.Path(path).name, type(e).__name__, e))]
        if damaged is not None:
            return [("archive-unreadable", "the entry %s of %s fails its own CRC-32: the zip is damaged" % (
                damaged, pathlib.Path(path).name))]
        infos = z.infolist()
        names = [i.filename for i in infos]
        if len(set(names)) != len(names):
            bad("archive-structure", "an entry name occurs more than once")
        roots = {n.split("/", 1)[0] for n in names}
        if len(roots) != 1 or any("/" not in n for n in names):
            return problems + [("archive-structure", "the entries are not all under one root directory")]
        root_dir = next(iter(roots))
        for n in names:
            parts = n.split("/")
            if n.startswith("/") or ".." in parts or "\\" in n or ":" in n:
                bad("archive-structure", "the entry %r would extract outside its directory" % n)
        mname = root_dir + "/MANIFEST.json"
        if mname not in names:
            return problems + [("manifest-missing", "the archive has no MANIFEST.json")]
        try:
            man = json.loads(z.read(mname).decode("utf-8"))
        except ValueError as e:
            return problems + [("manifest-unreadable", "MANIFEST.json does not parse (%s)" % e)]
        if (not isinstance(man, dict) or not isinstance(man.get("files"), list)
                or not all(isinstance(f, dict) and isinstance(f.get("path"), str) for f in man["files"])):
            return problems + [("manifest-unreadable", "MANIFEST.json is not a manifest: it has no list of files, each "
                                "with a path")]
        if man.get("manifest_format") != FORMAT:
            bad("manifest-unreadable", "MANIFEST.json is format %r; this reader knows %d" % (man.get("manifest_format"), FORMAT))
        arch, commit, tree, z_meta = (sub(man, k) for k in ("archive", "commit", "tree", "zip"))
        if str(commit.get("short")) != str(commit.get("sha"))[:7]:
            bad("manifest-mismatch", "MANIFEST.json gives the commit's short name as %r and its full name as %r, whose "
                "first seven characters differ" % (commit.get("short"), commit.get("sha")))
        # the manifest agrees with itself: the name is the date, the commit and the tree's state it records
        want = "%s-%s-%s%s" % (STEM, arch.get("date_utc"), commit.get("short"), "" if tree.get("clean") else "-dirty")
        if arch.get("name") != want or arch.get("root_dir") != root_dir:
            bad("manifest-mismatch", "MANIFEST.json gives the archive's name as %r and its directory as %r; its own date, "
                "commit and tree state make %r, and the archive's directory is %r" % (
                    arch.get("name"), arch.get("root_dir"), want, root_dir))
        if str(arch.get("created_utc"))[:10] != arch.get("date_utc"):
            bad("manifest-mismatch", "MANIFEST.json says it was created at %s on the date %s" % (
                arch.get("created_utc"), arch.get("date_utc")))
        if bool(tree.get("clean")) != (not tree.get("dirty_paths")):
            bad("manifest-mismatch", "MANIFEST.json says the tree was %s and lists %d differing path(s)" % (
                "clean" if tree.get("clean") else "not clean", len(tree.get("dirty_paths") or [])))
        try:
            stamp = entry_stamp_text(datetime.datetime.strptime(commit.get("committed_utc"), "%Y-%m-%dT%H:%M:%SZ")
                                     .replace(tzinfo=datetime.timezone.utc))
        except (TypeError, ValueError):
            stamp = None
        if stamp != z_meta.get("entry_time_utc"):
            bad("manifest-mismatch", "the commit's committer time %s, rounded down to an even second, is %s; MANIFEST.json "
                "says the entries are stamped %s" % (commit.get("committed_utc"), stamp, z_meta.get("entry_time_utc")))
        listed = {f["path"]: f for f in man["files"]}
        held = {n[len(root_dir) + 1:] for n in names} - {"MANIFEST.json"}
        for rel in sorted(held - set(listed)):
            bad("file-unlisted", "%s is in the archive and not in MANIFEST.json" % rel)
        for rel in sorted(set(listed) - held):
            bad("file-missing", "%s is in MANIFEST.json and not in the archive" % rel)
        data = {}
        for rel in sorted(held & set(listed)):
            b = z.read(root_dir + "/" + rel)
            data[rel] = b
            f = listed[rel]
            if len(b) != f.get("bytes"):
                bad("size-mismatch", "%s is %d bytes, MANIFEST.json says %s" % (rel, len(b), f.get("bytes")))
            if sha256(b) != f.get("sha256"):
                bad("hash-mismatch", "%s hashes to %s..., MANIFEST.json says %s..." % (rel, sha256(b)[:16], str(f.get("sha256"))[:16]))
        # the zip's own metadata is what the manifest says it is
        for i in infos:
            if i.compress_type != zipfile.ZIP_STORED or i.create_system != 3 or (i.external_attr >> 16) != ZIP_MODE:
                bad("zip-metadata", "%s is not stored, created by unix, mode 0644" % i.filename)
                break
        stamps = {"%04d-%02d-%02dT%02d:%02d:%02dZ" % i.date_time for i in infos}
        if stamps != {z_meta.get("entry_time_utc")}:
            bad("zip-metadata", "the entry times are %s where MANIFEST.json says %s" % (sorted(stamps), z_meta.get("entry_time_utc")))
        if [i.filename for i in infos] != sorted(names):
            bad("zip-metadata", "the entries are not sorted by path")
        # PNGs: the manifest says whether there are any, and each is the size it was rendered at and not blank
        png_files = sorted(r for r in listed if r.endswith(".png"))
        made = sub(man, "png").get("made")
        if made is False and png_files:
            bad("png-unexpected", "MANIFEST.json says no PNG was made, and the archive holds %d" % len(png_files))
        if made is True and not png_files:
            bad("png-missing", "MANIFEST.json says PNGs were made, and the archive holds none")
        for rel in png_files:
            if rel not in data:
                continue
            f = listed[rel]
            src = f.get("rendered_from")
            size = svg_size(data[src].decode("utf-8", "replace")) if src in data else None
            scale = f.get("scale") if isinstance(f.get("scale"), int) else 0
            expect = (size[0] * scale, size[1] * scale) if size else None
            facts, found = PNG.inspect(data[rel], expect=expect)
            for code, msg in found:
                bad(code, "%s: %s" % (rel, msg))
            if not found and (facts["width"], facts["height"]) != (f.get("width"), f.get("height")):
                bad("png-size", "%s is %d x %d, MANIFEST.json says %s x %s" % (
                    rel, facts["width"], facts["height"], f.get("width"), f.get("height")))
            if not found and (facts["band_rows"], facts["ink_pct"], facts["colours"]) != (
                    f.get("band_rows"), f.get("ink_pct"), f.get("colours")):
                bad("manifest-mismatch", "%s: its top %d rows hold %s%% non-background pixels in %d colours, and "
                    "MANIFEST.json says %s rows, %s%% and %s" % (rel, facts["band_rows"], facts["ink_pct"], facts["colours"],
                                                                f.get("band_rows"), f.get("ink_pct"), f.get("colours")))
            if src not in data:
                bad("png-source", "%s was rendered from %s, which the archive does not hold" % (rel, src))
        # each figure's sidecar still describes its SVGs
        for fg in (man["figures"] if isinstance(man.get("figures"), list) else []):
            if not isinstance(fg, dict):
                continue
            sc = fg.get("sidecar")
            if not sc or sc not in data:
                continue
            try:
                side = json.loads(data[sc].decode("utf-8"))
            except ValueError:
                bad("sidecar-mismatch", "%s does not parse" % sc)
                continue
            for rel in (fg["svg"] if isinstance(fg.get("svg"), list) else []):
                if rel in data:
                    title, label = svg_labels(data[rel].decode("utf-8", "replace"))
                    if label != side.get("alt") or title != side.get("alt"):
                        bad("sidecar-mismatch", "%s: its title and aria-label are not the alt text its sidecar %s gives" % (rel, sc))
            if side.get("figure") != fg.get("name"):
                bad("sidecar-mismatch", "%s describes figure %r, the manifest says %r" % (sc, side.get("figure"), fg.get("name")))
        # STATUS.md's links resolve inside the archive
        if "STATUS.md" in data:
            for target in LINK.findall(data["STATUS.md"].decode("utf-8", "replace")):
                t = target.split("#", 1)[0]
                if t and not t.startswith(("http://", "https://", "mailto:")) and t not in held | {"MANIFEST.json"}:
                    bad("link-dead", "STATUS.md links to %s, which the archive does not hold" % t)
        # STATUS.html is what the renderer makes of STATUS.md, and says what it says
        if "STATUS.md" in data and "STATUS.html" in data:
            md = data["STATUS.md"].decode("utf-8", "replace")
            page = data["STATUS.html"].decode("utf-8", "replace")
            if HTML.render(md) != page:
                bad("html-mismatch", "STATUS.html is not what python/packager_html.py makes of STATUS.md")
            for code, msg in HTML.check(md, page, held | {"MANIFEST.json"}):
                bad(code, "STATUS.html: " + msg)
        leaks = [r for r in data if not r.endswith(".png") and LEAK.search(data[r].decode("utf-8", "replace"))]
        if leaks:
            bad("personal-path", "%s holds a path under a user's directory" % leaks[0])
        if LEAK.search(z.read(mname).decode("utf-8", "replace")):
            bad("personal-path", "MANIFEST.json holds a path under a user's directory")
    return problems


# ---------------------------------------------------------------------------------------------------- CLI
def human(n):
    return "%.1f MiB" % (n / 1048576.0) if n >= 1048576 else "%.1f KiB" % (n / 1024.0)


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--verify", metavar="ARCHIVE", help="re-hash an archive against its manifest and check what it can")
    g.add_argument("--check", action="store_true", help="the packager's own self-test: plants each fault, needs no converter")
    ap.add_argument("--png", action="store_true", help="with --check: also build with the real converter")
    ap.add_argument("--root", default=str(ROOT), help="the repository's top (default: this one)")
    ap.add_argument("--out", default=DEFAULT_OUT, help="where to write, inside the tree only if git ignores it (default: "
                                                       "%s/)" % DEFAULT_OUT)
    ap.add_argument("--no-png", action="store_true", help="make no PNG renders (and need no converter)")
    ap.add_argument("--converter", metavar="PATH", help="an rsvg-convert to use instead of the one on PATH")
    ap.add_argument("--scale", type=int, default=SCALE_DEFAULT, help="PNG scale, 1 to 4 (default %d)" % SCALE_DEFAULT)
    ap.add_argument("--allow-dirty", action="store_true", help="export a dirty tree: the name ends -dirty and the manifest says so")
    ap.add_argument("--now", metavar="UTC", help="fix the clock, as 2026-10-19T17:31:02Z (so two builds compare byte for byte)")
    ap.add_argument("--force", action="store_true", help="replace an archive of the same name")
    ap.add_argument("--figure-check-args", default="", help=argparse.SUPPRESS)      # the self-test's: --no-controls
    a = ap.parse_args(argv)
    if a.png and not a.check:
        ap.error("--png goes with --check")
    if a.verify:
        bad = verify_archive(a.verify)
        if bad:
            for code, msg in bad:
                sys.stderr.write("project_packager: FAILED [%s] %s\n" % (code, msg))
            sys.stderr.write("project_packager: %d problem(s) in %s\n" % (len(bad), pathlib.Path(a.verify).name))
            return 1
        with zipfile.ZipFile(a.verify) as z:
            man = json.loads(z.read(z.namelist()[0].split("/")[0] + "/MANIFEST.json").decode("utf-8"))
        pngs = sum(1 for f in man["files"] if f["path"].endswith(".png"))
        print("project_packager: %s verifies: %d files re-hashed against MANIFEST.json, %s, the manifest and the zip's "
              "metadata agree with each other" % (
                  pathlib.Path(a.verify).name, len(man["files"]),
                  "%d PNGs checked for size and for not being blank" % pngs if pngs else
                  "no PNG (the archive was made with --no-png)"))
        return 0
    if a.check:
        import packager_check
        try:
            return packager_check.main(pathlib.Path(a.root), a.png)
        except Exception as e:                        # a defect in the check itself, said once and plainly
            import traceback
            sys.stderr.write(packager_check.defuse(traceback.format_exc()))
            print("project_packager: --check crashed, which is a defect in it: %s: %s" % (
                type(e).__name__, packager_check.defuse(str(e))[:200]))
            return 1
    if not 1 <= a.scale <= 4:
        ap.error("--scale is 1 to 4")
    try:
        res = build(a.root, a.out, no_png=a.no_png, converter=a.converter, scale=a.scale, allow_dirty=a.allow_dirty,
                    now=parse_now(a.now) if a.now else None, force=a.force,
                    figure_check_args=tuple(a.figure_check_args.split()))
    except Refused as r:
        for code, msg in r.items:
            sys.stderr.write("project_packager: REFUSED [%s] %s\n" % (code, msg))
        sys.stderr.write("project_packager: nothing was written\n")
        return 1
    try:
        shown = res["path"].relative_to(pathlib.Path(a.root).resolve()).as_posix()
    except ValueError:
        shown = str(res["path"])
    print("project_packager: wrote %s (%s, %d files%s) in %.0f s" % (
        shown, human(res["bytes"]), res["files"], ", %d PNGs" % res["pngs"] if res["pngs"] else ", no PNG",
        res["seconds"]))
    print("  zip sha256       %s" % res["sha256"])
    print("  MANIFEST.json    %s" % res["manifest_sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
