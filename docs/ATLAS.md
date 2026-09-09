# The atlas-engine integration: what a backend swap needs

atlas-engine (`../atlas-engine`, MIT) is the workload this tile exists
to serve: a language for platonography whose programs, the
**positives**, are evaluated by depositing points of light until the
measure shows. This file is the assessment made before any of it was
built (2026-09-04): where the seam is, what maps onto the tile as it
stands, what does not, and the order of work. The positives themselves
do not change; that is the first and most important finding.

## The seam

A positive is JavaScript in a deliberately small subset - `const`,
`let`, assignment, `if`/`else`, `return`, arithmetic, comparisons,
ternaries, `Math.*` from a fixed list, and a vocabulary: `s.u()` for a
uniform draw, `s.orbit(n, state, step, {until})` for a bounded
iteration with an escape test, `sum(n, term)` for a reduction,
`s.deposit({xyz, col, glow})` for the one deposit. Loops are
vocabulary, never `for`. The same source is RUN by the CPU evaluator
(`core/measure.mjs`, float64, an accuracy reference) and READ by the
emitter (`core/emit.mjs`), which writes pinned GLSL against the
registry contract:

    vec3 shape_<id>(vec2 q, vec4 rnd, uint seed, float P[8], out vec3 col)

with `uT` (the clock) a uniform. Pinned means every arithmetic
operation is single-rounded `precise` fma, add, subtract or multiply,
every transcendental is one of the det library's thirteen functions
built from those, every selection is exact, and the stream of draws is
an integer hash on the bit patterns. That discipline is what gives the
engine one hash across four GPU vendors (its docs/DETERMINISM.md), and
it is exactly the contract this tile implements natively.

So the backend swap is a second emitter target. A positive parses once;
today it becomes GLSL for a GPU, and the new target makes it a
sequencer program image, a constant bank, a stream layout and a deposit
schema for `cft_program_run` - the software backend now, the tile when
a card is in. Nothing upstream of the emitter moves, and nothing
downstream of the deposit changes its meaning.

## What maps, operation by operation

The det library is thirteen functions in 17 KB of GLSL: `det_sin`,
`det_cos` (both through one `det_sincos`), `det_tan`, `det_atan`,
`det_acos`, `det_exp2`, `det_log2`, `det_pow`, `det_sqrt`, `det_recip`,
`det_div`, `det_mod`, `det_scale48`. Across them: 56 `fma` sites (this census first said 42; the
generator rewrites all 56, counted 2026-09-07), a handful
of `abs`/`min`/`max`/`clamp`, four ternaries, integer shifts, masks and
xors on the bit patterns, one `floor`, one `isnan`, one `isinf`, and
104 bit-pattern constants written as `uintBitsToFloat(0x...)`. No raw
`sqrt`, `log2` or `atan` survives outside a comment. The census below
is against the sequencer's ISA as it stood when the census was taken
(docs/SEQUENCER.md): 30 ALU opcodes, per-instruction rounding, 16
registers per lane, three input streams, 16 addressable constants,
`REPEAT`/`ENDREP`/`SETACT`/`DEPOSIT`/`HALT`, loops four deep, 1,024
instructions per image. Two of the four gaps it found were closed on
2026-09-07 and are marked below; the census is left as it was written,
because what it found is the reason they were closed.

