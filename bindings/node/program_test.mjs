// Copyright 2026 Logan W.
// SPDX-License-Identifier: Apache-2.0
//
//     node bindings/node/program_test.mjs
//
// The orbit sequencer through this package: every case in
// bindings/node/seq_corpus.jsonl replayed against the C executor's
// recorded answer, then programs written by hand here for the two
// behaviours a fuzz corpus records but does not explain - SETACT's
// early exit, and deposit overflow - then the refusals, the memory,
// and a negative control.
//
// WHY A RECORDING AND NOT A LIVE COMPARISON. host/tests/seq_check.py
// is the live check and stays the gate: it runs the same programs
// through python/cft_golden/seq.py and through libcft in one process
// and compares deposits, counts, flags and STATUS. It needs a built
// libcft and a Python that can import cft_golden, and this package has
// neither by design - it is a wasm module and a JavaScript harness,
// and that it runs where a toolchain does not is the point of it. So
// make_seq_corpus.py writes the C executor's answers down once,
// refusing to record anything the golden model disagrees with, and
// this replays them through cft_program_load / cft_program_run.
//
// What that catches: a wrapper with two arguments transposed, a
// deposit buffer read at the wrong stride, a count read as a byte
// offset, a status word dropped on the floor, a refusal turned into a
// value. What it cannot catch is a change made to BOTH the C executor
// and the recording - seq_check.py is where that shows.
//
// `node test.mjs` replays the same corpus as one of its own tests, so
// the package's ordinary gate covers it; this file is where the rest
// of the surface is exercised.

import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { Context } from "./index.mjs";
import { STATUS_DEPOSIT_OVERFLOW } from "./lib.mjs";
import { CTRL, FLAG_BANK_EXT, alu, ctl, insn, packBank, programImage,
         readCorpus, replayCorpus }
  from "./seq_corpus.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));

// cft_op's opcode numbers, and the fields each one READS - which is not
// something the library publishes, so it is written where it is used
// (docs/PROGRAMS.md says the same of the two assemblers' tables).
const OP_FMA = 0;                 // reads ra, rb, rc
const OP_ADD = 1;                 // reads ra and rc
const OP_SUB = 2;                 // cft_op: SUB reads ra and rc (cft.h)
const OP_MUL = 3;                 // reads ra and rb
const OP_COPYSIGN = 6;            // reads ra and rb

let passed = 0, failed = 0, skipped = 0;
const failures = [];
const notes = [];

/** Skip this test, by name and with a reason. Thrown rather than
 *  returned so it works from inside a helper: a check that cannot run
 *  has to say so where it found out, and a skip that is reported as a
 *  pass is the failure this file exists to avoid. */
class Skip extends Error {}
function skip(why) { throw new Skip(why); }

function test(name, fn) {
  try {
    const note = fn();
    passed++;
    if (typeof note === "string") notes.push(`${name}: ${note}`);
  } catch (err) {
    if (err instanceof Skip) { skipped++; notes.push(`SKIP ${name}: ${err.message}`); }
    else { failed++; failures.push(`${name}: ${err.message}`); }
  }
}
function eq(got, want, what = "") {
  if (got !== want) throw new Error(`${what}expected ${want}, got ${got}`);
}
function ok(cond, what) { if (!cond) throw new Error(what); }

const hexOf = (f) => Buffer.from(f.bytes).toString("hex");

const FORMATS = ["fp32", "fp64", "fp128", "fp256"];
const ctxs = {};
for (const f of FORMATS) ctxs[f] = await Context.open(f);
const c64 = ctxs.fp64;

const corpus = readCorpus();
let summary = null;

test("the recorded corpus: every deposit, count, flag and STATUS word",
     () => {
  summary = replayCorpus(ctxs, { corpus });
  ok(summary.run > 0, "no program ran - the corpus proved nothing");
  ok(summary.refused > 0,
     "no program was refused - half of this check did not run");
  ok(summary.overflows > 0,
     "no run overflowed its deposit budget, so the STATUS comparison " +
     "never saw a set bit");
  ok(summary.lanes > 64,
     "no run crossed libcft's 64-lane block boundary, so the blocking " +
     "this corpus exists to cover was not exercised");
});

// ---------------------------------------------------------------------
// programs written by hand
// ---------------------------------------------------------------------
//
// The corpus is random programs over random operands: it covers a lot
// and explains nothing. These are written so that the expected answer
// is derived from docs/SEQUENCER.md by hand and can be read beside it.
//
//     REPEAT trip
//       DEPOSIT r0
//       r0 := r0 - 1          (SUB reads ra and rc - cft.h's slots)
//       SETACT r0             (active &= r0 != 0; narrows, never widens)
//     ENDREP
//     HALT
//
// Lane i starts with r0 = a[i] and counts down. A lane that reaches +0
// drops out and deposits nothing more, so its deposit COUNT is how far
// it got - the escape-time shape the sequencer exists for. Once every
// lane has dropped out the loop exits early, and P3 says that must
// change how long the run takes and nothing else.

function countdown(maxDeposits, trip = 4) {
  const one = c64.from(1).bytes;
  return programImage({
    formatCode: c64.format.code, elementBytes: c64.format.size,
    consts: [one], maxDeposits,
    insns: [
      ctl("repeat", 0, trip),
      ctl("deposit", 0),
      insn({ op: OP_SUB, rd: 0, ra: 0, rc: 0, kc: true }),
      ctl("setact", 0),
      ctl("endrep"),
      ctl("halt"),
    ],
  });
}

