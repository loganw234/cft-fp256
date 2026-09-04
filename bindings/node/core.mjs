// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// Context and Float: IEEE binary32/64/128/256 in Node, computed by
// libcft's wasm module and by nothing else.
//
// The one rule this file exists to keep: NOTHING NUMERIC IS COMPUTED
// HERE. Every arithmetic result, every rounded conversion, every flag
// is what a cftw_* call returned. The only bit manipulation below is
// the interchange codec - packing an integer significand and a power
// of two into an encoding, and reading one back - which is
// representation, not arithmetic: it reproduces a value exactly or it
// refuses.
//
// That rule is why decimal strings work the way they do. A decimal
// that is exactly representable is packed by the codec, no rounding
// involved. A decimal that is not is handed to the LIBRARY as an
// exact numerator and an exact denominator (or an exact pair of
// factors) and rounded by one cft_div/cft_mul/cft_cvt call - so the
// rounding is libcft's, in the context's own attribute, with the
// library's own flags. Where no such single exact call exists, the
// parse REFUSES and says why. There is no third path: a second
// implementation of the rounding is exactly how "identical bits"
// stops being true.
//
// The Python drop-in (bindings/python/cftmpfr) makes the same promise
// and borrows gmpy2/MPFR for the rounding, which costs it two things
// this package does not pay: a dependency, and roundTiesToAway, which
// MPFR cannot do at all. Here RMM parses decimals like every other
// attribute, because the thing doing the rounding is the library that
// implements it.

import {
  CLASS_NAMES, FP32, FP64, FP128, FP256, OP_ABS, OP_ADD, OP_CMPEQ,
  OP_CMPLE, OP_CMPLT, OP_COPYSIGN, OP_DOT, OP_FMA, OP_MAX, OP_MAXNUM,
  OP_MIN, OP_MINNUM, OP_MUL, OP_NEG, OP_SELECT, OP_SUB, OP_SUM,
  OP_SUMABS, OP_SUMSQ,
  RDN, RMM, RNE, RTZ, RUP, TRANSCEND_BINARY, TRANSCEND_INTARG,
  TRANSCEND_UNARY,
  checkStatus, flagNames, loadModule, withScratch,
} from "./lib.mjs";

// Three arities, not two: TRANSCEND_INTARG's second operand is an
// int64 array rather than an encoding, so it cannot share the binary
// path even though the argument count matches. lib.mjs says why.
const TRANSCEND_ARITY = new Map([
  ...TRANSCEND_UNARY.map((f) => [f, 1]),
  ...TRANSCEND_BINARY.map((f) => [f, 2]),
]);
const TRANSCEND_INT = new Set(TRANSCEND_INTARG);

/** The int64 range check every integer operand in this package goes
 *  through. int64 is exactly why these are BigInt at the boundary: a
 *  JS number is a binary64, so it silently stops being an integer
 *  above 2^53, and rootn's or pown's exponent is int64 in the
 *  contract. A safe integer is accepted and widened here - writing
 *  `pown(x, 3)` should not need a suffix - and anything past 2^53 has
 *  to arrive as a BigInt, because a number that large has already lost
 *  the value before this function could see it. */
function asI64(v, what) {
  let n;
  if (typeof v === "bigint") n = v;
  else if (typeof v === "number") {
    if (!Number.isSafeInteger(v))
      throw new TypeError(
        `${what} is an int64 in the contract; ${v} is not a safe integer, ` +
        `so a JS number cannot carry it - pass a BigInt`);
    n = BigInt(v);
  } else {
    throw new TypeError(`${what} wants a BigInt or a safe integer, got ` +
                        `${typeof v}`);
  }
  if (n < -(2n ** 63n) || n >= 2n ** 63n)
    throw new RangeError(`${what} is int64_t; ${n} does not fit`);
  return n;
}

// ---------------------------------------------------------------------
// Formats. Geometry only; the codes and names are cft.h's, and
// lib.mjs's audit has already made the module agree with them.
// ---------------------------------------------------------------------

class FormatInfo {
  constructor(code, name, ieeeName, width, expW) {
    this.code = code;
    this.name = name;             // cft_format_name()'s answer
    this.ieeeName = ieeeName;     // 754's name
    this.width = width;
    this.size = width / 8;        // bytes per element
    this.expW = expW;
    this.manW = width - 1 - expW;
    this.prec = this.manW + 1;
    this.bias = (1 << (expW - 1)) - 1;
    this.emax = this.bias;        // largest unbiased normal exponent
    this.emin = 1 - this.bias;    // smallest unbiased normal exponent
  }
}

const F32 = new FormatInfo(FP32, "fp32", "binary32", 32, 8);
const F64 = new FormatInfo(FP64, "fp64", "binary64", 64, 11);
const F128 = new FormatInfo(FP128, "fp128", "binary128", 128, 15);
const F256 = new FormatInfo(FP256, "fp256", "binary256", 256, 19);
const ALL_FORMATS = [F32, F64, F128, F256];

const BY_WIDTH = new Map(ALL_FORMATS.map((f) => [f.width, f]));
const BY_PREC = new Map(ALL_FORMATS.map((f) => [f.prec, f]));
const BY_NAME = new Map(ALL_FORMATS.flatMap((f) => [[f.name, f],
                                                    [f.ieeeName, f]]));

/** A format from a width (32/64/128/256), a precision (24/53/113/237)
 *  or a name ("fp128" / "binary128"). The three ranges do not collide,
 *  so there is nothing to guess. */
export function formatFor(spec) {
  if (typeof spec === "string") {
    const f = BY_NAME.get(spec.toLowerCase());
    if (f) return f;
  } else if (typeof spec === "number") {
    const f = BY_WIDTH.get(spec) ?? BY_PREC.get(spec);
    if (f) return f;
  }
  throw new TypeError(
    `unsupported format ${JSON.stringify(spec)}: this package drives IEEE ` +
    `interchange formats only - 32/64/128/256 by width, 24/53/113/237 by ` +
    `precision, or "binary128"/"fp128" by name`);
}

const ROUNDINGS = new Map([
  ["rne", RNE], ["rtz", RTZ], ["rdn", RDN], ["rup", RUP], ["rmm", RMM],
]);
const ROUNDING_NAME = new Map([...ROUNDINGS].map(([k, v]) => [v, k]));

/** Rounding by NAME only. cft.h's own names, and no numbers: every
 *  ecosystem numbers these differently (MPFR's 2 is up, the
 *  contract's 2 is down), and a silently transposed attribute is the
 *  worst bug this package could ship. */
function roundingFor(spec) {
  if (typeof spec === "string") {
    const r = ROUNDINGS.get(spec.toLowerCase());
    if (r !== undefined) return r;
  }
  throw new TypeError(
    `unknown rounding ${JSON.stringify(spec)}: use "rne", "rtz", "rdn", ` +
    `"rup" or "rmm" - names, not numbers, because the CFT, MPFR and ` +
    `RISC-V enumerations assign different numbers to the same directions`);
}

// ---------------------------------------------------------------------
// The interchange codec: bits <-> (kind, sign, m, e), all BigInt.
// Pure field packing. Exact both ways, or an Inexact refusal.
// ---------------------------------------------------------------------

/** Thrown by the codec when a value cannot be represented exactly. It
 *  is a routing signal, not always an error: the decimal parser
 *  catches it and looks for a single library call that can round. */
export class NotExact extends Error {}

function decode(fi, bits) {
  const sign = Number((bits >> BigInt(fi.width - 1)) & 1n);
  const biased = Number((bits >> BigInt(fi.manW)) &
                        ((1n << BigInt(fi.expW)) - 1n));
  const frac = bits & ((1n << BigInt(fi.manW)) - 1n);
  if (biased === (1 << fi.expW) - 1)
    return { kind: frac ? "nan" : "inf", sign, m: 0n, e: 0 };
  if (biased === 0) {
    if (frac === 0n) return { kind: "zero", sign, m: 0n, e: 0 };
    return { kind: "finite", sign, m: frac, e: fi.emin - fi.manW };
  }
  return {
    kind: "finite", sign,
    m: frac | (1n << BigInt(fi.manW)),
    e: biased - fi.bias - fi.manW,
  };
}

/** Bits for (-1)^sign * m * 2^e with m > 0, or NotExact. */
function encodeExact(fi, sign, m, e) {
  const L = m.toString(2).length;              // m > 0, so bit_length
  const E = e + L - 1;                         // exponent of the leading bit
  const signBit = BigInt(sign) << BigInt(fi.width - 1);
  if (E > fi.emax)
    throw new NotExact(`exponent ${E} is above ${fi.ieeeName}'s emax ` +
                       `${fi.emax}`);
  if (E >= fi.emin) {
    const shift = fi.prec - L;
    let sig;
    if (shift >= 0) sig = m << BigInt(shift);
    else {
      if (m & ((1n << BigInt(-shift)) - 1n))
        throw new NotExact(`needs ${L} significand bits; ${fi.ieeeName} ` +
                           `has ${fi.prec}`);
      sig = m >> BigInt(-shift);
    }
    return signBit
      | (BigInt(E + fi.bias) << BigInt(fi.manW))
      | (sig & ((1n << BigInt(fi.manW)) - 1n));
  }
  // subnormal: the value has to sit on the fixed grid 2^(emin - manW)
  const shift = e - (fi.emin - fi.manW);
  let k;
  if (shift >= 0) k = m << BigInt(shift);
  else {
    if (m & ((1n << BigInt(-shift)) - 1n))
      throw new NotExact(`below ${fi.ieeeName}'s subnormal grid ` +
                         `2^${fi.emin - fi.manW}`);
    k = m >> BigInt(-shift);
  }
  return signBit | k;
}

function bitsToBytes(fi, bits) {
  const out = new Uint8Array(fi.size);
  let v = bits;
  for (let i = 0; i < fi.size; i++) { out[i] = Number(v & 0xffn); v >>= 8n; }
  return out;
}

function bytesToBits(bytes) {
  let v = 0n;
  for (let i = bytes.length - 1; i >= 0; i--) v = (v << 8n) | BigInt(bytes[i]);
  return v;
}

// ---------------------------------------------------------------------
// Decimal strings
// ---------------------------------------------------------------------

const DECIMAL_RE = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/;

/** Lex a decimal string into a special, or (sign, M, E) with the value
 *  exactly (-1)^sign * M * 10^E. No rounding happens here: this is
 *  reading, and what is read is exact. */