| the emitted GLSL uses | on the tile | notes |
|---|---|---|
| `precise` fma, `+`, `-`, `*` | `MUL` then `ADD` for every `fma`; `ADD`, `SUB`, `MUL` at fp32, RNE, denormals kept | **the shipped library is unfused**: `gen-detlib` rewrites all 56 `fma` calls before the byte comparison that proves it identical to the darkroom's, so an `fma` is two roundings. Emitting `FMA` was tried on 2026-09-07 and gives 3,834 one-ULP differences across 14 of 19 functions (worst `det_mod`, 1,441 of 4,096 points): it saves 197 of 1,321 instructions and computes a different library |
| the thirteen det functions | inlined sequences of the above plus the integer opcodes | the "det_* to program port": the same generator (`tools/gen-detlib.mjs`) grows a second output |
| `abs`, `min`, `max`, `clamp` | `ABS`; `min`/`max` as `CMPLT`+`SELECT`, not the `MIN`/`MAX` opcodes | GLSL (8.1) defines `min`/`max` as comparisons, and 754's `minimum`/`maximum` differ from them on a NaN: the opcodes gave 36 mismatches in `det_atan` at `det_atan(+0, NaN)` on 2026-09-07, the compare-and-select form none, at 8 extra instructions across the library |
| ternary, `if`/`else` on values | `CMPLT`/`CMPLE`/`CMPEQ` + `SELECT`, branchless | the emitter already refuses a draw inside a conditional, so both arms evaluating is invisible |
| `floor` (once, in `det_mod`) | add and subtract 2^23 under a directed rounding, selected against \|x\| >= 2^23 where the value is already integral | exact everywhere; only the inexact flag differs, and flags are not part of the parity |
| `isnan`, `isinf` | `CMPEQ(x, x)`; mask and compare on the encoding | one instruction each |
| `floatBitsToUint`, `uintBitsToFloat` | nothing - the same register | free, as CAPABILITIES.md says |
| `^`, `&`, `\|`, `<<`, `>>`, `+` on `uint` | `IXOR`, `IAND`, `IOR`, `ISHL`, `ISHR`, `IADD` | present since 0x300 |
| `s.orbit` with `until` | `REPEAT n` ... `SETACT(!until)` ... `ENDREP`, the count and the escape flag in registers | the model the sequencer was built for; the emitter's unroller becomes unnecessary |
| `sum(n, term)` | a `REPEAT` accumulating into a register | per lane, no cross-lane reduction needed |
| `s.deposit({xyz, col, glow})` | up to seven `DEPOSIT`s per sample, index-addressed | the fixed-order deposition GPUs cannot promise; binning into the plate is a separate step, below |
| `P[8]`, `uT`, `TAU`, `PI` | the constant bank | 11 of the 16 addressable slots gone before any coefficient - 11 of 256 since indexed constants |

Two operations do not map, and both sit in the stream rather than in
the arithmetic:

- **The draw hash is `lowbias32`**: `x ^= x >> 16; x *= 0x7feb352d;
  x ^= x >> 15; x *= 0x846ca68b; x ^= x >> 16`, plus one more multiply
  in the per-sample seeding. Two 32-bit integer multiplies per draw.
  The ISA had no integer multiply. It cannot be built from the float
  opcodes either, because a 32x32-bit product exceeds the 24-bit
  significand and the conversions that a split-product route would
  need are host operations. **`IMUL`, opcode 30, closed this on
  2026-09-07** - the hash is eight instructions and four constants as
  a program, and the golden model, libcft and `cft_simpleops` all run
  it, checked against Python's own integers at every format.
- **The uniform is `float(x) * 2^-32`**: an integer-to-float
  conversion, which is `cft_cvt_from_u32` on the host and not an
  opcode. This one IS expressible in-lane: split `x` into two 16-bit
  halves, make each an exact float by OR-ing it under `0x4b000000` and
  subtracting 2^23, then `fma(hi, 65536, lo)` rounds the true value
  once, which is what a conforming `float(uint)` does. Nine
  instructions per draw as emitted - eight for the unfused
  `float(uint)`, seven if fused, plus the 2^-32 multiply - and the
  parity harness is what proves the GPUs' conversion is the same
  rounding.

## What the program model lacks for this workload

The five workloads of docs/BENCHMARKS.md found six asks of the program
model (docs/SEQUENCER.md, last section). The atlas port needs three of
them and adds one:

1. **An integer multiply. BUILT 2026-09-07.** `IMUL`, 32-bit low
   product, the next free opcode (30), in the integer group. Three
   16x16 partial products in `cft_simpleops` - the fourth lands
   entirely above bit 31 and is not computed - so it is off the fp
   datapath and rides the precomputed-result sideband the rest of the
   integer group already uses. `softfloat.py`'s `imul()` is the
   one-line definition; `host/src/softfloat.c` is the port;
   `tb/test_simpleops.py`'s `test_imul` and `tb/test_seq_core.py`'s
   `indexed_constants_and_imul` are the benches, and `formal/imul.sby`
   proves the three partial products equal a truncated 32x32 multiply
   over every input at fp32's width. The whole draw stream is now
   in-lane and the three input streams are enough.