test("SETACT drops a lane out, and the count says how far it got", () => {
  const prog = c64.loadProgram(countdown(4));
  try {
    eq(prog.format.name, "fp64", "the program's format: ");
    eq(prog.maxDeposits, 4, "max_deposits: ");
    eq(prog.nInsns, 6, "n_insns: ");
    eq(prog.nConsts, 1, "n_consts: ");
    // 3 -> deposits 3,2,1 then r0 is +0 and the lane is out.
    // 1 -> deposits 1 and is out on the first pass.
    // 5 -> deposits 5,4,3,2 and is still live when the trip runs out.
    const r = prog.run([3, 1, 5]);
    eq([...r.counts].join(","), "3,1,4", "deposit counts: ");
    eq(r.deposits.map((f) => f.toNumber()).join(","),
       "3,2,1,0,1,0,0,0,5,4,3,2", "the deposit window: ");
    eq(r.status, 0, "no lane overflowed: ");
    eq(r.depositOverflow, false, "depositOverflow: ");
    // Every slot is written and an untouched one reads +0 - normative,
    // because a run that left the buffer's previous contents there
    // would not be reproducible. The SIGN too: it is +0, not -0.
    for (const d of [3, 5, 6, 7])
      eq(r.deposits[d].bits, 0n, `slot ${d} is +0, bits and all: `);
  } finally { prog.free(); }
});

test("the early exit is invisible: a longer trip changes nothing", () => {
  // P3. Every lane is inactive after three passes, so trips 4, 9 and
  // 40 must agree on every deposit, every count, the flags and the
  // status; only the instruction count moves, and nothing here can see
  // it. This is the property the whole design rests on, in the one
  // place a JavaScript caller can check it.
  const want = (() => {
    const p = c64.loadProgram(countdown(4, 4));
    try { return p.run([3, 1, 2]); } finally { p.free(); }
  })();
  for (const trip of [9, 40]) {
    const p = c64.loadProgram(countdown(4, trip));
    try {
      const got = p.run([3, 1, 2]);
      eq([...got.counts].join(","), [...want.counts].join(","),
         `trip ${trip}: counts: `);
      eq(got.deposits.map(hexOf).join(" "),
         want.deposits.map(hexOf).join(" "), `trip ${trip}: deposits: `);
      eq(got.flags, want.flags, `trip ${trip}: flags: `);
      eq(got.status, want.status, `trip ${trip}: status: `);
    } finally { p.free(); }
  }
});

test("a lane past max_deposits drops the tail and sets STATUS bit 4", () => {
  const prog = c64.loadProgram(countdown(2));
  try {
    // 5 deposits four times into two slots: two fit, two are dropped.
    // The count is what FIT - it is the index of the next free slot,
    // and there is no next.
    const r = prog.run([5, 1]);
    eq([...r.counts].join(","), "2,1", "counts are what fitted: ");
    eq(r.deposits.map((f) => f.toNumber()).join(","), "5,4,1,0",
       "what fitted is correct and reproducible: ");
    eq(r.status, STATUS_DEPOSIT_OVERFLOW, "the STATUS word: ");
    eq(r.depositOverflow, true, "depositOverflow: ");
    eq(r.flags, 0,
       "overflow is NOT an IEEE flag - the five mean what 754 says: ");
  } finally { prog.free(); }
});

test("a zero deposit budget is a program, and every deposit overflows",
     () => {
  // host/src/program.c argues this one at length: the model's
  // validator accepts a zero budget and the tile refuses only
  // max_deposits > MAXD, so a host-side rule demanding one slot would
  // be the library inventing a rule neither of them states.
  const prog = c64.loadProgram(countdown(0));
  try {
    const r = prog.run([3, 1]);
    eq(r.deposits.length, 0, "n * 0 slots: ");
    eq([...r.counts].join(","), "0,0", "nothing fitted: ");
    eq(r.depositOverflow, true, "and the run says so: ");
  } finally { prog.free(); }
});

test("b and c are optional, and r3..r15 start at +0", () => {
  // r0 = a, r1 = b, r2 = c, and cft.h says b and c may be NULL, in
  // which case those registers start at +0. r7 has never been written
  // by anything, so depositing it is the check that the rest do too.
  const image = programImage({
    formatCode: c64.format.code, elementBytes: c64.format.size,
    consts: [], maxDeposits: 4,
    insns: [ctl("deposit", 0), ctl("deposit", 1), ctl("deposit", 2),
            ctl("deposit", 7), ctl("halt")],
  });
  const prog = c64.loadProgram(image);
  try {
    const withAll = prog.run([1.5], [2.5], [3.5]);
    eq(withAll.deposits.map((f) => f.toNumber()).join(","), "1.5,2.5,3.5,0",
       "the three streams land in r0, r1, r2: ");
    const bare = prog.run([1.5]);
    eq(bare.deposits.map((f) => f.toNumber()).join(","), "1.5,0,0,0",
       "b and c omitted start those registers at +0: ");
    eq([...bare.counts].join(","), "4", "four deposits either way: ");
  } finally { prog.free(); }
});

test("deposits are addressed by element index and nothing else", () => {
  // SEQUENCER.md P2: deposit d of element i lands at
  // i * max_deposits + d, which depends on the element's own index -
  // so the same elements in a longer run land in the same places, and
  // a run split across tiles writes the same bytes to the same
  // offsets. Run the same three lanes alone and then as the tail of a
  // longer array, and the windows must agree.
  const prog = c64.loadProgram(countdown(4));
  try {
    const short = prog.run([3, 1, 5]);
    const long = prog.run([9, 9, 9, 9, 9, 3, 1, 5]);
    for (let i = 0; i < 3; i++) {
      for (let d = 0; d < 4; d++)
        eq(hexOf(long.deposits[(5 + i) * 4 + d]),
           hexOf(short.deposits[i * 4 + d]),
           `element ${i}, slot ${d} moved when the array grew: `);
      eq(long.counts[5 + i], short.counts[i],
         `element ${i}'s count moved when the array grew: `);
    }
  } finally { prog.free(); }
});

