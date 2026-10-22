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
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


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
# The chunked tools' second stderr line (divsqrt_soak.c:1036, clause5_soak.c:2963, host/Makefile's soak-chunk): printed only when
# BATCH or CFT_CHUNK is not 4096, after the backend line, which stays as it was. A tool built at 4096 prints nothing more.
SOAK_CHUNK_LINE = re.compile(r"^soaking with BATCH (\d+) and CFT_CHUNK (\d+) \(the defaults are 4096\)$", M)


class SoakResult(Verdict):
    pass


CPU_OPENED_CARD = "soak: a CPU job opened the card"     # a CPU job's log that names a DEVICE: the pool's one promise broken


def parse_soak(text: str, rc: Optional[int], op: str, verdict_mode: str,
               artifact: Optional[str], expected_cases: Optional[int],
               cover: Optional[Dict[str, int]] = None, cpu: bool = False,
               chunk: Optional[int] = None) -> Verdict:
    """artifact: the xclbin the job was told to soak (None: the software backend, which
    only the dry run and the rate-free self checks use). expected_cases: exact, where
    the tool's counting is known (see Item.expected_cases), else None (then > 0).
    cover: for a job whose line says what it covered (Item.cover_spec): {"encodings": the
    slice's, "per_encoding": k}. The line must then carry ", E encodings, S skipped", E must
    be the slice's encodings, and cases + S must be k * E - so a slice that ran short, or
    long, or whose tool does not print the clause, is refused, and a slice that compared
    nothing because every pair was skipped (an all-NaN slice of cvtto32-all) is not.
    cpu: a job of the host pool, which is told no image and must say it soaked the software
    backend; a log that names a DEVICE is refused, by name (CPU_OPENED_CARD), because a CPU job
    that opened the card has broken the one promise the pool makes.
    chunk: the pass size the job was asked to run at (--sweep-chunk: the tool's -c<chunk> build), None for the default tool.
    The log must then say what it ran at and agree: a chunked build (other than 4096, which prints nothing) carries the line
    'soaking with BATCH n and CFT_CHUNK n (the defaults are 4096)' with both numbers the request's, and the verdict's extra
    gives them as `batch` and `chunk`; a log that disagrees, or lacks the line, is refused by name. For the default tool
    (None) a log that carries the line is refused too: that binary was not built as the default, and its slice would otherwise
    be recorded as one compared over 4096 operands."""
    m = _one(SOAK_LINE, text, "soak verdict")
    if m.group(1) != op or m.group(2) != verdict_mode:
        raise VerdictError(f"soak: the verdict is for '{m.group(1)} {m.group(2)}', the job "
                           f"was '{op} {verdict_mode}'")
    cases, vm, fm = int(m.group(3)), int(m.group(4)), int(m.group(5))
    enc = int(m.group(6)) if m.group(6) is not None else None
    skp = int(m.group(7)) if m.group(7) is not None else None
    dev = _maybe_one(SOAK_DEVICE, text, "soak backend line")
    sw = _maybe_one(SOAK_SOFTWARE, text, "soak backend line")
    if cpu:
        if dev:
            raise VerdictError(f"{CPU_OPENED_CARD} ('soaking the DEVICE backend: {dev.group(1)}'): CFT_SOAK_ARTIFACT "
                               f"reached a job the pool starts without an image")
        if not sw:
            raise VerdictError("soak: a CPU job's log has no 'soaking the software backend' line, so it is not "
                               "known which backend it ran on")
    if artifact is not None:
        if not dev or sw:
            raise VerdictError("soak: no 'soaking the DEVICE backend' line - the job did "
                               "not run on the card, so it proves nothing about it")
        if dev.group(1) != artifact:
            raise VerdictError(f"soak: it soaked {dev.group(1)!r}, not {artifact!r}")
    pass_size: Dict[str, int] = {}
    cl = _maybe_one(SOAK_CHUNK_LINE, text, "soak pass-size line")
    if chunk is None:
        if cl:
            raise VerdictError(f"soak: a job of the default tool says it ran at BATCH {cl.group(1)} and CFT_CHUNK "
                               f"{cl.group(2)}: that binary is not the default build, and nothing here would record it so")
    elif chunk == DEFAULT_BATCH:
        if cl:
            raise VerdictError(f"soak: the job was asked to run at the default pass size {chunk} (a build that prints no "
                               f"pass-size line) and says BATCH {cl.group(1)} and CFT_CHUNK {cl.group(2)}")
        pass_size = {"batch": DEFAULT_BATCH, "chunk": DEFAULT_BATCH}
    else:
        if not cl:
            raise VerdictError(f"soak: the job was asked to run at pass size {chunk} and its log has no 'soaking with BATCH n "
                               f"and CFT_CHUNK n' line, so it is not known what it ran at")
        if int(cl.group(1)) != chunk or int(cl.group(2)) != chunk:
            raise VerdictError(f"soak: the job was asked to run at pass size {chunk} and the tool says BATCH {cl.group(1)} and "
                               f"CFT_CHUNK {cl.group(2)}")
        pass_size = {"batch": int(cl.group(1)), "chunk": int(cl.group(2))}
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
    v = Verdict(ok, counts, extra=dict({"disagreements": disagreements}, **pass_size))
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

# THE INDEX-BASED ITEMS OF THE COVERAGE WAVE (2026-10-20): modes whose "encodings" are the indices of a space that is NOT
# 2^32, each a `<lo> <hi> <attribute>` job whose verdict line carries ", E encodings, S skipped" with E counting indices.
# Parcel HC (host/tools/divsqrt_soak.c, "Hard cases"; python/hardcases.py): constructed operands, k slots an index
# (division: the four sign combinations of one pair; square root: one), cases + S = k x E, and the cases of a slice are NOT
# a function of its bounds (an index whose construction yields no pair skips all k slots). Parcel CL (host/tools/clause5_soak.c,
# "Class-level (L2) modes"; python/c5_class_enum.py): one operand (a pair for scaleB) an index and k checks an index, a case a
# target (cvtto64-class) or a case a tile lane (rint64-class, scaleb64-class); only cvtto64-class skips. `(indices, k)`:
HARD_SPACE = {"div32-hard": (21_235_788, 4), "div64-hard": (289_685_696, 4), "sqrt64-hard": (4_456_448, 1)}
CLASS_SPACE = {"conv64to32-class": (136_192, 1), "rint64-class": (35_840, 4), "cvtto64-class": (40_768, 4),
               "cvtfrom64-class": (50_923, 1), "scaleb64-class": (72_648, 4)}
