# M4 model: what atan2's in-lane exact-quotient rule decides (scratch; the
# study's 2.5, after send-back 1's item 2). Exact quotients y/x = c 2^-e,
# c in {1, 3, 5, 7}, x > 0 with a random significand whose low three bits
# are zero (so c x is exact), t's exponent uniform where the main path
# cannot decide an exact quotient alone (from -(p + G) to -(p + G)/2, where
# atan(t) lies within the bound of the boundary t). Each lane through the
# unplanted fragment under every attribute: the remainder zero (s_h exact,
# the rule fires) or not (s_h an ulp or more off the exact quotient, the
# rule cannot fire); marked; wrong unmarked against transcend.py.
#
#   python exactq.py FMT N SEED

import random
import sys
import time

from m4core import FORMATS, sf, dec, evaluate2, ATTRS
from m4inv import build, GUARD
from m4harness import golden


def lanes(fmt, n, seed):
    rng = random.Random(seed * 7919 + fmt.width)
    p, G = fmt.prec, GUARD[fmt.name]
    out = []
    for _ in range(n):
        c = rng.choice((1, 3, 5, 7))
        e = rng.randint((p + G + 1) // 2, p + G)
        m = (rng.getrandbits(p - 1) | (1 << (p - 1))) & ~7
        Ex = rng.randint(-20, 20)
        x = sf.round_pack(fmt, 0, m, Ex - p + 1, 0)[0]
        y = sf.round_pack(fmt, 0, c * m, Ex - p + 1 - e, 0)[0]
        assert dec(fmt, y) == dec(fmt, x) * c / 2 ** e
        out.append((y, x))
    return out


def main():
    name, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    fmt = FORMATS[name]
    t0 = time.perf_counter()
    xs = lanes(fmt, n, seed)
    for rnd in ATTRS:
        f = build(fmt, rnd, "atan2")
        fired = off = marked = wrong = off_marked = 0
        for xa in xs:
            b, fw, pr = evaluate2(f, xa, want=["rem0"], full=True)
            zero = dec(fmt, pr["rem0"]) == 0
            fired += zero
            off += not zero
            if fw & 0x80:
                marked += 1
                off_marked += not zero
            elif (b, fw) != tuple(golden(fmt, "atan2", xa, rnd)):
                wrong += 1
        print(f"{name} atan2 {sf.RND_NAMES[rnd]} exact quotients below the main "
              f"path's reach, seed {seed}: {n} lanes; remainder zero (the rule "
              f"fires) {fired}; s_h off the exact quotient {off}, of them marked "
              f"{off_marked}; marked in all {marked}; wrong unmarked {wrong}; "
              f"{time.perf_counter() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
