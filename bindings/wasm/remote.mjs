// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The frame protocol of docs/REMOTE.md, spoken from JavaScript.
//
//     import { CftRemote } from "./remote.mjs";
//     const dev = await CftRemote.connect("ws://127.0.0.1:7755",
//                                         { abi: C.abiVersion() });
//     console.log(dev.caps.backend, dev.caps.tiles);
//     const { d, flags } = await dev.run(OP_FMA, FP64, RNE,
//                                        { a, b, c }, n);
//
// This is the same protocol host/src/backend_remote.c speaks, byte for
// byte: the same 32-byte header, the same little-endian fields, the
// same CRC-32 over the same bytes, the same opcodes and payload
// layouts. Nothing here is a JavaScript dialect of it. A frame this
// file builds and a frame the C client builds for the same call are
// the same bytes, which is the only reason the server can serve both
// without knowing which is which.
//
// TWO TRANSPORTS, ONE FRAME
//
//   ws://host:port    RFC 6455. One WebSocket message carries exactly
//                     one frame. Works in a browser and in Node 22,
//                     which has a global WebSocket.
//   tcp://host:port   the bare stream cft-serve's frame port speaks;
//                     Node only, through node:net, imported lazily so
//                     a browser bundle never sees it. "cft://host:port"
//                     is accepted as a spelling of it, because that is
//                     what cft_open() takes.
//
// The two differ in where a frame's boundary comes from and in
// nothing else, which is what makes them comparable: the same call
// over either leaves the server's STATS counters saying the same
// thing.
//
// THE ABI IS NOT TRANSCRIBED HERE
//
// Every frame carries the SENDER's cft_abi_version(), and the server
// refuses a mismatch rather than warning about one. A number copied
// into this file would be a number that could go stale against the
// module beside it, so there is none: `abi` is a required option and
// its natural value is the module's own C.abiVersion(). A client with
// no module has to say which ABI it is claiming, which is the honest
// position for a client that is not libcft.

export const PROTO_VERSION = 1;
export const HDR_BYTES = 32;
export const MAX_PAYLOAD = 1 << 30;          // CFTR_MAX_PAYLOAD, 1 GiB
export const CHUNK_BYTES = 16 << 20;         // CFTR_CHUNK_BYTES, 16 MiB
export const CAPS_BYTES = 56;                // CFTR_CAPS_BYTES
export const BACKEND_NAME = 32;              // CFTR_BACKEND_NAME
export const DEFAULT_PORT = 7754;            // CFTR_DEFAULT_PORT

export const KIND_REQUEST = 0, KIND_RESPONSE = 1, KIND_REFUSAL = 2;

export const OP = {
  HELLO: 0x0001, CAPS: 0x0002, STATS: 0x0003,
  RUN: 0x0010, REDUCE: 0x0011,
  PROG_LOAD: 0x0020, PROG_RUN: 0x0021, PROG_FREE: 0x0022,
  BUF_ALLOC: 0x0030, BUF_FREE: 0x0031, BUF_WRITE: 0x0032, BUF_READ: 0x0033,
  FLAGS_LOWER: 0x0040, FLAGS_RAISE: 0x0041, FLAGS_TEST: 0x0042,
  FLAGS_SAVE: 0x0043, FLAGS_RESTORE: 0x0044, FLAGS_TEST_SAVED: 0x0045,
  BYE: 0x00FF,
};

/** The opcode's name, for a message. */
export const OP_NAMES = Object.fromEntries(
  Object.entries(OP).map(([k, v]) => [v, k]));

/** cft_status, in cft_strerror's OWN WORDS and in cft_status order, so
 *  that a client with no module still says what the library says. The
 *  server sends its own text in a failed response's payload and that
 *  is what a caller sees; this table is for the frames that carry no
 *  payload to speak for them.
 *
 *  A transcription, and pinned as one: bindings/node/remote_test.mjs
 *  checks every entry against the module's cft_strerror() and checks
 *  that the number after the last one is the library's "unknown
 *  status", so a status added to cft.h fails a gate here rather than
 *  being quietly missing. */
export const STATUS_TEXT = [
  "ok",
  "invalid argument",
  "operation or format not available on this device",
  "no such device",
  "artifact missing, unreadable, or not a tile",
  "memory system fault: the output is not valid",
  "out of memory",
  "timed out",
  "internal error",
];

