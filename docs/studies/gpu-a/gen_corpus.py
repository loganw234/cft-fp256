#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""GPU-A's corpora, every expected value from python/cft_golden (the
authority). Run from the repository root; everything is written to OUT,
never into the tree.

    python -B docs/studies/gpu-a/gen_corpus.py conformance OUT [--jobs 2]
    python -B docs/studies/gpu-a/gen_corpus.py stream OUT [--triples 200000]
    python -B docs/studies/gpu-a/gen_corpus.py flip IN OUT --index K --bit B
    python -B docs/studies/gpu-a/gen_corpus.py verify CORPUS DEVICE_OUTPUT
    python -B docs/studies/gpu-a/gen_corpus.py show FILE...

conformance  runs vectors/gen_vectors.py for the twenty elementwise sets at
             `make vectors`' counts, refuses unless each set's sha256 is the
             line vectors/SHA256SUMS records for it, and keeps every "fma"
             case: conf-<fmt>.bin, the five attributes in file order.
stream       a seeded stream: vectors.random_cases' adversarial strategies
             (alignment, cancellation, both range edges, ties, raw bits),
             the FMA triples only, each under all five attributes, expected
             (bits, flags) from softfloat.fma: stream-<fmt>.bin.
flip         a plant: a copy with one bit of one expected result flipped.
verify       an independent check of a device's output file: compares it
             with the corpus in Python and prints hashlib's sha256 of it.

A corpus file, little-endian: b"CFTGPUA1", u32 format code (0 fp32 .. 3
fp256), u32 element bytes, u64 n; then a, b, c (n elements each), rnd
(n bytes), the expected d (n elements) and the expected flags (n bytes). A
device writes d || flags in the same layout, so a device that agrees on
every case writes exactly the corpus's tail and its sha256 is the
"expect" sum printed here.
"""
import argparse
import concurrent.futures
import functools
import hashlib
import json
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FMT_CODE = {"fp32": 0, "fp64": 1, "fp128": 2, "fp256": 3}
CODE_FMT = {v: k for k, v in FMT_CODE.items()}
RNDS = ("rne", "rtz", "rdn", "rup", "rmm")          # 0..4, RISC-V frm
MAGIC = b"CFTGPUA1"
# `make vectors` (Makefile:117): the elementwise sets' counts and seed.
CONF_ARGS = ["--formats", "fp32", "fp64", "fp128", "fp256",
             "--rounding", *RNDS, "--directed", "3000", "--random", "4000",
             "--simple", "200", "--transcend", "0", "--minmaxmag", "0",
             "--augmented", "0", "--formatof", "0"]
STREAM_SEED = 20261110


def sha(data):
    return hashlib.sha256(data).hexdigest()


def golden():
    """The model, imported only by the commands that need it, so that flip,
    verify and show run on a host without the model's dependencies."""
    sys.path.insert(0, str(ROOT / "python"))
    from cft_golden import FORMATS, softfloat, vectors
    return FORMATS, softfloat, vectors


def write_corpus(path, fname, rows):
    """rows: (rnd, a, b, c, d, flags) with integer encodings."""
    esz = {"fp32": 4, "fp64": 8, "fp128": 16, "fp256": 32}[fname]
    n = len(rows)
    cols = [b"".join(r[k].to_bytes(esz, "little") for r in rows) for k in (1, 2, 3)]
    rnd = bytes(r[0] for r in rows)
    tail = b"".join(r[4].to_bytes(esz, "little") for r in rows) + bytes(r[5] for r in rows)
    data = MAGIC + struct.pack("<IIQ", FMT_CODE[fname], esz, n) + b"".join(cols) + rnd + tail
    Path(path).write_bytes(data)
    return data, tail


def read_corpus(path):
    data = Path(path).read_bytes()
    if data[:8] != MAGIC:
        raise SystemExit(f"{path}: not a GPU-A corpus")
    code, esz, n = struct.unpack("<IIQ", data[8:24])
    off = 24 + 3 * n * esz + n
    return dict(fmt=CODE_FMT[code], esz=esz, n=n, data=data,
                rnd=data[24 + 3 * n * esz:off], tail=data[off:])


def describe(path, data, tail, fname, rows):
    per = [sum(1 for r in rows if r[0] == k) for k in range(5)]
    print(f"{Path(path).name}: {fname}, {len(rows)} cases "
          f"({', '.join(f'{RNDS[k]} {per[k]}' for k in range(5))}); "
          f"file sha256 {sha(data)}; expect {sha(tail)}", flush=True)


def conformance(out, jobs):
    vout = out / "vectors"
    t0 = time.perf_counter()
    subprocess.run([sys.executable, "-B", str(ROOT / "vectors/gen_vectors.py"),
                    "--out", str(vout), "--jobs", str(jobs), *CONF_ARGS],
                   check=True, stdout=subprocess.DEVNULL)
    print(f"gen_vectors.py: 20 elementwise sets in {time.perf_counter() - t0:.1f} s")
    record = {}
    for line in (ROOT / "vectors/SHA256SUMS").read_text().splitlines():
        digest, name = line.split()
        record[name.replace("out/", "", 1)] = digest
    for fname in FMT_CODE:
        rows = []
        for k, rname in enumerate(RNDS):
            set_name = fname + ("" if rname == "rne" else f"-{rname}") + ".jsonl"
            raw = (vout / set_name).read_bytes()
            if sha(raw) != record.get(set_name):
                raise SystemExit(f"REFUSED: {set_name} is not the published set "
                                 f"({sha(raw)} against {record.get(set_name)})")
            for line in raw.decode().splitlines():
                rec = json.loads(line)
                if rec["op"] != "fma":
                    continue
                assert rec["rnd"] == rname, set_name
                rows.append((k, int(rec["a"], 16), int(rec["b"], 16), int(rec["c"], 16),
                             int(rec["d"], 16), rec["flags"]))
        print(f"{fname}: 5 sets = vectors/SHA256SUMS")
        path = out / f"conf-{fname}.bin"
        data, tail = write_corpus(path, fname, rows)
        describe(path, data, tail, fname, rows)


