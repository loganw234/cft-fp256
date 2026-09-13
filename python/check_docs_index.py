# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Hold the documentation to the repository: links, coverage and stated counts.

Two families of claim, both mechanically checkable and both previously wrong:
docs/README.md's index of the documents, and the runner's stage counts as
quoted in CLAUDE.md, README.md and docs/VERIFICATION.md.

WHY THIS IS A GATE AND NOT A CONVENTION. docs/README.md is a hand-written
list of thirty-four files, and this repo has twice paid for a list that
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

    python python/check_docs_index.py          # report and exit nonzero
    python python/check_docs_index.py --quiet  # only on failure
"""
import pathlib
import re
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
        37: "thirty-seven", 38: "thirty-eight",
    }

    for name in ("CLAUDE.md", "README.md", "docs/VERIFICATION.md"):
        f = root / name
        if not f.is_file():
            continue
        body = f.read_text(encoding="utf-8", errors="replace")

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
        for word, num in ((w, n) for n, w in WORDS.items()):
            if ("%s stages" % word) in body and num != total:
                problems.append("%s says '%s stages' where the runner derives "
                                "%d" % (name, word, total))

    return derived

def main(argv):
    quiet = "--quiet" in argv[1:]
    root = pathlib.Path(__file__).resolve().parent.parent
    docs = root / "docs"
    index = docs / "README.md"

    if not index.is_file():
        sys.stderr.write("check_docs_index: %s is missing\n" % index)
        return 1

    text = index.read_text(encoding="utf-8")
    problems = []

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

    if problems:
        sys.stderr.write("check_docs_index: %d problem(s)\n" % len(problems))
        for p in problems:
            sys.stderr.write("  %s\n" % p)
        sys.stderr.write("  docs/README.md is the index; edit it to match "
                         "docs/, or correct the count.\n")
        return 1

    if not quiet:
        print("check_docs_index: %d documents, %d links, every count true"
              % (len(present), len(set(rel))))
        if stages:
            print("                  stage counts agree: %d total, %d quick, "
                  "%d gate" % (stages["total"], stages["quick"],
                               stages["gate"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
