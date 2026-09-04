// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// Check the committed conformance.html without a browser.
//
//     node bindings/wasm/verify.mjs [vectors-dir]
//
// A browser is where the page is USED, and a person watching one is
// how it was signed off before. Neither is a test you can re-run
// after a rebuild, and the page is a committed build product: the
// thing most likely to go quietly stale (it did - the module shipped
// on 2026-09-01 answered ABI 0.1 for a day, see the README). This
// script is the re-runnable half.
//
// It checks five things, in the order that makes the last two mean
// something:
//
//   1  THE PAGE'S OWN MODULE, extracted from the HTML. Emscripten's
//      -sSINGLE_FILE embeds the wasm as a JS string literal, so the
//      bytes are pulled straight back out of the committed file - no
//      rebuild, no trust in the build directory.
//   2  Its identity: instantiate those bytes with stub imports and
//      call cftw_abi_version(). This is the check the page's top line
//      renders, asked of the file in git.
//   3  That the node loader's module is the SAME MODULE, by sha256.
//      -sENVIRONMENT changes the loader, not the wasm, and that is a
//      claim worth measuring rather than repeating: without it a
//      replay under node would be a replay of a lookalike.
//   4  The replay itself, through the page's own bytes: the node
//      loader is handed the extracted module as Module.wasmBinary, so
//      cft_conformance() runs on the literal contents of
//      conformance.html over MEMFS - the same call the page makes,
//      the same per-element then whole-array passes, over the full
//      published sets rather than the embedded sample. One set per
//      directory, which is what the page's drop zone does, so this is
//      that path and not a tidier one: since ABI 0.3 the drop zone
//      accepts the twenty transcendental sets as well, since 0.6 the
//      augmented, reduction and character ones, and since 0.7 the four
//      magnitude sets of 9.6 and the eighty formatOf sets of 5.4.1 -
//      168 names - and they are replayed here for the same reason.
//   5  EVERY OPERATION THAT IS NOT AN OPCODE, driven THROUGH ITS OWN
//      WRAPPER from JavaScript: the thirty-nine transcendentals, the
//      three augmented operations of clause 9.5, clause 9.4's four
//      sum reductions and three scaled products, clause 5.12's
//      character conversions with 9.7's payload operations, and since
//      ABI 0.7 clause 9.6's four magnitude forms and clause 5.4.1's
//      six formatOf operations over all sixteen ordered pairs of
//      formats - the one family whose operands and result are
//      different widths in the same call. Step 4
//      would pass without any of them: the cft_conformance inside the
//      module has replayed those sets since the module was first
//      built from sources that carried them, and it dispatches every
//      one internally, in C, never touching cftw_exp or cftw_atan2 or
//      cftw_augmented_add. For a day that is exactly what the module
//      was - ABI 0.3 by its own report, with no entry point a
//      JavaScript caller could reach (docs/COMPATIBILITY.md called it
//      the half-step). So this step reads the same vector files
//      itself, calls cftw_exp … cftw_hypot, cftw_sinpi …
//      cftw_atan2pi, cftw_sin … cftw_atanh, cftw_exp2m1 …
//      cftw_rootn, cftw_augmented_add … cftw_augmented_mul,
//      cftw_reduce at opcodes 24/25/28/29, cftw_scaled_prod …
//      cftw_scaled_prod_diff, cftw_from_decimal_char …
//      cftw_set_payload_signaling, cftw_min_mag … cftw_maxnum_mag and
//      cftw_formatof_add … cftw_formatof_fma, one element at a time
//      for exact per-case flags and then as arrays where the C has a
//      batch shape, and compares encodings, sequences, scales and
//      flags against the file. A wrapper with its operands swapped, or
//      missing, fails here and nowhere else - which is why atan2's
//      y-first order is checked by running it rather than by reading
//      it, and why the formatOf six are driven with their two formats
//      the way round the file names them.
//
// The loader comes from bindings/node/ if the package is there, else
// from bindings/wasm/build/ after a build.sh run. Vectors come from
// the directory named on the command line, else vectors/out (`make
// vectors` from the repo root), else the build's own copy. Step 5
// needs the sets the containerized build does NOT generate (its image
// carries no mpmath, and the transcendental reference needs one), so
// `make vectors` from the repo root is what puts them in reach;
// without them step 5 says it did not run rather than reporting a
// pass.

import { createHash } from "node:crypto";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const PAGE = join(HERE, "conformance.html");

const FORMATS = ["fp32", "fp64", "fp128", "fp256"];
const ROUNDINGS = ["rne", "rtz", "rdn", "rup", "rmm"];
const CANONICAL = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    CANONICAL.push(r === "rne" ? `${f}.jsonl` : `${f}-${r}.jsonl`);

// The transcendental sets are their own files with their own schema
// ("fn" rather than "op", and no c operand), because these are library
// entry points rather than opcodes - vectors/gen_vectors.py says why.
// The names below are the arities cft.h gives them, and they are also
// the cftw_* export names and the sets' "fn" values: one spelling, all
// the way down. Phase 1's nine first, then phase 2's eleven, then
// phase 3's nine, then the ten that complete table 9.1; the same
// twenty files carry all four since ABI 0.6.
//
// TRANSCEND_INTARG is a third arity rather than a flag on the second:
// its second operand is an int64 array, not an encoding, and the sets
// record it as "n", a signed decimal.
const TRANSCEND_UNARY = ["exp", "expm1", "exp2", "log", "log1p",
                         "log2", "log10",
                         "sinpi", "cospi", "tanpi", "asin", "acos",
                         "atan", "asinpi", "acospi", "atanpi",
                         "sin", "cos", "tan", "sinh", "cosh", "tanh",
                         "asinh", "acosh", "atanh",
                         "exp2m1", "exp10", "exp10m1", "log2p1",
                         "log10p1", "rsqrt"];
const TRANSCEND_BINARY = ["pow", "hypot", "atan2", "atan2pi", "powr"];
const TRANSCEND_INTARG = ["pown", "compound", "rootn"];
const TRANSCEND_SETS = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    TRANSCEND_SETS.push({
      name: r === "rne" ? `${f}-transcend.jsonl`
                        : `${f}-transcend-${r}.jsonl`,
      fmt: FORMATS.indexOf(f), rnd: ROUNDINGS.indexOf(r), rndName: r,
    });

// The augmented sets (clause 9.5): ONE file per format, not one per
// attribute, and the absence of a "rnd" field in them is normative -
// 9.5 fixes the rounding to roundTiesTowardZero, which is not one of
// clause 4.3's five, so there is no attribute to record and none to
// pass. Two outputs per case, "r" and "e".
const AUG_NAMES = ["augmentedAddition", "augmentedSubtraction",
                   "augmentedMultiplication"];
const AUG_CALL = { augmentedAddition: "augmented_add",
                   augmentedSubtraction: "augmented_sub",
                   augmentedMultiplication: "augmented_mul" };
const AUGMENTED_SETS = FORMATS.map((f, i) => ({
  name: `${f}-augmented.jsonl`, fmt: i,
}));

// The reduction sets (clause 9.4): a case is a whole VECTOR and one
// answer - two for the three scaled products, which return a
// (significand, int64 scale) pair. sum/dot/sumsq/sumabs are opcodes
// 24/25/28/29 through cftw_reduce; the scaled products have their own
// entry points, because a pair does not fit through an entry point
// that delivers one element.
const REDUCE_OPCODE = { sum: 24, dot: 25, sumsq: 28, sumabs: 29 };
const REDUCE_SCALED = { scaled_prod: "scaled_prod",
                        scaled_prod_sum: "scaled_prod_sum",
                        scaled_prod_diff: "scaled_prod_diff" };
const REDUCE_BINARY = new Set(["dot", "scaled_prod_sum",
                               "scaled_prod_diff"]);
const REDUCE_SETS = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    REDUCE_SETS.push({
      name: r === "rne" ? `${f}-reduce.jsonl` : `${f}-reduce-${r}.jsonl`,
      fmt: FORMATS.indexOf(f), rnd: ROUNDINGS.indexOf(r), rndName: r,
    });

// The character sets (clause 5.12) and the payload operations (9.7).
// A case names a SEQUENCE rather than an encoding, and some cases
// assert a REFUSAL - a sequence outside the syntax must be rejected,
// which is as much a part of the contract as any value and the one
// part a set of encodings cannot express.
const CHAR_FROM = new Set(["from_decimal", "from_hex"]);
const CHAR_TO = new Set(["to_decimal", "to_hex"]);
const CHAR_PAYLOAD = { get_payload: "get_payload",
                       set_payload: "set_payload",
                       set_payload_signaling: "set_payload_signaling" };
const CHARACTER_SETS = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    CHARACTER_SETS.push({
      name: r === "rne" ? `${f}-character.jsonl`
                        : `${f}-character-${r}.jsonl`,
      fmt: FORMATS.indexOf(f), rnd: ROUNDINGS.indexOf(r), rndName: r,
    });

// The magnitude sets (754-2019 9.6): ONE file per format, and the
// absence of a "rnd" field is normative for a sharper reason than the
// augmented family's - these operations compare two sign-cleared
// encodings and then SELECT an operand, so there is no rounding for an
// attribute to direct and no attribute could change an answer. "fn"
// carries 754's own spelling rather than this repository's C names,
// because the set is a statement about the standard.
const MM_NAMES = ["minimumMagnitude", "minimumMagnitudeNumber",
                  "maximumMagnitude", "maximumMagnitudeNumber"];
