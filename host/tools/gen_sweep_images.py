#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The images host/tools/routine_sweep.c runs (parcel M4X, 2026-11-09).

    python3 -B host/tools/gen_sweep_images.py --out DIR [--names exp,sin] [--attrs rne,rtz,...]
                                              [--plant NAME] [--bound-shift S]

For each routine name and each rounding attribute at fp32 it writes, into the new directory DIR,

    <name>-fp32-<attr>.cftp    the program image: python/tests/mathlib_harness.r24_program(f), the shape the compiler inlines
                               (QUIET, the body, ENDQUIET, RAISE of the flag word, the result deposited, HALT), as seq.Program.to_bytes()
    <name>-fp32-<attr>.bank    the program's constant bank: n_consts fp32 words, little-endian, densely packed
    <name>-fp32-<attr>.marks   the lanes (encodings) that MUST mark, one 8-digit hex word a line, in ascending order; maybe none

and manifest.txt: a header, then one `image` line for each file set (name, attribute, instructions, words, the sha256 of each of
the three files, the fragment's dag_digest, the commit) and, for a name whose five attributes were all written, a `digest` line:
the first 32 bits of the sha256 of the five attributes' image and bank bytes, rne to rmm, image then bank, which is the `-d` word
routine-sweep's op names take. A name that is not built at fp32 (none of the four inverse routines: atan is parcel M4F1's, asin, acos and atan2 are parcel M4F2's) is
skipped and named, in the manifest and on stdout. A DIR that exists is refused (exit 2), nothing written.

The marks come from one table (MARKS): at fp32 exp marks five lanes under rtz, rdn and rup and none under rne and rmm (host/tests/
seq_check.py's routine_ln1p_marks derives them, and so does marks_exp() below: the floats nearest ln(1 + t) for t = 2^-23, 2^-22,
2^-21, -2^-22 and -2^-21). Every other file is empty until a sweep finds a lane the model says must mark. --plant NAME and
--bound-shift S build the fragment through mathlib.build (a plant of mathlib.PLANTS, TRIG_PLANTS ...; S is the in-lane bound's
widening, 34 for the G' = 6 of mathlib_harness.py's rate law); the marks table is the plain fragment's in either case, which is why
a `mark_silenced` image is red against it.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import struct
import subprocess
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "python"))
sys.path.insert(0, os.path.join(ROOT, "python", "tests"))

NAMES13 = ("exp", "exp2", "expm1", "log", "log2", "log1p", "sin", "cos", "tan", "atan", "asin", "acos", "atan2")
ATTRS = ("rne", "rtz", "rdn", "rup", "rmm")


