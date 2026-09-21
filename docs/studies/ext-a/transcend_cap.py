# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""transcend_cap.py - an instrument of docs/studies/EXT-A-wide-ladder.md.

Two facts about the thirty-nine transcendentals above binary256, shown on
the unmodified golden model:

1. THE CAP. transcend.py's Ziv schedule starts at 2p + 40 bits and stops at
   min(8p + 128, PREC_CAP_CEILING), and the ceiling is 832 because the C
   port's 2048-bit container cannot hold more (docs/TRANSCENDENTALS.md).
   At binary512 the FIRST attempt, 1018 bits, is already above it.

2. A PROOF WITH A LADDER IN IT. _pow_dyadic answers "can x**y be a grid
   point or a midpoint?" and returns None as a PROOF that it cannot. One
   branch - `if k > 24: return None` - leans on |E| < 2^24, which holds on
   the ladder that exists (the widest |E| is fp256's 262,378) and at
   binary512 (4,194,790 < 2^23), and fails at binary1024, whose exponents
   reach 2^26: x = 2^(2^25), y = 2^-25 is a representable pair with
   x**y == 2 EXACTLY.

The ceiling is lifted IN THIS PROCESS ONLY, by assigning the module
attribute after import. Nothing on disk changes; the point is to see what
the model does once it is allowed to try.

    python docs/studies/ext-a/transcend_cap.py > docs/studies/ext-a/transcend_cap.out.txt
"""
import pathlib
import sys
import time

# LF on every platform, like the vector sets: a captured run should diff
# clean against a re-run wherever either was made.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(newline="\n")

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden.formats import FpFormat, FP256      # noqa: E402
from cft_golden import softfloat as sf               # noqa: E402
from cft_golden import transcend as tr               # noqa: E402

FP512 = FpFormat("fp512", 23, 488)
FP1024 = FpFormat("fp1024", 27, 996)
ATTR = ((sf.RND_RNE, "RNE"), (sf.RND_RTZ, "RTZ"), (sf.RND_RDN, "RDN"),
        (sf.RND_RUP, "RUP"), (sf.RND_RMM, "RMM"))


def pow2(fmt, n):
    return (n + fmt.bias) << fmt.man_w


def three(fmt):
    return sf.from_int(fmt, 3, sf.RND_RNE)[0]


def show(fmt, tag, fn, *args):
    t0 = time.perf_counter()
    try:
        bits, flags = fn(fmt, *args)
    except tr.ZivEscalation as exc:
        print(f"  {tag:<44} REFUSED  ZivEscalation: {str(exc)[:64]}...", flush=True)
        return None
    ms = (time.perf_counter() - t0) * 1e3
    print(f"  {tag:<44} {hex(bits)[:20]}...  flags={flags:#04x}  ({ms:.0f} ms)", flush=True)
    return bits, flags


print("1. the schedule as shipped (PREC_CAP_CEILING = %d)" % tr.PREC_CAP_CEILING)
for f in (FP256, FP512, FP1024):
    print(f"  {f.name:<7} p={f.prec:<4} start={tr.start_prec(f):<5} cap={tr.prec_cap(f):<5} "
          f"attempts={list(tr._prec_schedule(f))}")
for f in (FP256, FP512, FP1024):
    for name, fn in (("exp", tr.exp), ("log", tr.log), ("atan", tr.atan)):
        show(f, f"{name}(3) @ {f.name}", fn, three(f), sf.RND_RNE)

print("\n2. the same, with the ceiling lifted in this process (1 << 20)")
tr.PREC_CAP_CEILING = 1 << 20
for f in (FP512, FP1024):
    print(f"  {f.name:<7} attempts now begin {list(tr._prec_schedule(f))[:3]}")
    for name, fn in (("exp", tr.exp), ("log", tr.log), ("atan", tr.atan)):
        show(f, f"{name}(3) @ {f.name}", fn, three(f), sf.RND_RNE)

print("\n3. pow(2^(2^25), 2^-25) at binary1024: the true value is 2, exactly, so every")
print("   attribute must deliver 2.0 and raise nothing")
two = pow2(FP1024, 1)
x, y = pow2(FP1024, 1 << 25), pow2(FP1024, -25)
for rnd, name in ATTR:
    r = show(FP1024, f"pow(2^(2^25), 2^-25)  {name}   [k = 25]", tr.pow, x, y, rnd)
    if r is not None:
        print(f"      value is 2.0: {r[0] == two}    inexact raised: {bool(r[1] & sf.FLAG_INEXACT)}")
print("   the same shape INSIDE the proof's envelope, for contrast:")
r = show(FP1024, "pow(2^(2^24), 2^-24)  RNE   [k = 24]", tr.pow, pow2(FP1024, 1 << 24), pow2(FP1024, -24), sf.RND_RNE)
if r is not None:
    print(f"      value is 2.0: {r[0] == two}    inexact raised: {bool(r[1] & sf.FLAG_INEXACT)}")
print("   and at binary512, where |E| < 2^23 and the proof still holds, the widest such pair:")
r = show(FP512, "pow(2^(2^21), 2^-21)  RNE   [k = 21]", tr.pow, pow2(FP512, 1 << 21), pow2(FP512, -21), sf.RND_RNE)
if r is not None:
    print(f"      value is 2.0: {r[0] == pow2(FP512, 1)}    inexact raised: {bool(r[1] & sf.FLAG_INEXACT)}")
