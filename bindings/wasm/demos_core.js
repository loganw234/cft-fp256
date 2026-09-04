// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The five contract workloads of docs/BENCHMARKS.md, ported to the
// wasm module - one compute core, driven identically by the page's
// Web Worker and by bindings/wasm/verify_demos.mjs under node.
//
// A PLAIN SCRIPT on purpose: no import, no export, no module scope.
// The page splices it into a Blob the worker imports, and node loads
// the same bytes with vm.runInThisContext. One file, one set of bits,
// two drivers - which is what makes "the browser computed the same
// records as the C tool" checkable without a browser.
//
// ===================================================================
// THE RULE THIS FILE KEEPS
//
// Every panel below is a port of ONE C tool's `--engine loop` path:
// the same operation sequence, the same rounding attributes, the same
// flag handling, the same record text, the same SHA-256 chain over it.
// Nothing numeric is computed here. Every result bit is what a cftw_*
// call returned; the only arithmetic in JavaScript is loop counters,
// array indices and the SHA-256 itself.
//
// Where a tool issues one library call per element, this file issues
// one call per BATCH of elements. That is not a liberty: cft_run is
// elementwise by contract, so n elements in one call and n calls of
// one element produce the same n results, and the tools' own
// checkpoints are batch-size independent for exactly this reason.
// It is also the only way a browser can run these at all - one
// _malloc per scalar call is the wasm boundary's known trap, so every
// buffer below is allocated once per job and reused.
//
// Where a value is turned into text for the SCREEN rather than for a
// record, the device's 754-2019 7.1 status word is saved and restored
// across the conversion (5.7.4's saveAllFlags/restoreFlags), because
// a rounded decimal raises inexact and would otherwise show up in a
// flag union that is supposed to describe the arithmetic. That is
// enclose.c's own pattern, borrowed for the same reason.
// ===================================================================

