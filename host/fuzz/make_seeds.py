# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Write the seed corpora the three in-process harnesses start from.

    python3 host/fuzz/make_seeds.py

A mutation fuzzer with no seeds spends its budget rediscovering the
magic number. These seeds are the shapes the protocol and the loader
actually see - a HELLO, a RUN with each operand mask, a program that
loads, a program that must not - so the first mutation is already a
mutation of something the parser gets past its first check.

The program seeds come from python/cft_golden, which is the authority
on what a program is; nothing here hand-assembles an image.
"""

import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS            # noqa: E402
from cft_golden import seq                # noqa: E402
from cft_golden import seqprogs           # noqa: E402

HERE = Path(__file__).resolve().parent

# --- the frame protocol, as docs/REMOTE.md lays it out ---------------
MAGIC = 0x52544643
PROTO = 1
HDR = 32
OP = {
    "HELLO": 0x0001, "CAPS": 0x0002, "STATS": 0x0003,
    "RUN": 0x0010, "REDUCE": 0x0011,
    "PROG_LOAD": 0x0020, "PROG_RUN": 0x0021, "PROG_FREE": 0x0022,
    "BUF_ALLOC": 0x0030, "BUF_FREE": 0x0031, "BUF_WRITE": 0x0032,
    "BUF_READ": 0x0033,
    "FLAGS_LOWER": 0x0040, "FLAGS_RAISE": 0x0041, "FLAGS_TEST": 0x0042,
    "FLAGS_SAVE": 0x0043, "FLAGS_RESTORE": 0x0044,
    "FLAGS_TEST_SAVED": 0x0045, "BYE": 0x00FF,
}


def write(sub, name, data):
    d = HERE / "corpus" / sub
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)


# --- fuzz_program: whole images --------------------------------------

def program_seeds():
    rng = random.Random(20260907)
    n = 0
    for fname in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[fname]
        for k in range(3):
            insns, consts = seq.random_program(fmt, rng)
            try:
                p = seq.Program(fmt, insns, consts, rng.choice([0, 1, 2, 4]))
            except seq.ProgramError:
                continue
            write("program", f"rand-{fname}-{k}", p.to_bytes())
            n += 1
        write("program", f"div-{fname}", seqprogs.div_program(fmt).to_bytes())
        write("program", f"sqrt-{fname}", seqprogs.sqrt_program(fmt).to_bytes())
        n += 2
    # An image the loader must refuse, so the refusal paths are seeded
    # too: an endrep with no repeat.
    bogus = seq.Program.__new__(seq.Program)
    bogus.fmt, bogus.insns = FORMATS["fp32"], [seq.endrep()]
    bogus.consts, bogus.max_deposits = [], 1
    write("program", "unbalanced-fp32", bogus.to_bytes())
    write("program", "header-only", struct.pack("<8I", MAGIC, 1, 0, 0, 1, 0,
                                                0, 0))
    return n + 2


# --- fuzz_serve: u16 op | u32 len | payload --------------------------

def rec(op, payload=b""):
    return struct.pack("<HI", op, len(payload)) + payload


def serve_seeds():
    prog = seqprogs.div_program(FORMATS["fp32"]).to_bytes()
    tiny = seq.Program(FORMATS["fp32"], [seq.halt()], [], 1).to_bytes()
    esz = 4
    n = 8

    write("serve", "hello", rec(OP["HELLO"]))
    write("serve", "hello-stats-bye",
          rec(OP["HELLO"]) + rec(OP["STATS"]) + rec(OP["BYE"]))
    for mask, nops in ((1, 1), (3, 2), (7, 3)):
        body = struct.pack("<IIIIQ", 1, 0, 0, mask, n) + \
            b"\x00" * (nops * n * esz)
        write("serve", f"run-mask{mask}", rec(OP["HELLO"]) + rec(OP["RUN"],
                                                                body))
    body = struct.pack("<IIIIQ", 24, 0, 0, 1, n) + b"\x00" * (n * esz)
    write("serve", "reduce", rec(OP["HELLO"]) + rec(OP["REDUCE"], body))

    prun = struct.pack("<IIIIQ", 1, 1, 1, 0, n) + b"\x00" * (n * esz)
    write("serve", "prog-load-run",
          rec(OP["HELLO"]) + rec(OP["PROG_LOAD"], prog) +
          rec(OP["PROG_RUN"], prun) + rec(OP["PROG_FREE"],
                                          struct.pack("<I", 1)))
    write("serve", "prog-tiny",
          rec(OP["HELLO"]) + rec(OP["PROG_LOAD"], tiny) +
          rec(OP["PROG_RUN"], prun))

    write("serve", "buffers",
          rec(OP["HELLO"]) + rec(OP["BUF_ALLOC"], struct.pack("<Q", 256)) +
          rec(OP["BUF_WRITE"], struct.pack("<IIQ", 1, 0, 0) + b"\xa5" * 64) +
          rec(OP["BUF_READ"], struct.pack("<IIQQ", 1, 0, 0, 64)) +
          rec(OP["BUF_FREE"], struct.pack("<I", 1)))

    write("serve", "flags",
          rec(OP["HELLO"]) +
          rec(OP["FLAGS_RAISE"], struct.pack("<I", 0x1F)) +
          rec(OP["FLAGS_TEST"], struct.pack("<I", 0x1F)) +
          rec(OP["FLAGS_SAVE"]) +
          rec(OP["FLAGS_RESTORE"], struct.pack("<II", 0x1F, 0x1F)) +
          rec(OP["FLAGS_TEST_SAVED"], struct.pack("<II", 0x1F, 0x1F)) +
          rec(OP["FLAGS_LOWER"], struct.pack("<I", 0x1F)))
    return 11


# --- fuzz_client: mode | patch | a stream of reply frames ------------

CRC_TABLE = []


def crc32(seed, data):
    if not CRC_TABLE:
        for i in range(256):
            c = i
            for _ in range(8):
                c = (0xEDB88320 ^ (c >> 1)) if (c & 1) else (c >> 1)
            CRC_TABLE.append(c)
    c = seed ^ 0xFFFFFFFF
    for b in data:
        c = CRC_TABLE[(c ^ b) & 0xFF] ^ (c >> 8)
    return c ^ 0xFFFFFFFF


def frame(kind, abi, fid, op, status, payload):
    """One frame, laid out as cftr_hdr_pack lays it out."""
    h = struct.pack("<IHHIIHHIII", MAGIC, PROTO, kind, abi, fid, op,
                    status, len(payload), 0, 0)
    assert len(h) == HDR, len(h)
    c = crc32(0, h)
    if payload:
        c = crc32(c, payload)
    return h[:24] + struct.pack("<I", c) + h[28:] + payload


def client_seeds(abi):
    # mode 1: cft_run over 4 fp32 elements -> flags, bus, 16 bytes
    body = struct.pack("<II", 0, 0) + b"\x00" * 16
    write("client", "run-ok",
          bytes([1, 31]) + frame(1, abi, 1, OP["RUN"], 0, body))
    write("client", "run-short",
          bytes([1, 31]) + frame(1, abi, 1, OP["RUN"], 0, body[:8]))
    write("client", "run-refusal",
          bytes([1, 31]) + frame(2, abi, 1, OP["RUN"], 5, b"no\x00"))
    # mode 2: cft_reduce -> flags, bus, one element
    write("client", "reduce-ok",
          bytes([2, 31]) + frame(1, abi, 1, OP["REDUCE"], 0,
                                 struct.pack("<II", 0, 0) + b"\x00" * 4))
    # mode 3: PROG_LOAD's 16 bytes then PROG_RUN's deposits and counts
    pl = struct.pack("<IIII", 1, 0, 1, 0)
    pr = struct.pack("<II", 0, 0) + b"\x00" * 16 + b"\x00" * 16
    write("client", "prog-ok",
          bytes([3, 31]) + frame(1, abi, 1, OP["PROG_LOAD"], 0, pl) +
          frame(1, abi, 2, OP["PROG_RUN"], 0, pr))
    # mode 0: raw framing
    write("client", "frame-hello",
          bytes([0, 31]) + frame(1, abi, 1, OP["HELLO"], 0, b"\x00" * 56))
    write("client", "frame-empty", bytes([0, 0]) + b"\x00" * 32)
    return 7


def main():
    abi = 0
    # The ABI the harness will demand back. Read it from the library if
    # it is built; otherwise leave it zero and let the harness's own
    # repair pass fix the field.
    try:
        import ctypes
        name = {"win32": "cft.dll"}.get(sys.platform, "libcft.so")
        lib = ctypes.CDLL(str(ROOT / "host" / name))
        lib.cft_abi_version.restype = ctypes.c_uint32
        abi = lib.cft_abi_version()
    except OSError:
        print("libcft not built; client seeds carry abi 0")
    print(f"{program_seeds()} program seeds")
    print(f"{serve_seeds()} serve seeds")
    print(f"{client_seeds(abi)} client seeds (abi {abi >> 16}.{abi & 0xFFFF})")


if __name__ == "__main__":
    main()
