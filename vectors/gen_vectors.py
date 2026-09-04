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

"b" appears only for the five binary functions (pow, hypot, atan2,
atan2Pi and powr), and "n" - a SIGNED DECIMAL, not an encoding - only
for the three that take an integer exponent (pown, compound and
rootn), because 754-2019 9.2.1 gives them one:

    {"fn": "rootn", "rnd": "rne", "a": "0x...", "n": -3,
     "d": "0x...", "flags": 16}

Keeping them in separate files means a consumer that predates ABI 0.3
reads exactly what it always read, and one that does not carry the
transcendentals skips a file rather than failing a line. A consumer
built against 0.3 and handed a 0.4 set fails on the NAME of a function
it does not know, which is the refusal it should give; one that knows
the names but not the "n" field fails on a missing key, which is the
same refusal.

The augmented arithmetic operations of 754-2019 clause 9.5 get a third
schema and a third family of files - `fp32-augmented.jsonl` and one per
format - because they are the only operations here with TWO outputs and
no rounding attribute:

    {"fn": "augmentedAddition", "a": "0x...", "b": "0x...",
     "r": "0x...", "e": "0x...", "flags": 8}

There is no "rnd" field and its absence is normative: 9.5 fixes the
rounding to roundTiesTowardZero, which is not one of the five
attributes, so there is no attribute to record and no per-attribute
file. A replayer that demanded one would be asking the wrong question.

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

The four MAGNITUDE forms of minimum and maximum (754-2019 9.6) get
their own family too - `fp32-minmaxmag.jsonl` and one per format - for
the reasons the augmented set has one: they are library entry points
rather than opcodes, so a replayer dispatches them by NAME, and they
consume no rounding attribute, so there is ONE file per format rather
than one per attribute.

    {"fn": "minimumMagnitude", "a": "0x...", "b": "0x...",
     "d": "0x...", "flags": 0}

"fn" is 754's own spelling - minimumMagnitude, minimumMagnitudeNumber,
maximumMagnitude, maximumMagnitudeNumber - not this repository's C
names, because the set is a statement about the standard. There is no
"rnd" field and, as in the augmented family, its absence is normative:
these operations SELECT one of their operands rather than computing a
value, so there is no rounding to record and an attribute could not
change an answer. The four opcodes of 9.6 that DO exist - min, max,
minnum, maxnum - stay where they are, in the elementwise sets, because
they are opcodes.

"refuse" marks a sequence that is NOT in 5.12's syntax and that a
conforming implementation must REFUSE - which is as much a part of the
contract as any value, and the one part a set of encodings cannot
express. Every "s" here is asserted to be free of characters JSON
would have to escape, so a replayer's scanner needs no unescaper.

The formatOf arithmetic of 754-2019 5.4.1 gets a family of its own -
`fp64-to-fp32-formatof.jsonl`, `fp256-to-fp128-formatof-rtz.jsonl` and so
on, one file per ORDERED PAIR of formats per attribute - because it is
the only family whose case has two formats:

    {"fn": "fma", "sfmt": "fp64", "dfmt": "fp32", "rnd": "rne",
     "a": "0x...", "b": "0x...", "c": "0x...",
     "d": "0x3f800001", "flags": 16}

"a" is a source-format encoding and "d" a destination-format one, so
the two are different widths on the same line; "b" appears for every
operation but sqrt and "c" only for fma. All sixteen ordered pairs are
emitted, the same-format four included, because 5.4.1 asks for
"destinations of all supported arithmetic formats and, for each
destination format, ... operands of all supported arithmetic formats".

This is the one family that repeats its formats INSIDE the record as
well as in the filename, and the repetition is deliberate: with two
formats there is a pairing to get wrong, and a set whose name and
contents disagree is a failure mode no other family has. cft_conformance
checks the two against each other and refuses a file that lies about
itself.

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
    FORMATS, OP_NAMES, RND_NAMES, TRANSCEND_ARITY, chars, TRANSCEND_INTARG, augmented, compute,
    transcend, vectors,
    MINMAX_MAG_FNS, MINMAX_MAG_754, MINMAX_MAG_IMPL,
)
from cft_golden import formatof  # noqa: E402
from cft_golden.formatof import (  # noqa: E402
    FORMATOF_ARITY, FORMATOF_SHORT,
)

#: The set files and the C entry points name these operations "add",
#: "div" and so on; the standard names them "formatOf-addition" and
#: "formatOf-division". FORMATOF_SHORT maps one way and this maps back,
#: so neither name is written out twice.
FORMATOF_LONG = {v: k for k, v in FORMATOF_SHORT.items()}
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

