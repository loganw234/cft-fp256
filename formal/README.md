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
| `mulexact.sby fold_*` | rtl/cft_mulpass.sv | the pass fold, the tree and the level chain deliver the columns' weighted sum, at the **real 24-bit chunk**, for all 7 pass geometries | bmc over 7 enabled intervals, column registers cut |
| `mulexact.sby sel_*` | rtl/cft_mulpass.sv | on pass p the columns are handed `a` and chunk group p of `b`; the column register holds their product; an unbuilt column holds zero | bmc over 3 enabled intervals, operand and column registers probed |
| `mulexact.sby cover_*` | rtl/cft_mulpass.sv | the claims are reached with a non-zero product, a product carrying into the top bit, and every pass's selection | cover |
| `mulpass_real.sby` x4 | rtl/cft_mulpass.sv | the same exactness claim as ONE property, unfactored, at the four geometries a solver will take that way | bmc, both multipliers standing, **boolector** |
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

* **cft_mulpass** - the multi-cycle rung's exactness, at the real
  chunk width. This one has its own section, below.

## cft_mulpass: three lemmas that compose into one exactness claim

The claim is that `cft_mulpass`, which walks the multiplier's chunks
`COLS` at a time over `NP` passes, hands back the same integer the
pipe's side-by-side array builds - `sum_k (a * b[24k +: 24]) << 24k`
truncated to 2P, `cft_fpfma_pipe.sv`'s `g_mul_local` - for every pass
geometry `cft_lanes` can build, at `CFT_MUL_MCH = 24`.

**Why it is not one property.** In one assertion it is a bounded model
check with a multiplier on each side, which is the shape a SAT solver
does worst at - the 2026-09-06 entry in docs/VALIDATION.md records four
hours without a return. `formal/mulpass_real.sby` is that form at the
real chunk, and it is not hopeless: **four of the seven geometries
close that way**, including fp256 at `MUL_PASSES` = 10, the deepest the
tile builds, and those four are in the gate as unfactored checks on the
composition below. Every single-column geometry closes and so does the
smallest two-column one; the three that do not are the ones that build
three or five columns, or two columns at P = 237, and each sits on its
first asserted step until the bound expires. The 2026-09-07 entry has
the per-task times and the step each stalls on. Split into lemmas, no
lemma contains any multiplier reasoning at all, and all seven
geometries close in seconds to minutes.

**And the engine matters more than the property does.** Everything else
in this directory runs on bitwuzla, boolector's successor, which is
faster on all of it. On this one property they are not comparable:
bitwuzla did not return on `p53c1` in **sixty minutes**, and boolector
closed the same task in **twenty-nine seconds**. yices, z3 and cvc5
were tried on it too and none returned in five minutes; the AIG
engines never reached a solver, because the aiger backend rejects the
model over undefined bits. That is why `mulpass_real.sby` carries its
own `[engines]` line instead of inheriting the directory's, and why
the four tasks that are in the gate are in it at all.

**The geometries are all seven.** `cft_mulgeom.svh` maps
(P, MUL_PASSES) to (COLS, passes); `cft_lanes` builds the fp64, fp128
and fp256 rungs at P = 53, 113, 237 and MUL_PASSES 2, 5, 10 - fp32 is
one chunk and never multi-pass - which is seven distinct (P, COLS)
pairs. Each is a task. The pass count each task believes its pair has
is passed in as `EXP_NP` and re-derived inside the harness from
cft_mulgeom.svh's own functions, so a geometry table that drifts from
the header refuses to elaborate.

**Lemma A, `fold_*`** (tb_mulfold_formal.sv). Every `dut.pcol[c]` -
the column registers - is made a yosys `cutpoint`, replacing the
register and the multiplier behind it with an unconstrained `$anyseq`,
and the harness reads those free values. The claim: the in-pass tree,
the shift-accumulate with its shift-out register, the completed-product
latch and the `en`-clocked level chain deliver at LEVEL, for the
operation captured five enabled edges earlier, exactly

    sum over passes p, columns c of pcol(p, c) << 24*(COLS*p + c)

truncated to 2P - where `pcol(p, c)` is the value on `dut.pcol[c]` in
the cycle that starts at E_n + 2 + p. The reference in the harness is a
plain wide weighted sum with no shift-out and no truncation, so the
lemma is exactly "the module's clever fold equals the obvious
arithmetic". It is linear in the free values; the multiplier is not in
the netlist at all, which the .sby asserts (`select -assert-count 0
t:$mul` on the prepared model).