function lexDecimal(s) {
  if (typeof s !== "string")
    throw new TypeError(`expected a string, got ${typeof s}`);
  // Specials are lexed here and never rounded. toString() writes
  // "nan", "inf", "-inf" and the two zeros without touching the
  // library, so the parse has to read them back the same way, or the
  // round trip is asymmetric by construction - the lesson
  // bindings/python learned at 8c347fd, where a version of gmpy2 that
  // refused every spelling of inf turned a formatting choice into a
  // portability bug.
  const t = s.trim();
  const sign = t.startsWith("-") ? 1 : 0;
  const body = (t[0] === "+" || t[0] === "-") ? t.slice(1) : t;
  const low = body.toLowerCase();
  if (low === "nan") return { kind: "nan", sign };
  if (low === "inf" || low === "infinity") return { kind: "inf", sign };

  const m = DECIMAL_RE.exec(t);
  if (!m || (m[2] === "" && (m[3] ?? "") === ""))
    throw new SyntaxError(
      `not a decimal number: ${JSON.stringify(s)}. This parser takes an ` +
      `optional sign, digits with an optional point, an optional ` +
      `exponent, and the words nan/inf/infinity - no hex floats, no ` +
      `separators, no locale.`);
  const intPart = m[2] || "";
  const fracPart = m[3] || "";
  const exp = m[4] ? Number(m[4]) : 0;
  return {
    kind: "finite", sign,
    M: BigInt((intPart + fracPart) || "0"),
    E: exp - fracPart.length,
  };
}

/** The EXACT decimal for (-1)^sign * m * 2^e, in the same shape
 *  cftmpfr's to_str writes: one digit, a point, the rest, an
 *  explicitly signed power of ten.
 *
 *  Exact, not shortest. Every binary float is a finite decimal
 *  (2^-k = 5^k * 10^-k), so this always terminates and always reads
 *  back to the same bits - the round trip needs no library and no
 *  agreement about what "shortest" means. The price is length: the
 *  smallest binary256 subnormal is 2^-262378, whose exact decimal
 *  runs to about 183,000 significant digits. Values people actually
 *  hold are short; the extremes are honest rather than convenient. */
function exactDecimal(sign, m, e) {
  let digits, p;
  if (e >= 0) { digits = (m << BigInt(e)).toString(); p = 0; }
  else { digits = (m * 5n ** BigInt(-e)).toString(); p = e; }
  const exp10 = digits.length - 1 + p;
  let mant = digits.replace(/0+$/, "") || "0";
  const head = mant[0];
  const tail = mant.slice(1);
  const body = tail ? `${head}.${tail}` : head;
  const sgn = sign ? "-" : "";
  return `${sgn}${body}e${exp10 >= 0 ? "+" : "-"}${Math.abs(exp10)}`;
}

const v5 = (n) => { let k = 0; while (n % 5n === 0n) { n /= 5n; k++; } return k; };

/** The largest j with 5^j exactly representable in this format - the
 *  edge of the window where one exact division or multiplication can
 *  deliver a correctly rounded decimal. Computed, not tabulated: it
 *  is a property of the precision and there is no reason for a second
 *  copy of it to exist and go stale. */
const POW5_LIMIT = new Map();
function pow5Limit(fi) {
  if (!POW5_LIMIT.has(fi)) {
    const bound = 1n << BigInt(fi.prec);
    let j = 0;
    while (5n ** BigInt(j + 1) < bound) j++;
    POW5_LIMIT.set(fi, j);
  }
  return POW5_LIMIT.get(fi);
}

// ---------------------------------------------------------------------
// Float
// ---------------------------------------------------------------------

export class Float {
  constructor(ctx, bytes) {
    if (!(bytes instanceof Uint8Array) || bytes.length !== ctx.format.size)
      throw new TypeError(
        `a ${ctx.format.ieeeName} encoding is ${ctx.format.size} bytes; ` +
        `got ${bytes?.length}`);
    this._ctx = ctx;
    this._bytes = bytes;
    Object.freeze(this);
  }

  get context() { return this._ctx; }

  /** A copy of the encoding: dense little-endian bytes, exactly what
   *  cft.h says a buffer element is. */
  get bytes() { return this._bytes.slice(); }

  /** The same encoding as one unsigned BigInt. Exact at every width -
   *  which a JS number is not, and is why nothing here returns one. */
  get bits() { return bytesToBits(this._bytes); }

  _parts() { return decode(this._ctx.format, this.bits); }

  get isNaN() { return this._parts().kind === "nan"; }
  get isInf() { return this._parts().kind === "inf"; }
  get isZero() { return this._parts().kind === "zero"; }
  /** The SIGN BIT: -0 is signed, and a NaN has one too. */
  get sign() { return this._parts().sign; }

  sameBits(other) {
    if (!(other instanceof Float)) return false;
    if (other._ctx.format !== this._ctx.format) return false;
    return this.bits === other.bits;
  }

  /** classifyOp (754 5.7.2), from cft_class - the library's answer,
   *  not a re-derivation from the fields. */
  classify() { return this._ctx.classify(this); }

  /** The exact decimal. See exactDecimal() for what "exact" costs. */
  toString() {
    const { kind, sign, m, e } = this._parts();
    if (kind === "nan") return "nan";
    if (kind === "inf") return sign ? "-inf" : "inf";
    if (kind === "zero") return sign ? "-0" : "0";
    return exactDecimal(sign, m, e);
  }

  /** A JS number, converted BY THE LIBRARY (cft_convert to fp64 under
   *  this context's attribute) - exact when widening, correctly
   *  rounded when narrowing. A NaN loses its payload here because a JS
   *  number cannot carry one; libcft's arithmetic only ever produces
   *  the canonical quiet NaN, so nothing an operation returned is
   *  lost. */
  toNumber() { return this._ctx.toNumber(this); }

  /** The value as a BigInt, via cft_cvt_to_i64 in this context's
   *  attribute. `exact` selects the ...Exact family, which is the one
   *  that reports inexact. */
  toBigInt(opts) { return this._ctx.toBigInt(this, opts); }

  add(y) { return this._ctx.add(this, y); }
  sub(y) { return this._ctx.sub(this, y); }
  mul(y) { return this._ctx.mul(this, y); }
  div(y) { return this._ctx.div(this, y); }
  sqrt() { return this._ctx.sqrt(this); }
  neg() { return this._ctx.neg(this); }
  abs() { return this._ctx.abs(this); }
  fma(y, z) { return this._ctx.fma(this, y, z); }

  /** The phase-1 transcendentals (ABI 0.3), correctly rounded in this
   *  value's own context and attribute. */
  exp() { return this._ctx.exp(this); }
  expm1() { return this._ctx.expm1(this); }
  exp2() { return this._ctx.exp2(this); }
  log() { return this._ctx.log(this); }
  log1p() { return this._ctx.log1p(this); }
  log2() { return this._ctx.log2(this); }
  log10() { return this._ctx.log10(this); }
  pow(y) { return this._ctx.pow(this, y); }
  hypot(y) { return this._ctx.hypot(this, y); }

  /** The phase-2 trigonometrics (ABI 0.4), same terms. `this` is the
   *  y operand of atan2 and atan2pi, so `y.atan2(x)` reads in the
   *  order cft.h names and C's atan2 uses. */
  sinpi() { return this._ctx.sinpi(this); }
  cospi() { return this._ctx.cospi(this); }
  tanpi() { return this._ctx.tanpi(this); }
  asin() { return this._ctx.asin(this); }
  acos() { return this._ctx.acos(this); }
  atan() { return this._ctx.atan(this); }
  asinpi() { return this._ctx.asinpi(this); }
  acospi() { return this._ctx.acospi(this); }
  atanpi() { return this._ctx.atanpi(this); }
  atan2(x) { return this._ctx.atan2(this, x); }
  atan2pi(x) { return this._ctx.atan2pi(this, x); }

  /** The phase-3 radian trigonometry and the hyperbolics (ABI 0.5),
   *  same terms. sin, cos and tan take RADIANS. */
  sin() { return this._ctx.sin(this); }
  cos() { return this._ctx.cos(this); }
  tan() { return this._ctx.tan(this); }
  sinh() { return this._ctx.sinh(this); }
  cosh() { return this._ctx.cosh(this); }
  tanh() { return this._ctx.tanh(this); }
  asinh() { return this._ctx.asinh(this); }
  acosh() { return this._ctx.acosh(this); }
  atanh() { return this._ctx.atanh(this); }

  /** The rest of 754-2019 table 9.1 (ABI 0.6), same terms. `pown`,
   *  `compound` and `rootn` take an INTEGER exponent - a BigInt, or a
   *  safe integer this package widens - because 9.2.1 asks for one:
   *  "n is a finite integral value in integralFormat". `powr` is not
   *  `pow`: a negative base is invalid for every exponent. */
  exp2m1() { return this._ctx.exp2m1(this); }
  exp10() { return this._ctx.exp10(this); }
  exp10m1() { return this._ctx.exp10m1(this); }
  log2p1() { return this._ctx.log2p1(this); }
  log10p1() { return this._ctx.log10p1(this); }
  rsqrt() { return this._ctx.rsqrt(this); }
  powr(y) { return this._ctx.powr(this, y); }
  pown(n) { return this._ctx.pown(this, n); }
  compound(n) { return this._ctx.compound(this, n); }
  rootn(n) { return this._ctx.rootn(this, n); }

  /** The clause-5.12 character conversions out of this value, and the
   *  clause-9.7 payload reads (ABI 0.6). `toDecimal()` with no digit
   *  count is the EXACT conversion, which is what toString() already
   *  writes; a count asks for exactly that many significant digits,
   *  correctly rounded in this context's attribute. `toHex()` is the
   *  shortest sequence that represents the value exactly and never
   *  rounds. */
  toDecimal(opts) { return this._ctx.toDecimal(this, opts); }
  toHex() { return this._ctx.toHex(this); }
  getPayload() { return this._ctx.getPayload(this); }
  setPayload() { return this._ctx.setPayload(this); }
  setPayloadSignaling() { return this._ctx.setPayloadSignaling(this); }

  /** The augmented arithmetic of clause 9.5 (ABI 0.6). Each returns
   *  `{ r, e }` - the operation rounded, and the error that rounding
   *  made - under roundTiesTowardZero, which is 9.5's own direction and
   *  not one this context can change. */
  augmentedAdd(y) { return this._ctx.augmentedAdd(this, y); }
  augmentedSub(y) { return this._ctx.augmentedSub(this, y); }
  augmentedMul(y) { return this._ctx.augmentedMul(this, y); }

