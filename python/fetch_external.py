# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Re-fetch the outside generators' files, and refuse any whose hash differs.

    python3 python/fetch_external.py DIR            download into DIR
    python3 python/fetch_external.py --verify DIR   check files already in DIR
    python3 python/fetch_external.py --compare-manifest MANIFEST.txt

The eleven files (docs/EXTERNAL-GENERATORS.md) are the three archives of
Berkeley SoftFloat 3e, Berkeley TestFloat 3e and UCBTEST and the eight IBM
FPgen files the parcel used. The table below is what the lead recorded when
he downloaded them on 2026-10-20: name, sha256 of the bytes, size, URL. No
byte of them is in this repository, and this script is how they come back.

Download mode takes only the files in the table, from the URLs in the table,
into a directory that does not exist yet (or exists and is empty): it never
overwrites. Each file is held in memory, its size and sha256 compared with
the table's, and written only if both match; a file that does not match is
named, refused and not written, and the exit status is 1.

IT NEVER RUNS AS PART OF A TEST, A STAGE OR CI. It touches the network and
writes outside files, and it refuses to start when CI, GITHUB_ACTIONS or
PYTEST_CURRENT_TEST is set. Nothing in python/tests, host/tests or
verify/run.sh calls it, and python/tests/test_external_gens.py holds the
refusal itself. --verify and --compare-manifest read local files only.
"""

import hashlib
import os
import re
import sys
import urllib.request

IBM = "https://raw.githubusercontent.com/sergev/ieee754-test-suite/master/"
# (path under DIR, sha256, size in bytes, URL)
MANIFEST = (
    ("testfloat-3e/TestFloat-3e.zip",
     "6d4bdf0096b48a653aa59fc203a9e5fe18b5a58d7a1b715107c7146776a0aad6",
     429806, "https://www.jhauser.us/arithmetic/TestFloat-3e.zip"),
    ("softfloat-3e/SoftFloat-3e.zip",
     "21130ce885d35c1fe73fc1e1bf2244178167e05c6747cad5f450cc991714c746",
     729637, "https://www.jhauser.us/arithmetic/SoftFloat-3e.zip"),
    ("ucbtest/ucbtest.tgz",
     "d9ce3515417faefd4918a60ceb3976718b3eafb3e5f20e1bcf4fc785b1909c7a",
     1021833, "https://www.netlib.org/fp/ucbtest.tgz"),
    ("ibm-fptest/Vicinity-Of-Rounding-Boundaries.fptest",
     "c47e58f6e604f3e41e701c719e61329930163158f68487643d03ccb036d62981",
     38134, IBM + "Vicinity-Of-Rounding-Boundaries.fptest"),
    ("ibm-fptest/Corner-Rounding.fptest",
     "5f652d83ea90fbc766f46dbdd0c97ab70cf4ba350ff0f617178dff203118e7ba",
     15653, IBM + "Corner-Rounding.fptest"),
    ("ibm-fptest/Rounding.fptest",
     "0ec1eb2d1764d1ae0f8493ead2d00cb453dd1b7de9dd4a2b2999be7a0a8ab4cc",
     36349, IBM + "Rounding.fptest"),
    ("ibm-fptest/Sticky-Bit-Calculation.fptest",
     "3191ce988657319f7d209f1ed1e2c798f4ff52afce8723cbbd1c0aa5743bb61d",
     5947, IBM + "Sticky-Bit-Calculation.fptest"),
    ("ibm-fptest/Underflow.fptest",
     "234700bf9a7bfd3598567f9737f7e1be6e64b8dbe34ef23c8e1795fb49c1eaab",
     164170, IBM + "Underflow.fptest"),
    ("ibm-fptest/Overflow.fptest",
     "88f361a142cd8faa7dcd9497b97e2e8f82d5f3e84a9f2f9e3d140557d8e08054",
     139239, IBM + "Overflow.fptest"),
    ("ibm-fptest/Divide-Trailing-Zeros.fptest",
     "f3d3da5801d37d542dad7604a518aeaf3264d6db4c8102912d932e4512011784",
     1784, IBM + "Divide-Trailing-Zeros.fptest"),
    ("ibm-fptest/syntax.txt",
     "2d7038d8a742dc0dca529d87bfad71ed9df24b46d7fbac5d52833dd33289bfe8",
     6307, IBM + "syntax.txt"),
)

REFUSE_ENV = ("CI", "GITHUB_ACTIONS", "PYTEST_CURRENT_TEST")


def refusal():
    """The environment variable that forbids a run, or None."""
    for v in REFUSE_ENV:
        if os.environ.get(v):
            return v
    return None


def check(data, sha256, size):
    """None if `data` is the table's file, else the reason it is not."""
    if len(data) != size:
        return f"{len(data)} bytes, the table says {size}"
    got = hashlib.sha256(data).hexdigest()
    if got != sha256:
        return f"sha256 {got}, the table says {sha256}"
    return None


