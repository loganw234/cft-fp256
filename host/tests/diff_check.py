# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Drive libcft and the golden model over the same inputs and compare.

    python3 host/tests/diff_check.py                  # the standard sweep
    python3 host/tests/diff_check.py --trials 20000   # longer
    python3 host/tests/diff_check.py --formats fp256 --rounding rdn

The conformance vectors check libcft against cases the model produced
earlier. This checks it against the model itself, right now, over
inputs the vectors do not contain - and specifically over the inputs
that probe the one place the C differs structurally from the Python.

That difference is operand alignment. The model shifts exactly, in
unbounded integers; for fp256 that can be 790,000 bits. libcft bounds
the shift and carries a sticky bit instead, on the argument that
beyond a certain exponent separation the smaller term cannot influence
anything but the sticky. The argument is written out in
host/src/softfloat.c. This file is why it does not have to be taken on
faith: it builds operand triples whose exponent separation lands
exactly on and around that boundary, in both directions, at every
precision and under every rounding attribute.

It doubles as the demonstration that the C ABI is callable from Python
with ctypes and no build step, which is half the reason the library is
C in the first place.
"""

import argparse
import ctypes
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import (  # noqa: E402
    FORMATS, OP_NAMES, PREC_CODE, RND_NAMES, compute, vectors,
)
from cft_golden import softfloat as sf  # noqa: E402

RND_BY_NAME = {v: k for k, v in RND_NAMES.items()}


# ---------------------------------------------------------------------
# the library
# ---------------------------------------------------------------------

def load_library():
    """Find and bind libcft. No build step, no generated bindings - the
    header is the whole contract, and this is what it costs to call it
    from another language.

    One candidate, chosen by platform: a tree built from two platforms
    holds both libraries, and falling back to whichever exists loads
    the foreign one and reports an ELF header problem rather than a
    missing build."""
    override = os.environ.get("CFT_LIB")
    if override:
        path = Path(override)
    else:
        name = {"win32": "cft.dll", "cygwin": "cft.dll",
                "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
        path = ROOT / "host" / name
    if not path.exists():
        raise SystemExit(
            f"{path} not found - build it first:\n"
            "    make -C host\n"
            "or point CFT_LIB at the shared library.")
    return ctypes.CDLL(str(path))


def bind(lib):
    u32p = ctypes.POINTER(ctypes.c_uint32)
    lib.cft_open.argtypes = [ctypes.c_char_p, ctypes.c_int,
                             ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_open.restype = ctypes.c_int
    lib.cft_close.argtypes = [ctypes.c_void_p]
    lib.cft_close.restype = None
    lib.cft_run.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                            u32p, u32p]
    lib.cft_run.restype = ctypes.c_int
    lib.cft_strerror.argtypes = [ctypes.c_int]
    lib.cft_strerror.restype = ctypes.c_char_p
    return lib


class Device:
    def __init__(self, lib):
        self.lib = lib
        handle = ctypes.c_void_p()
        st = lib.cft_open(None, 0, ctypes.byref(handle))
        if st != 0:
            raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}")
        self.handle = handle

    def close(self):
        self.lib.cft_close(self.handle)

    def run(self, fmt, op, rnd, triples):
        """One cft_run per element, so the flags are per-element too."""
        nbytes = fmt.width // 8
        code = PREC_CODE[fmt.name]
        buf_a = ctypes.create_string_buffer(nbytes)
        buf_b = ctypes.create_string_buffer(nbytes)
        buf_c = ctypes.create_string_buffer(nbytes)
        buf_d = ctypes.create_string_buffer(nbytes)
        flags = ctypes.c_uint32(0)
        out = []
        for xa, xb, xc in triples:
            buf_a.raw = xa.to_bytes(nbytes, "little")
            buf_b.raw = xb.to_bytes(nbytes, "little")
            buf_c.raw = xc.to_bytes(nbytes, "little")
            st = self.lib.cft_run(self.handle, op, code, rnd,
                                  buf_a, buf_b, buf_c, buf_d, 1,
                                  ctypes.byref(flags), None)
            if st != 0:
                raise SystemExit(
                    f"cft_run: {self.lib.cft_strerror(st).decode()}")
            out.append((int.from_bytes(buf_d.raw, "little"), flags.value))
        return out

    def run_batch(self, fmt, op, rnd, triples):
        """One cft_run over the whole array. Same arithmetic, different
        code path: this is what exercises the element loop and the
        flag accumulation that every real caller uses."""
        nbytes = fmt.width // 8
        n = len(triples)
        code = PREC_CODE[fmt.name]
        a = b"".join(t[0].to_bytes(nbytes, "little") for t in triples)
        b = b"".join(t[1].to_bytes(nbytes, "little") for t in triples)
        c = b"".join(t[2].to_bytes(nbytes, "little") for t in triples)
        buf_a = ctypes.create_string_buffer(a, len(a))
        buf_b = ctypes.create_string_buffer(b, len(b))
        buf_c = ctypes.create_string_buffer(c, len(c))
        buf_d = ctypes.create_string_buffer(n * nbytes)
        flags = ctypes.c_uint32(0)
        st = self.lib.cft_run(self.handle, op, code, rnd,
                              buf_a, buf_b, buf_c, buf_d, n,
                              ctypes.byref(flags), None)
        if st != 0:
            raise SystemExit(f"cft_run: {self.lib.cft_strerror(st).decode()}")
        raw = buf_d.raw
        return ([int.from_bytes(raw[i * nbytes:(i + 1) * nbytes], "little")
                 for i in range(n)], flags.value)


# ---------------------------------------------------------------------
# operand construction
# ---------------------------------------------------------------------

def _finite(fmt, e_unb, frac, sign=0):
    """A normal with the given unbiased exponent, or None out of range.
    For a normal, the unbiased exponent IS the position of the leading
    bit, which is what the boundary construction below needs to be able
    to place."""
    ef = e_unb + fmt.bias
    if ef < 1 or ef > fmt.exp_mask - 1:
        return None
    return (sign << (fmt.width - 1)) | (ef << fmt.man_w) | (frac & fmt.man_mask)


def _value_exponent_of_product(fmt, xa, xb):
    """Where the exact product's leading bit sits, or None if either
    operand is not finite and non-zero."""
    ua, ub = sf.unpack(fmt, xa), sf.unpack(fmt, xb)
    if ua.kind in (sf.INF, sf.NAN, sf.ZERO) or ub.kind in (sf.INF, sf.NAN,
                                                           sf.ZERO):
        return None
    mp = ua.m * ub.m
    return ua.e + ub.e + mp.bit_length() - 1


def boundary_cases(fmt, count, seed=11):
    """Triples whose exponent separation lands on the far/near cutoff.

    libcft switches strategy when the two terms' leading bits are more
    than 2p+4 apart. Random operands essentially never land near that
    line - and never land on the far side of it with the *addend*
    dominating - so the cases that would expose an off-by-one in the
    reduction have to be built deliberately.
    """
    rng = random.Random(seed ^ (fmt.width * 104729))
    p = fmt.prec
    far = 2 * p + 4
    edges = {0, 1, 2, 3, p - 1, p, p + 1, p + 2,
             far - 3, far - 2, far - 1, far, far + 1, far + 2, far + 3,
             2 * far, 4 * far}
    deltas = sorted(edges | {-d for d in edges if d})
    lo, hi = fmt.emin // 2, fmt.emax // 2
    cases = []

    while len(cases) < count:
        sa, sb, sc = rng.getrandbits(1), rng.getrandbits(1), rng.getrandbits(1)
        xa = _finite(fmt, rng.randint(lo, hi), rng.getrandbits(fmt.man_w), sa)
        xb = _finite(fmt, rng.randint(lo, hi), rng.getrandbits(fmt.man_w), sb)
        if xa is None or xb is None:
            continue
        vep = _value_exponent_of_product(fmt, xa, xb)
        if vep is None:
            continue

        for delta in deltas:
            xc = _finite(fmt, vep - delta, rng.getrandbits(fmt.man_w), sc)
            if xc is not None:
                cases.append((sf.OP_FMA, xa, xb, xc))

        # Massive cancellation: an addend that all but annihilates the
        # product. This is the other end of the same axis - the near
        # path with the widest possible intermediate - and it is where
        # a too-narrow window would show up as a wrong answer rather
        # than as an overflow.
        prod, _ = sf.mul(fmt, xa, xb)
        if not sf.is_nan(fmt, prod):
            cases.append((sf.OP_FMA, xa, xb, sf.negate(fmt, prod)))
            for _ in range(3):
                tweak = 1 << rng.randrange(0, fmt.man_w)
                cases.append((sf.OP_FMA, xa, xb,
                              sf.negate(fmt, prod ^ tweak)))

        # The same boundary for the two-operand steerings, where the
        # "product" is just a.
        vea = rng.randint(lo, hi)
        xa2 = _finite(fmt, vea, rng.getrandbits(fmt.man_w), sa)
        for delta in deltas:
            xc = _finite(fmt, vea - delta, rng.getrandbits(fmt.man_w), sc)
            if xa2 is not None and xc is not None:
                cases.append((sf.OP_ADD, xa2, 0, xc))
                cases.append((sf.OP_SUB, xa2, 0, xc))

    return cases[:count]


def extreme_cases(fmt, count, seed=13):
    """Products that land on emin and emax, where the bounded alignment
    and the subnormal clamp have to agree with the model at once."""
    rng = random.Random(seed ^ (fmt.width * 15485863))
    p = fmt.prec
    cases = []
    while len(cases) < count:
        for target in (fmt.emin, fmt.emin + p, fmt.emax, fmt.emax - p, 0):
            for _ in range(4):
                split = rng.randint(-p, p)
                ea = target // 2 + split
                eb = target - ea
                xa = _finite(fmt, ea, rng.getrandbits(fmt.man_w),
                             rng.getrandbits(1))
                xb = _finite(fmt, eb, rng.getrandbits(fmt.man_w),
                             rng.getrandbits(1))
                if xa is None or xb is None:
                    continue
                # an addend everywhere from far above to far below
                for shift in (-2 * p, -p, -1, 0, 1, p, 2 * p):
                    xc = _finite(fmt, target + shift,
                                 rng.getrandbits(fmt.man_w),
                                 rng.getrandbits(1))
                    if xc is not None:
                        cases.append((sf.OP_FMA, xa, xb, xc))
                # and a subnormal addend, which is the case the far
                # path has to left-normalise before it can carry a
                # sticky at all
                cases.append((sf.OP_FMA, xa, xb, rng.randrange(1, 1 << 8)))
    return cases[:count]


# ---------------------------------------------------------------------
# the comparison
# ---------------------------------------------------------------------

def check(dev, fmt, rnd, cases, label, stop_after=8):
    """Compare libcft against the model, case by case. Returns the
    number of disagreements."""
    hexw = fmt.width // 4
    by_op = {}
    for op, xa, xb, xc in cases:
        by_op.setdefault(op, []).append((xa, xb, xc))

    bad = 0
    for op, triples in sorted(by_op.items()):
        got = dev.run(fmt, op, rnd, triples)
        for (xa, xb, xc), (gd, gf) in zip(triples, got):
            wd, wf = compute(fmt, op, xa, xb, xc, rnd)
            if gd == wd and gf == wf:
                continue
            bad += 1
            if bad <= stop_after:
                print(f"  MISMATCH {label} {fmt.name} "
                      f"{OP_NAMES.get(op, f'reserved{op}')} "
                      f"{RND_NAMES[rnd]}")
                print(f"    a        0x{xa:0{hexw}x}")
                print(f"    b        0x{xb:0{hexw}x}")
                print(f"    c        0x{xc:0{hexw}x}")
                print(f"    model    0x{wd:0{hexw}x} flags 0x{wf:02x}")
                print(f"    libcft   0x{gd:0{hexw}x} flags 0x{gf:02x}")

        # The array path must agree with the element path, bit for bit,
        # and must OR the flags rather than report the last one.
        batch_d, batch_f = dev.run_batch(fmt, op, rnd, triples)
        want_f = 0
        for _, f in got:
            want_f |= f
        if batch_d != [d for d, _ in got]:
            bad += 1
            print(f"  MISMATCH {label} {fmt.name} "
                  f"{OP_NAMES.get(op, f'reserved{op}')}: the array path "
                  f"disagrees with the element path")
        if batch_f != want_f:
            bad += 1
            print(f"  MISMATCH {label} {fmt.name} "
                  f"{OP_NAMES.get(op, f'reserved{op}')}: batch flags "
                  f"0x{batch_f:02x}, OR of element flags 0x{want_f:02x}")
    return bad


def coverage(fmt, cases):
    """Which alignment path did these cases actually take?

    A boundary test that never reaches the boundary passes for the
    wrong reason, and passing for the wrong reason is indistinguishable
    from passing until the day it matters. So the classification libcft
    makes internally is reproduced here, from the model's own unpack,
    and reported alongside the result.
    """
    p = fmt.prec
    far = 2 * p + 4
    tally = {"far, product larger": 0, "far, addend larger": 0, "near": 0,
             "special (nan/inf/zero)": 0, "far, like signs": 0,
             "far, unlike signs": 0}
    widest = 0
    for op, xa, xb, xc in cases:
        if op not in (sf.OP_FMA, sf.OP_ADD, sf.OP_SUB, sf.OP_MUL):
            continue
        ra, rb, rc = sf.steer(fmt, op, xa, xb, xc)
        ua, ub, uc = sf.unpack(fmt, ra), sf.unpack(fmt, rb), sf.unpack(fmt, rc)
        if any(u.kind in (sf.NAN, sf.INF, sf.ZERO) for u in (ua, ub, uc)):
            tally["special (nan/inf/zero)"] += 1
            continue
        mp = ua.m * ub.m
        ep = ua.e + ub.e
        vep = ep + mp.bit_length() - 1
        vec = uc.e + uc.m.bit_length() - 1
        if vep - vec > far or vec - vep > far:
            tally["far, product larger" if vep > vec
                  else "far, addend larger"] += 1
            tally["far, like signs" if (ua.sign ^ ub.sign) == uc.sign
                  else "far, unlike signs"] += 1
        else:
            tally["near"] += 1
            widest = max(widest, max(vep, vec) - min(ep, uc.e) + 1)
    return tally, widest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coverage", action="store_true",
                    help="report which alignment path the cases reach, "
                         "instead of comparing")
    ap.add_argument("--formats", nargs="+", default=list(FORMATS),
                    choices=list(FORMATS))
    ap.add_argument("--rounding", nargs="+", default=list(RND_BY_NAME),
                    choices=list(RND_BY_NAME))
    ap.add_argument("--trials", type=int, default=1200,
                    help="cases per family per (format, attribute)")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    def build(fmt):
        return [
            ("random", vectors.testset(fmt, args.trials // 2,
                                       args.trials // 2, args.seed)),
            ("simple", vectors.simple_cases(fmt, max(8, args.trials // 40),
                                            args.seed + 1)),
            ("boundary", boundary_cases(fmt, args.trials, args.seed + 2)),
            ("extreme", extreme_cases(fmt, args.trials, args.seed + 3)),
        ]

    if args.coverage:
        for name in args.formats:
            fmt = FORMATS[name]
            cases = [c for _, fam in build(fmt) for c in fam]
            tally, widest = coverage(fmt, cases)
            print(f"{name}: far cutoff at 2p+4 = {2 * fmt.prec + 4} bits, "
                  f"{len(cases)} cases")
            for k, v in tally.items():
                print(f"    {k:24} {v}")
            print(f"    widest exact intermediate {widest} bits, of "
                  f"{2048} the container holds")
        return 0

    dev = Device(bind(load_library()))
    total = 0
    bad = 0
    try:
        for name in args.formats:
            fmt = FORMATS[name]
            families = build(fmt)
            for rname in args.rounding:
                rnd = RND_BY_NAME[rname]
                for label, cases in families:
                    bad += check(dev, fmt, rnd, cases, label)
                    total += len(cases)
                print(f"{name} {rname}: "
                      f"{sum(len(c) for _, c in families)} cases"
                      f"{'' if not bad else f'  ({bad} MISMATCHES)'}")
    finally:
        dev.close()

    print(f"\n{total} cases compared against the golden model")
    if bad:
        print(f"{bad} DISAGREEMENTS - libcft does not implement the contract")
        return 1
    print("libcft and the golden model agree on every case, bits and flags")
    return 0


if __name__ == "__main__":
    sys.exit(main())