export const FORMAT_SIZE = [4, 8, 16, 32];   // cft_format_size, fp32..fp256

// ---------------------------------------------------------------------
// CRC-32, as IEEE 802.3 / zlib / PNG define it
//
// Reflected polynomial 0xEDB88320, initial value all ones, final
// complement; check value 0xCBF43926 for the nine ASCII digits
// "123456789". The table is DERIVED from the polynomial here, as it is
// in the C, so the two cannot disagree about a constant neither of
// them typed.
// ---------------------------------------------------------------------

let CRC_TABLE = null;

function crcTable() {
  if (CRC_TABLE) return CRC_TABLE;
  const t = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++)
      c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[i] = c >>> 0;
  }
  CRC_TABLE = t;
  return t;
}

export function crc32(seed, bytes) {
  const t = crcTable();
  let c = (~seed) >>> 0;
  for (let i = 0; i < bytes.length; i++)
    c = (t[(c ^ bytes[i]) & 0xFF] ^ (c >>> 8)) >>> 0;
  return (~c) >>> 0;
}

/** 0 when this implementation gives the standard check value. Called
 *  before the first frame is sent, as the C does. */
export function crc32Selfcheck() {
  const nine = new Uint8Array([0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37,
                               0x38, 0x39]);
  return crc32(0, nine) === 0xCBF43926 ? 0 : -1;
}

// ---------------------------------------------------------------------
// The frame
// ---------------------------------------------------------------------

const MAGIC = new Uint8Array([0x43, 0x46, 0x54, 0x52]);   // 'C' 'F' 'T' 'R'

/** Build one frame: 32-byte header with the CRC filled in, then the
 *  payload. `claimExtra` is the negative control's wrong length - the
 *  header says one byte more than the frame carries. */
export function packFrame(h, payload, claimExtra = 0) {
  const len = payload ? payload.length : 0;
  if (len > MAX_PAYLOAD) throw new Error(`payload of ${len} bytes exceeds the cap`);
  const out = new Uint8Array(HDR_BYTES + len);
  const dv = new DataView(out.buffer);
  out.set(MAGIC, 0);
  dv.setUint16(4, PROTO_VERSION, true);
  dv.setUint16(6, h.kind, true);
  dv.setUint32(8, h.abi, true);
  dv.setUint32(12, h.id, true);
  dv.setUint16(16, h.op, true);
  dv.setUint16(18, h.status | 0, true);
  dv.setUint32(20, len + claimExtra, true);
  dv.setUint32(24, 0, true);                 // crc, filled below
  dv.setUint32(28, 0, true);                 // reserved
  if (len) out.set(payload, HDR_BYTES);
  dv.setUint32(24, crc32(0, out), true);
  return out;
}

/** The checks cftr_recv_frame makes, over a frame that is already
 *  whole: magic, protocol version, the reserved word, the sender's
 *  ABI, the length cap, the CRC. Throws a FrameError on any of them -
 *  which poisons the handle, as it does in the C client, because the
 *  stream past a frame that failed its checks is not to be trusted. */
