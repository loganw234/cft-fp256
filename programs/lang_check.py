#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The `lang` runner stage: the compiler (python/cftc) held to the language.

    python programs/lang_check.py [--segrun host/cft-segrun[.exe]]
                                  [--audit host/cft-audit[.exe]]
                                  [--corpus N] [--only A,B,...]
    python programs/lang_check.py --write     regenerate the committed
                                              compiled references

The language's reference interpreter, lang.run, is the definition of
correct (docs/LANGUAGE.md); every image the compiler writes must equal it
on seq.py, bit for bit, FLAGS included. A wrong semantics can hide on one
lane at the final step - the step map is many-to-one at the ulp scale
(L1's finding 1; the 2026-09-25 census) - so every comparison here is on
many lanes and at several step counts: the image's REPEAT patched to 1,
2 and 5 as well as its own count, against the interpreter's checkpoints.

  A  the corpus: the three references at fp32, fp64, fp128 and fp256 and
     Lorenz-63 and Henon-Heiles under every attribute, then systems a
     seeded generator writes as .cftl text - every built-in, arrays
     cyclic and not, lets, params, lane params, every integrator, maps
     with and without h, and the shapes the lowering must get right
     (sharing, the fold, spills, swaps and rotations, leaf outputs, an
     empty step) - at every format L1 takes them; each with lanes that
     overflow, hold a signalling NaN and hold subnormals
  B  the references against gen_odes.py's images: the compiled banks the
     classic banks byte for byte at fp64 and fp256, the hand-written
     image on its classic bank equal to the compiled one on its own and
     to the interpreter, and the costs side by side, pinned
  C  the halved bank against lang.run at h/2; every param's slot at a
     random value against lang.run on those encodings
  D  resume: one segment of 2S equals two of S
  E  libcft's software backend: cft-segrun certifies each compiled
     reference (a main run, a half-step run on the halved bank, a
     step-halving estimate); the golden reader, the golden audit and
     cft-audit accept each, in full and sampled
  F  determinism: two processes under two PYTHONHASHSEEDs write the same
     bytes, and the committed compiled references are those bytes
  G  every refusal of the compiler's, by name
  H  plants in a copy of the package: each stopped by the internal check,
     and with the check off each red on seq.py, its failing lanes counted
  I  the corpus's coverage, every tally nonzero

A check skipped prints a line that starts with SKIP, which the runner
counts and names on its VERDICT line.
"""

import argparse
import hashlib
import importlib
import json
import os
import random
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
from cftc import targets as TG                            # noqa: E402
from cftc.schedule import cycles                          # noqa: E402
from cftc.regalloc import Ins                             # noqa: E402
from cft_golden import FORMATS, asm, cert, lang, seq      # noqa: E402
from cft_golden import softfloat as sf                    # noqa: E402
from cft_golden.lang import constants as K                # noqa: E402

SYSTEMS = ROOT / "programs" / "systems"
COMPILED = SYSTEMS / "compiled"
PROGRAMS = ROOT / "programs"
REFS = {"lorenz63-rk4": 100, "lorenz96-rk4": 20, "henonheiles-lf": 100}
REF_LANES = {"lorenz63-rk4": 32, "lorenz96-rk4": 6, "henonheiles-lf": 32}
BOX = {"lorenz63-rk4": [(-20, 20), (-25, 25), (5, 45)],
       "henonheiles-lf": [(-0.4, 0.4)] * 4,
       "lorenz96-rk4": None}
CHECKPOINTS = (1, 2, 5)

# The costs the compiler measured on the references (section 4 of the
# design, L2.md), pinned so that a change that costs more is seen. Each
# row: image instructions, ALU a step, loads and stores a step, registers,
# scratch slots a lane, bank slots.
PINNED = {
    "lorenz63-rk4": (62, 53, 0, 0, 12, 3, 7),
    "lorenz96-rk4": (873, 760, 60, 50, 29, 48, 5),
    "henonheiles-lf": (23, 12, 0, 0, 9, 4, 5),
}


# ---- reporting ---------------------------------------------------------

class _Tally:
    ok = bad = skip = 0


TALLY = _Tally()
FAILURES = []


def ok(what):
    TALLY.ok += 1
    print(f"  ok    {what}", flush=True)


def bad(what):
    TALLY.bad += 1
    FAILURES.append(what)
    print(f"  FAIL  {what}", flush=True)


def check(cond, what, why=""):
    if cond:
        ok(what)
    else:
        bad(f"{what}" + (f": {why}" if why else ""))
    return cond


def skip(what, why):
    TALLY.skip += 1
    print(f"SKIP  {what}: {why}", flush=True)


def section(title):
    print(f"\n== {title}", flush=True)


# ---- lanes ---------------------------------------------------------------

def full_value(fmt, rng, lo, hi):
    """A value in [lo, hi] with twice the format's precision, rounded once:
    a full significand, so that no product is exact by accident."""
    num = rng.randrange(1 << (2 * fmt.prec))
    v = Fraction(lo) + (Fraction(hi) - Fraction(lo)) * \
        Fraction(num, 1 << (2 * fmt.prec))
    return K.round_once(fmt, sf.RND_RNE, v)[0] if v else 0


def lanes_for(fmt, n, rng, count, box=None):
    out = []
    for _ in range(count):
        row = []
        for comp in range(n):
            lo, hi = (box[comp] if isinstance(box, list) else
                      (box or (-3, 3)))
            row.append(full_value(fmt, rng, lo, hi))
        out.append(row)
    return out


def special_lanes(fmt, n, base, rng):
    """Three lanes, each there to raise something: one that overflows,
    one holding a signalling NaN, one holding subnormals."""
    huge = sf.round_pack(fmt, 0, 1, fmt.emax // 2 + 10)[0]
    over = list(base)
    over[0] = huge
    if n > 1:
        over[1] = huge
    snan = list(base)
    snan[0] = sf.snan_bits(fmt, 1)
    sub = [sf.min_subnormal_bits(fmt)] + \
        [rng.randrange(1, 1 << fmt.man_w) for _ in range(n - 1)]
    return [over, snan, sub]


# ---- running an image ------------------------------------------------------

def image_at(image, steps):
    """The image with its one REPEAT counting `steps` - every other word
    the same, as programs/check.py's _patch_trip makes a run of another
    length."""
    img = asm.Image.from_bytes(image)
    words = list(img.insns)
    for k, w in enumerate(words):
        d = asm.decode(w)
        if d["ctrl"] and d["op"] == asm.REPEAT:
            words[k] = asm.repeat(steps)
    return asm.Image(img.fmt, words, img.consts, img.max_deposits, img.flags,
                     scratch_depth=img.scratch_depth,
                     scratch_io=img.scratch_io).to_bytes()


def run_image(image, c, states, lane_params=None, bank=None, depth=None,
              block=None):
    d = depth or c.depth
    prog = seq.Program.from_bytes(image, scratch_depth=d)
    n = len(states)
    vals = c.lowered.bank_values() if bank is None else list(bank)
    sin = block if block is not None else c.scratch_block(states,
                                                          lane_params)
    return seq.run(prog, [0] * n, [0] * n, [0] * n, bank=vals,
                   scratch_in=sin, scratch_depth=d)


def compare(c, states, lane_params, top, bank=None, interp=None):
    """seq.py on the image at 1, 2, 5 and `top` steps against lang.run's
    checkpoints. -> (failing lanes, first step a lane or FLAGS parts,
    flags equal everywhere)."""
    marks = sorted({s for s in CHECKPOINTS if s < top} | {top})
    ref = lang.run(c.graph, states, top, lane_params=lane_params,
                   at=tuple(s for s in marks if s != top),
                   **(interp or {}))
    n, m = c.ir.n_state, c.ir.m
    lp = lane_params
    if lp is None:
        lp = [[b for _n, _d, b in c.ir.lane] for _ in states]
    failing, first, flags_ok = set(), None, True
    for s in marks:
        r = run_image(image_at(c.image, s), c, states, lane_params, bank)
        want, wflags = (ref.states, ref.flags) if s == top else ref.at[s]
        for k in range(len(states)):
            out = r.scratch_out[k * m:(k + 1) * m]
            if out[:n] != want[k] or out[n:] != list(lp[k]):
                failing.add(k)
                first = s if first is None else first
        if r.flags != wflags or r.status != 0:
            flags_ok = False
            first = s if first is None else first
    return failing, first, flags_ok, ref


# ---- the generator ------------------------------------------------------

LITS = ["1", "2", "3", "0.5", "0.25", "1.5", "(1/3)", "(2/7)", "0.1", "7",
        "0x1.8p+1", "2.5e-1"]
CMPS = ["<", "<=", ">", ">=", "=="]
FNS2 = ["copysign", "min", "max", "minnum", "maxnum"]


def g_expr(rng, ops, depth):
    if depth <= 0 or rng.random() < 0.3:
        if ops and rng.random() < 0.85:
            return rng.choice(ops)
        return rng.choice(LITS[:6])
    kind = rng.choice(["+", "-", "*", "neg", "fma", "abs", "fn2", "cmp",
                       "select", "const", "fold", "dup"])

    def sub():
        return g_expr(rng, ops, depth - 1)
    if kind in ("+", "-", "*"):
        return f"({sub()} {kind} {sub()})"
    if kind == "neg":
        return f"-({sub()})"
    if kind == "fma":
        return f"fma({sub()}, {sub()}, {sub()})"
    if kind == "abs":
        return f"abs({sub()})"
    if kind == "fn2":
        return f"{rng.choice(FNS2)}({sub()}, {sub()})"
    if kind == "cmp":
        return f"({sub()} {rng.choice(CMPS)} {sub()})"
    if kind == "select":
        return f"select({sub()}, {sub()}, {sub()})"
    if kind == "fold":                    # a neg beside a constant
        return f"({rng.choice(LITS)} * -({sub()}))"
    if kind == "dup":                     # sharing: one expression twice
        e = sub()
        return f"(({e}) * ({e}))"
    return f"({rng.choice(LITS)} {rng.choice(['+', '-', '*', '/'])} " \
           f"{rng.choice(LITS)})"


def g_system(rng, k):
    """(text, shape) - a random system the language takes, or one L1
    refuses for a reason a random source may meet (counted, not run)."""
    shape = rng.choice(["rk4", "euler", "sv", "map", "maph", "rk4", "map",
                        "pressure", "permute", "ranges"])
    fmt = rng.choice(["fp32", "fp64", "fp128", "fp256"])
    rnd = rng.choice(["rne", "rne", "rtz", "rdn", "rup", "rmm"])
    lines = [f"system g{k}", f"format {fmt}", f"round {rnd}"]
    params = [f"p{i}" for i in range(rng.randint(0, 2))]
    lanes = [f"l{i}" for i in range(rng.randint(0, 2))]
    consts = [f"c{i}" for i in range(rng.randint(0, 2))]
    if params:
        lines.append("param " + ", ".join(f"{p} = {rng.choice(LITS)}"
                                          for p in params))
    for ln in lanes:
        lines.append(f"lane param {ln}" + (f" = {rng.choice(LITS)}"
                                           if rng.random() < 0.5 else ""))
    for cn in consts:
        lines.append(f"const {cn} = {rng.choice(LITS)} * {rng.choice(LITS)}")
    extra = params + consts + lanes
    h = rng.choice(["1/8", "0.01", "1/3", "0x1p-4"])
    if shape == "pressure":
        n = rng.randint(28, 44)
        lines.append(f"state a[{n}] cyclic")
        ops = ["a[i+1]", "a[i-1]", "a[i-2]", "a[i+2]", "a[i]"] + extra
        body = g_expr(rng, ops, 2)
        lines.append(f"d/dt a[i] = fma(a[i+1] - a[i-2], a[i-1], -a[i]) + "
                     f"{body}" + "".join(f" + {e}" for e in extra))
        lines.append(f"step {rng.choice(['rk4', 'euler'])}, h = {h}")
        return "\n".join(lines) + "\n", shape
    if shape == "permute":
        n = rng.randint(2, 5)
        lines.append(f"state a[{n}] cyclic, x, y")
        rot = rng.choice(["a[i+1]", "a[i-1]", "a[i]"])
        lines.append(f"next a[i] = {rot}")
        leaves = ["y"] + params + lanes
        lines.append(f"next x = {rng.choice(leaves)}")
        lines.append(f"next y = {g_expr(rng, ['x', 'y', 'a[0]'], 2)}"
                     + "".join(f" + {e}" for e in extra))
        lines.append("step map")
        return "\n".join(lines) + "\n", shape
    if shape == "sv":
        nq = rng.randint(1, 3)
        qs = [f"q{i}" for i in range(nq)]
        ms = [f"m{i}" for i in range(nq)]
        lines.append("state " + ", ".join(qs + ms))
        eqs = [f"d/dt {q} = {g_expr(rng, ms + extra, 2)}" for q in qs]
        eqs += [f"d/dt {m} = {g_expr(rng, qs + extra, 3)}" for m in ms]
        if extra:
            eqs[0] += " + " + " + ".join(extra)
        lines += eqs
        lines.append(f"step stormer-verlet, h = {h}, q = ({', '.join(qs)}),"
                     f" p = ({', '.join(ms)})")
        return "\n".join(lines) + "\n", shape
    integ = {"rk4": "rk4", "euler": "euler", "map": "map", "maph": "maph",
             "ranges": "rk4"}[shape]
    scal = [f"s{i}" for i in range(rng.randint(1, 3))]
    arr = None
    if rng.random() < 0.5 or shape == "ranges":
        arr = (rng.randint(3, 6), shape != "ranges" and rng.random() < 0.6)
    decl = scal + ([f"a[{arr[0]}]" + (" cyclic" if arr[1] else "")]
                   if arr else [])
    lines.append("state " + ", ".join(decl))
    word = "next" if integ.startswith("map") else "d/dt"
    operands = scal + extra + (["h", "(h/2)"] if integ == "maph" else [])
    lets = [f"r{i}" for i in range(rng.randint(0, 2))]
    for i, r in enumerate(lets):
        lines.append(f"let {r} = {g_expr(rng, operands + lets[:i], 2)}")
    eqs = []
    for s in scal:
        tail = ["a[0]"] if arr else []
        eqs.append(f"{word} {s} = {g_expr(rng, operands + lets + tail, 3)}")
    if arr:
        if arr[1]:
            near = ["a[i]", "a[i+1]", "a[i-1]"]
            eqs.append(f"{word} a[i] = {g_expr(rng, near + scal, 2)}")
        else:
            last = arr[0] - 1
            eqs.append(f"{word} a[i] = {g_expr(rng, ['a[i-1]', 'a[i]', 'a[i+1]'] + scal, 2)} for i in 1..{last - 1}")
            eqs.append(f"{word} a[0] = {g_expr(rng, ['a[0]', 'a[1]'] + scal, 2)}")
            eqs.append(f"{word} a[{last}] = {g_expr(rng, [f'a[{last}]', f'a[{last - 1}]'] + scal, 2)}")
    used = extra + lets + (["h"] if integ == "maph" else [])
    if used:
        eqs[0] += " + " + " + ".join(used)
    lines += eqs
    if integ == "map":
        lines.append("step map")
    elif integ == "maph":
        lines.append(f"step map, h = {h}")
    else:
        lines.append(f"step {integ}, h = {h}")
    return "\n".join(lines) + "\n", shape


# A random source may meet a refusal a writer could meet too: a negated
# constant that is exactly zero, a constant mixing h with a rational, a
# constant past a narrow format. Those are counted and named; any other
# refusal is a defect in the generator, and fails.
ARTIFACTS = {"constant-negative-zero", "h-nonlinear", "constant-overflow",
             "constant-rounds-to-zero", "halving-underflow"}


def with_format(text, fmt):
    lines = text.split("\n")
    return "\n".join(f"format {fmt}" if ln.startswith("format ") else ln
                     for ln in lines)


def with_round(text, rnd):
    lines = text.split("\n")
    out, done = [], False
    for ln in lines:
        if ln.startswith("round "):
            out.append(f"round {rnd}")
            done = True
        else:
            out.append(ln)
            if ln.startswith("format ") and not done and \
                    not any(x.startswith("round ") for x in lines):
                out.append(f"round {rnd}")
                done = True
    return "\n".join(out)


# ---- coverage ---------------------------------------------------------------

COVER = {"ops": {}, "rounds": set(), "formats": set(), "integrators": set(),
         "shared": 0, "folded": 0, "spilled": 0, "copies": 0,
         "empty_step": 0, "lane_params": 0, "homed": 0, "pinned": 0,
         "flags": 0, "systems": 0}


def cover(c, flags):
    COVER["systems"] += 1
    for op, k in c.ir.op_counts().items():
        COVER["ops"][op] = COVER["ops"].get(op, 0) + k
    COVER["rounds"].add(c.ir.rnd_name)
    COVER["formats"].add(c.ir.fmt_name)
    COVER["integrators"].add(c.ir.integrator[0])
    COVER["shared"] += c.lowered.shared
    COVER["folded"] += len(c.lowered.folds)
    COVER["spilled"] += c.program.spill_slots
    COVER["copies"] += c.program.step_counts()["copies"]
    COVER["empty_step"] += not c.lowered.nodes
    COVER["lane_params"] += len(c.ir.lane)
    COVER["homed"] += c.program.pinning != "all"
    COVER["pinned"] += c.program.pinning != "none"
    COVER["flags"] |= flags


# ---- A and B: the references -------------------------------------------

def ref_text(base, fmt):
    src = SYSTEMS / f"{base}-fp64.cftl"
    return with_format(src.read_text(encoding="ascii"), fmt)


def ref_compile(base, fmt, rnd=None, steps=None):
    text = ref_text(base, fmt)
    if rnd is not None:
        text = with_round(text, rnd)
    name = f"{base}-{fmt}" + (f"-{rnd}" if rnd else "")
    return cftc.compile_text(text, steps or REFS[base],
                             source=f"programs/systems/{name}.cftl",
                             stem=name)


def ref_lanes(base, fmt, n, rng):
    lanes = lanes_for(fmt, n, rng, REF_LANES[base], BOX[base])
    specials = special_lanes(fmt, n, lanes[0], rng)
    return lanes, specials


def hand_image(base, fmt):
    name = f"{base}-{fmt}"
    data = asm.assemble((PROGRAMS / f"{name}.cfta").read_text(
        encoding="ascii"), name)
    man = {}
    for line in (PROGRAMS / "MANIFEST").read_text(encoding="utf-8") \
            .splitlines():
        if line.strip() and not line.startswith("#"):
            hsh, fname = line.split()
            man[fname] = hsh
    return data, hashlib.sha256(data).hexdigest() == man.get(name + ".cftp")


def hand_costs(image):
    """gen_odes.py's image in the same terms as the compiled one."""
    img = asm.Image.from_bytes(image)
    words = [asm.decode(w) for w in img.insns]
    s = next(k for k, d in enumerate(words) if d["ctrl"] and
             d["op"] == asm.REPEAT)
    e = next(k for k, d in enumerate(words) if d["ctrl"] and
             d["op"] == asm.ENDREP)
    body = []
    regs = set()
    slots = set()
    for d in words[s + 1:e]:
        if d["ctrl"]:
            slot = d["imm"] & asm.SLOT_MASK
            slots.add(slot)
            if d["op"] == asm.LDL:
                body.append(Ins("ldl", rd=d["rd"], slot=slot))
                regs.add(d["rd"])
            else:
                body.append(Ins("stl", srcs=(("r", d["ra"]),), slot=slot))
                regs.add(d["ra"])
            continue
        srcs = []
        for (idx, kk), f in zip(asm.sources(d), ("ra", "rb", "rc")):
            if f in asm.OP_FIELDS[d["op"]]:
                srcs.append(("b", idx) if kk else ("r", idx))
                if not kk:
                    regs.add(idx)
        regs.add(d["rd"])
        body.append(Ins("alu", rd=d["rd"], srcs=srcs, op="x"))
    for d in words:
        if d["ctrl"] and d["op"] in (asm.LDL, asm.STL):
            slots.add(d["imm"] & asm.SLOT_MASK)
            regs.add(d["rd"] if d["op"] == asm.LDL else d["ra"])
    alu = sum(1 for i in body if i.kind == "alu")
    loads = sum(1 for i in body if i.kind == "ldl")
    stores = sum(1 for i in body if i.kind == "stl")
    return {"instructions": len(img.insns), "alu": alu, "loads": loads,
            "stores": stores, "registers": len(regs),
            "slots": max(slots) + 1 if slots else 0,
            "bank": img.n_consts, "one_beat": cycles(body, 1),
            "sixteen_beats": cycles(body, 16)}


def compiled_costs(c):
    pc = c.program.step_counts()
    return {"instructions": len(c.image_obj.insns), "alu": pc["alu"],
            "loads": pc["loads"], "stores": pc["stores"],
            "registers": len(c.program.registers()),
            "slots": c.program.slots_used, "bank": len(c.lowered.slots),
            "one_beat": c.cycles_one_beat,
            "sixteen_beats": c.cycles_sixteen_beats}


def leg_references(rng):
    section("A. the references, at every format, against the interpreter; "
            "B. against gen_odes.py's images")
    table = []
    for base in REFS:
        for fmt in ("fp32", "fp64", "fp128", "fp256"):
            c = ref_compile(base, fmt)
            n = c.ir.n_state
            lanes, specials = ref_lanes(base, c.ir.fmt, n, rng)
            allv = lanes + specials
            failing, first, fok, ref = compare(c, allv, None, REFS[base])
            cover(c, ref.flags)
            check(not failing and fok,
                  f"{base} {fmt}: {len(allv)} lanes at 1, 2, 5 and "
                  f"{REFS[base]} steps equal the interpreter, FLAGS "
                  f"{ref.flags:#x} included",
                  f"{len(failing)} lanes differ from step {first}, FLAGS "
                  f"{'equal' if fok else 'differ'}")
            for role, lane, flag in (("overflow", specials[0],
                                      sf.FLAG_OVERFLOW),
                                     ("signalling NaN", specials[1],
                                      sf.FLAG_INVALID)):
                r1 = lang.run(c.graph, [lane], REFS[base])
                check(r1.flags & flag,
                      f"{base} {fmt}: the {role} lane raises "
                      f"{'overflow' if flag == sf.FLAG_OVERFLOW else 'invalid'}")
            if fmt in ("fp64", "fp256"):
                classic = (PROGRAMS / f"{base}-{fmt}.classic.bank") \
                    .read_bytes()
                check(c.bank == classic, f"{base} {fmt}: the compiled bank "
                      f"is the classic bank byte for byte "
                      f"({len(c.lowered.slots)} slots)")
                hand, in_manifest = hand_image(base, fmt)
                check(in_manifest, f"{base} {fmt}: gen_odes.py's image is "
                      f"programs/MANIFEST's")
                hfail = set()
                for s in sorted({*CHECKPOINTS, REFS[base]}):
                    hr = run_image(image_at(hand, s), c, allv,
                                   bank=c.lowered.bank_values(), depth=256)
                    cr = run_image(image_at(c.image, s), c, allv)
                    m = c.ir.m
                    for k in range(len(allv)):
                        if hr.scratch_out[k * m:(k + 1) * m] != \
                                cr.scratch_out[k * m:(k + 1) * m]:
                            hfail.add(k)
                    if hr.flags != cr.flags:
                        hfail.add(-1)
                check(not hfail, f"{base} {fmt}: gen_odes.py's image on the "
                      f"classic bank equals the compiled image at every "
                      f"checkpoint, states and FLAGS",
                      f"{len(hfail)} differences")
                if fmt == "fp64":
                    table.append((base, hand_costs(hand), compiled_costs(c)))
                    got = compiled_costs(c)
                    row = (got["instructions"], got["alu"], got["loads"],
                           got["stores"], got["registers"], got["slots"],
                           got["bank"])
                    check(row == PINNED[base], f"{base}: the compiled costs "
                          f"are the pinned {PINNED[base]}",
                          f"measured {row}")
    print("\n  the references' costs, a step unless said (gen_odes.py "
          "against compiled; cycles from the revision-7 model, believed):")
    keys = ("instructions", "alu", "loads", "stores", "registers", "slots",
            "bank", "one_beat", "sixteen_beats")
    print("  " + "system".ljust(16) + "".join(k.rjust(15) for k in keys))
    for base, h, cpl in table:
        print("  " + base.ljust(16) + "".join(
            f"{h[k]:>7}/{cpl[k]:<7}" for k in keys))
    section("A. Lorenz-63 and Henon-Heiles under every attribute")
    for base in ("lorenz63-rk4", "henonheiles-lf"):
        for rnd in ("rtz", "rdn", "rup", "rmm"):
            c = ref_compile(base, "fp64", rnd)
            n = c.ir.n_state
            lanes = lanes_for(c.ir.fmt, n, rng, 16, BOX[base])
            lanes += special_lanes(c.ir.fmt, n, lanes[0], rng)
            failing, first, fok, ref = compare(c, lanes, None, REFS[base])
            cover(c, ref.flags)
            check(not failing and fok, f"{base} fp64 {rnd}: {len(lanes)} "
                  f"lanes at four checkpoints equal the interpreter",
                  f"{len(failing)} lanes differ from step {first}")


# ---- A: the generated corpus --------------------------------------------

# Shapes the lowering must get right, written out so that no draw of the
# generator can leave one out: every built-in once, an empty step, a swap
# and a rotation (the closing copies' cycles, pinned and homed), outputs
# that are a param and a lane param, the fold in a flow and in a map, and
# sharing. Each runs at every format.
SHAPES = {
    "every-builtin": (
        "system builtins\nformat fp64\nround rne\nstate x, y, z\n"
        "param a = 0.75\nlane param w = 1.5\n"
        "next x = select(x < y, copysign(x, z), -(abs(y)))"
        " + min(x, z) + max(y, a)\n"
        "next y = fma(x, y, z) - (minnum(y, w) * maxnum(z, x))"
        " + (x <= z) + (y > z)\n"
        "next z = (z >= x) + (x == y) - z\nstep map\n"),
    "empty-step": "system idm\nformat fp64\nstate x, y\nnext x = x\n"
                  "next y = y\nstep map\n",
    "swap": "system swp\nformat fp64\nstate x, y, z\nnext x = y\n"
            "next y = x\nnext z = z * 2\nstep map\n",
    "rotation": "system rot\nformat fp64\nstate a[30] cyclic\n"
                "next a[i] = a[i+1]\nstep map\n",
    "rotation-homed": "system roth\nformat fp64\nstate a[40] cyclic, s\n"
                      "next a[i] = a[i-1]\nnext s = s + a[0] * a[39]\n"
                      "step map\n",
    "leaf-outputs": "system leaves\nformat fp64\nstate x, y, z\n"
                    "param p = 2.5\nlane param m\nnext x = p\nnext y = m\n"
                    "next z = z * x + y\nstep map\n",
    "fold-flow": "system nf\nformat fp64\nround rup\nstate x, y\n"
                 "d/dt x = -(x * y)\nd/dt y = 3 * -(x + y)\n"
                 "step euler, h = 1/3\n",
    "fold-map": "system nfm\nformat fp64\nround rdn\nstate x\n"
                "next x = fma(h, -(x * x), x)\nstep map, h = 0.1\n",
    "shared": "system sh\nformat fp64\nstate x, y\n"
              "next x = (x - y) * (x - y)\nnext y = (y - x) + (x - y)\n"
              "step map\n",
}


def corpus_texts(count, seed="lang corpus"):
    rng = random.Random(seed)
    out = []
    k = 0
    while len(out) < count:
        text, shape = g_system(rng, k)
        k += 1
        out.append((text, shape))
    return out


def leg_corpus(count, rng):
    section(f"A. {len(SHAPES)} written shapes and {count} generated systems, "
            f"at every format L1 takes them")
    refused = {}
    texts = [(t, s) for s, t in SHAPES.items()] + corpus_texts(count)
    runs = 0
    for k, (text, shape) in enumerate(texts):
        own = next(ln.split()[1] for ln in text.split("\n")
                   if ln.startswith("format "))
        fmts = [own] if shape == "pressure" else \
            ["fp32", "fp64", "fp128", "fp256"]
        for fmt in fmts:
            t = with_format(text, fmt)
            try:
                c = cftc.compile_text(t, 4, source=f"corpus {k} {fmt}",
                                      stem=f"g{k}")
            except lang.Refusal as e:
                if e.name not in ARTIFACTS:
                    bad(f"corpus {k} ({shape}) {fmt}: refused {e.name}, "
                        f"which no generated system should meet: {e}")
                    print(t)
                else:
                    refused[e.name] = refused.get(e.name, 0) + 1
                continue
            except cftc.InternalError as e:
                bad(f"corpus {k} ({shape}) {fmt}: internal error: {e}")
                print(t)
                continue
            g = c.ir
            lanes = lanes_for(g.fmt, g.n_state, rng, 8)
            lanes += special_lanes(g.fmt, g.n_state, lanes[0], rng)
            lp = None
            if g.lane:
                lp = [[full_value(g.fmt, rng, Fraction(1, 2), 2)
                       for _ in g.lane] for _ in lanes]
            failing, first, fok, ref = compare(c, lanes, lp, 4)
            cover(c, ref.flags)
            runs += 1
            if failing or not fok:
                bad(f"corpus {k} ({shape}) {fmt}: {len(failing)} of "
                    f"{len(lanes)} lanes differ from step {first}, FLAGS "
                    f"{'equal' if fok else 'differ'}")
                print(t)
    check(runs > 0, f"the corpus: {runs} compiled systems equal the "
          f"interpreter on 11 lanes at 1, 2 and 4 steps (each one held "
          f"above)")
    print(f"  refused as a writer would be, by name: "
          f"{dict(sorted(refused.items())) or 'none'}")


# ---- C and D: banks, params, resume ---------------------------------------

def leg_banks(rng):
    section("C. the halved bank and the params; D. resume")
    for base in REFS:
        c = ref_compile(base, "fp64")
        g = c.ir
        lanes = lanes_for(g.fmt, g.n_state, rng, 8, BOX[base])
        h = g.integrator[1]
        failing, first, fok, _ref = compare(
            c, lanes, None, REFS[base], bank=c.lowered.half_bits,
            interp={"h": h / 2})
        check(not failing and fok, f"{base}: the halved bank equals the "
              f"interpreter at h/2 = {K.literal(h / 2)}",
              f"{len(failing)} lanes from step {first}")
        if g.param:
            vals = c.lowered.bank_values()
            pbits = {}
            for s_idx, s in enumerate(c.lowered.slots):
                if s.kind == "param":
                    v = full_value(g.fmt, rng, Fraction(1, 2), 30)
                    vals[s_idx] = v
                    pbits[g.param[s.index][0]] = v
            failing, first, fok, _ref = compare(
                c, lanes, None, REFS[base], bank=vals,
                interp={"param_bits": pbits})
            check(not failing and fok, f"{base}: every param's slot at a "
                  f"random value equals the interpreter on those "
                  f"encodings ({', '.join(pbits)})",
                  f"{len(failing)} lanes from step {first}")
        # resume: 2S in one segment against two segments of S
        S = REFS[base] // 2
        whole = run_image(image_at(c.image, 2 * S), c, lanes)
        half1 = run_image(image_at(c.image, S), c, lanes)
        half2 = run_image(image_at(c.image, S), c, lanes,
                          block=half1.scratch_out)
        check(whole.scratch_out == half2.scratch_out and
              whole.flags == half1.flags | half2.flags,
              f"{base}: one segment of {2 * S} steps is two segments of "
              f"{S}, states and FLAGS")
    c = cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp64.cftl", 5,
                          params={"sigma": "12", "beta": "8/3"})
    want = K.round_once(c.ir.fmt, c.ir.rnd, Fraction(12))[0]
    slot = next(k for k, s in enumerate(c.lowered.slots)
                if s.kind == "param" and c.ir.param[s.index][0] == "sigma")
    check(c.lowered.slots[slot].bits == want and
          [o["name"] for o in c.manifest["param_overrides"]] ==
          ["sigma", "beta"],
          "--param sigma=12 writes RN(12) into sigma's slot, and the "
          "manifest records both overrides")


