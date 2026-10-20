# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""packager_check: `python python/project_packager.py --check`, the packager's own self-test.

A check that cannot fail is a defect, so this plants each fault the packager claims to refuse, in a scratch copy
of the tree, and requires the packager to name it. It needs no converter: the PNG legs are covered by the PNG
reader's own plants (python/packager_png.py) and by archives it builds around synthetic PNGs, so the check can
run in the gate's `generated` stage, where a converter may not exist and a check that skipped would fail
`--require-all`. `--check --png` adds the legs that need one, and refuses by name if there is none.

WHAT IT DOES (no count is written here: the report it prints counts what it ran)
  1. The real tree: can an archive be made from it? The figures and sidecars agree, STATUS.md builds, lints (no
     typed number) and links only to files the archive would hold, and its page says its words. No git, no
     writing. This is the leg that fails when an edit to the README, the gallery or a sidecar breaks a reader.
  2. The template's own rules, and each reader's refusal to default: a typed number, a fact without a source or a
     rule, one unregistered, one never printed, a quotation likewise, a source that no longer says what is expected.
  3. The PNG reader: the decoder against the encoder on every filter and both colour types, and each kind of
     damaged, unsupported or blank image planted. The HTML check: a page that drops a word, adds one, loses a
     tag or links to a file the archive lacks.
  4. A scratch copy of exactly the files the packager and the figure check read (the copy is the proof of that: a
     read of any other file fails), committed in a git repository of its own. In it:
       - a build, and `--verify` of it;
       - reproducibility: the same commit and the same clock give the same zip byte for byte, in this process
         and in another under another PYTHONHASHSEED; a different clock changes MANIFEST.json's date fields and
         nothing else;
       - every refusal in docs/EXPORT.md's table, each planted and each required under its own code: where it is
         run (no git; a root that is not a work tree, or not its top); a figure, a sidecar, an SVG, a source, an
         extract, a caption, a light document, a README chart or the README's picture of one, changed or removed; a
         figure check gutted to exit 0 and say nothing; sidecars corrupted past a stubbed figure check; a personal
         path; the README's heading gone; a dirty tree, with a second fault beside it, and one allowed; no
         converter, a tool that is not one or cannot be run, and a fake that fails or writes a blank, half-size,
         16-bit or non-PNG image; an output directory git does not ignore; an archive already there; and the
         refusals that stand for a defect in the packager itself (a page that is not its Markdown, a status
         document that names a file the archive lacks, an archive that does not verify once written), planted by
         replacing that one function for the length of one build;
       - the archive's own checks, each planted in an archive rewritten so that the hash check cannot see it,
         one check at a time (a manifest that disagrees with itself, a zip whose metadata is not what it says, a
         dead link, a page that is not the Markdown's, a sidecar that no longer describes its SVG, a PNG that is
         blank, the wrong size, damaged or not from the archive, ...).
Everything is refused or failed BY NAME, and a plant the packager does not name is this check's failure.
"""
import copy
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import figure_extracts as X                                          # noqa: E402  (dumps: a sidecar's own serialiser)
import packager_html as HTML                                         # noqa: E402
import packager_png as PNG                                           # noqa: E402
import packager_status as ST                                         # noqa: E402
import project_packager as PK                                        # noqa: E402

UTC = datetime.timezone.utc
NOT_RUN = []        # plants that cannot run on this platform: counted and named apart from the controls that ran
NOW = datetime.datetime(2026, 10, 19, 12, 0, 0, tzinfo=UTC)
# The path the plants write, assembled so that this file itself carries no path under a user's directory.
PLANTED_PATH = ("C:" + "/" + "Users" + "/someone/notes").encode("ascii")
FAST = ("--no-controls",)            # project_figures --check without its own plants: the figures' freshness, whole


def quiet(*_a, **_k):
    pass


# A converter that answers `--version` as rsvg-convert does and then does what its mode file says, so that the
# packager's refusals of a bad render can be planted without a real converter: it can fail, write an image that is
# blank or the wrong size, or write bytes that are not a PNG. (Its good mode is not used here: the packager's good
# renders are the real converter's, in `--check --png`.)
FAKE_CONVERTER = r"""
import pathlib
import re
import sys

here = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, @@HERE@@)
import packager_png as P

args = sys.argv[1:]
mode = (here / "mode.txt").read_text().strip()
if args == ["--version"]:
    print("rsvg-convert version 9.9.9")
    sys.exit(1 if mode == "version-fails" else 0)
fmt = args[args.index("-f") + 1]
out = args[args.index("-o") + 1]
text = open(args[-1], encoding="utf-8").read()
m = re.search(r'<svg\b[^>]*?\bwidth="(\d+)"[^>]*?\bheight="(\d+)"', text)
w, h = int(m.group(1)), int(m.group(2))
if fmt == "pdf":
    open(out, "wb").write(b"%PDF-1.5\n/BaseFont /ABCDEF+FakeSans\n")
    sys.exit(0)
if mode == "fail":
    sys.stderr.write("the fake converter fails on purpose\n")
    sys.exit(1)
if mode == "nothing":
    sys.exit(0)                      # says it succeeded and writes no file
if mode == "garbage":
    open(out, "wb").write(b"this is not a PNG")
    sys.exit(0)
zoom = float(args[args.index("--zoom") + 1]) if "--zoom" in args else 1.0
W, H = int(w * zoom), int(h * zoom)
if mode == "fail-late":
    open(out, "wb").write(P.encode(W, H, P._synthetic(W, H, 3, ink=True, seed=5, ink_rows=min(H, P.BAND_ROWS)), 2))
    sys.stderr.write("the fake converter writes its image and then fails\n")
    sys.exit(1)
if mode == "wrong-size":
    W, H = W // 2, H // 2
if mode == "sixteen-bit":
    open(out, "wb").write(P._raw(W, H, 16, 2, (b"\x00" + bytes(W * 6)) * H))
    sys.exit(0)
