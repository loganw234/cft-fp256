# The determinism contract

What this hardware promises about every bit it produces, stated so it
can be checked by someone who trusts none of this code. Clause
references are to IEEE Std 754-2019, quote-verified 2026-08-28 against
the licensed PDF, with the standard's own words where the choice is
load-bearing.

## The promise

**Same inputs, same op, same bits - on this tile, on the golden model,
and on any other implementation of this contract.** No configuration,
compiler, driver, tool version, placement seed, or timing behaviour may
change a result bit or a flag bit. A divergence is a bug in the
diverging implementation, by definition, and the conformance vectors
(vectors/) are how the claim is scored.

This is the same bar the atlas-engine det library holds on GPUs - one
hash across vendors - reached from the other side. GLSL earns it by
pinning a hostile toolchain operation by operation; RTL earns it by
construction, because there is no driver between the source and the
gates. The two meet at the primitive set: pinned add/sub/mul/fma with
RNE, denormals, and exact selections. An algorithm written against
those primitives (every `det_*` function is fma/Newton/polynomial
chains over them) lands on identical bits wherever the primitives do.

## Formats

The IEEE 754-2019 binary interchange ladder, exactly:

| format | w (exp) | t (frac) | p | emax | bias |
|---|---|---|---|---|---|
| fp32  | 8  | 23  | 24  | 127    | 127    |
| fp64  | 11 | 52  | 53  | 1023   | 1023   |
| fp128 | 15 | 112 | 113 | 16383  | 16383  |
| fp256 | 19 | 236 | 237 | 262143 | 262143 |

fp256 parameters follow Table 3.5's binary{k} formulas; the standard
names the example itself: "binary256 would have p = 237 and
emax = 262143" (3.6, Table 3.5). No bfloat, no TF32, no vendor
variants: identity needs one definition per width.

Hardware and golden model both implement all four rungs; a trimmed
tile advertises what it carries in the CAPS CSR
(docs/ARCHITECTURE.md) and is bit-identical on those rungs.

## Operations

The arithmetic core: `fma(a,b,c) = a*b + c`, `add`, `sub`, `mul` -
elementwise over vectors. Division and square root are contract
operations composed from the tile's seed opcodes and FMA; the rest of
clause 5 - roundToIntegral, the conversions, scaleB/logB, nextUp/
nextDown, classification, totalOrder, the signaling comparisons,
remainder - are contract operations too, specified in their own
section below, and so are the nine phase-1 transcendentals of clause 9
(exp, expm1, exp2, log, log1p, log2, log10, pow, hypot), the eleven
phase-2 trigonometrics (sinPi, cosPi, tanPi, asin, acos, atan, atan2,
asinPi, acosPi, atanPi, atan2Pi) and the nine of phase 3 (sin, cos
and tan of a radian argument; sinh, cosh, tanh, asinh, acosh, atanh),
correctly rounded. The three augmented arithmetic operations of clause
9.5 - augmentedAddition, augmentedSubtraction and
augmentedMultiplication, each returning a PAIR under a rounding the
five attributes do not include - are contract operations too, in their
own section below. Clause 5's last requirement, 5.12's conversions
between the formats and external character sequences - decimal and
hexadecimal, both directions - joined them on 2026-09-03 along with
clause 9.7's three NaN payload operations, and have their own section
too. Everything is scored the same way regardless of route:
`python/cft_golden/softfloat.py` defines the bits, with `transcend.py`
and `augmented.py` beside it for the clause-9 sets and `chars.py` for
the character conversions.

ADD/SUB/MUL are defined as operand-steered FMA (see
`cft_golden.softfloat.steer` and rtl/cft_opmux.sv); the steering is
proven equivalent to the direct IEEE definitions by
`test_steering_composition`, signed zeros and specials included.

fusedMultiplyAdd computes "(x × y) + z as if with unbounded range and
precision, rounding only once to the destination format" (5.4.1). The
product is exact inside the datapath; it cannot overflow, underflow,
or round before the addend joins. `test_fp32_fused_single_rounding_witness`
holds the canonical witness: fp32 `fma(1+2^-23, 1-2^-23, -1) = -2^-46`
exactly, where any double-rounded implementation returns +0.

## Rounding

All five 754-2019 rounding-direction attributes (4.3.1, 4.3.2),
selected per operation in MODE[14:12] using RISC-V's `frm` encoding:

| code | attribute | name here |
|---|---|---|
| 0 | roundTiesToEven | `rne` - the default, and what "the contract" means unless a run says otherwise |
| 1 | roundTowardZero | `rtz` |
| 2 | roundTowardNegative | `rdn` |
| 3 | roundTowardPositive | `rup` |
| 4 | roundTiesToAway | `rmm` |

Encodings 5-7 are reserved: the hardware treats them as `rne`, and the
golden model rejects them outright, so no conforming host can depend
on a value the contract does not define.

**Five, and exactly five.** 754-2019 9.5 defines a SIXTH rounding
direction, roundTiesTowardZero, for the augmented arithmetic
operations and for nothing else. It is not in this table because it is
not an attribute: no operation here accepts it, no MODE encoding
carries it, and the gate that admits these five rejects it. It lives
inside `round_pack` numbered outside the three-bit attribute field, and
the augmented operations - which take no attribute argument at all -
are its only callers. See the clause-9.5 section below.

**Each attribute is its own deterministic contract** - the same inputs
under the same attribute always give the same bits, on every device
that implements this specification. Determinism was never a property
of round-to-nearest specifically; it is a property of the rounding
being *specified*.

Two consequences that catch implementations out, both of them
mode-dependent and both pinned by named tests:

- **Overflow (7.4)** is signalled in every attribute, but what gets
  delivered differs: `rne`/`rmm` give an infinity; `rtz` never does
  (it gives the largest finite magnitude); `rdn` gives -infinity only
  on the negative side and `rup` +infinity only on the positive one.
- **The sign of an exact zero (6.3)** is +0 in every attribute except
  `rdn`, where it is -0.

The attribute travels with its operation down the pipeline rather than
being latched per run, so adjacent operations may use different ones.
That is what interval arithmetic wants: a lower and an upper bound
from a single pass. `test_directed_modes_bracket_the_exact_value`
proves the pair brackets the exact result and, when inexact, that the
two bounds are adjacent - the tightest interval the format admits.

Every rounding in the implementation still happens at exactly one site
in each of the golden model (`round_pack`) and the RTL (stage 13 of
`cft_fpfma_pipe`), which is what makes the claim auditable. The
attributes are verified against the *definition* rather than against
another implementation: `python/tests/test_rounding.py` decodes each
result into an exact rational and re-derives what 754 requires by
exact rational floor division, sharing no code path with the model.

## The non-arithmetic operations

Nineteen opcodes that do not round, do not consult the rounding
attribute, and cannot be inexact:

| group | operations | clause |
|---|---|---|
| sign | `abs`, `negate`, `copySign` | 5.5.1 |
| min/max | `minimum`, `maximum`, `minimumNumber`, `maximumNumber` | 9.6 |
| predicate | `cmplt`, `cmple`, `cmpeq` (quiet comparisons) | 5.11 |
| data | `select` | - |
| integer | `iand`, `ior`, `ixor`, `iadd`, `isub`, `ishl`, `ishr`, `icmplt` | - |

