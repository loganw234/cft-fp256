// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
//     node bindings/node/test.mjs
//
// The package's own tests: conversions, the decimal contract, flags,
// refusals, the clause-5 surface, batch-equals-scalar and the
// contract's reduction tree. The 236,000-case conformance replay is
// conformance.mjs; this file is everything the vectors cannot express.
//
// Two of these are worth naming, because they are checks against
// something this repository did not write:
//
//   * decimal parsing at binary64 is compared against V8's own
//     strtod. ECMAScript specifies Number(s) as the correctly rounded
//     binary64 of the decimal s under roundTiesToEven, so for the RNE
//     context it is an independent oracle for the library's decimal
//     path - a different implementation, by different people,
//     answering the same question.
//   * the tree reduction is compared against the shape cft.h
//     documents, rebuilt out of scalar cft_run adds. That is a check
//     of the SHAPE (left child is the largest power of two strictly
//     below the range), not of the arithmetic, and it is the one
//     thing a reduction contract can get wrong while every element
//     still rounds correctly.
//
// And a negative control: the comparisons are shown failing on a
// one-bit change before they are believed.

import { readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Context, formatFor } from "./index.mjs";
import { decode, encodeExact } from "./core.mjs";
import { FLAGS_ALL, FLAG_INEXACT, FLAG_INVALID, FLAG_DIVBYZERO,
         FLAG_OVERFLOW, FLAG_UNDERFLOW, FORMATOF_METHOD, MINMAG_METHOD,
         is754version1985, is754version2008, is754version2019 }
  from "./lib.mjs";

let passed = 0, failed = 0;
const failures = [];

function test(name, fn) {
  try { fn(); passed++; }
  catch (err) { failed++; failures.push(`${name}: ${err.message}`); }
}
function eq(got, want, what = "") {
  if (got !== want)
    throw new Error(`${what}expected ${want}, got ${got}`);
}
function ok(cond, what) { if (!cond) throw new Error(what); }
function throws(fn, what) {
  try { fn(); } catch { return; }
  throw new Error(`${what}: expected a refusal, got a value`);
}

// A seeded generator, so a failure reproduces.
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const WIDTHS = [32, 64, 128, 256];
const ATTRS = ["rne", "rtz", "rdn", "rup", "rmm"];

const ctxs = {};
for (const w of WIDTHS) ctxs[w] = await Context.open(w);
const c64 = ctxs[64];

// ---------------------------------------------------------------------
// identity
// ---------------------------------------------------------------------

/** The ABI the TREE is at, read out of cft.h.
 *
 *  Not a number typed here, and the difference is the whole value of
 *  the check. A hard-coded "0.6" agrees with a stale module exactly as
 *  happily as with a fresh one - which is how bindings/wasm's module
 *  spent a day reporting an ABI whose operations it did not export
 *  (docs/COMPATIBILITY.md's half-step). Read from the header, the
 *  assertion becomes "the module was built from THIS tree", which is
 *  the thing worth knowing, and it goes green on the integrator's
 *  version bump without this file being edited. bindings/wasm's
 *  verify.mjs derives it the same way from the same two macros. */
function abiFromHeader() {
  const here = dirname(fileURLToPath(import.meta.url));
  const h = readFileSync(join(resolve(here, "..", ".."), "host", "include",
                              "cft.h"), "utf8");
  const get = (name) => {
    const m = h.match(new RegExp(`^#define\\s+${name}\\s+(\\d+)`, "m"));
    if (!m) throw new Error(`cft.h has no ${name}`);
    return Number(m[1]);
  };
  return `${get("CFT_ABI_VERSION_MAJOR")}.${get("CFT_ABI_VERSION_MINOR")}`;
}

test("the module is the tree's own ABI, on the software backend", () => {
  eq(c64.abiVersion, abiFromHeader(), "abi (cft.h says): ");
  eq(c64.backend, "software", "backend: ");
});

test("all four formats open and report their own geometry", () => {
  for (const w of WIDTHS) {
    const fi = ctxs[w].format;
    eq(fi.width, w, `${w}: `);
    eq(fi.size, w / 8, `${w} size: `);
    eq(fi.manW + fi.expW + 1, w, `${w} sign + exponent + significand: `);
    eq(fi.emin, 1 - fi.emax, `${w} exponent range is symmetric: `);
  }
  eq(ctxs[256].precision, 237, "binary256 precision: ");
});

test("a format is nameable by width, precision or name", () => {
  eq(formatFor(128), formatFor(113), "128 vs precision 113: ");
  eq(formatFor("binary128"), formatFor("fp128"), "names: ");
  throws(() => formatFor(80), "x87 double-extended is not an interchange format");
  throws(() => formatFor("binary16"), "binary16 is not implemented");
});

test("rounding is by name, never by number", () => {
  for (const a of ATTRS) eq(c64.withRounding(a).rounding, a, `${a}: `);
  throws(() => c64.withRounding(2), "a raw 2 means different things per ABI");
  throws(() => c64.withRounding("RNDN"), "MPFR's spelling is not this one");
});

// ---------------------------------------------------------------------
// the codec and the decimal round trip
// ---------------------------------------------------------------------

function interestingBits(fi, rand) {
  const one = ((BigInt(fi.bias) << BigInt(fi.manW)));
  const signBit = 1n << BigInt(fi.width - 1);
  const expAll = ((1n << BigInt(fi.expW)) - 1n) << BigInt(fi.manW);
  const out = [
    0n,                                   // +0
    signBit,                              // -0
    expAll,                               // +inf
    signBit | expAll,                     // -inf
    expAll | (1n << BigInt(fi.manW - 1)), // canonical qNaN
    1n,                                   // smallest subnormal
    (1n << BigInt(fi.manW)) - 1n,         // largest subnormal
    1n << BigInt(fi.manW),                // smallest normal
    expAll - 1n,                          // largest finite
    one, one | 1n, signBit | one,         // 1, nextUp(1), -1
  ];
  for (let i = 0; i < 40; i++) {
    let v = 0n;
    for (let b = 0; b < fi.width; b += 16)
      v = (v << 16n) | BigInt(Math.floor(rand() * 65536));
    out.push(v & ((1n << BigInt(fi.width)) - 1n));
  }
  return out;
}

for (const w of WIDTHS) {
  test(`binary${w}: bits -> bytes -> bits is the identity`, () => {
    const ctx = ctxs[w];
    const rand = mulberry32(0x5eed + w);
    for (const bits of interestingBits(ctx.format, rand)) {
      const f = ctx.fromBits(bits);
      eq(f.bits, bits, `0x${bits.toString(16)}: `);
      eq(ctx.fromBytes(f.bytes).bits, bits, `via bytes 0x${bits.toString(16)}: `);
    }
  });

  test(`binary${w}: toString writes an exact decimal parse reads back`, () => {
    const ctx = ctxs[w];
    const rand = mulberry32(0xbeef + w);
    for (const bits of interestingBits(ctx.format, rand)) {
      const f = ctx.fromBits(bits);
      const s = f.toString();
      const back = ctx.from(s);
      if (f.isNaN) { ok(back.isNaN, `${s} should read back as a NaN`); continue; }
      ok(back.sameBits(f),
         `${s} read back as 0x${back.bits.toString(16)}, not ` +
         `0x${f.bits.toString(16)}`);
      eq(ctx.lastFlags, 0, `${s} is exact by construction, so `);
    }
  });
}

test("the sign of a zero survives the decimal round trip", () => {
  for (const w of WIDTHS) {
    const ctx = ctxs[w];
    eq(ctx.from("-0").toString(), "-0", `binary${w} -0: `);
    eq(ctx.from("-0").sign, 1, `binary${w} -0 sign: `);
    eq(ctx.from("0").sign, 0, `binary${w} +0 sign: `);
    eq(ctx.from("-0.000e10").sign, 1, `binary${w} -0.000e10: `);
    ok(ctx.from(ctx.zero(1).toString()).sameBits(ctx.zero(1)), "round trip -0");
  }
});

test("specials are lexed, not rounded, and need no library at all", () => {
  for (const w of WIDTHS) {
    const ctx = ctxs[w];
    for (const s of ["nan", "NaN", "NAN", "-nan"])
      ok(ctx.from(s).isNaN, `binary${w} ${s}`);
    for (const [s, sign] of [["inf", 0], ["INF", 0], ["Infinity", 0],
                             ["-inf", 1], ["-Infinity", 1], ["+inf", 0]]) {
      const f = ctx.from(s);
      ok(f.isInf && f.sign === sign, `binary${w} ${s}`);
    }
    eq(ctx.from("  1.5  ").toString(), "1.5e+0", `binary${w} whitespace: `);
  }
});

// ---------------------------------------------------------------------
// decimal rounding: the library's, checked against V8's strtod
// ---------------------------------------------------------------------

function bitsOfDouble(x) {
  const b = new Uint8Array(8);
  new DataView(b.buffer).setFloat64(0, x, true);
  let v = 0n;
  for (let i = 7; i >= 0; i--) v = (v << 8n) | BigInt(b[i]);
  return v;
}

test("binary64 decimals round like V8's own strtod (RNE)", () => {
  const rand = mulberry32(0xd0d0);
  let checked = 0;
  for (let i = 0; i < 400; i++) {
    // 15 digits and |E| <= 22: the window where one exact cft_div or
    // cft_mul delivers the correctly rounded value.
    const digits = 1 + Math.floor(rand() * 15);
    let s = String(1 + Math.floor(rand() * 9));
    for (let d = 1; d < digits; d++) s += String(Math.floor(rand() * 10));
    const e = Math.floor(rand() * 45) - 22;
    const str = `${rand() < 0.5 ? "-" : ""}${s}e${e}`;
    const mine = c64.from(str);
    eq(mine.bits, bitsOfDouble(Number(str)), `${str}: `);
    checked++;
  }
  ok(checked === 400, "400 strings");
});

test("0.1 is 0x3fb999999999999a, and inexact says so", () => {
  const f = c64.from("0.1");
  eq(f.bits, 0x3fb999999999999an, "0.1: ");
  ok(c64.lastFlags & FLAG_INEXACT, "0.1 must be inexact");
  const half = c64.from("0.5");
  eq(half.bits, 0x3fe0000000000000n, "0.5: ");
  eq(c64.lastFlags, 0, "0.5 is exact, so ");
});

test("a directed attribute moves a decimal the way it should", () => {
  const up = c64.withRounding("rup").from("0.1");
  const dn = c64.withRounding("rdn").from("0.1");
  const rz = c64.withRounding("rtz").from("0.1");
  ok(up.bits > dn.bits, "roundTowardPositive must land above roundTowardNegative");
  eq(rz.bits, dn.bits, "0.1 is positive, so toward-zero is toward-negative: ");
  eq(dn.bits, 0x3fb9999999999999n, "0.1 rounded down: ");
  // and the sign travels with the digits: -0.1 rounds the other way
  const negUp = c64.withRounding("rup").from("-0.1");
  eq(negUp.bits, 0x8000000000000000n | 0x3fb9999999999999n,
     "-0.1 toward +inf is the smaller magnitude: ");
});

test("ties-to-away parses decimals, which MPFR cannot", () => {
  // The Python drop-in refuses every inexact decimal under RNDNA
  // because MPFR has no such attribute. Here the library rounds.
  const rmm = c64.withRounding("rmm");
  const f = rmm.from("0.1");
  ok(rmm.lastFlags & FLAG_INEXACT, "still inexact");
  ok(f.bits === 0x3fb999999999999an || f.bits === 0x3fb9999999999999n,
     "an adjacent binary64 either way");
});

test("a decimal outside the exact-operand window is refused, loudly", () => {
  throws(() => c64.from("1e100"), "10^100 is not exact in binary64");
  throws(() => c64.from("1e-400"), "10^-400 is not exact in binary64");
  throws(() => c64.from("1.7976931348623157e308"), "17 digits at binary64");
  // ...and the same string is fine where the format does hold it.
  ok(ctxs[256].from("1e100") instanceof Object, "binary256 holds 10^100");
});

test("a malformed string is a refusal, not a NaN", () => {
  for (const s of ["", "  ", "0x1p3", "1_000", "1,5", "1.2.3", "e5", "1e"])
    throws(() => c64.from(s), `${JSON.stringify(s)}`);
});

// ---------------------------------------------------------------------
// numbers and integers
// ---------------------------------------------------------------------

test("a JS number goes in and comes back unchanged at binary64", () => {
  const rand = mulberry32(0xfeed);
  for (let i = 0; i < 200; i++) {
    const x = (rand() - 0.5) * Math.pow(2, Math.floor(rand() * 200) - 100);
    eq(c64.fromNumber(x).toNumber(), x, `${x}: `);
  }
  eq(Object.is(c64.fromNumber(-0).toNumber(), -0), true, "-0 keeps its sign");
  ok(c64.fromNumber(Infinity).isInf, "inf");
  ok(c64.fromNumber(NaN).isNaN, "nan");
});

test("widening a number is exact, narrowing is the library's rounding", () => {
  const wide = ctxs[256].fromNumber(0.1);
  eq(ctxs[256].lastFlags, 0, "binary64 -> binary256 is exact, so ");
  eq(wide.toNumber(), 0.1, "and comes back: ");
  const narrow = ctxs[32].fromNumber(0.1);
  ok(ctxs[32].lastFlags & FLAG_INEXACT, "binary64 -> binary32 rounds");
  eq(narrow.bits, 0x3dcccccdn, "0.1 in binary32: ");
});

test("integers convert through the library, or exactly, or not at all", () => {
  eq(c64.fromBigInt(0n).bits, 0n, "zero: ");
  eq(c64.fromBigInt(-1n).toString(), "-1e+0", "-1: ");
  const twoTo53 = c64.fromBigInt(1n << 53n);
  eq(c64.lastFlags, 0, "2^53 itself is exact, so ");
  const odd = c64.fromBigInt((1n << 53n) + 1n);
  ok(c64.lastFlags & FLAG_INEXACT, "2^53+1 does not fit and says inexact");
  ok(odd.sameBits(twoTo53), "2^53+1 rounds to 2^53 under RNE");
  // beyond 64 bits the library has no conversion, so exact or refused
  const big = 1n << 200n;
  eq(c64.fromBigInt(big).toString(), ctxs[256].fromBigInt(big).toString(),
     "2^200 is exact in both: ");
  throws(() => c64.fromBigInt((1n << 200n) + 1n),
         "2^200+1 needs 201 bits and no 64-bit conversion reaches it");
});

test("convertToInteger follows the contract's fixed invalid values", () => {
  eq(c64.from("42.5").toBigInt({ exact: true }), 42n, "RNE ties to even: ");
  ok(c64.lastFlags & FLAG_INEXACT, "roundToIntegralExact reports inexact");
  eq(c64.from("42.5").toBigInt(), 42n, "the plain family agrees on the value: ");
  eq(c64.lastFlags & FLAG_INEXACT, 0, "and does not report inexact");
  eq(c64.nan().toBigInt(), (1n << 63n) - 1n, "NaN -> INT64_MAX: ");
  ok(c64.lastFlags & FLAG_INVALID, "and invalid");
  eq(c64.inf(1).toBigInt(), -(1n << 63n), "-inf -> INT64_MIN: ");
  eq(c64.from("-1").toBigInt({ unsigned: true }), 0n, "-1 -> unsigned 0: ");
  ok(c64.lastFlags & FLAG_INVALID, "and invalid");
});

// ---------------------------------------------------------------------
// arithmetic, slots and flags
// ---------------------------------------------------------------------

test("the operand slots are the ones cft.h names", () => {
  // ADD and SUB read a and c; MUL reads a and b; FMA reads all three.
  // Getting a slot wrong is a wrong answer, not a crash.
  eq(c64.add(1, 2).toNumber(), 3, "1+2: ");
  eq(c64.sub(5, 3).toNumber(), 2, "5-3: ");
  eq(c64.sub(3, 5).toNumber(), -2, "3-5 is not 5-3: ");
  eq(c64.mul(3, 4).toNumber(), 12, "3*4: ");
  eq(c64.fma(2, 3, 4).toNumber(), 10, "2*3+4: ");
  eq(c64.copysign(3, -1).toNumber(), -3, "copysign takes a's magnitude: ");
});

test("fma is one rounding, not a multiply and an add", () => {
  // The classic witness: a*b is inexact in binary64, and the exact
  // product is recovered by the fma.
  const a = c64.fromBits(0x3ff0000000000001n);      // 1 + 2^-52
  const p = c64.mul(a, a);
  const err = c64.fma(a, a, c64.neg(p));
  ok(!err.isZero, "fma(a,a,-a*a) is the exact rounding error, not zero");
});

test("division and square root raise what the contract says", () => {
  const z = c64.div(1, 0);
  ok(z.isInf && (c64.lastFlags & FLAG_DIVBYZERO), "1/0 is inf + divbyzero");
  const n = c64.sqrt(-1);
  ok(n.isNaN && (c64.lastFlags & FLAG_INVALID), "sqrt(-1) is NaN + invalid");
  eq(c64.sqrt(4).toNumber(), 2, "sqrt(4): ");
  eq(c64.lastFlags, 0, "sqrt(4) is exact, so ");
  const big = c64.fromBits(0x7fefffffffffffffn);    // largest finite
  c64.mul(big, big);
  ok(c64.lastFlags & FLAG_OVERFLOW, "max^2 overflows");
});

test("flags are sticky until cleared", () => {
  c64.clearFlags();
  eq(c64.flags, 0, "cleared: ");
  c64.from("0.1");
  c64.add(1, 1);
  ok(c64.flags & FLAG_INEXACT, "the earlier inexact is still there");
  eq(c64.lastFlags, 0, "even though the last call raised nothing: ");
  ok(c64.flagNames().includes("inexact"), "and it has a name");
  c64.clearFlags();
});

test("min and max distinguish the two zeros", () => {
  eq(c64.min(c64.zero(0), c64.zero(1)).sign, 1, "min(+0,-0) is -0: ");
  eq(c64.max(c64.zero(0), c64.zero(1)).sign, 0, "max(+0,-0) is +0: ");
  ok(c64.min(c64.nan(), c64.from(1)).isNaN, "min propagates a NaN");
  eq(c64.minnum(c64.nan(), c64.from(1)).toNumber(), 1,
     "minnum returns the number: ");
});

