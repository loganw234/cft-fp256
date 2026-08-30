# Capabilities

An honest inventory of what this tile can and cannot do, measured
against IEEE 754-2019 and against the workload it was built to serve.

**The empty boxes are the point.** This file exists so that "is it
general purpose yet?" has an answer you can check rather than a
feeling, and so the gap between *a very good fused-multiply-add engine*
and *a general floating-point processor* is written down instead of
implied. Today the tile is emphatically the former.

| mark | meaning |
|---|---|
| **yes** | in the RTL and verified bit-exact against the golden model, in simulation and through the real XRT stack |
| **model** | defined in `python/cft_golden` and covered by conformance vectors, but no hardware - a host can use it, the tile cannot |
| **no** | not implemented anywhere |
| **out** | deliberately excluded; the reason is given |

Anything marked **yes** is bit-identical across every device that
implements this contract - that is the whole product. Anything marked
**no** is not slow here, it is *absent*: the host must do it.

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

A build may drop the fp64/fp128/fp256 banks (`EN_FP64` and friends);
what remains is advertised in the CAPS register and behaves
identically on the rungs it keeps.

## Arithmetic operations (754-2019 clause 5.4.1)

These are the *required* homogeneous general-computational operations.
Four of six exist.

| operation | status | notes |
|---|---|---|
| `fusedMultiplyAdd` | **yes** | the core; one rounding, exact product internally |
| `addition` | **yes** | steered through the FMA (b := 1.0) |
| `subtraction` | **yes** | steered (b := 1.0, c sign-flipped) |
| `multiplication` | **yes** | steered (c := signed zero) |
| `division` | **no** | see "What general purpose would take" |
| `squareRoot` | **no** | same |

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
| invalid | **yes** | sNaN operand, `inf * 0`, `inf - inf` |
| divideByZero | **no** | bit reserved; there is no division to raise it |
| trap handling | **out** | flags are sticky data, never control flow. Deterministic by construction |
| per-element flags | **no** | the FLAGS register is the OR over the run, not per lane |

Reading the flags from the host is currently blocked by a tooling gap,
not a hardware one - see "Host access" below.

## Non-arithmetic operations

These do not round, ignore the rounding attribute, and reach the
output through the pipeline's precomputed-result path rather than the
datapath - so they cost a comparator and a sign bit, not a stage.

| operation | status | notes |
|---|---|---|
| `abs`, `negate`, `copySign` | **yes** | quiet: signal nothing, preserve NaN payloads |
| `minimum`, `maximum` | **yes** | NaN propagates; `min(+0,-0)` is -0 |
| `minimumNumber`, `maximumNumber` | **yes** | returns the number when one operand is NaN |

## Everything else in clause 5 - the gap

Most of this does not exist. It is listed in full because the length
of the list *is* the distance to general purpose.

| group | operations | status |
|---|---|---|
| sign operations (5.5.1) | `abs`, `negate`, `copySign` | **yes** |
| sign operations (5.5.1) | `copy` | **no** - a memcpy; nothing needs the tile for it |
| min/max (5.3.1, 9.6) | `minimum`, `maximum`, `minimumNumber`, `maximumNumber` | **yes** |
| comparisons (5.6.1, 5.11) | `compareQuiet*`, `compareSignaling*`, all 22 predicates | **no** |
| conversions (5.4.2) | int -> float, float -> int (all five roundings) | **no** |
| format conversion (5.4.2) | fp32 <-> fp64 <-> fp128 <-> fp256 | **no** |
| round to integral (5.3.1) | `roundToIntegral{TiesToEven,TowardZero,...,Exact}` | **no** |
| remainder (5.3.1) | `remainder` | **no** |
| scaling (5.3.3) | `scaleB`, `logB` | **no** |
| next (5.3.1) | `nextUp`, `nextDown` | **no** |
| classification (5.7.2) | `class`, `isNaN`, `isInfinite`, `isNormal`, `isSubnormal`, `isZero`, `isSignMinus`, `isCanonical` | **no** |
| total order (5.10) | `totalOrder`, `totalOrderMag` | **no** |
| NaN payloads (6.2.3) | payload propagation | **out** | 
| reductions | `dot`, `sum` with index-fixed tree order | **no** - roadmap, and the headline feature when it lands: deterministic reduction is what no GPU can promise |

The NaN row is a deliberate deviation from a *recommendation*: any NaN
in produces one canonical quiet NaN out, because payload propagation
order is exactly where implementations diverge. Documented in
docs/DETERMINISM.md.

## Recommended operations (clause 9.2)