const MM_CALL = { minimumMagnitude: "min_mag",
                  minimumMagnitudeNumber: "minnum_mag",
                  maximumMagnitude: "max_mag",
                  maximumMagnitudeNumber: "maxnum_mag" };
const MINMAXMAG_SETS = FORMATS.map((f, i) => ({
  name: `${f}-minmaxmag.jsonl`, fmt: i,
}));

// The formatOf sets (5.4.1): one file per ORDERED PAIR of formats per
// attribute, all sixteen pairs including the same-format four, because
// 5.4.1 asks for every destination and, per destination, every source.
// 80 files.
//
// The only family whose case carries TWO formats, and the only one
// whose operand and result encodings are DIFFERENT WIDTHS on the same
// line - which is why the driver below reads "a" at the source's
// element size and "d" at the destination's, and why it checks the
// record's own sfmt/dfmt against the file's name rather than trusting
// either alone.
const FO_ARITY = { add: 2, sub: 2, mul: 2, div: 2, sqrt: 1, fma: 3 };
const FO_CALL = { add: "formatof_add", sub: "formatof_sub",
                  mul: "formatof_mul", div: "formatof_div",
                  sqrt: "formatof_sqrt", fma: "formatof_fma" };
const FORMATOF_SETS = [];
for (const s of FORMATS)
  for (const d of FORMATS)
    for (const r of ROUNDINGS)
      FORMATOF_SETS.push({
        name: r === "rne" ? `${s}-to-${d}-formatof.jsonl`
                          : `${s}-to-${d}-formatof-${r}.jsonl`,
        sfmt: FORMATS.indexOf(s), dfmt: FORMATS.indexOf(d),
        sName: s, dName: d,
        rnd: ROUNDINGS.indexOf(r), rndName: r,
      });

let failed = false;
const ok = (m) => console.log(`  ok    ${m}`);
const bad = (m) => { failed = true; console.log(`  FAIL  ${m}`); };
const sha256 = (b) => createHash("sha256").update(b).digest("hex");

// ---------------------------------------------------------------------
// 1. the page's module
//
// findWasmBinary(){return binaryDecode('...')} - one JS string literal
// holding one byte per code unit. The literal is walked rather than
// evaluated: this script reads a build product, and a build product is
// data. If the walk is wrong the sha256 in step 3 says so, which is
// why that check is worth having even though the answer looks obvious.
// ---------------------------------------------------------------------

function extractWasm(html) {
  // The CALL, not the definition of binaryDecode() a few hundred bytes
  // earlier - anchoring on the bare name finds the function body first
  // and reads a parameter list where a string literal should be.
  const anchor = "findWasmBinary(){return binaryDecode(";
  const at = html.indexOf(anchor);
  if (at < 0)
    throw new Error("no findWasmBinary(){return binaryDecode( in the page " +
                    "- has the emscripten SINGLE_FILE encoding changed? " +
                    "Teach this script the new one rather than deleting " +
                    "the check");
  let i = at + anchor.length;
  const quote = html[i++];
  if (quote !== "'" && quote !== '"')
    throw new Error(`binaryDecode( is not followed by a string literal`);

  const ESC = { n: 10, r: 13, t: 9, b: 8, f: 12, v: 11, 0: 0 };
  const out = [];
  for (;;) {
    const c = html[i++];
    if (c === undefined) throw new Error("unterminated wasm string literal");
    if (c === quote) break;
    if (c !== "\\") {
      const cc = html.codePointAt(i - 1);
      if (cc > 0xff)
        throw new Error(`code unit ${cc} > 255 in the wasm literal`);
      out.push(cc);
      continue;
    }
    const e = html[i++];
    if (e === "x") {
      out.push(parseInt(html.slice(i, i + 2), 16));
      i += 2;
    } else if (e === "u") {
      const cc = parseInt(html.slice(i, i + 4), 16);
      if (cc > 0xff) throw new Error(`\\u${html.slice(i, i + 4)} > 255`);
      out.push(cc);
      i += 4;
    } else if (e in ESC) {
      out.push(ESC[e]);
    } else {
      out.push(e.charCodeAt(0));     // \\ \' \" and anything else
    }
  }
  return Uint8Array.from(out);
}

console.log(`page    ${PAGE}`);
const html = readFileSync(PAGE, "utf8");
const pageWasm = extractWasm(html);
const pageHash = sha256(pageWasm);
console.log(`module  ${pageWasm.length.toLocaleString("en-US")} bytes, ` +
            `sha256 ${pageHash}`);

const MAGIC = [0x00, 0x61, 0x73, 0x6d];
if (MAGIC.every((b, k) => pageWasm[k] === b))
  ok("the extracted bytes are a wasm module (\\0asm)");
else
  bad("the extracted bytes do not start with the wasm magic");

// ---------------------------------------------------------------------
// 2. identity: ABI version, from the page's bytes
//
// cftw_abi_version() returns (major << 16) | minor and touches neither
// memory nor an import, so stub imports are enough to ask it. cft.h
// defines the encoding; this script derives the expectation from the
// header instead of hard-coding 2, because a hard-coded 2 would agree
// with a stale header just as happily as with a fresh one.
// ---------------------------------------------------------------------

function abiFromHeader() {
  const h = readFileSync(join(ROOT, "host", "include", "cft.h"), "utf8");
  const get = (name) => {
    const m = h.match(new RegExp(`^#define\\s+${name}\\s+(\\d+)`, "m"));
    if (!m) throw new Error(`cft.h has no ${name}`);
    return Number(m[1]);
  };
  const major = get("CFT_ABI_VERSION_MAJOR");
  const minor = get("CFT_ABI_VERSION_MINOR");
  return { major, minor, encoded: (major << 16) | minor };
}

function stubImports(mod) {
  const imports = {};
  for (const d of WebAssembly.Module.imports(mod)) {
    const ns = (imports[d.module] ??= {});
    if (d.kind === "function") ns[d.name] = () => 0;
    else if (d.kind === "memory")
      ns[d.name] = new WebAssembly.Memory({ initial: 256, maximum: 32768 });
    else if (d.kind === "table")
      ns[d.name] = new WebAssembly.Table({ initial: 0, element: "anyfunc" });
    else ns[d.name] = new WebAssembly.Global({ value: "i32", mutable: true }, 0);
  }
  return imports;
}

const want = abiFromHeader();
const mod = await WebAssembly.compile(pageWasm);
const inst = await WebAssembly.instantiate(mod, stubImports(mod));
const abi = inst.exports.cftw_abi_version() >>> 0;
const spell = (v) => `${v >>> 16}.${v & 0xffff}`;
console.log(`abi     cftw_abi_version() = ${abi} (${spell(abi)}); ` +
            `cft.h says ${want.encoded} (${want.major}.${want.minor})`);
if (abi === want.encoded)
  ok(`the page reports libcft ABI ${spell(abi)}, matching the header`);
else
  bad(`the page reports ABI ${spell(abi)} where the tree is at ` +
      `${want.major}.${want.minor} - rebuild it with bindings/wasm/build.sh`);

const exported = WebAssembly.Module.exports(mod)
  .map((e) => e.name).filter((n) => n.startsWith("cftw_"));
console.log(`exports ${exported.length} cftw_* entry points`);
// One name per ABI step, so a module built from a tree whose header
// has moved on is caught by the missing operation and not only by the
// version number: 0.1's cft_run, 0.2's clause-5 set, 0.3's nine, 0.4's
// eleven, 0.5's nine, 0.6's four packages, 0.7's two. Every one is
// listed in full because a module can carry all but one and still
// report 0.7, which is
// the failure mode this file is here for - it happened at 0.3 and at
// 0.4, once per minor step, until 0.5 shipped its wrappers with the
// library's own step and 0.6 and 0.7 did the same.
//
// CFT_SUMSQ and CFT_SUMABS are deliberately not in this list and need
// no wrapper: they are opcodes 28 and 29 through cftw_reduce, which
// has been exported since 0.1. Step 5 issues them, which is the check
// that matters for an opcode.
const NEEDED = ["cftw_run", "cftw_reduce", "cftw_conformance",
                "cftw_convert", "cftw_rint", "cftw_class", "cftw_rem",
                ...TRANSCEND_UNARY.map((f) => `cftw_${f}`),
                ...TRANSCEND_BINARY.map((f) => `cftw_${f}`),
                ...TRANSCEND_INTARG.map((f) => `cftw_${f}`),
                "cftw_format_decimal_digits",
                "cftw_from_decimal_char", "cftw_to_decimal_char",
                "cftw_from_hex_char", "cftw_to_hex_char",
                "cftw_get_payload", "cftw_set_payload",
                "cftw_set_payload_signaling",
                "cftw_scaled_prod", "cftw_scaled_prod_sum",
                "cftw_scaled_prod_diff",
                "cftw_augmented_add", "cftw_augmented_sub",
                "cftw_augmented_mul",
                // ABI 0.7, package B: the status word of 7.1 with
                // 5.7.4's six operations, cft.h's CFT_FLAGS_ALL macro
                // projected as a call (a macro is the one part of a
                // header the far side of a wasm boundary cannot
                // reach), and 5.7.1's three predicates.
                "cftw_flags_all", "cftw_lower_flags", "cftw_raise_flags",
                "cftw_test_flags", "cftw_save_all_flags",
                "cftw_restore_flags", "cftw_test_saved_flags",
                "cftw_is754version1985", "cftw_is754version2008",
                "cftw_is754version2019",
                // ABI 0.7, package B: 9.6's magnitude four.
                "cftw_min_mag", "cftw_max_mag", "cftw_minnum_mag",
                "cftw_maxnum_mag",
                // ABI 0.7, package A: 5.4.1's formatOf six.
                "cftw_formatof_add", "cftw_formatof_sub",
                "cftw_formatof_mul", "cftw_formatof_div",
                "cftw_formatof_sqrt", "cftw_formatof_fma"];