  lt(y) { return this._ctx.lt(this, y); }
  le(y) { return this._ctx.le(this, y); }
  eq(y) { return this._ctx.eq(this, y); }

  [Symbol.for("nodejs.util.inspect.custom")]() {
    const fi = this._ctx.format;
    const hex = this.bits.toString(16).padStart(fi.size * 2, "0");
    let d = this.toString();
    if (d.length > 44) d = d.slice(0, 41) + "...";
    return `Float(${fi.ieeeName}, 0x${hex} ~ ${d})`;
  }
}

// ---------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------

export class Context {
  /** Open a context. `format` is a width, precision or name;
   *  `rounding` is one of the five attribute names.
   *
   *  A cft_device is not thread-safe and cft.h says so. Node is one
   *  thread per process by default, but a worker gets its own module
   *  instance and should open its own context. */
  static async open(format, rounding = "rne") {
    const { M, C } = await loadModule();
    const fi = formatFor(format);
    const rnd = roundingFor(rounding);

    const size = C.formatSize(fi.code);
    if (size !== fi.size)
      throw new Error(
        `the module says ${fi.name} elements are ${size} bytes; this ` +
        `package has ${fi.size}. One of them is wrong and every buffer ` +
        `below would be the wrong length.`);

    return withScratch(M, (s) => {
      const pp = s.alloc(4);
      const st = C.openSoftware(pp);
      const dev = s.u32(pp);
      if (st !== 0 || !dev)
        throw new Error(`cft_open(software): ${C.strerror(st)}`);
      const mask = C.capsMask(dev) >>> 0;
      if (!(mask & (1 << fi.code)))
        throw new Error(`this device does not implement ${fi.name}`);
      return new Context(M, C, dev, fi, rnd);
    });
  }

  constructor(M, C, dev, fi, rnd) {
    this._M = M;
    this._C = C;
    this._dev = dev;
    this._fi = fi;
    this._rnd = rnd;
    /** The flags of the most recent call. */
    this.lastFlags = 0;
    /** Sticky across calls until clearFlags(), like MPFR's own model. */
    this.flags = 0;
  }

  get format() { return this._fi; }
  get precision() { return this._fi.prec; }
  get rounding() { return ROUNDING_NAME.get(this._rnd); }
  /** "software", or the device runtime's name, from cft_get_caps. */
  get backend() { return this._C.capsBackend(this._dev); }
  get abiVersion() {
    const v = this._C.abiVersion() >>> 0;
    return `${v >>> 16}.${v & 0xffff}`;
  }

  close() {
    if (this._dev) { this._C.close(this._dev); this._dev = 0; }
  }

  clearFlags() { this.flags = 0; }
  flagNames(flags) { return flagNames(flags ?? this.flags); }

  /** A context of the same shape with a different attribute. */
  withRounding(rounding) {
    return new Context(this._M, this._C, this._dev, this._fi,
                       roundingFor(rounding));
  }

  // -- construction ------------------------------------------------

  /** The general front door: a string is a decimal, a bigint is an
   *  integer, a number is a JS double, a Float of this format passes
   *  through. */
  from(v) {
    if (v instanceof Float) return this._same(v);
    if (typeof v === "string") return this.parse(v);
    if (typeof v === "bigint") return this.fromBigInt(v);
    if (typeof v === "number") return this.fromNumber(v);
    if (typeof v === "boolean")
      throw new TypeError("refusing a boolean as a number");
    throw new TypeError(`cannot use ${typeof v} as an operand`);
  }

  fromBytes(bytes) { return new Float(this, Uint8Array.from(bytes)); }

  /** An encoding given as an integer. No arithmetic meaning is
   *  attached to the integer; these are the bits. */
  fromBits(bits) {
    if (typeof bits !== "bigint")
      throw new TypeError("fromBits wants a BigInt of the raw encoding");
    if (bits < 0n || bits >= 1n << BigInt(this._fi.width))
      throw new RangeError(`${bits} does not fit ${this._fi.width} bits`);
    return new Float(this, bitsToBytes(this._fi, bits));
  }

  zero(sign = 0) { return this.fromBits(this._signBit(sign)); }

  inf(sign = 0) {
    const fi = this._fi;
    return this.fromBits(this._signBit(sign) |
      (((1n << BigInt(fi.expW)) - 1n) << BigInt(fi.manW)));
  }

  /** The canonical quiet NaN: sign 0, quiet bit, payload 0 - the one
   *  libcft arithmetic returns (docs/DETERMINISM.md). */
  nan() {
    const fi = this._fi;
    return this.fromBits((((1n << BigInt(fi.expW)) - 1n) << BigInt(fi.manW)) |
                         (1n << BigInt(fi.manW - 1)));
  }

  _signBit(sign) {
    return sign ? 1n << BigInt(this._fi.width - 1) : 0n;
  }

  _same(f) {
    if (f._ctx._fi !== this._fi)
      throw new TypeError(
        `mixed formats: a ${f._ctx._fi.ieeeName} operand in a ` +
        `${this._fi.ieeeName} context. Convert explicitly with ` +
        `convert() - implicit widening would have to choose semantics ` +
        `for you.`);
    return f;
  }

  // -- decimal strings ---------------------------------------------

  /** A decimal string. Exact if the value is representable; otherwise
   *  correctly rounded by ONE libcft call on exact operands; otherwise
   *  refused with the reason. See the file header. */
  parse(s) {
    const lex = lexDecimal(s);
    if (lex.kind === "nan") { this.lastFlags = 0; return this.nan(); }
    if (lex.kind === "inf") { this.lastFlags = 0; return this.inf(lex.sign); }

    const fi = this._fi;
    const { sign, M, E } = lex;
    // A zero decimal is a zero, and rounding never changes a sign, so
    // a negative decimal is -0 under every attribute (754). No library
    // call can tell you otherwise and none is asked.
    if (M === 0n) { this.lastFlags = 0; return this.zero(sign); }

    // A resource bound, not a semantic one. The steps below compute
    // 5^|E| exactly, and |E| comes from the caller. The widest thing
    // this package can legitimately be asked to read is the exact
    // decimal of the smallest binary256 subnormal - about 183,000
    // digits at E = -262,378 - so the limit is set well above that
    // and refuses the rest rather than allocating for it.
    const DIGIT_LIMIT = 1_000_000;
    if (!Number.isFinite(E) || Math.abs(E) > DIGIT_LIMIT ||
        M.toString().length > DIGIT_LIMIT)
      throw new RangeError(
        `${JSON.stringify(s.slice(0, 40))}...: this parser works in exact ` +
        `integers and refuses inputs beyond ${DIGIT_LIMIT} digits or a ` +
        `decimal exponent beyond +-${DIGIT_LIMIT} - past that the exact ` +
        `arithmetic costs more than the answer is worth`);

    // 1. exact? Then it is packing, not rounding.
    try {
      if (E >= 0)
        return this._exact(sign, M * 5n ** BigInt(E), E);
      const k = -E;
      const b = v5(M);
      if (b >= k) return this._exact(sign, M / 5n ** BigInt(k), -k);
    } catch (err) { if (!(err instanceof NotExact)) throw err; }

    // 2. one correctly-rounded library call on exact operands.
    if (E >= 0) {
      // value = (M * 2^E) * 5^E, both factors exact -> one cft_mul,
      // which rounds the exact product once.
      const rounded = this._tryPair(sign, M, E, 5n ** BigInt(E), 0,
                                    (a, b) => this.mul(a, b));
      if (rounded) return rounded;
      // or, when the whole value is an integer a 64-bit conversion can
      // take: cft_cvt_from_u64/i64 rounds it once.
      const N = M * 10n ** BigInt(E);
      if (N < 1n << 64n) {
        const f = this.fromBigInt(sign ? -N : N);
        return f;
      }
    } else {
      // value = (M5 * 2^-k) / 5^(k-b), both exact -> one cft_div.
      const k = -E;
      const b = v5(M);
      const rounded = this._tryPair(sign, M / 5n ** BigInt(b), -k,
                                    5n ** BigInt(k - b), 0,
                                    (a, d) => this.div(a, d));
      if (rounded) return rounded;
    }

    throw new RangeError(
      `${JSON.stringify(s)} is not representable in ${fi.ieeeName} and no ` +
      `single libcft call can round it, so it is refused rather than ` +
      `rounded here: a second implementation of the semantics is how ` +
      `bit-identity dies. The window is an exact numerator over an exact ` +
      `denominator in this format - about ` +
      `${Math.floor(fi.prec * Math.LN2 / Math.LN10)} significant digits ` +
      `with |exponent| up to ${pow5Limit(fi)} after cancelling fives. ` +
      `Shorten the digit string, use a wider format, or supply the value ` +
      `with fromBits(). An exact decimal of any magnitude - including ` +
      `everything toString() writes - is always accepted.`);
  }

  _exact(sign, m, e) {
    const bits = m === 0n ? this._signBit(sign)
                          : encodeExact(this._fi, sign, m, e);
    this.lastFlags = 0;
    return this.fromBits(bits);
  }

  /** Encode both operands exactly and let `op` (a libcft call) round
   *  once, or return null if either operand is not exact here. */
  _tryPair(sign, m1, e1, m2, e2, op) {
    let a, b;
    try {
      a = this.fromBits(encodeExact(this._fi, sign, m1, e1));
      b = this.fromBits(encodeExact(this._fi, 0, m2, e2));
    } catch (err) {
      if (err instanceof NotExact) return null;
      throw err;
    }
    return op(a, b);
  }

  // -- numbers and integers ----------------------------------------

  /** A JS number (a binary64). Widening is exact; narrowing to
   *  binary32 is rounded BY cft_convert in this context's attribute -
   *  this package never rounds a double itself. */
  fromNumber(x) {
    if (typeof x !== "number")
      throw new TypeError(`fromNumber wants a number, got ${typeof x}`);
    const buf = new Uint8Array(8);
    new DataView(buf.buffer).setFloat64(0, x, true);
    if (this._fi === F64) { this.lastFlags = 0; return new Float(this, buf); }
    const src = new Context(this._M, this._C, this._dev, F64, this._rnd);
    return this.convert(new Float(src, buf));
  }

