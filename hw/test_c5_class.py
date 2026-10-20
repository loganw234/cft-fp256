#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Test of the clause-5 soak's class-level (L2) modes (host/tools/clause5_soak.c: conv64to32-class, rint64-class,
cvtto64-class, cvtfrom64-class, scaleb64-class), on the software backend. POSIX with make and a C compiler (the soak
needs a 64-bit Linux); skipped by name elsewhere. The model is hw/test_c5_exhaustive.py, whose Tool and build helpers
this file uses.

    python3 hw/test_c5_class.py [--only GROUP,...] [--baseline-tree DIR] [--thorough] [--keep]

It builds the tool in a scratch copy of host/ (make clause5-soak, XRT=0) and runs, niced, one process at a time:
  build      the tool builds; each mode's index space is the size python/c5_class_enum.py gives; the C tool's `dump` of
             EVERY index of each of the five spaces equals the Python reference's, line for line (not a sample)
  whole      each mode over its whole index space under every attribute it takes: no mismatch, the verdict clause holds
             (E = the indices, cases + skipped = k x E, which parse_soak's cover rule says; k is 4 for the two tile modes,
             a case a lane, and for cvtto64-class, a case a target), and for cvtto64-class the skipped pairs equal an
             INDEPENDENT count, in Python, from the rule alone
  spread     each mode and attribute over slices of odd alignment and size across the space, each held to the same rules
  refuse     a range that is empty, reversed, past the space, or not a number is refused by name (exit 2); so are an
             attribute a mode has no oracle for, a missing attribute, and a dump of a job that is not a class mode
  sabotage   CFT_SOAK_SABOTAGE=1 makes every mode FAIL, naming operands that are in the slice's enumerated set
  plants     one defect in a scratch copy for each class of check, red at the check written for it, each preceded by a
             CONTROL that the unplanted copy passes: a slice counted one index short (parse_soak's cover rule); a mode that
             skips every index (cvtto64-class given NaNs: the cover rule passes it, the rule that a class item compare
             something refuses it); a wrong class selector in the C operand builder (the dump comparison names the first
             index); a skip filter too eager (the independent skip count); a rounding defect in the library (a sticky tree
             without the lowest dropped bit) that the class mode catches and the same number of the random mode's draws
             do not; a defect only a FLAG shows (the library drops INEXACT for one class of operand: seen by a class case
             run alone, unseen in the batched build); and a defect of ONE LANE of a tile (seen by the default build, which
             runs each operand in each lane, unseen by the build that does not rotate)
  port       the Python port of the tool's random generator equals the operands the real tool prints, 16 batches
  unchanged  (with --baseline-tree DIR, a directory holding the baseline's host/, e.g. `git archive 881bbcb host | tar -x -C DIR`)
             the random modes and the exhaustive modes of that tree's tool and of this tree's print the same bytes and exit
             with the same status - 259 invocations, 301 with --thorough - and so does the failing path of conv64to32 under
             a fault planted in both trees' library; a control shows the comparison can tell a changed random mode

Prints one line a group and a last line "c5-class test: N checks, F failed, S skipped".
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
import test_c5_exhaustive as X  # noqa: E402  (Tool, build, copy_tree, patch_once, NICE)

CHECKS = 0
FAILS: list = []
SKIPS: list = []
NICE = X.NICE
ENUMS = C5.enums64()
JOBS = list(ENUMS)                     # conv64to32-class, rint64-class, cvtto64-class, cvtfrom64-class, scaleb64-class
ATTRS = {j: ENUMS[j].attrs for j in JOBS}


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


def variants():
    return [(j, a) for j in JOBS for a in ATTRS[j]]


def judge(job, attr, lo, hi, rc, out, m, skips=True, require_cases=True):
    """The rules every passing slice must meet. parse_soak's cover rule (the driver's own: E is the slice's indices,
    cases + skipped is k x E, and cases are k x E exactly where no pair is skipped); the rule written here for a class
    item, that a slice whose operands are known to include compared ones compared something; and, for cvtto64-class,
    that the skipped pairs are the independent Python count's."""
    if m is None:
        return False, f"no verdict line: rc {rc}: {out[-200:]}"
    e = ENUMS[job]
    k = e.k
    exact = job != "cvtto64-class"
    try:
        v = L.parse_soak(out, rc, job, attr, None, k * (hi - lo) if exact else None,
                         {"encodings": hi - lo, "per_encoding": k})
    except L.VerdictError as ex:
        return False, f"refused by the cover rule: {ex}"
    if not v.ok:
        return False, f"rc {rc}, mismatches: {out[:300]}"
    cases, skp = int(m.group(3)), int(m.group(7))
    if require_cases and cases == 0:
        return False, f"the slice [{lo}, {hi}) compared nothing: every one of its {k * (hi - lo)} checks was skipped"
    if not exact and skips:
        want = C5.expected_skipped_cvtto(e, lo, hi, attr)
        if skp != want:
            return False, f"{skp} pairs skipped where the independent count of the pairs the targets cannot hold is {want}"
    if exact and skp != 0:
        return False, f"{skp} skipped in a mode that skips nothing"
    return True, ""


def operand_set(job, lo, hi):
    e = ENUMS[job]
    return {e.operands(i)[0] for i in range(lo, hi)}


# ---------------------------------------------------------------------------------------------------
# the slices
# ---------------------------------------------------------------------------------------------------

def spread_slices(job: str, n: int = 40):
    """Slices of odd alignment and size across the space (a fixed seed), and its first and last indices."""
    size = ENUMS[job].N
    rnd = random.Random(20261020 + sum(map(ord, job)))
    out = [(0, min(size, 1)), (size - 1, size), (0, min(size, 4097)), (max(0, size - 4097), size)]
    cap = 1500 if job == "cvtto64-class" else 6000
    for _ in range(n):
        ln = rnd.randrange(1, cap)
        lo = rnd.randrange(0, size - ln)
        out.append((lo, lo + ln))
    return out


def run_dump(tool, job, lo, hi):
    return tool.raw("dump", job, lo, hi)


# ---------------------------------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------------------------------

def group_build(tool, work) -> None:
    for job in JOBS:
        rc, out, err = tool.raw("dump", job, "size")
        check(f"build: `dump {job} size` is the size the Python reference gives ({ENUMS[job].N})",
              rc == 0 and out.strip() == str(ENUMS[job].N), f"rc {rc}, {out.strip()!r}")
    t0 = time.time()
    for job in JOBS:
        e = ENUMS[job]
        rc, out, err = tool.raw("dump", job, 0, e.N)
        lines = out.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        first = None
        if len(lines) != e.N:
            first = f"{len(lines)} lines for {e.N} indices"
        else:
            for i, ln in enumerate(lines):
                if ln != e.dump_line(i):
                    first = f"index {i}: C {ln!r}, Python {e.dump_line(i)!r}"
                    break
        check(f"build: the C tool's `dump` of EVERY index of {job} ({e.N}) equals the Python reference's, line for line",
              rc == 0 and first is None, first or f"rc {rc}")
    print(f"      (the five spaces, {sum(e.N for e in ENUMS.values())} lines each side, {time.time() - t0:.0f} s)")
    rc, out, err = tool.raw("dump", "conv64to32-class", 1000, 1010)
    check("build: a part of the dump is that part of the whole", rc == 0 and out.splitlines() ==
          [ENUMS["conv64to32-class"].dump_line(i) for i in range(1000, 1010)], out[:200])
    rc, out, err = tool.raw("probe", "scalbn")
    check("build: the older probes still run", rc == 0 and "HONOURED" in out, out[:200])


def group_whole(tool) -> None:
    t0 = time.time()
    skipped_total = {}
    for job, attr in variants():
        e = ENUMS[job]
        rc, out, m = tool.run(job, 0, e.N, attr)
        ok, why = judge(job, attr, 0, e.N, rc, out, m)
        if ok and job == "cvtto64-class":
            skipped_total[attr] = (int(m.group(3)), int(m.group(7)))
        check(f"whole: {job} {attr} over its whole index space ({e.N}): passes, every count as promised", ok, why)
    print(f"      ({len(variants())} runs of the whole spaces in {time.time() - t0:.0f} s; cvtto64-class cases and skipped {skipped_total})")


def group_spread(tool) -> None:
    t0 = time.time()
    n = bad = 0
    for job, attr in variants():
        for lo, hi in spread_slices(job):
            rc, out, m = tool.run(job, lo, hi, attr)
            ok, why = judge(job, attr, lo, hi, rc, out, m, require_cases=False)
            n += 1
            if not ok:
                bad += 1
                check(f"spread: {job} {attr} [{lo}, {hi})", False, why)
    check(f"spread: {len(variants())} mode and attribute pairs over 44 slices each, of odd alignment and size: all {n} pass, "
          f"every count as promised", bad == 0, f"{bad} of {n} failed")
    print(f"      ({n} slices in {time.time() - t0:.0f} s)")


def group_refuse(tool) -> None:
    for job in JOBS:
        N = ENUMS[job].N
        a = ATTRS[job][0]
        for what, args in (("an empty range", (job, 5, 5, a)), ("a reversed range", (job, 9, 5, a)),
                           (f"a range past the space ({N})", (job, 0, N + 1, a)), (f"a start at {N}", (job, N, N + 1, a)),
                           ("a negative start", (job, -1, 5, a)), ("garbage for a start", (job, "abc", 5, a)),
                           ("garbage for an end", (job, 0, "12x", a)), ("an empty bound", (job, "", 5, a))):
            rc, out, err = tool.raw(*args)
            check(f"refuse: {job}: {what} is refused by name, exit 2, and runs nothing",
                  rc == 2 and f"need 0 <= lo < hi <= {N} (the indices of the {job} space)" in err and " cases," not in out,
                  f"rc {rc}: {err[-200:]}")
        rc, out, err = tool.raw(job, 0, 64)
        check(f"refuse: {job}: no attribute is refused, exit 2, and runs nothing", rc == 2 and " cases," not in out, f"rc {rc}")
        rc, out, err = tool.raw(job, 0, 64, "rtx")
        check(f"refuse: {job}: an attribute that does not exist is refused, exit 2", rc == 2 and " cases," not in out, f"rc {rc}")
        rc, out, err = tool.raw(job, 0, 64, "rmm")
        if "rmm" in ATTRS[job]:
            check(f"refuse: {job}: rmm IS accepted (its oracle is ties-away by definition)", rc == 0 and f"{job} rmm:" in out, out[:200])
        else:
            check(f"refuse: {job}: rmm has no oracle here and is refused, exit 2, and runs nothing",
                  rc == 2 and " cases," not in out, f"rc {rc}")
    rc, out, err = tool.raw("dump", "rint64-class")
    check("refuse: dump with no range or `size` is refused", rc == 2, f"rc {rc}")
    rc, out, err = tool.raw("dump", "rint64", 0, 5)
    check("refuse: dump of a job that is not a class mode is refused", rc == 2 and out == "", f"rc {rc}")
    rc, out, err = tool.raw("dump", "rint64-class", 0, ENUMS["rint64-class"].N + 1)
    check("refuse: dump past the space is refused by name", rc == 2 and "need 0 <= lo < hi <=" in err and out == "", f"rc {rc}")


def group_sabotage(tool) -> None:
    for job, attr in variants():
        e = ENUMS[job]
        lo, hi = (e.N // 2, e.N // 2 + 256)
        rc0, out0, m0 = tool.run(job, lo, hi, attr)
        rc, out, m = tool.run(job, lo, hi, attr, env={"CFT_SOAK_SABOTAGE": "1"})
        vm = int(m.group(4)) if m else 0
        named = [int(a, 16) for a in re.findall(r"^  MISMATCH \S+ \S+ a=0x([0-9a-f]+)", out, re.M)]
        ops = operand_set(job, lo, hi)
        # the sabotage flips the first result of every call; in a tile mode that first lane can be a benign operand (1.0 for rint,
        # +0 for scaleB) that stands in front of the operand to put it in a lane, and that is named then
        benign = {"rint64-class": {0x3FF0000000000000}, "scaleb64-class": {0}}.get(job, set())
        inside = all(a in ops or a in benign for a in named) and any(a in ops for a in named)
        check(f"sabotage: {job} {attr}: CFT_SOAK_SABOTAGE=1 fails (exit 1, value mismatches, operands named that the slice "
              f"enumerates, or the benign operand in front of one) and the same slice passes without it",
              rc0 == 0 and rc == 1 and vm > 0 and named and inside,
              f"clean rc {rc0}; sabotaged rc {rc}, {vm} mismatches, named {[hex(a) for a in named[:3]]}")


# --- the plants ------------------------------------------------------------------------------------

def group_plants(tool, built_tree: str, work: str) -> None:
    # (a) a slice counted one index short: parse_soak's cover rule refuses it, by name
    wc = X.plant_tool(built_tree, work, "count", [("        if (conv64to32_batch(mi, A, n, flags_ok))\n            return 1;\n        encodings += n;",
                                                   "        if (conv64to32_batch(mi, A, n, flags_ok))\n            return 1;\n        encodings += n - 1;")])
    if wc is None:
        check("plants: the slice-short plant builds", False, "make failed")
    else:
        lo, hi = 1000, 6000
        rc0, out0, m0 = tool.run("conv64to32-class", lo, hi, "rne")
        ok0, why0 = judge("conv64to32-class", "rne", lo, hi, rc0, out0, m0)
        check("plant (slice short) CONTROL: the real tool passes the slice and the cover rule", ok0, why0)
        rc, out, m = wc.run("conv64to32-class", lo, hi, "rne")
        ok, why = judge("conv64to32-class", "rne", lo, hi, rc, out, m)
        check("plant (slice short): a tool that counts one index too few is refused by the cover rule, by name "
              "('encodings where the slice has')", not ok and "encodings where the slice has" in why, why)
    # (b) a mode that skips every index: the cover rule passes it (cases + skipped is k x E), a class item must compare something
    ws = X.plant_tool(built_tree, work, "skipall", [(
        "    return ((uint64_t)sign << 63) | ((uint64_t)b << 52) |\n           (cls_sig(CLS_W + 1, d, c, t) & cls_mask(CLS_W));",
        "    if (job == CLS_CVTTO)\n        return 0x7ff8000000000000ull;\n    return ((uint64_t)sign << 63) | ((uint64_t)b << 52) |\n"
        "           (cls_sig(CLS_W + 1, d, c, t) & cls_mask(CLS_W));")])
    if ws is None:
        check("plants: the skip-everything plant builds", False, "make failed")
    else:
        N = ENUMS["cvtto64-class"].N
        rc, out, m = ws.run("cvtto64-class", 0, N, "rne")
        blind, why_blind = judge("cvtto64-class", "rne", 0, N, rc, out, m, skips=False, require_cases=False)
        full, why_full = judge("cvtto64-class", "rne", 0, N, rc, out, m, skips=False)
        check("plant (skip every index): the mode that skips every index passes the cover rule (E, cases + skipped = 4 x E, "
              "no mismatch, exit 0) - parse_soak alone does not see it", blind and m is not None and int(m.group(3)) == 0
              and int(m.group(7)) == 4 * N, why_blind)
        check("plant (skip every index): and the rule that a class item compare something refuses it, by name "
              "('compared nothing')", not full and "compared nothing" in why_full, why_full)
        rc1, out1, m1 = tool.run("cvtto64-class", 0, N, "rne")
        okc, whyc = judge("cvtto64-class", "rne", 0, N, rc1, out1, m1)
        check("plant (skip every index) CONTROL: the real tool passes the whole space, the independent skip count included",
              okc, whyc)
    # (c) a wrong class selector in the C operand builder: the dump comparison goes red at the first index it moves
    wd = X.plant_tool(built_tree, work, "dumpsel",
                      [("D = c == 0 ? 0 : (c == 1 ? 1 : (c == 2 ? half : (half | 1)));",
                        "D = c == 0 ? 0 : (c == 1 ? 1 : (c == 2 ? half : half));")])
    if wd is None:
        check("plants: the class-selector plant builds", False, "make failed")
    else:
        e = ENUMS["rint64-class"]
        rc, out, err = wd.raw("dump", "rint64-class", 0, e.N)
        first = next((i for i, ln in enumerate(out.splitlines()) if ln != e.dump_line(i)), None)
        rc0, out0, err0 = tool.raw("dump", "rint64-class", 0, e.N)
        check("plant (class selector) CONTROL: the real tool's dump equals the reference", out0.splitlines() ==
              [e.dump_line(i) for i in range(e.N)], "differs")
        check("plant (class selector): a C operand builder that gives class 3 the class-2 representative is caught by the dump "
              "comparison, which names the first index that moves", first is not None, "no difference found")
    # (c2) cvtto64-class's skipped pairs are counted independently, in Python, from the rule: a u32 skip filter that is too eager
    # (the shared kernel cvtto_batch, the same plant as hw/test_c5_exhaustive.py's) prints E encodings, cases + skipped = 4 x E and
    # no mismatch, so the cover rule passes it, and only the independent count refuses it
    wf = X.plant_tool(built_tree, work, "skipfilter", [("} else if (r < 0 || r > (long long)UINT32_MAX) {",
                                                          "} else if (r < 0 || r >= (long long)INT32_MAX) {")])
    if wf is None:
        check("plants: the skip-filter plant builds", False, "make failed")
    else:
        N = ENUMS["cvtto64-class"].N
        rc, out, m = wf.run("cvtto64-class", 0, N, "rne")
        blind, why_blind = judge("cvtto64-class", "rne", 0, N, rc, out, m, skips=False)
        full, why_full = judge("cvtto64-class", "rne", 0, N, rc, out, m)
        check("plant (skip filter): a u32 skip filter that is too eager passes the cover rule and every other check (exit 0, no "
              "mismatch, E encodings, cases + skipped = 4 x E)", blind, why_blind)
        check("plant (skip filter): and the independent count of the pairs the targets cannot hold catches it, by name",
              not full and "independent count" in why_full, why_full)
    # (d) a rounding defect: the library's sticky tree leaves out the lowest dropped bit
    wl = plant_sticky(built_tree, work)
    if wl is None:
        check("plants: the sticky-tree plant builds", False, "make failed")
        return
    N = ENUMS["conv64to32-class"].N
    # the planted build must still be the library: CONTROL = the unplanted tool passes these runs
    rows = {}
    for attr in ("rne", "rtz", "rdn", "rup"):
        rc0, out0, m0 = tool.run("conv64to32-class", 0, N, attr)
        ok0, why0 = judge("conv64to32-class", attr, 0, N, rc0, out0, m0)
        rc, out, m = wl.run("conv64to32-class", 0, N, attr)
        vm = int(m.group(4)) if m else -1
        named = re.findall(r"^  MISMATCH conv64to32 \S+ a=0x([0-9a-f]+)", out, re.M)
        rnd = []
        for seed in (1, 77, 4242):
            rcr = subprocess.run(NICE + [wl.path, "conv64to32", str(N), str(seed), attr], capture_output=True, text=True, timeout=600)
            mm = re.search(r"^(\S+) (\S+): (\d+) cases, (\d+) value mismatches, (\d+) flag mismatches", rcr.stdout, re.M)
            rnd.append(int(mm.group(4)) if mm else -1)
        rows[attr] = (ok0, vm, named[:2], rnd)
        check(f"plant (rounding defect) CONTROL: the unplanted tool passes conv64to32-class {attr} over the whole space", ok0, why0)
        if attr != "rtz":
            check(f"plant (rounding defect): the class mode catches a sticky tree without the lowest dropped bit under {attr}: exit 1, "
                  f"value mismatches, operands named", rc == 1 and vm > 0 and bool(named) and all(
                      int(a, 16) in operand_set("conv64to32-class", 0, N) for a in named), f"rc {rc}, {vm}, {named[:3]}")
            check(f"plant (rounding defect): the same number of the random mode's draws ({N} each, seeds 1, 77, 4242) under {attr} "
                  f"do NOT catch it", all(x == 0 for x in rnd), f"{rnd}")
        else:
            check("plant (rounding defect): under rtz the defect has no value-level witness (truncation never rounds up, and the "
                  "inexact flag is computed apart): the class mode passes, as it must", rc == 0 and vm == 0, f"rc {rc}, {vm}")
    big = subprocess.run(NICE + [wl.path, "conv64to32", str(100 * N), "1", "rup"], capture_output=True, text=True, timeout=900)
    mm = re.search(r"^(\S+) (\S+): (\d+) cases, (\d+) value mismatches, (\d+) flag mismatches", big.stdout, re.M)
    check(f"plant (rounding defect): even {100 * N} random draws (100 times the class set) do not catch it under rup",
          mm is not None and int(mm.group(4)) == 0 and big.returncode == 0, big.stdout[:200])
    print(f"      (planted tool: attribute -> (control ok, class-mode mismatches, first operands, random mismatches over 3 seeds): {rows})")
    # the other modes that round through the same function are caught too
    N2 = ENUMS["cvtfrom64-class"].N
    rc, out, m = wl.run("cvtfrom64-class", 0, N2, "rup")
    check("plant (rounding defect): cvtfrom64-class, which rounds through the same function, is caught too under rup",
          rc == 1 and m is not None and int(m.group(4)) > 0, out[:200])
    # (e) a defect only a FLAG shows: the library drops INEXACT for the operands whose dropped bits are exactly 0...01 and which
    # do not overflow fp32 (the overflow path raises INEXACT itself; the value is
    # right in every attribute). In a batch the flags are compared as an OR, and the other operands raise INEXACT, so it is unseen
    # (-DCLS_BATCH=4092: the whole space passes); a class case run alone has its own flags, and the default build sees it
    sf_edit = [("src/softfloat.c", "    *inexact = 1;\n    return 0;\n}\n",
                "    {\n        cft_bn plant_t;\n        cft_bn_shr(&plant_t, m, 1);\n        *inexact = !(shift > 1 && cft_bn_bit(m, 0) &&\n"
                "                     !cft_bn_low_nonzero(&plant_t, shift - 1));\n    }\n    return 0;\n}\n")]
    wf1 = build_knob(built_tree, work, "flagonly-alone", sf_edit, "-O2")
    wf2 = build_knob(built_tree, work, "flagonly-batch", sf_edit, "-O2 -DCLS_BATCH=4092")
    if wf1 is None or wf2 is None:
        check("plants: the flag-only builds", False, "make failed")
    else:
        for attr in ("rne", "rtz"):
            rc1, out1, m1 = wf1.run("conv64to32-class", 0, N, attr)
            rc2, out2, m2 = wf2.run("conv64to32-class", 0, N, attr)
            named = [int(a, 16) for a in re.findall(r"^  FLAGS conv64to32 \S+ a=0x([0-9a-f]+) lib=0x00 want=0x1[08]", out1, re.M)]
            check(f"plant (flag only): a class case run alone sees INEXACT dropped on the lone-lowest-bit operands under {attr}: exit 1, "
                  f"value mismatches 0, flag mismatches > 0, the operands named (each with dropped bits 0...01)",
                  rc1 == 1 and m1 is not None and int(m1.group(4)) == 0 and int(m1.group(5)) > 0 and bool(named)
                  and all(lone_low_bit(x) for x in named), f"rc {rc1}: {out1[:300]}")
            check(f"plant (flag only): the same space in batches of 4092 does NOT see it under {attr} (flags are compared as an OR "
                  f"over a call): exit 0, 0 value and 0 flag mismatches - the known limit the default build removes",
                  rc2 == 0 and m2 is not None and int(m2.group(4)) == 0 and int(m2.group(5)) == 0, f"rc {rc2}: {out2[:200]}")
    # (f) a defect specific to one LANE of the tile: cft_rint's result is flipped in lane 2 of a pass when the operand's fraction field
    # is exactly 0x20 (the class-0 representative with a walking one at bit 5). Run as the index space lays it out, an operand's lane is
    # its index mod 4 and the walking one at bit 5 is pattern 9, index mod 4 = 1, so a run that does not rotate (-DCLS_LANES=1
    # -DCLS_BATCH=4092) never has it in lane 2 and never meets the fault; the default build runs each operand in each lane and does
    rint_edit = [("src/clause5.c", "            memcpy(dp + i * esz, t + i * esz, esz);\n        }\n        off += c;\n",
                  "            memcpy(dp + i * esz, t + i * esz, esz);\n            {\n                uint64_t plant_av;\n"
                  "                memcpy(&plant_av, ap + i * esz, 8);\n"
                  "                if ((i % 4) == 2 && (plant_av & 0x000fffffffffffffull) == 0x20ull)\n"
                  "                    dp[i * esz] ^= 1u;\n            }\n        }\n        off += c;\n")]
    wl1 = build_knob(built_tree, work, "lane-rotated", rint_edit, "-O2")
    wl2 = build_knob(built_tree, work, "lane-fixed", rint_edit, "-O2 -DCLS_LANES=1 -DCLS_BATCH=4092")
    if wl1 is None or wl2 is None:
        check("plants: the lane-fault builds", False, "make failed")
    else:
        Nr = ENUMS["rint64-class"].N
        rc0, out0, m0 = tool.run("rint64-class", 0, Nr, "rne")
        ok0, why0 = judge("rint64-class", "rne", 0, Nr, rc0, out0, m0)
        check("plant (lane) CONTROL: the real tool passes rint64-class over the whole space (k = 4: each operand in each lane)", ok0, why0)
        rc1, out1, m1 = wl1.run("rint64-class", 0, Nr, "rne")
        named = [int(a, 16) for a in re.findall(r"^  MISMATCH rint\S* rne a=0x([0-9a-f]+)", out1, re.M)]
        check("plant (lane): a fault in lane 2 of cft_rint that only the operand with fraction field 0x20 meets is caught by the "
              "default build, which runs each operand in each lane: exit 1, value mismatches, that operand named",
              rc1 == 1 and m1 is not None and int(m1.group(4)) > 0 and bool(named) and all(x & 0x000FFFFFFFFFFFFF == 0x20 for x in named),
              f"rc {rc1}: {out1[:300]}")
        rc2, out2, m2 = wl2.run("rint64-class", 0, Nr, "rne")
        check("plant (lane): the same fault is NOT met by a run that does not rotate (-DCLS_LANES=1 -DCLS_BATCH=4092: each operand in the "
              "one lane its index gives it): 0 mismatches, exit 0 - the hole the rotation closes",
              rc2 == 0 and m2 is not None and int(m2.group(4)) == 0 and int(m2.group(3)) == Nr, f"rc {rc2}: {out2[:200]}")


def lone_low_bit(x: int) -> bool:
    """Is the operand one whose bits below its fp32 rounding position are exactly 0...01 (the only dropped bit set is the
    lowest)? The operands the flag-only plant's defect acts on."""
    u = C5.sf.unpack(C5.FP64, x)
    if u.kind not in (C5.sf.NORM, C5.sf.SUB):
        return False
    top = u.m.bit_length() - 1 + u.e
    ulp = max(top - 23, -149)
    dropped = ulp - u.e
    return dropped > 1 and (u.m & ((1 << dropped) - 1)) == 1


def build_knob(built_tree: str, work: str, name: str, edits: list, cflags: str):
    """A copy of the built tree with the edits (each (file under host/, old, new), applied exactly once), built with CFLAGS=cflags
    (the class modes' compile-time knobs, CLS_BATCH and CLS_LANES): its Tool, or None."""
    tree = X.copy_tree(built_tree, os.path.join(work, "plant-" + name))
    for rel, old, new in edits:
        X.patch_once(os.path.join(tree, "host", *rel.split("/")), old, new, name)
    env = dict(os.environ)
    env["CFLAGS"] = cflags
    p = subprocess.run(NICE + ["make", "-C", os.path.join(tree, "host"), "-j4", "clause5-soak"], capture_output=True, text=True,
                       timeout=900, env=env)
    exe = os.path.join(tree, "host", "clause5-soak")
    if p.returncode != 0 or not os.path.exists(exe):
        print(f"  build of {name} failed (rc {p.returncode}): {(p.stdout + p.stderr)[-600:]}")
        return None
    return X.Tool(exe)


def plant_sticky(built_tree: str, work: str):
    """A copy of the built tree whose library has a sticky tree that leaves out the lowest dropped bit (sf_round_at's
    `stk`), rebuilt: its Tool, or None."""
    tree = X.copy_tree(built_tree, os.path.join(work, "plant-sticky"))
    sf_c = os.path.join(tree, "host", "src", "softfloat.c")
    X.patch_once(sf_c, "        int stk   = cft_bn_low_nonzero(m, shift - 1) || sticky;\n",
                 "        cft_bn plant_t;\n        int stk;\n        cft_bn_shr(&plant_t, m, 1);\n"
                 "        stk = (shift > 1 && cft_bn_low_nonzero(&plant_t, shift - 2)) || sticky;\n", "sticky")
    return X.build(tree, "the sticky-tree plant")


def group_port(tool) -> None:
    """The Python port of the tool's random generator is held to the real tool: the operand of the first lane of each of
    16 batches, from the software backend's sabotage control."""
    rc, out, err = tool.raw("conv64to32", 100000, 1, "rne", env={"CFT_SOAK_SABOTAGE": "1"})
    named = [int(a, 16) for a in re.findall(r"^  MISMATCH conv64to32 rne a=0x([0-9a-f]+)", out, re.M)]
    g = C5.SoakRng(1)
    leaders = []
    for _ in range(25):                                   # 100,000 operands: 24 batches of 4,096 and one of 1,696
        leaders.append(g.banded64())
        for _ in range(4095):
            g.banded64()
    # a batch whose first operand is a NaN prints nothing (flipping a NaN's low bit still agrees as a class), so the printed
    # operands are the leaders that are not NaNs, in order
    want = [x for x in leaders if not ((x >> 52) & 0x7FF == 0x7FF and x & ((1 << 52) - 1))]
    check(f"port: the ported banded64() equals the {len(named)} batch-leading operands the real tool printed (the NaN-led "
          f"batches print nothing: {25 - len(want)} of 25)", len(named) >= 12 and named == want[:len(named)],
          f"{[hex(x) for x in named[:4]]} vs {[hex(x) for x in want[:4]]}")


def group_unchanged(tool, built_tree: str, base_dir: str, work: str, thorough: bool) -> None:
    rev = os.path.basename(os.path.normpath(base_dir))
    base = X.copy_tree(base_dir, os.path.join(work, "baseline"))
    old = X.build(base, f"the baseline {rev}")
    if old is None:
        check(f"unchanged: the baseline {rev} builds", False, "make failed")
        return
    count = 1000000 if thorough else 200000
    seeds = (1, 77, 4242) if thorough else (1, 77)
    inv = []
    for seed in seeds:
        for m in ("rne", "rtz", "rdn", "rup", "rmm"):
            inv += [("cvtto32", count, seed, m), ("cvtto64", count, seed, m), ("rint64", count, seed, m)]
        for m in ("rne", "rtz", "rdn", "rup"):
            inv += [("cvtfrom32", count, seed, m), ("cvtfrom64", count, seed, m), ("scaleb32", count, seed, m),
                    ("scaleb64", count, seed, m), ("conv64to32", count, seed, m)]
        inv += [("conv32to64", count, seed, None), ("rem32", count, seed, None), ("rem64", count, seed, None),
                ("nextup64", count, seed, None), ("nextdown64", count, seed, None), ("logb64", count, seed, None),
                ("class64", count, seed, None)]
    for c in (1, 7, 4095, 4096, 4097, 12289):
        inv += [("conv64to32", c, 5, "rne"), ("conv64to32", c, 5, "rup"), ("conv32to64", c, 5, None)]
    cases = [([j, str(c), str(s)] + ([m] if m else []), {}) for j, c, s, m in inv]
    # the sabotage runs (failing logs, operands and all)
    for j, m in (("conv64to32", "rne"), ("conv64to32", "rdn"), ("rint64", "rne"), ("cvtto64", "rup"), ("cvtfrom64", "rtz"),
                 ("scaleb64", "rne"), ("scaleb32", "rup"), ("conv32to64", None)):
        cases.append(([j, "100000", "3"] + ([m] if m else []), {"CFT_SOAK_SABOTAGE": "1"}))
    # the exhaustive modes of the earlier parcel, over slices and every attribute they take
    for job, attrs in (("conv32to64-all", [None]), ("cvtto32-all", ["rne", "rtz", "rdn", "rup", "rmm"]),
                       ("cvtfrom32-all", ["rne", "rtz", "rdn", "rup"]), ("cvtfrom64-all", ["rne", "rtz", "rdn", "rup"]),
                       ("scaleb32-all", ["rne", "rtz", "rdn", "rup"]), ("scaleb32-wide", ["rne", "rtz", "rdn", "rup"])):
        for a in attrs:
            for lo, hi in ((0, 5000), (0x3F7FFF00, 0x3F800100), (0x4EFFFF00, 0x4F000100), (0x7F7FFF00, 0x7F800100),
                           (0xBF000000, 0xBF001000)):
                if job == "scaleb32-wide":
                    hi = lo + 200
                cases.append(([job, str(lo), str(hi)] + ([a] if a else []), {}))
            cases.append(([job, "0", "2000"] + ([a] if a else []), {"CFT_SOAK_SABOTAGE": "1"}))
    for job, attrs in (("rint32", ["rne", "rtz", "rdn", "rup", "rmm"]), ("nextup32", [None]), ("nextdown32", [None]),
                       ("logb32", [None]), ("class32", [None])):
        for a in attrs:
            cases.append(([job, "0x3F7FFF00", "0x3F800100"] + ([a] if a else []), {}))
    for p in ("scalbn", "castflags", "cvtfrom", "scalebrange"):
        cases.append((["probe", p], {}))
    n = same = 0
    for args, env in cases:
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
            check(f"unchanged: {' '.join(args)} {env or ''} prints the same bytes and exits the same", False,
                  f"{outs[0][0]} vs {outs[1][0]}")
    # the argument errors print the usage text, which is longer now by design: stdout and exit status are compared, and every
    # line of the old usage must be in the new
    for args in (["conv32to64", "5"], ["nosuchjob", "1", "2"], ["cvtfrom32", "100", "1", "rmm"], ["scaleb32", "100", "1", "rmm"]):
        res = []
        for t in (old, tool):
            pr = subprocess.run(NICE + [t.path] + args, capture_output=True, text=True, timeout=60)
            res.append((pr.returncode, pr.stdout, pr.stderr.replace(t.path, "<tool>")))
        n += 1
        old_lines = [x for x in res[0][2].splitlines() if x.strip()]
        ok = res[0][0] == res[1][0] and res[0][1] == res[1][1] and all(x in res[1][2] for x in old_lines)
        same += ok
        if not ok:
            check(f"unchanged: the argument error {' '.join(args)} keeps its old usage lines", False, res[1][2][:200])
    # the failing paths of the one random mode whose driver was split (conv64to32): the SAME fault is planted in both trees'
    # library - an extra divide-by-zero flag, which no conversion and no oracle ever raises, for every operand in [1, 2) -
    # which makes the batch flags disagree and sends the mode down its per-lane flag recheck; the output, FLAGS lines and
    # counts and all, must be the same from both tools
    flag_edit = ("            acc |= fl;\n        }\n        lane_store(fd, (uint8_t *)d, i, &v);",
                 "            acc |= fl;\n            if (e == -52)\n                acc |= CFT_SF_DIVZERO;\n        }\n"
                 "        lane_store(fd, (uint8_t *)d, i, &v);")
    pl = []
    for label, src in (("old", base), ("new", built_tree)):
        t = X.copy_tree(src, os.path.join(work, "flagplant-" + label))
        X.patch_once(os.path.join(t, "host", "src", "clause5.c"), flag_edit[0], flag_edit[1], "flag plant " + label)
        pl.append(X.build(t, f"the {label} tree with the flag fault"))
    if None in pl:
        check("unchanged: the flag-fault builds of both trees", False, "make failed")
    else:
        nf = sf = 0
        for seed in (1, 77):
            for m in ("rne", "rtz", "rdn", "rup"):
                outs = []
                for t in pl:
                    pr = subprocess.run(NICE + [t.path, "conv64to32", "200000", str(seed), m], capture_output=True, text=True, timeout=600)
                    outs.append((pr.returncode, pr.stdout, pr.stderr))
                nf += 1
                sf += outs[0] == outs[1]
                if outs[0] != outs[1]:
                    check(f"unchanged (flag fault): conv64to32 200000 {seed} {m}", False, "differs")
        flags_seen = "FLAGS conv64to32" in outs[0][1] and outs[0][0] == 1
        check(f"unchanged (flag fault): conv64to32's failing path - flag mismatches named, exit 1 - is the same from the old and the "
              f"new tool: {sf} of {nf} runs identical (the fault is seen: FLAGS lines, exit 1)", sf == nf and flags_seen, f"{sf} of {nf}")
    # the comparison can fail: the new tree's random conv64to32 counting one case too few differs from the baseline's
    wr = X.plant_tool(built_tree, work, "randcount", [("    cases += n;\n    return 0;\n}\n\n/* The castflags probe's verdict, applied",
                                                        "    cases += n - 1;\n    return 0;\n}\n\n/* The castflags probe's verdict, applied")])
    if wr is None:
        check("plants: the changed-random-mode plant builds", False, "make failed")
    else:
        outs = []
        for t in (old, wr):
            pr = subprocess.run(NICE + [t.path, "conv64to32", "200000", "1", "rne"], capture_output=True, text=True, timeout=600)
            outs.append((pr.returncode, pr.stdout, pr.stderr))
        check("unchanged (plant): a random mode that counts one case too few a batch is told from the baseline by the byte "
              "comparison (200000 cases against 199951)", outs[0] != outs[1] and "200000 cases" in outs[0][1]
              and "199951 cases" in outs[1][1], f"{outs}")
    check(f"unchanged: {n} invocations of the random and exhaustive modes ({rev}'s tool and this tree's): the same stdout, "
          f"stderr and exit status for all {same} that agree (the four argument errors: stdout and exit status, and every "
          f"old usage line present)", same == n, f"{n - same} differ")
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
        skip("c5-class", "needs POSIX with make and a C compiler (the soak requires a 64-bit Linux)")
        print(f"c5-class test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped")
        return 0
    work = tempfile.mkdtemp(prefix="c5-class-test-")
    t0 = time.time()
    try:
        tree = X.copy_tree(ROOT, os.path.join(work, "tree"))
        tool = X.build(tree, "this tree")
        if tool is None:
            check("build: clause5-soak builds in a scratch copy of host/", False, "make failed")
        else:
            for name, fn in (("build", lambda: group_build(tool, work)), ("whole", lambda: group_whole(tool)),
                             ("spread", lambda: group_spread(tool)), ("refuse", lambda: group_refuse(tool)),
                             ("sabotage", lambda: group_sabotage(tool)), ("port", lambda: group_port(tool)),
                             ("plants", lambda: group_plants(tool, tree, work))):
                if want(name):
                    n0, f0 = CHECKS, len(FAILS)
                    fn()
                    print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            if rev and want("unchanged"):
                n0, f0 = CHECKS, len(FAILS)
                group_unchanged(tool, tree, rev, work, thorough)
                print(f"unchanged: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            elif want("unchanged") and only is not None:
                skip("unchanged", "needs --baseline-tree DIR")
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"c5-class test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