test("a program carries its own format, whatever context loaded it", () => {
  // A program is compiled for one format because its constants are
  // format-width values. Loading an fp256 image from an fp64 context
  // must not read its operands eight bytes at a time.
  const f256 = ctxs.fp256;
  const image = programImage({
    formatCode: f256.format.code, elementBytes: f256.format.size,
    consts: [], maxDeposits: 1,
    insns: [ctl("deposit", 0), ctl("halt")],
  });
  const prog = c64.loadProgram(image);
  try {
    eq(prog.format.name, "fp256", "the program's own format: ");
    eq(prog.format.size, 32, "and therefore its element size: ");
    const x = f256.from("1e-100");
    const r = prog.run([x]);
    ok(r.deposits[0].sameBits(x),
       "an fp256 operand goes in and comes back unchanged");
  } finally { prog.free(); }
});

test("n = 0 is an answer, not an error", () => {
  const prog = c64.loadProgram(countdown(2));
  try {
    const r = prog.run([]);
    eq(r.deposits.length, 0, "no elements, no deposits: ");
    eq(r.counts.length, 0, "and no counts: ");
    eq(r.flags, 0, "and nothing raised: ");
  } finally { prog.free(); }
});

// ---------------------------------------------------------------------
// refusals, and what this surface does with them
// ---------------------------------------------------------------------

test("the loader's refusals arrive as errors carrying its own words",
     () => {
  const bad = [
    ["an unbalanced endrep", [ctl("endrep"), ctl("halt")]],
    ["halt inside a loop", [ctl("repeat", 0, 2), ctl("halt"),
                            ctl("endrep"), ctl("halt")]],
    ["actall inside a loop", [ctl("repeat", 0, 2), ctl("actall"),
                              ctl("endrep"), ctl("halt")]],
    ["repeat 0", [ctl("repeat", 0, 0), ctl("endrep"), ctl("halt")]],
    ["a stray field on a deposit",
     [insn({ op: CTRL.deposit, ra: 0, ka: true, ctrl: true }), ctl("halt")]],
    ["an immediate on an ALU instruction",
     [insn({ op: OP_SUB, rd: 0, ra: 0, rc: 0, imm: 1 }), ctl("halt")]],
    ["reserved bit 30",
     [insn({ op: OP_SUB, rd: 0 }) | (1n << 30n), ctl("halt")]],
    ["a constant the bank does not hold",
     [insn({ op: OP_SUB, rd: 0, ra: 0, rc: 3, kc: true }), ctl("halt")]],
    ["four nested repeats of 2^32-1",
     [...Array(4).fill(ctl("repeat", 0, 0xffffffff)),
      insn({ op: OP_SUB, rd: 0 }),
      ...Array(4).fill(ctl("endrep")), ctl("halt")]],
  ];
  for (const [what, insns] of bad) {
    let threw = null;
    try {
      c64.loadProgram(programImage({
        formatCode: c64.format.code, elementBytes: c64.format.size,
        insns, maxDeposits: 1,
      }));
    } catch (err) { threw = err; }
    ok(threw, `${what} must be refused, not loaded`);
    ok(/cft_program_load/.test(threw.message),
       `${what}: the error names the call that refused it`);
  }
});

test("a truncated, over-long or mislabelled image is a different program",
     () => {
  const good = countdown(2);
  const bend = (bytes, at, to) => {
    const c = Uint8Array.from(bytes); c[at] = to; return c;
  };
  const cases = [
    ["one byte short", good.slice(0, good.length - 1)],
    ["one byte long", Uint8Array.from([...good, 0])],
    ["empty", new Uint8Array(0)],
    ["header only", good.slice(0, 32)],
    ["bad magic", bend(good, 0, 0x44)],
    ["a version this loader does not speak", bend(good, 4, 2)],
    ["a non-zero reserved header word", bend(good, 24, 1)],
    ["a precision code off the ladder", bend(good, 20, 9)],
  ];
  for (const [what, image] of cases) {
    let threw = null;
    try { c64.loadProgram(image); } catch (err) { threw = err; }
    ok(threw, `${what} must be refused`);
  }
  // and the untouched image still loads, so the eight above failed for
  // the reason claimed and not because the whole test is broken
  c64.loadProgram(good).free();
});

test("a freed program refuses every later call", () => {
  const p = c64.loadProgram(countdown(1));
  p.run([1]);
  p.free();
  p.free();                       // idempotent
  eq(p.freed, true, "freed: ");
  let threw = null;
  try { p.run([1]); } catch (err) { threw = err; }
  ok(threw && /already been freed/.test(threw.message),
     "run() after free() must throw rather than reach into the heap");
});

test("mismatched stream lengths are refused before any call is made", () => {
  const p = c64.loadProgram(countdown(1));
  try {
    let threw = null;
    try { p.run([1, 2, 3], [1, 2]); } catch (err) { threw = err; }
    ok(threw && /same lane index/.test(threw.message),
       "b shorter than a must be refused");
    threw = null;
    try { p.run(null); } catch (err) { threw = err; }
    ok(threw, "a is not optional");
    threw = null;
    try { p.run(new Uint8Array(7)); } catch (err) { threw = err; }
    ok(threw && /whole number/.test(threw.message),
       "a byte array that is not a whole number of elements is refused");
  } finally { p.free(); }
});

// ---------------------------------------------------------------------
// memory
// ---------------------------------------------------------------------
//
// The handle is a wasm-heap allocation the library owns, and every run
// copies operands in and deposits out through Scratch. A leak anywhere
// in that chain shows up as growth, and since dlmalloc reuses a freed
// block, a probe allocation that comes back to the same address is the
// stronger of the two signals.

