# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The reference assembler, as a pipe, so a JavaScript test can hold its
own encoder to it.

    echo '[{"name":"x","text":".format fp64\\n.deposits 1\\nhalt\\n"}]' \
        | python bindings/node/asm_ref.py

Reads a JSON array of `{name, text}` on stdin, where `text` is `.cfta`
source (docs/PROGRAMS.md), and writes one JSON object on stdout:

    {"python": "3.12.9",
     "programs": {"<name>": {"hex": ..., "format": "fp64", "n_insns": 3,
                             "n_consts": 2, "max_deposits": 1,
                             "flags": 1, "digest": "<sha256 of the image>",
                             "features": ["BANK_PTR"]},
                  ...},
     "errors": {"<name>": "<why it was refused>"}}

WHY THIS EXISTS. `python/cft_golden/asm.py` is the reference encoder
and `bindings/node/seq_corpus.mjs` carries a second one, because a test
that writes a program by hand needs one and a binding is not the place
for an assembler. Two encoders are two opinions about the instruction
word unless something compares them, and revision 2 gave them something
new to disagree about: which bit of `imm[27:24]` is which register's
fifth (docs/SEQUENCER.md R1), and whether a `BANK_EXT` header means an
image with no constant section or an image with a zero `n_consts` (R3).
Neither disagreement is visible in a round trip through ONE of them -
a permuted register-high-bit assembles and disassembles perfectly - so
the comparison has to be between the two, over the same program, in
bytes. `.cfta` text is the shared spelling of "the same program".

This is the pipe and not an import because `bindings/node` is a wasm
module and a JavaScript harness, and the whole point of it is that it
runs where a toolchain does not (make_seq_corpus.py says the same about
the corpus). program_test.mjs SKIPS by name when this cannot run;
`host/tests/seq_check.py` and `make programs-check` remain the gates
that need the toolchain.
"""

import json
import platform
import sys
from pathlib import Path

# The model lives beside the tree, not on the path: this file is under
# bindings/node/ and cft_golden is under python/. Derived from __file__
# rather than assumed to be the working directory, because the caller is
# a node process whose cwd is its own business.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))

from cft_golden import asm  # noqa: E402


def one(text, banks=()):
    """-> the reference's own answer for one source, as plain JSON.

    `banks` are hex strings: the constant banks this program will be run
    with, so the reference can state the digest of image AND data
    together for each. That is the number `cft_program_digest` returns
    and the one a plate's attestation carries, and it is only checkable
    across the two implementations if both are asked about the same
    bank.
    """
    image = asm.assemble(text)
    img = asm.Image.from_bytes(image)
    # The round trip is asserted HERE rather than in JavaScript because
    # it is a property of the reference and not of the comparison: an
    # image the reference cannot re-assemble from its own disassembly is
    # not a fixed point, and comparing bytes against it would be
    # comparing against something that moves.
    again = asm.assemble(asm.disassemble(image))
    if again != image:
        raise asm.AsmError(
            "the reference does not round-trip this program: "
            f"{len(image)} bytes in, {len(again)} out")
    return {
        "hex": image.hex(),
        "format": img.fmt.name,
        "n_insns": len(img.insns),
        "n_consts": img.n_consts,
        "max_deposits": img.max_deposits,
        "flags": img.flags,
        "bank_external": bool(img.bank_external),
        # Image.digest() answers hex, and takes the bank the run
        # supplies. The empty bank is the image alone, which is the
        # only form a program carrying its own constants accepts.
        "digest": img.digest(),
        "bank_digests": [img.digest(bytes.fromhex(b)) for b in banks],
    }


def main():
    spec = json.load(sys.stdin)
    out = {"python": platform.python_version(), "programs": {}, "errors": {}}
    for entry in spec:
        name = entry["name"]
        try:
            out["programs"][name] = one(entry["text"], entry.get("banks", ()))
        except Exception as exc:               # noqa: BLE001 - reported, not raised
            out["errors"][name] = f"{type(exc).__name__}: {exc}"
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
