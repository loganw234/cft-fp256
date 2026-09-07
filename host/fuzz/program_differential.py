# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Two loaders, one pile of bytes: does either take an image the other
refuses?

    python3 host/fuzz/program_differential.py [--trials 200000]
                                              [--dir host/fuzz/corpus/program]

docs/SEQUENCER.md's "What the loader refuses" is the specification;
python/cft_golden/seq.py is the executable form of it and the authority;
host/src/program.c is the C port that a device actually loads through,
and docs/REMOTE.md's PROG_LOAD hands it bytes off a socket. Two
validators that disagree about what is legal are a device executing
something the host believed it had rejected - the failure
host/tests/seq_check.py already looks for over VALID programs and their
deliberate corruptions. This looks for it over bytes neither was
written with in mind.

The difference from seq_check.py's refusal arm is where the images come
from. There they are built by the model's own encoder and then broken
in one of nine named ways; here they are mutated bytes, repaired only
far enough to get past the header, so the mutation reaches fields no
named corruption thought to touch - which is how the multiplication in
seq_validate's worst-case bound was found to wrap.

A mismatch is printed with the image in hex and written to
host/fuzz/crashes/program-differential/ so it can be replayed.
"""

import argparse
import ctypes
import random
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import FORMATS            # noqa: E402
from cft_golden import seq                # noqa: E402

CFT_OK = 0
MAGIC = 0x50544643
HDR = 32
PREC_ESZ = {0: 4, 1: 8, 2: 16, 3: 32}


def load_library():
    name = {"win32": "cft.dll", "cygwin": "cft.dll",
            "darwin": "libcft.dylib"}.get(sys.platform, "libcft.so")
    path = ROOT / "host" / name
    if not path.exists():
        raise SystemExit(f"{path} not found - run `make -C host` first")
    lib = ctypes.CDLL(str(path))
    lib.cft_open.argtypes = [ctypes.c_char_p, ctypes.c_int,
                             ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_open.restype = ctypes.c_int
    lib.cft_close.argtypes = [ctypes.c_void_p]
    lib.cft_program_load.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                     ctypes.c_size_t,
                                     ctypes.POINTER(ctypes.c_void_p)]
    lib.cft_program_load.restype = ctypes.c_int
    lib.cft_program_free.argtypes = [ctypes.c_void_p]
    lib.cft_strerror.argtypes = [ctypes.c_int]
    lib.cft_strerror.restype = ctypes.c_char_p
    return lib


def c_accepts(lib, dev, image):
    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st == CFT_OK:
        lib.cft_program_free(handle)
        return True, "ok"
    return False, lib.cft_strerror(st).decode()


def model_accepts(image):
    try:
        seq.Program.from_bytes(image)
        return True, "ok"
    except (seq.ProgramError, struct.error, ValueError, IndexError) as exc:
        return False, str(exc)[:120]


def repair(image, rng):
    """Put a mutated image back into a shape the header check accepts,
    so the mutation is spent on the instruction stream rather than on
    the magic number. The same job fuzz_program.c's fixup does, in
    Python, because this script mutates in Python."""
    b = bytearray(image)
    if len(b) < HDR:
        b += bytes(HDR - len(b))
    prec = b[20] & 3
    struct.pack_into("<8I", b, 0, MAGIC, 1, 0, 0,
                     struct.unpack_from("<I", b, 16)[0], prec, 0, 0)
    esz = PREC_ESZ[prec]
    n_consts = rng.randrange(4)
    if HDR + n_consts * esz > len(b):
        n_consts = 0
    n_insns = (len(b) - HDR - n_consts * esz) // 8
    struct.pack_into("<II", b, 8, n_insns, n_consts)
    want = HDR + n_consts * esz + n_insns * 8
    return bytes(b[:want]) + bytes(max(0, want - len(b)))


def mutate(image, rng):
    b = bytearray(image)
    for _ in range(1 + rng.randrange(6)):
        what = rng.randrange(7)
        if not b:
            b = bytearray(HDR)
        if what == 0:
            i = rng.randrange(len(b))
            b[i] ^= 1 << rng.randrange(8)
        elif what == 1:
            i = rng.randrange(len(b))
            b[i] = rng.randrange(256)
        elif what == 2 and len(b) >= 8:
            i = rng.randrange(len(b) - 7)
            struct.pack_into("<Q", b, i, rng.choice(
                [0, 1, 2, 3, 4, 7, 8, 1 << 16, 1 << 17, 1 << 20, 1 << 24,
                 1 << 31, (1 << 32) - 1, 1 << 32, (1 << 64) - 1,
                 rng.getrandbits(64)]))
        elif what == 3 and len(b) >= 4:
            i = rng.randrange(len(b) - 3)
            struct.pack_into("<I", b, i, rng.choice(
                [0, 1, 2, 3, 15, 16, 1 << 20, (1 << 20) + 1, 1 << 24,
                 1 << 31, (1 << 32) - 1, rng.getrandbits(32)]))
        elif what == 4:
            b += bytes(8 * (1 + rng.randrange(4)))
        elif what == 5 and len(b) > 40:
            del b[-8 * (1 + rng.randrange(3)):]
        else:                                     # a whole instruction word
            if len(b) >= HDR + 8:
                slot = HDR + 8 * rng.randrange((len(b) - HDR) // 8)
                if slot + 8 <= len(b):
                    ctrl = rng.random() < 0.5
                    op = (rng.randrange(6) if ctrl else
                          rng.choice([0, 1, 2, 3, 8, 16, 24, 200]))
                    imm = rng.choice([0, 1, 2, 4, 1 << 16, 1 << 17, 1 << 20,
                                      1 << 24, 1 << 31, (1 << 32) - 1])
                    w = (op | (rng.randrange(16) << 8) |
                         (rng.randrange(16) << 12) |
                         (rng.randrange(16) << 16) |
                         (rng.randrange(16) << 20) |
                         (rng.randrange(8) << 24) |
                         (int(ctrl) << 31) | (imm << 32))
                    struct.pack_into("<Q", b, slot, w & ((1 << 64) - 1))
    return bytes(b)


def seeds():
    out = []
    rng = random.Random(4919)
    for name in ("fp32", "fp64", "fp128", "fp256"):
        fmt = FORMATS[name]
        for _ in range(4):
            insns, consts = seq.random_program(fmt, rng)
            try:
                out.append(seq.Program(fmt, insns, consts,
                                       rng.choice([0, 1, 2])).to_bytes())
            except seq.ProgramError:
                pass
    d = HERE / "corpus" / "program"
    if d.is_dir():
        out += [p.read_bytes() for p in sorted(d.iterdir()) if p.is_file()]
    return out or [struct.pack("<8I", MAGIC, 1, 0, 0, 1, 0, 0, 0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=200000)
    ap.add_argument("--seed", type=int, default=20260907)
    ap.add_argument("--dir", action="append", default=[],
                    help="also compare every file in this directory")
    args = ap.parse_args()

    lib = load_library()
    dev = ctypes.c_void_p()
    st = lib.cft_open(None, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}")

    out = HERE / "crashes" / "program-differential"
    rng = random.Random(args.seed)
    pool = seeds()
    both_accept = both_refuse = 0
    mismatches = 0
    checked = 0

    corpus = []
    for d in args.dir:
        corpus += [p.read_bytes() for p in sorted(Path(d).iterdir())
                   if p.is_file()]

    def compare(image, why):
        nonlocal both_accept, both_refuse, mismatches, checked
        checked += 1
        c_ok, c_msg = c_accepts(lib, dev, image)
        m_ok, m_msg = model_accepts(image)
        if c_ok == m_ok:
            if c_ok:
                both_accept += 1
            else:
                both_refuse += 1
            return
        mismatches += 1
        out.mkdir(parents=True, exist_ok=True)
        name = f"diff-{mismatches:04d}-{'C-accepts' if c_ok else 'model-accepts'}"
        (out / name).write_bytes(image)
        if mismatches <= 5:
            print(f"  MISMATCH ({why}) -> host/fuzz/crashes/"
                  f"program-differential/{name}")
            print(f"    libcft: {'ACCEPT' if c_ok else 'REFUSE ' + c_msg}")
            print(f"    model : {'ACCEPT' if m_ok else 'REFUSE ' + m_msg}")
            print(f"    image : {image.hex()}")

    for image in corpus:
        compare(image, "corpus file")
    for i in range(args.trials):
        image = mutate(rng.choice(pool), rng)
        if rng.random() < 0.85:
            image = repair(image, rng)
        compare(image, "mutation")
        if len(pool) < 400 and rng.random() < 0.002:
            pool.append(image)

    lib.cft_close(dev)
    print(f"\n{checked} images through both loaders: "
          f"{both_accept} accepted by both, {both_refuse} refused by both, "
          f"{mismatches} disagreements")
    if not both_accept:
        print("NO IMAGE WAS ACCEPTED - the mutation never produced a valid "
              "program, so half of this check did not run")
        return 1
    if mismatches:
        print(f"{mismatches} DISAGREEMENTS - see host/fuzz/crashes/"
              f"program-differential")
        return 1
    print("libcft and the golden model take and refuse exactly the same "
          "images")
    return 0


if __name__ == "__main__":
    sys.exit(main())
