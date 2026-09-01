# formal/ - property proofs for the control-logic modules

The simulation benches (tb/) check the RTL against the golden model on
driven traffic; the proofs here quantify over *all* traffic, for the
handful of modules whose correctness is a control argument rather than
an arithmetic one. The golden model remains the authority on values -
nothing in this directory re-litigates numerics.

Everything runs inside one pinned container (docker/Dockerfile.formal:
Yosys 0.68+136, SBY v0.68, bitwuzla 0.9.1, from the YosysHQ
oss-cad-suite 2026-08-31 release, base image and tarball both pinned
by measured hash):

    docker build -t cft-formal -f docker/Dockerfile.formal docker
    MSYS_NO_PATHCONV=1 docker run --rm -v "$PWD:/work" -w /work \
        cft-formal ./formal/run.sh

`./formal/run.sh` from a shell with Docker does the same thing (it
re-execs itself in the image). It prints a per-proof verdict table and
exits nonzero unless every proof passes AND the negative control
fails.

## What is proven

| proof | module | claim | method |
|---|---|---|---|
| `fifo.sby prove` | rtl/cft_fifo.sv | count consistency, full/empty contract, data integrity + FIFO ordering | **unbounded** (mode prove, abc pdr), ~30 s |
| `fifo.sby cover` | rtl/cft_fifo.sv | all 8 control shapes reachable | bmc to depth 24 |
| `seedop.sby check` | rtl/cft_seedop.sv | special-case routing + decode exactness, every input | complete (comb, bmc), ~5 s |
| `seedop.sby cover` | rtl/cft_seedop.sv | all 12 operand-class antecedents satisfiable | comb cover |
| `equiv.sby check` | rtl/cft_simpleops.sv | bit-exact to the frozen pre-rewrite ref on `valid`, `d`, `flags`, for every op except 26/27 | complete (comb miter, bmc), ~2 s |
| `equiv.sby cover` | rtl/cft_simpleops.sv | the carve-out's neighbour opcodes (25, 28) still trap in both | comb cover |
| `negcontrol.sby` | rtl/cft_fifo.sv | "the head bypass was never needed" - **deliberately false, must be refuted** | bmc, cex at step 3 |

In detail:

* **cft_fifo** (at WIDTH=8, DEPTH_LOG2=3): under the module's own
  caller contract - no write at `count == DEPTH`, no read at
  `count == 0`, both assumed, nothing else constrained (`clear`,
  `rst_n`, data and enable timing all free after a t=0 reset) - for
  unbounded time: `count` equals writes-minus-reads since
  reset/clear and never exceeds DEPTH; and in every cycle with
  `count != 0`, `rd_data` is bit-for-bit the oldest unconsumed write,
  in that same cycle. The spec is a shadow FIFO built in the harness
  from port activity alone. Ordering, no-loss, no-duplication and
  no-corruption are all corollaries of every pop matching the shadow
  head. The cover task shows full, empty-after-full, both capture
  forms, the two-cycle bypass age-out, wrapped occupancy and
  mid-stream clear are each reachable, so the proof does not hold by
  excluding them.

* **cft_seedop** (at EXP_W=8, MAN_W=23): `valid` exactly on opcodes
  26/27; RECIP_SEED: NaN -> canonical qNaN, +/-inf -> +/-0,
  biased-exponent-zero (zero or subnormal - flush-at-input is the
  spec) -> +/-inf; RSQRT_SEED: NaN -> qNaN, zero-class -> +/-inf
  (sign carried), negative non-zero-class (including -inf) -> qNaN,
  +inf -> +0. Plus two envelope claims from the module's header: a
  normal operand never yields an infinity or NaN from either seed,
  and an RSQRT seed of a positive normal is strictly normal. All
  expected encodings are derived from EXP_W/MAN_W field expressions
  in the wrapper - no hand-typed hex; the only literals are the
  opcode numbers themselves, which are ISA assignments
  (python/cft_golden/softfloat.py).