# ---- E: libcft's software backend -----------------------------------------

def leg_libcft(segrun, audit, rng, work):
    section("E. cft-segrun certifies the compiled references; both "
            "auditors accept")
    if not segrun or not Path(segrun).is_file():
        skip("E: cft-segrun's certificates of the compiled images",
             f"no cft-segrun at {segrun!r} (the stage builds it)")
        return
    segrun = Path(segrun).resolve()
    have_audit = bool(audit) and Path(audit).is_file()
    if have_audit:
        audit = Path(audit).resolve()
    if not have_audit:
        skip("E: cft-audit on each certificate",
             f"no cft-audit at {audit!r} (the stage builds it)")
    for base in REFS:
        for fmt in ("fp64", "fp256"):
            c = cftc.compile_file(SYSTEMS / f"{base}-{fmt}.cftl", REFS[base],
                                  source=f"programs/systems/{base}-{fmt}"
                                         ".cftl")
            certify(c, f"{base}-{fmt}", segrun, audit if have_audit else None,
                    rng, work)
    text, _shape = next((t, s) for t, s in corpus_texts(40, "lang e")
                        if "lane param" in t and "h = " in t
                        and "step map\n" not in t)
    try:
        c = cftc.compile_text(with_format(text, "fp64"), 6,
                              source="generated", stem="generated")
    except lang.Refusal as e:
        skip("E: a generated system with lane params", f"L1 refused it: {e}")
        return
    certify(c, "generated-lane-params", segrun,
            audit if have_audit else None, rng, work)