rows = P._synthetic(W, H, 3, ink=(mode != "blank"), seed=5, ink_rows=min(H, P.BAND_ROWS))
open(out, "wb").write(P.encode(W, H, rows, 2))
"""


def make_fake_converter(tmp, mode):
    d = pathlib.Path(tmp) / "fake"
    d.mkdir(exist_ok=True)
    (d / "fake_rsvg.py").write_text(FAKE_CONVERTER.replace("@@HERE@@", repr(str(HERE))), encoding="utf-8", newline="\n")
    (d / "mode.txt").write_text(mode, encoding="ascii")
    if os.name == "nt":
        exe = d / "rsvg-convert.cmd"
        exe.write_bytes(('@"%s" -B "%s" %%*\r\n' % (sys.executable, d / "fake_rsvg.py")).encode("ascii"))
    else:
        exe = d / "rsvg-convert"
        exe.write_bytes(('#!/bin/sh\nexec "%s" -B "%s" "$@"\n' % (sys.executable, d / "fake_rsvg.py")).encode("ascii"))
        exe.chmod(0o755)
    return str(exe)


# ------------------------------------------------------------------------------------------ the real tree
def archive_paths_for(figs):
    paths = {"STATUS.md", "STATUS.html", "MANIFEST.json"} | {rel for rel, _w in PK.LIGHT_DOCS}
    for fg in figs:
        paths.update([fg["svg_light"], fg["svg_dark"], fg["png_light"], fg["png_dark"], fg["caption_file"]])
        if fg["sidecar"]:
            paths.add(fg["sidecar"])
    return paths


def real_tree(root, report):
    """Problems (strings) that stop an archive being made from this tree, found without git and without writing."""
    rd = ST.Reader(root)
    figs, probs = PK.collect_figures(root, rd)
    if probs:
        return ["the tree: %s: %s" % p for p in probs]
    ctx = {"commit_sha": "0" * 40, "commit_utc": "1980-01-01 00:00:00", "tree_clean": True, "png": True,
           "figures": figs, "light_docs": list(PK.LIGHT_DOCS), "archive_paths": archive_paths_for(figs)}
    err = None
    try:
        text, facts, quotes, refs, reads, dropped = ST.build(rd, ctx)
    except (ST.SourceError, ST.DocError) as e:
        err = e
    crlf = PK.crlf_read(root, rd)                 # as a build does: before the reason a CRLF file may have broken a reader
    if crlf:
        return ["the tree: %s: %s" % PK.crlf_problem(crlf)]
    if err is not None:
        return ["the tree: STATUS.md cannot be made: %s" % err]
    out = []
    for rel in refs:
        if rel not in ctx["archive_paths"]:
            out.append("the tree: STATUS.md refers to %s, which the archive would not hold" % rel)
    for target in PK.LINK.findall(text):
        t = target.split("#", 1)[0]
        if t and not t.startswith(("http://", "https://", "mailto:")) and t not in ctx["archive_paths"]:
            out.append("the tree: STATUS.md would link to %s, which the archive would not hold" % t)
    for code, msg in HTML.check(text, HTML.render(text), ctx["archive_paths"]):
        out.append("the tree: STATUS.html would not hold: %s: %s" % (code, msg))
    if not out:
        report.append("the real tree: %d figures, their sidecars agree with them and the gallery; STATUS.md builds from "
                      "%d facts and %d quotations read from %d files, every link in it would resolve, and its HTML "
                      "says the same words" % (len(figs), len(facts), len(quotes), len(reads)))
    return out


def html_plants():
    """The renderer's check, planted: a page that says what the Markdown says passes, and each way of not doing so
    is named."""
    problems, report = [], []
    md = ("# Title\n\nA paragraph with `code`, **bold** and a [link](a.md).\n\n| a | b |\n|---|---|\n| first | second |\n\n"
          "> quoted\n> - item one\n\n![alt text](p.png)\n")
    page = HTML.render(md)
    held = {"a.md", "p.png"}
    clean = HTML.check(md, page, held)
    if clean:
        problems.append("html control: a page rendered from a plain document is refused: %s" % clean[0][1])
    else:
        report.append("html control: a page rendered from a document of every kind of block says the same words, balances "
                      "its tags and links to files the archive holds")
    if HTML.render(md) != page:
        problems.append("html: the renderer is not a pure function of the text")
    plants = [
        ("a word dropped from the page", page.replace("paragraph", "", 1), held, "html-text"),
        ("a word added to the page", page.replace("quoted", "quoted extra", 1), held, "html-text"),
        ("a table cell dropped", page.replace("<td>second</td>", "", 1), held, "html-text"),
        ("a closing tag removed", page.replace("</table>", "", 1), held, "html-malformed"),
        ("a closing tag too many", page.replace("</p>", "</p></p>", 1), held, "html-malformed"),
        ("a page that ends with a tag still open", page.replace("</html>", "", 1), held, "html-malformed"),
        ("a link to a file the archive does not hold", page, {"p.png"}, "html-link"),
        ("a picture the archive does not hold", page, {"a.md"}, "html-link"),
    ]
    for label, broken, h, code in plants:
        found = codes_of(HTML.check(md, broken, h))
        if code in found:
            report.append("html plant, %s: %s" % (label, code))
        else:
            problems.append("html plant, %s: not named %s (it gave %s)" % (label, code, found or "nothing"))
    return problems, report


# --------------------------------------------------------------------------------------- the template's rules
def status_plants():
    problems, report = [], []

    def must(label, fn, exc, word):
        try:
            fn()
        except exc as e:
            if word in str(e):
                report.append("template plant, %s: refused (%s)" % (label, word))
            else:
                problems.append("template plant, %s: refused, but not as '%s': %s" % (label, word, str(e)[:100]))
        else:
            problems.append("template plant, %s: not refused" % label)

    src = [{"path": "x", "sha256": "0" * 64, "reads": "x"}]

    def render_ok():
        d = ST.Doc()
        f = d.fact("n", 5, "5", src, "a rule")
        q = d.quote("q", "text", src[0], "a rule")
        d.line("cft-fp256 has ", f, " things and SHA-256 sums; ", q, " is quoted, at ", d.ref("a/b.md"))
        text, facts, quotes, refs = d.render()
        return text
    try:
        text = render_ok()
        if text != "cft-fp256 has 5 things and SHA-256 sums; text is quoted, at a/b.md\n":
            problems.append("template: a clean line rendered as %r" % text)
        else:
            report.append("template control: a line made of a fact, a quotation, a path and two allowed names renders")
    except ST.DocError as e:
        problems.append("template: a clean line was refused: %s" % e)

    def typed():
        ST.Doc().line("52 stages")

    def formatted():
        ST.Doc().line("%d stages" % 52)

    def nosource():
        ST.Doc().fact("n", 1, "1", [], "a rule")

    def norule():
        ST.Doc().fact("n", 1, "1", src, "")

    def unregistered():
        d = ST.Doc()
        d.line("x ", ("F", "ghost"))
        d.render()

    def unprinted():
        d = ST.Doc()
        d.fact("n", 1, "1", src, "a rule")
        d.line("nothing")
        d.render()

    def unquoted():
        d = ST.Doc()
        d.line(d.block("ghost"))
        d.render()

    def unprinted_quote():
        d = ST.Doc()
        d.quote("q", "text", src[0], "a rule")
        d.line("nothing")
        d.render()
    must("a number typed into the text", typed, ST.DocError, "digit")
    must("a count formatted into a string by code", formatted, ST.DocError, "digit")
    must("a fact with no source", nosource, ST.DocError, "no source")
    must("a fact with no rule", norule, ST.DocError, "no rule")
    must("a fact one of whose sources is empty", lambda: ST.Doc().fact("n", 1, "1", [src[0], None], "a rule"), ST.DocError,
         "no source")
    must("a quotation with no source", lambda: ST.Doc().quote("q", "text", None, "a rule"), ST.DocError, "no source or rule")
    must("a quotation with no rule", lambda: ST.Doc().quote("q", "text", src[0], ""), ST.DocError, "no source or rule")

    def unregistered_inline_quote():
        d = ST.Doc()
        d.line("x ", ("Q", "ghost"))
        d.render()

    def shared_block():
        d = ST.Doc()
        d.quote("q", "text", src[0], "a rule")
        d.line("beside ", d.block("q"))
        d.render()
    must("a quotation used inline and never registered", unregistered_inline_quote, ST.DocError, "not registered")
    must("a block quotation on a line that holds other text", shared_block, ST.DocError, "shares its line")

    def fact_twice():
        d = ST.Doc()
        d.fact("n", 1, "1", src, "a rule")
        d.fact("n", 2, "2", src, "a rule")

    def quote_twice():
        d = ST.Doc()
        d.quote("q", "a", src[0], "a rule")
        d.quote("q", "b", src[0], "a rule")
    must("a fact registered twice", fact_twice, ST.DocError, "registered twice")
    must("a quotation registered twice", quote_twice, ST.DocError, "registered twice")
    must("a part that is not a string, a fact, a quotation or a path", lambda: ST.Doc().line(5), ST.DocError, "neither a string")
    must("a fact used and never registered", unregistered, ST.DocError, "not registered")
    must("a fact registered and never printed", unprinted, ST.DocError, "never printed")
    must("a quotation used and never registered", unquoted, ST.DocError, "not registered")
    must("a quotation registered and never printed", unprinted_quote, ST.DocError, "never printed")
    must("a count that finds nothing is not zero", lambda: ST.count_lines("no stages here", r"^stage ", "stage lines", "x"),
         ST.SourceError, "no stage lines")
    must("a document that is read for its newest date and writes none", lambda: ST.newest_written_date("no date here", "x"),
         ST.SourceError, "writes no date")
    must("a README with no title", lambda: ST.readme_summary("text with no title"), ST.SourceError,
         "does not begin with its title")
    must("a README with no table of what is built", lambda: ST.readme_built("# t\n\n## Other\n\ntext\n"),
         ST.SourceError, "What is built and working")
    must("a gallery with no table", lambda: ST.parse_gallery("# nothing\n"), ST.SourceError, "table of figures")
    must("a README with nothing under its title", lambda: ST.readme_summary("# T\n\n## Next\n"), ST.SourceError,
         "nothing between")
    must("a README whose built section holds no table",
         lambda: ST.readme_built("## What is built and working\n\nno table here\n\n## Next\n"), ST.SourceError, "holds no table")
    must("a gallery table that lists a figure it does not describe",
         lambda: ST.parse_gallery("| [a](#a) | t |\n\n## G\n"), ST.SourceError, "not the figures it describes")
    must("a gallery block with no title",
         lambda: ST.parse_gallery('| [a](#a) | t |\n\n## G\n\n<a id="a"></a>\n\n<picture>\n  <img alt="x" src="s">\n'
                                  "</picture>\n\n**Shows.** x\n"), ST.SourceError, "no `### ` title")
    def gallery(title="### T\n\n", img='  <img alt="x" src="s">\n', close="</picture>\n\n", shows="**Shows.** a\n\n",
                not_shows="**Does not show.** b\n\n", source="**Source.** c\n"):
        """A one-figure gallery, complete unless a piece is given another value."""
        return ('| [a](#a) | t |\n\n## G\n\n<a id="a"></a>\n\n' + title + "<picture>\n" + img + close + shows + not_shows + source)
    try:
        if [g["name"] for g in ST.parse_gallery(gallery())] == ["a"]:
            report.append("template control: a complete one-figure gallery parses")
        else:
            problems.append("template: a complete one-figure gallery did not parse as one figure")
    except ST.SourceError as e:
        problems.append("template: a complete one-figure gallery was refused: %s" % e)
    must("a gallery block with a title and no alt text", lambda: ST.parse_gallery(gallery(img='  <img src="s">\n')),
         ST.SourceError, "no <img alt>")
    must("a gallery block with no </picture>", lambda: ST.parse_gallery(gallery(close="")), ST.SourceError, "no </picture>")
    must("a gallery caption with no Shows paragraph", lambda: ST.parse_gallery(gallery(shows="")), ST.SourceError,
         "no `**Shows.**`")
    must("a gallery caption with no Does-not-show paragraph", lambda: ST.parse_gallery(gallery(not_shows="")), ST.SourceError,
         "no `**Does not show.**`")
    must("a gallery caption with no Source paragraph", lambda: ST.parse_gallery(gallery(source="")), ST.SourceError,
         "no `**Source.**`")
    with tempfile.TemporaryDirectory(prefix="packager-reader-") as tmp:
        t = pathlib.Path(tmp)
        (t / "verify").mkdir()
        (t / "verify" / "run.sh").write_text("# a runner with no stage lines\nBUDGET_QUICK=a\nBUDGET_GATE=a\n", encoding="utf-8")
        (t / "docs").mkdir()
        (t / "docs" / "VALIDATION.md").write_text("# a ledger with no entries\n", encoding="utf-8")
        must("a runner with no stage lines", lambda: ST.read_runner(ST.Reader(t)), ST.SourceError, "no stage lines")
        must("a ledger with no entries", lambda: ST.read_ledger(ST.Reader(t)), ST.SourceError, "no `## ` heading")
        must("a file that is not there", lambda: ST.Reader(t).text("docs/NOPE.md"), ST.SourceError, "is not in the tree")
        (t / "docs" / "latin1.md").write_bytes(b"caf" + bytes([0xE9]) + b"\n")
        must("a file that is not UTF-8 text", lambda: ST.Reader(t).text("docs/latin1.md"), ST.SourceError, "is not UTF-8 text")
        (t / "docs" / "bad.json").write_text("{ not json", encoding="utf-8")
        must("a JSON file that does not parse", lambda: ST.Reader(t).json("docs/bad.json"), ST.SourceError,
             "does not parse as JSON")
        (t / "docs" / "VALIDATION.md").write_text("# a ledger\n\n## an undated heading\n", encoding="utf-8")
        must("a ledger with no dated heading", lambda: ST.read_ledger(ST.Reader(t)), ST.SourceError, "begins with a date")
        (t / "docs" / "VALIDATION.md").write_text("# a ledger\n\n## 2026-01-01 - one\n\n## an undated newest\n", encoding="utf-8")
        must("a ledger whose newest heading is not dated", lambda: ST.read_ledger(ST.Reader(t)), ST.SourceError,
             "newest entry's heading")
        (t / "docs" / "ROADMAP.md").write_text("# a roadmap\n\n## a heading\n", encoding="utf-8")
        must("a roadmap with no plan of record", lambda: ST.read_plan(ST.Reader(t)), ST.SourceError, "plan of record")
        (t / "verify" / "run.sh").write_text('stage a "x"\nstage b "y"\n', encoding="utf-8")
        must("a runner with stages and no budget lists", lambda: ST.read_runner(ST.Reader(t)), ST.SourceError, "no BUDGET_QUICK")
        (t / "verify" / "run.sh").write_text('stage a "x"\nBUDGET_QUICK=a,b,c\nBUDGET_GATE=a\n', encoding="utf-8")
        must("budgets that are not nested", lambda: ST.read_runner(ST.Reader(t)), ST.SourceError, "not nested")
        (t / "verify" / "run.sh").write_text('stage a "x"\nBUDGET_QUICK=a\nBUDGET_GATE=a,b\n', encoding="utf-8")
        must("a gate budget with more members than there are stages", lambda: ST.read_runner(ST.Reader(t)), ST.SourceError,
             "not nested")
        (t / "tb").mkdir()
        (t / "tb" / "Makefile").write_text("# a Makefile with no bench list\n", encoding="utf-8")
        must("a Makefile with no bench list", lambda: ST.read_benches(ST.Reader(t)), ST.SourceError, "cannot read the bench list")
        empty = t / "empty"
        (empty / "python" / "tests").mkdir(parents=True)
        (empty / "docs" / "img" / "figures").mkdir(parents=True)
        must("a test directory with no test file", lambda: ST.read_tests(ST.Reader(empty)), ST.SourceError, "holds no .py file")
        must("a directory of sidecars with none in it", lambda: ST.read_sidecar_claims(ST.Reader(empty)), ST.SourceError,
             "holds no sidecar")
        (t / "python" / "tests").mkdir(parents=True)
        (t / "python" / "tests" / "t.py").write_text("x = 1\n", encoding="utf-8")
        must("a test directory that defines no test", lambda: ST.read_tests(ST.Reader(t)), ST.SourceError, "no test function")
        (t / "docs" / "img" / "figures").mkdir(parents=True)
        (t / "docs" / "img" / "figures" / "x.json").write_text("{}", encoding="utf-8")
        must("a sidecar with no checks list", lambda: ST.read_sidecar_claims(ST.Reader(t)), ST.SourceError, "no `checks`")
        must("a sidecar without the field a fact reads",
             lambda: ST.Reader(t).field("docs/img/figures/x.json", "data", "a"), ST.SourceError, "has no field")
    return problems, report


# ----------------------------------------------------------------------------------------------- scratch
def sgit(S, *args):
    cmd = ["git", "-c", "core.autocrlf=false", "-c", "user.name=packager-check",
           "-c", "user.email=packager-check@example.invalid", "-c", "commit.gpgsign=false", "-C", str(S)] + list(args)
    p = subprocess.run(cmd, capture_output=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("git %s failed in the scratch tree: %s" % (" ".join(args[:2]), p.stderr.decode("utf-8", "replace")[:200]))
    return p.stdout.decode("utf-8", "replace")


def needed_files(root):
    """Every file the figure check and the packager read: the figure check's own list (python/project_figures.py's
    controls compute it the same way), the packager's, and the scripts."""
    import figure_extracts as X
    import project_figures as PF
    try:
        results = PF.build_all(str(root))
        need = set()
        for r in results:
            need.update(r.src.needed())
        need.update(PF.outputs(results))
    except AttributeError as e:
        raise RuntimeError("python/project_figures.py no longer offers what its own controls use to find the files a "
                           "figure reads (build_all, outputs, Src.needed: %s); packager_check.needed_files must follow it" % e)
    for p in (root / X.EXTRACT_DIR).glob("*.json"):
        need.add(X.EXTRACT_DIR + "/" + p.name)
        for s in json.loads(p.read_text(encoding="utf-8"))["sources"]:
            if s.get("kind") in ("file", "file-prefix"):
                need.add(s["path"])
    need.update(["python/project_figures.py", "python/figure_kit.py", "python/figure_extracts.py",
                 "python/readme_charts.py", ".gitattributes", "docs/VALIDATION.md", "docs/ROADMAP.md",
                 "verify/run.sh", "tb/Makefile", "formal/run.sh"])
    need.update(rel for rel, _why in PK.LIGHT_DOCS)
    need.update(PK.README_CHARTS_DATA)
    need.update(str(p.relative_to(root)).replace("\\", "/") for p in (root / "python" / "tests").rglob("*.py"))
    for d in (PK.FIG_DIR, PK.BENCH_DIR):
        need.update("%s/%s" % (d, p.name) for p in (root / d).iterdir() if p.is_file())
    return sorted(need)