`exp`, `expm1`, `exp2`, `exp10`, `log`, `log2`, `log10`, `log1p`,
`hypot`, `pow`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`,
`sinh`, `cosh`, `tanh`, `asinh`, `acosh`, `atanh`, `rSqrt`,
`compound`, `rootn`, `pown`, `powr` - **all no**, and mostly by
choice rather than by omission. See the next section: the atlas det
library computes these *in software from fused multiply-add*, exactly
so their results do not depend on anyone's hardware transcendental.
The tile's job is to make that software exact and fast, not to grow
its own `sin`.

## The atlas-engine det_* library

`atlas-engine`'s deterministic library is the workload this tile
exists to serve, and the most useful measure of readiness. It is 38
functions, and **none of them run on the tile today** - but the reason
is not the one the empty column suggests.

The library is *self-contained software*. `det_sqrt` is a bit-pattern
seed refined by Newton iterations on `fma`; `det_div` is a reciprocal
refined the same way; `det_sincos`, `det_exp2` and `det_log2` are
range reduction plus polynomials. Across the library the primitive
mix is 51 uses of `fma` against a handful of everything else. It is
built that way deliberately - a GLSL driver may flush denormals or
differ on `sin`, so the library trusts almost nothing but fma.

That means the distance to running it on-chip is short and specific:

| what det_* needs | status |
|---|---|
| correctly-rounded `fma` | **yes** |
| bit reinterpretation (float <-> uint) | free - the same register, no operation needed |
| integer add / subtract / shift on the bit pattern | **no** - needed for seeds like `0x5F375A86 - (m >> 1)` |
| compare and branchless select | **no** - every special-case guard in the library is one |
| `abs`, `min`, `max` | **yes** |
| `clamp` | **yes** as `min`+`max`; one pass each until there is a sequencer |
| `floor`, `round`, `step` | **no** - `roundToIntegral` is the next cheap win |
| a sequencer to run a chain on-chip | **no** - the v2 orbit engine |

Six rows, three still missing after the 2026-08-29 work. Grouped by
what they would unlock:

| family | functions |
|---|---|
| algebraic | `det_div`, `det_div2`, `det_recip`, `det_sqrt`, `det_isqrt`, `det_scale48` |
| transcendental | `det_exp2`, `det_log2`, `det_pow`, `det_sin`, `det_cos`, `det_sincos`, `det_tan`, `det_asin`, `det_acos`, `det_atan`, `det_sinh`, `det_cosh`, `det_tanh` |
| rounding / piecewise | `det_fract`, `det_mod`, `det_mix`, `det_mix3`, `det_smoothstep` |
| vector | `det_dot3`, `det_cross`, `det_len`, `det_len2`, `det_len3`, `det_len3v`, `det_normalize3`, `det_rodrigues` |
| complex | `det_cmul`, `det_cdiv`, `det_cinv`, `det_csqrt` |
| atlas-specific | `det_pal`, `det_pal1` |

Today a det_* function could in principle be evaluated as a hybrid -
the tile doing the fma passes, the host doing the integer and select
work between them - and the result would be bit-exact. It would also
be absurdly slow, one memory round trip per arithmetic step. That is
not a product, it is an existence proof.

## Engine and host

| capability | status | notes |
|---|---|---|
| elementwise over three input arrays | **yes** | D = op(A, B, C) |
| burst AXI, overlapped read/compute/write | **yes** | ~4.4 cycles/beat, port-bound |
| precision and rounding selected per run | **yes** | snapshot at start; a mid-run change cannot corrupt a run |
| capability discovery (CAPS) | **yes** | which rungs this bitstream carries |
| bus-fault reporting (STATUS) | **yes** in RTL | see Host access |
| multiple compute units | **no** | one CU per bitstream today |
| strided or gathered access | **no** | three dense linear streams |
| on-chip program / loop | **no** | one operation per pass over memory |
| in-place operation (D aliasing A/B/C) | works, undocumented | the write pointer trails the read pointers by construction |

### Host access

The Python host cannot read the status registers. Checked against XRT
2.14.354 and 2.19.194: `pyxrt.kernel` exposes `group_id` and the CU
access modes and nothing else - no `read_register`, and no `pyxrt.ip`.
So FLAGS, STATUS and CAPS are reachable from the C++ API and from the
cocotb bench, but not from `host/examples/vector_fma.py`, which warns
rather than pretending the check ran.

This costs diagnosis rather than correctness: the result-buffer
comparison against the golden model is the real gate, and a bus fault
corrupts the results, so a fault still fails the run - just as "wrong
answer" instead of "the memory never delivered". The fix is to give
the kernel a small status output buffer so the sticky words come back
through the AXI master like every other result.

## What "general purpose" would take

Three things, in the order they matter:

1. **Programmability.** The single largest gap is not an arithmetic
   operation, it is that the tile has no way to express *a sequence*.
   Every operation today is one pass over memory. A det_* function is
   ten to thirty dependent steps; at one memory round trip each, the
   arithmetic is free and the traffic is everything. The v2
   orbit/micro-sequencer engine is what turns this from a vector ALU
   into a processor, and it is worth more than every missing operation
   below combined.

2. **The cheap operations, which are cheap.** `abs`, `negate`,
   `copySign` and the four min/max forms landed on 2026-08-29 and cost
   a comparator each - they ride the pipeline's existing
   precomputed-result path, so they added no stage and no latency.
   What remains in the same class: comparison predicates, select,
   `roundToIntegral`, classification, and integer/bit operations on
   the pattern. All shallow logic on data the datapath already
   unpacks, absent because nothing needed them yet rather than because
   they are hard. Together with (1) they are what the det library
   actually requires.

3. **Division and square root.** The genuinely expensive additions,
   and the least urgent: the det library already implements both from
   fma to better precision than a hardware unit would give it, and
   with a rounding it controls. Worth building when someone needs a
   correctly-rounded `divide` per the standard, not before.

Format conversions and the remaining clause 5 operations follow from
(2). Transcendentals in hardware are not on the path at all - the
software-from-fma approach is the more defensible answer for a project
whose claim is reproducibility.

## Summary

- As an **FMA engine**: complete. Four interchange formats, all five
  rounding attributes, correct flags and edge cases, verified against
  the definition rather than against another implementation.
- As an **IEEE 754 implementation**: four of six required arithmetic
  operations, and none of the comparison, conversion, classification
  or auxiliary operations.
- As a **general-purpose float processor**: not yet, and the blocker
  is programmability rather than arithmetic.
- For the **atlas det library**: the hard part is done and the easy
  parts are missing.
