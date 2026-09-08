# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Assemble every `.cfta` in programs/ with cft-asm, and write MANIFEST.

`make programs` at the repo root is this script. The images land in
programs/out, which is gitignored - what is committed is the sources
and the MANIFEST, so a rebuild that changes one byte of one image is a
line in a diff rather than a silent difference between two people's
trees.

The hash is of the image cft-asm produced. programs/check.py then
re-assembles every source with python/cft_golden/asm.py and compares
byte for byte, which is what makes the MANIFEST a claim about the
FORMAT rather than about one compiler's output.
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asm", required=True, help="the cft-asm binary")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--manifest", default=str(HERE / "MANIFEST"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sources = sorted(HERE.glob("*.cfta"))
    if not sources:
        sys.exit("programs/: no .cfta sources")

    lines = []
    for src in sources:
        image = out / (src.stem + ".cftp")
        r = subprocess.run([args.asm, str(src), "-o", str(image)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.stderr.write(r.stdout + r.stderr)
            sys.exit(f"cft-asm refused {src.name}")
        data = image.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        lines.append(f"{digest}  {image.name}")
        print(f"  {image.name:<26} {len(data):>7} bytes  {digest[:16]}")

    text = (
        "# programs/MANIFEST - sha256 of every built image.\n"
        "#\n"
        "# Written by `make programs` (programs/build.py) and checked by\n"
        "# `make programs-check`. The images themselves are gitignored:\n"
        "# these hashes are what the tree commits, so an assembler change\n"
        "# that moves a byte shows up as a diff here and has to be\n"
        "# explained rather than noticed later.\n"
        "#\n"
        "# sha256                                                            "
        "  image\n"
        + "\n".join(lines) + "\n")
    Path(args.manifest).write_text(text, encoding="utf-8", newline="\n")
    print(f"  MANIFEST: {len(lines)} images")


if __name__ == "__main__":
    main()
