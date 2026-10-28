#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Test of the clause-5 soak's wide modes (host/tools/clause5_soak.c built with `make clause5-soak MPFR=1`, parcel HXb): the class
modes rint128-class, rint256-class, scaleb128-class, scaleb256-class, conv128to64-class, conv256to128-class, cvtto128-class,
cvtto256-class, cvtfrom128-class and cvtfrom256-class against MPFR through mpfr-check's own clause-5 rules (host/tools/mpfr_c5.h),
and rint128-f32 and rint256-f32 against the CPU's fp32 rint, on the software backend. POSIX with make, a C compiler and MPFR and
GMP to link (the system's: WSL cft2204's MPFR 4.1.0 and GMP 6.2.1); skipped by name elsewhere. The model is hw/test_c5_class.py,
and hw/test_c5_exhaustive.py's Tool and tree helpers are used.

    python3 hw/test_c5_wide.py [--only GROUP,...] [--baseline-tree DIR] [--thorough] [--keep]

It builds the tool in a scratch copy of host/ (make clause5-soak MPFR=1, XRT=0), and the default tool in a second copy, and runs,
niced, one process at a time:
  build      the MPFR=1 build's one warning line is the known FENV_ACCESS pragma's, and a CONTROL: the same source without its
             `#pragma GCC diagnostic` lines warns of mpfr_ieee.h's unused ieee_oracle, so the pragma takes a real warning
             away; `dump <word> size` of the twelve words is the Python reference's (2^32 for the two -f32 words); the default
             build refuses every wide word, run or dump, exit 2 (the usage text), and has no MPFR in it
  agree      the C tool's `dump` of EVERY index of nine of the ten wide class spaces equals python/c5_class_enum.py's line for
             line; of conv256to128-class (63,208,320 indices) every index of 768 of its 32,921 positions (the first and last 256
             structural ones, the 39 witnesses and 217 drawn from a fixed seed); rint{128,256}-f32's dump equals
             python/hardcases.py's widen_bits over the fp32 encodings' special regions and a fixed-seed sample
  whole      each class mode but conv256to128-class over its WHOLE index space under all five attributes: no mismatch, E the
             indices, cases = k x E, S = 0, and the driver's parse_soak accepts it under its cover rule; conv256to128-class over
             32 slices of 65,536 under all five (whole under all five with --thorough, about 7 minutes); rint{128,256}-f32
             over 2^22 encodings around 0.5, 1, 2^23 and their negatives under all five
  spread     every mode and attribute over slices of odd alignment and size across its space, each held to the same rules
  refuse     a range that is empty, reversed, past the space, negative or not a number refused by name, exit 2, nothing run;
             a missing attribute and one that does not exist; a dump past the space
  sabotage   CFT_SOAK_SABOTAGE=1 fails every mode under every attribute, naming operands its slice enumerates (or the benign
             operand in front of one in a tile mode), and the same slice passes without it
  plants     one defect for each class of check, red at the check written for it: a class selector wrong in the C builder (the
             dump agreement names the index); the shared rule given the wrong attribute (mpfr_c5.h: rtz as floor); a fault
             in one fp128 lane of cft_rint, caught by the default build and NOT by one that does not rotate; a sticky tree
             without the lowest dropped bit in the library (the wide conversions and scaleB's strips catch it); the FCVT
             table's u32 maximum off by one in the oracle (the lanes a target cannot hold ARE compared); a widening that
             drops a significand's last bit (the dump agreement and rint128-f32 catch it); a wide mode counting one index
             short (parse_soak's cover rule refuses it)
  unchanged  (with --baseline-tree DIR, a directory holding the baseline's host/) the MPFR=1 tool's OLDER modes print the same
             bytes and exit the same as the baseline's default tool, over 55 invocations

Prints one line a group and a last line "c5-wide test: N checks, F failed, S skipped".
"""
from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "python"))
import card_stress_lib as L  # noqa: E402
import c5_class_enum as C5  # noqa: E402
import hardcases as HC  # noqa: E402
import test_c5_exhaustive as X  # noqa: E402  (Tool, copy_tree, patch_once, build, NICE)

CHECKS = 0
FAILS: list = []
SKIPS: list = []
NICE = X.NICE
ENUMS = C5.enums_wide()                         # the ten class spaces, by job word
CLASS_JOBS = list(ENUMS)
F32_JOBS = ("rint128-f32", "rint256-f32")
ALL_JOBS = CLASS_JOBS + list(F32_JOBS)
ATTRS = ("rne", "rtz", "rdn", "rup", "rmm")
BIG = "conv256to128-class"                      # 63,208,320 indices: sampled, not whole
EXH = 1 << 32
BENIGN = {"rint128-class": {(16383 << 112)}, "scaleb128-class": {0}}     # 1.0 and +0 in front of a case in fp128's lane 1
PRAGMA = ('#pragma GCC diagnostic push\n', '#pragma GCC diagnostic ignored "-Wunused-function"\n',
          '#pragma GCC diagnostic pop\n')


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}"[:420])
    return bool(ok)


def skip(name: str, why: str) -> None:
    SKIPS.append(f"{name}: {why}")
    print(f"  SKIP  {name} - {why}")


def k_of(job: str) -> int:
    return 1 if job in F32_JOBS else ENUMS[job].k


def size_of(job: str) -> int:
    return EXH if job in F32_JOBS else ENUMS[job].N


def build_mpfr(tree: str, label: str, cflags: str = ""):
    """make clause5-soak MPFR=1 in tree/host (CFLAGS=cflags when given): (the Tool or None, make's log)."""
    env = dict(os.environ)
    if cflags:
        env["CFLAGS"] = cflags
    p = subprocess.run(NICE + ["make", "-C", os.path.join(tree, "host"), "-j4", "clause5-soak", "MPFR=1"], capture_output=True,
                       text=True, timeout=900, env=env)
    log = p.stdout + p.stderr
    exe = os.path.join(tree, "host", "clause5-soak")
    if p.returncode != 0 or not os.path.exists(exe):
        print(f"  build of {label} failed (rc {p.returncode}): {log[-600:]}")
        return None, log
    return X.Tool(exe), log


def planted(built_tree: str, work: str, name: str, edits: list, cflags: str = ""):
    """A copy of the built tree with each (file under host/, old, new) edit applied exactly once, built with MPFR=1: its Tool."""
    tree = X.copy_tree(built_tree, os.path.join(work, "plant-" + name))
    for rel, old, new in edits:
        X.patch_once(os.path.join(tree, "host", *rel.split("/")), old, new, name)
    tool, _log = build_mpfr(tree, name, cflags)
    return tool


def judge(job, attr, lo, hi, rc, out, m):
    """What every passing slice must meet: exit 0, no mismatch, the verdict for this job and attribute, E the slice's indices,
    cases = k x E and nothing skipped (every wide mode compares every case), and the driver's own parse_soak accepting it under
    its cover rule (the exact count included)."""
    if m is None:
        return False, f"no verdict line: rc {rc}: {out[-200:]}"
    k = k_of(job)
    cases, vm, fm, enc, skp = int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
    if (m.group(1), m.group(2)) != (job, attr):
        return False, f"the verdict is for {m.group(1)} {m.group(2)}"
    if rc != 0 or vm or fm:
        return False, f"rc {rc}, {vm} value and {fm} flag mismatches: {out[:300]}"
    if enc != hi - lo or cases != k * enc or skp != 0:
        return False, f"{cases} cases, {enc} encodings, {skp} skipped for a slice of {hi - lo} at k = {k}"
    try:
        v = L.parse_soak(out, rc, job, attr, None, k * (hi - lo), {"encodings": hi - lo, "per_encoding": k})
    except L.VerdictError as ex:
        return False, f"refused by parse_soak: {ex}"
    if not v.ok:
        return False, "parse_soak says it failed"
    return True, ""


def dump_lines(tool, job, lo, hi):
    rc, out, err = tool.raw("dump", job, lo, hi, timeout=900)
    lines = out.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return rc, lines


def first_diff(tool, job, lo, hi, ref):
    """The first index of [lo, hi) whose C dump line differs from ref(i), or None; a count or exit status gone wrong is named."""
    rc, lines = dump_lines(tool, job, lo, hi)
    if rc != 0 or len(lines) != hi - lo:
        return f"rc {rc}, {len(lines)} lines for {hi - lo} indices"
    for j, ln in enumerate(lines):
        if ln != ref(lo + j):
            return f"index {lo + j}: C {ln!r}, Python {ref(lo + j)!r}"
    return None


def f32_ref(width):
    return lambda i: "%d 0x%0*x" % (i, width // 4, HC.widen_bits(i, 32, width))


# ---------------------------------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------------------------------

def group_build(tool, log: str, tree: str, work: str, deftool) -> None:
    warns = [ln for ln in log.splitlines() if "warning:" in ln]
    check("build: the MPFR=1 build prints one warning line, the FENV_ACCESS pragma's that the driver's table knows "
          "(hw/card_stress.py KNOWN_WARNINGS)", len(warns) == 1 and re.search(
              r"tools/clause5_soak\.c:\d+: warning: ignoring .#pragma STDC FENV_ACCESS. \[-Wunknown-pragmas\]", warns[0]) is not None,
          f"{warns}")
    ctl = X.copy_tree(tree, os.path.join(work, "nopragma"))
    for line in PRAGMA:
        X.patch_once(os.path.join(ctl, "host", "tools", "clause5_soak.c"), line, "", "no pragma")
    _t, clog = build_mpfr(ctl, "the build without the diagnostic pragma")
    cw = [ln for ln in clog.splitlines() if "warning:" in ln]
    check("build: CONTROL - the same source without its `#pragma GCC diagnostic` lines warns of mpfr_ieee.h's unused ieee_oracle "
          "(-Wunused-function), so the pragma takes a real warning away", any("ieee_oracle" in w and "unused-function" in w for w in cw),
          f"{cw}")
    for job in ALL_JOBS:
        rc, out, err = tool.raw("dump", job, "size")
        check(f"build: `dump {job} size` is the reference's {size_of(job)}", rc == 0 and out.strip() == str(size_of(job)),
              f"rc {rc} {out.strip()!r}")
    bad = []
    for job in ALL_JOBS:
        rc, out, err = deftool.raw(job, 0, 1, "rne")
        rcd, outd, errd = deftool.raw("dump", job, "size")
        if not (rc == 2 and " cases," not in out and "usage:" in err and rcd == 2 and outd == "" and "usage:" in errd):
            bad.append((job, rc, rcd))
    check("build: the default build (no MPFR) refuses each of the twelve wide words, as a run and as a dump: exit 2, the usage "
          "text, nothing run", not bad, f"{bad}")
    rc, out, err = deftool.raw("nosuchjob", 0, 1, "rne")
    _r2, _o2, err2 = tool.raw("nosuchjob", 0, 1, "rne")
    check("build: the default build's usage has no wide line and the MPFR=1 build's names the MPFR it was built with",
          "rint128-class" not in err and "(the wide modes, built with MPFR " in err2, err2[-200:])


def group_agree(tool) -> None:
    t0 = time.time()
    total = 0
    for job, e in ENUMS.items():
        if job == BIG:
            continue
        first = None
        for lo in range(0, e.N, 250000):
            hi = min(e.N, lo + 250000)
            first = first_diff(tool, job, lo, hi, e.dump_line)
            if first:
                break
        total += e.N
        check(f"agree: the C tool's dump of EVERY index of {job} ({e.N:,}) equals python/c5_class_enum.py's, line for line",
              first is None, first or "")
    e = ENUMS[BIG]
    per = 2 * C5.NCLS * (4 + e.W)
    npos, nstruct = e.npos, e.nstruct
    rnd = random.Random(20261027)
    picks = sorted(set(range(256)) | set(range(nstruct - 256, nstruct)) | set(range(nstruct, npos)))
    others = [p for p in range(256, nstruct - 256)]
    picks = sorted(set(picks) | set(rnd.sample(others, 217)))
    runs, start = [], picks[0]
    for a, b in zip(picks, picks[1:] + [None]):
        if b != a + 1:
            runs.append((start, a + 1))
            start = b
    bad = None
    for pa, pb in runs:
        bad = first_diff(tool, BIG, pa * per, pb * per, e.dump_line)
        if bad:
            break
    total += len(picks) * per
    check(f"agree: the C tool's dump of {BIG} equals the reference's at every index of {len(picks)} of its {npos:,} positions "
          f"(the first and last 256 structural ones, the {npos - nstruct} witnesses and 217 drawn; {len(picks) * per:,} lines)",
          len(picks) == 768 and bad is None, bad or f"{len(picks)} positions")
    regions = [(0, 0x1000), (0x007FF000, 0x00801000), (0x3F7FF000, 0x3F801000), (0x4AFFF000, 0x4B001000),
               (0x7F7FF000, 0x7F801000), (0x7FBFF000, 0x7FC01000), (0x7FFFF000, 0x80001000), (0x807FF000, 0x80801000),
               (0xBF7FF000, 0xBF801000), (0xFF7FF000, 0xFF801000), (0xFFBFF000, 0xFFC01000), (0xFFFFF000, EXH)]
    for _ in range(16):
        lo = rnd.randrange(0, EXH - 4096)
        regions.append((lo, lo + 4096))
    for job, width in (("rint128-f32", 128), ("rint256-f32", 256)):
        bad = None
        for lo, hi in regions:
            bad = first_diff(tool, job, lo, hi, f32_ref(width))
            if bad:
                break
        total += sum(hi - lo for lo, hi in regions)
        check(f"agree: {job}'s dump, the fp32 encodings widened, equals python/hardcases.py's widen_bits over {len(regions)} regions "
              f"(zeros, subnormals, the normal edges, infinities, both NaN kinds, both signs, and 16 drawn)", bad is None, bad or "")
    print(f"      ({total:,} dump lines compared in {time.time() - t0:.0f} s)")


def run_and_judge(tool, job, attr, lo, hi, label):
    rc, out, m = tool.run(job, lo, hi, attr, timeout=3600)
    ok, why = judge(job, attr, lo, hi, rc, out, m)
    return ok, why, out


def group_whole(tool, thorough: bool) -> None:
    t0 = time.time()
    for job in CLASS_JOBS:
        if job == BIG:
            continue
        e = ENUMS[job]
        for attr in ATTRS:
            ok, why, _out = run_and_judge(tool, job, attr, 0, e.N, "whole")
            check(f"whole: {job} {attr} over its whole index space ({e.N:,}, k = {e.k}): passes, {e.k * e.N:,} cases, none skipped",
                  ok, why)
    print(f"      (nine whole spaces under five attributes in {time.time() - t0:.0f} s)")
    t1 = time.time()
    e = ENUMS[BIG]
    starts = [0, e.N - 65536] + [((e.N - 65536) * j) // 31 for j in range(1, 31)]
    bad = []
    for attr in ATTRS:
        for lo in starts:
            ok, why, _out = run_and_judge(tool, BIG, attr, lo, lo + 65536, "slices")
            if not ok:
                bad.append((attr, lo, why))
    check(f"whole: {BIG} over 32 slices of 65,536 spread across its {e.N:,} indices, under all five attributes: every one passes",
          not bad, f"{bad[:2]}")
    if thorough:
        for attr in ATTRS:
            ok, why, _out = run_and_judge(tool, BIG, attr, 0, e.N, "whole")
            check(f"whole: {BIG} {attr} over its whole index space ({e.N:,}): passes, {e.N:,} cases, none skipped", ok, why)
    t2 = time.time()
    regions = [(0x3EFF0000, 0x3F100000), (0x4AFF0000, 0x4B100000), (0xBEFF0000, 0xBF100000), (0xCAFF0000, 0xCB100000)]
    for job in F32_JOBS:
        for attr in ATTRS:
            bad = [(lo, why) for lo, hi in regions for ok, why, _o in [run_and_judge(tool, job, attr, lo, hi, "f32")] if not ok]
            check(f"whole: {job} {attr} over 2^22 encodings around 0.5, 1, 2^23 and their negatives: every one equal to the fp32 "
                  f"rint widened, bits and flags", not bad, f"{bad[:2]}")
    print(f"      ({BIG}'s slices in {t2 - t1:.0f} s; the -f32 modes in {time.time() - t2:.0f} s)")


def spread_slices(job: str, n: int):
    size = size_of(job)
    rnd = random.Random(20261027 + sum(map(ord, job)))
    cap = 600 if job in ("cvtto256-class", "cvtto128-class") else (100000 if job in F32_JOBS else 3000)
    out = [(0, 1), (size - 1, size)]
    for _ in range(n):
        ln = rnd.randrange(1, cap)
        lo = rnd.randrange(0, size - ln)
        out.append((lo, lo + ln))
    return out


def group_spread(tool) -> None:
    t0 = time.time()
    n = bad = 0
    for job in ALL_JOBS:
        for attr in ATTRS:
            for lo, hi in spread_slices(job, 10):
                ok, why, _out = run_and_judge(tool, job, attr, lo, hi, "spread")
                n += 1
                if not ok:
                    bad += 1
                    check(f"spread: {job} {attr} [{lo}, {hi})", False, why)
    check(f"spread: the twelve modes under all five attributes over 12 slices each, of odd alignment and size: all {n} pass, every "
          f"count as promised", bad == 0, f"{bad} of {n} failed")
    print(f"      ({n} slices in {time.time() - t0:.0f} s)")


def group_refuse(tool) -> None:
    for job in ALL_JOBS:
        N = size_of(job)
        msg = (f"need 0 <= lo < hi <= 2^32 (the encodings of a 32-bit operand)" if job in F32_JOBS
               else f"need 0 <= lo < hi <= {N} (the indices of the {job} space)")
        bad = []
        for what, args in (("an empty range", (job, 5, 5, "rne")), ("a reversed range", (job, 9, 5, "rne")),
                           ("a range past the space", (job, 0, N + 1, "rne")), ("a start at the end", (job, N, N + 1, "rmm")),
                           ("a negative start", (job, -1, 5, "rne")), ("garbage for a start", (job, "abc", 5, "rne")),
                           ("garbage for an end", (job, 0, "12x", "rne")), ("an empty bound", (job, "", 5, "rne"))):
            rc, out, err = tool.raw(*args)
            if not (rc == 2 and msg in err and " cases," not in out):
                bad.append((what, rc, err[-120:]))
        check(f"refuse: {job}: a range empty, reversed, past the space, negative or not a number is refused by name, exit 2, "
              f"nothing run", not bad, f"{bad[:2]}")
        rc, out, err = tool.raw(job, 0, 64)
        rc2, out2, err2 = tool.raw(job, 0, 64, "rtx")
        check(f"refuse: {job}: no attribute, or one that does not exist, is refused, exit 2, nothing run",
              rc == 2 and rc2 == 2 and " cases," not in out + out2, f"rc {rc} {rc2}")
    rc, out, err = tool.raw("dump", "rint128-class", 0, ENUMS["rint128-class"].N + 1)
    check("refuse: a wide dump past the space is refused by name", rc == 2 and out == "" and
          "need 0 <= lo < hi <= 137344 (the indices of the rint128-class space)" in err, err[-200:])
    rc, out, err = tool.raw("dump", "rint128-class")
    check("refuse: a wide dump with no range or `size` is refused", rc == 2 and out == "", f"rc {rc}")


def operand_set(job, lo, hi):
    if job in F32_JOBS:
        return set(range(lo, hi))
    e = ENUMS[job]
    return {e.operands(i)[0] for i in range(lo, hi)}


def group_sabotage(tool) -> None:
    bad = []
    n = 0
    for job in ALL_JOBS:
        size = size_of(job)
        for attr in ATTRS:
            lo = size // 2 + (0x1234 if job in F32_JOBS else 0)
            hi = lo + (4096 if job in F32_JOBS else 64)
            rc0, out0, m0 = tool.run(job, lo, hi, attr)
            rc, out, m = tool.run(job, lo, hi, attr, env={"CFT_SOAK_SABOTAGE": "1"})
            vm = int(m.group(4)) if m else 0
            named = [int(a, 16) for a in re.findall(r"^  MISMATCH \S+ \S+ a=0x([0-9a-f]+)", out, re.M)]
            ops = operand_set(job, lo, hi)
            benign = BENIGN.get(job, set())
            inside = bool(named) and all(a in ops or a in benign for a in named) and any(a in ops for a in named)
            n += 1
            if not (rc0 == 0 and rc == 1 and vm > 0 and inside):
                bad.append((job, attr, rc0, rc, vm, [hex(a) for a in named[:2]]))
    check(f"sabotage: CFT_SOAK_SABOTAGE=1 fails all twelve modes under all five attributes ({n} runs): exit 1, value mismatches, "
          f"operands named that the slice enumerates (or the benign operand in front of one), the same slice passing without it",
          not bad, f"{bad[:3]}")


# --- the plants ------------------------------------------------------------------------------------

LANE_OLD = "            memcpy(dp + i * esz, t + i * esz, esz);\n        }\n        off += c;\n"
LANE_NEW = ("            memcpy(dp + i * esz, t + i * esz, esz);\n            {\n                uint64_t plant_av;\n"
            "                memcpy(&plant_av, ap + i * esz, 8);\n"
            "                if (esz == 16 && (i % 2) == 0 && plant_av == 0x20ull &&\n"
            "                    ((ap[i * esz + 14] | (ap[i * esz + 15] << 8)) & 0x7fff) == 0x3fff)\n"
            "                    dp[i * esz] ^= 1u;\n            }\n        }\n        off += c;\n")
STICKY_OLD = "        int stk   = cft_bn_low_nonzero(m, shift - 1) || sticky;\n"
STICKY_NEW = ("        cft_bn plant_t;\n        int stk;\n        cft_bn_shr(&plant_t, m, 1);\n"
              "        stk = (shift > 1 && cft_bn_low_nonzero(&plant_t, shift - 2)) || sticky;\n")


def group_plants(tool, built_tree: str, work: str) -> None:
    # (a) a wrong class selector in the C builder: class 3 given the class-2 representative (its lowest bit forgotten)
    t = planted(built_tree, work, "selector", [("tools/clause5_soak.c", "        if (c == 1 || c == 3)\n            wset(s, 0);\n",
                                                "        if (c == 1)\n            wset(s, 0);\n")])
    if t is None:
        check("plants: the selector plant builds", False, "make failed")
    else:
        e = ENUMS["rint128-class"]
        bad = first_diff(t, "rint128-class", 0, e.N, e.dump_line)
        check("plant (class selector): a C builder that gives class 3 the class-2 representative is caught by the dump agreement, "
              "which names the first index that moves", bad is not None and bad.startswith("index "), bad or "no difference")
    # (b) the shared rule given the wrong attribute: mpfr_c5.h's rtz rint as floor
    t = planted(built_tree, work, "rule", [("tools/mpfr_c5.h", "    case CFT_RTZ: return mpfr_trunc(r, v);\n",
                                            "    case CFT_RTZ: return mpfr_floor(r, v);\n")])
    if t is None:
        check("plants: the rule plant builds", False, "make failed")
    else:
        N = ENUMS["rint128-class"].N
        rc0, out0, m0 = tool.run("rint128-class", 0, N, "rtz")
        ok0, why0 = judge("rint128-class", "rtz", 0, N, rc0, out0, m0)
        rc, out, m = t.run("rint128-class", 0, N, "rtz")
        rcn, outn, mn = t.run("rint128-class", 0, N, "rne")
        okn, whyn = judge("rint128-class", "rne", 0, N, rcn, outn, mn)
        check("plant (shared rule) CONTROL: the real tool passes rint128-class rtz whole", ok0, why0)
        check("plant (shared rule): mpfr_c5.h's rint rule given floor for rtz fails rint128-class rtz (exit 1, value mismatches on "
              "negative non-integers), and the same planted tool passes rne - the soak's oracle IS the shared rule",
              rc == 1 and m is not None and int(m.group(4)) > 0 and okn, f"rc {rc}: {out[:200]}; rne {whyn}")
    # (c) a fault in lane 0 of fp128's cft_rint for the operands of exponent 0 (1.0's field) whose low 64 bits are 0x20: the walking
    # one at bit 5, pattern 9, an odd index (116 patterns a cell), so a run that does not rotate meets them in lane 1 only, never in
    # lane 0. (At exponent 0 the half class's bit is 111, not 5; at exponent 106 it IS bit 5, an even index, which a first version
    # of this plant, without the exponent, met in lane 0 unrotated: MEASURED 2026-10-27, its control red.)
    t1 = planted(built_tree, work, "lane-rotated", [("src/clause5.c", LANE_OLD, LANE_NEW)])
    t2 = planted(built_tree, work, "lane-fixed", [("src/clause5.c", LANE_OLD, LANE_NEW)], "-O2 -DCLS_LANES_128=1 -DCLS_BATCH=4092")
    if t1 is None or t2 is None:
        check("plants: the lane-fault builds", False, "make failed")
    else:
        N = ENUMS["rint128-class"].N
        rc1, out1, m1 = t1.run("rint128-class", 0, N, "rne")
        named = [int(a, 16) for a in re.findall(r"^  MISMATCH rint\S* rne a=0x([0-9a-f]+)", out1, re.M)]
        check("plant (lane): a fault in lane 0 of fp128's cft_rint that only operands of exponent 0 with low 64 bits 0x20 meet is "
              "caught by the default build, which runs each operand in each of fp128's two lanes: exit 1, value mismatches, those "
              "operands named", rc1 == 1 and m1 is not None and int(m1.group(4)) > 0 and bool(named) and
              all(x & ((1 << 64) - 1) == 0x20 and (x >> 112) & 0x7FFF == 0x3FFF for x in named), f"rc {rc1}: {out1[:300]}")
        rc2, out2, m2 = t2.run("rint128-class", 0, N, "rne")
        check("plant (lane): the same fault is NOT met by a build that does not rotate (-DCLS_LANES_128=1 -DCLS_BATCH=4092): 0 "
              "mismatches, exit 0, k = 1 - the hole the rotation closes", rc2 == 0 and m2 is not None and int(m2.group(4)) == 0
              and int(m2.group(3)) == N, f"rc {rc2}: {out2[:200]}")
    # (d) a rounding defect in the library: the sticky tree leaves out the lowest dropped bit (hw/test_c5_class.py's plant)
    t = planted(built_tree, work, "sticky", [("src/softfloat.c", STICKY_OLD, STICKY_NEW)])
    if t is None:
        check("plants: the sticky plant builds", False, "make failed")
    else:
        res = {}
        for job in ("conv128to64-class", "scaleb128-class", "scaleb256-class"):
            N = ENUMS[job].N
            rc, out, m = t.run(job, 0, N, "rup")
            res[job] = (rc, int(m.group(4)) if m else -1, int(m.group(5)) if m else -1)
        rc, out, m = t.run(BIG, 0, 65536 * 4, "rup")
        res[BIG] = (rc, int(m.group(4)) if m else -1, int(m.group(5)) if m else -1)
        check("plant (sticky): a sticky tree without the lowest dropped bit is caught under rup by conv128to64-class, scaleb128-class "
              "and scaleb256-class whole and by conv256to128-class's first 262,144 indices: exit 1, mismatches in each",
              all(r[0] == 1 and r[1] + r[2] > 0 for r in res.values()), f"{res}")
    # (e) the FCVT table off by one in the oracle: the lanes a target cannot hold ARE compared (S = 0), so they fail
    t = planted(built_tree, work, "fcvt", [("tools/mpfr_c5.h", '    { "to_u32", 32, 0, 0xffffffffull, 0 },\n',
                                            '    { "to_u32", 32, 0, 0xfffffffeull, 0 },\n')])
    if t is None:
        check("plants: the FCVT plant builds", False, "make failed")
    else:
        N = ENUMS["cvtto128-class"].N
        rc, out, m = t.run("cvtto128-class", 0, N, "rne")
        named = re.findall(r"^  MISMATCH cvt_to_u32 rne a=0x[0-9a-f]+ exact=\d lib=0x00000000ffffffff want=0x00000000fffffffe$",
                           out, re.M)
        check("plant (FCVT table): the oracle's u32 maximum off by one fails cvtto128-class on the lanes u32 cannot hold (a NaN, "
              "+inf, an overflow): the out-of-range pairs are compared, not skipped", rc == 1 and m is not None and
              int(m.group(4)) > 0 and int(m.group(7)) == 0 and bool(named), f"rc {rc}: {out[:300]}")
    # (f) a widening that drops the significand's last bit
    t = planted(built_tree, work, "widen", [("tools/clause5_soak.c",
                                             "        wput(dst, W->man_w - msb, msb, m & (((uint64_t)1 << msb) - 1));\n",
                                             "        wput(dst, W->man_w - msb, msb, m & (((uint64_t)1 << msb) - 2));\n")])
    if t is None:
        check("plants: the widening plant builds", False, "make failed")
    else:
        bad = first_diff(t, "rint128-f32", 0x3F000000, 0x3F001000, f32_ref(128))
        rc, out, m = t.run("rint128-f32", 0x3F000000, 0x3F800000, "rne")
        check("plant (widening): a widening that drops the significand's last bit is caught by the dump agreement (the index named) "
              "and by rint128-f32 rne over [0.5, 1) (0.5 + 2^-24 widened as 0.5 rounds to 0, not 1)",
              bad is not None and rc == 1 and m is not None and int(m.group(4)) > 0, f"{bad}; rc {rc}: {out[:200]}")
    # (g) a wide mode counting one index too few: parse_soak's cover rule refuses it by name
    t = planted(built_tree, work, "count", [("tools/clause5_soak.c",
                                             "                                : wcvtto_batch(wj->wf, mi, XA, n))\n            return 1;\n"
                                             "        encodings += n;\n",
                                             "                                : wcvtto_batch(wj->wf, mi, XA, n))\n            return 1;\n"
                                             "        encodings += n - 1;\n")])
    if t is None:
        check("plants: the count plant builds", False, "make failed")
    else:
        rc0, out0, m0 = tool.run("conv128to64-class", 1000, 6000, "rne")
        ok0, why0 = judge("conv128to64-class", "rne", 1000, 6000, rc0, out0, m0)
        rc, out, m = t.run("conv128to64-class", 1000, 6000, "rne")
        try:
            L.parse_soak(out, rc, "conv128to64-class", "rne", None, 5000, {"encodings": 5000, "per_encoding": 1})
            why = "accepted"
        except L.VerdictError as ex:
            why = str(ex)
        check("plant (slice short) CONTROL: the real tool passes the slice and the cover rule", ok0, why0)
        check("plant (slice short): a wide mode that counts one index too few a call is refused by parse_soak's cover rule, by name "
              "('encodings where the slice has')", "encodings where the slice has" in why, why)


# --- unchanged -------------------------------------------------------------------------------------

def group_unchanged(tool, base_dir: str, work: str) -> None:
    rev = os.path.basename(os.path.normpath(base_dir))
    base = X.copy_tree(base_dir, os.path.join(work, "baseline"))
    old = X.build(base, f"the baseline {rev}")
    if old is None:
        check(f"unchanged: the baseline {rev} builds", False, "make failed")
        return
    inv = []
    for job, attrs in (("conv64to32-class", ("rne", "rtz", "rdn", "rup")), ("rint64-class", ATTRS), ("cvtto64-class", ATTRS),
                       ("cvtfrom64-class", ("rne", "rup")), ("scaleb64-class", ("rne", "rdn"))):
        for a in attrs:
            inv.append(([job, "1000", "3000", a], {}))
    for j, m in (("rint64", "rmm"), ("cvtto64", "rne"), ("scaleb64", "rup"), ("conv64to32", "rtz"), ("cvtfrom64", "rdn"),
                 ("cvtto32", "rmm"), ("scaleb32", "rne"), ("cvtfrom32", "rup")):
        inv.append(([j, "100000", "77", m], {}))
    for j in ("conv32to64", "rem32", "rem64", "nextup64", "nextdown64", "logb64", "class64"):
        inv.append(([j, "100000", "5"], {}))
    for job, a in (("rint32", "rne"), ("rint32", "rmm"), ("nextup32", None), ("logb32", None), ("class32", None),
                   ("conv32to64-all", None), ("cvtto32-all", "rup"), ("cvtfrom64-all", "rtz"), ("scaleb32-all", "rdn")):
        inv.append(([job, "0x3F7FFF00", "0x3F800100"] + ([a] if a else []), {}))
    inv.append((["scaleb32-wide", "0x00000001", "0x00000041", "rup"], {}))
    for p in ("scalbn", "castflags", "cvtfrom", "scalebrange"):
        inv.append((["probe", p], {}))
    for job in ("rint64-class", "scaleb64-class", "cvtfrom64-class"):
        inv.append((["dump", job, "100", "200"], {}))
    for j, m in (("conv64to32", "rne"), ("rint64", "rne"), ("cvtto64", "rup"), ("rint64-class", "rmm"), ("cvtto32-all", "rne")):
        args = [j, "100000", "3", m] if "-" not in j else [j, "2000", "2600", m]
        inv.append((args, {"CFT_SOAK_SABOTAGE": "1"}))
    n = same = 0
    for args, env in inv:
        outs = []
        for t in (old, tool):
            e = dict(os.environ)
            e.update(env)
            pr = subprocess.run(NICE + [t.path] + args, capture_output=True, text=True, timeout=1800, env=e)
            outs.append((pr.returncode, pr.stdout, pr.stderr))
        n += 1
        if outs[0] == outs[1]:
            same += 1
        else:
            check(f"unchanged: {' '.join(args)} {env or ''}", False, f"{outs[0][0]} vs {outs[1][0]}")
    # 55: the list above (18 class-mode slices, 15 random runs, 10 exhaustive slices, 4 probes, 3 dumps, 5 sabotaged runs);
    # a list that shrank would prove less than this line says
    check(f"unchanged: {n} invocations of the older modes, probes and dumps ({rev}'s default tool and this tree's MPFR=1 tool): the "
          f"same stdout, stderr and exit status for all {same} that agree", same == n == 55,
          f"{n - same} differ of {n} (the list is 55 long)")
    print(f"      ({n} invocations compared, {same} identical)")


# ---------------------------------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    rev = args[args.index("--baseline-tree") + 1] if "--baseline-tree" in args else None
    keep = "--keep" in args
    thorough = "--thorough" in args

    def want(g: str) -> bool:
        return only is None or g in only

    if os.name != "posix" or not shutil.which("make") or not (shutil.which("cc") or shutil.which("gcc")):
        skip("c5-wide", "needs POSIX with make and a C compiler (the soak requires a 64-bit Linux), and MPFR and GMP")
        print(f"c5-wide test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped")
        return 0
    work = tempfile.mkdtemp(prefix="c5-wide-test-")
    t0 = time.time()
    try:
        tree = X.copy_tree(ROOT, os.path.join(work, "tree"))
        tool, log = build_mpfr(tree, "this tree")
        if tool is None:
            if "mpfr.h" in log and ("No such file" in log or "not found" in log):
                skip("c5-wide", "MPFR's headers are not installed (libmpfr-dev): the wide modes cannot be built here")
            else:
                check("build: clause5-soak MPFR=1 builds in a scratch copy of host/", False, log[-300:])
        else:
            # the default build, in a copy of its own: a clause5-soak already in the copied host/ (an MPFR=1 one, say) is removed
            # first, or make would call it up to date and this would test the wrong binary (CLAUDE.md's XRT=1 trap)
            dtree = X.copy_tree(ROOT, os.path.join(work, "default"))
            for exe in ("clause5-soak", "clause5-soak.exe"):
                if os.path.isfile(os.path.join(dtree, "host", exe)):
                    os.remove(os.path.join(dtree, "host", exe))
            deftool = X.build(dtree, "the default build")
            for name, fn in (("build", lambda: group_build(tool, log, tree, work, deftool)), ("agree", lambda: group_agree(tool)),
                             ("whole", lambda: group_whole(tool, thorough)), ("spread", lambda: group_spread(tool)),
                             ("refuse", lambda: group_refuse(tool)), ("sabotage", lambda: group_sabotage(tool)),
                             ("plants", lambda: group_plants(tool, tree, work))):
                if want(name):
                    if name == "build" and deftool is None:
                        check("build: the default clause5-soak builds", False, "make failed")
                        continue
                    n0, f0 = CHECKS, len(FAILS)
                    fn()
                    print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            if rev and want("unchanged"):
                n0, f0 = CHECKS, len(FAILS)
                group_unchanged(tool, rev, work)
                print(f"unchanged: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            elif want("unchanged") and only is not None:
                skip("unchanged", "needs --baseline-tree DIR")
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"c5-wide test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