# The cases and skipped slots of a mode over its WHOLE space, which the slices of a covered item must add up to. HC's, from
# `divsqrt-soak hard-count MODE 0 N` (the builders alone, no library; the same for every attribute); CL's only for the one
# mode that skips, cvtto64-class, by attribute (the tool's own counts, each equal to a count made in Python from the rounding rule
# alone, docs/CARDDAY.md): every other class mode makes k x E cases and skips none, which its `exact` rule already holds.
HARD_WHOLE = {"div32-hard": (64_346_592, 20_596_560), "div64-hard": (812_489_184, 346_253_600),
              "sqrt64-hard": (1_745_752, 2_710_696)}
CVTTO64_CLASS_WHOLE = {"rne": (91_005, 72_067), "rtz": (91_484, 71_588), "rdn": (85_141, 77_931),
                       "rup": (91_478, 71_594), "rmm": (90_986, 72_086)}
# The random ops whose OPERAND STREAM depends on BATCH (CK, 2026-10-20; READ in host/tools/clause5_soak.c drv_cvtfrom: a batch draws n
# operands for each of four source types in turn, so another BATCH hands the same draws to other types), and the call size of the
# tools as built by default (host/tools/*.c, `#define BATCH 4096`; the chunked tools say theirs on a stderr line).
LAYOUT_OPS = ("cvtfrom32", "cvtfrom64")
DEFAULT_BATCH = 4096
# The exponent lists random scaleB runs every batch against (SCALEB_N32 and SCALEB_N64 in host/tools/clause5_soak.c): a batch of n
# operands makes n x len cases and takes that many off the slice's count, so the cases of a slice are its count rounded UP by
# whole batches - and which whole batches depends on BATCH (CK's finding i: `scaleb32 100000 5 rne` 139,264 cases at 4096, 278,528 at 16384).
SCALEB_LIST = {"scaleb32": 17, "scaleb64": 27}
# The cases every OTHER random op's tool prints for a slice of `count`: (cases a count, cases added to every slice), so that a random slice
# is held to what it was asked for (KL-23, 2026-10-22; before it, only random scaleB under --sweep-chunk was, and a tool that stopped short
# still counted as covered if it printed one case). READ in host/tools/divsqrt_soak.c (soak_random and run_batch: `cases += n` a batch of n
# operands) and host/tools/clause5_soak.c (each drv_* and its batch function: `cases += n`; drv_cvtfrom runs cvtfrom_check, which adds n,
# for each of four source types, so 4 a count; drv_next64 runs next_edges64 first, eight cases), and MEASURED with those tools as built at
# f707fa3b on the software backend, at counts 1, 4095, 4096, 4097, 10000 and 20000 (hw/card_stress_fixtures/rnd-*.txt keeps one log of each,
# and the suite holds this table to them). None of these depends on BATCH (scaleB's does, above).
RANDOM_CASES = {
    "div32": (1, 0), "div64": (1, 0), "sqrt64": (1, 0),
    "rint64": (1, 0), "conv64to32": (1, 0), "conv32to64": (1, 0), "rem32": (1, 0), "rem64": (1, 0), "logb64": (1, 0), "class64": (1, 0),
    "cvtfrom32": (4, 0), "cvtfrom64": (4, 0),
    "nextup64": (1, 8), "nextdown64": (1, 8),
}
# The random ops whose cases are NOT held to a count, by name: drv_cvtto adds, for each of four integer targets, the lanes of the batch that
# are in the target's range (`cases += m`), so the cases are a function of the draws - 2.3 a count for cvtto32 and 2.0 for cvtto64 in the
# measurement above, 4 for a count of 1. The tool also prints "  skipped N lane-target pairs outside the target range" for the other lanes, and
# cases + skipped is 4 x count (MEASURED: 22,865 + 17,135 and 20,150 + 19,850 at a count of 10,000: hw/card_stress_fixtures/rnd-cvtto*.txt), which
# would hold them. parse_soak does not read that line (it is an import of the scheduler's runner, and reading it takes a new parameter), so
# they keep the rule they had - more than zero cases - and this is a known limit, not a figure. See docs/CARDDAY.md.
RANDOM_CASES_DRAWN = ("cvtto32", "cvtto64")

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
    # parcel HC, host/tools/divsqrt_soak.c: the hard-case modes call the same batch kernel as the random modes of the operation
    # (cft_div, cft_sqrt: composed of tile passes), so they reach the tile as those do
    "div32-hard": TILE, "div64-hard": TILE, "sqrt64-hard": TILE,
    # parcel CL, host/tools/clause5_soak.c: the class-level modes call the random mode's kernels: roundToIntegral and scaleB are
    # composed (cft_rint, cft_scaleb: tile), the three conversions are host operations
    "rint64-class": TILE, "scaleb64-class": TILE,
    "conv64to32-class": HOST, "cvtto64-class": HOST, "cvtfrom64-class": HOST,
}


def reach_of(op: Optional[str]) -> Optional[str]:
    """'tile' or 'host' for a soak job word, or None for one this table does not know."""
    return OP_REACH.get(op) if isinstance(op, str) else None


