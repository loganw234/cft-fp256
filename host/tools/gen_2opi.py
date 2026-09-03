# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Emit host/src/mp_2opi.h - the Payne-Hanek reduction constant.

    python3 host/tools/gen_2opi.py                 # write the header
    python3 host/tools/gen_2opi.py --check         # verify it

One number, 2/pi, to 270,336 bits. It is the only thing phase 3 needs
that phases 1 and 2 did not, and it is big because the exponent RANGE
sets its size rather than the precision does.

WHY 270,336 BITS. The reduction computes x mod (pi/2) by multiplying
the operand's integer significand into a WINDOW of the binary expansion
of 2/pi. Write |x| = m * 2^e with m the p-bit significand. In

    x * (2/pi) = m * sum_j b_j 2^(e-j)          2/pi = sum_{j>=1} b_j 2^-j

every term with e - j >= 2 is m times a multiple of 4, so it cannot
change the quadrant and cannot change the fraction: the window may
START at bit j0 = max(1, e-1) and everything above it is dropped
exactly. The window's WIDTH is a working-precision question, and the
window's START is an exponent-range question, so the constant has to
reach

    (largest e on the ladder) - 1 + (widest window the reduction uses)

bits. The largest e is fp256's emax - man_w = 262143 - 236 = 261,907,
because the significand carries the other 236 bits of the exponent
range; the widest window is CFT_TR_PH_WINDOW_MAX = 8192 bits
(host/src/transcend.h), which is what the deepest cancellation the
reduction provides for costs. That is 261,906 + 8,192 = 270,098 bits,
rounded up to a whole number of 32-bit limbs with margin: 270,336 bits,
8,448 limbs, 33 KiB of const data.

docs/TRANSCENDENTALS.md's phase-3 section does that arithmetic again
and derives the cancellation allowance the 8,192 buys, per format.

WHY IT IS GENERATED. The same reason the six in mp_consts.h are: a
hand-typed constant has been wrong in this project three times, and a
wrong one here would not crash - it would silently return the sine of
a slightly different number. So:

  * this script emits the header from mpmath;
  * `--check` regenerates and compares byte for byte, and
    python/tests/test_mp_consts.py runs that on every test run;
  * that same test INDEPENDENTLY re-derives 2/pi from Chudnovsky's
    series with binary splitting, in plain Python integers, sharing no
    code with mpmath - Machin in Fractions, which is what phase 2 used
    for pi at 1088 bits, is far too slow at a quarter of a million;
  * cft_mp_two_over_pi_selfcheck() in the C checks the stored top limbs
    against 2/pi derived from the INDEPENDENTLY verified pi already in
    mp_consts.h, and a checksum over every limb.

The bit order is big-endian WITHIN the array and within each word:
word k holds bits b_{32k+1} .. b_{32k+32}, most significant first. That
is the order the reduction reads them in - a window starting at an
arbitrary bit is one shift-and-or per word - and it is not the
little-endian limb order mp_consts.h uses, because that header stores a
NUMBER and this one stores a BIT STREAM.
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "host" / "src" / "mp_2opi.h"

#: fp256's emax - man_w: the largest exponent of an integer significand
#: anywhere on the interchange ladder, and therefore the deepest the
#: reduction's window can START.
E_MAX = 262143 - 236

#: CFT_TR_PH_WINDOW_MAX in host/src/transcend.h. Kept in sync by
#: python/tests/test_mp_consts.py, which reads the C and fails if the
#: two ever disagree - a window wider than the constant would read off
#: the end of the array.
WINDOW_MAX = 8192

#: (E_MAX - 1) + WINDOW_MAX, rounded up to a whole number of limbs with
#: margin. The margin is 238 bits, which is a whole fp256 significand.
BITS = 270336
WORDS = BITS // 32

assert BITS >= (E_MAX - 1) + WINDOW_MAX
assert BITS % 32 == 0


def two_over_pi_bits(nbits):
    """floor(2/pi * 2^nbits) as an integer: the first `nbits` binary
    digits of 2/pi, truncated toward zero.

    mpmath computes pi with its own algorithm at nbits + 128 bits; the
    truncation here is the only rounding, and it is downward, so every
    stored bit is a true bit of 2/pi."""
    import mpmath
    mpmath.mp.prec = nbits + 256
    v = 2 / mpmath.pi
    man, exp = mpmath.libmp.to_man_exp(v._mpf_)
    man = int(man)
    assert man > 0
    # value == man * 2^exp, and 1/2 < value < 1, so man.bit_length() + exp == 0
    assert man.bit_length() + exp == 0, (man.bit_length(), exp)
    shift = nbits - man.bit_length()
    return man << shift if shift >= 0 else man >> -shift