  toNumber(x) {
    x = this._same(x);
    if (this._fi === F64)
      return new DataView(x.bytes.buffer).getFloat64(0, true);
    const dst = new Context(this._M, this._C, this._dev, F64, this._rnd);
    const y = dst.convert(x);
    this.lastFlags = dst.lastFlags;
    this.flags |= dst.lastFlags;
    return new DataView(y.bytes.buffer).getFloat64(0, true);
  }

  /** An integer. Values that fit 64 bits go through
   *  cft_cvt_from_i64/u64, so the rounding of a big one is the
   *  library's; wider integers are taken only when exact. */
  fromBigInt(n) {
    if (typeof n !== "bigint")
      throw new TypeError(`fromBigInt wants a BigInt, got ${typeof n}`);
    const M = this._M;
    const fi = this._fi;
    if (n >= -(2n ** 63n) && n < 2n ** 63n) {
      return withScratch(M, (s) => {
        const src = s.alloc(8), out = s.alloc(fi.size), fl = s.alloc(4);
        new BigInt64Array(M.HEAPU8.buffer, src, 1)[0] = n;
        const st = this._C.cvtFromI64(this._dev, fi.code, this._rnd,
                                      src, out, 1, fl);
        checkStatus(this._C, st, "cft_cvt_from_i64");
        return this._finish(s.get(out, fi.size), s.u32(fl));
      });
    }
    if (n >= 0n && n < 2n ** 64n) {
      return withScratch(M, (s) => {
        const src = s.alloc(8), out = s.alloc(fi.size), fl = s.alloc(4);
        new BigUint64Array(M.HEAPU8.buffer, src, 1)[0] = n;
        const st = this._C.cvtFromU64(this._dev, fi.code, this._rnd,
                                      src, out, 1, fl);
        checkStatus(this._C, st, "cft_cvt_from_u64");
        return this._finish(s.get(out, fi.size), s.u32(fl));
      });
    }
    const sign = n < 0n ? 1 : 0;
    const m = n < 0n ? -n : n;
    try {
      return this._exact(sign, m, 0);
    } catch (err) {
      if (!(err instanceof NotExact)) throw err;
      throw new RangeError(
        `${n} is beyond 64 bits and not exactly representable in ` +
        `${fi.ieeeName} (${err.message}). The library rounds integers ` +
        `through cft_cvt_from_i64/u64, which stops at 64 bits, and this ` +
        `package will not round the rest itself.`);
    }
  }

  /** convertToInteger (754 5.4.1) via cft_cvt_to_i64, direction from
   *  this context's attribute. `exact: true` selects the ...Exact
   *  family, the only one that reports inexact. The invalid cases
   *  deliver the contract's fixed RISC-V FCVT values - see cft.h. */
  toBigInt(x, { exact = false, unsigned = false } = {}) {
    x = this._same(x);
    const M = this._M;
    return withScratch(M, (s) => {
      const a = s.put(x.bytes), dst = s.alloc(8), fl = s.alloc(4);
      const fn = unsigned ? this._C.cvtToU64 : this._C.cvtToI64;
      const st = fn(this._dev, this._fi.code, this._rnd, exact ? 1 : 0,
                    a, dst, 1, fl);
      checkStatus(this._C, st, unsigned ? "cft_cvt_to_u64"
                                        : "cft_cvt_to_i64");
      const v = unsigned
        ? new BigUint64Array(M.HEAPU8.buffer, dst, 1)[0]
        : new BigInt64Array(M.HEAPU8.buffer, dst, 1)[0];
      this.lastFlags = s.u32(fl);
      this.flags |= this.lastFlags;
      return v;
    });
  }

  // -- the calls ---------------------------------------------------

  _finish(bytes, fl) {
    this.lastFlags = fl;
    this.flags |= fl;
    return new Float(this, bytes);
  }

  /** One cft_run over n elements. Operands are Uint8Array of
   *  n * size bytes, or null for the slots cft.h says are unused. */
  _run(op, a, b, c, n = 1) {
    const M = this._M, fi = this._fi;
    return withScratch(M, (s) => {
      const pa = a ? s.put(a) : 0;
      const pb = b ? s.put(b) : 0;
      const pc = c ? s.put(c) : 0;
      const pd = s.alloc(fi.size * n);
      const fl = s.alloc(4);
      const st = this._C.run(this._dev, op, fi.code, this._rnd,
                             pa, pb, pc, pd, n, fl, 0);
      checkStatus(this._C, st, `cft_run(${op})`);
      return { bytes: s.get(pd, fi.size * n), flags: s.u32(fl) };
    });
  }

  _run1(op, a, b, c) {
    const r = this._run(op, a?.bytes ?? null, b?.bytes ?? null,
                        c?.bytes ?? null);
    return this._finish(r.bytes, r.flags);
  }

  // cft.h's operand slots are not all (a, b): ADD and SUB read a and
  // c, MUL reads a and b. Passing the wrong slot is a silently wrong
  // answer, so each call names the slots it means.
  add(x, y) { return this._run1(OP_ADD, this.from(x), null, this.from(y)); }
  sub(x, y) { return this._run1(OP_SUB, this.from(x), null, this.from(y)); }
  mul(x, y) { return this._run1(OP_MUL, this.from(x), this.from(y), null); }
  fma(x, y, z) {
    return this._run1(OP_FMA, this.from(x), this.from(y), this.from(z));
  }
  neg(x) { return this._run1(OP_NEG, this.from(x), null, null); }
  abs(x) { return this._run1(OP_ABS, this.from(x), null, null); }
  copysign(x, y) {
    return this._run1(OP_COPYSIGN, this.from(x), this.from(y), null);
  }
  min(x, y) { return this._run1(OP_MIN, this.from(x), this.from(y), null); }
  max(x, y) { return this._run1(OP_MAX, this.from(x), this.from(y), null); }
  minnum(x, y) {
    return this._run1(OP_MINNUM, this.from(x), this.from(y), null);
  }
  maxnum(x, y) {
    return this._run1(OP_MAXNUM, this.from(x), this.from(y), null);
  }
  select(x, y, cond) {
    return this._run1(OP_SELECT, this.from(x), this.from(y), this.from(cond));
  }

  /** The quiet comparisons deliver 1.0 or +0.0, not a boolean, so a
   *  SELECT can consume them (cft.h). cmplt/cmple/cmpeq return that
   *  Float; lt/le/eq are the convenience booleans over it. */
  cmplt(x, y) { return this._run1(OP_CMPLT, this.from(x), this.from(y), null); }
  cmple(x, y) { return this._run1(OP_CMPLE, this.from(x), this.from(y), null); }
  cmpeq(x, y) { return this._run1(OP_CMPEQ, this.from(x), this.from(y), null); }
  lt(x, y) { return !this.cmplt(x, y).isZero; }
  le(x, y) { return !this.cmple(x, y).isZero; }
  eq(x, y) { return !this.cmpeq(x, y).isZero; }