test("the predicates deliver 1.0 and +0.0, and the booleans read them", () => {
  eq(c64.cmplt(1, 2).toNumber(), 1, "1<2 as a value: ");
  eq(c64.cmplt(2, 1).toNumber(), 0, "2<1 as a value: ");
  ok(c64.lt(1, 2) && !c64.lt(2, 1), "the boolean form");
  ok(c64.eq(c64.zero(0), c64.zero(1)), "+0 == -0");
  ok(!c64.lt(c64.nan(), 1) && !c64.lt(1, c64.nan()), "unordered is false");
  eq(c64.select(c64.from(7), c64.from(9), c64.cmplt(1, 2)).toNumber(), 7,
     "select on a predicate: ");
});

// ---------------------------------------------------------------------
// clause 5
// ---------------------------------------------------------------------

test("roundToIntegral, and only the exact family signals", () => {
  eq(c64.rint(c64.from("2.5")).toNumber(), 2, "RNE ties to even: ");
  eq(c64.lastFlags, 0, "the named operation never signals inexact, so ");
  c64.rint(c64.from("2.5"), { exact: true });
  ok(c64.lastFlags & FLAG_INEXACT, "roundToIntegralExact does");
  eq(c64.withRounding("rup").rint(c64.from("2.1")).toNumber(), 3, "ceil: ");
  eq(c64.rint(c64.from("-0.4")).sign, 1, "rint(-0.4) keeps the sign: ");
});

test("scaleB scales by a power of two, exactly", () => {
  eq(c64.scaleb(c64.from(1), 10).toNumber(), 1024, "1 * 2^10: ");
  eq(c64.lastFlags, 0, "exact, so ");
  eq(c64.scaleb(c64.from(1), -1074).bits, 1n, "down to the last subnormal: ");
  ok(c64.scaleb(c64.from(1), 5000n).isInf, "and over the top");
  ok(c64.lastFlags & FLAG_OVERFLOW, "with overflow");
});

test("logB is value-based and says so on a subnormal", () => {
  eq(c64.logb(c64.from(1024)).toNumber(), 10, "logb(1024): ");
  eq(c64.logb(c64.fromBits(1n)).toNumber(), -1074, "logb(min subnormal): ");
  const z = c64.logb(c64.zero(0));
  ok(z.isInf && z.sign === 1, "logb(0) is -inf");
  ok(c64.lastFlags & FLAG_DIVBYZERO, "and raises divideByZero");
});

test("nextUp and nextDown walk the encoding, edges included", () => {
  eq(c64.nextUp(c64.zero(0)).bits, 1n, "nextUp(+0) is the least subnormal: ");
  eq(c64.nextUp(c64.zero(1)).bits, 1n, "nextUp(-0) too: ");
  eq(c64.nextDown(c64.zero(0)).bits, (1n << 63n) | 1n, "nextDown(+0): ");
  const max = c64.fromBits(0x7fefffffffffffffn);
  ok(c64.nextUp(max).isInf, "the largest finite steps to infinity");
  eq(c64.lastFlags, 0, "without overflow, per 754: ");
});

test("class names all ten kinds", () => {
  eq(c64.classify(c64.inf(1)), "-inf", "");
  eq(c64.classify(c64.from(-1)), "-normal", "");
  eq(c64.classify(c64.fromBits((1n << 63n) | 1n)), "-subnormal", "");
  eq(c64.classify(c64.zero(1)), "-zero", "");
  eq(c64.classify(c64.zero(0)), "+zero", "");
  eq(c64.classify(c64.fromBits(1n)), "+subnormal", "");
  eq(c64.classify(c64.from(1)), "+normal", "");
  eq(c64.classify(c64.inf(0)), "+inf", "");
  eq(c64.classify(c64.fromBits(0x7ff0000000000001n)), "snan", "");
  eq(c64.classify(c64.nan()), "qnan", "");
});

test("totalOrder orders what compareQuiet cannot", () => {
  ok(c64.totalOrder(c64.zero(1), c64.zero(0)), "-0 precedes +0");
  ok(!c64.totalOrder(c64.zero(0), c64.zero(1)), "and not the other way");
  ok(c64.totalOrder(c64.from(1), c64.nan()), "a number precedes +NaN");
  ok(c64.totalOrder(c64.zero(0), c64.zero(0), { mag: true }), "reflexive");
  eq(c64.lastFlags, 0, "and signals nothing ever: ");
});

test("remainder is exact and takes a's sign at zero", () => {
  eq(c64.rem(5, 3).toNumber(), -1, "remainder(5,3): ");
  eq(c64.lastFlags, 0, "exact, so ");
  eq(c64.rem(6, 3).sign, 0, "remainder(6,3) is +0: ");
  eq(c64.rem(-6, 3).sign, 1, "remainder(-6,3) is -0: ");
  ok(c64.rem(1, 0).isNaN && (c64.lastFlags & FLAG_INVALID),
     "remainder(x,0) is invalid");
});

test("the signaling comparisons signal on a quiet NaN", () => {
  c64.cmplt(c64.nan(), c64.from(1));
  eq(c64.lastFlags & FLAG_INVALID, 0, "the quiet form is quiet on a qNaN: ");
  c64.cmpSig("lt", c64.nan(), c64.from(1));
  ok(c64.lastFlags & FLAG_INVALID, "the signaling form is not");
});

test("convertFormat widens exactly and narrows with one rounding", () => {
  const wide = ctxs[256].convert(c64.from("0.1"));
  eq(ctxs[256].lastFlags, 0, "widening is exact and silent, so ");
  ok(c64.convert(wide).sameBits(c64.from("0.1")), "and comes back");
  const narrow = ctxs[32].convert(c64.from("0.1"));
  ok(ctxs[32].lastFlags & FLAG_INEXACT, "narrowing rounds");
  eq(narrow.bits, 0x3dcccccdn, "0.1 in binary32: ");
  const huge = ctxs[256].from("1e100");
  ctxs[32].convert(huge);
  ok(ctxs[32].lastFlags & FLAG_OVERFLOW, "and can overflow");
});

test("a Float from another format is refused, not silently widened", () => {
  throws(() => c64.add(ctxs[32].from(1), 1), "binary32 operand in binary64");
  throws(() => c64.add(true, 1), "a boolean is not a number");
});

// ---------------------------------------------------------------------
// the phase-1 transcendentals (ABI 0.3)
//
// The vectors score these too - conformance.mjs replays 64,325 cases
// through the same JavaScript surface - so what belongs here is what a
// vector set cannot say: the exact cases that must raise NOTHING, the
// clause 9.2.1 rows implementations most often differ on, and the
// promise that the batch call and the scalar call are the same answer.
//
// Every expectation below is either a value cft.h states in words or
// one that is exactly representable and checkable by eye. Nothing is
// compared against libm: a C library's exp is neither correctly
// rounded nor reproducible, which is the whole reason these functions
// are in this contract.
// ---------------------------------------------------------------------

test("the exact cases are exact, and raise nothing at all", () => {
  // cft.h: exp and expm1 are exact only at zero, log and log1p only at
  // 1 and 0, exp2 at an integer, log2 at a power of two, log10 at a
  // representable power of ten, pow at a dyadic result, hypot at a
  // perfect square. Each of these raises no flag, inexact included.
  const exact = [
    ["exp(0)", () => c64.exp(0), 1],
    ["exp2(10)", () => c64.exp2(10), 1024],
    ["log(1)", () => c64.log(1), 0],
    ["log1p(0)", () => c64.log1p(0), 0],
    ["log2(1024)", () => c64.log2(1024), 10],
    ["log10(1000)", () => c64.log10(1000), 3],
    ["pow(2,10)", () => c64.pow(2, 10), 1024],
    ["hypot(3,4)", () => c64.hypot(3, 4), 5],
  ];
  for (const [what, call, want] of exact) {
    c64.clearFlags();
    const got = call();
    eq(got.toNumber(), want, `${what}: `);
    eq(c64.lastFlags, 0, `${what} is exact, so `);
  }
  eq(c64.expm1(0).bits, 0n, "expm1(+0) is +0: ");
  eq(c64.lastFlags, 0, "and exact, so ");
});

test("an ordinary value rounds, and says inexact", () => {
  const e = c64.exp(1);
  ok(c64.lastFlags & FLAG_INEXACT, "exp(1) is irrational, so it rounds");
  // and the attribute decides which way: the directed pair must
  // bracket the value by exactly one ulp
  const lo = c64.withRounding("rdn").exp(1);
  const hi = c64.withRounding("rup").exp(1);
  eq(hi.bits, lo.bits + 1n, "rdn and rup bracket exp(1) by one ulp: ");
  ok(e.sameBits(lo) || e.sameBits(hi), "and RNE picks one of the two");
});

test("the signed zeros that expm1 and log1p exist for survive", () => {
  // cft.h calls this half the reason the two functions exist: the sign
  // of a zero operand is the sign of the zero result.
  eq(c64.expm1(c64.zero(0)).sign, 0, "expm1(+0) is +0: ");
  eq(c64.expm1(c64.zero(1)).sign, 1, "expm1(-0) is -0: ");
  eq(c64.log1p(c64.zero(0)).sign, 0, "log1p(+0) is +0: ");
  eq(c64.log1p(c64.zero(1)).sign, 1, "log1p(-0) is -0: ");
  for (const f of [c64.expm1(c64.zero(1)), c64.log1p(c64.zero(1))])
    ok(f.isZero, "and both are zeros");
});

test("the infinite arguments follow clause 9.2.1", () => {
  const ninf = c64.inf(1), pinf = c64.inf(0);
  ok(c64.exp(ninf).isZero && c64.exp(ninf).sign === 0, "exp(-inf) is +0");
  ok(c64.exp(pinf).isInf, "exp(+inf) is +inf");
  eq(c64.expm1(ninf).toNumber(), -1, "expm1(-inf): ");
  ok(c64.exp2(ninf).isZero, "exp2(-inf) is +0");
  const l = c64.log(pinf);
  ok(l.isInf && l.sign === 0, "log(+inf) is +inf");
});

test("log at zero is a pole: -inf, and divideByZero says which kind", () => {
  for (const z of [c64.zero(0), c64.zero(1)]) {
    c64.clearFlags();
    const r = c64.log(z);
    ok(r.isInf && r.sign === 1, "log(0) is -inf");
    ok(c64.lastFlags & FLAG_DIVBYZERO, "and raises divideByZero");
    eq(c64.lastFlags & FLAG_INVALID, 0, "and NOT invalid: ");
  }
  const r = c64.log1p(-1);
  ok(r.isInf && r.sign === 1, "log1p(-1) is -inf too");
  ok(c64.lastFlags & FLAG_DIVBYZERO, "with divideByZero");
});

test("a domain error is invalid, and delivers the canonical quiet NaN", () => {
  // The contract's canonical qNaN: sign 0, quiet bit, payload 0. Not
  // "some NaN" - a payload this library invented would be a bit that
  // differs between implementations, which is the whole disease.
  const canon = c64.nan();
  const cases = [
    ["log(-1)", () => c64.log(-1)],
    ["log2(-1)", () => c64.log2(-1)],
    ["log10(-1)", () => c64.log10(-1)],
    ["log1p(-2)", () => c64.log1p(-2)],
    ["pow(-2, 0.5)", () => c64.pow(-2, c64.from("0.5"))],
  ];
  for (const [what, call] of cases) {
    c64.clearFlags();
    const r = call();
    ok(r.isNaN, `${what} is a NaN`);
    ok(r.sameBits(canon), `${what} is THE canonical quiet NaN`);
    ok(c64.lastFlags & FLAG_INVALID, `${what} raises invalid`);
  }
});

test("pow's identities beat its NaNs, exactly as 754 says", () => {
  // The rows implementations most often disagree on, and the reason
  // cft.h lists them: an identity that holds for every x holds for a
  // NaN x too.
  c64.clearFlags();
  eq(c64.pow(c64.nan(), 0).toNumber(), 1, "pow(qNaN, +0) is 1: ");
  eq(c64.lastFlags, 0, "and raises nothing: ");
  eq(c64.pow(c64.nan(), c64.zero(1)).toNumber(), 1, "pow(qNaN, -0) too: ");
  eq(c64.pow(c64.inf(0), 0).toNumber(), 1, "pow(+inf, +0) is 1: ");
  eq(c64.pow(1, c64.nan()).toNumber(), 1, "pow(1, qNaN) is 1: ");
  eq(c64.lastFlags, 0, "also silently: ");
  eq(c64.pow(-1, c64.inf(0)).toNumber(), 1, "pow(-1, +inf) is 1: ");
  eq(c64.pow(-1, c64.inf(1)).toNumber(), 1, "pow(-1, -inf) is 1: ");
});

test("pow's pole is at a finite exponent, not at the limit", () => {
  // cft.h spells this out because the two look alike and are not:
  // pow(+-0, y) for FINITE y < 0 is the pole and signals divideByZero;
  // pow(+-0, -inf) is the |x| < 1 row, +inf, and signals NOTHING.
  c64.clearFlags();
  const pole = c64.pow(c64.zero(0), -1);
  ok(pole.isInf, "pow(+0, -1) is an infinity");
  ok(c64.lastFlags & FLAG_DIVBYZERO, "and signals divideByZero");
  c64.clearFlags();
  const limit = c64.pow(c64.zero(0), c64.inf(1));
  ok(limit.isInf && limit.sign === 0, "pow(+0, -inf) is +inf");
  eq(c64.lastFlags, 0, "and signals nothing at all: ");
});

test("hypot takes an infinity over a NaN, and never overflows on the way", () => {
  c64.clearFlags();
  const r = c64.hypot(c64.inf(1), c64.nan());
  ok(r.isInf && r.sign === 0, "hypot(-inf, qNaN) is +inf");
  eq(c64.lastFlags, 0, "and raises nothing: ");
  // 3*max and 4*max would each square to infinity; the true hypot is
  // 5*max, which is finite. One rounding over unbounded range.
  const max = c64.fromBits(0x7fefffffffffffffn);
  const big = c64.hypot(c64.mul(max, c64.from("0.6")),
                        c64.mul(max, c64.from("0.8")));
  ok(!big.isInf, "hypot(0.6*max, 0.8*max) stays finite");
});

test("a signaling NaN is invalid everywhere, cft.h's deliberate C break", () => {
  // 9.2.1's "even a quiet NaN" wording does not reach a signaling one,
  // so pow(sNaN, 0) is invalid here where C's pow returns 1.
  const snan = c64.fromBits(0x7ff0000000000001n);
  eq(c64.classify(snan), "snan", "the operand really is signaling: ");
  for (const [what, call] of [["exp", () => c64.exp(snan)],
                              ["log", () => c64.log(snan)],
                              ["pow(sNaN, 0)", () => c64.pow(snan, 0)],
                              ["pow(1, sNaN)", () => c64.pow(1, snan)],
                              ["hypot", () => c64.hypot(c64.inf(0), snan)]]) {
    c64.clearFlags();
    const r = call();
    ok(r.sameBits(c64.nan()), `${what} delivers the canonical quiet NaN`);
    ok(c64.lastFlags & FLAG_INVALID, `${what} raises invalid`);
  }
});

test("the operands are the ones cft.h names, in that order", () => {
  // pow is not symmetric, and a wrapper with its two operand pointers
  // swapped computes b**a while returning a plausible number. This is
  // the check that notices.
  eq(c64.pow(2, 3).toNumber(), 8, "pow(2,3): ");
  eq(c64.pow(3, 2).toNumber(), 9, "pow(3,2) is a different answer: ");
  eq(c64.hypot(3, 4).toNumber(), 5, "hypot(3,4): ");
  eq(c64.hypot(4, 3).toNumber(), 5, "hypot is symmetric, so: ");
  eq(c64.log(c64.exp(1)).toNumber(), 1, "log undoes exp at e: ");
});

test("all nine reach every format, and the wide ones are wider", () => {
  for (const w of WIDTHS) {
    const ctx = ctxs[w];
    ctx.clearFlags();
    eq(ctx.exp(0).toNumber(), 1, `binary${w} exp(0): `);
    eq(ctx.lastFlags, 0, `binary${w} exp(0) exact: `);
    eq(ctx.log(1).toNumber(), 0, `binary${w} log(1): `);
    eq(ctx.hypot(3, 4).toNumber(), 5, `binary${w} hypot(3,4): `);
    eq(ctx.pow(2, 10).toNumber(), 1024, `binary${w} pow(2,10): `);
  }
  // binary256 carries a value binary64 cannot: exp(1) to 237 bits,
  // whose leading 53 bits are binary64's exp(1) but which does not
  // narrow back to it exactly.
  const wide = ctxs[256].exp(1);
  const narrowed = c64.convert(wide);
  ok(c64.lastFlags & FLAG_INEXACT, "narrowing binary256's exp(1) rounds");
  ok(narrowed.sameBits(c64.exp(1)),
     "and lands on binary64's own correctly rounded exp(1)");
});

test("Float carries the nine as methods, on its own context", () => {
  const x = c64.from(1);
  ok(x.exp().sameBits(c64.exp(1)), "x.exp()");
  ok(x.log().sameBits(c64.log(1)), "x.log()");
  ok(c64.from(3).hypot(4).sameBits(c64.hypot(3, 4)), "x.hypot(y)");
  ok(c64.from(2).pow(10).sameBits(c64.pow(2, 10)), "x.pow(y)");
  const r = ctxs[128].withRounding("rup");
  ok(r.from(1).exp().sameBits(r.exp(1)), "and through a derived context");
});

test("the batch call is the scalar call, for all nine", () => {
  // Correct rounding is what makes this true by definition rather than
  // by luck: there is no vectorised approximation to differ from the
  // scalar path. Worth measuring anyway - it is the property a fast
  // path would silently break.
  const rand = mulberry32(0x7a4c3);
  const xs = [], ys = [];
  for (let i = 0; i < 129; i++) {          // not a power of two
    xs.push(c64.fromNumber(rand() * 20 - 10));
    ys.push(c64.fromNumber(rand() * 6));
  }
  const unary = ["exp", "expm1", "exp2", "log", "log1p", "log2", "log10"];
  for (const fn of unary) {
    const batch = c64.map(fn, xs);
    const batchFlags = c64.lastFlags;
    let flags = 0;
    for (let i = 0; i < xs.length; i++) {
      const one = c64[fn](xs[i]);
      flags |= c64.lastFlags;
      ok(batch[i].sameBits(one), `${fn} element ${i}`);
    }
    eq(batchFlags, flags, `${fn}: batch flags are the OR over elements: `);
  }
  for (const fn of ["pow", "hypot"]) {
    const batch = c64.map(fn, xs, ys);
    const batchFlags = c64.lastFlags;
    let flags = 0;
    for (let i = 0; i < xs.length; i++) {
      const one = c64[fn](xs[i], ys[i]);
      flags |= c64.lastFlags;
      ok(batch[i].sameBits(one), `${fn} element ${i}`);
    }
    eq(batchFlags, flags, `${fn}: batch flags are the OR over elements: `);
  }
  throws(() => c64.map("exp", xs, ys), "exp takes one operand array");
  throws(() => c64.map("pow", xs), "pow needs its second array");
  throws(() => c64.map("hypot", xs, ys, xs), "no c slot on a transcendental");
});