(function (root) {
  "use strict";

  // =================================================================
  // SHA-256, with its constants DERIVED
  //
  // K[i] and H0[i] are the fractional parts of the cube and square
  // roots of the first sixty-four primes. The C tools compute them
  // (collatz.c's root_frac32, over a 128-bit power); so does this,
  // over BigInt, rather than carrying sixty-four hand-typed words that
  // nothing would check.
  // =================================================================
  function firstPrimes(count) {
    const out = [];
    for (let cand = 2; out.length < count; cand++) {
      let prime = true;
      for (let d = 2; d * d <= cand; d++)
        if (cand % d === 0) { prime = false; break; }
      if (prime) out.push(cand);
    }
    return out;
  }

  // floor(frac(p^(1/root)) * 2^32) = low 32 bits of the integer
  // `root`-th root of (p << 32*root). Binary search, exactly as the C.
  function rootFrac32(p, rootN) {
    const target = BigInt(p) << BigInt(32 * rootN);
    const pow = (v) => { let a = 1n; for (let k = 0; k < rootN; k++) a *= v; return a; };
    let lo = 0n, hi = 1n;
    while (pow(hi) <= target) hi <<= 1n;
    while (hi - lo > 1n) {
      const mid = lo + (hi - lo) / 2n;
      if (pow(mid) > target) hi = mid; else lo = mid;
    }
    return Number(lo & 0xffffffffn);
  }

  let SHA_K = null, SHA_H0 = null;
  function shaInit() {
    if (SHA_K) return;
    const primes = firstPrimes(64);
    SHA_K = new Uint32Array(64);
    SHA_H0 = new Uint32Array(8);
    for (let i = 0; i < 64; i++) SHA_K[i] = rootFrac32(primes[i], 3);
    for (let i = 0; i < 8; i++) SHA_H0[i] = rootFrac32(primes[i], 2);
  }

  function rotr32(x, n) { return ((x >>> n) | (x << (32 - n))) >>> 0; }

  function Sha256() {
    shaInit();
    this.h = new Uint32Array(SHA_H0);
    this.bits = 0;
    this.buf = new Uint8Array(64);
    this.have = 0;
    this.w = new Uint32Array(64);
  }
  Sha256.prototype._block = function (p, off) {
    const w = this.w;
    for (let i = 0; i < 16; i++)
      w[i] = ((p[off + 4 * i] << 24) | (p[off + 4 * i + 1] << 16) |
              (p[off + 4 * i + 2] << 8) | p[off + 4 * i + 3]) >>> 0;
    for (let i = 16; i < 64; i++) {
      const x = w[i - 15], y = w[i - 2];
      const s0 = (rotr32(x, 7) ^ rotr32(x, 18) ^ (x >>> 3)) >>> 0;
      const s1 = (rotr32(y, 17) ^ rotr32(y, 19) ^ (y >>> 10)) >>> 0;
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) >>> 0;
    }
    let a = this.h[0], b = this.h[1], c = this.h[2], d = this.h[3];
    let e = this.h[4], f = this.h[5], g = this.h[6], hh = this.h[7];
    for (let i = 0; i < 64; i++) {
      const S1 = (rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25)) >>> 0;
      const ch = ((e & f) ^ (~e & g)) >>> 0;
      const t1 = (hh + S1 + ch + SHA_K[i] + w[i]) >>> 0;
      const S0 = (rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22)) >>> 0;
      const maj = ((a & b) ^ (a & c) ^ (b & c)) >>> 0;
      const t2 = (S0 + maj) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0;
      d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    this.h[0] = (this.h[0] + a) >>> 0; this.h[1] = (this.h[1] + b) >>> 0;
    this.h[2] = (this.h[2] + c) >>> 0; this.h[3] = (this.h[3] + d) >>> 0;
    this.h[4] = (this.h[4] + e) >>> 0; this.h[5] = (this.h[5] + f) >>> 0;
    this.h[6] = (this.h[6] + g) >>> 0; this.h[7] = (this.h[7] + hh) >>> 0;
  };
  Sha256.prototype.push = function (bytes) {
    this.bits += bytes.length * 8;
    let n = bytes.length, off = 0;
    while (n) {
      let take = 64 - this.have;
      if (take > n) take = n;
      this.buf.set(bytes.subarray(off, off + take), this.have);
      this.have += take; off += take; n -= take;
      if (this.have === 64) { this._block(this.buf, 0); this.have = 0; }
    }
  };
  Sha256.prototype.end = function () {
    const bits = this.bits;
    this.buf[this.have++] = 0x80;
    if (this.have > 56) {
      while (this.have < 64) this.buf[this.have++] = 0;
      this._block(this.buf, 0);
      this.have = 0;
    }
    while (this.have < 56) this.buf[this.have++] = 0;
    // The C keeps a uint64 bit count; a JS number is exact to 2^53
    // bits, which is a petabyte of record text - far past anything a
    // browser will hash - and the high word is written from it.
    const hi = Math.floor(bits / 4294967296), lo = bits >>> 0;
    this.buf[56] = (hi >>> 24) & 255; this.buf[57] = (hi >>> 16) & 255;
    this.buf[58] = (hi >>> 8) & 255;  this.buf[59] = hi & 255;
    this.buf[60] = (lo >>> 24) & 255; this.buf[61] = (lo >>> 16) & 255;
    this.buf[62] = (lo >>> 8) & 255;  this.buf[63] = lo & 255;
    this.have = 64;
    this._block(this.buf, 0);
    const out = new Uint8Array(32);
    for (let i = 0; i < 8; i++) {
      out[4 * i] = (this.h[i] >>> 24) & 255;
      out[4 * i + 1] = (this.h[i] >>> 16) & 255;
      out[4 * i + 2] = (this.h[i] >>> 8) & 255;
      out[4 * i + 3] = this.h[i] & 255;
    }
    return out;
  };

  const ENC = (typeof TextEncoder !== "undefined") ? new TextEncoder() : null;
  function bytesOf(s) {
    if (ENC) return ENC.encode(s);
    const out = new Uint8Array(s.length);          // record text is ASCII
    for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i) & 255;
    return out;
  }
  function hex32(b) {
    let s = "";
    for (let i = 0; i < b.length; i++) s += (b[i] >> 4).toString(16) + (b[i] & 15).toString(16);
    return s;
  }

  /** chain_0 = 32 zero bytes; chain_(i+1) = SHA-256(chain_i || line || "\n").
   *  The five tools spell this three slightly different ways (two push
   *  the newline separately, three append it to the line buffer first)
   *  and all five mean this. */
  function Chain() { this.v = new Uint8Array(32); }
  Chain.prototype.absorb = function (line) {
    const h = new Sha256();
    h.push(this.v);
    h.push(bytesOf(line + "\n"));
    this.v = h.end();
  };
  Chain.prototype.hex = function () { return hex32(this.v); };

  /** enclose.c's reproducible byte stream: SHA-256 over a label and a
   *  little-endian counter, read out eight bytes at a time. The dot
   *  kernel's vectors come from it, so they are the same numbers on
   *  every machine - and in this port, the same numbers as the tool's. */
  function Rng(label, stream) {
    this.label = bytesOf(label);
    this.counter = BigInt(stream) << 32n;
    this.buf = new Uint8Array(32);
    this.have = 0;
  }
  Rng.prototype.u64 = function () {
    if (this.have < 8) {
      const h = new Sha256();
      const ctr = new Uint8Array(8);
      let c = this.counter;
      for (let i = 0; i < 8; i++) { ctr[i] = Number(c & 255n); c >>= 8n; }
      h.push(this.label);
      h.push(ctr);
      this.buf = h.end();
      this.counter += 1n;
      this.have = 32;
    }
    let v = 0n;
    const base = 32 - this.have;
    for (let i = 0; i < 8; i++) v |= BigInt(this.buf[base + i]) << BigInt(8 * i);
    this.have -= 8;
    return v;
  };

  // =================================================================
  // The library, as this file uses it
  //
  // The opcode, format, rounding and flag numbers below are cft.h's.
  // They are AUDITED against the module at open time - every opcode
  // name is asked of cftw_op_name and every format name of
  // cftw_format_name - because a mistranscribed opcode field computes
  // a different operation and reports nothing. bindings/node/lib.mjs
  // makes the same check for the same reason.
  // =================================================================
  const OP = {
    fma: 0, add: 1, sub: 2, mul: 3, abs: 4, neg: 5, copysign: 6,
    min: 7, max: 8, minnum: 9, maxnum: 10, select: 11,
    cmplt: 12, cmple: 13, cmpeq: 14,
    iand: 16, ior: 17, ixor: 18, iadd: 19, isub: 20, ishl: 21, ishr: 22,
    icmplt: 23, sum: 24, dot: 25, recip_seed: 26, rsqrt_seed: 27,
    sumsq: 28, sumabs: 29,
  };
  const RND = { rne: 0, rtz: 1, rdn: 2, rup: 3, rmm: 4 };
  const FMTCODE = { fp32: 0, fp64: 1, fp128: 2, fp256: 3 };
  const FLAG = {
    invalid: 1, divbyzero: 2, overflow: 4, underflow: 8, inexact: 16,
  };
  const FLAG_NAMES = [
    [FLAG.invalid, "invalid"], [FLAG.divbyzero, "divideByZero"],
    [FLAG.overflow, "overflow"], [FLAG.underflow, "underflow"],
    [FLAG.inexact, "inexact"],
  ];
  function flagText(f) {
    const on = FLAG_NAMES.filter(([b]) => f & b).map(([, n]) => n);
    return on.length ? on.join(" ") : "none";
  }

  function fail(msg) { throw new Error(msg); }

  /** Wrap an instantiated emscripten module. One device, one bump
   *  allocator, and a table of raw exports - `_cftw_x` where the
   *  module has it (KEEPALIVE puts every one there) and cwrap only as
   *  a fallback, because cwrap's marshalling on a five-hundred-thousand
   *  call workload is the cost this file exists to avoid. */
  function createCft(M) {
    const g = (name, arity) => {
      const raw = M["_" + name];
      if (typeof raw === "function") return raw;
      if (typeof M.cwrap === "function")
        return M.cwrap(name, "number", new Array(arity).fill("number"));
      fail(`the module exports neither _${name} nor cwrap`);
    };
    const C = {
      M,
      abiVersion: g("cftw_abi_version", 0),
      formatSize: g("cftw_format_size", 1),
      formatName: g("cftw_format_name", 1),
      opName: g("cftw_op_name", 1),
      strerror: g("cftw_strerror", 1),
      openSoftware: g("cftw_open_software", 1),
      close: g("cftw_close", 1),
      capsBackend: g("cftw_caps_backend", 1),
      capsMask: g("cftw_caps_format_mask", 1),
      capsFlagsOk: g("cftw_caps_flags_readable", 1),
      run: g("cftw_run", 11),
      reduce: g("cftw_reduce", 10),
      divRaw: g("cftw_div", 9),
      sqrtRaw: g("cftw_sqrt", 8),
      scalebRaw: g("cftw_scaleb", 10),
      convertRaw: g("cftw_convert", 8),
      cvtFromI64: g("cftw_cvt_from_i64", 7),
      cvtToU64: g("cftw_cvt_to_u64", 8),
      fromDecimalChar: g("cftw_from_decimal_char", 8),
      toDecimalChar: g("cftw_to_decimal_char", 9),
      toHexChar: g("cftw_to_hex_char", 6),
      acosRaw: g("cftw_acos", 7),
      rootnRaw: g("cftw_rootn", 8),
      lowerFlags: g("cftw_lower_flags", 2),
      saveAllFlags: g("cftw_save_all_flags", 1),
      restoreFlags: g("cftw_restore_flags", 3),
      flagsAll: g("cftw_flags_all", 0),
    };

    const cstr = (p) => M.UTF8ToString(p);

    // ---- the audit ------------------------------------------------
    for (const [name, code] of Object.entries(OP))
      if (cstr(C.opName(code)) !== name)
        fail(`opcode ${code} is "${cstr(C.opName(code))}" in the module ` +
             `and "${name}" here - one of them is wrong, and a wrong ` +
             `opcode field computes a different operation silently`);
    for (const [name, code] of Object.entries(FMTCODE))
      if (cstr(C.formatName(code)) !== name)
        fail(`format ${code} is "${cstr(C.formatName(code))}" in the ` +
             `module and "${name}" here`);
    const allFlags = C.flagsAll() >>> 0;
    const ourAll = FLAG_NAMES.reduce((a, [b]) => a | b, 0);
    if (allFlags !== ourAll)
      fail(`the module's CFT_FLAGS_ALL is 0x${allFlags.toString(16)} and ` +
           `this file knows 0x${ourAll.toString(16)}`);

    // ---- memory ---------------------------------------------------
    // One arena per job, grown by doubling and never freed piecemeal.
    // Views are re-read on every access: ALLOW_MEMORY_GROWTH detaches
    // the old ArrayBuffer, and a cached HEAPU8 across a growth is the
    // classic way a wasm harness starts reading zeroes.
    const owned = [];
    C.malloc = function (bytes) {
      const p = M._malloc(bytes);
      if (!p) fail(`out of wasm memory asking for ${bytes} bytes`);
      owned.push(p);
      new Uint8Array(M.HEAPU8.buffer, p, bytes).fill(0);
      return p;
    };
    C.freeAll = function () {
      while (owned.length) M._free(owned.pop());
    };
    C.u8 = () => M.HEAPU8;
    C.f64 = () => new Float64Array(M.HEAPU8.buffer);
    C.i32 = () => new Int32Array(M.HEAPU8.buffer);
    C.u32 = () => new Uint32Array(M.HEAPU8.buffer);
    C.copy = function (dst, src, bytes) {
      M.HEAPU8.copyWithin(dst, src, src + bytes);
    };
    C.zero = function (dst, bytes) {
      M.HEAPU8.fill(0, dst, dst + bytes);
    };
    C.same = function (a, b, bytes) {
      const h = M.HEAPU8;
      for (let i = 0; i < bytes; i++) if (h[a + i] !== h[b + i]) return false;
      return true;
    };
    C.isZero = function (a, bytes) {
      const h = M.HEAPU8;
      for (let i = 0; i < bytes; i++) if (h[a + i]) return false;
      return true;
    };

    // ---- the device -----------------------------------------------
    const devOut = C.malloc(4);
    const st = C.openSoftware(devOut);
    if (st !== 0)
      fail(`cft_open: ${cstr(C.strerror(st))}`);
    C.dev = C.u32()[devOut >> 2];
    C.backend = cstr(C.capsBackend(C.dev));
    C.flagsReadable = C.capsFlagsOk(C.dev) !== 0;
    C.formatMask = C.capsMask(C.dev) >>> 0;

    // ---- scratch out-parameters -----------------------------------
    const flagPtr = C.malloc(4);
    const lenPtr = C.malloc(4);
    const i64Ptr = C.malloc(8);
    const ptrPtr = C.malloc(4);
    let txtCap = 4096;
    let txtPtr = C.malloc(txtCap);

    C.calls = 0;
    C.elemOps = 0;

    function check(status, what) {
      if (status !== 0) fail(`${what}: ${cstr(C.strerror(status))}`);
    }

    /** cft_run over n elements. Returns the flag word. */
    C.runN = function (op, fmt, rnd, a, b, c, d, n) {
      C.u32()[flagPtr >> 2] = 0;
      check(C.run(C.dev, op, fmt, rnd, a | 0, b | 0, c | 0, d, n, flagPtr, 0),
            "cft_run");
      C.calls++; C.elemOps += n;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    C.reduceN = function (op, fmt, rnd, a, b, d, n) {
      C.u32()[flagPtr >> 2] = 0;
      check(C.reduce(C.dev, op, fmt, rnd, a | 0, b | 0, d, n, flagPtr, 0),
            "cft_reduce");
      C.calls++; C.elemOps += n;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    C.divN = function (fmt, rnd, a, b, d, n) {
      C.u32()[flagPtr >> 2] = 0;
      check(C.divRaw(C.dev, fmt, rnd, a, b, d, n, flagPtr, 0), "cft_div");
      C.calls++; C.elemOps += n;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    C.sqrtN = function (fmt, rnd, a, d, n) {
      C.u32()[flagPtr >> 2] = 0;
      check(C.sqrtRaw(C.dev, fmt, rnd, a, d, n, flagPtr, 0), "cft_sqrt");
      C.calls++; C.elemOps += n;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    C.scaleb = function (fmt, rnd, a, nexp, d, n) {
      C.u32()[flagPtr >> 2] = 0;
      const lo = nexp >>> 0, hi = Math.floor(nexp / 4294967296) | 0;
      check(C.scalebRaw(C.dev, fmt, rnd, a, lo, hi, d, n, flagPtr, 0),
            "cft_scaleb");
      C.calls++; C.elemOps += n;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    C.convert = function (sfmt, dfmt, rnd, a, d, n) {
      C.u32()[flagPtr >> 2] = 0;
      check(C.convertRaw(C.dev, sfmt, dfmt, rnd, a, d, n, flagPtr),
            "cft_convert");
      C.calls++; C.elemOps += n;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    /** cft_cvt_from_i64 over one element, from a JS BigInt or safe int. */
    C.fromI64 = function (fmt, rnd, v, d) {
      const bv = typeof v === "bigint" ? v : BigInt(v);
      let u = BigInt.asUintN(64, bv);
      const h = C.u8();
      for (let i = 0; i < 8; i++) { h[i64Ptr + i] = Number(u & 255n); u >>= 8n; }
      C.u32()[flagPtr >> 2] = 0;
      check(C.cvtFromI64(C.dev, fmt, rnd, i64Ptr, d, 1, flagPtr),
            "cft_cvt_from_i64");
      C.calls++; C.elemOps += 1;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    /** cft_cvt_to_u64, exact, roundTowardZero - collatz.c's val_to_u64. */
    C.toU64 = function (fmt, a) {
      C.u32()[flagPtr >> 2] = 0;
      check(C.cvtToU64(C.dev, fmt, RND.rtz, 1, a, i64Ptr, 1, flagPtr, 0),
            "cft_cvt_to_u64");
      C.calls++; C.elemOps += 1;
      const fl = C.u32()[flagPtr >> 2] >>> 0;
      if (fl) fail("a value that must fit 64 bits exactly did not");
      const h = C.u8();
      let v = 0n;
      for (let i = 7; i >= 0; i--) v = (v << 8n) | BigInt(h[i64Ptr + i]);
      return v;
    };
    C.acos = function (fmt, rnd, a, d) {
      C.u32()[flagPtr >> 2] = 0;
      check(C.acosRaw(C.dev, fmt, rnd, a, d, 1, flagPtr), "cft_acos");
      C.calls++; C.elemOps += 1;
      return C.u32()[flagPtr >> 2] >>> 0;
    };
    C.rootn = function (fmt, rnd, a, n, d) {
      let u = BigInt.asUintN(64, BigInt(n));
      const h = C.u8();
      for (let i = 0; i < 8; i++) { h[i64Ptr + i] = Number(u & 255n); u >>= 8n; }
      C.u32()[flagPtr >> 2] = 0;
      check(C.rootnRaw(C.dev, fmt, rnd, a, i64Ptr, d, 1, flagPtr),
            "cft_rootn");
      C.calls++; C.elemOps += 1;
      return C.u32()[flagPtr >> 2] >>> 0;
    };

    function ensureTxt(cap) {
      if (cap <= txtCap) return;
      let n = txtCap;
      while (n < cap) n *= 2;
      txtPtr = C.malloc(n);          // the old block stays owned; jobs are short
      txtCap = n;
    }

    /** cft_to_decimal_char. digits = 0 is 5.12.2's EXACT conversion,
     *  and its length is not knowable in advance - about 183,000
     *  digits for the smallest binary256 subnormal - so cft.h gives it
     *  the two-call sizing protocol: a buffer too small refuses with
     *  *len set and NOTHING written. This tries the buffer it has and
     *  only pays for a second call when the answer did not fit, which
     *  on these workloads is never after the first growth.
     *  Returns { text, flags }. */
    C.toDecimal = function (fmt, rnd, a, digits) {
      for (;;) {
        C.u32()[flagPtr >> 2] = 0;
        C.u32()[lenPtr >> 2] = 0;
        const st2 = C.toDecimalChar(C.dev, fmt, rnd, a, digits, txtPtr,
                                    txtCap, lenPtr, flagPtr);
        if (st2 === 0)
          return { text: cstr(txtPtr), flags: C.u32()[flagPtr >> 2] >>> 0 };
        const need = C.u32()[lenPtr >> 2] >>> 0;
        if (!need || need <= txtCap)
          check(st2, "cft_to_decimal_char");
        ensureTxt(need);
      }
    };
    /** cft_to_hex_char - exact always, so no attribute and no flags
     *  (cft.h gives this one neither). Same sizing protocol. */
    C.toHex = function (fmt, a) {
      for (;;) {
        C.u32()[lenPtr >> 2] = 0;
        const st2 = C.toHexChar(C.dev, fmt, a, txtPtr, txtCap, lenPtr);
        if (st2 === 0) return cstr(txtPtr);
        const need = C.u32()[lenPtr >> 2] >>> 0;
        if (!need || need <= txtCap) check(st2, "cft_to_hex_char");
        ensureTxt(need);
      }
    };
    /** cft_from_decimal_char over one string. Returns { ok, flags }:
     *  ok is false when the library refused the syntax. */
    C.fromDecimal = function (fmt, rnd, s, d) {
      const bytes = M.lengthBytesUTF8(s) + 1;
      ensureTxt(bytes);
      M.stringToUTF8(s, txtPtr, txtCap);
      C.u32()[ptrPtr >> 2] = txtPtr;
      C.u32()[flagPtr >> 2] = 0;
      const status = C.fromDecimalChar(C.dev, fmt, rnd, ptrPtr, d, 1, 0,
                                       flagPtr);
      return { ok: status === 0, status,
               flags: C.u32()[flagPtr >> 2] >>> 0 };
    };

    /** Anything computed for the SCREEN rather than for a record goes
     *  through here: the 754-2019 7.1 status word is saved and
     *  restored across it (5.7.4), and so are the call counters, so a
     *  printout can neither pollute the flag union nor inflate the
     *  rate the panel reports. enclose.c's val_to_dec does the first
     *  half of this for the same reason. */
    C.present = function (fn) {
      const saved = C.saveAllFlags(C.dev) >>> 0;
      const calls = C.calls, ops = C.elemOps;
      try {
        return fn();
      } finally {
        C.restoreFlags(C.dev, saved, allFlags);
        C.calls = calls; C.elemOps = ops;
      }
    };
    C.showDecimal = function (fmt, a, digits) {
      return C.present(() => C.toDecimal(fmt, RND.rne, a, digits).text);
    };
    /** Presentation only: the value as a JS double, for a plot axis. */
    C.showDouble = function (fmt, a) {
      if (fmt === FMTCODE.fp64) return C.f64()[a >> 3];
      return C.present(() => {
        C.convert(fmt, FMTCODE.fp64, RND.rne, a, C.scratch64, 1);
        return C.f64()[C.scratch64 >> 3];
      });
    };
    C.scratch64 = C.malloc(8);
    // Eight element-wide scratch slots, MAX_ESZ bytes each so any
    // format fits. Callers pick a slot by index rather than sharing
    // one, because two helpers reaching for "the" scratch is how a
    // comparison starts reading a shift count.
    const TMP = [];
    for (let i = 0; i < 8; i++) TMP.push(C.malloc(32));
    C.tmp = (i) => TMP[i];
    C.flagsAllMask = allFlags;
    return C;
  }

  /** collatz.c / zoom.c / orbits.c / enclose.c / mersenne.c all measure
   *  p the same way, and none of them tabulates it: p is the smallest k
   *  for which 2^k + 1 is not representable, and the LIBRARY answers
   *  that question, in the flag it raises. */
  function measureFormat(C, fmtName) {
    const fmt = FMTCODE[fmtName];
    if (fmt === undefined) fail(`unknown format ${fmtName}`);
    const esz = C.formatSize(fmt);
    if (!esz) fail(`the module does not know format ${fmtName}`);
    const width = esz * 8;
    const one = C.malloc(esz), pow = C.malloc(esz), sum = C.malloc(esz);
    C.fromI64(fmt, RND.rne, 1, one);
    let prec = 0;
    for (let k = 1; k < width; k++) {
      C.scaleb(fmt, RND.rne, one, k, pow, 1);
      const f = C.runN(OP.add, fmt, RND.rne, pow, 0, one, sum, 1);
      if (f & FLAG.inexact) { prec = k; break; }
    }
    if (!prec) fail("could not measure the format's precision");
    const expW = width - prec;
    const bias = Math.pow(2, expW - 1) - 1;
    // orbits.c's derived Newton count: the seed is good to eight bits
    // and a step takes b to 2b - 1, iterated until it passes p + 2.
    let bits = 8, newton = 0;
    while (bits < prec + 2) { bits = 2 * bits - 1; newton++; }
    return { name: fmtName, fmt, esz, width, prec, expW, bias, newton,
             emin: 1 - bias, emax: bias };
  }

  // The exact decimal of an integral value, reshaped from 5.12.2's
  // "d.ddde+E" into a plain integer - collatz.c's val_to_dec, which
  // mersenne.c copied for the same reason.
  function decInteger(C, fi, ptr) {
    const raw = C.toDecimal(fi.fmt, RND.rne, ptr, 0).text;
    let p = 0, neg = false;
    if (raw[0] === "-") { neg = true; p = 1; }
    else if (raw[0] === "+") p = 1;
    let digits = "";
    while (p < raw.length && raw[p] !== "e" && raw[p] !== "E") {
      if (raw[p] !== ".") digits += raw[p];
      p++;
    }
    let expo = 0;
    if (p < raw.length) expo = parseInt(raw.slice(p + 1), 10);
    if (digits.length === 0 || digits === "0") return "0";
    if (expo < 0) fail(`${raw} is not an integer`);
    const want = expo + 1;
    if (want < digits.length) fail(`${raw} is not an integer`);
    return (neg ? "-" : "") + digits + "0".repeat(want - digits.length);
  }

  // A little-endian integer bit pattern of the element's width -
  // collatz.c's bits_from_u64, for the integer opcodes' shift counts.
  function bitsFromU64(C, fi, v, out) {
    C.zero(out, fi.esz);
    const h = C.u8();
    let u = BigInt(v);
    for (let i = 0; i < 8 && i < fi.esz; i++) {
      h[out + i] = Number(u & 255n); u >>= 8n;
    }
  }

  function valPow2(C, fi, e, out) {
    const one = C.tmp(0);
    C.fromI64(fi.fmt, RND.rne, 1, one);
    C.scaleb(fi.fmt, RND.rne, one, e, out, 1);
  }

  function bcast(C, fi, dst, src, n) {
    for (let i = 0; i < n; i++) C.copy(dst + i * fi.esz, src, fi.esz);
  }

  // =================================================================
  // Panel 1: cft-collatz --engine loop
  //
  // engine_pass() from host/tools/collatz.c, opcode for opcode. The C
  // issues these twenty-three passes over the live slots; so does this,
  // with the batch being the whole ensemble.
  // =================================================================
  const K = { HALF: 0, ONE: 1, THREE: 2, MTHREE: 3, ZERO: 4, P2: 5,
              IPM1: 6, ISH: 7, I1: 8, N: 9 };

  function collatzJob(C, cfg) {
    const fi = measureFormat(C, cfg.format);
    const esz = fi.esz;
    const deep = cfg.mode === "deep";
    const cap = deep ? cfg.values.length
                     : Math.min(cfg.batch, cfg.to - cfg.from);
    if (cap <= 0) fail("that configuration resolves no starting values");

    const arr = (n) => C.malloc(n * esz);
    const S = {
      n: arr(cap), cnt: arr(cap), peak: arr(cap), esc: arr(cap),
      live: arr(cap), start: arr(cap),
      q: arr(cap), t: arr(cap), odd: arr(cap), nn: arr(cap), y: arr(cap),
      ex: arr(cap), nd: arr(cap), cand: arr(cap), tmp: arr(cap),
    };
    const bc = [];
    for (let i = 0; i < K.N; i++) bc.push(arr(cap));
    const c1 = C.malloc(esz);
    valPow2(C, fi, -1, c1);            bcast(C, fi, bc[K.HALF], c1, cap);
    C.fromI64(fi.fmt, RND.rne, 1, c1); bcast(C, fi, bc[K.ONE], c1, cap);
    C.fromI64(fi.fmt, RND.rne, 3, c1); bcast(C, fi, bc[K.THREE], c1, cap);
    C.fromI64(fi.fmt, RND.rne, -3, c1); bcast(C, fi, bc[K.MTHREE], c1, cap);
    C.fromI64(fi.fmt, RND.rne, 0, c1); bcast(C, fi, bc[K.ZERO], c1, cap);
    valPow2(C, fi, fi.prec, c1);       bcast(C, fi, bc[K.P2], c1, cap);
    bitsFromU64(C, fi, fi.prec - 1, c1);            bcast(C, fi, bc[K.IPM1], c1, cap);
    bitsFromU64(C, fi, (fi.prec - 1) + fi.bias, c1); bcast(C, fi, bc[K.ISH], c1, cap);
    bitsFromU64(C, fi, 1, c1);         bcast(C, fi, bc[K.I1], c1, cap);

    const one = C.malloc(esz), wcap = C.malloc(esz), cursor = C.malloc(esz);
    const hi = C.malloc(esz);
    C.fromI64(fi.fmt, RND.rne, 1, one);
    valPow2(C, fi, 2 * fi.prec - 4, wcap);

    // The tool lowers the status word here: measuring p and building
    // the constants deliberately raised inexact, and 7.1 says a flag
    // is lowered only at the user's request. This is that request.
    C.lowerFlags(C.dev, C.flagsAllMask);
    C.calls = 0; C.elemOps = 0;

    let live = 0, nrec = 0;
    const recSlot = new Int32Array(cap);
    const recs = [];
    const chain = new Chain();
    let flagsSeen = 0, steps = 0, resolved = 0, escaped = 0, verified = 0;
    let maxSteps = 0, maxStepsN = "-", firstEscape = null;
    const trail = [];        // the trajectory, for the plot (presentation)
    let escapeAt = null;     // the index in `trail` where exactness ended
    let haveHi = false;

    if (deep) {
      for (const s of cfg.values) {
        const slot = live;
        const r = C.fromDecimal(fi.fmt, RND.rne, s, S.start + slot * esz);
        if (!r.ok || (r.flags & (FLAG.inexact | FLAG.overflow)))
          fail(`${s} is not an integer ${fi.name} holds exactly`);
        C.copy(S.n + slot * esz, S.start + slot * esz, esz);
        C.copy(S.peak + slot * esz, S.start + slot * esz, esz);
        C.zero(S.cnt + slot * esz, esz);
        C.zero(S.esc + slot * esz, esz);
        C.copy(S.live + slot * esz, one, esz);
        recSlot[slot] = nrec;
        recs.push(null);
        nrec++; live++;
      }
    } else {
      const r = C.fromDecimal(fi.fmt, RND.rne, String(cfg.from), cursor);
      if (!r.ok || (r.flags & (FLAG.inexact | FLAG.overflow)))
        fail("--from is not an integer this format holds exactly");
      const r2 = C.fromDecimal(fi.fmt, RND.rne, String(cfg.to), hi);
      if (!r2.ok || (r2.flags & (FLAG.inexact | FLAG.overflow)))
        fail("--to is not an integer this format holds exactly");
      haveHi = true;
    }

    function valLt(a, b) {
      const r = C.tmp(1);
      C.runN(OP.cmplt, fi.fmt, RND.rne, a, b, 0, r, 1);
      return !C.isZero(r, esz);
    }

    function fillBatch() {
      const want = cfg.batch - nrec;
      for (let i = 0; i < want; i++) {
        const slot = live;
        if (haveHi && !valLt(cursor, hi)) break;
        C.copy(S.start + slot * esz, cursor, esz);
        C.copy(S.n + slot * esz, cursor, esz);
        C.copy(S.peak + slot * esz, cursor, esz);
        C.zero(S.cnt + slot * esz, esz);
        C.zero(S.esc + slot * esz, esz);
        C.copy(S.live + slot * esz, one, esz);
        recSlot[slot] = nrec;
        recs.push(null);
        nrec++; live++;
        const f = C.runN(OP.add, fi.fmt, RND.rne, cursor, 0, one, cursor, 1);
        if (f & FLAG.inexact)
          fail("the sweep reached the largest integer this format holds exactly");
      }
    }

    // 23 elementwise passes, in the C's order. `f` is the union over
    // them and nothing else, so the flag/witness agreement below means
    // what the tool says it means.
    function enginePass(n) {
      let f = 0, newlyEscaped = 0;
      const R = (op, a, b, c, d) => { f |= C.runN(op, fi.fmt, RND.rne, a, b, c, d, n); };
      R(OP.cmplt, bc[K.ONE], S.n, 0, S.nd);
      R(OP.min, S.live, S.nd, 0, S.live);
      R(OP.mul, S.n, bc[K.HALF], 0, S.q);
      R(OP.ishr, S.n, bc[K.IPM1], 0, S.t);
      R(OP.isub, bc[K.ISH], S.t, 0, S.t);
      R(OP.ishr, S.n, S.t, 0, S.t);
      R(OP.iand, S.t, bc[K.I1], 0, S.t);
      R(OP.icmplt, bc[K.ZERO], S.t, 0, S.odd);
      R(OP.cmplt, S.n, bc[K.P2], 0, S.t);
      R(OP.min, S.odd, S.t, 0, S.odd);
      R(OP.min, S.odd, S.live, 0, S.tmp);
      R(OP.select, S.n, bc[K.ONE], S.tmp, S.nn);
      R(OP.fma, S.nn, bc[K.THREE], bc[K.ONE], S.y);
      R(OP.fma, S.nn, bc[K.MTHREE], S.y, S.ex);
      R(OP.cmpeq, S.ex, bc[K.ONE], 0, S.ex);
      R(OP.select, bc[K.ZERO], bc[K.ONE], S.ex, S.tmp);
      R(OP.select, S.tmp, S.esc, S.live, S.esc);
      R(OP.min, S.live, S.ex, 0, S.live);
      R(OP.select, S.y, S.q, S.odd, S.cand);
      R(OP.select, S.cand, S.n, S.live, S.n);
      R(OP.add, S.cnt, 0, bc[K.ONE], S.tmp);
      R(OP.select, S.tmp, S.cnt, S.live, S.cnt);
      R(OP.max, S.peak, S.n, 0, S.peak);
      for (let i = 0; i < n; i++)
        if (!C.isZero(S.esc + i * esz, esz)) newlyEscaped++;

      flagsSeen |= f;
      if (f & (FLAG.invalid | FLAG.divbyzero | FLAG.overflow | FLAG.underflow))
        fail(`the library raised 0x${f.toString(16)} on a step that can ` +
             `only ever raise inexact`);
      if (C.flagsReadable) {
        const flag = (f & FLAG.inexact) !== 0;
        const wit = newlyEscaped !== 0;
        if (flag !== wit)
          fail(`the INEXACT flag (${flag ? 1 : 0}) and the per-element ` +
               `exactness witness (${newlyEscaped} escapes) disagree`);
      }
      return newlyEscaped;
    }

    function harvest() {
      let keep = 0;
      for (let i = 0; i < live; i++) {
        const nv = S.n + i * esz;
        const esc = !C.isZero(S.esc + i * esz, esz);
        const done = C.same(nv, one, esz);
        if (!esc && !done) {
          if (keep !== i) {
            for (const p of [S.n, S.cnt, S.peak, S.esc, S.live, S.start])
              C.copy(p + keep * esz, p + i * esz, esz);
            recSlot[keep] = recSlot[i];
          }
          keep++;
          continue;
        }
        recs[recSlot[i]] = {
          n0: decInteger(C, fi, S.start + i * esz),
          peak: decInteger(C, fi, S.peak + i * esz),
          final: decInteger(C, fi, nv),
          steps: C.toU64(fi.fmt, S.cnt + i * esz),
          escaped: esc,
        };
      }
      live = keep;
    }

    function checkWitnessDomain() {
      for (let i = 0; i < live; i++)
        if (!valLt(S.peak + i * esz, wcap))
          fail("a trajectory left the exactness witness's proven domain");
    }

    function flushRecords() {
      for (let i = 0; i < nrec; i++) {
        const r = recs[i];
        if (!r) fail("a record was never filled");
        resolved++;
        steps += Number(r.steps);
        if (r.escaped) {
          escaped++;
          if (!firstEscape) firstEscape = { n0: r.n0, step: r.steps.toString() };
        } else {
          verified++;
          if (Number(r.steps) > maxSteps) { maxSteps = Number(r.steps); maxStepsN = r.n0; }
        }
        chain.absorb(`${r.n0} ${r.steps} ${r.peak} ${r.final} ` +
                     (r.escaped ? "esc" : "ok"));
      }
      const out = recs.slice(0, nrec);
      recs.length = 0;
      nrec = 0;
      return out;
    }

    let done = false, batches = 0;
    const scatter = [];
    const job = {
      title: "collatz", format: fi,
      total: deep ? 1 : (cfg.to - cfg.from),
      step() {
        if (done) return { done: true };
        const emitted = { rows: [], trail: null };
        if (!live && !nrec) {
          if (!deep) fillBatch();
          if (!live && !nrec) { done = true; return { done: true, emitted }; }
        }
        if (live) {
          // Presentation only: lane 0's value, sampled before the first
          // step and after every one, so the plotted trajectory is the
          // one the record describes. It is a conversion to binary64
          // under save/restore - it changes no bit and no flag.
          if (deep && trail.length === 0)
            trail.push(C.showDouble(fi.fmt, S.n));
          enginePass(live);
          checkWitnessDomain();
          if (deep && trail.length < 200000) {
            trail.push(C.showDouble(fi.fmt, S.n));
            if (!C.isZero(S.esc, esz) && escapeAt === null)
              escapeAt = trail.length - 1;
          }
          harvest();
          emitted.trail = deep ? trail.length : 0;
          if (live) return { done: false, emitted, live };
        }
        const flushed = flushRecords();
        for (const r of flushed) {
          scatter.push({ n0: r.n0, steps: Number(r.steps), peak: r.peak,
                         escaped: r.escaped });
          emitted.rows.push(r);
        }
        batches++;
        if (deep) { done = true; return { done: true, emitted }; }
        if (haveHi && !valLt(cursor, hi)) { done = true; return { done: true, emitted }; }
        return { done: false, emitted };
      },
      result() {
        return {
          chain: chain.hex(),
          chains: { chain: chain.hex() },
          stats: {
            format: fi.name, prec: fi.prec, resolved, verified, escaped,
            steps, maxSteps, maxStepsN,
            firstEscape,
            flags: flagsSeen, flagText: flagText(flagsSeen),
            status: C.saveAllFlags(C.dev) >>> 0,
            calls: C.calls, elemOps: C.elemOps, batches,
          },
          scatter,
          trail,
          escapeAt,
          exactEdge: fi.prec,          // every integer below 2^p is exact
          work: steps,                 // Collatz steps: the rate's numerator
          workUnit: "Collatz steps",
        };
      },
    };
    return job;
  }

  // =================================================================
  // Panel 2: cft-zoom --engine loop
  //
  // Three phases in one job: derive the nucleus (scan_eval's five
  // opcodes, at fp256 whatever the reference format is), run the
  // reference orbit (orbit_pass's eight), then the perturbed pixels
  // (pixel_chunk's twenty-three, at fp64).
  //
  // ONE departure from the C's call shape, and it changes no bit: the
  // seven per-iteration scalars pixel_chunk computes inside its
  // k-loop depend on the reference alone, so they are computed here as
  // seven BATCHED passes over the whole reference before the pixel
  // loop starts. cft_run is elementwise, so element k of the batched
  // pass and the C's k-th scalar call are the same operation on the
  // same operands; what it saves is 7 * maxk * chunks wasm crossings.
  // =================================================================
  function zoomJob(C, cfg) {
    const fi = measureFormat(C, cfg.format);
    const pf = measureFormat(C, "fp64");
    const f256 = measureFormat(C, "fp256");
    const esz = fi.esz;
    const width = cfg.width;
    if (!width || (width & (width - 1)))
      fail("width must be a power of two");
    let sh = 0; { let w = width; while (w > 1) { w >>= 1; sh++; } }
    const glitchBits = cfg.glitchBits > 0 ? cfg.glitchBits : (pf.prec >> 2);
    const zoomExp = cfg.zoomExp;
    const e = -zoomExp - sh;
    if (e < pf.emin)
      fail("that zoom and width put one pixel below binary64's smallest normal");

    // ---- the geometry, at binary256 ----
    const pixscale = C.malloc(f256.esz);
    valPow2(C, f256, 1 - zoomExp - sh, pixscale);

    // ---- the centre ----
    const c256r = C.malloc(f256.esz), c256i = C.malloc(f256.esz);
    const period = cfg.period;
    if (2 * period + 5 > f256.prec)
      fail("binary256 cannot hold the search grid for that period exactly");

    const SCAN_STEPS = 320;
    function deriveCentre() {
      const z = f256, ez = z.esz;
      const cand = C.malloc(SCAN_STEPS * ez), zval = C.malloc(SCAN_STEPS * ez);
      const minus2 = C.malloc(ez), w = C.malloc(ez), eighth = C.malloc(ez);
      const stepv = C.malloc(ez), zero = C.malloc(ez);
      const lo = C.malloc(ez), hi = C.malloc(ez), mid = C.malloc(ez);
      const zlo = C.malloc(ez), zhi = C.malloc(ez), zmid = C.malloc(ez);
      const maglo = C.malloc(ez), maghi = C.malloc(ez);
      const ival = C.malloc(ez), eps = C.malloc(ez);
      const half = C.malloc(ez), sum = C.malloc(ez);
      C.fromI64(z.fmt, RND.rne, -2, minus2);
      valPow2(C, z, -2 * period, w);
      valPow2(C, z, -3, eighth);
      C.zero(zero, ez);

      // scan_engine, loop route: five opcodes an iteration.
      const cap = SCAN_STEPS;
      const sz = C.malloc(cap * ez), ss = C.malloc(cap * ez);
      const sp = C.malloc(cap * ez), slive = C.malloc(cap * ez);
      const scand = C.malloc(cap * ez), sfour = C.malloc(cap * ez);
      const four = C.malloc(ez), oneV = C.malloc(ez);
      C.fromI64(z.fmt, RND.rne, 4, four);
      C.fromI64(z.fmt, RND.rne, 1, oneV);
      bcast(C, z, sfour, four, cap);

      function scanEval(cPtr, outPtr, n) {
        C.zero(sz, n * ez);
        bcast(C, z, slive, oneV, n);
        for (let it = 0; it < period; it++) {
          C.runN(OP.mul, z.fmt, RND.rne, sz, sz, 0, ss, n);
          const f = C.runN(OP.cmple, z.fmt, RND.rne, ss, sfour, 0, sp, n);
          if (f) fail("the escape comparison raised a flag");
          C.runN(OP.min, z.fmt, RND.rne, slive, sp, 0, slive, n);
          C.runN(OP.add, z.fmt, RND.rne, ss, 0, cPtr, scand, n);
          C.runN(OP.select, z.fmt, RND.rne, scand, sz, slive, sz, n);
        }
        C.copy(outPtr, sz, n * ez);
      }
      const vlt = (a, b) => {
        const r = C.tmp(1);
        C.runN(OP.cmplt, z.fmt, RND.rne, a, b, 0, r, 1);
        return !C.isZero(r, ez);
      };

      for (let i = 0; i < SCAN_STEPS; i++) {
        C.fromI64(z.fmt, RND.rne, i + 1, ival);
        C.runN(OP.mul, z.fmt, RND.rne, ival, w, 0, stepv, 1);
        C.runN(OP.mul, z.fmt, RND.rne, stepv, eighth, 0, eps, 1);
        C.runN(OP.add, z.fmt, RND.rne, minus2, 0, eps, cand + i * ez, 1);
      }
      const perCall = Math.min(cfg.batch || 1, SCAN_STEPS);
      for (let i = 0; i < SCAN_STEPS; i += perCall) {
        const n = Math.min(perCall, SCAN_STEPS - i);
        scanEval(cand + i * ez, zval + i * ez, n);
      }
      let brk = -1, sgnLo = false;
      for (let i = 0; i + 1 < SCAN_STEPS; i++) {
        const a = vlt(zval + i * ez, zero), b = vlt(zval + (i + 1) * ez, zero);
        if (a !== b) { brk = i; sgnLo = a; break; }
      }
      if (brk < 0) fail("no sign change of z_p was found near the tip");
      C.copy(lo, cand + brk * ez, ez);
      C.copy(hi, cand + (brk + 1) * ez, ez);
      C.copy(zlo, zval + brk * ez, ez);
      C.copy(zhi, zval + (brk + 1) * ez, ez);
      for (;;) {
        valPow2(C, z, -1, half);
        C.runN(OP.add, z.fmt, RND.rne, lo, 0, hi, sum, 1);
        C.runN(OP.mul, z.fmt, RND.rne, sum, half, 0, mid, 1);
        if (C.same(mid, lo, ez) || C.same(mid, hi, ez)) break;
        scanEval(mid, zmid, 1);
        const s = vlt(zmid, zero);
        if (s === sgnLo) { C.copy(lo, mid, ez); C.copy(zlo, zmid, ez); }
        else { C.copy(hi, mid, ez); C.copy(zhi, zmid, ez); }
      }
      C.runN(OP.mul, z.fmt, RND.rne, zlo, zlo, 0, maglo, 1);
      C.runN(OP.mul, z.fmt, RND.rne, zhi, zhi, 0, maghi, 1);
      C.copy(c256r, vlt(maghi, maglo) ? hi : lo, ez);
      C.zero(c256i, ez);
    }

    if (cfg.centre) {
      const parts = String(cfg.centre).split(",");
      if (parts.length !== 2) fail("centre takes RE,IM");
      for (const [s, dst] of [[parts[0], c256r], [parts[1], c256i]]) {
        const r = C.fromDecimal(f256.fmt, RND.rne, s.trim(), dst);
        if (!r.ok || (r.flags & (FLAG.inexact | FLAG.overflow)))
          fail("centre is not a pair binary256 holds exactly");
      }
    } else {
      deriveCentre();
    }
    if (cfg.refOffset) {
      const shift = C.malloc(f256.esz), nref = C.malloc(f256.esz);
      C.fromI64(f256.fmt, RND.rne, cfg.refOffset, shift);
      C.runN(OP.mul, f256.fmt, RND.rne, shift, pixscale, 0, nref, 1);
      C.runN(OP.add, f256.fmt, RND.rne, c256r, 0, nref, c256r, 1);
    }

    const cr = C.malloc(esz), ci = C.malloc(esz);
    if (fi.fmt === f256.fmt) {
      C.copy(cr, c256r, esz); C.copy(ci, c256i, esz);
    } else {
      C.convert(f256.fmt, fi.fmt, RND.rne, c256r, cr, 1);
      C.convert(f256.fmt, fi.fmt, RND.rne, c256i, ci, 1);
    }

    // 7.1's status word is lowered ONCE, here, now the setup is done.
    C.lowerFlags(C.dev, C.flagsAllMask);
    C.calls = 0; C.elemOps = 0;

    const refIters = cfg.refIters;
    const orbR = C.malloc((refIters + 2) * esz);
    const orbI = C.malloc((refIters + 2) * esz);
    const zr = C.malloc(esz), zi = C.malloc(esz);
    const four = C.malloc(esz);
    C.fromI64(fi.fmt, RND.rne, 4, four);
    const oa = C.malloc(esz), ob = C.malloc(esz), om = C.malloc(esz);
    const op_ = C.malloc(esz), ot = C.malloc(esz), od = C.malloc(esz);
    const onzi = C.malloc(esz);

    const chain = new Chain();
    const pixchain = new Chain();
    let k = 0, escapedAt = 0, flagsRef = 0, flagsSeen = 0;
    const orbitPlot = [];

    function noteFlags(f) {
      flagsSeen |= f;
      if (f & (FLAG.invalid | FLAG.divbyzero | FLAG.overflow | FLAG.underflow))
        fail(`the library raised 0x${f.toString(16)} on a step that can ` +
             `only ever raise inexact`);
    }
    const R1 = (op, a, b, c, d) => noteFlags(C.runN(op, fi.fmt, RND.rne, a, b, c, d, 1));

    // orbit_pass, loop route: eight ALU issues an iteration.
    function orbitIter() {
      R1(OP.mul, zr, zr, 0, oa);
      R1(OP.mul, zi, zi, 0, ob);
      R1(OP.add, oa, 0, ob, om);
      const f = C.runN(OP.cmple, fi.fmt, RND.rne, om, four, 0, op_, 1);
      if (f) fail("the escape comparison raised a flag");
      if (C.isZero(op_, esz)) return false;
      R1(OP.add, zr, 0, zr, ot);
      R1(OP.sub, oa, 0, ob, od);
      R1(OP.fma, ot, zi, ci, onzi);
      R1(OP.add, od, 0, cr, zr);
      C.copy(zi, onzi, esz);
      return true;
    }

    // ---- the pixel phase's state, built when the orbit is done ----
    let P = null, maxk = 0, npix = width * width, pixBase = 0;
    let pixIter = null, pixKind = null;
    let pixelWork = 0;

    function preparePixels() {
      maxk = Math.min(cfg.pixelIters, k >= 1 ? k - 1 : 0);
      if (!maxk) fail("the reference orbit is too short for any pixel work");
      const refR = C.malloc((maxk + 2) * 8), refI = C.malloc((maxk + 2) * 8);
      noteFlags(C.convert(fi.fmt, pf.fmt, RND.rne, orbR, refR, maxk + 2));
      noteFlags(C.convert(fi.fmt, pf.fmt, RND.rne, orbI, refI, maxk + 2));

      // tol = 2^-glitch_bits, by repeated halving as the C does.
      let tol = 1.0;
      for (let b = 0; b < glitchBits; b++) tol *= 0.5;

      // The seven per-iteration scalars, as seven batched passes.
      const n = maxk;
      const a2 = C.malloc(n * 8), b2 = C.malloc(n * 8), nb2 = C.malloc(n * 8);
      const t1 = C.malloc(n * 8), t2 = C.malloc(n * 8), gm = C.malloc(n * 8);
      const tolv = C.malloc(n * 8);
      const F = C.f64();
      for (let i = 0; i < n; i++) F[(tolv >> 3) + i] = tol;
      const PR = (op, a, b, c, d) => noteFlags(C.runN(op, pf.fmt, RND.rne, a, b, c, d, n));
      PR(OP.add, refR, 0, refR, a2);
      PR(OP.add, refI, 0, refI, b2);
      PR(OP.neg, b2, 0, 0, nb2);
      PR(OP.mul, refR + 8, refR + 8, 0, t1);
      PR(OP.fma, refI + 8, refI + 8, t1, t2);
      PR(OP.mul, t2, tolv, 0, gm);
      PR(OP.mul, gm, tolv, 0, gm);

      const cap = Math.min(cfg.batch, npix);
      const d = (m) => C.malloc(m * 8);
      P = {
        refR, refI, a2, b2, nb2, gm, cap, tol,
        dcr: d(cap), dci: d(cap), dr: d(cap), di: d(cap),
        live: d(cap), glit: d(cap), iter: d(cap),
        s1: d(cap), s2: d(cap), s3: d(cap), ndr: d(cap),
        u1: d(cap), u2: d(cap), d2: d(cap), ndi: d(cap), ndiNeg: d(cap),
        fr: d(cap), fi_: d(cap), pp: d(cap), mm: d(cap),
        glok: d(cap), escok: d(cap), ok: d(cap), glnow: d(cap), glev: d(cap),
        bA: d(cap), bB: d(cap), bnB: d(cap), bZr: d(cap), bZi: d(cap),
        bGT: d(cap), bK: d(cap), bFOUR: d(cap), bZERO: d(cap), bONE: d(cap),
        idx: new Int32Array(cap),
      };
      pixIter = new Int32Array(npix);
      pixKind = new Int8Array(npix).fill(-1);
      // half a pixel, as a binary64 number
      const ph = C.malloc(8);
      valPow2(C, pf, -zoomExp - sh, ph);
      P.pixd = C.f64()[ph >> 3];
    }

    function dfill(ptr, v, n) {
      const F = C.f64(); const base = ptr >> 3;
      for (let i = 0; i < n; i++) F[base + i] = v;
    }

    // pixel_chunk, opcode for opcode.
    function pixelChunk(n) {
      const F = () => C.f64();
      dfill(P.bFOUR, 4.0, n); dfill(P.bZERO, 0.0, n); dfill(P.bONE, 1.0, n);
      dfill(P.live, 1.0, n); dfill(P.glit, 0.0, n); dfill(P.iter, 0.0, n);
      C.zero(P.dr, n * 8); C.zero(P.di, n * 8);
      let live = n;
      for (let kk = 0; kk < maxk && live; kk++) {
        const H = F();
        const a2 = H[(P.a2 >> 3) + kk], b2 = H[(P.b2 >> 3) + kk];
        const nb2 = H[(P.nb2 >> 3) + kk], gm = H[(P.gm >> 3) + kk];
        const nr = H[(P.refR >> 3) + kk + 1], ni = H[(P.refI >> 3) + kk + 1];
        dfill(P.bA, a2, live); dfill(P.bB, b2, live); dfill(P.bnB, nb2, live);
        dfill(P.bZr, nr, live); dfill(P.bZi, ni, live);
        dfill(P.bGT, gm, live); dfill(P.bK, kk + 1, live);

        const PR = (op, a, b, c, d) => noteFlags(C.runN(op, pf.fmt, RND.rne, a, b, c, d, live));
        PR(OP.fma, P.bA, P.dr, P.dcr, P.s1);
        PR(OP.fma, P.bnB, P.di, P.s1, P.s2);
        PR(OP.fma, P.dr, P.dr, P.s2, P.s3);
        PR(OP.neg, P.di, 0, 0, P.ndiNeg);
        PR(OP.fma, P.ndiNeg, P.di, P.s3, P.ndr);
        PR(OP.fma, P.bA, P.di, P.dci, P.u1);
        PR(OP.fma, P.bB, P.dr, P.u1, P.u2);
        PR(OP.add, P.dr, 0, P.dr, P.d2);
        PR(OP.fma, P.d2, P.di, P.u2, P.ndi);
        PR(OP.add, P.bZr, 0, P.ndr, P.fr);
        PR(OP.add, P.bZi, 0, P.ndi, P.fi_);
        PR(OP.mul, P.fr, P.fr, 0, P.pp);
        PR(OP.fma, P.fi_, P.fi_, P.pp, P.mm);
        {
          let f = C.runN(OP.cmple, pf.fmt, RND.rne, P.bGT, P.mm, 0, P.glok, live);
          f |= C.runN(OP.cmple, pf.fmt, RND.rne, P.mm, P.bFOUR, 0, P.escok, live);
          if (f) fail("a pixel comparison raised a flag");
        }
        PR(OP.min, P.glok, P.escok, 0, P.ok);
        PR(OP.select, P.bZERO, P.bONE, P.glok, P.glnow);
        PR(OP.min, P.live, P.glnow, 0, P.glev);
        PR(OP.max, P.glit, P.glev, 0, P.glit);
        PR(OP.select, P.bK, P.iter, P.live, P.iter);
        PR(OP.select, P.ndr, P.dr, P.live, P.dr);
        PR(OP.select, P.ndi, P.di, P.live, P.di);
        PR(OP.min, P.live, P.ok, 0, P.live);
        pixelWork += live;

        if ((kk & 31) === 31) {
          const G = F();
          let keep = 0;
          for (let i = 0; i < live; i++) {
            if (G[(P.live >> 3) + i] === 0.0) {
              const gi = P.idx[i];
              pixIter[gi] = G[(P.iter >> 3) + i] | 0;
              pixKind[gi] = G[(P.glit >> 3) + i] !== 0.0 ? 1 : 0;
              continue;
            }
            if (keep !== i) {
              for (const p of [P.dcr, P.dci, P.dr, P.di, P.live, P.glit, P.iter])
                G[(p >> 3) + keep] = G[(p >> 3) + i];
              P.idx[keep] = P.idx[i];
            }
            keep++;
          }
          live = keep;
        }
      }
      const G = F();
      for (let i = 0; i < live; i++) {
        const gi = P.idx[i];
        pixIter[gi] = G[(P.iter >> 3) + i] | 0;
        pixKind[gi] = G[(P.glit >> 3) + i] !== 0.0 ? 1
                    : (G[(P.live >> 3) + i] !== 0.0 ? 2 : 0);
      }
    }

    let phase = "orbit", finished = false;
    let nEsc = 0, nGl = 0, nInt = 0, escMin = 0xffffffff, escMax = 0;
    const ORBIT_CHUNK = 64;

    /** |c_fmt - c_fp256| in pixels: the reference's own representation
     *  error, which is what decides whether a format can serve a zoom
     *  at all. zoom.c's centre_error_pixels, run here as presentation
     *  (save/restore) rather than inside the timed run. */
    function centreErrorPixels() {
      return C.present(() => {
        const wide = C.malloc(f256.esz), diff = C.malloc(f256.esz);
        const adiff = C.malloc(f256.esz), q = C.malloc(f256.esz);
        const px = C.malloc(f256.esz);
        if (fi.fmt === f256.fmt) C.copy(wide, cr, f256.esz);
        else C.convert(fi.fmt, f256.fmt, RND.rne, cr, wide, 1);
        C.runN(OP.sub, f256.fmt, RND.rne, wide, 0, c256r, diff, 1);
        C.runN(OP.abs, f256.fmt, RND.rne, diff, 0, 0, adiff, 1);
        valPow2(C, f256, 1 - zoomExp - sh, px);
        C.divN(f256.fmt, RND.rne, adiff, px, q, 1);
        return C.toDecimal(f256.fmt, RND.rne, q, 6).text;
      });
    }

    const job = {
      title: "zoom", format: fi,
      step() {
        if (finished) return { done: true };
        if (phase === "orbit") {
          const target = Math.min(k + ORBIT_CHUNK, refIters);
          while (k < target && !escapedAt) {
            if (!orbitIter()) { escapedAt = k; break; }
            k++;
            C.copy(orbR + k * esz, zr, esz);
            C.copy(orbI + k * esz, zi, esz);
            chain.absorb(`${k} ${decInteger0(C, fi, orbR + k * esz)} ` +
                         `${decInteger0(C, fi, orbI + k * esz)}`);
            if ((k & 7) === 0 || k < 64)
              orbitPlot.push([C.showDouble(fi.fmt, orbR + k * esz),
                              C.showDouble(fi.fmt, orbI + k * esz)]);
          }
          if (k >= refIters || escapedAt) {
            flagsRef = flagsSeen;
            preparePixels();
            phase = "pixels";
          }
          return { done: false, phase: "orbit",
                   progress: k / refIters, k,
                   emitted: { orbit: orbitPlot.length } };
        }
        // pixels, one chunk per step
        const n = Math.min(P.cap, npix - pixBase);
        const F = C.f64();
        for (let i = 0; i < n; i++) {
          const gi = pixBase + i;
          const ix = gi % width, iy = (gi / width) | 0;
          F[(P.dcr >> 3) + i] = (2 * ix + 1 - width - 2 * (cfg.refOffset | 0)) * P.pixd;
          F[(P.dci >> 3) + i] = (2 * iy + 1 - width) * P.pixd;
          P.idx[i] = gi;
        }
        pixelChunk(n);
        pixBase += n;
        const rowsDone = Math.floor(pixBase / width);
        if (pixBase >= npix) {
          for (let i = 0; i < npix; i++) {
            if (pixKind[i] < 0) fail("a pixel record was never filled");
            if (pixKind[i] === 0) {
              nEsc++;
              if (pixIter[i] < escMin) escMin = pixIter[i];
              if (pixIter[i] > escMax) escMax = pixIter[i];
            } else if (pixKind[i] === 1) nGl++;
            else nInt++;
          }
          for (let i = 0; i < npix; i++)
            pixchain.absorb(`${i} ${pixIter[i]} ` +
                            (pixKind[i] === 0 ? "esc" : (pixKind[i] === 1 ? "glitch" : "interior")));
          finished = true;
        }
        return { done: finished, phase: "pixels",
                 progress: pixBase / npix,
                 emitted: { rowsDone, iter: pixIter, kind: pixKind,
                            from: pixBase - n, to: pixBase } };
      },
      pixels: () => ({ iter: pixIter, kind: pixKind, width }),
      result() {
        return {
          chains: { orbit: chain.hex(), pixels: pixchain.hex() },
          chain: pixchain.hex(),
          stats: {
            format: fi.name, prec: fi.prec, pixelFormat: pf.name,
            width, zoomExp, period, refIters: k, escapedAt,
            pixelIters: maxk, glitchBits,
            centre: C.showDecimal(f256.fmt, c256r, 40),
            centreInFormat: C.showDecimal(fi.fmt, cr, 40),
            centreErrorPixels: centreErrorPixels(),
            pixscale: C.showDecimal(f256.fmt, pixscale, 6),
            escaped: nEsc, glitched: nGl, interior: nInt,
            escMin: nEsc ? escMin : 0, escMax,
            pixelWork,
            flags: flagsSeen, flagText: flagText(flagsSeen),
            flagsRef,
            status: C.saveAllFlags(C.dev) >>> 0,
            calls: C.calls, elemOps: C.elemOps,
          },
          orbitPlot,
          pixels: { iter: pixIter, kind: pixKind, width },
          work: pixelWork,
          workUnit: "fp64 pixel-iterations",
        };
      },
    };
    return job;
  }

  // zoom.c's val_to_dec is the plain exact conversion (no integer
  // reshaping) - orbit points are not integers.
  function decInteger0(C, fi, ptr) {
    return C.toDecimal(fi.fmt, RND.rne, ptr, 0).text;
  }

  // =================================================================
  // Panel 3: cft-orbits --engine loop (the tool's default engine)
  //
  // Kepler, Stormer-Verlet, 1/r^3 from cft_sqrt and cft_div - the
  // correctly rounded route. One library call per operation per
  // ensemble, exactly as opN/sqrtN/divN issue them.
  // =================================================================
  function orbitsJob(C, cfg) {
    const fi = measureFormat(C, cfg.format);
    const esz = fi.esz, M = cfg.members;
    const ncomp = 2, nL = 1;
    const nsteps0 = cfg.periods * cfg.stepsPerPeriod;
    let stride = cfg.sampleEvery || cfg.stepsPerPeriod;
    if (stride > nsteps0) stride = nsteps0;
    const nsamples = Math.floor(nsteps0 / stride);
    if (!nsamples) fail("sample-every is larger than the run");
    const nsteps = nsamples * stride;

    const arr = (n) => C.malloc(n * esz);
    const q = arr(ncomp * M), v = arr(ncomp * M);
    const x = arr(M), y = arr(M), w = arr(M), g = arr(M);
    const t1 = arr(M), t2 = arr(M);
    const H0 = arr(M), Hd = arr(M), dHmax = arr(M);
    const L0 = arr(M), Ld = arr(M), dLmax = arr(M);
    const CQ = (c) => q + c * M * esz;
    const CV = (c) => v + c * M * esz;

    const one = C.malloc(esz), mone = C.malloc(esz), two = C.malloc(esz);
    const half = C.malloc(esz), mhalf = C.malloc(esz), h = C.malloc(esz);
    const tmp = C.malloc(esz);
    C.fromI64(fi.fmt, RND.rne, 1, one);
    C.fromI64(fi.fmt, RND.rne, -1, mone);
    C.fromI64(fi.fmt, RND.rne, 2, two);
    valPow2(C, fi, -1, half);
    C.runN(OP.neg, fi.fmt, RND.rne, half, 0, 0, mhalf, 1);
    const cHalf = arr(M), cMu = arr(M), cHd = arr(M), cMg = arr(M);
    bcast(C, fi, cHalf, half, M);

    // h = 2 pi / steps_per_period, with pi = acos(-1) from the library.
    {
      const pi = C.malloc(esz), twopi = C.malloc(esz), nsp = C.malloc(esz);
      C.acos(fi.fmt, RND.rne, mone, pi);
      C.runN(OP.mul, fi.fmt, RND.rne, pi, two, 0, twopi, 1);
      C.fromI64(fi.fmt, RND.rne, cfg.stepsPerPeriod, nsp);
      C.divN(fi.fmt, RND.rne, twopi, nsp, h, 1);
    }
    // mu = 1; leapfrog weight 1; hd = h/2; mg = -(h mu)
    C.fromI64(fi.fmt, RND.rne, 1, tmp);
    bcast(C, fi, cMu, tmp, M);
    {
      const hs = C.malloc(esz), hd = C.malloc(esz), t = C.malloc(esz);
      C.runN(OP.mul, fi.fmt, RND.rne, one, h, 0, hs, 1);
      C.runN(OP.mul, fi.fmt, RND.rne, hs, half, 0, hd, 1);
      bcast(C, fi, cHd, hd, M);
      C.runN(OP.mul, fi.fmt, RND.rne, hs, tmp, 0, t, 1);
      C.runN(OP.neg, fi.fmt, RND.rne, t, 0, 0, t, 1);
      bcast(C, fi, cMg, t, M);
    }

    // ---- the initial ensemble ----
    {
      const num = C.malloc(esz), den = C.malloc(esz);
      const q0 = C.malloc(esz), v1 = C.malloc(esz), tt = C.malloc(esz);
      const ECC_NUM = 3, ECC_DEN = 4;
      C.fromI64(fi.fmt, RND.rne, ECC_DEN - ECC_NUM, num);
      C.fromI64(fi.fmt, RND.rne, ECC_DEN, den);
      const f = C.divN(fi.fmt, RND.rne, num, den, q0, 1);
      if (f & FLAG.inexact) fail("1 - e is not exact");
      C.fromI64(fi.fmt, RND.rne, ECC_DEN + ECC_NUM, num);
      C.fromI64(fi.fmt, RND.rne, ECC_DEN - ECC_NUM, den);
      C.divN(fi.fmt, RND.rne, num, den, tt, 1);
      C.sqrtN(fi.fmt, RND.rne, tt, v1, 1);
      const bits = C.malloc(esz);
      for (let m = 0; m < M; m++) {
        C.copy(CQ(0) + m * esz, q0, esz);
        C.zero(CQ(1) + m * esz, esz);
        C.zero(CV(0) + m * esz, esz);
        C.copy(CV(1) + m * esz, v1, esz);
        if (m) {
          // the ladder: nextUp applied `rung` times, as ONE integer add
          // on the encoding - exact, flagless, identical everywhere.
          const rung = Math.floor((m + 1) / 2) * cfg.spread;
          const slot = (m & 1) ? CQ(0) + m * esz : CV(1) + m * esz;
          bitsFromU64(C, fi, rung, bits);
          C.runN(OP.iadd, fi.fmt, RND.rne, slot, bits, 0, slot, 1);
        }
      }
    }
    const q0save = C.malloc(ncomp * M * esz), v0save = C.malloc(ncomp * M * esz);
    C.copy(q0save, q, ncomp * M * esz);
    C.copy(v0save, v, ncomp * M * esz);

    C.lowerFlags(C.dev, C.flagsAllMask);
    C.calls = 0; C.elemOps = 0;

    let flagsSeen = 0;
    function note(f) {
      flagsSeen |= f;
      if (f & (FLAG.invalid | FLAG.divbyzero | FLAG.overflow | FLAG.underflow))
        fail(`this workload can only ever raise inexact; got 0x${f.toString(16)}`);
      return f;
    }
    const opN = (op, a, b, c, d) => note(C.runN(op, fi.fmt, RND.rne, a, b, c, d, M));
    const sqN = (a, d) => note(C.sqrtN(fi.fmt, RND.rne, a, d, M));
    const dvN = (a, b, d) => note(C.divN(fi.fmt, RND.rne, a, b, d, M));

    function oneStep() {
      // drift; kick; drift  (leapfrog: one substep)
      opN(OP.fma, cHd, CV(0), CQ(0), CQ(0));
      opN(OP.fma, cHd, CV(1), CQ(1), CQ(1));
      opN(OP.mul, CQ(1), CQ(1), 0, w);
      opN(OP.fma, CQ(0), CQ(0), w, x);
      sqN(x, y);                       // s = sqrt(r^2)
      opN(OP.mul, x, y, 0, w);         // w = r^2 * s
      dvN(cMg, w, g);                  // g = -(h mu)/r^3
      opN(OP.fma, g, CQ(0), CV(0), CV(0));
      opN(OP.fma, g, CQ(1), CV(1), CV(1));
      opN(OP.fma, cHd, CV(0), CQ(0), CQ(0));
      opN(OP.fma, cHd, CV(1), CQ(1), CQ(1));
    }

    function invariants(qq, vv, Hp, Lp) {
      const Q = (c) => qq + c * M * esz, V = (c) => vv + c * M * esz;
      opN(OP.mul, V(1), V(1), 0, w);
      opN(OP.fma, V(0), V(0), w, t1);
      opN(OP.mul, t1, cHalf, 0, t1);
      opN(OP.mul, Q(1), Q(1), 0, w);
      opN(OP.fma, Q(0), Q(0), w, x);
      sqN(x, y);
      dvN(cMu, y, t2);
      opN(OP.sub, t1, 0, t2, Hp);
      opN(OP.mul, Q(1), V(0), 0, w);
      opN(OP.neg, w, 0, 0, w);
      opN(OP.fma, Q(0), V(1), w, Lp);
    }

    const chain = new Chain();
    const samples = [];
    let sample = 0, stepNo = 0;

    function emitSample(s, stepIdx) {
      invariants(q, v, Hd, Ld);
      if (s === 0) {
        C.copy(H0, Hd, M * esz);
        C.copy(L0, Ld, M * esz);
      } else {
        opN(OP.sub, Hd, 0, H0, t1);
        opN(OP.abs, t1, 0, 0, t1);
        opN(OP.max, dHmax, t1, 0, dHmax);
        opN(OP.sub, Ld, 0, L0, t1);
        opN(OP.abs, t1, 0, 0, t1);
        opN(OP.max, dLmax, t1, 0, dLmax);
      }
      const rows = [];
      for (let m = 0; m < M; m++) {
        const parts = [String(s), String(stepIdx), String(m)];
        for (let c = 0; c < ncomp; c++)
          parts.push(C.toDecimal(fi.fmt, RND.rne, q + (c * M + m) * esz, 0).text);
        for (let c = 0; c < ncomp; c++)
          parts.push(C.toDecimal(fi.fmt, RND.rne, v + (c * M + m) * esz, 0).text);
        parts.push(C.toDecimal(fi.fmt, RND.rne, Hd + m * esz, 0).text);
        parts.push(C.toDecimal(fi.fmt, RND.rne, Ld + m * esz, 0).text);
        chain.absorb(parts.join(" "));
        rows.push(m);
      }
      // presentation: positions and the two drifts, as doubles
      const pos = [], dH = [], dL = [];
      for (let m = 0; m < M; m++) {
        pos.push([C.showDouble(fi.fmt, q + (0 * M + m) * esz),
                  C.showDouble(fi.fmt, q + (1 * M + m) * esz)]);
        const saved = C.saveAllFlags(C.dev) >>> 0;
        C.runN(OP.sub, fi.fmt, RND.rne, Hd + m * esz, 0, H0 + m * esz, t1, 1);
        dH.push(C.showDouble(fi.fmt, t1));
        C.runN(OP.sub, fi.fmt, RND.rne, Ld + m * esz, 0, L0 + m * esz, t1, 1);
        dL.push(C.showDouble(fi.fmt, t1));
        C.restoreFlags(C.dev, saved, C.flagsAllMask);
      }
      const rec = { sample: s, step: stepIdx, pos, dH, dL };
      samples.push(rec);
      return rec;
    }

    let started = false, finished = false;
    const job = {
      title: "orbits", format: fi, nsamples, nsteps, stride, members: M,
      step() {
        if (finished) return { done: true };
        if (!started) {
          started = true;
          const rec = emitSample(0, 0);
          return { done: false, progress: 0, emitted: { sample: rec } };
        }
        const upto = (sample + 1) * stride;
        while (stepNo < upto) { oneStep(); stepNo++; }
        sample++;
        const rec = emitSample(sample, stepNo);
        if (sample >= nsamples) finished = true;
        return { done: finished, progress: sample / nsamples,
                 emitted: { sample: rec } };
      },
      result() {
        const maxOf = (p) => {
          let best = -Infinity;
          for (let m = 0; m < M; m++) best = Math.max(best, C.showDouble(fi.fmt, p + m * esz));
          return best;
        };
        return {
          chain: chain.hex(),
          chains: { chain: chain.hex() },
          stats: {
            format: fi.name, prec: fi.prec, members: M, nsteps, nsamples,
            stride, periods: cfg.periods, stepsPerPeriod: cfg.stepsPerPeriod,
            spread: cfg.spread,
            h: C.showDecimal(fi.fmt, h, 12),
            dHmax: maxOf(dHmax), dLmax: maxOf(dLmax),
            H0: C.showDouble(fi.fmt, H0), L0: C.showDouble(fi.fmt, L0),
            flags: flagsSeen, flagText: flagText(flagsSeen),
            status: C.saveAllFlags(C.dev) >>> 0,
            calls: C.calls, elemOps: C.elemOps,
          },
          samples,
          work: nsteps * M,
          workUnit: "element-steps",
        };
      },
    };
    return job;
  }

  // =================================================================
  // Panel 4: cft-enclose --engine loop
  //
  // All three kernels, in the tool's own item order: series, then dot,
  // then Horner. Every bound is a directed rounding of the library's,
  // and the width is hi - lo under roundTowardPositive so the number
  // reported is itself an upper bound on the true width.
  // =================================================================
  const KERNEL_NAME = ["series", "dot", "horner"];

  function dotMantissaBits(fi) {
    const mw = Math.floor(fi.prec / 2);
    return mw > 11 ? 11 : mw;
  }

  function encloseJob(C, cfg) {
    const fi = measureFormat(C, cfg.format);
    const esz = fi.esz;
    const points = cfg.points, degree = cfg.degree;
    const condLevels = cfg.condLevels, condMax = cfg.condMax;
    const rows = cfg.rows, dotM = cfg.dotM, dotTop = cfg.dotTop;
    const batch = cfg.batch;
    if (!points || (points & (points - 1))) fail("points must be a power of two");
    if (degree < 0 || ((degree + 1) % 8) !== 0)
      fail("degree must make (degree + 1) a multiple of 8");
    const mw = dotMantissaBits(fi);
    if (2 * mw > fi.prec) fail("this format is too narrow for an exact product stage");

    const items = [points + 1, 1 + condLevels + rows, points + 1];
    const base = [0, items[0], items[0] + items[1]];
    const total = items[0] + items[1] + items[2];

    const arr = (n) => C.malloc(n * esz);
    const zero = C.malloc(esz), one = C.malloc(esz);
    C.fromI64(fi.fmt, RND.rne, 0, zero);
    C.fromI64(fi.fmt, RND.rne, 1, one);
    const t1 = arr(batch), t2 = arr(batch), kv = arr(batch);
    const sx = arr(batch), stlo = arr(batch), sthi = arr(batch);
    const sslo = arr(batch), sshi = arr(batch);
    const hx = arr(batch), hlo = arr(batch), hhi = arr(batch);
    const hnn = arr(batch), hma = arr(batch), hmb = arr(batch);
    const hbclo = arr(batch), hbchi = arr(batch), hzero = arr(batch);
    bcast(C, fi, hzero, zero, batch);
    const dotCap = 4 * dotM + 2;
    const dx = arr(dotCap), dy = arr(dotCap);
    const clo = arr(degree + 1), chi = arr(degree + 1);
    const scr = C.malloc(esz), wv = C.malloc(esz);
    const dlo = C.malloc(esz), dhi = C.malloc(esz);
    // The widest width per kernel is kept as an ENCODING and compared
    // with the library's own CMPLT, not as a double: at fp256 a width
    // can be far below anything binary64 can order.
    const maxwBuf = [C.malloc(esz), C.malloc(esz), C.malloc(esz)];

    function valScaleOk(v, e, out) {
      const f = C.scaleb(fi.fmt, RND.rne, v, e, out, 1);
      return f === 0;
    }
    function valScale(v, e, out) {
      if (!valScaleOk(v, e, out))
        fail("a scaled constant this workload needs is not exact in this format");
    }
    function valFromI64(v, out) {
      const f = C.fromI64(fi.fmt, RND.rne, v, out);
      if (f & FLAG.inexact)
        fail("an integer this workload needs is not exact in this format");
    }
    function cmpOp(op, a, b) {
      C.runN(op, fi.fmt, RND.rne, a, b, 0, scr, 1);
      return !C.isZero(scr, esz);
    }
    const vlt = (a, b) => cmpOp(OP.cmplt, a, b);
    const vle = (a, b) => cmpOp(OP.cmple, a, b);

    // dot_representable, asked before any work
    {
      const v = C.malloc(esz), t = C.malloc(esz);
      valFromI64(1, v);
      const topx = dotTop - mw;
      const lowx = dotTop - 2 * mw - condMax;
      if (!valScaleOk(v, topx + mw, t) || !valScaleOk(v, lowx, t))
        fail(`${fi.name} cannot hold the dot kernel's condition ladder ` +
             `exactly: the spread that defeats a 237-bit significand puts ` +
             `the smallest element below this format's smallest normal, or ` +
             `the largest product above its largest finite`);
    }

    // series_terms: the smallest N whose tail bound falls below 2^-(p+1),
    // found by RUNNING the recurrence - the format's answer, not a table's.
    let terms = 0;
    {
      const saved = C.saveAllFlags(C.dev) >>> 0;
      const t = C.malloc(esz), kk = C.malloc(esz);
      const tail = C.malloc(esz), lim = C.malloc(esz);
      valFromI64(1, t);
      valPow2(C, fi, -fi.prec - 1, lim);
      for (let k = 1; k < 4 * fi.prec; k++) {
        valFromI64(k, kk);
        C.divN(fi.fmt, RND.rup, t, kk, t, 1);
        C.divN(fi.fmt, RND.rup, t, kk, tail, 1);
        if (vlt(tail, lim)) { terms = k; break; }
      }
      if (!terms) fail("the series never reached its tail bound");
      C.restoreFlags(C.dev, saved, C.flagsAllMask);
    }

    // horner_coeffs: c_0 = 1; c_k = c_{k-1}/k, RDN for the lower end and
    // RUP for the upper, so 1/k! is inside [clo_k, chi_k] by induction.
    let flagsSeen = 0;
    function expect(f, where) {
      if (f & (FLAG.invalid | FLAG.divbyzero | FLAG.overflow))
        fail(`${where} raised 0x${f.toString(16)}`);
      return f;
    }
    {
      let f = 0;
      valFromI64(1, clo);
      valFromI64(1, chi);
      const kk = C.malloc(esz);
      for (let k = 1; k <= degree; k++) {
        valFromI64(k, kk);
        f |= C.divN(fi.fmt, RND.rdn, clo + (k - 1) * esz, kk, clo + k * esz, 1);
        f |= C.divN(fi.fmt, RND.rup, chi + (k - 1) * esz, kk, chi + k * esz, 1);
      }
      expect(f, "a coefficient enclosure");
    }

    C.lowerFlags(C.dev, C.flagsAllMask);
    C.calls = 0; C.elemOps = 0;
    flagsSeen = 0;

    const chain = new Chain();
    const records = [];
    const stats = {
      n: [0, 0, 0], nexact: [0, 0, 0],
      maxw: [null, null, null], maxwIdx: [0, 0, 0],
      loSideExact: 0, hiSideExact: 0, straddle: 0,
      eLo: null, eHi: null,
    };

    function emit(kernel, idx, lo, hi, label) {
      if (!vle(lo, hi))
        fail("an enclosure came back with its ends the wrong way round");
      const f = C.runN(OP.sub, fi.fmt, RND.rup, hi, 0, lo, wv, 1);
      expect(f, "the width");
      flagsSeen |= f;
      const rec = {
        kernel, idx,
        lo: C.toHex(fi.fmt, lo), hi: C.toHex(fi.fmt, hi), w: C.toHex(fi.fmt, wv),
        exact: C.same(lo, hi, esz),
        width: C.showDouble(fi.fmt, wv),
        loD: C.showDouble(fi.fmt, lo), hiD: C.showDouble(fi.fmt, hi),
        label,
      };
      stats.n[kernel]++;
      if (rec.exact) stats.nexact[kernel]++;
      if (stats.maxw[kernel] === null || vlt(maxwBuf[kernel], wv)) {
        C.copy(maxwBuf[kernel], wv, esz);
        stats.maxw[kernel] = rec.width;
        stats.maxwIdx[kernel] = idx;
      }
      if (kernel === 1 && vle(lo, zero) && vle(zero, hi)) {
        stats.straddle++;
        rec.straddles = true;
      }
      if (kernel === 0 && idx === points) {
        stats.eLo = rec.lo; stats.eHi = rec.hi;
      }
      chain.absorb(`${KERNEL_NAME[kernel]} ${idx} ${rec.lo} ${rec.hi} ` +
                   `${rec.w} ${rec.exact ? "exact" : "strict"}`);
      records.push(rec);
      return rec;
    }

    // ---- the series ----
    let shBits = 0; { let p = points; while ((1 << shBits) !== p) shBits++; }
    function seriesPoint(j, out) {
      const v = C.tmp(1);
      valFromI64(j, v);
      if (j === 0) C.copy(out, v, esz);
      else valScale(v, -shBits, out);
    }
    function runSeries(baseIdx, n) {
      for (let i = 0; i < n; i++) {
        seriesPoint(baseIdx + i, sx + i * esz);
        C.copy(stlo + i * esz, one, esz);
        C.copy(sthi + i * esz, one, esz);
        C.copy(sslo + i * esz, one, esz);
        C.copy(sshi + i * esz, one, esz);
      }
      const kb = C.tmp(2);
      for (let term = 1; term <= terms; term++) {
        let f = 0;
        valFromI64(term, kb);
        bcast(C, fi, kv, kb, n);
        f |= C.runN(OP.mul, fi.fmt, RND.rdn, stlo, sx, 0, t1, n);
        f |= C.divN(fi.fmt, RND.rdn, t1, kv, stlo, n);
        f |= C.runN(OP.mul, fi.fmt, RND.rup, sthi, sx, 0, t2, n);
        f |= C.divN(fi.fmt, RND.rup, t2, kv, sthi, n);
        f |= C.runN(OP.add, fi.fmt, RND.rdn, sslo, 0, stlo, sslo, n);
        f |= C.runN(OP.add, fi.fmt, RND.rup, sshi, 0, sthi, sshi, n);
        expect(f, "a series term");
        flagsSeen |= f;
      }
      let f = 0;
      valFromI64(terms, kb);
      bcast(C, fi, kv, kb, n);
      f |= C.divN(fi.fmt, RND.rup, sthi, kv, t2, n);
      f |= C.runN(OP.add, fi.fmt, RND.rup, sshi, 0, t2, sshi, n);
      expect(f, "the series tail bound");
      flagsSeen |= f;
      const out = [];
      for (let i = 0; i < n; i++)
        out.push(emit(0, baseIdx + i, sslo + i * esz, sshi + i * esz,
                      C.showDecimal(fi.fmt, sx + i * esz, 12)));
      return out;
    }

    // ---- the dot cases ----
    function dotSpread(rung) {
      if (condLevels <= 1) return condMax;
      return Math.floor(rung * condMax / (condLevels - 1));
    }
    function dotCase(which) {
      const bv = C.tmp(3);
      if (which === 0) {
        const sm = mw >> 1, len = 4 * dotM;
        const gg = new Rng("cft-enclose dot exact v1", 0);
        for (let i = 0; i < len; i++) {
          let a = Number(gg.u64() % BigInt(1 << sm)) + 1;
          let b = Number(gg.u64() % BigInt(1 << sm)) + 1;
          if (gg.u64() & 1n) a = -a;
          if (gg.u64() & 1n) b = -b;
          valFromI64(a, dx + i * esz);
          valFromI64(b, dy + i * esz);
        }
        return { len, name: "exact", spread: -1 };
      }
      let spread, name, gg;
      if (which <= condLevels) {
        spread = dotSpread(which - 1);
        name = `cancel-spread${spread}`;
        gg = new Rng("cft-enclose dot cancel v1", which);
      } else {
        spread = condMax;
        name = `matvec-row${which - 1 - condLevels}`;
        gg = new Rng("cft-enclose dot matvec v1", which);
      }
      const len = 2 * dotM + 1;
      const TOP = 1n << BigInt(mw), HALF = 1n << BigInt(mw - 1);
      for (let i = 0; i < dotM; i++) {
        const a = (gg.u64() % TOP) | HALF | 1n;
        const b = (gg.u64() % TOP) | HALF | 1n;
        const ee = (i === 0) ? 0 : (i === 1 ? spread
                                            : Number(gg.u64() % BigInt(spread + 1)));
        valFromI64(a, dx + i * esz);
        valFromI64(b, bv);
        valScale(bv, dotTop - 2 * mw - ee, dy + i * esz);
        C.copy(dx + (dotM + i) * esz, dx + i * esz, esz);
        C.runN(OP.neg, fi.fmt, RND.rne, dy + i * esz, 0, 0, dy + (dotM + i) * esz, 1);
      }
      valFromI64(1, dx + 2 * dotM * esz);
      valFromI64(1, dy + 2 * dotM * esz);
      const swap = C.tmp(4);
      for (let i = len; i > 1; i--) {
        const j = Number(gg.u64() % BigInt(i));
        for (const p of [dx, dy]) {
          C.copy(swap, p + (i - 1) * esz, esz);
          C.copy(p + (i - 1) * esz, p + j * esz, esz);
          C.copy(p + j * esz, swap, esz);
        }
      }
      return { len, name, spread };
    }
    function runDot(baseIdx, n) {
      const out = [];
      for (let i = 0; i < n; i++) {
        const cse = dotCase(baseIdx + i);
        const flo = C.reduceN(OP.dot, fi.fmt, RND.rdn, dx, dy, dlo, cse.len);
        const fhi = C.reduceN(OP.dot, fi.fmt, RND.rup, dx, dy, dhi, cse.len);
        expect(flo | fhi, "a dot product");
        flagsSeen |= flo | fhi;
        if (!((flo | fhi) & FLAG.inexact) && !C.same(dlo, dhi, esz))
          fail("a dot product raised no inexact and still returned two different bounds");
        if (!(flo & FLAG.inexact)) stats.loSideExact++;
        if (!(fhi & FLAG.inexact)) stats.hiSideExact++;
        const rec = emit(1, baseIdx + i, dlo, dhi, cse.name);
        rec.len = cse.len;
        rec.spread = cse.spread;
        out.push(rec);
      }
      return out;
    }

    // ---- interval Horner ----
    function hornerPoint(j, out) {
      const v = C.tmp(5), t = C.tmp(6);
      valFromI64(j, v);
      if (j === 0) C.copy(t, v, esz);
      else valScale(v, 1 - shBits, t);
      const f = C.runN(OP.sub, fi.fmt, RND.rne, t, 0, one, out, 1);
      if (f) fail("a Horner evaluation point was not exact");
    }
    function runHorner(baseIdx, n) {
      for (let i = 0; i < n; i++) hornerPoint(baseIdx + i, hx + i * esz);
      C.zero(hlo, n * esz);
      C.zero(hhi, n * esz);
      let f = C.runN(OP.cmple, fi.fmt, RND.rne, hzero, hx, 0, hnn, n);
      for (let k = degree; k >= 0; k--) {
        bcast(C, fi, hbclo, clo + k * esz, n);
        bcast(C, fi, hbchi, chi + k * esz, n);
        f |= C.runN(OP.select, fi.fmt, RND.rne, hlo, hhi, hnn, hma, n);
        f |= C.runN(OP.select, fi.fmt, RND.rne, hhi, hlo, hnn, hmb, n);
        f |= C.runN(OP.fma, fi.fmt, RND.rdn, hx, hma, hbclo, hlo, n);
        f |= C.runN(OP.fma, fi.fmt, RND.rup, hx, hmb, hbchi, hhi, n);
      }
      expect(f, "a Horner step");
      flagsSeen |= f;
      if (!(f & FLAG.inexact))
        for (let i = 0; i < n; i++)
          if (!C.same(hlo + i * esz, hhi + i * esz, esz))
            fail("a Horner batch raised no inexact and still produced a nonzero width");
      const out = [];
      for (let i = 0; i < n; i++)
        out.push(emit(2, baseIdx + i, hlo + i * esz, hhi + i * esz,
                      C.showDecimal(fi.fmt, hx + i * esz, 12)));
      return out;
    }

    let cursor = 0, finished = false;
    const job = {
      title: "enclose", format: fi, total,
      step() {
        if (finished) return { done: true };
        let kern = 0, local = 0;
        for (let kk = 0; kk < 3; kk++)
          if (items[kk] && cursor >= base[kk] && cursor < base[kk] + items[kk]) {
            kern = kk; local = cursor - base[kk];
          }
        const room = items[kern] - local;
        const n = Math.min(batch, room);
        let out;
        if (kern === 0) out = runSeries(local, n);
        else if (kern === 1) out = runDot(local, n);
        else out = runHorner(local, n);
        cursor += n;
        if (cursor >= total) finished = true;
        return { done: finished, progress: cursor / total,
                 emitted: { records: out, kernel: KERNEL_NAME[kern] } };
      },
      result() {
        return {
          chain: chain.hex(),
          chains: { chain: chain.hex() },
          stats: {
            format: fi.name, prec: fi.prec, terms, degree, points,
            condMax, condLevels, rows, dotM, dotTop, mw,
            items: total,
            n: stats.n, nexact: stats.nexact,
            maxw: stats.maxw, maxwIdx: stats.maxwIdx,
            straddle: stats.straddle,
            loSideExact: stats.loSideExact, hiSideExact: stats.hiSideExact,
            eLo: stats.eLo, eHi: stats.eHi,
            flags: flagsSeen, flagText: flagText(flagsSeen),
            status: C.saveAllFlags(C.dev) >>> 0,
            calls: C.calls, elemOps: C.elemOps,
          },
          records,
          work: total,
          workUnit: "enclosures",
        };
      },
    };
    return job;
  }

  // =================================================================
  // Panel 5: cft-mersenne --engine loop
  //
  // Lucas-Lehmer with fp256 as an exact wide-integer multiplier. The
  // limb geometry is DERIVED from the format's own p, exactly as
  // geometry_derive does; the carry split is the fifteen cft_run
  // passes of the loop route; the convolution is 2L-1 CFT_DOT
  // reductions whose clean flag word is the exactness certificate.
  // =================================================================
  function geomOk(p, P, b, L, d) {
    if (b < 2 || L < 2 || d < 0 || d >= b) return false;
    if (L * b - P !== d) return false;
    if (b < 2 || 2 * b > p) return false;
    const room = p - 2 * b;
    if (room < 40 && L > Math.pow(2, room)) return false;
    if (d + 2 > b) return false;
    return true;
  }
  function geometryDerive(fi, P) {
    for (let L = 2; L <= P; L++) {
      const b = Math.ceil(P / L);
      if (Math.ceil(P / b) !== L) continue;
      const d = L * b - P;
      if (geomOk(fi.prec, P, b, L, d)) return { exp: P, b, L, d };
    }
    return null;
  }

  function mersenneJob(C, cfg) {
    const fi = measureFormat(C, cfg.format);
    const esz = fi.esz;
    const exps = cfg.exponents.slice();
    for (const P of exps) if (P < 3) fail("a Lucas-Lehmer exponent must be at least 3");

    C.lowerFlags(C.dev, C.flagsAllMask);
    C.calls = 0; C.elemOps = 0;

    const chain = new Chain();
    const records = [];
    let flagsSeen = 0, squaringsTotal = 0, passesTotal = 0, limbProducts = 0;

    function expectClean(f, what) {
      flagsSeen |= f;
      if (f && C.flagsReadable)
        fail(`${what} raised 0x${f.toString(16)}; every operation of a ` +
             `Lucas-Lehmer step must be exact`);
    }

    let G = null, S = null;      // geometry and engine state, per exponent
    let at = 0, stepK = 0, need = 0;
    const trace = [];

    function engineSetup(P) {
      G = geometryDerive(fi, P);
      if (!G)
        fail(`P = ${P} has no limb width ${fi.name} holds exactly (p = ${fi.prec})`);
      const cap = 2 * G.L + 2;
      const arr = () => C.malloc(cap * esz);
      S = {
        cap,
        y: arr(), yrev: arr(), c: arr(), lo: arr(), hi: arr(),
        cs: arr(), wit: arr(), scr: arr(),
        loop: [], invB: arr(), negB: arr(), invT: arr(), negT: arr(),
        invW: arr(), negW: arr(), bpow2d: arr(), bmagic: arr(),
        kminus2: arr(), kmodulus: arr(),
        one: C.malloc(esz), zero: C.malloc(esz), pow2d: C.malloc(esz),
        t1: C.malloc(esz), t2: C.malloc(esz), three: C.malloc(esz),
      };
      for (let i = 0; i < 15; i++) S.loop.push(arr());
      const { b, d, L } = G;
      C.fromI64(fi.fmt, RND.rne, 0, S.zero);
      C.fromI64(fi.fmt, RND.rne, 1, S.one);
      C.fromI64(fi.fmt, RND.rne, 3, S.three);
      valPow2(C, fi, d, S.pow2d);
      bcast(C, fi, S.bpow2d, S.pow2d, cap);
      valPow2(C, fi, fi.prec - 1, S.t1);
      bcast(C, fi, S.bmagic, S.t1, cap);
      const mk = (e, invPtr, negPtr) => {
        valPow2(C, fi, -e, S.t1); bcast(C, fi, invPtr, S.t1, cap);
        valPow2(C, fi, e, S.t1);
        C.runN(OP.neg, fi.fmt, RND.rne, S.t1, 0, 0, S.t2, 1);
        bcast(C, fi, negPtr, S.t2, cap);
      };
      mk(b, S.invB, S.negB);
      mk(b - d, S.invT, S.negT);
      mk(64, S.invW, S.negW);
      bitsFromU64(C, fi, fi.prec - 1, S.t1);            bcast(C, fi, S.loop[8], S.t1, cap);
      bitsFromU64(C, fi, (fi.prec - 1) + fi.bias, S.t1); bcast(C, fi, S.loop[9], S.t1, cap);
      bcast(C, fi, S.loop[10], S.one, cap);
      bcast(C, fi, S.loop[11], S.zero, cap);
      valPow2(C, fi, b, S.t1);
      C.runN(OP.sub, fi.fmt, RND.rne, S.t1, 0, S.one, S.t2, 1);   // 2^b - 1
      for (let i = 0; i < L - 1; i++) {
        C.copy(S.kmodulus + i * esz, S.t2, esz);
        C.copy(S.kminus2 + i * esz, S.t2, esz);
      }
      C.runN(OP.sub, fi.fmt, RND.rne, S.t1, 0, S.three, S.t2, 1); // 2^b - 3
      C.copy(S.kminus2, S.t2, esz);
      valPow2(C, fi, b - d, S.t1);
      C.runN(OP.sub, fi.fmt, RND.rne, S.t1, 0, S.one, S.t2, 1);   // 2^(b-d) - 1
      C.copy(S.kmodulus + (L - 1) * esz, S.t2, esz);
      C.copy(S.kminus2 + (L - 1) * esz, S.t2, esz);
    }

    function runNm(op, a, b, c, d, n, what) {
      expectClean(C.runN(op, fi.fmt, RND.rne, a, b, c, d, n), what);
    }

    // The carry split, loop route: fifteen cft_run passes, in order.
    function split(v, inv, neg, outLo, outHi, outWit, n) {
      const L0 = S.loop;
      const t = L0[0], s = L0[1], h = L0[2], pr = L0[3];
      const lo = L0[4], bb = L0[5], w = L0[6], p2 = L0[7];
      const what = "the carry split (host cft_run loop)";
      const R = (op, A, B, Cc, D) => runNm(op, A, B, Cc, D, n, what);
      R(OP.mul, v, inv, 0, t);
      R(OP.ishr, t, L0[8], 0, s);
      R(OP.isub, L0[9], s, 0, s);
      R(OP.ishr, t, s, 0, h);
      R(OP.ishl, h, s, 0, h);
      R(OP.cmplt, t, L0[10], 0, pr);
      R(OP.select, L0[11], h, pr, h);
      R(OP.fma, h, neg, v, lo);
      R(OP.neg, neg, 0, 0, bb);
      R(OP.fma, h, bb, lo, w);
      R(OP.cmpeq, w, v, 0, w);
      R(OP.cmplt, lo, bb, 0, p2);
      R(OP.min, w, p2, 0, w);
      R(OP.cmple, L0[11], lo, 0, p2);
      R(OP.min, w, p2, 0, w);
      C.copy(outLo, lo, n * esz);
      C.copy(outHi, h, n * esz);
      C.copy(outWit, w, n * esz);
      for (let i = 0; i < n; i++)
        if (!C.same(outWit + i * esz, S.one, esz))
          fail(`the carry split's per-element witness failed at limb ${i}`);
    }

    function allZero(a, n) {
      for (let i = 0; i < n; i++) if (!C.isZero(a + i * esz, esz)) return false;
      return true;
    }

    function carryPass(y, n, wrap) {
      split(y, S.invB, S.negB, S.lo, S.hi, S.wit, n);
      passesTotal++;
      if (allZero(S.hi, n)) return false;
      if (wrap) {
        runNm(OP.mul, S.hi + (n - 1) * esz, S.pow2d, 0, S.cs, 1,
              "the cyclic fold of the top carry");
      } else {
        if (!C.isZero(S.hi + (n - 1) * esz, esz))
          fail("a carry escaped the top limb of a product");
        C.copy(S.cs, S.zero, esz);
      }
      C.copy(S.cs + esz, S.hi, (n - 1) * esz);
      runNm(OP.add, S.lo, 0, S.cs, y, n, "the carry add");
      return true;
    }
    function normalize(y, n, wrap) {
      let guard = 0;
      while (carryPass(y, n, wrap))
        if (++guard > 1000000) fail("carry propagation did not converge");
    }
    function integralityGate(y, n) {
      runNm(OP.add, y, 0, S.bmagic, S.scr, n, "the limb integrality gate");
      runNm(OP.sub, S.scr, 0, S.bmagic, S.scr, n, "the limb integrality gate");
      runNm(OP.cmpeq, S.scr, y, 0, S.scr, n, "the limb integrality gate");
      for (let i = 0; i < n; i++)
        if (!C.same(S.scr + i * esz, S.one, esz))
          fail(`limb ${i} of the residue is not an integer`);
    }
    function canonicalize(y) {
      const L = G.L;
      let guard = 0;
      for (;;) {
        split(y + (L - 1) * esz, S.invT, S.negT, S.lo, S.hi, S.wit, 1);
        passesTotal++;
        if (C.isZero(S.hi, esz)) break;
        C.copy(y + (L - 1) * esz, S.lo, esz);
        runNm(OP.add, y, 0, S.hi, y, 1, "the reduction below 2^P");
        normalize(y, L, 1);
        if (++guard > 1000000) fail("the reduction below 2^P did not converge");
      }
      if (C.same(y, S.kmodulus, L * esz))
        for (let k = 0; k < L; k++) C.copy(y + k * esz, S.zero, esz);
    }

    function llStep() {
      const L = G.L;
      for (let k = 0; k < L; k++)
        C.copy(S.yrev + k * esz, S.y + (L - 1 - k) * esz, esz);
      for (let k = 0; k < 2 * L - 1; k++) {
        const i0 = Math.max(0, k - L + 1), i1 = Math.min(k, L - 1);
        const len = i1 - i0 + 1;
        const f = C.reduceN(OP.dot, fi.fmt, RND.rne, S.y + i0 * esz,
                            S.yrev + (L - 1 - k + i0) * esz,
                            S.c + k * esz, len);
        expectClean(f, "a convolution coefficient (CFT_DOT)");
        limbProducts += len;
      }
      C.copy(S.c + (2 * L - 1) * esz, S.zero, esz);
      runNm(OP.add, S.c, 0, S.kminus2, S.c, L, "the -2 of the recurrence");
      carryPass(S.c, 2 * L, 0);
      runNm(OP.mul, S.c + L * esz, S.bpow2d, 0, S.scr, L, "the fold's scale by 2^d");
      runNm(OP.add, S.c, 0, S.scr, S.y, L, "the fold");
      normalize(S.y, L, 1);
      canonicalize(S.y);
      integralityGate(S.y, L);
    }

    function res64() {
      let out = 0n;
      for (let k = 0; k < G.L; k++) {
        const shBits = k * G.b;
        if (shBits >= 64) break;
        split(S.y + k * esz, S.invW, S.negW, S.lo, S.hi, S.wit, 1);
        const word = C.toU64(fi.fmt, S.lo);
        out = BigInt.asUintN(64, out + (BigInt.asUintN(64, word) << BigInt(shBits)));
      }
      return out;
    }

    function residueDigest() {
      const h = new Sha256();
      for (let k = 0; k < G.L; k++)
        h.push(bytesOf(decInteger(C, fi, S.y + k * esz) + "\n"));
      return hex32(h.end());
    }

    function startExponent() {
      engineSetup(exps[at]);
      need = exps[at] - 2;
      for (let k = 0; k < G.L; k++) C.copy(S.y + k * esz, S.zero, esz);
      C.fromI64(fi.fmt, RND.rne, 4, S.y);
      stepK = 0;
    }
    startExponent();

    const CHUNK = 8;
    let finished = false;
    const totalSquarings = exps.reduce((a, P) => a + (P - 2), 0);

    const job = {
      title: "mersenne", format: fi, totalSquarings,
      step() {
        if (finished) return { done: true };
        const target = Math.min(stepK + CHUNK, need);
        while (stepK < target) { llStep(); stepK++; squaringsTotal++; }
        const emitted = { exponent: exps[at], step: stepK, need,
                          b: G.b, L: G.L, d: G.d };
        if (stepK >= need) {
          const prime = allZero(S.y, G.L);
          const r64 = res64();
          const digest = residueDigest();
          const rec = {
            exponent: exps[at], prime, squarings: need,
            res64: r64.toString(16).padStart(16, "0"),
            b: G.b, L: G.L, d: G.d, digest,
          };
          records.push(rec);
          chain.absorb(`${rec.exponent} ${prime ? "prime" : "composite"} ` +
                       `${need} ${rec.res64}`);
          emitted.record = rec;
          at++;
          if (at >= exps.length) finished = true;
          else startExponent();
        }
        return { done: finished,
                 progress: squaringsTotal / totalSquarings, emitted };
      },
      result() {
        return {
          chain: chain.hex(),
          chains: { chain: chain.hex() },
          stats: {
            format: fi.name, prec: fi.prec,
            exponents: exps.length, resolved: records.length,
            squarings: squaringsTotal, limbProducts, passes: passesTotal,
            flags: flagsSeen, flagText: flagText(flagsSeen),
            status: C.saveAllFlags(C.dev) >>> 0,
            calls: C.calls, elemOps: C.elemOps,
          },
          records,
          work: limbProducts,
          workUnit: "limb products",
        };
      },
    };
    return job;
  }
  // =================================================================
  // The panel table
  //
  // Each panel is a list of NAMED RUNS. A run is one configuration of
  // one tool, and it carries the exact native command line that
  // reproduces it - because that command is what produced the chain
  // the page compares itself against, and a command nobody can read
  // off the page is a chain nobody can re-derive.
  //
  // Panels with more than one run have more than one thing to say:
  // zoom needs a second frame to show what an fp64 reference does at
  // this depth, orbits a second ensemble, collatz both a single deep
  // trajectory and a sweep, enclose one run per format because the
  // ladder IS the four formats side by side.
  // =================================================================
  const COLLATZ_DEEP_VALUE = ((1n << 237n) - 1315n).toString();

  const ZOOM_BASE = {
    width: 128, zoomExp: 196, period: 51, refIters: 1001,
    pixelIters: 1000, batch: 1024, refOffset: 0, glitchBits: 0,
    centre: null,
  };
  const ORBITS_BASE = {
    members: 8, periods: 4, stepsPerPeriod: 512, sampleEvery: 32,
    spread: 1,
  };
  const ENCLOSE_BASE = {
    points: 16, degree: 23, dotM: 32, dotTop: 60, condMax: 164,
    condLevels: 6, rows: 8, batch: 256,
  };

  function collatzCommand(cfg) {
    const f = `--engine loop --format ${cfg.format}`;
    if (cfg.mode === "deep")
      return `./host/cft-collatz ${f} --mode deep --values ` +
             `${cfg.values.join(",")} --batch ${cfg.batch}`;
    return `./host/cft-collatz ${f} --mode sweep --from ${cfg.from} ` +
           `--to ${cfg.to} --batch ${cfg.batch}`;
  }
  function zoomCommand(cfg) {
    return `./host/cft-zoom --engine loop --format ${cfg.format} ` +
           `--width ${cfg.width} --ref-iters ${cfg.refIters} ` +
           `--pixel-iters ${cfg.pixelIters} --batch ${cfg.batch}`;
  }
  function orbitsCommand(cfg) {
    return `./host/cft-orbits --engine loop --format ${cfg.format} ` +
           `--members ${cfg.members} --periods ${cfg.periods} ` +
           `--steps-per-period ${cfg.stepsPerPeriod} ` +
           `--sample-every ${cfg.sampleEvery}`;
  }
  function encloseCommand(cfg) {
    return `./host/cft-enclose --engine loop --format ${cfg.format} ` +
           `--kernels series,dot,horner --points ${cfg.points} ` +
           `--cond-max ${cfg.condMax}`;
  }
  function mersenneCommand(cfg) {
    return `./host/cft-mersenne --engine loop --format ${cfg.format} ` +
           `--exponents ${cfg.exponents.join(",")}`;
  }

  const PANELS = {
    collatz: {
      id: "collatz", tool: "cft-collatz", doc: "docs/COLLATZ.md",
      title: "Collatz, exactly, to 2^237",
      create: collatzJob, command: collatzCommand,
      runs: [
        { name: "trajectory", chains: ["chain"],
          cfg: { format: "fp256", mode: "deep",
                 values: [COLLATZ_DEEP_VALUE], batch: 1 } },
        { name: "sweep", chains: ["chain"],
          cfg: { format: "fp256", mode: "sweep", from: 1, to: 1001,
                 batch: 1000 } },
      ],
    },
    zoom: {
      id: "zoom", tool: "cft-zoom", doc: "docs/ZOOM.md",
      title: "A 10^-61 zoom, fp256 reference and fp64 pixels",
      create: zoomJob, command: zoomCommand,
      runs: [
        { name: "fp256-reference", chains: ["orbit", "pixels"],
          cfg: Object.assign({ format: "fp256" }, ZOOM_BASE) },
        { name: "fp64-reference", chains: ["orbit", "pixels"],
          cfg: Object.assign({ format: "fp64" }, ZOOM_BASE) },
      ],
    },
    orbits: {
      id: "orbits", tool: "cft-orbits", doc: "docs/ORBITS.md",
      title: "A Kepler ensemble, fp256 beside fp64",
      create: orbitsJob, command: orbitsCommand,
      runs: [
        { name: "fp256", chains: ["chain"],
          cfg: Object.assign({ format: "fp256" }, ORBITS_BASE) },
        { name: "fp64", chains: ["chain"],
          cfg: Object.assign({ format: "fp64" }, ORBITS_BASE) },
      ],
    },
    enclose: {
      id: "enclose", tool: "cft-enclose", doc: "docs/ENCLOSE.md",
      title: "Rigorous enclosures, at every format",
      create: encloseJob, command: encloseCommand,
      runs: ["fp32", "fp64", "fp128", "fp256"].map((f) => ({
        name: f, chains: ["chain"],
        cfg: Object.assign({ format: f }, ENCLOSE_BASE),
      })),
    },
    mersenne: {
      id: "mersenne", tool: "cft-mersenne", doc: "docs/MERSENNE.md",
      title: "Lucas-Lehmer, fp256 as an exact multiplier",
      create: mersenneJob, command: mersenneCommand,
      runs: [
        { name: "to-2281", chains: ["chain"],
          cfg: { format: "fp256",
                 exponents: [521, 607, 1277, 1279, 1619, 2203, 2281] } },
      ],
    },
  };

  /** The larger known exponents, offered behind a time warning. The
   *  first list is the rest of cft-mersenne's own `known` set; the
   *  second is its `device` set, which that tool wires in and does not
   *  run. Minutes to hours in a browser, which is why they are opt-in. */
  const MERSENNE_MORE = {
    known: [3217, 4253, 4423, 9689, 9941, 11213],
    device: [19937, 21701, 23209, 44497],
  };

  /** The widest exponent spread the dot ladder can use while EVERY
   *  format still holds its data exactly. The binding constraint is
   *  binary32's smallest normal: the ladder's smallest element is
   *  2^(dot_top - 2*mw - spread), so spread <= dot_top - 2*mw -
   *  emin(binary32). Derived rather than typed, because it is the
   *  whole reason fp32 appears in the chart at all - enclose.c refuses
   *  its own default (--cond-max 225) at binary32 with exactly this
   *  arithmetic, and this is the largest value it does not refuse. */
  function encloseCondMax(C) {
    const f32 = measureFormat(C, "fp32");
    const mw = dotMantissaBits(f32);
    return ENCLOSE_BASE.dotTop - 2 * mw - f32.emin;
  }

  /** Every (panel, run) pair, flattened - the eleven configurations the
   *  page computes and verify_demos.mjs checks against the tools. */
  function allRuns() {
    const out = [];
    for (const key of Object.keys(PANELS))
      for (const run of PANELS[key].runs)
        out.push({ panel: key, run: run.name, cfg: run.cfg,
                   chains: run.chains,
                   command: PANELS[key].command(run.cfg) });
    return out;
  }

  root.CftDemos = {
    createCft, measureFormat, PANELS, allRuns,
    Sha256, Chain, Rng, hex32, bytesOf,
    OP, RND, FMTCODE, FLAG, flagText,
    encloseCondMax, decInteger, geometryDerive, dotMantissaBits,
    COLLATZ_DEEP_VALUE, MERSENNE_MORE,
    ZOOM_BASE, ORBITS_BASE, ENCLOSE_BASE,
  };
})(typeof globalThis !== "undefined" ? globalThis
   : (typeof self !== "undefined" ? self : this));
