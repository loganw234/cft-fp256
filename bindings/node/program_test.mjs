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

import { Context } from "./index.mjs";
import { STATUS_DEPOSIT_OVERFLOW } from "./lib.mjs";
import { CTRL, ctl, insn, programImage, readCorpus, replayCorpus }
  from "./seq_corpus.mjs";

const OP_SUB = 2;                 // cft_op: SUB reads ra and rc (cft.h)

let passed = 0, failed = 0;
const failures = [];

function test(name, fn) {
  try { fn(); passed++; }
  catch (err) { failed++; failures.push(`${name}: ${err.message}`); }
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

for (const f of FORMATS) ctxs[f].close();

if (summary)
  console.log(`corpus  ${summary.run} programs run, ${summary.refused} ` +
              `refused, ${summary.deposits} deposits and ` +
              `${summary.lanes} counts compared, ${summary.overflows} ` +
              `runs overflowed their deposit budget`);
console.log(`${passed} passed, ${failed} failed`);
for (const f of failures) console.log(`  FAIL  ${f}`);
process.exit(failed ? 1 : 0);
