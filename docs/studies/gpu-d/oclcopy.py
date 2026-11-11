#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""GPU-D's OpenCL C text: GPU-A's device copy of libcft's arithmetic
(devcopy.py's output: host/src with edit E1 alone) made OpenCL C 1.2 by a
fixed, listed and counted set of exact replacements, then joined with a
shim, GPU-A's lane and the kernel into ONE text for clCreateProgramWithSource.

    python3 oclcopy.py DEVSRC OUT.cl            # write, then check; prints the sha256
    python3 oclcopy.py DEVSRC OUT.cl --check    # check an existing text, write nothing
    python3 oclcopy.py DEVSRC - --selftest      # the plants: each must be refused

DEVSRC is a directory `devcopy.py --out` wrote. Every edit below is one
exact string replacement with the number of matches it must find, applied
to the copy in order. A count that differs refuses the copy and names the
edit, so a change in host/src that touches an edited line, or adds a second
match, stops the build here rather than slipping into the text:

  O1  the format table and its extern in __constant: OpenCL C 1.2 keeps
      program-scope data in the constant address space.
  O2  the identifier `half` renamed `half_`: `half` is a type name in OpenCL
      C. Seven uses, all in cft_sf_canonical_ranges (code, not comments).
  O3  the table's `name` field a __constant pointer: its initialisers are
      string literals, which are __constant data in OpenCL C.
  O4  cft_sf_reduce (the reduction tree) between #if 0 and #endif, on the
      blank lines around it: it recurses, OpenCL C has no recursion, and
      PoCL refused the whole program for it at link time. NOT syntax only:
      it takes a function out. Nothing in the text calls it (its only calls
      are its own), which derive() checks: outside the excluded lines the
      name appears once, as the prototype in softfloat.h.
  I   each #include line made a comment: the files are joined in include
      order instead (each keeps its guard), and <stdint.h>, <stddef.h> and
      <limits.h> are the shim's typedefs or OpenCL C's own size_t, INT_MAX.

The lane is not rewritten: gpua_fma_lane is taken from GPU-A's cft_fma.hip
byte for byte at every build (with CFT_HD empty it is OpenCL C), so it
cannot drift from GPU-A's. The kernel file around it is this study's.
Each part is preceded by #line, so a compiler names the original file and
line. --check derives the whole text again and compares byte for byte.
"""
import argparse
import hashlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HIP = HERE.parent / "gpu-a" / "cft_fma.hip"
KERNEL = HERE / "fma_kernel.cl"

# The copy's files in include order (cft_config.h first: bigint.h includes it).
ORDER = ("include/cft_config.h", "src/bigint.h", "src/softfloat.h",
         "src/bigint.c", "src/softfloat.c")

EDITS = (  # (kind, file, old, new, matches it must find)
    ("O1", "src/softfloat.h", b"extern const cft_fmt_desc cft_sf_formats[4];",
     b"extern __constant const cft_fmt_desc cft_sf_formats[4];", 1),
    ("O1", "src/softfloat.c", b"\nconst cft_fmt_desc cft_sf_formats[4] = {",
     b"\n__constant const cft_fmt_desc cft_sf_formats[4] = {", 1),
    ("O2", "src/softfloat.c", b"m = hi - lo, half;", b"m = hi - lo, half_;", 1),
    ("O2", "src/softfloat.c", b" half = 1;", b" half_ = 1;", 1),
    ("O2", "src/softfloat.c", b"while (half < m)", b"while (half_ < m)", 1),
    ("O2", "src/softfloat.c", b"half <<= 1;", b"half_ <<= 1;", 1),
    ("O2", "src/softfloat.c", b"half >>= 1;", b"half_ >>= 1;", 1),
    ("O2", "src/softfloat.c", b"= lo + half;", b"= lo + half_;", 2),
    ("O3", "src/softfloat.h", b"    const char *name;", b"    __constant const char *name;", 1),
    ("O4", "src/softfloat.c", b"}\n\nCFT_HD int cft_sf_reduce(const cft_fmt_desc *f, int op, int rnd,\n",
     b"}\n#if 0 /* O4: recursive, and OpenCL C has no recursion; nothing calls it */\n"
     b"CFT_HD int cft_sf_reduce(const cft_fmt_desc *f, int op, int rnd,\n", 1),
    ("O4", "src/softfloat.c", b"    *flags = lf | rf | af;\n    return 0;\n}\n\nCFT_HD int cft_sf_compute(",
     b"    *flags = lf | rf | af;\n    return 0;\n}\n#endif /* O4 */\nCFT_HD int cft_sf_compute(", 1),
    ("I", "include/cft_config.h", b"#include <limits.h>", b"/* I: <limits.h> */", 1),
    ("I", "src/bigint.h", b"#include <stdint.h>", b"/* I: <stdint.h> */", 1),
    ("I", "src/bigint.h", b'#include "../include/cft_config.h"',
     b'/* I: "../include/cft_config.h" */', 1),
    ("I", "src/softfloat.h", b"#include <stddef.h>", b"/* I: <stddef.h> */", 1),
    ("I", "src/softfloat.h", b'#include "bigint.h"', b'/* I: "bigint.h" */', 1),
    ("I", "src/bigint.c", b'#include "bigint.h"', b'/* I: "bigint.h" */', 1),
    ("I", "src/softfloat.c", b'#include "softfloat.h"', b'/* I: "softfloat.h" */', 1),
)

SHIM = b"""/* ---- oclcopy.py's shim: what host/src takes from <stdint.h>, in OpenCL C
 * 1.2's own types (char is signed, long is 64 bits); size_t and INT_MAX are
 * OpenCL C's. CFT_HD is devcopy.py's E1 macro, empty as on the CPU build. */
typedef char  int8_t;  typedef uchar  uint8_t;
typedef short int16_t; typedef ushort uint16_t;
typedef int   int32_t; typedef uint   uint32_t;
typedef long  int64_t; typedef ulong  uint64_t;
#define CFT_HD
"""

LANE_KEY = b"CFT_HD static void gpua_fma_lane("


def blob(data):
    """git's blob id of `data`: names the exact input without git."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def edit_files(files):
    """files: {name: bytes}. Applies EDITS in order; returns (edited, counts)."""
    out, counts = dict(files), {}
    for kind, name, old, new, want in EDITS:
        got = out[name].count(old)
        if got != want:
            raise ValueError(f"edit {kind} in {name}: {old.decode()!r} found {got} times, "
                             f"not {want}")
        out[name] = out[name].replace(old, new)
        counts[kind] = counts.get(kind, 0) + want
    return out, counts


def no_caller(text):
    """O4's function must have no caller left: outside its #if 0 the name
    appears once in the whole text, as softfloat.h's prototype."""
    lo, hi = text.index(b"#if 0 /* O4"), text.index(b"#endif /* O4 */")
    n = (text[:lo] + text[hi:]).count(b"cft_sf_reduce(")
    if n != 1:
        raise ValueError(f"O4: cft_sf_reduce( appears {n} times outside the excluded "
                         f"lines, not once (a caller was added?)")


def lane(hip):
    """gpua_fma_lane from cft_fma.hip, byte for byte: (first line number, text)."""
    lines = hip.splitlines(keepends=True)
    hits = [i for i, ln in enumerate(lines) if ln.startswith(LANE_KEY)]
    if len(hits) != 1:
        raise ValueError(f"cft_fma.hip: {LANE_KEY.decode()!r} found {len(hits)} times, not once")
    end = next(j for j in range(hits[0], len(lines)) if lines[j] == b"}\n")
    return hits[0] + 1, b"".join(lines[hits[0]:end + 1])


def derive(files, hip, kernel):
    """The whole text, and the edit counts. Deterministic: no date, no path."""
    edited, counts = edit_files(files)
    first, lane_text = lane(hip)
    head = [b"/* GENERATED by docs/studies/gpu-d/oclcopy.py - do not edit. libcft's arithmetic\n",
            b" * (host/src through GPU-A's devcopy.py, E1) as OpenCL C 1.2, edits "]
    head.append(b", ".join(b"%s %d" % (k.encode(), n) for k, n in sorted(counts.items())))
    head.append(b"; inputs by git blob id:\n")
    for name in ORDER:
        head.append(b" *   %s %s\n" % (name.encode(), blob(files[name]).encode()))
    head.append(b" *   cft_fma.hip %s (gpua_fma_lane, line %d)\n" % (blob(hip).encode(), first))
    head.append(b" *   fma_kernel.cl %s\n */\n" % blob(kernel).encode())
    parts = [b"".join(head), SHIM]
    for name in ORDER:
        parts.append(b'#line 1 "%s"\n' % name.encode() + edited[name])
    parts.append(b'#line %d "cft_fma.hip"\n' % first + lane_text)
    parts.append(b'#line 1 "fma_kernel.cl"\n' + kernel)
    text = b"".join(parts)
    no_caller(text)
    return text, counts


def read_inputs(devsrc, hip_path, kernel_path):
    files = {name: (devsrc / name).read_bytes() for name in ORDER}
    return files, hip_path.read_bytes(), kernel_path.read_bytes()


def check(text, want):
    """Refuse a text that is not the derivation byte for byte, naming the line."""
    if text == want:
        return
    for i, (a, b) in enumerate(zip(text.splitlines(), want.splitlines()), 1):
        if a != b:
            raise ValueError(f"the text's line {i} is not the derivation's: "
                             f"{a.decode('ascii', 'replace')!r}")
    raise ValueError("the text and the derivation differ in length (a line added or removed)")


def selftest(files, hip, kernel):
    """Plant a fault of each kind the counts and the check exist for; each must
    be refused by name. Then the honest derivation must pass."""
    good, _ = derive(files, hip, kernel)
    sf = files["src/softfloat.c"]
    plants = {
        "host/src's table line changed (O1 finds 0)":
            ("files", dict(files, **{"src/softfloat.c": sf.replace(
                b"\nconst cft_fmt_desc cft_sf_formats[4] = {",
                b"\nconst cft_fmt_desc  cft_sf_formats[4] = {", 1)})),
        "a second `half >>= 1;` in host/src (O2 finds 2)":
            ("files", dict(files, **{"src/softfloat.c": sf.replace(
                b"half >>= 1;", b"half >>= 1;\n            half >>= 1;", 1)})),
        "an include added to bigint.h (the text would miss it)":
            ("files", dict(files, **{"src/bigint.h": files["src/bigint.h"].replace(
                b"#include <stdint.h>", b"#include <stdint.h>\n#include <string.h>", 1)})),
        "the lane edited in cft_fma.hip (the check of the old text)":
            ("hip", hip.replace(b"rnd = CFT_SF_RNE;", b"rnd = CFT_SF_RTZ;", 1)),
        "a caller of the excluded cft_sf_reduce in the kernel (O4's check)":
            ("kernel", kernel + b"int x(void) { return cft_sf_reduce(0, 0, 0, 0, 0, 0, 0, 0, 0, 0); }\n"),
        "one byte of the written text changed":
            ("text", good.replace(b"half_ = 1;", b"half_ = 2;", 1)),
    }
    bad = 0
    for what, (kind, val) in plants.items():
        try:
            if kind == "files":
                text, _ = derive(val, hip, kernel)
                if b"#include <" in text:
                    raise ValueError("an #include survived the edits: "
                                     + text[text.index(b"#include <"):].split(b"\n")[0].decode())
                check(good, text)
            elif kind == "hip":
                check(good, derive(files, val, kernel)[0])
            elif kind == "kernel":
                check(good, derive(files, hip, val)[0])
            else:
                check(val, good)
            print(f"selftest: plant '{what}' PASSED - the check is broken")
            bad += 1
        except ValueError as e:
            print(f"selftest: plant '{what}' refused: {e}")
    check(good, derive(files, hip, kernel)[0])
    print(f"selftest: honest text accepted, sha256 {hashlib.sha256(good).hexdigest()}")
    if bad:
        sys.exit(1)
    print(f"selftest: OK, {len(plants)} plants refused by name")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("devsrc", type=Path)
    ap.add_argument("out")
    ap.add_argument("--hip", type=Path, default=HIP)
    ap.add_argument("--kernel", type=Path, default=KERNEL)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    try:
        files, hip, kernel = read_inputs(a.devsrc, a.hip, a.kernel)
        if a.selftest:
            return selftest(files, hip, kernel)
        text, counts = derive(files, hip, kernel)
        if b"#include <" in text or b'#include "' in text:
            raise ValueError("an #include survived the edits")
        if not a.check:
            Path(a.out).write_bytes(text)
        check(Path(a.out).read_bytes(), text)
        print(f"oclcopy: {len(ORDER)} files + gpua_fma_lane + fma_kernel.cl -> {Path(a.out).name}: "
              f"edits {', '.join(f'{k} {n}' for k, n in sorted(counts.items()))}, "
              f"no other difference; {len(text)} bytes, sha256 {hashlib.sha256(text).hexdigest()}")
    except (ValueError, OSError) as e:
        print(f"oclcopy: REFUSED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