for (const needed of NEEDED) {
  if (!exported.includes(needed)) bad(`the module does not export ${needed}`);
}
console.log(`needed  ${NEEDED.length} named entry points checked present`);

// ---------------------------------------------------------------------
// 3. the node loader, and that it loads the same module
// ---------------------------------------------------------------------

const LOADERS = [
  [join(ROOT, "bindings", "node", "cft_node.js"),
   join(ROOT, "bindings", "node", "cft_node.wasm")],
  [join(HERE, "build", "cft_node.js"), join(HERE, "build", "cft_node.wasm")],
];
const loader = LOADERS.find(([js, w]) => existsSync(js) && existsSync(w));
if (!loader) {
  console.log("\nno node loader found (bindings/node/cft_node.js or " +
              "bindings/wasm/build/cft_node.js).");
  console.log("Steps 1 and 2 stand; the replay did NOT run. " +
              "`bash bindings/wasm/build.sh` produces one.");
  process.exit(failed ? 1 : 2);
}
const [loaderJs, loaderWasm] = loader;
const loaderHash = sha256(readFileSync(loaderWasm));
console.log(`\nloader  ${loaderJs}`);
if (loaderHash === pageHash)
  ok("the node loader's module is the page's module, byte for byte");
else
  bad(`the node loader carries a DIFFERENT module (${loaderHash}); a ` +
      `replay through it would not be a replay of the page`);

// ---------------------------------------------------------------------
// 4. the replay - the page's bytes, the library's own cft_conformance
// ---------------------------------------------------------------------

const vdirs = [process.argv[2], join(ROOT, "vectors", "out"),
               join(HERE, "build", "vectors")].filter(Boolean);
const vdir = vdirs.find((d) => existsSync(d) &&
  CANONICAL.every((n) => existsSync(join(d, n))));
if (!vdir) {
  console.log(`\nno complete vector directory in: ${vdirs.join(", ")}`);
  console.log("Steps 1-3 stand; the replay did NOT run. Run `make vectors` " +
              "from the repo root, or pass a directory.");
  process.exit(failed ? 1 : 2);
}
console.log(`vectors ${vdir}`);
// Every family the generator writes and cft_conformance enumerates:
// the twenty opcode sets, the twenty transcendental ones, the four
// augmented, twenty reduction and twenty character sets of ABI 0.6,
// and since ABI 0.7 the four magnitude sets of 9.6 and the eighty
// formatOf sets of 5.4.1 - one per ordered pair of formats per
// attribute. 168 names in all; anything else in the directory is named
// and skipped rather than replayed under a schema it does not have.
const ALL_SET_NAMES = [...CANONICAL,
                       ...TRANSCEND_SETS.map((s) => s.name),
                       ...AUGMENTED_SETS.map((s) => s.name),
                       ...REDUCE_SETS.map((s) => s.name),
                       ...CHARACTER_SETS.map((s) => s.name),
                       ...MINMAXMAG_SETS.map((s) => s.name),
                       ...FORMATOF_SETS.map((s) => s.name)];
const KNOWN = new Set(ALL_SET_NAMES);
const stray = readdirSync(vdir).filter((n) => n.endsWith(".jsonl") &&
  !KNOWN.has(n));
if (stray.length) console.log(`        (ignoring ${stray.join(", ")})`);

const { default: createCftModule } = await import(pathToFileURL(loaderJs));
// The page's module, not the loader's file: same bytes by step 3, and
// this way the replay is literally of what is committed.
const M = await createCftModule({ wasmBinary: pageWasm });

const num = "number", str = "string";
const N = (k) => Array(k).fill(num);
const C = {
  strerror: M.cwrap("cftw_strerror", str, [num]),
  openSoftware: M.cwrap("cftw_open_software", num, [num]),
  capsBackend: M.cwrap("cftw_caps_backend", str, [num]),
  formatSize: M.cwrap("cftw_format_size", num, [num]),
  conformance: M.cwrap("cftw_conformance", num, [num, str, num, num, num, num]),
  reduce: M.cwrap("cftw_reduce", num, N(10)),
  decimalDigits: M.cwrap("cftw_format_decimal_digits", num, [num]),
  from_decimal: M.cwrap("cftw_from_decimal_char", num, N(8)),
  to_decimal: M.cwrap("cftw_to_decimal_char", num, N(9)),
  from_hex: M.cwrap("cftw_from_hex_char", num, N(8)),
  to_hex: M.cwrap("cftw_to_hex_char", num, N(6)),
  get_payload: M.cwrap("cftw_get_payload", num, N(5)),
  set_payload: M.cwrap("cftw_set_payload", num, N(5)),
  set_payload_signaling: M.cwrap("cftw_set_payload_signaling", num, N(5)),
  scaled_prod: M.cwrap("cftw_scaled_prod", num, N(8)),
  scaled_prod_sum: M.cwrap("cftw_scaled_prod_sum", num, N(9)),
  scaled_prod_diff: M.cwrap("cftw_scaled_prod_diff", num, N(9)),
  augmented_add: M.cwrap("cftw_augmented_add", num, N(8)),
  augmented_sub: M.cwrap("cftw_augmented_sub", num, N(8)),
  augmented_mul: M.cwrap("cftw_augmented_mul", num, N(8)),
  // ABI 0.7, package B: the status word, the predicates, 9.6's four.
  // No rounding argument on the magnitude four and no bus word: they
  // select an operand and issue no device pass (cft.h).
  flags_all: M.cwrap("cftw_flags_all", num, []),
  lower_flags: M.cwrap("cftw_lower_flags", null, N(2)),
  raise_flags: M.cwrap("cftw_raise_flags", null, N(2)),
  test_flags: M.cwrap("cftw_test_flags", num, N(2)),
  save_all_flags: M.cwrap("cftw_save_all_flags", num, N(1)),
  restore_flags: M.cwrap("cftw_restore_flags", null, N(3)),
  test_saved_flags: M.cwrap("cftw_test_saved_flags", num, N(2)),
  is754version1985: M.cwrap("cftw_is754version1985", num, []),
  is754version2008: M.cwrap("cftw_is754version2008", num, []),
  is754version2019: M.cwrap("cftw_is754version2019", num, []),
  min_mag: M.cwrap("cftw_min_mag", num, N(7)),
  max_mag: M.cwrap("cftw_max_mag", num, N(7)),
  minnum_mag: M.cwrap("cftw_minnum_mag", num, N(7)),
  maxnum_mag: M.cwrap("cftw_maxnum_mag", num, N(7)),
  // ABI 0.7, package A: 5.4.1's six. TWO formats per call, so the
  // operand and result buffers are different widths in one call.
  formatof_add: M.cwrap("cftw_formatof_add", num, N(10)),
  formatof_sub: M.cwrap("cftw_formatof_sub", num, N(10)),
  formatof_mul: M.cwrap("cftw_formatof_mul", num, N(10)),
  formatof_div: M.cwrap("cftw_formatof_div", num, N(10)),
  formatof_sqrt: M.cwrap("cftw_formatof_sqrt", num, N(9)),
  formatof_fma: M.cwrap("cftw_formatof_fma", num, N(11)),
};
// The thirty-nine, by name. Thirty-one take (dev, fmt, rnd, a, d, n, flags),
// five take (dev, fmt, rnd, a, b, d, n, flags) and three take an int64
// ARRAY where b would be - no bus word anywhere, because a host
// operation issues no device pass (cft.h).
for (const fn of TRANSCEND_UNARY)
  C[fn] = M.cwrap(`cftw_${fn}`, num, N(7));
for (const fn of [...TRANSCEND_BINARY, ...TRANSCEND_INTARG])
  C[fn] = M.cwrap(`cftw_${fn}`, num, N(8));

const pp = M._malloc(4);
const st = C.openSoftware(pp);
const dev = M.HEAPU32[pp >> 2];
M._free(pp);
if (st !== 0 || !dev) {
  bad(`cft_open(software): ${C.strerror(st)}`);
  process.exit(1);
}
console.log(`backend ${C.capsBackend(dev)}`);

let seq = 0;
function replayOneSet(name, text) {
  const dir = `/replay${seq++}`;
  M.FS.mkdir(dir);
  M.FS.writeFile(`${dir}/${name}`, text);
  const repSize = 65536;
  const rep = M._malloc(repSize);
  const cases64 = M._malloc(8);
  try {
    const status = C.conformance(dev, dir, rep, repSize, cases64, cases64 + 4);
    const report = M.UTF8ToString(rep);
    const cases = M.HEAPU32[cases64 >> 2] +
                  M.HEAPU32[(cases64 + 4) >> 2] * 4294967296;
    return { status, report, cases };
  } finally {
    M._free(rep);
    M._free(cases64);
    try { M.FS.unlink(`${dir}/${name}`); } catch { /* keep the real error */ }
    try { M.FS.rmdir(dir); } catch { /* ditto */ }
  }
}

