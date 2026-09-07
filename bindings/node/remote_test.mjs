// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The WebSocket transport held to the contract, headless.
//
//     node bindings/node/remote_test.mjs [--serve PATH] [--vectors DIR]
//                                        [--cases N] [--sets N]
//                                        [--bench-calls N] [--url URL]
//
// Starts cft-serve on two free loopback ports as a child process - the
// frame port and, with --ws, the WebSocket one - records its PID,
// drives every check through it, and stops it BY THAT PID. Nothing
// here kills by image name, on a host where other people's processes
// share them.
//
// What it checks, in the order it checks them:
//
//   A  the CRC-32 the frames carry, against Node's zlib.crc32 - an
//      implementation that shares no code with either the C's or
//      remote.mjs's; and the ABI the client puts in every frame,
//      against the module's own cft_abi_version().
//   B  the opening handshake: Sec-WebSocket-Accept recomputed with
//      node:crypto's SHA-1, and the two ways of getting it wrong.
//   C  HELLO over WebSocket and over TCP: the same caps block.
//   D  a replay of a vectors/out subset over WebSocket, each case
//      compared with the local wasm module's answer for the same
//      bytes AND with the golden model's published result; and the
//      same case over TCP, which must agree with the WebSocket one.
//      The three run interleaved and nothing is accumulated, so the
//      whole of vectors/out costs what one set of it costs in memory,
//      and the two connections interleave at the server.
//   D2 the reduction sets' sum and dot cases, which are REDUCE frames
//      rather than RUN ones. sumsq and sumabs are compositions the
//      client makes out of two passes and the scaled products are
//      host operations, so neither crosses and neither is replayed.
//   E  the server's STATS counters after the same work over each
//      transport: equal, because one message carries one frame and
//      the counters count frames.
//   F  fragmentation and ping/pong, driven by a raw client written
//      here over node:net, because a client library will not fragment
//      or ping on request and an untested branch is a claim.
//   G  the refusals: a wrong magic, a corrupted crc, a wrong ABI, a
//      request before HELLO, a text message, an oversize length - and
//      docs/REMOTE.md's two negative controls, a flipped bit of a
//      returned encoding and a frame whose header claims one byte
//      more than it carries.
//   H  the round trip, measured: one element per call, sequential,
//      over each transport.
//   I  the buffer and status-word operations, which libcft's own
//      client never issues (buffers are host memory on a remote
//      handle and the status word lives on the client) but which the
//      protocol serves and a client that is not libcft may want. A
//      path nobody exercises is a path nobody has tested.
//
// Exit status 0 only if every check passed.

import { spawn } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync }
  from "node:fs";
import net from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import zlib from "node:zlib";

import {
  FLAGS_ALL, FLAG_INEXACT, FLAG_INVALID, FLAG_OVERFLOW, loadModule,
  OPS_BY_NAME, Scratch,
} from "./lib.mjs";
import {
  CftRemote, FrameError, KIND_REFUSAL, KIND_RESPONSE, OP, RemoteError,
  ROUND_NAMES, FORMAT_SIZE, HDR_BYTES, STATUS_TEXT, crc32, packFrame,
  unpackFrame,
} from "../wasm/remote.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const EXE = process.platform === "win32" ? ".exe" : "";

// ---------------------------------------------------------------------
// arguments
// ---------------------------------------------------------------------

const args = process.argv.slice(2);
function opt(name, dflt) {
  const i = args.indexOf(name);
  return i >= 0 && i + 1 < args.length ? args[i + 1] : dflt;
}
const SERVE = opt("--serve", join(ROOT, "host", "cft-serve" + EXE));
const VECTORS = opt("--vectors", join(ROOT, "vectors", "out"));
const CASES = Number(opt("--cases", "400"));
const SETS = Number(opt("--sets", "8"));
const BENCH_CALLS = Number(opt("--bench-calls", "300"));
const URL_ONLY = opt("--url", null);      // drive a running server, no child
const WS_URL_ONLY = opt("--ws-url", null);
const VERBOSE = args.includes("--verbose");

let checks = 0, failures = 0;
const failed = [];

function check(ok, what) {
  checks++;
  if (!ok) { failures++; failed.push(what); }
  if (!ok || VERBOSE) console.log((ok ? "  ok   " : "  FAIL ") + what);
}

function section(title) { console.log("\n== " + title); }

const hex = (u8) => [...u8].map((b) => b.toString(16).padStart(2, "0")).join("");
const same = (x, y) => x.length === y.length && x.every((v, i) => v === y[i]);

// ---------------------------------------------------------------------
// the server, as a child process, stopped by PID
// ---------------------------------------------------------------------

class Server {
  static async start() {
    const dir = mkdtempSync(join(tmpdir(), "cft-ws-"));
    const portFile = join(dir, "port"), wsFile = join(dir, "ws-port");
    const cmd = [SERVE, "--port", "0", "--ws", "0",
                 "--port-file", portFile, "--ws-port-file", wsFile];
    console.log("$ " + cmd.join(" ") + "  &");
    const proc = spawn(cmd[0], cmd.slice(1),
                       { stdio: ["ignore", "pipe", "pipe"] });
    const log = [];
    proc.stdout.on("data", (d) => log.push(String(d)));
    proc.stderr.on("data", (d) => log.push(String(d)));
    const deadline = Date.now() + 20000;
    for (;;) {
      if (proc.exitCode !== null)
        throw new Error("cft-serve exited early:\n" + log.join(""));
      if (existsSync(portFile) && existsSync(wsFile)) {
        const p = Number(readFileSync(portFile, "utf8").trim());
        const w = Number(readFileSync(wsFile, "utf8").trim());
        if (p > 0 && w > 0) {
          console.log(`server pid ${proc.pid}, frames on ${p}, ` +
                      `WebSocket on ${w}`);
          const s = new Server();
          s.proc = proc; s.port = p; s.wsPort = w; s.dir = dir; s.log = log;
          return s;
        }
      }
      if (Date.now() > deadline)
        throw new Error("cft-serve did not report its ports in 20 s:\n" +
                        log.join(""));
      await new Promise((r) => setTimeout(r, 50));
    }
  }

