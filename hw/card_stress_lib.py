# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The long-run card stress driver's shared parts: the verdict parsers, the
sweep's items and coverage arithmetic, the metrics file's reading and writing,
and the telemetry reader. hw/card_stress.py (the driver), hw/card_stress_report.py
(the report) and the dry run's tests (hw/test_card_stress.py) all import this one
file, so the three cannot disagree about what a record means.

THE PARSERS. A verdict is read from a tool's log by a pattern anchored to a whole
line, and every parser FAILS LOUDLY: a line that is missing, appears twice, or has
the wrong shape raises VerdictError, and the driver records the leg as parse_error
and keeps its whole log. A count is never defaulted: it is a captured group of a
matched line, or it is absent from the record. Each pattern below quotes the
printf it matches (file and line at 582953c) and, where the tool's output has
been quoted in docs/VALIDATION.md, that quotation is one of the dry run's cases.

Python 3.10 or later (the box's python3 is 3.12; WSL's is 3.10). Standard library
only.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple


class VerdictError(Exception):
    """A tool's log did not say what a parser requires. Never a pass."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(epoch))


def parse_when(text: str) -> float:
    """'2026-10-19 08:00' or '2026-10-19 08:00:00' in the host's local time."""
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return time.mktime(time.strptime(text.strip(), fmt))
        except ValueError:
            pass
    raise ValueError(f"not a time: {text!r} (want 'YYYY-MM-DD HH:MM')")


def _one(rx: "re.Pattern[str]", text: str, what: str) -> "re.Match[str]":
    """The one line that matches, or VerdictError. Zero or two are both wrong."""
    hits = list(rx.finditer(text))
    if len(hits) != 1:
        raise VerdictError(f"{what}: expected exactly one line matching "
                           f"{rx.pattern!r}, found {len(hits)}")
    return hits[0]


def _maybe_one(rx: "re.Pattern[str]", text: str, what: str):
    hits = list(rx.finditer(text))
    if len(hits) > 1:
        raise VerdictError(f"{what}: {len(hits)} lines match {rx.pattern!r}")
    return hits[0] if hits else None


def _rc_agrees(rc: Optional[int], ok: bool, what: str) -> None:
    if rc is None:
        raise VerdictError(f"{what}: no exit status")
    if ok and rc != 0:
        raise VerdictError(f"{what}: the log says it passed and the exit status is {rc}")
    if not ok and rc == 0:
        raise VerdictError(f"{what}: the log says it failed and the exit status is 0")


class Verdict:
    """What a parser read. ok: the tool says it passed. counts: only what the
    tool printed, as ints. notes: short strings for the record."""

    def __init__(self, ok: bool, counts: Dict[str, int],
                 notes: Optional[List[str]] = None,
                 extra: Optional[Dict[str, Any]] = None):
        self.ok = ok
        self.counts = counts
        self.notes = notes or []
        self.extra = extra or {}

    def __repr__(self) -> str:
        return f"Verdict(ok={self.ok}, counts={self.counts}, notes={self.notes})"


M = re.MULTILINE

# ---------------------------------------------------------------------------
# api-test   host/tests/api_test.c:6115-6117
#   printf("api-test: all contract checks passed\n")  /  "api-test: %d FAILED\n"
# ---------------------------------------------------------------------------
API_PASS = re.compile(r"^api-test: all contract checks passed$", M)
API_FAIL = re.compile(r"^api-test: (\d+) FAILED$", M)


def parse_api_test(text: str, rc: Optional[int]) -> Verdict:
    p = list(API_PASS.finditer(text))
    f = list(API_FAIL.finditer(text))
    if len(p) + len(f) != 1:
        raise VerdictError(f"api-test: expected one verdict line, found "
                           f"{len(p)} pass and {len(f)} fail lines")
    if p:
        _rc_agrees(rc, True, "api-test")
        return Verdict(True, {"failed": 0})
    n = int(f[0].group(1))
    if n == 0:
        raise VerdictError("api-test: 'FAILED' with a count of 0")
    _rc_agrees(rc, False, "api-test")
    return Verdict(False, {"failed": n})


# ---------------------------------------------------------------------------
# device-test   host/tests/device_test.c
#   10040 and 10550: printf("\n%d checks, %d failed\n", ...)  (the totals line;
#     the sub-totals above it carry a leading indent or a label, so an anchored
#     pattern matches the totals alone)
#   10042: "the device image's identity holds"            (-i)
#   10587-10597: "the device and the software backend agree on every case
#     that RAN, bits and flags"  (or without "that RAN" when nothing was absent)
#   10586: "not on this device, each named above: NOT COMPARED %d format%s,
#     %d buffers leg%s, %d opcode%s and %d other leg%s; NOT TESTED %d; NOT RUN %d"
#   9327: "image: sha256 %s, %llu bytes, VERSION 0x%08x, CAPS 0x%08x[, CAPS2 0x%08x]"
#   9906: "device: backend %s, %u tile%s, contract 0x%08x, formats ..."
# ---------------------------------------------------------------------------
DT_TOTAL = re.compile(r"^(\d+) checks, (\d+) failed$", M)
DT_IDENTITY = re.compile(r"^the device image's identity holds$", M)
DT_AGREE = re.compile(r"^the device and the software backend agree on every "
                      r"case( that RAN)?, bits and flags$", M)
DT_NOT = re.compile(r"^not on this device, each named above: NOT COMPARED (\d+) "
                    r"formats?, (\d+) buffers? legs?, (\d+) opcodes? and (\d+) "
                    r"other legs?; NOT TESTED (\d+); NOT RUN (\d+)$", M)