# THE SEEDS. Both soak tools set rng_state = seed | 1 and draw from there, so two slices of one state draw the
# same operands, and the schedule up to 2026-10-19 (seed = base_seed + 7919 n, n restarting at 0 in every new
# --out) gave neighbouring items one state on half the n and every new run the last run's draws
# (docs/studies/SWP-A-coverage.md, 2.4: 96.2 per cent of the final run's random slices shared a state). From
# 2026-10-20 a random item's n-th slice has the seed
#     (item index << 40) | (n << 1) | 1
# (schedule A of docs/studies/swp-a/seed_audit.py): odd already, so `| 1` changes nothing, and distinct for
# every (item, n) with n < 2^39 by construction - the index fills bits 40 up, n bits 1 to 39. The index is the
# item's place in this table BY NAME, not its place in the catalog: the catalog loses items when a probe fails
# (a run on a libm without directed scalbn has fewer), and a position would then shift every later item's seeds.
# A new random item is APPENDED here (sweep_items refuses a random item that is not in the table, by name).
# `seed_scheme` 2 is recorded in each random slice's record; a record without it is the old schedule (1).
SEED_SCHEME = 2
SEED_N_LIMIT = 1 << 39
RANDOM_SEED_ORDER = (
    "div32-rne", "div32-rtz", "div32-rdn", "div32-rup", "div64-rne", "div64-rtz", "div64-rdn", "div64-rup",
    "sqrt64-rne", "sqrt64-rtz", "sqrt64-rdn", "sqrt64-rup",
    "rint64-rne", "cvtto32-rne", "cvtto64-rne", "rint64-rtz", "cvtto32-rtz", "cvtto64-rtz",
    "rint64-rdn", "cvtto32-rdn", "cvtto64-rdn", "rint64-rup", "cvtto32-rup", "cvtto64-rup",
    "rint64-rmm", "cvtto32-rmm", "cvtto64-rmm",
    "scaleb32-rne", "scaleb64-rne", "scaleb32-rtz", "scaleb64-rtz", "scaleb32-rdn", "scaleb64-rdn",
    "scaleb32-rup", "scaleb64-rup",
    "conv64to32-rne", "conv64to32-rtz", "conv64to32-rdn", "conv64to32-rup",
    "cvtfrom32-rne", "cvtfrom64-rne", "cvtfrom32-rtz", "cvtfrom64-rtz", "cvtfrom32-rdn", "cvtfrom64-rdn",
    "cvtfrom32-rup", "cvtfrom64-rup",
    "conv32to64", "rem32", "rem64", "nextup64", "nextdown64", "logb64", "class64",
)
RANDOM_SEED_INDEX = {name: i for i, name in enumerate(RANDOM_SEED_ORDER)}

# The host pool's slices are recorded under this image name: no image, no card (hw/card_stress.py, the pool).
CPU = "cpu"
# A host slice is sized like a card slice (the probe, then the measured rate x the target seconds, whole ATOMs)
# but is held at this many counts, not the card's 2^28: at 2^28 a fast host item (about 37 M/s) gets 7-second
# slices and the rotation, which equalises slices, would give it 7 s a turn against a slow item's 600 s.
HOST_SLICE_CAP = 1 << 36


class Item:
    """One campaign line. kind 'exhaustive': encodings [0, 2^32), sliced; kind 'random':
    a count of cases from a seed, any number of slices, each its own seed."""

    def __init__(self, name: str, tool: str, kind: str, op: str, mode: Optional[str],
                 base_seed: int = 0, verdict_mode: str = "-", extra_cases: int = 0,
                 exact: bool = False, per_encoding: Optional[int] = None,
                 space: int = EXH, level: Optional[str] = None,
                 whole: Optional[Tuple[int, int]] = None):
        self.name = name
        self.tool = tool              # 'divsqrt' | 'clause5'
        self.kind = kind              # 'exhaustive' | 'random'
        self.op = op
        self.mode = mode              # argv's mode word, or None when the job takes none
        self.base_seed = base_seed    # the soak SCRIPTS' seed (hw/run-soak.sh, run-c5-soak.sh); not the driver's since 2026-10-20
        self.seed_index = None        # a random item's place in RANDOM_SEED_ORDER (sweep_items sets it)
        self.verdict_mode = verdict_mode      # the second word of the tool's verdict line
        self.extra_cases = extra_cases        # cases the tool adds to every slice
        self.exact = exact                    # cases == slice size (+ extra) is known
        # checks (compared or skipped) the tool makes for each encoding of a slice, for a job
        # whose verdict line says what it covered (the -all and -wide modes); None for the rest
        self.per_encoding = per_encoding
        # 'tile' or 'host' (OP_REACH): whether the job's work runs on the card's tile at all
        self.reach = OP_REACH[op]
        # an exhaustive item's indices are [0, space): 2^32 encodings for the fp32-operand items, the mode's index count for the
        # hard-case and class-level items (HARD_SPACE, CLASS_SPACE); `level` says which kind of claim a pass is
        # ("exhaustive", "hard", "class" - a class item is a claim at the class level, PLAUSIBLE, not a sweep - or "random");
        # `whole` is the (cases, skipped) of a mode over its whole space where the tool's own counting gives it
        self.space = space
        self.level = level or ("exhaustive" if kind == "exhaustive" else "random")
        self.whole = whole
        # the op's random operand stream depends on BATCH (CK's finding ii): its stream identity includes the batch
        self.layout_dependent = kind == "random" and op in LAYOUT_OPS

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

    def random_cases(self, count: int, batch: int) -> Optional[int]:
        """The cases a RANDOM slice of `count` prints where the tool's counting is known. Random scaleB (scaleb32, scaleb64)
        runs batches of n = min(remaining, BATCH) operands against its exponent list and takes n x len(list) off the count, so a
        slice's cases are the count rounded up by whole batches, and which batches depends on BATCH. Exactly what drv_scaleb does
        (host/tools/clause5_soak.c), held to the real tool's own lines in the suite (139,264 at 4096 and 278,528 at 16384 for
        100,000). Every other random op but two is a multiple of the count, plus a constant (RANDOM_CASES above: the count itself for
        most, 4 x count for cvtfrom32 and cvtfrom64, count + 8 for nextup64 and nextdown64), the same at any BATCH. None for cvtto32
        and cvtto64 (RANDOM_CASES_DRAWN: the draws set their cases), for an exhaustive item, and for a count or a batch below 1."""
        if self.kind != "random" or count < 1 or batch < 1:
            return None
        ln = SCALEB_LIST.get(self.op)
        if ln is None:
            per = RANDOM_CASES.get(self.op)
            return None if per is None else count * per[0] + per[1]
        total, left = 0, count
        while left > 0:
            n = min(left, batch)
            total += n * ln
            left = left - n * ln if left > n * ln else 0
        return total

    def cover_spec(self, lo: int, hi: int) -> Optional[Dict[str, int]]:
        """What the verdict line of a slice must say it covered (parse_soak's `cover`), for the
        jobs that say it; None for the others."""
        if self.kind == "exhaustive" and self.per_encoding is not None:
            return {"encodings": hi - lo, "per_encoding": self.per_encoding}
        return None

    def seed_for(self, n: int) -> int:
        """The n-th random slice's seed (0-based): (item index << 40) | (n << 1) | 1, distinct for every
        (item, n), odd (so the tools' `| 1` changes nothing), recorded. See SEED_SCHEME above."""
        if self.seed_index is None:
            raise ValueError(f"{self.name}: not a random item, it has no seeds")
        if not 0 <= n < SEED_N_LIMIT:
            raise ValueError(f"{self.name}: slice number {n} is outside [0, 2^39), the room the seed gives n")
        return (self.seed_index << 40) | (n << 1) | 1


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
    # The coverage wave's index-based items (2026-10-20), APPENDED so that no earlier item's place in the rotation moves, and
    # exhaustive, so they take no seeds. Parcel HC: the hard-case modes of the divsqrt soak - div32-hard and div64-hard under the
    # four attributes (rmm is refused by name for division), sqrt64-hard under five (rmm rides the RNE oracle) - a space
    # of their own, k = 4, 4 and 1, cases not a function of the slice (a skipped index skips all k slots), held to the whole-space
    # cases of `hard-count`. Parcel CL: the class-level modes of the clause-5 soak, in its order, each under the attributes of the
    # random mode of the operation: conv64to32 four, rint64 and cvtto64 five, cvtfrom64 and scaleb64 the modes the probes
    # allow (as their random modes' are). Every class mode but cvtto64-class makes exactly k cases an index and skips none.
    for op, modes in (("div32-hard", MODES4), ("div64-hard", MODES4), ("sqrt64-hard", MODES5)):
        space, k = HARD_SPACE[op]
        for mode in modes:
            items.append(Item(f"{op}-{mode}", "divsqrt", "exhaustive", op, mode, verdict_mode=mode, exact=False,
                              per_encoding=k, space=space, level="hard", whole=HARD_WHOLE[op]))
    for op, modes in (("conv64to32-class", MODES4), ("rint64-class", MODES5), ("cvtto64-class", MODES5),
                      ("cvtfrom64-class", cvtfrom_modes), ("scaleb64-class", scaleb_modes)):
        space, k = CLASS_SPACE[op]
        for mode in modes:
            whole = CVTTO64_CLASS_WHOLE[mode] if op == "cvtto64-class" else (k * space, 0)
            items.append(Item(f"{op}-{mode}", "clause5", "exhaustive", op, mode, verdict_mode=mode,
                              exact=op != "cvtto64-class", per_encoding=k, space=space, level="class", whole=whole))
    for it in items:
        if it.kind == "random":
            if it.name not in RANDOM_SEED_INDEX:
                raise ValueError(f"random item {it.name!r} has no seed index: append it to RANDOM_SEED_ORDER "
                                 f"(hw/card_stress_lib.py), never insert it, so that no item's seeds move")
            it.seed_index = RANDOM_SEED_INDEX[it.name]
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

