// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The binding layer: load the wasm module, name the constants, and
// project the cftw_* exports as JavaScript functions. Nothing numeric
// happens here or anywhere else in this package - every value that
// comes back is bits libcft computed.
//
// The module is bindings/wasm's, unchanged: the same C sources, the
// same emcc flags, the same wasm bytes as the ones inside
// conformance.html, built by bindings/wasm/build.sh stage 5 with one
// different -sENVIRONMENT. `node bindings/wasm/verify.mjs` is the
// check that the two really are the same module; this file just loads
// it.
//
// Two rules the rest of the package inherits:
//
//   * An ENCODING IS BYTES. Never a JavaScript number. A JS number is
//     a binary64, so it cannot hold fp128 or fp256 at all, and even at
//     fp32/fp64 passing bits through one canonicalises NaN payloads
//     the engine is entitled to rewrite. Encodings travel as
//     Uint8Array (dense, little-endian, cft_format_size bytes - what
//     cft.h specifies) or, for one scalar, as a BigInt of the same
//     bits. `number` appears only in conversions that say so in their
//     name.
//   * The constants below are transcribed from cft.h, and a
//     transcription that nobody checks is a wrong answer waiting for
//     an opcode field. audit() asks the loaded module what it calls
//     each number and refuses to run if the answers disagree - the
//     check cft_format_name()/cft_op_name() exist for.

import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

export const ABI_MAJOR = 0;   // cft.h CFT_ABI_VERSION_MAJOR

export const FP32 = 0, FP64 = 1, FP128 = 2, FP256 = 3;

export const OP_FMA = 0, OP_ADD = 1, OP_SUB = 2, OP_MUL = 3;
export const OP_ABS = 4, OP_NEG = 5, OP_COPYSIGN = 6;
export const OP_MIN = 7, OP_MAX = 8, OP_MINNUM = 9, OP_MAXNUM = 10;
export const OP_SELECT = 11, OP_CMPLT = 12, OP_CMPLE = 13, OP_CMPEQ = 14;
export const OP_IAND = 16, OP_IOR = 17, OP_IXOR = 18, OP_IADD = 19;
export const OP_ISUB = 20, OP_ISHL = 21, OP_ISHR = 22, OP_ICMPLT = 23;
export const OP_SUM = 24, OP_DOT = 25;
export const OP_RECIP_SEED = 26, OP_RSQRT_SEED = 27;

export const RNE = 0, RTZ = 1, RDN = 2, RUP = 3, RMM = 4;

export const FLAG_INVALID = 1 << 0;
export const FLAG_DIVBYZERO = 1 << 1;
export const FLAG_OVERFLOW = 1 << 2;
export const FLAG_UNDERFLOW = 1 << 3;
export const FLAG_INEXACT = 1 << 4;

const FLAG_NAMES = [
  [FLAG_INVALID, "invalid"], [FLAG_DIVBYZERO, "divbyzero"],
  [FLAG_OVERFLOW, "overflow"], [FLAG_UNDERFLOW, "underflow"],
  [FLAG_INEXACT, "inexact"],
];

/** The IEEE exception names set in a flag word. An unknown bit is
 *  reported as a number rather than dropped: a flag word this package
 *  cannot name is news, not noise. */
export function flagNames(flags) {
  const names = FLAG_NAMES.filter(([b]) => flags & b).map(([, n]) => n);
  const known = FLAG_NAMES.reduce((a, [b]) => a | b, 0);
  const extra = flags & ~known;
  if (extra) names.push(`unknown 0x${extra.toString(16)}`);
  return names;
}

/** cft_class_value, 754-2019 5.7.2, as names. */
export const CLASS_NAMES = [
  "-inf", "-normal", "-subnormal", "-zero",
  "+zero", "+subnormal", "+normal", "+inf", "snan", "qnan",
];

// ---------------------------------------------------------------------
// The module
// ---------------------------------------------------------------------

let cached = null;

/** Instantiate the wasm module once per process and return the cwrap
 *  table. The .wasm is read here and handed over as Module.wasmBinary
 *  rather than left to emscripten's own path search, so the package
 *  works from any working directory and there is exactly one place
 *  that decides which module got loaded. */
export function loadModule() {
  if (!cached) cached = instantiate();
  return cached;
}