#: 754's spelling of each 9.6 magnitude form -> the model function that
#: defines it. Built from the model's own two tables rather than
#: written out, so the set can only ever record a name the model knows.
MINMAX_MAG_BY_754 = {MINMAX_MAG_754[k]: MINMAX_MAG_IMPL[k]
                     for k in MINMAX_MAG_FNS}

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
    ap.add_argument("--reduce", type=int, default=2,
                    help="random operand pools added to the reduction "
                         "sets' directed ones (-1 to skip the sets)")
    ap.add_argument("--augmented", type=int, default=24,
                    help="random pairs added to the clause-9.5 pool "
                         "(0 to skip the augmented sets)")
    ap.add_argument("--character", type=int, default=12,
                    help="random sequences added to the clause-5.12 "
                         "directed pool (0 to skip the sets)")
    ap.add_argument("--minmaxmag", type=int, default=16,
                    help="random pairs added to the clause-9.6 magnitude "
                         "pool (0 to skip the sets)")
    ap.add_argument("--formatof", type=int, default=8,
                    help="random operands added to each clause-5.4.1 "
                         "formatOf pool (0 to skip the sets)")
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
                for fn, xa, xb, nn in tcases:
                    d, flags = transcend.compute(fmt, fn, xa, xb, rnd, nn)
                    rec = {
                        "fn": fn,
                        "rnd": rname,
                        "a": f"0x{xa:0{hexw}x}",
                    }
                    if TRANSCEND_ARITY[fn] == 2:
                        rec["b"] = f"0x{xb:0{hexw}x}"
                    if TRANSCEND_INTARG[fn]:
                        rec["n"] = nn
                    rec["d"] = f"0x{d:0{hexw}x}"
                    rec["flags"] = flags
                    f.write(json.dumps(rec) + "\n")
            print(f"{path}: {len(tcases)} cases (seed {args.seed}, {rname})")

        # The four magnitude forms of 754-2019 9.6. ONE file per
        # format, whatever --rounding asked for, and for a sharper
        # reason than the augmented set's: these operations SELECT an
        # operand rather than computing a value, so there is no
        # rounding for an attribute to direct. Written before the
        # blocks below because those skip with `continue`, and a
        # --character 0 run must still emit these.
        if args.minmaxmag > 0:
            mcases = vectors.minmax_mag_cases(fmt, args.minmaxmag,
                                              args.seed + 21)
            path = outdir / f"{name}-minmaxmag.jsonl"
            with open(path, "w") as f:
                for fn, xa, xb in mcases:
                    d, flags = MINMAX_MAG_BY_754[fn](fmt, xa, xb)
                    f.write(json.dumps({
                        "fn": fn,
                        "a": f"0x{xa:0{hexw}x}",
                        "b": f"0x{xb:0{hexw}x}",
                        "d": f"0x{d:0{hexw}x}",
                        "flags": flags,
                    }) + "\n")
            print(f"{path}: {len(mcases)} cases (seed {args.seed}, "
                  f"no attribute - 9.6 selects, it does not round)")

        # The augmented arithmetic operations (754-2019 9.5). ONE file
        # per format, whatever --rounding asked for: the rounding is
        # fixed by the standard, so there is no attribute to sweep and
        # no per-attribute file to write. Two outputs per case.
        if args.augmented <= 0:
            continue
        acases = vectors.augmented_cases(fmt, args.augmented, args.seed + 7)
        path = outdir / f"{name}-augmented.jsonl"
        with open(path, "w") as f:
            for fn, xa, xb in acases:
                r, e, flags = augmented.compute(fmt, fn, xa, xb)
                f.write(json.dumps({
                    "fn": fn,
                    "a": f"0x{xa:0{hexw}x}",
                    "b": f"0x{xb:0{hexw}x}",
                    "r": f"0x{r:0{hexw}x}",
                    "e": f"0x{e:0{hexw}x}",
                    "flags": flags,
                }) + "\n")
        print(f"{path}: {len(acases)} cases (seed {args.seed}, "
              f"roundTiesTowardZero - 9.5 fixes it)")

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

    # The formatOf arithmetic of 754-2019 5.4.1: one file per ordered
    # (source, destination) pair per attribute, OUTSIDE the per-format
    # loop above because a case here has two formats and belongs to
    # neither of them alone.
    if args.formatof > 0:
        for sname in args.formats:
            for dname in args.formats:
                sfmt, dfmt = FORMATS[sname], FORMATS[dname]
                shexw, dhexw = sfmt.width // 4, dfmt.width // 4
                fcases = vectors.formatof_cases(sfmt, dfmt, args.formatof,
                                                args.seed + 21)
                for rname in args.rounding:
                    rnd = RND_BY_NAME[rname]
                    suffix = "" if rname == "rne" else f"-{rname}"
                    path = (outdir /
                            f"{sname}-to-{dname}-formatof{suffix}.jsonl")
                    with open(path, "w") as f:
                        for fn, xa, xb, xc in fcases:
                            long_fn = FORMATOF_LONG[fn]
                            d, flags = formatof.compute(sfmt, dfmt, long_fn,
                                                        xa, xb, xc, rnd)
                            rec = {
                                "fn": fn,
                                "sfmt": sname,
                                "dfmt": dname,
                                "rnd": rname,
                                "a": f"0x{xa:0{shexw}x}",
                            }
                            arity = FORMATOF_ARITY[long_fn]
                            if arity >= 2:
                                rec["b"] = f"0x{xb:0{shexw}x}"
                            if arity >= 3:
                                rec["c"] = f"0x{xc:0{shexw}x}"
                            rec["d"] = f"0x{d:0{dhexw}x}"
                            rec["flags"] = flags
                            f.write(json.dumps(rec) + "\n")
                    print(f"{path}: {len(fcases)} cases (seed {args.seed}, "
                          f"{rname})")


if __name__ == "__main__":
    main()
