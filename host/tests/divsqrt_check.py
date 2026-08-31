# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""cft_div, cft_sqrt and the seed opcodes against the golden model.

    python3 host/tests/divsqrt_check.py                # standard sweep
    python3 host/tests/divsqrt_check.py --trials 400   # longer
    python3 host/tests/divsqrt_check.py --formats fp64

test_sequences.py proves the composed sequence bit-identical to the
contract div/sqrt AT MODEL LEVEL. This proves the C PORT of that
sequence - host/src/divsqrt.c - against the same contract, over the
same operand families the model's matrix used to kill five broken
constructions: the exact-tie divisors around 1 and min_normal,
max_subnormal, both signs, full rounding-mode coverage, and randoms.
The check is per-call (n=1) so flags compare per element, plus one
large batch that crosses the library's internal chunk boundary so the
chunked path and its flag accumulation are exercised too.

The seed opcodes ride along: they are ordinary cft_run opcodes, but
they entered the contract after every other elementwise op, so they
get the same direct comparison here rather than waiting for the
vector sets to be regenerated.
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
    FORMATS, PREC_CODE, RND_NAMES, compute, vectors,
    OP_RECIP_SEED, OP_RSQRT_SEED,
    one_bits, min_normal_bits, max_subnormal_bits,
)
from cft_golden import softfloat as sf  # noqa: E402

RND_BY_NAME = {v: k for k, v in RND_NAMES.items()}


def load_library():
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
    lib.cft_div.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_size_t, u32p, u32p]
    lib.cft_div.restype = ctypes.c_int
    lib.cft_sqrt.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                             ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_size_t, u32p, u32p]
    lib.cft_sqrt.restype = ctypes.c_int
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

    def _call(self, fn, fmt, rnd, arrays, n):
        nbytes = fmt.width // 8
        bufs = [ctypes.create_string_buffer(
                    b"".join(v.to_bytes(nbytes, "little") for v in arr),
                    n * nbytes)
                for arr in arrays]
        out = ctypes.create_string_buffer(n * nbytes)
        flags = ctypes.c_uint32(0)
        st = fn(self.handle, PREC_CODE[fmt.name], rnd, *bufs, out, n,
                ctypes.byref(flags), None)
        if st != 0:
            raise SystemExit(
                f"call failed: {self.lib.cft_strerror(st).decode()}")
        raw = out.raw
        return ([int.from_bytes(raw[i * nbytes:(i + 1) * nbytes], "little")
                 for i in range(n)], flags.value)

    def div(self, fmt, rnd, avals, bvals):
        return self._call(self.lib.cft_div, fmt, rnd, [avals, bvals],
                          len(avals))

    def sqrt(self, fmt, rnd, avals):
        return self._call(self.lib.cft_sqrt, fmt, rnd, [avals], len(avals))

    def run1(self, fmt, op, rnd, xa):
        nbytes = fmt.width // 8
        a = ctypes.create_string_buffer(xa.to_bytes(nbytes, "little"), nbytes)
        d = ctypes.create_string_buffer(nbytes)
        flags = ctypes.c_uint32(0)
        st = self.lib.cft_run(self.handle, op, PREC_CODE[fmt.name], rnd,
                              a, None, None, d, 1, ctypes.byref(flags), None)
        if st != 0:
            raise SystemExit(
                f"cft_run: {self.lib.cft_strerror(st).decode()}")
        return int.from_bytes(d.raw, "little"), flags.value


def pool_for(fmt, extra_random, seed=0xD5EED):
    """The same families test_sequences.py runs the model over."""
    rng = random.Random(seed)
    pool = list(vectors.interesting_operands(fmt))
    for base in (one_bits(fmt), min_normal_bits(fmt)):
        pool += [base - 1, base + 1]
    pool += [max_subnormal_bits(fmt)]
    pool += [x | fmt.sign_mask for x in pool[:8]]
    pool += [rng.getrandbits(fmt.width) for _ in range(extra_random)]
    return pool


def check_div(dev, fmt, rnds, trials):
    pool = pool_for(fmt, trials)
    dens = pool[:min(len(pool), 22 if fmt.width <= 64 else 10)]
    bad = 0
    for rnd in rnds:
        avals, bvals, want = [], [], []
        for a in pool:
            for b in dens:
                avals.append(a)
                bvals.append(b)
                want.append(sf.div(fmt, a, b, rnd))
        got_d, got_f = dev.div(fmt, rnd, avals, bvals)
        exp_f = 0
        for i, (wd, wf) in enumerate(want):
            exp_f |= wf
            if got_d[i] != wd:
                bad += 1
                if bad <= 8:
                    print(f"  {fmt.name} {RND_NAMES[rnd]} "
                          f"{avals[i]:#x}/{bvals[i]:#x}: "
                          f"lib={got_d[i]:#x} model={wd:#x}")
        if got_f != exp_f:
            bad += 1
            print(f"  {fmt.name} {RND_NAMES[rnd]} div FLAGS: "
                  f"lib={got_f:#07b} model={exp_f:#07b}")
    return bad, len(pool) * len(dens) * len(rnds)