function heapProbe(M) {
  const p = M._malloc(64);
  M._free(p);
  return { ptr: p, bytes: M.HEAPU8.buffer.byteLength };
}

function noLeak(what, warm, hot) {
  const M = c64._M;
  for (let i = 0; i < 50; i++) warm();
  const before = heapProbe(M);
  for (let i = 0; i < 2000; i++) hot();
  const after = heapProbe(M);
  eq(after.bytes, before.bytes,
     `${what}: 2,000 cycles must not grow the wasm heap: `);
  eq(after.ptr, before.ptr,
     `${what}: a probe allocation must land at the same address: `);
}

test("many loads, runs and frees leave the heap where they found it",
     () => {
  const image = countdown(2);
  const a = [5, 1, 3, 0];
  const cycle = () => {
    const p = c64.loadProgram(image);
    const r = p.run(a);
    if (r.counts[0] !== 2) throw new Error("the run stopped being right");
    p.free();
  };
  noLeak("load/run/free", cycle, cycle);
});

test("a program loaded and never run frees cleanly too", () => {
  const image = countdown(2);
  const cycle = () => c64.loadProgram(image).free();
  noLeak("load/free", cycle, cycle);
});

test("a refused load leaks nothing either", () => {
  // The failure path is the one nobody exercises: cft_program_load
  // frees its own partial allocation when validation fails, and the
  // image copy this side made has to go back whatever happened.
  const bad = programImage({
    formatCode: c64.format.code, elementBytes: c64.format.size,
    insns: [ctl("endrep"), ctl("halt")], maxDeposits: 1,
  });
  const cycle = () => {
    try { c64.loadProgram(bad); throw new Error("that should not load"); }
    catch (err) {
      if (!/cft_program_load/.test(err.message)) throw err;
    }
  };
  noLeak("a refused load", cycle, cycle);
});

// ---------------------------------------------------------------------
// the negative control
// ---------------------------------------------------------------------

test("NEGATIVE CONTROL: the corpus comparison can fail", () => {
  // A checker that has never been seen to fail proves nothing. One
  // sabotage per thing the replay compares.
  const one = corpus.cases.find(
    (c) => c.expect === "ok" && c.deposits.some((d) => /[^0]/.test(d)));
  ok(one, "the corpus holds a case with a non-zero deposit");
  const bend = (mutate) => {
    const c = JSON.parse(JSON.stringify(one));
    mutate(c);
    try {
      replayCorpus(ctxs, { corpus: { header: corpus.header, cases: [c] } });
    } catch (err) { return err; }
    return null;
  };
  const d = one.deposits.findIndex((x) => /[^0]/.test(x));
  ok(bend((c) => {
    const flipped = (parseInt(c.deposits[d].slice(-2), 16) ^ 1)
      .toString(16).padStart(2, "0");
    c.deposits[d] = c.deposits[d].slice(0, -2) + flipped;
  }), "one flipped bit in one deposit must be caught");
  ok(bend((c) => { c.counts[0] += 1; }),
     "a wrong deposit count must be caught");
  ok(bend((c) => { c.flags ^= 1; }), "a wrong flag word must be caught");
  ok(bend((c) => { c.status ^= STATUS_DEPOSIT_OVERFLOW; }),
     "a wrong STATUS word must be caught");
  ok(bend((c) => { c.max_deposits += 1; }),
     "a wrong deposit budget must be caught");

  // And the other direction: a program the C loader refused, relabelled
  // as one that runs, must not quietly pass.
  const refusal = corpus.cases.find((c) => c.expect === "refused");
  const relabelled = {
    ...refusal, expect: "ok", n: 1, max_deposits: 1,
    n_insns: 0, n_consts: 0,
    a: ["0000000000000000"], b: ["0000000000000000"],
    c: ["0000000000000000"],
    deposits: ["0000000000000000"], counts: [0], flags: 0, status: 0,
  };
  let threw = null;
  try {
    replayCorpus(ctxs, { corpus: { header: corpus.header,
                                   cases: [relabelled] } });
  } catch (err) { threw = err; }
  ok(threw, "a refused program relabelled as a run must be caught");
});

// ---------------------------------------------------------------------
// revision 2: five-bit registers, and the bank as data   (2026-09-08)
// ---------------------------------------------------------------------
//
// docs/SEQUENCER.md's revision 2 adds two things this surface can be
// wrong about in silence, so both are written by hand here and the
// expected answer is derived beside them:
//
//   R1  a register field is FIVE bits - the low four where they were,
//       the fifth in imm[27:24], rd/ra/rb/rc in that order. An encoder
//       that dropped the fifth bit, or put rd's where ra's goes, would
//       still produce a loadable program that addressed a DIFFERENT
//       register. That is exactly the failure CAPS[5] exists to keep an
//       old bitstream out of, and it is invisible to a round trip.
//   R3  a BANK_EXT image carries no constant section and every run
//       supplies the constants. An encoder that wrote the section
//       anyway, or a runner that ignored the bank, would agree about
//       the image and compute on different numbers.
//
// The programs below are built so that the wrong answer is a DIFFERENT
// answer rather than a refusal: r20 is written first and r4 second, so
// an encoder that lost rd's fifth bit would have the second instruction
// overwrite the first and both deposits would read alike.

const u64 = (hi32lo) => {
  const b = new Uint8Array(8);
  new DataView(b.buffer).setBigUint64(0, hi32lo, true);
  return b;
};
const F64 = {
  one:  u64(0x3ff0000000000000n),   // 1.0
  two:  u64(0x4000000000000000n),   // 2.0
  three: u64(0x4008000000000000n),  // 3.0
};

