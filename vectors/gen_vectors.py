# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Emit on-disk conformance vector sets.

    python3 vectors/gen_vectors.py --out vectors/out [--formats fp32 fp256]
        [--directed 4000] [--random 6000] [--seed 3]
        [--rounding rne rtz rdn rup rmm]

One JSONL file per (format, rounding attribute): `fp32.jsonl` for the
default roundTiesToEven, `fp32-rtz.jsonl` and friends for the others.
Every line is one case with the golden result and flags:

    {"op": "fma", "rnd": "rne", "a": "0x...", "b": "0x...",
     "c": "0x...", "d": "0x...", "flags": 17}

The transcendentals get their own files - `fp32-transcend.jsonl` and
`fp32-transcend-rtz.jsonl` and so on - because they are library entry
points rather than opcodes, so a replayer dispatches them by NAME
rather than by opcode number and reads a different schema:

    {"fn": "pow", "rnd": "rne", "a": "0x...", "b": "0x...",
     "d": "0x...", "flags": 16}

"b" appears only for the four binary functions (pow, hypot, atan2 and
atan2Pi). Keeping them in separate files means a consumer that predates
ABI 0.3 reads exactly what it always read, and one that does not carry
the transcendentals skips a file rather than failing a line. A
consumer built against 0.3 and handed a 0.4 set fails on the NAME of a
function it does not know, which is the refusal it should give.

The REDUCTIONS get a third schema - `fp32-reduce.jsonl` and friends -
for the same reason, and the published sets carried none of them at
all before this. A reduction's operand is a whole VECTOR whose length
is part of the case, which neither schema above can express: both are
one line per case with a fixed number of single-element operands.

    {"fn": "sumsq", "rnd": "rne", "n": 5,
     "a": ["0x...", ...], "d": "0x...", "flags": 16}

    {"fn": "scaled_prod", "rnd": "rne", "n": 5, "a": ["0x...", ...],
     "pr": "0x...", "sf": -137, "flags": 16}

"b" appears for dot, scaled_prod_sum and scaled_prod_diff. The three
scaled products carry "pr" and "sf" instead of "d", because they return
a PAIR - the whole point of the operation - and a set that recorded
only the significand would score half of it.

Every opcode the tile implements appears here, arithmetic and
non-arithmetic alike, plus the unassigned codes whose defined
answer (canonical qNaN, invalid raised) is also part of the
contract. A set covering only the arithmetic would score almost
nothing.

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

from cft_golden import (  # noqa: E402
    FORMATS, OP_NAMES, RND_NAMES, TRANSCEND_ARITY, compute, transcend,
    vectors,
)
from cft_golden.reduce import (  # noqa: E402
    SP_PROD, SP_PROD_SUM, SP_PROD_DIFF, fdot, fsum, fsumabs, fsumsq,
    scaled_prod,
)

# The seven of clause 9.4, by the name their set records.
REDUCE_IMPL = {
    "sum":     lambda fmt, xs, ys, rnd: fsum(fmt, xs, rnd),
    "dot":     lambda fmt, xs, ys, rnd: fdot(fmt, xs, ys, rnd),
    "sumsq":   lambda fmt, xs, ys, rnd: fsumsq(fmt, xs, rnd),
    "sumabs":  lambda fmt, xs, ys, rnd: fsumabs(fmt, xs, rnd),
    "scaled_prod":
        lambda fmt, xs, ys, rnd: scaled_prod(fmt, xs, None, SP_PROD, rnd),
    "scaled_prod_sum":
        lambda fmt, xs, ys, rnd: scaled_prod(fmt, xs, ys, SP_PROD_SUM, rnd),
    "scaled_prod_diff":
        lambda fmt, xs, ys, rnd: scaled_prod(fmt, xs, ys, SP_PROD_DIFF, rnd),
}

