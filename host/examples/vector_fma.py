# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Minimal pyxrt host: run one vector op on the tile and verify every
element against the golden model.

    python3 host/examples/vector_fma.py build/cft_hw.xclbin \
        --format fp256 --op fma --n 4096

The host contract (docs/ARCHITECTURE.md): buffers are 32-byte aligned
(XRT BOs are 4 KB aligned, so this is free), elements little-endian,
and N a whole number of 256-bit beats - 8 elements for fp32, 4 for
fp64, 2 for fp128, 1 for fp256.

Requires XRT's Python bindings (pyxrt) on the machine with the card;
everything else in this repo runs without them.
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from cft_golden import (  # noqa: E402
    FORMATS, PREC_CODE, OP_FMA, OP_ADD, OP_SUB, OP_MUL, RND_NAMES,
    compute, vectors,
)

OPS = {"fma": OP_FMA, "add": OP_ADD, "sub": OP_SUB, "mul": OP_MUL}
ELEMS_PER_BEAT = {"fp32": 8, "fp64": 4, "fp128": 2, "fp256": 1}
RNDS = {v: k for k, v in RND_NAMES.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xclbin")
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--format", choices=tuple(ELEMS_PER_BEAT),
                    default="fp32")
    ap.add_argument("--op", choices=tuple(OPS), default="fma")
    ap.add_argument("--rounding", choices=tuple(RNDS), default="rne",
                    help="IEEE 754 rounding attribute (default rne)")
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    import pyxrt  # noqa: PLC0415  (imported late: only needed with a card)

    fmt = FORMATS[args.format]
    op = OPS[args.op]
    rnd = RNDS[args.rounding]
    epb = ELEMS_PER_BEAT[args.format]
    if args.n % epb:
        ap.error(f"--n must be a multiple of {epb} for {args.format}")
    ebytes = fmt.width // 8
    nbytes = args.n * ebytes

    rng = random.Random(args.seed)
    pool = vectors.interesting_operands(fmt)

    def stream():
        return [rng.choice(pool) if rng.random() < 0.1
                else rng.getrandbits(fmt.width) for _ in range(args.n)]

    va, vb, vc = stream(), stream(), stream()
    golden = [compute(fmt, op, va[i], vb[i], vc[i], rnd) for i in range(args.n)]
    expect = [g[0] for g in golden]
    exp_flags = 0
    for g in golden:
        exp_flags |= g[1]

    dev = pyxrt.device(args.device)
    uuid = dev.load_xclbin(pyxrt.xclbin(args.xclbin))
    krnl = pyxrt.kernel(dev, uuid, "cft_krnl")

    def make_bo(argno, data=None):
        bo = pyxrt.bo(dev, nbytes, pyxrt.bo.normal, krnl.group_id(argno))
        if data is not None:
            bo.write(b"".join(v.to_bytes(ebytes, "little") for v in data), 0)
            bo.sync(pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_TO_DEVICE,
                    nbytes, 0)
        return bo

    bo_a, bo_b, bo_c = make_bo(2, va), make_bo(3, vb), make_bo(4, vc)
    bo_d = make_bo(5)

    mode = op | (PREC_CODE[args.format] << 8) | (rnd << 12)
    run = krnl(mode, args.n, bo_a, bo_b, bo_c, bo_d)
    run.wait()

    bo_d.sync(pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, nbytes, 0)
    raw = bo_d.read(nbytes, 0)

    # STATUS (0x50) before anything else: if the memory system did not
    # vouch for the data, comparing it against the golden model is
    # meaningless - the bits under test were never really delivered.
    # If the register cannot be read at all, say so rather than
    # defaulting to "clean": a safety check that silently skips itself
    # is worse than no check, because the PASS line then overclaims.
    try:
        status = krnl.read_register(0x50)
    except Exception as exc:   # older XRT without read_register
        print(f"WARNING: could not read STATUS (0x50): {exc}. "
              f"Bus faults cannot be ruled out for this run.")
        status = 0
    if status:
        print(f"FAIL: kernel reported bus faults, STATUS={status:#05b} "
              f"(bit0 read resp, bit1 write resp, bit2 burst length). "
              f"The output buffer is not trustworthy; check that the "
              f"buffers are in range and 32-byte aligned.")
        return 1

    bad = 0
    for i in range(args.n):
        got = int.from_bytes(raw[i * ebytes:(i + 1) * ebytes], "little")
        if got != expect[i]:
            bad += 1
            if bad <= 10:
                print(f"MISMATCH [{i}]: a={va[i]:#x} b={vb[i]:#x} "
                      f"c={vc[i]:#x} got={got:#x} want={expect[i]:#x}")
    if bad:
        print(f"FAIL: {bad}/{args.n} elements differ from cft_golden")
        return 1
    print(f"PASS: {args.n} {args.format} {args.op} [{args.rounding}] elements "
          f"bit-exact against cft_golden "
          f"(expected sticky flags {exp_flags:#07b})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