// r20 = x + 1, r4 = x * x, r21 = r20 + 1, r6 = x * r21,
// r7 = fma(x, r21, r20); deposit r21, r7, r6, r4.
//
// Every one of the four fields carries a fifth bit somewhere: rd on the
// first, ra on the third (r20 read), rb on the fourth (r21 read), rc on
// the fifth (r20 read), and DEPOSIT's own ra on the sixth - which is
// the one place imm[25] may be set on a control instruction and the
// only imm bit that may be.
function regs32Program() {
  return programImage({
    formatCode: c64.format.code, elementBytes: c64.format.size,
    consts: [F64.one], maxDeposits: 4,
    insns: [
      // add r20, r0, ONE     (ADD reads ra and rc)
      alu({ op: OP_ADD, rd: 20, ra: 0, rc: 0, kc: true }),
      // mul r4, r0, r0       the decoy: rd & 0xF is 4 on both
      alu({ op: OP_MUL, rd: 4, ra: 0, rb: 0 }),
      // add r21, r20, ONE
      alu({ op: OP_ADD, rd: 21, ra: 20, rc: 0, kc: true }),
      // mul r6, r0, r21
      alu({ op: OP_MUL, rd: 6, ra: 0, rb: 21 }),
      // fma r7, r0, r21, r20
      alu({ op: OP_FMA, rd: 7, ra: 0, rb: 21, rc: 20 }),
      ctl("deposit", 21),
      ctl("deposit", 7),
      ctl("deposit", 6),
      ctl("deposit", 4),
      ctl("halt"),
    ],
  });
}

test("R1: r16..r31, with the fifth bits in imm[27:24]", () => {
  const prog = c64.loadProgram(regs32Program());
  try {
    eq(prog.nInsns, 10, "n_insns: ");
    eq(prog.flags, 0, "an ordinary image has no header flags: ");
    eq(prog.bankExternal, false, "bankExternal: ");
    const xs = [3, 5, 0.5];
    const r = prog.run(xs);
    // Derived here, from the program above and nothing else.
    const want = xs.flatMap((x) => [x + 2, x * (x + 2) + (x + 1),
                                    x * (x + 2), x * x]);
    eq(r.deposits.map((f) => f.toNumber()).join(","), want.join(","),
       "four registers above r15, each holding its own value: ");
    eq([...r.counts].join(","), "4,4,4", "every lane deposited four: ");
    eq(r.flags, 0, "nothing signalled: ");
  } finally { prog.free(); }
});

test("R1: dropping a register's fifth bit is a DIFFERENT answer", () => {
  // The negative control for the test above, and the reason it is
  // shaped the way it is. Encode the same program with every register
  // masked to four bits - which is what an old operand mux does, and
  // what an encoder that forgot imm[27:24] would emit - and check that
  // the machine does not agree with it. If these two ever matched, the
  // test above would be passing without testing anything.
  const flat = programImage({
    formatCode: c64.format.code, elementBytes: c64.format.size,
    consts: [F64.one], maxDeposits: 4,
    insns: [
      alu({ op: OP_ADD, rd: 20 & 15, ra: 0, rc: 0, kc: true }),
      alu({ op: OP_MUL, rd: 4, ra: 0, rb: 0 }),
      alu({ op: OP_ADD, rd: 21 & 15, ra: 20 & 15, rc: 0, kc: true }),
      alu({ op: OP_MUL, rd: 6, ra: 0, rb: 21 & 15 }),
      alu({ op: OP_FMA, rd: 7, ra: 0, rb: 21 & 15, rc: 20 & 15 }),
      ctl("deposit", 21 & 15),
      ctl("deposit", 7),
      ctl("deposit", 6),
      ctl("deposit", 4),
      ctl("halt"),
    ],
  });
  const wide = c64.loadProgram(regs32Program());
  const narrow = c64.loadProgram(flat);
  try {
    const a = wide.run([3, 5, 0.5]), b = narrow.run([3, 5, 0.5]);
    ok(a.deposits.map(hexOf).join(" ") !== b.deposits.map(hexOf).join(" "),
       "the five-bit program and the four-bit one must not agree - if " +
       "they do, the fifth bits are reaching nothing");
  } finally { wide.free(); narrow.free(); }
});

// The BANK_EXT worked example, small enough to read: acc = C0, then
// acc = fma(acc, x, C1), deposit. Two constants, neither in the image.
function hornerBankProgram({ flags = FLAG_BANK_EXT, consts = null } = {}) {
  return programImage({
    formatCode: c64.format.code, elementBytes: c64.format.size,
    consts: consts ?? [], nConsts: consts ? null : 2,
    maxDeposits: 1, flags,
    insns: [
      alu({ op: OP_COPYSIGN, rd: 3, ra: 0, rb: 0, ka: true, kb: true }),
      alu({ op: OP_FMA, rd: 3, ra: 3, rb: 0, rc: 1, kc: true }),
      ctl("deposit", 3),
      ctl("halt"),
    ],
  });
}

test("R3: a BANK_EXT image is header and instructions, and no more", () => {
  const image = hornerBankProgram();
  eq(image.length, 32 + 4 * 8,
     "bytes == 32 + 8 * n_insns, with no constant section: ");
  const dv = new DataView(image.buffer);
  eq(dv.getUint32(12, true), 2, "n_consts still says what is ADDRESSED: ");
  eq(dv.getUint32(24, true), FLAG_BANK_EXT, "the header's flags word: ");
  eq(dv.getUint32(28, true), 0, "reserved[1] stays zero: ");
});

