# The transcendentals, correctly rounded

**Phase 1** (ABI 0.3, 2026-09-02) is exp, expm1, exp2, log, log1p,
log2, log10, pow and hypot; **phase 2** (ABI 0.4, 2026-09-03) is
sinPi, cosPi, tanPi, asin, acos, atan, atan2, asinPi, acosPi, atanPi
and atan2Pi; **phase 3** (ABI 0.5, 2026-09-03) is sin, cos and tan of a
radian argument and the six hyperbolics; and the last section, **table
9.1 completed** (part of the 0.6 step, 2026-09-03), is the remaining
ten - exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt, pown, powr,
compound and rootn. Each has its own section, in that order, below.

exp, expm1, exp2, log, log1p, log2, log10, pow and hypot - phase 1 of
the transcendental set, landed 2026-09-02 as ABI 0.3. This is the
design, the proofs it rests on, and the measurements that were actually
taken.

*Note of 2026-10-21. Everything below is about libcft's host operations
(`cft_exp` and the rest), which the math library's M1 build left as they
were. Since that build (2026-10-13 to 2026-10-19) six of these
functions - exp, expm1, exp2, log, log1p and log2 - also run on the
tile, as routines the language compiles; the last section, "The six on
the tile", says what that is. A passage below that calls a
tile-assisted path a plausible later optimisation is as written on its
date, 2026-09-02 or 09-03.*

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

*Note of 2026-10-21. For six of these functions that tile path now
exists, built differently from how this section pictured it. M1's build
(2026-10-13 to 2026-10-19) made exp, expm1, exp2, log, log1p and log2
into routines of the tile's own instructions, which the language's
compiler writes into a program. A routine marks the lane it cannot
decide (bit 7 of the lane byte, STATUS[6]) and the definition replays
it, so the multiprecision evaluator decides only the cases the routine
cannot, as this section guessed the host would. The argument above
stands, and so do the host operations: `cft_exp` and the rest of the
thirty-nine still issue no `cft_run` pass. The last section, "The six on
the tile", has the details and the record.*

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

`err` counts units of 2^-W of RELATIVE error, W being the value's own
width (the bit length of its significand):

    |true - value| <= err * 2^-W * |value|

Relative rather than an ulp count, because relative error is ADDITIVE
through a multiplication where an ulp count is not: a significand just
above 2^(W-1) has ulps twice as coarse, relatively, as one just below
2^W, so an ulp-based bound has to be doubled at every multiply to stay
safe, and 2^170 over a series is not a bound but a surrender.

