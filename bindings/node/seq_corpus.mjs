// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
// The sequencer corpus, and the encoder a test needs to write a
// program by hand. No side effects: this file is imported by both
// test.mjs and program_test.mjs, and importing a test suite to reach
// one function in it would run the suite.
//
// WHAT THE CORPUS IS. `bindings/node/seq_corpus.jsonl` is what
// libcft's C executor answered for the shared fuzz corpus of programs
// - `cft_golden.seq.random_program` from a named seed, two thirds of
// them valid and one third deliberately corrupt.
// `bindings/node/make_seq_corpus.py` writes it, refusing to record
// anything the golden model disagrees with, and its header carries the
// seed and the shape so the file can be regenerated rather than
// believed. `host/tests/seq_check.py` is the live comparison and stays
// the gate; this is the recording, so that a wasm module and a
// JavaScript harness can be held to the same answers on a machine with
// no C compiler and no Python.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { STATUS_DEPOSIT_OVERFLOW } from "./lib.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------
// docs/SEQUENCER.md's instruction encoding and image layout
// ---------------------------------------------------------------------
//
// This package LOADS a program image; core.mjs deliberately has no
// assembler in it, because assembling is not what a binding does and a
// second encoder is a second opinion about the format. A test that
// writes a program by hand needs one anyway, so it lives here - the
// way host/tools/zoom.c and host/tools/orbits.c each carry their own
// copy of the same three helpers rather than sharing a header. The
// loader is the authority on what is legal; nothing here validates.

/** The six control codes, docs/SEQUENCER.md's table. */
export const CTRL = { halt: 0, repeat: 1, endrep: 2, deposit: 3,
                      setact: 4, actall: 5 };

/** One 64-bit little-endian instruction word, as a BigInt.
 *
 *  | 7:0 op | 11:8 rd | 15:12 ra | 19:16 rb | 23:20 rc | 26:24 rnd |
 *  | 27 ka | 28 kb | 29 kc | 30 reserved | 31 ctrl | 63:32 imm | */
export function insn({ op = 0, rd = 0, ra = 0, rb = 0, rc = 0, rnd = 0,
                       ka = false, kb = false, kc = false, ctrl = false,
                       imm = 0 } = {}) {
  return BigInt(op) | (BigInt(rd) << 8n) | (BigInt(ra) << 12n) |
         (BigInt(rb) << 16n) | (BigInt(rc) << 20n) | (BigInt(rnd) << 24n) |
         (BigInt(ka ? 1 : 0) << 27n) | (BigInt(kb ? 1 : 0) << 28n) |
         (BigInt(kc ? 1 : 0) << 29n) | (BigInt(ctrl ? 1 : 0) << 31n) |
         (BigInt(imm >>> 0) << 32n);
}

/** A control instruction. Only REPEAT reads `imm`, and only DEPOSIT
 *  and SETACT read `ra`; every other field must be zero or the loader
 *  refuses the program, so that one operation has one encoding and a
 *  readback hash is a hash of the program. */
export const ctl = (code, ra = 0, imm = 0) =>
  insn({ op: CTRL[code], ra, imm, ctrl: true });

/** header, constant bank, instruction stream - the bytes a device is
 *  DMA'd and can read back. `consts` are ENCODINGS (Uint8Array of the
 *  format's element size), because a constant bank holds format-width
 *  values and a program is compiled for one format. */
export function programImage({ formatCode, elementBytes, insns,
                               consts = [], maxDeposits }) {
  const bytes = new Uint8Array(32 + consts.length * elementBytes +
                               insns.length * 8);
  const dv = new DataView(bytes.buffer);
  bytes.set([0x43, 0x46, 0x54, 0x50], 0);              // "CFTP"
  dv.setUint32(4, 1, true);                            // version
  dv.setUint32(8, insns.length, true);
  dv.setUint32(12, consts.length, true);
  dv.setUint32(16, maxDeposits, true);
  dv.setUint32(20, formatCode, true);                  // the PREC_CODE ladder
  let off = 32;
  for (const k of consts) { bytes.set(k, off); off += elementBytes; }
  for (const w of insns) { dv.setBigUint64(off, w, true); off += 8; }
  return bytes;
}

// ---------------------------------------------------------------------
// the recording, and the replay
// ---------------------------------------------------------------------

export const CORPUS_PATH = join(HERE, "seq_corpus.jsonl");

