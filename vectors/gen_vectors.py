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

The clause-5.12 character conversions and the clause-9.7 payload
operations get a third family of files - `fp32-character.jsonl`,
`fp32-character-rtz.jsonl` and so on - for the same reason and with a
third schema, because a case here names a SEQUENCE rather than an
encoding:

    {"fn": "from_decimal", "rnd": "rne", "s": "1.5",
     "d": "0x3fc00000", "flags": 0}
    {"fn": "from_decimal", "rnd": "rne", "s": "1..2", "refuse": 1}
    {"fn": "to_decimal", "rnd": "rne", "a": "0x3fc00000",
     "digits": 0, "s": "1.5e+0", "flags": 0}
    {"fn": "to_hex", "rnd": "rne", "a": "0x3fc00000",
     "s": "0x1.8p+0", "flags": 0}
    {"fn": "get_payload", "rnd": "rne", "a": "0x7fc00005",
     "d": "0x40a00000", "flags": 0}

"refuse" marks a sequence that is NOT in 5.12's syntax and that a
conforming implementation must REFUSE - which is as much a part of the
contract as any value, and the one part a set of encodings cannot
express. Every "s" here is asserted to be free of characters JSON
would have to escape, so a replayer's scanner needs no unescaper.

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
    FORMATS, OP_NAMES, RND_NAMES, TRANSCEND_ARITY, chars, compute, transcend,
    vectors,
)

RND_BY_NAME = {v: k for k, v in RND_NAMES.items()}

PAYLOAD_IMPL = {
    "get_payload": chars.get_payload,
    "set_payload": chars.set_payload,
    "set_payload_signaling": chars.set_payload_signaling,
}


def plain(s):
    """A sequence JSON can write with no escapes, asserted rather than
    assumed - cft_conformance's scanner reads a string by looking for
    the closing quote and has no unescaper to give it."""
    assert '"' not in s and "\\" not in s and "\n" not in s, repr(s)
    return s


def character_record(fmt, hexw, rname, rnd, case):
    """One case as the record a replayer reads, or None when the case
    does not belong in this attribute's file."""
    kind = case[0]
    rec = {"fn": kind, "rnd": rname}
    if kind.endswith("_refuse"):
        return {"fn": kind[:-len("_refuse")], "rnd": rname,
                "s": plain(case[1]), "refuse": 1}
    if kind == "from_decimal" or kind == "from_hex":
        conv = chars.from_decimal if kind == "from_decimal" else chars.from_hex
        d, flags = conv(fmt, case[1], rnd)
        rec["s"] = plain(case[1])
        rec["d"] = f"0x{d:0{hexw}x}"
        rec["flags"] = flags
        return rec
    if kind == "to_decimal":
        s, flags = chars.to_decimal(fmt, case[1], case[2], rnd)
        rec["a"] = f"0x{case[1]:0{hexw}x}"
        rec["digits"] = case[2]
        rec["s"] = plain(s)
        rec["flags"] = flags
        return rec
    if kind == "to_hex":
        rec["a"] = f"0x{case[1]:0{hexw}x}"
        rec["s"] = plain(chars.to_hex(fmt, case[1]))
        rec["flags"] = 0
        return rec
    # The three 9.7 operations consult no attribute and signal nothing,
    # so one file carries them rather than five identical copies.
    if rname != "rne":
        return None
    rec["fn"] = case[1]
    rec["a"] = f"0x{case[2]:0{hexw}x}"
    rec["d"] = f"0x{PAYLOAD_IMPL[case[1]](fmt, case[2]):0{hexw}x}"
    rec["flags"] = 0
    return rec


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
    ap.add_argument("--character", type=int, default=12,
                    help="random sequences added to the clause-5.12 "
                         "directed pool (0 to skip the sets)")
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

        if args.transcend <= 0:
            continue
        tcases = vectors.transcend_cases(fmt, args.transcend, args.seed + 6)
        for rname in args.rounding:
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

        if args.character <= 0:
            continue
        ccases = vectors.character_cases(fmt, args.character, args.seed + 17)
        for rname in args.rounding:
            rnd = RND_BY_NAME[rname]
            suffix = "" if rname == "rne" else f"-{rname}"
            path = outdir / f"{name}-character{suffix}.jsonl"
            written = 0
            with open(path, "w") as f:
                for case in ccases:
                    rec = character_record(fmt, hexw, rname, rnd, case)
                    if rec is None:
                        continue
                    f.write(json.dumps(rec) + "\n")
                    written += 1
            print(f"{path}: {written} cases (seed {args.seed}, {rname})")


if __name__ == "__main__":
    main()
