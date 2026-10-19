# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""packager_status: the "where the project stands" document, made by script from the project's own files.

python/project_packager.py puts this document in every archive as STATUS.md. It answers: what is this project,
what is built, how much is checked, what did the card last do, where is the current round, and what do the
figures show. Every one of those answers is READ, not written:

  - a NUMBER enters the document only as a registered fact: its value, the text it prints as, the files it was
    read from (each with its SHA-256) and the rule that read it. The Doc class refuses a plain string that
    contains a digit, so a count cannot be typed into the template - not "52 stages", and not a count
    formatted into a string by code either, which would arrive as a plain string with digits in it. The two
    names that contain a digit and are not a count (SHA-256, U50) are the only exceptions, listed below.
  - TEXT enters as a quotation: the README's own summary, its table of what is built, the ledger's newest
    headings, each figure's title and caption. A quotation is registered with the file it was copied from and
    the rule that found it, and is printed as a block quotation, so a reader can see where the packager's words
    stop and the project's begin. Links in a quotation are made to resolve inside the archive.
  - A PATH enters as a reference to a file that the archive holds, and the packager checks that it does.

Every reader finds exactly what it expects or says by name what is missing (SourceError). None of them
returns 0, or an empty list, when a pattern misses: a count that defaults is a false claim. A sentence in a
source that has moved - a README heading renamed, a stage list reorganised - stops the export under
`status-source`, naming the file and what it no longer holds, which is the same trade python/project_figures.py
makes with the numbers the README states in words.

The document does NOT contain the date it was made. The date is in the archive's name and in MANIFEST.json, so
that two archives of one commit hold the same STATUS.md byte for byte.
"""
import collections
import hashlib
import html
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import figure_extracts as X                                          # noqa: E402  (_budget_members, _bench_count)

README = "README.md"
LEDGER = "docs/VALIDATION.md"
ROADMAP = "docs/ROADMAP.md"
GALLERY = "docs/FIGURES.md"
SIDECAR_DIR = "docs/img/figures"
BENCH_DIR = "docs/img/bench"
# Names that contain a digit and are not a count. Nothing else with a digit may be a plain string.
NAMES_WITH_DIGITS = ("cft-fp256", "SHA-256", "U50")
NEWEST_ENTRIES = 6


class SourceError(Exception):
    """A source no longer says what its reader expects."""


class DocError(Exception):
    """The template broke its own rules (a typed number, an unknown fact, an unused one)."""


# ---------------------------------------------------------------------------------------------- reading
class Reader:
    """Reads committed files from a work tree and remembers what it read, with each file's SHA-256."""

    def __init__(self, root):
        self.root = pathlib.Path(root)
        self.log = {}

    def _bytes(self, rel):
        p = self.root / rel
        if not p.is_file():
            raise SourceError("%s is not in the tree" % rel)
        b = p.read_bytes()
        self.log[rel] = {"sha256": hashlib.sha256(b).hexdigest(), "bytes": len(b)}
        return b

    def text(self, rel):
        try:
            return self._bytes(rel).decode("utf-8")
        except UnicodeDecodeError as e:
            raise SourceError("%s is not UTF-8 text (%s)" % (rel, e))

    def json(self, rel):
        try:
            return json.loads(self.text(rel))
        except ValueError as e:
            raise SourceError("%s does not parse as JSON (%s)" % (rel, e))

    def src(self, rel, reads):
        """A source record for the manifest: the file, its digest, and which part of it was read."""
        if rel not in self.log:
            self._bytes(rel)
        return {"path": rel, "sha256": self.log[rel]["sha256"], "reads": reads}

    def field(self, rel, *path):
        """(value, source) of a JSON field. A field that is absent is a SourceError, never a default."""
        cur = self.json(rel)
        for k in path:
            try:
                cur = cur[k]
            except (KeyError, IndexError, TypeError):
                raise SourceError("%s has no field %s" % (rel, ".".join(str(p) for p in path)))
        return cur, self.src(rel, "field " + ".".join(str(p) for p in path))

    def group(self, files, label, reads):
        """One source record for many files: how many, and a digest of their sorted (path, digest) listing."""
        lines = []
        for rel in sorted(files):
            if rel not in self.log:
                self._bytes(rel)
            lines.append("%s  %s\n" % (self.log[rel]["sha256"], rel))
        return {"path": label, "files": len(lines), "sha256": hashlib.sha256("".join(lines).encode("utf-8")).hexdigest(),
                "reads": reads}


def count_lines(text, pattern, what, rel):
    n = len(re.findall(pattern, text, re.M))
    if n == 0:
        raise SourceError("%s has no %s (pattern %s)" % (rel, what, pattern))
    return n


DATED_DOCS = ("CAPABILITIES.md", "docs/COMPLIANCE.md")      # the light documents whose reasons speak of the present


def newest_written_date(text, rel):
    """The newest YYYY-MM-DD the document itself writes. It is the document's own word, read from its text: nothing of
    the tree's history is used, so a shallow clone gives the same answer."""
    dates = re.findall(r"\b(20\d\d-\d\d-\d\d)\b", text)
    if not dates:
        raise SourceError("%s writes no date, and this archive says how current it is by the newest one" % rel)
    return max(dates)


