# IEEE 754-2019, clause by clause

What this library has of the standard, what it deliberately leaves
out, what is not there yet, and what the standard's own conformance
clause would ask before the word "conforms" could be used. Status at ABI 0.7 (2026-09-04), for the binary formats. The operation lists
below were taken from the standard's text, clause by clause, not from
memory; the counts are derived from those lists.

**The short answer.** The library conforms to IEEE 754-2019 in radix 2.
Clause 3.1.2 says an implementation of an arithmetic format "shall
provide all the operations of this standard defined in Clause 5, for
that format", and that a programming environment conforms "in a
particular radix, by implementing one or more of the basic formats of
that radix as both a supported arithmetic format and a supported
interchange format". binary32, binary64 and binary128 are the basic
formats here, binary256 a further interchange format that is also
arithmetic; every clause-5 operation exists for each of them, with the
cross-format forms of 5.4.1, the status word of 7.1 and 5.7.4, and the
predicates of 5.7.1 landing at ABI 0.7. Every recommended operation of
clause 9 for binary formats exists as well, all eight forms of 9.6
included. What is not provided is a choice, listed at the end, and
every item in it is something the standard permits an implementation
in radix 2 to leave out.

Legend. **yes**: present, defined by the golden model, gated by the
runner. **yes (contexts)**: the C library holds no state by design, so
the facility lives in the Python `Context` and the C++ context objects,
one attribute each. **composition**: not an entry point, but exactly
reachable from the entry points that exist, and said how. **exceeds**:
more than the clause asks. **excluded**: left out by design and stated in
docs/DETERMINISM.md. **language**: the clause addresses a language
standard, not a library.

## Clause 3 - formats

| clause | item | status |
|---|---|---|
| 3.3, 3.4 | binary32, binary64, binary128 interchange formats and their encodings | yes |
| 3.6 | binary256 as a binary*k* interchange format: p = 237, emax = 262143 from the clause's own formulas | yes |
| 3.4 | NaN encodings: quiet bit, sign, payload | yes; results carry the canonical quiet NaN (6.2.3, below) |
| 3.1.2 | initialise a format; convert between every pair of supported formats; read and write the encoding | yes - the character and integer conversions, `cft_convert` over all sixteen pairs, the encodings as byte arrays |
| 3.5 | decimal formats | excluded - a different datapath, effectively its own tile; conformance is claimed per radix, so this is permitted |
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
| 5.4.1 | addition, subtraction, multiplication, fusedMultiplyAdd, operands and destination in one format | yes - tile opcodes, the steered FMA |
| 5.4.1 | division, squareRoot, one format | yes - composed from the seed opcodes and FMA, correctly rounded |
| 5.4.1 | the same six as formatOf operations: operands in one format, destination in another, one rounding | yes - `cft_formatof_add/sub/mul/div/sqrt/fma` (ABI 0.7): when the destination is not narrower the operands widen exactly and the existing operation issues, so a device still runs it; when it is narrower the exact result is formed and rounded once against the destination - none of the six can be double rounded when the operands carry the source's precision, and the model constructs the counter-example for every narrowing pair |
| 5.4.1 | convertFromInt | yes - int32, uint32, int64, uint64 |
| 5.4.1 | convertToInteger, five directions, and convertToIntegerExact, five directions | yes - `cft_cvt_to_*` with the attribute and `exact`; the values 754 leaves open on invalid are fixed by the contract |
| 5.4.2 | convertFormat | yes - `cft_convert`, any of the four to any other |
| 5.4.2 | convertFromDecimalCharacter, convertToDecimalCharacter | yes, correctly rounded at every digit count - 5.12.2's H is unbounded, so exceeds |
| 5.4.3 | convertFromHexCharacter, convertToHexCharacter | yes |
| 5.5.1 | copy, negate, abs, copySign | yes - the encoding itself, `CFT_NEG`, `CFT_ABS`, `CFT_COPYSIGN`; signal nothing |
| 5.5.2 | decimal re-encoding | excluded |
| 5.6.1 | the 22 comparison predicates, one format | yes - `CFT_CMPLT`, `CFT_CMPLE`, `CFT_CMPEQ` quiet, the same three signaling through `cft_cmp_sig`, and `cft_class` for unordered; the other sixteen are the standard's own negations and operand swaps of these, which is how 5.11 defines them |
| 5.11 | comparison across two binary formats | composition - widen the narrower operand with `cft_convert`, which is exact, then compare; a signaling NaN signals invalid on the way, as the comparison itself would |
| 5.7.1 | is754version1985, is754version2008, is754version2019 | yes (ABI 0.7) - false, false, true. 2008 is not asserted because 754-2008 required minNum/maxNum/minNumMag/maxNumMag with a signaling-NaN rule that 2019's minimumNumber changed, and this library implements the 2019 semantics; 1985 is not asserted because it was not evaluated against the 1985 text |
| 5.7.2 | class, isSignMinus, isNormal, isFinite, isZero, isSubnormal, isInfinite, isNaN, isSignaling, isCanonical, radix | yes - `cft_class`; every is* predicate is a subset test on its byte; isCanonical constantly true, radix constantly 2 |
| 5.7.2 | totalOrder, totalOrderMag | yes |
| 5.7.3 | sameQuantum | excluded (decimal) |
| 5.7.4 | lowerFlags, raiseFlags, testFlags, testSavedFlags, restoreFlags, saveAllFlags | yes (ABI 0.7) - `cft_lower_flags`, `cft_raise_flags`, `cft_test_flags`, `cft_test_saved_flags`, `cft_restore_flags`, `cft_save_all_flags` over the status word on the device handle; the Python `Context` and the C++ context read that same word rather than keeping their own |
| 5.8 - 5.11 | the details of conversion, comparison and totalOrder | yes - the golden model follows them; the one value the standard leaves to the implementation (5.8, invalid conversions) is fixed |
| 5.12 | external character sequences, decimal and hexadecimal | yes - both directions, no cap on digits, the grammar as written in `python/cft_golden/chars.py` |