// ---------------------------------------------------------------------
// the phase-2 trigonometrics (ABI 0.4)
//
// Same division of labour as phase 1's block above: conformance.mjs
// replays 129,845 transcendental cases through this package's own
// methods, so what belongs here is what a vector set cannot say - the
// exact cases that must raise NOTHING, the clause 9.2.1 rows
// implementations most often differ on, the operand order of atan2,
// and batch-equals-scalar.
//
// Every expectation is either a value cft.h and docs/TRANSCENDENTALS.md
// state in words or one that is exactly representable and checkable by
// eye. Nothing is compared against Math.sin: an ordinary libm is
// neither correctly rounded nor reproducible, and JavaScript's Math is
// explicitly implementation-defined - which is the whole reason these
// functions are in this contract.
// ---------------------------------------------------------------------

test("sinPi's zeros carry the ARGUMENT's sign, not the result's", () => {
  // The row cft.h states first and libms most often get by accident:
  // sinPi of an integer is a zero, and its sign is the operand's.
  c64.clearFlags();
  const p1 = c64.sinpi(1), m1 = c64.sinpi(-1);
  ok(p1.isZero && p1.sign === 0, "sinPi(1) is +0");
  ok(m1.isZero && m1.sign === 1, "sinPi(-1) is -0");
  eq(c64.lastFlags, 0, "and both are exact, so ");
  ok(c64.sinpi(c64.zero(0)).sign === 0, "sinPi(+0) is +0");
  ok(c64.sinpi(c64.zero(1)).sign === 1, "sinPi(-0) is -0");
  // 2 and -2 are integers too, and 3 is the odd one
  ok(c64.sinpi(2).isZero && c64.sinpi(2).sign === 0, "sinPi(2) is +0");
  ok(c64.sinpi(-3).isZero && c64.sinpi(-3).sign === 1, "sinPi(-3) is -0");
  // and the half-integers are the other half of Niven's exact set
  eq(c64.sinpi(c64.from("0.5")).toNumber(), 1, "sinPi(1/2): ");
  eq(c64.sinpi(c64.from("1.5")).toNumber(), -1, "sinPi(3/2): ");
});

test("cosPi is even, so its half-integer zero has no sign to carry", () => {
  for (const x of ["0.5", "-0.5", "1.5", "-1.5", "2.5", "-2.5"]) {
    c64.clearFlags();
    const r = c64.cospi(c64.from(x));
    ok(r.isZero, `cosPi(${x}) is a zero`);
    eq(r.sign, 0, `cosPi(${x}) is +0, both signs of the argument: `);
    eq(c64.lastFlags, 0, `cosPi(${x}) is exact, so `);
  }
  eq(c64.cospi(0).toNumber(), 1, "cosPi(+0) is 1: ");
  eq(c64.cospi(1).toNumber(), -1, "cosPi(1) is (-1)^1: ");
  eq(c64.cospi(2).toNumber(), 1, "cosPi(2) is (-1)^2: ");
  eq(c64.cospi(-3).toNumber(), -1, "cosPi(-3), and cosPi is even: ");
});

test("tanPi is sinPi/cosPi in every respect, signs included", () => {
  // tanPi(1) = -0 because sinPi(1) is +0 and cosPi(1) is -1. A sign
  // this package computed itself would be a guess; this one is the
  // library's.
  c64.clearFlags();
  const t1 = c64.tanpi(1);
  ok(t1.isZero && t1.sign === 1, "tanPi(1) is -0");
  eq(c64.lastFlags, 0, "and exact, so ");
  const t0 = c64.tanpi(c64.zero(0));
  ok(t0.isZero && t0.sign === 0, "tanPi(+0) is +0");
  const t2 = c64.tanpi(2);
  ok(t2.isZero && t2.sign === 0, "tanPi(2) is +0 - n even, sign unflipped");
  // the quarter-integers are the exact nonzero ones
  eq(c64.tanpi(c64.from("0.25")).toNumber(), 1, "tanPi(1/4): ");
  eq(c64.tanpi(c64.from("0.75")).toNumber(), -1, "tanPi(3/4): ");
});

test("tanPi at a half-integer is a POLE: infinity with divideByZero", () => {
  // 754-2019 7.3: an exact infinity from finite operands signals
  // divideByZero. Not overflow, and not invalid.
  c64.clearFlags();
  const r = c64.tanpi(c64.from("0.5"));
  ok(r.isInf && r.sign === 0, "tanPi(1/2) is +inf");
  ok(c64.lastFlags & FLAG_DIVBYZERO, "and raises divideByZero");
  eq(c64.lastFlags & FLAG_INVALID, 0, "and NOT invalid: ");
  eq(c64.lastFlags & FLAG_OVERFLOW, 0, "and NOT overflow: ");
  c64.clearFlags();
  const n = c64.tanpi(c64.from("-0.5"));
  ok(n.isInf && n.sign === 1, "tanPi(-1/2) is -inf");
  ok(c64.lastFlags & FLAG_DIVBYZERO, "with divideByZero too");
});

test("the Pi-forms' exact table is larger, and atanPi(inf) is in it", () => {
  // Dividing by pi turns irrational multiples into dyadic rationals,
  // which is the whole reason these five functions exist separately.
  const exact = [
    ["asinPi(+0)", () => c64.asinpi(c64.zero(0)), 0],
    ["asinPi(1)", () => c64.asinpi(1), 0.5],
    ["asinPi(-1)", () => c64.asinpi(-1), -0.5],
    ["acosPi(1)", () => c64.acospi(1), 0],
    ["acosPi(+0)", () => c64.acospi(c64.zero(0)), 0.5],
    ["acosPi(-1)", () => c64.acospi(-1), 1],
    ["atanPi(+0)", () => c64.atanpi(c64.zero(0)), 0],
    ["atanPi(1)", () => c64.atanpi(1), 0.25],
    ["atanPi(-1)", () => c64.atanpi(-1), -0.25],
    ["atanPi(+inf)", () => c64.atanpi(c64.inf(0)), 0.5],
    ["atanPi(-inf)", () => c64.atanpi(c64.inf(1)), -0.5],
  ];
  for (const [what, call, want] of exact) {
    c64.clearFlags();
    const got = call();
    eq(got.toNumber(), want, `${what}: `);
    eq(c64.lastFlags, 0, `${what} is exact, so `);
  }
  // and the same argument through atan is NOT exact: atan(+inf) is
  // pi/2, an irrational, so it rounds and says so.
  c64.clearFlags();
  const half = c64.atan(c64.inf(0));
  ok(c64.lastFlags & FLAG_INEXACT, "atan(+inf) is pi/2 and rounds");
  ok(!half.sameBits(c64.from("0.5")), "and is nothing like 1/2");
});

test("asinPi(1/2) is 1/6 - rational, NOT dyadic, so inexact", () => {
  // The case docs/TRANSCENDENTALS.md calls out because it looks exact
  // and is not: 1/6 is a rational Niven's theorem produces, but it has
  // no finite binary expansion, so it is a rounding like any other.
  //
  // "Really 1/6" is checked by DERIVING 1/6 rather than transcribing
  // it - cft_div of 1 by 6, correctly rounded in the same attribute.
  // Two correctly rounded results of the same real number are the same
  // encoding, so this holds in every attribute, and it holds for the
  // directed pair too, which is what makes it more than a coincidence.
  const half = c64.from("0.5");
  for (const attr of ATTRS) {
    const c = c64.withRounding(attr);
    c.clearFlags();
    const got = c.asinpi(half);
    ok(c.lastFlags & FLAG_INEXACT, `asinPi(1/2) is inexact under ${attr}`);
    ok(got.sameBits(c.div(1, 6)),
       `asinPi(1/2) is the ${attr} rounding of 1/6`);
    // acosPi(1/2) = 1/3 is the same story
    c.clearFlags();
    const third = c.acospi(half);
    ok(c.lastFlags & FLAG_INEXACT, `acosPi(1/2) is inexact under ${attr}`);
    ok(third.sameBits(c.div(1, 3)),
       `acosPi(1/2) is the ${attr} rounding of 1/3`);
  }
  // and the directed pair really does straddle: one ulp apart
  const lo = c64.withRounding("rdn").asinpi(half);
  const hi = c64.withRounding("rup").asinpi(half);
  eq(hi.bits, lo.bits + 1n, "rdn and rup bracket 1/6 by one ulp: ");
});

test("the inverses are exact only at their zeros", () => {
  // Hermite-Lindemann: asin, atan and atan2 of a nonzero dyadic
  // rational are transcendental, so the exact set is the zeros, plus
  // acos(1) = +0.
  const exact = [
    ["asin(+0)", () => c64.asin(c64.zero(0)), 0],
    ["atan(+0)", () => c64.atan(c64.zero(0)), 0],
    ["acos(1)", () => c64.acos(1), 0],
  ];
  for (const [what, call, want] of exact) {
    c64.clearFlags();
    eq(call().toNumber(), want, `${what}: `);
    eq(c64.lastFlags, 0, `${what} raises nothing, so `);
  }
  ok(c64.asin(c64.zero(1)).sign === 1, "asin(-0) is -0");
  ok(c64.atan(c64.zero(1)).sign === 1, "atan(-0) is -0");
  // and the corners that look exact are not
  for (const [what, call] of [["asin(1)", () => c64.asin(1)],
                              ["acos(-1)", () => c64.acos(-1)],
                              ["atan(1)", () => c64.atan(1)]]) {
    c64.clearFlags();
    call();
    ok(c64.lastFlags & FLAG_INEXACT, `${what} is a multiple of pi, so inexact`);
  }
});

test("atan2's operands are y then x, and a minus zero names an axis", () => {
  // The row cft.h says implementations most often miss: atan2(+-0, -0)
  // is +-pi, because a MINUS zero denominator names the negative real
  // axis. And it is inexact, while atan2Pi of the same operands is an
  // exact +-1 - which is, in one line, why atan2Pi is its own function.
  c64.clearFlags();
  const pi = c64.atan2(c64.zero(0), c64.zero(1));
  ok(c64.lastFlags & FLAG_INEXACT, "atan2(+0, -0) is pi and inexact");
  ok(!pi.isZero && pi.sign === 0, "and it is a positive number, not a zero");
  const mpi = c64.atan2(c64.zero(1), c64.zero(1));
  ok(mpi.sign === 1, "atan2(-0, -0) is -pi");
  ok(c64.sub(pi, c64.from("3.141592653589793")).isZero,
     "and pi at binary64 is 3.141592653589793");

  c64.clearFlags();
  const one = c64.atan2pi(c64.zero(0), c64.zero(1));
  eq(one.toNumber(), 1, "atan2Pi(+0, -0) is 1: ");
  eq(c64.lastFlags, 0, "exactly, raising nothing: ");
  eq(c64.atan2pi(c64.zero(1), c64.zero(1)).toNumber(), -1,
     "atan2Pi(-0, -0): ");

  // a PLUS zero denominator is the other row entirely
  const z = c64.atan2(c64.zero(0), c64.zero(0));
  ok(z.isZero && z.sign === 0, "atan2(+0, +0) is +0");
  ok(c64.atan2(c64.zero(1), c64.zero(0)).sign === 1, "atan2(-0, +0) is -0");
});

test("swapping atan2's operands is a different answer, and says so", () => {
  // atan2 is not symmetric in any of these, so a wrapper with its two
  // operand pointers exchanged returns a plausible number everywhere.
  // This is the check that notices - the negative control run against
  // it is recorded in bindings/wasm/README.md.
  eq(c64.atan2pi(1, 0).toNumber(), 0.5, "atan2Pi(1, 0) is +1/2: ");
  eq(c64.atan2pi(0, 1).toNumber(), 0, "atan2Pi(0, 1) is +0, a different row: ");
  eq(c64.atan2pi(1, 1).toNumber(), 0.25, "atan2Pi(1, 1), the diagonal: ");
  eq(c64.atan2pi(1, -1).toNumber(), 0.75, "atan2Pi(1, -1), the other one: ");
  eq(c64.atan2pi(-1, -1).toNumber(), -0.75, "atan2Pi(-1, -1): ");
  eq(c64.atan2pi(c64.inf(0), c64.inf(0)).toNumber(), 0.25,
     "atan2Pi(+inf, +inf) is +1/4: ");
  eq(c64.atan2pi(c64.inf(0), c64.inf(1)).toNumber(), 0.75,
     "atan2Pi(+inf, -inf) is +3/4: ");
  // y = 0 with x > 0 is the one exact atan2 row, and it keeps y's sign
  c64.clearFlags();
  const r = c64.atan2(c64.zero(1), 1);
  ok(r.isZero && r.sign === 1, "atan2(-0, +1) is -0");
  eq(c64.lastFlags, 0, "exactly: ");
});

test("a NaN does not outrank atan2's table the way it beats pow's", () => {
  // cft.h states the asymmetry: pow(qNaN, +-0) is 1, but atan2 of a
  // NaN is a NaN.
  c64.clearFlags();
  ok(c64.atan2(c64.nan(), 1).isNaN, "atan2(qNaN, 1) is a NaN");
  ok(c64.atan2(c64.zero(0), c64.nan()).isNaN, "atan2(+0, qNaN) is a NaN too");
  ok(c64.atan2pi(c64.nan(), c64.nan()).isNaN, "and atan2Pi likewise");
  eq(c64.lastFlags & FLAG_INVALID, 0,
     "a QUIET NaN in is not itself an invalid: ");
});

test("|x| > 1 is a domain error in asin, acos and their Pi-forms", () => {
  const canon = c64.nan();
  const outside = [c64.from(2), c64.from(-2), c64.inf(0), c64.inf(1),
                   c64.nextUp(c64.from(1))];
  for (const fn of ["asin", "acos", "asinpi", "acospi"]) {
    for (const x of outside) {
      c64.clearFlags();
      const r = c64[fn](x);
      ok(r.sameBits(canon),
         `${fn}(${x.toString()}) is THE canonical quiet NaN`);
      ok(c64.lastFlags & FLAG_INVALID, `${fn}(${x.toString()}) raises invalid`);
    }
  }
  // exactly 1 is inside, and atan takes the whole line
  c64.clearFlags();
  ok(!c64.asin(1).isNaN, "asin(1) is a number - the endpoint is in range");
  ok(!c64.atan(c64.inf(0)).isNaN, "atan(+inf) is a number: every real is");
});

test("sinPi, cosPi and tanPi of an infinity are invalid - no limit", () => {
  const canon = c64.nan();
  for (const fn of ["sinpi", "cospi", "tanpi"]) {
    for (const s of [0, 1]) {
      c64.clearFlags();
      const r = c64[fn](c64.inf(s));
      ok(r.sameBits(canon), `${fn}(${s ? "-" : "+"}inf) is the canonical qNaN`);
      ok(c64.lastFlags & FLAG_INVALID, `${fn} of an infinity raises invalid`);
    }
  }
});

test("a signaling NaN is invalid across all eleven, as everywhere else", () => {
  // 9.2.1's "even a quiet NaN" wording does not reach a signaling one,
  // and this contract is uniform about it: sNaN in, invalid and the
  // canonical quiet NaN out, no exceptions and no per-function rows.
  const snan = c64.fromBits(0x7ff0000000000001n);
  eq(c64.classify(snan), "snan", "the operand really is signaling: ");
  const unary = ["sinpi", "cospi", "tanpi", "asin", "acos", "atan",
                 "asinpi", "acospi", "atanpi"];
  for (const fn of unary) {
    c64.clearFlags();
    const r = c64[fn](snan);
    ok(r.sameBits(c64.nan()), `${fn}(sNaN) delivers the canonical quiet NaN`);
    ok(c64.lastFlags & FLAG_INVALID, `${fn}(sNaN) raises invalid`);
  }
  for (const fn of ["atan2", "atan2pi"]) {
    for (const [y, x, what] of [[snan, c64.from(1), "sNaN, 1"],
                                [c64.from(1), snan, "1, sNaN"]]) {
      c64.clearFlags();
      const r = c64[fn](y, x);
      ok(r.sameBits(c64.nan()), `${fn}(${what}) is the canonical quiet NaN`);
      ok(c64.lastFlags & FLAG_INVALID, `${fn}(${what}) raises invalid`);
    }
  }
});

test("sinPi's reduction is exact at every magnitude, not just small ones", () => {
  // The claim that separates sinPi from sin: x mod 2 is a mask on the
  // encoding, so a huge even integer is a zero decided by integer
  // arithmetic rather than by a table of pi's bits. 2^80 is an even
  // integer at binary64; so is the largest finite value.
  c64.clearFlags();
  const big = c64.sinpi(c64.fromBigInt(1n << 80n));
  ok(big.isZero && big.sign === 0, "sinPi(2^80) is +0");
  eq(c64.lastFlags, 0, "and exact: ");
  const max = c64.fromBits(0x7fefffffffffffffn);
  const huge = c64.sinpi(max);
  ok(huge.isZero, "sinPi(maxFinite) is a zero, by the same reduction");
  eq(c64.cospi(max).toNumber(), 1, "and cosPi(maxFinite) is 1: ");
});

test("all eleven reach every format, and the wide ones are wider", () => {
  for (const w of WIDTHS) {
    const ctx = ctxs[w];
    ctx.clearFlags();
    ok(ctx.sinpi(1).isZero && ctx.sinpi(1).sign === 0, `binary${w} sinPi(1)`);
    eq(ctx.cospi(1).toNumber(), -1, `binary${w} cosPi(1): `);
    eq(ctx.acospi(-1).toNumber(), 1, `binary${w} acosPi(-1): `);
    eq(ctx.atanpi(ctx.inf(0)).toNumber(), 0.5, `binary${w} atanPi(+inf): `);
    eq(ctx.atan2pi(1, -1).toNumber(), 0.75, `binary${w} atan2Pi(1, -1): `);
    eq(ctx.lastFlags, 0, `binary${w}: every one of those is exact, so `);
  }
  // binary256 carries an atan(1) binary64 cannot, and it narrows back
  // onto binary64's own correctly rounded answer
  const wide = ctxs[256].atan(1);
  const narrowed = c64.convert(wide);
  ok(c64.lastFlags & FLAG_INEXACT, "narrowing binary256's atan(1) rounds");
  ok(narrowed.sameBits(c64.atan(1)),
     "and lands on binary64's own correctly rounded atan(1)");
});

