#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Vendor libcft into the Arduino library, and prove the copy is one.

WHY THERE IS A COPY AT ALL. An Arduino build compiles every source
under a library's src/ and adds src/ to the include path, and it will
not reach outside the library directory - there is no way to say "and
also compile ../../host/src". So the library has to CONTAIN libcft.
That is a copy, and a copy is a thing that drifts: someone fixes a
rounding edge in host/src/softfloat.c, the board keeps computing the
old answer, and the vector replay that was supposed to catch it is
replaying against a library that no longer exists anywhere else.

So the copy is generated and checked, never made by hand:

    python bindings/arduino/sync.py            copy, rewrite vendor.json
    python bindings/arduino/sync.py --check    fail if the copy drifted

--check is a gate. It fails if a vendored file differs from its source
by one byte, if a source has appeared or vanished upstream, or if a
file has been left behind in the vendored tree that no source explains.
It is the reason a board result means anything: the sha256 in
vendor.json says the bits on the part came from the bits in host/.

WHAT IS COPIED, AND THE LAYOUT IT LANDS IN

    host/include/cft.h        -> src/cft/include/cft.h
    host/include/cft_config.h -> src/cft/include/cft_config.h
    host/src/*.c, *.h         -> src/cft/src/

The nesting is not decoration. Every libcft source says
`#include "../include/cft.h"`, so the copy has to preserve the
include/ and src/ pair beside each other or every one of those lines
would need rewriting - and a vendored file that has been rewritten
cannot be compared to its source by hash. Nothing here edits a byte.

WHAT IS NOT COPIED

    backend_xrt.cpp   the XRT device backend. C++, and it needs Vitis.
    cft.hpp           the C++17 header-only wrapper. The AVR core
                      compiles at gnu++11 and the wrapper's std::span
                      branch wants C++20; a board that wants C++ can
                      take it from host/include, which is where it is
                      tested (make -C host cpptest).

WHAT IS OURS, NOT VENDORED: library.properties, README.md,
keywords.txt, src/cft.h (three lines that point at the vendored header
so a sketch can write `#include <cft.h>`), and src/cft_replay.[ch].
Those six are OWNED below and in vendor.json, so this script can tell
them apart from a stale copy and leave them alone. The examples and
src/cft_remote.h are ours too and are in no list, because the audit
only ever walks src/cft - a file outside that subtree is never
examined either way.

AND ONE DIRECTORY THIS SCRIPT DOES NOT LOOK AT: src/remote/. The
remote client for these same boards is built alongside this and owns
that subtree; it is in "ignore" so that --check never reports its files
as unexplained and a sync never removes them.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
LIB = os.path.join(HERE, "cft-arduino")
VENDOR_JSON = os.path.join(HERE, "vendor.json")

# Where the vendored copy lives, relative to the library root. Nothing
# outside this subtree is ever written or removed by a sync.
VENDOR_ROOT = os.path.join("src", "cft")

# Sources that are ours rather than upstream's, relative to the library
# root. Listed so --check can distinguish "you wrote this" from "this
# is a copy of a file that no longer exists".
OWNED = [
    "library.properties",
    "README.md",
    "keywords.txt",
    "src/cft.h",
    "src/cft_replay.h",
    "src/cft_replay.c",
]

# Subtrees this script neither writes nor audits, relative to the
# library root. See the module docstring.
IGNORE = [
    "src/remote",
]

# Upstream files this script deliberately does not take, and why - kept
# here rather than as a silent absence so that a source appearing
# upstream is either copied or refused by name.
SKIP = {
    "backend_xrt.cpp": "C++ and needs Vitis/XRT; no device on a board",
    "cft.hpp": "C++17 header-only wrapper; the AVR core builds at gnu++11",
}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def sources() -> list[tuple[str, str]]:
    """(repo-relative source, library-relative destination) pairs.

    Sorted, so vendor.json's order is a property of the tree and not of
    the filesystem's mood - a manifest that reshuffles itself makes
    every diff unreadable.
    """
    out: list[tuple[str, str]] = []
    inc = os.path.join(REPO, "host", "include")
    src = os.path.join(REPO, "host", "src")
    for name in sorted(os.listdir(inc)):
        if name in SKIP:
            continue
        if name.endswith((".h", ".c")):
            out.append(("host/include/" + name,
                        VENDOR_ROOT.replace(os.sep, "/") + "/include/" + name))
    for name in sorted(os.listdir(src)):
        if name in SKIP:
            continue
        if name.endswith((".h", ".c")):
            out.append(("host/src/" + name,
                        VENDOR_ROOT.replace(os.sep, "/") + "/src/" + name))
    return out


def vendored_on_disk() -> list[str]:
    """Every file under the vendored subtree, library-relative."""
    root = os.path.join(LIB, VENDOR_ROOT)
    found: list[str] = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            full = os.path.join(dirpath, name)
            found.append(os.path.relpath(full, LIB).replace(os.sep, "/"))
    return sorted(found)


def build_manifest() -> dict:
    entries = []
    for rel_src, rel_dst in sources():
        entries.append({
            "source": rel_src,
            "dest": rel_dst,
            "sha256": sha256_file(os.path.join(REPO, rel_src)),
        })
    return {
        "note": ("Generated by bindings/arduino/sync.py - do not edit. "
                 "Each sha256 is of the file in host/, which is the "
                 "authority; the copy under cft-arduino/src/cft is "
                 "byte-identical to it and `sync.py --check` fails if "
                 "it is not."),
        "library": "cft-arduino",
        "vendor_root": VENDOR_ROOT.replace(os.sep, "/"),
        "owned": OWNED,
        "ignore": IGNORE,
        "skipped": SKIP,
        "vendored": entries,
    }


def do_write() -> int:
    man = build_manifest()
    wanted = set()
    for e in man["vendored"]:
        src = os.path.join(REPO, e["source"])
        dst = os.path.join(LIB, e["dest"].replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fh:
            data = fh.read()
        old = None
        if os.path.exists(dst):
            with open(dst, "rb") as fh:
                old = fh.read()
        if old != data:
            with open(dst, "wb") as fh:
                fh.write(data)
            print("  wrote  %s" % e["dest"])
        wanted.add(e["dest"])

    removed = 0
    for rel in vendored_on_disk():
        if rel not in wanted:
            os.remove(os.path.join(LIB, rel.replace("/", os.sep)))
            print("  removed %s (no longer in host/)" % rel)
            removed += 1

    with io.open(VENDOR_JSON, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(man, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print("%d files vendored, %d removed; manifest %s"
          % (len(man["vendored"]), removed,
             os.path.relpath(VENDOR_JSON, REPO)))
    return 0


def do_check() -> int:
    if not os.path.exists(VENDOR_JSON):
        print("no vendor.json - run sync.py to create the copy",
              file=sys.stderr)
        return 1
    with io.open(VENDOR_JSON, "r", encoding="utf-8") as fh:
        man = json.load(fh)

    problems: list[str] = []

    # 1. The manifest against the tree upstream: a source added or
    #    removed in host/ makes the manifest itself stale, and no
    #    amount of matching hashes would say so.
    live = {s: d for s, d in sources()}
    listed = {e["source"]: e["dest"] for e in man.get("vendored", [])}
    for s in sorted(set(live) - set(listed)):
        problems.append("%s exists in host/ and is not vendored" % s)
    for s in sorted(set(listed) - set(live)):
        problems.append("%s is vendored and no longer exists in host/" % s)
    for s in sorted(set(live) & set(listed)):
        if live[s] != listed[s]:
            problems.append("%s is vendored to %s, expected %s"
                            % (s, listed[s], live[s]))

    # 2. Each recorded hash against the file in host/, then the copy
    #    against the same bytes. Two comparisons, because they fail for
    #    different reasons: the first says the manifest is out of date,
    #    the second says the copy is.
    for e in man.get("vendored", []):
        src = os.path.join(REPO, e["source"])
        dst = os.path.join(LIB, e["dest"].replace("/", os.sep))
        if not os.path.exists(src):
            continue                      # reported above
        now = sha256_file(src)
        if now != e["sha256"]:
            problems.append("%s changed since the manifest was written\n"
                            "    manifest %s\n    host/    %s"
                            % (e["source"], e["sha256"], now))
        if not os.path.exists(dst):
            problems.append("%s is missing from the library" % e["dest"])
            continue
        copy = sha256_file(dst)
        if copy != now:
            problems.append("%s differs from %s\n"
                            "    host/   %s\n    library %s"
                            % (e["dest"], e["source"], now, copy))

    # 3. Anything in the vendored subtree the manifest does not
    #    explain: a file left behind when a source was renamed
    #    compiles, and compiles the OLD code.
    wanted = set(listed.values())
    for rel in vendored_on_disk():
        if rel not in wanted:
            problems.append("%s is in the vendored tree and in no "
                            "manifest entry" % rel)

    if problems:
        print("vendored copy has drifted from host/:\n", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        print("\nRun: python bindings/arduino/sync.py", file=sys.stderr)
        return 1
    print("%d vendored files, all identical to host/"
          % len(man.get("vendored", [])))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify the copy instead of writing it")
    args = ap.parse_args()
    return do_check() if args.check else do_write()


if __name__ == "__main__":
    sys.exit(main())
