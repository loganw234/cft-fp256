#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Test of the divsqrt soak's hard-case modes (host/tools/divsqrt_soak.c: div32-hard, div64-hard, sqrt64-hard), on the
software backend, against python/hardcases.py, the reference generator. POSIX with make and a C compiler (the soak
needs a 64-bit Linux); skipped by name elsewhere.

    python3 hw/test_divsqrt_hard.py [--only GROUP,...] [--baseline-tree DIR] [--keep] [--verbose]

It builds the tool in a scratch copy of host/ (make divsqrt-soak, XRT=0) and runs, niced, one process at a time:
  build      the tool builds; `hard-space` prints the generator's segment table for each mode (names, starts, counts,
             the slots an index makes, the total)
  agree      `hard-dump` prints, line for line, what python/hardcases.py dumps: the first and last indices of every
             segment and indices drawn from a fixed seed, in every mode (the C builders against the Python ones);
             `hard-count`, the cases and skipped slots of a slice by segment, equals the generator's count; and the
             three whole spaces make the cases, skip the slots and have the longest skip run the documents state
             (the builders alone, 60 s for div64-hard)
  special    each mode, under each attribute it takes, over slices at the start and the end of every segment and
             across every boundary between two: each must pass, E encodings = the slice's indices, cases + S = k x E,
             and S equal to the generator's own count of the indices that skip (an independent count: the driver's
             parse_soak holds the sum, and only this holds the split); the stress driver's own parse_soak, with
             its cover rule, must accept the tool's output for each
  spread     the same over slices spread across each space (evenly, and drawn from a fixed seed)
  refuse     a range that is empty, reversed, past the end, not a number or empty is refused by name (exit 2); so is
             rmm for division, an attribute that does not exist, and a mode word that is not one
  sabotage   CFT_SOAK_SABOTAGE=1 makes every mode FAIL, naming operands that are among the slice's operands
  plants     one defect put back into a copy for each class of check, red at the check written for it: a construction
             off by one (python/hardcases.py's exact verification, then the tool's own, then the agreement check when
             the tool's is blinded too); a slice one encoding short and a skip count one slot short (each refused by
             the driver's own parse_soak as well); a mode that skips every index (refused by name, and with the
             refusal removed caught by the independent count, the driver's parse_soak accepting it); a build with no
             128-bit integer; and the prototype's division that computes 40 extra bits and rounds ties-to-even on
             them, found by the constructed set and not by as many of the soak's own random draws
  unchanged  (with --baseline-tree DIR, a directory holding the baseline's host/ - `git archive REV host | tar -x -C DIR`)
             the random, exhaustive and hard-case modes of that tree's tool and of this tree's - its default build and
             its MPFR=1 build both - over the same invocations, print the same bytes and exit with the same status;
             so do `hard-space`, `hard-dump` and `hard-count` of the three fp32 and fp64 spaces

The wide modes (parcel HXa: `make divsqrt-soak MPFR=1`, the fp64, fp128 and fp256 division and square root against
MPFR), in a second copy of host/ built with MPFR=1; skipped by name where MPFR does not build:
  wide-agree    `hard-space` of all 30 new mode words equals the generator's; `hard-dump` and `hard-count` of the four
                wide hard spaces equal python/hardcases.py's line for line (every segment's ends, its boundaries,
                indices from a fixed seed), and of the slice and window spaces the generator's widening and windows
                (zeros, subnormals, infinities, NaNs and both signs among them); the f64hard names dump div64-hard's and
                sqrt64-hard's own lines
  wide-run      every new mode under all five attributes over short slices (the slice's specials, the windows' ends,
                every hard segment's ends and boundaries): each passes, E = the slice, cases + S = k x E, S equal to
                the generator's own count of skipped indices, the stress driver's parse_soak accepts it under its
                cover rule, and the slice and f64hard modes print their ladder line with no disagreement
  wide-sabotage CFT_SOAK_SABOTAGE=1 fails every new mode, naming operands of the slice (the primary oracle);
                CFT_SOAK_SABOTAGE=2 fails every slice and f64hard mode by "MISMATCH <attribute> ladder" lines alone
                (the second check), and the same slices pass without it
  wide-refuse   a bad range refused by name for each new mode, and the default build (no MPFR) refusing a wide mode
                word as an unknown op, exit 2, nothing run
  wide-plants   a construction off by one in the wide F0 builder, refused by the tool's own exact check by name; a
                widening that drops a subnormal's last bit, caught by the ladder and by the dump agreement; and an
                oracle given the wrong attribute, caught

Prints one line a group and a last line "divsqrt-hard test: N checks, F failed, S skipped".
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
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, HERE)
import hardcases as H  # noqa: E402
import card_stress_lib as L  # noqa: E402  (the driver's parsers: the cover rule is held to the real one)

CHECKS = 0
FAILS: list = []
SKIPS: list = []


VERBOSE = "--verbose" in sys.argv


def check(name: str, ok: bool, detail: str = "") -> bool:
    global CHECKS
    CHECKS += 1
    if not ok:
        FAILS.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}"[:520])
    elif VERBOSE:
        print(f"  ok    {name}"[:400])
    return bool(ok)


def skip(name: str, why: str) -> None:
    SKIPS.append(f"{name}: {why}")
    print(f"  SKIP  {name} - {why}")


LINE = re.compile(r"^(\S+) (\S+): (\d+) cases, (\d+) value mismatches, (\d+) flag mismatches, (\d+) encodings, "
                  r"(\d+) skipped$", re.M)
NICE = ["nice", "-n", "10"] if shutil.which("nice") else []
# the whole spaces: (cases, skipped slots, the longest run of consecutive skipped indices), as the documents state them
WHOLE_SPACE = {"div32-hard": (64346592, 20596560, 2), "div64-hard": (812489184, 346253600, 2),
               "sqrt64-hard": (1745752, 2710696, 5)}
# (mode word, the attributes it takes, the slots an index makes)
MODES = [("div32-hard", ["rne", "rtz", "rdn", "rup"], 4), ("div64-hard", ["rne", "rtz", "rdn", "rup"], 4),
         ("sqrt64-hard", ["rne", "rtz", "rdn", "rup", "rmm"], 1)]


class Tool:
    """A built divsqrt-soak."""

    def __init__(self, path: str):
        self.path = path

    def run(self, mode: str, lo, hi, attr, env=None, timeout: int = 600):
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.run(NICE + [self.path, mode, str(lo), str(hi), attr], capture_output=True, text=True,
                           timeout=timeout, env=e)
        return p.returncode, p.stdout + p.stderr, LINE.search(p.stdout)

    def raw(self, *args, env=None, timeout: int = 600):
        e = dict(os.environ)
        e.update(env or {})
        p = subprocess.run(NICE + [self.path] + [str(a) for a in args], capture_output=True, text=True,
                           timeout=timeout, env=e)
        return p.returncode, p.stdout, p.stderr


def build(tree: str, label: str, extra=None):
    """make divsqrt-soak in tree/host: the Tool, or None with a reason."""
    p = subprocess.run(NICE + ["make", "-C", os.path.join(tree, "host"), "-j4", "divsqrt-soak"] + (extra or []),
                       capture_output=True, text=True, timeout=900)
    exe = os.path.join(tree, "host", "divsqrt-soak")
    if p.returncode != 0 or not os.path.exists(exe):
        print(f"  build of {label} failed (rc {p.returncode}): {(p.stdout + p.stderr)[-600:]}")
        return None
    return Tool(exe)


def copy_tree(src_root: str, dst: str) -> str:
    """A copy of host/ in dst, mtimes kept, so a built tree stays built."""
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(os.path.join(src_root, "host"), os.path.join(dst, "host"), copy_function=shutil.copy2)
    return dst


_SKIPPED: dict = {}


def skipped_indices(mode: str, lo: int, hi: int) -> int:
    """The indices of [lo, hi) whose construction yields no operands, counted by the Python generator."""
    key = (mode, lo, hi)
    if key not in _SKIPPED:
        _SKIPPED[key] = sum(1 for i in range(lo, hi) if H.gen(mode, i)[0] is None)
    return _SKIPPED[key]


def driver_view(mode, attr, k, lo, hi, rc, out):
    """What the stress driver's own parse_soak makes of a slice's output under the cover rule (E = the slice's indices,
    cases + skipped = k x E): (True, '') when it accepts, else (False, its refusal)."""
    try:
        L.parse_soak(out, rc, mode, attr, None, None, {"encodings": hi - lo, "per_encoding": k})
    except L.VerdictError as e:
        return False, str(e)
    return True, ""


