# The transcendentals, correctly rounded

exp, expm1, exp2, log, log1p, log2, log10, pow and hypot - phase 1 of
the transcendental set, landed 2026-09-02 as ABI 0.3. This is the
design, the proofs it rests on, and the measurements that were actually
taken.

## The promise, and why it is the only one worth making

**Correctly rounded, at all four formats, under all five rounding
attributes, with exact flags.** Not "accurate to an ulp", not
"faithful", not "algorithm-defined".

That is the same promise the rest of this library makes, and for these
functions it is the whole point. A result here is defined by the
mathematics alone: `exp(x)` rounded to binary64 under roundTiesToEven
is one specific bit pattern, and every correct implementation returns
it. An *accurate* exponential is a different thing entirely - two of
them disagree in the last bit on a percentage of inputs, neither can be
scored against the other, and "the same bits everywhere" quietly stops
being true in exactly the places nobody looks. A determinism contract
that stopped at the arithmetic and shipped an approximate `exp` would
have a hole in it the size of every application that uses one.

So: correctly rounded, or a status. If an input cannot be *shown*
correctly rounded within the library's working-precision cap, the call
returns `CFT_ERR_INTERNAL`. It does not return a plausible number.

## Why they are host operations

`cft_div` and `cft_sqrt` are composed from the tile's own opcodes: a
seed, Newton refinement, an exactly measured residual, one rounding.
The transcendentals are not, and the reason is structural rather than
an omission.

Division can decide its own last bit because it has an exactly
measurable residual. Given a candidate quotient q, the quantity
`a - q*b` is one fused multiply-add away and is EXACT - the datapath
computes it with no rounding at all - so the sign of that residual says
which side of the boundary the true quotient falls on, and one more
exact FMA against the half-ulp midpoint gives the guard bit. Square
root has the same structure with `a - s*s`.

`exp` has no such residual. There is no fused operation whose exact
result tells you which side of a rounding boundary `e^x` lies on;
knowing that requires more precision than the format has, and more
precision means a multiprecision evaluator, which is integer work. So
these are HOST operations: no `cft_run` pass is issued, no bus word is
produced, and the device argument is context, exactly as it is for the
clause-5 operations that contain no floating-point arithmetic.

A tile-assisted fast path for fp32 and fp64 is a plausible later
optimisation - the tile's FMA could carry a polynomial evaluation, with
the host deciding only the cases the polynomial cannot - but it would
have to reproduce these bits exactly, and that makes it an optimisation
rather than a different answer. It is not part of this contract.

## Two implementations, one definition

`python/cft_golden/transcend.py` defines every bit. `host/src/`'s
`mpfloat.c` and `transcend.c` are the library's own, and they share no
arithmetic with the model: the model evaluates with mpmath at a
working precision, the C evaluates with its own multiprecision floats
and a tracked error bound. What they DO share is the decision
procedure, and it is the thing that makes the whole design work.

Both split every input three ways:

1. **Exact cases**, decided by exact integer arithmetic and packed
   through `round_pack`.
2. **Neighbour cases**, where the true value provably lies inside one
   half of the gap next to a representable number, and the answer
   follows from which SIDE it is on.
3. **Everything else**, decided by an enclosure: compute an interval
   that provably contains the true value, round BOTH ends under the
   requested attribute, and accept the result only when they agree on
   the bits and on the flags. If they do not, raise the working
   precision and try again.

Step 3 is sound because rounding under every attribute is monotone in
the value, and so are tininess and the overflow test. Agreement at the
two ends is therefore agreement everywhere between them, and the true
value is between them.

## Why the loop terminates

A Ziv loop hangs exactly when the true value sits ON a rounding
boundary - a grid point or a midpoint - because no finite precision
ever separates it from one side. Every boundary is a dyadic rational,
so the loop can only hang where the true value is one, and the exact
cases are precisely an enumeration of when that happens:

