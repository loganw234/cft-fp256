#!/usr/bin/env node
// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// Check bindings/wasm/demos.html without a browser.
//
//     node bindings/wasm/verify_demos.mjs            # the whole check
//     node bindings/wasm/verify_demos.mjs --record   # re-record the chains
//     node bindings/wasm/verify_demos.mjs --panel zoom
//     node bindings/wasm/verify_demos.mjs --no-native
//
// WHAT IT CHECKS, and why each one is worth a line:
//
//   1  THE MODULE. The bytes embedded in demos.html are walked back
//      out of the page's JavaScript string literal and hashed. They
//      must equal bindings/node/cft_node.wasm - the module
//      conformance.html embeds and three documents quote. A demos page
//      running a DIFFERENT module would still produce chains; they
//      would just be a claim about some other build.
//
//   2  THE COMPUTE CORE. The core spliced into the page must be
//      demos_core.js byte for byte, because this script drives
//      demos_core.js and reports on demos.html. Without this line the
//      two could drift and the report would be about the wrong file.
//
//   3  THE CHAINS, three ways. For each of the eleven configurations:
//      run the NATIVE tool with the flags the page prints, run the
//      browser's compute core over the committed wasm module, and
//      compare both against the chain recorded in demos_chains.json.
//      All three must agree. --no-native drops the tool run (and says
//      so); --record writes the file instead of checking it.
//
// The native tools are the reference for every bit. If the core and a
// tool disagree, the core is wrong until shown otherwise.
//
// BUILDING THE TOOLS. `make -C host cft-collatz cft-zoom cft-orbits
// cft-enclose cft-mersenne` builds all five. On this Windows host that
// is, with mingw64 gcc on PATH:
//
//     make -C host CC=gcc OS=Windows_NT TMP=/tmp TEMP=/tmp \
//          cft-collatz.exe cft-zoom.exe cft-orbits.exe \
//          cft-enclose.exe cft-mersenne.exe
//
// This script does not build them: a checker that silently rebuilds
// its own reference is a checker that can hide a stale one.

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { hostname } from "node:os";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..", "..");
const PAGE = join(HERE, "demos.html");
const CORE = join(HERE, "demos_core.js");
const CHAINS = join(HERE, "demos_chains.json");
const MODULE_WASM = join(ROOT, "bindings", "node", "cft_node.wasm");
const MODULE_JS = join(ROOT, "bindings", "node", "cft_node.js");

const argv = process.argv.slice(2);
const has = (f) => argv.includes(f);
const valOf = (f, d) => {
  const i = argv.indexOf(f);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};
const RECORD = has("--record");
const NO_NATIVE = has("--no-native");
const ONLY_PANEL = valOf("--panel", null);
const ONLY_RUN = valOf("--run", null);

let failed = false;
const ok = (m) => console.log(`  ok    ${m}`);
const bad = (m) => { failed = true; console.log(`  FAIL  ${m}`); };
const note = (m) => console.log(`        ${m}`);
const sha256 = (b) => createHash("sha256").update(b).digest("hex");

// ---------------------------------------------------------------------
// 1. the module the page embeds
//
// emcc's SINGLE_FILE output is findWasmBinary(){return binaryDecode(
// '...')} - one JS string literal holding one byte per code unit. The
// literal is WALKED rather than evaluated: this script reads a build
// product, and a build product is data. bindings/wasm/verify.mjs does
// the same for conformance.html; the two must stay in step, and the
// sha256 below is what would notice if they did not.
// ---------------------------------------------------------------------
function extractWasm(html) {
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
    throw new Error("binaryDecode( is not followed by a string literal");
  const ESC = { n: 10, r: 13, t: 9, b: 8, f: 12, v: 11, 0: 0 };
  const out = [];
  for (;;) {
    const c = html[i++];
    if (c === undefined) throw new Error("unterminated wasm string literal");
    if (c === quote) break;
    if (c !== "\\") {
      const cc = html.codePointAt(i - 1);
      if (cc > 0xff) throw new Error(`code unit ${cc} > 255 in the literal`);
      out.push(cc);
      continue;
    }
    const e = html[i++];
    if (e === "x") { out.push(parseInt(html.slice(i, i + 2), 16)); i += 2; }
    else if (e === "u") {
      const cc = parseInt(html.slice(i, i + 4), 16);
      if (cc > 0xff) throw new Error(`\\u${html.slice(i, i + 4)} > 255`);
      out.push(cc); i += 4;
    } else if (e in ESC) out.push(ESC[e]);
    else out.push(e.charCodeAt(0));
  }
  return Uint8Array.from(out);
}

