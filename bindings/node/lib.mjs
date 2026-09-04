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
// Appended by ABI 0.6, never inserted: an opcode number is on the wire
// and in every published vector set (cft.h). Both are issued through
// cft_reduce like SUM and DOT, and both are compositions the library
// makes - DOT over (a, a), and an ABS pass then SUM - with one row of
// their own, 9.4's infinity ahead of NaN.
export const OP_SUMSQ = 28, OP_SUMABS = 29;

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

/** The transcendentals, by arity: phase 1's nine (ABI 0.3), then
 *  phase 2's eleven (ABI 0.4), then phase 3's nine (ABI 0.5), then the
 *  ten that complete 754-2019 table 9.1 (ABI 0.6). These
 *  are not opcodes - cft.h gives
 *  each its own entry point, because correct rounding here is a
 *  library algorithm rather than a tile pass - so they are addressed
 *  by name at every layer: the cftw_* export, the "fn" field in the
 *  transcendental vector sets, the golden model's dispatch and this
 *  table all use the same spelling.
 *
 *  atan2 and atan2pi are binary and read y first, then x - the C
 *  order, which cft.h keeps because that is what every caller of
 *  atan2 expects. Nothing in this package reorders them. powr's a is
 *  the base and b the exponent, and powr is NOT pow: a negative base
 *  is invalid for every exponent, a NaN included.
 *
 *  TRANSCEND_INTARG is a third arity rather than a flag on the second,
 *  because its second operand is not a float at all: 9.2.1 says "n is
 *  a finite integral value in integralFormat", so pown, compound and
 *  rootn read an int64 array beside the encoding array. The vector
 *  sets carry that operand as "n", a signed decimal rather than an
 *  encoding, for the same reason. */
export const TRANSCEND_UNARY = ["exp", "expm1", "exp2", "log", "log1p",
                                "log2", "log10",
                                "sinpi", "cospi", "tanpi", "asin", "acos",
                                "atan", "asinpi", "acospi", "atanpi",
                                "sin", "cos", "tan", "sinh", "cosh",
                                "tanh", "asinh", "acosh", "atanh",
                                "exp2m1", "exp10", "exp10m1", "log2p1",
                                "log10p1", "rsqrt"];
export const TRANSCEND_BINARY = ["pow", "hypot", "atan2", "atan2pi", "powr"];
export const TRANSCEND_INTARG = ["pown", "compound", "rootn"];

/** The three augmented operations of 754-2019 clause 9.5, by the name
 *  their vector sets and cft_conformance use. Each delivers a PAIR -
 *  the operation rounded, and the error that rounding made - and takes
 *  NO rounding attribute: 9.5 fixes the direction to
 *  roundTiesTowardZero, which is not one of clause 4.3's five, so
 *  there is nothing to pass and no per-attribute file. */
export const AUGMENTED = ["augmentedAddition", "augmentedSubtraction",
                          "augmentedMultiplication"];

/** The three scaled product reductions of clause 9.4, by their set
 *  names. Each returns a significand in +-[1, 2) and an int64 scale;
 *  they are not cft_reduce opcodes because a pair does not fit through
 *  an entry point that delivers one element. */
export const SCALED_PRODUCTS = ["scaled_prod", "scaled_prod_sum",
                                "scaled_prod_diff"];

/** The clause-5.12 character conversions and the clause-9.7 payload
 *  operations, by the name their vector sets use. The from_ pair are
 *  batches (n sequences in, n encodings out); the to_ pair are per
 *  element by design, because an output sequence's length is not known
 *  until the conversion has run and is wildly non-uniform - cft.h says
 *  so at length. The three payload operations are elementwise and
 *  signal nothing at all. */
