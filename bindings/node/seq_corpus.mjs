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
//
// FOR THE INTEGRATOR, 2026-09-08 evening. Revision 3's encodings below
// - the four scratch codes, the header's `scratch_io` word and the
// ninth constant-index bits in imm[30:28] - are written to
// docs/SEQUENCER.md's contract and are NOT yet cross-checked against
// `python/cft_golden/asm.py`, because asm.py on this branch is still
// revision 2 and another lane is widening it. `program_test.mjs`
// holds this encoder to asm.py byte for byte over four programs, and
// those four are revision 2's; the revision-3 tests beside them are
// this encoder against the LOADER, which is the C port of the same
// contract. When asm.py lands, add revision-3 programs to that
// comparison: it is where a permuted imm[30:28] would show, exactly as
// a permuted imm[27:24] showed at 0.9.

/** The ten control codes, docs/SEQUENCER.md's table - six through
 *  revision 2, and revision 3's four scratch codes (R4). */
export const CTRL = { halt: 0, repeat: 1, endrep: 2, deposit: 3,
                      setact: 4, actall: 5,
                      stl: 6, ldl: 7, stx: 8, ldx: 9 };

/** Revision 2's shape, 2026-09-08. Each lane owns THIRTY-TWO registers
 *  (R1) and the header's reserved[0] is a `flags` word (R3).
 *
 *  A register field is five bits: the low four stay where they were and
 *  the fifth of each lives in `imm[27:24]` - rd, ra, rb, rc in that
 *  order. `imm[31:28]` is read by nothing and must be zero. */
export const NREG = 32;
/** How many constants an instruction can ADDRESS: sixteen through the
 *  four-bit operand field, 256 through a byte of `imm` under `kx`, and
 *  512 with revision 3's ninth bits in `imm[30:28]` (R7). */
export const KADDR_PLAIN = 16;
export const KADDR_KX = 512;
/** Header flags: bit 0 is BANK_EXT - the image carries NO constant
 *  section, `n_consts` still says how many constants the program
 *  addresses, and every run supplies them. Bit 1 is SCRATCH_IO
 *  (revision 3, R5): the header's SECOND reserved word becomes
 *  `scratch_io`, n_scratch_in in [15:0] and n_scratch_out in [31:16],
 *  and every run preloads and reads back that many slots a lane. Every
 *  other bit is reserved-must-be-zero. */
export const FLAG_BANK_EXT = 0x1;
export const FLAG_SCRATCH_IO = 0x2;
/** Scratch slots a lane on the tile and in the software executor
 *  (SCRATCH_D). A static STL or LDL past it is refused at load; an
 *  indexed STX or LDX is reduced modulo it, which the contract fixes
 *  rather than leaving to an implementation. */
export const SCRATCH_D = 256;

// imm[27:24], in rd, ra, rb, rc order (docs/SEQUENCER.md R1's table),
// and the byte of imm each operand's constant index rides in under kx.
const RHI_SHIFT = { rd: 24n, ra: 25n, rb: 26n, rc: 27n };
const KX_SHIFT = [0, 8, 16];      // ra, rb, rc
// imm[28], imm[29], imm[30] - the NINTH bits of ka's, kb's and kc's
// constant indices under kx (revision 3, R7), the same construction as
// the fifth register bits one nibble down. imm[31] stays
// reserved-must-be-zero: it is the version guard for what comes next.
const KX9_SHIFT = [28n, 29n, 30n];

/** One 64-bit little-endian instruction word, as a BigInt.
 *
 *  | 7:0 op | 11:8 rd | 15:12 ra | 19:16 rb | 23:20 rc | 26:24 rnd |
 *  | 27 ka | 28 kb | 29 kc | 30 kx | 31 ctrl | 63:32 imm |
 *
 *  `rd`/`ra`/`rb`/`rc` are FIVE-BIT register numbers, or - where that
 *  operand's `k` bit is set - CONSTANT INDICES. The fifth register bit
 *  goes to its place in `imm` here rather than being the caller's
 *  problem, which is exactly what asm.py's `encode` does; this file and
 *  that one are two encoders held to identical output, and the way they
 *  are held is by writing the same rule twice and comparing bytes.
 *
 *  THE RESERVED-FIELD RULE decides every corner and is enforced here so
 *  a hand-written program is refused where it is written rather than at
 *  the loader: an operand naming a constant has no register high bit
 *  (the field is not read, so it must be zero), and under `kx` the
 *  index is a byte of `imm` and the operand field itself is zero. */
