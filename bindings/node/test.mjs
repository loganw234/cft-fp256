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

import { Context, formatFor } from "./index.mjs";
import { FLAG_INEXACT, FLAG_INVALID, FLAG_DIVBYZERO, FLAG_OVERFLOW }
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

test("the module is ABI 0.3 on the software backend", () => {
  eq(c64.abiVersion, "0.3", "abi: ");
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

console.log(`${passed} passed, ${failed} failed`);
for (const f of failures) console.log(`  FAIL  ${f}`);
process.exit(failed ? 1 : 0);
