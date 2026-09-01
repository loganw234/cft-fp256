# Capabilities

An honest inventory of what this tile can and cannot do, measured
against IEEE 754-2019 and against the workload it was built to serve.

**The empty boxes are the point.** This file exists so that "is it
general purpose yet?" has an answer you can check rather than a
feeling. For a long time the honest answer was *a very good
fused-multiply-add engine and not more*. As of 2026-08-31 the six
required arithmetic operations all exist and are proven; as of
2026-09-01 the REST of clause 5 does too - roundToIntegral, the
conversions, scaleB/logB, nextUp/nextDown, classification,
totalOrder, the signaling comparisons, remainder - every one with
zero new RTL, which is the composition methodology paying out. The
word "general purpose" now hangs on programmability alone, and the
boxes below say exactly where.

| mark | meaning |
|---|---|
| **yes** | in the RTL and verified bit-exact against the golden model, in simulation and through the real XRT stack |
| **composed** | the hardware supplies the primitive; libcft composes the full operation as a fixed sequence of those calls, identical on every backend, with the integer bookkeeping done exactly on the host - the same division of labour the multi-tile reduction fold uses. Bit-identical to the contract |
| **library** | in libcft and defined by the golden model, but the operation contains NO floating-point arithmetic at all - it is rounding-position bit surgery - so there is no backend pass to issue and nothing for a tile to accelerate. Bit-identical on every backend by construction |
| **model** | defined in `python/cft_golden` and covered by conformance vectors, but no hardware - a host can use it, the tile cannot |
| **no** | not implemented anywhere |
| **out** | deliberately excluded; the reason is given |

Anything marked **yes** or **composed** is bit-identical across every
device that implements this contract - that is the whole product.
Anything marked **no** is not slow here, it is *absent*: the host must
do it. You can check the central claim yourself with a browser and
nothing else: https://loganw234.github.io/cft-fp256/ replays the
published conformance vectors through the real library compiled to
WebAssembly.

## Formats

| format | status | notes |
|---|---|---|
| binary32 (fp32) | **yes** | 8 lanes per beat |
| binary64 (fp64) | **yes** | 4 lanes per beat |
| binary128 (fp128) | **yes** | 2 lanes per beat |
| binary256 (fp256) | **yes** | 1 per beat; 237-bit significand |
| binary16 (fp16) | **no** | would fit the ladder; nothing needs it yet |
| bfloat16, TF32, FP8 | **out** | not interchange formats. Identity needs one definition per width, and these have several |
| decimal64/128 | **out** | a different arithmetic, not a wider one |

A build may drop the fp64/fp128/fp256 banks (`EN_FP64` and friends) or
narrow the beat itself (`BEAT_BITS`); what remains is advertised in
CAPS and behaves identically on the rungs it keeps. A MODE selecting a
precision the build lacks is **refused** - STATUS[3], engine never
starts, no memory touched - rather than answered with plausible
garbage from banks that are not there.

## Arithmetic operations (754-2019 clause 5.4.1)

These are the *required* homogeneous general-computational operations.
**All six exist.**

| operation | status | notes |
|---|---|---|
| `fusedMultiplyAdd` | **yes** | the core; one rounding, exact product internally |
| `addition` | **yes** | steered through the FMA (b := 1.0) |
| `subtraction` | **yes** | steered (b := 1.0, c sign-flipped) |
| `multiplication` | **yes** | steered (c := signed zero) |
| `division` | **composed** | `cft_div`: recip seed (opcode 26, in hardware, rel. error < 2^-8.5 proven exhaustively) + Newton + a truncating Markstein finish driven to floor by exact residual signs + a MEASURED guard + one rounding. Correctly rounded in all five attributes, full flags |
| `squareRoot` | **composed** | `cft_sqrt`: same shape from the rsqrt seed (opcode 27) and the exact midpoint discriminant |

The evidence behind **composed**, because the mark is new: bit-identical
to the contract `div`/`sqrt` over the model matrix (29,124 cases, every
format and attribute, per-element flags); **23.875 billion cases
against the host CPU's own IEEE hardware** at fp32/fp64 - exhaustive
fp32 square root under every attribute - zero disagreements, flags
included; and **999,000 cases against GNU MPFR** across all four
formats, the only external oracle that reaches binary128/256. All in
docs/VALIDATION.md.

