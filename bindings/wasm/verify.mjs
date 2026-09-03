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
//      accepts the twenty transcendental sets as well, and they are
//      replayed here for the same reason.
//   5  The nine phase-1 transcendentals, driven THROUGH THEIR
//      WRAPPERS from JavaScript. Step 4 would pass without them: the
//      cft_conformance inside the module has replayed the
//      transcendental sets since the module was first built from the
//      0.3 sources, and it dispatches them internally, in C, never
//      touching cftw_exp and friends. For a day that is exactly what
//      the module was - ABI 0.3 by its own report, with no entry
//      point a JavaScript caller could reach (docs/COMPATIBILITY.md
//      called it the half-step). So this step reads the same vector
//      files itself, calls cftw_exp / cftw_expm1 / cftw_exp2 /
//      cftw_log / cftw_log1p / cftw_log2 / cftw_log10 / cftw_pow /
//      cftw_hypot one element at a time for exact per-case flags,
//      then once per family as an array, and compares encodings and
//      flags against the file. A wrapper with its operands swapped,
//      or missing, fails here and nowhere else.
//
// The loader comes from bindings/node/ if the package is there, else
// from bindings/wasm/build/ after a build.sh run. Vectors come from
// the directory named on the command line, else vectors/out (`make
// vectors` from the repo root), else the build's own copy. Step 5
// needs the transcendental sets, which the containerized build does
// NOT generate (its image carries no mpmath), so `make vectors` from
// the repo root is what puts them in reach; without them step 5 says
// it did not run rather than reporting a pass.

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
// the way down.
const TRANSCEND_UNARY = ["exp", "expm1", "exp2", "log", "log1p",
                         "log2", "log10"];