The count has no ceiling. It is a whole number of units carried with
its own exponent, c·2^k: exact below 2^63, and past that rounded UP to
63 significant bits, so a bound of any size is carried exactly or
rounded up and is never replaced by a smaller one. The one value above
every finite count is infinity - a bound, and one that cannot decide -
and it never displaces a bound that could. Two rules make it on
purpose. A divisor whose relative error passes 1/2 gives a bound of 1
or more. A logarithm's argument known only within a factor of two gives
a logarithm known only within ln 2, absolutely: not always a relative
error of 1 (log 2^100 would still be known to about 1%), but always
more than 2^-19, since no argument the evaluator forms has a logarithm
of 2^18 or more, and that logarithm is asinh's, acosh's or atanh's
result itself, rounded to 24 bits or more. A count can also grow to
infinity, since a multiply of two counts past 2^W multiplies them; but
a count of 2^W or more is already a relative error of 1, which decides
nothing (`host/src/mpfloat.c`'s header has the rest).

The rules, each an upper bound at every size of count and every
working precision, and each rounded up. `trunc(X)` is `X + 2 +
ceil(X·2^(1-W))`: truncating to W bits a value that already carries X
costs the truncation's two units and their cross term with X.

| step | bound |
|---|---|
| truncation to W bits | trunc(X) (one ulp is at most 2·2^-W relatively) |
| multiply | X = Ea + Eb + max(1, ceil(Ea·Eb·2^-W)), then trunc(X) |
| divide | X = Ea + Eb + max(1, ceil(2(Ea+Eb)·Eb·2^-W)) while Eb is below 2^(W-1), infinity past it; then trunc(X) |
| multiply or divide by a small integer | trunc(Ea) |
| add, like signs | trunc(Ea + Eb) (\|a+b\| >= max(\|a\|,\|b\|)) |
| add, unlike signs | (Ea << (la-lr+1)) + (Eb << (lb-lr+1)), a scale-down rounded up to a whole unit; then trunc() if the difference is wider than W bits |
| add, b wholly below a's last place | Ea + max(2, b's magnitude and b's own error, relative to a) |
| square root | ceil(Ea/2) + ceil(Ea²·2^-(W+1)) while Ea is below 2^W, Ea past it; then trunc() if the root is inexact |
| scale by a power of two | exact |

`host/src/mpfloat.c`'s header derives each row, and
`host/tests/mp_err_check.c` holds every row to its claim exactly, in
GMP: every significand pair, alignment and sign pair at W = 6 against
fourteen counts from zero past 2^W to infinity, and a fixed-seed sample
to 928 bits. Against MPFR it also holds two claims outside the table:
the count each stored constant carries, at every W from 2 to 1087 (1088
and above is refused: nothing is truncated there, and the count would be
short for ln10), and
the logarithm's conversion of an argument's error into its own
(`mp_log_of_mp`, phase 3's "Two reductions, two derivations"). The
runner's `mpfr` stage runs it.

The unlike-signs row is where a subtraction that loses k bits costs k
bits of the error budget, and it is the term the algorithms below are
shaped to keep small.

**The bound is checked, not trusted.** `cft_mp_round` rounds both ends
of `[m - err, m + err] * 2^exp` and accepts only if they agree. A bound
that is too generous costs an escalation; it cannot cost a wrong
answer. The only bound that could is one that is too SMALL, which is
why every rule is an upper bound at every size and rounds up, and why
the count has no ceiling.

Until 2026-09-30 it had one. The count saturated at 2^40, and a
saturated count was a clamp that still decided: 17,816 of the 298,133
final roundings over `transcend_check.py`'s sweep, every result equal
to the model's. A clamp that a later operation scaled back down looked
like an ordinary count, and was not a bound either. The count that
replaced it is at least the old one at every step, so it decides no
rounding the old one did not decide at the same attempt, with one
exception: where an end of the OLD enclosure lay exactly on the
format's grid, the old flags disagreed and the old loop escalated, and
the new count may decide there - correctly, since its enclosure holds
the true value (`host/src/mpfloat.c`'s header; verifier-W5 found 135
among 2,219,337 decisions on chains run through both libraries side by
side, and over the sweep no call took fewer attempts than before).
What it changes is which attempt decides, never a result wherever the
old one was right. Over the
whole sweep at the contract's precision (amd-arc-box, 2026-09-30) the
escalations rose from 84 to 805: 703 calls took more attempts and none
fewer, the C time rose 2%, and no result changed; no infinite count
arose, and the closest decision had 58 bits of room. Over the fp256
sweep alone (the desktop, the same day) it took 353 of 137,814 calls
one attempt further, from 514 bits to the cap at 832. Every one was
pow, powr, pown or compound, and each of the 351 examined one by one
had a base - x, or 1 + x for compound - one unit in its last place from
a small integer, a simple fraction or a power of two. By the binomial
theorem such a result lies within about 2^-2p of a representable
number, and the old count had decided every one of them on its clamp;
there the closest decision had 69 bits of room.

One consequence took a deliberate experiment to find. When two
approximations cancel EXACTLY, the difference is not provably zero -
and an exact zero is the one value that destroys the bound rather than
widening it, because zero has no relative error to carry. `cft_mp_add`
therefore returns a FAILURE whenever either operand was inexact, and
the Ziv loop escalates, as it does on any failure below the cap. (The
first repair returned a saturated bound instead, which does not reach
zero: "What phase 2 changed in phase 1's machinery" below.) At the
contract's own working precisions the operands of the subtraction that
can do this are exact, so nothing had ever reached it; running the
evaluator below its design precision did, in the form of
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
one structured family phase 1 saw escalate (2026-09-02; "The error
model" above has the ones that escalate since), and a loud refusal if
either is wrong.

## What was actually run

Windows 11, mingw64 gcc 16.1, MPFR 4.2.1, CPython 3.12, 2026-09-02.

| check | count | result |
|---|---|---|
| `python/tests/test_transcend.py` | 389 tests | pass |
| `python/tests/test_mp_consts.py` | 3 tests | pass |
| `host/tests/transcend_check.py`, C vs the model | 77,315 comparisons | C == model on every one, bits and flags |
| the same, with the library forced to start below the precision it needs | 72,275 comparisons | identical results through the escalation path |
| MPFR parity, the nine functions | 95,680 cases (4 formats x 5 attributes) | zero value mismatches, zero flag mismatches |
| `cft_conformance` replay, transcendental sets | 64,325 cases in 20 sets | every case, bits and flags |
| `cft.hpp` vs `cft.h` | 3,267 checks at C++17 and C++20 | identical bits and flags |
| the cftmpfr drop-in vs gmpy2 | 268 tests | bit-for-bit at every precision and attribute MPFR has |

Escalation, measured over the MPFR campaign's 95,680 elements: 15,350
reached the Ziv loop at all, and it escalated **zero** times - every
one of them was decided at the first attempt.

*Corrected 2026-09-03.* That 15,350 was measured through a pool whose
directed operands were being silently discarded - see the phase-2
section's account of the inverted success test in `build_tpool`. The
case COUNT above is unaffected (the pool was topped up with randoms to
the same size), but the operands were not the ones intended, and the
figures for the loop are therefore a measurement of a weaker campaign
than the text implies. The phase-2 entry carries the numbers from the
repaired pool, over all twenty functions. Over
`transcend_check.py`'s pools, which include the `pow(1+u, -(1+u))`
family on purpose, the model escalated 36 times and the deepest working
precision any input needed was 832 bits, the fp256 cap itself, for that
family. The rest were decided at 2p+40.

Because a path never taken is a path never tested, both implementations
carry a test-only knob that lowers the FIRST attempt's precision -
`CFT_TRANSCEND_MINPREC` in the C, `START_PREC_OVERRIDE` in the model -
and the `transcend` stage of `verify/run.sh` runs the sweep twice,
once normally and once with the C forced to start at 64 bits against an
UNESCALATED model. That second run drove 6,542 escalations through
`transcend_check.py`'s pools over 72,275 comparisons on 2026-09-02, and
150,218 over 580,977 on 2026-09-30, with the error count that has no
ceiling (amd-arc-box, an instrumented library); it is what found the
exact-cancellation hole in the error bound described above. The knob
cannot change a result: a rounding the enclosure decides at some
precision is decided the same way at every higher one, because raising
the precision only narrows the enclosure - and the run proves it, over
every comparison it makes against a reference that did not escalate.

## What was not here on 2026-09-02

*Status 2026-09-04: everything below except tile assistance and a
performance claim has since landed - phases 2 and 3 and the rest of
table 9.1 follow in this file, and docs/COMPLIANCE.md is the statement.
The section stays as written because the prediction it makes was tested
by what came after.*

- **Tile assistance.** Every one of these is host work today. A
  narrow-format fast path on the tile's FMA is a phase-2 optimisation
  and would have to reproduce these bits exactly.

  *Status 2026-10-21: built for six of them, as routines of the
  language and at all four formats, not as a narrow-format fast path
  behind the host calls (the last section). The bullet stays as written
  on 2026-09-02, and still holds of the thirty-nine host entry points.*
- **The rest of clause 9.** sin, cos, tan and the inverse trigonometric
  and hyperbolic functions need one thing this set did not: an
  argument reduction against pi, which is a different and harder
  problem (the worst-case cancellation is famously deep, and the
  reduction constant has to be carried to hundreds of thousands of bits
  at fp256). The evaluator here is the right foundation for them - the
  error model, the enclosure decision, the escalation and the exactness
  discipline all carry over unchanged - but the reduction is its own
  design.

  *Written 2026-09-02, and half-answered the next day.* Phase 2 below
  is the part of that set which needs NO reduction against pi - the
  Pi-variants, whose reduction is x mod 2 on a dyadic operand, and the
  inverse functions, which have nothing to reduce. It landed
  2026-09-03 as ABI 0.4 and reused every piece of the machinery named
  above. What is still not here is `sin`, `cos` and `tan` of a radian
  argument, which is the reduction problem itself.
- **A performance claim.** None is made. These calls are hundreds of
  multiprecision operations each; `docs/BENCHMARKS.md` has no row for
  them because none has been measured.

---

# Phase 2: the trigonometry that needs no reduction against pi

sinPi, cosPi, tanPi, asin, acos, atan, atan2, asinPi, acosPi, atanPi
and atan2Pi - landed 2026-09-03 as ABI 0.4. Same promise, same
evaluator, same three-way split, same loud refusal.

The section above ends by saying that the rest of clause 9 needs one
thing phase 1 did not: an argument reduction against pi, carried to
hundreds of thousands of bits at fp256. **These eleven are exactly the
functions that do not need it**, and that is the whole reason they are
a phase of their own rather than part of the next one.

- For the Pi-variants of the forward functions the reduction is
  `x mod 2`, and every operand is a DYADIC RATIONAL, so the reduction
  is a mask on the encoding and is exact at every magnitude.
  `sinPi(2^262000)` is `+0` decided by integer arithmetic; `sin` of the
  same argument would need pi to a quarter of a million bits before the
  first series term could be written down.
- The inverse functions take an argument in [-1, 1], or a ratio, so
  there is nothing to reduce at all. pi enters only as a factor of the
  ANSWER, at one multiplication's worth of precision.

`sin`, `cos` and `tan` of a radian argument were not here yet. That is
phase 3 (ABI 0.5, the same day, below), and it is the reduction problem
rather than this one.

## The exact cases, proved complete

Phase 1's enumerations rest on Lindemann-Weierstrass and on unique
factorisation. Phase 2's rest on two more theorems, and between them
they make every table below finite and closed.

**Niven's theorem** bounds the forward set. If r is rational and
sin(pi r) is rational, then sin(pi r) is 0, +-1/2 or +-1; the tangent
form says tan(pi r) is rational only when it is 0 or +-1. Every operand
here is a dyadic rational, so r is rational and the theorem applies -
and the +-1/2 case needs r = 1/6 + n and its friends, which is never
dyadic. So:

| function | exact exactly at | value |
|---|---|---|
| sinPi | the half-integers | `sinPi(n)` is a zero with the SIGN OF THE ARGUMENT; `sinPi(M/2)` for odd M is +1 when M = 1 (mod 4) and -1 when M = 3 (mod 4), times the argument's sign |
| cosPi | the half-integers | `cosPi(n)` is `(-1)^n`; `cosPi(n + 1/2)` is `+0`, for every n and both signs of the argument |
| tanPi | the quarter-integers | `tanPi(n)` is a zero whose sign is the argument's XOR the parity of n; `tanPi(M/4)` for odd M is +-1 by the same M mod 4 rule. The half-integers are a POLE, not a value |

Everything else on the line is irrational, hence not a dyadic rational,
hence not a rounding boundary, hence decided by the enclosure in finite
time. That is a proof and not an observation.

**Hermite-Lindemann** bounds the inverse set, and bounds it hard. If
theta is a nonzero algebraic number then `e^(i theta)` is
transcendental; but `sin theta = x` with x algebraic makes
`z = e^(i theta)` a root of `z^2 - 2ix z - 1`, hence algebraic. So asin
of a nonzero dyadic rational is 0 or transcendental, and the same
argument runs for cos and tan. Therefore:

| function | exact exactly at | value |
|---|---|---|
| asin | +-0 | +-0 |
| atan | +-0 | +-0 |
| acos | 1 | +0 |
| atan2 | y = +-0 with x > 0 | +-0 |

and nowhere else. `asin(1)` is pi/2 and INEXACT; `acos(-1)` is pi and
inexact; `atan2(+-0, -0)` is +-pi and inexact. Every other row of
9.2.1's atan2 table is an irrational multiple of pi.

**Niven again, for the Pi-variants of the inverses**, and here the
table is much larger, because dividing by pi turns those multiples into
dyadic rationals. `asinPi(x) = r` means `x = sin(pi r)`; r dyadic and x
rational force `sin(pi r)` into {0, +-1/2, +-1}, and of the r that
produce those only 0 and +-1/2 are themselves dyadic:

| function | exact at | value |
|---|---|---|
| asinPi | +-0, +-1 | +-0, +-1/2 |
| acosPi | 1, +-0, -1 | +0, 1/2, 1 |
| atanPi | +-0, +-1, +-inf | +-0, +-1/4, +-1/2 |
| atan2Pi | every axis and every diagonal | 0, +-1/4, +-1/2, +-3/4, +-1 |

`atan2Pi`'s diagonals are the rows `|y| == |x|`, which is an exact
comparison on the encoding: +-1/4 for a positive x and +-3/4 for a
negative one. Its axes are the zero and infinity rows. And the
completeness argument is the tangent form of Niven: a dyadic multiple
of pi has a rational tangent only at 0, +-1 and the pole, so `y/x` must
be 0, +-1 or undefined, which is exactly the axes and the diagonals.

**One case worth stating because it is not exact**: `asinPi(1/2)` is
exactly 1/6. That is RATIONAL - Niven's theorem produces it - and it is
NOT a dyadic rational, so it is not a rounding boundary, so it is
inexact and the enclosure decides it in finite time like any other
irrational. The distinction between "rational" and "dyadic rational" is
the whole of why the enumeration stops where it does, and `acosPi(1/2)
= 1/3` is the same story.

## The neighbour rules, and where each threshold comes from

Six families, each derived the way phase 1 derives its four: bound the
distance from the representable value, compare against a quarter of the
grid step there, and reduce to an integer condition on the argument's
exponent e.

| family | the true value | threshold |
|---|---|---|
| `asin(x)` | strictly ABOVE x: `asin(x) - x = x^3/6 + 3x^5/40 + ... > 0`, and at most `0.2\|x\|^3` for \|x\| <= 1/4 | `2e + p + 2 <= 0` |
| `atan(x)` | strictly BELOW x: `atan(x) - x = -x^3/3 + x^5/5 - ...`, alternating and decreasing, so at most `\|x\|^3/3` | `2e + p + 3 <= 0` |
| `cosPi`, and `sinPi` next to a half-integer | strictly below 1: `1 - cos(u) <= u^2/2` with `u = pi\|s\|`, so below `4.94 s^2` | `2v + p + 6 <= 0`, v the reduced argument's exponent |
| `acosPi(x)` | beside 1/2, below for a positive x and above for a negative one: `\|acosPi(x) - 1/2\| = \|asin(x)\|/pi <= 0.33\|x\|` | `e <= -(p+2)` |
| `atanPi(x)` for a huge x | below 1/2 by `atan(1/\|x\|)/pi <= 1/(pi\|x\|)` | `e >= p + 1` |
| `atan2Pi` beside 1 and 1/2 | below 1 for a tiny quotient against a negative x; beside 1/2 for a dominant y | `ey - ex <= -(p+1)`, `ex - ey <= -(p+2)` |
| `atan2(y, x>0)` beside an exact quotient | below `y/x`, by the atan rule applied to the quotient | `2 q + p + 3 <= 0` on the quotient's exponent |

Each derivation is the same shape. For asin: `0.2 < 2^-2.32` and
`|x|^3 < 2^(3e+3)`, so the excess is below `2^(3e+0.68)`; the grid step
at that magnitude is at least `2^(e-p+1)` and a quarter of it is
`2^(e-p-1)`; `3e + 0.68 < e - p - 1` reduces to `2e < -p - 1.68`, and
`2e + p + 2 <= 0` is the integer condition that implies it. For atan the
constant is `1/3 < 2^-1.58` and the same algebra gives `2e + p + 3 <= 0`.
For cosPi, `4.94 < 2^2.31` and `s^2 < 2^(2v+2)` give `2v + 4.31 < -p-1`,
hence `2v + p + 6 <= 0`.

**Which functions have no rule, and why that is the interesting half.**
`asinPi` and `atanPi` of a tiny argument are about `x/pi`, which is not
next to anything the format holds - the ordinary enclosure resolves
them, and the answer is NOT x. `acos` near 1 behaves like
`sqrt(2(1-x))`, which is nowhere near a representable neighbour of
anything. `asin` and `atan2` near their pi/2 and pi corners sit beside
numbers the format does not hold, so nothing has to be decided by a
side there. A neighbour rule applied where it is not needed would be a
wrong answer waiting to happen; the six above are the six that are.

**The witness needed generalising.** Phase 1's `round_neighbour` starts
from a representable ENCODING. That is not enough for atan2, whose
anchor is the quotient `y/x` - which is exactly a dyadic rational
whenever x's odd significand divides y's, and which can land on a
subnormal MIDPOINT rather than on the grid. `atan2(minSubnormal, 2)` is
that case: the quotient is `minSub/2`, not a representable number at
all, and a value just below a midpoint rounds differently from the
midpoint itself. `round_side` (C) and `_round_dyadic_side` (the model)
therefore take an exact dyadic `m * 2^e`, derive the grid step 2^g at
that magnitude, and place the witness at `m * 2^e -+ 2^(g-3)` - an
eighth of a step. Every value strictly inside the quarter-step rounds
identically under all five attributes, to V's own rounding when V is a
grid point and to the grid point on the witness's side when V is a
midpoint, so the witness answers for the true value and `round_pack`
derives the flags.

Why the quotient's odd part never needs more than p bits: `|y|/|x| =
(My/Mx) * 2^(Ey-Ex)` with both odd parts, so it is dyadic exactly when
Mx divides My, and the quotient's odd part is then `My/Mx`, no wider
than My. One exact integer division decides it.

## pi, generated and derived twice

`pi` and `1/pi` join ln2, log2e, ln10 and log10e in
`host/src/mp_consts.h`, at 1088 bits, emitted by
`host/tools/gen_mp_consts.py` from mpmath. Nothing is transcribed.

The reciprocal self-check the C already ran per call now covers the new
pair - but `pi * (1/pi) == 1` is a weaker statement than it looks: a
generator that emitted pi/2 and 2/pi would pass it. It says the two
halves agree with each other, not that either is pi. So pi gets an
INDEPENDENT derivation on both sides:

- **In C**, `cft_mp_consts_selfcheck()` re-sums Machin's
  `pi/4 = 4 atan(1/5) - atan(1/239)` at 256 bits, out of small-integer
  arithmetic that touches no stored constant, and requires the stored
  value to match within `2^-(256-32)`. That derivation is cached - it
  is a property of compile-time data, and re-deriving it on every call
  would cost more than the transcendental it guards - while the three
  cheap reciprocal products still run every time, as they always did. A
  failure is sticky: a bad header must not become good on the second
  call.
- **In Python**, `python/tests/test_mp_consts.py` does the same sum in
  exact `Fraction` arithmetic at the header's full 1088 bits, with no
  mpmath in it at all, and requires the committed limbs to be the true
  value truncated toward zero.

Two constants, not four: `pi/2` and `pi/4` are exact shifts of pi, and
`2/pi` an exact shift of `1/pi`.

**No argument-reduction headroom is consumed.** In phase 1, `k` in
`t = k ln2 + s` is bounded by `emax + man_w`, and ln2 has to be that
many bits sharper. Phase 2's reduction produces `|s| <= 1/4` by masking,
and pi multiplies it once; there is no large multiplier anywhere, which
is the same fact as "no reduction against pi", stated in bits.

## The algorithms, with their error bounds

**sinPi, cosPi, tanPi.** Reduce `|x| mod 2` to `k/2 + s` with `k` in
0..4 and `|s| <= 1/4`, exactly, by masking the encoding. `S == 0`
exactly when |x| is a half-integer, which is where every exact case of
the family lives, so the enclosure path never sees one. Then

    |sin(pi t)| = sin(pi|s|) when k is even, cos(pi|s|) when it is odd
    |cos(pi t)| = the other way round
    |tan(pi t)| = the quotient

and the SIGNS come off the quadrant exactly - `k mod 4` and the sign of
S - because no evaluation decides the sign of a value it is about to
round. `mp_sincos` sums both series at once: `term_n = v^n/n!` with
`n mod 4` selecting one of four accumulators, so the sine and the
cosine are each a difference of two like-signs sums.

**asin, acos, atan, atan2** all reduce to one routine, `mp_atan_pos`.
It reciprocates above 2 - `atan(t) = pi/2 - atan(1/t)`, where
`1/t <= 1/2` puts `atan(1/t)` below 0.464 and the difference above 1.1,
so the subtraction loses no bits - and otherwise applies three exact
halvings, `atan(u) = 2 atan(u/(1 + sqrt(1+u^2)))`, which take the
largest argument it ever sees down to 0.1421, and then the series.
Three halvings cost three square roots and three divisions and no
cancellation at all: `1 + u^2` and `1 + sqrt` are both like-signs adds.

    asin(x)  = atan(|x| / r)          r = sqrt((1-|x|)(1+|x|))
    acos(x)  = atan(r / |x|)          for a positive x
             = pi - atan(r / |x|)     for a negative one
    atan(x)  = atan(|x|)
    atan2    = atan(|y|/|x|), or pi - that when x < 0

The product form `(1-|x|)(1+|x|)` rather than `1 - x^2` is the same
trick phase 1's `log(m')` uses: for |x| just below 1 the factor
`1 - |x|` is EXACT at the working precision, so the cancellation
amplifies an error of zero and costs nothing, where `1 - x^2` formed
directly would lose every bit the answer has. `acos` uses
`atan(r/|x|)` rather than `pi/2 - asin(x)` for the same reason in the
other direction: for x just below 1 the difference form cancels the
whole answer away, and this one computes a small angle as a small
angle. Where a subtraction remains - `pi - a` for a negative operand,
`pi/2 - a` in the reciprocal branch - the subtrahend is bounded below
pi/2 and below 0.464 respectively, so at most one bit is charged.

**Both series split their terms.** The positive and the negative terms
go into separate accumulators and are subtracted once at the end,
instead of being added alternately into one running sum. That is not
tidiness. `cft_mp_add`'s unlike-signs rule charges a factor of two per
step even when nothing cancels, because the result can be half the
larger operand; over the hundred and thirty terms `mp_atan_series`
needs at the deepest working precision that is 2^65 - sixty-five bits
of the guard spent on nothing, and until 2026-09-30, when the count
saturated at 2^40, a clamp rather than a bound. Split in two it is ONE
doubling in total, and the
accumulators themselves only ever add like signs. The final
subtraction is safe by construction: for sin the positive part is
`v + v^5/120 + ...` and the negative `v^3/6 + ...`, so with
`|v| <= pi/4` the difference keeps more than four fifths of the larger;
for cos it keeps two thirds; for atan, more than nine tenths.

**The Pi-variants of the inverses** multiply by the generated `1/pi`. A
division by pi would do as well and cost sixty times more; the constant
carries its own two units of error and the multiply adds three.

## Special values and flags, all of 9.2.1

Every row below was transcribed from the standard and then CONFIRMED
against MPFR 4.2.2 - the mingw64 build on this host, and the first
release line to carry `mpfr_sinpi`, `mpfr_cospi`, `mpfr_tanpi` and the
Pi-variants of the inverses (they arrived in 4.2.0) - before it was
written down. Where the two could have differed, the probe is quoted.

- `sinPi(+-0) = +-0`. `sinPi` of an INTEGER n is a zero with the sign
  of the ARGUMENT, not with the parity of n: measured,
  `sinpi(1) = +0`, `sinpi(3) = +0`, `sinpi(-1) = -0`. That keeps sinPi
  odd, which is the property the standard does fix; periodicity cannot
  also be honoured in the sign, and is not.
- `sinPi(M/2)` for odd M is `+-1`: `+1` when `M = 1 (mod 4)`, `-1` when
  `M = 3 (mod 4)`, times the argument's sign.
- `cosPi(+-0) = 1`, `cosPi(n) = (-1)^n`, and `cosPi(n + 1/2) = +0` for
  every n and BOTH signs of the argument. cosPi is even, so that zero
  has no sign to carry, and MPFR delivers `+0` throughout.
- **`tanPi` is `sinPi/cosPi` in every respect, signs included.**
  `tanpi(1) = -0` - because `sinPi(1)` is `+0` and `cosPi(1)` is `-1` -
  and `tanpi(2) = +0`, `tanpi(-1) = +0`, `tanpi(-2) = -0`. That is the
  row an implementation reaching for "tanPi is odd, so tanPi(n) has the
  sign of n" gets wrong; both rules hold, and the quotient rule is the
  one that also fixes the parity.
- **tanPi at a half-integer is `+-infinity` with divideByZero raised.**
  Measured: `tanpi(1/2) = +Inf`, `tanpi(3/2) = -Inf`, `tanpi(5/2) =
  +Inf`, `tanpi(-1/2) = -Inf`, all with MPFR's divide-by-zero flag set.
  The sign is sinPi's, since cosPi there is `+0`. 754-2019 7.3 raises
  divideByZero exactly when an operation on finite operands has an
  exact infinite result, which is what a pole is, so the standard's
  general rule and MPFR's behaviour agree and the contract follows
  both.
- `tanPi(M/4)` for odd M is `+-1` by the same `M mod 4` rule.
- **tanPi cannot overflow at any format on this ladder.** A
  representable argument cannot get closer than `2^-p` to a pole - the
  binade [1/2, 1) has that ulp and no binade does better, and every
  value at or above `2^(p-1)` is an integer or a half-integer exactly -
  so `|tanPi| <= 1/(pi 2^-p) < 2^p`, which is far inside emax at all
  four rungs (24 against 127, 53 against 1023, 113 against 16383, 237
  against 262143). Overflow cannot occur anywhere in this set.
- `sinPi`, `cosPi` and `tanPi` of an infinity are **invalid**: there is
  no limit there. MPFR returns NaN and sets its NaN flag.
- `asin`, `acos`, `asinPi` and `acosPi` of an operand with `|x| > 1`
  are invalid, infinities included.
- `atan(+-inf) = +-pi/2`; `atanPi(+-inf) = +-1/2`, and that one is
  EXACT.
- **`atan2(+-0, -0) = +-pi`, and `atan2Pi(+-0, -0) = +-1`.** A minus
  zero denominator names the negative real axis, so the answer is pi
  and not zero. It is the row implementations most often miss, and its
  Pi form is exact where the radian form is an inexact rounding of pi -
  which is, in one line, the reason atan2Pi is a separate function.
  `atan2(+-0, +0) = +-0`; `atan2(y, +-0) = +-pi/2`;
  `atan2(+-inf, +inf) = +-pi/4` and `(+-inf, -inf) = +-3pi/4`.
- A quiet NaN operand does NOT outrank atan2's table the way it
  outranks pow's: `atan2` of a NaN is a NaN.
- A SIGNALING NaN raises invalid and delivers the canonical quiet NaN,
  as everywhere else in this contract.
- **Underflow can occur and comes through `round_pack` like everything
  else.** `sinPi` of a tiny x is about `pi x` and `atanPi` of one is
  about `x/pi`; at the smallest subnormal the first rounds to three
  subnormals and the second to zero (or to one subnormal upward), both
  tiny and inexact. `atan2(minSubnormal, maxFinite)` is about
  `2^-524522` at fp256 and underflows to zero with the same flags.

## What phase 2 changed in phase 1's machinery

Two defects, both pre-existing, both found by building this phase's
gates rather than by reasoning about them.

**`mpfr_check.c`'s transcendental pool had an inverted success test.**
`enc_from_val` returns 1 on success; `build_tpool` tested it against 0.
Every directed operand it meant to add - the exp2 integers, the log2
powers of two, the log10 powers of ten, the neighbours of 1, the
arguments below `2^-(p+3)` - was therefore discarded and a zeroed
encoding kept in its place, and the phase-1 MPFR campaign ran on
`build_pool`'s specials plus randoms. Found because the new
trigonometric pool came out at 42 entries where 192 were asked for.

**The exact-cancellation repair in `cft_mp_add` was unsound.** Phase 1
found that two inexact approximations cancelling to zero destroy the
error bound rather than widening it, and repaired it by returning the
larger operand with a SATURATED bound, on the reasoning that the
enclosure would then reach zero. It did not: `err` then saturated at
2^40 while the significand is `2^(W-1)`, so at any working precision
above 41 bits the enclosure was narrow, decidable and wrong. With the pool
fixed, that showed up as `pow(2 + ulp, ~10^4)` at fp128 overflowing
where the true value is about `2^9888`. The true difference is bounded
only in ABSOLUTE terms, which a relative bound around any value cannot
express, so it is now a FAILURE - and `tr_ziv` escalates on a failure
below the cap rather than refusing, because a failure there means the
precision was too coarse and not that no precision can decide. Only a
failure AT the cap is a refusal. The same change fixes a second
symptom: at 64 bits `log(1 + 2^-112)` comes out as `2 atanh(1/2)`, the
exponential's reduction multiple lands past its own cap, and
`mp_exp_full` used to refuse outright.

Both were invisible to every gate the project had until the pool was
repaired, and both are in code the contract's own working precisions
never reach. That is what the forced-low-precision run is for.

## What was actually run

Windows 11, mingw64 gcc 16.1, MPFR 4.2.2 (mingw64) with gmpy2 2.2.1's
own MPFR 4.2.1 for the Python side, CPython 3.12, 2026-09-03.

| check | count | result |
|---|---|---|
| `python/tests/test_transcend.py` | 567 tests | pass |
| `python/tests/test_mp_consts.py` | 4 tests | pass |
| the whole `python/tests` suite | 941 tests, 1 skipped | pass |
| `host/tests/transcend_check.py`, C vs the model, twenty functions | 154,269 comparisons | C == model on every one, bits and flags |
| the same, forced to start below the precision it needs | 143,069 comparisons | identical through the escalation path |
| MPFR parity, all twenty, four formats, five attributes | 414,008 cases total, of which 175,680 transcendental (95,680 phase 1, 80,000 phase 2) | **zero value mismatches, zero flag mismatches** |
| the same campaign with `CFT_TRANSCEND_MINPREC=64` | 414,008 cases, 38,338 escalations | zero mismatches |
| `cft_conformance` replay | 40 sets, 365,845 cases, of which 129,845 transcendental in 20 sets | every case, twice - per element and as arrays |
| `cft.hpp` vs `cft.h` | 3,751 checks at C++17 and again at C++20 | identical encodings and flags |
| the cftmpfr drop-in | 384 tests | pass, including the four inverse functions bit-for-bit against gmpy2 |
| `api-test` contract checks | all | pass |

**Escalation, measured.** Over the MPFR campaign's 175,680
transcendental elements, 74,755 reached the Ziv loop and it escalated
**zero** times: every one was decided at the first attempt, and the
deepest working precision used was 514 bits - fp256's `2p + 40`. 18,520
elements were decided exactly and 43,155 by a neighbour's side rather
than by any precision at all. **No input reached the cap.** Over
`transcend_check.py`'s pools the model escalated 36 times, all of them
still the phase-1 `pow(1+u, -(1+u))` family, and the deepest precision
any input needed was 832 bits - the fp256 cap itself - for that family.
No phase-2 input escalated at all at the contract's own precisions.

Forced low: `CFT_TRANSCEND_MINPREC=64` drives **38,338 escalations**
through the MPFR campaign and finds the same answers, and
`transcend_check.py --min-prec 64` drives the C's escalation path
against an UNESCALATED model over 143,069 comparisons with identical
results. That is the run that found both defects above.

**Negative control**, run and restored the same day. Inverting one
character - the `away` argument of atan's neighbour witness in
`do_atan_family`, so the true value is claimed to lie above its
argument rather than below - is caught by `api-test` (1 FAILED, at the
new `atan(min subnormal)` toward-zero case), by `transcend_check.py`
(fp32 rtz, the smallest subnormal: `0x1` where the model says `0x0`),
by the conformance replay (which stops at 68,542 cases), by MPFR parity
(from the first fp32 atan rtz row), and by the cftmpfr drop-in against
gmpy2 (12 tests). `cpptest` is deliberately not on that list: it issues
each entry point through `cft.hpp` and through `cft.h` on the same
library, so a library defect moves both sides and it is a marshalling
check by construction.

## What phase 3 inherits

Everything except the reduction. `mp_sincos` computes sin and cos of a
reduced argument in [0, pi/4] and is exactly what `sin(x)` needs once
`x mod (pi/2)` exists; `mp_atan_pos`, `round_side`, the split-series
discipline, the error model, the enclosure decision, the schedule, the
cap and the exactness machinery all carry over unchanged. What phase 3
has to build is the one thing this phase was defined to exclude:
`x mod (pi/2)` for an argument up to `2^262143`, which needs `2/pi` to
about 524,000 bits and a Payne-Hanek-style reduction, plus its own
exactness argument (`sin(x)` for a nonzero dyadic x is transcendental,
so the exact cases are only the zeros - but the WORST CASE of the
reduction is the famously deep part, and it is a measurement rather
than a theorem).

The hyperbolics need neither reduction nor a new constant: `sinh`,
`cosh`, `tanh` and their inverses are `exp` and `log` in different
clothes, with the same cancellation questions phase 1 already answers
(`sinh(x) = expm1(x)(expm1(x)+2)/(2(expm1(x)+1))` for a small x, and
`asinh(x) = log1p(x + x^2/(1 + sqrt(1+x^2)))`), and their exact cases
are the zeros by Lindemann-Weierstrass. They are a smaller job than
either phase so far.

---

# Phase 3: the reduction against pi, and the hyperbolics

sin, cos, tan of a RADIAN argument, and sinh, cosh, tanh, asinh, acosh,
atanh - landed 2026-09-03 as ABI 0.5. Same promise, same evaluator,
same three-way split, same loud refusal. What is new is the one thing
the first two phases were defined to exclude: `x mod (pi/2)` for a
dyadic x of any magnitude the formats hold, up to 2^262143.

## The constant, and why its size is set by the exponent range

The reduction is Payne-Hanek: multiply the operand's integer
significand into a WINDOW of the binary expansion of 2/pi. Write
|x| = m * 2^e with m the p-bit significand. In

    x * (2/pi) = m * sum_j b_j 2^(e-j)          2/pi = 0.b1 b2 b3 ...

every term with e - j >= 2 is m times a multiple of 4, so it changes
neither the quadrant (the integer part mod 4) nor the fraction: the
window may START at bit j0 = max(1, e-1) and everything above it is
dropped EXACTLY. So the window's start is an exponent-range question
and its width a precision question, and the two are separate. The
stored constant has to reach

    (deepest window start) + (widest window) = 261,906 + 8,192 bits

for fp256, whose emax - man_w = 261,907 is the largest exponent an
integer significand can carry on the ladder: 270,336 bits, 8,448
words, 33 KiB of const data in `host/src/mp_2opi.h`, rounded up to a
whole number of limbs. `host/tools/gen_2opi.py` derives that number
rather than adopting phase 2's estimate of half a million, which had
put the width on the wrong side of the sum.

The constant is GENERATED, never transcribed, and derived twice:
`gen_2opi.py` emits it from mpmath; `python/tests/test_mp_consts.py`
regenerates it and compares byte for byte, AND re-derives all 270,336
bits from Chudnovsky's series with binary splitting in plain Python
integers - no mpmath in it, nothing shared - and the two agree to the
last bit. Machin in exact Fractions, which proves the 1088-bit pi, is
hopeless at a quarter of a million bits; Chudnovsky's binary splitting
takes seconds. A third test ties `CFT_TR_PH_WINDOW_MAX` to the
constant's size, so widening the window without regenerating the header
fails rather than reading past the end of the array. At run time
`tr_2opi_ok()` in `host/src/transcend.c` checks two things that prove
different things: the top 512 bits against 2/pi derived from the
independently re-derived pi in `mp_consts.h`, which says the stream
really is 2/pi to the bits that other header carries; and an FNV-1a over
every word, which says the array in the binary is the array the
generator emitted and nothing at all about the deep bits. Only
regeneration proves those, and the test does it on every run.

## The cancellation, and why it is a measurement

Take the low `wbits` of the product, read the quadrant off the two
bits above the binary point, the half bit below it, and the reduced
fraction off the rest - all exact integer arithmetic on the window, so
no rounding decides a sign, which is the discipline phase 2 keeps with
its mask. If |x| sits very close to a multiple of pi/2 that fraction
has leading zeros, and the window must be that many bits wider to
deliver the same working precision. How many is NOT a theorem: the only
proven statement is the irrationality measure of pi, mu < 7.104
(Zeilberger-Zudilin 2020), which permits a reduced argument as small
as 2^-1,600,000 at fp256 - four hundred kilobits of cancellation
against a stored constant of 270,336. The bound is true, useless, and
stated here rather than quietly not mentioned.

So the reduction MEASURES the cancellation from the bits it has,
widens the window by exactly the deficit, and repeats: the dropped
tail of 2/pi is below 2^-(j0+wbits-1), so the absolute error in
|x|*(2/pi) is below 2^-(d-p) with d the fraction's width, and relative
to |t| ~ 2^vt that is 2^-(avail+vt); the loop widens until
avail + vt >= W + 8 for the deepest working precision W the format's
schedule can reach, plus a guard. A window that sees an exact multiple
of pi/2 - which no nonzero dyadic is - means the cancellation is at
least as deep as the window, and there is nothing to widen BY, so it
doubles. Past `CFT_TR_PH_WINDOW_MAX = 8192` bits it returns
`CFT_ERR_INTERNAL`: a window of W bits delivers the reduced argument
to the working precision as long as W >= p + 2 + cancellation + Wi +
10, so 8,192 provides for about 7,000 bits of cancellation at fp256
and 7,478 at fp64. The scratch is a plain limb array rather than a
`cft_bn` on purpose - the 2048-bit container would cap the allowance
at a few hundred bits and make the CONTAINER the thing the contract
refuses on.

**What the cancellation actually is.** `host/tools/pi_worstcase.py`
measures it: a steepest descent on the continued-fraction basis of
frac(2^e * 2/pi) per binade, each basis vector SOLVING for its best
multiple rather than stepping to it (a partial quotient of a million
would otherwise cost a million iterations), from a spread of anchors.
`--validate` compares it against exhaustive search on 200 random
instances and 19 real fp32 binades narrowed to a searchable slice, and
reports no disagreement. Run on this host:

| format | binades searched | deepest cancellation |
|---|---|---|
| fp32 | every one of 128 with \|x\| >= 1 | 29 bits |
| fp64 | every one of 1,024 | 61 bits |
| fp128 | every 16th of 16,384 | 121 bits |
| fp256 | every 512th of 262,144 | 245 bits |

The two published worst cases - 16367173 * 2^72 at binary32 and
0x1.6ac5b262ca1ffp+849 at binary64 - are the minimisers of their own
binades and sit at those depths; other binades tie them, which is what
the counting argument predicts: the minimum over N binades of a p-bit
format is about 2^-(p + 1 + log2 N), so roughly p + 8 bits at fp32
through p + 8 at fp256. fp128 and fp256 are sampled because the
constant is sized by the exponent range rather than by the depth
found, so a full sweep of 262,144 binades would refine a number no
design decision depends on. The reduction's own instrumentation over
the MPFR campaign: 9,855 arguments reduced,
0 window widenings, the widest window
1,184 bits, the deepest cancellation seen 239
bits - against an allowance of 8,192.

## The exact cases, proved

Hermite-Lindemann closes the whole set: if z is a nonzero algebraic
number then e^z is transcendental, and e^(iz) with it. Every operand
is a dyadic rational, hence algebraic, so:

| function | exact exactly at | argument |
|---|---|---|
| sin, tan | +-0, giving +-0 | sin(x) = a algebraic makes e^(ix) a root of z^2 - 2iaz - 1, hence algebraic, so x = 0; tan through sin/cos |
| cos | 0, giving 1 | the same root argument on cos |
| sinh, tanh, asinh, atanh | +-0, giving +-0 | sinh(x) = a makes e^x a root of z^2 - 2az - 1; asinh(x) = y dyadic nonzero would make x = sinh(y) transcendental; atanh likewise through tanh |
| cosh | 0, giving 1 | cosh(x) = a makes e^x a root of z^2 - 2az + 1 |
| acosh | 1, giving +0 | acosh(x) = y dyadic nonzero would make x = cosh(y) transcendental |

`tanh(+-inf) = +-1` is a limit that happens to be representable: a
special-value row rather than an exact case, raising nothing either
way. And there is no half-integer table here the way there is for
sinPi - an odd multiple of pi/2 is irrational, so no representable
argument is a zero of cos or a pole of tan, and tan never signals
divideByZero.

## The neighbour rules, and where each threshold comes from

Seven families, each derived the way phases 1 and 2 derive theirs: the
leading term of the series and its SIGN, against a quarter of the grid
step, reduced to an integer condition on the argument's exponent e.

| family | the true value | threshold |
|---|---|---|
| sin(x), asinh(x) | strictly on the ZERO side of x: -x^3/6 + ... | 2e + p + 2 <= 0 |
| tan(x), atanh(x) | strictly on the far side of x: +x^3/3 + ..., at most 0.357\|x\|^3 for \|x\| <= 1/4 | 2e + p + 3 <= 0 |
| sinh(x) | strictly on the far side: +x^3/6 + ..., at most 0.17\|x\|^3 | 2e + p + 2 <= 0 |
| tanh(x) | strictly on the zero side: -x^3/3 + ... | 2e + p + 3 <= 0 |
| cos(x) | strictly below 1: 1 - cos(x) <= x^2/2, against half the gap below 1, which is 2^-(p+1) | 2e + p + 3 <= 0 |
| cosh(x) | strictly above 1: cosh(x) - 1 <= 0.51x^2, against half the gap ABOVE 1, which is 2^-p - twice the gap below | 2e + p + 2 <= 0 |
| tanh(x) for a large x | inside the half gap below 1: 1 - tanh(x) = 2/(e^2x + 1) < 2e^-2x once x > 0.347(p+2) | 2^e >= p + 2, an integer test on the encoding |
| sin, cos beside 1 | \|sin x\| and \|cos x\| are STRICTLY below 1 for every nonzero dyadic x, so when the enclosure's low end is inside the half gap below 1 the side is the whole answer | on the enclosure, not the operand |

tanh's large-argument rule is deliberately an integer test on the
encoding - `2^e >= p + 2` - rather than the tighter `x > 0.347(p+2)`
the derivation allows, so that both implementations can apply it
without evaluating anything. The price is a band between the two,
where 1 - tanh(x) is below the first attempt's working precision and
the enclosure decides at the second: measured, three arguments per
format from fp64 up in the MPFR campaign, and none at fp32.

The thresholds take a quarter of the step rather than a half because
the step below a power of two is half the step above it: sin's rule
must hold when x is exactly 2^e and the neighbour toward zero is
2^(e-p) away, which is where `2e + p + 2` comes from with the leading
constant 1/6; cos's threshold is one worse than cosh's because 1 is
such a boundary and its gap below is half its gap above. Which
functions get NO rule is the interesting half: acosh near 1 behaves
like sqrt(2(x - 1)), which is beside nothing the format holds, so the
ordinary enclosure resolves it - the same reason phase 2's acos has
none.

The last row is the one that needed the model to reason rather than
compute. cos of an argument a hair from a multiple of 2pi is
1 - eps with eps far below the working precision; an enclosure of it
is [1 - eps - w, 1 - eps + w] and its top stays above 1 until the
precision passes -log2(eps) - the escalation the rule exists to avoid.
It does not need to: the low end plus the theorem is the proof, and
both implementations use it. The C has the reduced argument in hand,
so it applies cosPi's rule on it (2v + p + 3 <= 0 with v the reduced
argument's exponent); the model reads the low endpoint of an interval
mpmath reduced on its own.

## Two reductions, two derivations

The reference does NOT reimplement the argument reduction, and that is
deliberate: `python/cft_golden/transcend.py` hands mpmath's interval
sine and cosine an exact dyadic and lets them reduce internally, at
whatever precision the enclosure needs; the C reduces with its own
window of the stored 2/pi. Two implementations that shared a reduction
would agree about its bugs. The SIGN is the other independent
derivation: the C reads it off the quadrant its integer arithmetic
produces and never lets an evaluation decide it, exactly as phase 2
does with its mask; the model reads it off the enclosure, accepting a
rounding only when both endpoints agree on the sign - sound because
sin, cos and tan of a nonzero dyadic are never zero, so the enclosure
separates from zero at some finite precision.

The hyperbolics are written differently on the two sides too. The C
uses the doubling identity for sinh, `expm1(2x)` for tanh, and
`mp_log_of_mp`, a helper that converts a computed operand's relative
error into an absolute one on its logarithm and back, for the three
inverses; the model uses the odd/even split of expm1 and log1p forms:

    sinh(x)  = (expm1(x) - expm1(-x)) / 2
    cosh(x)  = (exp(x) + exp(-x)) / 2
    tanh(x)  = (expm1(x) - expm1(-x)) / (exp(x) + exp(-x))
    asinh(x) = log1p(x + x^2/(1 + sqrt(1 + x^2)))
    acosh(x) = log1p(d + sqrt(d*(x+1))),   d = x - 1 EXACTLY
    atanh(x) = log1p(2x/(1 - x)) / 2,      1 - x EXACTLY

The two EXACTLY are the trick phase 1's log(m') and phase 2's asin root
use: for x near 1 the difference is exact on the encoding, so the
cancellation amplifies an error of zero. Written the other way - acosh
through sqrt(x^2 - 1), atanh through log((1+x)/(1-x)) - both lose every
bit the answer has as x approaches 1. sinh and cosh carry an overflow
screen, `|x| log2(e)` enclosed above emax + 3 proving the result past
2^(emax+1), so nothing downstream is ever asked for e^(2^262143); it
fires only when it PROVES the overflow, and the response comes through
round_pack like every other.

## Special values and flags

Every row below was confirmed against MPFR 4.2.2 before it was written
down, and the ones a porter should not have to infer:

- `sin`, `cos` and `tan` of an infinity are **invalid**: no limit
  exists. The same row sinPi, cosPi and tanPi take.
- `sin(+-0) = +-0`, `tan(+-0) = +-0`, `cos(+-0) = 1`, and every one of
  them raises nothing.
- **tan never signals divideByZero** - no representable argument is a
  pole - but it CAN overflow near one, and how close a representable
  argument gets to a pole is the measurement above rather than a bound.
  sin, cos, tanh, asinh, acosh and atanh cannot overflow; sinh and cosh
  do, for a large argument, through round_pack.
- `tanh(+-inf) = +-1` EXACTLY, raising nothing.
- `atanh(+-1) = +-infinity` with **divideByZero** - 7.3's rule for an
  exact infinity from a finite operand, the row tanPi takes at a
  half-integer - and `|x| > 1` is invalid, infinities included.
- `acosh(x)` for any x below 1 is invalid: both zeros, every negative
  value, and -infinity. `acosh(+inf) = +inf`; `acosh(1) = +0`.
- `sinh` and `asinh` of `+-inf` are `+-inf`; `cosh(+-inf) = +inf`.
- Underflow happens for sin, tan, sinh, tanh, asinh and atanh of a tiny
  argument and follows clause 7 through the same round_pack.
- A signaling NaN raises invalid and delivers the canonical quiet NaN,
  as everywhere else in this contract.

## What was actually run

Windows 11, mingw64 gcc 16.1, MPFR 4.2.2, CPython 3.12, 2026-09-03.
The first half of this phase was built by one agent and the second
half finished by the reviewer after the agent was stopped twice by
server errors; every number below is from a run the reviewer made on
the tree that ships.

| check | count | result |
|---|---|---|
| `python/tests`, the whole suite | 944 passed, 1 skipped | pass |
| `host/tests/transcend_check.py`, C vs the model, twenty-nine functions | 280,670 comparisons | C == model on every one, bits and flags |
| the same, forced to start below the precision it needs | 264,430 comparisons | identical through the escalation path |
| `cft_conformance` replay at `make vectors`' arguments | 40 sets, 478,915 cases, of which 242,915 transcendental | every case, twice - per element and as arrays |
| MPFR parity, all twenty-nine, four formats, five attributes | 451,988 cases, of which 37,980 for the nine | **zero value mismatches, zero flag mismatches** |
| the same with `CFT_TRANSCEND_MINPREC=64` | 451,988 cases, 48,301 escalations | zero mismatches |
| `host/tests/api_test.c` | the phase-3 block: refusals, the exact cases, the special rows, one case from every neighbour family, and the two published worst cases with bits from mpmath at 700 bits | pass |
| `cft.hpp` vs `cft.h` | 4,111 checks at C++17 and again at C++20, each replaying 478,915 | identical encodings and flags |
| the cftmpfr drop-in | 576 tests, the nine bit-for-bit against gmpy2 at every precision and attribute MPFR has | pass |
| the Node binding | 79 tests; the page's own module at 140,869 bytes with 67 `cftw_*` exports | pass |
| `host/tools/pi_worstcase.py --validate` | 219 instances against exhaustive search | 0 disagreements |

**Escalation, measured.** The reduction: 9,855 arguments
reduced over the MPFR campaign, 0 window widenings,
widest window 1,184 bits, deepest cancellation seen
239 bits, and it never widened its window - the deepest
cancellation in that pool sits in an argument below 1, where the
window starts at bit 1 and has the argument's own exponent to spare.
The Ziv loop: at the contract's own precisions the only escalations
in the campaign are tanh's - three per format from fp64 up, nine in
all, for arguments between about 0.35(p+2) and p+2, where
1 - tanh(x) is already below the first attempt's precision but the
integer-encoded rule fires only from 2^e >= p+2 - each decided at the
next attempt. No radian argument and no other hyperbolic escalated.
The forced-low runs drive the escalation path through the C over
48,301 escalations and find the same answers.

**Negative control**, run and restored the same day: flipping the
SIDE of sin's neighbour witness in `do_radian` - so sin is claimed to
lie above a tiny argument rather than below it - is caught by
`api-test` ("sin(min subnormal) downward is +0"), by
`transcend_check.py` at the first fp32 sin case under roundTowardZero,
by the conformance replay, and by MPFR parity. The bits mpmath derived
for the two published worst cases are a second, independent control:
a reduction that dropped the wrong bits would return a plausible sine
of a slightly different number, and those two cases would not match.

## What remains of clause 9

With the twenty-nine the elementary set is complete: every function
754-2019 table 9.1 lists for which this library has a reduction and a
proof. What table 9.1 also lists and this library does not have:
`exp2m1`, `exp10`, `exp10m1`, `log2p1`, `log10p1` (exp and log again
with another constant, and the same exactness questions phase 1
answered), `pown`, `powr` and `compound` (pow with narrower domains),
and `rootn` (x^(1/n), whose exact cases are the perfect n-th powers
and need one more integer root). None needs a reduction, a constant
beyond ln 10, or a new idea; they are a smaller job than any phase so
far and are recorded in docs/ROADMAP.md as such. A tile-assisted fast
path for the narrow formats remains an optimisation, not a contract
change.

*Written 2026-09-03, and answered the same day.* The section below is
those ten. The prediction held for the machinery - no reduction, no
constant, no new series - and understated the work: the exactness
tables are larger than any phase's, two of them needed neighbour rules
nobody predicted, and the campaign found a one-ulp defect in MPFR's own
`compound`. A tile-assisted fast path is still not here.

---

# Table 9.1, completed

exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt, pown, powr, compound
and rootn - landed 2026-09-03 as part of the step to ABI 0.6. Same
promise, same evaluator, same three-way split, same loud refusal. With
these ten the library implements **every operation IEEE 754-2019 table
9.1 lists for the binary formats**.

The phase-3 section above ends by saying these are "a smaller job than
any phase so far", and that was right about the machinery and wrong
about where the work is. There is no reduction here, no constant beyond
the ln 10 and log10 e phase 1 already generates, and no new series.
What there is, is EXACTNESS: every one of the ten has a larger
exact-case table than the function it is built from, and each table has
to be proved closed before the Ziv loop under it is allowed to run,
because a true value sitting on a rounding boundary is precisely where
that loop does not terminate. Two of the ten also needed a neighbour
rule that no reasoning-from-the-shape-of-the-series predicted; the
sweep found them, and both are written up below rather than quietly
added.

## The exact cases, proved complete

| function | exact exactly when | why the list is closed |
|---|---|---|
| exp2m1 | **every integer argument** | 2^n - 1 is a dyadic rational for every n, positive or negative, and a rounding boundary of a p-bit format exactly while \|n\| <= p+1. A non-integer dyadic argument gives an algebraic irrational (exp2's own argument), so nothing else can be one |
| exp10 | a non-negative integer n whose 5^n fits in p+1 bits | 10^n = 2^n 5^n has odd part 5^n; a NEGATIVE power of ten is not a dyadic rational at all, and a non-integer dyadic exponent gives an algebraic irrational |
| exp10m1 | a non-negative integer n whose 10^n - 1 fits in p+1 bits | 10^n - 1 is an ODD integer, so its odd part is itself |
| log2p1 | 1 + x is a power of two | log2 of a positive rational is rational only for a power of two - unique factorisation, phase 1's log2 argument |
| log10p1 | 1 + x is a power of ten | the same, and 1 + x is dyadic, so only the non-negative powers can occur |
| rSqrt | x is an EVEN power of two | 1/sqrt(M 2^E) is rational only if sqrt(M) is, and dyadic only if sqrt(M) is a power of two; M odd forces M = 1, and then E must be even |
| pown | pow's integer-exponent branch: \|x\| a power of two at any n, or n <= p+1 with M^n inside p+1 bits | phase 1's p+1-bit odd-part bound, restated on an integer exponent |
| powr | the same, with the sign question deleted | the base is non-negative by domain |
| compound | 1 + x formed EXACTLY, then pown's procedure on it | the odd part of (1+x)^n is odd(1+x)^n, so the same bound closes it |
| rootn | the odd significand is a perfect \|n\|-th power AND \|n\| divides the exponent | (M 2^E)^(1/n) is rational only then; for a negative n the reciprocal of that is dyadic only when the root is 1, since 1/(odd > 1) is not |

Three of those deserve their arithmetic written out.

**exp2m1's table is the widest in the set and its boundary is the
sharpest.** 2^n - 1 for n = p+1 is a MIDPOINT of the format - the
value exactly halfway between 2^(p+1) - 2 and 2^(p+1) - and a midpoint
is the one place an enclosure never decides, at any precision. So the
exact case must reach it, and it does: |n| <= p+1 is computed by exact
integer arithmetic. One step further out, at n >= p+2, the exact
integer 2^n - 1 is up to 262,143 bits wide at fp256 and the 2048-bit
container cannot hold it - but it does not have to. The value then sits
in the top HALF of the gap below 2^n - the gap there is 2^(n-p) and
1 < 2^(n-p-1), so the value is above the midpoint - and the side
decides it; and for n <= -(p+2) the value
-(1 - 2^n) sits in the half gap above -1. Both are `round_neighbour`
witnesses, and both are exact statements rather than approximations.
The first holds up to n = emax + 1, where 2^n is past the largest
finite: overflow is judged on the rounding with the exponent unbounded
(754-2019 7.4), and toward zero that rounding is the largest finite
itself, so roundTowardZero and roundTowardNegative deliver it with
inexact alone. Only from n = emax + 2 does every attribute overflow.
Until 2026-10-30, n = emax + 1 took the overflow shortcut and raised
overflow under those two attributes as well (issue 1, found by an
outside comparison; VALIDATION.md, 2026-10-30).

**exp10 and exp10m1 past their exact tables are the counting argument
again, with one structured family worth doing by hand.** For an
integer n whose 5^n needs L > p+1 bits, 10^n is not a boundary and its
distance to the nearest one is at least 2^n absolute, hence 2^(1-L)
relative; the worst case is therefore L bits, which at fp256 is
about 183,000 and far past the cap. The expected number of n anywhere near
that is the same 2^-83-shaped count phase 1 makes for pow, over a
range of at most 78,913 integers per format, and the reasoning is
identical: 5^n mod 2^(L-p-1) is an odd number with no structure, and
the first attempt's 2p+40 bits decide it unless that residue is within
2^-(p+39) of an end.

exp10m1 has a family where the worst case IS attained, and it is
bounded: for (p+1)/log2(10) < n <= p/log2(5) the value 10^n - 1 is
exactly ONE below a multiple of the half-ulp, because 2^(e-p) divides
10^n there. The distance to the boundary is then 1 absolute and the
enclosure needs about e + 1 = log2(10)*n + 1 bits, which is at most
1.4307(p+1) - 36 bits at fp32, 77 at fp64, 163 at fp128 and 341 at
fp256, every one of them inside the FIRST attempt's 2p+40. That is a
proof rather than a measurement, and it is why the family costs
nothing.

**rSqrt can neither overflow nor underflow at any rung.** The largest
result is 1/sqrt(minSubnormal) = 2^((emax + p - 1)/2), and half of
emax + p - 1 is below emax whenever emax > p - 1, which holds at all
four (127 > 23, 1023 > 52, 16383 > 112, 262143 > 236). The smallest is
1/sqrt(maxFinite), about 2^-(emax/2), nowhere near tiny. So rSqrt has
no range screen and none is missing.

## The neighbour rules, and the two the sweep found

Five families, and the interesting half is which functions get NONE.

| family | the true value | threshold |
|---|---|---|
| `exp2m1(n)` for an integer n >= p+2 | strictly inside the top HALF of the gap below 2^n, above its midpoint | an integer test on the exponent |
| `exp2m1(x)`, `exp10m1(x)` for a very negative x | strictly inside the half gap above -1, since 2^x (or 10^x) has fallen below 2^-(p+2) | the screen's enclosure of `x` or `x log2(10)` below `-(p+3)` |
| `exp10(x)` for a tiny x | strictly between 1 and its neighbour on the sign side of x: \|10^x - 1\| <= 2.64\|x\| | `e <= -(p+4)`, the same threshold exp and exp2 take, with 2.64 in place of 1.01 |
| `pown`, `powr`, `compound`, `rootn` beside 1 | strictly inside the half gap next to 1, on the side the exact operand signs give | \|n log x\| (or \|log x / n\|) below 2^-(p+3) - pow's own rule, and for rootn it is what makes a huge \|n\| answerable at all |
| `log2p1(2^k)`, `log10p1(10^k)` | strictly above the INTEGER k, by an exponentially small step | derived below |
| `compound(x, n)` for a dominant x | strictly beside x^n, on the side of n's sign | `vexp(x) >= p + 2 + bits(\|n\|)`, with x^n an exact dyadic |

**Which functions get no tiny-argument rule, and why that is the
derivation rather than an omission.** For a tiny x,

    2^x - 1  ~ x ln2  = 0.693 x        log2(1+x)  ~ x/ln2  = 1.443 x
    10^x - 1 ~ x ln10 = 2.303 x        log10(1+x) ~ x/ln10 = 0.434 x

and not one of those is beside x. Only a base of e puts the value
inside the gap next to its own argument, which is exactly why expm1 and
log1p have a rule and their siblings in other bases do not. The
enclosure resolves all four to full relative precision, and round_pack
carries the underflow. The four answers at the smallest subnormal are
one subnormal, two subnormals, one subnormal and zero respectively -
four different answers, none of them x - and `host/tests/api_test.c`
asserts all four, because an implementation that reused expm1's rule
here would return x every time and pass every other test in this file.

rSqrt gets none either, and that one is a near miss worth stating:
1/sqrt(1+u) - 1 is about -u/2, which would be inside the half gap next
to 1 if \|u\| were below 2^-p - but the smallest nonzero u a
representable operand can have is the ulp of 1, which is 2^(1-p). No
operand comes close enough, so the rule is not needed and is not
written.

**The two rules the sweep found rather than the design predicted.**
Both are cases where the true value is an exponentially small step from
a value the format holds exactly, and neither has the shape of a
tiny-argument series.

*log2p1 of a power of two.* For x = 2^k the value is
k + log2(1 + 2^-k), and k is a GRID POINT of every format on this
ladder. An enclosure would have to separate the two and cannot, at any
precision; the side is the whole answer, and it is a theorem
(log2(1+u) > 0 for u > 0) rather than a measurement. The threshold is
derived: the excess is at most 2^(-k+0.529), the nearest boundary above
k is half an ulp away at 2^(g-p) with g = floor(log2 k), so the excess
is inside it once k > p - g + 0.529 - that is, once **k >= p - g + 1**.
And there is no band on the other side: at k = p - g the excess is at
least 1.4 half-gaps, so the enclosure decides that one with two bits
to spare. log10p1 of a power of ten is the same shape in another base;
there the comparison is made in EXACT integers against 23025/10000, a
rational below ln 10, and the closest that comparison comes to an
equality over every k any format on this ladder holds is a factor of
2^0.495 (fp128, k = 32), so five decimals of ln 10 decide it with room.

Nothing else in those two functions needs a rule, and the reason is
worth stating because it looks as though more should. x = 2^k plus one
ulp puts the value about 2^(1-p) above k in RELATIVE terms, which the
enclosure resolves in p + log2(k) bits; only the exact power, where the
whole perturbation is the "+1", is out of its reach.

*compound of a dominant operand.* For a large x the value is x^n times
(1 + 1/x)^n, and when x^n is itself an exact dyadic the correction is
below a quarter of the grid step there - so the side settles it,
exactly as hypot's dominant operand is settled. Without this,
`compound(2^1022, 1)` at binary64 is 2^1022 + 1: one unit above a grid
point whose ulp is 2^970, and no precision under the cap separates
them. The threshold: `vexp(x) >= p + 2 + bits(|n|)` makes |n/x| below
2^-(p+2), the binomial tail |(1+1/x)^n - 1 - n/x| is below 2(n/x)^2 and
so below it again, and a quarter of the relative grid step is
2^-(p+1). The correction's SIGN is n's, because 1 + 1/x is above 1 for
a positive x.

Both rules are in both implementations with the same thresholds, which
is the discipline the whole set keeps: the two may disagree about which
path answers an input, but never about whether the input is
answerable.

## The integer operand

`pown`, `compound` and `rootn` read an INTEGER second operand, and
9.2.1 says so in as many words: "n is a finite integral value in
integralFormat". So they take an `int64_t` array beside the encoding
array rather than a second encoding that would have to be interrogated
about whether it is integral - which is the question `pow` has to ask
and the reason `pow` and `pown` are different functions in the first
place.

That decision reaches four places. `cft.h` gains three prototypes whose
element count is called `count`, because `n` is taken; the vector sets
gain an `"n"` field, a signed decimal rather than an encoding, which
`host/src/conformance.c` parses with a `field_i64` of its own; the
internal `cft_tr_apply` gains an `nn` argument that is NULL for the
other thirty-six; and `cft.hpp` gains a `cspan<std::int64_t>` whose
length is checked against the output the way an encoding operand's is.
The whole int64 range is exercised - both ends of it, because INT64_MIN
has no positive negation and is exactly the value a naive |n| gets
wrong.

`rootn(x, 2)` is `squareRoot(x)` on every input but one, and the
exception is the standard's own NOTE: `rootn(-0, 2)` is +0 by the
"rootn(+-0, n) is +0 for even n > 0" row, where `squareRoot(-0)` is -0.
`host/tests/transcend_check.py` asserts the identity over the whole
pool at every attribute AND asserts the difference at that one input,
which is a stronger test than skipping the case.

## Special values and flags, all of 9.2.1

Every row was transcribed from the standard and then confirmed against
MPFR 4.2.2 - the mingw64 build on this host, the first release line to
carry `mpfr_exp2m1`, `mpfr_exp10m1`, `mpfr_log2p1`, `mpfr_log10p1`,
`mpfr_powr`, `mpfr_compound_si` and `mpfr_rootn_si` (all 4.2.0), which
`host/tools/mpfr_check.c` calls DIRECTLY. **Three rows differ, and in
all three this contract follows the standard.** Each was measured
before it was written down.

- **`rSqrt(+-0)` is `+-infinity`** with divideByZero. The sign
  survives. Measured: `mpfr_rec_sqrt(-0)` returns `+Inf`, which is what
  MPFR has always documented and predates 754-2019's rSqrt row.
  `rSqrt(+inf)` is +0 with no exception; `x < 0` is invalid,
  -infinity included.
- **`powr(1, qNaN)` is a quiet NaN.** The standard's row is
  "powr(+1, y) is 1 for FINITE y", and it lists "powr(x, qNaN) is qNaN
  for x >= 0" separately, so a NaN exponent is not covered by the
  first. Measured: `mpfr_powr(1, NaN)` returns 1.
- **`compound(x, 0)` for an x below -1 is invalid**, not 1. The row
  reads "compound(x, 0) is 1 for x >= -1 or quiet NaN", which makes the
  case below -1 rather than states it. MPFR agrees here - measured,
  `mpfr_compound_si(-2, 0)` is NaN - and it is listed with the other
  two because it is the row an implementation is most likely to get
  wrong.

The rest, and the ones a porter should not have to infer:

- `exp2m1(+-0)` and `exp10m1(+-0)` are `+-0`; `exp10(+-0)` is 1;
  `f(-inf)` is -1 for the two m1 forms and +0 for exp10; `f(+inf)` is
  +inf for all three.
- `log2p1(+-0)` and `log10p1(+-0)` are `+-0`; `f(-1)` is -infinity with
  **divideByZero** - 7.3's rule for an exact infinity from a finite
  operand, the row `atanh` takes at its pole - and an operand below -1
  is invalid, -infinity included. `f(+inf)` is +inf.
- **`powr` is not `pow`, and the differences are the point of having
  both.** `powr(x, y)` for x < 0 is invalid for EVERY y, a NaN
  included; `powr(+-0, +-0)`, `powr(+inf, +-0)` and `powr(+1, +-inf)`
  are invalid; `powr(qNaN, y)` and `powr(x, qNaN)` for x >= 0 are quiet
  NaNs with no exception - so `powr(qNaN, 0)` is a NaN where
  `pow(qNaN, 0)` is 1. `powr(+-0, y)` is +infinity with divideByZero
  for a finite y < 0, +infinity and SILENT for y = -infinity (the pole
  is the finite exponent, not the limit - the same distinction pow's
  table makes), and +0 for y > 0.
- **`pown(x, 0)` is 1 for any x that is not a signaling NaN**, an
  infinity and a quiet NaN included. `pown(+-0, n)` is `+-infinity`
  with divideByZero for an odd n < 0 and `+infinity` for an even one;
  `+-0` for an odd n > 0 and `+0` for an even one. The infinity rows
  are the same table with the zeros and infinities exchanged.
- `compound(-1, n)` is +infinity with divideByZero for n < 0 and +0 for
  n > 0; `compound(+-0, n)` is 1; `compound(+inf, n)` is +infinity for
  n > 0 and +0 for n < 0; `compound(qNaN, n)` is a quiet NaN for
  n != 0.
- **`rootn(x, 0)` is invalid for EVERY x, a quiet NaN included**: zero
  is outside the domain, and 9.2's general rule for an operand outside
  the domain is a quiet NaN with invalid. `rootn(x, 1)` is x, exactly
  and silently. A negative operand with an even n is invalid,
  -infinity included; the zero and infinity rows split on the parity of
  n exactly as pown's do.
- A signaling NaN raises invalid and delivers the canonical quiet NaN,
  as everywhere else in this contract.

## The oracle's own defect, and what was done about it

Phase 1 found that mpmath's interval `power` is not quite rigorous and
widened every endpoint by 256 units in response. This set found
something sharper, in the other oracle.

**`mpfr_compound_si` is off by one unit in the last place for a
NEGATIVE n**, whenever 1 + x is not representable at the working
precision - a double rounding of the intermediate sum. Measured on
4.2.2, this host, 2026-09-03, at 24 bits of precision:

    compound(1 + 2^-23, -1) toward zero returns 0x7.fffffp-4
      where (2 + 2^-23)^-1 computed at 400 bits and rounded once
      is 0x7.fffff8p-4
    compound(3 - 2^-22, -1) to nearest returns 0x4p-4
      where the same reference gives 0x4.000008p-4

n = -2 and n = -4 do it too on the same operands; a non-negative n does
not. `mpfr_pow_si` and `mpfr_rootn_si` were checked the same way over
n in [-12, 12] and five attributes and are sound at every one, so the
defect is specific to that entry point and that sign.

The library's answers were confirmed independently three ways before
the workaround was written: the golden model's rigorous mpmath
enclosure, the C's own tracked error bound, and
`python/tests/test_transcend.py`'s brute-force enclosure at four times
the escalation cap all agree with the 400-bit reference and not with
`mpfr_compound_si`. The campaign therefore keeps MPFR's own compound
for n >= 0 - which is the comparison worth having - and for n < 0
builds the expectation from the EXACTLY formed 1 + x and
`mpfr_pow_si`: still MPFR arithmetic, still one rounding, and not the
entry point with the defect. The domain rows (x <= -1) go through
`mpfr_compound_si` either way, since it is right about those.

That is the second time an external arbiter has been wrong in this
project and the second time the two independent implementations caught
it. It is the argument for having two.

## Where the two implementations disagree about EFFORT

They never disagree about an answer. They do disagree about how much
precision one of them takes, and this set produced the clearest example
the project has. Measured:

    iv.log1p(10587189 * 2^-106) at 88 bits returns an interval of
    RELATIVE width 4.8e-5; at 176 bits it is exact

mpmath's interval log1p forms 1 + x and takes the logarithm of a value
next to 1, so for an argument of magnitude 2^-83 it loses about
eighty-three bits of relative accuracy. The C never forms 1 + x for a
small argument - `mp_log1p_small` sums `2 atanh(u/(u+2))` on the EXACT
operand - so it decides those inputs at the first attempt, and the
model escalates once and agrees.

That had never shown before because phase 1's log1p has a neighbour
rule covering every |x| below 2^-(p+3), so the model was never asked
for one. log2p1 and log10p1 deliberately have no such rule - their
value is x/ln2 or x/ln10, which is not beside x - so they do ask. It is
the Ziv loop working exactly as designed, and it is one more reason the
two implementations are written differently on purpose.

## What was actually run

Windows 11, mingw64 gcc 16.1, MPFR 4.2.2, CPython 3.12, 2026-09-03,
with three other agents building on the same machine - so nothing below
is a timing figure and none is quoted as one.

| check | count | result |
|---|---|---|
| `python/tests`, the whole suite | 1,241 passed, 1 skipped | pass |
| `host/tests/transcend_check.py`, C vs the model, thirty-nine functions | 607,217 comparisons | C == model on every one, bits and flags |
| the same, forced to start below the precision it needs | 580,977 comparisons | identical through the escalation path |
| `rootn(x, 2)` against `cft_sqrt`, per element and per attribute | 17,665 comparisons | identical everywhere except x = -0, where the standard's own NOTE says they differ - and that difference is asserted |
| `make vectors` | 40 sets, 769,265 cases, of which 533,265 transcendental | regenerated from the model |
| `cft_conformance` replay at `make vectors`' arguments | 40 sets, 769,265 cases | every case, twice - per element and as arrays |
| `host/tests/api_test.c` | the table-9.1 block: the refusals, the exact cases, the three rows MPFR gets differently, one case from every neighbour family and from every family that has none | pass |
| MPFR parity, all thirty-nine, four formats, five attributes | 544,788 cases, of which 92,800 for the ten | **zero value mismatches, zero flag mismatches** |
| the same with `CFT_TRANSCEND_MINPREC=64` | 544,788 cases, 72,381 escalations | zero mismatches |
| `cft.hpp` vs `cft.h` | 4,549 checks at C++17 and again at C++20 | identical encodings and flags |
| the cftmpfr drop-in | 668 tests | pass, with exp10, rSqrt and rootn bit-for-bit against gmpy2 |
| `make examples-lang` | C++, Rust, Go and C# against the C example; Julia and R absent | same library, same bits |
| `verify/run.sh --only vectors,libcft,mpfr,transcend,cpp,bindings` | two stages of six - vectors and libcft | ok; STOPPED during transcend under time pressure, so the runner has not been seen green end to end on this tree. Every stage it did not reach was run standalone above with the arguments it uses |

**Escalation, measured.** Over the MPFR campaign's 306,460
transcendental elements, 138,825 reached the Ziv loop and it escalated
**nine** times - and all nine are phase 3's tanh, three per format from
fp64 up, which is exactly the count phase 3 recorded. **Not one of the
ten escalated there.** 32,585 elements were decided exactly and 56,835
by a neighbour's side.

**The ten's MPFR share was on the wrong pool (found 2026-10-30).** Its
92,800 cases ran on the trigonometric pool, not on the exponential pool
that holds their exact cases: the exp2 integers, the powers of two and
of ten, and the neighbours of one. `check_transcend` calls its fourth
argument `tpool`, and the caller passes the trigonometric pool there.
So none of the ten was held against MPFR at an exp2 integer at the top
of the range. On the exponential pool, MPFR found 10 flag mismatches in
the library as it stood, all of them exp2m1(emax + 1) under rtz and rdn
(issue 1), and nothing else. Since then the ten run on both pools. The same
question for all thirty-nine is answered below (audit of 2026-11-02).

Over `transcend_check.py`'s whole sweep the model escalated 182 times
across all thirty-nine functions and every pass the harness makes. A
separate run of the model ALONE over this set's own pools says where
the ten's share comes from:

| function | escalations | deepest |
|---|---|---|
| powr | 12 per format at fp64, fp128, fp256 | 292, 532 and **832** bits |
| log2p1, log10p1 | 25 each at fp32, 5 each at fp64 | 176 and 292 bits |
| the other seven | none, at any format | - |

powr's are phase 1's `pow(1+u, -(1+u))` family, inherited unchanged
along with the analysis that bounds it at 3p bits - 832 is the fp256
cap, exactly where phase 1 said that family lands. log2p1's and
log10p1's are the model's own evaluator rather than the mathematics,
and the section above explains them: mpmath's interval log1p forms
1 + x, so a tiny argument costs it most of its relative accuracy and it
needs the second attempt. The C decides those at the first. The balance
of the 182 is phase 1's pow on its own pool - 36 of them, the number
phase 3 recorded and unchanged by this set - and the batch passes
re-running operands the per-element passes already escalated on. Every
one of the 182 landed on the same answer as the C.

Forced low: `CFT_TRANSCEND_MINPREC=64` drives 72,381 escalations
through the MPFR campaign and finds the same answers, and
`transcend_check.py --min-prec 64` drives the C's escalation path
against an UNESCALATED model over 580,977 comparisons with identical
results.

**Negative control**, run and restored the same day. Inverting one
character - the `away` argument of log2p1's neighbour witness in
`do_logp1_family`, so `log2p1(2^k)` is claimed to lie BELOW the integer
k rather than above it - is caught by `api-test` (1 FAILED, at "and
upward it is nextUp(30)"), by `transcend_check.py` (fp32 rtz,
`log2p1(2^24)`: `0x41bfffff` where the model says `0x41c00000`), by the
conformance replay (which stops at 92,033 cases), and by MPFR parity
(from the first fp32 log2p1 row under roundTowardZero). Four gates, and
the rule it breaks is one of the two this set added.

### The pools, audited for all thirty-nine (2026-11-02)

Issue 1 was a pool that did not hold a family: the ten of table 9.1 had
never been asked an exp2 integer at the top of the range. The same
question, asked of every function at every format: for each family its
hard cases live in, does the pool it runs on hold members of it, and how
many? Four sources name the families, and the comparison with each was
run rather than read.

- **The vector generator.** `python/cft_golden/vectors.py` directs a list
  of operands at each function; it was written for the same hard cases
  and is the only other list of them in the repository. `mpfr-check`
  prints what it would ask (`CFT_MPFR_DUMP_CASES=1 ./mpfr-check 24 7`:
  every case of the transcendental phases, once, with the pool it comes
  from and whether its operands are directed or random; half a second),
  and a script builds the generator's operands at `extra = 0` with every
  append tagged by the line of the generator that makes it. A family is a
  line. A family the vectors direct at a function that its pool lacks is a
  gap by definition.
- **The golden model's branches.** The same cases, run through
  `python/cft_golden/transcend.py` under `sys.monitoring`, first hit per
  line, at each format: a line the vectors' cases reach and the
  oracle's do not is a branch the oracle never asks, and a line neither
  reaches is a hole in both. The thresholds no line shows are families
  too: each tiny rule (`ex <= -(p+c)`, `2 ex + p + c <= 0`, `ex >= p+1`),
  each screen (emax + 2, emax + 3, emin - man_w - 2), each exact table's
  bound (`|n| <= p+1`, M^n inside p+1 bits, 10^n - 1 inside p+1 bits, the
  k at which log2p1 changes rule) is straddled: the last operand on the
  rule's side, the first off it, and one more.
- **IEEE 754-2019 9.2.** The special rows: both zeros, both infinities, a
  quiet and a signaling NaN, 1, the ends of every domain, and for the
  binary functions every pair of them.
- **This document**, for the exact tables and the neighbour rules proved
  above.

What the vector generator directs at each group, and how many of it the
pools held. Distinct operands (pairs, for the binary functions; the
(operand, n) pairs with n inside the host's `long` for pown, compound and
rootn), fp32 / fp64 / fp128 / fp256. MEASURED on the desktop, 2026-11-02:

| functions | what the vectors direct | held before | held after |
|---|---|---|---|
| exp family (7) | 221/258/337/499 | 74/97/104/104 | 221/258/337/499 |
| trig family (9) | 244/244/244/244 | 116/116/116/124 | 244/244/244/244 |
| sin cos tan (3) | 626/4268/290/290 | 66/66/48/53 | 626/4268/290/290 |
| hyperbolics (6) | 222/222/222/222 | 73/73/72/81 | 222/222/222/222 |
| table 9.1 unary (6) | 524/775/871/1071 | 97/123/127/127 | 524/775/871/1071 |
| pow | 706/706/706/706 | 29/30/25/25 | 706/706/706/706 |
| hypot | 137/137/137/137 | 13/13/13/13 | 137/137/137/137 |
| atan2, atan2pi | 384/384/384/384 | 24/24/24/28 | 384/384/384/384 |
| powr | 733/733/733/733 | 46/49/44/40 | 733/733/733/733 |
| pown compound rootn | 2160/2160/2160/2160 | 184/182/187/179 | 2160/2160/2160/2160 |

Six findings, in the order they matter. Each is MEASURED.

1. **Twenty functions had no specials at three formats.** The trigonometric
   pool and the third pool (sinPi to atan2Pi, sin to atanh) take their first
   eighteen entries from an array `main` hands them, and what `main` hands
   them is the clause-5 loop's last pool, which is fp256's. At fp256 that is
   right. At fp32, fp64 and fp128 it is eighteen fp256 encodings read through
   a narrower format: at fp32 they are +0 twelve times, 0x00000001 three times
   and 0xffffffff three times. No -0, no infinity, no signaling NaN, no 1, no
   minimum or maximum normal: sin(+-inf), asin(-0), atanh(+-1) and the rest of
   9.2.1's rows were not held against MPFR at fp32, fp64 or fp128 for the
   eleven functions of the one pool and the nine of the other. (Table 9.1's
   ten, which also run on the trigonometric pool, have had the real ones from
   the exponential pool since 2026-10-30.)
   The defect is left in place, so that the default run asks what it always
   asked; the extras ask the real specials (`t:io`, `r:io`, `h:io`).
2. **The binary functions were asked 4 to 10 percent of the pairs the
   vectors direct.** `check_transcend` pairs `P[i]` with `P[j]` for
   `j = i mod (n/8), + n/8, ...`, which reaches the diagonal of the specials
   and little else: pow(-1, +inf), atan2(+-0, -0), hypot(inf, NaN) and the
   other off-diagonal rows of 9.2.1 were not asked. Nor were more than 5 of
   the 40 Pythagorean-triple pairs of hypot, any perfect power under a dyadic
   exponent (0 of 96), or most of the (operand, n) pairs at which M^n leaves
   the exact table: pown, compound and rootn pair each operand with a third of
   15 values of n.
3. **exp and expm1 never met their own edges.** The n ln 2 that overflow,
   underflow and make tiny the result (65 operands in the vector set) were
   held 0 of 65 at every format; sinh and cosh held 18 of 50 of theirs.
   exp2's integers stopped at emin - man_w: its tie at emin - man_w - 1
   (-150, -1075, -16495, -262379) and the quarter beneath it were never
   asked. The tie is where exp2 rounded wrongly under roundTiesToAway until
   2026-10-05, a defect this oracle could not have found (see the control
   below).
4. **The exact cases past the old pool's limit.** The powers of ten stop at
   5^25 (the builder multiplies while the odd part is under 2^60), so log10's
   exact table at fp128 and fp256 was held 53 of 147 and 53 of 309 operands;
   10^k - 1, where log10p1 is exact, 0 of 7, 15, 34 and 71; 2^k - 1, where
   log2p1 is exact, 20, 18, 18 and 18 of 278, 480, 480 and 480.
5. **sin, cos and tan: the reduction's hardest operands.** Every power of two
   over the exponent range is the window's start; the vector set has 554, 4,196
   and, sampled, 194 and 194 of them, and the pool held 54, 54, 2 and 2. The
   worst cases of the reduction (the representable numbers nearest a
   multiple of pi/2, one per binade of a sweep) were held 0 of 24, 24, 18
   and 18 at fp32, fp64, fp128 and fp256 (4 at fp128 by chance).
6. **Five lines of the model that no pool and no vector reaches**, and 65
   that only the vectors do; the branches are below.

By the vector generator's lines, the families and what each pool held
(need / held before / held after, fp32 / fp64 / fp128 / fp256; the three
numbers in a cell are a count of distinct operands or pairs):

**exp, expm1, exp2, log, log1p, log2, log10**

| family | need | held before | held after |
|---|---|---|---|
| the specials and extremes of both signs; NaNs with payload | 32/32/32/32 | 20/20/20/20 | 32/32/32/32 |
| powers of two, with a neighbour each side | 24/24/24/24 | 23/23/23/23 | 24/24/24/24 |
| 2^-k and 3 2^(-k-1), k = p+2 .. 2p (the neighbour rules) | 24/24/24/24 | 10/10/10/10 | 24/24/24/24 |
| powers of ten 5^k 2^k, with neighbours | 33/69/147/309 | 23/47/53/53 | 33/69/147/309 |
| 1 +- ulp, both signs | 4/4/4/4 | 3/3/3/3 | 4/4/4/4 |
| integers 1..24, p, 2p, emax-1..emax+1, emin-1.., to emin-man_w-1 | 60/62/62/62 | 14/14/14/14 | 60/62/62/62 |
| n ln 2, rounded and walked two ulps (overflow and underflow edges) | 65/65/65/65 | 0/0/0/0 | 65/65/65/65 |

**sinpi, cospi, tanpi, asin, acos, atan, asinpi, acospi, atanpi**

| family | need | held before | held after |
|---|---|---|---|
| the specials and extremes of both signs; NaNs with payload | 32/32/32/32 | 13/13/13/21 | 32/32/32/32 |
| 2^-k and 3 2^(-k-1), k = p/2 .. 4p | 36/36/36/36 | 27/27/27/27 | 36/36/36/36 |
| halves, quarters, integers and eighths, with neighbours | 162/162/162/162 | 79/79/79/79 | 162/162/162/162 |
| 1 - 2^-p and 1 - 2^(1-p) (asin's domain edge) | 4/4/4/4 | 2/2/2/2 | 4/4/4/4 |
| 1 +- ulp, both signs | 4/4/4/4 | 4/4/4/4 | 4/4/4/4 |
| the top of the range, 2^k for k = p-1 .. emax | 24/24/24/24 | 8/8/8/8 | 24/24/24/24 |

**sin, cos, tan**

| family | need | held before | held after |
|---|---|---|---|
| the specials and extremes of both signs; NaNs with payload | 32/32/32/32 | 13/13/13/22 | 32/32/32/32 |
| 2^k and 2^k - 1ulp at the ends and p, 2p | 36/36/36/36 | 21/21/21/23 | 36/36/36/36 |
| every power of two over the exponent range (sampled at the wide two) | 554/4196/194/194 | 54/54/2/2 | 554/4196/194/194 |
| 2^-k and 3 2^(-k-1), k = p/2-1 .. 2p | 28/28/28/28 | 21/21/21/21 | 28/28/28/28 |
| the reduction's worst cases (pi_worstcase.py) | 24/24/18/18 | 0/0/4/0 | 24/24/18/18 |

**sinh, cosh, tanh, asinh, acosh, atanh**

| family | need | held before | held after |
|---|---|---|---|
| the specials and extremes of both signs; NaNs with payload | 32/32/32/32 | 13/13/13/22 | 32/32/32/32 |
| 2^-k and 3 2^(-k-1), k = p/2-1 .. 4p | 32/32/32/32 | 24/24/24/24 | 32/32/32/32 |
| small integers, halves, quarters, with neighbours | 102/102/102/102 | 16/16/16/18 | 102/102/102/102 |
| 1 +- ulp, both signs | 4/4/4/4 | 4/4/4/4 | 4/4/4/4 |
| 2^k near 2^bitlen(p+2) (tanh -> 1) | 18/18/18/18 | 10/10/9/9 | 18/18/18/18 |
| n ln 2 +- 2 ulps (the sinh/cosh overflow edge), both signs | 50/50/50/50 | 18/18/18/18 | 50/50/50/50 |

**exp2m1, exp10, exp10m1, log2p1, log10p1, rsqrt**

| family | need | held before | held after |
|---|---|---|---|
| the specials and extremes of both signs; NaNs with payload | 32/32/32/32 | 22/22/22/22 | 32/32/32/32 |
| powers of two -6..6, +-p, emax, emin, with neighbours | 116/116/116/116 | 43/43/43/43 | 116/116/116/116 |
| 2^-k and 3 2^(-k-1), k = p+2 .. 2p | 20/20/20/20 | 13/13/13/13 | 20/20/20/20 |
| 2^k - 1 and 2^-k (2^k - 1), k <= min(p, 40) | 278/480/480/480 | 20/18/18/18 | 278/480/480/480 |
| 1 +- ulp, both signs | 4/4/4/4 | 4/4/4/4 | 4/4/4/4 |
| integers 1..11, p-1..p+3, 2p, emax-1..emax+1, emin, emin-man_w | 126/126/126/126 | 33/35/33/33 | 126/126/126/126 |
| powers of ten 5^k 2^k, with neighbours | 33/69/147/309 | 23/47/53/53 | 33/69/147/309 |
| 10^k - 1 | 7/15/34/71 | 0/0/0/0 | 7/15/34/71 |

**pow**

| family | need | held before | held after |
|---|---|---|---|
| the specials against the specials | 256/256/256/256 | 25/25/21/21 | 256/256/256/256 |
| integer exponents against 2, 3, 5, 7, 10, 4097 | 180/180/180/180 | 5/5/5/5 | 180/180/180/180 |
| perfect powers against dyadic exponents | 96/96/96/96 | 0/0/0/0 | 96/96/96/96 |
| pow(1+u, -(1+u)), the escalating family | 60/60/60/60 | 2/2/3/3 | 60/60/60/60 |
| a base 1 +- dy ulp against exponents across the range | 144/144/144/144 | 3/4/3/3 | 144/144/144/144 |

**hypot**

| family | need | held before | held after |
|---|---|---|---|
| Pythagorean triples, both signs | 40/40/40/40 | 5/5/5/5 | 40/40/40/40 |
| triples, one ulp off | 20/20/20/20 | 1/1/1/1 | 20/20/20/20 |
| triples scaled to the range's ends | 40/40/40/40 | 2/2/2/2 | 40/40/40/40 |
| extremes, zeros, infinities and NaNs | 11/11/11/11 | 5/5/5/5 | 11/11/11/11 |
| a dominant operand | 27/27/27/27 | 1/1/1/1 | 27/27/27/27 |

**atan2, atan2pi**

| family | need | held before | held after |
|---|---|---|---|
| the axes against the axes | 205/205/205/205 | 11/11/11/13 | 205/205/205/205 |
| the diagonals and one ulp off them | 128/128/128/128 | 12/12/12/14 | 128/128/128/128 |
| min subnormal over 2, 4, 1 | 5/5/5/5 | 0/0/0/0 | 5/5/5/5 |
| big and small against 1 and -1 | 30/30/30/30 | 0/0/0/0 | 30/30/30/30 |
| tiny y against 1, -1, 2, 3 | 20/20/20/20 | 1/1/1/1 | 20/20/20/20 |

**powr**

| family | need | held before | held after |
|---|---|---|---|
| powr's own table: negative bases, zeros, infinities, NaNs | 196/196/196/196 | 27/29/25/21 | 196/196/196/196 |
| the specials against the specials | 256/256/256/256 | 38/40/36/32 | 256/256/256/256 |
| integer exponents against 2, 3, 5, 7, 10, 4097 | 180/180/180/180 | 8/8/8/11 | 180/180/180/180 |
| perfect powers against dyadic exponents | 96/96/96/96 | 0/0/0/0 | 96/96/96/96 |
| pow(1+u, -(1+u)), the escalating family | 60/60/60/60 | 2/2/3/3 | 60/60/60/60 |
| a base 1 +- dy ulp against exponents across the range | 144/144/144/144 | 5/6/5/5 | 144/144/144/144 |

**pown, compound, rootn**

| family | need | held before | held after |
|---|---|---|---|
| the specials and extremes (operand only) | 23/23/23/23 | 20/20/20/20 | 23/23/23/23 |
| 2^e (operand only) | 24/24/24/24 | 17/17/17/17 | 24/24/24/24 |
| 2^-k (operand only) | 12/12/12/12 | 12/12/12/12 | 12/12/12/12 |
| perfect powers m 2^e, both signs (operand only) | 120/120/120/120 | 19/18/19/18 | 120/120/120/120 |
| perfect powers +- 1 ulp (operand only) | 32/32/32/32 | 10/10/10/10 | 32/32/32/32 |
| (operand, n) in the generator's stride, n within the host's long | 1560/1560/1560/1560 | 100/99/102/97 | 1560/1560/1560/1560 |
| (operand, n) for n = 0, 1, 2, -1, -2 | 900/900/900/900 | 125/123/125/120 | 900/900/900/900 |

**The golden model's branches.** At fp32 the vectors' cases reached 65
(function, line) pairs that the oracle's did not, 60 at fp64, 66 at fp128
and 33 at fp256: at fp32 pow 10 (6 at fp64), hypot 8, atan2 and atan2Pi 6
each, powr 4 (3), log10p1 4, atan, atanPi and acosh 3 each, exp2 2, and
one each for sixteen more functions, nearly all of them the infinity or
NaN row of finding 1. After the extras: none, at any format. The cases of
neither set reached five lines, which now the extras do: `hypot:898` (an
exact Pythagorean hypot past the largest finite, hypot(21 2^(emax-4), 28
2^(emax-4))), `rootn:2862` (the overflow screen, rootn(3 2^-(emax+3),
-1)), `_pow_dyadic:450` and `:453` (a perfect power to a dyadic exponent
whose power outruns p + 1 bits, pow(9, 27/2) at fp32) and
`_hypot_dyadic:501` (a Pythagorean hypot wider than p + 1 bits, the pair
(2^(j+1) - 1, (2^j - 1) 2^(j+1)) for j just over p/2). What no argument
reaches, at any of the four: `_mag_ge`'s zero rows and `_integrality`'s
zero and infinity rows (callers screen them first), `_pi_reduce`'s
even-integer and half-integer returns (the exact cases return before it),
`_signed_parts`'s straddle of zero (only a forced low start precision
reaches it), `_mag_cmp`'s shift left (the precision schedule keeps the
exponent negative), `_int_kth_root`'s M = 1 return, `_logp1_family`'s two
x = 0 returns (zero returns earlier), `pown`'s neighbour rule beside 1
(the nearest an integer exponent brings n log x to zero is 2^(1-p), above
2^-(p+3)) and `rootn`'s exact underflow (a root only shrinks the
exponent): fifteen lines (19 or 20 before the extras, at every format).

**Added beyond what the vector generator directs,** by family: where the
model or the standard asks for it, what it holds, how many of the intended
members the pools did not already ask, per format, and the cases they came
to (five attributes each).

| family | functions | where the model or the standard asks | what it holds | added of intended (fp32 / fp64 / fp128 / fp256) | cases |
|---|---|---|---|---|---|
| `x:int-edge` | exp, expm1, exp2, log, log1p, log2, log10 | `_exp_family`'s integer branch: `n > emax`, `n < emin - man_w - 1`, and the tie at `emin - man_w - 1` | the integers at both ends and each side of the tie, with the operand's own neighbours | 50 of 50 / 48 of 50 / 50 of 50 / 50 of 50 | 1,750 / 1,680 / 1,750 / 1,750 |
| `x:pow2-sub` | the same seven | log2's exact case `M == 1` at the subnormal powers of two | 2^k for k from emin - man_w to emin + 1, with neighbours | 14 of 14 / 14 of 14 / 14 of 14 / 14 of 14 | 490 / 490 / 490 / 490 |
| `x:ln2-edge` | the same seven | the screens at emax + 2 and emin - man_w - 2, and the true edges at emax + 1 and emin - man_w - 1 | n ln 2 for ten n, walked two ulps, both signs | 100 of 100 / 100 of 100 / 100 of 100 / 100 of 100 | 3,500 / 3,500 / 3,500 / 3,500 |
| `x:tiny-edge` | the same seven | the tiny rules, `ex <= -(p+c)` and `2 ex + p + c <= 0` for c = 2..6 | the binade boundary of each, straddled | 46 of 46 / 46 of 46 / 46 of 46 / 46 of 46 | 1,610 / 1,610 / 1,610 / 1,610 |
| `t:tiny-edge` | the nine trigonometric | the same rules, and atanPi's `ex >= p + 1` | the same | 36 of 36 / 38 of 38 / 38 of 38 / 38 of 38 | 1,620 / 1,710 / 1,710 / 1,710 |
| `t:beside-half` | sinPi, cosPi, tanPi | `2 s_vexp + p + 6 <= 0`, s the distance from a half-integer | h +- 2^-j for h = 1/2 .. 3 and j round (p + 6)/2 | 72 of 72 / 72 of 72 / 72 of 72 / 72 of 72 | 3,240 / 3,240 / 3,240 / 3,240 |
| `r:tiny-edge` | sin, cos, tan | the same rules | the same | 36 of 36 / 36 of 36 / 48 of 48 / 48 of 48 | 540 / 540 / 720 / 720 |
| `r:worst` | sin, cos, tan | the reduction's hardest binades (`_reduction_worst_cases`) | the representable numbers nearest a multiple of pi/2, found from MPFR's pi by the continued fraction, with a neighbour each side | 24 of 24 / 24 of 24 / 14 of 18 / 18 of 18 | 360 / 360 / 210 / 270 |
| `h:ln2-edge` | the six hyperbolics | `_cosh_sinh_overflow` at emax + 3 and the true edge at emax + 2 | n ln 2, walked two ulps | 42 of 60 / 42 of 60 / 42 of 60 / 42 of 60 | 1,260 / 1,260 / 1,260 / 1,260 |
| `h:tiny-edge` | the six hyperbolics | the same rules | the same | 46 of 46 / 48 of 48 / 48 of 48 / 48 of 48 | 1,380 / 1,440 / 1,440 / 1,440 |
| `m:int-edge` | exp2m1, exp10, exp10m1, log2p1, log10p1, rSqrt | exp2m1's `n == emax + 1`, `n > emax + 1`, `abs(n) <= p + 1` | the integers round each, with neighbours | 24 of 24 / 24 of 24 / 24 of 24 / 24 of 24 | 720 / 720 / 720 / 720 |
| `m:tiny-edge` | the same six | the same rules | the same | 36 of 46 / 38 of 46 / 38 of 46 / 38 of 46 | 1,080 / 1,140 / 1,140 / 1,140 |
| `m:log2p1-edge` | log2p1 | `_logp1_family`: x = 2^k from `k >= p - g + 1` | 2^k for the five k round the first | 14 of 14 / 15 of 15 / 15 of 15 / 15 of 15 | 420 / 450 / 450 / 450 |
| `m:log10-edge` | exp10, exp10m1 | their screens: `x log2(10)` against emax + 2 and -(p + 3) | n log10(2), walked two ulps | 90 of 90 / 90 of 90 / 90 of 90 / 90 of 90 | 2,700 / 2,700 / 2,700 / 2,700 |
| `pow:edge` | pow | `_screen_exponent`'s thresholds, and the overflow and underflow edges beneath them | (x, y) with y at n / log2(abs(x)) for x = 3, 5, 10, 3/2, 5/4, 3/4 and n at the top and the bottom of the range, walked two ulps, and the integers round it | 324 of 324 / 324 of 324 / 324 of 324 / 324 of 324 | 1,620 / 1,620 / 1,620 / 1,620 |
| `powr:edge` | powr | the same | the same | 324 of 324 / 324 of 324 / 324 of 324 / 324 of 324 | 1,620 / 1,620 / 1,620 / 1,620 |
| `pow:dyadic-wide` | pow | `_pow_dyadic`: `Y > p + 1`, and `root^Y` wider than p + 1 bits | a perfect square or fourth power to Y / 2^k with Y odd, across both edges | 46 of 46 / 54 of 54 / 54 of 54 / 51 of 51 | 230 / 270 / 270 / 255 |
| `powr:dyadic-wide` | powr | the same | the same | 46 of 46 / 54 of 54 / 54 of 54 / 51 of 51 | 230 / 270 / 270 / 255 |
| `hypot:exact-top` | hypot | `hypot:898`, the exact hypot past the largest finite | (3, 4), (5, 12), (8, 15) scaled so that the hypot passes 2^(emax+1) and so that it does not | 24 of 24 / 24 of 24 / 24 of 24 / 24 of 24 | 120 / 120 / 120 / 120 |
| `hypot:wide-triples` | hypot | `_hypot_dyadic`: an exact hypot wider than p + 1 bits | (2^(j+1) - 1, (2^j - 1) 2^(j+1)) for j round p/2 | 15 of 15 / 15 of 15 / 15 of 15 / 15 of 15 | 75 / 75 / 75 / 75 |
| `atan2:tiny-over-unit` | atan2, atan2Pi | `2 qv + p + 3 <= 0`, `ey - ex <= -(p+1)` | the vector set's tiny y against +-1, 2, 3, with the thresholds' k added | 46 of 50 / 46 of 50 / 46 of 50 / 46 of 50 | 460 / 460 / 460 / 460 |
| `int:specials` | pown, compound, rootn | 9.2.1's rows for the zeros, infinities and NaNs | the 18 specials against the 15 n the oracle uses | 58 of 145 / 58 of 145 / 58 of 145 / 65 of 145 | 870 / 870 / 870 / 975 |
| `int:exact-edge` | pown, compound | `_pown_dyadic`: `n > p + 1`, `M^n` wider than p + 1 bits | M, -M and M - 1 for odd M against the n round where M^n leaves p + 1 bits | 142 of 144 / 157 of 158 / 159 of 159 / 160 of 160 | 710 / 785 / 795 / 800 |
| `int:perfect-power` | rootn | `_rootn_dyadic`: the odd significand a perfect n-th power in absolute value | r^n, with neighbours, for r = 2 .. 13 and n = 2 .. 12 | 178 of 180 / 277 of 279 / 277 of 279 / 277 of 279 | 890 / 1,385 / 1,385 / 1,385 |
| `int:subnormal-recip` | rootn | `rootn:2862`, the overflow screen | 3, 5, 7 times a power of two just under the format's range, against n = -1, -2, 1 | 54 of 54 / 54 of 54 / 54 of 54 / 54 of 54 | 270 / 270 / 270 / 270 |
| `int:power-edge` | pown | the screens | 3, 5, 10 and their negatives against the n that takes them to 2^(emax+1) and 2^(emin-man_w-1) | 72 of 72 / 72 of 72 / 72 of 72 / 72 of 72 | 360 / 360 / 360 / 360 |

What was added, in `host/tools/mpfr_check.c`, as a phase of its own after
table91 that draws no random number: the three pools are as they were, down
to the draws, so every case the oracle asked before it asks now. A candidate
the function's pool already holds is skipped, and so is a pair the strided
pairing already asks. At the end of a run the tool prints, for each family
and format, how many members were intended, how many the pools held and how
many were added, and how many cases that came to; a dump line names the
family of each added case. Subsets run with `CFT_MPFR_PHASES` (a comma list of
`arith`, `clause5`, `transcend`, `trig`, `radian`, `table91`, `extras`,
`reduce`, `convert`, `formatof`) and `CFT_MPFR_FORMATS`; unset, everything
runs as it did.

**What it asks now, and what that cost.** MEASURED on the desktop (mingw64
gcc 16.1, GNU MPFR 4.2.2, 2026-11-02), the transcendental phases of each
format on their own, `CFT_MPFR_PHASES=transcend,trig,radian,table91,extras
CFT_MPFR_FORMATS=<format> ./mpfr-check 24 7`; cases per phase:

| format | transcend | trig | radian+hyperbolic | table91 | extras | all five | value / flag mismatches |
|---|---|---|---|---|---|---|---|
| fp32 | 23,920 | 20,000 | 9,495 | 53,360 | 102,860 | 209,635 | 0 / 0 |
| fp64 | 23,920 | 20,000 | 9,495 | 53,360 | 166,070 | 272,845 | 0 / 0 |
| fp128 | 23,920 | 20,000 | 9,495 | 53,360 | 113,355 | 220,130 | 0 / 0 |
| fp256 | 23,920 | 20,000 | 9,495 | 53,360 | 126,720 | 233,495 | 0 / 0 |
| four | 95,680 | 80,000 | 37,980 | 213,440 | 509,005 | 936,105 | 0 / 0 |

The first four columns are the oracle's own phases and have the numbers
they had on 2026-10-30 (23,920, 20,000, 9,495 and 53,360 a format): the
pools and their draws are as they were.

The extras alone, run apart, were 102,860, 166,070, 113,355 and 126,720
cases in 10, 27, 45 and 179 seconds at fp32, fp64, fp128 and fp256
(509,005 cases and 261 seconds in all). The same run earlier that hour, on
a quieter desktop and before two small families were added, took 6, 20, 35
and 151 seconds, 212 in all: the machine is shared, and the numbers move
with it.

The stage's `mpfr-check 24 7` was 859,874 cases in 565 s on 2026-10-30,
and the other phases are unchanged, so the whole run should be 859,874 +
509,005 = **1,368,879 cases in about 826 s** (565 + 261), or 777 s on the
quieter measure: 38 and 46 percent over 565, inside the brief's 50. That
is INFERRED, not measured. The full run is the lead's to make.

**Controls**, run on the 2026-11-02 tree, both on copies outside the
repository.

- The library as it stood before the exp2 fix (`ca43695d^`), against this
  oracle's extras alone: four value mismatches, one at each format, and no
  other case differing. Each is exp2 at emin - man_w - 1 under
  roundTiesToAway (family `x:ints`), at -150 (0xc3160000), -1075, -16495
  and -262379, where the library gives +0 with flags 0x18 and MPFR the
  smallest subnormal with flags 0x18: the four records ca43695d moved. The
  old pools hold none of the four operands (the fp32 pool has no -150).
- A fault planted in a copy of `host/src/transcend.c` (`asin(-0)` returns
  +0), against the pools as they were and then the extras: the trigonometric
  phase's 20,000 cases per format find nothing at fp32, fp64 or fp128, and the
  extras find it at each: 10 mismatches (asin and asinPi at -0, five
  attributes each; family `t:io`). At fp256 the old pool holds the real -0
  and finds the same 10.

**What the audit does not reach.**

- A family nobody has written down: not in the vector generator, not a
  threshold of the model, not a row of 9.2, not in this document. In
  particular the worst cases for rounding of exp, log, pow and the rest (the
  known hardest-to-round arguments) are in no pool; the reduction's are.
- The branch audit ran at all four formats, with the directed operands only (a
  dump's randoms are not a full run's). It shows which lines are reached, not
  that every value of a reached line's variables is.
- n beyond the host's `long` (MPFR's operand type): 300 vector pairs a format
  of pown, compound and rootn (n = +-2^62, INT64_MIN, INT64_MAX and -2^31).
  Host/tests/transcend_check.py holds them against the model.
- The pairs the strided pairing and the families skip are most of the cross
  product, on purpose; the new pairs are the vector generator's and the
  families named above.
- Sin, cos and tan at the wide formats are sampled as the vector generator
  samples them: 192 powers of two, and the deepest three binades of eight.
- The comparison scripts are not filed; the dump they read is what the tool
  prints.

## What is NOT here

- **The tile's RSQRT_SEED opcode.** `rSqrt` is host work like the other
  thirty-eight: `cft_mp_sqrt` and one division inside the evaluator.
  The tile has a reciprocal-square-root SEED opcode and a fast path
  built on it - seed, Newton refinement, an exactly measured residual -
  is a plausible later optimisation for the narrow formats, exactly as
  it is for exp. It would have to reproduce these bits exactly, which
  makes it an optimisation rather than a different answer, and nothing
  in this set reads it.
- **Anything else from table 9.1.** There is nothing else: with these
  ten the binary half of the table is complete.

---

# The six on the tile

exp, expm1, exp2, log, log1p and log2 - six of phase 1's nine - are also
routines the tile runs, since the math library round's M1 build
(2026-10-13 to 2026-10-19). Everything above is about libcft's host
operations and is left as it was; this section says what the six are,
what they are not, and where the record is.

- **Programs of the tile's instructions, on revision 8.** M1's build
  changed no RTL: the rtl tree, 44b963dd, is unchanged since 2026-10-05.
  Revision 8 carried what M1 and M2 need of a tile (docs/ROADMAP.md,
  "Revision 8: step 6's RTL revision": "M1 and M2 need R24's raise, with
  its mark, and R23's byte"). `python/cft_golden/mathlib.py` generates
  each at each of the four formats and five attributes, 120 fragments of
  175 to 433 instructions (docs/VALIDATION.md, M1's build, item 4); the
  design is docs/studies/M1-exp-log.md.
- **Operations of the language, not of the ABI.** `cftc` compiles each
  run-time `exp(a)` and the rest as a routine inlined where its node
  stands (language 1.1 and cftc's output version 6, 2026-10-15), for the
  software targets and revision 8's; revision 7's refuse such a program,
  `target-feature`. The thirty-nine host operations (`cft_exp` and the
  rest) call none: each is "HOST work: no cft_run pass is issued"
  (`host/src/transcend.c`, its header), and a program reaches a routine
  through the language (docs/LANGUAGE.md, "The operations").
- **Decided in the lane, or marked.** Where the true value lies within a
  routine's error bound of a rounding boundary - for whole windows of
  arguments, exp near 0 and log near 1 among them - the routine marks
  the lane, bit 7 of the lane byte and STATUS[6], and the definition
  replays it (docs/LANGUAGE.md, "A marked lane"). `transcend.py` stays
  the one definition.
- **Held** golden-first, with a planted fault for every check
  (`python/tests/test_mathlib.py`); through libcft's sequencer, 240
  programs and 13,483 lanes at the gate's arguments, 0 mismatches
  (`host/tests/seq_check.py`'s eighth corpus); by the `lang`,
  `lang-routines` and `tangent` stages, an unmarked lane equal to the
  definition bit for bit and a marked one replayed; and on the card,
  rev8q, 2026-10-19: "6 of 6 PASS", "118 checks ok, 0 failed"
  (docs/VALIDATION.md, "M1's build, seventh wave, closed").
- **Not here:** the other thirty-three, which are host operations only.
  The roadmap's next builds are sin, cos and tan (M2,
  docs/studies/M2-trig.md), then atan, atan2, asin and acos (M4), and
  the pow family (M3) last. No performance claim is made, as above:
  docs/FIGURES.md's "What a correctly rounded function costs the tile"
  counts instructions, not time.