/** The text of one <script type="text/plain" id="..."> block. The page
 *  carries the loader, the core and the driver this way so that the
 *  browser does not execute them on the main thread - it hands them to
 *  a Worker - and so that this script can read exactly what shipped. */
function extractBlock(html, id) {
  const open = `<script type="text/plain" id="${id}">`;
  const at = html.indexOf(open);
  if (at < 0) throw new Error(`no <script id="${id}"> block in the page`);
  const from = at + open.length;
  const to = html.indexOf("</scr" + "ipt>", from);
  if (to < 0) throw new Error(`the ${id} block is unterminated`);
  return html.slice(from, to);
}

const moduleWasm = readFileSync(MODULE_WASM);
const moduleHash = sha256(moduleWasm);
const coreSrc = readFileSync(CORE, "utf8");

console.log(`root    ${ROOT}`);
console.log(`module  ${MODULE_WASM}`);
console.log(`        ${moduleWasm.length.toLocaleString("en-US")} bytes, ` +
            `sha256 ${moduleHash}`);

let pageCore = null;
if (existsSync(PAGE)) {
  console.log(`page    ${PAGE}`);
  const raw = readFileSync(PAGE);
  const html = raw.toString("utf8");
  console.log(`        ${raw.length.toLocaleString("en-US")} bytes, ` +
              `sha256 ${sha256(raw)}`);
  console.log("\n== 1. the module the page embeds ==");
  try {
    const pageWasm = extractWasm(html);
    const pageHash = sha256(pageWasm);
    note(`page module ${pageWasm.length.toLocaleString("en-US")} bytes, ` +
         `sha256 ${pageHash}`);
    if (pageHash === moduleHash)
      ok("demos.html embeds bindings/node/cft_node.wasm, byte for byte - " +
         "the module conformance.html embeds");
    else
      bad(`demos.html embeds a DIFFERENT module (${pageHash}) than ` +
          `bindings/node/cft_node.wasm (${moduleHash})`);
  } catch (err) {
    bad(`could not read the page's module: ${err.message}`);
  }

  console.log("\n== 2. the compute core the page embeds ==");
  try {
    pageCore = extractBlock(html, "cft-core-src");
    if (pageCore === coreSrc)
      ok("demos.html carries demos_core.js byte for byte, so this check " +
         "is about the page and not about a lookalike");
    else
      bad(`the page's core (sha256 ${sha256(Buffer.from(pageCore))}) is not ` +
          `demos_core.js (sha256 ${sha256(Buffer.from(coreSrc))}) - ` +
          `rebuild the page`);
  } catch (err) {
    bad(`could not read the page's core: ${err.message}`);
  }
} else {
  console.log(`page    ${PAGE} is not built yet - checking the core alone`);
  console.log("\n== 1-2. the page ==");
  note("skipped: run `bash bindings/wasm/build_demos.sh` to build it");
}

// ---------------------------------------------------------------------
// The compute core, loaded into this process over the committed module.
// ---------------------------------------------------------------------
const require = createRequire(import.meta.url);
const createCftModule = require(MODULE_JS);
const M = await createCftModule({ wasmBinary: moduleWasm });
vm.runInThisContext(coreSrc, { filename: "demos_core.js" });
const D = globalThis.CftDemos;
if (!D) { console.log("  FAIL  demos_core.js defined no CftDemos"); process.exit(1); }

