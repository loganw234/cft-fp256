# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Record what libcft's C executor does to the shared sequencer fuzz
corpus, so a JavaScript harness can be held to it without a C compiler.

    python bindings/node/make_seq_corpus.py            # rewrite the file
    python bindings/node/make_seq_corpus.py --check    # regenerate and
                                                       # compare, no write

`host/tests/seq_check.py` is the live check: it runs the same programs
through the golden model and through libcft and compares them in one
process. That is the stronger test and it stays the gate. But it needs
a built `libcft` and a Python with `cft_golden` on the path, and
`bindings/node` has neither - it is a wasm module and a JavaScript
harness, and the whole point of it is that it runs where a toolchain
does not.

So this driver writes down what the C executor answered, once, and
`bindings/node/program_test.mjs` replays the SAME images and the SAME
operands through `cft_program_load`/`cft_program_run` in wasm and
compares every deposit, every count, the IEEE flag word and the STATUS
word against the recording. A disagreement is then either a wrong wasm
build or a changed executor, and both are news.

WHAT MAKES THIS A CORPUS RATHER THAN A PILE OF NUMBERS, and it is the
same rule the vector sets keep:

  * The programs are `cft_golden.seq.random_program`'s, from a NAMED
    SEED, so this file is derived data that anyone can regenerate
    rather than a set of magic numbers nobody can audit. `--check`
    regenerates it and refuses if a byte moved.
  * The expected values are the C EXECUTOR's, read out of `libcft`
    through ctypes exactly as seq_check.py reads them - not the golden
    model's, because seq_check.py already holds those two to each
    other and a recording of the model would be checking wasm against
    Python by way of a file.
  * REFUSALS ARE RECORDED TOO. Roughly a third of the corpus is
    deliberately corrupted (seq_check.py's own `corrupt()`), so the
    JavaScript surface is asked to refuse the programs the C loader
    refuses, with the same status. A binding that loaded them all
    would pass every value comparison in the file and still be wrong
    about the thing the loader exists for.
  * The n values straddle libcft's 64-lane block boundary at the two
    narrow formats, so the recording covers the blocking that
    seq_check.py's third comparison is about. At fp128 and fp256 they
    are small, because 100 lanes x 4 deposits of 64 hex digits is a
    megabyte of JSON for a fact the narrow formats already carry.

The file is JSONL: one header object, then one object per case.
Encodings are lower-case hex of the little-endian bytes, which is what
the image itself carries and what a JavaScript test can compare
without a decimal conversion standing between it and the bits.
"""

import argparse
import ctypes
import hashlib
import json
import os
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT / "host" / "tests"))

from cft_golden import FORMATS  # noqa: E402
from cft_golden import seq  # noqa: E402
from seq_check import corrupt, load_library  # noqa: E402

CFT_OK = 0
OUT = HERE / "seq_corpus.jsonl"

# The seed and the shape. Named here and written into the header, so
# the file says how to make itself.
SEED = 2609
PER_FORMAT = 48
CORRUPT_RATE = 0.32
# Two n ladders. The narrow one straddles libcft's 64-lane block
# (host/src/program.c BLOCK_LANES) in both directions; the wide one
# does not, because the recording would be enormous and the blocking
# is not format-dependent.
N_NARROW = [1, 2, 3, 5, 8, 63, 64, 65, 100]
N_WIDE = [1, 2, 3, 5, 8, 17]
MAXDEP = [0, 1, 2, 4]


def hexes(vals, esz):
    return [v.to_bytes(esz, "little").hex() for v in vals]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="regenerate and compare against the committed "
                         "file instead of writing it")
    args = ap.parse_args()

    lib = load_library()
    dev = ctypes.c_void_p()
    st = lib.cft_open(None, 0, ctypes.byref(dev))
    if st != CFT_OK:
        raise SystemExit(f"cft_open: {lib.cft_strerror(st).decode()}")

    lines = []
    counts = {"ok": 0, "refused": 0}
    try:
        for name in ("fp32", "fp64", "fp128", "fp256"):
            fmt = FORMATS[name]
            esz = fmt.width // 8
            rng = random.Random(SEED ^ (fmt.width * 7919))
            ns = N_NARROW if fmt.width <= 64 else N_WIDE
            for trial in range(PER_FORMAT):
                insns, consts = seq.random_program(fmt, rng)
                maxdep = rng.choice(MAXDEP)
                kind = None
                if rng.random() < CORRUPT_RATE:
                    insns, kind = corrupt(insns, rng)
                try:
                    prog = seq.Program(fmt, insns, consts, maxdep)
                except seq.ProgramError as err:
                    # The model refuses it. Record the image and the C
                    # loader's own answer, which seq_check.py has
                    # already shown agrees.
                    bogus = seq.Program.__new__(seq.Program)
                    bogus.fmt, bogus.insns = fmt, insns
                    bogus.consts, bogus.max_deposits = consts, maxdep
                    # every field to_bytes() reads, by name - the
                    # header's flags word (revision 2) and the two
                    # scratch counts (revision 3) included; this
                    # bypass had not been updated for either
                    bogus.flags = 0
                    bogus.n_scratch_in = bogus.n_scratch_out = 0
                    bogus._n_consts = len(consts)
                    image = bogus.to_bytes()
                    handle = ctypes.c_void_p()
                    rc = lib.cft_program_load(dev, image, len(image),
                                              ctypes.byref(handle))
                    if rc == CFT_OK:
                        lib.cft_program_free(handle)
                        raise SystemExit(
                            f"{name} trial {trial}: the model refuses this "
                            f"program and libcft loads it - record nothing "
                            f"until host/tests/seq_check.py is green")
                    lines.append({
                        "format": name, "expect": "refused",
                        "corruption": kind,
                        "model_reason": str(err),
                        "status": int(rc),
                        "status_text": lib.cft_strerror(rc).decode(),
                        "image": image.hex(),
                    })
                    counts["refused"] += 1
                    continue

                n = rng.choice(ns)
                a = seq.random_inputs(fmt, rng, n)
                b = seq.random_inputs(fmt, rng, n)
                c = seq.random_inputs(fmt, rng, n)
                image = prog.to_bytes()

                handle = ctypes.c_void_p()
                rc = lib.cft_program_load(dev, image, len(image),
                                          ctypes.byref(handle))
                if rc != CFT_OK:
                    raise SystemExit(
                        f"{name} trial {trial}: cft_program_load refused a "
                        f"program the model accepts "
                        f"({lib.cft_strerror(rc).decode()})")
                try:
                    def pack(vals):
                        return ctypes.create_string_buffer(
                            b"".join(v.to_bytes(esz, "little")
                                     for v in vals), n * esz)

                    buf_a, buf_b, buf_c = pack(a), pack(b), pack(c)
                    ndep = n * maxdep
                    buf_d = ctypes.create_string_buffer(max(1, ndep * esz))
                    cnt = (ctypes.c_uint32 * max(1, n))()
                    flags = ctypes.c_uint32(0)
                    bus = ctypes.c_uint32(0)
                    rc = lib.cft_program_run(handle, buf_a, buf_b, buf_c,
                                             buf_d, cnt, n,
                                             ctypes.byref(flags),
                                             ctypes.byref(bus))
                    if rc != CFT_OK:
                        raise SystemExit(
                            f"{name} trial {trial}: cft_program_run: "
                            f"{lib.cft_strerror(rc).decode()}")
                    raw = buf_d.raw
                    deposits = [int.from_bytes(raw[i * esz:(i + 1) * esz],
                                               "little")
                                for i in range(ndep)]
                finally:
                    lib.cft_program_free(handle)

                # The model ran these too, in seq_check.py. Assert the
                # agreement HERE as well, so a recording made against a
                # broken build cannot be committed quietly.
                want = seq.run(prog, a, b, c)
                if (want.deposits != deposits or want.counts != list(cnt)[:n]
                        or want.flags != flags.value
                        or want.status != bus.value):
                    raise SystemExit(
                        f"{name} trial {trial}: libcft and the golden model "
                        f"disagree - recording refused; run "
                        f"host/tests/seq_check.py")

                lines.append({
                    "format": name, "expect": "ok",
                    "n": n, "max_deposits": maxdep,
                    "n_insns": len(prog.insns), "n_consts": len(prog.consts),
                    "image": image.hex(),
                    "a": hexes(a, esz), "b": hexes(b, esz),
                    "c": hexes(c, esz),
                    "deposits": hexes(deposits, esz),
                    "counts": list(cnt)[:n],
                    "flags": flags.value, "status": bus.value,
                })
                counts["ok"] += 1
    finally:
        lib.cft_close(dev)

    body = "".join(json.dumps(o, sort_keys=True) + "\n" for o in lines)
    header = {
        "kind": "cft sequencer corpus",
        "version": 1,
        "generator": "bindings/node/make_seq_corpus.py",
        "seed": SEED,
        "per_format": PER_FORMAT,
        "corrupt_rate": CORRUPT_RATE,
        "programs": seq.random_program.__module__ + ".random_program",
        "executor": "libcft cft_program_load / cft_program_run, "
                    "software backend",
        "cases": len(lines),
        "runs": counts["ok"],
        "refusals": counts["refused"],
        "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }
    text = json.dumps(header, sort_keys=True) + "\n" + body

    if args.check:
        if not OUT.exists():
            print(f"{OUT} does not exist")
            return 1
        have = OUT.read_text(encoding="utf-8")
        if have != text:
            print(f"{OUT} differs from a fresh generation "
                  f"({len(have)} bytes on disk, {len(text)} generated)")
            return 1
        print(f"{OUT}: {len(lines)} cases, identical to a fresh generation")
        return 0

    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"{OUT}: {len(lines)} cases "
          f"({counts['ok']} run, {counts['refused']} refused), "
          f"{len(text):,} bytes")
    print(f"  body sha256 {header['body_sha256']}")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