export const CHARACTER_FNS = ["from_decimal", "from_hex", "to_decimal",
                              "to_hex", "get_payload", "set_payload",
                              "set_payload_signaling"];

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

    // ABI 0.6: clause 5.12's character conversions and 9.7's payloads.
    // Every string crosses as a heap pointer, never as cwrap's "string"
    // type: the from_ calls take an ARRAY of pointers, and the to_ calls
    // keep the C's two-call sizing protocol, which a marshalled return
    // value could not express - see core.mjs.
    decimalDigits: M.cwrap("cftw_format_decimal_digits", n, [n]),
    fromDecimalChar: M.cwrap("cftw_from_decimal_char", n, [n,n,n,n,n,n,n,n]),
    toDecimalChar: M.cwrap("cftw_to_decimal_char", n, [n,n,n,n,n,n,n,n,n]),
    fromHexChar:  M.cwrap("cftw_from_hex_char", n, [n,n,n,n,n,n,n,n]),
    toHexChar:    M.cwrap("cftw_to_hex_char", n, [n,n,n,n,n,n]),
    getPayload:   M.cwrap("cftw_get_payload", n, [n,n,n,n,n]),
    setPayload:   M.cwrap("cftw_set_payload", n, [n,n,n,n,n]),
    setPayloadSignaling:
                  M.cwrap("cftw_set_payload_signaling", n, [n,n,n,n,n]),

    // ABI 0.6: the scaled product reductions (9.4). A value and an
    // int64 scale, both out-pointers into the heap.
    scaledProd:   M.cwrap("cftw_scaled_prod", n, [n,n,n,n,n,n,n,n]),
    scaledProdSum:
                  M.cwrap("cftw_scaled_prod_sum", n, [n,n,n,n,n,n,n,n,n]),
    scaledProdDiff:
                  M.cwrap("cftw_scaled_prod_diff", n, [n,n,n,n,n,n,n,n,n]),

    // ABI 0.6: the augmented arithmetic (9.5). No rounding argument -
    // 9.5 fixes the direction, so there is none to pass.
    augmentedAdd: M.cwrap("cftw_augmented_add", n, [n,n,n,n,n,n,n,n]),
    augmentedSub: M.cwrap("cftw_augmented_sub", n, [n,n,n,n,n,n,n,n]),
    augmentedMul: M.cwrap("cftw_augmented_mul", n, [n,n,n,n,n,n,n,n]),
  };

  // ABI 0.3's nine, 0.4's eleven, 0.5's nine and 0.6's ten - the
  // thirty-nine transcendentals. Named
  // rather than numbered: these are library entry points, not opcodes,
  // so there is no field to mistranscribe and audit() has nothing to
  // ask the module about them - a missing export shows up as a missing
  // cwrap right here, which is why the loop is over the contract's own
  // name lists.
  //
  // The argument list ends at the flag word for all thirty-nine. That is
  // the contract's shape, not an oversight: these issue no device
  // pass, so there is no bus word (cft.h). Thirty-one are unary; pow,
  // hypot, atan2, atan2pi and powr take a second encoding; pown,
  // compound and rootn take an int64 ARRAY in b's place, which is the
  // same argument count and a different meaning, so they get their own
  // loop rather than sharing the binary one.
  for (const fn of TRANSCEND_UNARY)
    C[fn] = M.cwrap(`cftw_${fn}`, n, [n,n,n,n,n,n,n]);
  for (const fn of TRANSCEND_BINARY)
    C[fn] = M.cwrap(`cftw_${fn}`, n, [n,n,n,n,n,n,n,n]);
  for (const fn of TRANSCEND_INTARG)
    C[fn] = M.cwrap(`cftw_${fn}`, n, [n,n,n,n,n,n,n,n]);

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
  sumsq: OP_SUMSQ, sumabs: OP_SUMABS,
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

  /** One NUL-terminated sequence in the heap, as cft.h's from_ calls
   *  read it. UTF-8 because that is what emscripten writes; 5.12's
   *  syntax is ASCII, so the two agree on everything the library will
   *  accept and the encoding is only ever visible on a sequence it
   *  refuses. */
  putString(s) {
    const bytes = this.M.lengthBytesUTF8(s) + 1;
    const p = this.alloc(bytes);
    this.M.stringToUTF8(s, p, bytes);
    return p;
  }

  /** An array of pointers to NUL-terminated sequences: the
   *  `const char *const *` argument, laid out as wasm32's 4-byte
   *  offsets. */
  putStringArray(list) {
    const ptrs = list.map((s) => this.putString(s));
    const vec = this.alloc(4 * Math.max(ptrs.length, 1));
    ptrs.forEach((p, i) => { this.M.HEAPU32[(vec >> 2) + i] = p; });
    return vec;
  }

  /** n int64 values. Written through a BigInt64Array view taken here
   *  and never kept: a later _malloc can grow the module's memory and
   *  detach it. */
  putI64(values) {
    const p = this.alloc(8 * Math.max(values.length, 1));
    const view = new BigInt64Array(this.M.HEAPU8.buffer, p, values.length);
    values.forEach((v, i) => { view[i] = v; });
    return p;
  }

  /** One int64 back out, as a BigInt. */
  i64(ptr) {
    return new BigInt64Array(this.M.HEAPU8.buffer, ptr, 1)[0];
  }

  /** A NUL-terminated sequence back out. */
  str(ptr) { return this.M.UTF8ToString(ptr); }

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