test("Float carries the eleven as methods, y first on atan2", () => {
  const x = c64.from(1);
  ok(x.sinpi().sameBits(c64.sinpi(1)), "x.sinpi()");
  ok(x.cospi().sameBits(c64.cospi(1)), "x.cospi()");
  ok(x.tanpi().sameBits(c64.tanpi(1)), "x.tanpi()");
  ok(x.asin().sameBits(c64.asin(1)), "x.asin()");
  ok(x.acos().sameBits(c64.acos(1)), "x.acos()");
  ok(x.atan().sameBits(c64.atan(1)), "x.atan()");
  ok(x.asinpi().sameBits(c64.asinpi(1)), "x.asinpi()");
  ok(x.acospi().sameBits(c64.acospi(1)), "x.acospi()");
  ok(x.atanpi().sameBits(c64.atanpi(1)), "x.atanpi()");
  // y.atan2(x) reads in cft.h's order, and the asymmetry proves it
  ok(x.atan2(c64.zero(0)).sameBits(c64.atan2(1, c64.zero(0))), "y.atan2(x)");
  eq(x.atan2pi(c64.zero(0)).toNumber(), 0.5, "1 .atan2Pi(+0) is +1/2: ");
  eq(c64.zero(0).atan2pi(x).toNumber(), 0, "and +0 .atan2Pi(1) is +0: ");
  const r = ctxs[128].withRounding("rup");
  ok(r.from(1).asin().sameBits(r.asin(1)), "and through a derived context");
});

test("the batch call is the scalar call, for all eleven", () => {
  const rand = mulberry32(0x51c0a);
  const xs = [], ys = [], us = [];
  for (let i = 0; i < 129; i++) {          // not a power of two
    xs.push(c64.fromNumber(rand() * 8 - 4));      // sinPi's domain: all
    us.push(c64.fromNumber(rand() * 2 - 1));      // the inverses': [-1,1]
    ys.push(c64.fromNumber(rand() * 8 - 4));
  }
  const unary = [["sinpi", xs], ["cospi", xs], ["tanpi", xs],
                 ["asin", us], ["acos", us], ["atan", xs],
                 ["asinpi", us], ["acospi", us], ["atanpi", xs]];
  for (const [fn, src] of unary) {
    const batch = c64.map(fn, src);
    const batchFlags = c64.lastFlags;
    let flags = 0;
    for (let i = 0; i < src.length; i++) {
      const one = c64[fn](src[i]);
      flags |= c64.lastFlags;
      ok(batch[i].sameBits(one), `${fn} element ${i}`);
    }
    eq(batchFlags, flags, `${fn}: batch flags are the OR over elements: `);
  }
  for (const fn of ["atan2", "atan2pi"]) {
    const batch = c64.map(fn, ys, xs);          // y first, as ever
    const batchFlags = c64.lastFlags;
    let flags = 0;
    for (let i = 0; i < ys.length; i++) {
      const one = c64[fn](ys[i], xs[i]);
      flags |= c64.lastFlags;
      ok(batch[i].sameBits(one), `${fn} element ${i}`);
    }
    eq(batchFlags, flags, `${fn}: batch flags are the OR over elements: `);
  }
  throws(() => c64.map("sinpi", xs, ys), "sinpi takes one operand array");
  throws(() => c64.map("atan2", ys), "atan2 needs its second array");
  throws(() => c64.map("atan2pi", ys, xs, xs), "no c slot on a transcendental");
});

// ---------------------------------------------------------------------
// arrays: one call, same answers, and the contract's tree
// ---------------------------------------------------------------------

test("a batch call equals the scalar calls, element for element", () => {
  const rand = mulberry32(0xa11ce);
  const xs = [], ys = [];
  for (let i = 0; i < 257; i++) {           // not a power of two, on purpose
    xs.push(c64.fromNumber((rand() - 0.5) * 1e6));
    ys.push(c64.fromNumber((rand() - 0.5) * 1e-3));
  }
  const batch = c64.map("mul", xs, ys);
  const batchFlags = c64.lastFlags;
  let flags = 0;
  for (let i = 0; i < xs.length; i++) {
    const one = c64.mul(xs[i], ys[i]);
    flags |= c64.lastFlags;
    ok(batch[i].sameBits(one), `element ${i}`);
  }
  eq(batchFlags, flags, "the batch flags are the OR over the elements: ");
  ok(flags & FLAG_INEXACT, "and these products do round");
});

test("cft_reduce returns the tree cft.h documents, not a running sum", () => {
  // T(lo,hi) splits so the LEFT child covers the largest power of two
  // strictly smaller than the range. Rebuilt here out of scalar adds:
  // this checks the SHAPE, which is the part of a reduction that a
  // correct elementwise implementation can still get wrong.
  // 2^53 followed by ten ones: every sequential addition ties to even
  // and is absorbed, while the tree adds the ones to each other first.
  // Reassociation is the whole question, so the operands are chosen to
  // answer it rather than left to a random draw that may not.
  const xs = [c64.fromBigInt(1n << 53n)];
  for (let i = 0; i < 10; i++) xs.push(c64.from(1));
  const tree = (lo, hi) => {
    if (hi - lo === 1) return xs[lo];
    let split = 1;
    while (split * 2 < hi - lo) split *= 2;
    return c64.add(tree(lo, lo + split), tree(lo + split, hi));
  };
  const want = tree(0, xs.length);
  const got = c64.reduce("sum", xs);
  ok(got.sameBits(want),
     `tree ${want.toString()} vs cft_reduce ${got.toString()}`);
  // and a left-to-right accumulation is a DIFFERENT answer, which is
  // why the shape is in the contract at all
  let seq = xs[0];
  for (let i = 1; i < xs.length; i++) seq = c64.add(seq, xs[i]);
  ok(!seq.sameBits(got), "a sequential sum should differ here");
  eq(c64.reduce("sum", []).toString(), "0", "n == 0 is +0: ");
  ok(c64.reduce("sum", [xs[0]]).sameBits(xs[0]), "n == 1 is a[0] verbatim");
});

// ---------------------------------------------------------------------
// the phase-3 radian trigonometry and the hyperbolics (ABI 0.5)
// ---------------------------------------------------------------------

test("the exact cases of the nine are the zeros, and they raise nothing", () => {
  // Hermite-Lindemann: sin, tan, sinh, tanh, asinh and atanh of a
  // nonzero dyadic are transcendental, cos and cosh are 1 only at 0,
  // acosh is 0 only at 1 - and tanh(+-inf) is a limit that happens to
  // be representable. Every one leaves the flag word EMPTY.
  const rows = [
    ["sin(-0)", () => c64.sin(c64.zero(1)), 0, 1],
    ["cos(-0)", () => c64.cos(c64.zero(1)), 1, 0],
    ["tan(+0)", () => c64.tan(c64.zero(0)), 0, 0],
    ["sinh(-0)", () => c64.sinh(c64.zero(1)), 0, 1],
    ["cosh(-0)", () => c64.cosh(c64.zero(1)), 1, 0],
    ["tanh(-0)", () => c64.tanh(c64.zero(1)), 0, 1],
    ["asinh(-0)", () => c64.asinh(c64.zero(1)), 0, 1],
    ["acosh(1)", () => c64.acosh(1), 0, 0],
    ["atanh(-0)", () => c64.atanh(c64.zero(1)), 0, 1],
    ["tanh(+inf)", () => c64.tanh(c64.inf(0)), 1, 0],
    ["tanh(-inf)", () => c64.tanh(c64.inf(1)), -1, 1],
  ];
  for (const [name, f, want, sign] of rows) {
    c64.clearFlags();
    const r = f();
    eq(r.toNumber(), want, `${name}: `);
    eq(r.sign, sign, `${name} sign: `);
    eq(c64.lastFlags, 0, `${name} raises nothing: `);
  }
  const inexact = [
    ["sin(1)", () => c64.sin(1)], ["cos(1)", () => c64.cos(1)],
    ["tan(1/2)", () => c64.tan(c64.from("0.5"))],
    ["sinh(1)", () => c64.sinh(1)], ["cosh(1)", () => c64.cosh(1)],
    ["tanh(1/2)", () => c64.tanh(c64.from("0.5"))],
    ["asinh(1)", () => c64.asinh(1)], ["acosh(2)", () => c64.acosh(2)],
    ["atanh(1/2)", () => c64.atanh(c64.from("0.5"))],
  ];
  for (const [name, f] of inexact) {
    c64.clearFlags();
    f();
    ok(c64.lastFlags & FLAG_INEXACT, `${name} is inexact`);
  }
});

test("sin, cos and tan of an infinity are invalid: no limit exists", () => {
  for (const fn of ["sin", "cos", "tan"]) {
    for (const s of [0, 1]) {
      c64.clearFlags();
      const r = c64[fn](c64.inf(s));
      ok(r.isNaN, `${fn}(${s ? "-" : "+"}inf) is a NaN`);
      ok(c64.lastFlags & FLAG_INVALID, `${fn}(inf) raises invalid`);
    }
  }
});

test("the hyperbolics' domains: acosh below 1 and atanh past 1 are invalid, atanh(+-1) is a pole", () => {
  for (const x of [c64.zero(0), c64.zero(1), c64.from("0.5"), -2, c64.inf(1)]) {
    c64.clearFlags();
    ok(c64.acosh(x).isNaN, "acosh below 1 is a NaN");
    ok(c64.lastFlags & FLAG_INVALID, "and invalid");
  }
  c64.clearFlags();
  ok(c64.acosh(c64.inf(0)).isInf, "acosh(+inf) is +inf");
  eq(c64.lastFlags, 0, "silently: ");
  c64.clearFlags();
  const p = c64.atanh(1);
  ok(p.isInf && p.sign === 0, "atanh(1) is +inf");
  ok(c64.lastFlags & FLAG_DIVBYZERO, "with divideByZero: 7.3's exact infinity");
  eq(c64.lastFlags & FLAG_INVALID, 0, "and NOT invalid: ");
  const m = c64.atanh(-1);
  ok(m.isInf && m.sign === 1, "atanh(-1) is -inf");
  for (const x of [2, c64.from("-1.5"), c64.inf(0), c64.inf(1)]) {
    c64.clearFlags();
    ok(c64.atanh(x).isNaN, "atanh past 1 is a NaN");
    ok(c64.lastFlags & FLAG_INVALID, "and invalid");
  }
  ok(c64.sinh(c64.inf(1)).isInf && c64.sinh(c64.inf(1)).sign === 1,
     "sinh(-inf) is -inf: odd");
  ok(c64.cosh(c64.inf(1)).isInf && c64.cosh(c64.inf(1)).sign === 0,
     "cosh(-inf) is +inf: even");
  ok(c64.asinh(c64.inf(1)).isInf && c64.asinh(c64.inf(1)).sign === 1,
     "asinh(-inf) is -inf");
});

test("tiny arguments take a SIDE, and the neighbour rules give it", () => {
  // sin, tanh and asinh lie on the zero side of a tiny x; tan, sinh and
  // atanh on the far side; cos below 1 and cosh above it. A directed
  // rounding is the only thing that can see which, and the value it
  // sees is the library's.
  const m = c64.fromBits(1n);                    // the smallest subnormal
  const two = c64.fromBits(2n);
  const rows = [
    ["rdn", "sin", "zero"], ["rup", "sin", "same"],
    ["rup", "tan", "next"], ["rtz", "tan", "same"],
    ["rup", "sinh", "next"], ["rdn", "sinh", "same"],
    ["rdn", "tanh", "zero"], ["rne", "tanh", "same"],
    ["rdn", "asinh", "zero"], ["rup", "asinh", "same"],
    ["rup", "atanh", "next"], ["rne", "atanh", "same"],
  ];
  for (const [attr, fn, want] of rows) {
    const c = c64.withRounding(attr);
    c.clearFlags();
    const r = c[fn](m);
    if (want === "zero") ok(r.isZero && r.sign === 0, `${fn} ${attr} is +0`);
    else if (want === "same") ok(r.sameBits(m), `${fn} ${attr} stays put`);
    else ok(r.sameBits(two), `${fn} ${attr} steps off it`);
    ok((c.lastFlags & FLAG_INEXACT) && (c.lastFlags & FLAG_UNDERFLOW),
       `${fn} ${attr} is tiny and inexact`);
  }
  const one = c64.from("1");
  ok(c64.withRounding("rdn").cos(m).sameBits(c64.nextDown(one)),
     "cos(min) downward is nextDown(1)");
  ok(c64.withRounding("rne").cos(m).sameBits(one), "cos(min) to nearest is 1");
  ok(c64.withRounding("rup").cosh(m).sameBits(c64.nextUp(one)),
     "cosh(min) upward is nextUp(1)");
  ok(c64.withRounding("rne").cosh(m).sameBits(one), "cosh(min) to nearest is 1");
});

test("the reduction against pi, through the wasm: the binary64 worst case", () => {
  // 0x1.6ac5b262ca1ffp+849 is the double nearest a multiple of pi/2;
  // host/tools/pi_worstcase.py rediscovers it. Its sine is 1 minus
  // about 2^-123, inside the half gap below 1, so the neighbour rule
  // beside 1 answers: 1 to nearest, nextDown(1) downward. Its cosine
  // is the reduced argument itself, and those bits are mpmath's at 700
  // bits - host/tests/api_test.c carries the same case in C.
  const x = c64.fromBits(0x7506ac5b262ca1ffn);
  const one = c64.from("1");
  c64.clearFlags();
  ok(c64.sin(x).sameBits(one), "sin(worst) to nearest is 1");
  ok(c64.lastFlags & FLAG_INEXACT, "and inexact");
  ok(c64.withRounding("rdn").sin(x).sameBits(c64.nextDown(one)),
     "sin(worst) downward is nextDown(1)");
  eq(c64.cos(x).bits, 0xbc214ae72e6ba22fn,
     "cos(worst) is the reduced argument: ");
  // and a huge argument reduces to a finite nonzero sine: sin(2^1023)
  const big = c64.fromBits(0x7fe0000000000000n);
  const s = c64.sin(big);
  ok(!s.isNaN && !s.isZero && !s.isInf, "sin(2^1023) is a finite nonzero number");
});


/** A random FINITE encoding within `span` binades of 1, built from the
 *  bits rather than from a decimal string. The decimal parser has a
 *  deliberately narrow window - it rounds with one exact library call
 *  or refuses (core.mjs) - and at binary32 a seven-digit random decimal
 *  falls outside it, so a test that wants operands rather than parsing
 *  asks for bits. Finite because the identities under test have one
 *  documented exception on an infinity beside a NaN, which gets its own
 *  test rather than a random encounter here. */
function randomFinite(ctx, rand, span = 20) {
  const fi = ctx.format;
  const sign = rand() < 0.5 ? 0n : 1n;
  const e = BigInt(fi.bias + Math.floor(rand() * (2 * span + 1)) - span);
  let man = 0n;
  for (let i = 0; i < fi.manW; i += 30)
    man = (man << 30n) | BigInt(Math.floor(rand() * (1 << 30)));
  man &= (1n << BigInt(fi.manW)) - 1n;
  return ctx.fromBits((sign << BigInt(fi.width - 1)) |
                      (e << BigInt(fi.manW)) | man);
}

// ---------------------------------------------------------------------
// the rest of IEEE 754-2019 table 9.1 (ABI 0.6)
//
// Ten operations, and what is new in them is EXACTNESS rather than
// machinery: each has a larger exact-case table than the function it is
// built from. The rows below are the ones cft.h writes down because a
// porter should not have to infer them, and every expected value here
// was taken from python/cft_golden rather than from memory.
// ---------------------------------------------------------------------

test("table 9.1's new exact cases are exact, and raise nothing", () => {
  const rows = [
    // 2^n - 1 is a dyadic rational for every n, so exp2m1 is exact at
    // every integer argument - a much larger table than exp2's.
    ["exp2m1(3) = 7", () => c64.exp2m1(3), 7],
    ["exp2m1(-1) = -1/2", () => c64.exp2m1(-1), -0.5],
    ["exp2m1(+0) = +0", () => c64.exp2m1(c64.zero(0)), 0],
    // exp10 at the non-negative integers whose 5^n fits in p+1 bits
    ["exp10(2) = 100", () => c64.exp10(2), 100],
    ["exp10m1(2) = 99", () => c64.exp10m1(2), 99],
    // log2p1 and log10p1 form 1 + x EXACTLY on the encoding
    ["log2p1(7) = 3", () => c64.log2p1(7), 3],
    ["log10p1(9) = 1", () => c64.log10p1(9), 1],
    // rSqrt exactly at the even powers of two
    ["rsqrt(4) = 1/2", () => c64.rsqrt(4), 0.5],
    ["rsqrt(1/16) = 4", () => c64.rsqrt(c64.from("0.0625")), 4],
    // powr and the integer-exponent three, on their exact rows
    ["powr(2, 3) = 8", () => c64.powr(2, 3), 8],
    ["pown(2, 10) = 1024", () => c64.pown(2, 10n), 1024],
    ["compound(1/2, 4) = 5.0625", () => c64.compound(c64.from("0.5"), 4), 5.0625],
    ["rootn(8, 3) = 2", () => c64.rootn(8, 3), 2],
    ["rootn(8, 1) = 8", () => c64.rootn(8, 1), 8],
  ];
  for (const [name, f, want] of rows) {
    c64.clearFlags();
    const r = f();
    eq(r.toNumber(), want, `${name}: `);
    eq(c64.lastFlags, 0, `${name} raises nothing: `);
  }
  // and a negative power of ten is not dyadic at all, so it is not
  // exact even though exp10 of a POSITIVE integer is
  c64.clearFlags();
  eq(c64.exp10(-1).bits, 0x3fb999999999999an, "exp10(-1): ");
  ok(c64.lastFlags & FLAG_INEXACT, "exp10(-1) is inexact");
});