@functools.lru_cache(maxsize=2)
def stream_triples(fname, triples, seed):
    FORMATS, sf, vectors = golden()
    fmt = FORMATS[fname]
    draw = triples + triples // 2
    while True:
        cases = [c for c in vectors.random_cases(fmt, draw, seed) if c[0] == sf.OP_FMA]
        if len(cases) >= triples:
            return tuple(cases[:triples])
        draw *= 2


def stream_part(args):
    fname, triples, seed, k = args
    FORMATS, sf, _vectors = golden()
    fmt = FORMATS[fname]
    t0 = time.perf_counter()
    rows = [(k, a, b, c) + sf.fma(fmt, a, b, c, k)
            for _op, a, b, c in stream_triples(fname, triples, seed)]
    return fname, k, rows, time.perf_counter() - t0


def stream(out, triples, seed, jobs):
    work = [(f, triples, seed + FMT_CODE[f], k) for f in reversed(list(FMT_CODE))
            for k in range(5)]
    parts, cpu = {}, {}
    t0 = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as ex:
        for fname, k, rows, secs in ex.map(stream_part, work):
            parts[(fname, k)] = rows
            cpu[fname] = cpu.get(fname, 0.0) + secs
    print(f"stream: {len(work) * triples} golden FMAs in {time.perf_counter() - t0:.1f} s "
          f"wall with {jobs} workers (seed {seed} + format code)")
    for fname in FMT_CODE:
        rows = [r for k in range(5) for r in parts[(fname, k)]]
        print(f"  {fname}: {5 * triples} FMAs, {cpu[fname]:.1f} s in the model "
              f"({1e6 * cpu[fname] / (5 * triples):.1f} us each, triples drawn included)")
        path = out / f"stream-{fname}.bin"
        data, tail = write_corpus(path, fname, rows)
        describe(path, data, tail, fname, rows)


def flip(src, dst, index, bit):
    c = read_corpus(src)
    if not (0 <= index < c["n"]) or not (0 <= bit < 8 * c["esz"]):
        raise SystemExit("index or bit out of range")
    data = bytearray(c["data"])
    off = len(data) - len(c["tail"]) + index * c["esz"] + bit // 8
    data[off] ^= 1 << (bit % 8)
    Path(dst).write_bytes(bytes(data))
    print(f"flip: {Path(dst).name} = {Path(src).name} with bit {bit} of expected "
          f"d[{index}] flipped; expect {sha(bytes(data[len(data) - len(c['tail']):]))}")


def verify(corpus, devout):
    c = read_corpus(corpus)
    got = Path(devout).read_bytes()
    esz, n, want = c["esz"], c["n"], c["tail"]
    if len(got) != len(want):
        raise SystemExit(f"verify: {devout} is {len(got)} bytes, expected {len(want)}")
    dbad = sum(got[i * esz:(i + 1) * esz] != want[i * esz:(i + 1) * esz] for i in range(n))
    fbad = sum(got[n * esz + i] != want[n * esz + i] for i in range(n))
    print(f"verify: {Path(devout).name} against {Path(corpus).name}: {n} cases, "
          f"{dbad} results and {fbad} flags differ; hashlib sha256 {sha(got)}")
    return 1 if dbad or fbad else 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("conformance"); p.add_argument("out", type=Path)
    p.add_argument("--jobs", type=int, default=2)
    p = sub.add_parser("stream"); p.add_argument("out", type=Path)
    p.add_argument("--triples", type=int, default=200000)
    p.add_argument("--seed", type=int, default=STREAM_SEED)
    p.add_argument("--jobs", type=int, default=2)
    p = sub.add_parser("flip"); p.add_argument("src"); p.add_argument("dst")
    p.add_argument("--index", type=int, required=True)
    p.add_argument("--bit", type=int, required=True)
    p = sub.add_parser("verify"); p.add_argument("corpus"); p.add_argument("devout")
    p = sub.add_parser("show"); p.add_argument("files", nargs="+")
    a = ap.parse_args()
    if a.cmd in ("conformance", "stream"):
        a.out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "conformance":
        conformance(a.out, a.jobs)
    elif a.cmd == "stream":
        stream(a.out, a.triples, a.seed, a.jobs)
    elif a.cmd == "flip":
        flip(a.src, a.dst, a.index, a.bit)
    elif a.cmd == "verify":
        sys.exit(verify(a.corpus, a.devout))
    else:
        for f in a.files:
            c = read_corpus(f)
            per = [c["rnd"].count(k) for k in range(5)]
            print(f"{Path(f).name}: {c['fmt']}, {c['n']} cases ({per}); file sha256 "
                  f"{sha(c['data'])}; expect {sha(c['tail'])}")


if __name__ == "__main__":
    main()