def certify(c, name, segrun, audit, rng, work):
    g = c.ir
    d = work / "certs" / name
    d.mkdir(parents=True, exist_ok=True)
    lanes = lanes_for(g.fmt, g.n_state, rng, 4, BOX.get(name.rsplit("-", 1)[0]))
    lp = None
    if g.lane:
        lp = [[full_value(g.fmt, rng, Fraction(1, 2), 2) for _ in g.lane]
              for _ in lanes]
    block = c.scratch_block(lanes, lp)
    (d / "image.cftp").write_bytes(c.image)
    (d / "main.bank").write_bytes(c.bank)
    (d / "half.bank").write_bytes(c.half_bank)
    (d / "init.bin").write_bytes(cert.state_bytes(g.fmt_name, block))
    out, states = d / "c.cert", d / "states"
    for p in (out,):
        if p.exists():
            p.unlink()
    if states.exists():
        shutil.rmtree(states)
    args = ["--out", out, "--states", states, "--open", "--device", "sw"]
    if c.depth != 256:
        args += ["--scratch-depth", c.depth]
    args += ["--run", "main", "--image", d / "image.cftp", "--bank",
             d / "main.bank", "--init", d / "init.bin", "--segments", 2,
             "--steps", c.steps,
             "--run", "half-step", "--h-slots",
             ",".join(str(s) for s in c.lowered.h_slots),
             "--image", d / "image.cftp", "--bank", d / "half.bank",
             "--init", d / "init.bin", "--segments", 4, "--steps", c.steps,
             "--entry", "step-halving", "--uses", 1, "--scope", "max-lanes",
             "--value", f"rounded:{g.fmt_name}:rup"]
    t0 = time.perf_counter()
    r = subprocess.run([str(segrun)] + [str(a) for a in args],
                       capture_output=True, text=True, timeout=600)
    if not check(r.returncode == 0, f"{name}: cft-segrun certifies it, a "
                 f"main run of 2 segments and a half-step run of 4 on the "
                 f"halved bank, h-slots {c.lowered.h_slots} "
                 f"({time.perf_counter() - t0:.1f} s)",
                 f"rc {r.returncode}: {r.stderr.strip()[-300:]}"):
        return
    data = out.read_bytes()
    try:
        cert.parse(data)
        ok(f"{name}: the golden reader accepts it ({len(data)} bytes)")
    except cert.Refusal as e:
        bad(f"{name}: the golden reader refuses it: {e}")
        return
    sb = {}
    for run_i, segs in ((0, 2), (1, 4)):
        sb[run_i] = {b: (states / f"run-{run_i}-boundary-{b}.bin")
                     .read_bytes() for b in range(segs + 1)}
    progs = {0: (c.image, c.bank), 1: (c.image, c.half_bank)}
    seed = hashlib.sha256(f"lang {name}".encode()).digest()
    full = sampled = None
    try:
        t0 = time.perf_counter()
        full = cert.audit(data, None, progs, states=sb)
        ok(f"{name}: the golden audit accepts it in full, the step-halving "
           f"estimate re-derived ({time.perf_counter() - t0:.1f} s)")
        sampled = cert.audit(data, None, progs, states=sb,
                             choose={0: ("sample", 1), 1: ("sample", 2)},
                             seed=seed)
        ok(f"{name}: the golden audit accepts a sample")
    except cert.Refusal as e:
        bad(f"{name}: the golden audit refuses it: {e.name}: {e.message}")
        return
    if not audit:
        return
    for how, verdict, extra in (
            ("in full", full, ["--choose", "all", "--choose", "all"]),
            ("sampled", sampled, ["--choose", "sample:1", "--choose",
                                  "sample:2"])):
        args = ["--cert", out, "--states", states, "--seed", seed.hex(),
                "--run", "0", "--image", d / "image.cftp", "--bank",
                d / "main.bank", "--choose", extra[1],
                "--run", "1", "--image", d / "image.cftp", "--bank",
                d / "half.bank", "--choose", extra[3]]
        r = subprocess.run([str(audit)] + [str(a) for a in args],
                           capture_output=True, text=True, timeout=600)
        got = r.stdout.split("\n")
        if got and got[-1] == "":
            got = got[:-1]
        check(r.returncode == 0 and got == list(verdict.lines()),
              f"{name}: cft-audit accepts it {how}, the golden verdict line "
              f"for line",
              f"rc {r.returncode}: {r.stderr.strip()[-300:]}")