// Every set the page's drop zone accepts, one at a time in its own
// directory - which is exactly what the page does with a dropped file,
// so this measures that path and not a convenient variant of it. The
// transcendental sets are in the list since ABI 0.3 gave the page a
// reason to accept them, since 0.6 the augmented, reduction and
// character families are too, and since 0.7 the magnitude and formatOf
// ones; a directory that has only the twenty
// opcode sets (the containerized build's own copy) replays those and
// says the others were absent, rather than failing on a file nobody
// wrote.
const present = ALL_SET_NAMES.filter((n) => existsSync(join(vdir, n)));

console.log("\nreplay  (one cft_conformance() call per set, full files)");
let total = 0, clean = 0;
for (const name of present) {
  const text = readFileSync(join(vdir, name), "utf8");
  const r = replayOneSet(name, text);
  total += r.cases;
  const n = r.cases.toLocaleString("en-US").padStart(7);
  if (r.status === 0 && r.cases > 0) {
    clean++;
    console.log(`  ${name.padEnd(26)} ${n}  all matching`);
  } else {
    failed = true;
    console.log(`  ${name.padEnd(26)} ${n}  FAILED: ${C.strerror(r.status)}`);
    console.log(r.report.trim().split("\n").map((l) => "      " + l).join("\n"));
  }
}

// A run that checked nothing must not read as a pass - the rule
// cft_conformance applies to its own summary, applied here.
console.log("");
if (clean === present.length && total > 0)
  ok(`${total.toLocaleString("en-US")} cases over ${clean} sets, ` +
     `library matches the vectors exactly`);
else
  bad(`${clean} of ${present.length} sets clean, ` +
      `${total.toLocaleString("en-US")} cases`);

// ---------------------------------------------------------------------
// 5. everything that is not an opcode, through its own wrapper
//
// Step 4 dispatches all of it inside C and would be green with no
// cftw_* wrapper for any of it at all - it was, for a day. This step
// is the one that fails when the JavaScript surface is missing or
// wrong, so it reads the sets here and calls the exports.
// Per case first, because the flag word in the file is that case's,
// then as arrays wherever the C has a batch shape, because a wrapper
// that only works at n == 1 would be a wrapper that does not work.
//
// Six families, six schemas, one rule: nothing here computes an
// expected value. Every expectation is a field in a file the golden
// model wrote.
// ---------------------------------------------------------------------

function bytesOfHex(hex, esz) {
  let v = BigInt(hex);
  const out = new Uint8Array(esz);
  for (let i = 0; i < esz; i++) { out[i] = Number(v & 0xffn); v >>= 8n; }
  if (v !== 0n) throw new Error(`${hex} does not fit ${esz} bytes`);
  return out;
}

/** An INT64 field, read out of the raw line as a BigInt.
 *
 *  Not JSON.parse's answer, and the difference is not pedantry. A JSON
 *  number becomes a JS number, which is a binary64: the published sets
 *  carry pown's exponent at both int64 extremes, and JSON.parse turns
 *  9223372036854775807 into 9223372036854775808 - one past INT64_MAX,
 *  a different exponent, and a wrong answer that looks like a library
 *  bug. host/src/conformance.c reads these with field_i64() for the
 *  same reason; this is that function. The scan is the C's too: find
 *  the quoted key, then the signed decimal after the colon. */
function fieldI64(line, key) {
  const m = new RegExp(`"${key}"\\s*:\\s*(-?\\d+)`).exec(line);
  if (!m) return null;
  const v = BigInt(m[1]);
  if (v < -(2n ** 63n) || v >= 2n ** 63n)
    throw new Error(`"${key}": ${m[1]} is not an int64`);
  return v;
}

function hexOfBytes(bytes) {
  let s = "0x";
  for (let i = bytes.length - 1; i >= 0; i--)
    s += bytes[i].toString(16).padStart(2, "0");
  return s;
}

/** n int64 values into a fresh heap allocation. The caller frees. */
function mallocI64(values) {
  const p = M._malloc(8 * Math.max(values.length, 1));
  const view = new BigInt64Array(M.HEAPU8.buffer, p, values.length);
  values.forEach((v, i) => { view[i] = v; });
  return p;
}

/** One int64 out of the heap, as a BigInt. The view is taken here and
 *  never kept: a later _malloc can grow the memory and detach it. */
function readI64(p) {
  return new BigInt64Array(M.HEAPU8.buffer, p, 1)[0];
}

/** One NUL-terminated sequence into a fresh allocation. */
function mallocString(s) {
  const bytes = M.lengthBytesUTF8(s) + 1;
  const p = M._malloc(bytes);
  M.stringToUTF8(s, p, bytes);
  return p;
}

/** One set file: every case through its wrapper at n == 1, then each
 *  family once as one array. Returns a count, or throws the first
 *  disagreement with the library's operands in it. */
function driveTranscendSet(set, text) {
  const esz = C.formatSize(set.fmt);
  const byFn = new Map();
  let lineno = 0;
  for (const line of text.split("\n")) {
    lineno++;
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    if (c.rnd !== set.rndName)
      throw new Error(`${set.name}:${lineno}: attribute "${c.rnd}" in a ` +
                      `${set.rndName} set`);
    const binary = TRANSCEND_BINARY.includes(c.fn);
    const intarg = TRANSCEND_INTARG.includes(c.fn);
    if (!binary && !intarg && !TRANSCEND_UNARY.includes(c.fn))
      throw new Error(`${set.name}:${lineno}: unknown function "${c.fn}" - ` +
                      `this script's table and cft.h have diverged`);
    if (binary !== (c.b !== undefined))
      throw new Error(`${set.name}:${lineno}: ${c.fn} is ` +
                      `${binary ? "binary" : "unary"} but the case ` +
                      `${c.b !== undefined ? "carries" : "omits"} b`);
    // "n" is a SIGNED DECIMAL rather than an encoding, and its absence
    // on one of the three that take it is a refusal, not a default of
    // zero: pown(x, 0) is 1 for every x, so a missing field read as 0
    // would be a plausible wrong answer rather than a loud one. It is
    // read out of the raw line, not out of JSON.parse's object - see
    // fieldI64().
    const nn = fieldI64(line, "n");
    if (intarg !== (nn !== null))
      throw new Error(`${set.name}:${lineno}: ${c.fn} ` +
                      `${intarg ? "takes" : "does not take"} an integer ` +
                      `exponent but the case ` +
                      `${nn !== null ? "carries" : "omits"} "n"`);
    if (!byFn.has(c.fn)) byFn.set(c.fn, []);
    byFn.get(c.fn).push({
      lineno,
      a: bytesOfHex(c.a, esz),
      b: binary ? bytesOfHex(c.b, esz) : null,
      n: intarg ? nn : null,
      d: bytesOfHex(c.d, esz),
      flags: c.flags >>> 0,
    });
  }
  if (!byFn.size) throw new Error(`${set.name}: no cases`);

  let checked = 0;
  for (const [fn, cases] of byFn) {
    const binary = TRANSCEND_BINARY.includes(fn);
    const intarg = TRANSCEND_INTARG.includes(fn);
    // The int64 array sits where b's encoding array sits, which is why
    // its own branch is worth having: the argument COUNT is the same
    // and the meaning is not.
    const call = (pa, pb, pd, n, pfl) => (binary || intarg)
      ? C[fn](dev, set.fmt, set.rnd, pa, pb, pd, n, pfl)
      : C[fn](dev, set.fmt, set.rnd, pa, pd, n, pfl);

    // per element: the flag word in the file belongs to this case, and
    // an array call would only ever show their union
    const pa = M._malloc(esz), pb = M._malloc(esz);
    const pd = M._malloc(esz), pfl = M._malloc(4);
    const pn = M._malloc(8);
    let unionFlags = 0;
    try {
      for (const c of cases) {
        M.HEAPU8.set(c.a, pa);
        if (c.b) M.HEAPU8.set(c.b, pb);
        if (c.n !== null) new BigInt64Array(M.HEAPU8.buffer, pn, 1)[0] = c.n;
        M.HEAPU8.fill(0, pd, pd + esz);
        M.HEAPU32[pfl >> 2] = 0;
        const second = c.b ? pb : (c.n !== null ? pn : 0);
        const st = call(pa, second, pd, 1, pfl);
        if (st !== 0)
          throw new Error(`${set.name}:${c.lineno}: cftw_${fn} returned ` +
                          `${C.strerror(st)}`);
        const got = M.HEAPU8.slice(pd, pd + esz);
        const gotFlags = M.HEAPU32[pfl >> 2] >>> 0;
        if (hexOfBytes(got) !== hexOfBytes(c.d) || gotFlags !== c.flags)
          throw new Error(
            `${set.name}:${c.lineno}: ${fn} ${set.rndName}\n` +
            `        a        ${hexOfBytes(c.a)}\n` +
            (c.b ? `        b        ${hexOfBytes(c.b)}\n` : "") +
            (c.n !== null ? `        n        ${c.n}\n` : "") +
            `        expected ${hexOfBytes(c.d)} flags 0x` +
            `${c.flags.toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOfBytes(got)} flags 0x` +
            `${gotFlags.toString(16).padStart(2, "0")}`);
        unionFlags |= gotFlags;
        checked++;
      }
    } finally {
      for (const p of [pa, pb, pd, pfl, pn]) M._free(p);
    }

    // and once as one array of the whole family
    const n = cases.length;
    const aa = M._malloc(esz * n), ab = M._malloc(esz * n);
    const ad = M._malloc(esz * n), afl = M._malloc(4);
    const an = intarg ? mallocI64(cases.map((c) => c.n)) : 0;
    try {
      cases.forEach((c, i) => {
        M.HEAPU8.set(c.a, aa + i * esz);
        if (c.b) M.HEAPU8.set(c.b, ab + i * esz);
      });
      M.HEAPU8.fill(0, ad, ad + esz * n);
      M.HEAPU32[afl >> 2] = 0;
      const st = call(aa, binary ? ab : (intarg ? an : 0), ad, n, afl);
      if (st !== 0)
        throw new Error(`${set.name}: cftw_${fn} over ${n} elements ` +
                        `returned ${C.strerror(st)}`);
      cases.forEach((c, i) => {
        const got = M.HEAPU8.slice(ad + i * esz, ad + (i + 1) * esz);
        if (hexOfBytes(got) !== hexOfBytes(c.d))
          throw new Error(`${set.name}:${c.lineno}: ${fn} disagrees with ` +
                          `itself between n == 1 and n == ${n} - element ` +
                          `${i} is ${hexOfBytes(got)}, the scalar call and ` +
                          `the file both say ${hexOfBytes(c.d)}`);
      });
      const arrFlags = M.HEAPU32[afl >> 2] >>> 0;
      if (arrFlags !== unionFlags)
        throw new Error(`${set.name}: ${fn} over ${n} elements raised 0x` +
                        `${arrFlags.toString(16)}, the union over the ` +
                        `scalar calls is 0x${unionFlags.toString(16)}`);
    } finally {
      for (const p of [aa, ab, ad, afl]) M._free(p);
      if (an) M._free(an);
    }
  }
  return checked;
}