DT_IMAGE = re.compile(r"^image: sha256 ([0-9a-f]{64}), (\d+) bytes, VERSION "
                      r"0x([0-9a-f]{8}), CAPS 0x([0-9a-f]{8})(?:, CAPS2 "
                      r"0x([0-9a-f]{8}))?$", M)
DT_DEVICE = re.compile(r"^device: backend (\S+), (\d+) tiles?, contract "
                       r"0x([0-9a-f]{8}), formats((?: fp\d+)+)$", M)


def parse_device_test(text: str, rc: Optional[int], mode: str) -> Verdict:
    """mode 'i' (the identity) or anything else (a matrix against the software
    backend: -q -n 8, -n 4096, -r, -b)."""
    m = _one(DT_TOTAL, text, "device-test totals")
    checks, failed = int(m.group(1)), int(m.group(2))
    counts = {"checks": checks, "failed": failed}
    extra: Dict[str, Any] = {}
    if mode == "i":
        # The first of each, as hw/card-segrun.sh reads them (grep -m1): a log with a
        # second such line is not made worse by it, but one with none is no identity.
        ident = DT_IMAGE.search(text)
        dev = DT_DEVICE.search(text)
        if not ident:
            raise VerdictError("device-test -i: no 'image: sha256 ...' identity line")
        if not dev:
            raise VerdictError("device-test -i: no 'device: backend ...' line")
        extra = {"image_sha256": ident.group(1), "image_bytes": int(ident.group(2)),
                 "version": ident.group(3), "caps": ident.group(4),
                 "caps2": ident.group(5), "backend": dev.group(1),
                 "tiles": int(dev.group(2)), "formats": dev.group(4).split()}
        holds = DT_IDENTITY.search(text) is not None
        ok = failed == 0 and holds
        if failed == 0 and not holds:
            raise VerdictError("device-test -i: 0 failed but no 'the device "
                               "image's identity holds' line")
        if failed != 0 and holds:
            raise VerdictError("device-test -i: failures and an 'identity holds' line")
        _rc_agrees(rc, ok, "device-test -i")
        return Verdict(ok, counts, extra=extra)
    agree = _maybe_one(DT_AGREE, text, "device-test agreement line")
    nm = _maybe_one(DT_NOT, text, "device-test NOT-lines summary")
    notes: List[str] = []
    if nm:
        counts.update({"not_compared_formats": int(nm.group(1)),
                       "not_compared_buffer_legs": int(nm.group(2)),
                       "not_compared_opcodes": int(nm.group(3)),
                       "not_compared_other": int(nm.group(4)),
                       "not_tested": int(nm.group(5)), "not_run": int(nm.group(6))})
    ok = failed == 0 and agree is not None
    if failed == 0 and agree is None:
        raise VerdictError("device-test: 0 failed but no 'agree on every case' line")
    if failed != 0 and agree is not None:
        raise VerdictError("device-test: failures and an 'agree on every case' line")
    if agree is not None and (agree.group(1) is None) == (nm is not None):
        # 'agree on every case' without 'that RAN' is printed only when no NOT-line is
        # (device_test.c:10587-10597); both or neither the other way is a log we do not know.
        raise VerdictError("device-test: the agreement line's 'that RAN' and the "
                           "NOT-lines summary disagree about whether anything was absent")
    _rc_agrees(rc, ok, "device-test")
    return Verdict(ok, counts, notes, extra)


# ---------------------------------------------------------------------------
# card-segrun   hw/card-segrun.sh:208   echo "== card-segrun: $checks checks, $failed failed"
#   and, for the gate inside: "ok    the certificates made on this card: <segrun_check's line>"
# ---------------------------------------------------------------------------
SEGRUN_TOTAL = re.compile(r"^== card-segrun: (\d+) checks, (\d+) failed$", M)
SEGRUN_GATE = re.compile(r"^  ok    the certificates made on this card: (\d+) checks, "
                         r"(\d+) failed(?:, (\d+) skipped)?\b", M)
SEGRUN_KEPT = re.compile(r"^   logs kept in (\S+)$", M)


def parse_card_segrun(text: str, rc: Optional[int]) -> Verdict:
    m = _one(SEGRUN_TOTAL, text, "card-segrun totals")
    checks, failed = int(m.group(1)), int(m.group(2))
    counts = {"checks": checks, "failed": failed}
    extra: Dict[str, Any] = {}
    gates = list(SEGRUN_GATE.finditer(text))
    if gates:
        g = gates[-1]
        extra["gate_checks"] = int(g.group(1))
        extra["gate_failed"] = int(g.group(2))
        if g.group(3) is not None:
            extra["gate_skipped"] = int(g.group(3))
    kept = SEGRUN_KEPT.search(text)
    if kept:
        extra["kept_dir"] = kept.group(1)
    ok = failed == 0
    _rc_agrees(rc, ok, "card-segrun")
    return Verdict(ok, counts, extra=extra)


# ---------------------------------------------------------------------------
# seq_check.py --device   host/tests/seq_check.py
#   3331: "\n%d programs run through both implementations, %d refused by both"
#   3571-3576: "the device (<artifact>) and the golden model agree on every program
#     it ran: deposits, counts, flags and status, and every lane byte where asked;
#     it refused by name every program needing a bit it does not publish"
#   2454: "SKIP  the routine corpus (the eighth): ..."  (an inner skip)
# ---------------------------------------------------------------------------
SEQ_COUNT = re.compile(r"^(\d+) programs run through both implementations, "
                       r"(\d+) refused by both$", M)
SEQ_PASS = re.compile(r"^the device \((.+)\) and the golden model agree on every "
                      r"program it ran: deposits, counts, flags and status, and "
                      r"every lane byte where asked; it refused by name every "
                      r"program needing a bit it does not publish$", M)
