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
`det_div`, `det_mod`, `det_scale48`. Across them: 42 `fma`, a handful
of `abs`/`min`/`max`/`clamp`, four ternaries, integer shifts, masks and
xors on the bit patterns, one `floor`, one `isnan`, one `isinf`, and
104 bit-pattern constants written as `uintBitsToFloat(0x...)`. No raw
`sqrt`, `log2` or `atan` survives outside a comment. The census below
is against the sequencer's ISA (docs/SEQUENCER.md): 30 ALU opcodes,
per-instruction rounding, 16 registers per lane, three input streams,
16 addressable constants, `REPEAT`/`ENDREP`/`SETACT`/`DEPOSIT`/`HALT`,
loops four deep, 1,024 instructions per image.

| the emitted GLSL uses | on the tile | notes |
|---|---|---|
| `precise` fma, `+`, `-`, `*` | `FMA`, `ADD`, `SUB`, `MUL` at fp32, RNE, denormals kept | bit-exact by construction; the tile is what the discipline assumes a GPU is |
| the thirteen det functions | inlined sequences of the above plus the integer opcodes | the "det_* to program port": the same generator (`tools/gen-detlib.mjs`) grows a second output |
| `abs`, `min`, `max`, `clamp` | `ABS`, `MIN`, `MAX`, `MIN`+`MAX` | GLSL leaves `min`/`max` with a NaN undefined; the det discipline keeps NaN out, the parity harness confirms it |
| ternary, `if`/`else` on values | `CMPLT`/`CMPLE`/`CMPEQ` + `SELECT`, branchless | the emitter already refuses a draw inside a conditional, so both arms evaluating is invisible |
| `floor` (once, in `det_mod`) | add and subtract 2^23 under a directed rounding, selected against \|x\| >= 2^23 where the value is already integral | exact everywhere; only the inexact flag differs, and flags are not part of the parity |
| `isnan`, `isinf` | `CMPEQ(x, x)`; mask and compare on the encoding | one instruction each |
| `floatBitsToUint`, `uintBitsToFloat` | nothing - the same register | free, as CAPABILITIES.md says |
| `^`, `&`, `\|`, `<<`, `>>`, `+` on `uint` | `IXOR`, `IAND`, `IOR`, `ISHL`, `ISHR`, `IADD` | present since 0x300 |
| `s.orbit` with `until` | `REPEAT n` ... `SETACT(!until)` ... `ENDREP`, the count and the escape flag in registers | the model the sequencer was built for; the emitter's unroller becomes unnecessary |
| `sum(n, term)` | a `REPEAT` accumulating into a register | per lane, no cross-lane reduction needed |
| `s.deposit({xyz, col, glow})` | up to seven `DEPOSIT`s per sample, index-addressed | the fixed-order deposition GPUs cannot promise; binning into the plate is a separate step, below |
| `P[8]`, `uT`, `TAU`, `PI` | the constant bank | 11 of the 16 addressable slots gone before any coefficient |

Two operations do not map, and both sit in the stream rather than in
the arithmetic:

- **The draw hash is `lowbias32`**: `x ^= x >> 16; x *= 0x7feb352d;
  x ^= x >> 15; x *= 0x846ca68b; x ^= x >> 16`, plus one more multiply
  in the per-sample seeding. Two 32-bit integer multiplies per draw.
  The ISA has no integer multiply. It cannot be built from the float
  opcodes either, because a 32x32-bit product exceeds the 24-bit
  significand and the conversions that a split-product route would
  need are host operations.
- **The uniform is `float(x) * 2^-32`**: an integer-to-float
  conversion, which is `cft_cvt_from_u32` on the host and not an
  opcode. This one IS expressible in-lane: split `x` into two 16-bit
  halves, make each an exact float by OR-ing it under `0x4b000000` and
  subtracting 2^23, then `fma(hi, 65536, lo)` rounds the true value
  once, which is what a conforming `float(uint)` does. Six instructions
  per draw, and the parity harness is what proves the GPUs' conversion
  is the same rounding.

## What the program model lacks for this workload

The five workloads of docs/BENCHMARKS.md found six asks of the program
model (docs/SEQUENCER.md, last section). The atlas port needs three of
them and adds one:

1. **An integer multiply.** `IMUL`, 32-bit low product, the next free
   opcode (30), in the integer group. Four 16-bit partial products on
   the DSPs the tile is not short of; a golden-model definition of one
   line; the softfloat, the RTL and a cocotb target. Without it every
   draw goes to the host, and the number of draws per sample is
   data-dependent inside an orbit, so "host-fed randomness" needs the
   per-iteration stream read the zoom workload asked for. With it, the
   whole stream is in-lane and the three input streams are enough.
2. **Immediate constants.** Bit 30 of the instruction word is reserved
   and `imm` is 32 bits wide and unused by ALU instructions - exactly
   an fp32 constant. An "operand C is `imm`" form removes the
   sixteen-constant wall the enclose workload hit: `hopf` alone wants
   eleven constants before its first coefficient, and an inlined
   `det_sincos` carries a dozen more. This is the single change that
   turns chunked programs into one program per positive.
3. **More inputs than three.** The registry contract delivers seven
   per-sample values - `q.x`, `q.y`, four in `rnd`, `seed` - before a
   single lever. The orbits workload asked for register loading from a
   per-lane block; here the block is seven wide and fixed by the
   contract.
4. **Code size and subroutines.** No `CALL`, so every det function
   inlines at each use. `hopf` makes twelve sine or cosine calls;
   inlined `det_sincos` is on the order of forty instructions, so
   `hopf` is roughly 600 instructions, `buddha` with its two nested
   loops more, against an image capacity of 1,024. The emitter's
   existing `det_sincos` hoist (one call where the plate wrote several)
   is the first remedy and is already measured on the GPU; a `CALL`
   with a return address register is the durable one and is not in
   the ISA today.

None of these is deep. Together they are a VERSION step for the
sequencer (a new opcode, a new instruction form, a wider input block,
optionally a call), with the golden model first as always.

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
2. **`IMUL` and immediate constants** (cft-fp256): model, softfloat,
   RTL, cocotb, CAPS and VERSION; the API gains nothing, since a
   program image is data. The immediate form is what lets step 3 emit
   one image per positive.
3. **The emitter target** (atlas-engine): `core/emit-cft.mjs` from the
   same parse, producing the image, the constant bank, the seven-wide
   input block and the deposit schema; a runner in cft-fp256
   (`host/tools/positive-run.c`, on the pattern of the workload tools:
   resumable, checkpointed, chained) that runs the image on either
   backend and bins the records; the golden-model oracle from
   `seq.py`. `hopf` and `jong` first, as the README says.
4. **The wider input block and, if the budgets demand it, `CALL`**
   (cft-fp256), which step 3 will have measured the need for on the
   sixty-eight positives rather than guessed.
5. **The GPU record capture and the per-sample comparison**
   (atlas-engine), then the negative's hash beside the matrix.

Steps 1 and 3 need no hardware and no ABI change; they are the
"det_* to program port and the parity harness against the GLSL bits"
that CAPABILITIES.md has called startable since 2026-09-01. Step 2 is
the first RTL this workload asks for, and it is small.