## Clauses 6 and 7 - special values, default exception handling

| clause | item | status |
|---|---|---|
| 6.1 | infinity arithmetic | yes |
| 6.2.1 | signaling and quiet NaNs; invalid on a signaling operand in every general-computational operation, silence in the non-computational ones | yes |
| 6.2.3 | NaN payload propagation through arithmetic - a "should" | excluded: every NaN result is the canonical quiet NaN. 9.7's operations read and write payloads; arithmetic does not carry them |
| 6.3 | the sign bit, including exact zero results under each attribute | yes |
| 7.1 | the five exceptions signalled, default results delivered, the flags raised, and a status flag per exception that stays raised until the user lowers it | yes - per call in `flags_out`, and cumulatively in the device handle's status word, which every entry point ORs into through one hook and only the caller lowers (ABI 0.7) |
| 7.2 - 7.4, 7.6 | invalid, divideByZero, overflow, inexact | yes |
| 7.5 | underflow; tininess detected after rounding | yes - one of the two detections the clause allows, stated in docs/DETERMINISM.md |

## Clause 8 - alternate exception handling

Excluded. It is recommended, not required. Only default handling
exists, which is also what clause 11 requires of a reproducible
program.

## Clause 9 - recommended operations

| clause | operations | status |
|---|---|---|
| 9.1 | conforming language-defined operations | language |
| 9.2 | Table 9.1, all 39 | yes - correctly rounded in every format and attribute with exact flags, which is what 9.2 asks of a conforming operation; docs/TRANSCENDENTALS.md holds the proofs |
| 9.3 | getBinaryRoundingDirection, setBinaryRoundingDirection, saveModes, restoreModes, defaultModes | yes (contexts) - the rounding attribute on the Python `Context` and the C++ context; the decimal pair excluded |
| 9.4 | sum, dot, sumSquare, sumAbs, scaledProd, scaledProdSum, scaledProdDiff | yes - over a contractual tree, where the clause leaves the order to the implementation |
| 9.5 | augmentedAddition, augmentedSubtraction, augmentedMultiplication, with roundTiesTowardZero | yes |
| 9.6 | minimum, minimumNumber, maximum, maximumNumber | yes - the four opcodes |
| 9.6 | minimumMagnitude, minimumMagnitudeNumber, maximumMagnitude, maximumMagnitudeNumber | yes (ABI 0.7) - `cft_min_mag`, `cft_max_mag`, `cft_minnum_mag`, `cft_maxnum_mag`, host entry points from the clause's own definitions |
| 9.7 | getPayload, setPayload, setPayloadSignaling | yes |

## Clauses 10 and 11 - expression evaluation, reproducibility

Both address language standards. What they ask for is what this
library is: each entry point is one operation with no implicit
widening, contraction or reassociation (10.4's literal meaning), the
reduction tree is fixed by the contract rather than left to the
implementation, only default exception handling exists, and the
character conversions carry no precision limit - the three things
clause 11 puts on a "reproducible results required" program. Clause 11
counts only invalid, divideByZero and overflow as reproducible flags;
here underflow and inexact reproduce too, because tininess detection
and the rounding position are part of the contract.

## The conformance statement

The standard's own term is that a programming environment "conforms
to this standard, in a particular radix" (3.1.2). This library
conforms to IEEE 754-2019 in radix 2, from ABI 0.7 (2026-09-04), on these
terms:

- binary32, binary64 and binary128 are supported arithmetic and
  interchange formats; binary256 is a further supported arithmetic and
  interchange format, with 3.6's parameters for k = 256.
- Every operation of clause 5 is provided for each of them, the
  cross-format forms of 5.4.1 included, with correctly rounded results
  and the flags of clause 7, and every conversion of 5.12 with no limit
  on the digit count.
- All five rounding-direction attributes of 4.3 are provided;
  roundTiesToAway is optional in radix 2 and is provided anyway.
- Tininess is detected after rounding (7.5 allows either).
- The status word of 7.1 is on the device handle, raised by every
  operation and lowered only by the caller, with the six operations of
  5.7.4 over it.
- Every recommended operation of clause 9 for binary formats is
  provided: all 39 of Table 9.1 correctly rounded, the seven reductions,
  the three augmented operations, all eight forms of 9.6, the three
  payload operations, and the dynamic modes of 9.3 in the language
  contexts.
- is754version2019 answers true; is754version2008 and is754version1985
  answer false, for the reasons in the 5.7.1 row.

Not provided, by choice, and permitted: the decimal formats
(conformance is per radix); clause 8's alternate exception handling
(recommended); NaN payload propagation through arithmetic (6.2.3 is a
recommendation; every NaN result is the canonical quiet NaN, and 9.7's
operations read and write payloads explicitly). Clauses 10 and 11
address language standards; the library already behaves as their
strictest settings require.

Evidence: the golden model defines every operation from the standard's
text; `verify/run.sh` gates the C library, the C++ header, the Python
package, the Node package and the browser page against it, and GNU MPFR
arbitrates every operation it can reach - 739,234 cases with zero
value and zero flag mismatches at ABI 0.7. docs/VALIDATION.md holds the
census, and the earlier version of this section, which listed the four
items 0.7 closed and what each would cost, is in that file's history.