def read_runner(rd):
    """Stages and budgets, as python/check_docs_index.py and python/figure_extracts.py read them: the runner's own
    `stage NAME "..."` lines, and the members of its two BUDGET_ lists."""
    text = rd.text("verify/run.sh")
    stages = count_lines(text, r'^stage [a-z0-9-]+ "', "stage lines", "verify/run.sh")
    out = {"stages": stages}
    for key, var in (("quick", "BUDGET_QUICK"), ("gate", "BUDGET_GATE")):
        members = X._budget_members(text, var)
        if not members:
            raise SourceError("verify/run.sh has no %s list" % var)
        out[key] = len(members)
    if out["gate"] > stages or out["quick"] > out["gate"]:
        raise SourceError("verify/run.sh: the budgets are not nested (%d stages, gate %d, quick %d)" % (
            stages, out["gate"], out["quick"]))
    return out


def read_benches(rd):
    n = X._bench_count(rd.text("tb/Makefile"))
    if not n:
        raise SourceError("tb/Makefile: cannot read the bench list `make sim` runs (SIM_BENCHES as a flat list, or "
                          "as the union of its SIM_GROUP_ lists)")
    return n


def read_proofs(rd):
    return count_lines(rd.text("formal/run.sh"), r"^run_proof ", "run_proof lines", "formal/run.sh")


def read_tests(rd):
    """Test functions defined in python/tests: lines that begin `def test_`, as python/figure_extracts.py counts them."""
    files = sorted(str(p.relative_to(rd.root)).replace("\\", "/") for p in (rd.root / "python" / "tests").rglob("*.py"))
    if not files:
        raise SourceError("python/tests holds no .py file")
    n, defining = 0, 0
    for rel in files:
        c = len(re.findall(r"(?m)^\s*def test_", rd.text(rel)))
        n += c
        defining += 1 if c else 0
    if n == 0:
        raise SourceError("python/tests defines no test function (pattern ^\\s*def test_)")
    return n, defining, rd.group(files, "python/tests/*.py", "lines beginning `def test_`")


def read_sidecar_claims(rd):
    """(checks, agreeing, source) over every figure sidecar's `checks`: numbers the README and other documents state,
    phrases, and presence or consistency checks, as the figures' own check holds them to the record."""
    files = sorted("%s/%s" % (SIDECAR_DIR, p.name) for p in (rd.root / SIDECAR_DIR).glob("*.json"))
    if not files:
        raise SourceError("%s holds no sidecar" % SIDECAR_DIR)
    total = agree = 0
    for rel in files:
        checks = rd.json(rel).get("checks")
        if checks is None:
            raise SourceError("%s has no `checks` list" % rel)
        total += len(checks)
        agree += sum(1 for c in checks if c.get("verdict") == "agrees")
    return total, agree, rd.group(files, SIDECAR_DIR + "/*.json", "each sidecar's `checks` list, counted by verdict")


def read_ledger(rd):
    """The ledger's size and newest headings. An entry is a line beginning `## `, as python/figure_extracts.py counts."""
    text = rd.text(LEDGER)
    heads = re.findall(r"(?m)^## (.+)$", text)
    if not heads:
        raise SourceError("%s has no `## ` heading" % LEDGER)
    dates = re.findall(r"(?m)^## (\d{4}-\d{2}-\d{2})\b", text)
    if not dates:
        raise SourceError("%s has no entry whose heading begins with a date" % LEDGER)
    m = re.match(r"\d{4}-\d{2}-\d{2}", heads[-1])
    if not m:
        raise SourceError("%s: the newest entry's heading does not begin with a date: %r" % (LEDGER, heads[-1][:60]))
    return {"entries": len(heads), "lines": len(text.splitlines()), "first": dates[0], "last": m.group(0),
            "newest": heads[-NEWEST_ENTRIES:]}


def read_plan(rd):
    """The heading of the latest plan of record in the roadmap: the last heading that says `plan of record`."""
    text = rd.text(ROADMAP)
    plans = re.findall(r"(?m)^#{2,6} (.*\bplan of record\b.*)$", text)
    if not plans:
        raise SourceError("%s has no heading that says `plan of record`" % ROADMAP)
    return plans[-1]


def block_between(text, start_re, end_re, what, rel):
    """The lines of `text` after the line matching start_re up to (not including) the next line matching end_re."""
    lines = text.split("\n")
    for i, ln in enumerate(lines):
        if re.match(start_re, ln):
            for j in range(i + 1, len(lines)):
                if re.match(end_re, lines[j]):
                    return "\n".join(lines[i + 1:j]).strip("\n")
            return "\n".join(lines[i + 1:]).strip("\n")
    raise SourceError("%s has no %s (a line matching %s)" % (rel, what, start_re))


def readme_summary(text):
    """Everything between the README's title and its first second-level heading."""
    if not text.startswith("# "):
        raise SourceError("README.md does not begin with its title line (`# ...`)")
    body = block_between(text, r"# ", r"## ", "title", README)
    if not body.strip():
        raise SourceError("README.md has nothing between its title and its first `## ` heading")
    return body


def readme_built(text):
    """The table under `## What is built and working`."""
    body = block_between(text, r"## What is built and working\s*$", r"## ", "section `What is built and working`", README)
    rows = [ln for ln in body.split("\n") if ln.startswith("|")]
    if len(rows) < 3:
        raise SourceError("README.md: the section `What is built and working` holds no table")
    return "\n".join(rows)


