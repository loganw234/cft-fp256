# Study M4: the correctly rounded atan, atan2, asin and acos, designed

STATUS: a design study, 2026-10-23. Parcel M4S of the math library round
(docs/ROADMAP.md, "The math library: experiment E1, then M1's build and
M2 to M4 (plan of record, 2026-10-12)", its paragraph "M2, M3 and M4").
Logan, 2026-10-23, answering whether M4's study should run beside M2's
build: "Yes and go ahead with the study now". **Nothing here is built.**
No inverse trigonometric routine is in the golden model, cftc is
unchanged, and the language still refuses `atan(x)` as `transcendental`.
The design goes to the lead, and through the lead to Logan, before M4's
build, which is a round of its own, after M2's. This file, the model under
`docs/studies/m4/`, this file's row in docs/README.md and its VALIDATION
entry are the only changes the study made.

M2's study (docs/studies/M2-trig.md) is its nearest model of form, section
for section, and M1's design and Logan's answers on M1's and M2's studies
are its starting point: the in-lane test, the double word with TwoSum and
no augmented addition, the fragment in C4's shape, G and its mark-rate law,
the triple word at fp32. Where this study departs from one of them it says
so.

Every statement is one of five kinds, and says which:
- **READ**: from this tree at 3310133, with the file named;
- **MEASURED**: from a run of the study's model (section 11), on the
  desktop, niced, one process at a time, each run's output kept beside the
  model as `*.out.txt`; the runs, their times and the desktop's load are in
  the round's ledger (`ledger/M4S.md`), which is outside the tree;
- **COMPUTED**: arithmetic on read or measured numbers, shown;
- **ESTIMATE**: mine, and said so;
- **PROPOSED**: this design. Every name, constant and order below is a
  proposal for the lead and Logan, not a decision.

## Contents

0. In brief
1. What M4 works with
2. The algorithms
3. The error bound and the in-lane test
4. The specials and the flags
5. The cost
6. The language and the compiler
7. The derivative rules
8. How it will be held
9. Questions for Logan, each with a recommendation
10. What M4's build builds, in order
11. The model

---

## 0. In brief

- **What.** atan, atan2, asin and acos at fp32, fp64, fp128 and fp256
  under each of the five attributes, each a fragment in C4's shape, quiet,
  raising exactly transcend.py's flags, and setting bit 7 of the raised
  word where its own test cannot decide the last bit. PROPOSED, and
  measured in a Python model op by op through softfloat.compute, on seq.py
  as programs, and against transcend.py and mpmath.
- **One core, four front ends** (PROPOSED; MEASURED in the model, 2.1 to
  2.5). transcend.py defines all four through atan2, and so does the
  design: every function is sign (C + sigma theta0) with
  theta0 = atan(n/d), 0 <= n <= d, C one of 0, pi/2 and pi, sigma = +-1.
  - **The reduction** is a table of N = 8 entries, c = k/8, with ONE
    double-word quotient s = (n - c d)/(d + c n) = tan(theta0 - atan c),
    |s| <= 1/15; k is chosen from t~ = n_h RECIP_SEED(d_h), 8.5 bits, with
    a bias of 63/64 that keeps n_h - c d_h exact by Sterbenz for every
    k >= 1. Then atan(s) by a Taylor polynomial, M2's double-word head (K =
    6 steps) and a single-word tail (degree 12, 20 and 35 at fp64, fp128
    and fp256).
  - **asin and acos** take w = sqrt((1 - |x|)(1 + |x|)), transcend.py's
    product form, with 1 - |x| exact and 1 + |x| an exact double word, and
    a double-word square root (RSQRT_SEED, Newton, the exact residual by
    FMA). acos near 1 is then a small angle computed as one; nothing
    cancels anywhere.
  - **atan2's whole 9.2.1 table rides the core**: an infinite or zero
    operand forces theta0 to 0 (both infinite, to pi/4), and C and sigma do
    the rest, the signed zeros included. Its exact-quotient rule is decided
    in-lane by one FMA; its tiny-quotient range (x > 0, |y/x| below
    2^(emin+p+2), where the double word loses its low word) is marked.
- **The cost** (MEASURED, 5.1): atan 176, 186 and 203 instructions at
  fp64, fp128 and fp256; asin 221, 235 and 256; acos 4 fewer; atan2 216,
  226 and 243. **asin and acos of one argument cost 255, 269 and 290
  together** in a compiled step, 34 instructions more than asin alone,
  since cftc's inliner shares everything up to the quadrant's constant.
  Bank words 66, 74 and 89 for all four functions under all five
  attributes; no scratch slot; 15 to 21 values live. Against M2's sin
  (406, 382, 389) the inverse functions cost about half: their reduction
  is algebraic.
- **The bound** (MEASURED, verifier-VM1b's first-order budget as M2
  ported it, changed for two inputs, 3.2): every region keeps more than
  four bits at Logan's G, at most 0.058 Bv at fp64 (asin's random region;
  0.064 with its second-order residual), 0.030 at fp128 and 0.023 at
  fp256; fp32's double word at G = 18 keeps about one bit (0.42 Bv). The
  largest budget at each format bounds every error measured there, though
  13 of 76 regions' own budgets, from 300 lanes at fp128 and fp256, are
  passed by another sample's worst (3.3): the box's larger budgets are
  handed to the lead.
- **Held in the model against transcend.py** (MEASURED): the pools
  (transcend_check's trig pool and atan2 pairs with the vector sets'), all
  four formats, functions and attributes, 0 wrong unmarked lanes, on the
  model and as programs on seq.py; the specials row by row, the whole 9.2.1
  table included; five regions of placed arguments a function, 0 wrong.
- **The marks** (3.4, 3.5): random lanes at about 2^-G sig(V) where the
  values spread, fewer where they crowd next to pi/2 and pi; structured
  families: the tiny family (atan's x^3/3, asin's x^3/6, and atan2's exact
  quotients, which are atan's), the windows next to pi/2 and pi (atan of a
  large x, acos of a small x, atan2 beside its axes), about 2^(p - G + 2)
  arguments a window, and atan2's quotient within the bound of a grid
  point, division's hard cases. None next to +-1 (acos near 1 is a small
  angle with a relative gap of at least 2^-(p+3.6) from any representable
  number), none at the diagonals. Every marked guess counted; every
  unmarked lane right.
- **fp32** (2.8, question 3): **the triple word at G = 40 is built and
  measured**, not estimated: atan 472, asin 637, acos 633 and atan2 516
  instructions, 75 words for all four; 25 values live scheduled, 31 for
  atan2, so every fragment fits the 32 registers and runs on seq.py; 0
  wrong over the pools on the model and on seq.py; errors at most 2^-4.4
  Bv over five regions (measured, with no budget, as M1's fp32). Its first
  version passed the pools while missing its bound by 2^17 (3.6, item 5).
  The double word at G = 18, the fallback, is measured beside it: 143 to
  184 instructions, about one bit by its budget.
- **The model found eight things wrong in itself** (3.6), four of them
  worth the build's attention: a budget that froze its roundings (a
  residual of exactly 0 the tell); fp32's first triple word, which passed
  every pool while missing its bound by 2^17; 1 - x^2 formed directly,
  which I had argued exact and therefore no fault, and which passes every
  pool while missing the bound by 2^24 to 2^38 (now a plant); and the
  unbiased index, a real fault that the pools, the placed points, the
  specials and the bound check all missed, wrong and unmarked at every
  format on lanes the samplers never reach (now caught by section 8's
  audit). No defect in transcend.py was found.
- **Thirteen questions for Logan** (section 9), each with a
  recommendation.

## 1. What M4 works with

### 1.1 The plan, and what binds it

READ, docs/ROADMAP.md, the math library's plan of record: "Each starts as
a design study like M1's: golden-first, measured in a model, its questions
to Logan before its build. Each function gains an L3 rule." "M4, atan,
atan2, asin and acos." "M4 follows M2."

