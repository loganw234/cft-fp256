#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The fixed tier's golden referee (round 3's G3A; fp128 round 3's G3A2): a
corpus of the FMA's hard classes, every expected (bits, flags) from
python/cft_golden - the authority, never the generic kernel - in study
GPU-A's corpus layout, so that hip-corpus runs it on any device (either
tier, staged or resident) and the sha256 of its output equals the corpus's
expected tail.

    python -B host/tests/fma_edge_corpus.py OUT [--format fp256|fp128]
                                            [--count N] [--seed S] [--jobs J]

writes OUT/edge-<format>.bin (never into the tree) and
OUT/edge-<format>.expect, the sha256 of the expected d || flags. Five
classes, a fifth of the cases each, every class at all five attributes in
equal shares, random signs - the four GPU-A's stream does not aim at
(docs/studies/GPU-A-hip.md, section 6, "a known limit of the generator")
and the alignment edges; at fp256 (the default, G3A's):

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

--format fp128 (G3A2) writes the same classes scaled to binary128, every
constant from the format (bias 16383, a 112-bit fraction, the field
0x7FFF): exponents drawn within 16,000 binades (6,000 for classes 4 and 5)
where fp256's are within 262,000 (100,000); the short significands' low 64
fraction bits clear (fp256's 128); class 3's far products within 300
binades; class 4's top 80 to 112 fraction bits set and c near
top - (p + 2) = top - 115; class 5's gaps 25 to 33, -(138 to 146) and
+-(226 to 234) (the fixed window's sticky first arises at 29 for a
226-bit product and 30 for a 225-bit one, c's own at 142, and FAR = 2p + 4
= 230) - the classes of tools/fx128_stream.h's edge stream. Its file does
NOT depend on --jobs: its cases are made in chunks of a constant 5,000,
each seeded by the seed, the class and the chunk's first case alone (fp256's
chunks, G3A's, follow --jobs, so its file is the same only for the same
--jobs: --jobs 2 gives G3A's recorded expect 8eaba90c...).

The layout (gen_corpus.py's): b"CFTGPUA1", u32 format code (3, or 2 for
fp128), u32 element bytes (32 or 16), u64 n; a, b, c (n elements each,
little-endian), the attributes (n bytes), the expected d (n elements) and
flags (n bytes). Default count 750,000, past the 747,560 of VGPU-A's own
(unpublished) corpus of these classes.
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
# Each format's constants, fp256's G3A's own. code and esz: the corpus
# header's format code and element bytes; w the encoding's width; e1 the
# draw of classes 1 and 2's a exponent, short the short significands' low
# bits cleared, far class 3's far scale, x class 4's and 5's exponent draw,
# ones class 4's top bits set, cgap class 4's c offset (p + 2), gaps class
# 5's c offsets; step a chunk's cases (None: follow --jobs, as G3A's fp256).
PARAMS = {
    "fp256": dict(code=3, esz=32, w=256, bias=262143, emin=-262142, emax=262143, mw=236,
                  top=0x7FFFF, e1=262000, short=128, far=600, x=100000, ones=(200, 236),
                  cgap=239, gaps=((33, 41), (270, 278), (474, 482)), step=None),
    "fp128": dict(code=2, esz=16, w=128, bias=16383, emin=-16382, emax=16383, mw=112,
                  top=0x7FFF, e1=16000, short=64, far=300, x=6000, ones=(80, 112),
                  cgap=115, gaps=((25, 33), (138, 146), (226, 234)), step=5000),
}


def golden(name):
    sys.path.insert(0, str(ROOT / "python"))
    from cft_golden import FORMATS, softfloat
    return FORMATS[name], softfloat


def enc(P, sign, ef, frac):
    return (sign << (P["w"] - 1)) | (ef << P["mw"]) | (frac & ((1 << P["mw"]) - 1))


def ef_of(P, e):
    """the biased field of an unbiased exponent, clamped to a finite one"""
    return max(0, min(P["top"] - 1, e + P["bias"]))


def cancel(P, R, fmt, sf, a, b, rnd):
    """c = -(a*b rounded), a few ulps off half the time"""
    p, _ = sf.fma(fmt, a, b, 0, rnd)
    c = p ^ (1 << (P["w"] - 1))
    if R.random() < 0.5:
        c = max(0, min((1 << P["w"]) - 1, c + R.randint(-2, 2)))
    return c


def case(P, R, fmt, sf, cls, rnd):
    MW, EMIN, EMAX = P["mw"], P["emin"], P["emax"]
    FRAC = (1 << MW) - 1
    sa, sb, sc = R.getrandbits(1), R.getrandbits(1), R.getrandbits(1)
    fa, fb, fc = R.getrandbits(MW), R.getrandbits(MW), R.getrandbits(MW)
    if cls in (0, 1):
        t = EMIN + R.randint(-12, 12) if cls == 0 else EMAX + R.randint(-10, 1)
        ea = R.randint(-P["e1"], -20) if cls == 0 else R.randint(20, P["e1"])
        if R.random() < 0.25:                       # short significands: a*b exact
            fa &= ~((1 << P["short"]) - 1)
            fb &= ~((1 << P["short"]) - 1)
        a, b = enc(P, sa, ef_of(P, ea), fa), enc(P, sb, ef_of(P, t - ea), fb)
        return a, b, cancel(P, R, fmt, sf, a, b, rnd)
    if cls == 2:
        ulps = R.randint(0, 3)
        c = enc(P, sc, 1, ulps) if R.getrandbits(1) else enc(P, sc, 0, FRAC - ulps)
        t = EMIN + (R.randint(-4, 4) if R.getrandbits(1) else R.randint(-P["far"], P["far"]))
        ea = t // 2
        return enc(P, sa, ef_of(P, ea), fa), enc(P, sb, ef_of(P, t - ea), fb), c
    if cls == 3:
        top = EMAX - R.getrandbits(1)
        x = R.randint(-P["x"], P["x"])
        ones = R.randint(*P["ones"])
        fa |= FRAC ^ ((1 << (MW - ones)) - 1)       # the top `ones` bits of the fraction
        fb = R.getrandbits(16) if R.getrandbits(1) else 0
        fc = 0 if R.randint(0, 2) == 0 else fc
        return (enc(P, sa, ef_of(P, x), fa), enc(P, sb, ef_of(P, top - x), fb),
                enc(P, sc, ef_of(P, top - P["cgap"] + R.randint(0, 4)), fc))
    kind = R.randint(0, 3)
    (u0, u1), (b0, b1), (f0, f1) = P["gaps"]
    g = (R.randint(u0, u1), -R.randint(b0, b1), R.randint(f0, f1), -R.randint(f0, f1))[kind]
    ea, eb = R.randint(-P["x"], P["x"]), R.randint(-P["x"], P["x"])
    return (enc(P, sa, ef_of(P, ea), fa), enc(P, sb, ef_of(P, eb), fb),
            enc(P, sc, ef_of(P, ea + eb + g), fc))


def part(args):
    """cases [lo, hi) of class `cls`, case i's attribute i % 5"""
    name, cls, lo, hi, seed = args
    P = PARAMS[name]
    fmt, sf = golden(name)
    R = random.Random(seed * 1000003 + cls * 7919 + lo)
    rows = []
    t0 = time.perf_counter()
    for i in range(lo, hi):
        rnd = i % 5
        a, b, c = case(P, R, fmt, sf, cls, rnd)
        d, flags = sf.fma(fmt, a, b, c, rnd)
        rows.append((rnd, a, b, c, d, flags))
    return cls, lo, rows, time.perf_counter() - t0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--format", choices=("fp256", "fp128"), default="fp256")
    ap.add_argument("--count", type=int, default=750000)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--jobs", type=int, default=1)
    a = ap.parse_args()
    if a.count < 5 or a.count % 5:
        ap.error("--count is a positive multiple of 5 (a fifth a class)")
    if (ROOT / "host") in a.out.resolve().parents or a.out.resolve() == ROOT:
        ap.error("OUT is never inside the tree")
    P = PARAMS[a.format]
    a.out.mkdir(parents=True, exist_ok=True)
    per = a.count // 5
    step = P["step"] or max(5, (per // (4 * max(1, a.jobs)) // 5) * 5)
    work = [(a.format, cls, lo, min(per, lo + step), a.seed) for cls in range(5)
            for lo in range(0, per, step)]
    t0 = time.perf_counter()
    got, cpu = {}, 0.0
    with concurrent.futures.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for cls, lo, rows, secs in ex.map(part, work):
            got[(cls, lo)] = rows
            cpu += secs
    rows = [r for cls in range(5) for lo in range(0, per, step) for r in got[(cls, lo)]]
    esz, n = P["esz"], len(rows)
    cols = [b"".join(r[k].to_bytes(esz, "little") for r in rows) for k in (1, 2, 3)]
    tail = (b"".join(r[4].to_bytes(esz, "little") for r in rows) + bytes(r[5] for r in rows))
    data = (MAGIC + struct.pack("<IIQ", P["code"], esz, n) + b"".join(cols) +
            bytes(r[0] for r in rows) + tail)
    path = a.out / f"edge-{a.format}.bin"
    path.write_bytes(data)
    expect = hashlib.sha256(tail).hexdigest()
    (a.out / f"edge-{a.format}.expect").write_text(f"{expect}  edge-{a.format}.bin ({n} cases, "
                                                   f"the expected d||flags)\n")
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
