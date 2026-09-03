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
// The twenty transcendental sets - which carry all twenty FUNCTIONS
// since ABI 0.4, phase 1's nine and phase 2's eleven - get a SECOND
// pass, driven from JavaScript through Context's exp/log/pow/hypot and
// sinpi/asin/atan2 rather than handed to cft_conformance. That is not
// redundancy: cft_conformance dispatches all twenty internally in C
// and would be green with no JavaScript surface for any of them at
// all - it was, for a day (docs/COMPATIBILITY.md's half-step). The
// library remains the only thing computing; what this pass adds is
// that the package's own methods reach it, in the right order - which
// for atan2 and atan2pi means y first - with the flags intact.
//
// A run that checked nothing must not read as a pass. Zero cases, a
// missing set, or a directory with no sets in it are failures here,
// exactly as they are inside cft_conformance.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Context } from "./core.mjs";
import { TRANSCEND_BINARY, TRANSCEND_UNARY, loadModule } from "./lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");

const FORMATS = ["fp32", "fp64", "fp128", "fp256"];
const ROUNDINGS = ["rne", "rtz", "rdn", "rup", "rmm"];
const CANONICAL = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    CANONICAL.push(r === "rne" ? `${f}.jsonl` : `${f}-${r}.jsonl`);

// The transcendental sets: their own files, their own schema ("fn"
// rather than "op", no c operand), because the twenty are library
// entry points rather than opcodes - vectors/gen_vectors.py says why.
const TRANSCEND_SETS = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    TRANSCEND_SETS.push({
      name: r === "rne" ? `${f}-transcend.jsonl`
                        : `${f}-transcend-${r}.jsonl`,
      format: f, rounding: r,
    });
const TRANSCEND_ARITY = new Map([
  ...TRANSCEND_UNARY.map((f) => [f, 1]),
  ...TRANSCEND_BINARY.map((f) => [f, 2]),
]);

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
const KNOWN = new Set([...CANONICAL, ...TRANSCEND_SETS.map((s) => s.name)]);
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

let total = 0, clean = 0, bad = 0;
const t0 = Date.now();
for (const name of CANONICAL) {
  const r = replay(name, readFileSync(join(vdir, name), "utf8"));
  total += r.cases;
  const n = r.cases.toLocaleString("en-US").padStart(7);
  if (r.status === 0 && r.cases > 0) {
    clean++;
    console.log(`  ${name.padEnd(16)} ${n}  all matching`);
  } else {
    bad++;
    console.log(`  ${name.padEnd(16)} ${n}  FAILED: ${C.strerror(r.status)}`);
    console.log(r.report.trim().split("\n").map((l) => "      " + l).join("\n"));
  }
}

const secs = ((Date.now() - t0) / 1000).toFixed(1);
console.log("");
if (bad === 0 && clean === CANONICAL.length && total > 0)
  console.log(`${total.toLocaleString("en-US")} cases over ${clean} sets, ` +
              `library matches the vectors exactly (${secs}s)`);
else
  console.log(`${clean} of ${CANONICAL.length} sets clean, ` +
              `${total.toLocaleString("en-US")} cases - NOT A PASS (${secs}s)`);

// ---------------------------------------------------------------------
// The nine, through this package's own methods
//
// One Context per (format, attribute) - the sets are organised the same
// way - and one call per case, so the flag word the file carries is
// compared against the flag word that one call raised. Then one map()
// per family, because a batch call that disagreed with the scalar one
// would be a bug the per-case pass cannot see.
//
// Everything is compared as ENCODINGS: Float.bits, never a decimal and
// never a JS number. A NaN payload and a signed zero both survive that
// and neither survives a `number`.
// ---------------------------------------------------------------------

function hexOf(f, fi) {
  return "0x" + f.bits.toString(16).padStart(fi.size * 2, "0");
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
      const arity = TRANSCEND_ARITY.get(rec.fn);
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
      if (!byFn.has(rec.fn)) byFn.set(rec.fn, []);
      byFn.get(rec.fn).push({
        lineno,
        a: c.fromBits(BigInt(rec.a)),
        b: arity === 2 ? c.fromBits(BigInt(rec.b)) : null,
        d: c.fromBits(BigInt(rec.d)),
        flags: rec.flags >>> 0,
      });
    }
    if (!byFn.size) throw new Error(`${set.name}: no cases`);

    let checked = 0;
    for (const [fn, cases] of byFn) {
      let union = 0;
      for (const k of cases) {
        c.clearFlags();
        const got = k.b ? c[fn](k.a, k.b) : c[fn](k.a);
        if (!got.sameBits(k.d) || c.lastFlags !== k.flags)
          throw new Error(
            `${set.name}:${k.lineno}: ${fn} ${set.rounding}\n` +
            `        a        ${hexOf(k.a, fi)}\n` +
            (k.b ? `        b        ${hexOf(k.b, fi)}\n` : "") +
            `        expected ${hexOf(k.d, fi)} flags 0x` +
            `${k.flags.toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOf(got, fi)} flags 0x` +
            `${c.lastFlags.toString(16).padStart(2, "0")}`);
        union |= c.lastFlags;
        checked++;
      }
      c.clearFlags();
      const batch = TRANSCEND_ARITY.get(fn) === 2
        ? c.map(fn, cases.map((k) => k.a), cases.map((k) => k.b))
        : c.map(fn, cases.map((k) => k.a));
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

const haveTranscend = TRANSCEND_SETS.every((s) =>
  existsSync(join(vdir, s.name)));
if (!haveTranscend) {
  console.log(`\nno transcendental sets in ${vdir} - the twenty were NOT ` +
              `driven. Run \`make vectors\` from the repo root; the ` +
              `containerized wasm build cannot write them (no mpmath in ` +
              `the pinned image).`);
  console.log("NOT A PASS: the ABI 0.4 surface was not exercised.");
  process.exit(1);
}

console.log("\nthe twenty, through Context (per case, then as arrays)\n");
let tTotal = 0, tClean = 0, tBad = 0;
const t1 = Date.now();
for (const set of TRANSCEND_SETS) {
  let n = 0, err = null;
  try { n = await driveTranscendSet(set, readFileSync(join(vdir, set.name),
                                                     "utf8")); }
  catch (e) { err = e; }
  tTotal += n;
  const shown = n.toLocaleString("en-US").padStart(7);
  if (!err) {
    tClean++;
    console.log(`  ${set.name.padEnd(26)} ${shown}  all matching`);
  } else {
    tBad++;
    console.log(`  ${set.name.padEnd(26)} ${shown}  FAILED`);
    console.log(`      ${err.message}`);
  }
}
const tSecs = ((Date.now() - t1) / 1000).toFixed(1);

console.log("");
const allClean = bad === 0 && clean === CANONICAL.length && total > 0 &&
                 tBad === 0 && tClean === TRANSCEND_SETS.length && tTotal > 0;
if (allClean) {
  console.log(`${tTotal.toLocaleString("en-US")} transcendental cases over ` +
              `${tClean} sets, through this package's own methods, ` +
              `encodings and flags exact (${tSecs}s)`);
  console.log(`\n${(total + tTotal).toLocaleString("en-US")} cases over ` +
              `${clean + tClean} sets in all - a pass.`);
  process.exit(0);
}
console.log(`${tClean} of ${TRANSCEND_SETS.length} transcendental sets ` +
            `clean, ${tTotal.toLocaleString("en-US")} cases - NOT A PASS ` +
            `(${tSecs}s)`);
process.exit(1);
