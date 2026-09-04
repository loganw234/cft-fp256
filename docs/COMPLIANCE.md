# IEEE 754-2019, clause by clause

What this library has of the standard, what it deliberately leaves
out, and what is simply not there yet. Status at ABI 0.6 (2026-09-03),
for the binary formats. The operation lists below were taken from the
standard's own text, clause by clause, not from memory; the counts are
derived from those lists.

The one-line answer: **every operation the standard names for binary
formats is here except four**, and those four - the magnitude forms of
minimum and maximum in 9.6 - are host-side selections with no rounding
in them. Of the 146 operations clauses 5 and 9 name for binary formats,
139 exist in the library or its language contexts, 3 are conformance
predicates that belong to a language rather than a library, and 4 are
the gap.

Legend. **yes**: present, defined by the golden model, gated by the
runner. **yes (contexts)**: the C library holds no state by design, so
the facility lives in the Python `Context` and the C++ context objects,
one attribute each. **exceeds**: more than the clause asks. **gap**:
named by the standard, absent here. **excluded**: left out by design and
stated in docs/DETERMINISM.md. **language**: the clause addresses a
language standard, not a library.

## Clause 3 - formats

| clause | item | status |
|---|---|---|
| 3.3, 3.4 | binary32, binary64, binary128 interchange formats and their encodings | yes |
| 3.6 | binary256 as a binary*k* interchange format: p = 237, emax = 262143 from the clause's own formulas | yes |
| 3.4 | NaN encodings: quiet bit, sign, payload | yes; results carry the canonical quiet NaN (6.2.3, below) |
| 3.5 | decimal formats | excluded - a different datapath, effectively its own tile |
| 3.7 | extended and extendable precisions | not provided; optional |

## Clause 4 - attributes and rounding

| clause | item | status |
|---|---|---|
| 4.3.1 | roundTiesToEven | yes, the default |
| 4.3.2 | roundTowardPositive, roundTowardNegative, roundTowardZero | yes |
| 4.3.3 | roundTiesToAway | yes - optional for binary formats, so exceeds |
| 4.2 | attribute specification | static, per operation, in C (the clause allows static or dynamic); dynamic in the contexts (9.3) |
| 4.1 | preferredWidth, value-changing optimization, reproducible-results attributes | language; the library never widens, contracts or reassociates, so every call already behaves as if those were set to their strictest values |

## Clause 5 - required operations

| clause | operations | status |
|---|---|---|
| 5.3.1 | roundToIntegralTiesToEven, TiesToAway, TowardZero, TowardPositive, TowardNegative | yes - `cft_rint` with the attribute |
| 5.3.1 | roundToIntegralExact | yes - `cft_rint` with `exact` |
| 5.3.1 | nextUp, nextDown | yes |
| 5.3.1 | remainder | yes - `cft_rem`, exact by construction |
| 5.3.1 | quantize | excluded (decimal) |
| 5.3.2 | decimal operations | excluded |
| 5.3.3 | scaleB, logB | yes |
| 5.4.1 | addition, subtraction, multiplication, fusedMultiplyAdd | yes - tile opcodes, the steered FMA |
| 5.4.1 | division, squareRoot | yes - composed from the seed opcodes and FMA, correctly rounded |
| 5.4.1 | convertFromInt | yes - int32, uint32, int64, uint64 |
| 5.4.1 | convertToInteger, five directions, and convertToIntegerExact, five directions | yes - `cft_cvt_to_*` with the attribute and `exact`; the values 754 leaves open on invalid are fixed by the contract |
| 5.4.2 | convertFormat | yes - `cft_convert`, any of the four to any other |
| 5.4.2 | convertFromDecimalCharacter, convertToDecimalCharacter | yes, correctly rounded at every digit count - 5.12.2's H is unbounded, so exceeds |
| 5.4.3 | convertFromHexCharacter, convertToHexCharacter | yes |
| 5.5.1 | copy, negate, abs, copySign | yes - the encoding itself, `CFT_NEG`, `CFT_ABS`, `CFT_COPYSIGN`; signal nothing |
| 5.5.2 | decimal re-encoding | excluded |
| 5.6.1 | the 22 comparison predicates | yes - `CFT_CMPLT`, `CFT_CMPLE`, `CFT_CMPEQ` quiet, the same three signaling through `cft_cmp_sig`, and `cft_class` for unordered; the other sixteen are the standard's own negations and operand swaps of these, which is how 5.11 defines them |
| 5.7.1 | is754version1985, is754version2008, is754version2019 | language - they describe a programming environment; this file is the library's conformance statement |
| 5.7.2 | class, isSignMinus, isNormal, isFinite, isZero, isSubnormal, isInfinite, isNaN, isSignaling, isCanonical, radix | yes - `cft_class`; every is* predicate is a subset test on its byte; isCanonical constantly true, radix constantly 2 |
| 5.7.2 | totalOrder, totalOrderMag | yes |
| 5.7.3 | sameQuantum | excluded (decimal) |
| 5.7.4 | lowerFlags, raiseFlags, testFlags, testSavedFlags, restoreFlags, saveAllFlags | yes (contexts) - the sticky word on the Python `Context` and the C++ context; C returns each call's exception group and keeps no flag state, by design |
| 5.8 - 5.11 | the details of conversion, comparison and totalOrder | yes - the golden model follows them; the one value the standard leaves to the implementation (5.8, invalid conversions) is fixed |
| 5.12 | external character sequences, decimal and hexadecimal | yes - both directions, no cap on digits, the grammar as written in `python/cft_golden/chars.py` |