def make_scratch(root, S):
    files = needed_files(root)
    for rel in files:
        dst = S / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(root / rel), str(dst))
    (S / ".gitignore").write_text("/exports/\n__pycache__/\n*.pyc\n", encoding="utf-8", newline="")
    sgit(S, "init", "-q")
    sgit(S, "add", "-A")
    sgit(S, "commit", "-q", "--no-verify", "-m", "scratch copy of the files the packager reads")
    return len(files), sgit(S, "rev-parse", "HEAD").strip()


def mutate(S, rel, fn, commit=True):
    p = S / rel
    b = p.read_bytes()
    nb = fn(b)
    if nb == b:
        raise RuntimeError("the plant on %s changed nothing" % rel)
    p.write_bytes(nb)
    if commit:
        sgit(S, "commit", "-q", "--no-verify", "-am", "plant: " + rel)


def bump_digit_after(marker):
    """Add one to the first digit after `marker`: a one-character change that keeps the text well formed."""
    def fn(b):
        i = b.index(marker) + len(marker)
        while not chr(b[i]).isdigit():
            i += 1
        return b[:i] + bytes([ord("0") + (b[i] - ord("0") + 1) % 10]) + b[i + 1:]
    return fn


def add_file(S, rel, data):
    p = S / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    sgit(S, "add", "-A")
    sgit(S, "commit", "-q", "--no-verify", "-m", "plant: add " + rel)


def restore(S, c0):
    sgit(S, "reset", "-q", "--hard", c0)
    sgit(S, "clean", "-q", "-fd")