Rules worth stating because they are the ones implementations get
wrong:

- **`min(+0, -0)` is -0 and `max(+0, -0)` is +0.** Not a choice: 9.6
  says "for this operation, -0 compares less than +0", which takes ±0
  out of the "either operand" case. A min/max that returns "either,
  they're equal" is non-conforming and free to differ per device.
- **The `...Number` forms return the NUMBER when one operand is a
  signaling NaN**, raising invalid but not converting it - 9.6 says
  the sNaN "is otherwise ignored and not converted to a quiet NaN".
  This changed from 754-2008's minNum/maxNum; implementing the old
  behaviour is the common mistake.
- **The plain `minimum`/`maximum` forms return the canonical quiet
  NaN**, per the canonicalisation rule below - they do not forward the
  operand's payload.
- **`cmplt`/`cmple`/`cmpeq` are the QUIET predicates** (5.11): they
  signal only on a signaling NaN, and an unordered pair makes every
  predicate false. They yield 1.0 or +0.0 rather than a condition
  code; 5.6.1 calls the result boolean and nowhere fixes its
  representation, so this conforms and lets `select` consume it.

### Where the canonical-NaN rule does not apply

The rule below - any NaN in, one canonical quiet NaN out, sNaN raises
invalid - governs **arithmetic**. Four groups are outside it, and
saying so precisely matters because this document is what an
independent implementation is scored against:

| group | NaN behaviour |
|---|---|
| `abs`, `negate`, `copySign` | pass the pattern through, payload intact, signal **nothing** even for a signaling NaN (5.5.1: "they only affect the sign bit... and signal no exception"; 6.2.3 exempts exactly these) |
| `select` | moves whichever operand it selects through intact, payload and all, and signals nothing |
| the clause-5.12 conversions and the clause-9.7 payload operations | carry the payload, the quiet bit and the sign through in both directions, and signal nothing - 6.2 exempts 5.12's conversions from the sNaN rule outright, and 9.7 says its three "signal no exceptions". See their section below |
| the integer group | there are no NaNs - the operand is a W-bit unsigned word, and no bit pattern means anything but itself |

None of this weakens determinism. The canonical rule exists because in
arithmetic *which operand's payload survives* is where implementations
diverge; in every case above the result is a function of the input
bits with no choice to make. 754-2019 7.1 leaves the signalling
behaviour of operations outside the standard to the implementation,
and this table is that definition.

### Unassigned opcodes

Opcode 15 and everything from **30** up are unassigned. They return the
canonical quiet NaN with **invalid** raised, in the hardware and in
the golden model alike. Deterministic, and visible in the flags, so a
host that issues one early learns it now rather than getting a
plausible number that changes meaning under a later bitstream.

The hazard is not hypothetical; it has now fired three times. 24 and 25
became `sum` and `dot` (2026-08-30), 26 and 27 became the
divide/sqrt seeds (2026-08-31), and 28 and 29 became `sumsq` and
`sumabs` (2026-09-03) - each time, a vector set generated
before the assignment still named the opcode "reservedNN", and
replaying one would score the new operation against an answer recorded
for the unassigned-opcode result. `cft_conformance` detects that
specifically and says so, rather than reporting a mismatch; on the
third occasion that refusal is what caught it, in the generator's own
"unassigned representative" list. Note that
the rest of clause 5 landed WITHOUT consuming opcode space: the new
operations are library entry points over existing opcodes plus exact
host bookkeeping, so no further reassignment hazard was created - and
so did the three scaled products of clause 9.4, which return a pair and
could not be `cft_reduce` opcodes even if one were free.

## Division, square root, and the clause-5 completion set

These are contract operations with library entry points (`cft_div`,
`cft_rint`, `cft_convert`, ...) rather than engine opcodes. The route
differs - composed sequences of contract opcodes for div/sqrt/rint/
scaleB/the signaling compares, pure host bit surgery for operations
containing no floating-point arithmetic at all - but the scoring does
not: the golden model defines every bit and flag, and the same call
returns the same bits on every backend. The load-bearing choices:

- **`division` and `squareRoot` (5.4.1) are correctly rounded** in all
  five attributes with full flags - divideByZero for finite/0 per 7.3,
  invalid for 0/0, inf/inf and the negative root. The composition
  (seed, Newton, an exactly-measured residual, one rounding) is
  specified in `python/cft_golden/sequences.py` and held bit-identical
  to the contract functions by its own matrix; three independent
  oracles score the result (docs/VALIDATION.md).
- **`roundToIntegral{TiesToEven..TiesToAway}` (5.3.1, 5.9) signal
  NOTHING except invalid on sNaN** - never inexact, per the standard.
  `roundToIntegralExact` alone signals inexact, when the value
  changed. The sign of a zero result is the sign of the operand:
  rint(-0.4) is -0 in every attribute.
- **`convertFormat` (5.4.2)** between any two rungs of the ladder:
  widening is exact and silent, narrowing is one rounding with the
  full overflow/underflow/inexact behaviour of any arithmetic result.
  NaNs canonicalise into the destination (the standing deviation).
- **`convertToInteger` (5.4.1): 754 leaves the delivered value of the
  invalid cases to the implementation, and determinism cannot**, so
  this contract pins them to RISC-V's FCVT table: NaN and +inf deliver
  the integer type's maximum, -inf and negative overflow its minimum,
  a negative that rounds below zero delivers unsigned 0 - all with
  invalid raised, and invalid pre-empts inexact (7.2). A negative that
  rounds TO zero is simply zero, no signal. The named directions never
  signal inexact; the `...Exact` family alone does. `convertFromInt`
  converts zero to +0 and can signal nothing but inexact.
- **`scaleB` and `logB` (5.3.3)**, logBFormat chosen as the operand's
  own floating-point format. scaleB is one rounding at the shifted
  exponent. logB is value-based (a subnormal reports its true
  exponent), always exact; logB(+-0) is -inf and **signals
  divideByZero** per the standard, logB(+-inf) is +inf silently.
