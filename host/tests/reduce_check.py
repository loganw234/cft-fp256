# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""libcft's reduction tree against the golden model's, over the same inputs.

    python3 host/tests/reduce_check.py                 # standard sweep
    python3 host/tests/reduce_check.py --trials 4000
    python3 host/tests/reduce_check.py --formats fp256 --rounding rdn

Two independent implementations of one tree shape. The arithmetic at
each node is already cross-checked by diff_check.py, so what this adds
is the SHAPE: a reduction is only reproducible if both sides split the
index range the same way, at every level, for every n - and n is where
this goes wrong, because a shape that agrees on powers of two can
disagree on 5, 9 or 13 and never be noticed by a test that only tries
round numbers.

So the sizes here are deliberately awkward. Every n from 0 to 40 is
covered exhaustively, then random larger ones, because the small odd
sizes are exactly where a floor-vs-ceiling midpoint or an
extra-element-goes-left convention diverges.

It also checks the two calling-convention refusals in both directions,
since a reduction issued through cft_run() or an elementwise op issued
through cft_reduce() must be an error rather than a plausible number.
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
    FORMATS, PREC_CODE, RND_NAMES,
)
from cft_golden.reduce import (  # noqa: E402
    OP_SUM, OP_DOT, canonical_ranges, combine, fdot, fsum, reduce_bits,
)

RND_BY_NAME = {v: k for k, v in RND_NAMES.items()}

CFT_OK = 0
CFT_ERR_INVALID_ARGUMENT = 1
CFT_ERR_UNSUPPORTED = 2

OP_FMA = 0          # an elementwise opcode, for the refusal check


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
    lib.cft_reduce.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                               ctypes.c_void_p, ctypes.c_size_t, u32p, u32p]
    lib.cft_reduce.restype = ctypes.c_int
    lib.cft_run.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                            u32p, u32p]
    lib.cft_run.restype = ctypes.c_int
    lib.cft_op_name.argtypes = [ctypes.c_int]
    lib.cft_op_name.restype = ctypes.c_char_p
    lib.cft_supports.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.cft_supports.restype = ctypes.c_int


def to_bytes(fmt, values):
    esz = fmt.width // 8
    buf = bytearray()
    for v in values:
        buf += int(v).to_bytes(esz, "little")
    return bytes(buf)


def rand_finite(fmt, rng, spread=20):
    sign = rng.getrandbits(1)
    e = fmt.bias + rng.randint(-spread, spread)
    m = rng.getrandbits(fmt.man_w)
    return (sign << (fmt.width - 1)) | (e << fmt.man_w) | m


def rand_operand(fmt, rng):
    """Mostly ordinary numbers, with specials mixed in at a rate high
    enough to be hit and low enough that the arithmetic still gets
    exercised. A reduction over nothing but NaNs proves very little."""
    r = rng.random()
    if r < 0.04:
        return (fmt.exp_mask << fmt.man_w) | (1 << (fmt.man_w - 1))   # qNaN
    if r < 0.07:
        return rng.getrandbits(1) << (fmt.width - 1) | \
            (fmt.exp_mask << fmt.man_w)                              # inf
    if r < 0.11:
        return rng.getrandbits(1) << (fmt.width - 1)                 # zero
    if r < 0.15:
        return (rng.getrandbits(1) << (fmt.width - 1)) | \
            rng.randrange(1, 1 << fmt.man_w)                         # subnormal
    return rand_finite(fmt, rng)


class Checker:
    def __init__(self, lib, dev):
        self.lib, self.dev = lib, dev
        self.checked = 0
        self.failed = 0

    def call(self, op, fmt, rnd, xs, ys=None, n=None):
        esz = fmt.width // 8
        if n is None:
            n = len(xs)
        a = ctypes.create_string_buffer(to_bytes(fmt, xs), max(len(xs), 1) * esz)
        b = None
        if ys is not None:
            b = ctypes.create_string_buffer(to_bytes(fmt, ys),
                                            max(len(ys), 1) * esz)
        d = ctypes.create_string_buffer(esz)
        flags = ctypes.c_uint32(0xDEADBEEF)
        st = self.lib.cft_reduce(
            self.dev, op, PREC_CODE[fmt.name], rnd,
            ctypes.cast(a, ctypes.c_void_p),
            ctypes.cast(b, ctypes.c_void_p) if b is not None else None,
            ctypes.cast(d, ctypes.c_void_p), n,
            ctypes.byref(flags), None)
        if st != CFT_OK:
            return st, None, None
        return st, int.from_bytes(d.raw[:esz], "little"), flags.value

    def one(self, op, fmt, rnd, xs, ys):
        st, got, gflags = self.call(op, fmt, rnd, xs, ys)
        if op == OP_SUM:
            want, wflags = fsum(fmt, xs, rnd)
        else:
            want, wflags = fdot(fmt, xs, ys, rnd)
        self.checked += 1
        if st != CFT_OK:
            self.fail(op, fmt, rnd, xs, ys, f"status {st}")
        elif got != want or gflags != wflags:
            self.fail(op, fmt, rnd, xs, ys,
                      f"got 0x{got:x}/{gflags:02x} "
                      f"want 0x{want:x}/{wflags:02x}")

    def fail(self, op, fmt, rnd, xs, ys, why):
        self.failed += 1
        if self.failed <= 5:
            name = "sum" if op == OP_SUM else "dot"
            print(f"FAIL {name} {fmt.name} {RND_NAMES[rnd]} n={len(xs)}: {why}")
            print(f"     a = {[hex(x) for x in xs[:6]]}")
            if op == OP_DOT:
                print(f"     b = {[hex(y) for y in ys[:6]]}")