def fix_links(text, archive_paths):
    """A quotation's markdown links, made to resolve inside the archive: an in-page anchor points at the archive's
    README.md; a relative link to a file the archive holds is kept; a relative link to a file it does not hold
    keeps its text and loses its target; an http(s) link is kept. Returns (text, dropped targets)."""
    dropped = []

    def one(m):
        label, target = m.group(1), m.group(2)
        if target.startswith(("http://", "https://", "mailto:")):
            return m.group(0)
        if target.startswith("#"):
            return "[%s](%s%s)" % (label, README, target)
        path = target.split("#", 1)[0]
        if path in archive_paths:
            return m.group(0)
        dropped.append(target)
        return label
    return re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", one, text), dropped


# ------------------------------------------------------------------------------------ the figures' captions
def unescape_attr(s):
    return html.unescape(s)


def parse_gallery(text):
    """The gallery's figures in order: [{name, group, title, alt, paragraphs, body}]. Raises SourceError."""
    table = re.findall(r"(?m)^\| \[([a-z0-9-]+)\]\(#\1\) \| (.*) \|$", text)
    if not table:
        raise SourceError("%s has no table of figures (rows like `| [name](#name) | title |`)" % GALLERY)
    lines = text.split("\n")
    out, group, i = [], None, 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## "):
            group = ln[3:].strip()
        m = re.fullmatch(r'<a id="([a-z0-9-]+)"></a>', ln)
        if m and group is not None:
            j = i + 1
            while j < len(lines) and not re.fullmatch(r'<a id="[a-z0-9-]+"></a>', lines[j]) and not lines[j].startswith("## "):
                j += 1
            block = lines[i + 1:j]
            title = next((b[4:].strip() for b in block if b.startswith("### ")), None)
            img = next((b for b in block if b.lstrip().startswith("<img ")), None)
            alt_m = re.search(r'<img alt="([^"]*)"', img) if img is not None else None
            alt = alt_m.group(1) if alt_m else None
            if title is None or alt is None:
                raise SourceError("%s: the block of figure %s has no `### ` title or no <img alt>" % (GALLERY, m.group(1)))
            try:
                end = next(k for k, b in enumerate(block) if b.strip() == "</picture>")
            except StopIteration:
                raise SourceError("%s: the block of figure %s has no </picture>" % (GALLERY, m.group(1)))
            body = "\n".join(block[end + 1:]).strip("\n")
            paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
            out.append({"name": m.group(1), "group": group, "title": title, "alt": unescape_attr(alt),
                        "paragraphs": paras, "body": body})
            i = j
            continue
        i += 1
    names = [o["name"] for o in out]
    if names != [t[0] for t in table]:
        raise SourceError("%s: the figures in its table (%s) are not the figures it describes (%s)" % (
            GALLERY, ", ".join(t[0] for t in table), ", ".join(names)))
    for o in out:
        for lead in ("**Shows.**", "**Does not show.**", "**Source.**"):
            if not any(p.startswith(lead) for p in o["paragraphs"]):
                raise SourceError("%s: the caption of %s has no `%s` paragraph" % (GALLERY, o["name"], lead))
    return out


def caption_paragraph(fig, lead):
    return next(p for p in fig["paragraphs"] if p.startswith(lead))


def readme_picture_alts(text, names):
    """{name: alt text} for the README's pictures of docs/img/bench/NAME-light.svg."""
    out = {}
    for name in names:
        m = re.search(r'<img alt="([^"]*)" src="%s/%s-light\.svg">' % (re.escape(BENCH_DIR), re.escape(name)), text)
        if not m:
            raise SourceError("README.md has no <img alt=...> for %s/%s-light.svg" % (BENCH_DIR, name))
        out[name] = unescape_attr(m.group(1))
    return out


