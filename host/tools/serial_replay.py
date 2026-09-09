#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""Replay the published conformance vectors through a device over a wire.

    python host/tools/serial_replay.py --port COM7
    python host/tools/serial_replay.py --loopback
    python host/tools/serial_replay.py --loopback --corrupt

host/tools/cft_selftest.c replays vectors/out through a libcft device
by opening the files. A microcontroller has neither the files nor the
room for them, so this does the same replay from the other side: it
reads a set file exactly as conformance.c's reader does - the same
sets, in the same order, the same fields, the same expected encodings
and the same five exception flags - sends each case over a serial port
or a pipe, and compares what comes back BIT FOR BIT against what the
file records.

The device half is bindings/arduino/cft-arduino/src/cft_replay.c and
the protocol is documented beside it (CSRP/1: hex fields, a sequence
number, a CRC-16 per line, a per-case timeout). Two things speak it:
examples/VectorReplay/VectorReplay.ino on a board, and
bindings/arduino/loopback as a host process built from the same
sources. --loopback drives the second, which is how this harness gets
run against the whole census before any board exists, and --corrupt
makes that loopback answer wrongly on purpose so that a green report
is evidence rather than habit.

THE FRAME. ASCII lines terminated by \n; a \r before it is ignored, so
a port opened in text mode does no damage.

    request    >SS VERB [field ...] *CCCC
    response   <SS ok  [field ...] *CCCC
               <SS err REASON [text] *CCCC

SS is the request's sequence number, two lowercase hex digits, counting
mod 256; the response echoes it, and an answer carrying any other value
is a lost or duplicated line rather than a wrong answer - this tool
raises on it rather than scoring it. CCCC is CRC-16/CCITT-FALSE (poly
0x1021, init 0xffff, no reflection, no final xor) over every byte from
the leading > or < up to but not including the space before the *. Both
sides check it BEFORE the parse, so a damaged line never becomes a
case. Every request also carries a deadline (--timeout): a device that
answers nothing is a timeout with the request in the message, not a
hang.

Element encodings travel as the SET FILE'S OWN SPELLING - "0x" stripped,
most significant digit first. Not little-endian byte order: the wire
carries what the JSONL carries, so an expected value is compared as the
string it already is and there is no byte order to get wrong twice.
Character sequences travel as `h` followed by hex, because a 5.12
sequence may legally contain spaces and may be empty, and a
whitespace-delimited token carries neither. Operation names travel as
NAMES, the ones the set files use, resolved on the device through the
library's own cft_op_name() and cft_tr_from_name() - so there is no
third table for the mapping to drift in.

The verbs, the staging buffers, and what each one answers are in
bindings/arduino/cft-arduino/src/cft_replay.h, which is the device
half. They are not restated here: a protocol written down twice is a
protocol with two versions.

WHAT IT CHECKS AND WHAT IT DOES NOT. cft_conformance() replays each
set twice - once an element at a time, which is the only pass that
pins a case's exception flags exactly, and once as whole arrays, which
exists to exercise a DEVICE backend's partitioning across tiles. This
is the first pass. There are no tiles behind a UART, and a part with
2 KB of RAM cannot hold a set; the report says so rather than letting
the smaller claim read as the larger one.

A case the device cannot be asked - a format it does not carry, an
operation this build left out, a decimal sequence longer than its
buffer - is SKIPPED, by name, with a count, and never scored. A run
that could not check something says which.

Exit status is 0 only if every case that ran matched.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import queue
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))

FORMATS = ("fp32", "fp64", "fp128", "fp256")
ROUNDINGS = ("rne", "rtz", "rdn", "rup", "rmm")
FMT_BYTES = {"fp32": 4, "fp64": 8, "fp128": 16, "fp256": 32}


# ---------------------------------------------------------------------
# The frame
#
# CRC-16/CCITT-FALSE, the same polynomial and seed cft_replay_crc16()
# uses - table-driven here, bitwise there, because this side computes
# millions and that side runs on a part with 32 KB of flash.
#
# Two implementations of a checksum are two places for it to be wrong,
# so this one is held to the standard's own check value in
# python/tests/test_serial_replay.py and to the other implementation by
# every line of every replay: a device whose CRC disagreed with this
# one would fail the very first frame.
# ---------------------------------------------------------------------

def _crc16_table() -> list[int]:
    tab = []
    for i in range(256):
        c = i << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
        tab.append(c)
    return tab


_CRC_TAB = _crc16_table()


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CRC_TAB[((crc >> 8) ^ b) & 0xFF]
    return crc


class ProtocolError(Exception):
    """The wire misbehaved: a bad frame, a bad CRC, a lost line, a
    timeout. Distinct from a wrong ANSWER, which is a conformance
    failure and is reported as one."""