/** The augmented sets (9.5): two outputs per case, no attribute. Per
 *  case, then each operation once as one array. */
function driveAugmentedSet(set, text) {
  const esz = C.formatSize(set.fmt);
  const byFn = new Map();
  let lineno = 0;
  for (const line of text.split("\n")) {
    lineno++;
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    if (!AUG_NAMES.includes(c.fn))
      throw new Error(`${set.name}:${lineno}: unknown augmented operation ` +
                      `"${c.fn}"`);
    // The absence of "rnd" is normative: 9.5 fixes the direction to
    // roundTiesTowardZero, so a set that carried one would be recording
    // a choice that does not exist.
    if (c.rnd !== undefined)
      throw new Error(`${set.name}:${lineno}: an augmented case carries a ` +
                      `"rnd" field (${c.rnd}); 9.5 fixes the rounding to ` +
                      `roundTiesTowardZero, which is not one of the five ` +
                      `attributes, so there is nothing for it to name`);
    if (!byFn.has(c.fn)) byFn.set(c.fn, []);
    byFn.get(c.fn).push({
      lineno,
      a: bytesOfHex(c.a, esz), b: bytesOfHex(c.b, esz),
      r: bytesOfHex(c.r, esz), e: bytesOfHex(c.e, esz),
      flags: c.flags >>> 0,
    });
  }
  if (!byFn.size) throw new Error(`${set.name}: no cases`);

  let checked = 0;
  for (const [fn, cases] of byFn) {
    const w = C[AUG_CALL[fn]];
    const pa = M._malloc(esz), pb = M._malloc(esz);
    const pr = M._malloc(esz), pe = M._malloc(esz), pfl = M._malloc(4);
    let unionFlags = 0;
    try {
      for (const c of cases) {
        M.HEAPU8.set(c.a, pa);
        M.HEAPU8.set(c.b, pb);
        M.HEAPU8.fill(0, pr, pr + esz);
        M.HEAPU8.fill(0, pe, pe + esz);
        M.HEAPU32[pfl >> 2] = 0;
        const st = w(dev, set.fmt, pa, pb, pr, pe, 1, pfl);
        if (st !== 0)
          throw new Error(`${set.name}:${c.lineno}: cftw_${AUG_CALL[fn]} ` +
                          `returned ${C.strerror(st)}`);
        const gr = M.HEAPU8.slice(pr, pr + esz);
        const ge = M.HEAPU8.slice(pe, pe + esz);
        const gotFlags = M.HEAPU32[pfl >> 2] >>> 0;
        if (hexOfBytes(gr) !== hexOfBytes(c.r) ||
            hexOfBytes(ge) !== hexOfBytes(c.e) || gotFlags !== c.flags)
          throw new Error(
            `${set.name}:${c.lineno}: ${fn}\n` +
            `        a        ${hexOfBytes(c.a)}\n` +
            `        b        ${hexOfBytes(c.b)}\n` +
            `        expected r ${hexOfBytes(c.r)} e ${hexOfBytes(c.e)} ` +
            `flags 0x${c.flags.toString(16).padStart(2, "0")}\n` +
            `        got      r ${hexOfBytes(gr)} e ${hexOfBytes(ge)} ` +
            `flags 0x${gotFlags.toString(16).padStart(2, "0")}`);
        unionFlags |= gotFlags;
        checked++;
      }
    } finally {
      for (const p of [pa, pb, pr, pe, pfl]) M._free(p);
    }

    const n = cases.length;
    const aa = M._malloc(esz * n), ab = M._malloc(esz * n);
    const ar = M._malloc(esz * n), ae = M._malloc(esz * n);
    const afl = M._malloc(4);
    try {
      cases.forEach((c, i) => {
        M.HEAPU8.set(c.a, aa + i * esz);
        M.HEAPU8.set(c.b, ab + i * esz);
      });
      M.HEAPU8.fill(0, ar, ar + esz * n);
      M.HEAPU8.fill(0, ae, ae + esz * n);
      M.HEAPU32[afl >> 2] = 0;
      const st = w(dev, set.fmt, aa, ab, ar, ae, n, afl);
      if (st !== 0)
        throw new Error(`${set.name}: cftw_${AUG_CALL[fn]} over ${n} ` +
                        `elements returned ${C.strerror(st)}`);
      cases.forEach((c, i) => {
        const gr = M.HEAPU8.slice(ar + i * esz, ar + (i + 1) * esz);
        const ge = M.HEAPU8.slice(ae + i * esz, ae + (i + 1) * esz);
        if (hexOfBytes(gr) !== hexOfBytes(c.r) ||
            hexOfBytes(ge) !== hexOfBytes(c.e))
          throw new Error(`${set.name}:${c.lineno}: ${fn} disagrees with ` +
                          `itself between n == 1 and n == ${n} - element ` +
                          `${i} is (${hexOfBytes(gr)}, ${hexOfBytes(ge)}), ` +
                          `the scalar call and the file both say ` +
                          `(${hexOfBytes(c.r)}, ${hexOfBytes(c.e)})`);
      });
      const arrFlags = M.HEAPU32[afl >> 2] >>> 0;
      if (arrFlags !== unionFlags)
        throw new Error(`${set.name}: ${fn} over ${n} elements raised 0x` +
                        `${arrFlags.toString(16)}, the union over the ` +
                        `scalar calls is 0x${unionFlags.toString(16)}`);
    } finally {
      for (const p of [aa, ab, ar, ae, afl]) M._free(p);
    }
  }
  return checked;
}

/** The reduction sets (9.4). A case IS an array call, so there is no
 *  second array pass and none is needed - and the flags stay exact per
 *  case for the same reason. sum/dot/sumsq/sumabs go through
 *  cftw_reduce at opcodes 24/25/28/29; the three scaled products have
 *  their own entry points and return a pair. */