  get url() { return `tcp://127.0.0.1:${this.port}`; }
  get wsUrl() { return `ws://127.0.0.1:${this.wsPort}`; }

  async stop() {
    // By PID: kill() signals THIS child and nothing else on the host.
    if (this.proc.exitCode === null) {
      this.proc.kill();
      await new Promise((r) => {
        this.proc.once("exit", r);
        setTimeout(() => { this.proc.kill("SIGKILL"); r(); }, 5000);
      });
    }
    console.log(`server pid ${this.proc.pid} stopped ` +
                `(exit ${this.proc.exitCode})`);
    if (VERBOSE) console.log(this.log.join("").trimEnd());
    rmSync(this.dir, { recursive: true, force: true });
  }
}

// ---------------------------------------------------------------------
// a raw WebSocket client, written here
//
// A client library will not fragment a message or send a ping because
// a test asked it to, and "fragmentation tolerated on receive" and
// "ping/pong" are branches of the server. So this speaks RFC 6455
// itself: the handshake with a random key, client-to-server masking,
// and frames it is told the shape of.
// ---------------------------------------------------------------------

const WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11";

function acceptFor(key) {
  return createHash("sha1").update(key + WS_GUID).digest("base64");
}

class RawWs {
  constructor(sock) { this.sock = sock; this.buf = Buffer.alloc(0); }

  static connect(host, port, { headers = null, raw = null } = {}) {
    return new Promise((resolve_, reject) => {
      const sock = net.createConnection({ host, port });
      sock.setNoDelay(true);
      sock.once("error", reject);
      sock.once("connect", () => {
        const w = new RawWs(sock);
        w.key = randomBytes(16).toString("base64");
        const req = raw !== null ? raw : (headers || [
          `GET / HTTP/1.1`,
          `Host: ${host}:${port}`,
          `Upgrade: websocket`,
          `Connection: Upgrade`,
          `Sec-WebSocket-Key: ${w.key}`,
          `Sec-WebSocket-Version: 13`,
          `Origin: http://127.0.0.1:0`,
        ]).join("\r\n") + "\r\n\r\n";
        sock.write(req);
        w.pending = [];
        sock.on("data", (d) => {
          w.buf = Buffer.concat([w.buf, d]);
          w.drain();
        });
        sock.on("close", () => { w.closed = true; w.drain(); });
        resolve_(w);
      });
    });
  }

  drain() {
    while (this.pending.length && this.pending[0].test())
      this.pending.shift().go();
  }

  /** The HTTP response head, as text. */
  head() {
    return new Promise((resolve_) => {
      const want = {
        test: () => this.closed || this.buf.indexOf("\r\n\r\n") >= 0,
        go: () => {
          const at = this.buf.indexOf("\r\n\r\n");
          if (at < 0) { resolve_(this.buf.toString("latin1")); return; }
          const text = this.buf.subarray(0, at + 4).toString("latin1");
          this.buf = this.buf.subarray(at + 4);
          resolve_(text);
        },
      };
      this.pending.push(want);
      this.drain();
    });
  }

  /** One WebSocket frame from the server (unmasked, unfragmented -
   *  which is what cft-serve sends). */
  frame() {
    const parse = () => {
      if (this.buf.length < 2) return null;
      const b0 = this.buf[0], b1 = this.buf[1];
      if (b1 & 0x80) throw new Error("the server masked a frame");
      let len = b1 & 0x7f, off = 2;
      if (len === 126) {
        if (this.buf.length < 4) return null;
        len = this.buf.readUInt16BE(2); off = 4;
      } else if (len === 127) {
        if (this.buf.length < 10) return null;
        len = Number(this.buf.readBigUInt64BE(2)); off = 10;
      }
      if (this.buf.length < off + len) return null;
      const body = new Uint8Array(len);          // a copy of its own, so the
      body.set(this.buf.subarray(off, off + len));  // DataViews below are flat
      this.buf = this.buf.subarray(off + len);
      return { fin: !!(b0 & 0x80), opcode: b0 & 0x0f, body };
    };
    return new Promise((resolve_, reject) => {
      let out = null;
      const want = {
        test: () => { out = parse(); return out !== null || this.closed; },
        go: () => out !== null ? resolve_(out)
                               : reject(new Error("the server closed")),
      };
      this.pending.push(want);
      this.drain();
    });
  }

  /** One client frame, masked as RFC 6455 5.1 requires. */
  send(opcode, body, fin = true) {
    const mask = randomBytes(4);
    const n = body.length;
    const head = n <= 125 ? Buffer.from([(fin ? 0x80 : 0) | opcode, 0x80 | n])
      : n <= 0xffff
        ? Buffer.concat([Buffer.from([(fin ? 0x80 : 0) | opcode, 0x80 | 126]),
                         (() => { const b = Buffer.alloc(2); b.writeUInt16BE(n); return b; })()])
        : Buffer.concat([Buffer.from([(fin ? 0x80 : 0) | opcode, 0x80 | 127]),
                         (() => { const b = Buffer.alloc(8); b.writeBigUInt64BE(BigInt(n)); return b; })()]);
    const masked = Buffer.from(body);
    for (let i = 0; i < n; i++) masked[i] ^= mask[i & 3];
    this.sock.write(Buffer.concat([head, mask, masked]));
  }