# ---- F: determinism ----------------------------------------------------------

def compiled_references():
    out = {}
    for base, steps in REFS.items():
        for fmt in ("fp64", "fp256"):
            c = cftc.compile_file(SYSTEMS / f"{base}-{fmt}.cftl", steps,
                                  source=f"programs/systems/{base}-{fmt}"
                                         ".cftl")
            out.update(c.files())
    return out


def digests_main(path):
    """The child of leg F: compile what the file lists, print digests."""
    jobs = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for name, data in compiled_references().items():
        out[name] = hashlib.sha256(data).hexdigest()
    for k, text in enumerate(jobs):
        try:
            c = cftc.compile_text(text, 4, source=f"corpus {k}", stem=f"g{k}")
        except lang.Refusal as e:
            out[f"g{k}"] = f"refused {e.name}"
            continue
        for name, data in c.files().items():
            out[name] = hashlib.sha256(data).hexdigest()
    print(json.dumps(out, sort_keys=True))
    return 0


def leg_determinism(work):
    section("F. determinism: two processes, two hash seeds, the committed "
            "references")
    jobs = [t for t, _s in corpus_texts(6, "lang determinism")]
    jf = work / "determinism.json"
    jf.write_text(json.dumps(jobs), encoding="utf-8")
    seen = []
    for seed in ("0", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                            "--digests", str(jf)], capture_output=True,
                           text=True, env=env, timeout=900)
        if not check(r.returncode == 0, f"the compile under PYTHONHASHSEED "
                     f"{seed} ran", r.stderr.strip()[-300:]):
            return
        seen.append(json.loads(r.stdout))
    check(seen[0] == seen[1] and len(seen[0]) > 50,
          f"PYTHONHASHSEED 0 and 4242 write the same bytes: {len(seen[0])} "
          f"files (the six references and six generated systems, every "
          f"output)")
    files = compiled_references()
    have = sorted(p.name for p in COMPILED.iterdir()) if COMPILED.is_dir() \
        else []
    check(have == sorted(files), f"programs/systems/compiled/ holds exactly "
          f"the six references' {len(files)} files",
          f"it holds {len(have)}: run programs/lang_check.py --write")
    wrong = [n for n, data in files.items()
             if (COMPILED / n).is_file() and (COMPILED / n).read_bytes()
             != data]
    check(not wrong, "every committed compiled reference is what the "
          "compiler writes, byte for byte", f"differ: {wrong[:6]}")