// ---------------------------------------------------------------------
// 3. the chains
// ---------------------------------------------------------------------
const EXE = process.platform === "win32" ? ".exe" : "";
const TOOL_OF = {
  collatz: "cft-collatz", zoom: "cft-zoom", orbits: "cft-orbits",
  enclose: "cft-enclose", mersenne: "cft-mersenne",
};
// Where each tool prints each chain. One regex per chain name, so a
// tool that grows a second chain is a line here rather than a guess.
const CHAIN_RE = {
  chain: /^\s*chain\s+([0-9a-f]{64})\s*$/m,
  orbit: /^\s*orbit chain\s+([0-9a-f]{64})\s*$/m,
  pixels: /^\s*pixel chain\s+([0-9a-f]{64})\s*$/m,
};

function runNative(panel, command) {
  // The command the page prints is "./host/cft-x --flags ...". Split it
  // back into an argv rather than handing it to a shell.
  const parts = command.split(/\s+/);
  const exe = join(ROOT, "host", TOOL_OF[panel] + EXE);
  if (!existsSync(exe))
    throw new Error(`${exe} is not built. Build the five tools first:\n` +
      `        make -C host CC=gcc OS=Windows_NT TMP=/tmp TEMP=/tmp \\\n` +
      `             cft-collatz${EXE} cft-zoom${EXE} cft-orbits${EXE} ` +
      `cft-enclose${EXE} cft-mersenne${EXE}`);
  const out = execFileSync(exe, parts.slice(1), {
    cwd: ROOT, encoding: "utf8", maxBuffer: 256 * 1024 * 1024,
  });
  return out;
}

function chainsFrom(text, names) {
  const got = {};
  for (const n of names) {
    const m = CHAIN_RE[n].exec(text);
    if (!m) throw new Error(`the tool printed no "${n}" chain`);
    got[n] = m[1];
  }
  return got;
}

// The tools' report lines worth recording beside a chain: what the run
// cost and what it issued. The second alternative catches cft-zoom's
// continuation line, which starts with a number because the label
// above it covers two rows.
function reportLines(text) {
  return text.split("\n")
    .filter((l) => /^\s*(time|throughput|library calls|limb products|element ops|elementwise|pixel work|opcode issues|carry passes)\b/.test(l) ||
                   /pixel-iterations\/s/.test(l))
    .map((l) => l.trim());
}

function runCore(panel, runName, cfg) {
  const C = D.createCft(M);
  const t0 = Date.now();
  try {
    const job = D.PANELS[panel].create(C, cfg);
    for (;;) { const r = job.step(); if (r.done) break; }
    const res = job.result();
    res.seconds = (Date.now() - t0) / 1000;
    res.rate = res.seconds > 0 ? res.work / res.seconds : 0;
    return res;
  } finally {
    try { C.close(C.dev); C.freeAll(); } catch (e) { /* teardown */ }
  }
}

const runs = D.allRuns().filter((r) =>
  (!ONLY_PANEL || r.panel === ONLY_PANEL) && (!ONLY_RUN || r.run === ONLY_RUN));
if (!runs.length) {
  console.log("  FAIL  no run matched --panel/--run");
  process.exit(1);
}

let recorded = null;
if (!RECORD) {
  if (!existsSync(CHAINS)) {
    console.log(`\n  FAIL  ${CHAINS} is missing - run with --record first`);
    process.exit(1);
  }
  recorded = JSON.parse(readFileSync(CHAINS, "utf8"));
}

console.log(`\n== 3. the chains (${runs.length} configuration${runs.length === 1 ? "" : "s"}` +
            `${NO_NATIVE ? ", --no-native" : ""}) ==`);

