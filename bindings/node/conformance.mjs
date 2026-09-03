// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
//     node bindings/node/conformance.mjs [vectors-dir]
//
// The package's conformance test: replay the published vector sets
// through THIS module, with `make vectors` output from the repo root
// (or a directory named on the command line).
//
// It is the same call the browser page makes - cft_conformance() over
// files in MEMFS - because the point of a conformance test is that it
// is not a restatement of the thing being tested. The library parses
// the sets, drives every case per element for exact flags and then as
// arrays, compares, and its report IS the failure detail; this script
// writes files and prints what came back.
//
// EVERY SET FAMILY THAT IS NOT AN OPCODE then gets a SECOND pass,
// driven from JavaScript through this package's own Context methods
// rather than handed to cft_conformance. Since ABI 0.6 that is four
// families: the transcendental sets (all thirty-nine functions, table
// 9.1 complete), the augmented sets of clause 9.5, the reduction sets
// of 9.4 - sum, dot, sumsq, sumabs and the three scaled products - and
// the character sets of 5.12 with 9.7's payload operations. That is
// not redundancy: cft_conformance dispatches all of it internally in C
// and would be green with no JavaScript surface for any of it at all -
// it was, for a day (docs/COMPATIBILITY.md's half-step). The library
// remains the only thing computing; what this pass adds is that the
// package's own methods reach it, in the right order - which for atan2
// and atan2pi means y first, and for scaledProdDiff means a minus b -
// with the flags, the sequences and the scales intact.
//
// A run that checked nothing must not read as a pass. Zero cases, a
// missing set, or a directory with no sets in it are failures here,
// exactly as they are inside cft_conformance.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Context } from "./core.mjs";
import { AUGMENTED, TRANSCEND_BINARY, TRANSCEND_INTARG, TRANSCEND_UNARY,
         loadModule } from "./lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");

const FORMATS = ["fp32", "fp64", "fp128", "fp256"];
const ROUNDINGS = ["rne", "rtz", "rdn", "rup", "rmm"];
const CANONICAL = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    CANONICAL.push(r === "rne" ? `${f}.jsonl` : `${f}-${r}.jsonl`);

const perFmtRnd = (stem) => {
  const out = [];
  for (const f of FORMATS)
    for (const r of ROUNDINGS)
      out.push({
        name: r === "rne" ? `${f}-${stem}.jsonl` : `${f}-${stem}-${r}.jsonl`,
        format: f, rounding: r,
      });
  return out;
};

// The transcendental sets: their own files, their own schema ("fn"
// rather than "op", no c operand), because the thirty-nine are library
// entry points rather than opcodes - vectors/gen_vectors.py says why.
const TRANSCEND_SETS = perFmtRnd("transcend");
// Three arities: unary, two encodings, and one encoding beside an
// int64. The third is not a flag on the second, because its second
// operand is not a float at all (754-2019 9.2.1).
const TRANSCEND_ARITY = new Map([
  ...TRANSCEND_UNARY.map((f) => [f, 1]),
  ...TRANSCEND_BINARY.map((f) => [f, 2]),
]);
const TRANSCEND_INT = new Set(TRANSCEND_INTARG);

// The augmented sets: ONE file per format, not one per attribute, and
// the absence of a "rnd" field in them is normative - 9.5 fixes the
// rounding to roundTiesTowardZero, which is not one of clause 4.3's
// five. Two outputs per case.
const AUGMENTED_SETS = FORMATS.map((f) => ({
  name: `${f}-augmented.jsonl`, format: f,
}));
const AUG_METHOD = { augmentedAddition: "augmentedAdd",
                     augmentedSubtraction: "augmentedSub",
                     augmentedMultiplication: "augmentedMul" };

// The reduction sets: a case is a whole VECTOR and one answer - two
// for the three scaled products, which return a pair.
const REDUCE_SETS = perFmtRnd("reduce");
const REDUCE_PLAIN = new Set(["sum", "dot", "sumsq", "sumabs"]);
const SCALED_METHOD = { scaled_prod: "scaledProd",
                        scaled_prod_sum: "scaledProdSum",
                        scaled_prod_diff: "scaledProdDiff" };
const REDUCE_BINARY = new Set(["dot", "scaled_prod_sum", "scaled_prod_diff"]);

