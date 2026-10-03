#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The acceptance set: everything that runs on the card today, each entry
one run fixed in this repository - the admission test for a device, and
the `acceptance` runner stage on libcft's software backend.

    python programs/acceptance.py [--device sw|<xclbin>|cft://host:port]
                                  [--legs set,oracle,far] [--only NAME,...]
                                  [--golden named|all]
                                  [--segrun host/cft-segrun[.exe]]
                                  [--audit host/cft-audit[.exe]]
                                  [--work DIR]
    python programs/acceptance.py --write    remake programs/acceptance.json
                                             on the software backend

THE SET (ENTRIES below; programs/acceptance.json holds what each must give):
  - the six compiled references, programs/systems/compiled/: Lorenz-63 and
    Lorenz-96 under rk4 and Henon-Heiles under Stormer-Verlet, fp64 and
    fp256, each its committed .cftp and .bank;
  - the four variational references, programs/systems/compiled-tangent/;
  - the ten hard workloads that fit u50-rev7-quad, from the pack in
    programs/workloads/cft-hard-workloads/ (FPUT, phi4,
    Kuramoto-Sivashinsky, the reservoir map and Riccati, hard at fp64 and
    wide at fp256), compiled here from the pack's .cftl for u50-rev7-quad
    and held byte for byte to the committed image and bank digests.
Each entry is one run: its image and bank; its lanes, one block a tile on
the quad (256 at fp64, 64 at fp256), built by the recipes below; and four
segments of its steps. acceptance.json holds the SHA-256 of the image, the
bank and the initial state, and the expected (open) state hash at every
segment boundary, with each segment's flag word and STATUS - made by
`--write` on libcft's software backend at the card's scratch depth,
cft-segrun --scratch-depth 2048.

The lanes. The workloads': the pack's own three initial conditions, then
copies of them with (k // 3) x 2^-30 added to lane k's first value, every
value rounded once by the language - the lead's hard_card.py, exactly. The
references': each value a full significand drawn from SHAKE-256 of the
entry's name, the lane and the component, in the system's box, rounded
once - no random module, so the lanes are the same on every machine and
Python; and the last lane of tiles 1, 2 and 3 holds a lane that
overflows, one holding a signalling NaN and one holding subnormals, and,
for the variational references, the lane before each holds lane 0's state
with a special tangent (a signalling NaN; -0 and a subnormal; the largest
finite, signs alternating). The library cuts a run's lanes into a block a
tile in order (host/src/slice.h), so each special lane is on its own tile.

A device PASSES an entry when, on it:
  1. cft-segrun writes a certificate whose image and program digests,
     every boundary hash, flag word and STATUS are the committed ones,
     and whose boundary files are those states;
  2. cft-audit accepts the certificate in full: every segment re-run on
     libcft's software backend from its certified start;
  3. the golden checks accept it: the golden audit (cert.audit, which
     re-runs on seq.py) re-runs the segments the entry names, where that
     fits in the stage's time, and cft-audit handed the same choice prints
     its verdict line for line; and a spot check re-runs the last segment
     on seq.py for a few lanes - the first three, the first of each other
     tile, the special lanes - each equal to its certified end, bit for
     bit (lanes do not interact). `--golden all` has the golden audit
     re-run every segment of every entry, and cft-audit's full verdict
     must be its own line for line: about 45 minutes on the desktop,
     estimated from seq.py's measured cost a segment (not run).
A device passes the set when it passes every entry. Then the controls:
on the first entry's own certificate and states, a boundary hash, a flag
word and a parameter planted in its committed record, a bit flipped in a
boundary file - which the file check, the spot check, cft-audit and the
golden audit must each refuse - each must be caught.

THE WORKLOADS' OWN ORACLE. The pack's reference/*.json are one-step
vectors from the other model's own evaluator - a parser of the subset it
writes, rounding with integers and Fractions, importing nothing of this
repository. The compiled images of the 14 hard and wide programs, on
seq.py, and the language's interpreter, lang.run, must equal each: states,
FLAGS, and each lane's FLAGS alone, with the pack's own digests and format
layout.
  - `--legs oracle` (the `acceptance` stage, in the gate budget): the
    interpreter on all 21 programs, the seven extended ones included, and
    the ten card programs' images - the set's compilations, their REPEAT
    set to 1;
  - `--legs far` (the `acceptance-far` stage, the full census only, by
    the lead's choice): the images of the four past the card, Gray-Scott
    and Lorenz-tangent hard and wide, compiled here for sw:32768 - about
    12 minutes on the desktop, so the gate leaves them out;
  - the extended ones' images take minutes to hours each to compile and
    are left out (the pack's own runner verified them on amd-arc-box,
    2026-10-01 and 02).
Each leg's controls: a state bit and a lane's FLAGS planted in a copy of
its first program's vector, each caught.

One verdict line an entry and a program, and a total. Every check prints
`ok` or `FAIL`, and none is skipped: without cft-segrun or cft-audit the
set refuses to start, by name, since an entry neither auditor saw is not
admitted.
"""

import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

import cftc                                               # noqa: E402
from cft_golden import FORMATS, asm, cert, lang, seq      # noqa: E402
from cft_golden import softfloat as sf                    # noqa: E402
from cft_golden.lang import constants as K                # noqa: E402

SET = ROOT / "programs" / "acceptance.json"
PACK_REL = "programs/workloads/cft-hard-workloads"
PACK = ROOT / PACK_REL
EXE = ".exe" if os.name == "nt" else ""

DEPTH = 2048            # the card's scratch depth (revision 7), and --write's
TILES = 4               # u50-rev7-quad
BLOCK = {"fp64": 64, "fp256": 16}   # lanes a block: 16 beats of 32 bytes
SEGMENTS = 4
TARGET = "u50-rev7-quad"
FAR_TARGET = "sw:32768"             # the oracle's images past the card
ACCEPTED = "cft-certificate 1: ACCEPTED - every check passed"

# The references: (name, its directory, its system's box, the segments the
# golden audit re-runs in the stage). A segment's re-run on seq.py, all
# lanes, measured on the desktop (2026-10-02, the round's ledger, A1.md):
# lorenz63 10.4 s fp64 and 2.8 s fp256, lorenz96 36.7 and 9.4,
# henonheiles 2.4 and 0.7, lorenz63-tangent 22.9 and 5.7,
# lorenz96-tangent 73.5 and 19.8. The golden audit takes the last segment
# where that costs 10.4 s or less.
REFERENCES = (
    ("lorenz63-rk4-fp64", "compiled", "lorenz63-rk4", (3,)),
    ("lorenz63-rk4-fp256", "compiled", "lorenz63-rk4", (3,)),
    ("lorenz96-rk4-fp64", "compiled", "lorenz96-rk4", ()),
    ("lorenz96-rk4-fp256", "compiled", "lorenz96-rk4", (3,)),
    ("henonheiles-lf-fp64", "compiled", "henonheiles-lf", (3,)),
    ("henonheiles-lf-fp256", "compiled", "henonheiles-lf", (3,)),
    ("lorenz63-rk4-tangent-fp64", "compiled-tangent", "lorenz63-rk4", ()),
    ("lorenz63-rk4-tangent-fp256", "compiled-tangent", "lorenz63-rk4",
     (3,)),
    ("lorenz96-rk4-tangent-fp64", "compiled-tangent", "lorenz96-rk4", ()),
    ("lorenz96-rk4-tangent-fp256", "compiled-tangent", "lorenz96-rk4", ()),
)
# lang_check's boxes, written here so that the set is its own.
BOX = {"lorenz63-rk4": [(-20, 20), (-25, 25), (5, 45)],
       "lorenz96-rk4": None,                      # every component (-3, 3)
       "henonheiles-lf": [(Fraction(-2, 5), Fraction(2, 5))] * 4}
TANGENT_BOX = (-2, 2)

# The workloads that fit u50-rev7-quad, and their steps a segment, the same
# at fp64 and fp256: chosen so that each fp64 run is 2 to 4 s on the
# desktop's software backend (measured: phi4 0.099 s a step at 256 lanes,
# FPUT 0.072, the reservoir 0.50, KS 0.49, Riccati 0.51).
WORKLOADS = (("phi4", 8), ("fput", 8), ("reservoir", 2),
             ("kuramoto_sivashinsky", 2), ("riccati", 2))
# The rest of the 14 hard and wide programs, past the card: the oracle's.
FAR = ("gray_scott", "lorenz_tangent")


def entries():
    """The set, in order: each entry's parameters."""
    out = []
    for name, sub, system, golden in REFERENCES:
        out.append({"name": name,
                    "kind": "variational" if sub == "compiled-tangent"
                    else "reference",
                    "image": f"programs/systems/{sub}/{name}.cftp",
                    "bank": f"programs/systems/{sub}/{name}.bank",
                    "source": f"programs/systems/{name}.cftl",
                    "target": None, "system": system, "steps": None,
                    "segments": SEGMENTS, "golden": list(golden)})
    for family, steps in WORKLOADS:
        for tier, fmt in (("hard", "fp64"), ("wide", "fp256")):
            wid = f"{family}_{tier}_{fmt}"
            out.append({"name": wid, "kind": "workload", "image": None,
                        "bank": None,
                        "source": f"{PACK_REL}/programs/{wid}.cftl",
                        "target": TARGET, "system": None, "steps": steps,
                        "segments": SEGMENTS, "golden": []})
    return out


# ---- reporting -----------------------------------------------------------

class Tally:
    def __init__(self):
        self.ok = self.bad = 0
        self.failures = []


T = Tally()


def ok(what):
    T.ok += 1
    print(f"  ok    {what}", flush=True)


def bad(what):
    T.bad += 1
    T.failures.append(what)
    print(f"  FAIL  {what}", flush=True)


def check(cond, what, why=""):
    if cond:
        ok(what)
    else:
        bad(f"{what}" + (f": {why}" if why else ""))
    return bool(cond)


def sha(data):
    return hashlib.sha256(data).hexdigest()


# ---- lanes -----------------------------------------------------------------

def drawn(tag, nbits):
    """nbits drawn from SHAKE-256 of `tag`: the references' only source of
    variety, the same on every machine and every Python."""
    nbytes = (nbits + 7) // 8
    v = int.from_bytes(hashlib.shake_256(tag.encode("ascii"))
                       .digest(nbytes), "big")
    return v >> (8 * nbytes - nbits)


def full_value(fmt, tag, lo, hi):
    """A value in [lo, hi] at twice the format's precision, rounded once to
    nearest: a full significand, so that no product is exact by accident
    (lang_check.full_value's, drawn from SHAKE-256)."""
    num = drawn(tag, 2 * fmt.prec)
    v = Fraction(lo) + (Fraction(hi) - Fraction(lo)) * \
        Fraction(num, 1 << (2 * fmt.prec))
    return K.round_once(fmt, sf.RND_RNE, v)[0] if v else 0


def primal_specials(fmt, n, base, tag):
    """lang_check's three special lanes: one that overflows, one holding a
    signalling NaN, one holding subnormals."""
    huge = sf.round_pack(fmt, 0, 1, fmt.emax // 2 + 10)[0]
    over = list(base)
    over[0] = huge
    if n > 1:
        over[1] = huge
    snan = list(base)
    snan[0] = sf.snan_bits(fmt, 1)
    sub = [sf.min_subnormal_bits(fmt)] + \
        [1 + drawn(f"{tag} subnormal {j}", fmt.man_w + 64)
         % ((1 << fmt.man_w) - 1) for j in range(1, n)]
    return [over, snan, sub]


def tangent_specials(fmt, n, nvec, base):
    """tangent_check's three special tangents: a signalling NaN; -0 and a
    subnormal; the largest finite, its sign alternating."""
    top = ((fmt.exp_mask - 1) << fmt.man_w) | fmt.man_mask
    snan = [list(t) for t in base]
    snan[0][0] = sf.snan_bits(fmt, 1)
    small = [list(t) for t in base]
    small[0][0] = fmt.sign_mask
    if n > 1:
        small[0][1] = sf.min_subnormal_bits(fmt)
    huge = [[top | (fmt.sign_mask if i % 2 else 0) for i in range(n)]
            for _ in range(nvec)]
    return [snan, small, huge]


def reference_lanes(entry, g):
    """-> (the lane-major block, the special lanes): one block a tile."""
    fmt, n, nvec = g.fmt, g.n_state, len(g.tangent)
    blk = BLOCK[fmt.name]
    count = TILES * blk
    box = BOX[entry["system"]]
    name = entry["name"]

    def comp(j):
        return box[j] if box else (-3, 3)
    states = [[full_value(fmt, f"{name} lane {k} state {j}", *comp(j))
               for j in range(n)] for k in range(count)]
    tans = [[[full_value(fmt, f"{name} lane {k} tangent {t} {j}",
                         *TANGENT_BOX) for j in range(n)]
             for t in range(nvec)] for k in range(count)]
    special = []
    for i, lane in enumerate(primal_specials(fmt, n, states[0], name)):
        k = (i + 2) * blk - 1               # the last lane of tiles 1-3
        states[k] = lane
        special.append(k)
    if nvec:
        for i, tv in enumerate(tangent_specials(fmt, n, nvec, tans[0])):
            k = (i + 2) * blk - 2           # the lane before it
            states[k] = list(states[0])
            tans[k] = tv
            special.append(k)
    block = []
    for k in range(count):
        block += states[k]
        for t in range(nvec):
            block += tans[k][t]
    return block, sorted(special)


def workload_lanes(case, c):
    """-> (the lane-major block, lanes 0-2's states and lane params): the
    lead's hard_card.py - the pack's three lanes exactly, then exact
    perturbed copies, every value rounded once by the language."""
    g = c.ir
    rows = json.loads((PACK / case["inputs"]).read_bytes())["rows"]
    count = TILES * BLOCK[g.fmt_name]
    states, params = [], []
    for k in range(count):
        row = rows[k % 3]
        vals = [Fraction(v) for v in row["state"]]
        if k >= 3:
            vals[0] += Fraction(k // 3, 1 << 30)
        states.append([K.round_once(g.fmt, g.rnd, v)[0] for v in vals])
        params.append([K.round_once(g.fmt, g.rnd, Fraction(v))[0]
                       for v in row["lane_params"]])
    return c.scratch_block(states, params), (states[:3], params[:3])


# ---- the pack ----------------------------------------------------------------

_CATALOG = {}


def catalog():
    if not _CATALOG:
        doc = json.loads((PACK / "catalog.json").read_bytes())
        _CATALOG.update((c["id"], c) for c in doc["cases"])
    return _CATALOG


def vector(case):
    return json.loads((PACK / case["reference"]).read_bytes())


def hexes(rows):
    return [[int(v, 16) for v in row] for row in rows]


# One compilation a program and target in a process: the set's, which the
# oracle reuses with its REPEAT patched to 1.
_COMPILED = {}


def compiled(wid, steps, target):
    """-> (the compilation, seconds compiling here: 0 if reused)."""
    c = _COMPILED.get((wid, target))
    if c is not None and (steps is None or c.steps == steps):
        return c, 0.0
    case = catalog()[wid]
    t0 = time.perf_counter()
    c = cftc.compile_file(PACK / case["file"], steps or 1, target, stem=wid,
                          source=f"{PACK_REL}/{case['file']}")
    _COMPILED[(wid, target)] = c
    return c, time.perf_counter() - t0


def image_at(image, steps):
    """The image with its segment's REPEAT - its first - counting `steps`,
    every other word the same (programs/check.py's _patch_trip;
    lang_check.image_at). A call loop's REPEATs (parcel C4) are inside the
    step and keep their counts: patching them too ran a looped image wrong
    on 41 of 52 lanes (verifier-VC4, 2026-10-02)."""
    img = asm.Image.from_bytes(image)
    words = list(img.insns)
    for k, w in enumerate(words):
        dd = asm.decode(w)
        if dd["ctrl"] and dd["op"] == asm.REPEAT:
            words[k] = asm.repeat(steps)
            break
    return asm.Image(img.fmt, words, img.consts, img.max_deposits, img.flags,
                     scratch_depth=img.scratch_depth,
                     scratch_io=img.scratch_io).to_bytes()


def repeat_count(image):
    """The steps a segment: the count of the image's segment REPEAT, its
    first - a call loop's REPEATs (parcel C4) are inside the step."""
    for w in asm.Image.from_bytes(image).insns:
        dd = asm.decode(w)
        if dd["ctrl"] and dd["op"] == asm.REPEAT:
            return dd["imm"]
    raise ValueError("the image has no REPEAT, so it is not a segment")


# ---- the comparisons, each a list of problems by name ----------------------

PARAMS = ("name", "kind", "image", "bank", "source", "target", "format",
          "lanes", "slots", "steps", "segments", "golden", "special", "spot")


def committed_problems(rec, want):
    """What ran against the set's record, before the device: the
    parameters, then the image, the bank and the initial state."""
    diff = sorted(k for k in PARAMS if want.get(k) != rec.get(k))
    if diff:
        return [f"acceptance.json was made for other parameters "
                f"({', '.join(diff)}): run `programs/acceptance.py --write` "
                f"if the change is meant"]
    out = []
    for what, key in (("the image", "image_sha256"),
                      ("the bank", "bank_sha256"),
                      ("the initial state", "init_sha256")):
        if rec[key] != want[key]:
            out.append(f"{what} is {rec[key][:16]} where the set has "
                       f"{want[key][:16]}")
    return out


def outcome_problems(rec, want):
    """The device's boundary hashes, flag words and STATUS against the
    set's."""
    out = []
    for b, (h, w) in enumerate(zip(rec["boundaries"], want["boundaries"])):
        if h != w:
            out.append(f"boundary {b}'s hash is {h[:16]} where the set has "
                       f"{w[:16]}")
    for k in range(len(want["flags"])):
        if (rec["flags"][k], rec["status"][k]) != \
                (want["flags"][k], want["status"][k]):
            out.append(f"segment {k}'s flags {rec['flags'][k]} and STATUS "
                       f"{rec['status'][k]} where the set has "
                       f"{want['flags'][k]} and {want['status'][k]}")
    if len(rec["boundaries"]) != len(want["boundaries"]):
        out.append(f"{len(rec['boundaries'])} boundaries where the set has "
                   f"{len(want['boundaries'])}")
    return out


def certificate_problems(run0, files, rec, image, bank, init):
    """The certificate's own lines against what was handed to the device,
    and its boundary files against its hashes."""
    bounds = [run0.chain[0].start] + [s.end for s in run0.chain]
    out = []
    wrong = [b for b in sorted(files)
             if cert.state_hash(None, files[b]) != bounds[b]]
    if wrong:
        out.append(f"boundary files {wrong} are not the states the "
                   f"certificate hashes")
    if bounds[0] != cert.state_hash(None, init):
        out.append("its first boundary is not the initial state handed")
    if run0.output != bounds[-1]:
        out.append("its output is not its last boundary")
    if (run0.lanes, run0.steps, len(run0.chain)) != \
            (rec["lanes"], rec["steps"], rec["segments"]):
        out.append(f"it ran {run0.lanes} lanes, {len(run0.chain)} segments "
                   f"of {run0.steps} steps")
    if run0.image != sha(image) or run0.digest != sha(image + bank):
        out.append("its program-image or program-digest is not the image and "
                   "bank handed")
    return out


def bank_values(prog, bank):
    return cert.state_values(prog.fmt, bank) if prog.bank_ext else None


def spot_check(image, bank, fmt, slots, start, end, lanes, depth):
    """The segment from `start` re-run on seq.py for `lanes` alone: each
    lane's end equal to its certified end? -> (lanes that differ, STATUS)."""
    prog = seq.Program.from_bytes(image, scratch_depth=depth)
    a = cert.state_values(fmt, start)
    b = cert.state_values(fmt, end)
    sin = []
    for k in lanes:
        sin += a[k * slots:(k + 1) * slots]
    z = [0] * len(lanes)
    r = seq.run(prog, z, z, z, bank=bank_values(prog, bank), scratch_in=sin,
                scratch_depth=depth)
    wrong = [k for i, k in enumerate(lanes)
             if r.scratch_out[i * slots:(i + 1) * slots]
             != b[k * slots:(k + 1) * slots]]
    return wrong, r.status


def oracle_problems(states, flags, each, v):
    """A backend's one step against the pack's vector."""
    out = []
    want = hexes(v["expected"]["states"])
    for k, (got, w) in enumerate(zip(states, want)):
        if got != w:
            i = next(i for i, (x, y) in enumerate(zip(got, w)) if x != y)
            out.append(f"lane {k}'s component {i} is {got[i]:#x} where the "
                       f"vector has {w[i]:#x}")
    if len(states) != len(want):
        out.append(f"{len(states)} lanes where the vector has {len(want)}")
    if flags != v["expected"]["flags"]:
        out.append(f"FLAGS {flags:#x} where the vector has "
                   f"{v['expected']['flags']:#x}")
    if each != v["expected_lane_flags"]:
        out.append(f"each lane's FLAGS {each} where the vector has "
                   f"{v['expected_lane_flags']}")
    return out


# ---- the device ------------------------------------------------------------------

def segrun(tool, device, d, segments, steps):
    out, states = d / "c.cert", d / "states"
    # version 1: cft-segrun writes version 2 by default since version 2's
    # C half, and this leg holds version 1's certificate and its audit
    args = [tool, "--format-version", "1", "--out", out, "--states", states,
            "--open"]
    if device == "sw":
        args += ["--device", "sw", "--scratch-depth", DEPTH]
    else:
        args += ["--device", device]
    args += ["--run", "main", "--image", d / "image.cftp", "--bank",
             d / "image.bank", "--init", d / "init.bin", "--segments",
             segments, "--steps", steps]
    t0 = time.perf_counter()
    r = subprocess.run([str(a) for a in args], capture_output=True,
                       text=True, timeout=4 * 3600)
    return r, time.perf_counter() - t0


def audit_tool(tool, d, choose, states="states"):
    args = [tool, "--cert", d / "c.cert", "--states", d / states,
            "--run", "0", "--image", d / "image.cftp", "--bank",
            d / "image.bank", "--choose", choose]
    t0 = time.perf_counter()
    r = subprocess.run([str(a) for a in args], capture_output=True,
                       text=True, timeout=4 * 3600)
    lines = r.stdout.split("\n")
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return r.returncode, lines, r.stderr.strip(), time.perf_counter() - t0


# ---- one entry ----------------------------------------------------------------

def prepare(entry):
    """-> (image, bank, initial state bytes, the record's parameters, the
    lanes 0-2 of a workload or None, seconds compiling)."""
    rec = {k: entry[k] for k in ("name", "kind", "image", "bank", "source",
                                 "target", "segments", "golden")}
    secs = 0.0
    special = []
    first3 = None
    if entry["kind"] == "workload":
        case = catalog()[entry["name"]]
        c, secs = compiled(entry["name"], entry["steps"], entry["target"])
        image, bank = c.image, c.bank
        block, first3 = workload_lanes(case, c)
        fmt = c.ir.fmt
    else:
        image = (ROOT / entry["image"]).read_bytes()
        bank = (ROOT / entry["bank"]).read_bytes()
        g = lang.load(ROOT / entry["source"]).graph
        block, special = reference_lanes(entry, g)
        fmt = g.fmt
    slots = seq.Program.from_bytes(image, scratch_depth=DEPTH).n_scratch_in
    blk = BLOCK[fmt.name]
    rec.update(format=fmt.name, lanes=len(block) // slots, slots=slots,
               steps=repeat_count(image), special=special,
               spot=sorted({0, 1, 2} | {t * blk for t in range(1, TILES)}
                           | set(special)))
    init = cert.state_bytes(fmt, block)
    rec.update(image_sha256=sha(image), bank_sha256=sha(bank),
               init_sha256=sha(init))
    return image, bank, init, rec, first3, secs


def run_entry(entry, want, args, work):
    """Run one entry on the device and hold it to `want`, its committed
    record (None when --write is making it). -> (verdict line, record, the
    artifacts the controls use or None)."""
    name = entry["name"]
    d = work / name
    d.mkdir(parents=True)
    t_entry = time.perf_counter()
    try:
        image, bank, init, rec, first3, csecs = prepare(entry)
    except (lang.Refusal, cftc.InternalError, OSError, ValueError) as e:
        bad(f"{name}: its image or lanes could not be made: "
            f"{type(e).__name__}: {e}")
        return f"FAIL  {name}: its image or lanes could not be made", \
            None, None
    print(f"-- {name} ({rec['kind']}, {rec['format']}): {rec['lanes']} "
          f"lanes, {rec['segments']} segments of {rec['steps']} steps",
          flush=True)
    failed = []
    if entry["kind"] == "workload":
        v = vector(catalog()[name])
        if not check(first3 == (hexes(v["request"]["states"]),
                                hexes(v["request"]["lane_params"])),
                     f"{name}: lanes 0-2 are the pack's three initial "
                     f"conditions, its one-step vector's request",
                     "they differ"):
            failed.append("lanes 0-2")
        ok(f"{name}: compiled for {rec['target']} at {rec['steps']} steps a "
           f"segment ({csecs:.1f} s)")
    if want is not None:
        probs = committed_problems(rec, want)
        if not check(not probs, f"{name}: its parameters, image, bank and "
                     f"initial state are the set's, byte for byte",
                     "; ".join(probs)):
            return (f"FAIL  {name}: not the set's entry - "
                    f"{'; '.join(probs)}"), None, None
    (d / "image.cftp").write_bytes(image)
    (d / "image.bank").write_bytes(bank)
    (d / "init.bin").write_bytes(init)
    # 1. the device
    r, secs = segrun(args.segrun, args.device, d, rec["segments"],
                     rec["steps"])
    if not check(r.returncode == 0, f"{name}: cft-segrun ran it on "
                 f"{args.device} ({secs:.1f} s)",
                 f"rc {r.returncode}: {r.stderr.strip()[-400:]}"):
        return f"FAIL  {name}: cft-segrun did not run it", None, None
    data = (d / "c.cert").read_bytes()
    try:
        c = cert.parse(data)
    except cert.Refusal as e:
        bad(f"{name}: the golden reader refuses its certificate: {e.name}: "
            f"{e.message}")
        return f"FAIL  {name}: its certificate does not read", None, None
    run0, ident = c.runs[0], c.identity
    depth = cert.scratch_depth_of(ident, run0)
    ok(f"{name}: the certificate reads; backend {ident.backend}, "
       f"device-xclbin {str(ident.device_xclbin)[:16]}, device-tiles "
       f"{ident.device_tiles}, scratch depth {depth}")
    rec.update(boundaries=[run0.chain[0].start] +
               [s.end for s in run0.chain],
               flags=[s.flags for s in run0.chain],
               status=[s.status for s in run0.chain])
    files = {b: (d / "states" / f"run-0-boundary-{b}.bin").read_bytes()
             for b in range(rec["segments"] + 1)}
    probs = certificate_problems(run0, files, rec, image, bank, init)
    if not check(not probs, f"{name}: its boundary files are its hashes, and "
                 f"its lines are the run handed it", "; ".join(probs)):
        failed.append("the certificate's own lines")
    if want is not None:
        probs = outcome_problems(rec, want)
        if not check(not probs, f"{name}: every boundary hash, flag word and "
                     f"STATUS is the set's ({rec['segments'] + 1} "
                     f"boundaries, flags {rec['flags']})", "; ".join(probs)):
            failed.append("the committed digests")
    # 2. cft-audit, in full
    rc, lines, err, asecs = audit_tool(args.audit, d, "all")
    if not check(rc == 0 and lines[:1] == [ACCEPTED],
                 f"{name}: cft-audit accepts it in full ({asecs:.1f} s)",
                 f"rc {rc}: {err[-400:]}"):
        failed.append("cft-audit")
    # 3. the golden audit, where it fits, and the spot check
    segs = list(range(rec["segments"])) if args.golden == "all" \
        else list(rec["golden"])
    if segs:
        t0 = time.perf_counter()
        try:
            verdict = cert.audit(data, None, {0: (image, bank)},
                                 states={0: dict(files)},
                                 choose={0: "all" if args.golden == "all"
                                         else segs})
            gsecs = time.perf_counter() - t0
            if args.golden == "all":
                same, how = lines == verdict.lines(), "every segment"
            else:
                rc2, lines2, _e, _s = audit_tool(
                    args.audit, d, ",".join(str(s) for s in segs))
                same = rc2 == 0 and lines2 == verdict.lines()
                how = "segment " + ", ".join(str(s) for s in segs)
            if not check(same, f"{name}: the golden audit accepts it, {how} "
                         f"re-run on seq.py ({gsecs:.1f} s), and cft-audit's "
                         f"verdict is its own line for line",
                         "the two auditors' verdicts differ"):
                failed.append("the two auditors' verdicts")
        except cert.Refusal as e:
            bad(f"{name}: the golden audit refuses it: {e.name}: {e.message}"
                f" (run {e.run}, segment {e.segment})")
            failed.append("the golden audit")
    last = rec["segments"] - 1
    t0 = time.perf_counter()
    wrong, st = spot_check(image, bank, FORMATS[rec["format"]], rec["slots"],
                           files[last], files[last + 1], rec["spot"], depth)
    if not check(not wrong and st == 0,
                 f"{name}: the golden spot check - segment {last} re-run on "
                 f"seq.py for lanes {rec['spot']}, each equal to its "
                 f"certified end ({time.perf_counter() - t0:.1f} s)",
                 f"lanes {wrong} differ, STATUS {st:#x}"):
        failed.append("the golden spot check")
    secs = time.perf_counter() - t_entry
    if not segs:
        golden = "no golden audit here (seq.py's cost)"
    elif args.golden == "all":
        golden = "the golden audit re-ran every segment"
    else:
        golden = "the golden audit re-ran segment " + \
            ", ".join(str(s) for s in segs)
    line = (f"{name}: {rec['lanes']} lanes, {rec['segments']} x "
            f"{rec['steps']} steps on {ident.backend}, flags {rec['flags']}; ")
    kept = (name, rec, want, image, bank, init, files, data, d, run0, depth)
    if failed:
        return f"FAIL  {line}{'; '.join(failed)} ({secs:.1f} s)", rec, kept
    if want is None:
        return (f"MADE  {line}cft-audit accepts in full, {golden}, the spot "
                f"check holds ({secs:.1f} s)"), rec, kept
    return (f"PASS  {line}every digest the set's, cft-audit accepts in full, "
            f"{golden}, the spot check holds ({secs:.1f} s)"), rec, kept


def flip(data, fmt, slots, lane):
    """The state with the lowest bit of `lane`'s first element flipped."""
    vals = cert.state_values(fmt, data)
    vals[lane * slots] ^= 1
    return cert.state_bytes(fmt, vals)


def set_controls(args, kept):
    """Each check above watched failing on one entry's own artifacts."""
    name, rec, want, image, bank, init, files, data, d, run0, depth = kept
    print(f"-- the controls, on {name}'s own certificate and states",
          flush=True)
    base = want if want is not None else rec
    fmt = FORMATS[rec["format"]]
    w = copy.deepcopy(base)
    w["boundaries"][2] = ("0" if w["boundaries"][2][0] != "0" else "1") + \
        w["boundaries"][2][1:]
    check(any("boundary 2's hash" in p for p in outcome_problems(rec, w)),
          "control: a boundary hash planted in the record is caught")
    w = copy.deepcopy(base)
    w["flags"][1] ^= sf.FLAG_UNDERFLOW
    check(any("segment 1's flags" in p for p in outcome_problems(rec, w)),
          "control: a flag word planted in the record is caught")
    w = copy.deepcopy(base)
    w["steps"] += 1
    check(any("other parameters (steps)" in p
              for p in committed_problems(rec, w)),
          "control: a parameter planted in the record is caught")
    w = copy.deepcopy(base)
    w["init_sha256"] = sha(b"")
    check(any("the initial state" in p for p in committed_problems(rec, w)),
          "control: an initial state planted in the record is caught")
    planted = dict(files)
    planted[2] = flip(files[2], fmt, rec["slots"], 0)
    check(any("boundary files [2]" in p for p in
              certificate_problems(run0, planted, rec, image, bank, init)),
          "control: a bit flipped in boundary 2's file is caught by the "
          "file check")
    last = rec["segments"] - 1
    wrong, _st = spot_check(image, bank, fmt, rec["slots"], files[last],
                            flip(files[last + 1], fmt, rec["slots"], 0),
                            rec["spot"], depth)
    check(wrong == [0], "control: a bit flipped in lane 0's certified end is "
          "caught by the spot check", f"it named lanes {wrong}")
    pdir = d / "states-planted"
    shutil.copytree(d / "states", pdir)
    (pdir / "run-0-boundary-2.bin").write_bytes(planted[2])
    rc, _lines, err, _s = audit_tool(args.audit, d, "all", "states-planted")
    check(rc == 4 and "refused state-hash" in err,
          "control: cft-audit refuses that state, state-hash (exit 4)",
          f"rc {rc}: {err[-200:]}")
    try:
        cert.audit(data, None, {0: (image, bank)}, states={0: planted},
                   choose={0: [0]})
        bad("control: the golden audit accepted the flipped state")
    except cert.Refusal as e:
        check(e.name == "state-hash", "control: the golden audit refuses "
              "that state, state-hash", f"it refused {e.name}")


# ---- the set -------------------------------------------------------------------

def leg_set(args, work, selected):
    print(f"\n== the acceptance set on {args.device}", flush=True)
    want = {}
    if not args.write:
        if not SET.is_file():
            bad("programs/acceptance.json is missing: run --write on the "
                "software backend")
            return ["FAIL  the set: programs/acceptance.json is missing"]
        doc = json.loads(SET.read_bytes())
        want = {e["name"]: e for e in doc["entries"]}
        have = [e["name"] for e in entries()]
        if sorted(want) != sorted(have) or len(doc["entries"]) != len(have):
            bad(f"acceptance.json's entries are not the driver's: "
                f"{sorted(set(want) ^ set(have))}")
            return ["FAIL  the set: acceptance.json's entries differ"]
    verdicts, records, kept = [], [], None
    for e in entries():
        if selected and e["name"] not in selected:
            continue
        line, rec, art = run_entry(e, None if args.write else want[e["name"]],
                                   args, work)
        print(line, flush=True)
        verdicts.append(line)
        records.append(rec)
        kept = kept or art
    if kept:
        set_controls(args, kept)
    if args.write:
        if selected:
            print("  note  acceptance.json is not written: --only made part "
                  "of the set, as a trial", flush=True)
        elif all(v.startswith("MADE") for v in verdicts) and not T.bad:
            doc = {"acceptance": 1,
                   "made": "programs/acceptance.py --write: libcft's "
                           "software backend, cft-segrun --scratch-depth "
                           "2048, open certificates, each accepted by "
                           "cft-audit in full and by the golden checks",
                   "entries": records}
            SET.write_bytes((json.dumps(doc, indent=1, sort_keys=True)
                             + "\n").encode("ascii"))
            ok(f"wrote programs/acceptance.json: {len(records)} entries")
        else:
            bad("acceptance.json is not written: every entry must be made, "
                "and every check pass, in one run of the whole set")
    return verdicts


# ---- the workloads' own oracle -------------------------------------------------

def oracle_programs():
    """The 14 hard and wide programs, then the seven extended ones."""
    fams = [f for f, _s in WORKLOADS] + list(FAR)
    ids = []
    for tier, fmt in (("hard", "fp64"), ("wide", "fp256")):
        ids += [f"{f}_{tier}_{fmt}" for f in fams]
    ids += [f"{f}_extended_fp64" for f in fams]
    return ids


def card_programs():
    return {f"{f}_{t}" for f, _s in WORKLOADS
            for t in ("hard_fp64", "wide_fp256")}


def far_programs():
    """The four hard and wide programs past the card: the `far` leg's."""
    return [f"{f}_{t}" for t in ("hard_fp64", "wide_fp256") for f in FAR]


def oracle_consistency(wid, case, v, g):
    """The pack's own digests, and the vector's format layout and step
    count. -> [what failed]."""
    failed = []
    src = (PACK / case["file"]).read_bytes()
    inp = (PACK / case["inputs"]).read_bytes()
    if not check(sha(src) == case["source_sha256"] == v["source_sha256"]
                 and sha(inp) == case["input_sha256"] == v["input_sha256"],
                 f"{wid}: the source and the inputs are the ones the catalog "
                 f"and the vector were made from"):
        failed.append("the pack's digests")
    lay = v["format_layout"]
    if not check((g.fmt.width, g.fmt.exp_w, g.fmt.man_w) ==
                 (lay["width"], lay["exponent_bits"], lay["fraction_bits"])
                 and v["request"]["steps"] == 1,
                 f"{wid}: its format's layout is the vector's "
                 f"({lay['width']} bits: {lay['exponent_bits']} of exponent, "
                 f"{lay['fraction_bits']} of fraction), and the vector is one "
                 f"step"):
        failed.append("the layout")
    return failed


def oracle_controls(wid, states, flags, each, v):
    """Two plants in a copy of the vector, each caught by oracle_problems."""
    w = copy.deepcopy(v)
    st = w["expected"]["states"][1]
    st[0] = f"0x{int(st[0], 16) ^ 1:0{len(st[0]) - 2}x}"
    check(any("lane 1's component 0" in p
              for p in oracle_problems(states, flags, each, w)),
          f"control: a bit flipped in a copy of {wid}'s vector is caught")
    w = copy.deepcopy(v)
    w["expected_lane_flags"][0] ^= sf.FLAG_INEXACT
    check(any("each lane's FLAGS" in p
              for p in oracle_problems(states, flags, each, w)),
          f"control: a lane's FLAGS changed in a copy of {wid}'s vector is "
          f"caught")


def oracle_image(wid, c, req, lp):
    """The compiled image, its REPEAT 1, on seq.py: one step on the
    vector's lanes, and on each lane alone for its FLAGS. -> (states,
    FLAGS, each lane's FLAGS, STATUS)."""
    image = c.image if c.steps == 1 else image_at(c.image, 1)
    prog = seq.Program.from_bytes(image, scratch_depth=c.depth)
    bank = c.lowered.bank_values()
    m, n = c.ir.m, c.ir.n_state

    def one_step(lanes):
        z = [0] * len(lanes)
        block = c.scratch_block([req[k] for k in lanes],
                                [lp[k] for k in lanes])
        return seq.run(prog, z, z, z, bank=bank, scratch_in=block,
                       scratch_depth=c.depth)
    res = one_step(range(len(req)))
    got = [res.scratch_out[k * m:k * m + n] for k in range(len(req))]
    each = [one_step([k]).flags for k in range(len(req))]
    return got, res.flags, each, res.status


def leg_oracle(selected, far):
    """far False (the gate's): every program's interpreter, the ten card
    programs' images. far True (the full census's): the four images past
    the card, compiled here for sw:32768."""
    print("\n== the workloads' own oracle: the pack's one-step vectors"
          + (", the four images past the card" if far else ""), flush=True)
    verdicts = []
    card = card_programs()
    controlled = False
    for wid in (far_programs() if far else oracle_programs()):
        if selected and wid not in selected:
            continue
        case = catalog()[wid]
        v = vector(case)
        print(f"-- {wid} ({case['tier']}, {case['format']})", flush=True)
        req = hexes(v["request"]["states"])
        lp = hexes(v["request"]["lane_params"])
        t0 = time.perf_counter()
        g = lang.load(PACK / case["file"]).graph
        failed = oracle_consistency(wid, case, v, g)
        if not far:
            r = lang.run(g, req, 1, lane_params=lp)
            each = [lang.run(g, [req[k]], 1, lane_params=[lp[k]]).flags
                    for k in range(len(req))]
            probs = oracle_problems(r.states, r.flags, each, v)
            if not check(not probs, f"{wid}: lang.run, one step on the "
                         f"vector's {len(req)} lanes: its states, FLAGS "
                         f"{v['expected']['flags']:#x} and each lane's FLAGS "
                         f"alone {v['expected_lane_flags']} "
                         f"({time.perf_counter() - t0:.1f} s)",
                         "; ".join(probs)):
                failed.append("the interpreter")
            if not controlled:
                controlled = True
                oracle_controls(wid, r.states, r.flags, each, v)
            if wid not in card:
                where = ("the full census's (the acceptance-far stage, "
                         "--legs far)" if case["tier"] != "extended" else
                         "not compiled here (minutes to hours)")
                verdicts.append(f"FAIL  {wid}: {', '.join(failed)}" if failed
                                else f"PASS  {wid}: the interpreter equals "
                                     f"the vector; its image is {where}")
                print(verdicts[-1], flush=True)
                continue
        target = TARGET if wid in card else FAR_TARGET
        try:
            c, csecs = compiled(wid, None, target)
        except (lang.Refusal, cftc.InternalError) as e:
            bad(f"{wid}: the compiler refuses it for {target}: {e}")
            verdicts.append(f"FAIL  {wid}: not compiled for {target}")
            print(verdicts[-1], flush=True)
            continue
        t0 = time.perf_counter()
        got, flags, each, status = oracle_image(wid, c, req, lp)
        probs = oracle_problems(got, flags, each, v)
        if status:
            probs.append(f"STATUS {status:#x}")
        how = ("the set's compilation, its REPEAT 1" if not csecs else
               f"compiled for {target} here, {csecs:.1f} s")
        if not check(not probs, f"{wid}: the compiled image on seq.py ({how})"
                     f": its states, FLAGS and each lane's FLAGS "
                     f"({time.perf_counter() - t0:.1f} s)", "; ".join(probs)):
            failed.append("the compiled image")
        if far and not controlled:
            controlled = True
            oracle_controls(wid, got, flags, each, v)
        what = ("the compiled image on seq.py equals the vector" if far else
                "the interpreter and the compiled image on seq.py equal the "
                "vector")
        verdicts.append(f"FAIL  {wid}: {', '.join(failed)}" if failed
                        else f"PASS  {wid}: {what}")
        print(verdicts[-1], flush=True)
    return verdicts


# ---- main ------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="The acceptance set: the admission test for a device "
                    "(see the docstring).")
    ap.add_argument("--device", default="sw",
                    help="sw (libcft's software backend at --scratch-depth "
                         "2048), an xclbin, or cft://host:port")
    ap.add_argument("--legs", default="set",
                    help="set, oracle and far, comma-separated: set,oracle "
                         "is the `acceptance` stage, far the "
                         "`acceptance-far` stage")
    ap.add_argument("--only", default="",
                    help="entries or oracle programs, comma-separated")
    ap.add_argument("--golden", choices=("named", "all"), default="named",
                    help="named: the golden audit re-runs the segments each "
                         "entry names; all: every segment of every entry")
    ap.add_argument("--segrun", default=str(ROOT / "host" /
                                            f"cft-segrun{EXE}"))
    ap.add_argument("--audit", default=str(ROOT / "host" /
                                           f"cft-audit{EXE}"))
    ap.add_argument("--work", help="keep the certificates and states here "
                                   "(a new directory); otherwise a temporary "
                                   "one, removed")
    ap.add_argument("--write", action="store_true",
                    help="remake programs/acceptance.json from the software "
                         "backend (with --only, a trial that writes nothing)")
    args = ap.parse_args(argv)
    legs = {x.strip() for x in args.legs.split(",") if x.strip()}
    if not legs or legs - {"set", "oracle", "far"}:
        ap.error(f"--legs takes set, oracle and far, not {args.legs!r}")
    selected = {x.strip() for x in args.only.split(",") if x.strip()}
    known = {e["name"] for e in entries()} | set(oracle_programs())
    if selected - known:
        ap.error(f"--only names no entry or program: "
                 f"{sorted(selected - known)}")
    if args.write and (args.device != "sw" or legs != {"set"}
                       or args.golden != "named"):
        ap.error("--write makes the set on the software backend alone: "
                 "--device sw, --legs set, --golden named")
    if "set" in legs:
        for tool in (args.segrun, args.audit):
            if not Path(tool).is_file():
                ap.error(f"{tool} is not there: build it (make -C host "
                         f"cft-segrun{EXE} cft-audit{EXE})")
        args.segrun = str(Path(args.segrun).resolve())
        args.audit = str(Path(args.audit).resolve())
    if args.work:
        work = Path(args.work)
        if work.exists():
            ap.error(f"--work {work} exists; give a new directory")
        work.mkdir(parents=True)
    else:
        work = Path(tempfile.mkdtemp(prefix="acceptance-"))
    t0 = time.perf_counter()
    verdicts = []
    try:
        if "set" in legs:
            verdicts += leg_set(args, work, selected)
        if "oracle" in legs:
            verdicts += leg_oracle(selected, far=False)
        if "far" in legs:
            verdicts += leg_oracle(selected, far=True)
    finally:
        if not args.work:
            shutil.rmtree(work, ignore_errors=True)
    print("\n== verdicts", flush=True)
    for v in verdicts:
        print(v)
    npass = sum(v.startswith(("PASS", "MADE")) for v in verdicts)
    print(f"acceptance: {npass} of {len(verdicts)} "
          f"{'made' if args.write else 'PASS'} on {args.device} "
          f"({', '.join(sorted(legs))}); {T.ok} checks ok, {T.bad} failed, "
          f"{time.perf_counter() - t0:.0f} s", flush=True)
    if T.failures:
        print("failed:")
        for f in T.failures:
            print(f"  {f}")
    return 0 if verdicts and npass == len(verdicts) and not T.bad else 1


if __name__ == "__main__":
    sys.exit(main())
