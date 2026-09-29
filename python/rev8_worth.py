# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""What revision 8's two asks are worth, counted (docs/SEQUENCER.md,
"Revision 8 (proposed, 2026-09-29)", "What each is worth").

    python python/rev8_worth.py            # the tables
    python python/rev8_worth.py --check    # and exit nonzero on any mismatch

Two kernels, the ones the asks are for, each written with and without
the new instructions, run through the golden model and priced in the
census's own terms (docs/VALIDATION.md, controlled divergence steps 0 and
1a: per lane per step, t = a*ALU + s*SCR + e):

  ALU   an arithmetic instruction: 1, the unit. augadd and augerr are
        arithmetic and cost 1 each.
  SCR   a scratch access (STL, LDL, STX, LDX): s = 5.21 at fp64 and 5.08
        at fp256 on the card today; R18 (revision 7, parcel P1) changes
        it, and P1 measures by how much.
  e     a loop iteration's own cost, its ENDREP, which the census does
        not count as an instruction: 3.07 ns at fp64 against a = 1.72 ns
        (1.78 ALU), 2.93 ns at fp256 against a = 7.18 ns (0.41 ALU).
  p     what one POST-STEP costs beside its access. The census has no
        price for it, because no tile has one: a stepped LDX writes two
        registers and the register file has one write port. p = 0 is a
        step whose write rides a cycle the port is idle; p = 1 is a step
        that needs a write cycle of its own - an IADD's. Both are shown.

Every variant of a kernel is held BIT FOR BIT to a direct computation of
the same arithmetic in the same order, and the Cauchy variants to each
other; the instruction counts come from walking each program's control
flow and are held to seq.run's own count of instructions executed. So
the tables below are counts, not estimates - what they do not include is
said beside them.
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cft_golden import FORMATS, augmented  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from cft_golden import seq  # noqa: E402

# The census (docs/VALIDATION.md, 2026-09-25, "The census"), in ALU units.
CENSUS = {"fp64": dict(s=5.21, e=3.07 / 1.72),
          "fp256": dict(s=5.08, e=2.93 / 7.18)}

SCRATCH_CODES = (seq.STL, seq.LDL, seq.STX, seq.LDX)
AUG_CODES = (seq.AUGADD, seq.AUGERR)


# ---- counting ------------------------------------------------------------

def count(prog):
    """Instructions executed by one lane, by category, for a program
    whose every lane stays active (so the early exit never fires): the
    control flow of seq.run, walked without the arithmetic.

    Returns a dict: alu, aug, scr, steps (stepped accesses), endrep
    (loop iterations), repeat, other (deposit, halt, setact, actall),
    total - the last to be held against seq.run's insns_executed."""
    c = dict(alu=0, aug=0, scr=0, steps=0, endrep=0, repeat=0, other=0)
    pc, stack = 0, []
    while pc < len(prog.insns):
        d = seq.decode(prog.insns[pc])
        if not d["ctrl"]:
            c["alu"] += 1
        elif d["op"] in AUG_CODES:
            c["aug"] += 1
        elif d["op"] in SCRATCH_CODES:
            c["scr"] += 1
            c["steps"] += bool(seq.index_step(d))
        elif d["op"] == seq.REPEAT:
            c["repeat"] += 1
            stack.append([pc + 1, d["imm"]])
        elif d["op"] == seq.ENDREP:
            c["endrep"] += 1
            stack[-1][1] -= 1
            if stack[-1][1] > 0:
                pc = stack[-1][0]
                continue
            stack.pop()
        elif d["op"] == seq.HALT:
            c["other"] += 1
            break
        else:
            c["other"] += 1
        pc += 1
    # `steps` is a count WITHIN scr, not beside it
    c["total"] = (c["alu"] + c["aug"] + c["scr"] + c["endrep"]
                  + c["repeat"] + c["other"])
    return c


def price(c, s, e, p):
    """The census's price of one lane's run: ALU and the pair at 1, a
    scratch access at s, a loop iteration at e, a post-step at p."""
    return c["alu"] + c["aug"] + s * c["scr"] + e * c["endrep"] + \
        p * c["steps"]


