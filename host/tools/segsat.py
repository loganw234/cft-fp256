# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Reductions at scale on RESIDENT buffers: one `cft_reduce_seg` over
N elements in segments of L, the operands published to the device once,
timed over reps - so what is measured is the engine and the split of
whole segments across the image's tiles, not the bus.

    python host/tools/segsat.py --artifact IMAGE [--format fp64]
                                [--length 192] [--elements 16777216]
                                [--reps 5] [--op sum|maxall]

Written for the round-2 pair's saturation runs (2026-09-16): the card
day's `segtime.py` stages its operands on every call, which is the
right measurement of the call count and the wrong one of four tiles.
Every result is checked exactly - the values are small integers, so
every segment's sum is an exact integer in every format and a wrong
result is a wrong number, not a rounding difference. On the software
backend the four resident calls are an allocation and two no-ops, so
the same script runs there and says only that the answers agree.
"""

import argparse
import ctypes
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "host" / "tools"))

from cft_golden import FORMATS  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from gathertime import CFT_OK, load_library  # noqa: E402

FMT_CODE = {"fp32": 0, "fp64": 1, "fp128": 2, "fp256": 3}
OP_CODE = {"sum": 24, "maxall": 31}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--artifact", default=None)
    ap.add_argument("--format", default="fp64", choices=list(FMT_CODE))
    ap.add_argument("--length", type=int, default=192, help="L, the segment")
    ap.add_argument("--elements", type=int, default=1 << 24, help="N, a multiple of L")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--op", default="sum", choices=list(OP_CODE))
    args = ap.parse_args()
    fmt = FORMATS[args.format]
    esz = fmt.width // 8
    N, L = args.elements, args.length
    if N % L:
        raise SystemExit(f"--elements {N} is not a multiple of --length {L}")
    E = N // L

    lib = load_library()
    u32p = ctypes.POINTER(ctypes.c_uint32)
    lib.cft_alloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                              ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_alloc.restype = ctypes.c_int
    lib.cft_buffer_data.argtypes = [ctypes.c_void_p]
    lib.cft_buffer_data.restype = ctypes.c_void_p
    lib.cft_buffer_to_device.argtypes = [ctypes.c_void_p]
    lib.cft_buffer_to_device.restype = ctypes.c_int
    lib.cft_buffer_from_device.argtypes = [ctypes.c_void_p]
    lib.cft_buffer_from_device.restype = ctypes.c_int
    lib.cft_buffer_free.argtypes = [ctypes.c_void_p]
    lib.cft_reduce_seg.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t,
                                   u32p, u32p]
    lib.cft_reduce_seg.restype = ctypes.c_int

    dev = ctypes.c_void_p()
    art = args.artifact.encode() if args.artifact else None
    st = lib.cft_open(art, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}: "
                         f"{lib.cft_last_error().decode()}")

    # Small integers, so every segment's sum is exact at every format
    # (192 x 97 < 2^15; the whole array, 2^24 x 97 < 2^31) and a maximum
    # is one of them.
    vals = [(k % 97) + 1 for k in range(N)]
    t0 = time.perf_counter()
    enc = b"".join(sf.from_int(fmt, v)[0].to_bytes(esz, "little") for v in vals) \
        if esz != 8 else b"".join(__import__("struct").pack("<d", float(v)) for v in vals)
    t_enc = time.perf_counter() - t0

    a_buf = ctypes.c_void_p()
    d_buf = ctypes.c_void_p()
    for buf, nbytes in ((a_buf, N * esz), (d_buf, E * esz)):
        st = lib.cft_alloc(dev, nbytes, ctypes.byref(buf))
        if st != CFT_OK:
            raise SystemExit(f"cft_alloc({nbytes}): {lib.cft_strerror(st).decode()}: "
                             f"{lib.cft_last_error().decode()}")
    a_ptr = lib.cft_buffer_data(a_buf)
    d_ptr = lib.cft_buffer_data(d_buf)
    ctypes.memmove(a_ptr, enc, N * esz)
    t0 = time.perf_counter()
    st = lib.cft_buffer_to_device(a_buf)
    t_up = time.perf_counter() - t0
    if st != CFT_OK:
        raise SystemExit(f"cft_buffer_to_device: {lib.cft_strerror(st).decode()}")

    flags = ctypes.c_uint32(0)
    bus = ctypes.c_uint32(0)
    times = []
    for _ in range(max(1, args.reps)):
        t0 = time.perf_counter()
        st = lib.cft_reduce_seg(dev, OP_CODE[args.op], FMT_CODE[args.format], 0,
                                a_ptr, None, d_ptr, N, L, ctypes.byref(flags),
                                ctypes.byref(bus))
        times.append(time.perf_counter() - t0)
        if st != CFT_OK:
            raise SystemExit(f"cft_reduce_seg: {lib.cft_strerror(st).decode()}: "
                             f"{lib.cft_last_error().decode()}")
    t0 = time.perf_counter()
    lib.cft_buffer_from_device(d_buf)
    t_down = time.perf_counter() - t0
    got = ctypes.string_at(d_ptr, E * esz)
    bad = 0
    for s in range(E):
        seg = vals[s * L:(s + 1) * L]
        want = sum(seg) if args.op == "sum" else max(seg)
        w = sf.from_int(fmt, want)[0].to_bytes(esz, "little") if esz != 8 \
            else __import__("struct").pack("<d", float(want))
        if got[s * esz:(s + 1) * esz] != w:
            bad += 1
    med = statistics.median(times)
    print(f"{args.format} {args.op}: N={N} in E={E} segments of L={L}, resident, "
          f"{len(times)} reps (encode {t_enc:.1f} s, upload {t_up * 1e3:.1f} ms, "
          f"readback {t_down * 1e3:.1f} ms)")
    print(f"  one call   median {med * 1e6:10.1f} us   min {min(times) * 1e6:10.1f} us   "
          f"{N / med / 1e6:8.1f} M elements/s   {N * esz / med / 1e9:6.2f} GB/s of operand")
    print(f"  results    {E - bad}/{E} exact   flags {flags.value:#x}   status {bus.value:#x}")
    lib.cft_buffer_free(a_buf)
    lib.cft_buffer_free(d_buf)
    lib.cft_close(dev)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