// The character sets: a case names a SEQUENCE rather than an encoding,
// and some cases assert a REFUSAL.
const CHARACTER_SETS = perFmtRnd("character");
const CHAR_FROM = { from_decimal: "fromDecimal", from_hex: "fromHex" };
const CHAR_TO = { to_decimal: "toDecimal", to_hex: "toHex" };
const CHAR_PAYLOAD = { get_payload: "getPayload", set_payload: "setPayload",
                       set_payload_signaling: "setPayloadSignaling" };

const candidates = [process.argv[2], join(ROOT, "vectors", "out"),
                    join(ROOT, "bindings", "wasm", "build", "vectors")]
  .filter(Boolean);
const vdir = candidates.find((d) => existsSync(d) &&
  CANONICAL.every((n) => existsSync(join(d, n))));
if (!vdir) {
  console.error(`no complete vector directory in: ${candidates.join(", ")}`);
  console.error("Run `make vectors` from the repo root, or name a directory.");
  process.exit(2);
}

const { M, C } = await loadModule();

const pp = M._malloc(4);
const st = C.openSoftware(pp);
const dev = M.HEAPU32[pp >> 2];
M._free(pp);
if (st !== 0 || !dev) {
  console.error(`cft_open(software): ${C.strerror(st)}`);
  process.exit(1);
}

const abi = C.abiVersion() >>> 0;
console.log(`libcft ABI ${abi >>> 16}.${abi & 0xffff}, backend ` +
            `${C.capsBackend(dev)}, wasm32`);
console.log(`vectors    ${vdir}`);
const DRIVEN = [
  { label: "the thirty-nine transcendentals (table 9.1, complete)",
    unit: "transcendental", sets: TRANSCEND_SETS, drive: driveTranscendSet },
  { label: "the augmented arithmetic (clause 9.5)", unit: "augmented",
    sets: AUGMENTED_SETS, drive: driveAugmentedSet },
  { label: "the reductions and scaled products (clause 9.4)",
    unit: "reduction", sets: REDUCE_SETS, drive: driveReduceSet },
  { label: "the character conversions (5.12) and payloads (9.7)",
    unit: "character", sets: CHARACTER_SETS, drive: driveCharacterSet },
];
const KNOWN = new Set([...CANONICAL,
                       ...DRIVEN.flatMap((f) => f.sets.map((s) => s.name))]);
const stray = readdirSync(vdir).filter((n) => n.endsWith(".jsonl") &&
  !KNOWN.has(n));
if (stray.length) console.log(`           (ignoring ${stray.join(", ")})`);
console.log("");

let seq = 0;
function replay(name, text) {
  const dir = `/replay${seq++}`;
  M.FS.mkdir(dir);
  M.FS.writeFile(`${dir}/${name}`, text);
  const repSize = 65536;
  const rep = M._malloc(repSize);
  const cases64 = M._malloc(8);
  try {
    const status = C.conformance(dev, dir, rep, repSize, cases64, cases64 + 4);
    return {
      status,
      report: M.UTF8ToString(rep),
      cases: M.HEAPU32[cases64 >> 2] +
             M.HEAPU32[(cases64 + 4) >> 2] * 4294967296,
    };
  } finally {
    M._free(rep);
    M._free(cases64);
    try { M.FS.unlink(`${dir}/${name}`); } catch { /* keep the real error */ }
    try { M.FS.rmdir(dir); } catch { /* ditto */ }
  }
}

// Every family, through cft_conformance itself: the opcode sets plus
// the four that also get a JavaScript pass below. The library's own
// replay is the first word on all of them.
const ALL_SETS = [...CANONICAL,
                  ...DRIVEN.flatMap((f) => f.sets.map((s) => s.name))]
  .filter((n) => existsSync(join(vdir, n)));

let total = 0, clean = 0, bad = 0;
const t0 = Date.now();
for (const name of ALL_SETS) {
  const r = replay(name, readFileSync(join(vdir, name), "utf8"));
  total += r.cases;
  const n = r.cases.toLocaleString("en-US").padStart(7);
  if (r.status === 0 && r.cases > 0) {
    clean++;
    console.log(`  ${name.padEnd(26)} ${n}  all matching`);
  } else {
    bad++;
    console.log(`  ${name.padEnd(26)} ${n}  FAILED: ${C.strerror(r.status)}`);
    console.log(r.report.trim().split("\n").map((l) => "      " + l).join("\n"));
  }
}