function driveReduceSet(set, text) {
  const esz = C.formatSize(set.fmt);
  let lineno = 0, checked = 0;
  for (const line of text.split("\n")) {
    lineno++;
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    if (c.rnd !== set.rndName)
      throw new Error(`${set.name}:${lineno}: attribute "${c.rnd}" in a ` +
                      `${set.rndName} set`);
    const scaled = Object.hasOwn(REDUCE_SCALED, c.fn);
    const opcode = REDUCE_OPCODE[c.fn];
    if (!scaled && opcode === undefined)
      throw new Error(`${set.name}:${lineno}: unknown reduction "${c.fn}"`);
    const binary = REDUCE_BINARY.has(c.fn);
    if (!Array.isArray(c.a) || c.a.length !== c.n)
      throw new Error(`${set.name}:${lineno}: "a" is not ${c.n} elements`);
    if (binary && (!Array.isArray(c.b) || c.b.length !== c.n))
      throw new Error(`${set.name}:${lineno}: ${c.fn} needs a "b" of ` +
                      `${c.n} elements`);
    const n = c.n;
    const flags = c.flags >>> 0;

    const pa = M._malloc(esz * Math.max(n, 1));
    const pb = M._malloc(esz * Math.max(n, 1));
    const pd = M._malloc(esz), psf = M._malloc(8), pfl = M._malloc(4);
    try {
      c.a.forEach((h, i) => M.HEAPU8.set(bytesOfHex(h, esz), pa + i * esz));
      if (binary)
        c.b.forEach((h, i) => M.HEAPU8.set(bytesOfHex(h, esz), pb + i * esz));
      M.HEAPU8.fill(0, pd, pd + esz);
      new BigInt64Array(M.HEAPU8.buffer, psf, 1)[0] = 0n;
      M.HEAPU32[pfl >> 2] = 0;
      // n == 0 passes NULL for the operands, as the C's own replay
      // does: an empty reduction is an answer (+0 for a sum, and 9.4's
      // multiplicative identity for a scaled product), not a read.
      const ap = n ? pa : 0, bp = n && binary ? pb : 0;
      let st;
      if (!scaled)
        st = C.reduce(dev, opcode, set.fmt, set.rnd, ap, bp, pd, n, pfl, 0);
      else if (binary)
        st = C[c.fn](dev, set.fmt, set.rnd, ap, bp, pd, psf, n, pfl);
      else
        st = C[c.fn](dev, set.fmt, set.rnd, ap, pd, psf, n, pfl);
      if (st !== 0)
        throw new Error(`${set.name}:${lineno}: ${c.fn} over ${n} elements ` +
                        `returned ${C.strerror(st)}`);
      const got = M.HEAPU8.slice(pd, pd + esz);
      const gotSf = readI64(psf);
      const gotFlags = M.HEAPU32[pfl >> 2] >>> 0;
      const wantHex = scaled ? c.pr : c.d;
      // The scale is an int64 in the contract, so it is read the way
      // pown's exponent is - out of the line, never through a double.
      const wantSf = scaled ? fieldI64(line, "sf") : 0n;
      if (scaled && wantSf === null)
        throw new Error(`${set.name}:${lineno}: a scaled product's case ` +
                        `needs both "pr" and "sf" - it returns a pair`);
      if (hexOfBytes(got) !== hexOfBytes(bytesOfHex(wantHex, esz)) ||
          gotSf !== wantSf || gotFlags !== flags)
        throw new Error(
          `${set.name}:${lineno}: ${c.fn} ${set.rndName} over ${n} elements\n` +
          `        expected ${wantHex}` +
          (scaled ? ` scale ${wantSf}` : "") +
          ` flags 0x${flags.toString(16).padStart(2, "0")}\n` +
          `        got      ${hexOfBytes(got)}` +
          (scaled ? ` scale ${gotSf}` : "") +
          ` flags 0x${gotFlags.toString(16).padStart(2, "0")}`);
      checked++;
    } finally {
      for (const p of [pa, pb, pd, psf, pfl]) M._free(p);
    }
  }
  if (!checked) throw new Error(`${set.name}: no cases`);
  return checked;
}

/** One to_ conversion through the C's two-call sizing protocol,
 *  exactly as host/src/conformance.c runs it: ask with a NULL buffer
 *  and capacity 0, which reports the length and REFUSES, then call
 *  again with a buffer that size. A wrapper that answered the sizing
 *  call with CFT_OK, or that truncated into a short buffer, fails
 *  here. */
function charWrite(fmt, rnd, kind, pa, digits) {
  const plen = M._malloc(4), pfl = M._malloc(4);
  try {
    M.HEAPU32[plen >> 2] = 0;
    M.HEAPU32[pfl >> 2] = 0;
    const ask = kind === "to_decimal"
      ? C.to_decimal(dev, fmt, rnd, pa, digits, 0, 0, plen, pfl)
      : C.to_hex(dev, fmt, pa, 0, 0, plen);
    const need = M.HEAPU32[plen >> 2] >>> 0;
    if (ask === 0)
      throw new Error(`cftw_${kind}: the sizing call (NULL buffer, cap 0) ` +
                      `returned success where cft.h says it reports the ` +
                      `required length and refuses`);
    if (need < 2)
      throw new Error(`cftw_${kind}: sizing call reported ${need} bytes`);
    const out = M._malloc(need);
    try {
      // A buffer one byte short must refuse with NOTHING written -
      // "this library does not truncate a number" - and must still set
      // the length. Checked here rather than asserted in prose.
      M.HEAPU8.fill(0, out, out + need);
      M.HEAPU32[plen >> 2] = 0;
      const short_ = kind === "to_decimal"
        ? C.to_decimal(dev, fmt, rnd, pa, digits, out, need - 1, plen, pfl)
        : C.to_hex(dev, fmt, pa, out, need - 1, plen);
      if (short_ === 0)
        throw new Error(`cftw_${kind}: a buffer of ${need - 1} bytes was ` +
                        `accepted for an answer needing ${need}`);
      if ((M.HEAPU32[plen >> 2] >>> 0) !== need)
        throw new Error(`cftw_${kind}: a refused short buffer left the ` +
                        `length at ${M.HEAPU32[plen >> 2] >>> 0}, not ` +
                        `${need}`);
      if (M.HEAPU8[out] !== 0)
        throw new Error(`cftw_${kind}: a refused short buffer was written ` +
                        `into; cft.h says nothing is written`);
      M.HEAPU32[plen >> 2] = 0;
      M.HEAPU32[pfl >> 2] = 0;
      const st = kind === "to_decimal"
        ? C.to_decimal(dev, fmt, rnd, pa, digits, out, need, plen, pfl)
        : C.to_hex(dev, fmt, pa, out, need, plen);
      if (st !== 0)
        throw new Error(`cftw_${kind} returned ${C.strerror(st)} with the ` +
                        `${need}-byte buffer it asked for`);
      return { text: M.UTF8ToString(out), len: need,
               flags: M.HEAPU32[pfl >> 2] >>> 0 };
    } finally {
      M._free(out);
    }
  } finally {
    M._free(plen);
    M._free(pfl);
  }
}

/** The character sets (5.12) and the payload operations (9.7). Per
 *  case for exact flags and for the sizing protocol, then the from_
 *  conversions again as one array each, which is the batch-shaped half
 *  of this API. The to_ conversions are per element by design (cft.h
 *  says why), so their second pass is the one the first pass is. */
function driveCharacterSet(set, text) {
  const esz = C.formatSize(set.fmt);
  const batch = { from_decimal: [], from_hex: [] };
  let lineno = 0, checked = 0;
  for (const line of text.split("\n")) {
    lineno++;
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    if (c.rnd !== set.rndName)
      throw new Error(`${set.name}:${lineno}: attribute "${c.rnd}" in a ` +
                      `${set.rndName} set`);
    const refuse = c.refuse !== undefined;

    if (CHAR_FROM.has(c.fn)) {
      const ps = mallocString(c.s);
      const pin = M._malloc(4);
      const pd = M._malloc(esz), pbad = M._malloc(4), pfl = M._malloc(4);
      try {
        M.HEAPU32[pin >> 2] = ps;
        M.HEAPU8.fill(0, pd, pd + esz);
        M.HEAPU32[pbad >> 2] = 0;
        M.HEAPU32[pfl >> 2] = 0;
        const st = C[c.fn](dev, set.fmt, set.rnd, pin, pd, 1, pbad, pfl);
        checked++;
        if (refuse) {
          // The contract's refusal: a sequence outside 5.12's syntax
          // must be rejected rather than guessed at, and that is as
          // much a part of the contract as any value.
          if (st === 0)
            throw new Error(`${set.name}:${lineno}: cftw_${c.fn} ACCEPTED a ` +
                            `sequence that is not in the syntax: ` +
                            `${JSON.stringify(c.s)}`);
          continue;
        }
        if (st !== 0)
          throw new Error(`${set.name}:${lineno}: cftw_${c.fn} refused ` +
                          `${JSON.stringify(c.s)} at element ` +
                          `${M.HEAPU32[pbad >> 2]}: ${C.strerror(st)}`);
        const got = M.HEAPU8.slice(pd, pd + esz);
        const gotFlags = M.HEAPU32[pfl >> 2] >>> 0;
        if (hexOfBytes(got) !== hexOfBytes(bytesOfHex(c.d, esz)) ||
            gotFlags !== (c.flags >>> 0))
          throw new Error(
            `${set.name}:${lineno}: ${c.fn} ${set.rndName}\n` +
            `        s        ${JSON.stringify(c.s.slice(0, 200))}\n` +
            `        expected ${c.d} flags 0x` +
            `${(c.flags >>> 0).toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOfBytes(got)} flags 0x` +
            `${gotFlags.toString(16).padStart(2, "0")}`);
        batch[c.fn].push({ lineno, s: c.s, d: bytesOfHex(c.d, esz),
                           flags: c.flags >>> 0 });
      } finally {
        for (const p of [ps, pin, pd, pbad, pfl]) M._free(p);
      }
      continue;
    }

    const pa = mallocBytes(bytesOfHex(c.a, esz));
    try {
      if (CHAR_TO.has(c.fn)) {
        const got = charWrite(set.fmt, set.rnd, c.fn, pa,
                              c.fn === "to_decimal" ? (c.digits >>> 0) : 0);
        checked++;
        if (got.text !== c.s || got.flags !== (c.flags >>> 0))
          throw new Error(
            `${set.name}:${lineno}: ${c.fn} ${set.rndName} a=${c.a}` +
            (c.fn === "to_decimal" ? ` digits=${c.digits}` : "") + `\n` +
            `        expected ${JSON.stringify(c.s.slice(0, 200))} flags 0x` +
            `${(c.flags >>> 0).toString(16).padStart(2, "0")}\n` +
            `        got      ${JSON.stringify(got.text.slice(0, 200))} ` +
            `flags 0x${got.flags.toString(16).padStart(2, "0")}`);
        continue;
      }

      const pay = CHAR_PAYLOAD[c.fn];
      if (!pay)
        throw new Error(`${set.name}:${lineno}: unknown character or ` +
                        `payload operation "${c.fn}"`);
      const pd = M._malloc(esz);
      try {
        M.HEAPU8.fill(0, pd, pd + esz);
        const st = C[pay](dev, set.fmt, pa, pd, 1);
        checked++;
        if (st !== 0)
          throw new Error(`${set.name}:${lineno}: cftw_${pay} returned ` +
                          `${C.strerror(st)}`);
        const got = M.HEAPU8.slice(pd, pd + esz);
        if (hexOfBytes(got) !== hexOfBytes(bytesOfHex(c.d, esz)))
          throw new Error(
            `${set.name}:${lineno}: ${c.fn}\n` +
            `        a        ${c.a}\n` +
            `        expected ${c.d}\n        got      ${hexOfBytes(got)}`);
      } finally {
        M._free(pd);
      }
    } finally {
      M._free(pa);
    }
  }
  if (!checked) throw new Error(`${set.name}: no cases`);

  // The array pass over the from_ conversions: the same sequences
  // again, a whole file at a time, so the batch loop and the flag OR
  // run. The refused sequences are deliberately NOT in this pool - one
  // of them would refuse the whole call, which is the contract and not
  // a thing to measure here.
  for (const kind of ["from_decimal", "from_hex"]) {
    const cases = batch[kind];
    if (!cases.length) continue;
    const k = cases.length;
    const ptrs = cases.map((c) => mallocString(c.s));
    const pin = M._malloc(4 * k);
    const pd = M._malloc(esz * k), pbad = M._malloc(4), pfl = M._malloc(4);
    try {
      ptrs.forEach((p, i) => { M.HEAPU32[(pin >> 2) + i] = p; });
      M.HEAPU8.fill(0, pd, pd + esz * k);
      M.HEAPU32[pbad >> 2] = 0;
      M.HEAPU32[pfl >> 2] = 0;
      const st = C[kind](dev, set.fmt, set.rnd, pin, pd, k, pbad, pfl);
      if (st !== 0)
        throw new Error(`${set.name}: cftw_${kind} over ${k} sequences ` +
                        `failed at element ${M.HEAPU32[pbad >> 2]}: ` +
                        `${C.strerror(st)}`);
      let want = 0;
      cases.forEach((c, i) => {
        want |= c.flags;
        const got = M.HEAPU8.slice(pd + i * esz, pd + (i + 1) * esz);
        if (hexOfBytes(got) !== hexOfBytes(c.d))
          throw new Error(`${set.name}:${c.lineno}: ${kind} disagrees with ` +
                          `itself between n == 1 and n == ${k} - element ` +
                          `${i} (${JSON.stringify(c.s.slice(0, 60))}) is ` +
                          `${hexOfBytes(got)}, the scalar call and the file ` +
                          `both say ${hexOfBytes(c.d)}`);
      });
      const arrFlags = M.HEAPU32[pfl >> 2] >>> 0;
      if (arrFlags !== want)
        throw new Error(`${set.name}: ${kind} over ${k} sequences raised 0x` +
                        `${arrFlags.toString(16)}, the OR over the cases is ` +
                        `0x${want.toString(16)}`);
    } finally {
      for (const p of [...ptrs, pin, pd, pbad, pfl]) M._free(p);
    }
  }
  return checked;
}