  close() { this.sock.destroy(); }
}

// ---------------------------------------------------------------------
// the local module
// ---------------------------------------------------------------------

/** cftw_open_software takes a cft_device ** and returns a status, as
 *  bindings/node/core.mjs opens one. The scratch holds only the
 *  out-pointer; the device outlives it and is closed by hand. */
function openLocal(M, C) {
  const s = new Scratch(M);
  try {
    const pp = s.alloc(4);
    const st = C.openSoftware(pp);
    if (st !== 0)
      throw new Error(`the wasm module would not open a device: ` +
                      `${C.strerror(st)} ${C.lastError()}`);
    return s.u32(pp);
  } finally { s.free(); }
}

function localRun(M, C, dev, op, fmt, rnd, a, b, c, n) {
  const s = new Scratch(M);
  try {
    const esz = FORMAT_SIZE[fmt];
    const pa = s.put(a), pb = s.put(b), pc = s.put(c);
    const pd = s.alloc(n * esz), pf = s.alloc(4), pbus = s.alloc(4);
    const st = C.run(dev, op, fmt, rnd, pa, pb, pc, pd, n, pf, pbus);
    return { status: st, d: s.get(pd, n * esz), flags: s.u32(pf) };
  } finally { s.free(); }
}

// ---------------------------------------------------------------------
// the cases
// ---------------------------------------------------------------------

const FORMAT_OF_NAME = { fp32: 0, fp64: 1, fp128: 2, fp256: 3 };

function opcodeOf(name) {
  if (name in OPS_BY_NAME) return OPS_BY_NAME[name];
  const m = /^reserved(\d+)$/.exec(name);
  return m ? Number(m[1]) : null;
}

/** Little-endian element bytes from the big-endian hex the vectors
 *  publish. The file writes the encoding the way a person reads it;
 *  the wire carries it the way cft.h stores it. */
function bytesOfHex(h, esz) {
  const t = h.startsWith("0x") ? h.slice(2) : h;
  const out = new Uint8Array(esz);
  for (let i = 0; i < esz; i++)
    out[esz - 1 - i] = parseInt(t.substr(i * 2, 2), 16);
  return out;
}

/** Which of vectors/out's opcode sets to replay: `sets` of them, taken
 *  on a stride over the sorted names so the choice is reproducible.
 *  [] when the vectors have not been generated. */
function chooseSets(dir, sets) {
  if (!existsSync(dir)) return [];
  const wanted = readdirSync(dir)
    .filter((f) => /^fp(32|64|128|256)(-(rne|rtz|rdn|rup|rmm))?\.jsonl$/.test(f))
    .sort();
  const chosen = [];
  const step = Math.max(1, Math.floor(wanted.length / sets));
  for (let i = 0; i < wanted.length && chosen.length < sets; i += step)
    chosen.push(wanted[i]);
  return chosen;
}

/** One set's cases, at most `cases` of them, on a stride so the choice
 *  is the file's shape and not its head. One file at a time, because
 *  the whole of vectors/out is 168 sets of up to 12,000 lines and holding
 *  them all as typed arrays is memory spent for nothing. */
function loadCases(dir, f, cases) {
  const fmt = FORMAT_OF_NAME[f.split(/[-.]/)[0]];
  const esz = FORMAT_SIZE[fmt];
  const lines = readFileSync(join(dir, f), "utf8").split("\n")
    .filter((l) => l.trim());
  const stride = Math.max(1, Math.floor(lines.length / cases));
  const out = [];
  for (let i = 0; i < lines.length; i += stride) {
    const j = JSON.parse(lines[i]);
    const op = opcodeOf(j.op);
    if (op === null) continue;
    out.push({
      set: f, line: i + 1, name: j.op, op, fmt,
      rnd: ROUND_NAMES.indexOf(j.rnd),
      a: bytesOfHex(j.a, esz), b: bytesOfHex(j.b, esz),
      c: bytesOfHex(j.c, esz), d: bytesOfHex(j.d, esz),
      flags: j.flags,
    });
  }
  return out;
}

/** The reduction sets' sum and dot cases: the two reductions that are
 *  a DEVICE operation, so each is one REDUCE frame. sumsq and sumabs
 *  are compositions the client makes out of two passes
 *  (docs/REMOTE.md), and the scaled products are host operations that
 *  never cross, so neither is replayed here. */
function loadReduceCases(dir, f, cases) {
  const fmt = FORMAT_OF_NAME[f.split(/[-.]/)[0]];
  const esz = FORMAT_SIZE[fmt];
  const lines = readFileSync(join(dir, f), "utf8").split("\n")
    .filter((l) => l.trim());
  const out = [];
  for (let i = 0; i < lines.length && out.length < cases; i++) {
    const j = JSON.parse(lines[i]);
    if (j.fn !== "sum" && j.fn !== "dot") continue;
    const vec = (list) => {
      const u = new Uint8Array(list.length * esz);
      list.forEach((h, k) => u.set(bytesOfHex(h, esz), k * esz));
      return u;
    };
    out.push({
      set: f, line: i + 1, name: j.fn, op: OPS_BY_NAME[j.fn], fmt,
      rnd: ROUND_NAMES.indexOf(j.rnd), n: j.n,
      a: vec(j.a), b: j.b ? vec(j.b) : null,
      d: bytesOfHex(j.d, esz), flags: j.flags,
    });
  }
  return out;
}