const secs = ((Date.now() - t0) / 1000).toFixed(1);
console.log("");
if (bad === 0 && clean === ALL_SETS.length && total > 0)
  console.log(`${total.toLocaleString("en-US")} cases over ${clean} sets, ` +
              `library matches the vectors exactly (${secs}s)`);
else
  console.log(`${clean} of ${ALL_SETS.length} sets clean, ` +
              `${total.toLocaleString("en-US")} cases - NOT A PASS (${secs}s)`);

// ---------------------------------------------------------------------
// The four families, through this package's own methods
//
// One Context per (format, attribute) - the sets are organised the same
// way - and one call per case, so the flag word the file carries is
// compared against the flag word that one call raised. Then one map()
// or batch call per family, because a batch call that disagreed with
// the scalar one would be a bug the per-case pass cannot see.
//
// Everything is compared as ENCODINGS: Float.bits, never a decimal and
// never a JS number. A NaN payload and a signed zero both survive that
// and neither survives a `number`. The character sets are the one
// exception, and only because a sequence IS the answer there.
// ---------------------------------------------------------------------

function hexOf(f, fi) {
  return "0x" + f.bits.toString(16).padStart(fi.size * 2, "0");
}

/** An INT64 field, read out of the raw line as a BigInt.
 *
 *  Not JSON.parse's answer, and the difference is not pedantry. A JSON
 *  number becomes a JS number, which is a binary64: the published sets
 *  carry pown's exponent at both int64 extremes, and JSON.parse turns
 *  9223372036854775807 into 9223372036854775808 - one past INT64_MAX,
 *  a different exponent, and a wrong answer that would look like a
 *  library bug. host/src/conformance.c reads these with field_i64()
 *  for the same reason; this is that function. */
function fieldI64(line, key) {
  const m = new RegExp(`"${key}"\\s*:\\s*(-?\\d+)`).exec(line);
  if (!m) return null;
  const v = BigInt(m[1]);
  if (v < -(2n ** 63n) || v >= 2n ** 63n)
    throw new Error(`"${key}": ${m[1]} is not an int64`);
  return v;
}

async function driveTranscendSet(set, text) {
  const ctx = await Context.open(set.format);
  try {
    const c = ctx.withRounding(set.rounding);
    const fi = c.format;
    const byFn = new Map();
    let lineno = 0;
    for (const line of text.split("\n")) {
      lineno++;
      if (!line.trim()) continue;
      const rec = JSON.parse(line);
      const intarg = TRANSCEND_INT.has(rec.fn);
      const arity = intarg ? 1 : TRANSCEND_ARITY.get(rec.fn);
      if (arity === undefined)
        throw new Error(`${set.name}:${lineno}: unknown function ` +
                        `"${rec.fn}" - this package's table and cft.h ` +
                        `have diverged`);
      if (rec.rnd !== set.rounding)
        throw new Error(`${set.name}:${lineno}: attribute "${rec.rnd}" in ` +
                        `a ${set.rounding} set`);
      if ((arity === 2) !== (rec.b !== undefined))
        throw new Error(`${set.name}:${lineno}: ${rec.fn} is ` +
                        `${arity === 2 ? "binary" : "unary"} but the case ` +
                        `${rec.b !== undefined ? "carries" : "omits"} b`);
      // "n" is a signed decimal, not an encoding, and a missing one is
      // a refusal rather than a default of zero: pown(x, 0) is 1 for
      // every x, so reading a missing field as 0 would be a plausible
      // wrong answer instead of a loud one.
      const nn = fieldI64(line, "n");
      if (intarg !== (nn !== null))
        throw new Error(`${set.name}:${lineno}: ${rec.fn} ` +
                        `${intarg ? "takes" : "does not take"} an integer ` +
                        `exponent but the case ` +
                        `${nn !== null ? "carries" : "omits"} "n"`);
      if (!byFn.has(rec.fn)) byFn.set(rec.fn, []);
      byFn.get(rec.fn).push({
        lineno,
        a: c.fromBits(BigInt(rec.a)),
        b: arity === 2 ? c.fromBits(BigInt(rec.b)) : null,
        n: nn,
        d: c.fromBits(BigInt(rec.d)),
        flags: rec.flags >>> 0,
      });
    }
    if (!byFn.size) throw new Error(`${set.name}: no cases`);

    let checked = 0;
    for (const [fn, cases] of byFn) {
      const intarg = TRANSCEND_INT.has(fn);
      let union = 0;
      for (const k of cases) {
        c.clearFlags();
        const got = intarg ? c[fn](k.a, k.n)
                           : (k.b ? c[fn](k.a, k.b) : c[fn](k.a));
        if (!got.sameBits(k.d) || c.lastFlags !== k.flags)
          throw new Error(
            `${set.name}:${k.lineno}: ${fn} ${set.rounding}\n` +
            `        a        ${hexOf(k.a, fi)}\n` +
            (k.b ? `        b        ${hexOf(k.b, fi)}\n` : "") +
            (k.n !== null ? `        n        ${k.n}\n` : "") +
            `        expected ${hexOf(k.d, fi)} flags 0x` +
            `${k.flags.toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOf(got, fi)} flags 0x` +
            `${c.lastFlags.toString(16).padStart(2, "0")}`);
        union |= c.lastFlags;
        checked++;
      }
      c.clearFlags();
      const batch = intarg
        ? c.map(fn, cases.map((k) => k.a), cases.map((k) => k.n))
        : (TRANSCEND_ARITY.get(fn) === 2
           ? c.map(fn, cases.map((k) => k.a), cases.map((k) => k.b))
           : c.map(fn, cases.map((k) => k.a)));
      cases.forEach((k, i) => {
        if (!batch[i].sameBits(k.d))
          throw new Error(`${set.name}:${k.lineno}: ${fn} over ` +
                          `${cases.length} elements gives ` +
                          `${hexOf(batch[i], fi)} where one element at a ` +
                          `time gives ${hexOf(k.d, fi)}`);
      });
      if (c.lastFlags !== union)
        throw new Error(`${set.name}: ${fn} over ${cases.length} elements ` +
                        `raised 0x${c.lastFlags.toString(16)}, the union ` +
                        `over the scalar calls is 0x${union.toString(16)}`);
    }
    return checked;
  } finally {
    ctx.close();
  }
}