| function | the true value is a dyadic rational exactly when |
|---|---|
| exp, expm1 | the argument is 0 (Lindemann-Weierstrass: `exp` of a nonzero algebraic number is transcendental) |
| log, log1p | the argument is 1 / 0 (same theorem, other direction) |
| exp2 | the argument is an integer |
| log2 | the argument is a power of two |
| log10 | the argument is 10^k for k >= 0 with 5^k inside p bits (a negative power of ten is not a dyadic rational, so it is never an operand) |
| pow | see below |
| hypot | x^2 + y^2 is a perfect square in the dyadic rationals |

`exp2` of a non-integer dyadic is an irrational algebraic number;
`log2` of anything but a power of two, and `log10` of anything but a
power of ten, are irrational by unique factorisation. Those three lines
are proofs, not observations.

**pow and hypot need a bound to make the enumeration finite**, and it
is the same bound for both. A dyadic value `O * 2^k` with O odd is a
grid point of a p-bit format only if O fits in p bits, and a midpoint
only if it fits in p+1. So:

> A dyadic rational whose odd part needs more than p+1 bits cannot be
> a rounding boundary of a p-bit format.

For `pow`, write |x| = M·2^E and y = ±Y·2^F with M and Y odd. If y is
an integer n: the value is M^n·2^(En), whose odd part is M^n, so either
M = 1 (a pure exponent shift, computed directly) or n <= p+1 (and the
power is computed exactly with an early exit the moment it passes p+1
bits) or the value is not a boundary. A negative n with M > 1 gives a
rational that is not dyadic, which is not a boundary either. If y is
not an integer, y = ±Y/2^k with Y odd, and |x|^y is rational only if
|x| is an exact 2^k-th power - Y odd forces every prime exponent of M,
and E, to be divisible by 2^k - which k verified integer square roots
decide. All of it is bounded work.

For `hypot`, x^2 and y^2 have odd significands, so their sum loses at
most one low bit to carries (and only when the two square the same
power of two). A pair whose set bits span more than p+6 places
therefore has a sum whose odd part is wider than 2p+2 bits, whose
square root - if it has one - has an odd part wider than p+1 bits.
Everything inside that span is computed exactly and tested with one
integer square root.

## The neighbour rules, and why they are not an approximation

Four families are decided by neither an exact value nor an enclosure:

| family | the true value |
|---|---|
| exp(x), exp2(x) for \|x\| < 2^-(p+3) | strictly between 1 and its neighbour on the sign side of x |
| expm1(x) for \|x\| < 2^-(p+2) | strictly between x and the next value AWAY from zero: expm1(x) - x = x^2/2 + ... > 0 |
| log1p(x) for \|x\| < 2^-(p+2) | strictly between x and the next value TOWARD -infinity: log1p(x) - x = -x^2/2 + ... < 0 |
| pow(x, y) with \|y log x\| < 2^-(p+3) | strictly between 1 and its neighbour on the side the exact operand signs give |
| hypot(x, y) with 2·e_small + p + 2 < 2·e_big | strictly between \|big\| and the next value away from zero |

These are the inputs a naive Ziv loop runs forever on. log1p(2^-1074)
at binary64 differs from 2^-1074 by 2^-2149, and NO working precision
this or any evaluator carries will separate them - yet the answer is
not 2^-1074 under three of the five attributes. The separation is not
needed: the SIDE is known exactly, from the sign of a series term, and
the side is the whole answer.

Each rule places a WITNESS an eighth of a gap from the representable
neighbour and rounds that through `round_pack`. Every value strictly
inside that half of the gap rounds identically under all five
attributes - to the neighbour, except in the one directed attribute
that points across the gap - so the witness answers for the true value.
`round_pack` then derives the flags: inexact always, underflow when
the landing is tiny, and the overflow response when the neighbour is
the largest finite and the attribute steps past it. That last case is
real: `hypot(maxfinite, minsubnormal)` under roundTowardPositive is
+infinity with overflow raised.

The thresholds are derived, not chosen. For expm1 and log1p:
|f(x) - x| < 0.51·x^2 for |x| <= 1/16, the gap to the neighbour is at
least 2^(e-p) where e = floor(log2|x|), and 0.51·2^(2e+2) < 2^(e-p-1)
reduces to e <= -(p+3). For exp and exp2: |exp(x) - 1| < 1.01|x| and
the smaller gap next to 1 is 2^-(p+1), giving |x| < 2^-(p+3). For
hypot: sqrt(X^2+Y^2) - X < Y^2/(2X), and requiring that below a
quarter of the gap above X gives the exponent condition in the table.

