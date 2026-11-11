#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""GPU-A part 2: the program corpora, drawn by seq_check.py's own builders.

  gen_programs.py CORPUS_DIR [--formats fp64 fp256] [--golden] [--seed 17]

routines-<fmt>.bin   seq_check.py's routine corpus (its eighth: the six, the
                     trig part and the inverse part), its first round at
                     --seed (seq_check's default, 17), drawn by seq_check's
                     own functions in seq_check's order from seq_check's own
                     streams: the same programs in both shapes, lanes, masks
                     and lane-byte choices that `seq_check.py` holds libcft
                     to the golden model on. b and c are the zero streams
                     seq_check passes (atan2's x in b).
systems.bin          the eight cftc-compiled systems of programs/systems/
                     compiled (images and banks as committed), lanes from a
                     seeded stream of initial states in their scratch blocks,
                     a mask on half of them, the lane bytes on all.
fuzz-<fmt>.bin       the golden model's fuzz programs with every arm on: the
                     control codes the routines do not use (loops, SETACT,
                     ACTALL, the indexed scratch and its post-steps, deposit
                     overflow, strict range reports), --fuzz a format
bench.bin            the rate programs on typical arguments (bench_cases)
refuse.bin           one augmentedAddition program: the runner must refuse
                     it by name.
--golden             also routines-<fmt>.golden, the golden model's output
                     (python/cft_golden/seq.py) in the runner's layout, for
                     every case: a third executor on the same corpus.

The layout of a case, little-endian: "CFTSEQA1", then ten words (format
code, lanes, image bytes, bank bytes, presence bits b=1 c=2 mask=4
lane-bytes=8 scratch-in=16, fill bytes deposit | lane<<8, the count fill,
scratch-in and scratch-out slots a lane, the name's length), the name, the
image, the bank, a, b, c, the mask, the scratch-in block.
"""
import argparse
import hashlib
import random
import struct
import sys
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "host" / "tests"))
sys.path.insert(0, str(ROOT / "python"))

import seq_check as SC  # noqa: E402  seq_check's builders, unchanged
from cft_golden import FORMATS, seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402

CODE = {"fp32": 0, "fp64": 1, "fp128": 2, "fp256": 3}
FILL = SC.ROUTINE_FILL          # (deposit byte, count, lane byte): seq_check's


def case_bytes(name, fmt, image, bank, a, b, c, keep, lf, nsi=0, nso=0, sin=None):
    esz = fmt.width // 8
    n = len(a)
    nm = name.encode()
    present = ((1 if b is not None else 0) | (2 if c is not None else 0) |
               (4 if keep is not None else 0) | (8 if lf else 0) |
               (16 if sin is not None else 0))
    out = [b"CFTSEQA1", struct.pack("<10I", CODE[fmt.name], n, len(image), len(bank),
                                     present, FILL[0] | FILL[2] << 8, FILL[1], nsi, nso,
                                     len(nm)), nm, image, bank]
    for s in (a, b, c):
        if s is not None:
            out.append(b"".join(v.to_bytes(esz, "little") for v in s))
    if keep is not None:
        m = bytearray((n + 7) // 8)
        for i, k in enumerate(keep):
            if k:
                m[i >> 3] |= 1 << (i & 7)
        out.append(bytes(m))
    if sin is not None:
        out.append(b"".join(v.to_bytes(esz, "little") for v in sin))
    return b"".join(out)


def footprint(prog):
    """scratch_used, as program.c's seq_scratch_footprint gives it at 256."""
    used, indexed = 0, False
    for w in prog.insns:
        d = seq.decode(w)
        if d["ctrl"] and d["op"] in (seq.STL, seq.LDL):
            used = max(used, (d["imm"] & 0xFFFFFF) + 1)
        elif d["ctrl"] and d["op"] in (seq.STX, seq.LDX):
            indexed = True
    return 256 if indexed else used


def golden_bytes(prog, image, a, b, c, bank, keep, lf):
    """The golden model's run in the runner's output layout."""
    fmt = prog.fmt
    esz, n, md = fmt.width // 8, len(a), prog.max_deposits
    flags_word = struct.unpack_from("<I", image, 24)[0]
    want = SC.mrun(prog, a, b, c, bank=bank, lane_mask=keep)
    out = [struct.pack("<10I", len(prog.insns), prog.n_consts, md, flags_word, 0, 0,
                       footprint(prog), 0, want.flags, want.status)]
    dep, cnt, lb = [], [], []
    for i in range(n):
        if keep is not None and not keep[i]:
            dep.append(bytes([FILL[0]]) * (md * esz))
            cnt.append(FILL[1])
            lb.append(FILL[2])
            continue
        dep.append(b"".join(want.deposits[i * md + s].to_bytes(esz, "little")
                            for s in range(md)))
        cnt.append(want.counts[i])
        lb.append(want.lane_flags[i])
    out.append(b"".join(dep))
    out.append(struct.pack(f"<{n}I", *cnt))
    if lf:
        out.append(bytes(lb))
    return b"".join(out)


def routine_cases(fmt, seed, golden):
    """seq_check.routine_corpus's first round for one format, every part,
    drawn exactly as it draws: -> [(case bytes, golden bytes or b"")]."""
    ml, har, fam = SC.routine_modules()
    out = []
    for part in ("six", "trig", "inv"):
        if part == "inv" and fmt not in ml.INV_FORMATS:
            continue
        if part == "trig":
            th, tf = SC.trig_modules()
        if part == "inv":
            ih = SC.inv_modules()
        salt = SC.ROUTINE_PART[part][3]
        rng = random.Random((seed * 2654435761 + fmt.width * 40503) & 0xFFFFFFFF ^ salt)
        for fn in SC.routine_part_names(ml, part):
            for rnd in sf.RND_MODES:
                sub = random.Random(rng.getrandbits(64))
                _f, standalone, compiled = SC.routine_programs(fmt, fn, rnd)
                for shape, (prog, bank) in zip(SC.ROUTINE_SHAPES, (standalone, compiled)):
                    n = sub.choice(SC.ROUTINE_NS)
                    if part == "trig":
                        xs, _t = SC.trig_lanes(ml, th, tf, fmt, fn, rnd, n, sub)
                    elif part == "inv":
                        xs, _t = SC.inv_lanes(ml, ih, fmt, fn, rnd, n, sub)
                    else:
                        xs, _t = SC.routine_lanes(ml, har, fam, fmt, fn, rnd, n, sub)
                    keep = None
                    if sub.random() < 1 / 3:
                        keep = [sub.random() < 0.7 for _ in range(n)]
                        if not any(keep):
                            keep[sub.randrange(n)] = True
                    lf = shape == "compiled" or sub.random() < 0.5
                    xs_a, xs_b = SC.routine_operands(xs)
                    zeros = [0] * n
                    b = zeros if xs_b is None else xs_b
                    image = prog.to_bytes()
                    esz = fmt.width // 8
                    kb = b"".join(v.to_bytes(esz, "little") for v in bank)
                    name = f"{fmt.name} {fn} {sf.RND_NAMES[rnd]} {shape} n={n}"
                    cb = case_bytes(name, fmt, image, kb, xs_a, b, zeros, keep, lf)
                    gb = golden_bytes(prog, image, xs_a, b, zeros, bank, keep, lf) \
                        if golden else b""
                    out.append((cb, gb, len(prog.insns)))
    return out


def system_cases(seed):
    """The compiled systems: lanes are initial states in the scratch block."""
    from cft_golden import mathlib as ml
    rng = random.Random(seed ^ 0x53595354)          # "SYST"
    out = []
    for cftp in sorted((ROOT / "programs" / "systems" / "compiled").glob("*.cftp")):
        image = cftp.read_bytes()
        bank = cftp.with_suffix(".bank").read_bytes()
        code = struct.unpack_from("<I", image, 20)[0]
        fmt = FORMATS[["fp32", "fp64", "fp128", "fp256"][code]]
        sio = struct.unpack_from("<I", image, 28)[0]
        nsi, nso = sio & 0xFFFF, sio >> 16
        n = 1024 if fmt.name == "fp64" else 128
        sin = []
        for _ in range(n * nsi):
            v = Fraction(rng.randrange(1 << 20) + (1 << 19), 1 << 20) * rng.choice((1, -1))
            sin.append(ml._enc(fmt, v))
        keep = [rng.random() < 0.7 for _ in range(n)] if len(out) % 2 else None
        name = f"{cftp.stem} n={n}"
        out.append(case_bytes(name, fmt, image, bank, [0] * n, None, None, keep, True,
                              nsi, nso, sin))
    return out


def fuzz_cases(fmt, seed, trials):
    """fuzz-<fmt>.bin: the golden model's own fuzz generator (seq.random_program,
    every arm on: IMUL and kx, 32 registers, the scratch codes, revision 8's
    post-steps, R24's regions and raise) with seq.random_inputs' operands, a
    deposit budget, a scratch block, strict or not, a mask on a third of the
    runs and the lane bytes on half: every instruction class but the two
    augmented halves, whose programs are left out here (refuse.bin holds one).
    -> (cases, programs left out for augmentedAddition)."""
    rng = random.Random(seed ^ (fmt.width * 7919) ^ 0x46555A5A)    # "FUZZ"
    out, aug, ctrl, t = [], 0, {}, 0
    while len(out) < trials and t < 40 * trials:
        t += 1
        # half with revision 8's arm (whose programs mostly carry an augmented
        # half, and are drawn until enough do not), half without it
        rev8 = len(out) % 2 == 0
        insns, consts = seq.random_program(fmt, rng, extended=True, wide_regs=True,
                                           scratch=True, rev8=rev8, flags=True)
        if any(d["ctrl"] and d["op"] in (seq.AUGADD, seq.AUGERR)
               for d in map(seq.decode, insns)):
            aug += 1
            continue
        for d in map(seq.decode, insns):
            if d["ctrl"]:
                k = seq.CTRL_NAMES.get(d["op"], d["op"])
                ctrl[k] = ctrl.get(k, 0) + 1
        nsin, nsout = rng.choice([0, 1, 3]), rng.choice([0, 1, 4])
        pflags = ((seq.FLAG_SCRATCH_IO if nsin or nsout else 0) |
                  (seq.FLAG_SCRATCH_STRICT if rng.random() < 0.4 else 0))
        maxdep = rng.choice([0, 1, 2, 4])
        try:
            prog = seq.Program(fmt, insns, consts, max_deposits=maxdep, flags=pflags,
                               n_scratch_in=nsin, n_scratch_out=nsout)
        except seq.ProgramError:
            continue
        n = rng.choice((1, 2, 31, 64, 65, 100, 129))
        a, b, c = (seq.random_inputs(fmt, rng, n) for _ in range(3))
        sin = seq.random_inputs(fmt, rng, n * nsin) if nsin else None
        keep = None
        if rng.random() < 1 / 3:
            keep = [rng.random() < 0.7 for _ in range(n)]
        out.append(case_bytes(f"{fmt.name} fuzz {t} n={n}", fmt, prog.to_bytes(), b"", a, b,
                              c, keep, rng.random() < 0.5, nsin, nsout, sin))
    return out, aug, ctrl


BENCH = (("exp", 20), ("sin", 100), ("atan", 20))    # routine, |argument| bound


def bench_cases(seed):
    """bench.bin: the rate programs on typical arguments, as against the
    corpus's hard cases: exp, sin and atan, rne, the stand-alone shape, at
    fp64 then fp256 (cases 0 to 5), 4,096 lanes each, uniform in [-B, B]
    with 52 random fraction bits (rounded to the format), no specials, no
    mask, no lane bytes."""
    from cft_golden import mathlib as ml
    rng = random.Random(seed ^ 0x42454E43)          # "BENC"
    out = []
    for name in ("fp64", "fp256"):
        fmt = FORMATS[name]
        for fn, bound in BENCH:
            _f, (prog, bank), _c = SC.routine_programs(fmt, fn, sf.RND_RNE)
            xs = [ml._enc(fmt, Fraction(rng.randrange(-bound << 52, bound << 52), 1 << 52))
                  for _ in range(4096)]
            esz = fmt.width // 8
            kb = b"".join(v.to_bytes(esz, "little") for v in bank)
            out.append(case_bytes(f"{name} {fn} rne stand-alone typical n=4096", fmt,
                                  prog.to_bytes(), kb, xs, [0] * 4096, [0] * 4096, None,
                                  False))
    return out


def census(formats):
    """What the routine fragments are made of, from the programs themselves:
    every control code any of them uses, and for each routine the length
    and the operation counts of its two shapes (the five attributes')."""
    ml = SC.routine_modules()[0]
    names = {v: k for k, v in vars(sf).items() if k.startswith("OP_") and isinstance(v, int)}
    for name in formats:
        fmt, ctrl, rows = FORMATS[name], {}, []
        for part in ("six", "trig", "inv"):
            if part == "inv" and fmt not in ml.INV_FORMATS:
                continue
            for fn in SC.routine_part_names(ml, part):
                lens, ops = {}, {}
                for rnd in sf.RND_MODES:
                    _f, st, co = SC.routine_programs(fmt, fn, rnd)
                    for shape, (prog, _b) in zip(SC.ROUTINE_SHAPES, (st, co)):
                        lens.setdefault(shape, set()).add(len(prog.insns))
                        for w in prog.insns:
                            d = seq.decode(w)
                            key = (seq.CTRL_NAMES.get(d["op"], d["op"]) if d["ctrl"]
                                   else names.get(d["op"], d["op"]))
                            if d["ctrl"]:
                                ctrl[key] = ctrl.get(key, 0) + 1
                            elif shape == "stand-alone" and rnd == sf.RND_RNE:
                                ops[key] = ops.get(key, 0) + 1
                rows.append(f"  {fn}: stand-alone {sorted(lens['stand-alone'])}, compiled "
                            f"{sorted(lens['compiled'])} instructions; rne stand-alone ALU "
                            + ", ".join(f"{k} {v}" for k, v in
                                        sorted(ops.items(), key=lambda t: -t[1])))
        print(f"census {name}: control codes over every fragment, both shapes, five "
              f"attributes: " + ", ".join(f"{k} {v}" for k, v in sorted(ctrl.items())))
        print("\n".join(rows))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--formats", nargs="+", default=["fp64", "fp256"])
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--golden", action="store_true")
    ap.add_argument("--fuzz", type=int, default=200, help="fuzz programs a format")
    ap.add_argument("--census", action="store_true",
                    help="print what the fragments are made of, and write nothing")
    a = ap.parse_args()
    if SC.routine_modules() is None:
        sys.exit("gen_programs: the routine corpus needs mpmath and pytest")
    if a.census:
        census(a.formats)
        return
    a.out.mkdir(parents=True, exist_ok=True)
    for name in a.formats:
        cs, aug, ctrl = fuzz_cases(FORMATS[name], a.seed, a.fuzz)
        blob = b"".join(cs)
        (a.out / f"fuzz-{name}.bin").write_bytes(blob)
        print(f"fuzz-{name}.bin: {len(cs)} cases ({aug} drawn with an augmented half, left "
              f"out), sha256 {hashlib.sha256(blob).hexdigest()}; control codes: "
              + ", ".join(f"{k} {v}" for k, v in sorted(ctrl.items())))
    for name in a.formats:
        t0 = time.time()
        cs = routine_cases(FORMATS[name], a.seed, a.golden)
        blob = b"".join(c for c, _g, _n in cs)
        (a.out / f"routines-{name}.bin").write_bytes(blob)
        line = (f"routines-{name}.bin: {len(cs)} cases, sha256 "
                f"{hashlib.sha256(blob).hexdigest()}")
        if a.golden:
            gold = b"".join(g for _c, g, _n in cs)
            (a.out / f"routines-{name}.golden").write_bytes(gold)
            line += f"; golden output sha256 {hashlib.sha256(gold).hexdigest()}"
        print(f"{line} ({time.time() - t0:.0f} s)")
    blob = b"".join(system_cases(a.seed))
    (a.out / "systems.bin").write_bytes(blob)
    print(f"systems.bin: sha256 {hashlib.sha256(blob).hexdigest()}")
    blob = b"".join(bench_cases(a.seed))
    (a.out / "bench.bin").write_bytes(blob)
    print(f"bench.bin: sha256 {hashlib.sha256(blob).hexdigest()}")
    f64 = FORMATS["fp64"]
    prog = seq.Program(f64, [seq.augadd(3, 0, 1), seq.deposit(3), seq.halt()], max_deposits=1)
    blob = case_bytes("fp64 augadd", f64, prog.to_bytes(), b"", [1, 2], [3, 4], None, None,
                      False)
    (a.out / "refuse.bin").write_bytes(blob)
    print(f"refuse.bin: sha256 {hashlib.sha256(blob).hexdigest()}")


if __name__ == "__main__":
    main()