- **`nextUp`/`nextDown` (5.3.1)**: one step on the encoding. The
  standard's own edges are contract: nextUp(+-0) is the smallest
  positive subnormal, nextUp of the negative subnormal of LEAST
  magnitude is **-0** (that is the standard's explicit zero choice),
  the largest finite steps to infinity with **no overflow signal** -
  invalid on sNaN is the only signal these can raise.
- **`class` (5.7.2)** delivers one of ten values fixed to RISC-V's
  fclass bit indices (0 = negativeInfinity ... 9 = quietNaN; the full
  table is `cft_class_value` in cft.h) - one table for anyone porting,
  the same reasoning that chose frm. Non-computational: signals
  nothing, even for sNaN. isCanonical is constantly true (binary
  interchange formats have no non-canonical encodings); radix is 2.
- **`totalOrder`/`totalOrderMag` (5.10)** are defined on the entire
  encoding space and signal nothing on anything. The definition used
  is the order-embedding: complement negative encodings, set the sign
  bit on positive ones, compare unsigned - which reproduces 5.10's
  ordering exactly, NaN sign/quiet-bit/payload ordering included.
- **The signaling comparisons (5.6.1)** have the same truth table as
  the quiet predicates - unordered is false - and raise invalid for
  ANY NaN operand, quiet included. Like the quiet set, only lt/le/eq
  exist; greater and greaterEqual are the operand swap.
- **`remainder` (5.3.1) is EXACT, always**: r = x - y*n with n the
  integer nearest x/y, ties to even; no rounding attribute is consumed
  because none is ever used, and inexact/overflow/underflow cannot
  occur. A zero result takes x's sign. remainder(inf, y) and
  remainder(x, 0) are invalid; remainder(x, inf) is x exactly.

## The phase-1 transcendentals (clause 9.2)

exp, expm1, exp2, log, log1p, log2, log10, pow and hypot are contract
operations with library entry points (`cft_exp`, `cft_pow`, ...), added
2026-09-02. They are the first operations in this contract that 754
calls RECOMMENDED rather than required, and the reason they are in a
determinism document at all is the load-bearing choice:

**They are correctly rounded, in all five attributes, at all four
formats, with exact flags.** 754-2019 9.2 asks only that these
functions be "correctly rounded" if an implementation claims to provide
them under clause 9's rules, and most libraries do not claim it. This
one does, and it is not a quality boast: a correctly rounded result is
defined by the mathematics, so two conforming implementations agree bit
for bit and a vector set can score them. An "accurate" transcendental
cannot be scored at all - two of them disagree in the last bit on a
percentage of inputs and neither is wrong - which would put a hole in
the promise at the top of this document the size of every application
that calls `exp`.

`python/cft_golden/transcend.py` defines every bit;
docs/TRANSCENDENTALS.md carries the algorithms, the error bounds, the
exactness proofs and the honest statement of the Table Maker's Dilemma.
What belongs HERE is what an independent implementation is scored on:

- **The exact cases raise nothing**, and they are decided by exact
  arithmetic rather than by a tolerance: exp and expm1 only at zero,
  log and log1p only at 1 and 0, exp2 exactly when the argument is an
  integer whose power is representable, log2 exactly at the powers of
  two, log10 exactly at the powers of ten the format represents, pow
  exactly when the true value is a representable dyadic rational, hypot
  exactly when x^2 + y^2 is a perfect square. `hypot(3, 4)` is 5 with
  no inexact flag. Everything else is inexact.
- **Overflow and underflow follow clause 7** through the same
  round_pack every arithmetic result uses, delivered value included -
  the largest finite magnitude rather than an infinity under
  roundTowardZero and on the wrong side of the two directed attributes.
- **The clause 9.2.1 special-value table applies in full.** The rows
  implementations most often differ on: `exp(-inf)` is +0 and silent;
  `expm1(-inf)` is -1 exactly; `expm1(+-0)` and `log1p(+-0)` keep the
  operand's SIGN; `log(+-0)` and `log1p(-1)` are -inf with
  divideByZero; a negative operand to log, or one below -1 to log1p, is
  invalid; `pow(x, +-0)` is 1 for any x including a quiet NaN or an
  infinity; `pow(+1, y)` is 1 for any y; `pow(-1, +-inf)` is 1; a
  negative finite base with a non-integer exponent is invalid;
  `hypot(+-inf, y)` is +inf for any y including a quiet NaN.
- **`pow(+-0, y)` signals divideByZero for a FINITE negative y only.**
  `pow(+-0, -inf)` is +inf and signals nothing: it is the |x| < 1 row,
  and the divideByZero is the pole at a finite exponent rather than the
  limit. That is the single row of that table most often got wrong.
- **A signaling NaN operand is outside those rows.** 9.2.1's wording is
  "even a QUIET NaN", so an sNaN raises invalid and delivers the
  canonical quiet NaN like every other operation here. This differs
  from C's `pow(sNaN, 0)`, which returns 1, and the difference is a
  stated choice rather than an accident.
- **An input that cannot be shown correctly rounded is REFUSED.** The
  library evaluates at a working precision and raises it until an
  enclosure of the true value rounds one way at both ends; if it
  reaches its cap it returns a status and writes nothing. It never
  returns a plausible number. No input the formats can express should
  reach that cap - docs/TRANSCENDENTALS.md does the arithmetic - and if
  one ever does, a status is how you find out.

Like the clause-5 host operations, these issue no device pass: they are
exact integer work over a multiprecision evaluator, so the device
argument is context and the results are bit-identical across backends
by construction. A tile-assisted fast path for the narrow formats would
have to reproduce these bits exactly.

## The phase-2 trigonometrics (clause 9.2)

sinPi, cosPi, tanPi, asin, acos, atan, atan2, asinPi, acosPi, atanPi
and atan2Pi are contract operations with library entry points, added
2026-09-03 as ABI 0.4, on exactly the terms the nine above are:
**correctly rounded, in all five attributes, at all four formats, with
exact flags.**

They are the half of clause 9's trigonometry whose argument reduction
is EXACT, and that is why they arrived a phase before the rest. sinPi
reduces by `x mod 2` and every operand is a dyadic rational, so the
reduction is a mask on the encoding at every magnitude; the inverse
functions have nothing to reduce and meet pi only as a factor of the
answer. `sin`, `cos` and `tan` of a radian argument - the reduction
against pi itself - arrived as phase 3, below.

What belongs here is what an independent implementation is scored on:

- **The exact cases raise nothing, and they are an enumeration with a
  theorem behind it.** Niven's theorem makes sinPi and cosPi exact
  exactly at the half-integers and tanPi exactly at the
  quarter-integers; Hermite-Lindemann makes asin, atan and atan2 exact
  only where the answer is a zero, and acos only at `acos(1)`. The
  Pi-forms of the inverses get a larger table for Niven's reason:
  `asinPi(+-1) = +-1/2`, `acosPi(+-0) = 1/2`, `acosPi(-1) = 1`,
  `atanPi(+-1) = +-1/4`, `atanPi(+-inf) = +-1/2`, and atan2Pi exact on
  every axis and every diagonal - 0, +-1/4, +-1/2, +-3/4, +-1.
  `asinPi(1/2)` is exactly 1/6: rational, NOT dyadic, therefore inexact
  and therefore decidable.
- **sinPi of an integer is a zero with the sign of the ARGUMENT**, not
  of `(-1)^n`. `cosPi(n + 1/2)` is `+0` for every n and both signs,
  because cosPi is even. **tanPi is sinPi/cosPi in every respect**, so
  `tanPi(1)` is `-0`.
- **tanPi at a half-integer is `+-infinity` with divideByZero.** A pole
  is an exact infinity from finite operands, which is 7.3's condition.
  The sign is sinPi's, since cosPi there is `+0`.
- **Overflow cannot occur anywhere in this set.** tanPi is the only
  candidate and cannot reach it: a representable argument is at least
  `2^-p` from a pole, so `|tanPi| < 2^p`, far inside emax at every
  rung. Underflow can occur and follows clause 7 through the same
  round_pack.
- **sinPi, cosPi and tanPi of an infinity are invalid** - no limit
  exists. asin, acos and their Pi forms are invalid for `|x| > 1`,
  infinities included.
- **`atan2(+-0, -0) = +-pi` and `atan2Pi(+-0, -0) = +-1`.** A minus
  zero denominator names the negative real axis. `atan2(+-0, +0)` is
  `+-0`; `atan2(y, +-0)` is `+-pi/2`; `atan2(+-inf, +inf)` is `+-pi/4`
  and `(+-inf, -inf)` is `+-3pi/4`.
- **A quiet NaN does not outrank atan2's table** the way it outranks
  pow's. atan2 of a NaN is a NaN. A signaling NaN raises invalid and
  delivers the canonical quiet NaN, as everywhere else.
- **An input that cannot be shown correctly rounded is REFUSED**, on
  the same terms as phase 1.

Like the nine, these issue no device pass: the device argument is
context and the results are bit-identical across backends by
construction.

## The phase-3 radian trigonometry and the hyperbolics (clause 9.2)

sin, cos, tan of a RADIAN argument, and sinh, cosh, tanh, asinh, acosh,
atanh are contract operations with library entry points, added
2026-09-03 as ABI 0.5, on exactly the terms the twenty above are:
**correctly rounded, in all five attributes, at all four formats, with
exact flags.**

The first three are the reduction against pi that the two phases
before them were defined to exclude. It is a Payne-Hanek reduction
against a stored 2/pi of 270,336 bits - generated, never transcribed,
derived twice - that measures the cancellation an argument causes and
widens its window by exactly the deficit; past what the constant
covers it refuses with a status. How close a representable argument
can come to a multiple of pi/2 is a MEASUREMENT (29 bits at fp32 and
61 at fp64 over every binade, 121 and 245 over sampled fp128 and fp256
binades, against an allowance of about 7,000), not a theorem: the
irrationality measure of pi is far too weak to bound it at this
exponent range, and docs/TRANSCENDENTALS.md says so plainly. The
reference does not share that reduction - mpmath reduces on its own
inside its interval sine - so agreement is evidence rather than a
shared derivation. The six hyperbolics are exp and log in different
clothes and need no reduction at all.

What belongs here is what an independent implementation is scored on:

- **The exact cases are the zeros, and that is a theorem.**
  Hermite-Lindemann makes sin, tan, sinh, tanh, asinh and atanh exact
  only at +-0, cos and cosh only at 0 (giving 1), acosh only at 1
  (giving +0). Every other result is inexact. `tanh(+-inf) = +-1` is a
  limit that happens to be representable and raises nothing.
- **sin, cos and tan of an infinity are invalid.** No limit exists.
- **tan never signals divideByZero** - an odd multiple of pi/2 is
  irrational, so no representable argument is a pole - but it CAN
  overflow near one. sinh and cosh overflow for a large argument;
  sin, cos, tanh, asinh, acosh and atanh cannot. Underflow occurs for
  the six odd functions of a tiny argument and follows clause 7
  through the same round_pack.
- **`atanh(+-1) = +-infinity` with divideByZero**, 7.3's exact
  infinity from a finite operand; `|x| > 1` is invalid, infinities
  included. **acosh below 1 is invalid**, zeros and -infinity
  included; `acosh(+inf) = +inf`.
- **A tiny argument is decided by a SIDE.** sin, tanh and asinh lie
  strictly on the zero side of a tiny x, tan, sinh and atanh strictly
  on the far side, cos strictly below 1 and cosh strictly above it -
  each with a threshold derived from the series, so a directed
  rounding delivers the neighbour and no working precision was ever
  needed to separate them.
- **An input that cannot be shown correctly rounded is REFUSED**, on
  the same terms as the other phases - here that includes an argument
  whose cancellation against pi exceeds the stored constant's coverage,
  which the measurement above puts more than an order of magnitude
  beyond anything the formats have produced.

Like the twenty, these issue no device pass: the device argument is
context and the results are bit-identical across backends by
construction.

## The augmented arithmetic operations (clause 9.5)

augmentedAddition, augmentedSubtraction and augmentedMultiplication
are contract operations with library entry points (`cft_augmented_add`
and friends), added 2026-09-03 as part of the 0.6 step. They are the
first operations in this contract that return **two results** - the
operation rounded, and the error rounding made - and the first that
take **no rounding attribute**, because 754-2019 9.5 fixes the
rounding itself:

> This standard specifies a single rounding direction to be used in the
> operations in this subclause, defined as roundTiesTowardZero: the
> floating-point number nearest to the infinitely precise result shall
> be delivered; if the two nearest floating-point numbers bracketing an
> unrepresentable infinitely precise result are equally near, the one
> with smaller magnitude shall be delivered.

**That is a sixth rounding direction, and it is deliberately NOT a
sixth attribute.** The five of the Rounding section above are what
MODE[14:12] encodes and what every other operation here consults; this
one exists inside `round_pack` (`RND_RTTZ` in the model,
`CFT_SF_RTTZ` in the library, both numbered 16 - outside the three-bit
attribute field on purpose) and is reachable only from these three
operations, which have no argument to carry it. The gate that admits
the five rejects it, and no attribute can produce this rounding.

**The five attributes' bits are unchanged, and the conformance replay
is not what proves it.** `make vectors` regenerates the sets from the
current model, so a change that moved the model and the library
together would replay clean; that argument would be circular. What
proves it is the layer that shares no code with either:
`python/tests/test_rounding.py` re-derives every attribute from exact
rationals, `test_augmented.py` holds addition under all five against
the same independent reference, and the MPFR campaign arbitrates the
library against an outside implementation. As a one-off at the time of
the change, the current model was also compared directly against the
model as it stood at the preceding commit over add/sub/mul/fma/div/sqrt
- 216,480 cases across five attributes and four formats, bit-identical
including flags (docs/VALIDATION.md, 2026-09-03).

The tie rule differs from roundTiesToEven **only at an exact midpoint
whose lower neighbour has an odd last bit**, so an implementation that
quietly used roundTiesToEven would pass anything that did not aim at
that case. The vector sets aim at it at every binade edge.

What an independent implementation is scored on:

- **Overflow still delivers an infinity, in both directions.** 9.5:
  "roundTiesTowardZero carries all overflows (see 7.4) to infinity with
  the sign of the intermediate result" - unlike roundTowardZero, which
  never does. The threshold is a midpoint: a magnitude EQUAL to
  `2^emax x (2 - 2^-p)` rounds to the largest finite "with no change in
  sign" and raises **nothing**, because 9.5 signals inexact "only when
  roundTiesTowardZero(x + y) overflows". Above it, both outputs are the
  infinity and overflow and inexact are raised.
- **Underflow is a statement about the ERROR TERM, not about r**: it is
  raised when e is "non-zero and lies strictly between +-b^emin". The
  error term is exact, so this is **underflow WITHOUT inexact** - the
  one place in this contract where the two part company, and a
  deliberate exception to the "tiny AND inexact" rule stated under
  Underflow and the flags below. The tininess convention there
  (after-rounding, 7.5 a) is untouched and simply does not decide this
  case: 9.5 names the condition itself. A subnormal r whose residual
  the format holds exactly raises nothing at all - "the operation's
  subnormal and zero results are exact".
- **The signs of the zeros are two different rules.** An error term
  that is EXACTLY zero "is returned with the sign of
  roundTiesTowardZero(x + y)" - r's sign, so augmentedAddition(-3, 0)
  is (-3, -0). An error term that is non-zero and merely ROUNDS to zero
  keeps the sign of the exact residual, by 6.3's rule for a result that
  is "zero because of rounding". r's own zero sign is 6.3's as
  everywhere else: +0 for an exact cancellation (roundTiesTowardZero is
  not roundTowardNegative), the operand's sign for like-signed zeros,
  the XOR of the signs for a product.
- **Any NaN in gives the canonical quiet NaN as BOTH results**, invalid
  for a signaling one; an invalid operation (inf + (-inf), inf * 0)
  "produces the same quiet NaN for both outputs". An infinity from an
  infinite OPERAND is both results and signals nothing.
- **The error term is always representable for the sum and the
  difference.** Both operands are integer multiples of the format's
  smallest quantum, so the exact sum is one too, and the residual - at
  most half an ulp of r - needs at most p significant bits on a grid
  the format already has. 9.5 gives augmentedAddition no
  non-representable case, and the model and the library both assert it
  rather than trusting it. augmentedMultiplication has the one
  exception 9.5 names, a residual with "non-zero digits ... strictly
  between +-b^(emin-p+1)", and delivers it ROUNDED the same way with
  underflow and inexact raised. **That is the only case in which
  r + e is not exactly x op y**, and it is named rather than tolerated
  wherever the identity is checked.

Clause 11 lists 9.5 among the reproducible operations, which is the
standard making this document's argument for it: "A reproducible
operation is one of the operations described in Clause 5 or is a
supported operation from 9.2, 9.3, 9.5 or 9.6."

Like the clause-5 host operations and the transcendentals, these issue
no device pass: the arithmetic is exact integer work, so the device
argument is context and the results are bit-identical across backends
by construction. A tile-composed fast path (a TwoSum, or an FMA
residual) would have to reproduce these bits exactly - and could not
produce r from the tile's five attributes at all.

## The rest of clause 9.4's reductions

`sum` and `dot` were two of the seven reductions 754-2019 9.4 asks a
language to define. **sumSquare, sumAbs, scaledProd, scaledProdSum and
scaledProdDiff** are the other five, added 2026-09-03 as part of the
0.6 step, on exactly the terms the first two are: **one tree fixed by
element index, one rounding per node, in the caller's attribute.**

The clause is unusually explicit that it leaves this open -
"Implementations may associate in any order or evaluate in any wider
format" - which is precisely the freedom a determinism contract cannot
take. Everything below is what pinning it costs and buys.

### sumSquare and sumAbs ARE the tree, over a different leaf

    sumSquare(x) == dot(x, x)     node for node
    sumAbs(x)    == sum(|x|)      node for node

bit for bit and flag for flag. The library computes them by issuing
exactly those calls, so the device and the software backend agree by
CONSTRUCTION rather than by testing - there is no second tree walker to
keep in step - and a caller who wants the pieces can have them without
changing the answer. `host/tests/reduce_check.py` checks both
identities through the library rather than assuming them.

**One row is not the plain composition, and it is 9.4's own.** For
these two the standard orders the special values differently from sum
and dot:

> "For sumSquare and sumAbs, if any operand element is an infinity,
> +infinity is returned. Otherwise, if any operand element is a NaN a
> quiet NaN is returned." (9.4)

where sum and dot put NaN first. So a vector holding **both** an
infinity and a NaN returns `+inf` here, where the tree alone would
propagate the quiet NaN. Invalid is raised only if one of those NaNs is
signalling - 9.4's blanket rule for every reduction - and no other flag
is, because the result comes from that table rather than from an
addition ("exceptions are not signaled for each exceptional
intermediate operand or result"). With an infinity and NO NaN nothing
is overridden: every term of either operation is a square or a
magnitude, so no term is negative, no `inf - inf` can arise, and the
tree returns `+inf` on its own.

The `n == 1` edge is inherited from the tree and is worth stating
because it deviates from 9.4's blanket signalling-NaN rule: one leaf is
zero additions, so `sumAbs` of a lone sNaN is that pattern with its
sign cleared, raising nothing (abs signals nothing at all, 5.5.1),
while `sumSquare`'s leaf IS a multiply and so quiets it and raises
invalid. That is the same "one leaf means zero adds" reading `sum`
already carries.

### The scaled products, and the scaling rule this contract pins

`scaledProd(p, n)` returns `{pr, sf}` so that `scaleB(pr, sf)`
approximates the product of the elements - an
"implementation-defined approximation", in 9.4's words. Pinned here as:

- **The same index-shaped tree.** A node multiplies its two children's
  significands under the caller's attribute - the node's one rounding -
  and adds their scales.
- **Every node carries a pair**: a significand in `±[1, 2)` and an
  exact integer scale. After each multiply the binade is extracted back
  into the scale. Since `|m_L · m_R| < 4`, that extraction is a shift of
  0, 1 or 2 binades and is **exact** - a power-of-two scaling of a
  normal number never rounds.
- **The leaf is that same extraction** applied to the element, exact for
  every finite non-zero operand, subnormals included: a subnormal has
  fewer significant bits than the format holds, so its normalised
  significand always fits.

That invariant is the whole design. Both operands of every multiply are
in `±[1, 2)`, so every product is in `±[1, 4)`, which cannot leave any
rung of the ladder. Hence 9.4's requirement -

> "In the absence of any of the above, the scaled result, pr, shall not
> be affected by overflow or underflow." (9.4)

- holds **by construction rather than by testing**, and

> "These operations should not signal the divideByZero exception, even
> if implemented with logB." (9.4)

is free: the binade comes out of the encoding rather than out of logB,
and a zero never reaches the tree at all.

`pr` is in `±[1, 2)` for every n, including `n == 0`, where 9.4 fixes
the answer: "pr is 1 and sf is +0 without exception" - the
multiplicative identity, where an empty sum gives the additive one.

**scaledProdSum and scaledProdDiff** are the product of the pairwise
sums and differences. The leaf is ONE contract rounding of `p_i + q_i`
(or `p_i - q_i`) in the caller's attribute, with its full flags, and
its result is the factor everything above sees. **Those two, and only
those two, can signal overflow or underflow - and only from that
addition, never from the product tree.** Both are compositions and hold
as such:

    scaledProdSum(p, q)  == scaledProd(add(p, q))   + the adds' flags
    scaledProdDiff(p, q) == scaledProd(sub(p, q))   + the subs' flags

### The exception rules, and the empty vector

Stated as an independent implementation is scored on them:

- **invalid** for a signalling NaN operand (9.4's blanket rule); for
  `inf x 0` in the product; and for a scale that leaves the int64
  range. Nothing else raises it - in particular an infinity in the
  product with no zero does not, which 9.4 says explicitly.
- **inexact** from any node's multiply (and from any leaf add or
  subtract). 9.4 leaves this "not specified" outside overflow and
  underflow; this contract pins it.
- **overflow and underflow** cannot occur in a scaled product tree at
  all, by the invariant above; scaledProdSum and scaledProdDiff can
  raise them from the leaf addition, and then 9.4's infinity or zero
  row takes over the result.
- **divideByZero** never.
- The special-value rows apply to the **factors** - which for the two
  binary forms are the rounded sums, not the raw operands - in 9.4's
  order: a NaN gives the canonical quiet NaN; an infinity together with
  a zero is invalid and gives that NaN; an infinity alone gives an
  infinity; a zero alone gives a zero. **The sign of that infinity or
  zero is the sign of the true product** - the XOR over every factor's
  sign bit. 9.4 leaves the sign open; a determinism contract cannot. A
  sum of unlike infinities needs no row: that addition raises invalid
  and produces a quiet NaN by itself.
- The empty vector: `+0` and silent for sumSquare and sumAbs, `(1, +0)`
  and silent for the three scaled products.

### The scale's range

`sf` is an **int64**, accumulated with checked additions in tree order;
an addition that would leave the range signals **invalid** and delivers
the canonical quiet NaN for `pr` with `sf = 0`, which is what 9.4
requires when the scale is too large for integralFormat. Since
integralFormat here is not a floating-point format, `sf` still needs a
value and gets 0.

The guard is unreachable in practice and is implemented anyway: a leaf
contributes at most `emax + p - 1 = 262,379` to the magnitude at fp256
and a node at most 2, so a vector would need about 3.5e13 elements -
1.1 petabytes of fp256 - to reach it. The model applies the same
per-addition check so that both sides refuse on exactly the same
inputs, and a test exercises the RULE by narrowing the bound rather
than claiming the constant.

### What each layer can and cannot settle

Worth being precise about, because the strongest oracle here is
deliberately only half an oracle:

| layer | settles | does not settle |
|---|---|---|
| `python/cft_golden/reduce.py` | every bit, by definition | - |
| `host/tests/reduce_check.py` | the C against the model, tree shape included, plus both composition identities and the pr-in-[1,2) invariant | - |
| `host/tools/mpfr_check.c` | **each node's rounding and flags**, arbitrated by GNU MPFR at the format's precision and the caller's mode | **the tree's SHAPE**, which 9.4 leaves to the implementation and which the harness therefore reproduces rather than judges |
| `vectors/out/<fmt>-reduce*.jsonl` | any external implementation, replayably | - |

A reduction whose shape were wrong in both libcft and the MPFR harness
would pass the MPFR campaign. What guards the shape is that there are
two independent implementations of it compared against each other, that
the streaming accumulator agrees with the recursive definition, and
that the published vector sets carry the answers.

## The rest of table 9.1 (clause 9.2)

exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt, pown, powr, compound
and rootn are contract operations with library entry points, added
2026-09-03 as part of the step to ABI 0.6, on exactly the terms the
twenty-nine above are: **correctly rounded, in all five attributes, at
all four formats, with exact flags.** With these ten the contract
covers every operation IEEE 754-2019 table 9.1 defines for the binary
formats.

They need no reduction and no new constant. What they add is
exactness: each has a larger exact-case table than the function it is
built from, and every table is proved closed in
docs/TRANSCENDENTALS.md - which is what makes the inexact flag
trustworthy here and what keeps the Ziv loop terminating.

What belongs here is what an independent implementation is scored on:

- **The exact cases, each an enumeration with a proof.** exp2m1 at
  EVERY integer argument; exp10 and exp10m1 at the non-negative
  integers whose 10^n (odd part 5^n) or 10^n - 1 fits in p+1 bits;
  log2p1 and log10p1 wherever 1 + x is a power of two or of ten;
  rSqrt at the EVEN powers of two and nowhere else; pown, powr and
  compound by phase 1's p+1-bit odd-part bound on pow; rootn wherever
  the odd significand is a perfect |n|-th power and |n| divides the
  exponent. Everything else is inexact, and that is a theorem rather
  than a tolerance.
- **1 + x is formed EXACTLY.** log2p1, log10p1 and compound align the
  two exponents and add the integers; they never evaluate 1 + x in the
  format. `compound(2^-1074, 1)` at binary64 is the correctly rounded
  1 + 2^-1074 - which is 1 with inexact - and not what the format's own
  addition would give.
- **The three integer-exponent operations read an INTEGER.** 9.2.1
  asks for "a finite integral value in integralFormat", so pown,
  compound and rootn take an int64 per element rather than a floating
  operand that would have to be asked whether it is integral. A vector
  set carries it as a signed decimal in an `"n"` field.
- **rootn(x, 1) is x** and **rootn(x, 2) is squareRoot(x)** on every
  input but one: `rootn(-0, 2)` is +0 where `squareRoot(-0)` is -0,
  which is 754-2019's own NOTE and is tested both ways.
- **Three rows follow the standard where GNU MPFR does not**, and an
  implementation scored against MPFR rather than against the standard
  will differ on exactly these: `rSqrt(-0)` is **-infinity** with
  divideByZero (MPFR gives +infinity); `powr(+1, qNaN)` is a **quiet
  NaN** (MPFR gives 1); and `compound(x, 0)` for x below -1 is
  **invalid** rather than 1. Each was measured on MPFR 4.2.2 before it
  was written down.
- **powr is not pow.** A negative base is invalid for every exponent,
  a NaN included; `powr(+-0, +-0)`, `powr(+inf, +-0)` and
  `powr(+1, +-inf)` are invalid; and a quiet NaN operand outranks
  nothing, so `powr(qNaN, 0)` is a NaN where `pow(qNaN, 0)` is 1.
- **rootn(x, 0) is invalid for every x**, a quiet NaN included, because
  zero is outside the domain; a negative operand with an even n
  likewise.
- **Poles signal divideByZero:** `rSqrt(+-0)`, `log2p1(-1)`,
  `log10p1(-1)`, `compound(-1, n)` for n < 0, and the zero rows of
  pown and rootn for a negative n - 7.3's rule for an exact infinity
  from finite operands.
- **A tiny argument is NOT decided by a side here**, and that is a
  derivation rather than an omission: 2^x - 1 is about 0.693x,
  10^x - 1 about 2.303x, log2(1+x) about 1.443x and log10(1+x) about
  0.434x, none of which is beside x. The enclosure resolves all four to
  full relative precision and round_pack carries the underflow. What
  IS decided by a side: exp10 beside 1 for a tiny argument, exp2m1 and
  exp10m1 beside -1 for a very negative one, exp2m1 beside 2^n at an
  integer past p+1, the four powers beside 1, log2p1 and log10p1
  beside the integer k at x = 2^k or 10^k, and compound beside x^n for
  a dominant x.
- **An input that cannot be shown correctly rounded is REFUSED**, on
  the same terms as the three phases before.

Like the twenty-nine, these issue no device pass: the device argument
is context and the results are bit-identical across backends by
construction.

## Character sequences (clause 5.12) and NaN payloads (9.7)

convertFromDecimalCharacter, convertToDecimalCharacter,
convertFromHexCharacter, convertToHexCharacter, getPayload, setPayload
and setPayloadSignaling are contract operations with library entry
points, added 2026-09-03 as part of the 0.6 step. Unlike clause 9's
functions these are not recommendations: 5.12 opens with a **shall**,
and it is the last required part of clause 5 this contract had not
met.

**They are correctly rounded, in all five attributes, at all four
formats, with exact flags - and the standard's H is unbounded here.**
5.12.2 permits an implementation to cap the digit count it will round
correctly at some H >= M + 3, and to incur "additional rounding of the
order of 10^(M-H)" past it. This contract incurs none, at any length,
and the reason belongs in a determinism document rather than in a
manual: a capped conversion is not reproducible against an
implementation with a different cap. Two conforming libraries that
both round correctly agree bit for bit on every sequence; two that
both round "to within a thousandth of an ulp" agree on most of them,
and a vector set cannot tell you which ones.

`python/cft_golden/chars.py` defines every result and every character.
What belongs HERE is what an independent implementation is scored on:

- **The arithmetic is exact and the rounding is round_pack's.** A
  decimal sequence's value is a rational; the binary window is one
  integer division producing p+3 or p+4 bits plus a remainder, which
  is exactly round_pack's (m, e, sticky) precondition. So inexact,
  overflow and underflow are the same flags the same value would get
  from an arithmetic result, including 7.5's tininess-after-rounding
  and 7.4's per-attribute delivered value - an infinity under
  `rne`/`rmm`, the largest finite magnitude under `rtz`.
- **The EXACT conversion is exact, and terminates.** Every binary
  float is a finite decimal because `2^-k = 5^k * 10^-k`, so
  `convertToDecimalCharacter` with no digit count writes the whole
  value: 183,395 significant digits for the smallest binary256
  subnormal and 78,914 for the largest binary256 normal. Those lengths
  are a property of the format, not of this implementation.
- **The round trip is guaranteed at Pmin and is NOT guaranteed one
  digit short.** Pmin is `1 + ceiling(p * log10 2)` - 9, 17, 36 and 73
  - and 5.12.2 promises that a to-decimal / from-decimal pair at that
  many digits under a round-to-nearest attribute reproduces the
  original encoding. This contract holds it and exhibits its edge
  rather than asserting one: at Pmin - 1 there are neighbouring
  encodings whose decimals collide, and both host/tests/character_check.py
  and host/tests/api_test.c name a pair per format (0x417ffff5 and
  0x417ffff6 at binary32, which both write `1.5999990e+1`).
- **inexact is the only flag either output conversion can raise**, and
  only when a digit was dropped. The exponent is written out in full,
  so 5.12.2's "exponent not of sufficient width" overflow and
  underflow cannot arise. The hexadecimal output is exact by
  construction and raises nothing at all.
- **The syntax is exactly 5.12's, and anything else is REFUSED.**
  Optional sign, digits with an optional point, an optional exponent
  part; or 5.12.1's words with an optional payload suffix; or, for the
  hexadecimal parser, 5.12.3's grammar with its REQUIRED binary
  exponent. No whitespace, no separators, no locale, no hexadecimal in
  the decimal parser. A sequence outside it returns a status and
  writes nothing - the same discipline the transcendentals keep when
  they cannot show a result correctly rounded.
- **These are ENCODING operations, so the canonical-NaN rule does not
  reach them.** A NaN keeps its payload, its quiet bit and its sign in
  both directions, because 5.12's own requirement is that the round
  trip recover the original representation. This is the fourth group
  outside that rule, alongside abs/negate/copySign, select and the
  integer opcodes.
- **A signaling NaN is written `snan` and raises NOTHING.** 6.2
  exempts "the conversions described in 5.12" from the signaling-NaN
  rule, and 5.12.1 offers two spellings: write `snan`, or write `nan`
  and signal invalid. This contract takes the first, because the
  second loses the distinction the round trip is required to keep. So
  no conversion in this group ever raises invalid, in either
  direction.
- **The 9.7 payload set is the format's payload field.** Bits
  d2..d(p-1) of the trailing significand (6.2.1), so `0` up to
  `2^(man_w-1) - 1`, and `1` upward for setPayloadSignaling because
  payload 0 with the quiet bit clear is an infinity encoding. Anything
  outside gives `+0` and getPayload of a non-NaN gives `-1`, both of
  which are 9.7's own words. The admissibility test is on the VALUE,
  so `-0` passes it as the integer zero. All three signal nothing, for
  any operand, signaling NaNs included.
- **An exponent no arithmetic can reach still has a defined answer.**
  `1e999999999999` is in the syntax. Rather than materialise
  `10^999999999999`, the library answers from a band: a value whose
  leading bit sits at emax + 1 or above overflows in every attribute,
  and one below half the smallest subnormal rounds to zero or to that
  subnormal by attribute and sign alone. Each band is replaced by one
  representative inside it, so the answer is identical by construction
  rather than approximately right, and the band test brackets log2(10)
  with exact rational bounds and uses no floating point. An
  implementation that computed the power instead lands on the same
  bits; one that clamped to an infinity without checking the sign or
  the attribute does not.

Like the clause-5 host operations and all of clause 9, these issue no
device pass: the work is exact integer division and digit generation,
so the device argument is context and the results are bit-identical
across backends by construction.

## Subnormals

Fully supported, in and out, never flushed - there is no FTZ/DAZ mode
to even switch on. This is the freedom GLSL grants drivers ("a driver
may flush denormals", the exact hazard atlas finding 73 measured) that
this hardware simply does not have.

## NaN

Any NaN in, one canonical quiet NaN out: sign 0, exponent all ones,
quiet bit set, payload zero. A signaling NaN operand raises invalid
(7.2). Invalid operations (`inf * 0`, `inf - inf` in any fused
arrangement) produce the same canonical qNaN with invalid raised.

Deliberate deviation from a 754 *recommendation*: 6.2.3 recommends
(should, not shall) propagating an input NaN's payload. Payload
propagation order is exactly where implementations diverge - which
operand wins varies by vendor - so this contract chooses the one
canonical output instead. RISC-V made the same choice for the same
reason.

## Signed zero

Per 6.3, and the standard's words carry the two rules people miss:

- "When the sum of two operands with opposite signs (or the difference
  of two operands with like signs) is exactly zero, the sign of that
  sum (or difference) shall be +0" in every attribute except
  roundTowardNegative, where it is -0. Implemented in both the model
  and the RTL; `test_exact_cancellation_sign` pins all five.
- "However, ... when x is zero, x + x and x − (−x) have the sign of x"
  - like-signed zeros keep their sign.
- The zero product keeps XOR of the operand signs, which is why MUL's
  steering injects a zero addend carrying sign(a)^sign(b) rather than
  +0.
- FMA: an exactly-zero (a×b)+c follows the sum rules; a result that is
  zero *because of rounding* "takes the sign of the exact result"
  (6.3) - the underflowed-to-zero path keeps the true sign.

## Underflow and the flags

Flags are sticky data, never traps: every element yields a 5-bit set
`{inexact, underflow, overflow, divzero, invalid}` (divzero raised by
`cft_div` for finite/0 and by `logB(+-0)`, exactly per 7.3), and a
run's FLAGS CSR is the OR over all elements - order-independent by
construction.

Tininess is detected **after rounding**: a result is tiny when "a
non-zero result computed as though the exponent range were unbounded
would lie strictly between ± b^emin" (7.5 a). The standard requires
one consistent choice across all operations (7.5); this contract picks
after-rounding (as RISC-V does) and
`test_fp32_tininess_after_rounding_boundary` pins the observable
boundary: `fma(0.75, min_sub, max_sub)` rounds up to exactly
min_normal and must NOT raise underflow, where a before-rounding
implementation raises it.

The underflow flag rises only when the result is both tiny and inexact
(7.5: "if the rounded result is inexact ... the underflow flag shall be
raised. If the rounded result is exact, no flag is raised"). Exact
subnormal results are flagless.

One documented exception, and it is the standard's own: the augmented
arithmetic operations of 9.5 raise underflow when their ERROR TERM is
non-zero and subnormal, whether or not anything was inexact - 9.5
states that condition itself rather than deferring to 7.5. See the
clause-9.5 section above; nothing else in this contract raises
underflow without inexact.

Overflow follows 7.4: overflow and inexact are both raised in every
attribute, and the delivered value is the one that attribute's table
requires (see Rounding above) - infinity under `rne`/`rmm`, the
largest finite magnitude under `rtz`, and one or the other under the
directed attributes depending on which side of zero the result lies.
`test_overflow_response_table` holds all ten combinations as literals.

## Ordering

Elementwise work raises no ordering question at all: element i of the
output depends on element i of the inputs and nothing else, so the
flags OR is the only cross-element artifact and OR is commutative.

**Reductions landed 2026-08-30 and keep the promise this section made
before they existed:** their tree shape is fixed by element index,
never by arrival time or lane availability. A float accumulation whose
order depends on scheduling is the GPU failure mode this design refuses
(the darkroom measured it directly: a compare-and-swap deposit chain
measures warp arrival order, not the plate).

What that fixes, and what it deliberately leaves free, is worth being
precise about, because the freedom is load-bearing:

- **Fixed: the pairing.** Which values are added together, and at which
  level of the tree. `python/cft_golden/reduce.py` defines it - split at
  the largest power of two inside the index range - and everything else
  calls that one function.
- **Free: the schedule.** Adds may be issued in any order and be in
  flight together. A pair's operands are both determined before it
  issues, so when it issues cannot reach the answer. The hardware
  accumulator relies on this: it defers carries so several adds run at
  once, which is the difference between ~1 and ~15 cycles per element.
- **Free: the operand side.** `add(a,b) == add(b,a)` bit for bit here -
  magnitude is symmetric, the sign of an exact cancellation comes from
  the rounding attribute (6.3) rather than operand order, and NaN
  results are always the canonical quiet NaN rather than a propagated
  payload. Verified exhaustively over the interesting-operand pool
  crossed with itself, plus 80,000 random pairs across four formats and
  five attributes, and pinned by a test that asserts its own pair count
  - because it is a property three implementations quietly depend on,
  and because this line claimed 80,000 for a while when the test was
  doing 10,000.
- **Free: which tile.** A partial result is reusable if its range is a
  node of the tree; which physical tile evaluated that node cannot
  enter the answer. See docs/SCALING.md - this is why dynamic load
  balancing is available to a deterministic machine.

All seven of clause 9.4's reductions now share that one tree, including
the three scaled products, whose nodes carry a (significand, scale)
pair rather than a value - see the section above. Nothing in the four
bullets changes for them: the pairing is fixed, the schedule and the
operand side are free, and a scaled product splits across tiles on the
same canonical nodes.
| `host/tests/character_check.py` | the clause-5.12 conversions and the 9.7 payload operations, both directions | golden model, per-element flags, and the Pmin round trip with its collision at Pmin - 1 |

## The verification lattice

Every claim above is a test somewhere, and the layers share no code:

| layer | proves | against |
|---|---|---|
| `python/tests/test_softfloat.py` | golden model semantics | CPython native binary64, `math.fma`, mpmath (all four formats), hand-computed 754 anchors |
| `python/tests/test_clause5.py` | the clause-5 completion semantics | math.remainder/nextafter/ldexp/frexp, struct's double-to-float, an exact-rational rounding reference, hand-derived 754 edges |
| `python/tests/test_augmented.py` | the clause-9.5 pairs and their flags | an independent exact-rational restatement of 9.5, CPython's native binary64 away from the ties, hand-derived 754 edges, and the pair identity in exact integers |
| `python/tests/test_sequences.py` | the composed routes == the contract | bit-for-bit, every format and attribute |
| `tb/test_fpfma_fp32.py` / `_fp256.py` | RTL datapath, streamed | golden model, bit-for-bit incl. flags |
| `tb/test_krnl.py` | CSR + engine + AXI + steering + banks | golden model through the same interfaces XRT uses |
| `host/tests/divsqrt_check.py` / `clause5_check.py` / `augmented_check.py` | the C library's ports of every contract operation | golden model, per-element flags (and, for 9.5, the pair identity in exact integers) |
| `host/tests/transcend_check.py` | the thirty-nine transcendentals, and again through the escalation path | golden model, per-element flags |
| `host/tests/reduce_check.py` | all seven of clause 9.4 - the tree at every n, both composition identities, the scaled products' invariant | golden model, plus the library against itself for the identities |
| `host/tools/divsqrt_soak.c` / `mpfr_check.c` | div/sqrt and the completion set at scale | the host CPU's own IEEE hardware; GNU MPFR (the only external oracle reaching fp128/fp256) |
| `vectors/gen_vectors.py` | any external implementation | replayable JSONL conformance sets |

What is deliberately NOT claimed yet: behaviour on a physical card
(docs/BRINGUP.md gates that), and any timing/performance number.

## Clause locator index

For auditors with the standard open: format parameters 3.6 Table 3.5;
roundToIntegral, nextUp/nextDown and remainder 5.3.1 (rint details
5.9); scaleB and logB 5.3.3; fusedMultiplyAdd, division, squareRoot
and the integer conversions 5.4.1; convertFormat 5.4.2; signaling
comparisons 5.6.1; classification predicates 5.7.2; totalOrder 5.10;
quiet comparisons 5.11; the character-sequence conversions 5.12
(the words 5.12.1, decimal 5.12.2, hexadecimal 5.12.3; their
formatOf entries 5.4.2 and 5.4.3); NaN semantics 6.2 (binary NaN
encodings and the payload field 6.2.1, payload recommendation
6.2.3); sign bit rules 6.3; invalid 7.2; divideByZero 7.3; overflow
7.4; underflow and tininess 7.5; the recommended correctly-rounded
functions and their special-value tables 9.2 (the table itself 9.2.1);
the augmented arithmetic operations and roundTiesTowardZero 9.5;
the reduction operations - sum, dot, sumSquare, sumAbs and the three
scaled products - 9.4; minimum/maximum 9.6; the reproducible-operation list 11.
docs/COMPLIANCE.md is the clause-by-clause matrix: every operation the
standard names for binary formats, with its status here.
