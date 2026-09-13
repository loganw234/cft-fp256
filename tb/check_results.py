# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Read the results files a cocotb run wrote and fail if any test failed.

WHY THIS EXISTS. cocotb cannot set an exit code. Its own makefile says so
in as many words, at Makefile.inc:88 of cocotb 1.9.2:

    # Check that the COCOTB_RESULTS_FILE was created, since we can't set
    # an exit code from cocotb.
    define check_for_results_file
        @test -f $(COCOTB_RESULTS_FILE) || (echo "ERROR: ... was not
            written by the simulation!" >&2 && exit 1)
    endef

That check tests for the file's EXISTENCE and nothing else. A bench whose
assertions fail still writes a results file, so the file exists, so the
check passes, so make returns 0. Compile and elaboration failures do
propagate - cocotb removes the results file before each run, so a bench
that never got to write one trips the check above - and a bench that
hangs is caught by the `timeout` wrappers in tb/Makefile. The hole is
narrow and it is the worst one available: a bench that RAN, COMPARED
against the golden model, FOUND a mismatch, and recorded it in XML that
nothing opened.

`make sim` is twenty-one benches. Until this file existed, it could
report success with any number of them red. In a project whose claim is
that every number is checked, the suite's own exit code was the one
number nobody checked.

WHAT COUNTS AS FAILURE, and why a missing file is one of them. cocotb
writes JUnit XML: testsuite elements holding testcase elements, a failed
case carrying a <failure> child and an errored one an <error> child. Any
of those fails this check. So does a results file that is absent or
unparseable - because the caller names the files it expects, and a bench
that was asked for and left nothing behind has not passed, it has
vanished. That distinction is the reason this takes an explicit list of
files rather than globbing a directory: a glob cannot tell "nineteen of
twenty-one benches passed" from "twenty-one passed", and the first is a
red suite.

Skipped cases are reported but do not fail. cocotb marks a case skipped
when the bench itself decided the configuration does not apply, which is
a statement about coverage rather than correctness - but it is printed,
because a suite quietly skipping half its cases is worth seeing.
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def read_one(path):
    """-> (n_cases, [failure strings], n_skipped) or None if unreadable."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as exc:
        return ("unparseable", ["%s: %s" % (p, exc)], 0)

    cases = 0
    bad = []
    skipped = 0
    # The root may be <testsuites> or a single <testsuite>; iterate
    # descendants so both shapes read the same.
    for case in root.iter("testcase"):
        cases += 1
        name = "%s.%s" % (case.get("classname", "?"), case.get("name", "?"))
        for child in case:
            tag = child.tag.lower()
            if tag in ("failure", "error"):
                msg = (child.get("message") or (child.text or "").strip()
                       or tag)
                bad.append("%s: %s" % (name, msg.splitlines()[0][:120]))
            elif tag == "skipped":
                skipped += 1
    return (cases, bad, skipped)


def main(argv):
    if len(argv) < 2:
        sys.stderr.write(
            "usage: check_results.py <results.xml> [<results.xml> ...]\n"
            "  Fails if any named file records a failure or is missing.\n")
        return 2

    paths = argv[1:]
    total_cases = 0
    total_skipped = 0
    failed_benches = []
    missing = []
    empty = []

    for path in paths:
        got = read_one(path)
        # The bench name is the directory, which is how tb/Makefile names
        # them: sim_build/<bench>/results.xml.
        bench = Path(path).parent.name or path
        if got is None:
            missing.append(bench)
            print("  %-14s MISSING  %s" % (bench, path))
            continue
        cases, bad, skipped = got
        total_skipped += skipped
        if cases == "unparseable":
            failed_benches.append(bench)
            print("  %-14s UNPARSEABLE" % bench)
            for line in bad:
                print("       %s" % line)
            continue
        total_cases += cases
        # A bench that ran and compared NOTHING is not a bench that passed.
        # Measured 2026-09-12: a parseable results.xml with an empty
        # <testsuite> printed "ok 0 case(s)" and this file returned 0 - the
        # same vacuity it exists to close, one layer in. cocotb writes at
        # least one testcase for any bench that reached its coroutine, so zero
        # means the bench was collected and never ran.
        if cases == 0:
            empty.append(bench)
            print("  %-14s EMPTY    parsed, but recorded no test case" % bench)
            continue
        if bad:
            failed_benches.append(bench)
            print("  %-14s FAIL     %d case(s) of %d" % (bench, len(bad), cases))
            for line in bad:
                print("       %s" % line)
        else:
            note = "  (%d skipped)" % skipped if skipped else ""
            print("  %-14s ok       %d case(s)%s" % (bench, cases, note))

    print("-- %d bench(es), %d case(s), %d skipped" %
          (len(paths), total_cases, total_skipped))

    if missing or failed_benches or empty:
        # stdout holds the per-bench detail and stderr the verdict; without
        # this flush the verdict overtakes the table it summarises, and a
        # CI log reads "FAIL" with the reason printed underneath it.
        sys.stdout.flush()
        parts = []
        if failed_benches:
            parts.append("%d failed (%s)" %
                         (len(failed_benches), " ".join(failed_benches)))
        if missing:
            parts.append("%d wrote no results (%s)" %
                         (len(missing), " ".join(missing)))
        if empty:
            parts.append("%d recorded no cases (%s)" %
                         (len(empty), " ".join(empty)))
        sys.stderr.write("FAIL: " + ", ".join(parts) + "\n")
        return 1

    print("PASS: %d bench(es), no failures recorded" % len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