const fresh = [];
for (const r of runs) {
  console.log(`\n  ${r.panel}/${r.run}`);
  note(r.command);

  let nativeChains = null, nativeReport = [], nativeSeconds = null;
  if (!NO_NATIVE) {
    const t0 = Date.now();
    let text;
    try {
      text = runNative(r.panel, r.command);
    } catch (err) {
      bad(`the native tool did not run: ${err.message}`);
      continue;
    }
    nativeSeconds = (Date.now() - t0) / 1000;
    try {
      nativeChains = chainsFrom(text, r.chains);
    } catch (err) {
      bad(`could not read the tool's chain: ${err.message}`);
      continue;
    }
    nativeReport = reportLines(text);
    for (const l of nativeReport) note("tool: " + l);
  }

  let res;
  try {
    res = runCore(r.panel, r.run, r.cfg);
  } catch (err) {
    bad(`the compute core threw: ${err.message}`);
    continue;
  }
  note(`core: ${res.seconds.toFixed(3)} s, ` +
       `${Math.round(res.rate).toLocaleString("en-US")} ${res.workUnit}/s, ` +
       `${res.stats.calls.toLocaleString("en-US")} library calls, ` +
       `flags 0x${res.stats.flags.toString(16).padStart(2, "0")}`);

  const row = {
    panel: r.panel, run: r.run, command: r.command, cfg: r.cfg,
    chains: nativeChains || (recorded ? (recorded.runs.find(
      (x) => x.panel === r.panel && x.run === r.run) || {}).chains : null),
    native: { seconds: nativeSeconds, report: nativeReport },
    core: { seconds: res.seconds, rate: res.rate, unit: res.workUnit,
            calls: res.stats.calls },
  };
  fresh.push(row);

  for (const cname of r.chains) {
    const got = res.chains[cname];
    const want = recorded
      ? ((recorded.runs.find((x) => x.panel === r.panel && x.run === r.run)
          || { chains: {} }).chains || {})[cname]
      : null;
    if (nativeChains) {
      if (got === nativeChains[cname])
        ok(`${cname}: the core reproduced the tool's chain ${got}`);
      else
        bad(`${cname}: core ${got} != tool ${nativeChains[cname]}`);
    }
    if (want !== null && want !== undefined) {
      if (got === want)
        ok(`${cname}: matches the recorded chain in demos_chains.json`);
      else
        bad(`${cname}: core ${got} != recorded ${want}`);
      if (nativeChains && nativeChains[cname] !== want)
        bad(`${cname}: the tool now prints ${nativeChains[cname]}, and ` +
            `demos_chains.json records ${want} - re-record`);
    }
  }
}

if (RECORD) {
  if (NO_NATIVE) {
    console.log("\n  FAIL  --record needs the native tools; drop --no-native");
    process.exit(1);
  }
  const out = {
    recorded: new Date().toISOString().slice(0, 10),
    host: hostname(),
    module_sha256: moduleHash,
    core_sha256: sha256(Buffer.from(coreSrc)),
    build_command:
      "make -C host CC=gcc OS=Windows_NT TMP=/tmp TEMP=/tmp " +
      `cft-collatz${EXE} cft-zoom${EXE} cft-orbits${EXE} ` +
      `cft-enclose${EXE} cft-mersenne${EXE}`,
    runs: fresh,
  };
  writeFileSync(CHAINS, JSON.stringify(out, null, 2) + "\n");
  console.log(`\nwrote ${CHAINS}: ${fresh.length} runs, ` +
              `${fresh.reduce((a, r) => a + Object.keys(r.chains).length, 0)} chains`);
}

console.log("\n" + (failed
  ? "VERDICT: FAILED - see the FAIL lines above"
  : "VERDICT: the browser's compute core produced the C tools' chains, " +
    "over the module the conformance page embeds"));
process.exit(failed ? 1 : 0);