test("R3: the bank is the data, and two banks are two answers", () => {
  const prog = c64.loadProgram(hornerBankProgram());
  try {
    eq(prog.bankExternal, true, "bankExternal: ");
    eq(prog.nConsts, 2, "n_consts: ");
    eq(prog.bankBytes, 16, "the bank this program's runs must supply: ");

    const xs = [2, 3, 4];
    // acc = C0; acc = C0 * x + C1
    const run = (c0, c1) => {
      const r = prog.runBank([c0, c1], xs);
      eq(r.flags, 0, "nothing signalled: ");
      return r.deposits.map((f) => f.toNumber());
    };
    eq(run(1, 2).join(","), xs.map((x) => 1 * x + 2).join(","),
       "bank (1, 2): ");
    eq(run(2, 1).join(","), xs.map((x) => 2 * x + 1).join(","),
       "bank (2, 1): ");
    eq(run(3, 3).join(","), xs.map((x) => 3 * x + 3).join(","),
       "bank (3, 3): ");
  } finally { prog.free(); }
});

test("R3: the image is the schedule and the digest covers the data", () => {
  const prog = c64.loadProgram(hornerBankProgram());
  const hex = (u8) => Buffer.from(u8).toString("hex");
  try {
    const bankA = packBank([F64.one, F64.two], 8);
    const bankB = packBank([F64.two, F64.one], 8);
    const dA = hex(prog.digest(bankA)), dB = hex(prog.digest(bankB));
    eq(dA.length, 64, "a digest is 32 bytes: ");
    ok(dA !== dB,
       "two banks are two computations and must have two digests - the " +
       "image's own hash is the same in both, and that is the point");
    eq(hex(prog.digest(bankA)), dA, "and the digest is a function: ");
  } finally { prog.free(); }
});

test("R3: a program has ONE source of constants, and both calls say so",
     () => {
  const ext = c64.loadProgram(hornerBankProgram());
  const own = c64.loadProgram(
    hornerBankProgram({ flags: 0, consts: [F64.one, F64.two] }));
  try {
    // The same arithmetic, reached two ways: the carried image with
    // (1, 2) and the external one with the same two values.
    eq(own.bankExternal, false, "the carried image's bankExternal: ");
    eq(own.nConsts, 2, "and it addresses the same two: ");
    const carried = own.run([2, 3, 4]).deposits.map(hexOf).join(" ");
    const banked = ext.runBank([1, 2], [2, 3, 4]).deposits.map(hexOf).join(" ");
    eq(banked, carried,
       "one image with its constants and one with them as data must " +
       "compute the same bits: ");

    const refuses = (fn) => { try { fn(); return null; } catch (e) { return e; } };
    ok(/runBank/.test(String(refuses(() => ext.run([1])))),
       "run() on a BANK_EXT program names runBank");
    ok(refuses(() => ext.runBank([1], [1])) instanceof RangeError,
       "a bank that is not n_consts values wide is refused");
    ok(refuses(() => ext.runBank(null, [1])) !== null,
       "a BANK_EXT program refuses a missing bank");
    ok(refuses(() => own.runBank([1, 2], [1])) !== null,
       "a program carrying its own constants refuses a bank");
    ok(refuses(() => own.digest([1, 2])) !== null,
       "and refuses one in a digest, for the same reason");
    // The carried program's only digest form is the image alone.
    eq(Buffer.from(own.digest()).toString("hex").length, 64,
       "the carried program digests its image alone: ");
  } finally { ext.free(); own.free(); }
});

// ---------------------------------------------------------------------
// the reference encoder, and the library's own programs
// ---------------------------------------------------------------------
//
// seq_corpus.mjs carries an encoder because a test that writes a
// program by hand needs one, and python/cft_golden/asm.py is THE
// reference. Two encoders are two opinions about the instruction word
// unless something compares them, and revision 2 gave them something
// new to disagree about that no round trip can see: a permuted
// imm[27:24] assembles and disassembles perfectly and addresses the
// wrong registers. So the comparison is between the two, over the same
// program, in bytes, with `.cfta` text as the shared spelling of "the
// same program" - which is the same discipline docs/PROGRAMS.md holds
// asm.py and host/tools/cft-asm.c to.
//
// Then the library's own programs: assembled by the reference, loaded
// through this binding, and run against an oracle that is not either of
// them - `lowbias32` against the integer hash computed in JavaScript
// with Math.imul, and `horner-bank-fp64` (the BANK_EXT worked example,
// with its two committed banks) against a Horner loop driven through
// cft_fma. The second is the program-versus-loop identity claim on the
// one path a JavaScript caller can reach.
//
// BOTH SKIP BY NAME when Python or cft_golden is out of reach. This
// package is a wasm module and a JavaScript harness and runs where a
// toolchain does not; `make programs-check` and host/tests/seq_check.py
// are the gates that require one. A skip that says why is honest; a
// silent pass is not.

const PY = process.env.CFT_PYTHON ||
           (process.platform === "win32" ? "python" : "python3");
const ASM_REF = join(HERE, "asm_ref.py");
const PROGRAMS = resolve(HERE, "..", "..", "programs");

/** Assemble `.cfta` sources with the reference. Returns null, and says
 *  why, when the reference cannot be reached. */
function reference(spec) {
  const r = spawnSync(PY, [ASM_REF], {
    input: JSON.stringify(spec), encoding: "utf8", maxBuffer: 1 << 26,
  });
  if (r.error) return { skip: `${PY}: ${r.error.message}` };
  if (r.status !== 0)
    return { skip: `${PY} ${ASM_REF} exited ${r.status}: ` +
                   String(r.stderr).trim().split("\n").slice(-1)[0] };
  let out;
  try { out = JSON.parse(r.stdout); }
  catch { return { skip: `${PY} ${ASM_REF} did not answer JSON` }; }
  const bad = Object.entries(out.errors ?? {});
  if (bad.length)
    throw new Error(`the reference refused ${bad[0][0]}: ${bad[0][1]}`);
  return out;
}

