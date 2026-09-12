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

Generating them costs real minutes - 404 s for the five attributes on
the Windows desktop on 2026-09-07 - and every set is independent of
every other, so `--jobs N` writes them in N worker processes. A worker
rebuilds from the seed the operand pool its own files need and shares
nothing with any other worker, which is why the sets are the same bytes
at any --jobs rather than the same bytes when the scheduling is kind.
`--cache DIR` goes further and does not regenerate a set at all when
the model's source bytes, the generator's, the job's parameters, the
interpreter's version AND the bytes of the file already on disk are all
what they were when it was last written; see the block above main() for
why that cannot go stale, and verify/README.md for why the census
leaves it off.
"""

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import sys
from functools import lru_cache
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
    SP_PROD, SP_PROD_SUM, SP_PROD_DIFF, fdot, fmaxall, fsum, fsumabs,
    fsumsq,
    scaled_prod,
)

# The seven of clause 9.4, by the name their set records.
REDUCE_IMPL = {
    "sum":     lambda fmt, xs, ys, rnd: fsum(fmt, xs, rnd),
    "dot":     lambda fmt, xs, ys, rnd: fdot(fmt, xs, ys, rnd),
    "sumsq":   lambda fmt, xs, ys, rnd: fsumsq(fmt, xs, rnd),
    "sumabs":  lambda fmt, xs, ys, rnd: fsumabs(fmt, xs, rnd),
    "maxall":  lambda fmt, xs, ys, rnd: fmaxall(fmt, xs, rnd),
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


# ======================================================================
# The operand pools
#
# Every pool below is a pure function of (format, counts, seed). That is
# the property this whole file rests on and it is what makes a parallel
# run byte-identical to a serial one, rather than byte-identical when
# the scheduling is kind: a worker rebuilds from the seed the pool its
# own files need, nothing is shared between processes, and no result
# crosses one.
#
# lru_cache because a worker often draws two files of one family in a
# row - the queue is ordered so that a family's attributes are adjacent
# - and then the pool is built once for both. maxsize 2 is enough for
# that and keeps a finished fp256 pool from staying resident for the
# rest of the run.
# ======================================================================

@lru_cache(maxsize=2)
def pool_elementwise(fname, directed, nrandom, simple, seed):
    fmt = FORMATS[fname]
    return tuple(vectors.testset(fmt, directed, nrandom, seed)
                 + vectors.simple_cases(fmt, simple, seed + 2))


@lru_cache(maxsize=2)
def pool_transcend(fname, extra, seed):
    return tuple(vectors.transcend_cases(FORMATS[fname], extra, seed + 6))


@lru_cache(maxsize=2)
def pool_minmaxmag(fname, extra, seed):
    return tuple(vectors.minmax_mag_cases(FORMATS[fname], extra, seed + 21))


@lru_cache(maxsize=2)
def pool_augmented(fname, extra, seed):
    return tuple(vectors.augmented_cases(FORMATS[fname], extra, seed + 7))


@lru_cache(maxsize=2)
def pool_reduce(fname, extra, seed):
    return tuple(vectors.reduce_cases(FORMATS[fname], extra, seed + 8))


@lru_cache(maxsize=2)
def pool_character(fname, extra, seed):
    return tuple(vectors.character_cases(FORMATS[fname], extra, seed + 17))


@lru_cache(maxsize=2)
def pool_formatof(sname, dname, extra, seed):
    return tuple(vectors.formatof_cases(FORMATS[sname], FORMATS[dname],
                                        extra, seed + 21))


# ======================================================================
# One set file at a time
#
# Each writer takes its job's own parameters and nothing else, opens the
# file in TEXT mode - which is what the published sets have always been
# written in, and on Windows that means CRLF, so changing it would
# change every byte of every set - and returns the tail of the line the
# serial generator printed for it. The path is prefixed by the caller,
# because a line recovered from the cache has to name the directory this
# run wrote to and not the one the cache entry was made in.
#
# A writer with no cases returns None and leaves no file, which is what
# the old `for rname in args.rounding if tcases else ()` expressed.
# ======================================================================

def write_elementwise(job, path):
    fmt = FORMATS[job["fmt"]]
    hexw = fmt.width // 4
    rname = job["rnd"]
    rnd = RND_BY_NAME[rname]
    cases = pool_elementwise(job["fmt"], job["directed"], job["random"],
                             job["simple"], job["seed"])
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
    return f": {len(cases)} cases (seed {job['seed']}, {rname})"


def write_transcend(job, path):
    fmt = FORMATS[job["fmt"]]
    hexw = fmt.width // 4
    rname = job["rnd"]
    rnd = RND_BY_NAME[rname]
    tcases = pool_transcend(job["fmt"], job["extra"], job["seed"])
    if not tcases:
        return None
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
    return f": {len(tcases)} cases (seed {job['seed']}, {rname})"


def write_minmaxmag(job, path):
    fmt = FORMATS[job["fmt"]]
    hexw = fmt.width // 4
    mcases = pool_minmaxmag(job["fmt"], job["extra"], job["seed"])
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
    return (f": {len(mcases)} cases (seed {job['seed']}, "
            f"no attribute - 9.6 selects, it does not round)")


def write_augmented(job, path):
    fmt = FORMATS[job["fmt"]]
    hexw = fmt.width // 4
    acases = pool_augmented(job["fmt"], job["extra"], job["seed"])
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
    return (f": {len(acases)} cases (seed {job['seed']}, "
            f"roundTiesTowardZero - 9.5 fixes it)")


def write_reduce(job, path):
    fmt = FORMATS[job["fmt"]]
    hexw = fmt.width // 4
    rname = job["rnd"]
    rnd = RND_BY_NAME[rname]
    rcases = pool_reduce(job["fmt"], job["extra"], job["seed"])
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
    return (f": {len(rcases)} cases, {elems} elements "
            f"(seed {job['seed']}, {rname})")


def write_character(job, path):
    fmt = FORMATS[job["fmt"]]
    hexw = fmt.width // 4
    rname = job["rnd"]
    rnd = RND_BY_NAME[rname]
    ccases = pool_character(job["fmt"], job["extra"], job["seed"])
    written = 0
    with open(path, "w") as f:
        for case in ccases:
            rec = character_record(fmt, hexw, rname, rnd, case)
            if rec is None:
                continue
            f.write(json.dumps(rec) + "\n")
            written += 1
    return f": {written} cases (seed {job['seed']}, {rname})"


def write_formatof(job, path):
    sname, dname = job["sfmt"], job["dfmt"]
    sfmt, dfmt = FORMATS[sname], FORMATS[dname]
    shexw, dhexw = sfmt.width // 4, dfmt.width // 4
    rname = job["rnd"]
    rnd = RND_BY_NAME[rname]
    fcases = pool_formatof(sname, dname, job["extra"], job["seed"])
    with open(path, "w") as f:
        for fn, xa, xb, xc in fcases:
            long_fn = FORMATOF_LONG[fn]
            d, flags = formatof.compute(sfmt, dfmt, long_fn, xa, xb, xc, rnd)
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
    return f": {len(fcases)} cases (seed {job['seed']}, {rname})"


WRITERS = {
    "elementwise": write_elementwise,
    "transcend":   write_transcend,
    "minmaxmag":   write_minmaxmag,
    "augmented":   write_augmented,
    "reduce":      write_reduce,
    "character":   write_character,
    "formatof":    write_formatof,
}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_group(args):
    """Write every file of one group, in order. The argument is one
    tuple because this is what a worker process is handed. Returns
    (idx, tail, sha256, size) per file, with tail None where the family
    had nothing to write at this format."""
    group, outdir = args
    out = []
    for job in group:
        path = Path(outdir) / job["file"]
        tail = WRITERS[job["kind"]](job, path)
        if tail is None:
            out.append((job["idx"], None, None, None))
        else:
            out.append((job["idx"], tail, sha256_file(path),
                        os.path.getsize(path)))
    return out


# ======================================================================
# The content-hash cache (--cache DIR)
#
# A set is REGENERATED unless every one of these holds:
#
#   * the bytes of the model and of this generator hash to what they
#     hashed when the file was written - one digest over every .py in
#     python/cft_golden and over this file,
#   * the job descriptor is identical: family, format or ordered format
#     pair, rounding attribute, every count that family reads, and the
#     seed,
#   * the interpreter's version string is identical,
#   * and the file still on disk hashes to the digest recorded when it
#     was written, at the recorded length.
#
# The last clause is what makes a stale cache impossible rather than
# unlikely. A set that was hand-edited, truncated, half-written by an
# interrupted run or copied in from somewhere else does not match its
# recorded digest and is regenerated.
#
# The manifest lives OUTSIDE the output directory (vectors/.gen-cache by
# default) so that a vector set stays a directory of nothing but vector
# sets: a consumer that scans it, and the hash walk that proves two runs
# produced the same bytes, both see exactly what they saw before.
#
# It is an edit-and-rerun tool, and it says so in the log - a file it
# serves prints its recorded line with "[cached]" on the end, so a run
# that regenerated nothing cannot read as a run that regenerated
# everything. verify/run.sh leaves it off for the census and turns it on
# for the development loop (verify/README.md).
# ======================================================================

CACHE_VERSION = 1


def model_digest():
    """One digest over the model's and this generator's source bytes."""
    root = Path(__file__).resolve().parents[1]
    paths = sorted((root / "python" / "cft_golden").glob("*.py"))
    paths.append(Path(__file__).resolve())
    h = hashlib.sha256()
    for p in sorted(paths):
        h.update(p.resolve().relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(sha256_file(p).encode())
        h.update(b"\n")
    return h.hexdigest()


def job_key(job, model, pyver):
    payload = {k: v for k, v in job.items() if k != "idx"}
    blob = json.dumps({"v": CACHE_VERSION, "model": model, "python": pyver,
                       "job": payload}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def load_manifest(cachedir):
    try:
        with open(Path(cachedir) / "manifest.json", "r") as f:
            m = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(m, dict) or m.get("version") != CACHE_VERSION:
        return {}
    files = m.get("files")
    return files if isinstance(files, dict) else {}


def save_manifest(cachedir, model, pyver, files):
    d = Path(cachedir)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "manifest.json.tmp"
    with open(tmp, "w") as f:
        json.dump({"version": CACHE_VERSION, "model": model,
                   "python": pyver, "files": files}, f,
                  indent=1, sort_keys=True)
    os.replace(tmp, d / "manifest.json")


def cache_hit(entry, key, path):
    """True only if the recorded key matches AND the file on disk is
    byte for byte the file that key was recorded for."""
    if not isinstance(entry, dict) or entry.get("key") != key:
        return False
    try:
        if os.path.getsize(path) != entry.get("size"):
            return False
        return sha256_file(path) == entry.get("sha256")
    except OSError:
        return False


# ======================================================================
# The job list
#
# One job per output file, in the order the serial generator wrote them,
# carrying every parameter that file's contents depend on and nothing
# else. Jobs that read one pool share a "group" key and are handed to a
# worker together.
#
# The `continue`s of the old per-format loop are preserved exactly:
# --augmented 0 suppresses the reduction and character sets too, and
# --reduce -1 suppresses the character sets, because that is what this
# generator has always done and a set that appears or vanishes on a
# refactor is a set nobody can score against.
# ======================================================================

def build_jobs(args):
    jobs = []

    def add(kind, fname, group, **params):
        jobs.append(dict(idx=len(jobs), kind=kind, file=fname,
                         group=group, **params))

    def suffix(rname):
        return "" if rname == "rne" else f"-{rname}"

    for name in args.formats:
        g = ("elementwise", name, args.directed, args.random, args.simple,
             args.seed)
        for rname in args.rounding:
            add("elementwise", f"{name}{suffix(rname)}.jsonl", g,
                fmt=name, rnd=rname, directed=args.directed,
                random=args.random, simple=args.simple, seed=args.seed)

        if args.transcend > 0:
            g = ("transcend", name, args.transcend, args.seed)
            for rname in args.rounding:
                add("transcend", f"{name}-transcend{suffix(rname)}.jsonl", g,
                    fmt=name, rnd=rname, extra=args.transcend, seed=args.seed)

        # The four magnitude forms of 754-2019 9.6. ONE file per format,
        # whatever --rounding asked for, and for a sharper reason than
        # the augmented set's: these operations SELECT an operand rather
        # than computing a value, so there is no rounding for an
        # attribute to direct. Built before the families below because
        # those bail out with `continue`, and a --character 0 run must
        # still emit these.
        if args.minmaxmag > 0:
            g = ("minmaxmag", name, args.minmaxmag, args.seed)
            add("minmaxmag", f"{name}-minmaxmag.jsonl", g,
                fmt=name, extra=args.minmaxmag, seed=args.seed)

        # The augmented arithmetic operations (754-2019 9.5). ONE file
        # per format, whatever --rounding asked for: the rounding is
        # fixed by the standard, so there is no attribute to sweep and
        # no per-attribute file to write. Two outputs per case.
        if args.augmented <= 0:
            continue
        g = ("augmented", name, args.augmented, args.seed)
        add("augmented", f"{name}-augmented.jsonl", g,
            fmt=name, extra=args.augmented, seed=args.seed)

        if args.reduce < 0:
            continue
        g = ("reduce", name, args.reduce, args.seed)
        for rname in args.rounding:
            add("reduce", f"{name}-reduce{suffix(rname)}.jsonl", g,
                fmt=name, rnd=rname, extra=args.reduce, seed=args.seed)

        if args.character <= 0:
            continue
        g = ("character", name, args.character, args.seed)
        for rname in args.rounding:
            add("character", f"{name}-character{suffix(rname)}.jsonl", g,
                fmt=name, rnd=rname, extra=args.character, seed=args.seed)

    # The formatOf arithmetic of 754-2019 5.4.1: one file per ordered
    # (source, destination) pair per attribute, OUTSIDE the per-format
    # loop above because a case here has two formats and belongs to
    # neither of them alone.
    if args.formatof > 0:
        for sname in args.formats:
            for dname in args.formats:
                g = ("formatof", sname, dname, args.formatof, args.seed)
                for rname in args.rounding:
                    add("formatof",
                        f"{sname}-to-{dname}-formatof{suffix(rname)}.jsonl",
                        g, sfmt=sname, dfmt=dname, rnd=rname,
                        extra=args.formatof, seed=args.seed)
    return jobs


def group_cost(group):
    """A scheduling estimate only - it can be wrong without changing a
    byte. The widest format in the task times the files it writes: the
    model's cost per case climbs fast with the format's width, and the
    longest task sets the makespan, so it starts first."""
    w = 0
    for job in group:
        for k in ("fmt", "sfmt", "dfmt"):
            if k in job:
                w = max(w, FORMATS[job[k]].width)
    return w * len(group)


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
    ap.add_argument("--jobs", type=int, default=1,
                    help="worker processes (default 1, the serial "
                         "generator). Every worker rebuilds its own "
                         "pools from the seed, so the sets are the same "
                         "bytes at any --jobs")
    ap.add_argument("--cache", metavar="DIR", default=None,
                    help="reuse a set whose model, parameters and bytes "
                         "on disk are all unchanged, recording what was "
                         "written in DIR/manifest.json (default: no "
                         "cache, everything regenerated)")
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)

    jobs = build_jobs(args)

    manifest = {}
    model = pyver = None
    cached = {}
    if args.cache:
        model = model_digest()
        pyver = platform.python_version()
        manifest = dict(load_manifest(args.cache))
        for job in jobs:
            key = job_key(job, model, pyver)
            job["_key"] = key
            if cache_hit(manifest.get(job["file"]), key,
                         outdir / job["file"]):
                cached[job["idx"]] = manifest[job["file"]]

    todo = [j for j in jobs if j["idx"] not in cached]

    # One task per FILE, and the dearest first. Not per family, which
    # was the first shape of this and left the five fp256
    # transcendental attributes as one task: it was still running with
    # three workers idle after the other 163 files were done. A worker
    # that draws a file whose pool it does not have rebuilds it, and
    # that is cheap - measured 2026-09-07 on this desktop, the fp256
    # transcendental pool is 2.2 s and the fp256 elementwise pool 0.1 s
    # against files the model spends minutes on. The estimate below
    # only orders the queue; being wrong about it costs a little
    # makespan and cannot change a byte.
    work = sorted(([job] for job in todo), key=group_cost, reverse=True)

    results = {}
    nworkers = max(1, min(args.jobs, len(work)))
    payload = [(group, str(outdir)) for group in work]

    # Reported in the order the serial generator reported it, whatever
    # order the workers finish in: a file's line waits until every
    # earlier file has one. Printed as the prefix completes rather than
    # all at the end, because a stage that says nothing for ten minutes
    # reads as a stage that has hung.
    printed = 0

    def report_ready():
        nonlocal printed
        while printed < len(jobs):
            job = jobs[printed]
            path = outdir / job["file"]
            if job["idx"] in cached:
                print(f"{path}{cached[job['idx']]['tail']}  [cached]",
                      flush=True)
                printed += 1
                continue
            if job["idx"] not in results:
                return
            tail, dig, size = results[job["idx"]]
            printed += 1
            if tail is None:            # nothing to write at this format
                continue
            print(f"{path}{tail}", flush=True)
            if args.cache:
                manifest[job["file"]] = {"key": job["_key"], "sha256": dig,
                                         "size": size, "tail": tail}

    def collect(rows):
        for idx, tail, dig, size in rows:
            results[idx] = (tail, dig, size)
        report_ready()

    if nworkers <= 1:
        for one in payload:
            collect(run_group(one))
    else:
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=nworkers) as ex:
            for rows in ex.map(run_group, payload, chunksize=1):
                collect(rows)
    report_ready()

    if args.cache:
        save_manifest(args.cache, model, pyver, manifest)


if __name__ == "__main__":
    main()
