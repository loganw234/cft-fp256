#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The dry run's tests for hw/card_stress.py: no XRT, no card, no amd-arc-box.

    python3 hw/test_card_stress.py [--only NAME,...] [--no-plants]      (bash hw/test-card-stress.sh)

Three kinds of group, then the plants (the groups, by name, are in hw/test-card-stress.sh):
  parsers   the verdict parsers on REAL logs - the software backend's own runs of the same
            tools (hw/card_stress_fixtures/, made in WSL on 2026-10-16 from this tree's
            sources) - and on lines built from the tools' printf text; every parser must fail
            loudly on a log with its verdict line removed, doubled, damaged or contradicted by
            the exit status; and each parser's wording is found in the tool's own source.
  commands  the legs' command lines and timeouts, read off a Driver without running it.
  scenarios the driver itself as a subprocess against hw/card_stress_standin.py, which prints
            the tools' verdict lines and fails, hangs, loses the device or disagrees on a
            schedule: the scheduler, the rotation, the deadline, the stop file, the failure
            policy, the timeouts, the stray processes, the guard, the disk floor, the metrics,
            the sweep's resume and the report.
  plants    a NEGATIVE CONTROL for each class of check: one defect put back into a copy of the
            code, and the scenario written for it must FAIL. A check that cannot fail proves
            nothing (the standard hw/test-sweep-judge.sh sets).
  pool, seeds, trees   (parcel DR2, 2026-10-20) the host pool - the card's waves and the pool's slices by
            reach, STOP and the deadline, a host job's failure, --resume, the lock on the metrics
            file - the seed schedule over the catalog and across runs (--earlier-runs, an old run
            resumed), and coverage by tree (the tree the driver records, the report's section, --also).
  items, chunk, records, notes, standin   (parcel DR3, 2026-10-21) items: the 35 hard-case and class-level items in the catalog - held to
            the documents' figures and to the REAL tools' logs, planned, served to the end of their spaces and refused when short; chunk:
            --sweep-chunk, the tool's pass-size line held to the request, random scaleB's cases at a BATCH, and the rule for which random
            streams are repeats of which; records: the campaign's own space, --records/--sign-key/--device-key and their refusals, the record
            sink on a real dry run's records (refused as they stand; written with the one field that says 'dry run' changed in a scratch
            directory) and a real, NOT dry run of the driver over test doubles (POSIX); notes: --quick --sweep-items after an empty wave,
            figure_extracts' cpu filter (needs CARD_STRESS_METRICS), and standin_alive (its own group, `standin`, which its plants run).

POSIX-only checks (the `nice` and `timeout` wrappers, a process that ignores SIGTERM) are
SKIPped by name on Windows and run under WSL or on the box. Everything runs niced by the
caller's choice; nothing here starts anything heavy. Prints one line a group and a last line
"card-stress test: N checks, F failed, S skipped".
"""
from __future__ import annotations

import contextlib
import gzip
import hashlib
import importlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# CARD_STRESS_TEST_ROOT: a copy of this file run from a plant's directory (see plants) reads the
# real tree's tool sources, not its own parent directory
ROOT = os.environ.get("CARD_STRESS_TEST_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
import card_stress_lib as L  # noqa: E402

POSIX = os.name == "posix"
FIX = os.path.join(HERE, "card_stress_fixtures")
# an image the driver's OWN environment names, as an operator's shell might: no host-pool job may inherit it
LEAKED_ARTIFACT = "/leaked/by/the/environment.xclbin"

CHECKS = 0
FAILS: list = []
SKIPS: list = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}"[:400])
    return bool(ok)


def rmtree_force(path) -> None:
    """shutil.rmtree that also removes read-only files. The object files of a git repository are read-only, and on Windows
    shutil.rmtree(path, ignore_errors=True) leaves such a directory behind without a word (found 2026-10-20: thirteen of this
    parcel's own, each holding a scratch repository the tree tests made)."""
    def fix(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=fix)
        else:
            shutil.rmtree(path, onerror=fix)
    except OSError:
        pass


def skip(name: str, why: str) -> None:
    SKIPS.append(f"{name}: {why}")
    print(f"  SKIP  {name} - {why}")


# ---------------------------------------------------------------------------------------
# the parsers
# ---------------------------------------------------------------------------------------

def fixture(name: str) -> str:
    with open(os.path.join(FIX, name), "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def fixture_job(index: dict, nm: str):
    """(op, lo, hi, mode) of the soak command a fixture was made with, read from INDEX.txt, so
    the slice a check holds a log to is the one the log was made over."""
    cmd = re.sub(r" \[\d+ s\]$", "", index[nm][1]).split()
    while cmd and (cmd[0] == "env" or "=" in cmd[0]):
        cmd.pop(0)
    return cmd[1], int(cmd[2], 0), int(cmd[3], 0), (cmd[4] if len(cmd) > 4 else None)


def raises(fn) -> bool:
    try:
        fn()
    except L.VerdictError:
        return True
    return False


def squash(text: str) -> str:
    """A source file with adjacent string literals joined, so a message the tool prints from
    two literals is found as one (C: "a" "b"; Python: "a" f"b"; shell is left as it is)."""
    return re.sub(r'"\s*\n\s*f?"', "", text)


def source_has(path: str, *frags: str) -> list:
    with open(os.path.join(ROOT, path), "r", encoding="utf-8", errors="replace") as fh:
        text = squash(fh.read())
    return [f for f in frags if f not in text]


def group_parsers(tag: str = "") -> list:
    """Returns [(name, ok, detail)] so a plant can ask whether any check failed."""
    out: list = []

    def c(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), detail))

    index = {}
    with open(os.path.join(FIX, "INDEX.txt"), "r", encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip() and not ln.startswith("#"):
                nm, rc, cmd = ln.rstrip("\n").split("\t", 2)
                index[nm] = (int(rc), cmd)

    def rc_of(nm: str) -> int:
        return index[nm][0]

    # -- api-test: a real log, and its damages
    t = fixture("api-test.txt")
    v = L.parse_api_test(t, rc_of("api-test.txt"))
    c("api-test real log: pass, failed 0", v.ok and v.counts == {"failed": 0})
    c("api-test: the log without its verdict line is refused",
      raises(lambda: L.parse_api_test(t.replace("api-test: all contract checks passed", ""), 0)))
    c("api-test: a doubled verdict line is refused",
      raises(lambda: L.parse_api_test(t + "api-test: all contract checks passed\n", 0)))
    c("api-test: a pass line with a nonzero exit status is refused", raises(lambda: L.parse_api_test(t, 1)))
    c("api-test: FAILED with exit 1 is a failure with its count",
      (lambda r: (not r.ok) and r.counts == {"failed": 3})(L.parse_api_test("x\napi-test: 3 FAILED\n", 1)))
    c("api-test: 'FAILED' with exit 0 is refused", raises(lambda: L.parse_api_test("api-test: 3 FAILED\n", 0)))
    c("api-test: a damaged line (contract chekcs) is refused",
      raises(lambda: L.parse_api_test(t.replace("contract checks", "contract chekcs"), 0)))

    # -- device-test: real logs of the four matrices (the software backend), and damages
    for nm, mode in (("dt-q8-sw.txt", "q8"), ("dt-n256-sw.txt", "full"), ("dt-r-sw.txt", "r"),
                     ("dt-b-sw.txt", "b")):
        t = fixture(nm)
        v = L.parse_device_test(t, rc_of(nm), mode)
        m = re.search(r"^(\d+) checks, 0 failed$", t, re.M)
        c(f"device-test {nm}: pass with the log's own count", v.ok and v.counts["checks"] == int(m.group(1)),
          str(v.counts))
        c(f"device-test {nm}: NOT TESTED and NOT RUN are the log's own, not defaults",
          v.counts.get("not_tested") == int(re.search(r"NOT TESTED (\d+)", t).group(1))
          and v.counts.get("not_run") == int(re.search(r"NOT RUN (\d+)", t).group(1)))
        c(f"device-test {nm}: no totals line is refused",
          raises(lambda t=t, mode=mode: L.parse_device_test(re.sub(r"(?m)^\d+ checks, \d+ failed$", "", t), 0, mode)))
        c(f"device-test {nm}: a doubled totals line is refused",
          raises(lambda t=t, mode=mode: L.parse_device_test(t + "\n5 checks, 0 failed\n", 0, mode)))
        c(f"device-test {nm}: no agreement line is refused",
          raises(lambda t=t, mode=mode: L.parse_device_test(
              re.sub(r"(?m)^the device and the software backend agree.*$", "", t), 0, mode)))
        c(f"device-test {nm}: failures beside the agreement line are refused",
          raises(lambda t=t, mode=mode: L.parse_device_test(
              re.sub(r"(?m)^(\d+) checks, 0 failed$", r"\1 checks, 2 failed", t), 1, mode)))
        c(f"device-test {nm}: pass with exit status 1 is refused",
          raises(lambda t=t, mode=mode: L.parse_device_test(t, 1, mode)))
    tq = fixture("dt-q8-sw.txt")
    f = L.parse_device_test(re.sub(r"(?m)^(\d+) checks, 0 failed$", r"\1 checks, 4 failed", tq)
                            .replace("the device and the software backend agree on every case that RAN, bits and flags", ""),
                            1, "q8")
    c("device-test: a failing log (4 failed, no agreement line, exit 1) is a failure with its count",
      (not f.ok) and f.counts["failed"] == 4)
    c("device-test: the NOT-lines summary and the agreement phrase must agree about absence",
      raises(lambda: L.parse_device_test(
          tq.replace("that RAN, bits and flags", ", bits and flags"), 0, "q8")))

    # -- device-test -i: built from the printf text (a real -i needs an xclbin), checked
    ident = ("libcft build x\n"
             "device: backend xrt, 4 tiles, contract 0x00000b00, formats fp32 fp64 fp128 fp256\n"
             "image: sha256 " + "ab" * 32 + ", 51714554 bytes, VERSION 0x00000b00, CAPS 0x19faffff, CAPS2 0x001877fc\n"
             "\n25 checks, 0 failed\nthe device image's identity holds\n")
    v = L.parse_device_test(ident, 0, "i")
    c("device-test -i: identity, tiles and counts read", v.ok and v.extra["tiles"] == 4
      and v.extra["image_sha256"] == "ab" * 32 and v.counts == {"checks": 25, "failed": 0})
    c("device-test -i: no identity line is refused", raises(lambda: L.parse_device_test(
        ident.replace("image: sha256", "image: sha25"), 0, "i")))
    c("device-test -i: 0 failed without the 'identity holds' line is refused", raises(lambda: L.parse_device_test(
        ident.replace("the device image's identity holds", ""), 0, "i")))

    # -- card-segrun: the printf text, and the card's own quoted line
    sg = ("  ok    the certificates made on this card: 695 checks, 0 failed, 0 skipped\n"
          "== card-segrun: 6 checks, 0 failed\n")
    v = L.parse_card_segrun(sg, 0)
    c("card-segrun: totals and the gate's counts", v.ok and v.counts == {"checks": 6, "failed": 0}
      and v.extra["gate_checks"] == 695 and v.extra["gate_skipped"] == 0)
    v = L.parse_card_segrun("== card-segrun: 6 checks, 1 failed\n   logs kept in /tmp/x\n", 1)
    c("card-segrun: a failure is a failure, and its kept directory is read", (not v.ok) and v.extra["kept_dir"] == "/tmp/x")
    c("card-segrun: no totals line is refused", raises(lambda: L.parse_card_segrun("  ok    something\n", 0)))
    c("card-segrun: a pass with exit status 1 is refused", raises(lambda: L.parse_card_segrun(sg, 1)))

    # -- seq_check --device: a real log (the software backend), and damages
    t = fixture("seq-sw.txt")
    v = L.parse_seq_check(t, rc_of("seq-sw.txt"), "sw")
    c("seq_check real log: pass, its own program counts", v.ok and v.counts["programs"] == 741
      and v.counts["refused_by_both"] == 259, str(v.counts))
    c("seq_check: the wrong device named is refused", raises(lambda: L.parse_seq_check(t, 0, "x.xclbin")))
    c("seq_check: the software backend's verdict (--device ignored) is refused",
      raises(lambda: L.parse_seq_check(t.replace("the device (sw) and the golden model agree on every program it ran",
                                                 "libcft and the golden model agree on every program"), 0, "sw")))
    c("seq_check: no verdict line is refused",
      raises(lambda: L.parse_seq_check(re.sub(r"(?m)^the device \(sw\) and the golden.*$", "", t), 0, "sw")))
    c("seq_check: no count line is refused",
      raises(lambda: L.parse_seq_check(re.sub(r"(?m)^\d+ programs run through both.*$", "", t), 0, "sw")))
    f = L.parse_seq_check("\n5 programs run through both implementations, 1 refused by both\n3 DISAGREEMENTS\n", 1, "sw")
    c("seq_check: DISAGREEMENTS is a failure with its count", (not f.ok) and f.counts["disagreements"] == 3)
    s2 = L.parse_seq_check("SKIP  the routine corpus (the eighth): mpmath is not installed here\n" + t, 0, "sw")
    c("seq_check: an inner SKIP is counted in the record, not hidden", s2.counts.get("inner_skips") == 1)

    # -- acceptance: a real log (the software backend), the card's quoted lines, damages
    t = fixture("acc-sw.txt")
    v = L.parse_acceptance(t, rc_of("acc-sw.txt"), device="sw")
    c("acceptance real log: pass, its own counts", v.ok and v.counts["entries"] == 1 and v.counts["checks"] == 16
      and v.counts["failed"] == 0, str(v.counts))
    t8 = fixture("acc-rev8-sw.txt")
    v = L.parse_acceptance(t8, rc_of("acc-rev8-sw.txt"), device="sw", rev8=True, target="u50-rev8-quad")
    c("acceptance rev8 real log (the software backend, --target u50-rev8-quad): pass, its own counts",
      v.ok and v.counts["entries"] == 1 and v.counts["checks"] == 27 and v.counts["reported_seconds"] == 87, str(v.counts))
    c("acceptance rev8: the rev7 set's parser refuses the rev8 log", raises(lambda: L.parse_acceptance(t8, 0, device="sw")))
    q = "acceptance rev8: 9 of 9 PASS on ~/cardday-rev8q/cft_hw_quad.xclbin as u50-rev8-quad (set); 115 checks ok, 0 failed, 353 s\n"
    v = L.parse_acceptance(q, 0, device="~/cardday-rev8q/cft_hw_quad.xclbin", rev8=True, target="u50-rev8-quad")
    c("acceptance rev8: docs/VALIDATION.md's card line (rev8q), read", v.ok and v.counts["entries"] == 9
      and v.counts["checks"] == 115 and v.counts["reported_seconds"] == 353)
    q2 = "acceptance: 20 of 20 PASS on ~/cardday-rev8a/cft_hw_single.xclbin (set); 174 checks ok, 0 failed, 371 s\n"
    v = L.parse_acceptance(q2, 0, device="~/cardday-rev8a/cft_hw_single.xclbin")
    c("acceptance: docs/VALIDATION.md's card line (rev8a, 20 of 20, 174 checks), read",
      v.ok and v.counts["entries"] == 20 and v.counts["checks"] == 174)
    c("acceptance: the other set's line is refused", raises(lambda: L.parse_acceptance(q, 0, device="~/cardday-rev8q/cft_hw_quad.xclbin")))
    c("acceptance: the wrong target is refused",
      raises(lambda: L.parse_acceptance(q, 0, device="~/cardday-rev8q/cft_hw_quad.xclbin", rev8=True, target="u50-rev8-deep")))
    c("acceptance: the wrong device is refused", raises(lambda: L.parse_acceptance(q2, 0, device="other.xclbin")))
    f = L.parse_acceptance(q2.replace("20 of 20", "19 of 20").replace("0 failed", "3 failed"), 1, device="~/cardday-rev8a/cft_hw_single.xclbin")
    c("acceptance: 19 of 20 with 3 failed is a failure", (not f.ok) and f.counts["failed"] == 3)
    c("acceptance: no verdict line is refused", raises(lambda: L.parse_acceptance("== verdicts\nPASS x\n", 0, device="sw")))

    # -- the soaks: real logs, the sabotage controls' failing logs, damages
    for nm, op, vm, art, exp in (("soak-sqrt32.txt", "sqrt32", "rne", None, 1048576),
                                 ("soak-div32.txt", "div32", "rne", None, None),
                                 ("c5-nextup32.txt", "nextup32", "-", None, 1048576 + 8),
                                 ("c5-rint32.txt", "rint32", "rne", None, 262144),
                                 ("c5-conv32to64.txt", "conv32to64", "rne", None, None)):
        t = fixture(nm)
        v = L.parse_soak(t, rc_of(nm), op, vm, art, exp)
        c(f"soak {nm}: pass, the log's own cases", v.ok and v.counts["value_mismatches"] == 0, str(v.counts))
        c(f"soak {nm}: no verdict line is refused", raises(lambda t=t, op=op, vm=vm, exp=exp: L.parse_soak(
            re.sub(r"(?m)^\S+ \S+: \d+ cases.*$", "", t), 0, op, vm, None, exp)))
        c(f"soak {nm}: another job's verdict (wrong op) is refused",
          raises(lambda t=t, vm=vm, exp=exp: L.parse_soak(t, 0, "nosuchop", vm, None, exp)))
        if exp is not None:
            c(f"soak {nm}: a slice whose case count is not the expected one is refused",
              raises(lambda t=t, op=op, vm=vm, exp=exp: L.parse_soak(t, 0, op, vm, None, exp + 1)))
        dev = t.replace("soaking the software backend", "soaking the DEVICE backend: /box/img.xclbin")
        c(f"soak {nm}: the DEVICE line (the source's format) is read and held to the image",
          L.parse_soak(dev, 0, op, vm, "/box/img.xclbin", exp).ok)
        c(f"soak {nm}: the software backend's line, for a job told to soak a card, is refused",
          raises(lambda t=t, op=op, vm=vm, exp=exp: L.parse_soak(t, 0, op, vm, "/box/img.xclbin", exp)))
        c(f"soak {nm}: a card soak that names another image is refused",
          raises(lambda dev=dev, op=op, vm=vm, exp=exp: L.parse_soak(dev, 0, op, vm, "/box/other.xclbin", exp)))
    c("soak: a random job with 0 cases is refused (no zero-case 'pass')",
      raises(lambda: L.parse_soak("soaking the software backend\ndiv32 rne: 0 cases, 0 value mismatches, 0 flag mismatches\n",
                                  0, "div32", "rne", None, None)))
    c("soak: 'library call failed' is refused as a verdict (the device did not answer)",
      raises(lambda: L.parse_soak("soaking the DEVICE backend: /a.xclbin\n  library call failed\n"
                                  "sqrt32 rne: 4096 cases, 0 value mismatches, 0 flag mismatches\n",
                                  1, "sqrt32", "rne", "/a.xclbin", 1 << 20)))
    c("soak: ... and the driver classifies that log as the card not answering",
      L.classify_infra("soaking the DEVICE backend: /a.xclbin\n  library call failed\n") == "no_device")
    for nm, op, vm, exp, ncase, vmis, fmis in (("soak-sqrt32-sab.txt", "sqrt32", "rne", 65536, 65536, 65536, 0),
                                               ("c5-rint32-sab.txt", "rint32", "rne", 65536, 65536, 32, 0)):
        t = fixture(nm)
        v = L.parse_soak(t, rc_of(nm), op, vm, None, exp)
        c(f"soak {nm}: the sabotage control's real failing log is a failure with its counts and operands",
          (not v.ok) and v.counts["cases"] == ncase and v.counts["value_mismatches"] == vmis
          and v.counts["flag_mismatches"] == fmis and len(v.extra["disagreements"]) >= 3
          and all(re.search(r"a=0x[0-9a-f]+", d) for d in v.extra["disagreements"]), str(v.counts))
        c(f"soak {nm}: a failing log with exit status 0 is refused", raises(lambda t=t, op=op, vm=vm, exp=exp:
                                                                         L.parse_soak(t, 0, op, vm, None, exp)))

    parsers_exhaustive(c, index, rc_of)

    # -- cft-selftest and cft-resident: the source's text
    c("cft-selftest: '1224915 cases checked'", L.parse_selftest("1224915 cases checked\n", 0).counts == {"cases": 1224915})
    c("cft-selftest: CONFORMANCE FAILED is a failure", not L.parse_selftest("CONFORMANCE FAILED: x\n", 1).ok)
    c("cft-selftest: 0 cases is refused", raises(lambda: L.parse_selftest("0 cases checked\n", 0)))
    c("cft-selftest: silence is refused", raises(lambda: L.parse_selftest("", 0)))
    ok = "every row: status clean, the same bytes on every unit, on repeat, and in software\n"
    c("cft-resident: pass", L.parse_resident(ok, 0).ok)
    c("cft-resident: '2 row(s) FAILED a check' is a failure", L.parse_resident("2 row(s) FAILED a check\n", 1).counts == {"failed": 2})
    c("cft-resident: silence is refused", raises(lambda: L.parse_resident("", 0)))

    # -- the parsers' wording is in the tools' own sources
    for path, frags in (
            ("host/tests/api_test.c", ["api-test: all contract checks passed\\n", "api-test: %d FAILED\\n"]),
            ("host/tests/device_test.c", ["\\n%d checks, %d failed\\n", "the device image's identity holds\\n",
                                          "the device and the software backend agree on every case that RAN, bits and flags\\n",
                                          "not on this device, each named above: NOT COMPARED %d format%s, %d buffers leg%s, "
                                          "%d opcode%s and %d other leg%s; NOT TESTED %d; NOT RUN %d\\n",
                                          "image: sha256 %s, %llu bytes, VERSION 0x%08x, CAPS 0x%08x",
                                          "device: backend %s, %u tile%s, contract 0x%08x, formats"]),
            ("hw/card-segrun.sh", ['== card-segrun: $checks checks, $failed failed',
                                   "the certificates made on this card: "]),
            ("host/tests/seq_check.py", ["programs run through both implementations, ",
                                         "agree on every program it ran: deposits, counts, flags and status, and every lane byte where asked; "
                                         "it refused by name every program needing a bit it does not publish"]),
            ("programs/acceptance.py", ["checks ok, {T.bad} failed, ", "'made' if args.write else 'PASS'"]),
            ("host/tools/divsqrt_soak.c", ["%s %s: %llu cases, %llu value mismatches, %llu flag mismatches\\n",
                                           "soaking the %s backend%s%s\\n", "  library call failed\\n"]),
            ("host/tools/clause5_soak.c", ["%s %s: %llu cases, %llu value mismatches, %llu flag mismatches\\n",
                                           "soaking the %s backend%s%s\\n", "  library call failed in %s\\n"]),
            ("host/tools/cft_selftest.c", ["cases checked\\n"]),
            ("host/tools/cft_resident.cpp", ["every row: status clean, the same bytes on every unit, on repeat, and in software",
                                             "row(s) FAILED a check"])):
        missing = source_has(path, *frags)
        c(f"{path}: every wording a parser reads is in the source", not missing, f"not found: {missing}")
    return out


SOAK_EXH_LINE = re.compile(r"^(\S+) (\S+): (\d+) cases, (\d+) value mismatches, (\d+) flag mismatches, "
                           r"(\d+) encodings, (\d+) skipped$", re.M)


def c_array_len(src_text: str, decl: str) -> int:
    """Entries of the C array whose declaration starts with `decl`: the numbers between its braces."""
    i = src_text.index(decl)
    body = src_text[src_text.index("{", i) + 1:src_text.index("}", i)]
    body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    return len([x for x in body.replace("\n", " ").split(",") if x.strip()])


def parse_ok(fn):
    """(Verdict, '') or (None, the VerdictError's text): a check about a log that SHOULD parse must go red when the parser
    refuses it, not crash the whole group."""
    try:
        return fn(), ""
    except L.VerdictError as e:
        return None, str(e)


def parsers_exhaustive(c, index: dict, rc_of) -> None:
    """The clause-5 soak's exhaustive conversion and scaleB modes (the -all and -wide jobs; parcel EX) on
    REAL logs of the software backend. Their verdict line says what they covered, ", E encodings, S
    skipped", and a slice is held to it exactly: E the slice's encodings, and cases + S the checks an
    encoding takes times E. Every refusal below is shown on a real log with one thing changed."""
    items = {it.name: it for it in L.sweep_items()}
    standin = os.path.join(HERE, "card_stress_standin.py")
    good = (("c5x-conv32to64-all.txt", "conv32to64-all"), ("c5x-cvtto32-all.txt", "cvtto32-all-rup"),
            ("c5x-cvtto32-all-nan.txt", "cvtto32-all-rne"), ("c5x-cvtfrom32-all.txt", "cvtfrom32-all-rup"),
            ("c5x-cvtfrom64-all.txt", "cvtfrom64-all-rtz"), ("c5x-scaleb32-all.txt", "scaleb32-all-rdn"),
            ("c5x-scaleb32-wide.txt", "scaleb32-wide-rup"))
    for nm, iname in good:
        it = items[iname]
        op, lo, hi, mode = fixture_job(index, nm)
        t = fixture(nm)
        m = SOAK_EXH_LINE.search(t)
        c(f"exhaustive {nm}: the real verdict line carries the encodings and skipped clause", m is not None)
        if m is None:
            continue
        cases, enc, skp = int(m.group(3)), int(m.group(6)), int(m.group(7))
        exp, cover = it.expected_cases(lo, hi), it.cover_spec(lo, hi)
        c(f"exhaustive {nm}: made by the command line of {iname} (its job word and mode word)",
          (op, mode) == (it.op, it.mode) and m.group(1) == it.op and m.group(2) == it.verdict_mode)
        v, why = parse_ok(lambda: L.parse_soak(t, rc_of(nm), it.op, it.verdict_mode, None, exp, cover))
        c(f"exhaustive {nm}: pass, with the log's own cases, encodings and skipped",
          v is not None and v.ok and v.counts == {"cases": cases, "value_mismatches": 0, "flag_mismatches": 0,
                                                  "encodings": enc, "skipped": skp}, why or str(v.counts))
        c(f"exhaustive {nm}: the encodings are the slice's {hi - lo}, and cases + skipped are "
          f"{it.per_encoding} for each", enc == hi - lo and cases + skp == it.per_encoding * (hi - lo),
          f"{cases} + {skp} vs {it.per_encoding} x {hi - lo}")
        if it.exact:
            c(f"exhaustive {nm}: the catalog's expected_cases is the real tool's count, and nothing was skipped",
              exp == cases and skp == 0, f"{exp} vs {cases}, skipped {skp}")
        else:
            c(f"exhaustive {nm}: cases are not a function of the slice (expected_cases is None): coverage is "
              f"the encodings alone plus the identity", exp is None and cover is not None)
        for what, tweak in (("longer by one encoding", dict(cover, encodings=hi - lo + 1)),
                            ("shorter by one encoding", dict(cover, encodings=hi - lo - 1)),
                            ("with one more check an encoding", dict(cover, per_encoding=it.per_encoding + 1)),
                            ("with one fewer check an encoding", dict(cover, per_encoding=it.per_encoding - 1))):
            c(f"exhaustive {nm}: a slice {what} than the log is refused",
              raises(lambda tweak=tweak: L.parse_soak(t, 0, it.op, it.verdict_mode, None, exp, tweak)))
        if it.exact:
            c(f"exhaustive {nm}: a count of cases one more than the real one is refused",
              raises(lambda: L.parse_soak(t, 0, it.op, it.verdict_mode, None, exp + 1, cover)))
        line = m.group(0)
        for what, bad in (("its encodings clause removed", line.replace(f", {enc} encodings, {skp} skipped", "")),
                          ("one encoding fewer printed", line.replace(f", {enc} encodings,", f", {enc - 1} encodings,")),
                          ("one case more printed", line.replace(f": {cases} cases,", f": {cases + 1} cases,")),
                          ("one skipped pair more printed", line.replace(f", {skp} skipped", f", {skp + 1} skipped"))):
            c(f"exhaustive {nm}: the log with {what} is refused",
              raises(lambda bad=bad: L.parse_soak(t.replace(line, bad), 0, it.op, it.verdict_mode, None, exp, cover)))
        c(f"exhaustive {nm}: no verdict line is refused", raises(lambda: L.parse_soak(
            t.replace(line, ""), 0, it.op, it.verdict_mode, None, exp, cover)))
        c(f"exhaustive {nm}: a doubled verdict line is refused", raises(lambda: L.parse_soak(
            t + line + "\n", 0, it.op, it.verdict_mode, None, exp, cover)))
        c(f"exhaustive {nm}: another job's verdict (wrong op) is refused", raises(lambda: L.parse_soak(
            t, 0, "nosuchop", it.verdict_mode, None, exp, cover)))
        dev = t.replace("soaking the software backend", "soaking the DEVICE backend: /box/img.xclbin")
        pv, why = parse_ok(lambda: L.parse_soak(dev, 0, it.op, it.verdict_mode, "/box/img.xclbin", exp, cover))
        c(f"exhaustive {nm}: the DEVICE line is read and held to the image; the software line, for a card job, is refused",
          pv is not None and pv.ok
          and raises(lambda: L.parse_soak(t, 0, it.op, it.verdict_mode, "/box/img.xclbin", exp, cover))
          and raises(lambda: L.parse_soak(dev, 0, it.op, it.verdict_mode, "/box/other.xclbin", exp, cover)), why)
        # the stand-in must print what the real tool prints for the same slice
        argv = [sys.executable, standin, "soak", "--", "host/clause5-soak", op, str(lo), str(hi)] + ([mode] if mode else [])
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        sm = SOAK_EXH_LINE.search(p.stdout)
        c(f"exhaustive {nm}: the dry-run stand-in prints the real tool's line for this slice "
          f"({'whole' if it.exact else 'the encodings, and cases + skipped'})",
          sm is not None and sm.group(1, 2, 4, 5, 6) == m.group(1, 2, 4, 5, 6)
          and (sm.group(0) == m.group(0) if it.exact else int(sm.group(3)) + int(sm.group(7)) == cases + skp),
          (sm.group(0) if sm else p.stdout[-200:]) + " | " + m.group(0))
    t = fixture("c5x-cvtto32-all-nan.txt")
    v, why = parse_ok(lambda: L.parse_soak(t, 0, "cvtto32-all", "rne", None, None,
                                           items["cvtto32-all-rne"].cover_spec(0x7FC00000, 0x7FC01000)))
    c("exhaustive cvtto32-all: a slice that compared nothing because every pair was skipped (all NaN) is a pass "
      "with 0 cases, not 'the tool ran nothing'", v is not None and v.ok and v.counts["cases"] == 0 and v.counts["skipped"] == 4 * 4096
      and raises(lambda: L.parse_soak(t, 0, "cvtto32-all", "rne", None, None,
                                      dict(items["cvtto32-all-rne"].cover_spec(0x7FC00000, 0x7FC01000), encodings=4095))), why)
    for nm, iname in (("c5x-conv32to64-all-sab.txt", "conv32to64-all"), ("c5x-cvtto32-all-sab.txt", "cvtto32-all-rne"),
                      ("c5x-cvtfrom32-all-sab.txt", "cvtfrom32-all-rne"), ("c5x-cvtfrom64-all-sab.txt", "cvtfrom64-all-rne"),
                      ("c5x-scaleb32-all-sab.txt", "scaleb32-all-rne"), ("c5x-scaleb32-wide-sab.txt", "scaleb32-wide-rne")):
        it = items[iname]
        op, lo, hi, mode = fixture_job(index, nm)
        t = fixture(nm)
        m = SOAK_EXH_LINE.search(t)
        exp, cover = it.expected_cases(lo, hi), it.cover_spec(lo, hi)
        v, why = parse_ok(lambda: L.parse_soak(t, rc_of(nm), it.op, it.verdict_mode, None, exp, cover))
        c(f"exhaustive {nm}: the sabotage control's real failing log is a failure with its counts, its slice's "
          f"encodings and operands", v is not None and (not v.ok) and v.counts["value_mismatches"] == int(m.group(4)) > 0
          and v.counts["encodings"] == hi - lo and len(v.extra["disagreements"]) >= 3
          and all(re.search(r"a=0x[0-9a-f]+", d) for d in v.extra["disagreements"]), why or str(v.counts))
        c(f"exhaustive {nm}: a failing log with exit status 0 is refused",
          raises(lambda: L.parse_soak(t, 0, it.op, it.verdict_mode, None, exp, cover)))
        c(f"exhaustive {nm}: a failing log whose slice ran one encoding short is refused, not recorded as a failure",
          raises(lambda: L.parse_soak(t, 1, it.op, it.verdict_mode, None, exp, dict(cover, encodings=hi - lo + 1))))
    c("exhaustive: a probe-degraded job (the directed modes not honoured: 0 cases, 0 encodings) is refused for any slice",
      raises(lambda: L.parse_soak("soaking the software backend\nscalbn probe: directed-mode values NOT honoured; this job is "
                                  "covered by rne + the model matrix\nscaleb32-all rtz: 0 cases, 0 value mismatches, 0 flag "
                                  "mismatches, 0 encodings, 0 skipped\n", 0, "scaleb32-all", "rtz", None,
                                  items["scaleb32-all-rtz"].expected_cases(0, 1 << 20),
                                  items["scaleb32-all-rtz"].cover_spec(0, 1 << 20))))
    c("exhaustive: the older tool's line (no clause) is refused for a job that must say what it covered, and is still read "
      "for the jobs that do not", raises(lambda: L.parse_soak(
          "soaking the software backend\nscaleb32-all rdn: 4456448 cases, 0 value mismatches, 0 flag mismatches\n", 0,
          "scaleb32-all", "rdn", None, items["scaleb32-all-rdn"].expected_cases(0, 1 << 18),
          items["scaleb32-all-rdn"].cover_spec(0, 1 << 18)))
      and (parse_ok(lambda: L.parse_soak(fixture("c5-rint32.txt"), 0, "rint32", "rne", None, 262144))[0] or L.Verdict(False, {})).ok)
    # the catalog's per-encoding counts are the tool's own constants (read from its source)
    with open(os.path.join(ROOT, "host", "tools", "clause5_soak.c"), "r", encoding="utf-8") as fh:
        src = fh.read()
    n17 = c_array_len(src, "static const int64_t SCALEB_N32[]")
    lo_e = int(re.search(r"#define WIDE_LO \((-?\d+)\)", src).group(1))
    hi_e = int(re.search(r"#define WIDE_HI (\d+)", src).group(1))
    nb = c_array_len(src, "static const int64_t BEYOND[]")
    c("exhaustive: PER_ENCODING's scaleb counts are the C source's lists: 17 directed exponents, the range "
      f"{lo_e}..{hi_e} and its {nb} witnesses", L.PER_ENCODING["scaleb32-all"] == n17 == 17
      and L.PER_ENCODING["scaleb32-wide"] == (hi_e - lo_e + 1) + nb == 568 and (lo_e, hi_e) == (-278, 277))
    import importlib
    st_mod = importlib.import_module("card_stress_standin")       # HERE is on sys.path
    c("exhaustive: the stand-in's per-encoding table is the library's", st_mod.EXH_PER == L.PER_ENCODING)


# ---------------------------------------------------------------------------------------
# a Driver, read but not run: the legs' command lines
# ---------------------------------------------------------------------------------------

def script_job_lines(env_vars: dict):
    """The job lines hw/run-c5-soak.sh would run: its job-list block, lifted out of the script and run by bash
    with the given variables (as the script sets them), printing one tuple a line: (name, op, a, b, mode or
    None). None when there is no bash."""
    bash = shutil.which("bash")
    if not bash:
        return None
    with open(os.path.join(ROOT, "hw", "run-c5-soak.sh"), "r", encoding="utf-8") as fh:
        text = fh.read()
    a = text.index("\n{\n", text.index("# ---- job list")) + 1
    b = text.index('} > "$OUT/joblist"', a)
    pre = "set -euo pipefail\n" + "".join(f'{k}="{v}"\n' for k, v in env_vars.items())
    p = subprocess.run([bash, "-c", pre + text[a:b + 1]], capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        raise SystemExit(f"the script's job-list block did not run: {p.stderr[-300:]}")
    rows = []
    for ln in p.stdout.splitlines():
        w = ln.split()
        rows.append((w[0], w[1], int(w[2]), int(w[3]), w[4] if len(w) > 4 else None))
    return rows


def catalog_checks(c, mod, d, q) -> None:
    """The driver's catalog of the soaks' campaigns, and the exhaustive conversion and scaleB items parcel EX
    added to it: their order, their per-encoding counts, their command lines, which of them reach the tile, and
    that the campaign script's own job lines are the catalog's, item for item."""
    L = mod.L                    # the lib the driver under test imported (a plant's copy has its own)
    items = L.sweep_items()
    by_name = {it.name: it for it in items}
    new = (["conv32to64-all"] + [f"cvtto32-all-{m}" for m in L.MODES5]
           + [f"cvtfrom32-all-{m}" for m in L.MODES4] + [f"cvtfrom64-all-{m}" for m in L.MODES4]
           + [f"scaleb32-all-{m}" for m in L.MODES4] + [f"scaleb32-wide-{m}" for m in L.MODES4])
    names = [it.name for it in items]
    i0 = names.index("class32") + 1
    c("catalog: the 22 exhaustive conversion and scaleB items follow class32, in the script's order",
      names[i0:i0 + 22] == new, str(names[i0:i0 + 22]))
    camp = items[:90]                 # the scripts' campaign; the coverage wave's 35 index-based items are appended after it
    exh = [it for it in camp if it.kind == "exhaustive"]
    c("catalog: the scripts' campaign is the first 90 items - 36 exhaustive (the 14 of the last run and the 22 new) and 54 random, "
      "none gone - and the coverage wave's 35 exhaustive hard-case and class-level items follow it",
      len(items) == 125 and len(exh) == 36 and len(camp) - len(exh) == 54 and all(it.kind == "random" for it in items[i0 + 22:90])
      and all(it.kind == "exhaustive" and it.level in ("hard", "class") for it in items[90:]),
      f"{len(exh)} exhaustive of the first {len(camp)}, {len(items)} in all")
    c("catalog: the new items have per-encoding counts 1, 4, 2, 2, 17, 568; only cvtto32-all has no fixed case count",
      [(by_name[n].per_encoding, by_name[n].exact) for n in ("conv32to64-all", "cvtto32-all-rne", "cvtfrom32-all-rup",
                                                              "cvtfrom64-all-rdn", "scaleb32-all-rtz", "scaleb32-wide-rne")]
      == [(1, True), (4, False), (2, True), (2, True), (17, True), (568, True)])
    c("catalog: only the new items say what they covered (the 14 older exhaustive items and every random one do not)",
      sorted(it.name for it in camp if it.per_encoding is not None and it.name not in new) == []
      and all(by_name[n].per_encoding is not None for n in new))
    c("catalog: a probe that allows rne alone leaves the new cvtfrom and scaleB items rne alone and cvtto32-all its five",
      [it.name for it in L.sweep_items(("rne",), ("rne",)) if it.name in new]
      == ["conv32to64-all"] + [f"cvtto32-all-{m}" for m in L.MODES5] + ["cvtfrom32-all-rne", "cvtfrom64-all-rne",
                                                                          "scaleb32-all-rne", "scaleb32-wide-rne"])
    # which items reach the tile: the library's own classification, read from its source
    cft_h = open(os.path.join(ROOT, "host", "include", "cft.h"), "r", encoding="utf-8", errors="replace").read()
    c5_c = open(os.path.join(ROOT, "host", "src", "clause5.c"), "r", encoding="utf-8", errors="replace").read()
    flat = re.sub(r"\s+", " ", re.sub(r"^\s*\*", " ", cft_h, flags=re.M))
    c("reach: the library's own classification says what it says: COMPOSED (cft_rint, cft_scaleb, cft_cmp_sig) and "
      "HOST (everything else), and that cft_div and cft_sqrt are composed", "COMPOSED (cft_rint, cft_scaleb, cft_cmp_sig)" in flat
      and "HOST (everything else)" in flat and "the composed operations (cft_div, cft_sqrt, cft_rint, cft_scaleb" in flat)
    heads = {"rint": "roundToIntegral: composed", "scaleb": "scaleB: composed", "conv": "format conversion: host",
             "cvt": "integer conversions: host", "logb": "logB: host", "next": "nextUp / nextDown: host",
             "class": "classification: host", "rem": "remainder: host"}
    c("reach: host/src/clause5.c's section headings are the ones this classification was read from",
      all(f"/* ---- {h}" in c5_c for h in heads.values()))
    fam = {"sqrt": L.TILE, "div": L.TILE, "rint": L.TILE, "scaleb": L.TILE, "conv": L.HOST, "cvt": L.HOST,
           "logb": L.HOST, "next": L.HOST, "class": L.HOST, "rem": L.HOST}
    bad = [(it.name, it.reach) for it in items
           if it.reach != fam[re.match(r"(sqrt|div|rint|scaleb|conv|cvt|logb|next|class|rem)", it.op).group(1)]]
    c("reach: every item is marked as its operation's family is (sqrt, div, rint, scaleb: tile; conversions, "
      "next, logb, class, rem: host)", not bad, str(bad[:4]))
    c("reach: the table has no operation the catalog does not use; of the scripts' 90 items 43 reach the tile and 47 do not, and "
      "of the coverage wave's 35, 22 do (13 hard-case, 9 class-level: rint64-class and scaleb64-class) and 13 do not",
      set(L.OP_REACH) == {it.op for it in items} and sum(it.reach == L.TILE for it in camp) == 43
      and sum(it.reach == L.HOST for it in camp) == 47
      and sum(it.reach == L.TILE for it in items[90:]) == 22 and sum(it.reach == L.HOST for it in items[90:]) == 13
      and sum(it.reach == L.TILE for it in items) == 65,
      f"{sorted(set(L.OP_REACH) ^ {it.op for it in items})}")
    c("reach: of the 54 random items 25 reach the tile (div32, div64, sqrt64 x4 each; rint64 x5; scaleb32, scaleb64 x4 "
      "each) and 29 are host; of the 36 exhaustive items of the scripts' campaign 18 and 18",
      [(k, r, sum(it.kind == k and it.reach == r for it in camp))
       for k in ("random", "exhaustive") for r in (L.TILE, L.HOST)]
      == [("random", "tile", 25), ("random", "host", 29), ("exhaustive", "tile", 18), ("exhaustive", "host", 18)]
      and sorted({it.op for it in items if it.kind == "random" and it.reach == L.TILE})
      == ["div32", "div64", "rint64", "scaleb32", "scaleb64", "sqrt64"]
      and "rem32" in {it.op for it in items if it.reach == L.HOST} and "rem64" in {it.op for it in items if it.reach == L.HOST})
    c5_head = c5_c[:c5_c.index("#include")]
    c("reach: cft_rem is HOST by the header of host/src/clause5.c ('HOST - cft_convert, the integer conversions, cft_logb, "
      "cft_next_*, cft_class, cft_total_order*, cft_rem') and by its code (no cft_run in its section)",
      re.search(r"HOST - cft_convert, the integer conversions, cft_logb, cft_next_\*,\s*\*\s*cft_class, cft_total_order\*, cft_rem\.", c5_head) is not None
      and "cft_run(" not in c5_c[c5_c.index("/* ---- remainder: host"):c5_c.index("The magnitude forms of minimum and maximum")])
    # a wave job for a new item: its command line, what the verdict must cover, what the record says
    d.items = items
    d.rate = {}
    # a HOST item is planned for the pool (the cpu pseudo-image, reach host), never for the card; a TILE item for the card
    H = L.HOST
    wave = d.plan_wave(d.cpu, 3600, 1, ["cvtto32-all-rup"], H)
    j = wave[0]
    b = d.soak_binary(j["item"])
    c("a wave job for cvtto32-all-rup: clause5-soak cvtto32-all <lo> <hi> rup, over the probe size from 0",
      j["argv"] == [b, "cvtto32-all", "0", str(j["units"]), "rup"] and j["units"] == d.a.probe_cases, str(j["argv"]))
    c("... it must cover its slice's encodings at 4 checks an encoding, with no fixed case count, and its record says "
      "reach host", j["cover"] == {"encodings": j["units"], "per_encoding": 4} and j["expected"] is None
      and j["sweep"]["reach"] == "host", str((j["cover"], j["expected"], j["sweep"])))
    j = d.plan_wave(d.cpu, 3600, 1, ["conv32to64-all"], H)[0]
    c("a wave job for conv32to64-all: no mode word, exactly one case an encoding, record reach host",
      j["argv"] == [b, "conv32to64-all", "0", str(j["units"])] and j["expected"] == j["units"]
      and j["cover"] == {"encodings": j["units"], "per_encoding": 1} and j["sweep"]["reach"] == "host", str(j["argv"]))
    j = d.plan_wave(q, 3600, 1, ["scaleb32-wide-rdn"])[0]
    c("a wave job for scaleb32-wide-rdn: 568 checks an encoding, record reach tile",
      j["argv"][1:] == ["scaleb32-wide", "0", str(j["units"]), "rdn"] and j["expected"] == 568 * j["units"]
      and j["cover"]["per_encoding"] == 568 and j["sweep"]["reach"] == "tile")
    j = d.plan_wave(q, 3600, 1, ["rint32-rne"])[0]
    c("a wave job for an older exhaustive item is as it was (the encodings, no coverage clause) and says reach tile",
      j["expected"] == j["units"] and j["cover"] is None and j["sweep"]["reach"] == "tile")
    j = d.plan_wave(d.cpu, 3600, 1, ["nextup32"], H)[0]
    c("nextup32 still expects its 8 edge cases beyond the slice, reach host",
      j["expected"] == j["units"] + 8 and j["cover"] is None and j["sweep"]["reach"] == "host")
    j = d.plan_wave(d.cpu, 3600, 1, ["cvtfrom64-rne"], H)[0]
    c("a random item's job records its reach and has no coverage to check",
      j["cover"] is None and j["expected"] is None and j["sweep"]["reach"] == "host" and "count" in j["sweep"])
    # the campaign script's own job lines are the catalog's, item for item, in order, with its seeds and slices
    def compare_script(label, env_vars, probe_limited):
        rows = script_job_lines(env_vars)
        if rows is None:
            skip(f"catalog: {label}", "no bash on this host")
            return
        # the clause-5 items the SCRIPT runs: the hard-case and class-level items are the driver's own, appended by the coverage wave
        cat = [it for it in (L.sweep_items(("rne",), ("rne",)) if probe_limited else L.sweep_items())
               if it.tool == "clause5" and it.level not in ("hard", "class")]
        order: list = []
        for r in rows:
            if (r[1], r[4]) not in order:
                order.append((r[1], r[4]))
        c(f"catalog: {label}: the script's job lines run the catalog's clause-5 items in the catalog's order",
          order == [(it.op, it.mode) for it in cat], f"{len(order)} vs {len(cat)}; first difference "
          f"{next(((a, b2) for a, b2 in zip(order, [(it.op, it.mode) for it in cat]) if a != b2), None)}")
        okslices = okseed = True
        why = ""
        for it in cat:
            mine = [r for r in rows if (r[1], r[4]) == (it.op, it.mode)]
            if it.kind == "exhaustive":
                n = int(env_vars["WIDE_SLICES"]) if it.op == "scaleb32-wide" else int(env_vars["SLICES"])
                span = int(env_vars.get("QUICK_WIDE_SPAN" if it.op == "scaleb32-wide" else "QUICK_SPAN", 1 << 32))
                if not (len(mine) == n and mine[0][2] == 0 and mine[-1][3] == span
                        and all(mine[k][3] == mine[k + 1][2] for k in range(n - 1))
                        and len({r[3] - r[2] for r in mine}) == 1
                        and [r[0] for r in mine] == [f"{it.name}-{k}" for k in range(n)]):
                    okslices, why = False, f"{it.name}: {len(mine)} slices {mine[:1]}"
            elif len(mine) != 1 or mine[0][3] != it.base_seed or mine[0][0] != it.name:
                okseed, why = False, f"{it.name}: {mine[:1]} vs seed {it.base_seed:#x}"
        c(f"catalog: {label}: every exhaustive item's slices tile its span, and every random item has the script's seed",
          okslices and okseed, why)

    compare_script("full campaign", dict(SLICES=64, WIDE_SLICES=1024, RANDN=30000000, SCALEB_MODES="rne rtz rdn rup",
                                         CVTFROM_MODES="rne rtz rdn rup", WIDE_MODES="rne rtz rdn rup"), False)
    compare_script("QUICK campaign", dict(SLICES=4, QUICK_SPAN=1 << 24, WIDE_SLICES=4, QUICK_WIDE_SPAN=1 << 16, RANDN=2000000,
                                          SCALEB_MODES="rne rtz rdn rup", CVTFROM_MODES="rne rtz rdn rup",
                                          WIDE_MODES="rne rtz rdn rup"), False)
    compare_script("campaign with every directed probe failed (rne alone)",
                   dict(SLICES=64, WIDE_SLICES=1024, RANDN=30000000, SCALEB_MODES="rne", CVTFROM_MODES="rne",
                        WIDE_MODES="rne"), True)


def exhaustive_conversion_items(L) -> list:
    """The 22 exhaustive conversion and scaleB items parcel EX added, in the catalog's order: none of them is in --quick's
    own four (sqrt32-rne, rint32-rne, div32-rne, nextup32), which is the case that misled 2026-10-19's smoke."""
    return (["conv32to64-all"] + [f"cvtto32-all-{m}" for m in L.MODES5] + [f"cvtfrom32-all-{m}" for m in L.MODES4]
            + [f"cvtfrom64-all-{m}" for m in L.MODES4] + [f"scaleb32-all-{m}" for m in L.MODES4]
            + [f"scaleb32-wide-{m}" for m in L.MODES4])


def quick_checks(c, mod, tmp: str, imgs: dict) -> None:
    """--quick's revision-8 leg and sweep, read off a Driver without running it (parcel DR1, 2026-10-20): the routine entry the
    smoke now runs on the quad; --quick with --sweep-items, which used to plan only quick's own four items, so that every wave
    was empty whenever none was named and the log said the campaign was finished; and why a wave is empty, said by cause."""
    L = mod.L
    q, s, dp = imgs["quad"], imgs["single"], imgs["deep"]

    def drv(*extra):
        a = mod.parse_args(["--out", os.path.join(tmp, "quick"), "--quick", "--root", ROOT, "--rev8-images",
                            os.path.join(tmp, "quick-imgs"), "--disk-extra", ""] + list(extra))
        d = mod.Driver(a)
        d.items = L.sweep_items()
        return d

    d0 = drv()
    r8 = d0.leg_cmd("acceptance-rev8", q, 1)
    only = r8.argv[r8.argv.index("--only") + 1].split(",")
    c("quick: the quad's revision-8 leg is phi4_extended_fp64 and one routine entry (no compile), with --lib",
      only == ["phi4_extended_fp64", "lotkavolterra-rk4-tangent-fp64"] and "--lib" in r8.argv, str(only))
    byname = {it.name: it for it in d0.items}
    c("quick: without --sweep-items the sweep is still its own: four items on the quad, sqrt32-rne then rint32-rne on a single; "
      "all TILE items now (the fourth was nextup32, a host item, which is the pool's)",
      d0.quick_items(q, 0) == ["sqrt32-rne", "rint32-rne", "div32-rne", "rint64-rne"]
      and [d0.quick_items(s, 0), d0.quick_items(s, 1)] == [["sqrt32-rne"], ["rint32-rne"]]
      and all(byname[n].reach == L.TILE for n in d0.quick_items(q, 0)), str(d0.quick_items(q, 0)))
    c("quick: the pool's own list is host items only: a plain exhaustive one (with edge cases), one that says what it covered, "
      "and a random one", list(mod.QUICK_HOST_ITEMS) == ["nextup32", "conv32to64-all", "rem32"]
      and all(byname[n].reach == L.HOST for n in mod.QUICK_HOST_ITEMS))
    ex = exhaustive_conversion_items(L)
    c("quick: the 22 exhaustive conversion and scaleB items are 22, and not one is in quick's own four", len(ex) == 22
      and not set(ex) & {"sqrt32-rne", "rint32-rne", "div32-rne", "rint64-rne"})
    # --quick with --sweep-items: the named items, in the order named; the shuffle shows "named", not "the catalog's"
    named = ex[::-1]
    d1 = drv("--sweep-items", ",".join(named))
    forced = d1.quick_items(q, 0)
    wave = d1.plan_wave(q, 3600, 4, forced)
    c("quick with --sweep-items: the quad's wave is four jobs, one a tile, on the first four items named in the order named "
      "(none of them one of quick's own)", forced == named[:4] and [(j["tile"], j["item"].name) for j in wave]
      == [(1, named[0]), (2, named[1]), (3, named[2]), (4, named[3])], str([j["item"].name for j in wave]))
    for j in wave:
        d1.served[j["item"].name] = 1                       # as run_wave counts a slice served
    w5 = d1.plan_wave(s, 3600, 1, d1.quick_items(s, 0))
    d1.served[named[4]] = 1
    w6 = d1.plan_wave(s, 3600, 1, d1.quick_items(s, 1))
    c("quick with --sweep-items: a single image takes one item a wave, the least served first - the next two items named, "
      "not the first four again", [j["item"].name for j in w5 + w6] == named[4:6] and [j["tile"] for j in w5 + w6] == [None, None],
      str([j["item"].name for j in w5 + w6]))
    d2 = drv("--sweep-items", f"{ex[14]},{ex[14]},{ex[15]}")
    c("quick with --sweep-items: a name given twice is one item, and fewer items than tiles are fewer jobs",
      d2.quick_items(q, 0) == [ex[14], ex[15]] and len(d2.plan_wave(q, 3600, 4, d2.quick_items(q, 0))) == 2)
    d1.disabled_items = {named[0]: "x"}
    d1.intervals = {named[1]: [(0, L.EXH)]}
    c("quick with --sweep-items: an item that is disabled or covered is passed over, and the wave takes the least served "
      "of the rest (named[0..4] are served and named[0], [1] are out; of the eight TILE items named, [5] to [7] are unserved "
      "and then [2]; the host items named are the pool's, not the card's)",
      d1.quick_items(q, 0) == [named[5], named[6], named[7], named[2]], str(d1.quick_items(q, 0)))
    # a fixed list with a disabled item no longer loses the whole wave
    d3 = drv()
    d3.disabled_items = {"sqrt32-rne": "x"}
    w3 = d3.plan_wave(q, 3600, 4, d3.quick_items(q, 0))
    c("quick: one disabled item in quick's own four no longer empties the quad's wave: the other three run, on their own tiles",
      [(j["tile"], j["item"].name) for j in w3] == [(2, "rint32-rne"), (3, "div32-rne"), (4, "rint64-rne")], str(w3))
    # an empty wave says why: the campaign is finished only when it is. (ex[14..17] are scaleb32-all, TILE items; ex[0..13] are
    # host items, the pool's, which the card is not asked to run - the checks after d8)
    d4 = drv("--sweep-items", f"{ex[14]},{ex[17]}")
    d4.intervals = {ex[14]: [(0, L.EXH)], ex[17]: [(0, 1 << 31), (1 << 31, L.EXH)]}
    f4 = d4.quick_items(q, 0)
    why4, cause4 = d4.why_no_wave(f4)
    c("empty wave, every item named is covered: the campaign IS finished, and says so for the items named, with how many",
      f4 == [] and d4.plan_wave(q, 3600, 4, f4) == [] and cause4 == "finished"
      and why4 == "nothing left to run for the items named by --sweep-items: all 2 are exhaustive and covered", why4)
    d5 = drv("--sweep-items", f"{ex[14]},{ex[15]}")
    d5.disabled_items = {ex[14]: "3 slices in a row gave no readable verdict", ex[15]: "3 slices in a row gave no readable verdict"}
    f5 = d5.quick_items(q, 0)
    why5, cause5 = d5.why_no_wave(f5)
    c("empty wave, every item disabled: NOT finished, and the sentence names the cause and the items",
      d5.plan_wave(q, 3600, 4, f5) == [] and cause5 == "blocked" and "NOT finished" in why5 and "2 disabled" in why5
      and ex[14] in why5 and "nothing left to run" not in why5, why5)
    d6 = drv("--sweep-items", f"{ex[14]},{ex[15]}")
    d6.intervals = {ex[14]: [(0, L.EXH)]}
    d6.disabled_items = {ex[15]: "x"}
    why6, cause6 = d6.why_no_wave(d6.quick_items(q, 0))
    c("empty wave, one covered and one disabled: NOT finished, and both causes are named",
      cause6 == "blocked" and "1 covered" in why6 and "1 disabled" in why6, why6)
    d7 = drv("--sweep-items", ",".join(ex))
    old = ["sqrt32-rne", "rint32-rne", "div32-rne", "rint64-rne"]
    why7, cause7 = d7.why_no_wave(old)
    c("empty wave, the case of 2026-10-19: quick's own four planned with --sweep-items naming 22 others: every one is "
      "outside --sweep-items, NOT finished, and nothing is called covered",
      d7.plan_wave(q, 3600, 4, old) == [] and cause7 == "blocked" and "4 outside --sweep-items" in why7
      and "NOT finished" in why7 and "covered" not in why7 and "nothing left to run" not in why7, why7)
    d8 = drv("--sweep-items", "scaleb32-wide-rtz")
    d8.items = L.sweep_items(("rne",), ("rne",), ("rne",))
    why8, cause8 = d8.why_no_wave(d8.quick_items(q, 0))
    c("empty wave, an item named that this run's probes ruled out: it says so by name",
      cause8 == "blocked" and "not in this run's catalog" in why8 and "scaleb32-wide-rtz" in why8, why8)
    # verifier-VDR1 (b-1): "finished" is decided over the campaign, not over the wave's own list
    d9 = drv()
    d9.intervals = {"sqrt32-rne": [(0, L.EXH)]}
    f9 = d9.quick_items(s, 0)
    why9, cause9 = d9.why_no_wave(f9)
    c("empty wave, a single image whose sqrt32-rne is covered: its list plans no job while sqrt32-rtz is still to run, and "
      "the sentence says the campaign is NOT finished and what remains, not that nothing is left",
      f9 == ["sqrt32-rne"] and d9.plan_wave(s, 3600, 1, f9) == []
      and [j["item"].name for j in d9.plan_wave(s, 3600, 1, None)] == ["sqrt32-rtz"]
      and cause9 == "blocked" and "NOT finished" in why9 and "1 covered: sqrt32-rne" in why9
      and "can still run (sqrt32-rtz," in why9 and "nothing left to run" not in why9, why9)
    # ... and the smoke goes on to the single's second item when its first cannot run (881bbcb stopped at the empty wave)
    import contextlib
    import io
    d10 = drv()
    d10.intervals = {"sqrt32-rne": [(0, L.EXH)]}
    asked: list = []
    d10.guard = lambda waiting_ok: None
    d10.run_wave = lambda img, wave: asked.append([j["item"].name for j in wave]) or []
    with contextlib.redirect_stdout(io.StringIO()):
        d10.sweep_phase(s, 20.0)
    c("quick: a single image whose first item cannot run goes on to its second (rint32-rne) in the same smoke",
      asked == [["rint32-rne"]], str(asked))
    # a HOST item is the CPU pool's, not the card's: the card's wave never takes one, and the sentence for an empty wave names it so
    # (not covered, not disabled, and not "a defect in this driver")
    d11 = drv("--sweep-items", f"{ex[14]},{ex[0]}")
    d11.intervals = {ex[14]: [(0, L.EXH)]}
    why11, cause11 = d11.why_no_wave(d11.quick_items(q, 0))
    c("empty wave, a covered tile item and a host item named: the host item is called the CPU pool's - not covered, not a defect - "
      "and the campaign is NOT finished (the pool has work)", d11.quick_items(q, 0) == [] and cause11 == "blocked"
      and "1 covered" in why11 and "1 a host item the CPU pool runs, not the card" in why11 and "defect" not in why11
      and "nothing left to run" not in why11, why11)
    d12 = drv("--sweep-items", f"{ex[0]},{ex[1]}")
    c("only host items named: the card's wave is empty by design (quick_items gives none, plan_wave plans none), whatever is served",
      d12.quick_items(q, 0) == [] and d12.plan_wave(q, 3600, 4, []) == [] and d12.plan_wave(q, 3600, 4, [ex[0]]) == [])


def group_commands(src: str = HERE) -> list:
    out: list = []

    def c(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), detail))

    sys.path.insert(0, src)
    import importlib
    # a plant's copy has its own card_stress_lib: the driver module must import THAT, not the cached real one
    saved_lib = sys.modules.pop("card_stress_lib", None) if os.path.abspath(src) != os.path.abspath(HERE) else None
    mod = importlib.import_module("card_stress")
    tmp = tempfile.mkdtemp(prefix="cs-cmd-")
    try:
        a = mod.parse_args(["--out", os.path.join(tmp, "o"), "--until", "2099-01-01 00:00", "--root", ROOT,
                            "--rev8-images", os.path.join(tmp, "imgs")])
        d = mod.Driver(a)
        imgs = {}
        for n, (dflt, tiles, target, sha) in mod.IMAGES.items():
            im = mod.Image(n, f"/box/{n}.xclbin", tiles, target, sha)
            im.sha = sha
            imgs[n] = im
        q, s, dp = imgs["quad"], imgs["single"], imgs["deep"]
        x = q.path

        def argv(leg, img=q, visit=1):
            r = d.leg_cmd(leg, img, visit)
            return r if isinstance(r, mod.Skip) else r.argv

        c("api-test: host/api-test", argv("api-test")[-1].endswith(os.path.join("host", "api-test")))
        c("dt-i: run-device-test.sh IMAGE -i", argv("dt-i")[-3:] == [os.path.join(ROOT, "hw", "run-device-test.sh"), x, "-i"],
          str(argv("dt-i")))
        c("dt-q8: -q -n 8", argv("dt-q8")[-3:] == ["-q", "-n", "8"])
        c("dt-full: -n 4096", argv("dt-full")[-2:] == ["-n", "4096"])
        c("dt-r: -r", argv("dt-r")[-1] == "-r")
        c("dt-b: -b -n 4096", argv("dt-b")[-3:] == ["-b", "-n", "4096"])
        c("card-segrun: hw/card-segrun.sh IMAGE", argv("card-segrun")[-2].endswith("card-segrun.sh") and argv("card-segrun")[-1] == x)
        sq = argv("seq-check")
        c("seq-check: --trials 250 on the four formats, --device IMAGE",
          "--trials" in sq and sq[sq.index("--trials") + 1] == "250" and sq[sq.index("--formats") + 1:sq.index("--formats") + 5]
          == ["fp32", "fp64", "fp128", "fp256"] and sq[sq.index("--device") + 1] == x)
        ac = argv("acceptance")
        c("acceptance: acceptance.py --device IMAGE (the whole rev7 set)", ac[-2:] == ["--device", x] and "--only" not in ac)
        r8 = argv("acceptance-rev8")
        only = r8[r8.index("--only") + 1].split(",")
        c("acceptance-rev8 on the quad: --set rev8 --target u50-rev8-quad --images DIR",
          r8[r8.index("--set") + 1] == "rev8" and r8[r8.index("--target") + 1] == "u50-rev8-quad" and "--images" in r8)
        c("acceptance-rev8 on the quad: eight workloads and the six routine entries, the two long compiles left out",
          len(only) == 14 and "riccati_extended_fp64" not in only and "gray_scott_extended_fp64" not in only
          and all(e in only for e in mod.REV8_ROUTINE_ENTRIES), str(only))
        c("acceptance-rev8 on the quad: the routine entries make the leg name --lib, this tree's host/libcft.so (the "
          "XRT-linked one the build step checked)",
          "--lib" in r8 and r8[r8.index("--lib") + 1] == os.path.join(os.path.abspath(ROOT), "host", "libcft.so"), str(r8[-4:]))
        c("acceptance-rev8: the single has no entry, and the leg says so by name",
          isinstance(argv("acceptance-rev8", s), mod.Skip) and "u50-rev8" in argv("acceptance-rev8", s).reason)
        c("acceptance-rev8: the deep's one entry is a 40-minute compile with no cache, so it is skipped by name",
          isinstance(argv("acceptance-rev8", dp), mod.Skip) and "gray_scott_extended" in argv("acceptance-rev8", dp).reason)
        t_uncached = d.leg_cmd("acceptance-rev8", q, 1).timeout
        os.makedirs(os.path.join(tmp, "imgs"), exist_ok=True)
        for e in mod.REV8_ENTRIES["u50-rev8-quad"] + mod.REV8_ENTRIES["u50-rev8-deep"]:
            if e in mod.REV8_ROUTINE_ENTRIES:
                continue                   # a routine entry's files are committed: nothing of it is ever in the cache
            for ext in (".cftp", ".bank"):
                open(os.path.join(tmp, "imgs", e + ext), "w").close()
        r8c = d.leg_cmd("acceptance-rev8", q, 1)
        c("acceptance-rev8: with every workload cached the quad runs fifteen, riccati and the six routine entries "
          "included, and the timeout drops its compile allowance", len(r8c.argv[r8c.argv.index("--only") + 1].split(",")) == 15
          and r8c.timeout == t_uncached - mod.REV8_FIRST_COMPILE_ALLOWANCE, f"{r8c.timeout} vs {t_uncached}")
        c("acceptance-rev8: the routine entries are never 'uncached' (their image and bank are committed files): with "
          "the workloads cached the timeout is the leg's own, not the leg's plus the 4-hour compile allowance",
          r8c.timeout == float(mod.DEFAULT_TIMEOUTS["acceptance-rev8"]), str(r8c.timeout))
        r8d = d.leg_cmd("acceptance-rev8", dp, 1)
        c("acceptance-rev8: with the cache the deep runs gray_scott_extended, and names no --lib (no routine entry)",
          not isinstance(r8d, mod.Skip) and "--lib" not in r8d.argv)
        c("selftest: every third visit of an image (visit 1 runs, 2 and 3 skip, 4 runs)",
          [isinstance(d.leg_cmd("selftest", q, v), mod.Skip) for v in (1, 2, 3, 4)] == [False, True, True, False])
        c("timeouts: every leg has one, from the card's measured times with a floor",
          all(mod.DEFAULT_TIMEOUTS[leg] >= 300 for leg in mod.BATTERY))
        ok8, why8 = rev8_table_matches(mod)
        c("REV8_ENTRIES is acceptance.py's table: REV8's ten workloads then REV8_ROUTINES' six, entry for entry and target "
          "for target (read from its source), and acceptance.py has no other REV8 name this test has not been shown", ok8, why8)
        # the sweep's argv is the soak scripts' job line, one slice
        d.items = L.sweep_items()
        d.rate = {}
        wave = d.plan_wave(q, 3600, 4)
        c("a wave on the quad is four jobs, one a tile (CFT_XRT_TILES 1..4), on four different items",
          [j["tile"] for j in wave] == [1, 2, 3, 4] and len({j["item"].name for j in wave}) == 4)
        c("a wave on a single is one job, no tile pin", [j["tile"] for j in d.plan_wave(s, 3600, 1)] == [None])
        c("the first slice is the probe size, then the measured rate sizes the next",
          wave[0]["units"] == a.probe_cases)
        d.rate["sqrt32@quad"] = 2.0e5
        w2 = d.plan_wave(q, 3600, 1)
        c("a measured rate of 2e5 cases/s and a 600 s target make a slice of 2e5*600 rounded down to whole 2^20 atoms",
          w2[0]["item"].name == "sqrt32-rne" and w2[0]["units"] == (int(2.0e5 * 600) // L.ATOM) * L.ATOM, str(w2[0]["units"]))
        d.rate["sqrt32@quad"] = 2.0e6
        c("a rate high enough for more than 2^28 in the target is held at 2^28",
          d.plan_wave(q, 3600, 1)[0]["units"] == 1 << 28)
        c("near the deadline the slice is sized to the time left, not the target",
          d.plan_wave(q, 60, 1)[0]["slice_secs"] == 45.0)
        names = [it.name for it in d.items]
        c("the campaign has run-soak.sh's 5 exhaustive sqrt32 and 12 random divsqrt items first",
          names[:5] == [f"sqrt32-{m}" for m in L.MODES5] and names[5] == "div32-rne" and names[16] == "sqrt64-rup")
        catalog_checks(c, mod, d, q)
        quick_checks(c, mod, tmp, imgs)
        # the guard's matching rules, on synthetic command lines (what is a card user and what is not)
        def user(*args):
            return mod.card_user({"pid": 0, "ppid": 0, "args": list(args)})

        c("guard rules: device-test, run-device-test.sh, card-segrun.sh, card-identity.sh with an xclbin ARE card users",
          all(user(*a) for a in (("/x/device-test", "/i/q.xclbin", "-q"), ("bash", "hw/run-device-test.sh", "/i/q.xclbin", "-i"),
                                 ("bash", "hw/card-segrun.sh", "/i/q.xclbin"), ("bash", "hw/card-identity.sh", "/i/q.xclbin"))))
        c("guard rules: acceptance.py, seq_check.py and cft-segrun with --device <xclbin> ARE; with sw, sw:N or cft:// they are NOT",
          all(user(*a) for a in (("python3", "programs/acceptance.py", "--device", "/i/q.xclbin"),
                                 ("python3", "host/tests/seq_check.py", "--device", "/i/q.xclbin"),
                                 ("host/cft-segrun", "--device=/i/q.xclbin")))
          and not any(user(*a) for a in (("python3", "programs/acceptance.py", "--device", "sw"),
                                         ("python3", "host/tests/seq_check.py", "--device", "sw:2048"),
                                         ("host/cft-segrun", "--device", "cft://h:1"))))
        c("guard rules: hw/verify-image.sh (xclbinutil, no card; the gate's images stage runs it), cp, sha256sum, an editor and "
          "xclbinutil are NOT card users even with an xclbin argument",
          not any(user(*a) for a in (("bash", "hw/verify-image.sh", "/i/q.xclbin"), ("cp", "/i/q.xclbin", "/j/"),
                                     ("sha256sum", "/i/q.xclbin"), ("vim", "/i/q.xclbin"), ("xclbinutil", "-i", "/i/q.xclbin", "--info"))))
        c("guard rules: xbutil/xrt-smi examine (what the driver's telemetry runs) is NOT a card user; program, reset and validate ARE",
          not user("xbutil", "examine", "-d", "0000:02:00.1", "-r", "thermal") and not user("xrt-smi", "examine", "-d", "x")
          and all(user("xbutil", sub, "-d", "0000:02:00.1") for sub in ("program", "reset", "validate")))
        c("guard rules: a verify/run.sh run is recognised as one to allow beside it",
          mod.is_verify_run({"pid": 0, "ppid": 0, "args": ["bash", "verify/run.sh", "--only", "seq"]})
          and not mod.is_verify_run({"pid": 0, "ppid": 0, "args": ["bash", "hw/card-segrun.sh", "x.xclbin"]}))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        sys.path.remove(src)
        sys.modules.pop("card_stress", None)
        if saved_lib is not None:
            sys.modules["card_stress_lib"] = saved_lib
    return out


def rev8_table_matches(mod) -> tuple:
    """(ok, why): the driver's table is programs/acceptance.py's REV8 (ten workloads, a name and a target each) and then
    its REV8_ROUTINES (six routine entries, a name, a system and a target each), read from the source: every entry,
    every target and the order, with the routine names the leg treats as having no compile the same six. Parcel MA added
    REV8_ROUTINES on 2026-10-19 and this test read REV8 alone, counting its ten, so the six went by unseen; so any other
    module-level name that begins REV8 makes this red until it has been looked at and added to `known`."""
    with open(os.path.join(ROOT, "programs", "acceptance.py"), "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^REV8 = \((.*?)\)\n#", text, re.S | re.M)
    r = re.search(r"^REV8_ROUTINES = \(.*?\)\)\n", text, re.S | re.M)
    if not m or not r:
        return False, "REV8 or REV8_ROUTINES is not where this test reads it in programs/acceptance.py"
    pairs = re.findall(r'\("([a-z0-9_]+)", "(u50-rev8[a-z-]*)"\)', m.group(1))
    trips = re.findall(r'\("([a-z0-9-]+)", "([a-z0-9-]+)", "(u50-rev8[a-z-]*)"\)', r.group(0))
    table: dict = {"u50-rev8-quad": [], "u50-rev8": [], "u50-rev8-deep": []}
    for name, target in pairs:
        table[target].append(name)
    for name, _system, target in trips:
        table[target].append(name)
    known = {"REV8", "REV8_ROUTINES", "REV8_STEPS", "REV8_ORDER", "REV8_TILES"}
    other = sorted(set(re.findall(r"^(REV8\w*) = ", text, re.M)) - known)
    ok = (table == mod.REV8_ENTRIES and len(pairs) == 10 and len(trips) == 6
          and list(mod.REV8_ROUTINE_ENTRIES) == [n for n, _s, _t in trips] and not other)
    return ok, (f"REV8 has {len(pairs)} entries and REV8_ROUTINES {len(trips)}; the table differs by "
                f"{sorted({n for v in table.values() for n in v} ^ {n for v in mod.REV8_ENTRIES.values() for n in v})}; "
                f"routine names {list(mod.REV8_ROUTINE_ENTRIES) == [n for n, _s, _t in trips]}; other REV8 names {other}")


# ---------------------------------------------------------------------------------------
# the driver as a process, against the stand-ins
# ---------------------------------------------------------------------------------------

class Env:
    def __init__(self, tmp: str):
        self.tmp = tmp
        self.imgs: dict = {}
        self.shas: dict = {}
        for n in ("quad", "single", "deep"):
            d = os.path.join(tmp, "img", n)
            os.makedirs(d, exist_ok=True)
            p = os.path.join(d, f"cft_hw_{n}.xclbin")
            data = os.urandom(65536)
            with open(p, "wb") as fh:
                fh.write(data)
            sha = hashlib.sha256(data).hexdigest()
            with open(os.path.join(d, "SHA256SUMS"), "w") as fh:
                fh.write(f"{sha}  cft_hw_{n}.xclbin\n")
            self.imgs[n] = p
            self.shas[n] = sha
        self.n = 0


class Run:
    def __init__(self, out: str, proc=None):
        self.out = out
        self.proc = proc
        self.rc = None
        self.text = ""

    def finish(self, cap: float) -> "Run":
        try:
            self.text, _ = self.proc.communicate(timeout=cap)
            self.rc = self.proc.returncode
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.text, _ = self.proc.communicate()
            self.rc = "TIMEOUT"
        if self.text is None and getattr(self, "stdout_path", None):       # the driver wrote to a file, not a pipe
            with open(self.stdout_path, "r", encoding="utf-8", errors="replace") as fh:
                self.text = fh.read()
        return self

    @property
    def recs(self) -> list:
        p = os.path.join(self.out, "metrics.jsonl")
        return L.read_records(p)[0] if os.path.exists(p) else []

    def legs(self, leg=None, image=None, kind=None, status=None) -> list:
        return [r for r in self.recs if r.get("type") == "leg"
                and (leg is None or r["leg"] == leg) and (image is None or r["image"] == image)
                and (kind is None or r["kind"] == kind) and (status is None or r["status"] == status)]

    def events(self, name=None) -> list:
        return [r for r in self.recs if r.get("type") == "event" and (name is None or r["event"] == name)]

    def last(self, typ: str):
        r = [x for x in self.recs if x.get("type") == typ]
        return r[-1] if r else None


def pid_alive(pid: int) -> bool:
    if POSIX:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    p = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in p.stdout


def standin_alive(pid: int) -> bool:
    """Whether `pid` is still a card_stress_standin.py process. pid_alive alone cannot tell it from the NEXT process the OS gave
    that pid to (Windows hands a freed pid out again at once - to the very tasklist that asks, or to another session's process),
    so a hung stand-in the driver had killed could look alive: the hang check failed once in 7.5 minutes of a Git Bash run, six
    reruns of the same scenario passed, and this is the likely cause (BELIEVED). When the command line cannot be read it is ALIVE
    (verifier-VDR1, 2026-10-20, notes 2 and 3; fixed 2026-10-21): on Windows that is a PowerShell call that times out (the 60 s limit,
    on a loaded desktop: it used to raise and error the scenario instead of failing it), cannot be started, fails, or reads an empty
    command line of a pid that is still there (the code treated that as dead while this text said alive). The one empty answer that
    is dead is the pid's having exited between the first look and the query, which a second look at the pid tells."""
    if not pid_alive(pid):
        return False
    if POSIX:
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                return b"card_stress_standin" in fh.read()
        except OSError:
            return False
    try:
        q = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
                           capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, OSError):
        return True
    if q.returncode != 0:
        return True
    if not q.stdout.strip():
        return pid_alive(pid)
    return "card_stress_standin" in q.stdout


def start_driver(env: Env, name: str, args: list, scenario=None, src: str = HERE, extra_env=None,
                 base_extra=None, pre_stop: bool = False, to_file: bool = False) -> Run:
    """to_file: send the driver's output to a file instead of a pipe. A scenario that polls while a long run writes a
    lot of log would otherwise stall the driver in print() once the pipe's small buffer is full, because nothing
    reads it until the run ends."""
    env.n += 1
    out = os.path.join(env.tmp, f"{env.n:02d}-{name}")
    state = out + "-state"
    os.makedirs(state, exist_ok=True)
    if pre_stop:
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "STOP"), "w") as fh:
            fh.write("stale")
    cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", out, "--dry-run",
           "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1", "--kill-after", "2",
           "--guard-poll", "1"]
    for n, p in env.imgs.items():
        cmd += ["--image", f"{n}={p}"]
    cmd += (base_extra or []) + args
    e = dict(os.environ)
    e["CFT_STANDIN_STATE"] = state
    if scenario is not None:
        sc = os.path.join(state, "scenario.json")
        with open(sc, "w") as fh:
            json.dump(scenario, fh)
        e["CFT_STANDIN_SCENARIO"] = sc
    e.update(extra_env or {})
    if to_file:
        stdout_path = out + "-stdout.txt"
        with open(stdout_path, "w", encoding="utf-8") as sink:
            proc = subprocess.Popen(cmd, stdout=sink, stderr=subprocess.STDOUT, text=True, env=e, cwd=ROOT)
    else:
        stdout_path = None
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=e, cwd=ROOT)
    r = Run(out, proc)
    r.state = state
    r.stdout_path = stdout_path
    return r


def run_driver(env: Env, name: str, args: list, scenario=None, cap: float = 240, **kw) -> Run:
    return start_driver(env, name, args, scenario, **kw).finish(cap)


def until(seconds: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() + seconds))


def wait_for(cond, timeout: float, step: float = 0.25) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


def log_text(r: Run, rec: dict) -> str:
    p = os.path.join(r.out, rec["log"]) if rec.get("log") else None
    if not p or not os.path.exists(p):
        return ""
    if p.endswith(".gz"):
        with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    with open(p, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


# -- scenarios: each returns [(name, ok, detail)] ----------------------------------------

def scn_normal(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    # the driver is started with CFT_SOAK_ARTIFACT in ITS OWN environment (a card job sets its own over it; a host job
    # must not inherit it: the pool removes it from the child's environment)
    R = run_driver(env, "normal", ["--quick"], src=src, extra_env={"CFT_SOAK_ARTIFACT": LEAKED_ARTIFACT})
    env.normal = R
    legs = R.legs()
    cpu = [r for r in legs if r["image"] == "cpu"]
    c("normal: exit 0, every leg passed (quick is a check)", R.rc == 0, f"rc {R.rc}: {R.text[-300:]}")
    c("normal: 41 leg records: 39 passes (36 on the card's images, the 3 host slices on cpu) and the two named skips",
      len(legs) == 41 and sum(r["status"] == "pass" for r in legs) == 39 and sum(r["status"] == "skipped" for r in legs) == 2
      and len(cpu) == 3, f"{len(legs)} legs, {sorted({r['status'] for r in legs})}")
    skipped = [(r["leg"], r["image"]) for r in legs if r["status"] == "skipped"]
    c("normal: the skips are acceptance-rev8 on the single (no entry) and on the deep (a 40-minute compile uncached)",
      sorted(skipped) == [("acceptance-rev8", "deep"), ("acceptance-rev8", "single")] and all(r["reason"] for r in legs if r["status"] == "skipped"))
    cs = [r for r in R.recs if r.get("type") == "cycle_start"]
    c("normal: quick visits quad, single, deep once each, in that order", [r["image"] for r in cs] == ["quad", "single", "deep"])
    c("normal: run_start is the first record and run_end the last", R.recs[0]["type"] == "run_start" and R.recs[-1]["type"] == "run_end"
      and R.recs[-1]["reason"] == "quick_done")
    b = R.last("build")
    c("normal: the build record is ok and holds the images' hash checks",
      b is not None and b["ok"] and sum(1 for s in b["steps"] if s["name"].startswith("image ") and s["ok"]) == 3)
    rs = R.recs[0]
    c("normal: run_start carries each image's SHA-256, as hashed", all(rs["images"][n]["sha256"] == env.shas[n] for n in env.shas))
    ids = R.legs("dt-i")
    c("normal: each dt-i read the image's SHA-256 and tile count (the file's, 4/1/1)",
      len(ids) == 3 and all((r["extra"] or {}).get("image_sha256") == env.shas[r["image"]]
                            and (r["extra"] or {}).get("tiles") == (4 if r["image"] == "quad" else 1) for r in ids))
    c("normal: every card leg record has its image's hash, its times and a log", all(
        r["image_sha256"] == env.shas[r["image"]] and r["start_epoch"] <= r["end_epoch"] and (r["status"] == "skipped" or r["log"])
        for r in legs if r["image"] != "cpu"))
    c("normal: a passing leg's log is gzipped and readable", all(
        r["log_kept"] == "gz" and os.path.exists(os.path.join(R.out, r["log"])) and "standin: would run" in log_text(R, r)
        for r in legs if r["status"] == "pass"))
    sw = R.legs(kind="sweep")
    swc, swh = [r for r in sw if r["image"] != "cpu"], [r for r in sw if r["image"] == "cpu"]
    c("normal: the quad's sweep is four jobs on tiles 1 to 4; the others one job, no tile",
      sorted(r["tile"] for r in sw if r["image"] == "quad") == [1, 2, 3, 4] and all(r["tile"] is None for r in sw if r["image"] != "quad"))
    c("normal: every sweep job reports its cases (read from its verdict line) and its rate", all(
        (r["counts"] or {}).get("cases", 0) > 0 and (r["rate"] or {}).get("unit") == "cases/s" for r in sw))
    c("normal: nextup32's slice reports the 8 edge cases beyond its range, read, not assumed",
      [(r["counts"] or {}).get("cases", 0) - (r["sweep"]["hi"] - r["sweep"]["lo"]) for r in sw if r["sweep"]["item"] == "nextup32"] == [8])
    c("normal: every sweep job on the card's images soaked the DEVICE (the stand-in prints the line only when CFT_SOAK_ARTIFACT is "
      "set), and NONE of them is a host item: the card's sweep picked tile items only",
      all("soaking the DEVICE backend: " + env.imgs[r["image"]] in log_text(R, r) for r in swc)
      and {r["sweep"]["reach"] for r in swc} == {"tile"}, str(sorted({r["sweep"]["item"] for r in swc})))
    c("normal: the host pool ran quick's three host items once each, as CPU jobs: image cpu, no tile, no image hash, reach host, "
      "each recording the worker, the host and the tools' build id",
      sorted(r["sweep"]["item"] for r in swh) == ["conv32to64-all", "nextup32", "rem32"]
      and all(r["tile"] is None and r["image_sha256"] is None and r["sweep"]["reach"] == "host" and r["kind"] == "sweep"
              and set(r["sweep"]["pool"]) == {"worker", "host", "build_id"} for r in swh), str([r["sweep"] for r in swh][:1]))
    c("normal: no host job named the card although the driver's own environment did: each said 'soaking the software backend', "
      "never DEVICE, and was handed neither CFT_SOAK_ARTIFACT nor CFT_XRT_TILES (the stand-in prints what it was given)",
      len(swh) == 3 and all("soaking the software backend" in log_text(R, r) and "DEVICE" not in log_text(R, r)
                            and "standin: env CFT_SOAK_ARTIFACT=<unset> CFT_XRT_TILES=<unset>" in log_text(R, r) for r in swh),
      str([log_text(R, r)[:400] for r in swh][:1]))
    c("normal: a card job is handed its own image and its tile, over the leaked variable",
      len(swc) >= 1 and all(f"standin: env CFT_SOAK_ARTIFACT={env.imgs[r['image']]} CFT_XRT_TILES={r['tile'] or '<unset>'}" in log_text(R, r)
                            for r in swc), f"{len(swc)} card sweep jobs")
    r8 = R.legs("acceptance-rev8", "quad")
    t8 = log_text(R, r8[0]) if r8 else ""
    c("normal: the quad's revision-8 leg ran phi4_extended_fp64 and one routine entry, naming --lib (the stand-in prints "
      "the command it was given)", len(r8) == 1 and r8[0]["status"] == "pass"
      and "--only phi4_extended_fp64,lotkavolterra-rk4-tangent-fp64" in t8 and " --lib " in t8, t8[:300])
    c("normal: status.txt exists and names the legs, the card, the sweep, the host pool and the deadline",
      all(k in open(os.path.join(R.out, "status.txt")).read() for k in ("legs", "card ", "sweep ", "hostpool   3 worker(s)",
                                                                          "deadline", "FINISHED: quick_done")))
    c("normal: metrics.jsonl lines are whole JSON, one per record (read_records finds none bad)",
      L.read_records(os.path.join(R.out, "metrics.jsonl"))[1:] == (False, []))
    if POSIX:
        t = log_text(R, R.legs("dt-q8")[0])
        want_nice = min(19, os.nice(0) + 10)      # `nice -n 10` adds to the caller's niceness
        c(f"normal (POSIX): a leg runs at `nice -n 10` (this test's own niceness {os.nice(0)} + 10, at most 19: {want_nice})",
          f"standin: nice {want_nice}" in t, t[:200])
        c("normal (POSIX): a leg runs under `timeout --signal=TERM -k 2 <secs>s`",
          re.search(r"standin: parent: timeout --signal=TERM -k 2 \d+s ", t) is not None, t[:300])
    return out


def scn_fail_and_parse(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sc = [{"leg": "dt-full", "nth": [1], "do": "fail"}, {"leg": "api-test", "nth": [2], "do": "garbage"},
          {"leg": "dt-i", "image": "deep", "nth": [1], "do": "wrongsha"}]
    R = run_driver(env, "fail", ["--quick", "--legs", "api-test,dt-i,dt-full", "--no-sweep"], sc, src=src)
    f = R.legs("dt-full", "quad")[0]
    c("fail: a failing leg (the tool's own '2 failed') is status fail with its counts", f["status"] == "fail" and f["counts"]["checks"] == 10373
      and f["counts"]["failed"] == 2 and f["rc"] == 1, str(f))
    c("fail: its log is kept whole (not compressed) and holds the tool's text",
      f["log_kept"] == "whole" and f["log"].endswith(".log") and "2 failed" in log_text(R, f))
    c("fail: the run goes on after it (dt-full ran on the single and the deep, the quad's api-test..)",
      len(R.legs("dt-full")) == 3 and len(R.legs()) == 9)
    g = R.legs("api-test", "single")[0]
    c("fail: a log no parser can read is parse_error, not a pass, not a zero count",
      g["status"] == "parse_error" and g["counts"] is None and g["log_kept"] == "whole" and "expected one verdict line" in g["reason"], str(g))
    w = R.legs("dt-i", "deep")[0]
    c("fail: a dt-i that read another image's SHA-256 is a wrong answer (fail), by name",
      w["status"] == "fail" and "sha256" in w["reason"] and w["log_kept"] == "whole", str(w))
    c("fail: quick exits 1 when a leg did not pass", R.rc == 1, f"rc {R.rc}")
    return out


def scn_timeout(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    R = run_driver(env, "hang", ["--quick", "--legs", "api-test,dt-i", "--no-sweep", "--timeout", "api-test=3"],
                   [{"leg": "api-test", "nth": [1], "do": "hang"}], src=src, cap=120)
    a = R.legs("api-test", "quad")
    a0 = a[0] if a else {}
    a1 = a[1] if len(a) > 1 else {}
    c("timeout: the hung leg is status timeout, timed_out, signalled", len(a) == 2 and a0.get("status") == "timeout"
      and a0.get("timed_out") and a0.get("killed") in ("TERM", "KILL"), str([(x["status"], x["killed"]) for x in a]))
    c("timeout: it ended near its limit (3 s) plus the grace, not at the stand-in's 10^6 s", 2.5 <= a0.get("duration_s", 0) < 25, str(a0.get("duration_s")))
    c("timeout: the retry after the pause (attempt 2) ran and passed", a1.get("attempt") == 2 and a1.get("status") == "pass")
    c("timeout: a pause event and no recovery yet (the first failure only waits)", len(R.events("pause")) == 1 and not R.events("recover_start"))
    pids = [int(open(os.path.join(R.state, f)).read()) for f in os.listdir(R.state) if f.startswith("hang-")]
    c("timeout: the hung stand-in's process is gone (no stray process)", pids and not any(pid_alive(p) for p in pids), str(pids))
    c("timeout: the card-using api-test failure streak did not stop a run that then passed (exit 0 or quick's 1)", R.rc in (0, 1))
    return out


def scn_deaf(env: Env, src: str = HERE) -> list:
    out: list = []
    R = run_driver(env, "deaf", ["--quick", "--legs", "dt-i", "--no-sweep", "--timeout", "dt-i=3", "--max-card-failures", "50"],
                   [{"leg": "dt-i", "image": "quad", "nth": [1], "do": "hangdeaf"}], src=src, cap=120)
    a = R.legs("dt-i", "quad")
    pids = [int(open(os.path.join(R.state, f)).read()) for f in os.listdir(R.state) if f.startswith("hang-")]
    out.append(("deaf: a process that ignores SIGTERM is escalated to KILL after --kill-after",
                bool(a) and a[0]["status"] == "timeout" and a[0]["killed"] == "KILL" and a[0]["duration_s"] >= 4.5, str(a[:1])))
    out.append(("deaf: and it is dead afterwards", pids and not any(pid_alive(p) for p in pids), str(pids)))
    return out


def scn_nodevice(env: Env, src: str = HERE) -> list:
    """The ladder: pause and retry; the second consecutive failure opens another image and comes back."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    R = run_driver(env, "nodevice", ["--quick", "--legs", "dt-i,api-test", "--no-sweep", "--max-card-failures", "6"],
                   [{"leg": "dt-i", "nth": [1, 2], "do": "nodevice"}], src=src, cap=120)
    d = R.legs("dt-i", "quad")
    c("nodevice: the first two opens fail as no_device, attempts 1 and 2",
      [(x["attempt"], x["status"], x["kind"]) for x in d[:2]] == [(1, "no_device", "battery"), (2, "no_device", "battery")], str(d[:2]))
    c("nodevice: after the first failure it waits (pause) and retries the same leg", [e["detail"] for e in R.events("pause")][0].startswith("card not answering (consecutive failure 1)"))
    rec = [x for x in R.legs("dt-i", kind="recovery")]
    c("nodevice: after the second it opens ANOTHER image and then this one again (two recovery dt-i legs, both pass)",
      len(rec) == 2 and rec[0]["image"] != "quad" and rec[1]["image"] == "quad" and all(x["status"] == "pass" for x in rec), str([(x["image"], x["status"]) for x in rec]))
    c("nodevice: the events say so, in order", [e["event"] for e in R.events() if e["event"] in ("pause", "recover_start", "image_switch", "recover_end")]
      == ["pause", "pause", "recover_start", "image_switch", "recover_end"])
    c("nodevice: the run then went on (api-test and the other images' dt-i ran)", len(R.legs("api-test")) == 3 and len(R.legs("dt-i", "single", "battery")) == 1)
    c("nodevice: no_device is a failure for quick's exit status", R.rc == 1)
    return out


def scn_cardlost(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    R = run_driver(env, "cardlost", ["--quick", "--legs", "dt-i,api-test", "--no-sweep", "--max-card-failures", "4"],
                   [{"leg": "dt-i", "from": 1, "do": "nodevice"}], src=src, cap=120)
    c("cardlost: after N consecutive failures the driver stops with exit 3", R.rc == 3, f"rc {R.rc}: {R.text[-300:]}")
    c("cardlost: it wrote why (STOPPED.txt names the failure)", os.path.exists(os.path.join(R.out, "STOPPED.txt"))
      and "card_lost" in open(os.path.join(R.out, "STOPPED.txt")).read())
    c("cardlost: run_end says card_lost, exit 3", (R.last("run_end") or {}).get("reason") == "card_lost" and R.last("run_end")["exit"] == 3)
    c("cardlost: api-test (which needs no card) passing between the failures did not reset the count",
      len(R.legs("api-test", status="pass")) >= 1)
    c("cardlost: it did not go on to the third image", not R.legs(image="deep"))
    c("cardlost: the card is idle: no hang left, the driver's children all ended", R.proc.poll() is not None)
    return out


def scn_stopfile(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    r = start_driver(env, "stop", ["--until", until(45), "--legs", "api-test,dt-i,dt-q8,dt-full,dt-r", "--no-sweep"],
                     [{"leg": "dt-full", "nth": [1], "do": "slow:4"}], src=src)
    log = os.path.join(r.out, "driver.log")
    began = wait_for(lambda: os.path.exists(log) and "leg dt-full on quad starts" in open(log).read(), 120)
    t_touch = time.time()
    with open(os.path.join(r.out, "STOP"), "w") as fh:
        fh.write("stop")
    r.finish(90)
    c("stopfile: the driver reached dt-full (the slow leg) before the file was touched", began)
    df = r.legs("dt-full", "quad")
    c("stopfile: the leg running when STOP appeared ran to its end (a verdict, status pass, its 4 s)",
      len(df) == 1 and df[0]["status"] == "pass" and df[0]["duration_s"] >= 3.5 and df[0]["start_epoch"] < t_touch, str(df[:1]))
    c("stopfile: no leg started after STOP was touched", all(x["start_epoch"] < t_touch for x in r.legs()), str([x["leg"] for x in r.legs() if x["start_epoch"] >= t_touch]))
    c("stopfile: it ended cleanly: reason stop_file, exit 0", r.rc == 0 and (r.last("run_end") or {}).get("reason") == "stop_file", f"rc {r.rc}")
    # a stale STOP file at the start is refused, not obeyed (it would end a long run after its first leg)
    r2 = start_driver(env, "stop2", ["--quick", "--legs", "api-test", "--no-sweep"], src=src, pre_stop=True).finish(60)
    c("stopfile: a STOP file already there at the start is refused by name (exit 2), no run begun",
      r2.rc == 2 and "remove it to start" in r2.text and not os.path.exists(os.path.join(r2.out, "metrics.jsonl")), f"rc {r2.rc}: {r2.text[-200:]}")
    return out


def scn_deadline(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    t0 = time.time()
    deadline = t0 + 16
    R = run_driver(env, "deadline", ["--until", until(16), "--legs", "api-test,dt-i,dt-q8", "--no-sweep"],
                   [{"leg": "dt-q8", "nth": [2], "do": "fail"}], src=src, cap=120)
    legs = R.legs()
    c("deadline: ended at the deadline (reason deadline), exit 0 even with a failing leg in the run",
      R.rc == 0 and (R.last("run_end") or {}).get("reason") == "deadline", f"rc {R.rc}: {R.text[-200:]}")
    c("deadline: several cycles ran before it, and the failing leg was recorded", len({x["cycle"] for x in legs}) >= 2
      and any(x["status"] == "fail" for x in legs), str(len(legs)))
    c("deadline: no leg started after the deadline", all(x["start_epoch"] <= deadline + 0.5 for x in legs),
      str([x["start"] for x in legs if x["start_epoch"] > deadline + 0.5]))
    c("deadline: it ended within a few seconds of the deadline", (R.last("run_end")["epoch"] - deadline) < 15, str(R.last("run_end")["epoch"] - deadline))
    return out


def scn_rotation(env: Env, src: str = HERE) -> list:
    R = run_driver(env, "rotation", ["--until", until(35), "--legs", "api-test", "--no-sweep"], src=src, cap=120)
    cs = [r["image"] for r in R.recs if r.get("type") == "cycle_start"]
    want = L.smooth_wrr({"quad": 4, "single": 1, "deep": 1}, len(cs))
    out = [("rotation: the images visited are the weighted rotation (quad 4, single 1, deep 1), in its order",
            len(cs) >= 6 and cs == want, f"{cs} vs {want}"),
           ("rotation: the quad has four visits in every six",
            cs[:6].count("quad") == 4 and cs[:6].count("single") == 1 and cs[:6].count("deep") == 1, str(cs[:6]))]
    return out


def scn_diskfloor(env: Env, src: str = HERE) -> list:
    R = run_driver(env, "disk", ["--quick", "--legs", "api-test,dt-i", "--disk-floor-gb", "1000000000"], src=src, cap=60)
    return [("disk floor: below the floor the driver stops before any leg - not a host slice either - exit 3, reason disk_floor",
             R.rc == 3 and not R.legs() and (R.last("run_end") or {}).get("reason") == "disk_floor", f"rc {R.rc} legs {len(R.legs())}"),
            ("disk floor: it says which filesystem and how much, in STOPPED.txt",
             os.path.exists(os.path.join(R.out, "STOPPED.txt"))
             and "GB free, floor" in open(os.path.join(R.out, "STOPPED.txt")).read(), "")]


def spawn_sleeper(args_tail: list):
    """A process whose command line looks like `args_tail` and does nothing: python -c <sleep> <tail>."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"] + args_tail,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def scn_guard(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sl = spawn_sleeper(["device-test", env.imgs["quad"]])
    try:
        time.sleep(1.5)
        R = run_driver(env, "guard-a", ["--quick", "--legs", "api-test", "--no-sweep"], src=src, cap=90)
        c("guard: another process on the card (device-test with an xclbin) refuses the start, exit 2",
          R.rc == 2 and "guard_refused" in R.text and str(sl.pid) in R.text, f"rc {R.rc}: {R.text[-300:]}")
        c("guard: a refused start leaves no metrics file behind", not os.path.exists(os.path.join(R.out, "metrics.jsonl")))
        c("guard: and the guard did not kill what it detected (the sleeper is still alive)", sl.poll() is None)
    finally:
        sl.kill()
        sl.wait()
    sv = spawn_sleeper(["bash", "verify/run.sh", "--only", "seq"])
    try:
        time.sleep(1.5)
        R = run_driver(env, "guard-b", ["--quick", "--legs", "api-test", "--no-sweep"], src=src, cap=90)
        b = R.events("beside")
        c("guard: a verify/run.sh run (no card) is allowed beside it, and the run records that it ran",
          R.rc == 0 and len(R.legs("api-test")) == 3 and b and str(sv.pid) in b[0]["detail"], f"rc {R.rc}: {R.text[-200:]}")
        c("guard: and status.txt names it", "verify/run.sh pid " + str(sv.pid) in open(os.path.join(R.out, "status.txt")).read())
    finally:
        sv.kill()
        sv.wait()
    # between legs: wait for the other process to finish, then go on
    r = start_driver(env, "guard-c", ["--until", until(600), "--legs", "api-test,dt-i", "--no-sweep"],
                     [{"leg": "dt-i", "from": 1, "do": "slow:2"}], src=src)
    try:
        wait_for(lambda: r.legs("api-test"), 90)
        s2 = spawn_sleeper(["cft-selftest", "vectors/out", env.imgs["quad"]])
        t_sl = time.time()
        got = wait_for(lambda: r.events("guard_wait"), 90)
        n_during = len(r.legs())
        time.sleep(3)
        c("guard: a card user appearing mid-run makes the driver wait (guard_wait recorded)", got)
        c("guard: and no leg starts while it is there", len(r.legs()) == n_during or all(x["start_epoch"] < t_sl + 2 for x in r.legs()[n_during:]),
          f"{n_during} -> {len(r.legs())}")
        s2.kill()
        s2.wait()
        cleared = wait_for(lambda: r.events("guard_clear"), 60)
        c("guard: when it ends the driver goes on (guard_clear)", cleared)
    finally:
        with open(os.path.join(r.out, "STOP"), "w") as fh:
            fh.write("x")
        r.finish(120)
    return out


def intervals_of(R_list: list, item: str):
    iv = []
    for R in R_list:
        for x in R.legs(kind="sweep", status="pass"):
            if x["sweep"]["item"] == item:
                iv.append((x["sweep"]["lo"], x["sweep"]["hi"]))
    return iv


def scn_sweep(env: Env, src: str = HERE) -> list:
    """The sweep across a restart. Run A passes one slice, then every soak job loses the device until the
    driver stops (card_lost): the failed slice is NOT covered. Run B resumes the same directory and must
    start at that slice, not skip it, and carry on contiguously."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    rate = {"CFT_STANDIN_SOAK_RATE": "4000000"}
    sc = [{"leg": "soak", "op": "sqrt32", "from": 2, "do": "nodevice"}]
    # one image (the quad), one item: the slices of one campaign line run one after another, so
    # coverage and rates are comparable across the restart
    args = ["--legs", "api-test", "--weights", "quad=1,single=0,deep=0", "--sweep-items", "sqrt32-rne",
            "--sweep-minutes", "quad=1,single=1,deep=1", "--sweep-slice-seconds", "2", "--min-slice-seconds", "3",
            "--quarantine-after", "5", "--probe-cases", str(1 << 20)]
    A = run_driver(env, "sweepA", ["--until", until(120)] + args + ["--max-card-failures", "4"], sc, src=src, cap=150,
                   extra_env=rate)
    legsA = [x for x in A.legs(kind="sweep") if x["sweep"]["item"] == "sqrt32-rne"]
    passA = [x for x in legsA if x["status"] == "pass"]
    badA = [x for x in legsA if x["status"] == "no_device"]
    c("sweep: run A passed one slice (the probe, 2^20) and then lost the device on every job until it stopped",
      A.rc == 3 and len(passA) == 1 and (passA[0]["sweep"]["lo"], passA[0]["sweep"]["hi"]) == (0, 1 << 20) and len(badA) >= 3
      and (A.last("run_end") or {}).get("reason") == "card_lost", f"rc {A.rc}, {len(passA)} passed, {len(badA)} failed")
    c("sweep: every failed attempt was at the same place, the start of the first uncovered slice, 2^20",
      bool(badA) and {x["sweep"]["lo"] for x in badA} == {1 << 20}, str({x["sweep"]["lo"] for x in badA}))
    iv, _served, _cases, _seeds, _dis = L.sweep_coverage(A.recs)
    c("sweep: the coverage the records give is the passed slice alone: the failed slices are not covered",
      L.merge_intervals(iv.get("sqrt32-rne", [])) == [(0, 1 << 20)], str(iv))
    if len(passA) != 1 or not badA:
        return out
    return out + scn_sweep_resume(env, A, args, rate, src)


def scn_sweep_resume(env: Env, A: Run, args: list, rate: dict, src: str) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    env.n += 1
    cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", A.out, "--resume", "--dry-run",
           "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1", "--kill-after", "2", "--guard-poll", "1",
           "--until", until(22), "--max-card-failures", "20"] + args
    for n, p in env.imgs.items():
        cmd += ["--image", f"{n}={p}"]
    e = dict(os.environ)
    e.update(rate)
    e["CFT_STANDIN_STATE"] = A.state
    e.pop("CFT_STANDIN_SCENARIO", None)          # the device answers again
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT, timeout=150)
    R = Run(A.out)
    R.rc, R.text = p.returncode, p.stdout
    recs = R.recs
    c("sweep resume: the resumed run appended to the same metrics file (two run_start records, the second resumed)",
      [r.get("resumed") for r in recs if r.get("type") == "run_start"] == [False, True], str(R.text[-300:]))
    second = [i for i, r in enumerate(recs) if r.get("type") == "run_start"][1]
    after = [r for r in recs[second:] if r.get("type") == "leg" and r["kind"] == "sweep"]
    c("sweep resume: the slice that lost the device before the restart was redone FIRST: B's first slice starts at 2^20 and passes",
      bool(after) and after[0]["status"] == "pass" and after[0]["sweep"]["lo"] == 1 << 20,
      f"B's first slice {after[0]['sweep'] if after else None}")
    iv = intervals_of([R], "sqrt32-rne")
    merged = L.merge_intervals(iv)
    c("sweep resume: after the restart the passing slices are ONE contiguous range from 0, longer than A's, nothing skipped",
      len(merged) == 1 and merged[0][0] == 0 and merged[0][1] > (1 << 20) * 2, str(merged[:3]))
    c("sweep resume: no range was run twice by a passing slice", bool(merged) and sum(h - l for l, h in iv) == merged[0][1] - merged[0][0],
      f"{sum(h - l for l, h in iv)} vs {merged}")
    cycles = [r["cycle"] for r in recs if r.get("type") == "cycle_start"]
    c("sweep resume: cycle numbers continue across the restart (none twice, in order)", len(cycles) == len(set(cycles)) and cycles == sorted(cycles), str(cycles))
    c("sweep resume: rates were rebuilt from the records (the resumed run's first slice is rate-sized, not the probe)",
      bool(after) and (after[0]["sweep"]["hi"] - after[0]["sweep"]["lo"]) != (1 << 20),
      str([x["sweep"]["hi"] - x["sweep"]["lo"] for x in after][:4]))
    return out


def dg(d, *keys):
    """d[k1][k2]... or None when any step is missing: a check about a record a broken driver left incomplete must go red,
    not crash the scenario."""
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d


def stop_run(r: Run) -> None:
    with open(os.path.join(r.out, "STOP"), "w") as fh:
        fh.write("stop")


def scn_sweep_all(env: Env, src: str = HERE) -> list:
    """The exhaustive conversion and scaleB items (parcel EX: conv32to64-all, cvtto32-all, cvtfrom32-all, scaleb32-wide)
    served by the driver against the stand-in. A: four of them, one a tile, each to the end of the 2^32 space - every
    slice held to its encodings and to its checks, reach recorded, the status file and the report saying how much of
    the space each kind has seen. B: a slice the tool ran one encoding or one case short is parse_error, not covered,
    and served again. C: a refused slice survives a restart as a gap and is the first thing the resumed run serves."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    names = ["conv32to64-all", "cvtto32-all-rup", "cvtfrom32-all-rne", "scaleb32-wide-rdn"]
    base = SWEEP_ALL_BASE
    # -- A: served to the end
    r = start_driver(env, "sweepall", ["--until", until(300), "--sweep-items", ",".join(names)] + base, src=src, to_file=True)

    def complete():
        iv = L.sweep_coverage(r.recs)[0]
        return all(iv.get(n) and L.first_gap(iv[n]) is None for n in names)

    done = wait_for(complete, 200, 0.5)
    stop_run(r)
    r.finish(90)
    legs = r.legs(kind="sweep")
    c("sweep all: the four items were each served to the end of the space (2^32 encodings, no gap), then it stopped on STOP",
      done and r.rc == 0, f"done {done}, rc {r.rc}")
    c("sweep all: every slice passed", bool(legs) and all(x["status"] == "pass" for x in legs),
      str(sorted({x["status"] for x in legs})))
    per = {"conv32to64-all": 1, "cvtto32-all-rup": 4, "cvtfrom32-all-rne": 2, "scaleb32-wide-rdn": 568}
    host = {"conv32to64-all": "host", "cvtto32-all-rup": "host", "cvtfrom32-all-rne": "host", "scaleb32-wide-rdn": "tile"}
    for n in names:
        mine = sorted((x for x in legs if x["sweep"]["item"] == n), key=lambda x: x["sweep"]["lo"])
        enc = sum(dg(x, "counts", "encodings") or 0 for x in mine)
        c(f"sweep all {n}: the slices' encodings add up to exactly 2^32 and are contiguous from 0 (each slice's own "
          f"count read from its verdict line)", bool(mine) and enc == EXH_T and mine[0]["sweep"]["lo"] == 0
          and mine[-1]["sweep"]["hi"] == EXH_T and all(a["sweep"]["hi"] == b["sweep"]["lo"] for a, b in zip(mine, mine[1:])),
          f"{enc} encodings in {len(mine)} slices")
        c(f"sweep all {n}: each slice's verdict covered its slice, and its checks were {per[n]} an encoding",
          bool(mine) and all(dg(x, "counts", "encodings") == x["sweep"]["hi"] - x["sweep"]["lo"] == dg(x, "sweep", "expected_encodings")
                             and (dg(x, "counts", "cases") or 0) + (dg(x, "counts", "skipped") or 0) == per[n] * (dg(x, "counts", "encodings") or 0)
                             for x in mine))
        if n == "cvtto32-all-rup":
            c(f"sweep all {n}: no fixed count of cases is expected of it (its cases depend on the operands), and some pairs "
              f"were skipped", bool(mine) and all("expected_cases" not in x["sweep"] for x in mine)
              and sum(dg(x, "counts", "skipped") or 0 for x in mine) > 0)
        else:
            c(f"sweep all {n}: its cases are exactly {per[n]} a encoding, expected_cases recorded, nothing skipped",
              bool(mine) and all(dg(x, "sweep", "expected_cases") == per[n] * (x["sweep"]["hi"] - x["sweep"]["lo"])
                                 == dg(x, "counts", "cases") and dg(x, "counts", "skipped") == 0 for x in mine))
        job_word = {"conv32to64-all": "conv32to64-all", "cvtto32-all-rup": "cvtto32-all",
                    "cvtfrom32-all-rne": "cvtfrom32-all", "scaleb32-wide-rdn": "scaleb32-wide"}[n]
        c(f"sweep all {n}: every record says its reach ({host[n]}) and the tool's job word ({job_word})",
          bool(mine) and all(dg(x, "sweep", "reach") == host[n] and dg(x, "sweep", "op") == job_word for x in mine))
    c("sweep all: the first slice of each item is the probe size and the later ones are whole 2^20 atoms, capped at 2^28 on the "
      "card and at 2^36 for a host job",
      all((lambda sl, cap: bool(sl) and sl[0]["sweep"]["lo"] == 0 and sl[0]["sweep"]["hi"] == 1 << 20
           and all((x["sweep"]["hi"] - x["sweep"]["lo"]) % (1 << 20) == 0 and (x["sweep"]["hi"] - x["sweep"]["lo"]) <= cap for x in sl))
          (sorted((x for x in legs if x["sweep"]["item"] == n), key=lambda x: x["sweep"]["lo"]),
           1 << 36 if host[n] == "host" else 1 << 28) for n in names))
    c("sweep all: the three host items ran on the pool (image cpu) and the one tile item on the card (the quad)",
      all({x["image"] for x in legs if x["sweep"]["item"] == n} == ({"cpu"} if host[n] == "host" else {"quad"}) for n in names))
    st = open(os.path.join(r.out, "status.txt")).read()
    # the exhaustive items' spaces: 2^32 for each of the scripts' 36 (18 tile, 18 host), and for the coverage wave's 35 the indices of
    # the mode's own space (the library's table; the catalog check holds each to the documents' figures)
    ex_items = [it for it in L.sweep_items() if it.kind == "exhaustive"]
    sp_all = sum(it.space for it in ex_items)
    sp_t = sum(it.space for it in ex_items if it.reach == "tile")
    sp_h = sum(it.space for it in ex_items if it.reach == "host")
    c("sweep all: status.txt says what the tile has seen and what it has not, on a line of its own that begins 'reach': one tile "
      "item done of 40 (18 of the scripts' and the coverage wave's 22), three host items of 31 (18 and 13)",
      re.search(r"^reach      tile items: exhaustive %s of %s encodings .*; host items: exhaustive %s of %s encodings .*; "
                r"the tile computes nothing for a host item$" % (f"{EXH_T:,}", f"{sp_t:,}", f"{3 * EXH_T:,}", f"{sp_h:,}"), st, re.M)
      is not None and len(ex_items) == 71 and sp_t > 18 * EXH_T and sp_h > 18 * EXH_T, st[st.find("reach"):][:400])
    c("sweep all: and its sweep line counts all 71 exhaustive items' encodings, the new ones included, each over its own space",
      f"exhaustive {4 * EXH_T:,} of {sp_all:,} encodings" in st and sp_all == sp_t + sp_h, st[st.find("sweep "):][:200])
    rp = os.path.join(HERE, "card_stress_report.py")
    p = subprocess.run([sys.executable, "-B", "-I", rp, r.out, "--no-write"], capture_output=True, text=True, timeout=120)
    t = p.stdout
    c("sweep all: the report gives each item's reach and totals the coverage by reach",
      p.returncode == 0 and re.search(r"^  conv32to64-all\s.*\shost$", t, re.M) and re.search(r"^  scaleb32-wide-rdn\s.*\stile$", t, re.M)
      and re.search(r"^  reach tile: 1 exhaustive item\(s\) seen; covered %d of %d encodings \(100\.000%%\); fully covered 1 of 1$" % (EXH_T, EXH_T), t, re.M)
      and re.search(r"^  reach host: 3 exhaustive item\(s\) seen; covered %d of %d encodings \(100\.000%%\); fully covered 3 of 3$" % (3 * EXH_T, 3 * EXH_T), t, re.M)
      is not None, t[t.find("exhaustive items"):][:900])
    return out + scn_sweep_short(env, src, base)


def scn_sweep_short(env: Env, src: str, base: list) -> list:
    """B: a slice the tool ran one encoding or one case short is parse_error, by the rule written for it, not covered,
    and served again. Three of the items are HOST items, which the pool serves (image cpu), and one is a TILE item that has
    a cover spec (scaleb32-wide), which the card serves: the two paths each hold a slice to what it covered, so each is
    shown here, and a plant of either is caught by its own item."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sc = [{"leg": "soak", "op": "cvtto32-all", "nth": [1], "do": "short"},
          {"leg": "soak", "op": "cvtto32-all", "nth": [2], "do": "shortcase"},
          {"leg": "soak", "op": "conv32to64-all", "nth": [1], "do": "shortcase"},
          {"leg": "soak", "op": "cvtfrom64-all", "nth": [1], "do": "short"},
          {"leg": "soak", "op": "scaleb32-wide", "nth": [1], "do": "short"},
          {"leg": "soak", "op": "scaleb32-wide", "nth": [2], "do": "shortcase"},
          {"leg": "soak", "op": "scaleb32-wide", "nth": [3], "do": "badenc"}]
    bn = ["cvtto32-all-rne", "conv32to64-all", "cvtfrom64-all-rne", "scaleb32-wide-rne"]
    r2 = start_driver(env, "sweepshort", ["--until", until(120), "--sweep-items", ",".join(bn)] + base, sc, src=src,
                      to_file=True)

    def served():
        return all(any(x["status"] == "pass" and x["sweep"]["item"] == n for x in r2.legs(kind="sweep")) for n in bn)

    got = wait_for(served, 90, 0.4)
    stop_run(r2)
    r2.finish(60)
    for n, want in (("cvtto32-all-rne", ["encodings where the slice has", "checks where"]),
                    ("conv32to64-all", ["cases where the slice has"]), ("cvtfrom64-all-rne", ["cases where the slice has"]),
                    ("scaleb32-wide-rne", ["cases where the slice has", "cases where the slice has", "encodings where the slice has"])):
        mine = sorted((x for x in r2.legs(kind="sweep") if x["sweep"]["item"] == n), key=lambda x: x["start_epoch"])
        k = len(want)
        c(f"sweep short {n}: the first {k} slice(s) came back short and were refused as parse_error, by the rule written for each "
          f"({', '.join(want)}), with no counts recorded",
          got and len(mine) > k and all(x["status"] == "parse_error" and x["counts"] is None and w in (x["reason"] or "")
                                         for x, w in zip(mine[:k], want)), str([(x["status"], x["reason"]) for x in mine[:k + 1]]))
        c(f"sweep short {n}: the same slice [0, 2^20) was served again each time, and then passed",
          got and all((x["sweep"]["lo"], x["sweep"]["hi"]) == (0, 1 << 20) for x in mine[:k + 1]) and mine[k]["status"] == "pass"
          and mine[k]["counts"]["encodings"] == 1 << 20,
          f"got {got}; " + str([(x["sweep"]["lo"], x["sweep"]["hi"], x["status"], (x["reason"] or "")[:60]) for x in mine[:k + 1]]))
        iv, served_n, _cases, _seeds, _dis = L.sweep_coverage(r2.recs)
        c(f"sweep short {n}: the refused slices are not covered: the coverage the records give starts with the passing slice "
          f"and counts only passing slices", (iv.get(n) or [(None, None)])[0][0] == 0
          and served_n.get(n) == sum(1 for x in mine if x["status"] == "pass"))
    return out + scn_sweep_gap(env, src, base)


def scn_sweep_gap(env: Env, src: str, base: list) -> list:
    """C: a refused slice is a gap that survives a restart, and is the first thing the resumed run serves."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    scc = [{"leg": "soak", "op": "cvtto32-all", "from": 1, "do": "short"}]
    r3 = start_driver(env, "sweepgapA", ["--until", until(90), "--sweep-items", "cvtto32-all-rup"] + base, scc, src=src,
                      to_file=True)
    wait_for(lambda: len(r3.legs(kind="sweep")) >= 2, 60, 0.3)
    stop_run(r3)
    r3.finish(60)
    a = r3.legs(kind="sweep")
    c("sweep gap: run A's every attempt came back short and was refused (parse_error); the item has no coverage at all",
      len(a) >= 2 and all(x["status"] == "parse_error" and (x["sweep"]["lo"], x["sweep"]["hi"]) == (0, 1 << 20) for x in a)
      and not L.sweep_coverage(r3.recs)[0].get("cvtto32-all-rup"), str([(x["status"], x["sweep"]["lo"]) for x in a][:4]))
    os.remove(os.path.join(r3.out, "STOP"))                 # a stale STOP would refuse the resume, by design
    env.n += 1
    cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", r3.out, "--resume", "--dry-run",
           "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1", "--kill-after", "2", "--guard-poll", "1",
           "--until", until(14), "--sweep-items", "cvtto32-all-rup"] + base
    for nm, pth in env.imgs.items():
        cmd += ["--image", f"{nm}={pth}"]
    e = dict(os.environ)
    e["CFT_STANDIN_STATE"] = r3.state
    e.pop("CFT_STANDIN_SCENARIO", None)                     # the tool is whole again
    pr = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT, timeout=150)
    recs = L.read_records(os.path.join(r3.out, "metrics.jsonl"))[0]
    second = [i for i, x in enumerate(recs) if x.get("type") == "run_start"][1]
    after = [x for x in recs[second:] if x.get("type") == "leg" and x["kind"] == "sweep"]
    c("sweep gap: the resumed run served the refused slice FIRST: its first slice starts at 0 and passes",
      pr.returncode == 0 and bool(after) and after[0]["status"] == "pass" and after[0]["sweep"]["lo"] == 0
      and after[0]["counts"]["encodings"] == after[0]["sweep"]["hi"] - after[0]["sweep"]["lo"], f"rc {pr.returncode}: {pr.stdout[-300:]}")
    iv = L.sweep_coverage(recs)[0].get("cvtto32-all-rup", [])
    c("sweep gap: and the passing slices that followed are one contiguous range from 0",
      len(L.merge_intervals(iv)) == 1 and L.merge_intervals(iv)[0][0] == 0, str(L.merge_intervals(iv)[:3]))
    return out


EXH_T = 1 << 32
SWEEP_ALL_BASE = ["--legs", "api-test", "--weights", "quad=1,single=0,deep=0", "--sweep-minutes", "quad=5,single=5,deep=5",
                  "--sweep-slice-seconds", "600", "--min-slice-seconds", "3", "--quarantine-after", "1000"]


def scn_disagree(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    R = run_driver(env, "disagree", ["--quick", "--legs", "api-test", "--sweep-minutes", "quad=1,single=1,deep=1"],
                   [{"leg": "soak", "op": "sqrt32", "nth": [1], "do": "mismatch"}], src=src, cap=120)
    f = R.legs(kind="sweep", status="fail")
    c("disagreement: a soak that disagrees with the CPU oracle is status fail with its counts", len(f) == 1
      and f[0]["counts"]["value_mismatches"] == 1 and f[0]["counts"]["flag_mismatches"] == 1, str(f[:1]))
    c("disagreement: its record holds the operands (the MISMATCH and FLAGS lines, with a=0x...)",
      f and len(f[0]["disagreements"]) == 2 and all("a=0x" in d for d in f[0]["disagreements"]), str(f[:1]))
    c("disagreement: its log is kept whole", f and f[0]["log_kept"] == "whole" and "MISMATCH" in log_text(R, f[0]))
    c("disagreement: the slice counts as covered (a verdict was reached) and the sweep went on", len(R.legs(kind="sweep")) >= 8)
    iv, served, cases, seeds, dis = L.sweep_coverage(R.recs)
    c("disagreement: sweep_coverage lists it with its operands", len(dis) == 1 and dis[0]["lines"] and dis[0]["item"] == "sqrt32-rne")
    c("disagreement: status.txt counts it", "disagreements 1" in open(os.path.join(R.out, "status.txt")).read())
    return out


def telemetry_order_checks(src: str = HERE) -> list:
    """Whether two samples that overlap are recorded in the order their readings were taken, FORCED rather than waited for
    (parcel DR1, 2026-10-20; scn_telemetry's check of the stand-in's temperature saw one pair swapped on a busy desktop). A
    sample A takes its reading and is held inside its examine call, as a process the OS has not yet scheduled again; a second
    sample B then starts. A driver that lets B run takes B's reading second and appends B's record FIRST; one that serialises
    its samples keeps B waiting, and the records come out A, B. No load, no luck: the interleaving is the test's own."""
    import importlib
    import threading
    out: list = []
    sys.path.insert(0, src)
    saved_lib = sys.modules.pop("card_stress_lib", None) if os.path.abspath(src) != os.path.abspath(HERE) else None
    tmp = tempfile.mkdtemp(prefix="cs-tel-")
    go, go2 = threading.Event(), threading.Event()
    try:
        mod = importlib.import_module("card_stress")
        a = mod.parse_args(["--out", tmp, "--root", ROOT, "--dry-run", "--telemetry-reports", "thermal"])
        d = mod.Driver(a)
        mu = threading.Lock()
        taken: list = []
        held, b_in = threading.Event(), threading.Event()

        def examine(tool, rep, mode):
            with mu:
                taken.append(threading.current_thread().name)
                n = len(taken)
            if threading.current_thread().name == "A":
                held.set()
                go.wait(30)                    # A holds its reading, n = 1, and is not scheduled again until released
            else:
                b_in.set()
            return {"FPGA Temperature": 30.0 + 0.5 * n}, "", None

        d.examine = examine
        ta = threading.Thread(target=d.telemetry, args=("A",), name="A")
        tb = threading.Thread(target=d.telemetry, args=("B",), name="B")
        ta.start()
        held.wait(10)
        tb.start()
        if b_in.wait(1.5):                     # unserialised, B reads and appends at once; serialised, it waits for A
            tb.join(10)
        go.set()
        ta.join(10)
        tb.join(10)
        recs = [r for r in L.read_records(os.path.join(tmp, "metrics.jsonl"))[0] if r.get("type") == "telemetry"]
        whens = [r["when"] for r in recs]
        temps = [(r.get("values") or {}).get("thermal.FPGA Temperature") for r in recs]
        epochs = [r["epoch"] for r in recs]
        out.append(("telemetry: two samples that overlap are recorded in the order their readings were taken (A took "
                    "n=1 and was held; B started meanwhile)", taken == ["A", "B"] and whens == taken
                    and temps == [30.5, 31.0] and epochs == sorted(epochs) and not ta.is_alive() and not tb.is_alive(),
                    f"readings taken {taken}, records appended {whens}, temperatures {temps}"))
        # the run's stop reaches a timer sample that is in flight, with the run's own "end" sample waiting behind it
        d.a.telemetry_reports = "thermal,electrical"           # two examine calls a sample
        taken2: list = []
        held2 = threading.Event()

        def examine2(tool, rep, mode):
            with mu:
                taken2.append(threading.current_thread().name)
            if threading.current_thread().name == "T":
                held2.set()
                go2.wait(30)
            return {"FPGA Temperature": 50.0}, "", None

        d.examine = examine2
        tt = threading.Thread(target=d.telemetry, args=("timer",), name="T")
        te = threading.Thread(target=d.telemetry, args=("end",), name="E")
        tt.start()
        held2.wait(10)
        d.tel_stop.set()
        te.start()
        go2.set()
        tt.join(10)
        te.join(10)
        whens2 = [r["when"] for r in L.read_records(os.path.join(tmp, "metrics.jsonl"))[0]
                  if r.get("type") == "telemetry" and r["when"] in ("timer", "end")]
        out.append(("telemetry: a timer sample the run's stop reaches while it is in flight is dropped at its next "
                    "examine call, and the 'end' sample waiting behind it is taken and recorded", taken2 == ["T", "E", "E"]
                    and whens2 == ["end"] and not tt.is_alive() and not te.is_alive(),
                    f"examine calls {taken2}, records {whens2}"))
    except Exception as e:                     # a driver that cannot be driven this way is a red check, not a crash
        out.append(("telemetry: two samples that overlap are recorded in the order their readings were taken (the driver "
                    "could not be driven)", False, repr(e)))
    finally:
        go.set()
        go2.set()
        sys.path.remove(src)
        sys.modules.pop("card_stress", None)
        if saved_lib is not None:
            sys.modules["card_stress_lib"] = saved_lib
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def scn_telemetry(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    R = run_driver(env, "tel", ["--until", until(9), "--legs", "api-test", "--no-sweep", "--telemetry-seconds", "1"], src=src, cap=90)
    tel = [r for r in R.recs if r.get("type") == "telemetry"]
    timer = [r for r in tel if r["when"] == "timer"]
    c("telemetry: a timer sample every second between legs (at least three)", len(timer) >= 3, f"{len(timer)} of {len(tel)}")
    ok = [r for r in tel if r["ok"]]
    def tkey(r):
        return [k for k in r["values"] if k.startswith("thermal.") and "FPGA Temperature" in k][0]

    c("telemetry: samples carry numbers, labelled by the report and the reading's own description",
      bool(ok) and all(k.startswith(("thermal.", "electrical.")) for k in ok[0]["values"])
      and any("FPGA Temperature" in k for k in ok[0]["values"]) and any("current" in k for k in ok[0]["values"]), str(ok[:1]))
    c("telemetry: a report that fails (mechanical: unknown to the stand-in) is an error in the record while the others still read",
      all(r["ok"] and "mechanical" in (r["error"] or "") for r in tel), str([r["error"] for r in tel[:2]]))
    c("telemetry: host load, memory and free disk are in the sample where the host reports them", all(r["host"] and "disk_free_gb" in r["host"] for r in tel))
    xs = [r["epoch"] for r in ok]
    ts = [r["values"][tkey(r)] for r in ok]
    c("telemetry: the stand-in's temperature rises with time and the samples show it, in order",
      len(ts) >= 3 and ts == sorted(ts) and ts[-1] > ts[0] and xs == sorted(xs), str(ts))
    # the parser on text and JSON, and on garbage, directly
    c("telemetry parser: JSON with string numbers", L.parse_telemetry('{"thermals":[{"description":"HBM","temp_C":"35"}]}') == {"thermals.HBM.temp_C": 35.0})
    c("telemetry parser: as-is text rows", L.parse_telemetry("  FPGA Temperature   : 31 C\n  Power   15.5 W\nnot a row\n") ==
      {"FPGA Temperature": 31.0, "Power": 15.5})
    c("telemetry parser: nothing readable is {} (never a reading of 0)", L.parse_telemetry("ERROR: no device\n") == {})
    return out + telemetry_order_checks(src) + scn_telemetry_hang(env, src)


def scn_telemetry_hang(env: Env, src: str = HERE) -> list:
    """What the sampler's lock can cost the driver when the vendor tool hangs, as a process against the stand-in (parcel DR1,
    2026-10-20, the lead's question). EVERY examine call hangs (the stand-in sleeps for ever) and --telemetry-timeout is 2 s: each
    is killed at 2 s, so a sample - one report, as JSON and then as text - takes about 4 s and lets go of the lock. STOP is touched
    while the run's own first sample is in flight. The run goes on to what it must - that sample, the timer's, its own `end` - and
    ends by STOP, within about two samples, one timeout and a margin of the moment it was touched, however long a hung call would
    have been. The bound is measured from the run, not from a sample: 2 x the time from the run's start to its first telemetry
    record (that sample and about 0.6 s of setup) + 2 s + 10 s. Every sample is an error record, never a reading, no hung
    process is left, and no two samples ran at once (each takes at least 2 x 2 s, so two records 3.5 s apart or more)."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    r = start_driver(env, "telhang", ["--until", until(300), "--legs", "api-test", "--no-sweep", "--telemetry-seconds", "1",
                                      "--telemetry-timeout", "2", "--telemetry-reports", "electrical"],
                     [{"leg": "telemetry", "from": 1, "do": "hang"}], src=src)
    began = wait_for(lambda: any(f.startswith("hang-telemetry-") for f in os.listdir(r.state)), 60)
    t_stop = time.time()
    stop_run(r)
    r.finish(120)
    recs = r.recs
    tel = [x for x in recs if x.get("type") == "telemetry"]
    end = r.last("run_end") or {}
    pids = [int(open(os.path.join(r.state, f)).read()) for f in os.listdir(r.state) if f.startswith("hang-telemetry-")]
    to_first = (tel[0]["epoch"] - recs[0]["epoch"]) if tel and recs else 0.0     # run_start to the first telemetry record
    late = end.get("epoch", 1e9) - t_stop
    alive = [p for p in pids if standin_alive(p)]
    c("telemetry hang: every examine call hung and was killed at --telemetry-timeout: each sample is an error record "
      "('timed out'), never a reading, and no hung process is left", began and bool(tel) and bool(pids)
      and all((not x["ok"]) and x["values"] is None and "timed out" in (x["error"] or "") for x in tel) and not alive,
      f"began {began}; {len(tel)} samples (timed out, ok) {[('timed out' in (x['error'] or ''), x['ok']) for x in tel]}; "
      f"{len(pids)} hung calls, stand-ins still alive {alive}")
    for pid in alive:                  # a check that fails must not leave a hung stand-in behind: it is ours, killed by its pid
        try:
            if POSIX:
                os.kill(pid, signal.SIGKILL)
            else:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            pass
    c("telemetry hang: no two samples ran at once (consecutive records at least a sample, 3.5 s, apart)",
      len(tel) >= 2 and all(b["epoch"] - a["epoch"] >= 3.5 for a, b in zip(tel, tel[1:])),
      str([round(b["epoch"] - a["epoch"], 1) for a, b in zip(tel, tel[1:])]))
    c("telemetry hang: STOP, touched while the first sample was in flight, ended the run (exit 0, stop_file) within 2 x the "
      "time from the run's start to its first telemetry record, one timeout and 10 s of it",
      r.rc == 0 and end.get("reason") == "stop_file" and 0 < late <= 2 * to_first + 2 + 10,
      f"rc {r.rc}, {end.get('reason')}, ended {late:.1f} s after STOP; the first telemetry record came {to_first:.1f} s "
      f"after the run began")
    return out


def scn_build_refusals(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    q = env.imgs["quad"]
    sums = os.path.join(os.path.dirname(q), "SHA256SUMS")
    good = open(sums).read()
    try:
        with open(sums, "w") as fh:
            fh.write("0" * 64 + "  cft_hw_quad.xclbin\n")
        R = run_driver(env, "badsums", ["--quick", "--legs", "api-test", "--no-sweep"], src=src, cap=60)
        c("build: an image that is not what SHA256SUMS says stops the run before any leg, exit 3",
          R.rc == 3 and not R.legs() and not R.last("build")["ok"] and any("SHA256SUMS says" in s["detail"] for s in R.last("build")["steps"]), f"rc {R.rc}")
        os.remove(sums)
        R = run_driver(env, "nosums", ["--quick", "--legs", "api-test", "--no-sweep"], src=src, cap=60)
        c("build: an image with no SHA256SUMS beside it stops the run too", R.rc == 3 and not R.legs(), f"rc {R.rc}: {R.text[-400:]}")
    finally:
        with open(sums, "w") as fh:
            fh.write(good)
    R = run_driver(env, "wrongsha", ["--quick", "--legs", "api-test", "--no-sweep", "--sha", "quad=" + "1" * 64], src=src, cap=60)
    c("build: an image that is not the hash the driver was given stops the run (exit 3)",
      R.rc == 3 and not R.legs() and any("this driver was given" in s["detail"] for s in R.last("build")["steps"]), f"rc {R.rc}")
    R = run_driver(env, "badarg", ["--quick", "--legs", "nosuchleg"], src=src, cap=30)
    c("args: an unknown leg is refused by name", R.rc != 0 and "nosuchleg" in R.text)
    intree = os.path.join(ROOT, f"card-stress-intree-{os.getpid()}")
    try:
        cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", intree, "--dry-run", "--quick",
               "--legs", "api-test", "--no-sweep", "--telemetry-seconds", "0", "--disk-extra", ""]
        for n, pth in env.imgs.items():
            cmd += ["--image", f"{n}={pth}"]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=ROOT)
        c("build: an --out inside the checkout that git does not ignore is refused by name (exit 2), nothing run",
          p.returncode == 2 and "inside the checkout" in (p.stdout + p.stderr)
          and not os.path.exists(os.path.join(intree, "metrics.jsonl")), f"rc {p.returncode}: {(p.stdout + p.stderr)[-200:]}")
    finally:
        shutil.rmtree(intree, ignore_errors=True)
    import importlib
    sys.path.insert(0, src)
    mod = importlib.import_module("card_stress")
    try:
        import contextlib
        import io
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                mod.parse_args(["--out", os.path.join(env.tmp, "x")])
            refused = False
        except SystemExit:
            refused = True
        c("args: a long run (no --dry-run, no --quick) without --until is refused", refused)
    finally:
        sys.path.remove(src)
        sys.modules.pop("card_stress", None)
    return out


def scn_buildreal(env: Env, src: str = HERE) -> list:
    """The driver's build step and the real api-test, not dry: a scratch copy of the tree, the real make
    (XRT=0, the one thing this host can build), a fake ldd that says what the XRT-linked tools would say,
    a second fake that says they are not linked, and a make that cannot find XRT."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    need = [x for x in ("make", "cc", "git", "bash") if not shutil.which(x)]
    if not POSIX or need:
        skip("buildreal", "needs POSIX with make, cc, git and bash" + (f" (missing: {', '.join(need)})" if need else ""))
        return out
    root = os.path.join(env.tmp, "tree")
    if not os.path.isdir(root):
        os.makedirs(os.path.join(root, "programs"))
        ign = shutil.ignore_patterns("__pycache__", "*.o", "*.lo", "*.a", "*.so")
        shutil.copytree(os.path.join(ROOT, "host"), os.path.join(root, "host"), ignore=ign)
        shutil.copytree(os.path.join(ROOT, "hw"), os.path.join(root, "hw"), ignore=ign)
        shutil.copy(os.path.join(ROOT, "programs", "acceptance.py"), os.path.join(root, "programs", "acceptance.py"))
        for git in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "t"]):
            subprocess.run(["git", "-C", root] + git, capture_output=True, timeout=120)
    fake_ok = os.path.join(env.tmp, "fakebin-ok")
    fake_no = os.path.join(env.tmp, "fakebin-no")
    fake_opt = os.path.join(env.tmp, "fakebin-opt")
    for d, body in ((fake_ok, "echo '\tlibxrt_coreutil.so.2 => /fake/libxrt_coreutil.so.2 (0x0)'"),
                    (fake_no, "echo '\tnot a dynamic executable'"),
                    (fake_opt, 'case "$1" in *cft-selftest) echo "\tnot a dynamic executable";; '
                               '*) echo "\tlibxrt_coreutil.so.2 => /fake/libxrt_coreutil.so.2 (0x0)";; esac')):
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "ldd"), "w") as fh:
            fh.write("#!/bin/sh\n" + body + "\n")
        os.chmod(os.path.join(d, "ldd"), 0o755)

    def drive(name, fake, extra):
        env.n += 1
        o = os.path.join(env.tmp, f"{env.n:02d}-{name}")
        cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", root, "--out", o, "--quick",
               "--legs", "api-test", "--no-sweep", "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1",
               "--kill-after", "2", "--guard-poll", "1", "--build-jobs", "2"]
        for n, pth in env.imgs.items():
            cmd += ["--image", f"{n}={pth}", "--sha", f"{n}={env.shas[n]}"]
        e = dict(os.environ)
        e["PATH"] = fake + os.pathsep + e["PATH"]
        p = subprocess.run(cmd + extra, capture_output=True, text=True, env=e, cwd=ROOT, timeout=900)
        r = Run(o)
        r.rc, r.text = p.returncode, p.stdout + p.stderr
        return r

    R = drive("real-ok", fake_ok, ["--make-xrt-flags", "XRT=0"])
    b = R.last("build")
    c("buildreal: the real make of all, device-test, api-test, remote-test, divsqrt-soak and clause5-soak succeeds",
      b is not None and any(s["name"] == "make" and s["ok"] and "XRT=0" in s["detail"] and "divsqrt-soak" in s["detail"]
                            and "clause5-soak" in s["detail"] and "remote-test" in s["detail"] for s in b["steps"]),
      str(b and [s for s in b["steps"] if s["name"] == "make"]))
    c("buildreal: every tool is asserted XRT-linked (ldd), the build id equals cft-segrun's, the clause-5 probes ran",
      b is not None and b["ok"] and sum(1 for s in b["steps"] if s["name"].startswith("xrt ") and s["ok"]) >= 9
      and any(s["name"] == "build id" and s["ok"] for s in b["steps"]) and any(s["name"] == "probes" and s["ok"] for s in b["steps"]),
      f"rc {R.rc}: {R.text[-400:]}")
    ap = R.legs("api-test")
    c("buildreal: the REAL api-test ran through the driver on each image: pass, 'failed' 0 read from its own line",
      R.rc == 0 and len(ap) == 3 and all(x["status"] == "pass" and x["counts"] == {"failed": 0} for x in ap)
      and all("api-test: all contract checks passed" in log_text(R, x) and "standin" not in log_text(R, x) for x in ap), f"rc {R.rc}")
    c("buildreal: telemetry with no xbutil on the host is recorded as an error, not a reading, and the run goes on",
      all((not t["ok"]) and t["values"] is None and t["error"] for t in R.recs if t.get("type") == "telemetry"))
    N = drive("real-nolink", fake_no, ["--make-xrt-flags", "XRT=0"])
    nb = N.last("build")
    c("buildreal: tools that ldd says do not link XRT stop the run before any leg (exit 3), by name",
      N.rc == 3 and not N.legs() and nb is not None and not nb["ok"]
      and any(s["name"].startswith("xrt ") and not s["ok"] and "does NOT link XRT" in s["detail"] for s in nb["steps"]), f"rc {N.rc}: {N.text[-300:]}")
    O = drive("real-optional", fake_opt, ["--make-xrt-flags", "XRT=0", "--legs", "api-test,selftest"])
    ob = O.last("build")
    sel = O.legs("selftest")
    c("buildreal: an optional tool (cft-selftest) that ldd says is not linked disables ITS leg, by name, and the run goes on",
      O.rc == 0 and ob is not None and ob["ok"] and len(sel) == 3 and all(x["status"] == "skipped" and "does not link XRT" in (x["reason"] or "") for x in sel)
      and len(O.legs("api-test", status="pass")) == 3, f"rc {O.rc}: {O.text[-300:]}")
    X = drive("real-noxrt", fake_ok, ["--xrt-root", "/nonexistent-xrt-root"])
    xb = X.last("build")
    c("buildreal: a make that cannot find XRT stops the run before any leg (exit 3), the make step failed",
      X.rc == 3 and not X.legs() and xb is not None and any(s["name"] == "make" and not s["ok"] for s in xb["steps"]), f"rc {X.rc}: {X.text[-300:]}")
    return out


# a defect in the driver, injected into a copy: its leg tally raises once, on the third pass. The driver must record
# it (driver_error, with its traceback) and go on, as an unattended run has to.
INJECT = [("card_stress.py", "    def tally(self, image: str, status: str) -> None:\n        with self.tally_lock:",
           "    def tally(self, image: str, status: str) -> None:\n        if status == 'pass' and self.counts.get('pass', 0) == 2 and not getattr(self, '_boom', False):\n"
           "            self._boom = True\n            raise RuntimeError('injected fault')\n        with self.tally_lock:")]


def scn_internal_error(env: Env, src: str = HERE) -> list:
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    if src == HERE:
        src = make_plant_copy(env, "inject", INJECT)
    R = run_driver(env, "inject", ["--until", until(26), "--legs", "api-test,dt-i", "--no-sweep"], src=src, cap=120)
    e = R.events("driver_error")
    c("internal error: an unexpected exception in a cycle is recorded as driver_error with its traceback",
      len(e) == 1 and "injected fault" in e[0]["detail"] and "Traceback" in e[0].get("traceback", ""), f"rc {R.rc}: {R.text[-300:]}")
    c("internal error: and the run went on: more cycles ran, and it ended at the deadline, exit 0",
      R.rc == 0 and len({x["cycle"] for x in R.legs()}) >= 3 and (R.last("run_end") or {}).get("reason") == "deadline",
      f"rc {R.rc}, cycles {sorted({x['cycle'] for x in R.legs()})}")
    return out


def scn_signal(env: Env, src: str = HERE) -> list:
    """kill <pid> instead of touching STOP: one SIGTERM ends the run after the leg running; a second terminates that leg."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    if not POSIX:
        skip("signal", "needs POSIX (SIGTERM semantics)")
        return out
    r = start_driver(env, "sig1", ["--until", until(120), "--legs", "api-test,dt-i,dt-q8", "--no-sweep"],
                     [{"leg": "dt-i", "nth": [1], "do": "slow:5"}], src=src)
    log = os.path.join(r.out, "driver.log")
    began = wait_for(lambda: os.path.exists(log) and "leg dt-i on quad starts" in open(log).read(), 90)
    t0 = time.time()
    r.proc.send_signal(signal.SIGTERM)
    r.finish(90)
    di = r.legs("dt-i", "quad")
    c("signal: one SIGTERM: the leg running when it arrived ran to its end (pass, its 5 s)",
      bool(began) and len(di) == 1 and di[0]["status"] == "pass" and di[0]["duration_s"] >= 4.5, f"rc {r.rc}: {r.text[-300:]}")
    c("signal: ... the run ended, exit 0, reason signal, and no leg started after the signal",
      r.rc == 0 and (r.last("run_end") or {}).get("reason") == "signal" and all(x["start_epoch"] < t0 for x in r.legs()),
      f"rc {r.rc}, {(r.last('run_end') or {}).get('reason')}")
    r2 = start_driver(env, "sig2", ["--until", until(120), "--legs", "dt-i", "--no-sweep", "--timeout", "dt-i=60"],
                      [{"leg": "dt-i", "nth": [1], "do": "hang"}], src=src)
    log2 = os.path.join(r2.out, "driver.log")
    began2 = wait_for(lambda: os.path.exists(log2) and "leg dt-i on quad starts" in open(log2).read(), 90)
    r2.proc.send_signal(signal.SIGTERM)
    time.sleep(1.5)
    r2.proc.send_signal(signal.SIGTERM)
    r2.finish(60)
    d2 = r2.legs("dt-i", "quad")
    pids = [int(open(os.path.join(r2.state, f)).read()) for f in os.listdir(r2.state) if f.startswith("hang-")]
    c("signal: a second SIGTERM terminates the leg running, long before its 60 s timeout, and the run ends",
      bool(began2) and bool(d2) and d2[0]["killed"] in ("TERM", "KILL") and d2[0]["duration_s"] < 30 and r2.rc in (0, 3), f"rc {r2.rc}: {d2[:1]}")
    c("signal: and what it started is gone", bool(pids) and not any(pid_alive(x) for x in pids), str(pids))
    return out


def scn_torn_tail(env: Env, src: str = HERE) -> list:
    """A run killed mid-append leaves a last line with no newline. --resume must repair it (keep the torn bytes
    beside the file, cut back to the last whole record), not fuse the next record onto it."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    A = run_driver(env, "torn", ["--quick", "--legs", "api-test", "--no-sweep"], src=src)
    mp = os.path.join(A.out, "metrics.jsonl")
    nA = len(A.recs)
    torn = b'{"type":"leg","cycle":9,"image":"qu'
    with open(mp, "ab") as fh:
        fh.write(torn)
    env.n += 1
    cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", A.out, "--resume", "--dry-run",
           "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1", "--kill-after", "2", "--guard-poll", "1",
           "--quick", "--legs", "api-test", "--no-sweep"]
    for n, pth in env.imgs.items():
        cmd += ["--image", f"{n}={pth}"]
    e = dict(os.environ)
    e["CFT_STANDIN_STATE"] = A.state
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT, timeout=150)
    recs, partial, bad = L.read_records(mp)
    side = [f for f in os.listdir(A.out) if f.startswith("metrics.torn-")]
    c("torn tail: the resume ran (exit 0) and the file is whole: every line parses, no partial tail, more records than before",
      p.returncode == 0 and not partial and not bad and len(recs) > nA, f"rc {p.returncode}, partial {partial}, bad {bad}, {len(recs)} vs {nA}: {p.stdout[-300:]}")
    c("torn tail: the torn bytes were kept beside the file, exactly",
      len(side) == 1 and open(os.path.join(A.out, side[0]), "rb").read() == torn, str(side))
    c("torn tail: the run recorded it (a torn_tail event after the second run_start)",
      any(r.get("type") == "event" and r.get("event") == "torn_tail" for r in recs))
    return out


def scn_item_disabled(env: Env, src: str = HERE) -> list:
    """A sweep item whose every slice gives a log no parser can read must not starve the others: it is tried
    three times (--quarantine-after 2, and more than that in a row), disabled, recorded, and the sweep goes on."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sc = [{"leg": "soak", "op": "sqrt32", "from": 1, "do": "garbage"}]
    R = run_driver(env, "disable", ["--until", until(30), "--legs", "api-test", "--weights", "quad=1,single=0,deep=0",
                                    "--sweep-items", "sqrt32-rne,rint32-rne", "--sweep-minutes", "quad=1,single=1,deep=1",
                                    "--sweep-slice-seconds", "2", "--min-slice-seconds", "3", "--probe-cases", str(1 << 20)],
                   sc, src=src, cap=120, extra_env={"CFT_STANDIN_SOAK_RATE": "4000000"})
    bad = [x for x in R.legs(kind="sweep") if x["sweep"]["op"] == "sqrt32"]
    ev = R.events("item_disabled")
    good = [x for x in R.legs(kind="sweep", status="pass") if x["sweep"]["item"] == "rint32-rne"]
    c("item disabled: the item whose logs cannot be read was tried three times (all parse_error) and then disabled, recorded",
      len(bad) == 3 and all(x["status"] == "parse_error" for x in bad) and len(ev) == 1 and "sqrt32-rne" in ev[0]["detail"],
      f"{len(bad)} attempts {[x['status'] for x in bad]}, {len(ev)} events")
    c("item disabled: the other item went on past it (at least three passing slices, some after the event)",
      len(good) >= 3 and any(x["start_epoch"] > ev[0]["epoch"] for x in good) if ev else False, f"{len(good)} passing")
    c("item disabled: nothing of the disabled item started after the event", bool(ev) and all(x["start_epoch"] < ev[0]["epoch"] for x in bad))
    c("item disabled: status.txt names it", "disabled   sweep items: sqrt32-rne" in open(os.path.join(R.out, "status.txt")).read())
    return out + scn_quick_sweep(env, src)


def scn_quick_sweep(env: Env, src: str = HERE) -> list:
    """--quick with --sweep-items, as a process against the stand-in (parcel DR1, 2026-10-20). A: EX's 22 exhaustive items,
    none of them one of quick's own four - the case of 2026-10-19's smoke, whose every wave was empty while the log said
    the campaign was finished: the waves are now the first four named on the quad and the next two, then the next two, on
    the single and the deep. B: the only item named is disabled on the way: the empty wave that follows says so, by name,
    and does not say the campaign is finished."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    named = exhaustive_conversion_items(L)[::-1]            # reversed: "the order named" is not the catalog's order
    R = run_driver(env, "quicksweep", ["--quick", "--legs", "api-test", "--sweep-items", ",".join(named)], src=src, cap=150)
    sw = sorted((x for x in R.legs(kind="sweep") if x["image"] != "cpu"), key=lambda x: (x["start_epoch"], x["tile"] or 0))
    quad = sorted((x for x in sw if x["image"] == "quad"), key=lambda x: x["tile"] or 0)
    names_of = lambda im: [x["sweep"]["item"] for x in sw if x["image"] == im]
    c("quick sweep: with --sweep-items naming 22 items none of which is quick's own, the quad's wave is the first four named, "
      "one a tile, in the order named", [(x["tile"], x["sweep"]["item"]) for x in quad] == [(i + 1, named[i]) for i in range(4)],
      str([(x["tile"], x["sweep"]["item"]) for x in quad]))
    c("quick sweep: the single and then the deep take one item a wave, the next two named each, not the first again",
      names_of("single") == named[4:6] and names_of("deep") == named[6:8], f"{names_of('single')} {names_of('deep')}")
    host = [x for x in R.legs(kind="sweep") if x["image"] == "cpu"]
    c("quick sweep: all eight card slices passed, each of quick's own size (2^18 encodings), and the smoke exits 0",
      len(sw) == 8 and all(x["status"] == "pass" and x["sweep"]["hi"] - x["sweep"]["lo"] == 1 << 18 for x in sw) and R.rc == 0,
      f"rc {R.rc}, {len(sw)} slices, {sorted({x['status'] for x in sw})}")
    c("quick sweep: and the 14 host items among the 22 named were each served once by the pool, as CPU jobs (the card was asked "
      "for none of them), every slice passed and the file holds every one",
      sorted(x["sweep"]["item"] for x in host) == sorted(n for n in named if n not in {x["sweep"]["item"] for x in sw})
      and len(host) == 14 and all(x["status"] == "pass" and x["tile"] is None for x in host)
      and len({x["sweep"]["item"] for x in host} & {x["sweep"]["item"] for x in sw}) == 0, f"{len(host)} host slices")
    c("quick sweep: no wave was empty (no sweep_empty event), and the log never says the campaign is finished",
      not R.events("sweep_empty") and "nothing left to run" not in R.text, str([e["detail"] for e in R.events("sweep_empty")][:2]))
    R2 = run_driver(env, "quickdisabled", ["--quick", "--legs", "api-test", "--sweep-items", "sqrt32-rne"],
                    [{"leg": "soak", "op": "sqrt32", "from": 1, "do": "garbage"}], src=src, cap=150)
    dis, emp = R2.events("item_disabled"), R2.events("sweep_empty")
    c("quick sweep: the only item named gave three unreadable slices and was disabled (quad, then the single's two waves)",
      len(R2.legs(kind="sweep")) == 3 and all(x["status"] == "parse_error" for x in R2.legs(kind="sweep")) and len(dis) == 1,
      f"{[x['status'] for x in R2.legs(kind='sweep')]}, {len(dis)} events")
    c("quick sweep: the empty wave that follows says it is blocked, by name and by cause - the item disabled - and that the "
      "campaign is NOT finished, and the old 'nothing left to run in this campaign' is not said",
      len(emp) == 1 and emp[0].get("cause") == "blocked" and "sqrt32-rne" in emp[0]["detail"] and "disabled" in emp[0]["detail"]
      and "NOT finished" in emp[0]["detail"] and "nothing left to run" not in emp[0]["detail"] + R2.text
      and emp[0]["image"] == "deep" and bool(dis) and dis[0]["epoch"] <= emp[0]["epoch"], str([e["detail"] for e in emp][:2]))
    rp = os.path.join(src, "card_stress_report.py")         # src is HERE, or a plant's copy of the code
    if os.path.exists(rp):
        p = subprocess.run([sys.executable, "-B", "-I", rp, R2.out, "--no-write"], capture_output=True, text=True, timeout=120)
        c("quick sweep: the report reads a run directory that holds a sweep_empty event: exit 0, and its events line counts it",
          p.returncode == 0 and re.search(r"^\s*events\s*:.*\bsweep_empty 1\b", p.stdout, re.M) is not None,
          f"rc {p.returncode}: {p.stderr[-160:]}")
    return out


def scn_report(env: Env, src: str = HERE) -> list:
    """The report script on the normal run's records, held to figures counted here from the records
    themselves (not by the report's code); then the same run with one record changed."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    rp = os.path.join(src, "card_stress_report.py")     # src is HERE, or a plant's copy of the code
    if not os.path.exists(rp):
        skip("report", "hw/card_stress_report.py is not there")
        return out
    R = env.normal
    jpath = os.path.join(env.tmp, "rep.json")
    p = subprocess.run([sys.executable, "-B", "-I", rp, R.out, "--json", jpath], capture_output=True, text=True, timeout=120)
    txt = p.stdout
    legs = R.legs()
    n_pass = sum(r["status"] == "pass" for r in legs)
    n_skip = sum(r["status"] == "skipped" for r in legs)
    c("report: runs on a finished run, exit 0", p.returncode == 0, p.stderr[-300:])
    c("report: it states the legs recorded, passes and skips as counted from the records",
      f"{len(legs)} recorded; pass {n_pass}" in txt and f"skipped {n_skip}" in txt, txt[txt.find("== TOTALS"):][:300])
    c("report: it names every image and leg", all(k in txt for k in ("quad", "single", "deep", "dt-full", "card-segrun", "acceptance-rev8")))
    c("report: it writes report.txt beside the metrics", os.path.exists(os.path.join(R.out, "report.txt")))
    try:
        j = json.load(open(jpath))
        c("report: --json holds the same run as data", isinstance(j, dict) and len(j) > 3, str(list(j)[:6]))
    except (OSError, ValueError) as e:
        c("report: --json holds the same run as data", False, repr(e))
    cov = sum(r["sweep"]["hi"] - r["sweep"]["lo"] for r in legs
              if r["kind"] == "sweep" and r["status"] == "pass" and r["sweep"]["item"] == "sqrt32-rne")
    m = re.search(r"^\s*sqrt32-rne\s+(\d+)\s+(\d+)\s+(\d+)\s+([0-9.]+)%", txt, re.M)
    c("report: sqrt32-rne's covered encodings and percentage are the ones counted from the records",
      bool(m) and int(m.group(3)) == cov and abs(float(m.group(4)) - 100.0 * cov / 2 ** 32) < 0.0006,
      f"records say {cov}; report line {m.group(0) if m else None}")
    # parcel EX: the table's last column is the item's reach
    mr = re.search(r"^\s*sqrt32-rne\s.*\s(\w+)$", txt, re.M)
    recs_reach = {r["sweep"].get("reach") for r in legs if r["kind"] == "sweep" and r["sweep"]["item"] == "sqrt32-rne"}
    c("report: and its reach column (the last) is what the driver wrote into every one of its records (sqrt32 reaches the tile)",
      bool(mr) and recs_reach == {"tile"} and mr.group(1) == "tile",
      f"records say {sorted(map(str, recs_reach))}; report line {mr.group(0) if mr else None}")
    # a copy with one record changed must change the report, to the new truth
    cp = os.path.join(env.tmp, "rep-copy")
    os.makedirs(cp, exist_ok=True)
    recs = L.read_records(os.path.join(R.out, "metrics.jsonl"))[0]
    for r in recs:
        if r.get("type") == "leg" and r["leg"] == "dt-full" and r["image"] == "quad":
            r["status"] = "fail"
            r["counts"] = {"checks": 1, "failed": 1}
            r["log"] = "logs/the-planted-failure.log"
            break
    with open(os.path.join(cp, "metrics.jsonl"), "w") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")
    p2 = subprocess.run([sys.executable, "-B", "-I", rp, cp, "--no-write"], capture_output=True, text=True, timeout=120)
    c("report: one leg changed to fail: the totals say pass one fewer and fail 1, and the failure is listed with its log path",
      f"{len(legs)} recorded; pass {n_pass - 1}, fail 1" in p2.stdout and "the-planted-failure.log" in p2.stdout
      and "the-planted-failure.log" not in txt, p2.stdout[p2.stdout.find("== TOTALS"):][:300])
    return out


# ---------------------------------------------------------------------------------------
# parcel DR2 (2026-10-20): the host pool, the seeds, and coverage by tree
# ---------------------------------------------------------------------------------------

@contextlib.contextmanager
def lib_from(src: str):
    """card_stress_lib as the copy of the code under test in `src` has it (a plant's own, not the cached real one)."""
    saved = sys.modules.pop("card_stress_lib", None)
    sys.path.insert(0, src)
    try:
        yield importlib.import_module("card_stress_lib")
    finally:
        sys.path.remove(src)
        sys.modules.pop("card_stress_lib", None)
        if saved is not None:
            sys.modules["card_stress_lib"] = saved


def git_out(*args) -> "str | None":
    """git's output at ROOT, or None: the test's own reading of the facts the driver records, by its own commands."""
    try:
        p = subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


# the host-pool scenarios: a non-quick run whose card sweep has nothing to do (the items named are host items), a card leg
# that is quick, and a stand-in that runs a soak at 4 M cases a second
POOL_BASE = ["--legs", "api-test", "--weights", "quad=1,single=0,deep=0", "--sweep-minutes", "quad=5,single=5,deep=5",
             "--sweep-slice-seconds", "2", "--min-slice-seconds", "3", "--probe-cases", str(1 << 20), "--kill-after", "2"]
POOL_RATE = {"CFT_STANDIN_SOAK_RATE": "4000000"}


def pool_unit_checks(src: str = HERE) -> list:
    """In-process, on a Driver that is never run (parcel DR2). Over a whole rotation of the catalog the card's wave plans TILE
    items and never a HOST one, and the pool plans HOST items and never a tile one; two workers never take one item; and the
    seed guard refuses a slice whose tool state another (item, n) already started from."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sys.path.insert(0, src)
    saved_lib = sys.modules.pop("card_stress_lib", None) if os.path.abspath(src) != os.path.abspath(HERE) else None
    tmp = tempfile.mkdtemp(prefix="cs-pool-")
    try:
        mod = importlib.import_module("card_stress")
        L2 = mod.L
        d = mod.Driver(mod.parse_args(["--out", os.path.join(tmp, "o"), "--dry-run", "--root", ROOT]))
        d.items = L2.sweep_items()
        q = mod.Image("quad", "/box/quad.xclbin", 4, "u50-rev8-quad", None)
        card, pool = {}, {}
        for _ in range(33):                                   # 132 card jobs: every one of the 65 tile items about twice
            for j in d.plan_wave(q, 3600, 4):
                card[j["item"].name] = j["item"].reach
                d.served[j["item"].name] = d.served.get(j["item"].name, 0) + 1
        d.served = {}
        for _ in range(120):                                  # two turns of the 60 host items
            j = d.pool_plan()
            if j is None:
                break
            pool[j["item"].name] = (j["item"].reach, j["sweep"]["reach"], j["tile"])
            d.pool_busy.pop(j["item"].name, None)             # the slice is done
            d.served[j["item"].name] = d.served.get(j["item"].name, 0) + 1
        c("pool: over a whole rotation the card's waves plan the 65 TILE items (the 43 of the scripts' campaign and the coverage "
          "wave's 22) and not one host item",
          len(card) == 65 and set(card.values()) == {"tile"}, f"{len(card)} items, reaches {sorted(set(card.values()))}")
        c("pool: and the pool's slices are the 60 HOST items (the 47 and the wave's 13 class-level ones) and not one tile item, no "
          "tile pinned, each record saying reach host",
          len(pool) == 60 and {v[0] for v in pool.values()} == {"host"} and {v[1] for v in pool.values()} == {"host"}
          and {v[2] for v in pool.values()} == {None}, f"{len(pool)} items, {sorted({v[0] for v in pool.values()})}")
        d.pool_busy.clear()
        j1, j2 = d.pool_plan(), d.pool_plan()
        c("pool: two workers never take one item at once (the second plan, with the first still in flight, is another item)",
          j1 is not None and j2 is not None and j1["item"].name != j2["item"].name
          and set(d.pool_busy) == {j1["item"].name, j2["item"].name})
        # the seed guard
        it = next(i for i in d.items if i.kind == "random" and i.reach == L2.TILE)
        st = it.seed_for(0) | 1
        d.seed_n = {}
        d.seed_states = {st: ("some-other-item", 7)}
        try:
            d.plan_wave(q, 3600, 1, [it.name])
            raised = None
        except RuntimeError as e:
            raised = str(e)
        c("seeds: a slice whose tool state another (item, n) already started from is refused, by name, naming both",
          raised is not None and it.name in raised and "some-other-item" in raised and "slice 7" in raised, str(raised))
        d.seed_states = {st: (it.name, 0)}
        try:
            again = len(d.plan_wave(q, 3600, 1, [it.name])) == 1
        except RuntimeError:
            again = False
        c("seeds: the same item and n again (a slice served again after a failure) is not refused", again)
        # the run's rules reach a worker: started below the disk floor (above any disk's free space) it plans nothing and returns at once
        d3 = mod.Driver(mod.parse_args(["--out", os.path.join(tmp, "o3"), "--dry-run", "--root", ROOT, "--disk-floor-gb", "1000000000"]))
        os.makedirs(d3.out, exist_ok=True)     # the floor is read from the filesystem the run's directory is on
        d3.items = L2.sweep_items()
        t3 = threading.Thread(target=d3.pool_worker, args=(1,), daemon=True)
        t3.start()
        t3.join(5)
        returned = not t3.is_alive()
        d3.pool_stop.set()                     # (only a worker that did not return needs this)
        t3.join(10)
        c("pool: a worker started below the disk floor plans nothing and returns at once",
          returned and not d3.pool_busy and not d3.served and d3.pool_served == 0, f"returned {returned}")
    except Exception as e:                     # a driver that cannot be driven this way is a red check, not a crash
        c("pool: the driver could be driven in-process", False, repr(e))
    finally:
        sys.path.remove(src)
        sys.modules.pop("card_stress", None)
        if saved_lib is not None:
            sys.modules["card_stress_lib"] = saved_lib
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def cpu_parse_checks(src: str = HERE) -> list:
    """parse_soak(cpu=True), the parser of a host-pool job, on REAL logs of the software backend (hw/card_stress_fixtures/: the same
    tools, made on the path the pool runs, with no CFT_SOAK_ARTIFACT): they pass; the same log whose backend line names a DEVICE
    is refused by name (a CPU job that opened the card); and so is one that names no backend."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    index = {}
    with open(os.path.join(FIX, "INDEX.txt"), "r", encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip() and not ln.startswith("#"):
                nm, rc, cmd = ln.rstrip("\n").split("\t", 2)
                index[nm] = (int(rc), cmd)
    with lib_from(src) as L2:
        items = {it.name: it for it in L2.sweep_items()}

        def refusal(fn):
            try:
                fn()
            except L2.VerdictError as e:
                return str(e)
            return None
        for nm, iname in (("c5-nextup32.txt", "nextup32"), ("c5x-conv32to64-all.txt", "conv32to64-all"),
                          ("c5x-cvtto32-all.txt", "cvtto32-all-rup")):
            it = items[iname]
            op, lo, hi, mode = fixture_job(index, nm)
            t, rc = fixture(nm), index[nm][0]
            exp, cover = it.expected_cases(lo, hi), it.cover_spec(lo, hi)

            def parse(text, it=it, exp=exp, cover=cover, rc=rc):
                return L2.parse_soak(text, rc, it.op, it.verdict_mode, None, exp, cover, cpu=True)
            why = refusal(lambda: parse(t))
            dev = refusal(lambda: parse(t.replace("soaking the software backend", "soaking the DEVICE backend: /box/quad.xclbin")))
            none = refusal(lambda: parse(t.replace("soaking the software backend\n", "")))
            c(f"cpu parser {nm}: a real log of the software backend passes as a host job's, and a log that names a DEVICE is refused "
              f"as a CPU job that opened the card, one that names no backend is refused",
              "soaking the software backend" in t and why is None and dev is not None and dev.startswith(L2.CPU_OPENED_CARD)
              and none is not None and "software backend" in none, f"{why} | {dev} | {none}")
    return out


def append_lock_checks(src: str = HERE) -> list:
    """The metrics file has one writer at a time in this process (parcel DR2). Eight threads - the host pool's workers, the card's
    thread, the telemetry sampler - append at one instant, over and over. THE CAUSE, on every platform: the write is slowed by 5 ms
    inside, and no two threads may ever be inside it together (a lock held across the write makes this true; without it all eight
    are). THE SYMPTOM is what the file shows without the lock, and the two kinds of host show it differently (MEASURED with this
    check's own shape, 60 trials of eight threads by twelve rounds, the lock replaced by a no-op). Windows, whose emulation of
    O_APPEND seeks to the end and then writes, lets two writers at once overwrite each other: records were lost in 60 trials of 60
    (2,841 of 5,760 records in all; a dry run lost a leg record that way when the pool's workers finished together) and the file's
    order was not its epochs' order in 7 (Windows 11, Python 3.12.9). POSIX appends atomically, so no record is lost or torn, but
    the epoch is stamped before the write, so without the lock the file's order stops being its epochs' order: in 53 trials of 60
    (WSL2, Ubuntu 22.04, Python 3.10.12; 12 of 12 for verifier-VDR2). With the lock all of it is 0 of 60 on both. The check asks for
    the three things together - every record in the file, none torn, in the order of its epochs - and is red without the lock on both
    hosts (every time on Windows, most times on POSIX), which is why the cause is checked as well. An earlier version of this
    docstring said that only Windows shows the symptom, and gave 4 damaged trials in 60 with no record lost: the script that
    measured that gave both of its passes' files one name, so the second pass appended to the first's and the duplicates hid the loss."""
    out: list = []
    tmp = tempfile.mkdtemp(prefix="cs-app-")
    real_write = os.write
    try:
        with lib_from(src) as L2:
            n_thr, rounds = 8, 12
            state = {"in": 0, "max": 0}
            mu = threading.Lock()

            def slow_write(fd, data):
                with mu:
                    state["in"] += 1
                    state["max"] = max(state["max"], state["in"])
                time.sleep(0.005)
                try:
                    return real_write(fd, data)
                finally:
                    with mu:
                        state["in"] -= 1

            def run(path):
                bar = threading.Barrier(n_thr)

                def work(k):
                    for i in range(rounds):
                        bar.wait()
                        L2.append_record(path, {"type": "t", "k": k, "i": i})
                ts = [threading.Thread(target=work, args=(k,)) for k in range(n_thr)]
                for t in ts:
                    t.start()
                for t in ts:
                    t.join(120)

            os.write = slow_write
            try:
                run(os.path.join(tmp, "slow.jsonl"))
            finally:
                os.write = real_write
            out.append(("pool: no two threads are ever inside the metrics file's write at once (eight threads, twelve rounds, the write "
                        "slowed to 5 ms: the most at once was one)", state["max"] == 1, f"{state['max']} writers at once"))
            path = os.path.join(tmp, "metrics.jsonl")
            run(path)
            recs, partial, bad = L2.read_records(path)
            got = sorted((r["k"], r["i"]) for r in recs)
            ep = [r["epoch"] for r in recs]
            out.append(("pool: records written by eight threads at one instant are all in the file, none torn, and in the order of their epochs",
                        got == [(k, i) for k in range(n_thr) for i in range(rounds)] and not bad and not partial and ep == sorted(ep),
                        f"{len(recs)} of {n_thr * rounds} records, bad {bad}"))
    finally:
        os.write = real_write
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def scn_pool_stop(env: Env, src: str = HERE) -> list:
    """STOP and the deadline end host jobs. A host job is in flight (nextup32's first slice hangs for ever) and another
    item's slices run all the while (logb32's, quick). A: STOP is touched during a card leg that takes 9 s. No host slice starts
    after it; the run ends when the card leg has, not when the hung job would have; the hung job is terminated and recorded
    as an EVENT and not as a slice (a killed slice recorded as a parse_error would count toward disabling its item). B: the
    same with the deadline."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    base = POOL_BASE + ["--sweep-items", "nextup32,logb32", "--host-workers", "2"]
    base[base.index("--legs") + 1] = "dt-full"
    sc = [{"leg": "soak", "op": "nextup32", "nth": [1], "do": "hang"}, {"leg": "dt-full", "nth": [1], "do": "slow:9"}]
    r = start_driver(env, "poolstop", ["--until", until(180)] + base, sc, src=src, extra_env=POOL_RATE)
    log = os.path.join(r.out, "driver.log")
    began = wait_for(lambda: os.path.exists(log) and "leg dt-full on quad starts" in open(log).read()
                     and any(f.startswith("hang-soak-") for f in os.listdir(r.state)), 120)
    time.sleep(2.0)
    t_touch = time.time()
    n_before = len([x for x in r.legs(kind="sweep") if x["image"] == "cpu"])
    stop_run(r)
    r.finish(120)
    end = r.last("run_end") or {}
    host = [x for x in r.legs(kind="sweep") if x["image"] == "cpu"]
    pids = [int(open(os.path.join(r.state, f)).read()) for f in os.listdir(r.state) if f.startswith("hang-soak-")]
    ab = [e for e in r.events("host_job_abandoned")]
    c("pool stop: the host pool was working beside the card leg (logb32 slices recorded, nextup32's first hung) when STOP was touched",
      began and n_before >= 2 and len(pids) == 1, f"began {began}, {n_before} host slices before, {len(pids)} hung")
    c("pool stop: no host slice STARTED after STOP (a second of margin for a worker that had just passed its check)",
      began and not [x for x in host if x["start_epoch"] > t_touch + 1.0],
      str([(x["sweep"]["item"], round(x["start_epoch"] - t_touch, 1)) for x in host if x["start_epoch"] > t_touch + 1.0][:4]))
    c("pool stop: the run ended by STOP (exit 0) when the card leg had, nine seconds long, plus the pool's grace and a margin",
      r.rc == 0 and end.get("reason") == "stop_file" and end.get("epoch", 1e12) - t_touch <= 9 + 2 + 15,
      f"rc {r.rc}, {end.get('reason')}, {end.get('epoch', 0) - t_touch:.1f} s after STOP")
    c("pool stop: the hung host job was terminated (its process is gone) and is NOT a recorded slice: an event names it, no leg "
      "of nextup32 exists, and the item was neither disabled nor quarantined",
      bool(pids) and not any(pid_alive(p) for p in pids) and len(ab) == 1 and "nextup32" in ab[0]["detail"]
      and not [x for x in host if x["sweep"]["item"] == "nextup32"]
      and not r.events("item_disabled") and not r.events("quarantine"), f"{len(ab)} events, {[x['sweep']['item'] for x in host][:3]}")
    # B: the deadline
    sc2 = [{"leg": "soak", "op": "nextup32", "nth": [1], "do": "hang"}]
    t0 = time.time()
    deadline = t0 + 14
    r2 = start_driver(env, "pooldeadline", ["--until", until(14)] + POOL_BASE + ["--sweep-items", "nextup32,logb32", "--host-workers", "2"],
                      sc2, src=src, extra_env=POOL_RATE)
    r2.finish(120)
    end2 = r2.last("run_end") or {}
    host2 = [x for x in r2.legs(kind="sweep") if x["image"] == "cpu"]
    pids2 = [int(open(os.path.join(r2.state, f)).read()) for f in os.listdir(r2.state) if f.startswith("hang-soak-")]
    c("pool deadline: the run ended at the deadline (exit 0), no host slice started after it, and the hung job was terminated "
      "and recorded as an event and not as a slice",
      r2.rc == 0 and end2.get("reason") == "deadline" and end2.get("epoch", 1e12) - deadline <= 20
      and not [x for x in host2 if x["start_epoch"] > deadline + 1.0] and len(host2) >= 2
      and len(pids2) == 1 and not any(pid_alive(p) for p in pids2) and len(r2.events("host_job_abandoned")) == 1
      and not [x for x in host2 if x["sweep"]["item"] == "nextup32"],
      f"rc {r2.rc}, {end2.get('reason')}, {end2.get('epoch', 0) - deadline:.1f} s past it, {len(host2)} host slices")
    return out


def git_in(repo, *args):
    """git run in `repo` with its identity given on the command line, so that nobody's configuration is read for it or changed."""
    return subprocess.run(["git", "-c", "user.name=card-stress-test", "-c", "user.email=card-stress-test@example.invalid",
                           "-c", "commit.gpgsign=false", "-C", repo] + list(args), capture_output=True, text=True, timeout=60)


# the files the driver's build step looks into at --root, for the marker strings that tell it a tree is not stale (a driver
# started on a scratch repository without them ends at the build step, "build_failed")
MARKER_FILES = ("host/tests/seq_check.py", "programs/acceptance.py", "hw/card-segrun.sh", "hw/card_stress.py")


def make_scratch_repo(path, copy=()):
    """A repository of its own with one commit (the files of `copy`, copied from this tree, or empty), for a test that moves
    HEAD; None where git cannot make one."""
    try:
        os.makedirs(path, exist_ok=True)
        if subprocess.run(["git", "init", "-q", path], capture_output=True, text=True, timeout=60).returncode != 0:
            return None
        for rel in copy:
            os.makedirs(os.path.dirname(os.path.join(path, rel)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, rel), os.path.join(path, rel))
        if copy and git_in(path, "add", "-A").returncode != 0:
            return None
        return path if git_in(path, "commit", "-q", "--allow-empty", "-m", "first").returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def pool_tree_unit_checks(src: str = HERE) -> list:
    """A moved tree stops the host pool's workers (parcel DR2, after verifier-VDR2's (b-1): the records said so and the workers asked
    should_stop(git=False)). In-process, on Drivers that are never run, rooted in a scratch repository with the tree test switched on
    (--check-tree-in-dry-run: a plain dry run has it off by design) whose HEAD this test moves. The main loop's test says tree_moved;
    a worker started after the move plans nothing and returns at once, and has latched the same stop."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    tmp = tempfile.mkdtemp(prefix="cs-tree-")
    repo = make_scratch_repo(os.path.join(tmp, "repo"))
    if repo is None:
        skip("pool tree (unit)", "git cannot make a scratch repository on this host")
        rmtree_force(tmp)
        return []
    sys.path.insert(0, src)
    saved_lib = sys.modules.pop("card_stress_lib", None) if os.path.abspath(src) != os.path.abspath(HERE) else None
    try:
        mod = importlib.import_module("card_stress")
        L2 = mod.L

        def driver(name, *extra):
            d = mod.Driver(mod.parse_args(["--out", os.path.join(tmp, name), "--dry-run", "--root", repo] + list(extra)))
            os.makedirs(d.out, exist_ok=True)
            d.items = L2.sweep_items()
            d.head = d.git_head()
            return d
        dm, dw, dp = driver("main", "--check-tree-in-dry-run"), driver("worker", "--check-tree-in-dry-run"), driver("plain")
        before = [dm.should_stop(), dw.should_stop()]
        moved = git_in(repo, "commit", "-q", "--allow-empty", "-m", "second").returncode == 0 and dm.git_head() != dm.head
        sm = dm.should_stop()
        t = threading.Thread(target=dw.pool_worker, args=(1,), daemon=True)
        t.start()
        t.join(5)
        returned = not t.is_alive()
        dw.pool_stop.set()                     # (only a worker that did not return needs this)
        t.join(10)
        sp = dp.should_stop()
        c("pool tree: before HEAD moves no driver is told to stop (git is on, in a scratch repository, so the checks below can fail)",
          before == [None, None] and bool(dm.head) and dm.tree_check and dw.tree_check, f"{before}, head {dm.head[:12]}")
        c("pool tree: the main loop's test says tree_moved, exit 3, once HEAD has moved",
          moved and sm is not None and sm.reason == "tree_moved" and sm.exit_code == 3, f"moved {moved}, {sm and (sm.reason, sm.exit_code)}")
        c("pool tree: a worker started after HEAD moved plans nothing and returns at once, having latched the same stop (no host slice starts)",
          returned and not dw.pool_busy and not dw.served and dw.pool_served == 0 and dw.tree_stop is not None
          and dw.tree_stop.reason == "tree_moved", f"returned {returned}, busy {list(dw.pool_busy)}, latched {dw.tree_stop and dw.tree_stop.reason}")
        c("pool tree: a plain --dry-run does not test the tree, by design (its --root may be a checkout somebody is committing to)",
          sp is None and not dp.tree_check, f"{sp}")
    except Exception as e:                     # a driver that cannot be driven this way is a red check, not a crash
        c("pool tree: the driver could be driven in-process", False, repr(e))
    finally:
        sys.path.remove(src)
        sys.modules.pop("card_stress", None)
        if saved_lib is not None:
            sys.modules["card_stress_lib"] = saved_lib
        rmtree_force(tmp)
    c("pool tree: the scratch repository is removed afterwards (git's object files are read-only, which keeps a plain rmtree from "
      "removing it on Windows)", not os.path.exists(tmp), tmp)
    return out


def scn_pool_tree(env: Env, src: str = HERE) -> list:
    """A moved tree stops the host pool, as a process (parcel DR2, after verifier-VDR2's (b-1)). git is ENABLED - a dry run has the tree
    test off unless --check-tree-in-dry-run - and the driver's --root is a scratch repository whose HEAD this test moves while a card
    leg of 12 s is in flight. The main loop looks at the tree only between legs, so in those seconds only a worker's own test can stop
    the pool, which is running two quick host items all the while. After the commit no host slice may START; the run ends at the
    leg's end by tree_moved (exit 3), recorded as the main loop records any stop (one event, run_end's reason)."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    repo = make_scratch_repo(os.path.join(env.tmp, "treerepo"), MARKER_FILES)
    if repo is None:
        skip("pool tree", "git cannot make a scratch repository on this host")
        return []
    base = POOL_BASE + ["--sweep-items", "logb32,class32", "--host-workers", "2", "--root", repo, "--check-tree-in-dry-run"]
    base[base.index("--legs") + 1] = "dt-full"
    sc = [{"leg": "dt-full", "nth": [1], "do": "slow:12"}]
    r = start_driver(env, "pooltree", ["--until", until(180)] + base, sc, src=src, extra_env=POOL_RATE)
    log = os.path.join(r.out, "driver.log")
    began = wait_for(lambda: os.path.exists(log) and "leg dt-full on quad starts" in open(log).read()
                     and len([x for x in r.legs(kind="sweep") if x["image"] == "cpu"]) >= 3, 120)
    q = git_in(repo, "commit", "-q", "--allow-empty", "-m", "second")
    t_move = time.time()
    n_before = len([x for x in r.legs(kind="sweep") if x["image"] == "cpu"])
    if not wait_for(lambda: r.proc.poll() is not None, 30):      # the run ends by itself within the leg's seconds; a defect must
        stop_run(r)                                              # not make this wait for the deadline
    r.finish(120)
    end = r.last("run_end") or {}
    host = [x for x in r.legs(kind="sweep") if x["image"] == "cpu"]
    late = [x for x in host if x["start_epoch"] > t_move + 1.0]
    ev = r.events("tree_moved")
    c("pool tree: the pool was working beside the card's 12-second leg when HEAD moved (three host slices already recorded)",
      began and q.returncode == 0 and n_before >= 3, f"began {began}, commit rc {q.returncode}, {n_before} host slices before")
    c("pool tree: after HEAD moved no host slice STARTED (a second of margin for a worker that had just passed its check), though the "
      "card's leg went on for seconds more",
      began and not late, str([(x["sweep"]["item"], round(x["start_epoch"] - t_move, 1)) for x in late][:5]))
    c("pool tree: the run ended by tree_moved at the main loop's next check, exit 3, recorded as it records any stop: one event "
      "tree_moved and run_end's reason tree_moved",
      r.rc == 3 and end.get("reason") == "tree_moved" and end.get("exit") == 3 and len(ev) == 1,
      f"rc {r.rc}, run_end {end.get('reason')}, {len(ev)} events")
    return out


def scn_pool_failure(env: Env, src: str = HERE) -> list:
    """A host job's failure is its item's, never the card's. Every nextup32 job prints the tool's 'no such device' and exits 2
    (what makes a CARD leg no_device and counts toward stopping the run); logb32's first slice disagrees with the oracle.
    --max-card-failures is 2, so the card's rule, applied to a host job, would stop this run in its second slice."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sc = [{"leg": "soak", "op": "nextup32", "from": 1, "do": "nodevice"}, {"leg": "soak", "op": "logb32", "nth": [1], "do": "mismatch"}]
    R = run_driver(env, "poolfail", ["--until", until(14)] + POOL_BASE + ["--sweep-items", "nextup32,logb32,class32", "--host-workers", "3",
                                                                          "--max-card-failures", "2", "--quarantine-after", "2"],
                   sc, src=src, cap=120, extra_env=POOL_RATE)
    host = [x for x in R.legs(kind="sweep") if x["image"] == "cpu"]
    nu = [x for x in host if x["sweep"]["item"] == "nextup32"]
    lb = sorted((x for x in host if x["sweep"]["item"] == "logb32"), key=lambda x: x["start_epoch"])
    st = open(os.path.join(R.out, "status.txt")).read()
    c("pool failure: the run was not stopped by its host jobs failing: it ran to its deadline (exit 0, no STOPPED.txt), "
      "though --max-card-failures is 2",
      R.rc == 0 and (R.last("run_end") or {}).get("reason") == "deadline" and not os.path.exists(os.path.join(R.out, "STOPPED.txt")),
      f"rc {R.rc}: {R.text[-200:]}")
    c("pool failure: a host job that prints 'no such device' is a parse_error of ITS item - never no_device - three times, "
      "and then the item is disabled, recorded, and the pool goes on with the others",
      len(nu) == 3 and all(x["status"] == "parse_error" for x in nu) and len(R.events("item_disabled")) == 1
      and "nextup32" in R.events("item_disabled")[0]["detail"] and len([x for x in host if x["status"] == "pass"]) >= 3,
      str([(x["status"], x["reason"]) for x in nu][:3]))
    c("pool failure: nor did it start the card's recovery ladder (no pause, no image switch), and the card's streak is 0",
      not R.events("pause") and not R.events("recover_start") and not R.events("image_switch")
      and re.search(r"^card\s+consecutive failures 0 of 2$", st, re.M) is not None, st[st.find("card "):][:80])
    c("pool failure: a host job that disagrees with the oracle is a recorded disagreement (status fail, with its operands) and "
      "the slice counts as covered; the next slice of the item passes",
      len(lb) >= 2 and lb[0]["status"] == "fail" and lb[0]["disagreements"] and lb[1]["status"] == "pass"
      and "disagreements 1" in st, str([(x["status"]) for x in lb][:3]))
    api = R.legs("api-test")
    c("pool failure: the card's own legs were not touched: there were api-test legs and every one passed",
      len(api) >= 1 and all(x["status"] == "pass" for x in api), f"{len(api)} legs: {sorted({x['status'] for x in api})}")
    return out


def scn_pool_survives(env: Env, src: str = HERE) -> list:
    """A failure in the CARD's cycle must not take the host pool's jobs with it. The cycle's tally raises once (the fault of
    scn_internal_error: the driver records driver_error, terminates what the card side started, and goes on); a host job is in
    flight meanwhile (nextup32's first slice takes 9 s). It must run to its end and be recorded as a pass, not be killed with the
    card's children and recorded as a failure of its item."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    if src == HERE:
        src = make_plant_copy(env, "inject-pool", INJECT)
    base = list(POOL_BASE)
    base[base.index("--legs") + 1] = "api-test,dt-i"
    R = run_driver(env, "poolsurvive", ["--until", until(26)] + base + ["--sweep-items", "nextup32", "--host-workers", "1"],
                   [{"leg": "soak", "op": "nextup32", "nth": [1], "do": "slow:9"}], src=src, cap=120, extra_env=POOL_RATE)
    first = sorted((x for x in R.legs(kind="sweep") if x["image"] == "cpu"), key=lambda x: x["start_epoch"])[:1]
    err = R.events("driver_error")
    c("pool survives: the card's cycle failed (one driver_error, its traceback recorded) while a host job was in flight",
      len(err) == 1 and "injected fault" in err[0]["detail"] and bool(first) and first[0]["start_epoch"] < err[0]["epoch"] < first[0]["end_epoch"],
      f"{len(err)} driver_error events; first host slice {[(x['start_epoch'], x['end_epoch']) for x in first]}")
    c("pool survives: the host job in flight when the card's cycle failed ran to its end and is a recorded PASS (not killed with the "
      "card's children and recorded as a failure of its item), and the run went on to its deadline",
      bool(first) and first[0]["status"] == "pass" and not first[0]["killed"] and first[0]["duration_s"] >= 8.5
      and R.rc == 0 and (R.last("run_end") or {}).get("reason") == "deadline" and not R.events("item_disabled"),
      f"rc {R.rc}: {first[:1]}")
    return out


def scn_pool_nice(env: Env, src: str = HERE) -> list:
    """POSIX: a host job is niced and under `timeout` like every leg (the stand-in prints how it was started). Skipped by name on
    Windows, which has neither."""
    if not POSIX:
        skip("pool nice", "needs POSIX (`nice` and `timeout`)")
        return []
    R = run_driver(env, "poolnice", ["--quick", "--legs", "api-test", "--sweep-items", "nextup32,rem32", "--host-workers", "2"],
                   src=src, cap=120)
    host = [x for x in R.legs(kind="sweep") if x["image"] == "cpu"]
    want = min(19, os.nice(0) + 10)          # `nice -n 10` adds to the caller's niceness
    return [(f"pool nice (POSIX): a host job runs at `nice -n 10` (this test's own niceness {os.nice(0)} + 10, at most 19: {want}) and under "
             f"`timeout --signal=TERM -k 2 <secs>s`, like every leg",
             len(host) == 2 and all(f"standin: nice {want}" in log_text(R, x)
                                    and re.search(r"standin: parent: timeout --signal=TERM -k 2 \d+s ", log_text(R, x)) is not None for x in host),
             str([log_text(R, x)[:300] for x in host][:1]))]


def scn_pool_resume(env: Env, src: str = HERE) -> list:
    """--resume holds for the pool: a run stopped after some host slices is continued from the records alone - the next slice is
    the first uncovered one, nothing is run twice, and the rate measured on the cpu image is rebuilt (the first slice is not the
    probe size again)."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    args = POOL_BASE + ["--sweep-items", "nextup32", "--host-workers", "1", "--sweep-slice-seconds", "4"]
    A = start_driver(env, "poolresA", ["--until", until(120)] + args, src=src, extra_env=POOL_RATE)
    wait_for(lambda: len([x for x in A.legs(kind="sweep", status="pass") if x["image"] == "cpu"]) >= 3, 90)
    stop_run(A)
    A.finish(60)
    passA = [x for x in A.legs(kind="sweep", status="pass") if x["image"] == "cpu"]
    covA = max((x["sweep"]["hi"] for x in passA), default=0)
    c("pool resume: run A served at least three host slices of nextup32, the first the probe size, from 0",
      len(passA) >= 3 and passA[0]["sweep"]["lo"] == 0 and passA[0]["sweep"]["hi"] == 1 << 20, f"{len(passA)} slices")
    if len(passA) < 3:
        return out
    os.remove(os.path.join(A.out, "STOP"))               # a stale STOP would refuse the resume, by design
    env.n += 1
    cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", A.out, "--resume", "--dry-run",
           "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1", "--guard-poll", "1", "--until", until(14)] + args
    for nm, pth in env.imgs.items():
        cmd += ["--image", f"{nm}={pth}"]
    e = dict(os.environ)
    e.update(POOL_RATE)
    e["CFT_STANDIN_STATE"] = A.state
    e.pop("CFT_STANDIN_SCENARIO", None)
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT, timeout=150)
    R = Run(A.out)
    recs = R.recs
    second = [i for i, x in enumerate(recs) if x.get("type") == "run_start"][1]
    after = [x for x in recs[second:] if x.get("type") == "leg" and x["kind"] == "sweep" and x["image"] == "cpu"]
    c("pool resume: the resumed run's first host slice starts exactly where run A's coverage ended, and passes",
      p.returncode == 0 and bool(after) and after[0]["status"] == "pass" and after[0]["sweep"]["lo"] == covA,
      f"rc {p.returncode}; A covered to {covA}; B's first {after[0]['sweep'] if after else None}")
    allpass = [x for x in recs if x.get("type") == "leg" and x["kind"] == "sweep" and x["image"] == "cpu" and x["status"] == "pass"]
    iv = [(x["sweep"]["lo"], x["sweep"]["hi"]) for x in allpass]
    merged = L.merge_intervals(iv)
    c("pool resume: after it the passing host slices are one contiguous range from 0, longer than A's, and no range was run twice",
      len(merged) == 1 and merged[0][0] == 0 and merged[0][1] > covA and sum(h - l for l, h in iv) == merged[0][1], str(merged[:3]))
    c("pool resume: the rate measured on cpu was rebuilt from the records (B's first slice is not the probe size again)",
      bool(after) and after[0]["sweep"]["hi"] - after[0]["sweep"]["lo"] != 1 << 20, str([x["sweep"]["hi"] - x["sweep"]["lo"] for x in after][:3]))
    return out


def seed_checks(src: str = HERE) -> list:
    """The seed schedule, shown with the method of docs/studies/swp-a/seed_audit.py over the driver's own catalog: the tool
    starts from state = seed | 1, and no two (item, n) may start it from one state."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    with lib_from(src) as L2:
        rnd = [it for it in L2.sweep_items() if it.kind == "random"]
        c("seeds: the index table is the catalog's 54 random items, by name, in the catalog's order, each once; item i has index i",
          [it.name for it in rnd] == list(L2.RANDOM_SEED_ORDER) and len(set(L2.RANDOM_SEED_ORDER)) == 54
          and [it.seed_index for it in rnd] == list(range(54)))
        probed = {it.name: it.seed_index for it in L2.sweep_items(("rne",), ("rne",)) if it.seed_index is not None}
        c("seeds: an item's seeds do not depend on which other items exist: a run whose probes dropped the directed scaleB and cvtFrom "
          "modes (fewer than the 54 random items, some) gives every item it still has the same index",
          0 < len(probed) < 54 and all(L2.RANDOM_SEED_INDEX[n] == i for n, i in probed.items()), f"{len(probed)} random items")
        ns = list(range(600)) + [10 ** 5, 10 ** 6, 2 ** 20, 2 ** 31, 2 ** 38]
        states: dict = {}
        for it in rnd:
            for n in ns:
                states.setdefault(it.seed_for(n) | 1, []).append((it.name, n))
        c("seeds: over the 54 random items x 605 slice numbers (to 2^38) no two (item, n) start the tool from one state "
          "(seed_audit.py's method: count the states the tool's `| 1` leaves)", len(states) == 54 * len(ns),
          f"{len(states)} states for {54 * len(ns)} slices; shared: {[v for v in states.values() if len(v) > 1][:2]}")
        c("seeds: every seed is odd, so the tool's `| 1` changes nothing, and fits the 64 bits strtoull reads",
          all(it.seed_for(n) % 2 == 1 and it.seed_for(n) < 2 ** 64 for it in rnd for n in ns))
        old: dict = {}
        for it in rnd:
            for n in range(57):
                old.setdefault((it.base_seed + 7919 * n) | 1, []).append((it.name, n))
        shared_old = sum(len(v) for v in old.values() if len(v) > 1)
        c("seeds: CONTROL, the same method on the schedule before 2026-10-20 (base_seed + 7919 n, 54 items x n = 0..56, the grid of "
          "seed_audit.py) finds 2,962 of 3,078 slices on a shared state, as the study did: the check can fail",
          shared_old == 2962 and len(old) == 1597, f"{shared_old} slices shared, {len(old)} states")
        try:
            rnd[0].seed_for(2 ** 39)
            refused = None
        except ValueError as e:
            refused = str(e)
        c("seeds: a slice number the seed has no room for is refused, by name", refused is not None and rnd[0].name in refused, str(refused))
        saved = dict(L2.RANDOM_SEED_INDEX)
        try:
            del L2.RANDOM_SEED_INDEX["rem32"]
            try:
                L2.sweep_items()
                unnamed = None
            except ValueError as e:
                unnamed = str(e)
        finally:
            L2.RANDOM_SEED_INDEX.clear()
            L2.RANDOM_SEED_INDEX.update(saved)
        c("seeds: a random item missing from the table is refused by name when the catalog is built (append it, never insert)",
          unnamed is not None and "rem32" in unnamed and "RANDOM_SEED_ORDER" in unnamed, str(unnamed))
    return out


def scn_seeds(env: Env, src: str = HERE) -> list:
    """The seeds across runs, as processes (parcel DR2). A: a fresh run draws each item from n = 0 with the new seeds. B: a new
    --out that NAMES A (--earlier-runs) starts every item above A's highest n, so no seed repeats. C: a named directory that is
    no run is refused by name, before anything starts. D: a run made by the schedule before 2026-10-20 (the old formula, the
    collisions the study measured in it) is RESUMED by this driver: its new slices continue the n, meet none of the old states,
    and say seed_scheme 2."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    def rnd(R):
        return [x for x in R.legs(kind="sweep") if "seed_n" in x["sweep"]]

    items = "div32-rne,div32-rtz"
    qargs = ["--quick", "--legs", "api-test", "--sweep-items", items]
    idx = {n: i for i, n in enumerate(L.RANDOM_SEED_ORDER)}          # the table as this test knows it: by name
    A = run_driver(env, "seedsA", qargs, src=src, cap=150)
    sa = rnd(A)
    na = {}
    for x in sa:
        na.setdefault(x["sweep"]["item"], []).append(x["sweep"]["seed_n"])
    c("seeds A: a fresh run draws both items from n = 0, contiguous, each seed (item index << 40) | (n << 1) | 1 as the test computes it, "
      "and the record says seed_scheme 2",
      len(sa) == 6 and all(sorted(v) == list(range(len(v))) for v in na.values()) and set(na) == set(items.split(","))
      and all(x["sweep"]["seed"] == (idx[x["sweep"]["item"]] << 40) | (x["sweep"]["seed_n"] << 1) | 1 and x["sweep"]["seed_scheme"] == 2
              for x in sa), f"{len(sa)} slices, n by item {na}")
    maxa = {k: max(v) for k, v in na.items()}
    B = run_driver(env, "seedsB", qargs + ["--earlier-runs", A.out], src=src, cap=150)
    sb = rnd(B)
    nb = {}
    for x in sb:
        nb.setdefault(x["sweep"]["item"], []).append(x["sweep"]["seed_n"])
    rsb = B.recs[0] if B.recs else {}
    c("seeds B: a new --out naming run A starts each item at A's highest n + 1 and goes on contiguously",
      len(sb) == 6 and all(sorted(v) == list(range(maxa[k] + 1, maxa[k] + 1 + len(v))) for k, v in nb.items()), f"A's max {maxa}, B's n {nb}")
    c("seeds B: run_start says which runs were named and the first n each item got from them",
      (rsb.get("earlier_runs") or {}).get("first_n") == {k: v + 1 for k, v in maxa.items()}
      and [d["dir"] for d in (rsb.get("earlier_runs") or {}).get("dirs", [])] == [A.out], str(rsb.get("earlier_runs"))[:300])
    st_a = {x["sweep"]["seed"] | 1 for x in sa}
    st_b = {x["sweep"]["seed"] | 1 for x in sb}
    c("seeds B: no seed of B is a seed of A: the tool's states (seed | 1) of the two runs are twelve different ones",
      len(st_a) == 6 and len(st_b) == 6 and not st_a & st_b, f"{len(st_a)} + {len(st_b)} states, common {sorted(st_a & st_b)[:2]}")
    # C: refused by name
    empty = os.path.join(env.tmp, "not-a-run")
    os.makedirs(empty, exist_ok=True)
    damaged = os.path.join(env.tmp, "damaged-run")
    os.makedirs(damaged, exist_ok=True)
    with open(os.path.join(damaged, "metrics.jsonl"), "w") as fh:
        fh.write('{"type":"run_start"}\nthis line is not json\n')
    C1 = run_driver(env, "seedsC1", qargs + ["--earlier-runs", empty], src=src, cap=60)
    C2 = run_driver(env, "seedsC2", qargs + ["--earlier-runs", damaged], src=src, cap=60)
    C3 = run_driver(env, "seedsC3", qargs + ["--earlier-runs", A.out + "-no-such"], src=src, cap=60)
    c("seeds C: a named directory with no metrics.jsonl is refused by name (exit 2), the directory and the file named, and nothing started",
      C1.rc == 2 and empty in C1.text and "no metrics.jsonl" in C1.text and not os.path.exists(os.path.join(C1.out, "metrics.jsonl")),
      f"rc {C1.rc}: {C1.text[-300:]}")
    c("seeds C: so are a directory whose metrics.jsonl has a line that does not parse, and one that does not exist",
      C2.rc == 2 and damaged in C2.text and "do not parse" in C2.text and C3.rc == 2 and "not a directory" in C3.text,
      f"{C2.rc}: {C2.text[-200:]} | {C3.rc}: {C3.text[-200:]}")
    # D: a run made by the old schedule, resumed by this driver
    edits = [("card_stress_lib.py", "        return (self.seed_index << 40) | (n << 1) | 1\n", "        return self.base_seed + 7919 * n\n"),
             ("card_stress.py", "                if prior is not None and prior != (it.name, n):\n", "                if False:\n"),
             ("card_stress.py", '                                "seed_scheme": L.SEED_SCHEME, "tile": None}', '                                "tile": None}')]
    old_src = make_plant_copy(env, "oldseeds", edits)       # a copy of the code as it was: the old seeds, no guard, no marker
    names4 = "div32-rne,div32-rtz,div32-rdn,div32-rup"
    O = run_driver(env, "seedsOld", ["--quick", "--legs", "api-test", "--sweep-items", names4], src=old_src, cap=150)
    so = rnd(O)
    old_states = [x["sweep"]["seed"] | 1 for x in so]
    c("seeds D: the run made by the old schedule is what the study found: old seeds (base_seed + 7919 n), no seed_scheme, and two items "
      "that started the tool from one state", len(so) == 8 and all("seed_scheme" not in x["sweep"] for x in so)
      and len(set(old_states)) < len(old_states), f"{len(so)} slices, {len(set(old_states))} states")
    maxo = {}
    for x in so:
        maxo[x["sweep"]["item"]] = max(maxo.get(x["sweep"]["item"], -1), x["sweep"]["seed_n"])
    env.n += 1
    cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", O.out, "--resume", "--dry-run",
           "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1", "--kill-after", "2", "--guard-poll", "1",
           "--quick", "--legs", "api-test", "--sweep-items", names4]
    for nm, pth in env.imgs.items():
        cmd += ["--image", f"{nm}={pth}"]
    e = dict(os.environ)
    e["CFT_STANDIN_STATE"] = O.state
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, cwd=ROOT, timeout=150)
    R2 = Run(O.out)
    sr = [x for x in rnd(R2) if "seed_scheme" in x["sweep"]]
    new_states = [x["sweep"]["seed"] | 1 for x in sr]
    nr = {}
    for x in sr:
        nr.setdefault(x["sweep"]["item"], []).append(x["sweep"]["seed_n"])
    c("seeds D: this driver resumed the old run (exit 0, no driver_error), continued every item's n from the old run's highest + 1 "
      "(not from 0), and the new slices say seed_scheme 2",
      p.returncode == 0 and not R2.events("driver_error") and len(sr) >= 8 and set(nr) == set(names4.split(","))
      and all(sorted(v) == list(range(maxo[k] + 1, maxo[k] + 1 + len(v))) for k, v in nr.items()), f"rc {p.returncode}: n {nr}, old max {maxo}: {p.stdout[-200:]}")
    c("seeds D: and the new seeds are safe beside the old: the new slices' states are all different from each other and from every old "
      "state, though the old ones collide among themselves",
      len(set(new_states)) == len(new_states) > 0 and not set(new_states) & set(old_states), f"{len(new_states)} new, {len(set(old_states))} old")
    return out


# ---- coverage by tree: a synthetic pair of runs with known truth ----

TREE_A = {"commit": "a" * 40, "dirty": False, "dirty_files": 0, "rtl": "1" * 40, "rtl_dirty": False, "host_src": "2" * 40,
          "host_src_dirty": False, "cc": "gcc (fixture) 11.4.0"}
TREE_B = {"commit": "b" * 40, "dirty": False, "dirty_files": 0, "rtl": "3" * 40, "rtl_dirty": False, "host_src": "2" * 40,
          "host_src_dirty": False, "cc": "gcc (fixture) 12.2.0"}          # another RTL tree, the same host/ tree, another compiler
TREE_OLD = {"commit": "c" * 40, "dirty": False, "dirty_files": 0}      # a run from before 2026-10-20: it recorded no tree
M20, M28 = 1 << 20, 1 << 28


def tree_fixture(path: str, parts: list) -> None:
    """A metrics.jsonl: for each part (tree, [slice, ...]) a run_start naming the tree, then the slices, all passing. A slice is
    (image, item, op, reach, lo, hi) for an exhaustive item or (image, item, op, reach, n, count) for a random one."""
    recs = []
    t = 1_800_000_000.0
    for k, (tree, slices) in enumerate(parts):
        t += 10
        recs.append({"type": "run_start", "v": 1, "ts": L.iso(t), "epoch": t, "run_id": f"fixture-{k}", "host": "fixture", "out": path,
                     "argv": [], "settings": {"until": None, "quick": False, "dry_run": True}, "tree": tree,
                     "images": {n: {"sha256": "0" * 64, "bytes": 1, "tiles": 1, "path": "x", "target": "t"} for n in ("quad", "single", "deep")},
                     "deadline": None, "resumed": k > 0})
        for (image, item, op, reach, a, b) in slices:
            t += 5
            sw = {"item": item, "tool": "clause5", "op": op, "mode": "rne", "reach": reach, "tile": None}
            if item.startswith("div32"):
                sw.update(count=b, seed=(a << 1) | 1, seed_n=a, seed_scheme=2)
                cases = b
            else:
                sw.update(lo=a, hi=b)
                cases = b - a
            recs.append({"type": "leg", "v": 1, "ts": L.iso(t), "epoch": t, "cycle": 1, "image": image, "image_sha256": None,
                         "leg": f"sweep-{item}", "kind": "sweep", "attempt": 1, "start": L.iso(t - 4), "end": L.iso(t),
                         "start_epoch": t - 4, "end_epoch": t, "duration_s": 4.0, "rc": 0, "status": "pass", "timed_out": False,
                         "killed": None, "counts": {"cases": cases, "value_mismatches": 0, "flag_mismatches": 0},
                         "rate": {"value": cases / 4.0, "unit": "cases/s"}, "sweep": sw, "disagreements": None, "log": None,
                         "log_kept": "none", "reason": None, "tile": None, "extra": None})
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def union_len(iv: list) -> int:
    """The length of a union of [lo, hi) intervals, counted here by plain sorting (not by the library's code)."""
    n, end = 0, -1
    for lo, hi in sorted(iv):
        if hi > max(lo, end):
            n += hi - max(lo, end)
            end = hi
    return n


def tree_record_checks(env: Env, src: str = HERE) -> list:
    """The driver records the tree it runs from (parcel DR2): rtl and host/ tree hashes, whether each is modified, and the compiler,
    read here by the test's own git commands. Skipped by name where git cannot read this tree at all (a worktree whose .git file
    names a Windows path, read from WSL: the driver then records nothing, honestly, and there is nothing to compare)."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    if git_out("rev-parse", "HEAD:rtl") is None:
        skip("trees: run_start records the tree", "git cannot read this tree on this host (a worktree whose .git file names a Windows path, "
             "read from WSL), so the driver records none and there is nothing to compare it with")
        return []
    R = run_driver(env, "treerec", ["--quick", "--legs", "api-test", "--no-sweep"], src=src, cap=150)
    tr = (R.recs[0] if R.recs else {}).get("tree") or {}
    dirty_rtl = git_out("status", "--porcelain", "--untracked-files=all", "--", "rtl")
    dirty_host = git_out("status", "--porcelain", "--untracked-files=all", "--", "host")
    want_cc = None
    try:
        p = subprocess.run([os.environ.get("CC", "cc"), "--version"], capture_output=True, text=True, timeout=30)
        want_cc = (p.stdout or p.stderr).strip().splitlines()[0].strip() if p.returncode == 0 and (p.stdout or p.stderr).strip() else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    c("trees: run_start records the tree the driver runs from: git rev-parse HEAD:rtl and HEAD:host as this test reads them, whether "
      "each is modified, and the compiler's version line",
      tr.get("rtl") == git_out("rev-parse", "HEAD:rtl") and tr.get("host_src") == git_out("rev-parse", "HEAD:host")
      and tr.get("rtl_dirty") == bool(dirty_rtl) and tr.get("host_src_dirty") == bool(dirty_host) and tr.get("cc") == want_cc
      and bool(tr.get("rtl")), str(tr))
    return out


def scn_trees(env: Env, src: str = HERE) -> list:
    """Coverage kept apart by tree (parcel DR2). (1) The driver records the tree it runs from: rtl and host/ tree hashes, whether each is
    modified, and the compiler, read here by the test's own git commands. (2) The report counts a tile item's coverage per RTL tree
    with the images beneath, and a host item's per host/ tree and compiler, on a synthetic pair of runs whose truth is counted here:
    the other tree's slices are disjoint from the first tree's, so a report that summed trees would show it. (3) --also adds a
    second run directory to that section alone; a run that recorded no tree is kept apart by its commit."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    out += tree_record_checks(env, src)
    # (2)
    d1 = os.path.join(env.tmp, "trees-d1")
    d2 = os.path.join(env.tmp, "trees-d2")
    os.makedirs(d1, exist_ok=True)
    os.makedirs(d2, exist_ok=True)
    S = "sqrt32-rne"
    P1 = [(TREE_A, [("quad", S, "sqrt32", "tile", 0, M28), ("single", S, "sqrt32", "tile", M28, M28 + M20), ("deep", S, "sqrt32", "tile", 0, M20),
                    ("quad", "rint32-rne", "rint32", "tile", 0, M20),
                    ("quad", "div32-rne", "div32", "tile", 0, 1000), ("single", "div32-rne", "div32", "tile", 1, 500),
                    ("cpu", "nextup32", "nextup32", "host", 0, M20)]),
          (TREE_B, [("quad", S, "sqrt32", "tile", M28 + M20, M28 + 2 * M20), ("cpu", "nextup32", "nextup32", "host", M20, 2 * M20)])]
    P2 = [(TREE_A, [("quad", S, "sqrt32", "tile", M28 + 2 * M20, M28 + 3 * M20), ("cpu", "nextup32", "nextup32", "host", 2 * M20, 3 * M20)]),
          (TREE_OLD, [("quad", S, "sqrt32", "tile", 0, M20), ("quad", "nextup32", "nextup32", "host", 0, M20)])]
    tree_fixture(os.path.join(d1, "metrics.jsonl"), P1)
    tree_fixture(os.path.join(d2, "metrics.jsonl"), P2)
    rp = os.path.join(src, "card_stress_report.py")             # src is HERE, or a plant's copy of the code
    jp = os.path.join(env.tmp, "trees.json")

    def report(*extra):
        p = subprocess.run([sys.executable, "-B", "-I", rp, d1, "--no-write", "--json", jp] + list(extra), capture_output=True, text=True, timeout=120)
        try:
            js = json.load(open(jp, encoding="utf-8"))
        except (OSError, ValueError):
            js = {}
        return p, js

    def cls(js, kind):
        return [x for x in (js.get("sweep") or {}).get("trees", {}).get("classes", []) if x["kind"] == kind]

    def item(cl, name, which="exhaustive"):
        """The entry for an item in a class, or {} when there is no such class or item: a report that lost a class is a red
        check, not a crash."""
        return next((e for e in (cl or {}).get(which, []) if e["item"] == name), {})
    p1, j1 = report()
    tile, hostc = cls(j1, "tile"), cls(j1, "host")
    ta = next((x for x in tile if x["key"] == "1" * 40), {})
    tb = next((x for x in tile if x["key"] == "3" * 40), {})
    sa = item(ta, S) if ta else {}
    union_a = union_len([(0, M28), (M28, M28 + M20), (0, M20)])
    c("trees: a tile item's coverage is counted per RTL tree: two runs' trees are two classes, and nothing is summed across them",
      p1.returncode == 0 and len(tile) == 2 and ta and tb and item(tb, S).get("covered") == M20 and sa.get("covered") == union_a == M28 + M20,
      f"rc {p1.returncode}; {[(x['key'][:4], x['label']) for x in tile]}; A {sa.get('covered')} want {union_a}; B {item(tb, S).get('covered') if tb else None}")
    c("trees: and the images are reported separately beneath the tree: what quad, single and deep each covered ALONE (the quad's and "
      "the deep's overlap, so the tree's figure is their union and not their sum)",
      sa.get("by_image") == {"quad": M28, "single": M20, "deep": M20} and sa.get("covered") < sum(sa.get("by_image", {}).values())
      and ta.get("total", {}).get("by_image", {}).get("quad") == M28 + M20 and ta.get("images") == ["quad", "single", "deep"],
      str(sa.get("by_image")))
    dv = item(ta, "div32-rne", "random") if ta else {}
    c("trees: a random tile item has its slices, cases, highest seed_n and cases by image under the tree",
      dv.get("slices") == 2 and dv.get("cases") == 1500 and dv.get("max_seed_n") == 1 and dv.get("by_image") == {"quad": 1000, "single": 500}, str(dv))
    ha = next((x for x in hostc if x["key"].startswith("2" * 40) and "11.4.0" in x["key"]), {})
    hb = next((x for x in hostc if x["key"].startswith("2" * 40) and "12.2.0" in x["key"]), {})
    c("trees: a host item's coverage is counted by what it is about, the library's source (host/'s tree) AND the compiler: the same "
      "host/ tree under two compilers is two classes, on the cpu image",
      len(hostc) == 2 and item(ha, "nextup32").get("covered") == M20 and item(hb, "nextup32").get("covered") == M20
      and item(ha, "nextup32").get("by_image") == {"cpu": M20}, str([(x["key"][-12:], x["total"]) for x in hostc]))
    t1 = p1.stdout
    c("trees: the text says which key it uses (the RTL tree for tile items, the host/ tree and compiler for host items), names each "
      "class, and the header shows the tree's parts",
      "== SWEEP COVERAGE BY TREE ==" in t1 and "git rev-parse HEAD:rtl" in t1 and "host/" in t1 and "compiler" in t1
      and f"RTL tree {'1' * 12}" in t1 and f"RTL tree {'3' * 12}" in t1 and f"host/ tree {'2' * 12}, compiler gcc (fixture) 11.4.0" in t1
      and re.search(r"^tree\s+: commit a+ \(clean\), rtl 1{12}, host/ 2{12}, cc gcc \(fixture\) 11\.4\.0; commit b+", t1, re.M) is not None, t1[t1.find("== SWEEP COVERAGE BY TREE"):][:700])
    # (3)
    p2, j2 = report("--also", d2)
    tile2, host2 = cls(j2, "tile"), cls(j2, "host")
    ta2 = next((x for x in tile2 if x["key"] == "1" * 40), {})
    tb2 = next((x for x in tile2 if x["key"] == "3" * 40), {})
    to2 = [x for x in tile2 if x["key"].startswith("unrecorded:")]
    want_a2 = union_len([(0, M28 + M20), (M28 + 2 * M20, M28 + 3 * M20)])
    c("trees --also: a second run directory adds to the tree it ran on and to no other: tree A gains the second run's slice (a gap of "
      "tree B's range stays between them), tree B is as it was, and a run that recorded no tree is a class of its own, kept apart by its commit",
      p2.returncode == 0 and item(ta2, S).get("covered") == want_a2
      and item(tb2, S).get("covered") == M20 and len(to2) == 1 and "c" * 12 in to2[0]["label"] and item(to2[0], S).get("covered") == M20
      and len(tile2) == 3, f"rc {p2.returncode}; A {item(ta2, S).get('covered')} want {want_a2}; classes {[x['label'][:40] for x in tile2]}")
    ha2 = next((x for x in host2 if x["key"].startswith("2" * 40) and "11.4.0" in x["key"]), {})
    c("trees --also: a host item's second run on the same host/ tree and compiler adds to the same class (nextup32: two ranges, 2 x 2^20), "
      "and the old run's host slices (on the quad, before the pool) are their own class, by commit",
      item(ha2, "nextup32").get("covered") == 2 * M20 and len(host2) == 3 and any(x["key"].startswith("unrecorded:") for x in host2),
      str([(x["key"][-14:], item(x, "nextup32").get("covered")) for x in host2]))
    c("trees --also: the sections before it are of the first directory alone, as they were (the same legs line with and without)",
      re.search(r"^legs\s+: .*$", p1.stdout, re.M).group(0) == re.search(r"^legs\s+: .*$", p2.stdout, re.M).group(0))
    p3 = subprocess.run([sys.executable, "-B", "-I", rp, d1, "--no-write", "--also", os.path.join(env.tmp, "no-such-run")], capture_output=True,
                        text=True, timeout=60)
    c("trees --also: a directory with no metrics.jsonl is refused by name (exit 2)",
      p3.returncode == 2 and "no-such-run" in p3.stderr and "metrics.jsonl" in p3.stderr, f"rc {p3.returncode}: {p3.stderr[-200:]}")
    return out


# ---------------------------------------------------------------------------------------
# parcel DR3 (2026-10-21): the coverage wave's items, pass size and signed records, in the driver
# ---------------------------------------------------------------------------------------

M4, M5 = ("rne", "rtz", "rdn", "rup"), ("rne", "rtz", "rdn", "rup", "rmm")
# The documents' figures for the 35 index-based items (docs/CARDDAY.md; HC's and CL's VALIDATION entries), written out here and not
# read from the library: op -> (indices, k checks an index, attributes, reach, the (cases, skipped) of the whole space by attribute,
# None for k x indices and 0). The tool's own `hard-count` and whole-space runs (hw/card_stress_fixtures/count-*, cl-*) hold them.
DOC_INDEX = {
    "div32-hard": (21_235_788, 4, M4, "tile", {m: (64_346_592, 20_596_560) for m in M4}),
    "div64-hard": (289_685_696, 4, M4, "tile", {m: (812_489_184, 346_253_600) for m in M4}),
    "sqrt64-hard": (4_456_448, 1, M5, "tile", {m: (1_745_752, 2_710_696) for m in M5}),
    "conv64to32-class": (136_192, 1, M4, "host", None),
    "rint64-class": (35_840, 4, M5, "tile", None),
    "cvtto64-class": (40_768, 4, M5, "host", {"rne": (91_005, 72_067), "rtz": (91_484, 71_588), "rdn": (85_141, 77_931),
                                              "rup": (91_478, 71_594), "rmm": (90_986, 72_086)}),
    "cvtfrom64-class": (50_923, 1, M4, "host", None),
    "scaleb64-class": (72_648, 4, M4, "tile", None),
}
DOC_NAMES = [f"{op}-{m}" for op, v in DOC_INDEX.items() for m in v[2]]


def read_bytes(path: str) -> bytes:
    """A file's bytes, or b'' where it is not there: a check about a file a broken driver did not write must go red, not crash."""
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return b""


def raises_in(L2, fn) -> bool:
    """raises(), for the library a check imported itself (lib_from gives a module of its own, with its own VerdictError)."""
    try:
        fn()
    except L2.VerdictError:
        return True
    return False


def parse_ok_in(L2, fn):
    """parse_ok(), for the same."""
    try:
        return fn(), ""
    except L2.VerdictError as e:
        return None, str(e)


def fixture_index() -> dict:
    index = {}
    with open(os.path.join(FIX, "INDEX.txt"), "r", encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip() and not ln.startswith("#"):
                nm, rc, cmd = ln.rstrip("\n").split("\t", 2)
                index[nm] = (int(rc), cmd)
    return index


@contextlib.contextmanager
def driver_from(src: str, extra=()):
    """A Driver (never run) of the copy of the code in `src`, in a scratch directory: (module, driver, lib). A plant's copy has its own
    library and its own sweep_record.py, which the driver imports when --records is asked for, and python/ (cft_sign, cft_golden) is
    where the real tree has it."""
    pydir = os.path.join(ROOT, "python")
    plant = os.path.abspath(src) != os.path.abspath(HERE)
    sys.path.insert(0, src)
    sys.path.insert(1, pydir)
    saved = {k: sys.modules.pop(k, None) for k in ("card_stress_lib", "sweep_record")} if plant else {}
    tmp = tempfile.mkdtemp(prefix="cs-dr3-")
    try:
        mod = importlib.import_module("card_stress")
        d = mod.Driver(mod.parse_args(["--out", os.path.join(tmp, "o"), "--dry-run", "--root", ROOT] + list(extra)))
        d.items = mod.L.sweep_items()
        d.rate = {}
        yield mod, d, mod.L
    finally:
        sys.path.remove(src)
        sys.path.remove(pydir)
        sys.modules.pop("card_stress", None)
        if plant:
            sys.modules.pop("sweep_record", None)
            for k, v in saved.items():
                if v is not None:
                    sys.modules[k] = v
        rmtree_force(tmp)


@contextlib.contextmanager
def sr_from(src: str):
    """hw/sweep_record.py as the copy of the code in `src` has it (a plant's own), with its library: (module, lib)."""
    pydir = os.path.join(ROOT, "python")                    # a plant's copy sits outside the tree: its imports still need python/
    sys.path.insert(0, src)
    sys.path.insert(0, pydir)
    saved = {k: sys.modules.pop(k, None) for k in ("sweep_record", "card_stress_lib")} if os.path.abspath(src) != os.path.abspath(HERE) else {}
    try:
        mod = importlib.import_module("sweep_record")
        yield mod, mod.L
    finally:
        sys.path.remove(src)
        sys.path.remove(pydir)
        if saved:
            sys.modules.pop("sweep_record", None)
            for k, v in saved.items():
                if v is not None:
                    sys.modules[k] = v


def index_item_checks(src: str = HERE) -> list:
    """The 35 index-based items (parcels HC and CL) in the catalog: their spaces, k, reach, attributes, exactness and whole-space
    figures against the documents' and against the REAL tools' logs; each real log through parse_soak with the item's own rule, and
    damaged every way the rule must refuse; the stand-in printing the real tool's line; and the plans the driver makes for them."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    index = fixture_index()
    with lib_from(src) as L2:
        raises = lambda fn: raises_in(L2, fn)               # noqa: E731
        parse_ok = lambda fn: parse_ok_in(L2, fn)           # noqa: E731
        everything = L2.sweep_items()
        by = {it.name: it for it in everything}
        new = everything[90:]
        c("index items: the 35 follow the scripts' 90, in HC's then CL's order, one a (mode, attribute) and each attribute its "
          "operation's", [it.name for it in new] == DOC_NAMES and len(new) == 35, str([it.name for it in new][:5]))
        bad = []
        for op, (space, k, ms, reach, whole) in DOC_INDEX.items():
            for m in ms:
                it = by.get(f"{op}-{m}")
                if it is None:
                    bad.append(f"{op}-{m} missing")
                    continue
                w = whole[m] if whole else (k * space, 0)
                got = (it.op, it.mode, it.kind, it.space, it.per_encoding, it.reach, it.tool, it.verdict_mode, it.whole, it.exact)
                want = (op, m, "exhaustive", space, k, reach, "divsqrt" if op.endswith("-hard") else "clause5", m, w,
                        op in ("conv64to32-class", "rint64-class", "cvtfrom64-class", "scaleb64-class"))
                if got != want:
                    bad.append(f"{it.name}: {got} vs {want}")
        c("index items: each has the documents' space, k, reach, tool, verdict word and whole-space figures, and is exact where "
          "its cases are k x E (the four class modes that skip nothing) and not for the hard-case modes and cvtto64-class",
          not bad, "; ".join(bad[:2]))
        it = by["rint64-class-rne"]
        c("index items: the job line is `<tool> <op> <lo> <hi> <attribute>` over the item's own indices",
          it.argv("B", lo=3, hi=9) == ["B", "rint64-class", "3", "9", "rne"] and by["sqrt64-hard-rmm"].argv("B", lo=0, hi=7) ==
          ["B", "sqrt64-hard", "0", "7", "rmm"])
        lim = {i.name for i in L2.sweep_items(("rne",), ("rne",)) if i.level in ("hard", "class")}
        c("index items: a probe that allows rne alone leaves scaleb64-class and cvtfrom64-class rne alone and the others their modes",
          {n for n in lim if n.startswith(("scaleb64-class", "cvtfrom64-class"))} == {"scaleb64-class-rne", "cvtfrom64-class-rne"}
          and len(lim) == 35 - 3 - 3, str(len(lim)))
        # the whole-space figures against the real tool's own counts
        for mode, (space, k, _ms, _r, whole) in ((m, DOC_INDEX[m]) for m in ("div32-hard", "div64-hard", "sqrt64-hard")):
            lines = fixture(f"count-{mode}.txt").splitlines()
            tot = next((ln.split() for ln in lines if ln.startswith("total ")), None)
            segs = [ln.split() for ln in lines[1:] if ln and not ln.startswith(("total ", "maxskip "))]
            c(f"index items: hard-count of {mode}'s whole space (the real tool's log) gives {space:,} indices, the cases and "
              f"skipped slots the catalog holds, and its segments add up",
              tot is not None and tuple(int(x) for x in tot[1:]) == (space,) + whole["rne"]
              and sum(int(s[1]) for s in segs) == space and sum(int(s[2]) for s in segs) == whole["rne"][0]
              and sum(int(s[3]) for s in segs) == whole["rne"][1] and by[f"{mode}-rne"].whole == whole["rne"], str(tot))
        # real logs, each through the item's own rule
        goods = (("hc-div32-hard.txt", "div32-hard-rne"), ("hc-div64-hard.txt", "div64-hard-rtz"),
                 ("hc-sqrt64-hard.txt", "sqrt64-hard-rmm"), ("cl-conv64to32-class.txt", "conv64to32-class-rne"),
                 ("cl-rint64-class.txt", "rint64-class-rmm"), ("cl-cvtto64-class.txt", "cvtto64-class-rup"),
                 ("cl-cvtfrom64-class.txt", "cvtfrom64-class-rtz"), ("cl-scaleb64-class.txt", "scaleb64-class-rdn"))
        standin = os.path.join(src, "card_stress_standin.py")           # src: the code under test, or a plant's copy of it
        for nm, iname in goods:
            it = by[iname]
            op, lo, hi, mode = fixture_job(index, nm)
            t = fixture(nm)
            m = SOAK_EXH_LINE.search(t)
            if m is None:
                c(f"index {nm}: the real verdict line carries the encodings and skipped clause", False)
                continue
            cases, enc, skp = int(m.group(3)), int(m.group(6)), int(m.group(7))
            exp, cover = it.expected_cases(lo, hi), it.cover_spec(lo, hi)
            if cover is None:                    # an item with no cover rule is a red check here, not a crash further down
                c(f"index {nm}: {iname} has a cover rule: its verdict line says what a slice covered, and the slice is held to it", False)
                continue
            rc = index[nm][0]
            v, why = parse_ok(lambda: L2.parse_soak(t, rc, it.op, it.verdict_mode, None, exp, cover))
            c(f"index {nm}: made by {iname}'s command line; passes with the log's own cases, encodings and skipped, E the slice's "
              f"{hi - lo:,} indices and cases + skipped k x E (k = {it.per_encoding})",
              (op, mode) == (it.op, it.mode) and v is not None and v.ok and enc == hi - lo and cases + skp == it.per_encoding * (hi - lo)
              and v.counts == {"cases": cases, "value_mismatches": 0, "flag_mismatches": 0, "encodings": enc, "skipped": skp}, why)
            if lo == 0 and hi == it.space:
                c(f"index {nm}: a whole-space log: its cases and skipped are the catalog's whole-space figures for {iname}",
                  (cases, skp) == it.whole, f"{(cases, skp)} vs {it.whole}")
            if it.exact:
                c(f"index {nm}: the catalog's expected_cases is the real tool's count, and nothing was skipped",
                  exp == cases and skp == 0, f"{exp} vs {cases}, skipped {skp}")
            else:
                c(f"index {nm}: its cases are not a function of the slice (expected_cases is None): coverage is the indices "
                  f"alone plus k x E", exp is None and cover is not None)
            for what, tweak in (("longer by one index", dict(cover, encodings=hi - lo + 1)),
                                ("shorter by one index", dict(cover, encodings=hi - lo - 1)),
                                ("with one more check an index", dict(cover, per_encoding=it.per_encoding + 1)),
                                ("with one fewer check an index", dict(cover, per_encoding=it.per_encoding - 1))):
                c(f"index {nm}: a slice {what} than the log is refused",
                  raises(lambda tweak=tweak: L2.parse_soak(t, 0, it.op, it.verdict_mode, None, exp, tweak)))
            if it.exact:
                c(f"index {nm}: a count of cases one more than the real one is refused",
                  raises(lambda: L2.parse_soak(t, 0, it.op, it.verdict_mode, None, exp + 1, cover)))
            line = m.group(0)
            for what, bad in (("its encodings clause removed", line.replace(f", {enc} encodings, {skp} skipped", "")),
                              ("one index fewer printed", line.replace(f", {enc} encodings,", f", {enc - 1} encodings,")),
                              ("one case more printed", line.replace(f": {cases} cases,", f": {cases + 1} cases,")),
                              ("one skipped slot more printed", line.replace(f", {skp} skipped", f", {skp + 1} skipped"))):
                c(f"index {nm}: the log with {what} is refused",
                  raises(lambda bad=bad: L2.parse_soak(t.replace(line, bad), 0, it.op, it.verdict_mode, None, exp, cover)))
            c(f"index {nm}: no verdict line, a doubled one and another job's verdict are each refused",
              raises(lambda: L2.parse_soak(t.replace(line, ""), 0, it.op, it.verdict_mode, None, exp, cover))
              and raises(lambda: L2.parse_soak(t + line + "\n", 0, it.op, it.verdict_mode, None, exp, cover))
              and raises(lambda: L2.parse_soak(t, 0, "nosuchop", it.verdict_mode, None, exp, cover)))
            dev = t.replace("soaking the software backend", "soaking the DEVICE backend: /box/img.xclbin")
            pv, why = parse_ok(lambda: L2.parse_soak(dev, 0, it.op, it.verdict_mode, "/box/img.xclbin", exp, cover))
            c(f"index {nm}: the DEVICE line is read and held to the image, the software line for a card job is refused, and a CPU "
              f"job's log that names a DEVICE is refused",
              pv is not None and pv.ok and raises(lambda: L2.parse_soak(t, 0, it.op, it.verdict_mode, "/box/img.xclbin", exp, cover))
              and raises(lambda: L2.parse_soak(dev, 0, it.op, it.verdict_mode, None, exp, cover, cpu=True)), why)
            argv = [sys.executable, standin, "soak", "--", "host/" + ("divsqrt-soak" if it.tool == "divsqrt" else "clause5-soak"),
                    op, str(lo), str(hi), mode]
            p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
            sm = SOAK_EXH_LINE.search(p.stdout)
            c(f"index {nm}: the dry-run stand-in prints the real tool's line for this slice "
              f"({'whole' if lo == 0 and hi == it.space and it.exact or iname == 'cvtto64-class-rup' else 'its indices, and cases + skipped'})",
              sm is not None and sm.group(1, 2, 4, 5, 6) == m.group(1, 2, 4, 5, 6)
              and (sm.group(0) == m.group(0) if (it.exact or iname == "cvtto64-class-rup") else int(sm.group(3)) + int(sm.group(7)) == cases + skp),
              (sm.group(0) if sm else p.stdout[-200:]) + " | " + m.group(0))
        for nm, iname in (("hc-div32-hard-sab.txt", "div32-hard-rne"), ("cl-rint64-class-sab.txt", "rint64-class-rne")):
            it = by[iname]
            op, lo, hi, mode = fixture_job(index, nm)
            t = fixture(nm)
            exp, cover = it.expected_cases(lo, hi), it.cover_spec(lo, hi)
            v, why = parse_ok(lambda: L2.parse_soak(t, index[nm][0], it.op, it.verdict_mode, None, exp, cover))
            c(f"index {nm}: the mode's own negative control, a real failing log, is a failure with its counts and operands, "
              f"and a failing log with exit status 0 is refused",
              v is not None and (not v.ok) and v.counts["value_mismatches"] > 0 and v.counts["encodings"] == hi - lo
              and len(v.extra["disagreements"]) >= 3 and all(re.search(r"a=0x[0-9a-f]+", x) for x in v.extra["disagreements"])
              and raises(lambda: L2.parse_soak(t, 0, it.op, it.verdict_mode, None, exp, cover)), why)
        # the stand-in's tables are the library's (the stand-in of `src`, loaded from its file: a cached import of the real one would hide a plant)
        import importlib.util
        st_spec = importlib.util.spec_from_file_location("card_stress_standin_under_test", standin)
        st_mod = importlib.util.module_from_spec(st_spec)
        st_spec.loader.exec_module(st_mod)
        diff = []
        for op, (space, k, ms, _r, whole) in DOC_INDEX.items():
            if st_mod.IDX[op][:2] != (space, k):
                diff.append(op)
            for m in ms:
                ws = whole[m][1] if whole else 0
                if (st_mod.IDX[op][2] if st_mod.IDX[op][2] is not None else st_mod.CVTTO64_SKIPPED[m]) != ws:
                    diff.append(f"{op}-{m}")
        cuts = [0, 1, 777, 65536, 1 << 20, 3_000_001, 4_000_000, 21_235_787, 21_235_788]
        sums_ok = all(sum(st_mod.idx_skipped(op, m, a, b) for a, b in zip(cs, cs[1:])) == (whole[m][1] if whole else 0)
                      for op, (space, _k, ms, _r, whole) in DOC_INDEX.items() for m in ms
                      for cs in [[x for x in cuts if x < space] + [space]])
        c("index items: the stand-in's tables (indices, k, whole-space skips) are the documents' and the library's, and its skips "
          "spread over any partition of a space add up to the whole space's exactly", not diff and sums_ok, str(diff[:3]))
    return out


def index_plan_checks(src: str = HERE) -> list:
    """The jobs the driver plans for the index-based items, in-process: the space is the item's own (a short last slice, a whole-space
    first slice for a small space, none after it), the card's wave takes tile items and the pool host ones, and a record says what the
    slice was held to."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    try:
        with driver_from(src) as (mod, d, L2):
            q = mod.Image("quad", "/box/quad.xclbin", 4, "u50-rev8-quad", None)
            j = d.plan_wave(q, 3600, 1, ["rint64-class-rne"])[0]
            b = d.soak_binary(j["item"])
            c("index plan: rint64-class-rne's first slice is the WHOLE space (35,840 indices: the probe, 2^20, is cut to it): "
              "`clause5-soak rint64-class 0 35840 rne`, cover 4 checks an index, 143,360 cases expected, reach tile, tile pinned only "
              "in a wave of several",
              j["argv"] == [b, "rint64-class", "0", "35840", "rne"] and j["cover"] == {"encodings": 35840, "per_encoding": 4}
              and j["expected"] == 143360 and j["sweep"]["reach"] == "tile" and (j["lo"], j["hi"]) == (0, 35840), str(j["argv"]))
            d.intervals["rint64-class-rne"] = [(0, 35840)]
            c("index plan: once the whole space is covered the item is no longer planned (no gap)",
              d.plan_wave(q, 3600, 1, ["rint64-class-rne"]) == [])
            j = d.plan_wave(q, 3600, 1, ["div64-hard-rtz"])[0]
            c("index plan: div64-hard-rtz's first slice is the probe 2^20 from 0, cover 4 checks an index, NO fixed case count (a "
              "skipped index skips its four slots), reach tile",
              (j["lo"], j["hi"]) == (0, 1 << 20) and j["cover"] == {"encodings": 1 << 20, "per_encoding": 4} and j["expected"] is None
              and j["sweep"]["reach"] == "tile" and "expected_cases" not in j["sweep"], str((j["lo"], j["hi"], j["cover"])))
            sp = 289_685_696
            d.intervals["div64-hard-rtz"] = [(0, sp - 100)]
            j = d.plan_wave(q, 3600, 1, ["div64-hard-rtz"])[0]
            c("index plan: the last slice is short and ends exactly at the space's end, 289,685,696, not at 2^32",
              (j["lo"], j["hi"]) == (sp - 100, sp), str((j["lo"], j["hi"])))
            d.intervals["div64-hard-rtz"] = [(0, 1 << 20)]
            d.rate = {"div64-hard@quad": 1e9}
            j = d.plan_wave(q, 3600, 1, ["div64-hard-rtz"])[0]
            c("index plan: with a rate measured the next slice is a whole number of 2^20 atoms capped at the card's 2^28",
              j["lo"] == 1 << 20 and j["hi"] - j["lo"] == 1 << 28 and (j["hi"] - j["lo"]) % (1 << 20) == 0, str((j["lo"], j["hi"])))
            d.intervals["div64-hard-rtz"] = [(0, 1 << 20), ((1 << 20) + (1 << 28), sp - (1 << 20))]
            j = d.plan_wave(q, 3600, 1, ["div64-hard-rtz"])[0]
            c("index plan: a gap in the middle is served before the tail, and bounded by the next covered range",
              (j["lo"], j["hi"]) == (1 << 20, (1 << 20) + (1 << 28)), str((j["lo"], j["hi"])))
            j = d.plan_wave(d.cpu, 3600, 1, ["cvtto64-class-rne"], L2.HOST)[0]
            c("index plan: a host class item goes to the pool's plan (image cpu), reach host, with a cover but no fixed count of "
              "cases (cvtto64-class skips pairs)",
              j["sweep"]["reach"] == "host" and j["cover"] == {"encodings": 40768, "per_encoding": 4} and j["expected"] is None
              and j["tile"] is None, str(j["sweep"]))
            c("index plan: the card's sweep never plans a host class item and the pool never a tile one",
              d.plan_wave(q, 3600, 1, ["cvtto64-class-rne"]) == [] and d.plan_wave(d.cpu, 3600, 1, ["rint64-class-rne"], L2.HOST) == [])
    except Exception as e:                      # a driver that cannot be driven this way is a red check, not a crash
        c("index plan: the driver could be driven in-process", False, repr(e))
    return out


INDEX_TILE = ["div32-hard-rne", "sqrt64-hard-rmm", "rint64-class-rne", "scaleb64-class-rne"]
INDEX_HOST = ["cvtto64-class-rne", "conv64to32-class-rtz", "cvtfrom64-class-rup"]


def scn_index_items(env: Env, src: str = HERE) -> list:
    """The index-based items served by the driver against the stand-in, to the end of their own spaces: four tile items on the quad's
    four tiles (a hard-case item that needs several slices, one whose space is smaller than the probe, two class items) and three host
    items on the pool. Every slice held to its indices and to k x E, the space's end exact (a short last slice), the whole-space
    check run once per item, the status file and the report counting each item over its own space."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    names = INDEX_TILE + INDEX_HOST
    space = {f"{op}-{m}": v[0] for op, v in DOC_INDEX.items() for m in v[2]}
    kk = {f"{op}-{m}": v[1] for op, v in DOC_INDEX.items() for m in v[2]}
    r = start_driver(env, "indexitems", ["--until", until(300), "--sweep-items", ",".join(names)] + SWEEP_ALL_BASE, src=src, to_file=True)

    def complete():
        iv = L.sweep_coverage(r.recs)[0]
        return all(iv.get(n) and L.first_gap(iv[n], space[n]) is None for n in names)

    done = wait_for(complete, 200, 0.5)
    stop_run(r)
    r.finish(90)
    legs = r.legs(kind="sweep")
    c("index items: the seven items were each served to the end of their own space, then it stopped on STOP",
      done and r.rc == 0, f"done {done}, rc {r.rc}")
    c("index items: every slice passed", bool(legs) and all(x["status"] == "pass" for x in legs), str(sorted({x["status"] for x in legs})))
    for n in names:
        mine = sorted((x for x in legs if x["sweep"]["item"] == n), key=lambda x: x["sweep"]["lo"])
        enc = sum(dg(x, "counts", "encodings") or 0 for x in mine)
        c(f"index items {n}: the slices' indices are contiguous from 0 to exactly {space[n]:,} and add up to it, none run twice "
          f"(each slice's own count read from its verdict line)",
          bool(mine) and enc == space[n] and mine[0]["sweep"]["lo"] == 0 and mine[-1]["sweep"]["hi"] == space[n]
          and all(a["sweep"]["hi"] == b["sweep"]["lo"] for a, b in zip(mine, mine[1:])), f"{enc} in {len(mine)} slices")
        c(f"index items {n}: each slice's verdict covered its slice and made {kk[n]} checks an index, held to what the record says",
          bool(mine) and all(dg(x, "counts", "encodings") == x["sweep"]["hi"] - x["sweep"]["lo"] == dg(x, "sweep", "expected_encodings")
                             and (dg(x, "counts", "cases") or 0) + (dg(x, "counts", "skipped") or 0) == kk[n] * (dg(x, "counts", "encodings") or 0)
                             for x in mine))
        if n.startswith(("rint64-class", "scaleb64-class", "conv64to32-class", "cvtfrom64-class")):
            c(f"index items {n}: its cases are exactly {kk[n]} an index, expected_cases recorded, nothing skipped",
              bool(mine) and all(dg(x, "sweep", "expected_cases") == kk[n] * (x["sweep"]["hi"] - x["sweep"]["lo"]) == dg(x, "counts", "cases")
                                 and dg(x, "counts", "skipped") == 0 for x in mine))
        else:
            c(f"index items {n}: no fixed count of cases is expected of it (a skipped index skips its slots) and some were skipped",
              bool(mine) and all("expected_cases" not in x["sweep"] for x in mine) and sum(dg(x, "counts", "skipped") or 0 for x in mine) > 0)
    hard = sorted((x for x in legs if x["sweep"]["item"] == "div32-hard-rne"), key=lambda x: x["sweep"]["lo"])
    c("index items: div32-hard-rne took the probe [0, 2^20) and then a last slice that is SHORT (the space is no multiple of 2^20) and "
      "ends at 21,235,788; each class item's one slice is the whole space",
      len(hard) == 2 and (hard[0]["sweep"]["lo"], hard[0]["sweep"]["hi"]) == (0, 1 << 20) and hard[1]["sweep"]["hi"] == 21_235_788
      and (hard[1]["sweep"]["hi"] - hard[1]["sweep"]["lo"]) % (1 << 20) != 0
      and all(len([x for x in legs if x["sweep"]["item"] == n]) == 1 for n in ("rint64-class-rne", "scaleb64-class-rne", "cvtto64-class-rne")),
      str([(x["sweep"]["lo"], x["sweep"]["hi"]) for x in hard]))
    c("index items: the four tile items ran on the card (the quad, reach tile) and the three host items on the pool (image cpu, reach host)",
      all({(x["image"], x["sweep"]["reach"]) for x in legs if x["sweep"]["item"] == n} == {("quad", "tile")} for n in INDEX_TILE)
      and all({(x["image"], x["sweep"]["reach"]) for x in legs if x["sweep"]["item"] == n} == {("cpu", "host")} for n in INDEX_HOST))
    ev = r.events("whole_space_ok")
    c("index items: the whole-space check ran once for each of the seven items and found every one's slices adding up to the whole "
      "space's cases and skipped slots, and none disagreed",
      sorted(e["item"] for e in ev) == sorted(names) and not r.events("whole_space_mismatch"), str([e["item"] for e in ev]))
    st = open(os.path.join(r.out, "status.txt")).read()
    cov = sum(space[n] for n in names)
    ex_items = [it for it in L.sweep_items() if it.kind == "exhaustive"]
    c("index items: status.txt counts the seven items' indices over their own spaces in its sweep line",
      f"exhaustive {cov:,} of {sum(it.space for it in ex_items):,} encodings" in st, st[st.find("sweep "):][:200])
    rp = os.path.join(src, "card_stress_report.py")
    p = subprocess.run([sys.executable, "-B", "-I", rp, r.out, "--no-write"], capture_output=True, text=True, timeout=120)
    t = p.stdout
    tt, th = sum(space[n] for n in INDEX_TILE), sum(space[n] for n in INDEX_HOST)
    c("index items: the report counts each item over its own space - the item says [N indices], 100.000% of it - totals the "
      "coverage by reach from those spaces, and says what a class-level and a hard-case pass are",
      p.returncode == 0
      and re.search(r"^  rint64-class-rne \[35,840 indices\]\s+1\s+143360\s+35840\s+100\.000%", t, re.M)
      and re.search(r"^  div32-hard-rne \[21,235,788 indices\]\s+2\s+\d+\s+21235788\s+100\.000%", t, re.M)
      and re.search(r"^  reach tile: 4 exhaustive item\(s\) seen; covered %d of %d encodings \(100\.000%%\); fully covered 4 of 4$"
                    % (tt, tt), t, re.M)
      and re.search(r"^  reach host: 3 exhaustive item\(s\) seen; covered %d of %d encodings \(100\.000%%\); fully covered 3 of 3$"
                    % (th, th), t, re.M)
      and "claim at the class level (L2), PLAUSIBLE and not proved" in t and "deterministic space of constructed operands" in t,
      t[t.find("exhaustive items"):][:900])
    return out + scn_index_refusals(env, src)


def scn_index_refusals(env: Env, src: str = HERE) -> list:
    """A slice the tool ran one index or one case short is parse_error, by the rule written for it, not covered, and served again - the
    hard-case items and the class items alike; and a tool whose skips are wrong by one slot passes every slice's cover rule (cases +
    skipped is still k x E) and is caught only by the SUM over the covered item, which must say whole_space_mismatch."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sc = [{"leg": "soak", "op": "div32-hard", "nth": [1], "do": "short"},
          {"leg": "soak", "op": "div32-hard", "nth": [2], "do": "shortcase"},
          {"leg": "soak", "op": "div32-hard", "nth": [3], "do": "badenc"},
          {"leg": "soak", "op": "cvtto64-class", "nth": [1], "do": "short"},
          {"leg": "soak", "op": "rint64-class", "nth": [1], "do": "shortcase"},
          {"leg": "soak", "op": "sqrt64-hard", "from": 1, "do": "skipoff"}]
    bn = ["div32-hard-rne", "cvtto64-class-rne", "rint64-class-rne", "sqrt64-hard-rmm"]
    space = {"div32-hard-rne": 21_235_788, "cvtto64-class-rne": 40_768, "rint64-class-rne": 35_840, "sqrt64-hard-rmm": 4_456_448}
    r = start_driver(env, "indexshort", ["--until", until(180), "--sweep-items", ",".join(bn)] + SWEEP_ALL_BASE, sc, src=src, to_file=True)

    def covered_all():
        iv = L.sweep_coverage(r.recs)[0]
        return all(iv.get(n) and L.first_gap(iv[n], space[n]) is None for n in bn)

    got = wait_for(covered_all, 120, 0.4)
    stop_run(r)
    r.finish(60)
    for n, want in (("div32-hard-rne", ["encodings where the slice has", "checks where", "encodings where the slice has"]),
                    ("cvtto64-class-rne", ["encodings where the slice has"]), ("rint64-class-rne", ["cases where the slice has"])):
        mine = sorted((x for x in r.legs(kind="sweep") if x["sweep"]["item"] == n), key=lambda x: x["start_epoch"])
        k = len(want)
        c(f"index short {n}: the first {k} slice(s) came back short and were refused as parse_error, by the rule written for each "
          f"({', '.join(want)}), with no counts recorded",
          got and len(mine) > k and all(x["status"] == "parse_error" and x["counts"] is None and w in (x["reason"] or "")
                                         for x, w in zip(mine[:k], want)), str([(x["status"], x["reason"]) for x in mine[:k + 1]]))
        c(f"index short {n}: the same first slice was served again each time, and then passed; the refused ones are not covered",
          got and len(mine) > k and len({(x["sweep"]["lo"], x["sweep"]["hi"]) for x in mine[:k + 1]}) == 1 and mine[k]["status"] == "pass"
          and (L.sweep_coverage(r.recs)[0].get(n) or [(None, None)])[0][0] == 0
          and L.sweep_coverage(r.recs)[1].get(n) == sum(1 for x in mine if x["status"] == "pass"),
          str([(x["sweep"]["lo"], x["sweep"]["hi"], x["status"]) for x in mine[:k + 1]]))
    bad = r.events("whole_space_mismatch")
    ok = r.events("whole_space_ok")
    c("index short: sqrt64-hard-rmm, whose every slice is one skipped slot off (cases + skipped still k x E: every slice passed its "
      "cover rule), is caught by the whole-space check: ONE whole_space_mismatch event naming it and the figures, and the others' ok",
      got and len(bad) == 1 and bad[0]["item"] == "sqrt64-hard-rmm" and "NOT the whole space's" in bad[0]["detail"]
      and bad[0]["cases"] < bad[0]["want_cases"] and bad[0]["skipped"] > bad[0]["want_skipped"]
      and sorted(e["item"] for e in ok) == sorted(n for n in bn if n != "sqrt64-hard-rmm")
      and all(x["status"] == "pass" for x in r.legs(kind="sweep") if x["sweep"]["item"] == "sqrt64-hard-rmm"),
      str([e["detail"][:200] for e in bad]))
    return out


def cases_in(text: str) -> int:
    """The cases a soak log's verdict line says (the first number of its one verdict line)."""
    m = re.search(r"^\S+ \S+: (\d+) cases,", text, re.M)
    return int(m.group(1)) if m else -1


def synth_run(path: str, legs: list, tree: "dict | None" = None) -> None:
    """A metrics.jsonl for the report: a run_start, then each leg (image, sweep block, cases) as a passing sweep leg."""
    recs = []
    t = 1_800_000_000.0
    recs.append({"type": "run_start", "v": 1, "ts": L.iso(t), "epoch": t, "run_id": "fixture-0", "host": "fixture", "out": path, "argv": [],
                 "settings": {"until": None, "quick": False, "dry_run": True}, "tree": tree or {"commit": "a" * 40},
                 "images": {n: {"sha256": "0" * 64, "bytes": 1, "tiles": 1, "path": "x", "target": "t"} for n in ("quad", "single", "deep")},
                 "deadline": None, "resumed": False})
    for image, sw, cases in legs:
        t += 5
        recs.append({"type": "leg", "v": 1, "ts": L.iso(t), "epoch": t, "cycle": 1, "image": image, "image_sha256": None,
                     "leg": "sweep-" + sw["item"], "kind": "sweep", "attempt": 1, "start": L.iso(t - 4), "end": L.iso(t),
                     "start_epoch": t - 4, "end_epoch": t, "duration_s": 4.0, "rc": 0, "status": "pass", "timed_out": False,
                     "killed": None, "counts": {"cases": cases, "value_mismatches": 0, "flag_mismatches": 0},
                     "rate": {"value": cases / 4.0, "unit": "cases/s"}, "sweep": sw, "disagreements": None, "log": None,
                     "log_kept": "none", "reason": None, "tile": None, "extra": None})
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "metrics.jsonl"), "w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r) + "\n")


def chunk_unit_checks(src: str = HERE) -> list:
    """The pass size (parcel CK's chunked tools) in the driver, in-process: the tool's own stderr line read from REAL logs and held
    to the request, random scaleB's cases at a BATCH, and the rule for what is a repeat of what when the pass size differs."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    with lib_from(src) as L2:
        raises = lambda fn: raises_in(L2, fn)               # noqa: E731
        parse_ok = lambda fn: parse_ok_in(L2, fn)           # noqa: E731
        by = {it.name: it for it in L2.sweep_items()}
        tc = fixture("chunk-scaleb32-c16384.txt")
        td = fixture("chunk-scaleb32-default.txt")

        def parse(text, chunk, exp=None, op="scaleb32", mode="rne", cover=None, rc=0):
            return L2.parse_soak(text, rc, op, mode, None, exp, cover, chunk=chunk)
        v, why = parse_ok(lambda: parse(tc, 16384, 278528))
        c("chunk: the chunked tool's REAL log ('soaking with BATCH 16384 and CFT_CHUNK 16384 (the defaults are 4096)') asked as pass size "
          "16384 passes, and the verdict says its batch and chunk",
          v is not None and v.ok and v.extra.get("batch") == 16384 and v.extra.get("chunk") == 16384 and v.counts["cases"] == 278528, why)
        c("chunk: ... asked at 8192, at 4096 or as the default tool it is refused, by name (the numbers disagree with the request; "
          "a default job's tool does not print them)",
          all(raises(lambda ch=ch: parse(tc, ch)) for ch in (8192, 4096, None)))
        c("chunk: the line wrong in either number is refused: BATCH 16384 with CFT_CHUNK 4096, and the other way",
          raises(lambda: parse(tc.replace("CFT_CHUNK 16384", "CFT_CHUNK 4096"), 16384))
          and raises(lambda: parse(tc.replace("BATCH 16384", "BATCH 4096"), 16384)))
        c("chunk: the line twice, or the chunked log without its line, is refused for a job asked at 16384",
          raises(lambda: parse(tc.replace("soaking the software backend\n", "soaking the software backend\n" + tc.splitlines()[1] + "\n"), 16384))
          and raises(lambda: parse(td, 16384)))
        v, why = parse_ok(lambda: parse(td, None, 139264))
        c("chunk: the default tool's REAL log passes as a default job and its verdict carries no batch or chunk (its record is as it was)",
          v is not None and v.ok and "batch" not in v.extra and "chunk" not in v.extra, why)
        v, why = parse_ok(lambda: parse(td, 4096, 139264))
        c("chunk: a tool built at 4096 prints no pass-size line, so a job asked at 4096 passes on the default log and says 4096 and 4096; "
          "and a line in that log is refused",
          v is not None and v.extra.get("batch") == 4096 and v.extra.get("chunk") == 4096
          and raises(lambda: parse(tc, 4096)), why)
        for nm, iname, cl in (("chunk-rint64-class-c16384.txt", "rint64-class-rne", 16384), ("chunk-sqrt64-hard-c16384.txt", "sqrt64-hard-rne", 16384)):
            it = by[iname]
            op, lo, hi, mode = fixture_job(fixture_index(), nm)
            t = fixture(nm)
            v, why = parse_ok(lambda: L2.parse_soak(t, 0, it.op, it.verdict_mode, None, it.expected_cases(lo, hi), it.cover_spec(lo, hi), chunk=cl))
            c(f"chunk {nm}: a class-level or hard-case slice of the chunked tool passes its own rule, at batch {cl}",
              v is not None and v.ok and v.extra.get("batch") == cl, why)
        # random scaleB's cases at a BATCH: the real tools' lines
        s32, s64 = by["scaleb32-rne"], by["scaleb64-rne"]
        c("chunk: random scaleB's cases are its count rounded up by whole batches: for 100,000 the REAL tool printed 139,264 at 4096, "
          "278,528 at 16384 (scaleb32) and 442,368 at 16384 (scaleb64), and Item.random_cases gives each",
          s32.random_cases(100000, 4096) == cases_in(td) == 139264 and s32.random_cases(100000, 16384) == cases_in(tc) == 278528
          and s64.random_cases(100000, 16384) == cases_in(fixture("chunk-scaleb64-c16384.txt")) == 442368,
          f"{s32.random_cases(100000, 4096)} {s32.random_cases(100000, 16384)} {s64.random_cases(100000, 16384)}")
        c("chunk: ... a count that is a whole number of batches is its own (17 x 4096 x 4 at 4096), a count below one batch's cases is "
          "rounded up to the batch, and no other random op, count 0 or batch 0 has a figure",
          s32.random_cases(17 * 4096 * 4, 4096) == 17 * 4096 * 4 and s32.random_cases(5, 16384) == 5 * 17
          and by["cvtfrom64-rne"].random_cases(100000, 4096) is None and by["conv64to32-rne"].random_cases(1000, 4096) is None
          and s32.random_cases(0, 4096) is None and s32.random_cases(10, 0) is None
          and by["rint64-class-rne"].random_cases(10, 4096) is None)
        # the stand-in prints what the chunked tool prints
        standin = os.path.join(src, "card_stress_standin.py")
        pr = subprocess.run([sys.executable, standin, "soak", "--", "host/clause5-soak-c16384", "scaleb32", "100000", "5", "rne"],
                            capture_output=True, text=True, timeout=60)
        pr2 = subprocess.run([sys.executable, standin, "soak", "--", "host/clause5-soak-c16384", "scaleb64", "100000", "5", "rne"],
                             capture_output=True, text=True, timeout=60)
        c("chunk: the stand-in, told the chunked tool's name, prints the real tool's pass-size line and its cases (278,528 and 442,368)",
          "soaking with BATCH 16384 and CFT_CHUNK 16384 (the defaults are 4096)" in pr.stderr and cases_in(pr.stdout) == 278528
          and cases_in(pr2.stdout) == 442368, pr.stderr[-200:] + pr.stdout[-120:])
        # the stream rule: what is a repeat of what
        try:
            with driver_from(src, ["--sweep-chunk", "16384"]) as (mod, d, L3):
                cf = next(i for i in d.items if i.name == "cvtfrom64-rne")
                cv = next(i for i in d.items if i.name == "conv64to32-rne")
                st_cf, st_cv = cf.seed_for(0) | 1, cv.seed_for(0) | 1

                def planned(it, states):
                    d.seed_n, d.seed_states = {}, states
                    try:
                        d.plan_wave(d.cpu, 3600, 1, [it.name], L3.HOST)
                        return None
                    except RuntimeError as e:
                        return str(e)
                c("chunk streams: a cvtfrom slice at 16384 from a state another item's DEFAULT-batch slice used is NOT refused - its draws "
                  "go to other source types, so it is another stream",
                  planned(cf, {(st_cf, 4096): ("another-item", 3)}) is None)
                why = planned(cf, {(st_cf, 16384): ("another-item", 3)})
                c("chunk streams: ... a cvtfrom slice from a state a slice at the SAME batch used is refused, naming the batch and both",
                  why is not None and "batch 16384" in why and "another-item" in why and "slice 3" in why, str(why))
                why = planned(cv, {st_cv: ("another-item", 3)})
                c("chunk streams: every other item is keyed by its state alone: a chunked conv64to32 slice from a state a default slice "
                  "used IS refused (its operand sequence is the same at any batch), and the item's own slice again is not",
                  why is not None and "another-item" in why and planned(cv, {st_cv: (cv.name, 0)}) is None, str(why))
        except Exception as e:
            c("chunk streams: the driver could be driven in-process", False, repr(e))
        # records a chunked run left, and what a later run takes from them
        tmp = tempfile.mkdtemp(prefix="cs-chunk-")
        try:
            def run_dir(name, batch):
                recs = []
                for n in range(5 if batch is None else 10):
                    for iname in ("cvtfrom64-rne", "conv64to32-rne"):
                        it = by[iname]
                        sw = {"item": iname, "op": it.op, "tool": "clause5", "count": 1 << 20, "seed": it.seed_for(n), "seed_n": n}
                        if batch:
                            sw.update(batch=batch, chunk=batch)
                        recs.append({"type": "leg", "kind": "sweep", "status": "pass", "image": "cpu", "sweep": sw,
                                     "counts": {"cases": 1 << 20}})
                d = os.path.join(tmp, name)
                os.makedirs(d)
                with open(os.path.join(d, "metrics.jsonl"), "w") as fh:
                    for r in recs:
                        fh.write(json.dumps(r) + "\n")
                return d
            A, B = run_dir("A", None), run_dir("B", 16384)
            fl = lambda dirs, b: L2.earlier_runs(dirs, b)[0]
            c("chunk streams: --earlier-runs: a default earlier run (n to 4) floors BOTH items for a default run, and for a chunked run "
              "only conv64to32 (cvtfrom's chunked draws are other draws); a chunked earlier run (n to 9) floors both for a chunked "
              "run and only conv64to32 for a default one; and with no batch given every slice counts, as before the chunked tools",
              fl([A], 4096) == {"cvtfrom64-rne": 5, "conv64to32-rne": 5} and fl([A], 16384) == {"conv64to32-rne": 5}
              and fl([B], 16384) == {"cvtfrom64-rne": 10, "conv64to32-rne": 10} and fl([B], 4096) == {"conv64to32-rne": 10}
              and fl([A], None) == {"cvtfrom64-rne": 5, "conv64to32-rne": 5} and fl([B], None) == {"cvtfrom64-rne": 10, "conv64to32-rne": 10},
              f"{fl([A], 4096)} {fl([A], 16384)} {fl([B], 16384)} {fl([B], 4096)}")
            states = L2.earlier_runs([B], 16384)[1]
            c("chunk streams: the streams an earlier run started are keyed (state, batch) for a cvtfrom item and by state for the rest",
              (by["cvtfrom64-rne"].seed_for(3) | 1, 16384) in states and (by["conv64to32-rne"].seed_for(3) | 1) in states
              and (by["cvtfrom64-rne"].seed_for(3) | 1) not in states)
        finally:
            rmtree_force(tmp)
    return out


def chunk_report_checks(env: Env, src: str = HERE) -> list:
    """The report with chunked slices: a random item's coverage is a row of its own per batch (a cvtfrom slice's operands, and every
    slice's flag comparison, depend on it), and the sweep section says the pass size of an item that ran at another than the default;
    a run with none is reported as before."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    rp = os.path.join(src, "card_stress_report.py")
    if not os.path.exists(rp):
        skip("chunk report", "hw/card_stress_report.py is not there")
        return out
    cl = {"item": "rint64-class-rne", "tool": "clause5", "op": "rint64-class", "mode": "rne", "reach": "tile", "lo": 0, "hi": 35840,
          "tile": None, "batch": 16384, "chunk": 16384}
    r0 = {"item": "cvtfrom64-rne", "tool": "clause5", "op": "cvtfrom64", "mode": "rne", "reach": "host", "count": 1 << 20, "seed": 3,
          "seed_n": 1, "seed_scheme": 2, "tile": None}
    r1 = dict(r0, seed=5, seed_n=2, batch=16384, chunk=16384)
    d1, d2 = os.path.join(env.tmp, "rep-chunk"), os.path.join(env.tmp, "rep-nochunk")
    tree = {"commit": "b" * 40, "rtl": "c" * 40, "rtl_dirty": False, "host_src": "d" * 40, "host_src_dirty": False, "cc": "gcc 11"}
    synth_run(d1, [("quad", cl, 143360), ("cpu", r0, 1 << 20), ("cpu", r1, 1 << 20)], tree)
    synth_run(d2, [("quad", {k: v for k, v in cl.items() if k not in ("batch", "chunk")}, 143360), ("cpu", r0, 1 << 20)], tree)
    p1 = subprocess.run([sys.executable, "-B", "-I", rp, d1, "--no-write"], capture_output=True, text=True, timeout=120)
    p2 = subprocess.run([sys.executable, "-B", "-I", rp, d2, "--no-write"], capture_output=True, text=True, timeout=120)
    t1, t2 = p1.stdout, p2.stdout
    c("chunk report: a run with chunked slices says the pass size of each item that ran at another than 4096, and how many slices at each",
      p1.returncode == 0 and "pass size, items with a slice that ran at another than the default 4096" in t1
      and re.search(r"^  rint64-class-rne\s+1 at 16384$", t1, re.M) and re.search(r"^  cvtfrom64-rne\s+1 at 4096, 1 at 16384$", t1, re.M),
      t1[t1.find("slices:"):][:500])
    tr1 = t1[t1.find("== SWEEP COVERAGE BY TREE =="):]
    c("chunk report: coverage by tree keeps a random item's chunked and default streams in rows of their own, never summed",
      re.search(r"^\s+cvtfrom64-rne\s+1\s", tr1, re.M) and re.search(r"^\s+cvtfrom64-rne @batch 16384\s+1\s", tr1, re.M),
      tr1[tr1.find("random items (cases by image"):][:500])
    c("chunk report: a run with no chunked slice has no pass-size lines and one row for the item, as it always had",
      p2.returncode == 0 and "pass size" not in t2 and "@batch" not in t2 and re.search(r"^\s+cvtfrom64-rne\s+1\s", t2[t2.find("== SWEEP COVERAGE BY TREE =="):], re.M) is not None,
      t2[:200])
    return out


def scn_chunk(env: Env, src: str = HERE) -> list:
    """--sweep-chunk against the stand-in, a dry run: the sweep's slices - the card's and the pool's - run the -c<N> tools and the
    battery's legs the default ones; every record carries the batch and chunk the tool said, held to the request; a tool that
    leaves its line out, says another number, or (a default job) says one at all, is refused by name; random scaleB is held to the
    cases its BATCH gives. And, without the flag, nothing changes."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    names = ["scaleb64-rne", "rint64-class-rne", "div32-hard-rne", "sqrt64-hard-rup", "cvtfrom64-rne"]
    sc = [{"leg": "soak", "op": "rint64-class", "nth": [1], "do": "nochunk"}, {"leg": "soak", "op": "div32-hard", "nth": [1], "do": "wrongchunk"}]
    R = run_driver(env, "chunk", ["--quick", "--legs", "api-test", "--sweep-chunk", "16384", "--sweep-items", ",".join(names)], sc, src=src,
                   cap=150)
    sw = R.legs(kind="sweep")
    good = [x for x in sw if x["status"] == "pass"]
    bad = [x for x in sw if x["status"] != "pass"]
    c("chunk run: every slice that passed carries the batch and chunk its tool said, 16384 and 16384, on the card's images and on the pool",
      bool(good) and all(dg(x, "sweep", "batch") == 16384 and dg(x, "sweep", "chunk") == 16384 for x in good)
      and {x["image"] for x in good} >= {"quad", "cpu"}, str(sorted({x["image"] for x in good})))
    c("chunk run: the two slices whose tool left out its line or said another number were refused as parse_error, by name, with no batch "
      "recorded, and the items went on (served again, passing)",
      len(bad) == 2 and all(x["status"] == "parse_error" and "asked to run at pass size 16384" in (x["reason"] or "") and "batch" not in x["sweep"]
                            for x in bad)
      and {x["sweep"]["item"] for x in bad} == {"rint64-class-rne", "div32-hard-rne"}
      and all(any(g["sweep"]["item"] == b["sweep"]["item"] for g in good) for b in bad), str([(x["status"], x["reason"]) for x in bad]))
    c("chunk run: the tools the sweep ran are the -c16384 ones (the stand-in prints the command it was given): every sweep log, the card's "
      "and the pool's, names clause5-soak-c16384 or divsqrt-soak-c16384, and the battery's api-test the default host/api-test",
      bool(sw) and all(re.search(r"would run: .*(clause5|divsqrt)-soak-c16384 ", log_text(R, x)) for x in sw if x["log"])
      and all("api-test" in log_text(R, x) and "-c16384" not in log_text(R, x) for x in R.legs("api-test")), "")
    rs = R.recs[0]
    c("chunk run: run_start records the pass size, and so does settings.json",
      dg(rs, "settings", "sweep_chunk") == 16384 and json.load(open(os.path.join(R.out, "settings.json"))).get("sweep_chunk") == 16384)

    def bf(count, b, ln):
        total, left = 0, count
        while left > 0:
            n = min(left, b)
            total += n * ln
            left = left - n * ln if left > n * ln else 0
        return total
    rnd = [x for x in good if x["sweep"]["item"] == "scaleb64-rne"]
    c("chunk run: a random scaleB slice is held to the cases its BATCH gives (the count rounded up by whole batches of 27 exponents, "
      "computed here): expected_cases is recorded, is not the count, and is what the tool printed",
      bool(rnd) and all(x["sweep"].get("expected_cases") == bf(x["sweep"]["count"], 16384, 27) == dg(x, "counts", "cases")
                        and x["sweep"]["expected_cases"] != x["sweep"]["count"] for x in rnd), str([x["sweep"] for x in rnd][:1]))
    # the same items without the flag: nothing changes
    sc2 = [{"leg": "soak", "op": "rint64-class", "nth": [1], "do": "defchunk"}]
    D = run_driver(env, "nochunk", ["--quick", "--legs", "api-test", "--sweep-items", ",".join(names)], sc2, src=src, cap=150)
    dsw = D.legs(kind="sweep")
    dbad = [x for x in dsw if x["status"] != "pass"]
    c("no chunk: without the flag no sweep record has a batch or chunk, run_start and settings.json do not name a pass size, and the tools "
      "are the default ones",
      bool(dsw) and all("batch" not in x["sweep"] and "chunk" not in x["sweep"] for x in dsw) and "sweep_chunk" not in D.recs[0]["settings"]
      and "sweep_chunk" not in json.load(open(os.path.join(D.out, "settings.json")))
      and all("-c16384" not in log_text(D, x) and "-c4096" not in log_text(D, x) for x in dsw if x["log"]), "")
    c("no chunk: a default job whose tool says it ran at a pass size is refused by name (that binary is not the default build)",
      len(dbad) == 1 and dbad[0]["status"] == "parse_error" and "default tool says it ran at BATCH 16384" in (dbad[0]["reason"] or ""),
      str([(x["status"], x["reason"]) for x in dbad]))
    # the flag's own refusals, by name, before anything starts
    refused = []
    for bad_n in ("5000", "0", "70000", "-4096", "4097", "8191"):
        p = subprocess.run([sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", os.path.join(env.tmp, "x-" + bad_n),
                            "--dry-run", "--quick", "--sweep-chunk", bad_n], capture_output=True, text=True, timeout=60)
        refused.append(p.returncode == 2 and "--sweep-chunk" in p.stderr and "multiple of 4096 up to 65536" in p.stderr)
    c("chunk args: a pass size that is not a positive multiple of 4096 up to 65536 is refused by name (exit 2), the Makefile's own rule",
      all(refused), str(refused))
    return out


# The digest of the campaign records of the scripts' 90 items, by name and id, in catalog order - MEASURED at 827c3cf, before this parcel
# touched hw/sweep_record.py (a clean clone, `campaign_digest` below run there): the campaign of an item whose space is 2^32 must stay
# what it was, byte for byte, so that every campaign id a run has already written stays valid.
OLD_CAMPAIGN_DIGEST = "b8555f2f9edc1cf9ac4c097eb57e2553f4b7cbf3933831744ed653a5d415432d"
CONV32TO64_CAMPAIGN_ID = "c2aaacbea9016dc8da1472d1a71f15e161d49bdecdb2db6cadc4177a4fb3edc1"      # docs/SWEEP-RECORDS.md's own figure


def campaign_digest(SR, items) -> str:
    h = hashlib.sha256()
    for it in items:
        h.update(f"{it.name} {SR.record_id(SR.campaign_body(it))}\n".encode())
    return h.hexdigest()


def campaign_space_checks(src: str = HERE) -> list:
    """A campaign record says its item's own space (hw/sweep_record.py, changed at the lead's word on 2026-10-21): the 90 old items' campaign
    records and ids are byte for byte what they were at 827c3cf, the 35 new ones say their own spaces, and counts_problem now catches an
    interval past a new item's real space."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    with sr_from(src) as (SR, LS):
        items = LS.sweep_items()
        dg_now = campaign_digest(SR, items[:90])
        c("campaign space: the campaign records of the scripts' 90 items hash to what they did at 827c3cf (one digest over every name and "
          "id), and conv32to64-all's id is the one docs/SWEEP-RECORDS.md prints",
          dg_now == OLD_CAMPAIGN_DIGEST and SR.record_id(SR.campaign_body(next(i for i in items if i.name == "conv32to64-all"))) ==
          CONV32TO64_CAMPAIGN_ID, dg_now)
        c("campaign space: every old exhaustive item's campaign says 2^32 and every random one's has no space",
          all((SR.campaign_body(i).get("space") == (1 << 32)) if i.kind == "exhaustive" else ("space" not in SR.campaign_body(i)) for i in items[:90]))
        bad = []
        for op, (space, k, ms, _r, whole) in DOC_INDEX.items():
            for m in ms:
                it = next(i for i in items if i.name == f"{op}-{m}")
                camp = SR.campaign_body(it)
                camp["id"] = SR.record_id(camp)
                try:
                    SR.check_shape(camp, "test")
                except SR.Refusal as e:
                    bad.append(f"{it.name}: {e}")
                if (camp.get("space"), camp.get("per_encoding"), camp.get("exact")) != (space, k, op in ("conv64to32-class", "rint64-class", "cvtfrom64-class", "scaleb64-class")):
                    bad.append(f"{it.name}: {camp}")
        c("campaign space: each of the 35 new items' campaign says its own space (the documents'), its checks an index and whether its cases are "
          "exact, and is a campaign the verifier's form accepts", not bad, "; ".join(bad[:2]))
        d32 = next(i for i in items if i.name == "div32-hard-rne")
        camp = SR.campaign_body(d32)
        past = {"kind": "slice", "lo": 21_235_000, "hi": 21_235_789, "cases": 4 * 789, "skipped": 0}
        ends = {"kind": "slice", "lo": 21_235_000, "hi": 21_235_788, "cases": 4 * 788, "skipped": 0}
        r64 = next(i for i in items if i.name == "rint64-class-rne")
        cr = SR.campaign_body(r64)
        old = next(i for i in items if i.name == "sqrt32-rne")
        co = SR.campaign_body(old)
        why = SR.counts_problem(camp, past)
        c("campaign space: counts_problem refuses an interval one past a new item's real space, by name and figure (21,235,789 past 21,235,788; "
          "35,841 past 35,840), and accepts one that ends exactly at it",
          why is not None and "past the campaign's space of 21235788" in why and SR.counts_problem(camp, ends) is None
          and "past the campaign's space of 35840" in (SR.counts_problem(cr, {"kind": "slice", "lo": 0, "hi": 35841, "cases": 4 * 35841,
                                                                               "skipped": 0}) or "")
          and SR.counts_problem(cr, {"kind": "slice", "lo": 0, "hi": 35840, "cases": 4 * 35840, "skipped": 0}) is None, str(why))
        c("campaign space: an old item's space is still 2^32: an interval to 2^32 is accepted and one past it is refused",
          SR.counts_problem(co, {"kind": "slice", "lo": 0, "hi": 1 << 32, "cases": 1 << 32}) is None
          and "past the campaign's space of 4294967296" in (SR.counts_problem(co, {"kind": "slice", "lo": 0, "hi": (1 << 32) + 1,
                                                                                    "cases": (1 << 32) + 1}) or ""))
    return out


def make_key(tmp: str, name: str):
    """A throwaway Ed25519 key made now by python/cft_sign.py keygen in `tmp`: (path, public key hex, secret seed hex). Never a real key, never in a
    tree (the caller holds `tmp` to be outside every working tree)."""
    path = os.path.join(tmp, name)
    p = subprocess.run([sys.executable, "-B", "-I", os.path.join(ROOT, "python", "cft_sign.py"), "keygen", "--out", path],
                       capture_output=True, text=True, timeout=60)
    pub = re.findall(r"[0-9a-f]{64}", p.stdout)
    seed = re.search(r"^seed ([0-9a-f]{64})$", open(path).read(), re.M) if os.path.exists(path) else None
    return (path, pub[-1], seed.group(1)) if pub and seed else (None, None, None)


def outside_trees(path: str) -> bool:
    """Whether `path` is outside every git working tree (a key made there could be used by the driver): the test's own temp directory is,
    unless the machine's temp directory is inside a repository, in which case the key tests are skipped by name."""
    p = os.path.abspath(path)
    return not any(os.path.exists(os.path.join(d, ".git")) for d in [p] + list(_parents(p)))


def _parents(p: str):
    while True:
        q = os.path.dirname(p)
        if q == p:
            return
        yield q
        p = q


def parse_refusal(mod, argv: list):
    """The text a refused command line printed, or None when it was accepted."""
    import io
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            mod.parse_args(argv)
        return None
    except SystemExit:
        return buf.getvalue()


def records_args_checks(env: Env, src: str = HERE) -> list:
    """--records, --sign-key and --device-key at the command line, in-process: each refusal by name before anything starts, a key inside a git
    working tree refused (key-in-tree) whether or not it exists, the secret never read into a setting; and without the flags nothing is
    written or recorded that was not."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    kd = tempfile.mkdtemp(prefix="cs-key-")
    scratch = os.path.join(env.tmp, "keyrepo")
    try:
        if not outside_trees(kd):
            skip("records args", f"the temp directory {kd} is inside a git working tree: a key made here would be refused (key-in-tree)")
            return out
        key, pub, seed = make_key(kd, "a.key")
        c("records args: a throwaway key is made at run time by cft_sign.py keygen, outside every git working tree", key is not None, str(key))
        if key is None:
            return out
        with driver_from(src) as (mod, d, L2):
            base = ["--out", os.path.join(kd, "o"), "--quick", "--root", ROOT]
            r = parse_refusal(mod, base + ["--dry-run", "--records", "--sign-key", key])
            c("records args: --records with --dry-run is refused by name - the exporter refuses a run whose legs came from stand-ins - and "
              "nothing starts", r is not None and "refused with --dry-run" in r and "sweep_record" in r and "stand-ins" in r, str(r))
            r = parse_refusal(mod, base + ["--records"])
            c("records args: --records alone is refused: version 1 puts the device in every record, so it needs --sign-key or --device-key",
              r is not None and "needs a device" in r and "--sign-key" in r and "--device-key" in r, str(r))
            r = parse_refusal(mod, base + ["--sign-key", key])
            c("records args: --sign-key without --records is refused", r is not None and "give --records too" in r, str(r))
            r = parse_refusal(mod, base + ["--records", "--sign-key", key, "--device-key", pub])
            c("records args: --sign-key and --device-key together are refused (the key that signs names the device)",
              r is not None and "alternatives" in r, str(r))
            r = parse_refusal(mod, base + ["--records", "--device-key", "ab" * 31])
            c("records args: a --device-key that is not a public key is refused by name", r is not None and "64 lowercase hex" in r, str(r))
            r = parse_refusal(mod, base + ["--records", "--sign-key", os.path.join(ROOT, "hw", "never-made.key")])
            c("records args: a key path inside this repository is refused by name (key-in-tree) before any file is read, though no file is there",
              r is not None and "key-in-tree" in r, str(r))
            repo = make_scratch_repo(scratch)
            kin, _p, _s = make_key(scratch, "in.key") if repo else (None, None, None)
            r = parse_refusal(mod, base + ["--records", "--sign-key", kin]) if kin else None
            c("records args: a real key file inside ANOTHER git working tree is refused by name (key-in-tree) too",
              (repo is None and skip("records args", "git cannot make a scratch repository here") is None) or
              (kin is not None and r is not None and "key-in-tree" in r), str(r))
            if POSIX:
                loose = os.path.join(kd, "loose.key")
                shutil.copy(key, loose)
                os.chmod(loose, 0o644)
                r = parse_refusal(mod, base + ["--records", "--sign-key", loose])
                c("records args (POSIX): a key file others may read is refused by name (key-file)", r is not None and "key-file" in r, str(r))
            else:
                skip("records args (POSIX): a key file others may read", "Windows' permissions are ACLs, which cft_sign.py does not check")
            r = parse_refusal(mod, base + ["--records", "--sign-key", os.path.join(kd, "missing.key")])
            c("records args: a key file that is not there is refused by name (key-file), not a crash", r is not None and "key-file" in r, str(r))
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                a = mod.parse_args(base + ["--records", "--sign-key", key])
                b = mod.parse_args(base + ["--records", "--device-key", pub])
            c("records args: a good key and --records, or --device-key and --records, are accepted; the key's PATH is a setting and its "
              "SECRET is in no setting (the namespace settings.json is written from)",
              a.records and a.sign_key == key and b.records and b.device_key == pub and a.device_key is None
              and seed not in json.dumps(vars(a), default=str) and seed not in json.dumps(vars(b), default=str), "")
    finally:
        rmtree_force(kd)
        rmtree_force(scratch)
    # without the flags: no file, no setting, no status line - the run is as it was
    R = run_driver(env, "norec", ["--quick", "--legs", "api-test", "--sweep-items", "rint64-class-rne"], src=src, cap=100)
    st = open(os.path.join(R.out, "status.txt")).read()
    c("records args: without --records no records file is written, run_start names no records, settings.json names no records, key or pass "
      "size, and status.txt has no records line",
      not os.path.exists(os.path.join(R.out, "sweep-records.jsonl")) and "records" not in R.recs[0]["settings"]
      and not (set(json.load(open(os.path.join(R.out, "settings.json")))) & {"records", "sign_key", "device_key", "sweep_chunk"})
      and "records    " not in st and R.rc == 0, f"rc {R.rc}")
    return out


def records_sink_checks(env: Env, src: str = HERE) -> list:
    """The driver's record sink on the records of a real dry run (the stand-in's slices of index-based items, host and card): REFUSED as
    they stand - the exporter refuses a dry run - and, with one flag of run_start set to say the run was real, written, held to the
    verifier and to the driver's own coverage. This is how --records is exercised end to end on every platform without weakening that
    refusal: the same stream gives records only when the one field that says 'a dry run' is changed, in a scratch directory, by the
    test; nothing in the driver or the exporter offers such a switch. A leg the exporter refuses is named and the run goes on; a resumed
    run continues its file."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    kd = tempfile.mkdtemp(prefix="cs-key-")
    try:
        if not outside_trees(kd):
            skip("records sink", f"the temp directory {kd} is inside a git working tree")
            return out
        key, pub, seed = make_key(kd, "s.key")
        key2, pub2, _s2 = make_key(kd, "t.key")
        if key is None or key2 is None:
            c("records sink: throwaway keys were made", False)
            return out
        R = run_driver(env, "recsrc", ["--quick", "--legs", "api-test", "--sweep-items",
                                       "rint64-class-rne,div32-hard-rne,sqrt64-hard-rmm,scaleb64-class-rne,cvtto64-class-rne,conv64to32-class-rtz"],
                       src=src, cap=150)
        recs = R.recs
        card = [r for r in recs if r.get("type") == "leg" and r.get("kind") == "sweep" and r["status"] == "pass" and r["image"] != "cpu"]
        host = [r for r in recs if r.get("type") == "leg" and r.get("kind") == "sweep" and r["status"] == "pass" and r["image"] == "cpu"]
        c("records sink: the source run is a dry run with card slices on the quad, the single and the deep and host slices on the pool",
          dg(recs[0], "settings", "dry_run") is True and len(card) >= 8 and len(host) == 2 and {r["image"] for r in card} == {"quad", "single", "deep"},
          f"{len(card)} card, {len(host)} host")
        want_cases = sum(r["counts"]["cases"] for r in card)

        def feed_all(mod, sink, stream, dry_flag, via=None):
            for r in stream:
                r = json.loads(json.dumps(r))
                if r.get("type") == "run_start" and dry_flag is not None:
                    r["settings"]["dry_run"] = dry_flag
                (via.rec if via is not None else sink.feed)(r)

        with driver_from(src) as (mod, d, L2):
            def new_sink(path, k=None, dev=None):
                ev = []
                return mod.RecordSink(path, k, dev, emit=lambda name, detail, **kw: ev.append((name, detail))), ev
            # 1. the stream as it stands: refused, nothing written
            p1 = os.path.join(kd, "dry.jsonl")
            s1, ev1 = new_sink(p1, key)
            try:
                feed_all(mod, s1, recs, None)
                crash1 = None
            except Exception as e:                 # a refusal that escapes the sink would end a long run: a red check, not a crash
                crash1 = repr(e)
            c("records sink: the dry run's records fed as they stand are REFUSED by the exporter: one records_disabled event naming the dry run, "
              "every finished card slice counted as not exported, and no file",
              crash1 is None and not os.path.exists(p1) and [n for n, _ in ev1].count("records_disabled") == 1 and "dry run" in ev1[0][1]
              and s1.refused.get("disabled") == len(card) and s1.written == 0, str(crash1 or ev1[:2]))
            SR = s1.SR
            ex = SR.Exporter(public=bytes.fromhex(pub))
            try:
                ex.run_start(dict(recs[0]))
                raised = None
            except SR.Refusal as e:
                raised = (e.name, e.why)
            c("records sink: and the exporter itself still refuses that run_start, by name (metrics: a dry run)",
              raised is not None and raised[0] == "metrics" and "dry run" in raised[1], str(raised))
            # 2. the same stream with the one field changed: written, through the driver's own rec(), signed
            os.makedirs(d.out, exist_ok=True)
            p2 = os.path.join(kd, "signed.jsonl")
            s2, ev2 = new_sink(p2, key)
            d.sink = s2
            feed_all(mod, s2, recs, False, via=d)
            ring = os.path.join(kd, "ring.keyring")
            with open(ring, "w", newline="\n") as fh:
                fh.write(f"key {pub} Throwaway%20Holder\n")
            parsed = []
            try:
                parsed = SR.parse_file(read_bytes(p2))
                rep = SR.verify_records(parsed, SR.read_keyring(ring), require_signed=True)
                vr = (rep["clean"], rep["cases"], len(rep["findings"]), rep["slices"], rep["campaigns"], rep["unsigned"])
            except SR.Refusal as e:
                vr = ("refused", str(e))
            c("records sink: through Driver.rec the same stream, with only settings.dry_run said False, is written: the file verifies signed by "
              "the throwaway key against its keyring, every finished CARD slice is one record, no finding, and the cases total is the driver's "
              "own coverage of those slices",
              vr == (len(card), want_cases, 0, len(card), len({r["sweep"]["item"] for r in card}), 0), str(vr))
            camps = {r["operation"] + "-" + r.get("attribute", ""): r for _n, r in parsed if r["kind"] == "campaign"}
            c("records sink: the campaign records say each item's own space (div32-hard 21,235,788, rint64-class 35,840, cvtto64-class is a host "
              "item and has none), and Driver.rec still wrote metrics.jsonl first, every record of it",
              camps.get("div32-hard-rne", {}).get("space") == 21_235_788 and camps.get("rint64-class-rne", {}).get("space") == 35_840
              and "cvtto64-class-rne" not in camps and len(L.read_records(d.metrics)[0]) == len(recs), str(sorted(camps)))
            c("records sink: the host-pool slices are counted, not offered to the exporter (version 1 has no form for a slice with no image): "
              "2 counted, one records_host_slices event, and not one record_refused",
              s2.host_slices == len(host) == 2 and [n for n, _ in ev2].count("records_host_slices") == 1 and not s2.refused
              and "record_refused" not in [n for n, _ in ev2], str([(n, x[:60]) for n, x in ev2]))
            def slurp(pth):
                return read_bytes(pth).decode("utf-8", "replace")
            secret_in = any(seed in slurp(pth) for pth in (p2, d.metrics))
            c("records sink: the key's secret is in neither the records nor metrics.jsonl", not secret_in and seed not in s2.summary())
            # 3. unsigned, for a later `sign`: the file verifies only as unsigned, and sign makes it verify signed
            p3 = os.path.join(kd, "unsigned.jsonl")
            s3, _ev3 = new_sink(p3, None, pub)
            feed_all(mod, s3, recs, False)
            try:
                rep3 = SR.verify_records(SR.parse_file(read_bytes(p3)), None, require_signed=False)
                un = (rep3["clean"], rep3["unsigned"])
                try:
                    SR.verify_records(SR.parse_file(read_bytes(p3)), None, require_signed=True)
                    sig_needed = False
                except SR.Refusal as e:
                    sig_needed = e.name == "signature"
            except SR.Refusal as e:
                un, sig_needed = ("refused", str(e)), False
            c("records sink: with --device-key the records are written unsigned (verify without --allow-unsigned refuses them: signature) and "
              "name the key's device", un == (len(card), len(card)) and sig_needed and s3.ex.device == SR.device_of(bytes.fromhex(pub)), str(un))
            # 4. a leg the exporter refuses is named and the run goes on
            p4 = os.path.join(kd, "refused.jsonl")
            s4, ev4 = new_sink(p4, key)
            stream = json.loads(json.dumps(recs))
            victim = next(r for r in stream if r.get("type") == "leg" and r.get("kind") == "sweep" and r["status"] == "pass"
                          and r["image"] != "cpu" and r["sweep"]["item"] == "rint64-class-rne")
            victim["counts"]["cases"] += 1                     # a count the item's own rule (4 an index) would not have passed
            try:
                feed_all(mod, s4, stream, False)
                crashed = None
            except Exception as e:                              # a refusal that escapes the sink would end a long run
                crashed = repr(e)
            rep4 = SR.verify_records(SR.parse_file(read_bytes(p4)), None, require_signed=True) if os.path.exists(p4) else {"clean": -1}
            named = [x for n, x in ev4 if n == "record_refused"]
            c("records sink: a leg whose counts the exporter refuses is a record_refused event naming the refusal and the leg, the sink does not "
              "crash, and every other slice is still written",
              crashed is None and len(named) == 1 and named[0].startswith("metrics:") and "rint64-class-rne" in named[0] and "counts" in named[0]
              and s4.refused == {"metrics": 1} and rep4["clean"] == len(card) - 1, f"{crashed} {named[:1]} {rep4['clean']}")
            # 5. a resumed run continues its file: campaigns not repeated, another key refused, a torn tail cut back
            p5 = os.path.join(kd, "resume.jsonl")
            s5, _ev5 = new_sink(p5, key)
            not_deep = [r for r in recs if r.get("type") != "leg" or r.get("kind") != "sweep" or r["image"] != "deep"]
            feed_all(mod, s5, not_deep, False)
            first_n = s5.written
            s6, _ev6 = new_sink(p5, key)
            notes = s6.adopt(R.recs[0]["run_id"])
            feed_all(mod, s6, [r for r in recs if r.get("type") == "run_start" or r.get("type") == "build"
                               or (r.get("type") == "leg" and r.get("kind") == "sweep" and r["image"] == "deep")], False)
            lines = read_bytes(p5).split(b"\n")
            ncamp = sum(1 for ln in lines if b'"kind":"campaign"' in ln)
            try:
                rep5 = SR.verify_records(SR.parse_file(read_bytes(p5)), None, require_signed=True)
                v5 = (rep5["clean"], rep5["campaigns"])
            except SR.Refusal as e:
                v5 = ("refused", str(e))
            c("records sink: a resumed run's sink adopts the file (its campaigns are known: none is written twice) and the file, all of it, "
              "verifies as one run's, every card slice once",
              first_n > 0 and notes and v5 == (len(card), ncamp) and ncamp == len({r["sweep"]["item"] for r in card}), f"{v5} {ncamp} {notes}")
            s7, _ev7 = new_sink(p5, key2)
            try:
                s7.adopt(R.recs[0]["run_id"])
                other = None
            except mod.RecordsError as e:
                other = str(e)
            c("records sink: a resume with ANOTHER key is refused by name (the file is one device's), not appended to",
              other is not None and "device" in other, str(other))
            with open(p5, "ab") as fh:
                fh.write(b'{"kind":"slice","lo":0,"hi')
            s8, _ev8 = new_sink(p5, key)
            n8 = s8.adopt(R.recs[0]["run_id"])
            c("records sink: a torn last line (a write cut short) is cut back to the last whole record, and said",
              read_bytes(p5).endswith(b"\n") and any("torn" in x for x in n8), str(n8))
    finally:
        rmtree_force(kd)
    return out


def scn_records_real(env: Env, src: str = HERE) -> list:
    """--records on a run that is NOT a dry run: the driver's real path (its build step, its guard, its tools run as processes, its record
    sink) over a scratch checkout whose tools and `make` and `ldd` are TEST DOUBLES - shell scripts that run the stand-in. The exporter
    refuses a dry run's legs and cannot tell a double from a card, which is exactly why this lives in a throwaway tree under the test's
    temp directory and offers nothing a real run could reach. A: the default tools, signed with a throwaway key; the file verifies against
    its keyring and its case total is the driver's coverage of the card slices; the secret is nowhere in the run; the host slice is counted.
    B: --sweep-chunk, unsigned with --device-key: the build step runs `make SOAK_CHUNK=n soak-chunk` with the default build's flags,
    every slice says its pass size, `sweep_record.py sign` signs the file, and it verifies."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    need = [x for x in ("git", "sh", "nice", "timeout") if not shutil.which(x)]
    if not POSIX or need:
        skip("records real", "needs POSIX with git, sh, nice and timeout" + (f" (missing: {', '.join(need)})" if need else ""))
        return out
    kd = tempfile.mkdtemp(prefix="cs-key-")
    try:
        if not outside_trees(kd):
            skip("records real", f"the temp directory {kd} is inside a git working tree")
            return out
        key, pub, seed = make_key(kd, "r.key")
        ring = os.path.join(kd, "r.keyring")
        with open(ring, "w", newline="\n") as fh:
            fh.write(f"key {pub} Throwaway%20Holder\n")
        root = os.path.join(env.tmp, "faketree")
        for rel in ("host/tests/seq_check.py", "programs/acceptance.py", "hw/card-segrun.sh"):
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, rel), os.path.join(root, rel))
        shutil.copy(os.path.join(src, "card_stress.py"), os.path.join(root, "hw", "card_stress.py"))
        standin = os.path.join(src, "card_stress_standin.py")

        def script(path, body):
            with open(path, "w") as fh:
                fh.write("#!/bin/sh\n" + body + "\n")
            os.chmod(path, 0o755)
        run_standin = f"exec '{sys.executable}' '{standin}'"
        for name in ("divsqrt-soak", "clause5-soak"):
            script(os.path.join(root, "host", name), f'case "$1" in probe) exit 0;; esac\n{run_standin} soak -- "$0" "$@"')
        script(os.path.join(root, "host", "api-test"), f'{run_standin} api-test -- "$0" "$@"')
        script(os.path.join(root, "host", "cft-segrun"), 'echo FAKEBUILDID')
        for name in ("device-test", "remote-test", "cft-audit", "cft-selftest"):
            script(os.path.join(root, "host", name), "exit 0")
        open(os.path.join(root, "host", "libcft.so"), "w").close()
        for git in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "t"]):
            subprocess.run(["git", "-C", root] + git, capture_output=True, timeout=120)
        fb = os.path.join(env.tmp, "fakebin-rec")
        os.makedirs(fb, exist_ok=True)
        script(os.path.join(fb, "ldd"), "echo '\tlibxrt_coreutil.so.2 => /fake/libxrt_coreutil.so.2 (0x0)'")
        script(os.path.join(fb, "make"),
               'echo "$@" >> "$FAKE_MAKE_LOG"\ndir=.; prev=; n=\nfor a in "$@"; do\n  case "$prev" in -C) dir="$a";; esac\n'
               '  case "$a" in print-build-id) echo FAKEBUILDID; exit 0;; SOAK_CHUNK=*) n="${a#SOAK_CHUNK=}";; esac\n  prev="$a"\ndone\n'
               'if [ -n "$n" ]; then for t in divsqrt-soak clause5-soak; do cp "$dir/$t" "$dir/$t-c$n"; done; fi\nexit 0')
        items = "rint64-class-rne,scaleb64-class-rne,div32-hard-rne,sqrt64-hard-rmm,cvtto64-class-rne"

        def drive(name, extra):
            env.n += 1
            o = os.path.join(env.tmp, f"{env.n:02d}-{name}")
            makelog = os.path.join(env.tmp, f"{env.n:02d}-{name}-make.log")
            cmd = [sys.executable, "-B", "-I", os.path.join(src, "card_stress.py"), "--root", root, "--out", o, "--quick", "--legs", "api-test",
                   "--telemetry-seconds", "0", "--disk-extra", "", "--retry-pause", "1", "--kill-after", "2", "--guard-poll", "1",
                   "--build-jobs", "2", "--make-xrt-flags", "XRT=0", "--sweep-items", items]
            for n, pth in env.imgs.items():
                cmd += ["--image", f"{n}={pth}", "--sha", f"{n}={env.shas[n]}"]
            e = dict(os.environ)
            e["PATH"] = fb + os.pathsep + e["PATH"]
            e["FAKE_MAKE_LOG"] = makelog
            p = subprocess.run(cmd + extra, capture_output=True, text=True, env=e, cwd=ROOT, timeout=300)
            r = Run(o)
            r.rc, r.text = p.returncode, p.stdout + p.stderr
            r.makelog = open(makelog).read().splitlines() if os.path.exists(makelog) else []
            return r

        def cardslices(r):
            return [x for x in r.legs(kind="sweep", status="pass") if x["image"] != "cpu"]

        def sr(*args):
            return subprocess.run([sys.executable, "-B", "-I", os.path.join(src, "sweep_record.py")] + list(args),
                                  capture_output=True, text=True, timeout=120)

        def slurp_tree(d):
            blob = b""
            for dp, _dn, fns in os.walk(d):
                for fn in fns:
                    with open(os.path.join(dp, fn), "rb") as fh:
                        blob += fh.read()
            return blob
        # A: the default tools, signed
        A = drive("rec-real-a", ["--records", "--sign-key", key])
        rf = os.path.join(A.out, "sweep-records.jsonl")
        cs = cardslices(A)
        v = sr("verify", rf, "--keyring", ring) if os.path.exists(rf) else None
        m = re.search(r"(\d+) slices and 0 streams; (\d+) clean \((\d+) cases\), 0 FINDINGS", v.stdout) if v else None
        c("records real (A): a run that is not a dry run, with --records and --sign-key, exits 0 and its run_start says it was real and "
          "names the records file, signed",
          A.rc == 0 and dg(A.recs[0], "settings", "dry_run") is False and dg(A.recs[0], "settings", "records") == {"file": "sweep-records.jsonl", "signed": True}
          and len(cs) >= 8, f"rc {A.rc}: {A.text[-300:]}")
        c("records real (A): sweep_record.py verify of the file against its keyring says clean (exit 0), one record for every finished CARD "
          "slice, and a case total equal to the driver's coverage of those slices (summed here from metrics.jsonl)",
          v is not None and v.returncode == 0 and m is not None and int(m.group(1)) == int(m.group(2)) == len(cs)
          and int(m.group(3)) == sum(x["counts"]["cases"] for x in cs), (v.stdout + v.stderr)[-300:] if v else "no file")
        c("records real (A): signed by the throwaway key, the keyring's holder named; its secret is in no file of the run (settings, "
          "metrics, logs, records, driver.log)", v is not None and pub in v.stdout and "Throwaway%20Holder" in v.stdout
          and seed.encode() not in slurp_tree(A.out), v.stdout[-200:] if v else "")
        hs, sm = A.events("records_host_slices"), A.events("records_summary")
        c("records real (A): the host-pool slice is counted and said once (records_host_slices), the summary event names the key and the "
          "counts, and no leg was refused", len(hs) == 1 and len(sm) == 1 and f"signed by key {pub}" in sm[0]["detail"]
          and "refused: none" in sm[0]["detail"] and not A.events("record_refused"), str([e["detail"][:120] for e in sm]))
        c("records real (A): the default tools were built and run: no soak-chunk in the make log, no -c in any tool's name",
          bool(A.makelog) and not any("soak-chunk" in ln for ln in A.makelog) and all("sweep" not in x or "batch" not in x["sweep"] for x in cs), str(A.makelog[:2]))
        # B: --sweep-chunk, unsigned, signed afterwards by `sweep_record.py sign`
        B = drive("rec-real-b", ["--sweep-chunk", "16384", "--records", "--device-key", pub])
        bf = os.path.join(B.out, "sweep-records.jsonl")
        cb = cardslices(B)
        mk_def = next((ln.split() for ln in B.makelog if " all " in ln + " " and "SOAK_CHUNK" not in ln), [])
        mk_chk = next((ln.split() for ln in B.makelog if "SOAK_CHUNK=16384" in ln and "soak-chunk" in ln), [])

        def flags(tokens):
            i = tokens.index("-j2") + 1 if "-j2" in tokens else 0
            fl = []
            while i < len(tokens) and re.fullmatch(r"[A-Z0-9_]+=\S*", tokens[i]) and not tokens[i].startswith("SOAK_CHUNK="):
                fl.append(tokens[i])
                i += 1
            return fl
        c("records real (B): the build step ran the default make and then `make -C host SOAK_CHUNK=16384 soak-chunk`, with exactly the flags "
          "the default build took (XRT=0 here, and C5DEFS where the probe found roundeven)",
          bool(mk_def) and bool(mk_chk) and mk_chk[:2] == ["-C", mk_def[1]] and flags(mk_chk) == flags(mk_def) and "XRT=0" in flags(mk_chk)
          and mk_chk[-1] == "soak-chunk" and mk_chk[-2] == "SOAK_CHUNK=16384", f"{mk_def} | {mk_chk}")
        c("records real (B): every finished slice, on the card's images and the pool, carries the pass size its tool said (16384 and 16384), and "
          "the record file's run says the build asserted the chunked tools XRT-linked",
          B.rc == 0 and bool(cb) and all(dg(x, "sweep", "batch") == 16384 and dg(x, "sweep", "chunk") == 16384 for x in B.legs(kind="sweep", status="pass"))
          and any(s["name"] == "xrt divsqrt-soak-c16384" and s["ok"] for s in (B.last("build") or {}).get("steps", [])), f"rc {B.rc}: {B.text[-300:]}")
        vu = sr("verify", bf)
        vu2 = sr("verify", bf, "--allow-unsigned")
        signed = os.path.join(kd, "b-signed.jsonl")
        sg = sr("sign", bf, "--key", key, "--out", signed)
        vs = sr("verify", signed, "--keyring", ring) if sg.returncode == 0 else None
        mb = re.search(r"(\d+) slices and 0 streams; (\d+) clean \((\d+) cases\)", vs.stdout) if vs else None
        c("records real (B): --device-key writes unsigned records (verify refuses them without --allow-unsigned, accepts them with it), "
          "`sweep_record.py sign` with the key signs the whole file, and the signed file verifies against the keyring with the driver's own case total",
          vu.returncode == 2 and vu2.returncode == 0 and sg.returncode == 0 and vs is not None and vs.returncode == 0 and mb is not None
          and int(mb.group(1)) == len(cb) and int(mb.group(3)) == sum(x["counts"]["cases"] for x in cb),
          f"{vu.returncode} {vu2.returncode} {sg.returncode} {(vs.stdout + vs.stderr)[-200:] if vs else ''}")
    finally:
        rmtree_force(kd)
    return out


def quick_empty_wave_checks(env: Env, src: str = HERE) -> list:
    """VDR1-1: --quick with --sweep-items ends an image's sweep after ONE empty wave. A host-only list leaves every card wave empty; the quad
    (one quick wave) and the single and the deep (two) each say so once - not twice, which is what the smoke would do on those two images if
    the empty wave were followed by the next one of quick's own list while items are named."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    R = run_driver(env, "quickempty", ["--quick", "--legs", "api-test", "--sweep-items", "nextup32"], src=src, cap=120)
    emp = R.events("sweep_empty")
    c("quick sweep: with --sweep-items an empty wave ends the image's sweep at once - one sweep_empty event for each of the quad, the "
      "single and the deep, in that order, not two for the images that have two quick waves - and the smoke still exits 0",
      [e["image"] for e in emp] == ["quad", "single", "deep"] and all(e.get("cause") == "blocked" for e in emp) and R.rc == 0
      and len(R.legs(kind="sweep")) == 1, f"rc {R.rc}: {[(e['image'], e.get('cause')) for e in emp]}")
    return out


def standin_alive_checks() -> list:
    """VDR1-2 and VDR1-3: standin_alive on Windows asks PowerShell for a process's command line. A call that times out must not error the
    scenario (it counts the pid as alive: the check then fails, as it should for a stand-in it cannot show is gone), and an unreadable
    command line is ALIVE, as the docstring says: a call that fails, or reads an empty command line of a pid that is still there. An
    empty answer for a pid that has exited since the first look is the process having ended between the two calls: dead. Run here on any
    platform, by naming the Windows branch (POSIX set False) and giving it a PowerShell that times out, fails or answers."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    g = globals()
    saved = (g["POSIX"], g["pid_alive"], subprocess.run)

    def with_ps(answer, alive):
        """standin_alive(1234) with POSIX False, pid_alive answering from `alive` (a list, one answer a call), and subprocess.run being `answer`."""
        calls = list(alive)
        g["POSIX"] = False
        g["pid_alive"] = lambda pid: calls.pop(0) if calls else False
        subprocess.run = answer
        try:
            return standin_alive(1234)
        except Exception as e:
            return f"raised {type(e).__name__}"
        finally:
            g["POSIX"], g["pid_alive"], subprocess.run = saved

    def cp(rc, stdout):
        return lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], rc, stdout, "")

    def timeout(*a, **k):
        raise subprocess.TimeoutExpired(a[0] if a else "powershell", 60)

    def missing(*a, **k):
        raise FileNotFoundError("powershell")
    c("standin_alive: a PowerShell call that times out does not raise: the pid counts as alive (VDR1-2)", with_ps(timeout, [True]) is True,
      str(with_ps(timeout, [True])))
    c("standin_alive: a PowerShell that cannot be started, or fails, counts the pid as alive", with_ps(missing, [True]) is True and with_ps(cp(1, ""), [True]) is True)
    c("standin_alive: an EMPTY command line of a pid that is still there is unreadable, so ALIVE - the docstring's word, now the code's "
      "(VDR1-3)", with_ps(cp(0, ""), [True, True]) is True and with_ps(cp(0, "  \r\n"), [True, True]) is True,
      str((with_ps(cp(0, ""), [True, True]), with_ps(cp(0, "  \r\n"), [True, True]))))
    c("standin_alive: an empty answer for a pid that has exited since the first look is the process gone between the two calls: dead",
      with_ps(cp(0, ""), [True, False]) is False)
    c("standin_alive: a command line that names card_stress_standin is alive, another program's (a recycled pid) is dead, and a pid that is "
      "not alive at the first look is dead without asking",
      with_ps(cp(0, "python card_stress_standin.py soak"), [True]) is True and with_ps(cp(0, "notepad.exe"), [True]) is False
      and with_ps(cp(0, "x"), [False]) is False)
    return out


def fx_cpu_filter_checks(env: Env, src: str = HERE) -> list:
    """DR2's note on python/figure_extracts.py: a `cpu` (host-pool) sweep leg runs beside the card and is no card activity. The stress figure's
    power by activity, made from a real run's metrics.jsonl (set CARD_STRESS_METRICS to it: the lead's stress copy is the committed figures'
    source), must be the same when a cpu leg sits over every telemetry sample - the samples taken between legs must not become 'sweep, host
    items only'. Skipped by name without the file."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    path = os.environ.get("CARD_STRESS_METRICS", "")
    if not path or not os.path.isfile(path):
        skip("fx filter", "set CARD_STRESS_METRICS to a finished run's metrics.jsonl (the stress copy the committed figures come from)")
        return out
    import importlib.util
    fe_path = os.path.join(src, "figure_extracts.py")
    if not os.path.exists(fe_path):
        fe_path = os.path.join(ROOT, "python", "figure_extracts.py")
    sys.path.insert(0, os.path.join(ROOT, "python"))
    try:
        spec = importlib.util.spec_from_file_location("figure_extracts_under_test", fe_path)
        FE = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(FE)
        base = FE.make_stress(path, root=ROOT)["data"]["telemetry"]["power_by_activity"]
        recs = L.read_records(path)[0]
        host_leg = next(r for r in recs if r.get("type") == "leg" and r.get("kind") == "sweep" and r["sweep"].get("op") == "nextup32"
                        and r["status"] == "pass")
        extra = [dict(host_leg, image="cpu", start_epoch=r["epoch"] - 0.5, end_epoch=r["epoch"] + 0.5)
                 for r in recs if r.get("type") == "telemetry" and r.get("epoch")]
        dp = os.path.join(env.tmp, "fx-doctored.jsonl")
        with open(dp, "w", encoding="utf-8", newline="\n") as fh:
            for r in recs + extra:
                fh.write(json.dumps(r) + "\n")
        withcpu = FE.make_stress(dp, root=ROOT)["data"]["telemetry"]["power_by_activity"]
        c("fx filter: the stress figure's power by activity from the real run, and from the same run with a cpu sweep leg over every telemetry "
          "sample, are the same: a pool slice is not 'sweep, host items only' (the samples between legs stay between legs)",
          base == withcpu and base["quad"]["between legs"]["n"] > 0, f"{base['quad'].get('between legs')} vs {withcpu['quad'].get('between legs')}, "
          f"host-only {base['quad'].get('sweep, host items only')} vs {withcpu['quad'].get('sweep, host items only')}")
    except Exception as e:
        c("fx filter: the stress figure could be made from the real run and from the doctored one", False, repr(e))
    finally:
        sys.path.remove(os.path.join(ROOT, "python"))
    return out


def group_items(env: Env, src: str = HERE) -> list:
    """Parcel DR3, the coverage wave's items in the driver: the catalog and its real logs, the plans, the served items and their refusals."""
    return index_item_checks(src) + index_plan_checks(src) + scn_index_items(env, src)


def group_chunk(env: Env, src: str = HERE) -> list:
    """Parcel DR3, the pass size: the tool's line read and held to the request, the rule for what is a repeat of what, the report, the run."""
    return chunk_unit_checks(src) + chunk_report_checks(env, src) + scn_chunk(env, src)


def group_records(env: Env, src: str = HERE) -> list:
    """Parcel DR3, signed records from the driver: the campaign's own space, the flags and their refusals, the sink on a real dry run's
    records, and a real (not dry) run over test doubles."""
    return (campaign_space_checks(src) + records_args_checks(env, src) + records_sink_checks(env, src) + scn_records_real(env, src))


def group_notes(env: Env, src: str = HERE) -> list:
    """Parcel DR3, four verifiers' notes: --quick --sweep-items stops after one empty wave, the Windows stand-in check, figure_extracts' filter."""
    return quick_empty_wave_checks(env, src) + standin_alive_checks() + fx_cpu_filter_checks(env, src)


# ---------------------------------------------------------------------------------------
# the plants: one defect put back into a copy of the code; the scenario for it must FAIL
# ---------------------------------------------------------------------------------------

def make_plant_copy(env: Env, name: str, edits: list) -> str:
    """A copy of hw/'s code (and this test) in a directory of its own with each edit applied.
    An edit that does not match exactly once is an error: a plant that did not apply would
    prove nothing."""
    d = os.path.join(env.tmp, "plant-" + name)
    os.makedirs(d, exist_ok=True)
    for f in os.listdir(HERE):
        if f.endswith((".py", ".sh")):
            shutil.copy(os.path.join(HERE, f), os.path.join(d, f))
    if os.path.isdir(FIX) and not os.path.exists(os.path.join(d, "card_stress_fixtures")):
        shutil.copytree(FIX, os.path.join(d, "card_stress_fixtures"))
    if any(e[0] == "figure_extracts.py" for e in edits):          # lives in python/, not hw/: a plant of it gets its own copy
        shutil.copy(os.path.join(ROOT, "python", "figure_extracts.py"), os.path.join(d, "figure_extracts.py"))
    for fname, old, new in edits:
        p = os.path.join(d, fname)
        with open(p, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
        if text.count(old) != 1:
            raise SystemExit(f"plant {name}: {old[:70]!r} found {text.count(old)} times in {fname}; "
                             f"the plant did not apply, so it would prove nothing")
        with open(p, "w", encoding="utf-8", newline="") as fh:
            fh.write(text.replace(old, new))
    return d


def plant_parsers(env: Env, src: str) -> list:
    """The parser group, run as a subprocess from the plant's directory (so it imports the plant's
    card_stress_lib), reading the real tree's tool sources."""
    e = dict(os.environ)
    e["CARD_STRESS_TEST_ROOT"] = ROOT
    p = subprocess.run([sys.executable, "-B", "-I", os.path.join(src, "test_card_stress.py"), "--only", "parsers", "--no-plants"],
                       capture_output=True, text=True, env=e, timeout=120)
    bad = [ln.strip()[6:].strip() for ln in p.stdout.splitlines() if ln.startswith("  FAIL  ")]
    if p.returncode != 0 and not bad:
        bad = [f"parser group crashed under the plant: {p.stderr[-200:]}"]
    return [(b, False, "") for b in bad] or [("parser group passes under the plant", True, "")]


def plant_standin(env: Env, src: str) -> list:
    """The `standin` group of THIS test (standin_alive's own checks), run as a subprocess from the plant's directory, so it tests the plant's
    copy of the test; every FAIL line it prints is a failing check, named by its text."""
    e = dict(os.environ)
    e["CARD_STRESS_TEST_ROOT"] = ROOT
    p = subprocess.run([sys.executable, "-B", "-I", os.path.join(src, "test_card_stress.py"), "--only", "standin", "--no-plants"],
                       capture_output=True, text=True, env=e, timeout=120)
    bad = [ln.strip()[6:].strip() for ln in p.stdout.splitlines() if ln.startswith("  FAIL  ")]
    if p.returncode != 0 and not bad:
        bad = [f"the standin group crashed under the plant: {p.stderr[-200:]}"]
    return [(b, False, "") for b in bad] or [("the standin group passes under the plant", True, "")]


def plant_report(env: Env, src: str) -> list:
    """The report's own test (hw/test_card_stress_report.py), run from the plant's directory so it tests the plant's
    report; every FAIL line it prints is a failing check, named by its text."""
    p = subprocess.run([sys.executable, "-B", "-I", os.path.join(src, "test_card_stress_report.py")], capture_output=True,
                       text=True, timeout=300)
    bad = [re.sub(r"^\s*FAIL \[[^\]]*\] ", "", ln).strip() for ln in p.stdout.splitlines() if ln.lstrip().startswith("FAIL [")]
    if p.returncode != 0 and not bad:
        bad = [f"the report test crashed under the plant: {p.stderr[-200:]}"]
    return [(b, False, "") for b in bad] or [("the report test passes under the plant", True, "")]


def plants(env: Env) -> None:
    """Each plant is one defect put back into a copy of the code, run through the scenario written for it,
    which must FAIL - and fail at the check named for it, not merely somewhere: an earlier draft of this
    went red for every plant because the copy's root was wrong and the driver refused to start. So a
    CONTROL run comes first: an unmodified copy, run through the heaviest scenarios, must pass every check."""
    streak_old = ('        elif st in ("timeout", "no_device"):\n            self.streak += 1\n'
                  '            if self.streak >= self.a.max_card_failures:')
    # CARD_STRESS_PLANT=<text>: a development aid - run only the plants whose name contains it, and no control
    pick = os.environ.get("CARD_STRESS_PLANT")
    if not pick:
        ctl = make_plant_copy(env, "control", [])
        for nm, fn in (("normal", scn_normal), ("fail", scn_fail_and_parse), ("nodevice", scn_nodevice),
                       ("parsers", plant_parsers)):
            res = fn(env, ctl)
            bad = [n for n, ok, _ in res if not ok]
            check(f"plants: the CONTROL (an unmodified copy of the code) passes the {nm} checks", not bad, "; ".join(bad)[:300])
        print("plants: control done")
    P = [
        ("a timed-out leg is not classified as a timeout",
         [("card_stress.py", '        if res.timed_out:\n            return ("timeout"', '        if False:\n            return ("timeout"')],
         scn_timeout, ["timeout: the hung leg is status timeout"]),
        ("the stop file is ignored",
         [("card_stress.py", '        if os.path.exists(self.stop_path):\n            return Stop("stop_file"',
           '        if False:\n            return Stop("stop_file"')],
         scn_stopfile, ["stopfile: it ended cleanly: reason stop_file", "stopfile: no leg started after STOP"]),
        ("the guard sees nobody",
         [("card_stress.py", "            users, beside = find_card_users()\n", "            users, beside = [], []\n")],
         scn_guard, ["guard: another process on the card"]),
        ("the disk floor is never checked",
         [("card_stress.py", "            if free < self.a.disk_floor_gb:", "            if False:")],
         scn_diskfloor, ["disk floor: below the floor the driver stops before any leg"]),
        ("a slice that failed to finish is counted covered",
         [("card_stress_lib.py", '        if not item or r.get("status") not in ("pass", "fail"):',
           '        if not item or r.get("status") not in ("pass", "fail", "no_device", "timeout"):')],
         scn_sweep, ["sweep resume: the slice that lost the device before the restart was redone FIRST",
                     "sweep: the coverage the records give is the passed slice alone"]),
        ("a wrong image's SHA-256 is not checked",
         [("card_stress.py", '                if e.get("image_sha256") != img.sha:', "                if False:")],
         scn_fail_and_parse, ["fail: a dt-i that read another image's SHA-256 is a wrong answer"]),
        ("a soak that ran on the software backend passes",
         [("card_stress_lib.py", "        if not dev or sw:\n", "        if False:\n")],
         scn_soak_software, ["a card soak that says 'software backend' is parse_error"]),
        ("nextup32's eight edge cases are forgotten",
         [("card_stress_lib.py", 'verdict_mode="-", extra_cases=8, exact=True))\n    items.append(Item("nextdown32"',
           'verdict_mode="-", extra_cases=0, exact=True))\n    items.append(Item("nextdown32"')],
         scn_normal, ["normal: exit 0, every leg passed"]),
        ("the second consecutive failure does not open another image",
         [("card_stress.py", "        if streak >= 2:\n            other = self.other_image(img)",
           "        if streak >= 99:\n            other = self.other_image(img)")],
         scn_nodevice, ["nodevice: after the second it opens ANOTHER image"]),
        ("the run never stops for a card that does not answer",
         [("card_stress.py", streak_old, streak_old.replace("if self.streak >= self.a.max_card_failures:", "if False:"))],
         scn_cardlost, ["cardlost: after N consecutive failures the driver stops with exit 3"]),
        ("a log with no verdict line passes api-test",
         [("card_stress_lib.py", '    if len(p) + len(f) != 1:\n        raise VerdictError(f"api-test: expected one verdict line',
           '    if False:\n        raise VerdictError(f"api-test: expected one verdict line')],
         scn_fail_and_parse, ["fail: a log no parser can read is parse_error", "the scenario crashed"]),
        ("SIGTERM is not handled",
         [("card_stress.py", "        for s in (signal.SIGINT, signal.SIGTERM):\n            try:\n                signal.signal(s, handler)",
           "        for s in ():\n            try:\n                signal.signal(s, handler)")],
         scn_signal, ["signal: one SIGTERM"]),
        ("an unexpected exception in a cycle ends the run",
         INJECT + [("card_stress.py", "                except Exception as e:\n                    # An unexpected",
                    "                except ZeroDivisionError as e:\n                    # An unexpected")],
         scn_internal_error, ["internal error: an unexpected exception in a cycle is recorded"]),
        ("an --out inside the checkout is accepted",
         [("card_stress.py", "        rel = os.path.relpath(self.out, self.root)\n",
           "        return None\n        rel = os.path.relpath(self.out, self.root)\n")],
         scn_build_refusals, ["build: an --out inside the checkout"]),
        ("the XRT-link assertion is dropped",
         [("card_stress.py", 'step(f"xrt {exe}", rc == 0 and "xrt_coreutil" in out,', 'step(f"xrt {exe}", rc == 0,')],
         scn_buildreal, ["buildreal: tools that ldd says do not link XRT"]),
        ("an item whose slices cannot be read is never disabled",
         [("card_stress.py", "                if self.item_bad[it.name] > self.a.quarantine_after:", "                if False:")],
         scn_item_disabled, ["item disabled: the item whose logs cannot be read"]),
        ("a torn last line of metrics.jsonl is not repaired on resume",
         [("card_stress.py", "        self.repair_tail()\n        recs, _partial, bad = L.read_records(self.metrics)",
           "        recs, _partial, bad = L.read_records(self.metrics)")],
         scn_torn_tail, ["torn tail: the resume ran"]),
        ("an optional tool that is not XRT-linked stops the whole run",
         [("card_stress.py", '            if exe in optional and not (rc == 0 and "xrt_coreutil" in out):', "            if False:")],
         scn_buildreal, ["buildreal: an optional tool (cft-selftest)"]),
        ("the exit status is not compared with the verdict",
         [("card_stress_lib.py", "    if ok and rc != 0:", "    if False:")],
         plant_parsers, ["a pass line with a nonzero exit status is refused", "pass with exit status 1 is refused"]),
        ("verify-image.sh is counted as a card user",
         [("card_stress.py", '"card-identity.sh",\n                "seq_check.py"',
           '"card-identity.sh",\n                "verify-image.sh", "seq_check.py"')],
         lambda env, src: group_commands(src), ["guard rules: hw/verify-image.sh"]),
        ("a verdict line's count is read as 0 when its pattern misses",
         [("card_stress_lib.py", '    m = _one(DT_TOTAL, text, "device-test totals")\n    checks, failed = int(m.group(1)), int(m.group(2))',
           '    m = DT_TOTAL.search(text)\n    checks, failed = (int(m.group(1)), int(m.group(2))) if m else (0, 0)')],
         plant_parsers, ["no totals line is refused"]),
        # parcel EX: the exhaustive conversion and scaleB items, and which items reach the tile
        ("a slice that ran one encoding short is covered",
         [("card_stress_lib.py", '        if enc != cover["encodings"]:', "        if False:")],
         lambda env, src: scn_sweep_short(env, src, SWEEP_ALL_BASE) + plant_parsers(env, src),
         ["sweep short cvtto32-all-rne: the first 2 slice(s) came back short", "a slice shorter by one encoding than the log is refused"]),
        ("a slice that made one check too few is covered",
         [("card_stress_lib.py", "        if cases + skp != want:", "        if False:")],
         lambda env, src: scn_sweep_short(env, src, SWEEP_ALL_BASE) + plant_parsers(env, src),
         ["sweep short cvtto32-all-rup: the first 2 slice(s)", "sweep short cvtto32-all-rne: the first 2 slice(s) came back short",
          "the log with one case more printed is refused"]),
        ("the driver does not hold a slice to what it covered",
         [("card_stress.py", '            cover = job["cover"]\n', "            cover = None\n")],
         lambda env, src: scn_sweep_short(env, src, SWEEP_ALL_BASE),
         ["sweep short scaleb32-wide-rne: the first 3 slice(s) came back short"]),
        ("the host pool does not hold a slice to what it covered",
         [("card_stress.py", '        exp, cover = job["expected"], job["cover"]\n', '        exp, cover = job["expected"], None\n')],
         lambda env, src: scn_sweep_short(env, src, SWEEP_ALL_BASE),
         ["sweep short cvtto32-all-rne: the first 2 slice(s) came back short"]),
        ("a refused slice is counted covered, so a restart skips it",
         [("card_stress_lib.py", '        if not item or r.get("status") not in ("pass", "fail"):',
           '        if not item or r.get("status") not in ("pass", "fail", "parse_error"):')],
         lambda env, src: scn_sweep_short(env, src, SWEEP_ALL_BASE) + scn_sweep_gap(env, src, SWEEP_ALL_BASE),
         ["sweep short cvtto32-all-rne: the refused slices are not covered", "sweep gap: the resumed run served the refused slice FIRST"]),
        ("a slice that compared nothing because every pair was skipped is refused",
         [("card_stress_lib.py", "    elif expected_cases is None and cases == 0:", "    if expected_cases is None and cases == 0:")],
         plant_parsers, ["a slice that compared nothing because every pair was skipped (all NaN) is a pass"]),
        ("the stand-in prints the wrong count of checks for scaleb32-wide",
         [("card_stress_standin.py", '"scaleb32-all": 17, "scaleb32-wide": 568}', '"scaleb32-all": 17, "scaleb32-wide": 567}')],
         plant_parsers, ["the dry-run stand-in prints the real tool's line for this slice", "the stand-in's per-encoding table is the library's"]),
        ("the library's per-encoding count for scaleb32-wide is one too many",
         [("card_stress_lib.py", '"scaleb32-all": 17, "scaleb32-wide": 556 + 12}', '"scaleb32-all": 17, "scaleb32-wide": 556 + 13}')],
         plant_parsers, ["PER_ENCODING's scaleb counts are the C source's lists"]),
        ("remainder is marked as reaching the tile",
         [("card_stress_lib.py", '"rem32": HOST, "rem64": HOST,', '"rem32": TILE, "rem64": HOST,')],
         lambda env, src: group_commands(src), ["reach: of the 54 random items 25 reach the tile"]),
        ("a driver that does not record an item's reach",
         [("card_stress.py", '                                "reach": it.reach, "lo": lo, "hi": hi, "tile": None}',
           '                                "lo": lo, "hi": hi, "tile": None}')],
         lambda env, src: scn_sweep_all(env, src), ["sweep all conv32to64-all: every record says its reach (host)"]),
        ("the status file does not state which items reach the tile",
         [("card_stress.py", '            lines.append("reach      " + "; ".join(', '            lines.append("xreach     " + "; ".join(')],
         lambda env, src: scn_sweep_all(env, src), ["sweep all: status.txt says what the tile has seen"]),
        ("the report prints every item as reaching the tile",
         [("card_stress_report.py", '                      _reach_text(e["reach"])]\n                     for e in W["exhaustive"]])',
           '                      "tile"]\n                     for e in W["exhaustive"]])')],
         plant_report, ["sweep.exh[logb32].reach", "sweep.exh[conv32to64-all].reach", "sweep.exh[cvtfrom32-all-rne].reach"]),
        ("the report totals the coverage by reach wrongly (every item counted as a tile item)",
         [("card_stress_report.py", '        mine = [e for e in exh if e["reach"] == key]\n',
           '        mine = [e for e in exh if (e["reach"] == key or key == TILE)]\n')],
         plant_report, ["sweep.total.reach"]),
        ("the report prints every exhaustive item as a host item, whatever the records say",
         [("card_stress_report.py", '                      _reach_text(e["reach"])]\n                     for e in W["exhaustive"]])',
           '                      "host"]\n                     for e in W["exhaustive"]])')],
         lambda env, src: scn_report(env, src), ["report: and its reach column (the last) is what the driver wrote into every one of its records"]),
        # parcel DR1 (2026-10-20): the telemetry sampler's order, the revision-8 table, --quick with --sweep-items
        ("the telemetry sampler is not serialised",
         [("card_stress.py", "        with self.tel_lock:\n            self.take_sample(when, img)\n", "        self.take_sample(when, img)\n")],
         lambda env, src: telemetry_order_checks(src) + scn_telemetry_hang(env, src),
         ["telemetry: two samples that overlap are recorded in the order their readings were taken",
          "telemetry hang: no two samples ran at once"]),
        ("the run's stop does not reach a timer sample in flight",
         [("card_stress.py", '                    if when == "timer" and self.tel_stop.is_set():\n'
           '                        return          # the run is ending and its own "end" sample is next: not behind this one\n', "")],
         lambda env, src: telemetry_order_checks(src),
         ["telemetry: a timer sample the run's stop reaches while it is in flight is dropped"]),
        ("the driver appends telemetry records in swapped pairs",
         [("card_stress.py", "        self.rec(rec)\n        self.last_tel = rec\n",
           "        held = getattr(self, '_held', None)\n        if held is None:\n            self._held = rec\n"
           "        else:\n            self.rec(rec)\n            self.rec(held)\n            self._held = None\n"
           "        self.last_tel = rec\n")],
         scn_telemetry, ["telemetry: the stand-in's temperature rises with time and the samples show it, in order"]),
        ("the revision-8 table drops a routine entry",
         [("card_stress.py", '"culture-rk4-tangent-fp64", "culture-rk4-tangent-fp256")', '"culture-rk4-tangent-fp64")')],
         lambda env, src: group_commands(src), ["REV8_ENTRIES is acceptance.py's table"]),
        ("a routine entry counts as an image that is not cached",
         [("card_stress.py", "            missing = [e for e in chosen if e not in REV8_ROUTINE_ENTRIES\n                       and not all(",
           "            missing = [e for e in chosen\n                       if not all(")],
         lambda env, src: group_commands(src), ["acceptance-rev8: the routine entries are never 'uncached'",
                                                "acceptance-rev8: with every workload cached the quad runs fifteen"]),
        ("the revision-8 leg does not name --lib for the routine entries",
         [("card_stress.py", '                argv += ["--lib", os.path.join(R, "host", "libcft.so")]\n', "                pass\n")],
         lambda env, src: group_commands(src), ["acceptance-rev8 on the quad: the routine entries make the leg name --lib"]),
        ("--quick ignores --sweep-items again",
         [("card_stress.py", "        if self.sweep_only:\n            names = [n for n in dict.fromkeys(self.sweep_only)",
           "        if False:\n            names = [n for n in dict.fromkeys(self.sweep_only)")],
         lambda env, src: group_commands(src) + scn_quick_sweep(env, src),
         ["quick with --sweep-items: the quad's wave is four jobs", "quick sweep: with --sweep-items naming 22 items"]),
        ("an item outside --sweep-items is called covered in the empty wave's sentence",
         [("card_stress.py", '                return "outside --sweep-items", n\n', '                return "covered", n\n')],
         lambda env, src: group_commands(src), ["empty wave, the case of 2026-10-19"]),
        ("an empty wave still says the campaign is finished",
         [("card_stress.py", "                why, cause = self.why_no_wave(forced)\n",
           '                why, cause = "nothing left to run in this campaign", "finished"\n')],
         lambda env, src: scn_quick_sweep(env, src),
         ["quick sweep: the empty wave that follows says it is blocked"]),
        # verifier-VDR1's two (2026-10-20): "finished" decided over the campaign, and the smoke's next item
        ("the finished sentence is decided over the wave's list again",
         [("card_stress.py", "        campaign = named or [it.name for it in self.items]\n",
           "        campaign = list(forced) if forced else (named or [it.name for it in self.items])\n")],
         lambda env, src: group_commands(src), ["empty wave, a single image whose sqrt32-rne is covered"]),
        ("an empty quick wave ends the image's sweep again",
         [("card_stress.py", "                if self.quick and not self.sweep_only and waves + 1 < self.quick_waves(img):\n",
           "                if False:\n")],
         lambda env, src: group_commands(src), ["quick: a single image whose first item cannot run goes on to its second"]),
        # the lead's question about ab92598: the narrowed pid test must still see a stand-in that really is left hung
        ("a hung examine call is not killed at its timeout",
         [("card_stress.py", "def expand(path: str) -> str:\n    return os.path.expandvars(os.path.expanduser(path))\n",
           "def expand(path: str) -> str:\n    return os.path.expandvars(os.path.expanduser(path))\n\n\n"
           "def _run_no_kill(argv, timeout):\n"
           "    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)\n"
           "    out, err = p.communicate(timeout=timeout)     # a timeout raises and the child is left running: the defect\n"
           "    return subprocess.CompletedProcess(argv, p.returncode, out, err)\n"),
          ("card_stress.py", 'p = subprocess.run(argv + ["--format", "JSON", "--output", path], capture_output=True,\n'
           '                                   text=True, timeout=a.telemetry_timeout)',
           'p = _run_no_kill(argv + ["--format", "JSON", "--output", path], a.telemetry_timeout)'),
          ("card_stress.py", "p = subprocess.run(argv, capture_output=True, text=True, timeout=a.telemetry_timeout)",
           "p = _run_no_kill(argv, a.telemetry_timeout)")],
         lambda env, src: scn_telemetry_hang(env, src),
         ["telemetry hang: every examine call hung and was killed at --telemetry-timeout"]),
        # parcel DR2 (2026-10-20): the host pool, the seeds, coverage by tree
        ("a host job inherits CFT_SOAK_ARTIFACT and CFT_XRT_TILES from the driver's environment",
         [("card_stress.py", "        for k in drop:\n            env.pop(k, None)\n", "        for k in ():\n            env.pop(k, None)\n")],
         scn_normal, ["normal: no host job named the card although the driver's own environment did"]),
        ("the card's sweep picks host items too (and the pool tile items)",
         [("card_stress.py", "            if reach is not None and it.reach != reach:\n                continue\n",
           "            if False:\n                continue\n")],
         lambda env, src: pool_unit_checks(src), ["pool: over a whole rotation the card's waves plan the 65 TILE items", "pool: and the pool's slices are the 60 HOST items"]),
        ("the host pool does not look for a stop before it starts a slice",
         [("card_stress.py", "                stop = self.should_stop()\n                if stop is not None:",
           "                stop = None\n                if stop is not None:")],
         lambda env, src: pool_unit_checks(src) + scn_pool_stop(env, src),
         ["pool stop: no host slice STARTED after STOP", "pool: a worker started below the disk floor plans nothing"]),
        ("the host pool's workers do not test the tree before they start a slice",
         [("card_stress.py", "                stop = self.should_stop()\n                if stop is not None:",
           "                stop = self.should_stop(git=False)\n                if stop is not None:")],
         lambda env, src: pool_tree_unit_checks(src) + scn_pool_tree(env, src),
         ["pool tree: after HEAD moved no host slice STARTED", "pool tree: a worker started after HEAD moved plans nothing"]),
        ("the tree test stays off in a dry run even when asked for",
         [("card_stress.py", "        self.tree_check = (not a.dry_run) or bool(getattr(a, \"check_tree_in_dry_run\", False))",
           "        self.tree_check = not a.dry_run")],
         lambda env, src: pool_tree_unit_checks(src),
         ["pool tree: before HEAD moves no driver is told to stop", "pool tree: the main loop's test says tree_moved"]),
        ("a host job the run's end terminated is recorded as a slice of its item",
         [("card_stress.py", "        if slot[\"abandon\"] or (self.hard and res.killed):\n", "        if False:\n")],
         scn_pool_stop, ["pool stop: the hung host job was terminated", "pool deadline: the run ended at the deadline"]),
        ("a CPU job's log that names a DEVICE passes",
         [("card_stress_lib.py", "        if dev:\n            raise VerdictError(f\"{CPU_OPENED_CARD}", "        if False:\n            raise VerdictError(f\"{CPU_OPENED_CARD}")],
         lambda env, src: cpu_parse_checks(src), ["cpu parser c5-nextup32.txt"]),
        ("a host job's log is read for the card's failures: 'no such device' is no_device",
         [("card_stress.py", "            infra = L.classify_infra(text) if cmd.card else None\n", "            infra = L.classify_infra(text)\n")],
         scn_pool_failure, ["pool failure: a host job that prints 'no such device' is a parse_error of ITS item"]),
        ("a host job's failure is counted in the card's streak",
         [("card_stress.py", "        with self.pool_lock:\n            self.pool_served += 1\n",
           "        with self.pool_lock:\n            self.pool_served += 1\n            if rec[\"status\"] != \"pass\":\n                self.streak += 1\n")],
         scn_pool_failure, ["pool failure: nor did it start the card's recovery ladder"]),
        ("a resumed run does not read the cpu image's slices",
         [("card_stress_lib.py", "        if r.get(\"type\") != \"leg\" or r.get(\"kind\") != \"sweep\":\n            continue\n        sw = r.get(\"sweep\") or {}\n        item = sw.get(\"item\")\n",
           "        if r.get(\"type\") != \"leg\" or r.get(\"kind\") != \"sweep\" or r.get(\"image\") == \"cpu\":\n            continue\n        sw = r.get(\"sweep\") or {}\n        item = sw.get(\"item\")\n")],
         scn_pool_resume, ["pool resume: the resumed run's first host slice starts exactly where run A's coverage ended"]),
        ("a failure in the card's cycle terminates the host pool's jobs too",
         INJECT + [("card_stress.py", "                    self.terminate_children(card_only=True)\n", "                    self.terminate_children()\n")],
         scn_pool_survives, ["pool survives: the host job in flight when the card's cycle failed ran to its end"]),
        ("a host job is not niced",
         [("card_stress.py", "            if self.a.nice and shutil.which(\"nice\"):\n",
           "            if self.a.nice and shutil.which(\"nice\") and not threading.current_thread().name.startswith(\"host-pool\"):\n")],
         scn_pool_nice, ["pool nice (POSIX): a host job runs at `nice -n 10`"]),
        ("the metrics file is written by several threads without a lock",
         [("card_stress_lib.py", "    with _APPEND_LOCK:\n        now = time.time()", "    if True:\n        now = time.time()")],
         lambda env, src: append_lock_checks(src), ["pool: no two threads are ever inside the metrics file's write at once"]),
        ("the seeds are the old schedule again (base_seed + 7919 n)",
         [("card_stress_lib.py", "        return (self.seed_index << 40) | (n << 1) | 1\n", "        return self.base_seed + 7919 * n\n")],
         lambda env, src: seed_checks(src) + scn_seeds(env, src),
         ["seeds: over the 54 random items x 605 slice numbers", "seeds A: a fresh run draws both items"]),
        ("--earlier-runs is accepted and ignored",
         [("card_stress.py", "        if not self.a.earlier_runs:\n            return\n        try:\n", "        return\n        try:\n")],
         scn_seeds, ["seeds B: a new --out naming run A starts each item at A's highest n + 1"]),
        ("a slice may start the tool from a state another (item, n) already used",
         [("card_stress.py", "                if prior is not None and prior != (it.name, n):\n", "                if False:\n")],
         lambda env, src: pool_unit_checks(src), ["seeds: a slice whose tool state another (item, n) already started from is refused"]),
        ("the pool lets two workers take one item at once",
         [("card_stress.py", "            wave = self.plan_wave(self.cpu, remaining, 1, forced, L.HOST, set(self.pool_busy))\n",
           "            wave = self.plan_wave(self.cpu, remaining, 1, forced, L.HOST, set())\n")],
         lambda env, src: pool_unit_checks(src), ["pool: two workers never take one item at once"]),
        ("the seed guard refuses a slice served again after a failure",
         [("card_stress.py", "                if prior is not None and prior != (it.name, n):\n", "                if prior is not None:\n")],
         lambda env, src: pool_unit_checks(src), ["seeds: the same item and n again (a slice served again after a failure) is not refused"]),
        ("an item's seed index is its place in the catalog, not in the table",
         [("card_stress_lib.py", "            it.seed_index = RANDOM_SEED_INDEX[it.name]\n",
           "            it.seed_index = [x.kind for x in items[:items.index(it)]].count(\"random\")\n")],
         lambda env, src: seed_checks(src), ["seeds: an item's seeds do not depend on which other items exist"]),
        ("the driver does not record the tree it runs from",
         [("card_stress.py", "        self.tree.update(self.tree_facts())\n", "")],
         tree_record_checks, ["trees: run_start records the tree the driver runs from"]),
        ("the report counts every tile item under one tree",
         [("card_stress_report.py", "        return (h + (\"+modified\" if mod else \"\"),\n                f\"RTL tree {h[:12]}\"",
           "        return (\"one\",\n                f\"RTL tree {h[:12]}\"")],
         scn_trees, ["trees: a tile item's coverage is counted per RTL tree"]),
        ("the report counts a host item's coverage under the host/ tree alone, not the compiler",
         [("card_stress_report.py", "        return (h + (\"+modified\" if mod else \"\") + \"|\" + (cc or \"compiler not recorded\"),",
           "        return (h + (\"+modified\" if mod else \"\"),")],
         scn_trees, ["trees: a host item's coverage is counted by what it is about"]),
        ("the report adds the images' coverage of a tree instead of taking its union",
         [("card_stress_report.py", "                cov = covered([iv for v in per.values() for iv in v[\"iv\"]])\n",
           "                cov = sum(covered(v[\"iv\"]) for v in per.values())\n")],
         scn_trees, ["trees: and the images are reported separately beneath the tree"]),
        # parcel DR3 (2026-10-21): the index-based items, the pass size, the signed records, four verifiers' notes
        ("an index-based hard-case item says nothing of what its slice covered",
         [("card_stress_lib.py", 'per_encoding=k, space=space, level="hard", whole=HARD_WHOLE[op]))',
           'per_encoding=None, space=space, level="hard", whole=HARD_WHOLE[op]))')],
         lambda env, src: index_item_checks(src), ["index items: each has the documents' space, k, reach, tool"]),
        ("cvtto64-class is held to k x E cases though it skips pairs",
         [("card_stress_lib.py", 'exact=op != "cvtto64-class", per_encoding=k', 'exact=True, per_encoding=k')],
         lambda env, src: index_item_checks(src), ["index cl-cvtto64-class.txt: made by cvtto64-class-rup's command line"]),
        ("the stand-in's skipped slots for div32-hard are one off the whole space's",
         [("card_stress_standin.py", '"div32-hard": (21235788, 4, 20596560)', '"div32-hard": (21235788, 4, 20596561)')],
         lambda env, src: index_item_checks(src), ["index items: the stand-in's tables"]),
        ("a hard-case item is marked as a host item",
         [("card_stress_lib.py", '"div32-hard": TILE, "div64-hard": TILE, "sqrt64-hard": TILE,', '"div32-hard": HOST, "div64-hard": TILE, "sqrt64-hard": TILE,')],
         lambda env, src: group_commands(src), ["reach: every item is marked as its operation's family is"]),
        ("the driver's gap is over 2^32 encodings, not the item's own space",
         [("card_stress.py", "gap = L.first_gap(have, it.space)", "gap = L.first_gap(have)")],
         lambda env, src: index_plan_checks(src),
         ["index plan: the last slice is short and ends exactly at the space's end", "index plan: rint64-class-rne's first slice is the WHOLE space"]),
        ("the status file counts every exhaustive item over 2^32",
         [("card_stress.py", "ex_total += it.space", "ex_total += L.EXH")],
         lambda env, src: scn_index_items(env, src), ["index items: status.txt counts the seven items' indices"]),
        ("the report counts every exhaustive item over 2^32",
         [("card_stress_report.py", "space = ITEM_SPACE.get(it, EXH)", "space = EXH")],
         lambda env, src: scn_index_items(env, src), ["index items: the report counts each item over its own space"]),
        ("the whole-space check never runs",
         [("card_stress.py", "                    ev += self.whole_space_events(it)\n", "")],
         lambda env, src: scn_index_items(env, src),
         ["index items: the whole-space check ran once for each of the seven items", "index short: sqrt64-hard-rmm, whose every slice is one skipped slot off"]),
        ("the driver does not hold an index item's slice to what it covered (the card's path)",
         [("card_stress.py", '            cover = job["cover"]\n', "            cover = None\n")],
         lambda env, src: scn_index_refusals(env, src), ["index short div32-hard-rne: the first 3 slice(s) came back short"]),
        ("the host pool does not hold an index item's slice to what it covered",
         [("card_stress.py", '        exp, cover = job["expected"], job["cover"]\n', '        exp, cover = job["expected"], None\n')],
         lambda env, src: scn_index_refusals(env, src), ["index short cvtto64-class-rne: the first 1 slice(s) came back short"]),
        # the pass size
        ("a pass-size line that disagrees with the request is accepted",
         [("card_stress_lib.py", "        if int(cl.group(1)) != chunk or int(cl.group(2)) != chunk:", "        if False:")],
         lambda env, src: chunk_unit_checks(src) + scn_chunk(env, src),
         ["asked at 8192, at 4096 or as the default tool it is refused", "chunk run: the two slices whose tool left out its line"]),
        ("a default job's log that carries a pass-size line is accepted",
         [("card_stress_lib.py", "    if chunk is None:\n        if cl:\n", "    if chunk is None:\n        if False:\n")],
         lambda env, src: chunk_unit_checks(src) + scn_chunk(env, src),
         ["asked at 8192, at 4096 or as the default tool it is refused", "no chunk: a default job whose tool says it ran at a pass size is refused"]),
        ("the pool's slices are not held to the pass size",
         [("card_stress.py", "cpu=True, chunk=self.chunk)), card=False)", "cpu=True)), card=False)")],
         lambda env, src: scn_chunk(env, src), ["chunk run: every slice that passed carries the batch and chunk its tool said"]),
        ("the card's slices are not held to the pass size",
         [("card_stress.py", "t, rc, it.op, it.verdict_mode, img.path, exp, cover, chunk=self.chunk)))", "t, rc, it.op, it.verdict_mode, img.path, exp, cover)))")],
         lambda env, src: scn_chunk(env, src), ["chunk run: every slice that passed carries the batch and chunk its tool said"]),
        ("the sweep runs the default tools whatever --sweep-chunk says",
         [("card_stress.py", 'f"{name}-c{self.chunk}" if self.chunk else name', "name")],
         lambda env, src: scn_chunk(env, src),
         ["chunk run: every slice that passed carries the batch and chunk its tool said", "chunk run: the tools the sweep ran are the -c16384 ones"]),
        ("random scaleB is not held to the cases its BATCH gives",
         [("card_stress.py", 'job["expected"] = it.random_cases(units, self.batch) if self.chunk else None', 'job["expected"] = None')],
         lambda env, src: scn_chunk(env, src), ["chunk run: a random scaleB slice is held to the cases its BATCH gives"]),
        ("the build step does not build the chunked tools",
         [("card_stress.py", "        if self.chunk:\n            # --sweep-chunk N: the sweep's slices run the tools built at pass size N",
           "        if False:\n            # --sweep-chunk N: the sweep's slices run the tools built at pass size N")],
         lambda env, src: scn_records_real(env, src), ["records real (B): the build step ran the default make and then"]),
        ("the chunked build leaves out the default build's XRT flags",
         [("card_stress.py", '            cargv = ["make", "-C", host, f"-j{a.build_jobs}"] + xrt_flags\n', '            cargv = ["make", "-C", host, f"-j{a.build_jobs}"]\n')],
         lambda env, src: scn_records_real(env, src), ["records real (B): the build step ran the default make and then"]),
        ("a cvtfrom slice's stream is keyed by its tool state alone, whatever the batch",
         [("card_stress_lib.py", "    return (seed | 1, batch) if op in LAYOUT_OPS else seed | 1", "    return seed | 1")],
         lambda env, src: chunk_unit_checks(src), ["a cvtfrom slice from a state a slice at the SAME batch used is refused"]),
        ("every random item's stream is keyed by its batch",
         [("card_stress_lib.py", "    return (seed | 1, batch) if op in LAYOUT_OPS else seed | 1", "    return (seed | 1, batch)")],
         lambda env, src: chunk_unit_checks(src), ["chunk streams: every other item is keyed by its state alone"]),
        ("--earlier-runs floors a cvtfrom item by slices of every batch",
         [("card_stress_lib.py", "        if batch is not None:\n            # a layout-dependent item's highest n", "        if False:\n            # a layout-dependent item's highest n")],
         lambda env, src: chunk_unit_checks(src), ["chunk streams: --earlier-runs:"]),
        ("the report keys a random item's coverage by item alone, chunked or not",
         [("card_stress_report.py", 'rk = item if bt == DEFAULT_BATCH else f"{item} @batch {bt}"', "rk = item")],
         lambda env, src: chunk_report_checks(env, src), ["chunk report: coverage by tree keeps a random item's chunked and default streams"]),
        ("the report says nothing of the pass size",
         [("card_stress_report.py", '    if W.get("batches"):', "    if False:")],
         lambda env, src: chunk_report_checks(env, src), ["chunk report: a run with chunked slices says the pass size"]),
        # the signed records
        ("--records is accepted with --dry-run",
         [("card_stress.py", '        if a.dry_run:\n            ap.error("--records: refused with --dry-run.', '        if False:\n            ap.error("--records: refused with --dry-run.')],
         lambda env, src: records_args_checks(env, src), ["records args: --records with --dry-run is refused by name"]),
        ("a key inside a git working tree is not refused at the command line",
         [("card_stress.py", "                    SR.load_seed(a.sign_key)\n                except SR.Refusal as e:", "                    pass\n                except SR.Refusal as e:")],
         lambda env, src: records_args_checks(env, src),
         ["records args: a key path inside this repository is refused by name (key-in-tree)", "records args: a real key file inside ANOTHER git working tree"]),
        ("the key's secret is read into a setting",
         [("card_stress.py", "                    SR.load_seed(a.sign_key)\n                except SR.Refusal as e:",
           "                    a.sign_seed = SR.load_seed(a.sign_key).hex()\n                except SR.Refusal as e:")],
         lambda env, src: records_args_checks(env, src) + scn_records_real(env, src),
         ["records args: a good key and --records", "records real (A): signed by the throwaway key"]),
        ("the exporter accepts a dry run's legs",
         [("sweep_record.py", '            if isinstance(rec.get("settings"), dict) and rec["settings"].get("dry_run"):', "            if False:")],
         lambda env, src: records_sink_checks(env, src),
         ["records sink: the dry run's records fed as they stand are REFUSED by the exporter", "records sink: and the exporter itself still refuses that run_start"]),
        ("the sink offers a host-pool slice to the exporter",
         [("card_stress.py", '                    if rec.get("image") == L.CPU:', "                    if False:")],
         lambda env, src: records_sink_checks(env, src), ["records sink: the host-pool slices are counted, not offered to the exporter"]),
        ("a refusal escapes the record sink",
         [("card_stress.py", '            except self.SR.Refusal as e:\n                if typ == "run_start":', '            except KeyError as e:\n                if typ == "run_start":')],
         lambda env, src: records_sink_checks(env, src),
         ["records sink: the dry run's records fed as they stand are REFUSED by the exporter",
          "records sink: a leg whose counts the exporter refuses is a record_refused event"]),
        ("a resumed sink does not know the campaigns already in its file",
         [("card_stress.py", '                self.ex.seen.add(r["id"])', "                pass")],
         lambda env, src: records_sink_checks(env, src), ["records sink: a resumed run's sink adopts the file"]),
        ("a resumed sink appends another key's records to the file",
         [("card_stress.py", '                if r["run"]["device"] != self.ex.device:', "                if False:")],
         lambda env, src: records_sink_checks(env, src), ["records sink: a resume with ANOTHER key is refused by name"]),
        ("Driver.rec does not feed the record sink",
         [("card_stress.py", "        if self.sink is not None:\n            self.sink.feed(rec)", "        if False:\n            self.sink.feed(rec)")],
         lambda env, src: records_sink_checks(env, src), ["records sink: through Driver.rec the same stream"]),
        ("a campaign says 2^32 for an item whose space is smaller (the space forced back)",
         [("sweep_record.py", 'c["space"], c["exact"] = getattr(it, "space", L.EXH), bool(it.exact)', 'c["space"], c["exact"] = L.EXH, bool(it.exact)')],
         lambda env, src: campaign_space_checks(src),
         ["campaign space: counts_problem refuses an interval one past a new item's real space",
          "campaign space: each of the 35 new items' campaign says its own space"]),
        # the verifiers' notes
        ("--quick with --sweep-items tries a second wave after an empty one",
         [("card_stress.py", "                if self.quick and not self.sweep_only and waves + 1 < self.quick_waves(img):",
           "                if self.quick and waves + 1 < self.quick_waves(img):")],
         lambda env, src: quick_empty_wave_checks(env, src), ["quick sweep: with --sweep-items an empty wave ends the image's sweep at once"]),
        ("standin_alive lets a PowerShell timeout escape",
         [("test_card_stress.py", "    except (subprocess.TimeoutExpired, OSError):\n        return True\n    if q.returncode != 0:",
           "    except OSError:\n        return True\n    if q.returncode != 0:")],
         plant_standin, ["standin_alive: a PowerShell call that times out does not raise"]),
        ("standin_alive counts an empty command line as dead",
         [("test_card_stress.py", '    if not q.stdout.strip():\n        return pid_alive(pid)\n    return "card_stress_standin" in q.stdout',
           '    return "card_stress_standin" in q.stdout')],
         plant_standin, ["standin_alive: an EMPTY command line of a pid that is still there"]),
        ("a job asked at the default pass size 4096 is recorded as having no pass size",
         [("card_stress_lib.py", '        pass_size = {"batch": DEFAULT_BATCH, "chunk": DEFAULT_BATCH}', "        pass_size = {}")],
         lambda env, src: chunk_unit_checks(src), ["chunk: a tool built at 4096 prints no pass-size line"]),
        ("a --sweep-chunk that is no multiple of 4096 up to 65536 is accepted",
         [("card_stress.py", "    if a.sweep_chunk is not None and not (4096 <= a.sweep_chunk <= 65536 and a.sweep_chunk % 4096 == 0):", "    if False:")],
         lambda env, src: scn_chunk(env, src), ["chunk args: a pass size that is not a positive multiple of 4096 up to 65536 is refused by name"]),
        ("a torn last line of the records file is not cut back on resume",
         [("card_stress.py", '            with open(self.path, "r+b") as fh:\n                fh.truncate(cut)', '            with open(self.path, "r+b") as fh:\n                pass')],
         lambda env, src: records_sink_checks(env, src), ["records sink: a torn last line (a write cut short) is cut back to the last whole record"]),
        ("figure_extracts counts a host-pool slice as sweep activity beside the card",
         [("figure_extracts.py", 'sweeps_run = [r for r in ran if r["kind"] == "sweep" and r["image"] != "cpu"]',
           'sweeps_run = [r for r in ran if r["kind"] == "sweep"]')],
         lambda env, src: fx_cpu_filter_checks(env, src), ["fx filter: the stress figure's power by activity"]),
    ]
    for name, edits, fn, expects in P:
        if pick and pick not in name:
            continue
        try:
            d = make_plant_copy(env, re.sub(r"\W+", "-", name)[:28], edits)
        except SystemExit as e:
            check(f"plant [{name}]: applies", False, str(e))
            continue
        try:
            res = fn(env, d)
        except Exception as e:  # a plant that breaks the scenario outright is a failure the scenario saw
            res = [("the scenario crashed under the plant", False, repr(e))]
        if not res:
            skip(f"plant [{name}]", "its scenario was skipped on this host")
            continue
        caught = [(n, d2) for n, ok, d2 in res if not ok]
        intended = [n for n, _ in caught if any(e in n for e in expects)]
        check(f"plant [{name}]: its scenario FAILS, at the check written for it", bool(intended),
              "caught by: " + ("; ".join(n[:90] for n, _ in caught[:3]) if caught else "nothing - every check passed under the plant"))
        for n, d2 in caught[:2]:
            print(f"        caught by: {n[:110]}" + (f"  [{d2[:160]}]" if n.startswith("the scenario crashed") else ""))
        if len(caught) > 2:
            print(f"        ... and {len(caught) - 2} more failing checks")


def scn_soak_software(env: Env, src: str = HERE) -> list:
    """A card soak whose job fell back to the software backend must not pass."""
    R = run_driver(env, "soaksw", ["--quick", "--legs", "api-test"],
                   [{"leg": "soak", "op": "sqrt32", "nth": [1], "do": "software"}], src=src, cap=120)
    sw = sorted([x for x in R.legs(kind="sweep") if x["sweep"]["op"] == "sqrt32"], key=lambda x: x["start_epoch"])
    first = sw[0] if sw else None
    return [("a card soak that says 'software backend' is parse_error, never pass",
             first is not None and first["status"] == "parse_error" and "DEVICE" in (first["reason"] or ""),
             str(first and (first["status"], first["reason"])))]


def group_pool(env: Env, src: str = HERE) -> list:
    """The host pool (parcel DR2): the in-process checks, then STOP and the deadline, a host job's failure, and --resume."""
    return (pool_unit_checks(src) + pool_tree_unit_checks(src) + cpu_parse_checks(src) + append_lock_checks(src) + scn_pool_stop(env, src)
            + scn_pool_tree(env, src) + scn_pool_failure(env, src) + scn_pool_resume(env, src) + scn_pool_survives(env, src)
            + scn_pool_nice(env, src))


def group_seeds(env: Env, src: str = HERE) -> list:
    """The seeds (parcel DR2): the schedule over the catalog, then across runs and over an old run."""
    return seed_checks(src) + scn_seeds(env, src)


def run_group(name: str, results: list) -> None:
    bad = [(n, d) for n, ok, d in results if not ok]
    for n, ok, d in results:
        check(n, ok, d)
    print(f"{name}: {len(results)} checks, {len(bad)} failed")


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    want = lambda g: only is None or g in only
    tmp = tempfile.mkdtemp(prefix="card-stress-test-")
    env = Env(tmp)
    t0 = time.time()
    try:
        if want("parsers"):
            run_group("parsers", group_parsers())
        if want("commands"):
            run_group("commands", group_commands())
        if want("standin"):
            run_group("standin", standin_alive_checks())
        for gname, fn, posix_only in (("normal", scn_normal, False), ("fail", scn_fail_and_parse, False),
                                      ("timeout", scn_timeout, False), ("deaf", scn_deaf, True),
                                      ("nodevice", scn_nodevice, False), ("cardlost", scn_cardlost, False),
                                      ("stopfile", scn_stopfile, False), ("deadline", scn_deadline, False),
                                      ("rotation", scn_rotation, False), ("diskfloor", scn_diskfloor, False),
                                      ("guard", scn_guard, False), ("sweep", scn_sweep, False),
                                      ("disagree", scn_disagree, False), ("telemetry", scn_telemetry, False),
                                      ("build", scn_build_refusals, False), ("buildreal", scn_buildreal, False),
                                      ("internal", scn_internal_error, False), ("signal", scn_signal, True),
                                      ("torn", scn_torn_tail, False),
                                      ("disable", scn_item_disabled, False),
                                      ("sweepall", scn_sweep_all, False),
                                      ("pool", group_pool, False), ("seeds", group_seeds, False),
                                      ("trees", scn_trees, False),
                                      ("items", group_items, False), ("chunk", group_chunk, False),
                                      ("records", group_records, False), ("notes", group_notes, False)):
            if not want(gname):
                continue
            if posix_only and not POSIX:
                skip(gname, "needs POSIX (SIGTERM can be ignored; Windows has no such signal)")
                continue
            run_group(gname, fn(env))
        if want("report") and hasattr(env, "normal"):
            run_group("report", scn_report(env))
        if want("plants") and "--no-plants" not in sys.argv:
            plants(env)
    finally:
        rmtree_force(tmp)
    print(f"card-stress test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