def http_fetch(url, limit):
    """The body of `url`, at most limit bytes (one more is read to show it
    was too long)."""
    req = urllib.request.Request(url, headers={"User-Agent": "cft-fetch-external"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read(limit + 1)


def fetch_all(dest, manifest=MANIFEST, fetch=http_fetch, out=print):
    """Download every file of `manifest` into `dest` (new or empty) through
    `fetch(url, limit)`; return the list of refusals (empty on success)."""
    if os.path.exists(dest) and (not os.path.isdir(dest) or os.listdir(dest)):
        raise SystemExit(f"{dest} exists and is not an empty directory: "
                         "this script never overwrites")
    os.makedirs(dest, exist_ok=True)
    refused = []
    for rel, sha, size, url in manifest:
        try:
            data = fetch(url, size)
            why = check(data, sha, size)
        except Exception as e:   # a network error is a refusal like any other
            data, why = b"", f"{type(e).__name__}: {e}"
        if why:
            refused.append((rel, why))
            out(f"REFUSED {rel}: {why}")
            continue
        path = os.path.join(dest, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        out(f"ok {rel} {size} {sha}")
    return refused


def verify_dir(dest, manifest=MANIFEST, out=print):
    """Check files already in `dest` against the table; the refusals."""
    bad = []
    for rel, sha, size, _ in manifest:
        path = os.path.join(dest, *rel.split("/"))
        try:
            with open(path, "rb") as f:
                data = f.read()
            why = check(data, sha, size)
        except OSError as e:
            why = f"cannot read: {e.strerror}"
        if why:
            bad.append((rel, why))
            out(f"MISMATCH {rel}: {why}")
        else:
            out(f"ok {rel}")
    return bad


def parse_manifest_txt(text):
    """(sha256, size, path) of each file line of the lead's MANIFEST.txt."""
    rows = []
    for ln in text.splitlines():
        m = re.match(r"^([0-9a-f]{64})\s+(\d+)\s+(\S+)\s*$", ln)
        if m:
            rows.append((m.group(1), int(m.group(2)), m.group(3)))
    return rows


def compare_manifest(text, manifest=MANIFEST):
    """The differences between a MANIFEST.txt and the table (empty: equal)."""
    theirs = {p: (s, n) for s, n, p in parse_manifest_txt(text)}
    ours = {p: (s, n) for p, s, n, _ in manifest}
    diffs = []
    for p in sorted(set(theirs) | set(ours)):
        if theirs.get(p) != ours.get(p):
            diffs.append(f"{p}: manifest {theirs.get(p)}, table {ours.get(p)}")
    return diffs


def main(argv):
    if len(argv) == 2 and argv[0] == "--compare-manifest":
        with open(argv[1], encoding="utf-8") as f:
            diffs = compare_manifest(f.read())
        for d in diffs:
            print("DIFFERENT", d)
        print("the table equals the manifest" if not diffs else
              f"{len(diffs)} differences")
        return 1 if diffs else 0
    if len(argv) == 2 and argv[0] == "--verify":
        return 1 if verify_dir(argv[1]) else 0
    if len(argv) == 1 and not argv[0].startswith("-"):
        v = refusal()
        if v:
            print(f"fetch_external.py: refused: {v} is set. This script "
                  "downloads outside files and never runs in a test, a stage "
                  "or CI.", file=sys.stderr)
            return 2
        return 1 if fetch_all(argv[0]) else 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