Two side-conditions are assumed of the free values, and lemma C proves
the real ones satisfy them: a built column is below 2^(P+24), and a
column the tree reads but the geometry does not build is zero.

**Lemma B, `sel_*`** (tb_mulsel_formal.sv). `dut.a_r` and
`dut.bsel_r` - the registered multiplier operands - are probed. The
claim, at every cycle offset in the interval: at offset p+1 the
operands are the captured `a` and chunk group p of the captured `b`;
at offset 0 they are the *previous* operation's `a` and its last chunk
group, because the module's operand registers capture pass NP-1 one
edge into the next interval. That boundary cycle is the reason the fold
runs past the interval and the level chain needs the module header's KD
argument, and it is checked rather than excluded.

**Lemma C, same tasks.** `dut.pcol[c]` is probed too, and asserted
equal to a registered copy of `probe_ar * probe_bsel[c*24 +: 24]` -
written from the DUT's own operand wires, so yosys' `opt_merge` folds
the harness's multiply onto the module's own `$mul` cell and the claim
is one register against another. The .sby asserts the merge happened by
counting cells (`COLS + 1`, the extra one being the module's
`pidx * K` group address, not `2*COLS + 1`). The same tasks assert the
two side-conditions lemma A assumes.

**The composition.** Multiplication is a function, so equal operands
give equal products. B and C give, for the cycle starting at
E_n + 2 + p,

    dut.pcol[c] = a_n * b_n[24*(COLS*p + c) +: 24]   for c < COLS
    dut.pcol[c] = 0                                  for COLS <= c < NC

Substituting into A, and using K = COLS*24 so that the two weights
collapse into one chunk index k = COLS*p + c:

    p = trunc_2P( sum over k < NP*COLS of (a_n * chunk_k(b_n)) << 24k )
      = trunc_2P( sum over k < chunks(P) of (a_n * chunk_k(b_n)) << 24k )

the second step because `b` is zero-padded to whole groups, so every
chunk past `chunks(P)` is zero. That is the side-by-side array's own
expression, term for term. QED.

**What the composition asserts rather than proves.** One thing: that
`dut.pcol[c]` in lemma A is the same wire, at the same cycles, as
`dut.pcol[c]` in lemmas B and C. Both harnesses instantiate the same
module with the same LEVEL behind the same pacer, and both index cycles
by offset from the enabled edge, so this is an identity of naming, not
of behaviour - but it is written down here because it is the seam, and
a decomposition's seam is where a wrong proof would hide.

**How the cut and the probes are made.** Not by editing or copying the
RTL: `rtl/cft_mulpass.sv` is read unmodified and no derived copy exists
anywhere in this directory. mulexact.sby flattens the design and then
uses yosys' `cutpoint` and `connect -nounset -set` on the flattened
netlist - the same frontend limitation that shaped the FIFO proof (see
the next section) means there is no in-language way to do it.
`-nounset` is load-bearing: `connect -set` defaults to unsetting every
existing driver of its left-hand side, and a bare `assign qv = {qw7,
..., qw0}` in the harness makes `qv` and `qw0` one net as far as yosys'
signal map is concerned, so the default quietly took the harness's own
concatenation apart and every proof failed on a counterexample that was
the plumbing's.

**And four unfactored checks.** `mulpass_real.sby` p53c2, p53c1, p113c1
and p237c1 assert the whole claim in one place - the module's output
against the pipe's own column-sum expression, both multipliers
standing, no lemmas and no composition. They are in the gate so that
the composition argument above has something under it that does not
depend on the composition argument, and they reach fp64 at both pass
budgets, fp128 at five and ten, and fp256 at ten.

**Runtime**, one task at a time in the pinned image on a 12-core
desktop, is in docs/VALIDATION.md's 2026-09-07 entry with the per-task
table.

## What is NOT proven