## The multiprecision evaluator

`host/src/mpfloat.h` is a sign, an integer exponent, a W-bit
significand in a `cft_bn`, and an error bound. Floating point, not
fixed, and two input families settle that on their own:

- `pow(1 + 2^-236, 2^262000)` at fp256. The logarithm of that base is
  about 2^-236 and the product with y is an ordinary number, so the
  answer is ordinary - but a fixed-point evaluator carrying W bits
  below the point would need 236 + W of them to keep the base's
  logarithm to RELATIVE accuracy, and then a further 262,000 above the
  point for the exponent. The width would be set by the exponent RANGE
  rather than by the precision, which is the definition of the wrong
  representation.
- `log1p(2^-262000)`. The result is about 2^-262000 and must be correct
  to p bits OF ITS OWN MAGNITUDE. A fixed-point word deep enough to
  hold it is a third of a megabit wide and almost all zeroes.

### The error model

`err` counts units of 2^-W of RELATIVE error:

    |true - value| <= err * 2^-W * |value|

Relative rather than an ulp count, because relative error is ADDITIVE
through a multiplication where an ulp count is not: a significand just
above 2^(W-1) has ulps twice as coarse, relatively, as one just below
2^W, so an ulp-based bound has to be doubled at every multiply to stay
safe, and 2^170 over a series is not a bound but a surrender.

The rules, each an upper bound and each rounded up:

| step | bound |
|---|---|
| truncation to W bits | +2 (one ulp is at most 2·2^-W relatively) |
| multiply | Ea + Eb + 3 |
| divide | Ea + Eb + 3 |
| add, like signs | Ea + Eb + 2 (\|a+b\| >= max(\|a\|,\|b\|)) |
| add, unlike signs | 2·(Ea << (ea-er)) + 2·(Eb << (eb-er)) + 2 |
| square root | ceil(Ea/2) + 2 |
| scale by a power of two | exact |

The unlike-signs row is where a subtraction that loses k bits costs k
bits of the error budget, and it is the term the algorithms below are
shaped to keep small.

**The bound is checked, not trusted.** `cft_mp_round` rounds both ends
of `[m - err, m + err] * 2^exp` and accepts only if they agree. A bound
that is too generous costs an escalation; it cannot cost a wrong
answer. The only bound that could is one that is too SMALL, which is
why every rule rounds up and why the saturating arithmetic saturates
upward.

One consequence took a deliberate experiment to find. When two
approximations cancel EXACTLY, the difference is not provably zero -
and an exact zero is the one value that destroys the bound rather than
widening it, because zero has no relative error to carry. `cft_mp_add`
therefore returns a saturated bound rather than a zero whenever either
operand was inexact, which makes the enclosure reach zero and the loop
escalate. At the contract's own working precisions the operands of the
subtraction that can do this are exact, so nothing had ever reached it;
running the evaluator below its design precision did, in the form of
`pow(1 + 2^-112, 1 + 2^-112)` returning exactly 1.

### Division and square root inside the evaluator

Schoolbook, not Newton, and for the same reason: `floor` with a
remainder is exact to within one unit in the last place BY
CONSTRUCTION, where a Newton iteration's accuracy has to be argued or
measured. `bigint.h` deliberately carries no division; the evaluator
needs one per logarithm, and W iterations of shift-compare-subtract
cost about the same as sixty multiplies.

### The algorithms

**exp(t)**, for any t the screens let through: `t = k ln2 + s` with k
an integer and |s| <= ln2. `k` need not be the nearest integer - an
off-by-one only widens |s|, which the series still carries - so a
truncated estimate is enough. Then s is halved five times, the Taylor
series is summed until a term falls below the working precision, and
the result is squared five times and scaled by 2^k. With |s/32| <=
0.022 the series needs about W/6.5 terms; each squaring at most doubles
the accumulated relative error, which is the five bits of guard budget
it costs.