def judge(mode, attr, k, lo, hi, rc, out, m, skips=True):
    """The checks every passing slice must meet: exit 0, no mismatches, the encodings the slice has, cases + skipped
    = k x encodings, and (skips) the skipped count the generator gives, which parse_soak cannot see."""
    if m is None:
        return False, f"no verdict line: rc {rc}: {out[-200:]}"
    cases, vm, fm, enc, skp = int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
    if (m.group(1), m.group(2)) != (mode, attr):
        return False, f"the verdict is for {m.group(1)} {m.group(2)}"
    if rc != 0 or vm or fm:
        return False, f"rc {rc}, {vm} value and {fm} flag mismatches: {out[:300]}"
    if enc != hi - lo:
        return False, f"{enc} encodings for a slice of {hi - lo}"
    if cases + skp != k * enc:
        return False, f"{cases} cases + {skp} skipped is not {k} x {enc}"
    if skips:
        want = k * skipped_indices(mode, lo, hi)
        if skp != want:
            return False, (f"{skp} slots skipped where the independent count of the indices that skip is {want} "
                           f"({cases} compared)")
    return True, ""


# ---------------------------------------------------------------------------------------------------
# the slices
# ---------------------------------------------------------------------------------------------------

def special_slices(mode: str):
    """(what, lo, hi): the start and the end of every segment, and across every boundary between two."""
    sp = H.SPACES[mode]
    out = []
    for name, start, count in sp.segs:
        n = min(count, 3000)
        out.append((f"the start of {name}", start, start + n))
        out.append((f"the end of {name}", start + count - n, start + count))
    for (n1, s1, c1), (n2, s2, c2) in zip(sp.segs, sp.segs[1:]):
        a, b = min(700, c1), min(700, c2)
        out.append((f"across {n1} / {n2}", s2 - a, s2 + b))
    return out


def spread_slices(mode: str, size: int = 1000):
    """Slices across the whole space: 16 evenly (offset so none is aligned), and 8 at random from a fixed seed."""
    total = H.SPACES[mode].total
    even = [(i * (total // 16) + 1234 + 37 * i, i * (total // 16) + 1234 + 37 * i + size) for i in range(16)]
    rnd = random.Random(20261020)
    drawn = []
    for _ in range(8):
        lo = rnd.randrange(0, total - size)
        drawn.append((lo, lo + size))
    return [(a, min(b, total)) for a, b in even + drawn]


# ---------------------------------------------------------------------------------------------------
# the groups
# ---------------------------------------------------------------------------------------------------

def group_build(tool: Tool) -> None:
    for mode, _attrs, k in MODES:
        rc, out, err = tool.raw("hard-space", mode)
        want = "\n".join(H.space_lines(mode)) + "\n"
        check(f"build: `hard-space {mode}` prints the generator's segment table "
              f"({H.SPACES[mode].total:,} indices, {len(H.SPACES[mode].segs)} segments)", rc == 0 and out == want,
              f"rc {rc}: {out[:200]!r} against {want[:200]!r}")
        check(f"build: {mode} makes {k} slots an index in the generator", H.SPACES[mode].k == k, str(H.SPACES[mode].k))
    check("build: the three modes' totals are the documented ones (21,235,788, 289,685,696 and 4,456,448)",
          [H.SPACES[m].total for m, _a, _k in MODES] == [21235788, 289685696, 4456448],
          str([H.SPACES[m].total for m, _a, _k in MODES]))


def group_agree(tool: Tool) -> None:
    for mode, _attrs, _k in MODES:
        sp = H.SPACES[mode]
        rnd = random.Random(20261020)
        ranges = []
        for name, start, count in sp.segs:
            n = min(count, 300)
            ranges += [(start, start + n), (start + count - n, start + count)]
            for _ in range(6):
                lo = start + rnd.randrange(0, max(count - 60, 1))
                ranges.append((lo, min(lo + 60, start + count)))
        for (n1, s1, c1), (n2, s2, c2) in zip(sp.segs, sp.segs[1:]):
            ranges.append((s2 - min(40, c1), s2 + min(40, c2)))
        bad, lines, first, bad_count = 0, 0, "", 0
        for lo, hi in ranges:
            rc, out, err = tool.raw("hard-dump", mode, lo, hi)
            want = "\n".join(H.dump_lines(mode, lo, hi)) + "\n"
            lines += want.count("\n")
            if rc != 0 or out != want:
                bad += 1
                if not first:
                    a, b = out.splitlines(), want.splitlines()
                    d = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), None)
                    first = f"[{lo}, {hi}): rc {rc}, C {a[d] if d is not None else '-'!r} against Python " \
                            f"{b[d] if d is not None else '-'!r}"
            rc, out, err = tool.raw("hard-count", mode, lo, hi)
            if rc != 0 or out != "\n".join(H.count_lines(mode, lo, hi)) + "\n":
                bad_count += 1
        check(f"agree: {mode}: `hard-dump` equals python/hardcases.py's dump line for line over {len(ranges)} ranges "
              f"({lines:,} lines: every segment's start and end, its boundaries, indices drawn from a fixed seed)",
              bad == 0, f"{bad} ranges differ; first {first}")
        check(f"agree: {mode}: `hard-count` (the cases and skipped slots of a slice, per segment) equals the generator's "
              f"count over the same {len(ranges)} ranges", bad_count == 0, f"{bad_count} ranges differ")
    # the whole spaces, as the documents state them (docs/CARDDAY.md, docs/VALIDATION.md): the builders alone, every F0 and S0
    # case also checked in exact 128-bit integers by the tool as it is built. The longest run of skipped indices must stay
    # below the 64 at which an all-skipped slice is refused.
    t0 = time.time()
    for mode, (cases, skipped, longest) in WHOLE_SPACE.items():
        total = H.SPACES[mode].total
        rc, out, err = tool.raw("hard-count", mode, 0, total)
        mt = re.search(r"^total (\d+) (\d+) (\d+)$", out, re.M)
        ms = re.search(r"^maxskip (\d+)$", out, re.M)
        got = (int(mt.group(1)), int(mt.group(2)), int(mt.group(3)), int(ms.group(1))) if mt and ms else None
        check(f"agree: {mode}: the whole space ({total:,} indices) makes {cases:,} cases and skips {skipped:,} slots, and no run "
              f"of more than {longest} consecutive indices skips (below the refusal's 64)",
              rc == 0 and got == (total, cases, skipped, longest), f"rc {rc}: {got}")
    print(f"      (the three whole spaces counted in {time.time() - t0:.0f} s)")


def group_special(tool: Tool) -> None:
    n = bad = 0
    t0 = time.time()
    for mode, attrs, k in MODES:
        for what, lo, hi in special_slices(mode):
            for attr in attrs:
                rc, out, m = tool.run(mode, lo, hi, attr)
                ok, why = judge(mode, attr, k, lo, hi, rc, out, m)
                if ok:
                    ok, why = driver_view(mode, attr, k, lo, hi, rc, out)
                n += 1
                if not ok:
                    bad += 1
                    check(f"special: {mode} {attr} over {what} [{lo}, {hi})", False, why)
    check(f"special: {sum(len(a) * len(special_slices(m)) for m, a, _k in MODES)} slices (the start and end of every "
          f"segment and every boundary, in every mode, under every attribute): all {n} pass, every count as promised, "
          f"skips equal to the generator's, and the stress driver's own parse_soak accepts each under its cover rule",
          bad == 0, f"{bad} of {n} failed")
    print(f"      ({n} slices in {time.time() - t0:.0f} s)")
    # a few facts read off particular slices
    rc, out, m = tool.run("div32-hard", 0, 96, "rne")
    check("special: div32-hard over F3a (ties in the subnormal strip): 96 encodings, 384 cases, none skipped",
          rc == 0 and m is not None and (int(m.group(3)), int(m.group(6)), int(m.group(7))) == (384, 96, 0), out[:200])
    sp = H.SPACES["div32-hard"]
    d_start = [s for n_, s, c in sp.segs if n_ == "F0D"][0]
    rc, out, m = tool.run("div32-hard", d_start, d_start + 2000, "rne")
    check("special: div32-hard over a slice of F0D (divisors near 2.0): about half of its indices skip, and the tool says "
          "which (S equals the generator's count)",
          rc == 0 and m is not None and 0.3 < int(m.group(7)) / (4 * 2000) < 0.7, out[:200])


def group_spread(tool: Tool) -> None:
    t0 = time.time()
    n = bad = 0
    for mode, attrs, k in MODES:
        for lo, hi in spread_slices(mode):
            for attr in attrs:
                rc, out, m = tool.run(mode, lo, hi, attr)
                ok, why = judge(mode, attr, k, lo, hi, rc, out, m)
                n += 1
                if not ok:
                    bad += 1
                    check(f"spread: {mode} {attr} [{lo}, {hi})", False, why)
    check(f"spread: every mode and attribute over 24 slices of 1,000 indices across the whole space (16 even, 8 drawn "
          f"from a fixed seed): all {n} pass, every count as promised", bad == 0, f"{bad} of {n} failed")
    print(f"      ({n} slices in {time.time() - t0:.0f} s)")


def group_refuse(tool: Tool) -> None:
    for mode, _attrs, _k in MODES:
        total = H.SPACES[mode].total
        for what, args in (("an empty range", (5, 5)), ("a reversed range", (9, 5)), ("a range past the end", (0, total + 1)),
                           ("a start at the end", (total, total + 1)), ("a negative start", (-1, 5)),
                           ("garbage for a start", ("abc", 5)), ("garbage for an end", (0, "12x")),
                           ("an empty bound", ("", 5))):
            rc, out, err = tool.raw(mode, *args, "rne")
            check(f"refuse: {mode}: {what} is refused by name, exit 2, and runs nothing",
                  rc == 2 and f"need 0 <= lo < hi <= {total} (the indices of {mode})" in err and " cases," not in out,
                  f"rc {rc}: {err[-200:]}")
        for sub in ("hard-dump", "hard-count"):
            rc, out, err = tool.raw(sub, mode, 5, 5)
            check(f"refuse: {sub} {mode} 5 5 (an empty range) is refused by name, exit 2",
                  rc == 2 and "need 0 <= lo < hi" in err and out == "", f"rc {rc}: {err[-160:]}")
    for mode in ("div32-hard", "div64-hard"):
        rc, out, err = tool.raw(mode, 0, 64, "rmm")
        check(f"refuse: rmm for {mode} is refused by name (division has real ties), exit 2, and runs nothing",
              rc == 2 and "rmm is only checkable for sqrt" in err and " cases," not in out, f"rc {rc}: {err[-200:]}")
    rc, out, err = tool.raw("sqrt64-hard", 0, 64, "rmm")
    check("refuse: rmm IS accepted by sqrt64-hard (it rides the RNE oracle: an inexact root is never on a tie)",
          rc == 0 and "sqrt64-hard rmm:" in out, out[:200])
    rc, out, err = tool.raw("div32-hard", 0, 64, "rtx")
    check("refuse: an attribute that does not exist is refused by name, exit 2", rc == 2 and "unknown rounding mode rtx" in err,
          f"rc {rc}: {err[-200:]}")
    rc, out, err = tool.raw("div32-hard", 0, 64)
    check("refuse: no attribute prints the usage, with the hard-case lines, exit 2",
          rc == 2 and "div32-hard|div64-hard <lo> <hi>" in err and "hard-space" in err and "hard-dump" in err, err[-300:])
    rc, out, err = tool.raw("hard-space", "nosuch")
    check("refuse: hard-space of a mode that does not exist is refused by name, exit 2",
          rc == 2 and "unknown hard-case mode nosuch" in err, f"rc {rc}: {err[-160:]}")
    for sub in ("hard-dump", "hard-count"):
        rc, out, err = tool.raw(sub, "nosuch", 0, 4)
        check(f"refuse: {sub} of a mode that does not exist is refused by name, exit 2",
              rc == 2 and "unknown hard-case mode nosuch" in err, f"rc {rc}: {err[-160:]}")


def group_sabotage(tool: Tool) -> None:
    for mode, attrs, k in MODES:
        lo, hi = H.SPACES[mode].segs[-1][1], H.SPACES[mode].segs[-1][1] + 200      # the last segment's start
        operands = set()
        for i in range(lo, hi):
            for c in H.gen(mode, i):
                if c is not None:
                    operands.add(c[0])
        for attr in attrs:
            rc0, out0, m0 = tool.run(mode, lo, hi, attr)
            rc, out, m = tool.run(mode, lo, hi, attr, env={"CFT_SOAK_SABOTAGE": "1"})
            vm = int(m.group(4)) if m else 0
            named = [int(a, 16) for a in re.findall(r"^  MISMATCH \S+ a=0x([0-9a-f]+)", out, re.M)]
            check(f"sabotage: {mode} {attr}: CFT_SOAK_SABOTAGE=1 fails (exit 1, value mismatches, operands named that are "
                  f"the slice's own) and the same slice passes without it",
                  rc0 == 0 and rc == 1 and vm > 0 and named and all(a in operands for a in named),
                  f"clean rc {rc0}; sabotaged rc {rc}, {vm} mismatches, named {[hex(a) for a in named[:3]]}")


# --- the plants ------------------------------------------------------------------------------------

def patch_once(path: str, old: str, new: str, what: str) -> None:
    """Replace `old` by `new` in a file, which must contain it exactly once: a plant that did not apply proves nothing."""
    with open(path, "r", encoding="utf-8", newline="") as fh:
        text = fh.read()
    if text.count(old) != 1:
        raise SystemExit(f"plant {what}: {old[:70]!r} found {text.count(old)} times in {os.path.basename(path)}; "
                         f"the plant did not apply, so it would prove nothing")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text.replace(old, new))


