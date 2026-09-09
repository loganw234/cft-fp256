#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Build the embedded remote client with the desktop's C++ compiler and
drive it against a real cft-serve, with the server's lifecycle owned
here (docs/REMOTE.md, the serial transport section).

    python bindings/arduino/cft-arduino/src/remote/test/host_check.py
           [--cxx g++] [--port N] [--keep] [--one] [--via-bridge]
           [--url HOST:PORT]

The same cft_remote.cpp an Uno compiles is compiled here and driven
against the software backend behind a socket; host_check.cc compares
every answer with what libcft computes for the same call in the same
process. That is the codec verified end to end before any hardware
exists.

It is built and run TWICE: once with the 32-bit defaults and once with
the configuration an Uno gets - no message store, no backend name, no
sequencer capacities, a 256-byte chunk budget - because those are #if
branches and a 256-byte budget makes every run a different number of
frames. --one builds only the first.

  --via-bridge  put host/tools/cft-serial-bridge.py in the path, in its
                --serial-tcp mode, so the bytes go
                client -> byte pipe -> bridge -> cft-serve and back.
                Same checks, one more hop, and no board needed.
  --url         drive an already-running server instead of starting one.

The server is stopped BY ITS PID and only ever that; nothing here kills
by name. Exit status 0 only if every check passed.
"""

import argparse
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REMOTE = os.path.dirname(HERE)                        # src/remote
ROOT = os.path.abspath(os.path.join(REMOTE, "..", "..", "..", "..", ".."))
HOST = os.path.join(ROOT, "host")
EXE = ".exe" if os.name == "nt" else ""


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port, deadline, proc=None):
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), 0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default=os.environ.get("CXX", "g++"))
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--url", default=None,
                    help="HOST:PORT of a server already running")
    ap.add_argument("--via-bridge", action="store_true")
    ap.add_argument("--keep", action="store_true",
                    help="leave the built binaries in place")
    ap.add_argument("--one", action="store_true",
                    help="only the default configuration, not the AVR one")
    args = ap.parse_args()

    serve = os.path.join(HOST, "cft-serve" + EXE)
    lib = os.path.join(HOST, "libcft.a")
    for p in (lib,) + ((serve,) if not args.url else ()):
        if not os.path.exists(p):
            sys.exit("host_check: %s is not built (make -C host)" % p)

    # TWO builds of the same sources: the 32-bit defaults, and the
    # configuration an Uno gets. The second is not a formality - it is
    # the only thing that runs the #if branches a small board takes
    # (no message store, no backend name, no sequencer capacities) and
    # the 256-byte chunk budget, which changes how many frames every
    # run becomes.
    builds = [("default", [], os.path.join(HERE, "host_check" + EXE))]
    if not args.one:
        builds.append(("as an Uno sees it",
                       ["-DCFT_REMOTE_CHUNK_BYTES=256",
                        "-DCFT_REMOTE_ERR_BYTES=0",
                        "-DCFT_REMOTE_BACKEND_NAME_BYTES=0",
                        "-DCFT_REMOTE_KEEP_SEQ_CAPS=0"],
                       os.path.join(HERE, "host_check_avr" + EXE)))
    for label, extra, out in builds:
        cmd = [args.cxx, "-std=c++11", "-O2", "-Wall", "-Wextra", "-Wshadow"]
        cmd += extra
        cmd += ["-I" + os.path.join(HOST, "include"),
                "-I" + os.path.join(HOST, "src"),
                os.path.join(HERE, "host_check.cc"),
                os.path.join(REMOTE, "cft_remote.cpp"),
                lib, "-o", out]
        print("$ " + " ".join(cmd), flush=True)
        r = subprocess.run(cmd)
        if r.returncode:
            sys.exit("host_check: the build failed (%s)" % label)

    procs = []          # (name, Popen)
    try:
        if args.url:
            host, _, port = args.url.rpartition(":")
            port = int(port)
        else:
            host = "127.0.0.1"
            port = args.port or free_port()
            sp = subprocess.Popen([serve, "--port", str(port),
                                   "--bind", "127.0.0.1"])
            procs.append(("cft-serve", sp))
            print("cft-serve pid %d on port %d" % (sp.pid, port), flush=True)
            if not wait_for_port(port, time.time() + 15, sp):
                sys.exit("host_check: cft-serve did not come up")

        if args.via_bridge:
            bridge = os.path.join(HOST, "tools", "cft-serial-bridge.py")
            bport = free_port()
            bp = subprocess.Popen([sys.executable, bridge,
                                   "--serial-tcp", str(bport),
                                   "--server", "%s:%d" % (host, port),
                                   "--forever"])
            procs.append(("cft-serial-bridge", bp))
            print("bridge pid %d, board side on port %d" % (bp.pid, bport),
                  flush=True)
            if not wait_for_port(bport, time.time() + 15, bp):
                sys.exit("host_check: the bridge did not come up")
            host, port = "127.0.0.1", bport

        rc = 0
        for label, _, exe in builds:
            print("\n==== %s ====" % label, flush=True)
            rc |= subprocess.run([exe, "--host", host,
                                  "--port", str(port)]).returncode
        return rc
    finally:
        for name, p in reversed(procs):
            if p.poll() is None:
                print("stopping %s by pid %d" % (name, p.pid), flush=True)
                p.terminate()
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
        if not args.keep:
            for _, _, exe in builds:
                if os.path.exists(exe):
                    try:
                        os.remove(exe)
                    except OSError:
                        pass


if __name__ == "__main__":
    sys.exit(main())
