# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Did the lane mask reach the LANES, or only the STROBES?

    python host/tools/maskflags.py [--format fp32] [--lanes 48]
                                   [--artifact IMAGE]

A card-day instrument (2026-09-15). The round-2 image wrote every
masked lane's deposit slot with the value the lane computed, while the
register trace showed the tile had the bit, the pointer and the bytes,
and a read of a bogus mask address faulted - so the tile READ the
mask. Two things could then be true, and they leave different marks in
FLAGS:

  * the mask never reached the lanes (the slice of the beat, or its
    capture, built wrong): every lane is active, so a MASKED lane's
    exception reaches FLAGS exactly as an unmasked one's does;
  * the mask reached the lanes and only the drains' byte strobes were
    lost on the way to memory: a masked lane is not active, so its
    exception does NOT reach FLAGS (docs/SEQUENCER.md R17), and the
    deposit bytes are the only thing wrong.

So: one dense program, `ADD r3 = a + c; DEPOSIT r3; HALT`, with the
KEPT lanes exact (1 + 2) and the MASKED lanes poisoned (+inf + -inf,
which is INVALID). Run unmasked (FLAGS must show INVALID) and masked
(FLAGS must be clean if the mask reached the lanes). The deposit slots
and the counts of the masked lanes are printed beside it, with what
each holds.
"""

import argparse
import ctypes
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "host" / "tools"))

from cft_golden import FORMATS  # noqa: E402
from cft_golden import seq  # noqa: E402
from cft_golden import softfloat as sf  # noqa: E402
from gathertime import CFT_OK, RunArgs, load_library  # noqa: E402

FLAG_NAMES = [(sf.FLAG_INVALID, "INVALID"), (sf.FLAG_DIVZERO, "DIVZERO"),
              (sf.FLAG_OVERFLOW, "OVERFLOW"),
              (sf.FLAG_UNDERFLOW, "UNDERFLOW"),
              (sf.FLAG_INEXACT, "INEXACT")]


def flag_str(v):
    names = [n for b, n in FLAG_NAMES if v & b]
    return f"{v:#04x} ({' '.join(names) if names else 'clean'})"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--format", default="fp32", choices=["fp32", "fp64",
                                                         "fp128", "fp256"])
    ap.add_argument("--lanes", type=int, default=48)
    ap.add_argument("--masked-every", type=int, default=2)
    ap.add_argument("--artifact", default=None)
    args = ap.parse_args()

    fmt = FORMATS[args.format]
    esz = fmt.width // 8
    n = args.lanes
    K = args.masked_every

    lib = load_library()
    dev = ctypes.c_void_p()
    art = args.artifact.encode() if args.artifact else None
    st = lib.cft_open(art, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}: "
                         f"{lib.cft_last_error().decode()}")

    insns = [seq.alu(sf.OP_ADD, rd=3, ra=0, rc=2), seq.deposit(3),
             seq.halt()]
    prog = seq.Program(fmt, insns, [], max_deposits=1)
    image = prog.to_bytes()
    handle = ctypes.c_void_p()
    st = lib.cft_program_load(dev, image, len(image), ctypes.byref(handle))
    if st != CFT_OK:
        raise SystemExit(f"cft_program_load: "
                         f"{lib.cft_strerror(st).decode()}: "
                         f"{lib.cft_last_error().decode()}")

    one = sf.from_int(fmt, 1)[0]
    two = sf.from_int(fmt, 2)[0]
    three = sf.from_int(fmt, 3)[0]
    pinf = sf.inf_bits(fmt, 0)
    ninf = sf.inf_bits(fmt, 1)
    masked = [i % K == 0 for i in range(n)]
    a_vals = [pinf if masked[i] else one for i in range(n)]
    c_vals = [ninf if masked[i] else two for i in range(n)]
    buf_a = ctypes.create_string_buffer(
        b"".join(v.to_bytes(esz, "little") for v in a_vals), n * esz)
    buf_c = ctypes.create_string_buffer(
        b"".join(v.to_bytes(esz, "little") for v in c_vals), n * esz)
    buf_b = ctypes.create_string_buffer(n * esz)
    buf_dep = ctypes.create_string_buffer(n * esz)
    counts = (ctypes.c_uint32 * n)()
    flags = ctypes.c_uint32(0)
    bus = ctypes.c_uint32(0)
    mbytes = (n + 7) // 8
    mask = bytearray(mbytes)
    for i in range(n):
        if not masked[i]:
            mask[i >> 3] |= 1 << (i & 7)
    buf_mask = ctypes.create_string_buffer(bytes(mask), mbytes)

    A = RunArgs()
    A.struct_size = ctypes.sizeof(RunArgs)
    A.a = ctypes.cast(buf_a, ctypes.c_void_p)
    A.b = ctypes.cast(buf_b, ctypes.c_void_p)
    A.c = ctypes.cast(buf_c, ctypes.c_void_p)
    A.n = n
    A.deposits = ctypes.cast(buf_dep, ctypes.c_void_p)
    A.counts = counts
    A.flags_out = ctypes.pointer(flags)
    A.bus_out = ctypes.pointer(bus)

    pat = int.from_bytes(bytes([0x5A]) * esz, "little")

    def run(label, with_mask):
        ctypes.memset(buf_dep, 0x5A, n * esz)
        for i in range(n):
            counts[i] = 0x77777777
        flags.value = 0
        bus.value = 0
        A.lane_mask = ctypes.cast(buf_mask, ctypes.c_void_p) if with_mask \
            else None
        A.lane_mask_bytes = mbytes if with_mask else 0
        st = lib.cft_program_run_ex(handle, ctypes.byref(A))
        if st != CFT_OK:
            raise SystemExit(f"cft_program_run_ex ({label}): "
                             f"{lib.cft_strerror(st).decode()}: "
                             f"{lib.cft_last_error().decode()}")
        got = [int.from_bytes(buf_dep.raw[i * esz:(i + 1) * esz], "little")
               for i in range(n)]
        m_idx = [i for i in range(n) if masked[i]]
        k_idx = [i for i in range(n) if not masked[i]]
        kept_ok = sum(1 for i in k_idx if got[i] == three)
        m_pat = sum(1 for i in m_idx if got[i] == pat)
        m_cnt_pat = sum(1 for i in m_idx if counts[i] == 0x77777777)
        m_cnt_one = sum(1 for i in m_idx if counts[i] == 1)
        print(f"{label}:")
        print(f"  FLAGS {flag_str(flags.value)}   STATUS {bus.value:#x}")
        print(f"  kept lanes: {kept_ok} of {len(k_idx)} deposit 3")
        print(f"  masked lanes: {m_pat} of {len(m_idx)} deposit slots hold "
              f"the pattern; {len(m_idx) - m_pat} were written "
              f"(first masked lane holds {got[m_idx[0]]:#x})")
        print(f"  masked lanes' counts: {m_cnt_pat} hold the pattern, "
              f"{m_cnt_one} hold 1, "
              f"{len(m_idx) - m_cnt_pat - m_cnt_one} something else")
        return flags.value

    f_un = run("UNMASKED run, masked-to-be lanes poisoned", False)
    f_ma = run(f"MASKED run, every {K}th lane masked", True)
    print()
    if not (f_un & sf.FLAG_INVALID):
        print("VERDICT: the poison did not raise INVALID unmasked - the probe "
              "is wrong, not the tile")
        return 2
    if f_ma & sf.FLAG_INVALID:
        print("VERDICT: a MASKED lane's INVALID reached FLAGS - the mask never "
              "reached the lanes (the beat's slice or its capture)")
        return 1
    print("VERDICT: FLAGS is clean under the mask - the mask reached the "
          "lanes; what is lost is the drains' byte strobes on the way to "
          "memory")
    return 0


if __name__ == "__main__":
    sys.exit(main())