def marks_exp(ml, fmt):
    """The five lanes of fp32 that exp marks under rtz, rdn and rup (seq_check.routine_ln1p_marks, derived the same way)."""
    import mpmath
    out = []
    with mpmath.workprec(4 * fmt.prec + 100):
        for t in (Fraction(1, 2 ** 23), Fraction(1, 2 ** 22), Fraction(1, 2 ** 21), Fraction(-1, 2 ** 22),
                  Fraction(-1, 2 ** 21)):
            v = mpmath.log(1 + mpmath.mpf(t.numerator) / t.denominator)
            out.append(ml._enc(fmt, ml._frac(v)))
    return sorted(out)


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def commit() -> str:
    try:
        r = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
        c = r.stdout.strip()
        return c if r.returncode == 0 and len(c) in (40, 64) else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="the directory to make (it must not exist)")
    ap.add_argument("--names", default=",".join(NAMES13), help="comma list of routine names (default: the thirteen)")
    ap.add_argument("--attrs", default=",".join(ATTRS), help="comma list of rne,rtz,rdn,rup,rmm (default: all five)")
    ap.add_argument("--plant", default=None, help="build every selected routine with this plant (mathlib.build's)")
    ap.add_argument("--bound-shift", type=int, default=0, help="widen the in-lane bound by 2^S (mathlib.build's bound_shift)")
    a = ap.parse_args(argv)
    names = [n for n in a.names.split(",") if n]
    attrs = [x for x in a.attrs.split(",") if x]
    for n in names:
        if n not in NAMES13:
            print(f"gen_sweep_images: unknown routine {n!r}; the thirteen are {', '.join(NAMES13)}", file=sys.stderr)
            return 2
    for x in attrs:
        if x not in ATTRS:
            print(f"gen_sweep_images: unknown attribute {x!r}; the five are {', '.join(ATTRS)}", file=sys.stderr)
            return 2
    if not names or not attrs:
        print("gen_sweep_images: no names or no attributes selected", file=sys.stderr)
        return 2
    if a.bound_shift < 0:
        print("gen_sweep_images: --bound-shift is not negative", file=sys.stderr)
        return 2
    if os.path.exists(a.out):
        print(f"gen_sweep_images: {a.out} exists; it is refused, nothing written", file=sys.stderr)
        return 2

    from cft_golden import FP32  # noqa: E402
    from cft_golden import mathlib as ml  # noqa: E402
    from cft_golden import softfloat as sf  # noqa: E402
    import mathlib_harness as har  # noqa: E402
    rnd_of = {sf.RND_NAMES[r]: r for r in sf.RND_NAMES}
    for x in attrs:
        assert x in rnd_of, (x, rnd_of)
    marks = {("exp", "rtz"): marks_exp(ml, FP32), ("exp", "rdn"): marks_exp(ml, FP32), ("exp", "rup"): marks_exp(ml, FP32)}
    built = set(ml.NAMES) | set(ml.TRIG_NAMES) | set(ml._INV_TW_BUILDERS)
    com = commit()
    files, lines, skipped, wrote = {}, [], [], {}
    for n in names:
        if n not in built:
            skipped.append(n)
            continue
        per = {}
        for x in attrs:
            rnd = rnd_of[x]
            try:
                if a.plant is None and a.bound_shift == 0:
                    f = ml.fragment(n, FP32, rnd)
                else:
                    f = ml.build(n, FP32, rnd, bound_shift=a.bound_shift, plant=a.plant).fragment()
            except ValueError as exc:
                print(f"gen_sweep_images: {n} {x}: {exc}", file=sys.stderr)
                return 2
            prog, bank = har.r24_program(f)
            image = prog.to_bytes()
            bankb = b"".join(struct.pack("<I", w) for w in bank)
            assert len(bankb) == 4 * prog.n_consts == 4 * len(bank), (n, x)
            mk = "".join(f"{m:08x}\n" for m in marks.get((n, x), [])).encode()
            stem = f"{n}-fp32-{x}"
            files[stem + ".cftp"], files[stem + ".bank"], files[stem + ".marks"] = image, bankb, mk
            per[x] = (image, bankb)
            lines.append(f"image {n} {x} instructions {len(prog.insns)} words {len(bank)} image_sha256 {sha(image)} "
                         f"bank_sha256 {sha(bankb)} marks_sha256 {sha(mk)} dag_digest {ml.dag_digest(f)} commit {com}")
        wrote[n] = per
    head = ["# routine-sweep images, written by host/tools/gen_sweep_images.py (parcel M4X)",
            f"commit {com}", f"plant {a.plant or 'none'}", f"bound_shift {a.bound_shift}",
            f"names {','.join(names)}", f"attrs {','.join(attrs)}"]
    tail = []
    for n in skipped:
        tail.append(f"skipped {n} not built at fp32")
    for n, per in wrote.items():
        if all(x in per for x in ATTRS):
            h = hashlib.sha256()
            for x in ATTRS:
                h.update(per[x][0])
                h.update(per[x][1])
            tail.append(f"digest {n} {h.hexdigest()[:8]}")
    os.makedirs(a.out)
    for k in sorted(files):
        with open(os.path.join(a.out, k), "wb") as fh:
            fh.write(files[k])
    with open(os.path.join(a.out, "manifest.txt"), "w", newline="\n") as fh:
        fh.write("\n".join(head + lines + tail) + "\n")
    print(f"gen_sweep_images: {len(files)} files and manifest.txt in {a.out}")
    for n in wrote:
        print(f"  {n}: {len(wrote[n])} attributes")
    for n in skipped:
        print(f"  {n}: skipped, not built at fp32")
    return 0


if __name__ == "__main__":
    sys.exit(main())