# One writer at a time in this process. O_APPEND makes each write atomic on POSIX, but Windows' emulation of it
# seeks to the end and then writes, so two threads writing at once (the card's thread, the telemetry sampler, and
# since 2026-10-20 the host pool's workers) can both seek to one offset and one record overwrites the other: a
# dry run on Windows lost a leg record that way (the log said "pass", the file did not hold it).
_APPEND_LOCK = threading.Lock()


def append_record(path: str, rec: Dict[str, Any]) -> Dict[str, Any]:
    """One whole line in one write on an O_APPEND descriptor, so a reader sees a
    record or none; then fsync (a few records a minute at most). Returns the record AS WRITTEN: the
    caller's `rec` is copied and the copy is stamped (v, ts, epoch), so a caller that keeps what it
    appended and reads its time back from it (the status file's telemetry line did, and printed
    None, until 2026-10-22: KL-39) keeps this one."""
    rec = dict(rec)
    rec.setdefault("v", 1)
    with _APPEND_LOCK:
        now = time.time()               # stamped inside the lock: the file's order is the epochs' order
        rec.setdefault("ts", iso(now))
        rec.setdefault("epoch", round(now, 3))
        line = (json.dumps(rec, sort_keys=False, separators=(",", ":")) + "\n").encode("utf-8")
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
    return rec


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


def record_batch(sw: Dict[str, Any]) -> int:
    """The BATCH a sweep slice's tool ran at: what its record says (`sweep.batch`, written when the run used the chunked
    tools), else the default tools' 4096 - every record before 2026-10-21 and every default run's."""
    b = sw.get("batch")
    return b if isinstance(b, int) and not isinstance(b, bool) and b > 0 else DEFAULT_BATCH


# ---------------------------------------------------------------------------
# coverage by tree: the key the report and the resume share, and what a resume counts (parcel DR4, 2026-10-21)
# ---------------------------------------------------------------------------

def tree_key(kind: str, tr: Optional[Dict[str, Any]]) -> Tuple[str, Optional[str]]:
    """(key, unknown): the class a sweep slice of this reach falls in, given the `tree` of the run_start it ran after (None: it had none).
    THE definition of the key: the report's coverage by tree (card_stress_report.py) and the driver's --resume (Driver.count_by_class)
    both call it, so what the report puts in a class is what a resume counts. A TILE item is evidence about the RTL tree it ran on
    (tree.rtl, `git rev-parse HEAD:rtl`); a HOST item about the library's source and the compiler (tree.host_src, the tree hash of host/,
    and tree.cc, the compiler's first version line). A tree with uncommitted changes is a key of its own ('+modified'); a run that
    recorded none of it is kept apart by its commit ('unrecorded:<commit>'). `unknown` is None when every part of the key was recorded,
    and else names the part that was not: the report keeps such slices in a class of their own, and a resume never counts them (it does
    not guess that two runs lacking the same fact ran the same thing)."""
    tr = tr if isinstance(tr, dict) else {}

    def text(k: str) -> Optional[str]:
        v = tr.get(k)
        return v if isinstance(v, str) and v else None

    commit = text("commit")
    if kind == TILE:
        h = text("rtl")
        if not h:
            return "unrecorded:" + (commit or "?"), "no rtl/ tree recorded"
        return h + ("+modified" if tr.get("rtl_dirty") is True else ""), None
    if kind == HOST:
        h, cc = text("host_src"), text("cc")
        if not h:
            return "unrecorded:" + (commit or "?"), "no host/ tree recorded"
        return (h + ("+modified" if tr.get("host_src_dirty") is True else "") + "|" + (cc or "compiler not recorded"),
                None if cc else "compiler not recorded")
    return "none", "reach unknown"


def slice_reach(sw: Any) -> Optional[str]:
    """'tile' or 'host' for a sweep record's `sweep` object: what the record says (sweep.reach, written by the driver from OP_REACH),
    else what OP_REACH says of its op; None when neither does."""
    if not isinstance(sw, dict):
        return None
    return sw["reach"] if sw.get("reach") in (TILE, HOST) else reach_of(sw.get("op"))


GIT_HASH = re.compile(r"[0-9a-f]{40}")