def plant_tool(built_tree: str, work: str, name: str, edits: list, extra=None, rel=("tools", "divsqrt_soak.c")):
    """A copy of the built tree whose divsqrt_soak.c (or another file of host/, `rel`) has the edits (each applied exactly
    once), rebuilt: its Tool."""
    tree = copy_tree(built_tree, os.path.join(work, "plant-" + name))
    src = os.path.join(tree, "host", *rel)
    for old, new in edits:
        patch_once(src, old, new, name)
    if extra:                                           # a changed source needs the object rebuilt
        os.utime(src, None)
    return build(tree, name, extra)


def plant_generator(work: str, name: str, edits: list) -> str:
    """A scratch copy of python/hardcases.py with the edits (each applied exactly once): its path."""
    d = os.path.join(work, "gen-" + name)
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, "hardcases.py")
    shutil.copy2(os.path.join(ROOT, "python", "hardcases.py"), dst)
    for old, new in edits:
        patch_once(dst, old, new, name)
    return dst


PLANT_N = [0]


def run_generator(path: str, *args):
    p = subprocess.run([sys.executable, "-B", path, *[str(a) for a in args]], capture_output=True, text=True, timeout=600)
    return p.returncode, p.stdout + p.stderr


def flawed_rne(p: int, mx: int, my: int, g: int) -> int:
    """The prototype's planted defect (docs/studies/swp-a/hardcase_div.py H5): the quotient to g extra bits, rounded
    ties-to-even on those bits alone, ignoring the remainder. Returns the rounded significand in units of 2^(1-p)."""
    s = (mx << (p - 1 + g)) // my
    kept, low = s >> g, s & ((1 << g) - 1)
    half = 1 << (g - 1)
    return kept + (1 if (low > half or (low == half and (kept & 1))) else 0)


def exact_rne(p: int, x: int, my: int) -> int:
    """The correctly rounded significand of x / my, x in [my, 2 my), in units of 2^(1-p), by integer arithmetic written
    from the definition (nearest, ties to even)."""
    j, r = divmod(x << (p - 1), my)
    if 2 * r > my or (2 * r == my and j & 1):
        j += 1
    return j