2. **Indexed constants. BUILT 2026-09-07.** Bit 30 of the instruction
   word was reserved and `imm` is 32 bits wide and unused by ALU
   instructions. The form built is an INDEX rather than a value - `kx`
   sets the three operands' constant indices from `imm[7:0]`,
   `imm[15:8]` and `imm[23:16]`, and the bank grows to 256 - which is
   what serves both this port and the fp256 enclosure tool, where an
   immediate would have had to be a format-width value and could not
   have. `hopf`'s eleven constants and an inlined `det_sincos`'s dozen
   are now eleven and twelve of 256 rather than of sixteen. Measured
   on the enclose workload: 16 chunk programs to 1 at degree 127, 144
   library calls to 9, arithmetic intensity 6.6 to 102.6 operations
   per element moved against a K ~ 30 crossover, and the same SHA-256
   chain at every format. docs/ENCLOSE.md carries the numbers.
3. **More inputs than three.** The registry contract delivers seven
   per-sample values - `q.x`, `q.y`, four in `rnd`, `seed` - before a
   single lever. The orbits workload asked for register loading from a
   per-lane block; here the block is seven wide and fixed by the
   contract. Measured 2026-09-07: no det function takes three
   inputs, so this is the positive's ask and not the library's.
4. **Code size and subroutines.** No `CALL`, so every det function
   inlines at each use. `hopf` makes twelve sine or cosine calls;
   inlined `det_sincos` is 53 image words as emitted on 2026-09-07
   (`det_pow` 243; all nineteen functions together 1,362), so `hopf`
   is 541 words and `jong` 466 - both fit - while 28 of the 69
   positives are already over the 1,024-word image on their det_*
   calls alone (median 707, the worst 10,100). One more limit the
   census missed: `det_pow` needs 17 registers of the 16 a lane has,
   after the best of four schedules; every other function fits, the
   largest at 11. The emitter's
   existing `det_sincos` hoist (one call where the plate wrote several)
   is the first remedy and is already measured on the GPU; a `CALL`
   with a return address register is the durable one and is not in
   the ISA today. **The two capacities are BUILT 2026-09-08**, as
   revision 2 of the sequencer (docs/SEQUENCER.md): 4,096
   instructions through the CAPS field that already published the
   depth, and thirty-two registers a lane through five-bit register
   fields whose fifth bits sit in `imm[27:24]`, behind CAPS[5].
   Measured out of context on the U50 part at 135 MHz, the doubled
   file costs nothing - the block RAM was already deep enough - and
   the deeper instruction memory landed in an UltraRAM the tile was
   not using: 119,915 LUT against 120,173, WNS +1.196 ns both ways.
   So all but the worst handful of positives fit without `CALL`,
   `det_pow`'s seventeenth register exists, and the init block is
   not needed as an escape hatch.
5. **The constant bank as per-run data. BUILT 2026-09-08.** Every
   positive's image would have carried the eight levers, the clock
   and the pass data as constants, so every change was a new program
   and a reload - 256 passes on each of 16 supertiles a plate. Now the
   header's first reserved word is `flags`, bit 0 says the image
   carries no constants, a `BANK_PTR` register (0x64/0x68, kernel
   argument 8, VERSION 0x700) supplies them per run, and the host has
   `cft_program_run_bank` beside `cft_program_run` and
   `cft_program_digest`, SHA-256 over image and bank together, as the
   attestation. One image per positive, loaded once, with levers,
   clock and pass riding as data; the emitter's plan to put the
   per-run values at the tail of the bank in a fixed order makes the
   split a boundary and not a re-emit, exactly as it intended.

None of these is deep. Four of the five are built - the first two on
2026-09-07, the two capacities and the per-run bank on 2026-09-08 -
golden model first as always, and published as CAPS bits ([28] for
`IMUL`, [4] for `kx`, [5] for the registers, [6] for the bank) because
VERSION guards the register map and features are announced in CAPS;
the bank did step VERSION, to 0x700, because it added a register to
the map. `cft_program_load` refuses an image that uses any of them on
a device that does not publish it, by name, so a host asks rather than
guesses. The wider input block is withdrawn by its requester: with
`IMUL` in, every per-sample value the shape contract hands a plate is
integer arithmetic in-lane over the index ramp, about 65
instructions, and a positive's program takes one stream and leaves
two free. The optional `CALL` remains, measured rather than guessed:
at 4,096 words all but the worst handful of positives fit without it.

### The second round: what stops the other thirty. BUILT 2026-09-08, evening