class Link:
    """One request line in, one response line out."""

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout
        self.seq = 0
        self.sent = 0
        self.resyncs = 0

    # -- transport, supplied by a subclass --------------------------
    def _write(self, data: bytes) -> None:
        raise NotImplementedError

    def _readline(self, timeout: float) -> bytes | None:
        raise NotImplementedError

    def close(self) -> None:
        pass

    # -- the protocol ------------------------------------------------
    def ask(self, body: str) -> tuple[str, list[str]]:
        """Send one request, return (status, fields).

        status is 'ok' or 'err'; for 'err' the fields are the reason
        and whatever text came with it. Raises ProtocolError for
        anything that is not a well-formed answer to THIS request."""
        seq = self.seq
        self.seq = (self.seq + 1) & 0xFF
        head = (">%02x %s" % (seq, body)).encode("ascii")
        line = head + (" *%04x\n" % crc16(head)).encode("ascii")
        self._write(line)
        self.sent += 1

        deadline = time.perf_counter() + self.timeout
        while True:
            left = deadline - time.perf_counter()
            if left <= 0:
                raise ProtocolError(
                    "no answer within %.1fs to: %s" % (self.timeout, body))
            raw = self._readline(left)
            if raw is None:
                continue
            resp = raw.rstrip(b"\r\n")
            if not resp:
                continue
            if resp[:1] != b"<":
                # Anything the device printed that is not a response -
                # a boot banner, a stray print - is noise, not an
                # answer. Skipped, but counted: a run full of noise is
                # a run to look at.
                self.resyncs += 1
                continue
            try:
                got = self._parse(resp)
            except ProtocolError:
                self.resyncs += 1
                raise
            rseq, status, fields = got
            if rseq != seq:
                self.resyncs += 1
                raise ProtocolError(
                    "answer for sequence %02x arrived while %02x was "
                    "outstanding" % (rseq, seq))
            return status, fields

    @staticmethod
    def _parse(resp: bytes) -> tuple[int, str, list[str]]:
        if len(resp) < 8 or resp[-6:-4] != b" *":
            raise ProtocolError("malformed frame: %r" % resp[:120])
        try:
            want = int(resp[-4:], 16)
            rseq = int(resp[1:3], 16)
        except ValueError:
            raise ProtocolError("malformed frame: %r" % resp[:120])
        body = resp[:-6]
        got = crc16(body)
        if got != want:
            raise ProtocolError("checksum %04x, expected %04x, on: %r"
                                % (got, want, resp[:120]))
        parts = body[4:].decode("ascii", "replace").split(" ")
        if not parts:
            raise ProtocolError("empty response body")
        return rseq, parts[0], parts[1:]


class PipeLink(Link):
    """A loopback process on stdin and stdout.

    The reader runs on its own thread so that a device which answers
    nothing at all is a TIMEOUT rather than a hang - which is the whole
    point of the --corrupt drop mode, and would be untestable against a
    blocking readline."""

    def __init__(self, argv: list[str], timeout: float) -> None:
        super().__init__(timeout)
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL)
        self.q: queue.Queue = queue.Queue()
        self.t = threading.Thread(target=self._pump, daemon=True)
        self.t.start()

    def _pump(self) -> None:
        try:
            for line in self.proc.stdout:      # type: ignore[union-attr]
                self.q.put(line)
        except Exception:
            pass
        self.q.put(None)

    def _write(self, data: bytes) -> None:
        self.proc.stdin.write(data)            # type: ignore[union-attr]
        self.proc.stdin.flush()                # type: ignore[union-attr]

    def _readline(self, timeout: float) -> bytes | None:
        try:
            item = self.q.get(timeout=timeout)
        except queue.Empty:
            return None
        if item is None:
            raise ProtocolError("the loopback process closed its output")
        return item

    def close(self) -> None:
        try:
            self.proc.stdin.close()            # type: ignore[union-attr]
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


class SerialLink(Link):
    """A board on a serial port."""

    def __init__(self, port: str, baud: int, timeout: float,
                 settle: float) -> None:
        super().__init__(timeout)
        try:
            import serial                       # noqa: F401
        except ImportError:
            raise SystemExit(
                "pyserial is not installed: pip install pyserial\n"
                "(--loopback needs none of it, and is what runs in CI)")
        import serial
        self.ser = serial.Serial(port, baud, timeout=timeout)
        # A board that resets when the port opens - every AVR with the
        # auto-reset capacitor, which is all three of them - is not
        # listening yet. Wait, then throw away whatever it said while
        # booting.
        if settle > 0:
            time.sleep(settle)
        self.ser.reset_input_buffer()

    def _write(self, data: bytes) -> None:
        self.ser.write(data)
        self.ser.flush()

    def _readline(self, timeout: float) -> bytes | None:
        self.ser.timeout = timeout
        line = self.ser.readline()
        return line if line else None

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass


