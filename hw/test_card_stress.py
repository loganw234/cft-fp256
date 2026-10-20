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
    exh = [it for it in items if it.kind == "exhaustive"]
    c("catalog: 36 exhaustive items (the 14 of the last run and the 22 new) and the 54 random ones, none gone",
      len(exh) == 36 and len(items) - len(exh) == 54 and all(it.kind == "random" for it in items[i0 + 22:]),
      f"{len(exh)} exhaustive of {len(items)}")
    c("catalog: the new items have per-encoding counts 1, 4, 2, 2, 17, 568; only cvtto32-all has no fixed case count",
      [(by_name[n].per_encoding, by_name[n].exact) for n in ("conv32to64-all", "cvtto32-all-rne", "cvtfrom32-all-rup",
                                                              "cvtfrom64-all-rdn", "scaleb32-all-rtz", "scaleb32-wide-rne")]
      == [(1, True), (4, False), (2, True), (2, True), (17, True), (568, True)])
    c("catalog: only the new items say what they covered (the 14 older exhaustive items and every random one do not)",
      sorted(it.name for it in items if it.per_encoding is not None and it.name not in new) == []
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
    c("reach: the table has no operation the catalog does not use, and 43 items reach the tile and 47 do not",
      set(L.OP_REACH) == {it.op for it in items} and sum(it.reach == L.TILE for it in items) == 43
      and sum(it.reach == L.HOST for it in items) == 47,
      f"{sorted(set(L.OP_REACH) ^ {it.op for it in items})}")
    c("reach: of the 54 random items 25 reach the tile (div32, div64, sqrt64 x4 each; rint64 x5; scaleb32, scaleb64 x4 "
      "each) and 29 are host; of the 36 exhaustive items 18 and 18",
      [(k, r, sum(it.kind == k and it.reach == r for it in items))
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
        cat = [it for it in (L.sweep_items(("rne",), ("rne",)) if probe_limited else L.sweep_items()) if it.tool == "clause5"]
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
                            os.path.join(tmp, "quick-imgs")] + list(extra))
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
    c("empty wave, every item covered: the campaign IS finished, and says so in the old words, with how many",
      f4 == [] and d4.plan_wave(q, 3600, 4, f4) == [] and cause4 == "finished"
      and why4.startswith("nothing left to run in this campaign") and "2 items named by --sweep-items" in why4, why4)
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
    # a HOST item is the CPU pool's, not the card's: the card's wave never takes one, and the sentence for an empty wave names it so
    # (not covered, not disabled, and not "a defect in this driver")
    d9 = drv("--sweep-items", f"{ex[14]},{ex[0]}")
    d9.intervals = {ex[14]: [(0, L.EXH)]}
    why9, cause9 = d9.why_no_wave(d9.quick_items(q, 0))
    c("empty wave, a covered tile item and a host item named: the host item is called the CPU pool's - not covered, not a defect - "
      "and the campaign is NOT finished (the pool has work)", d9.quick_items(q, 0) == [] and cause9 == "blocked"
      and "1 covered" in why9 and "1 a host item the CPU pool runs, not the card" in why9 and "defect" not in why9
      and "nothing left to run" not in why9, why9)
    d9o = drv("--sweep-items", f"{ex[0]},{ex[1]}")
    c("only host items named: the card's wave is empty by design (quick_items gives none, plan_wave plans none), whatever is served",
      d9o.quick_items(q, 0) == [] and d9o.plan_wave(q, 3600, 4, []) == [] and d9o.plan_wave(q, 3600, 4, [ex[0]]) == [])


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
    cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", out, "--dry-run",
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
      all(f"standin: env CFT_SOAK_ARTIFACT={env.imgs[r['image']]} CFT_XRT_TILES={r['tile'] or '<unset>'}" in log_text(R, r) for r in swc))
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
    cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", A.out, "--resume", "--dry-run",
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
    ex36 = 18 * EXH_T
    c("sweep all: status.txt says what the tile has seen and what it has not, on a line of its own that begins 'reach': one tile "
      "item done of 18, three host items of 18",
      re.search(r"^reach      tile items: exhaustive %s of %s encodings .*; host items: exhaustive %s of %s encodings .*; "
                r"the tile computes nothing for a host item$" % (f"{EXH_T:,}", f"{ex36:,}", f"{3 * EXH_T:,}", f"{ex36:,}"), st, re.M)
      is not None, st[st.find("reach"):][:400])
    c("sweep all: and its sweep line counts all 36 exhaustive items' encodings, the new ones included",
      f"exhaustive {4 * EXH_T:,} of {36 * EXH_T:,} encodings" in st, st[st.find("sweep "):][:200])
    rp = os.path.join(HERE, "card_stress_report.py")
    p = subprocess.run([sys.executable, "-I", rp, r.out, "--no-write"], capture_output=True, text=True, timeout=120)
    t = p.stdout
    c("sweep all: the report gives each item's reach and totals the coverage by reach",
      p.returncode == 0 and re.search(r"^  conv32to64-all\s.*\shost$", t, re.M) and re.search(r"^  scaleb32-wide-rdn\s.*\stile$", t, re.M)
      and re.search(r"^  reach tile: 1 exhaustive item\(s\) seen; covered %d of %d encodings \(100\.000%%\); fully covered 1 of 1$" % (EXH_T, EXH_T), t, re.M)
      and re.search(r"^  reach host: 3 exhaustive item\(s\) seen; covered %d of %d encodings \(100\.000%%\); fully covered 3 of 3$" % (3 * EXH_T, 3 * EXH_T), t, re.M)
      is not None, t[t.find("exhaustive items"):][:900])
    return out + scn_sweep_short(env, src, base)


