// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// node page_datapath.mjs fma_probe.html - the probe page's data path outside a browser: its main
// script evaluated in node (22 or later) with a stub for its two DOM elements and no WebGPU; then
// its own unpack() (base64, gzip, every part's SHA-256 against the page's constants), corpus()
// on the four subsets, and compare() against each subset's own expected values (0 lanes must
// differ) and against one flipped expected bit (1 must). Nothing here touches a GPU or the page's
// run(), so the page itself stays NOT RUN. Last line OK (exit 0) or the first failure (exit 1).
import { readFileSync } from "node:fs";
import vm from "node:vm";

const html = readFileSync(process.argv[2] || "fma_probe.html", "utf8");
const blob = html.match(/<script id="blob" type="application\/octet-stream">([\s\S]*?)<\/script>/)[1];
const main = html.match(/<script>\n("use strict";[\s\S]*?)<\/script>/)[1];
const els = { blob: { textContent: blob }, record: { textContent: "" }, go: { addEventListener() {} } };
const ctx = vm.createContext({
  document: { getElementById: id => els[id] }, console, atob, TextDecoder, Blob, Response,
  DecompressionStream, DataView, Uint8Array, crypto: globalThis.crypto, JSON, Number, Math, Error,
});
vm.runInContext(main, ctx);                     // the script as the page has it; "go" is a stub
const fail = m => { console.log(`page_datapath: FAILED: ${m}`); process.exit(1); };
try {
  const parts = await vm.runInContext("unpack()", ctx);
  const names = Object.keys(parts).sort();
  console.log(`unpack: ${names.length} parts, each SHA-256 equal to the page's: ${names.join(", ")}`);
  console.log(els.record.textContent.split("\n").pop());
  for (const f of ["fp32", "fp64", "fp128", "fp256"]) {
    ctx.part = parts[`probe-${f}`];
    const cp = vm.runInContext("corpus(part)", ctx);
    ctx.cp = cp;
    const same = vm.runInContext("compare(cp, {d: cp.d, fl: cp.fl}, cp.d).bad", ctx);
    ctx.flipD = cp.d.slice(); ctx.flipD[0] ^= 1;
    const flip = vm.runInContext("compare(cp, {d: cp.d, fl: cp.fl}, flipD).bad", ctx);
    console.log(`${f}: corpus() fmt ${cp.fmt} esz ${cp.esz} n ${cp.n}; compare(): ${same} differ against its own ` +
                `values, ${flip} against one flipped bit`);
    if (cp.n !== 1024 || same !== 0 || flip !== 1) fail(`${f}`);
  }
  const wgsl = vm.runInContext("new TextDecoder().decode(part)", Object.assign(ctx, { part: parts.plain }));
  if (!/@compute @workgroup_size\(64u, 1u, 1u\)\nfn cft_fma_ocl\(/.test(wgsl)) fail("the plain module's entry point");
  console.log(`plain module: ${wgsl.split("\n").length - 1} lines, entry point cft_fma_ocl, @workgroup_size(64u, 1u, 1u)`);
  console.log("page_datapath: OK");
} catch (e) { fail(e.message); }
