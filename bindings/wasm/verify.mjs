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
// It checks four things, in the order that makes the last one mean
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
//      published sets rather than the embedded sample.
//
// The loader comes from bindings/node/ if the package is there, else
// from bindings/wasm/build/ after a build.sh run. Vectors come from
// the directory named on the command line, else vectors/out (`make
// vectors` from the repo root), else the build's own copy.

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
for (const needed of ["cftw_run", "cftw_conformance", "cftw_convert",
                      "cftw_rint", "cftw_class", "cftw_rem"]) {
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
const stray = readdirSync(vdir).filter((n) => n.endsWith(".jsonl") &&
  !CANONICAL.includes(n));
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
  conformance: M.cwrap("cftw_conformance", num, [num, str, num, num, num, num]),
};

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

console.log("\nreplay  (one cft_conformance() call per set, full files)");
let total = 0, clean = 0;
for (const name of CANONICAL) {
  const text = readFileSync(join(vdir, name), "utf8");
  const r = replayOneSet(name, text);
  total += r.cases;
  const n = r.cases.toLocaleString("en-US").padStart(7);
  if (r.status === 0 && r.cases > 0) {
    clean++;
    console.log(`  ${name.padEnd(16)} ${n}  all matching`);
  } else {
    failed = true;
    console.log(`  ${name.padEnd(16)} ${n}  FAILED: ${C.strerror(r.status)}`);
    console.log(r.report.trim().split("\n").map((l) => "      " + l).join("\n"));
  }
}

// A run that checked nothing must not read as a pass - the rule
// cft_conformance applies to its own summary, applied here.
console.log("");
if (clean === CANONICAL.length && total > 0)
  ok(`${total.toLocaleString("en-US")} cases over ${clean} sets, ` +
     `library matches the vectors exactly`);
else
  bad(`${clean} of ${CANONICAL.length} sets clean, ` +
      `${total.toLocaleString("en-US")} cases`);

console.log(failed ? "\nVERIFY FAILED" : "\nVERIFY OK");
process.exit(failed ? 1 : 0);
