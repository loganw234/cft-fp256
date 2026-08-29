# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Emit on-disk conformance vector sets.

    python3 vectors/gen_vectors.py --out vectors/out [--formats fp32 fp256]
        [--directed 4000] [--random 6000] [--seed 3]

One JSONL file per format. Every line is one case with the golden
result and flags:

    {"op": "fma", "a": "0x...", "b": "0x...", "c": "0x...",
     "d": "0x...", "flags": 17}

These files are the cross-implementation contract: the RTL testbenches
regenerate the same cases from the same seed, and a GPU-side det
library (or any other implementation claiming identity) is scored by
replaying the file. Vectors are derived data - never hand-edit;
regenerate and let the seed carry the provenance.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))

from cft_golden import FORMATS, OP_NAMES, compute, vectors  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="vectors/out")
    ap.add_argument("--formats", nargs="+", default=list(FORMATS),
                    choices=list(FORMATS))
    ap.add_argument("--directed", type=int, default=4000)
    ap.add_argument("--random", type=int, default=6000)
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for name in args.formats:
        fmt = FORMATS[name]
        hexw = fmt.width // 4
        cases = vectors.testset(fmt, args.directed, args.random, args.seed)
        path = outdir / f"{name}.jsonl"
        with open(path, "w") as f:
            for op, xa, xb, xc in cases:
                d, flags = compute(fmt, op, xa, xb, xc)
                f.write(json.dumps({
                    "op": OP_NAMES[op],
                    "a": f"0x{xa:0{hexw}x}",
                    "b": f"0x{xb:0{hexw}x}",
                    "c": f"0x{xc:0{hexw}x}",
                    "d": f"0x{d:0{hexw}x}",
                    "flags": flags,
                }) + "\n")
        print(f"{path}: {len(cases)} cases (seed {args.seed})")


if __name__ == "__main__":
    main()
