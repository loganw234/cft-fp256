#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Test of the clause-5 soak's exhaustive conversion and scaleB modes (host/tools/clause5_soak.c: conv32to64-all,
cvtto32-all, cvtfrom32-all, cvtfrom64-all, scaleb32-all, scaleb32-wide), on the software backend. POSIX with
make and a C compiler (the soak needs a 64-bit Linux); skipped by name elsewhere.

    python3 hw/test_c5_exhaustive.py [--only GROUP,...] [--baseline-tree DIR] [--keep]

It builds the tool in a scratch copy of host/ (make clause5-soak, XRT=0) and runs, niced, one process at a time:
  build      the tool builds, and `probe scalebrange` finds the derived exponent range holds on this libm
  special    every mode, under every attribute it takes, over small slices of every special region: zeros,
             subnormals (and the subnormal/normal edge), the edges of the normal range, infinities, quiet and
             signalling NaNs (and the edge between them), the four integer targets' range boundaries, and the
             integers around 2^24 and the i32 limits; each must pass with the counts the mode promises
  spread     every mode, every attribute, over slices spread across the whole 2^32 space (evenly, and drawn at
             random from a fixed seed)
  refuse     a range that is empty, reversed, past 2^32 or not a number is refused by name (exit 2); so is an
             attribute a mode has no oracle for
  sabotage   CFT_SOAK_SABOTAGE=1 makes every mode FAIL, naming operands inside its slice (and the same slice passes
             without it)
  plants     one defect put back into a scratch copy for each class of check, and the soak must go red, at the
             operand or the exponent the defect names: a library result changed for ONE operand, in each of the
             six modes (a copy of host/src/clause5.c, built; a CONTROL build of the same copy must pass first);
             the oracle given the wrong attribute, for each attribute of each mode that rounds; the exponent range
             wrong by one on either side, which `probe scalebrange` and the witnesses past the edges must both
             catch; and the tool counting one encoding too few
  unchanged  (with --baseline-tree DIR, a directory holding the baseline's host/ - `git archive REV host | tar -x -C DIR`)
             the random modes of that tree's tool and of this tree's, over the same invocations, print the same
             bytes and exit with the same status

Prints one line a group and a last line "c5-exhaustive test: N checks, F failed, S skipped".
"""
from __future__ import annotations

import math
import os
import random
import re
import struct
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import card_stress_lib as L  # noqa: E402

CHECKS = 0
FAILS: list = []
SKIPS: list = []


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


LINE = re.compile(r"^(\S+) (\S+): (\d+) cases, (\d+) value mismatches, (\d+) flag mismatches, (\d+) encodings, "
                  r"(\d+) skipped$", re.M)

# (job word, its attributes, checks an encoding, whether the case count is a function of the slice)
MODES = [("conv32to64-all", [None], 1, True),
         ("cvtto32-all", ["rne", "rtz", "rdn", "rup", "rmm"], 4, False),
         ("cvtfrom32-all", ["rne", "rtz", "rdn", "rup"], 2, True),
         ("cvtfrom64-all", ["rne", "rtz", "rdn", "rup"], 2, True),
         ("scaleb32-all", ["rne", "rtz", "rdn", "rup"], 17, True),
         ("scaleb32-wide", ["rne", "rtz", "rdn", "rup"], 568, True)]
NICE = ["nice", "-n", "10"] if shutil.which("nice") else []


def variants():
    return [(job, attr, k, exact) for job, attrs, k, exact in MODES for attr in attrs]


class Tool:
    """A built clause5-soak."""

    def __init__(self, path: str):
        self.path = path

    def run(self, job: str, lo, hi, attr=None, env=None, extra=None, timeout: int = 600):
        argv = NICE + [self.path, job, str(lo), str(hi)] + ([attr] if attr else []) + (extra or [])
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=e)
        out = p.stdout + p.stderr
        return p.returncode, out, LINE.search(p.stdout)

    def raw(self, *args, env=None, timeout: int = 600):
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.run(NICE + [self.path] + [str(a) for a in args], capture_output=True, text=True, timeout=timeout, env=e)
        return p.returncode, p.stdout, p.stderr


def build(tree: str, label: str):
    """make clause5-soak in tree/host: the Tool, or None with a reason."""
    p = subprocess.run(NICE + ["make", "-C", os.path.join(tree, "host"), "-j4", "clause5-soak"], capture_output=True, text=True,
                       timeout=900)
    exe = os.path.join(tree, "host", "clause5-soak")
    if p.returncode != 0 or not os.path.exists(exe):
        print(f"  build of {label} failed (rc {p.returncode}): {(p.stdout + p.stderr)[-600:]}")
        return None
    return Tool(exe)


def copy_tree(src_root: str, dst: str) -> str:
    """A copy of host/ (and what its Makefile reads) in dst, mtimes kept, so a built tree stays built."""
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(os.path.join(src_root, "host"), os.path.join(dst, "host"), copy_function=shutil.copy2)
    return dst


# The integers each of cvtto32-all's four targets holds: i32, u32, i64, u64.
TARGET_RANGES = ((-2 ** 31, 2 ** 31 - 1), (0, 2 ** 32 - 1), (-2 ** 63, 2 ** 63 - 1), (0, 2 ** 64 - 1))


def round_to_integer(f: float, attr: str) -> int:
    """The integer an attribute rounds the finite value f to (f is an fp32 value, so exact in a double), by the rule of
    the attribute and nothing the tool does: rtz toward zero, rdn down, rup up, rne to nearest with ties to even, rmm to
    nearest with ties away from zero."""
    fl = math.floor(f)
    frac = f - fl                      # exact: a double holding an fp32 value, and a fraction only below 2^23
    if frac == 0:
        return fl
    if attr == "rtz":
        return fl if f > 0 else fl + 1
    if attr == "rdn":
        return fl
    if attr == "rup":
        return fl + 1
    if frac < 0.5:
        return fl
    if frac > 0.5:
        return fl + 1
    if attr == "rmm":
        return fl + 1 if f > 0 else fl
    return fl if fl % 2 == 0 else fl + 1


def expected_skipped_cvtto32(lo: int, hi: int, attr: str) -> int:
    """The number of (encoding, target) pairs of the slice [lo, hi) that cvtto32-all must SKIP, counted here and not by
    the tool: a pair is compared exactly when the integer the attribute rounds the operand to lies in the target's range,
    and NaNs and infinities are in no target's range. The driver cannot count this (it does not see the operands), so
    this is the independent check of the split between compared and skipped that `cases + skipped = 4 x E` leaves open."""
    skipped = 0
    for enc in range(lo, hi):
        f = struct.unpack("<f", struct.pack("<I", enc))[0]
        if math.isnan(f) or math.isinf(f):
            skipped += len(TARGET_RANGES)
            continue
        r = round_to_integer(f, attr)
        skipped += sum(1 for tmin, tmax in TARGET_RANGES if not tmin <= r <= tmax)
    return skipped


def judge(job, attr, k, exact, lo, hi, rc, out, m, label="", skips=True):
    """The checks every passing slice must meet: exit 0, no mismatches, the encodings the slice has, and the checks
    the mode promises (skipped is zero except where the mode skips). For cvtto32-all, which skips the pairs a target
    cannot hold, `skips` also holds the skipped count to expected_skipped_cvtto32's independent one."""
    if m is None:
        return False, f"no verdict line: rc {rc}: {out[-200:]}"
    cases, vm, fm, enc, skp = int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
    if (m.group(1), m.group(2)) != (job, attr or "rne"):
        return False, f"the verdict is for {m.group(1)} {m.group(2)}"
    if rc != 0 or vm or fm:
        return False, f"rc {rc}, {vm} value and {fm} flag mismatches: {out[:300]}"
    if enc != hi - lo:
        return False, f"{enc} encodings for a slice of {hi - lo}"
    if cases + skp != k * enc:
        return False, f"{cases} cases + {skp} skipped is not {k} x {enc}"
    if exact and skp != 0:
        return False, f"{skp} skipped in a mode that skips nothing"
    if job == "cvtto32-all" and skips:
        want = expected_skipped_cvtto32(lo, hi, attr or "rne")
        if skp != want:
            return False, (f"{skp} pairs skipped where the independent count of the pairs the targets cannot hold is {want} "
                           f"({cases} compared)")
    return True, ""


# ---------------------------------------------------------------------------------------------------
# the slices
# ---------------------------------------------------------------------------------------------------

def around(centre: int, before: int = 32, after: int = 32):
    return (centre - before, centre + after)


SIGN = 0x80000000
SPECIAL = [  # (what it is, lo, hi): at most 64 encodings each, so even the wide mode's 568 checks an encoding are quick
    ("+0 and the first subnormals", 0x00000000, 0x00000040),
    ("-0 and the first negative subnormals", SIGN, SIGN + 0x40),
    ("the top subnormals and the smallest normals", 0x007FFFE0, 0x00800020),
    ("the same, negative", SIGN + 0x007FFFE0, SIGN + 0x00800020),
    ("around 0.5", *around(0x3F000000)), ("around -0.5", *around(0xBF000000)),
    ("around 1.0", *around(0x3F800000)), ("around -1.0", *around(0xBF800000)),
    ("around 1.5", *around(0x3FC00000)), ("around -1.5", *around(0xBFC00000)),
    ("around 2.5 (a tie for ties-to-even and ties-away)", *around(0x40200000)),
    ("around 2^23 (the last fraction bit)", *around(0x4B000000)), ("around -2^23", *around(0xCB000000)),
    ("around 2^24", *around(0x4B800000)), ("around -2^24", *around(0xCB800000)),
    ("around 2^31 (the i32 limit)", *around(0x4F000000)), ("around -2^31 (the i32 minimum)", *around(0xCF000000)),
    ("around 2^32 (the u32 limit)", *around(0x4F800000)), ("around -2^32", *around(0xCF800000)),
    ("around 2^63 (the i64 limit)", *around(0x5F000000)), ("around -2^63", *around(0xDF000000)),
    ("around 2^64 (the u64 limit)", *around(0x5F800000)), ("around -2^64", *around(0xDF800000)),
    ("the largest normals and +infinity", 0x7F7FFFE0, 0x7F800020),
    ("the same, negative", SIGN + 0x7F7FFFE0, SIGN + 0x7F800020),
    ("signalling NaNs", 0x7F800001, 0x7F800041), ("negative signalling NaNs", SIGN + 0x7F800001, SIGN + 0x7F800041),
    ("signalling to quiet NaN", *around(0x7FC00000)), ("the same, negative", *around(SIGN + 0x7FC00000)),
    ("the top quiet NaNs", 0x7FFFFFE0, 0x80000000), ("the top negative quiet NaNs", 0xFFFFFFE0, 0x100000000),
    # as 32-bit integers (cvtfrom): the exactness edge of fp32, the i32 limits, and the extremes
    ("integers around 2^24 (fp32's exactness edge)", *around(0x01000000)),
    ("integers around 2^25 and 2^26", *around(0x02000000)), ("integers around 2^30", *around(0x40000000)),
    ("integers around 2^31 (i32 max and min)", *around(0x80000000)), ("integers around 2^32 - 1", 0xFFFFFFE0, 0x100000000),
    ("all-ones and small integers", 0xFFFFFFC0, 0x100000000),
]


def spread_slices(size: int):
    """Slices across the whole space: 64 evenly (offset so none is aligned), and 32 at random from a fixed seed."""
    even = [(i * (1 << 26) + 0x1234 + i * 977, i * (1 << 26) + 0x1234 + i * 977 + size) for i in range(64)]
    rnd = random.Random(20261019)
    drawn = []
    for _ in range(32):
        lo = rnd.randrange(0, (1 << 32) - size)
        drawn.append((lo, lo + size))
    return even + drawn


# ---------------------------------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------------------------------

def group_build(tool: Tool) -> None:
    rc, out, err = tool.raw("probe", "scalebrange")
    check("build: `probe scalebrange` finds the derived exponent range [-278, 277] holds on this libm "
          "(one exponent outside [-277, 276], values and flags, past either edge)",
          rc == 0 and "HOLDS" in out and "range [-278, 277] is one exponent outside [-277, 276]" in out, out[-300:])
    check("build: the probe measured the edges as the derivation says: lowest -277 for rne and -276 for the directed "
          "attributes, highest 276 for all", "lowest exponent that changes a result: rne -277, rtz -276, rdn -276, rup -276; "
          "highest: rne 276, rtz 276, rdn 276, rup 276" in out, out[:300])
    rc, out, err = tool.raw("probe", "scalbn")
    check("build: the older probes still run (scalbn: directed modes honoured on this host)", rc == 0 and "HONOURED" in out, out[:200])
    # The library's table also holds the divsqrt soak's wide modes (parcel HXc, 2026-10-26: k = 1 for the fp32 slices and the
    # windows), which this tool does not have, and this tool's own wide fp32-slice modes rint128-f32 and rint256-f32 (parcel HXb,
    # 2026-10-27: k = 1), which only its MPFR=1 build has and hw/test_c5_wide.py tests: both are left out here, and every clause-5
    # mode of the default build is still held to its entry.
    c5_per = {j: k for j, k in L.PER_ENCODING.items() if j not in L.WIDE_OPS and j not in L.WIDE_C5_OPS}
    check("build: the checks an encoding each mode promises here are the driver library's PER_ENCODING (what the driver holds "
          "a slice to)", {j: k for j, _a, k, _e in MODES} == c5_per, str(c5_per))


def group_special(tool: Tool) -> None:
    n = bad = 0
    t0 = time.time()
    for job, attr, k, exact in variants():
        for what, lo, hi in SPECIAL:
            rc, out, m = tool.run(job, lo, hi, attr)
            ok, why = judge(job, attr, k, exact, lo, hi, rc, out, m)
            n += 1
            if not ok:
                bad += 1
                check(f"special: {job} {attr or '-'} over {what} [{lo:#x}, {hi:#x})", False, why)
    check(f"special: {len(variants())} mode and attribute pairs over {len(SPECIAL)} special regions each: all {n} slices pass, "
          f"every count as promised", bad == 0, f"{bad} of {n} failed")
    print(f"      ({n} slices in {time.time() - t0:.0f} s)")
    # a few facts about particular regions, read off the logs
    rc, out, m = tool.run("cvtto32-all", 0x7FC00000, 0x7FC01000, "rne")
    check("special: cvtto32-all over 4096 quiet NaNs compares nothing and skips every pair (0 cases, 16384 skipped), and "
          "that is a pass", rc == 0 and m is not None and (int(m.group(3)), int(m.group(6)), int(m.group(7))) == (0, 4096, 16384), out[:200])
    rc, out, m = tool.run("cvtto32-all", 0x4EFFFFE0, 0x4F000020, "rtz")
    check("special: around 2^31 cvtto32-all skips the pairs the target cannot hold (some, not all) and compares the rest",
          rc == 0 and m is not None and 0 < int(m.group(7)) < 4 * 64 and int(m.group(3)) > 0, out[:200])
    rc, out, m = tool.run("scaleb32-wide", 0x00000001, 0x00000021, "rup")
    check("special: scaleb32-wide over the smallest subnormals under rup is 568 checks an encoding with the witnesses past "
          "both edges among them", rc == 0 and m is not None and int(m.group(3)) == 568 * 32, out[:200])


def group_spread(tool: Tool) -> None:
    t0 = time.time()
    n = bad = 0
    for job, attr, k, exact in variants():
        size = 64 if job == "scaleb32-wide" else 512
        for lo, hi in spread_slices(size):
            rc, out, m = tool.run(job, lo, hi, attr)
            ok, why = judge(job, attr, k, exact, lo, hi, rc, out, m)
            n += 1
            if not ok:
                bad += 1
                check(f"spread: {job} {attr or '-'} [{lo:#x}, {hi:#x})", False, why)
    check(f"spread: {len(variants())} mode and attribute pairs over 96 slices across the whole space (64 even, 32 drawn from a fixed "
          f"seed): all {n} pass, every count as promised", bad == 0, f"{bad} of {n} failed")
    print(f"      ({n} slices in {time.time() - t0:.0f} s)")


def group_refuse(tool: Tool) -> None:
    for what, args in (("an empty range", ("conv32to64-all", 5, 5)), ("a reversed range", ("conv32to64-all", 9, 5)),
                       ("a range past 2^32", ("conv32to64-all", 0, 0x100000001)), ("a start at 2^32", ("conv32to64-all", 0x100000000, 0x100000001)),
                       ("a negative start", ("conv32to64-all", -1, 5)), ("garbage for a start", ("conv32to64-all", "abc", 5)),
                       ("garbage for an end", ("scaleb32-all", 0, "12x", "rne")), ("an empty bound", ("cvtto32-all", "", 5, "rne"))):
        rc, out, err = tool.raw(*args)
        check(f"refuse: {what} is refused by name, exit 2, and runs nothing",
              rc == 2 and ("need 0 <= lo < hi <= 2^32" in err or "usage" in err.lower()) and " cases," not in out, f"rc {rc}: {err[-200:]}")
    for what, args in (("rmm for scaleb32-all", ("scaleb32-all", 0, 64, "rmm")), ("rmm for scaleb32-wide", ("scaleb32-wide", 0, 64, "rmm")),
                       ("rmm for cvtfrom32-all", ("cvtfrom32-all", 0, 64, "rmm")), ("rmm for cvtfrom64-all", ("cvtfrom64-all", 0, 64, "rmm")),
                       ("an attribute that does not exist", ("cvtto32-all", 0, 64, "rtx")),
                       ("a mode word for conv32to64-all", ("conv32to64-all", 0, 64, "rne")),
                       ("no mode word for cvtto32-all", ("cvtto32-all", 0, 64))):
        rc, out, err = tool.raw(*args)
        check(f"refuse: {what} is refused, exit 2, and runs nothing", rc == 2 and " cases," not in out, f"rc {rc}: {(out + err)[-200:]}")
    rc, out, err = tool.raw("cvtto32-all", 0, 64, "rmm")
    check("refuse: rmm IS accepted by cvtto32-all (its oracle, llroundf, is ties-away by definition)", rc == 0 and "cvtto32-all rmm:" in out, out[:200])


def group_sabotage(tool: Tool) -> None:
    for job, attr, k, exact in variants():
        lo, hi = (0x3F800000, 0x3F800040) if job != "cvtfrom32-all" and job != "cvtfrom64-all" else (0x00001000, 0x00001040)
        rc0, out0, m0 = tool.run(job, lo, hi, attr)
        rc, out, m = tool.run(job, lo, hi, attr, env={"CFT_SOAK_SABOTAGE": "1"})
        vm = int(m.group(4)) if m else 0
        named = re.findall(r"^  MISMATCH \S+ \S+ a=0x([0-9a-f]+)", out, re.M)
        inside = all(lo <= int(a, 16) < hi for a in named)
        check(f"sabotage: {job} {attr or '-'}: CFT_SOAK_SABOTAGE=1 fails (exit 1, value mismatches, operands named inside the "
              f"slice) and the same slice passes without it", rc0 == 0 and rc == 1 and vm > 0 and named and inside,
              f"clean rc {rc0}; sabotaged rc {rc}, {vm} mismatches, named {named[:3]}")


# --- the plants ------------------------------------------------------------------------------------

PLANT_HELPER = '''
/* PLANT (a test's, never the library's): flip the low bit of the result of every lane whose input encoding is
 * CFT_PLANT_OPERAND, and - for scaleB - whose exponent is CFT_PLANT_NEXP when that is set. */
static int plant_hit(uint64_t in)
{
    const char *p = getenv("CFT_PLANT_OPERAND");
    return p && strtoull(p, NULL, 0) == in;
}
'''
PLANT_CONVERT = '''    for (i = 0; i < n; i++) {
        uint32_t in32;
        if (fs->width == 32) {
            memcpy(&in32, (const uint8_t *)a + i * 4, 4);
            if (plant_hit(in32))
                ((uint8_t *)d)[i * (size_t)(fd->width / 8)] ^= 1u;
        }
    }
'''
PLANT_FROM = '''    for (i = 0; i < n; i++) {
        uint32_t in32;
        if (elem_sz == 4) {
            memcpy(&in32, (const uint8_t *)src + i * 4, 4);
            if (plant_hit(in32))
                ((uint8_t *)d)[i * (size_t)(f->width / 8)] ^= 1u;
        }
    }
'''
PLANT_TO = '''    for (i = 0; i < n; i++) {
        uint32_t in32;
        if (f->width == 32) {
            memcpy(&in32, (const uint8_t *)a + i * 4, 4);
            if (plant_hit(in32))
                ((uint8_t *)dst)[i * (size_t)elem_sz] ^= 1u;
        }
    }
'''
PLANT_SCALEB_WRAPPER = '''
CFT_API cft_status cft_scaleb(cft_device *dev, cft_format fmt, cft_round rnd,
                              const void *a, int64_t nexp, void *d, size_t n,
                              uint32_t *flags_out, uint32_t *bus_out)
{
    cft_status st = scaleb_real(dev, fmt, rnd, a, nexp, d, n, flags_out, bus_out);
    size_t i;
    if (st == CFT_OK && fmt == CFT_FP32) {
        const char *pn = getenv("CFT_PLANT_NEXP");
        for (i = 0; i < n; i++) {
            uint32_t in32;
            memcpy(&in32, (const uint8_t *)a + i * 4, 4);
            if (plant_hit(in32) && (!pn || strtoll(pn, NULL, 0) == nexp))
                ((uint8_t *)d)[i * 4] ^= 1u;
        }
    }
    return st;
}
'''


def patch_once(path: str, old: str, new: str, what: str) -> None:
    """Replace `old` by `new` in a file, which must contain it exactly once: a plant that did not apply proves nothing."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    if text.count(old) != 1:
        raise SystemExit(f"plant {what}: {old[:70]!r} found {text.count(old)} times in {os.path.basename(path)}; "
                         f"the plant did not apply, so it would prove nothing")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace(old, new))


def plant_library(built_tree: str, work: str):
    """A copy of the built tree whose library has the one-operand fault, rebuilt: its Tool."""
    tree = copy_tree(built_tree, os.path.join(work, "plant-lib"))
    c5 = os.path.join(tree, "host", "src", "clause5.c")
    patch_once(c5, "#define CHUNK ((size_t)CFT_CHUNK)\n", "#define CHUNK ((size_t)CFT_CHUNK)\n" + PLANT_HELPER, "library: helper")
    patch_once(c5, "        lane_store(fd, (uint8_t *)d, i, &v);\n    }\n", "        lane_store(fd, (uint8_t *)d, i, &v);\n    }\n"
               + PLANT_CONVERT, "library: cft_convert")
    patch_once(c5, "    }\n    cft_flags_emit(dev, acc, flags_out);\n    return CFT_OK;\n}\n\nCFT_API cft_status cft_cvt_from_i32(",
               "    }\n" + PLANT_FROM + "    cft_flags_emit(dev, acc, flags_out);\n    return CFT_OK;\n}\n\nCFT_API cft_status cft_cvt_from_i32(",
               "library: cvt_from_core")
    patch_once(c5, "    }\n    cft_flags_emit(dev, acc, flags_out);\n    return CFT_OK;\n}\n\nCFT_API cft_status cft_cvt_to_i32(",
               "    }\n" + PLANT_TO + "    cft_flags_emit(dev, acc, flags_out);\n    return CFT_OK;\n}\n\nCFT_API cft_status cft_cvt_to_i32(",
               "library: cvt_to_core")
    patch_once(c5, "CFT_API cft_status cft_scaleb(cft_device *dev, cft_format fmt, cft_round rnd,\n"
                   "                              const void *a, int64_t nexp, void *d, size_t n,\n"
                   "                              uint32_t *flags_out, uint32_t *bus_out)\n{",
               "static cft_status scaleb_real(cft_device *dev, cft_format fmt, cft_round rnd,\n"
               "                              const void *a, int64_t nexp, void *d, size_t n,\n"
               "                              uint32_t *flags_out, uint32_t *bus_out)\n{", "library: cft_scaleb")
    patch_once(c5, "\n/* ---- signaling comparisons: composed ------------------------------ */\n",
               PLANT_SCALEB_WRAPPER + "\n/* ---- signaling comparisons: composed ------------------------------ */\n", "library: the scaleb wrapper")
    return build(tree, "the library plant")


def plant_tool(built_tree: str, work: str, name: str, edits: list):
    """A copy of the built tree whose clause5_soak.c has the edits (each applied exactly once), rebuilt: its Tool."""
    tree = copy_tree(built_tree, os.path.join(work, "plant-" + name))
    src = os.path.join(tree, "host", "tools", "clause5_soak.c")
    for old, new in edits:
        patch_once(src, old, new, name)
    return build(tree, name)


def group_plants(tool: Tool, built_tree: str, work: str) -> None:
    # (a) a library result changed for ONE operand
    lib = plant_library(built_tree, work)
    if lib is None:
        check("plants: the library plant builds", False, "make failed")
        return
    OP, SLO, SHI = 0x3F800005, 0x3F800000, 0x3F800100
    IOP, ILO, IHI = 0x00001005, 0x00001000, 0x00001100
    for job, attr, lo, hi, op, vm_min in (("conv32to64-all", None, SLO, SHI, OP, 1), ("cvtto32-all", "rne", SLO, SHI, OP, 8),
                                          ("cvtfrom32-all", "rne", ILO, IHI, IOP, 2), ("cvtfrom64-all", "rne", ILO, IHI, IOP, 2),
                                          ("scaleb32-all", "rne", SLO, SHI, OP, 17), ("scaleb32-wide", "rne", SLO, SHI, OP, 568)):
        k = dict((j, kk) for j, _a, kk, _e in MODES)[job]
        exact = dict((j, e) for j, _a, _k, e in MODES)[job]
        rc, out, m = lib.run(job, lo, hi, attr)
        ok, why = judge(job, attr, k, exact, lo, hi, rc, out, m)
        check(f"plant (library) CONTROL: the plant build passes {job} with the fault switched off", ok, why)
        rc, out, m = lib.run(job, lo, hi, attr, env={"CFT_PLANT_OPERAND": hex(op)})
        named = re.findall(r"^  MISMATCH \S+ \S+ a=0x([0-9a-f]+)", out, re.M)
        vm = int(m.group(4)) if m else 0
        check(f"plant (library): {job}: one operand's result changed in the library, and the soak goes red (exit 1, "
              f"{vm_min} or more mismatches) naming that operand and no other",
              rc == 1 and vm >= vm_min and named and all(int(a, 16) == op for a in named), f"rc {rc}, {vm} mismatches, named {named[:3]}")
    rc, out, m = lib.run("scaleb32-all", SLO, SHI, "rne", env={"CFT_PLANT_OPERAND": hex(OP), "CFT_PLANT_NEXP": "-149"})
    named = re.findall(r"^  MISMATCH scaleb32 rne a=0x([0-9a-f]+) b=0x([0-9a-f]+)", out, re.M)
    check("plant (library): scaleb32-all: a fault at one operand and ONE exponent names both (a=the operand, b=-149)",
          rc == 1 and m is not None and int(m.group(4)) == 1 and named == [("%016x" % OP, "%016x" % (-149 & (2 ** 64 - 1)))], f"{named}")
    rc, out, m = lib.run("scaleb32-wide", SLO, SHI, "rne", env={"CFT_PLANT_OPERAND": hex(OP), "CFT_PLANT_NEXP": "-279"})
    named = re.findall(r"^  MISMATCH (\S+) rne a=0x([0-9a-f]+) b=0x([0-9a-f]+)", out, re.M)
    check("plant (library): scaleb32-wide: a fault in the library at an exponent PAST the range's edge (-279) is caught "
          "by the witnesses past the edges, as a 'scaleb32-beyond' mismatch naming the operand and the exponent",
          rc == 1 and m is not None and int(m.group(4)) == 1 and named == [("scaleb32-beyond", "%016x" % OP, "%016x" % (-279 & (2 ** 64 - 1)))],
          f"{named}")
    # (b) the oracle given the wrong attribute: the table's own lines, as the source has them, each given another
    # attribute's rounding mode (the library is still asked for the right one)
    table = [('    { "rne", CFT_RNE, FE_TONEAREST  },', '    { "rne", CFT_RNE, FE_TOWARDZERO },'),
             ('    { "rtz", CFT_RTZ, FE_TOWARDZERO },', '    { "rtz", CFT_RTZ, FE_UPWARD     },'),
             ('    { "rdn", CFT_RDN, FE_DOWNWARD   },', '    { "rdn", CFT_RDN, FE_UPWARD     },'),
             ('    { "rup", CFT_RUP, FE_UPWARD     },', '    { "rup", CFT_RUP, FE_DOWNWARD   },')]
    wo = plant_tool(built_tree, work, "oracle", table)
    if wo is None:
        check("plants: the wrong-attribute build builds", False, "make failed")
    else:
        # slices where the rounding mode shows: fractions (cvtto32-all), inexact integers (cvtfrom32-all), subnormal
        # results (scaleb); in both signs
        shows = {"cvtto32-all": [(0x3FBFFFC0, 0x3FC00040), (0xBFBFFFC0, 0xBFC00040)],
                 "cvtfrom32-all": [(0x01000000 - 32, 0x01000000 + 32), (0xFEFFFFE0, 0xFF000020)],
                 "scaleb32-all": [(0x3F800000, 0x3F800040), (0xBF800000, 0xBF800040)],
                 "scaleb32-wide": [(0x3F800000, 0x3F800010), (0xBF800000, 0xBF800010)]}
        for job, attrs, k, exact in MODES:
            if job not in shows:
                continue
            for attr in attrs:
                if attr == "rmm":
                    continue
                vm_good = sum(int(wo_m.group(4)) for wo_m in (tool.run(job, lo, hi, attr)[2] for lo, hi in shows[job]) if wo_m)
                runs = [wo.run(job, lo, hi, attr) for lo, hi in shows[job]]
                vm = sum(int(m.group(4)) for _rc, _out, m in runs if m)
                named = [a for _rc, out, _m in runs for a in re.findall(r"^  MISMATCH \S+ \S+ a=0x([0-9a-f]+)", out, re.M)]
                check(f"plant (oracle): {job} {attr}: the oracle given another attribute's rounding mode is caught - the same "
                      f"slices pass with the right one, and fail with the wrong one, operands named",
                      vm_good == 0 and vm > 0 and all(r[0] == 1 for r in runs if r[2] and int(r[2].group(4))) and bool(named),
                      f"right oracle {vm_good} mismatches, wrong oracle {vm}")
        rc, out, m = tool.run("cvtfrom64-all", 0x01000000 - 32, 0x01000000 + 32, "rup")
        rc2, out2, m2 = wo.run("cvtfrom64-all", 0x01000000 - 32, 0x01000000 + 32, "rup")
        check("plant (oracle): cvtfrom64-all cannot be caught by the wrong attribute and says so: converting a 32-bit integer to "
              "fp64 is exact, so every rounding mode gives the same result (a limit, stated, not a defect)",
              rc == 0 and rc2 == 0 and m2 is not None and int(m2.group(4)) == 0, out2[:200])
    rm = plant_tool(built_tree, work, "rmm", [("llround(u2d(A64[i]))", "llrint(u2d(A64[i]))"),
                                               ("llroundf(u2f(A32[i]))", "llrintf(u2f(A32[i]))")])
    if rm is not None:
        a0 = tool.run("cvtto32-all", 0x401FFFC0, 0x40200040, "rmm")
        a1 = rm.run("cvtto32-all", 0x401FFFC0, 0x40200040, "rmm")
        check("plant (oracle): cvtto32-all rmm: ties-away's oracle replaced by ties-even's is caught at the ties (2.5 -> 3 against 2)",
              a0[0] == 0 and a1[0] == 1 and a1[2] is not None and int(a1[2].group(4)) > 0, a1[1][:200])
    # (c) the exponent range wrong by one on either side
    for what, old, new, op, lo, hi, expect_b in (("the low edge too narrow by one (-277)", "#define WIDE_LO (-278)", "#define WIDE_LO (-277)",
                                                  0x7F400000, 0x7F400000, 0x7F400010, -279),
                                                 ("the high edge too narrow by one (276)", "#define WIDE_HI 277", "#define WIDE_HI 276",
                                                  0x00000001, 0x00000001, 0x00000011, 278)):
        wr = plant_tool(built_tree, work, "range-lo" if "LO" in old else "range-hi", [(old, new)])
        if wr is None:
            check(f"plants: the range plant ({what}) builds", False, "make failed")
            continue
        rc, out, m = wr.run("scaleb32-wide", lo, hi, "rne")
        named = re.findall(r"^  MISMATCH scaleb32-beyond rne a=0x([0-9a-f]+) b=0x([0-9a-f]+)", out, re.M)
        check(f"plant (range): {what}: the witnesses past the edge fail against the edge's oracle value, naming the operand and an "
              f"exponent past the edge", rc == 1 and bool(named) and any(int(b, 16) == expect_b & (2 ** 64 - 1) for _a, b in named), f"{named[:3]}")
        rc, out, err = wr.raw("probe", "scalebrange")
        check(f"plant (range): {what}: `probe scalebrange` says the range DOES NOT HOLD (exit 1)", rc == 1 and "DOES NOT HOLD" in out, out[-200:])
    # (d) the tool counting one encoding too few
    wc = plant_tool(built_tree, work, "count", [("        if (conv32to64_batch(A, n))\n            return 1;\n        encodings += n;",
                                                  "        if (conv32to64_batch(A, n))\n            return 1;\n        encodings += n - 1;")])
    if wc is not None:
        rc, out, m = wc.run("conv32to64-all", 0x3F800000, 0x3F801000)
        ok, why = judge("conv32to64-all", None, 1, True, 0x3F800000, 0x3F801000, rc, out, m)
        check("plant (count): a tool that counts one encoding too few in its batch loop is caught by the checks every slice must "
              "meet (the encodings are the slice's)", not ok and "encodings for a slice of" in why, why)
    # (e) cvtto32-all's u32 skip filter too eager: lanes the target CAN hold are counted as skipped instead of compared. The tool
    # still prints E encodings and cases + skipped = 4 x E, no mismatch and exit 0 - so everything the driver's parse_soak can
    # check passes - and only the independent count of the pairs the targets cannot hold sees it.
    wf = plant_tool(built_tree, work, "skipfilter", [("} else if (r < 0 || r > (long long)UINT32_MAX) {",
                                                        "} else if (r < 0 || r >= (long long)INT32_MAX) {")])
    if wf is None:
        check("plants: the skip-filter plant builds", False, "make failed")
    else:
        flo, fhi = 0x4EFFFFC0, 0x4F000040          # 64 encodings below 2^31, 64 from 2^31 up
        rc0, out0, m0 = tool.run("cvtto32-all", flo, fhi, "rne")
        ok0, why0 = judge("cvtto32-all", "rne", 4, False, flo, fhi, rc0, out0, m0)
        check("plant (skip filter) CONTROL: the real tool passes the slice around 2^31, the independent skip count included",
              ok0, why0)
        rc, out, m = wf.run("cvtto32-all", flo, fhi, "rne")
        ok_blind, why_blind = judge("cvtto32-all", "rne", 4, False, flo, fhi, rc, out, m, skips=False)
        ok_full, why_full = judge("cvtto32-all", "rne", 4, False, flo, fhi, rc, out, m)
        check("plant (skip filter): a u32 skip filter that is too eager passes every check but the independent count (exit 0, "
              "no mismatch, E encodings, cases + skipped = 4 x E): the driver's parse_soak could not see it", ok_blind, why_blind)
        check("plant (skip filter): and the independent count of the pairs the targets cannot hold catches it (64 lanes the u32 "
              "target holds were counted as skipped)", not ok_full and "independent count" in why_full
              and m is not None and int(m.group(7)) == expected_skipped_cvtto32(flo, fhi, "rne") + 64, why_full)


def group_unchanged(tool: Tool, base_dir: str, work: str) -> None:
    rev = os.path.basename(os.path.normpath(base_dir))
    base = copy_tree(base_dir, os.path.join(work, "baseline"))
    old = build(base, f"the baseline {rev}")
    if old is None:
        check(f"unchanged: the baseline {rev} builds", False, "make failed")
        return
    n = same = 0
    cases = []
    for seed in (1, 77):
        for m in ("rne", "rtz", "rdn", "rup", "rmm"):
            cases += [("cvtto32", 200000, seed, m), ("cvtto64", 200000, seed, m), ("rint64", 200000, seed, m)]
        for m in ("rne", "rtz", "rdn", "rup"):
            cases += [("cvtfrom32", 200000, seed, m), ("cvtfrom64", 200000, seed, m), ("scaleb32", 200000, seed, m),
                      ("scaleb64", 200000, seed, m), ("conv64to32", 200000, seed, m)]
        cases += [("conv32to64", 200000, seed, None), ("rem32", 200000, seed, None), ("rem64", 200000, seed, None),
                  ("nextup64", 200000, seed, None), ("class64", 200000, seed, None)]
    cases += [("conv32to64", c, 5, None) for c in (1, 4095, 4097)] + [("scaleb32", 12289, 5, "rdn"), ("cvtto32", 12289, 5, "rup")]
    for job, count, seed, attr in cases:
        a = ([job, str(count), str(seed)] + ([attr] if attr else []))
        outs = []
        for t in (old, tool):
            pr = subprocess.run(NICE + [t.path] + a, capture_output=True, text=True, timeout=600)
            outs.append((pr.returncode, pr.stdout, pr.stderr))
        n += 1
        if outs[0] == outs[1]:
            same += 1
        else:
            check(f"unchanged: {' '.join(a)} prints the same bytes and exits the same", False, f"{outs[0][0]} vs {outs[1][0]}")
    for env in ({"CFT_SOAK_SABOTAGE": "1"},):
        for job, attr in (("cvtto32", "rne"), ("cvtfrom32", "rup"), ("scaleb32", "rne"), ("conv32to64", None)):
            a = [job, "100000", "3"] + ([attr] if attr else [])
            outs = []
            for t in (old, tool):
                e = dict(os.environ)
                e.update(env)
                pr = subprocess.run(NICE + [t.path] + a, capture_output=True, text=True, timeout=600, env=e)
                outs.append((pr.returncode, pr.stdout, pr.stderr))
            n += 1
            same += outs[0] == outs[1]
            if outs[0] != outs[1]:
                check(f"unchanged (sabotaged): {' '.join(a)}", False, "differs")
    check(f"unchanged: {n} invocations of the random modes ({rev}'s tool and this tree's): the same stdout, stderr and exit status "
          f"for all {same} that agree", same == n, f"{n - same} differ")
    print(f"      ({n} invocations compared, {same} identical)")


# ---------------------------------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    rev = args[args.index("--baseline-tree") + 1] if "--baseline-tree" in args else None
    keep = "--keep" in args

    def want(g: str) -> bool:
        return only is None or g in only

    if os.name != "posix" or not shutil.which("make") or not (shutil.which("cc") or shutil.which("gcc")):
        skip("c5-exhaustive", "needs POSIX with make and a C compiler (the soak requires a 64-bit Linux)")
        print(f"c5-exhaustive test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped")
        return 0
    work = tempfile.mkdtemp(prefix="c5-exh-test-")
    t0 = time.time()
    try:
        tree = copy_tree(ROOT, os.path.join(work, "tree"))
        tool = build(tree, "this tree")
        if tool is None:
            check("build: clause5-soak builds in a scratch copy of host/", False, "make failed")
        else:
            for name, fn in (("build", lambda: group_build(tool)), ("special", lambda: group_special(tool)),
                             ("spread", lambda: group_spread(tool)), ("refuse", lambda: group_refuse(tool)),
                             ("sabotage", lambda: group_sabotage(tool)),
                             ("plants", lambda: group_plants(tool, tree, work))):
                if want(name):
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
    print(f"c5-exhaustive test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