export function insn({ op = 0, rd = 0, ra = 0, rb = 0, rc = 0, rnd = 0,
                       ka = false, kb = false, kc = false, kx = false,
                       ctrl = false, imm = 0 } = {}) {
  const fields = { rd, ra, rb, rc };
  const isConst = { rd: false, ra: !!ka, rb: !!kb, rc: !!kc };
  const shift = { rd: 8n, ra: 12n, rb: 16n, rc: 20n };
  if (!(op >= 0 && op < 256))
    throw new RangeError(`op=${op} does not fit the opcode byte`);
  if (!(rnd >= 0 && rnd <= 4))
    throw new RangeError(`rnd=${rnd}; the contract defines 0..4`);
  let immBits = BigInt(imm >>> 0);
  let word = BigInt(op) | (BigInt(rnd) << 24n) |
             (BigInt(ka ? 1 : 0) << 27n) | (BigInt(kb ? 1 : 0) << 28n) |
             (BigInt(kc ? 1 : 0) << 29n) | (BigInt(kx ? 1 : 0) << 30n) |
             (BigInt(ctrl ? 1 : 0) << 31n);
  for (const name of ["rd", "ra", "rb", "rc"]) {
    const v = fields[name];
    const limit = isConst[name] ? (kx ? KADDR_KX : KADDR_PLAIN) : NREG;
    if (!(Number.isInteger(v) && v >= 0 && v < limit))
      throw new RangeError(`${name}=${v} outside 0..${limit - 1}`);
    if (isConst[name] && kx) continue;   // the index rides in imm
    word |= BigInt(v & 0xf) << shift[name];
    if (v >> 4) {
      if (isConst[name])
        throw new RangeError(`${name} names constant ${v}, which needs kx`);
      immBits |= 1n << RHI_SHIFT[name];
    }
  }
  if (immBits >> 32n)
    throw new RangeError("imm does not fit 32 bits");
  return word | (immBits << 32n);
}

/** One ALU instruction, choosing the form the assembler would: indexed
 *  when any constant index is 16 or more, plain otherwise. Pass
 *  `kx: true` to force the indexed form, which docs/SEQUENCER.md
 *  deliberately does not refuse for small indices. */
export function alu({ op, rd = 0, ra = 0, rb = 0, rc = 0, rnd = 0,
                      ka = false, kb = false, kc = false, kx = null } = {}) {
  const idx = [[ra, !!ka], [rb, !!kb], [rc, !!kc]];
  const indexed = kx === null
    ? idx.some(([v, f]) => f && v >= KADDR_PLAIN)
    : !!kx;
  let imm = 0;
  if (indexed) {
    if (!(ka || kb || kc))
      throw new RangeError("kx with no constant operand selects nothing");
    idx.forEach(([v, f], i) => {
      if (!f) return;
      if (!(v >= 0 && v < KADDR_KX))
        throw new RangeError(`constant index ${v} outside 0..${KADDR_KX - 1}`);
      // The low byte where it always went, and the ninth bit in its
      // own place in imm[30:28]. A ninth bit is READ only under kx and
      // only for an operand whose k flag is set, so it is written
      // nowhere else - which is what the loader's reserved-field rule
      // requires and what makes this encoder's output canonical.
      imm |= (v & 0xff) << KX_SHIFT[i];
      if (v >> 8) imm = Number(BigInt(imm >>> 0) | (1n << KX9_SHIFT[i]));
    });
  }
  return insn({ op, rd, ra, rb, rc, rnd, ka, kb, kc,
                kx: indexed, ctrl: false, imm: imm >>> 0 });
}

/** The four scratch codes of revision 3, R4.
 *
 *  | 6 STL ra, slot | 7 LDL rd, slot | 8 STX ra, rb | 9 LDX rd, rb |
 *
 *  The reserved-field rule settles each: STL reads `ra` and imm[23:0];
 *  LDL writes `rd` and reads imm[23:0]; STX reads `ra` and `rb`; LDX
 *  writes `rd` and reads `rb`, and for the indexed pair imm[23:0] is a
 *  field nothing reads. Registers are five bits and insn() puts each
 *  fifth bit in its place, so the only imm bits any of these carry are
 *  the slot and the high bits of the registers they NAME.
 *
 *  A static slot is held to SCRATCH_D here, where the program is
 *  written, rather than at the loader - the same courtesy alu() does
 *  for a constant index. An INDEXED slot is not bounded at all,
 *  because the contract reduces it modulo the depth. */
function scratchSlot(slot, who) {
  if (!(Number.isInteger(slot) && slot >= 0 && slot < SCRATCH_D))
    throw new RangeError(
      `${who} names scratch slot ${slot}, outside 0..${SCRATCH_D - 1}`);
  return slot;
}

export const stl = (ra, slot) =>
  insn({ op: CTRL.stl, ra, imm: scratchSlot(slot, "stl"), ctrl: true });
export const ldl = (rd, slot) =>
  insn({ op: CTRL.ldl, rd, imm: scratchSlot(slot, "ldl"), ctrl: true });
export const stx = (ra, rb) =>
  insn({ op: CTRL.stx, ra, rb, ctrl: true });