export function unpackFrame(m, myAbi) {
  if (m.length < HDR_BYTES)
    throw new FrameError(`a message of ${m.length} bytes cannot hold a ` +
                         `${HDR_BYTES}-byte frame header`);
  for (let i = 0; i < 4; i++)
    if (m[i] !== MAGIC[i])
      throw new FrameError(
        `not a cft frame: magic ${[...m.slice(0, 4)]
          .map((b) => b.toString(16).padStart(2, "0")).join(" ")}, ` +
        `expected 'C' 'F' 'T' 'R'`);
  const dv = new DataView(m.buffer, m.byteOffset, m.byteLength);
  const h = {
    proto: dv.getUint16(4, true),
    kind: dv.getUint16(6, true),
    abi: dv.getUint32(8, true),
    id: dv.getUint32(12, true),
    op: dv.getUint16(16, true),
    status: dv.getUint16(18, true),
    length: dv.getUint32(20, true),
  };
  const wantCrc = dv.getUint32(24, true);
  if (h.proto !== PROTO_VERSION)
    throw new FrameError(`protocol version ${h.proto}, this client speaks ` +
                         `${PROTO_VERSION}`);
  if (dv.getUint32(28, true) !== 0)
    throw new FrameError("reserved header word is not zero");
  if (h.abi !== myAbi)
    throw new FrameError(
      `ABI mismatch: the other end is libcft ${h.abi >>> 16}.` +
      `${h.abi & 0xFFFF}, this end is ${myAbi >>> 16}.${myAbi & 0xFFFF} - ` +
      `the two libraries may not agree on which operations exist, so this ` +
      `is refused rather than warned`);
  if (h.length > MAX_PAYLOAD)
    throw new FrameError(`frame length ${h.length} exceeds the ` +
                         `${MAX_PAYLOAD}-byte cap`);
  if (m.length !== HDR_BYTES + h.length)
    throw new FrameError(`truncated frame: the header claims ${h.length} ` +
                         `payload bytes and the message carries ` +
                         `${m.length - HDR_BYTES}`);
  const zeroed = new Uint8Array(m.length);
  zeroed.set(m);
  new DataView(zeroed.buffer).setUint32(24, 0, true);
  const crc = crc32(0, zeroed);
  if (crc !== wantCrc)
    throw new FrameError(
      `frame crc ${crc.toString(16).padStart(8, "0")} does not match the ` +
      `${wantCrc.toString(16).padStart(8, "0")} it carries: a corrupted ` +
      `frame, refused`);
  return { h, payload: m.subarray(HDR_BYTES) };
}

/** A transport or framing fault. Poisons the handle. */
export class FrameError extends Error {
  constructor(msg) { super(msg); this.name = "FrameError"; }
}

/** The server refused the frame, or answered the operation with a
 *  status. `status` is the cft_status; `refusal` says which of the two
 *  it was, because a refusal also ends the connection. */
export class RemoteError extends Error {
  constructor(msg, status, refusal) {
    super(msg);
    this.name = "RemoteError";
    this.status = status;
    this.refusal = !!refusal;
  }
}

// ---------------------------------------------------------------------
// Transports
//
// Two shapes, and the difference between them is the whole difference
// between the two ports:
//
//   kind "message"  readMessage() gives back exactly what one send
//                   put on the wire - the frame's boundary came with
//                   it (WebSocket).
//   kind "stream"   read(n) gives back n bytes and the reader has to
//                   know where the frame ends (TCP).
// ---------------------------------------------------------------------

class WebSocketTransport {
  constructor(sock) {
    this.kind = "message";
    this.sock = sock;
    this.queue = [];
    this.waiters = [];
    this.closed = null;
    sock.binaryType = "arraybuffer";
    sock.addEventListener("message", (ev) => {
      const data = ev.data;
      const push = (u8) => {
        if (this.waiters.length) this.waiters.shift().resolve(u8);
        else this.queue.push(u8);
      };
      if (typeof data === "string")
        this.fail(new FrameError("the server sent a text message where a " +
                                 "binary frame was due"));
      else if (data instanceof ArrayBuffer) push(new Uint8Array(data));
      else if (ArrayBuffer.isView(data))
        push(new Uint8Array(data.buffer, data.byteOffset, data.byteLength));
      else if (data && typeof data.arrayBuffer === "function")
        data.arrayBuffer().then((b) => push(new Uint8Array(b)));
    });
    sock.addEventListener("close", (ev) => {
      this.fail(new FrameError(
        `the server closed the WebSocket (code ${ev.code}` +
        `${ev.reason ? ", " + ev.reason : ""})`));
    });
    sock.addEventListener("error", () => {
      this.fail(new FrameError("the WebSocket failed"));
    });
  }

  fail(err) {
    this.closed = this.closed || err;
    while (this.waiters.length) this.waiters.shift().reject(err);
  }

  static open(url, timeoutMs) {
    return new Promise((resolve, reject) => {
      let sock;
      try {
        sock = new WebSocket(url);
      } catch (e) { reject(e); return; }
      const timer = setTimeout(() => {
        try { sock.close(); } catch { /* already gone */ }
        reject(new Error(`connecting to ${url}: no handshake in ${timeoutMs} ms`));
      }, timeoutMs);
      sock.addEventListener("open", () => {
        clearTimeout(timer);
        resolve(new WebSocketTransport(sock));
      }, { once: true });
      sock.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error(`connecting to ${url}: the WebSocket failed`));
      }, { once: true });
    });
  }

  send(bytes) { this.sock.send(bytes); }

  readMessage() {
    if (this.queue.length) return Promise.resolve(this.queue.shift());
    if (this.closed) return Promise.reject(this.closed);
    return new Promise((resolve, reject) =>
      this.waiters.push({ resolve, reject }));
  }

  close() { try { this.sock.close(1000); } catch { /* already gone */ } }
}

