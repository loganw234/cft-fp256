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
  RDN, RMM, RNE, RTZ, RUP, checkStatus, flagNames, loadModule, withScratch,
} from "./lib.mjs";

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

  /** One cft_run over a whole array: the call shape a device wants,
   *  and the reason a batch API exists at all. `op` is a name from
   *  cft.h ("add", "mul", "fma", ...); operands are arrays of Float
   *  or anything from() accepts, or null for an unused slot. */
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
    const code = typeof op === "string" ? OPS[op] : op;
    if (code === undefined)
      throw new TypeError(`unknown op ${JSON.stringify(op)}`);
    const r = this._run(code, pack(a), pack(b), pack(c), n);
    this.lastFlags = r.flags;
    this.flags |= r.flags;
    const out = [];
    for (let i = 0; i < n; i++)
      out.push(new Float(this, r.bytes.slice(i * fi.size, (i + 1) * fi.size)));
    return out;
  }

  /** The contract's tree reduction: sum, or dot with a second array.
   *  The tree shape is part of the contract, not an implementation
   *  detail (cft.h, docs/DETERMINISM.md), which is why this is
   *  cft_reduce and not a JS loop over add(). */
  reduce(op, a, b = null) {
    const M = this._M, fi = this._fi;
    const code = op === "sum" ? OP_SUM : op === "dot" ? OP_DOT : undefined;
    if (code === undefined)
      throw new TypeError(`reduce wants "sum" or "dot"`);
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