RND_BY_NAME = {v: k for k, v in RND_NAMES.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="vectors/out")
    ap.add_argument("--formats", nargs="+", default=list(FORMATS),
                    choices=list(FORMATS))
    ap.add_argument("--rounding", nargs="+", default=["rne"],
                    choices=list(RND_BY_NAME),
                    help="rounding attributes to emit (default: rne only)")
    ap.add_argument("--directed", type=int, default=4000)
    ap.add_argument("--random", type=int, default=6000)
    ap.add_argument("--simple", type=int, default=400,
                    help="cases per non-arithmetic opcode")
    ap.add_argument("--transcend", type=int, default=24,
                    help="random cases added to each transcendental "
                         "family's directed pool (0 to skip the sets)")
    ap.add_argument("--reduce", type=int, default=2,
                    help="random operand pools added to the reduction "
                         "sets' directed ones (-1 to skip the sets)")
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for name in args.formats:
        fmt = FORMATS[name]
        hexw = fmt.width // 4
        cases = (vectors.testset(fmt, args.directed, args.random, args.seed)
                 + vectors.simple_cases(fmt, args.simple, args.seed + 2))
        for rname in args.rounding:
            rnd = RND_BY_NAME[rname]
            # the default attribute keeps the plain filename, so an
            # existing consumer scoring fp32.jsonl is unaffected
            suffix = "" if rname == "rne" else f"-{rname}"
            path = outdir / f"{name}{suffix}.jsonl"
            with open(path, "w") as f:
                for op, xa, xb, xc in cases:
                    d, flags = compute(fmt, op, xa, xb, xc, rnd)
                    f.write(json.dumps({
                        "op": OP_NAMES.get(op, f"reserved{op}"),
                        "rnd": rname,
                        "a": f"0x{xa:0{hexw}x}",
                        "b": f"0x{xb:0{hexw}x}",
                        "c": f"0x{xc:0{hexw}x}",
                        "d": f"0x{d:0{hexw}x}",
                        "flags": flags,
                    }) + "\n")
            print(f"{path}: {len(cases)} cases (seed {args.seed}, {rname})")

        tcases = (vectors.transcend_cases(fmt, args.transcend, args.seed + 6)
                  if args.transcend > 0 else [])
        for rname in args.rounding if tcases else ():
            rnd = RND_BY_NAME[rname]
            suffix = "" if rname == "rne" else f"-{rname}"
            path = outdir / f"{name}-transcend{suffix}.jsonl"
            with open(path, "w") as f:
                for fn, xa, xb in tcases:
                    d, flags = transcend.compute(fmt, fn, xa, xb, rnd)
                    rec = {
                        "fn": fn,
                        "rnd": rname,
                        "a": f"0x{xa:0{hexw}x}",
                    }
                    if TRANSCEND_ARITY[fn] == 2:
                        rec["b"] = f"0x{xb:0{hexw}x}"
                    rec["d"] = f"0x{d:0{hexw}x}"
                    rec["flags"] = flags
                    f.write(json.dumps(rec) + "\n")
            print(f"{path}: {len(tcases)} cases (seed {args.seed}, {rname})")

        if args.reduce < 0:
            continue
        rcases = vectors.reduce_cases(fmt, args.reduce, args.seed + 8)
        for rname in args.rounding:
            rnd = RND_BY_NAME[rname]
            suffix = "" if rname == "rne" else f"-{rname}"
            path = outdir / f"{name}-reduce{suffix}.jsonl"
            elems = 0
            with open(path, "w") as f:
                for fn, xs, ys in rcases:
                    out = REDUCE_IMPL[fn](fmt, xs, ys, rnd)
                    rec = {
                        "fn": fn,
                        "rnd": rname,
                        "n": len(xs),
                        "a": [f"0x{v:0{hexw}x}" for v in xs],
                    }
                    if ys is not None:
                        rec["b"] = [f"0x{v:0{hexw}x}" for v in ys]
                    if len(out) == 3:
                        pr, sf_, flags = out
                        rec["pr"] = f"0x{pr:0{hexw}x}"
                        rec["sf"] = sf_
                    else:
                        d, flags = out
                        rec["d"] = f"0x{d:0{hexw}x}"
                    rec["flags"] = flags
                    elems += len(xs)
                    f.write(json.dumps(rec) + "\n")
            print(f"{path}: {len(rcases)} cases, {elems} elements "
                  f"(seed {args.seed}, {rname})")


if __name__ == "__main__":
    main()