async function driveAugmentedSet(set, text) {
  const ctx = await Context.open(set.format);
  try {
    const fi = ctx.format;
    const byFn = new Map();
    let lineno = 0;
    for (const line of text.split("\n")) {
      lineno++;
      if (!line.trim()) continue;
      const rec = JSON.parse(line);
      if (!AUGMENTED.includes(rec.fn))
        throw new Error(`${set.name}:${lineno}: unknown augmented ` +
                        `operation "${rec.fn}"`);
      // The absence of "rnd" is normative, so a set that carried one
      // would be recording a choice 9.5 does not offer.
      if (rec.rnd !== undefined)
        throw new Error(`${set.name}:${lineno}: an augmented case carries ` +
                        `"rnd": ${JSON.stringify(rec.rnd)}; 9.5 fixes the ` +
                        `rounding to roundTiesTowardZero, which is not one ` +
                        `of clause 4.3's five attributes`);
      if (!byFn.has(rec.fn)) byFn.set(rec.fn, []);
      byFn.get(rec.fn).push({
        lineno,
        a: ctx.fromBits(BigInt(rec.a)), b: ctx.fromBits(BigInt(rec.b)),
        r: ctx.fromBits(BigInt(rec.r)), e: ctx.fromBits(BigInt(rec.e)),
        flags: rec.flags >>> 0,
      });
    }
    if (!byFn.size) throw new Error(`${set.name}: no cases`);

    let checked = 0;
    for (const [fn, cases] of byFn) {
      const method = AUG_METHOD[fn];
      let union = 0;
      for (const k of cases) {
        ctx.clearFlags();
        const got = ctx[method](k.a, k.b);
        if (!got.r.sameBits(k.r) || !got.e.sameBits(k.e) ||
            ctx.lastFlags !== k.flags)
          throw new Error(
            `${set.name}:${k.lineno}: ${fn}\n` +
            `        a        ${hexOf(k.a, fi)}\n` +
            `        b        ${hexOf(k.b, fi)}\n` +
            `        expected r ${hexOf(k.r, fi)} e ${hexOf(k.e, fi)} ` +
            `flags 0x${k.flags.toString(16).padStart(2, "0")}\n` +
            `        got      r ${hexOf(got.r, fi)} e ${hexOf(got.e, fi)} ` +
            `flags 0x${ctx.lastFlags.toString(16).padStart(2, "0")}`);
        union |= ctx.lastFlags;
        checked++;
      }
      ctx.clearFlags();
      const batch = ctx.map(fn, cases.map((k) => k.a), cases.map((k) => k.b));
      cases.forEach((k, i) => {
        if (!batch.r[i].sameBits(k.r) || !batch.e[i].sameBits(k.e))
          throw new Error(`${set.name}:${k.lineno}: ${fn} over ` +
                          `${cases.length} elements gives ` +
                          `(${hexOf(batch.r[i], fi)}, ` +
                          `${hexOf(batch.e[i], fi)}) where one element at a ` +
                          `time gives (${hexOf(k.r, fi)}, ` +
                          `${hexOf(k.e, fi)})`);
      });
      if (ctx.lastFlags !== union)
        throw new Error(`${set.name}: ${fn} over ${cases.length} elements ` +
                        `raised 0x${ctx.lastFlags.toString(16)}, the union ` +
                        `over the scalar calls is 0x${union.toString(16)}`);
    }
    return checked;
  } finally {
    ctx.close();
  }
}