/** No vectors/out: inputs from an LCG instead, so the replay still
 *  compares the server with the local module bit for bit. There is no
 *  golden answer for these, and the report says so. */
function lcgCases(n) {
  let s = 0x9E3779B97F4A7C15n;
  const mask = (1n << 64n) - 1n;
  const byte = () => {
    s = (s * 6364136223846793005n + 1442695040888963407n) & mask;
    return Number((s ^ (s >> 29n)) >> 24n) & 0xff;
  };
  const out = [];
  const ops = ["fma", "add", "sub", "mul", "min", "max", "copysign", "cmplt"];
  for (let i = 0; i < n; i++) {
    const fmt = i & 3, esz = FORMAT_SIZE[fmt];
    const fill = () => Uint8Array.from({ length: esz }, byte);
    out.push({
      set: "(lcg)", line: i, name: ops[i % ops.length],
      op: OPS_BY_NAME[ops[i % ops.length]], fmt, rnd: i % 5,
      a: fill(), b: fill(), c: fill(), d: null, flags: null,
    });
  }
  return out;
}

// ---------------------------------------------------------------------
// the checks
// ---------------------------------------------------------------------

/** One pass over a batch of cases: each one run on the server over
 *  WebSocket, on the server over TCP, and in the local wasm module,
 *  and the three compared as it goes. Nothing is accumulated, so the
 *  whole of vectors/out is as cheap in memory as one set of it - and
 *  the two connections interleave at the server, which is the same
 *  multiplexing device-test's two handles exercise. */
async function replayBatch(M, C, localDev, wsDev, tcpDev, cases, golden, tally) {
  for (const k of cases) {
    const w = await wsDev.run(k.op, k.fmt, k.rnd, { a: k.a, b: k.b, c: k.c }, 1);
    const t = await tcpDev.run(k.op, k.fmt, k.rnd, { a: k.a, b: k.b, c: k.c }, 1);
    const loc = localRun(M, C, localDev, k.op, k.fmt, k.rnd, k.a, k.b, k.c, 1);
    tally.n++;
    const note = (what) => {
      if (!tally.firstBad)
        tally.firstBad = `${k.set}:${k.line} ${k.name} ` +
          `${ROUND_NAMES[k.rnd]}: ${what}`;
    };
    if (loc.status !== 0) {
      tally.badLocal++;
      note(`the local module refused the call with status ${loc.status}`);
    } else if (!same(w.d, loc.d)) {
      tally.badLocal++;
      note(`local ${hex(loc.d)}, websocket ${hex(w.d)}`);
    }
    if (golden) {
      if (!same(w.d, k.d)) {
        tally.badGolden++;
        note(`expected ${hex(k.d)}, websocket ${hex(w.d)}`);
      }
      if ((w.flags | 0) !== (k.flags | 0)) {
        tally.badFlags++;
        note(`flags ${k.flags} expected, ${w.flags} raised`);
      }
    }
    if (!same(w.d, t.d) || w.flags !== t.flags) {
      tally.badCross++;
      note(`websocket ${hex(w.d)}/${w.flags}, tcp ${hex(t.d)}/${t.flags}`);
    }
  }
}