export const ldx = (rd, rb) =>
  insn({ op: CTRL.ldx, rd, rb, ctrl: true });

/** A control instruction. Only REPEAT reads `imm`, and only DEPOSIT
 *  and SETACT read `ra`; every other field must be zero or the loader
 *  refuses the program, so that one operation has one encoding and a
 *  readback hash is a hash of the program.
 *
 *  Revision 2 touches this in one place and it is easy to miss: `ra` is
 *  five bits on DEPOSIT and SETACT too, so `deposit r20` sets imm[25],
 *  and imm[25] is the ONLY imm bit those two may set. insn() puts it
 *  there. */
export const ctl = (code, ra = 0, imm = 0) =>
  insn({ op: CTRL[code], ra, imm, ctrl: true });

/** header, constant bank, instruction stream - the bytes a device is
 *  DMA'd and can read back. `consts` are ENCODINGS (Uint8Array of the
 *  format's element size), because a constant bank holds format-width
 *  values and a program is compiled for one format.
 *
 *  `flags` is the header word that was reserved[0] until 2026-09-08.
 *  With FLAG_BANK_EXT set THE IMAGE CARRIES NO CONSTANT SECTION: the
 *  header's n_consts still says how many constants the program
 *  addresses and every run supplies them, so pass `nConsts` (or a
 *  `consts` array whose entries are only counted, never written). The
 *  The second reserved word became `scratch_io` at revision 3 and is
 *  meaningful only under FLAG_SCRATCH_IO: n_scratch_in in [15:0] and
 *  n_scratch_out in [31:16], each at most SCRATCH_D. With the flag
 *  clear the word must be zero, exactly as the reserved word it was -
 *  which is what lets a later field arrive without a version step. */
export function programImage({ formatCode, elementBytes, insns,
                               consts = [], nConsts = null, maxDeposits,
                               flags = 0, nScratchIn = 0,
                               nScratchOut = 0 }) {
  const bankExternal = (flags & FLAG_BANK_EXT) !== 0;
  const scratchIo = (flags & FLAG_SCRATCH_IO) !== 0;
  if (!scratchIo && (nScratchIn || nScratchOut))
    throw new RangeError(
      `this image does not set SCRATCH_IO, so its scratch_io word must ` +
      `be zero and it cannot declare ${nScratchIn}/${nScratchOut} slots`);
  for (const [name, v] of [["nScratchIn", nScratchIn],
                           ["nScratchOut", nScratchOut]])
    if (!(Number.isInteger(v) && v >= 0 && v <= SCRATCH_D))
      throw new RangeError(`${name}=${v} outside 0..${SCRATCH_D}`);
  const declared = nConsts === null ? consts.length : nConsts;
  if (!bankExternal && nConsts !== null && nConsts !== consts.length)
    throw new RangeError(
      `this image carries its constant section, so its n_consts is the ` +
      `${consts.length} values given and cannot be declared as ${nConsts}`);
  const carried = bankExternal ? 0 : consts.length;
  const bytes = new Uint8Array(32 + carried * elementBytes +
                               insns.length * 8);
  const dv = new DataView(bytes.buffer);
  bytes.set([0x43, 0x46, 0x54, 0x50], 0);              // "CFTP"
  dv.setUint32(4, 1, true);                            // version
  dv.setUint32(8, insns.length, true);
  dv.setUint32(12, declared, true);                    // ADDRESSED, not carried
  dv.setUint32(16, maxDeposits, true);
  dv.setUint32(20, formatCode, true);                  // the PREC_CODE ladder
  dv.setUint32(24, flags >>> 0, true);                 // was reserved[0]
  dv.setUint32(28,                                     // was reserved[1]
               ((nScratchIn & 0xffff) |
                ((nScratchOut & 0xffff) << 16)) >>> 0, true);
  let off = 32;
  if (!bankExternal) {
    // The constant section, through packBank - see below: the section
    // and the bank are ONE layout, and writing it twice is how the two
    // stop being one.
    bytes.set(packBank(consts, elementBytes), off);
    off += carried * elementBytes;
  }
  for (const w of insns) { dv.setBigUint64(off, w, true); off += 8; }
  return bytes;
}

/** The bank a BANK_EXT program's run supplies: n_consts format-width
 *  values, densely packed EXACTLY as an image's constant section is
 *  laid out (cft.h, docs/SEQUENCER.md R3). programImage lays its
 *  constant section out by calling this, so the two cannot drift: a
 *  bank that did not match the section it replaces would be a program
 *  computing on different numbers depending on where its constants came
 *  from, which is the whole thing BANK_EXT must not do. */
export function packBank(consts, elementBytes) {
  const bytes = new Uint8Array(consts.length * elementBytes);
  consts.forEach((k, i) => bytes.set(k, i * elementBytes));
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