## Clauses 6 and 7 - special values, default exception handling

| clause | item | status |
|---|---|---|
| 6.1 | infinity arithmetic | yes |
| 6.2.1 | signaling and quiet NaNs; invalid on a signaling operand in every general-computational operation, silence in the non-computational ones | yes |
| 6.2.3 | NaN payload propagation through arithmetic - a "should" | excluded: every NaN result is the canonical quiet NaN. 9.7's operations read and write payloads; arithmetic does not carry them |
| 6.3 | the sign bit, including exact zero results under each attribute | yes |
| 7.1 | flags raised per operation, per element or accumulated | yes |
| 7.2 - 7.4, 7.6 | invalid, divideByZero, overflow, inexact | yes |
| 7.5 | underflow; tininess detected after rounding | yes - one of the two detections the clause allows, stated in docs/DETERMINISM.md |

## Clause 8 - alternate exception handling

Excluded. Only default handling exists, which is also what clause 11
requires of a reproducible program.

## Clause 9 - recommended operations

| clause | operations | status |
|---|---|---|
| 9.1 | conforming language-defined operations | language |
| 9.2 | Table 9.1, all 39 | yes - correctly rounded in every format and attribute with exact flags, which is what 9.2 asks of a conforming operation; docs/TRANSCENDENTALS.md holds the proofs |
| 9.3 | getBinaryRoundingDirection, setBinaryRoundingDirection, saveModes, restoreModes, defaultModes | yes (contexts) - the rounding attribute on the Python `Context` and the C++ context; the decimal pair excluded |
| 9.4 | sum, dot, sumSquare, sumAbs, scaledProd, scaledProdSum, scaledProdDiff | yes - over a contractual tree, where the clause leaves the order to the implementation |
| 9.5 | augmentedAddition, augmentedSubtraction, augmentedMultiplication, with roundTiesTowardZero | yes |
| 9.6 | minimum, minimumNumber, maximum, maximumNumber | yes - the four opcodes |
| 9.6 | **minimumMagnitude, minimumMagnitudeNumber, maximumMagnitude, maximumMagnitudeNumber** | **gap** |
| 9.7 | getPayload, setPayload, setPayloadSignaling | yes |

## Clauses 10 and 11 - expression evaluation, reproducibility

Both address language standards. What they ask for is what this
library is: each entry point is one formatOf operation with no
implicit widening, contraction or reassociation (10.4's literal
meaning), the reduction tree is fixed by the contract rather than left
to the implementation, only default exception handling exists, and the
character conversions carry no precision limit - the three things
clause 11 puts on a "reproducible results required" program. Clause 11
counts only invalid, divideByZero and overflow as reproducible flags;
here underflow and inexact reproduce too, because tininess detection
and the rounding position are part of the contract.

## The gap, and its size

**9.6's magnitude four.** The standard defines them in one line each:

> minimumMagnitude(x, y) is x if |x| < |y|, y if |y| < |x|, otherwise
> minimum(x, y).

and the same shape for the other three with maximum, minimumNumber and
maximumNumber in the last position. They are selections on the
encoding - a magnitude compare, then the existing operation - so they
are host-side bit surgery of the nextUp kind: no rounding, no
attribute, invalid on a signaling NaN exactly as the four existing
forms raise it. The work is the smallest package this repo has shipped:
four functions in the golden model, four host entry points or opcodes,
their tests, vector sets, and the four language surfaces. Nothing in
them needs the tile.

**5.7.1's three predicates** are not counted as a gap. They ask whether
a *programming environment* conforms, which a library cannot answer
for the language above it. A binding that wants one returns a constant.

Everything else the standard names for binary formats is present, on
the terms above, with the stated exclusions - decimal formats, clause
8, and payload propagation through arithmetic - which are choices,
recorded as such, not gaps.
