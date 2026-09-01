# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
#
# Order-of-magnitude context for docs/BENCHMARKS.md: what does the
# Python route to high precision cost? mpmath is the library a Python
# user reaches for at fp128/fp256 precisions, and the golden model's
# own cross-check oracle, so its price belongs next to the C table -
# but as CONTEXT, not as a row of it. This script does not share the C
# benchmark's operand stream or its bit-agreement check (mpmath does
# not implement IEEE binary interchange formats: no subnormals, no
# format exponent range, no signed-zero discipline at these ops'
# edges), so its numbers are comparable in shape, not in rigor.
#
#   python3 host/tools/bench_mpmath.py
#
# Operands mirror the C tool's philosophy: normal-range values with
# full-precision significands, exponents within +/-8 of unity, seeded
# and identical on every run. No fma row: mpmath has no fused
# multiply-add.

import random
import time

import mpmath
from mpmath import mp, mpf

PRECS = [("fp32-equiv", 24), ("fp64-equiv", 53),
         ("fp128-equiv", 113), ("fp256-equiv", 237)]
N = 4096
TARGET_S = 0.35


def operands(prec, n, seed=0x243F6A88):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        # full-precision significand in [1, 2), assembled from random
        # bits so every limb participates, then a small power of two
        m = mpf(1) + mpf(rng.getrandbits(prec)) / mpf(2) ** prec
        e = rng.randint(-8, 8)
        s = -1 if rng.getrandbits(1) else 1
        out.append(s * m * mpf(2) ** e)
    return out


def timed(fn, n):
    fn()  # warm
    reps = 1
    while True:
        t0 = time.perf_counter()
        for _ in range(reps):
            fn()
        dt = time.perf_counter() - t0
        if dt >= TARGET_S or reps >= 1 << 20:
            break
        reps = max(reps + 1, int(reps * min(64.0, TARGET_S / dt * 1.25)))
    return dt * 1e9 / (n * reps)


def main():
    print(f"bench-mpmath: mpmath {mpmath.__version__}, "
          f"{mpmath.libmp.BACKEND} backend, "
          f"{N} elements per pass, >={TARGET_S}s per measurement")
    print(f"{'prec':<12} {'op':<6} {'ns/elem':>12} {'Melem/s':>12}")
    for name, prec in PRECS:
        mp.prec = prec
        a = operands(prec, N, seed=1)
        b = operands(prec, N, seed=2)
        c = operands(prec, N, seed=3)
        ap = [abs(v) for v in a]
        ops = [
            ("add", lambda: [x + y for x, y in zip(a, c)]),
            ("mul", lambda: [x * y for x, y in zip(a, b)]),
            ("div", lambda: [x / y for x, y in zip(a, b)]),
            ("sqrt", lambda: [x.sqrt() for x in ap]),
        ]
        for opname, fn in ops:
            ns = timed(fn, N)
            print(f"{name:<12} {opname:<6} {ns:>12.1f} {1e3 / ns:>12.3f}")


if __name__ == "__main__":
    main()