# ------------------------------------------------------------------------------------------ the archives
def load_archive(path):
    with zipfile.ZipFile(str(path)) as z:
        names = z.namelist()
        root_dir = names[0].split("/")[0]
        files = {n[len(root_dir) + 1:]: z.read(n) for n in names}
    man = json.loads(files["MANIFEST.json"].decode("utf-8"))
    when = datetime.datetime.strptime(man["zip"]["entry_time_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return root_dir, files, man, when


def save_archive(path, root_dir, files, man, when):
    f = dict(files)
    f["MANIFEST.json"] = PK.dumps(man).encode("utf-8")
    PK.write_zip(path, root_dir, list(f.items()), when)


def set_file(files, man, rel, data):
    """Change a file AND its manifest entry, so that the hash check agrees and only a deeper check can see it."""
    files[rel] = data
    for f in man["files"]:
        if f["path"] == rel:
            f["bytes"], f["sha256"] = len(data), PK.sha256(data)


def codes_of(found):
    return [c for c, _m in found]


def synthetic_png(w, h, kind):
    if kind == "good":
        return PNG.encode(w, h, PNG._synthetic(w, h, 3, ink=True, seed=3, ink_rows=min(h, PNG.BAND_ROWS)), 2)
    if kind == "blank":
        return PNG.encode(w, h, [bytes([250, 251, 252]) * w] * h, 2)
    if kind == "wrong-size":
        return PNG.encode(w // 2, h // 2, PNG._synthetic(w // 2, h // 2, 3, ink=True, seed=3, ink_rows=min(h // 2, PNG.BAND_ROWS)), 2)
    if kind == "sixteen-bit":
        return PNG._raw(w, h, 16, 2, (b"\x00" + bytes(w * 6)) * h)
    data = bytearray(synthetic_png(w, h, "good"))
    if kind == "corrupt":
        data[data.index(b"IDAT") + 12] ^= 0x40
    elif kind == "truncated":
        data = data[:len(data) // 2]
    return bytes(data)


def archive_plants(base_zip, tmp, report, problems):
    root_dir, files, man, when = load_archive(base_zip)
    n = [0]
    fig0 = man["figures"][0]["name"]                  # the first figure of the gallery: no figure is named here by hand

    def run(label, code, edit, only=True, writer=None, allow=()):
        f, m = dict(files), copy.deepcopy(man)
        w = when
        edit(f, m)
        n[0] += 1
        p = pathlib.Path(tmp) / ("plant-%d.zip" % n[0])
        if writer:
            writer(p, f, m)
        else:
            save_archive(p, root_dir, f, m, w)
        found = PK.verify_archive(p)
        codes = codes_of(found)
        if code is None:
            if found:
                problems.append("archive control, %s: a good archive was refused: %s" % (label, found[0][1][:100]))
            else:
                report.append("archive control, %s: verifies" % label)
        elif code not in codes:
            problems.append("archive plant, %s: --verify did not say %s (it said %s)" % (label, code, codes or "nothing"))
        elif only and not set(codes) <= {code} | set(allow):
            problems.append("archive plant, %s: --verify said %s, which is more than %s alone" % (label, sorted(set(codes)), code))
        else:
            report.append("archive plant, %s: %s" % (label, code))
        return found

    victim = "%s/%s-light.svg" % (PK.FIG_DIR, fig0)
    run("a file changed by one digit, manifest untouched", "hash-mismatch",
        lambda f, m: f.__setitem__(victim, bump_digit_after(b"</title>")(f[victim])))
    run("a file removed", "file-missing", lambda f, m: f.pop("%s/%s-dark.svg" % (PK.FIG_DIR, fig0)))
    run("a file added that the manifest does not list", "file-unlisted", lambda f, m: f.__setitem__("extra.txt", b"x"))
    run("a digest in the manifest changed", "hash-mismatch",
        lambda f, m: [x.__setitem__("sha256", "0" * 64) for x in m["files"] if x["path"] == victim])

    def metadata(p, f, m):
        save_archive(p, root_dir, f, m, when + datetime.timedelta(days=1, seconds=2))
    run("the zip's entry times changed", "zip-metadata", lambda f, m: None, writer=metadata)

    def deflated(p, f, m):
        f = dict(f)
        f["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
        with zipfile.ZipFile(str(p), "w", zipfile.ZIP_DEFLATED) as z:
            for rel, data in sorted(f.items()):
                zi = zipfile.ZipInfo(root_dir + "/" + rel, date_time=PK.entry_stamp(when))
                zi.compress_type = zipfile.ZIP_DEFLATED
                zi.create_system = 3
                zi.external_attr = PK.ZIP_MODE << 16
                z.writestr(zi, data)
    run("the zip compressed after all", "zip-metadata", lambda f, m: None, writer=deflated)
    def dead_link(f, m):
        md = f["STATUS.md"] + b"\n[x](docs/NOPE.md)\n"
        set_file(f, m, "STATUS.md", md)
        set_file(f, m, "STATUS.html", HTML.render(md.decode("utf-8")).encode("utf-8"))   # the page follows the Markdown
    run("STATUS.md linking to a file the archive lacks (the page re-rendered, hashes updated)", "link-dead", dead_link,
        allow=("html-link",))
    side = "%s/%s.json" % (PK.FIG_DIR, fig0)
    cap = "captions/%s.md" % fig0

    def alt_edited(f, m):
        d = json.loads(f[side].decode("utf-8"))
        d["alt"] = d["alt"] + " (edited)"
        set_file(f, m, side, (json.dumps(d, indent=1) + "\n").encode("utf-8"))
    run("a sidecar whose alt text is no longer its SVG's (hash updated)", "sidecar-mismatch", alt_edited)
    run("a sidecar that is not JSON (hash updated)", "sidecar-mismatch", lambda f, m: set_file(f, m, side, b"{ not json"))
    run("an SVG whose title is no longer its sidecar's alt text, its aria-label as it was (hash updated)", "sidecar-mismatch",
        lambda f, m: set_file(f, m, victim, f[victim].replace(b"<title>", b"<title>Edited: ", 1)))
    run("an SVG whose aria-label is no longer its sidecar's alt text, its title as it was (hash updated)", "sidecar-mismatch",
        lambda f, m: set_file(f, m, victim, f[victim].replace(b'aria-label="', b'aria-label="Edited: ', 1)))
    run("a personal path in a caption (hash updated)", "personal-path",
        lambda f, m: set_file(f, m, cap, f[cap] + b"\n" + PLANTED_PATH + b"\n"))
    page = "STATUS.html"
    run("STATUS.html changed by a comment no browser shows (hash updated)", "html-mismatch",
        lambda f, m: set_file(f, m, page, f[page] + b"<!-- edited -->\n"))
    run("STATUS.html saying something else (hash updated)", "html-text",
        lambda f, m: set_file(f, m, page, f[page].replace(b"was clean", b"was spotless", 1)), only=False)
    run("STATUS.html with a tag left open (hash updated)", "html-malformed",
        lambda f, m: set_file(f, m, page, f[page].replace(b"</body>", b"<div></body>", 1)), allow=("html-mismatch",))
    run("STATUS.html naming a file the archive lacks, in a link with no words (hash updated)", "html-link",
        lambda f, m: set_file(f, m, page, f[page].replace(b"</body>", b'<a href="docs/NOPE.md"></a></body>', 1)),
        allow=("html-mismatch",))

    def notzip(p, f, m):
        pathlib.Path(p).write_bytes(b"this is not a zip archive")
    run("a file that is not a zip", "archive-unreadable", lambda f, m: None, writer=notzip)

    def damaged_entry(p, f, m):
        g = dict(f)
        g["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
        PK.write_zip(p, root_dir, list(g.items()), when)
        with zipfile.ZipFile(str(p)) as z:
            offset = z.getinfo(root_dir + "/" + victim).header_offset
        raw = bytearray(pathlib.Path(p).read_bytes())
        name_len = int.from_bytes(raw[offset + 26:offset + 28], "little")
        extra_len = int.from_bytes(raw[offset + 28:offset + 30], "little")
        raw[offset + 30 + name_len + extra_len + 10] ^= 0x01        # one bit inside the entry's own data
        pathlib.Path(p).write_bytes(bytes(raw))
    run("a zip with one entry's bytes damaged and its structure intact", "archive-unreadable", lambda f, m: None,
        writer=damaged_entry)
    run("a manifest whose commit's short name is not the start of its full name", "manifest-mismatch",
        lambda f, m: m["commit"].__setitem__("sha", "0" * 40))

    def undeflatable_entry(p, f, m):
        g = dict(f)
        g["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
        with zipfile.ZipFile(str(p), "w", zipfile.ZIP_STORED) as z:
            for rel, data in sorted(g.items()):
                zi = zipfile.ZipInfo(root_dir + "/" + rel, date_time=PK.entry_stamp(when))
                zi.compress_type = zipfile.ZIP_DEFLATED if rel == victim else zipfile.ZIP_STORED
                zi.create_system = 3
                zi.external_attr = PK.ZIP_MODE << 16
                z.writestr(zi, data)
        with zipfile.ZipFile(str(p)) as z:
            offset = z.getinfo(root_dir + "/" + victim).header_offset
        raw = bytearray(pathlib.Path(p).read_bytes())
        name_len = int.from_bytes(raw[offset + 26:offset + 28], "little")
        extra_len = int.from_bytes(raw[offset + 28:offset + 30], "little")
        raw[offset + 30 + name_len + extra_len] = 0x07              # a deflate block header of the reserved type
        pathlib.Path(p).write_bytes(bytes(raw))
    run("a zip with one deflated entry whose stream cannot be inflated, its structure intact (zlib's error, not a CRC-32's)",
        "archive-unreadable", lambda f, m: None, writer=undeflatable_entry)
    run("a size in the manifest changed", "size-mismatch",
        lambda f, m: [x.__setitem__("bytes", x["bytes"] + 1) for x in m["files"] if x["path"] == victim])
    run("the commit named in the manifest is not the one in the archive's name", "manifest-mismatch",
        lambda f, m: m["commit"].__setitem__("short", "0000000"))
    run("the date in the manifest is not the date it was created", "manifest-mismatch",
        lambda f, m: m["archive"].__setitem__("date_utc", "2001-01-01"))
    run("the manifest says the tree was not clean and lists nothing that differed", "manifest-mismatch",
        lambda f, m: m["tree"].__setitem__("clean", False))
    run("a creation time that is not on the date the manifest gives (the name as it was)", "manifest-mismatch",
        lambda f, m: m["archive"].__setitem__("created_utc", "2001-01-01T00:00:00Z"))
    run("a manifest that lists differing paths for a tree it calls clean (the name as it was)", "manifest-mismatch",
        lambda f, m: m["tree"].__setitem__("dirty_paths", [" M README.md"]))
    run("a commit time that does not make the timestamp the entries carry", "manifest-mismatch",
        lambda f, m: m["commit"].__setitem__("committed_utc", "2001-01-01T00:00:00Z"))
    run("a manifest whose files have no paths", "manifest-unreadable",
        lambda f, m: m.__setitem__("files", [{"bytes": 1}]))
    run("a manifest of a format this reader does not know", "manifest-unreadable",
        lambda f, m: m.__setitem__("manifest_format", PK.FORMAT + 1))

    def list_manifest(p, f, m):
        PK.write_zip(p, root_dir, [(k, v) for k, v in f.items() if k != "MANIFEST.json"] + [("MANIFEST.json", b"[1, 2]")], when)
    run("a manifest that is JSON and not a manifest", "manifest-unreadable", lambda f, m: None, writer=list_manifest)

    def no_manifest(p, f, m):
        PK.write_zip(p, root_dir, [(k, v) for k, v in f.items() if k != "MANIFEST.json"], when)
    run("no MANIFEST.json", "manifest-missing", lambda f, m: None, writer=no_manifest)

    def bad_manifest(p, f, m):
        PK.write_zip(p, root_dir, [(k, v) for k, v in f.items() if k != "MANIFEST.json"] + [("MANIFEST.json", b"{ not json")], when)
    run("a MANIFEST.json that is not JSON", "manifest-unreadable", lambda f, m: None, writer=bad_manifest)

    def two_roots(p, f, m):
        g = dict(f)
        g["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
        PK.write_zip(p, root_dir, list(g.items()), when)
        with zipfile.ZipFile(str(p), "a") as z:
            z.writestr(zipfile.ZipInfo("elsewhere/x.txt", date_time=PK.entry_stamp(when)), b"x")
    run("an entry outside the archive's one directory", "archive-structure", lambda f, m: None, writer=two_roots)

    def extra_entry(name):
        def go(p, f, m):
            g = dict(f)
            g["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
            PK.write_zip(p, root_dir, list(g.items()), when)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")                    # zipfile warns about a duplicate name
                with zipfile.ZipFile(str(p), "a") as z:
                    z.writestr(zipfile.ZipInfo(name, date_time=PK.entry_stamp(when)), b"x")
        return go
    run("an entry name that occurs twice", "archive-structure", lambda f, m: None,
        writer=extra_entry(root_dir + "/README.md"), only=False)
    run("an entry that climbs out of the archive's directory", "archive-structure", lambda f, m: None,
        writer=extra_entry(root_dir + "/../evil.txt"), only=False)
    run("an entry with a drive letter's colon in its name", "archive-structure", lambda f, m: None,
        writer=extra_entry(root_dir + "/C:evil.txt"), only=False)
    if os.sep == "/":
        run("an entry with a backslash in its name", "archive-structure", lambda f, m: None,
            writer=extra_entry(root_dir + "/a" + chr(92) + "b.txt"), only=False)
    else:               # MEASURED 2026-10-19 on Python 3.12: on Windows zipfile reads a backslash in an entry name as a slash
        NOT_RUN.append("archive plant, an entry with a backslash in its name: zipfile on Windows reads a backslash as a "
                       "slash, so no archive can show it; it runs where os.sep is a slash")

    def absolute(p, f, m):
        g = dict(f)
        g["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
        PK.write_zip(p, "", list(g.items()), when)                 # every name starts with a slash
    run("every entry written with a leading slash", "archive-structure", lambda f, m: None, writer=absolute, only=False)

    def lone_file(p, f, m):
        with zipfile.ZipFile(str(p), "w", zipfile.ZIP_STORED) as z:
            z.writestr(zipfile.ZipInfo("MANIFEST.json", date_time=PK.entry_stamp(when)), b"{}")
    run("an archive whose one entry is in no directory", "archive-structure", lambda f, m: None, writer=lone_file, only=False)

    def zip_made(system=3, mode=PK.ZIP_MODE):
        def go(p, f, m):
            g = dict(f)
            g["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
            with zipfile.ZipFile(str(p), "w", zipfile.ZIP_STORED) as z:
                for rel, data in sorted(g.items()):
                    zi = zipfile.ZipInfo(root_dir + "/" + rel, date_time=PK.entry_stamp(when))
                    zi.compress_type = zipfile.ZIP_STORED
                    zi.create_system = system
                    zi.external_attr = mode << 16
                    z.writestr(zi, data)
        return go
    run("a zip whose entries say another system made them (the host field is not Unix)", "zip-metadata", lambda f, m: None,
        writer=zip_made(system=0))
    run("a zip whose entries carry another mode", "zip-metadata", lambda f, m: None, writer=zip_made(mode=0o100755))
    run("a manifest whose list of files is not a list (an empty object, which the next test cannot refuse)",
        "manifest-unreadable", lambda f, m: m.__setitem__("files", {}))
    run("a manifest that names another directory for the archive", "manifest-mismatch",
        lambda f, m: m["archive"].__setitem__("root_dir", "elsewhere"))

    def unsorted(p, f, m):
        g = dict(f)
        g["MANIFEST.json"] = PK.dumps(m).encode("utf-8")
        with zipfile.ZipFile(str(p), "w", zipfile.ZIP_STORED) as z:
            for rel in sorted(g, reverse=True):
                zi = zipfile.ZipInfo(root_dir + "/" + rel, date_time=PK.entry_stamp(when))
                zi.compress_type = zipfile.ZIP_STORED
                zi.create_system = 3
                zi.external_attr = PK.ZIP_MODE << 16
                z.writestr(zi, g[rel])
    run("the entries written in reverse order", "zip-metadata", lambda f, m: None, writer=unsorted)
    # the PNG leg, around synthetic images: only it can see these (each one is consistent with its manifest)
    svg = victim
    png0 = "png/%s-light.png" % fig0
    w, h = PK.svg_size(files[svg].decode("utf-8"))

    def with_png(kind, claim=None, source=None, stats=True):
        def edit(f, m):
            data = synthetic_png(w, h, kind)
            f[png0] = data
            facts, _found = PNG.inspect(data)
            entry = {"path": png0, "kind": "figure-png", "figure": fig0, "theme": "light",
                     "rendered_from": source or svg, "scale": 1, "width": (claim or (w, h))[0],
                     "height": (claim or (w, h))[1], "band_rows": facts.get("band_rows"),
                     "ink_pct": facts.get("ink_pct") if stats else -1.0, "colours": facts.get("colours"),
                     "bytes": len(data), "sha256": PK.sha256(data)}
            m["files"].append(entry)
            m["png"] = {"made": True, "scale": 1}
        return edit
    run("a synthetic PNG of the right size with ink", None, with_png("good"))
    run("a PNG that is blank", "png-blank", with_png("blank"))
    run("a PNG of the wrong size", "png-size", with_png("wrong-size"))
    run("a PNG of a kind the reader does not hold: sixteen bits to the sample", "png-unsupported", with_png("sixteen-bit"))
    run("a PNG with a damaged byte", "png-corrupt", with_png("corrupt"))
    run("a PNG cut short", "png-corrupt", with_png("truncated"))
    run("a PNG whose size is not the one the manifest states", "png-size", with_png("good", claim=(w + 1, h)))
    run("a PNG whose statistics are not the ones the manifest states", "manifest-mismatch", with_png("good", stats=False))
    run("a PNG rendered from a file the archive does not hold", "png-source", with_png("good", source="docs/NOPE.svg"),
        only=False)
    run("an archive that says it has PNGs and holds none", "png-missing", lambda f, m: m.__setitem__("png", {"made": True}))

    def png_but_none_made(f, m):
        with_png("good")(f, m)
        m["png"] = {"made": False, "reason": "claimed"}
    run("a PNG in an archive whose manifest says none was made", "png-unexpected", png_but_none_made)


# ------------------------------------------------------------------------------------------ scratch plants
def scratch_checks(root, with_png, problems, report):
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="packager-check-") as tmp:
        tmp = pathlib.Path(tmp)
        S = tmp / "tree"
        S.mkdir()
        try:
            nfiles, c0 = make_scratch(root, S)
        except RuntimeError as e:
            problems.append(str(e))
            return
        memo = {}
        outs = S / "exports"

        def build(sub, **kw):
            kw.setdefault("no_png", True)
            kw.setdefault("now", NOW)
            return PK.build(S, outs / sub, figure_check_args=FAST, say=quiet, memo=memo, **kw)

        def expect(label, code, fn, say=None, without=()):
            """fn must raise Refused with `code` among its refusals and, if `say` is given, those words in its message;
            and with none of the codes in `without` beside it (a fault named under its own name AND under a wrong one)."""
            try:
                fn()
            except PK.Refused as r:
                codes = codes_of(r.items)
                if code not in codes:
                    problems.append("plant, %s: refused under %s, not %s: %s" % (label, codes, code, r.items[0][1][:100]))
                elif [c for c in without if c in codes]:
                    problems.append("plant, %s: refused under %s, beside %s, which names a reason the plant does not have" % (
                        label, codes, code))
                elif say is not None and say not in dict(r.items)[code]:
                    problems.append("plant, %s: refused under %s, but not for the reason planted (it said %r, and the "
                                    "reason has %r)" % (label, code, dict(r.items)[code][:100], say))
                else:
                    report.append("plant, %s -> REFUSED [%s] %s" % (label, code, dict(r.items)[code][:110]))
            else:
                problems.append("plant, %s: the packager did not refuse it" % label)

        # ---- a clean build, and its own verdict
        try:
            base = build("base")
        except PK.Refused as r:
            problems.append("the scratch copy does not build, so no plant below proves anything: %s: %s" % r.items[0])
            return
        bad = PK.verify_archive(base["path"])
        if bad:
            problems.append("the scratch copy's archive does not verify: %s: %s" % bad[0])
            return
        report.append("a scratch copy of %d files, committed, builds an archive of %d files that verifies (%.0f s so far)"
                      % (nfiles, base["files"], time.monotonic() - t0))
        # ---- reproducibility
        again = build("again")
        if again["path"].read_bytes() != base["path"].read_bytes():
            problems.append("reproducibility: two builds of one commit at one clock are not the same zip, byte for byte")
        else:
            report.append("reproducibility, same commit and clock: the two zips are the same %d bytes" % base["bytes"])
        later = build("later", now=NOW + datetime.timedelta(days=1, seconds=3))
        a, b = load_archive(base["path"]), load_archive(later["path"])
        diff = sorted(rel for rel in a[1] if rel != "MANIFEST.json" and a[1][rel] != b[1].get(rel))
        ma, mb = a[2], b[2]
        for m in (ma, mb):
            for k in ("name", "file", "root_dir", "created_utc", "date_utc"):
                m["archive"].pop(k)
            m["zip"].pop("root_dir")
        if diff or set(a[1]) != set(b[1]) or ma != mb:
            problems.append("reproducibility: a different clock changed more than the manifest's date fields: %s" % (
                diff or "the manifest"))
        else:
            report.append("reproducibility, a clock a day and three seconds later: every file is the same but "
                          "MANIFEST.json's date fields (the archive's name, created_utc, date_utc and the root directory)")
        env = dict(os.environ, PYTHONHASHSEED="7")
        sub = subprocess.run([sys.executable, "-B", str(HERE / "project_packager.py"), "--root", str(S), "--out",
                              str(outs / "other"), "--no-png", "--now", NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "--figure-check-args=" + " ".join(FAST)], capture_output=True, env=env, timeout=600)
        other = outs / "other" / base["path"].name
        if sub.returncode != 0 or not other.is_file():
            problems.append("reproducibility: a build in another process failed: %s" % sub.stderr.decode("utf-8", "replace")[-200:])
        elif other.read_bytes() != base["path"].read_bytes():
            problems.append("reproducibility: a build in another process, under PYTHONHASHSEED=7, is not the same zip")
        else:
            report.append("reproducibility, another process under another PYTHONHASHSEED: the same zip, byte for byte")
        # ---- the plants
        def plant(label, code, setup, say=None, without=(), **kw):
            try:
                setup()
                expect(label, code, lambda: build("p-" + code, **kw), say=say, without=without)
            finally:
                restore(S, c0)
        # No figure is named here by hand: the first of the gallery, the first of the README's charts and the first data
        # file the charts are made from are taken from the tree, so a change to any of them cannot break a plant.
        FIG0 = "%s/%s" % (PK.FIG_DIR, ST.parse_gallery((S / PK.GALLERY).read_text(encoding="utf-8"))[0]["name"])
        CHART = PK.README_CHARTS[-1]

        def alt_edit(b):
            d = json.loads(b.decode("utf-8"))
            d["alt"] = d["alt"] + " (edited)"
            return X.dumps(d).encode("utf-8")
        plant("a figure's dark SVG missing", "missing-figure",
              lambda: (os.remove(str(S / (FIG0 + "-dark.svg"))), sgit(S, "commit", "-q", "--no-verify", "-am", "plant")))
        plant("a sidecar's alt text edited", "sidecar-mismatch", lambda: mutate(S, FIG0 + ".json", alt_edit))

        # Each of the sidecar's own checks, alone: the edits below move one thing the sidecar must agree with and leave
        # every other agreement as it was, so that a check that is removed leaves a plant unnamed.
        def sidecar_edit(fn):
            def edit(b):
                d = json.loads(b.decode("utf-8"))
                fn(d)
                return X.dumps(d).encode("utf-8")
            return edit
        plant("a sidecar that names another figure", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + ".json", sidecar_edit(lambda d: d.__setitem__("figure", d["figure"] + "-x"))))
        plant("a sidecar that lists other files", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + ".json", sidecar_edit(lambda d: d.__setitem__("files", d["files"][::-1]))))
        plant("the gallery's alt text for a figure edited, the sidecar and the SVG as they were", "sidecar-mismatch",
              lambda: mutate(S, "docs/FIGURES.md", lambda b: b.replace(b'<img alt="', b'<img alt="Edited: ', 1)))
        plant("the gallery's title for a figure edited", "sidecar-mismatch",
              lambda: mutate(S, "docs/FIGURES.md", lambda b: b.replace(b"\n### ", b"\n### Edited: ", 1)))
        plant("an SVG's aria-label edited, its title and the sidecar as they were", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + "-light.svg", lambda b: b.replace(b'aria-label="', b'aria-label="Edited: ', 1)))
        plant("an SVG that declares no size", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + "-dark.svg", lambda b: b.replace(b' width="', b' widthx="', 1)))
        plant("a number in a sidecar's data edited", "figures-out-of-date",
              lambda: mutate(S, FIG0 + ".json", bump_digit_after(b'"data"')))
        plant("a figure's SVG changed by one digit", "figures-out-of-date",
              lambda: mutate(S, FIG0 + "-light.svg", bump_digit_after(b"</title>")))
        plant("a file a sidecar was drawn from changed", "sidecar-mismatch",
              lambda: mutate(S, PK.README_CHARTS_DATA[0], bump_digit_after(b"\n")))
        extract = X.EXTRACT_DIR + "/" + sorted(p.name for p in (S / X.EXTRACT_DIR).glob("*.json"))[0]
        plant("an extract a sidecar was read from changed", "sidecar-mismatch",
              lambda: mutate(S, extract, bump_digit_after(b'"data"')))
        plant("the gallery's caption edited", "figures-out-of-date",
              lambda: mutate(S, "docs/FIGURES.md", lambda b: b.replace(b"**Shows.** ", b"**Shows.** Edited: ", 1)))
        plant("the gallery's caption label removed", "gallery-unreadable",
              lambda: mutate(S, "docs/FIGURES.md", lambda b: b.replace(b"**Shows.**", b"Shows.", 1)))
        plant("the README's picture of a bench chart no longer found", "readme-unreadable",
              lambda: mutate(S, "README.md", lambda b: b.replace(("%s-light.svg\">" % CHART).encode("ascii"),
                                                                  ("%s-light.svg?x\">" % CHART).encode("ascii"), 1)))
        plant("a figure file with no place in the gallery", "missing-figure",
              lambda: add_file(S, "docs/img/figures/zzz-extra.json", b"{}\n"))
        plant("a README chart's dark SVG missing", "missing-figure",
              lambda: (os.remove(str(S / ("%s/%s-dark.svg" % (PK.BENCH_DIR, CHART)))),
                       sgit(S, "commit", "-q", "--no-verify", "-am", "plant: remove a chart")), say="is not in the tree")
        plant("a README chart's SVG with no aria-label", "missing-figure",
              lambda: mutate(S, "%s/%s-light.svg" % (PK.BENCH_DIR, CHART),
                             lambda b: b.replace(b'aria-label="', b'data-label="', 1)), say="aria-label")
        plant("a sidecar that is not JSON", "sidecar-mismatch", lambda: mutate(S, FIG0 + ".json", lambda b: b"{ not json"),
              say="does not parse")
        plant("a sidecar that is JSON and not an object", "sidecar-mismatch", lambda: mutate(S, FIG0 + ".json", lambda b: b"[1, 2]\n"),
              say="not shaped as a sidecar is")
        plant("a sidecar whose source has no path", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + ".json", sidecar_edit(lambda d: d.__setitem__("sources", [{"sha256": "0" * 64}]))),
              say="not shaped as a sidecar is")
        plant("a sidecar that names a source that is not in the tree", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + ".json", sidecar_edit(
                  lambda d: d.__setitem__("sources", [{"path": "docs/NOPE.csv", "sha256": "0" * 64}]))),
              say="a source it cannot find")
        plant("a sidecar that names an extract that is not in the tree", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + ".json", sidecar_edit(
                  lambda d: d.__setitem__("extracts", [{"path": "docs/figures/NOPE.json", "sha256": "0" * 64}]))),
              say="an extract it cannot find")
        plant("python/readme_charts.py exiting with an error", "readme-charts-out-of-date",
              lambda: mutate(S, "python/readme_charts.py",
                             lambda b: b.replace(b"raise SystemExit(main())", b"raise SystemExit(3)", 1)), say="exit 3")
        plant("python/readme_charts.py exiting 0 and writing nothing", "readme-charts-out-of-date",
              lambda: mutate(S, "python/readme_charts.py",
                             lambda b: b.replace(b"raise SystemExit(main())", b"raise SystemExit(0)", 1)),
              say="is not what python/readme_charts.py makes")
        plant("a figure check that exits 0 and prints something that is not its summary", "figures-out-of-date",
              lambda: mutate(S, "python/project_figures.py", lambda b: b'import sys\nprint("all is well")\nsys.exit(0)\n'),
              say="no summary line")
        plant("an SVG's title edited, its aria-label and the sidecar as they were", "sidecar-mismatch",
              lambda: mutate(S, FIG0 + "-light.svg", lambda b: b.replace(b"<title>", b"<title>Edited: ", 1)))
        plant("a figure check that has been gutted to exit 0 and say nothing", "figures-out-of-date",
              lambda: mutate(S, "python/project_figures.py", lambda b: b"import sys\nsys.exit(0)\n"))

        # With the figure check stubbed out, a sidecar that has been corrupted gets past it; the status builder's own
        # consistency checks are then all that stand between it and a sentence in STATUS.md.
        STUB = b'import sys\nprint("project_figures: a stub that passes")\nsys.exit(0)\n'

        def corrupt(rel, edit, top=False):
            def go():
                mutate(S, "python/project_figures.py", lambda b: STUB)
                p = S / rel
                d = json.loads(p.read_text(encoding="utf-8"))
                edit(d if top else d["data"])
                p.write_bytes(X.dumps(d).encode("utf-8"))
                sgit(S, "commit", "-q", "--no-verify", "-am", "plant: corrupt " + rel)
            return go
        plant("legs by status that do not add to the legs", "status-source",
              corrupt(PK.FIG_DIR + "/stress-timeline.json", lambda d: d["legs"]["by_status"].__setitem__("pass", d["legs"]["by_status"]["pass"] + 1)))
        plant("tile and host cases that do not add to the cases", "status-source",
              corrupt(PK.FIG_DIR + "/stress-sweep.json", lambda d: d.__setitem__("tile_cases", d["tile_cases"] + 1)))
        plant("wins and losses that do not add to the comparisons", "status-source",
              corrupt(PK.FIG_DIR + "/perf-speedup.json", lambda d: d.__setitem__("wins", d["wins"] + 1)))
        plant("a sidecar without a number a fact reads", "status-source",
              corrupt(PK.FIG_DIR + "/stress-timeline.json", lambda d: d.pop("hours")))
        plant("a sidecar without its checks", "status-source",
              corrupt(PK.FIG_DIR + "/verify-stages.json", lambda d: d.pop("checks"), top=True))
        plant("a README chart's SVG changed by one digit", "readme-charts-out-of-date",
              lambda: mutate(S, "%s/%s-light.svg" % (PK.BENCH_DIR, CHART), bump_digit_after(b"<rect")))
        plant("a personal path in NOTICE", "personal-path",
              lambda: mutate(S, "NOTICE", lambda b: b + b"\nsee " + PLANTED_PATH + b"\n"))
        plant("the README's heading for what is built gone", "status-source",
              lambda: mutate(S, "README.md", lambda b: b.replace(b"## What is built and working", b"## What is built", 1)))
        DOC = PK.LIGHT_DOCS[-1][0]                       # a light document, taken from the packager's own list
        plant("a light document missing", "missing-document",
              lambda: (os.remove(str(S / DOC)), sgit(S, "commit", "-q", "--no-verify", "-am", "plant: remove " + DOC)))

        # A CRLF checkout is refused as one, by name, and not as the sidecar-mismatch its raw digests would also give.
        # The files are rewritten CRLF and `git add`ed, as a Windows editor leaves a tracked file: the blob is the same
        # LF one, so git calls the tree clean, and only the packager's own look at the bytes can see it.
        def crlf_plant(label, rels, say):
            try:
                for rel in rels:
                    mutate(S, rel, lambda b: b.replace(b"\n", b"\r\n"), commit=False)
                sgit(S, "add", "-A")
                expect(label, "crlf-checkout", lambda: build("p-crlf-checkout"), say=say, without=("sidecar-mismatch", "dirty-tree"))
            finally:
                restore(S, c0)
                for rel in rels:     # MEASURED: the index now records each file as it lies, so neither a reset nor a checkout
                    (S / rel).write_bytes((S / rel).read_bytes().replace(b"\r\n", b"\n"))      # rewrites it: write it LF
                sgit(S, "add", "-A")
                if any(b"\r" in (S / rel).read_bytes() for rel in rels) or sgit(S, "status", "--porcelain=v1").strip():
                    raise RuntimeError("the scratch tree is not as it was after the plant on %s" % ", ".join(rels))
        SRC = PK.README_CHARTS_DATA[0]
        crlf_plant("a file a sidecar was drawn from, saved with CRLF line endings, the tree clean to git", [SRC], SRC)
        crlf_plant("an extract a sidecar was read from, saved with CRLF line endings", [extract], extract)
        crlf_plant("a light document the archive copies and a source, both saved with CRLF line endings", [DOC, SRC], "2 file(s)")
        # MEASURED: with the ledger CRLF, STATUS.md builds, holds CR bytes and is not the LF tree's; the packager's reader
        # does not fail, so only a look at the files it read can refuse it
        crlf_plant("the ledger, a file STATUS.md is only read from, saved with CRLF line endings", [ST.LEDGER], ST.LEDGER)
        plant("a tree with an edit that is not committed", "dirty-tree",
              lambda: mutate(S, "README.md", lambda b: b + b"\nAn edit nobody committed.\n", commit=False))
        # independent refusals come back together, not one to a run
        try:
            os.remove(str(S / DOC))                      # not committed: the tree is dirty AND a document is missing
            try:
                build("p-both")
            except PK.Refused as r:
                got = codes_of(r.items)
                if "dirty-tree" in got and "missing-document" in got:
                    report.append("plant, a dirty tree with a light document missing -> both refusals in one run: %s" % got)
                else:
                    problems.append("plant, a dirty tree with a light document missing: refused under %s, not both "
                                    "dirty-tree and missing-document" % got)
            else:
                problems.append("plant, a dirty tree with a light document missing: the packager did not refuse it")
        finally:
            restore(S, c0)
        # a dirty tree, allowed: the archive says so in its name and its manifest
        try:
            mutate(S, "README.md", lambda b: b + b"\nAn edit nobody committed.\n", commit=False)
            d = build("dirty", allow_dirty=True)
            dman = load_archive(d["path"])[2]
            if not d["path"].name.endswith("-dirty.zip") or dman["tree"]["clean"] or not any("README.md" in p for p in dman["tree"]["dirty_paths"]):
                problems.append("plant, a dirty tree allowed: the archive does not say so in its name and its manifest")
            else:
                report.append("plant, a dirty tree with --allow-dirty -> an archive named %s whose manifest lists %s" % (
                    d["path"].name[-24:], dman["tree"]["dirty_paths"][0].strip()))
            if PK.verify_archive(d["path"]):
                problems.append("a dirty archive does not verify")
        finally:
            restore(S, c0)
        # ---- refusals that need no fault in the tree: where it is run, and what the packager itself produces. The
        # last group stands in for a defect (a renderer, a status builder, a verifier that is wrong) by replacing one
        # function for the length of one build, so that the packager's own check of its own work has a fault to refuse.
        def without_git():
            real = shutil.which
            shutil.which = lambda name, *a, **k: None if name == "git" else real(name, *a, **k)
            try:
                build("p-nogit")
            finally:
                shutil.which = real
        expect("git not on PATH", "no-git", without_git)

        def build_at(root, sub):
            return lambda: PK.build(root, outs / sub, no_png=True, now=NOW, figure_check_args=FAST, say=quiet, memo=memo)

        def outside_any_tree():
            bare = tmp / "not-a-tree"
            bare.mkdir(exist_ok=True)
            held = os.environ.get("GIT_CEILING_DIRECTORIES")
            os.environ["GIT_CEILING_DIRECTORIES"] = str(tmp)           # git looks no higher than this scratch directory
            try:
                build_at(bare, "p-bare")()
            finally:
                if held is None:
                    os.environ.pop("GIT_CEILING_DIRECTORIES", None)
                else:
                    os.environ["GIT_CEILING_DIRECTORIES"] = held
        expect("a root that is not a git work tree", "not-a-git-tree", outside_any_tree, say="git rev-parse --show-toplevel")
        expect("a root that is inside a work tree and is not its top", "not-a-git-tree", build_at(S / "python", "p-sub"),
               say="is not its top")

        def replaced(owner, name, fn, sub):
            """Build once with owner.name replaced by fn(original), then put the original back."""
            def go():
                real = getattr(owner, name)
                setattr(owner, name, fn(real))
                try:
                    build(sub)
                finally:
                    setattr(owner, name, real)
            return go
        expect("a page that leaves a tag open", "html-malformed",
               replaced(HTML, "render", lambda real: lambda md: real(md).replace("</body>", "<div></body>", 1), "p-html-tag"))
        expect("a page with words the Markdown does not have", "html-text",
               replaced(HTML, "render", lambda real: lambda md: real(md).replace("</body>", "<p>words not there</p></body>", 1),
                        "p-html-text"))
        expect("a page that names a file the archive does not hold", "html-link",
               replaced(HTML, "render", lambda real: lambda md: real(md).replace(
                   "</body>", '<a href="docs/NOPE.md"></a></body>', 1), "p-html-link"))

        def with_unheld_ref(real):
            def patched(rd, ctx):
                text, facts, quotes, refs, reads, dropped = real(rd, ctx)
                return text, facts, quotes, list(refs) + ["docs/NOPE.md"], reads, dropped
            return patched
        expect("a status document that refers to a file the archive does not hold", "status-source",
               replaced(ST, "build", with_unheld_ref, "p-ref"), say="does not hold")
        expect("an archive that does not verify once it is written (the verifier made to say so)", "self-verify",
               replaced(PK, "verify_archive", lambda real: lambda path: [("hash-mismatch", "planted: it does not verify")],
                        "p-selfverify"), say="planted")
        left = sorted(p.name for p in (outs / "p-selfverify").glob("*")) if (outs / "p-selfverify").is_dir() else []
        if left:
            problems.append("plant, an archive that does not verify: it left %s behind, where nothing should be" % left)
        else:
            report.append("plant, an archive that does not verify: nothing is left behind")
        expect("no converter, and --no-png not given", "no-converter",
               lambda: build("p-noconv", no_png=False, converter="no/such/rsvg-convert"))
        expect("a converter that is not rsvg-convert (Python itself)", "converter-unusable",
               lambda: build("p-notrsvg", no_png=False, converter=sys.executable), say="does not answer")
        notexe = tmp / "not-a-program.txt"
        notexe.write_text("this is text, not a program\n", encoding="ascii")
        expect("a converter that is a text file and cannot be run", "converter-unusable",
               lambda: build("p-textconv", no_png=False, converter=str(notexe)), say="could not be run")
        expect("an SVG that declares no size, handed to the renderer", "render-failed",
               lambda: PK.render_pngs({"exe": "never-run"}, [("png/x.png", "x.svg", '<svg xmlns="http://www.w3.org/2000/svg"/>')],
                                      1, str(tmp)), say="declares no width")
        for mode, code, what in (("fail", "render-failed", "fails on every file"),
                                 ("nothing", "render-failed", "exits 0 and writes no file"),
                                 ("fail-late", "render-failed", "writes its image and then exits with a failure"),
                                 ("version-fails", "converter-unusable", "answers --version with a failure"),
                                 ("blank", "png-blank", "writes a blank image of the right size"),
                                 ("wrong-size", "png-size", "writes an image of half the size"),
                                 ("sixteen-bit", "png-unsupported", "writes a 16-bit image, which the reader does not hold"),
                                 ("garbage", "png-corrupt", "writes bytes that are not a PNG")):
            expect("a converter that %s" % what, code,
                   lambda c=make_fake_converter(tmp, mode), m=mode: build("p-fake-" + m, no_png=False, converter=c, scale=1))
        expect("an output directory inside the tree that git does not ignore", "output-not-ignored",
               lambda: PK.build(S, S / "notignored", no_png=True, now=NOW, figure_check_args=FAST, say=quiet, memo=memo))
        expect("an archive already there", "exists", lambda: build("base"))
        nopng = load_archive(base["path"])[2]["png"]
        if nopng.get("made") is not False or "no-png" not in nopng.get("reason", "") and "--no-png" not in nopng.get("reason", ""):
            problems.append("a --no-png archive's manifest does not say that no PNG was made: %r" % nopng)
        else:
            report.append("control, --no-png: the manifest says png.made is false and why, and the archive holds no PNG")
        # ---- the archive's own checks
        archive_plants(base["path"], tmp, report, problems)
        # ---- the legs that need a converter
        if with_png:
            png_legs(S, c0, outs, build, expect, problems, report)
        report.append("the scratch tree's work took %.0f s" % (time.monotonic() - t0))


def png_legs(S, c0, outs, build, expect, problems, report):
    try:
        conv = PK.find_converter()
    except PK.Refused as r:                          # --png was asked for, so no converter is a failure, by name
        problems.append("--check --png needs a converter and was refused: %s: %s" % r.items[0])
        return
    p1 = build("png1", no_png=False)
    bad = PK.verify_archive(p1["path"])
    if bad:
        problems.append("the PNG archive does not verify: %s: %s" % bad[0])
        return
    m1 = load_archive(p1["path"])[2]
    report.append("with the real converter (%s %s): %d PNGs, fonts used %s; the archive verifies" % (
        conv["name"], conv["version"], p1["pngs"], ", ".join(m1["png"]["fonts"]["used"] or ["not read"])))
    p2 = build("png2", no_png=False)
    if p2["path"].read_bytes() != p1["path"].read_bytes():
        problems.append("reproducibility: two PNG builds of one commit at one clock are not the same zip")
    else:
        report.append("reproducibility with PNGs: the two zips are the same %d bytes" % p1["bytes"])
    root_dir, files, man, when = load_archive(p1["path"])
    victim = "png/%s-light.png" % man["figures"][0]["name"]
    entry = man["files"][[f["path"] for f in man["files"]].index(victim)]
    wh = (entry["width"], entry["height"])
    n = [0]

    def variant(label, code, data):
        f, m = dict(files), copy.deepcopy(man)
        set_file(f, m, victim, data)
        n[0] += 1
        out = outs / ("pngplant-%d.zip" % n[0])
        save_archive(out, root_dir, f, m, when)
        codes = codes_of(PK.verify_archive(out))
        if code in codes:
            report.append("archive plant on a real PNG, %s: %s" % (label, code))
        else:
            problems.append("archive plant on a real PNG, %s: --verify did not say %s (it said %s)" % (label, code, codes))
    variant("replaced by a blank image of the same size", "png-blank", synthetic_png(wh[0], wh[1], "blank"))
    real = files[victim]
    flipped = bytearray(real)
    flipped[real.index(b"IDAT") + 20] ^= 0x01
    variant("one bit flipped in its data", "png-corrupt", bytes(flipped))
    variant("replaced by an image half the size", "png-size", synthetic_png(wh[0], wh[1], "wrong-size"))


def defuse(text):
    """A failure of this check is not 'stale': verify/run.sh's `generated` stage calls any failing generator whose
    output says stale, differs from a fresh generation or has drifted from host/ STALE and tells the reader to
    regenerate, and this check has nothing to regenerate. The words are changed on the way out, so a problem line that
    quotes project_figures.py's own message cannot make it say so."""
    for pat, rep in ((r"(?i)stale", "out of date"), (r"(?i)differs from a fresh", "differs from a new"),
                     (r"(?i)has drifted from host/", "has moved from host/")):
        text = re.sub(pat, rep, text)
    return text


def main(root, with_png=False):
    t0 = time.monotonic()
    problems, report = [], []
    NOT_RUN.clear()
    root = pathlib.Path(root).resolve()
    problems += real_tree(root, report)
    p, r = status_plants()
    problems += p
    report += r
    p, r = PNG.selftest()
    problems += p
    report += r
    p, r = html_plants()
    problems += p
    report += r
    if not problems:
        scratch_checks(root, with_png, problems, report)
    if problems:
        for p in problems:
            print("  %s" % defuse(p))
        print("project_packager: --check found %d problem(s)" % len(problems))
        return 1
    for line in report:
        print("  control: %s" % line)
    for item in NOT_RUN:
        print("  SKIP  not run on this platform: %s" % item)         # the marker first: verify/run.sh counts it (carry_skips)
    print("project_packager: --check passed: the tree can be packaged, %d controls each refused or failed by name%s, a "
          "build verifies and reproduces%s (%.0f s)" % (
              len(report), "" if not NOT_RUN else " (plus %d that could not run on this platform, named above)" % len(NOT_RUN),
              ", with the real converter too" if with_png else "", time.monotonic() - t0))
    return 0