async function instantiate() {
  const wasmPath = join(HERE, "cft_node.wasm");
  const jsPath = join(HERE, "cft_node.js");
  let createCftModule, wasmBinary;
  try {
    createCftModule = require(jsPath);
    wasmBinary = readFileSync(wasmPath);
  } catch (err) {
    throw new Error(
      `cft: could not load the wasm module (${err.message}). ` +
      `bindings/node ships cft_node.js and cft_node.wasm as committed ` +
      `build products; regenerate them with ` +
      `\`bash bindings/wasm/build.sh\`.`);
  }
  const M = await createCftModule({ wasmBinary });

  const n = "number", s = "string";
  const C = {
    abiVersion:   M.cwrap("cftw_abi_version", n, []),
    strerror:     M.cwrap("cftw_strerror", s, [n]),
    lastError:    M.cwrap("cftw_last_error", s, []),
    formatSize:   M.cwrap("cftw_format_size", n, [n]),
    formatName:   M.cwrap("cftw_format_name", s, [n]),
    opName:       M.cwrap("cftw_op_name", s, [n]),

    openSoftware: M.cwrap("cftw_open_software", n, [n]),
    close:        M.cwrap("cftw_close", null, [n]),
    supports:     M.cwrap("cftw_supports", n, [n, n, n]),
    capsMask:     M.cwrap("cftw_caps_format_mask", n, [n]),
    capsTiles:    M.cwrap("cftw_caps_tiles", n, [n]),
    capsAbi:      M.cwrap("cftw_caps_abi_version", n, [n]),
    capsFlagsOk:  M.cwrap("cftw_caps_flags_readable", n, [n]),
    capsBackend:  M.cwrap("cftw_caps_backend", s, [n]),

    run:          M.cwrap("cftw_run", n, [n,n,n,n,n,n,n,n,n,n,n]),
    reduce:       M.cwrap("cftw_reduce", n, [n,n,n,n,n,n,n,n,n,n]),
    div:          M.cwrap("cftw_div", n, [n,n,n,n,n,n,n,n,n]),
    sqrt:         M.cwrap("cftw_sqrt", n, [n,n,n,n,n,n,n,n]),

    // ABI 0.2, the clause-5 completion set
    rint:         M.cwrap("cftw_rint", n, [n,n,n,n,n,n,n,n,n]),
    scaleb:       M.cwrap("cftw_scaleb", n, [n,n,n,n,n,n,n,n,n,n]),
    cmpSig:       M.cwrap("cftw_cmp_sig", n, [n,n,n,n,n,n,n,n,n]),
    convert:      M.cwrap("cftw_convert", n, [n,n,n,n,n,n,n,n]),
    cvtFromI32:   M.cwrap("cftw_cvt_from_i32", n, [n,n,n,n,n,n,n]),
    cvtFromU32:   M.cwrap("cftw_cvt_from_u32", n, [n,n,n,n,n,n,n]),
    cvtFromI64:   M.cwrap("cftw_cvt_from_i64", n, [n,n,n,n,n,n,n]),
    cvtFromU64:   M.cwrap("cftw_cvt_from_u64", n, [n,n,n,n,n,n,n]),
    cvtToI32:     M.cwrap("cftw_cvt_to_i32", n, [n,n,n,n,n,n,n,n]),
    cvtToU32:     M.cwrap("cftw_cvt_to_u32", n, [n,n,n,n,n,n,n,n]),
    cvtToI64:     M.cwrap("cftw_cvt_to_i64", n, [n,n,n,n,n,n,n,n]),
    cvtToU64:     M.cwrap("cftw_cvt_to_u64", n, [n,n,n,n,n,n,n,n]),
    logb:         M.cwrap("cftw_logb", n, [n,n,n,n,n,n]),
    nextUp:       M.cwrap("cftw_next_up", n, [n,n,n,n,n,n]),
    nextDown:     M.cwrap("cftw_next_down", n, [n,n,n,n,n,n]),
    classOf:      M.cwrap("cftw_class", n, [n,n,n,n,n]),
    totalOrder:   M.cwrap("cftw_total_order", n, [n,n,n,n,n,n]),
    totalOrderMag: M.cwrap("cftw_total_order_mag", n, [n,n,n,n,n,n]),
    rem:          M.cwrap("cftw_rem", n, [n,n,n,n,n,n,n]),

    conformance:  M.cwrap("cftw_conformance", n, [n,s,n,n,n,n]),
  };

  audit(M, C);
  return { M, C };
}

