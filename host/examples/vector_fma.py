# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Minimal pyxrt host: run one vector op on the tile and verify every
element against the golden model.

    python3 host/examples/vector_fma.py build/cft_hw.xclbin \
        --format fp256 --op fma --n 4096

The host contract (docs/ARCHITECTURE.md): buffers are 64-byte aligned
(XRT BOs always are), elements little-endian, and N a whole number of
512-bit beats - 16 elements for fp32, 2 for fp256.

Requires XRT's Python bindings (pyxrt) on the machine with the card;
everything else in this repo runs without them.
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "python"))

from cft_golden import (  # noqa: E402
    FORMATS, PREC_CODE, OP_FMA, OP_ADD, OP_SUB, OP_MUL,
    compute, vectors,
)

OPS = {"fma": OP_FMA, "add": OP_ADD, "sub": OP_SUB, "mul": OP_MUL}
ELEMS_PER_BEAT = {"fp32": 16, "fp256": 2}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("xclbin")
    ap.add_argument("--device", type=int, default=0)
    ap.add_argument("--format", choices=("fp32", "fp256"), default="fp32")
    ap.add_argument("--op", choices=tuple(OPS), default="fma")
    ap.add_argument("--n", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    import pyxrt  # noqa: PLC0415  (imported late: only needed with a card)

    fmt = FORMATS[args.format]
    op = OPS[args.op]
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
    expect = [compute(fmt, op, va[i], vb[i], vc[i])[0] for i in range(args.n)]
    exp_flags = 0
    for i in range(args.n):
        exp_flags |= compute(fmt, op, va[i], vb[i], vc[i])[1]

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

    mode = op | (PREC_CODE[args.format] << 4)
    run = krnl(mode, args.n, bo_a, bo_b, bo_c, bo_d)
    run.wait()

    bo_d.sync(pyxrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, nbytes, 0)
    raw = bo_d.read(nbytes, 0)

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
    print(f"PASS: {args.n} {args.format} {args.op} elements bit-exact "
          f"against cft_golden (expected sticky flags {exp_flags:#07b})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