def group_plants(tool: Tool, built_tree: str, work: str) -> None:
    sp32 = H.SPACES["div32-hard"]
    sp64 = H.SPACES["div64-hard"]
    f0a = [s for n_, s, c in sp32.segs if n_ == "F0A"][0]
    # CONTROL: the unplanted tool and generator pass what the plants below fail
    lo, hi = f0a + 100, f0a + 164
    rc, out, m = tool.run("div32-hard", lo, hi, "rne")
    ok, why = judge("div32-hard", "rne", 4, lo, hi, rc, out, m)
    check("plant CONTROL: the real tool passes the F0A slice the plants use, the independent skip count included", ok, why)
    rc, out = run_generator(os.path.join(ROOT, "python", "hardcases.py"), "verify", "div32-hard", 300)
    check("plant CONTROL: the real generator's exact verification passes the sample the Python plants use",
          rc == 0 and "every case verified in exact integers" in out, out[-200:])

    # (1a) a construction off by one, in the generator: its exact verification must fail, by name
    for what, edits, name_expected in (
            ("F0's dividend two too high (the congruence off by one step)",
             [("    x = r + my", "    x = r + my + 2")], "F0 closest approach"),
            ("F0's doubled quotient never built (a genuine construction reported as a skip)",
             [("    elif x % 2 == 0:\n        mx = x >> 1", "    elif False:\n        mx = x >> 1")], "F0 skip is genuine"),
            ("F2's divisor one ulp too far from 1.0", [("_enc(sp, sp.bias, sp.P1 + k) if v & 1 == 0",
                                                         "_enc(sp, sp.bias, sp.P1 + k + 1) if v & 1 == 0")], "F2 divisor"),
            ("F3a's odd quotient shifted one place too far", [("    return _enc(sp, 4, o << (s - 1)), _enc(sp, sp.bias + s + 3, sp.P1)",
                                                               "    return _enc(sp, 4, o << (s - 1)), _enc(sp, sp.bias + s + 4, sp.P1)")],
             "F3a tie in the subnormal strip"),
            ("F3b's dividend exponent one too high for the designed quotient exponent",
             [("    ea, eb = 1 + max(eq, 0), 1 + max(-eq, 0)", "    ea, eb = 2 + max(eq, 0), 1 + max(-eq, 0)")],
             "F3b the operand exponents differ"),
            ("S0's input rounded the wrong way (the nearest input off by one)",
             [("    k = (roots[r] ** 2 + (1 << (s - 1))) >> s", "    k = (roots[r] ** 2 + (1 << (s - 1))) // size + 1")],
             "S0 odd-square input")):
        gp = plant_generator(work, "p%d" % PLANT_N[0], edits)
        PLANT_N[0] += 1
        mode = "sqrt64-hard" if "S0" in what else "div32-hard"
        rc, out = run_generator(gp, "verify", mode, 300)
        check(f"plant (generator): {what}: `verify` exits 1 and names '{name_expected}'",
              rc == 1 and out.startswith("FAILED " + name_expected), f"rc {rc}: {out[:240]}")

    # (1b) the same off by one in the C tool: its own exact check refuses by name; with that check blinded too it runs
    # (and its operands are not the hard ones), and only the agreement with the generator sees it
    off = [("        x = r + my;\n", "        x = r + my + 2;\n")]
    wo = plant_tool(built_tree, work, "offbyone", off)
    if wo is None:
        check("plants: the off-by-one build builds", False, "make failed")
    else:
        rc, out, m = wo.run("div32-hard", lo, hi, "rne")
        check("plant (tool): a construction off by one is refused by the tool's own exact check, by name, exit 2, no verdict",
              rc == 2 and "the exact check of index" in out and "the construction is broken" in out and m is None, f"rc {rc}: {out[:240]}")
    blind = off + [("static int f0_exact(int p, uint64_t x, uint64_t my, int target, int plus)\n{\n",
                    "static int f0_exact(int p, uint64_t x, uint64_t my, int target, int plus)\n{\n    (void)p; (void)x; (void)my; (void)target; (void)plus;\n    return 1;\n")]
    wb = plant_tool(built_tree, work, "offbyone-blind", blind)
    if wb is None:
        check("plants: the blinded off-by-one build builds", False, "make failed")
    else:
        rc, out, m = wb.run("div32-hard", lo, hi, "rne")
        ok_blind, why_blind = judge("div32-hard", "rne", 4, lo, hi, rc, out, m, skips=False)
        check("plant (tool, check blinded): the same off-by-one runs and PASSES the soak, with every count as promised "
              "(a case that is not hard is as good a test of the library as any: only its hardness is lost)",
              ok_blind, why_blind)
        rc, dump, err = wb.raw("hard-dump", "div32-hard", lo, hi)
        want = "\n".join(H.dump_lines("div32-hard", lo, hi)) + "\n"
        differ = [i for i, (a, b) in enumerate(zip(dump.splitlines(), want.splitlines())) if a != b]
        check("plant (tool, check blinded): and the agreement with python/hardcases.py's dump catches it: the same number of "
              "lines, and lines differ, four at a time (the four slots of an index)",
              rc == 0 and len(dump.splitlines()) == len(want.splitlines()) and len(differ) > 0 and len(differ) % 4 == 0,
              f"rc {rc}, {len(differ)} lines differ")

    # (2) a slice short by one: the encodings, and the skip slots, counted one too few
    wc = plant_tool(built_tree, work, "count", [("        hencodings++;\n", "        hencodings += (idx != lo);\n")])
    if wc is not None:
        rc, out, m = wc.run("div32-hard", lo, hi, "rne")
        ok, why = judge("div32-hard", "rne", 4, lo, hi, rc, out, m)
        okd, whyd = driver_view("div32-hard", "rne", 4, lo, hi, rc, out)
        check("plant (count): a tool that counts one encoding too few is caught by the checks every slice must meet "
              "(E is the slice's indices), and the stress driver's own parse_soak refuses its line by name",
              not ok and "encodings for a slice of" in why and not okd and "encodings where the slice has" in whyd,
              f"{why} / {whyd}")
    d_start = [s for n_, s, c in sp32.segs if n_ == "F0D"][0]
    ws = plant_tool(built_tree, work, "skipcount", [("            hskipped += (uint64_t)sp->k;\n", "            hskipped += (uint64_t)sp->k - 1;\n")])
    if ws is not None:
        rc, out, m = ws.run("div32-hard", d_start, d_start + 200, "rne")
        ok, why = judge("div32-hard", "rne", 4, d_start, d_start + 200, rc, out, m)
        okd, whyd = driver_view("div32-hard", "rne", 4, d_start, d_start + 200, rc, out)
        check("plant (cover): a tool whose skipped slots are one short an index is caught by cases + skipped = k x E, "
              "the cover rule: here and by the stress driver's own parse_soak",
              not ok and "is not 4 x" in why and not okd and "skipped make" in whyd, f"{why} / {whyd}")

    # (3) a mode that skips every index
    skipall = [("        uint64_t my = f0_divisor(sp, fam, j), r, x, mx;\n",
                "        uint64_t my = f0_divisor(sp, fam, j), r, x, mx;\n        if (fam == H_F0A) return 0;\n")]
    wa = plant_tool(built_tree, work, "skipall", skipall)
    if wa is None:
        check("plants: the skip-everything build builds", False, "make failed")
    else:
        rc, out, m = wa.run("div32-hard", f0a, f0a + 4096, "rne")
        check("plant (skip all): a mode that skips every index of a 4,096-index slice is REFUSED by name (exit 2, no verdict "
              "line), not recorded as an empty pass", rc == 2 and m is None and "every one of the 4096 indices" in out
              and "refused" in out, f"rc {rc}: {out[:240]}")
        rc, out, m = wa.run("div32-hard", f0a, f0a + 8, "rne")
        ok, why = judge("div32-hard", "rne", 4, f0a, f0a + 8, rc, out, m)
        check("plant (skip all): an 8-index slice (below the 64 the refusal needs) is not refused and prints 0 cases and 32 "
              "skipped, and the independent skip count catches it", (not ok) and m is not None and int(m.group(3)) == 0
              and int(m.group(7)) == 32 and "independent count" in why, why)
    wn = plant_tool(built_tree, work, "skipall-norefuse", skipall + [("    if (!rc && !cases && hi - lo >= HMIN_REFUSE) {", "    if (0) {")])
    if wn is not None:
        rc, out, m = wn.run("div32-hard", f0a, f0a + 4096, "rne")
        ok_blind, why_blind = judge("div32-hard", "rne", 4, f0a, f0a + 4096, rc, out, m, skips=False)
        ok_full, why_full = judge("div32-hard", "rne", 4, f0a, f0a + 4096, rc, out, m)
        okd, whyd = driver_view("div32-hard", "rne", 4, f0a, f0a + 4096, rc, out)
        check("plant (skip all, refusal removed): the tool prints 0 cases and 4 x 4096 skipped, no mismatch, exit 0 - and the "
              "stress driver's own parse_soak ACCEPTS it under the cover rule (cases + skipped = k x E), as it accepts an "
              "all-NaN slice of cvtto32-all", ok_blind and okd, f"{why_blind} / {whyd}")
        check("plant (skip all, refusal removed): and the independent count of the indices that skip catches it",
              not ok_full and "independent count" in why_full and m is not None and int(m.group(7)) == 4 * 4096, why_full)

    # a LIBRARY defect that only the hard cases expose: the division's guard test (host/src/divsqrt.c, div_chunk) takes the
    # half-ulp discriminant for zero - an exact tie - when it is below 2^-(p-1) of the remainder: blind to a quotient that
    # close to a midpoint, so wrong under round-to-nearest-even on about half of the closest approaches to a midpoint, and
    # on about 10^-16 of random fp64 draws. A copy of the library, built.
    guard_helper = ('static int plant_tiny(const cft_fmt_desc *f, const uint8_t *t2, const uint8_t *r2, size_t i)\n'
                    '{   /* PLANT (a test\'s, never the library\'s): the discriminant t2 is "zero" when below 2^-(p-1) of r2 */\n'
                    '    cft_bn x, y;\n    lane_load(f, t2, i, &x);\n    lane_load(f, r2, i, &y);\n'
                    '    return (int)cft_bn_extract(&x, f->man_w, f->exp_w) + (f->man_w - 1) <\n'
                    '           (int)cft_bn_extract(&y, f->man_w, f->exp_w);\n}\n\n')
    wl = plant_tool(built_tree, work, "libguard",
                    [("static cft_status div_chunk(cft_device *dev, const cft_fmt_desc *f,\n",
                      guard_helper + "static cft_status div_chunk(cft_device *dev, const cft_fmt_desc *f,\n"),
                     ("        } else if (lane_mag_zero(f, t2, i)) {\n            guard = 1;                       /* exact tie */\n",
                      "        } else if (lane_mag_zero(f, t2, i) || plant_tiny(f, t2, r2, i)) {\n"
                      "            guard = 1;                       /* exact tie */\n")], rel=("src", "divsqrt.c"))
    if wl is None:
        check("plants: the library-guard plant builds", False, "make failed")
    else:
        k0 = [s for n_, s, c in sp64.segs if n_ == "F0K"][0]
        klo, khi = k0, k0 + 700_000                    # about 2 million cases, half of them closest approaches to a midpoint
        operands = {c[0] for i in range(klo, klo + 4000) for c in H.gen("div64-hard", i) if c is not None}
        rc0, out0, m0 = tool.run("div64-hard", klo, khi, "rne")
        ok0, why0 = judge("div64-hard", "rne", 4, klo, khi, rc0, out0, m0)
        check("plant (library guard) CONTROL: the real library passes the slice of F0K, about 2 million cases, under rne",
              ok0 and m0 is not None and int(m0.group(3)) > 1_500_000, why0)
        rc, out, m = wl.run("div64-hard", klo, khi, "rne")
        vm = int(m.group(4)) if m else 0
        named = [int(a, 16) for a in re.findall(r"^  MISMATCH rne a=0x([0-9a-f]+)", out, re.M)]
        check(f"plant (library guard): the same slice FAILS on the library whose guard test is blind to the closest approach "
              f"to a midpoint: {vm:,} value mismatches (about a quarter of the cases), exit 1, operands named",
              rc == 1 and vm > 200_000 and named, f"rc {rc}, {vm} mismatches, named {[hex(a) for a in named[:3]]}")
        rc, out, m = wl.run("div64-hard", klo, khi, "rtz")
        check("plant (library guard): and passes under rtz - the defect is in the tie only, the directed modes never see it",
              rc == 0 and m is not None and int(m.group(4)) == 0 and int(m.group(5)) == 0, out[:200])
        e = dict(os.environ)
        pr = subprocess.run(NICE + [wl.path, "div64", "2000000", "1", "rne"], capture_output=True, text=True, timeout=900, env=e)
        mr = re.search(r"^div64 rne: (\d+) cases, (\d+) value mismatches, (\d+) flag mismatches$", pr.stdout, re.M)
        check("plant (library guard): while the soak's RANDOM mode passes the same library on as many cases (2,000,000 banded "
              "div64 draws, rne, seed 1): the sampler never reaches the class (about 1.5e-16 a draw)",
              pr.returncode == 0 and mr is not None and (int(mr.group(1)), int(mr.group(2)), int(mr.group(3))) == (2000000, 0, 0),
              pr.stdout[-200:])

    # a compiler with no 128-bit integer: the three modes and the three sub-modes are named and refused, exit 2, and the
    # random modes still run (a 32-bit host builds the soak tool unchanged)
    w1 = plant_tool(built_tree, work, "noint128", [], extra=["CFLAGS=-O2 -U__SIZEOF_INT128__"])
    if w1 is None:
        check("plants: the build without __int128 builds", False, "make failed")
    else:
        bad = []
        for args in (("hard-space", "div32-hard"), ("hard-dump", "div32-hard", 0, 4), ("hard-count", "div32-hard", 0, 4),
                     ("div32-hard", 0, 64, "rne"), ("div64-hard", 0, 64, "rne"), ("sqrt64-hard", 0, 64, "rmm")):
            rc, out, err = w1.raw(*args)
            if not (rc == 2 and "need a 128-bit integer type" in err and " cases," not in out):
                bad.append((args, rc, err[-80:]))
        rc, out, err = w1.raw("div32", 4000, 1, "rne")
        check("plant (no __int128): without a 128-bit integer type the hard modes and sub-modes are refused by name, exit 2, "
              "and the random modes still run", not bad and rc == 0 and "div32 rne: 4000 cases" in out, f"{bad} / rc {rc}")

    # (4) the prototype's defective division: 40 extra bits, ties-to-even on them. In Python, as the prototype does.
    from_seed = os.path.join(ROOT, "docs", "studies", "swp-a")
    sys.path.insert(0, from_seed)
    import seed_audit as sa  # noqa: E402  (the port of the soak's sampler, held there to the real tool)
    sp64 = H.SPACES["div64-hard"]
    p = 53
    g = 40
    N = 100_000
    def numerator(mx, my):
        """The sampler's convention: the dividend significand doubled when it is below the divisor's, so that the
        quotient is in [1, 2) and both functions below work on one grid."""
        return mx if mx >= my else 2 * mx

    cons = []
    i = [s for n_, s, c in sp64.segs if n_ == "F0K"][0]
    while len(cons) < N:
        if i % 4 < 2:                                   # the midpoint target (v = 0, 1); F0K starts at a multiple of 4
            c = H.base_case(sp64, i)
            if c is not None:
                mx = (c[0] & (sp64.P1 - 1)) | sp64.P1
                my = (c[1] & (sp64.P1 - 1)) | sp64.P1
                cons.append((numerator(mx, my), my))
        i += 1
    fail_cons = sum(flawed_rne(p, x, my, g) != exact_rne(p, x, my) for x, my in cons)
    r = sa.Rng(0x50AC0003)
    nrand = fail_rand = 0
    while nrand < N:
        a, b = sa.banded64(r), sa.banded64(r)
        ea, eb = (a >> 52) & 2047, (b >> 52) & 2047
        if ea in (0, 2047) or eb in (0, 2047):
            continue
        mx, my = (a & ((1 << 52) - 1)) | (1 << 52), (b & ((1 << 52) - 1)) | (1 << 52)
        nrand += 1
        x = numerator(mx, my)
        fail_rand += flawed_rne(p, x, my, g) != exact_rne(p, x, my)
    check(f"plant (40 extra bits): the division that computes 40 extra bits and rounds ties-to-even on them fails on "
          f"{fail_cons:,} of {N:,} closest-approach-to-a-midpoint pairs the generator builds (div64-hard's F0K, "
          f"{100.0 * fail_cons / N:.1f} per cent)", fail_cons >= 0.2 * N, f"{fail_cons}")
    check(f"plant (40 extra bits): and on {fail_rand} of as many ({N:,}) of the soak's own random draws (the sampler's port "
          f"in docs/studies/swp-a/seed_audit.py, held there to the real tool)", fail_rand == 0, f"{fail_rand}")
    fail80 = sum(flawed_rne(p, x, my, 80) != exact_rne(p, x, my) for x, my in cons[:20000])
    check("plant (40 extra bits) CONTROL: with 80 extra bits the same method is correct on every one of 20,000 constructed pairs "
          "(the set does not simply fail everything)", fail80 == 0, f"{fail80}")