class TcpTransport {
  constructor(sock) {
    this.kind = "stream";
    this.sock = sock;
    this.buf = new Uint8Array(0);
    this.waiter = null;
    this.closed = null;
    sock.on("data", (chunk) => {
      const merged = new Uint8Array(this.buf.length + chunk.length);
      merged.set(this.buf, 0);
      merged.set(chunk, this.buf.length);
      this.buf = merged;
      this.pump();
    });
    sock.on("close", () => this.fail(new FrameError("the server closed the connection")));
    sock.on("error", (e) => this.fail(new FrameError(`socket: ${e.message}`)));
  }

  fail(err) {
    this.closed = this.closed || err;
    if (this.waiter) { const w = this.waiter; this.waiter = null; w.reject(err); }
  }

  pump() {
    if (!this.waiter || this.buf.length < this.waiter.n) return;
    const w = this.waiter;
    this.waiter = null;
    const out = this.buf.slice(0, w.n);
    this.buf = this.buf.slice(w.n);
    w.resolve(out);
  }

  static async open(host, port, timeoutMs) {
    const net = await import("node:net");
    return new Promise((resolve, reject) => {
      const sock = net.createConnection({ host, port });
      sock.setNoDelay(true);
      const timer = setTimeout(() => {
        sock.destroy();
        reject(new Error(`connecting to tcp://${host}:${port}: no answer in ` +
                         `${timeoutMs} ms`));
      }, timeoutMs);
      sock.once("connect", () => { clearTimeout(timer); resolve(new TcpTransport(sock)); });
      sock.once("error", (e) => {
        clearTimeout(timer);
        reject(new Error(`connecting to tcp://${host}:${port}: ${e.message}`));
      });
    });
  }

  send(bytes) { this.sock.write(bytes); }

  read(n) {
    if (n === 0) return Promise.resolve(new Uint8Array(0));
    if (this.buf.length >= n) {
      const out = this.buf.slice(0, n);
      this.buf = this.buf.slice(n);
      return Promise.resolve(out);
    }
    if (this.closed) return Promise.reject(this.closed);
    return new Promise((resolve, reject) => {
      this.waiter = { n, resolve, reject };
      this.pump();
    });
  }

  close() { this.sock.destroy(); }
}

// ---------------------------------------------------------------------
// The handle
// ---------------------------------------------------------------------

function u32le(v) {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setUint32(0, v >>> 0, true);
  return b;
}

/** How long to wait for a response, by the same rule
 *  src/backend_remote.c's timeout_ms() uses: CFT_TIMEOUT_MS from the
 *  environment when it is set and sane, else twenty minutes, and
 *  twenty minutes is also the cap. Deliberately not the XRT backend's
 *  sixty-second default: a remote server may be a software backend,
 *  and a program of ten million steps over four thousand lanes is a
 *  legitimate minute of its time. */
function responseTimeout(explicit) {
  const CAP = 20 * 60 * 1000;
  let ms = CAP;
  if (typeof explicit === "number" && explicit > 0) ms = explicit;
  else if (typeof process !== "undefined" && process.env &&
           process.env.CFT_TIMEOUT_MS) {
    const v = Number(process.env.CFT_TIMEOUT_MS);
    if (Number.isFinite(v) && v > 0) ms = v;
  }
  return ms > CAP || !(ms > 0) ? CAP : ms;
}