/** cft.h says to check the ABI at run time rather than trust the
 *  header you compiled against. This package's numbers all travel
 *  into an opcode or format field, so a mistranscription would
 *  compute a different operation and report nothing - which is why
 *  the header publishes cft_format_name()/cft_op_name(), and why this
 *  runs once per process. The expected name is the constant's own
 *  name, lowercased: one transcription, not two. */
function audit(M, C) {
  const abi = C.abiVersion() >>> 0;
  if (abi >>> 16 !== ABI_MAJOR)
    throw new Error(
      `the wasm module reports libcft ABI ${abi >>> 16}.${abi & 0xffff}; ` +
      `this package is written against major ${ABI_MAJOR}. A major change ` +
      `breaks source or binary compatibility (cft.h), so the opcode and ` +
      `format numbers here cannot be assumed to still mean what they say.`);

  const wrong = [];
  const check = (label, value, got) => {
    if (got !== label) wrong.push(`${label} = ${value}, but the library ` +
                                  `calls ${value} ${JSON.stringify(got)}`);
  };
  for (const [name, value] of Object.entries(OPS_BY_NAME))
    check(name, value, C.opName(value));
  for (const [name, value] of [["fp32", FP32], ["fp64", FP64],
                               ["fp128", FP128], ["fp256", FP256]])
    check(name, value, C.formatName(value));
  if (wrong.length)
    throw new Error(
      "this package's transcription of cft.h disagrees with the module " +
      "it loaded:\n" + wrong.map((w) => "    " + w).join("\n") +
      "\nThese numbers go into opcode and format fields, so continuing " +
      "would compute the wrong operation and say nothing about it.");
}

const OPS_BY_NAME = {
  fma: OP_FMA, add: OP_ADD, sub: OP_SUB, mul: OP_MUL,
  abs: OP_ABS, neg: OP_NEG, copysign: OP_COPYSIGN,
  min: OP_MIN, max: OP_MAX, minnum: OP_MINNUM, maxnum: OP_MAXNUM,
  select: OP_SELECT, cmplt: OP_CMPLT, cmple: OP_CMPLE, cmpeq: OP_CMPEQ,
  iand: OP_IAND, ior: OP_IOR, ixor: OP_IXOR, iadd: OP_IADD,
  isub: OP_ISUB, ishl: OP_ISHL, ishr: OP_ISHR, icmplt: OP_ICMPLT,
  sum: OP_SUM, dot: OP_DOT,
  recip_seed: OP_RECIP_SEED, rsqrt_seed: OP_RSQRT_SEED,
};
export { OPS_BY_NAME };

// ---------------------------------------------------------------------
// Heap helpers
//
// ALLOW_MEMORY_GROWTH is on, so a malloc can replace the module's
// ArrayBuffer and detach every view taken before it. Nothing here
// keeps a view across an allocation: each helper takes M.HEAPU8 fresh.
// ---------------------------------------------------------------------

export class Scratch {
  constructor(M) { this.M = M; this.ptrs = []; }

  alloc(bytes) {
    const p = this.M._malloc(bytes);
    if (!p) throw new Error(`out of wasm memory allocating ${bytes} bytes`);
    this.ptrs.push(p);
    this.M.HEAPU8.fill(0, p, p + bytes);
    return p;
  }

  /** Copy bytes in and return the pointer. */
  put(bytes) {
    const p = this.alloc(bytes.length);
    this.M.HEAPU8.set(bytes, p);
    return p;
  }

  /** Copy bytes back out. */
  get(ptr, len) {
    return this.M.HEAPU8.slice(ptr, ptr + len);
  }

  u32(ptr) { return this.M.HEAPU32[ptr >> 2] >>> 0; }

  free() {
    for (const p of this.ptrs) this.M._free(p);
    this.ptrs.length = 0;
  }
}

/** Run `fn` with a Scratch that is always freed. */
export function withScratch(M, fn) {
  const s = new Scratch(M);
  try { return fn(s); } finally { s.free(); }
}

/** Turn a nonzero cft_status into an Error carrying the library's own
 *  words. cft_strerror is the contract's vocabulary; this package does
 *  not invent a second one. */
export function checkStatus(C, status, what) {
  if (status === 0) return;
  const detail = C.lastError();
  throw new Error(`${what}: ${C.strerror(status)}` +
                  (detail ? ` - ${detail}` : ""));
}