SEQ_SW_PASS = re.compile(r"^libcft and the golden model agree on every program", M)
SEQ_BAD = re.compile(r"^(\d+) DISAGREEMENTS$|^THE .* (?:DID NOT REACH EVERY FORM|"
                     r"COMPARED NOTHING AND THE DEVICE REFUSED NOTHING OF IT)|"
                     r"^NO PROGRAM WAS ", M)
SEQ_SKIP = re.compile(r"^SKIP  ", M)


def parse_seq_check(text: str, rc: Optional[int],
                    artifact: Optional[str] = None) -> Verdict:
    m = _one(SEQ_COUNT, text, "seq_check program count")
    counts = {"programs": int(m.group(1)), "refused_by_both": int(m.group(2))}
    skips = len(SEQ_SKIP.findall(text))
    if skips:
        counts["inner_skips"] = skips
    if SEQ_SW_PASS.search(text):
        raise VerdictError("seq_check: the software backend's verdict line - "
                           "--device was not honoured, so the card was not used")
    p = _maybe_one(SEQ_PASS, text, "seq_check device verdict")
    bad = SEQ_BAD.search(text)
    if p and bad:
        raise VerdictError("seq_check: a pass line and a failure line")
    if p:
        if artifact is not None and p.group(1) != artifact:
            raise VerdictError(f"seq_check: the verdict names device {p.group(1)!r}, "
                               f"not {artifact!r}")
        _rc_agrees(rc, True, "seq_check")
        return Verdict(True, counts)
    if not bad:
        raise VerdictError("seq_check: neither the device's pass line nor a "
                           "recognised failure line")
    d = re.search(r"^(\d+) DISAGREEMENTS$", text, M)
    if d:
        counts["disagreements"] = int(d.group(1))
    _rc_agrees(rc, False, "seq_check")
    return Verdict(False, counts, [bad.group(0)[:200]])


# ---------------------------------------------------------------------------
# acceptance.py   programs/acceptance.py:1480-1487
#   f"{name}: {npass} of {len(verdicts)} {'made'|'PASS'} on {on} ({legs}); {ok} checks
#   ok, {bad} failed, {secs:.0f} s"   name = "acceptance" or "acceptance rev8";
#   on = the device, plus " as <target>" with --target
# ---------------------------------------------------------------------------
ACC_LINE = re.compile(r"^(acceptance|acceptance rev8): (\d+) of (\d+) PASS on "
                      r"(.+?)(?: as (u50-rev8(?:-quad|-deep)?))? \(([a-z,]+)\); "
                      r"(\d+) checks ok, (\d+) failed, (\d+) s$", M)


def parse_acceptance(text: str, rc: Optional[int], device: Optional[str] = None,
                     rev8: bool = False, target: Optional[str] = None) -> Verdict:
    m = _one(ACC_LINE, text, "acceptance verdict")
    if (m.group(1) == "acceptance rev8") != rev8:
        raise VerdictError(f"acceptance: the verdict is {m.group(1)!r}, not the "
                           f"{'rev8' if rev8 else 'rev7'} set's")
    npass, total = int(m.group(2)), int(m.group(3))
    okc, bad, secs = int(m.group(7)), int(m.group(8)), int(m.group(9))
    if device is not None and m.group(4) != device:
        raise VerdictError(f"acceptance: the verdict is on {m.group(4)!r}, not {device!r}")
    if target is not None and m.group(5) != target:
        raise VerdictError(f"acceptance: the verdict is as {m.group(5)!r}, not {target!r}")
    counts = {"entries": total, "entries_passed": npass, "checks": okc,
              "failed": bad, "reported_seconds": secs}
    ok = total > 0 and npass == total and bad == 0
    _rc_agrees(rc, ok, "acceptance")
    return Verdict(ok, counts)


# ---------------------------------------------------------------------------
# cft-selftest  host/tools/cft_selftest.c:79-81: "%" PRIu64 " cases checked", or
#   "CONFORMANCE FAILED: %s"
# cft-resident  host/tools/cft_resident.cpp:301-305:
#   "%d row(s) FAILED a check"  /  "every row: status clean, the same bytes on every
#   unit, on repeat, and in software"
# ---------------------------------------------------------------------------
SELFTEST_OK = re.compile(r"^(\d+) cases checked$", M)
SELFTEST_BAD = re.compile(r"^CONFORMANCE FAILED: (.*)$", M)
RESIDENT_OK = re.compile(r"^every row: status clean, the same bytes on every unit, "
                         r"on repeat, and in software$", M)
RESIDENT_BAD = re.compile(r"^(\d+) row\(s\) FAILED a check$", M)


def parse_selftest(text: str, rc: Optional[int]) -> Verdict:
    bad = SELFTEST_BAD.search(text)
    m = _maybe_one(SELFTEST_OK, text, "cft-selftest case count")
    if bad:
        _rc_agrees(rc, False, "cft-selftest")
        return Verdict(False, {"cases": int(m.group(1))} if m else {}, [bad.group(1)[:200]])
    if not m:
        raise VerdictError("cft-selftest: no 'N cases checked' line and no CONFORMANCE FAILED")
    if int(m.group(1)) == 0:
        raise VerdictError("cft-selftest: 0 cases checked")
    _rc_agrees(rc, True, "cft-selftest")
    return Verdict(True, {"cases": int(m.group(1))})


def parse_resident(text: str, rc: Optional[int]) -> Verdict:
    p = list(RESIDENT_OK.finditer(text))
    f = list(RESIDENT_BAD.finditer(text))
    if len(p) + len(f) != 1:
        raise VerdictError(f"cft-resident: expected one verdict line, found {len(p)} "
                           f"pass and {len(f)} fail lines")
    if p:
        _rc_agrees(rc, True, "cft-resident")
        return Verdict(True, {"failed": 0})
    n = int(f[0].group(1))
    if n == 0:
        raise VerdictError("cft-resident: 'FAILED a check' with a count of 0")
    _rc_agrees(rc, False, "cft-resident")
    return Verdict(False, {"failed": n})