**expm1(t)** uses the same halvings and the doubling identity
`expm1(2u) = expm1(u)·(expm1(u) + 2)`, NOT `exp(t) - 1`. For a negative
argument expm1(u) lies in (-1, 0) and expm1(u)+2 in (1, 2), so the
product never cancels, where `exp(t) - 1` would lose every bit the
answer has. Arguments of magnitude at least 1/2 take the general exp
path and subtract, which costs at most two bits.

**log(x)** for an exactly known x: write x = m'·2^E with m' in
[1/sqrt2, sqrt2), so that |log m'| <= ln2/2 and E·ln2 cannot cancel it
by more than one bit. The reduction to [1, 2) is the one that fails: an
x just below 1 would then be `-ln2 + (ln2 - eps)` and lose every bit of
the answer. Then `log m' = 2·atanh((m'-1)/(m'+1))`, and both the
subtraction and the addition are on EXACT operands, so the cancellation
in `m'-1` amplifies an error of zero and costs nothing. |z| <= 0.1716,
so the series needs about W/5.1 terms.

**log1p(u)** in three regimes, and the boundaries are where `1 + u`
stops being exactly representable at the working precision:

- |u| <= 1/4: `z = u/(u+2)` directly. `1 + u` is NEVER formed, which is
  the whole point - for u = 2^-1074 it would round to 1 and take the
  answer with it.
- |u| <= 2^(p+30): `1 + u` is exact at W >= 2p+40 bits, so the ordinary
  logarithm applies.
- larger: `log1p(u) = log(u) + log1p(1/u)`, with 1/u tiny and positive,
  so the first regime finishes it and neither term can cancel the
  other.

**exp2(t)**: `t = k + s` with k the integer part and s the fraction,
both EXACT on the encoding - no constant is consumed by this reduction,
unlike exp's - and then `2^t = 2^k · exp(s ln2)`.

**log2, log10**: the natural logarithm multiplied by a generated
constant. **pow**: `exp(y · log|x|)`, with the sign taken from the
parity of an integer exponent. **hypot**: `sqrt(x^2 + y^2)` with one
integer square root; no cancellation is possible, so the relative
error simply carries.

### Working precisions

| format | first attempt (2p+40) | cap (min(8p+128, 832)) | schedule |
|---|---|---|---|
| fp32 | 88 | 320 | 88, 176, 320 |
| fp64 | 146 | 552 | 146, 292, 552 |
| fp128 | 266 | 832 | 266, 532, 832 |
| fp256 | 514 | 832 | 514, 832 |

Internally each evaluation runs at W + 32 + h bits, where h is the
headroom the argument reduction needs: k in `t = k ln2 + s`, or the
binade exponent E in `log`, is bounded by emax + man_w, and the
constant it multiplies must be that many bits sharper. h is 8, 11, 15
and 19 for the four formats.

**Where 832 comes from.** The bigint container is 2048 bits.
`cft_mp_mul` forms the full 2W-bit product and `cft_mp_div` shifts the
numerator left by W before dividing, so 2·(W + 32 + h) must fit with
room to spare: 2·883 = 1766 at fp256, against 2048. 832 is the largest
round cap that leaves that margin, and it is written down in exactly
two places - `CFT_TR_PREC_CAP_CEILING` in `host/src/transcend.h` and
`PREC_CAP_CEILING` in the model - because both implementations have to
give up in the same place or they disagree about which inputs are
answerable.

**Why the cap cannot be reached by a non-exact case.** Reaching it at
fp256 would need the true value to agree with a rounding boundary for
832 - 237 = 595 bits past the rounding position. Over the whole
two-operand input space of 2^512 pairs, the expected number of inputs
that come within 2^-595 of a boundary is 2^(512-595) = 2^-83. At fp128
the same arithmetic gives 2^(256-719) and at fp64 2^(128-499). Those
are heuristic counting arguments, and they are stated as such - the
Table Maker's Dilemma has no proof for these functions at these
precisions - but they are the reason the cap is where it is rather than
somewhere it could plausibly be hit.

