#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""GPU-G's probe page data. run_gpug.sh calls it twice:

    python3 make_probe.py subset CORPUS_DIR SUBSET_DIR
    python3 make_probe.py page SUBSET_DIR RUN_DIR PAGE_IN PAGE_OUT

subset  takes from GPU-A's conformance corpora (conf-fp32 .. conf-fp256, every FMA case of
        the published vectors' elementwise sets, the five attributes in file order) every
        k-th case from the first, k = n // 1024: 1,024 a format, in GPU-A's corpus layout.
page    writes PAGE_IN with its two marked regions filled: the digests the page checks
        (each WGSL module, each subset; each module's d || flags as PoCL computed it on
        each subset, read from run_gpug.sh's harness logs), and ONE base64 blob, gzip of a
        header and the parts. It refuses unless the plain module is GREEN on PoCL in every
        format and each plant RED in at least one. Deterministic: gzip's mtime is 0.
"""
import base64
import gzip
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

FMTS = ("fp32", "fp64", "fp128", "fp256")
MODS = ("plain", "rmm-as-rne", "drop-flag")
PER = 1024
CHECK = re.compile(r"(\d+) results and (\d+) flags differ, (\d+) refused;.*sha256 ([0-9a-f]{64});.*: (RED|GREEN)$")


def sha(b):
    return hashlib.sha256(b).hexdigest()


def read_corpus(path):
    raw = path.read_bytes()
    if raw[:8] != b"CFTGPUA1":
        raise ValueError(f"{path}: not a GPU-A corpus")
    fmt, esz, n = struct.unpack_from("<IIQ", raw, 8)
    off, cols = 24, {}
    for name, w in (("a", esz), ("b", esz), ("c", esz), ("rnd", 1), ("d", esz), ("fl", 1)):
        cols[name] = [raw[off + i * w: off + (i + 1) * w] for i in range(n)]
        off += n * w
    if off != len(raw):
        raise ValueError(f"{path}: header does not match its size")
    return fmt, esz, n, cols


def subset(cdir, sdir):
    sdir.mkdir(parents=True, exist_ok=False)
    for name in FMTS:
        fmt, esz, n, cols = read_corpus(cdir / f"conf-{name}.bin")
        k = n // PER
        idx = [i * k for i in range(PER)]
        body = b"".join(b"".join(cols[c][i] for i in idx) for c in ("a", "b", "c", "rnd", "d", "fl"))
        out = b"CFTGPUA1" + struct.pack("<IIQ", fmt, esz, PER) + body
        (sdir / f"probe-{name}.bin").write_bytes(out)
        rn = [cols["rnd"][i][0] for i in idx]
        print(f"subset: conf-{name}.bin, {n} cases, every {k}th from case 0: {PER} cases "
              f"(rne {rn.count(0)} rtz {rn.count(1)} rdn {rn.count(2)} rup {rn.count(3)} rmm {rn.count(4)}), "
              f"{len(out)} B, sha256 {sha(out)}")


def page(sdir, rdir, page_in, page_out):
    parts = [(m, (rdir / f"fma-{m}.wgsl").read_bytes()) for m in MODS]
    parts += [(f"probe-{f}", (sdir / f"probe-{f}.bin").read_bytes()) for f in FMTS]
    want, diffs = {}, {}
    for m in MODS:
        for f in FMTS:
            last = (sdir / f"{m}-{f}.txt").read_text().strip().splitlines()[-1]
            g = CHECK.search(last)
            if not g:
                raise ValueError(f"{m} {f}: no check line in the harness log: {last[:120]!r}")
            want[f"{m}/{f}"], diffs[f"{m}/{f}"] = g.group(4), [int(g.group(1)), int(g.group(2)), g.group(5)]
            cols = read_corpus(sdir / f"probe-{f}.bin")[3]
            exp = sha(b"".join(cols["d"]) + b"".join(cols["fl"]))
            if m == "plain" and (g.group(5) != "GREEN" or g.group(4) != exp):
                raise ValueError(f"plain {f}: PoCL not GREEN at the subset's expected sum: {last[:160]!r}")
        if m != "plain" and all(diffs[f"{m}/{f}"][2] == "GREEN" for f in FMTS):
            raise ValueError(f"plant {m}: GREEN on every subset on PoCL, so the page could not see it")
    head, offs, body = [], 0, []
    for name, b in parts:
        head.append({"name": name, "offset": offs, "length": len(b)})
        offs += len(b)
        body.append(b)
    hj = json.dumps({"blob": "GPU-G probe 1", "parts": head}, separators=(",", ":")).encode()
    raw = struct.pack("<I", len(hj)) + hj + b"".join(body)
    gz = gzip.compress(raw, compresslevel=9, mtime=0)
    b64 = base64.b64encode(gz).decode()
    blob = "\n".join(b64[i:i + 100] for i in range(0, len(b64), 100))
    consts = ("const SHA = %s;\nconst OUT = %s;\nconst POCL = %s;\nconst BLOB = {gzip: %d, raw: %d};"
              % (json.dumps({n: sha(b) for n, b in parts}, indent=1), json.dumps(want, indent=1),
                 json.dumps(diffs, separators=(",", ":")), len(gz), len(raw)))
    text = page_in.read_text()
    for tag, fill in (("DATA", consts), ("BLOB", blob)):
        a, z = f"/* BEGIN {tag} */", f"/* END {tag} */"
        if text.count(a) != 1 or text.count(z) != 1:
            raise ValueError(f"{page_in}: the {tag} markers are not there once each")
        text = text[:text.index(a) + len(a)] + "\n" + fill + "\n" + text[text.index(z):]
    Path(page_out).write_text(text, newline="\n")
    apart = sum(len(gzip.compress(b, compresslevel=9, mtime=0)) for _, b in parts)
    print(f"page: {len(parts)} parts, {len(raw)} B; ONE gzip blob {len(gz)} B (the parts gzipped apart: "
          f"{apart} B), base64 {len(b64)} B on {blob.count(chr(10)) + 1} lines; -> {Path(page_out).name}, "
          f"{len(text.encode())} B, sha256 {sha(text.encode())}")
    for m in MODS:
        print(f"page: {m}: " + "; ".join(f"{f} {diffs[f'{m}/{f}'][0]} results and {diffs[f'{m}/{f}'][1]} "
                                          f"flags differ, {diffs[f'{m}/{f}'][2]}" for f in FMTS))


def main():
    a = sys.argv[1:]
    try:
        if len(a) == 3 and a[0] == "subset":
            subset(Path(a[1]), Path(a[2]))
        elif len(a) == 5 and a[0] == "page":
            page(Path(a[1]), Path(a[2]), Path(a[3]), a[4])
        else:
            sys.exit(__doc__)
    except (ValueError, OSError) as e:
        print(f"make_probe: REFUSED: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