# ---------------------------------------------------------------------------
# the soaks   host/tools/divsqrt_soak.c:476, host/tools/clause5_soak.c:2023 (at 582953c)
#   printf("%s %s: %llu cases, %llu value mismatches, %llu flag mismatches\n", job, mode,..)
#   stderr first line (divsqrt_soak.c:446, clause5_soak.c:1951):
#   "soaking the DEVICE backend: <artifact>"  or "soaking the software backend"
#   a failed library call prints "  library call failed" (divsqrt) or
#   "  library call failed in <what>" (clause5), then the verdict, exit 1
# The clause-5 soak's EXHAUSTIVE modes of the conversions and scaleB (the -all and -wide jobs, the
# `exh_mode` branch of its main) print the same line with ", E encodings, S skipped" appended: E
# operand encodings ran, and each (encoding, check) pair was compared (a case) or skipped, so
# cases + S is k * E with k fixed by the mode (PER_ENCODING below). That is how a slice's coverage
# is checked exactly where its count of cases depends on the operands (cvtto32-all compares
# in-range lanes only). Every other job's line is unchanged and has no such clause.
# ---------------------------------------------------------------------------
SOAK_LINE = re.compile(r"^(\S+) (\S+): (\d+) cases, (\d+) value mismatches, "
                       r"(\d+) flag mismatches(?:, (\d+) encodings, (\d+) skipped)?$", M)
SOAK_DEVICE = re.compile(r"^soaking the DEVICE backend: (.+)$", M)
SOAK_SOFTWARE = re.compile(r"^soaking the software backend$", M)
SOAK_LIBFAIL = re.compile(r"^  library call failed(?: in .*)?$", M)
SOAK_DISAGREE = re.compile(r"^  (?:MISMATCH|FLAGS) .*$", M)


class SoakResult(Verdict):
    pass


def parse_soak(text: str, rc: Optional[int], op: str, verdict_mode: str,
               artifact: Optional[str], expected_cases: Optional[int],
               cover: Optional[Dict[str, int]] = None) -> Verdict:
    """artifact: the xclbin the job was told to soak (None: the software backend, which
    only the dry run and the rate-free self checks use). expected_cases: exact, where
    the tool's counting is known (see Item.expected_cases), else None (then > 0).
    cover: for a job whose line says what it covered (Item.cover_spec): {"encodings": the
    slice's, "per_encoding": k}. The line must then carry ", E encodings, S skipped", E must
    be the slice's encodings, and cases + S must be k * E - so a slice that ran short, or
    long, or whose tool does not print the clause, is refused, and a slice that compared
    nothing because every pair was skipped (an all-NaN slice of cvtto32-all) is not."""
    m = _one(SOAK_LINE, text, "soak verdict")
    if m.group(1) != op or m.group(2) != verdict_mode:
        raise VerdictError(f"soak: the verdict is for '{m.group(1)} {m.group(2)}', the job "
                           f"was '{op} {verdict_mode}'")
    cases, vm, fm = int(m.group(3)), int(m.group(4)), int(m.group(5))
    enc = int(m.group(6)) if m.group(6) is not None else None
    skp = int(m.group(7)) if m.group(7) is not None else None
    dev = _maybe_one(SOAK_DEVICE, text, "soak backend line")
    sw = _maybe_one(SOAK_SOFTWARE, text, "soak backend line")
    if artifact is not None:
        if not dev or sw:
            raise VerdictError("soak: no 'soaking the DEVICE backend' line - the job did "
                               "not run on the card, so it proves nothing about it")
        if dev.group(1) != artifact:
            raise VerdictError(f"soak: it soaked {dev.group(1)!r}, not {artifact!r}")
    libfail = SOAK_LIBFAIL.search(text) is not None
    disagreements = [x.group(0).strip() for x in SOAK_DISAGREE.finditer(text)][:16]
    counts = {"cases": cases, "value_mismatches": vm, "flag_mismatches": fm}
    if enc is not None:
        counts["encodings"] = enc
        counts["skipped"] = skp
    if libfail:
        # The tool printed a verdict for the cases before the failure; it is not a
        # completed slice, and not a disagreement either: the card failed to answer.
        raise VerdictError("soak: 'library call failed' - the device did not answer a call "
                           f"(after {cases} cases)")
    if expected_cases is not None and cases != expected_cases:
        raise VerdictError(f"soak: {cases} cases where the slice has {expected_cases}")
    if cover is not None:
        if enc is None:
            raise VerdictError("soak: no ', E encodings, S skipped' clause on the verdict line, "
                               "which this job's tool prints so that a slice's coverage can be "
                               "checked - it is not the tool this driver was written for")
        if enc != cover["encodings"]:
            raise VerdictError(f"soak: {enc} encodings where the slice has {cover['encodings']}")
        want = cover["per_encoding"] * enc
        if cases + skp != want:
            raise VerdictError(f"soak: {cases} cases and {skp} skipped make {cases + skp} checks "
                               f"where {cover['per_encoding']} for each of {enc} encodings make {want}")
    elif expected_cases is None and cases == 0:
        raise VerdictError("soak: 0 cases - the tool ran nothing (its probe may have "
                           "degraded the job)")
    ok = vm == 0 and fm == 0
    _rc_agrees(rc, ok, "soak")
    v = Verdict(ok, counts, extra={"disagreements": disagreements})
    return v