export function readCorpus(path = CORPUS_PATH) {
  const lines = readFileSync(path, "utf8").split("\n").filter((l) => l);
  const header = JSON.parse(lines[0]);
  const cases = lines.slice(1).map((l) => JSON.parse(l));
  if (cases.length !== header.cases)
    throw new Error(`${path}: the header says ${header.cases} cases and ` +
                    `the file holds ${cases.length}`);
  return { header, cases };
}

const hexOf = (f) => Buffer.from(f.bytes).toString("hex");

/** Replay every case through cft_program_load / cft_program_run and
 *  compare with what the C executor answered.
 *
 *  `ctxs` maps a format name to an open Context; the program's own
 *  format decides which one loads it, and any of them would do, since
 *  a Program carries its format and the device is shared.
 *
 *  Returns a summary. Throws on the first disagreement, naming the
 *  case, the element, the slot and both values - "the arrays differ"
 *  would send the reader back to a hex dump.
 *
 *  A REFUSED case is a case the C loader refused, and the check is
 *  that this surface refuses it too, with the library's own words. A
 *  binding that loaded all of them would pass every value comparison
 *  in the file and still be wrong about what the loader is for. */
export function replayCorpus(ctxs, { corpus = readCorpus() } = {}) {
  const { cases } = corpus;
  let run = 0, refused = 0, deposits = 0, overflows = 0, lanes = 0;

  for (const [i, c] of cases.entries()) {
    const where = `case ${i} (${c.format}, ${c.expect})`;
    const ctx = ctxs[c.format];
    if (!ctx) throw new Error(`${where}: no open context for ${c.format}`);
    const image = Buffer.from(c.image, "hex");

    if (c.expect === "refused") {
      let threw = null;
      try { ctx.loadProgram(image); }
      catch (err) { threw = err; }
      if (!threw)
        throw new Error(
          `${where}: the C loader refused this program (${c.status_text}) ` +
          `and this one loaded it. Corruption: ${c.corruption}; the ` +
          `model's reason was ${JSON.stringify(c.model_reason)}`);
      if (!threw.message.includes(c.status_text))
        throw new Error(
          `${where}: refused with ${JSON.stringify(threw.message)} rather ` +
          `than the recorded ${JSON.stringify(c.status_text)}`);
      refused++;
      continue;
    }

    const prog = ctx.loadProgram(image);
    try {
      const expect = (got, want, what) => {
        if (got !== want)
          throw new Error(`${where}: ${what} is ${got}, recorded ${want}`);
      };
      expect(prog.format.name, c.format, "the program's format");
      expect(prog.maxDeposits, c.max_deposits, "max_deposits");
      expect(prog.nInsns, c.n_insns, "n_insns");
      expect(prog.nConsts, c.n_consts, "n_consts");

      const size = prog.format.size;
      const bytesOf = (list) => {
        const buf = new Uint8Array(size * list.length);
        list.forEach((h, k) => buf.set(Buffer.from(h, "hex"), k * size));
        return buf;
      };
      const r = prog.run(bytesOf(c.a), bytesOf(c.b), bytesOf(c.c));

      expect(r.deposits.length, c.deposits.length, "the deposit window");
      const md = Math.max(c.max_deposits, 1);
      for (let d = 0; d < c.deposits.length; d++) {
        const got = hexOf(r.deposits[d]);
        if (got !== c.deposits[d])
          throw new Error(
            `${where}: deposit[${d}] - element ${Math.floor(d / md)}, ` +
            `slot ${d % md} - is ${got}, the C executor wrote ` +
            `${c.deposits[d]}`);
      }
      deposits += c.deposits.length;

      expect(r.counts.length, c.n, "the counts length");
      for (let e = 0; e < c.n; e++)
        if (r.counts[e] !== c.counts[e])
          throw new Error(`${where}: counts[${e}] is ${r.counts[e]}, ` +
                          `the C executor said ${c.counts[e]}`);
      lanes += c.n;

      expect(r.flags, c.flags, "the IEEE flag word");
      expect(r.status, c.status, "the STATUS word");
      expect(r.depositOverflow,
             (c.status & STATUS_DEPOSIT_OVERFLOW) !== 0, "depositOverflow");
      if (r.depositOverflow) overflows++;
      run++;
    } finally {
      prog.free();
    }
  }
  return { run, refused, deposits, lanes, overflows };
}