What binds it (READ, Logan's answers on M1's study, 2026-10-12, and on
M2's, 2026-10-14):
- **G:** 44 at fp64, 46 at fp128 and fp256 (mathlib.py's `GUARD`);
- **fp32:** the triple word at G = 40, as M1's `plan_exp32` and
  `plan_log32` build it; for M2 the triple word measured first, the double
  word at G = 18 the measured fallback;
- **the in-lane test and the mark:** M1's test, Bv = 2^-(p+G) |V_h|, bit 7
  of the raised word (`seq.RAISE_MARK`) where the test cannot decide;
  quiet otherwise, raising exactly transcend.py's flags;
- **the structured families keep their marks,** their windows' centres
  listed in the build's tests (M2's answer 7);
- **constant arguments:** the exact cases folded, every other constant
  refused by name (M1's question 8, M2's answer 8);
- **live caps per function and format** (M2's answer 9);
- **the generator in mathlib.py** (M2's answer 11);
- **versions:** M2's build steps cftc's output version to 7 and the
  language to 1.2 (M2's answer 12);
- **no augmented addition:** the quad has no R21 (revision 8's question
  9), so every error-free sum is a TwoSum (6 instructions) or, where the
  exponents are provably ordered, a Fast2Sum (3);
- **the rounding rule:** IEEE 754 first (Logan, 2026-09-29). atan, atan2,
  asin and acos are 754-2019's recommended operations, 9.2, table 9.1, and
  atan2's special values are 9.2.1's.

### 1.2 What a tile gives a routine

READ (`python/cft_golden/softfloat.py`, `seq.py`, `routines.py`,
docs/SEQUENCER.md), as M1's 1.2 and M2's 1.2 list it, and four facts
M4 needs that they did not:
- **RECIP_SEED and RSQRT_SEED flush a subnormal operand to infinity**
  (softfloat.recip_seed: "Flush-at-input is a deliberate spec choice made
  for the hardware"; rsqrt_seed the same), and give 8.5 bits elsewhere. So
  atan2, whose operands may both be subnormal, scales them before any seed
  (2.5); asin's and acos's w is never subnormal (2.4).
- **A comparison's result is 1.0 or +0** (softfloat.icmplt), and SELECT
  tests the magnitude, so a sign bit taken by IAND (-0) reads as false.
  The design takes x's sign as a condition by ICMPLT against SIGN - 1, and
  XORs two conditions by IXOR of their encodings.
- **MIN and MAX** are ALU instructions (softfloat's 7 and 8); the design
  uses MIN to keep the table's index at most N - 1 and MAX to keep
  RSQRT_SEED's operand off zero at |x| = 1 (both data, 3.2).
- **routines.program and routines.run take two inputs** (r0 and r1, as
  division's a and b), so atan2's fragment runs on seq.py as y in r0 and x
  in r1, y first as C and transcend.py have it.

### 1.3 The definition

READ, `python/cft_golden/transcend.py`, `_asin_family` (asin at its line
1319), `_acos_family` (1373), `_atan_family` (1423), `_atan2_family`
(1534), and the helpers they call (`_ziv`, `_round_dyadic_side`,
`_exact_quotient`):
- **Each is a Ziv loop over mpmath's interval atan2.** asin(x) is
  atan2(|x|, sqrt((1-|x|)(1+|x|))) with x's sign; acos(x) is
  atan2(sqrt((1-x)(1+x)), x), not pi/2 - asin(x), "for x just below 1 the
  difference form cancels away the whole answer"; atan(x) is atan2(x, 1).
- **Exact only at the zeros and acos(1) = +0** (the comment above
  `_asin_acos_common`: by Hermite-Lindemann, asin, atan and atan2 of
  dyadic arguments are exact only where the result is a zero).
- **The tiny gates differ** (e = floor(log2 |x|)):
  - asin rounds x on the far side from zero once 2e + p + 2 <= 0
    (asin(x) - x = x^3/6 + ... > 0);
  - atan rounds x on the zero side once 2e + p + 3 <= 0
    (atan(x) - x = -x^3/3 + ... < 0);
  - acos has none: it is pi/2 - x - ..., next to nothing.
- **atan2:** the whole 9.2.1 table, atan2(+-0, -0) = +-pi included; the
  diagonals |y| = |x| through the enclosure (pi/4 and 3pi/4 are
  irrational, so no rule); and the exact-quotient rule for x > 0: when
  y/x is a dyadic q = qm 2^qe on the format's half-step grid
  (qe >= g - 1) and tiny (2 qv + p + 3 <= 0, qv = floor(log2 q)), the
  answer is decided on the zero side of q. atan2(minSubnormal, 2) lands on
  a subnormal MIDPOINT this way. An exact quotient finer than the half
  grid (only possible below 2^emin) is no rounding boundary, and the Ziv
  loop decides it.
- **No overflow, no divideByZero**; underflow only on the tiny paths and
  atan2's tiny quotients; inexact on every nonzero result (the results are
  irrational).

The routine must give transcend.py's bits and flags on every lane it does
not mark.

### 1.4 The constants beside the rounding boundaries

COMPUTED (`consts.py`, pi to 4,000 bits; `consts.out.txt`). A lane whose
answer is a multiple of pi/4 (atan(+-inf), every axis and diagonal of
atan2, acos(+-0), acos(-1), asin(+-1)) is decided by the in-lane test only
if that constant lies more than Bv from every rounding boundary. Its
distance, relative to the constant, in units of 2^-(p+G):

| | to a grid point (rtz, rdn, rup) | to a midpoint (rne, rmm) |
|---|---|---|
| fp64, pi/4, pi/2, pi | 6.2 x 10^12 Bv | 5.0 x 10^12 Bv |
| fp64, 3pi/4 | 6.2 x 10^12 | 8.8 x 10^12 |
| fp128, pi/4, pi/2, pi | 2.0 x 10^13 | 2.5 x 10^13 |
| fp128, 3pi/4 | 2.0 x 10^13 | 4.0 x 10^13 |
| fp256, pi/4, pi/2, pi | 4.0 x 10^13 | 4.4 x 10^12 |
| fp256, 3pi/4 | 1.9 x 10^13 | 4.0 x 10^13 |
| fp32 at G = 18, pi/4, pi/2, pi | 1.2 x 10^5 | 4.5 x 10^4 |
| fp32 at G = 18, 3pi/4 | 1.1 x 10^4 | 2.1 x 10^5 |

- **No constant answer marks** at any format or attribute: the nearest is
  2^42 Bv away at fp64 (fp32's double word, 2^13). At G = 40 fp32's bound
  is 2^22 times smaller, so the same distances are 2^22 times more bounds:
  at least 4.6 x 10^10 Bv (COMPUTED from the table).
- **Within reach of a correction term,** though, a boundary is crossed:
  atan(x) = pi/2 - 1/x + ... lands on the boundary b nearest pi/2 from
  below where 1/x = pi/2 - b, and acos(x) = pi/2 - x - ... where
  x = pi/2 - b. Those windows are 3.5's structured family; consts.py lists
  the nearest three boundaries per kind and the arguments within Bv of
  each, about 2^(p - G + 2) a window (fp64: 2^11.4 next to the nearest
  grid point, 2^9.4 next to the nearest midpoint; fp128 2^69; fp256 2^192).

## 2. The algorithms

### 2.1 One core, four front ends

PROPOSED. Every function is one fragment of eight parts, all run on every
lane, since there is no branch:

1. **front:** n <= d, both nonnegative, and the conditions the quadrant
   needs; atan: n, d = min, max of |x| and 1; asin, acos: of |x| and
   w = sqrt((1-|x|)(1+|x|)), a double word (2.4); atan2: of |y| and |x|,
   scaled when d is subnormal or large (2.5);
2. **index:** t~ = n_h RECIP_SEED(d_h); k = min(round(7.875 t~), 7) by
   the magic-number FMA and one MIN; c = k/8, exact (2.2);
3. **one quotient:** s = (n - c d)/(d + c n) as a double word, n - c d and
   d + c n by TwoProd, n_h - c d_h exact by Sterbenz; RECIP_SEED, Newton
   to p + 8 bits, the exact remainder by FMA, M2's tan quotient (2.2);
4. **z = s^2** as an exact double word, s's low word's share included;
5. **atan(s)/s** by Taylor in z: a single-word tail from degree D down to
   K, then K double-word steps, M2's head step (2.6); atan(s) = s P(z) as
   a double word;
6. **the table:** atan(k/8) in two words by a SELECT tree over k's three
   bits, bank words only;
7. **the reconstruction:** theta0 = atan(c) + atan(s);
   V = C + sigma theta0 with C one of 0, pi/2, pi in two words and sigma a
   sign word, then the result's sign, all applied to the double word V
   before its one rounding (rdn and rup are not symmetric);
8. **the final rounding and the test,** M1's (2.7), then the tiny paths,
   the specials and atan2's rules, lowest priority first.

The quadrant, by function (PROPOSED; swap is "n came from the second
operand"):

| function | n, d | swap | C, sigma | the result's sign |
|---|---|---|---|---|
| atan(x) | min, max of \|x\|, 1 | \|x\| > 1 | swap: pi/2, -; else 0, + | x's |
| asin(x) | min, max of \|x\|, w | \|x\| > w | swap: pi/2, -; else 0, + | x's |
| acos(x) | as asin's | as asin's | x >= 0: swap 0, +, else pi/2, -; x < 0: swap pi, -, else pi/2, + | + |
| atan2(y, x) | min, max of \|y\|, \|x\| | \|y\| > \|x\| | swap: pi/2, sigma - iff x >= 0; else 0, + (x >= 0) or pi, - (x < 0) | y's |

**Parts 2 to 6 do not depend on the function,** and asin and acos of one
argument share their front end too (acos's selection is asin's, its swap
read negated), so cftc's inliner, which hash-conses a routine's
instructions across a step's instances (READ, python/cftc/inline.py,
"SHARING"), computes everything up to C and sigma once. MEASURED
(`share.py`, inline.expand's keying replayed, every attribute):

| | fp64 | fp128 | fp256 |
|---|---|---|---|
| asin alone | 221 | 235 | 256 |
| asin and acos of one argument | 255 (438 apart) | 269 (466 apart) | 290 (508 apart) |

That is what makes asin's and acos's derivative rules cheap beside each
other (7), and a program that wants both pays 15% more than one.

**The internal arithmetic is RNE;** the routine's own attributes are RDN
and RUP (the test's two ends) and the program's attribute (the final
rounding and the tiny paths' FMA): within mathlib.py's widened invariants
(MEASURED: `mathlib.invariants` holds on all 80 fragments with no live
cap, `costs.*.out.txt`).

### 2.2 The reduction: a table, an index from a seed, one quotient

PROPOSED; MEASURED in the model (`m4inv.py`).

**Why a table, and why this one.** atan's Taylor series converges like
z^i/(2i+1), not factorially, so the reduced argument's size sets the
polynomial's length directly, and t = n/d alone (at most 1) does not
converge at all. The classical reduction is atan(t) = atan(c) +
atan((t - c)/(1 + t c)). It costs a quotient and the table's words; the
trade is measured in 2.3.

**One quotient, not two.** (t - c)/(1 + t c) with t = n/d is
(n - c d)/(d + c n): the reduced argument comes straight from n and d,
and t itself is never formed. Only t's first bits are needed, to choose k,
and RECIP_SEED gives them in one instruction: t~ = n_h RECIP_SEED(d_h),
within 2^-8.5 + 2^-p of n_h/d_h (READ, softfloat.recip_seed; the log
family's C = round(16 RECIP_SEED(m)) in mathlib.py is the same idea).

**The index, and why it is biased.** n - c d is formed as
(n_h - P) + (P - c d_h) + n_l - c d_l with P = RN(c d_h) and P - c d_h
its exact TwoProd error, and n_h - P must be exact: Sterbenz, if
1/2 <= n_h/P <= 2. A cell's k is chosen from t~, not t, so t can lie a
little outside the cell; unbiased, k = round(8 t~) = 1 admits
t/c = (1/2)(1 - 2^-8.5)/(1 + 2^-8.5) = 0.4945 by the seed's documented
bound, below 1/2. That is reached, not only allowed. The seed is the
reciprocal of its cell's midpoint to 18 bits, over 512 cells (READ,
softfloat `_seed_recip_entry`), so it overestimates 1/d in the upper half
of every cell; with d's significand within 2^-11 of 2 and n just under
d/16, the unbiased index takes k = 1 with a power of two between n_h and
P - n_h, and the difference needs p + 1 bits (COMPUTED). MEASURED (3.6,
item 7): at d = 2 - 2^-12 and n = 1/8 - 2^-15 - ulp, the unbiased index
has t/c = 0.49994, n_h - P rounds, and atan2 is wrong and unmarked at
every format (2^44 Bv at fp64). So k = round(7.875 t~) (7.875 = 8 x 63/64,
exact). COMPUTED in exact rationals (`m4inv.rho_of`,
`cells`), with |t~/t - 1| <= 0.0028:
- every k >= 1 has t/c in [0.5065, 1.5281], so n_h - P is exact
  (the top cell's ratio is at most 8/7 since n_h <= d_h by the selection);
- k is at most 7 by a MIN on the magic-number sum (the top cell is
  [6.5/(7.875 (1 + eps)), 1]), and k = 0 for t below 0.0636;
- |s| = |t - c|/(1 + t c) <= rho = 0.066667 (1/15, reached at t = 1 in
  the top cell: (1 - 7/8)/(1 + 7/8)), over every cell's ends; the bias
  costs nothing there.

**The numerator and the denominator** (PROPOSED). n - c d: the TwoProd
of c with d_h, n_h - P exact, the low words summed (for atan and atan2,
whose n and d are single words, n - c d is exactly the double word
(n_h - P) + (P - c d_h), normalised by Fast2Sum: |n_h - P| >= |P - c d_h|
or n_h = P; asin's and acos's add n_l and c d_l and take a TwoSum).
d + c n: Fast2Sum(d_h, RN(c n_h)) (d_h >= c n_h), the TwoProd error and
the low words into the low word. With k = 0 both are n and d themselves.

**The quotient** is M2's tan quotient (its 2.5): RECIP_SEED of D_h,
Newton y <- y + y (1 - D_h y) from 8 to at least p + 8 bits (3 steps at
fp64, 4 at fp128, 5 at fp256), s_h = N_h y, the remainder N_h - s_h D_h
exact by FMA, then + N_l - s_h D_l, s_l = remainder times y, Fast2Sum:
17, 19 and 21 instructions (MEASURED, the phase "quotient"). Its error is
about u^2 relative and enters the budget (3.2).

**Its size by part** (MEASURED, `costs.py`, rne; the other attributes give
the same counts):

| part | atan, fp64 | asin, fp64 | atan2, fp64 | atan, fp256 |
|---|---|---|---|---|
| front (and asin's sqrt) | 5 | 8 + 36 | 17 | 5 |
| index | 7 | 7 | 7 | 7 |
| numerator, denominator | 6 + 6 | 11 + 8 | 6 + 6 | 6 + 6 |
| quotient | 17 | 17 | 17 | 21 |
| z, tail, head | 6 + 6 + 52 | 6 + 6 + 52 | 6 + 6 + 52 | 6 + 29 + 52 |
| atan(s) = s P | 6 | 6 | 6 | 6 |
| table | 17 | 17 | 17 | 17 |
| reconstruction | 23 | 20 | 35 | 23 |
| final rounding and test | 9 | 9 | 9 | 9 |
| classify, specials, atan2's rules | 4 + 12 | 4 + 14 | 32 | 4 + 12 |
| in all | 176 | 221 | 216 | 203 |

The double-word head is the largest part, as in M1 and M2, and does not
grow with p: K = 6 at every format, since the head covers the terms above
2^-(G+3), which G and rho set (M1's 2.4). The tail grows with p: degree 12,
20 and 35. Nothing else does, but the quotient's Newton steps (17, 19, 21)
and asin's root's (36 to 44).

### 2.3 The trade: the table's size, halving, a longer polynomial

MEASURED (`costs.py`, the four functions built at each N; rne):

| N | rho | head K, degree D (fp64; fp128; fp256) | atan fp64, fp128, fp256 | atan2 fp64 | asin fp64 |
|---|---|---|---|---|---|
| 2 | 1/3 | 14, 29; 14, 49; 14, 87 | 243, 265, 305 | 283 | 288 |
| 4 | 1/7 | 8, 16; 8, 27; 8, 49 | 187, 200, 224 | 227 | 232 |
| **8** | **1/15** | **6, 12; 6, 20; 6, 35** | **176, 186, 203** | **216** | **221** |
| 16 | 0.0341 | 5, 9; 5, 16; 5, 28 | 182, 191, 205 | 222 | 227 |

- **N = 8 is the cheapest at every format** (fp32's double word too:
  160, 144, 143, 151 for atan). Each doubling of N saves about two head
  steps and halves the tail's slope, and costs a level of the SELECT tree
  in each of the two words: past 8 the tree outgrows the saving. M1's N = 8
  (Logan's answer 3 on M1's study) is this design's too.
- **N = 2 is "a longer polynomial":** c is 0 or 1/2 (the top cell at the
  Sterbenz limit, t/c <= 2 exactly), rho = 1/3, and the polynomial pays:
  K = 14 and D = 87 at fp256. With no table at all (c = 0, rho = 1) the
  series does not converge at t = 1 in any number of terms that fits.
- **Halving through a square root,** atan(t) = 2 atan(t/(1 + sqrt(1 +
  t^2))), is not built. ESTIMATE from the measured parts: a halving costs
  a double-word root (36 to 44 instructions, asin's) and a quotient (17
  to 21) and about 9 for 1 + t^2 and 1 + root, some 62 to 74; one halving
  takes rho from 1 to tan(pi/8) = 0.414, worse than N = 2's 1/3, so it
  would cost N = 2's polynomial and more, about 300 at fp64; two halvings
  (rho = 0.199) about 120 more for the halvings than N = 8's table and
  quotient together, for a polynomial still longer than N = 8's. The
  table wins.
- **1/x past 1** is the min/max of the front end: it costs nothing beyond
  the quotient every lane computes anyway (2.1), since n/d is formed for
  every lane.

### 2.4 asin and acos: the product form, and one root

PROPOSED.

**u = 1 - x^2 as (1 - |x|)(1 + |x|),** transcend.py's own trick:
1 - |x| by Fast2Sum (1 >= |x|; exact, and its error word zero for
|x| >= 1/2 by Sterbenz), 1 + |x| by Fast2Sum, exact; the product of the
two exact double words to a double word: TwoProd of the heads and two FMAs
for the cross terms, 12 instructions. The dropped product of the two error
words is at most u^2/2 where 1 - x^2 >= 3/4. Near |x| = 1, u is formed with
no cancellation at all; the root's residual needs u as a double word, and
gets one.

**The direct form is exact, and breaks the bound** (MEASURED, `uform.py`,
the pools under all five attributes and |V - f| / Bv over the edge, big
and diag regions, 300 lanes each at fp64 and fp32's double word, 100 at
fp128 and fp256). On a tile with FMA, 1 - x^2 is also exactly 1 - RN(x^2)
(Fast2Sum, since 1 >= RN(x^2)) plus x^2's TwoProd error, 7 instructions
against 12. It passes every pool (0 wrong, 0 marked) and misses the bound:

| largest \|V - f\| / Bv | fp32 double word | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| asin, the product form | 0.0499 | 0.008894 | 0.01559 | 0.01653 |
| asin, direct | 48.07 | 2.136 x 10^7 | 461 | 0.01653 |
| acos, the product form | 0.06963 | 0.009333 | 0.007793 | 0.01005 |
| acos, direct | 3,983 | 2.749 x 10^11 | 1.049 x 10^6 | 1.678 x 10^7 |
| either, direct then one Fast2Sum | the product form's, to the four digits printed | the same | the same | the same |

The two words are exact but not normalised: at x = 1 - k 2^-p, x^2's
rounding error is k^2 2^-2p while 1 - RN(x^2) is 2k 2^-p, so |u_l/u_h|
reaches about 2^(-(p+3)/2) near k = 2^((p-1)/2), and the root's one
residual step from u_h leaves (u_l/u_h)^2/8 of w: 2^-(p+6) relative, 2^(G-6)
Bv for acos, whose V is w there (COMPUTED: 2^38 at fp64, matching 2.7 x
10^11; 2^40 at fp128 and fp256, where 100 lanes a region did not reach the
worst k; asin's V is pi/2 less w, so its relative error is w's times
w/(pi/2)). One more Fast2Sum normalises the pair, 10 instructions against
the product form's 12, and gives the product form's largest errors at
every format: both are then normalised double words of the same u, and
the fp256 asin row shows that 100 lanes need not find the direct form's
fault at all. **Not proposed:** every other measurement here is
of the product form, and 2 instructions in 221 do not pay for measuring
asin and acos again; M4's build may take it with its own budget (5.4). The
direct form was first written into the model as a plant; I then argued it
no fault, since it is exact, and made it an alternative; measured, it is a
plant again (3.6, item 6).

**w = sqrt(u) as a double word:** y = RSQRT_SEED(MAX(u_h, 2^(emin+2p))),
the MAX only keeping the seed finite at u = 0 (|x| = 1, where u_h is
exactly 0 and w must come out exactly 0); Newton
y <- y + (y/2)(1 - u y^2), four instructions a step, 3, 4 and 5 steps;
w_h = u_h y; the residual u_h - w_h^2 exact by FMA, plus u_l; w_l = that
times y/2; Fast2Sum. 36 instructions at fp64, 40 at fp128, 44 at fp256
with the product form (MEASURED, the phase "sqrt").

**asin and acos share the core.** n, d = min, max of |x| and w by one
integer compare and four SELECTs; acos uses asin's selection with its swap
read negated, so the two functions' core instructions are one (2.1). The
alternatives the brief names, measured or argued:
- **the half-angle form** 2 asin(sqrt((1 - |x|)/2)): its 1 - |x| is exact
  too, but it costs a second root and a second core pass in a branchless
  fragment (every lane runs both forms), and the product form already
  carries no cancellation; not proposed (ESTIMATE: about 60 instructions
  more);
- **acos near 1 as a small angle:** it is one here: x near 1 has
  n = w (small), d = |x|, swap false, C = 0, sigma = +, so V = theta0 =
  atan(w/|x|), computed relative to itself; no pi/2 - asin(x) anywhere;
- **one polynomial on a SELECTed argument, against two polynomials and a
  SELECT:** the core is one polynomial on the SELECTed n, d; two
  polynomials would double the head (52 instructions) for nothing.

### 2.5 atan2: scaling, the quadrant, the table's rows, the exact quotient

PROPOSED.

**Scaling.** n = min(|y|, |x|), d = max: both are multiplied by 2^3p where
d < 2^(emin + 3p) (RECIP_SEED flushes a subnormal d, and the TwoProds'
errors must stay normal), and by 2^-2 where d >= 2^(emax - 1) (d + c n
would overflow), by three SELECTs each; the quotient is unchanged, and an
n lost to the downward scaling sits below every bit V keeps. 10
instructions.

**The quadrant** is the table of 2.1: C = pi/2 where |y| > |x|, else 0 or
pi by x's sign bit (so x = -0 counts as negative, which is 9.2.1's row);
sigma negative where swap XOR x's sign; the result's sign is y's.

**The 9.2.1 table rides the core.** With an infinite or zero operand the
quotient is garbage (NaN, or 0 against infinity); the core's theta0 is
forced to 0 there, and to pi/4 where both operands are infinite, by four
SELECTs, and C, sigma and y's sign then give every radian row: atan2(+-0,
-0) = +-pi (swap false, x negative, C = pi), atan2(+-0, x < 0) = +-pi,
atan2(+-y, +-0) = +-pi/2 (swap true), atan2(+-inf, finite) = +-pi/2,
atan2(+-inf, +-inf) = +-pi/4 and +-3pi/4, atan2(finite, -inf) = +-pi. Each
such V is a multiple of pi/4 in two words, rounded once by the final
rounding and decided by its test (1.4: every such constant lies 2^42 Bv or
more from a boundary). The zero rows (y = +-0 against x >= +0, and a finite
y against +inf) select y's signed zero after the rounding, with no flag.
The diagonals |y| = |x| need nothing: t = 1, k = 7, s = 1/15, and
atan(7/8) + atan(1/15) = pi/4 exactly in the reals, so V is pi/4 within the
bound and the test decides it as any constant (MEASURED, specials.py's
diagonal rows equal transcend.py under every attribute).

**The exact-quotient rule, in-lane.** For x > 0, |y| < |x| and k = 0, the
core's s is t = y/x itself, and its remainder N_h - s_h D_h (exact by
FMA) is zero exactly when the quotient is exact; below atan's gate
(s_h < 2^(floor(-(p+3)/2)+1), the definition's 2qv + p + 3 <= 0) the
answer is decided toward zero by one FMA under the attribute, s_h
(1 - 2^-(p+2)), the tiny path's form (M2's sin). Seven instructions.
Above the gate the main path decides an exact quotient like any other
argument: there t^3/3 is more than 2^-(p+G) t, so atan(t) lies farther
than the bound from the boundary t itself, and V resolves it unless
t - t^3/3 is a boundary, which is the tiny family (3.5). Without the rule (the side-rule-off plant) every exact
quotient below the gate whose t^3/3 is under the bound would mark:
atan2(2^-60, 1), atan2(9 2^-60, 3), and every atan2(y, 2^k) with y below
about 2^(k - (p+G)/2).

**The tiny-quotient range, marked.** Where x > 0, |y| < |x| and
t~ < 2^(emin + p + 2), the double word s loses its low word to underflow
(its remainder and low word fall below 2^emin), and the result is
subnormal or within a factor 2^(p+2) of it. The routine marks those lanes
(4 instructions) and the definition decides them. The subnormal MIDPOINT
of 1.3 is one of them: atan2(minSubnormal, 2) is marked, its guess 0 under
every attribute but rup. Deciding them in-lane would take M1's fixed grid
(mathlib.py's `_fixed_grid`): the quotient computed with n and d scaled
apart, the final rounding on the result's own grid, the screen below half
the smallest subnormal (ESTIMATE: about 40 instructions more, a sixth of
atan2's). These lanes are rare: |y/x| below 2^-967 at fp64, below
2^-16268 at fp128 (question 5).

### 2.6 The polynomial

PROPOSED; MEASURED in the model.

**atan(s)/s = sum (-1)^i z^i/(2i+1), z = s^2 <= rho^2 = 1/225,** Taylor,
for M1's and M2's reason: the remainder of an alternating series with
decreasing terms is under its first dropped term, a one-line rigorous
bound. The coefficients are exact rationals rounded once, two words in the
head.

**The head and the tail** (COMPUTED, `m4inv.plan_poly`, exact rationals):
the term |c_i| rho^(2i) is 2^-9.39, 2^-17.94, 2^-26.24, 2^-34.41,
2^-42.51 and 2^-50.56 for i = 1 to 6.
- A term above 2^-(G+3) would carry a single word's rounding into the
  bound, so the double-word head covers i = 0 to 5: K = 6 at G = 44 and
  at G = 46 (fp32's double word at G = 18: K = 3).
- The truncation |c_(D+1)| rho^(2D+2) must be under 2^-(p+G+3): D = 12, 20
  and 35 at fp64, fp128 and fp256 (fp32's double word: 5).
- A head step is M2's: y <- c_i + z y with y and z double words, nine
  instructions (MUL, the product's error by FMA, two FMAs for the cross
  terms, Fast2Sum against the coefficient, ordered since
  |z y_(i+1)| <= rho^2 |c_i|, and two adds).

**s's low word.** z = s_h^2 + 2 s_h s_l (one FMA more than M2's z), and
atan(s) = (s_h + s_l)(P_h + P_l) to a double word: s_l enters exactly to
first order through both, with no derivative correction. (M2 corrected
sin(r_h) by cos(r_h) r_l; here s_l s_h^2, which a correction of s_l alone
would leave out, is u rho^2 = 2^-(p+7.8) of s, past the bound, so it is
carried through z.)

### 2.7 The final rounding, the test, and no clamp

PROPOSED: M1's 3.1 with M2's Bv = 2^-(p+G) |V_h| (V is negative for half
of asin's, atan's and atan2's lanes). R = rnd(V_h + V_l), R1 =
rnd(V_h + RD(V_l - Bv)), R2 = rnd(V_h + RU(V_l + Bv)); a lane with R1 != R2
is marked: its flag word is 0x90 in place of 0x10, one SELECT between two
constant words, since the main path's flags are always exactly inexact
(4). Nine instructions.

**No clamp is needed** (COMPUTED). M2 clamped |sin| and |cos| below 1
because transcend.py decides the half gap below 1 by its side and 1 is
representable. Here no answer has a representable value beside it that
the definition decides by side:
- **acos never crosses zero:** acos(x) for x < 1 is at least
  acos(1 - 2^-p) = 2^((1-p)/2) (1 + ...), 2^(p/2) times Bv and more;
- **atan's and asin's never pass +-pi/2, atan2's never pass +-pi:** those
  are irrational, the true value is strictly inside, and the test is exact
  (the true value's rounding lies between R1 and R2), so an unmarked lane
  rounds as transcend.py does, including to the representable number just
  past pi/2 under rup where the definition gives it too;
- **asin(+-1), acos(-1), atan(+-inf)** are main-path lanes with
  theta0 = 0, decided by 1.4's distances.

### 2.8 fp32

Logan's guard for fp32's library is 40, by a triple word (his answer 2 on
M1's study), and for M2 he asked that the triple word be built and
measured first. **This study builds and measures M4's triple word**
(`m4tw.py`, `twrun.py`), and measures the double word at G = 18 beside it
as the fallback M2 measured.

**The triple word at G = 40** (PROPOSED; MEASURED). p + G = 64 bits, and a
double word at p = 24 floors near 2^-44.7 (M1's 2.5), so every value that
carries the bound has three words:
- **the numerator and the denominator** are exact expansions (TwoProd of
  c with each word, then TwoSum chains), renormalised;
- **the quotient** in three words: q0 = N0 y, the remainder N - q0 D to
  two words (N0 - q0 D0 exactly, by TwoProd of q0 and D0 and Sterbenz,
  since one FMA is exact only where q0 is faithful: 3.6, item 5; q0 D1 by
  TwoProd), q1 from it, the remainder again, q2; 52 instructions;
- **asin's and acos's u** as the exact expansion of the four products of
  the two exact double words, and **w** in three words from two exact
  residuals (u0 - w0^2 with w0^2 by TwoProd; r - 2 w0 w1 with w0 w1 by
  TwoProd, each exact by Sterbenz); 97 instructions with u;
- **the polynomial** (`m4tw.plan_tw`, M1's `plan_exp32` for atan's
  series): K3 = 3 triple-word steps (M1's exp32 step, with z in three
  words), K2 = 3 double-word steps, a tail to degree 8; 186 instructions,
  158 of them the triple-word head;
- **atan(s), the table, pi/2 and pi, theta0 and V** in three words; the
  final rounding through round-to-odd of the low words (M1's
  `_round_to_odd_add`), the test on RO(V1 + V2 -+ Bv).

MEASURED (`twrun.py`):

| fp32, triple word, G = 40 | atan | asin | acos | atan2 |
|---|---|---|---|---|
| instructions | 472 | 637 | 633 | 516 |
| bank words (all four, five attributes: 75) | 60 | 62 | 61 | 69 |
| values live, the design's order | 26 | 26 | 26 | 33 |
| values live, scheduled (mathlib's depth-first order) | 25 | 25 | 25 | 31 |
| TwoSums, Fast2Sums | 22, 31 | 32, 42 | 32, 42 | 22, 31 |
| the pools, five attributes: wrong unmarked | 0 | 0 | 0 | 0 (22 marked, the tiny-quotient range) |
| on seq.py (scheduled), five attributes: differing from the model, from transcend.py | 0, 0 | 0, 0 | 0, 0 | 0, 0 (22 marked) |

**Its error against mpmath** (MEASURED, `twrun.py measure`, rne, 2,000
lanes a region, 3.2's regions; every lane also against transcend.py, 0
wrong; the largest |V - f| / Bv):

| fp32, triple word | random | edge | big | small | diag |
|---|---|---|---|---|---|
| atan | 2^-7.27 | 2^-6.61 | 2^-8.35 | 2^-7.25 | - |
| asin | 2^-4.43 | 2^-4.42 | 2^-7.30 | 2^-4.43 | 2^-8.13 |
| acos | 2^-7.39 | 2^-4.83 | 2^-4.92 | 2^-8.16 | 2^-8.12 |
| atan2 | 2^-6.78 | 2^-6.02 | 2^-8.17 | 2^-5.45 | 2^-7.05 |

The triple word has no budget: the budget's port seeds its reverse sweep
from V_h and V_l, two words, and a third would need its own probe (M1's
fp32 had none either, its 2.5: "fp32 has no budget, so that is a
measurement, a lower bound on the worst, not a bound"). The largest error
found is 2^-4.4 Bv, about four bits under the bound; the box's larger
samples (`box_m4s.sh`, 20,000 a region) are the next lower bound, and an
exhaustive sweep of fp32's 2^32 arguments a function, a box job, would
count every lane.

- **It fits the 32 registers, atan2 by one:** 25 values live scheduled,
  31 for atan2 (whose two inputs, scaling and wider quadrant add six), and
  `routines.program` places every fragment (the on-seq run). It does not
  fit mathlib.py's fp32 cap of 21; question 9 proposes 25 and 31. With 31
  of 32 registers, an atan2 call leaves the program one register across
  it, so the compiler spills around every call (C4's allocator does so
  around any routine); a hand schedule should win back a few.
- **Its cost is 2.4 to 2.9 times the double word's at fp64** (atan 472
  against 176, asin 637 against 221, atan2 516 against 216; COMPUTED), and
  2.8 to 3.5 times fp32's own double word's, more than M1's triple-word
  exp's 2.1:
  the model is generic, as M1's exp32 model was (expansions summed by
  TwoSum chains, a negation by IXOR wherever an error term changes sign),
  and asin's root and atan2's reconstruction are triple-word in full. A
  hand-scheduled routine is cheaper; ESTIMATE, by M1's ratio, about 370 for
  atan and 460 for asin. And one of the three triple-word head steps is
  margin by a sample: in two words it saves 47 instructions a function
  and leaves the edge region's worst at 2^-3.3 Bv (MEASURED, section 8's
  head3-short), not proposed without a budget.
- **The double word at G = 18** (MEASURED, the model's default fp32 until
  this section: `*.fp32-dw18.out.txt`): atan 143, asin 184, acos 180,
  atan2 183 instructions, 44 to 51 words, 15 to 21 live; 0 wrong over the
  pools on the model and on seq.py; the budget's bound at most 0.42 Bv
  (asin's random region, 0.46 with its residual), about one bit, against
  the triple word's largest measured error of 2^-4.4 Bv at G = 40 (a
  measurement, not a budget); a mark rate of about 2^-17.5 a call, one in
  185,000 (M2's 2.7, COMPUTED the same way), against about 2^-39.5 for
  the triple word.

Question 3.

### 2.9 Out of scope: the Pi-variants and the inverse hyperbolics

READ, transcend.py: asinPi, acosPi, atanPi and atan2Pi share these
families (`over_pi`), exact at a larger table (1/2, 1/4, 3/4 and 1), with
neighbour rules beside 1/2 and 1. ESTIMATE: this design's core gives
theta0 in two words, and V/pi needs one double-word product by 1/pi in
two words (about 8 instructions) with C in quarters (exact words); the
exact rows (atanPi(+-1) = +-1/4, asinPi(+-1) = +-1/2, acosPi(-1) = 1, the
axes and diagonals of atan2Pi) must leave the main path, since their V
would sit on a boundary and mark; and the neighbour rules beside 1/2
(atanPi of |x| >= 2^(p+1), acosPi of |x| <= 2^-(p+2), atan2Pi's two
corners) are tiny paths of the tiny-path kind. About 25 instructions more
a function than the radian routine, and their own census (1/2 and 1/4
neighbours). asinh, acosh and atanh are logarithms
(transcend.py's phase 3: log(x + sqrt(x^2 + 1)), log(x + sqrt(x^2 - 1)),
log1p(2x/(1-x))/2), so they are M1's log family with a front end: a
double-word sqrt (2.4's, 36 to 44 instructions), the argument as a double
word into log1p's reduction (M1's log1p takes a double word u = 1 + x
already), and their own cancellation near 0 (asinh, atanh: the tiny paths)
and near 1 (acosh: sqrt(2(x-1)), a product form like 2.4's). ESTIMATE:
log1p's 200 to 230 instructions plus 50 to 70. Question 13.

## 3. The error bound and the in-lane test

### 3.1 The test

PROPOSED: M1's 3.1 with Bv = 2^-(p+G) |V_h|. Every rounding is monotone;
the true value lies in [V - Bv, V + Bv] when the bound holds, so its
rounding lies between R1 and R2, and where they are equal it is R1, and so
are its flags (on the main path always exactly inexact, 4).

**Where the test is not consulted:** the tiny paths of atan and asin,
decided by side as transcend.py decides them; atan2's exact-quotient rule,
the same; the zeros; the NaNs and the arguments outside asin's and acos's
domain; acos(1). **Where the lane is marked whatever the test says:**
atan2's tiny-quotient range (2.5).

### 3.2 The bound, budgeted

MEASURED, by verifier-VM1b's method for M1 as M2 ported it into
`m2budget.py` (M1's 3.2 and M2's 3.2 describe it): over a region's
arguments, the method error M (the twin run in exact arithmetic against
mpmath at 4p + 200 bits: the polynomial's truncation, the constants'
representation, the Newton steps') at its largest, plus each rounding's
largest CAPACITY, |s_i| ulp(v_i)/2. `m4budget.py` is a CHANGED COPY of
`m2budget.py` (that file is not edited): a lane is the routine's inputs,
(y, x) for atan2; the frozen data are this design's (the index's
magic-number FMA, by the fragment's meta; MIN and MAX, whose operands feed
only the index and a seed; every SELECT's condition); M2's reduction phases
frozen whole are gone, since this reduction is a quotient, which is
budgeted; and a SELECT between the words 0 and SIGN is a sign carrier
(sigma), whose IXOR is a negation (3.6, item 3).

The regions (`m4measure.py`'s samplers): **random**, every bit random (atan:
the exponent uniform from the gate to emax, so most lanes are next to
pi/2; asin, acos: |x| < 1; atan2: the operands' exponents within p + 40 of
each other); **edge**, n/d at the table's cells' ends, where |s| is
largest; **big**, atan of |x| >= 2^(p/2), atan2 with a dominant operand,
asin and acos at 1 - j 2^-p and 1 - 2^-e (w small); **small**, atan and
asin from the gate to 1/16, acos from 2^-(p+20), atan2 with x > 0 and
|y/x| from the range's edge to 1/16; **diag**, atan2 within four ulps of
|y| = |x|, asin and acos next to 1/sqrt(2) (the swap). Budgets over 1,000
lanes at fp64 and fp32's double word, 300 at fp128 and fp256, seed 2:

| the budget's bound in Bv (the residual; main lanes) | random | edge | big | small | diag |
|---|---|---|---|---|---|
| fp64 atan | 0.0087 (1.7e-05; 1,000) | 0.0250 (2.4e-03) | 0.0026 (7.0e-12) | 0.0083 (6.5e-07) | - |
| fp64 asin | 0.0582 (5.3e-03) | 0.0578 (7.3e-03) | 0.0111 (1.8e-03) | 0.0357 (5.3e-03) | 0.0108 (8.6e-04) |
| fp64 acos | 0.0122 (2.2e-03) | 0.0467 (4.9e-03) | 0.0462 (7.0e-03) | 0.0033 (5.7e-05) | 0.0126 (8.6e-04) |
| fp64 atan2 | 0.0212 (2.3e-03; 833) | 0.0314 (2.6e-03) | 0.0081 (1.1e-03; 762) | 0.0179 (2.9e-03; 256) | 0.0087 (5.8e-04) |
| fp128 atan | 0.0000 (300) | 0.0302 | 0.0000 | 0.0088 | - |
| fp128 asin | 0.0116 | 0.0302 | 0.0011 | 0.0090 | 0.0048 |
| fp128 acos | 0.0033 | 0.0300 | 0.0005 | 0.0001 | 0.0048 |
| fp128 atan2 | 0.0003 (256) | 0.0300 | 0.0000 (215) | 0.0024 (99) | 0.0048 |
| fp256 atan | 0.0000 (300) | 0.0228 | 0.0000 | 0.0000 | - |
| fp256 asin | 0.0021 | 0.0228 | 0.0000 | 0.0000 | 0.0071 |
| fp256 acos | 0.0000 | 0.0228 | 0.0000 | 0.0000 | 0.0071 |
| fp256 atan2 | 0.0002 (249) | 0.0228 | 0.0000 (224) | 0.0000 (137) | 0.0071 |
| fp32 double word, G = 18, atan | 0.108 (7.7e-03) | 0.163 (2.9e-02) | 0.025 | 0.028 | - |
| fp32 double word, asin | 0.418 (4.1e-02) | 0.399 (5.0e-02) | 0.088 (2.2e-03) | 0.242 (2.8e-02) | 0.084 (4.7e-03) |
| fp32 double word, acos | 0.112 (1.1e-02) | 0.356 (4.1e-02) | 0.322 (7.3e-02) | 0.031 | 0.107 (4.7e-03) |
| fp32 double word, atan2 | 0.154 (1.9e-02; 811) | 0.160 (1.9e-02) | 0.082 (2.2e-02; 760) | 0.117 (2.3e-02; 203) | 0.080 (5.0e-03) |

At fp128 and fp256 every residual is below 4 x 10^-20 Bv and is not shown;
a 0.0000 is under 5 x 10^-5 Bv (the region's V is pi/2 or a small t, where
nothing but the constants' last words is left).

- **Every region keeps more than four bits** at G = 44 at fp64 and G = 46
  at fp128 and fp256 (a bound under 1/16 of Bv): at most 0.058 Bv at fp64
  (asin, random; 0.064 with its residual), 0.030 at fp128 and 0.023 at
  fp256 (the edge regions). M1's planners' line is two bits; M2's sin kept
  0.096 at fp64.
- **What makes the bound.** At fp64 the quotient's roundings lead (the
  remainder's low-word additions and s_l's product, about u^2 relative of
  s, 0.018 Bv in asin's random region), then the reconstruction (0.011),
  asin's root (0.010), atan(s) = s P (0.006) and the tail's first FMA
  (0.004); the head is 0.0005. At fp128 and fp256 every rounding past the
  tail is below 10^-19 Bv, and the bound is the tail's first rounding
  (0.019 Bv at fp256's edge, the term c_6 z^6 rounded in one word) and the
  method error M (the truncation, planned to 2^-(p+G+3)).
- **The residual,** the second-order part, measured beside the bound on
  the same lanes and not bounded: 0.0073 Bv at most at fp64 (asin's edge,
  the quotient's Newton step being quadratic), negligible at fp128 and
  fp256.
- Each bound is a sample's (M1's 3.2, M2's 3.2): the regions are placed
  where the bound binds, and larger budgets, end-weighted, are the lead's
  on amd-arc-box (the handed-back script, section 11).

### 3.3 Measured against it

MEASURED (`m4measure.py`, rne, seed 1; 2,000 lanes a region at fp64 and
fp32's double word, 500 at fp128 and fp256). Each figure is the largest
|V - f(x)| / Bv over the lanes whose answer is the main path's, a lower
bound on the true worst; f is mpmath at 4p + 200 bits. Every lane was also
compared with transcend.py, bits and flag word: 0 wrong unmarked in every
run.

| atan, asin, acos, atan2 | random | edge | big | small | diag |
|---|---|---|---|---|---|
| fp64 | 2^-8.09, -6.50, -7.97, -7.83 | -6.93, -6.91, -6.81, -6.80 | -8.88, -8.57, -6.29, -8.57 | -7.67, -6.50, -8.53, -7.52 | -, -8.95, -8.01, -7.48 |
| fp128 | -69.20, -6.36, -14.08, -8.26 | -5.43, -5.16, -5.22, -5.26 | -68.75, -13.73, -14.19, -67.55 | -7.54, -8.17, -14.08, -6.00 | -, -7.78, -7.78, -10.05 |
| fp256 | -191.06, -7.60, -12.31, -7.62 | -5.55, -5.54, -6.02, -5.59 | -191.98, -15.58, -12.60, -190.89 | -9.50, -9.78, -14.86, -9.31 | -, -7.16, -7.16, -7.16 |
| fp32, double word, G = 18 | -5.22, -3.37, -5.00, -4.41 | -4.23, -3.66, -4.19, -4.34 | -5.85, -5.34, -3.45, -5.90 | -5.95, -3.37, -6.08, -4.53 | -, -5.34, -5.34, -4.68 |

- **The edge region is the worst at fp128 and fp256** (2^-5.2 to -5.6):
  the polynomial's truncation at |s| = 1/15 is planned to 2^-(p+G+3) and
  the constants' and the head's roundings come next; at fp64 the
  single-word tail's first term binds as well.
- **atan's random and big regions at fp128 and fp256** sit at 2^-69 and
  2^-191: V is pi/2 - 1/x with 1/x below every bit the double word keeps,
  so V's only error is pi/2's representation in two words.
- **Thirteen of the 76 cells with a budget of their own pass it**
  (COMPUTED from the outputs: the measured worst, seed 1, against the
  budget's bound, seed 2, on other lanes): eleven at fp256 and two at
  fp128, none at fp64 or fp32's double word, all in the random, small and
  big regions, whose exponents range widely, so that the budget's 300
  lanes did not reach the arguments where the polynomial and the quotient
  bind (fp256's acos small: a budget of 1.6 x 10^-26 Bv from lanes whose V
  is pi/2 less nothing, against 3.4 x 10^-5 measured). The largest is
  fp128's atan2 small, 0.0156 Bv against 0.0024; at fp256, 0.0052. M2's
  study found three such cells; M1's planners' "a sampled worst is only a
  lower bound" runs the other way too: a sampled budget is only a budget
  of its sample.
- **The largest budget at each format bounds every error measured at that
  format** (0.058, 0.030 and 0.023 Bv against 0.0128, 0.0279 and 0.0215 at
  fp64, fp128 and fp256; 0.42 against 0.097 for fp32's double word),
  since the edge regions are where both bind. The box's larger budgets
  (3,000 lanes at fp128 and fp256, `box_m4s.sh`) are the region-by-region
  bound; the study's are not, and section 8, item 3, asks the build for
  end-weighted samples, as M1's were.

### 3.4 How often a lane is marked

COMPUTED, then MEASURED (`rate.py`, M2's on this model: the bound inflated
to G' = 6, random arguments as 3.2's random region, seed 3, 2,000 a
function a format, rne and rtz; M1's constant 2^(0.53 - G') and the sum of
each lane's own 2^-G' sig(V)):

| marked, rne / rtz (each lane's own prediction) | atan | asin | acos | atan2 |
|---|---|---|---|---|
| fp64 | 5 / 7 (49.1) | 35 / 30 (47.1) | 41 / 36 (49.0) | 23 / 23 (40.3) |
| fp128 | 1 / 0 (49.1) | 47 / 43 (46.9) | 49 / 46 (49.0) | 40 / 26 (41.7) |
| fp256 | 0 / 0 (49.1) | 45 / 53 (46.6) | 62 / 62 (49.1) | 41 / 37 (42.2) |
| fp32, double word | 11 / 14 (48.7) | 56 / 44 (46.4) | 39 / 30 (48.8) | 25 / 14 (38.9) |

- Every marked guess was right and no unmarked lane was wrong, in all 32
  cells.
- **Where the values spread, the law holds:** asin's and acos's cells lie
  within 2.7 sigma of their own prediction (fp256's acos +1.9, fp32's acos
  rtz -2.7, fp64's asin rtz -2.5).
- **Where they crowd beside a constant, the law over-predicts.** atan's
  random arguments are mostly huge (the exponent uniform over the range),
  so V is pi/2 less a hair below every bit, and pi/2 lies 5 x 10^12 Bv from
  a boundary (1.4): at G' = 6 that is still 2^4 inflated bounds, so those
  lanes cannot mark, and atan marks 0 to 14 against 49 predicted (-5 to
  -7 sigma). atan2's random pairs crowd the same way next to pi/2 and pi
  where one operand dominates: -2.8 sigma at fp64. The law assumes the
  true value spread evenly in its cell; these are not.
- **At the proposed G** (COMPUTED): about 2^-G x 1.2 to 2^-G x 1.6 a call
  where the values spread (sig(V) averages 1.17 to 1.23 for asin's and
  acos's predictions, (46.6 to 49.1)/2,000 x 64), about 1.3 x 10^-13 at
  fp64 and 3.3 x 10^-14 at fp128 and fp256; less for atan of large
  arguments; the structured families (3.5) on top, and atan2's
  tiny-quotient range.
- **Over the pools** (MEASURED, all 80 configurations): no random lane
  marked; the marks were atan2's tiny-quotient range alone (19, 15, 19 and
  22 lanes a configuration at fp64, fp128, fp256 and fp32's double word).

### 3.5 The structured families

MEASURED (`census.py`), every lane against transcend.py under all five
attributes, every marked guess counted:

| family | fp64 | fp128 | fp256 | fp32, double word |
|---|---|---|---|---|
| tiny atan, c 1..16 (marked rne, rmm / the directed three, each) | 6 / 0 | 10 / 136 | 10 / 446 | 0 / 0 |
| tiny asin, the same | 0 / 6 | 0 / 140 | 0 / 450 | 0 / 0 |
| tiny atan2(c 2^-e x, x), x = 1, 3, 5 2^7 | 18 / 0 | 30 / 408 | 30 / 1,338 | 0 / 0 |
| near pi/2 and pi: atan, acos, atan2(y, -1), 129 about each centre | every lane, its kind's attributes | every lane | every lane | most (2.8) |
| acos(1 - j 2^-p), acos(-1 + j 2^-p), asin(1 - j 2^-p), j 1..64 | 0 | 0 | 0 | 0 |
| atan2(2^k, 1 + j ulp), j 1..40, k = -(p + 10) (directed three) | 11 | 40 | 40 | 3 to 4 (k = -34, -40) |
| the diagonals, atan2(x + j, x), 1,440 | 0 | 0 | 0 | 0 |
| wrong unmarked, in every family | 0 | 0 | 0 | 0 |

- **The tiny family.** atan(x) = x - x^3/3 + x^5/5 ...: where x^3/3 is a
  whole number of x's half-ulps, x - x^3/3 is a boundary and atan(x) lies
  x^5/5 from it, inside the bound while x^4 < 5 2^-(p+G). It is M2's tan's
  family with the other sign: at fp64 one centre, +-3 2^-26 under rne and
  rmm (M2's tan centre), counted three times in the census as 3 2^-26,
  6 2^-27 and 12 2^-28; asin(x) = x + x^3/6 + 3x^5/40 gives one centre,
  +-3 2^-25 under the directed three (MEASURED, the marked lanes listed in
  the ledger). At fp128 and fp256 the census, c <= 16, is a sample of a
  family whose centres run to c of about 2^12 and 2^33 (M2's 3.5's
  counting, COMPUTED for x^3/3 in the same way), as M1's and M2's were.
- **atan2's exact quotients are the tiny family again:** atan2(c 2^-e x, x)
  has t = c 2^-e exactly, so it marks where atan(c 2^-e) marks, at every x
  (18 = 3 x 6 at fp64). Below the gate the in-lane rule decides them
  (2.5), and none marks.
- **The windows next to pi/2 and pi** (1.4). Every one of the 129
  arguments about each centre marks under its kind's attributes (grid
  points: rtz, rdn, rup; midpoints: rne, rmm) and none under the others.
  At fp64 the window about the nearest grid point below pi/2 marks out to
  j = +-1024 and not at +-2048 (COMPUTED half-width about 1,350); at fp128
  and fp256 a window holds about 2^66 to 2^70 and 2^190 to 2^193 arguments
  (`consts.out.txt`, the five nearest boundaries of each): whole windows,
  as M1 found for exp near 0 and M2 for cos near 0. Their centres:
  `census.*-near.out.txt` (fp64's atan at 0x434d02967c31cdb5 and
  0x43349ff16b9c1e3e, acos at +-0x3c91a62633145c07 and
  +-0x3ca8d313198a2e03, atan2(y, -1) at y = +-0x3ca1a62633145c07 and
  +-0x3cb8d313198a2e03, the nearest of each kind). Section 9, question 7.
- **acos near 1, asin near 1:** none. acos(1 - eps) = sqrt(2 eps)(1 +
  eps/12 + ...); sqrt(2 eps) can be a representable number (eps = j^2
  2^-p at odd p), but eps/12 >= 2^-(p+3.6) relative keeps the answer far
  outside the bound (COMPUTED); asin's slope near 1 is 2^((p-1)/2) and
  more, so a window holds less than one argument.
- **atan2's quotient within the bound of a grid point,** division's hard
  cases, found by the specials run (4) before the census: y/x =
  2^k/(1 + j u) = 2^k (1 - j u + j^2 u^2 - ...), with u the ulp of 1,
  lies j^2 u^2 above the grid point 2^k (1 - j u). Where t^3/3 is under
  the bound too (k = -(p + 10) here) the lane marks under the directed
  three while j^2 u^2 < 2^-(p+G), j < 2^((p - G - 2)/2): 11.3 at fp64
  (11 measured), past 40 at fp128 and fp256, 2 at fp32's G = 18 (3 to 4
  measured, rup one more: its boundary is the grid point above). Where
  t^3/3 is past the bound (k = -10, -40 at fp64) the cubic moves the true
  value off the boundary and nothing marks. These inherit division's hard
  cases, as the brief said they would: the family is two-parameter (any
  y with few bits against any x next to a power of two), not a list of
  centres.
- **The diagonals and the axes themselves** mark none (1.4).

Section 9, question 7, asks to keep these marks, as M1's question 4 and
M2's question 7 did.

### 3.6 What the model found wrong in itself

MEASURED, each in the round's ledger; every run this study cites was made
after the fix it needed:
1. **The Sterbenz check's cushion.** `m4inv.rho_of` asserted t/c < 2 with
   t up to 1 + 2^-20 in the top cell, so N = 2 failed the check (t/c =
   2.0000019). n_h <= d_h by the selection, so the top cell's ratio is at
   most 1/c, exactly 2 at N = 2, which Sterbenz allows. Fixed; no default
   fragment changed (rho and the plan are computed from the cell's own
   ends, unchanged).
2. **The specials' row for maxN / (0.9 maxN)** was first written with a
   garbled argument; caught before any run.
3. **The budget's sign word.** `m4budget.py`'s Analyzer took sigma, a
   SELECT between the words SIGN and 0, as a continuous value, so the IXOR
   applying it looked like data and froze every rounding before the
   reconstruction into the method error M: M became the sampled worst of
   those roundings, not a budget. The tell was a second-order residual of
   exactly 0 in every region and zero capacity in every phase but the
   reconstruction (the first outputs, set aside, not cited). M2's sign
   words were built by integer shifts and never met this. Fixed: a SELECT
   between two sign words is a sign carrier. After the fix asin's fp64
   edge budget went from "0.0143 Bv" (a sampled M) to 0.047 Bv with a
   residual of 0.007 (300 lanes). M4's build ports the budget with this
   rule, and its test is a region whose capacity in the head is nonzero.
4. **The model's path put M2's directory first.** `m4core.py` inserted
   `docs/studies/m2/` at the head of Python's path, and M2 has scripts
   named as this model's (census.py, specials.py, rate.py): the first
   plants run imported M2's census and failed by name. Only plants.py
   imports a neighbour (MEASURED, by search), so no other run was touched;
   M2's directory now goes last. The second plants run failed on a format
   string, and the triple word's plants later on another in `twrun.py`;
   each output set aside, not cited.
5. **fp32's triple word passed the pools while breaking its bound.** Its
   first version was 0 wrong over the pools at every function and
   attribute, and on seq.py, but its errors against mpmath reached
   2^17 Bv for asin, acos and atan2 (about 2^-47 relative: a double word's
   accuracy), with atan's at 2^-6.6. Three causes, all of one kind: asin's
   and acos's numerator cut to two words; and the quotient's first
   remainder N0 - q0 D0, and the root's u0 - w0^2, each one FMA, exact only
   where q0 (w0) is faithful, while a single-word reciprocal can leave it
   two ulps off. At the double word's formats that costs 2^-2p of the
   value, 2^-106 at fp64, under the bound; at fp32 it is 2^-48, past it.
   Fixed (N in three words; both residuals exact by TwoProd and Sterbenz,
   two instructions each), and every triple-word run cited was made after
   the fix (the first outputs set aside). The pools cannot see a broken
   bound, only a wrong lane; the error against the reference is the test
   that saw it, which is why section 8's item 3 is there. M4's build ports
   the triple word with these residuals and holds its bound with a region
   of asin near 1/sqrt(2).
6. **A fault argued away.** The first plant list had "sqrt-product",
   1 - x^2 formed directly. I then reasoned that 1 - RN(x^2) by Fast2Sum
   plus x^2's exact TwoProd error is exactly 1 - x^2, so no fault, and a
   plant must be one: it became `u_form="direct"`, an alternative, and a
   plant dropping u's low word took its place. Measured (`uform.py`, 2.4)
   it passes every pool at every format and attribute and misses the
   bound by up to 2^(G-6), 2.7 x 10^11 Bv at fp64: the pair is exact but
   not normalised, and the root's one residual step needs it normalised.
   It is a plant again, sqrt-product, red in the bound check alone, beside
   u-low-dropped. Exactness is an argument about a sum; the bound is a
   measurement of a routine, and only the second was evidence.
7. **A real fault no check saw.** The plant sterbenz-bias (k chosen
   without the 63/64 bias) was red in nothing in its first run: pools,
   structured lanes, placed points and specials all passed, its largest
   placed error 2^-7.2 Bv. I first read the seed table at its cell 0
   only, where the seed is below 1 and n_h and P - n_h share a binade, and
   concluded that the failure the bias guards against is allowed by the
   seed's documented bound but not reached by its actual table. That was
   wrong, and was disproved before it was written anywhere: at the top
   cell, d near 2, the seed's overestimate puts a power of two between
   n_h and P - n_h (2.2), and at d = 2 - 2^-12, n = 1/8 - 2^-15 - ulp the
   planted atan2 is wrong and unmarked at every format and under rne and
   rtz (MEASURED, a probe: 2^44 Bv at fp64, 2^46 at fp128 and fp256, 2^18
   at fp32's double word), the unplanted fragment right on the same
   lanes. The lanes need d's significand within 2^-11 of 2 and n within
   about 2^-11 below d/16, which no sampler reaches. Section 8's item 2,
   the audit, was written for this: each lane's n_h/P against [1/2, 2] and
   n_h - P against its exact value, on lanes placed at both ends of d's
   binade and at the cells' ends, each lane also against transcend.py; it
   turns the plant red (8's table: the premise broken on 86 of 214 lanes,
   the difference inexact on 24, 23 answers wrong). A plant red in nothing
   is either no fault or a hole in the checks; this one was a hole, and the
   pools' 0 wrong said nothing about it.
8. **The batch logs' exit codes are date's.** `queue.sh` wrote each end
   line as `"$(date ...) end $out rc=$?"`, and the command substitution
   runs first and resets `$?` to date's 0 (MEASURED in bash and sh: after
   `false`, that string gives rc=0, and rc=1 with `$?` before `$(date)`).
   So every job in `queue1.log` to `queue9.log` reads rc=0, the two
   triple-word plants runs that crashed included (their tracebacks are in
   the outputs set aside). No figure here was read from an rc: every one
   is from its output, and every output cited was read. Fixed after queue
   9 (the rc taken before the date; a failing job then logs rc=2), the
   logs kept as captured, and `box_m4s.sh`'s end line fixed the same way
   before it is run. M2's `box_m2s.sh` has the same line, so its log's
   "end (0)" for all 49 jobs carries no information; its 49 outputs hold
   no traceback or error (READ), and the case is the lead's.

## 4. The specials and the flags

PROPOSED, and MEASURED equal to transcend.py, bits and flag word, row by
row (`specials.py`: each row under all five attributes, at fp64, fp128,
fp256 and fp32's double word), and over the pools (3.4). Rows in the
routine's order of priority, highest first; "main" is sections 2.1 to 2.7.
The gates are |x| < 2^-27 for atan and asin at fp64, 2^-57 at fp128,
2^-119 at fp256 (atan's and asin's coincide there; at fp32 atan's is 2^-13
and asin's 2^-12).

**atan:**

| operand | result | flags |
|---|---|---|
| NaN | the canonical quiet NaN | invalid if signalling |
| +-0 | the operand | none |
| \|x\| below the gate, subnormals included | x (1 - 2^-(p+2)) rounded once: x, or its neighbour toward zero under rtz and the attribute toward zero | inexact; + underflow where the result is below 2^emin |
| +-inf | +-pi/2 rounded (main, theta0 forced to 0) | inexact |
| main | R | inexact; + 0x80 where marked |

**asin:**

| operand | result | flags |
|---|---|---|
| NaN | the quiet NaN | invalid if signalling |
| \|x\| > 1, +-inf | the quiet NaN | invalid |
| +-0 | the operand | none |
| \|x\| below the gate | x (1 + 2^-(p+2)) rounded once: x, or its neighbour away from zero under the attribute away from zero | inexact; + underflow where \|x\| is below 2^emin |
| +-1 | +-pi/2 rounded (main: w = 0 exactly, theta0 = 0) | inexact |
| main | R | inexact; + 0x80 |

**acos:**

| operand | result | flags |
|---|---|---|
| NaN | the quiet NaN | invalid if signalling |
| \|x\| > 1, +-inf | the quiet NaN | invalid |
| +1 | +0 | none |
| -1, +-0 | pi, pi/2 rounded (main) | inexact |
| main | R | inexact; + 0x80 |

**atan2(y, x):**

| operands | result | flags |
|---|---|---|
| either a NaN | the quiet NaN | invalid if either signals |
| y = +-0 and x >= +0 (+0 included); finite y and x = +inf | y's signed zero | none |
| y = +-0 and x <= -0 (-0 included); finite y and x = -inf | +-pi rounded (main, theta0 = 0, C = pi) | inexact |
| x = +-0, y finite nonzero; y = +-inf, x finite | +-pi/2 rounded (main) | inexact |
| y = +-inf, x = +inf; x = -inf | +-pi/4, +-3pi/4 rounded (main, theta0 = pi/4) | inexact |
| x > 0, \|y\| < \|x\|, \|y/x\| below 2^(emin+p+2) (the tiny-quotient range) | the main path's guess | inexact, marked |
| x > 0, \|y\| < \|x\|, y/x exact and below atan's gate | y/x (1 - 2^-(p+2)) rounded once | inexact |
| main, the diagonals included | R | inexact; + 0x80 |

**The tiny paths are one FMA under the program's attribute,** as M2's
(its 4): the value x 2^-(p+2) from x lies strictly inside the half gap
transcend.py's witness names. Underflow is tininess after rounding: for
atan, the result below 2^emin (minNormal under rtz becomes the largest
subnormal and underflows; under rne it stays and does not); for asin, the
argument below 2^emin (the largest subnormal under rup becomes minNormal
and still underflows), as M2's sin and tan.

**MEASURED, the specials run** (`specials.*.out.txt`): atan's 19 rows, 95
lane-attributes, all equal; asin's and acos's 23 rows, 115 each, all
equal; atan2's 76 rows (the 9.2.1 grid of y in {+-0, +-1, +-inf, minSub}
against x in {+-0, +-1, +-inf, maxN}, the NaNs, the diagonals, the exact
quotients at, past and below the gate and against x < 0, a quotient one
ulp off, both operands subnormal, maxN against 0.9 maxN): 337 equal and
43 marked at fp64 and fp32's double word, 340 and 40 at fp128 and fp256,
0 wrong. Every mark is a tiny-quotient-range row (y = +-1 or minSub
against maxN, minSub against 1 and 2, 2^emin against 2^p) or the row
atan2(2^-60, 1 + ulp) under the directed three (3.5's hard case).

**The flag word** is a SELECT chain of constant words, so C4's own walk
(`routines.flag_words`) proves its values (MEASURED, `costs.py`, all 80):
{0x0, invalid, inexact, underflow|inexact, inexact|0x80} for atan and
asin, the same without underflow for acos and atan2. Within mathlib.py's
FLAG_WORDS; never bits [6:5]. The main path raises exactly inexact: no
main-path result is below 2^emin (atan2's below 2^(emin+p+2) are marked,
and every other function's result is at least about |x| or pi/4) and none
overflows (every result is at most pi).

## 5. The cost

### 5.1 Measured

MEASURED (`costs.py`; the fragment's body; inlined, a call adds QUIET,
ENDQUIET and RAISE, 3 more; every attribute gives the same counts):

| | fp32, double word (G = 18) | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| atan | 143 | 176 | 186 | 203 |
| asin | 184 | 221 | 235 | 256 |
| acos | 180 | 217 | 231 | 252 |
| atan2 | 183 | 216 | 226 | 243 |
| asin and acos of one argument, shared | - | 255 | 269 | 290 |
| bank words, a function | 44-51 | 54-61 | 62-69 | 77-84 |
| bank words, all four, five attributes | 57 | 66 | 74 | 89 |
| most values live, the design's order | 15, 16, 16, 21 | 15, 16, 16, 21 | the same | the same |
| most values live, the better of it and mathlib's depth-first order | 15, 16, 16, 19 | 15, 16, 16, 19 | the same | the same |
| scratch slots | 0 | 0 | 0 | 0 |

**fp32's triple word at G = 40** (2.8; MEASURED, `twrun.py costs`): atan
472, asin 637, acos 633 and atan2 516 instructions; 60 to 69 words a
function, 75 for all four under all five attributes; 26, 26, 26 and 33
values live in the design's order and 25, 25, 25 and 31 scheduled; no
scratch slot. asin and acos of one argument share their core here too
(not measured at fp32; the same keying applies).

**Against M2's** (its 5.1): sin is 406, 382 and 389 at fp64, fp128 and
fp256, most of it the Payne-Hanek reduction (206, 168, 155); the inverse
functions' reduction is the index and one quotient (30 to 34 instructions)
and asin's root (36 to 44), so they cost about half of sin.

### 5.2 Live values, and the proposed caps

MEASURED (`sched.py`, `sched.out.txt`): in the design's order atan keeps
15 values live, asin and acos 16, atan2 21, at every format and attribute;
mathlib's depth-first order (the second candidate of `schedule_order`,
which M1's build uses) gives 16, 20, 20 and 19. The better of the two is
15, 16, 16 and 19, and the invariants hold on both. PROPOSED caps
(routines.LIVE_CAP, per function and format, M2's answer 9's form):

| | fp32 | fp64 | fp128 | fp256 |
|---|---|---|---|---|
| atan | 25 (the triple word) | 15 | 15 | 15 |
| asin, acos | 25 | 16 | 16 | 16 |
| atan2 | 31 | 19 | 19 | 19 |

At the double word's formats every one is past mathlib.py's 13; against
the caps Logan approved for M2's functions (22, 26, 17 and 16 at fp32,
fp64, fp128 and fp256), atan, asin and acos are within them at fp64, fp128
and fp256, atan2's 19 is past them at fp128 and fp256, and fp32's triple
word, 25 and 31, is past both mathlib.py's 21 and M2's 22 (COMPUTED).

### 5.3 What C4's invariants need widened further

READ, `routines.invariants` and `routines.MATH_CONTRACT`, against the
fragments (MEASURED: `mathlib.invariants` holds on all 80 with no live
cap):
- **the live caps** above, by function and format;
- **two inputs for a math routine:** `routines.INPUTS` gives ("a", "b")
  to division only; atan2 is the first two-operand routine of the six's
  contract, and `routines.ROUTINES`, `INPUTS` and `GOLDEN` (transcend.
  compute with its second operand) need its entry; cftc's call loop takes
  a binary routine as it takes division;
- **MIN and MAX inside a routine:** M2's clamp introduced them; M4 uses
  MIN for the index and MAX for the root's seed. The build checks that
  cftc's emitter and internal check accept them as any instruction;
- **RSQRT_SEED in a math routine:** C4's root routine has it already;
- nothing else: the mark, RDN, RUP and the program's attribute are M1's
  widening, already in `MATH_CONTRACT`.

### 5.4 The alternatives

- **The table's size,** measured in 2.3: N = 8 is the cheapest.
- **Separate cores** (ESTIMATE): atan alone could skip atan2's scaling
  and quadrant (about 25 instructions), but the four functions' core
  instructions are one already; a separate asin/acos core would lose the
  sharing of 2.1 (255 together against 438 apart at fp64).
- **Two quotients** (t, then (t - c)/(1 + t c)): ESTIMATE 20 instructions
  more, for nothing, since t is never needed beyond its first bits.
- **Augmented addition, once every image carries R21** (COMPUTED from the
  counts, `costs.py`): atan holds 12 Fast2Sums and no TwoSum at every
  format, asin and acos 14 and one; augerr and augadd split a sum in 2
  instructions against 3 and 6, which saves 12 (atan) to 18 (asin) a call,
  about 7%.
- **atan2's tiny quotients decided in-lane** (2.5): ESTIMATE about 40
  instructions; question 5.
- **asin's and acos's 1 - x^2 directly, then one Fast2Sum** (MEASURED,
  2.4): 2 instructions fewer than the product form (219 and 215 at fp64),
  the same largest errors at every format over the same lanes; not
  proposed only because every other measurement here is of the product
  form. Without the Fast2Sum it is a fault (the plant sqrt-product).
- **fp32's triple word with one head step fewer** (MEASURED, 8): 47
  instructions a function, the sampled worst 2^-3.3 Bv; for the build,
  after a budget.

## 6. The language and the compiler

PROPOSED, in C4's, L4's, M1's and M2's pattern (M1's section 6 has the
machinery; this says what M4 adds).

**The nodes.** `atan(a)`, `asin(a)`, `acos(a)` and `atan2(a, b)`, each
with operands that are not all constants:
- each becomes a node of the step graph named as transcend.py names the
  function, its golden function transcend.atan, asin, acos, atan2 (bits
  and flags); the interpreter's operation table and the step graph's
  operation list gain four entries;
- **atan2 is the first built-in transcendental of two operands,** y first
  (C's order and transcend.py's); its arity in `lang/check.py`'s BUILTINS
  is 2, beside copysign's, min's and max's; a call with one argument is
  refused as any wrong arity is ("takes 2 arguments, 1 is given");
- `transcendental` stops being raised for the four; the names are already
  reserved (`lang/check.py`, TRANSCENDENTAL).

**What folds and what is refused** (M1's question 8 and M2's answer 8
applied; PROPOSED):
- **fold the exact rational cases:** atan(0) = 0, asin(0) = 0, acos(1) = 0,
  and atan2(0, c) = 0 for a constant c >= 0 (c = 0 included: atan2(+0,
  +0) = +0; a constant is an exact rational with no signed zero, so its 0
  is +0) - the only exact radian values (Hermite-Lindemann, 1.3);
- **irrational-constant** for every other constant argument: atan(1)
  (pi/4), asin(1/2), acos(0) (pi/2), atan2(1, 1), atan2(0, -1) (pi) and
  atan2(c, 0) for c != 0 (pi/2) are irrational, and the language carries
  no pi;
- **a constant outside the domain, asin(2) or acos(-3/2):**
  `irrational-constant`, its sentence saying "not a real number", as
  `log(-4)` is today (LANGUAGE.md's row: "one of the six of a constant
  whose value is irrational or not real ... `irrational-constant`"), and
  as sqrt(-4) is; no new refusal name;
- **atan2 of a constant and a non-constant** is a node like any other: a
  constant operand is a bank constant;
- a function of h that changes with h's size is `h-nonlinear`, as
  `sqrt(h)` is.

**cftc** (`python/cftc`):
- `ir.ROUTINES` and `routines.ROUTINES` gain atan, asin, acos (arity 1)
  and atan2 (arity 2), each carried by its fragment from the golden
  generator (question 11), bound to the node's operands, QUIET to
  ENDQUIET, then RAISE;
- the words are routine bank slots by bit pattern: 66, 74 and 89 for all
  four functions at fp64, fp128 and fp256 (5.1);
- **sharing:** the inliner's hash-consing already makes asin and acos of
  one operand share everything up to the quadrant's constant (2.1);
  nothing new is needed;
- the internal check holds each instance to its fragment under the
  widened invariants (5.3);
- the call loop takes a unary routine as it takes sqrt, and atan2 as it
  takes division.

**Targets** (READ, `python/cftc/targets.py`): revision 7's targets, the
round-2 images and open-core refuse an image with these routines
`target-feature`, for lack of FLAG_CONTROL, as they refuse C4's, M1's and
M2's; the software targets and revision 8's three compile them. No scratch
slot is used.

**Versions** (READ: cftc's VERSION and the language's version as M1's and
M2's builds step them): M2's build takes cftc's output version from 6 to 7
and the language to 1.2; M4's build steps each once more, 7 to 8 and 1.2
to 1.3, unless it lands with M2's and shares the step. The certificate
corpus is made again as each step remakes it. The language's step is
minor: names it refused only for not computing them, and no accepted
source changes.

**The interpreter needs mpmath** for these nodes, as for M1's and M2's (M1's
question 10, accepted); an auditor without it refuses
`definition-unavailable`.

**A marked lane** in the language's checks is replayed by the definition
and its guess compared only as a guess (M1's section 6).

## 7. The derivative rules

PROPOSED, in LANGUAGE.md's form ("The rules"; "The quotient and the
root"): each rule an expression in the language, its roundings fixed,
every point where the operation is not differentiable given its value.

| operation | its tangent | where a tangent is zero | where it is not differentiable |
|---|---|---|---|
| `atan(a)` | `da / fma(a, a, 1)` | zero | - (at +-inf, fma(a, a, 1) is +inf and the tangent +-0, the limit) |
| `asin(a)` | `da / sqrt(fma(-a, a, 1))` | zero | at a = +-1, da / +0: an infinity with divideByZero, or a NaN with invalid where da is +-0; past +-1 the root is a NaN, and so is the tangent |
| `acos(a)` | `da / (-sqrt(fma(-a, a, 1)))` | zero | as asin's, with the other sign |
| `atan2(a, b)` | `fma(b, da, -(a * db)) / fma(b, b, a * a)` | `(b * da) / fma(b, b, a * a)`; or `(-(a * db)) / fma(b, b, a * a)` | at the origin, 0/0: a NaN with invalid; see "magnitudes" |

**Rounding order and form.**
- **atan:** 1 + a^2 by one FMA, primal-only and shared across vectors,
  then one division a vector: two roundings, the fewest. The division
  routine a vector is the language's own pattern for the quotient's, the
  root's and the logarithms' rules (`da / b`, `da / (2 * r)`, `da / a`).
  `(1 / fma(a, a, 1)) * da` would spend one division a step and a MUL a
  vector, for a third rounding: the alternative, if a workload's tangent
  vectors are many.
- **asin and acos: 1 - a^2 as fma(-a, a, 1), not (1 - a)(1 + a).** The FMA
  forms 1 - a^2 exactly and rounds once, so it does not cancel near
  |a| = 1 (the cancellation the product form exists for is that of a
  ROUNDED a^2): one rounding against the product form's two (1 + a
  rounds, the product rounds; 1 - a is exact only for |a| >= 1/2). Then
  the root (C4's routine) and the negation, primal-only and shared, and
  one division a vector: three roundings. acos negates the root, not the
  quotient: `-(da / r)` rounds before negating, which differs under rdn
  and rup (M2's cos rule made the same choice).
- **atan2:** the numerator b da - a db is a sum with one product, so one
  FMA rounds it with one product's rounding before it (two roundings),
  as the product's rule rounds its sum; the denominator b^2 + a^2 the
  same, primal-only and shared; then one division a vector. The
  quotient's rule (`fma(-r, db, da) / b`) reads its own result; atan2's
  derivative has no such form, since r = atan2(a, b) is an angle.

**Magnitudes** (COMPUTED): fma(b, b, a * a) overflows where
max(|a|, |b|) passes about 2^(emax/2) (2^511.5 at fp64) and underflows
where both are below about 2^(emin/2): the tangent is then 0 (the true one
being about 1/max(|a|,|b|) times the tangents) or an infinity with
divideByZero (the true one huge but finite). A scaled form, dividing both
by the larger magnitude, would need the language to scale by a power of
two, which it cannot (no ldexp or logb): it costs two divisions and two
roundings more. PROPOSED: the direct form, the range limits stated in
LANGUAGE.md as the quotient's are, and the scaled form left to a workload
that needs it (question 10).

**Cost** (MEASURED, `share.py`): acos's tangent beside asin's costs the
primal 34 instructions of acos, not 217; their rules share
sqrt(fma(-a, a, 1)) and its negation, so each costs a vector one division.

**How it is held:** the rule table to the code, each rule rendered on a
one-operation system; the tangent stage's fourth check by a central
difference in high precision (M1's question 10, accepted); and a committed
compiled variational reference. PROPOSED: **the phase follower**,
d/dt c = -(w * s), d/dt s = w * c, d/dt phi = k * (atan2(s, c) - phi),
d/dt q = asin(q / 2) - atan(q) and d/dt v = acos(v / 2) - v, under rk4
with a tangent vector: atan2 of two state components (both operands
differentiated), and each unary function of a state component. The run
is chosen so that the oscillator's angle stays inside (-pi, pi), w T < pi,
since atan2's primal jumps at the negative axis (the tangent rule is
continuous there and a central difference across the jump is not); LANGUAGE.md
already measures atan2(s, c) on that oscillator ("Drift otherwise"). A rule
rounded otherwise must move its bytes.

## 8. How it will be held

PROPOSED, for M4's build, M1's and M2's section 8 item for item; agents
run the quick tests and the long runs are the lead's.

1. **Each fragment on seq.py against transcend.py,** as a stand-alone
   program through `routines.program` and `routines.run` (atan2 with y in
   r0 and x in r1), over the stage's trig pool and atan2 pairs, the vector
   sets' and test_transcend's brute pool, at every format and attribute:
   every unmarked lane equal in bits AND flag word, every marked lane
   replayed and its guess counted. MEASURED as a probe (`onseq.py`): all
   80 configurations at fp32's double word, fp64, fp128 and fp256, 0 lanes
   differing from the model and 0 unmarked lanes differing from
   transcend.py.
2. **The index's exactness,** per lane: n_h/P in [1/2, 2], Sterbenz's
   premise, and n_h - P equal to its exact value (an audit of the one
   instruction the design calls exact by Sterbenz, as M2 audits its
   reduction), and each lane against transcend.py, over lanes placed where
   a seed's overestimate meets k = 1 just below t = 1/16: d in the upper
   half of the seed's cell 0 (the premise breaks there unbiased, the
   difference stays exact), d = 2 - 2^-e at its top cell with n's last bit
   set (both break), and the cells' ends by `cells()`, both sides of each;
   at every format, and in asin and acos through their n and d. MEASURED
   as a probe (`plants.py`'s audit, atan2 at fp64, 214 lanes): the control
   passes it, and the sterbenz-bias plant, which no other check saw, turns
   it red (3.6, item 7). The seed's table is the tree's; if it ever
   changes, this audit is what notices.
3. **The bound, against an independent reference,** mpmath at 4p + 200
   bits (MPFR where the stage has it), at each region's own worst points
   (3.2's five); |V - f| / Bv under 1, the margins stated by the budget's
   bound, the sampled worst only as the lower bound it is. Budgets over
   larger samples, end-weighted as M1's were, are the lead's on
   amd-arc-box.
4. **The mark-rate law** with the bound inflated, by each lane's own
   2^-G' sig(V), over arguments whose values spread (asin, acos; atan2 and
   atan below their constants), every unmarked lane right and every
   marked guess right.
5. **The structured families as a committed list:** 3.5's centres and
   windows at every format by function and attribute, each with
   neighbours inside and outside; atan2's tiny-quotient range by its edge;
   atan2's quotient-near-a-grid-point family by its j threshold. A mark in
   the pools off the list fails the test (E1's rule).
6. **The constants** re-derived with a `--check`, as mathlib.py's are:
   pi/2, pi/4 and pi in two words (three at fp32) against an independent
   derivation (test_mp_consts.py's Chudnovsky series is one), atan(k/8) in
   two words against an independent series (atan of a rational by
   Machin-like integer arithmetic), the Taylor coefficients, the gates, the
   index's 7.875 and its MIN, the scaling words.
7. **atan2's 9.2.1 table** row by row, both signs of every zero, at every
   format and attribute (specials.py's rows), and the exact-quotient rule
   at the gate, one below it and one above, and with x < 0.
8. **program.c bit for bit** through `host/tests/seq_check.py`'s corpora;
   no new C.
9. **The language's checks:** the lang-routines stage with sources using
   the four functions, the tangent stage's rules, the committed reference
   (7), test_lang.py's refusal table (asin(2), atan(1), atan2(0, -1)).
10. **The card later:** STATUS[6] and the lane byte on a structured
    argument (atan(3 2^-26) under rne at fp64), and the acceptance set's
    inverse trigonometric case.

**The plants,** each in a fresh fragment and each red in a named case
(`plants.py`, MEASURED at fp64). Its checks: **pools**, the unary pool and
atan2's pairs under rne and rtz for all four functions, red on a wrong
unmarked lane or on a mark the unplanted fragment does not make there;
**structured**, the lanes the unplanted fragment marks among candidates
(the fp64 tiny centres, atan2(2^-40, 1 + j ulp), the windows' centres),
red where one is left unmarked; **bound**, |V - f| / Bv past 1 over
placed points (the edge, small and big regions, 48 a function each),
mpmath at 4p + 200 bits; **specials**, every row of 4 under all five
attributes, red on a wrong unmarked lane; **audit**, item 2's 214 lanes,
red on a broken premise, an inexact n_h - P or a wrong unmarked answer.
The control (no plant) is red in nothing, its largest placed error
2^-6.7 Bv; it marks 38 pool lanes (atan2's range) and 35 of 820
structured candidates.

| plant | the fault | red in | the first named case of each (fp64) |
|---|---|---|---|
| table-entry | atan(3/8)'s high word one ulp off | pools, bound, specials, audit | atan rne 3/8 - ulp (0x3fd7ffffffffffff) wrong; 2^42.7 Bv; atan2 "subnormal both, minSub / 3 minSub" wrong; 10 audit lanes wrong |
| coef | the z^1 coefficient without its low word | bound | atan 2^28.2 Bv (largest 2^33.5) |
| newton-short | the quotient's reciprocal one Newton step short | structured, bound, specials | asin rtz 3 2^-25 unmarked and wrong; atan 2^3.3 Bv; atan2 rtz "one ulp off, divisor 1 + ulp" wrong |
| sterbenz-bias | k chosen without the 63/64 bias | audit | of 214 lanes the premise broken on 86, n_h - P inexact on 24, 23 answers wrong |
| zl-dropped | z's low word left out of the head | bound | atan 2^27.1 Bv (largest 2^35.2) |
| sl-dropped | s's low word left out of atan(s) = s P | pools, structured, bound, specials, audit | atan rtz 5 + ulp wrong; asin rtz 3 2^-25 unmarked and wrong; 2^36.3 Bv; asin rtz "gate 2^-27" wrong |
| pio2-low | pi/2's low word dropped | pools, structured, bound, specials | atan rne 1.25 + ulp wrong; atan rtz two ulps from a window's centre next to pi/2 unmarked; 2^42.8 Bv; atan rtz "2^55" wrong |
| bound-loose | the in-lane bound 2^40 too small | structured, bound | asin rtz 3 2^-25 unmarked; 2^28.9 Bv |
| mark-silenced | the flag word never carries the mark | structured | asin rtz 3 2^-25 unmarked |
| tiny-gate-off | no tiny path | pools, specials | atan rne minSub wrong; "+minSub" wrong |
| tiny-side | the tiny path on the wrong side | pools, specials | atan rtz minSub wrong; "+minSub" wrong |
| domain-edge | \|x\| > 1 tested as \|x\| >= 1 | pools, specials | asin rne 1 wrong; "+1" wrong |
| signed-zero | atan2(+-0, -0) answered +-0, not +-pi | pools, specials | atan2 rne (+0, -0) wrong; "9.2.1 y +0, x -0" wrong |
| side-rule-off | the exact-quotient rule not applied | pools | atan2 rtz (2^-60, 1) marked off the list |
| side-rule-sign | the rule's FMA rounded away from zero | pools, specials | atan2 rtz (2^-60, 1) wrong; "exact quotient 2^-60 / 1" wrong |
| range-off | the tiny-quotient range not marked | pools, specials | atan2 rne (1, maxN) wrong; "9.2.1 y +1, x +maxN" wrong |
| u-low-dropped | u's low word left out of the root's residual | pools, bound, specials | asin rne 3 2^-27 wrong; 2^40.1 Bv; asin rtz "gate 2^-27" wrong |
| sqrt-product | 1 - x^2 formed directly (2.4) | bound | asin 2^1.8 Bv (largest 2^24.0) |
| quadrant | sigma from the swap alone, x's sign ignored | pools, bound, specials | atan2 rne (1, -1) wrong; 2^93.4 Bv; "9.2.1 y +1, x -1" wrong |

The brief's five: the 9.2.1 signed zeros (signed-zero), the exact-quotient
rule (side-rule-off, side-rule-sign), the tiny gates (tiny-gate-off,
tiny-side), the domain edge at +-1 (domain-edge) and the mark
(mark-silenced, bound-loose). The bit patterns of every case are in
`plants.fp64.out.txt`.

- **Every check is the only one to see some plant:** the pools alone see
  side-rule-off (a mark off the list, every answer right); the structured
  lanes alone see mark-silenced; the bound alone sees coef, zl-dropped and
  sqrt-product, accuracy faults far under the last bit that no pool lane
  reached; the audit alone sees sterbenz-bias. The specials are never alone
  at fp64 but name the 9.2.1 and gate rows by label.
- **fp32's triple word** (`twrun.py plants`; the pools under rne and the
  bound over the edge region, 200 lanes a function): the control is red in
  nothing (largest 2^-6.11 Bv); q2-dropped (the quotient's third word) red
  in the bound, 2^17.6 Bv; w2-dropped (the root's third word) 2^17.3;
  z2-dropped (2 s_0 s_2 left out of z's third word) 2^6.3; head3-two (two
  of the three planned triple-word head steps in two words) 2^6.7.
  **head3-short, one step, is red in nothing:** its largest error, 2^-3.32
  Bv, is inside the bound, so that step is margin and not need (`plan_tw`
  keeps two bits a word, M1's planner's rule). It is kept in the run as a
  measurement of that margin and is not counted as a plant; the build's
  planner may take the step back after a budget (MEASURED: 47
  instructions a function, atan 472 to 425; the error is a sample's, not a
  budget's, so the step is not proposed away here).

## 9. Questions for Logan, each with a recommendation

1. **One core for the four functions.** Every function is
   sign (C + sigma atan(n/d)) with 0 <= n <= d (2.1), and the four share
   the index, the quotient, the polynomial and the table instruction for
   instruction; asin and acos of one argument share their front end too
   (255 together against 438 apart at fp64). *Recommended: one core, the
   four as front ends,* as transcend.py's definitions all reduce to atan2.
2. **The reduction: a table of N = 8 and one quotient.** c = k/8 with k
   from RECIP_SEED's 8.5 bits and the 63/64 bias that keeps n_h - c d_h
   exact; s = (n - c d)/(d + c n), one double-word quotient (M2's tan
   quotient); |s| <= 1/15. Measured against N = 2, 4 and 16, N = 8 is the
   cheapest at every format (2.3); halving through a root and a longer
   polynomial cost more. *Recommended: N = 8, the SELECT tree, as M1's
   question 3 chose for exp's table.*
3. **fp32.** Logan's answer on M1's study binds the triple word at
   G = 40, and it is built and measured here (2.8): atan 472, asin 637,
   acos 633 and atan2 516 instructions, 75 words for all four; 25 values
   live scheduled, 31 for atan2, **whose 33 in the design's order do not
   fit the 32 registers**, so atan2 needs the depth-first schedule and
   leaves one register across a call; 0 wrong over the pools on the model
   and on seq.py; errors at most 2^-4.4 Bv over five regions, measured,
   with no budget. One of its head steps is margin by a sample (8): 47
   instructions a function, if a budget confirms it. The double word at
   G = 18, the fallback, is measured beside it: 143 to 184 instructions,
   about one bit by its budget (0.42 Bv), and a mark about once in 185,000
   calls against about 2^-39.5 a call. *Recommended: the triple word at
   G = 40,* with the box's 20,000-lane samples and an exhaustive sweep of
   fp32's 2^32 arguments a function (a box job) as its bound's evidence,
   since it has no budget; the double word only if the triple word's cost,
   2.8 to 3.5 times the double word's, is refused.
4. **G.** *Recommended: M1's, 44 at fp64 and 46 at fp128 and fp256 (fp32
   by question 3),* one guard a format for the whole library. MEASURED
   (`gcheck.py`): at G = 46 fp64's four fragments are the same
   instructions with one word changed, the bound's (the head's K = 6 and
   the tail's degree 12 are unchanged), so the budget's 0.058 Bv at G = 44
   is 0.23 Bv at 46 (COMPUTED, times 4): still two bits, and a mark four
   times rarer, for nothing. fp128 and fp256 keep about five bits at 46
   (0.030 and 0.023 Bv). Raising fp64 to 46 for these four functions alone
   would give the library two guards at one format; whether M1's and M2's
   fp64 routines can take 46 is theirs to measure, so this is offered, not
   recommended.
5. **atan2's tiny quotients** (x > 0, |y/x| below 2^(emin+p+2), where the
   result is subnormal or nearly so): marked and replayed (4
   instructions), or decided in-lane by M1's fixed grid (ESTIMATE about
   40 instructions more, a sixth of atan2). The subnormal midpoint
   atan2(minSubnormal, 2) is one of them. *Recommended: mark them.* They
   need |y/x| below 2^-967 at fp64; a workload that lives there can take
   the fixed grid later, as M2's question 2 left LDX.
6. **atan2's exact-quotient rule in-lane** (x > 0, k = 0, the remainder
   zero, below atan's gate: one FMA toward zero, 7 instructions).
   Without it every atan2(y, 2^k) with y below about 2^(k - (p+G)/2), and
   every y a scaled copy of x, would mark. *Recommended: keep it.*
7. **The structured families** (3.5) mark and are replayed: the tiny
   family (atan's x^3/3, asin's x^3/6, atan2's exact quotients above the
   gate), whole windows next to pi/2 and pi (atan of a large x, acos of a
   small x, atan2 beside an axis), and atan2's quotient within the bound
   of a grid point (division's hard cases, a two-parameter family).
   *Recommended: keep them, as M1's question 4 and M2's question 7 did;*
   list the windows' centres and the hard-case family's threshold in the
   build's tests; LANGUAGE.md's rule (M1's) covers them.
8. **Constants.** *Recommended, as M1's question 8 and M2's answer 8:*
   fold atan(0), asin(0), acos(1) and atan2(0, c) for a constant c >= 0
   to 0; `irrational-constant` for every other constant argument, its
   sentence saying "not a real number" for asin and acos outside [-1, 1]
   as `log(-4)` does; no new name.
9. **Live values.** *Recommended: caps per function and format in
   routines.LIVE_CAP* (5.2): 15, 16, 16 and 19 for atan, asin, acos and
   atan2 at fp64, fp128 and fp256, and 25, 25, 25 and 31 at fp32 (the
   triple word, scheduled), each the better of the design's order and
   mathlib's depth-first one.
10. **The derivative rules** (7). *Recommended:* `da / fma(a, a, 1)`;
    `da / sqrt(fma(-a, a, 1))` and `da / (-sqrt(fma(-a, a, 1)))`, 1 - a^2
    by one FMA rather than (1 - a)(1 + a); `fma(b, da, -(a * db)) /
    fma(b, b, a * a)`, with its range limits (an overflow of b^2 + a^2
    past about 2^(emax/2) gives a zero tangent) stated as the quotient's
    are; **the phase follower** as the committed reference.
11. **Where the generator lives.** *Recommended: mathlib.py,* beside M1's
    six and M2's three.
12. **Versions and order.** *Recommended:* M4's build after M2's, stepping
    cftc's output version 7 to 8 and the language 1.2 to 1.3, the
    certificate corpus made again, unless the two builds land together
    and share one step.
13. **The Pi-variants and the inverse hyperbolics** (2.9): asinPi, acosPi,
    atanPi and atan2Pi on this core with a product by 1/pi, their exact
    rows off the main path and their neighbour rules as tiny paths
    (ESTIMATE about 25 instructions a function more); asinh, acosh and
    atanh as M1's log1p with a root and a front end (ESTIMATE 50 to 70
    more than log1p). *Recommended: not in M4's build;* a parcel of their
    own after it, each with its census, if a workload asks.

## 10. What M4's build builds, in order

PROPOSED, after the lead's review and Logan's answers, and after M2's
build:

1. **The golden generator** (mathlib.py, question 11): atan, asin, acos
   and atan2 at fp64, fp128 and fp256 under every attribute, from the
   study's model:
   - the one core (2.1 to 2.3), its index with its exactness audit (8,
     item 2), the front ends (2.4, 2.5);
   - every constant derived and checked (`--check`): pi/2, pi/4, pi,
     atan(k/8), the coefficients, the gates, the scaling words;
   - the fragments held to the invariants, with question 9's caps and
     atan2's two inputs;
   - section 8's items 1 to 7 and the plants, quick ones in the golden
     stage; the larger bound, rate and census samples to the lead for
     amd-arc-box.
2. **fp32,** as question 3 decides.
3. **program.c parity:** the fragments' programs in seq_check's corpora.
4. **The language,** golden-first: the four nodes, atan2's arity, the
   folds and refusals, the renderers, the L3 rules with the
   central-difference check, LANGUAGE.md, the version step.
5. **cftc:** ROUTINES (atan2 binary), the internal check (MIN, MAX, two
   inputs), the targets' refusals, the call loop, VERSION, the corpus,
   the phase follower's committed bytes.
6. **The stages' legs:** lang-routines and tangent with marked lanes
   replayed; VERIFICATION.md's rows.
7. **The card,** on revision 8's images: STATUS[6] and the lane byte on a
   structured argument, and the acceptance set's case.

## 11. The model

Scratch made for this study, kept here as `m1/` and `m2/` keep theirs. It
is not the tree's code, and nothing in the tree imports it. Python with
mpmath; run from this directory, where `m4core.py` puts
`docs/studies/m2/` on the path (it imports M2's `m2core.py`, which puts
the repository's `python/` on it). No file under `docs/studies/m2/` was
edited; `m4budget.py` is a changed copy of M2's `m2budget.py`, under a new
name.

| file | what it is |
|---|---|
| `m4core.py` | M2's core imported, with two inputs (atan2's y and x), an evaluator over them, and the constants (pi, atan(k/N), the coefficients) |
| `m4inv.py` | the routines at the double word (2.1 to 2.7): the cells and rho, the planner, the builder, its plants |
| `m4tw.py` | fp32's triple word at G = 40 (2.8) and its plants |
| `m4harness.py` | the pools and the comparison with transcend.py |
| `pools_run.py`, `onseq.py` | the pools against transcend.py on the model, and as programs on seq.py |
| `m4measure.py`, `m4budget.py` | the error against the bound, sampled and budgeted (a changed copy of M2's budget, 3.2) |
| `rate.py`, `census.py`, `specials.py`, `consts.py` | the mark-rate law, the structured families, the specials row by row, the constants beside the boundaries |
| `costs.py`, `share.py`, `sched.py` | the cost (with mathlib.py's invariants and C4's flag-word walk) and the table's size, asin and acos shared, the live count scheduled |
| `twrun.py` | fp32's triple word: pools, costs, seq.py, the error, its plants |
| `plants.py` | the plants and the checks they must turn red, the index's audit (8, item 2) among them |
| `uform.py`, `gcheck.py` | asin's and acos's 1 - x^2 in three forms (2.4); fp64's fragments at G = 46 against 44 (question 4) |
| `fingerprint.py` | one hash of the 100 default fragments, to show which runs measured the same model |
| `box_m4s.sh` | the handed-back larger runs for amd-arc-box (not run here): the budgets at 12,000 and 3,000 lanes, the rate law at 50,000 and 20,000, fp128's and fp256's tiny census, the triple word over 20,000 a region |
| `queue.sh`, `jobs*.txt`, `queue*.log` | the batches: the runner, its job lists, each run's start and end (the logs' rc is date's, not the job's: 3.6, item 8) |
| `*.out.txt` | each run's output as captured, named for its script, its format (fp32's double word as `fp32-dw18`, its triple word as `fp32-tw`) and its region, family or seed |

**Which model the runs measured.** `fingerprint.py` hashes the 100
default fragments, each body, result, flag word and words. The double
word's hash, a55501a3993eb3fe..., was the same at 13:23 (a run in the
ledger) and in queues 6 to 9; the triple word's, da6c80e125086ccb..., in
queues 6 (after `m4tw.py`'s last change to a default fragment), 7, 8 and
9. Every double-word output kept here ran either on `m4inv.py` as it stood
from 12:57 to 13:22 (the budgets, census, rate and measure runs) or after,
on fragments the hash shows unchanged; the one edit between, which renamed
the direct form's branch from a plant to `u_form` and gave u-low-dropped its
condition, leaves the default instruction sequence as it was (READ: both
branches, before and after). Every later edit added a probe, a plant or a
`u_form`, none in a default fragment. The pools, on-seq, specials and
costs outputs are queue 6's (13:31 to 13:32); every triple-word output is
queue 7's or 9's, after the triple word's fixes (3.6, item 5) and equal to
queue 6's where both ran; the plants and u forms are queues 8 and 9's.
`m4budget.py`'s fix (3.6, item 3) came before every budget cited.

The runs, their times and the desktop's load are in the round's ledger,
`Data/runs/2026-10-12-math-round/ledger/M4S.md`, which is outside the
tree.
