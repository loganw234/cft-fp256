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

POSIX-only checks (the `nice` and `timeout` wrappers, a process that ignores SIGTERM) are
SKIPped by name on Windows and run under WSL or on the box. Everything runs niced by the
caller's choice; nothing here starts anything heavy. Prints one line a group and a last line
"card-stress test: N checks, F failed, S skipped".
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# CARD_STRESS_TEST_ROOT: a copy of this file run from a plant's directory (see plants) reads the
# real tree's tool sources, not its own parent directory
ROOT = os.environ.get("CARD_STRESS_TEST_ROOT") or os.path.dirname(HERE)
sys.path.insert(0, HERE)
import card_stress_lib as L  # noqa: E402

POSIX = os.name == "posix"
FIX = os.path.join(HERE, "card_stress_fixtures")

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


# ---------------------------------------------------------------------------------------
# a Driver, read but not run: the legs' command lines
# ---------------------------------------------------------------------------------------

def group_commands(src: str = HERE) -> list:
    out: list = []

    def c(name: str, ok: bool, detail: str = "") -> None:
        out.append((name, bool(ok), detail))

    sys.path.insert(0, src)
    import importlib
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
        c("acceptance-rev8 on the quad: eight entries, the two long compiles left out",
          len(only) == 8 and "riccati_extended_fp64" not in only and "gray_scott_extended_fp64" not in only, str(only))
        c("acceptance-rev8: the single has no entry, and the leg says so by name",
          isinstance(argv("acceptance-rev8", s), mod.Skip) and "u50-rev8" in argv("acceptance-rev8", s).reason)
        c("acceptance-rev8: the deep's one entry is a 40-minute compile with no cache, so it is skipped by name",
          isinstance(argv("acceptance-rev8", dp), mod.Skip) and "gray_scott_extended" in argv("acceptance-rev8", dp).reason)
        t_uncached = d.leg_cmd("acceptance-rev8", q, 1).timeout
        os.makedirs(os.path.join(tmp, "imgs"), exist_ok=True)
        for e in mod.REV8_ENTRIES["u50-rev8-quad"] + mod.REV8_ENTRIES["u50-rev8-deep"]:
            for ext in (".cftp", ".bank"):
                open(os.path.join(tmp, "imgs", e + ext), "w").close()
        r8c = d.leg_cmd("acceptance-rev8", q, 1)
        c("acceptance-rev8: with every image cached the quad runs nine, riccati included, and the timeout drops "
          "its compile allowance", len(r8c.argv[r8c.argv.index("--only") + 1].split(",")) == 9
          and r8c.timeout == t_uncached - mod.REV8_FIRST_COMPILE_ALLOWANCE)
        c("acceptance-rev8: with the cache the deep runs gray_scott_extended",
          not isinstance(d.leg_cmd("acceptance-rev8", dp, 1), mod.Skip))
        c("selftest: every third visit of an image (visit 1 runs, 2 and 3 skip, 4 runs)",
          [isinstance(d.leg_cmd("selftest", q, v), mod.Skip) for v in (1, 2, 3, 4)] == [False, True, True, False])
        c("timeouts: every leg has one, from the card's measured times with a floor",
          all(mod.DEFAULT_TIMEOUTS[leg] >= 300 for leg in mod.BATTERY))
        c("REV8_ENTRIES is acceptance.py's table (read from its source)", rev8_table_matches(mod))
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
    return out


def rev8_table_matches(mod) -> bool:
    with open(os.path.join(ROOT, "programs", "acceptance.py"), "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^REV8 = \((.*?)\)\n#", text, re.S | re.M)
    if not m:
        return False
    pairs = re.findall(r'\("([a-z0-9_]+)", "(u50-rev8[a-z-]*)"\)', m.group(1))
    table: dict = {"u50-rev8-quad": [], "u50-rev8": [], "u50-rev8-deep": []}
    for name, target in pairs:
        table[target].append(name)
    return table == mod.REV8_ENTRIES and len(pairs) == 10


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
                 base_extra=None, pre_stop: bool = False) -> Run:
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
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=e, cwd=ROOT)
    r = Run(out, proc)
    r.state = state
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

    R = run_driver(env, "normal", ["--quick"], src=src)
    env.normal = R
    legs = R.legs()
    c("normal: exit 0, every leg passed (quick is a check)", R.rc == 0, f"rc {R.rc}: {R.text[-300:]}")
    c("normal: 38 leg records: 36 passes and the two named skips",
      len(legs) == 38 and sum(r["status"] == "pass" for r in legs) == 36 and sum(r["status"] == "skipped" for r in legs) == 2,
      f"{len(legs)} legs, {sorted({r['status'] for r in legs})}")
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
    c("normal: every leg record has its image's hash, its times and a log", all(
        r["image_sha256"] == env.shas[r["image"]] and r["start_epoch"] <= r["end_epoch"] and (r["status"] == "skipped" or r["log"]) for r in legs))
    c("normal: a passing leg's log is gzipped and readable", all(
        r["log_kept"] == "gz" and os.path.exists(os.path.join(R.out, r["log"])) and "standin: would run" in log_text(R, r)
        for r in legs if r["status"] == "pass"))
    sw = R.legs(kind="sweep")
    c("normal: the quad's sweep is four jobs on tiles 1 to 4; the others one job, no tile",
      sorted(r["tile"] for r in sw if r["image"] == "quad") == [1, 2, 3, 4] and all(r["tile"] is None for r in sw if r["image"] != "quad"))
    c("normal: every sweep job reports its cases (read from its verdict line) and its rate", all(
        (r["counts"] or {}).get("cases", 0) > 0 and (r["rate"] or {}).get("unit") == "cases/s" for r in sw))
    c("normal: nextup32's slice reports the 8 edge cases beyond its range, read, not assumed",
      [(r["counts"] or {}).get("cases", 0) - (r["sweep"]["hi"] - r["sweep"]["lo"]) for r in sw if r["sweep"]["item"] == "nextup32"] == [8])
    c("normal: every sweep job soaked the DEVICE (the stand-in prints the line only when CFT_SOAK_ARTIFACT is set)",
      all("soaking the DEVICE backend: " + env.imgs[r["image"]] in log_text(R, r) for r in sw))
    c("normal: status.txt exists and names the legs, the card, the sweep and the deadline",
      all(k in open(os.path.join(R.out, "status.txt")).read() for k in ("legs", "card ", "sweep ", "deadline", "FINISHED: quick_done")))
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
    return [("disk floor: below the floor the driver stops before any leg, exit 3, reason disk_floor",
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
INJECT = [("card_stress.py", "    def tally(self, image: str, status: str) -> None:\n        self.counts[status] = self.counts.get(status, 0) + 1\n",
           "    def tally(self, image: str, status: str) -> None:\n        if status == 'pass' and self.counts.get('pass', 0) == 2 and not getattr(self, '_boom', False):\n"
           "            self._boom = True\n            raise RuntimeError('injected fault')\n        self.counts[status] = self.counts.get(status, 0) + 1\n")]


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
    return out


def scn_report(env: Env, src: str = HERE) -> list:
    """The report script on the normal run's records, held to figures counted here from the records
    themselves (not by the report's code); then the same run with one record changed."""
    out: list = []

    def c(n, ok, d=""):
        out.append((n, bool(ok), d))

    rp = os.path.join(HERE, "card_stress_report.py")
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
                                      ("disable", scn_item_disabled, False)):
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