function mallocBytes(bytes) {
  const p = M._malloc(bytes.length);
  M.HEAPU8.set(bytes, p);
  return p;
}

/** The magnitude sets (9.6): two operands in, one out, no attribute
 *  and no bus word. Per case for exact flags, then each operation once
 *  as one array. */
function driveMinMaxMagSet(set, text) {
  const esz = C.formatSize(set.fmt);
  const byFn = new Map();
  let lineno = 0;
  for (const line of text.split("\n")) {
    lineno++;
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    if (!MM_NAMES.includes(c.fn))
      throw new Error(`${set.name}:${lineno}: unknown magnitude operation ` +
                      `"${c.fn}" - 9.6 names four`);
    // The absence of "rnd" is normative: these compare magnitudes and
    // then SELECT an operand, so no attribute could change an answer
    // and a set carrying one would be recording a choice that does not
    // exist.
    if (c.rnd !== undefined)
      throw new Error(`${set.name}:${lineno}: a 9.6 magnitude case carries ` +
                      `a "rnd" field (${c.rnd}); there is no rounding here ` +
                      `for an attribute to direct`);
    if (!byFn.has(c.fn)) byFn.set(c.fn, []);
    byFn.get(c.fn).push({
      lineno,
      a: bytesOfHex(c.a, esz), b: bytesOfHex(c.b, esz),
      d: bytesOfHex(c.d, esz), flags: c.flags >>> 0,
    });
  }
  if (!byFn.size) throw new Error(`${set.name}: no cases`);

  let checked = 0;
  for (const [fn, cases] of byFn) {
    const w = C[MM_CALL[fn]];
    const pa = M._malloc(esz), pb = M._malloc(esz);
    const pd = M._malloc(esz), pfl = M._malloc(4);
    let unionFlags = 0;
    try {
      for (const c of cases) {
        M.HEAPU8.set(c.a, pa);
        M.HEAPU8.set(c.b, pb);
        M.HEAPU8.fill(0, pd, pd + esz);
        M.HEAPU32[pfl >> 2] = 0;
        const st = w(dev, set.fmt, pa, pb, pd, 1, pfl);
        if (st !== 0)
          throw new Error(`${set.name}:${c.lineno}: cftw_${MM_CALL[fn]} ` +
                          `returned ${C.strerror(st)}`);
        const got = M.HEAPU8.slice(pd, pd + esz);
        const gotFlags = M.HEAPU32[pfl >> 2] >>> 0;
        if (hexOfBytes(got) !== hexOfBytes(c.d) || gotFlags !== c.flags)
          throw new Error(
            `${set.name}:${c.lineno}: ${fn}\n` +
            `        a        ${hexOfBytes(c.a)}\n` +
            `        b        ${hexOfBytes(c.b)}\n` +
            `        expected ${hexOfBytes(c.d)} flags 0x` +
            `${c.flags.toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOfBytes(got)} flags 0x` +
            `${gotFlags.toString(16).padStart(2, "0")}`);
        unionFlags |= gotFlags;
        checked++;
      }
    } finally {
      for (const p of [pa, pb, pd, pfl]) M._free(p);
    }

    const n = cases.length;
    const aa = M._malloc(esz * n), ab = M._malloc(esz * n);
    const ad = M._malloc(esz * n), afl = M._malloc(4);
    try {
      cases.forEach((c, i) => {
        M.HEAPU8.set(c.a, aa + i * esz);
        M.HEAPU8.set(c.b, ab + i * esz);
      });
      M.HEAPU8.fill(0, ad, ad + esz * n);
      M.HEAPU32[afl >> 2] = 0;
      const st = w(dev, set.fmt, aa, ab, ad, n, afl);
      if (st !== 0)
        throw new Error(`${set.name}: cftw_${MM_CALL[fn]} over ${n} ` +
                        `elements returned ${C.strerror(st)}`);
      cases.forEach((c, i) => {
        const got = M.HEAPU8.slice(ad + i * esz, ad + (i + 1) * esz);
        if (hexOfBytes(got) !== hexOfBytes(c.d))
          throw new Error(`${set.name}:${c.lineno}: ${fn} disagrees with ` +
                          `itself between n == 1 and n == ${n} - element ` +
                          `${i} is ${hexOfBytes(got)}, the scalar call and ` +
                          `the file both say ${hexOfBytes(c.d)}`);
      });
      const arrFlags = M.HEAPU32[afl >> 2] >>> 0;
      if (arrFlags !== unionFlags)
        throw new Error(`${set.name}: ${fn} over ${n} elements raised 0x` +
                        `${arrFlags.toString(16)}, the union over the ` +
                        `scalar calls is 0x${unionFlags.toString(16)}`);
    } finally {
      for (const p of [aa, ab, ad, afl]) M._free(p);
    }
  }
  return checked;
}

/** The formatOf sets (5.4.1). The one family whose operands and result
 *  are DIFFERENT WIDTHS in the same call, so every buffer below is
 *  sized from the format it belongs to - and the record's own sfmt and
 *  dfmt are checked against the file's name, because with two formats
 *  there is a pairing to get wrong. */
