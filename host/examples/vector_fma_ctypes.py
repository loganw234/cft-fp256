# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The same program as vector_fma.c, in Python, through ctypes.

    python3 host/examples/vector_fma_ctypes.py [artifact.xclbin]

It must print exactly what the C program prints - every line, every
digit. Two things follow from that, and they are the reason this file
exists rather than being a paragraph in the documentation:

* Reaching the library from another language costs a ctypes.CDLL and
  eight argtypes. No binding generator, no build step, no compiler on
  the user's machine, no pyxrt.

* The port is a shim. Nothing about the arithmetic is reimplemented
  here, so there is no second implementation to drift - which is how
  "identical bits" usually stops being true, quietly, in the edge
  cases, months later.

`make -C host test` diffs the two outputs, so the claim is checked
rather than asserted.
"""

import ctypes
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

FMA, RNE = 0, 0
N = 4096
GEOM = [
    # width, exp_w, man_w, bias
    (32, 8, 23, 127),
    (64, 11, 52, 1023),
    (128, 15, 112, 16383),
    (256, 19, 236, 262143),
]
NAMES = ["fp32", "fp64", "fp128", "fp256"]


def library_path():
    """Exactly one candidate, chosen by platform.

    Listing every name and taking the first that exists looks tolerant
    and is not: a repository checked out on a shared volume and built
    from two platforms ends up holding both, and the fallback then
    loads the foreign one and fails with "invalid ELF header" instead
    of "build it first"."""
    override = os.environ.get("CFT_LIB")
    if override:
        return Path(override)
    name = {"win32": "cft.dll", "cygwin": "cft.dll",
            "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
    return ROOT / "host" / name


def load():
    path = library_path()
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make -C host` first")
    lib = ctypes.CDLL(str(path))

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
    lib.cft_supports.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    lib.cft_supports.restype = ctypes.c_int
    lib.cft_format_size.argtypes = [ctypes.c_int]
    lib.cft_format_size.restype = ctypes.c_size_t
    lib.cft_strerror.argtypes = [ctypes.c_int]
    lib.cft_strerror.restype = ctypes.c_char_p
    return lib


class Rng:
    """xorshift32, one step per byte - the same stream vector_fma.c
    generates, which is what lets the two checksums be compared."""

    def __init__(self, seed):
        self.s = seed or 1

    def byte(self):
        s = self.s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        self.s = s
        return s & 0xFF


def make_element(rng, width, exp_w, man_w, bias):
    nb = width // 8
    e = bytearray(rng.byte() for _ in range(nb))
    ef = bias - 32 + (rng.byte() & 63)
    kb, rb = man_w // 8, man_w % 8
    e[kb] &= (1 << rb) - 1
    for k in range(kb + 1, nb):
        e[k] = 0
    for j in range(exp_w):
        if (ef >> j) & 1:
            e[(man_w + j) // 8] |= 1 << ((man_w + j) % 8)
    if rng.byte() & 1:
        e[nb - 1] |= 0x80
    return bytes(e)


def fnv1a(data):
    h = 0xCBF29CE484222325
    for byte in data:
        h = ((h ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def main():
    artifact = sys.argv[1].encode() if len(sys.argv) > 1 else None
    lib = load()

    dev = ctypes.c_void_p()
    st = lib.cft_open(artifact, 0, ctypes.byref(dev))
    if st != 0:
        raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}")
    print(f"cft-fp256 vector fma, "
          f"{artifact.decode() if artifact else 'software'} backend")

    for f, (width, exp_w, man_w, bias) in enumerate(GEOM):
        if not lib.cft_supports(dev, FMA, f):
            print(f"{NAMES[f]:<6} not available on this device")
            continue
        esz = lib.cft_format_size(f)
        rng = Rng(0x1234567 + f)
        a, b, c = bytearray(), bytearray(), bytearray()
        for _ in range(N):
            a += make_element(rng, width, exp_w, man_w, bias)
            b += make_element(rng, width, exp_w, man_w, bias)
            c += make_element(rng, width, exp_w, man_w, bias)

        buf_a = ctypes.create_string_buffer(bytes(a), len(a))
        buf_b = ctypes.create_string_buffer(bytes(b), len(b))
        buf_c = ctypes.create_string_buffer(bytes(c), len(c))
        buf_d = ctypes.create_string_buffer(N * esz)
        flags = ctypes.c_uint32(0)
        st = lib.cft_run(dev, FMA, f, RNE, buf_a, buf_b, buf_c, buf_d, N,
                         ctypes.byref(flags), None)
        if st != 0:
            raise SystemExit(f"cft_run: {lib.cft_strerror(st).decode()}")

        print(f"{NAMES[f]:<6} n={N} rne  "
              f"checksum 0x{fnv1a(buf_d.raw):016x}  "
              f"flags 0x{flags.value:02x}")

    lib.cft_close(dev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