function concat(parts) {
  let n = 0;
  for (const p of parts) n += p.length;
  const out = new Uint8Array(n);
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

export class CftRemote {
  constructor(transport, abi, opts) {
    this.t = transport;
    this.abi = abi >>> 0;
    this.nextId = 0;
    this.poisoned = null;
    this.caps = null;
    this.url = opts.url;
    this.timeoutMs = responseTimeout(opts.timeoutMs);
    // The two sabotages of docs/REMOTE.md's negative control, on this
    // client, so that the same demonstration can be made over this
    // transport: "bit" flips the low bit of the first byte of every
    // RUN chunk's result AFTER the crc has passed; "length" makes
    // every RUN request's header claim one byte more than its payload
    // holds. Neither is a transport fault, which is the point.
    this.sabotage = opts.sabotage || null;
  }

  /** Connect and say HELLO. `url` is ws://, wss://, tcp:// or cft://.
   *  `abi` is this client's cft_abi_version() and is required - see
   *  the note at the top of this file. */
  static async connect(url, opts = {}) {
    const abi = opts.abi;
    if (typeof abi !== "number" || !Number.isInteger(abi) || abi < 0)
      throw new Error(
        "CftRemote.connect needs { abi }: every frame carries the sender's " +
        "cft_abi_version() and the server refuses a mismatch. Pass the " +
        "module's own C.abiVersion(), or the value your client claims.");
    if (crc32Selfcheck())
      throw new Error("the CRC-32 implementation failed its check value; " +
                      "refusing to speak a protocol it cannot checksum");
    let t;
    if (/^wss?:\/\//.test(url)) {
      t = await WebSocketTransport.open(url, opts.connectTimeoutMs || 10000);
    } else if (/^(tcp|cft):\/\//.test(url)) {
      const rest = url.replace(/^(tcp|cft):\/\//, "");
      const at = rest.lastIndexOf(":");
      if (at < 0) throw new Error(`"${url}" is not of the form tcp://host:port`);
      t = await TcpTransport.open(rest.slice(0, at),
                                  Number(rest.slice(at + 1)) || DEFAULT_PORT,
                                  opts.connectTimeoutMs || 10000);
    } else {
      throw new Error(`"${url}": expected ws://, wss://, tcp:// or cft://`);
    }
    const dev = new CftRemote(t, abi, { ...opts, url });
    try {
      dev.caps = parseCaps(await dev.request(OP.HELLO));
    } catch (e) {
      t.close();
      throw e;
    }
    return dev;
  }

  poison(err) {
    this.poisoned = this.poisoned || err;
    try { this.t.close(); } catch { /* already gone */ }
    return this.poisoned;
  }

  /** One request, one response. Returns the response payload; throws
   *  RemoteError when the operation failed or the frame was refused,
   *  FrameError (and poisons the handle) on anything else. */
  async request(op, payload = null) {
    if (this.poisoned)
      throw new FrameError(
        `this remote handle was poisoned by an earlier transport fault; ` +
        `close it and open it again (${this.url}): ${this.poisoned.message}`);
    const id = ++this.nextId;
    const claimExtra =
      (this.sabotage === "length" && op === OP.RUN) ? 1 : 0;
    const frame = packFrame({ kind: KIND_REQUEST, abi: this.abi, id, op,
                              status: 0 }, payload, claimExtra);
    let m;
    try {
      this.t.send(frame);
      m = await this.awaitFrame();
    } catch (e) {
      throw this.poison(e instanceof FrameError ? e : new FrameError(e.message));
    }
    let parsed;
    try {
      parsed = unpackFrame(m, this.abi);
    } catch (e) {
      throw this.poison(e);
    }
    const { h, payload: resp } = parsed;
    if (h.id !== id || h.op !== op)
      throw this.poison(new FrameError(
        `response id ${h.id} op 0x${h.op.toString(16).padStart(4, "0")} for ` +
        `request id ${id} op 0x${op.toString(16).padStart(4, "0")}: the ` +
        `stream is out of step`));
    const text = () => new TextDecoder().decode(resp).replace(/\0+$/, "");
    if (h.kind === KIND_REFUSAL) {
      const err = new RemoteError(`the server refused the request: ${text()}`,
                                  h.status, true);
      this.poison(new FrameError(err.message));
      throw err;
    }
    if (h.kind !== KIND_RESPONSE)
      throw this.poison(new FrameError(
        "a frame that is neither a response nor a refusal"));
    if (h.status !== 0)
      throw new RemoteError(
        text() || STATUS_TEXT[h.status] || `status ${h.status}`,
        h.status, false);
    return resp;
  }

  /** The next frame, or a timeout. A handle that timed out is
   *  poisoned by the caller and returns for good, as the C client's
   *  does: the stream is mid-answer and reading on from it is how a
   *  later request gets an earlier response. */
  awaitFrame() {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new FrameError(
        `no response in ${this.timeoutMs} ms`)), this.timeoutMs);
      if (typeof timer.unref === "function") timer.unref();
      this.readFrame().then(
        (v) => { clearTimeout(timer); resolve(v); },
        (e) => { clearTimeout(timer); reject(e); });
    });
  }

  /** One frame off the transport. A message transport hands one over
   *  whole; a stream transport is read for a header and then for the
   *  length the header states, which is where the boundary comes from
   *  on that side. */
  async readFrame() {
    if (this.t.kind === "message")
      return this.t.readMessage();
    const head = await this.t.read(HDR_BYTES);
    const len = new DataView(head.buffer, head.byteOffset, head.byteLength)
      .getUint32(20, true);
    if (len > MAX_PAYLOAD)
      throw new FrameError(`frame length ${len} exceeds the cap`);
    if (!len) return head;
    return concat([head, await this.t.read(len)]);
  }

  // ---- the operations ------------------------------------------------

  async capsAgain() { return parseCaps(await this.request(OP.CAPS)); }

  async stats() {
    const p = await this.request(OP.STATS);
    const dv = new DataView(p.buffer, p.byteOffset, p.byteLength);
    const entries = dv.getUint32(24, true);
    const byOp = {};
    for (let i = 0; i < entries; i++) {
      const o = 32 + i * 16;
      byOp[dv.getUint32(o, true)] = dv.getBigUint64(o + 8, true);
    }
    return {
      requests: dv.getBigUint64(0, true),
      bytesIn: dv.getBigUint64(8, true),
      bytesOut: dv.getBigUint64(16, true),
      byOp,
    };
  }

  /** cft_run. Operands are Uint8Arrays of n dense little-endian
   *  elements; an absent one is simply left out, as it is in the C.
   *  Split so that no frame carries more than CHUNK_BYTES of operand
   *  and result data - the same split, for the same reason (an
   *  element of an elementwise result depends on its own index alone).
   */
  async run(op, fmt, rnd, { a = null, b = null, c = null }, n) {
    const esz = FORMAT_SIZE[fmt];
    if (!esz) throw new Error(`format ${fmt} is not one of fp32/64/128/256`);
    const d = new Uint8Array(n * esz);
    if (n === 0) return { d, flags: 0, bus: 0 };
    const present = (a ? 1 : 0) | (b ? 2 : 0) | (c ? 4 : 0);
    const npresent = (a ? 1 : 0) + (b ? 1 : 0) + (c ? 1 : 0);
    const epc = Math.max(1, Math.floor(CHUNK_BYTES / ((npresent + 1) * esz)));
    let flags = 0, bus = 0;
    for (let off = 0; off < n; off += epc) {
      const k = Math.min(epc, n - off);
      const head = new Uint8Array(24);
      const hv = new DataView(head.buffer);
      hv.setUint32(0, op, true);
      hv.setUint32(4, fmt, true);
      hv.setUint32(8, rnd, true);
      hv.setUint32(12, present, true);
      hv.setBigUint64(16, BigInt(k), true);
      const parts = [head];
      for (const q of [a, b, c])
        if (q) parts.push(q.subarray(off * esz, (off + k) * esz));
      const resp = await this.request(OP.RUN, concat(parts));
      if (resp.length !== 8 + k * esz)
        throw this.poison(new FrameError(
          `RUN answered with ${resp.length} bytes where ${8 + k * esz} were due`));
      const rv = new DataView(resp.buffer, resp.byteOffset, resp.byteLength);
      flags |= rv.getUint32(0, true);
      bus |= rv.getUint32(4, true);
      d.set(resp.subarray(8), off * esz);
      // The negative control: one bit of one returned encoding, flipped
      // after the crc has passed and the frame is accepted. Nothing
      // about the transport notices; the replay and the chains do.
      if (this.sabotage === "bit") d[off * esz] ^= 0x01;
    }
    return { d, flags, bus };
  }

  /** cft_reduce. Not chunked, for the reason docs/REMOTE.md gives: a
   *  partial sum is only reusable if its range is a node of the tree. */
  async reduce(op, fmt, rnd, { a, b = null }, n) {
    const esz = FORMAT_SIZE[fmt];
    if (!esz) throw new Error(`format ${fmt} is not one of fp32/64/128/256`);
    const present = (a ? 1 : 0) | (b ? 2 : 0);
    const head = new Uint8Array(24);
    const hv = new DataView(head.buffer);
    hv.setUint32(0, op, true);
    hv.setUint32(4, fmt, true);
    hv.setUint32(8, rnd, true);
    hv.setUint32(12, present, true);
    hv.setBigUint64(16, BigInt(n), true);
    const parts = [head];
    for (const q of [a, b]) if (q) parts.push(q);
    const resp = await this.request(OP.REDUCE, concat(parts));
    if (resp.length !== 8 + esz)
      throw this.poison(new FrameError(
        `REDUCE answered with ${resp.length} bytes where ${8 + esz} were due`));
    const rv = new DataView(resp.buffer, resp.byteOffset, resp.byteLength);
    return { d: resp.slice(8), flags: rv.getUint32(0, true),
             bus: rv.getUint32(4, true) };
  }

  /** cft_program_load, on the server. The image is validated there by
   *  the same library; the client that has one should validate it
   *  first, as the C client does. */
  async programLoad(image) {
    const resp = await this.request(OP.PROG_LOAD, image);
    if (resp.length !== 16)
      throw this.poison(new FrameError(
        "PROG_LOAD answered with the wrong payload size"));
    const dv = new DataView(resp.buffer, resp.byteOffset, resp.byteLength);
    return { handle: dv.getUint32(0, true), format: dv.getUint32(4, true),
             maxDeposits: dv.getUint32(8, true) };
  }

  /** cft_program_run, one PROG_RUN per chunk of lanes. `fmt` and
   *  `maxDeposits` are what PROG_LOAD read out of the image, and the
   *  response's size is checked against them - a lane's deposits
   *  depend on that lane alone, which is why the chunking is safe. */
  async programRun(handle, fmt, { a = null, b = null, c = null }, n,
                   maxDeposits, wantCounts = false) {
    const esz = FORMAT_SIZE[fmt];
    if (!esz) throw new Error(`format ${fmt} is not one of fp32/64/128/256`);
    const present = (a ? 1 : 0) | (b ? 2 : 0) | (c ? 4 : 0);
    const npresent = (a ? 1 : 0) + (b ? 1 : 0) + (c ? 1 : 0);
    const perLane = npresent * esz + maxDeposits * esz + 4;
    const lpc = Math.max(1, Math.floor(CHUNK_BYTES / perLane));
    const deposits = new Uint8Array(n * maxDeposits * esz);
    const counts = wantCounts ? new Uint32Array(n) : null;
    let flags = 0, bus = 0;
    for (let off = 0; off < n; off += lpc) {
      const k = Math.min(lpc, n - off);
      const head = new Uint8Array(24);
      const hv = new DataView(head.buffer);
      hv.setUint32(0, handle, true);
      hv.setUint32(4, present, true);
      hv.setUint32(8, wantCounts ? 1 : 0, true);
      hv.setUint32(12, 0, true);
      hv.setBigUint64(16, BigInt(k), true);
      const parts = [head];
      for (const q of [a, b, c])
        if (q) parts.push(q.subarray(off * esz, (off + k) * esz));
      const resp = await this.request(OP.PROG_RUN, concat(parts));
      const depBytes = k * maxDeposits * esz;
      const want = 8 + depBytes + (wantCounts ? k * 4 : 0);
      if (resp.length !== want)
        throw this.poison(new FrameError(
          `PROG_RUN answered with ${resp.length} bytes where ${want} were due`));
      const rv = new DataView(resp.buffer, resp.byteOffset, resp.byteLength);
      flags |= rv.getUint32(0, true);
      bus |= rv.getUint32(4, true);
      if (depBytes)
        deposits.set(resp.subarray(8, 8 + depBytes), off * maxDeposits * esz);
      if (counts)
        for (let i = 0; i < k; i++)
          counts[off + i] = rv.getUint32(8 + depBytes + i * 4, true);
    }
    return { deposits, counts, flags, bus };
  }

  async programFree(handle) { await this.request(OP.PROG_FREE, u32le(handle)); }

  // ---- the buffer and status-word operations -------------------------
  //
  // libcft's own client never issues these - buffers are host memory
  // on a remote handle and the status word lives on the client, for
  // the reasons docs/REMOTE.md gives. They are here because the
  // protocol serves them and a client that is not libcft may want
  // them, and because a path nobody exercises is a path nobody has
  // tested.

  async bufAlloc(bytes) {
    const b = new Uint8Array(8);
    new DataView(b.buffer).setBigUint64(0, BigInt(bytes), true);
    const resp = await this.request(OP.BUF_ALLOC, b);
    return new DataView(resp.buffer, resp.byteOffset, resp.byteLength)
      .getUint32(0, true);
  }

  async bufFree(handle) { await this.request(OP.BUF_FREE, u32le(handle)); }

  async bufWrite(handle, offset, bytes) {
    const head = new Uint8Array(16);
    const dv = new DataView(head.buffer);
    dv.setUint32(0, handle, true);
    dv.setUint32(4, 0, true);
    dv.setBigUint64(8, BigInt(offset), true);
    await this.request(OP.BUF_WRITE, concat([head, bytes]));
  }

  async bufRead(handle, offset, bytes) {
    const head = new Uint8Array(24);
    const dv = new DataView(head.buffer);
    dv.setUint32(0, handle, true);
    dv.setUint32(4, 0, true);
    dv.setBigUint64(8, BigInt(offset), true);
    dv.setBigUint64(16, BigInt(bytes), true);
    return this.request(OP.BUF_READ, head);
  }

  async flagsLower(mask) { await this.request(OP.FLAGS_LOWER, u32le(mask)); }
  async flagsRaise(mask) { await this.request(OP.FLAGS_RAISE, u32le(mask)); }

  async flagsTest(mask) {
    const r = await this.request(OP.FLAGS_TEST, u32le(mask));
    return new DataView(r.buffer, r.byteOffset, r.byteLength).getUint32(0, true);
  }

  async flagsSave() {
    const r = await this.request(OP.FLAGS_SAVE);
    return new DataView(r.buffer, r.byteOffset, r.byteLength).getUint32(0, true);
  }

  async flagsRestore(saved, mask) {
    await this.request(OP.FLAGS_RESTORE, concat([u32le(saved), u32le(mask)]));
  }

  async flagsTestSaved(saved, mask) {
    const r = await this.request(OP.FLAGS_TEST_SAVED,
                                 concat([u32le(saved), u32le(mask)]));
    return new DataView(r.buffer, r.byteOffset, r.byteLength).getUint32(0, true);
  }

  /** BYE, then close. Best effort: the socket goes either way. */
  async close() {
    if (!this.poisoned) {
      try { await this.request(OP.BYE); } catch { /* the socket closes anyway */ }
    }
    try { this.t.close(); } catch { /* already gone */ }
  }
}