# ---- kernel 1: a Taylor coefficient as a Cauchy product -------------------
#
# c_n = sum_{j=0}^{n} a_j * b_(n-j) for every n = 0..N: the coefficients of
# the product of two truncated series, as a Taylor engine computes one
# product term of its recurrence. The series live in the scratch - a_j at
# slot A + j, b_j at slot B + j - and c_n is stored at slot C + n. REPEAT
# takes an immediate trip count, so the looped forms unroll the outer n
# (N + 1 copies of a small block) and loop over j.
#
#   looped, today's ISA   per term: LDX, LDX, FMA, IADD, ISUB
#   looped, revision 8    per term: LDX +1, LDX -1, FMA
#   unrolled, today's ISA per term: LDL, LDL, FMA (static slots)

A, B, C = 0, 72, 144


def _ints(fmt, values):
    return [v & ((1 << fmt.width) - 1) for v in values]


def cauchy_program(fmt, N, form):
    consts = [sf.zero_bits(fmt), 1]          # +0, and the integer 1
    insns = []
    for n in range(N + 1):
        if form == "unrolled":
            insns.append(seq.alu(sf.OP_IXOR, 12, 12, 12))       # acc := +0
            for j in range(n + 1):
                insns += [seq.ldl(13, A + j), seq.ldl(14, B + n - j),
                          seq.alu(sf.OP_FMA, 12, 13, 14, 12)]
            insns.append(seq.stl(12, C + n))
            continue
        consts += [A, B + n]
        ka, kb = len(consts) - 2, len(consts) - 1
        insns += [seq.alu(sf.OP_IOR, 10, ka, ka, ka=True, kb=True, kx=True),
                  seq.alu(sf.OP_IOR, 11, kb, kb, ka=True, kb=True, kx=True),
                  seq.alu(sf.OP_IXOR, 12, 12, 12),
                  seq.repeat(n + 1)]
        if form == "stepped":
            insns += [seq.ldx(13, 10, +1), seq.ldx(14, 11, -1),
                      seq.alu(sf.OP_FMA, 12, 13, 14, 12)]
        else:
            insns += [seq.ldx(13, 10), seq.ldx(14, 11),
                      seq.alu(sf.OP_FMA, 12, 13, 14, 12),
                      seq.alu(sf.OP_IADD, 10, 10, 1, kb=True),
                      seq.alu(sf.OP_ISUB, 11, 11, 1, kb=True)]
        insns += [seq.endrep(), seq.stl(12, C + n)]
    insns.append(seq.halt())
    return seq.Program(fmt, insns, _ints(fmt, consts), max_deposits=0,
                       flags=seq.FLAG_SCRATCH_IO, n_scratch_in=C,
                       n_scratch_out=C + N + 1)


def cauchy_reference(fmt, a, b):
    """The same sums, in the same order, with the model's FMA."""
    out = []
    for n in range(len(a)):
        acc = sf.zero_bits(fmt)
        for j in range(n + 1):
            acc, _ = sf.fma(fmt, a[j], b[n - j], acc)
        out.append(acc)
    return out


def _series(fmt, rng, k):
    return [sf.round_pack(fmt, rng.getrandbits(1),
                          rng.getrandbits(min(fmt.prec, 40)) | 1,
                          -min(fmt.prec, 40) - rng.randrange(0, 4))[0]
            for _ in range(k)]


def run_cauchy(fmt, N, lanes=3, seed=5):
    """-> {form: (counts, words)}, after holding every form to the
    reference and to each other, lane by lane."""
    rng = random.Random(seed ^ fmt.width ^ N)
    blocks, refs = [], []
    for _ in range(lanes):
        a, b = _series(fmt, rng, N + 1), _series(fmt, rng, N + 1)
        blk = [sf.zero_bits(fmt)] * C
        blk[A:A + N + 1], blk[B:B + N + 1] = a, b
        blocks += blk
        refs.append(cauchy_reference(fmt, a, b))
    out = {}
    for form in ("looped", "stepped", "unrolled"):
        prog = cauchy_program(fmt, N, form)
        res = seq.run(prog, [0] * lanes, [0] * lanes, scratch_in=blocks)
        width = C + N + 1
        for i in range(lanes):
            got = res.scratch_out[i * width + C: i * width + C + N + 1]
            if got != refs[i]:
                raise AssertionError(f"cauchy {fmt.name} N={N} {form} lane "
                                     f"{i} differs from the reference")
        c = count(prog)
        if c["total"] != res.insns_executed:
            raise AssertionError(f"cauchy {form}: counted {c['total']}, "
                                 f"seq.run executed {res.insns_executed}")
        out[form] = (c, len(prog.insns))
    return out