function driveFormatOfSet(set, text) {
  const sesz = C.formatSize(set.sfmt), desz = C.formatSize(set.dfmt);
  const byFn = new Map();
  let lineno = 0;
  for (const line of text.split("\n")) {
    lineno++;
    if (!line.trim()) continue;
    const c = JSON.parse(line);
    const arity = FO_ARITY[c.fn];
    if (arity === undefined)
      throw new Error(`${set.name}:${lineno}: unknown formatOf operation ` +
                      `"${c.fn}" - 5.4.1 names six`);
    if (c.sfmt !== set.sName || c.dfmt !== set.dName)
      throw new Error(`${set.name}:${lineno}: the case says ${c.sfmt} -> ` +
                      `${c.dfmt} in a file named for ${set.sName} -> ` +
                      `${set.dName}`);
    if (c.rnd !== set.rndName)
      throw new Error(`${set.name}:${lineno}: attribute "${c.rnd}" in a ` +
                      `${set.rndName} set`);
    if ((arity >= 2) !== (c.b !== undefined) ||
        (arity >= 3) !== (c.c !== undefined))
      throw new Error(`${set.name}:${lineno}: formatOf-${c.fn} reads ` +
                      `${arity} operand(s), the case carries ` +
                      `${1 + (c.b !== undefined) + (c.c !== undefined)}`);
    if (!byFn.has(c.fn)) byFn.set(c.fn, []);
    byFn.get(c.fn).push({
      lineno,
      a: bytesOfHex(c.a, sesz),
      b: arity >= 2 ? bytesOfHex(c.b, sesz) : null,
      c: arity >= 3 ? bytesOfHex(c.c, sesz) : null,
      d: bytesOfHex(c.d, desz),
      flags: c.flags >>> 0,
    });
  }
  if (!byFn.size) throw new Error(`${set.name}: no cases`);

  let checked = 0;
  for (const [fn, cases] of byFn) {
    const w = C[FO_CALL[fn]];
    const arity = FO_ARITY[fn];
    // (dev, sfmt, dfmt, rnd, a[, b[, c]], d, n, flags, bus) - the bus
    // word is real for the widening direction, which issues a device
    // pass underneath, and reads back 0 for the narrowing one.
    const call = (pa, pb, pc, pd, n, pfl, pbus) => arity === 1
      ? w(dev, set.sfmt, set.dfmt, set.rnd, pa, pd, n, pfl, pbus)
      : (arity === 2
         ? w(dev, set.sfmt, set.dfmt, set.rnd, pa, pb, pd, n, pfl, pbus)
         : w(dev, set.sfmt, set.dfmt, set.rnd, pa, pb, pc, pd, n, pfl, pbus));

    const pa = M._malloc(sesz), pb = M._malloc(sesz), pc = M._malloc(sesz);
    const pd = M._malloc(desz), pfl = M._malloc(4), pbus = M._malloc(4);
    let unionFlags = 0;
    try {
      for (const k of cases) {
        M.HEAPU8.set(k.a, pa);
        if (k.b) M.HEAPU8.set(k.b, pb);
        if (k.c) M.HEAPU8.set(k.c, pc);
        M.HEAPU8.fill(0, pd, pd + desz);
        M.HEAPU32[pfl >> 2] = 0;
        M.HEAPU32[pbus >> 2] = 0;
        const st = call(pa, pb, pc, pd, 1, pfl, pbus);
        if (st !== 0)
          throw new Error(`${set.name}:${k.lineno}: cftw_${FO_CALL[fn]} ` +
                          `returned ${C.strerror(st)}`);
        const got = M.HEAPU8.slice(pd, pd + desz);
        const gotFlags = M.HEAPU32[pfl >> 2] >>> 0;
        if (hexOfBytes(got) !== hexOfBytes(k.d) || gotFlags !== k.flags)
          throw new Error(
            `${set.name}:${k.lineno}: formatOf-${fn} ${set.sName} -> ` +
            `${set.dName} ${set.rndName}\n` +
            `        a        ${hexOfBytes(k.a)}\n` +
            (k.b ? `        b        ${hexOfBytes(k.b)}\n` : "") +
            (k.c ? `        c        ${hexOfBytes(k.c)}\n` : "") +
            `        expected ${hexOfBytes(k.d)} flags 0x` +
            `${k.flags.toString(16).padStart(2, "0")}\n` +
            `        got      ${hexOfBytes(got)} flags 0x` +
            `${gotFlags.toString(16).padStart(2, "0")}`);
        unionFlags |= gotFlags;
        checked++;
      }
    } finally {
      for (const p of [pa, pb, pc, pd, pfl, pbus]) M._free(p);
    }

    const n = cases.length;
    const aa = M._malloc(sesz * n), ab = M._malloc(sesz * n);
    const ac = M._malloc(sesz * n), ad = M._malloc(desz * n);
    const afl = M._malloc(4), abus = M._malloc(4);
    try {
      cases.forEach((k, i) => {
        M.HEAPU8.set(k.a, aa + i * sesz);
        if (k.b) M.HEAPU8.set(k.b, ab + i * sesz);
        if (k.c) M.HEAPU8.set(k.c, ac + i * sesz);
      });
      M.HEAPU8.fill(0, ad, ad + desz * n);
      M.HEAPU32[afl >> 2] = 0;
      M.HEAPU32[abus >> 2] = 0;
      const st = call(aa, ab, ac, ad, n, afl, abus);
      if (st !== 0)
        throw new Error(`${set.name}: cftw_${FO_CALL[fn]} over ${n} ` +
                        `elements returned ${C.strerror(st)}`);
      cases.forEach((k, i) => {
        const got = M.HEAPU8.slice(ad + i * desz, ad + (i + 1) * desz);
        if (hexOfBytes(got) !== hexOfBytes(k.d))
          throw new Error(`${set.name}:${k.lineno}: formatOf-${fn} ` +
                          `disagrees with itself between n == 1 and ` +
                          `n == ${n} - element ${i} is ${hexOfBytes(got)}, ` +
                          `the scalar call and the file both say ` +
                          `${hexOfBytes(k.d)}`);
      });
      const arrFlags = M.HEAPU32[afl >> 2] >>> 0;
      if (arrFlags !== unionFlags)
        throw new Error(`${set.name}: formatOf-${fn} over ${n} elements ` +
                        `raised 0x${arrFlags.toString(16)}, the union over ` +
                        `the scalar calls is 0x${unionFlags.toString(16)}`);
    } finally {
      for (const p of [aa, ab, ac, ad, afl, abus]) M._free(p);
    }
  }
  return checked;
}

// The six families of step 5, each with the sets it reads and the
// driver that calls its wrappers. All six have to be present: a run
// that drove five of them and said nothing about the sixth would be
// the half-step in miniature.
const STEP5 = [
  { label: "the thirty-nine transcendentals", unit: "transcendental",
    sets: TRANSCEND_SETS, drive: driveTranscendSet },
  { label: "the augmented arithmetic (9.5)", unit: "augmented",
    sets: AUGMENTED_SETS, drive: driveAugmentedSet },
  { label: "the reductions and scaled products (9.4)", unit: "reduction",
    sets: REDUCE_SETS, drive: driveReduceSet },
  { label: "the character conversions (5.12) and payloads (9.7)",
    unit: "character", sets: CHARACTER_SETS, drive: driveCharacterSet },
  { label: "the magnitude forms of minimum and maximum (9.6)",
    unit: "minmaxmag", sets: MINMAXMAG_SETS, drive: driveMinMaxMagSet },
  { label: "the formatOf arithmetic (5.4.1), all sixteen ordered pairs",
    unit: "formatof", sets: FORMATOF_SETS, drive: driveFormatOfSet },
];

const missingFamily = STEP5.filter((f) =>
  !f.sets.every((s) => existsSync(join(vdir, s.name))));
if (missingFamily.length) {
  console.log(`\nsets missing from ${vdir}: ` +
              `${missingFamily.map((f) => f.unit).join(", ")} - those ` +
              `wrappers were NOT driven.`);
  console.log("Steps 1-4 stand. `make vectors` from the repo root writes " +
              "them; the containerized build cannot (no mpmath in the " +
              "pinned image), so build/vectors never has them.");
  bad("the ABI 0.7 wrappers were not fully exercised - not a full pass");
  console.log(failed ? "\nVERIFY FAILED" : "\nVERIFY OK");
  process.exit(1);
}

console.log("\nstep 5  (cftw_* called from JavaScript, per case then as " +
            "arrays where the C batches)");
let tTotal = 0, tClean = 0, tSets = 0;
const perFamily = [];
for (const family of STEP5) {
  console.log(`\n  ${family.label}`);
  let fTotal = 0, fClean = 0;
  for (const set of family.sets) {
    const text = readFileSync(join(vdir, set.name), "utf8");
    let n = 0, err = null;
    try { n = family.drive(set, text); }
    catch (e) { err = e; }
    fTotal += n;
    const shown = n.toLocaleString("en-US").padStart(7);
    if (!err) {
      fClean++;
      console.log(`    ${set.name.padEnd(26)} ${shown}  all matching`);
    } else {
      failed = true;
      console.log(`    ${set.name.padEnd(26)} ${shown}  FAILED`);
      console.log(`        ${err.message}`);
    }
  }
  tTotal += fTotal;
  tClean += fClean;
  tSets += family.sets.length;
  perFamily.push({ unit: family.unit, cases: fTotal, clean: fClean,
                   sets: family.sets.length });
  if (fClean !== family.sets.length || fTotal === 0)
    failed = true;
}

console.log("");
for (const f of perFamily)
  console.log(`  ${f.unit.padEnd(16)} ${f.cases.toLocaleString("en-US")
    .padStart(9)} cases over ${f.clean}/${f.sets} sets`);
console.log("");
if (tClean === tSets && tTotal > 0)
  ok(`${tTotal.toLocaleString("en-US")} cases over ${tClean} sets driven ` +
     `through the wrappers themselves, encodings, sequences, scales and ` +
     `flags exact`);
else
  bad(`${tClean} of ${tSets} sets clean through the wrappers, ` +
      `${tTotal.toLocaleString("en-US")} cases`);

console.log(failed ? "\nVERIFY FAILED" : "\nVERIFY OK");
process.exit(failed ? 1 : 0);