# -------------------------------------------------------------------------------------------- the template
class Doc:
    """A document whose numbers cannot be typed. Lines are lists of parts. A part is a plain string (no digit
    allowed, bar NAMES_WITH_DIGITS), or what fact(), quote(), block() or ref() returned."""

    def __init__(self):
        self.lines = []
        self.facts = collections.OrderedDict()
        self.quotes = collections.OrderedDict()
        self.refs = []
        self.used = collections.Counter()

    # registering
    def fact(self, fid, value, text, sources, rule):
        if fid in self.facts:
            raise DocError("fact %s is registered twice" % fid)
        if not sources or not all(sources):
            raise DocError("fact %s has no source: a number the script cannot trace is not printed" % fid)
        if not rule:
            raise DocError("fact %s has no rule" % fid)
        self.facts[fid] = {"id": fid, "value": value, "text": text, "sources": sources, "rule": rule}
        return ("F", fid)

    def quote(self, qid, text, source, rule):
        if qid in self.quotes:
            raise DocError("quotation %s is registered twice" % qid)
        if not source or not rule:
            raise DocError("quotation %s has no source or rule" % qid)
        self.quotes[qid] = {"id": qid, "text": text, "source": source, "rule": rule}
        return ("Q", qid)

    def block(self, qid):
        return ("B", qid)

    def ref(self, rel):
        self.refs.append(rel)
        return ("P", rel)

    # writing
    def line(self, *parts):
        for p in parts:
            if isinstance(p, str):
                stripped = p
                for name in NAMES_WITH_DIGITS:
                    stripped = stripped.replace(name, "")
                if re.search(r"\d", stripped):
                    raise DocError("a plain string with a digit in it, %r: a number reaches the document only as a "
                                   "fact with a source (Doc.fact), a quotation (Doc.quote) or a path (Doc.ref)" % p[:80])
            elif not (isinstance(p, tuple) and len(p) == 2 and p[0] in "FQBP"):
                raise DocError("a part that is neither a string nor a registered fact, quotation or path: %r" % (p,))
        self.lines.append(parts)

    def blank(self):
        self.lines.append(("",))

    def render(self):
        """(markdown, facts, quotes, refs): each fact and quotation must have been used, each use must be registered."""
        out = []
        for parts in self.lines:
            buf = []
            for p in parts:
                if isinstance(p, str):
                    buf.append(p)
                    continue
                kind, key = p
                if kind == "F":
                    if key not in self.facts:
                        raise DocError("fact %s is used and not registered" % key)
                    self.used["F:" + key] += 1
                    buf.append(self.facts[key]["text"])
                elif kind == "Q":
                    if key not in self.quotes:
                        raise DocError("quotation %s is used and not registered" % key)
                    self.used["Q:" + key] += 1
                    buf.append(" ".join(self.quotes[key]["text"].split()))
                elif kind == "P":
                    buf.append(key)
                elif kind == "B":
                    if key not in self.quotes:
                        raise DocError("quotation %s is used and not registered" % key)
                    self.used["Q:" + key] += 1
                    if len(parts) != 1:
                        raise DocError("block quotation %s shares its line" % key)
                    for ln in self.quotes[key]["text"].split("\n"):
                        buf.append(("> " + ln) if ln.strip() else ">")
                    buf = ["\n".join(buf)]
            out.append("".join(buf))
        for fid in self.facts:
            if self.used["F:" + fid] == 0:
                raise DocError("fact %s is registered and never printed" % fid)
        for qid in self.quotes:
            if self.used["Q:" + qid] == 0:
                raise DocError("quotation %s is registered and never printed" % qid)
        text = "\n".join(out).rstrip("\n") + "\n"
        facts = [dict(self.facts[k], used=self.used["F:" + k]) for k in self.facts]
        quotes = [{"id": q["id"], "chars": len(q["text"]), "source": q["source"], "rule": q["rule"]}
                  for q in self.quotes.values()]
        return text, facts, quotes, sorted(set(self.refs))


def commas(v):
    return "{:,}".format(int(v))


