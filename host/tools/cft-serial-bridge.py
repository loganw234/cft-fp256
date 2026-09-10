#!/usr/bin/env python3
# Copyright 2026 Logan W.
# SPDX-License-Identifier: Apache-2.0
"""A byte pipe between a board's serial port and a cft-serve TCP port.

    python host/tools/cft-serial-bridge.py --serial COM5 --server 127.0.0.1:7754

That is the whole idea. A board with no network - an Uno, a Nano, a
Mega, a Pico - speaks the frame protocol of docs/REMOTE.md over its USB
serial port, and this copies those bytes to a server and the server's
bytes back. It is DELIBERATELY FRAMING-AGNOSTIC by default: it does not
parse, buffer, reorder or rewrite anything, because the protocol's
frames already carry their own length and their own CRC and a
transport that "helps" is a transport that can corrupt. What crosses
this bridge is byte for byte what the board sent, and the CRC on the
far end is what says so.

    --verbose      decode and print each frame's header as it goes past,
                   forwarding every byte unchanged. Reading, never
                   editing: this is a debugging window, not a filter.
    --framed       the one mode that is not a pure pipe, and it exists
                   for one board: an Uno and a Nano have ONE UART, so a
                   sketch that prints has to print down the same wire it
                   speaks the protocol on. In this mode the board-to-
                   server direction is followed frame by frame, whole
                   frames are forwarded, and any bytes BETWEEN frames
                   are printed here as the board's log instead of being
                   sent to a server that would refuse them and close.
    --loopback     prove the bridge with no board and no server: a
                   socket pair stands in for the serial port, a stub
                   stands in for cft-serve, and every byte is checked
                   both ways, in both modes, including a resync from
                   garbage.
    --probe-abi H:P  ask a server which libcft it is, so a sketch can
                   claim the right ABI word. It sends a HELLO with a
                   deliberately impossible ABI and reads the server's
                   own out of the REFUSAL's header - which is a legal
                   thing to do to this protocol, and the only way for a
                   client with no libcft to find the number.
    --serial-tcp N   take the BOARD side from a TCP connection on port N
                   instead of a serial port. For the host-side proof
                   (the client and the bridge in one pipeline, no
                   hardware), and for a serial device server on a
                   network.
    --list         the serial ports this machine has.

Needs Python 3 and pyserial, and nothing else.
"""

import argparse
import binascii
import os
import socket
import struct
import sys
import threading
import time

MAGIC = b"CFTR"
HDR = 32
PROTO = 1

KIND = {0: "request", 1: "response", 2: "refusal"}
OPS = {
    0x0001: "HELLO", 0x0002: "CAPS", 0x0003: "STATS",
    0x0010: "RUN", 0x0011: "REDUCE",
    0x0020: "PROG_LOAD", 0x0021: "PROG_RUN", 0x0022: "PROG_FREE",
    0x0023: "PROG_RUN_BANK", 0x0024: "PROG_RUN_EX",
    0x0030: "BUF_ALLOC", 0x0031: "BUF_FREE", 0x0032: "BUF_WRITE",
    0x0033: "BUF_READ",
    0x0040: "FLAGS_LOWER", 0x0041: "FLAGS_RAISE", 0x0042: "FLAGS_TEST",
    0x0043: "FLAGS_SAVE", 0x0044: "FLAGS_RESTORE", 0x0045: "FLAGS_TEST_SAVED",
    0x00FF: "BYE",
}
# cft_status, in cft.h's order.
STATUS = ["ok", "invalid argument",
          "operation or format not available on this device",
          "no such device", "artifact missing, unreadable, or not a tile",
          "memory system fault: the output is not valid", "out of memory",
          "timed out", "internal error"]