async function driveReduceSet(set, text) {
  const ctx = await Context.open(set.format);
  try {
    const c = ctx.withRounding(set.rounding);
    const fi = c.format;
    let lineno = 0, checked = 0;
    for (const line of text.split("\n")) {
      lineno++;
      if (!line.trim()) continue;
      const rec = JSON.parse(line);
      if (rec.rnd !== set.rounding)
        throw new Error(`${set.name}:${lineno}: attribute "${rec.rnd}" in ` +
                        `a ${set.rounding} set`);
      const scaled = SCALED_METHOD[rec.fn];
      if (!scaled && !REDUCE_PLAIN.has(rec.fn))
        throw new Error(`${set.name}:${lineno}: unknown reduction ` +
                        `"${rec.fn}"`);
      const binary = REDUCE_BINARY.has(rec.fn);
      if (!Array.isArray(rec.a) || rec.a.length !== rec.n)
        throw new Error(`${set.name}:${lineno}: "a" is not ${rec.n} elements`);
      if (binary && (!Array.isArray(rec.b) || rec.b.length !== rec.n))
        throw new Error(`${set.name}:${lineno}: ${rec.fn} needs a "b" of ` +
                        `${rec.n} elements`);
      const xs = rec.a.map((h) => c.fromBits(BigInt(h)));
      const ys = binary ? rec.b.map((h) => c.fromBits(BigInt(h))) : null;
      const flags = rec.flags >>> 0;

      c.clearFlags();
      if (scaled) {
        // The scale is an int64, so it is read out of the line rather
        // than through JSON.parse's double - the same rule pown's
        // exponent gets.
        const wantSf = fieldI64(line, "sf");
        if (wantSf === null)
          throw new Error(`${set.name}:${lineno}: a scaled product's case ` +
                          `needs both "pr" and "sf" - it returns a pair`);
        const wantPr = c.fromBits(BigInt(rec.pr));
        const got = binary ? c[scaled](xs, ys) : c[scaled](xs);
        if (typeof got.sf !== "bigint")
          throw new Error(`${set.name}:${lineno}: the scale came back a ` +
                          `${typeof got.sf}; it is an int64 in the contract`);
        if (!got.pr.sameBits(wantPr) || got.sf !== wantSf ||
            c.lastFlags !== flags)
          throw new Error(
            `${set.name}:${lineno}: ${rec.fn} ${set.rounding} over ` +
            `${rec.n} elements\n` +
            `        expected ${hexOf(wantPr, fi)} scale ${wantSf} flags 0x` +
            `${flags.toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOf(got.pr, fi)} scale ${got.sf} flags 0x` +
            `${c.lastFlags.toString(16).padStart(2, "0")}`);
      } else {
        const wantD = c.fromBits(BigInt(rec.d));
        const got = binary ? c.reduce(rec.fn, xs, ys) : c.reduce(rec.fn, xs);
        if (!got.sameBits(wantD) || c.lastFlags !== flags)
          throw new Error(
            `${set.name}:${lineno}: ${rec.fn} ${set.rounding} over ` +
            `${rec.n} elements\n` +
            `        expected ${hexOf(wantD, fi)} flags 0x` +
            `${flags.toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOf(got, fi)} flags 0x` +
            `${c.lastFlags.toString(16).padStart(2, "0")}`);
      }
      checked++;
    }
    if (!checked) throw new Error(`${set.name}: no cases`);
    return checked;
  } finally {
    ctx.close();
  }
}