  div(x, y) {
    const M = this._M, fi = this._fi;
    const a = this.from(x), b = this.from(y);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pb = s.put(b.bytes);
      const pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C.div(this._dev, fi.code, this._rnd, pa, pb, pd, 1,
                             fl, 0);
      checkStatus(this._C, st, "cft_div");
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  sqrt(x) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C.sqrt(this._dev, fi.code, this._rnd, pa, pd, 1, fl, 0);
      checkStatus(this._C, st, "cft_sqrt");
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  // -- the phase-1 transcendentals (ABI 0.3) -----------------------
  //
  // CORRECTLY ROUNDED at this context's precision under this context's
  // attribute, with 754-2019 clause 9.2.1's special values and exact
  // flags. That is the whole reason they belong in a determinism
  // contract: the result is defined by the mathematics, so every
  // correct implementation agrees bit for bit and this one is scorable
  // against any of them. An "accurate" transcendental - the ordinary
  // kind, faithful to an ulp or so - is precisely the thing this
  // project exists to replace, because two of them never agree.
  //
  // Nothing is computed here, as everywhere else in this file: each
  // call is one cftw_* call on bytes. The exactness rules are the
  // library's too - exp only at zero, log only at one, exp2 at an
  // integer the format's range holds, log2 at a power of two, log10 at
  // a representable power of ten, pow at a dyadic result, hypot at a
  // perfect square - decided there by exact arithmetic rather than
  // here by a tolerance.

  _transcend1(fn, x) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pd = s.alloc(fi.size), fl = s.alloc(4);
      // no bus_out: a host operation issues no device pass (cft.h)
      const st = this._C[fn](this._dev, fi.code, this._rnd, pa, pd, 1, fl);
      checkStatus(this._C, st, `cft_${fn}`);
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  _transcend2(fn, x, y) {
    const M = this._M, fi = this._fi;
    const a = this.from(x), b = this.from(y);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pb = s.put(b.bytes);
      const pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C[fn](this._dev, fi.code, this._rnd, pa, pb, pd, 1, fl);
      checkStatus(this._C, st, `cft_${fn}`);
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  /** e ** x. Exact only at x = 0, where exp(0) = 1 raises nothing;
   *  exp(-inf) is +0. */
  exp(x) { return this._transcend1("exp", x); }

  /** exp(x) - 1. expm1(+-0) is +-0 - the operand's sign, which is half
   *  of why this function exists - and expm1(-inf) is -1. */
  expm1(x) { return this._transcend1("expm1", x); }

  /** 2 ** x, exact when x is an integer whose power the format holds;
   *  exp2(-inf) is +0. */
  exp2(x) { return this._transcend1("exp2", x); }

  /** The natural logarithm. log(+-0) is -inf and signals divideByZero;
   *  a finite negative operand is invalid and delivers a quiet NaN. */
  log(x) { return this._transcend1("log", x); }

  /** log(1 + x). log1p(+-0) is +-0; log1p(-1) is -inf with
   *  divideByZero; x < -1 is invalid. */
  log1p(x) { return this._transcend1("log1p", x); }

  /** Base-two logarithm, exact at the powers of two. */
  log2(x) { return this._transcend1("log2", x); }

  /** Base-ten logarithm, exact at the powers of ten the format
   *  represents. */
  log10(x) { return this._transcend1("log10", x); }

  /** x ** y, 754-2019's `pow`: pow(x, +-0) is 1 for ANY x including a
   *  quiet NaN or an infinity, pow(1, y) is 1 for ANY y, and
   *  pow(-1, +-inf) is 1. A finite negative x with a non-integer y is
   *  invalid. A SIGNALING NaN is not covered by those rows and raises
   *  invalid like everywhere else in this contract - deliberately
   *  unlike C's pow(sNaN, 0), and cft.h says so. */
  pow(x, y) { return this._transcend2("pow", x, y); }

  /** sqrt(x^2 + y^2) as if computed with unbounded range and rounded
   *  once, so it neither overflows nor underflows on the way.
   *  hypot(+-inf, y) is +inf for any y, INCLUDING a quiet NaN. */
  hypot(x, y) { return this._transcend2("hypot", x, y); }

  // -- the phase-2 trigonometrics (ABI 0.4) ------------------------
  //
  // The same promise on the same machinery, and what these eleven have
  // in common is what they do NOT need: an argument reduction against
  // pi. sinPi's reduction is x mod 2 and every operand is a dyadic
  // rational, so it is a mask on the encoding and exact at every
  // magnitude; the inverses take an argument in [-1, 1] or a ratio and
  // meet pi only as a factor of the answer. sin, cos and tan of a
  // RADIAN argument are a different problem and are not here (cft.h).
  //
  // The exact cases are an enumeration with a proof behind it rather
  // than a tolerance: Niven's theorem bounds the forward set to the
  // half- and quarter-integers, Hermite-Lindemann bounds the inverses
  // to their zeros, and the Pi-forms get a larger table because
  // dividing by pi turns those multiples into dyadic rationals.
  // docs/TRANSCENDENTALS.md carries both arguments in full.

  /** sin(pi*x). The reduction is exact at every magnitude. sinPi(+-0)
   *  is +-0, and sinPi of an integer n is a zero with the sign of the
   *  ARGUMENT - sinPi(1) is +0 and sinPi(-1) is -0. An infinity is
   *  invalid: there is no limit. */
  sinpi(x) { return this._transcend1("sinpi", x); }

  /** cos(pi*x). cosPi(n) is (-1)^n and cosPi(n + 1/2) is +0 for every
   *  n and both signs - cosPi is even, so that zero has no sign to
   *  carry. An infinity is invalid. */
  cospi(x) { return this._transcend1("cospi", x); }

  /** tan(pi*x), which is sinPi/cosPi in every respect: tanPi(1) is -0,
   *  and a half-integer is a pole - +-infinity with divideByZero, 7.3's
   *  rule for an exact infinity from finite operands. It cannot
   *  overflow at any format here. */
  tanpi(x) { return this._transcend1("tanpi", x); }

  /** The inverse sine, exact only at +-0. asin(1) is pi/2 and inexact;
   *  |x| > 1 is invalid, infinities included. */
  asin(x) { return this._transcend1("asin", x); }

  /** The inverse cosine, exact only at acos(1) = +0; acos(-1) is pi
   *  and inexact. |x| > 1 is invalid. */
  acos(x) { return this._transcend1("acos", x); }

  /** The inverse tangent, exact only at +-0. atan(+-inf) is +-pi/2 and
   *  inexact. Every real is in range, so there is no domain error. */
  atan(x) { return this._transcend1("atan", x); }

  /** asin(x)/pi. Exact at asinPi(+-0) = +-0 and asinPi(+-1) = +-1/2.
   *  asinPi(1/2) is exactly 1/6, which is rational but NOT a dyadic
   *  rational - so it is inexact, and still decidable. */
  asinpi(x) { return this._transcend1("asinpi", x); }

  /** acos(x)/pi. Exact at acosPi(1) = +0, acosPi(+-0) = 1/2 and
   *  acosPi(-1) = 1; acosPi(1/2) is 1/3 and inexact for asinPi's
   *  reason. |x| > 1 is invalid. */
  acospi(x) { return this._transcend1("acospi", x); }

  /** atan(x)/pi. Exact at atanPi(+-0) = +-0, atanPi(+-1) = +-1/4 and
   *  atanPi(+-inf) = +-1/2 - that last one exactly, and raising
   *  nothing, where atan(+-inf) is an inexact +-pi/2. */
  atanpi(x) { return this._transcend1("atanpi", x); }

  /** atan2(y, x) - y FIRST, the C order and cft.h's, because that is
   *  what every caller of atan2 expects. atan2(+-0, -0) is +-pi and
   *  inexact: a minus-zero denominator names the negative real axis,
   *  which is the row implementations most often miss. atan2(+-0, +0)
   *  is +-0; atan2(y, +-0) is +-pi/2; atan2(+-inf, +inf) is +-pi/4 and
   *  (+-inf, -inf) is +-3pi/4. Unlike pow, a quiet NaN operand does not
   *  lose to this table: atan2 of a NaN is a NaN. */
  atan2(y, x) { return this._transcend2("atan2", y, x); }

  /** atan2(y, x)/pi, y first. Exact on every axis and every diagonal -
   *  |y| == |x| is an exact comparison on the encoding - giving 0,
   *  +-1/4, +-1/2, +-3/4 and +-1. atan2Pi(+-0, -0) is +-1 exactly where
   *  atan2 of the same operands is an inexact +-pi, which is in one
   *  line why this is a separate function. */
  atan2pi(y, x) { return this._transcend2("atan2pi", y, x); }

  // -- the phase-3 radian trigonometry and the hyperbolics (ABI 0.5) --
  //
  // What phase 2 was defined to exclude: sin, cos and tan of a RADIAN
  // argument, reduced against pi INSIDE the library - a Payne-Hanek
  // reduction against a stored 2/pi of a quarter of a million bits, at
  // any magnitude the format holds - and the six hyperbolics, which
  // are exp and log in different clothes and need no reduction at all.
  // Same promise, same machinery, same loud refusal past what the
  // constant covers (cft.h, docs/TRANSCENDENTALS.md).
  //
  // The exact cases are the zeros, and that is a theorem
  // (Hermite-Lindemann): sin, tan, sinh, tanh, asinh and atanh at +-0,
  // cos and cosh at 0 (giving 1), acosh at 1 (giving +0). Everything
  // else is inexact.

  /** sin(x), x in RADIANS. Exact only at +-0, where it is +-0; an
   *  infinity is invalid, there being no limit. */
  sin(x) { return this._transcend1("sin", x); }

  /** cos(x) in radians. cos(+-0) = 1 is the only exact case; an
   *  infinity is invalid. */
  cos(x) { return this._transcend1("cos", x); }

  /** tan(x) in radians. Exact only at +-0. No representable argument is
   *  a pole (an odd multiple of pi/2 is irrational), so it never
   *  signals divideByZero - but it can overflow near one. */
  tan(x) { return this._transcend1("tan", x); }

  /** sinh(x). Odd, exact only at +-0, sinh(+-inf) = +-inf, and it
   *  overflows for a large argument like any exponential. */
  sinh(x) { return this._transcend1("sinh", x); }

  /** cosh(x). Even, never below 1, exact only at cosh(+-0) = 1. */
  cosh(x) { return this._transcend1("cosh", x); }

  /** tanh(x). Odd, exact at +-0, and tanh(+-inf) = +-1 EXACTLY - a
   *  limit that happens to be representable, raising nothing. */
  tanh(x) { return this._transcend1("tanh", x); }

  /** asinh(x). Odd, exact only at +-0; asinh(+-inf) = +-inf. */
  asinh(x) { return this._transcend1("asinh", x); }

  /** acosh(x) on [1, +inf). acosh(1) = +0 exactly; every x below 1 is
   *  invalid - zeros, negatives and -inf included. */
  acosh(x) { return this._transcend1("acosh", x); }

  /** atanh(x) on (-1, 1). Exact only at +-0; atanh(+-1) is +-inf with
   *  divideByZero (7.3's exact infinity, the row tanPi takes at a
   *  pole); |x| > 1 is invalid, infinities included. */
  atanh(x) { return this._transcend1("atanh", x); }

  // -- the rest of table 9.1 (ABI 0.6) -----------------------------
  //
  // With these ten the library implements every operation 754-2019
  // table 9.1 lists for the binary formats. Same promise on the same
  // machinery: correctly rounded at this context's precision under its
  // attribute, 9.2.1's special values, exact flags, nothing computed
  // here. What is new is EXACTNESS, not machinery - each has a larger
  // exact-case table than the function it is built from, proved closed
  // in docs/TRANSCENDENTALS.md before the Ziv loop under it is allowed
  // to run, because a true value sitting on a rounding boundary is
  // exactly where that loop does not terminate.

  /** 2^x - 1. EXACT at every integer argument: 2^n - 1 is a dyadic
   *  rational for every n. Past |n| > p+1 the value is still known
   *  exactly and is delivered by a side rather than by a boundary. */
  exp2m1(x) { return this._transcend1("exp2m1", x); }

  /** 10^x, exact at the non-negative integers whose 5^n fits in p+1
   *  bits. A negative power of ten is not dyadic at all, so none of
   *  those is exact. */
  exp10(x) { return this._transcend1("exp10", x); }

  /** 10^x - 1, exact at the non-negative integers whose 10^n - 1 fits
   *  in p+1 bits. */
  exp10m1(x) { return this._transcend1("exp10m1", x); }

  /** log2(1 + x), with 1 + x formed EXACTLY on the encoding and never
   *  as a rounded sum - which is the whole reason this function
   *  exists. Exact where 1 + x is a power of two; log2p1(-1) is -inf
   *  with divideByZero, and an operand below -1 is invalid. */
  log2p1(x) { return this._transcend1("log2p1", x); }

  /** log10(1 + x), the same construction and the same edges, exact
   *  where 1 + x is a power of ten. */
  log10p1(x) { return this._transcend1("log10p1", x); }

  /** 1/sqrt(x). Exact exactly at the even powers of two, and it can
   *  neither overflow nor underflow at any format. rSqrt(+-0) is
   *  +-INFINITY with divideByZero and THE SIGN SURVIVES: rSqrt(-0) is
   *  -infinity, which is the standard's row and not MPFR's. */
  rsqrt(x) { return this._transcend1("rsqrt", x); }

  /** x^y on [0, +inf) x [-inf, +inf]. powr is NOT pow, and the
   *  differences are the reason it is a separate operation: powr(x, y)
   *  for x < 0 is invalid for EVERY y, a NaN included; powr(+-0, +-0),
   *  powr(+inf, +-0) and powr(+1, +-inf) are invalid; and
   *  powr(qNaN, y) is a quiet NaN where pow(qNaN, 0) is 1. */
  powr(x, y) { return this._transcend2("powr", x, y); }

  /** x^n for an INTEGER n - a BigInt, or a safe integer widened here.
   *  pown(x, 0) is 1 for any x that is not a signaling NaN, an
   *  infinity and a quiet NaN included. */
  pown(x, n) { return this._transcendInt("pown", x, n); }

  /** (1 + x)^n, integer n, with 1 + x formed exactly. compound(x, 0)
   *  is 1 "for x >= -1 or quiet NaN", so an x BELOW -1 with n = 0 is
   *  invalid rather than 1; compound(-1, n) is +inf with divideByZero
   *  for n < 0 and +0 for n > 0; compound(+-0, n) is 1. */
  compound(x, n) { return this._transcendInt("compound", x, n); }

  /** x^(1/n), integer n. rootn(x, 0) is invalid - zero is outside the
   *  domain for every x. rootn(x, 1) is x exactly and silently.
   *  rootn(x, 2) is squareRoot(x) on every input EXCEPT x = -0, where
   *  the standard's own NOTE says they differ: rootn(-0, 2) is +0 by
   *  the even-n row where squareRoot(-0) is -0. */
  rootn(x, n) { return this._transcendInt("rootn", x, n); }

  /** One of the three with an integer exponent, at n == 1. The int64
   *  travels in a one-element heap array, which is the shape cft.h
   *  gives it - `const int64_t *n` beside the encoding array, never a
   *  scalar parameter, so it needs no BigInt across the wasm
   *  boundary. */
  _transcendInt(fn, x, n) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    const nn = asI64(n, `${fn}'s exponent`);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pn = s.putI64([nn]);
      const pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C[fn](this._dev, fi.code, this._rnd, pa, pn, pd, 1, fl);
      checkStatus(this._C, st, `cft_${fn}`);
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  // -- clause 5.12's characters and clause 9.7's payloads (ABI 0.6) --
  //
  // Strings are JavaScript strings at this boundary and heap bytes
  // below it, and the conversion in both directions is the library's:
  // this package writes the sequence into wasm memory and hands the
  // pointer over, or asks the library how long its answer is and reads
  // it back. It does NOT parse a decimal itself here - Context.parse()
  // above is the older, narrower path that packs an exact value or
  // rounds it with one arithmetic call, and it REFUSES what it cannot
  // do that way; fromDecimal() is the library's own 5.12 parser, with
  // no window and no refusal except the syntax's own.
  //
  // THE SIZING PROTOCOL IS THE C's, EXACTLY. cft.h: a NULL buffer with
  // cap 0 asks for the required length including the NUL, a buffer too
  // small is CFT_ERR_INVALID_ARGUMENT with the length set and NOTHING
  // written, and *len is set either way. This package performs both
  // calls and hands back a string, which is what a JS caller wants -
  // but it does not invent a different contract underneath, and
  // toDecimalInto() below exposes the raw protocol so a caller can see
  // the refusal happen. test.mjs drives both.

  /** Pmin (5.12.2) for this context's format: 9, 17, 36, 73. The digit
   *  count at which a to-decimal / from-decimal round trip under a
   *  round-to-nearest attribute is GUARANTEED to reproduce the
   *  encoding. Fewer digits than this is not a rounding error, it is a
   *  different number. From the library, not tabulated here. */
  get decimalDigits() { return this._C.decimalDigits(this._fi.code); }

  /** One decimal sequence -> an encoding, correctly rounded in this
   *  context's attribute by the library's own 5.12 parser. A sequence
   *  outside the syntax is refused with the library's status, not
   *  guessed at. */
  fromDecimal(s) { return this._fromChar("fromDecimalChar", s); }

  /** One hexadecimal sequence -> an encoding. A hex sequence's value is
   *  dyadic, so exact is the common case; more bits than the format
   *  holds round once. The binary exponent is REQUIRED by 5.12.3's
   *  grammar, and a sequence without one is refused. */
  fromHex(s) { return this._fromChar("fromHexChar", s); }

  _fromChar(which, s) {
    if (typeof s !== "string")
      throw new TypeError(`${which} wants a string, got ${typeof s}`);
    const M = this._M, fi = this._fi;
    return withScratch(M, (st_) => {
      const pin = st_.putStringArray([s]);
      const pd = st_.alloc(fi.size), bad = st_.alloc(4), fl = st_.alloc(4);
      const st = this._C[which](this._dev, fi.code, this._rnd, pin, pd, 1,
                                bad, fl);
      if (st !== 0)
        throw new SyntaxError(
          `${JSON.stringify(s)} is not a sequence 754-2019 clause 5.12 ` +
          `accepts (the library refused element ${st_.u32(bad)}): ` +
          `${this._C.strerror(st)}. The syntax is an optional sign, digits ` +
          `with an optional point and an optional exponent - a hex ` +
          `sequence needs 0x and a REQUIRED binary exponent - or the words ` +
          `inf / infinity / nan / snan with an optional (payload).`);
      return this._finish(st_.get(pd, fi.size), st_.u32(fl));
    });
  }

  /** An encoding -> a decimal sequence. `digits: 0` (the default) is
   *  the EXACT conversion 5.12.2 asks for: every digit of the exact
   *  value, trailing zeros removed, no attribute consulted and no flag
   *  raised. It always terminates and it can be long - about 183,000
   *  significant digits for the smallest binary256 subnormal.
   *  `digits: h` for h >= 1 asks for exactly h significant digits,
   *  correctly rounded under this context's attribute with trailing
   *  zeros KEPT, and raises inexact when a digit was dropped. */
  toDecimal(x, { digits = 0 } = {}) {
    const a = this.from(x);
    const d = asI64(digits, "toDecimal's digit count");
    if (d < 0n) throw new RangeError("toDecimal's digit count is a count");
    return withScratch(this._M, (s) => {
      const pa = s.put(a.bytes);
      const { text, flags } = this._sized(
        (out, cap, len, fl) =>
          this._C.toDecimalChar(this._dev, this._fi.code, this._rnd, pa,
                                Number(d), out, cap, len, fl),
        s, "cft_to_decimal_char", true);
      this.lastFlags = flags;
      this.flags |= flags;
      return text;
    });
  }

  /** An encoding -> the shortest hexadecimal sequence that represents
   *  it EXACTLY (5.12.3, "in the absence of an explicit precision
   *  specification"). Canonical: one leading 1, no trailing zeros, an
   *  explicitly signed binary exponent - so a subnormal prints with
   *  its true exponent, 0x1p-149 for the smallest binary32. Exact
   *  always, so no attribute is consulted and no flag can be raised;
   *  the library gives this one no flag word and none is invented. */
  toHex(x) {
    const a = this.from(x);
    return withScratch(this._M, (s) => {
      const pa = s.put(a.bytes);
      return this._sized(
        (out, cap, len) =>
          this._C.toHexChar(this._dev, this._fi.code, pa, out, cap, len),
        s, "cft_to_hex_char", false).text;
    });
  }

  /** The two-call sizing protocol, run: ask with a NULL buffer and a
   *  zero capacity, allocate exactly what the library asked for, call
   *  again. The refusal path is not smoothed over - a status that is
   *  neither the sizing refusal nor OK is raised - because the whole
   *  point of exposing the protocol is that a caller can tell the two
   *  apart. */
  _sized(call, s, what, hasFlags) {
    const len = s.alloc(4);
    const fl = hasFlags ? s.alloc(4) : 0;
    const ask = call(0, 0, len, fl);
    const need = s.u32(len);
    if (ask === 0)
      throw new Error(
        `${what}: a NULL buffer with capacity 0 returned success, where ` +
        `cft.h's sizing protocol says it reports the required length and ` +
        `refuses. The module and this package disagree about the protocol.`);
    if (need < 2)
      throw new Error(`${what}: required length ${need} - a sequence is at ` +
                      `least one character and a NUL`);
    const out = s.alloc(need);
    const st = call(out, need, len, fl);
    checkStatus(this._C, st, what);
    return { text: s.str(out), len: need, flags: hasFlags ? s.u32(fl) : 0 };
  }

  /** The sizing protocol with the buffer the CALLER chose, so the
   *  refusal is visible rather than handled. Returns
   *  `{ status, len, text }`: `status` 0 with the text on success, and
   *  the library's CFT_ERR_INVALID_ARGUMENT with `len` set and no text
   *  when `cap` is too small - which is the contract's answer, because
   *  this library does not truncate a number. `cap: 0` is the sizing
   *  question itself. */
  toDecimalInto(x, cap, { digits = 0 } = {}) {
    const a = this.from(x);
    const d = asI64(digits, "toDecimalInto's digit count");
    return withScratch(this._M, (s) => {
      const pa = s.put(a.bytes);
      const len = s.alloc(4), fl = s.alloc(4);
      const out = cap > 0 ? s.alloc(cap) : 0;
      const st = this._C.toDecimalChar(this._dev, this._fi.code, this._rnd,
                                       pa, Number(d), out, cap, len, fl);
      const flags = s.u32(fl);
      this.lastFlags = flags;
      this.flags |= flags;
      return { status: st, len: s.u32(len), flags,
               text: st === 0 ? s.str(out) : null };
    });
  }

  /** getPayload (9.7): a NaN's payload as a floating-point integer;
   *  anything that is not a NaN gives -1, which is 9.7's own answer.
   *  Non-computational - it signals nothing, so there is no flags
   *  argument and none is invented. */
  getPayload(x) { return this._payload("getPayload", x); }

  /** setPayload (9.7): a non-negative floating-point integer in the
   *  admissible set 0 .. 2^(manW - 1) - 1 becomes a quiet NaN carrying
   *  it; ANYTHING else becomes +0. The test is on the VALUE, so -0
   *  passes it as the integer zero. */
  setPayload(x) { return this._payload("setPayload", x); }

  /** setPayloadSignaling (9.7): the same with a signaling NaN, where
   *  payload 0 is NOT admissible - payload 0 with the quiet bit clear
   *  is an infinity encoding - so setPayloadSignaling(+-0) is +0. */
  setPayloadSignaling(x) { return this._payload("setPayloadSignaling", x); }

  _payload(which, x) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pd = s.alloc(fi.size);
      const st = this._C[which](this._dev, fi.code, pa, pd, 1);
      checkStatus(this._C, st, `cft_${which}`);
      return new Float(this, s.get(pd, fi.size));
    });
  }

  // -- the augmented arithmetic (clause 9.5, ABI 0.6) --------------
  //
  // A PAIR out: r is the operation rounded and e is the error that
  // rounding made, and together they carry the exact result the format
  // alone cannot hold. That is what a compensated summation or an
  // exactly-rounded dot product is built out of, and what those
  // algorithms currently reconstruct by hand from TwoSum and Dekker
  // splitting - correctly only under assumptions a compiler is free to
  // break.
  //
  // NO ROUNDING ATTRIBUTE IS ACCEPTED, and this context's attribute is
  // not consulted either. 9.5 fixes the direction itself:
  // roundTiesTowardZero, which is not one of clause 4.3's five, so
  // there is nothing to pass. The tie rule differs from
  // roundTiesToEven only at an exact midpoint whose lower neighbour is
  // odd - so an implementation that quietly used RNE would pass every
  // test that did not aim there, which is why the vector sets aim
  // there at every binade edge.

  /** `{ r, e }` of augmentedAddition(x, y). The sign of a zero e is
   *  the sign of r when the residual is exactly zero, so
   *  augmentedAdd(-3, 0) is (-3, -0) and augmentedAdd(3, -3) is
   *  (+0, +0). */
  augmentedAdd(x, y) { return this._augmented("augmentedAdd", x, y); }

  /** `{ r, e }` of augmentedSubtraction(x, y): x + (-y) with every
   *  rule of the addition, the signed zeros included. */
  augmentedSub(x, y) { return this._augmented("augmentedSub", x, y); }

  /** `{ r, e }` of augmentedMultiplication(x, y). This is the one
   *  operation of the three whose e can fail to be representable -
   *  9.5's residual with non-zero digits strictly between
   *  +-b^(emin-p+1) - and it delivers that residual ROUNDED, raising
   *  underflow and inexact. It is the only case in which r + e is not
   *  exactly x * y. */
  augmentedMul(x, y) { return this._augmented("augmentedMul", x, y); }

  _augmented(which, x, y) {
    const M = this._M, fi = this._fi;
    const a = this.from(x), b = this.from(y);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pb = s.put(b.bytes);
      // r and e must not overlap each other - cft.h refuses the same
      // pointer for both - so they are two allocations, never one.
      const pr = s.alloc(fi.size), pe = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C[which](this._dev, fi.code, pa, pb, pr, pe, 1, fl);
      checkStatus(this._C, st, `cft_${which}`);
      const flags = s.u32(fl);
      this.lastFlags = flags;
      this.flags |= flags;
      return { r: new Float(this, s.get(pr, fi.size)),
               e: new Float(this, s.get(pe, fi.size)) };
    });
  }

  // -- the scaled product reductions (clause 9.4, ABI 0.6) ---------
  //
  // A pair again, and a different one: a significand in +-[1, 2) and
  // an INT64 SCALE. The scale comes back as a BigInt, for the reason
  // every integer in this package does - it is int64_t in the
  // contract, a JS number stops being an integer above 2^53, and a
  // scale that silently lost its low bits would be a wrong answer
  // wearing a plausible one's clothes. It is small in practice (a leaf
  // contributes at most emax + p - 1 = 262,379 at fp256), which is an
  // argument for a Number and not a good enough one: the contract's
  // type is the one that survives the case nobody tested.

  /** `{ pr, sf }` with scaleB(pr, sf) ~ the product of the array.
   *  Cannot overflow or underflow, by construction rather than by
   *  luck: every node's operands are in +-[1, 2), so no product can
   *  leave any rung of the ladder. n == 0 gives pr = 1 and sf = 0
   *  without exception - 9.4 fixes that, the multiplicative identity
   *  where an empty sum gives the additive one. */
  scaledProd(a) { return this._scaledProd("scaledProd", a, null); }

  /** `{ pr, sf }` over the products of (a[i] + b[i]). The leaf is ONE
   *  contract rounding of that sum in this context's attribute, and it
   *  is the only place this operation can signal overflow or
   *  underflow - never the product tree. */
  scaledProdSum(a, b) { return this._scaledProd("scaledProdSum", a, b); }

  /** `{ pr, sf }` over the products of (a[i] - b[i]), a first. */
  scaledProdDiff(a, b) { return this._scaledProd("scaledProdDiff", a, b); }

  _scaledProd(which, a, b) {
    const M = this._M, fi = this._fi;
    if (!Array.isArray(a))
      throw new TypeError(`${which} reduces an array of operands`);
    if (b && b.length !== a.length)
      throw new RangeError(`operand arrays differ in length: ` +
                           `${a.length} and ${b.length}`);
    const n = a.length;
    const pack = (arr) => {
      if (!arr) return null;
      const buf = new Uint8Array(fi.size * n);
      arr.forEach((v, i) => buf.set(this.from(v).bytes, i * fi.size));
      return buf;
    };
    const ab = pack(a), bb = pack(b);
    return withScratch(M, (s) => {
      const pa = n ? s.put(ab) : 0;
      const pb = bb && n ? s.put(bb) : 0;
      const pr = s.alloc(fi.size), psf = s.alloc(8), fl = s.alloc(4);
      const st = b
        ? this._C[which](this._dev, fi.code, this._rnd, pa, pb, pr, psf, n, fl)
        : this._C[which](this._dev, fi.code, this._rnd, pa, pr, psf, n, fl);
      checkStatus(this._C, st, `cft_${which}`);
      const flags = s.u32(fl);
      this.lastFlags = flags;
      this.flags |= flags;
      return { pr: new Float(this, s.get(pr, fi.size)), sf: s.i64(psf) };
    });
  }

  // -- clause 5 ----------------------------------------------------

  /** roundToIntegral. exact: true is roundToIntegralExact, the one
   *  that signals inexact when the value changed. */
  rint(x, { exact = false } = {}) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C.rint(this._dev, fi.code, this._rnd, exact ? 1 : 0,
                              pa, pd, 1, fl, 0);
      checkStatus(this._C, st, "cft_rint");
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  /** scaleB: x * 2^n, one rounding. n is a BigInt or a safe integer;
   *  it is int64_t in the contract and crosses into wasm as two
   *  halves. */
  scaleb(x, n) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    const nv = BigInt(n);
    if (nv < -(2n ** 63n) || nv >= 2n ** 63n)
      throw new RangeError(`scaleb's exponent is int64_t; ${nv} does not fit`);
    const u = BigInt.asUintN(64, nv);
    const lo = Number(u & 0xffffffffn);
    const hi = Number(BigInt.asIntN(32, u >> 32n));
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C.scaleb(this._dev, fi.code, this._rnd, pa, lo, hi,
                                pd, 1, fl, 0);
      checkStatus(this._C, st, "cft_scaleb");
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  /** The signaling comparisons: the same predicate values as the
   *  quiet ones, but invalid for ANY NaN operand. */
  cmpSig(cmp, x, y) {
    const M = this._M, fi = this._fi;
    const a = this.from(x), b = this.from(y);
    const op = { lt: OP_CMPLT, le: OP_CMPLE, eq: OP_CMPEQ }[cmp];
    if (op === undefined)
      throw new TypeError(`cmpSig wants "lt", "le" or "eq", got ` +
                          `${JSON.stringify(cmp)}`);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pb = s.put(b.bytes);
      const pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C.cmpSig(this._dev, op, fi.code, pa, pb, pd, 1, fl, 0);
      checkStatus(this._C, st, "cft_cmp_sig");
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  /** convertFormat: THIS context's format is the destination. */
  convert(x) {
    if (!(x instanceof Float))
      throw new TypeError("convert wants a Float");
    const M = this._M, src = x._ctx._fi, dst = this._fi;
    return withScratch(M, (s) => {
      const pa = s.put(x.bytes), pd = s.alloc(dst.size), fl = s.alloc(4);
      const st = this._C.convert(this._dev, src.code, dst.code, this._rnd,
                                 pa, pd, 1, fl);
      checkStatus(this._C, st, "cft_convert");
      return this._finish(s.get(pd, dst.size), s.u32(fl));
    });
  }

  logb(x) { return this._unary("logb", x); }
  nextUp(x) { return this._unary("nextUp", x); }
  nextDown(x) { return this._unary("nextDown", x); }

  _unary(which, x) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C[which](this._dev, fi.code, pa, pd, 1, fl);
      checkStatus(this._C, st, `cft_${which}`);
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  /** class (754 5.7.2). Non-computational: it signals nothing, so
   *  there is no flags argument and none is invented. */
  classify(x) {
    const M = this._M, fi = this._fi;
    const a = this.from(x);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pc = s.alloc(1);
      const st = this._C.classOf(this._dev, fi.code, pa, pc, 1);
      checkStatus(this._C, st, "cft_class");
      const v = M.HEAPU8[pc];
      return CLASS_NAMES[v] ?? `class ${v}`;
    });
  }

  /** totalOrder (754 5.10), as the 1.0/+0.0 predicate; `mag` selects
   *  totalOrderMag. Signals nothing on anything, which is what makes
   *  it the sort key compareQuiet cannot be. */
  totalOrder(x, y, { mag = false } = {}) {
    const M = this._M, fi = this._fi;
    const a = this.from(x), b = this.from(y);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pb = s.put(b.bytes), pd = s.alloc(fi.size);
      const fn = mag ? this._C.totalOrderMag : this._C.totalOrder;
      const st = fn(this._dev, fi.code, pa, pb, pd, 1);
      checkStatus(this._C, st, "cft_total_order");
      return !new Float(this, s.get(pd, fi.size)).isZero;
    });
  }

  /** remainder (754 5.3.1). Always exact; no attribute is consumed
   *  because none is used. */
  rem(x, y) {
    const M = this._M, fi = this._fi;
    const a = this.from(x), b = this.from(y);
    return withScratch(M, (s) => {
      const pa = s.put(a.bytes), pb = s.put(b.bytes);
      const pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C.rem(this._dev, fi.code, pa, pb, pd, 1, fl);
      checkStatus(this._C, st, "cft_rem");
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }

  // -- arrays ------------------------------------------------------

  /** One library call over a whole array: the call shape a device
   *  wants, and the reason a batch API exists at all. `op` is a name
   *  from cft.h - an opcode ("add", "mul", "fma", ...), one of the
   *  thirty-nine transcendentals ("exp", "pow", "sinpi", "atan2",
   *  "rootn", ...), one of the three augmented operations, or one of
   *  the payload operations; operands are arrays of Float or anything
   *  from() accepts, or null for an unused slot. For atan2 and atan2pi
   *  the first array is y and the second is x, as everywhere else in
   *  this package. For pown, compound and rootn the SECOND array is
   *  the integer exponents - BigInts, or safe integers - because the
   *  contract's second operand there is an int64 and not an encoding.
   *
   *  The transcendentals take a different C entry point, not an opcode
   *  in cft_run, so they are dispatched by name below. They are
   *  correctly rounded, which means the array answer IS the scalar
   *  answer element by element: there is no vectorised approximation
   *  here to drift from a scalar path, and test.mjs checks that rather
   *  than assuming it.
   *
   *  The three augmented operations return `{ r, e }` of two arrays
   *  rather than one array, because they have two outputs; the payload
   *  three return one array and no flags, because 9.7 says they signal
   *  nothing. Both are the C's shapes carried up, not new ones. */
  map(op, a, b = null, c = null) {
    const fi = this._fi;
    const lens = [a, b, c].filter(Boolean).map((v) => v.length);
    if (!lens.length) throw new TypeError("map needs at least one operand");
    const n = lens[0];
    if (lens.some((l) => l !== n))
      throw new RangeError(`operand arrays differ in length: ${lens}`);
    const pack = (arr) => {
      if (!arr) return null;
      const buf = new Uint8Array(fi.size * n);
      arr.forEach((v, i) => buf.set(this.from(v).bytes, i * fi.size));
      return buf;
    };
    const split = (bytes) => {
      const out = [];
      for (let i = 0; i < n; i++)
        out.push(new Float(this, bytes.slice(i * fi.size, (i + 1) * fi.size)));
      return out;
    };

    // The three with an int64 exponent array. Same argument count as a
    // binary call and a different second operand, so it is its own
    // branch rather than a flag on that one.
    if (typeof op === "string" && TRANSCEND_INT.has(op)) {
      if (c) throw new TypeError(`${op} takes no c operand`);
      if (!b) throw new TypeError(`${op} needs an array of integer exponents`);
      const ns = b.map((v, i) => asI64(v, `${op}'s exponent [${i}]`));
      const ab = pack(a);
      return withScratch(this._M, (s) => {
        const pa = s.put(ab), pn = s.putI64(ns);
        const pd = s.alloc(fi.size * n), fl = s.alloc(4);
        const st = this._C[op](this._dev, fi.code, this._rnd, pa, pn, pd, n,
                               fl);
        checkStatus(this._C, st, `cft_${op}`);
        const flags = s.u32(fl);
        this.lastFlags = flags;
        this.flags |= flags;
        return split(s.get(pd, fi.size * n));
      });
    }

    // The augmented three: two outputs, no rounding argument.
    const AUG = { augmentedAddition: "augmentedAdd",
                  augmentedSubtraction: "augmentedSub",
                  augmentedMultiplication: "augmentedMul" };
    const augFn = typeof op === "string"
      ? (AUG[op] ?? (Object.values(AUG).includes(op) ? op : undefined))
      : undefined;
    if (augFn !== undefined) {
      if (c) throw new TypeError(`${op} takes no c operand`);
      if (!b) throw new TypeError(`${op} needs a second operand array`);
      const ab = pack(a), bb = pack(b);
      return withScratch(this._M, (s) => {
        const pa = s.put(ab), pb = s.put(bb);
        const pr = s.alloc(fi.size * n), pe = s.alloc(fi.size * n);
        const fl = s.alloc(4);
        const st = this._C[augFn](this._dev, fi.code, pa, pb, pr, pe, n, fl);
        checkStatus(this._C, st, `cft_${augFn}`);
        const flags = s.u32(fl);
        this.lastFlags = flags;
        this.flags |= flags;
        return { r: split(s.get(pr, fi.size * n)),
                 e: split(s.get(pe, fi.size * n)) };
      });
    }

    // The 9.7 payload three: elementwise, and no flag word at all.
    const PAY = { get_payload: "getPayload", set_payload: "setPayload",
                  set_payload_signaling: "setPayloadSignaling" };
    const payFn = typeof op === "string"
      ? (PAY[op] ?? (Object.values(PAY).includes(op) ? op : undefined))
      : undefined;
    if (payFn !== undefined) {
      if (b || c) throw new TypeError(`${op} reads one operand array`);
      const ab = pack(a);
      return withScratch(this._M, (s) => {
        const pa = s.put(ab), pd = s.alloc(fi.size * n);
        const st = this._C[payFn](this._dev, fi.code, pa, pd, n);
        checkStatus(this._C, st, `cft_${payFn}`);
        return split(s.get(pd, fi.size * n));
      });
    }

    const arity = typeof op === "string" ? TRANSCEND_ARITY.get(op) : undefined;
    if (arity !== undefined) {
      if (c) throw new TypeError(`${op} takes no c operand`);
      if (arity === 2 && !b)
        throw new TypeError(`${op} needs a second operand array`);
      if (arity === 1 && b)
        throw new TypeError(`${op} takes one operand array, not two`);
      const ab = pack(a), bb = pack(b);
      return withScratch(this._M, (s) => {
        const pa = s.put(ab);
        const pb = bb ? s.put(bb) : 0;
        const pd = s.alloc(fi.size * n), fl = s.alloc(4);
        const st = arity === 2
          ? this._C[op](this._dev, fi.code, this._rnd, pa, pb, pd, n, fl)
          : this._C[op](this._dev, fi.code, this._rnd, pa, pd, n, fl);
        checkStatus(this._C, st, `cft_${op}`);
        const flags = s.u32(fl);
        this.lastFlags = flags;
        this.flags |= flags;
        return split(s.get(pd, fi.size * n));
      });
    }

    const code = typeof op === "string" ? OPS[op] : op;
    if (code === undefined)
      throw new TypeError(`unknown op ${JSON.stringify(op)}`);
    const r = this._run(code, pack(a), pack(b), pack(c), n);
    this.lastFlags = r.flags;
    this.flags |= r.flags;
    return split(r.bytes);
  }

  /** Many sequences -> many encodings in ONE library call: the from_
   *  conversions are the batch-shaped half of clause 5.12, and this is
   *  that shape. The flag word is the OR across the batch; a sequence
   *  outside the syntax refuses the WHOLE call and the error names
   *  which element was at fault, because a caller reading a file of
   *  numbers needs the line and not just the verdict. */
  mapFromDecimal(list) { return this._mapFromChar("fromDecimalChar", list); }
  mapFromHex(list) { return this._mapFromChar("fromHexChar", list); }

  _mapFromChar(which, list) {
    if (!Array.isArray(list) || list.some((s) => typeof s !== "string"))
      throw new TypeError(`${which} wants an array of strings`);
    const M = this._M, fi = this._fi;
    const n = list.length;
    return withScratch(M, (s) => {
      const pin = s.putStringArray(list);
      const pd = s.alloc(fi.size * Math.max(n, 1));
      const bad = s.alloc(4), fl = s.alloc(4);
      const st = this._C[which](this._dev, fi.code, this._rnd, pin, pd, n,
                                bad, fl);
      if (st !== 0) {
        const i = s.u32(bad);
        throw new SyntaxError(
          `${which} refused the batch at element ${i} ` +
          `(${JSON.stringify(list[i] ?? "?")}): ` +
          `${this._C.strerror(st)}. On a refusal the whole call is refused ` +
          `and the output is unspecified - cft.h, and this package does not ` +
          `hand back a half-converted array.`);
      }
      const flags = s.u32(fl);
      this.lastFlags = flags;
      this.flags |= flags;
      const bytes = s.get(pd, fi.size * Math.max(n, 1));
      const out = [];
      for (let i = 0; i < n; i++)
        out.push(new Float(this, bytes.slice(i * fi.size, (i + 1) * fi.size)));
      return out;
    });
  }

  /** The contract's tree reduction: "sum", "dot" with a second array,
   *  and since ABI 0.6 "sumsq" and "sumabs" - opcodes 28 and 29, the
   *  other two of clause 9.4's sum reductions.
   *  The tree shape is part of the contract, not an implementation
   *  detail (cft.h, docs/DETERMINISM.md), which is why this is
   *  cft_reduce and not a JS loop over add().
   *
   *  sumsq and sumabs are the SAME tree over a different leaf, so the
   *  library issues `dot(a, a)` and an `abs` pass then `sum` - with one
   *  documented row of their own, where 754-2019 9.4 puts an infinity
   *  AHEAD of a NaN for these two and behind it for sum and dot. A
   *  vector holding both comes back +inf here where dot or sum would
   *  give a quiet NaN. */
  reduce(op, a, b = null) {
    const M = this._M, fi = this._fi;
    const REDUCE_OPS = { sum: OP_SUM, dot: OP_DOT,
                         sumsq: OP_SUMSQ, sumabs: OP_SUMABS };
    const code = REDUCE_OPS[op];
    if (code === undefined)
      throw new TypeError(`reduce wants "sum", "dot", "sumsq" or "sumabs"`);
    if (b && code !== OP_DOT)
      throw new TypeError(`${op} reads one operand array; only dot takes b`);
    const n = a.length;
    const pack = (arr) => {
      if (!arr) return null;
      const buf = new Uint8Array(fi.size * n);
      arr.forEach((v, i) => buf.set(this.from(v).bytes, i * fi.size));
      return buf;
    };
    const ab = pack(a), bb = pack(b);
    return withScratch(M, (s) => {
      const pa = ab ? s.put(ab) : 0;
      const pb = bb ? s.put(bb) : 0;
      const pd = s.alloc(fi.size), fl = s.alloc(4);
      const st = this._C.reduce(this._dev, code, fi.code, this._rnd,
                                pa, pb, pd, n, fl, 0);
      checkStatus(this._C, st, "cft_reduce");
      return this._finish(s.get(pd, fi.size), s.u32(fl));
    });
  }
}

const OPS = {
  fma: OP_FMA, add: OP_ADD, sub: OP_SUB, mul: OP_MUL, abs: OP_ABS,
  neg: OP_NEG, copysign: OP_COPYSIGN, min: OP_MIN, max: OP_MAX,
  minnum: OP_MINNUM, maxnum: OP_MAXNUM, select: OP_SELECT,
  cmplt: OP_CMPLT, cmple: OP_CMPLE, cmpeq: OP_CMPEQ,
};

export { ALL_FORMATS, exactDecimal, encodeExact, decode };