# ---------------------------------------------------------------------------
# "the card is not answering": what the tools print when they cannot use the device.
# Used only when no verdict parsed (a parsed verdict is a card that answered).
# Each line cites where the sentence comes from.
# ---------------------------------------------------------------------------
INFRA_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    ("no_device", re.compile(r"no such device")),                      # device.c:364
    ("no_device", re.compile(r"opening device \d+: ")),                # backend_xrt.cpp:1907
    ("no_device", re.compile(r"cft_open\(.*\) failed: ")),             # divsqrt_soak.c:437
    ("no_device", re.compile(r"^device \S+: ", M)),                    # device_test.c:9884
    ("no_device", re.compile(r"loading \S+: ")),                       # backend_xrt.cpp:1948
    ("no_device", re.compile(r"failed to open cu context")),           # HOSTAPI.md, held tile
    ("poisoned", re.compile(r"is already running when this handle opens it")),
    ("poisoned", re.compile(r"is running work this process did not start")),
    ("poisoned", re.compile(r"complete while tile \d+")),
    ("no_device", re.compile(r"artifact missing, unreadable, or not a tile")),
    ("no_device", re.compile(r"^  library call failed", M)),            # the soaks: a call the device did not answer
    ("no_device", re.compile(r"CFT_ERR_TIMEOUT|timed out|did not complete within")),
]


def classify_infra(text: str) -> Optional[str]:
    for name, rx in INFRA_PATTERNS:
        if rx.search(text):
            return name
    return None


# ---------------------------------------------------------------------------
# sweep items: the native-oracle soaks' campaigns, as hw/run-soak.sh and
# hw/run-c5-soak.sh list them, cut into slices the driver runs one at a time.
# ---------------------------------------------------------------------------
EXH = 1 << 32           # all fp32 encodings
ATOM = 1 << 20          # slice boundaries are multiples of this
MODES5 = ("rne", "rtz", "rdn", "rup", "rmm")
MODES4 = ("rne", "rtz", "rdn", "rup")

# Checks a slice of each exhaustive conversion/scaleB mode makes for every encoding of its
# operand, compared (a case) or skipped, held by the tool's own verdict line (its ", E
# encodings, S skipped" clause) and by the real logs of hw/card_stress_fixtures. From
# host/tools/clause5_soak.c's "Exhaustive modes" section: conv32to64-all widens each fp32
# encoding once; cvtto32-all runs each against the four integer targets (a pair is skipped
# where the rounded value leaves the target's range, so its CASES depend on the operands and
# only cases + skipped is fixed); cvtfrom32-all and cvtfrom64-all convert each 32-bit integer as
# an i32 and as a u32; scaleb32-all runs the 17 exponents of the directed list; scaleb32-wide the
# 556 exponents -278..277 that can change a result and 12 witnesses past them.
PER_ENCODING = {"conv32to64-all": 1, "cvtto32-all": 4, "cvtfrom32-all": 2, "cvtfrom64-all": 2,
                "scaleb32-all": 17, "scaleb32-wide": 556 + 12}

# WHERE EACH SOAK'S WORK RUNS: on the tile or on the host. The campaign's items are not all tests of
# the card. From the library's own classification, host/include/cft.h ("The remaining clause-5
# operations") and the header of host/src/clause5.c (lines 13-25): COMPOSED operations - cft_rint,
# cft_scaleb, cft_cmp_sig - are cft_run() passes, "on a device it runs on the tile"; HOST
# operations - cft_convert, the integer conversions, cft_logb, cft_next_*, cft_class,
# cft_total_order*, cft_rem - "contain NO floating-point arithmetic at all ... nothing for a device
# to accelerate and no backend pass to issue. The device argument is context ... not a
# participant. They are bit-identical on every backend by construction". The section headings of
# that file say the same: "roundToIntegral: composed", "scaleB: composed" against "format
# conversion: host", "integer conversions: host", "logB: host", "nextUp / nextDown: host",
# "classification: host", "remainder: host" (cft_rem has no cft_run call). cft_div and cft_sqrt
# (host/src/divsqrt.c, header lines 4-21) are composed from the operations the tile has: every
# floating-point step is one cft_run().
# So a card soak of a HOST item runs libcft's host code on the box against the box's CPU: a
# full-space test of the library that the software backend on any CPU repeats, and one in which
# the tile computes nothing. The host items stay in the campaign, and every record says which
# kind it is (sweep.reach). scaleB is TILE with one qualification: its multiplies run on
# the tile only for an exponent at or above the format's subnormal floor (-149 for fp32, -1074 for
# fp64); below that cft_scaleb takes its host path.
TILE, HOST = "tile", "host"
OP_REACH = {
    # host/src/divsqrt.c: composed
    "sqrt32": TILE, "sqrt64": TILE, "div32": TILE, "div64": TILE,
    # host/src/clause5.c: roundToIntegral and scaleB are composed
    "rint32": TILE, "rint64": TILE,
    "scaleb32": TILE, "scaleb64": TILE, "scaleb32-all": TILE, "scaleb32-wide": TILE,
    # host/src/clause5.c: host
    "nextup32": HOST, "nextdown32": HOST, "logb32": HOST, "class32": HOST,
    "nextup64": HOST, "nextdown64": HOST, "logb64": HOST, "class64": HOST,
    "conv32to64": HOST, "conv64to32": HOST, "conv32to64-all": HOST,
    "cvtto32": HOST, "cvtto64": HOST, "cvtto32-all": HOST,
    "cvtfrom32": HOST, "cvtfrom64": HOST, "cvtfrom32-all": HOST, "cvtfrom64-all": HOST,
    "rem32": HOST, "rem64": HOST,
}


def reach_of(op: Optional[str]) -> Optional[str]:
    """'tile' or 'host' for a soak job word, or None for one this table does not know."""
    return OP_REACH.get(op) if isinstance(op, str) else None