# --- the wide modes (parcel HXa) -------------------------------------------------------------------

WIDE_HARD = [("div128-hard", 4), ("div256-hard", 4), ("sqrt128-hard", 1), ("sqrt256-hard", 1)]
F64HARD = [("div128-f64hard", "div64-hard", 4), ("div256-f64hard", "div64-hard", 4),
           ("sqrt128-f64hard", "sqrt64-hard", 1), ("sqrt256-f64hard", "sqrt64-hard", 1)]
SLICE = [f"{op}{w}-f32" for op in ("sqrt", "recip") for w in (64, 128, 256)]
WINDOWS = [f"{op}{w}-win-{h}" for op in ("sqrt", "recip") for w in (128, 256) for h in H.WIN_H]
ATTRS5 = ["rne", "rtz", "rdn", "rup", "rmm"]
# the fp32 slice's specials: zeros and subnormals of both signs, the subnormal/normal boundary, 1.0, the largest
# finite and the infinities, the sNaN/qNaN boundary, the top of the negative NaNs
SLICE_RANGES = [(0, 0x800), (0x007FFC00, 0x00800400), (0x3F7FFC00, 0x3F800400), (0x7F7FFC00, 0x7F800400),
                (0x7FBFFC00, 0x7FC00400), (0x80000000, 0x80000800), (0xBF7FFC00, 0xBF800400),
                (0xFF7FFC00, 0xFF800400), ((1 << 32) - 0x800, 1 << 32)]