atlas-engine's docs/CFT-GAPS.md measured, over the scheduled programs
of the corpus, what stops the thirty positives that do not fit
revision 2: thirty over thirty-two registers as scheduled (twenty-three
still over with every per-run value hoisted into the bank, five of
them above sixty-four - `throughput` 183, `vlsi` 134, `rule30` 128,
`threebody` 102, `universal` 91 - and those are live values carried
through a loop, not scheduling slack), six over 4,096 words (the
largest, `throughput`, 12,618), and two over 256 constants
(`throughput` 464 with the hoisted frontier in the bank, `vlsi` 318).
It asked for three things. Revision 3 of the sequencer
(docs/SEQUENCER.md, R4 to R7; docs/PROGRAMS.md for the text form)
builds the three and one more, golden model first as always:

6. **A per-lane spill memory. BUILT.** 256 slots a lane, the lane's
   own, reached by four control codes: `STL`/`LDL` by a static slot
   in the immediate, `STX`/`LDX` by a register's low bits reduced
   modulo the depth. A store is a register write for the active
   mask's purposes, a load writes `rd`, neither rounds or raises a
   flag. Published as log2 depth in CAPS2[3:0] behind CAPS2[4]
   (`CFT_SEQ_FEAT_SCRATCH`), read as `cft_caps.max_scratch`, refused
   by name where absent. The spiller is the engine's; the memory
   and the `stl`/`ldl` mnemonics are here, with a forty-term spill
   held to the same arithmetic without one in the program library.
7. **The image to 16,384 words. BUILT.** Through the CAPS field that
   already published the depth, as revision 2's 4,096 was. It holds
   every positive as it lowers today, with room for the spills.
8. **The bank to 512. BUILT.** Under `kx`, `imm[28]`, `imm[29]` and
   `imm[30]` are the ninth bits of the three constant indices - the
   construction of R1's fifth register bits - behind CAPS[7]
   (`CFT_SEQ_FEAT_KX9`), `KMEM_D` 512; `imm[31]` stays reserved as
   the next version guard. A revision-2 tile would read eight bits
   and address the wrong constant in silence, which is why this took
   a CAPS bit and not only the reserved-bit rule.
9. **The scratch as a per-run block, in and out.** Not asked this
   round, but two older asks - the init block, and the orbits
   workload's per-lane register load - are one mechanism once the
   scratch exists: the header's second reserved word carries
   `n_scratch_in` and `n_scratch_out` under flags bit 1, the host
   preloads the first slots of every lane from a lane-major buffer
   before the first instruction and reads the first slots back after
   the last deposit, through `SCRATCH_IN_PTR` and `SCRATCH_OUT_PTR`
   (0x70/0x74 and 0x78/0x7C, kernel arguments 9 and 10; the map grew,
   so VERSION is 0x800; CAPS2[5], `CFT_SEQ_FEAT_SCRATCH_IO`). On the
   host, ABI 0.10's `cft_program_run_ex` takes everything a run
   carries in one `cft_run_args`, and the two older calls are
   wrappers over it, so the positional signatures stop growing by an
   argument a round. A program run twice with its state carried out
   and back in, held to one longer run, is the library's check.

Measured and not asked, as that file says and this one keeps:
`CALL` (41,435 words of inlined copies across the corpus, 2,065 of
them in `throughput`, which it would still leave at 8,330 - so it
halves most images and decides no positive's fit once the image is
16,384), the active mask scoped to a loop (six positives' inner
loops, bounds 6 to 32; `SETACT` at the top level already serves the
other forty-two and the engine did that the same evening), and a
per-sample clock (0 to 3 bank slots a positive when the shutter is
open). What the engine does next is its own list in that file:
hoisting the per-run frontier into the bank, copy coalescing, then
the spiller against item 6 and the parity harness behind it.

## Deposition, the half the tile does not do yet

On a GPU the deposit is a float atomic into the plate, and the order
in which warps arrive is the one thing the det discipline cannot pin;
the darkroom lives with it per program. The sequencer deposits
index-addressed records per lane - `xyz`, `col`, `glow`, the orbit's
count - and stops there. Binning those records into a negative is a
fixed-order accumulation that the host does deterministically today
(the software tier), and that a scatter-add accumulator on the tile
would do tomorrow; the reduction accumulator's tree is the model for
how such a thing stays contractual. For the parity question that
ordering does not matter: parity is claimed on the deposited records,
sample by sample, and a negative built from identical records in a
fixed order is identical.

## The parity harness

The one-hash matrix compares negatives across GPUs. The tile joins it
in two steps:

- **Records against the golden model.** The program the emitter writes
  is data; `python/cft_golden/seq.py` evaluates it exactly, so every
  positive gets an oracle that is not a GPU: the records the model
  computes for a sample budget are the records libcft's software
  backend and the tile must reproduce bit for bit. This is the same
  lattice every other operation here sits in.