class Item:
    """One campaign line. kind 'exhaustive': encodings [0, 2^32), sliced; kind 'random':
    a count of cases from a seed, any number of slices, each its own seed."""

    def __init__(self, name: str, tool: str, kind: str, op: str, mode: Optional[str],
                 base_seed: int = 0, verdict_mode: str = "-", extra_cases: int = 0,
                 exact: bool = False, per_encoding: Optional[int] = None):
        self.name = name
        self.tool = tool              # 'divsqrt' | 'clause5'
        self.kind = kind              # 'exhaustive' | 'random'
        self.op = op
        self.mode = mode              # argv's mode word, or None when the job takes none
        self.base_seed = base_seed
        self.verdict_mode = verdict_mode      # the second word of the tool's verdict line
        self.extra_cases = extra_cases        # cases the tool adds to every slice
        self.exact = exact                    # cases == slice size (+ extra) is known
        # checks (compared or skipped) the tool makes for each encoding of a slice, for a job
        # whose verdict line says what it covered (the -all and -wide modes); None for the rest
        self.per_encoding = per_encoding
        # 'tile' or 'host' (OP_REACH): whether the job's work runs on the card's tile at all
        self.reach = OP_REACH[op]

    def argv(self, binary: str, lo: int = 0, hi: int = 0, count: int = 0,
             seed: int = 0) -> List[str]:
        if self.kind == "exhaustive":
            a = [binary, self.op, str(lo), str(hi)]
        else:
            a = [binary, self.op, str(count), str(seed)]
        if self.mode is not None:
            a.append(self.mode)
        return a

    def expected_cases(self, lo: int, hi: int) -> Optional[int]:
        """The exact count of cases a slice prints, where it is a function of the slice alone:
        the slice's size times the checks an encoding takes, plus the cases the tool adds to
        every slice (nextup32's eight edges). None where it is not (cvtto32-all, random)."""
        if self.kind == "exhaustive" and self.exact:
            return (hi - lo) * (self.per_encoding or 1) + self.extra_cases
        return None

    def cover_spec(self, lo: int, hi: int) -> Optional[Dict[str, int]]:
        """What the verdict line of a slice must say it covered (parse_soak's `cover`), for the
        jobs that say it; None for the others."""
        if self.kind == "exhaustive" and self.per_encoding is not None:
            return {"encodings": hi - lo, "per_encoding": self.per_encoding}
        return None

    def seed_for(self, n: int) -> int:
        """The n-th random slice's seed (0-based): distinct, nonzero, recorded."""
        return self.base_seed + 7919 * n