/** The caps block a HELLO or CAPS response carries. Read by offset and
 *  not by total length: the block's first 56 bytes are what this
 *  document version defines, and a server that appends to it stays
 *  readable here. */
export function parseCaps(p) {
  if (p.length < CAPS_BYTES)
    throw new FrameError(`HELLO answered with ${p.length} bytes, not the ` +
                         `${CAPS_BYTES} of a caps block`);
  const dv = new DataView(p.buffer, p.byteOffset, p.byteLength);
  const name = p.subarray(24, 24 + BACKEND_NAME);
  let end = name.indexOf(0);
  if (end < 0) end = BACKEND_NAME;
  return {
    formatMask: dv.getUint32(0, true),
    opGroups: dv.getUint32(4, true),
    tiles: dv.getUint32(8, true),
    deviceVersion: dv.getUint32(12, true),
    flagsReadable: dv.getUint32(16, true),
    abi: dv.getUint32(20, true),
    backend: new TextDecoder().decode(name.subarray(0, end)),
    extra: p.subarray(CAPS_BYTES),      // whatever a later server appends
  };
}

/** The names cft_format_name gives, in cft_format order. */
export const FORMAT_NAMES = ["binary32", "binary64", "binary128", "binary256"];

/** The rounding attributes, in cft_round order. */
export const ROUND_NAMES = ["rne", "rtz", "rdn", "rup", "rmm"];

/** The transports, exported so that a test can speak the protocol
 *  badly on purpose - a wrong magic, a corrupted crc, a request
 *  before HELLO - the way host/tests/remote_test.c does over TCP. */
export { WebSocketTransport, TcpTransport };