# ---- G: refusals -------------------------------------------------------------

def leg_refusals():
    section("G. every refusal the compiler makes, by name")
    made = set()

    def expect(name, fn, what):
        try:
            fn()
        except lang.Refusal as e:
            if check(e.name == name, f"{name}: {what}",
                     f"refused {e.name} instead: {e}"):
                made.add(name)
            print(f"        {e}")
            return
        bad(f"{name}: {what} - accepted")
    l63 = SYSTEMS / "lorenz63-rk4-fp64.cftl"
    l96 = SYSTEMS / "lorenz96-rk4-fp64.cftl"
    trim = TG.Target("u50-trim", ("fp64", "fp128"), 32768, 512, 2048, 1024,
                     TG.TILE_FEATURES)
    pre_r4 = TG.Target("pre-r4", TG.ALL_FORMATS, 16384, 512, 256, 64,
                       TG.TILE_FEATURES & ~TG.FEATURE_BITS["SCRATCH_STRICT"])
    tiny = TG.Target("tiny", TG.ALL_FORMATS, 16, 512, 256, 64,
                     TG.TILE_FEATURES)
    big = ("system big\nformat fp64\nstate x[257]\n"
           "next x[i] = x[i] + 1\nstep map\n")
    halving = ("system hu\nformat fp32\nstate x\nnext x = x + h\n"
               "step map, h = 3 * 0x1p-149\n")
    expect("target-format",
           lambda: cftc.compile_file(SYSTEMS / "lorenz63-rk4-fp256.cftl", 3,
                                     target=trim),
           "fp256 for a build that carries fp64 and fp128")
    expect("target-feature",
           lambda: cftc.compile_file(l63, 3, target=pre_r4),
           "a strict image for a tile without CAPS2[6]")
    expect("program-capacity",
           lambda: cftc.compile_file(l63, 3, target=tiny),
           "62 instructions for a target that holds 16")
    expect("scratch-capacity",
           lambda: cftc.compile_text(big, 2, target="sw"),
           "257 state values a lane on the software backend's 256")
    try:
        c = cftc.compile_text(big, 2, target="u50-rev7")
        check(c.program.slots_used == 257 and c.depth == 512,
              "the same program is accepted where the scratch is deep "
              "enough (u50-rev7), declaring .scratch 512")
    except lang.Refusal as e:
        bad(f"the 257-slot program is refused on u50-rev7: {e}")
    expect("loader-bound",
           lambda: cftc.compile_file(l96, cftc.MAX_STEPS),
           "4,294,967,295 steps of Lorenz-96")
    expect("segment-steps", lambda: cftc.compile_file(l63, 0), "0 steps")
    expect("segment-steps", lambda: cftc.compile_file(l63, 1 << 32),
           "2^32 steps")
    expect("halving-underflow", lambda: cftc.compile_text(halving, 2),
           "h = 3 x 2^-149 at fp32, whose half is not exact")
    check(made == set(cftc.NAMES), f"every one of the compiler's "
          f"{len(cftc.NAMES)} names was made", f"missing "
          f"{sorted(set(cftc.NAMES) - made)}")