def log(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


# ---------------------------------------------------------------- frames

def unpack_header(h):
    """The 32 bytes of docs/REMOTE.md's header, or None if they are not
    one. Checks exactly what a receiver checks before it reads a
    payload: the magic, the protocol version and the reserved word."""
    if len(h) < HDR or h[0:4] != MAGIC:
        return None
    proto, kind, abi, ident, op, status, length, crc, resv = \
        struct.unpack_from("<HHIIHHIII", h, 4)
    if proto != PROTO or resv != 0:
        return None
    return dict(proto=proto, kind=kind, abi=abi, id=ident, op=op,
                status=status, length=length, crc=crc)


def describe(h, where):
    return ("%s %-8s %-14s id %-5d abi %d.%d  %6d bytes  status %d (%s)"
            % (where, KIND.get(h["kind"], "?%d" % h["kind"]),
               OPS.get(h["op"], "op 0x%04x" % h["op"]), h["id"],
               h["abi"] >> 16, h["abi"] & 0xFFFF, h["length"], h["status"],
               STATUS[h["status"]] if h["status"] < len(STATUS) else "?"))


class Scanner:
    """Follows the framing in one direction without ever holding a
    payload: at most the 32 bytes of a header, then a countdown.

    feed(bytes) yields ("text", b), ("header", b), ("payload", b) in
    order. A pure pipe ignores what it yields and forwards the original
    bytes; --framed forwards only the header and payload parts and
    prints the text; --verbose uses the headers and forwards
    everything. One scanner, three uses, no second parser."""

    def __init__(self):
        self.buf = bytearray()
        self.left = 0

    def feed(self, data):
        pending = bytearray(data)
        while pending:
            if self.left:                   # inside a payload: count down
                k = min(self.left, len(pending))
                yield ("payload", bytes(pending[:k]))
                del pending[:k]
                self.left -= k
                continue
            self.buf.append(pending[0])
            del pending[:1]
            n = len(self.buf)
            if n <= 4:
                # A candidate is only a candidate while it is still a
                # prefix of the magic. When it stops being one, its
                # FIRST byte is text and the rest goes back in front of
                # the stream - so "CFT" followed by a real frame does
                # not swallow the frame.
                if bytes(self.buf) != MAGIC[:n]:
                    yield ("text", bytes(self.buf[:1]))
                    rest = bytes(self.buf[1:])
                    self.buf = bytearray()
                    pending[:0] = rest
                continue
            if n < HDR:
                continue
            hdr = bytes(self.buf)
            self.buf = bytearray()
            h = unpack_header(hdr)
            if h is None:
                # The magic was a coincidence in text: same rule.
                yield ("text", hdr[:1])
                pending[:0] = hdr[1:]
                continue
            self.left = h["length"]
            yield ("header", hdr)


# ---------------------------------------------------------------- pipes

class Pipe:
    """read_some(n) returns up to n bytes, b'' when nothing arrived
    before the timeout, and None at end of stream."""
    def read_some(self, n):
        raise NotImplementedError

    def write_all(self, b):
        raise NotImplementedError

    def close(self):
        pass


class SerialPipe(Pipe):
    def __init__(self, port, baud, timeout=0.05, rtscts=False, dsrdtr=False):
        import serial                       # pyserial, imported here so
        self.s = serial.Serial()            # --loopback needs nothing
        self.s.port = port
        self.s.baudrate = baud
        self.s.timeout = timeout
        self.s.rtscts = rtscts
        self.s.dsrdtr = dsrdtr
        self.s.open()

    def read_some(self, n):
        # What is already there, immediately; otherwise block for
        # one byte until the timeout. Asking for n outright would
        # wait the whole timeout for a frame that is already
        # complete.
        k = self.s.in_waiting
        b = self.s.read(min(k, n) if k else 1)
        return b if b else b""

    def write_all(self, b):
        self.s.write(b)
        self.s.flush()

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


class SockPipe(Pipe):
    def __init__(self, sock, timeout=0.05):
        self.s = sock
        self.s.settimeout(timeout)

    def read_some(self, n):
        try:
            b = self.s.recv(n)
        except socket.timeout:
            return b""
        except OSError:
            return None
        return b if b else None

    def write_all(self, b):
        self.s.sendall(b)

    def close(self):
        try:
            self.s.close()
        except OSError:
            pass


# ---------------------------------------------------------------- pumping

class Pump:
    """One direction. Forwards bytes; the scanner is a passive observer
    unless `framed` is set, in which case only frames are forwarded and
    everything between them is the board's log."""

    def __init__(self, src, dst, where, verbose=False, framed=False,
                 counters=None):
        self.src, self.dst = src, dst
        self.where = where
        self.verbose = verbose
        self.framed = framed
        self.scan = Scanner()
        self.text = bytearray()
        self.counters = counters if counters is not None else {}
        self.counters.setdefault("bytes", 0)
        self.counters.setdefault("frames", 0)
        self.counters.setdefault("text", 0)
        self.stop = threading.Event()
        self.ended = threading.Event()

    def _flush_text(self, force=False):
        while True:
            i = self.text.find(b"\n")
            if i < 0:
                break
            line = bytes(self.text[:i]).rstrip(b"\r")
            del self.text[:i + 1]
            log("  %s log: %s" % (self.where,
                                  line.decode("utf-8", "replace")))
        if force and self.text:
            log("  %s log: %s" % (self.where,
                                  bytes(self.text).decode("utf-8", "replace")))
            self.text = bytearray()

    def run(self):
        try:
            while not self.stop.is_set():
                b = self.src.read_some(4096)
                if b is None:
                    break
                if not b:
                    if self.framed:
                        self._flush_text()
                    continue
                self.counters["bytes"] += len(b)
                if not (self.verbose or self.framed):
                    self.dst.write_all(b)
                    continue
                out = bytearray()
                for kind, chunk in self.scan.feed(b):
                    if kind == "header":
                        self.counters["frames"] += 1
                        if self.verbose:
                            h = unpack_header(chunk)
                            log(describe(h, self.where))
                        if self.framed:
                            self._flush_text(force=True)
                            out += chunk
                    elif kind == "payload":
                        if self.framed:
                            out += chunk
                    else:
                        self.counters["text"] += len(chunk)
                        if self.framed:
                            self.text += chunk
                if self.framed:
                    if out:
                        self.dst.write_all(bytes(out))
                    self._flush_text()
                else:
                    self.dst.write_all(b)
        except Exception as e:              # a closed pipe ends a session
            if not self.stop.is_set():
                log("  %s ended: %s" % (self.where, e))
        finally:
            self.ended.set()


def session(board, server, verbose=False, framed=False):
    """Pump both directions until either end goes quiet. Returns the two
    counter dicts."""
    up = {}
    down = {}
    a = Pump(board, server, "board->server", verbose, framed, up)
    b = Pump(server, board, "server->board", verbose, False, down)
    ta = threading.Thread(target=a.run, daemon=True)
    tb = threading.Thread(target=b.run, daemon=True)
    ta.start()
    tb.start()
    try:
        while not (a.ended.is_set() or b.ended.is_set()):
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    a.stop.set()
    b.stop.set()
    return up, down


# ---------------------------------------------------------------- probe

def probe_abi(where):
    """The server's own ABI word, read out of the header of the refusal
    it sends to a HELLO that claims an impossible one.

    Every frame carries the SENDER's cft_abi_version() and both ends
    compare for equality, so a client that is not libcft has to be told
    the number - and this is where it comes from. The server refuses
    0.0, and its refusal is a frame, and a frame's header carries its
    sender's ABI. Nothing is guessed and nothing is transcribed."""
    host, _, port = where.rpartition(":")
    s = socket.create_connection((host or "127.0.0.1", int(port)), 10)
    try:
        h = bytearray(HDR)
        h[0:4] = MAGIC
        struct.pack_into("<HHIIHHIII", h, 4, PROTO, 0, 0, 1, 0x0001, 0, 0, 0, 0)
        struct.pack_into("<I", h, 24, binascii.crc32(bytes(h)) & 0xFFFFFFFF)
        s.sendall(bytes(h))
        s.settimeout(10)
        got = b""
        while len(got) < HDR:
            c = s.recv(HDR - len(got))
            if not c:
                sys.exit("probe-abi: the server closed without answering")
            got += c
        hh = unpack_header(got)
        if hh is None:
            sys.exit("probe-abi: the answer is not a cft frame")
        msg = b""
        while len(msg) < hh["length"]:
            c = s.recv(hh["length"] - len(msg))
            if not c:
                break
            msg += c
    finally:
        s.close()
    abi = hh["abi"]
    print("server            %s" % where)
    print("kind              %s" % KIND.get(hh["kind"], hh["kind"]))
    if msg:
        print("message           %s" % msg.rstrip(b"\x00").decode("utf-8",
                                                                 "replace"))
    print("abi word          0x%08x   (libcft %d.%d)"
          % (abi, abi >> 16, abi & 0xFFFF))
    print()
    print("put this in the sketch:")
    print("    #define CFT_REMOTE_ABI 0x%08XUL" % abi)
    return 0


# ---------------------------------------------------------------- loopback

def _frame(op, payload=b"", abi=11, ident=1, kind=0, status=0):
    h = bytearray(HDR)
    h[0:4] = MAGIC
    struct.pack_into("<HHIIHHIII", h, 4, PROTO, kind, abi, ident, op, status,
                     len(payload), 0, 0)
    crc = binascii.crc32(bytes(h))
    crc = binascii.crc32(payload, crc) & 0xFFFFFFFF
    struct.pack_into("<I", h, 24, crc)
    return bytes(h) + payload


def loopback(verbose=False):
    """The bridge proved with no board and no server.

    A socket pair stands in for the serial port and a second one for
    cft-serve, so the bytes really do cross two pipes and two threads,
    and every check is on what came out the other side."""
    fails = []
    total = [0]

    def want(ok, what):
        total[0] += 1
        print("  %-4s %s" % ("ok" if ok else "FAIL", what))
        if not ok:
            fails.append(what)

    print("cft-serial-bridge --loopback")

    print("\nthe header decoder")
    f = _frame(0x0010, b"\x01\x02\x03\x04")
    h = unpack_header(f[:HDR])
    want(h is not None and h["op"] == 0x0010 and h["length"] == 4 and
         h["abi"] == 11, "a RUN header decodes: op, length and abi")
    want(unpack_header(b"XXXX" + f[4:HDR]) is None, "a wrong magic is not one")
    bad = bytearray(f[:HDR])
    bad[4] = 9
    want(unpack_header(bytes(bad)) is None,
         "a protocol version this bridge does not know is not one")
    bad = bytearray(f[:HDR])
    bad[28] = 1
    want(unpack_header(bytes(bad)) is None,
         "a nonzero reserved word is not one")

    print("\nthe scanner, byte by byte")
    sc = Scanner()
    stream = b"boot ok\r\n" + _frame(0x0001) + _frame(0x0010, bytes(range(64)))
    text, frames, payload = bytearray(), 0, bytearray()
    for i in range(len(stream)):            # one byte at a time, the worst case
        for kind, chunk in sc.feed(stream[i:i + 1]):
            if kind == "text":
                text += chunk
            elif kind == "header":
                frames += 1
            else:
                payload += chunk
    want(bytes(text) == b"boot ok\r\n", "text before a frame stays text")
    want(frames == 2, "two frames are two frames")
    want(bytes(payload) == bytes(range(64)), "the payload comes through whole")

    sc = Scanner()
    junk = b"CFT" + b"CFTR" + b"not a header at all....."   # a near miss
    got, resynced = bytearray(), False
    for kind, chunk in sc.feed(junk + _frame(0x0011)):
        if kind == "text":
            got += chunk
        elif kind == "header":
            resynced = True
    want(resynced and bytes(got) == junk,
         "four magic bytes inside text do not swallow the next frame")

    print("\nthe pipe, both directions")
    b0, b1 = socket.socketpair()            # board end, bridge's board side
    s0, s1 = socket.socketpair()            # bridge's server side, server end
    board = SockPipe(b1)
    server = SockPipe(s0)
    up, down = {}, {}
    pa = Pump(board, server, "board->server", verbose, False, up)
    pb = Pump(server, board, "server->board", verbose, False, down)
    ta = threading.Thread(target=pa.run, daemon=True)
    tb = threading.Thread(target=pb.run, daemon=True)
    ta.start()
    tb.start()

    req = _frame(0x0010, bytes(range(256)) * 8)     # 2 kB, several reads
    b0.sendall(req)
    got = b""
    s1.settimeout(5)
    while len(got) < len(req):
        got += s1.recv(65536)
    want(got == req, "a 2 kB request arrives byte for byte (%d bytes)"
         % len(req))

    resp = _frame(0x0010, bytes(range(200)), kind=1)
    s1.sendall(resp)
    got = b""
    b0.settimeout(5)
    while len(got) < len(resp):
        got += b0.recv(65536)
    want(got == resp, "and the response comes back the same way")
    pa.stop.set()
    pb.stop.set()
    for s in (b0, b1, s0, s1):
        s.close()

    print("\n--framed: one UART carrying a log and a protocol")
    b0, b1 = socket.socketpair()
    s0, s1 = socket.socketpair()
    board = SockPipe(b1)
    server = SockPipe(s0)
    up = {}
    pa = Pump(board, server, "board->server", verbose, True, up)
    ta = threading.Thread(target=pa.run, daemon=True)
    ta.start()
    f1 = _frame(0x0001)
    f2 = _frame(0x0010, bytes(range(120)))
    b0.sendall(b"cft: hello from an Uno\r\n" + f1 +
               b"cft: asking for an fma\n" + f2)
    got = b""
    s1.settimeout(5)
    while len(got) < len(f1) + len(f2):
        got += s1.recv(65536)
    want(got == f1 + f2, "only the frames reach the server")
    want(up["text"] == len(b"cft: hello from an Uno\r\n"
                           b"cft: asking for an fma\n"),
         "and every byte of the log was held back (%d bytes)" % up["text"])
    pa.stop.set()
    for s in (b0, b1, s0, s1):
        s.close()

    print("\n%d checks, %d failed" % (total[0], len(fails)))
    return 1 if fails else 0


# ---------------------------------------------------------------- main

def list_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        sys.exit("cft-serial-bridge: pyserial is not installed "
                 "(pip install pyserial)")
    for p in sorted(list_ports.comports()):
        print("%-10s %s" % (p.device, p.description))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="a byte pipe between a board's serial port and cft-serve",
        epilog="docs/REMOTE.md is the protocol; this understands none of it.")
    ap.add_argument("--serial", help="the board's serial port (COM5, "
                                     "/dev/ttyACM0)")
    ap.add_argument("--serial-tcp", type=int, metavar="PORT",
                    help="take the board side from a TCP connection here")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--rtscts", action="store_true")
    ap.add_argument("--server", default="127.0.0.1:7754",
                    help="HOST:PORT of cft-serve (default 127.0.0.1:7754)")
    ap.add_argument("--verbose", action="store_true",
                    help="decode each frame's header as it goes past")
    ap.add_argument("--framed", action="store_true",
                    help="board->server: forward frames, print the rest as "
                         "the board's log")
    ap.add_argument("--forever", action="store_true",
                    help="keep serving sessions instead of exiting after one")
    ap.add_argument("--settle", type=float, default=0.0, metavar="SECONDS",
                    help="wait this long after opening the port before the "
                         "first byte crosses - a board that resets when the "
                         "port opens needs it")
    ap.add_argument("--loopback", action="store_true",
                    help="prove the bridge with no board and no server")
    ap.add_argument("--probe-abi", metavar="HOST:PORT",
                    help="ask a server which libcft it is")
    ap.add_argument("--list", action="store_true", help="list serial ports")
    args = ap.parse_args()

    if args.loopback:
        return loopback(args.verbose)
    if args.probe_abi:
        return probe_abi(args.probe_abi)
    if args.list:
        return list_ports()
    if not args.serial and args.serial_tcp is None:
        ap.error("one of --serial, --serial-tcp, --loopback, --probe-abi "
                 "or --list")

    host, _, port = args.server.rpartition(":")
    host = host or "127.0.0.1"
    port = int(port)

    listener = None
    board = None
    if args.serial_tcp is not None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", args.serial_tcp))
        listener.listen(1)
        log("bridge: board side on tcp 127.0.0.1:%d, server %s:%d, pid %d"
            % (args.serial_tcp, host, port, os.getpid()))
    else:
        board = SerialPipe(args.serial, args.baud, rtscts=args.rtscts)
        log("bridge: %s at %d baud <-> %s:%d, pid %d"
            % (args.serial, args.baud, host, port, os.getpid()))
        if args.settle:
            time.sleep(args.settle)

    rc = 0
    try:
        while True:
            if listener is not None:
                conn, _ = listener.accept()
                board = SockPipe(conn)
            try:
                sock = socket.create_connection((host, port), 15)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError as e:
                log("bridge: cannot reach %s:%d - %s" % (host, port, e))
                rc = 2
                break
            server = SockPipe(sock)
            up, down = session(board, server, args.verbose, args.framed)
            log("bridge: session over - %d bytes up (%d frames), %d bytes "
                "down (%d frames)" % (up["bytes"], up["frames"],
                                      down["bytes"], down["frames"]))
            server.close()
            if listener is not None:
                board.close()
                board = None
            if not args.forever:
                break
    except KeyboardInterrupt:
        pass
    finally:
        if board is not None:
            board.close()
        if listener is not None:
            listener.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