def check_refusals(lib, dev, fmt):
    """The calling-convention boundary, both ways round."""
    esz = fmt.width // 8
    a = ctypes.create_string_buffer(esz * 4)
    d = ctypes.create_string_buffer(esz * 4)
    bad = 0

    st = lib.cft_run(dev, OP_SUM, PREC_CODE[fmt.name], 0,
                     ctypes.cast(a, ctypes.c_void_p), None,
                     ctypes.cast(a, ctypes.c_void_p),
                     ctypes.cast(d, ctypes.c_void_p), 4, None, None)
    if st != CFT_ERR_INVALID_ARGUMENT:
        print(f"FAIL cft_run(sum) returned {st}, want INVALID_ARGUMENT")
        bad += 1

    st = lib.cft_reduce(dev, OP_FMA, PREC_CODE[fmt.name], 0,
                        ctypes.cast(a, ctypes.c_void_p), None,
                        ctypes.cast(d, ctypes.c_void_p), 4, None, None)
    if st != CFT_ERR_INVALID_ARGUMENT:
        print(f"FAIL cft_reduce(fma) returned {st}, want INVALID_ARGUMENT")
        bad += 1

    if lib.cft_op_name(OP_SUM) != b"sum" or lib.cft_op_name(OP_DOT) != b"dot":
        print("FAIL cft_op_name does not know the reduction opcodes")
        bad += 1

    if not lib.cft_supports(dev, OP_SUM, PREC_CODE[fmt.name]):
        print("FAIL software backend reports sum unsupported")
        bad += 1
    return bad


def check_partition(lib, dev, fmt, rng, trials):
    """A reduction split across tiles must equal the whole.

    Done here rather than only in the model because this is the property
    a multi-tile host will depend on, and it depends on libcft's tree
    agreeing with the model's at EVERY node, not just at the root.
    """
    bad = 0
    ck = Checker(lib, dev)
    for _ in range(trials):
        n = rng.choice([1, 2, 3, 5, 7, 9, 13, 16, 17, 31, 33, 64, 65])
        xs = [rand_finite(fmt, rng) for _ in range(n)]
        rnd = rng.choice(list(RND_NAMES))
        st, whole, wflags = ck.call(OP_SUM, fmt, rnd, xs)
        if st != CFT_OK:
            print(f"FAIL partition base call status {st}")
            bad += 1
            continue
        for parts in (2, 4, 8):
            partials, flags = [], 0
            for lo, hi in canonical_ranges(n, parts):
                p, f = reduce_bits(fmt, xs, rnd, lo, hi)
                partials.append(p)
                flags |= f
            got, cf = combine(fmt, partials, rnd)
            if got != whole or (flags | cf) != wflags:
                print(f"FAIL partition n={n} parts={parts} {fmt.name} "
                      f"{RND_NAMES[rnd]}: 0x{got:x} vs 0x{whole:x}")
                bad += 1
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=1500)
    ap.add_argument("--formats", nargs="+", default=list(FORMATS))
    ap.add_argument("--rounding", nargs="+", default=list(RND_BY_NAME))
    ap.add_argument("--seed", type=int, default=20260830)
    args = ap.parse_args()

    lib = load_library()
    bind(lib)
    dev = ctypes.c_void_p()
    st = lib.cft_open(None, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open failed: {st}")

    rng = random.Random(args.seed)
    ck = Checker(lib, dev)
    bad = 0

    for fname in args.formats:
        fmt = FORMATS[fname]
        rounds = [RND_BY_NAME[r] for r in args.rounding]

        # Every small n, exhaustively. This is where a shape bug lives:
        # an implementation that agrees on 2, 4, 8 and 16 can still
        # disagree on 5, and only trying round numbers would miss it.
        for n in range(0, 41):
            for rnd in rounds:
                xs = [rand_operand(fmt, rng) for _ in range(n)]
                ys = [rand_operand(fmt, rng) for _ in range(n)]
                ck.one(OP_SUM, fmt, rnd, xs, ys)
                ck.one(OP_DOT, fmt, rnd, xs, ys)

        for _ in range(args.trials):
            n = rng.randint(41, 400)
            rnd = rng.choice(rounds)
            xs = [rand_operand(fmt, rng) for _ in range(n)]
            ys = [rand_operand(fmt, rng) for _ in range(n)]
            ck.one(rng.choice((OP_SUM, OP_DOT)), fmt, rnd, xs, ys)

        bad += check_refusals(lib, dev, fmt)
        bad += check_partition(lib, dev, fmt, rng, 60)

    lib.cft_close(dev)

    total = ck.checked
    bad += ck.failed
    print(f"{total} reductions checked across "
          f"{len(args.formats)} formats, {bad} failures")
    if total < 1000:
        raise SystemExit("suspiciously few checks ran - the sweep did not "
                         "cover what it claims to")
    if bad:
        raise SystemExit(1)
    print("libcft and the golden model agree on the tree, bits and flags")


if __name__ == "__main__":
    main()