test("rSqrt(±0) is ±infinity with divideByZero, and the SIGN survives", () => {
  // The standard's row is ±inf; GNU MPFR's mpfr_rec_sqrt returns +inf
  // for both zeros, and this contract follows the standard (cft.h).
  for (const s of [0, 1]) {
    c64.clearFlags();
    const r = c64.rsqrt(c64.zero(s));
    ok(r.isInf, `rsqrt(${s ? "-" : "+"}0) is an infinity`);
    eq(r.sign, s, `rsqrt(${s ? "-" : "+"}0) sign: `);
    ok(c64.lastFlags & FLAG_DIVBYZERO, "with divideByZero");
    eq(c64.lastFlags & FLAG_INVALID, 0, "and NOT invalid: ");
  }
  // it can neither overflow nor underflow at any rung
  for (const w of WIDTHS) {
    const c = ctxs[w];
    const fi = c.format;
    c.clearFlags();
    c.rsqrt(c.fromBits(1n));                       // smallest subnormal
    eq(c.lastFlags & (FLAG_OVERFLOW | FLAG_UNDERFLOW), 0,
       `rsqrt(min subnormal) at ${fi.ieeeName} neither over- nor underflows: `);
    c.clearFlags();
    c.rsqrt(c.fromBits((((1n << BigInt(fi.expW)) - 1n) <<
                        BigInt(fi.manW)) - 1n));   // largest finite
    eq(c.lastFlags & (FLAG_OVERFLOW | FLAG_UNDERFLOW), 0,
       `rsqrt(maxfinite) at ${fi.ieeeName} neither: `);
  }
});

test("powr is NOT pow, on every row where the two part company", () => {
  // powr(x, y) for x < 0 is invalid for EVERY y, a NaN included, where
  // pow(-1, 2) is 1; powr(±0, ±0), powr(+inf, ±0) and powr(+1, ±inf)
  // are invalid where pow answers 1; and powr(qNaN, y) is a quiet NaN
  // where pow(qNaN, 0) is 1.
  const invalid = [
    ["powr(-1, 2)", () => c64.powr(-1, 2)],
    ["powr(+0, +0)", () => c64.powr(c64.zero(0), c64.zero(0))],
    ["powr(-0, -0)", () => c64.powr(c64.zero(1), c64.zero(1))],
    ["powr(+inf, +0)", () => c64.powr(c64.inf(0), c64.zero(0))],
    ["powr(+1, +inf)", () => c64.powr(1, c64.inf(0))],
    ["powr(+1, -inf)", () => c64.powr(1, c64.inf(1))],
    ["powr(-1, qNaN)", () => c64.powr(-1, c64.nan())],
  ];
  for (const [name, f] of invalid) {
    c64.clearFlags();
    ok(f().isNaN, `${name} is a quiet NaN`);
    ok(c64.lastFlags & FLAG_INVALID, `${name} raises invalid`);
  }
  // and the NaN rows, which raise NOTHING
  for (const [name, f] of [["powr(qNaN, 2)", () => c64.powr(c64.nan(), 2)],
                           ["powr(+1, qNaN)", () => c64.powr(1, c64.nan())]]) {
    c64.clearFlags();
    ok(f().isNaN, `${name} is a quiet NaN`);
    eq(c64.lastFlags, 0, `${name} raises nothing: `);
  }
  // the same operands through pow, which answers differently
  eq(c64.pow(-1, 2).toNumber(), 1, "pow(-1, 2): ");
  eq(c64.pow(c64.nan(), 0).toNumber(), 1, "pow(qNaN, 0): ");
  eq(c64.pow(1, c64.nan()).toNumber(), 1, "pow(1, qNaN): ");
  eq(c64.pow(c64.zero(0), c64.zero(0)).toNumber(), 1, "pow(+0, +0): ");
});

test("the integer-exponent three follow 9.2.1's rows, not pow's", () => {
  // pown(x, 0) is 1 for any x that is not a signaling NaN - an
  // infinity and a quiet NaN included.
  for (const [name, x] of [["1", 1], ["+inf", c64.inf(0)], ["-inf", c64.inf(1)],
                           ["qNaN", c64.nan()], ["-0", c64.zero(1)]]) {
    c64.clearFlags();
    eq(c64.pown(x, 0).toNumber(), 1, `pown(${name}, 0): `);
    eq(c64.lastFlags, 0, `pown(${name}, 0) raises nothing: `);
  }
  // compound(x, 0) is 1 "for x >= -1 or quiet NaN", so an x BELOW -1
  // with n = 0 is INVALID rather than 1 - the row that separates it
  // from pown.
  c64.clearFlags();
  ok(c64.compound(-2, 0).isNaN, "compound(-2, 0) is a quiet NaN");
  ok(c64.lastFlags & FLAG_INVALID, "and invalid, where pown would answer 1");
  eq(c64.pown(-2, 0).toNumber(), 1, "pown(-2, 0): ");
  c64.clearFlags();
  eq(c64.compound(-1, 0).toNumber(), 1, "compound(-1, 0): ");
  eq(c64.compound(c64.zero(1), 5).toNumber(), 1, "compound(-0, 5): ");
  // compound(-1, n): +inf with divideByZero for n < 0, +0 for n > 0
  c64.clearFlags();
  const pole = c64.compound(-1, -2);
  ok(pole.isInf && pole.sign === 0, "compound(-1, -2) is +inf");
  ok(c64.lastFlags & FLAG_DIVBYZERO, "with divideByZero");
  c64.clearFlags();
  const z = c64.compound(-1, 3);
  ok(z.isZero && z.sign === 0, "compound(-1, 3) is +0");
  eq(c64.lastFlags, 0, "silently: ");
  // rootn(x, 0) is invalid for every x; rootn(x, 1) is x exactly and
  // silently; and rootn(-0, 2) is +0 where squareRoot(-0) is -0, which
  // is the difference the standard's own NOTE names.
  c64.clearFlags();
  ok(c64.rootn(8, 0).isNaN, "rootn(8, 0) is a quiet NaN");
  ok(c64.lastFlags & FLAG_INVALID, "and invalid: zero is outside the domain");
  const even = c64.rootn(c64.zero(1), 2);
  ok(even.isZero && even.sign === 0, "rootn(-0, 2) is +0 (the even-n row)");
  const odd = c64.rootn(c64.zero(1), 3);
  ok(odd.isZero && odd.sign === 1, "rootn(-0, 3) is -0 (the odd-n row)");
  ok(c64.sqrt(c64.zero(1)).sign === 1, "squareRoot(-0) is -0, which differs");
});

test("log2p1 and log10p1 have log's edges, one step over", () => {
  for (const fn of ["log2p1", "log10p1"]) {
    c64.clearFlags();
    const p = c64[fn](-1);
    ok(p.isInf && p.sign === 1, `${fn}(-1) is -inf`);
    ok(c64.lastFlags & FLAG_DIVBYZERO, `${fn}(-1) signals divideByZero`);
    eq(c64.lastFlags & FLAG_INVALID, 0, `${fn}(-1) is not invalid: `);
    c64.clearFlags();
    ok(c64[fn](-2).isNaN, `${fn}(-2) is a quiet NaN`);
    ok(c64.lastFlags & FLAG_INVALID, `${fn} below -1 is invalid`);
  }
  // 1 + x is formed EXACTLY, never as a rounded sum - which is the
  // whole reason these two functions exist. At x = 2^-1000 a rounded
  // 1 + x would be exactly 1, and the answer would be an exact,
  // silent +0. It is not: it is x/ln 2 and x/ln 10, inexact, and
  // these bits are python/cft_golden's.
  const x1000 = c64.scaleb(c64.from(1), -1000);
  for (const [fn, want] of [["log2p1", 0x01771547652b82fen],
                            ["log10p1", 0x015bcb7b1526e50en]]) {
    c64.clearFlags();
    const r = c64[fn](x1000);
    eq(r.bits, want, `${fn}(2^-1000) - a rounded 1 + x would give +0: `);
    ok(c64.lastFlags & FLAG_INEXACT, `${fn}(2^-1000) is inexact`);
  }
  // and at the subnormal floor the two land on opposite sides of the
  // smallest subnormal, which only a directed attribute can see:
  // 2^-1074/ln 2 is above it and 2^-1074/ln 10 is below.
  const tiny = c64.fromBits(1n);
  c64.clearFlags();
  eq(c64.log2p1(tiny).bits, 1n, "log2p1(min subnormal) to nearest: ");
  ok((c64.lastFlags & FLAG_UNDERFLOW) && (c64.lastFlags & FLAG_INEXACT),
     "tiny and inexact");
  eq(c64.log10p1(tiny).bits, 0n, "log10p1(min subnormal) to nearest is +0: ");
  eq(c64.withRounding("rup").log10p1(tiny).bits, 1n,
     "and upward it steps onto the smallest subnormal: ");
});

test("an integer operand is a BigInt or a safe integer, never a lost one", () => {
  // int64 is why: a JS number stops being an integer above 2^53, so a
  // value that large has already lost its identity before this package
  // could see it, and it is refused rather than silently widened.
  eq(c64.pown(2, 10).bits, c64.pown(2, 10n).bits, "10 and 10n agree: ");
  throws(() => c64.pown(2, 2 ** 60), "a number past 2^53 is not an integer");
  throws(() => c64.pown(2, 1.5), "a non-integer is not an exponent");
  throws(() => c64.pown(2, "3"), "a string is not an exponent");
  throws(() => c64.pown(2, 2n ** 63n), "2^63 is past INT64_MAX");
  // and the int64 extremes, which the published sets carry, go through
  const big = c64.pown(c64.from("1.5"), 9223372036854775807n);
  ok(big.isInf, "pown(1.5, INT64_MAX) overflows to an infinity");
  const small = c64.pown(c64.from("1.5"), -9223372036854775808n);
  ok(small.isZero, "pown(1.5, INT64_MIN) underflows to a zero");
});

test("all ten of table 9.1 reach every format, and the batch is the scalar", () => {
  const UNARY10 = ["exp2m1", "exp10", "exp10m1", "log2p1", "log10p1",
                   "rsqrt"];
  const INT10 = ["pown", "compound", "rootn"];
  for (const w of WIDTHS) {
    const c = ctxs[w];
    for (const fn of UNARY10) {
      const r = c[fn](c.from("0.5"));
      ok(!r.isNaN, `${fn} at ${c.format.ieeeName} is a number`);
      eq(r.bytes.length, c.format.size, `${fn} at ${w} width: `);
    }
    ok(!c.powr(2, c.from("0.5")).isNaN, `powr at ${c.format.ieeeName}`);
    for (const fn of INT10)
      ok(!c[fn](c.from("0.5"), 3).isNaN, `${fn} at ${c.format.ieeeName}`);
  }
  // batch equals scalar, element for element, for all ten - the three
  // with an integer exponent take their exponents as the SECOND array.
  const n = 129;
  const rand = mulberry32(0x0606);
  const xs = [], ns = [];
  for (let i = 0; i < n; i++) {
    xs.push(c64.from(String((rand() * 8 - 2).toFixed(6))));
    ns.push(BigInt(Math.floor(rand() * 9) - 4));
  }
  for (const fn of UNARY10) {
    c64.clearFlags();
    const batch = c64.map(fn, xs);
    let union = 0;
    xs.forEach((x, i) => {
      const one = c64.withRounding("rne");
      one.clearFlags();
      const s = one[fn](x);
      union |= one.lastFlags;
      ok(batch[i].sameBits(s), `${fn}[${i}] batch equals scalar`);
    });
    eq(c64.lastFlags, union, `${fn} batch flags are the union: `);
  }
  const powrBatch = c64.map("powr", xs.map((x) => c64.abs(x)), xs);
  xs.forEach((x, i) => ok(powrBatch[i].sameBits(c64.powr(c64.abs(x), x)),
                          `powr[${i}] batch equals scalar`));
  for (const fn of INT10) {
    const batch = c64.map(fn, xs, ns);
    xs.forEach((x, i) => ok(batch[i].sameBits(c64[fn](x, ns[i])),
                            `${fn}[${i}] batch equals scalar`));
  }
});

// ---------------------------------------------------------------------
// clause 5.12's character conversions and clause 9.7's payloads
// ---------------------------------------------------------------------

test("Pmin is the library's, and the round trip at it recovers the bits", () => {
  // 5.12.2 opens with a SHALL: under roundTiesToEven, format -> decimal
  // sequence -> format recovers the original representation. Pmin is
  // the digit count at which that is guaranteed - 9, 17, 36, 73 - and
  // it comes from the library rather than a table here.
  const want = { 32: 9, 64: 17, 128: 36, 256: 73 };
  const rand = mulberry32(0x5120);
  for (const w of WIDTHS) {
    const c = ctxs[w];
    eq(c.decimalDigits, want[w], `Pmin(${c.format.ieeeName}): `);
    let checked = 0;
    for (const bits of interestingBits(c.format, rand)) {
      const x = c.fromBits(bits);
      const s = c.toDecimal(x, { digits: c.decimalDigits });
      const back = c.fromDecimal(s);
      ok(back.sameBits(x),
         `${c.format.ieeeName} round trip at ${c.decimalDigits} digits: ` +
         `0x${bits.toString(16)} -> ${s.slice(0, 60)} -> ` +
         `0x${back.bits.toString(16)}`);
      checked++;
    }
    ok(checked > 40, `${c.format.ieeeName}: ${checked} encodings round-tripped`);
  }
});

test("the exact conversion is exact, and a digit count rounds", () => {
  // digits = 0 is 5.12.2's exact conversion: every digit of the exact
  // value, trailing zeros removed, no attribute consulted, no flag.
  c64.clearFlags();
  eq(c64.toDecimal(c64.from("1.5")), "1.5e+0", "exact 1.5: ");
  eq(c64.lastFlags, 0, "the exact conversion raises nothing: ");
  eq(c64.toDecimal(c64.zero(0)), "0", "+0: ");
  eq(c64.toDecimal(c64.zero(1), { digits: 9 }), "-0",
     "-0 at any digit count: ");
  // digits >= 1 keeps trailing zeros, so a caller who asked for h can
  // count h of them
  c64.clearFlags();
  eq(c64.toDecimal(c64.from("1.5"), { digits: 5 }), "1.5000e+0",
     "1.5 at 5 digits: ");
  eq(c64.lastFlags, 0, "nothing was dropped, so nothing is raised: ");
  // and inexact is raised when a digit WAS dropped
  c64.clearFlags();
  eq(c64.toDecimal(c64.from("0.1"), { digits: 3 }), "1.00e-1",
     "0.1 at 3 digits: ");
  ok(c64.lastFlags & FLAG_INEXACT, "a dropped digit is inexact");
  // the exact decimal of an extreme is long and still terminates
  const tiny = ctxs[256].fromBits(1n);
  const s = ctxs[256].toDecimal(tiny);
  ok(s.length > 180000,
     `the smallest binary256 subnormal's exact decimal is ${s.length} ` +
     `characters`);
});

test("the sizing protocol is the C's: ask, allocate, and a short buffer refuses", () => {
  // cft.h: *len is ALWAYS set, cap = 0 with a NULL buffer asks, and a
  // buffer too small is CFT_ERR_INVALID_ARGUMENT with *len set and
  // NOTHING written - this library does not truncate a number. All
  // three are checked by running them, not by reading the header.
  const x = c64.from("1.5");
  const ask = c64.toDecimalInto(x, 0);
  ok(ask.status !== 0, "the sizing call refuses rather than succeeding");
  eq(ask.len, "1.5e+0".length + 1, "and reports the length including the NUL: ");
  const short = c64.toDecimalInto(x, ask.len - 1);
  ok(short.status !== 0, "a buffer one byte short is refused");
  eq(short.len, ask.len, "and still reports the length: ");
  eq(short.text, null, "with nothing written: ");
  const exact = c64.toDecimalInto(x, ask.len);
  eq(exact.status, 0, "the buffer it asked for succeeds: ");
  eq(exact.text, "1.5e+0", "and carries the sequence: ");
  // toDecimal() runs that protocol for you and hands back the string
  eq(c64.toDecimal(x), exact.text, "toDecimal agrees with the raw protocol: ");
});

test("toHex is exact, canonical, and needs no attribute at all", () => {
  eq(ctxs[32].toHex(ctxs[32].fromBits(1n)), "0x1p-149",
     "the smallest binary32 subnormal prints its TRUE exponent: ");
  eq(c64.toHex(c64.zero(0)), "0x0p+0", "+0: ");
  eq(c64.toHex(c64.zero(1)), "-0x0p+0", "-0: ");
  eq(c64.toHex(c64.from("1.5")), "0x1.8p+0", "1.5: ");
  // exact always, in every attribute, and raising nothing. The operand
  // is built BEFORE the flags are cleared: parsing "0.1" is itself an
  // inexact library call, and a flag word measured across both would
  // be measuring the parse.
  const tenth = c64.from("0.1");
  for (const a of ATTRS) {
    const c = c64.withRounding(a);
    c.clearFlags();
    eq(c.toHex(tenth), c64.toHex(tenth), `toHex is the same under ${a}: `);
    eq(c.lastFlags, 0, `toHex raises nothing under ${a}: `);
  }
  // and it reads back exactly
  const rand = mulberry32(0x5123);
  for (const w of WIDTHS) {
    const c = ctxs[w];
    for (const bits of interestingBits(c.format, rand)) {
      const x = c.fromBits(bits);
      ok(c.fromHex(c.toHex(x)).sameBits(x),
         `${c.format.ieeeName} hex round trip 0x${bits.toString(16)}`);
    }
  }
});

test("a sequence outside 5.12's syntax is REFUSED, not guessed at", () => {
  // The refusal is as much a part of the contract as any value, and it
  // is the one part a set of encodings cannot express.
  for (const bad of ["1..2", "0x1.8", "", "1 000", " 1.5", "1.5 ",
                     "0x1.8p", "nan()", "1,5", "0b101", "++1"])
    throws(() => c64.fromDecimal(bad),
           `fromDecimal(${JSON.stringify(bad)}) must refuse`);
  // the hex form's binary exponent is REQUIRED - 5.12.3's grammar
  // writes {decExponent}, not {decExponent}?
  throws(() => c64.fromHex("0x1.8"), "a hex sequence needs its p exponent");
  throws(() => c64.fromHex("1.5"), "a decimal is not a hex sequence");
  eq(c64.fromHex("0x1.8p+0").bits, 0x3ff8000000000000n, "0x1.8p+0: ");
  // and the decimal parser takes no hexadecimal, which is the same
  // refusal from the other side
  throws(() => c64.fromDecimal("0x10"), "no hexadecimal in the decimal parser");
});

test("a NaN keeps its payload and its signaling bit through both directions", () => {
  // These are ENCODING operations, not arithmetic, so the
  // canonical-NaN rule does not govern them (cft.h) - and 5.12's own
  // requirement is that the round trip recover the representation. An
  // sNaN is written "snan", the spelling that raises NOTHING.
  const snan = c64.fromBits(0x7ff0000000000005n);
  const s = c64.toDecimal(snan);
  eq(s, "snan(0x5)", "an sNaN is written snan with its payload: ");
  c64.clearFlags();
  ok(c64.fromDecimal(s).sameBits(snan), "and reads back to the same bits");
  eq(c64.lastFlags, 0, "no conversion here ever raises invalid: ");
  const qnan = c64.fromBits(0x7ff8000000000005n);
  ok(c64.fromDecimal(c64.toDecimal(qnan)).sameBits(qnan),
     "a qNaN payload survives too");
  ok(c64.fromHex(c64.toHex(snan)).sameBits(snan),
     "and so does the hex round trip");
});

