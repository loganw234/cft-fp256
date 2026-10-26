#!/usr/bin/env python3
"""hx_iterates.py - parcel HX: how wide are the values the division and root programs compute on the fp32 slice?
(scratch beside docs/studies/HX-wide-sweeps.md, section 3.1; nothing in the tree imports it).

The slice's INPUTS have 24 significant bits at every rung. The question is whether the program's own values do: the
seed refined by Newton, the quotient and root estimates, the exact residuals. This runs the tree's own program route
(python/cft_golden/seqprogs.py, read only: div_prep, sqrt_prep, the programs, seq.run) on fp32 values widened
exactly to fp128 and fp256, and counts the significant bits (leading one to lowest one) of each deposit the program
returns: the root s1 and the quotient q2, and the residuals r. A deposit of more than 24 significant bits was
computed, not copied; one near the format's precision used the whole datapath.

usage: python3 hx_iterates.py TREE [N]      (N fp32 inputs, default 400; under a minute)
"""
import random
import statistics
import sys


def sigbits(fmt, bits):
    man = bits & ((1 << fmt.man_w) - 1)
    e = (bits >> fmt.man_w) & ((1 << fmt.exp_w) - 1)
    m = man | ((1 << fmt.man_w) if e else 0)
    if m == 0:
        return 0
    return m.bit_length() - ((m & -m).bit_length() - 1)


def main():
    tree = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 400
    sys.path.insert(0, tree + "/python")
    from cft_golden import seq, seqprogs as SP, softfloat as sf
    from cft_golden.formats import FP32, FP128, FP256
    rng = random.Random(20261026)
    xs32 = []
    while len(xs32) < n:
        x = rng.getrandbits(31)                       # positive fp32 encodings, finite and nonzero
        if 0 < x < 0x7F800000:
            xs32.append(x)
    fails = 0
    for fmt in (FP128, FP256):
        xs = [sf.convert(FP32, fmt, x)[0] for x in xs32]
        one = sf.convert(FP32, fmt, 0x3F800000)[0]
        a_l, keep = [], []
        for x in xs:
            special, core = SP.sqrt_prep(fmt, x)
            if special is None:
                a_l.append(core[0])
        res = seq.run(SP.sqrt_program_for(fmt), a_l, [0] * len(a_l))
        s1 = [sigbits(fmt, res.deposits[3 * j]) for j in range(len(a_l))]
        r = [sigbits(fmt, res.deposits[3 * j + 1]) for j in range(len(a_l))]
        ac_l, bc_l = [], []
        for x in xs:
            special, core = SP.div_prep(fmt, one, x)
            if special is None:
                ac_l.append(core[0])
                bc_l.append(core[1])
        res = seq.run(SP.div_program_for(fmt), ac_l, bc_l)
        q2 = [sigbits(fmt, res.deposits[3 * j]) for j in range(len(ac_l))]
        r2 = [sigbits(fmt, res.deposits[3 * j + 1]) for j in range(len(ac_l))]
        inputs = [sigbits(fmt, x) for x in xs]
        print("%s, %d fp32 inputs widened (p = %d): significant bits, min / median / max" % (fmt.name, n, fmt.prec))
        for name, v in (("the inputs", inputs), ("sqrt: the root s1", s1), ("sqrt: the residual r", r),
                        ("1/x: the quotient q2", q2), ("1/x: the remainder r2", r2)):
            print("  %-24s %4d / %6.1f / %4d" % (name, min(v), statistics.median(v), max(v)))
        wide = statistics.median(s1) >= fmt.prec - 8 and statistics.median(q2) >= fmt.prec - 8
        print("CHECK %s: the median root and quotient carry at least p - 8 significant bits: %s"
              % (fmt.name, "ok" if wide else "FAILED"))
        fails += not wide
        narrow = max(inputs) <= 24
        print("CHECK %s: no input carries more than 24 (the slice is what it claims): %s"
              % (fmt.name, "ok" if narrow else "FAILED"))
        fails += not narrow
    print("hx_iterates: %d check(s) failed" % fails)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