# ---- H: plants -----------------------------------------------------------------

CHECK_OFF = ("__init__.py", "    verify(low, prog, c.image, steps, half)\n",
             "    pass  # PLANT: the internal check, off\n")

PLANTS = {
    "a dropped node": [
        ("regalloc.py", '        self.emit(Ins("alu", op=nd.op,',
         '        (self.emit if j != len(self.low.nodes) // 2 else '
         '(lambda _i: None))(Ins("alu", op=nd.op,')],
    "a swapped fma operand that changes the sum": [
        ("regalloc.py",
         "        dying = [k for k in keys if self.next_use(k, q) is None]\n",
         "        if nd.op == 'fma' and srcs[1] != srcs[2] and j == min(\n"
         "                x for x, y in enumerate(self.low.nodes)\n"
         "                if y.op == 'fma' and y.args[1] != y.args[2]):\n"
         "            srcs = (srcs[0], srcs[2], srcs[1])\n"
         "        dying = [k for k in keys if self.next_use(k, q) is None]\n")],
    "a register reused while live": [
        ("__init__.py", "    c.program = prog = best_program(low)\n",
         "    c.program = prog = best_program(low)\n"
         "    _plant_reuse(prog)\n"),
        ("__init__.py", "def compile_text(",
         "def _plant_reuse(prog):\n"
         "    body = prog.body\n"
         "    for i, ins in enumerate(body):\n"
         "        if ins.kind != 'alu':\n"
         "            continue\n"
         "        for j in range(i + 1, len(body)):\n"
         "            for r in body[j].reads():\n"
         "                if r == ins.rd:\n"
         "                    continue\n"
         "                live = all(r != body[x].rd for x in range(i, j)\n"
         "                           if body[x].rd is not None)\n"
         "                if live and any(r in body[x].reads() or r == body[x].rd\n"
         "                                for x in range(0, i)):\n"
         "                    ins.rd = r\n"
         "                    return\n"
         "\n\n"
         "def compile_text(")],
    "a wrong h-scaled slot": [
        ("regalloc.py",
         '                     else ("b", self.low.slot_of[a]) for a in nd.args)',
         '                     else ("b", _plant_slot(self.low, a)) for a in nd.args)'),
        ("regalloc.py", "def allocate(low, order, pinning=\"none\"):",
         "def _plant_slot(low, a):\n"
         "    k = low.slot_of[a]\n"
         "    if low.slots[k].factor == __import__('fractions').Fraction(1, 2):\n"
         "        for kk, s in enumerate(low.slots):\n"
         "            if s.kind == 'const' and s.factor == 1:\n"
         "                return kk\n"
         "    return k\n"
         "\n\n"
         "def allocate(low, order, pinning=\"none\"):")],
    "a fold that is not bit-identical (RN(-c) for -RN(c))": [
        ("lower.py", "                            bits ^ sign, flags))",
         "                            __import__('cft_golden.lang.constants',"
         " fromlist=['x']).round_once(graph.fmt, graph.rnd, -exact)[0],"
         " flags))")],
}
PLANT_SYSTEMS = {
    "a fold that is not bit-identical (RN(-c) for -RN(c))":
        [("henonheiles-lf", "fp64", "rdn"), ("henonheiles-lf", "fp64", "rup"),
         ("henonheiles-lf", "fp64", None)],
}
DEFAULT_PLANT_SYSTEMS = [("lorenz63-rk4", "fp64", None),
                         ("henonheiles-lf", "fp64", None)]