def resolve_tree(tr: Optional[Dict[str, Any]], rev: Optional[Callable[[str, str], Optional[str]]] = None
                 ) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """(the tree, why): a run_start's `tree` with what the run did not record taken from its commit where it can be, and, by directory
    ('rtl', 'host'), what could not be known. A run before 2026-10-20 recorded its commit and no tree hashes; `rev(commit, rel)` is
    `git rev-parse COMMIT:REL` in the driver's checkout (None where git cannot say) and gives them, as a DERIVED fact. A tree is derived
    only from a commit this checkout holds and only when the run's checkout was recorded clean (`dirty` is false: a tree that was not
    clean is not the commit's). A run that DID record a tree whose commit is here is held to it: a recorded hash that is not git's for
    that commit is unknown, by name, and is not chosen between. With no `rev` nothing is derived (the resuming run's own tree)."""
    tr = tr if isinstance(tr, dict) else {}
    commit = tr["commit"] if isinstance(tr.get("commit"), str) and GIT_HASH.fullmatch(tr["commit"]) else None
    use: Dict[str, Any] = dict(tr)
    why: Dict[str, str] = {}
    for key, dirty_key, rel in (("rtl", "rtl_dirty", "rtl"), ("host_src", "host_src_dirty", "host")):
        have = tr[key] if isinstance(tr.get(key), str) and tr[key] else None
        got = rev(commit, rel) if (rev is not None and commit) else None
        if have is not None:
            if got is not None and got != have:
                use[key] = None
                why[rel] = f"it recorded {rel}/ tree {have[:12]}, which git does not give for its commit {commit[:12]} ({got[:12]})"
        elif got is None:
            why[rel] = "no tree recorded" + ("" if rev is None else f" and its commit {commit[:12]} is not in this checkout (or has no {rel}/)"
                                             if commit else " and no usable commit either")
        elif tr.get("dirty") is not False:
            why[rel] = (f"no tree recorded, and its checkout was not recorded clean (dirty: {tr.get('dirty')}), so its commit "
                        f"{commit[:12]} is not what ran")
        else:
            use[key], use[dirty_key] = got, False
    return use, why


def run_classes(tr: Optional[Dict[str, Any]], rev: Optional[Callable[[str, str], Optional[str]]] = None
                ) -> Dict[str, Tuple[str, Optional[str]]]:
    """{TILE: (key, unknown), HOST: (key, unknown)} for a run_start's `tree`: tree_key over resolve_tree's tree, the reason resolve_tree
    gives for a directory it could not know taking the place of tree_key's own."""
    use, why = resolve_tree(tr, rev)
    out: Dict[str, Tuple[str, Optional[str]]] = {}
    for kind, rel in ((TILE, "rtl"), (HOST, "host")):
        key, unknown = tree_key(kind, use)
        out[kind] = (key, why.get(rel) or unknown)
    return out