def check_sqrt(dev, fmt, rnds, trials):
    pool = pool_for(fmt, trials, seed=0x59012)
    bad = 0
    for rnd in rnds:
        want = [sf.sqrt(fmt, a, rnd) for a in pool]
        got_d, got_f = dev.sqrt(fmt, rnd, pool)
        exp_f = 0
        for i, (wd, wf) in enumerate(want):
            exp_f |= wf
            if got_d[i] != wd:
                bad += 1
                if bad <= 8:
                    print(f"  {fmt.name} {RND_NAMES[rnd]} sqrt({pool[i]:#x}): "
                          f"lib={got_d[i]:#x} model={wd:#x}")
        if got_f != exp_f:
            bad += 1
            print(f"  {fmt.name} {RND_NAMES[rnd]} sqrt FLAGS: "
                  f"lib={got_f:#07b} model={exp_f:#07b}")
    return bad, len(pool) * len(rnds)


def check_seeds(dev, fmt, trials):
    """The seed opcodes through cft_run, one element per call so the
    (quiet) flags compare per element too."""
    pool = pool_for(fmt, trials, seed=0x5EED5)
    bad = 0
    for op in (OP_RECIP_SEED, OP_RSQRT_SEED):
        for a in pool:
            wd, wf = compute(fmt, op, a, 0, 0)
            gd, gf = dev.run1(fmt, op, 0, a)
            if (gd, gf) != (wd, wf):
                bad += 1
                if bad <= 8:
                    print(f"  {fmt.name} op{op}({a:#x}): "
                          f"lib={gd:#x},{gf} model={wd:#x},{wf}")
    return bad, 2 * len(pool)


def check_chunk_crossing(dev, fmt, rnd):
    """One n that crosses the library's internal chunk size, so the
    chunk loop, its flag accumulation and the aliasing discipline at
    chunk edges all run. 4096 is divsqrt.c's CHUNK; 5000 crosses it."""
    rng = random.Random(0xC40551)
    n = 5000
    avals = [rng.getrandbits(fmt.width) for _ in range(n)]
    bvals = [rng.getrandbits(fmt.width) for _ in range(n)]
    want = [sf.div(fmt, avals[i], bvals[i], rnd) for i in range(n)]
    got_d, got_f = dev.div(fmt, rnd, avals, bvals)
    exp_f = 0
    bad = 0
    for i, (wd, wf) in enumerate(want):
        exp_f |= wf
        if got_d[i] != wd:
            bad += 1
            if bad <= 8:
                print(f"  chunk {fmt.name} [{i}] {avals[i]:#x}/{bvals[i]:#x}: "
                      f"lib={got_d[i]:#x} model={wd:#x}")
    if got_f != exp_f:
        bad += 1
        print(f"  chunk {fmt.name} FLAGS: lib={got_f:#07b} model={exp_f:#07b}")
    return bad, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--formats", nargs="+", default=list(FORMATS))
    ap.add_argument("--rounding", nargs="+", default=list(RND_BY_NAME))
    ap.add_argument("--trials", type=int, default=None,
                    help="extra random operands per pool (default scales "
                         "with width)")
    args = ap.parse_args()

    lib = bind(load_library())
    dev = Device(lib)
    rnds = [RND_BY_NAME[r] for r in args.rounding]
    total_bad = 0
    total = 0

    for name in args.formats:
        fmt = FORMATS[name]
        trials = args.trials
        if trials is None:
            trials = 30 if fmt.width <= 64 else 8
        for fn, lbl in ((lambda: check_div(dev, fmt, rnds, trials), "div"),
                        (lambda: check_sqrt(dev, fmt, rnds,
                                            2 * trials), "sqrt"),
                        (lambda: check_seeds(dev, fmt, 2 * trials), "seeds")):
            bad, count = fn()
            total_bad += bad
            total += count
            print(f"{fmt.name} {lbl}: {count} cases, {bad} disagreements")

    bad, count = check_chunk_crossing(dev, FORMATS["fp32"], rnds[0])
    total_bad += bad
    total += count
    print(f"fp32 chunk-crossing div: {count} cases, {bad} disagreements")

    dev.close()
    if total_bad:
        raise SystemExit(f"FAIL: {total_bad} of {total} disagree")
    print(f"OK: {total} cases, library matches the model exactly")


if __name__ == "__main__":
    main()
