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
// A run that checked nothing must not read as a pass. Zero cases, a
// missing set, or a directory with no sets in it are failures here,
// exactly as they are inside cft_conformance.

import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { loadModule } from "./lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");

const FORMATS = ["fp32", "fp64", "fp128", "fp256"];
const ROUNDINGS = ["rne", "rtz", "rdn", "rup", "rmm"];
const CANONICAL = [];
for (const f of FORMATS)
  for (const r of ROUNDINGS)
    CANONICAL.push(r === "rne" ? `${f}.jsonl` : `${f}-${r}.jsonl`);

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
const stray = readdirSync(vdir).filter((n) => n.endsWith(".jsonl") &&
  !CANONICAL.includes(n));
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
if (bad === 0 && clean === CANONICAL.length && total > 0) {
  console.log(`${total.toLocaleString("en-US")} cases over ${clean} sets, ` +
              `library matches the vectors exactly (${secs}s)`);
  process.exit(0);
}
console.log(`${clean} of ${CANONICAL.length} sets clean, ` +
            `${total.toLocaleString("en-US")} cases - NOT A PASS (${secs}s)`);
process.exit(1);