def count_slices(records: Iterable[Dict[str, Any]], now: Dict[str, Tuple[str, Optional[str]]],
                 rev: Optional[Callable[[str, str], Optional[str]]] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """What a RESUME counts (parcel DR4): of a metrics file's records, in order, the finished sweep slices (a leg of kind sweep with status pass
    or fail and an item: what sweep_coverage takes) whose class, under the last run_start before them, is known and is the one `now` gives
    their reach (`run_classes` of the resuming run's own tree). Every other slice stays in the file and in the report and is not counted:
    it is of another class, or of an unknown one (its own, or - when this run's own is unknown - every one). Returns (the slices counted,
    in order, and a tally): `slices` (all finished), `counted` and `other` ({reach: n}) and `unknown`, a list of {ts, commit, reach, why, n},
    one for each run_start, reach and reason."""
    counted: List[Dict[str, Any]] = []
    tally: Dict[str, Any] = {"slices": 0, "counted": {TILE: 0, HOST: 0}, "other": {TILE: 0, HOST: 0}, "unknown": []}
    cur: Optional[Dict[str, Tuple[str, Optional[str]]]] = None
    start: Dict[str, Any] = {}
    names: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    for r in records:
        typ = r.get("type")
        if typ == "run_start":
            tr = r.get("tree") if isinstance(r.get("tree"), dict) else None
            cur, start = run_classes(tr, rev), {"ts": r.get("ts"), "commit": (tr or {}).get("commit") if isinstance((tr or {}).get("commit"), str) else None}
            continue
        if typ != "leg" or r.get("kind") != "sweep" or r.get("status") not in ("pass", "fail"):
            continue
        sw = r.get("sweep") if isinstance(r.get("sweep"), dict) else {}
        if not sw.get("item"):
            continue
        tally["slices"] += 1
        reach = slice_reach(sw)
        if reach not in (TILE, HOST):
            key, unknown, want = "none", "reach unknown", ("", None)
        else:
            key, unknown = (cur if cur is not None else run_classes(None, rev))[reach]
            want = now.get(reach, ("", "this run's own class is not known"))
            if unknown is None and want[1] is not None:
                unknown = f"this run's own {reach} class is not known ({want[1]})"
        if unknown is None and key == want[0]:
            counted.append(r)
            tally["counted"][reach] += 1
        elif unknown is None:
            tally["other"][reach] += 1
        else:
            k = (start.get("ts"), start.get("commit"), reach, unknown)
            if k not in names:
                names[k] = {"ts": start.get("ts"), "commit": start.get("commit"), "reach": reach, "why": unknown, "n": 0}
                tally["unknown"].append(names[k])
            names[k]["n"] += 1
    return counted, tally


def stream_key(op: Optional[str], seed: int, batch: int):
    """What identifies a random stream: the state the tool starts from (seed | 1) and, for the ops whose operand stream
    depends on BATCH (LAYOUT_OPS), the batch as well. The rule of the pass size: a chunked cvtfrom slice at a state a default
    one used is NOT a repeat of it (the draws go to other source types) and so does not collide with it; every other item's
    operand sequence is the same at any BATCH, so a chunked slice at a state a default slice used IS a repeat, and does."""
    return (seed | 1, batch) if op in LAYOUT_OPS else seed | 1


def seed_states(records: Iterable[Dict[str, Any]]) -> Dict[Any, Tuple[str, int]]:
    """{the stream a slice's tool started (stream_key): (item, n)} for every random slice the records name, whatever
    its status: a slice that timed out drew from its seed all the same. The key is the state (seed | 1), or (state, batch) for
    a LAYOUT_OPS item. Under the schedule before 2026-10-20 two items share a state on half the n, and the later record wins
    here; the new schedule never shares one."""
    out: Dict[Any, Tuple[str, int]] = {}
    for r in records:
        if r.get("type") != "leg" or r.get("kind") != "sweep":
            continue
        sw = r.get("sweep") or {}
        if isinstance(sw.get("item"), str) and isinstance(sw.get("seed"), int) and isinstance(sw.get("seed_n"), int):
            out[stream_key(sw.get("op"), sw["seed"], record_batch(sw))] = (sw["item"], sw["seed_n"])
    return out


class EarlierRunError(ValueError):
    """A directory named as an earlier run cannot be used as one; the message names it."""


def earlier_runs(dirs: Iterable[str], batch: Optional[int] = None
                 ) -> Tuple[Dict[str, int], Dict[Any, Tuple[str, int]], List[Dict[str, Any]]]:
    """(the first slice number n each random item may use, the streams those runs started (stream_key), a note a directory):
    for each directory NAMED (never found by looking), its metrics.jsonl's highest seed_n of a completed slice
    (pass or fail) of an item, plus one - a slice that did not complete is served again by the run that left it, and
    is not a draw a later run must avoid. Refused by name: a name that is not a directory, a directory with no
    metrics.jsonl, and a file with lines that do not parse (they might be the slices with the highest n, and a floor
    that is too low repeats draws without a word). A torn last line, the mark of a killed run, is allowed and noted.
    batch: the BATCH the run that asks will use. A LAYOUT_OPS item (cvtfrom32, cvtfrom64: its operand stream depends on BATCH)
    is floored only by the earlier slices that ran at that batch, since another batch's draws are not these; every other item
    is floored by every earlier slice, whatever its batch, because its draws are the same at any (docs/CARDDAY.md, "The soak at
    a larger pass size"). None: every slice counts for every item, as before the chunked tools."""
    floor: Dict[str, int] = {}
    states: Dict[Any, Tuple[str, int]] = {}
    notes: List[Dict[str, Any]] = []
    for d in dirs:
        path = os.path.join(d, "metrics.jsonl")
        if not os.path.isdir(d):
            raise EarlierRunError(f"--earlier-runs {d}: not a directory")
        if not os.path.isfile(path):
            raise EarlierRunError(f"--earlier-runs {d}: no metrics.jsonl in it, so it cannot say which seeds it used "
                                  f"(name a run's output directory, the one that holds metrics.jsonl)")
        recs, partial, bad = read_records(path)
        if bad:
            raise EarlierRunError(f"--earlier-runs {d}: metrics.jsonl lines {bad[:10]} do not parse; a run whose "
                                  f"record is damaged cannot say which seeds it used")
        seeds = sweep_coverage(recs)[3]
        if batch is not None:
            # a layout-dependent item's highest n is taken over the slices of this batch alone
            swp = [r["sweep"] for r in recs if r.get("type") == "leg" and r.get("kind") == "sweep"
                   and isinstance(r.get("sweep"), dict) and r["sweep"].get("op") in LAYOUT_OPS
                   and isinstance(r["sweep"].get("item"), str)]
            layout_items = {sw["item"] for sw in swp}
            seeds = {k: v for k, v in seeds.items() if k not in layout_items}
            for r in recs:
                sw = r.get("sweep") if r.get("type") == "leg" and r.get("kind") == "sweep" else None
                if (isinstance(sw, dict) and sw.get("item") in layout_items and r.get("status") in ("pass", "fail")
                        and "seed_n" in sw and record_batch(sw) == batch):
                    seeds[sw["item"]] = max(seeds.get(sw["item"], -1), int(sw["seed_n"]))
        for item, n in seeds.items():
            floor[item] = max(floor.get(item, 0), n + 1)
        states.update(seed_states(recs))
        notes.append({"dir": d, "records": len(recs), "items": len(seeds), "torn_tail": bool(partial)})
    return floor, states, notes


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


# A reading that means "no reading" (KL-32, 2026-10-22). The U50's FPGA HBM temperature, in xbutil's thermal report
# (`thermal.devices[0].thermals.FPGA HBM.temp_C`), reads 0 in most samples: 670 of the 865 of the 2026-10-19 long run, in runs of
# 7 to 45 samples at a time between runs of readings from 27 to 35 (MEASURED in that run's metrics.jsonl). A stack of HBM at 0 degrees
# on a powered card is not a temperature, so a 0 here is taken as the sensor giving none (BELIEVED: the cause is not known, and the
# reading is not documented); it is left out of the report's range for the label and the status file says so beside it. Only this
# label: the rails that read a flat 0 in EVERY sample of a run (19 of the 40 labels that run's report showed) are not a mixture of
# readings and none, and stay in as they were.
def is_hbm_temperature(label: Any) -> bool:
    """The label of an HBM temperature in the thermal report, as parse_telemetry keys it: `thermal.` + the sensor's path, with
    `HBM` and `temp` in it (not the HBM rail's voltage and current, which are `electrical.`)."""
    return isinstance(label, str) and label.startswith("thermal.") and "HBM" in label and "temp" in label.lower()


def no_reading(label: Any, value: Any) -> bool:
    """True for a reading that is the sensor's 'none': an HBM temperature of exactly 0."""
    return (is_hbm_temperature(label) and isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0)


TELEMETRY_SHOWN = 12        # values the status file's telemetry line names; the rest are counted


def telemetry_line(rec: Dict[str, Any]) -> str:
    """The status file's telemetry line for a sample's record (KL-39, 2026-10-22; Logan reads it each morning). It carried None for the
    time and the first six values of the record, which were the first report's rails; it now has the sample's own time (the record is the
    one append_record stamped), what took it (`when`, the image), and up to TELEMETRY_SHOWN values - the thermal report's first (the
    temperatures), then the power the card draws, then the rest in the record's order - with the count of those left out, and an HBM
    temperature of 0 marked as no reading. A sample with no values says so and why, as before."""
    vals = rec.get("values") if isinstance(rec.get("values"), dict) else {}
    ts = rec.get("ts") if isinstance(rec.get("ts"), str) and rec.get("ts") else "time not recorded"
    how = ", ".join(str(x) for x in (rec.get("when"), rec.get("image")) if isinstance(x, str) and x)
    head = f"telemetry  {ts}{' (' + how + ')' if how else ''}: "
    if not vals:
        err = rec.get("error")
        return head + "no values parsed" + (f" ({err})" if err else "")

    def rank(kv: Tuple[int, Tuple[str, Any]]) -> Tuple[int, int]:
        label = kv[1][0]
        return (0 if label.startswith("thermal.") else 1 if "power_consumption" in label else 2, kv[0])

    chosen = [kv for _i, kv in sorted(enumerate(vals.items()), key=rank)][:TELEMETRY_SHOWN]
    parts = [f"{k}={x}" + (" (no reading)" if no_reading(k, x) else "") for k, x in chosen]
    left = len(vals) - len(chosen)
    return head + "; ".join(parts) + (f"; {left} more value(s) in metrics.jsonl" if left else "")


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
# an image's manifest, held to the image and to the checkout (KL-42, 2026-10-22)
# ---------------------------------------------------------------------------
# Coverage is filed under the RTL tree of the checkout the driver runs from (tree.rtl = `git rev-parse HEAD:rtl`), which is the tree
# the images were built from only if the operator ran from the checkout they were built from; the driver never read the manifest
# hw/rebuild-2022.sh writes beside each xclbin, so nothing said when that was wrong. judge_manifest reads it: what the manifest says
# (its sha256, its commit, whether rtl/ was that commit's) is held to the image's own SHA-256 and to the checkout's rtl tree, and
# the verdict is a state, recorded in run_start beside the image's SHA-256. The key coverage is filed by does not change.
#
#   ok               the manifest is the image's, its commit is in this checkout, rtl/ was that commit's when the image was built, and the
#                    commit's rtl tree is this checkout's: per-tree coverage is true of this image
#   dry_run          no manifest, in a dry run: its stand-in images are built from nothing. Neutral, and not looked for again
#   missing          NO manifest beside the image: FLAGGED, not refused - nothing is wrong that the driver can see, only unchecked, and
#                    a night's run is not lost to a file left behind in a copy (the image's SHA-256 is still held to SHA256SUMS)
#   commit_unknown   the manifest names no whole commit, or one this checkout does not hold (or which has no rtl/): FLAGGED for the
#                    same reason - a shallow clone cannot show a difference, and a difference it cannot show is not one
#   unverified       FLAGGED: the manifest does not say whether rtl/ was its commit's (no bitstream_sources: and no tree: line), or
#                    this checkout's own rtl tree cannot be read
#   sha256_mismatch  REFUSED: the manifest has no sha256 of 64 hex digits, or another image's: it is not this image's manifest
#   rtl_modified     REFUSED: the manifest says rtl/ was not its commit's when it was built (bitstream_sources: MODIFIED, naming a file
#                    under rtl/; or a DIRTY tree with no scoped line): the image is of no tree any checkout has
#   rtl_differs      REFUSED: the commit's rtl tree is not this checkout's: every tile slice would be filed under a tree the image is not
# A refusal is a certain wrong answer; a flag is an absence. hw/rebuild-2022.sh's `bitstream_sources:` is scoped to rtl/ and hw/, so
# MODIFIED naming only hw/ files leaves the rtl tree the commit's: that is judged on the trees (state ok, the files said in `why`).
MANIFEST_SUFFIX = ".manifest.txt"
MANIFEST_REFUSED = ("sha256_mismatch", "rtl_modified", "rtl_differs")
MANIFEST_FLAGGED = ("missing", "commit_unknown", "unverified")
SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_MANIFEST_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):[ \t]*(.*?)[ \t]*$")
MANIFEST_SOURCES_MAX = 300           # characters of `bitstream_sources:` kept in a record (a MODIFIED line lists files)


