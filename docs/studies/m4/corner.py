# M4 model: atan2's tiny-numerator corner (scratch; the study's 2.5 and 3.6,
# item 9, after send-back 1): m4measure's region "tinyn", a subnormal or
# tiny |y| against x over the whole range above it, through the model and,
# with "seq", as programs on seq.py (routines.run; the triple word
# scheduled as twrun.py does). Each lane against transcend.py, bits and flag
# word: wrong unmarked, marked; and |V - f| / Bv by mpmath at 4p + 200 bits
# on the unmarked lanes whose answer is the main path's (finite nonzero
# operands; a lane whose Bv underflowed to 0 is counted apart, since the
# test then certifies it with no margin). A plant name builds
# that fault instead (prescale-d: the prescale keyed on d, as first
# designed; range-low, the triple word's range at the double word's edge).
#
#   python corner.py FMT N SEED [seq] [PLANT]     (FMT fp32-tw: the triple word)

import sys
import time

import mpmath

from m4core import FORMATS, sf, dec, evaluate2, ATTRS
from m4harness import golden
from m4measure import sample, true_value
from m4inv import build, PLANTS
import m4tw
from cft_golden import mathlib, routines


def main():
    name, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    rest = sys.argv[4:]
    on_seq = "seq" in rest
    plant = next((a for a in rest if a != "seq"), None)
    tw = name == "fp32-tw"
    fmt = FORMATS["fp32" if tw else name]
    if plant:
        assert plant in (m4tw.PLANTS_TW if tw else PLANTS), plant
    t0 = time.perf_counter()
    xs = sample(fmt, "atan2", "tinyn", n, seed)
    mpmath.mp.prec = 4 * fmt.prec + 200
    for rnd in ATTRS:
        f = (m4tw.build if tw else build)(fmt, rnd, "atan2", plant=plant)
        if on_seq:
            frag = f.to_fragment()
            if tw:
                frag = mathlib.permuted(frag, mathlib._dfs_order(frag))
            outs, wds = routines.run(frag, [a for a, _ in xs], [b for _, b in xs])
        wrong = marked = differ = 0
        first = None
        worst, wlane = 0.0, None
        bv0 = 0
        for i, xa in enumerate(xs):
            b, fw, pr = evaluate2(f, xa, want=["Vh", "Vl", "Bv"] + (["V2"] if tw else []),
                                  full=True)
            if on_seq:
                if (outs[i], wds[i]) != (b, fw):
                    differ += 1
                b, fw = outs[i], wds[i]
            gb, gf = golden(fmt, "atan2", xa, rnd)
            if fw & 0x80:
                marked += 1
                continue
            if (b, fw) != (gb, gf):
                wrong += 1
                first = first or xa
            y, x = xa
            if (y & ~fmt.sign_mask) == 0 or rnd != ATTRS[0] or fw != 0x10:
                continue
            Vv = dec(fmt, pr["Vh"]) + dec(fmt, pr["Vl"]) + (dec(fmt, pr["V2"]) if tw else 0)
            Bv = abs(dec(fmt, pr["Bv"]))
            if Bv == 0:
                # the bound itself underflowed: the test then certifies the
                # lane with no margin at all, a broken bound whatever |V - f|
                bv0 += 1
                continue
            r = abs(mpmath.mpf(Vv.numerator) / Vv.denominator
                    - true_value("atan2", xa, fmt)) / (mpmath.mpf(Bv.numerator) / Bv.denominator)
            if float(r) > worst:
                worst, wlane = float(r), xa
        tail = (f"; largest |V - f|/Bv over the unmarked lanes "
                f"2^{float(mpmath.log(worst, 2)) if worst else -999:.2f}"
                f" (at {wlane}); unmarked lanes whose Bv underflowed to 0: {bv0}"
                if rnd == ATTRS[0] else "")
        print(f"{name} atan2 {sf.RND_NAMES[rnd]} corner tinyn seed {seed}"
              f"{' plant ' + plant if plant else ''}{' on seq.py' if on_seq else ''}: "
              f"{len(xs)} lanes, {len(f.body)} instructions: wrong unmarked {wrong}"
              f"{' (first ' + str(first) + ')' if first else ''}, marked {marked}"
              f"{', differ from the model ' + str(differ) if on_seq else ''}{tail}; "
              f"{time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