# ---------------------------------------------------------------------
# The device, as this harness sees it
# ---------------------------------------------------------------------

class Device:
    def __init__(self, link: Link) -> None:
        self.link = link
        status, f = link.ask("id")
        if status != "ok" or len(f) < 7:
            raise ProtocolError("id: %s %s" % (status, " ".join(f)))
        self.protocol = f[0]
        self.abi = f[1]
        self.backend = f[2]
        self.format_mask = int(f[3])
        self.line_cap = int(f[4])
        self.stage_cap = int(f[5])
        self.out_cap = int(f[6])
        self.verbs = set(f[7].split(",")) if len(f) > 7 else set()
        if self.protocol != "csrp/1":
            raise ProtocolError("device speaks %s, this tool speaks csrp/1"
                                % self.protocol)

    def has_format(self, fmt: str) -> bool:
        return bool(self.format_mask & (1 << FORMATS.index(fmt)))

    def formats(self) -> list[str]:
        return [f for f in FORMATS if self.has_format(f)]

    def ask(self, body: str) -> tuple[str, list[str]]:
        """One request, refused HERE if it is longer than the device
        said it could hold.

        Without this a too-long request is truncated by the device's
        line buffer, fails its checksum, and comes back as `err crc` -
        which reads as a wire problem when the truth is that this board
        cannot be asked this case. A skip with the two numbers in it
        says which. The 10 is the frame: '>SS ' and ' *CCCC'."""
        if len(body) + 10 > self.line_cap:
            raise Skip("the request is %d characters and this device's "
                       "line is %d" % (len(body) + 10, self.line_cap))
        return self.link.ask(body)

    # -- the staged transfers ---------------------------------------
    def clr(self) -> None:
        st, f = self.link.ask("clr")
        if st != "ok":
            raise ProtocolError("clr: %s" % " ".join(f))

    def put(self, slot: int, data: bytes) -> None:
        """Fill a staging buffer, in chunks the device's line can hold."""
        if len(data) > self.stage_cap:
            raise Skip("needs %d staging bytes, device has %d"
                       % (len(data), self.stage_cap))
        # "put S OOOOOO h" plus the frame; leave generous room.
        room = max(16, (self.line_cap - 48) // 2)
        off = 0
        while off < len(data) or (off == 0 and not data):
            chunk = data[off:off + room]
            st, f = self.link.ask("put %d %d h%s"
                                  % (slot, off, chunk.hex()))
            if st != "ok":
                raise Skip("put refused: %s" % " ".join(f))
            off += len(chunk)
            if not data:
                break

    def get(self, length: int) -> bytes:
        """Read the out buffer back, in chunks."""
        room = max(16, (self.line_cap - 48) // 2)
        out = bytearray()
        off = 0
        while off < length:
            take = min(room, length - off)
            st, f = self.link.ask("get %d %d" % (off, take))
            if st != "ok":
                raise ProtocolError("get: %s" % " ".join(f))
            if len(f) != 1 or not f[0].startswith("h"):
                raise ProtocolError("get: bad text field %r" % f[:1])
            piece = bytes.fromhex(f[0][1:])
            if len(piece) != take:
                raise ProtocolError("get returned %d bytes, asked %d"
                                    % (len(piece), take))
            out += piece
            off += take
        return bytes(out)


class Skip(Exception):
    """This case cannot be asked of this device. Not a failure; it is
    counted and named, and never scored as checked."""


# ---------------------------------------------------------------------
# The sets, in cft_conformance()'s order
# ---------------------------------------------------------------------

def discover(vdir: str) -> list[tuple[str, str, dict]]:
    """(path, kind, meta) for every set file present, in the order
    host/src/conformance.c walks them - per format, then the formatOf
    pairs. The order is not cosmetic: a report that lists sets in a
    different order than cft-selftest's cannot be read beside it."""
    sets: list[tuple[str, str, dict]] = []

    def add(name: str, kind: str, **meta):
        p = os.path.join(vdir, name + ".jsonl")
        if os.path.exists(p):
            sets.append((p, kind, meta))

    for fmt in FORMATS:
        for ri, rnd in enumerate(ROUNDINGS):
            add(fmt if ri == 0 else "%s-%s" % (fmt, rnd), "elementwise",
                fmt=fmt)
        for ri, rnd in enumerate(ROUNDINGS):
            add("%s-transcend" % fmt if ri == 0
                else "%s-transcend-%s" % (fmt, rnd), "transcend", fmt=fmt)
        add("%s-augmented" % fmt, "augmented", fmt=fmt)
        for ri, rnd in enumerate(ROUNDINGS):
            add("%s-reduce" % fmt if ri == 0
                else "%s-reduce-%s" % (fmt, rnd), "reduce", fmt=fmt)
        for ri, rnd in enumerate(ROUNDINGS):
            add("%s-character" % fmt if ri == 0
                else "%s-character-%s" % (fmt, rnd), "character", fmt=fmt)
        add("%s-minmaxmag" % fmt, "minmaxmag", fmt=fmt)

    for sfmt in FORMATS:
        for dfmt in FORMATS:
            for ri, rnd in enumerate(ROUNDINGS):
                base = "%s-to-%s-formatof" % (sfmt, dfmt)
                add(base if ri == 0 else "%s-%s" % (base, rnd),
                    "formatof", fmt=sfmt, dfmt=dfmt)
    return sets


# Which verb each kind of set needs, so a set can be skipped by NAME on
# a device whose build left that verb out rather than failing case by
# case on a refusal.
KIND_VERB = {
    "elementwise": "run",
    "transcend": "trn",
    "augmented": "aug",
    "reduce": "red",
    "minmaxmag": "mmg",
    "formatof": "fof",
    "character": "chs",     # chw and pay ride along with it
}


# ---------------------------------------------------------------------
# One case
# ---------------------------------------------------------------------

class Mismatch(Exception):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text


def _elem(obj: dict, key: str, nbytes: int) -> str:
    """One element encoding, as the wire spells it.

    "0x" and exactly 2*nbytes hex digits, most significant first -
    host/src/conformance.c's parse_hex_elem, which accepts either case
    of the x and of the digits. Lowercased on the way out, because the
    device answers in lowercase and the comparison is a string one."""
    v = obj[key]
    if not isinstance(v, str) or v[:2].lower() != "0x":
        raise ValueError("%s is not an encoding: %r" % (key, v))
    h = v[2:].lower()
    if len(h) != 2 * nbytes:
        raise ValueError("%s is %d hex digits, expected %d"
                         % (key, len(h), 2 * nbytes))
    return h


def _fail(path: str, lineno: int, head: str, rows: list[tuple[str, str]]
          ) -> Mismatch:
    body = "%s:%d: %s\n" % (path, lineno, head)
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        body += "  %-*s %s\n" % (width, k, v)
    return Mismatch(body)


def run_case(dev: Device, kind: str, meta: dict, obj: dict, path: str,
             lineno: int) -> None:
    """Ask one case and compare. Raises Mismatch, Skip or ProtocolError."""
    fmt = meta["fmt"]
    nb = FMT_BYTES[fmt]

    if kind == "elementwise":
        rnd, op = obj["rnd"], obj["op"]
        a, b, c = (_elem(obj, k, nb) for k in ("a", "b", "c"))
        want_d, want_fl = _elem(obj, "d", nb), int(obj["flags"])
        st, f = dev.ask("run %s %s %s %s %s %s" % (fmt, rnd, op, a, b, c))
        if st != "ok":
            raise Skip("%s %s: %s" % (op, rnd, " ".join(f)))
        got_d, got_fl = f[0], int(f[1], 16)
        if got_d != want_d or got_fl != want_fl:
            raise _fail(path, lineno, "%s %s %s" % (fmt, op, rnd), [
                ("a", "0x" + a), ("b", "0x" + b), ("c", "0x" + c),
                ("expected", "0x%s flags 0x%02x" % (want_d, want_fl)),
                ("got", "0x%s flags 0x%02x" % (got_d, got_fl))])
        return

    if kind == "transcend":
        rnd, fn = obj["rnd"], obj["fn"]
        a = _elem(obj, "a", nb)
        b = _elem(obj, "b", nb) if "b" in obj else "-"
        n = str(obj["n"]) if "n" in obj else "-"
        want_d, want_fl = _elem(obj, "d", nb), int(obj["flags"])
        st, f = dev.ask("trn %s %s %s %s %s %s"
                             % (fmt, rnd, fn, a, b, n))
        if st != "ok":
            raise Skip("%s %s: %s" % (fn, rnd, " ".join(f)))
        got_d, got_fl = f[0], int(f[1], 16)
        if got_d != want_d or got_fl != want_fl:
            raise _fail(path, lineno, "%s %s %s" % (fmt, fn, rnd), [
                ("a", "0x" + a), ("b", "0x" + b if b != "-" else "-"),
                ("n", n),
                ("expected", "0x%s flags 0x%02x" % (want_d, want_fl)),
                ("got", "0x%s flags 0x%02x" % (got_d, got_fl))])
        return

    if kind == "augmented":
        fn = obj["fn"]
        a, b = _elem(obj, "a", nb), _elem(obj, "b", nb)
        want_r, want_e = _elem(obj, "r", nb), _elem(obj, "e", nb)
        want_fl = int(obj["flags"])
        st, f = dev.ask("aug %s %s %s %s" % (fmt, fn, a, b))
        if st != "ok":
            raise Skip("%s: %s" % (fn, " ".join(f)))
        got_r, got_e, got_fl = f[0], f[1], int(f[2], 16)
        if got_r != want_r or got_e != want_e or got_fl != want_fl:
            raise _fail(path, lineno, "%s %s" % (fmt, fn), [
                ("a", "0x" + a), ("b", "0x" + b),
                ("expected", "0x%s 0x%s flags 0x%02x"
                 % (want_r, want_e, want_fl)),
                ("got", "0x%s 0x%s flags 0x%02x"
                 % (got_r, got_e, got_fl))])
        return

    if kind == "minmaxmag":
        fn = obj["fn"]
        a, b = _elem(obj, "a", nb), _elem(obj, "b", nb)
        want_d, want_fl = _elem(obj, "d", nb), int(obj["flags"])
        st, f = dev.ask("mmg %s %s %s %s" % (fmt, fn, a, b))
        if st != "ok":
            raise Skip("%s: %s" % (fn, " ".join(f)))
        got_d, got_fl = f[0], int(f[1], 16)
        if got_d != want_d or got_fl != want_fl:
            raise _fail(path, lineno, "%s %s" % (fmt, fn), [
                ("a", "0x" + a), ("b", "0x" + b),
                ("expected", "0x%s flags 0x%02x" % (want_d, want_fl)),
                ("got", "0x%s flags 0x%02x" % (got_d, got_fl))])
        return

    if kind == "formatof":
        dfmt = meta["dfmt"]
        dnb = FMT_BYTES[dfmt]
        fn, rnd = obj["fn"], obj["rnd"]
        a = _elem(obj, "a", nb)
        b = _elem(obj, "b", nb) if "b" in obj else "-"
        c = _elem(obj, "c", nb) if "c" in obj else "-"
        want_d, want_fl = _elem(obj, "d", dnb), int(obj["flags"])
        st, f = dev.ask("fof %s %s %s %s %s %s %s"
                             % (fmt, dfmt, rnd, fn, a, b, c))
        if st != "ok":
            raise Skip("%s %s: %s" % (fn, rnd, " ".join(f)))
        got_d, got_fl = f[0], int(f[1], 16)
        if got_d != want_d or got_fl != want_fl:
            raise _fail(path, lineno, "%s->%s %s %s"
                        % (fmt, dfmt, fn, rnd), [
                ("a", "0x" + a), ("b", "0x" + b if b != "-" else "-"),
                ("c", "0x" + c if c != "-" else "-"),
                ("expected", "0x%s flags 0x%02x" % (want_d, want_fl)),
                ("got", "0x%s flags 0x%02x" % (got_d, got_fl))])
        return

    if kind == "reduce":
        fn, rnd, n = obj["fn"], obj["rnd"], int(obj["n"])
        # Packed little-endian elements: exactly what cft_reduce reads,
        # so the device converts nothing and cannot convert it wrongly.
        va = b"".join(bytes.fromhex(x[2:])[::-1] for x in obj["a"])
        if len(va) != n * nb:
            raise ValueError("\"a\" holds %d elements, \"n\" says %d"
                             % (len(va) // nb, n))
        binary = "b" in obj
        dev.clr()
        dev.put(0, va)
        if binary:
            vb = b"".join(bytes.fromhex(x[2:])[::-1] for x in obj["b"])
            dev.put(1, vb)
        scaled = fn.startswith("scaled_prod")
        want_fl = int(obj["flags"])
        want_d = _elem(obj, "pr" if scaled else "d", nb)
        want_sf = int(obj.get("sf", 0))
        st, f = dev.ask("red %s %s %s %d" % (fmt, rnd, fn, n))
        if st != "ok":
            raise Skip("%s %s n=%d: %s" % (fn, rnd, n, " ".join(f)))
        if scaled:
            got_d, got_sf, got_fl = f[0], int(f[1]), int(f[2], 16)
        else:
            got_d, got_sf, got_fl = f[0], 0, int(f[1], 16)
        if got_d != want_d or got_fl != want_fl or got_sf != want_sf:
            raise _fail(path, lineno,
                        "%s %s %s over %d elements" % (fmt, fn, rnd, n), [
                ("expected", "0x%s scale %d flags 0x%02x"
                 % (want_d, want_sf, want_fl)),
                ("got", "0x%s scale %d flags 0x%02x"
                 % (got_d, got_sf, got_fl))])
        return

    if kind == "character":
        fn, rnd = obj["fn"], obj["rnd"]

        if fn in ("from_decimal", "from_hex"):
            seq = obj["s"].encode("utf-8")
            refuse = "refuse" in obj
            # Inline when the hex fits the device's line, staged when
            # it does not. Both paths run in every full census: the
            # 5.12 sets carry sequences from one byte to eleven
            # thousand.
            if 2 * len(seq) + 64 <= dev.line_cap:
                field = "h" + seq.hex()
            else:
                dev.clr()
                dev.put(0, seq)
                field = "@"
            st, f = dev.ask("chs %s %s %s %s" % (fmt, rnd, fn, field))
            if refuse:
                if st == "err" and f and f[0] == "refused":
                    return
                if st == "ok":
                    raise _fail(path, lineno,
                                "%s %s ACCEPTED a sequence that is not in "
                                "the syntax" % (fmt, fn),
                                [("s", repr(obj["s"])[:200]),
                                 ("got", "0x%s" % f[0])])
                raise Skip("%s: %s" % (fn, " ".join(f)))
            if st != "ok":
                if f and f[0] == "refused":
                    raise _fail(path, lineno,
                                "%s %s %s REFUSED a sequence in the syntax"
                                % (fmt, fn, rnd),
                                [("s", repr(obj["s"])[:200]),
                                 ("expected", "0x%s" % _elem(obj, "d", nb))])
                raise Skip("%s: %s" % (fn, " ".join(f)))
            want_d, want_fl = _elem(obj, "d", nb), int(obj["flags"])
            got_d, got_fl = f[0], int(f[1], 16)
            if got_d != want_d or got_fl != want_fl:
                raise _fail(path, lineno, "%s %s %s" % (fmt, fn, rnd), [
                    ("s", repr(obj["s"])[:200]),
                    ("expected", "0x%s flags 0x%02x" % (want_d, want_fl)),
                    ("got", "0x%s flags 0x%02x" % (got_d, got_fl))])
            return

        if fn in ("to_decimal", "to_hex"):
            a = _elem(obj, "a", nb)
            digits = int(obj.get("digits", 0))
            want_s = obj["s"].encode("utf-8")
            want_fl = int(obj["flags"])
            st, f = dev.ask("chw %s %s %s %d %s"
                                 % (fmt, rnd, fn, digits, a))
            if st != "ok":
                raise Skip("%s a=0x%s digits=%d: %s"
                           % (fn, a, digits, " ".join(f)))
            got_len, got_fl = int(f[0]), int(f[1], 16)
            got_s = dev.get(got_len)
            if got_s != want_s or got_fl != want_fl:
                raise _fail(path, lineno, "%s %s %s a=0x%s digits=%d"
                            % (fmt, fn, rnd, a, digits), [
                    ("expected", "%s flags 0x%02x"
                     % (want_s.decode("utf-8", "replace")[:200], want_fl)),
                    ("got", "%s flags 0x%02x"
                     % (got_s.decode("utf-8", "replace")[:200], got_fl))])
            return

        # The three 9.7 payload operations: no attribute, no flags.
        a = _elem(obj, "a", nb)
        want_d = _elem(obj, "d", nb)
        st, f = dev.ask("pay %s %s %s" % (fmt, fn, a))
        if st != "ok":
            raise Skip("%s: %s" % (fn, " ".join(f)))
        if f[0] != want_d:
            raise _fail(path, lineno, "%s %s" % (fmt, fn), [
                ("a", "0x" + a),
                ("expected", "0x" + want_d), ("got", "0x" + f[0])])
        return

    raise ValueError("unknown set kind %r" % kind)


# ---------------------------------------------------------------------
# The replay
# ---------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.notes: list[str] = []
        self.sets = 0
        self.cases = 0
        self.skipped: dict[str, int] = {}
        self.failure: str | None = None
        # Kept out of `notes`, because a failure returns before the
        # timing is known and a printer that assumed the last note was
        # the timing would then swallow a real one.
        self.elapsed = 0.0

    def note(self, text: str) -> None:
        self.notes.append(text)

    def skip(self, why: str) -> None:
        self.skipped[why] = self.skipped.get(why, 0) + 1


def replay(dev: Device, vdir: str, patterns: list[str] | None,
           limit: int | None, out, progress: bool) -> Report:
    rep = Report()
    all_sets = discover(vdir)
    if not all_sets:
        rep.note("no vector sets found under %s - nothing was checked" % vdir)
        rep.failure = "no sets"
        return rep

    chosen = []
    for path, kind, meta in all_sets:
        base = os.path.basename(path)[:-len(".jsonl")]
        if patterns and not any(fnmatch.fnmatch(base, p) for p in patterns):
            continue
        chosen.append((path, kind, meta))
    if not chosen:
        rep.note("no set matched %s - nothing was checked"
                 % ", ".join(patterns or []))
        rep.failure = "no sets matched"
        return rep

    t0 = time.perf_counter()
    for path, kind, meta in chosen:
        rel = os.path.relpath(path, REPO).replace(os.sep, "/")
        fmt = meta["fmt"]
        need = [fmt] + ([meta["dfmt"]] if "dfmt" in meta else [])
        missing = [f for f in need if not dev.has_format(f)]
        if missing:
            rep.note("%s: skipped, %s not on this device"
                     % (rel, " or ".join(sorted(set(missing)))))
            continue
        verb = KIND_VERB[kind]
        if dev.verbs and verb not in dev.verbs:
            rep.note("%s: skipped, this build has no `%s` (%s)"
                     % (rel, verb, kind))
            continue

        rep.sets += 1
        n_here = 0
        with open(path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                if limit is not None and n_here >= limit:
                    break
                obj = json.loads(line)
                try:
                    run_case(dev, kind, meta, obj, rel, lineno)
                except Skip as s:
                    rep.skip("%s: %s" % (rel, s))
                    continue
                except Mismatch as m:
                    rep.failure = m.text
                    return rep
                rep.cases += 1
                n_here += 1
                if progress and rep.cases % 2000 == 0:
                    el = time.perf_counter() - t0
                    out.write("\r  %d cases, %.0f/s   "
                              % (rep.cases, rep.cases / el if el else 0))
                    out.flush()
    if progress:
        out.write("\r" + " " * 40 + "\r")
        out.flush()
    rep.elapsed = time.perf_counter() - t0
    return rep


def print_report(dev: Device, vdir: str, rep: Report, out) -> None:
    for n in rep.notes:
        out.write(n + "\n")
    if rep.failure:
        out.write("\n" + rep.failure)
        out.write("\nCONFORMANCE FAILED after %d matching cases\n"
                  % rep.cases)
        return
    if rep.skipped:
        total = sum(rep.skipped.values())
        out.write("%d case%s skipped, by reason:\n"
                  % (total, "" if total == 1 else "s"))
        for why, k in sorted(rep.skipped.items(),
                             key=lambda kv: -kv[1])[:20]:
            out.write("  %6d  %s\n" % (k, why))
        if len(rep.skipped) > 20:
            out.write("  ... and %d more reasons\n" % (len(rep.skipped) - 20))
    out.write("%d set%s, %d cases, all matching (one element at a time, "
              "which is the pass that pins each case's exception flags "
              "exactly; cft_conformance()'s second pass replays a set as "
              "ARRAYS to exercise a device backend's partitioning across "
              "tiles, and there are no tiles behind a serial port)\n"
              % (rep.sets, "" if rep.sets == 1 else "s", rep.cases))
    out.write("%d cases checked\n" % rep.cases)


def print_device(dev: Device, transport: str, out) -> None:
    out.write("libcft ABI %s over %s\n" % (dev.abi, dev.protocol))
    out.write("transport      %s\n" % transport)
    out.write("backend        %s\n" % dev.backend)
    out.write("formats        %s\n" % " ".join(dev.formats()))
    out.write("buffers        line %d, stage %d x2, out %d\n"
              % (dev.line_cap, dev.stage_cap, dev.out_cap))
    out.write("verbs          %s\n" % ",".join(sorted(dev.verbs)))


# ---------------------------------------------------------------------
# The negative control
# ---------------------------------------------------------------------

CORRUPT_MODES = [
    ("bits", "the result encoding, one nibble"),
    ("flags", "the exception flags, one nibble"),
    ("crc", "the frame's checksum, answer intact"),
    ("seq", "the sequence number, answer intact"),
    ("drop", "no answer at all"),
    ("text", "a to_decimal sequence, one nibble"),
]


def corrupt_battery(exe: str, vdir: str, out) -> int:
    """Run the harness against a loopback that answers wrongly, once
    per way of being wrong, and require it to notice every time.

    A green conformance report is only evidence if the thing producing
    it can produce a red one. Six modes rather than one because they
    reach six different checks - two comparisons, two frame rules, the
    timeout, and the character-sequence path that comes back through
    `get` - and a harness that caught only the first would have five
    untested alarms."""
    ok = True
    out.write("negative control: the loopback answers wrongly on "
              "purpose, six ways\n\n")
    for mode, what in CORRUPT_MODES:
        # `text` has to damage an answer that carries a character
        # sequence, which is a `get`; the rest damage the first `run`.
        # Named by VERB rather than by position, so that a change in
        # how many round trips a case takes cannot quietly move the
        # corruption onto a line where it would test nothing.
        if mode == "text":
            sets, verb, limit = ["fp32-character"], "get", 12
        else:
            sets, verb, limit = ["fp32"], "run", 8
        argv = [exe, "--corrupt", mode, "--corrupt-at", "1",
                "--corrupt-verb", verb]
        link = PipeLink(argv, timeout=3.0)
        caught, detail = False, ""
        try:
            dev = Device(link)
            rep = replay(dev, vdir, sets, limit, out, False)
            if rep.failure:
                caught = True
                detail = rep.failure.strip().split("\n")[0]
            else:
                detail = "%d cases, all matching" % rep.cases
        except ProtocolError as e:
            caught = True
            detail = str(e).split("\n")[0]
        finally:
            link.close()
        out.write("  %-6s %-38s %s\n     %s\n"
                  % (mode, what, "CAUGHT" if caught else "MISSED **",
                     detail[:150]))
        ok = ok and caught
    out.write("\n%s\n" % ("every corruption was caught - the harness can "
                          "fail, so its passes mean something"
                          if ok else
                          "AT LEAST ONE CORRUPTION WENT UNNOTICED"))
    return 0 if ok else 1


# ---------------------------------------------------------------------

def default_loopback() -> str:
    base = os.path.join(REPO, "bindings", "arduino", "loopback",
                        "cft-replay-loopback-full")
    for cand in (base + ".exe", base):
        if os.path.exists(cand):
            return cand
    return base


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exit status is 0 only if every case that ran matched.")
    ap.add_argument("--vectors", default=os.path.join(REPO, "vectors", "out"),
                    help="the vector set directory (default vectors/out)")
    ap.add_argument("--port", help="serial port, e.g. COM7 or /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--settle", type=float, default=2.0,
                    help="seconds to wait after opening the port, for a "
                         "board that resets when it is opened (default 2)")
    ap.add_argument("--loopback", nargs="?", const="", metavar="EXE",
                    help="drive a local process instead of a port")
    ap.add_argument("--loopback-arg", action="append", default=[],
                    metavar="ARG", help="extra argument for the loopback "
                                        "process; repeatable")
    ap.add_argument("--corrupt", action="store_true",
                    help="run the negative control battery (implies "
                         "--loopback)")
    ap.add_argument("--sets", help="comma-separated globs over set names, "
                                   "e.g. 'fp32*,fp64-reduce*'")
    ap.add_argument("--limit", type=int, help="at most N cases per set")
    ap.add_argument("--timeout", type=float, default=10.0,
                    help="seconds to wait for one answer (default 10)")
    ap.add_argument("--list-sets", action="store_true",
                    help="print the sets that would run, and stop")
    ap.add_argument("--progress", action="store_true",
                    help="a running case count on stderr")
    args = ap.parse_args()
    out = sys.stdout

    if args.list_sets:
        for path, kind, meta in discover(args.vectors):
            base = os.path.basename(path)[:-len(".jsonl")]
            if args.sets and not any(fnmatch.fnmatch(base, p)
                                     for p in args.sets.split(",")):
                continue
            n = sum(1 for _ in open(path, "r", encoding="utf-8"))
            out.write("%-40s %-12s %7d\n" % (base, kind, n))
        return 0

    if args.corrupt:
        exe = args.loopback or default_loopback()
        if not os.path.exists(exe):
            out.write("no loopback binary at %s\n"
                      "build it: make -C bindings/arduino/loopback\n" % exe)
            return 2
        return corrupt_battery(exe, args.vectors, out)

    if args.loopback is not None:
        exe = args.loopback or default_loopback()
        if not os.path.exists(exe):
            out.write("no loopback binary at %s\n"
                      "build it: make -C bindings/arduino/loopback\n" % exe)
            return 2
        link = PipeLink([exe] + args.loopback_arg, args.timeout)
        transport = "loopback %s" % os.path.basename(exe)
    elif args.port:
        link = SerialLink(args.port, args.baud, args.timeout, args.settle)
        transport = "%s at %d baud" % (args.port, args.baud)
    else:
        ap.error("give --port or --loopback")
        return 2

    try:
        dev = Device(link)
        print_device(dev, transport, out)
        out.write("\nreplaying %s\n"
                  % os.path.relpath(args.vectors, REPO).replace(os.sep, "/"))
        patterns = args.sets.split(",") if args.sets else None
        rep = replay(dev, args.vectors, patterns, args.limit, sys.stderr,
                     args.progress)
        print_report(dev, args.vectors, rep, out)
        if link.resyncs:
            out.write("%d line%s on this link were not answers to the "
                      "request outstanding\n"
                      % (link.resyncs, "" if link.resyncs == 1 else "s"))
        out.write("%.1f s, %.0f cases a second\n"
                  % (rep.elapsed,
                     rep.cases / rep.elapsed if rep.elapsed > 0 else 0))
        return 0 if rep.failure is None else 1
    except ProtocolError as e:
        out.write("\nPROTOCOL FAILURE: %s\n" % e)
        return 1
    finally:
        link.close()


if __name__ == "__main__":
    sys.exit(main())