async function driveCharacterSet(set, text) {
  const ctx = await Context.open(set.format);
  try {
    const c = ctx.withRounding(set.rounding);
    const fi = c.format;
    const batch = { from_decimal: [], from_hex: [] };
    let lineno = 0, checked = 0;
    for (const line of text.split("\n")) {
      lineno++;
      if (!line.trim()) continue;
      const rec = JSON.parse(line);
      if (rec.rnd !== set.rounding)
        throw new Error(`${set.name}:${lineno}: attribute "${rec.rnd}" in ` +
                        `a ${set.rounding} set`);
      const refuse = rec.refuse !== undefined;

      if (CHAR_FROM[rec.fn]) {
        const method = CHAR_FROM[rec.fn];
        c.clearFlags();
        if (refuse) {
          // The contract's refusal: a sequence outside 5.12's syntax
          // must be rejected rather than guessed at, and that is as
          // much a part of the contract as any value.
          let accepted = false;
          try { c[method](rec.s); accepted = true; } catch { /* expected */ }
          if (accepted)
            throw new Error(`${set.name}:${lineno}: ${method} ACCEPTED a ` +
                            `sequence that is not in the syntax: ` +
                            `${JSON.stringify(rec.s)}`);
          checked++;
          continue;
        }
        const want = c.fromBits(BigInt(rec.d));
        const got = c[method](rec.s);
        if (!got.sameBits(want) || c.lastFlags !== (rec.flags >>> 0))
          throw new Error(
            `${set.name}:${lineno}: ${rec.fn} ${set.rounding}\n` +
            `        s        ${JSON.stringify(rec.s.slice(0, 200))}\n` +
            `        expected ${hexOf(want, fi)} flags 0x` +
            `${(rec.flags >>> 0).toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOf(got, fi)} flags 0x` +
            `${c.lastFlags.toString(16).padStart(2, "0")}`);
        batch[rec.fn].push({ lineno, s: rec.s, d: want,
                             flags: rec.flags >>> 0 });
        checked++;
        continue;
      }

      const a = c.fromBits(BigInt(rec.a));
      if (CHAR_TO[rec.fn]) {
        c.clearFlags();
        const got = rec.fn === "to_decimal"
          ? c.toDecimal(a, { digits: rec.digits >>> 0 })
          : c.toHex(a);
        if (got !== rec.s || c.lastFlags !== (rec.flags >>> 0))
          throw new Error(
            `${set.name}:${lineno}: ${rec.fn} ${set.rounding} ` +
            `a=${hexOf(a, fi)}` +
            (rec.fn === "to_decimal" ? ` digits=${rec.digits}` : "") + `\n` +
            `        expected ${JSON.stringify(rec.s.slice(0, 200))} ` +
            `flags 0x${(rec.flags >>> 0).toString(16).padStart(2, "0")}\n` +
            `        got      ${JSON.stringify(got.slice(0, 200))} ` +
            `flags 0x${c.lastFlags.toString(16).padStart(2, "0")}`);
        // and the sizing protocol underneath it, on the same value: a
        // buffer one byte short must refuse with the length still set
        // and nothing written.
        if (rec.fn === "to_decimal") {
          const bytes = Buffer.byteLength(rec.s, "utf8") + 1;
          const ask = c.toDecimalInto(a, 0, { digits: rec.digits >>> 0 });
          if (ask.status === 0 || ask.len !== bytes)
            throw new Error(`${set.name}:${lineno}: the sizing call gave ` +
                            `status ${ask.status} len ${ask.len}, where the ` +
                            `sequence needs ${bytes} bytes and cft.h says ` +
                            `a NULL buffer refuses`);
          const short = c.toDecimalInto(a, bytes - 1,
                                        { digits: rec.digits >>> 0 });
          if (short.status === 0 || short.text !== null || short.len !== bytes)
            throw new Error(`${set.name}:${lineno}: a buffer of ${bytes - 1} ` +
                            `bytes was not refused cleanly (status ` +
                            `${short.status}, len ${short.len})`);
        }
        checked++;
        continue;
      }

      const method = CHAR_PAYLOAD[rec.fn];
      if (!method)
        throw new Error(`${set.name}:${lineno}: unknown character or ` +
                        `payload operation "${rec.fn}"`);
      const want = c.fromBits(BigInt(rec.d));
      const got = c[method](a);
      if (!got.sameBits(want))
        throw new Error(
          `${set.name}:${lineno}: ${rec.fn}\n` +
          `        a        ${hexOf(a, fi)}\n` +
          `        expected ${hexOf(want, fi)}\n` +
          `        got      ${hexOf(got, fi)}`);
      checked++;
    }
    if (!checked) throw new Error(`${set.name}: no cases`);

    // The array pass over the from_ conversions - the batch-shaped half
    // of this API. The refused sequences are deliberately not in the
    // pool: one of them refuses the whole call, which is the contract
    // and gets its own check above.
    for (const [fn, method] of [["from_decimal", "mapFromDecimal"],
                                ["from_hex", "mapFromHex"]]) {
      const cases = batch[fn];
      if (!cases.length) continue;
      c.clearFlags();
      const got = c[method](cases.map((k) => k.s));
      let want = 0;
      cases.forEach((k, i) => {
        want |= k.flags;
        if (!got[i].sameBits(k.d))
          throw new Error(`${set.name}:${k.lineno}: ${fn} over ` +
                          `${cases.length} sequences gives ` +
                          `${hexOf(got[i], fi)} where one at a time gives ` +
                          `${hexOf(k.d, fi)}`);
      });
      if (c.lastFlags !== want)
        throw new Error(`${set.name}: ${fn} over ${cases.length} sequences ` +
                        `raised 0x${c.lastFlags.toString(16)}, the OR over ` +
                        `the cases is 0x${want.toString(16)}`);
    }
    return checked;
  } finally {
    ctx.close();
  }
}

