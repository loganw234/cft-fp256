# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Hold the documentation to the repository: links, coverage and stated counts.

Three families of claim, all mechanically checkable and all previously wrong:
docs/README.md's index of the documents; the counts the front-door files
state (runner stages, RTL benches, formal proofs, VERIFICATION.md's tiers,
the index's own totals) against the files that own them; and, since
2026-09-24, every tracked document's relative links and the repository
paths it quotes in backticks.

WHY THIS IS A GATE AND NOT A CONVENTION. docs/README.md is a hand-written
list of the documents, and this repo has twice paid for a list that
could lie about what it described: verify/run.sh kept its stage names in
three places until two of them drifted (clause5 and mpfr reached the run
without reaching --list, and the sim line claimed 15 targets after the
aggregate grew to 17), and one opcode assignment touched ten hand-written
lists across four languages. An index nobody checks is the same shape of
debt, and it fails in the most useless way available: a document is added,
the index does not mention it, and the file that exists to make documents
findable is the reason one is not.

Three things can go wrong and all three are mechanical:

  a link that does not resolve - the index sends a reader nowhere;
  a document present in docs/ and absent from the index - the exact
    failure the index was written to fix;
  a stated line count that has drifted - the index is a list of sizes as
    well as names, and a wrong size misleads about what a file costs to
    read.

Counts are checked rather than generated on purpose. Generating them would
make this file authoritative over prose somebody wrote deliberately; the
index is written by hand, in a voice, and this only refuses to let it be
wrong.

A quoted path is one in backticks whose first component is a top-level
directory of this repository. A path in ANOTHER repository is written with
that repository's name inside the backticks (`cft-rebound/docs/HARDWARE.md`)
so that it is not mistaken for one of ours. The ledger, docs/ROUND2.md and
the design studies (RECORD_DOCS), each of which docs/README.md must file
under "The record" or "The design studies", are exempt, since a path in them
is a fact about its date; so are the products of a build or a run, each tied
to a pattern in the file that produces it.

Every run also plants faults in a scratch copy of the documents - one per
entry in CONTROLS and run_controls, covering every check and branch here -
and requires each to be caught by name (HonestFramework METHOD section 3).
"Every check" is a measured claim, not an intention: on 2026-09-24 a
mutation test disabled each check and branch in turn, in memory, and every
mutation was caught by a control. Its first run found nine that were not,
in the version that first claimed this sentence.

    python python/check_docs_index.py          # report and exit nonzero
    python python/check_docs_index.py --quiet  # only on failure
"""
import pathlib
import posixpath
import re
import subprocess
import sys


def check_stage_counts(problems, root):
    """Stated stage counts must match what verify/run.sh derives.

    The runner is the only authority here: it greps its own `stage` calls, so
    adding a stage changes the number with no second edit. A document that
    quotes the number is a transcription, and on 2026-09-12 three of them
    quoted 37/24/32 against a real 36/23/31 - off by one, because the probe
    that produced them counted lines beginning with a marker and the legend
    line began with one too.
    """
    runner = root / "verify" / "run.sh"
    if not runner.is_file():
        problems.append("verify/run.sh is missing; cannot check stage counts")
        return None

    text = runner.read_text(encoding="utf-8", errors="replace")
    total = len(re.findall(r'^stage [a-z0-9-]+ "', text, re.M))

    def members(var):
        m = re.search(r"^%s=(\S*)" % var, text, re.M)
        if not m:
            return None
        out = []
        for part in m.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            if part.startswith("$"):
                inner = members(part[1:].strip("{}"))
                if inner:
                    out.extend(inner)
            else:
                out.append(part)
        return out

    quick = members("BUDGET_QUICK") or []
    gate = members("BUDGET_GATE") or []
    derived = {"total": total, "quick": len(quick), "gate": len(gate)}

    WORDS = {
        30: "thirty", 31: "thirty-one", 32: "thirty-two", 33: "thirty-three",
        34: "thirty-four", 35: "thirty-five", 36: "thirty-six",
        37: "thirty-seven", 38: "thirty-eight", 39: "thirty-nine",
        40: "forty", 41: "forty-one", 42: "forty-two", 43: "forty-three",
        44: "forty-four", 45: "forty-five",
    }

    for name in ("CLAUDE.md", "README.md", "docs/VERIFICATION.md",
                 "docs/README.md"):
        f = root / name
        if not f.is_file():
            continue
        # Bold stripped: "runs **35** of **41**" is the same claim.
        body = f.read_text(encoding="utf-8", errors="replace").replace("**", "")

        # "23 of 36 stages" / "31 of 36" - the pair must be (a budget, total).
        #
        # Scoped to lines that are ABOUT stages. An earlier version matched
        # every "N of M" in the file and flagged "71 of 148", a sentence about
        # vector sets. A check that fires on unrelated prose gets silenced,
        # and a silenced check catches nothing.
        ABOUT = ("stage", "budget", "verify-quick", "verify-gate",
                 "verify/run.sh")
        for line in body.splitlines():
            low = line.lower()
            if not any(k in low for k in ABOUT):
                continue
            for a, b in re.findall(r"(\d+) of (\d+)", line):
                a, b = int(a), int(b)
                if b != total:
                    problems.append("%s: %r says 'of %d' where verify/run.sh "
                                    "derives %d stages"
                                    % (name, line.strip()[:48], b, total))
                elif a not in (derived["quick"], derived["gate"]):
                    problems.append("%s says '%d of %d', which is neither the "
                                    "quick budget (%d) nor the gate budget (%d)"
                                    % (name, a, b, derived["quick"],
                                       derived["gate"]))

        # "all 36" / "all thirty-six stages"
        for n in re.findall(r"all (\d+)(?= with| stages)", body):
            if int(n) != total:
                problems.append("%s says 'all %s' where the runner derives %d"
                                % (name, n, total))
        # "thirty-six stages", and docs/README.md's "thirty-seven runner
        # stages" - which the bare form let drift past 38 on 2026-09-14.
        for word, num in ((w, n) for n, w in WORDS.items()):
            if re.search(r"\b%s (?:runner )?stages\b" % word, body) \
                    and num != total:
                problems.append("%s says '%s ... stages' where the runner "
                                "derives %d" % (name, word, total))

    return derived

def check_sim_bench_count(problems, root):
    """Stated RTL-bench counts must match what tb/Makefile derives.

    SIM_BENCHES is the list `make sim` runs and `check_results.py` reads,
    so it is the only authority. Four documents quoted "21" by hand on
    2026-09-14 when the twenty-second bench (krnlf128) was added; a count
    that is transcribed is a count that drifts, which is what the stage
    counts above already learned.
    """
    mk = root / "tb" / "Makefile"
    if not mk.is_file():
        problems.append("tb/Makefile is missing; cannot check the bench count")
        return None
    text = mk.read_text(encoding="utf-8", errors="replace")
    # The assignment spans backslash-continued lines.
    text = text.replace("\\\n", " ")
    m = re.search(r"^SIM_BENCHES\s*=\s*(.*)$", text, re.M)
    if not m:
        problems.append("tb/Makefile has no SIM_BENCHES assignment")
        return None
    total = len(m.group(1).split())

    WORDS = {20: "twenty", 21: "twenty-one", 22: "twenty-two",
             23: "twenty-three", 24: "twenty-four", 25: "twenty-five"}
    ABOUT = ("sim", "bench", "cocotb", "rtl", "target")
    for name in ("CLAUDE.md", "README.md", "docs/VERIFICATION.md",
                 "verify/run.sh"):
        f = root / name
        if not f.is_file():
            continue
        # Flattened, because prose wraps: "twenty-one\nbenches" is one
        # count, and a per-line scan (this check's first draft) missed it
        # in CLAUDE.md within the hour. The ABOUT filter applies to a
        # window before each match instead of to a line.
        # Bold stripped, as for the stages below, and any number the
        # shared NUMBER pattern reads rather than a fixed table of words.
        body = re.sub(r"\s+", " ",
                      f.read_text(encoding="utf-8", errors="replace")
                      .replace("**", "")).lower()
        pat = (r"\b" + NUMBER +
               r" (?:rtl sims|simulation targets|targets|benches|cocotb targets)\b")
        for m in re.finditer(pat, body):
            window = body[max(0, m.start() - 120):m.end()]
            if not any(k in window for k in ABOUT):
                continue
            tok = m.group(1)
            n = as_number(tok)
            if n != total:
                problems.append("%s: %r says %s where tb/Makefile derives %d "
                                "benches" % (name, m.group(0), tok, total))
    return total


# ---------------------------------------------------------------------------
# The rest of the tree's documents (added 2026-09-24).
#
# Everything above holds docs/README.md and four files' stage counts. A
# sweep of all fifty-three tracked documents that day found what that scope
# could not see: README.md's at-a-glance table said "**39** gate stages"
# for a runner of forty - bold, so the patterns above never matched it -
# and five backticked paths in live documents that name nothing in this
# repository (four of them another repository's documents, unqualified). HonestFramework's FAILURE-MODES #15 is this exact shape: "the
# docs are all updated", with the map itself stale. The defence it names is
# to make the cross-reference a gate rather than a habit, so it is one.

WORD_UNITS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
WORD_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
             "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
NUMBER = (r"(\d[\d,]*|(?:%s)(?:-(?:%s))?|%s)"
          % ("|".join(WORD_TENS), "|".join(WORD_UNITS), "|".join(WORD_UNITS)))


def as_number(tok):
    """'37', '48,612', 'thirty-seven', 'Twelve' -> int; None otherwise."""
    tok = tok.lower().replace(",", "")
    if tok.isdigit():
        return int(tok)
    if tok in WORD_UNITS:
        return WORD_UNITS[tok]
    tens, _, unit = tok.partition("-")
    if tens in WORD_TENS and (not unit or unit in WORD_UNITS):
        return WORD_TENS[tens] + (WORD_UNITS[unit] if unit else 0)
    return None


def tracked_files(root):
    """The repository's own list of what it contains, or None.

    Tracked rather than present on disk, so that a path which exists only
    as a build product on this machine is not mistaken for part of the
    repository - a clean clone, which is what a reader has, lacks it.
    """
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"],
                             capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def prose(text):
    """(line number, line) for every line outside a fenced code block.

    Fenced blocks hold commands, logs and placeholders written to be read
    as examples; the checks below are about what the prose claims.
    """
    fenced = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if not fenced:
            yield n, line


def paragraphs(text):
    """(first line number, the paragraph as one line) outside fenced blocks.

    This repository hard-wraps its prose, and Markdown lets a code span or a
    link's text run across a line break. Scanned a line at a time, a wrapped
    span inverts the backtick pairing for the rest of its line and its path
    is never seen - a review of this check found four such paths, all real.
    Joined into paragraphs, the pairing is the one a renderer makes.
    """
    start, buf, fenced = None, [], False
    for n, line in enumerate(text.splitlines(), 1):
        fence = line.lstrip().startswith("```")
        if fence:
            fenced = not fenced
        if not fence and not fenced and line.strip():
            if start is None:
                start = n
            buf.append(line.strip())
            continue
        if buf:                 # a blank line or a fence ends a paragraph
            yield start, " ".join(buf)
        start, buf = None, []
    if buf:
        yield start, " ".join(buf)


def index_sections(root):
    """docs/README.md as {section heading: [(href, stated lines), ...]}."""
    text = (root / "docs" / "README.md").read_text(encoding="utf-8")
    sections, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"^## (.+)$", line)
        if m:
            cur = m.group(1).strip()
            sections[cur] = []
            continue
        m = re.match(r"^\|\s*\[[^\]]+\]\(([^)]+)\)\s*\|\s*([\d,]+)\s*\|", line)
        if m and cur:
            sections[cur].append((m.group(1), int(m.group(2).replace(",", ""))))
    return sections


# Documents whose quoted paths are history rather than live claims, and the
# section of docs/README.md that makes each one a record. The exemption is
# re-derived on every run: a document the index stops filing under one of
# these sections fails the run by name, so the exemption cannot outlive the
# reason it was granted.
RECORD_SECTIONS = ("The record", "The design studies")
RECORD_DOCS = {
    "docs/VALIDATION.md": "the append-only ledger; a path in an entry is a fact about its date",
    "docs/ROUND2.md": "the round's plan, kept as written below its outcome box",
    "docs/studies/": "design studies, kept as written",
}

# Paths a document may quote that are products of a build or a run, not
# tracked files. Each names the file that produces it and a pattern that
# file must still contain, re-derived on every run: when the producer stops
# writing the path, the exemption fails by name instead of outliving its
# reason. A key also covers everything beneath it (verify/state/<run-id>/).
BUILD_OUTPUTS = {
    "host/cft-resident": ("host/Makefile", r"(?m)^cft-resident\$\(EXE\):"),
    "host/positive-run": ("host/Makefile", r"(?m)^positive-run\$\(EXE\):"),
    "host/device-test": ("host/Makefile", r"(?m)^device-test\$\(EXE\):"),
    "host/api-test": ("host/Makefile", r"(?m)^api-test\$\(EXE\):"),
    "host/remote-test": ("host/Makefile", r"(?m)^remote-test\$\(EXE\):"),
    "host/libcft.a": ("host/Makefile", r"(?m)^libcft\.a:"),
    "vectors/out": ("Makefile", r"--out vectors/out"),
    "verify/state": ("verify/run.sh", r'STATEROOT="\$ROOT/verify/state"'),
    "verify/_mpfr-prefix": ("verify/run.sh", r'pfx="\$ROOT/verify/_mpfr-prefix"'),
    "bindings/wasm/build": ("bindings/wasm/build.sh",
                            r"(?m)^OUT=bindings/wasm/build$"),
    "bindings/wasm/build/demos_negative_control.html":
        ("bindings/wasm/build_demos.sh",
         r'--out "\$OUT/demos_negative_control\.html"'),
}


def build_output(tok):
    """The BUILD_OUTPUTS key covering `tok`, or None."""
    for key in BUILD_OUTPUTS:
        if tok == key or tok.startswith(key + "/"):
            return key
    return None


def check_all_links(problems, root, tracked):
    """Every relative link and image in every tracked document resolves."""
    files = set(tracked)
    dirs = {posixpath.dirname(f) for f in tracked}
    for d in list(dirs):
        while d:
            d = posixpath.dirname(d)
            dirs.add(d)
    n = 0
    for doc in (f for f in tracked if f.endswith(".md")):
        text = (root / doc).read_text(encoding="utf-8", errors="replace")
        base = posixpath.dirname(doc)
        for line_no, line in paragraphs(text):
            hrefs = re.findall(r"\[[^\]]*\]\(([^)\s]+)\)", line)
            hrefs += re.findall(r"\b(?:src|srcset)=\"([^\"\s]+)\"", line)
            for href in hrefs:
                if href.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                n += 1
                target = posixpath.normpath(
                    posixpath.join(base, href.split("#")[0]))
                if target.startswith("../"):
                    continue          # another repository; not ours to hold
                if target not in files and target not in dirs:
                    problems.append("%s:%d: broken link %s" % (doc, line_no, href))
    return n


def check_quoted_paths(problems, root, tracked):
    """A path a live document quotes in backticks is in the repository."""
    files = set(tracked)
    dirs = set()
    for f in tracked:
        d = posixpath.dirname(f)
        while d and d not in dirs:
            dirs.add(d)
            d = posixpath.dirname(d)
    tops = {f.split("/")[0] for f in tracked if "/" in f}

    sections = index_sections(root)
    filed = {posixpath.normpath(posixpath.join("docs", h))
             for s in RECORD_SECTIONS for h, _ in sections.get(s, [])}
    for exempt in RECORD_DOCS:
        members = [f for f in tracked if f == exempt or
                   (exempt.endswith("/") and f.startswith(exempt) and f.endswith(".md"))]
        if not members:
            problems.append("record exemption %s names no tracked document"
                            % exempt)
        for f in members:
            if f not in filed:
                problems.append("%s is exempt from the quoted-path check as a "
                                "record, but docs/README.md no longer files it "
                                "under %s" % (f, " or ".join(RECORD_SECTIONS)))

    for path, (producer, pat) in BUILD_OUTPUTS.items():
        ptext = (root / producer).read_text(encoding="utf-8", errors="replace") \
            if (root / producer).is_file() else ""
        if not re.search(pat, ptext):
            problems.append("%s is exempt as a product of %s, which no longer "
                            "matches %s" % (path, producer, pat))

    n = 0
    for doc in (f for f in tracked if f.endswith(".md")):
        if any(doc == e or (e.endswith("/") and doc.startswith(e))
               for e in RECORD_DOCS):
            continue
        text = (root / doc).read_text(encoding="utf-8", errors="replace")
        for line_no, line in paragraphs(text):
            for span in re.findall(r"`([^`]+)`", line):
                for tok in span.split():
                    tok = re.sub(r"[:,;.)]+[\d,-]*$", "", tok).rstrip("/")
                    if "/" not in tok or tok.split("/")[0] not in tops:
                        continue
                    if re.search(r"[*<>${}\[\]?]|\.\.\.", tok):
                        continue      # a pattern or a placeholder, not a path
                    n += 1
                    if tok in files or tok in dirs:
                        continue
                    if build_output(re.sub(r"\.exe$", "", tok)):
                        continue
                    problems.append("%s:%d: `%s` is quoted but is not in the "
                                    "repository" % (doc, line_no, tok))
    return n


def check_prose_counts(problems, root, present):
    """Counts the four front-door files state that the checks above miss.

    Bold is stripped first: "**39** gate stages" is how README.md's table
    stated a stale count past the stage check. Each count is derived from
    the file that owns the fact, never from a second list.
    """
    runner = (root / "verify" / "run.sh").read_text(encoding="utf-8",
                                                    errors="replace")
    stages = len(re.findall(r'^stage [a-z0-9-]+ "', runner, re.M))
    formal = root / "formal" / "run.sh"
    proofs = len(re.findall(r"^run_proof ", formal.read_text(
        encoding="utf-8", errors="replace"), re.M)) if formal.is_file() else None
    ver = (root / "docs" / "VERIFICATION.md").read_text(encoding="utf-8",
                                                         errors="replace")
    layers = ver.split("## The layers", 1)[-1].split("\n## ", 1)[0]
    tiers = len(re.findall(r"^\d+\. \*\*", layers, re.M))

    derived = [
        ("stages", stages, r"%s (?:gate |runner )?stages\b"),
        ("proofs", proofs, r"%s (?:machine-checked )?(?:proofs|proof tasks)\b"),
        ("proofs", proofs, r"%s tasks \+ a negative control"),
        ("tiers", tiers, r"%s tiers\b"),
        ("documents", len(present), r"indexes (?:the )?%s documents\b"),
    ]
    for name in ("CLAUDE.md", "README.md", "docs/VERIFICATION.md",
                 "docs/README.md"):
        f = root / name
        if not f.is_file():
            continue
        body = re.sub(r"\s+", " ", f.read_text(encoding="utf-8",
                                               errors="replace").replace("**", ""))
        for what, value, pat in derived:
            if value is None:
                continue
            for m in re.finditer(r"(?i)\b" + pat % NUMBER, body):
                near = body[max(0, m.start() - 80):m.end() + 40]
                if what == "stages" and re.search(
                        r"(?i)\b(?:pipe\w*|fma|core|deep)\b", near):
                    continue      # a pipeline's depth, not the runner's
                if what == "tiers" and not re.search(
                        r"(?i)verif|layer|stage|gate|page", near):
                    continue      # tiers of something else
                if as_number(m.group(1)) != value:
                    problems.append("%s says %r where the tree derives %d %s"
                                    % (name, m.group(0), value, what))

    # docs/README.md's opening: the file and line totals, and the four
    # subtotals by kind. Each subtotal is the sum of the rows of the
    # sections it names; every section with rows belongs to exactly one.
    index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    sections = index_sections(root)
    m = re.search(r"(?im)^%s files, ([\d,]+) lines\." % NUMBER, index)
    rows_total = sum(c for rows in sections.values() for _, c in rows)
    if not m:
        problems.append("docs/README.md no longer opens with '<N> files, <M> "
                        "lines.' - the check cannot hold its totals")
    else:
        if as_number(m.group(1)) != len(present):
            problems.append("docs/README.md says %r files where docs/ holds %d"
                            % (m.group(1), len(present)))
        if as_number(m.group(2)) != rows_total:
            problems.append("docs/README.md says %s lines in total where its "
                            "own rows sum to %d" % (m.group(2), rows_total))
    KINDS = (("you consult", ("Start here", "The contract", "Reference")),
             ("tool manual", ("The tools",)),
             ("operations", ("Operations",)),
             ("record", RECORD_SECTIONS))
    claimed_sections = set()
    for key, heads in KINDS:
        mm = re.search(r"\*\*([\d,]+) lines [^*]*%s[^*]*\*\*" % key, index)
        secs = [s for s in sections if s.startswith(heads)]
        claimed_sections.update(secs)
        if not mm:
            problems.append("docs/README.md no longer states the '%s' "
                            "subtotal" % key)
            continue
        want = sum(c for s in secs for _, c in sections[s])
        if as_number(mm.group(1)) != want:
            problems.append("docs/README.md says %s lines %s where the rows "
                            "under %s sum to %d"
                            % (mm.group(1), key, ", ".join(secs), want))
    for s, rows in sections.items():
        if rows and s not in claimed_sections:
            problems.append("docs/README.md section %r is in none of the four "
                            "subtotals" % s)


def run_checks(root, tracked):
    """Every check, against the tree at `root`. Returns (problems, stats)."""
    docs = root / "docs"
    index = docs / "README.md"
    problems = []
    text = index.read_text(encoding="utf-8")

    # 1. Every relative link resolves.
    links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
    rel = [h for h in links if not h.startswith(("http://", "https://", "#"))]
    for href in sorted(set(rel)):
        if not (index.parent / href).exists():
            problems.append("broken link: %s" % href)

    # 2. Every document under docs/ is listed. The index does not list
    #    itself, and a link may be written with either separator.
    listed = {h.replace("\\", "/") for h in rel}
    present = sorted(str(p.relative_to(docs)).replace("\\", "/")
                     for p in docs.rglob("*.md") if p.name != "README.md")
    for d in present:
        if d not in listed:
            problems.append("not listed in the index: docs/%s" % d)

    # 3. Stated line counts match. The index writes them with thousands
    #    separators, so compare on digits.
    rows = re.findall(r"\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([\d,]+)\s*\|", text)
    for _name, href, claimed in rows:
        p = index.parent / href
        if not p.exists():
            continue                      # already reported as a broken link
        actual = len(p.read_text(encoding="utf-8",
                                 errors="replace").splitlines())
        want = int(claimed.replace(",", ""))
        if actual != want:
            problems.append("line count drift: %s says %s, file has %d"
                            % (href, claimed, actual))

    stages = check_stage_counts(problems, root)
    check_sim_bench_count(problems, root)
    check_prose_counts(problems, root, present)
    nlinks = check_all_links(problems, root, tracked)
    npaths = check_quoted_paths(problems, root, tracked)
    return problems, {"present": len(present), "index_links": len(set(rel)),
                      "stages": stages, "links": nlinks, "paths": npaths,
                      "docs": sum(1 for f in tracked if f.endswith(".md"))}


# The planted faults. Each is put into a scratch copy of the documents and
# must produce a problem, absent from the unplanted copy, that matches its
# pattern - so every check above has been watched to fail, on every run,
# rather than once when it was written. (file, text appended, pattern.)
CONTROLS = (
    ("docs/INTEGRATION.md", "\nSee [nothing](NO-SUCH-DOC.md).\n",
     r"^docs/INTEGRATION\.md:\d+: broken link NO-SUCH-DOC\.md$"),
    ("CONFORMANCE.md", "\n![x](docs/img/no-such.svg)\n",
     r"^CONFORMANCE\.md:\d+: broken link docs/img/no-such\.svg$"),
    ("docs/BITSTREAM-BUILDS.md", "\nRun `hw/no-such-script.sh` first.\n",
     r"^docs/BITSTREAM-BUILDS\.md:\d+: `hw/no-such-script\.sh` is quoted"),
    ("README.md", "\n| **99** gate stages |\n",
     r"^README\.md says '99 gate stages'"),
    ("docs/VERIFICATION.md", "\nThe gate is 99 machine-checked proofs.\n",
     r"^docs/VERIFICATION\.md says '99 machine-checked proofs'"),
    ("docs/README.md", "\nThe verification map: Ninety-nine tiers.\n",
     r"^docs/README\.md says 'Ninety-nine tiers'"),
    ("docs/VERIFICATION.md", "\n`docs/README.md` indexes the ninety documents.\n",
     r"^docs/VERIFICATION\.md says 'indexes the ninety documents'"),
    ("README.md", "\n| 99 RTL sims |\n", r"^README\.md: '99 rtl sims'"),
    ("docs/FUNDING.md", "\none line more than the index says\n",
     r"^line count drift: FUNDING\.md"),
    ("docs/README.md", "\nSee [x](NO-SUCH-INDEXED.md).\n",
     r"^broken link: NO-SUCH-INDEXED\.md$"),
    ("CONFORMANCE.md", '\n<img src="docs/img/no-such-html.svg">\n',
     r"^CONFORMANCE\.md:\d+: broken link docs/img/no-such-html\.svg$"),
    ("CLAUDE.md", "\nThe gate budget runs 35 of 99 stages.\n",
     r"^CLAUDE\.md: '.*' says 'of 99' where verify/run\.sh derives"),
    ("docs/VERIFICATION.md", "\nIt runs all 99 with one command.\n",
     r"^docs/VERIFICATION\.md says 'all 99' where the runner derives"),
    ("docs/README.md", "\nthirty runner stages\n",
     r"^docs/README\.md says 'thirty \.\.\. stages' where the runner derives"),
    ("README.md", "\n99 tasks + a negative control\n",
     r"^README\.md says '99 tasks \+ a negative control'"),
    ("CLAUDE.md", "\ntwenty RTL sims\n",
     r"^CLAUDE\.md: 'twenty rtl sims' says twenty where tb/Makefile derives"),
    # A span and a link that wrap, as this repo's hard-wrapped prose does,
    # and the bold forms of the bench and budget counts.
    ("docs/ZOOM.md", "\nRun `bash\nhw/no-such-wrapped.sh` first.\n",
     r"^docs/ZOOM\.md:\d+: `hw/no-such-wrapped\.sh` is quoted"),
    ("docs/ORBITS.md", "\nSee [the long\nname](NO-SUCH-WRAPPED.md).\n",
     r"^docs/ORBITS\.md:\d+: broken link NO-SUCH-WRAPPED\.md$"),
    ("README.md", "\n| **98** RTL sims |\n", r"^README\.md: '98 rtl sims'"),
    ("CLAUDE.md", "\nThe gate budget runs **35** of **98** stages.\n",
     r"^CLAUDE\.md: '.*' says 'of 98' where verify/run\.sh derives"),
)


def run_controls(root, tracked, baseline):
    """Plant each fault in a scratch copy; each must be caught by name."""
    import shutil
    import tempfile
    failures = []
    with tempfile.TemporaryDirectory(prefix="check_docs_index-") as tmp:
        t = pathlib.Path(tmp)
        copy = [f for f in tracked if f.endswith(".md")] + [
            "verify/run.sh", "tb/Makefile", "formal/run.sh"] + sorted(
            {producer for producer, _ in BUILD_OUTPUTS.values()})
        for f in copy:
            if (root / f).is_file():
                (t / f).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / f, t / f)
        base = set(run_checks(t, tracked)[0])
        if base != set(baseline):
            failures.append("the scratch copy does not reproduce the tree's "
                            "own verdict, so no control below proves anything")
        # Structural controls: the totals line, a subtotal, a record
        # exemption and a build-product exemption, each broken in turn.
        idx = (t / "docs" / "README.md").read_text(encoding="utf-8")
        edits = [
            ("docs/README.md", idx, re.sub(
                r"(?im)^(%s files, )([\d,]+)( lines\.)" % NUMBER,
                lambda m: m.group(1) + "1" + m.group(4), idx, count=1),
             r"^docs/README\.md says 1 lines in total"),
            ("docs/README.md", idx, re.sub(r"\*\*[\d,]+ lines you consult",
                                           "**1 lines you consult", idx, count=1),
             r"^docs/README\.md says 1 lines you consult"),
            ("docs/README.md", idx, idx.replace("\n## The record\n",
                                                "\n## The past\n", 1),
             r"^docs/VALIDATION\.md is exempt .* no longer files it"),
        ]
        edits += [
            ("docs/README.md", idx, re.sub(
                r"(?m)^\|\s*\[FUNDING\.md\]\(FUNDING\.md\).*\n", "", idx, count=1),
             r"^not listed in the index: docs/FUNDING\.md$"),
            ("docs/README.md", idx, re.sub(
                r"(?im)^%s( files, )" % NUMBER,
                lambda m: "1" + m.group(2), idx, count=1),
             r"^docs/README\.md says '1' files where docs/ holds"),
            ("docs/README.md", idx, re.sub(r"\*\*[\d,]+ lines of tool manual",
                                           "**1 lines of tool manual", idx, count=1),
             r"^docs/README\.md says 1 lines tool manual"),
            ("docs/README.md", idx, re.sub(r"\*\*[\d,]+ lines of operations",
                                           "**1 lines of operations", idx, count=1),
             r"^docs/README\.md says 1 lines operations"),
            ("docs/README.md", idx, re.sub(r"\*\*[\d,]+ lines of record",
                                           "**1 lines of record", idx, count=1),
             r"^docs/README\.md says 1 lines record"),
            ("docs/README.md", idx, idx.replace("\n## Operations", "\n## Doing things", 1),
             r"^docs/README\.md section .* is in none of the four subtotals$"),
        ]
        cl = (t / "CLAUDE.md").read_text(encoding="utf-8")
        edits.append(("CLAUDE.md", cl, re.sub(r"\b\d+ of (\d+) stages",
                                              r"1 of \1 stages", cl, count=1),
                      r"^CLAUDE\.md says '1 of \d+', which is neither"))
        mk = (t / "host" / "Makefile").read_text(encoding="utf-8")
        edits.append(("host/Makefile", mk,
                      re.sub(r"(?m)^cft-resident\$\(EXE\):", "x-gone:", mk),
                      r"^host/cft-resident is exempt as a product of "
                      r"host/Makefile, which no longer matches"))
        rs = (t / "verify" / "run.sh").read_text(encoding="utf-8")
        edits.append(("verify/run.sh", rs,
                      rs.replace('STATEROOT="$ROOT/verify/state"',
                                 'STATEROOT="$ROOT/verify/runs"', 1),
                      r"^verify/state is exempt as a product of verify/run\.sh"))
        for f, add, pat in CONTROLS:
            orig = (t / f).read_text(encoding="utf-8")
            edits.append((f, orig, orig + add, pat))
        for f, orig, planted, pat in edits:
            if planted == orig:
                failures.append("control on %s did not change the file, so "
                                "it proves nothing (%s)" % (f, pat))
                continue
            (t / f).write_text(planted, encoding="utf-8")
            try:
                got = set(run_checks(t, tracked)[0]) - base
            finally:
                (t / f).write_text(orig, encoding="utf-8")
            if not any(re.search(pat, p) for p in got):
                failures.append("NEGATIVE CONTROL FAILED TO FAIL: %s, planted "
                                "in %s; new problems: %s"
                                % (pat, f, sorted(got) or "none"))
        n = len(edits)
    return failures, n


def main(argv):
    quiet = "--quiet" in argv[1:]
    root = pathlib.Path(__file__).resolve().parent.parent
    index = root / "docs" / "README.md"

    if not index.is_file():
        sys.stderr.write("check_docs_index: %s is missing\n" % index)
        return 1
    tracked = tracked_files(root)
    if tracked is None:
        sys.stderr.write("check_docs_index: `git ls-files` failed, so the "
                         "links and quoted paths of every document could "
                         "not be checked - refusing rather than passing\n")
        return 1

    problems, stats = run_checks(root, tracked)
    failures, ncontrols = run_controls(root, tracked, problems)
    problems += failures
    stages = stats["stages"]

    if problems:
        sys.stderr.write("check_docs_index: %d problem(s)\n" % len(problems))
        for p in problems:
            sys.stderr.write("  %s\n" % p)
        sys.stderr.write("  docs/README.md is the index; edit it to match "
                         "docs/, or correct the count.\n")
        return 1

    if not quiet:
        print("check_docs_index: %d documents, %d links, every count true"
              % (stats["present"], stats["index_links"]))
        if stages:
            print("                  stage counts agree: %d total, %d quick, "
                  "%d gate" % (stages["total"], stages["quick"],
                               stages["gate"]))
        print("                  %d tracked documents: %d relative links "
              "resolve, %d quoted paths exist"
              % (stats["docs"], stats["links"], stats["paths"]))
        print("                  %d negative controls planted, each caught "
              "by name" % ncontrols)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