def plant_copy(edits, tag, work):
    d = work / "plants" / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    pkg = d / f"cftc_plant_{tag}"
    shutil.copytree(ROOT / "python" / "cftc", pkg,
                    ignore=shutil.ignore_patterns("__pycache__"))
    for fname, old, new in edits:
        p = pkg / fname
        text = p.read_text(encoding="utf-8")
        if text.count(old) != 1:
            raise AssertionError(f"the plant's anchor is in {fname} "
                                 f"{text.count(old)} times, not once: "
                                 f"{old.strip()[:60]!r}")
        p.write_text(text.replace(old, new), encoding="utf-8")
    sys.path.insert(0, str(d))
    try:
        mod = importlib.import_module(pkg.name)
    finally:
        sys.path.remove(str(d))
    return mod


def leg_plants(rng, work):
    section("H. plants in a copy of the package: the internal check stops "
            "each, and with it off seq.py turns each red")
    for k, (what, edits) in enumerate(PLANTS.items()):
        systems = PLANT_SYSTEMS.get(what, DEFAULT_PLANT_SYSTEMS)
        try:
            on = plant_copy(edits, f"{k}on", work)
            off = plant_copy(edits + [CHECK_OFF], f"{k}off", work)
        except AssertionError as e:
            bad(f"plant {what!r}: {e}")
            continue
        stopped = []
        lanes_red = {}
        firsts = []
        for base, fmt, rnd in systems:
            text = ref_text(base, fmt)
            if rnd:
                text = with_round(text, rnd)
            tag = f"{base} {fmt}{' ' + rnd if rnd else ''}"
            try:
                on.compile_text(text, REFS[base], source=tag)
                stopped.append((tag, "accepted"))
            except on.InternalError as e:
                stopped.append((tag, "stopped"))
                print(f"        {tag}: {str(e)[:150]}")
            except Exception as e:                     # noqa: BLE001
                stopped.append((tag, f"{type(e).__name__}"))
            try:
                c = off.compile_text(text, REFS[base], source=tag)
            except Exception as e:                     # noqa: BLE001
                bad(f"plant {what!r}: with the check off {tag} does not "
                    f"compile ({type(e).__name__}: {e})")
                continue
            lanes = lanes_for(c.ir.fmt, c.ir.n_state, rng, REF_LANES[base],
                              BOX[base])
            failing, first, fok, _ref = compare(c, lanes, None, REFS[base])
            lanes_red[tag] = (len(failing), len(lanes), first, fok)
            if failing or not fok:
                firsts.append(first)
        visible = [t for t, (nf, _n, _f, fok) in lanes_red.items()
                   if nf or not fok]
        check(any(s == "stopped" for _t, s in stopped) and
              all(s in ("stopped", "accepted") for _t, s in stopped),
              f"plant {what!r}: the internal check stops it "
              f"({', '.join(f'{t}: {s}' for t, s in stopped)})")
        check(bool(visible), f"plant {what!r}: red on seq.py with the check "
              f"off - " + "; ".join(
                  f"{t}: {nf} of {n} lanes from step {f}"
                  + ("" if fok else ", FLAGS differ")
                  for t, (nf, n, f, fok) in lanes_red.items()),
              "no lane differs")


