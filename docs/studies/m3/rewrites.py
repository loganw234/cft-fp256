# M3 model: the compiler rewrites of a constant exponent (scratch; the
# study's section 6, question 4). Each candidate is an existing operation
# that must equal transcend.py in bits AND flags on every lane: MUL, the
# tile's own (it reads a and b; ADD reads a and c: asm.OP_FIELDS); C4's division and square root by softfloat's div and sqrt
# (their definitions, which C4's routines equal); ADD. MEASURED over every
# x of the pools (pow's x values and the integer cases' operands) at one
# format, every attribute. A rewrite with a lane that differs is not one.
#
#   python rewrites.py FMT

import sys

from m3core import FORMATS, ATTRS, AN, sf, tr, golden
import m3harness as H


def xs_of(fmt):
    s = {x for x, _ in H.pool(fmt, "pow")}
    s |= {x for x, _ in H.pool(fmt, "pown")}
    return sorted(s)


def main():
    fmt = FORMATS[sys.argv[1]]
    one = sf.one_bits(fmt)
    xs = xs_of(fmt)
    two = sf.round_pack(fmt, 0, 2, 0, 0)[0]
    mone = sf.one_bits(fmt, 1)
    cands = [
        ("pow(a, 2) -> a * a", "pow", two,
         lambda a, r: sf.compute(fmt, sf.OP_MUL, a, a, 0, r)),
        ("pow(a, 1) -> a * 1", "pow", one,
         lambda a, r: sf.compute(fmt, sf.OP_MUL, a, one, 0, r)),
        ("pow(a, -1) -> 1 / a", "pow", mone,
         lambda a, r: sf.div(fmt, one, a, r)),
        ("pown(a, 2) -> a * a", "pown", 2,
         lambda a, r: sf.compute(fmt, sf.OP_MUL, a, a, 0, r)),
        ("pown(a, 1) -> a * 1", "pown", 1,
         lambda a, r: sf.compute(fmt, sf.OP_MUL, a, one, 0, r)),
        ("pown(a, -1) -> 1 / a", "pown", -1,
         lambda a, r: sf.div(fmt, one, a, r)),
        ("rootn(a, 1) -> a * 1", "rootn", 1,
         lambda a, r: sf.compute(fmt, sf.OP_MUL, a, one, 0, r)),
        ("rootn(a, -1) -> 1 / a", "rootn", -1,
         lambda a, r: sf.div(fmt, one, a, r)),
        ("rootn(a, 2) -> sqrt(a)  (NOT proposed: -0)", "rootn", 2,
         lambda a, r: sf.sqrt(fmt, a, r)),
        ("compound(a, 1) -> 1 + a  (NOT proposed: -1 under rdn)",
         "compound", 1,
         lambda a, r: sf.compute(fmt, sf.OP_ADD, one, 0, a, r)),
        ("pow(a, 0.5) -> sqrt(a)  (NOT proposed: -0, -inf)", "pow",
         sf.round_pack(fmt, 0, 1, -1, 0)[0],
         lambda a, r: sf.sqrt(fmt, a, r)),
    ]
    for name, fn, b2, op in cands:
        diff = []
        for rnd in ATTRS:
            for a in xs:
                want = golden(fmt, fn, (a, b2), rnd)
                got = op(a, rnd)
                if tuple(got) != tuple(want):
                    diff.append((AN[rnd], a, got, want))
        print(f"{fmt.name} {name}: {len(xs)} x values x 5 attributes, "
              f"{len(diff)} differing", flush=True)
        for rn, a, got, want in diff[:4]:
            print(f"    {rn} x={a:#x}: rewrite ({got[0]:#x}, {got[1]:#x}) "
                  f"transcend ({want[0]:#x}, {want[1]:#x})")


if __name__ == "__main__":
    main()