def fnv1a64(words):
    """FNV-1a over the limbs, little-endian byte order within each.

    A checksum, not a proof: it says the array in the binary is the
    array the generator emitted - it catches a truncation, a byte swap
    or an edit - and it says nothing whatever about those bits being
    2/pi's. Only regenerating (or the independent derivation in
    python/tests/test_mp_consts.py) says that."""
    h = 0xCBF29CE484222325
    for w in words:
        for k in range(4):
            h ^= (w >> (8 * k)) & 0xFF
            h = (h * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def words_of(bits):
    """The bit stream as WORDS 32-bit words, most significant bit of
    2/pi first."""
    return [(bits >> (BITS - 32 * (k + 1))) & 0xFFFFFFFF
            for k in range(WORDS)]


def render():
    value = two_over_pi_bits(BITS)
    words = words_of(value)
    checksum = fnv1a64(words)

    lines = []
    add = lines.append
    add("/* Copyright 2026 Logan W.")
    add(" * SPDX-License-Identifier: Apache-2.0")
    add(" *")
    add(" * GENERATED by host/tools/gen_2opi.py - do not edit.")
    add(" *")
    add(f" * 2/pi to {BITS:,} bits, truncated toward zero, as a BIT STREAM:")
    add(" * word k holds bits b_(32k+1) .. b_(32k+32) of")
    add(" *")
    add(" *     2/pi = 0.b1 b2 b3 ...      (binary)")
    add(" *")
    add(" * most significant first within the word. That is the order the")
    add(" * Payne-Hanek reduction in host/src/transcend.c reads them in -")
    add(" * a window starting at an arbitrary bit is one shift-and-or per")
    add(" * word - and it is deliberately NOT the little-endian limb order")
    add(" * of mp_consts.h, which stores numbers rather than a stream.")
    add(" *")
    add(f" * Why {BITS:,}: the window may start as deep as bit"
        f" {E_MAX - 1:,}")
    add(" * (fp256's emax - man_w, less one) and may be as wide as")
    add(f" * CFT_TR_PH_WINDOW_MAX = {WINDOW_MAX:,} bits, so the last bit the")
    add(f" * reduction can ask for is {(E_MAX - 1) + WINDOW_MAX:,}."
        " The rest is margin,")
    add(" * rounded up to a whole number of limbs. gen_2opi.py derives it.")
    add(" *")
    add(" * Regenerate with `python3 host/tools/gen_2opi.py`;")
    add(" * python/tests/test_mp_consts.py fails if this file and the")
    add(" * script disagree, AND re-derives the value from Chudnovsky's")
    add(" * series in plain Python integers, which shares nothing with")
    add(" * mpmath. cft_mp_two_over_pi_selfcheck() checks the top of the")
    add(" * array against pi and the whole of it against the checksum.")
    add(" */")
    add("")
    add("#ifndef CFT_MP_2OPI_H")
    add("#define CFT_MP_2OPI_H")
    add("")
    add("#include <stdint.h>")
    add("")
    add(f"#define CFT_TWO_OVER_PI_BITS  {BITS}")
    add(f"#define CFT_TWO_OVER_PI_WORDS {WORDS}")
    add("")
    add("/* FNV-1a over the array below, little-endian bytes within each")
    add(" * word. Proves the array in the binary is the array emitted")
    add(" * here; proves nothing about those bits being 2/pi's. */")
    add(f"#define CFT_TWO_OVER_PI_FNV1A UINT64_C(0x{checksum:016x})")
    add("")
    add("static const uint32_t")
    add("cft_two_over_pi[CFT_TWO_OVER_PI_WORDS] = {")
    for i in range(0, WORDS, 6):
        row = " ".join(f"0x{w:08x}u," for w in words[i:i + 6])
        add(f"    {row}")
    add("};")
    add("")
    add("#endif /* CFT_MP_2OPI_H */")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify the committed header instead of writing it")
    ap.add_argument("--out", default=str(HEADER))
    args = ap.parse_args()
    text = render()
    out = Path(args.out)
    if args.check:
        if not out.exists():
            print(f"{out}: missing", file=sys.stderr)
            return 1
        if out.read_text() != text:
            print(f"{out}: does NOT match what the generator emits - "
                  "regenerate it (python3 host/tools/gen_2opi.py)",
                  file=sys.stderr)
            return 1
        print(f"{out}: matches the generator, 2/pi at {BITS} bits")
        return 0
    out.write_text(text)
    print(f"{out}: 2/pi at {BITS} bits ({WORDS} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