# ---- I: coverage ---------------------------------------------------------------

def leg_coverage():
    section("I. what the corpus covered")
    ops = COVER["ops"]
    want_ops = ["fma", "add", "sub", "mul", "neg", "abs", "copysign", "min",
                "max", "minnum", "maxnum", "cmplt", "cmple", "cmpeq",
                "select"]
    print(f"  {COVER['systems']} systems; ops {dict(sorted(ops.items()))}")
    check(all(ops.get(o) for o in want_ops), "every operation of the "
          "language was compiled and run", f"missing "
          f"{[o for o in want_ops if not ops.get(o)]}")
    check(COVER["rounds"] == {"rne", "rtz", "rdn", "rup", "rmm"},
          "every attribute", f"{sorted(COVER['rounds'])}")
    check(COVER["formats"] == {"fp32", "fp64", "fp128", "fp256"},
          "every format", f"{sorted(COVER['formats'])}")
    check(COVER["integrators"] >= {"rk4", "euler", "stormer-verlet",
                                   "map"}, "every integrator",
          f"{sorted(COVER['integrators'])}")
    for key, what in (("shared", "shared subexpressions"),
                      ("folded", "folds"), ("spilled", "spill slots"),
                      ("copies", "closing copies"),
                      ("empty_step", "empty steps"),
                      ("lane_params", "lane params"),
                      ("homed", "systems with homed values"),
                      ("pinned", "systems with pinned values")):
        check(COVER[key] > 0, f"{what}: {COVER[key]}")
    for flag, word in ((sf.FLAG_OVERFLOW, "overflow"),
                       (sf.FLAG_INVALID, "invalid"),
                       (sf.FLAG_UNDERFLOW, "underflow"),
                       (sf.FLAG_INEXACT, "inexact")):
        check(COVER["flags"] & flag, f"a run raised {word}")


# ---- the committed references ----------------------------------------------

def write_references():
    COMPILED.mkdir(parents=True, exist_ok=True)
    files = compiled_references()
    for p in COMPILED.iterdir():
        if p.name not in files:
            p.unlink()
    for name, data in files.items():
        (COMPILED / name).write_bytes(data)
        print(f"  wrote programs/systems/compiled/{name} ({len(data)} bytes)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--segrun", help="host/cft-segrun, for leg E")
    ap.add_argument("--audit", help="host/cft-audit, for leg E")
    ap.add_argument("--corpus", type=int, default=48,
                    help="generated systems in leg A (default 48)")
    ap.add_argument("--only", default="",
                    help="a comma list of legs: refs,corpus,banks,libcft,"
                         "determinism,refusals,plants")
    ap.add_argument("--write", action="store_true",
                    help="write programs/systems/compiled/ and exit")
    ap.add_argument("--digests", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.digests:
        return digests_main(a.digests)
    if a.write:
        return write_references()
    only = {x for x in a.only.split(",") if x}
    t0 = time.perf_counter()
    work = Path(tempfile.mkdtemp(prefix="lang-check-"))

    def rng(leg):
        # one generator a leg, so that a leg's lanes - and so its counts,
        # a plant's failing lanes among them - are the same whichever
        # other legs ran before it (--only)
        return random.Random(f"lang check {leg}")
    legs = [("refs", lambda: leg_references(rng("refs"))),
            ("corpus", lambda: leg_corpus(a.corpus, rng("corpus"))),
            ("banks", lambda: leg_banks(rng("banks"))),
            ("libcft", lambda: leg_libcft(a.segrun, a.audit, rng("libcft"),
                                          work)),
            ("determinism", lambda: leg_determinism(work)),
            ("refusals", leg_refusals),
            ("plants", lambda: leg_plants(rng("plants"), work))]
    try:
        for name, fn in legs:
            if only and name not in only:
                continue
            t = time.perf_counter()
            fn()
            print(f"  ({name}: {time.perf_counter() - t:.1f} s)")
        if not only or {"refs", "corpus"} <= only:
            leg_coverage()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    dt = time.perf_counter() - t0
    print(f"\nlang_check: {TALLY.ok} ok, {TALLY.bad} FAIL, {TALLY.skip} SKIP "
          f"in {dt:.0f} s")
    for f in FAILURES[:20]:
        print(f"  FAIL  {f}")
    return 1 if TALLY.bad else 0


if __name__ == "__main__":
    sys.exit(main())
