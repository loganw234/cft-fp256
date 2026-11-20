#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The fixed tier's golden referee (round 3's G3A): a corpus of the fp256
FMA's hard classes, every expected (bits, flags) from python/cft_golden -
the authority, never the generic kernel - in study GPU-A's corpus layout,
so that hip-corpus runs it on any device (either tier, staged or resident)
and the sha256 of its output equals the corpus's expected tail.

    python -B host/tests/fma_edge_corpus.py OUT [--count N] [--seed S] [--jobs J]

writes OUT/edge-fp256.bin (never into the tree) and OUT/edge-fp256.expect,
the sha256 of the expected d || flags. Five classes, a fifth of the cases
each, every class at all five attributes in equal shares, random signs -
the four GPU-A's stream does not aim at (docs/studies/GPU-A-hip.md,
section 6, "a known limit of the generator") and the alignment edges:

  1 cancellation near EMIN: c = -(a*b rounded by the model under the
    case's attribute), the product within 12 binades of the subnormal
    boundary, a few ulps off, a quarter with short significands (exact);
  2 cancellation near EMAX, the same within 10 binades of the top;
  3 c at the normal boundary: the smallest normal a few ulps up, or the
    largest subnormal a few ulps down, against products at the same scale
    (within 4 binades) and at far ones (within 600);
  4 overflow by a rounding carry: a's significand all ones in its top 200
    to 236 bits, b a power of two (or one a little above it) putting the
    product in the largest binade or the one below, c near half an ulp of
    that binade, below, at and above it (a third of them powers of two);
  5 the alignment edges: c above the product's lead by 33 to 41 binades
    (where the fixed window's sticky first arises: 37 for a 474-bit
    product, 38 for a 473-bit one), below it by 270 to 278 (c's own, 274),
    and either way by 474 to 482 (softfloat.c's FAR = 2p + 4 = 478).

The layout (gen_corpus.py's): b"CFTGPUA1", u32 format code 3, u32 element
bytes 32, u64 n; a, b, c (n elements each, little-endian), the attributes
(n bytes), the expected d (n elements) and flags (n bytes). Default count
750,000, past the 747,560 of VGPU-A's own (unpublished) corpus of these
classes.
"""
import argparse
import concurrent.futures
import hashlib
import random
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAGIC = b"CFTGPUA1"
RNDS = ("rne", "rtz", "rdn", "rup", "rmm")
CLASSES = ("cancellation near EMIN", "cancellation near EMAX", "c at the normal boundary",
           "overflow by a rounding carry", "the alignment edges")
BIAS, EMIN, EMAX, MW, TOP = 262143, -262142, 262143, 236, 0x7FFFF
FRAC = (1 << MW) - 1


def golden():
    sys.path.insert(0, str(ROOT / "python"))
    from cft_golden import FORMATS, softfloat
    return FORMATS["fp256"], softfloat


def enc(sign, ef, frac):
    return (sign << 255) | (ef << MW) | (frac & FRAC)


def ef_of(e):
    """the biased field of an unbiased exponent, clamped to a finite one"""
    return max(0, min(TOP - 1, e + BIAS))


def cancel(R, fmt, sf, a, b, rnd):
    """c = -(a*b rounded), a few ulps off half the time"""
    p, _ = sf.fma(fmt, a, b, 0, rnd)
    c = p ^ (1 << 255)
    if R.random() < 0.5:
        c = max(0, min((1 << 256) - 1, c + R.randint(-2, 2)))
    return c


def case(R, fmt, sf, cls, rnd):
    sa, sb, sc = R.getrandbits(1), R.getrandbits(1), R.getrandbits(1)
    fa, fb, fc = R.getrandbits(MW), R.getrandbits(MW), R.getrandbits(MW)
    if cls in (0, 1):
        t = EMIN + R.randint(-12, 12) if cls == 0 else EMAX + R.randint(-10, 1)
        ea = R.randint(-262000, -20) if cls == 0 else R.randint(20, 262000)
        if R.random() < 0.25:                       # short significands: a*b exact
            fa &= ~((1 << 128) - 1)
            fb &= ~((1 << 128) - 1)
        a, b = enc(sa, ef_of(ea), fa), enc(sb, ef_of(t - ea), fb)
        return a, b, cancel(R, fmt, sf, a, b, rnd)
    if cls == 2:
        ulps = R.randint(0, 3)
        c = enc(sc, 1, ulps) if R.getrandbits(1) else enc(sc, 0, FRAC - ulps)
        t = EMIN + (R.randint(-4, 4) if R.getrandbits(1) else R.randint(-600, 600))
        ea = t // 2
        return enc(sa, ef_of(ea), fa), enc(sb, ef_of(t - ea), fb), c
    if cls == 3:
        top = EMAX - R.getrandbits(1)
        x = R.randint(-100000, 100000)
        ones = R.randint(200, 236)
        fa |= FRAC ^ ((1 << (MW - ones)) - 1)       # the top `ones` bits of the fraction
        fb = R.getrandbits(16) if R.getrandbits(1) else 0
        fc = 0 if R.randint(0, 2) == 0 else fc
        return (enc(sa, ef_of(x), fa), enc(sb, ef_of(top - x), fb),
                enc(sc, ef_of(top - 239 + R.randint(0, 4)), fc))
    kind = R.randint(0, 3)
    g = (R.randint(33, 41), -R.randint(270, 278), R.randint(474, 482), -R.randint(474, 482))[kind]
    ea, eb = R.randint(-100000, 100000), R.randint(-100000, 100000)
    return enc(sa, ef_of(ea), fa), enc(sb, ef_of(eb), fb), enc(sc, ef_of(ea + eb + g), fc)


def part(args):
    """cases [lo, hi) of class `cls`, case i's attribute i % 5"""
    cls, lo, hi, seed = args
    fmt, sf = golden()
    R = random.Random(seed * 1000003 + cls * 7919 + lo)
    rows = []
    t0 = time.perf_counter()
    for i in range(lo, hi):
        rnd = i % 5
        a, b, c = case(R, fmt, sf, cls, rnd)
        d, flags = sf.fma(fmt, a, b, c, rnd)
        rows.append((rnd, a, b, c, d, flags))
    return cls, lo, rows, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--count", type=int, default=750000)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    if a.count < 5 or a.count % 5:
        ap.error("--count is a positive multiple of 5 (a fifth a class)")
    if (ROOT / "host") in a.out.resolve().parents or a.out.resolve() == ROOT:
        ap.error("OUT is never inside the tree")
    a.out.mkdir(parents=True, exist_ok=True)
    per = a.count // 5
    step = max(5, (per // (4 * max(1, a.jobs)) // 5) * 5)
    work = [(cls, lo, min(per, lo + step), a.seed) for cls in range(5)
            for lo in range(0, per, step)]
    t0 = time.perf_counter()
    got, cpu = {}, 0.0
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for cls, lo, rows, secs in ex.map(part, work):
            got[(cls, lo)] = rows
            cpu += secs
    rows = [r for cls in range(5) for lo in range(0, per, step) for r in got[(cls, lo)]]
    esz, n = 32, len(rows)
    cols = [b"".join(r[k].to_bytes(esz, "little") for r in rows) for k in (1, 2, 3)]
    tail = (b"".join(r[4].to_bytes(esz, "little") for r in rows) + bytes(r[5] for r in rows))
    data = MAGIC + struct.pack("<IIQ", 3, esz, n) + b"".join(cols) + bytes(r[0] for r in rows) + tail
    path = a.out / "edge-fp256.bin"
    path.write_bytes(data)
    expect = hashlib.sha256(tail).hexdigest()
    (a.out / "edge-fp256.expect").write_text(f"{expect}  edge-fp256.bin ({n} cases, the "
                                             f"expected d||flags)\n")
    for cls in range(5):
        cr = rows[cls * per:(cls + 1) * per]
        fl = [sum(1 for r in cr if r[5] & (1 << k)) for k in range(5)]
        print(f"  class {cls + 1}, {CLASSES[cls]}: {per} cases, {per // 5} an attribute; flags "
              f"set: invalid {fl[0]}, overflow {fl[2]}, underflow {fl[3]}, inexact {fl[4]}")
    print(f"fma_edge_corpus: {n} cases (seed {a.seed}) in {time.perf_counter() - t0:.1f} s wall, "
          f"{cpu:.1f} s in the model with {a.jobs} workers; {path.name} sha256 "
          f"{hashlib.sha256(data).hexdigest()}; expect {expect}")


if __name__ == "__main__":
    main()