const missing = DRIVEN.filter((f) =>
  !f.sets.every((s) => existsSync(join(vdir, s.name))));
if (missing.length) {
  console.log(`\nsets missing from ${vdir}: ` +
              `${missing.map((f) => f.unit).join(", ")} - those methods were ` +
              `NOT driven. Run \`make vectors\` from the repo root; the ` +
              `containerized wasm build cannot write them (no mpmath in ` +
              `the pinned image).`);
  console.log("NOT A PASS: the ABI 0.6 surface was not exercised.");
  process.exit(1);
}

console.log("\nthrough Context's own methods (per case, then as arrays)");
let tTotal = 0, tClean = 0, tSets = 0;
const perFamily = [];
const t1 = Date.now();
for (const family of DRIVEN) {
  console.log(`\n  ${family.label}`);
  let fTotal = 0, fClean = 0;
  for (const set of family.sets) {
    let n = 0, err = null;
    try {
      n = await family.drive(set, readFileSync(join(vdir, set.name), "utf8"));
    } catch (e) { err = e; }
    fTotal += n;
    const shown = n.toLocaleString("en-US").padStart(7);
    if (!err) {
      fClean++;
      console.log(`    ${set.name.padEnd(26)} ${shown}  all matching`);
    } else {
      console.log(`    ${set.name.padEnd(26)} ${shown}  FAILED`);
      console.log(`        ${err.message}`);
    }
  }
  tTotal += fTotal;
  tClean += fClean;
  tSets += family.sets.length;
  perFamily.push({ unit: family.unit, cases: fTotal, clean: fClean,
                   sets: family.sets.length });
}
const tSecs = ((Date.now() - t1) / 1000).toFixed(1);

console.log("");
for (const f of perFamily)
  console.log(`  ${f.unit.padEnd(16)} ${f.cases.toLocaleString("en-US")
    .padStart(9)} cases over ${f.clean}/${f.sets} sets`);
console.log("");
const allClean = bad === 0 && clean === ALL_SETS.length && total > 0 &&
                 tClean === tSets && tTotal > 0 &&
                 perFamily.every((f) => f.cases > 0);
if (allClean) {
  console.log(`${tTotal.toLocaleString("en-US")} cases over ${tClean} sets, ` +
              `through this package's own methods, encodings, sequences, ` +
              `scales and flags exact (${tSecs}s)`);
  console.log(`\n${(total + tTotal).toLocaleString("en-US")} cases over ` +
              `${clean + tClean} set replays in all - a pass.`);
  process.exit(0);
}
console.log(`${tClean} of ${tSets} sets clean through this package's own ` +
            `methods, ${tTotal.toLocaleString("en-US")} cases - NOT A PASS ` +
            `(${tSecs}s)`);
process.exit(1);
