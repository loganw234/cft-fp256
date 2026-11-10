#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Test of routine-sweep (host/tools/routine_sweep.c, parcel M4X), its oracle header (host/tools/mpfr_tfn.h) and its image generator
(host/tools/gen_sweep_images.py), on the software backend. POSIX with make, a C compiler and MPFR and GMP to link (the system's:
WSL cft2204's MPFR 4.1.0 and GMP 6.2.1, on which mpfr_tfn.h builds for the thirteen routines); python3 with mpmath and pytest, which
python/tests/mathlib_harness.py needs. Skipped by name without any of them. The model is hw/test_c5_wide.py.

    python3 hw/test_routine_sweep.py [--only GROUP,...] [--names exp,sin] [--slice-bits 16] [--rate-lanes 262144]
                                     [--baseline-tree DIR] [--keep]

It builds the tool in a scratch copy of host/ (make routine-sweep positive-run) and its images with the generator, and runs, niced,
one process at a time:
  build     the tool builds with no warning (CONTROL: without the `#pragma GCC diagnostic` lines around mpfr_tfn.h it warns of
            unused functions, so the pragma takes a real warning away); `list` names the thirteen, nine with a digest and four
            `no image`, the digests the generator's manifest gives
  images    the generator is deterministic (twice into two directories: every file equal); each of the nine's image and bank run
            through positive-run deposit mathlib.evaluate's bits (and routines.run's) on 200 lanes under rne and 32 under each other
            attribute
  oracle    `routine-sweep oracle` against transcend.compute, bits and flags, for ALL THIRTEEN under all five attributes over the
            fp32 pools (mathlib_harness.pools and edge_pool, transcend_check's unary_pool, trig_pool and radian_pool) and the
            special classes (zeros, infinities, quiet and signalling NaNs, the subnormal and normal ends, +-1, the neighbours of
            every power of two from 2^-149 to 2^127, exp's and exp2's overflow and underflow edges, exp2's tie at emin - p, log1p's
            and expm1's -1 edges), and atan2 over the nine x of M4X's list against the pools' y
  agree     for each of the nine and each attribute, two 256-lane slices: the tool passes them, and every unmarked lane's
            mathlib.evaluate answer is the oracle's (so a lane the tool calls right is the fragment's own), and the tool's marks
            are evaluate's
  marks     exp's five marking lanes under each attribute (0, 5, 5, 5, 0 over slices that hold them, none off the list, no guess
            wrong); and at volume, images built with --bound-shift 34 (G' = 6): the tool's marks and wrong guesses over a 2^14
            slice equal Python's count over the same lanes
  whole     each of the nine under `all` over four slices of 2^slice-bits (16): around 1, in the tiny range, large, negative -
            E the slice, cases = 5 E, nothing skipped, and L.parse_soak accepting it with cover {E, per_encoding 5}; each single
            attribute over one slice
  fast      CFT_SWEEP_ORACLE_CHECK=1 over the first 2^13 lanes of those slices: no difference between the fast path and
            ieee_tfn_oracle; CONTROL: a fast path that rounds rup as rtz is red
  refuse    an empty, reversed, past-2^32, negative or non-numeric range; a missing, a bad attribute; an unknown name, a name with
            no image; a bad x; a digest that is not the images'; a truncated image, a truncated bank, a missing marks file: each
            exit 2 and nothing run
  sabotage  CFT_SOAK_SABOTAGE=1, =2 and =3 exit 1 and name what they should, on the nine (=3 on images with marks: --bound-shift 34); the same
            slice passes without
  plants    each built by the generator or a patch of the scratch copy, red where it says, its control green: exp table_entry (value
            mismatches), sin inf_flag_dropped (flag mismatches, no value mismatch), log1p pminn_dropped under rtz (flag mismatches),
            exp mark_silenced under rtz (flag mismatches by the .marks list and no value mismatch), raw_tfn given the wrong attribute
            (value mismatches), the tool stopping one lane early (parse_soak's cover rule refuses it)
  unchanged (with --baseline-tree DIR, a directory holding the baseline's host/; needs MPFR 4.2) mpfr-check's output for
            CFT_MPFR_PHASES=transcend,trig,radian,table91 CFT_MPFR_FORMATS=fp32 `mpfr-check 24 7` is the baseline's, byte for byte, its
            first (version) line apart. Skipped by name on MPFR 4.1.
  rate      no assertion: each of the nine under `all` over --rate-lanes (2^18) lanes on the software backend: the `device s`,
            `oracle s` line and lanes a second
  legs      the judges this file uses, each leg of each failing alone on doctored input, and green on the real one

Prints one line a group and a last line "routine-sweep test: N checks, F failed, S skipped".
"""
from __future__ import annotations

import filecmp
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
sys.path.insert(0, os.path.join(ROOT, "python", "tests"))
sys.path.insert(0, os.path.join(ROOT, "host", "tests"))
import card_stress_lib as L  # noqa: E402
import test_c5_exhaustive as X  # noqa: E402  (copy_tree, patch_once, NICE)

CHECKS = 0
FAILS: list = []
SKIPS: list = []
NICE = X.NICE
ATTRS = ("rne", "rtz", "rdn", "rup", "rmm")
NINE = ("exp", "exp2", "expm1", "log", "log2", "log1p", "sin", "cos", "tan")
THIRTEEN = NINE + ("atan", "asin", "acos", "atan2")
# the nine x of M4X's brief (item 8): 1, -1, 1 + ulp, 2^40, the largest normal, the smallest normal, a subnormal, two full significands
X9 = (0x3f800000, 0xbf800000, 0x3f800001, 0x53800000, 0x7f7fffff, 0x00800000, 0x00000003, 0x3fb504f3, 0xc0490fdb)
MARKS_LINE = re.compile(r"^(\S+) (\S+): (\d+) marked \(rne (\S+), rtz (\S+), rdn (\S+), rup (\S+), rmm (\S+)\), (\d+) off the list, "
                        r"(\d+) guesses wrong$", re.M)
FIVE = (0x33ffffff, 0x347ffffe, 0x34fffffc, 0xb4800001, 0xb5000002)    # exp's marking lanes under rtz, rdn and rup
PRAGMAS = ('#pragma GCC diagnostic push\n', '#pragma GCC diagnostic ignored "-Wunused-function"\n',
           '#pragma GCC diagnostic ignored "-Wunused-variable"\n', '#pragma GCC diagnostic ignored "-Wunused-const-variable"\n',
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


class Sweep:
    """A built routine-sweep and the images directory it reads."""

    def __init__(self, path: str, imgs: str):
        self.path, self.imgs = path, imgs

    def raw(self, *args, env=None, imgs=None, stdin=None, timeout: int = 900):
        e = dict(os.environ)
        e.pop("CFT_SOAK_ARTIFACT", None)                 # an agent's run never names a card
        e["CFT_SWEEP_IMAGES"] = imgs or self.imgs
        e.update(env or {})
        p = subprocess.run(NICE + [self.path] + [str(a) for a in args], capture_output=True, text=True, timeout=timeout, env=e,
                           input=stdin)
        return p.returncode, p.stdout, p.stderr

    def run(self, op, lo, hi, mode, **kw):
        """(rc, stdout + stderr, the verdict match or None)."""
        rc, out, err = self.raw(op, lo, hi, mode, **kw)
        return rc, out + err, L.SOAK_LINE.search(out)


def judge_run(rc, text, op, mode, lo, hi, k):
    """What every passing slice must meet: exit 0; the one verdict, for this op and mode; no value or flag mismatch; E the slice;
    cases = k E; nothing skipped; no disagreement line; L.parse_soak accepting it, unedited, under its cover rule."""
    ms = list(L.SOAK_LINE.finditer(text))
    if len(ms) != 1:
        return False, f"{len(ms)} verdict lines: rc {rc}: {text[-200:]}"
    m = ms[0]
    cases, vm, fm, enc, skp = int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
    if (m.group(1), m.group(2)) != (op, mode):
        return False, f"the verdict is for {m.group(1)} {m.group(2)}"
    if rc != 0:
        return False, f"rc {rc}: {text[:300]}"
    if vm or fm or L.SOAK_DISAGREE.search(text):
        return False, f"{vm} value and {fm} flag mismatches: {text[:300]}"
    if enc != hi - lo or cases != k * enc or skp != 0:
        return False, f"{cases} cases, {enc} encodings, {skp} skipped for a slice of {hi - lo} at k = {k}"
    try:
        v = L.parse_soak(text, rc, op, mode, None, k * (hi - lo), {"encodings": hi - lo, "per_encoding": k})
    except L.VerdictError as ex:
        return False, f"refused by parse_soak: {ex}"
    return (True, "") if v.ok else (False, "parse_soak says it failed")


def marks_of(text):
    """(M, [rne..rmm as ints or None], O, W) from the marks line."""
    m = MARKS_LINE.search(text)
    if not m:
        return None
    cols = [None if g == "-" else int(g) for g in m.group(4, 5, 6, 7, 8)]
    return int(m.group(3)), cols, int(m.group(9)), int(m.group(10))


def counts(m):
    return int(m.group(3)), int(m.group(4)), int(m.group(5))


def have_mpmath() -> bool:
    try:
        import mpmath  # noqa: F401
        import pytest  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


def mods():
    from cft_golden import FP32, mathlib as ml, routines, softfloat as sf, transcend as T
    import mathlib_harness as har
    return FP32, ml, routines, sf, T, har


def gen(outdir, *args):
    p = subprocess.run(NICE + [sys.executable, "-B", os.path.join(ROOT, "host", "tools", "gen_sweep_images.py"), "--out", outdir]
                       + list(args), capture_output=True, text=True, timeout=900)
    return p.returncode, p.stdout + p.stderr


def gen_account(manifest):
    """The generator's own account of what it built (send-back 1 of parcel M4X2): (BUILT, SKIPPED) - BUILT the (name, digest) of each `digest` line, in the order
    written, SKIPPED the names of its `skipped <name> not built at fp32` lines. The test follows these, so that a routine built later (parcel M4F1's atan) breaks
    no figure here; what must stay true is held by account_problems."""
    return (re.findall(r"^digest (\w+) ([0-9a-f]{8})$", manifest, re.M), re.findall(r"^skipped (\w+) not built at fp32$", manifest, re.M))


def account_problems(built, skipped):
    """What is wrong with a generator's account: BUILT and SKIPPED must be disjoint, a name once each, and together the tool's thirteen, BUILT in the tool's order."""
    names = [n for n, _ in built]
    p = []
    if len(set(names)) != len(names) or len(set(skipped)) != len(skipped):
        p.append("a name twice")
    if set(names) & set(skipped):
        p.append(f"both built and skipped: {sorted(set(names) & set(skipped))}")
    if [n for n in THIRTEEN if n not in names and n not in skipped]:
        p.append(f"neither built nor skipped: {[n for n in THIRTEEN if n not in names and n not in skipped]}")
    if [n for n in names + list(skipped) if n not in THIRTEEN]:
        p.append("a name that is not one of the thirteen")
    if names != [n for n in THIRTEEN if n in names]:
        p.append("built names not in the tool's order")
    return p


def digest_judge(built, table):
    """The build step's rule (hw/card_stress.py, `routine images`): every row of the table must be among the built names with an equal digest, in the table's
    order - a row the generator skipped, or whose digest differs, fails by name (so does a table whose order is not the generator's); a built name with no row is NAMED
    and does not fail. Returns (failures, named)."""
    d = dict(built)
    fails = []
    for n, dg in table.items():
        if n not in d:
            fails.append(f"{n}: no digest line (skipped, or not built)")
        elif d[n] != dg:
            fails.append(f"{n}: the generator's digest is {d[n]}, the table's {dg}")
    if not fails and [n for n, _ in built if n in table] != list(table):
        fails.append("the table's order is not the generator's")
    return fails, [n for n, _ in built if n not in table]


def build_tool(tree: str, label: str, targets=("routine-sweep",)):
    """make in tree/host: (log, rc)."""
    p = subprocess.run(NICE + ["make", "-C", os.path.join(tree, "host"), "-j4"] + list(targets), capture_output=True, text=True,
                       timeout=900)
    return p.stdout + p.stderr, p.returncode


def plant_tool(built_tree: str, work: str, name: str, edits: list):
    """A copy of the built tree with each (file under host/, old, new) edit applied exactly once, rebuilt: its Sweep path or None."""
    tree = X.copy_tree(built_tree, os.path.join(work, "plant-" + name))
    for rel, old, new in edits:
        X.patch_once(os.path.join(tree, "host", *rel.split("/")), old, new, name)
    log, rc = build_tool(tree, name)
    exe = os.path.join(tree, "host", "routine-sweep")
    if rc != 0 or not os.path.exists(exe):
        print(f"  build of plant {name} failed (rc {rc}): {log[-500:]}")
        return None
    return exe


# ---------------------------------------------------------------------------------------------------
# the lanes
# ---------------------------------------------------------------------------------------------------

def special_lanes():
    out = {0x00000000, 0x80000000, 0x7f800000, 0xff800000, 0x7fc00000, 0xffc00000, 0x7fc00001, 0x7fffffff, 0x7f800001,
           0x7fa00000, 0xff800001, 0xffbfffff, 0x00000001, 0x80000001, 0x007fffff, 0x807fffff, 0x00800000, 0x80800000,
           0x7f7fffff, 0xff7fffff, 0x3f800000, 0xbf800000, 0x3f7fffff, 0x3f800001, 0xbf7fffff, 0xbf800001}
    for e in range(0, 255):                              # the neighbours of every power of two, both signs: every tiny gate
        for d in (-2, -1, 0, 1, 2):
            for s in (0, 0x80000000):
                v = (e << 23) + d
                if 0 <= v < 0x7f800000:
                    out.add(v | s)
    for x in (-1.0, -150.0, -149.0, -126.0, 88.72283935546875, -103.97, -87.33, 128.0, 127.99999, -150.00001):
        import struct
        b = struct.unpack("<I", struct.pack("<f", x))[0]
        out.update({(b + d) & 0xffffffff for d in (-3, -2, -1, 0, 1, 2, 3)})
    return out


def oracle_lanes(fn):
    FP32, ml, routines, sf, T, har = mods()
    import transcend_check as tc
    out = set(har.pools(FP32)) | special_lanes()
    for f in ("exp", "exp2", "expm1", "log", "log2", "log1p"):
        try:
            out |= set(har.edge_pool(FP32, f))
        except (ValueError, KeyError):
            pass
    for pool in (tc.unary_pool(FP32, 60, 7), tc.trig_pool(FP32, 60, 7), tc.radian_pool(FP32, 60, 7)):
        out |= set(pool)
    return sorted(out)


def tool_oracle(tool, op, attr, lanes, env=None):
    """routine-sweep oracle: {lane: (bits, flags)}, or (None, message)."""
    rc, out, err = tool.raw("oracle", op, attr, stdin="".join(f"{x:08x}\n" for x in lanes), env=env)
    rows = [ln.split() for ln in out.splitlines()]
    if rc != 0 or len(rows) != len(lanes):
        return None, f"rc {rc}, {len(rows)} lines for {len(lanes)} lanes: {err[-200:]}"
    return {int(a, 16): (int(b, 16), int(c, 16)) for a, b, c in rows}, ""


def diff_oracle(got, want):
    """The lanes where {lane: (bits, flags)} differ: [(lane, got, want)], and a lane-count difference is one more."""
    bad = [(x, got.get(x), w) for x, w in want.items() if got.get(x) != w]
    if len(got) != len(want):
        bad.append((-1, len(got), len(want)))
    return bad


# ---------------------------------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------------------------------

def group_build(tool, log, tree, work, imgs, manifest):
    warns = [ln for ln in log.splitlines() if "warning:" in ln]
    check("build: the build of the whole library and the tool prints no warning (WSL's MPFR 4.1.0 builds mpfr_tfn.h)", not warns,
          f"{warns[:3]}")
    ctl = X.copy_tree(tree, os.path.join(work, "nopragma"))
    for line in PRAGMAS:
        X.patch_once(os.path.join(ctl, "host", "tools", "routine_sweep.c"), line, "", "no pragma")
    exe = os.path.join(ctl, "host", "routine-sweep")
    if os.path.exists(exe):
        os.remove(exe)
    clog, _rc = build_tool(ctl, "the build without the diagnostic pragma")
    cw = [ln for ln in clog.splitlines() if "warning:" in ln]
    check("build: CONTROL - the same source without its `#pragma GCC diagnostic` lines warns of mpfr_tfn.h's unused functions "
          "(-Wunused-function), so the pragma takes a real warning away", any("unused" in w for w in cw), f"{cw[:2]}")
    rc, out, err = tool.raw("list")
    rows = out.splitlines()
    names = [r.split("-f32")[0] for r in rows]
    check("build: `list` names the thirteen, in the order of the brief", rc == 0 and names == list(THIRTEEN), f"rc {rc} {names}")
    built, skipped = gen_account(manifest)
    dig = dict(built)
    listed = {r.split("-f32")[0]: re.search(r"digest (\S+)$", r).group(1) for r in rows if "digest" in r}
    check("build: `list` gives each routine the generator built (its `digest` lines) the digest the generator's manifest gives (two implementations of the same hash "
          "over five images and banks)", listed == dig and len(built) > 0, f"{listed} {dig}")
    noimg = [r.split("-f32")[0] for r in rows if r.endswith("no image")]
    check("build: `list` has thirteen rows, five images for exactly the generator's built names (in the tool's order) and `no image` for exactly the names it skipped",
          len(rows) == 13 and [r.split("-f32")[0] for r in rows if "digest" in r] == [n for n, _ in built] and noimg == skipped and not account_problems(built, skipped),
          f"{rows} {built} {skipped}")
    check("build: RED - the `list` check above, evaluated on lists in memory, is red when `list` says `no image` for a name the account did not skip (a doctored noimg with one built name added), and when a built name is dropped",
          not (noimg + [built[0][0]] == skipped) and not ([r.split("-f32")[0] for r in rows if "digest" in r] == [n for n, _ in built[1:]]), "")
    rc, out, err = tool.raw("list", imgs=os.path.join(work, "nowhere"))
    check("build: `list` with no images directory says `no image` thirteen times", rc == 0 and out.count("no image") == 13, out[:200])
    rc, out, err = tool.raw("exp-f32", 0, 4, "rne")
    check("build: the oracle line names the linked MPFR and GMP", re.search(r"^oracle: MPFR \S+ with GMP \S+, mpfr_ieee\.h's emulation$",
          err, re.M) is not None and L.SOAK_ORACLE_MPFR.search(err) is not None, err[:200])
    check("build: the backend line is the soaks', word for word", L.SOAK_SOFTWARE.search(err) is not None, err[:200])
    check("build: one image line an attribute, `image <name> <attr>: sha256 <64 hex>, I instructions, K words`",
          len(re.findall(r"^image exp rne: sha256 [0-9a-f]{64}, \d+ instructions, \d+ words$", err, re.M)) == 1, err[:400])


def group_images(tool, tree, work, imgs, manifest):
    FP32, ml, routines, sf, T, har = mods()
    d2 = os.path.join(work, "img-again")
    rc, o = gen(d2)
    same = rc == 0 and sorted(os.listdir(d2)) == sorted(os.listdir(imgs)) and all(
        filecmp.cmp(os.path.join(d2, f), os.path.join(imgs, f), shallow=False) for f in os.listdir(imgs))
    built, skipped = gen_account(manifest)
    expected_files = 15 * len(built) + 1                     # three files an attribute, five attributes, a built name; and manifest.txt
    check("images: the generator is deterministic - a second run into another directory writes the same files (15 for each built routine and the manifest: 136 with nine), byte for byte",
          same and len(os.listdir(imgs)) == expected_files, f"{len(os.listdir(imgs))} files, {expected_files} expected, {o[-200:]}")
    rc, o = gen(d2)
    check("images: a DIR that exists is refused (exit 2), nothing written", rc == 2 and "exists" in o, o[-200:])
    rc, o = gen(os.path.join(work, "img-bad"), "--names", "exp,nonesuch")
    check("images: an unknown name is refused, exit 2", rc == 2, o[-200:])
    image_line = re.compile(r"^image \S+ \S+ instructions \d+ words \d+ image_sha256 [0-9a-f]{64} bank_sha256 [0-9a-f]{64} "
                            r"marks_sha256 [0-9a-f]{64} dag_digest [0-9a-f]{64} commit \S+$", re.M)
    check("images: the generator's account is whole - the names it built (`digest` lines) and the names it skipped (`skipped ... not built at fp32`) are disjoint, once each, "
          "BUILT in the tool's order, and together the thirteen", account_problems(built, skipped) == [], f"{account_problems(built, skipped)} {built} {skipped}")
    check("images: the manifest has an image line for each (built name, attribute) - 45 with nine - with its three sha256, dag_digest and commit",
          len(image_line.findall(manifest)) == 5 * len(built), f"{len(image_line.findall(manifest))} for {len(built)} built")
    # send-back 1 of parcel M4X2: the RED checks below evaluate the conditions of the checks above on doctored input - one on a doctored COPY of the images directory
    # (work/img-red), the others on doctored lists and on a manifest string held in memory; the digest judge's reds and greens, on doctored tables, follow them.
    red_dir = os.path.join(work, "img-red")
    shutil.copytree(imgs, red_dir)
    for ext in ("cftp", "bank", "marks"):
        os.remove(os.path.join(red_dir, f"{built[0][0]}-fp32-rne.{ext}"))
    check("images: RED - one built name's three files of one attribute removed: the derived file count is not the directory's (the deterministic-run check's figure)",
          len(os.listdir(red_dir)) != expected_files, f"{len(os.listdir(red_dir))} vs {expected_files}")
    shutil.rmtree(red_dir)
    check("images: RED - a `skipped` line added for a name that has a digest line: the account is not whole (built and skipped overlap)",
          any("both built and skipped" in x for x in account_problems(built, skipped + [built[0][0]])), "")
    check("images: RED - a built name dropped from both lists: the account is not whole (neither built nor skipped)",
          any("neither built nor skipped" in x for x in account_problems(built[1:], skipped)), "")
    check("images: RED - an image line dropped: the manifest's image lines are not 5 for each built name",
          len(image_line.findall(manifest.replace(image_line.findall(manifest)[0] + "\n", "", 1))) != 5 * len(built), "")
    check("images: GREEN - while atan is skipped: lists with one more built name (an atan `digest` line, atan taken off the skipped lines) have a whole account "
          "(when atan is built the lists are the real ones and this repeats the account check)",
          account_problems(built + ([("atan", "00000000")] if "atan" in skipped else []), [n for n in skipped if n != "atan"]) == [], "")
    # parcel M4X2: the generator's `digest` lines against hw/card_stress_lib.py's table of them, which the card driver holds its build step to: a moved fragment
    # fails the gate at its merge and not a night. The judge is a function, so that it is shown red on a doctored table as well as green on the real one.
    mdig = built
    fails_, named_ = digest_judge(mdig, L.ROUTINE_DIGESTS)
    doctored = dict(L.ROUTINE_DIGESTS)
    doctored["exp"] = doctored["exp"][:-1] + ("0" if doctored["exp"][-1] != "0" else "1")
    check("images: every row of hw/card_stress_lib.py's ROUTINE_DIGESTS is among the generator's `digest` lines with an equal digest, in the table's order (the build step's rule); "
          f"a built name with no row is named and does not fail ({named_ or 'none today'})", not fails_ and len(L.ROUTINE_DIGESTS) > 0, f"{fails_} {mdig} {L.ROUTINE_DIGESTS}")
    check("images: ... and the same judge is red on a table with one digit of exp's digest changed, on one with a row the generator skipped (a name never built, "
          "when it skipped none) and on one in another order; the table with a row dropped is green and names the built name it lacks",
          digest_judge(mdig, doctored)[0] and digest_judge(mdig, dict(L.ROUTINE_DIGESTS, **{(skipped or ["nonesuch"])[0]: "00000000"}))[0]
          and digest_judge(mdig, dict(reversed(list(L.ROUTINE_DIGESTS.items()))))[0]
          and digest_judge(mdig, {k: v for k, v in L.ROUTINE_DIGESTS.items() if k != "tan"}) == ([], ["tan"] + [n for n, _ in mdig if n not in L.ROUTINE_DIGESTS]), "")
    check("images: ... and green, naming the extra, on built names with one more than the table has: a name that can never be built or tabled (nonesuch), added to the real lists",
          digest_judge(mdig + [("nonesuch", "00000000")], L.ROUTINE_DIGESTS) == ([], named_ + ["nonesuch"]), "")
    ok = os.path.exists(os.path.join(tree, "host", "positive-run"))
    if not ok:
        skip("images: positive-run", "did not build")
        return
    rnd_of = {sf.RND_NAMES[r]: r for r in sf.RND_NAMES}
    rng = random.Random(11)
    pool = list(har.pools(FP32))
    for n in NINE:
        for ai, attr in enumerate(ATTRS):
            f = ml.fragment(n, FP32, rnd_of[attr])
            k = 200 if attr == "rne" else 32
            xs = rng.sample(pool, k)
            with open(os.path.join(work, "a.bin"), "wb") as fh:
                fh.write(b"".join(x.to_bytes(4, "little") for x in xs))
            stem = os.path.join(imgs, f"{n}-fp32-{attr}")
            p = subprocess.run(NICE + [os.path.join(tree, "host", "positive-run"), stem + ".cftp", "--a", os.path.join(work, "a.bin"),
                                       "--bank", stem + ".bank", "--out", os.path.join(work, "d.bin")], capture_output=True, text=True)
            raw = open(os.path.join(work, "d.bin"), "rb").read() if p.returncode == 0 else b""
            dep = [int.from_bytes(raw[i:i + 4], "little") for i in range(0, len(raw), 4)]
            outs, words = routines.run(f, xs)
            ev = [ml.evaluate(f, x) for x in xs]
            check(f"images: {n} {attr}: positive-run of the image and bank deposits mathlib.evaluate's bits on {k} lanes",
                  p.returncode == 0 and dep == [b for b, _w in ev], f"rc {p.returncode} {p.stderr[-200:]}")
            check(f"images: {n} {attr}: ... and routines.run's", dep == list(outs) if p.returncode == 0 else False, "")


def group_oracle(tool):
    FP32, ml, routines, sf, T, har = mods()
    rnd_of = {sf.RND_NAMES[r]: r for r in sf.RND_NAMES}
    findings = []
    nlanes = len(oracle_lanes("exp"))
    print(f"  oracle: {nlanes} lanes for each of the twelve unary names and 5 attributes ({12 * 5 * nlanes} comparisons)")
    for fn in THIRTEEN:
        if fn == "atan2":
            continue
        lanes = oracle_lanes(fn)
        for attr in ATTRS:
            got, why = tool_oracle(tool, f"{fn}-f32", attr, lanes)
            want = {x: T.compute(FP32, fn, x, 0, rnd_of[attr]) for x in lanes}
            bad = diff_oracle(got, want) if got is not None else [(-2, why, "")]
            check(f"oracle: {fn} {attr}: {len(lanes)} lanes, bits and flags equal transcend.compute's", not bad,
                  f"{len(bad)} differ: {[(hex(x), g, w) for x, g, w in bad[:3]]}")
            findings += bad[:2]
    ys = sorted(random.Random(3).sample(oracle_lanes("atan2"), 420) + [0, 0x80000000, 0x7f800000, 0xff800000, 0x7fc00000, 0x7fa00000,
                                                                       1, 0x00800000, 0x7f7fffff, 0x3f800000, 0xbf800000])
    print(f"  oracle: atan2 over {len(ys)} y for each of the nine x and 5 attributes ({9 * 5 * len(ys)} comparisons)")
    for x in X9:
        for attr in ATTRS:
            got, why = tool_oracle(tool, f"atan2-f32-x{x:08x}", attr, ys)
            want = {y: T.compute(FP32, "atan2", y, x, rnd_of[attr]) for y in ys}
            bad = diff_oracle(got, want) if got is not None else [(-2, why, "")]
            check(f"oracle: atan2 x={x:#010x} {attr}: {len(ys)} y, bits and flags equal transcend.compute's", not bad,
                  f"{len(bad)} differ: {[(hex(a), g, w) for a, g, w in bad[:3]]}")
    # NaN is the canonical quiet NaN on our side, as a row of its own
    got, _ = tool_oracle(tool, "log-f32", "rne", [0xbf800000, 0x7fa00001, 0xff800001, 0x7fc12345])
    check("oracle: log of -1, of two sNaNs and of a quiet NaN with a payload are all 0x7fc00000",
          got is not None and all(v[0] == 0x7fc00000 for v in got.values()), f"{got}")


def slice_lanes(lo, n):
    return list(range(lo, lo + n))


AGREE_SLICES = (0x3f7fff80, 0x40490f00)


def group_agree(tool, names):
    FP32, ml, routines, sf, T, har = mods()
    rnd_of = {sf.RND_NAMES[r]: r for r in sf.RND_NAMES}
    for n in names:
        for attr in ATTRS:
            f = ml.fragment(n, FP32, rnd_of[attr])
            for lo in AGREE_SLICES:
                lanes = slice_lanes(lo, 256)
                got, why = tool_oracle(tool, f"{n}-f32", attr, lanes)
                bad, py_marked = [], 0
                for x in lanes:
                    bits, fw = ml.evaluate(f, x)
                    if fw & ml.MARK:
                        py_marked += 1
                    elif got is None or got[x] != (bits, fw):
                        bad.append(x)
                rc, text, m = tool.run(f"{n}-f32", lo, lo + 256, attr)
                ok, why2 = judge_run(rc, text, f"{n}-f32", attr, lo, lo + 256, 1)
                mk = marks_of(text)
                check(f"agree: {n} {attr} [{lo:#x}, +256): every unmarked lane of mathlib.evaluate is the oracle's in bits and flags",
                      not bad and got is not None, f"{[hex(x) for x in bad[:3]]} {why}")
                check(f"agree: {n} {attr} [{lo:#x}, +256): the tool passes the slice and its marks ({mk and mk[0]}) are evaluate's "
                      f"({py_marked})", ok and mk is not None and mk[0] == py_marked, f"{why2} {mk}")


def group_marks(tool, work):
    FP32, ml, routines, sf, T, har = mods()
    rnd_of = {sf.RND_NAMES[r]: r for r in sf.RND_NAMES}
    tot, offs, wrongs = [0] * 5, 0, 0
    for lane in FIVE:
        rc, text, m = tool.run("exp-f32", lane - 4, lane + 5, "all")
        ok, why = judge_run(rc, text, "exp-f32", "all", lane - 4, lane + 5, 5)
        mk = marks_of(text)
        check(f"marks: exp [{lane - 4:#x}, +9) under all passes", ok, why)
        if mk:
            tot = [a + b for a, b in zip(tot, mk[1])]
            offs += mk[2]
            wrongs += mk[3]
    check("marks: exp's five lanes mark 0, 5, 5, 5, 0 under rne, rtz, rdn, rup, rmm", tot == [0, 5, 5, 5, 0], f"{tot}")
    check("marks: ... none of them off the list, and no guess wrong", offs == 0 and wrongs == 0, f"{offs} off, {wrongs} wrong")
    check("marks: ... and the model agrees: evaluate marks exactly those lanes under each attribute",
          all(sum(1 for x in FIVE if ml.evaluate(ml.fragment("exp", FP32, rnd_of[a]), x)[1] & ml.MARK) == c
              for a, c in zip(ATTRS, (0, 5, 5, 5, 0))), "")
    # at volume
    vol = os.path.join(work, "img-s34")
    rc, o = gen(vol, "--names", "exp,sin", "--attrs", "rtz", "--bound-shift", "34")
    check("marks: the generator makes the --bound-shift 34 images", rc == 0, o[-200:])
    for n in ("exp", "sin"):
        lo, cnt = 0x3f000000, 1 << 14
        rc, text, m = tool.run(f"{n}-f32", lo, lo + cnt, "rtz", imgs=vol)
        mk = marks_of(text)
        f = ml.build(n, FP32, sf.RND_RTZ, bound_shift=34).fragment()
        marked = guess_wrong = 0
        for x in range(lo, lo + cnt):
            bits, fw = ml.evaluate(f, x)
            if fw & ml.MARK:
                marked += 1
                if (bits, fw & 0x1f) != T.compute(FP32, n, x, 0, sf.RND_RTZ):
                    guess_wrong += 1
        vm = counts(m) if m else None
        check(f"marks: {n} at G' = 6 over [{lo:#x}, +2^14) under rtz: the tool's marks ({mk and mk[1][1]}) equal Python's ({marked}), "
              f"its wrong guesses ({mk and mk[3]}) Python's ({guess_wrong}), no unmarked lane wrong, every mark off the list",
              mk is not None and mk[1][1] == marked and mk[3] == guess_wrong and vm is not None and vm[1:] == (0, 0) and mk[2] == marked
              and marked > 0, f"{mk} {vm} python {marked} {guess_wrong}")


def slices_of(bits):
    n = 1 << bits
    return {"around 1": 0x3f800000 - n // 2, "tiny": 0x33800000 - n // 2, "large": 0x42b17218 - n // 2, "negative": 0xc0000000 - n // 2}


def group_whole(tool, names, bits):
    n = 1 << bits
    for name in names:
        for what, lo in slices_of(bits).items():
            rc, text, m = tool.run(f"{name}-f32", lo, lo + n, "all")
            ok, why = judge_run(rc, text, f"{name}-f32", "all", lo, lo + n, 5)
            check(f"whole: {name} all over 2^{bits} lanes {what} [{lo:#x}, +{n:#x}): judged by L.parse_soak", ok, why)
    lo = slices_of(bits)["around 1"]
    for attr in (ATTRS if "exp" in names else ()):      # once, with exp
        rc, text, m = tool.run("exp-f32", lo, lo + n, attr)
        ok, why = judge_run(rc, text, "exp-f32", attr, lo, lo + n, 1)
        check(f"whole: exp {attr} alone over 2^{bits} lanes around 1", ok, why)


def group_fast(tool, names, bits):
    n = 1 << min(bits, 13)
    for name in names:
        for what, lo in slices_of(bits).items():
            rc, text, m = tool.run(f"{name}-f32", lo, lo + n, "all", env={"CFT_SWEEP_ORACLE_CHECK": "1"})
            ok, why = judge_run(rc, text, f"{name}-f32", "all", lo, lo + n, 5)
            check(f"fast: {name} {what} [{lo:#x}, +{n:#x}) with the oracle beside every lane: no difference (no ORACLE line)",
                  ok and "ORACLE" not in text, why)


def group_refuse(tool, work, imgs):
    def refused(label, args, expect=None, **kw):
        rc, out, err = tool.raw(*args, **kw)
        ok = rc == 2 and L.SOAK_LINE.search(out) is None and " cases," not in out and (expect is None or expect in out + err)
        check(f"refuse: {label}: exit 2, no verdict line, nothing run", ok, f"rc {rc} out {out[:80]!r} err {err[-160:]!r}")
    for label, args in (("an empty range", ("exp-f32", 5, 5, "rne")), ("a reversed range", ("exp-f32", 9, 5, "rne")),
                        ("a range past 2^32", ("exp-f32", 0, 0x100000001, "rne")), ("a lo past 2^32", ("exp-f32", 0x100000000, 0x100000001, "rne")),
                        ("a negative lo", ("exp-f32", -1, 5, "rne")), ("a negative hi", ("exp-f32", 0, -5, "rne")),
                        ("a non-numeric lo", ("exp-f32", "abc", 5, "rne")), ("a lo of 1.5", ("exp-f32", "1.5", 5, "rne")),
                        ("a bare 0x", ("exp-f32", "0x", 5, "rne")), ("a number past 64 bits", ("exp-f32", 0, "99999999999999999999", "rne"))):
        refused(label, args)
    refused("a missing attribute", ("exp-f32", 0, 5))
    refused("an unknown attribute", ("exp-f32", 0, 5, "rnx"))
    refused("an unknown name", ("nonesuch-f32", 0, 5, "rne"), "unknown op")
    n_ = gen_account(open(os.path.join(imgs, "manifest.txt")).read())[0][-1][0]
    noimg_dir = os.path.join(work, "img-noimage")
    shutil.copytree(imgs, noimg_dir)
    for attr in ("rne", "rtz", "rdn", "rup", "rmm"):
        os.remove(os.path.join(noimg_dir, f"{n_}-fp32-{attr}.cftp"))
    refused(f"a name with no image ({n_}, the last the generator built, its five .cftp files removed from a copy of its output)",
            (f"{n_}-f32" + ("-x3f800000" if n_ == "atan2" else ""), 0, 5, "rne"), f"{n_}-fp32-rne.cftp", imgs=noimg_dir)
    op_ = f"{n_}-f32" + ("-x3f800000" if n_ == "atan2" else "")
    rc, text, m = tool.run(op_, 0, 4, "rne")
    ok, why = judge_run(rc, text, op_, "rne", 0, 4, 1)
    check(f"refuse: CONTROL - the same op ({n_}) over the generator's own output, its images present, is run to a verdict and not refused", ok, why)
    refused("a name without -f32", ("exp", 0, 5, "rne"), "unknown op")
    refused("atan2 without its x", ("atan2-f32", 0, 5, "rne"), "atan2 takes")
    refused("an x with 7 digits", ("atan2-f32-x3f80000", 0, 5, "rne"), "eight hex")
    refused("an x that is not hex", ("atan2-f32-xzzzzzzzz", 0, 5, "rne"))
    refused("an x on a unary name", ("exp-f32-x3f800000", 0, 5, "rne"), "only atan2")
    refused("a digest that is not the images'", ("exp-f32-d00000000", 0, 5, "rne"), "digest")
    rc, out, err = tool.raw("list")
    d = re.search(r"^exp-f32: .*digest (\S+)$", out, re.M).group(1)
    rc, text, m = tool.run(f"exp-f32-d{d}", 0, 4, "rne")
    ok, why = judge_run(rc, text, f"exp-f32-d{d}", "rne", 0, 4, 1)
    check("refuse: CONTROL - the images' own digest is accepted, and the verdict names the op word as given", ok, why)
    refused("a bad digest word (7 digits)", ("exp-f32-d1234567", 0, 5, "rne"), "eight hex")
    refused("an unknown images directory", ("exp-f32", 0, 5, "rne"), "cannot read", imgs=os.path.join(work, "nowhere"))
    bad = os.path.join(work, "img-trunc")
    shutil.copytree(imgs, bad)
    with open(os.path.join(bad, "exp-fp32-rne.cftp"), "r+b") as fh:
        fh.truncate(100)
    refused("a truncated image (exp rne, 100 bytes)", ("exp-f32", 0, 5, "rne"), "exp-fp32-rne.cftp", imgs=bad)
    shutil.copy(os.path.join(imgs, "exp-fp32-rne.cftp"), os.path.join(bad, "exp-fp32-rne.cftp"))
    with open(os.path.join(bad, "exp-fp32-rtz.bank"), "r+b") as fh:
        fh.truncate(100)
    refused("a truncated bank (exp rtz, 100 bytes)", ("exp-f32", 0, 5, "rtz"), "exp-fp32-rtz.bank", imgs=bad)
    os.remove(os.path.join(bad, "exp-fp32-rdn.marks"))
    refused("a missing marks file (exp rdn)", ("exp-f32", 0, 5, "rdn"), "exp-fp32-rdn.marks", imgs=bad)
    with open(os.path.join(bad, "exp-fp32-rup.marks"), "w") as fh:
        fh.write("33ffffff\nnot hex\n")
    refused("a marks file with a line that is not hex", ("exp-f32", 0, 5, "rup"), "exp-fp32-rup.marks", imgs=bad)
    refused("a bad CFT_SWEEP_LANES", ("exp-f32", 0, 5, "rne"), env={"CFT_SWEEP_LANES": "0"})
    refused("a non-numeric CFT_SWEEP_LANES", ("exp-f32", 0, 5, "rne"), env={"CFT_SWEEP_LANES": "many"})
    refused("oracle with an unknown attribute", ("oracle", "exp-f32", "all"))
    rc, out, err = tool.raw("oracle", "exp-f32", "rne", stdin="3f800000\nxyz\n")
    check("refuse: oracle with a lane that is not hex: exit 2", rc == 2, f"rc {rc} {err[-100:]}")
    # a path that measures nothing says so and does not crash: one lane, an all-NaN slice
    rc, text, m = tool.run("exp-f32", 0x7fc00000, 0x7fc00001, "all")
    ok, why = judge_run(rc, text, "exp-f32", "all", 0x7fc00000, 0x7fc00001, 5)
    mk = marks_of(text)
    check("refuse: a slice of one lane that is a NaN runs: 5 cases, no mark, and the marks line says 0", ok and mk and mk[0] == 0, why)
    rc, text, m = tool.run("exp-f32", 0x7fc00000, 0x7fc01000, "rne", env={"CFT_SWEEP_LANES": "7"})
    ok, why = judge_run(rc, text, "exp-f32", "rne", 0x7fc00000, 0x7fc01000, 1)
    check("refuse: an all-NaN slice at 7 lanes a call (a short last call) is judged whole", ok, why)


def group_sabotage(tool, work, names):
    vol = os.path.join(work, "img-sab3")
    rc, o = gen(vol, "--bound-shift", "34", "--names", ",".join(names), "--attrs", "rtz")
    check("sabotage: the images with marks (--bound-shift 34) are generated", rc == 0, o[-200:])
    for n in names:
        lo = 0x3f7ff000
        for s, want in (("1", "MISMATCH"), ("2", "FLAGS")):
            rc, text, m = tool.run(f"{n}-f32", lo, lo + 512, "all", env={"CFT_SOAK_SABOTAGE": s})
            check(f"sabotage: {n} =1/2 {s} over 512 lanes exits 1 and prints {want} lines", rc == 1 and f"  {want} " in text,
                  f"rc {rc} {text[-200:]}")
        rc, text, m = tool.run(f"{n}-f32", lo, lo + 512, "all")
        ok, why = judge_run(rc, text, f"{n}-f32", "all", lo, lo + 512, 5)
        check(f"sabotage: {n} the same slice passes without", ok, why)
        lo3 = 0x3f000000
        rc, text, m = tool.run(f"{n}-f32", lo3, lo3 + 4096, "rtz", imgs=vol, env={"CFT_SOAK_SABOTAGE": "3"})
        mk = marks_of(text)
        check(f"sabotage: {n} =3 over 4096 lanes with marks ({mk and mk[0]}) exits 1 on the call's STATUS check alone: a FLAGS line "
              f"for STATUS[6], and no MISMATCH line", rc == 1 and "STATUS[6] set and no lane" in text
              and text.count("  FLAGS ") == 1 and "  MISMATCH " not in text
              and mk is not None and mk[0] == 0, f"rc {rc} {text[-300:]}")
        rc, text, m = tool.run(f"{n}-f32", lo3, lo3 + 4096, "rtz", imgs=vol)
        mk = marks_of(text)
        check(f"sabotage: {n} the same marked slice passes without =3 (marks counted, not failed)",
              rc == 0 and mk is not None and mk[0] > 0, f"rc {rc} {mk}")
    rc, text, m = tool.run("exp-f32", 0x3f800000, 0x3f800010, "rne", env={"CFT_SOAK_SABOTAGE": "3"})
    check("sabotage: =3 over a slice with no marked lane says so on stderr and passes (it sabotages nothing)",
          rc == 0 and "nothing is sabotaged" in text, f"rc {rc} {text[-200:]}")


def run_plant_slice(exe, imgs, op, lo, hi, mode, env=None):
    t = Sweep(exe, imgs)
    rc, text, m = t.run(op, lo, hi, mode, env=env)
    return rc, text, m, (counts(m) if m else None)


def group_plants(tool, tree, work, imgs):
    base = Sweep(tool.path, imgs)

    def plant_imgs(name, *args):
        d = os.path.join(work, "pl-" + name)
        rc, o = gen(d, *args)
        check(f"plants: the generator builds {name}", rc == 0, o[-200:])
        return d

    # (a) a wrong word
    d = plant_imgs("table_entry", "--names", "exp", "--plant", "table_entry", "--attrs", "rne")
    rc, text, m, c = run_plant_slice(tool.path, d, "exp-f32", 0x3e800000, 0x3e804000, "rne")
    check("plants: exp table_entry over 2^14 normal x at 0.25 (the table's entry j = 3 is reached there only) is red in value mismatches", rc == 1 and c and c[1] > 0, f"rc {rc} {c}")
    rc, text, m, c = run_plant_slice(tool.path, imgs, "exp-f32", 0x3e800000, 0x3e804000, "rne")
    check("plants: ... CONTROL, the plain exp, is green", judge_run(rc, text, "exp-f32", "rne", 0x3e800000, 0x3e804000, 1)[0], f"{c}")
    # (b) a flag dropped: sin inf_flag_dropped
    d = plant_imgs("inf_flag_dropped", "--names", "sin", "--plant", "inf_flag_dropped", "--attrs", "rne")
    tot_v = tot_f = 0
    for lo in (0x7f800000, 0xff800000):
        rc, text, m, c = run_plant_slice(tool.path, d, "sin-f32", lo, lo + 1, "rne")
        tot_v += c[1] if c else 0
        tot_f += c[2] if c else 0
        check(f"plants: sin inf_flag_dropped at {lo:#x} exits 1", rc == 1, f"rc {rc}")
    check("plants: ... red in flag mismatches and in no value mismatch", tot_f > 0 and tot_v == 0, f"V {tot_v} F {tot_f}")
    rc, text, m, c = run_plant_slice(tool.path, imgs, "sin-f32", 0x7f800000, 0x7f800001, "rne")
    check("plants: ... CONTROL, the plain sin at +inf, is green", judge_run(rc, text, "sin-f32", "rne", 0x7f800000, 0x7f800001, 1)[0], f"{c}")
    # (c) log1p pminn_dropped under rtz at x = 2^emin
    d = plant_imgs("pminn_dropped", "--names", "log1p", "--plant", "pminn_dropped", "--attrs", "rtz")
    rc, text, m, c = run_plant_slice(tool.path, d, "log1p-f32", 0x00800000, 0x00800001, "rtz")
    check("plants: log1p pminn_dropped under rtz at x = 2^emin is red in flag mismatches", rc == 1 and c and c[2] > 0, f"rc {rc} {c}")
    rc, text, m, c = run_plant_slice(tool.path, imgs, "log1p-f32", 0x00800000, 0x00800001, "rtz")
    check("plants: ... CONTROL, the plain log1p, is green", judge_run(rc, text, "log1p-f32", "rtz", 0x00800000, 0x00800001, 1)[0], f"{c}")
    # (d) a mark silenced: red by the .marks list, and by no value mismatch
    d = plant_imgs("mark_silenced", "--names", "exp", "--plant", "mark_silenced", "--attrs", "rtz")
    tv = tf = tm = 0
    for lane in FIVE:
        rc, text, m, c = run_plant_slice(tool.path, d, "exp-f32", lane - 4, lane + 5, "rtz")
        mk = marks_of(text)
        tv += c[1] if c else 0
        tf += c[2] if c else 0
        tm += mk[0] if mk else 0
    check("plants: exp mark_silenced under rtz over the five lanes: 5 flag mismatches by the .marks list, no value mismatch, no mark counted",
          tf == 5 and tv == 0 and tm == 0, f"V {tv} F {tf} marks {tm}")
    tm = tf = 0
    for lane in FIVE:
        rc, text, m, c = run_plant_slice(tool.path, imgs, "exp-f32", lane - 4, lane + 5, "rtz")
        mk = marks_of(text)
        tf += c[2] if c else 0
        tm += mk[0] if mk else 0
    check("plants: ... CONTROL, the plain exp, marks the five and has no flag mismatch", tf == 0 and tm == 5, f"F {tf} marks {tm}")
    # (e) the oracle given the wrong attribute
    exe = plant_tool(tree, work, "oracle_attr", [("tools/mpfr_tfn.h", "        tunb = raw_tfn(runb, fn, a, b, nn, rnd);\n",
                                                "        tunb = raw_tfn(runb, fn, a, b, nn, rnd == MPFR_RNDN ? MPFR_RNDZ : rnd);\n")])
    if exe:
        rc, text, m, c = run_plant_slice(exe, imgs, "exp-f32", 0x3f000000, 0x3f001000, "rne")
        check("plants: raw_tfn given rtz for rne is red in value mismatches", rc == 1 and c and c[1] > 0, f"rc {rc} {c}")
    # (f) a count short
    exe = plant_tool(tree, work, "short", [("tools/routine_sweep.c", "for (i = 0; i < nl; i++) {   /* the lanes of one call */",
                                           "for (i = 0; i + 1 < nl; i++) {   /* the lanes of one call */")])
    if exe:
        rc, text, m, c = run_plant_slice(exe, imgs, "exp-f32", 0x3f000000, 0x3f000100, "all")
        try:
            L.parse_soak(text, rc, "exp-f32", "all", None, 5 * 256, {"encodings": 256, "per_encoding": 5})
            refused_by_cover = False
        except L.VerdictError as ex:
            refused_by_cover = "cases" in str(ex)
        m1 = L.SOAK_LINE.search(text)
        check("plants: the tool stopping one lane early (a call's last lane unjudged) exits 0 with no mismatch and a short count, "
              "and L.parse_soak's cover rule refuses the verdict", rc == 0 and m1 is not None and int(m1.group(3)) < 5 * 256
              and refused_by_cover, f"rc {rc} {m1 and m1.group(0)}")
    # (g) the fast path rounding rup as rtz
    exe = plant_tool(tree, work, "fast_rup", [("tools/routine_sweep.c", "        case 3: away = !sign; break;                    /* rup */\n",
                                               "        case 3: away = 0; break;                        /* rup */\n")])
    if exe:
        rc, text, m, c = run_plant_slice(exe, imgs, "exp-f32", 0x3f000000, 0x3f000400, "all", env={"CFT_SWEEP_ORACLE_CHECK": "1"})
        check("plants: a fast path that rounds rup as rtz is red under CFT_SWEEP_ORACLE_CHECK=1: ORACLE value mismatches",
              rc == 1 and c and c[1] > 0 and "MISMATCH ORACLE rup" in text, f"rc {rc} {c}")
    rc, text, m, c = run_plant_slice(tool.path, imgs, "exp-f32", 0x3f000000, 0x3f000400, "all", env={"CFT_SWEEP_ORACLE_CHECK": "1"})
    check("plants: ... CONTROL, the real fast path under the same check, is green",
          judge_run(rc, text, "exp-f32", "all", 0x3f000000, 0x3f000400, 5)[0], f"{c}")


def group_unchanged(tree, base_dir, work):
    probe = subprocess.run(["sh", "-c", "printf '#include <mpfr.h>\\n#if MPFR_VERSION < MPFR_VERSION_NUM(4,2,0)\\n#error old\\n#endif\\n' "
                                        "| cc -E -x c - >/dev/null 2>&1"])
    if probe.returncode != 0:
        skip("unchanged", "mpfr-check needs MPFR 4.2.0 or newer (Pi-variants, exp2m1 ...) and this host's is older; run it on the desktop's mingw64")
        return
    if not base_dir:
        skip("unchanged", "needs --baseline-tree DIR (git archive REV host | tar -x -C DIR)")
        return
    outs = []
    for label, t in (("this tree", tree), ("the baseline", base_dir)):
        t2 = X.copy_tree(t, os.path.join(work, "mc-" + label.replace(" ", "-")))
        for exe in ("mpfr-check", "mpfr-check.exe"):
            p = os.path.join(t2, "host", exe)
            if os.path.isfile(p):
                os.remove(p)
        log, rc = build_tool(t2, label, ("mpfr-check",))
        if rc != 0:
            check(f"unchanged: mpfr-check builds in {label}", False, log[-300:])
            return
        env = dict(os.environ, CFT_MPFR_PHASES="transcend,trig,radian,table91", CFT_MPFR_FORMATS="fp32")
        exe = os.path.join(t2, "host", "mpfr-check")
        p = subprocess.run(NICE + [exe if os.path.exists(exe) else exe + ".exe", "24", "7"], capture_output=True, text=True, env=env, timeout=3600)
        outs.append((p.returncode, p.stdout + p.stderr))
    (rc1, o1), (rc2, o2) = outs
    check("unchanged: mpfr-check's output and exit status are the baseline's, byte for byte, the first (version) line apart",
          rc1 == rc2 and o1.split("\n")[1:] == o2.split("\n")[1:] and len(o1) > 100, f"rc {rc1} {rc2}, {len(o1)} {len(o2)} bytes")


def group_rate(tool, names, lanes):
    print(f"  rate (software backend, {lanes} lanes under all, load: {os.getloadavg()[0]:.1f} on {os.cpu_count()} threads at the start):")
    for n in names:
        lo = 0x3f800000 - lanes // 2
        rc, text, m = tool.run(f"{n}-f32", lo, lo + lanes, "all", env={"CFT_SWEEP_LANES": "16384"})
        t = re.search(r"device ([\d.]+) s, oracle ([\d.]+) s", text)
        ok, why = judge_run(rc, text, f"{n}-f32", "all", lo, lo + lanes, 5)
        if t:
            d, o = float(t.group(1)), float(t.group(2))
            print(f"    {n:6s} device {d:8.2f} s oracle {o:6.2f} s  {lanes / (d + o):9.0f} lanes/s ({'ok' if ok else 'RED'})")
        else:
            print(f"    {n:6s} no timing line: {why}")


def group_legs(tool, imgs, work):
    """Each leg of judge_run (and of the oracle and marks comparisons) failing alone on doctored input; green on the real one."""
    rc, text, m = tool.run("exp-f32", 0x3f800000, 0x3f800100, "all")
    op, lo, hi = "exp-f32", 0x3f800000, 0x3f800100
    check("legs: judge_run on a real run is green", judge_run(rc, text, op, "all", lo, hi, 5)[0], text[-200:])
    line = L.SOAK_LINE.search(text).group(0)
    cases = int(L.SOAK_LINE.search(text).group(3))

    def doctored(old, new, **kw):
        return judge_run(kw.get("rc", rc), text.replace(old, new, 1), kw.get("op", op), kw.get("mode", "all"), kw.get("lo", lo),
                         kw.get("hi", hi), kw.get("k", 5))[0]
    legs = {
        "exit status": doctored("x", "x", rc=1),
        "value mismatches": doctored("0 value mismatches", "1 value mismatches"),
        "flag mismatches": doctored("0 flag mismatches", "1 flag mismatches"),
        "a disagreement line": judge_run(rc, text + "  MISMATCH rne a=0x00000000 lib=0x1 mpfr=0x2\n", op, "all", lo, hi, 5)[0],
        "the op": judge_run(rc, text, "exp2-f32", "all", lo, hi, 5)[0],
        "the mode": judge_run(rc, text, op, "rne", lo, hi, 5)[0],
        "E": judge_run(rc, text, op, "all", lo, hi + 1, 5)[0],
        "cases": doctored(f"{cases} cases", f"{cases - 1} cases"),
        "skipped": doctored("0 skipped", "1 skipped"),
        "k": judge_run(rc, text, op, "all", lo, hi, 1)[0],
        "no verdict": judge_run(rc, text.replace(line, ""), op, "all", lo, hi, 5)[0],
        "two verdicts": judge_run(rc, text + line + "\n", op, "all", lo, hi, 5)[0],
    }
    for leg, ok in legs.items():
        check(f"legs: judge_run fails on its own, doctored {leg}", not ok, "")
    mk = marks_of(text)
    check("legs: marks_of reads the marks line and a doctored line has no parse", mk is not None and marks_of(text.replace("guesses", "gesses")) is None, f"{mk}")
    a = {1: (0x3f800000, 0x10), 2: (0x40000000, 0x10)}
    check("legs: diff_oracle is empty on equal maps", not diff_oracle(a, dict(a)), "")
    check("legs: diff_oracle sees a bits difference", bool(diff_oracle(a, {1: (0x3f800001, 0x10), 2: a[2]})), "")
    check("legs: diff_oracle sees a flags difference", bool(diff_oracle(a, {1: (0x3f800000, 0x00), 2: a[2]})), "")
    check("legs: diff_oracle sees a missing lane", bool(diff_oracle({1: a[1]}, a)), "")
    check("legs: diff_oracle sees a non-canonical NaN (0x7fe00000 for 0x7fc00000)", bool(diff_oracle({1: (0x7fe00000, 1)}, {1: (0x7fc00000, 1)})), "")
    # the agree group's comparison: evaluate of a PLANTED fragment is not the oracle's at x near 0.25, where table_entry acts
    FP32, ml, routines, sf, T, har = mods()
    lanes = slice_lanes(0x3e800000, 64)
    gotl, _ = tool_oracle(tool, "exp-f32", "rne", lanes)
    pf = ml.build("exp", FP32, sf.RND_RNE, plant="table_entry").fragment()
    plain = ml.fragment("exp", FP32, sf.RND_RNE)
    check("legs: the agree comparison is green on the plain exp over 64 lanes at 0.25", all(gotl[x] == ml.evaluate(plain, x) for x in lanes), "")
    check("legs: ... and red on exp with table_entry planted (evaluate is not the oracle's)",
          any(gotl[x] != ml.evaluate(pf, x) for x in lanes), "")
    # the marks group's comparison: the tool's count on --bound-shift 34 images is not the plain fragment's (0) over the same lanes
    vol = os.path.join(work, "img-legs-s34")
    rc, o = gen(vol, "--names", "exp", "--attrs", "rtz", "--bound-shift", "34")
    rc, text, m = tool.run("exp-f32", 0x3f000000, 0x3f000000 + 4096, "rtz", imgs=vol)
    mk = marks_of(text)
    py_plain = sum(1 for x in range(0x3f000000, 0x3f000000 + 256) if ml.evaluate(ml.fragment("exp", FP32, sf.RND_RTZ), x)[1] & ml.MARK)
    rc2, text2, m2 = tool.run("exp-f32", 0x3f000000, 0x3f000000 + 256, "rtz", imgs=vol)
    mk2 = marks_of(text2)
    check("legs: the marks comparison is red when Python counts the plain fragment (0) against the tool's G' = 6 images' marks over "
          f"the same 256 lanes ({mk2 and mk2[1][1]}); its other leg, the wrong-guess count, is the plain fragment's 0 against the tool's "
          f"({mk and mk[3]})", rc2 == 0 and mk2 is not None and py_plain == 0 and mk2[1][1] > 0, f"{mk2} {py_plain}")
    got, _ = tool_oracle(tool, "exp-f32", "rne", [0x3f800000, 0x7fa00001])
    check("legs: tool_oracle's reading of the tool is the transcend value for exp(1) and exp(sNaN)",
          got == {0x3f800000: (0x402df854, 0x10), 0x7fa00001: (0x7fc00000, 0x01)}, f"{got}")


# ---------------------------------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]

    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default

    only = set(opt("--only").split(",")) if opt("--only") else None
    names = tuple(opt("--names", ",".join(NINE)).split(","))
    bits = int(opt("--slice-bits", "16"))
    rate_lanes = int(opt("--rate-lanes", str(1 << 18)))
    base = opt("--baseline-tree")
    keep = "--keep" in args

    def want(g):
        return only is None or g in only

    t0 = time.time()
    if os.name != "posix" or not shutil.which("make") or not (shutil.which("cc") or shutil.which("gcc")):
        skip("routine-sweep", "needs POSIX with make and a C compiler, and MPFR and GMP")
    elif not have_mpmath():
        skip("routine-sweep", "needs python3 with mpmath and pytest (python/tests/mathlib_harness.py)")
    elif subprocess.run(["sh", "-c", "printf '#include <mpfr.h>\\n#include <gmp.h>\\n' | cc -E -x c - >/dev/null 2>&1"]).returncode != 0:
        skip("routine-sweep", "MPFR's or GMP's headers are not installed (libmpfr-dev, libgmp-dev)")
    else:
        work = tempfile.mkdtemp(prefix="routine-sweep-test-")
        try:
            tree = X.copy_tree(ROOT, os.path.join(work, "tree"))
            for exe in ("routine-sweep", "routine-sweep.exe", "positive-run", "positive-run.exe"):
                if os.path.isfile(os.path.join(tree, "host", exe)):
                    os.remove(os.path.join(tree, "host", exe))
            log, rc = build_tool(tree, "this tree", ("routine-sweep", "positive-run"))
            exe = os.path.join(tree, "host", "routine-sweep")
            if rc != 0 or not os.path.exists(exe):
                check("build: routine-sweep builds in a scratch copy of host/", False, log[-400:])
            else:
                imgs = os.path.join(work, "img")
                grc, o = gen(imgs)
                if grc != 0:
                    check("images: the generator writes the images", False, o[-400:])
                else:
                    tool = Sweep(exe, imgs)
                    manifest = open(os.path.join(imgs, "manifest.txt")).read()
                    for name, fn in (("build", lambda: group_build(tool, log, tree, work, imgs, manifest)),
                                     ("images", lambda: group_images(tool, tree, work, imgs, manifest)),
                                     ("oracle", lambda: group_oracle(tool)),
                                     ("agree", lambda: group_agree(tool, names)),
                                     ("marks", lambda: group_marks(tool, work)),
                                     ("whole", lambda: group_whole(tool, names, bits)),
                                     ("fast", lambda: group_fast(tool, names, bits)),
                                     ("refuse", lambda: group_refuse(tool, work, imgs)),
                                     ("sabotage", lambda: group_sabotage(tool, work, names)),
                                     ("plants", lambda: group_plants(tool, tree, work, imgs)),
                                     ("unchanged", lambda: group_unchanged(ROOT, base, work)),
                                     ("rate", lambda: group_rate(tool, names, rate_lanes)),
                                     ("legs", lambda: group_legs(tool, imgs, work))):
                        if want(name) and (name != "rate" or only is not None):
                            n0, f0 = CHECKS, len(FAILS)
                            t1 = time.time()
                            fn()
                            print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed, {time.time() - t1:.0f} s")
        finally:
            if not keep:
                shutil.rmtree(work, ignore_errors=True)
            else:
                print(f"kept {work}")
    print(f"routine-sweep test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