test("the from_ conversions batch, and their flag word is the OR", () => {
  const list = ["1.5", "0.1", "2", "1e400", "5e-400", "-0", "inf", "nan"];
  c64.clearFlags();
  const batch = c64.mapFromDecimal(list);
  const union = batch.map((_, i) => {
    const c = c64.withRounding("rne");
    c.clearFlags();
    c.fromDecimal(list[i]);
    return c.lastFlags;
  }).reduce((a, b) => a | b, 0);
  eq(c64.lastFlags, union, "the batch's flags are the OR of the cases: ");
  list.forEach((s, i) =>
    ok(batch[i].sameBits(c64.fromDecimal(s)),
       `batch[${i}] (${s}) equals the scalar conversion`));
  // one bad sequence refuses the WHOLE call and names the element
  throws(() => c64.mapFromDecimal(["1.5", "1..2", "2"]),
         "a batch with one bad sequence is refused whole");
  const hexes = ["0x1.8p+0", "0x1p-149", "-0x1.fp+3"];
  const hb = c64.mapFromHex(hexes);
  hexes.forEach((s, i) => ok(hb[i].sameBits(c64.fromHex(s)),
                             `hex batch[${i}] equals the scalar`));
});

test("the 9.7 payload operations, which signal nothing at all", () => {
  const qnan5 = c64.fromBits(0x7ff8000000000005n);
  c64.clearFlags();
  eq(c64.getPayload(qnan5).toNumber(), 5, "getPayload(qNaN payload 5): ");
  eq(c64.lastFlags, 0, "and signals nothing: ");
  // anything that is not a NaN gives -1, which is 9.7's own answer
  for (const [name, x] of [["1.0", 1], ["+inf", c64.inf(0)],
                           ["+0", c64.zero(0)]])
    eq(c64.getPayload(x).toNumber(), -1, `getPayload(${name}): `);
  eq(c64.setPayload(5).bits, 0x7ff8000000000005n, "setPayload(5): ");
  eq(c64.setPayloadSignaling(5).bits, 0x7ff0000000000005n,
     "setPayloadSignaling(5): ");
  // the admissibility test is on the VALUE, so -0 passes it as the
  // integer zero - 754 settles that -0 equals 0
  eq(c64.setPayload(c64.zero(1)).bits, 0x7ff8000000000000n,
     "setPayload(-0) is the payload-0 quiet NaN: ");
  // and payload 0 is NOT admissible for the signaling form, because
  // payload 0 with the quiet bit clear is an INFINITY encoding
  const z = c64.setPayloadSignaling(c64.zero(0));
  ok(z.isZero && z.sign === 0, "setPayloadSignaling(+0) is +0");
  // ANYTHING outside the admissible set is +0, per 9.7
  for (const [name, x] of [["1.5", c64.from("1.5")], ["-1", -1],
                           ["+inf", c64.inf(0)], ["qNaN", c64.nan()]]) {
    const r = c64.setPayload(x);
    ok(r.isZero && r.sign === 0, `setPayload(${name}) is +0`);
  }
  eq(c64.lastFlags, 0, "none of this signals: ");
  // elementwise over an array, and no flag word in that shape either
  const xs = [qnan5, c64.from(1), c64.inf(0)];
  const got = c64.map("get_payload", xs);
  xs.forEach((x, i) => ok(got[i].sameBits(c64.getPayload(x)),
                          `get_payload batch[${i}] equals the scalar`));
});

// ---------------------------------------------------------------------
// the augmented arithmetic (clause 9.5)
// ---------------------------------------------------------------------

/** The exact value of a list of Floats, summed in BigInt: each finite
 *  value is sign * m * 2^e exactly, so putting them over a common power
 *  of two and adding is exact arithmetic with no library and no
 *  opinion. Returns null if any operand is not finite. */
function exactSum(ctx, floats) {
  const parts = floats.map((f) => decode(ctx.format, f.bits));
  if (parts.some((p) => p.kind !== "finite" && p.kind !== "zero")) return null;
  const es = parts.filter((p) => p.kind === "finite").map((p) => p.e);
  const e0 = es.length ? Math.min(...es) : 0;
  let acc = 0n;
  for (const p of parts) {
    if (p.kind === "zero") continue;
    const v = p.m << BigInt(p.e - e0);
    acc += p.sign ? -v : v;
  }
  return { m: acc, e: e0 };
}

function sameExact(A, B) {
  if (A === null || B === null) return false;
  const e = Math.min(A.e, B.e);
  return (A.m << BigInt(A.e - e)) === (B.m << BigInt(B.e - e));
}

test("the augmented pair reconstructs its operation EXACTLY", () => {
  // r + e is exactly x op y - that is the whole point of the pair, and
  // it is what a compensated summation is built out of. Checked two
  // ways, because the two say different things: in BigInt, which is
  // exact for any operands at all, and through the LIBRARY'S OWN add
  // on the wider format, which is an independent route to the same
  // claim wherever the exact sum fits binary128's 113 bits.
  const c128 = ctxs[128];
  const rand = mulberry32(0x0905);
  let checked = 0, widened = 0;
  const pairs = [
    [c64.from("1"), c64.fromBits(0x3ca0000000000000n)],   // 1, 2^-53
    [c64.from("0.1"), c64.from("0.2")],
    [c64.from("3"), c64.from("-3")],
    [c64.from("-3"), c64.zero(0)],
    [c64.fromBits(0x3ff0000000000001n), c64.fromBits(0x3ca0000000000000n)],
    [c64.fromBits(1n), c64.fromBits(2n)],
  ];
  for (let i = 0; i < 60; i++) {
    // operands within 40 binades of each other, so the exact sum fits
    // binary128 and the library's own add can be the second witness
    const e = Math.floor(rand() * 40) - 20;
    pairs.push([c64.from(String((rand() * 4 - 2).toFixed(9))),
                c64.scaleb(c64.from(String((rand() * 4 - 2).toFixed(9))), e)]);
  }
  for (const [x, y] of pairs) {
    for (const [name, fn, wide] of [
      ["augmentedAdd", "augmentedAdd", (a, b) => c128.add(a, b)],
      ["augmentedSub", "augmentedSub", (a, b) => c128.sub(a, b)],
      ["augmentedMul", "augmentedMul", (a, b) => c128.mul(a, b)],
    ]) {
      c64.clearFlags();
      const { r, e } = c64[fn](x, y);
      if (r.isNaN || r.isInf) continue;
      // 9.5's one exception: augmentedMultiplication's residual can
      // fail to be representable, and is then delivered ROUNDED with
      // underflow AND inexact. That is the only case in which r + e is
      // not exact, and the flag word says which case it is.
      if (name === "augmentedMul" && (c64.lastFlags & FLAG_INEXACT)) continue;
      const lhs = exactSum(c64, [r, e]);
      const rhs = name === "augmentedSub"
        ? exactSum(c64, [x, c64.neg(y)]) : null;
      if (name !== "augmentedMul") {
        ok(sameExact(lhs, rhs ?? exactSum(c64, [x, y])),
           `${name}(${x.toString().slice(0, 20)}, ` +
           `${y.toString().slice(0, 20)}): r + e is exactly the operation`);
        checked++;
      }
      // the second witness: the LIBRARY's add on binary128, where the
      // exact result fits it. Widening from binary64 is exact and
      // silent, so any inexact here would be the 128-bit add's.
      c128.clearFlags();
      const wr = c128.convert(r), we = c128.convert(e);
      const sum = c128.add(wr, we);
      c128.clearFlags();
      const truth = wide(c128.convert(x), c128.convert(y));
      if (!(c128.lastFlags & FLAG_INEXACT) && !truth.isNaN) {
        ok(sum.sameBits(truth),
           `${name}: the library's binary128 add agrees that r + e is ` +
           `the operation`);
        widened++;
      }
    }
  }
  ok(checked > 100, `${checked} pairs reconstructed exactly in BigInt`);
  ok(widened > 50, `${widened} confirmed by the library's own binary128 add`);
});

test("roundTiesTowardZero is 9.5's own direction, and is not ties-to-even", () => {
  // The tie rule differs from roundTiesToEven only at an exact midpoint
  // whose lower neighbour is odd - so an implementation that quietly
  // used RNE would pass every test that did not aim there. This one
  // aims there: nextUp(1) has an odd last bit, and adding half an ulp
  // lands exactly on the midpoint above it.
  const x = c64.fromBits(0x3ff0000000000001n);      // nextUp(1), odd
  const y = c64.fromBits(0x3ca0000000000000n);      // 2^-53, half an ulp
  const { r, e } = c64.augmentedAdd(x, y);
  eq(r.bits, 0x3ff0000000000001n,
     "roundTiesTowardZero takes the SMALLER magnitude at the tie: ");
  eq(e.bits, 0x3ca0000000000000n, "and the residual is the other half: ");
  eq(c64.add(x, y).bits, 0x3ff0000000000002n,
     "roundTiesToEven takes the even neighbour instead: ");
  // and no attribute changes the augmented answer, because there is
  // none to pass
  for (const a of ATTRS) {
    const c = c64.withRounding(a);
    eq(c.augmentedAdd(x, y).r.bits, r.bits,
       `augmentedAdd is unchanged under ${a}: `);
  }
});

test("the sign of a zero e is r's, and 9.5's special rows hold", () => {
  // "augmentedAddition(-3, 0) delivers (-3, -0) and
  //  augmentedAddition(3, -3) delivers (+0, +0)" - cft.h
  let p = c64.augmentedAdd(-3, c64.zero(0));
  eq(p.r.toNumber(), -3, "augmentedAdd(-3, +0) r: ");
  ok(p.e.isZero && p.e.sign === 1, "and e is -0, taking r's sign");
  p = c64.augmentedAdd(3, -3);
  ok(p.r.isZero && p.r.sign === 0, "augmentedAdd(3, -3) r is +0");
  ok(p.e.isZero && p.e.sign === 0, "and e is +0");
  // any NaN operand gives the canonical quiet NaN as BOTH results, and
  // an invalid operation produces the same quiet NaN for both outputs
  c64.clearFlags();
  p = c64.augmentedAdd(c64.inf(0), c64.inf(1));
  ok(p.r.isNaN && p.e.isNaN, "inf + (-inf) is a NaN in both results");
  ok(p.r.sameBits(p.e), "and the SAME quiet NaN for both outputs");
  ok(c64.lastFlags & FLAG_INVALID, "with invalid");
  c64.clearFlags();
  p = c64.augmentedMul(c64.inf(0), c64.zero(0));
  ok(p.r.isNaN && p.e.isNaN && p.r.sameBits(p.e),
     "inf * 0 is the same quiet NaN in both");
  ok(c64.lastFlags & FLAG_INVALID, "with invalid");
  c64.clearFlags();
  p = c64.augmentedAdd(c64.nan(), 1);
  ok(p.r.isNaN && p.e.isNaN, "a quiet NaN propagates as both results");
  eq(c64.lastFlags, 0, "and raises nothing, being quiet: ");
  // an infinite r from an infinite OPERAND signals nothing; from
  // OVERFLOW it signals overflow and inexact, and always delivers an
  // infinity, because roundTiesTowardZero carries overflow to infinity
  c64.clearFlags();
  p = c64.augmentedAdd(c64.inf(0), 1);
  ok(p.r.isInf && p.e.isInf, "an infinite operand gives infinity in both");
  eq(c64.lastFlags, 0, "silently: ");
  c64.clearFlags();
  const big = c64.fromBits(0x7fefffffffffffffn);
  p = c64.augmentedAdd(big, big);
  ok(p.r.isInf && p.e.isInf, "overflow delivers an infinity in both");
  ok(c64.lastFlags & FLAG_OVERFLOW, "with overflow");
  ok(c64.lastFlags & FLAG_INEXACT, "and inexact");
});

test("underflow is a statement about e, and comes WITHOUT inexact", () => {
  // "it is raised when e is non-zero and lies strictly between
  //  +-b^emin. Since e is exact, that is underflow WITHOUT inexact -
  //  the one place in this contract where those two part company."
  c64.clearFlags();
  const { r, e } = c64.augmentedAdd(1, c64.fromBits(1n));
  eq(r.toNumber(), 1, "r is 1: ");
  eq(e.bits, 1n, "e is the smallest subnormal, exactly: ");
  ok(c64.lastFlags & FLAG_UNDERFLOW, "underflow is raised");
  eq(c64.lastFlags & FLAG_INEXACT, 0, "and inexact is NOT: ");
  // a subnormal r with an exactly representable residual raises
  // nothing at all - "the operation's subnormal and zero results are
  // exact"
  c64.clearFlags();
  c64.augmentedAdd(c64.fromBits(1n), c64.fromBits(2n));
  eq(c64.lastFlags, 0, "a subnormal sum with an exact residual is silent: ");
});

test("the augmented three batch, with two arrays out", () => {
  const n = 65;
  const rand = mulberry32(0x0955);
  const xs = [], ys = [];
  for (let i = 0; i < n; i++) {
    xs.push(c64.from(String((rand() * 8 - 4).toFixed(9))));
    ys.push(c64.from(String((rand() * 8 - 4).toFixed(9))));
  }
  for (const [name, fn] of [["augmentedAddition", "augmentedAdd"],
                            ["augmentedSubtraction", "augmentedSub"],
                            ["augmentedMultiplication", "augmentedMul"]]) {
    c64.clearFlags();
    const batch = c64.map(name, xs, ys);
    let union = 0;
    xs.forEach((x, i) => {
      const c = c64.withRounding("rne");
      c.clearFlags();
      const p = c[fn](x, ys[i]);
      union |= c.lastFlags;
      ok(batch.r[i].sameBits(p.r), `${name} batch r[${i}] equals the scalar`);
      ok(batch.e[i].sameBits(p.e), `${name} batch e[${i}] equals the scalar`);
    });
    eq(c64.lastFlags, union, `${name} batch flags are the union: `);
  }
});

// ---------------------------------------------------------------------
// clause 9.4's remaining reductions and the scaled products
// ---------------------------------------------------------------------

test("sumSquare is dot(x, x) and sumAbs is sum(|x|), through the package", () => {
  // They are the SAME tree over a different leaf, so the library issues
  // exactly those compositions and both backends agree by construction
  // rather than by testing. This drives all four through this package
  // and holds the identity, bit for bit and flag for flag.
  const rand = mulberry32(0x0904);
  for (const w of WIDTHS) {
    const c = ctxs[w];
    for (const n of [0, 1, 2, 5, 17, 64, 129]) {
      const xs = [];
      for (let i = 0; i < n; i++) xs.push(randomFinite(c, rand, 20));
      c.clearFlags();
      const sq = c.reduce("sumsq", xs);
      const sqFlags = c.lastFlags;
      c.clearFlags();
      const dot = c.reduce("dot", xs, xs);
      ok(sq.sameBits(dot),
         `${c.format.ieeeName} n=${n}: sumsq == dot(x, x)`);
      eq(sqFlags, c.lastFlags, `${c.format.ieeeName} n=${n} sumsq flags: `);
      c.clearFlags();
      const ab = c.reduce("sumabs", xs);
      const abFlags = c.lastFlags;
      c.clearFlags();
      const sum = c.reduce("sum", xs.map((v) => c.abs(v)));
      ok(ab.sameBits(sum),
         `${c.format.ieeeName} n=${n}: sumabs == sum(|x|)`);
      eq(abFlags, c.lastFlags, `${c.format.ieeeName} n=${n} sumabs flags: `);
    }
  }
  throws(() => c64.reduce("sumsq", [c64.from(1)], [c64.from(1)]),
         "only dot takes a second array");
  throws(() => c64.reduce("product", [c64.from(1)]), "an unknown reduction");
});

test("the ONE row where sumsq and sumabs are not the composition", () => {
  // 754-2019 9.4: "For sumSquare and sumAbs, if any operand element is
  // an infinity, +inf is returned. Otherwise, if any operand element is
  // a NaN a quiet NaN is returned" - infinity ahead of NaN, where sum
  // and dot put the NaN first. That single row is the whole difference.
  const mix = [c64.inf(0), c64.nan()];
  for (const fn of ["sumsq", "sumabs"]) {
    c64.clearFlags();
    const r = c64.reduce(fn, mix);
    ok(r.isInf && r.sign === 0, `${fn}([+inf, qNaN]) is +inf`);
    eq(c64.lastFlags, 0, `${fn} raises nothing on a quiet NaN: `);
  }
  c64.clearFlags();
  ok(c64.reduce("sum", mix).isNaN,
     "sum of the same vector is a quiet NaN - the row that differs");
  ok(c64.reduce("dot", mix, mix).isNaN, "and so is dot");
  // invalid is raised only if one of those NaNs is SIGNALLING
  const snan = c64.fromBits(0x7ff0000000000005n);
  c64.clearFlags();
  const r = c64.reduce("sumsq", [c64.inf(0), snan]);
  ok(r.isInf, "sumsq([+inf, sNaN]) is still +inf");
  ok(c64.lastFlags & FLAG_INVALID, "with invalid, by 9.4's blanket rule");
  // n == 1: the leaf differs, and cft.h says how. sumsq's leaf IS a
  // multiply, so it quiets and signals; sumabs's is an abs, which by
  // 5.5.1 signals nothing at all.
  c64.clearFlags();
  ok(c64.reduce("sumsq", [snan]).isNaN, "sumsq([sNaN]) at n=1 is a quiet NaN");
  ok(c64.lastFlags & FLAG_INVALID, "and signals: the leaf is a multiply");
  c64.clearFlags();
  const lone = c64.reduce("sumabs", [snan]);
  eq(lone.bits, snan.bits,
     "sumabs([sNaN]) at n=1 comes back with its sign cleared: ");
  eq(c64.lastFlags, 0, "and NO flag: the leaf is an abs (5.5.1): ");
  // n == 0 is +0 and raises nothing, for all four
  for (const fn of ["sum", "sumsq", "sumabs"]) {
    c64.clearFlags();
    const z = c64.reduce(fn, []);
    ok(z.isZero && z.sign === 0, `${fn}([]) is +0`);
    eq(c64.lastFlags, 0, `${fn}([]) raises nothing: `);
  }
});