# ---- kernel 2: a compensated step -----------------------------------------
#
# K steps of x := x + h*f(x) with the rounding error of each addition
# carried to the next, on f(x) = x (so the increment is one FMA and the
# step is all compensation). The state x, the compensation c and h live
# in registers r0, r2 and r1; the loop body is one step:
#
#   kahan     y = h*x + c; t = x + y; z = t - x; c = y - z; x := t
#             Fast2Sum's error: exact only when |x| >= |y| in exponent
#   twosum    y = h*x + c; s = x + y; bp = s - x; ap = s - bp;
#             db = y - bp; da = x - ap; c = da + db; x := s
#             Knuth's TwoSum: exact for every order, six additions
#   augmented y = h*x + c; c = augerr(x, y); x = augadd(x, y)
#             754-2019 augmentedAddition: exact for every order, and in
#             place - no temporary, no copy
#
# The copy (x := t, an IOR) is what a REPEAT body pays to keep x in one
# register; unrolling by two renames it away and doubles the body. Both
# are shown. The three forms do NOT compute the same bits: RNE and
# roundTiesTowardZero part at ties, and Fast2Sum's error is exact only
# under its precondition - each is held to its own reference.

def comp_program(fmt, K, form):
    insns = [seq.repeat(K)]
    if form == "kahan":
        insns += [seq.alu(sf.OP_FMA, 3, 1, 0, 2),            # y
                  seq.alu(sf.OP_ADD, 4, 0, rc=3),            # t = x + y
                  seq.alu(sf.OP_SUB, 5, 4, rc=0),            # z = t - x
                  seq.alu(sf.OP_SUB, 2, 3, rc=5),            # c = y - z
                  seq.alu(sf.OP_IOR, 0, 4, 4)]               # x := t
    elif form == "twosum":
        insns += [seq.alu(sf.OP_FMA, 3, 1, 0, 2),            # y
                  seq.alu(sf.OP_ADD, 4, 0, rc=3),            # s = x + y
                  seq.alu(sf.OP_SUB, 5, 4, rc=0),            # bp = s - x
                  seq.alu(sf.OP_SUB, 6, 4, rc=5),            # ap = s - bp
                  seq.alu(sf.OP_SUB, 7, 3, rc=5),            # db = y - bp
                  seq.alu(sf.OP_SUB, 8, 0, rc=6),            # da = x - ap
                  seq.alu(sf.OP_ADD, 2, 8, rc=7),            # c = da + db
                  seq.alu(sf.OP_IOR, 0, 4, 4)]               # x := s
    else:
        insns += [seq.alu(sf.OP_FMA, 3, 1, 0, 2),            # y
                  seq.augerr(2, 0, 3),                       # c
                  seq.augadd(0, 0, 3)]                       # x
    insns += [seq.endrep(), seq.deposit(0), seq.deposit(2), seq.halt()]
    return seq.Program(fmt, insns, max_deposits=2)


def comp_reference(fmt, form, x, h, K):
    c = sf.zero_bits(fmt)
    add = lambda p, q: sf.add(fmt, p, q)[0]            # noqa: E731
    sub = lambda p, q: sf.sub(fmt, p, q)[0]            # noqa: E731
    for _ in range(K):
        y = sf.fma(fmt, h, x, c)[0]
        if form == "kahan":
            t = add(x, y)
            c = sub(y, sub(t, x))
            x = t
        elif form == "twosum":
            s = add(x, y)
            bp = sub(s, x)
            ap = sub(s, bp)
            c = add(sub(x, ap), sub(y, bp))
            x = s
        else:
            x, c, _ = augmented.augmented_add(fmt, x, y)
    return x, c