The structured families are the ones worth checking by hand rather than
by counting, and one of them does escalate. `pow(1+u, -(1+u))` is
`1 - u + u^3/2`: the u^2 term cancels for that exponent and no other,
so the value sits three precisions from the representable `1-u` and the
first attempt cannot see the gap. No representable y can cancel the
u^3 term as well - it would need a u^2 correction, which is 2p bits
below 1 and does not fit - so 3p bits is the family's floor, and
3·237 = 711 sits comfortably under 832.

**Reaching the cap is loud.** The model raises `ZivEscalation`; the C
returns `CFT_ERR_INTERNAL` and writes nothing useful. Neither returns a
number.

## The constants

ln2, log2e, ln10 and log10e, at 1088 bits each, in
`host/src/mp_consts.h`. They are DERIVED, never transcribed - a
hand-typed constant has been wrong in this project three times, and a
wrong one here would not crash, it would return a plausible number with
a silently wrong low bit. So there are three independent checks:

- `host/tools/gen_mp_consts.py --check` regenerates the header from
  mpmath and compares it byte for byte.
- `python/tests/test_mp_consts.py` runs that on every test run AND
  re-derives each constant from the committed limbs, checking that the
  stored value is the true one truncated toward zero and never above
  it.
- `cft_mp_consts_selfcheck()` multiplies ln2 by log2e and ln10 by
  log10e at runtime and requires both products to be 1 to within a few
  units in the last place, so a corrupted or truncated header fails at
  the point of use rather than in the low bit of somebody's
  exponential.

1088 bits is the widest working significand (832) plus 32 bits of guard
plus 19 bits of argument-reduction headroom, rounded up to a whole
number of limbs with margin.

## The reference's own arbiter, and its one correction

The model's enclosure comes from mpmath's interval context, which is
documented as rigorous and is not, quite. Measured on 2026-09-02, at
514 bits:

    iv.power(1 + 2^-236, -(1 + 2^-236))

returns the DEGENERATE interval [g, g] at g = 1 - 2^-236, while the
true value is g + 2^-709 - so the "enclosure" excludes the value it is
supposed to contain, by rather less than one unit in the last place.
Both `iv.power` and `iv.exp(y*iv.log(x))` do it, so it is the
underlying directed rounding of `mpf_exp`/`mpf_log` rather than the
interval layer. Left alone it costs the last bit of that `pow` under
roundTowardPositive.

Every endpoint is therefore moved outward by 256 units of the working
precision before it is believed - about a hundredfold mpmath's own
accuracy claim for these functions, and eight bits out of the forty the
schedule carries as guard. It cannot cost correctness, because a
too-wide enclosure escalates where a too-narrow one lies.

Worth noting which implementation was right: the C, whose error bound
is derived and checked rather than inherited, had the correct answer
throughout. That is the argument for having two.

## Flags

Everything comes from `round_pack`, the library's single rounding
authority, so tininess (after rounding), the overflow response table
per attribute, and the underflow rule (tiny AND inexact) are the same
code the arithmetic uses.

- **inexact** on every result except the exact cases, which are decided
  by exact arithmetic rather than by a tolerance. An "exact" decided by
  comparing against a rounded reconstruction is a tolerance wearing a
  proof's clothes.
- **overflow/underflow** per clause 7, including the delivered value:
  maxfinite rather than infinity under roundTowardZero and on the wrong
  side of the two directed attributes.
- **divideByZero** for log(±0), log1p(-1), and pow of a zero base to a
  FINITE negative exponent. `pow(±0, -inf)` is the |x| < 1 row of the
  table: +infinity, signalling NOTHING, because the divideByZero is the
  pole at a finite exponent rather than the limit.
- **invalid** for a negative operand to log, an operand below -1 to
  log1p, a negative finite base with a non-integer exponent, and any
  signaling NaN.

### The one stated deviation