const TRANSCEND_BINARY = ["pow", "hypot"];
const TRANSCEND_SETS = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    TRANSCEND_SETS.push({
      name: r === "rne" ? `${f}-transcend.jsonl`
                        : `${f}-transcend-${r}.jsonl`,
      fmt: FORMATS.indexOf(f), rnd: ROUNDINGS.indexOf(r), rndName: r,
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
// version number: 0.1's cft_run, 0.2's clause-5 set, 0.3's nine. The
// nine are listed in full because a module can carry eight of them and
// still report 0.3, which is the failure mode this file is here for.
const NEEDED = ["cftw_run", "cftw_conformance", "cftw_convert",
                "cftw_rint", "cftw_class", "cftw_rem",
                ...TRANSCEND_UNARY.map((f) => `cftw_${f}`),
                ...TRANSCEND_BINARY.map((f) => `cftw_${f}`)];
for (const needed of NEEDED) {
  if (!exported.includes(needed)) bad(`the module does not export ${needed}`);
}

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
const KNOWN = new Set([...CANONICAL, ...TRANSCEND_SETS.map((s) => s.name)]);
const stray = readdirSync(vdir).filter((n) => n.endsWith(".jsonl") &&
  !KNOWN.has(n));
if (stray.length) console.log(`        (ignoring ${stray.join(", ")})`);

const { default: createCftModule } = await import(pathToFileURL(loaderJs));
// The page's module, not the loader's file: same bytes by step 3, and
// this way the replay is literally of what is committed.
const M = await createCftModule({ wasmBinary: pageWasm });

const num = "number", str = "string";
const C = {
  strerror: M.cwrap("cftw_strerror", str, [num]),
  openSoftware: M.cwrap("cftw_open_software", num, [num]),
  capsBackend: M.cwrap("cftw_caps_backend", str, [num]),
  formatSize: M.cwrap("cftw_format_size", num, [num]),
  conformance: M.cwrap("cftw_conformance", num, [num, str, num, num, num, num]),
};
// The nine, by name. Seven take (dev, fmt, rnd, a, d, n, flags) and two
// take (dev, fmt, rnd, a, b, d, n, flags) - no bus word either way,
// because a host operation issues no device pass (cft.h).
for (const fn of TRANSCEND_UNARY)
  C[fn] = M.cwrap(`cftw_${fn}`, num, [num, num, num, num, num, num, num]);
for (const fn of TRANSCEND_BINARY)
  C[fn] = M.cwrap(`cftw_${fn}`, num,
                  [num, num, num, num, num, num, num, num]);

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
// reason to accept them; a directory that has only the twenty opcode
// sets (the containerized build's own copy) replays those and says the
// others were absent, rather than failing on a file nobody wrote.
const present = [...CANONICAL,
                 ...TRANSCEND_SETS.map((s) => s.name)]
  .filter((n) => existsSync(join(vdir, n)));

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
// 5. the nine, through their own wrappers
//
// Step 4 dispatches the transcendentals inside C and would be green
// with no cftw_* wrapper for any of them at all - it was, for a day.
// This step is the one that fails when the JavaScript surface is
// missing or wrong, so it reads the sets here and calls the exports.
// Per case first, because the flag word in the file is that case's,
// then once per family as an array, because a wrapper that only works
// at n == 1 would be a wrapper that does not work.
// ---------------------------------------------------------------------

function bytesOfHex(hex, esz) {
  let v = BigInt(hex);
  const out = new Uint8Array(esz);
  for (let i = 0; i < esz; i++) { out[i] = Number(v & 0xffn); v >>= 8n; }
  if (v !== 0n) throw new Error(`${hex} does not fit ${esz} bytes`);
  return out;
}

function hexOfBytes(bytes) {
  let s = "0x";
  for (let i = bytes.length - 1; i >= 0; i--)
    s += bytes[i].toString(16).padStart(2, "0");
  return s;
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
    if (!binary && !TRANSCEND_UNARY.includes(c.fn))
      throw new Error(`${set.name}:${lineno}: unknown function "${c.fn}" - ` +
                      `this script's table and cft.h have diverged`);
    if (binary !== (c.b !== undefined))
      throw new Error(`${set.name}:${lineno}: ${c.fn} is ` +
                      `${binary ? "binary" : "unary"} but the case ` +
                      `${c.b !== undefined ? "carries" : "omits"} b`);
    if (!byFn.has(c.fn)) byFn.set(c.fn, []);
    byFn.get(c.fn).push({
      lineno,
      a: bytesOfHex(c.a, esz),
      b: binary ? bytesOfHex(c.b, esz) : null,
      d: bytesOfHex(c.d, esz),
      flags: c.flags >>> 0,
    });
  }
  if (!byFn.size) throw new Error(`${set.name}: no cases`);

  let checked = 0;
  for (const [fn, cases] of byFn) {
    const binary = TRANSCEND_BINARY.includes(fn);
    const call = (pa, pb, pd, n, pfl) => binary
      ? C[fn](dev, set.fmt, set.rnd, pa, pb, pd, n, pfl)
      : C[fn](dev, set.fmt, set.rnd, pa, pd, n, pfl);

    // per element: the flag word in the file belongs to this case, and
    // an array call would only ever show their union
    const pa = M._malloc(esz), pb = M._malloc(esz);
    const pd = M._malloc(esz), pfl = M._malloc(4);
    let unionFlags = 0;
    try {
      for (const c of cases) {
        M.HEAPU8.set(c.a, pa);
        if (c.b) M.HEAPU8.set(c.b, pb);
        M.HEAPU8.fill(0, pd, pd + esz);
        M.HEAPU32[pfl >> 2] = 0;
        const st = call(pa, c.b ? pb : 0, pd, 1, pfl);
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

    // and once as one array of the whole family
    const n = cases.length;
    const aa = M._malloc(esz * n), ab = M._malloc(esz * n);
    const ad = M._malloc(esz * n), afl = M._malloc(4);
    try {
      cases.forEach((c, i) => {
        M.HEAPU8.set(c.a, aa + i * esz);
        if (c.b) M.HEAPU8.set(c.b, ab + i * esz);
      });
      M.HEAPU8.fill(0, ad, ad + esz * n);
      M.HEAPU32[afl >> 2] = 0;
      const st = call(aa, binary ? ab : 0, ad, n, afl);
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
    }
  }
  return checked;
}

const haveTranscend = TRANSCEND_SETS.every((s) =>
  existsSync(join(vdir, s.name)));
if (!haveTranscend) {
  console.log(`\nno transcendental sets in ${vdir} - the nine were NOT ` +
              `driven.`);
  console.log("Steps 1-4 stand. `make vectors` from the repo root writes " +
              "them; the containerized build cannot (no mpmath in the " +
              "pinned image), so build/vectors never has them.");
  bad("the ABI 0.3 wrappers were not exercised - this is not a full pass");
  console.log(failed ? "\nVERIFY FAILED" : "\nVERIFY OK");
  process.exit(1);
}

console.log("\nthe nine  (cftw_* called from JavaScript, per case then " +
            "as arrays)");
let tTotal = 0, tClean = 0;
for (const set of TRANSCEND_SETS) {
  const text = readFileSync(join(vdir, set.name), "utf8");
  let n = 0, err = null;
  try { n = driveTranscendSet(set, text); }
  catch (e) { err = e; }
  tTotal += n;
  const shown = n.toLocaleString("en-US").padStart(7);
  if (!err) {
    tClean++;
    console.log(`  ${set.name.padEnd(26)} ${shown}  all matching`);
  } else {
    failed = true;
    console.log(`  ${set.name.padEnd(26)} ${shown}  FAILED`);
    console.log(`      ${err.message}`);
  }
}

console.log("");
if (tClean === TRANSCEND_SETS.length && tTotal > 0)
  ok(`${tTotal.toLocaleString("en-US")} transcendental cases over ` +
     `${tClean} sets, through the wrappers, encodings and flags exact`);
else
  bad(`${tClean} of ${TRANSCEND_SETS.length} transcendental sets clean, ` +
      `${tTotal.toLocaleString("en-US")} cases`);

console.log(failed ? "\nVERIFY FAILED" : "\nVERIFY OK");
process.exit(failed ? 1 : 0);