def sweep_items(scaleb_modes: Iterable[str] = MODES4,
                cvtfrom_modes: Iterable[str] = MODES4,
                wide_modes: Optional[Iterable[str]] = None) -> List[Item]:
    """The campaign, in run-soak.sh's and run-c5-soak.sh's own order and with their seeds.
    scaleb_modes and cvtfrom_modes are what run-c5-soak.sh's probes decide ('rne' alone
    when a probe fails); hw/card_stress.py runs the same probes. wide_modes are the modes
    of scaleb32-wide: the scaleb modes, unless `probe scalebrange` found the derived exponent
    range does not hold on this libm, and then none (the script drops those jobs the same way)."""
    scaleb_modes, cvtfrom_modes = tuple(scaleb_modes), tuple(cvtfrom_modes)
    wide_modes = scaleb_modes if wide_modes is None else tuple(wide_modes)
    items: List[Item] = []
    # hw/run-soak.sh: exhaustive fp32 sqrt, five modes (RMM rides the RNE oracle)
    for mode in MODES5:
        items.append(Item(f"sqrt32-{mode}", "divsqrt", "exhaustive", "sqrt32", mode,
                          verdict_mode=mode, exact=True))
    # hw/run-soak.sh: random banded div32 / div64 / sqrt64, seeds 0x50AC0000 + s
    s = 1
    for op in ("div32", "div64", "sqrt64"):
        for mode in MODES4:
            items.append(Item(f"{op}-{mode}", "divsqrt", "random", op, mode,
                              base_seed=0x50AC0000 + s, verdict_mode=mode))
            s += 1
    # hw/run-c5-soak.sh: exhaustive fp32 clause 5
    for mode in MODES5:
        items.append(Item(f"rint32-{mode}", "clause5", "exhaustive", "rint32", mode,
                          verdict_mode=mode, exact=True))
    # nextup32 and nextdown32 run eight edge cases in EVERY slice before the range
    # (clause5_soak.c:629-635 calls next_edges32, which counts eight)
    items.append(Item("nextup32", "clause5", "exhaustive", "nextup32", None,
                      verdict_mode="-", extra_cases=8, exact=True))
    items.append(Item("nextdown32", "clause5", "exhaustive", "nextdown32", None,
                      verdict_mode="-", extra_cases=8, exact=True))
    items.append(Item("logb32", "clause5", "exhaustive", "logb32", None,
                      verdict_mode="-", exact=True))
    items.append(Item("class32", "clause5", "exhaustive", "class32", None,
                      verdict_mode="-", exact=True))
    # hw/run-c5-soak.sh: the exhaustive modes of the 32-bit-operand conversions and scaleB, in
    # its order. Each says what it covered on its verdict line (PER_ENCODING above); the four
    # with a probe (cvtfrom32-all, cvtfrom64-all, scaleb32-all, scaleb32-wide) take the modes
    # the probe allows, as their random modes do. conv32to64-all takes no mode word and its
    # verdict says "rne", like conv32to64.
    items.append(Item("conv32to64-all", "clause5", "exhaustive", "conv32to64-all", None,
                      verdict_mode="rne", exact=True,
                      per_encoding=PER_ENCODING["conv32to64-all"]))
    for mode in MODES5:
        items.append(Item(f"cvtto32-all-{mode}", "clause5", "exhaustive", "cvtto32-all", mode,
                          verdict_mode=mode, per_encoding=PER_ENCODING["cvtto32-all"]))
    for op in ("cvtfrom32-all", "cvtfrom64-all"):
        for mode in cvtfrom_modes:
            items.append(Item(f"{op}-{mode}", "clause5", "exhaustive", op, mode,
                              verdict_mode=mode, exact=True, per_encoding=PER_ENCODING[op]))
    for op, modes in (("scaleb32-all", scaleb_modes), ("scaleb32-wide", wide_modes)):
        for mode in modes:
            items.append(Item(f"{op}-{mode}", "clause5", "exhaustive", op, mode,
                              verdict_mode=mode, exact=True, per_encoding=PER_ENCODING[op]))
    # hw/run-c5-soak.sh: the random campaigns, seed 0xC5000000 + s in its loop order
    s = 1
    for mode in MODES5:
        items.append(Item(f"rint64-{mode}", "clause5", "random", "rint64", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
        items.append(Item(f"cvtto32-{mode}", "clause5", "random", "cvtto32", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
        items.append(Item(f"cvtto64-{mode}", "clause5", "random", "cvtto64", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
    for mode in scaleb_modes:
        items.append(Item(f"scaleb32-{mode}", "clause5", "random", "scaleb32", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
        items.append(Item(f"scaleb64-{mode}", "clause5", "random", "scaleb64", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
    for mode in MODES4:
        items.append(Item(f"conv64to32-{mode}", "clause5", "random", "conv64to32", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
    for mode in cvtfrom_modes:
        items.append(Item(f"cvtfrom32-{mode}", "clause5", "random", "cvtfrom32", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
        items.append(Item(f"cvtfrom64-{mode}", "clause5", "random", "cvtfrom64", mode,
                          base_seed=0xC5000000 + s, verdict_mode=mode)); s += 1
    # conv32to64 takes no mode word and its verdict says "rne" (clause5_soak.c:1981)
    items.append(Item("conv32to64", "clause5", "random", "conv32to64", None,
                      base_seed=0xC5000000 + s, verdict_mode="rne")); s += 1
    items.append(Item("rem32", "clause5", "random", "rem32", None,
                      base_seed=0xC5000000 + s, verdict_mode="-")); s += 1
    items.append(Item("rem64", "clause5", "random", "rem64", None,
                      base_seed=0xC5000000 + s, verdict_mode="-")); s += 1
    for op in ("nextup64", "nextdown64", "logb64", "class64"):
        items.append(Item(op, "clause5", "random", op, None,
                          base_seed=0xC5000000 + s, verdict_mode="-")); s += 1
    return items


# ---------------------------------------------------------------------------
# intervals: the exhaustive items' coverage
# ---------------------------------------------------------------------------

def merge_intervals(iv: Iterable[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Sorted, merged, adjacent intervals joined. [lo, hi) each."""
    out: List[Tuple[int, int]] = []
    for lo, hi in sorted(iv):
        if hi <= lo:
            raise ValueError(f"empty or reversed interval [{lo}, {hi})")
        if out and lo <= out[-1][1]:
            if hi > out[-1][1]:
                out[-1] = (out[-1][0], hi)
        else:
            out.append((lo, hi))
    return out


def covered(iv: Iterable[Tuple[int, int]]) -> int:
    return sum(hi - lo for lo, hi in merge_intervals(iv))


def first_gap(iv: Iterable[Tuple[int, int]], total: int = EXH) -> Optional[Tuple[int, int]]:
    """The first uncovered [lo, hi) within [0, total), or None when all is covered."""
    pos = 0
    for lo, hi in merge_intervals(iv):
        if lo > pos:
            return (pos, min(lo, total))
        pos = max(pos, hi)
        if pos >= total:
            return None
    return (pos, total) if pos < total else None


# ---------------------------------------------------------------------------
# the metrics file: one JSON object a line, appended, never rewritten
# ---------------------------------------------------------------------------

def append_record(path: str, rec: Dict[str, Any]) -> None:
    """One whole line in one write on an O_APPEND descriptor, so a reader sees a
    record or none; then fsync (a few records a minute at most)."""
    rec = dict(rec)
    rec.setdefault("v", 1)
    now = time.time()
    rec.setdefault("ts", iso(now))
    rec.setdefault("epoch", round(now, 3))
    line = (json.dumps(rec, sort_keys=False, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)


def read_records(path: str) -> Tuple[List[Dict[str, Any]], bool, List[int]]:
    """(records, partial_tail, bad_line_numbers). A last line with no newline that does not
    parse is a writer caught mid-append: skipped and reported as partial_tail. Any other
    line that does not parse is reported in bad_line_numbers (1-based) and skipped - the
    report prints it; nothing here hides it."""
    recs: List[Dict[str, Any]] = []
    bad: List[int] = []
    partial = False
    with open(path, "rb") as fh:
        data = fh.read()
    lines = data.split(b"\n")
    tail = lines.pop()          # text after the last newline: "" when the file is whole
    for i, ln in enumerate(lines, 1):
        if not ln.strip():
            continue
        try:
            recs.append(json.loads(ln.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            bad.append(i)
    if tail.strip():
        try:
            recs.append(json.loads(tail.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            partial = True
    return recs, partial, bad


def sweep_coverage(records: Iterable[Dict[str, Any]]):
    """Rebuild the sweep's state from the leg records alone: (intervals by item, the
    count of cases and slices served by item, every disagreement). A slice is COVERED
    when its leg finished with a verdict - status 'pass', or 'fail' with mismatch counts -
    and not when it timed out, lost the device or failed to parse."""
    intervals: Dict[str, List[Tuple[int, int]]] = {}
    served: Dict[str, int] = {}
    cases: Dict[str, int] = {}
    seeds: Dict[str, int] = {}
    disagree: List[Dict[str, Any]] = []
    for r in records:
        if r.get("type") != "leg" or r.get("kind") != "sweep":
            continue
        sw = r.get("sweep") or {}
        item = sw.get("item")
        if not item or r.get("status") not in ("pass", "fail"):
            continue
        counts = r.get("counts") or {}
        served[item] = served.get(item, 0) + 1
        cases[item] = cases.get(item, 0) + int(counts.get("cases", 0))
        if "lo" in sw and "hi" in sw:
            intervals.setdefault(item, []).append((int(sw["lo"]), int(sw["hi"])))
        if "seed_n" in sw:
            seeds[item] = max(seeds.get(item, -1), int(sw["seed_n"]))
        if r.get("status") == "fail":
            disagree.append({"item": item, "sweep": sw, "counts": counts,
                             "lines": r.get("disagreements") or [], "log": r.get("log"),
                             "start": r.get("start"), "image": r.get("image")})
    return intervals, served, cases, seeds, disagree


# ---------------------------------------------------------------------------
# telemetry: xbutil / xrt-smi examine's output, and the host's
# ---------------------------------------------------------------------------
_NUM = re.compile(r"^-?\d+(?:\.\d+)?$")


def _num(x: Any) -> Optional[float]:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str) and _NUM.match(x.strip()):
        return float(x.strip())
    return None


def flatten_numbers(obj: Any, prefix: str = "") -> Dict[str, float]:
    """Every numeric leaf of a JSON value, keyed by a label: the enclosing objects'
    'description' / 'location_id' / 'id' / 'name' where they carry one, and the leaf's
    key. XRT writes most numbers as strings ("30"), which are read as numbers. The
    schema of xbutil's JSON is not fixed here (BELIEVED from memory of XRT 2.x, not read
    from a card): a number is kept under whatever label its neighbours give it."""
    out: Dict[str, float] = {}

    def walk(o: Any, label: str) -> None:
        if isinstance(o, dict):
            tag = ""
            for k in ("description", "location_id", "id", "name"):
                v = o.get(k)
                if isinstance(v, str) and v:
                    tag = v
                    break
            here = f"{label}.{tag}" if (label and tag) else (tag or label)
            for k, v in o.items():
                if k in ("description", "location_id", "id", "name"):
                    continue
                walk(v, f"{here}.{k}" if here else str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                # an element that names itself is labelled by its name, so a reordered
                # list gives the same labels; an anonymous one by its position
                named = isinstance(v, dict) and any(
                    isinstance(v.get(k), str) and v.get(k)
                    for k in ("description", "location_id", "id", "name"))
                walk(v, label if named else (f"{label}[{i}]" if label else f"[{i}]"))
        else:
            n = _num(o)
            if n is not None:
                out[label] = n

    walk(obj, prefix)
    return out


_TEXT_ROW = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _()./#-]*?)\s*:?\s+(-?\d+(?:\.\d+)?)\s*"
                       r"(?:C|W|V|A|mV|mA|MHz|RPM|%|Watts|Volts|Amps)?\s*$")


def parse_telemetry(text: str) -> Dict[str, float]:
    """JSON first (xbutil examine --format JSON), else 'label  value [unit]' rows of the
    as-is text. Returns {} when nothing is read: the caller records the raw text then
    and says so, never an empty reading as though it were a reading."""
    s = text.strip()
    if s.startswith("{") or s.startswith("["):
        try:
            return flatten_numbers(json.loads(s))
        except ValueError:
            pass
    out: Dict[str, float] = {}
    for ln in text.splitlines():
        m = _TEXT_ROW.match(ln)
        if m:
            out[m.group(1).strip()] = float(m.group(2))
    return out


def host_sample(paths: Iterable[str]) -> Dict[str, Any]:
    """Load, memory and free disk, where the host reports them (Linux's /proc; elsewhere
    those fields are simply absent, never zero)."""
    import shutil
    h: Dict[str, Any] = {}
    try:
        l1, l5, l15 = os.getloadavg()
        h.update(load1=round(l1, 2), load5=round(l5, 2), load15=round(l15, 2))
    except (AttributeError, OSError):
        pass
    try:
        with open("/proc/meminfo", "r", encoding="ascii", errors="replace") as fh:
            for ln in fh:
                if ln.startswith("MemAvailable:"):
                    h["mem_avail_mb"] = int(ln.split()[1]) // 1024
                elif ln.startswith("MemTotal:"):
                    h["mem_total_mb"] = int(ln.split()[1]) // 1024
    except OSError:
        pass
    free: Dict[str, float] = {}
    for p in paths:
        try:
            free[p] = round(shutil.disk_usage(p).free / 1e9, 2)
        except OSError:
            pass
    if free:
        h["disk_free_gb"] = free
    return h


# ---------------------------------------------------------------------------
# a weighted rotation (smooth weighted round robin), deterministic from its history
# ---------------------------------------------------------------------------

def smooth_wrr(weights: Dict[str, int], n: int) -> List[str]:
    """The first n picks. Each round every name gains its weight; the largest total is
    picked and loses the sum of the weights. With quad=4, single=1, deep=1 it picks the
    quad four times in six, spread out, never the single twice in a row."""
    total = sum(weights.values())
    cur = {k: 0 for k in weights}
    picks: List[str] = []
    for _ in range(n):
        for k, w in weights.items():
            cur[k] += w
        best = max(weights, key=lambda k: (cur[k], -list(weights).index(k)))
        cur[best] -= total
        picks.append(best)
    return picks