* **Other parameterizations.** The FIFO proof runs one small instance
  (8x8, not the deployed 256x32) and the two float modules run at the
  fp32 rung, not 11/52, 15/112, 19/236. The modules are parameterized
  and nothing in them branches on the parameter values, but that is an
  argument, not a proof. Small is complete in the dimension that
  matters for the FIFO - every control shape exists at DEPTH 8 and the
  covers prove them reachable - and the seedop exponent algebra is
  re-derived per rung by the Python side (test_seeds.py, exhaustively
  at 8/23). **cft_mulpass is the exception**: it is proven at the real
  24-bit chunk and at every (P, COLS) pair the tile builds, which is
  every rung and every `MUL_PASSES` value, so no width argument is
  being made for it.
* **cft_mulpass off the live rung.** The harnesses pace at exactly the
  lane's own NP, which is what `cft_lanes` gives the live rung. The
  module's header says a lane seeing a LONGER enabled period still
  produces the right product (its pass counter saturates and it folds
  zeros) and a lane seeing a shorter one produces garbage that nothing
  reads. Neither is proven here; only the live rung's pacing is.
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
* run.sh checks for assertion cells twice - once before anything runs,
  on the four single-file harnesses, and once per task afterwards on
  the model sby actually built and solved - because the frontend's
  failure mode for unsupported constructs is silence;
* the negative control is not decoration. It is the proof that the
  gate can still see an assertion fail at all.

The cft_mulpass proofs need the same internals the FIFO proof could
not reach, and get them the other way: outside the language, in the
yosys script, after `flatten`. `cutpoint` replaces a net's driver with
an unconstrained value and `connect -nounset -set` aliases a harness
wire onto a flattened internal one. Both fail loudly rather than
silently - `connect` aborts on a name it cannot resolve, and a probe
that never attached is left undriven, which sby's own model build turns
into an unconstrained `$anyseq` (`design_prep.ys`:
`setundef -undriven -anyseq`), so its assertion is refuted rather than
vacuously satisfied.

## Vacuity, checked twice

The preflight at the top of run.sh elaborates each single-file harness
and counts the `$check` cells with `FLAVOR=assert` that survive `prep`.
It cannot cover mulexact.sby, whose model only exists after a flatten,
a cutpoint and a set of `connect` commands; mirroring those in a second
script would be a copy to drift.

So every task, old and new, is checked again after it runs, on
`<workdir>/model/design_prep.il` - the netlist sby hands the engine.
Its `$assert` and `$cover` cells are counted against a stated minimum
and a task whose checks were silently dropped fails the gate even
though the engine said pass. The minimums are minimums, so adding a
property never breaks the gate; the guarded failure mode is wholesale
silent loss.

That check earned itself during this work. `chparam` with a selection
that matches nothing is silent, and an early version of mulexact.sby
ran every task at the harness's default geometry and passed. The fix
is in the harnesses (`EXP_NP`, re-derived and refused on a mismatch)
rather than the gate, but the lesson is the same one: a proof that
cannot say which design it proved is not evidence.

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

The cft_mulpass decomposition was validated the same way, and more of
it, because a decomposition can be wrong in a way one property cannot:
each lemma can pass while the seam between them leaks. Six mutations,
five in rtl/cft_mulpass.sv and one in the harness itself, each applied
to a scratch copy and run against the task that ought to catch it. All
six were refuted:

| mutation | caught by | refuted at |
|---|---|---|
| `acc <= s[P+K:K]` clears bit 3 - one carry dropped per pass | `fold_53c1`, `fold_53c2` | step 19, step 13 |
| the shift-out register keeps one stale low bit | `fold_53c1` | step 19 |
| the level chain is read one enabled edge short | `fold_53c1` | step 19 |
| the chunk group is selected one pass early (`pidx + 1`) | `sel_53c1`, `sel_53c2` | step 7, step 5 |
| a column multiplies the wrong chunk of its own group | `sel_53c2` | step 5, on two columns at once |
| **the harness's** own pass window is one cycle late (`ed[2]`) | `fold_53c1` | step 19 |

The last row is the one that matters most. It mutates nothing in the
RTL: it moves the reference's idea of which cycles belong to which
operation. If lemma A were checking only arithmetic and not timing, it
would still have passed. It failed, so the fold's alignment to the
enable is inside the claim.

The fifth row is the second-most useful. Lemma C's reference product is
written to be structurally identical to the module's own multiply so
that opt_merge collapses them; a mutation that makes them differ could
in principle turn the proof into a genuine two-multiplier equivalence
and time out rather than fail. It did not - bitwuzla refuted it in
seconds, on two columns at once.

A proof that has never been watched failing is a claim, not a gate.