def manifest_path(image_path: str) -> str:
    """The manifest beside an image: `<name>.manifest.txt` for `<name>.xclbin` (hw/rebuild-2022.sh writes cft_<target>.manifest.txt
    beside cft_<target>.xclbin, and a staged pair keeps the pair of names). Its `artifact:` line names the build's own file name
    (cft_hw.xclbin), not the staged one, so the name is not what ties the two: the `sha256:` line is."""
    base, ext = os.path.splitext(image_path)
    return (base if ext.lower() == ".xclbin" else image_path) + MANIFEST_SUFFIX


def parse_manifest(text: str) -> Dict[str, str]:
    """The top-level `key: value` lines of a manifest, the first of a key winning. An indented line (a `hdlparam:` under `generics:`)
    belongs to the key above it and is not read."""
    out: Dict[str, str] = {}
    for ln in text.splitlines():
        m = _MANIFEST_KEY.match(ln)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2)
    return out


def judge_manifest(text: Optional[str], image_sha: str, checkout_rtl: Optional[str],
                   rtl_of: Callable[[str], Optional[str]], dry: bool = False) -> Dict[str, Any]:
    """The verdict on one image's manifest (the states are above). text: the manifest's text, None when there is none; image_sha: the
    image's own SHA-256; checkout_rtl: this checkout's `HEAD:rtl` tree (None where git cannot say); rtl_of(commit): the rtl tree of a
    commit in this checkout, None where it does not hold the commit. Returns the dict run_start records as the image's `manifest` (the
    caller adds `file`): state, refuse (a refusal), why (one sentence naming the state), and what the manifest said - sha256, commit,
    tree, sources - and rtl, the commit's rtl tree where it was found. Never raises on a manifest's content."""
    r: Dict[str, Any] = {"state": "", "refuse": False, "why": "", "sha256": None, "commit": None, "rtl": None,
                         "tree": None, "sources": None}

    def done(state: str, why: str) -> Dict[str, Any]:
        r["state"], r["why"], r["refuse"] = state, why, state in MANIFEST_REFUSED
        return r

    if text is None:
        return (done("dry_run", "a dry run's stand-in image is built from no commit, so it has no manifest")
                if dry else done("missing", "no manifest beside the image, so the tree it was built from is not checked: per-tree coverage "
                                            "is true of this image only if this checkout's rtl/ is the one it was built from"))
    f = parse_manifest(text)
    sha = (f.get("sha256") or "").lower()
    r["sha256"] = sha or None
    r["commit"] = f.get("commit") or None
    r["tree"] = f.get("tree") or None
    src = f.get("bitstream_sources") or ""
    r["sources"] = src[:MANIFEST_SOURCES_MAX] or None
    if not SHA256_HEX.fullmatch(sha):
        return done("sha256_mismatch", f"its manifest has no sha256 of 64 hex digits (it says {sha[:20]!r}), so it cannot be shown to be this image's")
    if sha != image_sha:
        return done("sha256_mismatch", f"its manifest says sha256 {sha[:16]}..., the image hashes to {image_sha[:16]}...: "
                                       f"it is another image's manifest")
    # did the build see this commit's rtl/? hw/rebuild-2022.sh's bitstream_sources is scoped to rtl/ and hw/; an older manifest has only
    # the whole tree's flag. True: yes; False: no; None: the manifest does not say.
    hw_note = ""
    same: Optional[bool] = None
    if src.startswith("rtl/ and hw/ identical to"):
        same = True
    elif src.startswith("MODIFIED"):
        files = src.rsplit(":", 1)[1].split() if ":" in src else []
        under_rtl = [x for x in files if x.startswith("rtl/")]
        same = bool(files) and not under_rtl
        if same:
            hw_note = f" (its hw/ differed from the commit's in {len(files)} file(s), which the rtl tree does not see)"
        else:
            return done("rtl_modified", "its manifest says rtl/ was modified when the image was built (" + (src[:160] or "no detail")
                        + "): the image is of no tree any checkout has")
    elif not src:
        tr = (f.get("tree") or "").strip().lower()
        if tr == "clean":
            same = True                          # a manifest from before the scoped line: a clean whole tree has a clean rtl/
        elif tr.startswith("dirty"):
            return done("rtl_modified", "its manifest says the tree was DIRTY and has no bitstream_sources: line to say rtl/ was not "
                                        "what changed: the image is of no tree any checkout has")
    if same is None:
        return done("unverified", "its manifest does not say whether rtl/ was its commit's (no bitstream_sources: line, and a tree: "
                                  "line that is neither clean nor DIRTY), so its commit's rtl tree is not known to be the image's")
    commit = r["commit"] or ""
    if not GIT_HASH.fullmatch(commit):
        return done("commit_unknown", f"its manifest names no whole commit (commit: {commit[:20]!r}), so its rtl tree cannot be read")
    rtl = rtl_of(commit)
    if rtl is None:
        return done("commit_unknown", f"its manifest names commit {commit[:12]}, which this checkout does not hold (or which has no rtl/): "
                                      f"a shallow clone cannot show whether rtl/ differs")
    r["rtl"] = rtl
    if not checkout_rtl:
        return done("unverified", "this checkout's own rtl tree cannot be read (git), so it cannot be compared with the image's")
    if rtl != checkout_rtl:
        return done("rtl_differs", f"the image was built at commit {commit[:12]} whose rtl tree is {rtl[:12]}; this checkout's is "
                                   f"{checkout_rtl[:12]}: tile slices would be filed under a tree the image is not")
    return done("ok", f"built at commit {commit[:12]}, whose rtl tree {rtl[:12]} is this checkout's" + hw_note)