## Rounding (clause 4.3)

All five attributes, selected per operation, carried with the
operation down the pipeline so adjacent operations may differ.

| attribute | status |
|---|---|
| roundTiesToEven | **yes** |
| roundTowardZero | **yes** |
| roundTowardPositive | **yes** |
| roundTowardNegative | **yes** |
| roundTiesToAway | **yes** |

The mode-dependent consequences are implemented too, not just the
increment rule: the clause 7.4 overflow table (roundTowardZero never
yields an infinity; the directed attributes only on their own side)
and the clause 6.3 signed zero of an exact cancellation.

## Exceptions and flags (clause 7)

| item | status | notes |
|---|---|---|
| inexact | **yes** | sticky, OR-accumulated over the run |
| underflow | **yes** | tininess after rounding, raised only when tiny **and** inexact |
| overflow | **yes** | with the per-attribute delivered result |
| invalid | **yes** | sNaN operand, `inf * 0`, `inf - inf`, `0/0`, `inf/inf`, sqrt of a negative |
| divideByZero | **yes** | raised by `cft_div` for finite/0, exactly per 7.3 |
| trap handling | **out** | flags are sticky data, never control flow. Deterministic by construction |
| per-element flags | **no** | the FLAGS register is the OR over the run, not per lane |

## Non-arithmetic operations

These do not round, ignore the rounding attribute, and reach the
output through the pipeline's precomputed-result path rather than the
datapath - so they cost a comparator and a sign bit, not a stage.

| operation | status | notes |
|---|---|---|
| `abs`, `negate`, `copySign` | **yes** | quiet: signal nothing, preserve NaN payloads |
| `select` | **yes** | `c` non-zero ? `a` : `b`; moves NaNs intact, signals nothing |
| `cmplt`, `cmple`, `cmpeq` | **yes** | quiet predicates yielding 1.0 or +0.0 |
| `minimum`, `maximum` | **yes** | NaN propagates; `min(+0,-0)` is -0 |
| `minimumNumber`, `maximumNumber` | **yes** | returns the number when one operand is NaN |
| `recip_seed`, `rsqrt_seed` | **yes** | the divide/sqrt starting points, exposed as opcodes 26/27 (quiet, no flags, subnormal inputs flush to their zero-class result by spec) - a caller building its own iteration gets the same seed the library uses |

## Everything else in clause 5 - now covered

This table used to be titled "the remaining gap", and its length was
the distance to full 754 coverage. On 2026-09-01 the distance closed:
every remaining operation landed as a contract function - composed
from existing opcodes where floating-point work exists, host bit
surgery where none does - with **zero new RTL**, which was the point
of the composition methodology. `python/cft_golden/softfloat.py`
defines each one; `host/tests/clause5_check.py` holds libcft identical
to it (112,372 comparisons, every format and attribute).