754-2019 9.2.1 says `pow(x, ±0)` is 1 "for any x (even a zero, quiet
NaN, or infinity)" and `pow(+1, y)` is 1 "for any y (even a quiet
NaN)", and `hypot` of an infinity is +infinity "even if the other
operand is a NaN". The standard's word there is QUIET. A signaling NaN
operand is therefore not covered by those rows, and this contract does
what it does everywhere else: raises invalid and delivers the canonical
quiet NaN. That differs from C's `pow(sNaN, 0)`, and the difference is
deliberate and written down rather than accidental.

## What is proven and what is measured

**Proven** - by argument, in this document and in the source:

- the exact-case enumerations are complete (the transcendence and
  unique-factorisation results, and the p+1-bit odd-part bound for pow
  and hypot);
- the neighbour rules' thresholds;
- the error bounds of every evaluator operation, each an upper bound;
- that the enclosure decision is sound, from the monotonicity of
  rounding, tininess and overflow in the value;
- that the loop terminates for every input the exact cases do not
  catch.

**Measured** - the numbers below are from runs, not from memory. The
Table Maker's Dilemma is the honest gap: there is no proof that no
input requires more than the cap, at fp128 or fp256 or anywhere else.
What there is, is a counting argument that puts the expected number at
2^-83 across the whole fp256 pow input space, a hand analysis of the
one structured family that does escalate, and a loud refusal if either
is wrong.

## What was actually run

Windows 11, mingw64 gcc 16.1, MPFR 4.2.1, CPython 3.12, 2026-09-02.

| check | count | result |
|---|---|---|
| `python/tests/test_transcend.py` | 389 tests | pass |
| `python/tests/test_mp_consts.py` | 3 tests | pass |
| `host/tests/transcend_check.py`, C vs the model | 77,315 comparisons | C == model on every one, bits and flags |
| the same, with the library forced to start below the precision it needs | 77,315 comparisons | identical results through the escalation path |
| MPFR parity, the nine functions | 95,680 cases (4 formats x 5 attributes) | zero value mismatches, zero flag mismatches |
| `cft_conformance` replay, transcendental sets | 64,325 cases in 20 sets | every case, bits and flags |
| `cft.hpp` vs `cft.h` | 3,267 checks at C++17 and C++20 | identical bits and flags |
| the cftmpfr drop-in vs gmpy2 | 268 tests | bit-for-bit at every precision and attribute MPFR has |

Escalation, measured over the MPFR campaign's 95,680 elements: 15,350
reached the Ziv loop at all, and it escalated **zero** times - every
one of them was decided at the first attempt. Over
`transcend_check.py`'s pools, which include the `pow(1+u, -(1+u))`
family on purpose, the model escalated 36 times and the deepest working
precision any input needed was 832 bits, the fp256 cap itself, for that
family. The rest were decided at 2p+40.

Because a path never taken is a path never tested, both implementations
carry a test-only knob that lowers the FIRST attempt's precision -
`CFT_TRANSCEND_MINPREC` in the C, `START_PREC_OVERRIDE` in the model -
and the `transcend` stage of `verify/run.sh` runs the whole sweep twice,
once normally and once with the C forced to start at 64 bits against an
UNESCALATED model. That second run drives 6,542 escalations through the
MPFR campaign, and it is what found the exact-cancellation hole in the
error bound described above. The knob cannot change a result: a
rounding the enclosure decides at some precision is decided the same
way at every higher one, because raising the precision only narrows the
enclosure - and the run proves it, over 77,315 comparisons.

## What is not here

- **Tile assistance.** Every one of these is host work today. A
  narrow-format fast path on the tile's FMA is a phase-2 optimisation
  and would have to reproduce these bits exactly.
- **The rest of clause 9.** sin, cos, tan and the inverse trigonometric
  and hyperbolic functions need one thing this set did not: an
  argument reduction against pi, which is a different and harder
  problem (the worst-case cancellation is famously deep, and the
  reduction constant has to be carried to hundreds of thousands of bits
  at fp256). The evaluator here is the right foundation for them - the
  error model, the enclosure decision, the escalation and the exactness
  discipline all carry over unchanged - but the reduction is its own
  design.
- **A performance claim.** None is made. These calls are hundreds of
  multiprecision operations each; `docs/BENCHMARKS.md` has no row for
  them because none has been measured.
