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
on what a program is; nothing here hand-assembles an image - with the
one temporary exception rev2_seeds() states and explains.
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
    "PROG_RUN_BANK": 0x0023,
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
    # "CFTP", not the frame's "CFTR": this seed is named for an image
    # with no constants and no instructions, and with the wrong magic
    # it was only ever a second copy of "the magic is checked".
    write("program", "header-only",
          struct.pack("<8I", PROG_MAGIC, 1, 0, 0, 1, 0, 0, 0))
    return n + 2 + rev2_seeds()


# --- revision 2's shapes (docs/SEQUENCER.md, 2026-09-08) -------------
#
# ASSEMBLED HERE rather than asked of the model, which is the one
# exception to this file's rule and is temporary. The model's half of
# the 2026-09-08 round - NREG 32, the header's flags word, run() taking
# a bank - is a separate change landing beside this one, and a seed
# corpus that waits for it is a corpus that does not cover the parser
# the round just changed. When seq.py emits these shapes, delete the
# assembly below and ask it instead; the images must come out
# byte-identical, which is a test worth writing at that moment.
#
# The encodings are docs/SEQUENCER.md's, restated once:
#   bits 7:0 op | 11:8 rd | 15:12 ra | 19:16 rb | 23:20 rc | 26:24 rnd
#   27 ka | 28 kb | 29 kc | 30 kx | 31 ctrl | 63:32 imm
#   imm[24] rd[4] | imm[25] ra[4] | imm[26] rb[4] | imm[27] rc[4]
#
# "CFTP", the PROGRAM magic - not MAGIC above, which is "CFTR" and
# belongs to the remote frame. Derived from the four bytes rather than
# typed as a number, so the two cannot disagree.
PROG_MAGIC = int.from_bytes(b"CFTP", "little")
BANK_EXT = 1


def _alu(op, rd, ra=0, rb=0, rc=0, rnd=0, ka=0, kb=0, kc=0):
    imm = ((rd >> 4) & 1) << 24
    if not ka:
        imm |= ((ra >> 4) & 1) << 25
    if not kb:
        imm |= ((rb >> 4) & 1) << 26
    if not kc:
        imm |= ((rc >> 4) & 1) << 27
    return (op | ((rd & 15) << 8) | ((ra & 15) << 12) | ((rb & 15) << 16) |
            ((rc & 15) << 20) | (rnd << 24) | (ka << 27) | (kb << 28) |
            (kc << 29) | (imm << 32))


def _ctrl(code, ra=0, imm=0):
    return (code | ((ra & 15) << 12) | (1 << 31) |
            ((imm | (((ra >> 4) & 1) << 25)) << 32))


def _image(fmt_code, insns, consts, esz, max_deposits, flags=0):
    body = b"".join(struct.pack("<Q", w) for w in insns)
    kon = b"" if flags & BANK_EXT else b"".join(consts)
    return struct.pack("<8I", PROG_MAGIC, 1, len(insns), len(consts),
                       max_deposits, fmt_code, flags, 0) + kon + body


def rev2_seeds():
    n = 0
    for code, fname in enumerate(("fp32", "fp64", "fp128", "fp256")):
        esz = 4 << code
        zero = b"\x00" * esz
        # r16 = r0*r1 + r2; r17 = r16 + r0; deposit r17; deposit r16; halt
        wide = [_alu(0, 16, 0, 1, 2), _alu(1, 17, 16, 0, 0),
                _ctrl(3, 17), _ctrl(3, 16), _ctrl(0)]
        write("program", f"regs32-{fname}",
              _image(code, wide, [], esz, 2))
        n += 1
        # r31 through a loop, with SETACT and DEPOSIT naming it - the
        # only two control codes whose imm may carry a register bit
        loop = [_alu(0, 31, 0, 1, 2), _ctrl(1, 0, 3),
                _alu(3, 31, 31, 31), _ctrl(3, 31), _ctrl(4, 31),
                _ctrl(2), _ctrl(0)]
        write("program", f"regs32-loop-{fname}",
              _image(code, loop, [], esz, 4))
        n += 1
        # BANK_EXT: no constant section, two constants addressed
        ext = [_alu(0, 4, 0, 0, 1, 0, 0, 1, 1), _ctrl(3, 4), _ctrl(0)]
        write("program", f"bankext-{fname}",
              _image(code, ext, [zero, zero], esz, 1, BANK_EXT))
        n += 1
    # And the two the loader must refuse, so the new refusal paths are
    # seeded as the old ones are: a flag bit nothing assigns, and a
    # BANK_EXT image that still carries its constant section.
    esz = 4
    ext = [_alu(0, 4, 0, 0, 1, 0, 0, 1, 1), _ctrl(3, 4), _ctrl(0)]
    write("program", "flags-unassigned-fp32",
          _image(0, ext, [b"\x00" * esz] * 2, esz, 1, 2))
    img = _image(0, ext, [b"\x00" * esz] * 2, esz, 1)
    write("program", "bankext-with-consts-fp32",
          img[:24] + struct.pack("<I", BANK_EXT) + img[28:])
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

    # PROG_RUN_BANK: the fourth fixed word is the bank's byte length,
    # and the bank itself sits between the fixed fields and the
    # operands. Two fp32 constants, so eight bytes (ABI 0.9).
    bext = _image(0, [_alu(0, 4, 0, 0, 1, 0, 0, 1, 1), _ctrl(3, 4),
                      _ctrl(0)], [b"\x00" * esz] * 2, esz, 1, BANK_EXT)
    prunb = struct.pack("<IIIIQ", 1, 1, 1, 2 * esz, n) + \
        b"\x00" * (2 * esz) + b"\x00" * (n * esz)
    write("serve", "prog-bank-run",
          rec(OP["HELLO"]) + rec(OP["PROG_LOAD"], bext) +
          rec(OP["PROG_RUN_BANK"], prunb) +
          rec(OP["PROG_FREE"], struct.pack("<I", 1)))
    n += 1

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
