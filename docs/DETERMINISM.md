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
correctly rounded. Everything is scored the same way regardless of route:
`python/cft_golden/softfloat.py` defines the bits.

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
invalid - governs **arithmetic**. Three groups are outside it, and
saying so precisely matters because this document is what an
independent implementation is scored against:

| group | NaN behaviour |
|---|---|
| `abs`, `negate`, `copySign` | pass the pattern through, payload intact, signal **nothing** even for a signaling NaN (5.5.1: "they only affect the sign bit... and signal no exception"; 6.2.3 exempts exactly these) |
| `select` | moves whichever operand it selects through intact, payload and all, and signals nothing |
| the integer group | there are no NaNs - the operand is a W-bit unsigned word, and no bit pattern means anything but itself |

None of this weakens determinism. The canonical rule exists because in
arithmetic *which operand's payload survives* is where implementations
diverge; in every case above the result is a function of the input
bits with no choice to make. 754-2019 7.1 leaves the signalling
behaviour of operations outside the standard to the implementation,
and this table is that definition.

### Unassigned opcodes

Opcode 15 and everything from **28** up are unassigned. They return the
canonical quiet NaN with **invalid** raised, in the hardware and in
the golden model alike. Deterministic, and visible in the flags, so a
host that issues one early learns it now rather than getting a
plausible number that changes meaning under a later bitstream.

The hazard is not hypothetical; it has now fired twice. 24 and 25
became `sum` and `dot` (2026-08-30), and 26 and 27 became the
divide/sqrt seeds (2026-08-31) - each time, a vector set generated
before the assignment still named the opcode "reservedNN", and
replaying one would score the new operation against an answer recorded
for the unassigned-opcode result. `cft_conformance` detects that
specifically and says so, rather than reporting a mismatch. Note that
the rest of clause 5 landed WITHOUT consuming opcode space: the new
operations are library entry points over existing opcodes plus exact
host bookkeeping, so no further reassignment hazard was created.

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

## The verification lattice

Every claim above is a test somewhere, and the layers share no code:

| layer | proves | against |
|---|---|---|
| `python/tests/test_softfloat.py` | golden model semantics | CPython native binary64, `math.fma`, mpmath (all four formats), hand-computed 754 anchors |
| `python/tests/test_clause5.py` | the clause-5 completion semantics | math.remainder/nextafter/ldexp/frexp, struct's double-to-float, an exact-rational rounding reference, hand-derived 754 edges |
| `python/tests/test_sequences.py` | the composed routes == the contract | bit-for-bit, every format and attribute |
| `tb/test_fpfma_fp32.py` / `_fp256.py` | RTL datapath, streamed | golden model, bit-for-bit incl. flags |
| `tb/test_krnl.py` | CSR + engine + AXI + steering + banks | golden model through the same interfaces XRT uses |
| `host/tests/divsqrt_check.py` / `clause5_check.py` | the C library's ports of every contract operation | golden model, per-element flags |
| `host/tests/transcend_check.py` | the twenty-nine transcendentals, and again through the escalation path | golden model, per-element flags |
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
quiet comparisons 5.11; NaN semantics 6.2 (payload recommendation
6.2.3); sign bit rules 6.3; invalid 7.2; divideByZero 7.3; overflow
7.4; underflow and tininess 7.5; the recommended correctly-rounded
functions and their special-value tables 9.2 (the table itself 9.2.1);
minimum/maximum 9.6.