// One program, spelled twice: as `.cfta` for the reference and as
// insn/alu/programImage calls for this package's encoder. Raw
// encodings rather than decimals in the constants, so that what is
// compared is the ENCODER and not the two character conversions.
const PAIRED = [
  {
    name: "regs32",
    // Registers above fifteen in all four fields, and on DEPOSIT.
    text: [
      ".format fp64", ".deposits 4",
      ".const ONE = 0x3ff0000000000000",
      "add r20, r0, ONE",
      "mul r4, r0, r0",
      "add r21, r20, ONE",
      "mul r6, r0, r21",
      "fma r7, r0, r21, r20",
      "deposit r21", "deposit r7", "deposit r6", "deposit r4",
      "halt", "",
    ].join("\n"),
    build: regs32Program,
  },
  {
    name: "bank-ext",
    text: [
      ".format fp64", ".deposits 1", ".bank external",
      ".const C0", ".const C1",
      "copysign r3, C0, C0",
      "fma r3, r3, r0, C1",
      "deposit r3",
      "halt", "",
    ].join("\n"),
    build: () => hornerBankProgram(),
  },
  {
    name: "rounding-and-loops",
    // The fields revision 2 did NOT move, checked in the same act: a
    // per-instruction rounding attribute, a nested REPEAT whose trip
    // count is a whole 32-bit immediate, SETACT and ACTALL.
    text: [
      ".format fp32", ".deposits 3",
      ".const HALF = 0x3f000000",
      "repeat 3",
      "  mul.rtz r5, r0, r0",
      "  add.rup r6, r5, HALF",
      "  deposit r6",
      "  setact r5",
      "endrep",
      "actall",
      "halt", "",
    ].join("\n"),
    build: () => programImage({
      formatCode: ctxs.fp32.format.code, elementBytes: 4,
      consts: [Uint8Array.from([0x00, 0x00, 0x00, 0x3f])], maxDeposits: 3,
      insns: [
        ctl("repeat", 0, 3),
        alu({ op: OP_MUL, rd: 5, ra: 0, rb: 0, rnd: 1 }),   // rtz
        alu({ op: OP_ADD, rd: 6, ra: 5, rc: 0, kc: true, rnd: 3 }), // rup
        ctl("deposit", 6),
        ctl("setact", 5),
        ctl("endrep"),
        ctl("actall"),
        ctl("halt"),
      ],
    }),
  },
  {
    name: "kx-wide-bank",
    // Twenty constants: past the sixteen a four-bit operand field
    // reaches, so the reference emits the indexed form and so must
    // this one. n_consts is 20 and the image carries none of them.
    text: [
      ".format fp64", ".deposits 1", ".bank external",
      ...Array.from({ length: 20 }, (_, i) => `.const K${i}`),
      "copysign r3, K0, K0",
      "fma r3, r3, r0, K17",
      "fma r3, r3, r0, K19",
      "deposit r3",
      "halt", "",
    ].join("\n"),
    build: () => programImage({
      formatCode: c64.format.code, elementBytes: 8,
      nConsts: 20, maxDeposits: 1, flags: FLAG_BANK_EXT,
      insns: [
        alu({ op: OP_COPYSIGN, rd: 3, ra: 0, rb: 0, ka: true, kb: true }),
        alu({ op: OP_FMA, rd: 3, ra: 3, rb: 0, rc: 17, kc: true }),
        alu({ op: OP_FMA, rd: 3, ra: 3, rb: 0, rc: 19, kc: true }),
        ctl("deposit", 3),
        ctl("halt"),
      ],
    }),
  },
];

test("this package's encoder and python/cft_golden/asm.py, byte for byte",
     () => {
  const ref = reference(PAIRED.map(({ name, text }) => ({ name, text })));
  if (ref.skip) return skip(ref.skip);
  let words = 0;
  for (const { name, build } of PAIRED) {
    const want = ref.programs[name];
    ok(want, `the reference said nothing about ${name}`);
    const got = Buffer.from(build()).toString("hex");
    if (got !== want.hex)
      throw new Error(
        `${name}: this encoder wrote\n    ${got}\n  and the reference ` +
        `wrote\n    ${want.hex}`);
    words += want.n_insns;
  }
  return `${PAIRED.length} programs, ${words} instructions, identical ` +
         `bytes (python ${ref.python})`;
});

test("the header the binding reports is the header the reference wrote",
     () => {
  const ref = reference(PAIRED.map(({ name, text }) => ({ name, text })));
  if (ref.skip) return skip(ref.skip);
  for (const { name } of PAIRED) {
    const want = ref.programs[name];
    const ctx = ctxs[want.format];
    const prog = ctx.loadProgram(Buffer.from(want.hex, "hex"));
    try {
      eq(prog.format.name, want.format, `${name}: format: `);
      eq(prog.nInsns, want.n_insns, `${name}: n_insns: `);
      eq(prog.nConsts, want.n_consts, `${name}: n_consts: `);
      eq(prog.maxDeposits, want.max_deposits, `${name}: max_deposits: `);
      eq(prog.flags, want.flags, `${name}: the header's flags word: `);
      eq(prog.bankExternal, want.bank_external, `${name}: bankExternal: `);
      // cft_program_digest against the model's own SHA-256 over the
      // same bytes. For a BANK_EXT program the image alone is not a
      // form it accepts, so this covers the carrying ones.
      if (!want.bank_external)
        eq(Buffer.from(prog.digest()).toString("hex"), want.digest,
           `${name}: the image digest: `);
    } finally { prog.free(); }
  }
  return `${PAIRED.length} headers and the digests of ` +
         `${PAIRED.filter((p) => !ref.programs[p.name].bank_external).length}`;
});

// ---- the library's programs, run against oracles that are not it -----

function libraryProgram(file, banks = []) {
  const path = join(PROGRAMS, file);
  if (!existsSync(path)) return { skip: `${path} is not there` };
  const ref = reference([{ name: file, text: readFileSync(path, "utf8"),
                           banks: banks.map((b) => Buffer.from(b).toString("hex")) }]);
  if (ref.skip) return ref;
  return { ref, info: ref.programs[file] };
}