| group | operations | status |
|---|---|---|
| sign operations (5.5.1) | `abs`, `negate`, `copySign` | **yes** |
| sign operations (5.5.1) | `copy` | **no** - a memcpy; nothing needs the tile for it |
| min/max (9.6) | `minimum`, `maximum`, `minimumNumber`, `maximumNumber` | **yes** - 754-2019 moved these out of 5.3.1 and changed the sNaN rule; this follows the 2019 semantics |
| comparisons (5.6.1, 5.11) | `compareQuietLess`, `LessEqual`, `Equal` - as floats a select can consume; **greater/greaterEqual come free by swapping the operand pointers** | **yes** |
| comparisons (5.6.1) | `compareSignaling{Less,LessEqual,Equal}` (`cft_cmp_sig`) | **composed** - the quiet predicate's value from the tile, invalid-for-any-NaN synthesised exactly on the host |
| reductions | `sum`, `dot` with the index-fixed tree | **yes** - contract 0x500; the tree shape is part of the contract, four tiles return what one returns, and `dot(a,b) == sum(mul(a,b))` exactly, flags included |
| round to integral (5.3.1) | `roundToIntegral{TiesToEven..TiesToAway}` + `Exact` (`cft_rint`) | **composed** - the magic-constant addition under the caller's attribute, made total by host bookkeeping; the named variants signal nothing, per the standard |
| scaling (5.3.3) | `scaleB` (`cft_scaleb`) | **composed** - multiplies by exact powers of two; one rounding, the mul's flags ARE the contract flags |
| conversions (5.4.1) | int32/uint32/int64/uint64 -> float, float -> int, all five roundings + Exact variants (`cft_cvt_*`) | **library** - with the invalid-case delivery 754 leaves open pinned to RISC-V's FCVT table |
| format conversion (5.4.2) | fp32 <-> fp64 <-> fp128 <-> fp256, any pair (`cft_convert`) | **library** - widening exact and silent, narrowing one `round_pack` |
| remainder (5.3.1) | `remainder` (`cft_rem`) | **library** - exact always, by one bounded integer walk; the model's unbounded divmod and the C walk agree over every matrix including the fp256 full-gap case |
| scaling (5.3.3) | `logB` (`cft_logb`) | **library** - value-based on subnormals; logB(0) is -inf + divideByZero |
| next (5.3.1) | `nextUp`, `nextDown` (`cft_next_up/_down`) | **library** - one step on the encoding, the standard's -0 edge included |
| classification (5.7.2) | `class` + every is* predicate as a subset test (`cft_class`) | **library** - ten values pinned to RISC-V fclass bit indices |
| total order (5.10) | `totalOrder`, `totalOrderMag` (`cft_total_order*`) | **library** - the order-embedding key; defined on the whole encoding space, signals nothing |
| NaN payloads (6.2.3) | payload propagation | **out** |

What **library** rows would take to become **yes** is the same short
list it always was - a handful of comb opcodes in `cft_simpleops`
(which now carries an exhaustive-equivalence proof methodology to
absorb them safely) and, for beat-rate conversions, the one
structurally new datapath in the whole set: cross-width lane steering.
Neither buys correctness; both are throughput decisions for after the
sequencer.

The NaN row is a deliberate deviation from a *recommendation*: any NaN
in produces one canonical quiet NaN out, because payload propagation
order is exactly where implementations diverge. Documented in
docs/DETERMINISM.md.

## Recommended operations (clause 9.2)

