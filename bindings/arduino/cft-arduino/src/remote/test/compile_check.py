#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Compile the Remote* examples for every board and report flash and RAM.

    python bindings/arduino/cft-arduino/src/remote/test/compile_check.py
           [--cli PATH] [--warnings] [--fqbn X] [Example ...]

The library is compiled from a SCRATCH COPY of src/, in a temporary
directory, for one reason: this half of cft-arduino - src/remote/ and
examples/Remote* - is written beside an on-chip half that owns
library.properties and the rest of src/, and this check has to run
whether that half is present yet or not. On a merged tree the copy is
the real thing. On a tree that has only this half, two files are
SYNTHESISED and the run says so:

  * library.properties, if there is none.
  * src/cft_arduino.h, if src/ has no header directly in it.

The second is not cosmetic and it is worth knowing about: arduino-cli's
library resolver indexes a library by the headers that sit DIRECTLY in
src/, and nothing deeper. A sketch's `#include <remote/cft_remote.h>`
therefore finds nothing until some header at the root of src/ has
already pulled the library in - after which src/ is on the include path
and every subdirectory include works. The on-chip half's own header
does that job in the shipped library; this synthesises a one-line stand-
in when it is not there yet.

Exit status 0 only if every board compiled.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = os.path.dirname(HERE)                        # src/remote
SRC = os.path.dirname(REMOTE)                         # src
LIB = os.path.dirname(SRC)                            # cft-arduino
EXAMPLES = os.path.join(LIB, "examples")

BOARDS = [
    ("arduino:avr:uno", "Uno", None),
    ("arduino:avr:nano", "Nano", None),
    ("arduino:avr:mega", "Mega", None),
    ("esp32:esp32:esp32", "ESP32", None),
    ("rp2040:rp2040:rpipico", "Pico", None),
]

# The examples that only make sense on a board with a network.
NETWORK_ONLY = {"RemoteWiFiFma": ("esp32:esp32:esp32",)}

PROPS = """name=cft-arduino
version=0.0.0-compile-check
author=Logan W.
maintainer=Logan W.
sentence=scratch library for the remote client's compile check
paragraph=synthesised by src/remote/test/compile_check.py; the shipped
category=Data Processing
url=https://github.com/
architectures=*
"""

SHIM = """/* Synthesised by src/remote/test/compile_check.py.
 *
 * arduino-cli's library resolver only sees headers that sit directly in
 * src/, so a sketch's #include <remote/cft_remote.h> needs one of them
 * to have pulled the library in first. In the shipped library that is
 * the on-chip half's own header; this stands in for it when this half
 * is compiled on its own.
 */
#ifndef CFT_ARDUINO_SHIM_H_
#define CFT_ARDUINO_SHIM_H_
#include "remote/cft_remote.h"
#endif
"""


def stage(tmp, note):
    """A library directory arduino-cli will accept, built from src/."""
    lib = os.path.join(tmp, "libraries", "cft-arduino")
    os.makedirs(lib)
    shutil.copytree(SRC, os.path.join(lib, "src"))
    props = os.path.join(LIB, "library.properties")
    if os.path.exists(props):
        shutil.copy(props, os.path.join(lib, "library.properties"))
    else:
        note.append("library.properties: synthesised (this half only)")
        with open(os.path.join(lib, "library.properties"), "w") as f:
            f.write(PROPS)
    roots = [f for f in os.listdir(os.path.join(lib, "src"))
             if f.endswith((".h", ".hpp", ".hh"))]
    if not roots:
        note.append("src/cft_arduino.h: synthesised (no header at the root "
                    "of src/ yet, so nothing would resolve the library)")
        with open(os.path.join(lib, "src", "cft_arduino.h"), "w") as f:
            f.write(SHIM)
    else:
        note.append("src/ root headers: %s" % ", ".join(sorted(roots)))
    return os.path.join(tmp, "libraries")


def sizes(js):
    sec = js["builder_result"]["executable_sections_size"]
    flash = ram = fmax = rmax = 0
    for s in sec:
        if s["name"] == "text":
            flash += s["size"]
            fmax = max(fmax, s.get("max_size", 0))
        elif s["name"] == "data":
            ram += s["size"]
            rmax = max(rmax, s.get("max_size", 0))
    return flash, fmax, ram, rmax


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cli", default=os.environ.get("ARDUINO_CLI",
                                                    "arduino-cli"))
    ap.add_argument("--warnings", action="store_true",
                    help="build with --warnings all and list every one")
    ap.add_argument("--fqbn", action="append",
                    help="only this board (repeatable)")
    ap.add_argument("names", nargs="*", help="only these examples")
    args = ap.parse_args()

    names = sorted(n for n in os.listdir(EXAMPLES) if n.startswith("Remote"))
    if args.names:
        names = [n for n in names if n in args.names]
    boards = [b for b in BOARDS if not args.fqbn or b[0] in args.fqbn]

    tmp = tempfile.mkdtemp(prefix="cft-compile-check-")
    rc = 0
    rows = []
    try:
        note = []
        libs = stage(tmp, note)
        print("compile_check: %s" % os.path.basename(tmp))
        for line in note:
            print("  " + line)
        print()
        for name in names:
            want = NETWORK_ONLY.get(name)
            for fqbn, label, _ in boards:
                if want and fqbn not in want:
                    continue
                cmd = [args.cli, "compile", "--fqbn", fqbn,
                       "--libraries", libs, "--format", "json",
                       os.path.join(EXAMPLES, name)]
                if args.warnings:
                    # --clean as well: a cached build prints nothing, and a
                    # warning count taken off a cache is not a measurement.
                    cmd[2:2] = ["--warnings", "all", "--clean"]
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.returncode:
                    print("FAILED  %-16s %s" % (name, fqbn))
                    sys.stdout.write(p.stderr[-4000:])
                    try:
                        j = json.loads(p.stdout)
                        for d in j.get("builder_result", {}).get(
                                "diagnostics", []):
                            print("   %s: %s" % (d.get("severity"),
                                                 d.get("message")))
                    except Exception:
                        sys.stdout.write(p.stdout[-4000:])
                    rc = 1
                    continue
                j = json.loads(p.stdout)
                flash, fmax, ram, rmax = sizes(j)
                ws = [l for l in ((p.stderr or "") + (p.stdout or "")
                                  ).splitlines() if "warning:" in l]
                # A core's own warnings are the core's. Only the ones in
                # this half's files are this half's to answer for.
                mine = [l for l in ws
                        if "cft_remote" in l or ("/" + name) in l
                        or ("\\" + name) in l]
                rows.append((name, label, flash, fmax, ram, rmax, len(ws),
                             len(mine)))
                print("  %-16s %-6s flash %7d / %-8d (%4.1f%%)   "
                      "ram %6d / %-6s%s"
                      % (name, label, flash, fmax,
                         100.0 * flash / fmax if fmax else 0.0, ram,
                         str(rmax) if rmax else "-",
                         ("   warnings %d, of them this half's %d"
                          % (len(ws), len(mine))) if args.warnings else ""))
                if args.warnings and mine:
                    for l in mine:
                        print("     %s" % l)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("| example | board | flash | of | RAM (globals) | of |")
    print("|---|---|---|---|---|---|")
    for r in rows:
        print("| %s | %s | %d | %d | %d | %s |"
              % (r[0], r[1], r[2], r[3], r[4], r[5] or "-"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