def run_comp(fmt, K=64, lanes=8, seed=11):
    """-> {form: (counts, words)}, each form held to its own reference."""
    rng = random.Random(seed ^ fmt.width)
    xs = [sf.round_pack(fmt, 0, rng.getrandbits(30) | 1 << 30, -30)[0]
          for _ in range(lanes)]
    hs = [sf.round_pack(fmt, 0, rng.getrandbits(20) | 1, -40)[0]
          for _ in range(lanes)]
    out = {}
    for form in ("kahan", "twosum", "augmented"):
        prog = comp_program(fmt, K, form)
        res = seq.run(prog, xs, hs, [sf.zero_bits(fmt)] * lanes)
        for i in range(lanes):
            want = comp_reference(fmt, form, xs[i], hs[i], K)
            if tuple(res.deposits[2 * i: 2 * i + 2]) != want:
                raise AssertionError(f"compensated {fmt.name} {form} lane "
                                     f"{i} differs from its reference")
        c = count(prog)
        if c["total"] != res.insns_executed:
            raise AssertionError(f"compensated {form}: counted "
                                 f"{c['total']}, seq.run executed "
                                 f"{res.insns_executed}")
        out[form] = (c, len(prog.insns))
    return out


# ---- the tables -------------------------------------------------------------

def report(check=False):
    lines = [
        "Per Cauchy term, in the census's units (s a scratch access, e a",
        "loop iteration, p a post-step): looped 3 + 2s + e; stepped",
        "1 + 2s + e + 2p; unrolled 1 + 2s, and O(N^2) instruction words.",
        "Per compensated step: kahan 5 (4 unrolled by two), twosum 8 (7),",
        "augmented 3, each + e. Plug in R18's s where P1 measures it.",
        ""]
    for fname in ("fp64", "fp256"):
        fmt = FORMATS[fname]
        s, e = CENSUS[fname]["s"], CENSUS[fname]["e"]
        lines.append(f"== {fname}: s = {s:.2f}, e = {e:.2f} ALU "
                     f"(the census); p = post-step price ==")
        for N in (30, 64):
            res = run_cauchy(fmt, N)
            terms = (N + 1) * (N + 2) // 2
            lines.append(f"-- Cauchy products, every c_n for n = 0..{N} "
                         f"({terms} terms), one lane --")
            lines.append(f"   {'form':9} {'words':>6} {'ALU':>6} "
                         f"{'SCR':>6} {'steps':>6} {'loops':>6}  "
                         f"{'price p=0':>10} {'p=1':>10}")
            for form in ("looped", "stepped", "unrolled"):
                c, words = res[form]
                lines.append(
                    f"   {form:9} {words:6d} {c['alu']:6d} {c['scr']:6d} "
                    f"{c['steps']:6d} {c['endrep']:6d}  "
                    f"{price(c, s, e, 0):10.1f} {price(c, s, e, 1):10.1f}")
            lo, st = res["looped"][0], res["stepped"][0]
            per = (price(lo, s, e, 0) - price(st, s, e, 0)) / terms
            lines.append(f"   stepped against looped: {per:.2f} ALU a term "
                         f"saved at p = 0 "
                         f"({100 * (1 - price(st, s, e, 0) / price(lo, s, e, 0)):.1f}%), "
                         f"{(price(lo, s, e, 1) - price(st, s, e, 1)) / terms:.2f} "
                         f"at p = 1")
        res = run_comp(fmt)
        K = 64
        lines.append(f"-- compensated step, {K} steps, one lane --")
        lines.append(f"   {'form':9} {'words':>6} {'ALU':>6} {'aug':>6} "
                     f"{'loops':>6}  {'a step':>7} {'renamed':>8}")
        for form in ("kahan", "twosum", "augmented"):
            c, words = res[form]
            step = (c["alu"] + c["aug"]) / K
            renamed = step - (1 if form != "augmented" else 0)
            lines.append(f"   {form:9} {words:6d} {c['alu']:6d} "
                         f"{c['aug']:6d} {c['endrep']:6d}  {step:7.1f} "
                         f"{renamed:8.1f}")
    text = "\n".join(lines)
    print(text)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit nonzero if any kernel disagrees with its "
                         "reference (the tables are printed either way)")
    ap.parse_args()
    try:
        report()
    except AssertionError as exc:
        print(f"MISMATCH: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