`exp`, `expm1`, `exp2`, `exp10`, `log`, `log2`, `log10`, `log1p`,
`hypot`, `pow`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`,
`sinh`, `cosh`, `tanh`, `asinh`, `acosh`, `atanh`, `rSqrt`,
`compound`, `rootn`, `pown`, `powr` - **all no**, and mostly by
choice rather than by omission. The atlas det library computes these
*in software from fused multiply-add*, exactly so their results do not
depend on anyone's hardware transcendental. The tile's job is to make
that software exact and fast, not to grow its own `sin`. The composed
divide and square root are the template for how such a function ships
here when one is genuinely wanted: hardware seed, FMA composition,
proof against oracles - never a black-box unit.

## The atlas-engine det_* library

`atlas-engine`'s deterministic library is the workload this tile
exists to serve, and the most useful measure of readiness. It is 38
functions built almost entirely from `fma` (51 uses against a handful
of everything else), deliberately, so a GLSL driver's quirks cannot
reach the results.

The distance to running it on-chip:

| what det_* needs | status |
|---|---|
| correctly-rounded `fma` | **yes** |
| bit reinterpretation (float <-> uint) | free - the same register, no operation needed |
| integer add / subtract / shift on the bit pattern | **yes** |
| compare and branchless select | **yes** |
| `abs`, `min`, `max` | **yes** |
| `clamp` | **yes** as `min`+`max`; one pass each until there is a sequencer |
| division / sqrt / rsqrt seeds to refine | **yes** - opcodes 26/27, plus the fully-composed `cft_div`/`cft_sqrt` when the correctly-rounded answer is wanted outright |
| `floor`, `round`, `step` | **composed** (2026-09-01) - `cft_rint` under the directed attributes IS floor/ceil/trunc/round; `step` was always cmple+select |
| a sequencer to run a chain on-chip | **not in hardware.** The ISA is specified (docs/SEQUENCER.md), the golden model executes it, and libcft runs programs today on the software backend - so a program can be written and checked now. The RTL is v2 |

Today a det_* function could be evaluated as a hybrid - the tile doing
the fma passes, the host doing the integer and select work between
them - and the result would be bit-exact. `cft_div` and `cft_sqrt` ARE
that hybrid, shipped and proven: ~25-30 passes per call, which is the
honest price of correct rounding composed from FMA, and the measured
reason the sequencer is v2's headline (the same sequence as one
on-chip program is the ~25x traffic win).

## Engine and host

| capability | status | notes |
|---|---|---|
| elementwise over three input arrays | **yes** | D = op(A, B, C) |
| burst AXI, overlapped read/compute/write | **yes** | one AXI master per stream, one HBM pseudo-channel per master |
| precision and rounding selected per run | **yes** | snapshot at start; a mid-run change cannot corrupt a run |
| capability discovery (CAPS) | **yes** | formats and opcode groups this bitstream carries |
| unsupported precision | **refused** | STATUS[3]: engine never starts, memory untouched, done still asserts - an error, not an output |
| bus-fault reporting (STATUS) | **yes** | including the abandon-on-length-violation path, so a protocol fault is a prompt error rather than a hang |
| multiple compute units | **yes** | libcft partitions elementwise runs and reductions across up to 64 CUs; four tiles return what one returns, flags included. The quad image is built and verified |
| reductions on-chip | **yes** | streaming accumulator with the contract's tree |
| strided or gathered access | **no** | three dense linear streams |
| on-chip program / loop | **no** | one operation per pass over memory; the sequencer is v2 |
| in-place operation (D aliasing A/B/C) | **yes** | documented in cft.h: each element is read before written |

### Host access

libcft's XRT backend reads FLAGS, STATUS and CAPS and refuses to open
a device where it cannot. The old pyxrt limitation stands for pyxrt
itself (no `read_register` as of XRT 2.19), so
`host/examples/vector_fma.py` warns rather than pretending the check
ran - but every caller going through libcft (which is every language
in docs/COMPATIBILITY.md) gets the full story.

## What "general purpose" would take from here

1. **Programmability.** The one remaining structural gap. Every
   operation today is one pass over memory; a det_* function is ten to
   thirty dependent steps, and the composed div/sqrt measure the cost
   precisely (~25-30 passes per call). The v2 orbit sequencer is what
   turns this from a vector ALU into a processor. The design is
   settled and executable - docs/SEQUENCER.md, seq.py, and libcft's
   software-backend program runner agree over a fuzz corpus - so a
   program can be written and checked today; the tile just cannot run
   one yet.

2. ~~The cheap operations, which are cheap.~~ **Done** (2026-09-01):
   `roundToIntegral`, the conversions, classification, and the rest of
   clause 5 landed as compositions and library operations - zero new
   RTL, which was always the claim about why they were cheap.

3. ~~Division and square root.~~ **Done** (2026-08-31): seed opcodes
   in hardware, composition in libcft, correctly rounded per 5.4.1
   with full flags, three independent oracles. The gap this file was
   originally written around no longer exists.

## Summary

- As an **FMA engine**: complete. Four interchange formats, all five
  rounding attributes, correct flags and edge cases, verified against
  the definition rather than against another implementation.
- As an **IEEE 754 implementation**: **clause 5 is covered on the
  binary side** - the six required arithmetic operations, reductions
  with a contractual tree, and as of 2026-09-01 the entire completion
  set: roundToIntegral, every conversion, scaleB/logB, nextUp/
  nextDown, classification, totalOrder, the signaling comparisons,
  remainder. What remains outside: the character-sequence conversions
  of 5.4.2/5.12 (inherently host-library work, hex trivial, decimal
  needing big-integer scaling - planned, not blocking any numeric
  path), NaN payload propagation (**out**, deliberately), and clause
  9's recommended transcendentals (**out** by design - the det-library
  route computes them from FMA).
- As a **general-purpose float processor**: the blocker is
  programmability alone - the sequencer, not arithmetic. That
  sentence was true yesterday about the operation set with six ops;
  it is simply more visibly true now.
- For the **atlas det library**: every primitive it refines from
  exists on the tile, including its seeds and now floor/round; what is
  missing is the on-chip sequence to chain them without a memory round
  trip per step.