* **cft_simpleops** (at EXP_W=8, MAN_W=23): the area rewrite is
  bit-identical to tb/wrappers/cft_simpleops_ref.sv - the frozen flat
  form it replaced - on all three outputs, for all 2^104 input values
  with `op != 26 && op != 27`. Those two codes were deliberately
  reassigned to cft_seedop (tb/test_simpleops.py REASSIGNED_OPS); the
  ref predates the reassignment and still traps them, so they are the
  one sanctioned divergence, excluded by assumption and bracketed by
  covers proving 25 and 28 still trap in both. This was scoped as a
  try-and-report stretch goal with a 30-minute solver budget; bitwuzla
  closed it in about two seconds.

## What is NOT proven

* **Other parameterizations.** Each proof runs one small instance
  (FIFO at 8x8, not the deployed 256x32; the float modules at the
  fp32 rung, not 11/52, 15/112, 19/236). The modules are
  parameterized and nothing in them branches on the parameter values,
  but that is an argument, not a proof. Small is complete in the
  dimension that matters for the FIFO - every control shape exists at
  DEPTH 8 and the covers prove them reachable - and the seedop
  exponent algebra is re-derived per rung by the Python side
  (test_seeds.py, exhaustively at 8/23).
* **Seed values.** This gate proves cft_seedop routes specials
  correctly; that the table entries approximate 1/x and 1/sqrt(x)
  within 2^-8.5 is python/tests/test_seeds.py's exhaustive claim, and
  table/RTL sync is test_seed_rom_sync.py's. Two gates, two jobs.
* **BRAM collision behaviour.** Formal uses Verilog semantics, where
  a same-cycle read of a written address returns the old word; on the
  fabric it is undefined (UG573), which is why the bypass exists. The
  proof shows rd_data is right in the cycles the bypass owns; it
  cannot model "undefined". The negative control demonstrates the
  bypass path is genuinely exercised by the proof's world.
* **cft_fifo outside its caller contract.** Overflow/underflow
  behaviour is explicitly unspecified (the module's header says so);
  driving it formally would prove the absence of guards the header
  already documents as absent.
* **Synthesis, timing, and everything the sim gate owns.** This is a
  source-level property gate, one more layer beside tb/ and the
  Python oracles - not a replacement for any of them.

## Why the FIFO engine is pdr, not hand-invariant k-induction

The contract assertions alone are not k-inductive; closing an
induction by hand needs strengthening invariants that name the DUT's
internals (RAM slot vs shadow slot, bypass registers vs head). Yosys's
open frontend gives formal code no path to those internals: `bind`
parses and silently binds nothing (the checker vanishes and everything
"passes"), and hierarchical references (`dut.wp`) elaborate as fresh
dangling wires. Both were tried during commissioning; the first
attempt "proved" the FIFO with zero assertions in the model. Three
consequences shape this directory:

* the proof engine for the FIFO is `abc pdr`, which synthesises the
  inductive invariant internally from the external spec - a proof by
  induction whose hypothesis the engine finds rather than a human
  writes (the price: the invariant is not a readable artifact);
* run.sh's preflight counts assertion cells in every elaborated model
  before running anything, because the frontend's failure mode for
  unsupported constructs is silence;
* the negative control is not decoration. It is the proof that the
  gate can still see an assertion fail at all.

## The negative control

negcontrol.sby asserts that a bypass-less synchronous read would have
presented the right word whenever `count` reads nonzero - the exact
claim cft_fifo's design refutes by existing. `expect fail` makes the
refutation the passing outcome; sby produces the counterexample (a
write landing at the read head, step 3) and run.sh reports the gate
dead if the refutation ever stops happening.

## Commissioning evidence

Beyond the negative control, each harness was validated against a
mutation before first commit (scratch copies, not in the tree):

* cft_fifo with the bypass mux removed (`rd_data = ram_q`): pdr
  refutes `a_head_data` with a 3-frame counterexample - the capture
  case, as the module header predicts.
* tb_seedop_formal with the rsqrt zero-class expectation flipped to
  +0: `a_rsqrt_zc` refuted (the RTL carries the operand's sign, per
  754-2019 9.2.1).
* cft_simpleops_ref with ICMPLT weakened from `<` to `<=`:
  `a_same_d` refuted.

A proof that has never been watched failing is a claim, not a gate.