def scn_sweep_short(env: Env, src: str, base: list) -> list:
    """B: a slice the tool ran one encoding or one case short is parse_error, by the rule written for it, not covered,
    and served again."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    sc = [{"leg": "soak", "op": "cvtto32-all", "nth": [1], "do": "short"},
          {"leg": "soak", "op": "cvtto32-all", "nth": [2], "do": "shortcase"},
          {"leg": "soak", "op": "conv32to64-all", "nth": [1], "do": "shortcase"},
          {"leg": "soak", "op": "cvtfrom64-all", "nth": [1], "do": "short"}]
    bn = ["cvtto32-all-rne", "conv32to64-all", "cvtfrom64-all-rne"]
    r2 = start_driver(env, "sweepshort", ["--until", until(120), "--sweep-items", ",".join(bn)] + base, sc, src=src,
                      to_file=True)

    def served():
        return all(any(x["status"] == "pass" and x["sweep"]["item"] == n for x in r2.legs(kind="sweep")) for n in bn)

    got = wait_for(served, 90, 0.4)
    stop_run(r2)
    r2.finish(60)
    for n, want in (("cvtto32-all-rne", ["encodings where the slice has", "checks where"]),
                    ("conv32to64-all", ["cases where the slice has"]), ("cvtfrom64-all-rne", ["cases where the slice has"])):
        mine = sorted((x for x in r2.legs(kind="sweep") if x["sweep"]["item"] == n), key=lambda x: x["start_epoch"])
        k = len(want)
        c(f"sweep short {n}: the first {k} slice(s) came back short and were refused as parse_error, by the rule written for each "
          f"({', '.join(want)}), with no counts recorded",
          got and len(mine) > k and all(x["status"] == "parse_error" and x["counts"] is None and w in (x["reason"] or "")
                                         for x, w in zip(mine[:k], want)), str([(x["status"], x["reason"]) for x in mine[:k + 1]]))
        c(f"sweep short {n}: the same slice [0, 2^20) was served again each time, and then passed",
          got and all((x["sweep"]["lo"], x["sweep"]["hi"]) == (0, 1 << 20) for x in mine[:k + 1]) and mine[k]["status"] == "pass"
          and mine[k]["counts"]["encodings"] == 1 << 20, str([(x["sweep"]["lo"], x["sweep"]["hi"]) for x in mine[:k + 1]]))
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
    cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", r3.out, "--resume", "--dry-run",
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
    ends by STOP, within two samples, one timeout and a margin of the moment it was touched, however long a hung call would have
    been: the bound is 2 x the first sample's own time + 2 s + 10 s. Every sample is an error record, never a reading, no hung
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
    first = (tel[0]["epoch"] - recs[0]["epoch"]) if tel and recs else 0.0
    late = end.get("epoch", 1e9) - t_stop
    c("telemetry hang: every examine call hung and was killed at --telemetry-timeout: each sample is an error record "
      "('timed out'), never a reading, and no hung process is left", began and bool(tel) and bool(pids)
      and all((not x["ok"]) and x["values"] is None and "timed out" in (x["error"] or "") for x in tel)
      and not any(pid_alive(p) for p in pids), f"{len(tel)} samples, {len(pids)} hung calls, first error {(tel[:1] or [{}])[0].get('error')}")
    c("telemetry hang: no two samples ran at once (consecutive records at least a sample, 3.5 s, apart)",
      len(tel) >= 2 and all(b["epoch"] - a["epoch"] >= 3.5 for a, b in zip(tel, tel[1:])),
      str([round(b["epoch"] - a["epoch"], 1) for a, b in zip(tel, tel[1:])]))
    c("telemetry hang: STOP, touched while the first sample was in flight, ended the run (exit 0, stop_file) within two "
      "samples, one timeout and 10 s of it", r.rc == 0 and end.get("reason") == "stop_file" and 0 < late <= 2 * first + 2 + 10,
      f"rc {r.rc}, {end.get('reason')}, ended {late:.1f} s after STOP; the first sample took {first:.1f} s")
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
        cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", intree, "--dry-run", "--quick",
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
        cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", root, "--out", o, "--quick",
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
    cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", A.out, "--resume", "--dry-run",
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
        p = subprocess.run([sys.executable, "-I", rp, R2.out, "--no-write"], capture_output=True, text=True, timeout=120)
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
    p = subprocess.run([sys.executable, "-I", rp, R.out, "--json", jpath], capture_output=True, text=True, timeout=120)
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
    p2 = subprocess.run([sys.executable, "-I", rp, cp, "--no-write"], capture_output=True, text=True, timeout=120)
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
        for _ in range(24):                                   # 96 card jobs: every one of the 43 tile items about twice
            for j in d.plan_wave(q, 3600, 4):
                card[j["item"].name] = j["item"].reach
                d.served[j["item"].name] = d.served.get(j["item"].name, 0) + 1
        d.served = {}
        for _ in range(94):                                   # two turns of the 47 host items
            j = d.pool_plan()
            if j is None:
                break
            pool[j["item"].name] = (j["item"].reach, j["sweep"]["reach"], j["tile"])
            d.pool_busy.pop(j["item"].name, None)             # the slice is done
            d.served[j["item"].name] = d.served.get(j["item"].name, 0) + 1
        c("pool: over a whole rotation the card's waves plan the 43 TILE items and not one host item",
          len(card) == 43 and set(card.values()) == {"tile"}, f"{len(card)} items, reaches {sorted(set(card.values()))}")
        c("pool: and the pool's slices are the 47 HOST items and not one tile item, no tile pinned, each record saying reach host",
          len(pool) == 47 and {v[0] for v in pool.values()} == {"host"} and {v[1] for v in pool.values()} == {"host"}
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


def append_lock_checks(src: str = HERE) -> list:
    """The metrics file has one writer at a time in this process (parcel DR2). Eight threads - the host pool's workers, the card's
    thread, the telemetry sampler - append at one instant, over and over. THE CAUSE, on every platform: the write is slowed by 5 ms
    inside, and no two threads may ever be inside it together (a lock held across the write makes this true; without it all eight
    are). THE SYMPTOM, which only Windows shows (its emulation of O_APPEND seeks to the end and then writes, so two writers at once
    overwrite each other: a dry run lost a leg record that way when the pool's workers finished together, and POSIX appends
    atomically): every record is in the file, none torn, in the order of its epoch. The symptom is not reproduced every time
    without the lock (MEASURED, Windows 11, Python 3.12.9: 4 trials in 60 of eight threads by twenty-five rounds damaged the file, and none lost a whole
    record), which is why the cause is checked as well."""
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
    c("pool failure: the card's own legs were not touched: every api-test passed", all(x["status"] == "pass" for x in R.legs("api-test")))
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
    cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", A.out, "--resume", "--dry-run",
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
        probed = {it.name: it.seed_index for it in L2.sweep_items(("rne",), ("rne",))}
        c("seeds: an item's seeds do not depend on which other items exist: a run whose probes dropped the directed scaleB and cvtFrom "
          "modes gives every item it still has the same index", all(L2.RANDOM_SEED_INDEX[n] == i for n, i in probed.items() if i is not None))
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
    cmd = [sys.executable, "-I", os.path.join(src, "card_stress.py"), "--root", ROOT, "--out", O.out, "--resume", "--dry-run",
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


def scn_trees(env: Env, src: str = HERE) -> list:
    """Coverage kept apart by tree (parcel DR2). (1) The driver records the tree it runs from: rtl and host/ tree hashes, whether each is
    modified, and the compiler, read here by the test's own git commands. (2) The report counts a tile item's coverage per RTL tree
    with the images beneath, and a host item's per host/ tree and compiler, on a synthetic pair of runs whose truth is counted here:
    the other tree's slices are disjoint from the first tree's, so a report that summed trees would show it. (3) --also adds a
    second run directory to that section alone; a run that recorded no tree is kept apart by its commit."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    # (1)
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
        p = subprocess.run([sys.executable, "-I", rp, d1, "--no-write", "--json", jp] + list(extra), capture_output=True, text=True, timeout=120)
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
    p3 = subprocess.run([sys.executable, "-I", rp, d1, "--no-write", "--also", os.path.join(env.tmp, "no-such-run")], capture_output=True,
                        text=True, timeout=60)
    c("trees --also: a directory with no metrics.jsonl is refused by name (exit 2)",
      p3.returncode == 2 and "no-such-run" in p3.stderr and "metrics.jsonl" in p3.stderr, f"rc {p3.returncode}: {p3.stderr[-200:]}")
    return out


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
    p = subprocess.run([sys.executable, "-I", os.path.join(src, "test_card_stress.py"), "--only", "parsers", "--no-plants"],
                       capture_output=True, text=True, env=e, timeout=120)
    bad = [ln.strip()[6:].strip() for ln in p.stdout.splitlines() if ln.startswith("  FAIL  ")]
    if p.returncode != 0 and not bad:
        bad = [f"parser group crashed under the plant: {p.stderr[-200:]}"]
    return [(b, False, "") for b in bad] or [("parser group passes under the plant", True, "")]


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
         [("card_stress.py", '                cause, tag = "outside --sweep-items", n\n', '                cause, tag = "covered", n\n')],
         lambda env, src: group_commands(src), ["empty wave, the case of 2026-10-19"]),
        ("an empty wave still says the campaign is finished",
         [("card_stress.py", "                why, cause = self.why_no_wave(forced)\n",
           '                why, cause = "nothing left to run in this campaign", "finished"\n')],
         lambda env, src: scn_quick_sweep(env, src),
         ["quick sweep: the empty wave that follows says it is blocked"]),
        # parcel DR2 (2026-10-20): the host pool, the seeds, coverage by tree
        ("a host job inherits CFT_SOAK_ARTIFACT and CFT_XRT_TILES from the driver's environment",
         [("card_stress.py", "        for k in drop:\n            env.pop(k, None)\n", "        for k in ():\n            env.pop(k, None)\n")],
         scn_normal, ["normal: no host job named the card although the driver's own environment did"]),
        ("the card's sweep picks host items too (and the pool tile items)",
         [("card_stress.py", "                if reach is not None and it.reach != reach:\n                    continue\n",
           "                if False:\n                    continue\n")],
         lambda env, src: pool_unit_checks(src), ["pool: over a whole rotation the card's waves plan the 43 TILE items", "pool: and the pool's slices are the 47 HOST items"]),
        ("the host pool does not look for a stop before it starts a slice",
         [("card_stress.py", "                if self.should_stop(git=False) is not None:\n", "                if False:\n")],
         lambda env, src: pool_unit_checks(src) + scn_pool_stop(env, src),
         ["pool stop: no host slice STARTED after STOP", "pool: a worker started below the disk floor plans nothing"]),
        ("a host job the run's end terminated is recorded as a slice of its item",
         [("card_stress.py", "        if slot[\"abandon\"] or (self.hard and res.killed):\n", "        if False:\n")],
         scn_pool_stop, ["pool stop: the hung host job was terminated", "pool deadline: the run ended at the deadline"]),
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
         scn_trees, ["trees: run_start records the tree the driver runs from"]),
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
    return (pool_unit_checks(src) + append_lock_checks(src) + scn_pool_stop(env, src) + scn_pool_failure(env, src)
            + scn_pool_resume(env, src) + scn_pool_survives(env, src) + scn_pool_nice(env, src))


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
                                      ("trees", scn_trees, False)):
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
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"card-stress test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
