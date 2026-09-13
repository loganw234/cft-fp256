# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Hold docs/README.md to docs/: links resolve, nothing omitted, counts true.

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
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