test("programs/lowbias32-fp32.cfta on the index ramp, against the hash",
     () => {
  const got = libraryProgram("lowbias32-fp32.cfta");
  if (got.skip) return skip(got.skip);
  const { info } = got;
  eq(info.format, "fp32", "the program's format: ");
  const ctx = ctxs.fp32;
  const prog = ctx.loadProgram(Buffer.from(info.hex, "hex"));
  try {
    // --iota n: stream a is the element INDEX as a format-width integer
    // bit pattern, which is what the atlas plates take.
    const N = 4096;
    const a = new Uint8Array(N * 4);
    const dv = new DataView(a.buffer);
    for (let i = 0; i < N; i++) dv.setUint32(i * 4, i, true);
    const r = prog.run(a);

    // docs/ATLAS.md's lowbias32, computed here in plain JavaScript over
    // uint32 - a different implementation on a different machine model,
    // which is the point: IMUL is defined on 32 bits precisely so its
    // value agrees with a GPU computing it on a `uint`.
    const lowbias32 = (x) => {
      x = (x ^ (x >>> 16)) >>> 0;
      x = Math.imul(x, 0x7feb352d) >>> 0;
      x = (x ^ (x >>> 15)) >>> 0;
      x = Math.imul(x, 0x846ca68b) >>> 0;
      return (x ^ (x >>> 16)) >>> 0;
    };
    for (let i = 0; i < N; i++) {
      const bits = Number(r.deposits[i].bits & 0xffffffffn) >>> 0;
      const want = lowbias32(i);
      if (bits !== want)
        throw new Error(
          `draw ${i}: the program hashed to 0x${bits.toString(16)} and ` +
          `lowbias32 says 0x${want.toString(16)}`);
    }
    eq(r.flags, 0,
       "the whole program is integer-group and must signal NOTHING - a " +
       "draw stream that raised invalid would poison whatever ran " +
       "beside it: ");
    eq(r.status, 0, "and no lane overflowed its budget: ");
    return `${N} draws over the index ramp, bit for bit, no flags`;
  } finally { prog.free(); }
});

test("programs/horner-bank-fp64.cfta with its two committed banks", () => {
  const bankFiles = ["horner-bank-fp64.exp.bank",
                     "horner-bank-fp64.ramp.bank"];
  const paths = bankFiles.map((f) => join(PROGRAMS, f));
  if (!paths.every(existsSync))
    return skip(`${bankFiles.join(" / ")}: not in programs/`);
  const banks = paths.map((p) => new Uint8Array(readFileSync(p)));
  const got = libraryProgram("horner-bank-fp64.cfta", banks);
  if (got.skip) return skip(got.skip);
  const { info } = got;
  ok(info.bank_external, "the worked example must be a BANK_EXT image");

  const prog = c64.loadProgram(Buffer.from(info.hex, "hex"));
  try {
    eq(prog.nConsts, 24, "twenty-four coefficients addressed: ");
    eq(prog.bankBytes, 24 * 8, "and the bank each run supplies: ");
    for (const b of banks)
      eq(b.length, prog.bankBytes, "each committed bank is that size: ");

    const xs = [0.5, 1, 1.5, 2, -0.75];
    const answers = banks.map((bank) => {
      const r = prog.runBank(bank, xs);
      // The oracle: the same Horner recurrence through cft_fma, which
      // is a different path through the library - the elementwise
      // engine rather than the sequencer's ALU. docs/BENCHMARKS.md
      // calls this the program-versus-loop identity, and this is the
      // one place a JavaScript caller can check it.
      const k = [];
      const bv = new DataView(bank.buffer, bank.byteOffset, bank.byteLength);
      for (let i = 0; i < 24; i++)
        k.push(c64.fromBits(bv.getBigUint64(i * 8, true)));
      xs.forEach((x, lane) => {
        const xf = c64.from(x);
        let acc = k[0];
        for (let i = 1; i < 24; i++) acc = c64.fma(acc, xf, k[i]);
        if (hexOf(r.deposits[lane]) !== hexOf(acc))
          throw new Error(
            `x = ${x}: the program deposited ${hexOf(r.deposits[lane])} ` +
            `and the same Horner through cft_fma gives ${hexOf(acc)}`);
      });
      return r.deposits.map(hexOf).join(" ");
    });
    ok(answers[0] !== answers[1],
       "the two committed banks must give two answers - if they agree, " +
       "the bank never reached the run and one image would be one " +
       "polynomial after all");

    // And the digest is over image AND data: the reference computed one
    // per bank from the same definition.
    banks.forEach((bank, i) => {
      eq(Buffer.from(prog.digest(bank)).toString("hex"),
         info.bank_digests[i],
         `${bankFiles[i]}: cft_program_digest against the model's: `);
    });
    ok(info.bank_digests[0] !== info.bank_digests[1],
       "two banks, two digests");
    return `24 coefficients, ${xs.length} points, two banks, two answers, ` +
           `two digests`;
  } finally { prog.free(); }
});

// ---------------------------------------------------------------------

for (const f of FORMATS) ctxs[f].close();

if (summary)
  console.log(`corpus  ${summary.run} programs run, ${summary.refused} ` +
              `refused, ${summary.deposits} deposits and ` +
              `${summary.lanes} counts compared, ${summary.overflows} ` +
              `runs overflowed their deposit budget`);
for (const n of notes) console.log(`  ${n}`);
console.log(`${passed} passed, ${failed} failed` +
            (skipped ? `, ${skipped} skipped` : ""));
for (const f of failures) console.log(`  FAIL  ${f}`);
process.exit(failed ? 1 : 0);