test("a scaled product's pair reconstructs its product", () => {
  // scaleB(pr, sf) is the answer, and pr is in +-[1, 2) for every n.
  // Reconstructed two ways: through the library's own scaleB, and
  // exactly in BigInt from the encoding.
  const cases = [
    [[12], 12],
    [[3, 5], 15],
    [[2, 2, 2, 2], 16],
    [[1.5, -4], -6],
    [[7], 7],
  ];
  for (const [vals, want] of cases) {
    const xs = vals.map((v) => c64.from(v));
    c64.clearFlags();
    const { pr, sf } = c64.scaledProd(xs);
    eq(typeof sf, "bigint", "the scale is a BigInt - it is int64: ");
    // pr is in +-[1, 2): the exponent of |pr| is exactly 0
    const parts = decode(c64.format, pr.bits);
    eq(parts.e + parts.m.toString(2).length - 1, 0,
       `pr for [${vals}] is in ±[1, 2): `);
    ok(c64.scaleb(pr, sf).toNumber() === want,
       `scaleB(pr, sf) for [${vals}] is ${want}`);
    // and the same reconstruction in exact integers, no library at all
    const ex = decode(c64.format, pr.bits);
    const shift = BigInt(ex.e) + sf;
    const exact = shift >= 0n ? ex.m << shift : null;
    if (exact !== null)
      eq(Number(ex.sign ? -exact : exact), want,
         `pr * 2^sf for [${vals}] in BigInt: `);
  }
  // n == 0 is 9.4's multiplicative identity, "without exception"
  c64.clearFlags();
  const empty = c64.scaledProd([]);
  eq(empty.pr.toNumber(), 1, "scaledProd([]) pr: ");
  eq(empty.sf, 0n, "scaledProd([]) sf: ");
  eq(c64.lastFlags, 0, "and raises nothing: ");
  // it cannot overflow or underflow, by construction: a product far
  // outside binary64's range still comes back as a pair
  const huge = [];
  for (let i = 0; i < 200; i++) huge.push(c64.fromBits(0x7fefffffffffffffn));
  c64.clearFlags();
  const h = c64.scaledProd(huge);
  ok(!h.pr.isInf && !h.pr.isZero,
     "200 copies of maxfinite give a finite normal pr");
  ok(h.sf > 200000n, `and a large scale (${h.sf})`);
  eq(c64.lastFlags & (FLAG_OVERFLOW | FLAG_UNDERFLOW), 0,
     "with neither overflow nor underflow: ");
});

test("the scaled sums and differences are their compositions, a first", () => {
  // cft.h: scaled_prod_sum(a, b) == scaled_prod(run(ADD, a, b)) and
  // scaled_prod_diff(a, b) == scaled_prod(run(SUB, a, b)), with the
  // add's flags OR'd in. Checked by running both.
  const rand = mulberry32(0x0940);
  for (const n of [1, 2, 5, 33]) {
    const xs = [], ys = [];
    for (let i = 0; i < n; i++) {
      xs.push(c64.from(String((rand() * 20 - 10).toFixed(6))));
      ys.push(c64.from(String((rand() * 20 - 10).toFixed(6))));
    }
    for (const [fn, op] of [["scaledProdSum", (a, b) => c64.add(a, b)],
                            ["scaledProdDiff", (a, b) => c64.sub(a, b)]]) {
      const got = c64[fn](xs, ys);
      const leaves = xs.map((x, i) => op(x, ys[i]));
      const want = c64.scaledProd(leaves);
      ok(got.pr.sameBits(want.pr), `${fn} n=${n}: pr is the composition's`);
      eq(got.sf, want.sf, `${fn} n=${n} sf: `);
    }
  }
  // the operand order is visible: a - b, not b - a
  const d1 = c64.scaledProdDiff([c64.from(1)], [c64.from(2)]);
  const d2 = c64.scaledProdDiff([c64.from(2)], [c64.from(1)]);
  eq(d1.pr.toNumber(), -1, "scaledProdDiff([1], [2]) pr: ");
  eq(d2.pr.toNumber(), 1, "scaledProdDiff([2], [1]) pr: ");
  eq(d1.sf, 0n, "scaledProdDiff([1], [2]) sf: ");
  throws(() => c64.scaledProdSum([c64.from(1)], [c64.from(1), c64.from(2)]),
         "mismatched operand arrays");
});

test("9.4's special rows for a scaled product, in 9.4's order", () => {
  // any factor a NaN -> quiet NaN, sf = 0; an infinity AND a zero ->
  // invalid; an infinity with no zero -> that infinity, no exception; a
  // zero with no infinity -> a zero, no exception. divideByZero is
  // NEVER signalled, which 9.4 asks for explicitly.
  c64.clearFlags();
  let p = c64.scaledProd([c64.inf(0), c64.zero(0)]);
  ok(p.pr.isNaN, "inf x 0 is a quiet NaN");
  eq(p.sf, 0n, "with sf 0: ");
  ok(c64.lastFlags & FLAG_INVALID, "and invalid");
  c64.clearFlags();
  p = c64.scaledProd([c64.inf(0), c64.from(2)]);
  ok(p.pr.isInf && p.pr.sign === 0, "an infinity with no zero is that infinity");
  eq(p.sf, 0n, "sf 0: ");
  eq(c64.lastFlags, 0, "and NO exception: ");
  c64.clearFlags();
  p = c64.scaledProd([c64.from(-2), c64.zero(0)]);
  ok(p.pr.isZero && p.pr.sign === 1,
     "a zero with no infinity is a zero with the true product's sign");
  eq(c64.lastFlags, 0, "silently: ");
  c64.clearFlags();
  p = c64.scaledProd([c64.nan(), c64.from(2)]);
  ok(p.pr.isNaN, "a NaN factor gives a quiet NaN");
  eq(c64.lastFlags, 0, "and a QUIET NaN raises nothing: ");
  // divideByZero never, even with a zero in the vector
  eq(c64.lastFlags & FLAG_DIVBYZERO, 0, "no divideByZero anywhere: ");
});

// ---------------------------------------------------------------------
// ABI 0.7, package B: the status word (7.1, 5.7.4)
//
// The word lives on the DEVICE and nothing in the library ever lowers
// it. What these check is mostly that this package did not build a
// second one beside it - which it did until 0.7, and which was right
// only by construction.
// ---------------------------------------------------------------------

test("the sticky word IS the library's word, not a copy beside it", () => {
  // raiseFlags touches ONLY the C - it is 7.1's "raised without an
  // exception being signaled at the user's request" and no arithmetic
  // happens. If Context.flags were a JavaScript field it would still
  // read 0 here, so this is the discriminator between one word and two.
  c64.clearFlags();
  eq(c64.flags, 0, "a lowered word reads: ");
  c64.raiseFlags(FLAG_OVERFLOW);
  eq(c64.flags, FLAG_OVERFLOW, "after raiseFlags(overflow), flags: ");
  ok(c64.testFlags(FLAG_OVERFLOW), "and testFlags agrees");
  ok(!c64.testFlags(FLAG_INVALID), "while an unraised flag does not");
  // saveAllFlags is a third entry point onto the same word
  eq(c64.saveAllFlags(), FLAG_OVERFLOW, "saveAllFlags: ");
  c64.clearFlags();
  eq(c64.flags, 0, "and clearFlags reaches the library: ");
  ok(!c64.testFlags(FLAGS_ALL), "the library agrees it is empty");
});

test("one word per DEVICE, seen through every context over it", () => {
  // withRounding() makes a second Context object over one device. The
  // flags belong to the computation, not to the attribute it ran
  // under, so both must see one word - which is exactly what a
  // per-Context JavaScript copy could not do.
  c64.clearFlags();
  const up = c64.withRounding("rup");
  const dn = c64.withRounding("rdn");
  up.from("0.1");                       // inexact, raised through `up`
  ok(dn.flags & FLAG_INEXACT, "a call through one context is visible in another");
  ok(c64.flags & FLAG_INEXACT, "and in the context they came from");
  eq(dn.lastFlags, 0, "lastFlags stays per-object: ");
  dn.clearFlags();
  eq(up.flags, 0, "and lowering through one lowers the word for all: ");
  // toNumber opens a temporary fp64 context over the same device, so
  // its rounding lands in the same word rather than in a private one
  const c32 = ctxs[32];
  c32.clearFlags();
  c32.toNumber(c32.from("0.1"));
  ok(c32.flags & FLAG_INEXACT, "the temporary context's flags reach the word");
  c32.clearFlags();
});

test("nothing in the library lowers a flag - only the user", () => {
  // VALIDATION's row: three calls raising overflow+inexact,
  // divideByZero and invalid, and the word holds all four afterwards.
  c64.clearFlags();
  const big = c64.fromBits(0x7fefffffffffffffn);
  c64.mul(big, big);                                   // overflow|inexact
  c64.div(c64.from(1), c64.zero(0));                   // divideByZero
  c64.nextUp(c64.fromBits(0x7ff0000000000001n));       // sNaN -> invalid
  const want = FLAG_OVERFLOW | FLAG_INEXACT | FLAG_DIVBYZERO | FLAG_INVALID;
  eq(c64.flags, want, "three calls, four flags standing: ");
  // and a clean call adds nothing and removes nothing
  const before = c64.saveAllFlags();
  c64.add(1, 1);
  eq(c64.lastFlags, 0, "an exact add raises nothing: ");
  eq(c64.flags, before, "and leaves the word exactly where it was: ");
  c64.clearFlags();
});

test("5.7.4's six work on an exceptionGroup, not on all-or-nothing", () => {
  c64.clearFlags();
  c64.raiseFlags(FLAG_INVALID | FLAG_INEXACT | FLAG_OVERFLOW);
  c64.lowerFlags(FLAG_INEXACT);
  eq(c64.flags, FLAG_INVALID | FLAG_OVERFLOW, "lowering one bit leaves the rest: ");
  ok(c64.testFlags(FLAG_INVALID | FLAG_UNDERFLOW),
     "testFlags is ANY of the group, not all of it");
  ok(!c64.testFlags(FLAG_UNDERFLOW | FLAG_DIVBYZERO),
     "and false when the group is disjoint from the word");
  c64.clearFlags();
});

test("save and restore is a round trip, and RESTORES rather than ORs", () => {
  c64.clearFlags();
  c64.raiseFlags(FLAG_INVALID);
  const saved = c64.saveAllFlags();
  eq(saved, FLAG_INVALID, "saved: ");
  c64.raiseFlags(FLAG_INEXACT | FLAG_OVERFLOW);
  c64.restoreFlags(saved, FLAGS_ALL);
  eq(c64.flags, FLAG_INVALID,
     "restore puts the word back, so a flag low in `saved` comes back low: ");
  // flags OUTSIDE the mask are untouched, which is what makes the mask
  // worth having
  c64.raiseFlags(FLAG_UNDERFLOW);
  c64.restoreFlags(0, FLAG_INVALID);
  eq(c64.flags, FLAG_UNDERFLOW,
     "restoring only invalid left underflow alone: ");
  // the pure predicate: same question, no device
  ok(Context.testSavedFlags(saved, FLAG_INVALID), "testSavedFlags(saved, invalid)");
  ok(!Context.testSavedFlags(saved, FLAG_INEXACT), "and not inexact");
  eq(c64.testSavedFlags(saved, FLAG_INVALID),
     Context.testSavedFlags(saved, FLAG_INVALID),
     "the library's answer and the static one agree: ");
  eq(c64.testSavedFlags(0, FLAGS_ALL), false, "an empty word tests false: ");
  c64.clearFlags();
});

test("an exceptionGroup is checked, not just passed through", () => {
  throws(() => c64.raiseFlags(1 << 20),
         "a bit no exception of this library owns");
  throws(() => c64.lowerFlags("inexact"),
         "a name where 5.7.4's representation is a mask");
  throws(() => c64.testFlags(-1), "a negative mask is not a subset");
  eq(FLAGS_ALL, FLAG_INVALID | FLAG_DIVBYZERO | FLAG_OVERFLOW |
                FLAG_UNDERFLOW | FLAG_INEXACT,
     "FLAGS_ALL is the five, derived: ");
});

// Opened here rather than inside the test, because test() runs its
// body synchronously: an `async` body would have its failures land in
// a rejected promise nobody reads, and the test would pass no matter
// what it found.
const freshCtx = await Context.open(64);

test("a fresh device opens with every flag lowered (7.1)", () => {
  // "A program that does not inherit status flags from another source
  // begins execution with all status flags lowered."
  eq(freshCtx.flags, 0, "a device that has computed nothing: ");
  ok(!freshCtx.testFlags(FLAGS_ALL), "and the library agrees");
  // ... and it is ITS OWN word: raising here must not touch c64's
  c64.clearFlags();
  freshCtx.raiseFlags(FLAG_INVALID);
  eq(c64.flags, 0, "another device's word is untouched: ");
  eq(freshCtx.flags, FLAG_INVALID, "while its own moved: ");
});

// ---------------------------------------------------------------------
// ABI 0.7, package B: 5.7.1's three conformance predicates
// ---------------------------------------------------------------------

// The device-free forms, awaited out here for the same reason.
const FREE_VERSIONS = [await is754version1985(), await is754version2008(),
                       await is754version2019()];

test("5.7.1's predicates: 1985 no, 2008 no, 2019 yes", () => {
  eq(c64.is754version1985(), false, "is754version1985: ");
  eq(c64.is754version2008(), false, "is754version2008: ");
  eq(c64.is754version2019(), true, "is754version2019: ");
  // the same three without a device, because 5.7.1 asks about the
  // programming environment rather than about a number
  eq(FREE_VERSIONS[0], c64.is754version1985(), "free vs method 1985: ");
  eq(FREE_VERSIONS[1], c64.is754version2008(), "free vs method 2008: ");
  eq(FREE_VERSIONS[2], c64.is754version2019(), "free vs method 2019: ");
});

test("2008 is false BECAUSE of the row 9.6 changed", () => {
  // 754-2008 required minNum/maxNum/minNumMag/maxNumMag; 754-2019
  // replaced them with 9.6's recommended operations and changed the
  // signaling-NaN rule - 2008's minNum said nothing about it, 2019's
  // minimumNumber signals invalid and still returns the number. This
  // library implements the 2019 row, which is what makes the predicate
  // above answer no rather than yes.
  const snan = c64.fromBits(0x7ff0000000000001n);
  c64.clearFlags();
  const got = c64.minnumMag(snan, c64.from(3));
  eq(got.toNumber(), 3, "minimumMagnitudeNumber(sNaN, 3) returns the number: ");
  ok(c64.lastFlags & FLAG_INVALID, "and signals invalid, which 2008 did not");
  c64.clearFlags();
});

// ---------------------------------------------------------------------
// ABI 0.7, package B: 9.6's four magnitude forms
//
// Each is "x if |x| < |y|, y if |y| < |x|, otherwise <the operation
// named last>". Everything below is that sentence read literally.
// ---------------------------------------------------------------------

test("the magnitude forms pick by magnitude when the magnitudes differ", () => {
  for (const w of WIDTHS) {
    const c = ctxs[w];
    const a = c.from(-5), b = c.from(2);
    ok(c.minMag(a, b).sameBits(b), `${w}: minMag(-5, 2) is 2`);
    ok(c.maxMag(a, b).sameBits(a), `${w}: maxMag(-5, 2) is -5`);
    ok(c.minnumMag(a, b).sameBits(b), `${w}: minnumMag(-5, 2) is 2`);
    ok(c.maxnumMag(a, b).sameBits(a), `${w}: maxnumMag(-5, 2) is -5`);
    c.clearFlags();
    c.minMag(a, b);
    eq(c.lastFlags, 0, `${w}: a selection of two numbers raises nothing: `);
  }
});

test("EQUAL MAGNITUDES defer, and that is the row worth its own test", () => {
  // "otherwise minimum(x, y)" - so +-3 is not "return x" and not
  // "return y", it is minimum(+3, -3) = -3 and maximum(+3, -3) = +3.
  // An implementation that quietly prefers an operand on this tie is
  // wrong here and invisible everywhere else.
  for (const w of WIDTHS) {
    const c = ctxs[w];
    const p = c.from(3), m = c.from(-3);
    eq(c.minMag(p, m).toString(), "-3e+0", `${w}: minMag(+3, -3): `);
    eq(c.maxMag(p, m).toString(), "3e+0", `${w}: maxMag(+3, -3): `);
    // ... and the same the other way round, because deferral does not
    // care about operand order
    eq(c.minMag(m, p).toString(), "-3e+0", `${w}: minMag(-3, +3): `);
    eq(c.maxMag(m, p).toString(), "3e+0", `${w}: maxMag(-3, +3): `);
    eq(c.minnumMag(p, m).toString(), "-3e+0", `${w}: minnumMag(+3, -3): `);
    eq(c.maxnumMag(p, m).toString(), "3e+0", `${w}: maxnumMag(+3, -3): `);
    // +-0 have equal magnitude too, so the zeros come from the base
    // operation: -0 for the minima, +0 for the maxima
    eq(c.minMag(c.zero(0), c.zero(1)).sign, 1, `${w}: minMag(+0, -0) is -0: `);
    eq(c.maxMag(c.zero(0), c.zero(1)).sign, 0, `${w}: maxMag(+0, -0) is +0: `);
    eq(c.minnumMag(c.zero(1), c.zero(0)).sign, 1, `${w}: minnumMag zeros: `);
    eq(c.maxnumMag(c.zero(1), c.zero(0)).sign, 0, `${w}: maxnumMag zeros: `);
  }
});

test("a NaN has no magnitude, so every NaN case is the deferral", () => {
  for (const w of WIDTHS) {
    const c = ctxs[w];
    const q = c.nan(), three = c.from(3);
    c.clearFlags();
    ok(c.minMag(q, three).isNaN, `${w}: minMag(qNaN, 3) is a NaN`);
    ok(c.maxMag(three, q).isNaN, `${w}: maxMag(3, qNaN) is a NaN`);
    eq(c.lastFlags, 0, `${w}: a QUIET NaN raises nothing: `);
    ok(c.minnumMag(q, three).sameBits(three),
       `${w}: minnumMag(qNaN, 3) is the number`);
    ok(c.maxnumMag(q, three).sameBits(three),
       `${w}: maxnumMag(qNaN, 3) is the number`);
    ok(c.minnumMag(q, q).isNaN, `${w}: two NaNs give a NaN even here`);
    // a signaling NaN raises invalid in all four, and nothing else can
    // be raised at all
    const fi = c.format;
    const snan = c.fromBits((((1n << BigInt(fi.expW)) - 1n) <<
                             BigInt(fi.manW)) | 1n);
    for (const fn of ["minMag", "maxMag", "minnumMag", "maxnumMag"]) {
      c.clearFlags();
      const got = c[fn](snan, three);
      eq(c.lastFlags, FLAG_INVALID, `${w}: ${fn}(sNaN, 3) flags: `);
      if (fn.includes("num")) ok(got.sameBits(three), `${w}: ${fn} returns 3`);
      else ok(got.isNaN, `${w}: ${fn} returns a quiet NaN`);
    }
    c.clearFlags();
  }
});