- **Records against the GPU.** A debug variant of the emitted GLSL that
  writes `xyz`, `col` and `glow` to a buffer instead of depositing
  gives the GPU's own records for the same samples, and the comparison
  is per sample rather than per negative, which is the only way a
  first divergence gets named. Where they differ, the discipline's
  own findings say where to look first: `length()` (which the emitter
  trusts but GLSL does not pin), `float(uint)`'s rounding, and a
  `min`/`max` that saw a NaN.

Then the negative: bin the records in index order, hash, and the tile
is one more column in atlas-engine's matrix, with the fixed-order
deposition that column alone can claim.

## Order of work

1. **The det library's second edition** (atlas-engine, software only):
   `tools/gen-detlib.mjs` gains an ISA target that turns
   `core/detlib.glsl.template` into instruction sequences with the
   register discipline written down, plus `u2f` as the six-instruction
   conversion and the two integer-multiply sites marked as needing
   `IMUL`. Verified function by function against the pinned GLSL on a
   sweep of arguments, through libcft's software backend.
   **Done 2026-09-07**, on atlas-engine's branch `cft-detlib` (commit
   af5feda, unmerged, for review): `gen-detlib --target cft` emits
   all nineteen functions - the thirteen det_*, their four helpers,
   `u2f`, `hashu` - with the register discipline written down in
   that repository's docs/CFT-DETLIB.md, and
   `tools/verify-cft-detlib.mjs` holds every one bit-identical to
   the shipped library on 4,096-point sweeps through libcft's
   software backend, `hashu` with its two `IMUL`s emulated since the
   opcode does not exist yet. It corrected this document three times
   on the way (the table above): the library is unfused, `min`/`max`
   are comparisons, `u2f` is nine instructions. Eleven of the
   nineteen need indexed constants (`det_div` lands on exactly 16,
   `det_pow` wants 43; 77 distinct constants in all, inside
   `KMEM_D`'s 256), `hashu` alone needs `IMUL`, and `det_pow` alone
   needs a seventeenth register.
2. **`IMUL` and indexed constants** (cft-fp256): model, softfloat,
   RTL, cocotb, CAPS and VERSION; the API gains nothing, since a
   program image is data. **Done on 2026-09-07 except CAPS and
   VERSION, which are the integrator's** - the model, libcft,
   `cft_simpleops`, `cft_seq`, three benches, a formal proof and the
   enclose measurement are in; `cft_caps` does not yet publish either
   feature and the sequencer VERSION has not been stepped, so a host
   still cannot ask a device whether its bitstream carries them. The
   indexed form is what lets step 3 emit one image per positive.
3. **The emitter target** (atlas-engine): `core/emit-cft.mjs` from the
   same parse, producing the image, the constant bank, the seven-wide
   input block and the deposit schema; a runner in cft-fp256
   (`host/tools/positive-run.c`, on the pattern of the workload tools:
   resumable, checkpointed, chained) that runs the image on either
   backend and bins the records; the golden-model oracle from
   `seq.py`. `hopf` and `jong` first, as the README says.
   **The runner exists (2026-09-08)**: `host/tools/positive-run`
   takes an image file, `--iota n` or raw streams, an optional bank,
   and prints the counts, the flags, the program digest and the
   deposit buffer's SHA-256, on the software backend, in emulation
   and on the card alike (docs/PROGRAMS.md). The emitter target on
   the atlas side is the open half of this step.
4. **`CALL`, if the budgets demand it** (cft-fp256), which step 3
   measures on the sixty-eight positives rather than guesses; the
   wider input block is withdrawn (item 3 above) and the two
   capacities that were the other half of this step are built.
   Measured 2026-09-08, evening (atlas-engine's docs/CFT-GAPS.md):
   41,435 words across the corpus, and it decides no positive's fit
   once the image is 16,384 - so it stays optional with its number
   known, and the second round's spill memory, deeper image and
   wider bank (items 6 to 9 above) are built in its place.
5. **The GPU record capture and the per-sample comparison**
   (atlas-engine), then the negative's hash beside the matrix.

Steps 1 and 3 need no hardware and no ABI change; they are the
"det_* to program port and the parity harness against the GLSL bits"
that CAPABILITIES.md has called startable since 2026-09-01. Step 2 is
the first RTL this workload asks for, and it is small.