WINDOW_RANGES = [(0, 0x800), (0x7FFFFC00, 0x80000400), ((1 << 32) - 0x800, 1 << 32)]
LADDER = re.compile(r"^  ladder: (\d+) of the (\d+) cases rounded to (fp32|fp64) and checked against the CPU's own, "
                    r"(\d+) value and (\d+) flag disagreements$", re.M)


def wide_space_k(mode: str) -> int:
    for m, k in WIDE_HARD:
        if m == mode:
            return k
    for m, _base, k in F64HARD:
        if m == mode:
            return k
    return 1


def wide_ref_space(mode: str):
    """The generator's space a wide mode runs over (None for the slice and window modes, which skip nothing)."""
    for m, _k in WIDE_HARD:
        if m == mode:
            return m
    for m, base, _k in F64HARD:
        if m == mode:
            return base
    return None


def hard_slices(space: str, n: int = 160):
    """(what, lo, hi): every segment's start and end and every boundary, n indices each, in a generator space."""
    sp = H.SPACES[space]
    out = []
    for name, start, count in sp.segs:
        m = min(count, n)
        out.append((f"the start of {name}", start, start + m))
        out.append((f"the end of {name}", start + count - m, start + count))
    for (n1, s1, c1), (n2, s2, c2) in zip(sp.segs, sp.segs[1:]):
        out.append((f"across {n1} / {n2}", s2 - min(n // 2, c1), s2 + min(n // 2, c2)))
    return out


def wide_slices(mode: str):
    space = wide_ref_space(mode)
    if space:
        return hard_slices(space)
    return [(f"[{lo:#x}, {hi:#x})", lo, hi) for lo, hi in (SLICE_RANGES if mode.endswith("-f32") else WINDOW_RANGES)]


def wide_judge(mode, attr, lo, hi, rc, out, m):
    """judge() for a wide mode: the skips against the generator's space where there is one, none elsewhere; and the
    ladder line, where the mode has one, with every case of the slice through it and no disagreement."""
    k = wide_space_k(mode)
    space = wide_ref_space(mode)
    if m is None:
        return False, f"no verdict line: rc {rc}: {out[-300:]}"
    cases, vm, fm, enc, skp = int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6)), int(m.group(7))
    if (m.group(1), m.group(2)) != (mode, attr):
        return False, f"the verdict is for {m.group(1)} {m.group(2)}"
    if rc != 0 or vm or fm:
        return False, f"rc {rc}, {vm} value and {fm} flag mismatches: {out[:400]}"
    if enc != hi - lo or cases + skp != k * enc:
        return False, f"{cases} cases + {skp} skipped, {enc} encodings, for a slice of {hi - lo} at k = {k}"
    want = k * (skipped_indices(space, lo, hi) if space else 0)
    if skp != want:
        return False, f"{skp} slots skipped where the generator's count is {want}"
    ladder = mode.endswith("-f32") or mode.endswith("-f64hard")
    lm = LADDER.search(out)
    if ladder and not (mode.startswith("div") and attr == "rmm"):
        if not lm or int(lm.group(1)) != cases or int(lm.group(2)) != cases or lm.group(4) != "0" or lm.group(5) != "0":
            return False, f"the ladder line is missing or wrong: {lm.group(0) if lm else None!r}"
    elif lm and int(lm.group(1)) != 0:
        return False, f"a ladder ran where none should: {lm.group(0)!r}"
    return True, ""


def group_wide_agree(wtool: Tool) -> None:
    bad = []
    for mode in SLICE + WINDOWS + [m for m, _k in WIDE_HARD] + [m for m, _b, _k in F64HARD]:
        rc, out, err = wtool.raw("hard-space", mode)
        space = wide_ref_space(mode)
        if space:
            want = H.space_lines(space)
            want[0] = want[0].replace(space, mode, 1)
        else:
            want = H.plain_lines("space", mode)
        if rc != 0 or out != "\n".join(want) + "\n":
            bad.append((mode, rc, out[:120]))
    check("wide-agree: `hard-space` of all 30 new mode words is the generator's table (the f64hard names their fp64 "
          "space's under their own name)", not bad and len(SLICE + WINDOWS) == 22, str(bad[:3]))
    for mode, _k in WIDE_HARD:
        sp = H.SPACES[mode]
        rnd = random.Random(20261026)
        ranges = []
        for name, start, count in sp.segs:
            n = min(count, 40)
            ranges += [(start, start + n), (start + count - n, start + count)]
            for _ in range(3):
                lo = start + rnd.randrange(0, max(count - 12, 1))
                ranges.append((lo, min(lo + 12, start + count)))
        for (n1, s1, c1), (n2, s2, c2) in zip(sp.segs, sp.segs[1:]):
            ranges.append((s2 - min(8, c1), s2 + min(8, c2)))
        bad_d = bad_c = lines = 0
        first = ""
        for lo, hi in ranges:
            rc, out, err = wtool.raw("hard-dump", mode, lo, hi)
            want = "\n".join(H.dump_lines(mode, lo, hi)) + "\n"
            lines += want.count("\n")
            if rc != 0 or out != want:
                bad_d += 1
                if not first:
                    a, b = out.splitlines(), want.splitlines()
                    d = next((i for i in range(min(len(a), len(b))) if a[i] != b[i]), None)
                    first = f"[{lo}, {hi}): rc {rc} {err[-100:]!r}, C {a[d] if d is not None else '-'!r} " \
                            f"against Python {b[d] if d is not None else '-'!r}"
            rc, out, err = wtool.raw("hard-count", mode, lo, hi)
            if rc != 0 or out != "\n".join(H.count_lines(mode, lo, hi)) + "\n":
                bad_c += 1
        check(f"wide-agree: {mode}: `hard-dump` equals python/hardcases.py's dump line for line over {len(ranges)} ranges "
              f"({lines:,} lines: every segment's ends and boundaries, indices from a fixed seed)", bad_d == 0,
              f"{bad_d} ranges differ; first {first}")
        check(f"wide-agree: {mode}: `hard-count` equals the generator's count over the same ranges", bad_c == 0,
              f"{bad_c} ranges differ")
    bad_p = []
    for mode in SLICE + WINDOWS:
        for lo, hi in (SLICE_RANGES if mode.endswith("-f32") else WINDOW_RANGES):
            lo2, hi2 = lo, min(hi, lo + 300)
            rc, out, err = wtool.raw("hard-dump", mode, lo2, hi2)
            if rc != 0 or out != "\n".join(H.plain_lines("dump", mode, lo2, hi2)) + "\n":
                bad_p.append((mode, lo2, rc))
            rc, out, err = wtool.raw("hard-count", mode, lo2, hi2)
            if rc != 0 or out != "\n".join(H.plain_lines("count", mode, lo2, hi2)) + "\n":
                bad_p.append((mode, lo2, "count", rc))
    check(f"wide-agree: the {len(SLICE + WINDOWS)} slice and window modes: `hard-dump` (the widened fp32 encodings - "
          f"zeros, subnormals, infinities and NaNs of both signs among them - and the windows' x) and `hard-count` equal "
          f"the generator's over {len(SLICE_RANGES)} or {len(WINDOW_RANGES)} ranges each", not bad_p, str(bad_p[:4]))
    bad_f = []
    for mode, base, _k in F64HARD:
        for lo, hi in ((0, 50), (H.SPACES[base].total - 50, H.SPACES[base].total)):
            for sub in ("hard-dump", "hard-count"):
                a = wtool.raw(sub, mode, lo, hi)
                b = wtool.raw(sub, base, lo, hi)
                if a[0] != 0 or a[1] != b[1]:
                    bad_f.append((mode, sub, lo))
    check("wide-agree: the f64hard names' `hard-dump` and `hard-count` are div64-hard's and sqrt64-hard's own lines",
          not bad_f, str(bad_f[:3]))


def group_wide_run(wtool: Tool) -> None:
    t0 = time.time()
    n = bad = 0
    for mode in SLICE + WINDOWS + [m for m, _k in WIDE_HARD] + [m for m, _b, _k in F64HARD]:
        for what, lo, hi in wide_slices(mode):
            for attr in ATTRS5:
                rc, out, m = wtool.run(mode, lo, hi, attr)
                ok, why = wide_judge(mode, attr, lo, hi, rc, out, m)
                if ok:
                    ok, why = driver_view(mode, attr, wide_space_k(mode), lo, hi, rc, out)
                n += 1
                if not ok:
                    bad += 1
                    check(f"wide-run: {mode} {attr} over {what} [{lo}, {hi})", False, why)
    check(f"wide-run: all 30 new modes under all five attributes over their slices ({n} runs: the fp32 slice's specials, "
          f"the windows' ends and middle, every hard segment's ends and boundaries): each passes, every count as promised, "
          f"skips equal to the generator's, the ladder through every case where there is one, and the stress driver's "
          f"parse_soak accepts each under its cover rule", bad == 0, f"{bad} of {n} failed")
    print(f"      ({n} wide slices in {time.time() - t0:.0f} s)")


def group_wide_sabotage(wtool: Tool) -> None:
    bad1, bad2 = [], []
    for mode in SLICE + WINDOWS + [m for m, _k in WIDE_HARD] + [m for m, _b, _k in F64HARD]:
        what, lo, hi = wide_slices(mode)[-1] if mode.endswith("hard") else wide_slices(mode)[2 if mode.endswith("-f32")
                                                                                              else 1]
        for attr in ("rne", "rmm"):
            rc0, out0, m0 = wtool.run(mode, lo, hi, attr)
            rc, out, m = wtool.run(mode, lo, hi, attr, env={"CFT_SOAK_SABOTAGE": "1"})
            vm = int(m.group(4)) if m else 0
            named = re.findall(r"^  MISMATCH " + attr + r" a=0x([0-9a-f]+)", out, re.M)
            if not (rc0 == 0 and rc == 1 and vm > 0 and named):
                bad1.append((mode, attr, rc0, rc, vm, len(named)))
            if mode.endswith("-f32") or mode.endswith("-f64hard"):
                if mode.startswith("div") and attr == "rmm":
                    continue
                rc, out, m = wtool.run(mode, lo, hi, attr, env={"CFT_SOAK_SABOTAGE": "2"})
                lad = re.findall(r"^  MISMATCH " + attr + r" ladder a=0x", out, re.M)
                prim = re.findall(r"^  MISMATCH " + attr + r" a=0x", out, re.M)
                lm = LADDER.search(out)
                if not (rc == 1 and lad and not prim and lm and int(lm.group(4)) > 0 and m and
                        int(m.group(4)) == int(lm.group(4))):
                    bad2.append((mode, attr, rc, len(lad), len(prim)))
    check("wide-sabotage: CFT_SOAK_SABOTAGE=1 (the library's first result of each batch flipped) fails all 30 new modes "
          "under rne and rmm - exit 1, value mismatches, operands named - and the same slices pass without it", not bad1,
          str(bad1[:4]))
    check("wide-sabotage: CFT_SOAK_SABOTAGE=2 (the CPU's first narrow result of each batch flipped) fails every slice and "
          "f64hard mode by the ladder alone - exit 1, 'MISMATCH <attribute> ladder' lines and no other, the verdict's "
          "value mismatches the ladder's own count - so the second check can fail", not bad2, str(bad2[:4]))


def group_wide_refuse(wtool: Tool, tool: Tool) -> None:
    bad = []
    for mode in SLICE + WINDOWS + [m for m, _k in WIDE_HARD] + [m for m, _b, _k in F64HARD]:
        space = wide_ref_space(mode)
        total = H.SPACES[space].total if space else 1 << 32
        for args in ((5, 5), (9, 5), (0, total + 1), ("abc", 5), (-1, 5)):
            rc, out, err = wtool.raw(mode, *args, "rne")
            if not (rc == 2 and f"need 0 <= lo < hi <= {total} (the indices of {mode})" in err and " cases," not in out):
                bad.append((mode, args, rc, err[-80:]))
    check("wide-refuse: an empty, reversed, too long, garbage or negative range is refused by name for every new mode, "
          "exit 2, nothing run", not bad, str(bad[:3]))
    bad = []
    for mode in ("sqrt128-f32", "div256-hard", "recip128-win-key", "div128-f64hard"):
        rc, out, err = tool.raw(mode, 0, 64, "rne")
        if not (rc == 2 and f"unknown op {mode}" in err and " cases," not in out):
            bad.append((mode, rc, err[-80:]))
        rc, out, err = tool.raw("hard-space", mode)
        if not (rc == 2 and f"unknown hard-case mode {mode}" in err):
            bad.append(("hard-space", mode, rc))
    check("wide-refuse: the default build (no MPFR=1) refuses a wide mode word by name as an unknown op, and its "
          "hard-space as an unknown hard-case mode, exit 2, nothing run", not bad, str(bad[:3]))
    rc, out, err = wtool.raw("div128-hard", 0, 64)
    check("wide-refuse: the MPFR build's usage names the wide modes after every line the default prints",
          rc == 2 and "div32-hard|div64-hard <lo> <hi>" in err and "-win-{ones,zeros,alt,key}" in err
          and "built with MPFR" in err, err[-300:])


def group_wide_plants(wtree: str, work: str) -> None:
    # (1) the wide F0 builder's dividend two too high: the tool's own exact check refuses by name
    wp = plant_tool(wtree, work, "wide-f0", [("        mpz_add(wz_x, wz_r, wz_my);\n",
                                               "        mpz_add(wz_x, wz_r, wz_my);\n        mpz_add_ui(wz_x, wz_x, 2);\n")],
                    extra=["MPFR=1"])
    if wp is None:
        check("wide-plants: the wide F0 plant builds", False, "make failed")
    else:
        f0a = [s for n_, s, c in H.SPACES["div128-hard"].segs if n_ == "F0A"][0]
        rc, out, m = wp.run("div128-hard", f0a, f0a + 64, "rne")
        check("wide-plants: a wide F0 construction off by two is refused by the tool's own exact check, by name, exit 2, "
              "no verdict", rc == 2 and "the exact check of index" in out and m is None, f"rc {rc}: {out[:240]}")
    # (2) a widening that drops a subnormal's last bit: the ladder and the dump agreement both see it
    wl = plant_tool(wtree, work, "wide-widen", [("        uint64_t m = ex ? frac | ((uint64_t)1 << N->man_w) : frac;\n",
                                                 "        uint64_t m = ex ? frac | ((uint64_t)1 << N->man_w) : (frac > 1 ? frac & ~(uint64_t)1 : frac);\n")],
                    extra=["MPFR=1"])
    if wl is None:
        check("wide-plants: the widening plant builds", False, "make failed")
    else:
        rc, out, m = wl.run("sqrt128-f32", 0, 0x800, "rne")
        lm = LADDER.search(out)
        rc2, dump, err = wl.raw("hard-dump", "sqrt128-f32", 0, 300)
        check("wide-plants: a widening that drops a subnormal's last bit passes the MPFR check (the library and MPFR see "
              "the same wrong input) and is caught by the ladder against the CPU's own fp32 root, and by the dump "
              "agreement with the generator",
              rc == 1 and lm is not None and int(lm.group(4)) > 0 and "MISMATCH rne ladder" in out
              and dump != "\n".join(H.plain_lines("dump", "sqrt128-f32", 0, 300)) + "\n", f"rc {rc}: {out[:300]}")
    # (3) the oracle under the wrong attribute (rtz asked, rne given): caught
    wo = plant_tool(wtree, work, "wide-oracle", [("static const mpfr_rnd_t WMR[5] = { MPFR_RNDN, MPFR_RNDZ,",
                                                  "static const mpfr_rnd_t WMR[5] = { MPFR_RNDN, MPFR_RNDN,")],
                    extra=["MPFR=1"])
    if wo is None:
        check("wide-plants: the oracle plant builds", False, "make failed")
    else:
        rc, out, m = wo.run("recip128-win-key", 0, 2048, "rtz")
        check("wide-plants: an oracle that rounds rtz as rne fails recip128-win-key under rtz, value mismatches named",
              rc == 1 and m is not None and int(m.group(4)) > 0, f"rc {rc}: {out[:200]}")


# --- the baseline ----------------------------------------------------------------------------------

def group_unchanged(tool: Tool, base_dir: str, work: str, label: str = "") -> None:
    rev = os.path.basename(os.path.normpath(base_dir))
    base = copy_tree(base_dir, os.path.join(work, "baseline" + label.replace(" ", "-")))
    old = build(base, f"the baseline {rev}")
    if old is None:
        check(f"unchanged: the baseline {rev} builds", False, "make failed")
        return
    cases = []
    for seed in (1, 77):
        for m in ("rne", "rtz", "rdn", "rup"):
            cases += [("div32", 200000, seed, m), ("div64", 200000, seed, m), ("sqrt64", 200000, seed, m)]
    cases += [("div32", c, 5, "rne") for c in (1, 4095, 4096, 4097, 12289)]
    cases += [("sqrt64", 4097, 3, "rup"), ("div64", 4097, 3, "rdn")]
    for m in ("rne", "rtz", "rdn", "rup", "rmm"):
        cases += [("sqrt32", 0, 200000, m), ("sqrt32", 0x3F800000, 0x3F800000 + 100000, m),
                  ("sqrt32", 0x7F7FFF00, 0x7F800100, m)]
    # the hard-case modes (parcel HXa added them here): every segment's start under every attribute each takes, and
    # slices across the spaces
    for mode, attrs, _k in MODES:
        for name, start, count in H.SPACES[mode].segs:
            for m in attrs:
                cases.append((mode, start, start + min(count, 2000), m))
        total = H.SPACES[mode].total
        cases += [(mode, total // 3, total // 3 + 20000, "rne"), (mode, total - 5000, total, attrs[-1])]
    refusals = [("div32", 100, 1, "rmm"), ("div64", 100, 1, "rmm"), ("sqrt64", 100, 1, "rmm"), ("div32", 100, 1, "rtx"),
                ("nosuchop", 100, 1, "rne"), ("div64-hard", 0, 64, "rmm"), ("div32-hard", 5, 5, "rne"),
                ("sqrt64-hard", 0, 4456449, "rne")]
    subs = []
    for mode, _attrs, _k in MODES:
        total = H.SPACES[mode].total
        subs += [("hard-space", mode), ("hard-dump", mode, 0, 3000), ("hard-dump", mode, total - 3000, total),
                 ("hard-count", mode, 0, 20000), ("hard-count", mode, total - 20000, total)]
    subs += [("hard-space", "nosuch"), ("hard-dump", "div64-hard", 5, 5)]
    n = same = 0
    for args in subs:
        a = [str(x) for x in args]
        outs = []
        for t in (old, tool):
            pr = subprocess.run(NICE + [t.path] + a, capture_output=True, text=True, timeout=600)
            outs.append((pr.returncode, pr.stdout, pr.stderr))
        n += 1
        if outs[0] == outs[1]:
            same += 1
        else:
            check(f"unchanged{label}: {' '.join(a)} prints the same bytes and exits the same", False,
                  f"{outs[0][0]} vs {outs[1][0]}")
    for job, a1, a2, attr in cases + refusals:
        a = [job, str(a1), str(a2), attr]
        outs = []
        for t in (old, tool):
            pr = subprocess.run(NICE + [t.path] + a, capture_output=True, text=True, timeout=600)
            outs.append((pr.returncode, pr.stdout, pr.stderr))
        n += 1
        if outs[0] == outs[1]:
            same += 1
        else:
            check(f"unchanged{label}: {' '.join(a)} prints the same bytes and exits the same", False,
                  f"{outs[0][0]} vs {outs[1][0]}")
    for env in ({"CFT_SOAK_SABOTAGE": "1"}, {"CFT_SOAK_SABOTAGE": "2"}):
        for job, a1, a2, attr in (("div32", 100000, 3, "rne"), ("div64", 100000, 3, "rup"), ("sqrt64", 100000, 3, "rdn"),
                                  ("sqrt32", 0, 100000, "rmm"), ("div64-hard", 21250240, 21252240, "rne"),
                                  ("sqrt64-hard", 262144, 266240, "rmm")):
            a = [job, str(a1), str(a2), attr]
            outs = []
            for t in (old, tool):
                e = dict(os.environ)
                e.update(env)
                pr = subprocess.run(NICE + [t.path] + a, capture_output=True, text=True, timeout=600, env=e)
                outs.append((pr.returncode, pr.stdout, pr.stderr))
            n += 1
            same += outs[0] == outs[1]
            if outs[0] != outs[1]:
                check(f"unchanged{label} (sabotaged {env['CFT_SOAK_SABOTAGE']}): {' '.join(a)}", False, "differs")
    # the argument errors print the usage, which is longer now by design: stdout and the exit status are the same and every
    # line the old usage printed is printed by the new
    for a in (["div32"], ["sqrt32", "0", "10"], ["div32", "100", "1"], []):
        o, nw = [subprocess.run(NICE + [t.path] + a, capture_output=True, text=True, timeout=60) for t in (old, tool)]
        old_lines = [ln.replace(old.path, "X") for ln in o.stderr.splitlines()]
        new_lines = [ln.replace(tool.path, "X") for ln in nw.stderr.splitlines()]
        ok = o.returncode == nw.returncode == 2 and o.stdout == nw.stdout and all(ln in new_lines for ln in old_lines)
        n += 1
        same += ok
        if not ok:
            check(f"unchanged{label} (usage): {' '.join(a)}", False, f"{o.returncode} vs {nw.returncode}")
    check(f"unchanged{label}: {n} invocations of the random, exhaustive and hard-case modes and the hard-case "
          f"sub-commands ({rev}'s tool and this tree's{label}): the same stdout, stderr and exit status for all {same} "
          f"that agree (the usage errors: the old lines all printed)", same == n, f"{n - same} differ")
    print(f"      ({n} invocations compared, {same} identical{label})")


# ---------------------------------------------------------------------------------------------------

def main() -> int:
    args = sys.argv[1:]
    only = set(args[args.index("--only") + 1].split(",")) if "--only" in args else None
    rev = args[args.index("--baseline-tree") + 1] if "--baseline-tree" in args else None
    keep = "--keep" in args

    def want(g: str) -> bool:
        return only is None or g in only

    if os.name != "posix" or not shutil.which("make") or not (shutil.which("cc") or shutil.which("gcc")):
        skip("divsqrt-hard", "needs POSIX with make and a C compiler (the soak requires a 64-bit Linux)")
        print(f"divsqrt-hard test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped")
        return 0
    work = tempfile.mkdtemp(prefix="divsqrt-hard-test-")
    t0 = time.time()
    try:
        tree = copy_tree(ROOT, os.path.join(work, "tree"))
        tool = build(tree, "this tree")
        if tool is None:
            check("build: divsqrt-soak builds in a scratch copy of host/", False, "make failed")
        else:
            for name, fn in (("build", lambda: group_build(tool)), ("agree", lambda: group_agree(tool)),
                             ("special", lambda: group_special(tool)), ("spread", lambda: group_spread(tool)),
                             ("refuse", lambda: group_refuse(tool)), ("sabotage", lambda: group_sabotage(tool)),
                             ("plants", lambda: group_plants(tool, tree, work))):
                if want(name):
                    n0, f0 = CHECKS, len(FAILS)
                    fn()
                    print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            wide = [g for g in ("wide-agree", "wide-run", "wide-sabotage", "wide-refuse", "wide-plants") if want(g)]
            wtool = wtree = None
            if wide or (rev and want("unchanged")):
                # the wide modes' build (parcel HXa): MPFR=1, the system's MPFR (or CFLAGS/LDLIBS from the caller's make)
                wtree = copy_tree(ROOT, os.path.join(work, "tree-mpfr"))
                wtool = build(wtree, "this tree with MPFR=1", ["MPFR=1"])
                if wtool is None:
                    for g in wide:
                        skip(g, "divsqrt-soak does not build with MPFR=1 here (no MPFR or GMP to link)")
                    wide = []
            for name in wide:
                fn = {"wide-agree": lambda: group_wide_agree(wtool), "wide-run": lambda: group_wide_run(wtool),
                      "wide-sabotage": lambda: group_wide_sabotage(wtool),
                      "wide-refuse": lambda: group_wide_refuse(wtool, tool),
                      "wide-plants": lambda: group_wide_plants(wtree, work)}[name]
                n0, f0 = CHECKS, len(FAILS)
                fn()
                print(f"{name}: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            if rev and want("unchanged"):
                n0, f0 = CHECKS, len(FAILS)
                group_unchanged(tool, rev, work)
                if wtool is not None:
                    group_unchanged(wtool, rev, work, " (MPFR=1)")
                else:
                    skip("unchanged (MPFR=1)", "divsqrt-soak does not build with MPFR=1 here")
                print(f"unchanged: {CHECKS - n0} checks, {len(FAILS) - f0} failed")
            elif want("unchanged") and only is not None:
                skip("unchanged", "needs --baseline-tree DIR")
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
    print(f"divsqrt-hard test: {CHECKS} checks, {len(FAILS)} failed, {len(SKIPS)} skipped, {time.time() - t0:.0f} s")
    for f in FAILS:
        print("  FAILED:", f[:300])
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
