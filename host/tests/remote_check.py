# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""The remote backend held to the contract, with the server's lifecycle
owned here (docs/REMOTE.md).

    python host/tests/remote_check.py [--vectors DIR] [--keep] [--port N]
                                      [--collatz-count N] [--url URL]

Starts `cft-serve` on a free loopback port as a child process, records
its PID (and writes it to $REMOTE_PIDFILE when that is set, which is
how verify/run.sh's `remote` stage keeps it beside the run's logs),
and drives every check through it:

  1. the CRC-32 the frames carry, held against zlib.crc32 - an
     implementation that shares no code with the C one;
  2. remote-test: the protocol refusals, the operations libcft's own
     client never issues, and a bit-identity sample against the
     software backend on BOTH div/sqrt routes;
  3. device-test: the remote backend against the software one over the
     full opcode matrix, partition invariance and the awkward
     reduction lengths - the same harness that holds the XRT backend;
  4. a bounded conformance replay, local and remote, same report;
  5. one workload chain, local and remote, same chain;
  6. remote-test --bench on both routes: the round-trip counts.

--url skips the server and drives an already-running one (the cross-OS
run: a server in the WSL distro, this script on Windows). The server is
stopped BY ITS PID and only ever that; nothing here kills by name.

Exit status 0 only if every check passed.
"""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.path.dirname(HERE)
ROOT = os.path.dirname(HOST)
EXE = ".exe" if os.name == "nt" else ""


def tool(name):
    p = os.path.join(HOST, name + EXE)
    if not os.path.exists(p):
        sys.exit(f"remote_check: {p} is not built (make -C host {name})")
    return p


def run(cmd, env=None, check=True, quiet=False):
    """Run a command, echo its output, return (rc, stdout)."""
    if not quiet:
        print("$ " + " ".join(cmd), flush=True)
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, env=e, capture_output=True, text=True)
    out = r.stdout + (("\n" + r.stderr) if r.stderr.strip() else "")
    if not quiet:
        print(out.rstrip(), flush=True)
    if check and r.returncode != 0:
        raise SystemExit(f"remote_check: {cmd[0]} exited {r.returncode}")
    return r.returncode, r.stdout


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def field(text, key):
    """The value after `key` on the line that starts with it."""
    for line in text.splitlines():
        t = line.strip()
        if t.startswith(key):
            return t[len(key):].strip()
    return None


class Server:
    """cft-serve as a child process, stopped by PID."""

    def __init__(self, port, artifact=None, pidfile=None):
        self.port = port
        self.log = tempfile.NamedTemporaryFile("w+", prefix="cft-serve-",
                                               suffix=".log", delete=False)
        cmd = [tool("cft-serve"), "--port", str(port)]
        if artifact:
            cmd += ["--artifact", artifact]
        print("$ " + " ".join(cmd) + "  &", flush=True)
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT)
        self.pid = self.proc.pid
        print(f"server pid {self.pid} (log {self.log.name})", flush=True)
        if pidfile:
            with open(pidfile, "w") as f:
                f.write(f"{self.pid}\n")
        # readiness: the port answers a TCP connect
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.proc.poll() is not None:
                self.log.seek(0)
                sys.exit("remote_check: the server exited early:\n" + self.log.read())
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.1)
        sys.exit("remote_check: the server did not start listening in 20 s")

    def stop(self):
        if self.proc.poll() is None:
            # By PID: Popen.terminate is TerminateProcess/SIGTERM on THIS
            # child and nothing else on the host.
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(10)
        print(f"server pid {self.pid} stopped (exit {self.proc.returncode})", flush=True)
        self.log.seek(0)
        tail = self.log.read().splitlines()[-6:]
        for line in tail:
            print("   server| " + line)
        self.log.close()


def gen_bounded_vectors(outdir, python):
    """A small set, generated from the model into a fresh directory."""
    cmd = [python, os.path.join(ROOT, "vectors", "gen_vectors.py"),
           "--out", outdir, "--formats", "fp32", "fp256",
           "--rounding", "rne", "rdn",
           "--directed", "120", "--random", "160", "--simple", "24",
           "--transcend", "2", "--reduce", "1", "--augmented", "4",
           "--character", "2", "--minmaxmag", "4", "--formatof", "2"]
    run(cmd, quiet=True)
    n = len([f for f in os.listdir(outdir) if f.endswith(".jsonl")])
    print(f"bounded vector set: {n} files in {outdir}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vectors", help="replay this directory instead of a "
                    "freshly generated bounded set")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--url", help="drive an already-running server (no "
                    "server is started or stopped)")
    ap.add_argument("--artifact", help="the server's device")
    ap.add_argument("--collatz-count", type=int, default=2000)
    ap.add_argument("--elements", type=int, default=64,
                    help="device-test's element count")
    ap.add_argument("--keep", action="store_true",
                    help="keep the generated vectors")
    args = ap.parse_args()

    python = sys.executable
    failures = []

    def note(ok, what):
        print(("PASS " if ok else "FAIL ") + what, flush=True)
        if not ok:
            failures.append(what)

    # 1. the CRC, against zlib
    rc, out = run([tool("remote-test"), "--crc"], quiet=True)
    check = field(out, "crc32 check")
    stream = field(out, "crc32 stream")
    note(rc == 0 and check == f"{zlib.crc32(b'123456789'):08x}",
         f"CRC-32 check value {check} == zlib's {zlib.crc32(b'123456789'):08x}")
    # the stream is the LCG's, reproduced here from its stated constants
    seed = 0x9E3779B97F4A7C15
    mask = (1 << 64) - 1
    buf = bytearray()
    for _ in range(1000):
        seed = (seed * 6364136223846793005 + 1442695040888963407) & mask
        buf.append(((seed ^ (seed >> 29)) >> 24) & 0xFF)
    note(stream == f"{zlib.crc32(bytes(buf)):08x}",
         f"CRC-32 of a 1000-byte stream {stream} == zlib's "
         f"{zlib.crc32(bytes(buf)):08x}")

    server = None
    if args.url:
        url = args.url
        print(f"driving an existing server at {url}", flush=True)
    else:
        port = args.port or free_port()
        server = Server(port, args.artifact, os.environ.get("REMOTE_PIDFILE"))
        url = f"cft://127.0.0.1:{port}"
    try:
        # 2. the protocol, both routes
        for route in ("1", "0"):
            rc, out = run([tool("remote-test"), url, "-n", str(args.elements)],
                          env={"CFT_DIVSQRT_SEQ": route}, check=False)
            note(rc == 0, f"remote-test (CFT_DIVSQRT_SEQ={route})")

        # 3. device-test: the remote backend against the software one
        rc, out = run([tool("device-test"), url, "-n", str(args.elements)],
                      check=False)
        note(rc == 0, f"device-test {url} -n {args.elements}")

        # 4. the bounded replay, local and remote
        vec = args.vectors
        tmp = None
        if not vec:
            tmp = tempfile.mkdtemp(prefix="cft-remote-vectors-")
            gen_bounded_vectors(tmp, python)
            vec = tmp
        rc_l, out_l = run([tool("cft-selftest"), vec], check=False, quiet=True)
        t0 = time.time()
        rc_r, out_r = run([tool("cft-selftest"), vec, url], check=False, quiet=True)
        t1 = time.time()
        cl = [l for l in out_l.splitlines() if l.endswith("cases checked")]
        cr = [l for l in out_r.splitlines() if l.endswith("cases checked")]
        sets_l = [l for l in out_l.splitlines() if " sets, " in l]
        sets_r = [l for l in out_r.splitlines() if " sets, " in l]
        print("local : " + (sets_l[0] if sets_l else out_l.strip()[-200:]))
        print("remote: " + (sets_r[0] if sets_r else out_r.strip()[-200:]))
        note(rc_l == 0 and rc_r == 0 and cl == cr and sets_l == sets_r and cl,
             f"conformance replay of {vec}: local and remote agree "
             f"({cl[0] if cl else '?'}; remote {t1 - t0:.1f} s)")
        if tmp and not args.keep:
            shutil.rmtree(tmp, ignore_errors=True)

        # 5. one workload chain
        base = [tool("cft-collatz"), "--mode", "sweep", "--from", "1",
                "--count", str(args.collatz_count), "--format", "fp256",
                "--batch", "256", "--csv"]
        rc_l, out_l = run(base, check=False, quiet=True)
        rc_r, out_r = run(base + ["--artifact", url], check=False, quiet=True)

        def csv_row(out):
            lines = [l for l in out.splitlines() if l.startswith(("software,", "remote,"))]
            return lines[0].split(",") if lines else None
        row_l, row_r = csv_row(out_l), csv_row(out_r)
        chain_l = row_l[-1] if row_l else "?"
        chain_r = row_r[-1] if row_r else "?"
        print(f"local  chain {chain_l}  ({row_l[15] if row_l else '?'} steps/s)")
        print(f"remote chain {chain_r}  ({row_r[15] if row_r else '?'} steps/s)")
        note(rc_l == 0 and rc_r == 0 and row_l and row_r and chain_l == chain_r
             and row_l[9] == row_r[9],
             f"cft-collatz sweep 1..{args.collatz_count} fp256: same chain "
             f"local and remote")

        # 6. the round trips, both routes
        for route in ("1", "0"):
            rc, out = run([tool("remote-test"), url, "--bench"],
                          env={"CFT_DIVSQRT_SEQ": route}, check=False)
            note(rc == 0, f"remote-test --bench (CFT_DIVSQRT_SEQ={route})")
    finally:
        if server:
            server.stop()

    print()
    if failures:
        print(f"remote_check: {len(failures)} FAILED:")
        for f in failures:
            print("  " + f)
        sys.exit(1)
    print("remote_check: every check passed")


if __name__ == "__main__":
    main()