def manifest_step(name: str, mf: Dict[str, Any]) -> Tuple[bool, str]:
    """(ok, detail) of an image's `manifest` build step: a refusal is not ok; a flag is ok and says it was NOT CHECKED, by state."""
    st = mf.get("state") or "?"
    if mf.get("refuse"):
        return False, f"{st}: {mf.get('why')}. REFUSED: the run does not start (the manifest is {mf.get('file')})"
    if st in MANIFEST_FLAGGED:
        return True, f"{st}: NOT CHECKED, flagged and the run goes on: {mf.get('why')}"
    return True, f"{st}: {mf.get('why')}"


def manifest_brief(mf: Dict[str, Any]) -> str:
    """One image's manifest in a few words, for the status file and the report's header."""
    st = mf.get("state") or "?"
    if st == "ok":
        return f"built at {str(mf.get('commit'))[:12]}, rtl {str(mf.get('rtl'))[:12]} (this checkout's)"
    if st == "dry_run":
        return "no manifest (dry run)"
    if st in MANIFEST_FLAGGED:
        return f"NOT CHECKED ({st})"
    return f"REFUSED ({st})"


# ---------------------------------------------------------------------------
# vectors/out, which the selftest leg reads (KL-44, 2026-10-22)
# ---------------------------------------------------------------------------
_VECTOR_LINE = re.compile(r"^([0-9a-fA-F]{64})[ \t]+\*?(.+?)[ \t]*$")


def file_sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def vectors_problem(root: str) -> Optional[str]:
    """None when `vectors/out` is there and every file `vectors/SHA256SUMS` lists holds to it (what `cd vectors && sha256sum -c --quiet
    SHA256SUMS` says); else the refusal's text, which begins with its name and says `make vectors`. The selftest leg runs
    `cft-selftest vectors/out IMAGE` every third visit of each image; on a clean clone vectors/out is not there (it is generated, and
    untracked), and until 2026-10-22 the driver neither checked nor made it, so that leg failed at every one of those visits (KL-44)."""
    vec = os.path.join(root, "vectors")
    fix = "run `make vectors` (docs/CARDDAY.md)"
    if not os.path.isdir(os.path.join(vec, "out")):
        return (f"vectors_out_missing: vectors/out is not there, and the selftest leg (cft-selftest vectors/out IMAGE) would fail at "
                f"every third visit of each image; {fix}")
    try:
        with open(os.path.join(vec, "SHA256SUMS"), "r", encoding="utf-8", errors="replace") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    except OSError as e:
        return f"vectors_out_unheld: vectors/SHA256SUMS cannot be read ({e}), so vectors/out cannot be held to it; it is a tracked file"
    entries: List[Tuple[str, str]] = []
    for ln in lines:
        m = _VECTOR_LINE.match(ln)
        if not m:
            return f"vectors_out_unheld: vectors/SHA256SUMS has a line that is not '<sha256>  <path>': {ln[:60]!r}"
        entries.append((m.group(1).lower(), m.group(2)))
    if not entries:
        return "vectors_out_unheld: vectors/SHA256SUMS lists no file, so vectors/out is held to nothing"
    bad: List[str] = []
    top = os.path.normpath(vec) + os.sep
    for want, rel in entries:
        p = os.path.normpath(os.path.join(vec, rel))
        if not p.startswith(top):
            bad.append(f"{rel} (outside vectors/)")
            continue
        try:
            got = file_sha256(p)
        except OSError:
            bad.append(f"{rel} (missing)")
            continue
        if got != want:
            bad.append(f"{rel} (differs)")
    if bad:
        return (f"vectors_out_mismatch: {len(bad)} of the {len(entries)} files vectors/SHA256SUMS lists are missing or differ in "
                f"vectors/out (first: {', '.join(bad[:3])}); {fix}")
    return None


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