test("the answer is an operand's own encoding, bit for bit", () => {
  // The result is always one of the two operand encodings except where
  // the base operation delivers a NaN - so a random sweep can check
  // that identity without knowing which operand it should be.
  const rand = mulberry32(0x9600);
  for (const w of WIDTHS) {
    const c = ctxs[w];
    const bits = interestingBits(c.format, rand);
    for (let i = 0; i < bits.length; i++) {
      const a = c.fromBits(bits[i]);
      const b = c.fromBits(bits[(i * 7 + 3) % bits.length]);
      for (const fn of ["minMag", "maxMag", "minnumMag", "maxnumMag"]) {
        const got = c[fn](a, b);
        ok(got.sameBits(a) || got.sameBits(b) || got.isNaN,
           `${w} ${fn}: the result is an operand or a NaN`);
      }
    }
  }
});

test("the magnitude four batch through map() exactly as they scalar", () => {
  const rand = mulberry32(0x9601);
  for (const w of WIDTHS) {
    const c = ctxs[w];
    const bits = interestingBits(c.format, rand);
    const xs = bits.map((b) => c.fromBits(b));
    const ys = bits.map((_, i) => c.fromBits(bits[(i * 5 + 1) % bits.length]));
    for (const [name, method] of Object.entries(MINMAG_METHOD)) {
      let union = 0;
      const scalar = xs.map((x, i) => {
        c.clearFlags();
        const r = c[method](x, ys[i]);
        union |= c.lastFlags;
        return r;
      });
      // by 754's spelling, which is what the vector sets carry ...
      c.clearFlags();
      const batch = c.map(name, xs, ys);
      batch.forEach((g, i) => ok(g.sameBits(scalar[i]),
        `${w} ${name}[${i}]: the array answer is the scalar answer`));
      eq(c.lastFlags, union, `${w} ${name}: the batch flag word is the union: `);
      // ... and by this package's method name, the same answer
      const alias = c.map(method, xs, ys);
      alias.forEach((g, i) => ok(g.sameBits(scalar[i]),
        `${w} ${method}[${i}]: reachable by either spelling`));
    }
    throws(() => c.map("minimumMagnitude", xs), "a second array is required");
    c.clearFlags();
  }
});

// ---------------------------------------------------------------------
// ABI 0.7, package A: clause 5.4.1's formatOf arithmetic
// ---------------------------------------------------------------------

const FO_BINARY = ["formatOfAdd", "formatOfSub", "formatOfMul", "formatOfDiv"];

test("a same-format formatOf call IS the operation that was already here", () => {
  // 5.4.1 asks for every ORDERED pair, the four same-format ones
  // included, and those must be the existing entry points bit for bit
  // - not a reimplementation that happens to agree.
  const rand = mulberry32(0x5410);
  for (const w of WIDTHS) {
    const base = ctxs[w];
    const name = base.format.name;
    for (const attr of ATTRS) {
      const c = base.withRounding(attr);
      const bits = interestingBits(c.format, rand);
      for (let i = 0; i < bits.length; i++) {
        const a = c.fromBits(bits[i]);
        const b = c.fromBits(bits[(i * 3 + 5) % bits.length]);
        const z = c.fromBits(bits[(i * 11 + 2) % bits.length]);
        const pairs = [
          [c.formatOfAdd(name, a, b), c.add(a, b)],
          [c.formatOfSub(name, a, b), c.sub(a, b)],
          [c.formatOfMul(name, a, b), c.mul(a, b)],
          [c.formatOfDiv(name, a, b), c.div(a, b)],
          [c.formatOfSqrt(name, a), c.sqrt(a)],
          [c.formatOfFma(name, a, b, z), c.fma(a, b, z)],
        ];
        for (const [got, want] of pairs)
          ok(got.sameBits(want),
             `${w} ${attr} case ${i}: formatOf agrees with the same-format ` +
             `operation (${got.bits.toString(16)} vs ${want.bits.toString(16)})`);
      }
    }
  }
});

test("widening is exact, so it is convert-then-operate and says so", () => {
  // The interchange ladder NESTS - every binary32 value is a binary64
  // value in significand bits and in exponent range both - so widening
  // rounds nothing and the operation's rounding is still the only one.
  const rand = mulberry32(0x5411);
  for (const sw of WIDTHS) {
    for (const dw of WIDTHS) {
      if (dw <= sw) continue;
      const src = ctxs[sw], dst = ctxs[dw];
      const dname = dst.format.name;
      const bits = interestingBits(src.format, rand);
      for (let i = 0; i < bits.length; i++) {
        const a = src.fromBits(bits[i]);
        const b = src.fromBits(bits[(i * 3 + 5) % bits.length]);
        src.clearFlags();
        const got = src.formatOfAdd(dname, a, b);
        const foFlags = src.lastFlags;
        dst.clearFlags();
        const want = dst.add(dst.convert(a), dst.convert(b));
        ok(got.sameBits(want),
           `${sw}->${dw} case ${i}: formatOfAdd is convert-then-add`);
        // the WORD rather than lastFlags, because the composition is
        // three calls and only their union is comparable with the one
        // call formatOf makes - a signaling NaN signals in the
        // conversion there and inside the operation here
        eq(foFlags, dst.flags,
           `${sw}->${dw} case ${i}: and raises what the widened add raises: `);
      }
      src.clearFlags();
      dst.clearFlags();
    }
  }
});

// The double-rounding witnesses, rebuilt here from the FORMAT
// DESCRIPTORS ALONE - the construction python/cft_golden/formatof.py's
// double_rounding_witness() derives, ported rather than tabulated, so
// nothing here is a number somebody typed.
//
// One idea for all three: put the exact result a hair ABOVE a midpoint
// of the DESTINATION grid, closer to it than half an ulp of the
// intermediate. The first rounding lands exactly ON the midpoint, the
// second sees a tie and breaks it to even DOWNWARD, and the single
// correct rounding goes UP because the exact value was above. The
// midpoint chosen is m = 1 + 2^-pd, whose destination neighbours are
// 1 (last bit 0, so the tie goes there) and nextUp(1).
function foWitness(sfi, dfi, fn) {
  const ps = BigInt(sfi.prec), pd = BigInt(dfi.prec);
  const M = (1n << pd) + 1n;                 // m's significand, pd+1 bits
  if (fn === "fma") {
    // a*b = m exactly with b = 1, and c the smallest positive source
    // value - below every plausible intermediate's half-ulp at
    // magnitude 1, which is why no width rescues this one.
    return {
      a: encodeExact(sfi, 0, M, -Number(pd)),
      b: encodeExact(sfi, 0, 1n << (ps - 1n), 1 - Number(ps)),
      c: 1n,
    };
  }
  if (fn === "div") {
    // Y with M*Y == -1 (mod 2^pd): the exact product m*y falls one
    // unit of the product's last place short of a source value, so the
    // source value just above it is the dividend and x/y sits that far
    // above m.
    const Y = (1n << (ps - 1n)) + ((1n << (ps - pd)) - 1n);
    if (Y % (1n << pd) !== (1n << pd) - 1n)
      throw new Error("the divisor construction lost its residue");
    return {
      a: encodeExact(sfi, 0, M * Y + 1n, 1 - Number(pd) - Number(ps)),
      b: encodeExact(sfi, 0, Y, 1 - Number(ps)),
      c: null,
    };
  }
  // squareRoot: m^2 needs 2*pd + 1 bits and the ladder gives it, so it
  // is a source value; the source value ONE ULP ABOVE it has a root a
  // quarter of an intermediate ulp above m.
  if (2n * pd + 1n > ps)
    throw new Error("no square-root witness: m^2 does not fit the source");
  return { a: encodeExact(sfi, 0, M * M, -2 * Number(pd)) + 1n,
           b: null, c: null };
}

test("NARROWING IS NOT A DOUBLE ROUNDING, and the witnesses show it", () => {
  // Both halves of every witness, which is the whole point: the
  // implementation agrees with the single correct rounding, AND the
  // composed route disagrees with it. A witness that stopped
  // separating the two would be checking that two identical things are
  // identical.
  let witnesses = 0;
  for (const sw of WIDTHS) {
    for (const dw of WIDTHS) {
      if (dw >= sw) continue;
      const src = ctxs[sw], dst = ctxs[dw];
      const sfi = src.format, dfi = dst.format;
      const dname = dfi.name;
      // The two destination values the witness sits between: 1.0,
      // whose last significand bit is 0 and which therefore wins a
      // ties-to-even tie, and nextUp(1), which is where the exact
      // value rounds when it is a hair above the midpoint.
      const one = BigInt(dfi.bias) << BigInt(dfi.manW);
      for (const fn of ["fma", "div", "sqrt"]) {
        const w = foWitness(sfi, dfi, fn);
        const a = src.fromBits(w.a);
        const b = w.b === null ? null : src.fromBits(w.b);
        const cc = w.c === null ? null : src.fromBits(w.c);

        src.clearFlags();
        const single = fn === "fma" ? src.formatOfFma(dname, a, b, cc)
          : (fn === "div" ? src.formatOfDiv(dname, a, b)
                          : src.formatOfSqrt(dname, a));
        const singleFlags = src.lastFlags;

        // the route this library refuses: round in the SOURCE format,
        // then convert down. Two roundings, both the library's own.
        src.clearFlags();
        const inSource = fn === "fma" ? src.fma(a, b, cc)
          : (fn === "div" ? src.div(a, b) : src.sqrt(a));
        dst.clearFlags();
        const composed = dst.convert(inSource);

        eq(single.bits, one + 1n,
           `${sw}->${dw} ${fn}: the single rounding is nextUp(1) `);
        eq(composed.bits, one,
           `${sw}->${dw} ${fn}: the composed route is 1.0 `);
        ok(!single.sameBits(composed),
           `${sw}->${dw} ${fn}: and the two DIFFER - by one ulp of the ` +
           `destination, the composed one low`);
        ok(singleFlags & FLAG_INEXACT,
           `${sw}->${dw} ${fn}: the single rounding is inexact`);
        eq(single.context.format, dfi,
           `${sw}->${dw} ${fn}: the result carries the destination's context: `);
        witnesses++;
      }
      src.clearFlags();
      dst.clearFlags();
    }
  }
  eq(witnesses, 18, "six narrowing pairs x three operations: ");
});

test("the destination's exceptions, on the destination's grid", () => {
  const f64 = ctxs[64], f32name = "fp32";
  // A HAIR ABOVE HALF binary32's least subnormal. 2^-150 is exactly
  // half of 2^-149, so a sum a hair above it in magnitude rounds AWAY
  // from zero under roundTiesToEven and lands on the least subnormal -
  // with the destination's underflow beside the inexact, neither of
  // which the source format had any reason to raise. This is the row
  // that caught the MPFR harness double rounding the destination's
  // subnormal grid (docs/VALIDATION.md, 2026-09-04).
  const a = f64.fromBits(0x8037478c91215daen);      // about -2^-968
  const b = f64.fromBits(0xb690000000000000n);      // exactly -2^-150
  f64.clearFlags();
  const got = f64.formatOfAdd(f32name, a, b);
  eq(got.bits, 0x80000001n, "fp64->fp32 add just past the midpoint: ");
  eq(f64.lastFlags, FLAG_UNDERFLOW | FLAG_INEXACT, "with the destination's flags: ");
  // and its negation, because a sign error here would be invisible
  f64.clearFlags();
  const gotP = f64.formatOfAdd(f32name, f64.fromBits(0x0037478c91215daen),
                               f64.fromBits(0x3690000000000000n));
  eq(gotP.bits, 0x00000001n, "the same row negated: ");
  eq(f64.lastFlags, FLAG_UNDERFLOW | FLAG_INEXACT, "same flags: ");

  // OVERFLOW is the destination's too: two unremarkable binary64
  // values whose product a binary32 cannot hold. 2^100 x 2^100 is
  // 2^200, far past binary32's 2^128.
  const p100 = f64.fromBits(0x4630000000000000n);   // 2^100
  f64.clearFlags();
  const over = f64.formatOfMul(f32name, p100, p100);
  ok(over.isInf && over.sign === 0, "2^100 x 2^100 overflows binary32");
  eq(f64.lastFlags, FLAG_OVERFLOW | FLAG_INEXACT, "overflow and inexact: ");
  // the same operands in binary64 raise nothing at all, which is the
  // point: the exceptions belong to the destination
  f64.clearFlags();
  const fine = f64.mul(p100, p100);
  eq(f64.lastFlags, 0, "while binary64 holds 2^200 exactly: ");
  ok(!fine.isInf, "and finitely");

  // A SIGNALING NaN raises invalid and delivers the DESTINATION's
  // canonical quiet NaN (6.2.1, and this contract's payload rule).
  const snan = f64.fromBits(0x7ff0000000000001n);
  f64.clearFlags();
  const q = f64.formatOfAdd(f32name, snan, f64.from(1));
  ok(q.sameBits(ctxs[32].nan()), "sNaN gives the destination's canonical qNaN");
  eq(f64.lastFlags, FLAG_INVALID, "with invalid: ");
  f64.clearFlags();
});

test("the destination is an argument, and the result knows it", () => {
  const f256 = ctxs[256];
  const got = f256.formatOfDiv("fp32", f256.from(1), f256.from(3));
  eq(got.context.format.ieeeName, "binary32", "the result's format: ");
  eq(got.bytes.length, 4, "and its width: ");
  // the same call written from the value rather than from the context
  const alt = f256.from(1).formatOfDiv("fp32", f256.from(3));
  ok(alt.sameBits(got), "Float.formatOfDiv is Context.formatOfDiv");
  // a destination can be named by width, precision or name, like every
  // other format in this package
  ok(f256.formatOfDiv(32, f256.from(1), f256.from(3)).sameBits(got),
     "the destination takes a width");
  ok(f256.formatOfDiv("binary32", f256.from(1), f256.from(3)).sameBits(got),
     "and 754's own name");
  throws(() => f256.formatOfDiv("binary16", f256.from(1), f256.from(3)),
         "a format this library does not implement");
  throws(() => f256.formatOfSqrt("fp32", f256.from(4), f256.from(1)),
         "squareRoot reads one operand");
  throws(() => f256.formatOfAdd("fp32", f256.from(1), f256.from(2),
                                f256.from(3)),
         "addition reads two, and a third is a mistake rather than a c");
  throws(() => f256.formatOfAdd("fp32", ctxs[64].from(1), f256.from(1)),
         "a binary64 operand in a binary256 source context");
  f256.clearFlags();
});

test("the formatOf six batch through mapFormatOf as they scalar", () => {
  const rand = mulberry32(0x5412);
  for (const sw of [64, 256]) {
    for (const dw of [32, 128]) {
      const src = ctxs[sw];
      const dname = formatFor(dw).name;
      const bits = interestingBits(src.format, rand);
      const xs = bits.map((b) => src.fromBits(b));
      const ys = bits.map((_, i) => src.fromBits(bits[(i * 3 + 1) % bits.length]));
      const zs = bits.map((_, i) => src.fromBits(bits[(i * 7 + 4) % bits.length]));
      for (const fn of ["add", "sub", "mul", "div", "sqrt", "fma"]) {
        const method = FORMATOF_METHOD[fn];
        let union = 0;
        const scalar = xs.map((x, i) => {
          src.clearFlags();
          const r = fn === "sqrt" ? src[method](dname, x)
            : (fn === "fma" ? src[method](dname, x, ys[i], zs[i])
                            : src[method](dname, x, ys[i]));
          union |= src.lastFlags;
          return r;
        });
        src.clearFlags();
        const batch = src.mapFormatOf(fn, dname, xs,
                                      fn === "sqrt" ? null : ys,
                                      fn === "fma" ? zs : null);
        batch.forEach((g, i) => ok(g.sameBits(scalar[i]),
          `${sw}->${dw} ${fn}[${i}]: the array answer is the scalar answer`));
        eq(src.lastFlags, union,
           `${sw}->${dw} ${fn}: the batch flag word is the union: `);
      }
      throws(() => src.mapFormatOf("sqrt", dname, xs, ys),
             "squareRoot takes no b array");
      throws(() => src.mapFormatOf("add", dname, xs),
             "addition needs a b array");
      throws(() => src.mapFormatOf("nope", dname, xs, ys),
             "an operation 5.4.1 does not name");
      src.clearFlags();
    }
  }
});

test("map() sends a formatOf name somewhere useful", () => {
  // "add", "sub", "mul" and "fma" are opcodes as well as formatOf
  // names, and a bare name in a one-format call is the opcode - that
  // reading has to keep working.
  const xs = [c64.from(1), c64.from(2)];
  const ys = [c64.from(3), c64.from(4)];
  const added = c64.map("add", xs, null, ys);
  eq(added[0].toNumber(), 4, "map(\"add\") is still the opcode: ");
  // "div" and "sqrt" are not opcodes at all, so they land in the
  // unknown-op path, and it names the entry point that can take them
  try {
    c64.map("div", xs, ys);
    throw new Error("map(\"div\") should refuse");
  } catch (err) {
    ok(/mapFormatOf/.test(err.message),
       `the refusal points at mapFormatOf (got: ${err.message})`);
  }
});

// ---------------------------------------------------------------------
// the negative control
// ---------------------------------------------------------------------

test("NEGATIVE CONTROL: the comparisons can fail", () => {
  const f = c64.from("1.5");
  const flipped = c64.fromBits(f.bits ^ 1n);
  ok(!f.sameBits(flipped), "sameBits must notice one bit");
  ok(flipped.toString() !== f.toString(), "and so must the decimal");
  let caught = false;
  try { eq(flipped.bits, f.bits, "deliberate: "); } catch { caught = true; }
  ok(caught, "eq() must throw on a difference");
  ok(bitsOfDouble(0.1) !== bitsOfDouble(0.1 + Number.EPSILON),
     "the V8 oracle distinguishes adjacent doubles");
});

// ---------------------------------------------------------------------

for (const w of WIDTHS) ctxs[w].close();
freshCtx.close();

console.log(`${passed} passed, ${failed} failed`);
for (const f of failures) console.log(`  FAIL  ${f}`);
process.exit(failed ? 1 : 0);
