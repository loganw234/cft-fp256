# Study M2: the correctly rounded sin, cos and tan, designed

STATUS: a design study, 2026-10-13. Parcel M2S of the math library round
(docs/ROADMAP.md, "The math library: experiment E1, then M1's build and
M2 to M4 (plan of record, 2026-10-12)", its paragraph "M2, M3 and M4", and
step 6's part 5, "M2, sin, cos, tan"). **Nothing here is built.** No
radian routine is in the golden model, cftc is unchanged, and the language
still refuses `sin(x)` as `transcendental`. The design goes to the lead,
and through the lead to Logan, before M2's build, which is a round of its
own (Logan, 2026-10-12: "M2-M4 builds becoming their own round"). This
file, the model under `docs/studies/m2/`, this file's row in
docs/README.md and its VALIDATION entry are the only changes the study
made.

**A note of 2026-10-13, at the merge with M1's build** (the lead; the
study's text stays as written at 1337a13). Parcel MB1, merged beside this
study at 26ced32, set mathlib.py's `LIVE_CAP` to 21 at fp32 and 13 at
fp64, fp128 and fp256, the measured maxima of exp, exp2 and expm1 in
their scheduled order. Where this study reads the cap, section 5.1's
"mathlib.py's LIVE_CAP for exp is 23" and question 9's "fp128's 17 and
fp256's 16 are within it", it reads 1337a13's 23. Against the merged cap
the study's fragments exceed it at every format: 22 against 21 at fp32,
26, 17 and 16 against 13 at fp64, fp128 and fp256 (verifier-VIW1,
MEASURED, the fragments through the merged `invariants()` at its default
cap; with `live_cap=None`, as costs.py passes it, they hold). Question
9's recommendation, a cap by function and format, stands; its premise
that only fp64 is past the cap does not.

**A note of 2026-10-27, at parcel M2G1** (the reduction built; the study's
text stays as written at 1337a13). The reduction of 2.2 and 2.3, design A:
the plan with its static proofs, the SELECT window, the exact sum, the audit
and the constants' `--check`, is built in python/cft_golden/mathlib.py
(`plan_reduction`, `trig_reduction`, `reduction_audit`, `build_reduction`)
and held by python/tests/test_mathlib_reduction.py; it equals section 11's
model on every argument of `redcheck.py` and `m2edges.py`, and r's largest
errors are 2.2's table (docs/VALIDATION.md, the entry for parcel M2G1).
**Nothing else of M2 is built:** no sin, cos or tan routine, no polynomial,
no tiny path, no fp32 triple word. One finding: 2.4's rho = pi/4 (1 + 2^-30)
does not hold at fp32 with G = 18, where the quadrant count, taken from the
high word of the exact sum alone, leaves |r| past pi/4 by 2^-17.09 (MEASURED,
x = 0x44264edd, n = 424 where 423 is the nearest integer) and by up to
2^-11.66 (COMPUTED from the generator's static bounds), so the bound there is
pi/4 (1 + 2^-11); at fp64, fp128 and fp256 the bounds are 2^-33.04, 2^-64.0
and 2^-62.0, inside the study's. And 2.2's "the quadrant count is MAGIC + n" is MAGIC + n' with n' congruent
to n mod 4 (MEASURED on fp64's 3,853 lanes: equal to n on 121; BELIEVED because the reductions modulo m = 4U take out
multiples of 4 that n' does not count).

**A note of 2026-10-27** (parcel M2X, M2's build, wave 1; the study's text
stays as written at 1337a13). Section 2.7's triple word at G = 40, the one
ESTIMATE of this study, is now built and measured in the study's model, in
new files only (`docs/studies/m2/tw32*`; docs/VALIDATION.md, the entry of
that date). What the measurement makes of the study's statements:
- 2.7's "in all about 930 for sin": **939 instructions** (cos 936, tan
  993), under every attribute, 1.010 of the estimate; by 2.7's three parts
  the reduction is 319 (about 320), the heads 484 (about 490) and the rest
  136 (about 120; tan's quotient is 60 where the sketch said about 35). The
  reduction is not 2.7's four bins of about 19 bits but two exact
  double-word groups cut at 2^-20, the lower group's carry into the upper,
  and two VecSum passes. Bank words: 102 for the three functions under five
  attributes (the double word's 82).
- 2.7's "the live count is not estimated; M1's triple-word exp keeps 33 to
  34": **23 values live**, in the design's order and scheduled, all 15
  fragments accepted by `routines.program`; past the tree's cap of 21 at
  fp32 for the six, so these three want a cap of 23 (question 9).
- 3.2's budget, ported once more for a triple word, under rne (the study's
  budgets are rne; the directed attributes' budgets were not run, and a
  sample under all five, tan near, is identical): the
  bound is **at most 0.3675 Bv in all 18 regions at 1,500 lanes** (a margin
  of 1.44 bits) and **at most 0.4296 Bv at 12,000 lanes on the box** (the
  lead's run of tw32_box.sh, 2026-10-27; a margin of 1.22 bits), against 0.33
  to 0.61 (0.73 at the edge) for the double word at G = 18 (1,500 lanes);
  the pools are 0 wrong on the model and on seq.py (11,400 lanes each), and
  the rate law holds in all 6 cells at 50,000 lanes on the box. The
  structured families that marked at G = 18 (cos at 2^-12 and its
  neighbours) do not mark at G = 40 inside the tiny gates.
- Question 3: all five of the brief's conditions hold, so by its rule the
  triple word at G = 40 is recommended, the double word at G = 18 staying
  the measured fallback; the choice is Logan's. G = 40 is the last G the
  plan's static proofs hold at (36 to 40 build, 41 to 44 fail by name).
- **2.2's and 2.4's cushion** |r| <= pi/4 (1 + 2^-30), which m2trig uses at
  fp32 too, does not hold at fp32 for the double word's reduction (M2G1,
  READ from the lead's messages of 2026-10-27: 0x3f490fdb, 2^-25.10 over, a
  tie; 0x44264edd, 2^-17.09 over, the mid sum's low word left out of the
  quadrant count; its static bound 2^-11.66). The triple word's reduction
  counts the quadrant from the rounded exact upper part, and its overshoot
  is bounded from its pieces' static magnitudes at 2^-18.91 (COMPUTED); the
  largest measured is 2^-19.02 over 14,021 arguments, the floats next to
  the odd multiples of pi/4 in every binade among them.

**A note of 2026-10-27, at parcel M2G2a** (sin, cos and tan built at fp64,
fp128 and fp256; M2's build, wave 2, first half; the study's text stays as
written at 1337a13). The three routines of 2.1 to 2.6 are in
python/cft_golden/mathlib.py on M2G1's reduction: `build` and `fragment` take
`TRIG_NAMES = ("sin", "cos", "tan")` beside `NAMES` (the six's battery
iterates NAMES, so they are not in it), at fp64, fp128 and fp256 under the
five attributes, 45 fragments; at fp32 each is refused by name, the shape
being Logan's choice from M2X's measurement and parcel M2F's to build.
`plan_trig` (the polynomials for a given rho) and `trig_after` (everything
after sin(r) and cos(r), taking V as two words or three) are the sections M2F
calls unchanged. They are held by python/tests/mathlib_trig_harness.py and
test_mathlib_trig.py (docs/VALIDATION.md, the entry of that date, whose
figures these are). They are section 11's model: the dataflow digest of every
fragment in the design's order is `m2trig.build`'s, so are its instruction
counts (406, 402 and 419 at fp64, 382, 378 and 397 at fp128, 389, 385 and 406
at fp256, under every attribute), its bank words (111, 108 and 122 for the
three under five attributes), its plan ((8, 12) and (8, 13), (8, 18) and
(8, 19), (8, 28) and (8, 29)), its counts by phase except that M2G1's
`inrange` compare is in "classify" and not in "range" (confirmed: one
instruction moves, at fp128 and fp256), and (result, flag word, V_h, V_l, R)
on every lane of the pools: 84,630 lanes over the 45 fragments, none
differing (MEASURED, a scratch comparison with this directory's model, in the
entry). What the build adds to the study:
- 2.1's sharing (475, 455 and 464 instructions for the three of one argument
  in a compiled step, at every attribute) and 5.1's live count (26, 17 and 16
  in the design's order) hold, and one thing about the scheduler does not:
  mathlib.py's `schedule_order` keeps 30, 21 and 17 values live (its order by
  phase) and 31, 30 and 30 (depth first) for these, ABOVE the design's order.
  The design's order is now a third candidate of `schedule_order`, strictly the
  lowest for all 45 and for none of the six, so `TRIG_LIVE_CAP` (question 9's
  cap per function and format) is 26, 17 and 16.
- 3.5's structured centres are exactly the pools' marks that are not past the
  range, at every format: cos at three values (fp64: four) under the directed
  three, tan at 3 2^-k under rne and rmm, both signs, 72 lanes over the 45
  fragments (the committed list `TRIG_POOL_MARKS`); every other lane of the
  pools that is not past the range is decided and right.
- 8's table: the plants are reproduced at fp64, all 14 named cases lane for
  lane (exact-add by its 27 lanes on the binade edges, the first
  0x46167c4c45c1b200), and the bounds the table gives to its precision, at its
  64 points of each region (2^98 Bv for quadrant-sign, 2^17.0 for
  newton-short, the control 2^-4.52, ...: the entry has them all).
- Not in this note and not built: the budget, the mark-rate law and the
  structured families (parcel M2G2b's), fp32 (parcel M2F's), program.c and
  cftc (M2P's and M2C's), the language (M2L's).

**A note of 2026-10-28, at parcel M2G2b** (the budget, the mark-rate law and
the structured families of sin, cos and tan, ported from this study's model;
M2's build, wave 2, second half; the study's text stays as written at 1337a13).
They are python/tests/mathlib_trig_budget.py (3.2), the rate check in
mathlib_trig_harness.py (3.4), mathlib_trig_family.py with its committed
`TRIG_FAMILY` and the family checks (3.5), and the commands `trig-budget`,
`trig-rate` and `trig-family` of mathlib_runs.py, held by test_mathlib_trig.py
(docs/VALIDATION.md, the entry of that date, whose figures these are).
python/cft_golden is unchanged: no fragment moved. What they reproduce of 3.2
to 3.5, and what they move:
- **3.2's table stands, to its digits.** The port of `m2budget.py`'s method
  (the three trig extensions of 3.2 and 3.6; `Analyzer` and `Budget` of the six,
  extended by subclass) gives, at the model's own lanes (`m2measure.py`'s
  sample, ported by M2G2a: seeds 21 to 25, 1,500 lanes a region at fp64 and
  400 at fp128 and fp256), the model's printed output line for line in all 15
  cells at fp64, the control among them (fp64 sin, edge: 0.07031 Bv, M 0.0298,
  capacities 0.0405, 126 instructions that ever round, the ten largest
  capacities by instruction, opcode and phase), and in all 30 cells at fp128 and
  fp256 but for the instruction numbers, one higher after the range compare M2G1
  builds early (MEASURED). V is bit-identical across the five attributes on
  2,700 lanes (300 a function and format), so the rne budgets are every
  attribute's (MEASURED). 3.6's items 6 and 7 are planted in the tool and red:
  a RECIP_SEED's source frozen gives tan 2^+46.5 Bv on the golden stage's 60
  lanes (12 a region, seed 5) against a clean largest error found of 0.014 (the
  model's 2^+46.7 against 0.048), and the error-free phases recomputed a method
  error of 6 x 10^294 Bv and a bound of 2.8 x 10^297 on the same 60 lanes (the
  model's 2^+822 on four).
- **3.4's rate cells stand, and one column moves.** At seed 3, 2,000 arguments
  a format (rate.py's lanes), all 18 cells have the study's counts, no unmarked
  lane wrong and every guess right (MEASURED). The "own prediction" column is
  equal for sin and tan and not for cos: 51.0 against 50.1 at fp128 and 51.7
  against 49.3 at fp256 (50.36 against 50.34 at fp64: one lane). The study took the
  significand of V_h, 1 where cos x is within half a unit of 1 from below (56
  lanes at fp128, 150 at fp256) and the cell is the one under 1, twice as wide a
  window; the law's m_V is the true value's, 2 there (parcel RC's calibration;
  MEASURED: the sum with V_h's significand is the study's 50.1 and 49.3). The
  study's pooled sin -2.0 and cos +2.0 sigma are for `trig-rate` at the box's
  size (50,000 and 20,000) to settle against these expectations.
- **3.5's tables stand, and its reading of them moves.** The tiny family's
  and the minimisers' counts are the study's at the decided G in all three
  formats (MEASURED, every lane against transcend.py), and the three measured
  windows (fp64 sin 3 2^-25 rtz j = -9 .. 11, tan 3 2^-26 rne -23 .. 19, cos
  2^-26 rtz -255 .. 128) end between the exact edges the theory computes, the
  last lane it demands marked and the first it calls clear (above and below the
  centre: 8 and 15, 6 and 13; 13 and 26, 16 and 30; 89 and 167, 179 and 333). **The census is c <= 16 (five bits), and the family goes
  beyond it:** the theory finds, and the fragments mark with every guess right
  (MEASURED), sin under rne and rmm at c = 21 and 27 (2^-54 at fp128, 2^-116 at
  fp256: a midpoint needs 2e = p - bitlen(c), and the first c divisible by 3 whose
  bit length has the parity of p has five bits at these formats), cos under rne at c = 2^46 - 1, 2^46 + 1 and
  3 2^46 - 1 at 2^-142 and 3 2^48 - 1 at 2^-143 at fp256 (x^2/2 within 2^-285 of
  a midpoint), and nine tan centres under rne at fp128 and fp256 where the
  study's census has three. 3.5's "none under rne and rmm, p is odd" for sin and
  cos holds for the census and not for the family. The fp64 cos directed count
  (14 arguments) is seven centres, one of which (7 2^-26) is at d = 0.78 of
  the bound, in neither "must" nor "must not". The clamp matters to the theory:
  the grid point 1 is no boundary of sin and cos.

**A note of 2026-10-29, at parcel M2P** (program.c parity: the 45 fragments
through libcft's sequencer; M2's build, wave 3; the study's text stays as
written at 1337a13). The routine corpus of host/tests/seq_check.py, the eighth,
has a second part beside M1's six: sin, cos and tan at fp64, fp128 and fp256
under the five attributes, each fragment as a stand-alone program
(`routines.program`) and as the compiler inlines it (QUIET, the body, ENDQUIET,
RAISE, the result deposited), 90 programs a round, through libcft and the
golden model. At the gate's arguments: 5,237 lanes compared, 0 mismatches, the
six's draws unchanged by digest (docs/VALIDATION.md, the entry of that date,
whose figures these are). python/cft_golden and the harnesses are unchanged: no
fragment moved. What the run says of the programs the study designed:
- **Sizes as libcft's sequencer reads them:** 381 to 424 instructions (a
  fragment's count of 5.1 plus 3 stand-alone and 5 compiled) and 101 to 119
  bank words, against the six's 178 to 438 and 62 to 123; no trig program is the
  largest of the 330 by either measure.
- **Registers:** the programs write r25 at fp64 and r16 at fp128 and stay in r15
  at fp256 (5.1's live counts 26, 17 and 16), so the 60 programs of fp64 and fp128
  need the REGS32 bit (CAPS[5]) of a device, which the six need at fp32 alone.
- **Forms the six's programs do not have** (the entry lists them by encoding):
  `min` and `max` against a bank word, sin's and cos's clamp (mathlib.py's
  `fmin` and `fmax`; the fuzzing corpora draw `min` and not `max`, so no corpus
  reached `max` before);
  `cmplt` of two registers; a SELECT whose two arms are both bank words
  addressed by plain index (below 16), the reduction's choice between two of
  2/pi's chunks; an ADD at round-down against `MAGIC`, the quadrant count; the
  program's own attribute on an FMA against a bank word;
  `iand` against a mask on a register past r15. RECIP_SEED in tan's quotient and
  an IXOR against a word are forms the six's programs already have.
- fp32 is not in this note, as it is not built: the corpus names it in its
  summary line and draws no lane of it. When parcel M2F builds the three at
  fp32 and adds it to `TRIG_FORMATS` the same loop runs them.

M1's study (docs/studies/M1-exp-log.md) is its model of form, section for
section, and M1's design is its starting point: the in-lane test, the
double word with TwoSum and no augmented addition, the fragment in C4's
shape, the guard G and its mark-rate law. Where this study departs from
M1 it says so.

Every statement is one of five kinds, and says which:
- **READ**: from this tree at 1337a13, with the file named;
- **MEASURED**: from a run of the study's model (section 11), on the
  desktop, niced, one process at a time, each run's output kept beside the
  model as `*.out.txt`; the runs, their times and the desktop's load are in
  the round's ledger (`ledger/M2S.md`), which is outside the tree;
- **COMPUTED**: arithmetic on read or measured numbers, shown;
- **ESTIMATE**: mine, and said so;
- **PROPOSED**: this design. Every name, constant and order below is a
  proposal for the lead and Logan, not a decision.

## Contents

0. In brief
1. What M2 works with
2. The algorithms
3. The error bound and the in-lane test
4. The specials and the flags
5. The cost
6. The language and the compiler
7. The derivative rules
8. How it will be held
9. Questions for Logan, each with a recommendation
10. What M2's build builds, in order
11. The model

---

## 0. In brief

- **What.** sin, cos and tan at fp32, fp64, fp128 and fp256 under each of
  the five attributes, each a fragment in C4's shape, inlined where its
  node stands, quiet, raising exactly transcend.py's flags, and setting
  bit 7 of the raised word where its own test cannot decide the last bit.
  PROPOSED, and measured in a Python model op by op through
  softfloat.compute, on seq.py as programs, and against transcend.py and
  mpmath.
- **The reduction** (PROPOSED; MEASURED in the model, 2.2 and 2.3):
  - Payne-Hanek against 2/pi's bits for every lane down to the tiny
    gate; no Cody-Waite path, since with no branch a second reduction
    would only add its instructions; |x| < pi/4 takes r = |x| for 5;
  - 2/pi in bank words of b bits (44 at fp64, 108 at fp128, 233 at
    fp256), read by a SELECT log-shifter over the bucket the exponent
    picks: no scratch slot, no branch;
  - the sum carried exactly through the cancellation, in units where
    every piece has a fixed grid, so that the generator proves each
    exact sum before any lane runs, and an audit checks each claim lane
    by lane;
  - **fp64's whole range:** 1,232 bits of 2/pi in 28 words (30 with two
    zero words); **fp128 and fp256 to 2^1024,** marked and replayed past
    it (certificate version 2's question 3), 15 and 10 words. fp256's
    2^1024 costs 32 instructions more than 2^128; past 2^1024 the window
    wants LDX (question 2);
  - fp128's cancellation over that range is 123 bits, past the docs'
    sampled 121 for the whole range (1.4).
- **The rest** (PROPOSED): Taylor polynomials S(z) = sin r / r and
  C(z) = cos r with double-word heads of 8 steps, no table; tan by its
  own double-word quotient, 19 to 23 instructions, not C4's division;
  M1's in-lane test with Bv = 2^-(p+G) |V_h|; and the clamp, |sin x| and
  |cos x| < 1 by Hermite-Lindemann, 4 instructions. G = 44 at fp64 and 46
  at fp128 and fp256, M1's.
- **The cost** (MEASURED, 5.1): sin 406, 382 and 389 instructions at
  fp64, fp128 and fp256; cos 4 fewer; tan 13 to 17 more. Bank words 111,
  108 and 122 for all three functions under all five attributes; no
  scratch slot; 26, 17 and 16 values live. **sin and cos of one argument
  together cost 434, 411 and 418** in a compiled step, since cftc's
  inliner shares their whole prefix; all three, 475, 455 and 464. The
  surveyor guessed about 250 at fp64 and 1,500 to 2,500 at fp256: fp256
  costs about what fp64 does, for M1's reason.
- **The bound** (MEASURED, verifier-VM1b's first-order budget, ported,
  3.2): every region budgeted keeps more than two bits, at most 0.096 Bv
  at fp64, 0.073 at fp128 and 0.166 at fp256 (the box's larger budgets:
  0.100, 0.0729 and 0.1663); at G = 46 fp64 would keep less than two
  (0.26 to 0.36 Bv), as M1 found.
- **Held in the model against transcend.py** (MEASURED): the radian pools
  at four formats, all 60 configurations, 0 wrong unmarked lanes, on the
  model and as programs on seq.py; the specials row by row; at each
  format six regions of arguments (6,000 or more a function) against
  mpmath at 4p + 200 bits and transcend.py, 0 wrong; every error under
  its region's bound by the box's larger budgets, though three cells
  pass the study's own (3.3); the reduction against exact rationals with
  the audit, 0 failures (3.3, 2.2).
- **The marks** (3.4, 3.5): random lanes at about 2^(0.67 - G) a call
  for sin and cos (their values crowd toward 1); the structured families
  next to 0, sin's and tan's where x^3/6 or x^3/3 lands on a rounding
  boundary and cos's where x^2/2 does, each a window of neighbours, a few
  centres at fp64 and many at fp256. The arguments nearest multiples of
  pi/2 mark none, but at fp128 and fp256 their neighbours do under the
  directed attributes, where (j ulp)^2/2 lands on the grid below 1.
  Every marked guess was right.
- **fp32** (2.7, question 3): the double word reaches G = 18 only, MEASURED
  at 344 to 359 instructions; the triple word at G = 40, Logan's for M1's
  library, is an ESTIMATE of about 930.
- **The model found nine defects in itself** (3.6), four of them in its
  own measuring tools, one through a planted fault the pools could not
  see. No defect in transcend.py was found.
- **Twelve questions for Logan** (section 9), each with a recommendation.

## 1. What M2 works with

### 1.1 The plan, and what binds it

READ, docs/ROADMAP.md, step 6's part 5 ("M2, sin, cos, tan") and the math
library's plan of record ("M2, M3 and M4"):
- **fp64, full range,** with 2/pi's bits in the bank, "about 1,200, fit the
  bank (about 23 words), but choosing the window by the exponent needs a
  copy in each lane's scratch, read by LDX (the surveyor's estimate)";
- **fp256, a stated range,** "beyond which a lane is marked and replayed.
  The range is wide, so that marks stay rare: certificate version 2's
  question 3, which Logan decided as recommended". 2^1024 "needs about
  1,300 bits of 2/pi by the study's estimate, and M2 measures its cost";
- each function gains an L3 derivative rule;
- fp32 and fp128 are this study's to design and recommend, as M1 did.

What binds it (READ):
- **Certificate version 2's question 3** (docs/studies/CERT-V2.md, 7.1
  and its question 3): "a wide range, its cost measured by M2, with mark
  and replay past it", decided as recommended. Its estimate of the cost,
  "A window of 237 + 245 bits (the significand, and the cancellation part
  M sampled) plus a guard then makes about E + 244 bits", leaves out the
  result's own bits: host/src/transcend.c's window needs
  W >= p + 2 + cancellation + Wi + 10 (docs/TRANSCENDENTALS.md, "The
  cancellation, and why it is a measurement"), with Wi the working
  precision, here p + G. Section 2.3 measures the difference.
- **No augmented addition.** The quad is built without R21 (revision 8's
  question 9, probe L), so, as M1 does, every error-free sum here is a
  TwoSum (6 instructions) or, where the exponents are provably ordered, a
  Fast2Sum (3). One image serves every target.
- **The rounding rule:** IEEE 754 first (Logan, 2026-09-29). sin, cos and
  tan are among 754-2019's recommended operations, 9.2, table 9.1
  (`python/cft_golden/transcend.py`'s docstring).
- **The order:** M2's study runs beside M1's build; M2's build follows in a
  round of its own (the plan of record, "The order").

### 1.2 What a tile gives a routine

READ (`python/cft_golden/softfloat.py`, `seq.py`, `routines.py`,
`mathlib.py`, docs/SEQUENCER.md), as M1's 1.2 lists it, and four facts
M1 did not need:
- **MIN, MAX and COPYSIGN** are ALU instructions (softfloat's 7, 8 and 6,
  asm's OP_FIELDS); this design uses MIN and MAX for its clamp (2.6).
- **IMUL is 32 bits by 32, low 32 bits only** (softfloat.imul), so no wide
  integer multiply exists: the reduction's products are FMA's TwoProd, and
  an integer Payne-Hanek as transcend.c's is not available (the step-6
  survey, part M, said the same).
- **LDX and STX** read and write a lane's scratch at rb's bit pattern
  modulo the run's depth, and revision 8's R22 steps rb after the access.
  The depth is a run's parameter: 256 by default and on the software
  target, 2,048 on revision 7's U50 images, 4,096 on rev8a and rev8q and
  8,192 on rev8d (SEQUENCER.md; cftc/targets.py). Slots start at +0 every
  run unless SCRATCH_IO preloads them, so a copy of a table in scratch is
  filled each run.
- **A scratch access is priced at s = 5.21 ALU instructions at fp64 and
  5.08 at fp256** by the census (SEQUENCER.md, R22's "What each is worth,
  counted"), and a stepped LDX at up to one more.

### 1.3 The definition

READ, `python/cft_golden/transcend.py`, the radian functions
(`_radian_family`, `_ziv_signed`) and the comment block "THE ARGUMENT
REDUCTION, AND WHY THIS MODULE DOES NOT WRITE ONE":
- **The specials:** a NaN gives the canonical quiet NaN, invalid if
  signalling; +-inf give the quiet NaN with invalid; +-0 give sin and tan
  the operand and cos 1, with no flag.
- **The tiny rules,** each the leading term of the series and its sign
  against a quarter of the grid step, decided by the side of a
  representable neighbour, with e = floor(log2 |x|): sin's
  2e + p + 2 <= 0, the neighbour of x toward zero; tan's
  2e + p + 3 <= 0, the neighbour of x away from zero; cos's
  2e + p + 3 <= 0, the neighbour of 1 toward zero.
- **Beside one:** |sin x| and |cos x| are strictly below 1 for every
  nonzero dyadic x (Hermite-Lindemann), so where the enclosure's low end
  lies in the half gap below 1 the side is the whole answer, the
  neighbour of +-1 toward zero.
- **Everything else** goes through a Ziv loop on mpmath's interval sine,
  cosine and tangent, which reduce internally; the sign is read off the
  enclosure. host/src/transcend.c reduces Payne-Hanek-style from a
  270,336-bit window of 2/pi, deliberately a different derivation.
- **No exact case** but the zeros (and cos(0) = 1), no divideByZero
  (no representable argument is a pole), no overflow in practice (how
  close an argument gets to a pole is a measurement; 1.4), and underflow
  only on the tiny paths.

The routine must give transcend.py's bits and flags on every lane it does
not mark.

### 1.4 How close an argument comes to a multiple of pi/2

READ, `host/tools/pi_worstcase.py` and docs/TRANSCENDENTALS.md: "lost" is
how many leading zeros the reduced fraction t = x 2/pi - n has, so
|t| >= 2^-(lost+1). The tool's search, validated against exhaustive search,
measured 29 bits at fp32 and 61 at fp64 over every binade, and 121 at
fp128 (every 16th binade) and 245 at fp256 (every 512th). By the counting
argument the minimum over N binades of a p-bit format is about
2^-(p + 1 + log2 N).

MEASURED here (`worst_range.py`, the tool's own search, `worst_over_format`,
over every binade of the stated range [1, 2^1024), 1,024 binades; below 1
there is no cancellation to measure, since |x| < pi/4 takes r = |x| exactly
and from pi/4 to 1 |r| stays above 0.57):

| | deepest | where (value exponent) | then | time |
|---|---|---|---|---|
| fp128 | 123 bits | 909 | 122 at 244 and 910 | 33 s |
| fp256 | 244 bits | 239, 606 and 964 | 243 at 240, 564, 607 and 965 | 118 s |

- **fp128's stated range goes deeper than the docs' figure for the whole
  range:** 123 bits against 121. The docs' figure is a sample, every 16th
  binade, and a sampled worst is a lower bound: 909 is not a multiple of
  16. The design takes 123 (`m2plan.LOST`), since it sizes the window
  (2.2; section 3.6, item 3).
- **fp256's range reaches 244, within the docs' 245,** which the design
  keeps.
- **fp32 and fp64** keep the docs' figures, measured over every binade.
- The whole of fp128's range (16,384 binades) and of fp256's (262,144)
  were not searched here. At the rates above, about 0.03 s and 0.12 s a
  binade, they would take about 9 minutes and 8 hours (COMPUTED): a box's
  runs, and the stated range does not need them (2.3). The lead's box
  run searched fp128's (MEASURED, `box-out/worst-fp128.out.txt`): 123
  bits at value exponent 909, tied by 1964, 2434, 3811, 13962 and 16052.

## 2. The algorithms

### 2.1 One shape for three routines, and what they share

PROPOSED. sin, cos and tan are one fragment of nine parts, all run on
every lane, since there is no branch:

1. **reduce** |x| = n pi/2 + r, |r| <= pi/4 (1 + 2^-30), with r a double
   word r_h + r_l and n mod 4 in the low bits of an encoding (2.2);
2. **z** = r_h^2 as an exact double word (TwoProd);
3. **S and C**, two Taylor polynomials in z, S(z) = sin(r)/r and
   C(z) = cos(r), each a single-word Horner tail and K double-word steps
   (2.4);
4. **sin(r) and cos(r)** as double words: r_h S and C, with r_l's share by
   the derivative (2.4);
5. **select** by n and by x's sign: sin(|x|) is S, C, -S, -C for
   n = 0..3; cos is C, -S, -C, S; tan is S/C or -C/S, by a double-word
   quotient of its own (2.5). x's sign joins for sin and tan, which are
   odd. The sign goes onto the double word V before its one rounding,
   since rdn and rup are not symmetric;
6. **round once** under the program's attribute, R = rnd(V_h + V_l), and
   **test**: M1's in-lane test (its 3.1) with Bv = 2^-(p+G) |V_h|, the
   absolute value because V may be negative (2.6);
7. **clamp**, for sin and cos only: both ends' roundings and the guess
   are kept within [rnd(-1 + tiny), rnd(1 - tiny)], the definition's
   beside-one rule as two MAX and two MIN instructions (2.6);
8. **classify** x: NaN, signalling, infinity, zero, the tiny gate, and
   past a stated range (fp128, fp256) the mark (2.3);
9. **select** the tiny paths' and the specials' answers over the main
   path's, lowest priority first, as M1 does. The flag word is built from
   constant words only, so its possible values are a finite set (4).

The internal arithmetic is RNE; the routine's own attributes are RDN (the
bucket's floor and the test's low end), RUP (the test's high end) and the
program's attribute (the final roundings and the tiny paths' one FMA):
within mathlib.py's widened invariants (6).

**Parts 1 to 4 do not depend on the function.** The three fragments,
built by one generator, emit them instruction for instruction alike, and
cftc's inliner hash-conses a routine's instructions across the instances
of a step by opcode, attribute and operands (READ, python/cftc/inline.py's
docstring, "SHARING"). So sin(a) and cos(a) in one step compute the
reduction and both polynomials once. MEASURED (`share.py`, replaying
inline.expand's keying over the instances bound to one input), at every
attribute:

| | fp64 | fp128 | fp256 |
|---|---|---|---|
| sin alone | 406 | 382 | 389 |
| sin and cos | 434 (808 apart) | 411 (760 apart) | 418 (774 apart) |
| sin and tan | 449 (825 apart) | 428 (779 apart) | 437 (795 apart) |
| sin, cos and tan | 475 (1,227 apart) | 455 (1,157 apart) | 464 (1,180 apart) |

This is what makes the derivative rules cheap (7): sin's tangent reads
cos(a), which costs 28 instructions more than sin(a) at fp64, not 402.

### 2.2 The reduction

PROPOSED; MEASURED in the model (`m2red.py`, `redcheck.py`).

**No Cody-Waite path.** The plan's brief asks for a Cody-Waite reduction
for small |x| and Payne-Hanek from some point on. With no branch, every
lane runs every path, so a Cody-Waite path beside Payne-Hanek would only
add its instructions: each lane would compute both reductions and select
one. Payne-Hanek here covers every argument down to the tiny gate,
because its window starts at zero words for small arguments (below), and
|x| < pi/4 takes r = |x| exactly by an IAND, a compare and three SELECTs
(n = 0), 5 instructions. So the answer to "from where" is: from the tiny
gate, for every lane.

**The window, chosen by the exponent.** Write |x| = M 2^e, with M the
p-bit integer significand (as a float: two integer instructions on the
encoding) and e = E - (p - 1). Store 2/pi as chunks of b bits,
2/pi = sum_k c_k 2^-((k+1) b), each c_k an integer below 2^b held exactly
as a float. Every chunk before c_(g-1) contributes a multiple of 4 to
x 2/pi when e - (g-1) b >= 2, and drops out modulo 4: the bucket is

    g - 1 = floor(G0 / b),   G0 = e - 2 = E - p - 1,
    sigma = e - g b, in [2 - b, 1].

g - 1 is computed from the biased exponent (an IAND and an ISHR) by an IOR
into a magic number (so E becomes a float exactly), one subtraction, one
FMA by 1/b and one addition rounded down (the floor): 6 instructions, and
b need not be a power of two. Then

    x 2/pi = 2^sigma S (mod 4),   S = sum_(j<L) M c_(g-1+j) 2^-(jb),

the window being the L chunks c_(g-1) .. c_(g-2+L). Arguments too small
for any chunk to drop take Z leading zero words (2 at fp64, fp128 and
fp256). The
window is read out of the table of K words by a SELECT log-shifter over
the shift g - 1 + Z, bank words only: at the level of each bit i of the
shift, from the highest, an array of L + 2^i - 1 SELECTs. The
alternative, L stepped LDXs from a scratch copy of the table, is counted
in 5.3.

**Why S-hat.** Every product T_j = M c 2^-(jb) has a fixed grid, 2^-(jb),
and fixed bounds, whatever sigma is: only the modulus m = 2^(2 - sigma)
and the quadrant unit U = 2^-sigma move, and both are powers of two built
from sigma by integer instructions on the encoding (sigma itself and
V = 2^sigma, U, m and 1/m: 8 instructions). So every piece of the sum can
be bounded once, at
generation, over every chunk that can stand at its position
(`m2plan.analyse`), and the generator emits only the operations the
bounds need: no guard is data-dependent but the first product's.

**The sum, exactly where the cancellation happens.** The reduced fraction
t = x 2/pi - n can be as small as 2^-(lost+1) (1.4), and r must be known
to 2^-(p+G+3) of itself, so the sum must be exact down to about
2^-(lost + p + G) absolute: 2^-162 at fp64. A double word is not enough
if anything rounds before the cancellation. The design:
- **products:** T_j = M c 2^-(jb) by TwoProd (MUL and one FMA) where its
  low word reaches the needed accuracy, by MUL alone after that;
- **coarse:** P_0 mod m (guarded: past 2^(p-1) m it is 0 mod m), rho_0
  mod m and P_1 mod m, each by a magic-number quotient and one FMA, and
  their sum V_I, which the bounds prove exact (it is why b <= p - 4, and
  smaller where a chunk at the second position has leading zeros: fp128's
  b came down from 109 to 108 so); k_1 = round(V_I / U) and
  f_I = V_I - k_1 U, exact, |f_I| <= U/2;
- **mid:** every piece whose grid lies above a fixed S-hat "bottom"
  2^beta, and the upper parts of the pieces that straddle it, split there
  by a magic number (3 instructions, no guard: the bounds keep each piece
  inside the magic's range); summed exactly into a double word (a piece
  goes into the low word where that sum is provably exact, else by
  TwoSum); reduced modulo U; added to f_I by TwoSum with the low words
  added exactly; the quadrant taken out once more; renormalised by
  TwoSum. **The cancellation against the nearest multiple of pi/2 happens
  here, and nothing in it rounds;**
- **lower:** the pieces and parts below the bottom, a double-word sum
  (TwoSum for each piece large enough that a rounding there would reach
  the accuracy needed, plain adds below);
- **then** t = (exact part + lower part) 2^sigma, exactly scaled, and
  r = t pi/2 by a double-word product with pi/2 in two words.

The bottom and b come from the budget (`m2plan.plan`): the lower sum's
double-word error must stay under a quarter of t's allowed error
(2^-(p+G+3+lost+1)), and the exact combination of f_I with the mid sum
must fit a double word, |f + mid| <= U <= 2^(b-2) on the bottom's grid,
which gives b <= 2p + 1 + beta. L is the least whose dropped tail of
2/pi, under 2^(1 + p - (L-1) b), is under a quarter of the allowance.

**Every instruction the generator calls exact is listed and audited**
(`m2red.audit`): on each lane, its operands' exact values, the exact
operation and the rounded result are compared. MEASURED (`redcheck.py`,
the reduction alone against x 2/pi in exact rationals, 2/pi to
e + 2p + 400 bits, with r's error in units of the routine's bound
2^-(p+G); the arguments are random over the range in every bucket, each
bucket's two edge exponents with three significands, every power of two
the range holds (every 7th at fp128 and fp256), and the pools' deepest
cancellations; then, as a second set, the products' binade edges of
`m2edges.py`, below):

| | arguments | r's largest relative error, of 2^-(p+G) | quadrant off | audit failures |
|---|---|---|---|---|
| fp64 | 3,853 | 2^-7.90 | 0 | 0 |
| fp128 | 676 | 2^-50.90 | 0 | 0 |
| fp256 | 434 | 2^-189.59 | 0 | 0 |
| the binade edges: fp64, fp128, fp256 | 1,844, 632, 302 | 2^-7.90, 2^-56.43, 2^-181.91 | 0 | 0 |

At fp64 the reduction's error stays within its planned share of the
bound, 2^-3 of it (the plan's delta = 3), at 2^-7.9; at fp128 and fp256
it is the double word's own floor, far below.

**The binade edges** (`m2edges.py`). The static proofs bound each piece by
the extremes of its product T_j = M c 2^-(jb), and a sum they call exact
is nearest to failing where a product sits next to a power of two, so
that its grid changes. Random arguments rarely put one there: the
exact-add plant (section 8) replaced a TwoSum the proofs need with a
plain add and passed every random and pool lane, because the add is
inexact only when P_2 lies within |rho_1| of a binade's top. So the
family puts each product there: for every bucket and every position
whose chunk c is nonzero, the significands next to M0 = ceil(2^K / c),
2^K the power of two inside [2^(p-1) c, 2^p c), and the two ends, at
three exponents of the bucket (1,844 arguments at fp64).

**Its size by part** (MEASURED, `costs.py`, sin under rne; cos and tan,
and the other attributes, the same in every part but select, quotient
and special):

| part | fp64 | fp128 | fp256 |
|---|---|---|---|
| setup: E, the bucket, sigma's powers of two, M | 18 | 18 | 18 |
| window: the SELECT shifter and its bit tests | 61 | 35 | 22 |
| products: TwoProd where the low word counts | 21 | 17 | 17 |
| coarse: three pieces mod m, V_I, the quadrant, f_I | 18 | 18 | 18 |
| mid: splits, the exact sum, mod U, f_I + mid, the quadrant again | 36 | 28 | 28 |
| lower: the double-word sum, then the exact part plus it | 33 | 33 | 33 |
| scale: t V, r = t pi/2 as a double word, n | 14 | 14 | 14 |
| small: \|x\| < pi/4 takes r = \|x\| | 5 | 5 | 5 |
| the reduction | 206 | 168 | 155 |
| z = r_h^2, S's and C's tails, S's and C's heads | 4, 4 + 5, 70 + 69 | 4, 10 + 11, 70 + 69 | 4, 20 + 21, 70 + 69 |
| sin(r) and cos(r) as double words, with r_l's share | 7 | 7 | 7 |
| select, final rounding with the test and clamp | 9, 13 | 9, 13 | 9, 13 |
| classify, the range's mark, the tiny path and specials | 6, -, 13 | 6, 2, 13 | 6, 2, 13 |
| sin | 406 | 382 | 389 |

### 2.3 The range

**fp64: the whole range** (PROPOSED, the plan's), |x| < 2^1024. MEASURED
(`costs.py`): 28 chunks of 44 bits, 1,232 bits of 2/pi, with the 2 zero
words 30 bank words, read by a shifter of 5 levels (61 instructions with
its bit tests). The plan's estimate, about 1,200 bits in about 23 words,
holds for the bits; the words are 28 because each carries 44 bits, not 53: at fp64
the exact combination of 2.2 needs b <= 2p + 1 + beta = 44 (beta = -63).

**fp128 and fp256: a stated range,** |x| < 2^R, PROPOSED R = 1024 for
both (question 2). A lane at 2^R or above is marked, by one compare and
one SELECT of the flag word (2 instructions), and replayed by the
definition: certificate version 2's question 3 as decided. Its result is
a guess and means nothing.

What a range costs, MEASURED (`ranges.py`: the plan and sin's built
fragment at each R; the cancellation used past 2^1024 is the
[1, 2^1024) figure, an ESTIMATE there):

| fp128, \|x\| < 2^R | 2^128 | 2^256 | 2^512 | 2^1024 | 2^2048 | 2^4096 | 2^16384 (all) |
|---|---|---|---|---|---|---|---|
| words of 2/pi (chunks x b bits) | 7 (5 x 109) | 8 (6 x 109) | 10 (8 x 108) | 15 (13 x 108) | 25 (23 x 104) | 45 (43 x 103) | 166 (164 x 102) |
| shifter levels, SELECTs | 2, 11 | 2, 11 | 3, 19 | 4, 31 | 5, 51 | 6, 87 | 8, 287 |
| sin: instructions, bank words, live | 360, 94, 16 | 360, 95, 16 | 369, 98, 16 | 382, 104, 17 | 403, 114, 25 | 440, 135, 41 | 640, 257, 137 |

| fp256, \|x\| < 2^R | 2^128 | 2^256 | 2^512 | 2^1024 | 2^2048 | 2^4096 | 2^16384 | 2^65536 | 2^262144 (all) |
|---|---|---|---|---|---|---|---|---|---|
| words of 2/pi (chunks x b bits) | 6 (4 x 233) | 7 (5 x 233) | 8 (6 x 233) | 10 (8 x 233) | 14 (12 x 230) | 23 (21 x 230) | 78 (76 x 227) | 294 (292 x 227) | 1,181 (1,179 x 223) |
| shifter levels, SELECTs | 1, 5 | 2, 11 | 2, 11 | 3, 19 | 4, 31 | 5, 51 | 7, 155 | 9, 547 | 11, 2,091 |
| sin: instructions, bank words, live | 357, 112, 16 | 380, 114, 16 | 380, 115, 16 | 389, 118, 16 | 402, 123, 17 | 423, 132, 25 | 529, 189, 73 | 923, 407, 265 | not built: 1,181 words |

- **From 2^128 to 2^1024 the range costs 22 instructions at fp128 and 32
  at fp256;** the reduction's arithmetic does not change, only the
  window's shifter grows, a level for each doubling of the table. At
  fp256 below 2^256 no bucket has a chunk at the window's first position,
  so its product and that product's reduction modulo m drop out: of the
  23 instructions from 2^128 to 2^256, 15 are those (products 14 to 17,
  coarse 6 to 18) and 8 the shifter's second level (MEASURED, `ranges.py`,
  which prints the reduction's parts at each range).
- **Past 2^1024 the SELECT window stops being the right tool:** at fp128
  2^4096 keeps 41 values live, past the 32 registers, and the whole
  range 137 live and 257 bank words of the 512; at fp256 2^16384 keeps
  73 live, 2^65536 265 live in 407 words, and the whole range needs 1,181
  words of 2/pi, past the bank. A wider range wants the LDX window (5.3),
  whose cost does not grow with the table: L stepped loads, and the
  table's words in scratch slots (166 at fp128's whole range, within
  even the software target's 256; 1,181 at fp256's, within revision 8's
  4,096 and 8,192 slots but not 256).
- **2^1024 covers every magnitude an fp64 value has,** and an argument
  past it is not one a program reaches by stepping time or an angle:
  marks past it stay rare, which is what the question's "wide" asks.

**The plan's 1,300 bits for fp256 to 2^1024** (CERT-V2's estimate) left
out the result's own p + G bits (1.1). COMPUTED from the plan's budget:
the last bit a lane at 2^1024 needs is about
E_max - (p - 1) + 2p + lost + G + 7 = 787 + 474 + 245 + 46 + 7 = 1,559,
and the table holds 1,864 (8 chunks of 233 bits; the deepest chunk a
lane reads ends at bit (g_max - 1 + L) b = 8 x 233), the difference the
bucket's granularity, a whole chunk.

### 2.4 The polynomials

PROPOSED; MEASURED in the model.

**One polynomial domain, no table.** |r| <= rho = pi/4 (1 + 2^-30), the
cushion covering the quadrant count's rounding at a half-integer t. With
z = r^2 <= rho^2 = 0.617:
- S(z) = sin(r)/r = sum (-1)^k z^k / (2k+1)!, and
- C(z) = cos(r) = sum (-1)^k z^k / (2k)!,
Taylor, for M1's reason: the remainder is a rigorous one-line bound. The
coefficients are exact rationals rounded once (two words where the head
needs them).

**The head and the tail** (COMPUTED by `m2trig.plan_poly`, exact
rationals). The term |c_k| rho^(2k) of each series is, k = 0..9:

| k | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 |
|---|---|---|---|---|---|---|---|---|---|---|
| S | 2^0 | 2^-3.3 | 2^-8.3 | 2^-14.4 | 2^-21.3 | 2^-28.7 | 2^-36.7 | 2^-45.1 | 2^-53.9 | 2^-63.0 |
| C | 2^0 | 2^-1.7 | 2^-6.0 | 2^-11.6 | 2^-18.1 | 2^-25.3 | 2^-33.0 | 2^-41.2 | 2^-49.8 | 2^-58.8 |

- A term above 2^-(G+3) would carry a single word's rounding into the
  bound, so the double-word head covers k = 0..7 of each: K = 8 for S and
  for C at G = 44 and 46. As in M1 (its 2.4), the head's length is set by
  G and not by p.
- The truncation |c_(D+1)| rho^(2D+2) must be under 2^-(p+G+3): D = 12,
  18 and 28 for S and 13, 19 and 29 for C at fp64, fp128 and fp256. Each
  further degree is one FMA.
- A head step is y <- c_k + z y with y and z double words: MUL, the
  product's error by FMA, two FMAs for the cross terms y_h z_l and y_l z_h,
  Fast2Sum against the coefficient (ordered: |z y_(k+1)| <= 0.31 |c_k| for
  C and 0.10 |c_k| for S), and two adds: 9 instructions, M1's step and one
  FMA for z_l.

**r_l's share.** sin(r_h + r_l) = sin(r_h) + cos(r_h) r_l and
cos(r_h + r_l) = cos(r_h) - sin(r_h) r_l to first order; |r_l| <= u |r_h|,
so each correction is one FMA into the low word, and what it leaves out,
sin(r_h) r_l^2 / 2, is below u^2 |r|^3.

**Why no table.** A table of N entries would shrink |r| and shorten the
head, but its rows are double words of sin and cos (4 words an entry, a
SELECT tree each) and each function then needs both addition-formula
products. For N = 8 subintervals of [0, pi/4], |r'| <= pi/64 and the head
shrinks from 8 steps to 4 for each polynomial (COMPUTED as above: 72
instructions saved for the two). The table's cost is an ESTIMATE, not
built: 4 SELECT trees over 9 entries (about 36 instructions with the bit
tests), the split of t into j/16 and a remainder (about 4), and the two
reconstructions, four double-word products and two double-word sums
(about 40): more than the head saves. M1's table paid because exp's
reconstruction is one product (2^(j/8) times 1 + Z).

### 2.5 Selection, the sign, and tan

PROPOSED.

**The quadrant.** n mod 4 lives in the low two bits of an encoding (the
quadrant count is MAGIC + n, a float whose ulp is 1); two IANDs give
b0 = n & 1 and b1 = n & 2, which select:
- sin(|x|): V = b0 ? cos(r) : sin(r), negated where b1;
- cos(|x|): V = b0 ? sin(r) : cos(r), negated where b0 XOR b1;
- tan(|x|): N/D with N = b0 ? cos(r) : sin(r), D = b0 ? sin(r) : cos(r),
  negated where b0.
The negation is an IXOR of both words with a sign word built from the
bits (one or two shifts and an IXOR), XORed again with x's sign for sin
and tan. Two SELECTs a double word.

**tan by a quotient of its own, not by C4's division.** C4's division
routine (`routines.fragment("div", ...)`, 177 to 191 instructions) takes
two single words and returns the correctly rounded quotient: tan needs the
quotient of two DOUBLE words to 2^-(p+G), which rounding sin(r) and
cos(r) to single words first would lose (each rounding is 2^-p). The
design's quotient: RECIP_SEED of D_h (8.5 bits), Newton steps
y <- y + y (1 - D_h y), two FMAs each, doubling 8 bits until at least
p + 8 (3 steps at fp64, 4 at fp128, 5 at fp256); q_h = N_h y; the
remainder N - q_h D by FMA, with N_l and D_l; q_l = remainder y; Fast2Sum.
MEASURED: 19, 21 and 23 instructions with the sign's two IXORs (fp64,
fp128, fp256), about a ninth of a division routine. Its error is the
Newton step's and the remainder's, about u^2 relative, and enters the
budget (3.2).

### 2.6 The final rounding, the test and the clamp

PROPOSED, M1's 3.1 with two changes.
- **Bv = 2^-(p+G) |V_h|**, by ABS and a MUL with a power of two: V is
  negative for half the lanes, and the test's lo_dn = RD(V_l - Bv) and
  lo_up = RU(V_l + Bv) must enclose the true value whatever its sign.
- R = rnd(V_h + V_l), R1 = rnd(V_h + lo_dn), R2 = rnd(V_h + lo_up); a lane
  with R1 != R2 (IXOR, as a SELECT's condition) is marked: its flag word
  is inexact with bit 7 (0x90) in place of inexact (0x10), one SELECT
  between two constant words, since the main path's flags are always
  exactly inexact (no underflow and no overflow can reach it: 4).

**The clamp** (sin and cos). transcend.py answers a value inside the half
gap below 1 by its side (1.3), and so must the routine, or every argument
near a multiple of 2pi, where cos(r) = 1 - r^2/2 sits inside Bv of 1,
would mark under rtz, rdn and rup. The same theorem is in-lane: the true
value T satisfies -1 < T < 1, so its rounding lies within
[rnd(-1 + tiny), rnd(1 - tiny)], two constant words for the program's
attribute (1 under rne, rmm and rup, 1 - 2^-p under rtz and rdn, and
their mirrors). The routine takes R1 = MAX(R1, L1), R2 = MIN(R2, U1) and
the guess clamped the same way: 4 instructions. The pools' arguments near
multiples of pi/2 and 3.5's near family measure it: no such argument
marks. Without the clamp, 16 lanes of the plants' pool slice (which runs
rne and rtz) mark that the routine does not, sin's and cos's under rtz,
the first sin at 0x597e3ca9b6c655cb (the clamp-off plant, section 8).
Under rne and rmm the clamp's words are +-1 themselves and change
nothing; it acts under the directed three.

### 2.7 fp32

Logan's answer to M1's question 2 set fp32's library at G = 40, by a
triple word (ROADMAP, "Logan's answers", 2026-10-12). This model builds
fp32 in double words only, which is MEASURED below; the triple word is an
ESTIMATE.

**The double word reaches G = 18 at fp32 and no further** (MEASURED,
`fp32_guard.py`, the plan and the three fragments built at G = 16, 18,
20, 22, 30 and 40: every static proof holds at 18; at 20 and 22 the mid
sum's low word is not provably exact, at 16 and 30 a straddling piece
is out of its split's range, and at 40 there is no plan, since the exact
combination would need b <= 2p + 1 + beta = -7). It is M1's finding for
exp (its 2.5): a double word at p = 24 floors near 2^-44.7. That G = 16
fails where 18 holds says the plan searches b for the coarse sum but not
the bottom for the splits' range; a plan that searched both might
recover 16, but nothing past the floor. At G = 18 (`costs.py`,
`pools_run.py`, `onseq.py`, `specials.py`, `census.py`, `rate.py` at
fp32):
- sin 348, cos 344 and tan 359 instructions; 74 to 78 bank words a
  function and 82 for all three; 22 values live; b = 15, L = 8, 17 words
  of 2/pi for the whole range (|x| < 2^128); S with K = 4 and D = 6, C
  with K = 5 and D = 7;
- the reduction 216 of sin's 348 (window 47, products 29, mid 44, lower
  41): fp32's narrow word holds less of 2/pi, as the reduction's trend
  across the formats says (5.1);
- the pools (760 arguments, all 15 configurations): 0 wrong, on the model
  and as programs on seq.py; cos marks 2^-12 and 3 2^-12 under rne and
  rmm and 2^-11 and 2^-10 under the directed three, both signs, every
  guess right; the specials row by row equal to transcend.py;
- **the bound** (`m2budget.py` at fp32, 1,500 lanes in each of 3.2's five
  regions): 0.33 to 0.39 Bv for sin and cos, with a residual of 0.012 at
  most, and 0.53 to 0.61 for tan, whose residual adds up to 0.12 more
  (0.73 Bv at the edge). The largest errors measured are 0.19 Bv for sin
  and cos and 0.24 for tan (`m2measure.py`, 6,000 arguments a function,
  0 wrong). sin and cos keep about 1.3 bits and tan under half a bit:
  the double word holds at G = 18, at its floor;
- a mark rate of 2^(0.53 - 18) = 2^-17.5 a call (COMPUTED), about one in
  185,000.

**The triple word at G = 40** (not built; ESTIMATE, counted from the
design's parts):
- **the reduction, about 320 instructions.** The cancellation is 29 bits
  at fp32, and t must be known to 2^-97 absolute, so the exact mid sum
  runs from U <= 2^14 down to a bottom near 2^-56: about 70 bits, which
  no double word holds. The design: each mid piece split at fixed bin
  boundaries (four bins of about 19 bits, each a single word whose sum
  the static proofs show exact), the bins' carries propagated, the top
  bin reduced modulo U, and the bins with the lower double word turned
  into a triple word by two VecSum passes. The double word's reduction
  is 216;
- **the heads, about 490.** At G = 40, S's terms above 2^-(G+3-p) =
  2^-19 (k = 0 to 3) and C's (k = 0 to 4) need triple-word Horner steps;
  in the double word z = r_0^2 each is about 48 instructions (three
  TwoProds, four TwoSums, the renormalisation; M1's exp32 step, in the
  single word r_0, is 38 by its model), so 9 steps; then 3 double-word
  steps each and tails of one to three FMAs;
- **the rest, about 120:** sin(r_0) and cos(r_0) as triple words, r's
  lower words by the derivative to second order (cos(r_0) delta and
  sin(r_0) delta^2/2, delta = r_1 + r_2), tan's quotient in triple words
  (about 35), the final rounding through round-to-odd of the low words
  (M1's), the test, the clamp, the specials;
- **in all about 930 for sin,** 2.3 times fp64's 406; M1's triple-word exp
  is 2.1 times its fp64 exp. The live count is not estimated: M1's
  triple-word exp keeps 33 to 34, past the 32 registers.

Question 3.

## 3. The error bound and the in-lane test

### 3.1 The test

PROPOSED: M1's 3.1, with Bv = 2^-(p+G) |V_h| and, for sin and cos, the
clamp (2.6). Every rounding is monotone, the true value lies in
[V - Bv, V + Bv] when the bound holds, so its rounding lies between R1
and R2, and where they are equal it IS R1; so are its flags, which on the
main path are always exactly inexact (4). The clamp narrows the interval
by a theorem, not by a measurement, and keeps the property.

**Where the test is not consulted:** the tiny paths, decided by side as
transcend.py decides them; the zeros; the infinities and NaNs. **Where the
lane is marked whatever the test says:** past a stated range (2.3).

### 3.2 The bound, budgeted

MEASURED, by verifier-VM1b's method for M1, ported (`m2budget.py`; M1's
3.2 describes the method): over a region's arguments, the method error M
(the twin run in exact arithmetic against mpmath at 4p + 200 bits:
2/pi's dropped tail, the polynomials' truncation, the constants'
representation, the Newton step's error) at its largest, plus each
rounding's largest CAPACITY, |s_i| ulp(v_i)/2, the most it can add rounded
the worst way. Two extensions, both needed for trig:
- an IXOR of a value with the sign word, or with the quadrant's sign
  carrier, is a negation, continuous, and not data;
- the reduction's error-free phases (setup, window, products, coarse,
  mid) are frozen in the twin: their instructions are exact or capture
  their rounding exactly, and the audit checks each claim lane by lane;
  freezing them keeps the twin's modular bookkeeping (quotients chosen by
  the original's roundings) consistent. The first port, which recomputed
  a TwoProd's product exactly under a frozen quotient, gave a method
  error of 2^+822 Bv on four lanes: the twin had moved by multiples of
  the modulus. The lower sum and everything after it are budgeted.

A third, found by the model's own budget and fixed (3.6, item 7): a
RECIP_SEED's output is data, but its source is not; the first version
froze tan's denominator D_h as the seed's operand and lost D's low word,
a bound of 2^+46.7 Bv against a measured error of 0.048 Bv.

The budget's bound is a bound as far as the sample reaches the region's
extremes (M1's 3.2): the regions are placed where the bound binds,
|r| near pi/4 (the polynomials' truncation), x near multiples of pi/2
(the reduction's cancellation, sin's and cos's small results), small
arguments (r = x), and arguments random in every bit. What first order
leaves out, E - (M + the roundings' terms), is measured beside it.

MEASURED (`m2budget.py`, rne; "edge" is x within 3 ulps of
(k + 1/2) pi/2, k odd and random in the range's bits, so |r| is near
pi/4; "near" within 3 ulps of k pi/2, k odd, so r is small and the
cancellation deep, where cos is small and tan large; "zero" the same at
even k, where sin and tan are small; "small" |x| from the tiny gate to 4;
"random" every bit random, the exponent uniform over the range; each
region's lanes, then the budget's bound in Bv, sin, cos and tan):

| region | fp64, G = 44 (1,500 lanes) | fp64, G = 46 (1,000) | fp128, G = 46 (400) | fp256, G = 46 (400) |
|---|---|---|---|---|
| edge | 0.070, 0.066, 0.096 | 0.264, 0.258, 0.362 | 0.073, 0.073, 0.068 | 0.166, 0.166, 0.145 |
| near | 0.065, 0.066, 0.092 | 0.261, 0.259, 0.351 | 0.071, 0.070, 0.067 | 0.103, 0.110, 0.094 |
| zero | 0.062, 0.065, 0.093 | | 0.061, 0.068, 0.065 | 0.140, 0.128, 0.124 |
| small | 0.061, 0.062, 0.088 | | 0.004, 0.026, 0.026 | 0.027, 0.053, 0.049 |
| random | 0.067, 0.066, 0.091 | | 0.061, 0.054, 0.058 | 0.140, 0.108, 0.129 |
| the residual, at most | 0.0014; tan 0.0125 | 0.0057; tan 0.049 | 4e-20 | 2e-57 |

The zero region was added after the first runs: the sampler's near
region held odd multiples only, so sin's small results next to k pi were
budgeted in no region until then (the pools and the census held them;
3.3, 3.5).

- **Every region budgeted keeps more than two bits** (a bound under a
  quarter of Bv, M1's planners' line) at G = 44 at fp64 and at G = 46 at
  fp128 and fp256: at most 0.096 Bv at fp64 (tan, the edge; 0.106 with
  its residual), 0.073 at fp128, 0.166 at fp256.
- **At G = 46 fp64 keeps less than two bits:** 0.26 Bv for sin and cos
  and 0.36 for tan, with residuals of 0.006 and 0.049. The bound holds,
  with about 1.3 bits for tan; M1's question 1 chose G = 44 at fp64 for
  the same reason, and these numbers agree with it (question 4).
- **What makes the bound.** At fp64 the largest share is C's tail, whose
  first term (k = 8, 2^-49.8 at rho) rounds in a single word: 0.015 Bv
  of capacity at G = 44; then sin(r) and cos(r) (0.008), the reduction's
  scaling by pi/2 (0.006), the heads; tan adds its quotient (0.020). At
  fp128 and fp256 every rounding past the tails is below 1e-19 Bv, and
  the bound is the tail's rounding (0.059 Bv) and the method error M,
  which at fp256 is S's and C's truncation (0.104 Bv at the edge, inside
  the plan's 2^-(p+G+3)).
- **The residual** is the second-order part, measured beside the bound
  on the same lanes, not bounded: 0.0125 Bv at most at fp64 G = 44 (tan,
  whose quotient's Newton step is quadratic), and negligible at fp128
  and fp256.
- Each bound comes from a sample. **The box's larger budgets**
  (MEASURED: the lead's run of `box_m2s.sh` at dc6e0bd on amd-arc-box,
  16:44 to 17:50 on 2026-10-13, the same five regions at 12,000 lanes
  at fp64 and 3,000 at fp128 and fp256, seeds 121 to 125;
  `box-out/budget-*.out.txt`): at most 0.100 Bv at fp64 (tan at the
  edge, its residual at most 0.0147), 0.0729 at fp128 and 0.1663 at
  fp256 (sin and cos at the edge). They bound every error 3.3 measured;
  the study's own bounds miss three cells (3.3).

### 3.3 Measured against it

MEASURED (`m2measure.py`, rne). Each figure is the largest
|V - f(x)| / Bv found over the lanes whose answer is the main path's, a
lower bound on the true worst; f(x) is mpmath at 4p + 200 bits. Every
lane was also compared with transcend.py, bits and flag word: 0 wrong
unmarked in every run.

| sin, cos, tan | random | edge | near | zero | small | the pools' main lanes |
|---|---|---|---|---|---|---|
| fp64 | 2^-5.11, -5.13, -4.57 (2,000) | -4.94, -4.95, -4.35 (1,000) | -4.98, -5.12, -4.43 (1,000) | -5.14, -5.08, -4.43 (1,000) | -5.75, -5.48, -4.96 (1,000) | -5.09, -5.07, -4.55 (2,253) |
| fp128 | -4.11, -4.03, -4.11 | -3.91, -3.97, -3.97 | -4.42, -4.75, -4.50 | -4.18, -4.66, -4.32 | -6.14, -6.97, -6.25 | -5.58, -7.76, -5.62 (57) |
| fp256 | -3.47, -3.36, -3.03 | -3.23, -3.23, -2.80 | -3.29, -3.32, -3.39 | -3.59, -3.29, -3.11 | -5.28, -7.04, -5.26 | -5.18, -8.46, -5.34 (36) |

- The pools' arguments are mostly marked or special at fp128 and fp256
  (past the stated range, 282 to 293 of about 615), so their main lanes
  are few there.
- **Three of the 45 cells with a budget of their own** (five regions,
  three functions, three formats) **pass the study's own bound** (3.2):
  fp128 cos random, 2^-4.03 = 0.0612 Bv against 0.0541; fp128 sin small,
  2^-6.14 = 0.0142 against 0.0036; fp256 tan near, 2^-3.39 = 0.0954
  against 0.0941. The 400-lane budgets and the sparse "small" region
  missed lanes near |r| = pi/4. **The box's larger budgets (3.2) bound
  every cell** (COMPUTED from the outputs): those three at 0.0724,
  0.0679 and 0.1391 Bv. fp256's tan at the edge comes closest, 2^-2.80
  = 0.144 Bv against 0.1453 (the budgets' own lanes: 0.143 at 400 and
  0.144 at 3,000). There the bound is nearly attained: the method error
  and the roundings' worst cases meet on one lane, as the budget
  assumes they may.
- **The reduction's cancellation does not show** in the near and zero
  regions, whose largest errors are no larger than the random ones: the
  reduction is exact through it (2.2), and r's relative error stays at
  2^-7.9 of the bound at fp64 (2.2's table).
- **fp32** (the double word, G = 18; `measure.fp32-*.out.txt`): random
  2^-2.52, -2.86, -2.47 (sin, cos, tan), edge -2.43, -2.39, -2.08, near
  -2.67, -2.67, -2.39, zero -2.94, -2.79, -2.39, small -2.61, -2.91,
  -2.60; 0 wrong. Its budget is in 2.7: the double word at its floor.

### 3.4 How often a lane is marked

COMPUTED, then MEASURED.
- **The law, lane by lane.** M1's 3.4: a lane is marked when its true
  value lies within Bv of a rounding boundary, one boundary an ulp under
  every attribute, so P = 2 Bv / ulp(V) = 2^-G sig(V), sig(V) the
  result's significand in [1, 2). M1 averaged sig over a binade with the
  result spread evenly in log scale, 1/ln 2, for 2^(0.53 - G). sin's and
  cos's values are not spread so: they crowd toward +-1, where sig is
  near 2. So `rate.py` prints both, M1's constant and the sum over the
  lanes of each lane's own 2^-G sig(V).
- **Measured,** with the bound inflated to G' = 6 so that marks are
  common enough to count, rne and rtz, random arguments (`rate.py`;
  seed 3, 2,000 arguments a format, the three functions; seed 5, 6,000
  at fp64 and 3,000 at fp256, sin and cos):

  | marked (each lane's own prediction) | sin, rne / rtz | cos, rne / rtz | tan, rne / rtz |
  |---|---|---|---|
  | fp32 (G = 18 design) | 57 / 32 (49.3) | 46 / 56 (50.8) | 50 / 35 (45.2) |
  | fp64 | 34 / 46 (49.8) | 68 / 40 (50.3) | 41 / 46 (45.1) |
  | fp128 | 44 / 38 (49.5) | 45 / 64 (50.1) | 45 / 40 (44.9) |
  | fp256 | 38 / 47 (49.8) | 56 / 67 (49.3) | 56 / 43 (45.7) |
  | fp64, 6,000 | 137 / 164 (149.5) | 135 / 165 (151.8) | |
  | fp256, 3,000 | 79 / 71 (74.6) | 88 / 80 (73.6) | |

  - Every marked guess was right, and no unmarked lane was wrong, in
    all 30 cells.
  - Each cell lies within 2.5 sigma of its own prediction; M1's constant
    misses the fp64 cos cell by 3.4 sigma and fp256's cos rtz by 3.3.
  - The predicted rate is about 2.5% for sin and cos and 2.25% for tan:
    sig(V) averages about 1.59 for sin's and cos's values and 1.44 for
    tan's (COMPUTED from the predictions), against M1's 1/ln 2 = 1.443.
  - **Pooled, sin marks 787 against 844 predicted (-2.0 sigma) and cos
    910 against 852 (+2.0 sigma);** tan 356 against 362, and all three
    together 2,053 against 2,058 (COMPUTED from the table). The same
    arguments serve sin and cos, whose values have the same distribution,
    so the law predicts the same rate for both. Whether their opposite
    departures are real is not settled at this size. The first version
    of `rate.py`, which printed M1's constant only, gave the same counts
    at seed 3 (`rate.*-first.out.txt`; the model is deterministic),
    which is how the departure was first seen.
  - **At the box's size they do not persist** (MEASURED, the lead's
    box run, `box-out/rate-*.out.txt`: seed 7, 50,000 arguments at
    fp64 and 20,000 at fp128 and fp256, rne and rtz): each of its 18
    cells within 1.0 sigma of its own prediction, every guess right,
    0 wrong; pooled, sin 4,508 against 4,500.0 (+0.12 sigma), cos 4,517
    against 4,496.4 (+0.31), tan 4,064 against 4,069.2 (-0.08)
    (COMPUTED from the outputs).
- **At the proposed G** (COMPUTED): sin and cos about
  2^-G x 1.59 = 2^(0.67 - G) a call, 9.0 x 10^-14 at G = 44 and
  2.3 x 10^-14 at G = 46; tan about 2^(0.53 - G). The structured
  families (3.5) come on top, and the lanes past a stated range (2.3).
- **Over the pools** (MEASURED, all 60 configurations): no random lane
  marked. The marks were the structured lanes of 3.5 and the past-range
  lanes at fp128 and fp256.

### 3.5 The structured families

Some arguments sit next to an exact case, x near 0, where sin x and tan x
are about x and cos x about 1: their true value then lies closer to a
rounding boundary than the bound resolves. The routine marks them; a
replay decides them. The other family the brief names, the arguments
nearest multiples of pi/2, has no exact case near it, and the nearest
arguments themselves mark none; but at fp128 and fp256 their neighbours
do (below).

MEASURED (`census.py`): the tiny family, +-c 2^-e for c = 1 to 16 and e
from (p + G)/4 - 4 up to the tiny gate; the near family, the
representable numbers nearest k pi/2 for k = 1 to 64 with two neighbours
each side, both signs, and the deepest cancellations of the stage's own
sweep (pi_worstcase), within the stated range. Every lane against
transcend.py, all five attributes:

| tiny family | arguments | sin: rne and rmm; the directed three | cos | tan | wrong |
|---|---|---|---|---|---|
| fp32 (G = 18) | 144 | 2; 0 | 6; 6 | 0; 0 | 0 |
| fp64 | 144 | 0; 2 | 0; 14 | 2; 0 | 0 |
| fp128 | 384 | 0; 84 | 0; 244 | 6; 78 | 0 |
| fp256 | 880 | 0; 270 | 0; 740 | 6; 264 | 0 |

- Every marked guess was right.
- **The near family: 0 marked** at every format, function and attribute
  (688 arguments at fp32 and fp64, 676 at fp128 and fp256), 0 wrong. The
  cancellation is the reduction's to carry (2.2), and it does.
- **The neighbours of the nearest arguments mark** at fp128 and fp256
  (verifier-VM2S's family, found in its check; MEASURED here,
  `census.py` FAMILY minnbr: the minimiser m0 of every binade and m0 + j
  for j = -4..4, positive, all five attributes, every lane against
  transcend.py). fp128, binades 40 to 90 (459 arguments): sin marks 48
  under each directed attribute (binades 56, 57, 59, 60, 61 and 64), cos
  36 (54, 55, 58, 62, 63 and 65). fp256, binades 100 to 210 (999): sin
  156 (26 binades from 116 to 188), cos 254 (36 from 117 to 186). None
  under rne and rmm, none for tan, none at fp32 (binades 0 to 40) or
  fp64 (0 to 80); the minimisers alone (j = 0) mark none; every guess
  right, 0 wrong. The cause, in VM2S's words: with r = j ulp(x) + delta
  and |delta| tiny, (j ulp)^2/2 lies on the result's grid below 1 once
  E is at least about p/2. That is the tiny family with (j ulp)^2/2 in
  the place of x^2/2: sin marks next to odd multiples and cos next to
  even ones, where each is about +-cos r (COMPUTED). The window beyond
  |j| = 4 is not measured.
- **Which arguments mark** (COMPUTED). sin x = x - x^3/6 + x^5/120 ...:
  where x^3/6 is a whole number of x's ulps, x - x^3/6 is a grid point
  (the directed attributes' boundary); where it is an odd number of half
  ulps, a midpoint (rne's and rmm's). sin x then lies x^5/120 from the
  boundary, inside the bound while x^4 < 120 2^-(p+G). For x = c 2^-e
  the first needs 3 | c and e at most about (p - bitlen(c))/2, the
  second e above about bitlen(c) + (p + G - 7)/4: so bitlen(c) below
  about (p - G + 7)/6. That is c = 3 at fp64 (3 2^-25 under the directed
  three, as measured) and at fp32 (3 2^-11, a midpoint, under rne and
  rmm), but c up to about 2^12 at fp128 and 2^33 at fp256. tan is the
  same with x^3/3 and 2x^5/15. cos x = 1 - x^2/2 + x^4/24: x^2/2 is a
  whole number of the grid's steps below 1 when 2e + 1 <= p, and an odd
  number of half steps when 2e = p; the lane marks while
  x^4 < 24 2^-(p+G), so log2(c) below about (p - G + 3)/4. That is c = 1
  to 7 at fp64 under the directed three and none under rne and rmm (p is
  odd), as measured, and c up to about 2^17 at fp128 and 2^48 at fp256.
- **So the census is a sample at fp128 and fp256,** not the family: its
  c <= 16 holds a few of the centres, as M1's census did (M1's 3.5).
- **Each centre is a window.** A neighbour x + j ulp(x) moves the true
  value's distance from the boundary by about j ulp(x) x^2/2 for sin,
  j ulp(x) x^2 for tan, and j x ulp(x) for cos, which is much less than
  the value's ulp (COMPUTED). So it marks too while that stays inside
  Bv: |j| up to Bv / (ulp(x) x^2/2) for sin, Bv / (ulp(x) x^2) for tan,
  and Bv / (x ulp(x)), about 2^(2e - G - 1) at x = 2^-e, for cos.
  MEASURED (`window.py`, every neighbour against transcend.py, each
  marked guess right and no unmarked lane wrong):

  | centre | neighbours tried | marked | COMPUTED half-width |
  |---|---|---|---|
  | fp64 sin, 3 2^-25, rtz | j = -40..40 | 21, j = -9..11 | 10.8 |
  | fp64 tan, 3 2^-26, rne | -40..40 | 43, j = -23..19 | 21.6 |
  | fp64 cos, 2^-26, rtz | -400..400 | 384, j = -255..128 | 128 above, 256 below (the finer ulp) |
  | fp32 cos, 2^-12, rne | -100..100 | 96, j = -63..32 | 32 above, 64 below |
  | fp32 sin, 3 2^-11, rne | -40..40 | 6, j = -2..3 | 2.7 |

  At fp256 a cos window at 2^-e holds about 2^(2e - 47) arguments each
  side (COMPUTED), about 2^189 at e = 118, the last exponent whose x^2/2
  lands on the grid below 1: whole windows, as M1 found for exp near 0
  (its 3.5).

Section 9, question 7, asks to keep these marks, as M1's question 4 did.

### 3.6 What the model found wrong in itself

MEASURED, each in the round's ledger; every run this study cites was made
after the fix it needed, on the final model (section 11 says how that is
held). Each is a check for M2's build (section 8):
1. **The reduction is of |x|.** M is the encoding's significand without
   its sign, and the first harness compared the reduction with x 2/pi:
   every failure was a negative argument. The design applies x's sign
   with the quadrant's, to the double word V before its one rounding,
   since rdn and rup are not symmetric (2.5).
2. **fp128's coarse sum was not provably exact at b = 109.** A chunk with
   leading zeros at the window's second position makes P_1's grid finer
   than the plan assumed; the generator's static proof failed (an
   assertion, before any lane ran: `redcheck-first.out.txt`, between its
   fp64 and fp256 lines), and the plan now searches b downward: 108 at
   fp128. The generator's own proofs are part of what M2's build ports
   (8, item 2).
3. **fp128's cancellation was the docs' sampled figure.** The plan first
   sized fp128's reduction with 121 bits (docs/TRANSCENDENTALS.md, every
   16th binade of fp128's whole range); pi_worstcase's own search over
   every binade of the stated range [1, 2^1024) found 123 (1.4). A
   sampled worst is only a lower bound, and here it sizes the window: the
   plan now takes the range's measured figure. fp256's range reaches 244,
   within the 245 used.
4. **A stated range below 2^p** leaves the window's first position
   without a chunk in every bucket; the first generator assumed it had
   one and failed for 2^128 at fp256 (`ranges.py`). Positions without a
   chunk now contribute nothing. The default fragments are unchanged by
   the fix: their counts are the costs run's from before it (MEASURED),
   and the fix acts only where a position has no chunk in any bucket,
   which no default plan has (COMPUTED: the last bucket is 22, 8 and 3 at
   fp64, fp128 and fp256, so position 0 holds c_0 there).
5. **The live count:** the first version computed the classification and
   the reduction's powers of two before the window, 35 to 37 values live
   at fp64; emitted after, 26 (5.1).
6. **The budget's first port** recomputed a TwoProd's product exactly
   under a frozen modular quotient, and gave a method error of 2^+822 Bv
   (3.2). The reduction's error-free phases are frozen whole now.
7. **The budget froze RECIP_SEED's source.** Every non-arithmetic
   instruction's operands were frozen as data, so tan's denominator D_h
   stayed rounded in the twin while D's low word was recomputed: a bound
   of 1.17 x 10^14 Bv (2^+46.7) at fp64 against a measured error of
   0.048 Bv. A seed's output is data and its source is not; fixed, and
   the four fp64 tan regions run again (0.088 to 0.096 Bv). M2's build
   ports the budget with tan's quotient in it, so its test is a tan
   region whose bound is near its measured error.
8. **The audit's arguments missed a planted fault.** The exact-add plant
   (a TwoSum the static proofs need, replaced by a plain add still
   claimed exact) passed the pools, random arguments and the deepest
   cancellations: the add is inexact only when the piece P_2 lies within
   |rho_1| of a binade's top. The products' binade edges (`m2edges.py`,
   2.2) find it; they are now in the audit's arguments, in `redcheck.py`
   and in section 8's item 2.
9. **The budgets' near region held odd multiples of pi/2 only,** where
   cos is small; sin's small results next to k pi were in no budgeted
   region. The zero region (even multiples) was added and budgeted (3.2).
   The pools and the census held such lanes throughout.

## 4. The specials and the flags

PROPOSED, and MEASURED equal to transcend.py, bits and flag word, row by
row (`specials.py`: both signs of each row's arguments, every function,
all five attributes, fp32's double word, fp64, fp128 and fp256: nine
rows of arguments a function), and over the pools (3.3).
Rows are in the routine's order of priority, highest first; "main" is
sections 2.2 to 2.6. The gates are 2^-27 for all three at fp64, 2^-57 at
fp128 and 2^-119 at fp256 (sin's and cos's coincide there; at fp32 sin's
is 2^-12 and cos's and tan's 2^-13).

**sin:**

| operand | result | flags |
|---|---|---|
| NaN | the canonical quiet NaN | invalid if signalling |
| +inf, -inf | the quiet NaN | invalid |
| +-0 | the operand | none |
| \|x\| below the gate, subnormals included | x (1 - 2^-(p+2)) rounded once: x, or its neighbour toward zero under rtz and the directed attribute toward zero | inexact; + underflow where the result is below 2^emin |
| \|x\| >= 2^R (fp128, fp256) | the main path's guess, meaningless | inexact, marked |
| main | R | inexact; + 0x80 where marked |

**cos:**

| operand | result | flags |
|---|---|---|
| NaN | the quiet NaN | invalid if signalling |
| +inf, -inf | the quiet NaN | invalid |
| +-0 | 1 | none |
| \|x\| below the gate | 1 under rne, rmm and rup; 1 - 2^-p under rtz and rdn (a constant word) | inexact |
| \|x\| >= 2^R | as sin | inexact, marked |
| main | R, clamped (2.6) | inexact; + 0x80 |

**tan:**

| operand | result | flags |
|---|---|---|
| NaN | the quiet NaN | invalid if signalling |
| +inf, -inf | the quiet NaN | invalid |
| +-0 | the operand | none |
| \|x\| below the gate | x (1 + 2^-(p+2)) rounded once: x, or its neighbour away from zero under the directed attribute away from zero | inexact; + underflow where \|x\| is below 2^emin |
| \|x\| >= 2^R | as sin | inexact, marked |
| main | R | inexact; + 0x80 |

**The tiny paths are one FMA under the program's attribute,** whose value
lies strictly inside the half gap transcend.py's witness names (an eighth
of a gap from x there; here x 2^-(p+2) from it, within the half gap at a
power of two and everywhere else), so it rounds as the witness does under
every attribute. Underflow is tininess after rounding: for sin, the
result below 2^emin (min normal under rtz goes to the largest subnormal
and underflows; under rne it stays min normal and does not); for tan, the
argument below 2^emin (the largest subnormal under rup becomes min normal
and still underflows, since the true value is tiny), as the specials run
measured row by row.

**The flag word** is a SELECT chain of constant words, so C4's own walk
(`routines.flag_words`, no IOR rule needed) proves its values: {0x0,
invalid, inexact, underflow|inexact, inexact|0x80} for sin and tan, and
cos without underflow (MEASURED by `costs.py` on all 60 fragments; the
pools saw exactly 0x0, 0x1, 0x10, 0x18 and 0x90). It is within
mathlib.py's FLAG_WORDS. Never bits [6:5]. The main path raises exactly
inexact: no lane past the tiny gate has a result below 2^emin (|sin x| and
|tan x| are at least about |x| or |r|, and |r| >= 2^-(lost+1) pi/2), and
none overflows (|tan x| <= 1/|sin r| < 2^(lost+2) at every format).

## 5. The cost

### 5.1 Measured

MEASURED (`costs.py`; the fragment's body; inlined, a call adds QUIET,
ENDQUIET and RAISE, 3 more; every attribute gives the same counts):

| | fp64 | fp128 | fp256 |
|---|---|---|---|
| sin | 406 | 382 | 389 |
| cos | 402 | 378 | 385 |
| tan | 419 | 397 | 406 |
| sin and cos of one argument, shared (2.1) | 434 | 411 | 418 |
| sin, cos and tan of one argument | 475 | 455 | 464 |
| bank words, a function | 104-108 | 101-105 | 115-119 |
| bank words, all three, five attributes | 111 | 108 | 122 |
| of them, 2/pi's table | 30 | 15 | 10 |
| most values live | 26 | 17 | 16 |
| scratch slots | 0 | 0 | 0 |
| range | all | 2^1024 | 2^1024 |

**By part:** 2.2's table (sin under rne). fp32's double word at G = 18 is
in 2.7: sin 348, cos 344, tan 359, 82 words for all three, live 22.

The double-word heads are the largest single part, 139 instructions for
the two polynomials at every format, as M1's exp's head was its largest;
the tails grow with p (9 FMAs at fp64, 21 at fp128, 41 at fp256 for the
two), and nothing else does. The reduction shrinks with p instead
(206, 168 and 155 at fp64, fp128 and fp256), because the wider word holds
more of 2/pi: 30, 15 and 10 words, read through a shifter of 5, 4 and 3
levels.

**Live values.** The peak is the window's first shifter level at fp64
(26) and fp128 (17), the products at fp256 (16). The classification is
emitted after the final rounding, and the reduction's powers of two and M
after the window, to keep them out of those ranges: the first version,
with both before the reduction, kept 35 to 37 live at fp64, 26 to 28 at
fp128 and 22 to 24 at fp256 (MEASURED, its pools run,
`pools_run-first.out.txt`). mathlib.py's LIVE_CAP for exp is 23:
section 6 and question 9.

### 5.2 Against the surveyor's estimates

READ (the step-6 survey, part M, 4.2 and 4.5; ROADMAP's step 6, M2;
CERT-V2's 7.1) against MEASURED and COMPUTED:

| | the estimate | this design |
|---|---|---|
| sin/cos instructions, fp64, full range | about 250 | 402-406; 434 for both of one argument |
| sin/cos instructions, fp256 | about 1,500-2,500, range-limited | 385-389 to 2^1024 |
| 2/pi at fp64, full range | about 1,200 bits, about 23 words | 1,232 bits in 28 words of 44 bits, and 2 zero words |
| 2/pi at fp256 to 2^1024 | about 1,300 bits, five or six constants | 1,864 bits in 8 words of 233 bits, and 2 zero words (2.3) |
| where they live | a per-lane scratch copy, read by LDX | the bank, read by a SELECT shifter; LDX the alternative (5.3) |

The fp256 figure moves furthest for M1's reason: the double-word head is
set by G, not p, and the reduction's words grow with p, so fp256 costs
about what fp64 costs.

### 5.3 The alternatives

**The window by LDX from a scratch copy** (COMPUTED from the built
fragments, `costs.py`: the shifter's instructions replaced by L stepped
LDXs from a copy of the table at slots 0 to K-1; the shift's encoding
already holds the slot in its low bits, since MAGIC's low bits are zero):

| | fp64 | fp128 | fp256 |
|---|---|---|---|
| sin by the SELECT shifter | 406 | 382 | 389 |
| sin by LDX | 351 | 352 | 372 |
| the window's time, ALU instructions (an LDX at the census's s, 5.21 at fp64 and 5.08 at fp256) | 61 against about 31 | 35 against about 26 | 22 against about 25 |
| slots a lane, filled each run | 30 | 15 | 10 |

At fp256 the LDX window is not faster: five loads cost more than 22
SELECTs. At fp64 it saves 55 instruction words and about 30 ALU
instructions' time a call, about 7%, for 30 slots a lane, their fill
(30 STLs from a register, each word copied from the bank first: about 60
instructions a run, or the SCRATCH_IO preload) and the compiler work of
M1's 5.3. Question 1.

**Design B,** the mid pieces summed with the double word's accuracy and
the reduction's absolute error, about 2^-104 at fp64, carried into the
in-lane bound as an absolute term (the deepest cancellations would then
mark). MEASURED as built (`costs.py`, the same generator with
variant B): 411, 381 and 388 instructions, against A's 406, 382 and 389,
before the bound's extra term: its sum without A's structure takes more
TwoSums at fp64, and A's exact structure costs at most one instruction
more at fp128 and fp256. A decides every lane, so B is not proposed.

**A table** (2.4): not built; its cost, an ESTIMATE, exceeds what it saves.

**Augmented addition, once every image carries R21** (COMPUTED from the
fragments' error-free transformations, `costs.py`): sin at fp64 holds 7
TwoSums and 18 Fast2Sums (fp128 and fp256: 6 and 18); augerr and augadd
split a sum in 2 instructions against 6 and 3, which saves 7 x 4 + 18 =
46 instructions at fp64 (11%) and 42 at fp128 and fp256. As in M1, the
quad is built without R21 (revision 8's question 9), so TwoSum is what
every image runs; the magic-number splits keep their own roundings and
are unchanged.

**G = 46 at fp64** (MEASURED: `pools_run.py` at G = 46, rne and rtz;
`m2budget.py` at G = 46, 3.2): sin 414, cos 410 and tan 427
instructions, 8 more each than at G = 44, 107 to 111 words and 27 values
live; over the pools 0 wrong, with the same marks. By the budget the
bound is 0.26 Bv for sin and cos and 0.36 for tan at G = 46, against
0.07 and 0.10 at G = 44: fewer than two bits of margin, for a mark rate
four times smaller. M1's question 1 weighed the same and chose 44; this
design agrees (question 4).

## 6. The language and the compiler

PROPOSED, in C4's, L4's and M1's pattern (M1's section 6 has the
machinery; this section says what M2 adds).

**The nodes.** `sin(a)`, `cos(a)`, `tan(a)`, each with an operand that is
not a constant:
- each becomes a node of the step graph, named as transcend.py names the
  function, with `transcend.sin`, `cos` and `tan` its golden functions
  (bits and flags);
- the interpreter's operation table (`python/cft_golden/lang/interp.py`,
  `_ops`) and the step graph's operation list (`lang/graph.py`, OPS)
  gain three entries; as with div and sqrt, a graph without them writes
  the same bytes;
- `transcendental` stops being raised for these three. The names are
  already reserved (`lang/check.py`, TRANSCENDENTAL).

**What stays refused, and what folds** (M1's question 8, which Logan
settled for M1's six as recommended, applied to these three):
- `sin(0)` and `tan(0)` fold to 0 and `cos(0)` to 1: the exact rational
  cases;
- every other constant argument is `irrational-constant`: sin, cos and
  tan of a nonzero rational are transcendental (Hermite-Lindemann, as
  transcend.py's comment block argues; for tan, a rational tan q would
  make e^(2iq) = (1 + i tan q)/(1 - i tan q) algebraic). No constant is a
  pole of tan (pi/2 is irrational), so nothing here is
  `constant-division-by-zero`;
- a function of a constant that changes with h's size is `h-nonlinear`,
  as `sqrt(h)` is (M1's section 6).

**cftc** (`python/cftc`):
- `ir.ROUTINES` and `routines.ROUTINES` gain sin, cos and tan, arity 1,
  each carried by its fragment from the golden generator (question 11),
  bound to the node's operand, QUIET to ENDQUIET, then RAISE;
- the words are routine bank slots by bit pattern: 111, 108 and 122 for
  all three functions at fp64, fp128 and fp256 (5.1);
- **sharing:** the inliner's hash-consing already makes sin, cos and tan
  of one operand share their prefix (2.1); nothing new is needed for it;
- the internal check holds each instance to its fragment under
  mathlib.py's widened invariants, which these fragments meet with no
  live cap (MEASURED, `costs.py`). Two things are new to routines: MIN
  and MAX inside a fragment (the clamp; C4's and M1's use neither), which
  the build checks cftc's emitter and internal check accept as any
  instruction; and 26 values live at fp64 (question 9);
- the call loop takes a unary routine as it takes sqrt.

**Targets** (READ, `python/cftc/targets.py`): revision 7's targets, the
round-2 images and open-core refuse an image with these routines
`target-feature`, for lack of FLAG_CONTROL, as they refuse C4's and M1's;
the software targets and revision 8's three compile them. The design uses
no scratch slot. The LDX alternative (5.3) would need a fixed region of
30 slots a lane at fp64 (15 at fp128, 10 at fp256), filled each run.

**Versions** (READ: cftc's VERSION 5, the language's (1, 0)):
- M1's build takes cftc's output VERSION from 5 to 6 and the language to
  1.1 (the plan of record); M2's build steps each once more, 6 to 7 and
  1.1 to 1.2, unless the two builds land together. The certificate
  corpus is made again as each step remakes it;
- the language's step is minor: names it refused only for not computing
  them, and no accepted source changes.

**The interpreter needs mpmath** for these nodes, as for M1's (M1's
question 10, accepted); an auditor without it refuses
`definition-unavailable`.

**A marked lane in the language's checks** is replayed by the definition
and its guess compared only as a guess, as M1's section 6 says. The
census of 3.5 lists the lanes that mark on purpose.

## 7. The derivative rules

PROPOSED, in LANGUAGE.md's form ("The rules"; "The quotient and the
root"). Each rule reads a primal value by name where it has one and
writes it again where it has none, and the compiler shares it.

| operation | its tangent | where a tangent is zero | where it is not differentiable |
|---|---|---|---|
| `sin(a)` | `cos(a) * da` | zero | - (at +-inf, cos(a) is a NaN, as the primal is) |
| `cos(a)` | `(-sin(a)) * da` | zero | - |
| `tan(a)` | `fma(r, r, 1) * da` | zero | - (no representable argument is a pole) |

**Rounding order.**
- **sin:** cos(a) is its own correctly rounded routine (written again: it
  has no name), then one product: one rounding of the rule's own.
- **cos:** sin(a) written again, its negation exact and primal-only, so
  shared across vectors as the quotient's -r is; one product a vector.
  Unary minus binds tighter than `*` (LANGUAGE.md, "Expressions and
  operations"), so
  `-sin(a) * da` reads the same; the canonical form writes the brackets.
  The form matters: `-(sin(a) * da)` rounds the product before negating,
  which differs under rdn and rup.
- **tan:** `fma(r, r, 1)`, 1 + tan^2, one rounding, primal-only and
  shared across vectors; then one product a vector: two roundings.
  `da / cos(a)^2` would spend a division routine a vector (C4's, 177 to
  191 instructions); `fma(r, r * da, da)` two roundings a vector with
  nothing shared.

**Cost** (MEASURED, `share.py`): cos(a) beside sin(a) costs 28 to 29
instructions of the primal, not 378 to 402, because the two fragments
share their prefix; so sin's and cos's tangents cost each vector one MUL,
and the step one routine's tail. tan's costs one FMA for the step and one
MUL a vector.

**A marked lane.** The tangent's cos(a) or sin(a) is a routine and may
mark like any other; the language's checks replay it (6).

**How it is held:**
- the rule table to the code, each rule rendered on a one-operation
  system;
- the tangent stage's fourth check by a central difference in high
  precision, as M1's question 10 accepted for M1's functions;
- a committed compiled variational reference. PROPOSED: the pendulum,
  d/dt theta = omega, d/dt omega = -(g/L) sin(theta), under rk4 with a
  tangent vector; its energy, omega^2/2 - (g/L) cos(theta), an exact
  quantity to watch, and both functions in its step. A rule rounded
  otherwise must move its bytes.

## 8. How it will be held

PROPOSED, for M2's build, M1's section 8 item for item; agents run the
quick tests and the long runs are the lead's.

1. **Each fragment on seq.py against transcend.py,** as a stand-alone
   program through `routines.program` and `routines.run`, over the
   stage's radian pool, the vector sets' and test_transcend's brute
   pool, at every format and attribute: every unmarked lane equal in bits
   AND flag word, every marked lane replayed and its guess counted.
   MEASURED as a probe (`onseq.py`): all 60 configurations at fp32 (the
   double word), fp64, fp128 and fp256, 0 lanes differing from the model
   and 0 unmarked lanes differing from transcend.py.
2. **The reduction alone against exact rationals,** the audit of every
   instruction called exact, over random arguments in every bucket, each
   bucket's edge exponents, every power of two, the deepest
   cancellations, and the products' binade edges (`redcheck.py`,
   `m2edges.py`; 2.2). The pools are not the test of the reduction: they
   hold few arguments of each bucket's interior, and the exact-add plant
   passes them (3.6, item 8).
3. **The bound, against an independent reference,** mpmath at 4p + 200
   bits (MPFR where the stage has it), at each region's own worst points:
   |r| near pi/4, x near odd and even multiples of pi/2 (and
   pi_worstcase's minimisers), small x, random x; |V - f| / Bv under 1;
   the margins stated by the budget's bound (3.2), the sampled worst only
   as the lower bound it is. Budgets over larger samples, end-weighted as
   M1's were, are the lead's on amd-arc-box.
4. **The mark-rate law** with the bound inflated, by each lane's own
   2^-G' sig(V) (3.4): every unmarked lane right and every marked guess
   right; at a size that settles sin's and cos's opposite departures
   (3.4), the lead's on amd-arc-box.
5. **The structured families as a committed list:** 3.5's marked
   arguments at every format, by function and attribute, each with
   neighbours inside and outside its window; and the arguments nearest
   multiples of pi/2 with their neighbours, whose marks at fp128 and
   fp256 (3.5) join the list. A mark in the pools off the list fails
   the test, as E1's brief correction 1 made it for exp.
6. **The constants** re-derived with a `--check`, as mathlib.py's are:
   2/pi's chunks against host/src/mp_2opi.h AND an independent derivation
   (test_mp_consts.py's Chudnovsky series is one), pi/2's two words, the
   Taylor coefficients, the gates, the clamp's words, the range's word.
7. **The stated range:** a lane at 2^R and above marked, at 2^R's
   neighbour below decided; the lane's guess not counted.
8. **program.c bit for bit** through `host/tests/seq_check.py`'s
   corpora; no new C.
9. **The language's checks:** the lang-routines stage with sources using
   the three functions, the tangent stage's rules, the committed
   reference (7), test_lang.py's refusal table.
10. **The card later:** STATUS[6] and the lane byte on a structured
    argument (cos(2^-26) under rtz at fp64), and the acceptance set with
    a radian routine case.

**The plants,** each in a fresh fragment and each red in a named case
(`plants.py`, MEASURED at fp64). Its four checks: **pools**, the pool
slice (test_transcend's brute pool, the deepest cancellations, every 16th
power of two, 64 random; 387 arguments) under rne and rtz for the three
functions, red on a wrong unmarked lane or on a mark the unplanted
fragment does not make there (the committed list's part in the slice);
**structured**, 3.5's fp64 centres that must mark (cos at 2^-26, 2^-25,
3 2^-26 and 2^-24 under the directed three, tan at 3 2^-26 under rne and
rmm, both signs); **bound**, |V - f| / Bv past 1 over placed points in
five regions (64 each), mpmath at 4p + 200 bits; **audit**, a claimed-exact
instruction inexact on a lane, over random arguments, the slice and the
1,844 binade edges.

| plant | the fault | red in | a named case |
|---|---|---|---|
| none | the control | nothing | (the slice marks no lane under rne and rtz; largest error 2^-4.52 Bv) |
| chunk | one bit flipped in a stored chunk of 2/pi | pools, bound | sin rne 0x6500000000000000 wrong; 2^106 Bv |
| window | the window read one word late | pools, bound | sin rne 0x3fefffffffffffff wrong; 2^145 Bv |
| mid-inexact | the mid pieces summed with rounding under design A's bound | pools, bound | cos rne 0x79ffce36f3ebfe43 wrong; 2^35.7 Bv |
| exact-add | the mid sum's first TwoSum a plain add, still claimed exact | audit | 27 lanes, the first 0x46167c4c45c1b200, all binade edges |
| quadrant-sign | cos's sign from n's low bit alone | pools, bound | cos rne 0x4008000000000000 (3) wrong; 2^98 Bv |
| clamp-tight | the clamp's ends one ulp inside rnd(+-1 -+ tiny) | pools, structured | sin rne 0x597e3ca9b6c655cb marked off the list; cos rtz 2^-26 unmarked |
| bound-loose | the in-lane bound 2^40 too small | structured, bound | cos rtz 2^-26 unmarked; 2^35.5 Bv |
| mark-silenced | the flag word never carries the mark | structured | cos rtz 2^-26 unmarked |
| coef | S's z^1 coefficient without its low word | pools, bound | sin rne 0x541e146a1edcbc95 wrong; 2^39.9 Bv |
| newton-short | tan's reciprocal one Newton step short | structured, bound | tan rne 3 2^-26 unmarked; 2^17.0 Bv in the zero region |
| tiny-gate-off | no tiny path | pools | sin rne 0x1 (the smallest subnormal) wrong |
| rl-dropped | r_l's share left out | pools, bound | sin rne 0x4570b04fbfd9356e wrong; 2^44.2 Bv |
| zl-dropped | z_l's share in the head left out | pools, bound | sin rne 0xc96f96a1cd67f437 wrong; 2^42.2 Bv |
| clamp-off | no clamp: the definition's beside-one rule switched off | pools | sin rtz 0x597e3ca9b6c655cb marked off the list (16 such) |

- **exact-add was red in nothing** until the audit took the binade
  edges (3.6, item 8): the random arguments, the slice and the deepest
  cancellations hold no lane where its add is inexact.
- **The pools' off-list rule** (E1's) is what turns clamp-tight's and
  clamp-off's extra marks red; before it, the pools counted only wrong
  unmarked lanes, and clamp-off was red in nothing.
- quadrant-sign changes only cos's fragment, newton-short only tan's, and
  clamp-tight and clamp-off sin's and cos's (MEASURED, `plant_diff.py`,
  each plant's fragments against the control's); each is red through a
  function it changes.

## 9. Questions for Logan, each with a recommendation

1. **Where 2/pi lives, and how the window is chosen.** The plan expected a
   copy in each lane's scratch read by LDX. The design reads it from bank
   words by a SELECT log-shifter (2.2): 61 instructions at fp64, 35 at
   fp128 and 22 at fp256 to 2^1024, no scratch slot, no fill, no compiler
   layout. LDX would save 55, 30 and 17 instructions a call (5.3) for a
   region of 30, 15 and 10 slots in every lane, filled each run, and the
   compiler's layout, call loop and certificate version 2's source-shape
   rule taught a fixed region (M1's 5.3 listed the same costs for its
   tables). *Recommended: the SELECT shifter for M2's build, as M1's
   question 3 chose SELECT trees; LDX later if a workload's instruction
   count needs it, or for a range past 2^1024.*
2. **fp128's and fp256's stated range.** *Recommended: 2^1024 for both*
   (2.3): every magnitude an fp64 value has; 15 and 10 bank words of 2/pi;
   22 and 32 instructions above a range of 2^128; past it a lane is
   marked and replayed, which certificate version 2's question 3
   decided. fp128's whole range by the SELECT shifter would keep 137
   values live and take 257 bank words, and fp256's would need 1,181
   words of 2/pi, past the bank; by LDX they are 166 and 1,181 slots a
   lane.
3. **fp32.** Logan set M1's library at G = 40 at fp32, by a triple word.
   This model builds fp32 in double words only, which reach G = 18: sin
   348, cos 344 and tan 359 instructions, 0 wrong over the pools on the
   model and on seq.py, and a mark rate of 2^-17.5 a call, about one in
   185,000; by the budget sin and cos keep about 1.3 bits there and tan
   under half a bit (2.7). The triple word at G = 40 is not built; its
   cost is an ESTIMATE, about 930 instructions for sin, 2.3 times fp64's,
   as M1's triple-word exp is 2.1 times its fp64 exp. *Recommended: the triple
   word at G = 40, one G a format across the library as Logan set it for
   M1, built and measured first in M2's build, its live count against the
   32 registers with it.* The double word at G = 18 is the measured
   alternative, if fp32's trig is wanted before the triple word is
   built, or if that measures far past the estimate.
4. **G.** *Recommended: M1's, 44 at fp64 and 46 at fp128 and fp256 (fp32
   by question 3),* one guard a format for the whole library, so that
   LANGUAGE.md's rule and the mark-rate law are one statement. By the
   budget the bound keeps at most 0.096 Bv at fp64 (tan's edge; 0.106
   with its residual, about 3.2 bits) and 0.073 and 0.166 Bv at fp128 and
   fp256 (about 3.8 and 2.6 bits) (3.2); the box's larger budgets give
   0.100 at fp64 (0.115 with its residual, about 3.1 bits), 0.0729 and
   0.1663 (3.2). At G = 46, fp64 would keep 0.26 to 0.36 Bv, under two
   bits (5.3).
5. **tan.** *Recommended: its own double-word quotient* (2.5), 19 to 23
   instructions after the shared prefix. C4's division takes single words
   and would lose the precision G needs; dividing two routines' rounded
   results would not be correctly rounded.
6. **The clamp** |sin x|, |cos x| < 1 in-lane (2.6). *Recommended: keep
   it*, 4 instructions: it is the definition's beside-one rule, and
   without it a lane whose sin or cos lies within Bv of +-1 marks under
   rtz, rdn and rup (16 lanes of the plants' slice under rtz; 2.6).
7. **The structured families** (3.5) mark and are replayed: whole windows
   of arguments next to an exact case, larger at fp128 and fp256 than at
   fp64, and at fp128 and fp256 under the directed attributes the
   neighbours of the arguments nearest multiples of pi/2.
   *Recommended: keep them, as M1's question 4 did;* list the
   windows' centres in the build's tests; LANGUAGE.md's rule (M1's) covers
   them.
8. **Constants.** *Recommended: as M1's question 8 settled for M1's six:*
   fold sin(0), cos(0) and tan(0); `irrational-constant` for every other
   constant argument; `h-nonlinear` for a function of h (6).
9. **Live values.** fp64's fragments keep 26 values live, past
   mathlib.py's LIVE_CAP of 23 for exp; fp128's 17 and fp256's 16 are
   within it. *Recommended: a cap by function and format in mathlib.py,
   26 for the radian routines at fp64,* as Logan's answer to M1's
   question 12 expected the cap to rise; the LDX window would remove
   fp64's peak (the shifter's first level).
10. **The derivative rules** (7). *Recommended: `cos(a) * da`,
    `(-sin(a)) * da` and `fma(r, r, 1) * da`, the pendulum as the
    committed reference.* The two routines of one argument share their
    prefix, so sin's and cos's tangents cost each vector one product.
11. **Where the generator lives.** *Recommended: mathlib.py,* M1's module,
    with its battery and plants, beside exp and M1's other five.
12. **Versions and order.** *Recommended:* M2's build steps cftc's
    output VERSION and the language's minor version once more after M1's
    build (6 to 7, 1.1 to 1.2), with the certificate corpus made again,
    unless the two builds land together and share one step.

## 10. What M2's build builds, in order

PROPOSED, after the lead's review and Logan's answers:

1. **The golden generator** (mathlib.py, question 11): sin, cos and tan
   at fp64, fp128 and fp256 under every attribute, from the study's model:
   - the reduction's plan with its static proofs (2.2: the coarse sum, the
     splits' ranges, the exact combination), and the audit of every
     instruction it calls exact as a test;
   - every constant derived and checked (`--check`): 2/pi's chunks
     against host/src/mp_2opi.h and an independent derivation, pi/2, the
     coefficients, the gates, the clamp's and the range's words;
   - the fragments held to the invariants, with question 9's cap;
   - section 8's items 1 to 7 and the plants, quick ones in the golden
     stage; the larger bound, rate and census samples go to the lead for
     amd-arc-box.
2. **fp32,** as question 3 decides.
3. **program.c parity:** the fragments' programs in seq_check's corpora.
4. **The language,** golden-first: the three nodes, the folds and
   refusals, the renderers, the L3 rules with the central-difference
   check, LANGUAGE.md, the version step.
5. **cftc:** ROUTINES, the internal check (MIN and MAX inside a routine),
   the targets' refusals, the call loop, VERSION, the corpus, the
   pendulum's committed bytes.
6. **The stages' legs:** lang-routines and tangent with marked lanes
   replayed; VERIFICATION.md's rows.
7. **The card,** on revision 8's images: STATUS[6] and the lane byte on
   a structured argument, and the acceptance set's radian case.

## 11. The model

Scratch made for this study, kept here as `m1/` keeps M1's. It is not the
tree's code, and nothing in the tree imports it. Python with mpmath; run
from this directory, where `m2core.py` puts the repository's `python/` on
the path (and `m2const.py` its `host/tools/`).

| file | what it is |
|---|---|
| `m2core.py` | the SSA builder in C4's Fragment shape (hash-consing through routines.simplify), the counted error-free transformations, the evaluator through softfloat.compute as seq.py's ALU calls it, encodings |
| `m2const.py` | 2/pi's bits from mpmath, held to host/src/mp_2opi.h; pi; the Taylor coefficients |
| `m2plan.py` | the reduction's parameters from the budget, the chunks, the static analysis of every piece; the measured cancellations (LOST) |
| `m2red.py` | the reduction (2.2), its plants, and the audit of its exact claims |
| `m2edges.py` | the reduction's edge arguments: every product next to a power of two (2.2) |
| `m2trig.py` | the routines (2.1 to 2.7) and their plants |
| `m2harness.py` | the radian pools and the comparison with transcend.py |
| `pools_run.py`, `onseq.py` | the pools against transcend.py on the model, and as programs on seq.py |
| `redcheck.py` | the reduction alone against exact rationals, with the audit |
| `m2measure.py`, `m2budget.py` | the error against the bound, sampled and budgeted (verifier-VM1b's method, ported, with its extensions) |
| `rate.py`, `census.py`, `window.py`, `specials.py` | the mark-rate law, the structured families and their windows, the specials row by row |
| `costs.py`, `share.py`, `ranges.py`, `fp32_guard.py` | the cost (with mathlib.py's invariants and C4's flag-word walk), the sharing across sin, cos and tan, a stated range's cost, how far fp32's double word goes |
| `worst_range.py` | pi_worstcase.py's own search over every binade of a stated range |
| `plants.py`, `plant_diff.py` | the plants and the four checks they must turn red; which fragments each plant changes |
| `*.out.txt` | each run's output as captured, named for its script, its format and its region or seed; `-first` marks a run of the first version (classification first, fp128's cancellation at the docs' 121; for `rate`, the script before the per-lane prediction) |
| `queue*.log` | each batch's start and end times, run by run |
| `box_m2s.sh` | the larger samples handed to the lead for amd-arc-box (not run by the study) |
| `box-out/` | that script's outputs as the lead's run captured them: amd-arc-box, dc6e0bd, 16:44 to 17:50 on 2026-10-13, six jobs at a time, all 49 ended 0 |

**Which model the runs measured.** The routines' modules (`m2core`,
`m2const`, `m2plan`, `m2red`, `m2trig`) last changed before the runs this
study cites, except `m2trig`'s fp32 guard and comments, which change no
fp64, fp128 or fp256 fragment. The 45 default fragments (three formats,
three functions, five attributes) hash to one fingerprint before and
after the last batch of re-runs (MEASURED, 361409789c94... both times,
the round's ledger). Where a measuring script gained a mode or a check
after a run (the zero region, the binade edges, the off-list marks, the
per-lane rate), the earlier modes draw the same arguments, and the runs
that needed the new one were made again. The early runs made before the
last change to the plan or the reduction were all made again on the
final code (`queue6.log`). `m2budget.py`'s fix (3.6, item 7) changes
only a fragment with a seed in it, tan's, and every tan budget cited ran
after it.

The runs, their times and the desktop's load are in the round's ledger,
`Data/runs/2026-10-12-math-round/ledger/M2S.md`, which is outside the
tree.