# ------------------------------------------------------------------------------------------- the document
def build(rd, ctx):
    """STATUS.md for the tree `rd` reads. `ctx`: commit_sha, commit_utc, tree_clean, png (are PNG renders in the
    archive), figures (the packager's list, see project_packager.collect_figures), light_docs ((path, reason)),
    archive_paths (every path the archive will hold). Returns (markdown, facts, quotes, refs, reads)."""
    d = Doc()
    git = [{"git": "rev-parse HEAD, log -1: the commit this tree is"}]
    F = d.fact

    def sc(rel, *path):
        """A number a figure's sidecar holds under its `data` key."""
        return rd.field(rel, "data", *path)

    # ---- the commit
    sha = ctx["commit_sha"]
    f_short = F("commit_short", sha[:7], sha[:7], git, "the first seven characters of the commit's full name")
    f_sha = F("commit_sha", sha, sha, git, "git rev-parse HEAD")
    f_when = F("commit_utc", ctx["commit_utc"], ctx["commit_utc"], git, "the commit's committer time, in UTC")

    # ---- the README's own words
    readme = rd.text(README)
    summ, dropped1 = fix_links(readme_summary(readme), ctx["archive_paths"])
    built, dropped2 = fix_links(readme_built(readme), ctx["archive_paths"])
    q_summ = d.quote("readme_summary", summ, rd.src(README, "from the title line to the first `## ` heading"),
                     "the README's opening block, unchanged but for links (an anchor points at the archive's README.md)")
    q_built = d.quote("readme_built", built, rd.src(README, "the table under `## What is built and working`"),
                      "the README's table of what is built, unchanged but for links")

    # ---- verification, read from the tree
    run = read_runner(rd)
    run_src = rd.src("verify/run.sh", "the `stage NAME \"` lines and the members of BUDGET_QUICK and BUDGET_GATE")
    f_stages = F("stages", run["stages"], commas(run["stages"]), [run_src],
                 "count of lines beginning `stage NAME \"` in verify/run.sh, as python/check_docs_index.py counts them")
    f_quick = F("quick", run["quick"], commas(run["quick"]), [run_src], "members of BUDGET_QUICK, $-references expanded")
    f_gate = F("gate", run["gate"], commas(run["gate"]), [run_src], "members of BUDGET_GATE, $-references expanded")
    f_full = F("full_only", run["stages"] - run["gate"], commas(run["stages"] - run["gate"]), [run_src],
               "the stages less the gate budget's members")
    benches = read_benches(rd)
    f_bench = F("benches", benches, commas(benches), [rd.src("tb/Makefile", "SIM_BENCHES, or the union of SIM_GROUP_ lists")],
                "python/figure_extracts.py's bench counter: the `make sim` list")
    proofs = read_proofs(rd)
    f_proofs = F("proofs", proofs, commas(proofs), [rd.src("formal/run.sh", "lines beginning `run_proof `")],
                 "count of run_proof lines in formal/run.sh")
    tests, defining, tests_src = read_tests(rd)
    f_tests = F("tests", tests, commas(tests), [tests_src], "lines beginning `def test_` in python/tests/*.py")
    f_tfiles = F("test_files", defining, commas(defining), [tests_src], "the .py files of python/tests that define at least one")
    total, agree, claims_src = read_sidecar_claims(rd)
    f_claims = F("sidecar_checks", total, commas(total), [claims_src], "the `checks` rows of every figure sidecar")
    f_agree = F("sidecar_checks_agree", agree, commas(agree), [claims_src], "those rows whose verdict is `agrees`")

    # ---- the card
    TL, SW, TM, CK, SP = (SIDECAR_DIR + "/" + n + ".json" for n in
                          ("stress-timeline", "stress-sweep", "stress-telemetry", "hw-clock", "perf-speedup"))
    sid, s1 = sc(TL, "run", "id")
    started, s2 = sc(TL, "run", "started")
    ended, s3 = sc(TL, "run", "ended")
    hours, s4 = sc(TL, "hours")
    legs, s5 = sc(TL, "legs", "total")
    bys, s6 = sc(TL, "legs", "by_status")
    cycles, s7 = sc(TL, "cycles_n")
    visits, s8 = sc(TL, "visits")
    tot = sum(bys.values())
    if tot != legs:
        raise SourceError("%s: the legs by status add to %d, the legs to %d" % (TL, tot, legs))
    other = legs - bys["pass"] - bys["skipped"]
    f_sid = F("stress_id", sid, sid, [s1], "the run's id")
    f_start = F("stress_started", started, started, [s2], "the run's start, on the box's clock as the records give it")
    f_end = F("stress_ended", ended, ended, [s3], "the run's end, on the same clock")
    f_hours = F("stress_hours", hours, "%.1f" % hours, [s4], "the run's wall time in hours")
    f_legs = F("legs_total", legs, commas(legs), [s5], "the legs the run ran")
    f_pass = F("legs_pass", bys["pass"], commas(bys["pass"]), [s6], "legs whose status is pass")
    f_skip = F("legs_skipped", bys["skipped"], commas(bys["skipped"]), [s6], "legs whose status is skipped")
    f_other = F("legs_other", other, commas(other), [s5, s6], "the legs less those that passed or were skipped")
    f_cyc = F("cycles", cycles, commas(cycles), [s7], "the cycles through the three images")
    f_vq = F("visits_quad", visits["quad"], commas(visits["quad"]), [s8], "visits to the quad image")
    f_vs = F("visits_single", visits["single"], commas(visits["single"]), [s8], "visits to the single image")
    f_vd = F("visits_deep", visits["deep"], commas(visits["deep"]), [s8], "visits to the deep image")
    cut_img, s9 = sc(TL, "cut", "image")
    cut_visit, s10 = sc(TL, "cut", "visit")
    cut_run, s11 = sc(TL, "cut", "legs_run")
    cut_of, s12 = sc(TL, "cut", "legs_of")
    f_cimg = F("stress_cut_image", cut_img, cut_img, [s9], "the image the run's last visit was to, which the deadline cut")
    f_cvis = F("stress_cut_visit", cut_visit, commas(cut_visit), [s10], "that visit's number among the visits to that image")
    f_crun = F("stress_cut_run", cut_run, commas(cut_run), [s11], "the legs of the battery that visit ran before the deadline")
    f_cof = F("stress_cut_of", cut_of, commas(cut_of), [s12], "the legs of the battery a visit has")
    cases, w1 = sc(SW, "cases_total")
    tile, w2 = sc(SW, "tile_cases")
    host, w3 = sc(SW, "host_cases")
    mism, w4 = sc(SW, "mismatches")
    exh, w5 = sc(SW, "exh_complete")
    exh_n, w6 = sc(SW, "exh_total")
    if tile + host != cases:
        raise SourceError("%s: tile cases and host cases do not add to the cases in all" % SW)
    f_cases = F("sweep_cases", cases, commas(cases), [w1], "the sweep's cases in all")
    f_tile = F("sweep_tile", tile, commas(tile), [w2], "cases from items that exercise the tile")
    f_tilep = F("sweep_tile_pct", 100.0 * tile / cases, "%.1f%%" % (100.0 * tile / cases), [w1, w2],
                "tile cases as a share of the cases in all")
    f_host = F("sweep_host", host, commas(host), [w3], "cases from items that run in libcft's host code")
    f_mism = F("sweep_mismatches", mism, commas(mism), [w4], "cases that disagreed with the oracle")
    f_exh = F("exh_complete", exh, commas(exh), [w5], "exhaustive items that covered every encoding")
    f_exhn = F("exh_total", exh_n, commas(exh_n), [w6], "exhaustive items")
    pw = {}
    for img in ("quad", "single", "deep"):
        v, srcr = sc(TM, "by_image", img, "median")
        pw[img] = F("power_" + img, v, "%.1f" % v, [srcr], "median board power over the samples taken with this image loaded")
    peak, t1 = sc(TM, "peak", "watts")
    nsamp, t2 = sc(TM, "n")
    f_peak = F("power_peak", peak, "%.1f" % peak, [t1], "the highest board power sampled")
    f_nsamp = F("power_samples", nsamp, commas(nsamp), [t2], "the sensor samples")
    att, c1 = sc(CK, "attempts")
    one, c2 = sc(CK, "max_single")
    four, c3 = sc(CK, "max_quad")
    missed, c4 = sc(CK, "n_missed")
    left, c5 = sc(CK, "left_out")
    # The figure does not claim to draw every build the ledger gives a slack for (its caption: "this page does not say
    # there are no others"), so these facts are the builds it DRAWS and the items it LISTS and does not draw.
    f_att = F("clock_attempts", len(att), commas(len(att)), [rd.src(CK, "the length of field attempts")],
              "the U50 builds the figure draws: the entries of its `attempts`, whose kernel slack it reads from the ledger")
    f_c1 = F("clock_single", one, commas(one), [c2], "the highest clock at which a drawn one-tile build closed timing, in MHz")
    f_c4 = F("clock_quad", four, commas(four), [c3], "the highest clock at which a drawn four-tile build closed timing, in MHz")
    f_cm = F("clock_missed", missed, commas(missed), [c4], "the drawn builds that missed")
    f_left = F("clock_left_out", len(left), commas(len(left)), [rd.src(CK, "the length of field left_out")],
               "the other figures of slack that the figure lists and does not draw, each with the reason")
    cells, p1 = sc(SP, "n_cells")
    wins, p2 = sc(SP, "wins")
    losses, p3 = sc(SP, "losses")
    best, p4 = sc(SP, "best")
    worst, p5 = sc(SP, "worst")
    if wins + losses != cells:
        raise SourceError("%s: wins and losses do not add to the cells" % SP)
    f_cells = F("speed_cells", cells, commas(cells), [p1], "the comparisons the figure draws")
    f_wins = F("speed_wins", wins, commas(wins), [p2], "comparisons in which the tile is ahead of the fastest real software")
    f_loss = F("speed_losses", losses, commas(losses), [p3], "comparisons in which it is behind")
    f_best = F("speed_best", best, "%.1f" % best, [p4], "the largest ratio of the tile's rate to the software's")
    f_worst = F("speed_worst", 1.0 / worst, "%.1f" % (1.0 / worst), [p5], "the reciprocal of the smallest such ratio")
    grid, p6 = sc(SP, "cells")
    n_min, n_max = min(c["n"] for c in grid), max(c["n"] for c in grid)
    f_nmin = F("speed_n_min", n_min, commas(n_min), [p6], "the smallest element count at which a drawn cell was measured")
    f_nmax = F("speed_n_max", n_max, commas(n_max), [p6], "the largest element count at which a drawn cell was measured")

    # ---- the math library
    MC, MM = SIDECAR_DIR + "/math-cost.json", SIDECAR_DIR + "/math-marks.json"
    cmin, m1 = sc(MC, "min")
    cmax, m2 = sc(MC, "max")
    rmin, m3 = sc(MC, "red_min")
    rmax, m4 = sc(MC, "red_max")
    runs, m5 = sc(MM, "runs")
    lanes, m6 = sc(MM, "lanes")
    marked, m7 = sc(MM, "marked")
    wrong, m8 = sc(MM, "wrong_unmarked")
    f_cmin = F("math_min", cmin, commas(cmin), [m1], "the fewest tile instructions in a routine's program")
    f_cmax = F("math_max", cmax, commas(cmax), [m2], "the most tile instructions in a routine's program")
    f_rmin = F("red_min", rmin, commas(rmin), [m3], "the fewest instructions range reduction takes in sin, cos or tan")
    f_rmax = F("red_max", rmax, commas(rmax), [m4], "the most instructions range reduction takes")
    f_runs = F("marks_runs", runs, commas(runs), [m5], "the captured mark-rate runs")
    f_lanes = F("marks_lanes", lanes, commas(lanes), [m6], "the lanes those runs sampled")
    f_marked = F("marks_marked", marked, commas(marked), [m7], "the lanes marked undecided")
    f_wrong = F("marks_wrong", wrong, commas(wrong), [m8], "the lanes that were wrong and not marked")

    # ---- the round
    led = read_ledger(rd)
    led_src = rd.src(LEDGER, "its `## ` headings and its line count")
    f_ent = F("ledger_entries", led["entries"], commas(led["entries"]), [led_src], "count of lines beginning `## `")
    f_lines = F("ledger_lines", led["lines"], commas(led["lines"]), [led_src], "the file's line count")
    f_first = F("ledger_first", led["first"], led["first"], [led_src], "the date at the start of the first dated heading")
    f_last = F("ledger_last", led["last"], led["last"], [led_src], "the date at the start of the newest heading")
    q_plan = d.quote("plan", read_plan(rd), rd.src(ROADMAP, "the last heading that says `plan of record`"),
                     "the heading of the roadmap's latest plan of record")
    q_new = d.quote("ledger_newest", "\n".join("- " + h for h in led["newest"]), led_src,
                    "the headings of the ledger's newest entries, oldest first")

    # ---- the figures
    figs = ctx["figures"]
    gallery_src = rd.src(GALLERY, "each figure's block: its title and its caption paragraphs")
    f_nfig = F("figure_count", len(figs), commas(len(figs)), [rd.src(GALLERY, "the figures in its table"),
                                                                   rd.src(README, "the pictures of docs/img/bench")],
               "the figures the archive holds: the gallery's, and the README's own charts")

    # ------------------------------------------------------------------------------------ write it
    d.line("# cft-fp256: where the project stands")
    d.blank()
    d.line("This is the state of the repository at commit ", f_short, ", in full ", f_sha, ", committed ", f_when,
           " UTC. ", "The tree it was made from was clean." if ctx["tree_clean"] else
           "The tree it was made from was NOT clean: `MANIFEST.json` lists what differed from the commit.")
    d.blank()
    d.line("It is made by `python/project_packager.py` from the project's own files. Every number outside a block "
           "quotation is read from the commit itself or from a committed file - the one named in the table, or the "
           "sidecar of the figure named beside it - and `MANIFEST.json` names each source with its SHA-256 and the rule "
           "that read it; the script refuses to write a number that no source gave it. A block quotation is copied "
           "from the file named under it. The date this archive was made is in its file name and in `MANIFEST.json`, "
           "and not here, so that two archives of one commit hold the same document.")
    d.blank()
    d.line("## What it is")
    d.blank()
    d.line(d.block("readme_summary"))
    d.blank()
    d.line("Source: `README.md`, from its title to its first second-level heading.")
    d.blank()
    d.line("## What is built")
    d.blank()
    d.line(d.block("readme_built"))
    d.blank()
    d.line("Source: `README.md`, the table under \"What is built and working\".")
    d.blank()
    d.line("## How much is checked")
    d.blank()
    d.line("| what is counted | how many | where it is read |")
    d.line("|---|---|---|")
    d.line("| runner stages | ", f_stages, " | `verify/run.sh`: the lines beginning `stage NAME` |")
    d.line("| in the quick budget | ", f_quick, " | `verify/run.sh`: `BUDGET_QUICK` |")
    d.line("| in the gate budget (quick is part of it) | ", f_gate, " | `verify/run.sh`: `BUDGET_GATE` |")
    d.line("| only in the full census | ", f_full, " | the stages less the gate budget |")
    d.line("| RTL benches run by `make sim` | ", f_bench, " | `tb/Makefile`: the bench list |")
    d.line("| formal proof tasks | ", f_proofs, " | `formal/run.sh`: the lines beginning `run_proof` |")
    d.line("| test functions in `python/tests` | ", f_tests, " | ", f_tfiles, " files: the lines beginning `def test_` |")
    d.blank()
    d.line("That last count is functions defined; pytest collects more, because one function can be run for each of "
           "many cases. Beside the gate, the figures are held to the record: of the ", f_claims, " checks the figures' "
           "sidecars hold (numbers that the README and other documents state, phrases, and presence or consistency "
           "checks), ", f_agree, " agree. Each figure's sidecar lists its own, and `python/project_figures.py --check`, "
           "which ran before this archive was made, makes them again on every run.")
    d.blank()
    d.line("## The card: its latest results")
    d.blank()
    d.line("These are the results the figures' sidecars hold, read from them below. Anything newer than the figures is "
           "in the ledger entries listed under the round: the ledger is the project's running record.")
    d.blank()
    d.line("The card's long stress run, ", f_sid, ", from ", f_start, " to ", f_end, " on the box's clock (", f_hours,
           " hours), ran ", f_legs, " legs in ", f_cyc, " cycles through the quad, single and deep images (", f_vq, ", ",
           f_vs, " and ", f_vd, " visits): ", f_pass, " passed, ", f_skip, " were skipped, and ", f_other, " did "
           "anything else (failed, timed out, found no device, could not be parsed, or errored). The run's last visit, "
           "to the ", f_cimg, " image (visit number ", f_cvis, "), was cut by the deadline after ", f_crun, " of its ",
           f_cof, " legs. Figure `stress-timeline`.")
    d.blank()
    d.line("Its native-oracle sweep covered ", f_cases, " cases in all, of which ", f_tile, " (", f_tilep, ") came from "
           "items that exercise the tile and ", f_host, " from items that run in libcft's host code on the box's CPU, "
           "where the tile does no work; ", f_mism, " cases disagreed with the oracle, and ", f_exh, " of ", f_exhn,
           " exhaustive items covered every encoding. The total is not a count of cases \"on the card\". Figure "
           "`stress-sweep`.")
    d.blank()
    d.line("Board power over the run, taken from ", f_nsamp, " sensor samples: the median was ", pw["quad"], " W with the "
           "quad image loaded, ", pw["single"], " W with the single and ", pw["deep"], " W with the deep one, and the "
           "highest sample was ", f_peak, " W. Figure `stress-telemetry`.")
    d.blank()
    d.line("Clock: the figure `hw-clock` draws the kernel slack of ", f_att, " U50 builds that it reads from the ledger, ",
           f_cm, " of them missed; of the builds drawn, one tile closed timing at up to ", f_c1, " MHz and four tiles at up "
           "to ", f_c4, " MHz. It lists ", f_left, " other figures of slack that it does not draw, each with the reason, and "
           "it does not say there are no others.")
    d.blank()
    d.line("Speed: the figure `perf-speedup` compares the resident tiles with the fastest real software for multiply, "
           "fused multiply-add and add, in ", f_cells, " cells (each an operation, a format, a machine and a number of "
           "tiles), each at the largest size that both the device sweep and the peer runs measured (", f_nmin, " to ",
           f_nmax, " elements here) and never below the figure's floor, under which a device call is mostly fixed cost. "
           "The tile is ahead in ", f_wins, " of them, by up to ", f_best, "x, and behind in ", f_loss, ", by up to ",
           f_worst, "x. It does not show divide, square root, the other operations or smaller sizes; its data is the "
           "README's own, the sweep and the peer runs in `docs/bench/`.")
    d.blank()
    d.line("The math library: its correctly rounded routines are programs of ", f_cmin, " to ", f_cmax, " tile "
           "instructions, and range reduction takes ", f_rmin, " to ", f_rmax, " of each of sin, cos and tan (figure "
           "`math-cost`). In ", f_runs, " captured runs over ", f_lanes, " lanes, ", f_marked, " lanes were marked "
           "undecided and ", f_wrong, " were wrong and not marked (figure `math-marks`).")
    d.blank()
    d.line("## The round")
    d.blank()
    d.line("The latest plan of record in `docs/ROADMAP.md`:")
    d.blank()
    d.line(d.block("plan"))
    d.blank()
    d.line("The validation ledger, `docs/VALIDATION.md`, describes itself as append-only. It holds ", f_ent, " entries in ",
           f_lines, " lines, from ", f_first, " to ", f_last, ". Its newest entries, in its own words:")
    d.blank()
    d.line(d.block("ledger_newest"))
    d.blank()
    d.line("## The figures")
    d.blank()
    how_png = (" and as a PNG render of each" if ctx["png"] else
               " (this archive was made with `--no-png`, so it holds no PNG render of them)")
    d.line("The archive holds ", f_nfig, " figures: the gallery's, drawn by `python/project_figures.py` from committed "
           "data, and the README's own charts. Each comes as a light and a dark SVG, exactly as committed", how_png,
           ", with its sidecar and its caption where it has them. The pictures below are the light ones, and each "
           "caption is its source's own.")
    d.blank()
    group = None
    for fg in figs:
        if fg["group"] != group:
            group = fg["group"]
            if fg["group_source"] is None:
                d.line("### ", group)
            else:
                slug = re.sub(r"[^a-z]+", "_", group.lower()).strip("_")
                d.line("### ", d.quote("group_" + slug, group, fg["group_source"], "the group's heading in its source"))
            d.blank()
        src = fg["caption_source"]
        d.line("#### ", d.quote("title_" + fg["name"], fg["title"], src, "the figure's title in its source"))
        d.blank()
        pic = fg["png_light"] if ctx["png"] else fg["svg_light"]
        alt = fg["alt"].replace("[", "(").replace("]", ")")
        d.line("![", d.quote("alt_" + fg["name"], alt, src, "the picture's own alt text in its source, with any square "
                             "bracket shown as a parenthesis"), "](", d.ref(pic), ")")
        d.blank()
        if fg["origin"] == "readme":
            d.line("The README's own caption for this chart, which has no sidecar:")
            d.blank()
        d.quote("cap_" + fg["name"], fg["caption_text"], src, fg["caption_rule"])
        d.line(d.block("cap_" + fg["name"]))
        d.blank()
        files = [fg["svg_light"], fg["svg_dark"]] + ([fg["png_light"], fg["png_dark"]] if ctx["png"] else [])
        parts = ["Files: "]
        for k, rel in enumerate(files):
            parts += ["`", d.ref(rel), "`", ", " if k + 1 < len(files) else ""]
        if fg["sidecar"]:
            parts += [", its sidecar `", d.ref(fg["sidecar"]), "`"]
        parts += [", its caption `", d.ref(fg["caption_file"]), "`."]
        d.line(*parts)
        d.blank()
    d.line("## What else is in this archive")
    d.blank()
    d.line("Light documents, copied as they stand, each for the reason given:")
    d.blank()
    for rel, why in ctx["light_docs"]:
        if rel in DATED_DOCS:
            day = newest_written_date(rd.text(rel), rel)
            f_day = F("written_" + re.sub(r"[^a-z]+", "_", rel.lower()).strip("_"), day, day,
                      [rd.src(rel, "the newest YYYY-MM-DD it writes")],
                      "the newest date written in the document itself, read from its text")
            d.line("- `", d.ref(rel), "`: ", why, "; the newest date the document itself writes is ", f_day, ".")
        else:
            d.line("- `", d.ref(rel), "`: ", why)
    d.blank()
    d.line("`MANIFEST.json` lists every other file here with its size and SHA-256 and where it came from, the converter and "
           "its fonts, and the sources of every number above. To check an archive against it, run `python "
           "python/project_packager.py --verify ARCHIVE.zip`. `", d.ref("STATUS.html"), "` is this page again, "
           "rendered for a browser: its words are checked against this page's, and `--verify` renders it again and "
           "compares. The links in the copied documents that point at files this archive does not hold do not resolve.")
    text, facts, quotes, refs = d.render()
    return text, facts, quotes, refs, dict(sorted(rd.log.items())), dropped1 + dropped2