async function main() {
  console.log("cft-fp256: the WebSocket transport, held to the contract " +
              "(docs/REMOTE.md)");

  const { M, C } = await loadModule();
  const abi = C.abiVersion() >>> 0;
  const localDev = openLocal(M, C);

  let server = null, url = URL_ONLY, wsUrl = WS_URL_ONLY;
  if (!url || !wsUrl) {
    if (!existsSync(SERVE))
      throw new Error(`${SERVE} is not built (make -C host cft-serve)`);
    server = await Server.start();
    url = server.url;
    wsUrl = server.wsUrl;
  }

  try {
    // ---- A. the numbers the frames carry ---------------------------
    section("A. the CRC-32 and the ABI");
    const nine = new TextEncoder().encode("123456789");
    check(crc32(0, nine) === 0xCBF43926,
          `CRC-32 check value ${crc32(0, nine).toString(16)} is the ` +
          `standard 0xcbf43926`);
    const stream = new Uint8Array(4096);
    for (let i = 0; i < stream.length; i++) stream[i] = (i * 37 + 11) & 0xff;
    const mine = crc32(0, stream) >>> 0;
    const theirs = zlib.crc32 ? zlib.crc32(Buffer.from(stream)) >>> 0 : null;
    check(theirs === null || mine === theirs,
          `CRC-32 of a 4096-byte stream ${mine.toString(16)} == ` +
          `zlib's ${theirs === null ? "(zlib.crc32 not in this Node)"
                                    : theirs.toString(16)}`);
    check(abi >>> 16 === 0 && (abi & 0xffff) > 0,
          `the module reports libcft ABI ${abi >>> 16}.${abi & 0xffff}, ` +
          `which is what every frame will carry`);
    {
      // remote.mjs transcribes cft_strerror's sentences for a client
      // that has no module. Pin the transcription to the library: every
      // entry as the module words it, and nothing missing off the end.
      const wrong = STATUS_TEXT
        .map((t, i) => (t === C.strerror(i) ? null : `${i}: "${t}" vs ` +
                        `"${C.strerror(i)}"`))
        .filter(Boolean);
      check(wrong.length === 0 &&
            C.strerror(STATUS_TEXT.length) === "unknown status",
            `remote.mjs's ${STATUS_TEXT.length} cft_status sentences are the ` +
            `module's own, and ${STATUS_TEXT.length} is past the last one` +
            (wrong.length ? " - " + wrong.join("; ") : ""));
    }

    // ---- B. the opening handshake -----------------------------------
    section("B. the RFC 6455 handshake");
    {
      const port = Number(wsUrl.split(":").pop());
      const w = await RawWs.connect("127.0.0.1", port);
      const head = await w.head();
      const line = head.split("\r\n")[0];
      const acc = /Sec-WebSocket-Accept:\s*(\S+)/i.exec(head);
      check(line === "HTTP/1.1 101 Switching Protocols",
            `the server answers "${line}"`);
      check(!!acc && acc[1] === acceptFor(w.key),
            `Sec-WebSocket-Accept ${acc ? acc[1] : "(absent)"} == ` +
            `base64(SHA-1(key + GUID)) computed with node:crypto`);
      check(/Upgrade:\s*websocket/i.test(head) &&
            /Connection:\s*Upgrade/i.test(head),
            "the response carries Upgrade: websocket and Connection: Upgrade");
      w.close();
    }
    {
      const port = Number(wsUrl.split(":").pop());
      const w = await RawWs.connect("127.0.0.1", port,
        { headers: ["GET / HTTP/1.1", "Host: x", "Accept: */*"] });
      const head = await w.head();
      check(/^HTTP\/1\.1 400 /.test(head),
            `a GET without Upgrade is refused: "${head.split("\r\n")[0]}"`);
      w.close();
    }
    {
      const port = Number(wsUrl.split(":").pop());
      // Terminated, so the handshake reader stops rather than waiting
      // out its stall timeout for a request head that never ends.
      const w = await RawWs.connect("127.0.0.1", port,
                                    { raw: "CFTR\x01\x00\r\n\r\n" });
      const head = await w.head();
      check(/^HTTP\/1\.1 400 /.test(head) || head === "",
            `a binary frame on the WebSocket port is refused: ` +
            `"${head.split("\r\n")[0] || "(closed)"}"`);
      w.close();
    }

    // ---- C. HELLO over both -----------------------------------------
    section("C. HELLO over each transport");
    const wsDev = await CftRemote.connect(wsUrl, { abi });
    const tcpDev = await CftRemote.connect(url, { abi });
    const capsEqual = ["formatMask", "opGroups", "tiles", "deviceVersion",
                       "flagsReadable", "abi", "backend",
                       "maxDeposits", "maxInsns", "maxConsts", "seqFeatures"]
      .every((k) => wsDev.caps[k] === tcpDev.caps[k]);
    check(capsEqual,
          `the caps block is the same over both: backend ` +
          `"${wsDev.caps.backend}", formats 0x` +
          `${wsDev.caps.formatMask.toString(16)}, ABI ` +
          `${wsDev.caps.abi >>> 16}.${wsDev.caps.abi & 0xffff}`);
    check(wsDev.caps.abi === abi,
          "the server's libcft is the same ABI as this module's");

    // ---- D. the replay ----------------------------------------------
    section("D. the replay, WebSocket against local and against the model");
    const chosen = chooseSets(VECTORS, SETS);
    const golden = chosen.length > 0;
    const tally = { n: 0, badLocal: 0, badGolden: 0, badFlags: 0,
                    badCross: 0, firstBad: null };
    const t0 = process.hrtime.bigint();
    let firstCase = null;
    if (golden) {
      console.log(`  ${chosen.length} sets of ${VECTORS}, up to ${CASES} ` +
                  `cases each`);
      for (const f of chosen) {
        const cases = loadCases(VECTORS, f, CASES);
        if (!firstCase) firstCase = cases[0];
        await replayBatch(M, C, localDev, wsDev, tcpDev, cases, true, tally);
        if (VERBOSE)
          console.log(`  ${f.padEnd(18)} ${String(cases.length).padStart(6)} ` +
                      `cases, ${tally.n} so far`);
      }
    } else {
      console.log(`  vectors/out is not generated (${VECTORS}); the golden ` +
                  `comparison is NOT RUN. Falling back to LCG inputs, which ` +
                  `still compare the server with the local module and the ` +
                  `two transports with each other.`);
      const cases = lcgCases(CASES);
      firstCase = cases[0];
      await replayBatch(M, C, localDev, wsDev, tcpDev, cases, false, tally);
    }
    const secs = Number(process.hrtime.bigint() - t0) / 1e9;
    console.log(`  ${tally.n} cases in ${secs.toFixed(1)} s ` +
                `(${(tally.n / secs).toFixed(0)} cases/s, one WebSocket and ` +
                `one TCP round trip each)`);
    const cases = [firstCase];
    check(tally.badLocal === 0,
          `${tally.n} cases: every WebSocket result equals the local wasm ` +
          `module's` +
          (tally.firstBad ? ` (first difference: ${tally.firstBad})` : ""));
    if (golden) {
      check(tally.badGolden === 0,
            `${tally.n} cases: every WebSocket result equals the golden ` +
            `model's published d`);
      check(tally.badFlags === 0,
            `${tally.n} cases: every WebSocket flag word equals the golden ` +
            `model's published one`);
    }
    check(tally.badCross === 0,
          `${tally.n} cases: WebSocket and TCP return the same bytes and ` +
          `the same flags`);

    // ---- D2. the reductions ------------------------------------------
    section("D2. the reductions (REDUCE frames) over WebSocket");
    let redN = 0, redBadGolden = 0, redBadCross = 0, redFirst = null;
    if (golden) {
      const redFiles = readdirSync(VECTORS)
        .filter((f) =>
          /^fp(32|64|128|256)-reduce(-(rne|rtz|rdn|rup|rmm))?\.jsonl$/.test(f))
        .sort();
      let redSets = 0;
      for (const f of redFiles) {
        const rc = loadReduceCases(VECTORS, f, CASES);
        if (!rc.length) continue;
        redSets++;
        for (const k of rc) {
          const w = await wsDev.reduce(k.op, k.fmt, k.rnd,
                                       { a: k.a, b: k.b }, k.n);
          const t = await tcpDev.reduce(k.op, k.fmt, k.rnd,
                                        { a: k.a, b: k.b }, k.n);
          redN++;
          if (!same(w.d, k.d)) {
            redBadGolden++;
            redFirst = redFirst || `${f}:${k.line} ${k.name} n=${k.n}: ` +
              `expected ${hex(k.d)}, got ${hex(w.d)}`;
          }
          if (!same(w.d, t.d) || w.flags !== t.flags) redBadCross++;
        }
      }
      console.log(`  ${redN} sum/dot cases from ${redSets} reduction sets`);
      check(redBadGolden === 0,
            `${redN} REDUCE cases over WebSocket: every result equals the ` +
            `golden model's published one` +
            (redFirst ? ` (first difference: ${redFirst})` : ""));
      check(redBadCross === 0,
            `${redN} REDUCE cases: WebSocket and TCP agree on bytes and flags`);
    } else {
      console.log("  vectors/out is not generated; NOT RUN.");
    }

    // ---- E. the counters ---------------------------------------------
    section("E. the server's STATS counters, one transport against the other");
    const wsStats = await wsDev.stats();
    const tcpStats = await tcpDev.stats();
    const opsEqual = JSON.stringify(
      Object.entries(wsStats.byOp).map(([k, v]) => [k, String(v)])) ===
      JSON.stringify(
        Object.entries(tcpStats.byOp).map(([k, v]) => [k, String(v)]));
    check(wsStats.requests === tcpStats.requests && opsEqual,
          `${wsStats.requests} requests each, and the same count per opcode ` +
          `(RUN x${wsStats.byOp[OP.RUN]})`);
    check(Number(wsStats.byOp[OP.RUN] || 0n) === tally.n,
          `and the RUN count is the ${tally.n} cases replayed, so the ` +
          `client's chunking issued one frame per call on both`);
    check(wsStats.bytesIn === tcpStats.bytesIn &&
          wsStats.bytesOut === tcpStats.bytesOut,
          `${wsStats.bytesIn} bytes in and ${wsStats.bytesOut} out each - ` +
          `the counters count PROTOCOL bytes, so the envelope does not ` +
          `move them`);

    // ---- F. fragmentation, ping and pong -----------------------------
    section("F. fragmentation on receive, ping and pong");
    {
      const port = Number(wsUrl.split(":").pop());
      const w = await RawWs.connect("127.0.0.1", port);
      await w.head();
      const hello = packFrame({ kind: 0, abi, id: 1, op: OP.HELLO, status: 0 },
                              null);
      // In three pieces: binary/!fin, continuation/!fin, continuation/fin.
      w.send(0x2, Buffer.from(hello.subarray(0, 7)), false);
      w.send(0x0, Buffer.from(hello.subarray(7, 20)), false);
      w.send(0x0, Buffer.from(hello.subarray(20)), true);
      const f = await w.frame();
      const { h, payload } = unpackFrame(f.body, abi);
      check(f.opcode === 0x2 && h.kind === KIND_RESPONSE && h.status === 0 &&
            payload.length >= 56,
            `a HELLO split across three WebSocket fragments is answered ` +
            `with a ${payload.length}-byte caps block`);

      const ball = Buffer.from("cft-fp256 ping");
      w.send(0x9, ball);
      const pong = await w.frame();
      check(pong.opcode === 0xA && Buffer.from(pong.body).equals(ball),
            `a ping is answered with a pong carrying the same ` +
            `${ball.length} bytes`);

      // and the connection still works afterwards
      const again = packFrame({ kind: 0, abi, id: 2, op: OP.STATS, status: 0 },
                              null);
      w.send(0x2, Buffer.from(again));
      const f2 = await w.frame();
      const r2 = unpackFrame(f2.body, abi);
      check(r2.h.kind === KIND_RESPONSE && r2.h.status === 0 && r2.h.id === 2,
            "the connection serves a request after the ping");
      w.send(0x8, Buffer.from([0x03, 0xE8]));           // close, 1000
      const bye = await w.frame().catch(() => null);
      check(bye === null || bye.opcode === 0x8,
            "a close frame is answered with a close frame");
      w.close();
    }

    // ---- G. the refusals ---------------------------------------------
    section("G. the refusals, over WebSocket");

    async function refusal(name, build, expect = null) {
      const port = Number(wsUrl.split(":").pop());
      const w = await RawWs.connect("127.0.0.1", port);
      await w.head();
      w.send(0x2, Buffer.from(build()));
      let text = "", kind = null, status = null;
      try {
        const f = await w.frame();
        const dv = new DataView(f.body.buffer, f.body.byteOffset,
                                f.body.byteLength);
        kind = dv.getUint16(6, true);
        status = dv.getUint16(18, true);
        text = new TextDecoder().decode(f.body.subarray(HDR_BYTES))
          .replace(/\0+$/, "");
      } catch { /* the server may simply close */ }
      w.close();
      check(kind === KIND_REFUSAL && (expect === null || text.includes(expect)),
            `${name}: refused with status ${status} - "${text.slice(0, 90)}"`);
    }

    const goodHello = () => packFrame({ kind: 0, abi, id: 1, op: OP.HELLO,
                                        status: 0 }, null);
    await refusal("a wrong magic", () => {
      const f = goodHello(); f[0] = 0x47; return f;         /* 'G' */
    }, "not a cft frame");
    await refusal("a corrupted crc", () => {
      const f = packFrame({ kind: 0, abi, id: 1, op: OP.PROG_LOAD, status: 0 },
                          new Uint8Array([1, 2, 3, 4]));
      f[HDR_BYTES] ^= 0x01;                 /* after the crc was taken */
      return f;
    }, "crc");
    await refusal("a wrong ABI", () => packFrame(
      { kind: 0, abi: abi ^ 0x10000, id: 1, op: OP.HELLO, status: 0 }, null),
      "ABI mismatch");
    await refusal("a request before HELLO", () => packFrame(
      { kind: 0, abi, id: 1, op: OP.STATS, status: 0 }, null), "before HELLO");
    await refusal("a length past the cap", () => {
      const f = goodHello();
      new DataView(f.buffer).setUint32(20, 0x7fffffff, true);
      return f;
    });
    {
      // A text message where a binary frame was due.
      const port = Number(wsUrl.split(":").pop());
      const w = await RawWs.connect("127.0.0.1", port);
      await w.head();
      w.send(0x1, Buffer.from("hello"));
      let kind = null, text = "";
      try {
        const f = await w.frame();
        kind = new DataView(f.body.buffer, f.body.byteOffset,
                            f.body.byteLength).getUint16(6, true);
        text = new TextDecoder().decode(f.body.subarray(HDR_BYTES))
          .replace(/\0+$/, "");
      } catch { /* may close */ }
      w.close();
      check(kind === KIND_REFUSAL && /text message/.test(text),
            `a text message is refused: "${text.slice(0, 80)}"`);
    }

    section("G2. docs/REMOTE.md's two negative controls, over WebSocket");
    {
      // (1) one bit of one returned encoding, flipped in the CLIENT
      // after the crc has passed. Nothing about the transport notices.
      const sab = await CftRemote.connect(wsUrl, { abi, sabotage: "bit" });
      const k = cases[0];
      const r = await sab.run(k.op, k.fmt, k.rnd, { a: k.a, b: k.b, c: k.c }, 1);
      const loc = localRun(M, C, localDev, k.op, k.fmt, k.rnd, k.a, k.b, k.c, 1);
      check(!same(r.d, loc.d),
            `a flipped bit of a returned encoding is caught by the ` +
            `comparison and by nothing else: local ${hex(loc.d)}, ` +
            `sabotaged ${hex(r.d)}`);
      await sab.close();
    }
    {
      // (2) a header that claims one byte more than the message holds.
      const sab = await CftRemote.connect(wsUrl, { abi, sabotage: "length" });
      const k = cases[0];
      let err = null;
      try {
        await sab.run(k.op, k.fmt, k.rnd, { a: k.a, b: k.b, c: k.c }, 1);
      } catch (e) { err = e; }
      check(err instanceof RemoteError && err.refusal &&
            /truncated frame/.test(err.message),
            `a RUN whose header claims one byte more than it carries is ` +
            `refused: "${err ? err.message.slice(0, 110) : "(no error)"}"`);
      let after = null;
      try {
        await sab.run(k.op, k.fmt, k.rnd, { a: k.a, b: k.b, c: k.c }, 1);
      } catch (e) { after = e; }
      check(after instanceof FrameError && /poisoned/.test(after.message),
            "and the handle is poisoned: every later call refuses until it " +
            "is closed and opened again");
      await sab.close();
    }

    // ---- H. the round trip -------------------------------------------
    //
    // Two shapes, and the same two docs/REMOTE.md measured for the C
    // client: one fp64 element per call, which is all socket, and 4,096
    // of them, which is all arithmetic. The absolute numbers are a
    // JavaScript client's - a promise and an event-loop turn per call
    // where the C client has a blocking recv - so what is comparable
    // here is TCP against WebSocket from the SAME client, which is the
    // cost of the envelope and of nothing else.
    section("H. the round trip, TCP against WebSocket, same client");
    const benchOp = OPS_BY_NAME.fma, benchFmt = 1;      // fp64 fma, rne
    const one = (v) => {
      const u = new Uint8Array(8);
      new DataView(u.buffer).setFloat64(0, v, true);
      return u;
    };
    const bench = async (dev, label, n, calls) => {
      const rep = (u) => {
        const out = new Uint8Array(n * 8);
        for (let i = 0; i < n; i++) out.set(u, i * 8);
        return out;
      };
      const a = rep(one(1.5)), b = rep(one(2.25)), c = rep(one(0.125));
      for (let i = 0; i < 10; i++)                      // warm the path
        await dev.run(benchOp, benchFmt, 0, { a, b, c }, n);
      const t0 = process.hrtime.bigint();
      for (let i = 0; i < calls; i++)
        await dev.run(benchOp, benchFmt, 0, { a, b, c }, n);
      const t1 = process.hrtime.bigint();
      const us = Number(t1 - t0) / 1000 / calls;
      console.log(`  ${label.padEnd(10)} ${String(n).padStart(5)} fp64 ` +
                  `element(s)/call  ${us.toFixed(1).padStart(8)} us/call  ` +
                  `${(1e6 / us).toFixed(0).padStart(7)} calls/s  ` +
                  `${(n * 1e6 / us).toFixed(0).padStart(9)} elements/s ` +
                  `(${calls} sequential calls)`);
      return us;
    };
    const usTcp = await bench(tcpDev, "TCP", 1, BENCH_CALLS);
    const usWs = await bench(wsDev, "WebSocket", 1, BENCH_CALLS);
    const batch = Math.max(20, Math.floor(BENCH_CALLS / 10));
    const usTcpB = await bench(tcpDev, "TCP", 4096, batch);
    const usWsB = await bench(wsDev, "WebSocket", 4096, batch);
    console.log(`  the envelope costs ${(usWs - usTcp).toFixed(1)} us on a ` +
                `one-element call and ${(usWsB - usTcpB).toFixed(1)} us on a ` +
                `4,096-element one`);
    check([usTcp, usWs, usTcpB, usWsB].every(Number.isFinite),
          `round trips measured: one element TCP ${usTcp.toFixed(1)} us, ` +
          `WebSocket ${usWs.toFixed(1)} us; 4,096 elements TCP ` +
          `${usTcpB.toFixed(1)} us, WebSocket ${usWsB.toFixed(1)} us`);

    // ---- I. the operations libcft's own client never issues ---------
    section("I. the buffer and status-word operations, over WebSocket");
    {
      const h = await wsDev.bufAlloc(1024);
      check(h > 0, `BUF_ALLOC of 1024 bytes gave handle ${h}`);
      const payload = new Uint8Array(64);
      for (let i = 0; i < payload.length; i++) payload[i] = (i * 7 + 3) & 0xff;
      await wsDev.bufWrite(h, 16, payload);
      const back = await wsDev.bufRead(h, 16, payload.length);
      check(same(back, payload),
            `BUF_WRITE then BUF_READ returns the same ${payload.length} ` +
            `bytes at offset 16`);
      const zeros = await wsDev.bufRead(h, 0, 16);
      check(zeros.every((b) => b === 0),
            "the bytes before the write are still zero, so the offset was " +
            "honoured");
      let past = null;
      try { await wsDev.bufRead(h, 1000, 1000); } catch (e) { past = e; }
      check(past instanceof RemoteError && !past.refusal,
            `a read past the end of the buffer is the operation's own ` +
            `failure and not a refusal: "${past ? past.message.slice(0, 70)
                                                : "(none)"}"`);
      await wsDev.bufFree(h);
      let twice = null;
      try { await wsDev.bufFree(h); } catch (e) { twice = e; }
      check(twice instanceof RemoteError && !twice.refusal,
            "freeing the same handle twice is an invalid argument, and the " +
            "connection carries on");
    }
    {
      // 5.7.4's six, on the SERVER's own status word. libcft's client
      // never issues these - its word is the client handle's - but the
      // server's word is observable state and the protocol serves it.
      // FLAGS_TEST and FLAGS_TEST_SAVED are PREDICATES, 1 or 0, as
      // cft.h says: "the value is 1 or 0 so that it cannot be mistaken
      // for a flag word". FLAGS_SAVE is the word.
      await wsDev.flagsLower(FLAGS_ALL);
      check(await wsDev.flagsTest(FLAGS_ALL) === 0,
            "FLAGS_LOWER of every exception leaves FLAGS_TEST answering 0");
      await wsDev.flagsRaise(FLAG_INVALID | FLAG_INEXACT);
      const saved = await wsDev.flagsSave();
      check(saved === (FLAG_INVALID | FLAG_INEXACT),
            `FLAGS_RAISE of invalid|inexact, then FLAGS_SAVE, gives the ` +
            `word 0x${saved.toString(16)}`);
      check(await wsDev.flagsTest(FLAG_INVALID) === 1 &&
            await wsDev.flagsTest(FLAG_OVERFLOW) === 0,
            "FLAGS_TEST answers 1 for a raised exception and 0 for one that " +
            "is not");
      await wsDev.flagsRestore(0, FLAGS_ALL);
      check(await wsDev.flagsTest(FLAGS_ALL) === 0 &&
            await wsDev.flagsSave() === 0,
            "FLAGS_RESTORE of an empty word under a full mask clears them");
      check(await wsDev.flagsTestSaved(saved, FLAG_INVALID) === 1 &&
            await wsDev.flagsTestSaved(saved, FLAG_OVERFLOW) === 0,
            "FLAGS_TEST_SAVED answers about the saved word and not the " +
            "current one, which is now empty");
    }
    {
      // PROG_LOAD's frame path, with bytes that are not an image: the
      // server's library refuses them, which is the operation's own
      // failure and leaves the connection usable. A VALID sequencer
      // image is not loaded from JavaScript here - see docs/REMOTE.md's
      // "what was not run".
      let bad = null;
      try {
        await wsDev.programLoad(new Uint8Array([0xde, 0xad, 0xbe, 0xef]));
      } catch (e) { bad = e; }
      check(bad instanceof RemoteError && !bad.refusal,
            `PROG_LOAD of four bytes that are not an image is the ` +
            `operation's own failure: "${bad ? bad.message.slice(0, 70)
                                             : "(none)"}"`);
      const after = await wsDev.capsAgain();
      check(after.backend === wsDev.caps.backend,
            "and the connection still answers CAPS afterwards");
    }

    await wsDev.close();
    await tcpDev.close();
  } finally {
    C.close(localDev);
    if (server) await server.stop();
  }

  console.log();
  if (failures) {
    console.log(`remote_test: ${checks} checks, ${failures} FAILED:`);
    for (const f of failed) console.log("  " + f);
    process.exit(1);
  }
  console.log(`remote_test: ${checks} checks, 0 failures`);
}

main().catch((e) => {
  console.error("remote_test: " + (e && e.stack ? e.stack : e));
  process.exit(2);
});
